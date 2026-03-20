---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
stopped_at: Completed 02-03-PLAN.md (gap closure — device routing fix)
last_updated: "2026-03-20T15:05:07.230Z"
progress:
  total_phases: 2
  completed_phases: 2
  total_plans: 8
  completed_plans: 8
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-19)

**Core value:** Community-friendly retro gamepad firmware with flexible GPIO configuration and consistent configurator experience
**Current focus:** Phase 02 — configurator-integration

## Current Position

Phase: 02 (configurator-integration) — COMPLETE
Plan: 3 of 3 (gap closure 02-03 complete)

## Performance Metrics

**Velocity:**

- Total plans completed: 1
- Average duration: 1 min
- Total execution time: ~0.02 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| Phase 01-firmware-foundation P05 | 1 | 1 tasks | 1 files |

**Recent Trend:**

- Last 5 plans: 1 min
- Trend: -

*Updated after each plan completion*
| Phase 01-firmware-foundation P01 | 15 | 2 tasks | 7 files |
| Phase 01-firmware-foundation P02 | 2 | 2 tasks | 2 files |
| Phase 01-firmware-foundation P03 | 5 | 1 tasks | 2 files |
| Phase 01-firmware-foundation P04 | 3 | 1 tasks | 1 files |
| Phase 02-configurator-integration P01 | 2 | 1 tasks | 1 files |
| Phase 02-configurator-integration P02 | 15 | 1 tasks | 1 files |
| Phase 02-configurator-integration P03 | 1 | 1 tasks | 1 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Pre-Phase 1: Config-mode PID must be confirmed against configurator.py find_config_port() scan list before firmware write — STACK.md says 0xF011, FEATURES.md says 0xF00F, ARCHITECTURE.md says 0xF00F; pick the correct next-sequential value
- Pre-Phase 1: XInput subtype must be confirmed before firmware write — recommend 0x03 (ArcadeStick) to avoid false-positive collision with non-OCC standard gamepads; verify 0x03 is not already claimed
- Pre-Phase 1: DEVTYPE string is "retro_gamepad", config struct magic is 0x52455452 ("RETR"), version 1
- [Phase 01-firmware-foundation]: XInput subtype 0x01 chosen for pico-retro; config-mode PID 0xF00F inserted sequentially; DEVICE_SCREEN_CLASSES deferred to Phase 2 when RetroApp class is created
- [Phase 01-firmware-foundation]: Single cmake target pico_retro_controller; Pico W build via PICO_RETRO_WIRELESS=ON; OUTPUT_NAME Retro_Controller / Retro_Controller_W
- [Phase 01-firmware-foundation]: tusb_config.h device-mode only (no PIO-USB host); retro_config_t with int8_t pin fields (-1 disabled), EMA alpha 0-100, full-range calibration defaults
- [Phase 01-firmware-foundation]: XInput subtype 0x01 (XINPUT_SUBTYPE_GAMEPAD) chosen for pico-retro; CDC config-mode PID 0xF00F inserted sequentially
- [Phase 01-firmware-foundation]: config_serial_loop name chosen over config_mode_main for retro serial handler; device_name validates all chars before writing; SCAN/STOP intentionally omitted; debounce upper bound 255 (full uint8_t)
- [Phase 01-firmware-foundation]: g_config_mode set BEFORE tusb_init() to ensure correct descriptor set is loaded at USB init time
- [Phase 01-firmware-foundation]: Digital trigger outputs 0/255 axis byte (not button press) per CONTEXT.md locked decision
- [Phase 02-configurator-integration]: run_scan() scans from GPIO 0 (not 2 like pedal) — retro has no PIO-USB on GP0/GP1; pins 23/24/25 skipped (reserved); MONITOR_INTERVAL_MS=50ms for ~20Hz
- [Phase 02-configurator-integration]: RetroApp uses GPIO_OPTIONS -1..27 for buttons, ADC_OPTIONS -1/26/27/28 for trigger analog pin; EMA alpha is 0-100 int percent; pico_retro registered in DEVICE_SCREEN_CLASSES (was retro_gamepad placeholder, corrected in 02-03)
- [Phase 02-configurator-integration 02-03]: pico_retro key replaces retro_gamepad in DEVICE_SCREEN_MAP and DEVICE_SCREEN_CLASSES; device routing now matches firmware RETRO_DEVTYPE_STR exactly
- [Phase 02-configurator-integration]: pico_retro key replaces retro_gamepad placeholder in DEVICE_SCREEN_MAP and DEVICE_SCREEN_CLASSES to match firmware RETRO_DEVTYPE_STR

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 1 start: XInput subtype selection is an open question (0x01 vs 0x03) — must be resolved before writing usb_descriptors.h
- Phase 1 start: Config-mode PID has a three-way discrepancy across research docs — must check configurator.py source to confirm the next available PID
- Phase 2 dependency: Retro_Controller.gif tile asset must exist in configurator folder at EXE build time — can use a static placeholder if no animation is ready

## Session Continuity

Last session: 2026-03-20T15:03:01.332Z
Stopped at: Completed 02-03-PLAN.md (gap closure — device routing fix)
Resume file: None
