/*
 * main.c - Pico Pedal Controller Firmware
 *
 * A controller extension/passthrough device that:
 *   - Reads a guitar controller connected via USB-A (PIO-USB host, Core 1)
 *   - Reads up to 4 pedal buttons on configurable GPIO pins
 *   - Merges pedal button presses with the guitar controller's input
 *   - Presents as an XInput Guitar Alternate controller to the host PC
 *
 * Hardware:
 *   Native USB (micro-USB on Pico) -> Host PC (XInput device mode)
 *   USB-A port via PIO-USB (GP2=D+, GP3=D-) -> Guitar controller (USB host)
 *   Up to 4 pedal buttons on any GPIO (default GP4–GP7)
 *
 * If no guitar controller is connected, the pedal still works standalone —
 * it sends only its own button presses with all axes at rest.
 *
 * Boot: Check watchdog scratch register -> config mode or play mode.
 */

#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/adc.h"
#include "hardware/watchdog.h"
#include "hardware/structs/watchdog.h"
#include "tusb_config.h"
#include "tusb.h"

#include "usb_descriptors.h"
#include "xinput_driver.h"
#include "xinput_host.h"
#include "pedal_config.h"
#include "pedal_config_serial.h"
#if PEDAL_LED_DEBUG
#include "apa102_leds.h"
#endif

#define REPORT_INTERVAL_US     1000   // 1ms report interval (1000Hz)
#define ONBOARD_LED_PIN        25

// XInput button masks indexed by button_index_t — shared lookup table
// for mapping pedal buttons to guitar controller inputs
static const uint16_t button_masks[BTN_IDX_COUNT] = {
    [BTN_IDX_GREEN]      = GUITAR_BTN_GREEN,
    [BTN_IDX_RED]        = GUITAR_BTN_RED,
    [BTN_IDX_YELLOW]     = GUITAR_BTN_YELLOW,
    [BTN_IDX_BLUE]       = GUITAR_BTN_BLUE,
    [BTN_IDX_ORANGE]     = GUITAR_BTN_ORANGE,
    [BTN_IDX_STRUM_UP]   = GUITAR_BTN_STRUM_UP,
    [BTN_IDX_STRUM_DOWN] = GUITAR_BTN_STRUM_DOWN,
    [BTN_IDX_START]      = GUITAR_BTN_START,
    [BTN_IDX_SELECT]     = GUITAR_BTN_SELECT,
    [BTN_IDX_DPAD_UP]    = GUITAR_BTN_DPAD_UP,
    [BTN_IDX_DPAD_DOWN]  = GUITAR_BTN_DPAD_DOWN,
    [BTN_IDX_DPAD_LEFT]  = GUITAR_BTN_DPAD_LEFT,
    [BTN_IDX_DPAD_RIGHT] = GUITAR_BTN_DPAD_RIGHT,
    [BTN_IDX_GUIDE]      = GUITAR_BTN_GUIDE,
};

static pedal_config_t g_config;

typedef struct {
    uint32_t last_change_us;
    bool     stable;
    bool     raw;
} debounce_state_t;

static debounce_state_t g_debounce[PEDAL_BUTTON_COUNT];

//--------------------------------------------------------------------
// Watchdog scratch register — config mode trigger
//--------------------------------------------------------------------

static bool check_scratch_config_mode(void) {
    if (watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC) {
        watchdog_hw->scratch[0] = 0;
        return true;
    }
    return false;
}

static void request_config_mode_reboot(void) {
    watchdog_hw->scratch[0] = WATCHDOG_CONFIG_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

//--------------------------------------------------------------------
// GPIO init — pedal buttons (active-low with internal pull-ups)
//--------------------------------------------------------------------

static void init_gpio_pin(int8_t pin) {
    if (pin < 0 || pin > 28) return;
    // Don't configure PIO-USB pins as GPIO
    if (pin == PIO_USB_DP_PIN || pin == (PIO_USB_DP_PIN + 1)) return;
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
}

//--------------------------------------------------------------------
// ADC init — analog pedal inputs (GP26/GP27/GP28 only)
//--------------------------------------------------------------------

static void init_adc(void) {
    adc_init();
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        int8_t pin = g_config.adc_pin[i];
        if (pin >= 26 && pin <= 28)
            adc_gpio_init((uint)pin);
    }
}

