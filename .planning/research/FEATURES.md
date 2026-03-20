# Feature Research

**Domain:** Retro-style gamepad firmware (pico-retro variant for OCC platform)
**Researched:** 2026-03-19
**Confidence:** HIGH — derived from existing proven firmware variants in this codebase

## Context

pico-retro is a new firmware variant joining guitar-wired, guitar-wireless, drums-wired, and pico-dongle.
The OCC platform has established, battle-tested patterns for all foundational concerns. This research
maps which features are direct ports of those patterns vs which are new decisions for this variant.

The 13-button retro input set: DPad (Up/Down/Left/Right), ABXY, Start, Select, Guide, LB, RB, LT, RT.
All 13 map cleanly to standard XInput button bitmasks that already exist in `usb_descriptors.h`.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that every OCC firmware variant provides. Missing these = pico-retro feels like a broken draft,
not a shipping firmware.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| 13-button digital input set | Defines the device — without all 13 buttons it is not a retro gamepad | LOW | DPad=4, ABXY=4, Start/Select/Guide=3, LB/RB=2. All map directly to existing XINPUT_BTN_* masks |
| Configurable GPIO pin assignment per button | Every OCC variant does this. Users wire buttons to whatever GPIO is convenient on their PCB | LOW | `int8_t pin_buttons[BTN_IDX_COUNT]` array, -1=disabled. Direct copy of guitar/drums pattern |
| XInput gamepad output (VID 0x045E / PID 0x028E) | Required for Windows to recognise the device as a standard controller | LOW | Shared xinput_driver.c already handles this; retro uses standard gamepad subtype (0x01), not guitar alternate (0x07) |
| Dual-mode USB (XInput play + CDC config) | All OCC variants use this. Watchdog scratch register triggers config mode | LOW | Exact same boot-check pattern as guitar/drums — copy and adapt |
| Flash-backed config with CRC | Users expect settings to survive power cycle | LOW | Same `__attribute__((packed))` struct + CRC32 checksum pattern, last flash sector |
| Config mode serial protocol (PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, REBOOT, BOOTSEL, SCAN) | Configurator depends on this exact command set | MEDIUM | New `retro_config_serial.c` following same command dispatch pattern as `config_serial.c` and `drum_config_serial.c` |
| Magic vibration → config mode entry | Configurator uses this to enter config mode without physical button | LOW | Same MAGIC_STEP0/1/2 detection in xinput_driver.c — no change needed |
| Configurable debounce (ms) | Cheap buttons bounce. OCC always exposes this | LOW | Single `uint8_t debounce_ms` field, same per-button debounce loop |
| Custom device name (alphanumeric, max 20 chars) | Shown in Windows joy.cpl. Users want their device to have a real name | LOW | Same 32-byte `device_name` field + USB string descriptor pattern. Validation already exists in configurator |
| Onboard LED blink in config mode | Visual confirmation that config mode is active | LOW | Same 3-blink pattern from guitar/drums main.c |
| DEVTYPE response in GET_CONFIG | Configurator routes to RetroApp using this string | LOW | Define `DEVICE_TYPE "retro_gamepad"` — needs a new unique string and matching DEVTYPE in configurator |
| Config mode VID/PID distinct from play mode | Allows configurator to find the device without conflicting with guitar/drums | LOW | New PID needed (e.g. 0xF00F). Must be added to CLAUDE.md VID/PID table |

### Differentiators (Competitive Advantage)

