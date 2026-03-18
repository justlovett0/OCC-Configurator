/*
 * pedal_config_serial.c - CDC serial command handler for pedal controller
 *
 * Handles the config-mode serial protocol: GET_CONFIG, SET, SAVE, SCAN, etc.
 * Much simpler than the guitar variant — only 4 buttons with mappings,
 * debounce, and device name.
 */

#include "pedal_config.h"
#include "usb_descriptors.h"
#include "tusb.h"
#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "hardware/gpio.h"
#include "hardware/adc.h"
#include "hardware/watchdog.h"
#include "hardware/structs/watchdog.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#define MONITOR_INTERVAL_MS  50   // 20 Hz streaming rate

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
// Button name table (for mapping display)
//--------------------------------------------------------------------

static const char *button_names[BTN_IDX_COUNT] = {
    "green", "red", "yellow", "blue", "orange",
    "strum_up", "strum_down", "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right", "guide",
    "whammy", "tilt"
};

//--------------------------------------------------------------------
// Config serialization (GET_CONFIG response)
//--------------------------------------------------------------------

static void send_config(const pedal_config_t *config) {
    char buf[640];

    // Line 1: DEVTYPE
    serial_writeln("DEVTYPE:" DEVICE_TYPE);

    // Line 2: CFG — all key=value pairs
    int n = snprintf(buf, sizeof(buf),
        "CFG:"
        "pedal0=%d,pedal1=%d,pedal2=%d,pedal3=%d,"
        "pedal0_map=%u,pedal1_map=%u,pedal2_map=%u,pedal3_map=%u,"
        "debounce=%u,"
        "adc0=%d,adc0_axis=%u,adc0_invert=%u,adc0_min=%u,adc0_max=%u,"
        "adc1=%d,adc1_axis=%u,adc1_invert=%u,adc1_min=%u,adc1_max=%u,"
        "device_name=%s",
        config->pin_buttons[0], config->pin_buttons[1],
        config->pin_buttons[2], config->pin_buttons[3],
        config->button_mapping[0], config->button_mapping[1],
        config->button_mapping[2], config->button_mapping[3],
        config->debounce_ms,
        config->adc_pin[0], config->adc_axis[0],
        config->adc_invert[0], config->adc_min[0], config->adc_max[0],
        config->adc_pin[1], config->adc_axis[1],
        config->adc_invert[1], config->adc_min[1], config->adc_max[1],
        config->device_name);
    (void)n;
    serial_writeln(buf);
}

//--------------------------------------------------------------------
// SET command handler
//--------------------------------------------------------------------

