/*
 * usb_descriptors.h - USB descriptor definitions for the OCC arcade stick
 */

#ifndef _USB_DESCRIPTORS_H_
#define _USB_DESCRIPTORS_H_

#include <stdbool.h>
#include <stdint.h>

#include "arcadestick_config.h"

extern bool g_config_mode;
extern const char *g_device_name;
extern uint8_t g_play_usb_mode;

#define XINPUT_VID                0x045E
#define XINPUT_PID                0x028E

#define XINPUT_IF_CLASS           0xFF
#define XINPUT_IF_SUBCLASS        0x5D
#define XINPUT_IF_PROTOCOL        0x01

#define XINPUT_SUBTYPE_ARCADE_STICK 0x03

#define XINPUT_EP_IN              0x81
#define XINPUT_EP_OUT             0x02

#define XINPUT_REPORT_SIZE        20
#define XINPUT_OUT_REPORT_SIZE    8
#define XINPUT_EP_MAX_PACKET      32
#define XINPUT_DESC_CONFIG_TOTAL  49

#define HID_PLAY_VID              0x2E8A
#define HID_PLAY_PID              0x10A3
#define HID_EP_IN                 0x81
#define HID_EP_SIZE               16
#define HID_POLL_INTERVAL_MS      1

#define CONFIG_MODE_VID           0x2E8A
#define CONFIG_MODE_PID           0xF012

#define CDC_EP_NOTIF              0x83
#define CDC_EP_OUT                0x04
#define CDC_EP_IN                 0x84
#define CDC_EP_NOTIF_SIZE         8
#define CDC_EP_DATA_SIZE          64

#define MAGIC_STEP_COUNT          3
#define MAGIC_TIMEOUT_MS          3000

#define MAGIC_STEP0_LEFT          0x47
#define MAGIC_STEP0_RIGHT         0x43
#define MAGIC_STEP1_LEFT          0x43
#define MAGIC_STEP1_RIGHT         0x47
#define MAGIC_STEP2_LEFT          0x4F
#define MAGIC_STEP2_RIGHT         0x4B

#define WATCHDOG_CONFIG_MAGIC     0xC0F16000

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

typedef struct __attribute__((packed)) {
    uint8_t  report_id;
    uint8_t  report_size;
    uint16_t buttons;
    uint8_t  left_trigger;
    uint8_t  right_trigger;
    int16_t  left_stick_x;
    int16_t  left_stick_y;
    int16_t  right_stick_x;
    int16_t  right_stick_y;
    uint8_t  reserved[6];
} xinput_report_t;

typedef struct __attribute__((packed)) {
    uint16_t buttons;
    uint8_t hat;
    int8_t x;
    int8_t y;
    int8_t z;
    int8_t rz;
} hid_arcadestick_report_t;

#define HID_HAT_CENTERED          0x0F

#endif /* _USB_DESCRIPTORS_H_ */
