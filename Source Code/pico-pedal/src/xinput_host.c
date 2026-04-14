/*
 * xinput_host.c - USB Host XInput controller reader via PIO-USB
 *
 * Implements a custom TinyUSB host class driver that claims wired
 * Xbox 360-family interfaces (class 0xFF, subclass 0x5D), reads
 * interrupt IN reports when present, and provides them to Core 0 via
 * a spin-locked shared buffer.
 *
 * The driver is registered via usbh_app_driver_get_cb() which TinyUSB
 * calls during host initialization to discover application-provided
 * class drivers.
 */

#include "xinput_host.h"
#include "tusb.h"
#include "class/hid/hid.h"
#include "host/usbh.h"
#include "host/usbh_pvt.h"
#include "pio_usb.h"
#include "pico/sync.h"
#include "hardware/gpio.h"
#include <string.h>

//--------------------------------------------------------------------
// Shared state (accessed by both cores, protected by spin lock)
//--------------------------------------------------------------------

static spin_lock_t *_report_lock;
static xinput_report_t _shared_report;
static volatile bool _host_connected;
static volatile bool _report_valid;
static volatile bool _any_device_mounted;  // any USB device seen, not just XInput
static volatile uint8_t _core1_status;     // 0=not started, 1=alive, 2=tuh_init done
static uint8_t _usb_host_pin_dp;
static uint8_t _usb_host_pin_dm;

// Debug counters — incremented on Core 1, read by Core 0 for CDC output
static volatile xinput_debug_t _dbg;

// Probe counters — defined here, incremented directly from pio_usb_host.c
volatile uint8_t _xinput_probe_fired = 0;
volatile uint8_t _xinput_probe_real  = 0;

// Bus state — set each SOF frame in pio_usb_host.c, read by Core 0
volatile uint8_t _xinput_root_connected = 0;
volatile uint8_t _xinput_root_suspended = 0;
// Force-reconnect: written by Core 0, cleared in SOF frame callback
volatile bool    _xinput_force_reconnect = false;
// Set by the low-level PIO host when it has to synthetically complete an
// EP0 status OUT stage after repeated NAKs. The next SETUP should wait a bit
// before reusing control EP0 on that device.
volatile bool    _xinput_delay_next_setup = false;
// Enum progress counters
volatile uint8_t _xinput_bus_reset_count  = 0;
volatile uint8_t _xinput_setup_sent_count = 0;
volatile uint16_t _xinput_ep0_nak_count   = 0;
volatile uint16_t _xinput_ep0_noresp_count = 0;
volatile uint16_t _xinput_ep0_badpid_count = 0;
volatile uint16_t _xinput_setup_ack_count = 0;
volatile uint16_t _xinput_setup_fail_count = 0;
volatile uint16_t _xinput_setup_nak_count = 0;
volatile uint16_t _xinput_setup_noresp_count = 0;
volatile uint16_t _xinput_hcd_ep0_complete_count = 0;
volatile uint16_t _xinput_hcd_ep0_in_submit_count = 0;
volatile uint16_t _xinput_hcd_ep0_in_submit_fail_count = 0;
volatile uint16_t _xinput_ep0_in_attempt_count = 0;
volatile uint16_t _xinput_hcd_ep0_out_submit_count = 0;
volatile uint16_t _xinput_hcd_ep0_out_submit_fail_count = 0;
volatile uint16_t _xinput_ep0_out_attempt_count = 0;
volatile uint16_t _xinput_ep0_out_ack_count = 0;
volatile uint16_t _xinput_ep0_out_nak_count = 0;
volatile uint16_t _xinput_ep0_out_noresp_count = 0;
volatile uint16_t _xinput_ep0_out_stall_count = 0;
volatile uint16_t _xinput_ep0_status_out_compat_count = 0;
volatile uint8_t _xinput_last_setup_addr = 0;
volatile uint8_t _xinput_last_setup_bmRequestType = 0;
volatile uint8_t _xinput_last_setup_bRequest = 0;
volatile uint16_t _xinput_last_setup_wValue = 0;

