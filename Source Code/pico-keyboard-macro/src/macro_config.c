/*
 * macro_config.c - Flash-backed config storage for keyboard macro pad
 *
 * Same load/save/checksum pattern as other OCC firmwares.
 * struct is 3723 bytes so we write 15 flash pages (3840 bytes).
 */

#include "macro_config.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include <string.h>

#define FLASH_CONFIG_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR    ((const macro_config_t *)(XIP_BASE + FLASH_CONFIG_OFFSET))

// Round struct size up to a multiple of FLASH_PAGE_SIZE for programming
#define CONFIG_PAGES      ((sizeof(macro_config_t) + FLASH_PAGE_SIZE - 1) / FLASH_PAGE_SIZE)
#define CONFIG_SAVE_SIZE  (CONFIG_PAGES * FLASH_PAGE_SIZE)

static uint32_t _calc_checksum(const macro_config_t *c) {
    const uint8_t *data = (const uint8_t *)c;
    size_t len = offsetof(macro_config_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xDEADBEEF;
}

void config_set_defaults(macro_config_t *c) {
    memset(c, 0, sizeof(macro_config_t));
    c->magic   = CONFIG_MAGIC;
    c->version = CONFIG_VERSION;

    // All slots disabled by default
    for (int i = 0; i < MACRO_COUNT; i++) {
        c->macros[i].pin          = -1;
        c->macros[i].trigger_mode = TRIGGER_PRESS;
        c->macros[i].text[0]      = '\0';
        c->macros[i].send_enter   = 0;
    }

    c->debounce_ms = 5;
    strncpy(c->device_name, "Macro Pad", DEVICE_NAME_MAX);
    c->device_name[DEVICE_NAME_MAX] = '\0';

    c->checksum = _calc_checksum(c);
}

bool config_is_valid(const macro_config_t *c) {
    if (c->magic   != CONFIG_MAGIC)   return false;
    if (c->version != CONFIG_VERSION) return false;
    if (c->checksum != _calc_checksum(c)) return false;
    return true;
}

void config_load(macro_config_t *c) {
    const macro_config_t *flash = FLASH_CONFIG_ADDR;
    if (config_is_valid(flash)) {
        memcpy(c, flash, sizeof(macro_config_t));
    } else {
        config_set_defaults(c);
    }
}

void config_save(const macro_config_t *c) {
    // Static buffer avoids large stack allocation
    static uint8_t buf[CONFIG_SAVE_SIZE];
    memset(buf, 0xFF, sizeof(buf));
    memcpy(buf, c, sizeof(macro_config_t));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, buf, CONFIG_SAVE_SIZE);
    restore_interrupts(ints);
}

void config_update_checksum(macro_config_t *c) {
    c->magic   = CONFIG_MAGIC;
    c->version = CONFIG_VERSION;
    c->checksum = _calc_checksum(c);
}
