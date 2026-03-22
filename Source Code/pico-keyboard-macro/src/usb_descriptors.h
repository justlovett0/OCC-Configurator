/*
 * usb_descriptors.h - Keyboard Macro USB descriptor constants
 */

#ifndef _USB_DESCRIPTORS_H_
#define _USB_DESCRIPTORS_H_

#include <stdint.h>

// Custom device name — set from config before tusb_init()
extern const char *g_device_name;

// VID/PID — OCC vendor, keyboard macro product
#define MACRO_VID           0x2E8A
#define MACRO_PID           0xF011

// Endpoint assignments
// EP0: control (reserved by USB stack)
// EP1 IN:  HID keyboard reports
// EP2 IN:  CDC notification (interrupt)
// EP3 OUT: CDC data out
// EP3 IN:  CDC data in (0x83)
#define MACRO_EP_HID_IN     0x81
#define MACRO_EP_CDC_NOTIF  0x82
#define MACRO_EP_CDC_OUT    0x03
#define MACRO_EP_CDC_IN     0x83

#endif /* _USB_DESCRIPTORS_H_ */
