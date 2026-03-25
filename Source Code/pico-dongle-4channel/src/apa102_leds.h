/*
 * apa102_leds.h - Simple APA102/SK9822 driver for 4-channel dongle
 *
 * 8 LEDs on hardware SPI0: GP3 = MOSI (DI), GP6 = SCK (CI).
 * DMA-backed, non-blocking. All LEDs share one RGB color; per-LED
 * brightness (0-31 APA102 global) lets individual slots be on/off/dim.
 */

#ifndef _APA102_LEDS_H_
#define _APA102_LEDS_H_

#include <stdint.h>

#define DONGLE_LED_COUNT   8
#define LED_SPI_DI_PIN     3    // SPI0 TX / Data In
#define LED_SPI_SCK_PIN    6    // SPI0 SCK / Clock In

// Init SPI0 and claim a DMA channel. Call once after hardware init.
void apa102_init(void);

// Send frame to strip. brightness[i] = 0-31 per LED; r/g/b = common color.
void apa102_write(const uint8_t brightness[DONGLE_LED_COUNT], uint8_t r, uint8_t g, uint8_t b);

// Blocking all-off — use at init/shutdown
void apa102_all_off(void);

#endif /* _APA102_LEDS_H_ */
