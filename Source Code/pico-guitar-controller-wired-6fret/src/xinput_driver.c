/*
 * xinput_driver.c - Custom TinyUSB class driver for XInput
 *
 * Handles XInput protocol and detects the magic vibration sequence
 * that triggers a switch to config mode.
 *
 * XInput OUT report format (8 bytes):
 *   Byte 0: 0x00 (report ID)
 *   Byte 1: 0x08 (report size)
 *   Byte 2: 0x00
 *   Byte 3: Left motor speed  (0-255)
 *   Byte 4: Right motor speed (0-255)
 *   Byte 5-7: 0x00
 */

#include "tusb.h"
#include "device/usbd.h"
#include "device/usbd_pvt.h"
#include "xinput_driver.h"
#include "usb_descriptors.h"
#include "pico/stdlib.h"
#include "pico/unique_id.h"
#include "xsm3/xsm3.h"
#include <string.h>

//--------------------------------------------------------------------
// Driver State
//--------------------------------------------------------------------

static struct {
    uint8_t ep_in;
    uint8_t ep_out;
    bool    mounted;
    bool    tx_busy;
    bool    led_report_seen;   // set when Windows/Linux XInput LED OUT report arrives
    uint8_t out_buf[XINPUT_EP_MAX_PACKET];
} _xinput;

//--------------------------------------------------------------------
// Magic Vibration Sequence Detection
//
// The configurator sends 3 specific vibration commands in order
// within MAGIC_TIMEOUT_MS. If all 3 match, we flag for config mode.
//--------------------------------------------------------------------

static struct {
    uint8_t  step;              // Current step in the sequence (0-2)
    uint32_t first_step_ms;     // Timestamp of step 0
    bool     triggered;         // Sequence completed
} _magic;

// Expected (left, right) motor bytes for each step
static const uint8_t magic_sequence[MAGIC_STEP_COUNT][2] = {
    { MAGIC_STEP0_LEFT, MAGIC_STEP0_RIGHT },  // Step 0: 0x47, 0x43
    { MAGIC_STEP1_LEFT, MAGIC_STEP1_RIGHT },  // Step 1: 0x43, 0x47
    { MAGIC_STEP2_LEFT, MAGIC_STEP2_RIGHT },  // Step 2: 0x4F, 0x4B
};

#define MOTOR_TOLERANCE  2  // Allow ±2 for scaling differences

static bool motor_matches(uint8_t actual, uint8_t expected) {
    int diff = (int)actual - (int)expected;
    return (diff >= -MOTOR_TOLERANCE && diff <= MOTOR_TOLERANCE);
}

static void check_magic(const uint8_t *out_report, uint32_t len) {
    if (_magic.triggered) return;
    if (len < 5) return;

    // OUT report: byte 3 = left motor, byte 4 = right motor
    uint8_t left  = out_report[3];
    uint8_t right = out_report[4];

    uint32_t now_ms = to_ms_since_boot(get_absolute_time());

    // Check if current motors match the expected step
    uint8_t step = _magic.step;
    if (motor_matches(left,  magic_sequence[step][0]) &&
        motor_matches(right, magic_sequence[step][1])) {

        if (step == 0) {
            _magic.first_step_ms = now_ms;
        } else {
            // Check timeout from first step
            if ((now_ms - _magic.first_step_ms) > MAGIC_TIMEOUT_MS) {
                // Took too long — restart
                _magic.step = 0;
                return;
            }
        }

        _magic.step++;

        if (_magic.step >= MAGIC_STEP_COUNT) {
            // Full sequence matched!
            _magic.triggered = true;
            _magic.step = 0;
        }
    } else {
        // Mismatch — check if it matches step 0 (restart sequence)
        if (motor_matches(left,  magic_sequence[0][0]) &&
            motor_matches(right, magic_sequence[0][1])) {
            _magic.step = 1;
            _magic.first_step_ms = now_ms;
        } else {
            _magic.step = 0;
        }
    }
}

//--------------------------------------------------------------------
// TinyUSB Class Driver Callbacks
//--------------------------------------------------------------------

static void xinput_init(void) {
    memset(&_xinput, 0, sizeof(_xinput));
    memset(&_magic, 0, sizeof(_magic));
}

static void xinput_reset(uint8_t rhport) {
    (void)rhport;
    memset(&_xinput, 0, sizeof(_xinput));
    // Don't reset _magic — preserve across USB resets
}

