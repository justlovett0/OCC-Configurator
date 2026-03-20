# Project Research Summary

**Project:** OCC pico-retro — Retro Gamepad Firmware Variant + Configurator Extension
**Domain:** Embedded RP2040 firmware (C/Pico SDK) + Windows GUI configurator (Python/Tkinter)
**Researched:** 2026-03-19
**Confidence:** HIGH

## Executive Summary

pico-retro is a new OCC platform variant — a retro-style gamepad firmware for the Raspberry Pi Pico targeting 13 digital buttons (DPad, ABXY, Start/Select/Guide, LB/RB) plus optional analog LT/RT triggers. The OCC platform already has five proven variants (guitar-wired, guitar-wireless, drums-wired, pico-dongle, pico-pedal) and pico-retro is a straight extension of those patterns rather than a greenfield build. All foundational concerns — dual-mode USB, flash-backed config, config serial protocol, configurator routing, and build pipeline integration — have established, battle-tested patterns that pico-retro copies directly. pico-pedal is the closest structural model: no LEDs, no BLE, no I2C, minimal firmware surface.

The recommended approach is to build pico-retro in two focused phases. Phase 1 establishes the firmware skeleton with all identity constants locked in (DEVTYPE, config magic, VID/PID, XInput subtype) and a verified wired play loop covering all 13 digital buttons plus analog trigger support. Phase 2 builds the RetroApp configurator screen and integrates it into the build pipeline. BLE wireless, LED strip support, and rumble are explicitly deferred to v2+ — including them in v1 would double implementation cost with no community validation that they are needed for this form factor.

The primary risks are identity-collision bugs that appear early and silently: using an existing config-mode PID, XInput subtype, or config struct magic from another OCC variant, or forgetting to register the new DEVTYPE and subtype in the configurator's routing tables. Every one of these is a Phase 1 task with a low fix cost — the danger is discovering them in Phase 2 after the configurator screen is already built. The secondary risks are all well-known Tkinter pitfalls that the OCC codebase has already solved; RetroApp must follow the established patterns from day one rather than discovering them through bugs.

---

## Key Findings

### Stack

The stack is fully determined by the existing OCC platform. There are no technology decisions to make — only correct application of the established patterns.

**Core technologies:**
- Pico SDK 2.2.0 + TinyUSB 0.18.0 (bundled): firmware build system, USB stack, and XInput vendor-class driver — versions are locked together; do not use standalone TinyUSB
- CMake 3.13+ / ARM GCC: required by Pico SDK; each variant is a standalone CMake project
- C11 firmware language: all existing variants use C11 in practice regardless of C++17 standard set in CMake
- Python 3.11 + Tkinter: configurator GUI — single-root-window Frame architecture; no other GUI framework is acceptable
- PyInstaller 6.x: Windows EXE packaging; spec files must be deleted before each run
- pyserial 3.5 + Pillow 9.x: serial communication and image loading for the configurator

**Critical version note:** Pico SDK 2.2.0 ships TinyUSB 0.18.0, not 0.20.0 (standalone). Do not install standalone TinyUSB alongside the SDK.

