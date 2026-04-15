/*
 * main.c - OCC arcade stick firmware
 */

#include <stdio.h>
#include <string.h>

#include "arcadestick_config.h"
#include "arcadestick_config_serial.h"
#include "hardware/gpio.h"
#include "hardware/structs/watchdog.h"
#include "hardware/watchdog.h"
#include "pico/bootrom.h"
#include "pico/stdlib.h"
#include "tusb.h"
#include "usb_descriptors.h"
#include "xinput_driver.h"

#define USB_MOUNT_TIMEOUT_MS 1000

typedef struct {
    uint32_t last_change_us;
    bool stable;
    bool raw;
} debounce_state_t;

typedef struct {
    bool up;
    bool down;
    bool left;
    bool right;
    bool b[ARCADE_ATTACK_COUNT];
    bool start;
    bool select;
    bool guide;
    bool l3;
    bool r3;
} input_state_t;

static arcadestick_config_t g_config;
static volatile bool g_usb_mounted = false;

void tud_mount_cb(void) { g_usb_mounted = true; }
void tud_umount_cb(void) { g_usb_mounted = false; }
void tud_suspend_cb(bool remote_wakeup_en) { (void) remote_wakeup_en; }
void tud_resume_cb(void) {}

static bool debounce_read(debounce_state_t *state, bool current_raw, uint32_t now_us, uint32_t debounce_us) {
    if (current_raw != state->raw) {
        state->raw = current_raw;
        state->last_change_us = now_us;
    } else if (current_raw != state->stable && (now_us - state->last_change_us) >= debounce_us) {
        state->stable = current_raw;
    }
    return state->stable;
}

static void init_input_pin(int8_t pin) {
    if (pin < 0) {
        return;
    }
    gpio_init((uint) pin);
    gpio_set_dir((uint) pin, GPIO_IN);
    gpio_pull_up((uint) pin);
}

static bool read_active_low_pin(int8_t pin) {
    return pin >= 0 && !gpio_get((uint) pin);
}

static bool boot_combo_requested(const arcadestick_config_t *config) {
    if (config->pin_start < 0 || config->pin_select < 0 || config->pin_guide < 0) {
        return false;
    }

    init_input_pin(config->pin_start);
    init_input_pin(config->pin_select);
    init_input_pin(config->pin_guide);
    sleep_ms(2);

    return read_active_low_pin(config->pin_start) &&
           read_active_low_pin(config->pin_select) &&
           read_active_low_pin(config->pin_guide);
}

static uint8_t resolve_stick_mode(const arcadestick_config_t *config) {
    if (config->pin_mode_a >= 0 && config->pin_mode_b >= 0) {
        bool mode_a = read_active_low_pin(config->pin_mode_a);
        bool mode_b = read_active_low_pin(config->pin_mode_b);

        if (!mode_a && !mode_b) return STICK_MODE_DPAD;
        if (mode_a && !mode_b) return STICK_MODE_LEFT_STICK;
        if (!mode_a && mode_b) return STICK_MODE_RIGHT_STICK;
    }
    return config->stick_mode;
}

static uint8_t make_hat(bool up, bool down, bool left, bool right) {
    if (up && !down) {
        if (right && !left) return 1;
        if (left && !right) return 7;
        return 0;
    }
    if (down && !up) {
        if (right && !left) return 3;
        if (left && !right) return 5;
        return 4;
    }
    if (right && !left) return 2;
    if (left && !right) return 6;
    return HID_HAT_CENTERED;
}

static int8_t axis_value(bool negative, bool positive) {
    if (negative == positive) return 0;
    return positive ? 127 : -127;
}

