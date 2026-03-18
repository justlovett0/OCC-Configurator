/*
 * dongle_bt.c - Multi-slot BLE Passive Scanner for Guitar Controller Dongle
 *
 * Scans for BLE advertisements from guitar controllers and routes each one
 * to the correct slot (0-3) by matching the advertiser's MAC address.
 *
 * Identification (unchanged from single-controller version):
 *   - 16-bit service UUID 0xFFE0 in the advertisement
 *   - Manufacturer Specific Data: company 0xFFFF, tag 0x47, then 12-byte report
 *
 * The controller firmware is NOT modified. MAC-based routing is transparent
 * to the controller — it just keeps broadcasting as it always did.
 */

#include "dongle_bt.h"

#include <string.h>
#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "btstack.h"

/* ── Identification constants (must match controller_bt.c) ── */
#define OCC_SERVICE_UUID_16   0xFFE0
#define OCC_COMPANY_ID        0xFFFF
#define OCC_PROTOCOL_TAG      0x47

/* A slot is "connected" if its last advertisement arrived within this window */
#define CONTROLLER_TIMEOUT_MS  1000

/* ────────────────────────────────────────────────────────────────── */
/* Per-slot state                                                     */
/* ────────────────────────────────────────────────────────────────── */

typedef struct {
    bool          bound;                    /* true = has a saved MAC             */
    uint8_t       mac[BLE_MAC_LEN];         /* BLE address of bound controller    */
    dongle_report_t report;                 /* Latest received report             */
    bool          report_new;              /* true = report not yet read by app   */
    uint32_t      last_report_ms;           /* Timestamp of last valid adv        */
} slot_state_t;

/* ────────────────────────────────────────────────────────────────── */
/* Module state                                                       */
/* ────────────────────────────────────────────────────────────────── */

static struct {
    bool               hci_ready;
    bool               scanning;
    slot_state_t       slots[DONGLE_MAX_CONTROLLERS];

    /* Bind mode */
    bool               binding;             /* true = waiting for a new controller */
    uint8_t            bind_slot;           /* which slot is being bound           */
    dongle_bt_bind_cb_t bind_cb;            /* callback to invoke on success       */
} _d;

/* ────────────────────────────────────────────────────────────────── */
/* Advertisement parser (unchanged)                                   */
/* ────────────────────────────────────────────────────────────────── */

static bool parse_occ_advertisement(const uint8_t *adv_data, uint8_t adv_len,
                                     dongle_report_t *report) {
    bool found_uuid = false;
    const uint8_t *mfr_report = NULL;
    uint8_t mfr_report_len = 0;

    uint8_t pos = 0;
    while (pos < adv_len) {
        uint8_t field_len  = adv_data[pos];
        if (field_len == 0) break;
        if (pos + field_len >= adv_len) break;

        uint8_t field_type        = adv_data[pos + 1];
        const uint8_t *field_data = &adv_data[pos + 2];
        uint8_t data_len          = field_len - 1;

        if ((field_type == BLUETOOTH_DATA_TYPE_COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS ||
             field_type == BLUETOOTH_DATA_TYPE_INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS) &&
            data_len >= 2) {
            for (uint8_t i = 0; i + 1 < data_len; i += 2) {
                uint16_t uuid = (uint16_t)field_data[i] | ((uint16_t)field_data[i+1] << 8);
                if (uuid == OCC_SERVICE_UUID_16) { found_uuid = true; break; }
            }
        }

        if (field_type == BLUETOOTH_DATA_TYPE_MANUFACTURER_SPECIFIC_DATA &&
            data_len >= 3 + (uint8_t)sizeof(dongle_report_t)) {
            uint16_t company = (uint16_t)field_data[0] | ((uint16_t)field_data[1] << 8);
            uint8_t  tag     = field_data[2];
            if (company == OCC_COMPANY_ID && tag == OCC_PROTOCOL_TAG) {
                mfr_report     = &field_data[3];
                mfr_report_len = data_len - 3;
            }
        }

        pos += field_len + 1;
    }

    if (found_uuid && mfr_report && mfr_report_len >= sizeof(dongle_report_t)) {
        memcpy(report, mfr_report, sizeof(dongle_report_t));
        return true;
    }
    return false;
}

/* ────────────────────────────────────────────────────────────────── */
/* Packet handler                                                     */
/* ────────────────────────────────────────────────────────────────── */

