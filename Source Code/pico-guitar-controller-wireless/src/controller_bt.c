/*
 * controller_bt.c - GATT Peripheral for Guitar Controller
 *
 * Controller runs as a BLE peripheral with custom service 0xFFE0 /
 * characteristic 0xFFE1. The dongle connects, subscribes to notifications,
 * and receives 12-byte gamepad reports at ~250 Hz.
 *
 * Connected BLE uses all 37 data channels with frequency hopping and
 * automatic ACK/retransmit — much better range than the old ADV_NONCONN_IND
 * broadcast which used only 3 fixed advertising channels with no retransmit.
 *
 * Identification: dongle scans for ADV_IND containing service UUID 0xFFE0,
 * then connects, discovers 0xFFE1, and enables notifications.
 */

#include "controller_bt.h"
#include "occ_controller.h"   /* generated from occ_controller.gatt by compile_gatt.py */

#include <string.h>
#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "btstack.h"

#define OCC_SERVICE_UUID_16  0xFFE0
#define DEVICE_NAME_BUF      21   /* 20 chars + NUL */

/* ── Module state ── */
static struct {
    bool                  hci_ready;
    bool                  active;             /* advertising or connected */
    hci_con_handle_t      con_handle;
    bool                  notify_enabled;
    bool                  send_pending;       /* request_can_send_now in flight */
    controller_report_t   pending_report;     /* buffered for next CAN_SEND_NOW */
    char                  device_name[DEVICE_NAME_BUF];
    uint8_t               adv_data[31];
    uint8_t               adv_data_len;
} _ctrl;

/* ── Build advertisement: Flags + Service UUID 0xFFE0 only ──
 * Report data now travels via GATT notifications, not ad payload. */
static void build_adv_data(void) {
    uint8_t *p = _ctrl.adv_data;

    /* Flags: LE General Discoverable, BR/EDR Not Supported */
    *p++ = 0x02;
    *p++ = BLUETOOTH_DATA_TYPE_FLAGS;
    *p++ = 0x06;

    /* Complete 16-bit Service UUID list: 0xFFE0 */
    *p++ = 0x03;
    *p++ = BLUETOOTH_DATA_TYPE_COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS;
    *p++ = (uint8_t)(OCC_SERVICE_UUID_16 & 0xFF);
    *p++ = (uint8_t)(OCC_SERVICE_UUID_16 >> 8);

    _ctrl.adv_data_len = (uint8_t)(p - _ctrl.adv_data);
}

static void start_advertising(void) {
    bd_addr_t null_addr;
    memset(null_addr, 0, sizeof(null_addr));
    gap_advertisements_set_data(_ctrl.adv_data_len, _ctrl.adv_data);
    /* ADV_IND (0x00): connectable undirected — lets dongle initiate connection */
    gap_advertisements_set_params(0x0020, 0x0020, 0x00,
                                  0, null_addr, 0x07, 0x00);
    gap_advertisements_enable(1);
    _ctrl.active = true;
}

/* ── ATT read callback — serves device name ── */
static uint16_t att_read_callback(hci_con_handle_t con_handle,
                                   uint16_t att_handle,
                                   uint16_t offset,
                                   uint8_t *buffer, uint16_t buffer_size) {
    (void)con_handle;
    if (att_handle == ATT_CHARACTERISTIC_GAP_DEVICE_NAME_01_VALUE_HANDLE) {
        return att_read_callback_handle_blob(
            (const uint8_t *)_ctrl.device_name,
            (uint16_t)strlen(_ctrl.device_name),
            offset, buffer, buffer_size);
    }
    return 0;
}

/* ── ATT write callback — CCCD subscription from dongle ── */
static int att_write_callback(hci_con_handle_t con_handle,
                               uint16_t att_handle,
                               uint16_t transaction_mode,
                               uint16_t offset,
                               uint8_t *buffer, uint16_t buffer_size) {
    (void)con_handle;
    (void)transaction_mode;
    (void)offset;
    (void)buffer_size;
    if (att_handle == ATT_CHARACTERISTIC_0xFFE1_01_CLIENT_CONFIGURATION_HANDLE) {
        _ctrl.notify_enabled = (buffer[0] & 0x01) != 0;
        printf("CTRL BT: Notifications %s\n",
               _ctrl.notify_enabled ? "enabled" : "disabled");
    }
    return 0;
}

/* ── ATT packet handler — fires notification when radio is ready ── */
static void att_packet_handler(uint8_t packet_type, uint16_t channel,
                                uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;
    if (packet_type != HCI_EVENT_PACKET) return;
    if (hci_event_packet_get_type(packet) != ATT_EVENT_CAN_SEND_NOW) return;

    /* Snapshot what we're sending — pending_report may change before CAN_SEND_NOW fires */
    controller_report_t just_sent = _ctrl.pending_report;
    att_server_notify(_ctrl.con_handle,
                      ATT_CHARACTERISTIC_0xFFE1_01_VALUE_HANDLE,
                      (const uint8_t *)&just_sent,
                      sizeof(controller_report_t));

    /* If state changed while we were waiting (e.g. button tapped and released),
     * request another send immediately so the transition isn't lost */
    if (memcmp(&_ctrl.pending_report, &just_sent, sizeof(controller_report_t)) != 0) {
        att_server_request_can_send_now_event(_ctrl.con_handle);
        /* send_pending stays true */
    } else {
        _ctrl.send_pending = false;
    }
}

