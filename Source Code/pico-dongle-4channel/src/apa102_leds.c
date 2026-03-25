/*
 * apa102_leds.c - APA102/SK9822 driver for 4-channel dongle
 *
 * Hardware SPI0 + DMA for non-blocking frame sends.
 * GP3 = SPI0 TX (MOSI/DI), GP6 = SPI0 SCK (CI).
 *
 * Frame layout (APA102):
 *   4 bytes start (0x00)
 *   8 x 4 bytes LED: [0xE0|brightness] [B] [G] [R]
 *   1 byte end (0xFF)
 *   Total = 37 bytes
 */

#include "apa102_leds.h"
#include "pico/stdlib.h"
#include "hardware/spi.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include <string.h>

#define LED_SPI_INST    spi0
#define LED_SPI_BAUD    4000000  // 4 MHz

// 4 start + 8*4 LEDs + 1 end = 37, round up to 40
#define LED_BUF_SIZE    40

static bool spi_initialized = false;
static int  dma_chan        = -1;

// Double buffers — DMA reads one while CPU writes the other
static uint8_t led_buf[2][LED_BUF_SIZE];
static uint8_t active_buf = 0;
static bool    dma_busy   = false;

static void wait_dma(void) {
    if (!dma_busy || dma_chan < 0) return;
    dma_channel_wait_for_finish_blocking(dma_chan);
    dma_busy = false;
}

static void start_dma(const uint8_t *buf, uint16_t len) {
    if (dma_chan < 0) return;
    if (dma_busy) dma_channel_wait_for_finish_blocking(dma_chan);
    dma_busy = true;
    dma_channel_set_read_addr(dma_chan, buf, false);
    dma_channel_set_trans_count(dma_chan, len, true);
}

void apa102_init(void) {
    if (spi_initialized) return;

    spi_init(LED_SPI_INST, LED_SPI_BAUD);
    spi_set_format(LED_SPI_INST, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(LED_SPI_DI_PIN,  GPIO_FUNC_SPI);
    gpio_set_function(LED_SPI_SCK_PIN, GPIO_FUNC_SPI);
    spi_initialized = true;

    dma_chan = dma_claim_unused_channel(false);
    if (dma_chan >= 0) {
        dma_channel_config c = dma_channel_get_default_config(dma_chan);
        channel_config_set_transfer_data_size(&c, DMA_SIZE_8);
        channel_config_set_read_increment(&c, true);
        channel_config_set_write_increment(&c, false);
        channel_config_set_dreq(&c, spi_get_dreq(LED_SPI_INST, true));
        dma_channel_configure(dma_chan, &c,
            &spi_get_hw(LED_SPI_INST)->dr,
            NULL, 0, false);
    }
}

void apa102_write(const uint8_t brightness[DONGLE_LED_COUNT], uint8_t r, uint8_t g, uint8_t b) {
    if (!spi_initialized) return;

    uint8_t back = 1 - active_buf;
    uint8_t *buf = led_buf[back];
    uint16_t pos = 0;

    // Start frame
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;

    // LED frames: [0xE0 | 5-bit brightness] [B] [G] [R]
    for (int i = 0; i < DONGLE_LED_COUNT; i++) {
        buf[pos++] = 0xE0 | (brightness[i] & 0x1F);
        buf[pos++] = b;
        buf[pos++] = g;
        buf[pos++] = r;
    }

    // End frame — 1 byte of 0xFF is enough for 8 LEDs
    buf[pos++] = 0xFF;

    if (dma_chan >= 0) {
        start_dma(buf, pos);
        active_buf = back;
    } else {
        spi_write_blocking(LED_SPI_INST, buf, pos);
    }
}

void apa102_all_off(void) {
    if (!spi_initialized) return;
    wait_dma();

    uint8_t *buf = led_buf[0];
    uint16_t pos = 0;

    buf[pos++] = 0x00; buf[pos++] = 0x00;
    buf[pos++] = 0x00; buf[pos++] = 0x00;

    for (int i = 0; i < DONGLE_LED_COUNT; i++) {
        buf[pos++] = 0xE0;
        buf[pos++] = 0x00;
        buf[pos++] = 0x00;
        buf[pos++] = 0x00;
    }
    buf[pos++] = 0xFF;

    spi_write_blocking(LED_SPI_INST, buf, pos);
}
