/*
 * guitar_config.c - Flash-backed configuration storage (v7)
 *
 * v6: Added analog sensitivity (min/max) for tilt and whammy.
 * v7: Added LED loop (color rotation) fields.
 */

#include "guitar_config.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include <string.h>

#define FLASH_CONFIG_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR    ((const guitar_config_t *)(XIP_BASE + FLASH_CONFIG_OFFSET))

static uint32_t _calc_checksum(const guitar_config_t *config) {
    const uint8_t *data = (const uint8_t *)config;
    size_t len = offsetof(guitar_config_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xDEADBEEF;
}

void config_set_defaults(guitar_config_t *config) {
    memset(config, 0, sizeof(guitar_config_t));
    config->magic   = CONFIG_MAGIC;
    config->version = CONFIG_VERSION;

    config->pin_buttons[BTN_IDX_GREEN]      = 0;
    config->pin_buttons[BTN_IDX_RED]        = 1;
    config->pin_buttons[BTN_IDX_YELLOW]     = 2;
    config->pin_buttons[BTN_IDX_BLUE]       = 3;
    config->pin_buttons[BTN_IDX_ORANGE]     = 4;
    config->pin_buttons[BTN_IDX_STRUM_UP]   = 5;
    config->pin_buttons[BTN_IDX_STRUM_DOWN] = 6;
    config->pin_buttons[BTN_IDX_START]      = 7;
    config->pin_buttons[BTN_IDX_SELECT]     = 8;
    config->pin_buttons[BTN_IDX_DPAD_UP]    = -1;
    config->pin_buttons[BTN_IDX_DPAD_DOWN]  = -1;
    config->pin_buttons[BTN_IDX_DPAD_LEFT]  = -1;
    config->pin_buttons[BTN_IDX_DPAD_RIGHT] = -1;
    config->pin_buttons[BTN_IDX_GUIDE]      = -1;

    config->tilt_mode           = INPUT_MODE_DIGITAL;
    config->pin_tilt_digital    = 9;
    config->pin_tilt_analog     = 27;

    config->whammy_mode          = INPUT_MODE_ANALOG;
    config->pin_whammy_digital   = -1;
    config->pin_whammy_analog    = 26;

    config->debounce_ms = 5;

    // I2C defaults — GP20/GP21 for I2C0 (avoids collision with default
    // button layout which uses GP0-GP8, and LED SPI which uses GP3/GP6).
    config->pin_i2c_sda   = 20;
    config->pin_i2c_scl   = 21;
    config->adxl345_axis  = 1;  // Y axis
    config->i2c_model     = I2C_MODEL_ADXL345;  // default to ADXL345

    // Sensitivity defaults: full ADC range (no scaling)
    config->tilt_min   = 0;
    config->tilt_max   = 4095;
    config->whammy_min = 0;
    config->whammy_max = 4095;

    config->tilt_invert   = 0;
    config->whammy_invert = 0;

    // Joystick defaults — disabled
    config->pin_joy_x        = -1;
    config->pin_joy_y        = -1;
    config->pin_joy_sw       = -1;
    config->joy_whammy_axis  = 0;   // 0=none, 1=X, 2=Y
    config->joy_dpad_x       = 0;   // 1 = map X axis to DPad L/R
    config->joy_dpad_y       = 0;   // 1 = map Y axis to DPad U/D
    config->joy_dpad_x_invert = 0;  // 1 = flip X DPad direction
    config->joy_dpad_y_invert = 0;  // 1 = flip Y DPad direction
    config->joy_deadzone     = 205; // ~5% of 4095

    // LEDs disabled by default
    config->leds.enabled = 0;
    config->leds.count = 0;
    config->leds.base_brightness = 5;   // Moderate idle glow

    // Default colors: green, red, yellow, blue, orange for first 5
    const uint8_t def_colors[][3] = {
        {0, 255, 0},     // green
        {255, 0, 0},     // red
        {255, 200, 0},   // yellow
        {0, 0, 255},     // blue
        {255, 100, 0},   // orange
    };
    for (int i = 0; i < 5 && i < MAX_LEDS; i++) {
        config->leds.colors[i].r = def_colors[i][0];
        config->leds.colors[i].g = def_colors[i][1];
        config->leds.colors[i].b = def_colors[i][2];
    }
    for (int i = 5; i < MAX_LEDS; i++) {
        config->leds.colors[i].r = 255;
        config->leds.colors[i].g = 255;
        config->leds.colors[i].b = 255;
    }

    // Default mapping: first 5 buttons → first 5 LEDs
    for (int i = 0; i < LED_INPUT_COUNT; i++) {
        config->leds.led_map[i] = 0;
        config->leds.active_brightness[i] = 25;  // Bright on press
    }
    // Green fret → LED 0, Red → LED 1, etc.
    for (int i = 0; i < 5 && i < MAX_LEDS; i++) {
        config->leds.led_map[i] = (1u << i);
    }

    // LED loop disabled by default
    config->leds.loop_enabled = 0;
    config->leds.loop_start   = 0;
    config->leds.loop_end     = 0;

    // Default device name
    strncpy(config->device_name, "Guitar Controller", DEVICE_NAME_MAX);
    config->device_name[DEVICE_NAME_MAX] = '\0';

    // Analog smoothing — default is slider level 4 → alpha 90 (responsive but stable)
    config->ema_alpha = 90;

    config->checksum = _calc_checksum(config);
}

bool config_is_valid(const guitar_config_t *config) {
    if (config->magic != CONFIG_MAGIC) return false;
    if (config->version != CONFIG_VERSION) return false;
    if (config->checksum != _calc_checksum(config)) return false;
    return true;
}

void config_load(guitar_config_t *config) {
    const guitar_config_t *flash_config = FLASH_CONFIG_ADDR;
    if (config_is_valid(flash_config)) {
        memcpy(config, flash_config, sizeof(guitar_config_t));
    } else {
        config_set_defaults(config);
    }
}

void config_save(const guitar_config_t *config) {
    uint8_t buf[FLASH_PAGE_SIZE];
    memset(buf, 0xFF, sizeof(buf));
    memcpy(buf, config, sizeof(guitar_config_t));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, buf, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void config_update_checksum(guitar_config_t *config) {
    config->magic    = CONFIG_MAGIC;
    config->version  = CONFIG_VERSION;
    config->checksum = _calc_checksum(config);
}
