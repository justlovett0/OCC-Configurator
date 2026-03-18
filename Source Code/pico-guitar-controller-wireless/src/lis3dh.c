/*
 * lis3dh.c - LIS3DH Accelerometer I2C Driver
 *
 * Uses RP2040 hardware I2C0 with configurable SDA/SCL pins.
 * Configured for ±2g range, high-resolution 12-bit mode, 100 Hz ODR.
 *
 * The LIS3DH outputs left-justified 16-bit values. We right-shift by 4
 * to get 12-bit signed values:
 *   ±2g range → 1g ≈ 1024 LSB
 *   Range: -2048 to +2047
 *   At rest face-up: X≈0, Y≈0, Z≈+1024 (1g)
 *
 * We scale to 0-4095 to match ADC range, so the rest of the firmware
 * treats this chip identically to the ADXL345.
 */

#include "lis3dh.h"
#include "hardware/i2c.h"
#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include <string.h>

// ── LIS3DH register addresses ──────────────────────────────────────
#define REG_WHO_AM_I    0x0F   // Fixed ID register — always reads 0x33
#define REG_CTRL_REG1   0x20   // Output data rate, axes enable
#define REG_CTRL_REG4   0x23   // Full scale, high-res mode, BDU
#define REG_OUT_X_L     0x28   // First of 6 output bytes (XL,XH,YL,YH,ZL,ZH)

// Auto-increment bit — set bit 7 of register address for multi-byte reads
#define AUTO_INC        0x80

#define LIS3DH_WHO_AM_I_VAL  0x33   // Expected WHO_AM_I response

// CTRL_REG1: ODR=100Hz (0101), low-power off, all axes on → 0x57
#define CTRL_REG1_VAL   0x57

// CTRL_REG4: BDU=0, FS=±2g (00), HR=1 (high-res 12-bit) → 0x08
#define CTRL_REG4_VAL   0x08

#define I2C_INST        i2c0
#define I2C_BAUD        100000    // 100 kHz — reliable on all boards
#define I2C_TIMEOUT_US  10000

static bool    _initialized = false;
static uint8_t _addr        = LIS3DH_ADDR_LOW;
static int8_t  _sda_pin     = -1;
static int8_t  _scl_pin     = -1;

// ── Internal helpers ────────────────────────────────────────────────

static bool i2c_write_reg(uint8_t reg, uint8_t value) {
    uint8_t buf[2] = { reg, value };
    int ret = i2c_write_timeout_us(I2C_INST, _addr, buf, 2, false, I2C_TIMEOUT_US);
    return (ret == 2);
}

static bool i2c_read_reg(uint8_t reg, uint8_t *dest, size_t len) {
    int ret = i2c_write_timeout_us(I2C_INST, _addr, &reg, 1, true, I2C_TIMEOUT_US);
    if (ret != 1) return false;
    ret = i2c_read_timeout_us(I2C_INST, _addr, dest, len, false, I2C_TIMEOUT_US);
    return (ret == (int)len);
}

static bool try_address(uint8_t addr) {
    uint8_t who = 0;
    uint8_t reg = REG_WHO_AM_I;
    _addr = addr;
    int ret = i2c_write_timeout_us(I2C_INST, addr, &reg, 1, true, I2C_TIMEOUT_US);
    if (ret != 1) return false;
    ret = i2c_read_timeout_us(I2C_INST, addr, &who, 1, false, I2C_TIMEOUT_US);
    if (ret != 1) return false;
    return (who == LIS3DH_WHO_AM_I_VAL);
}

static bool init_i2c_pins(int8_t sda, int8_t scl) {
    if (sda < 0 || scl < 0) return false;

    i2c_deinit(I2C_INST);

    // Release previously assigned pins before re-assigning
    if (_sda_pin >= 0) gpio_set_function(_sda_pin, GPIO_FUNC_NULL);
    if (_scl_pin >= 0) gpio_set_function(_scl_pin, GPIO_FUNC_NULL);

    // ── I2C bus recovery ──────────────────────────────────────────────
    // If the Pico rebooted mid-transaction (e.g. via watchdog) the LIS3DH
    // may be holding SDA low waiting for clock pulses to finish a byte.
    // Manually clock SCL up to 9 times until SDA releases, then STOP.
    {
        gpio_init(scl);
        gpio_init(sda);
        gpio_set_dir(scl, GPIO_OUT);
        gpio_set_dir(sda, GPIO_IN);
        gpio_pull_up(sda);
        gpio_pull_up(scl);

        gpio_put(scl, 1);
        sleep_us(5);

        for (int i = 0; i < 9; i++) {
            if (gpio_get(sda)) break;
            gpio_put(scl, 0);
            sleep_us(5);
            gpio_put(scl, 1);
            sleep_us(5);
        }

        // STOP condition: SDA low → high while SCL high
        gpio_set_dir(sda, GPIO_OUT);
        gpio_put(sda, 0);
        sleep_us(5);
        gpio_put(scl, 1);
        sleep_us(5);
        gpio_put(sda, 1);
        sleep_us(5);

        gpio_set_dir(sda, GPIO_IN);
        gpio_set_dir(scl, GPIO_IN);
        sleep_us(10);
    }
    // ── End bus recovery ──────────────────────────────────────────────

    i2c_init(I2C_INST, I2C_BAUD);
    gpio_set_function(sda, GPIO_FUNC_I2C);
    gpio_set_function(scl, GPIO_FUNC_I2C);
    gpio_pull_up(sda);
    gpio_pull_up(scl);

    _sda_pin = sda;
    _scl_pin = scl;
    return true;
}

