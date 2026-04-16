/*
 * main.c - Pico W Guitar Controller Dongle Firmware
 *
 * ── Design summary ────────────────────────────────────────────────────────
 *
 *  • NO MAC PERSISTENCE — controller bindings live in RAM only. Every reboot
 *    starts completely fresh. No MAC addresses are written to flash during
 *    play mode.
 *
 *  • USB FOLLOWS WIRELESS STATE — the XInput device count presented to Windows
 *    exactly tracks how many controllers are currently wirelessly connected.
 *    When a controller disconnects, its XInput interface is removed from the
 *    USB descriptor (full re-enumeration). When it reconnects, the interface
 *    is added back. Windows never sees a ghost controller.
 *
 *  • NON-BLOCKING USB reconnect — a state machine keeps cyw43_arch_poll()
 *    running throughout the disconnect/reconnect pause. sleep_ms() is never
 *    called from the main loop.
 *
 *  • AUTO-REBIND on disconnection — when a controller times out the slot
 *    automatically re-enters bind mode. The same or a replacement controller
 *    can pair without any button press.
 *
 *  • COALESCE TIMER — if several slots change state in quick succession (e.g.
 *    two controllers disconnect within milliseconds), the USB change is batched
 *    into a single re-enumeration instead of firing once per slot.
 *
 * ── Sync / Bind buttons (pull-up, active-low) ─────────────────────────────
 *
 *   GPIO 21 — auto on boot; press to re-sync slot 0
 *   GPIO 20 — press to search for a 2nd controller
 *   GPIO 19 — press to search for a 3rd controller
 *   GPIO 18 — press to search for a 4th controller
 *
 * ── LED behaviour ─────────────────────────────────────────────────────────
 *
 *   Config mode:                double-blink
 *   Any slot in bind/sync mode: rapid blink (100 ms) — including boot
 *   All active slots connected, no bind pending: solid ON
 *   No controllers, not syncing: slow blink (fallback)
 *
 * ── USB interface count ───────────────────────────────────────────────────
 *
 *   Starts at 0 (device fully disconnected from host).
 *   After each state change, g_num_controllers is set to the index of the
 *   highest CONNECTED slot + 1, and a USB re-enumeration is triggered.
 *
 *   Example with slots 0, 1, 2 all connected:
 *     g_num_controllers = 3  →  Windows sees 3 XInput guitar devices
 *   Slot 1 drops out:
 *     g_num_controllers = 3  (slot 2 is still highest)
 *     slot 1 interface sends zero reports until it reconnects
 *   Slots 1 and 2 both drop out:
 *     g_num_controllers = 1  (slot 0 is still connected)
 *     Windows sees 1 XInput guitar device
 *   Slot 0 drops out:
 *     g_num_controllers = 0  →  USB physically disconnects from host
 *
 *   NOTE: interfaces for slots below the highest connected slot are kept
 *   even while temporarily disconnected. Only trailing disconnected slots
 *   (i.e. highest connected slot + 1 and above) are removed. This avoids
 *   Windows renumbering e.g. "Guitar 1" when "Guitar 2" disconnects.
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/cyw43_arch.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "tusb.h"

#include "usb_descriptors.h"
#include "xinput_driver.h"
#include "dongle_bt.h"
#include "dongle_bindings.h"
#include "apa102_leds.h"

/* ── Timing constants ──────────────────────────────────────────────── */

#define REPORT_INTERVAL_US        1000   /* ~1 kHz XInput report rate           */
#define SYNC_DEBOUNCE_MS           300   /* debounce for all sync buttons        */
#define USB_RECONNECT_PAUSE_MS     600   /* pause between disconnect/reconnect   */

/*
 * After any wireless state change (connect or disconnect), wait this long
 * before triggering a USB re-enumeration. This coalesces rapid successive
 * changes (e.g. two controllers dropping at the same time) into a single
 * USB cycle instead of two back-to-back ones.
 */
#define USB_COALESCE_MS             80

