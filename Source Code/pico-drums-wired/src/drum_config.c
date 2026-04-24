/*
 * drum_config.c - Flash-backed configuration storage for drum kit (v3)
 *
 * v2: Added APA102 LED strip support.
 * v3: Added D-pad (up/down/left/right) and foot pedal inputs.
 * v4: Added breathe+wave effects and per-effect LED speed fields.
 */

#include "drum_config.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include <string.h>

#define FLASH_CONFIG_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR    ((const drum_config_t *)(XIP_BASE + FLASH_CONFIG_OFFSET))

static uint32_t _calc_checksum(const drum_config_t *config) {
    const uint8_t *data = (const uint8_t *)config;
    size_t len = offsetof(drum_config_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xDEADBEEF;
}

void config_set_defaults(drum_config_t *config) {
    memset(config, 0, sizeof(drum_config_t));
    config->magic   = CONFIG_MAGIC;
    config->version = CONFIG_VERSION;

    // Default pin layout — user will remap these via configurator
    config->pin_buttons[BTN_IDX_RED_DRUM]    = 0;
    config->pin_buttons[BTN_IDX_YELLOW_DRUM] = 1;
    config->pin_buttons[BTN_IDX_BLUE_DRUM]   = 2;
    config->pin_buttons[BTN_IDX_GREEN_DRUM]  = 3;
    config->pin_buttons[BTN_IDX_YELLOW_CYM]  = 4;
    config->pin_buttons[BTN_IDX_BLUE_CYM]    = 5;
    config->pin_buttons[BTN_IDX_GREEN_CYM]   = 6;
    config->pin_buttons[BTN_IDX_START]       = 7;
    config->pin_buttons[BTN_IDX_SELECT]      = 8;
    // New inputs default to disabled — assign pins via configurator
    config->pin_buttons[BTN_IDX_DPAD_UP]     = -1;
    config->pin_buttons[BTN_IDX_DPAD_DOWN]   = -1;
    config->pin_buttons[BTN_IDX_DPAD_LEFT]   = -1;
    config->pin_buttons[BTN_IDX_DPAD_RIGHT]  = -1;
    config->pin_buttons[BTN_IDX_FOOT_PEDAL]  = -1;

    config->debounce_ms = 5;

    // LEDs disabled by default
    config->leds.enabled         = 0;
    config->leds.count           = 0;
    config->leds.base_brightness = 2;
    config->leds.data_pin        = LED_SPI_DEFAULT_DATA_PIN;
    config->leds.clock_pin       = LED_SPI_DEFAULT_CLOCK_PIN;

    // Default pad colors: original 9 pads + dpad (white) + pedal (orange)
    const uint8_t def_colors[][3] = {
        {255,   0,   0},   // Red Drum
        {255, 128,   0},   // Yellow Drum
        {  0,   0, 255},   // Blue Drum
        {  0, 255,   0},   // Green Drum
        {255, 128,   0},   // Yellow Cymbal
        {  0,   0, 255},   // Blue Cymbal
        {  0, 255,   0},   // Green Cymbal
        {255, 255, 255},   // Start
        {255, 255, 255},   // Select
        {255, 255, 255},   // D-pad Up
        {255, 255, 255},   // D-pad Down
        {255, 255, 255},   // D-pad Left
        {255, 255, 255},   // D-pad Right
        {255,  80,   0},   // Foot Pedal (orange)
    };
    for (int i = 0; i < BTN_IDX_COUNT && i < MAX_LEDS; i++) {
        config->leds.colors[i].r = def_colors[i][0];
        config->leds.colors[i].g = def_colors[i][1];
        config->leds.colors[i].b = def_colors[i][2];
    }

    // Default mapping: each button → its own LED (1:1)
    for (int i = 0; i < DRUM_INPUT_COUNT; i++) {
        config->leds.led_map[i]          = (i < MAX_LEDS) ? (1u << i) : 0;
        config->leds.active_brightness[i] = 25;
    }

    config->leds.loop_enabled = 0;
    config->leds.loop_start   = 0;
    config->leds.loop_end     = 0;

    config->leds.breathe_enabled    = 0;
    config->leds.breathe_start      = 0;
    config->leds.breathe_end        = 0;
    config->leds.breathe_min_bright = 1;
    config->leds.breathe_max_bright = 9;

    config->leds.wave_enabled = 0;
    config->leds.wave_origin  = 0;

    // Effect speeds
    config->leds.loop_speed_ms    = 3000;
    config->leds.breathe_speed_ms = 3000;
    config->leds.wave_speed_ms    = 800;

    strncpy(config->device_name, "Drum Controller", DEVICE_NAME_MAX);
    config->device_name[DEVICE_NAME_MAX] = '\0';

    config->checksum = _calc_checksum(config);
}

bool config_is_valid(const drum_config_t *config) {
    if (config->magic   != CONFIG_MAGIC)   return false;
    if (config->version != CONFIG_VERSION) return false;
    if (config->checksum != _calc_checksum(config)) return false;
    if (!apa102_spi_pin_is_valid(config->leds.data_pin, config->leds.clock_pin)) return false;
    return true;
}

void config_load(drum_config_t *config) {
    const drum_config_t *flash_config = FLASH_CONFIG_ADDR;
    if (config_is_valid(flash_config))
        memcpy(config, flash_config, sizeof(drum_config_t));
    else
        config_set_defaults(config);
}

void config_save(const drum_config_t *config) {
    uint8_t buf[FLASH_PAGE_SIZE];
    memset(buf, 0xFF, sizeof(buf));
    memcpy(buf, config, sizeof(drum_config_t));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, buf, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void config_update_checksum(drum_config_t *config) {
    config->magic    = CONFIG_MAGIC;
    config->version  = CONFIG_VERSION;
    config->checksum = _calc_checksum(config);
}
