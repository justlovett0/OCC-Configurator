/*
 * bt_hid_gamepad.h - Bluetooth LE HID Gamepad for Pico W
 *
 * Uses BLE (Bluetooth Low Energy) HIDS profile — the same approach used
 * by Santroller and every modern wireless gamepad (Switch Pro, DualSense, etc).
 *
 * Why BLE instead of Bluetooth Classic:
 *   - Windows 10/11 fully supports BLE HID gamepads out of the box
 *   - Bluetooth Classic HID on Windows requires legacy drivers that
 *     misclassify non-standard subtypes (guitar, drum, etc.)
 *   - BLE HIDS uses GATT + the HID Service (0x1812), which Windows maps
 *     directly from the HID report descriptor — no SDP subtype games needed
 *
 * The HID report uses a Report ID byte (0x01) as its first byte, which the
 * BLE HIDS stack strips before sending. The report struct itself is unchanged
 * from the working USB XInput layout (buttons, triggers, axes).
 */

#ifndef _BT_HID_GAMEPAD_H_
#define _BT_HID_GAMEPAD_H_

#include <stdint.h>
#include <stdbool.h>

// ── HID Report Structure ──
// First byte is Report ID (always 0x01).
// Remaining bytes match XInput layout for compatibility with build_bt_report().
// Total: 13 bytes (1 report ID + 12 data)
//
// The BLE send function passes (report + 1, size - 1) to strip the report ID,
// because BLE HIDS handles the report ID routing in the GATT layer itself.
typedef struct __attribute__((packed)) {
    uint8_t  report_id;      // Always 0x01
    uint16_t buttons;        // 16 buttons (same bit layout as XInput)
    uint8_t  left_trigger;   // Left trigger  (0-255)
    uint8_t  right_trigger;  // Right trigger (0-255)
    int16_t  left_stick_x;   // Left  stick X axis / Whammy (BT mode only)
    int16_t  left_stick_y;   // Left  stick Y axis
    int16_t  right_stick_x;  // Right stick X (unused in BT mode)
    int16_t  right_stick_y;  // Right stick Y / Tilt
} bt_hid_report_t;

// Initialize Bluetooth LE HID subsystem.
// Must be called after cyw43_arch_init().
// device_name: the Bluetooth discoverable name (from config).
void bt_hid_init(const char *device_name);

// Process Bluetooth events. Call this in the main loop.
// (Used alongside cyw43_arch_poll() in poll mode.)
void bt_hid_task(void);

// Returns true if a Bluetooth host is connected and ready for reports.
bool bt_hid_connected(void);

// Send a gamepad report to the connected host.
// Returns true on success.
bool bt_hid_send_report(const bt_hid_report_t *report);

// Returns true if bt_hid_send_report() can be called
// (connected and not waiting for send-complete).
bool bt_hid_ready(void);

#endif /* _BT_HID_GAMEPAD_H_ */
