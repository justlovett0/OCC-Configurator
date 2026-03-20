/*
 * retro_config.c - Flash-backed configuration storage for retro controller
 */

#include "retro_config.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include <string.h>

#define FLASH_CONFIG_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR    ((const retro_config_t *)(XIP_BASE + FLASH_CONFIG_OFFSET))

static uint32_t _calc_checksum(const retro_config_t *config) {
    const uint8_t *data = (const uint8_t *)config;
    size_t len = offsetof(retro_config_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xDEADBEEF;
}

void config_set_defaults(retro_config_t *config) {
    memset(config, 0, sizeof(retro_config_t));
    config->magic   = CONFIG_MAGIC;
    config->version = CONFIG_VERSION;

    // All button pins disabled by default — user assigns via configurator
    for (int i = 0; i < RETRO_BTN_COUNT; i++) {
        config->pin_buttons[i] = -1;
    }

    // Triggers disabled by default
    config->pin_lt = -1;
    config->pin_rt = -1;

    // Default to digital mode (no ADC needed until user configures analog)
    config->mode_lt = INPUT_MODE_DIGITAL;
    config->mode_rt = INPUT_MODE_DIGITAL;

    config->debounce_ms = 5;

    // Empty device name — configurator will set this if desired
    memset(config->device_name, 0, sizeof(config->device_name));

    // Full ADC range calibration defaults
    config->lt_min = 0;
    config->lt_max = 4095;
    config->rt_min = 0;
    config->rt_max = 4095;

    // Normal orientation (no invert)
    config->lt_invert = 0;
    config->rt_invert = 0;

    // No smoothing by default (0 = fastest response, matches guitar convention)
    config->lt_ema_alpha = 0;
    config->rt_ema_alpha = 0;

    config->checksum = _calc_checksum(config);
}

bool config_is_valid(const retro_config_t *config) {
    if (config->magic != CONFIG_MAGIC) return false;
    if (config->version != CONFIG_VERSION) return false;
    if (config->checksum != _calc_checksum(config)) return false;
    return true;
}

void config_load(retro_config_t *config) {
    const retro_config_t *flash_config = FLASH_CONFIG_ADDR;
    if (config_is_valid(flash_config)) {
        memcpy(config, flash_config, sizeof(retro_config_t));
    } else {
        config_set_defaults(config);
    }
}

void config_save(const retro_config_t *config) {
    uint8_t buf[FLASH_PAGE_SIZE];
    memset(buf, 0xFF, sizeof(buf));
    memcpy(buf, config, sizeof(retro_config_t));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, buf, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void config_update_checksum(retro_config_t *config) {
    config->magic    = CONFIG_MAGIC;
    config->version  = CONFIG_VERSION;
    config->checksum = _calc_checksum(config);
}
