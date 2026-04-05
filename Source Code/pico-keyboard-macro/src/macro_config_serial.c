/*
 * macro_config_serial.c - Non-blocking CDC serial handler for keyboard macro pad
 *
 * Unlike the guitar/pedal firmwares, this runs alongside HID (not in a
 * blocking config-mode loop). config_serial_task() is called every main loop
 * iteration — it reads whatever bytes are available, accumulates a line,
 * then dispatches the command when \n or \r is received.
 *
 * GET_CONFIG response format:
 *   DEVTYPE:keyboard_macro
 *   CFG:macro_count=20,debounce=5,device_name=Macro Pad
 *   MACRO:0,pin=2,mode=0,text=Hello World
 *   MACRO:1,pin=-1,mode=0,text=
 *   ... (all 20 slots)
 *
 * The MACRO: lines use text= as the last field so the value can contain
 * commas without ambiguity.
 *
 * In macro text, \\n is stored as actual \n (Enter), \\t as \t (Tab).
 */

#include "macro_config.h"
#include "macro_config_serial.h"
#include "tusb.h"
#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "hardware/gpio.h"
#include "hardware/watchdog.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

//--------------------------------------------------------------------
// Serial write helpers
//--------------------------------------------------------------------

static void serial_write(const char *str) {
    uint32_t len = (uint32_t)strlen(str);
    uint32_t sent = 0;
    while (sent < len) {
        uint32_t avail = tud_cdc_write_available();
        if (avail == 0) { tud_task(); continue; }
        uint32_t chunk = (len - sent < avail) ? (len - sent) : avail;
        tud_cdc_write(str + sent, chunk);
        tud_cdc_write_flush();
        sent += chunk;
    }
}

static void serial_writeln(const char *str) {
    serial_write(str);
    serial_write("\r\n");
}

//--------------------------------------------------------------------
// GET_CONFIG response
//--------------------------------------------------------------------

static void send_config(const macro_config_t *c) {
    char buf[128];

    serial_writeln("DEVTYPE:" DEVICE_TYPE);

    snprintf(buf, sizeof(buf), "CFG:macro_count=%d,debounce=%u,device_name=%s",
             MACRO_COUNT, c->debounce_ms, c->device_name);
    serial_writeln(buf);

    // One line per macro slot — text= is last so commas in it are fine
    for (int i = 0; i < MACRO_COUNT; i++) {
        snprintf(buf, sizeof(buf), "MACRO:%d,pin=%d,mode=%u,enter=%u,text=",
                 i, c->macros[i].pin, c->macros[i].trigger_mode, c->macros[i].send_enter);
        serial_write(buf);
        // Write text char-by-char, escaping control chars back to \\n / \\t
        const char *t = c->macros[i].text;
        while (*t) {
            if (*t == '\n') serial_write("\\n");
            else if (*t == '\t') serial_write("\\t");
            else { char ch[2] = {*t, '\0'}; serial_write(ch); }
            t++;
        }
        serial_write("\r\n");
    }
}

//--------------------------------------------------------------------
// Escape sequence processing for macro text values
// Converts \\n -> \n (Enter) and \\t -> \t (Tab) in-place.
// dst must be at least MACRO_STR_LEN+1 bytes.
//--------------------------------------------------------------------

static void process_text(char *dst, const char *src) {
    size_t out = 0;
    for (size_t i = 0; src[i] && out < MACRO_STR_LEN; i++) {
        if (src[i] == '\\' && src[i + 1] == 'n') {
            dst[out++] = '\n';
            i++;  // skip 'n'
        } else if (src[i] == '\\' && src[i + 1] == 't') {
            dst[out++] = '\t';
            i++;
        } else {
            // Accept printable ASCII + \n + \t (already handled above)
            unsigned char ch = (unsigned char)src[i];
            if (ch >= 0x20 && ch <= 0x7E)
                dst[out++] = (char)ch;
        }
    }
    dst[out] = '\0';
}

//--------------------------------------------------------------------
// SET command handler
//--------------------------------------------------------------------

