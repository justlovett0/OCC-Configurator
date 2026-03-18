/*
 * xinput_driver.c - Custom TinyUSB class driver for XInput (multi-slot)
 *
 * One TinyUSB custom driver handles all XInput interfaces. When TinyUSB
 * parses the config descriptor, it calls xinput_open() for each interface
 * whose class/subclass matches. We use bInterfaceNumber (0-3) as the slot
 * index and store per-slot endpoint addresses and state.
 *
 * XInput OUT report format (8 bytes):
 *   Byte 0: 0x00 (report ID)
 *   Byte 1: 0x08 (report size)
 *   Byte 2: 0x00
 *   Byte 3: Left motor speed  (0-255)
 *   Byte 4: Right motor speed (0-255)
 *   Bytes 5-7: 0x00
 */

#include "tusb.h"
#include "device/usbd.h"
#include "device/usbd_pvt.h"
#include "xinput_driver.h"
#include "usb_descriptors.h"
#include "pico/stdlib.h"
#include <string.h>

#define XINPUT_MAX_SLOTS  4

/* ────────────────────────────────────────────────────────────────── */
/* Per-slot driver state                                              */
/* ────────────────────────────────────────────────────────────────── */

typedef struct {
    uint8_t ep_in;
    uint8_t ep_out;
    bool    mounted;
    bool    tx_busy;
    uint8_t out_buf[XINPUT_EP_MAX_PACKET];
} xinput_slot_t;

static xinput_slot_t _slots[XINPUT_MAX_SLOTS];

/* ────────────────────────────────────────────────────────────────── */
/* TinyUSB class driver callbacks                                     */
/* ────────────────────────────────────────────────────────────────── */

static void xinput_init(void) {
    memset(_slots, 0, sizeof(_slots));
}

static void xinput_reset(uint8_t rhport) {
    (void)rhport;
    memset(_slots, 0, sizeof(_slots));
}

static uint16_t xinput_open(uint8_t rhport, tusb_desc_interface_t const *desc_intf,
                             uint16_t max_len) {
    /* Only claim interfaces with the XInput class/subclass */
    if (desc_intf->bInterfaceClass    != XINPUT_IF_CLASS ||
        desc_intf->bInterfaceSubClass != XINPUT_IF_SUBCLASS) {
        return 0;
    }

    /* Map bInterfaceNumber directly to a slot index */
    uint8_t slot = desc_intf->bInterfaceNumber;
    if (slot >= XINPUT_MAX_SLOTS) return 0;

    uint16_t drv_len = sizeof(tusb_desc_interface_t);
    uint8_t const *p_desc = tu_desc_next(desc_intf);

    while (drv_len < max_len) {
        if (tu_desc_type(p_desc) == TUSB_DESC_ENDPOINT) {
            tusb_desc_endpoint_t const *ep_desc = (tusb_desc_endpoint_t const *)p_desc;
            TU_ASSERT(usbd_edpt_open(rhport, ep_desc));

            if (tu_edpt_dir(ep_desc->bEndpointAddress) == TUSB_DIR_IN) {
                _slots[slot].ep_in = ep_desc->bEndpointAddress;
            } else {
                _slots[slot].ep_out = ep_desc->bEndpointAddress;
                /* Prime the OUT endpoint to receive motor/rumble packets */
                usbd_edpt_xfer(rhport, _slots[slot].ep_out,
                               _slots[slot].out_buf, sizeof(_slots[slot].out_buf));
            }
        }

        drv_len += tu_desc_len(p_desc);
        p_desc   = tu_desc_next(p_desc);

        /* Stop at next interface or end-of-config */
        if (drv_len < max_len && tu_desc_type(p_desc) == TUSB_DESC_INTERFACE) break;
    }

    _slots[slot].mounted  = true;
    _slots[slot].tx_busy  = false;
    return drv_len;
}

static bool xinput_control_xfer_cb(uint8_t rhport, uint8_t stage,
                                    tusb_control_request_t const *request) {
    (void)rhport; (void)stage; (void)request;
    return true;
}

static bool xinput_xfer_cb(uint8_t rhport, uint8_t ep_addr,
                            xfer_result_t result, uint32_t xferred_len) {
    (void)result;
    (void)xferred_len;

    for (uint8_t s = 0; s < XINPUT_MAX_SLOTS; s++) {
        if (!_slots[s].mounted) continue;

        if (ep_addr == _slots[s].ep_in) {
            _slots[s].tx_busy = false;
            return true;
        }

        if (ep_addr == _slots[s].ep_out) {
            /* Rearm the OUT endpoint */
            usbd_edpt_xfer(rhport, _slots[s].ep_out,
                           _slots[s].out_buf, sizeof(_slots[s].out_buf));
            return true;
        }
    }

    return false;
}

/* ────────────────────────────────────────────────────────────────── */
/* Driver registration                                                */
/* ────────────────────────────────────────────────────────────────── */

static const usbd_class_driver_t _xinput_class_driver = {
#if CFG_TUSB_DEBUG >= 2
    .name = "XInput",
#endif
    .init             = xinput_init,
    .reset            = xinput_reset,
    .open             = xinput_open,
    .control_xfer_cb  = xinput_control_xfer_cb,
    .xfer_cb          = xinput_xfer_cb,
    .sof              = NULL,
};

usbd_class_driver_t const* usbd_app_driver_get_cb(uint8_t *driver_count) {
    *driver_count = 1;
    return &_xinput_class_driver;
}

/* ────────────────────────────────────────────────────────────────── */
/* Public API                                                         */
/* ────────────────────────────────────────────────────────────────── */

bool xinput_ready(uint8_t slot) {
    if (slot >= XINPUT_MAX_SLOTS) return false;
    return _slots[slot].mounted && !_slots[slot].tx_busy && tud_ready();
}

bool xinput_send_report(uint8_t slot, const xinput_report_t *report) {
    if (!xinput_ready(slot)) return false;
    bool ok = usbd_edpt_xfer(0, _slots[slot].ep_in,
                              (uint8_t *)report, sizeof(xinput_report_t));
    if (ok) {
        _slots[slot].tx_busy = true;
    }
    return ok;
}
