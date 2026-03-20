# Pitfalls Research

**Domain:** Pico XInput firmware variant + Tkinter configurator integration
**Researched:** 2026-03-19
**Confidence:** HIGH — all pitfalls drawn from actual bugs encountered and fixed in the OCC codebase, documented in detailedcontext.md and CLAUDE.md

---

## Critical Pitfalls

### Pitfall 1: Missing DEVTYPE causes configurator to silently route nowhere

**What goes wrong:**
A new firmware variant that does not emit `DEVTYPE:<string>` as the first line of its `GET_CONFIG` response causes the configurator to treat the device as `"unknown"`. The `_route_to_screen()` call fails its lookup in `DEVICE_SCREEN_CLASSES`, shows an error dialog, and leaves the user on the main menu. No configurator screen opens at all. The error message instructs the developer to add `serial_writeln("DEVTYPE:" DEVICE_TYPE)` — which is exactly what happens when the line is missing.

**Why it happens:**
When porting from guitar firmware as a template, the `GET_CONFIG` response format looks like: `DEVTYPE:guitar_alternate`, then `CFG:key=val,...`. A new firmware author might change all the config keys but forget the `DEVTYPE:` string is hard-coded at the top of `config_serial.c`'s send function. Or they copy the header but leave `DEVICE_TYPE` pointing at `"guitar_alternate"` — the configurator then routes to the guitar `App` screen instead of the new one, producing a subtly broken configuration experience rather than an outright error.

**How to avoid:**
- Define `DEVICE_TYPE` in `retro_config.h` as a distinct string (e.g., `"retro_gamepad"`) before writing any `config_serial.c` code.
- Add `"retro_gamepad"` to `DEVICE_SCREEN_CLASSES` and `DEVICE_TYPE_UF2_HINTS` in `configurator.py` before testing the firmware.
- Verify by connecting the device and checking whether the configurator reaches the correct screen. If it shows the error dialog, `DEVTYPE:` is wrong or missing.

**Warning signs:**
- Configurator shows "Unsupported device type: guitar_alternate" when connecting a retro gamepad.
- Configurator shows the guitar `App` screen when a retro controller is connected.
- `GET_CONFIG` response in the serial debug console does not start with `DEVTYPE:`.

**Phase to address:** Phase 1 (firmware skeleton) — define `DEVICE_TYPE` and verify routing before writing any business logic.

---

### Pitfall 2: Config struct version mismatch causes silent defaults on every boot

**What goes wrong:**
The flash config is validated by three fields: `magic`, `version`, and `checksum`. If `CONFIG_VERSION` in the new firmware does not match the value stored in flash (e.g., because you flash the firmware but the Pico had a previous OCC variant stored), `config_is_valid()` returns false and `config_set_defaults()` runs on every boot. All user settings are silently discarded.

**Why it happens:**
Different OCC variants use different `CONFIG_MAGIC` values (`"GUIT"` = `0x47554954`, `"DRUM"` = `0x4452554D`) which prevents cross-variant corruption. But if a developer forgets to define a unique magic for `pico-retro` and reuses `"GUIT"`, then the retro firmware would load garbage config from a Pico that previously ran guitar firmware. The checksum catches it in practice, but the wrong magic is confusing.

Separately, adding a field to the config struct mid-development without bumping `CONFIG_VERSION` causes a packed-struct size mismatch: `config_is_valid()` passes (old magic + old version = valid), but `sizeof(retro_config_t)` has changed, so `memcpy` loads the wrong bytes into the new fields. This produces mysterious behavior on devices that were previously flashed.

**How to avoid:**
- Define a unique `CONFIG_MAGIC` for pico-retro (e.g., `0x52455452` = `"RETR"`).
- Start at `CONFIG_VERSION 1`. Bump the version every time a field is added to the config struct during development.
- Never reuse magic values from other OCC variants.

**Warning signs:**
- `config_is_valid()` always returns false even on a freshly saved config.
- All config resets to defaults every boot after adding a new struct field.
- A Pico that previously ran guitar firmware behaves erratically with retro firmware before a factory reset.

