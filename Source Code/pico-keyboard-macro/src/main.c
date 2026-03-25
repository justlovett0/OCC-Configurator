/*
 * main.c - Keyboard Macro Pad Firmware
 *
 * Presents as a composite USB device: HID keyboard + CDC serial port.
 * Each configurable GPIO pin triggers a string of keystrokes when pressed.
 *
 * Hardware:
 *   Native USB (micro-USB) -> Host PC (HID keyboard + CDC config port)
 *   GPIO pins -> buttons to GND (active-low, internal pull-ups)
 *
 * CDC is always available — no reboot needed to configure. The configurator
 * can connect at any time while the keyboard is fully operational.
 *
 * Macro execution:
 *   One character is sent per step (key-down 10ms, key-up 5ms, next char).
 *   Only one macro runs at a time; if a second fires mid-string it is ignored.
 *   TRIGGER_HOLD re-queues the string after completion if the button is still
 *   held (500ms inter-repeat delay).
 */

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/watchdog.h"
#include "tusb_config.h"
#include "tusb.h"
#include "class/hid/hid.h"

#include "usb_descriptors.h"
#include "macro_config.h"
#include "macro_config_serial.h"

// ── Timing ──
#define KEY_DOWN_US       10000   // hold key-down for 10ms
#define KEY_UP_US          5000   // hold key-up/gap for 5ms
#define HOLD_REPEAT_US   500000   // 500ms between repeats for TRIGGER_HOLD
#define POLL_INTERVAL_US   1000   // button poll rate 1ms

// ── Onboard LED ──
#define ONBOARD_LED_PIN    25

static macro_config_t g_config;

//--------------------------------------------------------------------
// ASCII → HID keycode lookup
//
// Table covers printable ASCII 0x20–0x7E (95 chars).
// Also handles \n (Enter) and \t (Tab) as special cases.
//
// Entry: {keycode, needs_shift}
// shift modifier = KEYBOARD_MODIFIER_LEFTSHIFT (0x02)
//--------------------------------------------------------------------

typedef struct { uint8_t keycode; uint8_t shift; } keymap_entry_t;

