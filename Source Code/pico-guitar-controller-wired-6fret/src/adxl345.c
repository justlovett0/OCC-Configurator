/*
 * adxl345.c - ADXL345 Accelerometer I2C Driver
 *
 * Uses RP2040 hardware I2C0 with configurable SDA/SCL pins.
 * Configured for ±2g range, full resolution (10-bit).
 *
 * The ADXL345 outputs signed 10-bit values:
 *   ±2g range → ~256 LSB/g
 *   Range: -512 to +511
 *   At rest face-up: X≈0, Y≈0, Z≈+256 (1g)
 *
 * We scale the raw tilt axis to 0-4095 to match ADC range,
 * so the rest of the firmware treats it uniformly.
 */

#include "adxl345.h"
#include "hardware/i2c.h"
#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include <string.h>

// ADXL345 register addresses
#define REG_DEVID          0x00
#define REG_BW_RATE        0x2C
#define REG_POWER_CTL      0x2D
#define REG_DATA_FORMAT    0x31
#define REG_DATAX0         0x32   // 6 bytes: X0,X1, Y0,Y1, Z0,Z1

#define ADXL345_DEVID      0xE5   // Fixed device ID

#define I2C_INST           i2c0
#define I2C_BAUD           100000  // 100 kHz (standard mode — more compatible with clone boards)
#define I2C_TIMEOUT_US     10000

static bool     _initialized = false;
static uint8_t  _addr = ADXL345_ADDR_LOW;
static int8_t   _sda_pin = -1;
static int8_t   _scl_pin = -1;

// ── Internal helpers ────────────────────────────────────

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
    uint8_t devid = 0;
    uint8_t reg = REG_DEVID;
    _addr = addr;
    int ret = i2c_write_timeout_us(I2C_INST, addr, &reg, 1, true, I2C_TIMEOUT_US);
    if (ret != 1) return false;
    ret = i2c_read_timeout_us(I2C_INST, addr, &devid, 1, false, I2C_TIMEOUT_US);
    if (ret != 1) return false;
    return (devid == ADXL345_DEVID);
}

static bool init_i2c_pins(int8_t sda, int8_t scl) {
    // Validate pins — must be valid I2C0 SDA/SCL pairs
    // I2C0 SDA: GP0, GP4, GP8, GP12, GP16, GP20
    // I2C0 SCL: GP1, GP5, GP9, GP13, GP17, GP21
    if (sda < 0 || scl < 0) return false;

    // Deinit first to handle re-initialization safely (e.g. after adxl345_detect).
    // i2c_deinit is safe to call even if the peripheral is not running.
    i2c_deinit(I2C_INST);

    // Reset pin functions before re-assigning (avoids glitches on repeated calls)
    if (_sda_pin >= 0) gpio_set_function(_sda_pin, GPIO_FUNC_NULL);
    if (_scl_pin >= 0) gpio_set_function(_scl_pin, GPIO_FUNC_NULL);

    // ── I2C bus recovery ────────────────────────────────────────────────
    // If the Pico rebooted (e.g. via watchdog) while the ADXL345 was mid-
    // transaction, the sensor may be holding SDA low waiting for more clock
    // pulses to finish the byte it was sending. The hardware I2C peripheral
    // cannot recover from this on its own — i2c_init() will just see a stuck
    // bus and every subsequent transaction will time out.
    //
    // The I2C spec recovery procedure: drive SCL manually up to 9 times until
    // SDA goes high, then issue a STOP condition (SDA low→high while SCL high).
    // After this the bus is idle and the peripheral can take over normally.
    {
        // Briefly take pins as plain GPIO outputs
        gpio_init(scl);
        gpio_init(sda);
        gpio_set_dir(scl, GPIO_OUT);
        gpio_set_dir(sda, GPIO_IN);   // read SDA, don't drive it
        gpio_pull_up(sda);
        gpio_pull_up(scl);

        gpio_put(scl, 1);
        sleep_us(5);

        // Clock SCL up to 9 times until SDA reads high
        for (int i = 0; i < 9; i++) {
            if (gpio_get(sda)) break;   // SDA released — bus is free
            gpio_put(scl, 0);
            sleep_us(5);
            gpio_put(scl, 1);
            sleep_us(5);
        }

        // Issue a STOP condition: SDA low → high while SCL is high
        gpio_set_dir(sda, GPIO_OUT);
        gpio_put(sda, 0);
        sleep_us(5);
        gpio_put(scl, 1);
        sleep_us(5);
        gpio_put(sda, 1);
        sleep_us(5);

        // Release both pins back to inputs before the peripheral claims them
        gpio_set_dir(sda, GPIO_IN);
        gpio_set_dir(scl, GPIO_IN);
        sleep_us(10);
    }
    // ── End bus recovery ────────────────────────────────────────────────

    i2c_init(I2C_INST, I2C_BAUD);
    gpio_set_function(sda, GPIO_FUNC_I2C);
    gpio_set_function(scl, GPIO_FUNC_I2C);
    gpio_pull_up(sda);
    gpio_pull_up(scl);

    _sda_pin = sda;
    _scl_pin = scl;
    return true;
}

