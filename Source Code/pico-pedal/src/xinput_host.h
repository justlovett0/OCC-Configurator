/*
 * xinput_host.h - USB Host XInput controller reader
 *
 * Runs on Core 1 via PIO-USB. Reads XInput reports from a connected
 * guitar controller and makes them available to Core 0 for merging
 * with pedal button inputs.
 *
 * Hardware: PIO-USB on two consecutive GPIO pins configured at runtime.
 * The host pin pair comes from pedal_config_t.
 */

#ifndef _XINPUT_HOST_H_
#define _XINPUT_HOST_H_

#include <stdint.h>
#include <stdbool.h>
#include "usb_descriptors.h"

// Initialize the USB host on Core 1. Call from core1_main().
// usb_host_pin is the lower-numbered pin of the consecutive pair.
// usb_host_dm_first = 0 -> D+ on usb_host_pin, D- on usb_host_pin + 1
// usb_host_dm_first = 1 -> D- on usb_host_pin, D+ on usb_host_pin + 1
void xinput_host_init(int8_t usb_host_pin, bool usb_host_dm_first);

// Run one iteration of the host task. Call repeatedly from Core 1 loop.
void xinput_host_task(void);

// Returns true if any USB device is mounted on the host port,
// regardless of whether it was claimed as XInput.
bool xinput_host_any_device(void);

// Returns true if a supported wired host interface is mounted/configured.
bool xinput_host_connected(void);

// Returns 0 if Core 1 hasn't started yet, 1 if alive but tuh_init not done,
// 2 if tuh_init returned. Used to distinguish crash vs hang vs wiring issue.
uint8_t xinput_host_core1_status(void);

// Copy the latest host controller report into *report.
// Returns true if a valid report is available, false if no controller
// is connected or no report has been received yet.
// Thread-safe (uses hardware spin lock).
bool xinput_host_get_report(xinput_report_t *report);

// Debug counters — read from Core 0, written from Core 1 callbacks.
// Lets us trace enumeration events over USB CDC without UART pins.
typedef struct {
    uint8_t mount_count;    // times tuh_mount_cb fired (any device got an address)
    uint8_t umount_count;   // times tuh_umount_cb fired
    uint8_t open_attempts;  // times xinputh_open() was called (interface seen)
    uint8_t open_claims;    // times xinputh_open() returned true (XInput match)
    uint8_t last_class;     // bInterfaceClass of most recent open() call
    uint8_t last_subclass;  // bInterfaceSubClass
    uint8_t last_proto;     // bInterfaceProtocol
    uint8_t se0_count;      // times tuh_umount_cb ran the SE0 recovery fix
    uint8_t xfer_success;   // times a valid report was received
    uint8_t xfer_fail;      // times xfer_cb got a non-SUCCESS result
    uint8_t probe_fired;    // times anti-phantom probe ran (from pio_usb_host.c)
    uint8_t probe_real;     // times probe returned real device detected
    uint8_t root_connected;  // PIO-USB root->connected (1=device seen, 0=idle)
    uint8_t root_suspended;  // PIO-USB root->suspended (1=bus reset in progress)
    uint8_t bus_reset_count;  // times port_reset_start called (enum started)
    uint8_t setup_sent_count; // times SETUP packet sent in usb_setup_transaction
    uint16_t ep0_nak_count;   // EP0 IN got NAK
    uint16_t ep0_noresp_count; // EP0 IN saw no valid response/start
    uint16_t ep0_badpid_count; // EP0 IN got data with unexpected PID
    uint16_t setup_ack_count;  // SETUP packet got ACK
    uint16_t setup_fail_count; // SETUP packet did not get ACK
    uint16_t setup_nak_count;  // SETUP packet got NAK
    uint16_t setup_noresp_count; // SETUP packet got no valid handshake
    uint16_t hcd_ep0_complete_count; // HCD reported EP0 completion event
    uint16_t hcd_ep0_in_submit_count; // TinyUSB HCD queued EP0 IN stage
    uint16_t hcd_ep0_in_submit_fail_count; // TinyUSB tried to queue EP0 IN but start failed
    uint16_t ep0_in_attempt_count; // low-level host loop entered EP0 IN transaction
    uint16_t hcd_ep0_out_submit_count; // TinyUSB HCD queued EP0 OUT status stage
    uint16_t hcd_ep0_out_submit_fail_count; // TinyUSB tried to queue EP0 OUT but start failed
    uint16_t ep0_out_attempt_count; // low-level host loop entered EP0 OUT transaction
    uint16_t ep0_out_ack_count; // EP0 OUT got ACK
    uint16_t ep0_out_nak_count; // EP0 OUT got NAK
    uint16_t ep0_out_noresp_count; // EP0 OUT saw no valid response/start
    uint16_t ep0_out_stall_count; // EP0 OUT got STALL
    uint16_t ep0_status_out_compat_count; // synthetic EP0 status-OUT completions
    uint8_t last_setup_addr; // device address used for the most recent SETUP
    uint8_t last_setup_bmRequestType;
    uint8_t last_setup_bRequest;
    uint16_t last_setup_wValue;
} xinput_debug_t;

void xinput_host_get_debug(xinput_debug_t *out);

// Request a forced disconnect recovery from Core 0.
// Clears root->connected inside the SOF callback on Core 1 so it's GPIO-safe.
void xinput_host_force_reconnect(void);

#endif /* _XINPUT_HOST_H_ */