// Map a raw 12-bit ADC reading through the calibration window to a
// signed 16-bit XInput axis value [-32768, +32767].
// The [adc_min, adc_max] window is clamped then stretched to full range.
static int16_t adc_to_axis16(uint16_t raw, uint16_t cal_min, uint16_t cal_max,
                              uint8_t invert) {
    if (cal_max <= cal_min) cal_max = cal_min + 1;
    if (raw < cal_min) raw = cal_min;
    if (raw > cal_max) raw = cal_max;
    uint32_t range  = cal_max - cal_min;
    uint32_t scaled = ((uint32_t)(raw - cal_min) * 4095u) / range;
    if (invert) scaled = 4095u - scaled;
    // Map [0, 4095] → [-32768, +32767]
    return (int16_t)(((scaled * 65535u) / 4095u) - 32768u);
}

static void init_all_gpio(void) {
    for (int i = 0; i < PEDAL_BUTTON_COUNT; i++)
        init_gpio_pin(g_config.pin_buttons[i]);
    init_adc();
}

//--------------------------------------------------------------------
// Input reading
//--------------------------------------------------------------------

static inline bool read_pin(int8_t pin) {
    if (pin < 0 || pin > 28) return false;
    if (pin == PIO_USB_DP_PIN || pin == (PIO_USB_DP_PIN + 1)) return false;
    return !gpio_get(pin);  // Active low: pressed = GPIO low
}

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
// Report building — merge passthrough + pedal buttons
//--------------------------------------------------------------------

static void build_report(xinput_report_t *report) {
    uint32_t now_us = time_us_32();
    uint32_t debounce_us = (uint32_t)g_config.debounce_ms * 1000;

    // Start with the passthrough report from the connected guitar controller.
    // If no controller is connected, use a blank report with axes at rest.
    xinput_report_t host_report;
    bool have_host = xinput_host_get_report(&host_report);

    if (have_host) {
        memcpy(report, &host_report, sizeof(xinput_report_t));
    } else {
        memset(report, 0, sizeof(xinput_report_t));
        report->report_id   = 0x00;
        report->report_size = 0x14;
        report->right_stick_x = -32768;  // Whammy at rest (0%)
    }

    // Apply analog pedal inputs — max-merge with the guitar passthrough.
    // For each axis, whichever source is further from rest wins.
    // The unsigned shift (+32768) lets us compare whammy and tilt with
    // the same formula: 0 = at rest, 65535 = fully active.
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        int8_t pin = g_config.adc_pin[i];
        if (pin < 26 || pin > 28) continue;

        adc_select_input((uint)(pin - 26));
        uint16_t raw = adc_read();
        int16_t  val = adc_to_axis16(raw, g_config.adc_min[i],
                                     g_config.adc_max[i],
                                     g_config.adc_invert[i]);

        if (g_config.adc_axis[i] == ADC_AXIS_WHAMMY) {
            uint32_t host_u  = (uint32_t)(report->right_stick_x + 32768);
            uint32_t pedal_u = (uint32_t)(val + 32768);
            if (pedal_u > host_u)
                report->right_stick_x = val;
        } else if (g_config.adc_axis[i] == ADC_AXIS_TILT) {
            uint32_t host_u  = (uint32_t)(report->right_stick_y + 32768);
            uint32_t pedal_u = (uint32_t)(val + 32768);
            if (pedal_u > host_u)
                report->right_stick_y = val;
        }
    }

    // Apply pedal button presses.
    // Most mappings OR into the buttons field. BTN_IDX_WHAMMY and
    // BTN_IDX_TILT instead drive their axis to 100% via max-merge,
    // so pressing a digital pedal can activate whammy or tilt just like
    // an analog input — whichever source is further from rest wins.
    for (int i = 0; i < PEDAL_BUTTON_COUNT; i++) {
        bool raw = read_pin(g_config.pin_buttons[i]);
        bool is_pressed = debounce(&g_debounce[i], raw, now_us, debounce_us);
        if (!is_pressed) continue;

        uint8_t mapping = g_config.button_mapping[i];
        if (mapping == BTN_IDX_WHAMMY) {
            // Max-merge: button contributes +32767 (100%)
            if (report->right_stick_x < 32767)
                report->right_stick_x = 32767;
        } else if (mapping == BTN_IDX_TILT) {
            if (report->right_stick_y < 32767)
                report->right_stick_y = 32767;
        } else if (mapping < BTN_IDX_WHAMMY) {
            report->buttons |= button_masks[mapping];
        }
    }
}

