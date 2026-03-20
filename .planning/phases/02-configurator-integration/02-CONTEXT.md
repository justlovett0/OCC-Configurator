# Phase 2: Configurator Integration - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Build RetroApp advanced configurator screen that connects to pico-retro firmware, enabling users to:
1. Detect and assign GPIO pins for all 13 buttons (DPad 4-way, ABXY, Start, Select, Guide, LB, RB)
2. Detect and configure 2 analog/digital triggers (LT/RT) with per-trigger mode selection and calibration
3. Live-monitor analog trigger output during calibration
4. Back up config, flash firmware updates, and restore config via existing pipeline

Identity constants from Phase 1 are locked: DEVTYPE="pico_retro", config-mode PID=0xF00F, XInput subtype=0x01, serial protocol reuses existing commands (PING, GET_CONFIG, SET, SAVE, DEFAULTS, REBOOT).

</domain>

<decisions>
## Implementation Decisions

### GPIO Button Detection & Pin Assignment
- **Default GPIO assignments**: Firmware ships with sensible GPIO defaults (e.g., DPad on GP0-GP3, buttons on GP4-GP13, triggers on GP26-GP27); users only reassign if using different pins
- **DETECT mechanism**: Clicking "Detect [Button]" starts a 10-second SCAN in the firmware. If no button press detected, auto-cancel with "timeout" message. User can also cancel manually.
- **Pin editing**: Users can both DETECT buttons AND manually edit GPIO pin numbers using custom dropdowns (like GuitarApp pattern)
- **Button display**: All 13 buttons appear as a single scrollable list (not grouped); each row shows button name, DETECT button, and GPIO pin dropdown
- **Manual override UX**: After detecting a pin, user can click the dropdown to manually select a different GPIO (0-27) if needed

### Analog Trigger Configuration (LT/RT)
- **Tab-based organization**: LT and RT triggers are in separate tabs for clarity
- **Mode-dependent UI**:
  - Mode selector at top of each trigger tab
  - If Digital mode: show only GPIO pin dropdown + DETECT button
  - If Analog mode: show full analog suite (min/max sliders, EMA alpha, invert toggle, live monitoring)
- **Analog calibration**:
  - Min/max values are raw ADC 0-4095 (user-facing labels: "Min", "Max")
  - EMA alpha is 0-100% (user-facing slider, stored as 0-100 in firmware config)
  - Invert toggle reverses calibration direction (0=normal, 1=inverted, stored as boolean in config)
- **Live monitoring** (analog only):
  - "Enable Monitor Mode" toggle at top of trigger tab
  - When enabled: show inline bars displaying real-time raw ADC and calibrated output (0-255) below min/max sliders
  - Bars update in real-time as user adjusts sliders (following GuitarApp pattern)
  - No monitoring for digital triggers (DETECT alone confirms wiring)

### Screen Organization & Navigation
- **Overall structure**: Single scrollable Frame containing device name section → button list section → trigger tabs → menu bar
- **Entry point**: Main menu auto-detects device type; if pico-retro detected, show "Advanced Configuration" button (use existing main menu detection logic)
- **Back button**: RetroApp has a "Main Menu" button that:
  - Saves configuration to device (SAVE command)
  - Returns controller to play mode (REBOOT command)
  - Navigates back to main menu
- **Menu bar**: Full Advanced menu (Flash Firmware, BOOTSEL, Export/Import, Serial Debug) matching GuitarApp/DrumApp pattern

### Config Storage & Serialization
- **Struct fields** (from Phase 1): `int8_t pin_buttons[13]`, `int8_t pin_lt`, `pin_rt`, `uint8_t mode_lt/mode_rt`, `uint16_t lt_min, lt_max, rt_min, rt_max`, `uint8_t lt_invert, rt_invert`, `uint8_t lt_ema_alpha, rt_ema_alpha` (0-100%), `char device_name[32]`
- **Device name**: Alphanumeric + space, max 20 chars, validated in both firmware + configurator (existing pattern)
- **Config backup/restore**: Automatic during firmware flash (existing OCC backup/restore thread pattern); RetroApp does not need new backup logic

### Firmware Update Integration
- **UF2 discovery**: Retro_Controller.uf2 and Retro_Controller_W.uf2 added to firmware tile grid (discover via find_uf2_files() pattern)
- **Device routing**: XINPUT_SUBTYPE_TO_DEVTYPE dict maps 0x01 → "pico_retro"; OCC_SUBTYPES list includes 1
- **GIF asset**: Retro_Controller.gif must exist in configurator bundle (placeholder OK if animation not ready; matches existing tile asset pattern)
- **Update UI**: Menu item "Flash Firmware to Pico..." shows both retro variants; backup/restore happens automatically like other controller types

### Claude's Discretion
- Exact visual layout and spacing for button rows and trigger sections (follow GuitarApp/DrumApp patterns for consistency)
- Specific font sizes and colors (use existing theme constants: BG_CARD, TEXT, ACCENT_BLUE, etc.)
- EMA alpha conversion formula (linear 0-100 or curve-based; match guitar implementation)
- Exact button row height and padding

</decisions>

<specifics>
## Specific Ideas

