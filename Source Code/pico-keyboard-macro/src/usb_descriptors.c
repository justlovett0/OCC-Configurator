/*
 * usb_descriptors.c - Composite HID keyboard + CDC descriptors
 *
 * Always composite — no mode switching needed. HID is the keyboard interface,
 * CDC is the always-on config serial port. No reboot required to configure.
 */

#include "tusb.h"
#include "usb_descriptors.h"
#include "pico/unique_id.h"
#include <string.h>
#include <stdio.h>

const char *g_device_name = "Macro Pad";

// ====================================================================
//  DEVICE DESCRIPTOR
// ====================================================================

// bDeviceClass = 0xEF (Misc), SubClass = 0x02, Protocol = 0x01
// Required for IAD composite devices so Windows recognizes the IAD
static const tusb_desc_device_t device_desc = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = TUSB_CLASS_MISC,
    .bDeviceSubClass    = 0x02,
    .bDeviceProtocol    = 0x01,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = MACRO_VID,
    .idProduct          = MACRO_PID,
    .bcdDevice          = 0x0100,
    .iManufacturer      = 1,
    .iProduct           = 2,
    .iSerialNumber      = 3,
    .bNumConfigurations = 1,
};

uint8_t const *tud_descriptor_device_cb(void) {
    return (uint8_t const *)&device_desc;
}

// ====================================================================
//  HID REPORT DESCRIPTOR
// ====================================================================

// Standard 6KRO keyboard — no report ID (report_id = 0 when sending)
static const uint8_t hid_report_desc[] = { TUD_HID_REPORT_DESC_KEYBOARD() };

uint8_t const *tud_hid_descriptor_report_cb(uint8_t itf) {
    (void)itf;
    return hid_report_desc;
}

// ====================================================================
//  CONFIGURATION DESCRIPTOR
// ====================================================================

// Total length = config header + HID interface + CDC (IAD + 2 interfaces)
#define CONFIG_TOTAL_LEN  (TUD_CONFIG_DESC_LEN + TUD_HID_DESC_LEN + TUD_CDC_DESC_LEN)

static const uint8_t config_desc[] = {
    // Config header: 1 config, 3 interfaces total, remote wakeup enabled, 100mA
    TUD_CONFIG_DESCRIPTOR(1, 3, 0, CONFIG_TOTAL_LEN, TUSB_DESC_CONFIG_ATT_REMOTE_WAKEUP, 100),

    // HID keyboard: interface 0, EP 0x81, 1ms poll interval
    TUD_HID_DESCRIPTOR(0, 0, HID_ITF_PROTOCOL_NONE,
                       sizeof(hid_report_desc),
                       MACRO_EP_HID_IN, CFG_TUD_HID_EP_BUFSIZE, 1),

    // CDC: interfaces 1+2, notif EP 0x82 (8 bytes), data EPs 0x03 out / 0x83 in
    TUD_CDC_DESCRIPTOR(1, 4, MACRO_EP_CDC_NOTIF, 8,
                       MACRO_EP_CDC_OUT, MACRO_EP_CDC_IN, CFG_TUD_CDC_EP_BUFSIZE),
};

uint8_t const *tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    return config_desc;
}

// ====================================================================
//  STRING DESCRIPTORS
// ====================================================================

static const uint16_t lang_desc[] = {
    (TUSB_DESC_STRING << 8) | (2 + 2), 0x0409
};

static uint16_t str_buf[64];

static const uint16_t *make_str(const char *str) {
    uint8_t len = (uint8_t)strlen(str);
    if (len > 62) len = 62;
    str_buf[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 + 2 * len));
    for (uint8_t i = 0; i < len; i++)
        str_buf[i + 1] = str[i];
    return str_buf;
}

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid;
    switch (index) {
        case 0: return lang_desc;
        case 1: return make_str("OCC");
        case 2: return make_str(g_device_name);
        case 3: {
            static char serial[32];
            pico_unique_board_id_t id;
            pico_get_unique_board_id(&id);
            snprintf(serial, sizeof(serial),
                     "%02X%02X%02X%02X%02X%02X%02X%02X",
                     id.id[0], id.id[1], id.id[2], id.id[3],
                     id.id[4], id.id[5], id.id[6], id.id[7]);
            return make_str(serial);
        }
        case 4: return make_str("Macro Pad Config");
        default: return NULL;
    }
}

// ====================================================================
//  HID CALLBACKS (required by TinyUSB, stubs — we push reports ourselves)
// ====================================================================

uint16_t tud_hid_get_report_cb(uint8_t itf, uint8_t report_id,
                                hid_report_type_t report_type,
                                uint8_t *buffer, uint16_t reqlen) {
    (void)itf; (void)report_id; (void)report_type; (void)buffer; (void)reqlen;
    return 0;
}

void tud_hid_set_report_cb(uint8_t itf, uint8_t report_id,
                            hid_report_type_t report_type,
                            uint8_t const *buffer, uint16_t bufsize) {
    (void)itf; (void)report_id; (void)report_type; (void)buffer; (void)bufsize;
}
