/*
 * usb_descriptors.c - XInput Guitar Alternate USB Descriptors
 *
 * XInput only — no dual-mode, no CDC.
 */

#include "tusb.h"
#include "usb_descriptors.h"
#include "pico/unique_id.h"
#include <string.h>
#include <stdio.h>

// ====================================================================
//  DEVICE DESCRIPTOR
// ====================================================================

static const tusb_desc_device_t xinput_device_desc = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = 0xFF,
    .bDeviceSubClass    = 0xFF,
    .bDeviceProtocol    = 0xFF,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = XINPUT_VID,
    .idProduct          = XINPUT_PID,
    .bcdDevice          = 0x0114,
    .iManufacturer      = 1,
    .iProduct           = 2,
    .iSerialNumber      = 3,
    .bNumConfigurations = 1,
};

uint8_t const* tud_descriptor_device_cb(void) {
    return (uint8_t const *)&xinput_device_desc;
}

// ====================================================================
//  CONFIGURATION DESCRIPTOR
// ====================================================================

static const uint8_t xinput_config_desc[] = {
    0x09, TUSB_DESC_CONFIGURATION,
    XINPUT_DESC_CONFIG_TOTAL, 0x00, 0x01, 0x01, 0x00, 0x80, 0xFA,
    0x09, TUSB_DESC_INTERFACE,
    0x00, 0x00, 0x02,
    XINPUT_IF_CLASS, XINPUT_IF_SUBCLASS, XINPUT_IF_PROTOCOL, 0x00,
    0x11, 0x21, 0x00, 0x01,
    XINPUT_SUBTYPE_DONGLE, 0x25,
    XINPUT_EP_IN, XINPUT_REPORT_SIZE,
    0x00, 0x00, 0x00, 0x00, 0x13,
    XINPUT_EP_OUT, XINPUT_OUT_REPORT_SIZE, 0x00, 0x00,
    0x07, TUSB_DESC_ENDPOINT,
    XINPUT_EP_IN, TUSB_XFER_INTERRUPT,
    XINPUT_EP_MAX_PACKET, 0x00, 0x04,
    0x07, TUSB_DESC_ENDPOINT,
    XINPUT_EP_OUT, TUSB_XFER_INTERRUPT,
    XINPUT_EP_MAX_PACKET, 0x00, 0x08,
};

uint8_t const* tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    return xinput_config_desc;
}

// ====================================================================
//  STRING DESCRIPTORS
// ====================================================================

static const char *DEVICE_NAME = "Guitar Controller Dongle";

static const uint16_t string_desc_language[] = {
    (TUSB_DESC_STRING << 8) | (2 + 2), 0x0409
};

static uint16_t _string_desc_buf[64];

static const uint16_t* _make_string_desc(const char* str) {
    uint8_t len = (uint8_t)strlen(str);
    if (len > 62) len = 62;
    _string_desc_buf[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 + 2 * len));
    for (uint8_t i = 0; i < len; i++) {
        _string_desc_buf[i + 1] = str[i];
    }
    return _string_desc_buf;
}

uint16_t const* tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid;
    switch (index) {
        case 0:  return string_desc_language;
        case 1:  return _make_string_desc(DEVICE_NAME);
        case 2:  return _make_string_desc(DEVICE_NAME);
        case 3: {
            static char serial[32];
            pico_unique_board_id_t id;
            pico_get_unique_board_id(&id);
            snprintf(serial, sizeof(serial),
                     "%02X%02X%02X%02X%02X%02X%02X%02X",
                     id.id[0], id.id[1], id.id[2], id.id[3],
                     id.id[4], id.id[5], id.id[6], id.id[7]);
            return _make_string_desc(serial);
        }
        default: return NULL;
    }
}