static bool handle_set(pedal_config_t *config, const char *param) {
    // Find the '=' separator
    const char *eq = strchr(param, '=');
    if (!eq) return false;

    // Extract key and value
    size_t key_len = (size_t)(eq - param);
    const char *val_str = eq + 1;

    // ── Pedal button pins ──
    for (int i = 0; i < PEDAL_BUTTON_COUNT; i++) {
        char key[8];
        snprintf(key, sizeof(key), "pedal%d", i);
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

    // ── Pedal button mappings ──
    for (int i = 0; i < PEDAL_BUTTON_COUNT; i++) {
        char key[16];
        snprintf(key, sizeof(key), "pedal%d_map", i);
        if (key_len == strlen(key) && strncmp(param, key, key_len) == 0) {
            int v = atoi(val_str);
            if (v < 0 || v >= BTN_IDX_COUNT) {
                serial_writeln("ERR:mapping out of range (0 to 15)");
                return true;
            }
            config->button_mapping[i] = (uint8_t)v;
            serial_writeln("OK");
            return true;
        }
    }

    // ── Analog input pins ──
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        char key[8];
        snprintf(key, sizeof(key), "adc%d", i);
        if (key_len == strlen(key) && strncmp(param, key, key_len) == 0) {
            int v = atoi(val_str);
            if (v != -1 && (v < 26 || v > 28)) {
                serial_writeln("ERR:adc pin must be 26, 27, 28, or -1 (disabled)");
                return true;
            }
            config->adc_pin[i] = (int8_t)v;
            serial_writeln("OK");
            return true;
        }
    }

    // ── Analog axis mapping ──
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        char key[16];
        snprintf(key, sizeof(key), "adc%d_axis", i);
        if (key_len == strlen(key) && strncmp(param, key, key_len) == 0) {
            int v = atoi(val_str);
            if (v < 0 || v >= ADC_AXIS_COUNT) {
                serial_writeln("ERR:adc axis 0=whammy 1=tilt");
                return true;
            }
            config->adc_axis[i] = (uint8_t)v;
            serial_writeln("OK");
            return true;
        }
    }

    // ── Analog invert ──
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        char key[16];
        snprintf(key, sizeof(key), "adc%d_invert", i);
        if (key_len == strlen(key) && strncmp(param, key, key_len) == 0) {
            config->adc_invert[i] = (atoi(val_str) != 0) ? 1 : 0;
            serial_writeln("OK");
            return true;
        }
    }

    // ── Analog calibration min ──
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        char key[16];
        snprintf(key, sizeof(key), "adc%d_min", i);
        if (key_len == strlen(key) && strncmp(param, key, key_len) == 0) {
            int v = atoi(val_str);
            if (v < 0 || v > 4095) {
                serial_writeln("ERR:adc_min 0-4095");
                return true;
            }
            config->adc_min[i] = (uint16_t)v;
            serial_writeln("OK");
            return true;
        }
    }

    // ── Analog calibration max ──
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        char key[16];
        snprintf(key, sizeof(key), "adc%d_max", i);
        if (key_len == strlen(key) && strncmp(param, key, key_len) == 0) {
            int v = atoi(val_str);
            if (v < 0 || v > 4095) {
                serial_writeln("ERR:adc_max 0-4095");
                return true;
            }
            config->adc_max[i] = (uint16_t)v;
            serial_writeln("OK");
            return true;
        }
    }

    // ── Debounce ──
    if (key_len == 8 && strncmp(param, "debounce", 8) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 50) {
            serial_writeln("ERR:debounce 0-50");
            return true;
        }
        config->debounce_ms = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Device name ──
    if (key_len == 11 && strncmp(param, "device_name", 11) == 0) {
        size_t vlen = strlen(val_str);
        if (vlen > DEVICE_NAME_MAX) vlen = DEVICE_NAME_MAX;
        memset(config->device_name, 0, sizeof(config->device_name));
        memcpy(config->device_name, val_str, vlen);
        config->device_name[DEVICE_NAME_MAX] = '\0';
        serial_writeln("OK");
        return true;
    }

    serial_writeln("ERR:unknown key");
    return true;
}

//--------------------------------------------------------------------
// SCAN mode — detect button presses on GPIO pins
//--------------------------------------------------------------------

static void run_scan(pedal_config_t *config) {
    // Set all valid GPIO pins as input with pull-up
    bool pin_inited[29] = {false};
    for (int pin = 2; pin <= 28; pin++) {
        // Skip PIO-USB pins (GP0, GP1)
        if (pin == 0 || pin == 1) continue;
        gpio_init(pin);
        gpio_set_dir(pin, GPIO_IN);
        gpio_pull_up(pin);
        pin_inited[pin] = true;
    }
    sleep_ms(10);  // Let pull-ups settle

    // Read initial state
    bool prev_state[29] = {false};
    for (int pin = 2; pin <= 28; pin++) {
        if (pin_inited[pin])
            prev_state[pin] = !gpio_get(pin);
    }

    serial_writeln("SCAN:started");

    // Scan loop — report pin changes until STOP received
    char line[64];
    char out[32];
    int line_pos = 0;

    while (true) {
        tud_task();

        // Check for incoming serial commands
        if (tud_cdc_available()) {
            int c = tud_cdc_read_char();
            if (c == '\r' || c == '\n') {
                if (line_pos > 0) {
                    line[line_pos] = '\0';
                    if (strcmp(line, "STOP") == 0) {
                        serial_writeln("OK");
                        return;
                    }
                    line_pos = 0;
                }
            } else if (line_pos < (int)sizeof(line) - 1) {
                line[line_pos++] = (char)c;
            }
        }

        // Poll digital pins for changes
        for (int pin = 2; pin <= 28; pin++) {
            if (!pin_inited[pin]) continue;
            bool pressed = !gpio_get(pin);
            if (pressed && !prev_state[pin]) {
                snprintf(out, sizeof(out), "PIN:%d", pin);
                serial_writeln(out);
            }
            prev_state[pin] = pressed;
        }

        sleep_ms(5);
    }
}