- RetroApp should look and feel consistent with GuitarApp and DrumApp (dark theme, RoundedButton for detects, same menu structure)
- For GPIO dropdowns, follow the existing GuitarApp combo box pattern with GPIO 0-27 + "disabled" option
- Device name field: similar to existing guitar device name input, with real-time validation (alphanumeric + space, max 20 chars)
- Tab navigation in trigger section should use standard Tkinter tabs (like existing patterns in the codebase)
- Live monitor bars: follow GuitarApp's whammy/tilt monitor pattern (raw ADC bar + calibrated 0-255 bar side-by-side)

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Configurator Patterns
- `Source Code/configurator/configurator.py` §8138–8300 — App class constructor and structure (menu bar, pin_vars, scanning pattern, device routing)
- `Source Code/configurator/configurator.py` §2970–3030 — Button DETECT mechanism (start_detect, _on_detected, _on_error, SCAN/PIN: protocol)
- `Source Code/configurator/configurator.py` §3100–3200 — Live monitoring pattern (monitor enable toggle, real-time bars, whammy/tilt example)
- `Source Code/configurator/configurator.py` §12009–12100 — DrumApp class structure (menu bar pattern, _build_menu, _build_ui)
- `Source Code/configurator/configurator.py` §1945–2090 — FlashFirmwareScreen (firmware discovery, tile grid, UF2 handling)

### Existing Device Integration
- `Source Code/configurator/configurator.py` § "find_uf2_files()" — UF2 discovery logic (used for firmware tiles)
- `Source Code/configurator/configurator.py` § "DEVICE_SCREEN_CLASSES" — Device routing dict (maps DEVTYPE to screen class)
- `Source Code/configurator/configurator.py` § "XINPUT_SUBTYPE_TO_DEVTYPE" — XInput subtype to device type mapping (add 1 → "pico_retro")
- `Source Code/configurator/configurator.py` § "OCC_SUBTYPES" — List of supported XInput subtypes (add 1 for pico-retro)

### Firmware Configuration Protocol
- `.planning/phases/01-firmware-foundation/01-CONTEXT.md` §L84–L90 — Serial config protocol (PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, REBOOT)
- `Source Code/pico-retro/src/retro_config.h` — Config struct definition (pins, modes, calibration, device_name, checksum — mirrors pedal_config.h pattern)
- `Source Code/pico-retro/src/config_serial.c` — Serial command handler (SET key parsing, GET_CONFIG response formatting)

### Backup/Restore Pipeline
- `Source Code/configurator/configurator.py` § "_flash_firmware()" — Firmware flash with automatic backup/restore (reuse existing logic, add pico-retro to DEVICE_SCREEN_CLASSES)

### Device Naming
- `CLAUDE.md` § "Device name" — Alphanumeric + space, max 20 chars, validated in firmware + configurator
- Existing device name validation pattern (used in guitar, drums, pedal controllers)

### Requirements
- `.planning/REQUIREMENTS.md` §L23–L33 — Phase 2 CFG requirements (CFG-02 through CFG-11) — exact acceptance criteria

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **GuitarApp class** — Full template for RetroApp structure (menus, scrolling, pin_vars, button detection, live monitoring)
- **Button DETECT pattern** — Existing start_detect() → pico.start_scan() → read_scan_line(PIN:X) → pico.stop_scan() flow; copy and adapt
- **Live monitor bars** — GuitarApp whammy/tilt monitor UI (real-time ADC + calibrated bars); adapt for LT/RT triggers
- **GPIO dropdown** — Combo boxes with GPIO 0-27 + "disabled" option (reusable pattern across controllers)
- **Device name input** — Text field with real-time validation (alphanumeric + space, max 20 chars)
- **Tab control** — Standard Tkinter tabs for separating LT and RT trigger configuration
- **Firmware flash dialog** — Existing menu-driven firmware selection and backup/restore (reuse for pico-retro .uf2 files)

### Established Patterns
- **Device detection** — DEVTYPE response routes to controller-specific App class via DEVICE_SCREEN_CLASSES dict
- **Button detection** — SCAN command + PIN: response + threading pattern (proven in EasyConfig and App)
- **Config serialization** — GET_CONFIG parses all struct fields; SET:key=value updates individual fields; SAVE persists to flash
- **Menu structure** — App/DrumApp menu bar with Advanced cascade menu (Flash Firmware, BOOTSEL, Export/Import, Serial Debug)
- **Scrollable UI** — Single scrollable Frame with all controls (pin_vars dict for state, _all_widgets list for tracking)
- **Live monitoring toggle** — Enable/disable toggle that starts/stops background polling thread (guitar App pattern)
- **Firmware update** — Automatic backup before flash, restore after reboot via SET commands (existing pipeline, pico-retro just needs device routing)

### Integration Points
- **DEVICE_SCREEN_CLASSES**: Add `"pico_retro": RetroApp` mapping so configurator routes pico-retro devices to RetroApp
- **XINPUT_SUBTYPE_TO_DEVTYPE**: Add `1: "pico_retro"` so XInput subtype 0x01 maps to pico_retro device type
- **OCC_SUBTYPES**: Add `1` to supported subtypes list (for firmware detection and routing)
- **find_uf2_files()**: Will auto-discover Retro_Controller.uf2 and Retro_Controller_W.uf2 (no code change needed if files follow naming pattern)
- **Main menu device detection**: Existing auto-detect logic will recognize DEVTYPE:pico_retro and show "Advanced Configuration" button (no changes needed)

</code_context>

<deferred>
## Deferred Ideas

- LED strip support for pico-retro — Future phase (v2 requirement)
- Wireless/BLE configuration UI — Phase 3+ (architecture ready in firmware, UI deferred)
- Advanced button remapping (chords, modifiers) — Future enhancement (not standard gamepad feature)

</deferred>

---

*Phase: 02-configurator-integration*
*Context gathered: 2026-03-20*
