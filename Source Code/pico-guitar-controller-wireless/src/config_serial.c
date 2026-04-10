/*
 * config_serial.c - CDC serial config mode
 *
 * Commands: PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS,
 *           SCAN, STOP, REBOOT, BOOTSEL, ROTATE_BLE_IDENTITY,
 *           MONITOR_ADC:pin, MONITOR_I2C, STOP
 *
 * LED keys:
 *   led_enabled, led_count, led_brightness
 *   led_color_N=RRGGBB     (hex, per-LED)
 *   led_map_N=XXXX          (hex 16-bit mask, per-input)
 *   led_active_N=V           (0-31, per-input)
 *
 * I2C keys:
 *   tilt_mode=digital|analog|i2c
 *   i2c_sda, i2c_scl, adxl345_axis, i2c_model
 *
 * MONITOR commands stream MVAL:value lines at ~20Hz until STOP.
 */

#include "config_serial.h"
#include "guitar_config.h"
#include "ble_identity_storage.h"
// apa102_leds.h is included transitively via guitar_config.h — do not
// include it directly here to avoid confusion about include ordering.
#include "adxl345.h"
#include "lis3dh.h"
#include "tusb.h"
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/adc.h"
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

// Adaptive ADC detection: baseline noise + significant delta
#define ADC_NOISE_SAMPLES     16     // Samples to measure noise floor
#define ADC_NOISE_MARGIN      3      // Multiplier over noise for detection
#define ADC_MIN_THRESHOLD     30     // Minimum absolute threshold — lowered from 150
                                     // so weak hall sensors (whammy range ~150 counts)
                                     // are detected with a light press (~20% movement)
#define ADC_DETECT_HYSTERESIS 2      // Hysteresis divisor for release

// Monitor streaming rate
#define MONITOR_INTERVAL_MS   50     // ~20 Hz

static bool gpio_is_scannable(int pin) {
    if (pin < GPIO_MIN || pin > GPIO_MAX) return false;
    // Pico W: GPIO 23, 24, 25 used by CYW43 WiFi/BT chip; 29 = VSYS ADC
    if (pin == 23 || pin == 24 || pin == 25 || pin == 29) return false;
    return true;
}

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
// Button/input name tables
//--------------------------------------------------------------------

static const char *button_names[BTN_IDX_COUNT] = {
    "green", "red", "yellow", "blue", "orange",
    "strum_up", "strum_down", "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "guide"
};

// Input names for LED mapping (14 buttons + tilt + whammy)
static const char *input_names[LED_INPUT_COUNT] = {
    "green", "red", "yellow", "blue", "orange",
    "strum_up", "strum_down", "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "guide", "tilt", "whammy"
};

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
// Mode name helpers
//--------------------------------------------------------------------

static const char *tilt_mode_str(uint8_t mode) {
    switch (mode) {
        case INPUT_MODE_ANALOG:       return "analog";
        case INPUT_MODE_I2C_ADXL345: return "i2c";
        case INPUT_MODE_I2C_LIS3DH:  return "i2c";  // both I2C modes report as "i2c"
        default:                      return "digital";
    }
}

static uint8_t parse_tilt_mode(const char *str) {
    if (strcmp(str, "analog") == 0) return INPUT_MODE_ANALOG;
    if (strcmp(str, "i2c") == 0)    return INPUT_MODE_I2C_ADXL345;  // model set separately
    return INPUT_MODE_DIGITAL;
}

static const char *whammy_mode_str(uint8_t mode) {
    return (mode == INPUT_MODE_ANALOG) ? "analog" : "digital";
}

//--------------------------------------------------------------------
// Config serialization — sends all config including LED + I2C data
//--------------------------------------------------------------------