// Indexed by (char - 0x20), covers space (0x20) through ~ (0x7E)
static const keymap_entry_t keymap[95] = {
    /* 0x20  */ { HID_KEY_SPACE,         0 },
    /* 0x21 !*/ { HID_KEY_1,             1 },
    /* 0x22 "*/ { HID_KEY_APOSTROPHE,    1 },
    /* 0x23 #*/ { HID_KEY_3,             1 },
    /* 0x24 $*/ { HID_KEY_4,             1 },
    /* 0x25 %*/ { HID_KEY_5,             1 },
    /* 0x26 &*/ { HID_KEY_7,             1 },
    /* 0x27 '*/ { HID_KEY_APOSTROPHE,    0 },
    /* 0x28 (*/ { HID_KEY_9,             1 },
    /* 0x29 )*/ { HID_KEY_0,             1 },
    /* 0x2A **/ { HID_KEY_8,             1 },
    /* 0x2B +*/ { HID_KEY_EQUAL,         1 },
    /* 0x2C ,*/ { HID_KEY_COMMA,         0 },
    /* 0x2D -*/ { HID_KEY_MINUS,         0 },
    /* 0x2E .*/ { HID_KEY_PERIOD,        0 },
    /* 0x2F /*/ { HID_KEY_SLASH,         0 },
    /* 0x30 0*/ { HID_KEY_0,             0 },
    /* 0x31 1*/ { HID_KEY_1,             0 },
    /* 0x32 2*/ { HID_KEY_2,             0 },
    /* 0x33 3*/ { HID_KEY_3,             0 },
    /* 0x34 4*/ { HID_KEY_4,             0 },
    /* 0x35 5*/ { HID_KEY_5,             0 },
    /* 0x36 6*/ { HID_KEY_6,             0 },
    /* 0x37 7*/ { HID_KEY_7,             0 },
    /* 0x38 8*/ { HID_KEY_8,             0 },
    /* 0x39 9*/ { HID_KEY_9,             0 },
    /* 0x3A :*/ { HID_KEY_SEMICOLON,     1 },
    /* 0x3B ;*/ { HID_KEY_SEMICOLON,     0 },
    /* 0x3C <*/ { HID_KEY_COMMA,         1 },
    /* 0x3D =*/ { HID_KEY_EQUAL,         0 },
    /* 0x3E >*/ { HID_KEY_PERIOD,        1 },
    /* 0x3F ?*/ { HID_KEY_SLASH,         1 },
    /* 0x40 @*/ { HID_KEY_2,             1 },
    /* 0x41 A*/ { HID_KEY_A,             1 },
    /* 0x42 B*/ { HID_KEY_B,             1 },
    /* 0x43 C*/ { HID_KEY_C,             1 },
    /* 0x44 D*/ { HID_KEY_D,             1 },
    /* 0x45 E*/ { HID_KEY_E,             1 },
    /* 0x46 F*/ { HID_KEY_F,             1 },
    /* 0x47 G*/ { HID_KEY_G,             1 },
    /* 0x48 H*/ { HID_KEY_H,             1 },
    /* 0x49 I*/ { HID_KEY_I,             1 },
    /* 0x4A J*/ { HID_KEY_J,             1 },
    /* 0x4B K*/ { HID_KEY_K,             1 },
    /* 0x4C L*/ { HID_KEY_L,             1 },
    /* 0x4D M*/ { HID_KEY_M,             1 },
    /* 0x4E N*/ { HID_KEY_N,             1 },
    /* 0x4F O*/ { HID_KEY_O,             1 },
    /* 0x50 P*/ { HID_KEY_P,             1 },
    /* 0x51 Q*/ { HID_KEY_Q,             1 },
    /* 0x52 R*/ { HID_KEY_R,             1 },
    /* 0x53 S*/ { HID_KEY_S,             1 },
    /* 0x54 T*/ { HID_KEY_T,             1 },
    /* 0x55 U*/ { HID_KEY_U,             1 },
    /* 0x56 V*/ { HID_KEY_V,             1 },
    /* 0x57 W*/ { HID_KEY_W,             1 },
    /* 0x58 X*/ { HID_KEY_X,             1 },
    /* 0x59 Y*/ { HID_KEY_Y,             1 },
    /* 0x5A Z*/ { HID_KEY_Z,             1 },
    /* 0x5B [*/ { HID_KEY_BRACKET_LEFT,  0 },
    /* 0x5C \*/ { HID_KEY_BACKSLASH,     0 },
    /* 0x5D ]*/ { HID_KEY_BRACKET_RIGHT, 0 },
    /* 0x5E ^*/ { HID_KEY_6,             1 },
    /* 0x5F _*/ { HID_KEY_MINUS,         1 },
    /* 0x60 `*/ { HID_KEY_GRAVE,         0 },
    /* 0x61 a*/ { HID_KEY_A,             0 },
    /* 0x62 b*/ { HID_KEY_B,             0 },
    /* 0x63 c*/ { HID_KEY_C,             0 },
    /* 0x64 d*/ { HID_KEY_D,             0 },
    /* 0x65 e*/ { HID_KEY_E,             0 },
    /* 0x66 f*/ { HID_KEY_F,             0 },
    /* 0x67 g*/ { HID_KEY_G,             0 },
    /* 0x68 h*/ { HID_KEY_H,             0 },
    /* 0x69 i*/ { HID_KEY_I,             0 },
    /* 0x6A j*/ { HID_KEY_J,             0 },
    /* 0x6B k*/ { HID_KEY_K,             0 },
    /* 0x6C l*/ { HID_KEY_L,             0 },
    /* 0x6D m*/ { HID_KEY_M,             0 },
    /* 0x6E n*/ { HID_KEY_N,             0 },
    /* 0x6F o*/ { HID_KEY_O,             0 },
    /* 0x70 p*/ { HID_KEY_P,             0 },
    /* 0x71 q*/ { HID_KEY_Q,             0 },
    /* 0x72 r*/ { HID_KEY_R,             0 },
    /* 0x73 s*/ { HID_KEY_S,             0 },
    /* 0x74 t*/ { HID_KEY_T,             0 },
    /* 0x75 u*/ { HID_KEY_U,             0 },
    /* 0x76 v*/ { HID_KEY_V,             0 },
    /* 0x77 w*/ { HID_KEY_W,             0 },
    /* 0x78 x*/ { HID_KEY_X,             0 },
    /* 0x79 y*/ { HID_KEY_Y,             0 },
    /* 0x7A z*/ { HID_KEY_Z,             0 },
    /* 0x7B {*/ { HID_KEY_BRACKET_LEFT,  1 },
    /* 0x7C |*/ { HID_KEY_BACKSLASH,     1 },
    /* 0x7D }*/ { HID_KEY_BRACKET_RIGHT, 1 },
    /* 0x7E ~*/ { HID_KEY_GRAVE,         1 },
};

