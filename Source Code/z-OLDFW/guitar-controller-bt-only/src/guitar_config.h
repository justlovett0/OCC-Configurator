/*
 * guitar_config.h - GPIO-to-button mapping + LED + device name + I2C
 *
 * v5: Added I2C accelerometer (ADXL345) support for tilt.
 * v6: Added per-input sensitivity (min/max ADC range) for tilt and whammy.
 * v7: Added LED loop (color rotation) feature.
 * v8: Added 5-pin analog joystick support.
 * v9: Added joy_dpad_x/y_invert fields (struct unchanged from v8 size).
 * v10: Added i2c_model field to select accelerometer chip (ADXL345 / LIS3DH).
 *      Bumped CONFIG_VERSION to force defaults reset on first boot after update.
 * v11: Added ema_alpha field for user-configurable analog smoothing strength.
 */

#ifndef _GUITAR_CONFIG_H_
#define _GUITAR_CONFIG_H_

#include <stdint.h>
#include <stdbool.h>
#include "apa102_leds.h"

#define CONFIG_MAGIC              0x47554954  // "GUIT"
#define CONFIG_VERSION            11
#define DEVICE_NAME_MAX           31          // + null terminator = 32 bytes

// ── Device type identifier (sent as DEVTYPE: in GET_CONFIG response) ──
#define DEVICE_TYPE               "guitar_alternate"

// ── Input modes for tilt and whammy ──
#define INPUT_MODE_DIGITAL        0   // On/off switch (GPIO pull-up, active low)
#define INPUT_MODE_ANALOG         1   // Analog voltage via ADC (GP26-28)
#define INPUT_MODE_I2C_ADXL345    2   // I2C accelerometer: ADXL345 / GY-291
#define INPUT_MODE_I2C_LIS3DH     3   // I2C accelerometer: LIS3DH
// To add a new chip: define INPUT_MODE_I2C_<NAME> here, add a driver,
// and handle it in main.c (init_i2c_tilt / build_report) and config_serial.c.

// ── I2C accelerometer model selection ──
// Stored as i2c_model in the config struct. Used when tilt_mode is
// INPUT_MODE_I2C_ADXL345 or INPUT_MODE_I2C_LIS3DH.
#define I2C_MODEL_ADXL345         0
#define I2C_MODEL_LIS3DH          1

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
    // Raw ADC values (0–4095) clamped to [min, max] then remapped to full range.
    // Set min=0, max=4095 for no scaling (default).
    uint16_t tilt_min;              // ADC value that maps to axis minimum
    uint16_t tilt_max;              // ADC value that maps to axis maximum
    uint16_t whammy_min;            // ADC value that maps to whammy minimum
    uint16_t whammy_max;            // ADC value that maps to whammy maximum

    // ── Axis inversion ──
    uint8_t  tilt_invert;           // 1 = flip axis so max ADC → -32768, min ADC → +32767
    uint8_t  whammy_invert;         // 1 = flip whammy axis

    // ── 5-pin analog joystick ──
    // VRx/VRy connect to ADC pins (GP26–28). SW click is a digital GPIO.
    // joy_whammy_axis: 0=none, 1=X axis drives whammy, 2=Y axis drives whammy.
    //   Both + and - deflection produce whammy output (bi-directional → unipolar).
    //   At rest (within deadzone) = no whammy input.
    // joy_dpad_x: 1 → X+ = DPad-Right, X- = DPad-Left.
    // joy_dpad_y: 1 → Y+ = DPad-Down,  Y- = DPad-Up.
    // joy_dpad_x_invert: flip X DPad (1 → X+ = DPad-Left, X- = DPad-Right).
    // joy_dpad_y_invert: flip Y DPad (1 → Y+ = DPad-Up,   Y- = DPad-Down).
    // joy_deadzone: raw deviation from centre (2048) before any axis activates.
    //   Default 205 ≈ 5% of 4095 full scale.
    // pin_joy_sw maps to the Guide button when pressed.
    int8_t   pin_joy_x;             // ADC pin for VRx, -1 = disabled
    int8_t   pin_joy_y;             // ADC pin for VRy, -1 = disabled
    int8_t   pin_joy_sw;            // Digital GPIO for click switch, -1 = disabled
    uint8_t  joy_whammy_axis;       // 0=none, 1=X, 2=Y
    uint8_t  joy_dpad_x;            // bool: X axis → DPad L/R
    uint8_t  joy_dpad_y;            // bool: Y axis → DPad U/D
    uint8_t  joy_dpad_x_invert;     // bool: invert X DPad direction
    uint8_t  joy_dpad_y_invert;     // bool: invert Y DPad direction
    uint16_t joy_deadzone;          // ADC units from centre, default 205

    // ── LED configuration (APA102 / SK9822 / Dotstar) ──
    led_config_t leds;

    // ── Custom device name (shown in Windows joy.cpl etc.) ──
    char device_name[DEVICE_NAME_MAX + 1];  // 32 bytes, null-terminated

    // ── Analog smoothing (EMA filter) ──
    // Slider level 0-9 maps to alpha values via a lookup table in the configurator.
    // Range active: 10–254. Stored 0 = level 0 = alpha 255 (no smoothing).
    // Default 90 = level 4 (responsive and stable).
    uint8_t  ema_alpha;             // EMA alpha; 0 stored means 255 (no smoothing)

    uint32_t checksum;
} guitar_config_t;

void config_load(guitar_config_t *config);
void config_save(const guitar_config_t *config);
void config_set_defaults(guitar_config_t *config);
bool config_is_valid(const guitar_config_t *config);
void config_update_checksum(guitar_config_t *config);

#endif