static void send_config(const guitar_config_t *config) {
    char buf[768];
    int pos;

    serial_writeln("DEVTYPE:" DEVICE_TYPE);

    // First line: button/axis/I2C config
    pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "CFG:");
    for (int i = 0; i < BTN_IDX_COUNT; i++)
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%s=%d,",
                        button_names[i], (int)config->pin_buttons[i]);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "tilt_mode=%s,",
                    tilt_mode_str(config->tilt_mode));
    // Always send both tilt pins so configurator can remember them
    // Send the pin appropriate for the current mode.
    // For I2C mode we report pin_tilt_digital (fallback if mode is switched back),
    // and the i2c_sda / i2c_scl fields below carry the real I2C pin info.
    {
        int tilt_pin_val;
        if (config->tilt_mode == INPUT_MODE_ANALOG)
            tilt_pin_val = (int)config->pin_tilt_analog;
        else if (config->tilt_mode == INPUT_MODE_I2C_ADXL345 ||
                 config->tilt_mode == INPUT_MODE_I2C_LIS3DH)
            tilt_pin_val = (int)config->pin_i2c_sda;  // report SDA as the primary pin
        else
            tilt_pin_val = (int)config->pin_tilt_digital;
        pos += snprintf(buf + pos, sizeof(buf) - pos, "tilt_pin=%d,", tilt_pin_val);
    }
    pos += snprintf(buf + pos, sizeof(buf) - pos, "whammy_mode=%s,",
                    whammy_mode_str(config->whammy_mode));
    pos += snprintf(buf + pos, sizeof(buf) - pos, "whammy_pin=%d,",
                    config->whammy_mode == INPUT_MODE_ANALOG
                        ? (int)config->pin_whammy_analog
                        : (int)config->pin_whammy_digital);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "debounce=%d,",
                    (int)config->debounce_ms);
    // I2C config
    pos += snprintf(buf + pos, sizeof(buf) - pos, "i2c_sda=%d,",
                    (int)config->pin_i2c_sda);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "i2c_scl=%d,",
                    (int)config->pin_i2c_scl);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "adxl345_axis=%d,",
                    (int)config->adxl345_axis);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "i2c_model=%d,",
                    (int)config->i2c_model);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "tilt_min=%u,",
                    (unsigned)config->tilt_min);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "tilt_max=%u,",
                    (unsigned)config->tilt_max);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "whammy_min=%u,",
                    (unsigned)config->whammy_min);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "whammy_max=%u,",
                    (unsigned)config->whammy_max);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "tilt_invert=%d,",
                    (int)config->tilt_invert);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "whammy_invert=%d,",
                    (int)config->whammy_invert);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_pin_x=%d,",
                    (int)config->pin_joy_x);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_pin_y=%d,",
                    (int)config->pin_joy_y);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_pin_sw=%d,",
                    (int)config->pin_joy_sw);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_whammy_axis=%d,",
                    (int)config->joy_whammy_axis);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_dpad_x=%d,",
                    (int)config->joy_dpad_x);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_dpad_y=%d,",
                    (int)config->joy_dpad_y);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_dpad_x_invert=%d,",
                    (int)config->joy_dpad_x_invert);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_dpad_y_invert=%d,",
                    (int)config->joy_dpad_y_invert);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "joy_deadzone=%u,",
                    (unsigned)config->joy_deadzone);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "device_name=%s,",
                    config->device_name);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "ema_alpha=%u,",
                    (unsigned)config->ema_alpha);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "sync_pin=%d,",
                    (int)config->sync_pin);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "wireless_default_mode=%u,",
                    (unsigned)config->wireless_default_mode);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "start_hold_enabled=%d,",
                    (int)config->start_hold_enabled);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "start_hold_ms=%u",
                    (unsigned)config->start_hold_ms);
    serial_writeln(buf);

    // Second line: LED basic config
    pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "LED:");
    pos += snprintf(buf + pos, sizeof(buf) - pos, "enabled=%d,",
                    config->leds.enabled);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "count=%d,",
                    config->leds.count);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "brightness=%d,",
                    config->leds.base_brightness);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "loop_enabled=%d,",
                    config->leds.loop_enabled);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "loop_start=%d,",
                    config->leds.loop_start);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "loop_end=%d,",
                    config->leds.loop_end);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "breathe_enabled=%d,",
                    config->leds.breathe_enabled);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "breathe_start=%d,",
                    config->leds.breathe_start);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "breathe_end=%d,",
                    config->leds.breathe_end);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "breathe_min=%d,",
                    config->leds.breathe_min_bright);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "breathe_max=%d,",
                    config->leds.breathe_max_bright);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "wave_enabled=%d,",
                    config->leds.wave_enabled);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "wave_origin=%d,",
                    config->leds.wave_origin);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "loop_speed=%d,",    config->leds.loop_speed_ms);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "breathe_speed=%d,", config->leds.breathe_speed_ms);
    pos += snprintf(buf + pos, sizeof(buf) - pos, "wave_speed=%d",     config->leds.wave_speed_ms);
    serial_writeln(buf);

    // Third line: LED colors (hex RRGGBB for each)
    pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "LED_COLORS:");
    for (int i = 0; i < MAX_LEDS; i++) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%02X%02X%02X",
                        config->leds.colors[i].r,
                        config->leds.colors[i].g,
                        config->leds.colors[i].b);
        if (i < MAX_LEDS - 1)
            pos += snprintf(buf + pos, sizeof(buf) - pos, ",");
    }
    serial_writeln(buf);

    // Fourth line: LED mappings (per-input: hex mask + active brightness)
    pos = 0;
    pos += snprintf(buf + pos, sizeof(buf) - pos, "LED_MAP:");
    for (int i = 0; i < LED_INPUT_COUNT; i++) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, "%s=%04X:%d",
                        input_names[i],
                        config->leds.led_map[i],
                        config->leds.active_brightness[i]);
        if (i < LED_INPUT_COUNT - 1)
            pos += snprintf(buf + pos, sizeof(buf) - pos, ",");
    }
    serial_writeln(buf);
}