// Returns false if char has no mapping (skip it)
static bool char_to_hid(char c, uint8_t *keycode, uint8_t *modifier) {
    if (c == '\n' || c == '\r') {
        *keycode = HID_KEY_ENTER; *modifier = 0; return true;
    }
    if (c == '\t') {
        *keycode = HID_KEY_TAB; *modifier = 0; return true;
    }
    unsigned char uc = (unsigned char)c;
    if (uc < 0x20 || uc > 0x7E) return false;
    const keymap_entry_t *e = &keymap[uc - 0x20];
    *keycode  = e->keycode;
    *modifier = e->shift ? KEYBOARD_MODIFIER_LEFTSHIFT : 0;
    return true;
}

//--------------------------------------------------------------------
// Debounce state
//--------------------------------------------------------------------

typedef struct {
    uint32_t last_change_us;
    bool     stable;
    bool     raw;
} debounce_t;

static debounce_t g_debounce[MACRO_COUNT];

static bool debounce_update(debounce_t *d, bool raw, uint32_t now_us, uint32_t window_us) {
    if (raw != d->raw) {
        d->raw = raw;
        d->last_change_us = now_us;
    } else if (raw != d->stable) {
        if ((now_us - d->last_change_us) >= window_us)
            d->stable = raw;
    }
    return d->stable;
}

//--------------------------------------------------------------------
// Macro execution state machine
//--------------------------------------------------------------------

typedef enum {
    EXEC_IDLE,
    EXEC_KEY_DOWN,   // key is held, waiting KEY_DOWN_US
    EXEC_KEY_UP,     // release sent, waiting KEY_UP_US before next char
    EXEC_HOLD_WAIT,  // between repeats for TRIGGER_HOLD
} exec_state_t;

static exec_state_t  exec_state    = EXEC_IDLE;
static const char   *exec_text_ptr = NULL;   // current position in macro text
static const char   *exec_text_start = NULL; // start of macro text (for hold repeat)
static uint8_t       exec_slot     = 0;
static uint32_t      exec_until_us = 0;      // time when current phase ends
static bool          exec_enter_sent = false; // tracks if trailing Enter was already sent
static uint32_t      exec_hid_stall_us = 0;  // when HID-not-ready stall began (for timeout)

// Queue a macro to execute. Ignored if one is already running.
static void macro_queue(uint8_t slot) {
    if (exec_state != EXEC_IDLE) return;
    const char *text = g_config.macros[slot].text;
    if (!text[0]) return;  // empty string — nothing to do

    exec_slot         = slot;
    exec_text_start   = text;
    exec_text_ptr     = text;
    exec_state        = EXEC_KEY_DOWN;
    exec_until_us     = 0;   // send immediately next step
    exec_enter_sent   = false;
    exec_hid_stall_us = 0;
}

// Advance the state machine. Call every main loop iteration.
static void exec_step(uint32_t now_us) {
    if (exec_state == EXEC_IDLE) return;

    // If USB is suspended, signal the host to wake up — don't try to send reports
    if (g_suspended) {
        tud_remote_wakeup();
        return;
    }

    if ((int32_t)(now_us - exec_until_us) < 0) return; // not time yet

    if (exec_state == EXEC_KEY_DOWN) {
        // Find next char with a valid keycode (skip unmapped chars)
        uint8_t keycode = 0, modifier = 0;
        while (*exec_text_ptr && !char_to_hid(*exec_text_ptr, &keycode, &modifier))
            exec_text_ptr++;

        if (!*exec_text_ptr) {
            // End of string — send trailing Enter if configured
            if (g_config.macros[exec_slot].send_enter && !exec_enter_sent) {
                if (tud_hid_ready()) {
                    uint8_t keycodes[6] = {HID_KEY_ENTER, 0, 0, 0, 0, 0};
                    tud_hid_keyboard_report(0, 0, keycodes);
                    exec_enter_sent = true;
                    exec_state    = EXEC_KEY_UP;
                    exec_until_us = now_us + KEY_DOWN_US;
                }
                return;
            }
            // Proceed to repeat or finish
            if (g_config.macros[exec_slot].trigger_mode == TRIGGER_HOLD &&
                g_debounce[exec_slot].stable) {
                // Button still held — wait then repeat from start
                exec_state    = EXEC_HOLD_WAIT;
                exec_until_us = now_us + HOLD_REPEAT_US;
            } else {
                exec_state = EXEC_IDLE;
            }
            return;
        }

        if (tud_hid_ready()) {
            uint8_t keycodes[6] = {keycode, 0, 0, 0, 0, 0};
            tud_hid_keyboard_report(0, modifier, keycodes);
            exec_state    = EXEC_KEY_UP;
            exec_until_us = now_us + KEY_DOWN_US;
            exec_text_ptr++;
        }
        // If HID not ready, retry next iteration (exec_until_us stays in the past)
    }
    else if (exec_state == EXEC_KEY_UP) {
        if (tud_hid_ready()) {
            tud_hid_keyboard_report(0, 0, NULL);  // release all keys
            exec_state       = EXEC_KEY_DOWN;
            exec_until_us    = now_us + KEY_UP_US;
            exec_hid_stall_us = 0;
        } else {
            // Track how long we've been stalled — abort after 1s to avoid deadlock
            if (exec_hid_stall_us == 0) exec_hid_stall_us = now_us;
            if ((now_us - exec_hid_stall_us) > 1000000u) exec_state = EXEC_IDLE;
        }
    }
    else if (exec_state == EXEC_HOLD_WAIT) {
        // Repeat — restart from beginning of string
        exec_text_ptr   = exec_text_start;
        exec_enter_sent = false;
        exec_state      = EXEC_KEY_DOWN;
        exec_until_us   = now_us;
    }
}

