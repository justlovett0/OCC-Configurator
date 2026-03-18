/*
 * usb_descriptors.c - Dual-mode USB Descriptors for Drum Kit
 *
 * Normal mode:  XInput Drum Kit (Xbox 360 drum controller, subtype 0x02)
 * Config mode:  CDC ACM serial port for the configurator GUI
 */

#include "tusb.h"
#include "usb_descriptors.h"
#include "pico/unique_id.h"
#include <string.h>
#include <stdio.h>

bool g_config_mode = false;
const char *g_device_name = "Drum Controller";

// ====================================================================
//  DEVICE DESCRIPTORS
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

static const tusb_desc_device_t cdc_device_desc = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = TUSB_CLASS_CDC,
    .bDeviceSubClass    = 0x00,
    .bDeviceProtocol    = 0x00,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = CONFIG_MODE_VID,
    .idProduct          = CONFIG_MODE_PID,
    .bcdDevice          = 0x0100,
    .iManufacturer      = 1,
    .iProduct           = 2,
    .iSerialNumber      = 3,
    .bNumConfigurations = 1,
};

uint8_t const* tud_descriptor_device_cb(void) {
    return (uint8_t const *)(g_config_mode ? &cdc_device_desc : &xinput_device_desc);
}

// ====================================================================
//  CONFIGURATION DESCRIPTORS
// ====================================================================

static const uint8_t xinput_config_desc[] = {
    // Configuration Descriptor (9)
    0x09, TUSB_DESC_CONFIGURATION,
    XINPUT_DESC_CONFIG_TOTAL, 0x00, 0x01, 0x01, 0x00, 0x80, 0xFA,
    // Interface Descriptor (9)
    0x09, TUSB_DESC_INTERFACE,
    0x00, 0x00, 0x02,
    XINPUT_IF_CLASS, XINPUT_IF_SUBCLASS, XINPUT_IF_PROTOCOL, 0x00,
    // XInput Vendor Descriptor (17)
    // Byte 4 of this descriptor is the device subtype: 0x02 = drum kit
    0x11, 0x21, 0x00, 0x01,
    XINPUT_SUBTYPE_DRUM_KIT, 0x25,           // <-- 0x02 here identifies drums
    XINPUT_EP_IN, XINPUT_REPORT_SIZE,
    0x00, 0x00, 0x00, 0x00, 0x13,
    XINPUT_EP_OUT, XINPUT_OUT_REPORT_SIZE, 0x00, 0x00,
    // Endpoint IN (7)
    0x07, TUSB_DESC_ENDPOINT,
    XINPUT_EP_IN, TUSB_XFER_INTERRUPT,
    XINPUT_EP_MAX_PACKET, 0x00, 0x04,
    // Endpoint OUT (7)
    0x07, TUSB_DESC_ENDPOINT,
    XINPUT_EP_OUT, TUSB_XFER_INTERRUPT,
    XINPUT_EP_MAX_PACKET, 0x00, 0x08,
};

#define CDC_CONFIG_TOTAL_LEN  75

static const uint8_t cdc_config_desc[] = {
    // Configuration Descriptor (9)
    0x09, TUSB_DESC_CONFIGURATION,
    CDC_CONFIG_TOTAL_LEN, 0x00, 0x02, 0x01, 0x00, 0x80, 0xFA,
    // IAD (8)
    0x08, TUSB_DESC_INTERFACE_ASSOCIATION,
    0x00, 0x02,
    TUSB_CLASS_CDC, CDC_COMM_SUBCLASS_ABSTRACT_CONTROL_MODEL,
    CDC_COMM_PROTOCOL_NONE, 0x00,
    // CDC Communication Interface (9)
    0x09, TUSB_DESC_INTERFACE,
    0x00, 0x00, 0x01,
    TUSB_CLASS_CDC, CDC_COMM_SUBCLASS_ABSTRACT_CONTROL_MODEL,
    CDC_COMM_PROTOCOL_NONE, 0x04,
    // CDC Functional Descriptors (5+5+4+5 = 19)
    0x05, TUSB_DESC_CS_INTERFACE, CDC_FUNC_DESC_HEADER, 0x20, 0x01,
    0x05, TUSB_DESC_CS_INTERFACE, CDC_FUNC_DESC_CALL_MANAGEMENT, 0x00, 0x01,
    0x04, TUSB_DESC_CS_INTERFACE, CDC_FUNC_DESC_ABSTRACT_CONTROL_MANAGEMENT, 0x02,
    0x05, TUSB_DESC_CS_INTERFACE, CDC_FUNC_DESC_UNION, 0x00, 0x01,
    // Notification Endpoint (7)
    0x07, TUSB_DESC_ENDPOINT,
    CDC_EP_NOTIF, TUSB_XFER_INTERRUPT, CDC_EP_NOTIF_SIZE, 0x00, 0x10,
    // CDC Data Interface (9)
    0x09, TUSB_DESC_INTERFACE,
    0x01, 0x00, 0x02,
    TUSB_CLASS_CDC_DATA, 0x00, 0x00, 0x00,
    // Data OUT Endpoint (7)
    0x07, TUSB_DESC_ENDPOINT,
    CDC_EP_OUT, TUSB_XFER_BULK, CDC_EP_DATA_SIZE, 0x00, 0x00,
    // Data IN Endpoint (7)
    0x07, TUSB_DESC_ENDPOINT,
    CDC_EP_IN, TUSB_XFER_BULK, CDC_EP_DATA_SIZE, 0x00, 0x00,
};

uint8_t const* tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    return g_config_mode ? cdc_config_desc : xinput_config_desc;
}

// ====================================================================
//  STRING DESCRIPTORS
// ====================================================================

static const uint16_t string_desc_language[] = {
    (TUSB_DESC_STRING << 8) | (2 + 2), 0x0409
};

static uint16_t _string_desc_buf[64];

static const uint16_t* _make_string_desc(const char* str) {
    uint8_t len = (uint8_t)strlen(str);
    if (len > 62) len = 62;
    _string_desc_buf[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 + 2 * len));
    for (uint8_t i = 0; i < len; i++)
        _string_desc_buf[i + 1] = str[i];
    return _string_desc_buf;
}

uint16_t const* tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid;
    switch (index) {
        case 0: return string_desc_language;
        case 1: return _make_string_desc(g_device_name);
        case 2: return _make_string_desc(g_config_mode
                        ? "Drum Controller Config Mode"
                        : g_device_name);
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
        case 4: return _make_string_desc("Config Serial Port");
        default: return NULL;
    }
}
