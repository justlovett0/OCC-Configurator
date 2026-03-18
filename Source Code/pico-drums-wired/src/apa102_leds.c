/*
 * apa102_leds.c - APA102 / SK9822 / Dotstar / APA107 LED driver
 *
 * Uses RP2040 hardware SPI0 with DMA for non-blocking transfers.
 * GP3 = SPI0 TX (MOSI / DI), GP6 = SPI0 SCK (CI).
 *
 * DMA sends the LED frame in the background so the CPU returns
 * immediately and USB interrupt/task handling is never starved.
 *
 * Double-buffered: while DMA reads from one buffer, the CPU can
 * prepare the next frame in the other buffer.
 */

#include "apa102_leds.h"
#include "pico/stdlib.h"
#include "hardware/spi.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include <string.h>

#define LED_SPI_INST    spi0
#define LED_SPI_BAUD    4000000  // 4 MHz — well within APA102 spec

// Max frame: 4 (start) + 16*4 (LEDs) + 4 (end) = 72 bytes, pad to 76
#define LED_BUF_SIZE    76

static bool     spi_initialized = false;
static int      dma_chan = -1;
static bool     dma_initialized = false;

// Double buffers — DMA reads from one while CPU writes the other
static uint8_t  led_buf[2][LED_BUF_SIZE];
static uint8_t  active_buf = 0;        // Which buffer DMA is currently sending
static bool     dma_busy = false;       // Is a DMA transfer in flight?

// ── LED loop (color rotation) state ─────────────────────────────────────────
// The loop rotates the configured colors of LEDs [loop_start..loop_end] by
// one position every second, with a smooth integer crossfade at 60 Hz.
//
// loop_phase: which slot's color is currently shown at loop_start.
//             Advances by 1 (mod loop_len) each time a full second elapses.
// loop_last_step_us: time_us_32() value when the current step began.
// loop_colors[][3]: current interpolated RGB for each LED in the loop range,
//                   indexed 0..(loop_len-1).  Written every call so the
//                   caller can substitute them into the frame.
static uint8_t  loop_phase        = 0;
static uint32_t loop_last_step_us = 0;
static bool     loop_seeded       = false;
static uint8_t  loop_colors[MAX_LEDS][3];  // interpolated output

// ── Internal helpers ────────────────────────────────────

// Wait for any in-flight DMA to finish (used only by blocking calls
// like apa102_flash_led and apa102_all_off where we must guarantee
// the transfer is complete before returning).
static void wait_for_dma(void) {
    if (!dma_busy || dma_chan < 0) return;
    dma_channel_wait_for_finish_blocking(dma_chan);
    dma_busy = false;
}

// Build an APA102 frame into the given buffer.
// Returns the number of bytes written.
static uint16_t build_frame(uint8_t *buf, const led_config_t *cfg,
                            const uint8_t *brightness) {
    uint8_t count = cfg->count;
    if (count > MAX_LEDS) count = MAX_LEDS;

    uint16_t pos = 0;

    // Start frame: 4 bytes of 0x00
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;

    // LED frames: [0xE0 | brightness] [blue] [green] [red]
    for (int i = 0; i < count; i++) {
        buf[pos++] = 0xE0 | (brightness[i] & 0x1F);
        buf[pos++] = cfg->colors[i].b;
        buf[pos++] = cfg->colors[i].g;
        buf[pos++] = cfg->colors[i].r;
    }

    // End frame: at least ceil(count/16) + 1 bytes of 0xFF
    uint8_t end_bytes = (count / 16) + 1;
    for (int i = 0; i < end_bytes; i++) {
        buf[pos++] = 0xFF;
    }

    return pos;
}

// Kick off a DMA transfer from the given buffer.
static void start_dma_transfer(const uint8_t *buf, uint16_t len) {
    if (dma_chan < 0) return;

    // If previous transfer is still going, wait for it.
    // (Should be rare — 76 bytes @ 4MHz = ~152us, and we call at 60Hz = 16ms apart)
    if (dma_busy) {
        dma_channel_wait_for_finish_blocking(dma_chan);
    }

    dma_busy = true;
    dma_channel_set_read_addr(dma_chan, buf, false);
    dma_channel_set_trans_count(dma_chan, len, true);  // true = start immediately
}

// ── Public API ──────────────────────────────────────────

