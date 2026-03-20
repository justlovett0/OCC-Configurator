# Architecture Research

**Domain:** Embedded gamepad firmware + Windows configurator GUI (pico-retro integration)
**Researched:** 2026-03-19
**Confidence:** HIGH — based on direct source code analysis of all existing variants

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     OCC Firmware Variants (Pico)                     │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────┤
│guitar-wired  │ drums-wired  │guitar-wireless│ pico-pedal  │pico-retro│
│  DEVTYPE:    │  DEVTYPE:    │  DEVTYPE:    │  DEVTYPE:   │ DEVTYPE: │
│ guitar_alt   │  drum_kit    │ guitar_alt   │   pedal     │  retro   │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬──────┴────┬────┘
       │              │              │              │           │
       └──────────────┴──────────────┴──────────────┴───────────┘
                              │ USB (CDC serial, 115200 baud)
                              │ VID 0x2E8A / PID unique per type
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 OCC Configurator (Python/Tkinter, Windows)           │
├─────────────┬─────────────┬─────────────┬──────────────┬────────────┤
│  MainMenu   │FlashFirmware│  EasyConfig │  App(Guitar) │  RetroApp  │
│             │   Screen    │   Screen    │  DrumApp     │  (new)     │
│             │             │             │  PedalApp    │            │
└─────────────┴─────────────┴─────────────┴──────────────┴────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| `pico-retro/src/retro_config.h` | Declares `retro_config_t` struct, DEVTYPE constant, button enum | C header, packed struct with magic/version/pins/name/checksum |
| `pico-retro/src/retro_config.c` | Flash load/save, CRC checksum, set_defaults | Identical pattern to `pedal_config.c` and `guitar_config.c` |
| `pico-retro/src/retro_config_serial.c` | CDC serial command loop (PING, GET_CONFIG, SET, SAVE, etc.) | Identical pattern to `pedal_config_serial.c` |
| `pico-retro/src/main.c` | Boot decision (watchdog scratch), XInput play loop, config mode dispatch | Identical to pico-pedal pattern (no LEDs, simpler than guitar) |
| `pico-retro/src/usb_descriptors.c/h` | USB VID/PID table, XInput subtype, config mode CDC VID/PID | Copy from pedal; change CONFIG_MODE_PID to `0xF00F` (next available), subtype to 0x01 (gamepad) |
| `pico-retro/src/xinput_driver.c/h` | XInput HID report building and submission | Verbatim copy — no changes needed |
| `pico-retro/CMakeLists.txt` | CMake project definition, pico_sdk_import, ninja build | Modelled exactly on `pico-guitar-controller-wired/CMakeLists.txt` |
| Configurator `RetroApp` class | Screen for device name, GPIO pin assignment, analog trigger config, detect scan, analog monitor | New screen class following `PedalApp` as closest structural model |
| Configurator `DEVICE_SCREEN_CLASSES` | Maps DEVTYPE string → screen class | Add `"retro": RetroApp` entry |
| Configurator `DEVICE_TYPE_UF2_HINTS` | Maps DEVTYPE → UF2 filename substring | Add `"retro": "retro"` |
| Configurator `OCC_SUBTYPES` | Set of recognized XInput subtypes | Add retro subtype integer |
| `build_all_firmware.bat` | Sequential build of all firmware, copy UF2 to configurator folder | Add step 7 for pico-retro |

## Recommended Project Structure

