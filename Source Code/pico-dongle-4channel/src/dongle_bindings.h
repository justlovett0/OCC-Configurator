#ifndef _DONGLE_BINDINGS_H_
#define _DONGLE_BINDINGS_H_

#include <stdbool.h>
#include <stdint.h>

#include "dongle_bt.h"

typedef struct {
    bool    valid;
    uint8_t addr_type;
    uint8_t mac[BLE_MAC_LEN];
} dongle_binding_t;

void dongle_bindings_load(dongle_binding_t bindings[DONGLE_MAX_CONTROLLERS]);
void dongle_bindings_save_slot(uint8_t slot, const dongle_binding_t *binding);
void dongle_bindings_clear_slot(uint8_t slot);

#endif
