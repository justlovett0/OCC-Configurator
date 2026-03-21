/*
 * drum_config_serial.c - CDC serial config mode for drum kit
 *
 * Commands: PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS,
 *           SCAN, REBOOT, BOOTSEL,
 *           LED_FLASH:N, LED_SOLID:N, LED_OFF
 *
 * GET_CONFIG response (5 lines):
 *   DEVTYPE:drum_kit
 *   CFG:red_drum=N,...,foot_pedal=N,debounce=N,device_name=...
 *   LED:enabled=N,count=N,brightness=N,loop_enabled=N,...,wave_origin=N,loop_speed=N,breathe_speed=N,wave_speed=N
 *   LED_COLORS:R0G0B0,R1G1B1,...
 *   LED_MAP:name=mask:brightness,...
 *
 * SET keys: red_drum, yellow_drum, blue_drum, green_drum,
 *           yellow_cym, blue_cym, green_cym, start, select,
 *           dpad_up, dpad_down, dpad_left, dpad_right, foot_pedal,
 *           debounce, device_name,
 *           led_enabled, led_count, led_brightness,
 *           led_color_N (hex RRGGBB), led_map_N (hex 16-bit mask),
 *           led_active_N (0-31),
 *           led_loop_enabled, led_loop_start, led_loop_end,
 *           led_breathe_enabled, led_breathe_start, led_breathe_end,
 *           led_breathe_min, led_breathe_max,
 *           led_wave_enabled, led_wave_origin,
 *           led_loop_speed, led_breathe_speed, led_wave_speed
 */

#include "drum_config_serial.h"
#include "drum_config.h"
// apa102_leds.h is included transitively via drum_config.h
#include "tusb.h"
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/watchdog.h"
#include "pico/bootrom.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

// BUILD_DATE_STR is injected by CMake (-DBUILD_DATE_STR="...").
// Falls back to the compiler's __DATE__ if not provided.
#ifndef BUILD_DATE_STR
#define BUILD_DATE_STR __DATE__
#endif

#define CMD_BUF_SIZE          512
#define SCAN_REPEAT_MS        300
#define GPIO_MIN              0
#define GPIO_MAX              28
#define CONNECT_TIMEOUT_MS    30000
#define DISCONNECT_TIMEOUT_MS 5000

static const char *button_names[BTN_IDX_COUNT] = {
    "red_drum", "yellow_drum", "blue_drum", "green_drum",
    "yellow_cym", "blue_cym", "green_cym",
    "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "foot_pedal"
};

// Input names for LED mapping (matches button order)
static const char *input_names[DRUM_INPUT_COUNT] = {
    "red_drum", "yellow_drum", "blue_drum", "green_drum",
    "yellow_cym", "blue_cym", "green_cym",
    "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "foot_pedal"
};

//--------------------------------------------------------------------
// Serial I/O
//--------------------------------------------------------------------

static void serial_write(const char *str) {
    if (!tud_cdc_connected()) return;
    uint32_t len = strlen(str);
    uint32_t sent = 0;
    while (sent < len) {
        uint32_t avail = tud_cdc_write_available();
        if (avail == 0) { tud_task(); tud_cdc_write_flush(); continue; }
        uint32_t chunk = len - sent;
        if (chunk > avail) chunk = avail;
        tud_cdc_write(str + sent, chunk);
        sent += chunk;
    }
    tud_cdc_write_flush();
}

static void serial_writeln(const char *str) {
    serial_write(str);
    serial_write("\n");
}

//--------------------------------------------------------------------
// Hex helpers
//--------------------------------------------------------------------

static uint8_t hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + c - 'a';
    if (c >= 'A' && c <= 'F') return 10 + c - 'A';
    return 0;
}

static uint8_t hex_byte(const char *s) {
    return (hex_nibble(s[0]) << 4) | hex_nibble(s[1]);
}

//--------------------------------------------------------------------
// Config serialization
//--------------------------------------------------------------------