// ── Public API ──────────────────────────────────────────────────────

bool lis3dh_detect(int8_t sda_pin, int8_t scl_pin) {
    if (!init_i2c_pins(sda_pin, scl_pin)) return false;

    bool found = try_address(LIS3DH_ADDR_LOW) ||
                 try_address(LIS3DH_ADDR_HIGH);

    // Tear down after probe — caller calls lis3dh_init() if needed
    i2c_deinit(I2C_INST);
    _initialized = false;
    return found;
}

bool lis3dh_init(int8_t sda_pin, int8_t scl_pin) {
    // Fast path: already initialized on the same pins — verify still alive
    if (_initialized && _sda_pin == sda_pin && _scl_pin == scl_pin) {
        uint8_t who = 0;
        if (i2c_read_reg(REG_WHO_AM_I, &who, 1) && who == LIS3DH_WHO_AM_I_VAL)
            return true;
        _initialized = false;
    }

    if (!init_i2c_pins(sda_pin, scl_pin)) return false;

    // LIS3DH needs ~5 ms after power-on before I2C is ready
    sleep_ms(5);

    bool found = try_address(LIS3DH_ADDR_LOW) ||
                 try_address(LIS3DH_ADDR_HIGH);

    if (!found) {
        i2c_deinit(I2C_INST);
        return false;
    }

    // Configure:
    // CTRL_REG1: 100 Hz ODR, normal mode, all axes enabled
    if (!i2c_write_reg(REG_CTRL_REG1, CTRL_REG1_VAL)) goto fail;

    // CTRL_REG4: ±2g, high-resolution 12-bit, BDU disabled
    if (!i2c_write_reg(REG_CTRL_REG4, CTRL_REG4_VAL)) goto fail;

    // Wait for first batch of measurements to settle
    sleep_ms(20);

    _initialized = true;
    return true;

fail:
    i2c_deinit(I2C_INST);
    return false;
}

bool lis3dh_read_xyz(int16_t *x, int16_t *y, int16_t *z) {
    if (!_initialized) return false;

    // Set auto-increment bit so all 6 bytes are read in one transaction
    uint8_t buf[6];
    uint8_t reg = REG_OUT_X_L | AUTO_INC;
    if (!i2c_read_reg(reg, buf, 6)) return false;

    // Data is little-endian, left-justified 12-bit in a 16-bit word.
    // Right-shift by 4 to get 12-bit signed value in range -2048..+2047.
    *x = (int16_t)((buf[0] | ((uint16_t)buf[1] << 8))) >> 4;
    *y = (int16_t)((buf[2] | ((uint16_t)buf[3] << 8))) >> 4;
    *z = (int16_t)((buf[4] | ((uint16_t)buf[5] << 8))) >> 4;
    return true;
}

int16_t lis3dh_read_axis(uint8_t axis) {
    int16_t x, y, z;
    if (!lis3dh_read_xyz(&x, &y, &z)) return 0;
    switch (axis) {
        case LIS3DH_AXIS_X: return x;
        case LIS3DH_AXIS_Y: return y;
        case LIS3DH_AXIS_Z: return z;
        default:            return 0;
    }
}

uint16_t lis3dh_to_adc_scale(int16_t raw) {
    // LIS3DH ±2g, 12-bit: raw is -2048 to +2047
    // Map to 0-4095 to match ADC scale:
    //   raw = -2048 → 0
    //   raw =     0 → 2048
    //   raw = +2047 → 4095
    int32_t scaled = (int32_t)raw + 2048;
    if (scaled < 0)    scaled = 0;
    if (scaled > 4095) scaled = 4095;
    return (uint16_t)scaled;
}

bool lis3dh_is_ready(void) {
    return _initialized;
}

void lis3dh_deinit(void) {
    if (_initialized) {
        // Power down: clear CTRL_REG1 ODR bits (ODR=0000 = power-down)
        i2c_write_reg(REG_CTRL_REG1, 0x00);
        i2c_deinit(I2C_INST);
        _initialized = false;
    }
}
