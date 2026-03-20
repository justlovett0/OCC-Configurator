/*
 * main.c - Pico Retro Gamepad Controller Firmware
 *
 * Boot flow:
 *   1. Check watchdog scratch[0] for config mode magic → enter CDC serial config mode
 *   2. Load config from flash
 *   3. Set custom device name for USB descriptors
 *   4. (Pico W) Initialize CYW43
 *   5. Initialize TinyUSB with descriptor set selected by g_config_mode
 *   6. If config mode: enter config_serial_loop (never returns)
 *   7. Wait up to USB_MOUNT_TIMEOUT_MS for a USB host to enumerate
 *   8. If no USB host: enter standby loop (scaffold for Phase 3+ BLE)
 *   9. If USB host: initialize GPIOs, enter XInput report loop
 *
 * Input reading:
 *   - 13 digital buttons (active-low, internal pull-ups, debounced)
 *   - LT/RT triggers: analog (ADC 0-4095 scaled to 0-255 with EMA) or digital (0/255)
 *
 * Config mode entry:
 *   - Watchdog scratch[0] = WATCHDOG_CONFIG_MAGIC at boot
 *   - Magic vibration sequence from configurator → reboot into config mode
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "hardware/gpio.h"
#include "hardware/adc.h"
#include "hardware/watchdog.h"
#include "hardware/structs/watchdog.h"
#include "tusb.h"
#include "usb_descriptors.h"
#include "retro_config.h"
#include "retro_config_serial.h"
#include "xinput_driver.h"

#ifdef PICO_W_BT
#include "pico/cyw43_arch.h"
#endif

//--------------------------------------------------------------------
// Constants
//--------------------------------------------------------------------

#define USB_MOUNT_TIMEOUT_MS  1000

//--------------------------------------------------------------------
// Global state
//--------------------------------------------------------------------

static retro_config_t g_config;
static volatile bool  g_usb_mounted = false;

//--------------------------------------------------------------------
// TinyUSB mount callbacks
//--------------------------------------------------------------------

void tud_mount_cb(void)  { g_usb_mounted = true; }
void tud_umount_cb(void) { g_usb_mounted = false; }
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; }
void tud_resume_cb(void) {}

//--------------------------------------------------------------------
// Debounce state and function
//--------------------------------------------------------------------

typedef struct {
    uint32_t last_change_us;
    bool     stable;
    bool     raw;
} debounce_state_t;

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
// EMA smoothing state and function
//--------------------------------------------------------------------

typedef struct {
    uint32_t state;
    bool     seeded;
} ema_state_t;

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
// ADC calibration scaling
//--------------------------------------------------------------------

static uint16_t apply_sensitivity(uint16_t raw, uint16_t min_val, uint16_t max_val) {
    if (max_val <= min_val) return raw;
    if (raw <= min_val) return 0;
    if (raw >= max_val) return 4095;
    return (uint16_t)(((uint32_t)(raw - min_val) * 4095u) / (max_val - min_val));
}

//--------------------------------------------------------------------
// Pico W GPIO reserved pin guard
//--------------------------------------------------------------------

#ifdef PICO_W_BT
static bool g_cyw43_initialized = false;

static bool is_picow_reserved(uint pin) {
    return (pin == 23 || pin == 24 || pin == 25 || pin == 29);
}
#endif

//--------------------------------------------------------------------
// XInput button mask lookup table
//--------------------------------------------------------------------

static const uint16_t button_masks[BTN_IDX_COUNT] = {
    [BTN_IDX_DPAD_UP]    = XINPUT_BTN_DPAD_UP,
    [BTN_IDX_DPAD_DOWN]  = XINPUT_BTN_DPAD_DOWN,
    [BTN_IDX_DPAD_LEFT]  = XINPUT_BTN_DPAD_LEFT,
    [BTN_IDX_DPAD_RIGHT] = XINPUT_BTN_DPAD_RIGHT,
    [BTN_IDX_A]          = XINPUT_BTN_A,
    [BTN_IDX_B]          = XINPUT_BTN_B,
    [BTN_IDX_X]          = XINPUT_BTN_X,
    [BTN_IDX_Y]          = XINPUT_BTN_Y,
    [BTN_IDX_START]      = XINPUT_BTN_START,
    [BTN_IDX_SELECT]     = XINPUT_BTN_BACK,
    [BTN_IDX_GUIDE]      = XINPUT_BTN_GUIDE,
    [BTN_IDX_LB]         = XINPUT_BTN_LEFT_SHOULDER,
    [BTN_IDX_RB]         = XINPUT_BTN_RIGHT_SHOULDER,
};

//--------------------------------------------------------------------
// GPIO initialization
//--------------------------------------------------------------------

static void init_button_gpios(const retro_config_t *config) {
    for (int i = 0; i < RETRO_BTN_COUNT; i++) {
        int8_t pin = config->pin_buttons[i];
        if (pin < 0) continue;
#ifdef PICO_W_BT
        if (g_cyw43_initialized && is_picow_reserved((uint)pin)) continue;
#endif
        gpio_init((uint)pin);
        gpio_set_dir((uint)pin, GPIO_IN);
        gpio_pull_up((uint)pin);
    }
}

static void init_trigger_gpio(int8_t pin, uint8_t mode) {
    if (pin < 0) return;
#ifdef PICO_W_BT
    if (g_cyw43_initialized && is_picow_reserved((uint)pin)) return;
#endif
    if (mode == INPUT_MODE_ANALOG) {
        if (pin >= 26 && pin <= 28) {
            adc_gpio_init((uint)pin);
        }
    } else {
        gpio_init((uint)pin);
        gpio_set_dir((uint)pin, GPIO_IN);
        gpio_pull_up((uint)pin);
    }
}

//--------------------------------------------------------------------
// Trigger read functions
//--------------------------------------------------------------------

static uint8_t read_trigger_analog(int8_t pin, uint16_t tmin, uint16_t tmax,
                                   uint8_t invert, uint8_t ema_alpha_pct,
                                   ema_state_t *ema) {
    if (pin < 26 || pin > 28) return 0;
    adc_select_input((uint)(pin - 26));
    uint16_t raw    = adc_read();
    uint16_t scaled = apply_sensitivity(raw, tmin, tmax);
    // EMA alpha 0 stored → 255 internal (fastest response, matching guitar convention)
    uint32_t alpha  = (ema_alpha_pct == 0) ? 255u : (uint32_t)ema_alpha_pct;
    uint16_t smooth = ema_update(ema, scaled, alpha);
    if (invert) smooth = 4095 - smooth;
    return (uint8_t)(smooth * 255u / 4095u);
}

static uint8_t read_trigger_digital(int8_t pin, debounce_state_t *dbs,
                                    uint32_t now_us, uint32_t debounce_us) {
    if (pin < 0 || pin > 28) return 0;
    bool raw     = !gpio_get((uint)pin);  // active-low
    bool pressed = debounce(dbs, raw, now_us, debounce_us);
    return pressed ? 255u : 0u;
}

//--------------------------------------------------------------------
// Config mode reboot
//--------------------------------------------------------------------

static void request_config_mode_reboot(void) {
    watchdog_hw->scratch[0] = WATCHDOG_CONFIG_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

//--------------------------------------------------------------------
// Main
//--------------------------------------------------------------------

int main(void) {
    stdio_init_all();
    adc_init();

    // 1. Check watchdog scratch for config mode request (BEFORE tusb_init)
    if (watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC) {
        watchdog_hw->scratch[0] = 0;  // clear flag
        g_config_mode = true;
    }

    // 2. Load config from flash
    config_load(&g_config);

    // 3. Set device name for USB descriptor
    if (g_config.device_name[0] != '\0') {
        g_device_name = g_config.device_name;
    }

    // 4. Pico W CYW43 init (if applicable)
#ifdef PICO_W_BT
    if (cyw43_arch_init() == 0) {
        g_cyw43_initialized = true;
    }
#endif

    // 5. Initialize TinyUSB (descriptor set selected by g_config_mode)
    tusb_init();

    // 6. If config mode, enter serial config loop (never returns until REBOOT)
    if (g_config_mode) {
        config_serial_loop(&g_config);
        // If we somehow exit the loop, reboot
        watchdog_reboot(0, 0, 10);
        while (1) { tight_loop_contents(); }
    }

    // 7. USB mount detection — wait up to USB_MOUNT_TIMEOUT_MS
    {
        uint32_t start_ms = to_ms_since_boot(get_absolute_time());
        while (!g_usb_mounted) {
            tud_task();
#ifdef PICO_W_BT
            if (g_cyw43_initialized) cyw43_arch_poll();
#endif
            uint32_t elapsed = to_ms_since_boot(get_absolute_time()) - start_ms;
            if (elapsed >= USB_MOUNT_TIMEOUT_MS) break;
            sleep_ms(1);
        }
    }

    // 8. If no USB host detected, enter standby (scaffold for Phase 3+ BLE)
    if (!g_usb_mounted) {
        while (true) {
#ifdef PICO_W_BT
            if (g_cyw43_initialized) cyw43_arch_poll();
#endif
            tight_loop_contents();
        }
    }

    // 9. USB connected — initialize GPIOs for buttons and triggers
    init_button_gpios(&g_config);
    init_trigger_gpio(g_config.pin_lt, g_config.mode_lt);
    init_trigger_gpio(g_config.pin_rt, g_config.mode_rt);

    // 10. State arrays
    static debounce_state_t btn_debounce[RETRO_BTN_COUNT] = {0};
    static debounce_state_t lt_debounce = {0};
    static debounce_state_t rt_debounce = {0};
    static ema_state_t ema_lt = {0};
    static ema_state_t ema_rt = {0};

    // 11. Main game loop — read inputs, build XInput report, send
    while (true) {
        tud_task();

        // Check for magic vibration sequence from configurator
        if (xinput_magic_detected()) {
            request_config_mode_reboot();
        }

        uint32_t now_us     = (uint32_t)to_us_since_boot(get_absolute_time());
        uint32_t debounce_us = (uint32_t)g_config.debounce_ms * 1000u;

        // Read all 13 digital buttons (active-low, internal pull-up)
        uint16_t buttons = 0;
        for (int i = 0; i < RETRO_BTN_COUNT; i++) {
            int8_t pin = g_config.pin_buttons[i];
            if (pin < 0) continue;
#ifdef PICO_W_BT
            if (g_cyw43_initialized && is_picow_reserved((uint)pin)) continue;
#endif
            bool raw     = !gpio_get((uint)pin);  // active-low, internal pull-up
            bool pressed = debounce(&btn_debounce[i], raw, now_us, debounce_us);
            if (pressed) {
                buttons |= button_masks[i];
            }
        }

        // Read LT trigger
        uint8_t lt_val = 0;
        if (g_config.pin_lt >= 0) {
            if (g_config.mode_lt == INPUT_MODE_ANALOG) {
                lt_val = read_trigger_analog(g_config.pin_lt,
                    g_config.lt_min, g_config.lt_max,
                    g_config.lt_invert, g_config.lt_ema_alpha, &ema_lt);
            } else {
                lt_val = read_trigger_digital(g_config.pin_lt,
                    &lt_debounce, now_us, debounce_us);
            }
        }

        // Read RT trigger
        uint8_t rt_val = 0;
        if (g_config.pin_rt >= 0) {
            if (g_config.mode_rt == INPUT_MODE_ANALOG) {
                rt_val = read_trigger_analog(g_config.pin_rt,
                    g_config.rt_min, g_config.rt_max,
                    g_config.rt_invert, g_config.rt_ema_alpha, &ema_rt);
            } else {
                rt_val = read_trigger_digital(g_config.pin_rt,
                    &rt_debounce, now_us, debounce_us);
            }
        }

        // Build XInput report
        xinput_report_t report = {0};
        report.report_id     = 0x00;
        report.report_size   = 0x14;  // 20 bytes
        report.buttons       = buttons;
        report.left_trigger  = lt_val;
        report.right_trigger = rt_val;
        // left_stick_x/y, right_stick_x/y = 0 (unused in v1, no joysticks)

        // Send report (~1kHz poll rate)
        if (xinput_ready()) {
            xinput_send_report(&report);
        }

        sleep_ms(1);
    }

    return 0;  // unreachable
}
