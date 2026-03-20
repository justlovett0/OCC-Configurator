# Phase 2: Configurator Integration - Research

**Researched:** 2026-03-20
**Domain:** Python/Tkinter configurator extension, serial protocol expansion, firmware SCAN/MONITOR commands
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**GPIO Button Detection & Pin Assignment**
- Default GPIO assignments: Firmware ships with sensible GPIO defaults (DPad on GP0-GP3, buttons on GP4-GP13, triggers on GP26-GP27); users only reassign if using different pins
- DETECT mechanism: Clicking "Detect [Button]" starts a 10-second SCAN in the firmware. If no button press detected, auto-cancel with "timeout" message. User can also cancel manually.
- Pin editing: Users can both DETECT buttons AND manually edit GPIO pin numbers using custom dropdowns (like GuitarApp pattern)
- Button display: All 13 buttons appear as a single scrollable list (not grouped); each row shows button name, DETECT button, and GPIO pin dropdown
- Manual override UX: After detecting a pin, user can click the dropdown to manually select a different GPIO (0-27) if needed

**Analog Trigger Configuration (LT/RT)**
- Tab-based organization: LT and RT triggers are in separate tabs for clarity
- Mode-dependent UI: mode selector at top of each trigger tab
  - Digital mode: show only GPIO pin dropdown + DETECT button
  - Analog mode: show full analog suite (min/max sliders, EMA alpha, invert toggle, live monitoring)
- Analog calibration: min/max values are raw ADC 0-4095; EMA alpha is 0-100% (stored as 0-100 in firmware); invert toggle 0=normal, 1=inverted
- Live monitoring (analog only): "Enable Monitor Mode" toggle; show inline bars for real-time raw ADC and calibrated output (0-255) below min/max sliders; no monitoring for digital triggers

**Screen Organization & Navigation**
- Overall structure: Single scrollable Frame — device name section → button list → trigger tabs → menu bar
- Entry point: Main menu auto-detects pico-retro, shows "Advanced Configuration" button
- Back button: saves config (SAVE), reboots to play mode (REBOOT), navigates to main menu
- Menu bar: Full Advanced menu (Flash Firmware, BOOTSEL, Export/Import, Serial Debug) matching GuitarApp/DrumApp pattern

**Config Storage & Serialization**
- Struct fields: `int8_t pin_buttons[13]`, `int8_t pin_lt`, `pin_rt`, `uint8_t mode_lt/mode_rt`, `uint16_t lt_min, lt_max, rt_min, rt_max`, `uint8_t lt_invert, rt_invert`, `uint8_t lt_ema_alpha, rt_ema_alpha` (0-100%), `char device_name[32]`
- Device name: alphanumeric + space, max 20 chars, validated in both firmware + configurator
- Config backup/restore: automatic during firmware flash (existing OCC backup/restore thread pattern)

**Firmware Update Integration**
- UF2 discovery: Retro_Controller.uf2 and Retro_Controller_W.uf2 added to firmware tile grid via find_uf2_files() pattern
- Device routing: XINPUT_SUBTYPE_TO_DEVTYPE dict maps 0x01 → "pico_retro"; OCC_SUBTYPES includes 1
- GIF asset: Wired_Retro_Controller.gif must exist in configurator bundle
- Update UI: menu item shows both retro variants; backup/restore happens automatically

### Claude's Discretion
- Exact visual layout and spacing for button rows and trigger sections
- Specific font sizes and colors (use existing theme constants: BG_CARD, TEXT, ACCENT_BLUE, etc.)
- EMA alpha conversion formula (linear 0-100 or curve-based; match guitar implementation)
- Exact button row height and padding

