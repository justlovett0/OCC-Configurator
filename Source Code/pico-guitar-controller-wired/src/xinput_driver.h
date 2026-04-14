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

// Returns true if the magic vibration sequence was detected.
// Calling this clears the flag.
bool xinput_magic_detected(void);

// Returns true if the Windows/Linux XInput LED control report (byte[0]=0x01)
// was received. Signals that the host speaks XInput — used for PS3 auto-detection.
bool xinput_led_report_seen(void);

// Returns true if the Xbox 360 security challenge (req 0x81) was received.
// Real 360 consoles never send the LED report — this catches them instead.
bool xinput_auth_seen(void);

//--------------------------------------------------------------------
// Diagnostics
//--------------------------------------------------------------------

// Bitmask: bit0=mounted, bit1=tx_busy, bit2=tud_ready, bit3=send_ever_failed
uint8_t  xinput_diag_flags(void);
uint32_t xinput_diag_send_ok(void);
uint32_t xinput_diag_send_fail(void);
uint32_t xinput_diag_cb_in(void);
uint32_t xinput_diag_cb_out(void);
uint32_t xinput_diag_ready_false(void);
uint32_t xinput_diag_last_send_ms(void);

#endif /* _XINPUT_DRIVER_H_ */
