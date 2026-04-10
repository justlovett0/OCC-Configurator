#include "controller_binding_storage.h"

#include <stddef.h>
#include <string.h>

#include "hardware/flash.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#define CONTROLLER_BIND_MAGIC         0x43425442u
#define CONTROLLER_BIND_VERSION       1u
#define CONTROLLER_BIND_FLASH_OFFSET  (PICO_FLASH_SIZE_BYTES - (2 * FLASH_SECTOR_SIZE))
#define CONTROLLER_BIND_FLASH_ADDR    ((const controller_binding_flash_t *)(XIP_BASE + CONTROLLER_BIND_FLASH_OFFSET))

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint8_t  valid;
    uint8_t  addr_type;
    uint8_t  addr[CONTROLLER_BT_ADDR_LEN];
    uint32_t checksum;
} controller_binding_flash_t;

static uint32_t controller_binding_checksum(const controller_binding_flash_t *binding) {
    const uint8_t *data = (const uint8_t *)binding;
    size_t len = offsetof(controller_binding_flash_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);
    }
    return sum ^ 0xB16DFACEu;
}

bool controller_binding_is_valid(const controller_bt_binding_t *binding) {
    return binding && binding->valid;
}

void controller_binding_load(controller_bt_binding_t *binding) {
    if (!binding) return;

    memset(binding, 0, sizeof(*binding));

    const controller_binding_flash_t *flash_binding = CONTROLLER_BIND_FLASH_ADDR;
    if (flash_binding->magic != CONTROLLER_BIND_MAGIC) return;
    if (flash_binding->version != CONTROLLER_BIND_VERSION) return;
    if (flash_binding->valid != 1) return;
    if (flash_binding->checksum != controller_binding_checksum(flash_binding)) return;

    binding->valid = true;
    binding->addr_type = flash_binding->addr_type;
    memcpy(binding->addr, flash_binding->addr, CONTROLLER_BT_ADDR_LEN);
}

void controller_binding_save(const controller_bt_binding_t *binding) {
    controller_binding_flash_t flash_binding;
    memset(&flash_binding, 0xFF, sizeof(flash_binding));
    flash_binding.magic = CONTROLLER_BIND_MAGIC;
    flash_binding.version = CONTROLLER_BIND_VERSION;
    flash_binding.valid = (binding && binding->valid) ? 1 : 0;
    flash_binding.addr_type = binding ? binding->addr_type : 0;
    if (binding && binding->valid) {
        memcpy(flash_binding.addr, binding->addr, CONTROLLER_BT_ADDR_LEN);
    }
    flash_binding.checksum = controller_binding_checksum(&flash_binding);

    uint8_t page[FLASH_PAGE_SIZE];
    memset(page, 0xFF, sizeof(page));
    memcpy(page, &flash_binding, sizeof(flash_binding));

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(CONTROLLER_BIND_FLASH_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(CONTROLLER_BIND_FLASH_OFFSET, page, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}

void controller_binding_clear(void) {
    controller_binding_save(NULL);
}