### Deferred Ideas (OUT OF SCOPE)
- LED strip support for pico-retro
- Wireless/BLE configuration UI
- Advanced button remapping (chords, modifiers)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CFG-02 | Device naming — user can set/change device name (alphanumeric, max 20 chars, validated) | VALID_NAME_CHARS pattern + vcmd + firmware SET:device_name handler confirmed |
| CFG-03 | GPIO button mapping — interactive DETECT for each button (press, configurator records GPIO) | Requires SCAN/STOP/PIN: in retro firmware (critical gap — must add in Phase 2) |
| CFG-04 | Analog trigger detection — DETECT for LT/RT (pull/press, configurator records ADC pin) | Same SCAN mechanism; ADC pins 26-28; firmware validates analog pins 26-28 |
| CFG-05 | Analog/digital mode toggle — per-trigger "Analog" or "Digital" mode selection | SET:mode_lt, SET:mode_rt; firmware validates 0=digital, 1=analog |
| CFG-06 | Analog trigger monitor — real-time raw ADC + calibrated 0-255 bar graphs | Requires MONITOR_ADC in retro firmware (critical gap — must add in Phase 2) |
| CFG-07 | Min/max calibration UI — sliders to set trigger min/max; live output bar updates | SET:lt_min, SET:lt_max, SET:rt_min, SET:rt_max; 0-4095 range |
| CFG-08 | Smoothing control — EMA alpha slider 0-100% | SET:lt_ema_alpha, SET:rt_ema_alpha; firmware accepts 0-100 |
| CFG-09 | Invert toggle — per-trigger invert option | SET:lt_invert, SET:rt_invert; firmware accepts 0 or 1 |
| CFG-10 | Config backup/restore — automatic before firmware flash, restore via SET after flash | Existing _flash_firmware() pipeline; add pico_retro to DEVICE_SCREEN_CLASSES |
| CFG-11 | Firmware update integration — add pico-retro to existing update pipeline | DEVICE_TYPE_UF2_HINTS["pico_retro"]="retro" already present; Wired_Retro_Controller.gif exists |
| USB-01 | Config mode PID 0xF00F distinct from guitar (0xF00D) and drums (0xF00E) | PID already set in Phase 1 firmware; configurator find_config_port() must recognise 0xF00F |
</phase_requirements>

---

## Summary

Phase 2 builds the `RetroApp` configurator screen and must also extend the pico-retro firmware with two serial protocol commands that were intentionally omitted in Phase 1. The configurator side is a straightforward adaptation of the existing `GuitarApp`/`DrumApp` patterns — same scrollable card layout, same DETECT threading model, same device name field. The less-obvious dependency is that `retro_config_serial.c` currently has no `SCAN`/`STOP`/`PIN:` or `MONITOR_ADC` commands, which are both required by the DETECT (CFG-03/04) and live monitoring (CFG-06) requirements. These must be added to the firmware as part of this phase, following the `pico-pedal` implementation exactly.

The device routing infrastructure is already partially in place: `XINPUT_SUBTYPE_TO_DEVTYPE[1]="pico_retro"`, `OCC_SUBTYPES` includes `1`, and `DEVICE_TYPE_UF2_HINTS["pico_retro"]="retro"`. The only missing routing step is adding `"pico_retro": RetroApp` to `DEVICE_SCREEN_CLASSES` and instantiating `RetroApp` in `_build_device_screens()`. `Wired_Retro_Controller.gif` already exists in the configurator bundle.

EMA alpha treatment differs between guitar and retro: guitar uses a 10-level lookup table (EMA_ALPHA_TABLE with internal values 10-255, 0-9 slider) translated to proprietary firmware values, while retro stores the user-facing 0-100 value directly. The RetroApp EMA slider is simpler — a linear 0-100 ttk.Scale maps directly to `SET:lt_ema_alpha=N`.

**Primary recommendation:** Implement in three work streams: (1) firmware additions to `retro_config_serial.c` (SCAN+MONITOR_ADC), (2) RetroApp class construction in configurator.py, (3) device routing hookup in DEVICE_SCREEN_CLASSES and main().

---

## Standard Stack

### Core (all already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tkinter | stdlib | UI widgets, root window, Canvas | Project-wide UI framework |
| ttk | stdlib | Scrollbar, Combobox, Scale | Themed extension of tkinter |
| threading | stdlib | Background SCAN/MONITOR threads | Non-blocking serial ops |
| json | stdlib | Export/import config files | Human-readable config backup |

### Existing Internal Patterns (must reuse)
| Pattern | Location | Purpose |
|---------|----------|---------|
| `RoundedButton` | configurator.py | All action buttons (Canvas subclass, NOT Frame) |
| `CustomDropdown` | configurator.py | GPIO pin selectors (wraps ttk.Combobox) |
| `LiveBarGraph` | configurator.py | Real-time ADC/calibrated value bars |
| `PicoSerial` | configurator.py | All serial communication (PING, GET_CONFIG, SET, SAVE, SCAN, MONITOR_ADC) |
| `VALID_NAME_CHARS` | configurator.py line 936 | `set(string.ascii_letters + string.digits + ' ')` |
| `BG_CARD, TEXT, ACCENT_BLUE, BORDER, BG_INPUT` | configurator.py | Dark theme constants |

**No new pip dependencies required.**

---

## Architecture Patterns

