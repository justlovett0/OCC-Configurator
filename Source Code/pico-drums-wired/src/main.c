/*
 * main.c - Pico Drum Controller Firmware
 *
 * Boot flow:
 *   - scratch[0] requests config mode
 *   - scratch[1] requests a play mode (normal / PS3 / Fortnite)
 *   - holding Start at boot forces PS3 mode
 *   - holding Start+Select at boot forces Fortnite mode
 *
 * Play modes:
 *   - Normal:    Xbox 360 XInput drum kit
 *   - PS3:       HID drum kit
 *   - Fortnite:  Rock Band drum persona over XInput
 */

#include <limits.h>
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
#define LED_UPDATE_INTERVAL_US  16667
#define ONBOARD_LED_PIN         25

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

static const bool is_cymbal[BTN_IDX_COUNT] = {
    [BTN_IDX_YELLOW_CYM] = true,
    [BTN_IDX_BLUE_CYM]   = true,
    [BTN_IDX_GREEN_CYM]  = true,
};

typedef struct {
    uint32_t last_change_us;
    bool     stable;
    bool     raw;
} debounce_state_t;

typedef struct {
    uint16_t buttons;
    uint16_t pressed_mask;
    bool     any_cymbal;
} input_state_t;

typedef struct __attribute__((packed)) {
    uint8_t status;
    uint8_t buttons1;
    uint8_t buttons2;
    uint8_t lx;
    uint8_t ly;
    uint8_t rx;
    uint8_t ry;
    uint8_t reserved[20];
} ps3_report_t;

static drum_config_t g_config;
static uint16_t g_pressed_mask;
static debounce_state_t g_debounce[BTN_IDX_COUNT];
static bool g_hid_detecting = false;
static uint32_t g_hid_detect_start_ms = 0;
static uint8_t g_fortnite_prev_cymbals = 0;
static uint8_t g_fortnite_dpad_mask = 0;

static bool debounce(debounce_state_t *state, bool current_raw,
                     uint32_t now_us, uint32_t debounce_us) {
    if (current_raw != state->raw) {
        state->raw = current_raw;
        state->last_change_us = now_us;
    } else if (current_raw != state->stable) {
        if ((now_us - state->last_change_us) >= debounce_us) {
            state->stable = current_raw;
        }
    }
    return state->stable;
}

static bool check_scratch_config_mode(void) {
    if (watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC) {
        watchdog_hw->scratch[0] = 0;
        return true;
    }
    return false;
}

static drum_play_mode_t check_scratch_play_mode(void) {
    uint32_t scratch = watchdog_hw->scratch[1];
    watchdog_hw->scratch[1] = WATCHDOG_PLAY_MODE_NONE;
    if (scratch == WATCHDOG_PLAY_MODE_PS3) return DRUM_PLAY_MODE_PS3;
    if (scratch == WATCHDOG_PLAY_MODE_FORTNITE) return DRUM_PLAY_MODE_FORTNITE;
    return DRUM_PLAY_MODE_XINPUT;
}

static void leds_off_for_reboot(void) {
    led_config_t tmp;
    memcpy(&tmp, &g_config.leds, sizeof(tmp));
    apa102_all_off(&tmp);
}

