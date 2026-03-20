# Phase 1: Firmware Foundation - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement TWO separate firmware variants for pico-retro (like guitar-wired vs guitar-wireless), each enumerated as a standard XInput gamepad on Windows:

1. **pico-retro-wired** — Pico only, wired USB XInput mode
2. **pico-retro-wireless** — Pico W only, wired USB mode (detects USB at boot) + wireless-ready architecture for Phase 3+ BLE implementation

Both variants handle all 13 digital button inputs with fully configurable GPIO pin assignments, support 2 LT/RT triggers configurable per-trigger as analog (0-255 ADC-scaled) or digital (0 or 255), store configuration in flash with magic number and CRC checksum, and support CDC serial config mode (115200 baud) with existing command protocol.

Configurator detects device type (via DEVTYPE response) and flashes the appropriate `.uf2` file. Both firmware targets are built from the same pico-retro source tree (separate CMake targets like guitar-wired/wireless).

</domain>

<decisions>
## Implementation Decisions

### Trigger GPIO Pin Configuration
- **Single pin per trigger** — Config struct stores one GPIO pin per trigger (pin_lt, pin_rt), not separate pins for analog vs digital
- Firmware checks the current mode (stored in config) and reads that pin via ADC (analog mode) or GPIO pull (digital mode)
- Simplifies the config struct and matches the pedal approach rather than guitar's dual-pin pattern
- Configurator will present a single DETECT function per trigger (user presses/pulls, configurator records the pin)

### Trigger Output in Digital Mode
- Even when set to digital mode, triggers output axis values (0–255 on the trigger axis), not button events
- Digital mode means "threshold detection on a single GPIO pin" (reads HIGH/LOW), not "generate a button press"
- Output: 0 when released, 255 when pressed; no intermediate values in digital mode
- This keeps the XInput report structure consistent (triggers always output axis values)

### Boot Behavior Without USB
- When firmware boots and does NOT detect USB host within ~1 second (USB_MOUNT_TIMEOUT_MS), enter **sleep/standby state** ready for wireless
- Do NOT attempt to enumerate as XInput without a host
- This follows the guitar-wireless pattern and scaffolds for future BLE HID implementation (Phase 3+)
- During standalone testing in Phase 1, USB must be present for any XInput behavior
- No LED signaling (pico-retro v1 has no LEDs); firmware will be silent waiting for USB

### Config Mode Entry
- **Only watchdog scratch register trigger** — magic vibration sequence from configurator (via SET:reboot_to_config=1 or similar)
- **No button-hold fallback** at boot (unlike guitar-wireless with SELECT hold)
- If configurator cannot communicate via USB, user must reconnect USB before reconfiguring
- This is acceptable for v1 since pico-retro is prepared for community contributions; advanced users can add fallback later if needed

### Button Index Enum & XInput Mapping
- Define 13-button enum (button_index_t):
  - DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT (4)
  - BTN_A, BTN_B, BTN_X, BTN_Y (4)
  - BTN_START, BTN_SELECT (2)
  - BTN_GUIDE (1)
  - BTN_LB, BTN_RB (2)
  - **Total: 13 buttons** (triggers are NOT button indices; they are analog/digital outputs)
- Map each to standard XInput button masks via lookup table (like guitar/drums/pedal)
- LT/RT are separate from this enum — they are always axis outputs, never buttons

### Config Struct Design
- Magic number: unique 4-char code (e.g., "RETRO" → 0x52455452)
- CONFIG_VERSION: start at 1 (increment if struct layout changes)
- Fields:
  - `int8_t pin_buttons[13]` — GPIO pin per button (-1 = disabled)
  - `int8_t pin_lt`, `pin_rt` — LT/RT GPIO pins (-1 = disabled)
  - `uint8_t mode_lt`, `mode_rt` — INPUT_MODE_DIGITAL or INPUT_MODE_ANALOG
  - `uint8_t debounce_ms` — shared debounce time for all digital inputs
  - `char device_name[32]` — alphanumeric, max 20 chars (validated in firmware + configurator)
  - Per-trigger calibration (if analog): `uint16_t lt_min, lt_max, rt_min, rt_max` (raw ADC 0–4095)
  - Per-trigger invert: `uint8_t lt_invert, rt_invert` (0 = normal, 1 = invert)
  - Per-trigger EMA smoothing: `uint8_t lt_ema_alpha, rt_ema_alpha` (0–100, user-facing %)
  - `uint32_t checksum` — CRC over struct (like all other variants)
- Store in flash sector (last sector, like guitar/drums/pedal)

### Firmware Variants & Device Identity
- **DEVTYPE string**: Both variants respond with `DEVTYPE:pico_retro` in GET_CONFIG (used by configurator routing)
- **XInput mode VID/PID**: 0x045E / 0x028E (standard XInput, Windows recognizes as "gamepad")
- **XInput subtype**: 0x01 (XINPUT_DEVSUBTYPE_GAMEPAD — standard gamepad, not guitar/drums)
  - NOTE: Requires adding `1: "pico_retro"` to `XINPUT_SUBTYPE_TO_DEVTYPE` dict in configurator.py (one-line change, part of Phase 1)
  - NOTE: Also requires adding `1` to `OCC_SUBTYPES` list in configurator.py
- **Config mode VID/PID**: 0x2E8A / 0xF00F (unique PID for pico-retro config mode, different from guitar/drums/pedal)
- **String descriptor**: "Retro Gamepad" + device_name from config (so Windows Device Manager shows something user-friendly)
- **CDC interface**: Separate for config mode (115200 baud, like all variants)