```
Source Code/
├── pico-retro/                        # New firmware project (mirrors pico-pedal layout)
│   ├── CMakeLists.txt                 # Project build definition
│   ├── pico_sdk_import.cmake          # SDK import (copy verbatim from any existing variant)
│   ├── build.bat                      # Single-project build helper (optional)
│   └── src/
│       ├── main.c                     # Boot logic, XInput play loop, config mode
│       ├── retro_config.h             # Config struct, DEVTYPE, button enum
│       ├── retro_config.c             # Flash load/save/defaults/checksum
│       ├── retro_config_serial.h      # config_mode_main() declaration
│       ├── retro_config_serial.c      # CDC serial command loop
│       ├── usb_descriptors.h          # VID/PID, XInput subtype, report struct
│       ├── usb_descriptors.c          # USB descriptor tables
│       ├── xinput_driver.h            # XInput send API
│       ├── xinput_driver.c            # XInput HID driver (verbatim copy)
│       └── tusb_config.h              # TinyUSB configuration (verbatim copy)
│
├── configurator/
│   ├── configurator.py                # Add RetroApp class + routing entries
│   ├── Retro_Controller.uf2           # (populated by build_all_firmware.bat)
│   ├── Retro_Controller.gif           # Tile animation (same base name as UF2)
│   └── Retro_Controller.uf2.date      # Build date sidecar
│
├── build_all_firmware.bat             # Add step [7/7] for pico-retro
└── build_all_and_package.bat          # No changes needed
```

### Structure Rationale

- **pico-retro/ as sibling directory:** All existing variants are siblings under `Source Code/`. Consistent placement avoids special-casing in build scripts.
- **No shared library folder:** Each firmware variant is intentionally self-contained. Files like `xinput_driver.c` are copied, not symlinked. This is an established project convention that keeps each variant independently buildable.
- **pico-pedal as the template:** pico-pedal is the most recent and simplest variant (no LEDs, no BLE, no I2C). pico-retro follows the same pattern, keeping complexity minimal.

## Architectural Patterns

### Pattern 1: Dual-Mode Boot via Watchdog Scratch Register

**What:** At startup, `main.c` reads `watchdog_hw->scratch[0]`. If it equals `WATCHDOG_CONFIG_MAGIC (0xC0F16000)`, the firmware branches into CDC serial config mode instead of XInput play mode. The magic value is written by the firmware itself in response to the magic vibration XInput sequence, then the device reboots.

**When to use:** Every firmware variant uses this pattern identically. pico-retro copies it verbatim.

**Trade-offs:** Simple and reliable. Watchdog scratch register survives a soft reboot. No additional hardware needed.

**Implementation sketch:**
```c
// In main.c — copy this block unchanged from pico-pedal/src/main.c
static bool check_scratch_config_mode(void) {
    if (watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC) {
        watchdog_hw->scratch[0] = 0;
        return true;
    }
    return false;
}
// In main():
if (check_scratch_config_mode()) {
    g_config_mode = true;
    tusb_init();
    config_mode_main(&g_config);   // never returns
}
```

### Pattern 2: Packed Config Struct with CRC in Flash

**What:** Each firmware variant defines one `packed` struct with a magic constant, version number, all config fields, and a trailing CRC32 checksum. The struct is stored in the last flash sector. On boot, the firmware validates magic + version + CRC; on mismatch it writes defaults.

**When to use:** Every firmware variant uses this. pico-retro defines `retro_config_t` following the same layout.

**Trade-offs:** Flash wear is low (config saves are infrequent). Packed struct is simple but version bumps require a CRC reset — any field addition increments `CONFIG_VERSION`.

**retro_config_t minimum fields:**
```c
typedef struct __attribute__((packed)) {
    uint32_t magic;                           // 0x52455452 "RETR"
    uint16_t version;                         // increment on every struct change

    int8_t   pin_buttons[BTN_IDX_COUNT];      // 13 buttons, -1 = disabled

    // LT/RT analog trigger inputs (optional — -1 = disabled)
    uint8_t  lt_mode;                         // INPUT_MODE_DIGITAL or INPUT_MODE_ANALOG
    int8_t   pin_lt_digital;
    int8_t   pin_lt_analog;
    uint16_t lt_min, lt_max;
    uint8_t  lt_invert;

    uint8_t  rt_mode;
    int8_t   pin_rt_digital;
    int8_t   pin_rt_analog;
    uint16_t rt_min, rt_max;
    uint8_t  rt_invert;

    uint8_t  ema_alpha;                       // analog smoothing
    uint8_t  debounce_ms;

    char     device_name[DEVICE_NAME_MAX + 1];
    uint32_t checksum;
} retro_config_t;
```

