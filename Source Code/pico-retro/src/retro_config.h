/*
 * retro_config.h - Retro controller configuration
 *
 * Stores GPIO pin assignments for 13 digital buttons plus 2 trigger
 * inputs (LT/RT). Each trigger is individually configurable as digital
 * (threshold GPIO) or analog (ADC 0-4095 scaled to 0-255).
 *
 * Config is stored in the last flash sector with a magic number,
 * version field, and rotating-accumulate checksum.
 *
 * v1: Initial version — 13 buttons, 2 triggers, calibration, EMA smoothing.
 */

#ifndef _RETRO_CONFIG_H_
#define _RETRO_CONFIG_H_

#include <stdint.h>
#include <stdbool.h>

#define CONFIG_MAGIC              0x52455452  // "RETR"
#define CONFIG_VERSION            1
#define DEVICE_NAME_MAX           31          // + null terminator = 32 bytes

// ── Device type identifier (sent as DEVTYPE: in GET_CONFIG response) ──
#define DEVICE_TYPE               "pico_retro"

#define RETRO_BTN_COUNT           13

// ── Trigger input mode ──
typedef enum {
    INPUT_MODE_DIGITAL = 0,  // Reads GPIO HIGH/LOW, outputs 0 or 255
    INPUT_MODE_ANALOG  = 1   // Reads ADC, scales to 0-255 with calibration
} input_mode_t;

// ── Button index enum (13 standard gamepad buttons) ──
// LT/RT triggers are NOT in this enum — they are always axis outputs.
typedef enum {
    BTN_IDX_DPAD_UP = 0,
    BTN_IDX_DPAD_DOWN,
    BTN_IDX_DPAD_LEFT,
    BTN_IDX_DPAD_RIGHT,
    BTN_IDX_A,
    BTN_IDX_B,
    BTN_IDX_X,
    BTN_IDX_Y,
    BTN_IDX_START,
    BTN_IDX_SELECT,
    BTN_IDX_GUIDE,
    BTN_IDX_LB,
    BTN_IDX_RB,
    BTN_IDX_COUNT  // = 13
} button_index_t;

// ── Configuration struct ──
// Packed to minimise flash page usage. Must fit in FLASH_PAGE_SIZE (256 bytes).
typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;

    // ── Button GPIO pins (-1 = disabled) ──
    int8_t   pin_buttons[RETRO_BTN_COUNT];

    // ── Trigger GPIO pins (-1 = disabled) ──
    int8_t   pin_lt;   // LT trigger GPIO pin
    int8_t   pin_rt;   // RT trigger GPIO pin

    // ── Trigger modes ──
    uint8_t  mode_lt;  // input_mode_t: INPUT_MODE_DIGITAL or INPUT_MODE_ANALOG
    uint8_t  mode_rt;

    // ── Shared debounce for all digital inputs (ms) ──
    uint8_t  debounce_ms;

    // ── Custom device name (alphanumeric, max 20 chars enforced by configurator) ──
    char     device_name[DEVICE_NAME_MAX + 1];  // 32 bytes, null-terminated

    // ── Trigger calibration (raw ADC 0-4095) ──
    uint16_t lt_min, lt_max;   // Full range defaults: 0, 4095
    uint16_t rt_min, rt_max;

    // ── Trigger axis invert (0 = normal, 1 = invert) ──
    uint8_t  lt_invert, rt_invert;

    // ── EMA smoothing (0-100 user %, 0 = no smoothing / fastest response) ──
    uint8_t  lt_ema_alpha, rt_ema_alpha;

    uint32_t checksum;
} retro_config_t;

_Static_assert(sizeof(retro_config_t) <= 256,
               "retro_config_t exceeds FLASH_PAGE_SIZE");

void config_load(retro_config_t *config);
void config_save(const retro_config_t *config);
void config_set_defaults(retro_config_t *config);
bool config_is_valid(const retro_config_t *config);
void config_update_checksum(retro_config_t *config);

#endif /* _RETRO_CONFIG_H_ */