### Serial Config Protocol
- Reuse existing protocol (115200 baud, CDC)
- Commands: PING, GET_CONFIG, SET:key=value, SAVE, DEFAULTS, REBOOT
- GET_CONFIG response must include `DEVTYPE:pico_retro` (first line, after PING)
- SET command keys: `pin_button_N`, `pin_lt`, `pin_rt`, `mode_lt`, `mode_rt`, `lt_min`, `lt_max`, etc. (match struct fields)
- Full config serialization/deserialization (like existing firmwares)

### Analog Trigger Smoothing (EMA)
- Exponential Moving Average filter: `output = (1 - alpha) * output + alpha * raw_adc`
- Alpha stored as 0–100 (user-facing %), converted internally to 0.0–1.0 (0.00 = no smoothing, 1.00 = only latest sample)
- Apply only in analog mode
- Matches guitar whammy/tilt smoothing behavior

### Start-Up Calibration
- On first boot or DEFAULTS command, set calibration to full range:
  - `lt_min = 0, lt_max = 4095` (raw ADC)
  - `rt_min = 0, rt_max = 4095`
- User can refine via configurator monitor screen + min/max sliders (Phase 2)

### Claude's Discretion
- Exact EMA alpha conversion formula (linear 0–100 → 0.0–1.0, or curve-based)
- Specific flash sector address and memory layout
- XInput vibration sequence recognition (magic pattern from configurator vibration request)
- Exact USB_MOUNT_TIMEOUT_MS value (1000 seems safe; could be 500–2000)
- Internal debounce implementation (simple state machine vs counter; current approach used in guitar/drums/pedal is fine)

</decisions>

<specifics>
## Specific Ideas

- Config struct should be directly comparable to guitar_config.h in structure (magic + version + pins + modes + calibration + checksum) so the codebase feels cohesive
- Device name validation: alphanumeric + space, max 20 chars (same as existing project standard)
- USB descriptor should say "Retro Gamepad" or similar in the device string so Windows Device Manager displays something intuitive to end users (not "Unknown Device")

</specifics>

<canonical_refs>
## Canonical References

### Firmware Architecture
- `Source Code/pico-pedal/src/pedal_config.h` — Simplest config struct example (magic, version, pins, device_name, checksum pattern)
- `Source Code/pico-drums-wired/src/drum_config.h` — Multi-button config with LED (no LEDs for pico-retro, but button indexing pattern is relevant)
- `Source Code/pico-guitar-controller-wireless/src/guitar_config.h` §L1–L100 — Dual-mode input (analog/digital), per-input calibration (min/max), EMA smoothing, USB detection pattern
- `Source Code/pico-guitar-controller-wireless/src/main.c` §L1–L150 — Boot flow with USB detection timeout, wireless standby scaffold, config mode entry via watchdog

### USB & Serial
- `Source Code/pico-pedal/src/usb_descriptors.c` — CDC config mode descriptor pattern
- `Source Code/pico-drums-wired/src/usb_descriptors.h` — XInput VID/PID and device subtype enum
- `CLAUDE.md` § VID/PID Reference table — Config mode PIDs (guitar=0xF00D, drums=0xF00E, pico-retro=0xF00F)

### REQUIREMENTS.md
- `.planning/REQUIREMENTS.md` §L6–L20 — Phase 1 firmware requirements (FW-01 through FW-10, USB-02) — exact acceptance criteria

### Serial Protocol
- `Source Code/pico-pedal/src/pedal_config_serial.c` — Serial command parsing and config struct serialization (reuse pattern, not LEDs)
- Existing commands (PING, GET_CONFIG, SET, SAVE, DEFAULTS, REBOOT) already proven; no new protocol needed

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **pedal_config.h + pedal_config.c** — Direct template for config struct (simple, small, no LEDs). Can mostly copy and adapt field names.
- **guitar_config.h** §L69–L120 — Analog/digital mode enum pattern, min/max calibration fields, EMA smoothing field
- **xinput_driver.c** — Button mask lookup table (all variants share this; add pico-retro button indices)
- **config_serial.c** (guitar or pedal) — SET:key=value parsing, GET_CONFIG response formatting, DEVTYPE handling
- **usb_descriptors.c** — CDC + XInput descriptor pattern (dual mode)

### Established Patterns
- Button indexing via enum (button_index_t) and lookup table to XInput masks — proven across guitar/drums/pedal
- Config struct with magic/version/checksum stored in last flash sector — standard in all variants
- ADC reading with debounce state machine — implemented in guitar/pedal
- CDC serial config mode via watchdog scratch register trigger — standard boot flow
- USB detection timeout (USB_MOUNT_TIMEOUT_MS) and wireless-ready boot — guitar-wireless pattern

### Integration Points
- Add new CMakeLists.txt in `Source Code/pico-retro/` (copy pico-pedal structure, add to top-level build list)
- Add DEVTYPE="pico_retro" mapping in configurator.py (DEVTYPE_TO_UF2_SUBSTRING, XINPUT_SUBTYPE_TO_DEVTYPE)
- Add XInput subtype 0x01 mapping to pico_retro in configurator XINPUT_SUBTYPE_TO_DEVTYPE dict
- Serial device detection in configurator uses DEVTYPE; no changes needed beyond firmware DEVTYPE response

</code_context>

<deferred>
## Deferred Ideas

- BLE wireless implementation — Phase 3+. Boot architecture in Phase 1 will be ready; actual BTstack HID code deferred.
- LED support — explicitly out of scope for v1 to keep firmware simple for community contributions.
- Advanced button remapping (modifier chords, etc.) — future enhancement; standard gamepad mapping is table stakes.

</deferred>

---

*Phase: 01-firmware-foundation*
*Context gathered: 2026-03-19*