//--------------------------------------------------------------------
// TinyUSB device callbacks (required by TinyUSB)
//--------------------------------------------------------------------

void tud_mount_cb(void)   {}
void tud_umount_cb(void)  {}
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; }
void tud_resume_cb(void)  {}

//--------------------------------------------------------------------
// CDC debug output — Core 0 only, writes directly to TinyUSB CDC TX.
// Only active when PEDAL_HOST_DEBUG is defined.
//--------------------------------------------------------------------

#if PEDAL_HOST_DEBUG
static void dbg_printf(const char *fmt, ...) {
    if (!tud_cdc_connected()) return;
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n > 0) {
        tud_cdc_write(buf, (uint32_t)n);
        tud_cdc_write_flush();
    }
}
#endif

//--------------------------------------------------------------------
// Onboard LED — steady in play mode, blink pattern in config mode
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
// Core 1 entry point — PIO-USB host for reading guitar controller
//--------------------------------------------------------------------

static void core1_main(void) {
    sleep_ms(10);  // Let Core 0 finish device stack init
    xinput_host_init();
    while (true) {
        xinput_host_task();
    }
}

//--------------------------------------------------------------------
// Main
//--------------------------------------------------------------------

int main(void) {
    // 120MHz gives an exact integer PIO clock divider (120/12 = 10) for
    // full-speed USB timing. Default 125MHz is fractional (10.417) and
    // causes PIO-USB enumeration to fail.
    set_sys_clock_khz(120000, true);

    stdio_init_all();
    onboard_led_init();
    config_load(&g_config);

    bool enter_config = check_scratch_config_mode();

    // Set custom device name for USB string descriptors
    if (g_config.device_name[0] != '\0') {
        g_device_name = g_config.device_name;
    }

    if (enter_config) {
        // ── Config mode ──
        // Single-core, no USB host needed. CDC serial for configurator.
        g_config_mode = true;
        tud_init(0);
        while (true) {
            tud_task();
            onboard_led_blink_config();
            if (tud_cdc_connected()) {
                gpio_put(ONBOARD_LED_PIN, true);
                config_mode_main(&g_config);
            }
        }
    } else {
        // ── Play mode ──
        // Core 0: XInput device + pedal buttons + report merging
        // Core 1: PIO-USB host reading guitar controller
        g_config_mode = false;

        init_all_gpio();
        memset(g_debounce, 0, sizeof(g_debounce));

        // Reset Core 1 to a clean state, then launch it.
        multicore_reset_core1();
        multicore_launch_core1(core1_main);

#if PEDAL_HOST_DEBUG
        // Debug mode: present as CDC so we can get serial output over USB.
        // g_config_mode=true selects CDC descriptors (VID=0x2E8A, PID=0xF010).
        // Open the COM port in PuTTY at any baud to receive status dumps.
        g_config_mode = true;
#endif
        tud_init(0);

#if PEDAL_LED_DEBUG
        // Minimal LED config for debug — 4 LEDs, no effects
        static led_config_t _dbg_leds = { .enabled = 1, .count = 4 };
        apa102_init();
#endif

        xinput_report_t report; (void)report;
#if PEDAL_LED_DEBUG
        uint64_t last_led_us     = 0;
        bool     led_on          = false;
        uint64_t startup_done_us = time_us_64() + 1000000u;  // 1s for Core 1 to init
#endif

        uint64_t last_report_us = 0;
#if PEDAL_HOST_DEBUG
        uint64_t last_dbg_us = 0;
        xinput_debug_t prev_dbg = {0};
        bool hdr_printed = false;
#endif

        while (true) {
            tud_task();

#if PEDAL_HOST_DEBUG
            uint64_t now_us = time_us_64();

            // Print header once CDC connects
            if (!hdr_printed && tud_cdc_connected()) {
                hdr_printed = true;
                dbg_printf("\r\n=== Pedal Host Debug ===\r\n");
                dbg_printf("dp_pin=%u  tx_ch=1  120MHz\r\n\r\n", (unsigned)PIO_USB_DP_PIN);
                dbg_printf("state: c1 any mnt umt oat ocl cls/sub/pro se0 ok fail pfird preal rcon rsus brst\r\n");
                dbg_printf("ep0:   setup sack sfail hcmp hqin hqfl inat hqou hqof oat2 oack onak onrs ostl nak nrsp bpid\r\n");
                dbg_printf("last:  saddr bmReq req wValue\r\n");
            }

            // Every 500ms: dump counters if anything changed or periodically
            if (now_us - last_dbg_us >= 500000u) {
                last_dbg_us = now_us;
                xinput_debug_t d;
                xinput_host_get_debug(&d);
                bool any   = xinput_host_any_device();
                bool xinup = xinput_host_connected();
                uint8_t c1 = xinput_host_core1_status();

                // Print if anything changed from last dump
                if (d.mount_count     != prev_dbg.mount_count     ||
                    d.umount_count    != prev_dbg.umount_count    ||
                    d.open_attempts   != prev_dbg.open_attempts   ||
                    d.xfer_success    != prev_dbg.xfer_success    ||
                    d.xfer_fail       != prev_dbg.xfer_fail       ||
                    d.probe_fired     != prev_dbg.probe_fired     ||
                    d.probe_real      != prev_dbg.probe_real      ||
                    d.root_connected  != prev_dbg.root_connected  ||
                    d.root_suspended  != prev_dbg.root_suspended  ||
                    d.bus_reset_count != prev_dbg.bus_reset_count ||
                    d.setup_sent_count!= prev_dbg.setup_sent_count||
                    d.ep0_nak_count   != prev_dbg.ep0_nak_count   ||
                    d.ep0_noresp_count!= prev_dbg.ep0_noresp_count||
                    d.ep0_badpid_count!= prev_dbg.ep0_badpid_count||
                    d.setup_ack_count != prev_dbg.setup_ack_count ||
                    d.setup_fail_count!= prev_dbg.setup_fail_count||
                    d.hcd_ep0_complete_count != prev_dbg.hcd_ep0_complete_count ||
                    d.hcd_ep0_in_submit_count != prev_dbg.hcd_ep0_in_submit_count ||
                    d.hcd_ep0_in_submit_fail_count != prev_dbg.hcd_ep0_in_submit_fail_count ||
                    d.ep0_in_attempt_count != prev_dbg.ep0_in_attempt_count ||
                    d.hcd_ep0_out_submit_count != prev_dbg.hcd_ep0_out_submit_count ||
                    d.hcd_ep0_out_submit_fail_count != prev_dbg.hcd_ep0_out_submit_fail_count ||
                    d.ep0_out_attempt_count != prev_dbg.ep0_out_attempt_count ||
                    d.ep0_out_ack_count != prev_dbg.ep0_out_ack_count ||
                    d.ep0_out_nak_count != prev_dbg.ep0_out_nak_count ||
                    d.ep0_out_noresp_count != prev_dbg.ep0_out_noresp_count ||
                    d.ep0_out_stall_count != prev_dbg.ep0_out_stall_count ||
                    d.last_setup_addr != prev_dbg.last_setup_addr ||
                    d.last_setup_bmRequestType != prev_dbg.last_setup_bmRequestType ||
                    d.last_setup_bRequest != prev_dbg.last_setup_bRequest ||
                    d.last_setup_wValue != prev_dbg.last_setup_wValue ||
                    any != (bool)(prev_dbg.mount_count & 0x80)) {

                    dbg_printf("state: %u %u %u %u %u %u %02X/%02X/%02X %u %u %u %u %u %u %u %u  %s\r\n",
                        c1, (unsigned)any,
                        d.mount_count, d.umount_count,
                        d.open_attempts, d.open_claims,
                        d.last_class, d.last_subclass, d.last_proto,
                        d.se0_count,
                        d.xfer_success, d.xfer_fail,
                        d.probe_fired, d.probe_real,
                        d.root_connected, d.root_suspended,
                        d.bus_reset_count,
                        xinup ? "XINPUT-OK" : (any ? "device-no-claim" : "no-device"));
                    dbg_printf("ep0:   %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u\r\n",
                        d.setup_sent_count,
                        d.setup_ack_count, d.setup_fail_count,
                        d.hcd_ep0_complete_count, d.hcd_ep0_in_submit_count,
                        d.hcd_ep0_in_submit_fail_count, d.ep0_in_attempt_count,
                        d.hcd_ep0_out_submit_count, d.hcd_ep0_out_submit_fail_count,
                        d.ep0_out_attempt_count,
                        d.ep0_out_ack_count, d.ep0_out_nak_count,
                        d.ep0_out_noresp_count, d.ep0_out_stall_count,
                        d.ep0_nak_count, d.ep0_noresp_count, d.ep0_badpid_count);
                    dbg_printf("last:  %u 0x%02X 0x%02X 0x%04X\r\n",
                        d.last_setup_addr, d.last_setup_bmRequestType,
                        d.last_setup_bRequest, d.last_setup_wValue);

                    prev_dbg = d;
                    // Stash `any` in unused high bit of mount_count for change detection
                    if (any) prev_dbg.mount_count |= 0x80;
                }
            }

            // Recovery watchdog: if a real device was probed but never mounted after 3s,
            // force a reconnect so the detection loop can try again.
            {
                static uint64_t last_preal_change_us = 0;
                static uint8_t  last_preal_seen = 0;
                xinput_debug_t dw;
                xinput_host_get_debug(&dw);
                if (dw.probe_real != last_preal_seen) {
                    last_preal_seen       = dw.probe_real;
                    last_preal_change_us  = now_us;
                }
                if (last_preal_change_us > 0 &&
                    (now_us - last_preal_change_us) > 3000000u &&
                    dw.probe_real > 0 && dw.mount_count == 0) {
                    dbg_printf("watchdog: no mount after 3s, forcing reconnect\r\n");
                    xinput_host_force_reconnect();
                    last_preal_change_us = now_us;  // reset so we don't spam
                }
            }
#else
            // Normal play mode — not used while PEDAL_HOST_DEBUG is active
            uint64_t now_us = time_us_64();
            if (now_us - last_report_us >= REPORT_INTERVAL_US) {
                last_report_us = now_us;
                if (xinput_ready()) {
                    build_report(&report);
                    xinput_send_report(&report);
                }
            }
#endif

#if PEDAL_LED_DEBUG
            // APA102 debug indicators (GP6=SCK, GP7=MOSI):
            //   solid blue        = Core 1 never started (crashed)
            //   fast blue  200ms  = Core 1 alive but tuh_init() hasn't returned
            //   solid magenta     = tuh_init() returned false (host controller failed)
            //   slow red   500ms  = tuh_init ok + task running, nothing on bus (wiring/VBUS)
            //   fast amber 100ms  = device present but not XInput
            //   solid green       = XInput guitar active
            {
                uint8_t c1      = xinput_host_core1_status();
                bool    startup = (now_us >= startup_done_us);

                if (!startup) {
                    // Still in 1s startup window — LEDs off while Core 1 initializes
                } else if (c1 == 0) {
                    // Core 1 never ran — solid blue
                    if (!led_on) {
                        for (int i = 0; i < _dbg_leds.count; i++) {
                            _dbg_leds.colors[i].r = 0;
                            _dbg_leds.colors[i].g = 0;
                            _dbg_leds.colors[i].b = 255;
                        }
                        uint8_t bri[MAX_LEDS] = {8, 8, 8, 8};
                        apa102_update(&_dbg_leds, bri);
                        led_on = true;
                    }
                } else if (c1 == 1) {
                    // Core 1 alive but tuh_init hasn't returned — fast blue blink
                    if (now_us - last_led_us >= 200000u) {
                        last_led_us = now_us;
                        led_on = !led_on;
                        if (led_on) {
                            for (int i = 0; i < _dbg_leds.count; i++) {
                                _dbg_leds.colors[i].r = 0;
                                _dbg_leds.colors[i].g = 0;
                                _dbg_leds.colors[i].b = 255;
                            }
                            uint8_t bri[MAX_LEDS] = {8, 8, 8, 8};
                            apa102_update(&_dbg_leds, bri);
                        } else {
                            uint8_t bri[MAX_LEDS] = {0};
                            apa102_update(&_dbg_leds, bri);
                        }
                    }
                } else if (c1 == 3) {
                    // tuh_init returned false — host controller failed — solid magenta
                    if (!led_on) {
                        for (int i = 0; i < _dbg_leds.count; i++) {
                            _dbg_leds.colors[i].r = 255;
                            _dbg_leds.colors[i].g = 0;
                            _dbg_leds.colors[i].b = 255;
                        }
                        uint8_t bri[MAX_LEDS] = {8, 8, 8, 8};
                        apa102_update(&_dbg_leds, bri);
                        led_on = true;
                    }
                } else {
                    // c1 == 2 or 4: tuh_init done (4 = task loop confirmed running)
                    bool xinput_up = xinput_host_connected();
                    bool any_dev   = xinput_host_any_device();

                    if (xinput_up) {
                        if (!led_on) {
                            for (int i = 0; i < _dbg_leds.count; i++) {
                                _dbg_leds.colors[i].r = 0;
                                _dbg_leds.colors[i].g = 255;
                                _dbg_leds.colors[i].b = 0;
                            }
                            uint8_t bri[MAX_LEDS] = {8, 8, 8, 8};
                            apa102_update(&_dbg_leds, bri);
                            led_on = true;
                        }
                    } else {
                        uint64_t period_us = any_dev ? 100000u : 500000u;
                        if (now_us - last_led_us >= period_us) {
                            last_led_us = now_us;
                            led_on = !led_on;
                            if (led_on) {
                                for (int i = 0; i < _dbg_leds.count; i++) {
                                    _dbg_leds.colors[i].r = 255;
                                    _dbg_leds.colors[i].g = any_dev ? 80 : 0;
                                    _dbg_leds.colors[i].b = 0;
                                }
                                uint8_t bri[MAX_LEDS] = {8, 8, 8, 8};
                                apa102_update(&_dbg_leds, bri);
                            } else {
                                uint8_t bri[MAX_LEDS] = {0};
                                apa102_update(&_dbg_leds, bri);
                            }
                        }
                    }
                }
            }
#endif
        }
    }
    return 0;
}
