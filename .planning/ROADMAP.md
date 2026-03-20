# Roadmap: OCC pico-retro Variant

## Overview

pico-retro is a new OCC platform variant — a retro-style gamepad firmware for Raspberry Pi Pico/Pico W. The work divides naturally into two sequential phases. Phase 1 produces a flashable firmware that enumerates as a standard XInput gamepad, handles all 13 digital buttons (GPIO configurable) plus analog/digital LT/RT triggers with calibration, and enters CDC serial config mode. Phase 2 builds the RetroApp advanced configurator screen (following the drums configurator pattern) that connects to the firmware, exposes all GPIO pin mappings and trigger calibration settings with live monitoring, and integrates with the existing firmware update pipeline. The phases are strictly sequential: identity constants locked in Phase 1 (DEVTYPE string, config-mode PID, XInput subtype) are referenced verbatim in Phase 2 configurator routing tables.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Firmware Foundation** - Working pico-retro firmware with XInput gamepad output, 13 digital buttons (GPIO configurable), analog/digital LT/RT triggers with calibration, CDC config mode, and Pico W build target
- [ ] **Phase 2: Configurator Integration** - RetroApp advanced configurator screen with GPIO button mapping, trigger mode selection and calibration, live analog trigger monitoring, and firmware update pipeline integration

## Phase Details

### Phase 1: Firmware Foundation
**Goal**: A flashable pico-retro firmware exists that Windows recognizes as a gamepad, reads all digital button inputs, supports analog/digital trigger configuration, and supports serial configuration
**Depends on**: Nothing (first phase)
**Requirements**: FW-01, FW-02, FW-03, FW-04, FW-05, FW-06, FW-07, FW-08, FW-09, FW-10, USB-02
**Success Criteria** (what must be TRUE):
  1. Single .uf2 file works on both Pico and Pico W; at boot detects USB connection — if USB detected, enumerates as XInput gamepad in Windows Device Manager; if no USB detected, boots into wireless standby (ready for BLE implementation later); architecture supports adding wireless mode without major refactoring
  2. All 13 digital buttons register correct XInput button outputs when pressed, with fully configurable GPIO pin assignments (digital inputs only)
  3. LT and RT triggers work in both analog mode (0-255 ADC-scaled output) and digital mode (0 or 255) with per-trigger calibration min/max and EMA smoothing stored in flash
  4. Magic vibration sequence from the configurator causes the device to reboot into CDC serial config mode, where PING, GET_CONFIG, SET, SAVE, DEFAULTS, and REBOOT commands all respond correctly
  5. Config survives power cycle: settings written via SET/SAVE are read back correctly after unplug/replug
**Plans:** 4/5 plans executed
Plans:
- [ ] 01-01-PLAN.md — Project scaffold, config struct, flash storage
- [ ] 01-02-PLAN.md — USB descriptors (XInput subtype 0x01 + CDC PID 0xF00F)
- [ ] 01-03-PLAN.md — Serial config protocol (PING, GET_CONFIG, SET, SAVE, DEFAULTS, REBOOT)
- [ ] 01-04-PLAN.md — Main.c boot flow, button/trigger input, XInput reports
- [ ] 01-05-PLAN.md — Configurator.py pico-retro device registration

### Phase 2: Configurator Integration
**Goal**: RetroApp advanced configurator screen exposes all GPIO pin mappings, trigger calibration with live monitoring, and integrates with existing firmware update pipeline
**Depends on**: Phase 1
**Requirements**: CFG-02, CFG-03, CFG-04, CFG-05, CFG-06, CFG-07, CFG-08, CFG-09, CFG-10, CFG-11, USB-01 (11 total)
**Success Criteria** (what must be TRUE):
  1. Main menu detects pico-retro device type and displays it to user; user clicks "Advanced Configuration" button, magic vibration sequence enters config mode, RetroApp screen opens
  2. User can DETECT each of the 13 digital buttons by physically pressing them, and the configurator records the correct GPIO pin
  3. User can DETECT LT and RT triggers, choose analog or digital mode for each, and calibrate analog triggers with live output bar monitoring (0-255) while adjusting min/max, smoothing alpha, and invert sliders
  4. Firmware update feature in configurator automatically backs up current config, flashes Retro_Controller.uf2, waits for reboot, and restores all settings (using existing pipeline, pico-retro added to supported device list)
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Firmware Foundation | 4/5 | In Progress|  |
| 2. Configurator Integration | 0/TBD | Not started | - |