// ── Public API ──────────────────────────────────────────

bool adxl345_detect(int8_t sda_pin, int8_t scl_pin) {
    if (!init_i2c_pins(sda_pin, scl_pin)) return false;

    // Try both possible addresses
    bool found = false;
    if (try_address(ADXL345_ADDR_LOW)) {
        found = true;
    } else if (try_address(ADXL345_ADDR_HIGH)) {
        found = true;
    }

    // Always tear down after a probe — the caller will call adxl345_init() if needed.
    // Reset _initialized so the next adxl345_init() does a full setup.
    i2c_deinit(I2C_INST);
    _initialized = false;
    return found;
}

bool adxl345_init(int8_t sda_pin, int8_t scl_pin) {
    // If already initialized on the same pins, just verify the device is still alive.
    if (_initialized && _sda_pin == sda_pin && _scl_pin == scl_pin) {
        uint8_t devid = 0;
        if (i2c_read_reg(REG_DEVID, &devid, 1) && devid == ADXL345_DEVID)
            return true;
        // Device lost — fall through to full re-init
        _initialized = false;
    }

    // Always fully re-initialize I2C (handles: first call, pin change, detect→init sequence)
    if (!init_i2c_pins(sda_pin, scl_pin)) return false;

    // ADXL345 needs up to 1.4 ms after power-on before the I2C bus is ready.
    // In practice we add a small guard delay here.
    sleep_ms(2);

    // Try both addresses
    bool found = false;
    if (try_address(ADXL345_ADDR_LOW)) {
        found = true;
    } else if (try_address(ADXL345_ADDR_HIGH)) {
        found = true;
    }

    if (!found) {
        i2c_deinit(I2C_INST);
        return false;
    }

    // Configure the ADXL345:
    // 1. Set data rate to 100 Hz (0x0A)
    if (!i2c_write_reg(REG_BW_RATE, 0x0A)) goto fail;

    // 2. Set data format: ±2g range, FULL_RES (bit3), right-justified.
    //    0x08 = FULL_RES enabled. In ±2g this gives the same 10-bit range as
    //    0x00 but scales correctly if the range is ever widened.
    if (!i2c_write_reg(REG_DATA_FORMAT, 0x08)) goto fail;

    // 3. Enable measurement mode (exit standby)
    if (!i2c_write_reg(REG_POWER_CTL, 0x08)) goto fail;

    // Allow the first batch of measurements to stabilise
    sleep_ms(20);

    _initialized = true;
    return true;

fail:
    i2c_deinit(I2C_INST);
    return false;
}

bool adxl345_read_xyz(int16_t *x, int16_t *y, int16_t *z) {
    if (!_initialized) return false;

    uint8_t buf[6];
    if (!i2c_read_reg(REG_DATAX0, buf, 6)) return false;

    // Data is little-endian, 10-bit signed
    *x = (int16_t)(buf[0] | (buf[1] << 8));
    *y = (int16_t)(buf[2] | (buf[3] << 8));
    *z = (int16_t)(buf[4] | (buf[5] << 8));
    return true;
}

int16_t adxl345_read_axis(uint8_t axis) {
    int16_t x, y, z;
    if (!adxl345_read_xyz(&x, &y, &z)) return 0;
    switch (axis) {
        case ADXL345_AXIS_X: return x;
        case ADXL345_AXIS_Y: return y;
        case ADXL345_AXIS_Z: return z;
        default:             return 0;
    }
}

uint16_t adxl345_to_adc_scale(int16_t raw) {
    // ADXL345 ±2g range: raw is roughly -512 to +511
    // Map to 0-4095 (12-bit ADC scale)
    //   raw = -512 → 0
    //   raw = 0    → 2048
    //   raw = +511 → 4095
    int32_t scaled = ((int32_t)raw + 512) * 4095 / 1023;
    if (scaled < 0)    scaled = 0;
    if (scaled > 4095) scaled = 4095;
    return (uint16_t)scaled;
}

bool adxl345_is_ready(void) {
    return _initialized;
}

void adxl345_deinit(void) {
    if (_initialized) {
        // Put into standby
        i2c_write_reg(REG_POWER_CTL, 0x00);
        i2c_deinit(I2C_INST);
        _initialized = false;
    }
}
