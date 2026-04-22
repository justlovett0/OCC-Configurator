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
#include "hardware/gpio.h"
#include "pico/bootrom.h"

#include "hardware/sync.h"
#include "pico/unique_id.h"

#define OCC_MAX_APA102_LEDS 16u
#define OCC_APA102_DEFAULT_DATA_PIN 3u
#define OCC_APA102_PEDAL_DATA_PIN 7u
#define OCC_APA102_CLOCK_PIN 6u

static void apa102_clock_bit(uint data_pin, uint clock_pin, bool bit) {
    gpio_put(data_pin, bit ? 1 : 0);
    sleep_us(1);
    gpio_put(clock_pin, 1);
    sleep_us(1);
    gpio_put(clock_pin, 0);
    sleep_us(1);
}

static void apa102_send_byte(uint data_pin, uint clock_pin, uint8_t value) {
    for (int bit = 7; bit >= 0; bit--) {
        apa102_clock_bit(data_pin, clock_pin, (value & (1u << bit)) != 0);
    }
}

static void apa102_all_off_on_pins(uint data_pin, uint clock_pin) {
    if (data_pin == clock_pin) return;

    gpio_init(data_pin);
    gpio_init(clock_pin);
    gpio_set_dir(data_pin, GPIO_OUT);
    gpio_set_dir(clock_pin, GPIO_OUT);
    gpio_put(data_pin, 0);
    gpio_put(clock_pin, 0);
    sleep_us(10);

    // Send twice so already-latched APA102/SK9822 chains reliably receive the
    // blank frame even if the previous firmware left the clock line mid-frame.
    for (int pass = 0; pass < 2; pass++) {
        for (int i = 0; i < 4; i++) {
            apa102_send_byte(data_pin, clock_pin, 0x00);
        }
        for (uint led = 0; led < OCC_MAX_APA102_LEDS; led++) {
            apa102_send_byte(data_pin, clock_pin, 0xE0);
            apa102_send_byte(data_pin, clock_pin, 0x00);
            apa102_send_byte(data_pin, clock_pin, 0x00);
            apa102_send_byte(data_pin, clock_pin, 0x00);
        }
        for (int i = 0; i < 8; i++) {
            apa102_send_byte(data_pin, clock_pin, 0xFF);
        }
        sleep_ms(2);
    }
}

static void release_normal_gpio(void) {
    for (uint pin = 0; pin <= 29; pin++) {
        gpio_init(pin);
        gpio_set_dir(pin, GPIO_IN);
        gpio_disable_pulls(pin);
    }
}

static void quiesce_occ_outputs(void) {
    apa102_all_off_on_pins(OCC_APA102_DEFAULT_DATA_PIN, OCC_APA102_CLOCK_PIN);
    apa102_all_off_on_pins(OCC_APA102_PEDAL_DATA_PIN, OCC_APA102_CLOCK_PIN);
#ifdef PICO_DEFAULT_LED_PIN
    gpio_init(PICO_DEFAULT_LED_PIN);
    gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);
    gpio_put(PICO_DEFAULT_LED_PIN, 0);
#endif
    release_normal_gpio();
}

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

    quiesce_occ_outputs();

    flash_range_erase(0, flash_size_bytes);
    wipe_occ_config_sector(flash_size_bytes);

    // Leave an eyecatcher pattern in the first page of flash so picotool can
    // more easily check the size:
    static const uint8_t eyecatcher[FLASH_PAGE_SIZE] = "NUKE";
    flash_range_program(0, eyecatcher, FLASH_PAGE_SIZE);

    ble_identity_generate(new_identity);
    write_ble_identity_record(flash_size_bytes, new_identity);

    quiesce_occ_outputs();

    reset_usb_boot(0, 0);
}
