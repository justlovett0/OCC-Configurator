/*
 * xinput_host.c - USB Host XInput controller reader via PIO-USB
 *
 * Implements a custom TinyUSB host class driver that claims XInput
 * interfaces (class 0xFF, subclass 0x5D, protocol 0x01), reads
 * interrupt IN reports, and provides them to Core 0 via a spin-locked
 * shared buffer.
 *
 * The driver is registered via usbh_app_driver_get_cb() which TinyUSB
 * calls during host initialization to discover application-provided
 * class drivers.
 */

#include "xinput_host.h"
#include "tusb.h"
#include "host/usbh.h"
#include "host/usbh_pvt.h"
#include "pio_usb.h"
#include "pico/sync.h"
#include <string.h>

//--------------------------------------------------------------------
// Shared state (accessed by both cores, protected by spin lock)
//--------------------------------------------------------------------

static spin_lock_t *_report_lock;
static xinput_report_t _shared_report;
static volatile bool _host_connected;
static volatile bool _report_valid;

//--------------------------------------------------------------------
// Host driver state (Core 1 only)
//--------------------------------------------------------------------

static struct {
    uint8_t dev_addr;
    uint8_t ep_in;
    uint8_t itf_num;
    bool    mounted;
    uint8_t report_buf[32];
} _xinputh;

//--------------------------------------------------------------------
// Custom TinyUSB host class driver callbacks
//--------------------------------------------------------------------

static bool xinputh_init(void) {
    memset(&_xinputh, 0, sizeof(_xinputh));
    return true;
}

static bool xinputh_open(uint8_t rhport, uint8_t dev_addr,
                         tusb_desc_interface_t const *desc_itf,
                         uint16_t max_len) {
    (void)rhport;

    // Only claim XInput interfaces (vendor class 0xFF, subclass 0x5D)
    if (desc_itf->bInterfaceClass    != XINPUT_IF_CLASS ||
        desc_itf->bInterfaceSubClass != XINPUT_IF_SUBCLASS ||
        desc_itf->bInterfaceProtocol != XINPUT_IF_PROTOCOL) {
        return false;
    }

    // Only support one device at a time
    if (_xinputh.mounted) return false;

    _xinputh.dev_addr = dev_addr;
    _xinputh.itf_num  = desc_itf->bInterfaceNumber;

    // Parse the interface descriptor block to find the interrupt IN endpoint
    uint8_t const *p_desc = (uint8_t const *)desc_itf;
    uint16_t drv_len = 0;

    while (drv_len < max_len) {
        uint8_t desc_type = tu_desc_type(p_desc);

        if (desc_type == TUSB_DESC_ENDPOINT) {
            tusb_desc_endpoint_t const *ep_desc =
                (tusb_desc_endpoint_t const *)p_desc;

            if (tu_edpt_dir(ep_desc->bEndpointAddress) == TUSB_DIR_IN) {
                TU_ASSERT(tuh_edpt_open(dev_addr, ep_desc));
                _xinputh.ep_in = ep_desc->bEndpointAddress;
            }
            // We don't need the OUT endpoint (vibration) for passthrough
        }

        drv_len += tu_desc_len(p_desc);
        p_desc   = tu_desc_next(p_desc);
    }

    if (_xinputh.ep_in == 0) return false;

    _xinputh.mounted = true;
    return true;
}

static bool xinputh_set_config(uint8_t dev_addr, uint8_t itf_num) {
    // Start the first IN transfer to begin reading reports
    if (_xinputh.ep_in) {
        usbh_edpt_xfer(dev_addr, _xinputh.ep_in,
                        _xinputh.report_buf, sizeof(_xinputh.report_buf));
    }
    usbh_driver_set_config_complete(dev_addr, itf_num);
    return true;
}