#define XINPUT_DESC_TYPE_RESERVED          0x21
#define XINPUT_SERIAL_NUMBER_WVALUE        0x0000
#define XINPUT_INPUT_CAPS_WVALUE           0x0100
#define XINPUT_VIBRATION_CAPS_WVALUE       0x0000

typedef struct __attribute__((packed)) {
    uint8_t bLength;
    uint8_t bDescriptorType;
    uint8_t flags;
    uint8_t reserved;
    uint8_t subtype;
    uint8_t reserved2;
    uint8_t ep_in;
    uint8_t ep_in_size;
    uint8_t reserved3[5];
    uint8_t ep_out;
    uint8_t ep_out_size;
    uint8_t reserved4[2];
} xinput_desc_t;

typedef struct __attribute__((packed)) {
    uint32_t serial;
} xinput_serial_t;

typedef struct __attribute__((packed)) {
    uint8_t  report_id;
    uint8_t  report_size;
    uint8_t  padding;
    uint8_t  left_motor;
    uint8_t  right_motor;
    uint8_t  padding2[3];
} xinput_vibration_caps_t;

typedef struct __attribute__((packed)) {
    uint8_t  report_id;
    uint8_t  report_size;
    uint16_t buttons;
    uint8_t  left_trigger;
    uint8_t  right_trigger;
    uint16_t left_stick_x;
    uint16_t left_stick_y;
    uint16_t right_stick_x;
    uint16_t right_stick_y;
    uint8_t  reserved[4];
    uint16_t flags;
} xinput_input_caps_t;

//--------------------------------------------------------------------
// Host driver state (Core 1 only)
//--------------------------------------------------------------------

static struct {
    uint8_t dev_addr;
    uint8_t ep_in;
    uint8_t ep_out;
    uint8_t itf_num;
    uint8_t protocol;
    uint8_t subtype;
    uint16_t ep_in_size;
    bool    mounted;
    bool    led_kick_sent;
    uint8_t report_buf[32];
    uint8_t out_buf[8];
} _xinputh;

static bool xinputh_is_supported_protocol(uint8_t protocol) {
    switch (protocol) {
        case 0x01:
        case 0x04:
            return true;
        default:
            return false;
    }
}

static bool xinputh_vendor_get_report(uint8_t dev_addr, uint8_t itf_num,
                                      uint8_t recipient, uint16_t wvalue,
                                      void *buffer, uint16_t wlength) {
    tusb_control_request_t const req = {
        .bmRequestType_bit = {
            .recipient = recipient,
            .type = TUSB_REQ_TYPE_VENDOR,
            .direction = TUSB_DIR_IN
        },
        .bRequest = HID_REQ_CONTROL_GET_REPORT,
        .wValue = wvalue,
        .wIndex = itf_num,
        .wLength = wlength,
    };
    tuh_xfer_t xfer = {
        .daddr = dev_addr,
        .ep_addr = 0,
        .setup = &req,
        .buffer = (uint8_t *)buffer,
        .complete_cb = NULL,
        .user_data = 0,
    };
    return tuh_control_xfer(&xfer);
}

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

    // Record every interface we see — useful for debugging unknown devices
    _dbg.open_attempts++;
    _dbg.last_class    = desc_itf->bInterfaceClass;
    _dbg.last_subclass = desc_itf->bInterfaceSubClass;
    _dbg.last_proto    = desc_itf->bInterfaceProtocol;

    // Only claim wired Xbox 360-family interfaces (vendor class 0xFF, subclass 0x5D)
    if (desc_itf->bInterfaceClass    != XINPUT_IF_CLASS ||
        desc_itf->bInterfaceSubClass != XINPUT_IF_SUBCLASS ||
        !xinputh_is_supported_protocol(desc_itf->bInterfaceProtocol)) {
        return false;
    }

    // Only support one device at a time
    if (_xinputh.mounted) return false;

    _xinputh.dev_addr = dev_addr;
    _xinputh.itf_num  = desc_itf->bInterfaceNumber;
    _xinputh.protocol = desc_itf->bInterfaceProtocol;

    // Parse the interface descriptor block to find the vendor descriptor and
    // the interrupt endpoints used by the XInput interface.
    uint8_t const *p_desc = (uint8_t const *)desc_itf;
    uint16_t drv_len = 0;

    while (drv_len < max_len) {
        uint8_t desc_type = tu_desc_type(p_desc);

        if (desc_type == XINPUT_DESC_TYPE_RESERVED) {
            xinput_desc_t const *x_desc = (xinput_desc_t const *)p_desc;
            _xinputh.subtype = x_desc->subtype;
        }

        if (desc_type == TUSB_DESC_ENDPOINT) {
            tusb_desc_endpoint_t const *ep_desc =
                (tusb_desc_endpoint_t const *)p_desc;

            if (tu_edpt_dir(ep_desc->bEndpointAddress) == TUSB_DIR_IN) {
                TU_ASSERT(tuh_edpt_open(dev_addr, ep_desc));
                _xinputh.ep_in = ep_desc->bEndpointAddress;
                _xinputh.ep_in_size = tu_edpt_packet_size(ep_desc);
            } else {
                TU_ASSERT(tuh_edpt_open(dev_addr, ep_desc));
                _xinputh.ep_out = ep_desc->bEndpointAddress;
            }
        }

        drv_len += tu_desc_len(p_desc);
        p_desc   = tu_desc_next(p_desc);
    }

    if (_xinputh.ep_in == 0) return false;

    _xinputh.mounted = true;
    _dbg.open_claims++;
    return true;
}

