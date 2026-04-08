/*
 * apa102_leds.h - APA102 / SK9822 / Dotstar / APA107 LED driver
 *
 * Bit-banged SPI on configurable pins (default GP3=DI, GP6=SCK).
 * Supports up to MAX_LEDS LEDs in a daisy chain.
 *
 * APA102 frame format per LED: [111 + 5-bit global brightness] [B] [G] [R]
 */

#ifndef _APA102_LEDS_H_
#define _APA102_LEDS_H_

#include <stdint.h>
#include <stdbool.h>

#define MAX_LEDS          16
#define LED_SPI_DI_PIN     3    // MOSI / Data In
#define LED_SPI_SCK_PIN    6    // SCK  / Clock In

// Input index for LED mapping (14 buttons + tilt + whammy)
#define LED_INPUT_COUNT    16
#define LED_INPUT_TILT     14
#define LED_INPUT_WHAMMY   15

typedef struct __attribute__((packed)) {
    uint8_t r, g, b;
} led_color_t;

typedef struct __attribute__((packed)) {
    uint8_t  enabled;             // 0=off, 1=on
    uint8_t  count;               // Number of LEDs in chain (0-16)
    uint8_t  base_brightness;     // Idle brightness (0-31, APA102 global)
    led_color_t colors[MAX_LEDS]; // Per-LED color (R, G, B)

    // Per-input LED mapping
    // led_map[i] is a 16-bit bitmask: bit N = this input affects LED N
    uint16_t led_map[LED_INPUT_COUNT];
    // Brightness when input is active (0-31)
    uint8_t  active_brightness[LED_INPUT_COUNT];

    // ── LED loop (color rotation) ──
    // When enabled, the colors of LEDs [loop_start..loop_end] rotate by one
    // position every second, with a smooth crossfade over the full interval.
    uint8_t  loop_enabled;   // 0 = off, 1 = on
    uint8_t  loop_start;     // First LED index in the loop (0-based)
    uint8_t  loop_end;       // Last LED index in the loop (0-based, inclusive)

    // ── LED breathe ──
    // When enabled, LEDs [breathe_start..breathe_end] slowly fade their brightness
    // between breathe_min_bright and breathe_max_bright on a 3-second triangle wave.
    uint8_t  breathe_enabled;    // 0 = off, 1 = on
    uint8_t  breathe_start;      // First LED index (0-based)
    uint8_t  breathe_end;        // Last LED index (0-based, inclusive)
    uint8_t  breathe_min_bright; // Minimum brightness (0-31)
    uint8_t  breathe_max_bright; // Maximum brightness (0-31)

    // ── LED wave ──
    // On any button press (rising edge), a brightness pulse emanates from
    // wave_origin outward across all LEDs at 8 LEDs/sec, peaking at 31,
    // then fading back to base_brightness over 300 ms per LED.
    uint8_t  wave_enabled; // 0 = off, 1 = on
    uint8_t  wave_origin;  // LED index the wave originates from (0-based)

    // ── Effect speeds ──
    uint16_t loop_speed_ms;    // Color loop full rotation time (ms), default 3000
    uint16_t breathe_speed_ms; // Breathe full cycle time (ms), default 3000
    uint16_t wave_speed_ms;    // Ripple transit time across full strip (ms), default 800
} led_config_t;

// Initialize SPI pins for LED output
void apa102_init(void);

// Push current LED state to the strip
// brightness[i] = 0-31 per LED, colors from config
void apa102_update(const led_config_t *cfg, const uint8_t *brightness);

// Convenience: update LEDs based on current button states
// pressed_mask: bitmask of which inputs are currently active
//   bits 0-13 = BTN_IDX_*, bit 14 = tilt, bit 15 = whammy
void apa102_update_from_inputs(const led_config_t *cfg, uint16_t pressed_mask);

// Turn all LEDs off
void apa102_all_off(const led_config_t *cfg);

// Flash a single LED (for identification during config)
// Blinks LED at index `led_idx` with color from config, count times
void apa102_flash_led(const led_config_t *cfg, uint8_t led_idx, uint8_t count);

// Flash all LEDs once in a solid color, then turn off.
// Blocking — used for boot-mode indication (PS3 = green, KB = orange).
void apa102_flash_all_color(const led_config_t *cfg, uint8_t r, uint8_t g, uint8_t b);

#endif /* _APA102_LEDS_H_ */
