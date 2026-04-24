/*
 * drum_config.h - Flash-backed configuration for XInput Drum Kit
 *
 * Inputs:
 *   9 digital buttons: Red Drum, Yellow Drum, Blue Drum, Green Drum,
 *                      Yellow Cymbal, Blue Cymbal, Green Cymbal,
 *                      Start, Select
 *   4 D-pad buttons:   D-pad Up, Down, Left, Right
 *   1 Foot Pedal:      Bass pedal (XInput LB / left bumper)
 *
 * v1: Initial drum kit config.
 * v2: Added APA102 LED strip support.
 * v3: Added D-pad (up/down/left/right) and foot pedal inputs.
 * v4: Added breathe+wave effects and per-effect LED speed fields.
 * v5: Added configurable LED SPI data/clock pins.
 */

#ifndef _DRUM_CONFIG_H_
#define _DRUM_CONFIG_H_

#include <stdint.h>
#include <stdbool.h>

#include "apa102_leds.h"

// Number of mappable inputs on this device (used by serial handler and defaults).
// Separate from LED_INPUT_COUNT (which is always 16 in apa102_leds.h) —
// drums use the first DRUM_INPUT_COUNT slots of the led_map/active_brightness arrays.
#define DRUM_INPUT_COUNT  14

#define CONFIG_MAGIC      0x4452554D  // "DRUM"
#define CONFIG_VERSION    5           // Bumped for configurable LED SPI pins
#define DEVICE_NAME_MAX   31          // + null terminator = 32 bytes

// ── Device type identifier (read by configurator GUI) ──
#define DEVICE_TYPE       "drum_kit"

// ── Button indices ──
typedef enum {
    BTN_IDX_RED_DRUM = 0,
    BTN_IDX_YELLOW_DRUM,
    BTN_IDX_BLUE_DRUM,
    BTN_IDX_GREEN_DRUM,
    BTN_IDX_YELLOW_CYM,
    BTN_IDX_BLUE_CYM,
    BTN_IDX_GREEN_CYM,
    BTN_IDX_START,
    BTN_IDX_SELECT,
    BTN_IDX_DPAD_UP,
    BTN_IDX_DPAD_DOWN,
    BTN_IDX_DPAD_LEFT,
    BTN_IDX_DPAD_RIGHT,
    BTN_IDX_FOOT_PEDAL,
    BTN_IDX_COUNT           // = 14, also = DRUM_INPUT_COUNT
} button_index_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;

    int8_t   pin_buttons[BTN_IDX_COUNT]; // GPIO pin per button; -1 = disabled

    uint8_t  debounce_ms;

    // ── LED configuration (APA102 / SK9822 / Dotstar) ──
    led_config_t leds;

    // Custom device name shown in USB string descriptors
    char     device_name[DEVICE_NAME_MAX + 1];

    uint32_t checksum;
} drum_config_t;

void config_load(drum_config_t *config);
void config_save(const drum_config_t *config);
void config_set_defaults(drum_config_t *config);
bool config_is_valid(const drum_config_t *config);
void config_update_checksum(drum_config_t *config);

#endif /* _DRUM_CONFIG_H_ */
