# Phase 1: Firmware Foundation - Research

**Researched:** 2026-03-19
**Domain:** Raspberry Pi Pico/Pico W firmware — XInput gamepad, TinyUSB CDC, flash config storage
**Confidence:** HIGH (all findings verified against live source code in the OCC repository)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Trigger GPIO Pin Configuration**
- Single pin per trigger — Config struct stores one GPIO pin per trigger (pin_lt, pin_rt), not separate pins for analog vs digital
- Firmware checks the current mode (stored in config) and reads that pin via ADC (analog mode) or GPIO pull (digital mode)
- Simplifies the config struct and matches the pedal approach rather than guitar's dual-pin pattern
- Configurator will present a single DETECT function per trigger (user presses/pulls, configurator records the pin)

**Trigger Output in Digital Mode**
- Even when set to digital mode, triggers output axis values (0–255 on the trigger axis), not button events
- Digital mode means "threshold detection on a single GPIO pin" (reads HIGH/LOW), not "generate a button press"
- Output: 0 when released, 255 when pressed; no intermediate values in digital mode
- This keeps the XInput report structure consistent (triggers always output axis values)

**Boot Behavior Without USB**
- When firmware boots and does NOT detect USB host within ~1 second (USB_MOUNT_TIMEOUT_MS), enter sleep/standby state ready for wireless
- Do NOT attempt to enumerate as XInput without a host
- This follows the guitar-wireless pattern and scaffolds for future BLE HID implementation (Phase 3+)
- No LED signaling (pico-retro v1 has no LEDs); firmware will be silent waiting for USB

**Config Mode Entry**
- Only watchdog scratch register trigger — magic vibration sequence from configurator (via SET:reboot_to_config=1 or similar)
- No button-hold fallback at boot (unlike guitar-wireless with SELECT hold)

**Button Index Enum & XInput Mapping**
- Define 13-button enum (button_index_t): DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT, BTN_A, BTN_B, BTN_X, BTN_Y, BTN_START, BTN_SELECT, BTN_GUIDE, BTN_LB, BTN_RB — Total: 13 buttons
- LT/RT are separate from this enum — always axis outputs, never buttons

**Config Struct Design**
- Magic number: 0x52455452 ("RETR")
- CONFIG_VERSION: start at 1
- Fields: int8_t pin_buttons[13], int8_t pin_lt, pin_rt, uint8_t mode_lt, mode_rt, uint8_t debounce_ms, char device_name[32], uint16_t lt_min/lt_max/rt_min/rt_max, uint8_t lt_invert/rt_invert, uint8_t lt_ema_alpha/rt_ema_alpha (0–100), uint32_t checksum

**USB Descriptor**
- VID/PID: 0x045E / 0x028E (standard XInput)
- XInput subtype: 0x01 (XINPUT_DEVSUBTYPE_GAMEPAD)
- CDC config mode: VID/PID 0x2E8A / 0xF00F

**Serial Config Protocol**
- Reuse existing protocol (115200 baud, CDC)
- Commands: PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, REBOOT
- GET_CONFIG first line: DEVTYPE:pico_retro

**Analog Trigger Smoothing (EMA)**
- output = (1 - alpha) * output + alpha * raw_adc
- Alpha stored as 0–100 (user-facing %), converted internally to 0.0–1.0

**Start-Up Calibration**
- On first boot or DEFAULTS: lt_min=0, lt_max=4095, rt_min=0, rt_max=4095

### Claude's Discretion
- Exact EMA alpha conversion formula (linear 0–100 → 0.0–1.0, or curve-based)
- Specific flash sector address and memory layout
- XInput vibration sequence recognition (magic pattern from configurator vibration request)
- Exact USB_MOUNT_TIMEOUT_MS value (1000 seems safe; could be 500–2000)
- Internal debounce implementation (simple state machine vs counter)

### Deferred Ideas (OUT OF SCOPE)
- BLE wireless implementation — Phase 3+
- LED support — explicitly out of scope for v1
- Advanced button remapping (modifier chords, etc.)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FW-01 | Pico/Pico W target support — single .uf2, boot detects USB | **Architectural constraint identified** — see critical finding below. Two separate builds needed. |
| FW-02 | Dual-mode USB boot — normal = XInput; watchdog scratch = CDC config mode | Verified pattern in all existing variants |
| FW-03 | 13-button input set — DPad 4-way, A/B/X/Y, Start, Select, Guide, LB, RB | Matches existing button_index_t enum pattern |
| FW-04 | Analog triggers (LT/RT) — configurable analog (0-255) or digital (on/off) | Single-pin pattern validated against pedal_config.h approach |
| FW-05 | GPIO pin assignment — all 13 buttons + 2 triggers fully configurable | Standard pattern across all variants |
| FW-06 | Configuration storage — packed struct in flash sector with magic + CRC | Exact flash save/load pattern sourced from pedal_config.c |
| FW-07 | Serial config protocol — PING, GET_CONFIG, SET, SAVE, DEFAULTS, REBOOT | pedal_config_serial.c is the direct template |
| FW-08 | USB descriptor — XInput subtype 0x01 XINPUT_DEVSUBTYPE_GAMEPAD | **OCC_SUBTYPES conflict identified** — see open questions |
| FW-09 | Analog trigger smoothing — EMA with user-configurable alpha | Exact integer math implementation found in guitar wireless main.c |
| FW-10 | Trigger min/max calibration — per-trigger calibration points, scale to 0-255 | apply_sensitivity() pattern sourced from guitar wireless main.c |
| USB-02 | XInput mode VID/PID — 0x045E / 0x028E recognized by Windows as gamepad | Standard across all variants, confirmed in usb_descriptors.h |
</phase_requirements>

