/*
 * dongle_bt.h - Multi-slot GATT Central for Guitar Controller Dongle (4-channel)
 *
 * Manages up to 4 connected BLE slots. Each slot has its own GATT state
 * machine: scan → connect → discover service 0xFFE0 → discover char
 * 0xFFE1 → subscribe → receive 12-byte reports via notifications.
 *
 * Bind flow:
 *   1. Call dongle_bt_start_bind(slot, callback).
 *   2. First OCC ADV_IND seen → connect → GATT setup → callback fires.
 *   3. MAC saved; dongle_bt.c auto-reconnects on disconnect internally.
 *
 * "Connected" = GATT subscription active. On disconnect, dongle_bt.c
 * calls gap_connect(mac) directly — main.c does not call start_bind.
 */

#ifndef _DONGLE_BT_H_
#define _DONGLE_BT_H_

#include <stdint.h>
#include <stdbool.h>

#define DONGLE_MAX_CONTROLLERS   4
#define BLE_MAC_LEN              6
#define DONGLE_CONTROLLER_KIND_GUITAR  0
#define DONGLE_CONTROLLER_KIND_DRUM    1

/* ── Report structure received from controller (12 bytes, unchanged) ── */
typedef struct __attribute__((packed)) {
    uint16_t buttons;
    uint8_t  left_trigger;
    uint8_t  right_trigger;
    int16_t  left_stick_x;
    int16_t  left_stick_y;
    int16_t  right_stick_x;   /* Whammy */
    int16_t  right_stick_y;   /* Tilt   */
} dongle_report_t;

/*
 * Bind completion callback. Invoked from BLE interrupt context when a new
 * controller advertisement is accepted and stored as slot `slot`.
 *
 *   slot — 0-3: which slot was just bound
 *   mac  — 6-byte BLE address of the newly bound controller
 *
 * IMPORTANT: Do not call any blocking functions from this callback.
 * Set a flag and handle in main loop.
 */
typedef void (*dongle_bt_bind_cb_t)(uint8_t slot, uint8_t addr_type, const uint8_t mac[BLE_MAC_LEN]);

/* ── Lifecycle ──────────────────────────────────────────────────── */

/* Initialize the BLE scanner. Call after cyw43_arch_init(). */
void dongle_bt_init(void);

/* ── Slot binding management ────────────────────────────────────── */

/*
 * Pre-load a bound MAC address for slot `slot` (0-3).
 * Call for each already-bound slot before scanning starts so the dongle
 * knows which advertisements to route to which XInput instance.
 */
void dongle_bt_set_bound_mac(uint8_t slot, uint8_t addr_type, const uint8_t mac[BLE_MAC_LEN]);

/* Remove the bound MAC for slot `slot`. That slot will no longer receive data. */
void dongle_bt_clear_bound_mac(uint8_t slot);
bool dongle_bt_get_bound_mac(uint8_t slot, uint8_t *addr_type, uint8_t mac[BLE_MAC_LEN]);

/*
 * Enter bind mode for slot `slot`.
 * The next valid OCC advertisement from a MAC not already bound to another
 * slot will be stored as the binding for `slot`, and `cb` will be invoked.
 * Any previously stored MAC for `slot` is overwritten.
 * While bind mode is active, already-bound slots continue to work normally.
 */
void dongle_bt_start_bind(uint8_t slot, dongle_bt_bind_cb_t cb);

/* Cancel any active bind mode without saving anything. */
void dongle_bt_cancel_bind(void);

/* Returns true if a bind operation is currently in progress. */
bool dongle_bt_is_binding(void);

/* Returns the slot index currently being bound (0-3), or 0xFF if none. */
uint8_t dongle_bt_binding_slot(void);

/* ── Status & data retrieval ────────────────────────────────────── */

/*
 * Returns true if slot `slot` has received an advertisement within
 * CONTROLLER_TIMEOUT_MS and is therefore considered connected.
 */
bool dongle_bt_connected(uint8_t slot);

/*
 * Fill *out with the latest report for slot `slot`.
 * Returns true if the report is new since the last call to this function.
 * Returns false (and leaves *out unchanged) if no report has ever arrived.
 */
bool dongle_bt_get_report(uint8_t slot, dongle_report_t *out);
uint8_t dongle_bt_get_controller_kind(uint8_t slot);

/* Returns how many slots are currently active (connected). */
uint8_t dongle_bt_active_count(void);

#endif /* _DONGLE_BT_H_ */
