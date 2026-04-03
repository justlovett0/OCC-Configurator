/*
 * dongle_bt.h - GATT Central for Single-Slot Guitar Controller Dongle
 *
 * Scans for any OCC controller (ADV_IND with service UUID 0xFFE0),
 * connects, discovers service/characteristic, subscribes for notifications,
 * and receives 12-byte gamepad reports.
 *
 * Connected BLE: 37-channel frequency hopping + ACK/retransmit for
 * better range vs the old broadcast/scan model.
 */

#ifndef _DONGLE_BT_H_
#define _DONGLE_BT_H_

#include <stdint.h>
#include <stdbool.h>

// ── Report structure received from controller (12 bytes) ──
typedef struct __attribute__((packed)) {
    uint16_t buttons;        // 16 buttons (XInput bit layout)
    uint8_t  left_trigger;   // 0-255
    uint8_t  right_trigger;  // 0-255
    int16_t  left_stick_x;
    int16_t  left_stick_y;
    int16_t  right_stick_x;  // Whammy
    int16_t  right_stick_y;  // Tilt
} dongle_report_t;

// Initialize the BLE scanner subsystem.
// Call after cyw43_arch_init().
void dongle_bt_init(void);

// Start scanning for a controller.
void dongle_bt_start_sync(void);

// Returns true if we are receiving advertisements from a controller.
bool dongle_bt_connected(void);

// Returns true if actively scanning (even if no controller found yet).
bool dongle_bt_scanning(void);

// Returns true if HCI has finished initializing.
bool dongle_bt_hci_ready(void);

// Get the latest received report.
// Returns true if a report has been received since the last call.
bool dongle_bt_get_report(dongle_report_t *out);

#endif /* _DONGLE_BT_H_ */