### Recommended RetroApp Structure
```
class RetroApp:
    __init__()        # PicoSerial, tk.Vars, widget tracking dicts
    _build_menu()     # Advanced cascade menu (copy DrumApp._build_menu)
    _build_ui()       # Connection card + scrollable content
    _build_buttons_section()   # 13-button DETECT list
    _build_triggers_section()  # ttk.Notebook LT/RT tabs
    _build_lt_tab()   # mode selector → conditional analog/digital UI
    _build_rt_tab()   # same pattern as LT
    _make_device_name_section()  # copy App._make_device_name_section()
    _load_config()    # parse GET_CONFIG → populate tk.Vars
    _push_all_values()  # SET all keys before SAVE
    _go_back()        # _push_all_values → SAVE → REBOOT → on_back()
    _connect_clicked()  # connect → _load_config → enable controls
    show() / hide()   # pack/pack_forget + mousewheel binding
```

### Pattern 1: Button DETECT Threading
**What:** Background daemon thread sends SCAN, reads PIN: lines, calls back on main thread via `root.after(0, callback)`. Follows the EasyConfig / GuitarApp pattern exactly.

**Critical finding:** `retro_config_serial.c` currently does NOT implement SCAN/STOP/PIN:. Must add these commands to the firmware (follow `pico-pedal/src/pedal_config_serial.c` `run_scan()` function).

**Firmware SCAN implementation to add (from pedal pattern):**
```c
// In config_serial_loop, add:
else if (strcmp(line, "SCAN") == 0) {
    run_scan(config);
}

// run_scan() polls all GPIO 0-28 for transitions,
// sends PIN:<pin> on press, stops on "STOP\n" from host.
// Must call gpio_pull_up + gpio_set_dir_in on all pins before scanning.
```

**Configurator DETECT thread (copy from GuitarApp _wire_dpad_cell lines 3095-3163):**
```python
# Source: configurator.py lines 3000-3030 (EasyConfig DETECT pattern)
def _thread():
    try:
        self.pico.start_scan()   # sends SCAN, waits for OK
        while self.scanning:
            line = self.pico.read_scan_line(0.1)
            if line and line.startswith("PIN:"):
                pin = int(line[4:])
                if 0 <= pin <= 27:
                    self.pico.stop_scan()
                    self.scanning = False
                    self.root.after(0, lambda p=pin: _on_detected(p))
                    return
    except Exception as exc:
        self.root.after(0, lambda e=str(exc): _on_error(e))

threading.Thread(target=_thread, daemon=True).start()
```

**Timeout (10-second DETECT):** Use `time.time()` deadline inside the thread loop. After 10s, call `pico.stop_scan()`, `self.scanning = False`, and `root.after(0, lambda: _on_timeout())`.

### Pattern 2: Live Analog Monitoring
**What:** MONITOR_ADC command streams `MVAL:<raw_adc>` lines. PicoSerial.drain_monitor_latest() drains the buffer and returns the most recent value only (prevents backlog).

**Critical finding:** `retro_config_serial.c` does NOT implement MONITOR_ADC. Must add following `pico-pedal/src/pedal_config_serial.c` `run_monitor_adc()`.

**Firmware MONITOR_ADC to add:**
```c
// In config_serial_loop, add:
else if (strncmp(line, "MONITOR_ADC:", 12) == 0) {
    int pin = atoi(line + 12);
    run_monitor_adc(pin);
}

// run_monitor_adc() reads ADC at ~50Hz, sends "MVAL:<val>\r\n",
// stops on "STOP\n" from host. Validate pin 26-28.
```

**Configurator monitor pattern (copy from GuitarApp _start_monitor lines 2913-2939):**
```python
# Source: configurator.py lines 2913-2939
def _start_monitor(self, pin, bar):
    self._monitoring = True
    def _thread():
        try:
            self.pico.start_monitor_adc(pin)
            while self._monitoring:
                val, _ = self.pico.drain_monitor_latest(0.05)
                if val is not None:
                    self.root.after(0, lambda v=val: bar.set_value(v))
        except Exception:
            pass
    self._monitor_thread = threading.Thread(target=_thread, daemon=True)
    self._monitor_thread.start()
```

### Pattern 3: GPIO Pin Dropdown
**What:** `CustomDropdown` populated with values `["-1 (disabled)", "0", "1", ..., "27"]` for digital buttons; `["26", "27", "28", "-1 (disabled)"]` for analog trigger pins.

**Key rule from CLAUDE.md:** Combo box `.current()` does NOT fire `<<ComboboxSelected>>` — always manually sync the backing `tk.IntVar` after calling `.current()`.

```python
# Source: GuitarApp _make_button_row pattern (lines ~8700-8755)
pin_var = tk.IntVar(value=default_pin)
combo = CustomDropdown(row_frame, values=GPIO_OPTIONS, state="readonly")
combo.current(GPIO_OPTIONS.index(str(default_pin)))
pin_var.set(default_pin)  # manual sync — .current() does NOT fire <<ComboboxSelected>>
```

