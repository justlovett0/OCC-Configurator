/*
 * arcadestick_config.h - Arcade stick configuration storage
 */

#ifndef _ARCADESTICK_CONFIG_H_
#define _ARCADESTICK_CONFIG_H_

#include <stdbool.h>
#include <stdint.h>

#define CONFIG_MAGIC            0x4153544Bu  // "ASTK"
#define CONFIG_VERSION          1
#define DEVICE_NAME_MAX         31
#define DEVICE_TYPE             "pico_arcadestick"

#define ARCADE_ATTACK_COUNT     8

typedef enum {
    USB_MODE_XINPUT = 0,
    USB_MODE_HID    = 1,
} arcadestick_usb_mode_t;

typedef enum {
    STICK_MODE_DPAD       = 0,
    STICK_MODE_LEFT_STICK = 1,
    STICK_MODE_RIGHT_STICK = 2,
} arcadestick_stick_mode_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;

    int8_t pin_up;
    int8_t pin_down;
    int8_t pin_left;
    int8_t pin_right;

    int8_t pin_attack[ARCADE_ATTACK_COUNT];

    int8_t pin_start;
    int8_t pin_select;
    int8_t pin_guide;
    int8_t pin_l3;
    int8_t pin_r3;

    int8_t pin_mode_a;
    int8_t pin_mode_b;

    uint8_t usb_mode;
    uint8_t stick_mode;
    uint8_t debounce_ms;

    char device_name[DEVICE_NAME_MAX + 1];

    uint32_t checksum;
} arcadestick_config_t;

_Static_assert(sizeof(arcadestick_config_t) <= 256,
               "arcadestick_config_t exceeds FLASH_PAGE_SIZE");

void config_load(arcadestick_config_t *config);
void config_save(const arcadestick_config_t *config);
void config_set_defaults(arcadestick_config_t *config);
bool config_is_valid(const arcadestick_config_t *config);
void config_update_checksum(arcadestick_config_t *config);

#endif /* _ARCADESTICK_CONFIG_H_ */
