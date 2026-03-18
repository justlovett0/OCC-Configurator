/*
 * main.c - Pico W Guitar Controller Dongle Firmware
 *
 * Simple wireless dongle: BLE passive scan → XInput Guitar Alternate.
 *
 * Boot flow:
 *   1. Init CYW43 (LED available)
 *   2. Init TinyUSB with D+ disconnected (no device visible to host)
 *   3. Init BTstack, begin scanning for any matching controller
 *   4. Main loop: poll BLE, manage USB connect/disconnect, blink LED
 *
 * USB behavior:
 *   - No XInput device visible until a controller is found
 *   - When controller found: USB D+ pulled up, XInput appears
 *   - When controller lost: USB D+ released, XInput disappears,
 *     scanning restarts immediately
 *
 * Sync button (GPIO 21):
 *   - Press at any time: forget current controller, hide XInput,
 *     restart scanning
 *
 * LED:
 *   - Scanning for controller: rapid blink (150ms on/off)
 *   - Connected to controller: solid ON
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "hardware/gpio.h"
#include "tusb_config.h"
#include "tusb.h"

#include "usb_descriptors.h"
#include "xinput_driver.h"
#include "dongle_bt.h"

// ────────────────────────────────────────────────────────────────────────
// Configuration
// ────────────────────────────────────────────────────────────────────────

#define SYNC_BUTTON_PIN          21      // GPIO for sync/re-pair button
#define REPORT_INTERVAL_US       1000    // ~1000 Hz USB XInput reports
#define SYNC_DEBOUNCE_MS         300     // Debounce for sync button
#define LED_BLINK_INTERVAL_MS    150     // LED blink rate while scanning

// After disconnecting USB, wait this long before reconnecting so the
// host OS notices the removal. This is done non-blocking.
#define USB_RECONNECT_DELAY_MS   500

// ────────────────────────────────────────────────────────────────────────
// State
// ────────────────────────────────────────────────────────────────────────

static bool g_usb_connected = false;       // Is USB D+ pulled up?
static bool g_was_bt_connected = false;    // Was controller connected last iteration?

// Non-blocking USB reconnect timer
static bool     g_usb_reconnect_pending = false;
static uint32_t g_usb_reconnect_at_ms = 0;

// LED blink state
static bool     g_led_state = false;
static uint32_t g_led_last_toggle_ms = 0;

// ────────────────────────────────────────────────────────────────────────
// CYW43 LED (Pico W onboard LED)
// ────────────────────────────────────────────────────────────────────────

static void led_set(bool on) {
    cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, on ? 1 : 0);
}

static void led_update_blink(uint32_t now_ms) {
    if (now_ms - g_led_last_toggle_ms >= LED_BLINK_INTERVAL_MS) {
        g_led_last_toggle_ms = now_ms;
        g_led_state = !g_led_state;
        led_set(g_led_state);
    }
}

// ────────────────────────────────────────────────────────────────────────
// Sync button (GPIO 21, active low with internal pull-up)
// ────────────────────────────────────────────────────────────────────────

static void init_sync_button(void) {
    gpio_init(SYNC_BUTTON_PIN);
    gpio_set_dir(SYNC_BUTTON_PIN, GPIO_IN);
    gpio_pull_up(SYNC_BUTTON_PIN);
}

static bool read_sync_button(void) {
    return !gpio_get(SYNC_BUTTON_PIN);   // Active low
}

// ────────────────────────────────────────────────────────────────────────
// USB soft connect/disconnect
// ────────────────────────────────────────────────────────────────────────

static void usb_soft_connect(void) {
    if (!g_usb_connected) {
        tud_connect();
        g_usb_connected = true;
        printf("DONGLE: USB connected (XInput visible)\n");
    }
}

static void usb_soft_disconnect(void) {
    if (g_usb_connected) {
        tud_disconnect();
        g_usb_connected = false;
        printf("DONGLE: USB disconnected (XInput hidden)\n");
    }
}

// Schedule a non-blocking USB reconnect after a delay
static void usb_schedule_reconnect(uint32_t now_ms) {
    g_usb_reconnect_pending = true;
    g_usb_reconnect_at_ms = now_ms + USB_RECONNECT_DELAY_MS;
}

// ────────────────────────────────────────────────────────────────────────
// TinyUSB callbacks (required by TinyUSB, can be empty)
// ────────────────────────────────────────────────────────────────────────

void tud_mount_cb(void)   {}
void tud_umount_cb(void)  {}
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; }
void tud_resume_cb(void)  {}

// ────────────────────────────────────────────────────────────────────────
// Main
// ────────────────────────────────────────────────────────────────────────

int main(void) {
    stdio_init_all();

    // ── Init CYW43 (required for BLE and onboard LED) ──
    // This can take a moment — if it fails, there's nothing we can do.
    if (cyw43_arch_init()) {
        // Fatal: CYW43 failed. Spin forever.
        // (No LED available since CYW43 owns it on Pico W)
        while (1) { tight_loop_contents(); }
    }

    // LED is now available. Start blinking immediately to show life.
    g_led_last_toggle_ms = to_ms_since_boot(get_absolute_time());
    g_led_state = true;
    led_set(true);

    printf("DONGLE: CYW43 initialized\n");

    // ── Init sync button ──
    init_sync_button();

    // ── Init TinyUSB but keep D+ disconnected ──
    // The host sees NO device until we call tud_connect() later.
    tusb_init();
    tud_disconnect();
    g_usb_connected = false;

    printf("DONGLE: TinyUSB initialized (USB hidden)\n");

    // ── Init BLE and start scanning ──
    dongle_bt_init();
    dongle_bt_start_sync();

    printf("DONGLE: BLE scan started — entering main loop\n");

    // ── Main loop variables ──
    xinput_report_t  xreport;
    dongle_report_t  bt_report;
    memset(&bt_report, 0, sizeof(bt_report));
    uint64_t last_report_us     = 0;
    uint32_t last_sync_press_ms = 0;
    bool     sync_was_pressed   = false;

    // ── Main loop ──
    while (true) {
        // These two calls drive everything: TinyUSB and CYW43/BTstack.
        // They must be called frequently and never starved.
        tud_task();
        cyw43_arch_poll();

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        bool bt_connected = dongle_bt_connected();

        // ── Non-blocking USB reconnect ──
        if (g_usb_reconnect_pending && !g_usb_connected) {
            if (now_ms >= g_usb_reconnect_at_ms) {
                g_usb_reconnect_pending = false;
                // Only connect if controller is still there
                if (bt_connected) {
                    usb_soft_connect();
                }
            }
        }

        // ── Sync button ──
        bool sync_pressed = read_sync_button();
        if (sync_pressed && !sync_was_pressed) {
            if (now_ms - last_sync_press_ms >= SYNC_DEBOUNCE_MS) {
                last_sync_press_ms = now_ms;
                printf("DONGLE: Sync button — re-scanning\n");

                usb_soft_disconnect();
                g_usb_reconnect_pending = false;
                dongle_bt_start_sync();
                g_was_bt_connected = false;
                bt_connected = false;
            }
        }
        sync_was_pressed = sync_pressed;

        // ── BLE connection state transitions ──

        if (bt_connected && !g_was_bt_connected) {
            // Controller just appeared — schedule USB connect
            // (non-blocking delay so CYW43 keeps getting polled)
            printf("DONGLE: Controller found\n");
            usb_schedule_reconnect(now_ms);
        }

        if (!bt_connected && g_was_bt_connected) {
            // Controller just disappeared — immediately hide XInput
            printf("DONGLE: Controller lost — re-scanning\n");
            usb_soft_disconnect();
            g_usb_reconnect_pending = false;
            dongle_bt_start_sync();
        }

        g_was_bt_connected = bt_connected;

        // ── LED ──
        if (bt_connected) {
            led_set(true);                   // Solid = connected
        } else {
            led_update_blink(now_ms);        // Blink = scanning
        }

        // ── XInput reports at ~1kHz ──
        uint64_t now_us = time_us_64();
        if (now_us - last_report_us >= REPORT_INTERVAL_US) {
            last_report_us = now_us;

            if (g_usb_connected && xinput_ready()) {
                memset(&xreport, 0, sizeof(xinput_report_t));
                xreport.report_id   = 0x00;
                xreport.report_size = 0x14;

                dongle_bt_get_report(&bt_report);

                if (bt_connected) {
                    xreport.buttons       = bt_report.buttons;
                    xreport.left_trigger  = bt_report.left_trigger;
                    xreport.right_trigger = bt_report.right_trigger;
                    xreport.left_stick_x  = bt_report.left_stick_x;
                    xreport.left_stick_y  = bt_report.left_stick_y;
                    xreport.right_stick_x = bt_report.right_stick_x;
                    xreport.right_stick_y = bt_report.right_stick_y;
                }

                xinput_send_report(&xreport);
            }
        }

    }

    return 0;
}
