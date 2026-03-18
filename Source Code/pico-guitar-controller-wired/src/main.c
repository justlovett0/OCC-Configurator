/*
 * main.c - Pico Guitar Controller Firmware
 *
 * Boot: Check watchdog scratch register → config mode or play mode.
 * Play mode: XInput guitar + APA102 LED strip driven by button state.
 *
 * v6: Added analog sensitivity (min/max ADC range) for tilt and whammy.
 * v6.1: Fixed XInput axis range (now uses full -32768..+32767 instead of 0..32767).
 *       Added EMA smoothing filter on whammy and tilt analog paths.
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/adc.h"
#include "hardware/watchdog.h"
#include "hardware/structs/watchdog.h"
#include "tusb_config.h"
#include "tusb.h"

#include "usb_descriptors.h"
#include "xinput_driver.h"
#include "guitar_config.h"
#include "config_serial.h"
#include "apa102_leds.h"
#include "adxl345.h"
#include "lis3dh.h"

#define REPORT_INTERVAL_US    1000
#define LED_UPDATE_INTERVAL_US 16667  // ~60Hz LED refresh (plenty smooth)
#define ADC_RESOLUTION        4095
#define DIGITAL_AXIS_ON       32767
#define ONBOARD_LED_PIN       25

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

static guitar_config_t g_config;

typedef struct {
    uint32_t last_change_us;
    bool     stable;
    bool     raw;
} debounce_state_t;

static debounce_state_t g_debounce[BTN_IDX_COUNT];
static debounce_state_t g_debounce_tilt;
static debounce_state_t g_debounce_whammy;

// Track which inputs are currently pressed (for LED driver)
static uint16_t g_pressed_mask;

// I2C tilt baseline (measured at startup when guitar is at rest)
static uint16_t g_i2c_tilt_baseline = 2048;
static bool     g_i2c_tilt_ready = false;

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
    // Turn off LEDs before rebooting (use aligned copy)
    led_config_t tmp;
    memcpy(&tmp, &g_config.leds, sizeof(led_config_t));
    apa102_all_off(&tmp);
    watchdog_hw->scratch[0] = WATCHDOG_CONFIG_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

//--------------------------------------------------------------------
// GPIO / ADC init
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
    if (g_config.tilt_mode == INPUT_MODE_DIGITAL && g_config.pin_tilt_digital >= 0)
        init_gpio_pin(g_config.pin_tilt_digital);
    if (g_config.whammy_mode == INPUT_MODE_DIGITAL && g_config.pin_whammy_digital >= 0)
        init_gpio_pin(g_config.pin_whammy_digital);
}

static void init_adc(void) {
    adc_init();
    if (g_config.tilt_mode == INPUT_MODE_ANALOG &&
        g_config.pin_tilt_analog >= 26 && g_config.pin_tilt_analog <= 28)
        adc_gpio_init(g_config.pin_tilt_analog);
    if (g_config.whammy_mode == INPUT_MODE_ANALOG &&
        g_config.pin_whammy_analog >= 26 && g_config.pin_whammy_analog <= 28)
        adc_gpio_init(g_config.pin_whammy_analog);
}

static void init_i2c_tilt(void) {
    if (g_config.tilt_mode != INPUT_MODE_I2C_ADXL345 &&
        g_config.tilt_mode != INPUT_MODE_I2C_LIS3DH) return;

    bool use_lis3dh = (g_config.i2c_model == I2C_MODEL_LIS3DH);

    if (use_lis3dh)
        g_i2c_tilt_ready = lis3dh_init(g_config.pin_i2c_sda, g_config.pin_i2c_scl);
    else
        g_i2c_tilt_ready = adxl345_init(g_config.pin_i2c_sda, g_config.pin_i2c_scl);

    if (g_i2c_tilt_ready) {
        // Measure baseline at rest — average several readings
        sleep_ms(50);
        uint32_t sum = 0;
        int good = 0;
        for (int i = 0; i < 8; i++) {
            int16_t raw = use_lis3dh
                ? lis3dh_read_axis(g_config.adxl345_axis)
                : adxl345_read_axis(g_config.adxl345_axis);
            uint16_t scaled = use_lis3dh
                ? lis3dh_to_adc_scale(raw)
                : adxl345_to_adc_scale(raw);
            sum += scaled;
            good++;
            sleep_ms(5);
        }
        if (good > 0)
            g_i2c_tilt_baseline = (uint16_t)(sum / good);
    }
}

//--------------------------------------------------------------------
// Input reading
//--------------------------------------------------------------------

static inline bool read_pin(int8_t pin) {
    if (pin < 0 || pin > 28) return false;
    if (is_led_spi_pin(pin)) return false;
    return !gpio_get(pin);
}

static uint16_t read_adc_pin(int8_t pin) {
    if (pin < 26 || pin > 28) return 0;
    adc_select_input(pin - 26);
    return adc_read();
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

// Apply min/max sensitivity scaling to a raw ADC value.
// Clamps the value to [min_val, max_val] then stretches it to [0, 4095].
static uint16_t apply_sensitivity(uint16_t raw, uint16_t min_val, uint16_t max_val) {
    if (max_val <= min_val) return raw;  // Degenerate range — pass through
    if (raw <= min_val) return 0;
    if (raw >= max_val) return 4095;
    return (uint16_t)(((uint32_t)(raw - min_val) * 4095u) / (max_val - min_val));
}

// Map a 12-bit ADC value [0, 4095] to a full signed 16-bit XInput axis [-32768, +32767].
// This covers the complete XInput range so Windows sees 0%–100% travel.
static inline int16_t adc_to_axis(uint16_t val) {
    // val=0 → -32768, val=4095 → +32767
    // Use 32-bit multiply to avoid overflow: 4095 * 65535 = 0xFFFE_FEA1, fits in uint32_t
    return (int16_t)(((uint32_t)val * 65535u / 4095u) - 32768u);
}

// ── EMA (Exponential Moving Average) smoothing ───────────────────────────────
// Smooths jittery analog readings without adding noticeable latency.
// State is a fixed-point value scaled by 256 (8 fractional bits).
// alpha = smoothing factor in [1..255]; higher = faster response (less smoothing).
//   alpha=255 → effectively no smoothing (nearly pass-through)
//   alpha=128 → ~50% weight on new sample (moderate)
//   alpha= 32 → ~12% weight on new sample (heavy)
// The alpha value is read from g_config.ema_alpha (set by the configurator).
// A stored value of 0 means 255 (no smoothing), since the slider level 0 maps
// to alpha 255 and is stored as 0 to keep the default-flash value clean.
#define EMA_ALPHA_DEFAULT   90u   // Fallback only — superseded by g_config.ema_alpha

// Resolve the config alpha: 0 stored → 255 (no smoothing); else use as-is.
static inline uint32_t config_ema_alpha(void) {
    return (g_config.ema_alpha == 0) ? 255u : (uint32_t)g_config.ema_alpha;
}

typedef struct {
    uint32_t state;    // Fixed-point: actual_value * 256
    bool     seeded;
} ema_state_t;

static ema_state_t g_ema_whammy;
static ema_state_t g_ema_tilt;

static uint16_t ema_update(ema_state_t *ema, uint16_t raw, uint32_t alpha) {
    uint32_t raw32 = (uint32_t)raw << 8;   // scale to fixed-point
    if (!ema->seeded) {
        ema->state  = raw32;
        ema->seeded = true;
    } else {
        // state = state + alpha * (raw - state) / 256
        if (raw32 > ema->state)
            ema->state += (alpha * (raw32 - ema->state)) >> 8;
        else
            ema->state -= (alpha * (ema->state - raw32)) >> 8;
    }
    return (uint16_t)(ema->state >> 8);   // back to [0, 4095]
}

static void build_report(xinput_report_t *report) {
    uint32_t now_us = time_us_32();
    uint32_t debounce_us = (uint32_t)g_config.debounce_ms * 1000;

    memset(report, 0, sizeof(xinput_report_t));
    report->report_id   = 0x00;
    report->report_size = 0x14;

    uint16_t buttons = 0;
    uint16_t pressed = 0;  // For LED mapping

    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        bool raw = read_pin(g_config.pin_buttons[i]);
        bool is_pressed = debounce(&g_debounce[i], raw, now_us, debounce_us);
        if (is_pressed) {
            buttons |= button_masks[i];
            pressed |= (1u << i);
        }
    }
    report->buttons = buttons;

    // ── Whammy ──────────────────────────────────────────────────────────────
    // XInput guitar alternate subtype maps right_stick_x as:
    //   -32768 = 0% (rest / released)
    //   +32767 = 100% (fully pressed)
    // So we use the full bipolar adc_to_axis() mapping:
    //   ADC 0    → -32768 (0%)
    //   ADC 4095 → +32767 (100%)
    // With sensitivity min/max: apply_sensitivity() maps rest → 0 → -32768 (0%).
    // right_stick_x is initialised to -32768 (0% = released) before any input runs.
    report->right_stick_x = -32768;  // default: 0% whammy

    bool whammy_active = false;
    if (g_config.whammy_mode == INPUT_MODE_ANALOG &&
        g_config.pin_whammy_analog >= 26 && g_config.pin_whammy_analog <= 28) {
        uint16_t raw    = read_adc_pin(g_config.pin_whammy_analog);
        uint16_t scaled = apply_sensitivity(raw, g_config.whammy_min, g_config.whammy_max);
        uint16_t smooth = ema_update(&g_ema_whammy, scaled, config_ema_alpha());
        if (g_config.whammy_invert) smooth = 4095 - smooth;
        report->right_stick_x = adc_to_axis(smooth);
        whammy_active = (smooth > ADC_RESOLUTION / 4);
    } else if (g_config.whammy_mode == INPUT_MODE_DIGITAL &&
               g_config.pin_whammy_digital >= 0) {
        bool raw = read_pin(g_config.pin_whammy_digital);
        bool p   = debounce(&g_debounce_whammy, raw, now_us, debounce_us);
        report->right_stick_x = p ? DIGITAL_AXIS_ON : -32768;
        whammy_active = p;
    }
    // If whammy is disabled, right_stick_x stays -32768 (0%).
    if (whammy_active) pressed |= (1u << LED_INPUT_WHAMMY);

    // ── Tilt ────────────────────────────────────────────────────────────────
    bool tilt_active = false;
    if (g_config.tilt_mode == INPUT_MODE_ANALOG) {
        uint16_t raw    = read_adc_pin(g_config.pin_tilt_analog);
        uint16_t scaled = apply_sensitivity(raw, g_config.tilt_min, g_config.tilt_max);
        uint16_t smooth = ema_update(&g_ema_tilt, scaled, config_ema_alpha());
        if (g_config.tilt_invert) smooth = 4095 - smooth;
        report->right_stick_y = adc_to_axis(smooth);
        tilt_active = (smooth > ADC_RESOLUTION / 4);
    } else if (g_config.tilt_mode == INPUT_MODE_I2C_ADXL345 ||
               g_config.tilt_mode == INPUT_MODE_I2C_LIS3DH) {
        if (g_i2c_tilt_ready) {
            bool use_lis3dh = (g_config.i2c_model == I2C_MODEL_LIS3DH);
            int16_t raw = use_lis3dh
                ? lis3dh_read_axis(g_config.adxl345_axis)
                : adxl345_read_axis(g_config.adxl345_axis);
            uint16_t scaled = use_lis3dh
                ? lis3dh_to_adc_scale(raw)
                : adxl345_to_adc_scale(raw);
            uint16_t sensed = apply_sensitivity(scaled, g_config.tilt_min, g_config.tilt_max);
            uint16_t smooth = ema_update(&g_ema_tilt, sensed, config_ema_alpha());
            if (g_config.tilt_invert) smooth = 4095 - smooth;
            report->right_stick_y = adc_to_axis(smooth);
            int diff = (int)smooth - (int)g_i2c_tilt_baseline;
            if (diff < 0) diff = -diff;
            tilt_active = (diff > ADC_RESOLUTION / 4);
        }
    } else {
        bool raw = read_pin(g_config.pin_tilt_digital);
        bool p   = debounce(&g_debounce_tilt, raw, now_us, debounce_us);
        report->right_stick_y = p ? DIGITAL_AXIS_ON : 0;
        tilt_active = p;
    }
    if (tilt_active) pressed |= (1u << LED_INPUT_TILT);

    // ── 5-pin Joystick ──────────────────────────────────────────────────────
    {
        int16_t joy_x_raw = 0, joy_y_raw = 0;
        bool joy_x_valid = (g_config.pin_joy_x >= 26 && g_config.pin_joy_x <= 28);
        bool joy_y_valid = (g_config.pin_joy_y >= 26 && g_config.pin_joy_y <= 28);

        if (joy_x_valid) joy_x_raw = (int16_t)read_adc_pin(g_config.pin_joy_x) - 2048;
        if (joy_y_valid) joy_y_raw = (int16_t)read_adc_pin(g_config.pin_joy_y) - 2048;

        int16_t dz = (int16_t)g_config.joy_deadzone;

        // ── Joystick whammy ─────────────────────────────────────────────────
        // Maps bi-directional joystick deflection to whammy (both + and - press).
        // Uses the same bipolar scale as the whammy bar:
        //   rest (within deadzone) → -32768 (0%)
        //   full deflection        → +32767 (100%)
        // Merged with physical whammy bar by taking whichever is higher.
        if (g_config.joy_whammy_axis != 0) {
            bool axis_valid = (g_config.joy_whammy_axis == 1) ? joy_x_valid : joy_y_valid;
            if (axis_valid) {
                int16_t raw     = (g_config.joy_whammy_axis == 1) ? joy_x_raw : joy_y_raw;
                int16_t abs_raw = (raw < 0) ? -raw : raw;

                int16_t joy_whammy_out;
                if (abs_raw <= dz) {
                    // Inside deadzone — no whammy contribution (0%)
                    joy_whammy_out = -32768;
                } else {
                    // Map deadzone-edge..2047 → -32768..+32767 (bipolar, matches whammy bar)
                    int32_t travel     = (int32_t)(abs_raw - dz);
                    int32_t max_travel = 2047 - dz;
                    if (max_travel < 1) max_travel = 1;
                    int32_t out = ((travel * 65535) / max_travel) - 32768;
                    if (out >  32767) out =  32767;
                    if (out < -32768) out = -32768;
                    joy_whammy_out = (int16_t)out;
                }

                // Merge: higher value wins (both sources work simultaneously)
                if (joy_whammy_out > report->right_stick_x)
                    report->right_stick_x = joy_whammy_out;
            }
        }

        // ── DPad from joystick X axis ───────────────────────────────────────
        if (g_config.joy_dpad_x && joy_x_valid) {
            uint16_t btn_pos = g_config.joy_dpad_x_invert ? GUITAR_BTN_DPAD_LEFT  : GUITAR_BTN_DPAD_RIGHT;
            uint16_t btn_neg = g_config.joy_dpad_x_invert ? GUITAR_BTN_DPAD_RIGHT : GUITAR_BTN_DPAD_LEFT;
            if      (joy_x_raw >  dz) report->buttons |= btn_pos;
            else if (joy_x_raw < -dz) report->buttons |= btn_neg;
        }

        // ── DPad from joystick Y axis ───────────────────────────────────────
        if (g_config.joy_dpad_y && joy_y_valid) {
            uint16_t btn_pos = g_config.joy_dpad_y_invert ? GUITAR_BTN_DPAD_UP   : GUITAR_BTN_DPAD_DOWN;
            uint16_t btn_neg = g_config.joy_dpad_y_invert ? GUITAR_BTN_DPAD_DOWN : GUITAR_BTN_DPAD_UP;
            if      (joy_y_raw >  dz) report->buttons |= btn_pos;
            else if (joy_y_raw < -dz) report->buttons |= btn_neg;
        }

        // ── Joystick click → Guide button ───────────────────────────────────
        if (g_config.pin_joy_sw >= 0) {
            if (read_pin(g_config.pin_joy_sw))
                report->buttons |= GUITAR_BTN_GUIDE;
        }
    }

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

    // Set custom device name for USB string descriptors
    if (g_config.device_name[0] != '\0') {
        g_device_name = g_config.device_name;
    }

    if (enter_config) {
        g_config_mode = true;
        tusb_init();
        while (true) {
            tud_task();
            onboard_led_blink_config();
            if (tud_cdc_connected()) {
                gpio_put(ONBOARD_LED_PIN, true);
                config_mode_main(&g_config);
            }
        }
    } else {
        g_config_mode = false;
        gpio_put(ONBOARD_LED_PIN, true);

        // Initialize APA102 LED strip BEFORE GPIO init
        // so SPI pins (GP3, GP6) are claimed and won't be
        // reconfigured as button inputs
        static led_config_t aligned_leds;
        memcpy(&aligned_leds, &g_config.leds, sizeof(led_config_t));

        if (aligned_leds.enabled) {
            apa102_init();
        }

        // Initialize I2C tilt (ADXL345 or LIS3DH) BEFORE GPIO init
        // so I2C pins aren't reconfigured
        init_i2c_tilt();

        init_all_gpio();
        init_adc();
        memset(g_debounce, 0, sizeof(g_debounce));
        memset(&g_debounce_tilt, 0, sizeof(g_debounce_tilt));
        memset(&g_debounce_whammy, 0, sizeof(g_debounce_whammy));
        memset(&g_ema_whammy, 0, sizeof(g_ema_whammy));
        memset(&g_ema_tilt,   0, sizeof(g_ema_tilt));

        // Show idle LED state
        if (aligned_leds.enabled) {
            apa102_update_from_inputs(&aligned_leds, 0);
        }

        tusb_init();

        xinput_report_t report;
        uint64_t last_report_us = 0;
        uint64_t last_led_us = 0;

        while (true) {
            tud_task();
            if (xinput_magic_detected()) {
                request_config_mode_reboot();
            }

            uint64_t now_us = time_us_64();

            if (now_us - last_report_us >= REPORT_INTERVAL_US) {
                last_report_us = now_us;
                if (xinput_ready()) {
                    build_report(&report);
                    xinput_send_report(&report);
                }
            }

            // Update LEDs at ~60Hz (non-blocking DMA transfer)
            if (aligned_leds.enabled &&
                (now_us - last_led_us >= LED_UPDATE_INTERVAL_US)) {
                last_led_us = now_us;
                apa102_update_from_inputs(&aligned_leds, g_pressed_mask);
            }
        }
    }
    return 0;
}
