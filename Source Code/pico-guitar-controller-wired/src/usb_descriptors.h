/*
 * usb_descriptors.h - XInput Guitar Alternate USB Descriptor Definitions
 */

#ifndef _USB_DESCRIPTORS_H_
#define _USB_DESCRIPTORS_H_

#include <stdint.h>
#include <stdbool.h>

//--------------------------------------------------------------------
// Global mode flags — set before tusb_init(), select descriptor set
//--------------------------------------------------------------------

extern bool g_config_mode;
extern bool g_hid_mode;   // HID mode (PS3 / macOS / Linux without XInput driver)
extern bool g_kb_mode;    // HID keyboard mode (Fortnite Festival) — orange held at boot

// Custom device name — set from config before tusb_init()
extern const char *g_device_name;

//--------------------------------------------------------------------
// XInput Constants
//--------------------------------------------------------------------

#define XINPUT_VID                0x045E
#define XINPUT_PID                0x028E

#define XINPUT_IF_CLASS           0xFF
#define XINPUT_IF_SUBCLASS        0x5D
#define XINPUT_IF_PROTOCOL        0x01

#define XINPUT_SUBTYPE_GUITAR_ALT 0x07

#define XINPUT_EP_IN              0x81
#define XINPUT_EP_OUT             0x02

#define XINPUT_REPORT_SIZE        20
#define XINPUT_OUT_REPORT_SIZE    8
#define XINPUT_EP_MAX_PACKET      32

#define XINPUT_DESC_CONFIG_TOTAL  83   // IF0(40) + IF1(19) + IF2(15) + header(9)

//--------------------------------------------------------------------
// Config Mode (CDC) Constants
//--------------------------------------------------------------------

#define CONFIG_MODE_VID           0x2E8A
#define CONFIG_MODE_PID           0xF00D

#define CDC_EP_NOTIF              0x83
#define CDC_EP_OUT                0x04
#define CDC_EP_IN                 0x84
#define CDC_EP_NOTIF_SIZE         8
#define CDC_EP_DATA_SIZE          64

//--------------------------------------------------------------------
// Magic vibration sequence constants
//--------------------------------------------------------------------

#define MAGIC_STEP_COUNT         3
#define MAGIC_TIMEOUT_MS         3000

#define MAGIC_STEP0_LEFT         0x47
#define MAGIC_STEP0_RIGHT        0x43
#define MAGIC_STEP1_LEFT         0x43
#define MAGIC_STEP1_RIGHT        0x47
#define MAGIC_STEP2_LEFT         0x4F
#define MAGIC_STEP2_RIGHT        0x4B

#define WATCHDOG_CONFIG_MAGIC    0xC0F16000
#define WATCHDOG_HID_MAGIC       0x48494400   // "HID\0" — scratch[1] for HID mode

//--------------------------------------------------------------------
// HID Mode (PS3 / macOS / Linux) — GH Les Paul PS3
//--------------------------------------------------------------------

#define HID_MODE_VID             0x12BA   // RedOctane / Activision
#define HID_MODE_PID             0x0100   // GH Les Paul for PS3

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
//
// D-pad Up/Down share bits with Strum Up/Down. Both can be wired
// independently; the report OR's them together.
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