/* ── Sync button GPIO map ──────────────────────────────────────────── */
/*
 * Hardcoded sync / bind button GPIO assignments (active-low, internal pull-up):
 *   GPIO 21 — slot 0  (auto-bind on boot; press to re-sync controller 1)
 *   GPIO 20 — slot 1  (bind controller 2)
 *   GPIO 19 — slot 2  (bind controller 3)
 *   GPIO 18 — slot 3  (bind controller 4)
 */
static const uint8_t sync_pins[DONGLE_MAX_CONTROLLERS] = { 21, 20, 19, 18 };

/* ── Module state ──────────────────────────────────────────────────── */

static bool g_cyw43_init_ok = false;

/* ── USB connection state machine ──────────────────────────────────── */
/*
 * States:
 *   USB_IDLE          Normal operation; no reconnect pending.
 *   USB_COALESCING    A wireless state change just happened; waiting
 *                     USB_COALESCE_MS to see if more changes follow before
 *                     committing to a USB cycle.
 *   USB_DISCONNECTING USB has been physically disconnected (DP pulled low);
 *                     waiting USB_RECONNECT_PAUSE_MS before reconnecting.
 */
typedef enum {
    USB_IDLE = 0,
    USB_COALESCING,
    USB_DISCONNECTING,
} usb_state_t;

static usb_state_t usb_state               = USB_IDLE;
static uint32_t    usb_state_enter_ms      = 0;     /* timestamp of last state change */
static bool        g_usb_ever_connected    = false; /* true after first tud_connect */
static bool        g_usb_physically_connected = false; /* true while D+ is pulled high */

/*
 * Desired interface count — updated whenever the wireless topology changes.
 * The USB state machine reads this when it finally fires the re-enumeration.
 */
static uint8_t     g_desired_num_ctrl = 0;

/* ── Per-slot state ────────────────────────────────────────────────── */
/*
 * slot_allocated[s]:
 *   true from the moment slot s first pairs successfully. Never goes false.
 *   Prevents auto-rebind from firing on a slot that was never paired.
 *
 * slot_was_connected[s]:
 *   true while (or after) slot s has been seen as BLE-connected.
 *   Goes false when the timeout is detected and rebind starts.
 *   Goes true again when rebind completes.
 */
static bool slot_allocated[DONGLE_MAX_CONTROLLERS]    = {false};
static bool slot_was_connected[DONGLE_MAX_CONTROLLERS] = {false};
static volatile bool slot_binding_save_pending[DONGLE_MAX_CONTROLLERS] = {false};
static dongle_binding_t pending_slot_binding[DONGLE_MAX_CONTROLLERS];

static bool sync_slot_subtype(uint8_t slot) {
    if (slot >= DONGLE_MAX_CONTROLLERS) return false;

    uint8_t kind = dongle_bt_get_controller_kind(slot);
    uint8_t subtype = (kind == DONGLE_CONTROLLER_KIND_DRUM)
        ? XINPUT_SUBTYPE_DRUM_KIT
        : XINPUT_SUBTYPE_DONGLE;

    if (g_controller_subtypes[slot] == subtype) return false;
    g_controller_subtypes[slot] = subtype;
    return true;
}

static void process_pending_binding_saves(void) {
    for (uint8_t s = 0; s < DONGLE_MAX_CONTROLLERS; s++) {
        if (!slot_binding_save_pending[s]) continue;
        uint32_t irq = save_and_disable_interrupts();
        dongle_binding_t binding = pending_slot_binding[s];
        slot_binding_save_pending[s] = false;
        restore_interrupts(irq);
        dongle_bindings_save_slot(s, &binding);
    }
}

