/*
 * usb_descriptors.h - GH Live-style 6-fret USB descriptor definitions
 */

#ifndef _USB_DESCRIPTORS_H_
#define _USB_DESCRIPTORS_H_

#include <stdint.h>
#include <stdbool.h>

//--------------------------------------------------------------------
// Global mode flags - set before tusb_init(), select descriptor set
//--------------------------------------------------------------------

extern bool g_config_mode;
extern bool g_hid_mode;
extern bool g_kb_mode;
extern bool g_xinput_mode;

// Custom device name - set from config before tusb_init()
extern const char *g_device_name;

//--------------------------------------------------------------------
// GH Live HID mode constants
//--------------------------------------------------------------------

#define GHL_HID_VID              0x12BA
#define GHL_HID_PID              0x074B
#define GHL_HID_EP_IN            0x81
#define GHL_HID_EP_OUT           0x01
#define GHL_HID_REPORT_SIZE      27
#define GHL_HID_OUT_REPORT_SIZE  8
#define GHL_HID_EP_MAX_PACKET    64
#define GHL_HID_DESC_CONFIG_TOTAL 41

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
// Legacy watchdog mode constants
//--------------------------------------------------------------------

#define WATCHDOG_CONFIG_MAGIC    0xC0F16000
#define WATCHDOG_HID_MAGIC       0x48494400
#define WATCHDOG_XINPUT_MAGIC    0x58494E00

//--------------------------------------------------------------------
// XInput mode constants (Xbox 360 native)
//--------------------------------------------------------------------

#define XINPUT_VID              0x045E
#define XINPUT_PID              0x028E
#define XINPUT_IF_CLASS         0xFF
#define XINPUT_IF_SUBCLASS      0x5D
#define XINPUT_IF_PROTOCOL      0x01
#define XINPUT_SUBTYPE_GUITAR   0x06    // GH/RB guitar subtype
#define XINPUT_EP_IN            0x81
#define XINPUT_EP_OUT           0x02
#define XINPUT_EP_MAX_PACKET    32

// Magic vibration sequence → triggers config mode reboot from XInput mode
#define MAGIC_STEP_COUNT        3
#define MAGIC_TIMEOUT_MS        2000
#define MAGIC_STEP0_LEFT        0x47
#define MAGIC_STEP0_RIGHT       0x43
#define MAGIC_STEP1_LEFT        0x43
#define MAGIC_STEP1_RIGHT       0x47
#define MAGIC_STEP2_LEFT        0x4F
#define MAGIC_STEP2_RIGHT       0x4B

// 20-byte XInput report sent to the 360
typedef struct __attribute__((packed)) {
    uint8_t  report_id;     // always 0x00
    uint8_t  report_len;    // always 0x14 (20)
    uint16_t buttons;       // XInput button bitmask
    uint8_t  lt;            // left trigger  (unused for guitar)
    uint8_t  rt;            // right trigger (unused for guitar)
    int16_t  lx;            // left stick X  (unused for guitar)
    int16_t  ly;            // left stick Y  (unused for guitar)
    int16_t  rx;            // right stick X (unused for guitar)
    int16_t  ry;            // right stick Y = whammy
    uint8_t  reserved[6];   // must be zero
} xinput_report_t;

//--------------------------------------------------------------------
// GH Live fret/button masks
//--------------------------------------------------------------------

#define GHL_FRET_WHITE_1         0x01
#define GHL_FRET_BLACK_1         0x02
#define GHL_FRET_BLACK_2         0x04
#define GHL_FRET_BLACK_3         0x08
#define GHL_FRET_WHITE_2         0x10
#define GHL_FRET_WHITE_3         0x20

#define GHL_BTN_HERO_POWER       0x01
#define GHL_BTN_START            0x02
#define GHL_BTN_GHTV             0x04
#define GHL_BTN_GUIDE            0x10

#define GHL_STRUM_UP             0x00
#define GHL_STRUM_NEUTRAL        0x7F
#define GHL_STRUM_DOWN           0xFF

#define GHL_HAT_UP               0x00
#define GHL_HAT_UP_RIGHT         0x01
#define GHL_HAT_RIGHT            0x02
#define GHL_HAT_DOWN_RIGHT       0x03
#define GHL_HAT_DOWN             0x04
#define GHL_HAT_DOWN_LEFT        0x05
#define GHL_HAT_LEFT             0x06
#define GHL_HAT_UP_LEFT          0x07
#define GHL_HAT_CENTER           0x08

typedef struct __attribute__((packed)) {
    uint8_t fret_bits;            // byte 0
    uint8_t buttons;              // byte 1
    uint8_t reserved2;            // byte 2
    uint8_t reserved3;            // byte 3
    uint8_t strum;                // byte 4
    uint8_t hat;                  // byte 5
    uint8_t tilt;                 // byte 6
    uint8_t reserved7[12];        // bytes 7-18
    uint8_t whammy;               // byte 19
    uint8_t reserved20[7];        // bytes 20-26
} ghl_hid_report_t;

bool ghl_magic_keepalive_seen(void);

#endif /* _USB_DESCRIPTORS_H_ */
