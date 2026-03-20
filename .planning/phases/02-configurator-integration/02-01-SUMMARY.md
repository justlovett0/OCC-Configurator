---
phase: 02-configurator-integration
plan: 01
subsystem: firmware
tags: [pico-retro, serial-protocol, gpio, adc, scan, monitor]

# Dependency graph
requires:
  - phase: 01-firmware-foundation
    provides: retro_config_serial.c with config_serial_loop dispatch, retro_config_t struct
provides:
  - SCAN/STOP/PIN: serial protocol for GPIO button detection in pico-retro firmware
  - MONITOR_ADC/MVAL:/STOP serial protocol for live ADC streaming in pico-retro firmware
affects:
  - 02-configurator-integration (RetroApp DETECT button and analog monitor UI)

# Tech tracking
tech-stack:
  added: [hardware/adc.h (Pico SDK ADC peripheral)]
  patterns: [run_scan/run_monitor_adc static helper pattern matching pico-pedal implementation]

key-files:
  created: []
  modified:
    - Source Code/pico-retro/src/retro_config_serial.c

key-decisions:
  - "run_scan() starts scan from GPIO 0 (not 2 like pedal) because retro has no PIO-USB on GP0/GP1"
  - "Pins 23/24/25 skipped in scan loop — reserved RP2040 internal pins"
  - "MONITOR_INTERVAL_MS = 50ms (~20Hz) matches pedal implementation exactly"

patterns-established:
  - "run_scan pattern: init all valid GPIO as input pull-up, snapshot prev state, loop reporting transitions until STOP"
  - "run_monitor_adc pattern: validate ADC pin range 26-28, stream MVAL:<val> at interval, stop on STOP command"

requirements-completed: [CFG-03, CFG-04, CFG-06]

# Metrics
duration: 2min
completed: 2026-03-20
---

# Phase 2 Plan 01: SCAN and MONITOR_ADC Serial Commands Summary

**SCAN (GPIO button detect) and MONITOR_ADC (live ADC streaming) serial commands added to retro_config_serial.c, following pico-pedal implementation with retro-specific GPIO range (0-28 minus reserved pins)**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-20T14:41:07Z
- **Completed:** 2026-03-20T14:43:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Added `run_scan()` — polls GPIO 0-28 (skipping reserved 23/24/25), reports `PIN:<n>` on button press transitions, exits on `STOP`
- Added `run_monitor_adc()` — validates ADC pin (26-28), streams `MVAL:<val>` at ~20Hz, exits on `STOP`
- Dispatched both commands from `config_serial_loop()` after the BOOTSEL handler
- Added `#include "hardware/adc.h"` and `#define MONITOR_INTERVAL_MS 50`
- Updated file header comment to document SCAN, STOP, and MONITOR_ADC commands

## Task Commits

Each task was committed atomically:

1. **Task 1: Add run_scan() and run_monitor_adc() to retro_config_serial.c** - `adfa811` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified
- `Source Code/pico-retro/src/retro_config_serial.c` - Added SCAN/MONITOR_ADC functions and dispatch entries

## Decisions Made
- `run_scan()` scans from GPIO 0 (not 2 like pico-pedal) because retro has no PIO-USB occupying GP0/GP1
- Pins 23, 24, 25 skipped — reserved for RP2040 internal use (SMPS/LED/USB sense)
- MONITOR_INTERVAL_MS = 50ms matches pedal exactly, giving ~20Hz update rate

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- pico-retro firmware now supports all three serial commands needed by the configurator: SCAN (DETECT button), MONITOR_ADC (analog trigger live monitor)
- Plan 02-02 can proceed to integrate DETECT button and analog monitor UI in the configurator RetroApp screen

## Self-Check: PASSED

- FOUND: Source Code/pico-retro/src/retro_config_serial.c
- FOUND: .planning/phases/02-configurator-integration/02-01-SUMMARY.md
- FOUND: commit adfa811

---
*Phase: 02-configurator-integration*
*Completed: 2026-03-20*
