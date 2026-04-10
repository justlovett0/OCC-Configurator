#include "dongle_bindings.h"

#include <stddef.h>
#include <string.h>

#include "hardware/flash.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#define DONGLE_BIND_MAGIC         0x44424E44u
#define DONGLE_BIND_VERSION       1u
#define DONGLE_BIND_FLASH_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define DONGLE_BIND_FLASH_ADDR    ((const dongle_bindings_flash_t *)(XIP_BASE + DONGLE_BIND_FLASH_OFFSET))

typedef struct __attribute__((packed)) {
    uint8_t valid;
    uint8_t addr_type;
    uint8_t mac[BLE_MAC_LEN];
} dongle_binding_slot_flash_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    dongle_binding_slot_flash_t slots[DONGLE_MAX_CONTROLLERS];
    uint32_t checksum;
} dongle_bindings_flash_t;

static uint32_t dongle_bindings_checksum(const dongle_bindings_flash_t *bindings) {
    const uint8_t *data = (const uint8_t *)bindings;
    size_t len = offsetof(dongle_bindings_flash_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xD06E6C45u;
}

static void dongle_bindings_defaults(dongle_bindings_flash_t *bindings) {
    memset(bindings, 0, sizeof(*bindings));
    bindings->magic = DONGLE_BIND_MAGIC;
    bindings->version = DONGLE_BIND_VERSION;
}

static bool dongle_bindings_flash_valid(const dongle_bindings_flash_t *bindings) {
    if (bindings->magic != DONGLE_BIND_MAGIC) return false;
    if (bindings->version != DONGLE_BIND_VERSION) return false;
    if (bindings->checksum != dongle_bindings_checksum(bindings)) return false;
    return true;
}

void dongle_bindings_load(dongle_binding_t bindings[DONGLE_MAX_CONTROLLERS]) {
    for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
        memset(&bindings[i], 0, sizeof(bindings[i]));
    }

    const dongle_bindings_flash_t *flash_bindings = DONGLE_BIND_FLASH_ADDR;
    if (!dongle_bindings_flash_valid(flash_bindings)) return;

    for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
        bindings[i].valid = flash_bindings->slots[i].valid == 1;
        bindings[i].addr_type = flash_bindings->slots[i].addr_type;
        memcpy(bindings[i].mac, flash_bindings->slots[i].mac, BLE_MAC_LEN);
    }
}

void dongle_bindings_save_slot(uint8_t slot, const dongle_binding_t *binding) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return;

    dongle_bindings_flash_t flash_bindings;
    if (dongle_bindings_flash_valid(DONGLE_BIND_FLASH_ADDR)) {
        memcpy(&flash_bindings, DONGLE_BIND_FLASH_ADDR, sizeof(flash_bindings));
    } else {
        dongle_bindings_defaults(&flash_bindings);
    }

    memset(&flash_bindings.slots[slot], 0, sizeof(flash_bindings.slots[slot]));
    if (binding && binding->valid) {
        flash_bindings.slots[slot].valid = 1;
        flash_bindings.slots[slot].addr_type = binding->addr_type;
        memcpy(flash_bindings.slots[slot].mac, binding->mac, BLE_MAC_LEN);
    }
    flash_bindings.checksum = dongle_bindings_checksum(&flash_bindings);

    uint8_t page[FLASH_PAGE_SIZE];
    memset(page, 0xFF, sizeof(page));
    memcpy(page, &flash_bindings, sizeof(flash_bindings));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(DONGLE_BIND_FLASH_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(DONGLE_BIND_FLASH_OFFSET, page, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void dongle_bindings_clear_slot(uint8_t slot) {
    dongle_bindings_save_slot(slot, NULL);
}