/* ── HCI event handler ── */
static btstack_packet_callback_registration_t hci_cb;

static void packet_handler(uint8_t packet_type, uint16_t channel,
                            uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;
    if (packet_type != HCI_EVENT_PACKET) return;

    switch (hci_event_packet_get_type(packet)) {

        case BTSTACK_EVENT_STATE:
            if (btstack_event_state_get_state(packet) == HCI_STATE_WORKING) {
                _ctrl.hci_ready = true;
                printf("CTRL BT: HCI ready — starting advertising\n");
                start_advertising();
            }
            break;

        case HCI_EVENT_LE_META:
            if (hci_event_le_meta_get_subevent_code(packet) ==
                    HCI_SUBEVENT_LE_CONNECTION_COMPLETE) {
                uint8_t status =
                    hci_subevent_le_connection_complete_get_status(packet);
                if (status == 0) {
                    _ctrl.con_handle =
                        hci_subevent_le_connection_complete_get_connection_handle(packet);
                    printf("CTRL BT: Dongle connected, handle=0x%04x\n",
                           _ctrl.con_handle);
                    /* Dongle is the central — no Windows 15ms floor applies.
                     * Request 7.5–15ms interval for low latency. */
                    gap_request_connection_parameter_update(_ctrl.con_handle,
                        6, 12,   /* 7.5ms–15ms (units of 1.25ms) */
                        0,       /* no slave latency */
                        40);     /* 400ms supervision timeout (units of 10ms) */
                }
            }
            break;

        case HCI_EVENT_DISCONNECTION_COMPLETE: {
            uint16_t handle =
                hci_event_disconnection_complete_get_connection_handle(packet);
            if (handle == _ctrl.con_handle) {
                printf("CTRL BT: Disconnected — restarting advertising\n");
                _ctrl.con_handle     = HCI_CON_HANDLE_INVALID;
                _ctrl.notify_enabled = false;
                _ctrl.send_pending   = false;
                start_advertising();
            }
            break;
        }

        default:
            break;
    }
}

/* ────────────────────────────────────────────────────────────────────────
 * Public API
 * ────────────────────────────────────────────────────────────────────── */

void controller_bt_init(const char *device_name) {
    memset(&_ctrl, 0, sizeof(_ctrl));
    _ctrl.con_handle = HCI_CON_HANDLE_INVALID;

    const char *name = device_name ? device_name : "Guitar Controller";
    strncpy(_ctrl.device_name, name, DEVICE_NAME_BUF - 1);
    _ctrl.device_name[DEVICE_NAME_BUF - 1] = '\0';

    build_adv_data();

    l2cap_init();
    sm_init();
    sm_set_io_capabilities(IO_CAPABILITY_NO_INPUT_NO_OUTPUT);
    sm_set_authentication_requirements(0);   /* no pairing/bonding */

    /* profile_data[] generated from occ_controller.gatt by compile_gatt.py */
    att_server_init(profile_data, att_read_callback, att_write_callback);

    hci_cb.callback = &packet_handler;
    hci_add_event_handler(&hci_cb);

    /* Separate ATT packet handler for CAN_SEND_NOW notifications */
    att_server_register_packet_handler(att_packet_handler);

    printf("CTRL BT: Init done — powering on HCI\n");
    hci_power_control(HCI_POWER_ON);
}

void controller_bt_start_sync(void) {
    if (!_ctrl.hci_ready) return;
    /* If connected, drop the connection so dongle can re-sync with another unit */
    if (_ctrl.con_handle != HCI_CON_HANDLE_INVALID) {
        gap_disconnect(_ctrl.con_handle);
        /* Advertising restarts in the disconnect event handler */
    } else {
        start_advertising();
    }
    printf("CTRL BT: Sync requested\n");
}

void controller_bt_send_report(const controller_report_t *report) {
    if (!_ctrl.notify_enabled) return;
    if (memcmp(report, &_ctrl.pending_report, sizeof(controller_report_t)) == 0)
        return;

    memcpy(&_ctrl.pending_report, report, sizeof(controller_report_t));
    if (_ctrl.send_pending) return;   /* already queued; latest data will be sent */

    _ctrl.send_pending = true;
    att_server_request_can_send_now_event(_ctrl.con_handle);
}

bool controller_bt_connected(void) {
    /* "connected" = GATT client subscribed and ready to receive reports */
    return _ctrl.notify_enabled;
}