/* ────────────────────────────────────────────────────────────────── */
/* APA102 LED update                                                  */
/*                                                                    */
/* LED pairs per slot (1-indexed in schematic → 0-indexed here):     */
/*   Slot 0: LEDs 4 & 5   Slot 1: LEDs 3 & 6                        */
/*   Slot 2: LEDs 2 & 7   Slot 3: LEDs 1 & 8                        */
/*                                                                    */
/* off = not syncing, idle                                            */
/* flash = actively binding to a controller                           */
/* solid = controller connected                                       */
/* ────────────────────────────────────────────────────────────────── */

static void dongle_led_update(void) {
    static uint32_t blink_last  = 0;
    static bool     blink_state = false;

    uint32_t now = to_ms_since_boot(get_absolute_time());
    if (now - blink_last >= 300) {
        blink_last  = now;
        blink_state = !blink_state;
    }

    static const uint8_t led_pairs[DONGLE_MAX_CONTROLLERS][2] = {
        {3, 4}, {2, 5}, {1, 6}, {0, 7}
    };
    uint8_t brightness[DONGLE_LED_COUNT] = {0};

    for (uint8_t s = 0; s < DONGLE_MAX_CONTROLLERS; s++) {
        uint8_t b = 0;
        bool binding = dongle_bt_is_binding() && (dongle_bt_binding_slot() == s);

        if (dongle_bt_connected(s))
            b = 15;                      // solid, half brightness
        else if (binding && blink_state)
            b = 15;                      // flash on half-cycle

        brightness[led_pairs[s][0]] = b;
        brightness[led_pairs[s][1]] = b;
    }

    apa102_write(brightness, 255, 255, 255);  // white
}

/* ────────────────────────────────────────────────────────────────── */
/* Sync button helpers                                                */
/* ────────────────────────────────────────────────────────────────── */

static void init_sync_buttons(void) {
    for (int i = 0; i < DONGLE_MAX_CONTROLLERS; i++) {
        gpio_init(sync_pins[i]);
        gpio_set_dir(sync_pins[i], GPIO_IN);
        gpio_pull_up(sync_pins[i]);
    }
}

static bool read_sync_button(uint8_t slot) {
    return !gpio_get(sync_pins[slot]);   /* active low */
}

/* ────────────────────────────────────────────────────────────────── */
/* Desired interface count calculation                                */
/*                                                                    */
/* Returns the number of XInput interfaces that should be presented  */
/* to the host right now, based on which slots are currently         */
/* wirelessly connected.                                             */
/*                                                                    */
/* The count is (highest connected slot index + 1), so that slot     */
/* numbering on the host stays stable even when a middle slot drops. */
/* Trailing disconnected slots are hidden; gaps in the middle are    */
/* kept (and send zero reports) to avoid renumbering.                */
/*                                                                    */
/* Returns 0 when no slots are connected (USB should disconnect).    */
/* ────────────────────────────────────────────────────────────────── */

static uint8_t calc_desired_ctrl_count(void) {
    int8_t highest = -1;
    for (int8_t s = (int8_t)DONGLE_MAX_CONTROLLERS - 1; s >= 0; s--) {
        if (dongle_bt_connected((uint8_t)s)) {
            highest = s;
            break;
        }
    }
    return (highest >= 0) ? (uint8_t)(highest + 1) : 0;
}

/* ────────────────────────────────────────────────────────────────── */
/* Schedule a USB re-enumeration                                      */
/*                                                                    */
/* Call whenever the wireless topology changes (controller connects  */
/* or disconnects). The coalesce timer absorbs rapid successive      */
/* changes so only one USB cycle fires.                              */
/* ────────────────────────────────────────────────────────────────── */

static void schedule_usb_update(void) {
    /* Snapshot desired count at the moment of scheduling.
     * If more changes arrive before the coalesce window expires, the
     * state machine re-reads it just before firing. */
    g_desired_num_ctrl = calc_desired_ctrl_count();

    if (usb_state == USB_IDLE || usb_state == USB_COALESCING) {
        usb_state          = USB_COALESCING;
        usb_state_enter_ms = to_ms_since_boot(get_absolute_time());
    }
    /* If already USB_DISCONNECTING, the reconnect will naturally pick up the
     * latest g_desired_num_ctrl when tud_connect() fires — no extra action. */
}