static void build_xinput_report(const input_state_t *state, uint8_t stick_mode, xinput_report_t *report) {
    memset(report, 0, sizeof(*report));
    report->report_id = 0x00;
    report->report_size = 0x14;

    bool up = state->up && !state->down;
    bool down = state->down && !state->up;
    bool left = state->left && !state->right;
    bool right = state->right && !state->left;

    if (stick_mode == STICK_MODE_DPAD) {
        if (up) report->buttons |= XINPUT_BTN_DPAD_UP;
        if (down) report->buttons |= XINPUT_BTN_DPAD_DOWN;
        if (left) report->buttons |= XINPUT_BTN_DPAD_LEFT;
        if (right) report->buttons |= XINPUT_BTN_DPAD_RIGHT;
    } else if (stick_mode == STICK_MODE_LEFT_STICK) {
        report->left_stick_x = (int16_t) axis_value(left, right) * 256;
        report->left_stick_y = (int16_t) axis_value(down, up) * 256;
    } else {
        report->right_stick_x = (int16_t) axis_value(left, right) * 256;
        report->right_stick_y = (int16_t) axis_value(down, up) * 256;
    }

    if (state->b[0]) report->buttons |= XINPUT_BTN_X;
    if (state->b[1]) report->buttons |= XINPUT_BTN_Y;
    if (state->b[2]) report->buttons |= XINPUT_BTN_RIGHT_SHOULDER;
    if (state->b[3]) report->buttons |= XINPUT_BTN_LEFT_SHOULDER;
    if (state->b[4]) report->buttons |= XINPUT_BTN_A;
    if (state->b[5]) report->buttons |= XINPUT_BTN_B;
    if (state->b[6]) report->right_trigger = 255;
    if (state->b[7]) report->left_trigger = 255;

    if (state->start) report->buttons |= XINPUT_BTN_START;
    if (state->select) report->buttons |= XINPUT_BTN_BACK;
    if (state->guide) report->buttons |= XINPUT_BTN_GUIDE;
    if (state->l3) report->buttons |= XINPUT_BTN_LEFT_THUMB;
    if (state->r3) report->buttons |= XINPUT_BTN_RIGHT_THUMB;
}

static void build_hid_report(const input_state_t *state, uint8_t stick_mode, hid_arcadestick_report_t *report) {
    memset(report, 0, sizeof(*report));

    bool up = state->up && !state->down;
    bool down = state->down && !state->up;
    bool left = state->left && !state->right;
    bool right = state->right && !state->left;

    report->buttons = 0;
    for (int i = 0; i < ARCADE_ATTACK_COUNT; ++i) {
        if (state->b[i]) {
            report->buttons |= (uint16_t) (1u << i);
        }
    }
    if (state->start) report->buttons |= (1u << 8);
    if (state->select) report->buttons |= (1u << 9);
    if (state->guide) report->buttons |= (1u << 10);
    if (state->l3) report->buttons |= (1u << 11);
    if (state->r3) report->buttons |= (1u << 12);

    report->hat = HID_HAT_CENTERED;
    report->x = 0;
    report->y = 0;
    report->z = 0;
    report->rz = 0;

    if (stick_mode == STICK_MODE_DPAD) {
        report->hat = make_hat(up, down, left, right);
    } else if (stick_mode == STICK_MODE_LEFT_STICK) {
        report->x = axis_value(left, right);
        report->y = axis_value(up, down);
    } else {
        report->z = axis_value(left, right);
        report->rz = axis_value(up, down);
    }
}

static void request_config_mode_reboot(void) {
    watchdog_hw->scratch[0] = WATCHDOG_CONFIG_MAGIC;
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}

