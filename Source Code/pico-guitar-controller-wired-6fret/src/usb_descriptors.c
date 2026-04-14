/*
 * usb_descriptors.c - GH Live-style USB descriptors
 *
 * Normal mode:  GH Live-style HID guitar
 * Config mode:  CDC ACM serial port for the configurator GUI
 */

#include "tusb.h"
#include "usb_descriptors.h"
#include "pico/unique_id.h"
#include <string.h>
#include <stdio.h>

bool g_config_mode  = false;
bool g_hid_mode     = false;
bool g_kb_mode      = false;
bool g_xinput_mode  = false;

const char *g_device_name = "OCC 6-Fret Guitar";

static bool g_ghl_keepalive_seen = false;

static const tusb_desc_device_t ghl_hid_device_desc = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = 0x00,
    .bDeviceSubClass    = 0x00,
    .bDeviceProtocol    = 0x00,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = GHL_HID_VID,
    .idProduct          = GHL_HID_PID,
    .bcdDevice          = 0x0100,
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

static const tusb_desc_device_t hid_kb_device_desc = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = 0x00,
    .bDeviceSubClass    = 0x00,
    .bDeviceProtocol    = 0x00,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = 0x2E8A,
    .idProduct          = 0xF012,
    .bcdDevice          = 0x0100,
    .iManufacturer      = 1,
    .iProduct           = 2,
    .iSerialNumber      = 3,
    .bNumConfigurations = 1,
};

// Raw 27-byte input report + 8-byte output report for keepalive packets.
static const uint8_t ghl_hid_report_desc[] = {
    0x06, 0x00, 0xFF,
    0x09, 0x01,
    0xA1, 0x01,
    0x15, 0x00,
    0x26, 0xFF, 0x00,
    0x75, 0x08,
    0x95, GHL_HID_REPORT_SIZE,
    0x09, 0x01,
    0x81, 0x02,
    0x95, GHL_HID_OUT_REPORT_SIZE,
    0x09, 0x02,
    0x91, 0x02,
    0xC0
};

static const uint8_t hid_kb_report_desc[] = { TUD_HID_REPORT_DESC_KEYBOARD() };

static const uint8_t ghl_hid_config_desc[] = {
    0x09, TUSB_DESC_CONFIGURATION,
    GHL_HID_DESC_CONFIG_TOTAL, 0x00,
    0x01, 0x01, 0x00, 0x80, 0xFA,

    0x09, TUSB_DESC_INTERFACE,
    0x00, 0x00, 0x02,
    TUSB_CLASS_HID, 0x00, 0x00, 0x00,

    0x09, 0x21,
    0x11, 0x01,
    0x00,
    0x01,
    0x22,
    sizeof(ghl_hid_report_desc), 0x00,

    0x07, TUSB_DESC_ENDPOINT,
    GHL_HID_EP_IN, TUSB_XFER_INTERRUPT,
    GHL_HID_EP_MAX_PACKET, 0x00, 0x01,

    0x07, TUSB_DESC_ENDPOINT,
    GHL_HID_EP_OUT, TUSB_XFER_INTERRUPT,
    GHL_HID_EP_MAX_PACKET, 0x00, 0x01,
};

#define HID_KB_DESC_CONFIG_TOTAL  34

static const uint8_t hid_kb_config_desc[] = {
    0x09, TUSB_DESC_CONFIGURATION,
    HID_KB_DESC_CONFIG_TOTAL, 0x00,
    0x01, 0x01, 0x00, 0x80, 0xFA,

    0x09, TUSB_DESC_INTERFACE,
    0x00, 0x00, 0x01,
    TUSB_CLASS_HID, 0x01, 0x01, 0x00,

    0x09, 0x21,
    0x11, 0x01,
    0x00,
    0x01,
    0x22,
    sizeof(hid_kb_report_desc), 0x00,

    0x07, TUSB_DESC_ENDPOINT,
    0x81, TUSB_XFER_INTERRUPT,
    0x08, 0x00, 0x01,
};

#define CDC_CONFIG_TOTAL_LEN  75

static const uint8_t cdc_config_desc[] = {
    0x09, TUSB_DESC_CONFIGURATION,
    CDC_CONFIG_TOTAL_LEN, 0x00, 0x02, 0x01, 0x00, 0x80, 0xFA,

    0x08, TUSB_DESC_INTERFACE_ASSOCIATION,
    0x00, 0x02,
    TUSB_CLASS_CDC, CDC_COMM_SUBCLASS_ABSTRACT_CONTROL_MODEL,
    CDC_COMM_PROTOCOL_NONE, 0x00,

    0x09, TUSB_DESC_INTERFACE,
    0x00, 0x00, 0x01,
    TUSB_CLASS_CDC, CDC_COMM_SUBCLASS_ABSTRACT_CONTROL_MODEL,
    CDC_COMM_PROTOCOL_NONE, 0x04,

    0x05, TUSB_DESC_CS_INTERFACE, CDC_FUNC_DESC_HEADER, 0x20, 0x01,
    0x05, TUSB_DESC_CS_INTERFACE, CDC_FUNC_DESC_CALL_MANAGEMENT, 0x00, 0x01,
    0x04, TUSB_DESC_CS_INTERFACE, CDC_FUNC_DESC_ABSTRACT_CONTROL_MANAGEMENT, 0x02,
    0x05, TUSB_DESC_CS_INTERFACE, CDC_FUNC_DESC_UNION, 0x00, 0x01,

    0x07, TUSB_DESC_ENDPOINT,
    CDC_EP_NOTIF, TUSB_XFER_INTERRUPT, CDC_EP_NOTIF_SIZE, 0x00, 0x10,

    0x09, TUSB_DESC_INTERFACE,
    0x01, 0x00, 0x02,
    TUSB_CLASS_CDC_DATA, 0x00, 0x00, 0x00,

    0x07, TUSB_DESC_ENDPOINT,
    CDC_EP_OUT, TUSB_XFER_BULK, CDC_EP_DATA_SIZE, 0x00, 0x00,

    0x07, TUSB_DESC_ENDPOINT,
    CDC_EP_IN, TUSB_XFER_BULK, CDC_EP_DATA_SIZE, 0x00, 0x00,
};

