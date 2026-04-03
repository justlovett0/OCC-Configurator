/*
 * dongle_bt.c - GATT Central for Single-Slot Guitar Controller Dongle
 *
 * Scans for any OCC controller (ADV_IND with service UUID 0xFFE0), connects,
 * discovers service/characteristic, subscribes to notifications, and receives
 * 12-byte gamepad reports.
 *
 * Connected BLE: 37-channel frequency hopping + ACK/retransmit = much better
 * range than the old passive scan / ADV_NONCONN_IND broadcast model.
 *
 * No MAC storage, no bind mode — just grab the first OCC controller seen.
 * On disconnect, restarts scanning and connects to the next controller found.
 *
 * dongle_bt_start_sync() resets state and restarts the search.
 */

#include "dongle_bt.h"

#include <string.h>
#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "hardware/sync.h"
#include "btstack.h"

#define OCC_SERVICE_UUID_16  0xFFE0
#define OCC_CHAR_UUID_16     0xFFE1

/* ── GATT state ── */
typedef enum {
    GATT_IDLE = 0,
    GATT_CONNECTING,
    GATT_DISC_SVC,
    GATT_DISC_CHAR,
    GATT_SUBSCRIBING,
    GATT_READY,
} gatt_state_t;

/* Single registration covers any connection, any characteristic */
static gatt_client_notification_t _notification_listener;

/* ── Module state ── */
static struct {
    bool              hci_ready;
    bool              scanning;
    bool              connecting;
    gatt_state_t      gatt_state;
    hci_con_handle_t  con_handle;

    gatt_client_service_t        service;
    gatt_client_characteristic_t characteristic;

    dongle_report_t   report;
    bool              report_new;
    uint32_t          last_report_ms;
} _dongle;

/* ────────────────────────────────────────────────────────────────── */
/* Helpers                                                            */
/* ────────────────────────────────────────────────────────────────── */

/* Check for service UUID 0xFFE0 in advertisement — identifies OCC controller */
static bool is_occ_advertisement(const uint8_t *adv_data, uint8_t adv_len) {
    uint8_t pos = 0;
    while (pos < adv_len) {
        uint8_t field_len = adv_data[pos];
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
                if (uuid == OCC_SERVICE_UUID_16) return true;
            }
        }
        pos += field_len + 1;
    }
    return false;
}

static void start_scan(void) {
    if (_dongle.scanning || _dongle.connecting) return;
    gap_set_scan_params(0, 0x0020, 0x001E, 0);
    gap_start_scan();
    _dongle.scanning = true;
    printf("DONGLE BT: Scanning for controller\n");
}

static void stop_scan(void) {
    if (!_dongle.scanning) return;
    gap_stop_scan();
    _dongle.scanning = false;
}

/* ────────────────────────────────────────────────────────────────── */
/* GATT client event handler                                          */
/* ────────────────────────────────────────────────────────────────── */

static void gatt_client_handler(uint8_t packet_type, uint16_t channel,
                                  uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;
    if (packet_type != HCI_EVENT_PACKET) return;

    switch (hci_event_packet_get_type(packet)) {

        case GATT_EVENT_SERVICE_QUERY_RESULT:
            if (_dongle.gatt_state != GATT_DISC_SVC) break;
            gatt_event_service_query_result_get_service(packet, &_dongle.service);
            break;

        case GATT_EVENT_CHARACTERISTIC_QUERY_RESULT:
            if (_dongle.gatt_state != GATT_DISC_CHAR) break;
            gatt_event_characteristic_query_result_get_characteristic(
                packet, &_dongle.characteristic);
            break;

        case GATT_EVENT_QUERY_COMPLETE: {
            uint8_t status = gatt_event_query_complete_get_att_status(packet);
            if (status != 0) {
                printf("DONGLE BT: GATT query failed status=%d\n", status);
                gap_disconnect(_dongle.con_handle);
                break;
            }

            switch (_dongle.gatt_state) {

                case GATT_DISC_SVC:
                    _dongle.gatt_state = GATT_DISC_CHAR;
                    gatt_client_discover_characteristics_for_service_by_uuid16(
                        gatt_client_handler, _dongle.con_handle,
                        &_dongle.service, OCC_CHAR_UUID_16);
                    break;

                case GATT_DISC_CHAR:
                    _dongle.gatt_state = GATT_SUBSCRIBING;
                    gatt_client_write_client_characteristic_configuration(
                        gatt_client_handler, _dongle.con_handle,
                        &_dongle.characteristic,
                        GATT_CLIENT_CHARACTERISTICS_CONFIGURATION_NOTIFICATION);
                    break;

                case GATT_SUBSCRIBING:
                    _dongle.gatt_state    = GATT_READY;
                    _dongle.last_report_ms =
                        to_ms_since_boot(get_absolute_time());
                    printf("DONGLE BT: Ready — receiving reports\n");
                    break;

                default:
                    break;
            }
            break;
        }

        case GATT_EVENT_NOTIFICATION: {
            if (_dongle.gatt_state != GATT_READY) break;

            uint16_t vlen = gatt_event_notification_get_value_length(packet);
            if (vlen < sizeof(dongle_report_t)) break;
            const uint8_t *val = gatt_event_notification_get_value(packet);

            uint32_t irq = save_and_disable_interrupts();
            memcpy(&_dongle.report, val, sizeof(dongle_report_t));
            _dongle.report_new    = true;
            _dongle.last_report_ms = to_ms_since_boot(get_absolute_time());
            restore_interrupts(irq);
            break;
        }

        default:
            break;
    }
}

/* ────────────────────────────────────────────────────────────────── */
/* HCI / GAP event handler                                            */
/* ────────────────────────────────────────────────────────────────── */