Features that go beyond table stakes and deliver extra value for the OCC community. These make pico-retro
a useful platform contribution rather than just a bare-minimum port.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Analog trigger support (LT/RT as ADC inputs) | Many retro gamepad PCBs use analog triggers. Digital-only triggers lose nuance; analog gives 0-255 pressure range matching real XInput triggers | MEDIUM | XInput report has dedicated `uint8_t left_trigger` and `uint8_t right_trigger` byte fields (0-255). Configure as digital (GPIO pull-up) or analog (ADC GP26-28). Same digital/analog mode enum as guitar whammy/tilt |
| Analog trigger calibration (min/max ADC range) | Physical sensors vary. Same apply_sensitivity() pattern from guitar gives full-range travel from any sensor | LOW | `uint16_t lt_min/lt_max/rt_min/rt_max` in config struct. EMA smoothing optional |
| Analog trigger invert flag | Some sensors read high at rest. One-click fix in configurator | LOW | `uint8_t lt_invert / rt_invert` fields |
| GPIO SCAN command in config mode | Community builders use this to discover which pin a button is wired to without reading schematics | LOW | Exact same adaptive ADC noise-floor detection already in config_serial.c — copy directly |
| MONITOR_ADC:pin streaming | Live ADC readout for trigger calibration. pico-pedal already does this | LOW | Already proven in pedal_config_serial.c. Essential for analog trigger min/max calibration in RetroApp |
| EMA smoothing on analog triggers | Eliminates ADC jitter on trigger inputs without adding noticeable lag | LOW | Same `ema_state_t` + `ema_update()` pattern from guitar main.c; single shared `ema_alpha` config value |
| Wireless path readiness (Pico W architecture, implementation deferred) | pico-retro targets both Pico and Pico W. Structuring the firmware now avoids a painful rewrite later | MEDIUM | Follow guitar-wireless pattern: `#ifdef PICO_W` guards around BLE init, USB host detect at boot. v1 ships as wired-only; the BLE implementation is Phase 3+ |
| Report rate 1ms (1000Hz) | Same as guitar variant. Retro gamers expect low-latency input | LOW | `REPORT_INTERVAL_US 1000` — no change from guitar firmware |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem appealing but are deliberately excluded from pico-retro v1.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| APA102/LED strip support | "It would look cool" | Adds SPI peripheral init, LED config struct (180+ bytes in config), led_config_serial keys, and APA102 driver dependency. Triples firmware complexity. The whole point of pico-retro is low barrier to community contribution | Defer to v2+ as an optional add-on after core firmware is stable and documented |
| Analog stick (left/right thumbstick axes) | Standard gamepad has sticks | Retro gamepads do not have thumbsticks — that is the point of the retro form factor. Adding sticks blurs the scope and turns pico-retro into a generic gamepad firmware, which already exists | If full analog sticks are needed, that is a separate `pico-gamepad` variant |
| Button remapping in firmware | "Let me remap A to B" | GPIO-to-XInput-button is already configurable via pin assignment. Firmware-level remapping on top of that creates two layers of indirection that confuse users and complicate config serialisation | Configurator pin assignment covers this use case entirely |
| Rumble/vibration output passthrough | "I want force feedback" | XInput output reports already deliver rumble data to the firmware (the magic vibration detection path reads them). Actually driving motor hardware requires a separate GPIO + PWM subsystem and a new config key. Out of scope for v1 | Document the XInput OUT report path so community can add rumble in a fork |
| BLE wireless implementation (v1) | Wireless is convenient | BTstack BLE requires substantial init code, GATT profile generation, `can_send_now` callback pattern, connection parameter negotiation, and Pico W-specific build config. Full BLE doubles firmware complexity and test burden | Architecture ready (Pico W build target + `#ifdef PICO_W` guards). Implementation deferred to Phase 3+ milestone |

---

## Feature Dependencies

```
[XInput play mode output]
    └──requires──> [XInput gamepad subtype in USB descriptor]
                       └──requires──> [VID 0x045E / PID 0x028E]

[Config mode serial protocol]
    └──requires──> [Dual-mode USB (CDC path)]
                       └──requires──> [Watchdog scratch trigger]
                       └──requires──> [Config mode VID/PID distinct from play mode]

[Configurator RetroApp routing]
    └──requires──> [DEVTYPE "retro_gamepad" in GET_CONFIG response]
                       └──requires──> [Config mode serial protocol]

[Analog trigger calibration]
    └──requires──> [Analog trigger support (ADC mode)]
                       └──requires──> [Analog/digital mode enum in config struct]

[MONITOR_ADC streaming]
    └──enhances──> [Analog trigger calibration]

[EMA smoothing]
    └──enhances──> [Analog trigger support]

[Wireless readiness]
    └──requires──> [Core firmware stable on Pico (wired)]
    └──conflicts──> [APA102 LEDs v1] — BLE and LEDs both add substantial init; avoid combining in v1
```

### Dependency Notes

- **Analog trigger support requires mode enum:** `uint8_t lt_mode / rt_mode` (INPUT_MODE_DIGITAL=0, INPUT_MODE_ANALOG=1). Same enum already defined in guitar_config.h — retro_config.h can define its own copy or reuse.
- **DEVTYPE requires new string:** `"retro_gamepad"` must be added to `DEVICE_SCREEN_CLASSES` in the configurator alongside guitar/drums entries.
- **Config mode VID/PID conflict:** pico-retro needs its own CDC PID. 0xF00F is the natural next value after guitar (0xF00D) and drums (0xF00E). Must not reuse existing PIDs or the configurator cannot distinguish device types in config mode.
- **Wireless readiness does not conflict with wired:** `#ifdef PICO_W` compile-time guards ensure the wired Pico build is unaffected. The Pico W build compiles with BLE stubs until Phase 3.

---

## MVP Definition

### Launch With (v1)

Minimum viable pico-retro firmware — everything needed for a community member to build and use a retro gamepad.

- [ ] 13-button digital input set with configurable GPIO pins — core identity of the variant
- [ ] XInput gamepad subtype output (not guitar-alternate) — correct Windows device class
- [ ] Dual-mode USB with CDC config mode — required for configurator to work
- [ ] Config mode serial protocol (PING, GET_CONFIG, SET, SAVE, DEFAULTS, REBOOT, BOOTSEL, SCAN) — full configurator integration
- [ ] DEVTYPE "retro_gamepad" in GET_CONFIG — configurator routing to RetroApp
- [ ] New config mode PID (0xF00F) — distinguishable in CDC mode
- [ ] Configurable debounce — community buttons vary widely
- [ ] Custom device name — users want named devices
- [ ] Flash-backed config with CRC — settings survive power cycle
- [ ] Analog/digital trigger support for LT/RT with calibration (min/max, invert, EMA) — retro PCBs often have analog triggers; digital-only forces a hardware compromise
- [ ] MONITOR_ADC streaming — essential for trigger calibration workflow in RetroApp
- [ ] Pico W build target with `#ifdef PICO_W` guards (BLE stubs only) — future-proofs architecture without v1 implementation cost