int main(void) {
    stdio_init_all();

    config_load(&g_config);

    if (watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC) {
        watchdog_hw->scratch[0] = 0;
        g_config_mode = true;
    } else if (boot_combo_requested(&g_config)) {
        g_config_mode = true;
    }

    g_play_usb_mode = g_config.usb_mode;

    if (g_config.device_name[0] != '\0') {
        g_device_name = g_config.device_name;
    }

    init_input_pin(g_config.pin_up);
    init_input_pin(g_config.pin_down);
    init_input_pin(g_config.pin_left);
    init_input_pin(g_config.pin_right);
    for (int i = 0; i < ARCADE_ATTACK_COUNT; ++i) {
        init_input_pin(g_config.pin_attack[i]);
    }
    init_input_pin(g_config.pin_start);
    init_input_pin(g_config.pin_select);
    init_input_pin(g_config.pin_guide);
    init_input_pin(g_config.pin_l3);
    init_input_pin(g_config.pin_r3);
    init_input_pin(g_config.pin_mode_a);
    init_input_pin(g_config.pin_mode_b);

    tusb_init();

    if (g_config_mode) {
        config_serial_loop(&g_config);
        watchdog_reboot(0, 0, 10);
        while (1) { tight_loop_contents(); }
    }

    uint32_t start_ms = to_ms_since_boot(get_absolute_time());
    while (!g_usb_mounted) {
        tud_task();
        if ((to_ms_since_boot(get_absolute_time()) - start_ms) >= USB_MOUNT_TIMEOUT_MS) {
            break;
        }
        sleep_ms(1);
    }

    if (!g_usb_mounted) {
        while (true) {
            tight_loop_contents();
        }
    }

    debounce_state_t db_up = {0}, db_down = {0}, db_left = {0}, db_right = {0};
    debounce_state_t db_attack[ARCADE_ATTACK_COUNT] = {0};
    debounce_state_t db_start = {0}, db_select = {0}, db_guide = {0}, db_l3 = {0}, db_r3 = {0};
    xinput_report_t xinput_report = {0}, last_xinput_report = {0};
    hid_arcadestick_report_t hid_report = {0}, last_hid_report = {0};

    while (true) {
        tud_task();

        if (g_play_usb_mode == USB_MODE_XINPUT && xinput_magic_detected()) {
            request_config_mode_reboot();
        }

        uint32_t now_us = (uint32_t) to_us_since_boot(get_absolute_time());
        uint32_t debounce_us = (uint32_t) g_config.debounce_ms * 1000u;
        input_state_t state = {0};

        state.up = debounce_read(&db_up, read_active_low_pin(g_config.pin_up), now_us, debounce_us);
        state.down = debounce_read(&db_down, read_active_low_pin(g_config.pin_down), now_us, debounce_us);
        state.left = debounce_read(&db_left, read_active_low_pin(g_config.pin_left), now_us, debounce_us);
        state.right = debounce_read(&db_right, read_active_low_pin(g_config.pin_right), now_us, debounce_us);
        for (int i = 0; i < ARCADE_ATTACK_COUNT; ++i) {
            state.b[i] = debounce_read(&db_attack[i], read_active_low_pin(g_config.pin_attack[i]), now_us, debounce_us);
        }
        state.start = debounce_read(&db_start, read_active_low_pin(g_config.pin_start), now_us, debounce_us);
        state.select = debounce_read(&db_select, read_active_low_pin(g_config.pin_select), now_us, debounce_us);
        state.guide = debounce_read(&db_guide, read_active_low_pin(g_config.pin_guide), now_us, debounce_us);
        state.l3 = debounce_read(&db_l3, read_active_low_pin(g_config.pin_l3), now_us, debounce_us);
        state.r3 = debounce_read(&db_r3, read_active_low_pin(g_config.pin_r3), now_us, debounce_us);

        uint8_t stick_mode = resolve_stick_mode(&g_config);

        if (g_play_usb_mode == USB_MODE_HID) {
            build_hid_report(&state, stick_mode, &hid_report);
            if (memcmp(&hid_report, &last_hid_report, sizeof(hid_report)) != 0 && tud_hid_ready()) {
                tud_hid_report(0, &hid_report, sizeof(hid_report));
                last_hid_report = hid_report;
            }
        } else {
            build_xinput_report(&state, stick_mode, &xinput_report);
            if (memcmp(&xinput_report, &last_xinput_report, sizeof(xinput_report)) != 0 && xinput_ready()) {
                if (xinput_send_report(&xinput_report)) {
                    last_xinput_report = xinput_report;
                }
            }
        }

        sleep_ms(1);
    }
}
