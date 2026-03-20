---
phase: 01-firmware-foundation
plan: 05
subsystem: ui
tags: [configurator, xinput, device-routing, pid, pico-retro]

# Dependency graph
requires: []
provides:
  - Configurator recognizes pico-retro via XInput subtype 0x01 (OCC_SUBTYPES)
  - Configurator can find pico-retro serial port in CDC config mode (PID 0xF00F in CONFIG_MODE_PIDS)
  - Configurator maps pico_retro device type to "retro" for UF2 filename matching
affects: [02-retro-configurator-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "New device registration pattern: 4 routing-table additions per device type (CONFIG_MODE_PIDS, DEVICE_TYPE_UF2_HINTS, XINPUT_SUBTYPE_TO_DEVTYPE, OCC_SUBTYPES)"

key-files:
  created: []
  modified:
    - "Source Code/configurator/configurator.py"

key-decisions:
  - "XInput subtype 0x01 (standard gamepad) chosen for pico-retro — plan specified this value"
  - "Config-mode PID 0xF00F chosen for pico-retro — inserted between 0xF00E (drums) and 0xF010 (pedal) in sequential order"
  - "DEVICE_SCREEN_CLASSES left unchanged — pico_retro entry deferred to Phase 2 when RetroApp class is created; unknown device type already handled gracefully"

patterns-established:
  - "Device registration pattern: each new firmware variant requires exactly 4 routing-table additions to configurator.py without removing existing entries"

requirements-completed: [FW-08]

# Metrics
duration: 1min
completed: 2026-03-20
---

# Phase 1 Plan 05: Configurator pico-retro device identity registration

**4-line addition registers pico-retro XInput subtype 0x01, config-mode PID 0xF00F, and UF2 hint "retro" in configurator routing tables**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-20T04:55:25Z
- **Completed:** 2026-03-20T04:56:37Z
- **Tasks:** 1 of 1
- **Files modified:** 1

## Accomplishments
- Added `0xF00F: "Retro Gamepad Config"` to CONFIG_MODE_PIDS enabling CDC serial port detection
- Added `"pico_retro": "retro"` to DEVICE_TYPE_UF2_HINTS for UF2 firmware file matching
- Added `1: "pico_retro"` to XINPUT_SUBTYPE_TO_DEVTYPE for XInput gamepad routing
- Added `1` to OCC_SUBTYPES set so pico-retro is recognized as an OCC device during XInput polling

## Task Commits

Each task was committed atomically:

1. **Task 1: Add pico-retro device identity to configurator routing tables** - `fdd5b85` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `Source Code/configurator/configurator.py` - Added 4 routing-table entries for pico-retro device type registration

## Decisions Made
- XInput subtype 0x01 (standard gamepad / XINPUT_DEVSUBTYPE_GAMEPAD) chosen as specified in the plan
- Config-mode PID 0xF00F inserted in sequential PID order between existing 0xF00E and 0xF010
- DEVICE_SCREEN_CLASSES deliberately left unchanged — pico_retro will be added in Phase 2 when RetroApp class is created; the configurator already handles unknown device types gracefully with an "unsupported device type" message, so adding a None entry would cause a crash rather than graceful degradation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Python syntax verified via `py -m py_compile`. All 4 additions confirmed present and original entries intact.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Configurator routing infrastructure for pico-retro is complete
- Phase 2 (02-retro-configurator-ui) can now create the RetroApp screen class and add `"pico_retro": RetroApp` to DEVICE_SCREEN_CLASSES
- The "retro" UF2 hint will correctly match any firmware file containing "retro" in its filename

---
## Self-Check: PASSED

- `Source Code/configurator/configurator.py` — FOUND
- Commit `fdd5b85` — FOUND

*Phase: 01-firmware-foundation*
*Completed: 2026-03-20*
