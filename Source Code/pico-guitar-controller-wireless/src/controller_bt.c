/*
 * controller_bt.c - GATT peripheral for the wireless guitar dongle mode
 *
 * The controller advertises a custom GATT service (0xFFE0/0xFFE1). In open
 * sync mode it uses normal ADV_IND advertising so a dongle can discover it.
 * After a dongle has fully claimed the controller, it switches to directed
 * low-duty advertising toward that dongle only.
 */

#include "controller_bt.h"
#include "occ_controller.h"

#include <stdio.h>
#include <string.h>

#include "btstack.h"
#include "pico/cyw43_arch.h"
#include "pico/stdlib.h"

#define OCC_SERVICE_UUID_16  0xFFE0
#define DEVICE_NAME_BUF      21
#define ADV_TYPE_INDIRECT    0x00
#define ADV_TYPE_DIRECT_LOW  0x04

static struct {
    bool                    hci_ready;
    bool                    active;
    hci_con_handle_t        con_handle;
    bool                    notify_enabled;
    bool                    send_pending;
    controller_report_t     pending_report;
    char                    device_name[DEVICE_NAME_BUF];
    uint8_t                 adv_data[31];
    uint8_t                 adv_data_len;
    controller_bt_binding_t bound_peer;
    controller_bt_binding_t connected_peer;
    controller_bt_binding_t claimed_peer;
    bool                    claim_pending;
} _ctrl;

static void build_adv_data(void) {
    uint8_t *p = _ctrl.adv_data;

    *p++ = 0x02;
    *p++ = BLUETOOTH_DATA_TYPE_FLAGS;
    *p++ = 0x06;

    *p++ = 0x03;
    *p++ = BLUETOOTH_DATA_TYPE_COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS;
    *p++ = (uint8_t)(OCC_SERVICE_UUID_16 & 0xFF);
    *p++ = (uint8_t)(OCC_SERVICE_UUID_16 >> 8);

    _ctrl.adv_data_len = (uint8_t)(p - _ctrl.adv_data);
}

static void start_open_advertising(void) {
    bd_addr_t null_addr;
    memset(null_addr, 0, sizeof(null_addr));
    gap_advertisements_set_data(_ctrl.adv_data_len, _ctrl.adv_data);
    gap_advertisements_set_params(0x0020, 0x0020, ADV_TYPE_INDIRECT,
                                  0, null_addr, 0x07, 0x00);
    gap_advertisements_enable(1);
    _ctrl.active = true;
}

static void start_locked_advertising(void) {
    if (!_ctrl.bound_peer.valid) {
        start_open_advertising();
        return;
    }

    bd_addr_t peer_addr;
    memcpy(peer_addr, _ctrl.bound_peer.addr, sizeof(peer_addr));
    gap_advertisements_set_data(_ctrl.adv_data_len, _ctrl.adv_data);
    gap_advertisements_set_params(0x00A0, 0x00F0, ADV_TYPE_DIRECT_LOW,
                                  _ctrl.bound_peer.addr_type, peer_addr, 0x07, 0x00);
    gap_advertisements_enable(1);
    _ctrl.active = true;
}

static void start_advertising_for_mode(void) {
    if (_ctrl.bound_peer.valid) {
        start_locked_advertising();
    } else {
        start_open_advertising();
    }
}

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

        if (_ctrl.notify_enabled && _ctrl.connected_peer.valid) {
            if (!_ctrl.bound_peer.valid ||
                _ctrl.bound_peer.addr_type != _ctrl.connected_peer.addr_type ||
                memcmp(_ctrl.bound_peer.addr, _ctrl.connected_peer.addr, CONTROLLER_BT_ADDR_LEN) != 0) {
                _ctrl.bound_peer = _ctrl.connected_peer;
                _ctrl.claimed_peer = _ctrl.connected_peer;
                _ctrl.claim_pending = true;
            }
        }
    }
    return 0;
}