### Add After Validation (v1.x)

Features to add once the core firmware is in community use.

- [ ] EMA smoothing configurability (alpha slider in RetroApp) — add once analog triggers are in use and smoothing need is confirmed
- [ ] GPIO SCAN adaptive noise-floor tuning for retro button hardware — initial copy from guitar may need threshold adjustment for different switch types
- [ ] RetroApp Easy Config section — simplify first-run pin assignment for most common wiring layouts

### Future Consideration (v2+)

Features deferred until pico-retro has community uptake.

- [ ] BLE wireless implementation (Pico W) — full BTstack HID peripheral path, Phase 3+ milestone
- [ ] APA102 LED strip support — optional visual flair; adds significant complexity
- [ ] Rumble output (GPIO + PWM for motor) — requires XInput OUT report parsing beyond magic detection

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| 13-button digital inputs + GPIO config | HIGH | LOW | P1 |
| XInput gamepad subtype output | HIGH | LOW | P1 |
| Dual-mode USB + CDC config mode | HIGH | LOW | P1 |
| Config serial protocol (full command set) | HIGH | MEDIUM | P1 |
| DEVTYPE + config mode PID | HIGH | LOW | P1 |
| Configurable debounce | HIGH | LOW | P1 |
| Custom device name | MEDIUM | LOW | P1 |
| Flash config + CRC | HIGH | LOW | P1 |
| Analog/digital trigger support + calibration | HIGH | MEDIUM | P1 |
| MONITOR_ADC streaming | MEDIUM | LOW | P1 |
| Pico W build target (BLE stubs) | MEDIUM | LOW | P1 |
| EMA smoothing slider | LOW | LOW | P2 |
| Easy Config for retro layout | MEDIUM | MEDIUM | P2 |
| BLE wireless implementation | MEDIUM | HIGH | P3 |
| APA102 LED support | LOW | HIGH | P3 |
| Rumble output | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Comparison: pico-retro vs Existing Variants

| Feature | guitar-wired | drums-wired | pico-retro (v1) |
|---------|--------------|-------------|-----------------|
| Button count | 14 (guitar-specific) | 14 (drums-specific) | 13 (standard gamepad) |
| Analog axes in play mode | 2 (whammy + tilt via right stick) | None | 2 (LT/RT as trigger bytes) |
| Analog calibration | Yes (min/max/invert/EMA) | No | Yes for LT/RT (same pattern) |
| LED strip support | Yes (APA102) | Yes (APA102) | No (v1) |
| Config mode PID | 0xF00D | 0xF00E | 0xF00F (proposed) |
| XInput subtype | 0x07 (guitar alternate) | 0x08 (drum kit) | 0x01 (standard gamepad) |
| I2C accelerometer | Yes (ADXL345/LIS3DH tilt) | No | No |
| Pico W wireless | Yes (BLE HID peripheral) | No | Architecture ready, v1 wired-only |
| Firmware files | guitar_config.{c,h}, config_serial.{c,h} | drum_config.{c,h}, drum_config_serial.{c,h} | retro_config.{c,h}, retro_config_serial.{c,h} |
| Config struct name | guitar_config_t | drum_config_t | retro_config_t |
| Config magic | 0x47554954 "GUIT" | 0x4452554D "DRUM" | new 4-byte value e.g. 0x52455452 "RETR" |

---

## Trigger Handling: Key Design Decision

XInput's `xinput_report_t` has dedicated `uint8_t left_trigger` and `uint8_t right_trigger` fields
(0–255 range), separate from the button bitmask. This is different from how guitar whammy/tilt
works (those use `int16_t right_stick_x/y`).

For pico-retro triggers:
- **Digital mode:** pressed = 255, released = 0
- **Analog mode:** ADC 0-4095 → 0-255 (8-bit mapping via `apply_sensitivity()` then divide by 16)
- **Invert flag:** 255 - value when sensor reads high at rest
- **EMA smoothing:** same `ema_state_t` + `ema_update()` but output truncated to 0-255

This is simpler than the guitar's bipolar whammy mapping. Both triggers follow the same
digital/analog mode pattern as whammy/tilt, just writing to different report fields.

---

## Sources

- Existing OCC firmware (guitar_config.h, drum_config.h, pedal_config.h, usb_descriptors.h, main.c) — HIGH confidence — first-party codebase
- XInput report structure (xinput_report_t) in usb_descriptors.h — HIGH confidence — verified in source
- PROJECT.md requirements (pico-retro scope, out-of-scope items) — HIGH confidence — authoritative project spec
- CLAUDE.md architectural rules — HIGH confidence — authoritative project guidelines

---
*Feature research for: pico-retro gamepad firmware variant (OCC platform)*
*Researched: 2026-03-19*