static void packet_handler(uint8_t packet_type, uint16_t channel,
                           uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;

    if (packet_type != HCI_EVENT_PACKET) return;

    uint8_t event_type = hci_event_packet_get_type(packet);

    switch (event_type) {

        case BTSTACK_EVENT_STATE:
            if (btstack_event_state_get_state(packet) == HCI_STATE_WORKING) {
                _d.hci_ready = true;
                printf("DONGLE BT: HCI ready\n");
                if (_d.scanning) {
                    // Passive scan, ~84% duty cycle (interval=20ms, window=16.875ms).
                    // Avoid 100% duty cycle — it overloads the CYW43 event queue.
                    gap_set_scan_params(0, 0x0020, 0x001B, 0);
                    gap_start_scan();
                    printf("DONGLE BT: Scan started\n");
                }
            }
            break;

        case GAP_EVENT_ADVERTISING_REPORT: {
            if (!_d.scanning) break;

            /* Parse the advertisement payload */
            uint8_t adv_len        = gap_event_advertising_report_get_data_length(packet);
            const uint8_t *adv_data = gap_event_advertising_report_get_data(packet);

            dongle_report_t report;
            if (!parse_occ_advertisement(adv_data, adv_len, &report)) break;

            /* Get the advertiser's BLE MAC address */
            bd_addr_t addr;
            gap_event_advertising_report_get_address(packet, addr);

            uint32_t now_ms = to_ms_since_boot(get_absolute_time());

            /* ── Bind mode: save this controller to the target slot ── */
            if (_d.binding) {
                /*
                 * Make sure this MAC isn't already bound to a DIFFERENT slot.
                 * If it's already bound to the exact target slot that's fine —
                 * pressing sync again just refreshes the binding.
                 */
                bool already_other = false;
                for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
                    if (i == _d.bind_slot) continue;
                    if (_d.slots[i].bound &&
                        memcmp(_d.slots[i].mac, addr, BLE_MAC_LEN) == 0) {
                        already_other = true;
                        break;
                    }
                }

                if (!already_other) {
                    uint8_t s = _d.bind_slot;
                    memcpy(_d.slots[s].mac, addr, BLE_MAC_LEN);
                    _d.slots[s].bound           = true;
                    _d.slots[s].report          = report;
                    _d.slots[s].report_new      = true;
                    _d.slots[s].last_report_ms  = now_ms;

                    _d.binding = false;

                    printf("DONGLE BT: Slot %d bound to %02X:%02X:%02X:%02X:%02X:%02X\n",
                           s,
                           addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]);

                    if (_d.bind_cb) {
                        _d.bind_cb(s, addr);
                        _d.bind_cb = NULL;
                    }
                    break;   /* Don't also do normal routing below */
                }
            }

            /* ── Normal mode: route by MAC ── */
            for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
                if (_d.slots[i].bound &&
                    memcmp(_d.slots[i].mac, addr, BLE_MAC_LEN) == 0) {
                    _d.slots[i].report         = report;
                    _d.slots[i].report_new     = true;
                    _d.slots[i].last_report_ms = now_ms;
                    break;
                }
            }
            break;
        }

        default:
            break;
    }
}

/* ────────────────────────────────────────────────────────────────── */
/* Public API                                                         */
/* ────────────────────────────────────────────────────────────────── */

void dongle_bt_init(void) {
    memset(&_d, 0, sizeof(_d));

    /*
     * Minimal BLE Central (scanner) initialisation.
     */
    l2cap_init();

    // Security Manager — required by BTstack HCI state machine to reach
    // HCI_STATE_WORKING on CYW43, even when not using pairing/bonding.
    sm_init();

    // Minimal ATT server (required by BTstack internals even for central-only).
    // Profile is a single 0x0000 terminator entry — the correct empty ATT database.
    static const uint8_t empty_profile[] = { 0x00, 0x00 };
    att_server_init(empty_profile, NULL, NULL);

    static btstack_packet_callback_registration_t hci_cb;
    hci_cb.callback = &packet_handler;
    hci_add_event_handler(&hci_cb);

    /* Start scanning immediately on power-on */
    _d.scanning = true;
    hci_power_control(HCI_POWER_ON);
    /* Actual scan start happens in packet_handler when HCI_STATE_WORKING fires */
}

void dongle_bt_set_bound_mac(uint8_t slot, const uint8_t mac[BLE_MAC_LEN]) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return;
    memcpy(_d.slots[slot].mac, mac, BLE_MAC_LEN);
    _d.slots[slot].bound = true;
}

void dongle_bt_clear_bound_mac(uint8_t slot) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return;
    memset(&_d.slots[slot], 0, sizeof(slot_state_t));
}

void dongle_bt_start_bind(uint8_t slot, dongle_bt_bind_cb_t cb) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return;
    _d.bind_slot = slot;
    _d.bind_cb   = cb;
    _d.binding   = true;
    printf("DONGLE BT: Bind mode started for slot %d\n", slot);
}

void dongle_bt_cancel_bind(void) {
    _d.binding = false;
    _d.bind_cb = NULL;
    printf("DONGLE BT: Bind mode cancelled\n");
}

bool dongle_bt_is_binding(void) {
    return _d.binding;
}

uint8_t dongle_bt_binding_slot(void) {
    return _d.binding ? _d.bind_slot : 0xFF;
}

bool dongle_bt_connected(uint8_t slot) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return false;
    if (!_d.slots[slot].bound) return false;
    if (_d.slots[slot].last_report_ms == 0) return false;
    uint32_t now_ms = to_ms_since_boot(get_absolute_time());
    return (now_ms - _d.slots[slot].last_report_ms) < CONTROLLER_TIMEOUT_MS;
}

bool dongle_bt_get_report(uint8_t slot, dongle_report_t *out) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return false;
    if (_d.slots[slot].last_report_ms == 0) return false;
    memcpy(out, &_d.slots[slot].report, sizeof(dongle_report_t));
    bool was_new = _d.slots[slot].report_new;
    _d.slots[slot].report_new = false;
    return was_new;
}

uint8_t dongle_bt_active_count(void) {
    uint8_t count = 0;
    for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
        if (dongle_bt_connected(i)) count++;
    }
    return count;
}
