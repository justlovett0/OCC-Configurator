/*
 * main.c - Pico GH Live-style 6-fret guitar firmware
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
#include "guitar_config.h"
#include "config_serial.h"
#include "apa102_leds.h"
#include "adxl345.h"
#include "lis3dh.h"
#include "xinput_driver.h"

#define REPORT_INTERVAL_US      1000
#define LED_UPDATE_INTERVAL_US  16667
#define ADC_RESOLUTION          4095
#define ADC_CENTER              2048
#define ONBOARD_LED_PIN         25
#define KEEPALIVE_TIMEOUT_MS    12000

static const uint8_t fret_masks[6] = {
    GHL_FRET_WHITE_1,
    GHL_FRET_BLACK_1,
    GHL_FRET_BLACK_2,
    GHL_FRET_BLACK_3,
    GHL_FRET_WHITE_2,
    GHL_FRET_WHITE_3,
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
static uint32_t g_start_hold_start_us = 0;
static uint32_t g_pressed_mask = 0;

static uint16_t g_i2c_tilt_baseline = 2048;
static bool     g_i2c_tilt_ready = false;

typedef struct {
    uint32_t state;
    bool     seeded;
} ema_state_t;

static ema_state_t g_ema_whammy;
static ema_state_t g_ema_tilt;

static bool check_scratch_config_mode(void) {
    if (watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC) {
        watchdog_hw->scratch[0] = 0;
        return true;
    }
    return false;
}

static bool check_scratch_xinput_mode(void) {
    if (watchdog_hw->scratch[0] == WATCHDOG_XINPUT_MAGIC) {
        watchdog_hw->scratch[0] = 0;
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

void request_xinput_mode_reboot(void) {
    led_config_t tmp;
    memcpy(&tmp, &g_config.leds, sizeof(led_config_t));
    apa102_all_off(&tmp);
    watchdog_hw->scratch[0] = WATCHDOG_XINPUT_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

static inline bool is_led_spi_pin(int8_t pin) {
    if (!g_config.leds.enabled) return false;
    int8_t data_pin = apa102_spi_data_pin_is_valid(g_config.leds.data_pin)
        ? g_config.leds.data_pin : LED_SPI_DEFAULT_DATA_PIN;
    int8_t clock_pin = apa102_spi_clock_pin_is_valid(g_config.leds.clock_pin)
        ? g_config.leds.clock_pin : LED_SPI_DEFAULT_CLOCK_PIN;
    return pin == data_pin || pin == clock_pin;
}

static void init_gpio_pin(int8_t pin) {
    if (pin < 0 || pin > 28) return;
    if (is_led_spi_pin(pin)) return;
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
}

static void init_all_gpio(void) {
    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        init_gpio_pin(g_config.pin_buttons[i]);
    }
    if (g_config.tilt_mode == INPUT_MODE_DIGITAL && g_config.pin_tilt_digital >= 0)
        init_gpio_pin(g_config.pin_tilt_digital);
    if (g_config.whammy_mode == INPUT_MODE_DIGITAL && g_config.pin_whammy_digital >= 0)
        init_gpio_pin(g_config.pin_whammy_digital);
    if (g_config.pin_joy_sw >= 0)
        init_gpio_pin(g_config.pin_joy_sw);
}

static void init_adc(void) {
    adc_init();
    if (g_config.tilt_mode == INPUT_MODE_ANALOG &&
        g_config.pin_tilt_analog >= 26 && g_config.pin_tilt_analog <= 28)
        adc_gpio_init(g_config.pin_tilt_analog);
    if (g_config.whammy_mode == INPUT_MODE_ANALOG &&
        g_config.pin_whammy_analog >= 26 && g_config.pin_whammy_analog <= 28)
        adc_gpio_init(g_config.pin_whammy_analog);
    if (g_config.pin_joy_x >= 26 && g_config.pin_joy_x <= 28)
        adc_gpio_init(g_config.pin_joy_x);
    if (g_config.pin_joy_y >= 26 && g_config.pin_joy_y <= 28)
        adc_gpio_init(g_config.pin_joy_y);
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

static bool boot_override_button_held(int8_t pin) {
    if (pin < 0 || pin > 28) return false;
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
    sleep_ms(5);
    return !gpio_get(pin);
}

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

static uint16_t apply_sensitivity(uint16_t raw, uint16_t min_val, uint16_t max_val) {
    if (max_val <= min_val) return raw;
    if (raw <= min_val) return 0;
    if (raw >= max_val) return 4095;
    return (uint16_t)(((uint32_t)(raw - min_val) * 4095u) / (max_val - min_val));
}

static inline uint32_t config_ema_alpha(void) {
    return (g_config.ema_alpha == 0) ? 255u : (uint32_t)g_config.ema_alpha;
}

static uint16_t ema_update(ema_state_t *ema, uint16_t raw, uint32_t alpha) {
    uint32_t raw32 = (uint32_t)raw << 8;
    if (!ema->seeded) {
        ema->state = raw32;
        ema->seeded = true;
    } else if (raw32 > ema->state) {
        ema->state += (alpha * (raw32 - ema->state)) >> 8;
    } else {
        ema->state -= (alpha * (ema->state - raw32)) >> 8;
    }
    return (uint16_t)(ema->state >> 8);
}

static uint8_t adc_to_u8(uint16_t val) {
    return (uint8_t)(((uint32_t)val * 255u) / 4095u);
}

static uint8_t hat_from_buttons(bool up, bool down, bool left, bool right) {
    if (up && right)  return GHL_HAT_UP_RIGHT;
    if (up && left)   return GHL_HAT_UP_LEFT;
    if (down && right) return GHL_HAT_DOWN_RIGHT;
    if (down && left)  return GHL_HAT_DOWN_LEFT;
    if (up)    return GHL_HAT_UP;
    if (down)  return GHL_HAT_DOWN;
    if (left)  return GHL_HAT_LEFT;
    if (right) return GHL_HAT_RIGHT;
    return GHL_HAT_CENTER;
}

static uint8_t collapse_to_single_fret(uint8_t fret_bits) {
    for (int i = 0; i < 6; i++) {
        if (fret_bits & fret_masks[i]) return fret_masks[i];
    }
    return 0;
}

static void build_report(ghl_hid_report_t *report, bool multibutton_enabled) {
    uint32_t now_us = time_us_32();
    uint32_t debounce_us = (uint32_t)g_config.debounce_ms * 1000u;

    memset(report, 0, sizeof(*report));
    report->strum  = GHL_STRUM_NEUTRAL;
    report->hat    = GHL_HAT_CENTER;
    report->tilt   = 0x80;
    report->whammy = 0x80;

    uint32_t pressed = 0;
    uint8_t fret_bits = 0;

    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        bool raw = read_pin(g_config.pin_buttons[i]);
        bool is_pressed = debounce(&g_debounce[i], raw, now_us, debounce_us);

        if (i == BTN_IDX_START && g_config.start_hold_enabled) {
            if (raw) {
                if (g_start_hold_start_us == 0)
                    g_start_hold_start_us = now_us;
                if ((now_us - g_start_hold_start_us) < (uint32_t)g_config.start_hold_ms * 1000u)
                    is_pressed = false;
            } else {
                g_start_hold_start_us = 0;
            }
        }

        if (!is_pressed) continue;
        pressed |= (1u << i);

        switch (i) {
            case BTN_IDX_WHITE_1: fret_bits |= GHL_FRET_WHITE_1; break;
            case BTN_IDX_BLACK_1: fret_bits |= GHL_FRET_BLACK_1; break;
            case BTN_IDX_BLACK_2: fret_bits |= GHL_FRET_BLACK_2; break;
            case BTN_IDX_BLACK_3: fret_bits |= GHL_FRET_BLACK_3; break;
            case BTN_IDX_WHITE_2: fret_bits |= GHL_FRET_WHITE_2; break;
            case BTN_IDX_WHITE_3: fret_bits |= GHL_FRET_WHITE_3; break;
            case BTN_IDX_START:      report->buttons |= GHL_BTN_START; break;
            case BTN_IDX_HERO_POWER: report->buttons |= GHL_BTN_HERO_POWER; break;
            case BTN_IDX_GHTV:       report->buttons |= GHL_BTN_GHTV; break;
            case BTN_IDX_GUIDE:      report->buttons |= GHL_BTN_GUIDE; break;
            default: break;
        }
    }

    report->fret_bits = multibutton_enabled ? fret_bits : collapse_to_single_fret(fret_bits);

    bool dpad_up = (pressed & (1u << BTN_IDX_DPAD_UP)) != 0;
    bool dpad_down = (pressed & (1u << BTN_IDX_DPAD_DOWN)) != 0;
    bool dpad_left = (pressed & (1u << BTN_IDX_DPAD_LEFT)) != 0;
    bool dpad_right = (pressed & (1u << BTN_IDX_DPAD_RIGHT)) != 0;

    if ((pressed & (1u << BTN_IDX_STRUM_UP)) && !(pressed & (1u << BTN_IDX_STRUM_DOWN))) {
        report->strum = GHL_STRUM_UP;
    } else if ((pressed & (1u << BTN_IDX_STRUM_DOWN)) && !(pressed & (1u << BTN_IDX_STRUM_UP))) {
        report->strum = GHL_STRUM_DOWN;
    }

    bool whammy_active = false;
    if (g_config.whammy_mode == INPUT_MODE_ANALOG &&
        g_config.pin_whammy_analog >= 26 && g_config.pin_whammy_analog <= 28) {
        uint16_t raw = read_adc_pin(g_config.pin_whammy_analog);
        uint16_t scaled = apply_sensitivity(raw, g_config.whammy_min, g_config.whammy_max);
        uint16_t smooth = ema_update(&g_ema_whammy, scaled, config_ema_alpha());
        if (g_config.whammy_invert) smooth = 4095 - smooth;
        report->whammy = adc_to_u8(smooth);
        whammy_active = (smooth > ADC_RESOLUTION / 4);
    } else if (g_config.whammy_mode == INPUT_MODE_DIGITAL &&
               g_config.pin_whammy_digital >= 0) {
        bool raw = read_pin(g_config.pin_whammy_digital);
        bool p = debounce(&g_debounce_whammy, raw, now_us, debounce_us);
        report->whammy = p ? 0xFF : 0x80;
        whammy_active = p;
    }
    if (whammy_active) pressed |= (1u << LED_INPUT_WHAMMY);

    bool tilt_active = false;
    if (g_config.tilt_mode == INPUT_MODE_ANALOG) {
        uint16_t raw = read_adc_pin(g_config.pin_tilt_analog);
        uint16_t scaled = apply_sensitivity(raw, g_config.tilt_min, g_config.tilt_max);
        uint16_t smooth = ema_update(&g_ema_tilt, scaled, config_ema_alpha());
        if (g_config.tilt_invert) smooth = 4095 - smooth;
        report->tilt = adc_to_u8(smooth);
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
            report->tilt = adc_to_u8(smooth);
            int diff = (int)smooth - (int)g_i2c_tilt_baseline;
            if (diff < 0) diff = -diff;
            tilt_active = (diff > ADC_RESOLUTION / 4);
        }
    } else {
        bool raw = read_pin(g_config.pin_tilt_digital);
        bool p = debounce(&g_debounce_tilt, raw, now_us, debounce_us);
        report->tilt = p ? 0xFF : 0x80;
        tilt_active = p;
    }
    if (tilt_active) pressed |= (1u << LED_INPUT_TILT);

    {
        bool joy_x_valid = (g_config.pin_joy_x >= 26 && g_config.pin_joy_x <= 28);
        bool joy_y_valid = (g_config.pin_joy_y >= 26 && g_config.pin_joy_y <= 28);
        int16_t joy_x_raw = joy_x_valid ? (int16_t)read_adc_pin(g_config.pin_joy_x) - ADC_CENTER : 0;
        int16_t joy_y_raw = joy_y_valid ? (int16_t)read_adc_pin(g_config.pin_joy_y) - ADC_CENTER : 0;
        int16_t dz = (int16_t)g_config.joy_deadzone;

        if (g_config.joy_whammy_axis != 0) {
            bool axis_valid = (g_config.joy_whammy_axis == 1) ? joy_x_valid : joy_y_valid;
            if (axis_valid) {
                int16_t raw = (g_config.joy_whammy_axis == 1) ? joy_x_raw : joy_y_raw;
                int16_t abs_raw = (raw < 0) ? -raw : raw;
                if (abs_raw > dz) {
                    uint16_t joy_val = (uint16_t)(((uint32_t)(abs_raw - dz) * 4095u) / (uint32_t)(2047 - dz ? 2047 - dz : 1));
                    if (joy_val > 4095) joy_val = 4095;
                    uint8_t joy_whammy = adc_to_u8(joy_val);
                    if (joy_whammy > report->whammy)
                        report->whammy = joy_whammy;
                }
            }
        }

        if (g_config.joy_dpad_x && joy_x_valid) {
            if (joy_x_raw > dz) {
                if (g_config.joy_dpad_x_invert) dpad_left = true;
                else dpad_right = true;
            } else if (joy_x_raw < -dz) {
                if (g_config.joy_dpad_x_invert) dpad_right = true;
                else dpad_left = true;
            }
        }

        if (g_config.joy_dpad_y && joy_y_valid) {
            if (joy_y_raw > dz) {
                if (g_config.joy_dpad_y_invert) dpad_up = true;
                else dpad_down = true;
            } else if (joy_y_raw < -dz) {
                if (g_config.joy_dpad_y_invert) dpad_down = true;
                else dpad_up = true;
            }
        }

        if (g_config.pin_joy_sw >= 0 && read_pin(g_config.pin_joy_sw)) {
            report->buttons |= GHL_BTN_GUIDE;
            pressed |= (1u << BTN_IDX_GUIDE);
        }
    }

    if (dpad_up) pressed |= (1u << BTN_IDX_DPAD_UP);
    if (dpad_down) pressed |= (1u << BTN_IDX_DPAD_DOWN);
    if (dpad_left) pressed |= (1u << BTN_IDX_DPAD_LEFT);
    if (dpad_right) pressed |= (1u << BTN_IDX_DPAD_RIGHT);

    report->hat = hat_from_buttons(dpad_up, dpad_down, dpad_left, dpad_right);
    g_pressed_mask = pressed;
}

// XInput button bits for 360 Guitar Hero guitar mapping
#define XI_BTN_DPAD_UP    0x0001
#define XI_BTN_DPAD_DOWN  0x0002
#define XI_BTN_START      0x0010
#define XI_BTN_BACK       0x0020
#define XI_BTN_GUIDE      0x0400  // Xbox guide button
#define XI_BTN_LB         0x0100  // Orange fret
#define XI_BTN_RB         0x0200  // White3 (extra, no GH equiv)
#define XI_BTN_A          0x1000  // Green  (White1)
#define XI_BTN_B          0x2000  // Red    (Black1)
#define XI_BTN_X          0x4000  // Blue   (Black3)
#define XI_BTN_Y          0x8000  // Yellow (Black2)

static void build_xinput_report(xinput_report_t *xrpt, const ghl_hid_report_t *ghl) {
    memset(xrpt, 0, sizeof(*xrpt));
    xrpt->report_id  = 0x00;
    xrpt->report_len = 0x14;

    uint16_t btns = 0;

    // Fret buttons → GH guitar colours
    if (ghl->fret_bits & GHL_FRET_WHITE_1) btns |= XI_BTN_A;
    if (ghl->fret_bits & GHL_FRET_BLACK_1) btns |= XI_BTN_B;
    if (ghl->fret_bits & GHL_FRET_BLACK_2) btns |= XI_BTN_Y;
    if (ghl->fret_bits & GHL_FRET_BLACK_3) btns |= XI_BTN_X;
    if (ghl->fret_bits & GHL_FRET_WHITE_2) btns |= XI_BTN_LB;
    if (ghl->fret_bits & GHL_FRET_WHITE_3) btns |= XI_BTN_RB;

    // Strum
    if (ghl->strum == GHL_STRUM_UP)   btns |= XI_BTN_DPAD_UP;
    if (ghl->strum == GHL_STRUM_DOWN) btns |= XI_BTN_DPAD_DOWN;

    // System buttons
    if (ghl->buttons & GHL_BTN_START)      btns |= XI_BTN_START;
    if (ghl->buttons & GHL_BTN_HERO_POWER) btns |= XI_BTN_BACK;
    if (ghl->buttons & GHL_BTN_GUIDE)      btns |= XI_BTN_GUIDE;

    xrpt->buttons = btns;

    // Whammy: GHL 0x80=rest, 0xFF=max → XInput ry 0..+32767
    uint8_t w = ghl->whammy;
    xrpt->ry = (w > 0x80) ? (int16_t)(((uint32_t)(w - 0x80) * 32767u) / 127u) : 0;
}

static void build_kb_report(const ghl_hid_report_t *ghl) {
    uint8_t keys[6] = {0};
    uint8_t n = 0;
    if ((ghl->fret_bits & GHL_FRET_WHITE_1) && n < 6) keys[n++] = HID_KEY_A;
    if ((ghl->fret_bits & GHL_FRET_BLACK_1) && n < 6) keys[n++] = HID_KEY_S;
    if ((ghl->fret_bits & GHL_FRET_BLACK_2) && n < 6) keys[n++] = HID_KEY_D;
    if ((ghl->fret_bits & GHL_FRET_BLACK_3) && n < 6) keys[n++] = HID_KEY_J;
    if ((ghl->fret_bits & GHL_FRET_WHITE_2) && n < 6) keys[n++] = HID_KEY_K;
    if ((ghl->fret_bits & GHL_FRET_WHITE_3) && n < 6) keys[n++] = HID_KEY_L;
    if (ghl->strum != GHL_STRUM_NEUTRAL && n < 6)     keys[n++] = HID_KEY_SPACE;
    if ((ghl->buttons & GHL_BTN_START) && n < 6)      keys[n++] = HID_KEY_RETURN;
    if ((ghl->buttons & GHL_BTN_HERO_POWER) && n < 6) keys[n++] = HID_KEY_ESCAPE;
    if ((ghl->buttons & GHL_BTN_GHTV) && n < 6)       keys[n++] = HID_KEY_TAB;
    if (ghl->tilt > 0xC0 && n < 6)                    keys[n++] = HID_KEY_SHIFT_LEFT;
    tud_hid_keyboard_report(0, 0, keys);
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t reqlen) {
    (void)instance;
    (void)report_id;
    (void)report_type;
    memset(buffer, 0, reqlen);
    return reqlen;
}

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

int main(void) {
    stdio_init_all();
    onboard_led_init();
    config_load(&g_config);

    bool enter_config = check_scratch_config_mode();
    bool enter_xinput = false;
    bool enter_kb = false;
    if (!enter_config) {
        enter_xinput = check_scratch_xinput_mode();
        if (!enter_xinput)
            enter_kb = boot_override_button_held(g_config.pin_buttons[BTN_IDX_WHITE_3]);
    }

    if (g_config.device_name[0] != '\0')
        g_device_name = g_config.device_name;

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
    }

    g_config_mode  = false;
    g_hid_mode     = false;
    g_kb_mode      = enter_kb;
    g_xinput_mode  = enter_xinput;
    gpio_put(ONBOARD_LED_PIN, true);

    static led_config_t aligned_leds;
    memcpy(&aligned_leds, &g_config.leds, sizeof(led_config_t));
    if (aligned_leds.enabled) {
        apa102_init(&aligned_leds);
        if (g_kb_mode)
            apa102_flash_all_color(&aligned_leds, 255, 80, 0);
        else
            apa102_flash_all_color(&aligned_leds, 80, 160, 255);
    }

    init_i2c_tilt();
    init_all_gpio();
    init_adc();
    memset(g_debounce, 0, sizeof(g_debounce));
    memset(&g_debounce_tilt, 0, sizeof(g_debounce_tilt));
    memset(&g_debounce_whammy, 0, sizeof(g_debounce_whammy));
    memset(&g_ema_whammy, 0, sizeof(g_ema_whammy));
    memset(&g_ema_tilt, 0, sizeof(g_ema_tilt));

    if (aligned_leds.enabled)
        apa102_update_from_inputs(&aligned_leds, 0);

    tusb_init();

    ghl_hid_report_t report;
    xinput_report_t xi_report;
    uint64_t last_report_us = 0;
    uint64_t last_led_us = 0;
    uint32_t last_keepalive_ms = 0;

    while (true) {
        tud_task();

        if (!g_xinput_mode && ghl_magic_keepalive_seen())
            last_keepalive_ms = to_ms_since_boot(get_absolute_time());

        // In XInput mode: magic vibration triggers config mode reboot
        if (g_xinput_mode && xinput_magic_detected())
            request_config_mode_reboot();

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        bool multibutton_enabled = (now_ms - last_keepalive_ms) <= KEEPALIVE_TIMEOUT_MS;

        uint64_t now_us = time_us_64();
        if (now_us - last_report_us >= REPORT_INTERVAL_US) {
            last_report_us = now_us;
            build_report(&report, multibutton_enabled);

            if (g_xinput_mode) {
                build_xinput_report(&xi_report, &report);
                xinput_send_report(&xi_report);
            } else if (tud_hid_ready()) {
                if (g_kb_mode) build_kb_report(&report);
                else tud_hid_report(0, &report, sizeof(report));
            }
        }

        if (aligned_leds.enabled && (now_us - last_led_us >= LED_UPDATE_INTERVAL_US)) {
            last_led_us = now_us;
            apa102_update_from_inputs(&aligned_leds, g_pressed_mask);
        }
    }

    return 0;
}
