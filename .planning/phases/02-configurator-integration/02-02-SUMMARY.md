---
phase: 02-configurator-integration
plan: 02
subsystem: ui
tags: [tkinter, python, configurator, xinput, serial, retro-gamepad]

# Dependency graph
requires:
  - phase: 01-firmware-foundation
    provides: retro_config_serial.c GET_CONFIG key names (btn0-btn12, pin_lt/rt, mode_lt/rt, lt/rt_min/max/ema_alpha/invert, debounce, device_name)

provides:
  - RetroApp class in configurator.py for retro_gamepad device type
  - 13-button GPIO pin mapping UI with CustomDropdown and Detect placeholders
  - LT/RT trigger tabs with digital/analog mode selection and EMA calibration sliders
  - Device name entry with alphanumeric+space validation, max 20 chars
  - _load_config() / _push_all_values() serialization covering all retro_config_t fields
  - retro_gamepad entry in DEVICE_SCREEN_MAP and DEVICE_SCREEN_CLASSES

affects:
  - 02-03 (Plan 03 adds DETECT threading and live monitor bar to RetroApp)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - RetroApp follows PedalApp constructor pattern (pico, frame, _build_menu, _build_ui)
    - _make_device_name_section accepts parent arg (vs PedalApp self.content implicit)
    - Combo .current() always followed by manual IntVar.set() sync per CLAUDE.md rule
    - _refresh_trigger_tab called after every layout change that affects scroll height
    - show() sets window title and menubar; __init__ never touches these

key-files:
  created: []
  modified:
    - Source Code/configurator/configurator.py

key-decisions:
  - "RetroApp GPIO_OPTIONS uses -1..27 (28 GPIO pins); ADC_OPTIONS restricted to -1,26,27,28 for analog trigger pin selector"
  - "EMA alpha stored as 0-100 integer percent in both firmware and UI (not lookup table)"
  - "retro_gamepad added to DEVICE_SCREEN_MAP and DEVICE_SCREEN_CLASSES for automatic screen routing"
  - "Detect buttons and monitor bar are placeholder-ready stubs; threading implemented in Plan 03"

patterns-established:
  - "Section builder methods take an explicit parent frame arg for testability"
  - "_refresh_trigger_tab handles both show/hide of analog frame and pin dropdown values swap"

requirements-completed:
  - CFG-02
  - CFG-05
  - CFG-08
  - CFG-09

# Metrics
duration: 15min
completed: 2026-03-20
---

# Phase 02 Plan 02: RetroApp Configurator Screen Summary

**RetroApp class with 13-button GPIO mapping, LT/RT trigger tabs (digital/analog), EMA calibration sliders, and full config load/push lifecycle registered in DEVICE_SCREEN_CLASSES for retro_gamepad routing**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-20T14:38:50Z
- **Completed:** 2026-03-20T14:53:50Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- RetroApp class inserted before DEVICE_SCREEN_CLASSES with complete static UI layout
- Button pin mapping section: 13 rows (D-Pad/ABXY/Start/Select/Guide/LB/RB) each with CustomDropdown (GPIO 0-27 + Disabled) and Detect placeholder
- LT/RT trigger tabs using ttk.Notebook with mode-dependent UI: digital (GPIO pin only) vs analog (min/max sliders 0-4095, EMA slider 0-100%, invert checkbox, monitor placeholder)
- `_load_config()` parses all GET_CONFIG keys from retro_config_serial.c response into tk.Vars
- `_push_all_values()` sends SET commands for all 13 btn keys, trigger config, calibration, debounce, device_name
- `show()`/`hide()` navigation sets title/menubar in `show()` only per CLAUDE.md rule
- `retro_gamepad` registered in both DEVICE_SCREEN_MAP and DEVICE_SCREEN_CLASSES

## Task Commits

Each task was committed atomically:

1. **Task 1: Create RetroApp class with UI structure and config load/push** - `757d775` (feat)

**Plan metadata:** (docs commit to follow with SUMMARY.md)

## Files Created/Modified
- `Source Code/configurator/configurator.py` - Added RetroApp class (1287 lines) and retro_gamepad entries in routing tables

## Decisions Made
- GPIO_OPTIONS covers -1 (disabled) + 0-27 for button mapping; ADC_OPTIONS restricted to -1,26,27,28 for trigger analog pin selector (matches firmware ADC-capable pins)
- EMA alpha is 0-100 integer (linear percent), stored directly - not a lookup table (differs from PedalApp which omits EMA entirely)
- Detect button stubs (`_start_btn_detect`, `_start_trigger_detect`) added as pass-through placeholders to keep Plan 03 injection surface clean
- `_make_card(parent)` accepts explicit parent unlike PedalApp's implicit `self.content` - cleaner when multiple sections share a frame

## Deviations from Plan

None - plan executed exactly as written. The plan specified the loop-based `_push_all_values()` pattern, which was implemented as specified.

## Issues Encountered
- Edit tool string match failure on first attempt due to trailing whitespace differences in the target block - resolved by using exact characters from Read output.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- RetroApp is ready for Plan 03 to wire in DETECT threading (SCAN/STOP serial protocol) and LiveBarGraph monitor bars for analog trigger live readout
- `self._btn_detect_buttons` dict and `self._lt_monitor_bar` / `self._rt_monitor_bar` placeholders are in place for Plan 03 to replace

---
*Phase: 02-configurator-integration*
*Completed: 2026-03-20*
