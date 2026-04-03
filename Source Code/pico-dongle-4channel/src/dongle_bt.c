/*
 * dongle_bt.c - Multi-slot GATT Central for Guitar Controller Dongle (4-channel)
 *
 * Manages up to 4 BLE connections to guitar controllers. Each slot has its own
 * GATT state machine:
 *
 *   IDLE → CONNECTING (gap_connect called)
 *        → DISC_SVC   (service discovery for 0xFFE0)
 *        → DISC_CHAR  (characteristic discovery for 0xFFE1)
 *        → SUBSCRIBING (writing CCCD to enable notifications)
 *        → READY      (receiving 12-byte gamepad reports via GATT notification)
 *        → IDLE       (on disconnect — auto-reconnects if MAC is known)
 *
 * Bind flow: dongle_bt_start_bind(slot, cb) → scan for ADV_IND with UUID 0xFFE0
 * → connect → discover → subscribe → cb(slot, mac) fires.
 *
 * Auto-reconnect: on disconnect, if slot has a saved MAC, calls gap_connect(mac)
 * directly (no scan needed). Controller's ADV_IND will be received eventually.
 *
 * Only one gap_connect() is in flight at a time (BLE HCI limitation).
 * Pending reconnects queue up via try_start_pending_connections().
 */

#include "dongle_bt.h"

#include <string.h>
#include <stdio.h>

#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "hardware/sync.h"
#include "btstack.h"

#define OCC_SERVICE_UUID_16   0xFFE0
#define OCC_CHAR_UUID_16      0xFFE1

/* ────────────────────────────────────────────────────────────────── */
/* GATT state machine per slot                                        */
/* ────────────────────────────────────────────────────────────────── */

typedef enum {
    GATT_IDLE = 0,      /* not connected, not trying */
    GATT_CONNECTING,    /* gap_connect() called, waiting for result */
    GATT_DISC_SVC,      /* discovering primary service 0xFFE0 */
    GATT_DISC_CHAR,     /* discovering characteristic 0xFFE1 */
    GATT_SUBSCRIBING,   /* writing CCCD to enable notifications */
    GATT_READY,         /* subscribed, reports arriving via notifications */
} gatt_state_t;

typedef struct {
    bool              bound;
    uint8_t           mac[BLE_MAC_LEN];
    uint8_t           addr_type;
    hci_con_handle_t  con_handle;
    gatt_state_t      gatt_state;

    gatt_client_service_t        service;
    gatt_client_characteristic_t characteristic;

    dongle_report_t   report;
    bool              report_new;
    uint32_t          last_report_ms;
} slot_state_t;

/* ────────────────────────────────────────────────────────────────── */
/* Module state                                                       */
/* ────────────────────────────────────────────────────────────────── */

/* Single registration covers all connections and all characteristics */
static gatt_client_notification_t _notification_listener;

static struct {
    bool               hci_ready;
    bool               scanning;
    bool               connecting;       /* one gap_connect() in flight */
    slot_state_t       slots[DONGLE_MAX_CONTROLLERS];

    /* Bind mode */
    bool               binding;
    uint8_t            bind_slot;
    dongle_bt_bind_cb_t bind_cb;
} _d;

/* ────────────────────────────────────────────────────────────────── */
/* Helpers                                                            */
/* ────────────────────────────────────────────────────────────────── */

static uint8_t find_slot_by_con_handle(hci_con_handle_t con) {
    for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
        if (_d.slots[i].con_handle == con &&
            _d.slots[i].gatt_state != GATT_IDLE) {
            return i;
        }
    }
    return 0xFF;
}

static uint8_t find_slot_by_mac(const bd_addr_t addr) {
    for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
        if (_d.slots[i].bound &&
            memcmp(_d.slots[i].mac, addr, BLE_MAC_LEN) == 0) {
            return i;
        }
    }
    return 0xFF;
}

/* Check UUID 0xFFE0 in advertisement — identifies an OCC controller */
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

/* Start or restart scanning (passive, ~94% duty cycle) */
static void start_scan(void) {
    if (_d.scanning) return;
    gap_set_scan_params(0, 0x0020, 0x001E, 0);
    gap_start_scan();
    _d.scanning = true;
    printf("DONGLE BT: Scan started\n");
}

static void stop_scan(void) {
    if (!_d.scanning) return;
    gap_stop_scan();
    _d.scanning = false;
}

/*
 * Try to make progress on pending work:
 *  1. Reconnect bound+IDLE slots directly (no scan needed — direct address connect)
 *  2. Start scan when in bind mode (looking for new/unknown controller)
 *
 * Only one gap_connect() at a time — this serialises multiple reconnects.
 */
