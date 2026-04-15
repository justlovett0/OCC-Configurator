/*
 * arcadestick_config_serial.c - CDC serial command handler for arcade stick config mode
 */

#include "arcadestick_config_serial.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hardware/watchdog.h"
#include "pico/bootrom.h"
#include "pico/stdlib.h"
#include "tusb.h"

static void serial_write(const char *str) {
    uint32_t len = (uint32_t) strlen(str);
    uint32_t sent = 0;
    while (sent < len) {
        uint32_t avail = tud_cdc_write_available();
        if (avail == 0) {
            tud_task();
            continue;
        }
        uint32_t chunk = (len - sent < avail) ? (len - sent) : avail;
        tud_cdc_write(str + sent, chunk);
        tud_cdc_write_flush();
        sent += chunk;
    }
}

static void serial_writeln(const char *str) {
    serial_write(str);
    serial_write("\r\n");
}

static bool parse_pin_value(const char *val_str, int *out_pin) {
    int v = atoi(val_str);
    if (v < -1 || v > 28) {
        serial_writeln("ERR:pin out of range (-1 to 28)");
        return false;
    }
    *out_pin = v;
    return true;
}

static void send_config(const arcadestick_config_t *config) {
    char buf[512];

    serial_writeln("DEVTYPE:" DEVICE_TYPE);

    snprintf(
        buf, sizeof(buf),
        "CFG:"
        "pin_up=%d,pin_down=%d,pin_left=%d,pin_right=%d,"
        "pin_b1=%d,pin_b2=%d,pin_b3=%d,pin_b4=%d,pin_b5=%d,pin_b6=%d,pin_b7=%d,pin_b8=%d,"
        "pin_start=%d,pin_select=%d,pin_guide=%d,pin_l3=%d,pin_r3=%d,"
        "pin_mode_a=%d,pin_mode_b=%d,"
        "usb_mode=%u,stick_mode=%u,debounce=%u,device_name=%s",
        config->pin_up, config->pin_down, config->pin_left, config->pin_right,
        config->pin_attack[0], config->pin_attack[1], config->pin_attack[2], config->pin_attack[3],
        config->pin_attack[4], config->pin_attack[5], config->pin_attack[6], config->pin_attack[7],
        config->pin_start, config->pin_select, config->pin_guide, config->pin_l3, config->pin_r3,
        config->pin_mode_a, config->pin_mode_b,
        config->usb_mode, config->stick_mode, config->debounce_ms, config->device_name);
    serial_writeln(buf);
}

static bool handle_set(arcadestick_config_t *config, const char *param) {
    const char *eq = strchr(param, '=');
    if (!eq) {
        serial_writeln("ERR:malformed SET (no = found)");
        return true;
    }

    size_t key_len = (size_t) (eq - param);
    const char *val_str = eq + 1;
    int pin_value = -1;

    struct pin_key_map {
        const char *name;
        int8_t *dest;
    };
    struct pin_key_map pin_map[] = {
        {"pin_up", &config->pin_up},
        {"pin_down", &config->pin_down},
        {"pin_left", &config->pin_left},
        {"pin_right", &config->pin_right},
        {"pin_start", &config->pin_start},
        {"pin_select", &config->pin_select},
        {"pin_guide", &config->pin_guide},
        {"pin_l3", &config->pin_l3},
        {"pin_r3", &config->pin_r3},
        {"pin_mode_a", &config->pin_mode_a},
        {"pin_mode_b", &config->pin_mode_b},
    };

    for (size_t i = 0; i < sizeof(pin_map) / sizeof(pin_map[0]); ++i) {
        if (strlen(pin_map[i].name) == key_len && strncmp(param, pin_map[i].name, key_len) == 0) {
            if (!parse_pin_value(val_str, &pin_value)) {
                return true;
            }
            *pin_map[i].dest = (int8_t) pin_value;
            serial_writeln("OK");
            return true;
        }
    }

    for (int i = 0; i < ARCADE_ATTACK_COUNT; ++i) {
        char key[12];
        snprintf(key, sizeof(key), "pin_b%d", i + 1);
        if (strlen(key) == key_len && strncmp(param, key, key_len) == 0) {
            if (!parse_pin_value(val_str, &pin_value)) {
                return true;
            }
            config->pin_attack[i] = (int8_t) pin_value;
            serial_writeln("OK");
            return true;
        }
    }

    if (key_len == 8 && strncmp(param, "usb_mode", 8) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 1) {
            serial_writeln("ERR:usb_mode must be 0 (xinput) or 1 (hid)");
            return true;
        }
        config->usb_mode = (uint8_t) v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 10 && strncmp(param, "stick_mode", 10) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 2) {
            serial_writeln("ERR:stick_mode must be 0 (dpad), 1 (left), or 2 (right)");
            return true;
        }
        config->stick_mode = (uint8_t) v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 8 && strncmp(param, "debounce", 8) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 255) {
            serial_writeln("ERR:debounce must be 0-255");
            return true;
        }
        config->debounce_ms = (uint8_t) v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 11 && strncmp(param, "device_name", 11) == 0) {
        size_t out = 0;
        memset(config->device_name, 0, sizeof(config->device_name));
        for (size_t i = 0; val_str[i] != '\0' && out < DEVICE_NAME_MAX; ++i) {
            unsigned char ch = (unsigned char) val_str[i];
            if (isalnum(ch) || ch == ' ' || ch == '-' || ch == '_') {
                config->device_name[out++] = (char) ch;
            }
        }
        while (out > 0 && config->device_name[out - 1] == ' ') {
            out--;
        }
        config->device_name[out] = '\0';
        serial_writeln("OK");
        return true;
    }

    serial_writeln("ERR:unknown key");
    return true;
}