void apa102_init(void) {
    if (spi_initialized) return;

    // Init SPI peripheral
    spi_init(LED_SPI_INST, LED_SPI_BAUD);
    spi_set_format(LED_SPI_INST, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);

    gpio_set_function(LED_SPI_DI_PIN, GPIO_FUNC_SPI);   // GP3 = SPI0 TX
    gpio_set_function(LED_SPI_SCK_PIN, GPIO_FUNC_SPI);   // GP6 = SPI0 SCK

    spi_initialized = true;

    // Init DMA channel
    if (!dma_initialized) {
        dma_chan = dma_claim_unused_channel(false);
        if (dma_chan >= 0) {
            dma_channel_config c = dma_channel_get_default_config(dma_chan);
            channel_config_set_transfer_data_size(&c, DMA_SIZE_8);
            channel_config_set_read_increment(&c, true);    // Read from buffer
            channel_config_set_write_increment(&c, false);  // Write to fixed SPI DR
            channel_config_set_dreq(&c, spi_get_dreq(LED_SPI_INST, true));  // TX DREQ

            dma_channel_configure(
                dma_chan,
                &c,
                &spi_get_hw(LED_SPI_INST)->dr,  // Write address: SPI data register
                NULL,                             // Read address: set per transfer
                0,                                // Transfer count: set per transfer
                false                             // Don't start yet
            );

            dma_initialized = true;
        }
        // If DMA claim failed, dma_chan stays -1 and we fall back to blocking
    }
}

void apa102_update(const led_config_t *cfg, const uint8_t *brightness) {
    if (!cfg->enabled || cfg->count == 0 || !spi_initialized) return;

    // Build frame into the back buffer (not the one DMA might be reading)
    uint8_t back = 1 - active_buf;
    uint16_t len = build_frame(led_buf[back], cfg, brightness);

    if (dma_chan >= 0) {
        // Non-blocking DMA send
        start_dma_transfer(led_buf[back], len);
        active_buf = back;  // Swap buffers
    } else {
        // Fallback: blocking SPI (shouldn't happen normally, but safe)
        spi_write_blocking(LED_SPI_INST, led_buf[back], len);
    }
}

// ── LED loop update ──────────────────────────────────────────────────────────
// Called every frame (~60 Hz) from apa102_update_from_inputs().
// Computes the crossfaded color for each LED in the loop range and stores
// results in loop_colors[0..len-1].
//
// Timing: uses integer fixed-point (t in 0..255 maps 0.0..1.0 within 1 s).
// No floating point — safe on RP2040 without FPU penalty in tight loops.
static void update_loop_colors(const led_config_t *cfg) {
    uint8_t start = cfg->loop_start;
    uint8_t end   = cfg->loop_end;

    // Validate range
    if (start > end || end >= cfg->count || end >= MAX_LEDS) return;
    uint8_t len = end - start + 1;
    if (len < 2) return;

    uint32_t now = time_us_32();

    if (!loop_seeded) {
        loop_phase        = 0;
        loop_last_step_us = now;
        loop_seeded       = true;
    }

    // How far through the current 1-second step are we? (0..255)
    uint32_t elapsed = now - loop_last_step_us;
    if (elapsed >= 1000000u) {
        // Step complete — advance phase
        loop_phase = (uint8_t)((loop_phase + 1) % len);
        loop_last_step_us = now;
        elapsed = 0;
    }
    uint32_t t256 = (elapsed * 256u) / 1000000u;  // 0..255

    // Compute interpolated color for each slot in the loop
    for (uint8_t i = 0; i < len; i++) {
        // Source color: config color at (phase + i) % len, relative to loop_start
        uint8_t cur_slot  = (uint8_t)((loop_phase + i)     % len);
        uint8_t next_slot = (uint8_t)((loop_phase + i + 1) % len);

        const led_color_t *cur  = &cfg->colors[start + cur_slot];
        const led_color_t *next = &cfg->colors[start + next_slot];

        // Linear interpolate each channel: out = cur + t256*(next-cur)/256
        // Use signed arithmetic to handle next < cur correctly.
        loop_colors[i][0] = (uint8_t)((int)cur->r + (int)((((int)next->r - (int)cur->r) * (int)t256) / 256));
        loop_colors[i][1] = (uint8_t)((int)cur->g + (int)((((int)next->g - (int)cur->g) * (int)t256) / 256));
        loop_colors[i][2] = (uint8_t)((int)cur->b + (int)((((int)next->b - (int)cur->b) * (int)t256) / 256));
    }
}

