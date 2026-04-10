#include "ble_identity_storage.h"

#include <stddef.h>
#include <string.h>

#include "hardware/flash.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"
#include "pico/unique_id.h"

#define BLE_IDENTITY_FLASH_ADDR ((const ble_identity_flash_t *)(XIP_BASE + BLE_IDENTITY_FLASH_OFFSET))

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint8_t  valid;
    uint8_t  addr[BLE_IDENTITY_ADDR_LEN];
    uint32_t checksum;
} ble_identity_flash_t;

static uint32_t ble_identity_checksum(const ble_identity_flash_t *identity) {
    const uint8_t *data = (const uint8_t *)identity;
    size_t len = offsetof(ble_identity_flash_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xB1E1D7A9u;
}

bool ble_identity_is_valid(const uint8_t *addr) {
    if (!addr) return false;

    bool all_zero = true;
    bool all_ff = true;
    for (int i = 0; i < BLE_IDENTITY_ADDR_LEN; i++) {
        if (addr[i] != 0x00) all_zero = false;
        if (addr[i] != 0xFF) all_ff = false;
    }
    if (all_zero || all_ff) return false;

    return (addr[0] & 0xC0) == 0xC0;
}

static uint32_t ble_identity_seed(void) {
    pico_unique_board_id_t board_id;
    pico_get_unique_board_id(&board_id);

    uint64_t now = time_us_64();
    uint32_t seed = (uint32_t)now ^ (uint32_t)(now >> 32) ^ 0xA53C9E17u;
    for (size_t i = 0; i < sizeof(board_id.id); i++) {
        seed ^= ((uint32_t)board_id.id[i]) << ((i % 4) * 8);
        seed = (seed << 5) | (seed >> 27);
        seed ^= 0x9E3779B9u + (uint32_t)i;
    }
    return seed ? seed : 0xD1CEBEEFu;
}

static uint32_t ble_identity_next(uint32_t *state) {
    uint32_t x = *state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    if (x == 0) x = 0x6D2B79F5u;
    *state = x;
    return x;
}

void ble_identity_generate(uint8_t *out_addr) {
    uint32_t state = ble_identity_seed();
    do {
        for (int i = 0; i < BLE_IDENTITY_ADDR_LEN; i++) {
            out_addr[i] = (uint8_t)ble_identity_next(&state);
        }
        out_addr[0] &= 0x3F;
        out_addr[0] |= 0xC0;
    } while (!ble_identity_is_valid(out_addr));
}

bool ble_identity_load(uint8_t *out_addr) {
    if (!out_addr) return false;
    memset(out_addr, 0, BLE_IDENTITY_ADDR_LEN);

    const ble_identity_flash_t *flash_identity = BLE_IDENTITY_FLASH_ADDR;
    if (flash_identity->magic != BLE_IDENTITY_FLASH_MAGIC) return false;
    if (flash_identity->version != BLE_IDENTITY_FLASH_VERSION) return false;
    if (flash_identity->valid != 1) return false;
    if (flash_identity->checksum != ble_identity_checksum(flash_identity)) return false;
    if (!ble_identity_is_valid(flash_identity->addr)) return false;

    memcpy(out_addr, flash_identity->addr, BLE_IDENTITY_ADDR_LEN);
    return true;
}

void ble_identity_save(const uint8_t *addr) {
    ble_identity_flash_t flash_identity;
    memset(&flash_identity, 0xFF, sizeof(flash_identity));
    flash_identity.magic = BLE_IDENTITY_FLASH_MAGIC;
    flash_identity.version = BLE_IDENTITY_FLASH_VERSION;
    flash_identity.valid = (addr && ble_identity_is_valid(addr)) ? 1 : 0;
    if (flash_identity.valid) {
        memcpy(flash_identity.addr, addr, BLE_IDENTITY_ADDR_LEN);
    }
    flash_identity.checksum = ble_identity_checksum(&flash_identity);

    uint8_t page[FLASH_PAGE_SIZE];
    memset(page, 0xFF, sizeof(page));
    memcpy(page, &flash_identity, sizeof(flash_identity));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(BLE_IDENTITY_FLASH_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(BLE_IDENTITY_FLASH_OFFSET, page, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void ble_identity_clear(void) {
    ble_identity_save(NULL);
}