**VID/PID assignment for pico-retro:**
- XInput play mode: VID 0x045E / PID 0x028E (shared by all OCC variants — required for XInput enumeration)
- Config mode (CDC): VID 0x2E8A / PID 0xF011 (next sequential after pedal's 0xF010; PITFALLS.md noted 0xF00F as next after drums — STACK.md assigns 0xF011 accounting for pedal; use 0xF011)
- DEVTYPE string: `"retro_gamepad"`
- XInput subtype: `0x01` (standard gamepad) — but see Architecture pitfall below about subtype collision risk

### Features

pico-retro has a well-scoped feature set. All table-stakes features are low-complexity ports of existing patterns. Two features require new design decisions: analog trigger handling and XInput subtype selection.

**Must have (table stakes — all LOW complexity):**
- 13-button digital input with configurable GPIO pin assignment (`pin_buttons[BTN_IDX_COUNT]`, -1=disabled)
- XInput gamepad subtype output (0x01, standard gamepad) via shared `xinput_driver.c`
- Dual-mode USB: XInput play mode + CDC config mode via watchdog scratch register
- Config serial protocol: PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, REBOOT, BOOTSEL, SCAN
- DEVTYPE `"retro_gamepad"` as first line of GET_CONFIG response
- Config mode PID 0xF011 (unique, distinguishable from guitar/drums/pedal)
- Config struct `retro_config_t` with magic `0x52455452` ("RETR"), version 1, CRC32
- Configurable debounce, custom device name, flash-backed config
- Magic vibration sequence → config mode entry (verbatim copy, no changes)

**Should have (differentiators — MEDIUM complexity):**
- Analog/digital mode for LT/RT triggers: `uint8_t lt_mode / rt_mode`, configurable per trigger; ADC on GP26-GP28; digital mode = 0/255, analog mode = ADC 0-4095 remapped to 0-255
- Analog trigger calibration: `lt_min/lt_max/rt_min/rt_max` stored in config struct; same `apply_sensitivity()` pattern as guitar whammy
- MONITOR_ADC streaming: live ADC readout for trigger calibration in RetroApp (proven in pedal_config_serial.c)
- Pico W build target with `#ifdef PICO_W` guards and BLE stubs (wired-only v1, wireless-ready architecture)

**Defer (v2+):**
- BLE wireless implementation (full BTstack HID peripheral path — doubles firmware complexity)
- APA102 LED strip support (triples config struct; no v1 value for retro form factor)
- Rumble output (requires GPIO + PWM subsystem beyond magic-sequence path)
- Analog thumbsticks (out of scope; separate `pico-gamepad` variant if needed)

**Key design decision — trigger handling:** XInput report uses dedicated `uint8_t left_trigger / right_trigger` fields (0-255), not the stick axes used by guitar whammy/tilt. Triggers are simpler to map: digital = 0 or 255, analog = ADC / 16 after `apply_sensitivity()`.

### Architecture

pico-retro is a sibling directory to all existing variants under `Source Code/`. pico-pedal is the direct template: copy its CMakeLists.txt, usb_descriptors, tusb_config.h, and xinput_driver.c verbatim, then write new `retro_config.{c,h}` and `retro_config_serial.{c,h}`. The configurator extension is a new `RetroApp` class in `configurator.py` that follows the `PedalApp` structural model.

**Major components:**
1. `pico-retro/src/main.c` — boot decision (watchdog scratch), XInput play loop at 1000Hz, config mode dispatch; copy pico-pedal pattern unchanged
2. `pico-retro/src/retro_config.{c,h}` — `retro_config_t` struct (magic "RETR", version 1), flash load/save/defaults/CRC; copy pedal_config.c pattern
3. `pico-retro/src/retro_config_serial.{c,h}` — CDC command loop (PING, GET_CONFIG, SET, SAVE, DEFAULTS, REBOOT, BOOTSEL, SCAN, MONITOR_ADC); copy pedal_config_serial.c pattern
4. `pico-retro/src/usb_descriptors.{c,h}` — VID/PID 0xF011 config mode, XInput subtype, report struct; copy pedal, change PID and subtype
5. Configurator `RetroApp` class — `tk.Frame` subclass; pin assignment UI, analog trigger calibration, MONITOR_ADC live view, detect scan; follow PedalApp model
6. Configurator routing entries — `DEVICE_SCREEN_CLASSES["retro_gamepad"] = RetroApp`, `DEVICE_TYPE_UF2_HINTS["retro_gamepad"] = "retro"`, `OCC_SUBTYPES.add(subtype)`, `XINPUT_SUBTYPE_TO_DEVTYPE[subtype] = "retro_gamepad"`
7. `build_all_firmware.bat` step 7 — cmake+ninja build, copy UF2 and .uf2.date to configurator folder

**Key pattern — DEVTYPE routing:** Firmware emits `DEVTYPE:retro_gamepad` as the first line of GET_CONFIG. Configurator reads this string and looks it up in `DEVICE_SCREEN_CLASSES`. The string in firmware and the dict key in configurator must be identical. Verify this before any integration testing.

**Open question on XInput subtype:** STACK.md recommends subtype 0x01 (standard gamepad). ARCHITECTURE.md flags that 0x01 is very common and could produce false positives (non-OCC standard gamepads triggering the controller card). PITFALLS.md recommends 0x03 (ArcadeStick) or 0x04 (FlightStick) as safer choices. The dongle uses 0x0B (GuitarBass) for exactly this reason. **Decision needed before Phase 1 firmware write:** choose a subtype that is uncommon enough to avoid false positives. Recommendation: use 0x03 (ArcadeStick) — not currently claimed by any OCC variant and passes analog axes cleanly.

### Risk Landscape

All 12 identified pitfalls are known failure modes from the existing OCC codebase — none are theoretical. They fall into two categories: Phase 1 identity bugs (must fix before any testing) and Phase 2 Tkinter bugs (follow established patterns from the start).

**Top 5 pitfalls with prevention:**

1. **Missing or wrong DEVTYPE** — Define `DEVICE_TYPE "retro_gamepad"` in `retro_config.h` and add it to `DEVICE_SCREEN_CLASSES` before writing any config serial code. Wrong DEVTYPE causes the configurator to silently route to the wrong screen or show an error dialog.

2. **Config struct magic/version collision** — Use unique magic `0x52455452` ("RETR") and start at `CONFIG_VERSION 1`. Bump version on every struct field change during development. Sharing magic with guitar ("GUIT") causes corrupt config loads on any Pico previously running guitar firmware.

3. **XInput subtype not in OCC_SUBTYPES + XINPUT_SUBTYPE_TO_DEVTYPE** — Add the retro subtype to both dict entries atomically. Missing `OCC_SUBTYPES` = device invisible in main menu. Missing `XINPUT_SUBTYPE_TO_DEVTYPE` = EasyConfig cannot route firmware tile for the device.

4. **Config mode PID collision** — Use 0xF011. Do not copy `usb_descriptors.h` from guitar and leave `CONFIG_MODE_PID = 0xF00D`. The configurator identifies device type by PID before serial connection.

5. **Serial poll race condition (configurator)** — `RetroApp` 1s poll must check `_backup_in_progress` flag before opening serial port. MONITOR_ADC streaming must be guarded with `_monitor_active` flag. This pattern already exists in MainMenu; replicate it in RetroApp from day one.

**Additional Tkinter pitfalls to implement correctly from the start (Phase 2):**
- Combo box `.current()` does not fire `<<ComboboxSelected>>` — manually sync backing `IntVar` after every `combo.current()` call in `_load_config()`
- Never rebuild UI cards on every poll — use `_last_state` tuple comparison; only rebuild on actual change
- `bind_all("<MouseWheel>", ...)` in `show()`, `unbind_all` in `hide()` — never in `__init__`
- `root.title()` and `root.config(menu=...)` in `show()` only — never in `__init__`
- SCAN/STOP guard: track `self.scanning` boolean; only send `STOP` if `was_active = self.scanning` is True

---

## Implications for Roadmap

Based on combined research, a two-phase structure is recommended. Phase 1 closes all identity decisions and produces a working wired firmware. Phase 2 builds the configurator screen. These phases are sequential by dependency: the DEVTYPE string and subtype chosen in Phase 1 are constants that Phase 2 configurator code must match exactly.

### Phase 1: Firmware Foundation

**Rationale:** All 12 pitfalls that originate in Phase 1 (identity constants, config struct, USB descriptors, build pipeline) must be resolved before any configurator work begins. A configurator built against wrong DEVTYPE or PID constants will need to be partially rewritten.

**Delivers:** A flashable pico-retro.uf2 that enumerates as an XInput standard gamepad on Windows, reads 13 digital buttons at 1000Hz, supports analog LT/RT triggers with calibration, and enters CDC config mode via the magic vibration sequence. Pico W build target compiles cleanly with BLE stubs.

**Addresses (from FEATURES.md):** All 13 table-stakes features; analog trigger support + calibration; MONITOR_ADC streaming; Pico W `#ifdef PICO_W` guards.

**Must lock in before writing firmware code:**
- XInput subtype value (recommend 0x03, confirm no conflict)
- Config mode PID (0xF011 per STACK.md)
- DEVTYPE string (`"retro_gamepad"`)
- Config magic (`0x52455452`)

**Avoids (from PITFALLS.md):** Pitfalls 1 (DEVTYPE), 2 (config magic/version), 3 (subtype collision), 4 (PID collision), 11 (trigger range guard), 12 (build script omission).

**Research flag:** No additional research needed. All patterns are proven in pico-pedal and guitar-wired. Template files are identified.

### Phase 2: Configurator Screen

**Rationale:** Depends on Phase 1 firmware being stable and identity constants finalized. RetroApp must match the DEVTYPE string and config key names exactly.

**Delivers:** A `RetroApp` screen class in `configurator.py` with: GPIO pin assignment for all 13 buttons, analog/digital trigger mode selection, trigger calibration UI with MONITOR_ADC live view, device name editor, detect/scan support, config save/load/defaults, and integration into the backup+restore flow.

**Uses (from STACK.md):** Python 3.11, Tkinter tk.Frame architecture, pyserial for serial communication, existing PicoSerial class (no changes needed).

**Implements (from ARCHITECTURE.md):** RetroApp class, DEVICE_SCREEN_CLASSES/DEVICE_TYPE_UF2_HINTS/OCC_SUBTYPES/XINPUT_SUBTYPE_TO_DEVTYPE routing entries, build_all_firmware.bat step 7.

**Avoids (from PITFALLS.md):** Pitfalls 5 (poll race), 6 (STOP guard), 7 (combo IntVar sync), 8 (UI rebuild on poll), 9 (bind_all in __init__), 10 (title/menu in __init__).

**Research flag:** No additional research needed. PedalApp is the direct structural model. All Tkinter pitfalls have known solutions already in the codebase.

### Phase 3: Wireless + Extras (Future)

**Rationale:** Deferred until pico-retro has community validation. BLE requires substantial additional firmware surface and doubles test burden.

**Delivers:** BLE HID peripheral on Pico W (copy guitar-wireless bt_hid patterns, adapt for gamepad report format); optionally APA102 LEDs; optionally rumble output.

**Research flag:** Needs research-phase when planned. BLE on Pico W has documented gotchas (can_send_now callback pattern, Windows BLE connection parameter constraints, compile_gatt.py for GATT profile). Do not hand-write GATT bytes.

### Phase Ordering Rationale

- Phase 1 before Phase 2: configurator routing tables reference DEVTYPE and subtype constants that must be stable; building RetroApp against provisional values creates rework
- All Phase 1 identity constants (DEVTYPE, magic, PID, subtype) must be committed to `CLAUDE.md` VID/PID table before Phase 2 begins
- Phase 3 is independent once Phase 1 firmware is stable; it does not block any Phase 2 work

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All technologies are locked by existing OCC platform. No new technology decisions. Direct source inspection of all variants. |
| Features | HIGH | Feature set derived from existing codebase + PROJECT.md spec. XInput report structure verified in source. Trigger handling design is straightforward. |
| Architecture | HIGH | All patterns have direct implementations in pico-pedal and guitar-wired. Component boundaries are identical to existing variants. |
| Pitfalls | HIGH | All 12 pitfalls are documented real bugs from OCC development history, not theoretical risks. Solutions are proven in the codebase. |

**Overall confidence:** HIGH

### Gaps to Address

- **XInput subtype selection:** STACK.md recommends 0x01 (standard gamepad); ARCHITECTURE.md and PITFALLS.md both warn about false-positive collision risk with non-OCC gamepads. Recommendation is 0x03 (ArcadeStick), but this is a judgment call that must be made explicitly before Phase 1 firmware is written and confirmed against the full `XINPUT_SUBTYPE_TO_DEVTYPE` table in configurator.py. Check that 0x03 is not already used.

- **Config mode PID discrepancy:** FEATURES.md proposes 0xF00F (next after drums 0xF00E); STACK.md assigns 0xF011 (next after pedal 0xF010); ARCHITECTURE.md says 0xF00F. All three differ. Check the current `find_config_port()` scan list in configurator.py to confirm which PIDs are already registered, then pick the correct next-sequential value and use it consistently across all files.

- **GIF tile asset:** `build_all_firmware.bat` auto-discovers GIFs by matching UF2 base name. A `Retro_Controller.gif` must exist in the configurator folder at EXE build time. This is a build artifact dependency — plan for it in Phase 2 (can be a placeholder static image converted to GIF if no animation is ready).

---

## Sources

### Primary (HIGH confidence)
- OCC codebase direct inspection: `pico-guitar-controller-wired/src/`, `pico-pedal/src/`, `pico-drums-wired/src/`, `pico-guitar-controller-wireless/src/` — all patterns
- `configurator/configurator.py` lines 870-15868 — routing tables, screen architecture, serial protocol
- `CLAUDE.md` — authoritative architectural rules and VID/PID reference table
- `PROJECT.md` — authoritative pico-retro scope and out-of-scope definitions
- `build_all_firmware.bat`, `build_exe.bat` — build pipeline structure

### Secondary (HIGH confidence — official external sources)
- Pico SDK 2.2.0 release notes (GitHub) — SDK version confirmation
- Microsoft Learn: XInput subtypes reference — subtype 0x01 = GAMEPAD, 0x05 suppresses axes
- PyInstaller changelog 6.x — current series confirmed
- TinyUSB issue #2756 (pico-sdk) — confirms SDK 2.2.0 ships TinyUSB 0.18.0

---
*Research completed: 2026-03-19*
*Ready for roadmap: yes*
