/*
 * usb_descriptors.h - XInput Drum Kit USB Descriptor Definitions
 */

#ifndef _USB_DESCRIPTORS_H_
#define _USB_DESCRIPTORS_H_

#include <stdint.h>
#include <stdbool.h>

//--------------------------------------------------------------------
// Global mode flag — set before tusb_init(), selects descriptor set
//--------------------------------------------------------------------

extern bool g_config_mode;
extern const char *g_device_name;

//--------------------------------------------------------------------
// XInput Constants
//--------------------------------------------------------------------

#define XINPUT_VID                0x045E
#define XINPUT_PID                0x028E

#define XINPUT_IF_CLASS           0xFF
#define XINPUT_IF_SUBCLASS        0x5D
#define XINPUT_IF_PROTOCOL        0x01

// Drum kit subtype (0x08) — tells Windows/games this is a drum controller. NOT 0x02 bc thats WHEEL apparently
#define XINPUT_SUBTYPE_DRUM_KIT   0x08

#define XINPUT_EP_IN              0x81
#define XINPUT_EP_OUT             0x02

#define XINPUT_REPORT_SIZE        20
#define XINPUT_OUT_REPORT_SIZE    8
#define XINPUT_EP_MAX_PACKET      32

#define XINPUT_DESC_CONFIG_TOTAL  49

//--------------------------------------------------------------------
// Config Mode (CDC) Constants
//--------------------------------------------------------------------

#define CONFIG_MODE_VID           0x2E8A
#define CONFIG_MODE_PID           0xF00E   // Different PID from guitar to avoid confusion

#define CDC_EP_NOTIF              0x83
#define CDC_EP_OUT                0x04
#define CDC_EP_IN                 0x84
#define CDC_EP_NOTIF_SIZE         8
#define CDC_EP_DATA_SIZE          64

//--------------------------------------------------------------------
// Magic vibration sequence — same mechanism as guitar firmware
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

//--------------------------------------------------------------------
// XInput Button bit masks
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
// Drum-to-XInput Button Mapping
//
// Standard Rock Band / Clone Hero drum XInput mapping:
//   Pads:    Red=B, Yellow=Y, Blue=X, Green=A
//   Cymbals: Yellow Cymbal = Left Shoulder (LB)
//            Blue Cymbal   = Right Shoulder (RB)
//            Green Cymbal  = Right Thumb (RS click)
//   Cymbal flag: right_trigger byte set to 0xFF when any cymbal is hit
//                (distinguishes cymbal from pad on same colour)
//   D-pad:  Up/Down/Left/Right = standard XInput D-pad bits
//   Foot Pedal: Left Thumb (LS click) — bass pedal per Rock Band spec
//   Start = Start, Select = Back
//--------------------------------------------------------------------

#define DRUM_BTN_RED_DRUM     XINPUT_BTN_B
#define DRUM_BTN_YELLOW_DRUM  XINPUT_BTN_Y
#define DRUM_BTN_BLUE_DRUM    XINPUT_BTN_X
#define DRUM_BTN_GREEN_DRUM   XINPUT_BTN_A
#define DRUM_BTN_YELLOW_CYM   XINPUT_BTN_LEFT_SHOULDER
#define DRUM_BTN_BLUE_CYM     XINPUT_BTN_RIGHT_SHOULDER
#define DRUM_BTN_GREEN_CYM    XINPUT_BTN_RIGHT_THUMB
#define DRUM_BTN_START        XINPUT_BTN_START
#define DRUM_BTN_SELECT       XINPUT_BTN_BACK
#define DRUM_BTN_DPAD_UP      XINPUT_BTN_DPAD_UP
#define DRUM_BTN_DPAD_DOWN    XINPUT_BTN_DPAD_DOWN
#define DRUM_BTN_DPAD_LEFT    XINPUT_BTN_DPAD_LEFT
#define DRUM_BTN_DPAD_RIGHT   XINPUT_BTN_DPAD_RIGHT
#define DRUM_BTN_FOOT_PEDAL   XINPUT_BTN_LEFT_THUMB   // Bass pedal — LS click per Rock Band XInput drum kit

// right_trigger value used to flag a cymbal hit (non-zero = cymbal)
#define DRUM_CYMBAL_FLAG      0xFF

//--------------------------------------------------------------------
// XInput Report Packet (same 20-byte layout as guitar)
//--------------------------------------------------------------------

typedef struct __attribute__((packed)) {
    uint8_t  report_id;
    uint8_t  report_size;
    uint16_t buttons;
    uint8_t  left_trigger;
    uint8_t  right_trigger;   // Set to DRUM_CYMBAL_FLAG when a cymbal is active
    int16_t  left_stick_x;
    int16_t  left_stick_y;
    int16_t  right_stick_x;
    int16_t  right_stick_y;
    uint8_t  reserved[6];
} xinput_report_t;

#endif /* _USB_DESCRIPTORS_H_ */