static void request_config_mode_reboot(void) {
    leds_off_for_reboot();
    watchdog_hw->scratch[0] = WATCHDOG_CONFIG_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

static void request_play_mode_reboot(drum_play_mode_t mode) {
    leds_off_for_reboot();
    watchdog_hw->scratch[1] = WATCHDOG_PLAY_MODE_NONE;
    if (mode == DRUM_PLAY_MODE_PS3) {
        watchdog_hw->scratch[1] = WATCHDOG_PLAY_MODE_PS3;
    } else if (mode == DRUM_PLAY_MODE_FORTNITE) {
        watchdog_hw->scratch[1] = WATCHDOG_PLAY_MODE_FORTNITE;
    }
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

static void request_ps3_mode_reboot(void) {
    request_play_mode_reboot(DRUM_PLAY_MODE_PS3);
}

static inline bool is_led_spi_pin(int8_t pin) {
    if (!g_config.leds.enabled) return false;
    int8_t data_pin = apa102_spi_data_pin_is_valid(g_config.leds.data_pin)
        ? g_config.leds.data_pin : LED_SPI_DEFAULT_DATA_PIN;
    int8_t clock_pin = apa102_spi_clock_pin_is_valid(g_config.leds.clock_pin)
        ? g_config.leds.clock_pin : LED_SPI_DEFAULT_CLOCK_PIN;
    return pin == data_pin || pin == clock_pin;
}

static bool pin_is_usable_button(int8_t pin) {
    return pin >= 0 && pin <= 28 && !is_led_spi_pin(pin);
}

static bool boot_override_button_held(int8_t pin) {
    if (!pin_is_usable_button(pin)) return false;
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
    sleep_us(50);
    return !gpio_get(pin);
}

static void convert_to_ps3_drum(ps3_report_t *ps3, const xinput_report_t *xi) {
    memset(ps3, 0, sizeof(*ps3));
    uint16_t b = xi->buttons;

    if (b & XINPUT_BTN_BACK)         ps3->buttons1 |= 0x01;
    if (b & XINPUT_BTN_START)        ps3->buttons1 |= 0x08;
    if (b & XINPUT_BTN_DPAD_UP)      ps3->buttons1 |= 0x10;
    if (b & XINPUT_BTN_DPAD_RIGHT)   ps3->buttons1 |= 0x20;
    if (b & XINPUT_BTN_DPAD_DOWN)    ps3->buttons1 |= 0x40;
    if (b & XINPUT_BTN_DPAD_LEFT)    ps3->buttons1 |= 0x80;

    if (b & XINPUT_BTN_LEFT_THUMB)     ps3->buttons2 |= 0x01;
    if (b & XINPUT_BTN_RIGHT_THUMB)    ps3->buttons2 |= 0x02;
    if (b & XINPUT_BTN_LEFT_SHOULDER)  ps3->buttons2 |= 0x04;
    if (b & XINPUT_BTN_RIGHT_SHOULDER) ps3->buttons2 |= 0x08;
    if (b & XINPUT_BTN_Y)              ps3->buttons2 |= 0x10;
    if (b & XINPUT_BTN_B)              ps3->buttons2 |= 0x20;
    if (b & XINPUT_BTN_A)              ps3->buttons2 |= 0x40;
    if (b & XINPUT_BTN_X)              ps3->buttons2 |= 0x80;

    ps3->lx = 0x80;
    ps3->ly = 0x80;
    ps3->rx = 0x80;
    ps3->ry = 0x80;
}

static void init_gpio_pin(int8_t pin) {
    if (!pin_is_usable_button(pin)) return;
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
}

static void init_all_gpio(void) {
    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        init_gpio_pin(g_config.pin_buttons[i]);
    }
}

static inline bool read_pin(int8_t pin) {
    if (!pin_is_usable_button(pin)) return false;
    return !gpio_get(pin);
}

static void read_inputs(input_state_t *state) {
    memset(state, 0, sizeof(*state));
    uint32_t now_us = time_us_32();
    uint32_t debounce_us = (uint32_t)g_config.debounce_ms * 1000u;

    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        bool raw = read_pin(g_config.pin_buttons[i]);
        bool active = debounce(&g_debounce[i], raw, now_us, debounce_us);
        if (active) {
            state->buttons |= button_masks[i];
            state->pressed_mask |= (1u << i);
            if (is_cymbal[i]) {
                state->any_cymbal = true;
            }
        }
    }

    g_pressed_mask = state->pressed_mask;
}

static void build_standard_report(xinput_report_t *report, const input_state_t *state) {
    memset(report, 0, sizeof(*report));
    report->report_id = 0x00;
    report->report_size = XINPUT_REPORT_SIZE;
    report->buttons = state->buttons;
    if (state->any_cymbal) {
        report->right_trigger = DRUM_CYMBAL_FLAG;
    }
}

static void update_fortnite_cymbal_dpad(const input_state_t *state, uint16_t *buttons) {
    const uint8_t yellow_bit = 0x01;
    const uint8_t blue_bit = 0x02;
    uint8_t cymbal_mask = 0;

    if (state->pressed_mask & (1u << BTN_IDX_YELLOW_CYM)) cymbal_mask |= yellow_bit;
    if (state->pressed_mask & (1u << BTN_IDX_BLUE_CYM)) cymbal_mask |= blue_bit;

    if (cymbal_mask != g_fortnite_prev_cymbals) {
        if (cymbal_mask == 0) {
            g_fortnite_dpad_mask = 0;
        }

        if (g_fortnite_dpad_mask != 0) {
            if ((cymbal_mask & yellow_bit) == 0) {
                g_fortnite_dpad_mask &= (uint8_t)~yellow_bit;
            } else if ((cymbal_mask & blue_bit) == 0) {
                g_fortnite_dpad_mask &= (uint8_t)~blue_bit;
            }
        }

        if (g_fortnite_dpad_mask == 0) {
            if ((cymbal_mask & yellow_bit) != 0) {
                g_fortnite_dpad_mask |= yellow_bit;
            } else if ((cymbal_mask & blue_bit) != 0) {
                g_fortnite_dpad_mask |= blue_bit;
            }
        }

        g_fortnite_prev_cymbals = cymbal_mask;
    }

    if (g_fortnite_dpad_mask & yellow_bit) *buttons |= XINPUT_BTN_DPAD_UP;
    if (g_fortnite_dpad_mask & blue_bit)   *buttons |= XINPUT_BTN_DPAD_DOWN;
}