### Pattern 4: Mode-Dependent Tab UI
**What:** ttk.Notebook with LT and RT tabs. Each tab rebuilds its inner content when the mode Radiobutton changes.

```python
nb = ttk.Notebook(trigger_frame)
lt_tab = tk.Frame(nb, bg=BG_CARD)
rt_tab = tk.Frame(nb, bg=BG_CARD)
nb.add(lt_tab, text="LT Trigger")
nb.add(rt_tab, text="RT Trigger")
```

Inside each tab, use a `tk.StringVar` for mode ("digital"/"analog"). When mode changes, pack/pack_forget the analog-only widgets (min/max sliders, EMA slider, invert checkbox, monitor section). This avoids destroying/rebuilding widgets — only show/hide them.

### Pattern 5: Device Name Field
**What:** tk.Entry with validate="key" vcmd that enforces VALID_NAME_CHARS and max 20 chars.

```python
# Source: configurator.py lines 9245-9250 (App._make_device_name_section)
_vcmd = (self.root.register(
    lambda P: len(P) <= 20 and all(c in VALID_NAME_CHARS for c in P)), '%P')
self._name_entry = tk.Entry(row, textvariable=self.device_name,
    bg=BG_INPUT, fg=TEXT, insertbackground=TEXT, font=(FONT_UI, 10),
    width=30, bd=1, relief="solid", validate="key", validatecommand=_vcmd)
```

Push: `name = ''.join(c for c in self.device_name.get() if c in VALID_NAME_CHARS).strip()[:20]`

### Pattern 6: Device Routing Hookup
**What:** Three one-line additions in configurator.py to complete pico-retro routing:

```python
# 1. In DEVICE_SCREEN_CLASSES dict (line ~15558):
DEVICE_SCREEN_CLASSES = {
    ...
    "pico_retro": RetroApp,   # ADD THIS
}

# 2. In _build_device_screens() function (line ~15866):
# No change needed — loop over DEVICE_SCREEN_CLASSES automatically instantiates RetroApp

# 3. find_config_port() must recognise PID 0xF00F (USB-01):
# Verify 0xF00F is in the config-mode PID scan list
```

### Recommended File Layout for RetroApp
```
configurator.py
├── class RetroApp          # ~600-800 lines, after PedalApp class
│   ├── RETRO_BUTTON_DEFS  # list of (key, label) for 13 buttons
│   ├── RETRO_KEY_MAP       # key → SET command key (btn0..btn12, pin_lt, etc.)
│   ├── __init__            # vars, build_menu, build_ui
│   ├── _build_menu         # copy DrumApp._build_menu verbatim
│   ├── _build_ui           # conn card + scrollable content
│   └── ...
└── DEVICE_SCREEN_CLASSES   # add "pico_retro": RetroApp
```

### Anti-Patterns to Avoid
- **Don't use Toplevel for screens:** All screens are tk.Frame instances sharing root window (CLAUDE.md)
- **Don't call `.current()` and expect ComboboxSelected:** Always sync backing IntVar manually (CLAUDE.md)
- **Don't rebuild UI cards on every poll:** Only rebuild if backing state tuple changed (CLAUDE.md)
- **Don't set geometry in `__init__`:** Set title and menu only in `show()`, never `__init__` (CLAUDE.md)
- **Don't call `_update_scroll_state()` at init time only:** Recalculate after every layout change (CLAUDE.md)
- **Don't use RoundedButton as tk.Frame subclass:** RoundedButton is a tk.Canvas subclass (CLAUDE.md)
- **Don't add LED support:** Deferred to v2 — out of scope for this phase

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Serial communication | Custom read/write | `PicoSerial` (existing) | Handles drain, timeouts, retry, buffer flush |
| Scan buffer drain | Custom loop | `pico.drain_monitor_latest()` | Prevents MVAL backlog accumulation |
| GPIO pin scan | New serial protocol | SCAN/STOP/PIN: pattern from pedal (copy run_scan()) | Battle-tested, configurator already speaks this protocol |
| ADC monitoring | New serial protocol | MONITOR_ADC/MVAL: from pedal (copy run_monitor_adc()) | Configurator PicoSerial.start_monitor_adc() already handles this |
| Rounded action buttons | Custom Canvas widget | `RoundedButton` (existing) | Handles state, colors, disabled appearance |
| Pin dropdowns | Custom list widget | `CustomDropdown` (existing) | Correct keyboard nav, style, state management |
| Live bar graphs | Custom Canvas drawing | `LiveBarGraph` (existing) | Already handles ADC value normalization |
| UF2 discovery | New file scanner | `find_uf2_files()` (existing) | Handles MEIPASS bundle and dev paths |
| Device name validation | Regex or custom | `VALID_NAME_CHARS` + vcmd pattern | Already tested across Guitar/Drum/Pedal apps |

