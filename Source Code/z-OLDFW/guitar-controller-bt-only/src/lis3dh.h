/*
 * lis3dh.h - LIS3DH Accelerometer I2C Driver
 *
 * Supports standard LIS3DH breakout boards (e.g. Adafruit, SparkFun, generic).
 * Uses RP2040 hardware I2C0 with configurable SDA/SCL pins.
 *
 * The LIS3DH outputs signed 12-bit values (left-justified in 16-bit words):
 *   ±2g range, high-resolution mode → 1g ≈ 1024 LSB (after right-shift by 4)
 *   Range: -2048 to +2047
 *   At rest face-up: X≈0, Y≈0, Z≈+1024 (1g)
 *
 * Raw values are scaled to 0-4095 to match ADC range for uniform
 * handling with analog inputs in the rest of the firmware.
 *
 * I2C addresses (set by SDO/SA0 pin on the breakout board):
 *   0x18 — SDO → GND  (default on most boards)
 *   0x19 — SDO → VCC
 */

#ifndef _LIS3DH_H_
#define _LIS3DH_H_

#include <stdint.h>
#include <stdbool.h>

// LIS3DH I2C addresses
#define LIS3DH_ADDR_LOW    0x18   // SDO → GND (default on most boards)
#define LIS3DH_ADDR_HIGH   0x19   // SDO → VCC

// Axis selection — same values as ADXL345 for uniform use in config
#define LIS3DH_AXIS_X  0
#define LIS3DH_AXIS_Y  1
#define LIS3DH_AXIS_Z  2

// Initialize the I2C bus and configure the LIS3DH.
// Returns true if the device was found and configured.
bool lis3dh_init(int8_t sda_pin, int8_t scl_pin);

// Probe for a LIS3DH on the given pins without full init.
// Useful for auto-detection during scan. Always tears down I2C after probing.
bool lis3dh_detect(int8_t sda_pin, int8_t scl_pin);

// Read all three axes. Returns raw 12-bit signed values (right-justified).
// Returns true on success.
bool lis3dh_read_xyz(int16_t *x, int16_t *y, int16_t *z);

// Read a single axis. Returns raw 12-bit signed value (right-justified).
// axis: 0=X, 1=Y, 2=Z. Returns 0 on error.
int16_t lis3dh_read_axis(uint8_t axis);

// Scale a raw 12-bit axis value to 0-4095 (matching ADC range).
// Identical mapping to adxl345_to_adc_scale so the two chips are
// interchangeable in the rest of the firmware.
uint16_t lis3dh_to_adc_scale(int16_t raw);

// Returns true if the driver has been successfully initialized.
bool lis3dh_is_ready(void);

// Release I2C pins so they can be used for other purposes.
void lis3dh_deinit(void);

#endif /* _LIS3DH_H_ */