static void run_scan(void) {
    serial_writeln("OK");
    while (true) {
        tud_task();

        for (int pin = 0; pin <= 28; ++pin) {
            if (pin >= 23 && pin <= 25) {
                continue;
            }
            if (pin < 26) {
                gpio_init((uint) pin);
                gpio_set_dir((uint) pin, GPIO_IN);
                gpio_pull_up((uint) pin);
            }
            bool active = false;
            if (pin >= 26) {
                gpio_init((uint) pin);
                gpio_set_dir((uint) pin, GPIO_IN);
                gpio_pull_up((uint) pin);
                active = !gpio_get((uint) pin);
            } else {
                active = !gpio_get((uint) pin);
            }
            if (active) {
                char line[32];
                snprintf(line, sizeof(line), "PIN:%d", pin);
                serial_writeln(line);
                sleep_ms(120);
            }
        }

        if (tud_cdc_available()) {
            char line[64];
            int idx = 0;
            while (tud_cdc_available() && idx < (int) sizeof(line) - 1) {
                char ch = (char) tud_cdc_read_char();
                if (ch == '\r' || ch == '\n') {
                    break;
                }
                line[idx++] = ch;
            }
            line[idx] = '\0';
            if (strcmp(line, "STOP") == 0) {
                serial_writeln("OK");
                return;
            }
        }

        sleep_ms(10);
    }
}

void config_serial_loop(arcadestick_config_t *config) {
    char line[160];
    int idx = 0;
    absolute_time_t last_activity = get_absolute_time();

    while (!tud_cdc_connected()) {
        tud_task();
        sleep_ms(10);
    }

    while (true) {
        tud_task();

        while (tud_cdc_available()) {
            char ch = (char) tud_cdc_read_char();
            last_activity = get_absolute_time();

            if (ch == '\r' || ch == '\n') {
                if (idx == 0) {
                    continue;
                }
                line[idx] = '\0';
                idx = 0;

                if (strcmp(line, "PING") == 0) {
                    serial_writeln("PONG");
                } else if (strcmp(line, "GET_CONFIG") == 0) {
                    send_config(config);
                } else if (strncmp(line, "SET:", 4) == 0) {
                    handle_set(config, line + 4);
                } else if (strcmp(line, "SAVE") == 0) {
                    config_update_checksum(config);
                    config_save(config);
                    serial_writeln("OK");
                } else if (strcmp(line, "DEFAULTS") == 0) {
                    config_set_defaults(config);
                    serial_writeln("OK");
                } else if (strcmp(line, "REBOOT") == 0) {
                    serial_writeln("OK");
                    sleep_ms(20);
                    watchdog_reboot(0, 0, 10);
                    while (1) { tight_loop_contents(); }
                } else if (strcmp(line, "BOOTSEL") == 0) {
                    serial_writeln("OK");
                    sleep_ms(20);
                    reset_usb_boot(0, 0);
                } else if (strcmp(line, "GET_FW_DATE") == 0) {
                    serial_writeln("FW_DATE:" BUILD_DATE_STR);
                } else if (strcmp(line, "SCAN") == 0) {
                    run_scan();
                } else if (strcmp(line, "STOP") == 0) {
                    serial_writeln("OK");
                } else {
                    serial_writeln("ERR:unknown command");
                }
            } else if (idx < (int) sizeof(line) - 1) {
                line[idx++] = ch;
            }
        }

        if (absolute_time_diff_us(last_activity, get_absolute_time()) > 1000 * 1000) {
            sleep_ms(2);
        }
    }
}