---

## Common Pitfalls

### Pitfall 1: SCAN/MONITOR_ADC Not In Retro Firmware
**What goes wrong:** RetroApp calls `pico.start_scan()` or `pico.start_monitor_adc()`, firmware responds `ERR:unknown command`, DETECT never completes.
**Why it happens:** `retro_config_serial.c` comment line 13 explicitly says "pico-retro has no LEDs and no SCAN/STOP commands". Neither SCAN nor MONITOR_ADC were implemented in Phase 1.
**How to avoid:** Phase 2 must add both commands to `retro_config_serial.c` before implementing the configurator DETECT/monitor UI. The implementation must exactly follow `pico-pedal/src/pedal_config_serial.c` (run_scan and run_monitor_adc functions).
**Warning signs:** `ERR:unknown command` in serial debug console when clicking Detect.

### Pitfall 2: Analog Trigger Pin Validation
**What goes wrong:** User DETECTs a digital button GPIO (0-22) for an analog trigger; firmware responds `ERR:analog pin must be 26-28`.
**Why it happens:** Firmware validates analog pin range (26-28) when mode_lt/mode_rt is INPUT_MODE_ANALOG. SCAN returns PIN: for any pressed GPIO.
**How to avoid:** In the trigger DETECT thread, only accept pins 26-28 when mode is "analog". Accept 0-27 when mode is "digital".

### Pitfall 3: Concurrent SCAN and MONITOR_ADC
**What goes wrong:** User has monitoring enabled and then clicks Detect — two firmware streaming sessions conflict.
**Why it happens:** SCAN and MONITOR_ADC are mutually exclusive streaming modes in firmware.
**How to avoid:** Before calling `pico.start_scan()`, check `self._monitoring` and stop it first (call `pico.stop_monitor()`, set `self._monitoring = False`). GuitarApp does this — see lines 3233-3238.

### Pitfall 4: EMA Alpha Range Mismatch
**What goes wrong:** Guitar's EMA uses a 10-level lookup table (EMA_ALPHA_TABLE), but retro uses linear 0-100 directly. Cross-pasting guitar EMA logic into RetroApp breaks the slider semantics.
**Why it happens:** Guitar firmware stores proprietary internal EMA values (10-255); retro firmware stores user-facing 0-100 directly (confirmed in `retro_config_serial.c` — `lt_ema_alpha must be 0-100`).
**How to avoid:** RetroApp EMA slider: `ttk.Scale(from_=0, to=100, variable=self.lt_ema_alpha_var)`. Push: `self.pico.set_value("lt_ema_alpha", str(self.lt_ema_alpha_var.get()))`. No lookup table.

### Pitfall 5: Scroll State After Tab Show/Hide
**What goes wrong:** Showing/hiding analog-only widgets when mode changes doesn't trigger scroll recalculation.
**Why it happens:** CLAUDE.md rule: "Scroll state must be recalculated (`_update_scroll_state()`) after every layout change."
**How to avoid:** Call `self._update_scroll_state()` at the end of every mode-change callback that pack/pack_forgets widgets.

### Pitfall 6: Device Routing — DEVICE_SCREEN_CLASSES Not Updated
**What goes wrong:** Configurator routes pico-retro to "unsupported device" error even though DEVTYPE:pico_retro is returned.
**Why it happens:** `XINPUT_SUBTYPE_TO_DEVTYPE` and `OCC_SUBTYPES` already include pico_retro (confirmed in source), but `DEVICE_SCREEN_CLASSES` does NOT have `"pico_retro"` entry (line 15558-15564 — only guitar, drums, pedal).
**How to avoid:** Add `"pico_retro": RetroApp` to DEVICE_SCREEN_CLASSES. Confirm `find_config_port()` includes PID 0xF00F in its scan list.

### Pitfall 7: USB-01 — PID 0xF00F in find_config_port()
**What goes wrong:** Config mode device not auto-detected because 0xF00F missing from port scan list.
**Why it happens:** `find_config_port()` scans for known config-mode PIDs. If 0xF00F is not listed, pico-retro won't be found in config mode.
**How to avoid:** Search configurator.py for `0xF00D` to find the PID list and verify 0xF00F is already present.

---

## Code Examples