### Pattern 3: DEVTYPE String → Configurator Screen Routing

**What:** When the configurator opens a CDC serial connection, it sends `GET_CONFIG`. The first line of the firmware response is `DEVTYPE:<string>`. The configurator reads this string and looks it up in `DEVICE_SCREEN_CLASSES` to find the correct screen class to show.

**When to use:** Every connected-device screen. Adding pico-retro requires two additions in `configurator.py`:

```python
# In DEVICE_TYPE_UF2_HINTS — maps DEVTYPE to UF2 filename substring
DEVICE_TYPE_UF2_HINTS = {
    ...
    "retro": "retro",        # matches "Retro_Controller.uf2"
}

# In DEVICE_SCREEN_CLASSES — maps DEVTYPE to screen class
DEVICE_SCREEN_CLASSES = {
    ...
    "retro": RetroApp,
}
```

And in the firmware's `retro_config.h`:
```c
#define DEVICE_TYPE  "retro"
```

**Trade-offs:** The string-based mapping is extensible with zero changes to routing logic. The only risk is a mismatch between the firmware's `DEVICE_TYPE` constant and the configurator's dict key — keep them identical.

### Pattern 4: XInput Subtype for Pre-Serial Detection

**What:** Before the configurator opens a serial port, it identifies OCC devices by their XInput subtype (byte in the USB descriptor). This enables the "Easy Config" flow and vibration-triggered config mode entry.

**pico-retro XInput subtype:** The retro gamepad should use `XINPUT_DEVSUBTYPE_GAMEPAD = 0x01` (standard gamepad, not a guitar subtype). This requires:
1. Adding the new subtype to `OCC_SUBTYPES` in configurator.py
2. Adding a `XINPUT_SUBTYPE_TO_DEVTYPE` entry: `{1: "retro"}` — but note subtype 1 may conflict with standard gamepads. Use a less common subtype (e.g., 0x10 = wheel, or a custom value) to avoid false positives. The safest approach is to verify the chosen value does not appear in `XINPUT_SUBTYPE_TO_DEVTYPE` for any other OCC variant.

**Current OCC subtype assignments:**
```
8  → drum_kit
6  → guitar_alternate
7  → guitar_alternate
11 → dongle
```

**Recommendation:** Assign subtype `0x10` (XINPUT_DEVSUBTYPE_WHEEL, rarely used by real wheels in this context) or any value not yet claimed. Confirm final value before firmware implementation.

## Data Flow

### Config Mode Entry (XInput → CDC)

```
User clicks "Configure" in MainMenu
    ↓
Configurator sends magic vibration to XInput slot
    (left_motor=0x47, right=0x43 → 0x43/0x47 → 0x4F/0x4B)
    ↓
Firmware validates 3-step sequence
    ↓
Firmware writes WATCHDOG_CONFIG_MAGIC → scratch[0]
Firmware calls watchdog_reboot(0, 0, 50)
    ↓
Pico reboots; scratch[0] is read in main()
g_config_mode = true → tusb_init() with CDC descriptors (VID 0x2E8A / PID retro-specific)
    ↓
Configurator detects new COM port
Sends GET_CONFIG
Firmware responds: "DEVTYPE:retro\r\nCFG:...\r\n..."
    ↓
Configurator reads DEVTYPE → looks up DEVICE_SCREEN_CLASSES["retro"] → RetroApp
RetroApp.show() called
```

### Config Read/Write Cycle (Configurator ↔ Firmware)

```
RetroApp._load_config()
    → pico.get_config()
    → serial: GET_CONFIG
    ← DEVTYPE:retro
    ← CFG:button0=2,button1=3,...,lt_mode=1,lt_min=100,...,device_name=MyPad
    → parse into tk.IntVar / tk.StringVar backing state

User edits a field → backing var changes

RetroApp._save_config()
    → pico.send("SET:button0=2")
    → pico.send("SET:lt_mode=1")
    → ... (one SET per changed field)
    → pico.send("SAVE")
    ← OK
    → firmware writes retro_config_t to flash
```

### Firmware Play Loop (XInput mode)