//--------------------------------------------------------------------
// SET command handler
//--------------------------------------------------------------------

static bool handle_set(guitar_config_t *config, const char *kv_str) {
    char key[40] = {0}, val[40] = {0};
    const char *eq = strchr(kv_str, '=');
    if (!eq) { serial_writeln("ERR:missing ="); return false; }

    size_t key_len = eq - kv_str;
    if (key_len >= sizeof(key)) key_len = sizeof(key) - 1;
    memcpy(key, kv_str, key_len);
    strncpy(val, eq + 1, sizeof(val) - 1);
    for (int i = strlen(val) - 1; i >= 0 && (val[i] <= ' '); i--) val[i] = '\0';

    // Button pins
    for (int i = 0; i < BTN_IDX_COUNT; i++) {
        if (strcmp(key, button_names[i]) == 0) {
            int pin = atoi(val);
            if (pin < -1 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
            config->pin_buttons[i] = (int8_t)pin;
            serial_writeln("OK"); return true;
        }
    }

    // Tilt
    if (strcmp(key, "tilt_mode") == 0) {
        uint8_t mode = parse_tilt_mode(val);
        // If the configurator sent "i2c", resolve to the correct I2C mode
        // based on the current i2c_model field so init_i2c_tilt() and
        // build_report() pick the right driver without ambiguity.
        if (mode == INPUT_MODE_I2C_ADXL345 && config->i2c_model == I2C_MODEL_LIS3DH)
            mode = INPUT_MODE_I2C_LIS3DH;
        config->tilt_mode = mode;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "tilt_pin") == 0) {
        int pin = atoi(val);
        if (pin < -1 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
        if (config->tilt_mode == INPUT_MODE_ANALOG)
            config->pin_tilt_analog = (int8_t)pin;
        else
            config->pin_tilt_digital = (int8_t)pin;
        serial_writeln("OK"); return true;
    }

    // Whammy
    if (strcmp(key, "whammy_mode") == 0) {
        config->whammy_mode = (strcmp(val, "analog") == 0)
                              ? INPUT_MODE_ANALOG : INPUT_MODE_DIGITAL;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "whammy_pin") == 0) {
        int pin = atoi(val);
        if (pin < -1 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
        if (config->whammy_mode == INPUT_MODE_ANALOG)
            config->pin_whammy_analog = (int8_t)pin;
        else
            config->pin_whammy_digital = (int8_t)pin;
        serial_writeln("OK"); return true;
    }

    // Debounce
    if (strcmp(key, "debounce") == 0) {
        int ms = atoi(val);
        if (ms < 0 || ms > 255) { serial_writeln("ERR:0-255"); return false; }
        config->debounce_ms = (uint8_t)ms;
        serial_writeln("OK"); return true;
    }

    // ── I2C settings ──
    if (strcmp(key, "i2c_sda") == 0) {
        int pin = atoi(val);
        if (pin < 0 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
        config->pin_i2c_sda = (int8_t)pin;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "i2c_scl") == 0) {
        int pin = atoi(val);
        if (pin < 0 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
        config->pin_i2c_scl = (int8_t)pin;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "adxl345_axis") == 0) {
        int a = atoi(val);
        if (a < 0 || a > 2) { serial_writeln("ERR:0-2"); return false; }
        config->adxl345_axis = (uint8_t)a;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "i2c_model") == 0) {
        int m = atoi(val);
        if (m < 0 || m > 1) { serial_writeln("ERR:0=ADXL345 1=LIS3DH"); return false; }
        config->i2c_model = (uint8_t)m;
        // Keep tilt_mode in sync — resolve to the matching INPUT_MODE_I2C_*
        // so that init_i2c_tilt() and build_report() use the correct driver.
        if (config->tilt_mode == INPUT_MODE_I2C_ADXL345 ||
            config->tilt_mode == INPUT_MODE_I2C_LIS3DH) {
            config->tilt_mode = (m == I2C_MODEL_LIS3DH)
                ? INPUT_MODE_I2C_LIS3DH : INPUT_MODE_I2C_ADXL345;
        }
        serial_writeln("OK"); return true;
    }

    // ── LED settings ──

    if (strcmp(key, "led_enabled") == 0) {
        config->leds.enabled = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_count") == 0) {
        int c = atoi(val);
        if (c < 0 || c > MAX_LEDS) { serial_writeln("ERR:0-16"); return false; }
        config->leds.count = (uint8_t)c;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_brightness") == 0) {
        int b = atoi(val);
        if (b < 0 || b > 31) { serial_writeln("ERR:0-31"); return false; }
        config->leds.base_brightness = (uint8_t)b;
        serial_writeln("OK"); return true;
    }

    // led_color_N=RRGGBB
    if (strncmp(key, "led_color_", 10) == 0) {
        int idx = atoi(key + 10);
        if (idx < 0 || idx >= MAX_LEDS) { serial_writeln("ERR:led index"); return false; }
        if (strlen(val) != 6) { serial_writeln("ERR:need RRGGBB"); return false; }
        config->leds.colors[idx].r = hex_byte(val);
        config->leds.colors[idx].g = hex_byte(val + 2);
        config->leds.colors[idx].b = hex_byte(val + 4);
        serial_writeln("OK"); return true;
    }

    // led_map_N=XXXX  (hex 16-bit mask)
    if (strncmp(key, "led_map_", 8) == 0) {
        int idx = atoi(key + 8);
        if (idx < 0 || idx >= LED_INPUT_COUNT) { serial_writeln("ERR:input index"); return false; }
        unsigned long mask = strtoul(val, NULL, 16);
        config->leds.led_map[idx] = (uint16_t)(mask & 0xFFFF);
        serial_writeln("OK"); return true;
    }

    // led_active_N=V  (0-31)
    if (strncmp(key, "led_active_", 11) == 0) {
        int idx = atoi(key + 11);
        if (idx < 0 || idx >= LED_INPUT_COUNT) { serial_writeln("ERR:input index"); return false; }
        int b = atoi(val);
        if (b < 0 || b > 31) { serial_writeln("ERR:0-31"); return false; }
        config->leds.active_brightness[idx] = (uint8_t)b;
        serial_writeln("OK"); return true;
    }

    // LED loop settings
    if (strcmp(key, "led_loop_enabled") == 0) {
        config->leds.loop_enabled = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_loop_start") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:0-15"); return false; }
        config->leds.loop_start = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_loop_end") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:0-15"); return false; }
        config->leds.loop_end = (uint8_t)v;
        serial_writeln("OK"); return true;
    }

    // LED breathe settings
    if (strcmp(key, "led_breathe_enabled") == 0) {
        config->leds.breathe_enabled = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_start") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:0-15"); return false; }
        config->leds.breathe_start = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_end") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:0-15"); return false; }
        config->leds.breathe_end = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_min") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 31) { serial_writeln("ERR:0-31"); return false; }
        config->leds.breathe_min_bright = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_max") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 31) { serial_writeln("ERR:0-31"); return false; }
        config->leds.breathe_max_bright = (uint8_t)v;
        serial_writeln("OK"); return true;
    }

    // LED wave settings
    if (strcmp(key, "led_wave_enabled") == 0) {
        config->leds.wave_enabled = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_wave_origin") == 0) {
        int v = atoi(val);
        if (v < 0 || v >= MAX_LEDS) { serial_writeln("ERR:0-15"); return false; }
        config->leds.wave_origin = (uint8_t)v;
        serial_writeln("OK"); return true;
    }

    // LED effect speeds
    if (strcmp(key, "led_loop_speed") == 0) {
        int v = atoi(val);
        if (v < 100 || v > 9999) { serial_writeln("ERR:100-9999"); return false; }
        config->leds.loop_speed_ms = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_breathe_speed") == 0) {
        int v = atoi(val);
        if (v < 100 || v > 9999) { serial_writeln("ERR:100-9999"); return false; }
        config->leds.breathe_speed_ms = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "led_wave_speed") == 0) {
        int v = atoi(val);
        if (v < 100 || v > 9999) { serial_writeln("ERR:100-9999"); return false; }
        config->leds.wave_speed_ms = (uint16_t)v;
        serial_writeln("OK"); return true;
    }

    // ── Analog sensitivity ──
    if (strcmp(key, "tilt_min") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 4095) { serial_writeln("ERR:0-4095"); return false; }
        config->tilt_min = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "tilt_max") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 4095) { serial_writeln("ERR:0-4095"); return false; }
        config->tilt_max = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "whammy_min") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 4095) { serial_writeln("ERR:0-4095"); return false; }
        config->whammy_min = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "whammy_max") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 4095) { serial_writeln("ERR:0-4095"); return false; }
        config->whammy_max = (uint16_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "tilt_invert") == 0) {
        config->tilt_invert = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "whammy_invert") == 0) {
        config->whammy_invert = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }

    // ── Joystick settings ──
    if (strcmp(key, "joy_pin_x") == 0) {
        int pin = atoi(val);
        if (pin < -1 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
        config->pin_joy_x = (int8_t)pin;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "joy_pin_y") == 0) {
        int pin = atoi(val);
        if (pin < -1 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
        config->pin_joy_y = (int8_t)pin;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "joy_pin_sw") == 0) {
        int pin = atoi(val);
        if (pin < -1 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
        config->pin_joy_sw = (int8_t)pin;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "joy_whammy_axis") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 2) { serial_writeln("ERR:0-2"); return false; }
        config->joy_whammy_axis = (uint8_t)v;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "joy_dpad_x") == 0) {
        config->joy_dpad_x = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "joy_dpad_y") == 0) {
        config->joy_dpad_y = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "joy_dpad_x_invert") == 0) {
        config->joy_dpad_x_invert = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "joy_dpad_y_invert") == 0) {
        config->joy_dpad_y_invert = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "joy_deadzone") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 4095) { serial_writeln("ERR:0-4095"); return false; }
        config->joy_deadzone = (uint16_t)v;
        serial_writeln("OK"); return true;
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
        serial_writeln("OK"); return true;
    }

    // Analog smoothing EMA alpha
    if (strcmp(key, "ema_alpha") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 255) { serial_writeln("ERR:0-255"); return false; }
        config->ema_alpha = (uint8_t)v;
        serial_writeln("OK"); return true;
    }

    // Dongle sync button pin
    if (strcmp(key, "sync_pin") == 0) {
        int pin = atoi(val);
        if (pin < -1 || pin > 28) { serial_writeln("ERR:pin range"); return false; }
        config->sync_pin = (int8_t)pin;
        serial_writeln("OK"); return true;
    }

    // Wireless default mode: 0 = Dongle, 1 = Bluetooth HID
    if (strcmp(key, "wireless_default_mode") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 1) { serial_writeln("ERR:0 or 1"); return false; }
        config->wireless_default_mode = (uint8_t)v;
        serial_writeln("OK"); return true;
    }

    // START button hold-to-activate
    if (strcmp(key, "start_hold_enabled") == 0) {
        config->start_hold_enabled = (atoi(val) != 0) ? 1 : 0;
        serial_writeln("OK"); return true;
    }
    if (strcmp(key, "start_hold_ms") == 0) {
        int v = atoi(val);
        if (v < 0 || v > 5000) { serial_writeln("ERR:0-5000"); return false; }
        config->start_hold_ms = (uint16_t)v;
        serial_writeln("OK"); return true;
    }

    serial_writeln("ERR:unknown key");
    return false;
}