static void att_packet_handler(uint8_t packet_type, uint16_t channel,
                               uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;
    if (packet_type != HCI_EVENT_PACKET) return;
    if (hci_event_packet_get_type(packet) != ATT_EVENT_CAN_SEND_NOW) return;

    controller_report_t just_sent = _ctrl.pending_report;
    att_server_notify(_ctrl.con_handle,
                      ATT_CHARACTERISTIC_0xFFE1_01_VALUE_HANDLE,
                      (const uint8_t *)&just_sent,
                      sizeof(controller_report_t));

    if (memcmp(&_ctrl.pending_report, &just_sent, sizeof(controller_report_t)) != 0) {
        att_server_request_can_send_now_event(_ctrl.con_handle);
    } else {
        _ctrl.send_pending = false;
    }
}

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
                printf("CTRL BT: HCI ready - starting advertising\n");
                start_advertising_for_mode();
            }
            break;

        case HCI_EVENT_LE_META:
            if (hci_event_le_meta_get_subevent_code(packet) ==
                    HCI_SUBEVENT_LE_CONNECTION_COMPLETE) {
                uint8_t status = hci_subevent_le_connection_complete_get_status(packet);
                if (status == 0) {
                    _ctrl.con_handle =
                        hci_subevent_le_connection_complete_get_connection_handle(packet);
                    _ctrl.connected_peer.valid = true;
                    _ctrl.connected_peer.addr_type =
                        hci_subevent_le_connection_complete_get_peer_address_type(packet);
                    hci_subevent_le_connection_complete_get_peer_address(
                        packet, _ctrl.connected_peer.addr);
                    printf("CTRL BT: Dongle connected, handle=0x%04x\n", _ctrl.con_handle);
                    gap_request_connection_parameter_update(_ctrl.con_handle, 6, 12, 0, 40);
                }
            }
            break;

        case HCI_EVENT_DISCONNECTION_COMPLETE: {
            uint16_t handle =
                hci_event_disconnection_complete_get_connection_handle(packet);
            if (handle == _ctrl.con_handle) {
                printf("CTRL BT: Disconnected - restarting advertising\n");
                _ctrl.con_handle = HCI_CON_HANDLE_INVALID;
                _ctrl.notify_enabled = false;
                _ctrl.send_pending = false;
                _ctrl.connected_peer.valid = false;
                start_advertising_for_mode();
            }
            break;
        }

        default:
            break;
    }
}

void controller_bt_init(const char *device_name, const controller_bt_binding_t *binding) {
    memset(&_ctrl, 0, sizeof(_ctrl));
    _ctrl.con_handle = HCI_CON_HANDLE_INVALID;
    if (binding && binding->valid) {
        _ctrl.bound_peer = *binding;
    }

    const char *name = device_name ? device_name : "Guitar Controller";
    strncpy(_ctrl.device_name, name, DEVICE_NAME_BUF - 1);
    _ctrl.device_name[DEVICE_NAME_BUF - 1] = '\0';

    build_adv_data();

    l2cap_init();
    sm_init();
    sm_set_io_capabilities(IO_CAPABILITY_NO_INPUT_NO_OUTPUT);
    sm_set_authentication_requirements(0);

    att_server_init(profile_data, att_read_callback, att_write_callback);

    hci_cb.callback = &packet_handler;
    hci_add_event_handler(&hci_cb);
    att_server_register_packet_handler(att_packet_handler);

    printf("CTRL BT: Init done - powering on HCI\n");
    hci_power_control(HCI_POWER_ON);
}

void controller_bt_start_sync(void) {
    if (!_ctrl.hci_ready) return;
    if (_ctrl.con_handle != HCI_CON_HANDLE_INVALID) {
        gap_disconnect(_ctrl.con_handle);
    } else {
        start_advertising_for_mode();
    }
    printf("CTRL BT: Sync requested\n");
}

void controller_bt_forget_bonding(void) {
    memset(&_ctrl.bound_peer, 0, sizeof(_ctrl.bound_peer));
    memset(&_ctrl.connected_peer, 0, sizeof(_ctrl.connected_peer));
    memset(&_ctrl.claimed_peer, 0, sizeof(_ctrl.claimed_peer));
    _ctrl.claim_pending = false;

    if (!_ctrl.hci_ready) return;
    if (_ctrl.con_handle != HCI_CON_HANDLE_INVALID) {
        gap_disconnect(_ctrl.con_handle);
    } else {
        start_open_advertising();
    }
}

bool controller_bt_take_new_claim(controller_bt_binding_t *out_binding) {
    if (!_ctrl.claim_pending) return false;
    if (out_binding) {
        *out_binding = _ctrl.claimed_peer;
    }
    _ctrl.claim_pending = false;
    return true;
}

bool controller_bt_is_open_sync_mode(void) {
    return !_ctrl.bound_peer.valid;
}

void controller_bt_send_report(const controller_report_t *report) {
    if (!_ctrl.notify_enabled) return;
    if (memcmp(report, &_ctrl.pending_report, sizeof(controller_report_t)) == 0) {
        return;
    }

    memcpy(&_ctrl.pending_report, report, sizeof(controller_report_t));
    if (_ctrl.send_pending) return;

    _ctrl.send_pending = true;
    att_server_request_can_send_now_event(_ctrl.con_handle);
}

bool controller_bt_connected(void) {
    return _ctrl.notify_enabled;
}
