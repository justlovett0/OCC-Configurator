/*
 * xinput_driver.c - Custom TinyUSB class driver for XInput
 *
 * Handles XInput protocol for Guitar Alternate controller.
 */

#include "tusb.h"
#include "device/usbd.h"
#include "device/usbd_pvt.h"
#include "xinput_driver.h"
#include "usb_descriptors.h"
#include <string.h>

//--------------------------------------------------------------------
// Driver State
//--------------------------------------------------------------------

static struct {
    uint8_t ep_in;
    uint8_t ep_out;
    bool    mounted;
    bool    tx_busy;
    uint8_t out_buf[XINPUT_EP_MAX_PACKET];
} _xinput;

//--------------------------------------------------------------------
// TinyUSB Class Driver Callbacks
//--------------------------------------------------------------------

static void xinput_init(void) {
    memset(&_xinput, 0, sizeof(_xinput));
}

static void xinput_reset(uint8_t rhport) {
    (void)rhport;
    memset(&_xinput, 0, sizeof(_xinput));
}

static uint16_t xinput_open(uint8_t rhport, tusb_desc_interface_t const *desc_intf, uint16_t max_len) {
    if (desc_intf->bInterfaceClass    != XINPUT_IF_CLASS ||
        desc_intf->bInterfaceSubClass != XINPUT_IF_SUBCLASS) {
        return 0;
    }

    uint16_t drv_len = sizeof(tusb_desc_interface_t);
    uint8_t const *p_desc = tu_desc_next(desc_intf);

    while (drv_len < max_len) {
        if (tu_desc_type(p_desc) == TUSB_DESC_ENDPOINT) {
            tusb_desc_endpoint_t const *ep_desc = (tusb_desc_endpoint_t const *)p_desc;
            TU_ASSERT(usbd_edpt_open(rhport, ep_desc));

            if (tu_edpt_dir(ep_desc->bEndpointAddress) == TUSB_DIR_IN) {
                _xinput.ep_in = ep_desc->bEndpointAddress;
            } else {
                _xinput.ep_out = ep_desc->bEndpointAddress;
                usbd_edpt_xfer(rhport, _xinput.ep_out,
                               _xinput.out_buf, sizeof(_xinput.out_buf));
            }
        }
        drv_len += tu_desc_len(p_desc);
        p_desc   = tu_desc_next(p_desc);
    }

    _xinput.mounted = true;
    _xinput.tx_busy = false;
    return drv_len;
}

static bool xinput_control_xfer_cb(uint8_t rhport, uint8_t stage, tusb_control_request_t const *request) {
    (void)rhport; (void)stage; (void)request;
    return true;
}

static bool xinput_xfer_cb(uint8_t rhport, uint8_t ep_addr, xfer_result_t result, uint32_t xferred_len) {
    (void)result;
    (void)xferred_len;

    if (ep_addr == _xinput.ep_in) {
        _xinput.tx_busy = false;
    } else if (ep_addr == _xinput.ep_out) {
        // Rearm OUT endpoint (consume and discard host→device data)
        usbd_edpt_xfer(rhport, _xinput.ep_out, _xinput.out_buf, sizeof(_xinput.out_buf));
    }

    return true;
}

//--------------------------------------------------------------------
// Driver Registration
//--------------------------------------------------------------------

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

//--------------------------------------------------------------------
// Public API
//--------------------------------------------------------------------

void xinput_driver_init(void) {
    xinput_init();
}

bool xinput_ready(void) {
    return _xinput.mounted && !_xinput.tx_busy && tud_ready();
}

bool xinput_send_report(const xinput_report_t *report) {
    if (!xinput_ready()) return false;
    bool ok = usbd_edpt_xfer(0, _xinput.ep_in, (uint8_t *)report, sizeof(xinput_report_t));
    if (ok) {
        _xinput.tx_busy = true;
    }
    return ok;
}