static void try_start_pending_connections(void) {
    if (_d.connecting) return;

    /* Direct reconnect for slots with a known MAC */
    for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
        slot_state_t *s = &_d.slots[i];
        if (s->bound && s->gatt_state == GATT_IDLE) {
            s->gatt_state = GATT_CONNECTING;
            s->con_handle = HCI_CON_HANDLE_INVALID;
            _d.connecting = true;
            stop_scan();
            gap_connect(s->mac, (bd_addr_type_t)s->addr_type);
            printf("DONGLE BT: Reconnecting slot %d\n", i);
            return;
        }
    }

    /* Need scan for bind mode */
    if (_d.binding) {
        start_scan();
    }
}

/* ────────────────────────────────────────────────────────────────── */
/* GATT client event handler                                          */
/*                                                                    */
/* Used as both:                                                      */
/*   gatt_client_register_handler() → receives GATT_EVENT_NOTIFICATION*/
/*   per-operation callback        → receives discovery/complete events*/
/*                                                                    */
/* State transitions prevent double-processing if an event arrives   */
/* via both paths (in practice they use separate event codes).       */
/* ────────────────────────────────────────────────────────────────── */

static void gatt_client_handler(uint8_t packet_type, uint16_t channel,
                                  uint8_t *packet, uint16_t size) {
    (void)channel;
    (void)size;
    if (packet_type != HCI_EVENT_PACKET) return;

    uint8_t event_type = hci_event_packet_get_type(packet);

    switch (event_type) {

        /* ── Service discovery result ── */
        case GATT_EVENT_SERVICE_QUERY_RESULT: {
            hci_con_handle_t con = gatt_event_service_query_result_get_handle(packet);
            uint8_t s = find_slot_by_con_handle(con);
            if (s >= DONGLE_MAX_CONTROLLERS) break;
            if (_d.slots[s].gatt_state != GATT_DISC_SVC) break;
            gatt_event_service_query_result_get_service(packet, &_d.slots[s].service);
            break;
        }

        /* ── Characteristic discovery result ── */
        case GATT_EVENT_CHARACTERISTIC_QUERY_RESULT: {
            hci_con_handle_t con =
                gatt_event_characteristic_query_result_get_handle(packet);
            uint8_t s = find_slot_by_con_handle(con);
            if (s >= DONGLE_MAX_CONTROLLERS) break;
            if (_d.slots[s].gatt_state != GATT_DISC_CHAR) break;
            gatt_event_characteristic_query_result_get_characteristic(
                packet, &_d.slots[s].characteristic);
            break;
        }

        /* ── Operation complete — advance the state machine ── */
        case GATT_EVENT_QUERY_COMPLETE: {
            hci_con_handle_t con = gatt_event_query_complete_get_handle(packet);
            uint8_t s = find_slot_by_con_handle(con);
            if (s >= DONGLE_MAX_CONTROLLERS) break;

            uint8_t status = gatt_event_query_complete_get_att_status(packet);
            if (status != 0) {
                printf("DONGLE BT: GATT query failed status=%d slot=%d\n", status, s);
                gap_disconnect(_d.slots[s].con_handle);
                break;
            }

            switch (_d.slots[s].gatt_state) {

                case GATT_DISC_SVC:
                    /* Service found → discover the 0xFFE1 characteristic */
                    _d.slots[s].gatt_state = GATT_DISC_CHAR;
                    gatt_client_discover_characteristics_for_service_by_uuid16(
                        gatt_client_handler, con,
                        &_d.slots[s].service, OCC_CHAR_UUID_16);
                    break;

                case GATT_DISC_CHAR:
                    /* Characteristic found → enable notifications via CCCD */
                    _d.slots[s].gatt_state = GATT_SUBSCRIBING;
                    gatt_client_write_client_characteristic_configuration(
                        gatt_client_handler, con,
                        &_d.slots[s].characteristic,
                        GATT_CLIENT_CHARACTERISTICS_CONFIGURATION_NOTIFICATION);
                    break;

                case GATT_SUBSCRIBING:
                    /* Subscribed — reports will now arrive as notifications */
                    _d.slots[s].gatt_state    = GATT_READY;
                    _d.slots[s].last_report_ms =
                        to_ms_since_boot(get_absolute_time());
                    printf("DONGLE BT: Slot %d READY (%02X:%02X:%02X:%02X:%02X:%02X)\n",
                           s,
                           _d.slots[s].mac[0], _d.slots[s].mac[1],
                           _d.slots[s].mac[2], _d.slots[s].mac[3],
                           _d.slots[s].mac[4], _d.slots[s].mac[5]);

                    if (_d.binding && _d.bind_slot == s) {
                        _d.binding = false;
                        if (_d.bind_cb) {
                            _d.bind_cb(s, _d.slots[s].mac);
                            _d.bind_cb = NULL;
                        }
                    }
                    break;

                default:
                    break;
            }
            break;
        }

        /* ── Incoming gamepad report notification ── */
        case GATT_EVENT_NOTIFICATION: {
            hci_con_handle_t con = gatt_event_notification_get_handle(packet);
            uint8_t s = find_slot_by_con_handle(con);
            if (s >= DONGLE_MAX_CONTROLLERS) break;
            if (_d.slots[s].gatt_state != GATT_READY) break;

            uint16_t vlen = gatt_event_notification_get_value_length(packet);
            if (vlen < sizeof(dongle_report_t)) break;

            const uint8_t *val = gatt_event_notification_get_value(packet);

            /* IRQ-safe copy — main loop reads this without disable */
            uint32_t irq = save_and_disable_interrupts();
            memcpy(&_d.slots[s].report, val, sizeof(dongle_report_t));
            _d.slots[s].report_new    = true;
            _d.slots[s].last_report_ms = to_ms_since_boot(get_absolute_time());
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

        /* ── BT stack up — start scanning ── */
        case BTSTACK_EVENT_STATE:
            if (btstack_event_state_get_state(packet) == HCI_STATE_WORKING) {
                _d.hci_ready = true;
                printf("DONGLE BT: HCI ready\n");
                try_start_pending_connections();
            }
            break;

        /* ── Connection established ── */
        case HCI_EVENT_LE_META: {
            if (hci_event_le_meta_get_subevent_code(packet) !=
                    HCI_SUBEVENT_LE_CONNECTION_COMPLETE) break;

            _d.connecting = false;

            uint8_t status =
                hci_subevent_le_connection_complete_get_status(packet);

            bd_addr_t addr;
            hci_subevent_le_connection_complete_get_peer_address(packet, addr);

            uint8_t s = find_slot_by_mac(addr);

            if (status != 0) {
                printf("DONGLE BT: Connection failed status=%d\n", status);
                /* Reset state for this slot so retry is attempted */
                if (s < DONGLE_MAX_CONTROLLERS)
                    _d.slots[s].gatt_state = GATT_IDLE;
                try_start_pending_connections();
                break;
            }

            hci_con_handle_t con =
                hci_subevent_le_connection_complete_get_connection_handle(packet);

            if (s >= DONGLE_MAX_CONTROLLERS) {
                /* MAC not recognised — close connection */
                printf("DONGLE BT: Unknown MAC, disconnecting\n");
                gap_disconnect(con);
                try_start_pending_connections();
                break;
            }

            _d.slots[s].con_handle  = con;
            _d.slots[s].gatt_state  = GATT_DISC_SVC;
            printf("DONGLE BT: Connected slot %d handle=0x%04x — discovering\n",
                   s, con);

            /* Enforce tight interval — central API sends LL_CONNECTION_UPDATE_IND */
            gap_update_connection_parameters(con,
                6, 12,    /* 7.5–15ms */
                0,        /* no slave latency */
                40);      /* 400ms supervision timeout */

            gatt_client_discover_primary_services_by_uuid16(
                gatt_client_handler, con, OCC_SERVICE_UUID_16);

            /* Check for other pending reconnects */
            try_start_pending_connections();
            break;
        }

        /* ── Disconnection — reset slot, auto-reconnect if MAC known ── */
        case HCI_EVENT_DISCONNECTION_COMPLETE: {
            uint16_t con =
                hci_event_disconnection_complete_get_connection_handle(packet);
            uint8_t s = find_slot_by_con_handle(con);
            if (s >= DONGLE_MAX_CONTROLLERS) break;

            printf("DONGLE BT: Slot %d disconnected\n", s);
            _d.slots[s].gatt_state  = GATT_IDLE;
            _d.slots[s].con_handle  = HCI_CON_HANDLE_INVALID;

            /* If this slot was mid-bind, cancel */
            if (_d.binding && _d.bind_slot == s) {
                _d.binding = false;
                _d.bind_cb = NULL;
            }

            /* Auto-reconnect: dongle_bt.c handles this internally */
            try_start_pending_connections();
            break;
        }

        /* ── Scan result — look for OCC controller to bind ── */
        case GAP_EVENT_ADVERTISING_REPORT: {
            if (!_d.scanning) break;
            if (!_d.binding)  break;   /* scan only during bind */

            uint8_t adv_len        = gap_event_advertising_report_get_data_length(packet);
            const uint8_t *adv_data = gap_event_advertising_report_get_data(packet);

            if (!is_occ_advertisement(adv_data, adv_len)) break;

            bd_addr_t addr;
            gap_event_advertising_report_get_address(packet, addr);
            uint8_t addr_type = gap_event_advertising_report_get_address_type(packet);

            /* Reject if this MAC is already bound to a different slot */
            for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
                if (i == _d.bind_slot) continue;
                if (_d.slots[i].bound &&
                    memcmp(_d.slots[i].mac, addr, BLE_MAC_LEN) == 0)
                    goto done; /* already bound elsewhere */
            }

            {
                uint8_t s = _d.bind_slot;
                memcpy(_d.slots[s].mac, addr, BLE_MAC_LEN);
                _d.slots[s].addr_type  = addr_type;
                _d.slots[s].bound      = true;
                _d.slots[s].gatt_state = GATT_CONNECTING;
                _d.slots[s].con_handle = HCI_CON_HANDLE_INVALID;

                stop_scan();
                _d.connecting = true;
                gap_connect(addr, (bd_addr_type_t)addr_type);
                printf("DONGLE BT: Bind slot %d — connecting to %02X:%02X:%02X:%02X:%02X:%02X\n",
                       s,
                       addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]);
            }
done:
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
    for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++)
        _d.slots[i].con_handle = HCI_CON_HANDLE_INVALID;

    l2cap_init();
    sm_init();
    sm_set_io_capabilities(IO_CAPABILITY_NO_INPUT_NO_OUTPUT);
    sm_set_authentication_requirements(0);

    static const uint8_t empty_profile[] = { 0x00, 0x00 };
    att_server_init(empty_profile, NULL, NULL);

    gatt_client_init();
    /* Register for notifications from any connection / any characteristic */
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

void dongle_bt_set_bound_mac(uint8_t slot, const uint8_t mac[BLE_MAC_LEN]) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return;
    memcpy(_d.slots[slot].mac, mac, BLE_MAC_LEN);
    _d.slots[slot].addr_type = 0;   /* assume public; addr_type not exposed in API */
    _d.slots[slot].bound     = true;
    /* Actual connection starts when HCI is ready via try_start_pending_connections */
}

