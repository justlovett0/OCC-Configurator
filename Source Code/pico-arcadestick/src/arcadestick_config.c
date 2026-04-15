/*
 * arcadestick_config.c - Flash-backed arcade stick configuration
 */

#include "arcadestick_config.h"

#include <stddef.h>
#include <string.h>

#include "hardware/flash.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#define FLASH_TARGET_OFFSET (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR    ((const arcadestick_config_t *)(XIP_BASE + FLASH_TARGET_OFFSET))

static uint32_t calc_checksum(const arcadestick_config_t *config) {
    const uint8_t *data = (const uint8_t *) config;
    size_t len = offsetof(arcadestick_config_t, checksum);
    uint32_t acc = 0;

    for (size_t i = 0; i < len; ++i) {
        acc = (acc << 5) | (acc >> 27);
        acc += data[i];
    }
    return acc;
}

void config_set_defaults(arcadestick_config_t *config) {
    memset(config, 0, sizeof(*config));
    config->magic = CONFIG_MAGIC;
    config->version = CONFIG_VERSION;

    config->pin_up = -1;
    config->pin_down = -1;
    config->pin_left = -1;
    config->pin_right = -1;

    for (int i = 0; i < ARCADE_ATTACK_COUNT; ++i) {
        config->pin_attack[i] = -1;
    }

    config->pin_start = -1;
    config->pin_select = -1;
    config->pin_guide = -1;
    config->pin_l3 = -1;
    config->pin_r3 = -1;
    config->pin_mode_a = -1;
    config->pin_mode_b = -1;

    config->usb_mode = USB_MODE_XINPUT;
    config->stick_mode = STICK_MODE_DPAD;
    config->debounce_ms = 5;

    memset(config->device_name, 0, sizeof(config->device_name));
    config->checksum = calc_checksum(config);
}

bool config_is_valid(const arcadestick_config_t *config) {
    return config->magic == CONFIG_MAGIC &&
           config->version == CONFIG_VERSION &&
           config->checksum == calc_checksum(config);
}

void config_load(arcadestick_config_t *config) {
    const arcadestick_config_t *flash_config = FLASH_CONFIG_ADDR;
    if (config_is_valid(flash_config)) {
        memcpy(config, flash_config, sizeof(*config));
    } else {
        config_set_defaults(config);
    }
}

void config_save(const arcadestick_config_t *config) {
    uint8_t page_buf[FLASH_PAGE_SIZE] = {0};
    memcpy(page_buf, config, sizeof(*config));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_TARGET_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_TARGET_OFFSET, page_buf, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void config_update_checksum(arcadestick_config_t *config) {
    config->magic = CONFIG_MAGIC;
    config->version = CONFIG_VERSION;
    config->checksum = calc_checksum(config);
}