**Phase to address:** Phase 1 (firmware skeleton) — define magic and version before the first build.

---

### Pitfall 3: XInput subtype collision causes configurator to misidentify the device

**What goes wrong:**
The configurator identifies XInput devices before a serial connection by reading the XInput subtype byte from the USB descriptor. `OCC_SUBTYPES = {8, 6, 7, 11}` maps subtypes to device types. If pico-retro uses a subtype already in that set, the configurator routes to the wrong configurator screen. If it uses a subtype outside the set, the device is invisible to the configurator's main menu controller card — the user sees "No OCC device detected" despite the controller being connected and functional.

The subtype `0x05` (`XINPUT_DEVSUBTYPE_DANCE_PAD`) must never be used — Windows suppresses all analog axis output for it. This was a real bug encountered with the dongle.

**Why it happens:**
XInput subtypes that are meaningful to Windows: `0x01` = Gamepad, `0x02` = Wheel, `0x03` = ArcadeStick, `0x04` = FlightStick, `0x05` = DancePad (suppresses axes), `0x06` = Guitar, `0x07` = GuitarAlternate, `0x08` = DrumKit, `0x0B` = GuitarBass (used as dongle). A retro gamepad is logically a `0x01` (Gamepad), but that subtype is very common and is not in `OCC_SUBTYPES`, so the main menu would ignore it.

**How to avoid:**
- Choose a subtype that is safe for axis output and not already used by other OCC variants. The dongle uses `0x0B` (GuitarBass) specifically to be distinguishable. The retro gamepad could use `0x03` (ArcadeStick) or `0x04` (FlightStick) — both pass analog axes through cleanly.
- Add the chosen subtype to `OCC_SUBTYPES` and `XINPUT_SUBTYPE_TO_DEVTYPE` in `configurator.py` at the same time the firmware defines it.
- Test by launching the configurator with the controller plugged in via XInput and confirming the controller card appears.

**Warning signs:**
- Main menu shows "No OCC device detected" when the controller is connected.
- Main menu shows the wrong device type (e.g., "Guitar") for a retro gamepad.
- Backup & Update finds no matching UF2 for the device.

**Phase to address:** Phase 1 (firmware skeleton) — pick subtype and update configurator constants before testing any USB detection.

---

### Pitfall 4: Config mode PID collision causes port detection failure or ambiguous routing

**What goes wrong:**
In config mode the firmware uses a distinct VID/PID pair (`0x2E8A/0xF00D` for guitar, `0x2E8A/0xF00E` for drums). The configurator scans for these PIDs in `find_config_port()`. If pico-retro reuses an existing PID (e.g., `0xF00D`), the configurator cannot tell which device type is in config mode from the PID alone. It must then rely entirely on the `DEVTYPE:` line — which is fine as long as `DEVTYPE` is correct — but the main menu connection flow sends the magic sequence to whatever XInput controller it finds, meaning if both a guitar and a retro gamepad are plugged in, the wrong one might enter config mode.

**Why it happens:**
The natural shortcut is to copy `usb_descriptors.h` from guitar firmware. The PID constant `CONFIG_MODE_PID = 0xF00D` is right there; a developer might not realize it needs to change.

**How to avoid:**
- Assign a new PID to pico-retro config mode (e.g., `0xF010`).
- Update the VID/PID reference table in `CLAUDE.md` when adding the new variant.
- The configurator's `find_config_port()` scans all known config PIDs — update that list to include the new PID.

**Warning signs:**
- Configurator intermittently routes to the guitar screen when a retro controller enters config mode.
- Two OCC devices plugged in simultaneously cause configuration of the wrong device.

**Phase to address:** Phase 1 (firmware skeleton) — before first config mode test.

---

### Pitfall 5: Serial poll race condition corrupts config mode operations

**What goes wrong:**
`MainMenu._refresh_controller_status()` opens the serial port every 1 second to read the device name. If the Backup & Update background worker, a save operation, or any other serial-using action is in progress at the same time, the poll grabs the port first and causes `PermissionError: [Errno 13] Access is denied` on the worker's side. The worker fails partway through a save or restore sequence.