void apa102_update_from_inputs(const led_config_t *cfg, uint16_t pressed_mask) {
    if (!cfg->enabled || cfg->count == 0) return;

    uint8_t count = cfg->count;
    if (count > MAX_LEDS) count = MAX_LEDS;

    uint8_t brightness[MAX_LEDS];
    for (int i = 0; i < count; i++) {
        brightness[i] = cfg->base_brightness;
    }

    for (int inp = 0; inp < LED_INPUT_COUNT; inp++) {
        if (!(pressed_mask & (1u << inp))) continue;
        uint16_t mask = cfg->led_map[inp];
        if (mask == 0) continue;
        for (int led = 0; led < count; led++) {
            if (mask & (1u << led)) {
                uint8_t ab = cfg->active_brightness[inp];
                if (ab > brightness[led]) {
                    brightness[led] = ab;
                }
            }
        }
    }

    // ── LED loop: substitute interpolated colors for loop LEDs ──────────────
    // We make a shallow copy of the config and patch the colors[] entries for
    // the loop range so that apa102_update() renders them with crossfaded hues.
    if (cfg->loop_enabled &&
        cfg->loop_start <= cfg->loop_end &&
        cfg->loop_end < count)
    {
        update_loop_colors(cfg);

        // Stack-copy only the colors array (rest of the struct is read-only here)
        led_color_t patched_colors[MAX_LEDS];
        for (int i = 0; i < count; i++) {
            patched_colors[i] = cfg->colors[i];
        }

        uint8_t start = cfg->loop_start;
        uint8_t end   = cfg->loop_end;
        uint8_t len   = end - start + 1;
        for (int i = 0; i < len; i++) {
            patched_colors[start + i].r = loop_colors[i][0];
            patched_colors[start + i].g = loop_colors[i][1];
            patched_colors[start + i].b = loop_colors[i][2];
        }

        // Build a temporary config view pointing at our patched colors.
        // We copy the whole struct (it's small, ~100 bytes) so the pointer
        // to colors[] is valid for the duration of this call.
        led_config_t tmp = *cfg;
        for (int i = 0; i < MAX_LEDS; i++) {
            tmp.colors[i] = patched_colors[i];
        }
        apa102_update(&tmp, brightness);
    } else {
        apa102_update(cfg, brightness);
    }
}

void apa102_all_off(const led_config_t *cfg) {
    if (!spi_initialized) return;

    uint8_t count = cfg->count;
    if (count == 0) return;
    if (count > MAX_LEDS) count = MAX_LEDS;

    // Must be synchronous — caller expects LEDs are off when we return
    wait_for_dma();

    uint8_t *buf = led_buf[0];
    uint16_t pos = 0;

    buf[pos++] = 0x00;
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;
    buf[pos++] = 0x00;

    for (int i = 0; i < count; i++) {
        buf[pos++] = 0xE0;
        buf[pos++] = 0x00;
        buf[pos++] = 0x00;
        buf[pos++] = 0x00;
    }

    uint8_t end_bytes = (count / 16) + 1;
    for (int i = 0; i < end_bytes; i++) {
        buf[pos++] = 0xFF;
    }

    spi_write_blocking(LED_SPI_INST, buf, pos);
}

void apa102_flash_led(const led_config_t *cfg, uint8_t led_idx, uint8_t blink_count) {
    uint8_t count = cfg->count;
    if (count == 0) return;
    if (count > MAX_LEDS) count = MAX_LEDS;
    if (led_idx >= count) return;

    apa102_init();

    // Flash is inherently blocking (sleep_ms between blinks)
    // so we wait for any DMA and use blocking SPI directly
    wait_for_dma();

    for (int blink = 0; blink < blink_count; blink++) {
        uint8_t brightness[MAX_LEDS];
        memset(brightness, 0, sizeof(brightness));
        brightness[led_idx] = 31;

        uint16_t len = build_frame(led_buf[0], cfg, brightness);
        spi_write_blocking(LED_SPI_INST, led_buf[0], len);
        sleep_ms(300);

        memset(brightness, 0, sizeof(brightness));
        len = build_frame(led_buf[0], cfg, brightness);
        spi_write_blocking(LED_SPI_INST, led_buf[0], len);
        sleep_ms(200);
    }
}
