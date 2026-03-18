/*
 * usb_descriptors.h - XInput Guitar Dongle USB Descriptor Definitions
 *
 * Multi-controller version: supports 1-4 XInput interfaces in one USB device.
 *
 * Endpoint assignment per slot:
 *   Slot 0: Interface 0 — EP IN 0x81, EP OUT 0x02
 *   Slot 1: Interface 1 — EP IN 0x83, EP OUT 0x04
 *   Slot 2: Interface 2 — EP IN 0x85, EP OUT 0x06
 *   Slot 3: Interface 3 — EP IN 0x87, EP OUT 0x08
 *
 * g_num_controllers (1-4) controls which configuration descriptor is returned
 * to the host. When this value changes, the dongle performs a USB soft
 * disconnect/reconnect so Windows re-enumerates with the new interface count.
 */

#ifndef _USB_DESCRIPTORS_H_
#define _USB_DESCRIPTORS_H_

#include <stdint.h>
#include <stdbool.h>

/* ── Global ──────────────────────────────────────────────────────── */

extern uint8_t  g_num_controllers;   /* 1-4: how many XInput interfaces to present */

/* ── XInput protocol constants ───────────────────────────────────── */

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

/* Endpoint addresses — indexed by slot number */
#define XINPUT_EP_IN_SLOT(n)   (0x81 + ((n) * 2))   /* 0x81, 0x83, 0x85, 0x87 */
#define XINPUT_EP_OUT_SLOT(n)  (0x02 + ((n) * 2))   /* 0x02, 0x04, 0x06, 0x08 */

/* Legacy single-slot names (kept so xinput_driver.c compile stays clean) */
#define XINPUT_EP_IN           XINPUT_EP_IN_SLOT(0)
#define XINPUT_EP_OUT          XINPUT_EP_OUT_SLOT(0)

#define XINPUT_REPORT_SIZE        20
#define XINPUT_OUT_REPORT_SIZE    8
#define XINPUT_EP_MAX_PACKET      32

/* ── XInput button bit masks ─────────────────────────────────────── */

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

/* ── Guitar-to-XInput button mapping ────────────────────────────── */

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

/* ── XInput Report Packet ────────────────────────────────────────── */

typedef struct __attribute__((packed)) {
    uint8_t  report_id;
    uint8_t  report_size;
    uint16_t buttons;
    uint8_t  left_trigger;
    uint8_t  right_trigger;
    int16_t  left_stick_x;
    int16_t  left_stick_y;
    int16_t  right_stick_x;   /* Whammy */
    int16_t  right_stick_y;   /* Tilt   */
    uint8_t  reserved[6];
} xinput_report_t;

#endif /* _USB_DESCRIPTORS_H_ */