**Why it happens:**
Tkinter's `after()` poll is on the main thread. The worker is on a background thread. Both attempt `serial.Serial(port)` at unpredictable moments. Without a mutex, whichever thread reaches `CreateFile` first wins; the other gets Access Denied.

This was a real bug in OCC fixed by the `_backup_in_progress` flag: when the flag is set, `_refresh_controller_status()` skips the serial open entirely.

**How to avoid:**
- The `_backup_in_progress` flag pattern already exists in `MainMenu`. The `RetroApp` screen will need the same pattern for its own 1s poll.
- Any new "monitoring" mode (e.g., analog trigger live view) must guard itself with a `_monitor_active` flag checked in the poll.
- Never open the serial port inside a `_poll` or `after()` callback while a background worker thread might hold it.

**Warning signs:**
- `PermissionError` appearing in save/restore error dialogs on devices that are working correctly at the USB/firmware level.
- Intermittent config saves that succeed sometimes and fail sometimes with no firmware changes.
- `ERR:unknown command` responses poisoning the read buffer (caused by the poll sending a command while the monitor stream is active).

**Phase to address:** Phase 2 (configurator screen) — implement poll guard before any serial background work.

---

### Pitfall 6: SCAN mode `STOP` command sent to non-scanning firmware corrupts subsequent response