//--------------------------------------------------------------------
// GPIO init
//--------------------------------------------------------------------

static void init_gpio(void) {
    for (int i = 0; i < MACRO_COUNT; i++) {
        int8_t pin = g_config.macros[i].pin;
        if (pin < 0 || pin > 28) continue;
        gpio_init((uint)pin);
        gpio_set_dir((uint)pin, GPIO_IN);
        gpio_pull_up((uint)pin);
    }
}

//--------------------------------------------------------------------
// Button polling and trigger detection
//--------------------------------------------------------------------

static bool g_was_pressed[MACRO_COUNT] = {false};

static void poll_buttons(uint32_t now_us) {
    uint32_t debounce_us = (uint32_t)g_config.debounce_ms * 1000;

    for (int i = 0; i < MACRO_COUNT; i++) {
        int8_t pin = g_config.macros[i].pin;
        if (pin < 0 || pin > 28) {
            g_was_pressed[i] = false;
            continue;
        }

        bool raw     = !gpio_get((uint)pin);   // active-low
        bool pressed = debounce_update(&g_debounce[i], raw, now_us, debounce_us);

        uint8_t mode = g_config.macros[i].trigger_mode;

        if (mode == TRIGGER_PRESS) {
            if (pressed && !g_was_pressed[i])
                macro_queue((uint8_t)i);
        }
        else if (mode == TRIGGER_RELEASE) {
            if (!pressed && g_was_pressed[i])
                macro_queue((uint8_t)i);
        }
        else if (mode == TRIGGER_HOLD) {
            if (pressed && !g_was_pressed[i])
                macro_queue((uint8_t)i);
            // hold repeat is handled inside exec_step once string finishes
        }

        g_was_pressed[i] = pressed;
    }
}

//--------------------------------------------------------------------
// TinyUSB mount callbacks (required)
//--------------------------------------------------------------------

static bool g_suspended = false;

void tud_mount_cb(void)   {}
void tud_umount_cb(void)  {}
void tud_suspend_cb(bool remote_wakeup_en) { (void)remote_wakeup_en; g_suspended = true; }
void tud_resume_cb(void)  { g_suspended = false; }

//--------------------------------------------------------------------
// Main
//--------------------------------------------------------------------

int main(void) {
    stdio_init_all();

    gpio_init(ONBOARD_LED_PIN);
    gpio_set_dir(ONBOARD_LED_PIN, GPIO_OUT);
    gpio_put(ONBOARD_LED_PIN, true);

    config_load(&g_config);

    // Set custom device name for USB string descriptor
    if (g_config.device_name[0] != '\0')
        g_device_name = g_config.device_name;

    init_gpio();
    memset(g_debounce, 0, sizeof(g_debounce));
    memset(g_was_pressed, 0, sizeof(g_was_pressed));

    tusb_init();

    uint32_t last_poll_us = 0;

    while (true) {
        tud_task();

        uint32_t now_us = time_us_32();

        // Poll buttons at POLL_INTERVAL_US rate
        if ((now_us - last_poll_us) >= POLL_INTERVAL_US) {
            last_poll_us = now_us;
            poll_buttons(now_us);
        }

        // Advance macro execution state machine
        exec_step(now_us);

        // Non-blocking serial command handler
        config_serial_task(&g_config);
    }

    return 0;
}