//--------------------------------------------------------------------
// Adaptive ADC noise measurement
//--------------------------------------------------------------------

typedef struct {
    uint16_t baseline;
    uint16_t noise;       // Peak-to-peak noise amplitude
    uint16_t threshold;   // Detection threshold (noise * margin, clamped to min)
} adc_channel_state_t;

static void measure_adc_noise(adc_channel_state_t *ch_state, int channel) {
    adc_select_input(channel);
    sleep_ms(5);

    uint32_t sum = 0;
    uint16_t min_val = 4095, max_val = 0;

    for (int s = 0; s < ADC_NOISE_SAMPLES; s++) {
        uint16_t val = adc_read();
        sum += val;
        if (val < min_val) min_val = val;
        if (val > max_val) max_val = val;
        sleep_us(500);
    }

    ch_state->baseline = (uint16_t)(sum / ADC_NOISE_SAMPLES);
    ch_state->noise = max_val - min_val;

    // Threshold = noise * margin, but at least ADC_MIN_THRESHOLD
    uint16_t computed = ch_state->noise * ADC_NOISE_MARGIN;
    ch_state->threshold = (computed > ADC_MIN_THRESHOLD)
                          ? computed : ADC_MIN_THRESHOLD;
}

//--------------------------------------------------------------------
// Pin scanning (digital + ADC + I2C device detection)
//
// Improved: adaptive noise floor for ADC, I2C probing for ADXL345
//--------------------------------------------------------------------

