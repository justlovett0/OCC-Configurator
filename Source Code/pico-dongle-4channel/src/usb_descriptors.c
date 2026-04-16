/*
 * usb_descriptors.c - Dynamic USB Descriptors for Multi-Controller Guitar Dongle
 *
 * Normal mode (XInput):
 *   Presents g_num_controllers (1-4) independent XInput Guitar Alternate
 *   interfaces in a single composite USB device. Windows enumerates each
 *   interface as a separate controller using the standard XInput driver.
 *
 * Config mode (CDC):
 *   Falls back to single CDC ACM serial port for the configurator GUI.
 *
 * Per-interface endpoint layout:
 *   Slot 0: IF 0, EP IN 0x81, EP OUT 0x02
 *   Slot 1: IF 1, EP IN 0x83, EP OUT 0x04
 *   Slot 2: IF 2, EP IN 0x85, EP OUT 0x06
 *   Slot 3: IF 3, EP IN 0x87, EP OUT 0x08
 *
 * Each interface descriptor block is exactly 40 bytes:
 *   9  bytes: Interface descriptor
 *   17 bytes: XInput-specific class descriptor (references EP addresses)
 *   7  bytes: Endpoint IN descriptor
 *   7  bytes: Endpoint OUT descriptor
 *
 * Config descriptor total:
 *   9 bytes header + N * 40 bytes interfaces
 */

#include "tusb.h"
#include "usb_descriptors.h"
#include "pico/unique_id.h"
#include <string.h>
#include <stdio.h>

/* ── Globals ─────────────────────────────────────────────────────── */

uint8_t     g_num_controllers = 1;      /* Start with one XInput interface */
uint8_t     g_controller_subtypes[XINPUT_MAX_CONTROLLERS] = {
    XINPUT_SUBTYPE_DONGLE,
    XINPUT_SUBTYPE_DONGLE,
    XINPUT_SUBTYPE_DONGLE,
    XINPUT_SUBTYPE_DONGLE,
};
static const char *g_device_name = "Guitar Controller Dongle";

/* ────────────────────────────────────────────────────────────────── */
/* DEVICE DESCRIPTORS                                                 */
/* ────────────────────────────────────────────────────────────────── */

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

/* ────────────────────────────────────────────────────────────────── */
/* XINPUT CONFIGURATION DESCRIPTOR (dynamic, 1-4 controllers)        */
/*                                                                    */
/* Max size: 9 + 4*40 = 169 bytes                                    */
/* ────────────────────────────────────────────────────────────────── */

#define XINPUT_BYTES_PER_INTERFACE   40
#define XINPUT_CONFIG_HEADER_LEN      9
#define XINPUT_CONFIG_MAX_LEN        (XINPUT_CONFIG_HEADER_LEN + \
                                      XINPUT_MAX_CONTROLLERS * XINPUT_BYTES_PER_INTERFACE)

static uint8_t _xinput_cfg_buf[XINPUT_CONFIG_MAX_LEN];
static uint8_t _xinput_cfg_built_for = 0;   /* rebuild when g_num_controllers changes */
static uint8_t _xinput_cfg_subtypes[XINPUT_MAX_CONTROLLERS] = {0};