static void build_fortnite_report(xinput_report_t *report, const input_state_t *state) {
    bool red_pad = (state->pressed_mask & (1u << BTN_IDX_RED_DRUM)) != 0;
    bool yellow_pad = (state->pressed_mask & (1u << BTN_IDX_YELLOW_DRUM)) != 0;
    bool blue_pad = (state->pressed_mask & (1u << BTN_IDX_BLUE_DRUM)) != 0;
    bool green_pad = (state->pressed_mask & (1u << BTN_IDX_GREEN_DRUM)) != 0;
    bool yellow_cym = (state->pressed_mask & (1u << BTN_IDX_YELLOW_CYM)) != 0;
    bool blue_cym = (state->pressed_mask & (1u << BTN_IDX_BLUE_CYM)) != 0;
    bool green_cym = (state->pressed_mask & (1u << BTN_IDX_GREEN_CYM)) != 0;
    bool kick = (state->pressed_mask & (1u << BTN_IDX_FOOT_PEDAL)) != 0;

    memset(report, 0, sizeof(*report));
    report->report_id = 0x00;
    report->report_size = XINPUT_REPORT_SIZE;
    report->buttons = 0;

    if (state->buttons & XINPUT_BTN_START) report->buttons |= XINPUT_BTN_START;
    if (state->buttons & XINPUT_BTN_BACK)  report->buttons |= XINPUT_BTN_BACK;
    if (state->buttons & XINPUT_BTN_DPAD_LEFT)  report->buttons |= XINPUT_BTN_DPAD_LEFT;
    if (state->buttons & XINPUT_BTN_DPAD_RIGHT) report->buttons |= XINPUT_BTN_DPAD_RIGHT;
    if (state->buttons & XINPUT_BTN_DPAD_UP)    report->buttons |= XINPUT_BTN_DPAD_UP;
    if (state->buttons & XINPUT_BTN_DPAD_DOWN)  report->buttons |= XINPUT_BTN_DPAD_DOWN;

    uint16_t buttons = report->buttons;
    update_fortnite_cymbal_dpad(state, &buttons);
    report->buttons = buttons;

    if (red_pad)                    report->buttons |= XINPUT_BTN_B;
    if (yellow_pad || yellow_cym)   report->buttons |= XINPUT_BTN_Y;
    if (blue_pad || blue_cym)       report->buttons |= XINPUT_BTN_X;
    if (green_pad || green_cym)     report->buttons |= XINPUT_BTN_A;

    if (red_pad || yellow_pad || blue_pad || green_pad) {
        report->buttons |= XINPUT_BTN_RIGHT_THUMB;
    }
    if (yellow_cym || blue_cym || green_cym) {
        report->buttons |= XINPUT_BTN_RIGHT_SHOULDER;
    }
    if (kick) {
        report->buttons |= XINPUT_BTN_LEFT_SHOULDER;
    }

    report->left_stick_x  = red_pad ? INT16_MAX : 0;
    report->left_stick_y  = (yellow_pad || yellow_cym) ? INT16_MIN : 0;
    report->right_stick_x = (blue_pad || blue_cym) ? INT16_MAX : 0;
    report->right_stick_y = (green_pad || green_cym) ? INT16_MIN : 0;
}

void tud_mount_cb(void) {
    if (g_play_mode == DRUM_PLAY_MODE_XINPUT && !g_config_mode) {
        g_hid_detecting = true;
        g_hid_detect_start_ms = to_ms_since_boot(get_absolute_time());
    }
}

void tud_umount_cb(void) {
    watchdog_hw->scratch[1] = WATCHDOG_PLAY_MODE_NONE;
    g_hid_detecting = false;
}

