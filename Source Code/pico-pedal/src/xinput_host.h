/*
 * xinput_host.h - USB Host XInput controller reader
 *
 * Runs on Core 1 via PIO-USB. Reads XInput reports from a connected
 * guitar controller and makes them available to Core 0 for merging
 * with pedal button inputs.
 *
 * Hardware: PIO-USB on two consecutive GPIO pins (D+ and D- = D+ + 1).
 * Default: GP0 (D+), GP1 (D-). Change PIO_USB_DP_PIN to use other pins.
 * External 1.5k pull-up on D+ to 3.3V required for full-speed host.
 */

#ifndef _XINPUT_HOST_H_
#define _XINPUT_HOST_H_

#include <stdint.h>
#include <stdbool.h>
#include "usb_descriptors.h"

// PIO-USB D+ pin (D- is always D+ + 1).
// Change this if your hardware uses different GPIO pins.
#define PIO_USB_DP_PIN   0

// Initialize the USB host on Core 1. Call from core1_main().
void xinput_host_init(void);

// Run one iteration of the host task. Call repeatedly from Core 1 loop.
void xinput_host_task(void);

// Returns true if a guitar controller is currently connected via USB host.
bool xinput_host_connected(void);

// Copy the latest host controller report into *report.
// Returns true if a valid report is available, false if no controller
// is connected or no report has been received yet.
// Thread-safe (uses hardware spin lock).
bool xinput_host_get_report(xinput_report_t *report);

#endif /* _XINPUT_HOST_H_ */
