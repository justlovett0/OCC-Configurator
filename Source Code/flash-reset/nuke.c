/**
 * Copyright (c) 2020 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

// Obliterate the contents of flash. This is a silly thing to do if you are
// trying to run this program from flash, so you should really load and run
// directly from SRAM. You can enable RAM-only builds for all targets by doing:
//
// cmake -DPICO_NO_FLASH=1 ..
//
// in your build directory. We've also forced no-flash builds for this app in
// particular by adding:
//
// pico_set_binary_type(flash_nuke no_flash)
//
// To the CMakeLists.txt app for this file. Just to be sure, we can check the
// define:
#if !PICO_NO_FLASH && !PICO_COPY_TO_RAM
#error "This example must be built to run from SRAM!"
#endif

#include <stddef.h>
#include <string.h>

#include "pico/stdlib.h"
#include "hardware/flash.h"
#include "pico/bootrom.h"

#include "hardware/sync.h"
#include "pico/unique_id.h"

// OCC stores controller configuration in the last flash sector. Explicitly
// wipe it so factory reset clears persisted settings/device names even if the
// broader full-flash erase behavior changes or is partially ineffective.
static void wipe_occ_config_sector(uint flash_size_bytes) {
    flash_range_erase(flash_size_bytes - FLASH_SECTOR_SIZE, FLASH_SECTOR_SIZE);
}

#define BLE_IDENTITY_FLASH_MAGIC    0x424C4549u
#define BLE_IDENTITY_FLASH_VERSION  1u
#define BLE_IDENTITY_ADDR_LEN       6u

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

static bool ble_identity_is_valid(const uint8_t *addr) {
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

static void ble_identity_generate(uint8_t *out_addr) {
    uint32_t state = ble_identity_seed();
    do {
        for (int i = 0; i < BLE_IDENTITY_ADDR_LEN; i++) {
            out_addr[i] = (uint8_t)ble_identity_next(&state);
        }
        out_addr[0] &= 0x3F;
        out_addr[0] |= 0xC0;
    } while (!ble_identity_is_valid(out_addr));
}

static void write_ble_identity_record(uint flash_size_bytes, const uint8_t *addr) {
    uint32_t offset = flash_size_bytes - (3 * FLASH_SECTOR_SIZE);
    ble_identity_flash_t identity;
    memset(&identity, 0xFF, sizeof(identity));
    identity.magic = BLE_IDENTITY_FLASH_MAGIC;
    identity.version = BLE_IDENTITY_FLASH_VERSION;
    identity.valid = ble_identity_is_valid(addr) ? 1 : 0;
    memcpy(identity.addr, addr, BLE_IDENTITY_ADDR_LEN);
    identity.checksum = ble_identity_checksum(&identity);

    uint8_t page[FLASH_PAGE_SIZE];
    memset(page, 0xFF, sizeof(page));
    memcpy(page, &identity, sizeof(identity));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(offset, FLASH_SECTOR_SIZE);
    flash_range_program(offset, page, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

int main() {
    uint flash_size_bytes;
    uint8_t new_identity[BLE_IDENTITY_ADDR_LEN];

    uint8_t txbuf[4];
    uint8_t rxbuf[4];
    txbuf[0] = 0x9f;

    flash_do_cmd(txbuf, rxbuf, 4);

    flash_size_bytes = 1u << rxbuf[3];

    flash_range_erase(0, flash_size_bytes);
    wipe_occ_config_sector(flash_size_bytes);

    // Leave an eyecatcher pattern in the first page of flash so picotool can
    // more easily check the size:
    static const uint8_t eyecatcher[FLASH_PAGE_SIZE] = "NUKE";
    flash_range_program(0, eyecatcher, FLASH_PAGE_SIZE);

    ble_identity_generate(new_identity);
    write_ble_identity_record(flash_size_bytes, new_identity);

#ifdef PICO_DEFAULT_LED_PIN
    // Flash LED for success
    gpio_init(PICO_DEFAULT_LED_PIN);
    gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);
    for (int i = 0; i < 3; ++i) {
        gpio_put(PICO_DEFAULT_LED_PIN, 1);
        sleep_ms(100);
        gpio_put(PICO_DEFAULT_LED_PIN, 0);
        sleep_ms(100);
    }
#endif

    reset_usb_boot(0, 0);
}
