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
static uint8_t  loop_phase        = 0;
static uint32_t loop_last_step_us = 0;
static bool     loop_seeded       = false;
static uint8_t  loop_colors[MAX_LEDS][3];  // interpolated output

// ── LED breathe state ────────────────────────────────────────────────────────
// Triangle-wave oscillator between breathe_min_bright and breathe_max_bright.
// Period: 3 seconds (1.5 s up, 1.5 s down).  Uses delta accumulation so
// time_us_32() wrap-around is handled correctly.
#define BREATHE_PERIOD_US 3000000u
static uint32_t breathe_phase_us = 0;
static uint32_t breathe_last_us  = 0;
static bool     breathe_seeded   = false;

// ── LED wave state ───────────────────────────────────────────────────────────
// Rising-edge triggered pulses.  Up to WAVE_MAX_ACTIVE simultaneous waves.
// Each wave front travels outward from wave_origin at ~24 LEDs/sec
// (41.7 ms per LED).  Each LED peaks at brightness 31 then fades to
// base_brightness over 100 ms.
#define WAVE_US_PER_LED  41667u
#define WAVE_FADE_US     100000u
#define WAVE_MAX_ACTIVE  4
typedef struct { bool active; uint32_t start_us; } wave_t;
static wave_t   waves[WAVE_MAX_ACTIVE];
static uint16_t wave_prev_mask = 0xFFFFu; // init high: avoids spurious trigger on first frame

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

// ── Breathe brightness ───────────────────────────────────────────────────────
// Returns the instantaneous brightness (0-31) for the breathe effect.
// Called every frame; advances the internal phase accumulator by the elapsed
// time since the previous call so the rate is wall-clock-accurate.
static uint8_t compute_breathe_brightness(const led_config_t *cfg) {
    uint8_t mn = cfg->breathe_min_bright;
    uint8_t mx = cfg->breathe_max_bright;
    if (mn > mx) { uint8_t t = mn; mn = mx; mx = t; }
    if (mn == mx) return mn;

    uint32_t now = time_us_32();
    if (!breathe_seeded) {
        breathe_last_us  = now;
        breathe_phase_us = 0;
        breathe_seeded   = true;
    }
    uint32_t delta = now - breathe_last_us;
    breathe_last_us  = now;
    breathe_phase_us = (breathe_phase_us + delta) % BREATHE_PERIOD_US;

    // Triangle wave: first half rises 0→255, second half falls 255→0
    uint32_t half = BREATHE_PERIOD_US / 2u;
    uint32_t t256 = (breathe_phase_us < half)
                  ? (breathe_phase_us * 256u) / half
                  : ((BREATHE_PERIOD_US - breathe_phase_us) * 256u) / half;

    return (uint8_t)(mn + (((uint32_t)(mx - mn) * t256) / 256u));
}

void apa102_update_from_inputs(const led_config_t *cfg, uint16_t pressed_mask) {
    if (!cfg->enabled || cfg->count == 0) return;

    uint8_t count = cfg->count;
    if (count > MAX_LEDS) count = MAX_LEDS;

    // ── 1. Base brightness ───────────────────────────────────────────────────
    uint8_t brightness[MAX_LEDS];
    for (int i = 0; i < count; i++) {
        brightness[i] = cfg->base_brightness;
    }

    // ── 2. Breathe: override brightness for breathe range ───────────────────
    if (cfg->breathe_enabled &&
        cfg->breathe_start <= cfg->breathe_end &&
        cfg->breathe_end < count)
    {
        uint8_t bb = compute_breathe_brightness(cfg);
        for (int i = cfg->breathe_start; i <= cfg->breathe_end; i++) {
            brightness[i] = bb;
        }
    }

    // ── 3. Reactive: raise brightness for pressed inputs' mapped LEDs ────────
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

    // ── 4. Wave: rising-edge trigger, then propagate outward ────────────────
    if (cfg->wave_enabled) {
        uint16_t trigger = pressed_mask & ~((1u << LED_INPUT_TILT) | (1u << LED_INPUT_WHAMMY));
        uint16_t rising = trigger & ~wave_prev_mask;
        wave_prev_mask = trigger;
        if (rising) {
            uint32_t now = time_us_32();
            // Find a free slot; if all busy, overwrite the oldest
            int slot = -1;
            for (int i = 0; i < WAVE_MAX_ACTIVE; i++) {
                if (!waves[i].active) { slot = i; break; }
            }
            if (slot < 0) {
                slot = 0;
                for (int i = 1; i < WAVE_MAX_ACTIVE; i++) {
                    if ((uint32_t)(now - waves[i].start_us) >
                        (uint32_t)(now - waves[slot].start_us))
                        slot = i;
                }
            }
            waves[slot].active   = true;
            waves[slot].start_us = now;
        }
        uint8_t  origin   = (cfg->wave_origin < count) ? cfg->wave_origin : 0;
        uint8_t  max_dist = 0;
        for (int led = 0; led < count; led++) {
            uint8_t d = (uint8_t)(led >= origin ? led - origin : origin - led);
            if (d > max_dist) max_dist = d;
        }
        uint32_t lifetime = (uint32_t)max_dist * WAVE_US_PER_LED + WAVE_FADE_US;
        for (int w = 0; w < WAVE_MAX_ACTIVE; w++) {
            if (!waves[w].active) continue;
            uint32_t elapsed = time_us_32() - waves[w].start_us;
            if (elapsed >= lifetime) { waves[w].active = false; continue; }
            for (int led = 0; led < count; led++) {
                uint8_t  dist   = (uint8_t)(led >= origin ? led - origin : origin - led);
                uint32_t t_peak = (uint32_t)dist * WAVE_US_PER_LED;
                if (elapsed >= t_peak) {
                    uint32_t since = elapsed - t_peak;
                    if (since < WAVE_FADE_US) {
                        // Fade from 31 down to base_brightness
                        uint32_t t256 = (since * 256u) / WAVE_FADE_US;
                        int32_t  base = cfg->base_brightness;
                        int32_t  wb   = 31 + ((base - 31) * (int32_t)t256) / 256;
                        if (wb < 0)  wb = 0;
                        if (wb > 31) wb = 31;
                        if ((uint8_t)wb > brightness[led]) brightness[led] = (uint8_t)wb;
                    }
                }
            }
        }
    } else {
        // Wave disabled — keep prev_mask in sync so there's no stale rising-edge
        wave_prev_mask = pressed_mask & ~((1u << LED_INPUT_TILT) | (1u << LED_INPUT_WHAMMY));
        for (int i = 0; i < WAVE_MAX_ACTIVE; i++) waves[i].active = false;
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