```
Boot → config valid in flash → g_config_mode = false
    ↓
tusb_init() with XInput descriptors (VID 0x045E / PID 0x028E, subtype=retro_subtype)
    ↓
Loop at ~1000 Hz:
    read 13 digital GPIO pins (active-low, debounced)
    read LT/RT analog ADC channels (if configured)
    build xinput_report_t:
        buttons bitmask → standard ABXY + DPad + Start/Select/Guide + LB/RB
        left_trigger  → LT (0–255 byte or 0/255 digital)
        right_trigger → RT (0–255 byte or 0/255 digital)
        sticks → 0 (retro gamepad has no sticks)
    call tud_xinput_n_report(0, &report)
    check for magic vibration sequence → config mode reboot if detected
```

### Wireless Path (Architecture Ready, Not Yet Implemented)

```
[Future] pico-retro on Pico W:

Boot → USB host detection (USB_MOUNT_TIMEOUT_MS)
    USB host present → XInput wired (identical to wired path above)
    No USB host → wireless mode (BLE HID or dongle BLE broadcast)
        BLE HID: bt_hid_gamepad pattern from guitar-wireless
        Dongle:  controller_bt.c pattern from guitar-wireless

Key files to add (future phase):
    pico-retro/src/bt_hid_gamepad.c/h   (copy from guitar-wireless, adapt report)
    pico-retro/src/controller_bt.c/h    (copy from guitar-wireless, adapt report)
    pico-retro/src/btstack_config.h     (copy verbatim)
```

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single retro variant | Described above — one new firmware project, one new screen class |
| Multiple retro variants (e.g. SNES vs N64 layout) | Add DEVTYPE variants like "retro_snes" / "retro_n64"; reuse RetroApp with a layout_mode field; no structural changes needed |
| Community forks | The pico-retro project is self-contained by design; forks can modify the src/ folder independently of other variants |

## Anti-Patterns

### Anti-Pattern 1: Reusing an Existing VID/PID for Config Mode

**What people do:** Assign `0xF00D` (guitar) or `0xF00E` (drums) as the config-mode PID for pico-retro to "save work."

**Why it's wrong:** The configurator identifies which firmware is connected by (VID, PID) at the OS level. Sharing a PID means the configurator cannot distinguish pico-retro from guitar in config mode, which breaks routing before `GET_CONFIG` is even sent.

**Do this instead:** Assign a new unique PID. `0xF00F` is the next sequential value after drums (`0xF00E`) and is currently unused.

### Anti-Pattern 2: Including apa102_leds.h in retro_config.h

**What people do:** Copy guitar_config.h wholesale and forget to remove the LED include, or add LED fields "for future use."

**Why it's wrong:** The `config_serial.c` rule in CLAUDE.md states that `apa102_leds.h` defines `LED_INPUT_COUNT=16` as a fixed constant and must not be redefined. Including it from a config header that also tries to define LED-adjacent constants causes conflicts. More importantly, pico-retro has no LED support in v1.

**Do this instead:** `retro_config.h` must not include `apa102_leds.h`. The LED section is absent from `retro_config_t` entirely.

### Anti-Pattern 3: Adding RetroApp as a Toplevel Instead of Frame

**What people do:** Create `RetroApp` as a `tk.Toplevel` window for "simplicity."

**Why it's wrong:** CLAUDE.md explicitly states all screens are `tk.Frame` instances sharing one root window — never `Toplevel` for screens. The root window geometry is set once (1180x820) and must not be changed.

**Do this instead:** `RetroApp.__init__` stores `self.frame = tk.Frame(root, bg=BG_MAIN)`. The `show()` method calls `self.frame.pack(fill="both", expand=True)` and sets `self.root.title(...)` and `self.root.config(menu=self._menu_bar)`.

### Anti-Pattern 4: Rebuilding UI Cards on Every Poll

**What people do:** Call `_build_ui()` inside the 1-second poll callback to reflect updated state.

**Why it's wrong:** Combo dropdowns collapse immediately whenever the widget is destroyed and recreated. CLAUDE.md rule: never rebuild UI cards/buttons unless their backing state tuple has actually changed.