//--------------------------------------------------------------------
// MONITOR_ADC — stream live ADC readings for the configurator bar graph
//--------------------------------------------------------------------

static void run_monitor_adc(int pin) {
    if (pin < 26 || pin > 28) {
        serial_writeln("ERR:adc pin must be 26, 27, or 28");
        return;
    }

    int ch = pin - 26;
    adc_init();
    adc_gpio_init((uint)pin);
    sleep_ms(10);

    serial_writeln("OK");

    char cmd_buf[32];
    int  cmd_pos = 0;
    uint32_t last_send_ms = 0;

    while (true) {
        tud_task();

        // Check for STOP command
        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                cmd_buf[cmd_pos] = '\0';
                if (strcmp(cmd_buf, "STOP") == 0) {
                    serial_writeln("OK");
                    return;
                }
                cmd_pos = 0;
            } else if (cmd_pos < (int)sizeof(cmd_buf) - 1) {
                cmd_buf[cmd_pos++] = c;
            }
        }

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        if ((now_ms - last_send_ms) >= MONITOR_INTERVAL_MS) {
            last_send_ms = now_ms;
            adc_select_input((uint)ch);
            uint16_t val = adc_read();
            char buf[20];
            snprintf(buf, sizeof(buf), "MVAL:%u", val);
            serial_writeln(buf);
        }

        sleep_ms(1);
    }
}

//--------------------------------------------------------------------
// Config mode main loop
//--------------------------------------------------------------------

void config_mode_main(pedal_config_t *config) {
    char line[256];
    int  line_pos = 0;

    // Connection timeout — reboot if no data for 30s
    uint32_t last_activity_ms = to_ms_since_boot(get_absolute_time());
    const uint32_t CONNECT_TIMEOUT_MS = 30000;
    // Disconnect timeout — reboot if CDC disconnects for 5s
    uint32_t disconnect_start_ms = 0;
    bool     was_connected = true;
    const uint32_t DISCONNECT_TIMEOUT_MS = 5000;

    while (true) {
        tud_task();

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());

        // Handle CDC disconnect
        if (!tud_cdc_connected()) {
            if (was_connected) {
                disconnect_start_ms = now_ms;
                was_connected = false;
            } else if ((now_ms - disconnect_start_ms) >= DISCONNECT_TIMEOUT_MS) {
                // Disconnected too long — reboot to play mode
                watchdog_reboot(0, 0, 10);
                while (1) { tight_loop_contents(); }
            }
            continue;
        }
        was_connected = true;

        // Connection activity timeout
        if ((now_ms - last_activity_ms) >= CONNECT_TIMEOUT_MS) {
            watchdog_reboot(0, 0, 10);
            while (1) { tight_loop_contents(); }
        }

        if (!tud_cdc_available()) continue;

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
            // ── SCAN / STOP ──
            else if (strcmp(line, "SCAN") == 0) {
                run_scan(config);
            }
            // ── MONITOR_ADC:<pin> ──
            else if (strncmp(line, "MONITOR_ADC:", 12) == 0) {
                int pin = atoi(line + 12);
                run_monitor_adc(pin);
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