### SCAN Implementation in retro_config_serial.c (from pedal pattern)
```c
// Source: pico-pedal/src/pedal_config_serial.c run_scan()
static void run_scan(retro_config_t *config) {
    // Pull all GPIOs up, set as input
    bool pin_inited[29] = {false};
    bool prev_state[29] = {false};
    for (int pin = 0; pin < 29; pin++) {
        if (pin == 23 || pin == 24 || pin == 25) continue; // skip reserved
        gpio_init(pin);
        gpio_set_dir(pin, GPIO_IN);
        gpio_pull_up(pin);
        pin_inited[pin] = true;
        prev_state[pin] = !gpio_get(pin);
    }
    serial_writeln("OK");
    char line[64]; int line_pos = 0;
    char out[32];
    absolute_time_t deadline = make_timeout_time_ms(10000); // 10s timeout
    while (!time_reached(deadline)) {
        tud_task();
        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                line[line_pos] = '\0'; line_pos = 0;
                if (strcmp(line, "STOP") == 0) {
                    serial_writeln("OK"); return;
                }
            } else if (line_pos < 63) { line[line_pos++] = c; }
        }
        for (int pin = 0; pin < 29; pin++) {
            if (!pin_inited[pin]) continue;
            bool pressed = !gpio_get(pin);
            if (pressed && !prev_state[pin]) {
                snprintf(out, sizeof(out), "PIN:%d", pin);
                serial_writeln(out);
            }
            prev_state[pin] = pressed;
        }
        sleep_ms(10);
    }
    serial_writeln("TIMEOUT");
}
```

### MONITOR_ADC Implementation in retro_config_serial.c (from pedal pattern)
```c
// Source: pico-pedal/src/pedal_config_serial.c run_monitor_adc()
static void run_monitor_adc(int pin) {
    if (pin < 26 || pin > 28) {
        serial_writeln("ERR:invalid ADC pin (must be 26-28)");
        return;
    }
    adc_init();
    adc_gpio_init(pin);
    adc_select_input(pin - 26);
    serial_writeln("OK");
    char cmd_buf[32]; int cmd_pos = 0;
    char out[32];
    while (true) {
        tud_task();
        while (tud_cdc_available()) {
            char c = (char)tud_cdc_read_char();
            if (c == '\n' || c == '\r') {
                cmd_buf[cmd_pos] = '\0'; cmd_pos = 0;
                if (strcmp(cmd_buf, "STOP") == 0) {
                    serial_writeln("OK"); return;
                }
            } else if (cmd_pos < 31) { cmd_buf[cmd_pos++] = c; }
        }
        uint16_t val = adc_read();
        snprintf(out, sizeof(out), "MVAL:%u", val);
        serial_writeln(out);
        sleep_ms(20); // ~50Hz
    }
}
```

### Config Key Mapping for RetroApp
```python
# Source: retro_config_serial.c GET_CONFIG response lines 62-87
# Key → SET command → tk.Var pattern
RETRO_BUTTON_DEFS = [
    ("btn0",  "D-Pad Up"),     # BTN_IDX_DPAD_UP
    ("btn1",  "D-Pad Down"),   # BTN_IDX_DPAD_DOWN
    ("btn2",  "D-Pad Left"),   # BTN_IDX_DPAD_LEFT
    ("btn3",  "D-Pad Right"),  # BTN_IDX_DPAD_RIGHT
    ("btn4",  "A"),            # BTN_IDX_A
    ("btn5",  "B"),            # BTN_IDX_B
    ("btn6",  "X"),            # BTN_IDX_X
    ("btn7",  "Y"),            # BTN_IDX_Y
    ("btn8",  "Start"),        # BTN_IDX_START
    ("btn9",  "Select"),       # BTN_IDX_SELECT
    ("btn10", "Guide"),        # BTN_IDX_GUIDE
    ("btn11", "LB"),           # BTN_IDX_LB
    ("btn12", "RB"),           # BTN_IDX_RB
]
# All 13 use SET:btn0=<pin> through SET:btn12=<pin>
```

### _push_all_values for RetroApp
```python
def _push_all_values(self):
    # 13 digital buttons
    for key, _ in RETRO_BUTTON_DEFS:
        self.pico.set_value(key, str(self._pin_vars[key].get()))

    # Trigger modes
    self.pico.set_value("mode_lt", str(self._mode_lt.get()))
    self.pico.set_value("mode_rt", str(self._mode_rt.get()))

    # Trigger pins
    self.pico.set_value("pin_lt", str(self._pin_lt.get()))
    self.pico.set_value("pin_rt", str(self._pin_rt.get()))

    # Calibration
    self.pico.set_value("lt_min", str(self._lt_min.get()))
    self.pico.set_value("lt_max", str(self._lt_max.get()))
    self.pico.set_value("rt_min", str(self._rt_min.get()))
    self.pico.set_value("rt_max", str(self._rt_max.get()))

    # EMA (0-100 linear — NOT a lookup table like GuitarApp)
    self.pico.set_value("lt_ema_alpha", str(self._lt_ema.get()))
    self.pico.set_value("rt_ema_alpha", str(self._rt_ema.get()))

    # Invert
    self.pico.set_value("lt_invert", "1" if self._lt_invert.get() else "0")
    self.pico.set_value("rt_invert", "1" if self._rt_invert.get() else "0")

    # Debounce
    self.pico.set_value("debounce", str(self._debounce.get()))

    # Device name (validated)
    name = ''.join(c for c in self.device_name.get() if c in VALID_NAME_CHARS).strip()
    self.pico.set_value("device_name", (name or "Retro Controller")[:20])
```