static btstack_packet_callback_registration_t hci_cb;

static void packet_handler(uint8_t packet_type, uint16_t channel,
                            uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;
    if (packet_type != HCI_EVENT_PACKET) return;

    switch (hci_event_packet_get_type(packet)) {

        case BTSTACK_EVENT_STATE:
            if (btstack_event_state_get_state(packet) == HCI_STATE_WORKING) {
                _dongle.hci_ready = true;
                printf("DONGLE BT: HCI ready\n");
                start_scan();
            }
            break;

        case HCI_EVENT_LE_META: {
            if (hci_event_le_meta_get_subevent_code(packet) !=
                    HCI_SUBEVENT_LE_CONNECTION_COMPLETE) break;

            _dongle.connecting = false;

            uint8_t status =
                hci_subevent_le_connection_complete_get_status(packet);

            if (status != 0) {
                printf("DONGLE BT: Connection failed status=%d — retrying\n", status);
                _dongle.gatt_state = GATT_IDLE;
                start_scan();
                break;
            }

            _dongle.con_handle =
                hci_subevent_le_connection_complete_get_connection_handle(packet);
            _dongle.gatt_state = GATT_DISC_SVC;
            printf("DONGLE BT: Connected handle=0x%04x — discovering\n",
                   _dongle.con_handle);

            /* Enforce tight interval — central API sends LL_CONNECTION_UPDATE_IND */
            gap_update_connection_parameters(_dongle.con_handle,
                6, 12, 0, 40);

            gatt_client_discover_primary_services_by_uuid16(
                gatt_client_handler, _dongle.con_handle, OCC_SERVICE_UUID_16);
            break;
        }

        case HCI_EVENT_DISCONNECTION_COMPLETE: {
            uint16_t con =
                hci_event_disconnection_complete_get_connection_handle(packet);
            if (con != _dongle.con_handle) break;

            printf("DONGLE BT: Disconnected — scanning for next controller\n");
            _dongle.gatt_state  = GATT_IDLE;
            _dongle.con_handle  = HCI_CON_HANDLE_INVALID;
            _dongle.connecting  = false;
            start_scan();
            break;
        }

        case GAP_EVENT_ADVERTISING_REPORT: {
            if (!_dongle.scanning) break;
            if (_dongle.connecting) break;
            if (_dongle.gatt_state != GATT_IDLE) break;

            uint8_t adv_len        = gap_event_advertising_report_get_data_length(packet);
            const uint8_t *adv_data = gap_event_advertising_report_get_data(packet);

            if (!is_occ_advertisement(adv_data, adv_len)) break;

            bd_addr_t addr;
            gap_event_advertising_report_get_address(packet, addr);
            uint8_t addr_type = gap_event_advertising_report_get_address_type(packet);

            stop_scan();
            _dongle.gatt_state = GATT_CONNECTING;
            _dongle.connecting = true;
            gap_connect(addr, (bd_addr_type_t)addr_type);
            printf("DONGLE BT: OCC controller found — connecting\n");
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
    memset(&_dongle, 0, sizeof(_dongle));
    _dongle.con_handle = HCI_CON_HANDLE_INVALID;

    l2cap_init();
    sm_init();
    sm_set_io_capabilities(IO_CAPABILITY_NO_INPUT_NO_OUTPUT);
    sm_set_authentication_requirements(0);

    static const uint8_t empty_profile[] = { 0x00, 0x00 };
    att_server_init(empty_profile, NULL, NULL);

    gatt_client_init();
    /* Receive notifications from any connection / any characteristic */
    gatt_client_listen_for_characteristic_value_updates(
        &_notification_listener, gatt_client_handler,
        GATT_CLIENT_ANY_CONNECTION, NULL);

    hci_cb.callback = &packet_handler;
    hci_add_event_handler(&hci_cb);

    /* Override BTstack defaults (30ms/latency=4) → 7.5–15ms/latency=0.
     * gap_set_connection_parameters persists and is used by every gap_connect() call. */
    gap_set_connection_parameters(
        0x0060, 0x0030,   /* scan interval/window for connection setup */
        6, 12,            /* conn interval min=7.5ms, max=15ms */
        0,                /* no slave latency */
        40,               /* supervision timeout 400ms */
        0x0010, 0x0030);  /* CE length hint */

    printf("DONGLE BT: Init — powering on HCI\n");
    hci_power_control(HCI_POWER_ON);
}

void dongle_bt_start_sync(void) {
    /* Drop existing connection, reset state, start fresh search */
    if (_dongle.con_handle != HCI_CON_HANDLE_INVALID) {
        gap_disconnect(_dongle.con_handle);
        /* scan restarts in disconnect event handler */
    } else {
        _dongle.gatt_state = GATT_IDLE;
        _dongle.connecting = false;
        if (_dongle.hci_ready) start_scan();
    }
    printf("DONGLE BT: Sync requested\n");
}

bool dongle_bt_connected(void) {
    return _dongle.gatt_state == GATT_READY;
}

bool dongle_bt_scanning(void) {
    /* true while still searching (either scanning or mid-connection) */
    return _dongle.scanning || _dongle.connecting ||
           (_dongle.gatt_state > GATT_IDLE && _dongle.gatt_state < GATT_READY);
}

bool dongle_bt_hci_ready(void) {
    return _dongle.hci_ready;
}

bool dongle_bt_get_report(dongle_report_t *out) {
    if (_dongle.last_report_ms == 0) return false;

    uint32_t irq = save_and_disable_interrupts();
    memcpy(out, &_dongle.report, sizeof(dongle_report_t));
    bool was_new = _dongle.report_new;
    _dongle.report_new = false;
    restore_interrupts(irq);
    return was_new;
}