void dongle_bt_clear_bound_mac(uint8_t slot) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return;
    if (_d.slots[slot].gatt_state != GATT_IDLE &&
        _d.slots[slot].con_handle != HCI_CON_HANDLE_INVALID) {
        gap_disconnect(_d.slots[slot].con_handle);
    }
    memset(&_d.slots[slot], 0, sizeof(slot_state_t));
    _d.slots[slot].con_handle = HCI_CON_HANDLE_INVALID;
}

void dongle_bt_start_bind(uint8_t slot, dongle_bt_bind_cb_t cb) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return;

    /* Drop existing connection for this slot if any */
    if (_d.slots[slot].gatt_state != GATT_IDLE &&
        _d.slots[slot].con_handle != HCI_CON_HANDLE_INVALID) {
        gap_disconnect(_d.slots[slot].con_handle);
    }
    /* Clear slot state — new controller will overwrite MAC */
    memset(&_d.slots[slot], 0, sizeof(slot_state_t));
    _d.slots[slot].con_handle = HCI_CON_HANDLE_INVALID;

    _d.bind_slot = slot;
    _d.bind_cb   = cb;
    _d.binding   = true;
    printf("DONGLE BT: Bind mode started for slot %d\n", slot);

    if (_d.hci_ready)
        try_start_pending_connections();
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
    return _d.slots[slot].gatt_state == GATT_READY;
}

bool dongle_bt_get_report(uint8_t slot, dongle_report_t *out) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return false;
    if (_d.slots[slot].last_report_ms == 0) return false;

    uint32_t irq = save_and_disable_interrupts();
    memcpy(out, &_d.slots[slot].report, sizeof(dongle_report_t));
    bool was_new = _d.slots[slot].report_new;
    _d.slots[slot].report_new = false;
    restore_interrupts(irq);
    return was_new;
}

uint8_t dongle_bt_active_count(void) {
    uint8_t count = 0;
    for (uint8_t i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
        if (dongle_bt_connected(i)) count++;
    }
    return count;
}