static uint16_t xinput_open(uint8_t rhport, tusb_desc_interface_t const *desc_intf, uint16_t max_len) {
    // Claim the main controller interface (5D/01) and the security interface (FD/13).
    // The unknown IF1 (5D/03) is also ours but has no endpoints — claim it too.
    if (desc_intf->bInterfaceClass != XINPUT_IF_CLASS) return 0;
    bool is_security = (desc_intf->bInterfaceSubClass == 0xFD);
    bool is_ctrl     = (desc_intf->bInterfaceSubClass == XINPUT_IF_SUBCLASS);
    if (!is_security && !is_ctrl) return 0;

    uint16_t drv_len = sizeof(tusb_desc_interface_t);
    uint8_t const *p_desc = tu_desc_next(desc_intf);

    while (drv_len < max_len) {
        // Stop if we've reached the next interface — don't consume it
        if (tu_desc_type(p_desc) == TUSB_DESC_INTERFACE) break;

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

    if (is_ctrl) {
        _xinput.mounted = true;
        _xinput.tx_busy = false;
    }
    return drv_len;
}

// Receive buffers for host-to-device challenge packets
static uint8_t _xsm3_init_buf[0x22];    // challenge init (0x22 bytes)
static uint8_t _xsm3_verify_buf[0x16];  // challenge verify (0x16 bytes)
static uint8_t _xsm3_x84_buf[32];       // 0x84 OUT data — accepted, not processed
static uint16_t _xsm3_status = 0x0002;  // 2 = ready

static bool xinput_control_xfer_cb(uint8_t rhport, uint8_t stage, tusb_control_request_t const *request) {
    // Only handle vendor requests
    if (request->bmRequestType_bit.type != TUSB_REQ_TYPE_VENDOR) return true;

    switch (request->bRequest) {
    case 0x81: // Get identification — 360 starts auth here
        if (stage == CONTROL_STAGE_SETUP) {
            // Build serial from board ID
            uint8_t serial[12] = {0};
            pico_unique_board_id_t bid;
            pico_get_unique_board_id(&bid);
            memcpy(serial, bid.id, 8);

            xsm3_set_vid_pid(serial, XINPUT_VID, XINPUT_PID);
            xsm3_initialise_state();
            xsm3_set_identification_data(xsm3_id_data_ms_controller);
            return tud_control_xfer(rhport, request,
                                    (void *)xsm3_id_data_ms_controller, 0x1D);
        }
        return true;

    case 0x82: // Challenge init — 360 sends 0x22-byte encrypted challenge
        if (stage == CONTROL_STAGE_SETUP)
            return tud_control_xfer(rhport, request, _xsm3_init_buf, 0x22);
        if (stage == CONTROL_STAGE_DATA)
            xsm3_do_challenge_init(_xsm3_init_buf);
        return true;

    case 0x83: // Get challenge response (0x30 bytes)
        if (stage == CONTROL_STAGE_SETUP)
            return tud_control_xfer(rhport, request, xsm3_challenge_response, 0x30);
        return true;

    case 0x86: // Status — 0x0002 = response ready
        if (stage == CONTROL_STAGE_SETUP)
            return tud_control_xfer(rhport, request, &_xsm3_status, sizeof(_xsm3_status));
        return true;

    case 0x84: // OUT data from 360 — accept it, no processing needed
        if (stage == CONTROL_STAGE_SETUP)
            return tud_control_xfer(rhport, request, _xsm3_x84_buf,
                                    sizeof(_xsm3_x84_buf));
        return true;

    case 0x87: // Challenge verify — 360 sends 0x16-byte verification packet
        if (stage == CONTROL_STAGE_SETUP)
            return tud_control_xfer(rhport, request, _xsm3_verify_buf, 0x16);
        if (stage == CONTROL_STAGE_DATA)
            xsm3_do_challenge_verify(_xsm3_verify_buf);
        return true;

    default:
        return false;
    }
}

static bool xinput_xfer_cb(uint8_t rhport, uint8_t ep_addr, xfer_result_t result, uint32_t xferred_len) {
    (void)result;

    if (ep_addr == _xinput.ep_in) {
        _xinput.tx_busy = false;
    } else if (ep_addr == _xinput.ep_out) {
        // *** Check for magic vibration sequence ***
        check_magic(_xinput.out_buf, xferred_len);

        // *** Detect XInput LED report (byte[0]=0x01, byte[1]=0x03) ***
        // Windows and Linux xpad both send this within ~500ms of enumeration.
        // PS3 never sends it — absence signals non-XInput host.
        if (xferred_len >= 2 &&
            _xinput.out_buf[0] == 0x01 &&
            _xinput.out_buf[1] == 0x03) {
            _xinput.led_report_seen = true;
        }

        // Rearm OUT endpoint
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

bool xinput_magic_detected(void) {
    if (_magic.triggered) {
        _magic.triggered = false;
        return true;
    }
    return false;
}

bool xinput_led_report_seen(void) {
    return _xinput.led_report_seen;
}