/* ────────────────────────────────────────────────────────────────── */
/* USB connection state machine (non-blocking)                        */
/*                                                                    */
/* Must be called every main-loop iteration.                         */
/* Never calls sleep_ms(); cyw43_arch_poll() keeps running.          */
/* ────────────────────────────────────────────────────────────────── */

static void usb_connection_task(void) {
    uint32_t now_ms = to_ms_since_boot(get_absolute_time());

    switch (usb_state) {

        case USB_IDLE:
            /* Nothing to do */
            break;

        case USB_COALESCING:
            /*
             * Waiting for rapid successive changes to settle.
             * Re-snapshot the desired count in case more slots changed
             * while we were waiting.
             */
            g_desired_num_ctrl = calc_desired_ctrl_count();

            if (now_ms - usb_state_enter_ms >= USB_COALESCE_MS) {
                /* Coalesce window expired — act on the current desired count */

                if (g_desired_num_ctrl == 0 && !g_usb_ever_connected) {
                    /*
                     * Still waiting for the very first controller to pair;
                     * nothing to do yet (USB stays disconnected).
                     */
                    usb_state = USB_IDLE;
                    break;
                }

                /* Update global descriptor count */
                g_num_controllers = g_desired_num_ctrl;

                if (!g_usb_ever_connected) {
                    /*
                     * First controller ever — USB was physically disconnected.
                     * Just pull DP high; no prior disconnect needed.
                     */
                    tud_connect();
                    g_usb_ever_connected       = true;
                    g_usb_physically_connected = true;
                    usb_state = USB_IDLE;
                } else if (g_desired_num_ctrl == 0) {
                    /*
                     * All controllers gone — pull DP low.
                     * Stay disconnected until a controller comes back.
                     */
                    tud_disconnect();
                    g_usb_physically_connected = false;
                    usb_state = USB_IDLE;
                } else if (g_usb_physically_connected) {
                    /*
                     * Interface count changed while USB was active — re-enumerate.
                     * Phase 1: disconnect now.
                     * Phase 2: reconnect after USB_RECONNECT_PAUSE_MS.
                     */
                    tud_disconnect();
                    g_usb_physically_connected = false;
                    usb_state_enter_ms = now_ms;
                    usb_state = USB_DISCONNECTING;
                } else {
                    /*
                     * USB was already physically down (count went 0→N).
                     * Skip the disconnect+pause — just connect directly.
                     */
                    tud_connect();
                    g_usb_physically_connected = true;
                    usb_state = USB_IDLE;
                }
            }
            break;

        case USB_DISCONNECTING:
            /*
             * Waiting for the host to notice we are gone before reconnecting.
             * Keep re-snapshotting desired count in case more wireless changes
             * arrive during the pause — the reconnect will use the latest value.
             */
            g_desired_num_ctrl = calc_desired_ctrl_count();
            g_num_controllers  = g_desired_num_ctrl;

            if (now_ms - usb_state_enter_ms >= USB_RECONNECT_PAUSE_MS) {
                if (g_desired_num_ctrl == 0) {
                    /*
                     * All controllers still gone by the time the pause
                     * expired — stay disconnected.
                     */
                    usb_state = USB_IDLE;
                } else {
                    /* At least one controller alive — reconnect */
                    tud_connect();
                    g_usb_physically_connected = true;
                    usb_state = USB_IDLE;
                }
            }
            break;
    }
}

/* ────────────────────────────────────────────────────────────────── */
/* BLE bind callback                                                  */
/*                                                                    */
/* *** CALLED FROM BLE INTERRUPT CONTEXT ***                         */
/*                                                                    */
/* ONLY sets flags / calls schedule_usb_update() — no blocking       */
/* calls, no flash writes, no heavy work.                            */
/*                                                                    */
/* schedule_usb_update() itself only writes two variables and one    */
/* enum, all of which are main-loop-owned, so it is safe to call     */
/* from interrupt context on a single-core M0+.                      */
/* ────────────────────────────────────────────────────────────────── */