static void run_scan(guitar_config_t *config) {
    // Init digital GPIO pins for scanning
    for (int pin = GPIO_MIN; pin <= GPIO_MAX; pin++) {
        if (!gpio_is_scannable(pin)) continue;
        if (pin >= 26 && pin <= 28) continue;
        gpio_init(pin);
        gpio_set_dir(pin, GPIO_IN);
        gpio_pull_up(pin);
    }

    // Init ADC channels
    adc_init();
    for (int ch = 0; ch < 3; ch++) adc_gpio_init(26 + ch);
    sleep_ms(20);

    // Measure noise floor for each ADC channel (adaptive threshold)
    adc_channel_state_t adc_state[3];
    for (int ch = 0; ch < 3; ch++) {
        measure_adc_noise(&adc_state[ch], ch);
    }

    // Probe I2C for supported accelerometers
    bool adxl345_found = adxl345_detect(config->pin_i2c_sda, config->pin_i2c_scl);
    bool lis3dh_found  = false;
    if (!adxl345_found)
        lis3dh_found = lis3dh_detect(config->pin_i2c_sda, config->pin_i2c_scl);

    uint32_t last_report_ms[GPIO_MAX + 1];
    bool pin_was_pressed[GPIO_MAX + 1];
    memset(last_report_ms, 0, sizeof(last_report_ms));
    memset(pin_was_pressed, 0, sizeof(pin_was_pressed));

    // Report I2C detection immediately
    if (adxl345_found) {
        serial_writeln("I2C:ADXL345");
    } else if (lis3dh_found) {
        serial_writeln("I2C:LIS3DH");
    }

    serial_writeln("OK");

    char cmd_buf[CMD_BUF_SIZE];
    int cmd_pos = 0;

    while (true) {
        tud_task();
        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                cmd_buf[cmd_pos] = '\0';
                for (int i = cmd_pos - 1; i >= 0 && cmd_buf[i] <= ' '; i--) cmd_buf[i] = '\0';
                if (strcmp(cmd_buf, "STOP") == 0) { serial_writeln("OK"); return; }
                cmd_pos = 0;
            } else if (cmd_pos < CMD_BUF_SIZE - 1) { cmd_buf[cmd_pos++] = c; }
        }

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());

        // Digital pin scanning (GP0-GP22)
        for (int pin = GPIO_MIN; pin <= 22; pin++) {
            if (!gpio_is_scannable(pin)) continue;
            bool pressed = !gpio_get(pin);
            if (pressed) {
                if ((now_ms - last_report_ms[pin]) >= SCAN_REPEAT_MS) {
                    char buf[16]; snprintf(buf, sizeof(buf), "PIN:%d", pin);
                    serial_writeln(buf); last_report_ms[pin] = now_ms;
                }
            }
            pin_was_pressed[pin] = pressed;
        }

        // Analog pin scanning (GP26-28) with adaptive threshold
        for (int ch = 0; ch < 3; ch++) {
            int pin = 26 + ch;
            adc_select_input(ch);
            uint16_t val = adc_read();
            int diff = (int)val - (int)adc_state[ch].baseline;
            if (diff < 0) diff = -diff;

            if (diff > adc_state[ch].threshold && !pin_was_pressed[pin]) {
                if ((now_ms - last_report_ms[pin]) >= SCAN_REPEAT_MS) {
                    // Report as APIN (analog pin) with the current value
                    char buf[32];
                    snprintf(buf, sizeof(buf), "APIN:%d:%u", pin, val);
                    serial_writeln(buf);
                    last_report_ms[pin] = now_ms;
                }
                pin_was_pressed[pin] = true;
            } else if (diff <= adc_state[ch].threshold / ADC_DETECT_HYSTERESIS) {
                pin_was_pressed[pin] = false;
            }
        }
        sleep_ms(5);
    }
}

