#ifndef _CONTROLLER_BINDING_STORAGE_H_
#define _CONTROLLER_BINDING_STORAGE_H_

#include <stdbool.h>

#include "controller_bt.h"

void controller_binding_load(controller_bt_binding_t *binding);
void controller_binding_save(const controller_bt_binding_t *binding);
void controller_binding_clear(void);
bool controller_binding_is_valid(const controller_bt_binding_t *binding);

#endif
