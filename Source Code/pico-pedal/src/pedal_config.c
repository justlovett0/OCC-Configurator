/*
 * pedal_config.c - Flash-backed configuration storage for pedal controller
 */

#include "pedal_config.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include <string.h>

#define FLASH_CONFIG_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR    ((const pedal_config_t *)(XIP_BASE + FLASH_CONFIG_OFFSET))

static uint32_t _calc_checksum(const pedal_config_t *config) {
    const uint8_t *data = (const uint8_t *)config;
    size_t len = offsetof(pedal_config_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xDEADBEEF;
}

void config_set_defaults(pedal_config_t *config) {
    memset(config, 0, sizeof(pedal_config_t));
    config->magic   = CONFIG_MAGIC;
    config->version = CONFIG_VERSION;

    // Default pedal button pins: GP2–GP5
    // (GP0/GP1 reserved for PIO-USB D+/D-)
    config->pin_buttons[0] = 2;
    config->pin_buttons[1] = 3;
    config->pin_buttons[2] = 4;
    config->pin_buttons[3] = 5;

    // Default mappings: Green, Red, Yellow, Blue frets
    config->button_mapping[0] = BTN_IDX_GREEN;
    config->button_mapping[1] = BTN_IDX_RED;
    config->button_mapping[2] = BTN_IDX_YELLOW;
    config->button_mapping[3] = BTN_IDX_BLUE;

    config->debounce_ms = 5;

    strncpy(config->device_name, "Pedal Controller", DEVICE_NAME_MAX);
    config->device_name[DEVICE_NAME_MAX] = '\0';

    // Analog inputs disabled by default
    for (int i = 0; i < PEDAL_ADC_COUNT; i++) {
        config->adc_pin[i]    = -1;
        config->adc_axis[i]   = ADC_AXIS_WHAMMY;
        config->adc_invert[i] = 0;
        config->adc_min[i]    = 0;
        config->adc_max[i]    = 4095;
    }

    config->checksum = _calc_checksum(config);
}

bool config_is_valid(const pedal_config_t *config) {
    if (config->magic != CONFIG_MAGIC) return false;
    if (config->version != CONFIG_VERSION) return false;
    if (config->checksum != _calc_checksum(config)) return false;
    return true;
}

void config_load(pedal_config_t *config) {
    const pedal_config_t *flash_config = FLASH_CONFIG_ADDR;
    if (config_is_valid(flash_config)) {
        memcpy(config, flash_config, sizeof(pedal_config_t));
    } else {
        config_set_defaults(config);
    }
}

void config_save(const pedal_config_t *config) {
    uint8_t buf[FLASH_PAGE_SIZE];
    memset(buf, 0xFF, sizeof(buf));
    memcpy(buf, config, sizeof(pedal_config_t));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, buf, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void config_update_checksum(pedal_config_t *config) {
    config->magic    = CONFIG_MAGIC;
    config->version  = CONFIG_VERSION;
    config->checksum = _calc_checksum(config);
}
