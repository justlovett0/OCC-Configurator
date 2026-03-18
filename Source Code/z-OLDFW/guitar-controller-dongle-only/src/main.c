/*
 * main.c - Pico W Guitar Controller Firmware (Dongle Mode)
 *
 * This is a modified version of the BT firmware that sends gamepad
 * reports to a wireless USB dongle instead of directly to the OS.
 *
 * Boot flow (same as original BT firmware):
 *   1. Check watchdog scratch register → USB CDC config mode
 *   2. Initialize USB and wait up to USB_MOUNT_TIMEOUT_MS:
 *      - If a USB host enumerates the device → USB XInput play mode
 *        (identical to the original wired firmware — configurator works)
 *      - If timeout expires with no host → Wireless dongle mode
 *        (sends reports to dongle via BLE custom GATT service)
 *
 * This means:
 *   - Plug in USB → wired controller (configurator works normally)
 *   - Power from battery → wireless mode, sends to dongle
 *   - Magic vibration sequence (USB) → config mode reboot
 *   - SELECT held at boot → config mode (fallback)
 *
 * ╔═══════════════════════════════════════════════════════════════════╗
 * ║  SYNC BUTTON CONFIGURATION                                      ║
 * ║                                                                  ║
 * ║  Change this pin to whichever GPIO you wire a momentary          ║
 * ║  push-button to on your controller Pico W for sync.              ║
 * ║  The button should connect the GPIO to GND when pressed.         ║
 * ║  Internal pull-up is enabled.                                    ║
 * ║                                                                  ║
 * ║  NOTE: This is SEPARATE from the guitar's Start/Select buttons.  ║
 * ║  You can reuse one of those GPIOs if you want, or add a          ║
 * ║  dedicated sync button.                                          ║
 * ╚═══════════════════════════════════════════════════════════════════╝
 */

/*
 * ╔═══════════════════════════════════════════════════════════════════╗
 * ║  SYNC BUTTON DEFAULT                                            ║
 * ║                                                                  ║
 * ║  The sync button GPIO is stored in the config struct and can     ║
 * ║  be changed via the OCC Configurator. The default is GPIO 15.   ║
 * ║  You can also change the default below — it is used on first    ║
 * ║  boot or after a factory reset.                                  ║
 * ╚═══════════════════════════════════════════════════════════════════╝
 */

// Default sync pin is set in guitar_config.c config_set_defaults() (GPIO 15)

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
#include "controller_bt.h"

#define REPORT_INTERVAL_US     1000       // ~1000 Hz for USB XInput
#define BT_REPORT_INTERVAL_US  4000       // ~250 Hz for BLE to dongle
#define LED_UPDATE_INTERVAL_US 16667      // ~60 Hz LED refresh
#define ADC_RESOLUTION         4095
#define DIGITAL_AXIS_ON        32767
#define SYNC_DEBOUNCE_MS       300

// Time to wait for a USB host to enumerate before falling back to wireless.
#define USB_MOUNT_TIMEOUT_MS   3000

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

//--------------------------------------------------------------------
// USB mount state tracking
//--------------------------------------------------------------------

static volatile bool g_usb_mounted = false;

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

static inline bool is_picow_reserved(int8_t pin) {
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
#define EMA_ALPHA_DEFAULT   90u

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
// Shared input reading
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
// USB XInput report builder (for wired mode)
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

//--------------------------------------------------------------------
// Wireless report builder (for dongle mode)
//--------------------------------------------------------------------

static void build_wireless_report(controller_report_t *report) {
    input_state_t inp;
    read_all_inputs(&inp);

    memset(report, 0, sizeof(controller_report_t));
    report->buttons       = inp.buttons;
    report->right_stick_x = inp.right_stick_x;
    report->right_stick_y = inp.right_stick_y;
}

//--------------------------------------------------------------------
// Sync button
//--------------------------------------------------------------------

static void init_sync_button(void) {
    int8_t pin = g_config.sync_pin;
    if (pin < 0 || pin > 28) return;
    if (is_picow_reserved(pin)) return;
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
}

static bool read_sync_button(void) {
    int8_t pin = g_config.sync_pin;
    if (pin < 0 || pin > 28) return false;
    if (is_picow_reserved(pin)) return false;
    return !gpio_get(pin);
}

//--------------------------------------------------------------------
// TinyUSB callbacks
//--------------------------------------------------------------------

void tud_mount_cb(void)   { g_usb_mounted = true; }
void tud_umount_cb(void)  { g_usb_mounted = false; }
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; }
void tud_resume_cb(void)  {}

//--------------------------------------------------------------------
// Check if SELECT button is held at boot
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
// Shared play-mode hardware init
//--------------------------------------------------------------------