**What goes wrong:**
When a detect button is clicked, the configurator sends `SCAN`, reads pin responses, then sends `STOP`. If the firmware is not currently in scan mode (e.g., because the user clicked Stop on a previous scan and the configurator's state is out of sync), the firmware responds `ERR:unknown command`. This `ERR:` line sits in the read buffer and is read as the response to the next command (e.g., `SET:green=5` receives `ERR:unknown command` instead of `OK`). The save fails.

**Why it happens:**
The firmware only recognizes `STOP` inside the scan loop. Outside it, `STOP` is an unknown command. The configurator must track `self.scanning` accurately and only send `STOP` if it knows the firmware is scanning.

This was fixed in PedalApp with the `was_active` guard. The retro configurator must follow the same pattern from the start.

**How to avoid:**
- Track `self.scanning` as a boolean. Set it `True` when `SCAN` is sent, `False` when `STOP` is sent or when scan results in a timeout.
- Only transmit `STOP\n` to the firmware when `was_active = self.scanning` is True at the point of stopping.
- Call `pico.flush_input()` / `reset_input_buffer()` before the first command after any mode transition.

**Warning signs:**
- Save succeeds on first attempt but fails with `ERR:unknown command` after the user has used the Detect feature.
- Serial debug console shows `ERR:unknown command` immediately after a `SET:` command.

**Phase to address:** Phase 2 (configurator screen) — implement correctly in `_stop_detect()` from day one.

---

### Pitfall 7: Combo box `.current()` does not fire `<<ComboboxSelected>>` — IntVar goes out of sync

**What goes wrong:**
During `_load_config()`, the configurator calls `combo.current(index)` to set the displayed value of a dropdown. This does NOT fire the `<<ComboboxSelected>>` event. Any code that reads the backing `IntVar` on save will get whatever the `IntVar` was last set to by an event — which may be stale from a previous load or the default from `__init__`. The save then sends the wrong pin number to the firmware.

**Why it happens:**
This is a known Tkinter behavior (confirmed in CLAUDE.md and in the detailed session context). The `<<ComboboxSelected>>` binding only fires on user interaction. `combo.current()` is a display-only operation.

**How to avoid:**
- After every `combo.current(index)` call during config load, immediately set the backing `IntVar`: `self.some_pin_var.set(OPTION_LIST[index])`.
- For analog/digital pin combos, use the proven pattern from the guitar App: after loading, call the sync helper with `restore=True` to update enable/disable states without wiping pin vars.
- Write a brief `_sync_combos_from_vars()` method for the retro screen and call it at the end of `_load_config()`.

**Warning signs:**
- Saving config and reloading shows different values than what the UI displayed.
- A pin that was set to GPIO 5 in the UI saves as GPIO 0 (the default).
- Works on first connect; breaks after config is loaded from firmware.

**Phase to address:** Phase 2 (configurator screen) — before `_load_config()` is tested.

---

### Pitfall 8: UI cards rebuild every poll cycle — combo dropdowns collapse while user is interacting

**What goes wrong:**
If `_refresh_firmware_status()` or any 1-second poll unconditionally destroys and recreates UI widgets (cards, dropdowns, buttons), any open combo dropdown collapses the moment the poll fires. The user experiences menus that snap shut immediately after being opened, making the UI unusable with a connected device.

**Why it happens:**
The natural approach is to rebuild the UI whenever new data arrives. The correct approach is to compute a "state tuple" representing what the UI should show, compare it to `_last_state`, and only rebuild if the tuple has changed.

This was a real bug in MainMenu fixed with `_last_fw_state` debouncing.

**How to avoid:**
- Wrap every card-rebuilding call in a state comparison: `if new_state == self._last_state: return`.
- The state tuple should include all fields that affect the UI: connection status, device name, firmware version, etc.
- Only rebuild when the tuple actually changes.

**Warning signs:**
- Dropdowns snap closed immediately after being opened.
- Spinboxes lose focus after one second.
- Status labels flicker even when nothing has changed.

**Phase to address:** Phase 2 (configurator screen) — implement `_last_state` pattern from the start, not as a fix later.

---

### Pitfall 9: Mousewheel scroll handler bound globally (bind_all) gets stolen by last-initialized screen

**What goes wrong:**
`bind_all("<MouseWheel>", handler)` binds the handler to the entire Tkinter application, not just to the widget that called it. If multiple screen instances are created at startup (as OCC does — it creates all screen instances in `main()` before showing any of them), the last instance's `bind_all` call in `__init__` overwrites all previous ones. The wrong screen handles scroll events — guitar scroll works when on the drums screen and vice versa.

**Why it happens:**
`DEVICE_SCREEN_CLASSES` creates all screen instances at startup. Each `__init__` calls `bind_all` in `_build_ui()`. The last `__init__` to run wins.

This was a real bug fixed by moving `bind_all` to `show()` and adding `unbind_all` to `hide()`.

**How to avoid:**
- Never call `bind_all("<MouseWheel>", ...)` in `__init__` or `_build_ui()`.
- Call it in `show()` and call `unbind_all("<MouseWheel>")` in `hide()`.
- Apply this rule to any other application-wide event bindings.

**Warning signs:**
- Scroll works on the first screen shown but uses the wrong handler after switching screens.
- Debug print confirms that the wrong screen's `_on_mousewheel` fires.

**Phase to address:** Phase 2 (configurator screen) — follow the show/hide pattern from the start.

---

### Pitfall 10: `root.title()` and `root.config(menu=...)` called in `__init__` clobber other screens

**What goes wrong:**
All OCC screens share one root window. If a screen class sets the window title or menu bar inside `__init__`, it runs at construction time — which is before any screen is shown. Because all screens are constructed in sequence in `main()`, whichever `__init__` runs last sets the title/menu that appears when the application starts. The active screen (MainMenu) gets the wrong title and menu.

**Why it happens:**
Setting title and menu bar in `__init__` feels natural. It becomes wrong when multiple screen instances share one window and are all constructed at startup.

**How to avoid:**
- Never call `root.title()` or `root.config(menu=...)` in `__init__`.
- Store `self._menu_bar = tk.Menu(...)` in `__init__`, but apply it only in `show()` via `root.config(menu=self._menu_bar)`.
- Set window title in `show()` only.
- If the new screen has no menu bar, apply an empty menu in `show()` to clear the previous screen's menu: `root.config(menu=tk.Menu(root))`.

**Warning signs:**
- Main menu opens with the configurator title/menu instead of the main menu title.
- Menu bar from the retro screen appears while the main menu is showing.

**Phase to address:** Phase 2 (configurator screen) — follow the show/hide pattern from the start, before any testing.

---

### Pitfall 11: Analog trigger ADC range not validated — user can set min >= max

**What goes wrong:**
The analog trigger calibration flow (min/max ADC values) relies on the user setting min < max. If the user accidentally sets min >= max (e.g., both calibrated at the same physical position), the firmware's remapping code divides by `(max - min)` or produces inverted output. On a 12-bit ADC, a zero range causes a divide-by-zero in integer math, producing a garbage axis value. On the Pico this typically results in an axis stuck at maximum or minimum, not a crash.

**Why it happens:**
The guitar firmware has the same calculation. On the whammy the risk is lower because the sensor physically travels far. On triggers, especially if both endpoints are set from a "at rest" reading (user forgot to actuate), min and max can be identical.

**How to avoid:**
- In the configurator, prevent saving if `min >= max`: clamp before sending SET commands and show a warning.
- In the firmware, guard the remapping: if `max <= min`, output 0 (or center) rather than computing a bad division.
- The guitar whammy calibration code in EasyConfig uses a 20% deadzone inset (`deadzone = int(0.20 * range)`) and validates `range > 0` before applying calibration — copy this pattern.

**Warning signs:**
- Axis output stuck at full deflection despite trigger being at rest.
- Calibration values show min == max in GET_CONFIG response.

**Phase to address:** Phase 1 (firmware) for the guard, Phase 2 (configurator) for the UI validation.

---

### Pitfall 12: Build script not updated — new firmware omitted from the build pipeline

**What goes wrong:**
`build_all_firmware.bat` explicitly lists each firmware project (currently 6 steps). If pico-retro is not added as a step, the configurator EXE is built without the retro UF2 bundled. The firmware tile grid shows no retro tile. The user must manually locate and flash the UF2 file.

Similarly, `build_exe.bat` scans for `.uf2` files in the configurator folder. If the retro UF2 was not copied there by the build script, it is not bundled into the EXE. There is no build-time error — the tile is simply absent.

**Why it happens:**
The build script is not auto-discovering. Each firmware is a manually listed step. Adding a firmware directory does not automatically add it to the pipeline.

**How to avoid:**
- Add pico-retro as step 7 (or next) in `build_all_firmware.bat` at the same time the firmware directory is created.
- Follow the naming convention: `pico_retro_controller.uf2` → `Retro_Gamepad_Controller.uf2` (matching the hint used in `DEVICE_TYPE_UF2_HINTS`).
- Create a matching `.gif` file with the same base name as the UF2. The build script auto-discovers GIFs by matching the UF2 base name — a missing GIF shows only a placeholder icon, but no GIF for a new variant is easy to miss.
- Verify the tile appears in the firmware grid after building the EXE.

**Warning signs:**
- No retro tile in the firmware grid of the configurator.
- `build_exe.bat` log shows "No GIF found for Retro_Gamepad_Controller.uf2".
- Backup & Update shows "No matching UF2 firmware file found" for retro devices.

**Phase to address:** Phase 1 (firmware skeleton) — add the build step when the directory is created.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Copy guitar `config_serial.c` verbatim for retro | Faster prototype | Leaves guitar-specific keys (`tilt_mode`, `whammy_mode`, I2C) in retro firmware — configurator will send these SET commands during restore and get ERR responses | Never — strip guitar-specific keys before first commit |
| Reuse guitar `usb_descriptors.h` with only DEVICE_TYPE changed | One fewer file to write | Config PID collision if `CONFIG_MODE_PID` is not changed | Never — always assign a new PID |
| Skip `DEVICE_TYPE_UF2_HINTS` and `OCC_SUBTYPES` entries for now | Faster iteration | Retro device invisible to configurator's firmware card and backup flow | Only acceptable on day 1 of firmware bringup, must be resolved before any integration testing |
| Implement RetroApp scroll without `_last_state` debounce | Simpler initial code | Dropdown collapse bug becomes apparent only when testing with a device connected | Never — implement from the start |
| Omit `CONFIG_MAGIC` unique value | One fewer constant | If a user flashes retro firmware onto a Pico with guitar config in flash, it may boot with nonsense defaults before the checksum catches it | Never — always unique magic per variant |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Serial config port detection | Scanning only for known config PIDs (`0xF00D`, `0xF00E`) without adding the new retro PID | Add new config PID to the configurator's port scan list at the same time as firmware definition |
| Backup & Update restore | Pushing ALL keys from the backup JSON including guitar-specific ones that retro firmware does not handle | The restore loop already sends `SET:key=value` for all backed-up keys — retro firmware will respond `ERR:unknown key` for unrecognized keys. These errors are tolerable but noisy. Document which keys are retro-specific. |
| EasyConfig whammy calibration | Using the same calibration algorithm directly for trigger calibration without accounting for different travel range and resting position | Triggers rest at 0 (not midpoint); calibration should treat rest as minimum, full press as maximum, no invert logic needed |
| Config mode entry (magic vibration sequence) | Assuming the magic sequence triggers instantly | The configurator already handles the latency (up to 3s timeout for sequence detection), but new firmware must implement the same `MAGIC_STEP*` constants and detection logic |
| `find_uf2_for_device_type()` hint matching | UF2 filename not containing the hint substring from `DEVICE_TYPE_UF2_HINTS` | The hint is matched against the lowercase UF2 filename. Name the UF2 file so it contains a unique, unambiguous substring (e.g., "retro") and register that hint |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Rebuilding all UI widgets on every 1s poll | Dropdowns collapse, spinboxes lose focus, CPU spikes | `_last_state` tuple comparison — only rebuild on actual change | Immediately when any user tries to interact with a connected device |
| Serial reads without timeout in background thread | Thread hangs indefinitely if firmware stops responding, blocking the entire serial worker | Always use `timeout=` on `serial.Serial()` construction; use `read_until()` with timeout rather than blocking `readline()` | When firmware crashes or USB cable is pulled mid-session |
| `bind_all` in `__init__` with multiple screen instances | Wrong scroll handler active on some screens | Only bind in `show()`, unbind in `hide()` | Immediately, but only caught during multi-screen testing |

---

## "Looks Done But Isn't" Checklist

- [ ] **DEVTYPE routing:** Verify `RetroApp` appears (not guitar App, not error dialog) when retro controller connects — `DEVTYPE:retro_gamepad` must match `DEVICE_SCREEN_CLASSES` key exactly.
- [ ] **OCC_SUBTYPES coverage:** Verify main menu controller card shows retro device by confirming its XInput subtype is in `OCC_SUBTYPES` and `XINPUT_SUBTYPE_TO_DEVTYPE`.
- [ ] **Build pipeline inclusion:** Verify retro UF2 tile appears in FlashFirmwareScreen firmware grid after EXE build.
- [ ] **Config restore after firmware flash:** Verify all retro-specific keys restore correctly and guitar-specific keys in backup JSON produce only harmless `ERR:unknown key` responses (not crashes or partial saves).
- [ ] **Config mode port detection:** Verify `find_config_port()` finds the retro device using its new config PID.
- [ ] **Scroll and dropdown stability:** With retro device connected and configurator polling, verify dropdowns stay open and spinboxes retain focus for at least 5 seconds.
- [ ] **Trigger calibration guards:** Verify firmware handles `min >= max` gracefully (outputs 0, not a crash or stuck axis).
- [ ] **Title and menu bar:** Verify that when RetroApp is showing, the window title is correct, and when returning to MainMenu, its title and empty menu bar are restored.
- [ ] **Mousewheel:** Verify scroll works on RetroApp screen and not on MainMenu (no cross-screen bleed).
- [ ] **Magic sequence detection:** Verify that pressing the "Configure Controller" button on the main menu actually triggers config mode entry for the retro firmware (not just for guitar firmware).

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong DEVTYPE string | LOW | Update `DEVICE_TYPE` define in firmware header, rebuild, reflash. Update `DEVICE_SCREEN_CLASSES` key in configurator if mismatch is on the Python side. |
| Config struct magic collision | LOW | Define unique `CONFIG_MAGIC`, bump `CONFIG_VERSION`, rebuild, reflash. User must factory reset (DEFAULTS command or nuke.uf2) to clear corrupted flash. |
| XInput subtype not in OCC_SUBTYPES | LOW | Add subtype to `OCC_SUBTYPES` and `XINPUT_SUBTYPE_TO_DEVTYPE` in configurator.py, rebuild EXE. No firmware change needed. |
| Build script missing retro step | LOW | Add step to `build_all_firmware.bat`, rebuild EXE. Existing flash images are unaffected. |
| Poll race condition causing save failures | MEDIUM | Add `_backup_in_progress` flag pattern to RetroApp, rebuild EXE. Existing firmware unaffected. |
| Combo IntVar out of sync | MEDIUM | Add manual IntVar sync after all `combo.current()` calls in `_load_config()`. Requires EXE rebuild. Users with saved configs may need to re-save once after the fix. |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Missing DEVTYPE | Phase 1 (firmware skeleton) | Connect device, confirm RetroApp screen opens |
| Config struct magic collision | Phase 1 (firmware skeleton) | Flash onto Pico previously running guitar firmware, verify clean boot |
| XInput subtype collision or absence | Phase 1 (firmware skeleton) | Main menu controller card shows retro device correctly |
| Config mode PID collision | Phase 1 (firmware skeleton) | `find_config_port()` finds retro device only (not guitar) |
| Serial poll race condition | Phase 2 (configurator screen) | Save config while main menu poll is running — no PermissionError |
| STOP command to non-scanning firmware | Phase 2 (configurator screen) | Use detect, cancel, then save — no ERR in save response |
| Combo IntVar out of sync | Phase 2 (configurator screen) | Load config, save without changes, reload — values match |
| UI card rebuild on every poll | Phase 2 (configurator screen) | Hold dropdown open for 3 seconds with device connected — dropdown stays open |
| Mousewheel bind_all bleed | Phase 2 (configurator screen) | Navigate to RetroApp, scroll, navigate to MainMenu, confirm no scroll handler fires |
| title/menu in __init__ | Phase 2 (configurator screen) | Launch app, check window title on first screen shown |
| Analog trigger range validation | Phase 1 (firmware) + Phase 2 (configurator) | Set min == max in calibration, verify firmware outputs center, not garbage |
| Build script omission | Phase 1 (firmware skeleton) | Retro UF2 tile visible in firmware grid after EXE build |

---

## Sources

- `detailedcontext.md` — Comprehensive bug log including: poll race condition, STOP command guard, combo IntVar bug, bind_all scroll bug, title/menu in __init__, state-change debounce pattern, DEVTYPE routing, OCC_SUBTYPES, config magic/version, build script patterns
- `CLAUDE.md` — Architectural rules distilled from the same bugs: RoundedButton must be Canvas, combo `.current()` does not fire events, scroll state recalculation, never rebuild UI unless state changed, config_serial.c include ordering, LED_INPUT_COUNT fixed constant, DEVTYPE routing, OCC_SUBTYPES set, BLE connection parameters, build script *.spec deletion
- `Source Code/configurator/configurator.py` (lines 873–900, 15547–15561) — `DEVICE_TYPE_UF2_HINTS`, `XINPUT_SUBTYPE_TO_DEVTYPE`, `OCC_SUBTYPES`, `DEVICE_SCREEN_CLASSES` — the actual routing tables that new variants must register in
- `Source Code/pico-guitar-controller-wired/src/guitar_config.h` — Config struct versioning pattern, `CONFIG_MAGIC`, `CONFIG_VERSION`
- `Source Code/pico-guitar-controller-wired/src/usb_descriptors.h` — VID/PID constants, XInput subtype values, note that `0x05` suppresses axes
- `Source Code/pico-drums-wired/src/drum_config.h` — Second variant showing the same patterns (magic `"DRUM"`, version 3, `DEVICE_TYPE "drum_kit"`) confirming the pattern is consistent across variants
- `Source Code/configurator/build_exe.bat` — Build pipeline: auto-discovers UF2 by filename, requires GIF with same base name, nuke.uf2 handled separately
- `Source Code/build_all_firmware.bat` — Manual step list showing each variant must be explicitly added

---
*Pitfalls research for: Pico XInput firmware variants (pico-retro) + Tkinter configurator integration*
*Researched: 2026-03-19*
