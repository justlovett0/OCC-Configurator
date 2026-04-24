/*
 * guitar_config.h - GPIO-to-button mapping + LED + device name + I2C
 *
 * v5:  Added I2C accelerometer (ADXL345) support for tilt.
 * v6:  Added per-input sensitivity (min/max ADC range) for tilt and whammy.
 * v7:  Added LED loop (color rotation) feature.
 * v8:  Added 5-pin analog joystick support.
 * v9:  Added joy_dpad_x/y_invert fields (struct unchanged from v8 size).
 * v10: Added i2c_model field to select accelerometer chip (ADXL345 / LIS3DH).
 *      Bumped CONFIG_VERSION to force defaults reset on first boot after update.
 * v11: Added ema_alpha field for user-configurable analog smoothing strength.
 * v12: Added sync_pin for dongle pairing button.
 * v13: MERGED firmware. Added wireless_default_mode to select whether the
 *      controller defaults to Dongle mode or Bluetooth HID mode when no USB
 *      host is detected. Changed DEVICE_TYPE to "guitar_combined".
 * v14: Added per-effect LED speed fields (loop_speed_ms, breathe_speed_ms, wave_speed_ms).
 * v15: Added start_hold_enabled / start_hold_ms — optional hold-to-activate for START button.
 */

#ifndef _GUITAR_CONFIG_H_
#define _GUITAR_CONFIG_H_

#include <stdint.h>
#include <stdbool.h>
#include "apa102_leds.h"

#define CONFIG_MAGIC              0x47554954  // "GUIT"
#define CONFIG_VERSION            16
#define DEVICE_NAME_MAX           31          // + null terminator = 32 bytes

// ── Device type identifier (sent as DEVTYPE: in GET_CONFIG response) ──
// "guitar_combined" tells the configurator this firmware supports both
// Dongle and Bluetooth HID wireless modes, selectable via wireless_default_mode.
#define DEVICE_TYPE               "guitar_combined"

// ── Input modes for tilt and whammy ──
#define INPUT_MODE_DIGITAL        0   // On/off switch (GPIO pull-up, active low)
#define INPUT_MODE_ANALOG         1   // Analog voltage via ADC (GP26-28)
#define INPUT_MODE_I2C_ADXL345    2   // I2C accelerometer: ADXL345 / GY-291
#define INPUT_MODE_I2C_LIS3DH     3   // I2C accelerometer: LIS3DH

// ── I2C accelerometer model selection ──
#define I2C_MODEL_ADXL345         0
#define I2C_MODEL_LIS3DH          1

// ── Wireless default mode (wireless_default_mode field) ──
// Controls which wireless mode is used after boot when no USB host is detected.
// Can be overridden temporarily via GUIDE button hold (dongle→BT only).
#define WIRELESS_DEFAULT_DONGLE      0   // Default: connect to USB dongle via BLE
#define WIRELESS_DEFAULT_BLUETOOTH   1   // Default: pair directly over Bluetooth HID

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
    BTN_IDX_COUNT           // = 14
} button_index_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;

    int8_t   pin_buttons[BTN_IDX_COUNT];  // 14 buttons, -1 = disabled

    uint8_t  tilt_mode;              // INPUT_MODE_DIGITAL/ANALOG/I2C_ADXL345
    int8_t   pin_tilt_digital;
    int8_t   pin_tilt_analog;

    uint8_t  whammy_mode;            // INPUT_MODE_DIGITAL/ANALOG (I2C not used for whammy)
    int8_t   pin_whammy_digital;
    int8_t   pin_whammy_analog;

    uint8_t  debounce_ms;

    // ── I2C configuration (for I2C accelerometer tilt) ──
    int8_t   pin_i2c_sda;           // I2C0 SDA pin (default GP20)
    int8_t   pin_i2c_scl;           // I2C0 SCL pin (default GP21)
    uint8_t  adxl345_axis;          // 0=X, 1=Y, 2=Z — which axis maps to tilt
    uint8_t  i2c_model;             // I2C_MODEL_ADXL345 or I2C_MODEL_LIS3DH

    // ── Analog sensitivity / calibration ──
    uint16_t tilt_min;
    uint16_t tilt_max;
    uint16_t whammy_min;
    uint16_t whammy_max;

    // ── Axis inversion ──
    uint8_t  tilt_invert;
    uint8_t  whammy_invert;

    // ── 5-pin analog joystick ──
    int8_t   pin_joy_x;
    int8_t   pin_joy_y;
    int8_t   pin_joy_sw;
    uint8_t  joy_whammy_axis;
    uint8_t  joy_dpad_x;
    uint8_t  joy_dpad_y;
    uint8_t  joy_dpad_x_invert;
    uint8_t  joy_dpad_y_invert;
    uint16_t joy_deadzone;

    // ── LED configuration (APA102 / SK9822 / Dotstar) ──
    led_config_t leds;

    // ── Custom device name ──
    char device_name[DEVICE_NAME_MAX + 1];  // 32 bytes, null-terminated

    // ── Analog smoothing (EMA filter) ──
    uint8_t  ema_alpha;

    // ── Dongle sync button ──
    // GPIO pin for the "Start sync" button in wireless dongle mode.
    // Active low (button connects GPIO to GND). -1 = disabled.
    int8_t   sync_pin;              // Default 15

    // ── Wireless default mode (v13) ──
    // WIRELESS_DEFAULT_DONGLE (0)     : boot into Dongle BLE mode
    // WIRELESS_DEFAULT_BLUETOOTH (1)  : boot into Bluetooth HID mode
    // While in Dongle mode, holding GUIDE for 3 seconds reboots into BT HID
    // mode as a one-time override (does not change this stored setting).
    uint8_t  wireless_default_mode;

    // ── START button hold-to-activate ──
    uint8_t  start_hold_enabled;    // 1 = require hold before START registers
    uint16_t start_hold_ms;         // hold duration in ms (default 500)

    uint32_t checksum;
} guitar_config_t;

void config_load(guitar_config_t *config);
void config_save(const guitar_config_t *config);
void config_set_defaults(guitar_config_t *config);
bool config_is_valid(const guitar_config_t *config);
void config_update_checksum(guitar_config_t *config);

#endif