// Xbox 360 XInput device descriptor
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

// XInput config: 3 interfaces — controller (0), unknown (1), security (2)
//   IF0 (9) + vendor_cap (17) + EP_IN (7) + EP_OUT (7) = 40
//   IF1 (9) + vendor_cap (10)                           = 19
//   IF2 (9) + security_cap (6)                          = 15
//   config header (9) + 40 + 19 + 15                   = 83
#define XINPUT_CONFIG_TOTAL 83

static const uint8_t xinput_config_desc[] = {
    // Configuration
    9, TUSB_DESC_CONFIGURATION,
    XINPUT_CONFIG_TOTAL, 0x00,
    0x03,       // bNumInterfaces
    0x01,       // bConfigurationValue
    0x00,       // iConfiguration
    0x80,       // bmAttributes: bus-powered
    0xFA,       // bMaxPower: 500 mA

    // Interface 0: XInput controller (class FF/5D/01)
    9, TUSB_DESC_INTERFACE,
    0x00,                   // bInterfaceNumber
    0x00,                   // bAlternateSetting
    0x02,                   // bNumEndpoints
    XINPUT_IF_CLASS,        // 0xFF
    XINPUT_IF_SUBCLASS,     // 0x5D
    XINPUT_IF_PROTOCOL,     // 0x01
    0x00,                   // iInterface

    // XInput capability descriptor (17 bytes) — subtype byte is guitar (0x06)
    17, 0x21, 0x10, 0x01, XINPUT_SUBTYPE_GUITAR, 0x25,
    XINPUT_EP_IN,  0x14,
    0x03, 0x03, 0x03, 0x04, 0x13,
    XINPUT_EP_OUT, 0x08,
    0x03, 0x03,

    // EP IN (controller → host, interrupt, 32 bytes, 1ms)
    7, TUSB_DESC_ENDPOINT,
    XINPUT_EP_IN, TUSB_XFER_INTERRUPT,
    XINPUT_EP_MAX_PACKET, 0x00, 0x01,

    // EP OUT (host → controller, interrupt, 32 bytes, 8ms)
    7, TUSB_DESC_ENDPOINT,
    XINPUT_EP_OUT, TUSB_XFER_INTERRUPT,
    XINPUT_EP_MAX_PACKET, 0x00, 0x08,

    // Interface 1: unknown (class FF/5D/03) — no endpoints, required by 360
    9, TUSB_DESC_INTERFACE,
    0x01, 0x00, 0x00,
    0xFF, 0x5D, 0x03, 0x00,

    // Vendor descriptor for IF1 (10 bytes)
    10, 0x21, 0x00, 0x01, 0x01, 0x00, 0x07, 0x00, 0x00, 0x00,

    // Interface 2: security (class FF/FD/13) — no endpoints
    9, TUSB_DESC_INTERFACE,
    0x02, 0x00, 0x00,
    0xFF, 0xFD, 0x13, 0x00,

    // Security descriptor (6 bytes)
    6, 0x41, 0x00, 0x01, 0x01, 0x03,
};

uint8_t const* tud_hid_descriptor_report_cb(uint8_t instance) {
    (void)instance;
    return g_kb_mode ? hid_kb_report_desc : ghl_hid_report_desc;
}

uint8_t const* tud_descriptor_device_cb(void) {
    if (g_config_mode)  return (uint8_t const *)&cdc_device_desc;
    if (g_kb_mode)      return (uint8_t const *)&hid_kb_device_desc;
    if (g_xinput_mode)  return (uint8_t const *)&xinput_device_desc;
    return (uint8_t const *)&ghl_hid_device_desc;
}

uint8_t const* tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    if (g_config_mode)  return cdc_config_desc;
    if (g_kb_mode)      return hid_kb_config_desc;
    if (g_xinput_mode)  return xinput_config_desc;
    return ghl_hid_config_desc;
}

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
        case 1:  return _make_string_desc(g_config_mode ? "Open Controller Config" : "Open Controller");
        case 2:  return _make_string_desc(g_config_mode ? "6-Fret Guitar Config Mode" : g_device_name);
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
        case 4:  return _make_string_desc("Config Serial Port");
        default: return NULL;
    }
}

static bool ghl_keepalive_matches(uint8_t const *buffer, uint16_t len) {
    if (len < 3) return false;
    return buffer[0] == 0x02 && buffer[1] == 0x08 && buffer[2] == 0x20;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
                           hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize) {
    (void)instance;
    (void)report_id;
    (void)report_type;

    if (!g_kb_mode && ghl_keepalive_matches(buffer, bufsize)) {
        g_ghl_keepalive_seen = true;
    }
}

bool ghl_magic_keepalive_seen(void) {
    if (g_ghl_keepalive_seen) {
        g_ghl_keepalive_seen = false;
        return true;
    }
    return false;
}