---

## Summary

All core firmware patterns for pico-retro exist in the OCC codebase and are directly reusable. The config struct pattern follows pedal_config.h (the simplest variant), the EMA smoothing and ADC scaling follow guitar_config.h, and the boot flow follows pico-guitar-controller-wireless/main.c. The serial protocol (pedal_config_serial.c) is the closest template — copy, rename fields, and adapt for 13 buttons plus 2 analog/digital triggers.

Two significant architectural issues surfaced during research and must be resolved before implementation begins: (1) FW-01's "single .uf2 for Pico and Pico W" is impossible with the current SDK build pattern — Pico W requires `set(PICO_BOARD pico_w)` which compiles in CYW43 hardware libraries absent on standard Pico; the project will need two CMake targets. (2) The XInput subtype 0x01 chosen for pico-retro is NOT in `OCC_SUBTYPES = {8, 6, 7, 11}` in configurator.py, meaning the configurator's XInput-path magic sequence will not trigger for pico-retro without a code change.

**Primary recommendation:** Model pico-retro firmware on pico-pedal (simplest config + serial patterns) combined with pico-guitar-controller-wireless (USB detection boot flow, EMA smoothing, ADC scaling). Produce two UF2 targets from one source tree — one with `PICO_BOARD pico` (default) and one with `PICO_BOARD pico_w`. Update `OCC_SUBTYPES` and `CONFIG_MODE_PIDS` in configurator.py as part of Phase 1 implementation.

---

## Critical Findings

### Finding 1: Single-UF2 Pico/Pico W Is Architecturally Impossible

**Confidence: HIGH** — Verified by examining all CMakeLists.txt files.

Every Pico W firmware variant in the project requires `set(PICO_BOARD pico_w)` in CMakeLists.txt to compile. This causes the Pico SDK to link the CYW43 wireless chip libraries. A UF2 built with `PICO_BOARD pico_w` will not boot on a standard Pico (no CYW43 chip hardware).

The existing project has no precedent for a single cross-board UF2. The wireless guitar firmware is Pico W only. The wired guitar, drums-wired, and pedal are all Pico only (no `set(PICO_BOARD pico_w)`).

**Resolution for FW-01:** The plan must produce two CMake targets from one source:
- `pico_retro_controller` — no PICO_BOARD set (defaults to Pico)
- `pico_retro_controller_w` — with `set(PICO_BOARD pico_w)`

Both share the same `src/` files. The Pico W variant defers CYW43 init (just like wireless guitar does gracefully). Use `#ifdef PICO_W` guards or the `g_cyw43_initialized` pattern. Phase 1 need only guarantee the Pico build works; the Pico W build can be stubbed with the same USB-only code path (no actual wireless).