### _load_config for RetroApp
```python
def _load_config(self):
    cfg = self.pico.get_config()
    # Buttons
    for key, _ in RETRO_BUTTON_DEFS:
        self._pin_vars[key].set(int(cfg.get(key, -1)))
    # Triggers
    self._mode_lt.set(int(cfg.get("mode_lt", 0)))
    self._mode_rt.set(int(cfg.get("mode_rt", 0)))
    self._pin_lt.set(int(cfg.get("pin_lt", 26)))
    self._pin_rt.set(int(cfg.get("pin_rt", 27)))
    self._lt_min.set(int(cfg.get("lt_min", 0)))
    self._lt_max.set(int(cfg.get("lt_max", 4095)))
    self._rt_min.set(int(cfg.get("rt_min", 0)))
    self._rt_max.set(int(cfg.get("rt_max", 4095)))
    self._lt_ema.set(int(cfg.get("lt_ema_alpha", 0)))
    self._rt_ema.set(int(cfg.get("rt_ema_alpha", 0)))
    self._lt_invert.set(bool(int(cfg.get("lt_invert", 0))))
    self._rt_invert.set(bool(int(cfg.get("rt_invert", 0))))
    self._debounce.set(int(cfg.get("debounce_ms", 5)))
    self.device_name.set(cfg.get("device_name", "Retro Controller"))
    # Update mode-dependent tab UI
    self._refresh_lt_tab()
    self._refresh_rt_tab()
    self._update_scroll_state()
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Guitar EMA lookup table (10-level, 255=no smoothing) | Retro EMA 0-100 linear (0=no smoothing, 100=max) | Simpler slider, no translation layer |
| EasyConfig DETECT (wizard-style, one button at a time) | RetroApp DETECT (single scrollable list, detect any button in-place) | Users can re-detect individual buttons without page navigation |
| Guitar whammy monitor (show after auto-detect only) | Retro trigger monitor (explicit toggle, show for analog mode regardless) | Users can see live values while manually adjusting sliders |

**Already done (Phase 1):**
- `XINPUT_SUBTYPE_TO_DEVTYPE[1] = "pico_retro"` — confirmed present at line 893
- `OCC_SUBTYPES` includes `1` — confirmed at line 898
- `DEVICE_TYPE_UF2_HINTS["pico_retro"] = "retro"` — confirmed at line 884
- `Wired_Retro_Controller.gif` exists in configurator directory

**Not done (Phase 2 must do):**
- SCAN/STOP/PIN: in `retro_config_serial.c`
- MONITOR_ADC/MVAL: in `retro_config_serial.c`
- `RetroApp` class in `configurator.py`
- `"pico_retro": RetroApp` in `DEVICE_SCREEN_CLASSES`
- Verify `find_config_port()` includes PID 0xF00F

---

## Open Questions

1. **Does `find_config_port()` already include PID 0xF00F?**
   - What we know: PID 0xF00F was set in Phase 1 firmware. The configurator must recognise it to auto-connect in config mode.
   - What's unclear: The PID scan list in find_config_port() was not audited in this research.
   - Recommendation: Planner must include a task to search for `0xF00D` in configurator.py (the guitar config PID), find the PID scan list, and verify/add 0xF00F.

2. **SCAN timeout handling — configurator vs firmware?**
   - What we know: CONTEXT.md says "10-second SCAN; auto-cancel with timeout message."
   - What's unclear: The timeout can be in firmware (run_scan() uses make_timeout_time_ms(10000)) or in configurator thread (time.time() deadline). Both pedal and guitar implement timeout in the thread, not firmware.
   - Recommendation: Implement 10s timeout in the DETECT thread (configurator side). Firmware SCAN sends TIMEOUT when its own deadline passes — configurator handles both TIMEOUT message and its own thread deadline.

3. **Calibrated 0-255 bar in live monitor — firmware or configurator calculation?**
   - What we know: CFG-06 requires "calibrated output (0-255) bar." MONITOR_ADC streams raw ADC (0-4095).
   - What's unclear: The calibrated value can be computed in the configurator (using current lt_min/lt_max/lt_invert vars) or streamed from firmware.
   - Recommendation: Compute in configurator. Raw ADC comes from MONITOR_ADC; configurator applies the same min/max/invert formula used in firmware to produce the 0-255 value in real time. This avoids a firmware protocol change and lets the bar update instantly as sliders move.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None detected — no test files in repository |
| Config file | None — Wave 0 must create |
| Quick run command | `python -m pytest tests/ -x -q` (after Wave 0 setup) |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CFG-02 | Device name validation (VALID_NAME_CHARS, max 20) | unit | `pytest tests/test_retro_app.py::test_device_name_validation -x` | Wave 0 |
| CFG-03 | DETECT thread completes on PIN: response | unit | `pytest tests/test_retro_app.py::test_detect_button -x` | Wave 0 |
| CFG-04 | Trigger DETECT accepts only 26-28 for analog mode | unit | `pytest tests/test_retro_app.py::test_trigger_detect_pin_range -x` | Wave 0 |
| CFG-05 | Mode toggle updates UI visibility | unit | `pytest tests/test_retro_app.py::test_mode_toggle -x` | Wave 0 |
| CFG-06 | Live monitor starts/stops correctly | unit | `pytest tests/test_retro_app.py::test_monitor_lifecycle -x` | Wave 0 |
| CFG-07 | Min/max sliders push correct SET commands | unit | `pytest tests/test_retro_app.py::test_calibration_push -x` | Wave 0 |
| CFG-08 | EMA slider 0-100 maps directly to lt_ema_alpha | unit | `pytest tests/test_retro_app.py::test_ema_push -x` | Wave 0 |
| CFG-09 | Invert toggle pushes 0 or 1 | unit | `pytest tests/test_retro_app.py::test_invert_push -x` | Wave 0 |
| CFG-10 | _push_all_values sends all required SET keys | unit | `pytest tests/test_retro_app.py::test_push_all_values -x` | Wave 0 |
| CFG-11 | DEVICE_SCREEN_CLASSES contains pico_retro | unit | `pytest tests/test_retro_app.py::test_routing -x` | Wave 0 |
| USB-01 | PID 0xF00F in find_config_port() scan list | unit | `pytest tests/test_retro_app.py::test_config_pid -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_retro_app.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_retro_app.py` — covers all CFG-02 through CFG-11 and USB-01
- [ ] `tests/conftest.py` — shared fixtures (mock PicoSerial, mock tk.Tk root)
- [ ] Framework install: `pip install pytest` — if not present

---

## Sources

### Primary (HIGH confidence)
- `Source Code/configurator/configurator.py` lines 8138-8300 — App class constructor, state vars, widget tracking
- `Source Code/configurator/configurator.py` lines 2970-3163 — DETECT threading pattern (EasyConfig + DPad wiring)
- `Source Code/configurator/configurator.py` lines 2913-2939 — _start_monitor, monitoring thread
- `Source Code/configurator/configurator.py` lines 9228-9254 — _make_device_name_section, VALID_NAME_CHARS vcmd
- `Source Code/configurator/configurator.py` lines 12009-12220 — DrumApp class structure, _build_menu pattern
- `Source Code/configurator/configurator.py` lines 874-898 — DEVICE_TYPE_UF2_HINTS, XINPUT_SUBTYPE_TO_DEVTYPE, OCC_SUBTYPES
- `Source Code/configurator/configurator.py` lines 15557-15564 — DEVICE_SCREEN_CLASSES (pico_retro NOT present)
- `Source Code/pico-retro/src/retro_config_serial.c` — All SET keys, GET_CONFIG response format, confirmed no SCAN/MONITOR
- `Source Code/pico-retro/src/retro_config.h` — retro_config_t struct, button enums, DEVICE_NAME_MAX
- `Source Code/pico-pedal/src/pedal_config_serial.c` — SCAN/STOP/PIN: and MONITOR_ADC reference implementations

### Secondary (MEDIUM confidence)
- `Source Code/configurator/configurator.py` lines 10601-10657 — GuitarApp _push_all_values (adaptation model)
- `Source Code/configurator/configurator.py` lines 10365-10600 — GuitarApp _load_config (adaptation model)
- `.planning/phases/01-firmware-foundation/01-CONTEXT.md` lines 84-101 — Phase 1 serial protocol decisions

### Tertiary (LOW confidence)
- None — all findings verified against source code directly.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all patterns verified in existing configurator.py source
- Architecture: HIGH — GuitarApp and DrumApp patterns read directly; retro_config_serial.c read in full
- Pitfalls: HIGH — SCAN/MONITOR gap confirmed by reading retro_config_serial.c source; not inferred
- Firmware commands: HIGH — pedal implementation read in full as reference

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (30 days — stable Python/Tkinter/RP2040 stack)
