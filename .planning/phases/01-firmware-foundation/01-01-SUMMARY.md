---
phase: 01-firmware-foundation
plan: 01
subsystem: firmware
tags: [pico-sdk, tinyusb, cmake, xinput, flash-storage, c]

# Dependency graph
requires: []
provides:
  - pico-retro CMake project with dual Pico/Pico W build option (PICO_RETRO_WIRELESS)
  - retro_config_t packed struct (magic 0x52455452, version 1, 13 buttons, LT/RT triggers)
  - Flash load/save/defaults with interrupt-safe erase+program and rotating-accumulate checksum
  - xinput_driver.h/c shared from pico-pedal (magic vibration sequence detection)
  - tusb_config.h (device-mode only, CDC enabled, no USB host)
affects: [02-usb-descriptors, 03-main-firmware, 04-config-serial, 05-configurator-integration]

# Tech tracking
tech-stack:
  added: [pico-sdk, tinyusb-device, hardware_flash, hardware_sync, hardware_adc]
  patterns:
    - packed config struct with magic+version+rotating-checksum in last flash sector
    - PICO_RETRO_WIRELESS cmake option selects Pico vs Pico W target
    - OUTPUT_NAME sets UF2 filename (Retro_Controller / Retro_Controller_W)

key-files:
  created:
    - "Source Code/pico-retro/CMakeLists.txt"
    - "Source Code/pico-retro/pico_sdk_import.cmake"
    - "Source Code/pico-retro/src/tusb_config.h"
    - "Source Code/pico-retro/src/xinput_driver.h"
    - "Source Code/pico-retro/src/xinput_driver.c"
    - "Source Code/pico-retro/src/retro_config.h"
    - "Source Code/pico-retro/src/retro_config.c"
  modified: []

key-decisions:
  - "Single add_executable target; Pico W selected by -DPICO_RETRO_WIRELESS=ON cmake option at configure time"
  - "tusb_config.h is device-mode only — removed all PIO-USB and host-mode defines from pedal's version"
  - "retro_config_t uses int8_t pin fields (value -1 = disabled) matching all other OCC variants"
  - "config_set_defaults leaves device_name empty and all pins at -1 — user assigns everything via configurator"

patterns-established:
  - "Pattern: CMake wireless option — set(PICO_BOARD pico_w) gated on option before pico_sdk_init()"
  - "Pattern: Flash config — rotating-accumulate checksum, last flash sector, interrupt-safe erase+program"
  - "Pattern: input_mode_t enum — DIGITAL=0, ANALOG=1 for per-trigger mode selection"

requirements-completed: [FW-01, FW-06]

# Metrics
duration: 15min
completed: 2026-03-19
---

# Phase 1 Plan 01: Firmware Foundation Summary

**pico-retro CMake scaffold with dual Pico/Pico W build option, retro_config_t flash-backed config struct (13 buttons, analog/digital LT/RT triggers, rotating-accumulate checksum), and shared xinput_driver**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-19T00:00:00Z
- **Completed:** 2026-03-19
- **Tasks:** 2
- **Files modified:** 7 created

## Accomplishments

- Created pico-retro project directory with CMakeLists.txt supporting Pico and Pico W builds via a single `PICO_RETRO_WIRELESS` cmake option
- Defined retro_config_t with 13-button enum, per-trigger analog/digital mode, calibration min/max, EMA alpha, and interrupt-safe flash storage
- Copied xinput_driver and pico_sdk_import.cmake verbatim from pico-pedal; created device-mode-only tusb_config.h

## Task Commits

1. **Task 1: Project scaffold** — `340584e` (feat)
2. **Task 2: retro_config.h and retro_config.c** — `dbfdb37` (feat)

## Files Created/Modified

- `Source Code/pico-retro/CMakeLists.txt` — Dual-target cmake build (Pico default, Pico W via PICO_RETRO_WIRELESS=ON)
- `Source Code/pico-retro/pico_sdk_import.cmake` — SDK import boilerplate (copied from pico-pedal)
- `Source Code/pico-retro/src/tusb_config.h` — TinyUSB device mode only, CDC enabled, no host/PIO-USB
- `Source Code/pico-retro/src/xinput_driver.h` — XInput driver API + magic vibration detection (copied from pico-pedal)
- `Source Code/pico-retro/src/xinput_driver.c` — XInput TinyUSB class driver implementation (copied from pico-pedal)
- `Source Code/pico-retro/src/retro_config.h` — Config struct, button enum (13 entries), input_mode_t, function declarations
- `Source Code/pico-retro/src/retro_config.c` — Flash load/save with save_and_disable_interrupts, rotating-accumulate checksum, defaults

## Decisions Made

- Single cmake target `pico_retro_controller` with `PICO_RETRO_WIRELESS` option — cleaner than two separate targets; matches how wireless guitar is built (separate cmake invocation)
- tusb_config.h stripped of all PIO-USB/host-mode config since pico-retro has no USB passthrough (unlike pico-pedal)
- config_set_defaults sets all pins to -1 and device_name to empty — pico-retro is meant for community use where GPIO varies per hardware, so no hardcoded defaults make sense

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Project scaffold is complete; all subsequent plans (usb_descriptors.c, main.c, retro_config_serial.c) have their home directory and CMakeLists.txt already listing them in the source list
- retro_config_t struct is the authoritative config definition for all subsequent firmware plans
- xinput_driver.c is ready to be used by usb_descriptors.c and main.c
- No blockers for Phase 1 Plan 02

---
## Self-Check: PASSED

- All 7 files confirmed present on disk
- Commits 340584e and dbfdb37 verified in git log
- retro_config.h: 8 occurrences of retro_config_t, all required constants and fields present
- retro_config.c: 7 function implementations, 0xDEADBEEF checksum, interrupt-safe flash ops

---
*Phase: 01-firmware-foundation*
*Completed: 2026-03-19*
