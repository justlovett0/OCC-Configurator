/*
 * dongle_bt.c - BLE Passive Scanner for Guitar Controller Dongle
 *
 * Continuously scans for BLE advertisements and extracts gamepad reports
 * from any advertisement that matches our identification pattern:
 *   - Contains 16-bit service UUID 0xFFE0
 *   - Contains Manufacturer Specific Data with company 0xFFFF, tag 0x47
 *   - Has at least 12 bytes of report data after the tag
 *
 * Zero-connection approach — the controller broadcasts and the dongle
 * listens. No GATT, no pairing, no address storage.
 *
 * The "connected" state simply means "we received a valid advertisement
 * within the last TIMEOUT_MS".
 */

#include "dongle_bt.h"

#include <string.h>
#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "btstack.h"

// ── Identification constants (must match controller_bt.c) ──
#define OCC_SERVICE_UUID_16   0xFFE0
#define OCC_COMPANY_ID        0xFFFF
#define OCC_PROTOCOL_TAG      0x47

// If no advertisement received within this time, consider disconnected
#define CONTROLLER_TIMEOUT_MS 1000

// ────────────────────────────────────────────────────────────────────────
// State
// ────────────────────────────────────────────────────────────────────────

static struct {
    bool              scanning;
    bool              hci_ready;
    dongle_report_t   report;
    bool              report_new;
    uint32_t          last_report_ms;   // Timestamp of last valid advertisement
} _dongle;

// ────────────────────────────────────────────────────────────────────────
// Advertisement parser
// ────────────────────────────────────────────────────────────────────────

static bool parse_occ_advertisement(const uint8_t *adv_data, uint8_t adv_len,
                                     dongle_report_t *report) {
    bool found_uuid = false;
    const uint8_t *mfr_report = NULL;
    uint8_t mfr_report_len = 0;

    uint8_t pos = 0;
    while (pos < adv_len) {
        uint8_t field_len = adv_data[pos];
        if (field_len == 0) break;
        if (pos + field_len >= adv_len) break;

        uint8_t field_type = adv_data[pos + 1];
        const uint8_t *field_data = &adv_data[pos + 2];
        uint8_t data_len = field_len - 1;

        // Check for 16-bit Service UUID list containing 0xFFE0
        if ((field_type == BLUETOOTH_DATA_TYPE_COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS ||
             field_type == BLUETOOTH_DATA_TYPE_INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS) &&
            data_len >= 2) {
            for (uint8_t i = 0; i + 1 < data_len; i += 2) {
                uint16_t uuid = (uint16_t)field_data[i] | ((uint16_t)field_data[i+1] << 8);
                if (uuid == OCC_SERVICE_UUID_16) {
                    found_uuid = true;
                    break;
                }
            }
        }

        // Check for Manufacturer Specific Data
        if (field_type == BLUETOOTH_DATA_TYPE_MANUFACTURER_SPECIFIC_DATA &&
            data_len >= 3 + (uint8_t)sizeof(dongle_report_t)) {
            uint16_t company = (uint16_t)field_data[0] | ((uint16_t)field_data[1] << 8);
            uint8_t tag = field_data[2];
            if (company == OCC_COMPANY_ID && tag == OCC_PROTOCOL_TAG) {
                mfr_report = &field_data[3];
                mfr_report_len = data_len - 3;
            }
        }

        pos += field_len + 1;
    }

    // Must have BOTH the service UUID and valid manufacturer data
    if (found_uuid && mfr_report && mfr_report_len >= sizeof(dongle_report_t)) {
        memcpy(report, mfr_report, sizeof(dongle_report_t));
        return true;
    }

    return false;
}

// ────────────────────────────────────────────────────────────────────────
// Packet Handler
// ────────────────────────────────────────────────────────────────────────

