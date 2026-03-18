/*
 * main.c - Pico Drum Controller Firmware
 *
 * Boot: Check watchdog scratch register → config mode or play mode.
 * Play mode: XInput drum kit. 14 digital buttons, active-low with pull-ups.
 *            Optional APA102 LED strip driven by button state.
 *
 * Inputs:
 *   Red Drum, Yellow Drum, Blue Drum, Green Drum  → B, Y, X, A
 *   Yellow Cymbal, Blue Cymbal, Green Cymbal       → LS, RS, RT (+ cymbal flag)
 *   Start, Select
 *   D-pad Up, Down, Left, Right                   → DPAD bits
 *   Foot Pedal                                    → Left Thumb (bass pedal per Rock Band XInput spec)
 *
 * Cymbals set right_trigger = 0xFF in the XInput report to distinguish
 * them from the same-colour pad hits (standard Rock Band encoding).
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/watchdog.h"
#include "hardware/structs/watchdog.h"
#include "tusb_config.h"
#include "tusb.h"

#include "usb_descriptors.h"
#include "xinput_driver.h"
#include "drum_config.h"
#include "drum_config_serial.h"
#include "apa102_leds.h"

#define REPORT_INTERVAL_US      1000
#define LED_UPDATE_INTERVAL_US  16667   // ~60 Hz
#define ONBOARD_LED_PIN         25

// XInput button mask for each drum button index.
// D-pad uses the standard XInput dpad bits (low nibble of buttons word).
// Foot pedal uses Left Thumb / LS click (0x0040) — bass pedal in Rock Band XInput drum kit.
static const uint16_t button_masks[BTN_IDX_COUNT] = {
    [BTN_IDX_RED_DRUM]    = DRUM_BTN_RED_DRUM,
    [BTN_IDX_YELLOW_DRUM] = DRUM_BTN_YELLOW_DRUM,
    [BTN_IDX_BLUE_DRUM]   = DRUM_BTN_BLUE_DRUM,
    [BTN_IDX_GREEN_DRUM]  = DRUM_BTN_GREEN_DRUM,
    [BTN_IDX_YELLOW_CYM]  = DRUM_BTN_YELLOW_CYM,
    [BTN_IDX_BLUE_CYM]    = DRUM_BTN_BLUE_CYM,
    [BTN_IDX_GREEN_CYM]   = DRUM_BTN_GREEN_CYM,
    [BTN_IDX_START]       = DRUM_BTN_START,
    [BTN_IDX_SELECT]      = DRUM_BTN_SELECT,
    [BTN_IDX_DPAD_UP]     = DRUM_BTN_DPAD_UP,
    [BTN_IDX_DPAD_DOWN]   = DRUM_BTN_DPAD_DOWN,
    [BTN_IDX_DPAD_LEFT]   = DRUM_BTN_DPAD_LEFT,
    [BTN_IDX_DPAD_RIGHT]  = DRUM_BTN_DPAD_RIGHT,
    [BTN_IDX_FOOT_PEDAL]  = DRUM_BTN_FOOT_PEDAL,
};

// Which buttons are cymbals — hitting these also sets the cymbal flag byte
static const bool is_cymbal[BTN_IDX_COUNT] = {
    [BTN_IDX_YELLOW_CYM] = true,
    [BTN_IDX_BLUE_CYM]   = true,
    [BTN_IDX_GREEN_CYM]  = true,
};

static drum_config_t g_config;

// Tracks which inputs are pressed (used by LED driver)
static uint16_t g_pressed_mask;

//--------------------------------------------------------------------
// Debounce
//--------------------------------------------------------------------

typedef struct {
    uint32_t last_change_us;
    bool     stable;
    bool     raw;
} debounce_state_t;

static debounce_state_t g_debounce[BTN_IDX_COUNT];

static bool debounce(debounce_state_t *state, bool current_raw,
                     uint32_t now_us, uint32_t debounce_us) {
    if (current_raw != state->raw) {
        state->raw = current_raw;
        state->last_change_us = now_us;
    } else if (current_raw != state->stable) {
        if ((now_us - state->last_change_us) >= debounce_us)
            state->stable = current_raw;
    }
    return state->stable;
}

//--------------------------------------------------------------------
// Watchdog scratch register
//--------------------------------------------------------------------

static bool check_scratch_config_mode(void) {
    if (watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC) {
        watchdog_hw->scratch[0] = 0;
        return true;
    }
    return false;
}

static void request_config_mode_reboot(void) {
    // Turn off LEDs before rebooting
    led_config_t tmp;
    memcpy(&tmp, &g_config.leds, sizeof(led_config_t));
    apa102_all_off(&tmp);
    watchdog_hw->scratch[0] = WATCHDOG_CONFIG_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

//--------------------------------------------------------------------
// GPIO init
//--------------------------------------------------------------------

static inline bool is_led_spi_pin(int8_t pin) {
    if (!g_config.leds.enabled) return false;
    return (pin == LED_SPI_DI_PIN || pin == LED_SPI_SCK_PIN);
}

static void init_gpio_pin(int8_t pin) {
    if (pin < 0 || pin > 28) return;
    if (is_led_spi_pin(pin)) return;
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
}

static void init_all_gpio(void) {
    for (int i = 0; i < BTN_IDX_COUNT; i++)
        init_gpio_pin(g_config.pin_buttons[i]);
}

static inline bool read_pin(int8_t pin) {
    if (pin < 0 || pin > 28) return false;
    if (is_led_spi_pin(pin)) return false;
    return !gpio_get(pin);  // active-low
}

//--------------------------------------------------------------------
// Build XInput report
//--------------------------------------------------------------------

static void build_report(xinput_report_t *report) {
    memset(report, 0, sizeof(xinput_report_t));
    report->report_id   = 0x00;
    report->report_size = XINPUT_REPORT_SIZE;

    uint32_t now_us      = time_us_32();
    uint32_t debounce_us = (uint32_t)g_config.debounce_ms * 1000u;

    bool any_cymbal  = false;
    uint16_t pressed = 0;

    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        bool raw     = read_pin(g_config.pin_buttons[i]);
        bool active  = debounce(&g_debounce[i], raw, now_us, debounce_us);
        if (active) {
            report->buttons |= button_masks[i];
            pressed |= (1u << i);
            if (is_cymbal[i])
                any_cymbal = true;
        }
    }

    // Set cymbal flag byte when any cymbal is active
    if (any_cymbal)
        report->right_trigger = DRUM_CYMBAL_FLAG;

    g_pressed_mask = pressed;
}

//--------------------------------------------------------------------
// TinyUSB callbacks
//--------------------------------------------------------------------

void tud_mount_cb(void)   {}
void tud_umount_cb(void)  {}
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; }
void tud_resume_cb(void)  {}

//--------------------------------------------------------------------
// Onboard LED
//--------------------------------------------------------------------

static void onboard_led_init(void) {
    gpio_init(ONBOARD_LED_PIN);
    gpio_set_dir(ONBOARD_LED_PIN, GPIO_OUT);
}

static void onboard_led_blink_config(void) {
    static uint32_t last_toggle = 0;
    static int phase = 0;
    uint32_t now = to_ms_since_boot(get_absolute_time());
    const uint32_t pattern[] = {100, 100, 100, 700};
    if (now - last_toggle >= pattern[phase % 4]) {
        last_toggle = now;
        gpio_put(ONBOARD_LED_PIN, (phase % 2) == 0);
        phase++;
    }
}

//--------------------------------------------------------------------
// Main
//--------------------------------------------------------------------

int main(void) {
    stdio_init_all();
    onboard_led_init();
    config_load(&g_config);

    bool enter_config = check_scratch_config_mode();

    if (g_config.device_name[0] != '\0')
        g_device_name = g_config.device_name;

    if (enter_config) {
        // ── Config mode ──────────────────────────────────────────────
        g_config_mode = true;
        tusb_init();
        while (true) {
            tud_task();
            onboard_led_blink_config();
            if (tud_cdc_connected()) {
                gpio_put(ONBOARD_LED_PIN, true);
                drum_config_mode_main(&g_config);
            }
        }
    } else {
        // ── Play mode ────────────────────────────────────────────────
        g_config_mode = false;
        gpio_put(ONBOARD_LED_PIN, true);

        // Init APA102 LED strip BEFORE GPIO init so SPI pins are
        // claimed and won't be reconfigured as button inputs
        static led_config_t aligned_leds;
        memcpy(&aligned_leds, &g_config.leds, sizeof(led_config_t));

        if (aligned_leds.enabled)
            apa102_init();

        init_all_gpio();
        memset(g_debounce, 0, sizeof(g_debounce));

        // Show idle LED state
        if (aligned_leds.enabled)
            apa102_update_from_inputs(&aligned_leds, 0);

        tusb_init();

        xinput_report_t report;
        uint64_t last_report_us = 0;
        uint64_t last_led_us    = 0;

        while (true) {
            tud_task();

            if (xinput_magic_detected())
                request_config_mode_reboot();

            uint64_t now_us = time_us_64();

            if (now_us - last_report_us >= REPORT_INTERVAL_US) {
                last_report_us = now_us;
                if (xinput_ready()) {
                    build_report(&report);
                    xinput_send_report(&report);
                }
            }

            // Update LEDs at ~60 Hz
            if (aligned_leds.enabled &&
                (now_us - last_led_us >= LED_UPDATE_INTERVAL_US)) {
                last_led_us = now_us;
                apa102_update_from_inputs(&aligned_leds, g_pressed_mask);
            }
        }
    }
    return 0;
}