static void on_bind_complete(uint8_t slot, uint8_t addr_type, const uint8_t mac[BLE_MAC_LEN]) {

    /* Mark the slot as allocated so auto-rebind logic knows it exists */
    slot_allocated[slot]    = true;
    slot_was_connected[slot] = false;
    pending_slot_binding[slot].valid = true;
    pending_slot_binding[slot].addr_type = addr_type;
    memcpy(pending_slot_binding[slot].mac, mac, BLE_MAC_LEN);
    slot_binding_save_pending[slot] = true;

    /*
     * Wait for the first report before exposing this slot over USB. That
     * report carries the optional controller-kind byte used for drum subtype.
     */
}

/* ────────────────────────────────────────────────────────────────── */
/* Auto-rebind + disconnect detection                                 */
/*                                                                    */
/* Detects when a previously-connected slot times out, removes it    */
/* from the USB descriptor (via schedule_usb_update), and restarts   */
/* bind mode so the controller can re-pair automatically.            */
/* ────────────────────────────────────────────────────────────────── */

static void rebind_disconnected_slots(void) {
    bool any_changed = false;

    for (uint8_t s = 0; s < DONGLE_MAX_CONTROLLERS; s++) {
        if (!slot_allocated[s]) continue;   /* Slot never paired — skip */

        bool connected_now = dongle_bt_connected(s);

        if (connected_now) {
            if (sync_slot_subtype(s)) {
                any_changed = true;
            }
            if (!slot_was_connected[s]) {
                /*
                 * Slot just came back online (rebind completed and first
                 * advertisement arrived). Mark it connected and schedule
                 * USB update so the interface reappears.
                 */
                slot_was_connected[s] = true;
                any_changed = true;
            }
        } else if (slot_was_connected[s]) {
            /*
             * Slot was connected and has just timed out.
             *
             * 1. Clear the flag — set again when controller returns.
             * 2. Schedule a USB update to shrink the interface count if
             *    this was a trailing slot.
             * 3. Restart bind mode so the controller can auto-rejoin.
             *    (Only one bind runs at a time; if one is already active,
             *    dongle_bt_start_bind replaces it for this slot.)
             */
            slot_was_connected[s] = false;
            g_controller_subtypes[s] = XINPUT_SUBTYPE_DONGLE;
            any_changed = true;
            /* Auto-reconnect is now handled internally by dongle_bt.c via
             * gap_connect(mac) — no need to call dongle_bt_start_bind here. */
        }
    }

    if (any_changed) {
        schedule_usb_update();
    }
}

/* ────────────────────────────────────────────────────────────────── */
/* TinyUSB callbacks                                                  */
/* ────────────────────────────────────────────────────────────────── */

void tud_mount_cb(void)                              {}
void tud_umount_cb(void)                             {}
void tud_suspend_cb(bool remote_wakeup_en)           { (void)remote_wakeup_en; }
void tud_resume_cb(void)                             {}

/* ────────────────────────────────────────────────────────────────── */
/* Main                                                               */
/* ────────────────────────────────────────────────────────────────── */