static void packet_handler(uint8_t packet_type, uint16_t channel,
                           uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;

    if (packet_type != HCI_EVENT_PACKET) return;

    uint8_t event_type = hci_event_packet_get_type(packet);

    switch (event_type) {

        case BTSTACK_EVENT_STATE: {
            uint8_t state = btstack_event_state_get_state(packet);
            printf("DONGLE BT: HCI state changed to %d\n", state);

            if (state == HCI_STATE_WORKING) {
                _dongle.hci_ready = true;
                printf("DONGLE BT: HCI ready — starting scan\n");
                // Start scanning now that HCI is up
                if (_dongle.scanning) {
                    // Passive scan, ~84% duty cycle (interval=20ms, window=16.875ms).
                    // Avoid 100% duty cycle — it overloads the CYW43 event queue.
                    gap_set_scan_params(0, 0x0020, 0x001B, 0);
                    gap_start_scan();
                    printf("DONGLE BT: Scan started\n");
                }
            }
            break;
        }

        case GAP_EVENT_ADVERTISING_REPORT: {
            if (!_dongle.scanning) break;

            uint8_t adv_len = gap_event_advertising_report_get_data_length(packet);
            const uint8_t *adv_data = gap_event_advertising_report_get_data(packet);

            dongle_report_t report;
            if (parse_occ_advertisement(adv_data, adv_len, &report)) {
                memcpy(&_dongle.report, &report, sizeof(dongle_report_t));
                _dongle.report_new = true;
                _dongle.last_report_ms = to_ms_since_boot(get_absolute_time());
            }
            break;
        }

        default:
            break;
    }
}

// ────────────────────────────────────────────────────────────────────────
// Public API
// ────────────────────────────────────────────────────────────────────────

void dongle_bt_init(void) {
    memset(&_dongle, 0, sizeof(_dongle));

    printf("DONGLE BT: Initializing BTstack...\n");

    // Minimal BTstack init for passive scanning
    l2cap_init();

    // Security Manager — required by BTstack HCI state machine to reach
    // HCI_STATE_WORKING on CYW43, even when not using pairing/bonding.
    sm_init();

    // Minimal ATT server (required by BTstack internals even for central-only).
    // Profile is a single 0x0000 terminator entry — the correct empty ATT database.
    static const uint8_t empty_profile[] = { 0x00, 0x00 };
    att_server_init(empty_profile, NULL, NULL);

    // Register HCI event handler
    static btstack_packet_callback_registration_t hci_cb;
    hci_cb.callback = &packet_handler;
    hci_add_event_handler(&hci_cb);

    printf("DONGLE BT: Powering on HCI...\n");

    // Power on — HCI init is async, packet_handler will get
    // BTSTACK_EVENT_STATE when HCI_STATE_WORKING is reached.
    hci_power_control(HCI_POWER_ON);
}

void dongle_bt_start_sync(void) {
    // Reset all state — "forgets" any current controller.
    _dongle.last_report_ms = 0;
    _dongle.report_new = false;
    memset(&_dongle.report, 0, sizeof(dongle_report_t));
    _dongle.scanning = true;

    if (_dongle.hci_ready) {
        gap_stop_scan();

        // Passive scan, ~84% duty cycle (interval=20ms, window=16.875ms).
        // Avoid 100% duty cycle — it overloads the CYW43 event queue.
        gap_set_scan_params(0, 0x0020, 0x001B, 0);
        gap_start_scan();
        printf("DONGLE BT: Scan restarted (accepting any controller)\n");
    } else {
        printf("DONGLE BT: HCI not ready yet — scan will start when ready\n");
    }
}

bool dongle_bt_connected(void) {
    if (!_dongle.scanning) return false;
    if (_dongle.last_report_ms == 0) return false;

    uint32_t now_ms = to_ms_since_boot(get_absolute_time());
    return (now_ms - _dongle.last_report_ms) < CONTROLLER_TIMEOUT_MS;
}

bool dongle_bt_scanning(void) {
    return _dongle.scanning;
}

bool dongle_bt_hci_ready(void) {
    return _dongle.hci_ready;
}

bool dongle_bt_get_report(dongle_report_t *out) {
    if (_dongle.last_report_ms == 0) return false;
    memcpy(out, &_dongle.report, sizeof(dongle_report_t));
    bool was_new = _dongle.report_new;
    _dongle.report_new = false;
    return was_new;
}
