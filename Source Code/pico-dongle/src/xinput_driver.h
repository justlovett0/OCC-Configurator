/*
 * xinput_driver.h - Custom TinyUSB class driver for XInput
 */

#ifndef _XINPUT_DRIVER_H_
#define _XINPUT_DRIVER_H_

#include <stdint.h>
#include <stdbool.h>
#include "usb_descriptors.h"

void xinput_driver_init(void);
bool xinput_send_report(const xinput_report_t *report);
bool xinput_ready(void);

#endif /* _XINPUT_DRIVER_H_ */
