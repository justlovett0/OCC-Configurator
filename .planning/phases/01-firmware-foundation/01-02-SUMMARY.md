---
phase: 01-firmware-foundation
plan: 02
subsystem: firmware/usb
tags: [usb-descriptors, xinput, cdc, pico-retro]
dependency_graph:
  requires: ["01-01"]
  provides: ["usb_descriptors.h", "usb_descriptors.c", "xinput_report_t", "g_config_mode"]
  affects: ["pico-retro main.c", "config_serial.c"]
tech_stack:
  added: []
  patterns: ["TinyUSB descriptor callbacks", "dual-mode XInput/CDC USB"]
key_files:
  created:
    - "Source Code/pico-retro/src/usb_descriptors.h"
    - "Source Code/pico-retro/src/usb_descriptors.c"
  modified: []
decisions:
  - "XInput subtype 0x01 (XINPUT_SUBTYPE_GAMEPAD) — standard gamepad, not guitar alternate"
  - "CDC config mode PID 0xF00F — next sequential slot after existing OCC variants"
  - "g_device_name initialized to NULL (not a default string) to allow main.c to control fallback"
metrics:
  duration: "2 min"
  completed: "2026-03-20"
  tasks_completed: 2
  files_created: 2
---

# Phase 1 Plan 02: USB Descriptor Layer Summary

**One-liner:** XInput gamepad descriptors (subtype 0x01) with CDC config mode (PID 0xF00F) using g_config_mode flag for descriptor switching.

## What Was Built

Two USB descriptor files for pico-retro that define the device's USB identity in both operating modes:

- **usb_descriptors.h** — All constants and types: VID/PID pairs, XInput subtype, CDC endpoint addresses, magic vibration sequence values, WATCHDOG_CONFIG_MAGIC, 15 XINPUT_BTN_* mask constants, and the packed xinput_report_t struct.
- **usb_descriptors.c** — TinyUSB descriptor callbacks: `tud_descriptor_device_cb`, `tud_descriptor_configuration_cb`, `tud_descriptor_string_cb`. XInput config descriptor uses XINPUT_SUBTYPE_GAMEPAD (0x01). CDC device descriptor uses CONFIG_MODE_PID (0xF00F). Product string is "Retro Gamepad" in XInput mode and "Retro Gamepad Config" in CDC mode. Serial number derived from Pico unique board ID.

## Decisions Made

| Decision | Rationale |
|---|---|
| XINPUT_SUBTYPE_GAMEPAD = 0x01 | Standard gamepad subtype; confirmed in STATE.md decisions from plan 01 resolution |
| CONFIG_MODE_PID = 0xF00F | Sequential after 0xF00D (guitar), 0xF00E (drums), 0xF010 (pedal) — pico-retro gets 0xF00F |
| g_device_name = NULL | main.c controls device name from config; usb_descriptors.c falls back to "Retro Gamepad" |
| Manufacturer string = "OCC" | Consistent with other OCC variants |
| No GUITAR_BTN_* aliases | Retro gamepad does not need guitar-specific aliases — buttons map directly to XINPUT_BTN_* |

## Commits

| Task | Commit | Description |
|---|---|---|
| Task 1: usb_descriptors.h | 8b7736f | Constants, masks, xinput_report_t, magic values |
| Task 2: usb_descriptors.c | ce0add0 | TinyUSB callbacks, dual-mode descriptor switching |

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- Source Code/pico-retro/src/usb_descriptors.h: FOUND
- Source Code/pico-retro/src/usb_descriptors.c: FOUND
- Commit 8b7736f: FOUND
- Commit ce0add0: FOUND
