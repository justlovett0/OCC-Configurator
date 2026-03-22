/*
 * macro_config.h - Keyboard macro pad configuration
 *
 * 20 macro slots, each with a GPIO pin, trigger mode, and up to 25 chars to type.
 * Stored packed in last flash sector with magic + checksum.
 *
 * Trigger modes:
 *   TRIGGER_PRESS   — type string once on button press
 *   TRIGGER_RELEASE — type string once on button release
 *   TRIGGER_HOLD    — repeat string while button held (500ms inter-repeat)
 *
 * v1: Initial version.
 * v2: Added send_enter per slot.
 */

#ifndef _MACRO_CONFIG_H_
#define _MACRO_CONFIG_H_

#include <stdint.h>
#include <stdbool.h>

#define CONFIG_MAGIC      0x4D43524F  // "MCRO"
#define CONFIG_VERSION    3           // v3: MACRO_STR_LEN 25->180
#define DEVICE_TYPE       "keyboard_macro"

#define MACRO_COUNT       20
#define MACRO_STR_LEN     180  // max chars per macro (+ null = 181 bytes stored)
#define DEVICE_NAME_MAX   31   // + null = 32 bytes

typedef enum {
    TRIGGER_PRESS   = 0,
    TRIGGER_RELEASE = 1,
    TRIGGER_HOLD    = 2,
} trigger_mode_t;

typedef struct __attribute__((packed)) {
    int8_t  pin;                      // GPIO pin (-1 = disabled)
    uint8_t trigger_mode;             // trigger_mode_t
    char    text[MACRO_STR_LEN + 1];  // what to type, null-terminated
    uint8_t send_enter;               // 1 = send Enter after text
} macro_slot_t;

typedef struct __attribute__((packed)) {
    uint32_t     magic;
    uint16_t     version;
    macro_slot_t macros[MACRO_COUNT];
    uint8_t      debounce_ms;
    char         device_name[DEVICE_NAME_MAX + 1];
    uint32_t     checksum;
} macro_config_t;

void config_load(macro_config_t *c);
void config_save(const macro_config_t *c);
void config_set_defaults(macro_config_t *c);
bool config_is_valid(const macro_config_t *c);
void config_update_checksum(macro_config_t *c);

#endif /* _MACRO_CONFIG_H_ */