static void build_xinput_config_desc(uint8_t num) {
    if (num < 1) num = 1;
    if (num > XINPUT_MAX_CONTROLLERS) num = XINPUT_MAX_CONTROLLERS;

    uint16_t total_len = XINPUT_CONFIG_HEADER_LEN + num * XINPUT_BYTES_PER_INTERFACE;
    uint8_t *p = _xinput_cfg_buf;

    /* ── Configuration descriptor (9 bytes) ── */
    *p++ = 0x09;
    *p++ = TUSB_DESC_CONFIGURATION;
    *p++ = (uint8_t)(total_len & 0xFF);
    *p++ = (uint8_t)(total_len >> 8);
    *p++ = num;    /* bNumInterfaces */
    *p++ = 0x01;   /* bConfigurationValue */
    *p++ = 0x00;   /* iConfiguration */
    *p++ = 0x80;   /* bmAttributes: bus-powered */
    *p++ = 0xFA;   /* bMaxPower: 500 mA */

    for (uint8_t i = 0; i < num; i++) {
        uint8_t ep_in  = (uint8_t)XINPUT_EP_IN_SLOT(i);
        uint8_t ep_out = (uint8_t)XINPUT_EP_OUT_SLOT(i);

        /* ── Interface descriptor (9 bytes) ── */
        *p++ = 0x09;
        *p++ = TUSB_DESC_INTERFACE;
        *p++ = i;                    /* bInterfaceNumber */
        *p++ = 0x00;                 /* bAlternateSetting */
        *p++ = 0x02;                 /* bNumEndpoints */
        *p++ = XINPUT_IF_CLASS;      /* 0xFF */
        *p++ = XINPUT_IF_SUBCLASS;   /* 0x5D */
        *p++ = XINPUT_IF_PROTOCOL;   /* 0x01 */
        *p++ = 0x00;                 /* iInterface */

        /* ── XInput-specific class descriptor (17 bytes, length=0x11) ── */
        *p++ = 0x11;
        *p++ = 0x21;
        *p++ = 0x00;
        *p++ = 0x01;
        *p++ = g_controller_subtypes[i];
        *p++ = 0x25;
        *p++ = ep_in;                      /* IN endpoint address  */
        *p++ = XINPUT_REPORT_SIZE;         /* 20 */
        *p++ = 0x00;
        *p++ = 0x00;
        *p++ = 0x00;
        *p++ = 0x00;
        *p++ = 0x13;
        *p++ = ep_out;                     /* OUT endpoint address */
        *p++ = XINPUT_OUT_REPORT_SIZE;     /* 8 */
        *p++ = 0x00;
        *p++ = 0x00;

        /* ── Endpoint IN descriptor (7 bytes) ── */
        *p++ = 0x07;
        *p++ = TUSB_DESC_ENDPOINT;
        *p++ = ep_in;
        *p++ = TUSB_XFER_INTERRUPT;
        *p++ = XINPUT_EP_MAX_PACKET;       /* 32 */
        *p++ = 0x00;
        *p++ = 0x04;                       /* bInterval: 4 ms */

        /* ── Endpoint OUT descriptor (7 bytes) ── */
        *p++ = 0x07;
        *p++ = TUSB_DESC_ENDPOINT;
        *p++ = ep_out;
        *p++ = TUSB_XFER_INTERRUPT;
        *p++ = XINPUT_EP_MAX_PACKET;       /* 32 */
        *p++ = 0x00;
        *p++ = 0x08;                       /* bInterval: 8 ms */
    }

    _xinput_cfg_built_for = num;
    memcpy(_xinput_cfg_subtypes, g_controller_subtypes, sizeof(_xinput_cfg_subtypes));
}

uint8_t const* tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;

    /* Rebuild config descriptor if controller count changed */
    if (_xinput_cfg_built_for != g_num_controllers ||
        memcmp(_xinput_cfg_subtypes, g_controller_subtypes, sizeof(_xinput_cfg_subtypes)) != 0) {
        build_xinput_config_desc(g_num_controllers);
    }

    return _xinput_cfg_buf;
}

/* ────────────────────────────────────────────────────────────────── */
/* STRING DESCRIPTORS                                                 */
/* ────────────────────────────────────────────────────────────────── */

static const uint16_t string_desc_language[] = {
    (TUSB_DESC_STRING << 8) | (2 + 2), 0x0409
};

static uint16_t _string_desc_buf[64];

static const uint16_t* _make_string_desc(const char *str) {
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
        case 1:  return _make_string_desc(g_device_name);
        case 2:  return _make_string_desc(g_device_name);
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
