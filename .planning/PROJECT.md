# OCC: Pico Guitar Controller (+ Community Variants)

## What This Is

XInput gamepad firmware for Raspberry Pi Pico/Pico W with a Python/Tkinter configurator GUI for Windows. Supports multiple controller types — guitar (6/7 strings, wireless), drums, dongle (4-channel), and now retro-style gamepad. Each firmware variant is a separate CMake project producing its own `.uf2` file. The configurator auto-detects firmware type and routes to the correct configuration screen.

## Core Value

Community-friendly controller firmware platform with flexible GPIO pin configuration, consistent dual-mode USB architecture (XInput + serial config), and unified configurator experience across all controller types.

## Requirements

### Validated

- ✓ Guitar controller (wired) — Phase 0
- ✓ Guitar controller (wireless/BLE) — Phase 0
- ✓ Drums controller (wired) — Phase 0
- ✓ Pico dongle (4-channel XInput relay) — Phase 0
- ✓ Configurator GUI (dark theme, device detection, pin mapping, LED effects, firmware flashing) — Phase 0
- ✓ Serial protocol (115200 baud config mode, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, SCAN, etc.) — Phase 0
- ✓ LED support (APA102 strips, per-input mapping, brightness control, effects) — Phase 0

### Active

- [ ] **Retro gamepad firmware** — Pico/Pico W, 13-button input set (DPad, ABXY, Start, Select, Guide, LB, RB, LT, RT), configurable GPIO pins, analog/digital trigger support
- [ ] **Configurator RetroApp screen** — Device naming, GPIO detection, analog trigger monitoring/calibration, min/max/smoothing/invert settings
- [ ] **Firmware variant detection** — Extend existing DEVTYPE logic to recognize pico-retro variant and route to RetroApp
- [ ] **Wireless path readiness** — pico-retro firmware structured to support BLE HID on Pico W (implementation deferred)

### Out of Scope

- LED support for pico-retro (keep firmware simple for community contributions)
- BLE wireless implementation for pico-retro (architecture ready, implementation Phase 3+)
- Additional controller types beyond retro (future versions)
- Mobile configurator (Windows desktop only)

## Context

OCC started as a guitar controller for XInput gaming on Windows. It has evolved to support multiple controller types while maintaining consistent architecture:

- **Firmware architecture:** Dual-mode USB (normal boot = XInput gamepad, watchdog scratch trigger = CDC serial config mode). Config stored in flash sector with CRC checksum. Fully configurable GPIO pins and behavior.
- **Configurator architecture:** Tkinter-based, all screens are Frame instances in one root window. Device detection via GET_CONFIG response, routing to controller-specific App screens. Background threads handle backup, firmware flashing, config restoration.
- **Community readiness:** This project is preparing for community contributions — GPIO flexibility, clear build process, consistent patterns across variants.

## Constraints

- **Tech stack:** C + Pico SDK + TinyUSB (firmware), Python 3.11+ + Tkinter (configurator)
- **Windows-only:** Configurator runs on Windows only (PyInstaller exe). Firmware runs on Pico/Pico W.
- **XInput mode:** All firmware must expose standard XInput (VID 0x045E, PID 0x028E)
- **Config mode VIDs:** Unique per controller type (guitar 0x2E8A/0xF00D, drums 0x2E8A/0xF00E, etc.)
- **Build format:** Each firmware variant is a separate CMake project in its own directory (guitar-wired/, pico-dongle/, pico-retro/, etc.). Configurator bundles all `.uf2` files and detects them at runtime.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Retro gamepad as distinct firmware variant | Simpler input set than guitar, good for community first contribution | ✓ Good — clear scope, reuses existing patterns |
| No LED support in pico-retro v1 | Keeps firmware simple for new contributors, LEDs add complexity | ✓ Good — lower barrier to entry |
| pico-retro supports both Pico and Pico W | Future-proofs for wireless, maintains consistency | — Pending |
| Wireless path ready (not implemented v1) | Establishes architecture for BLE without full implementation | — Pending |
| GPIO configuration like guitar/drums | Flexibility for different button layouts in community | ✓ Good — proven pattern |
| Analog/digital trigger configurability | Matches guitar whammy flexibility, supports different sensor types | ✓ Good — established approach |

---

*Last updated: 2026-03-19 after initialization*