static void send_config(const drum_config_t *config) {
    char buf[512];
    int pos;

    // Device type — configurator reads this to select the correct UI
    serial_writeln("DEVTYPE:" DEVICE_TYPE);

    // Line 1: button pins + debounce + device name
    pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "CFG:");
    for (int i = 0; i < BTN_IDX_COUNT; i++)
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%s=%d,",
                        button_names[i], (int)config->pin_buttons[i]);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "debounce=%d,",
                    (int)config->debounce_ms);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "device_name=%s",
                    config->device_name);
    serial_writeln(buf);

    // Line 2: LED global settings
    pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos,
                    "LED:enabled=%d,count=%d,brightness=%d,"
                    "loop_enabled=%d,loop_start=%d,loop_end=%d,"
                    "breathe_enabled=%d,breathe_start=%d,breathe_end=%d,"
                    "breathe_min=%d,breathe_max=%d,"
                    "wave_enabled=%d,wave_origin=%d,"
                    "loop_speed=%d,breathe_speed=%d,wave_speed=%d",
                    (int)config->leds.enabled,
                    (int)config->leds.count,
                    (int)config->leds.base_brightness,
                    (int)config->leds.loop_enabled,
                    (int)config->leds.loop_start,
                    (int)config->leds.loop_end,
                    (int)config->leds.breathe_enabled,
                    (int)config->leds.breathe_start,
                    (int)config->leds.breathe_end,
                    (int)config->leds.breathe_min_bright,
                    (int)config->leds.breathe_max_bright,
                    (int)config->leds.wave_enabled,
                    (int)config->leds.wave_origin,
                    (int)config->leds.loop_speed_ms,
                    (int)config->leds.breathe_speed_ms,
                    (int)config->leds.wave_speed_ms);
    serial_writeln(buf);

    // Line 3: LED colors (R,G,B hex per LED)
    pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "LED_COLORS:");
    for (int i = 0; i < MAX_LEDS; i++) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%02X%02X%02X",
                        config->leds.colors[i].r,
                        config->leds.colors[i].g,
                        config->leds.colors[i].b);
        if (i < MAX_LEDS - 1) buf[pos++] = ',';
    }
    serial_writeln(buf);

    // Line 4: LED map + active brightness
    pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "LED_MAP:");
    for (int i = 0; i < DRUM_INPUT_COUNT; i++) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%s=%04X:%d",
                        input_names[i],
                        (unsigned)config->leds.led_map[i],
                        (int)config->leds.active_brightness[i]);
        if (i < DRUM_INPUT_COUNT - 1) buf[pos++] = ',';
    }
    serial_writeln(buf);
}

//--------------------------------------------------------------------
// SET handler
//--------------------------------------------------------------------

static bool handle_led_set(drum_config_t *config, const char *key, const char *val) {
    if (strcmp(key, "led_enabled") == 0) {
        config->leds.enabled = (uint8_t)atoi(val);
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_count") == 0) {
        int v = atoi(val);
        if (v < 0 || v > MAX_LEDS) { serial_writeln("ERR:range 0-16"); return true; }
        config->leds.count = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_brightness") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 31) { serial_writeln("ERR:range 0-31"); return true; }
        config->leds.base_brightness = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strncmp(key, "led_color_", 10) == 0) {
        int idx = atoi(key + 10);
        if (idx < 0 || idx >= MAX_LEDS) { serial_writeln("ERR:led index"); return true; }
        if (strlen(val) < 6) { serial_writeln("ERR:need RRGGBB hex"); return true; }
        config->leds.colors[idx].r = hex_byte(val);
        config->leds.colors[idx].g = hex_byte(val + 2);
        config->leds.colors[idx].b = hex_byte(val + 4);
        serial_writeln("OK"); return true;
    }
    if (strncmp(key, "led_map_", 8) == 0) {
        int idx = atoi(key + 8);
        if (idx < 0 || idx >= DRUM_INPUT_COUNT) { serial_writeln("ERR:input index"); return true; }
        config->leds.led_map[idx] = (uint16_t)strtoul(val, NULL, 16);
        serial_writeln("OK"); return true;
    }
    if (strncmp(key, "led_active_", 11) == 0) {
        int idx = atoi(key + 11);
        if (idx < 0 || idx >= DRUM_INPUT_COUNT) { serial_writeln("ERR:input index"); return true; }
        int v = atoi(val);
        if (v < 0 || v > 31) { serial_writeln("ERR:range 0-31"); return true; }
        config->leds.active_brightness[idx] = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_loop_enabled") == 0) {
        config->leds.loop_enabled = (uint8_t)atoi(val);
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_loop_start") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:range"); return true; }
        config->leds.loop_start = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_loop_end") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:range"); return true; }
        config->leds.loop_end = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_enabled") == 0) {
        config->leds.breathe_enabled = (uint8_t)atoi(val);
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_start") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:range"); return true; }
        config->leds.breathe_start = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_end") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:range"); return true; }
        config->leds.breathe_end = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_min") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 31) { serial_writeln("ERR:0-31"); return true; }
        config->leds.breathe_min_bright = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_max") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 31) { serial_writeln("ERR:0-31"); return true; }
        config->leds.breathe_max_bright = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_wave_enabled") == 0) {
        config->leds.wave_enabled = (uint8_t)atoi(val);
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_wave_origin") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:0-15"); return true; }
        config->leds.wave_origin = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_loop_speed") == 0) {
        int v = atoi(val);
        if (v < 100 || v > 9999) { serial_writeln("ERR:100-9999"); return true; }
        config->leds.loop_speed_ms = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_speed") == 0) {
        int v = atoi(val);
        if (v < 100 || v > 9999) { serial_writeln("ERR:100-9999"); return true; }
        config->leds.breathe_speed_ms = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_wave_speed") == 0) {
        int v = atoi(val);
        if (v < 100 || v > 9999) { serial_writeln("ERR:100-9999"); return true; }
        config->leds.wave_speed_ms = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    return false;  // Not an LED key
}

