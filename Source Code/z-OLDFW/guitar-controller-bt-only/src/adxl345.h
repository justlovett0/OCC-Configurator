/*
 * adxl345.h - ADXL345 Accelerometer I2C Driver
 *
 * Supports GY-291 / GY-ADXL345 daughterboards.
 * Uses RP2040 hardware I2C with configurable SDA/SCL pins.
 *
 * Default I2C0: SDA=GP4, SCL=GP5
 * (GP3/GP6 are reserved for LED SPI, so we avoid those)
 */

#ifndef _ADXL345_H_
#define _ADXL345_H_

#include <stdint.h>
#include <stdbool.h>

// ADXL345 I2C addresses (depends on SDO pin)
#define ADXL345_ADDR_LOW   0x53   // SDO → GND (default on most boards)
#define ADXL345_ADDR_HIGH  0x1D   // SDO → VCC

// Default I2C pins (avoid GP3/GP6 used by LED SPI)
#define DEFAULT_I2C_SDA_PIN  4
#define DEFAULT_I2C_SCL_PIN  5

// Axis selection
#define ADXL345_AXIS_X  0
#define ADXL345_AXIS_Y  1
#define ADXL345_AXIS_Z  2

// Initialize the I2C bus and configure the ADXL345
// Returns true if the device was found and configured
bool adxl345_init(int8_t sda_pin, int8_t scl_pin);

// Probe for an ADXL345 on the given pins without full init
// Useful for auto-detection during scan
bool adxl345_detect(int8_t sda_pin, int8_t scl_pin);

// Read all three axes (raw 10-bit signed values, ±2g range)
// Returns true on success
bool adxl345_read_xyz(int16_t *x, int16_t *y, int16_t *z);

// Read a single axis, returns raw signed value
// axis: 0=X, 1=Y, 2=Z
// Returns 0 on error
int16_t adxl345_read_axis(uint8_t axis);

// Scale raw value to 0-4095 range (matching ADC scale)
// for uniform handling with analog inputs
uint16_t adxl345_to_adc_scale(int16_t raw);

// Check if the driver has been successfully initialized
bool adxl345_is_ready(void);

// Deinitialize — release I2C pins so they can be used for other purposes
void adxl345_deinit(void);

#endif /* _ADXL345_H_ */
