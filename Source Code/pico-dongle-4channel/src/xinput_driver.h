/*
 * xinput_driver.h - Custom TinyUSB class driver for XInput (multi-slot)
 *
 * Handles up to 4 independent XInput interfaces in a single composite device.
 * Each slot (0-3) corresponds to one interface / one set of endpoints.
 * The single usbd_app_driver_get_cb entry point claims all matching interfaces
 * by tracking them by bInterfaceNumber inside the driver.
 */

#ifndef _XINPUT_DRIVER_H_
#define _XINPUT_DRIVER_H_

#include <stdint.h>
#include <stdbool.h>
#include "usb_descriptors.h"

/* Send an XInput report for slot `slot` (0-3).
   Returns true if the report was submitted successfully. */
bool xinput_send_report(uint8_t slot, const xinput_report_t *report);

/* Returns true if slot `slot` is mounted and ready to send. */
bool xinput_ready(uint8_t slot);

#endif /* _XINPUT_DRIVER_H_ */
