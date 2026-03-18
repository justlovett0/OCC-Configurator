/*
 * controller_bt.h - BLE Advertisement Broadcaster for Guitar Controller
 *
 * NEW APPROACH: Instead of a GATT connection, the controller broadcasts
 * its gamepad report directly inside the BLE advertisement payload.
 * The dongle passively scans and reads the data — no connection needed.
 *
 * This avoids all GATT service discovery, characteristic subscription,
 * and connection state management that can fail silently on the CYW43.
 *
 * Advertisement payload layout (31 bytes max):
 *   [3 bytes] Flags (General Discoverable | BR/EDR Not Supported)
 *   [3 bytes] 16-bit Service UUID: 0xFFE0 (identifies this as our controller)
 *   [15 bytes] Manufacturer Specific Data:
 *       [1 byte]  length (14)
 *       [1 byte]  AD type (0xFF = Manufacturer Specific)
 *       [2 bytes] Company ID: 0xFFFF (reserved for testing)
 *       [1 byte]  Protocol tag: 0x47 ('G' for guitar)
 *       [12 bytes] Report data (buttons, triggers, axes)
 *
 * The dongle identifies us by:
 *   1. The 16-bit service UUID 0xFFE0 in the advertisement
 *   2. The company ID 0xFFFF and protocol tag 0x47 in manufacturer data
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