**Do this instead:** Update the backing `tk.IntVar` / `tk.StringVar` / `tk.BooleanVar` directly. Only rebuild the widget tree when the structural shape of the config has changed (e.g., switching between digital and analog trigger mode).

### Anti-Pattern 5: Adding Retro Subtype to OCC_SUBTYPES Without XINPUT_SUBTYPE_TO_DEVTYPE

**What people do:** Add the subtype to `OCC_SUBTYPES` but forget `XINPUT_SUBTYPE_TO_DEVTYPE`, so EasyConfig finds the device but can't infer its type for the firmware tile.

**Why it's wrong:** EasyConfig's state machine has an "xinput" branch that calls `XINPUT_SUBTYPE_TO_DEVTYPE.get(xinput_subtype, "unknown")`. An unknown type causes it to show a generic firmware tile and prevents backup/restore routing.

**Do this instead:** Always add both entries atomically: `OCC_SUBTYPES.add(retro_subtype)` and `XINPUT_SUBTYPE_TO_DEVTYPE[retro_subtype] = "retro"`.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Pico SDK (CMake) | `pico_sdk_import.cmake` + `pico_sdk_init()` | Copy `pico_sdk_import.cmake` verbatim from any existing variant; requires `PICO_SDK_PATH` env var |
| TinyUSB | CMake `tinyusb_device` + `tinyusb_board` link | `tusb_config.h` configures class drivers; copy from pico-pedal, no changes needed for wired-only v1 |
| BTstack | CMake `pico_cyw43_arch_none` + btstack libs | Only needed for wireless variant (future phase); not present in v1 |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `retro_config.c` ↔ Flash | Direct `flash_range_erase` / `flash_range_program` via Pico SDK | Offset = last sector: `(PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)` — same as all other variants |
| `retro_config_serial.c` ↔ `retro_config.h` | Includes config header; calls `config_load`, `config_save`, `config_set_defaults` | Standard pattern; serial module must not include `apa102_leds.h` directly |
| `RetroApp` ↔ `PicoSerial` | Calls `pico.send(cmd)`, `pico.get_config()`, `pico.flush_input()` | `PicoSerial` is a shared class in configurator.py; no changes needed to it |
| `RetroApp` ↔ `MainMenu` | `on_back` callback passed in constructor; called when user clicks "Back" | Standard pattern; `RetroApp` calls `self._on_back()` to return to menu |
| `build_all_firmware.bat` ↔ `pico-retro/` | `cd /d` to project dir, runs cmake+ninja, `copy /Y` UF2 to configurator folder | Follow [N/7] numbering; copy both `.uf2` and `.uf2.date` |
| `configurator.py` ↔ `Retro_Controller.uf2` | `find_uf2_files()` scans for `*.uf2`; UF2 filename must not contain "nuke"; GIF shares base name | File must be named `Retro_Controller.uf2` to match the "retro" hint substring |

## VID/PID Assignment for pico-retro

| Mode | VID | PID | Notes |
|------|-----|-----|-------|
| XInput play mode | 0x045E | 0x028E | Same as all OCC variants — standard XInput |
| Config mode (CDC) | 0x2E8A | 0xF00F | Next sequential after 0xF00E (drums); currently unassigned |

## Sources

- Direct source analysis: `Source Code/pico-guitar-controller-wired/src/` (HIGH confidence)
- Direct source analysis: `Source Code/pico-pedal/src/` (HIGH confidence)
- Direct source analysis: `Source Code/pico-guitar-controller-wireless/src/` (HIGH confidence)
- Direct source analysis: `Source Code/configurator/configurator.py` lines 870–15868 (HIGH confidence)
- Direct source analysis: `Source Code/build_all_firmware.bat` (HIGH confidence)
- `CLAUDE.md` architectural rules (HIGH confidence — authoritative project guidelines)
- `PROJECT.md` requirements and constraints (HIGH confidence)

---
*Architecture research for: pico-retro integration into OCC multi-variant platform*
*Researched: 2026-03-19*