static void handle_set(drum_config_t *config, const char *kv) {
    char key[64];
    const char *eq = strchr(kv, '=');
    if (!eq) { serial_writeln("ERR:no ="); return; }

    size_t klen = (size_t)(eq - kv);
    if (klen >= sizeof(key)) { serial_writeln("ERR:key too long"); return; }
    memcpy(key, kv, klen);
    key[klen] = '\0';
    const char *val = eq + 1;

    // Button pins (covers all BTN_IDX_COUNT entries including new ones)
    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        if (strcmp(key, button_names[i]) == 0) {
            int pin = atoi(val);
            if (pin < -1 || pin > 28) { serial_writeln("ERR:invalid pin"); return; }
            config->pin_buttons[i] = (int8_t)pin;
            serial_writeln("OK");
            return;
        }
    }

    if (strcmp(key, "debounce") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 50) { serial_writeln("ERR:range 0-50"); return; }
        config->debounce_ms = (uint8_t)v;
        serial_writeln("OK");
        return;
    }

    // Device name — accept only alphanumeric and space chars
    if (strcmp(key, "device_name") == 0) {
        memset(config->device_name, 0, sizeof(config->device_name));
        size_t out = 0;
        for (size_t i = 0; val[i] && out < 20; i++) {
            unsigned char c = (unsigned char)val[i];
            if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                (c >= '0' && c <= '9') || c == ' ')
                config->device_name[out++] = (char)c;
        }
        while (out > 0 && config->device_name[out - 1] == ' ') out--;
        config->device_name[out] = '\0';
        serial_writeln("OK");
        return;
    }

    // LED keys
    if (handle_led_set(config, key, val)) return;

    serial_writeln("ERR:unknown key");
}

//--------------------------------------------------------------------
// Pin scan
//--------------------------------------------------------------------

static bool gpio_is_scannable(int pin) {
    if (pin < GPIO_MIN || pin > GPIO_MAX) return false;
    if (pin == 23 || pin == 24 || pin == 25) return false;
    // Skip SPI LED pins if LEDs are enabled
    if (pin == LED_SPI_DI_PIN || pin == LED_SPI_SCK_PIN) return false;
    return true;
}

static void run_scan(void) {
    bool last_state[29] = {false};
    for (int i = GPIO_MIN; i <= GPIO_MAX; i++) {
        if (!gpio_is_scannable(i)) continue;
        gpio_init(i);
        gpio_set_dir(i, GPIO_IN);
        gpio_pull_up(i);
    }
    sleep_ms(10);
    for (int i = GPIO_MIN; i <= GPIO_MAX; i++) {
        if (gpio_is_scannable(i))
            last_state[i] = !gpio_get(i);
    }

    serial_writeln("OK");

    char cmd_buf[CMD_BUF_SIZE];
    int cmd_pos = 0;
    uint32_t last_scan_ms = 0;

    while (true) {
        tud_task();

        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                cmd_buf[cmd_pos] = '\0';
                for (int i = cmd_pos - 1; i >= 0 && cmd_buf[i] <= ' '; i--)
                    cmd_buf[i] = '\0';
                if (strcmp(cmd_buf, "STOP") == 0) {
                    serial_writeln("OK");
                    return;
                }
                cmd_pos = 0;
            } else if (cmd_pos < CMD_BUF_SIZE - 1) {
                cmd_buf[cmd_pos++] = c;
            }
        }

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        if ((now_ms - last_scan_ms) >= SCAN_REPEAT_MS) {
            last_scan_ms = now_ms;
            char buf[32];
            for (int i = GPIO_MIN; i <= GPIO_MAX; i++) {
                if (!gpio_is_scannable(i)) continue;
                bool cur = !gpio_get(i);
                if (cur && !last_state[i]) {
                    snprintf(buf, sizeof(buf), "PIN:%d", i);
                    serial_writeln(buf);
                }
                last_state[i] = cur;
            }
        }
        sleep_ms(1);
    }
}