static void handle_set(macro_config_t *c, const char *param) {
    const char *eq = strchr(param, '=');
    if (!eq) { serial_writeln("ERR:missing ="); return; }

    size_t key_len = (size_t)(eq - param);
    const char *val = eq + 1;

    // ── macro_N_pin ──
    for (int i = 0; i < MACRO_COUNT; i++) {
        char key[16];
        int klen = snprintf(key, sizeof(key), "macro%d_pin", i);
        if (key_len == (size_t)klen && strncmp(param, key, key_len) == 0) {
            int v = atoi(val);
            if (v < -1 || v > 28) { serial_writeln("ERR:pin -1 to 28"); return; }
            c->macros[i].pin = (int8_t)v;
            serial_writeln("OK");
            return;
        }
    }

    // ── macro_N_mode ──
    for (int i = 0; i < MACRO_COUNT; i++) {
        char key[16];
        int klen = snprintf(key, sizeof(key), "macro%d_mode", i);
        if (key_len == (size_t)klen && strncmp(param, key, key_len) == 0) {
            int v = atoi(val);
            if (v < 0 || v > 2) { serial_writeln("ERR:mode 0=press 1=release 2=hold"); return; }
            c->macros[i].trigger_mode = (uint8_t)v;
            serial_writeln("OK");
            return;
        }
    }

    // ── macro_N_enter ──
    for (int i = 0; i < MACRO_COUNT; i++) {
        char key[16];
        int klen = snprintf(key, sizeof(key), "macro%d_enter", i);
        if (key_len == (size_t)klen && strncmp(param, key, key_len) == 0) {
            int v = atoi(val);
            c->macros[i].send_enter = (v != 0) ? 1 : 0;
            serial_writeln("OK");
            return;
        }
    }

    // ── macro_N_text ── (value is everything after '=', including commas)
    for (int i = 0; i < MACRO_COUNT; i++) {
        char key[16];
        int klen = snprintf(key, sizeof(key), "macro%d_text", i);
        if (key_len == (size_t)klen && strncmp(param, key, key_len) == 0) {
            process_text(c->macros[i].text, val);
            serial_writeln("OK");
            return;
        }
    }

    // ── debounce ──
    if (key_len == 8 && strncmp(param, "debounce", 8) == 0) {
        int v = atoi(val);
        if (v < 0 || v > 50) { serial_writeln("ERR:debounce 0-50"); return; }
        c->debounce_ms = (uint8_t)v;
        serial_writeln("OK");
        return;
    }

    // ── device_name ── alphanumeric + space, max 20 chars
    if (key_len == 11 && strncmp(param, "device_name", 11) == 0) {
        memset(c->device_name, 0, sizeof(c->device_name));
        size_t out = 0;
        for (size_t i = 0; val[i] && out < 20; i++) {
            unsigned char ch = (unsigned char)val[i];
            if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') ||
                (ch >= '0' && ch <= '9') || ch == ' ')
                c->device_name[out++] = (char)ch;
        }
        // trim trailing spaces
        while (out > 0 && c->device_name[out - 1] == ' ') out--;
        c->device_name[out] = '\0';
        serial_writeln("OK");
        return;
    }

    serial_writeln("ERR:unknown key");
}

//--------------------------------------------------------------------
// SCAN mode — detect GPIO presses, stream PIN: lines until STOP
// Runs as a blocking sub-loop (same pattern as pedal firmware).
//--------------------------------------------------------------------

static void run_scan(void) {
    bool pin_inited[29] = {false};
    for (int pin = 0; pin <= 28; pin++) {
        gpio_init((uint)pin);
        gpio_set_dir((uint)pin, GPIO_IN);
        gpio_pull_up((uint)pin);
        pin_inited[pin] = true;
    }
    sleep_ms(10);

    bool prev[29] = {false};
    for (int pin = 0; pin <= 28; pin++) {
        if (pin_inited[pin])
            prev[pin] = !gpio_get((uint)pin);
    }

    serial_writeln("OK");

    char line[32];
    int  line_pos = 0;
    char out[20];

    while (true) {
        tud_task();

        if (tud_cdc_available()) {
            int c = tud_cdc_read_char();
            if (c == '\r' || c == '\n') {
                if (line_pos > 0) {
                    line[line_pos] = '\0';
                    if (strcmp(line, "STOP") == 0) {
                        serial_writeln("OK");
                        return;
                    }
                    line_pos = 0;
                }
            } else if (line_pos < (int)sizeof(line) - 1) {
                line[line_pos++] = (char)c;
            }
        }

        for (int pin = 0; pin <= 28; pin++) {
            if (!pin_inited[pin]) continue;
            bool pressed = !gpio_get((uint)pin);
            if (pressed && !prev[pin]) {
                snprintf(out, sizeof(out), "PIN:%d", pin);
                serial_writeln(out);
            }
            prev[pin] = pressed;
        }

        sleep_ms(5);
    }
}

//--------------------------------------------------------------------
// Non-blocking serial task — called from main loop every iteration
//--------------------------------------------------------------------

void config_serial_task(macro_config_t *config) {
    // Static line buffer persists across calls
    static char line[256];
    static int  line_pos = 0;

    if (!tud_cdc_available()) return;

    // Read all available bytes this call (up to fill the line buffer)
    while (tud_cdc_available()) {
        int c = tud_cdc_read_char();
        if (c < 0) break;

        if (c == '\r' || c == '\n') {
            if (line_pos == 0) continue;
            line[line_pos] = '\0';
            line_pos = 0;

            // ── Dispatch ──
            if (strcmp(line, "PING") == 0) {
                serial_writeln("PONG");
            }
            else if (strcmp(line, "GET_CONFIG") == 0) {
                send_config(config);
            }
            else if (strcmp(line, "GET_FW_DATE") == 0) {
                serial_writeln("FW_DATE:" BUILD_DATE_STR);
            }
            else if (strncmp(line, "SET:", 4) == 0) {
                handle_set(config, line + 4);
            }
            else if (strcmp(line, "SAVE") == 0) {
                config_update_checksum(config);
                config_save(config);
                serial_writeln("OK");
            }
            else if (strcmp(line, "DEFAULTS") == 0) {
                config_set_defaults(config);
                serial_writeln("OK");
            }
            else if (strcmp(line, "SCAN") == 0) {
                // Blocking sub-loop — returns when STOP received
                run_scan();
            }
            else if (strcmp(line, "REBOOT") == 0) {
                serial_writeln("OK");
                sleep_ms(50);
                watchdog_reboot(0, 0, 10);
                while (1) { tight_loop_contents(); }
            }
            else if (strcmp(line, "BOOTSEL") == 0) {
                serial_writeln("OK");
                sleep_ms(50);
                reset_usb_boot(0, 0);
            }
            else {
                serial_writeln("ERR:unknown command");
            }

            return; // one command per call keeps main loop responsive
        }
        else if (line_pos < (int)sizeof(line) - 1) {
            line[line_pos++] = (char)c;
        }
    }
}
