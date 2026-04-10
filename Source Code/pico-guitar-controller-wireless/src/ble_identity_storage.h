#ifndef _BLE_IDENTITY_STORAGE_H_
#define _BLE_IDENTITY_STORAGE_H_

#include <stdbool.h>
#include <stdint.h>

#include "hardware/flash.h"

#define BLE_IDENTITY_FLASH_MAGIC    0x424C4549u
#define BLE_IDENTITY_FLASH_VERSION  1u
#define BLE_IDENTITY_FLASH_OFFSET   (PICO_FLASH_SIZE_BYTES - (3 * FLASH_SECTOR_SIZE))
#define BLE_IDENTITY_ADDR_LEN       6u

bool ble_identity_is_valid(const uint8_t *addr);
void ble_identity_generate(uint8_t *out_addr);
bool ble_identity_load(uint8_t *out_addr);
void ble_identity_save(const uint8_t *addr);
void ble_identity_clear(void);

#endif /* _BLE_IDENTITY_STORAGE_H_ */
