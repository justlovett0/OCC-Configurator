/*
 * controller_bt.h - GATT Peripheral for Guitar Controller (wireless)
 *
 * Controller advertises as ADV_IND with service UUID 0xFFE0.
 * The dongle connects, subscribes to characteristic 0xFFE1,
 * and receives 12-byte gamepad reports via GATT notifications.
 *
 * Connected BLE: 37-channel frequency hopping + ACK/retransmit,
 * giving much better range than the old ADV_NONCONN_IND broadcast.
 */

#ifndef _CONTROLLER_BT_H_
#define _CONTROLLER_BT_H_

#include <stdint.h>
#include <stdbool.h>

// ── Report structure embedded in advertisement (12 bytes) ──
typedef struct __attribute__((packed)) {
    uint16_t buttons;        // 16 buttons (XInput bit layout)
    uint8_t  left_trigger;   // 0-255
    uint8_t  right_trigger;  // 0-255
    int16_t  left_stick_x;
    int16_t  left_stick_y;
    int16_t  right_stick_x;  // Whammy
    int16_t  right_stick_y;  // Tilt
} controller_report_t;

// Initialize the BLE broadcaster.
// Call after cyw43_arch_init().
void controller_bt_init(const char *device_name);

// Start advertising (call at boot or when sync is pressed).
void controller_bt_start_sync(void);

// Update the advertisement data with the latest gamepad report.
// Call this at your desired report rate (~250 Hz).
void controller_bt_send_report(const controller_report_t *report);

// Returns true if advertising is active (always true once started).
bool controller_bt_connected(void);

#endif /* _CONTROLLER_BT_H_ */
