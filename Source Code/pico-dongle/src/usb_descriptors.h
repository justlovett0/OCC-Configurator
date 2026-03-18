/*
 * usb_descriptors.h - XInput Guitar Alternate USB Descriptor Definitions
 *
 * XInput only — no CDC config mode.
 */

#ifndef _USB_DESCRIPTORS_H_
#define _USB_DESCRIPTORS_H_

#include <stdint.h>
#include <stdbool.h>

//--------------------------------------------------------------------
// XInput Constants
//--------------------------------------------------------------------

#define XINPUT_VID                0x045E
#define XINPUT_PID                0x028E

#define XINPUT_IF_CLASS           0xFF
#define XINPUT_IF_SUBCLASS        0x5D
#define XINPUT_IF_PROTOCOL        0x01

// Subtype 0x0B = XINPUT_DEVSUBTYPE_GUITAR_BASS — a guitar-family subtype that
// exposes full analog axes (whammy, tilt) and is distinct from 0x07 (Guitar
// Alternate) used by the wired/wireless guitar firmware and 0x08 (Drum Kit).
// Games treat all guitar subtypes (0x06, 0x07, 0x0B) identically.
// The configurator keys off this value to recognise a dongle and suppress
// the Configure button (dongle has no config serial mode).
// NOTE: Do NOT use 0x05 — that is XINPUT_DEVSUBTYPE_DANCE_PAD and causes
// Windows to suppress all analog axis output.
#define XINPUT_SUBTYPE_DONGLE     0x0B

#define XINPUT_EP_IN              0x81
#define XINPUT_EP_OUT             0x02

#define XINPUT_REPORT_SIZE        20
#define XINPUT_OUT_REPORT_SIZE    8
#define XINPUT_EP_MAX_PACKET      32

#define XINPUT_DESC_CONFIG_TOTAL  49

//--------------------------------------------------------------------
// XInput Button bit masks (bytes 2-3 of report, little-endian uint16)
//--------------------------------------------------------------------

#define XINPUT_BTN_DPAD_UP        0x0001
#define XINPUT_BTN_DPAD_DOWN      0x0002
#define XINPUT_BTN_DPAD_LEFT      0x0004
#define XINPUT_BTN_DPAD_RIGHT     0x0008
#define XINPUT_BTN_START          0x0010
#define XINPUT_BTN_BACK           0x0020
#define XINPUT_BTN_LEFT_THUMB     0x0040
#define XINPUT_BTN_RIGHT_THUMB    0x0080
#define XINPUT_BTN_LEFT_SHOULDER  0x0100
#define XINPUT_BTN_RIGHT_SHOULDER 0x0200
#define XINPUT_BTN_GUIDE          0x0400
#define XINPUT_BTN_A              0x1000
#define XINPUT_BTN_B              0x2000
#define XINPUT_BTN_X              0x4000
#define XINPUT_BTN_Y              0x8000

//--------------------------------------------------------------------
// Guitar-to-XInput Button Mapping
//--------------------------------------------------------------------

#define GUITAR_BTN_GREEN          XINPUT_BTN_A
#define GUITAR_BTN_RED            XINPUT_BTN_B
#define GUITAR_BTN_YELLOW         XINPUT_BTN_Y
#define GUITAR_BTN_BLUE           XINPUT_BTN_X
#define GUITAR_BTN_ORANGE         XINPUT_BTN_LEFT_SHOULDER
#define GUITAR_BTN_STRUM_UP       XINPUT_BTN_DPAD_UP
#define GUITAR_BTN_STRUM_DOWN     XINPUT_BTN_DPAD_DOWN
#define GUITAR_BTN_START          XINPUT_BTN_START
#define GUITAR_BTN_SELECT         XINPUT_BTN_BACK
#define GUITAR_BTN_DPAD_UP        XINPUT_BTN_DPAD_UP
#define GUITAR_BTN_DPAD_DOWN      XINPUT_BTN_DPAD_DOWN
#define GUITAR_BTN_DPAD_LEFT      XINPUT_BTN_DPAD_LEFT
#define GUITAR_BTN_DPAD_RIGHT     XINPUT_BTN_DPAD_RIGHT
#define GUITAR_BTN_GUIDE          XINPUT_BTN_GUIDE

//--------------------------------------------------------------------
// XInput Report Packet
//--------------------------------------------------------------------

typedef struct __attribute__((packed)) {
    uint8_t  report_id;
    uint8_t  report_size;
    uint16_t buttons;
    uint8_t  left_trigger;
    uint8_t  right_trigger;
    int16_t  left_stick_x;
    int16_t  left_stick_y;
    int16_t  right_stick_x;   // Whammy
    int16_t  right_stick_y;   // Tilt
    uint8_t  reserved[6];
} xinput_report_t;

#endif /* _USB_DESCRIPTORS_H_ */
