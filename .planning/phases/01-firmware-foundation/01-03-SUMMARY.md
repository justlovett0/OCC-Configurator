---
phase: 01-firmware-foundation
plan: 03
subsystem: firmware
tags: [c, pico-sdk, tinyusb, cdc-serial, retro-controller, config-protocol]

# Dependency graph
requires:
  - phase: 01-01
    provides: retro_config_t struct and config_load/save/set_defaults/update_checksum API

provides:
  - CDC serial config protocol for pico-retro (retro_config_serial.h, retro_config_serial.c)
  - config_serial_loop() entry point for config-mode main in main.c
  - PING/GET_CONFIG/SET/SAVE/DEFAULTS/REBOOT/BOOTSEL command handler

affects:
  - Phase 2 configurator (RetroApp screen must send PING, GET_CONFIG, SET commands using these exact key names)
  - Phase 1 plan 01-04 or 01-05 if main.c needs config_serial_loop wired in

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CDC serial line reader with character-by-character accumulation into 256-byte buffer"
    - "serial_write/serial_writeln CDC output helpers with flow control via tud_cdc_write_available"
    - "watchdog_reboot + tight_loop_contents for supervised reboot from config mode"
    - "Disconnect timeout (5s) + activity timeout (30s) before automatic reboot to play mode"

key-files:
  created:
    - "Source Code/pico-retro/src/retro_config_serial.h"
    - "Source Code/pico-retro/src/retro_config_serial.c"
  modified: []

key-decisions:
  - "Function named config_serial_loop (not config_mode_main) to match plan spec and project naming convention"
  - "device_name validation validates all chars before writing (not character-filter approach) to reject invalid names with ERR response"
  - "SCAN/STOP and LED_* commands intentionally omitted — pico-retro has no LEDs and button scan is guitar/pedal-specific"
  - "Debounce max validated as 0-255 (full uint8_t range) not 0-50 like pedal — retro uses longer debounce for noisy arcade buttons"

patterns-established:
  - "Pattern: ADC pin validation occurs at pin_lt/pin_rt SET time using current mode_lt/mode_rt values"
  - "Pattern: GET_CONFIG key names exactly match SET command key names (btn0-btn12, pin_lt, pin_rt, etc.)"
  - "Pattern: No apa102_leds.h in retro_config_serial.c per CLAUDE.md rule"

requirements-completed: [FW-05, FW-07]

# Metrics
duration: 5min
completed: 2026-03-20
---

# Phase 1 Plan 03: Serial Config Protocol Summary

**115200 baud CDC serial handler for pico-retro with PING/GET_CONFIG/SET/SAVE/DEFAULTS/REBOOT/BOOTSEL, full retro_config_t field coverage, and ADC pin + device_name validation**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-20T05:01:00Z
- **Completed:** 2026-03-20T05:03:17Z
- **Tasks:** 1 of 1
- **Files modified:** 2

## Accomplishments

- Created retro_config_serial.h declaring `void config_serial_loop(retro_config_t *config)`
- Created retro_config_serial.c with full CDC serial command handler: PING returns PONG; GET_CONFIG sends DEVTYPE:pico_retro + CFG line with all 17 config fields; SET handles btn0-btn12, pin_lt, pin_rt, mode_lt, mode_rt, lt_min, lt_max, rt_min, rt_max, lt_invert, rt_invert, lt_ema_alpha, rt_ema_alpha, debounce, device_name; SAVE persists to flash; DEFAULTS resets; REBOOT and BOOTSEL work correctly
- ADC pin validation: pin_lt/pin_rt reject non-26-28 pins when analog mode active
- device_name validation: alphanumeric + space only, max 20 chars, trailing spaces stripped, invalid chars return ERR response
- No apa102_leds.h inclusion, no SCAN/STOP, no LED commands — compliant with CLAUDE.md architecture rules

## Task Commits

1. **Task 1: Create retro_config_serial.h and retro_config_serial.c** - `30b59ec` (feat)

## Files Created/Modified

- `Source Code/pico-retro/src/retro_config_serial.h` - Header declaring config_serial_loop entry point
- `Source Code/pico-retro/src/retro_config_serial.c` - Full CDC serial command handler for config mode

## Decisions Made

- Named function `config_serial_loop` (matching plan spec) rather than `config_mode_main` (pedal convention) for clarity
- device_name validation rejects the full value if any invalid char found (vs character-filter approach in pedal) — gives the configurator a clear ERR signal to display
- debounce upper bound set to 255 (full uint8_t) rather than 50 — arcade/retro buttons may need longer debounce than guitar pedals
- SCAN/STOP intentionally absent — not a retro controller requirement; will be added in Phase 2 only if the configurator needs it

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `config_serial_loop` is ready to be called from `main.c` after watchdog-scratch config-mode detection
- GET_CONFIG DEVTYPE:pico_retro is ready for configurator routing via DEVICE_SCREEN_CLASSES in Phase 2
- All SET key names (btn0-btn12, pin_lt, pin_rt, etc.) are established — Phase 2 RetroApp must use these exact names

---
*Phase: 01-firmware-foundation*
*Completed: 2026-03-20*
