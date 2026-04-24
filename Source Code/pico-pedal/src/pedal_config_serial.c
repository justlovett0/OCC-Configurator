/*
 * pedal_config_serial.c - CDC serial command handler for pedal controller
 *
 * Handles the config-mode serial protocol: GET_CONFIG, SET, SAVE, SCAN, etc.
 * Supports pedal button mappings, analog setup, and APA102 lighting config.
 */

#include "pedal_config.h"
#include "apa102_leds.h"
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

static const char *input_names[LED_INPUT_COUNT] = {
    "pedal1", "pedal2", "pedal3", "pedal4",
    "unused4", "unused5", "unused6", "unused7",
    "unused8", "unused9", "unused10", "unused11",
    "unused12", "unused13", "unused14", "unused15"
};

static uint8_t hex_nibble(char c) {
    if (c >= '0' && c <= '9') return (uint8_t)(c - '0');
    if (c >= 'a' && c <= 'f') return (uint8_t)(10 + c - 'a');
    if (c >= 'A' && c <= 'F') return (uint8_t)(10 + c - 'A');
    return 0;
}

static uint8_t hex_byte(const char *s) {
    return (uint8_t)((hex_nibble(s[0]) << 4) | hex_nibble(s[1]));
}

//--------------------------------------------------------------------
// Config serialization (GET_CONFIG response)
//--------------------------------------------------------------------