void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; }
void tud_resume_cb(void) {}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t reqlen) {
    (void)instance;
    (void)report_id;
    (void)report_type;
    memset(buffer, 0, reqlen);
    return reqlen;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
                           hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize) {
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)bufsize;
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

static void flash_boot_color(const led_config_t *cfg, uint8_t r, uint8_t g, uint8_t b) {
    if (!cfg->enabled || cfg->count == 0) return;

    led_config_t tmp;
    memcpy(&tmp, cfg, sizeof(tmp));
    for (uint8_t i = 0; i < tmp.count && i < MAX_LEDS; i++) {
        tmp.colors[i].r = r;
        tmp.colors[i].g = g;
        tmp.colors[i].b = b;
    }

    uint8_t brightness[MAX_LEDS] = {0};
    for (uint8_t i = 0; i < tmp.count && i < MAX_LEDS; i++) {
        brightness[i] = tmp.base_brightness ? tmp.base_brightness : 8;
    }

    apa102_update(&tmp, brightness);
    sleep_ms(80);
}

int main(void) {
    stdio_init_all();
    onboard_led_init();
    config_load(&g_config);

    bool enter_config = check_scratch_config_mode();
    drum_play_mode_t play_mode = check_scratch_play_mode();

    if (g_config.device_name[0] != '\0') {
        g_device_name = g_config.device_name;
    }

    if (!enter_config) {
        bool start_held = boot_override_button_held(g_config.pin_buttons[BTN_IDX_START]);
        bool select_held = boot_override_button_held(g_config.pin_buttons[BTN_IDX_SELECT]);
        if (start_held && select_held) {
            play_mode = DRUM_PLAY_MODE_FORTNITE;
        } else if (start_held) {
            play_mode = DRUM_PLAY_MODE_PS3;
        }
    }

    if (enter_config) {
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
    }

    g_config_mode = false;
    g_play_mode = play_mode;
    gpio_put(ONBOARD_LED_PIN, true);

    static led_config_t aligned_leds;
    memcpy(&aligned_leds, &g_config.leds, sizeof(aligned_leds));
    if (aligned_leds.enabled) {
        apa102_init(&aligned_leds);
        if (g_play_mode == DRUM_PLAY_MODE_PS3) {
            flash_boot_color(&aligned_leds, 176, 0, 255);
        } else if (g_play_mode == DRUM_PLAY_MODE_FORTNITE) {
            flash_boot_color(&aligned_leds, 255, 80, 0);
        }
    }

    init_all_gpio();
    memset(g_debounce, 0, sizeof(g_debounce));
    g_pressed_mask = 0;
    g_fortnite_prev_cymbals = 0;
    g_fortnite_dpad_mask = 0;

    if (aligned_leds.enabled) {
        apa102_update_from_inputs(&aligned_leds, 0);
    }

    tusb_init();

    input_state_t input_state;
    xinput_report_t report;
    ps3_report_t ps3_report;
    uint64_t last_report_us = 0;
    uint64_t last_led_us = 0;

    while (true) {
        tud_task();

        if (g_play_mode == DRUM_PLAY_MODE_XINPUT && xinput_magic_detected()) {
            request_config_mode_reboot();
        }

        if (g_play_mode == DRUM_PLAY_MODE_XINPUT && g_hid_detecting) {
            if (xinput_led_report_seen()) {
                g_hid_detecting = false;
            } else if (to_ms_since_boot(get_absolute_time()) - g_hid_detect_start_ms > 3000) {
                g_hid_detecting = false;
                request_ps3_mode_reboot();
            }
        }

        uint64_t now_us = time_us_64();
        if (now_us - last_report_us >= REPORT_INTERVAL_US) {
            last_report_us = now_us;
            read_inputs(&input_state);

            if (g_play_mode == DRUM_PLAY_MODE_PS3) {
                if (tud_hid_ready()) {
                    build_standard_report(&report, &input_state);
                    convert_to_ps3_drum(&ps3_report, &report);
                    tud_hid_report(0, &ps3_report, sizeof(ps3_report));
                }
            } else if (xinput_ready()) {
                if (g_play_mode == DRUM_PLAY_MODE_FORTNITE) {
                    build_fortnite_report(&report, &input_state);
                } else {
                    build_standard_report(&report, &input_state);
                }
                xinput_send_report(&report);
            }
        }

        if (aligned_leds.enabled && (now_us - last_led_us >= LED_UPDATE_INTERVAL_US)) {
            last_led_us = now_us;
            apa102_update_from_inputs(&aligned_leds, g_pressed_mask);
        }
    }
}
