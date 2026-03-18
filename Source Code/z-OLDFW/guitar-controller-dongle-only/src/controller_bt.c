/*
 * controller_bt.c - BLE Advertisement Broadcaster for Guitar Controller
 *
 * Broadcasts gamepad reports inside BLE advertisement manufacturer data.
 * The dongle passively scans and reads the report — no connection needed.
 *
 * This is the simplest and most reliable BLE data transfer on the CYW43:
 *   - No GATT server, no services, no characteristics, no subscriptions
 *   - No pairing, no security manager, no bonding
 *   - No connection state machine that can stall or fail
 *   - Just: advertise with data → scanner reads data
 *
 * The advertisement is updated on every call to controller_bt_send_report()
 * by stopping advertisements, updating the payload, and restarting them.
 * At ~250 Hz this gives excellent responsiveness.
 *
 * Identification: The dongle looks for:
 *   1. 16-bit service UUID 0xFFE0 in the advertisement
 *   2. Manufacturer Specific Data with company ID 0xFFFF and tag byte 0x47
 */

#include "controller_bt.h"

#include <string.h>
#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "btstack.h"

// ── Identification constants (must match dongle_bt.c) ──
#define OCC_SERVICE_UUID_16   0xFFE0    // 16-bit service UUID in advertisement
#define OCC_COMPANY_ID        0xFFFF    // Manufacturer Specific Data company ID
#define OCC_PROTOCOL_TAG      0x47      // 'G' for guitar controller

// ────────────────────────────────────────────────────────────────────────
// State
// ────────────────────────────────────────────────────────────────────────

static struct {
    bool             active;           // Advertising is running
    uint8_t          adv_data[31];     // Current advertisement payload
    uint8_t          adv_data_len;
    controller_report_t last_report;   // Last report (for comparison)
    bool             hci_ready;        // HCI stack is powered on
} _ctrl;

// ────────────────────────────────────────────────────────────────────────
// Build advertisement payload with embedded report
// ────────────────────────────────────────────────────────────────────────

static void build_adv_data(const controller_report_t *report) {
    uint8_t *p = _ctrl.adv_data;

    // AD: Flags — General Discoverable | BR/EDR Not Supported
    *p++ = 0x02;                                        // length
    *p++ = BLUETOOTH_DATA_TYPE_FLAGS;                   // type
    *p++ = 0x06;                                        // value

    // AD: Complete List of 16-bit Service UUIDs — 0xFFE0
    // This is the primary identifier the dongle uses to filter scan results.
    *p++ = 0x03;                                        // length
    *p++ = BLUETOOTH_DATA_TYPE_COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS;
    *p++ = (uint8_t)(OCC_SERVICE_UUID_16 & 0xFF);      // UUID low byte
    *p++ = (uint8_t)(OCC_SERVICE_UUID_16 >> 8);         // UUID high byte

    // AD: Manufacturer Specific Data — company ID + tag + 12-byte report
    // Total: 1 (type) + 2 (company) + 1 (tag) + 12 (report) = 16 data bytes
    *p++ = 16;                                          // length (data bytes)
    *p++ = BLUETOOTH_DATA_TYPE_MANUFACTURER_SPECIFIC_DATA;
    *p++ = (uint8_t)(OCC_COMPANY_ID & 0xFF);            // Company ID low
    *p++ = (uint8_t)(OCC_COMPANY_ID >> 8);              // Company ID high
    *p++ = OCC_PROTOCOL_TAG;                            // Protocol tag
    memcpy(p, report, sizeof(controller_report_t));     // 12-byte report
    p += sizeof(controller_report_t);

    _ctrl.adv_data_len = (uint8_t)(p - _ctrl.adv_data);
}

// ────────────────────────────────────────────────────────────────────────
// Packet handler — just tracks HCI power state
// ────────────────────────────────────────────────────────────────────────

static void packet_handler(uint8_t packet_type, uint16_t channel,
                           uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;

    if (packet_type != HCI_EVENT_PACKET) return;

    if (hci_event_packet_get_type(packet) == BTSTACK_EVENT_STATE) {
        if (btstack_event_state_get_state(packet) == HCI_STATE_WORKING) {
            _ctrl.hci_ready = true;
            printf("CTRL BT: HCI ready, starting advertisements\n");

            // Set advertisement parameters
            uint16_t adv_int_min = 0x0020;  // 20ms — fast for low latency
            uint16_t adv_int_max = 0x0020;  // 20ms
            uint8_t  adv_type    = 0x03;    // ADV_NONCONN_IND — non-connectable
            bd_addr_t null_addr;
            memset(null_addr, 0, 6);
            gap_advertisements_set_params(adv_int_min, adv_int_max, adv_type,
                                          0, null_addr, 0x07, 0x00);
            gap_advertisements_set_data(_ctrl.adv_data_len, _ctrl.adv_data);
            gap_advertisements_enable(1);
            _ctrl.active = true;
        }
    }
}

// ────────────────────────────────────────────────────────────────────────
// Public API
// ────────────────────────────────────────────────────────────────────────

void controller_bt_init(const char *device_name) {
    (void)device_name;  // Not used in advertisement-only mode

    memset(&_ctrl, 0, sizeof(_ctrl));

    // Build initial advertisement with zeroed report
    controller_report_t zero_report;
    memset(&zero_report, 0, sizeof(zero_report));
    build_adv_data(&zero_report);

    // Minimal BTstack init — no L2CAP, no SM, no ATT server needed
    l2cap_init();

    // We still need a minimal ATT server for BTstack internals
    static const uint8_t empty_profile[] = { 1, 0x00, 0x00 };
    att_server_init(empty_profile, NULL, NULL);

    // Register HCI event handler
    static btstack_packet_callback_registration_t hci_cb;
    hci_cb.callback = &packet_handler;
    hci_add_event_handler(&hci_cb);

    // Power on — packet_handler will start advertising when HCI is ready
    hci_power_control(HCI_POWER_ON);
}

void controller_bt_start_sync(void) {
    if (!_ctrl.hci_ready) return;

    // (Re)start advertising
    gap_advertisements_set_data(_ctrl.adv_data_len, _ctrl.adv_data);
    gap_advertisements_enable(1);
    _ctrl.active = true;
    printf("CTRL BT: Advertising started\n");
}

void controller_bt_send_report(const controller_report_t *report) {
    if (!_ctrl.hci_ready || !_ctrl.active) return;

    // Only update advertisement if report data changed
    // (avoids unnecessary HCI commands which could stall)
    if (memcmp(report, &_ctrl.last_report, sizeof(controller_report_t)) == 0) {
        return;
    }
    memcpy(&_ctrl.last_report, report, sizeof(controller_report_t));

    // Rebuild advertisement payload with new report data
    build_adv_data(report);

    // Update the advertisement — BTstack handles stopping/restarting internally
    gap_advertisements_set_data(_ctrl.adv_data_len, _ctrl.adv_data);
}

bool controller_bt_connected(void) {
    // In broadcast mode, "connected" means "advertising and dongle can see us"
    // We return true once advertising is active — the dongle is a passive scanner.
    return _ctrl.active;
}