static void send_config(const pedal_config_t *config) {
    char buf[768];

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
        "usb_host_pin=%d,usb_host_dm_first=%u,"
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
        config->usb_host_pin, config->usb_host_dm_first,
        config->device_name);
    (void)n;
    serial_writeln(buf);

    n = snprintf(buf, sizeof(buf),
        "LED:"
        "enabled=%u,count=%u,brightness=%u,data_pin=%d,clock_pin=%d,"
        "loop_enabled=%u,loop_start=%u,loop_end=%u,"
        "breathe_enabled=%u,breathe_start=%u,breathe_end=%u,"
        "breathe_min=%u,breathe_max=%u,"
        "wave_enabled=%u,wave_origin=%u,"
        "loop_speed=%u,breathe_speed=%u,wave_speed=%u",
        config->leds.enabled, config->leds.count, config->leds.base_brightness,
        config->leds.data_pin, config->leds.clock_pin,
        config->leds.loop_enabled, config->leds.loop_start, config->leds.loop_end,
        config->leds.breathe_enabled, config->leds.breathe_start, config->leds.breathe_end,
        config->leds.breathe_min_bright, config->leds.breathe_max_bright,
        config->leds.wave_enabled, config->leds.wave_origin,
        config->leds.loop_speed_ms, config->leds.breathe_speed_ms, config->leds.wave_speed_ms);
    (void)n;
    serial_writeln(buf);

    int pos = snprintf(buf, sizeof(buf), "LED_COLORS:");
    for (int i = 0; i < MAX_LEDS; i++) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%02X%02X%02X%s",
                        config->leds.colors[i].r, config->leds.colors[i].g, config->leds.colors[i].b,
                        (i < MAX_LEDS - 1) ? "," : "");
    }
    serial_writeln(buf);

    pos = snprintf(buf, sizeof(buf), "LED_MAP:");
    for (int i = 0; i < LED_INPUT_COUNT; i++) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%s=%04X:%u%s",
                        input_names[i], config->leds.led_map[i], config->leds.active_brightness[i],
                        (i < LED_INPUT_COUNT - 1) ? "," : "");
    }
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
    if (key_len == 12 && strncmp(param, "usb_host_pin", 12) == 0) {
        int v = atoi(val_str);
        if (!config_usb_host_pin_valid(v)) {
            serial_writeln("ERR:usb_host_pin must be 0-27");
            return true;
        }
        config->usb_host_pin = (int8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 17 && strncmp(param, "usb_host_dm_first", 17) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 1) {
            serial_writeln("ERR:usb_host_dm_first must be 0 or 1");
            return true;
        }
        config->usb_host_dm_first = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

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

    if (key_len == 11 && strncmp(param, "led_enabled", 11) == 0) {
        config->leds.enabled = (atoi(val_str) != 0) ? 1 : 0;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 9 && strncmp(param, "led_count", 9) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > MAX_LEDS) {
            serial_writeln("ERR:0-16");
            return true;
        }
        config->leds.count = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 14 && strncmp(param, "led_brightness", 14) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 31) {
            serial_writeln("ERR:0-31");
            return true;
        }
        config->leds.base_brightness = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }
    if (key_len == 12 && strncmp(param, "led_data_pin", 12) == 0) {
        int v = atoi(val_str);
        if (!apa102_spi_pin_is_valid(v, config->leds.clock_pin)) {
            serial_writeln("ERR:invalid SPI0 pair");
            return true;
        }
        config->leds.data_pin = (int8_t)v;
        serial_writeln("OK");
        return true;
    }
    if (key_len == 13 && strncmp(param, "led_clock_pin", 13) == 0) {
        int v = atoi(val_str);
        if (!apa102_spi_pin_is_valid(config->leds.data_pin, v)) {
            serial_writeln("ERR:invalid SPI0 pair");
            return true;
        }
        config->leds.clock_pin = (int8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len > 10 && strncmp(param, "led_color_", 10) == 0) {
        int idx = atoi(param + 10);
        if (idx < 0 || idx >= MAX_LEDS || strlen(val_str) != 6) {
            serial_writeln("ERR:led index");
            return true;
        }
        config->leds.colors[idx].r = hex_byte(val_str);
        config->leds.colors[idx].g = hex_byte(val_str + 2);
        config->leds.colors[idx].b = hex_byte(val_str + 4);
        serial_writeln("OK");
        return true;
    }

    if (key_len > 8 && strncmp(param, "led_map_", 8) == 0) {
        int idx = atoi(param + 8);
        if (idx < 0 || idx >= LED_INPUT_COUNT) {
            serial_writeln("ERR:input index");
            return true;
        }
        config->leds.led_map[idx] = (uint16_t)(strtoul(val_str, NULL, 16) & 0xFFFFu);
        serial_writeln("OK");
        return true;
    }

    if (key_len > 11 && strncmp(param, "led_active_", 11) == 0) {
        int idx = atoi(param + 11);
        int v = atoi(val_str);
        if (idx < 0 || idx >= LED_INPUT_COUNT) {
            serial_writeln("ERR:input index");
            return true;
        }
        if (v < 0 || v > 31) {
            serial_writeln("ERR:0-31");
            return true;
        }
        config->leds.active_brightness[idx] = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 16 && strncmp(param, "led_loop_enabled", 16) == 0) {
        config->leds.loop_enabled = (atoi(val_str) != 0) ? 1 : 0;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 14 && strncmp(param, "led_loop_start", 14) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v >= MAX_LEDS) {
            serial_writeln("ERR:0-15");
            return true;
        }
        config->leds.loop_start = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 12 && strncmp(param, "led_loop_end", 12) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v >= MAX_LEDS) {
            serial_writeln("ERR:0-15");
            return true;
        }
        config->leds.loop_end = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 19 && strncmp(param, "led_breathe_enabled", 19) == 0) {
        config->leds.breathe_enabled = (atoi(val_str) != 0) ? 1 : 0;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 17 && strncmp(param, "led_breathe_start", 17) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v >= MAX_LEDS) {
            serial_writeln("ERR:0-15");
            return true;
        }
        config->leds.breathe_start = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 15 && strncmp(param, "led_breathe_end", 15) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v >= MAX_LEDS) {
            serial_writeln("ERR:0-15");
            return true;
        }
        config->leds.breathe_end = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 15 && strncmp(param, "led_breathe_min", 15) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 31) {
            serial_writeln("ERR:0-31");
            return true;
        }
        config->leds.breathe_min_bright = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 15 && strncmp(param, "led_breathe_max", 15) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v > 31) {
            serial_writeln("ERR:0-31");
            return true;
        }
        config->leds.breathe_max_bright = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 16 && strncmp(param, "led_wave_enabled", 16) == 0) {
        config->leds.wave_enabled = (atoi(val_str) != 0) ? 1 : 0;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 15 && strncmp(param, "led_wave_origin", 15) == 0) {
        int v = atoi(val_str);
        if (v < 0 || v >= MAX_LEDS) {
            serial_writeln("ERR:0-15");
            return true;
        }
        config->leds.wave_origin = (uint8_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 14 && strncmp(param, "led_loop_speed", 14) == 0) {
        int v = atoi(val_str);
        if (v < 100 || v > 9999) {
            serial_writeln("ERR:100-9999");
            return true;
        }
        config->leds.loop_speed_ms = (uint16_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 17 && strncmp(param, "led_breathe_speed", 17) == 0) {
        int v = atoi(val_str);
        if (v < 100 || v > 9999) {
            serial_writeln("ERR:100-9999");
            return true;
        }
        config->leds.breathe_speed_ms = (uint16_t)v;
        serial_writeln("OK");
        return true;
    }

    if (key_len == 14 && strncmp(param, "led_wave_speed", 14) == 0) {
        int v = atoi(val_str);
        if (v < 100 || v > 9999) {
            serial_writeln("ERR:100-9999");
            return true;
        }
        config->leds.wave_speed_ms = (uint16_t)v;
        serial_writeln("OK");
        return true;
    }

    // ── Device name ──
    // Device name — accept only alphanumeric and space chars
    if (key_len == 11 && strncmp(param, "device_name", 11) == 0) {
        memset(config->device_name, 0, sizeof(config->device_name));
        size_t out = 0;
        for (size_t i = 0; val_str[i] && out < 20; i++) {
            unsigned char c = (unsigned char)val_str[i];
            if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                (c >= '0' && c <= '9') || c == ' ')
                config->device_name[out++] = (char)c;
        }
        while (out > 0 && config->device_name[out - 1] == ' ') out--;
        config->device_name[out] = '\0';
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
    for (int pin = 0; pin <= 28; pin++) {
        if (config_pin_is_usb_host_reserved(config, pin)) continue;
        if (config->leds.enabled &&
            (pin == config->leds.data_pin || pin == config->leds.clock_pin)) continue;
        gpio_init(pin);
        gpio_set_dir(pin, GPIO_IN);
        gpio_pull_up(pin);
        pin_inited[pin] = true;
    }
    sleep_ms(10);  // Let pull-ups settle

    // Read initial state
    bool prev_state[29] = {false};
    for (int pin = 0; pin <= 28; pin++) {
        if (pin_inited[pin])
            prev_state[pin] = !gpio_get(pin);
    }

    serial_writeln("OK");

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
        for (int pin = 0; pin <= 28; pin++) {
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

    if (config->leds.enabled && config->leds.count > 0) {
        apa102_init(&config->leds);
    }

    // Pre-connection timeout — reboot if host never connects within 30s
    uint32_t connect_start_ms = to_ms_since_boot(get_absolute_time());
    const uint32_t CONNECT_TIMEOUT_MS = 30000;
    // Disconnect timeout — reboot if CDC drops for 5s after being connected
    uint32_t disconnect_start_ms = 0;
    bool     was_connected = false;
    const uint32_t DISCONNECT_TIMEOUT_MS = 5000;

    while (true) {
        tud_task();

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());

        // Handle CDC disconnect / not-yet-connected
        if (!tud_cdc_connected()) {
            if (!was_connected) {
                // Never connected — boot back to play mode after timeout
                if ((now_ms - connect_start_ms) > CONNECT_TIMEOUT_MS) {
                    watchdog_reboot(0, 0, 10);
                    while (1) { tight_loop_contents(); }
                }
            } else {
                // Was connected, now dropped — short grace period then reboot
                if (disconnect_start_ms == 0) disconnect_start_ms = now_ms;
                else if ((now_ms - disconnect_start_ms) > DISCONNECT_TIMEOUT_MS) {
                    watchdog_reboot(0, 0, 10);
                    while (1) { tight_loop_contents(); }
                }
            }
            continue;
        }
        was_connected = true;
        disconnect_start_ms = 0;

        if (!tud_cdc_available()) continue;

        int c = tud_cdc_read_char();
        if (c < 0) continue;

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
            else if (strncmp(line, "LED_FLASH:", 10) == 0) {
                int idx = atoi(line + 10);
                if (idx >= 0 && idx < MAX_LEDS) {
                    serial_writeln("OK");
                    apa102_flash_led(&config->leds, (uint8_t)idx, 3);
                } else {
                    serial_writeln("ERR:led index");
                }
            }
            else if (strncmp(line, "LED_SOLID:", 10) == 0) {
                int idx = atoi(line + 10);
                if (idx >= 0 && idx < MAX_LEDS) {
                    uint8_t brightness[MAX_LEDS] = {0};
                    brightness[idx] = 31;
                    serial_writeln("OK");
                    apa102_update(&config->leds, brightness);
                } else {
                    serial_writeln("ERR:led index");
                }
            }
            else if (strcmp(line, "LED_OFF") == 0) {
                apa102_all_off(&config->leds);
                serial_writeln("OK");
            }
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