**Configurator impact:** Two UF2 files will appear in the firmware tile grid. Name them `Retro_Controller.uf2` and `Retro_Controller_W.uf2`. Only one GIF asset needed (shared base name prefix won't work — configurator matches by `find_uf2_files()` which uses base name for GIF lookup).

### Finding 2: XInput Subtype 0x01 Not in OCC_SUBTYPES

**Confidence: HIGH** — Sourced directly from configurator.py lines 893–895.

```python
OCC_SUBTYPES = {8, 6, 7, 11}   # Drum Kit (8), Guitar (6/7), Dongle (11=0x0B)
```

The configurator scans for XInput controllers matching this set when looking for OCC devices to send the magic vibration sequence. If pico-retro uses subtype 0x01 (standard gamepad), the configurator will not find it as an OCC device and will not offer the "Configure Controller" path.

**Resolution:** Add subtype 0x01 to `OCC_SUBTYPES` and add a `1: "retro_gamepad"` entry to `XINPUT_SUBTYPE_TO_DEVTYPE`. This is a one-line change in configurator.py, but it must be part of Phase 1 scope.

Alternative: Use a different subtype that avoids collision with non-OCC standard gamepads. STATE.md flags 0x03 (ArcadeStick) as a consideration. However, subtype 0x03 is more semantically wrong for a retro gamepad than 0x01. The correct fix is adding 0x01 to `OCC_SUBTYPES` and relying on VID/PID matching as the primary OCC identifier (all OCC devices share 0x045E/0x028E in XInput mode, which Windows assigns to the generic Xbox driver — the subtype is only used internally for routing).

### Finding 3: Config-Mode PID 0xF00F Is Available

**Confidence: HIGH** — Verified by reading all usb_descriptors.h files and configurator.py.

Existing PID assignments:
| PID | Variant | Source |
|-----|---------|--------|
| 0xF00D | Guitar wired + wireless | usb_descriptors.h guitar variants |
| 0xF00E | Drums wired | usb_descriptors.h pico-drums-wired |
| 0xF00F | **AVAILABLE — pico-retro** | Not used by any existing firmware |
| 0xF010 | Pedal | usb_descriptors.h pico-pedal |

The CONTEXT.md and STATE.md had a discrepancy (some docs said 0xF00F, STACK.md said 0xF011). The source of truth (configurator.py `CONFIG_MODE_PIDS` dict and all firmware headers) confirms **0xF00F is correct and available**. The pedal jumped from 0xF00E (drums) to 0xF010, leaving 0xF00F unused.

`configurator.py CONFIG_MODE_PIDS` must add `0xF00F: "Retro Gamepad Config"`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Pico SDK | Project version (2.x) | GPIO, ADC, flash, watchdog, hardware drivers | Required for RP2040 |
| TinyUSB | Bundled with SDK | USB device stack (XInput + CDC) | All OCC variants use it |
| pico_stdlib | SDK | Core utilities, timing, sleep | All OCC variants |
| hardware_flash | SDK | Flash erase/program for config storage | All OCC variants |
| hardware_adc | SDK | 12-bit ADC for analog triggers | Pedal and guitar use it |
| hardware_watchdog | SDK | Config mode reboot via scratch register | All OCC variants |
| hardware_gpio | SDK | Digital button reading with pull-ups | All OCC variants |
| pico_unique_id | SDK | Board ID for USB serial number string | All OCC variants |
| pico_bootrom | SDK | BOOTSEL reboot command | All OCC variants |

### Supporting (Pico W build only)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pico_cyw43_arch_poll | SDK | CYW43 chip init + poll for wireless scaffold | Pico W UF2 target only |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Two CMake targets | Single target with runtime detection | Runtime detection is impossible — board type is compile-time |
| Subtype 0x01 | Subtype 0x03 (ArcadeStick) | 0x01 is semantically correct; requires one OCC_SUBTYPES change vs 0x03 which also requires a change |

**Installation (no package manager — SDK is git submodule):**
```bash
# Pico (standard)
cmake -B build-pico . && cmake --build build-pico
# Pico W
cmake -B build-picow -DPICO_BOARD=pico_w . && cmake --build build-picow
```

---

## Architecture Patterns

### Recommended Project Structure
```
Source Code/pico-retro/
├── CMakeLists.txt           # Two targets: pico_retro + pico_retro_w
├── pico_sdk_import.cmake    # Copy from adjacent project
├── src/
│   ├── main.c               # Boot flow, input loop, USB XInput reports
│   ├── retro_config.h       # retro_config_t struct + constants
│   ├── retro_config.c       # config_load/save/defaults/is_valid
│   ├── retro_config_serial.c # CDC serial command handler
│   ├── usb_descriptors.h    # VID/PID, subtype, XInput/CDC constants
│   ├── usb_descriptors.c    # tud_descriptor_*_cb implementations
│   ├── xinput_driver.h      # Copy from existing project
│   └── xinput_driver.c      # Copy from existing project (unchanged)
```

### Pattern 1: Config Struct (retro_config.h)

**What:** Packed struct with magic, version, pins, modes, calibration, checksum
**When to use:** Copy pedal_config.h and adapt — it is the simplest struct in the project.

```c
// Source: Source Code/pico-pedal/src/pedal_config.h (adapted)
#define CONFIG_MAGIC     0x52455452  // "RETR"
#define CONFIG_VERSION   1
#define RETRO_BTN_COUNT  13

typedef enum {
    BTN_IDX_DPAD_UP = 0,
    BTN_IDX_DPAD_DOWN,
    BTN_IDX_DPAD_LEFT,
    BTN_IDX_DPAD_RIGHT,
    BTN_IDX_A,
    BTN_IDX_B,
    BTN_IDX_X,
    BTN_IDX_Y,
    BTN_IDX_START,
    BTN_IDX_SELECT,
    BTN_IDX_GUIDE,
    BTN_IDX_LB,
    BTN_IDX_RB,
    BTN_IDX_COUNT  // = 13
} button_index_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    int8_t   pin_buttons[RETRO_BTN_COUNT]; // -1 = disabled
    int8_t   pin_lt;                       // -1 = disabled
    int8_t   pin_rt;
    uint8_t  mode_lt;                      // INPUT_MODE_DIGITAL or INPUT_MODE_ANALOG
    uint8_t  mode_rt;
    uint8_t  debounce_ms;
    char     device_name[32];             // 31 chars + null
    uint16_t lt_min, lt_max;              // raw ADC 0-4095
    uint16_t rt_min, rt_max;
    uint8_t  lt_invert, rt_invert;        // 0=normal, 1=invert
    uint8_t  lt_ema_alpha, rt_ema_alpha;  // 0-100 user %, 0=fastest (no smooth)
    uint32_t checksum;
} retro_config_t;
```

### Pattern 2: Flash Storage (retro_config.c)

**What:** Load from last flash sector, validate magic+version+checksum, fall back to defaults.
**When to use:** Exact copy of pedal_config.c with struct type substituted.

```c
// Source: Source Code/pico-pedal/src/pedal_config.c (exact pattern)
#define FLASH_CONFIG_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define FLASH_CONFIG_ADDR    ((const retro_config_t *)(XIP_BASE + FLASH_CONFIG_OFFSET))

static uint32_t _calc_checksum(const retro_config_t *config) {
    const uint8_t *data = (const uint8_t *)config;
    size_t len = offsetof(retro_config_t, checksum);
    uint32_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
        sum = (sum << 3) | (sum >> 29);   // rotating left shift
    }
    return sum ^ 0xDEADBEEF;
}

void config_save(const retro_config_t *config) {
    uint8_t buf[FLASH_PAGE_SIZE];
    memset(buf, 0xFF, sizeof(buf));       // flash erases to 0xFF
    memcpy(buf, config, sizeof(retro_config_t));
    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_CONFIG_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_CONFIG_OFFSET, buf, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
}
```

**Important:** `retro_config_t` must fit within `FLASH_PAGE_SIZE` (256 bytes). With current fields it is well under this limit.

### Pattern 3: USB Detection Boot Flow (main.c)

**What:** Init TinyUSB, wait up to USB_MOUNT_TIMEOUT_MS for host mount, fall through to standby if no USB.
**When to use:** Copy from pico-guitar-controller-wireless/src/main.c — this is the exact pattern required by FW-01.

```c
// Source: Source Code/pico-guitar-controller-wireless/src/main.c lines 722-748
#define USB_MOUNT_TIMEOUT_MS  1000

static volatile bool g_usb_mounted = false;
void tud_mount_cb(void)  { g_usb_mounted = true; }
void tud_umount_cb(void) { g_usb_mounted = false; }

// In main():
g_config_mode = false;
tusb_init();
{
    uint32_t start_ms = to_ms_since_boot(get_absolute_time());
    while (!g_usb_mounted) {
        tud_task();
        uint32_t elapsed = to_ms_since_boot(get_absolute_time()) - start_ms;
        if (elapsed >= USB_MOUNT_TIMEOUT_MS) break;
        sleep_ms(1);
    }
}

if (g_usb_mounted) {
    // XInput play mode — main game loop
} else {
    // No USB host — standby (scaffold for BLE, Phase 3+)
    while (true) { tight_loop_contents(); }
}
```

**Pico W difference:** The Pico W build adds `cyw43_arch_init()` before this block and `cyw43_arch_poll()` inside the wait loop. Use a `g_cyw43_initialized` flag to guard these calls so the same source compiles cleanly for both targets.

### Pattern 4: EMA Smoothing (integer fixed-point, from guitar wireless)

**What:** Exponential Moving Average using integer math with 8-bit fractional precision. Avoids floating point entirely.
**When to use:** In analog trigger read path, in analog mode only.

```c
// Source: Source Code/pico-guitar-controller-wireless/src/main.c lines 359-379
typedef struct {
    uint32_t state;
    bool     seeded;
} ema_state_t;

static uint16_t ema_update(ema_state_t *ema, uint16_t raw, uint32_t alpha) {
    uint32_t raw32 = (uint32_t)raw << 8;
    if (!ema->seeded) {
        ema->state  = raw32;
        ema->seeded = true;
    } else {
        if (raw32 > ema->state)
            ema->state += (alpha * (raw32 - ema->state)) >> 8;
        else
            ema->state -= (alpha * (ema->state - raw32)) >> 8;
    }
    return (uint16_t)(ema->state >> 8);
}
```

**Alpha conversion (Claude's Discretion — recommended):** The guitar firmware stores `ema_alpha` as 0–100 (user percentage) but the `config_ema_alpha()` function converts: `return (g_config.ema_alpha == 0) ? 255u : (uint32_t)g_config.ema_alpha;`. This means 0 maps to 255 (fastest response, nearly no smoothing), and 100 maps to 100 (moderate smoothing). This is a non-obvious inversion. For pico-retro, use a cleaner linear mapping: `alpha_internal = (uint32_t)user_pct * 255 / 100;` where user_pct=0 → alpha_internal=0 (frozen/maximum smoothing) and user_pct=100 → alpha_internal=255 (no smoothing, tracks live signal). OR adopt the guitar's existing convention for consistency. **Recommendation:** Match guitar behavior exactly (0=255=fastest, higher value=slower convergence) for cross-device configurator consistency.

### Pattern 5: ADC Calibration Scaling (apply_sensitivity)

**What:** Map raw ADC reading from calibration [min, max] range to [0, 4095], then scale to output range.
**When to use:** In analog trigger read path before EMA, then scale result to trigger byte (0–255).

```c
// Source: Source Code/pico-guitar-controller-wireless/src/main.c lines 343-348
static uint16_t apply_sensitivity(uint16_t raw, uint16_t min_val, uint16_t max_val) {
    if (max_val <= min_val) return raw;
    if (raw <= min_val) return 0;
    if (raw >= max_val) return 4095;
    return (uint16_t)(((uint32_t)(raw - min_val) * 4095u) / (max_val - min_val));
}
```

**Trigger output scaling (0–255 byte):** After calibration and EMA, scale 12-bit ADC (0–4095) to trigger byte (0–255):
```c
uint8_t trigger_byte = (uint8_t)(smooth_adc * 255u / 4095u);
```
This is straightforward integer scaling — no existing helper needed.

### Pattern 6: Watchdog Config Mode Reboot

**What:** Set scratch[0] to magic value, then watchdog reboot with short delay.
**When to use:** On receipt of XInput magic vibration sequence (xinput_magic_detected()).

```c
// Source: Source Code/pico-guitar-controller-wireless/src/main.c lines 214-221
static void request_config_mode_reboot(void) {
    watchdog_hw->scratch[0] = WATCHDOG_CONFIG_MAGIC;  // 0xC0F16000
    watchdog_reboot(0, 0, 10);
    while (1) { tight_loop_contents(); }
}
```

The magic vibration sequence detection and `xinput_driver.c` are shared across all variants — copy `xinput_driver.c` and `xinput_driver.h` unchanged.

### Pattern 7: Debounce State Machine

**What:** Timestamp-based debounce — raw state change recorded with timestamp; stable state only updates after `debounce_us` elapsed.
**When to use:** All 13 digital button reads. Can use same struct for digital trigger read.

```c
// Source: Source Code/pico-guitar-controller-wireless/src/main.c lines 331-341
typedef struct {
    uint32_t last_change_us;
    bool     stable;
    bool     raw;
} debounce_state_t;

static bool debounce(debounce_state_t *state, bool current_raw,
                     uint32_t now_us, uint32_t debounce_us) {
    if (current_raw != state->raw) {
        state->raw = current_raw;
        state->last_change_us = now_us;
    } else if (current_raw != state->stable) {
        if ((now_us - state->last_change_us) >= debounce_us)
            state->stable = current_raw;
    }
    return state->stable;
}
```

### Pattern 8: Serial Config Protocol (retro_config_serial.c)

**What:** CDC serial command loop — PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, REBOOT, SCAN, BOOTSEL.
**When to use:** Exact copy of pedal_config_serial.c, adapt field names and count.

GET_CONFIG must send exactly:
```
DEVTYPE:pico_retro\r\n
CFG:btn0=<pin>,...,btn12=<pin>,pin_lt=<pin>,pin_rt=<pin>,mode_lt=<m>,mode_rt=<m>,...\r\n
```

The configurator reads DEVTYPE from the first line. The CFG line format is arbitrary key=value — the configurator stores all keys in a dict and reads them by name. Keep key names exactly matching the SET command keys.

### Anti-Patterns to Avoid

- **Do NOT include apa102_leds.h** — pico-retro has no LEDs. `CLAUDE.md` states `config_serial.c` must not include it directly. Since retro has no LED config, this file never needs to be included. No `led_config_t` field in `retro_config_t`.
- **Do NOT redefine LED_INPUT_COUNT** — pico-retro never includes apa102_leds.h, so no conflict risk, but confirm no transitive include pulls it in.
- **Do NOT call gpio_init on pins 23, 24, 25, 29 on Pico W** — CYW43 uses these. Mirror the wireless guitar's `is_picow_reserved()` guard (compile-time guard via `#ifdef PICO_BOARD_PICO_W` or runtime guard via `g_cyw43_initialized`).
- **Do NOT use adc_gpio_init for non-ADC pins** — ADC pins are GP26, GP27, GP28 only. `pin_lt` and `pin_rt` in digital mode may be any GPIO; in analog mode must be 26-28. Validate in SET handler.
- **Do NOT write more than FLASH_PAGE_SIZE bytes in config_save** — The buffer is 256 bytes; `retro_config_t` must stay under this. Current design is well under 100 bytes.
- **Do NOT call tusb_init() before watchdog scratch check** — Config mode flag must be set before TinyUSB initializes so the correct descriptor set is used.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| XInput USB driver | Custom TinyUSB class driver | `xinput_driver.c` (copy from any variant) | Already implements Xbox 360 protocol correctly |
| Magic vibration detection | Custom XInput output parsing | `xinput_magic_detected()` in xinput_driver | Exact 3-step sequence already implemented |
| Flash sector erase/write | Manual flash programming | `flash_range_erase`, `flash_range_program` (Pico SDK) | Handles alignment and timing requirements |
| ADC reading | Direct register access | `adc_select_input()`, `adc_read()` (Pico SDK) | Handles mux switching correctly |
| USB string descriptors | Manual UTF-16 encoding | `_make_string_desc()` helper (copy from usb_descriptors.c) | Handles header byte format correctly |
| Interrupt-safe flash write | Hoping it works | `save_and_disable_interrupts()` / `restore_interrupts()` | Flash writes corrupt if interrupted |

---

## Common Pitfalls

### Pitfall 1: Flash Write Interrupt Safety

**What goes wrong:** Firmware crashes or corrupts flash if an interrupt fires during `flash_range_erase` / `flash_range_program`.
**Why it happens:** Flash is XIP (execute in place) — an interrupt that executes from flash while flash is being written causes a bus fault.
**How to avoid:** Always wrap flash operations with `save_and_disable_interrupts()` / `restore_interrupts()`. Pattern is in pedal_config.c lines 80-83.
**Warning signs:** Intermittent crashes immediately after SAVE command, especially with debug builds.

### Pitfall 2: CDC Config Mode Descriptor Must Be Set Before tusb_init()

**What goes wrong:** Firmware enumerates as XInput even in config mode, or config mode CDC doesn't appear.
**Why it happens:** TinyUSB reads `g_config_mode` flag in `tud_descriptor_device_cb()` and `tud_descriptor_configuration_cb()`. If this flag is set after `tusb_init()`, the USB host has already cached the wrong descriptor.
**How to avoid:** Set `g_config_mode = true` BEFORE calling `tusb_init()`. Pattern confirmed in all variants.
**Warning signs:** Configurator can't connect to serial port after magic sequence; USB shows XInput device in config mode.

### Pitfall 3: ADC Pin Validation

**What goes wrong:** Calling `adc_gpio_init()` on a non-ADC pin (GP0-25) silently corrupts GPIO state.
**Why it happens:** Pico ADC is only connected to GP26, GP27, GP28 (ADC0, ADC1, ADC2). `adc_select_input(pin - 26)` with pin < 26 reads garbage or wraps around.
**How to avoid:** In SET handler for `pin_lt`/`pin_rt`, reject pins outside 26-28 when mode is analog: `if (v != -1 && (v < 26 || v > 28)) return ERR`. In analog init, guard with `if (pin >= 26 && pin <= 28)`.
**Warning signs:** Analog trigger reads always return 0 or max; other GPIOs behave oddly after ADC init.

### Pitfall 4: OCC_SUBTYPES Not Updated in Configurator

**What goes wrong:** "Configure Controller" button in MainMenu doesn't react when pico-retro is connected via XInput. The controller appears in joy.cpl but the configurator's poll never finds it.
**Why it happens:** `OCC_SUBTYPES = {8, 6, 7, 11}` is the filter for XInput devices the configurator considers OCC-owned. Subtype 0x01 is not in this set.
**How to avoid:** Add `1` to `OCC_SUBTYPES` and add `1: "retro_gamepad"` to `XINPUT_SUBTYPE_TO_DEVTYPE` in configurator.py. Add `0xF00F: "Retro Gamepad Config"` to `CONFIG_MODE_PIDS`. Add `"retro_gamepad": "retro"` to `DEVICE_TYPE_UF2_HINTS`. Add `"retro_gamepad": RetroApp` to `DEVICE_SCREEN_CLASSES`.
**Warning signs:** Magic sequence button does nothing; configurator poll completes silently without finding device.

### Pitfall 5: Pico W GPIO Reserved Pins

**What goes wrong:** Firmware attempts to use GPIO 23, 24, 25, or 29 as button inputs on a Pico W — these are wired to the CYW43 chip, not available as user GPIO.
**Why it happens:** Standard Pico has all GPIO 0-28 available as user pins. Pico W reassigns 4 of them internally.
**How to avoid:** In `init_gpio_pin()`, add a `is_picow_reserved()` guard: skip pins 23, 24, 25, 29. Apply only when `g_cyw43_initialized` is true (indicating Pico W hardware). Pattern from guitar wireless main.c lines 250-253.
**Warning signs:** Firmware locks up or behaves erratically on Pico W with specific GPIO assignments.

### Pitfall 6: Struct Size Exceeds FLASH_PAGE_SIZE

**What goes wrong:** `config_save()` silently truncates config or overflows buffer — later fields including checksum are not written.
**Why it happens:** Flash is programmed in 256-byte pages. The save buffer is `uint8_t buf[FLASH_PAGE_SIZE]` (256 bytes). `memcpy(buf, config, sizeof(retro_config_t))` will overflow if struct exceeds 256 bytes.
**How to avoid:** Add a compile-time assertion: `_Static_assert(sizeof(retro_config_t) <= FLASH_PAGE_SIZE, "retro_config_t exceeds flash page size");`. With current field list the struct is approximately 70-80 bytes — well within limit.
**Warning signs:** Config saves but fails validation on next boot; checksum mismatch.

### Pitfall 7: device_name Validation in Serial Handler

**What goes wrong:** Invalid characters (symbols, non-ASCII) in device_name corrupt BLE advertisement on future Pico W builds, or crash USB string descriptor generation.
**Why it happens:** BLE ADV payload has strict character requirements. USB string descriptors iterate over bytes assuming printable ASCII.
**How to avoid:** In SET:device_name handler, filter to alphanumeric + space only, strip trailing spaces, max 20 chars. Exact pattern from pedal_config_serial.c lines 224-236. This is project standard.
**Warning signs:** BLE won't broadcast (Phase 3+ concern). USB string shows garbled product name.

---

## Code Examples

### XInput Button Mask Lookup Table
```c
// Source: usb_descriptors.h (drums) + guitar wireless main.c pattern
static const uint16_t button_masks[BTN_IDX_COUNT] = {
    [BTN_IDX_DPAD_UP]    = XINPUT_BTN_DPAD_UP,
    [BTN_IDX_DPAD_DOWN]  = XINPUT_BTN_DPAD_DOWN,
    [BTN_IDX_DPAD_LEFT]  = XINPUT_BTN_DPAD_LEFT,
    [BTN_IDX_DPAD_RIGHT] = XINPUT_BTN_DPAD_RIGHT,
    [BTN_IDX_A]          = XINPUT_BTN_A,
    [BTN_IDX_B]          = XINPUT_BTN_B,
    [BTN_IDX_X]          = XINPUT_BTN_X,
    [BTN_IDX_Y]          = XINPUT_BTN_Y,
    [BTN_IDX_START]      = XINPUT_BTN_START,
    [BTN_IDX_SELECT]     = XINPUT_BTN_BACK,
    [BTN_IDX_GUIDE]      = XINPUT_BTN_GUIDE,
    [BTN_IDX_LB]         = XINPUT_BTN_LEFT_SHOULDER,
    [BTN_IDX_RB]         = XINPUT_BTN_RIGHT_SHOULDER,
};
```

### XInput Report Structure (retro gamepad)
```c
// Source: usb_descriptors.h (drums) — same 20-byte XInput layout
typedef struct __attribute__((packed)) {
    uint8_t  report_id;      // always 0x00
    uint8_t  report_size;    // always 0x14 (20)
    uint16_t buttons;        // 13 buttons via masks above
    uint8_t  left_trigger;   // LT axis 0-255
    uint8_t  right_trigger;  // RT axis 0-255
    int16_t  left_stick_x;   // 0 (unused in v1)
    int16_t  left_stick_y;   // 0 (unused in v1)
    int16_t  right_stick_x;  // 0 (unused in v1)
    int16_t  right_stick_y;  // 0 (unused in v1)
    uint8_t  reserved[6];
} xinput_report_t;
```

### XInput Vendor Descriptor (subtype 0x01 — gamepad)
```c
// Source: pico-pedal/src/usb_descriptors.c adapted with XINPUT_SUBTYPE_GAMEPAD=0x01
static const uint8_t xinput_config_desc[] = {
    0x09, TUSB_DESC_CONFIGURATION,
    XINPUT_DESC_CONFIG_TOTAL, 0x00, 0x01, 0x01, 0x00, 0x80, 0xFA,
    0x09, TUSB_DESC_INTERFACE,
    0x00, 0x00, 0x02,
    XINPUT_IF_CLASS, XINPUT_IF_SUBCLASS, XINPUT_IF_PROTOCOL, 0x00,
    // XInput Vendor Descriptor — byte [4] is the subtype
    0x11, 0x21, 0x00, 0x01,
    0x01,  // <-- XINPUT_SUBTYPE_GAMEPAD (0x01)
    0x25,
    XINPUT_EP_IN, XINPUT_REPORT_SIZE,
    0x00, 0x00, 0x00, 0x00, 0x13,
    XINPUT_EP_OUT, XINPUT_OUT_REPORT_SIZE, 0x00, 0x00,
    // ... endpoints same as pedal
};
```

### Analog Trigger Read Path (full pipeline)
```c
// Source: guitar wireless main.c lines 412-427 (adapted for trigger byte output)
// Run in the main input read loop:
static ema_state_t g_ema_lt;
static ema_state_t g_ema_rt;

static uint8_t read_trigger_analog(int8_t pin, uint16_t tmin, uint16_t tmax,
                                   uint8_t invert, uint8_t ema_alpha_pct,
                                   ema_state_t *ema) {
    if (pin < 26 || pin > 28) return 0;
    adc_select_input((uint)(pin - 26));
    uint16_t raw    = adc_read();
    uint16_t scaled = apply_sensitivity(raw, tmin, tmax);
    // alpha: 0 pct → 0 (frozen), 100 pct → 255 (live); match guitar: 0→255, other→value
    uint32_t alpha  = (ema_alpha_pct == 0) ? 255u : (uint32_t)ema_alpha_pct;
    uint16_t smooth = ema_update(ema, scaled, alpha);
    if (invert) smooth = 4095 - smooth;
    return (uint8_t)(smooth * 255u / 4095u);
}

static uint8_t read_trigger_digital(int8_t pin, debounce_state_t *dbs,
                                    uint32_t now_us, uint32_t debounce_us) {
    if (pin < 0 || pin > 28) return 0;
    bool raw     = !gpio_get(pin);  // active-low
    bool pressed = debounce(dbs, raw, now_us, debounce_us);
    return pressed ? 255u : 0u;
}
```

### Configurator.py Changes Required
```python
# Source: configurator.py (lines 840-895) — additions for pico-retro

# Add to CONFIG_MODE_PIDS:
CONFIG_MODE_PIDS = {
    0xF00D: "Guitar Config",
    0xF00E: "Drum Kit Config",
    0xF00F: "Retro Gamepad Config",   # NEW
    0xF010: "Pedal Config",
}

# Add to DEVICE_TYPE_UF2_HINTS:
DEVICE_TYPE_UF2_HINTS = {
    ...existing...,
    "retro_gamepad": "retro",         # NEW
}

# Add to XINPUT_SUBTYPE_TO_DEVTYPE:
XINPUT_SUBTYPE_TO_DEVTYPE = {
    ...existing...,
    1: "retro_gamepad",               # NEW — standard gamepad subtype
}

# Add to OCC_SUBTYPES:
OCC_SUBTYPES = {8, 6, 7, 11, 1}      # Add 1 for retro gamepad

# Add to DEVICE_SCREEN_CLASSES:
DEVICE_SCREEN_CLASSES = {
    ...existing...,
    "retro_gamepad": RetroApp,        # NEW — Phase 2 class
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate digital/analog pins per input (guitar) | Single pin per input, mode selects read method (pedal/retro) | pico-pedal v2 | Simpler config struct, easier configurator UX |
| Guitar-only OCC device detection | DEVTYPE: line first in GET_CONFIG response | guitar firmware v12+ | Enables correct screen routing without subtype guessing |
| Manual USB string UTF-16 | _make_string_desc() helper | All current variants | Eliminates off-by-one errors in string descriptor header |

**Deprecated/outdated:**
- Old guitar firmware had separate `pin_tilt_digital` and `pin_tilt_analog` fields. Retro does NOT need this — single `pin_lt`/`pin_rt` following pedal pattern.
- Some old docs referenced PID 0xF011 for retro. This is incorrect — 0xF00F is available and correct.

---

## Open Questions

1. **Single UF2 vs Two UF2 for FW-01**
   - What we know: A single UF2 that runs on both Pico and Pico W is not possible with the current SDK build system. Every Pico W variant sets `PICO_BOARD pico_w` which compiles in CYW43-specific code that fails on standard Pico.
   - What's unclear: Whether FW-01's intent is "one source tree builds two UF2 files" or literally "one UF2 binary boots on both hardware variants."
   - Recommendation: Clarify intent, but plan for two CMake targets from one source tree. Name them `Retro_Controller.uf2` (Pico) and `Retro_Controller_W.uf2` (Pico W). The Pico W build uses `g_cyw43_initialized` guard pattern from wireless guitar. This is the only viable approach.

2. **OCC_SUBTYPES and configurator routing for subtype 0x01**
   - What we know: Standard gamepads (subtype 0x01) are extremely common — every Xbox 360 pad, many PC controllers. Adding 0x01 to `OCC_SUBTYPES` means the configurator will light up for ANY generic XInput gamepad, not just pico-retro.
   - What's unclear: Whether this creates false positives in the wild (a real Xbox 360 controller plugged in while a pico-retro is connected would be mis-identified).
   - Recommendation: The VID/PID check is the primary filter — `OCC_SUBTYPES` is a secondary scan that only triggers "Configure Controller" UI. Since VID/PID 0x045E/0x028E is the same for all XInput devices, the subtype is the only distinguishing feature. Accept the tradeoff: pico-retro users likely don't have real Xbox 360 controllers simultaneously. If this becomes an issue, use a less common subtype (0x03 ArcadeStick is also available and less commonly seen in the wild). Decide before writing usb_descriptors.h.

3. **EMA Alpha Convention**
   - What we know: Guitar firmware uses inverted convention (0 stored → 255 internal = fastest response; 100 stored → 100 internal = more smoothing). Logically counterintuitive.
   - What's unclear: Whether future Phase 2 configurator should expose this as "Smoothing %" (where 0%=no smooth, 100%=maximum smooth) and whether to match guitar's internal convention or use a cleaner one.
   - Recommendation: For firmware, store raw uint8_t (0-100). For display, the configurator converts as needed. Keep firmware-side convention identical to guitar for copy-paste reuse.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None — embedded C firmware, no unit test framework in project |
| Config file | N/A |
| Quick run command | Flash to hardware, run `GET_CONFIG` over serial |
| Full suite command | Flash, test all buttons + analog triggers, verify USB enumeration |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FW-01 | Single source builds Pico + Pico W UF2 | Build smoke | `cmake --build build-pico && cmake --build build-picow` | ❌ Wave 0 — CMakeLists.txt does not exist |
| FW-02 | Dual-mode boot — XInput normal, CDC on scratch trigger | Manual hardware | Flash, connect, verify XInput in joy.cpl; send magic, verify CDC | ❌ Wave 0 |
| FW-03 | 13-button input reads correctly | Manual hardware | Press each button, observe in joy.cpl | ❌ Wave 0 |
| FW-04 | LT/RT analog + digital mode works | Manual hardware | Set mode, read trigger axis in joy.cpl | ❌ Wave 0 |
| FW-05 | GPIO assignments configurable via SET | Manual serial | SET:btn0=N, verify pin reads correctly | ❌ Wave 0 |
| FW-06 | Config persists across reboot | Manual hardware | SAVE, reboot, GET_CONFIG, verify values match | ❌ Wave 0 |
| FW-07 | Serial protocol responds correctly | Manual serial | PING→PONG, GET_CONFIG→DEVTYPE, SET→OK, SAVE→OK | ❌ Wave 0 |
| FW-08 | Enumerates as gamepad subtype 0x01 | Manual hardware | Check Device Manager / joy.cpl subtype label | ❌ Wave 0 |
| FW-09 | EMA smoothing reduces noise | Manual hardware | Observe analog trigger bar with different alpha values | ❌ Wave 0 |
| FW-10 | Trigger calibration scales to 0-255 | Manual serial | SET:lt_min/max, monitor trigger output | ❌ Wave 0 |
| USB-02 | XInput VID 0x045E PID 0x028E | Manual hardware | Check Device Manager USB device properties | ❌ Wave 0 |

**Note:** All firmware validation is manual (hardware-on-target testing). No automated test framework exists in the project. Verification is performed by flashing, interacting with hardware, and reading serial output. Build smoke tests (does it compile without errors) are the only automatable check.

### Sampling Rate
- **Per task commit:** Compile smoke test — verify `cmake --build build-pico` succeeds without errors or warnings
- **Per wave merge:** Full manual flash test — XInput enumeration, button reads, serial protocol
- **Phase gate:** All FW-0x requirements manually verified before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `Source Code/pico-retro/CMakeLists.txt` — build system for both Pico and Pico W targets
- [ ] `Source Code/pico-retro/src/retro_config.h` — config struct definition
- [ ] `Source Code/pico-retro/src/retro_config.c` — flash load/save
- [ ] `Source Code/pico-retro/src/retro_config_serial.c` — serial command handler
- [ ] `Source Code/pico-retro/src/main.c` — boot flow + input loop
- [ ] `Source Code/pico-retro/src/usb_descriptors.h` — XInput/CDC constants
- [ ] `Source Code/pico-retro/src/usb_descriptors.c` — descriptor callbacks
- [ ] `Source Code/pico-retro/src/xinput_driver.h` — copy from existing project
- [ ] `Source Code/pico-retro/src/xinput_driver.c` — copy from existing project
- [ ] `Source Code/pico-retro/pico_sdk_import.cmake` — copy from existing project

---

## Sources

### Primary (HIGH confidence)
- `Source Code/pico-pedal/src/pedal_config.h` — config struct pattern, field names, magic, version, checksum
- `Source Code/pico-pedal/src/pedal_config.c` — flash save/load/checksum implementation (exact code)
- `Source Code/pico-pedal/src/pedal_config_serial.c` — serial command handler implementation (exact code)
- `Source Code/pico-pedal/src/usb_descriptors.h` — XInput VID/PID, CDC PID 0xF010, magic sequence constants
- `Source Code/pico-pedal/src/usb_descriptors.c` — descriptor callback implementations
- `Source Code/pico-guitar-controller-wireless/src/main.c` — USB mount timeout boot flow, EMA smoothing, ADC scaling, debounce, watchdog reboot
- `Source Code/pico-guitar-controller-wireless/src/guitar_config.h` — EMA alpha field, calibration fields, INPUT_MODE constants
- `Source Code/pico-drums-wired/src/usb_descriptors.h` — XInput button masks, report struct, drum subtype 0x08 (reference for subtype byte position)
- `Source Code/configurator/configurator.py` lines 840–898 — CONFIG_MODE_PIDS, OCC_SUBTYPES, XINPUT_SUBTYPE_TO_DEVTYPE, DEVICE_SCREEN_CLASSES (live configurator source)
- All `CMakeLists.txt` files — confirmed `set(PICO_BOARD pico_w)` requirement for Pico W builds
- `CLAUDE.md` — VID/PID reference table, architectural rules

### Secondary (MEDIUM confidence)
- `Source Code/pico-guitar-controller-wired/src/usb_descriptors.h` — confirmed PID 0xF00D for wired guitar
- `detailedcontext.md` — guitar_config_t struct sizeof (188 bytes), confirming well under FLASH_PAGE_SIZE

### Tertiary (LOW confidence)
- None — all claims verified against live source code

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in existing CMakeLists.txt files
- Architecture patterns: HIGH — code examples sourced directly from working firmware
- Pitfalls: HIGH — all pitfalls derived from live code patterns, existing guards, or CLAUDE.md rules
- Config struct design: HIGH — verified against pedal_config.h template directly
- PID assignment: HIGH — verified against all usb_descriptors.h and configurator.py
- Single-UF2 constraint: HIGH — verified by examining all CMakeLists.txt

**Research date:** 2026-03-19
**Valid until:** 2026-09-19 (stable Pico SDK — not fast-moving; valid for ~6 months)
