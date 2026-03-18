/*
 * main.c - Pico W Combined Wireless Guitar Controller Firmware
 *
 * Supports wired USB XInput, wireless Dongle mode, and wireless Bluetooth HID.
 *
 * Boot flow:
 *   1. Check watchdog scratch[0] → USB CDC config mode (unchanged from before)
 *   2. Initialize USB and wait up to USB_MOUNT_TIMEOUT_MS:
 *      - If a USB host enumerates → USB XInput play mode (wired, configurator works)
 *      - If timeout expires with no host → wireless mode
 *   3. Wireless mode selection (when no USB host):
 *      a. Check watchdog scratch[1]:
 *         - WATCHDOG_BT_OVERRIDE_MAGIC     → boot into Bluetooth HID (one-time)
 *         - WATCHDOG_DONGLE_OVERRIDE_MAGIC → boot into Dongle mode (one-time)
 *         scratch[1] is always cleared after reading.
 *      b. Otherwise use g_config.wireless_default_mode:
 *         - WIRELESS_DEFAULT_DONGLE (0)    → Dongle BLE mode (factory default)
 *         - WIRELESS_DEFAULT_BLUETOOTH (1) → Bluetooth HID mode
 *
 * GUIDE button hold (3 seconds) — switches wireless mode for current session:
 *   Dongle mode  → hold GUIDE 3s → reboots into Bluetooth HID mode
 *   Bluetooth    → hold GUIDE 3s → reboots into Dongle mode
 *   This can be repeated back and forth without limit.
 *   It does NOT change the stored wireless_default_mode setting.
 *
 * Configurator access:
 *   - Plug in USB → wired mode → configurator detects it normally
 *   - Magic vibration sequence (USB) → config mode reboot
 *   - SELECT held at boot → config mode (fallback for no-USB scenarios)
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
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
#include "controller_bt.h"      // Dongle BLE broadcaster
#include "bt_hid_gamepad.h"     // Bluetooth HID gamepad

#define REPORT_INTERVAL_US      1000      // ~1000 Hz for USB XInput
#define BT_REPORT_INTERVAL_US   4000      // ~250 Hz for BLE/BT wireless
#define LED_UPDATE_INTERVAL_US  16667     // ~60 Hz LED refresh
#define ADC_RESOLUTION          4095
#define DIGITAL_AXIS_ON         32767

// Time to wait for a USB host to enumerate before going wireless.
#define USB_MOUNT_TIMEOUT_MS    1000

// How long GUIDE must be held (in dongle mode) to trigger a switch to BT HID.
#define GUIDE_HOLD_TO_BT_MS     3000

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

// I2C tilt baseline
static uint16_t g_i2c_tilt_baseline = 2048;
static bool     g_i2c_tilt_ready = false;

//--------------------------------------------------------------------
// CYW43 LED wrappers (Pico W onboard LED)
//--------------------------------------------------------------------

static bool g_cyw43_initialized = false;

static void picow_led_set(bool on) {
    if (g_cyw43_initialized) {
        cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, on ? 1 : 0);
    }
}

static void picow_led_blink_config(void) {
    static uint32_t last_toggle = 0;
    static int phase = 0;
    uint32_t now = to_ms_since_boot(get_absolute_time());
    const uint32_t pattern[] = {100, 100, 100, 700};
    if (now - last_toggle >= pattern[phase % 4]) {
        last_toggle = now;
        picow_led_set((phase % 2) == 0);
        phase++;
    }
}

static void picow_led_blink_bt_waiting(void) {
    static uint32_t last_toggle = 0;
    static bool state = false;
    uint32_t now = to_ms_since_boot(get_absolute_time());
    if (now - last_toggle >= 500) {
        last_toggle = now;
        state = !state;
        picow_led_set(state);
    }
}

static void picow_led_blink_usb_waiting(void) {
    static uint32_t last_toggle = 0;
    static bool state = false;
    uint32_t now = to_ms_since_boot(get_absolute_time());
    if (now - last_toggle >= 150) {
        last_toggle = now;
        state = !state;
        picow_led_set(state);
    }
}

// Blinks at a rate that speeds up over 'progress_ms' out of 'total_ms'.
// Used as a visual countdown indicator for the GUIDE hold switch.
static void picow_led_blink_countdown(uint32_t progress_ms, uint32_t total_ms) {
    static uint32_t last_toggle = 0;
    static bool state = false;
    uint32_t now = to_ms_since_boot(get_absolute_time());
    // Interpolate blink interval from 500ms (start) down to 80ms (end)
    uint32_t interval = 500 - (progress_ms * 420 / total_ms);
    if (interval < 80) interval = 80;
    if (now - last_toggle >= interval) {
        last_toggle = now;
        state = !state;
        picow_led_set(state);
    }
}

//--------------------------------------------------------------------
// USB mount state tracking
//--------------------------------------------------------------------

static volatile bool g_usb_mounted = false;

//--------------------------------------------------------------------
// Watchdog scratch registers
//--------------------------------------------------------------------

static bool check_scratch_config_mode(void) {
    if (watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC) {
        watchdog_hw->scratch[0] = 0;
        return true;
    }
    return false;
}

// Check scratch[1] for a one-time override to boot into BT HID mode.
// Written by GUIDE hold in dongle mode. Clears itself.
static bool check_scratch_bt_override(void) {
    if (watchdog_hw->scratch[1] == WATCHDOG_BT_OVERRIDE_MAGIC) {
        watchdog_hw->scratch[1] = 0;
        return true;
    }
    return false;
}

// Check scratch[1] for a one-time override to boot into Dongle mode.
// Written by GUIDE hold in BT HID mode. Clears itself.
static bool check_scratch_dongle_override(void) {
    if (watchdog_hw->scratch[1] == WATCHDOG_DONGLE_OVERRIDE_MAGIC) {
        watchdog_hw->scratch[1] = 0;
        return true;
    }
    return false;
}

static void request_config_mode_reboot(void) {
    led_config_t tmp;
    memcpy(&tmp, &g_config.leds, sizeof(led_config_t));
    apa102_all_off(&tmp);
    watchdog_hw->scratch[0] = WATCHDOG_CONFIG_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

static void request_bt_mode_reboot(void) {
    led_config_t tmp;
    memcpy(&tmp, &g_config.leds, sizeof(led_config_t));
    apa102_all_off(&tmp);
    watchdog_hw->scratch[1] = WATCHDOG_BT_OVERRIDE_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

static void request_dongle_mode_reboot(void) {
    led_config_t tmp;
    memcpy(&tmp, &g_config.leds, sizeof(led_config_t));
    apa102_all_off(&tmp);
    watchdog_hw->scratch[1] = WATCHDOG_DONGLE_OVERRIDE_MAGIC;
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

static inline bool is_picow_reserved(int8_t pin) {
    // Pico W: GPIO23, 24, 25, 29 are used by CYW43 chip
    return (pin == 23 || pin == 24 || pin == 25 || pin == 29);
}

static void init_gpio_pin(int8_t pin) {
    if (pin < 0 || pin > 28) return;
    if (is_led_spi_pin(pin)) return;
    if (is_picow_reserved(pin)) return;
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
    if (is_picow_reserved(pin)) return false;
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

static uint16_t apply_sensitivity(uint16_t raw, uint16_t min_val, uint16_t max_val) {
    if (max_val <= min_val) return raw;
    if (raw <= min_val) return 0;
    if (raw >= max_val) return 4095;
    return (uint16_t)(((uint32_t)(raw - min_val) * 4095u) / (max_val - min_val));
}

static inline int16_t adc_to_axis(uint16_t val) {
    return (int16_t)(((uint32_t)val * 65535u / 4095u) - 32768u);
}

// ── EMA smoothing ──
static inline uint32_t config_ema_alpha(void) {
    return (g_config.ema_alpha == 0) ? 255u : (uint32_t)g_config.ema_alpha;
}

typedef struct {
    uint32_t state;
    bool     seeded;
} ema_state_t;

static ema_state_t g_ema_whammy;
static ema_state_t g_ema_tilt;

static uint16_t ema_update(ema_state_t *ema, uint16_t raw, uint32_t alpha) {
    uint32_t raw32 = (uint32_t)raw << 8;
    if (!ema->seeded) {
        ema->state  = raw32;
        ema->seeded = true;
    } else {
        if (raw32 > ema->state)
            ema->state += (alpha * (raw32 - ema->state)) >> 8;
        else
            ema->state -= (alpha * (ema->state - raw32)) >> 8;
    }
    return (uint16_t)(ema->state >> 8);
}

//--------------------------------------------------------------------
// Shared input reading — fills button/axis values used by all
// wireless and USB report builders
//--------------------------------------------------------------------

typedef struct {
    uint16_t buttons;
    uint16_t pressed_mask;
    int16_t  right_stick_x;   // Whammy
    int16_t  right_stick_y;   // Tilt
} input_state_t;

static void read_all_inputs(input_state_t *state) {
    uint32_t now_us = time_us_32();
    uint32_t debounce_us = (uint32_t)g_config.debounce_ms * 1000;

    uint16_t buttons = 0;
    uint16_t pressed = 0;

    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        bool raw = read_pin(g_config.pin_buttons[i]);
        bool is_pressed = debounce(&g_debounce[i], raw, now_us, debounce_us);
        if (is_pressed) {
            buttons |= button_masks[i];
            pressed |= (1u << i);
        }
    }
    state->buttons = buttons;

    // ── Whammy ──
    state->right_stick_x = -32768;
    bool whammy_active = false;
    if (g_config.whammy_mode == INPUT_MODE_ANALOG &&
        g_config.pin_whammy_analog >= 26 && g_config.pin_whammy_analog <= 28) {
        uint16_t raw    = read_adc_pin(g_config.pin_whammy_analog);
        uint16_t scaled = apply_sensitivity(raw, g_config.whammy_min, g_config.whammy_max);
        uint16_t smooth = ema_update(&g_ema_whammy, scaled, config_ema_alpha());
        if (g_config.whammy_invert) smooth = 4095 - smooth;
        state->right_stick_x = adc_to_axis(smooth);
        whammy_active = (smooth > ADC_RESOLUTION / 4);
    } else if (g_config.whammy_mode == INPUT_MODE_DIGITAL &&
               g_config.pin_whammy_digital >= 0) {
        bool raw = read_pin(g_config.pin_whammy_digital);
        bool p   = debounce(&g_debounce_whammy, raw, now_us, debounce_us);
        state->right_stick_x = p ? DIGITAL_AXIS_ON : -32768;
        whammy_active = p;
    }
    if (whammy_active) pressed |= (1u << LED_INPUT_WHAMMY);

    // ── Tilt ──
    state->right_stick_y = 0;
    bool tilt_active = false;
    if (g_config.tilt_mode == INPUT_MODE_ANALOG) {
        uint16_t raw    = read_adc_pin(g_config.pin_tilt_analog);
        uint16_t scaled = apply_sensitivity(raw, g_config.tilt_min, g_config.tilt_max);
        uint16_t smooth = ema_update(&g_ema_tilt, scaled, config_ema_alpha());
        if (g_config.tilt_invert) smooth = 4095 - smooth;
        state->right_stick_y = adc_to_axis(smooth);
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
            state->right_stick_y = adc_to_axis(smooth);
            int diff = (int)smooth - (int)g_i2c_tilt_baseline;
            if (diff < 0) diff = -diff;
            tilt_active = (diff > ADC_RESOLUTION / 4);
        }
    } else {
        bool raw = read_pin(g_config.pin_tilt_digital);
        bool p   = debounce(&g_debounce_tilt, raw, now_us, debounce_us);
        state->right_stick_y = p ? DIGITAL_AXIS_ON : 0;
        tilt_active = p;
    }
    if (tilt_active) pressed |= (1u << LED_INPUT_TILT);

    // ── 5-pin Joystick ──
    {
        int16_t joy_x_raw = 0, joy_y_raw = 0;
        bool joy_x_valid = (g_config.pin_joy_x >= 26 && g_config.pin_joy_x <= 28);
        bool joy_y_valid = (g_config.pin_joy_y >= 26 && g_config.pin_joy_y <= 28);

        if (joy_x_valid) joy_x_raw = (int16_t)read_adc_pin(g_config.pin_joy_x) - 2048;
        if (joy_y_valid) joy_y_raw = (int16_t)read_adc_pin(g_config.pin_joy_y) - 2048;

        int16_t dz = (int16_t)g_config.joy_deadzone;

        if (g_config.joy_whammy_axis != 0) {
            bool axis_valid = (g_config.joy_whammy_axis == 1) ? joy_x_valid : joy_y_valid;
            if (axis_valid) {
                int16_t raw     = (g_config.joy_whammy_axis == 1) ? joy_x_raw : joy_y_raw;
                int16_t abs_raw = (raw < 0) ? -raw : raw;

                int16_t joy_whammy_out;
                if (abs_raw <= dz) {
                    joy_whammy_out = -32768;
                } else {
                    int32_t travel     = (int32_t)(abs_raw - dz);
                    int32_t max_travel = 2047 - dz;
                    if (max_travel < 1) max_travel = 1;
                    int32_t out = ((travel * 65535) / max_travel) - 32768;
                    if (out >  32767) out =  32767;
                    if (out < -32768) out = -32768;
                    joy_whammy_out = (int16_t)out;
                }
                if (joy_whammy_out > state->right_stick_x)
                    state->right_stick_x = joy_whammy_out;
            }
        }

        if (g_config.joy_dpad_x && joy_x_valid) {
            uint16_t btn_pos = g_config.joy_dpad_x_invert ? GUITAR_BTN_DPAD_LEFT  : GUITAR_BTN_DPAD_RIGHT;
            uint16_t btn_neg = g_config.joy_dpad_x_invert ? GUITAR_BTN_DPAD_RIGHT : GUITAR_BTN_DPAD_LEFT;
            if      (joy_x_raw >  dz) buttons |= btn_pos;
            else if (joy_x_raw < -dz) buttons |= btn_neg;
        }

        if (g_config.joy_dpad_y && joy_y_valid) {
            uint16_t btn_pos = g_config.joy_dpad_y_invert ? GUITAR_BTN_DPAD_UP   : GUITAR_BTN_DPAD_DOWN;
            uint16_t btn_neg = g_config.joy_dpad_y_invert ? GUITAR_BTN_DPAD_DOWN : GUITAR_BTN_DPAD_UP;
            if      (joy_y_raw >  dz) buttons |= btn_pos;
            else if (joy_y_raw < -dz) buttons |= btn_neg;
        }

        if (g_config.pin_joy_sw >= 0) {
            if (read_pin(g_config.pin_joy_sw))
                buttons |= GUITAR_BTN_GUIDE;
        }

        state->buttons = buttons;
    }

    state->pressed_mask = pressed;
    g_pressed_mask = pressed;
}

//--------------------------------------------------------------------
// Report builders
//--------------------------------------------------------------------

static void build_xinput_report(xinput_report_t *report) {
    input_state_t inp;
    read_all_inputs(&inp);
    memset(report, 0, sizeof(xinput_report_t));
    report->report_id     = 0x00;
    report->report_size   = 0x14;
    report->buttons       = inp.buttons;
    report->right_stick_x = inp.right_stick_x;
    report->right_stick_y = inp.right_stick_y;
}

static void build_wireless_dongle_report(controller_report_t *report) {
    input_state_t inp;
    read_all_inputs(&inp);
    memset(report, 0, sizeof(controller_report_t));
    report->buttons       = inp.buttons;
    report->right_stick_x = inp.right_stick_x;
    report->right_stick_y = inp.right_stick_y;
}

static void build_bt_hid_report(bt_hid_report_t *report) {
    input_state_t inp;
    read_all_inputs(&inp);
    memset(report, 0, sizeof(bt_hid_report_t));
    report->report_id      = 0x01;
    report->buttons        = inp.buttons;
    report->right_stick_x  = inp.right_stick_x;
    report->right_stick_y  = inp.right_stick_y;
}

//--------------------------------------------------------------------
// TinyUSB callbacks
//--------------------------------------------------------------------

void tud_mount_cb(void)   { g_usb_mounted = true; }
void tud_umount_cb(void)  { g_usb_mounted = false; }
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; }
void tud_resume_cb(void)  {}

//--------------------------------------------------------------------
// SELECT held at boot → config mode fallback
//--------------------------------------------------------------------

static bool check_select_held_at_boot(void) {
    int8_t select_pin = g_config.pin_buttons[BTN_IDX_SELECT];
    if (select_pin < 0 || select_pin > 28) return false;
    if (is_picow_reserved(select_pin)) return false;

    gpio_init(select_pin);
    gpio_set_dir(select_pin, GPIO_IN);
    gpio_pull_up(select_pin);
    sleep_ms(20);

    bool held = !gpio_get(select_pin);
    if (held) {
        sleep_ms(200);
        held = !gpio_get(select_pin);
    }
    return held;
}

//--------------------------------------------------------------------
// Pairing status LED blink helper
//
// Blinks all LEDs in a solid color at 500 ms intervals while the
// controller is searching for a wireless connection:
//   - Yellow (255, 200, 0) → waiting to pair in Dongle mode
//   - Blue   (0,   0, 255) → waiting to pair in Bluetooth HID mode
//
// Call apa102_update_from_inputs() once connected to restore the
// user's configured color scheme.
//--------------------------------------------------------------------

static led_config_t g_aligned_leds;   // declared here so apa102_blink_pairing can use it

static void apa102_blink_pairing(uint8_t r, uint8_t g, uint8_t b) {
    if (!g_aligned_leds.enabled) return;

    static uint32_t last_toggle_ms = 0;
    static bool     leds_on = true;
    uint32_t now_ms = to_ms_since_boot(get_absolute_time());

    if (now_ms - last_toggle_ms >= 500) {
        last_toggle_ms = now_ms;
        leds_on = !leds_on;
    }

    // Build a temporary led_config_t that is identical to the user's
    // config (same count, same brightness) but with every LED set to
    // the requested pairing color.
    led_config_t tmp;
    memcpy(&tmp, &g_aligned_leds, sizeof(led_config_t));
    uint8_t n = (tmp.count > 0) ? tmp.count : MAX_LEDS;
    for (int i = 0; i < n && i < MAX_LEDS; i++) {
        tmp.colors[i].r = r;
        tmp.colors[i].g = g;
        tmp.colors[i].b = b;
    }

    // Build brightness array: use base_brightness when on, 0 when off
    uint8_t brightness[MAX_LEDS];
    uint8_t brt = (tmp.base_brightness > 0) ? tmp.base_brightness : 5;
    for (int i = 0; i < MAX_LEDS; i++) {
        brightness[i] = (leds_on && i < n) ? brt : 0;
    }

    apa102_update(&tmp, brightness);
}

//--------------------------------------------------------------------
// Shared play-mode hardware init
//--------------------------------------------------------------------

static void init_play_mode_hardware(void) {
    memcpy(&g_aligned_leds, &g_config.leds, sizeof(led_config_t));

    if (g_aligned_leds.enabled) {
        apa102_init();
    }

    init_i2c_tilt();
    init_all_gpio();
    init_adc();
    memset(g_debounce, 0, sizeof(g_debounce));
    memset(&g_debounce_tilt, 0, sizeof(g_debounce_tilt));
    memset(&g_debounce_whammy, 0, sizeof(g_debounce_whammy));
    memset(&g_ema_whammy, 0, sizeof(g_ema_whammy));
    memset(&g_ema_tilt,   0, sizeof(g_ema_tilt));

    if (g_aligned_leds.enabled) {
        apa102_update_from_inputs(&g_aligned_leds, 0);
    }
}

//--------------------------------------------------------------------
// Main
//--------------------------------------------------------------------

int main(void) {
    stdio_init_all();

    // Initialize CYW43 early — needed for the onboard LED and all wireless modes
    if (cyw43_arch_init()) {
        // CYW43 init failed — USB modes will still work
    } else {
        g_cyw43_initialized = true;
    }

    picow_led_set(true);  // LED on during boot

    config_load(&g_config);

    // Set custom device name for USB string descriptors
    if (g_config.device_name[0] != '\0') {
        g_device_name = g_config.device_name;
    }

    // ── Step 1: Check for config mode via watchdog scratch[0] ──
    bool enter_config = check_scratch_config_mode();

    if (enter_config) {
        // ═══════════════════════════════════════════════════════════════
        // CONFIG MODE — USB CDC serial
        // Configurator connects here to read/write settings.
        // ═══════════════════════════════════════════════════════════════
        g_config_mode = true;
        tusb_init();

        while (true) {
            tud_task();
            if (g_cyw43_initialized) cyw43_arch_poll();
            picow_led_blink_config();

            if (tud_cdc_connected()) {
                picow_led_set(true);
                config_mode_main(&g_config);
            }
        }
    }

    // ── Step 2: Check scratch[1] for a GUIDE-hold mode override ──
    // Both values are mutually exclusive — read and clear whichever is set.
    // bt_override:     set by GUIDE hold in dongle mode → force BT HID this boot
    // dongle_override: set by GUIDE hold in BT mode     → force Dongle this boot
    bool bt_override     = check_scratch_bt_override();
    bool dongle_override = !bt_override && check_scratch_dongle_override();

    // ── Step 3: Try USB XInput first ──
    // Always start TinyUSB and give a real USB host time to enumerate.
    g_config_mode = false;
    tusb_init();

    {
        uint32_t start_ms = to_ms_since_boot(get_absolute_time());

        while (!g_usb_mounted) {
            tud_task();
            if (g_cyw43_initialized) cyw43_arch_poll();
            picow_led_blink_usb_waiting();

            uint32_t elapsed = to_ms_since_boot(get_absolute_time()) - start_ms;
            if (elapsed >= USB_MOUNT_TIMEOUT_MS) {
                break;  // No USB host — fall through to wireless
            }

            if (elapsed >= (USB_MOUNT_TIMEOUT_MS - 500)) {
                if (check_select_held_at_boot()) {
                    request_config_mode_reboot();
                }
            }

            sleep_ms(1);
        }
    }

    // ── Step 4: Initialize shared play-mode hardware ──
    init_play_mode_hardware();

    // ── Step 5: Enter the appropriate play mode ──

    if (g_usb_mounted) {
        // ═══════════════════════════════════════════════════════════════
        // USB XINPUT PLAY MODE — Wired controller
        // A USB host enumerated us. Run as XInput gamepad.
        // Configurator detects this, sends magic vibration → config mode.
        // ═══════════════════════════════════════════════════════════════
        picow_led_set(true);

        xinput_report_t report;
        uint64_t last_report_us = 0;
        uint64_t last_led_us = 0;

        while (true) {
            tud_task();
            if (g_cyw43_initialized) cyw43_arch_poll();

            if (xinput_magic_detected()) {
                request_config_mode_reboot();
            }

            uint64_t now_us = time_us_64();

            if (now_us - last_report_us >= REPORT_INTERVAL_US) {
                last_report_us = now_us;
                if (xinput_ready()) {
                    build_xinput_report(&report);
                    xinput_send_report(&report);
                }
            }

            if (g_aligned_leds.enabled &&
                (now_us - last_led_us >= LED_UPDATE_INTERVAL_US)) {
                last_led_us = now_us;
                apa102_update_from_inputs(&g_aligned_leds, g_pressed_mask);
            }
        }

    } else {
        // ── No USB host: choose wireless mode ──
        //
        // Priority order:
        //   1. bt_override     (scratch[1] = BT magic,     set by GUIDE hold in dongle) → BT HID
        //   2. dongle_override (scratch[1] = Dongle magic, set by GUIDE hold in BT)     → Dongle
        //   3. g_config.wireless_default_mode
        bool use_bt_hid;
        if (bt_override)
            use_bt_hid = true;
        else if (dongle_override)
            use_bt_hid = false;
        else
            use_bt_hid = (g_config.wireless_default_mode == WIRELESS_DEFAULT_BLUETOOTH);

        const char *bt_name = (g_config.device_name[0] != '\0')
                              ? g_config.device_name
                              : "Guitar Controller";

        if (!use_bt_hid) {
            // ═══════════════════════════════════════════════════════════
            // WIRELESS DONGLE MODE
            //
            // Broadcasts gamepad report via BLE advertisements.
            // The USB dongle passively scans and reads the data.
            // No BLE connection is established — always broadcasting.
            // The controller is always ready to pair; no sync button needed.
            //
            // APA102 LEDs blink yellow continuously in dongle mode.
            //
            // GUIDE BUTTON HOLD (3 s): reboots into Bluetooth HID mode.
            // Hold GUIDE again in BT mode to switch back. Repeatable.
            // ═══════════════════════════════════════════════════════════

            if (g_cyw43_initialized) {
                controller_bt_init(bt_name);
                controller_bt_start_sync();
            }

            controller_report_t dongle_report;
            uint64_t last_report_us = 0;
            uint64_t last_led_us = 0;

            // ── Dongle pairing blink timeout ──
            // Since dongle mode is broadcast-only (no true connection handshake),
            // we blink yellow for a fixed window then switch to normal LED colors.
            // 5 seconds matches the feel of BT HID pairing feedback.
            #define DONGLE_PAIRING_BLINK_MS  5000
            uint32_t dongle_start_ms = to_ms_since_boot(get_absolute_time());
            bool     dongle_paired   = false;

            // ── GUIDE hold tracking ──
            int8_t   guide_pin = g_config.pin_buttons[BTN_IDX_GUIDE];
            bool     guide_holdable = (guide_pin >= 0 && guide_pin <= 28 &&
                                       !is_picow_reserved(guide_pin) &&
                                       !is_led_spi_pin(guide_pin));
            uint32_t guide_hold_start_ms = 0;
            bool     guide_was_held = false;

            while (true) {
                if (g_cyw43_initialized) {
                    cyw43_arch_poll();
                }

                uint32_t now_ms = to_ms_since_boot(get_absolute_time());

                // ── GUIDE hold: switch to Bluetooth HID mode ──
                bool guide_held = guide_holdable && !gpio_get(guide_pin);

                if (guide_held && !guide_was_held) {
                    guide_hold_start_ms = now_ms;
                }

                bool in_guide_countdown = false;
                if (guide_held) {
                    uint32_t held_ms = now_ms - guide_hold_start_ms;
                    if (held_ms >= GUIDE_HOLD_TO_BT_MS) {
                        request_bt_mode_reboot();  // never returns
                    }
                    picow_led_blink_countdown(held_ms, GUIDE_HOLD_TO_BT_MS);
                    in_guide_countdown = true;
                }

                guide_was_held = guide_held;

                // ── Onboard LED ──
                if (!in_guide_countdown) {
                    picow_led_blink_bt_waiting();
                }

                uint64_t now_us = time_us_64();

                // ── Broadcast wireless reports at ~250 Hz ──
                if (now_us - last_report_us >= BT_REPORT_INTERVAL_US) {
                    last_report_us = now_us;
                    build_wireless_dongle_report(&dongle_report);
                    controller_bt_send_report(&dongle_report);
                }

                // ── APA102 LED strip ──
                // Blink yellow while waiting for a dongle to pick up the broadcast.
                // After DONGLE_PAIRING_BLINK_MS, assume the dongle has synced and
                // switch to the user's configured color scheme.
                if (!dongle_paired &&
                    (to_ms_since_boot(get_absolute_time()) - dongle_start_ms >= DONGLE_PAIRING_BLINK_MS)) {
                    dongle_paired = true;
                }

                if (g_aligned_leds.enabled &&
                    (now_us - last_led_us >= LED_UPDATE_INTERVAL_US)) {
                    last_led_us = now_us;
                    if (dongle_paired) {
                        apa102_update_from_inputs(&g_aligned_leds, g_pressed_mask);
                    } else {
                        apa102_blink_pairing(255, 200, 0);
                    }
                }

                sleep_us(100);
            }

        } else {
            // ═══════════════════════════════════════════════════════════
            // BLUETOOTH HID MODE
            //
            // Becomes a BLE HID gamepad, discoverable by name.
            // Compatible with Windows 10/11, Steam, etc. directly.
            // Reached either via wireless_default_mode = 1, or via the
            // GUIDE-hold override from dongle mode.
            // ═══════════════════════════════════════════════════════════

            if (g_cyw43_initialized) {
                bt_hid_init(bt_name);
            }

            bt_hid_report_t bt_report;
            uint64_t last_report_us = 0;
            uint64_t last_led_us = 0;

            // ── GUIDE hold tracking (switch back to Dongle mode) ──
            int8_t   bt_guide_pin = g_config.pin_buttons[BTN_IDX_GUIDE];
            bool     bt_guide_holdable = (bt_guide_pin >= 0 && bt_guide_pin <= 28 &&
                                          !is_picow_reserved(bt_guide_pin) &&
                                          !is_led_spi_pin(bt_guide_pin));
            uint32_t bt_guide_hold_start_ms = 0;
            bool     bt_guide_was_held = false;

            while (true) {
                if (g_cyw43_initialized) {
                    cyw43_arch_poll();
                    bt_hid_task();
                }

                uint32_t bt_now_ms = to_ms_since_boot(get_absolute_time());

                // ── GUIDE hold: switch back to Dongle mode ──
                bool bt_guide_held = bt_guide_holdable && !gpio_get(bt_guide_pin);

                if (bt_guide_held && !bt_guide_was_held) {
                    bt_guide_hold_start_ms = bt_now_ms;
                }

                bool bt_in_countdown = false;
                if (bt_guide_held) {
                    uint32_t held_ms = bt_now_ms - bt_guide_hold_start_ms;
                    if (held_ms >= GUIDE_HOLD_TO_BT_MS) {
                        request_dongle_mode_reboot();  // never returns
                    }
                    picow_led_blink_countdown(held_ms, GUIDE_HOLD_TO_BT_MS);
                    bt_in_countdown = true;
                }

                bt_guide_was_held = bt_guide_held;

                // ── Onboard LED ──
                if (!bt_in_countdown) {
                    if (!bt_hid_connected()) {
                        picow_led_blink_bt_waiting();
                    } else {
                        picow_led_set(true);
                    }
                }

                uint64_t now_us = time_us_64();

                if (now_us - last_report_us >= BT_REPORT_INTERVAL_US) {
                    last_report_us = now_us;
                    if (bt_hid_connected() && bt_hid_ready()) {
                        build_bt_hid_report(&bt_report);
                        bt_hid_send_report(&bt_report);
                    }
                }

                if (g_aligned_leds.enabled &&
                    (now_us - last_led_us >= LED_UPDATE_INTERVAL_US)) {
                    last_led_us = now_us;

                    if (bt_hid_connected()) {
                        // Connected — show configured color scheme
                        apa102_update_from_inputs(&g_aligned_leds, g_pressed_mask);
                    } else {
                        // Waiting to pair over Bluetooth — blink blue
                        apa102_blink_pairing(0, 0, 255);
                    }
                }

                sleep_us(100);
            }
        }
    }

    return 0;
}