static led_config_t g_aligned_leds;

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

    // Initialize CYW43 early
    if (cyw43_arch_init()) {
        // CYW43 init failed — can still do USB modes
    } else {
        g_cyw43_initialized = true;
    }

    picow_led_set(true);

    config_load(&g_config);

    if (g_config.device_name[0] != '\0') {
        g_device_name = g_config.device_name;
    }

    // ── Step 1: Check for config mode ──
    bool enter_config = check_scratch_config_mode();

    if (enter_config) {
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

    // ── Step 2: Try USB XInput first ──
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
                break;
            }

            if (elapsed >= (USB_MOUNT_TIMEOUT_MS - 500)) {
                if (check_select_held_at_boot()) {
                    request_config_mode_reboot();
                }
            }

            sleep_ms(1);
        }
    }

    // ── Step 3: Initialize play mode ──
    init_play_mode_hardware();

    if (g_usb_mounted) {
        // ═══════════════════════════════════════════════════════════════
        // USB XINPUT PLAY MODE — Wired controller
        // Identical to original firmware. Configurator works normally.
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
        // ═══════════════════════════════════════════════════════════════
        // WIRELESS DONGLE MODE — Broadcasts reports via BLE advertisements
        //
        // The controller embeds its 12-byte gamepad report directly in the
        // BLE advertisement payload. The dongle passively scans and reads
        // the data — no BLE connection is established.
        // ═══════════════════════════════════════════════════════════════
        const char *bt_name = (g_config.device_name[0] != '\0')
                              ? g_config.device_name
                              : "Guitar Controller";

        // Initialize sync button
        init_sync_button();

        if (g_cyw43_initialized) {
            controller_bt_init(bt_name);

            // Auto-start advertising on boot
            controller_bt_start_sync();
        }

        controller_report_t report;
        uint64_t last_report_us = 0;
        uint64_t last_led_us = 0;
        uint32_t last_sync_press_ms = 0;
        bool     sync_was_pressed = false;

        // Track when wireless mode started for LED flash duration
        uint32_t wireless_start_ms = to_ms_since_boot(get_absolute_time());
        // Flash APA102 LEDs for 5 seconds at boot to show "wireless mode active"
        #define WIRELESS_FLASH_DURATION_MS  5000

        while (true) {
            if (g_cyw43_initialized) {
                cyw43_arch_poll();
            }

            // ── Sync button handling ──
            bool sync_pressed = read_sync_button();
            if (sync_pressed && !sync_was_pressed) {
                uint32_t now_ms = to_ms_since_boot(get_absolute_time());
                if (now_ms - last_sync_press_ms >= SYNC_DEBOUNCE_MS) {
                    last_sync_press_ms = now_ms;
                    if (g_cyw43_initialized) {
                        controller_bt_start_sync();
                    }
                    // Reset the LED flash timer so user gets visual feedback
                    wireless_start_ms = now_ms;
                }
            }
            sync_was_pressed = sync_pressed;

            // ── Onboard Pico W LED ──
            // Solid ON once advertising is active (always broadcasting)
            if (controller_bt_connected()) {
                picow_led_set(true);
            } else {
                picow_led_blink_bt_waiting();
            }

            uint64_t now_us = time_us_64();

            // ── Broadcast wireless reports at ~250 Hz ──
            if (now_us - last_report_us >= BT_REPORT_INTERVAL_US) {
                last_report_us = now_us;
                build_wireless_report(&report);
                controller_bt_send_report(&report);
            }

            // ── APA102 LED strip updates ──
            if (g_aligned_leds.enabled &&
                (now_us - last_led_us >= LED_UPDATE_INTERVAL_US)) {
                last_led_us = now_us;

                uint32_t now_ms = to_ms_since_boot(get_absolute_time());
                bool in_flash_period = (now_ms - wireless_start_ms) < WIRELESS_FLASH_DURATION_MS;

                if (in_flash_period) {
                    // Flash ALL LEDs on/off at 500ms intervals
                    // Clear visual indicator: "wireless mode, broadcasting"
                    bool leds_on = ((now_ms / 500) % 2) == 0;

                    uint8_t brightness[MAX_LEDS];
                    if (leds_on) {
                        for (int i = 0; i < MAX_LEDS; i++)
                            brightness[i] = g_aligned_leds.base_brightness > 0
                                            ? g_aligned_leds.base_brightness : 5;
                    } else {
                        memset(brightness, 0, sizeof(brightness));
                    }
                    apa102_update(&g_aligned_leds, brightness);
                } else {
                    // After flash period: normal input-driven LED behavior
                    apa102_update_from_inputs(&g_aligned_leds, g_pressed_mask);
                }
            }

            sleep_us(100);
        }
    }
    return 0;
}