static bool xinputh_xfer_cb(uint8_t dev_addr, uint8_t ep_addr,
                             xfer_result_t result, uint32_t xferred_bytes) {
    if (ep_addr == _xinputh.ep_in) {
        if (result == XFER_RESULT_SUCCESS && xferred_bytes >= 14) {
            // Parse the 20-byte XInput report from raw bytes
            // Report format:
            //   [0]    report_id (0x00)
            //   [1]    report_size (0x14 = 20)
            //   [2-3]  buttons (uint16_t LE)
            //   [4]    left_trigger
            //   [5]    right_trigger
            //   [6-7]  left_stick_x (int16_t LE)
            //   [8-9]  left_stick_y (int16_t LE)
            //   [10-11] right_stick_x (int16_t LE) — whammy
            //   [12-13] right_stick_y (int16_t LE) — tilt
            //   [14-19] reserved
            xinput_report_t report;
            memset(&report, 0, sizeof(report));
            report.report_id     = _xinputh.report_buf[0];
            report.report_size   = _xinputh.report_buf[1];
            report.buttons       = (uint16_t)_xinputh.report_buf[2] |
                                   ((uint16_t)_xinputh.report_buf[3] << 8);
            report.left_trigger  = _xinputh.report_buf[4];
            report.right_trigger = _xinputh.report_buf[5];
            report.left_stick_x  = (int16_t)((uint16_t)_xinputh.report_buf[6] |
                                   ((uint16_t)_xinputh.report_buf[7] << 8));
            report.left_stick_y  = (int16_t)((uint16_t)_xinputh.report_buf[8] |
                                   ((uint16_t)_xinputh.report_buf[9] << 8));
            report.right_stick_x = (int16_t)((uint16_t)_xinputh.report_buf[10] |
                                   ((uint16_t)_xinputh.report_buf[11] << 8));
            report.right_stick_y = (int16_t)((uint16_t)_xinputh.report_buf[12] |
                                   ((uint16_t)_xinputh.report_buf[13] << 8));

            // Update shared state (spin lock for cross-core thread safety)
            uint32_t save = spin_lock_blocking(_report_lock);
            memcpy(&_shared_report, &report, sizeof(xinput_report_t));
            _report_valid   = true;
            _host_connected = true;
            spin_unlock(_report_lock, save);
        }

        // Re-arm the IN transfer for the next report
        usbh_edpt_xfer(dev_addr, _xinputh.ep_in,
                        _xinputh.report_buf, sizeof(_xinputh.report_buf));
    }
    return true;
}

static void xinputh_close(uint8_t dev_addr) {
    if (dev_addr == _xinputh.dev_addr) {
        _xinputh.mounted = false;
        _xinputh.ep_in   = 0;

        uint32_t save = spin_lock_blocking(_report_lock);
        _host_connected = false;
        _report_valid   = false;
        memset(&_shared_report, 0, sizeof(_shared_report));
        spin_unlock(_report_lock, save);
    }
}

//--------------------------------------------------------------------
// Host class driver registration
//
// TinyUSB calls usbh_app_driver_get_cb() during host init to discover
// application-provided class drivers. This is the host-side equivalent
// of usbd_app_driver_get_cb() used by the XInput device driver.
//--------------------------------------------------------------------

static const usbh_class_driver_t _xinput_host_driver = {
#if CFG_TUSB_DEBUG >= 2
    .name = "XInput Host",
#endif
    .init       = xinputh_init,
    .open       = xinputh_open,
    .set_config = xinputh_set_config,
    .xfer_cb    = xinputh_xfer_cb,
    .close      = xinputh_close,
};

usbh_class_driver_t const *usbh_app_driver_get_cb(uint8_t *driver_count) {
    *driver_count = 1;
    return &_xinput_host_driver;
}

//--------------------------------------------------------------------
// Public API
//--------------------------------------------------------------------

void xinput_host_init(void) {
    _report_lock = spin_lock_init(spin_lock_claim_unused(true));
    _host_connected = false;
    _report_valid   = false;
    memset(&_shared_report, 0, sizeof(_shared_report));
    memset(&_xinputh, 0, sizeof(_xinputh));

    // Configure PIO-USB as the host-mode backend for RHPORT1
    pio_usb_configuration_t pio_cfg = PIO_USB_DEFAULT_CONFIG;
    pio_cfg.pin_dp = PIO_USB_DP_PIN;
    tuh_configure(1, TUH_CFGID_RPI_PIO_USB_CONFIGURATION, &pio_cfg);
    tuh_init(1);
}

void xinput_host_task(void) {
    tuh_task();
}

bool xinput_host_connected(void) {
    return _host_connected;
}

bool xinput_host_get_report(xinput_report_t *report) {
    uint32_t save = spin_lock_blocking(_report_lock);
    bool valid = _report_valid;
    if (valid) {
        memcpy(report, &_shared_report, sizeof(xinput_report_t));
    }
    spin_unlock(_report_lock, save);
    return valid;
}
