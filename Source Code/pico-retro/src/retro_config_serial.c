/*
 * retro_config_serial.c - CDC serial command handler for retro controller
 *
 * Handles the config-mode serial protocol at 115200 baud over TinyUSB CDC:
 *   PING        → PONG
 *   GET_CONFIG  → DEVTYPE:pico_retro + CFG:key=value,...
 *   SET:key=val → update in-memory config field with validation
 *   SAVE        → persist config to flash
 *   DEFAULTS    → reset config to factory defaults
 *   REBOOT      → watchdog reboot (returns to play mode)
 *   BOOTSEL     → enter USB bootloader
 *
 * pico-retro has no LEDs and no SCAN/STOP commands — those are guitar/pedal-
 * specific features. Do not add them here.
 */

#include "retro_config_serial.h"
#include "retro_config.h"
#include "tusb.h"
#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "hardware/watchdog.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

//--------------------------------------------------------------------
// Serial I/O helpers
//--------------------------------------------------------------------

static void serial_write(const char *str) {
    uint32_t len = (uint32_t)strlen(str);
    uint32_t sent = 0;
    while (sent < len) {
        uint32_t avail = tud_cdc_write_available();
        if (avail == 0) { tud_task(); continue; }
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

//--------------------------------------------------------------------
// Config serialization (GET_CONFIG response)
//--------------------------------------------------------------------

static void send_config(const retro_config_t *config) {
    char buf[512];

    // Line 1: DEVTYPE — used by configurator to route to the correct screen
    serial_writeln("DEVTYPE:" DEVICE_TYPE);

    // Line 2: CFG — all key=value pairs for the retro controller
    // Key names must exactly match the SET command keys below.
    int n = snprintf(buf, sizeof(buf),
        "CFG:"
        "btn0=%d,btn1=%d,btn2=%d,btn3=%d,btn4=%d,btn5=%d,btn6=%d,"
        "btn7=%d,btn8=%d,btn9=%d,btn10=%d,btn11=%d,btn12=%d,"
        "pin_lt=%d,pin_rt=%d,"
        "mode_lt=%u,mode_rt=%u,"
        "debounce=%u,"
        "device_name=%s,"
        "lt_min=%u,lt_max=%u,rt_min=%u,rt_max=%u,"
        "lt_invert=%u,rt_invert=%u,"
        "lt_ema_alpha=%u,rt_ema_alpha=%u",
        config->pin_buttons[0],  config->pin_buttons[1],
        config->pin_buttons[2],  config->pin_buttons[3],
        config->pin_buttons[4],  config->pin_buttons[5],
        config->pin_buttons[6],  config->pin_buttons[7],
        config->pin_buttons[8],  config->pin_buttons[9],
        config->pin_buttons[10], config->pin_buttons[11],
        config->pin_buttons[12],
        config->pin_lt, config->pin_rt,
        config->mode_lt, config->mode_rt,
        config->debounce_ms,
        config->device_name,
        config->lt_min, config->lt_max,
        config->rt_min, config->rt_max,
        config->lt_invert, config->rt_invert,
        config->lt_ema_alpha, config->rt_ema_alpha);
    (void)n;
    serial_writeln(buf);
}

//--------------------------------------------------------------------
// SET command handler
//--------------------------------------------------------------------

static bool handle_set(retro_config_t *config, const char *param) {
    // Find the '=' separator
    const char *eq = strchr(param, '=');
    if (!eq) {
        serial_writeln("ERR:malformed SET (no = found)");
        return true;
    }

    size_t key_len = (size_t)(eq - param);
    const char *val_str = eq + 1;

    // ── Button pins btn0 through btn12 ──
    for (int i = 0; i < RETRO_BTN_COUNT; i++) {
        char key[8];
        snprintf(key, sizeof(key), "btn%d", i);
        if (key_len == strlen(key) && strncmp(param, key, key_len) == 0) {
            int v = atoi(val_str);
            if (v < -1 || v > 28) {
                serial_writeln("ERR:pin out of range (-1 to 28)");
                return true;
            }
            config->pin_buttons[i] = (int8_t)v;
            serial_writeln("OK");
            return true;
        }
    }

    // ── Trigger pin — LT ──
    if (key_len == 6 && strncmp(param, "pin_lt", 6) == 0) {
        int v = atoi(val_str);
        if (v < -1 || v > 28) {
            serial_writeln("ERR:pin out of range (-1 to 28)");
            return true;
        }
        // Validate ADC-capable pin when mode is analog
        if (config->mode_lt == INPUT_MODE_ANALOG && v != -1) {
            if (v < 26 || v > 28) {
                serial_writeln("ERR:analog pin must be 26-28");
                return true;
            }
        }
        config->pin_lt = (int8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Trigger pin — RT ──
    if (key_len == 6 && strncmp(param, "pin_rt", 6) == 0) {
        int v = atoi(val_str);
        if (v < -1 || v > 28) {
            serial_writeln("ERR:pin out of range (-1 to 28)");
            return true;
        }
        // Validate ADC-capable pin when mode is analog
        if (config->mode_rt == INPUT_MODE_ANALOG && v != -1) {
            if (v < 26 || v > 28) {
                serial_writeln("ERR:analog pin must be 26-28");
                return true;
            }
        }
        config->pin_rt = (int8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Trigger mode — LT ──
    if (key_len == 7 && strncmp(param, "mode_lt", 7) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 1) {
            serial_writeln("ERR:mode_lt must be 0 (digital) or 1 (analog)");
            return true;
        }
        config->mode_lt = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Trigger mode — RT ──
    if (key_len == 7 && strncmp(param, "mode_rt", 7) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 1) {
            serial_writeln("ERR:mode_rt must be 0 (digital) or 1 (analog)");
            return true;
        }
        config->mode_rt = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Calibration — lt_min ──
    if (key_len == 6 && strncmp(param, "lt_min", 6) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 4095) {
            serial_writeln("ERR:lt_min must be 0-4095");
            return true;
        }
        config->lt_min = (uint16_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Calibration — lt_max ──
    if (key_len == 6 && strncmp(param, "lt_max", 6) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 4095) {
            serial_writeln("ERR:lt_max must be 0-4095");
            return true;
        }
        config->lt_max = (uint16_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Calibration — rt_min ──
    if (key_len == 6 && strncmp(param, "rt_min", 6) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 4095) {
            serial_writeln("ERR:rt_min must be 0-4095");
            return true;
        }
        config->rt_min = (uint16_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Calibration — rt_max ──
    if (key_len == 6 && strncmp(param, "rt_max", 6) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 4095) {
            serial_writeln("ERR:rt_max must be 0-4095");
            return true;
        }
        config->rt_max = (uint16_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Invert — lt_invert ──
    if (key_len == 9 && strncmp(param, "lt_invert", 9) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 1) {
            serial_writeln("ERR:lt_invert must be 0 or 1");
            return true;
        }
        config->lt_invert = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Invert — rt_invert ──
    if (key_len == 9 && strncmp(param, "rt_invert", 9) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 1) {
            serial_writeln("ERR:rt_invert must be 0 or 1");
            return true;
        }
        config->rt_invert = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── EMA smoothing — lt_ema_alpha ──
    if (key_len == 12 && strncmp(param, "lt_ema_alpha", 12) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 100) {
            serial_writeln("ERR:lt_ema_alpha must be 0-100");
            return true;
        }
        config->lt_ema_alpha = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── EMA smoothing — rt_ema_alpha ──
    if (key_len == 12 && strncmp(param, "rt_ema_alpha", 12) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 100) {
            serial_writeln("ERR:rt_ema_alpha must be 0-100");
            return true;
        }
        config->rt_ema_alpha = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Debounce ──
    if (key_len == 8 && strncmp(param, "debounce", 8) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 255) {
            serial_writeln("ERR:debounce must be 0-255");
            return true;
        }
        config->debounce_ms = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Device name — alphanumeric + space only, max 20 chars ──
    if (key_len == 11 && strncmp(param, "device_name", 11) == 0) {
        // Validate: only alphanumeric and space characters allowed
        for (size_t i = 0; val_str[i] != '\0'; i++) {
            unsigned char c = (unsigned char)val_str[i];
            if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                  (c >= '0' && c <= '9') || c == ' ')) {
                serial_writeln("ERR:invalid device name");
                return true;
            }
        }
        memset(config->device_name, 0, sizeof(config->device_name));
        size_t out = 0;
        for (size_t i = 0; val_str[i] && out < 20; i++) {
            config->device_name[out++] = val_str[i];
        }
        // Strip trailing spaces
        while (out > 0 && config->device_name[out - 1] == ' ') out--;
        config->device_name[out] = '\0';
        serial_writeln("OK");
        return true;
    }

    serial_writeln("ERR:unknown key");
    return true;
}

//--------------------------------------------------------------------
// Config mode main loop
//--------------------------------------------------------------------

void config_serial_loop(retro_config_t *config) {
    char line[256];
    int  line_pos = 0;

    // Reboot to play mode if no activity for 30 seconds
    uint32_t last_activity_ms = to_ms_since_boot(get_absolute_time());
    const uint32_t CONNECT_TIMEOUT_MS = 30000;

    // Reboot to play mode if CDC disconnects for 5 seconds
    uint32_t disconnect_start_ms = 0;
    bool     was_connected = true;
    const uint32_t DISCONNECT_TIMEOUT_MS = 5000;

    while (true) {
        tud_task();

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());

        // Handle CDC disconnect / reconnect
        if (!tud_cdc_connected()) {
            if (was_connected) {
                disconnect_start_ms = now_ms;
                was_connected = false;
            } else if ((now_ms - disconnect_start_ms) >= DISCONNECT_TIMEOUT_MS) {
                watchdog_reboot(0, 0, 10);
                while (1) { tight_loop_contents(); }
            }
            sleep_ms(1);
            continue;
        }
        was_connected = true;

        // Activity timeout — reboot if idle too long
        if ((now_ms - last_activity_ms) >= CONNECT_TIMEOUT_MS) {
            watchdog_reboot(0, 0, 10);
            while (1) { tight_loop_contents(); }
        }

        if (!tud_cdc_available()) {
            sleep_ms(1);
            continue;
        }

        int c = tud_cdc_read_char();
        if (c < 0) continue;

        last_activity_ms = now_ms;

        if (c == '\r' || c == '\n') {
            if (line_pos == 0) continue;
            line[line_pos] = '\0';
            line_pos = 0;

            // ── PING ──
            if (strcmp(line, "PING") == 0) {
                serial_writeln("PONG");
            }
            // ── GET_CONFIG ──
            else if (strcmp(line, "GET_CONFIG") == 0) {
                send_config(config);
            }
            // ── SET:key=value ──
            else if (strncmp(line, "SET:", 4) == 0) {
                handle_set(config, line + 4);
            }
            // ── SAVE ──
            else if (strcmp(line, "SAVE") == 0) {
                config_update_checksum(config);
                config_save(config);
                serial_writeln("OK");
            }
            // ── DEFAULTS ──
            else if (strcmp(line, "DEFAULTS") == 0) {
                config_set_defaults(config);
                serial_writeln("OK");
            }
            // ── REBOOT ──
            else if (strcmp(line, "REBOOT") == 0) {
                serial_writeln("OK");
                sleep_ms(50);
                watchdog_reboot(0, 0, 10);
                while (1) { tight_loop_contents(); }
            }
            // ── BOOTSEL ──
            else if (strcmp(line, "BOOTSEL") == 0) {
                serial_writeln("OK");
                sleep_ms(50);
                reset_usb_boot(0, 0);
            }
            // ── Unknown command ──
            else {
                serial_writeln("ERR:unknown command");
            }
        } else if (line_pos < (int)sizeof(line) - 1) {
            line[line_pos++] = (char)c;
        }
    }
}
