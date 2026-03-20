# Requirements: OCC pico-retro Variant

**Defined:** 2026-03-19
**Core Value:** Community-friendly retro gamepad firmware with flexible GPIO configuration and consistent configurator experience

## v1 Requirements

### Firmware - pico-retro

- [x] **FW-01**: Pico/Pico W target support — Single `.uf2` file builds for both Pico and Pico W; at boot detects USB connection to determine wired vs wireless mode (wireless mode not implemented v1, but architecture supports it)
- [x] **FW-02**: Dual-mode USB boot — Normal start = XInput gamepad mode; watchdog scratch trigger = CDC serial config mode
- [x] **FW-03**: 13-button input set — DPad (4-way), A/B/X/Y buttons, Start, Select, Guide, LB, RB
- [x] **FW-04**: Analog triggers (LT/RT) — Configurable per-trigger as analog (0-255) or digital (on/off)
- [x] **FW-05**: GPIO pin assignment — All 13 buttons + 2 triggers have fully configurable GPIO pins (set at build time via config)
- [x] **FW-06**: Configuration storage — Packed `retro_config_t` struct in flash sector with magic number and CRC checksum
- [x] **FW-07**: Serial config protocol — Implement config mode serial loop supporting PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, REBOOT commands (115200 baud)
- [x] **FW-08**: USB descriptor — Standard gamepad identification (XInput subtype 0x01 XINPUT_DEVSUBTYPE_GAMEPAD) so Windows Device Manager displays as "gamepad"
- [x] **FW-09**: Analog trigger smoothing — EMA exponential moving average for analog trigger noise reduction with user-configurable alpha
- [x] **FW-10**: Trigger min/max calibration — Store per-trigger calibration points; scale raw ADC to 0-255 output range

### Configurator - RetroApp Screen

- [ ] **CFG-02**: Device naming — User can set/change device name (alphanumeric, max 20 chars, validated in configurator + firmware)
- [x] **CFG-03**: GPIO button mapping — Interactive DETECT function for each button (press button, configurator records GPIO pin)
- [x] **CFG-04**: Analog trigger detection — DETECT function for LT/RT triggers (pull/press, configurator records ADC pin)
- [ ] **CFG-05**: Analog/digital mode toggle — User selects per-trigger: "Analog" or "Digital" mode
- [x] **CFG-06**: Analog trigger monitor — Real-time monitor screen showing raw ADC and calibrated output (0-255 bar graphs) for each analog trigger
- [ ] **CFG-07**: Min/max calibration UI — Sliders to set trigger min/max values; live output bar updates as user adjusts
- [ ] **CFG-08**: Smoothing control — EMA alpha slider for trigger smoothing (0-100%)
- [ ] **CFG-09**: Invert toggle — Per-trigger invert option (reverse calibration direction)
- [ ] **CFG-10**: Config backup/restore — Automatic backup before firmware flash, config restoration via SET commands after flash
- [ ] **CFG-11**: Firmware update integration — Add pico-retro to existing firmware update pipeline (backup config, flash Retro_Controller.uf2, restore config after reboot)

### USB & Device Identity

- [ ] **USB-01**: Config mode PID — Unique USB PID for config mode (0xF00F), distinct from guitar (0xF00D) and drums (0xF00E)
- [x] **USB-02**: XInput mode VID/PID — Standard XInput (0x045E / 0x028E) recognized by Windows as gamepad controller

## v2 Requirements

### Firmware Enhancements

- **FW-EX-01**: BLE wireless on Pico W — Implement BTstack HID peripheral mode for wireless gamepad on Pico W
- **FW-EX-02**: LED strip support — Optional WS2812B/APA102 LED animation with per-button mapping
- **FW-EX-03**: Joystick inputs — Optional left/right analog sticks (X/Y axes)
- **FW-EX-04**: Rumble support — Haptic feedback via dual rumble motors on triggers

### Configurator Enhancements

- **CFG-EX-01**: LED configuration screen — Map LEDs to buttons/inputs with effect selection
- **CFG-EX-02**: Wireless pairing UI — BLE device discovery and pairing workflow
- **CFG-EX-03**: Joystick calibration — Joystick deadzone, sensitivity, and invert settings

## Out of Scope

| Feature | Reason |
|---------|--------|
| LED support (v1) | Keeps firmware simple for initial community contribution |
| Joystick/sticks (v1) | DPad is table stakes; sticks add complexity — defer to v2 |
| BLE wireless (v1) | Architecture scaffolding in place, implementation deferred to Phase 3 |
| Rumble support (v1) | Not core to gamepad function; nice-to-have for v2 |
| Mobile configurator | Windows desktop only; mobile is future consideration |
| Modifier/chord mappings | Not standard gamepad feature; community request only |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FW-01 | Phase 1 | Complete |
| FW-02 | Phase 1 | Complete |
| FW-03 | Phase 1 | Complete |
| FW-04 | Phase 1 | Complete |
| FW-05 | Phase 1 | Complete |
| FW-06 | Phase 1 | Complete |
| FW-07 | Phase 1 | Complete |
| FW-08 | Phase 1 | Complete |
| FW-09 | Phase 1 | Complete |
| FW-10 | Phase 1 | Complete |
| CFG-02 | Phase 2 | Pending |
| CFG-03 | Phase 2 | Complete |
| CFG-04 | Phase 2 | Complete |
| CFG-05 | Phase 2 | Pending |
| CFG-06 | Phase 2 | Complete |
| CFG-07 | Phase 2 | Pending |
| CFG-08 | Phase 2 | Pending |
| CFG-09 | Phase 2 | Pending |
| CFG-10 | Phase 2 | Pending |
| CFG-11 | Phase 2 | Pending |
| USB-01 | Phase 2 | Pending |
| USB-02 | Phase 1 | Complete |

**Coverage:**
- v1 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0 ✓

---

*Requirements defined: 2026-03-19*
*Last updated: 2026-03-19 after roadmap creation — traceability confirmed