//--------------------------------------------------------------------
// Main config mode loop
//--------------------------------------------------------------------

void drum_config_mode_main(drum_config_t *config) {
    char cmd_buf[CMD_BUF_SIZE];
    int cmd_pos = 0;
    bool was_connected = false;
    uint32_t disconnect_time_ms = 0;
    uint32_t start_time_ms = to_ms_since_boot(get_absolute_time());

    while (true) {
        tud_task();
        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        bool connected = tud_cdc_connected();

        if (!was_connected && !connected) {
            if ((now_ms - start_time_ms) > CONNECT_TIMEOUT_MS) {
                watchdog_reboot(0, 0, 10);
                while (1) { tight_loop_contents(); }
            }
        }
        if (was_connected && !connected) {
            if (disconnect_time_ms == 0) disconnect_time_ms = now_ms;
            else if ((now_ms - disconnect_time_ms) > DISCONNECT_TIMEOUT_MS) {
                watchdog_reboot(0, 0, 10);
                while (1) { tight_loop_contents(); }
            }
        }
        if (connected) { was_connected = true; disconnect_time_ms = 0; }

        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                if (cmd_pos == 0) continue;
                cmd_buf[cmd_pos] = '\0';
                cmd_pos = 0;
                for (int i = strlen(cmd_buf) - 1; i >= 0 && cmd_buf[i] <= ' '; i--)
                    cmd_buf[i] = '\0';

                if (strcmp(cmd_buf, "PING") == 0)
                    serial_writeln("PONG");
                else if (strcmp(cmd_buf, "GET_FW_DATE") == 0)
                    serial_writeln("FW_DATE:" BUILD_DATE_STR);
                else if (strcmp(cmd_buf, "GET_CONFIG") == 0)
                    send_config(config);
                else if (strncmp(cmd_buf, "SET:", 4) == 0)
                    handle_set(config, cmd_buf + 4);
                else if (strcmp(cmd_buf, "SAVE") == 0) {
                    config_update_checksum(config);
                    config_save(config);
                    serial_writeln("OK");
                }
                else if (strcmp(cmd_buf, "DEFAULTS") == 0) {
                    config_set_defaults(config);
                    serial_writeln("OK");
                }
                else if (strcmp(cmd_buf, "SCAN") == 0)
                    run_scan();
                else if (strncmp(cmd_buf, "LED_FLASH:", 10) == 0) {
                    int idx = atoi(cmd_buf + 10);
                    if (idx >= 0 && idx < MAX_LEDS && idx < config->leds.count) {
                        serial_writeln("OK");
                        led_config_t tmp;
                        memcpy(&tmp, &config->leds, sizeof(led_config_t));
                        apa102_flash_led(&tmp, (uint8_t)idx, 3);
                    } else {
                        serial_writeln("ERR:led index");
                    }
                }
                else if (strncmp(cmd_buf, "LED_SOLID:", 10) == 0) {
                    int idx = atoi(cmd_buf + 10);
                    if (idx >= 0 && idx < MAX_LEDS && idx < config->leds.count) {
                        serial_writeln("OK");
                        apa102_init();
                        led_config_t tmp;
                        memcpy(&tmp, &config->leds, sizeof(led_config_t));
                        uint8_t br[MAX_LEDS];
                        memset(br, 0, sizeof(br));
                        br[idx] = 31;
                        apa102_update(&tmp, br);
                    } else {
                        serial_writeln("ERR:led index");
                    }
                }
                else if (strcmp(cmd_buf, "LED_OFF") == 0) {
                    apa102_init();
                    led_config_t tmp;
                    memcpy(&tmp, &config->leds, sizeof(led_config_t));
                    apa102_all_off(&tmp);
                    serial_writeln("OK");
                }
                else if (strcmp(cmd_buf, "REBOOT") == 0) {
                    serial_writeln("OK"); sleep_ms(100);
                    watchdog_reboot(0, 0, 10);
                    while (1) { tight_loop_contents(); }
                }
                else if (strcmp(cmd_buf, "BOOTSEL") == 0) {
                    serial_writeln("OK"); sleep_ms(100);
                    reset_usb_boot(0, 0);
                    while (1) { tight_loop_contents(); }
                }
                else
                    serial_writeln("ERR:unknown command");
            } else if (cmd_pos < CMD_BUF_SIZE - 1) {
                cmd_buf[cmd_pos++] = c;
            }
        }
        sleep_ms(1);
    }
}