int main(void) {
    stdio_init_all();

    if (cyw43_arch_init()) {
        while (1) tight_loop_contents();   /* Fatal: CYW43 chip init failed */
    }
    g_cyw43_init_ok = true;

    apa102_init();
    apa102_all_off();

    init_sync_buttons();

    /* ════════════════════════════════════════════════════════════════
     * PLAY MODE — XInput + BLE scanning
     * ════════════════════════════════════════════════════════════════ */

    g_num_controllers = 0;

    /*
     * Init USB hardware then immediately pull DP low so Windows cannot
     * enumerate us. DP goes high again inside usb_connection_task() after
     * the first controller pairs.
     */
    tusb_init();
    tud_disconnect();

    /* Init BLE scanner (pure Central — passive scan) */
    dongle_bt_init();

    dongle_binding_t saved_bindings[DONGLE_MAX_CONTROLLERS];
    dongle_bindings_load(saved_bindings);
    bool any_saved_binding = false;
    for (uint8_t s = 0; s < DONGLE_MAX_CONTROLLERS; s++) {
        if (!saved_bindings[s].valid) continue;
        any_saved_binding = true;
        slot_allocated[s] = true;
        dongle_bt_set_bound_mac(s, saved_bindings[s].addr_type, saved_bindings[s].mac);
    }

    /*
     * Auto-start bind on slot 0. LED will blink rapidly until the first
     * controller is found (dongle_bt_is_binding() == true the whole time).
     */
    if (!any_saved_binding) {
        dongle_bt_start_bind(0, on_bind_complete);
    }

    /* ── Main loop state ── */
    xinput_report_t xreport;
    dongle_report_t bt_report;
    memset(&bt_report, 0, sizeof(bt_report));

    uint64_t  last_report_us                             = 0;
    uint32_t  last_sync_press_ms[DONGLE_MAX_CONTROLLERS] = {0};
    bool      sync_was_pressed[DONGLE_MAX_CONTROLLERS]   = {false};

    while (true) {
        tud_task();
        cyw43_arch_poll();
        process_pending_binding_saves();

        /* ── Detect wireless disconnections, trigger USB update ── */
        rebind_disconnected_slots();

        /* ── Drive the non-blocking USB connect/disconnect machine ── */
        usb_connection_task();

        /* ── Sync button handling ── */
        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        for (uint8_t s = 0; s < DONGLE_MAX_CONTROLLERS; s++) {
            bool pressed = read_sync_button(s);
            if (pressed && !sync_was_pressed[s]) {
                if (now_ms - last_sync_press_ms[s] >= SYNC_DEBOUNCE_MS) {
                    last_sync_press_ms[s] = now_ms;
                    dongle_bindings_clear_slot(s);
                    slot_allocated[s] = false;
                    slot_was_connected[s] = false;
                    g_controller_subtypes[s] = XINPUT_SUBTYPE_DONGLE;
                    slot_binding_save_pending[s] = false;
                    memset(&pending_slot_binding[s], 0, sizeof(pending_slot_binding[s]));
                    dongle_bt_start_bind(s, on_bind_complete);
                    schedule_usb_update();
                }
            }
            sync_was_pressed[s] = pressed;
        }

        /* ── LED status (~60 Hz — avoids blocking on DMA every loop) ── */
        static uint32_t last_led_ms = 0;
        if (now_ms - last_led_ms >= 16) {
            last_led_ms = now_ms;
            dongle_led_update();
        }

        /* ── Send XInput reports at ~1 kHz for all exposed slots ── */
        uint64_t now_us = time_us_64();
        if (now_us - last_report_us >= REPORT_INTERVAL_US) {
            last_report_us = now_us;

            for (uint8_t s = 0; s < g_num_controllers; s++) {
                if (!xinput_ready(s)) continue;

                memset(&xreport, 0, sizeof(xinput_report_t));
                xreport.report_id   = 0x00;
                xreport.report_size = 0x14;

                if (dongle_bt_connected(s)) {
                    dongle_bt_get_report(s, &bt_report);
                    xreport.buttons       = bt_report.buttons;
                    xreport.left_trigger  = bt_report.left_trigger;
                    xreport.right_trigger = bt_report.right_trigger;
                    xreport.left_stick_x  = bt_report.left_stick_x;
                    xreport.left_stick_y  = bt_report.left_stick_y;
                    xreport.right_stick_x = bt_report.right_stick_x;
                    xreport.right_stick_y = bt_report.right_stick_y;
                }
                /*
                 * Disconnected slots within the exposed range get an all-zero
                 * report — no phantom buttons, sticks centred.
                 */
                xinput_send_report(s, &xreport);
            }
        }

    }

    return 0;
}
