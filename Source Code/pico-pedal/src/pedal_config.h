/*
 * pedal_config.h - Pedal controller configuration
 *
 * Stores GPIO pin assignments and button-to-input mappings for up to
 * 4 pedal buttons. Each button maps to any guitar controller input
 * via a button_index_t value.
 *
 * Also supports up to 2 analog (ADC) inputs on GP26/GP27/GP28, each
 * mappable to whammy (right_stick_x) or tilt (right_stick_y). The
 * pedal's analog value is max-merged with the guitar passthrough so
 * whichever source is pressed further wins.
 *
 * v1: Initial version — 4 buttons, mappings, debounce, device name.
 * v2: Added 2 analog ADC input slots with axis mapping, invert, and
 *     calibration (min/max).
 */

#ifndef _PEDAL_CONFIG_H_
#define _PEDAL_CONFIG_H_

#include <stdint.h>
#include <stdbool.h>

#define CONFIG_MAGIC              0x5045444C  // "PEDL"
#define CONFIG_VERSION            2
#define DEVICE_NAME_MAX           31          // + null terminator = 32 bytes

// ── Device type identifier (sent as DEVTYPE: in GET_CONFIG response) ──
#define DEVICE_TYPE               "pedal"

#define PEDAL_BUTTON_COUNT        4

// ── Analog (ADC) input slots — GP26/GP27/GP28 only ──
#define PEDAL_ADC_COUNT           2

// Which XInput axis an analog pedal input is routed to
typedef enum {
    ADC_AXIS_WHAMMY = 0,   // right_stick_x — rest = -32768, full = +32767
    ADC_AXIS_TILT   = 1,   // right_stick_y — rest = 0, active = +32767
    ADC_AXIS_COUNT  = 2
} adc_axis_t;

// ── Button index enum (shared with guitar firmware for mapping targets) ──
// Each pedal button maps to one of these indices, which correspond to
// XInput button masks looked up at runtime.
typedef enum {
    BTN_IDX_GREEN = 0,
    BTN_IDX_RED,
    BTN_IDX_YELLOW,
    BTN_IDX_BLUE,
    BTN_IDX_ORANGE,
    BTN_IDX_STRUM_UP,
    BTN_IDX_STRUM_DOWN,
    BTN_IDX_START,
    BTN_IDX_SELECT,
    BTN_IDX_DPAD_UP,
    BTN_IDX_DPAD_DOWN,
    BTN_IDX_DPAD_LEFT,
    BTN_IDX_DPAD_RIGHT,
    BTN_IDX_GUIDE,
    // Axis outputs: pressing the button drives the axis to 100% (+32767)
    // using the same max-merge as analog inputs — guitar passthrough wins
    // if already higher, otherwise the button press takes over.
    BTN_IDX_WHAMMY,         // 14 — right_stick_x → +32767 when pressed
    BTN_IDX_TILT,           // 15 — right_stick_y → +32767 when pressed
    BTN_IDX_COUNT           // = 16
} button_index_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;

    // ── Pedal button GPIO pins (-1 = disabled) ──
    int8_t   pin_buttons[PEDAL_BUTTON_COUNT];

    // ── Button mappings: which guitar input each pedal button emulates ──
    // Values are button_index_t (0–13). e.g. BTN_IDX_GREEN, BTN_IDX_STRUM_DOWN.
    uint8_t  button_mapping[PEDAL_BUTTON_COUNT];

    uint8_t  debounce_ms;

    // ── Custom device name ──
    char device_name[DEVICE_NAME_MAX + 1];  // 32 bytes, null-terminated

    // ── Analog (ADC) pedal inputs ──
    // Only GP26/GP27/GP28 support ADC. Set adc_pin[i] = -1 to disable.
    // Output is max-merged with the guitar passthrough: whichever source
    // is further from rest wins.
    int8_t   adc_pin[PEDAL_ADC_COUNT];     // GPIO pin (26–28), or -1 = disabled
    uint8_t  adc_axis[PEDAL_ADC_COUNT];    // adc_axis_t: ADC_AXIS_WHAMMY or ADC_AXIS_TILT
    uint8_t  adc_invert[PEDAL_ADC_COUNT];  // 1 = invert axis direction
    uint16_t adc_min[PEDAL_ADC_COUNT];     // Calibration floor  (raw ADC, 0–4095)
    uint16_t adc_max[PEDAL_ADC_COUNT];     // Calibration ceiling (raw ADC, 0–4095)

    uint32_t checksum;
} pedal_config_t;

void config_load(pedal_config_t *config);
void config_save(const pedal_config_t *config);
void config_set_defaults(pedal_config_t *config);
bool config_is_valid(const pedal_config_t *config);
void config_update_checksum(pedal_config_t *config);

#endif /* _PEDAL_CONFIG_H_ */