//--------------------------------------------------------------------
// MONITOR — stream live sensor values for the configurator bar graph
//--------------------------------------------------------------------

static void run_monitor_adc(int pin) {
    if (pin < 26 || pin > 28) {
        serial_writeln("ERR:invalid ADC pin");
        return;
    }

    int ch = pin - 26;
    adc_init();
    adc_gpio_init(pin);
    sleep_ms(10);

    serial_writeln("OK");

    char cmd_buf[CMD_BUF_SIZE];
    int cmd_pos = 0;
    uint32_t last_send_ms = 0;

    while (true) {
        tud_task();

        // Check for STOP command
        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                cmd_buf[cmd_pos] = '\0';
                for (int i = cmd_pos - 1; i >= 0 && cmd_buf[i] <= ' '; i--) cmd_buf[i] = '\0';
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
        if ((now_ms - last_send_ms) >= MONITOR_INTERVAL_MS) {
            last_send_ms = now_ms;
            adc_select_input(ch);
            uint16_t val = adc_read();
            char buf[20];
            snprintf(buf, sizeof(buf), "MVAL:%u", val);
            serial_writeln(buf);
        }

        sleep_ms(1);
    }
}

// axis_filter: 0=X, 1=Y, 2=Z for single-axis mode; -1 = send all three axes
// (all-three mode is used by the debug console quick-button MONITOR_I2C with no arg)
static void run_monitor_i2c(guitar_config_t *config, int axis_filter) {
    bool use_lis3dh = (config->i2c_model == I2C_MODEL_LIS3DH);

    if (use_lis3dh) {
        if (!lis3dh_init(config->pin_i2c_sda, config->pin_i2c_scl)) {
            serial_writeln("ERR:LIS3DH not found");
            return;
        }
    } else {
        if (!adxl345_init(config->pin_i2c_sda, config->pin_i2c_scl)) {
            serial_writeln("ERR:ADXL345 not found");
            return;
        }
    }

    serial_writeln("OK");

    char cmd_buf[CMD_BUF_SIZE];
    int cmd_pos = 0;
    uint32_t last_send_ms = 0;

    // Single-axis mode: 50 Hz (20 ms).  All-axes debug mode keeps 20 Hz (50 ms)
    // so the debug console isn't flooded.
    uint32_t interval_ms = (axis_filter >= 0) ? 20 : 50;

    while (true) {
        tud_task();

        // Check for STOP command
        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                cmd_buf[cmd_pos] = '\0';
                for (int i = cmd_pos - 1; i >= 0 && cmd_buf[i] <= ' '; i--) cmd_buf[i] = '\0';
                if (strcmp(cmd_buf, "STOP") == 0) {
                    if (use_lis3dh) lis3dh_deinit();
                    else            adxl345_deinit();
                    serial_writeln("OK");
                    return;
                }
                cmd_pos = 0;
            } else if (cmd_pos < CMD_BUF_SIZE - 1) {
                cmd_buf[cmd_pos++] = c;
            }
        }

        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        if ((now_ms - last_send_ms) >= interval_ms) {
            last_send_ms = now_ms;

            int16_t x, y, z;
            bool read_ok = use_lis3dh
                ? lis3dh_read_xyz(&x, &y, &z)
                : adxl345_read_xyz(&x, &y, &z);

            if (read_ok) {
                char buf[32];

                if (axis_filter >= 0) {
                    // Single-axis mode: read only the requested axis and emit one MVAL: line.
                    // This minimises serial traffic and gives the lowest possible latency.
                    uint16_t val;
                    if (axis_filter == 0)
                        val = use_lis3dh ? lis3dh_to_adc_scale(x) : adxl345_to_adc_scale(x);
                    else if (axis_filter == 1)
                        val = use_lis3dh ? lis3dh_to_adc_scale(y) : adxl345_to_adc_scale(y);
                    else
                        val = use_lis3dh ? lis3dh_to_adc_scale(z) : adxl345_to_adc_scale(z);
                    snprintf(buf, sizeof(buf), "MVAL:%u", val);
                    serial_writeln(buf);
                } else {
                    // All-axes debug mode: emit MVAL_X/Y/Z for the debug console.
                    uint16_t sx = use_lis3dh ? lis3dh_to_adc_scale(x) : adxl345_to_adc_scale(x);
                    uint16_t sy = use_lis3dh ? lis3dh_to_adc_scale(y) : adxl345_to_adc_scale(y);
                    uint16_t sz = use_lis3dh ? lis3dh_to_adc_scale(z) : adxl345_to_adc_scale(z);
                    snprintf(buf, sizeof(buf), "MVAL_X:%u", sx); serial_writeln(buf);
                    snprintf(buf, sizeof(buf), "MVAL_Y:%u", sy); serial_writeln(buf);
                    snprintf(buf, sizeof(buf), "MVAL_Z:%u", sz); serial_writeln(buf);
                }
            } else {
                serial_writeln("ERR:I2C read failed");
            }
        }

        sleep_ms(1);
    }
}

