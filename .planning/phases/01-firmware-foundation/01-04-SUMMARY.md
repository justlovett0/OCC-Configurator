---
phase: 01-firmware-foundation
plan: 04
subsystem: firmware
tags: [c, pico-sdk, tinyusb, xinput, retro-controller, debounce, ema, adc]

# Dependency graph
requires:
  - phase: 01-01
    provides: retro_config_t struct, config_load API, retro_config.h
  - phase: 01-02
    provides: usb_descriptors.h XInput report struct, button masks, WATCHDOG_CONFIG_MAGIC, magic sequence constants
  - phase: 01-03
    provides: retro_config_serial.h config_serial_loop() entry point
  - phase: xinput_driver
    provides: xinput_send_report, xinput_ready, xinput_magic_detected

provides:
  - Complete pico-retro firmware entry point (main.c) with full XInput gamepad runtime
  - Boot flow: watchdog config check → config_load → tusb_init → USB detection → XInput loop or config mode
  - 13 digital button reading with per-button debounce and XInput mask lookup table
  - Analog LT/RT trigger reading with ADC, EMA smoothing, calibration, invert
  - Digital LT/RT trigger reading outputting 0/255 axis values
  - Magic vibration sequence detection → watchdog reboot into config mode
  - Pico W CYW43 init and reserved GPIO guard (23/24/25/29) under PICO_W_BT ifdef
  - Wireless standby loop scaffold for Phase 3+ BLE

affects:
  - Phase 3 BLE: standby loop block at bottom of main.c is where BLE init/loop code goes
  - Phase 2 configurator: RetroApp must send magic vibration sequence to enter config mode

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Three-path boot flow: config mode / XInput gamepad / wireless standby"
    - "Watchdog scratch[0] checked and cleared BEFORE tusb_init to prevent descriptor flipping"
    - "Debounce: raw edge detection + stable state with configurable threshold in microseconds"
    - "EMA smoothing: fixed-point (Q8) exponential moving average; alpha 0 stored = 255 internal (fastest)"
    - "Active-low button reading: !gpio_get() + gpio_pull_up() per button GPIO"
    - "Digital trigger outputs 0 or 255 as axis value, not button press"
    - "GPIO reserved pin guard for Pico W: pins 23/24/25/29 skipped under PICO_W_BT"

key-files:
  created:
    - "Source Code/pico-retro/src/main.c"
  modified: []

key-decisions:
  - "g_config_mode set BEFORE tusb_init() — required so TinyUSB selects correct descriptor set at init time"
  - "Digital trigger outputs 0/255 as axis byte, not boolean button press — per CONTEXT.md locked decision"
  - "Standby loop uses tight_loop_contents() only — no BLE code yet, reserved for Phase 3"
  - "xinput_ready() checked before xinput_send_report() — prevents send attempts when USB not ready"
  - "EMA alpha 0 stored = 255 internal — matches guitar controller convention for fastest response"

patterns-established:
  - "Pattern: Button mask lookup table indexed by button_index_t enum for clean O(1) button → XInput bit mapping"
  - "Pattern: apply_sensitivity() + ema_update() pipeline for analog trigger processing"
  - "Pattern: request_config_mode_reboot() sets watchdog scratch then calls watchdog_reboot + infinite loop"

requirements-completed: [FW-03, FW-04, FW-09, FW-10]

# Metrics
duration: 5min
completed: 2026-03-20
---

# Phase 1 Plan 04: main.c Firmware Entry Point Summary

**XInput gamepad runtime with 3-path boot (config/USB/standby), 13 debounced digital buttons, analog/digital LT/RT triggers with EMA smoothing and calibration, and magic vibration config-mode entry**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-20T05:05:00Z
- **Completed:** 2026-03-20T05:10:00Z
- **Tasks:** 1 of 1
- **Files modified:** 1

## Accomplishments

- Created `main.c` tying together all four previously built files (retro_config.h, usb_descriptors.h, retro_config_serial.h, xinput_driver.h) into functional firmware
- Boot flow: watchdog scratch check before tusb_init → config load → optional cyw43 init → tusb_init → 1s USB mount wait → XInput gamepad loop or config serial loop or wireless standby
- 13 digital button reading with per-button debounce via configurable debounce_ms, mapped to XInput masks via static lookup table
- LT/RT triggers: analog path uses ADC + apply_sensitivity() + EMA + invert, outputting 0-255; digital path uses debounce outputting 0 or 255
- Magic vibration sequence detection via xinput_magic_detected() triggers watchdog-scratch reboot into config mode
- Pico W CYW43 guard with is_picow_reserved() keeping GPIO 23/24/25/29 clean under PICO_W_BT ifdef

## Task Commits

1. **Task 1: Create main.c boot flow with config mode check, USB detection, and standby** - `5b3113e` (feat)

## Files Created/Modified

- `Source Code/pico-retro/src/main.c` - Complete firmware entry point: boot flow, input reading, XInput report loop, config mode entry

## Decisions Made

- `g_config_mode` is set before `tusb_init()` (Pitfall 2 from research) — this is the critical ordering constraint that determines which descriptor set TinyUSB loads
- Digital trigger outputs 0 or 255 as an axis byte (left_trigger/right_trigger fields), not as a button press — per CONTEXT.md locked decision
- Added `xinput_ready()` guard before `xinput_send_report()` — matches pattern from guitar wireless main.c, prevents attempting sends when USB not yet stable
- EMA alpha 0 stored maps to 255 internal — fastest response, matches existing guitar controller convention

## Deviations from Plan

None - plan executed exactly as written.

The plan specified `xinput_send_report(&report, sizeof(report))` but the actual function signature (confirmed from xinput_driver.h) is `xinput_send_report(const xinput_report_t *report)` without a length parameter. Used the correct signature and added `xinput_ready()` guard inline — this is not a deviation from intent, just correcting the plan's approximate interface spec against the real implementation.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All four firmware files for pico-retro are now complete: retro_config.{h,c}, usb_descriptors.{h,c}, retro_config_serial.{h,c}, xinput_driver.{h,c}, main.c
- Phase 1 plan 05 (CMakeLists.txt) can now wire all these files together into a buildable target
- Phase 2 (configurator RetroApp): config mode entry via magic vibration is implemented and ready; GET_CONFIG DEVTYPE:pico_retro ready for screen routing
- Phase 3 (BLE): standby loop in main.c is the exact placeholder for BLE init/loop code

---
*Phase: 01-firmware-foundation*
*Completed: 2026-03-20*