static bool xinputh_set_config(uint8_t dev_addr, uint8_t itf_num) {
    uint32_t save = spin_lock_blocking(_report_lock);
    _host_connected = true;
    spin_unlock(_report_lock, save);

    // Some XInput devices expect the standard Xbox vendor GET_REPORT probes
    // during bring-up. Ignore failures and keep enumeration moving.
    xinput_serial_t serial = {0};
    xinput_input_caps_t input_caps = {0};
    xinput_vibration_caps_t vibration_caps = {0};

    (void)xinputh_vendor_get_report(dev_addr, itf_num, TUSB_REQ_RCPT_DEVICE,
                                    XINPUT_SERIAL_NUMBER_WVALUE,
                                    &serial, sizeof(serial));
    (void)xinputh_vendor_get_report(dev_addr, itf_num, TUSB_REQ_RCPT_INTERFACE,
                                    XINPUT_INPUT_CAPS_WVALUE,
                                    &input_caps, sizeof(input_caps));
    (void)xinputh_vendor_get_report(dev_addr, itf_num, TUSB_REQ_RCPT_INTERFACE,
                                    XINPUT_VIBRATION_CAPS_WVALUE,
                                    &vibration_caps, sizeof(vibration_caps));

    // Some downstream Pico guitar firmwares assume a host is "real XInput"
    // only after seeing the standard LED/ring-of-light OUT report. Send a
    // harmless one-shot packet so they stay in XInput mode instead of falling
    // back to HID a few seconds after mount.
    if (_xinputh.ep_out && !_xinputh.led_kick_sent) {
        memset(_xinputh.out_buf, 0, sizeof(_xinputh.out_buf));
        _xinputh.out_buf[0] = 0x01;
        _xinputh.out_buf[1] = 0x03;
        usbh_edpt_xfer(dev_addr, _xinputh.ep_out,
                       _xinputh.out_buf, sizeof(_xinputh.out_buf));
        _xinputh.led_kick_sent = true;
    }

    // Start the first IN transfer to begin reading reports.
    if (_xinputh.ep_in) {
        uint16_t xfer_len = _xinputh.ep_in_size;
        if (xfer_len == 0 || xfer_len > sizeof(_xinputh.report_buf)) {
            xfer_len = sizeof(_xinputh.report_buf);
        }
        usbh_edpt_xfer(dev_addr, _xinputh.ep_in,
                        _xinputh.report_buf, xfer_len);
    }
    usbh_driver_set_config_complete(dev_addr, itf_num);
    return true;
}