// Monitor a digital pin — report 0 or 4095 (for consistent bar graph)
static void run_monitor_digital(int pin) {
    if (pin < 0 || pin > 28) {
        serial_writeln("ERR:invalid pin");
        return;
    }

    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_pull_up(pin);
    sleep_ms(10);

    serial_writeln("OK");

    char cmd_buf[CMD_BUF_SIZE];
    int cmd_pos = 0;
    uint32_t last_send_ms = 0;

    while (true) {
        tud_task();

        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                cmd_buf[cmd_pos] = '\0';
                for (int i = cmd_pos - 1; i >= 0 && cmd_buf[i] <= ' '; i--) cmd_buf[i] = '\0';
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
        if ((now_ms - last_send_ms) >= MONITOR_INTERVAL_MS) {
            last_send_ms = now_ms;
            bool pressed = !gpio_get(pin);
            char buf[16];
            snprintf(buf, sizeof(buf), "MVAL:%u", pressed ? 4095 : 0);
            serial_writeln(buf);
        }

        sleep_ms(1);
    }
}

//--------------------------------------------------------------------
// Main config mode loop
//--------------------------------------------------------------------

void config_mode_main(guitar_config_t *config) {
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
                else if (strcmp(cmd_buf, "ROTATE_BLE_IDENTITY") == 0) {
                    uint8_t new_addr[BLE_IDENTITY_ADDR_LEN];
                    ble_identity_generate(new_addr);
                    ble_identity_save(new_addr);
                    serial_writeln("OK");
                    sleep_ms(100);
                    watchdog_reboot(0, 0, 10);
                    while (1) { tight_loop_contents(); }
                }
                else if (strcmp(cmd_buf, "SCAN") == 0)
                    run_scan(config);

                // ── Monitor commands ──
                else if (strncmp(cmd_buf, "MONITOR_ADC:", 12) == 0) {
                    int pin = atoi(cmd_buf + 12);
                    run_monitor_adc(pin);
                }
                else if (strcmp(cmd_buf, "MONITOR_I2C") == 0) {
                    // No axis arg — debug console mode: streams all 3 axes at 20 Hz
                    run_monitor_i2c(config, -1);
                }
                else if (strncmp(cmd_buf, "MONITOR_I2C:", 12) == 0) {
                    // Single-axis mode: MONITOR_I2C:0/1/2 — streams only MVAL: at 50 Hz
                    int axis = atoi(cmd_buf + 12);
                    if (axis < 0 || axis > 2) axis = 0;
                    run_monitor_i2c(config, axis);
                }
                else if (strncmp(cmd_buf, "MONITOR_DIG:", 12) == 0) {
                    int pin = atoi(cmd_buf + 12);
                    run_monitor_digital(pin);
                }

                // ── LED commands ──
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