static bool xinputh_xfer_cb(uint8_t dev_addr, uint8_t ep_addr,
                             xfer_result_t result, uint32_t xferred_bytes) {
    if (ep_addr == _xinputh.ep_in) {
        if (result != XFER_RESULT_SUCCESS) _dbg.xfer_fail++;
        if (result == XFER_RESULT_SUCCESS && xferred_bytes >= 14) {
            _dbg.xfer_success++;
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
        uint16_t xfer_len = _xinputh.ep_in_size;
        if (xfer_len == 0 || xfer_len > sizeof(_xinputh.report_buf)) {
            xfer_len = sizeof(_xinputh.report_buf);
        }
        usbh_edpt_xfer(dev_addr, _xinputh.ep_in, _xinputh.report_buf, xfer_len);
    }
    return true;
}

static void xinputh_close(uint8_t dev_addr) {
    if (dev_addr == _xinputh.dev_addr) {
        _xinputh.mounted = false;
        _xinputh.ep_in   = 0;
        _xinputh.ep_out  = 0;
        _xinputh.ep_in_size = 0;
        _xinputh.protocol = 0;
        _xinputh.subtype = 0;
        _xinputh.led_kick_sent = false;
        memset(_xinputh.out_buf, 0, sizeof(_xinputh.out_buf));

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
// TinyUSB global host callbacks — fire for ANY device, not just XInput.
// Used to distinguish "nothing plugged in" from "plugged in but wrong class".
//--------------------------------------------------------------------

void tuh_mount_cb(uint8_t dev_addr) {
    (void)dev_addr;
    _any_device_mounted = true;
    _dbg.mount_count++;
}

void tuh_umount_cb(uint8_t dev_addr) {
    (void)dev_addr;
    _any_device_mounted = false;
    _dbg.umount_count++;

    // PIO-USB quirk: TX SM idles in J-state (D+=HIGH, D-=LOW). The RX init path
    // sets GPIO_OVERRIDE_INVERT on both pins, so get_line_state() reads J-state as
    // PORT_PIN_FS_IDLE and immediately triggers a phantom CONNECT on startup.
    // After the phantom enum fails, root->connected stays true (connection_check()
    // only resets it on SE0, which J-state idle never produces). Detection loop is
    // gated by !root->connected → real guitar is never detected.
    //
    // Fix: briefly force SE0 (D+=LOW, D-=LOW) via GPIO output overrides so that
    // connection_check() sees SE0 twice and resets root->connected = false,
    // re-enabling the detection loop for the real device.
    // Runs on Core 1 inside tuh_task(), so sleep_ms() only blocks Core 1.
    gpio_set_outover(_usb_host_pin_dp, GPIO_OVERRIDE_LOW);
    gpio_set_outover(_usb_host_pin_dm, GPIO_OVERRIDE_LOW);
    gpio_set_oeover(_usb_host_pin_dp,  GPIO_OVERRIDE_HIGH);
    gpio_set_oeover(_usb_host_pin_dm,  GPIO_OVERRIDE_HIGH);

    _dbg.se0_count++;
    sleep_ms(3);  // 3 SOF ticks — enough for connection_check() to see SE0 twice

    gpio_set_outover(_usb_host_pin_dp, GPIO_OVERRIDE_NORMAL);
    gpio_set_outover(_usb_host_pin_dm, GPIO_OVERRIDE_NORMAL);
    gpio_set_oeover(_usb_host_pin_dp,  GPIO_OVERRIDE_NORMAL);
    gpio_set_oeover(_usb_host_pin_dm,  GPIO_OVERRIDE_NORMAL);
}

//--------------------------------------------------------------------
// Public API
//--------------------------------------------------------------------

void xinput_host_init(int8_t usb_host_pin, bool usb_host_dm_first) {
    _core1_status = 1;  // Core 1 is alive — set before anything else
    _report_lock = spin_lock_init(spin_lock_claim_unused(true));
    _host_connected    = false;
    _report_valid      = false;
    _any_device_mounted = false;
    _usb_host_pin_dp    = (uint8_t)(usb_host_dm_first ? (usb_host_pin + 1) : usb_host_pin);
    _usb_host_pin_dm    = (uint8_t)(usb_host_dm_first ? usb_host_pin : (usb_host_pin + 1));
    memset(&_shared_report, 0, sizeof(_shared_report));
    memset(&_xinputh, 0, sizeof(_xinputh));

    // Configure PIO-USB as the host-mode backend for RHPORT1.
    // tx_ch=1: PIO-USB default is DMA channel 0, but apa102_init() claims
    // channel 0 first via dma_claim_unused_channel(). pio_usb_bus_init()
    // calls dma_claim_mask() which panics if the channel is already taken,
    // silently halting Core 1. Channel 1 is always free.
    pio_usb_configuration_t pio_cfg = PIO_USB_DEFAULT_CONFIG;
    pio_cfg.pin_dp = _usb_host_pin_dp;
    pio_cfg.pinout = usb_host_dm_first ? PIO_USB_PINOUT_DMDP
                                       : PIO_USB_PINOUT_DPDM;
    pio_cfg.tx_ch  = 1;
    tuh_configure(1, TUH_CFGID_RPI_PIO_USB_CONFIGURATION, &pio_cfg);
    bool tuh_ok = tuh_init(1);
    _core1_status = tuh_ok ? 2 : 3;  // 3 = tuh_init returned false
}

uint8_t xinput_host_core1_status(void) {
    return _core1_status;
}

void xinput_host_task(void) {
    tuh_task();
    // Advance status to 4 on first task loop iteration — proves the loop is running
    if (_core1_status == 2) _core1_status = 4;
}

bool xinput_host_any_device(void) {
    return _any_device_mounted;
}

bool xinput_host_connected(void) {
    return _host_connected;
}

void xinput_host_get_debug(xinput_debug_t *out) {
    // Counters are written on Core 1; reading them on Core 0 without a lock
    // is safe for display — worst case we see a value that's off by one.
    *out = *(xinput_debug_t *)&_dbg;
    out->probe_fired      = _xinput_probe_fired;
    out->probe_real       = _xinput_probe_real;
    out->root_connected   = _xinput_root_connected;
    out->root_suspended   = _xinput_root_suspended;
    out->bus_reset_count  = _xinput_bus_reset_count;
    out->setup_sent_count = _xinput_setup_sent_count;
    out->ep0_nak_count    = _xinput_ep0_nak_count;
    out->ep0_noresp_count = _xinput_ep0_noresp_count;
    out->ep0_badpid_count = _xinput_ep0_badpid_count;
    out->setup_ack_count  = _xinput_setup_ack_count;
    out->setup_fail_count = _xinput_setup_fail_count;
    out->setup_nak_count = _xinput_setup_nak_count;
    out->setup_noresp_count = _xinput_setup_noresp_count;
    out->hcd_ep0_complete_count = _xinput_hcd_ep0_complete_count;
    out->hcd_ep0_in_submit_count = _xinput_hcd_ep0_in_submit_count;
    out->hcd_ep0_in_submit_fail_count = _xinput_hcd_ep0_in_submit_fail_count;
    out->ep0_in_attempt_count = _xinput_ep0_in_attempt_count;
    out->hcd_ep0_out_submit_count = _xinput_hcd_ep0_out_submit_count;
    out->hcd_ep0_out_submit_fail_count = _xinput_hcd_ep0_out_submit_fail_count;
    out->ep0_out_attempt_count = _xinput_ep0_out_attempt_count;
    out->ep0_out_ack_count = _xinput_ep0_out_ack_count;
    out->ep0_out_nak_count = _xinput_ep0_out_nak_count;
    out->ep0_out_noresp_count = _xinput_ep0_out_noresp_count;
    out->ep0_out_stall_count = _xinput_ep0_out_stall_count;
    out->ep0_status_out_compat_count = _xinput_ep0_status_out_compat_count;
    out->last_setup_addr = _xinput_last_setup_addr;
    out->last_setup_bmRequestType = _xinput_last_setup_bmRequestType;
    out->last_setup_bRequest = _xinput_last_setup_bRequest;
    out->last_setup_wValue = _xinput_last_setup_wValue;
}

void xinput_host_force_reconnect(void) {
    _xinput_force_reconnect = true;
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
