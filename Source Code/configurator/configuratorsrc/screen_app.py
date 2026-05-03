import sys, os, time, threading, json, datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .constants import (BG_MAIN, BG_CARD, BG_INPUT, BG_HOVER, BORDER, TEXT, TEXT_DIM,
                         TEXT_HEADER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
                         DIGITAL_PINS, DIGITAL_PIN_LABELS, ANALOG_PINS,
                         ANALOG_PIN_LABELS, I2C0_SDA_PINS, I2C0_SCL_PINS, I2C_SDA_LABELS,
                         I2C_SCL_LABELS, I2C_MODEL_LABELS, I2C_MODEL_VALUES,
                         ADXL345_AXIS_LABELS, MAX_LEDS, VALID_NAME_CHARS, OCC_SUBTYPES,
                         GUITAR_PROFILE_DEFS)
from .fonts import FONT_UI, APP_VERSION
from .widgets import (RoundedButton, HelpButton, HelpDialog, CustomDropdown,
                       SpeedSlider, LiveBarGraph, LiveBarGraphVertical, CalibratedBarGraph,
                       _help_text)
from .serial_comms import PicoSerial
from .firmware_utils import (flash_uf2_with_reboot, enter_bootsel_for,
                              find_uf2_files, find_uf2_for_device_type,
                              get_bundled_fw_date_str, find_rpi_rp2_drive)
from .xinput_utils import (XINPUT_AVAILABLE, ERROR_SUCCESS, xinput_get_connected,
                           MAGIC_STEPS, xinput_send_vibration)
from .utils import (_ask_wired_or_wireless, _bind_global_mousewheel,
                     _center_window, _centered_dialog, _find_preset_configs,
                     _make_flash_popup, _mousewheel_units,
                     _signal_unavailable_message,
                     _unbind_global_mousewheel, CONTROLLER_SIGNAL_LABEL,
                     HOST_SYSTEM_LABEL, PLAY_MODE_LABEL)

MAX_GUITAR_LED_INPUT_COUNT = max(
    len(profile["led_input_names"]) + 2 for profile in GUITAR_PROFILE_DEFS.values()
)
LED_DATA_PINS = [3, 7, 19, 23]
LED_CLOCK_PINS = [2, 6, 18, 22]
LED_PIN_COMBO_STYLE = "LedPin.TCombobox"
class App:
    def __init__(self, root, on_back=None, guitar_profile="standard"):
        self.root = root
        self._on_back = on_back
        self._guitar_profile_key = guitar_profile
        self._apply_guitar_profile(guitar_profile)
        # Title is set in show() so it doesn't get overwritten by other screens at startup
        self.root.configure(bg=BG_MAIN)
        # Geometry is applied in show() so it doesn't clobber other screens at startup

        self.pico = PicoSerial()
        self.scanning = False
        self.scan_target = None

        # Config variables
        self.pin_vars = {}
        self.enable_vars = {}
        self.tilt_mode = tk.StringVar(value="digital")
        self.tilt_pin = tk.IntVar(value=9)
        self.tilt_enabled = tk.BooleanVar(value=True)
        self.whammy_mode = tk.StringVar(value="analog")
        self.whammy_pin = tk.IntVar(value=26)
        self.whammy_enabled = tk.BooleanVar(value=True)
        self.debounce_var = tk.IntVar(value=5)

        # Sensitivity (min/max ADC values, 0-4095)
        self.tilt_min = tk.IntVar(value=0)
        self.tilt_max = tk.IntVar(value=4095)
        self.whammy_min = tk.IntVar(value=0)
        self.whammy_max = tk.IntVar(value=4095)

        # Axis inversion
        self.tilt_invert   = tk.BooleanVar(value=False)
        self.whammy_invert = tk.BooleanVar(value=False)

        # Raw ADC snapshots for guided whammy calibration (not persisted to flash)
        self._whammy_rest_raw = None
        self._whammy_act_raw  = None

        # I2C config
        self.i2c_sda_pin = tk.IntVar(value=4)
        self.i2c_scl_pin = tk.IntVar(value=5)
        self.adxl345_axis = tk.IntVar(value=1)
        self.i2c_model    = tk.IntVar(value=0)   # 0=ADXL345, 1=LIS3DH, extensible

        # Joystick config
        self.joy_pin_x       = tk.IntVar(value=-1)
        self.joy_pin_y       = tk.IntVar(value=-1)
        self.joy_pin_sw      = tk.IntVar(value=-1)
        self.joy_x_enabled   = tk.BooleanVar(value=False)
        self.joy_y_enabled   = tk.BooleanVar(value=False)
        self.joy_sw_enabled  = tk.BooleanVar(value=False)
        self.joy_whammy_axis = tk.IntVar(value=0)  # 0=none, 1=X, 2=Y
        self.joy_dpad_x        = tk.BooleanVar(value=False)
        self.joy_dpad_y        = tk.BooleanVar(value=False)
        self.joy_dpad_x_invert = tk.BooleanVar(value=False)
        self.joy_dpad_y_invert = tk.BooleanVar(value=False)
        self.joy_deadzone      = tk.IntVar(value=205)

        self._loaded_device_type = self._default_device_type  # updated by _load_config

        # LED state
        self.led_enabled = tk.BooleanVar(value=False)
        self.led_count = tk.IntVar(value=0)
        self.led_base_brightness = tk.IntVar(value=5)
        self.led_data_pin = tk.IntVar(value=3)
        self.led_clock_pin = tk.IntVar(value=6)
        self.led_colors = [tk.StringVar(value="FFFFFF") for _ in range(MAX_LEDS)]
        self.led_maps = [tk.IntVar(value=0) for _ in range(MAX_GUITAR_LED_INPUT_COUNT)]
        self.led_active_br = [tk.IntVar(value=7) for _ in range(MAX_GUITAR_LED_INPUT_COUNT)]
        self.led_reactive = tk.BooleanVar(value=True)
        self._led_maps_backup = [0] * MAX_GUITAR_LED_INPUT_COUNT
        self._led_data_combo = None
        self._led_clock_combo = None

        # LED loop state
        self.led_loop_enabled    = tk.BooleanVar(value=False)
        self.led_loop_start      = tk.IntVar(value=0)
        self.led_loop_end        = tk.IntVar(value=0)
        self.led_breathe_enabled = tk.BooleanVar(value=False)
        self.led_breathe_start   = tk.IntVar(value=1)
        self.led_breathe_end     = tk.IntVar(value=1)
        self.led_breathe_min     = tk.IntVar(value=1)
        self.led_breathe_max     = tk.IntVar(value=9)
        self.led_wave_enabled    = tk.BooleanVar(value=False)
        self.led_wave_origin     = tk.IntVar(value=1)
        self.led_loop_speed      = tk.IntVar(value=3000)
        self.led_breathe_speed   = tk.IntVar(value=3000)
        self.led_wave_speed      = tk.IntVar(value=800)

        # Device name
        self.device_name = tk.StringVar(value=self._default_device_name)

        # Exported JSON metadata used by the preset installer only.
        self.quick_tune_enabled = tk.BooleanVar(value=False)

        # Analog smoothing.
        # ema_alpha_var holds the actual firmware EMA alpha value used internally.
        # smooth_level_var is the 0-9 user-facing slider position.
        # Lookup table: index = slider position (0-9), value = EMA alpha sent to firmware.
        #   0 = no smoothing (255), 1-9 = progressively heavier smoothing.
        self.EMA_ALPHA_TABLE = [255, 180, 140, 110, 90, 75, 60, 45, 25, 10]
        self.smooth_level_var = tk.IntVar(value=4)   # default level 4 → alpha 90 ≈ old 80
        self.ema_alpha_var    = tk.IntVar(value=self.EMA_ALPHA_TABLE[4])

        # Live monitoring state
        self._monitoring = False
        self._monitor_thread = None
        self._debug_text = None    # set when debug console is open
        self._debug_win  = None
        self._help_dialog = None

        # Widget tracking
        self._all_widgets = []
        self._det_btns = {}
        self._pin_combos = {}
        self._sp_combos = {}
        self._row_w = {}
        self._led_widgets = []
        self._led_sub_cards = []
        self._led_color_btns = []
        self._led_map_cbs = {}
        self._led_map_widgets = []
        self._i2c_widgets = []  # I2C-specific widgets (show/hide with mode)

        self._apply_theme()
        self._build_menubar()
        self._build_ui()
        self._set_controls_enabled(False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _axis_analog_pins(self):
        # GPIO 29 is available on wired guitars, but reserved by the Pico W radio.
        if self._loaded_device_type == "guitar_combined":
            return ANALOG_PINS
        return [26, 27, 28, 29]

    def _axis_digital_pins(self):
        pins = list(DIGITAL_PINS)
        if self._loaded_device_type != "guitar_combined":
            pins.append(29)
        return pins

    def _apply_guitar_profile(self, profile_name):
        profile = GUITAR_PROFILE_DEFS[profile_name]
        self._profile_title = profile["title"]
        self._default_device_name = profile["device_name"]
        self._button_defs = list(profile["button_defs"])
        self._led_input_names = list(profile["led_input_names"]) + ["tilt", "whammy"]
        self._led_input_labels = list(profile["led_input_labels"]) + ["Tilt", "Whammy"]
        self._led_input_count = len(self._led_input_names)
        self._fret_colors = dict(profile["fret_colors"])
        self._supported_types = set(profile["supported_types"])
        self._default_device_type = "guitar_live_6fret" if profile_name == "six_fret" else "guitar_alternate"

    def _go_back(self):
        """Save config to the device, then return to the main menu.
        Save runs synchronously here so it completes before hide() disconnects."""
        if self.pico.connected:
            self._set_status("   Saving configuration...", ACCENT_ORANGE)
            try:
                self._push_all_values()
                self.pico.save()
                self._set_status("   Configuration saved.", ACCENT_GREEN)
            except Exception:
                pass  # Don't block navigation if save fails
        if self._on_back:
            self.hide()
            self._on_back()

    def _on_close(self):
        self._stop_monitoring()
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
        self.root.destroy()

    def show(self):
        """Show the configurator UI and restore window to full size."""
        self.root.title(f"OCC - {self._profile_title}")
        self.root.config(menu=self._menu_bar)
        self._outer_frame.pack(fill="both", expand=True)
        _bind_global_mousewheel(self._scroll_canvas, self._on_mousewheel)
        self.root.update_idletasks()

    def hide(self):
        """Hide the configurator UI (return to main menu)."""
        _unbind_global_mousewheel(self._scroll_canvas)
        self._stop_monitoring()
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
            self.pico.disconnect()
        self._outer_frame.pack_forget()

    # ── Theme ───────────────────────────────────────────────

    def _apply_theme(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG_CARD, foreground=TEXT, borderwidth=0,
                    font=(FONT_UI, 9))
        s.configure("TFrame", background=BG_CARD)
        s.configure("TLabel", background=BG_CARD, foreground=TEXT)
        s.configure("TCheckbutton", background=BG_CARD, foreground=TEXT)
        s.map("TCheckbutton", background=[("active", BG_HOVER)])
        s.configure("TRadiobutton", background=BG_CARD, foreground=TEXT)
        s.map("TRadiobutton", background=[("active", BG_HOVER)])
        s.configure("TLabelframe", background=BG_CARD, bordercolor=BORDER)
        s.configure("TLabelframe.Label", background=BG_CARD, foreground=ACCENT_BLUE,
                    font=(FONT_UI, 10, "bold"))
        # TCombobox style removed — CustomDropdown handles its own rendering
        s.configure("TSpinbox", fieldbackground=BG_INPUT, foreground=TEXT,
                    arrowcolor=TEXT, bordercolor=BORDER)
        s.configure("Det.TButton", background=BG_INPUT, foreground=TEXT,
                    bordercolor=BORDER, padding=(8, 3), font=(FONT_UI, 8))
        s.map("Det.TButton",
              background=[("active", BG_HOVER), ("disabled", "#333336")],
              foreground=[("disabled", "#666666")])

    # ── Menubar ─────────────────────────────────────────────

    def _build_menubar(self):
        mb = tk.Menu(self.root, bg=BG_CARD, fg=TEXT,
                     activebackground=ACCENT_BLUE, activeforeground="#fff", bd=0)
        fw = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT,
                     activebackground=ACCENT_BLUE, activeforeground="#fff")

        uf2_list = find_uf2_files()
        if uf2_list:
            flash_sub = tk.Menu(fw, tearoff=0, bg=BG_CARD, fg=TEXT,
                                activebackground=ACCENT_BLUE, activeforeground="#fff")
            for display_name, full_path in uf2_list:
                flash_sub.add_command(
                    label=display_name,
                    command=lambda p=full_path: self._flash_firmware(p))
            flash_sub.add_separator()
            flash_sub.add_command(label="Browse for .uf2...",
                                  command=lambda: self._flash_firmware(None))
            fw.add_cascade(label="Flash Firmware to Pico...", menu=flash_sub)
        else:
            fw.add_command(label="Flash Firmware to Pico...",
                           command=lambda: self._flash_firmware(None))

        fw.add_command(label="Enter BOOTSEL Mode", command=self._enter_bootsel)
        fw.add_separator()
        fw.add_command(label="Export Configuration...", command=self._export_config)
        fw.add_command(label="Import Configuration...", command=self._import_config)
        fw.add_separator()
        fw.add_checkbutton(label="Quick Tune on Preset Install",
                           variable=self.quick_tune_enabled)
        fw.add_separator()
        fw.add_command(label="Switch Dongle/BT Default", command=self._switch_wireless_default)
        fw.add_separator()
        fw.add_command(label="Serial Debug Console", command=self._show_serial_debug)
        fw.add_separator()
        fw.add_command(label="Exit", command=self._on_close)
        mb.add_cascade(label="Advanced", menu=fw)

        pm = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT,
                     activebackground=ACCENT_BLUE, activeforeground="#fff")
        presets = _find_preset_configs(
            self._supported_types,
            allow_unspecified=(self._guitar_profile_key != "six_fret"),
        )
        if presets:
            for display_name, fpath in presets:
                pm.add_command(label=display_name,
                               command=lambda p=fpath: self._import_preset(p))
        else:
            pm.add_command(label="No preset configs found", state="disabled")
        mb.add_cascade(label="Preset Config", menu=pm)

        hm = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT,
                     activebackground=ACCENT_BLUE, activeforeground="#fff")
        hm.add_command(label="About", command=self._show_about)
        mb.add_cascade(label="Help", menu=hm)
        # Store menu bar — applied in show(), not here, because all screens
        # share root and the last __init__ to run would clobber earlier ones.
        self._menu_bar = mb

    # ── Main UI Build ───────────────────────────────────────

    def _switch_wireless_default(self):
        """Toggle wireless_default_mode between Dongle (0) and Bluetooth (1).

        Only meaningful for guitar_combined firmware. For all other types,
        show a friendly message instead of silently doing nothing.
        """
        dtype = getattr(self, '_loaded_device_type', '')
        if dtype != "guitar_combined":
            messagebox.showinfo(
                "Wireless Setting Not Available",
                "This setting is only for wireless guitars.\n\n"
                "The connected device does not support switching\n"
                "between Dongle and Bluetooth modes."
            )
            return

        if not self.pico.connected:
            messagebox.showerror("Not Connected",
                                 "No controller is connected. Please connect first.")
            return

        # Read the current value fresh from the controller.
        # NOTE: wireless_default_mode is the last field in the CFG line.
        # If the firmware's send_config() buffer is too small it gets truncated
        # and the key will be absent — we treat that as a hard error rather than
        # silently defaulting to 0 (which would always switch TO Bluetooth and
        # never allow switching back to Dongle).
        try:
            cfg = self.pico.get_config()
        except Exception as exc:
            messagebox.showerror("Read Error",
                                 f"Could not read configuration from controller:\n{exc}")
            return

        if "wireless_default_mode" not in cfg:
            messagebox.showerror(
                "Firmware Too Old",
                "The connected firmware did not report 'wireless_default_mode'.\n\n"
                "Please flash the latest combined wireless firmware and try again."
            )
            return

        try:
            current = int(cfg["wireless_default_mode"])
        except ValueError:
            messagebox.showerror("Read Error",
                                 f"Unexpected value for wireless_default_mode: "
                                 f"'{cfg['wireless_default_mode']}'")
            return

        # Clamp to valid range in case flash is corrupt
        if current not in (0, 1):
            current = 0

        # Toggle: Dongle (0) → Bluetooth (1), Bluetooth (1) → Dongle (0)
        new_val        = 1 - current
        mode_name      = "Bluetooth HID" if new_val == 1 else "Dongle"
        mode_name_prev = "Dongle"        if new_val == 1 else "Bluetooth HID"

        if not messagebox.askyesno(
            "Switch Wireless Default",
            f"Current default:  {mode_name_prev}\n"
            f"Switch to:        {mode_name}\n\n"
            f"After saving, the controller will boot into {mode_name} mode\n"
            f"by default when not connected via USB.\n\n"
            f"Apply change?"
        ):
            return

        try:
            self.pico.set_value("wireless_default_mode", str(new_val))
            self.pico.save()
        except Exception as exc:
            messagebox.showerror("Write Error",
                                 f"Could not save setting:\n{exc}")
            return

        messagebox.showinfo(
            "Wireless Default Updated",
            f"Default wireless mode set to:  {mode_name}\n\n"
            f"The controller will use {mode_name} mode on next\n"
            f"wireless boot (when no USB host is detected).\n\n"
            f"Reminder: while in Dongle mode you can still switch\n"
            f"to Bluetooth for a single session by holding the\n"
            f"GUIDE button for 3 seconds."
        )

    def _open_help(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self.root, [
                ("Pins & Detections", _help_text(
                    ("Selecting Pins for Button Inputs", "bold"),
                    ("\n\n", None),
                    ("Next to each button input which the controller will send, you can manually or automatically choose the GPIO pin to correspond to that button input.", None),
                    ("Use the dropdown menu to manually choose a GPIO Pin, or use the \"Detect\" button and OCC will attempt to detect you clicking that button on your device automatically and assign the pin in the dropdown.", None),
                    ("\n\n", None),
                    ("Reserved Pins & Conflicts", "bold"),
                    ("\n\n", None),
                    ("Keep in mind, you generally shouldn't set a pin to be multiple inputs, although it can work if you have a special use case.", None),
                    ("Some inputs will automatically NOT allow you to duplicate pins for inputs, such as Up and Down not being the same button on your device.", None),
                )),
                ("Analog & Digital Inputs", _help_text(
                    ("Analog vs Digital", "bold"),
                    ("\n\n", None),
                    ("A Digital pin input is a simple button press. Digital detection will see if you are pressing a button or not, no inbetween.", None),
                    ("An Analog input is a variable input, basically. It will detect you NOT pressing anything, fully pressing an input, or the inbetween.", None),
                    ("\n\n", None),
                    ("Digital pin input is typically for buttons, Analog pin input is for things like accelerometers, joysticks, or triggers.", None),
                )),
                ("Lighting & Effects", _help_text(
                    ("Controller LEDs are communicated through two pins, GPIO 3 and 6 by default. Tell OCC how many LEDs are in series on those LED pins, and you can individually address each one.", None),
                    ("\n\n", None),
                    ("OCC has multiple lighting effects programmed in:", "bold"),
                    ("\n\n", None),
                    ("LED Color Loop", "bold"),
                    ("\n\n", None),
                    ("Set the starting and ending LED you'd like to loop, and while the controller is on, it will make the LEDs gradually fade into eachothers color, looping.", None),
                    ("\n\n", None),
                    ("LED Breathe", "bold"),
                    ("\n\n", None),
                    ("Set the starting to ending LEDs you'd like to be effected, set their low and high brightness, and while the controller is on, the LEDs will gradually turn thier brightness up and back down, looping.", None),
                    ("\n\n", None),
                    ("LED Wave", "bold"),
                    ("\n\n", None),
                    ("Set the LED origin point and on any button press, a \"ripple\" of brightness will wave through the LEDs in line from the pre-set origin point.", None),
                    ("\n\n", None),
                    ("Reactive LEDs", "bold"),
                    ("\n\n", None),
                    ("This is the complicated looking one.. but I promise it is not bad.", None),
                    ("On the left, rows are depicted by button inputs. Each column is an LED in your controller. Match up in the grid which button goes with which LED number. On button press, the LED corresponding to that button will get brighter.", None),
                )),
                ("Boot Modes", _help_text(
                    ("Boot Modes", "bold"),
                    ("\n\n", None),
                    ("PS3/HID:", "bold"),
                    (" Hold Yellow while powering on to enter PS3/HID mode", None),
                    ("\n\n", None),
                    ("FFestival/Keyboard:", "bold"),
                    (" Hold Orange while powering on to enter Fortnite Festival keyboard mode", None),
                    ("\n\n", None),
                    ("PS3/FF boot modes are only for USB wired connections", None),
                )),
            ])
        self._help_dialog.open()

    def _build_ui(self):
        self._outer_frame = tk.Frame(self.root, bg=BG_MAIN)
        outer = self._outer_frame
        outer.pack(fill="both", expand=True, padx=12, pady=8)

        # Connection card
        conn_card = tk.Frame(outer, bg=BG_CARD, highlightbackground=BORDER,
                             highlightthickness=1)
        conn_card.pack(fill="x", pady=(0, 8), ipady=10, ipadx=14)

        tk.Label(conn_card, text="CONNECTION", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=14, pady=(8, 0))
        tk.Label(conn_card, text="Click Connect to switch the controller to config mode.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(anchor="w", padx=14, pady=(0, 8))

        btn_bar = tk.Frame(conn_card, bg=BG_CARD)
        btn_bar.pack(fill="x", padx=14)

        self.connect_btn = RoundedButton(
            btn_bar, text="Connect to Controller", command=self._connect_clicked,
            bg_color=ACCENT_BLUE, btn_width=190, btn_height=34)
        self.connect_btn.pack(side="left", padx=(0, 8))

        self.manual_btn = RoundedButton(
            btn_bar, text="Manual COM Port", command=self._manual_connect,
            bg_color="#555560", btn_width=150, btn_height=34,
            btn_font=(FONT_UI, 8, "bold"))
        self.manual_btn.pack(side="left")

        HelpButton(btn_bar, command=self._open_help).pack(side="right", anchor="center", padx=(0, 4))

        self.status_label = tk.Label(conn_card, text="   Not connected",
                                      bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        self.status_label.pack(anchor="w", padx=14, pady=(8, 6))

        # Tab bar
        tab_bar = tk.Frame(outer, bg=BG_MAIN)
        tab_bar.pack(fill="x")
        _TAB_NAMES = ["Buttons", "Tilt & Whammy", "Joystick & Dpad", "Lighting"]
        self._tab_labels = []
        for _i, _name in enumerate(_TAB_NAMES):
            _lbl = tk.Label(tab_bar, text=_name, bg=BG_MAIN, fg=TEXT_DIM,
                            font=(FONT_UI, 10, "bold"), padx=18, pady=10,
                            cursor="hand2")
            _lbl.pack(side="left")
            _lbl.bind("<Button-1>", lambda e, idx=_i: self._switch_tab(idx))
            self._tab_labels.append(_lbl)
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x")

        # Scrollable area — one slot per tab
        scroll_outer = tk.Frame(outer, bg=BG_MAIN)
        scroll_outer.pack(fill="both", expand=True)

        self._tab_slots   = []
        self._tab_widgets = []   # (canvas, scrollbar, content, window_id) per tab
        for _ in range(4):
            _slot    = tk.Frame(scroll_outer, bg=BG_MAIN)
            _canvas  = tk.Canvas(_slot, bg=BG_MAIN, highlightthickness=0, bd=0)
            _sb      = ttk.Scrollbar(_slot, orient="vertical", command=self._on_yview)
            _content = tk.Frame(_canvas, bg=BG_MAIN)
            _content.bind("<Configure>", self._on_content_configure)
            _win = _canvas.create_window((0, 0), window=_content, anchor="nw")
            _canvas.configure(yscrollcommand=_sb.set)
            _canvas.pack(side="left", fill="both", expand=True)
            _sb.pack(side="right", fill="y")
            _canvas.bind("<Configure>", self._on_canvas_resize)
            self._tab_slots.append(_slot)
            self._tab_widgets.append((_canvas, _sb, _content, _win))

        # Build Tab 0: Buttons
        self._set_active_tab_refs(0)
        self._make_device_name_section()
        self._make_section("FRET BUTTONS", ["frets"])
        self._make_section("STRUM", ["strum"])
        self._make_section("NAVIGATION", ["nav", "nav2"])
        self._make_debounce_section()

        # Build Tab 1: Tilt & Whammy
        self._set_active_tab_refs(1)
        self._make_analog_section(
            "TILT SENSOR", "tilt", self.tilt_mode, self.tilt_pin, self.tilt_enabled,
            hint="Digital: ball tilt switch.  Analog: accelerometer output on ADC pin.  "
                 "I2C: ADXL345/LIS3DH accelerometer (select chip model below).",
            supports_i2c=True,
            on_open=lambda: (self._refresh_analog_combo("tilt"), self._sync_i2c_combos()))
        self._make_analog_section(
            "WHAMMY BAR", "whammy", self.whammy_mode, self.whammy_pin, self.whammy_enabled,
            hint="Digital: hall switch.  Analog: linear hall sensor (OH49E) or potentiometer.",
            supports_i2c=False,
            on_open=lambda: self._refresh_analog_combo("whammy"))

        # Build Tab 2: Joystick & Dpad
        self._set_active_tab_refs(2)
        self._make_section("D-PAD / DIRECTIONAL STICK", ["dpad"],
                           hint="For controllers with a navigation stick. "
                                "D-Pad Up/Down share XInput bits with Strum Up/Down.")
        self._make_joystick_section()

        # Build Tab 3: Lighting
        self._set_active_tab_refs(3)
        self._make_led_section()

        # Activate tab 0 as default
        self._active_tab = 0
        self._tab_slots[0].pack(fill="both", expand=True)
        self._set_active_tab_refs(0)
        self._scroll_enabled   = True
        self._scroll_animating = False
        self._scroll_target    = None
        self._update_tab_styling()

        # Bottom action bar
        bottom = tk.Frame(outer, bg=BG_MAIN)
        bottom.pack(fill="x", pady=(6, 0))

        self.back_btn = RoundedButton(
            bottom, text="◀  Main Menu", command=self._go_back,
            bg_color="#555560", btn_width=130, btn_height=32,
            btn_font=(FONT_UI, 8, "bold"))
        self.back_btn.pack(side="left", padx=(0, 8))

        self.defaults_btn = RoundedButton(
            bottom, text="Reset to Defaults", command=self._reset_defaults,
            bg_color="#555560", btn_width=155, btn_height=32,
            btn_font=(FONT_UI, 8, "bold"))
        self.defaults_btn.pack(side="left")

        self.save_reboot_btn = RoundedButton(
            bottom, text="Save & Enter Play Mode", command=self._save_and_reboot,
            bg_color=ACCENT_GREEN, btn_width=200, btn_height=34)
        self.save_reboot_btn.pack(side="right")
        self.save_reboot_btn.set_state("disabled")

    def _update_scroll_state(self):
        """Compare content height to canvas height.
        If content fits: snap to top, hide scrollbar, block mousewheel.
        If content overflows: show scrollbar and allow mousewheel.
        Called after any layout change (resize, expand/collapse).
        """
        self._scroll_canvas.update_idletasks()
        content_h = self.content.winfo_reqheight()
        canvas_h  = self._scroll_canvas.winfo_height()
        needs_scroll = content_h > canvas_h

        if needs_scroll and not self._scroll_enabled:
            self._scrollbar.pack(side="right", fill="y")
            self._scroll_enabled = True
        elif not needs_scroll and self._scroll_enabled:
            self._scroll_canvas.yview_moveto(0)
            self._scrollbar.pack_forget()
            self._scroll_enabled = False

        self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all"))

    def _on_content_configure(self, event):
        # Only update scroll for the active tab's content frame
        if event.widget is self.content:
            self._update_scroll_state()

    def _on_canvas_resize(self, event):
        # Only update scroll for the active tab's canvas
        if event.widget is self._scroll_canvas:
            self._scroll_canvas.itemconfig(self._content_window, width=event.width)
            self._update_scroll_state()

    def _on_yview(self, *args):
        """Direct scrollbar command — moves canvas and cancels any
        in-flight mousewheel animation so the bar always wins."""
        self._scroll_target = None
        self._scroll_canvas.yview(*args)

    def _set_active_tab_refs(self, idx):
        """Point self.content / canvas / scrollbar at the given tab slot."""
        canvas, sb, content, win = self._tab_widgets[idx]
        self._scroll_canvas  = canvas
        self._scrollbar      = sb
        self.content         = content
        self._content_window = win

    def _switch_tab(self, idx):
        """Switch visible tab, update scroll refs and styling."""
        if idx == self._active_tab:
            return
        self._tab_slots[self._active_tab].pack_forget()
        self._tab_slots[idx].pack(fill="both", expand=True)
        self._scroll_target    = None
        self._scroll_animating = False
        self._scroll_enabled   = True
        self._active_tab = idx
        self._set_active_tab_refs(idx)
        self._update_tab_styling()
        self._update_scroll_state()

    def _update_tab_styling(self):
        for i, lbl in enumerate(self._tab_labels):
            if i == self._active_tab:
                lbl.config(bg=BG_CARD, fg=TEXT)
            else:
                lbl.config(bg=BG_MAIN, fg=TEXT_DIM)

    def _on_mousewheel(self, event):
        """Eased mousewheel scroll — animates toward the target fraction
        so scrolling feels smooth rather than jumping by whole units."""
        delta = _mousewheel_units(event)
        if delta is None:
            return
        content_h = max(1, self.content.winfo_reqheight())
        cur_frac  = self._scroll_canvas.yview()[0]
        # 60 px per notch
        new_frac  = cur_frac + delta * 60 / content_h
        new_frac  = max(0.0, min(1.0, new_frac))
        self._scroll_target = new_frac
        if not self._scroll_animating:
            self._scroll_animating = True
            self._do_scroll_step()

    def _do_scroll_step(self):
        """Animation tick — ease 25 % of the remaining distance per frame."""
        if self._scroll_target is None or not self._scroll_canvas.winfo_exists():
            self._scroll_animating = False
            return
        cur  = self._scroll_canvas.yview()[0]
        diff = self._scroll_target - cur
        if abs(diff) < 0.0005:
            self._scroll_canvas.yview_moveto(self._scroll_target)
            self._scroll_animating = False
            self._scroll_target    = None
            return
        self._scroll_canvas.yview_moveto(cur + diff * 0.25)
        self._scroll_canvas.after(16, self._do_scroll_step)

    # ── Section builders ────────────────────────────────────

    def _make_card(self):
        card = tk.Frame(self.content, bg=BG_CARD,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 6), padx=2)
        return card

    def _make_collapsible_card(self, title, collapsed=False, on_open=None):
        """Return (card, body) where body is the collapsible content frame.

        The header row contains a triangle arrow + title that toggle the body.
        collapsed=True starts the section folded up.
        on_open: optional callable invoked each time the section is expanded.
        """
        card = tk.Frame(self.content, bg=BG_CARD,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 6), padx=2)

        # Header row (always visible, clickable)
        header = tk.Frame(card, bg=BG_CARD, cursor="hand2")
        header.pack(fill="x", padx=12, pady=(8, 0))

        arrow_var = tk.StringVar(value="\u25b6" if collapsed else "\u25bc")
        arrow_lbl = tk.Label(header, textvariable=arrow_var,
                             bg=BG_CARD, fg=ACCENT_BLUE,
                             font=(FONT_UI, 9, "bold"))
        arrow_lbl.pack(side="left", padx=(0, 6))

        title_lbl = tk.Label(header, text=title,
                             bg=BG_CARD, fg=ACCENT_BLUE,
                             font=(FONT_UI, 9, "bold"), cursor="hand2")
        title_lbl.pack(side="left")

        # Thin separator below header (hidden when collapsed)
        sep = tk.Frame(card, bg=BORDER, height=1)

        # Body frame (the collapsible part)
        body = tk.Frame(card, bg=BG_CARD)

        _open = [not collapsed]

        def _toggle(_event=None):
            if _open[0]:
                body.pack_forget()
                sep.pack_forget()
                arrow_var.set("\u25b6")
            else:
                sep.pack(fill="x", padx=12, pady=(4, 0))
                body.pack(fill="x", padx=12, pady=(6, 10))
                arrow_var.set("\u25bc")
                if on_open:
                    on_open()
            _open[0] = not _open[0]
            self._update_scroll_state()

        # Set initial visual state
        if collapsed:
            pass  # sep and body stay un-packed
        else:
            sep.pack(fill="x", padx=12, pady=(4, 0))
            body.pack(fill="x", padx=12, pady=(6, 10))

        for widget in (header, arrow_lbl, title_lbl):
            widget.bind("<Button-1>", _toggle)

        return card, body

    def _make_sub_collapsible(self, parent, title, collapsed=True):
        """Nested collapsible card — packed into `parent` instead of self.content."""
        card = tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(2, 2))

        header = tk.Frame(card, bg=BG_CARD, cursor="hand2")
        header.pack(fill="x", padx=10, pady=(6, 0))

        arrow_var = tk.StringVar(value="\u25b6" if collapsed else "\u25bc")
        arrow_lbl = tk.Label(header, textvariable=arrow_var,
                             bg=BG_CARD, fg=ACCENT_BLUE, font=(FONT_UI, 8, "bold"))
        arrow_lbl.pack(side="left", padx=(0, 5))

        title_lbl = tk.Label(header, text=title,
                             bg=BG_CARD, fg=ACCENT_BLUE,
                             font=(FONT_UI, 8, "bold"), cursor="hand2")
        title_lbl.pack(side="left")

        sep = tk.Frame(card, bg=BORDER, height=1)
        body = tk.Frame(card, bg=BG_CARD)

        _open = [not collapsed]

        def _toggle(_event=None):
            if _open[0]:
                body.pack_forget()
                sep.pack_forget()
                arrow_var.set("\u25b6")
            else:
                sep.pack(fill="x", padx=10, pady=(4, 0))
                body.pack(fill="x", padx=10, pady=(6, 8))
                arrow_var.set("\u25bc")
            _open[0] = not _open[0]
            self._update_scroll_state()

        if not collapsed:
            sep.pack(fill="x", padx=10, pady=(4, 0))
            body.pack(fill="x", padx=10, pady=(6, 8))

        for widget in (header, arrow_lbl, title_lbl):
            widget.bind("<Button-1>", _toggle)

        return card, body

    def _make_section(self, title, sections, hint=None):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text=title, bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        if hint:
            tk.Label(inner, text=hint, bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8), wraplength=820,
                     justify="left", anchor="w").pack(fill="x", pady=(0, 4))

        for key, name, sec in self._button_defs:
            if sec in sections:
                self._make_button_row(inner, key, name)

    def _make_button_row(self, parent, key, name):
        self.pin_vars[key] = tk.IntVar(value=-1)
        self.enable_vars[key] = tk.BooleanVar(value=True)

        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=3)

        # enable_vars still used internally for save/load; no visible checkbox
        self.enable_vars[key].set(True)

        fc = self._fret_colors.get(key)
        if fc:
            # Horizontal rounded-rectangle icon
            # Draw within (0,0,W,H) where W/H are 1px less than canvas size
            # so arcs at the right/bottom edge don't get clipped.
            CW, CH, r = 16, 10, 3   # canvas size, corner radius
            W, H = CW - 1, CH - 1   # drawing boundary (inclusive)
            sq = tk.Canvas(row, width=CW, height=CH, bg=BG_CARD,
                           highlightthickness=0, bd=0)
            sq.create_arc(0,     0,     r*2,   r*2,   start=90,  extent=90, fill=fc, outline=fc)
            sq.create_arc(W-r*2, 0,     W,     r*2,   start=0,   extent=90, fill=fc, outline=fc)
            sq.create_arc(0,     H-r*2, r*2,   H,     start=180, extent=90, fill=fc, outline=fc)
            sq.create_arc(W-r*2, H-r*2, W,     H,     start=270, extent=90, fill=fc, outline=fc)
            sq.create_rectangle(r,  0,  W-r, H,   fill=fc, outline=fc)
            sq.create_rectangle(0,  r,  W,   H-r, fill=fc, outline=fc)
            sq.pack(side="left", padx=(0, 5))
        else:
            _BUTTON_ICONS = {
                "strum_up":   "^",
                "strum_down": "v",
                "start":      "+",
                "select":     "-",
                "guide":      "Ø",
            }
            icon_char = _BUTTON_ICONS.get(key)
            if icon_char:
                tk.Label(row, text=icon_char, bg=BG_CARD, fg="white",
                         font=(FONT_UI, 9, "bold"), width=2,
                         anchor="center").pack(side="left", padx=(0, 5))
            else:
                # Spacer so other rows align with fret rows (icon width + padx)
                tk.Frame(row, bg=BG_CARD, width=19, height=1).pack(side="left")

        # Fixed character-width label keeps Pin:/dropdown aligned across all rows
        tk.Label(row, text=name, bg=BG_CARD, fg=TEXT, width=14,
                 anchor="w", font=(FONT_UI, 9)).pack(side="left", padx=(0, 6))

        tk.Label(row, text="Pin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))

        combo = CustomDropdown(row, state="readonly", width=18,
                              values=[DIGITAL_PIN_LABELS[p] for p in DIGITAL_PINS])
        combo.current(0)
        combo.pack(side="left", padx=(0, 8))
        combo.bind("<<ComboboxSelected>>",
                   lambda _e, k=key, c=combo: self._on_pin_combo(k, c))
        self._all_widgets.append(combo)
        self._pin_combos[key] = combo

        det_btn = ttk.Button(row, text="Detect", style="Det.TButton", width=7,
                              command=lambda k=key, n=name: self._start_detect(k, n))
        det_btn.pack(side="left")
        self._det_btns[key] = det_btn
        self._row_w[key] = (combo, det_btn)

    def _make_analog_section(self, title, prefix, mode_var, pin_var, enable_var,
                             hint="", supports_i2c=False, on_open=None):
        _card, inner = self._make_collapsible_card(title, collapsed=True, on_open=on_open)
        if hint:
            tk.Label(inner, text=hint, bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8), wraplength=820,
                     justify="left", anchor="w").pack(fill="x", pady=(0, 4))

        # Enable + mode row
        top_row = tk.Frame(inner, bg=BG_CARD)
        top_row.pack(fill="x", pady=2)

        en_cb = ttk.Checkbutton(top_row, text="Enabled", variable=enable_var,
                                 command=lambda p=prefix: self._on_toggle_analog(p))
        en_cb.pack(side="left", padx=(0, 14))
        self._all_widgets.append(en_cb)

        ttk.Label(top_row, text="Mode:").pack(side="left", padx=(0, 4))
        rd = ttk.Radiobutton(top_row, text="Digital", variable=mode_var, value="digital",
                              command=lambda: self._refresh_analog_combo(prefix))
        rd.pack(side="left", padx=(0, 8))
        self._all_widgets.append(rd)
        ra = ttk.Radiobutton(top_row, text="Analog", variable=mode_var, value="analog",
                              command=lambda: self._refresh_analog_combo(prefix))
        ra.pack(side="left", padx=(0, 8))
        self._all_widgets.append(ra)

        ri = None
        if supports_i2c:
            ri = ttk.Radiobutton(top_row, text="I2C Accelerometer", variable=mode_var,
                                  value="i2c",
                                  command=lambda: self._refresh_analog_combo(prefix))
            ri.pack(side="left")
            self._all_widgets.append(ri)

        # Pin row (hidden when I2C mode)
        pin_row = tk.Frame(inner, bg=BG_CARD)
        pin_row.pack(fill="x", pady=2)
        tk.Label(pin_row, text="     Pin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), width=8).pack(side="left")

        combo = CustomDropdown(pin_row, state="readonly", width=18)
        combo.pack(side="left", padx=(0, 8))
        self._all_widgets.append(combo)

        det_btn = ttk.Button(pin_row, text="Detect", style="Det.TButton", width=7,
                              command=lambda p=prefix: self._start_detect(
                                  f"{p}_pin", f"{prefix.title()} sensor"))
        det_btn.pack(side="left")
        self._det_btns[f"{prefix}_pin"] = det_btn

        # I2C configuration row (shown only when I2C mode selected)
        i2c_row = tk.Frame(inner, bg=BG_CARD)
        # Don't pack yet — managed by _refresh_analog_combo

        if supports_i2c:
            tk.Label(i2c_row, text="     SDA:", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
            sda_combo = CustomDropdown(i2c_row, state="readonly", width=16,
                                      values=[I2C_SDA_LABELS[p] for p in I2C0_SDA_PINS])
            sda_combo.pack(side="left", padx=(0, 8))
            sda_combo.bind("<<ComboboxSelected>>",
                           lambda _e: self.i2c_sda_pin.set(
                               I2C0_SDA_PINS[sda_combo.current()]))
            self._all_widgets.append(sda_combo)

            tk.Label(i2c_row, text="SCL:", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
            scl_combo = CustomDropdown(i2c_row, state="readonly", width=16,
                                      values=[I2C_SCL_LABELS[p] for p in I2C0_SCL_PINS])
            scl_combo.pack(side="left", padx=(0, 8))
            scl_combo.bind("<<ComboboxSelected>>",
                           lambda _e: self.i2c_scl_pin.set(
                               I2C0_SCL_PINS[scl_combo.current()]))
            self._all_widgets.append(scl_combo)

            tk.Label(i2c_row, text="Axis:", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
            axis_combo = CustomDropdown(i2c_row, state="readonly", width=8,
                                       values=[ADXL345_AXIS_LABELS[a] for a in [0, 1, 2]])
            axis_combo.pack(side="left")
            axis_combo.bind("<<ComboboxSelected>>",
                            lambda _e: self.adxl345_axis.set(axis_combo.current()))
            self._all_widgets.append(axis_combo)

            tk.Label(i2c_row, text="Chip:", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(10, 3))
            model_combo = CustomDropdown(i2c_row, state="readonly", width=16,
                                        values=I2C_MODEL_LABELS)
            model_combo.pack(side="left")
            model_combo.bind("<<ComboboxSelected>>",
                             lambda _e: self.i2c_model.set(
                                 I2C_MODEL_VALUES[model_combo.current()]))
            self._all_widgets.append(model_combo)

            self._i2c_widgets = [i2c_row, sda_combo, scl_combo, axis_combo, model_combo]

        # ── Sensitivity vars (needed by both bars below) ──
        sens_min_var = self.tilt_min if prefix == "tilt" else self.whammy_min
        sens_max_var = self.tilt_max if prefix == "tilt" else self.whammy_max
        invert_var   = self.tilt_invert if prefix == "tilt" else self.whammy_invert

        # ── Live monitor bar graph (raw ADC value + red min/max marker lines) ──
        monitor_row = tk.Frame(inner, bg=BG_CARD)
        monitor_row.pack(fill="x", pady=(6, 0))

        bar = LiveBarGraph(monitor_row, label="Original Value", width=380, height=24,
                           min_marker_var=sens_min_var, max_marker_var=sens_max_var)
        bar.pack(side="left", padx=(24, 8))

        monitor_btn = RoundedButton(
            monitor_row, text="Monitor", command=lambda p=prefix: self._toggle_monitor(p),
            bg_color="#555560", btn_width=80, btn_height=24,
            btn_font=(FONT_UI, 7, "bold"))
        monitor_btn.pack(side="left")
        self._all_widgets.append(monitor_btn)

        # ── Calibrated bar (post-sensitivity + silent 5% deadzone) ──
        cal_row = tk.Frame(inner, bg=BG_CARD)
        cal_row.pack(fill="x", pady=(2, 2))
        cal_bar = CalibratedBarGraph(cal_row, label="Calibrated Value", width=380, height=24,
                                     min_var=sens_min_var, max_var=sens_max_var,
                                     invert_var=invert_var,
                                     ema_alpha_var=self.ema_alpha_var)
        cal_bar.pack(side="left", padx=(24, 8))

        # Redraw both bars whenever min/max/invert change (slider, entry, Set Min/Max, Reset)
        def _on_sens_change(*_):
            bar.redraw_markers()
            cal_bar.redraw()
        sens_min_var.trace_add("write", _on_sens_change)
        sens_max_var.trace_add("write", _on_sens_change)
        invert_var.trace_add("write", _on_sens_change)

        # ── Input Smoothing (EMA alpha) ──────────────────────────────────────
        # One shared setting for both tilt and whammy — only rendered in the
        # whammy section. A single smooth_level_var (0-9) drives ema_alpha_var
        # via a lookup table, which in turn drives both bars and the firmware.
        if prefix == "whammy":
            smooth_row = tk.Frame(inner, bg=BG_CARD)
            smooth_row.pack(fill="x", pady=(6, 0))

            tk.Label(smooth_row, text="Input Smoothing:", bg=BG_CARD, fg=TEXT,
                     font=(FONT_UI, 9), width=16, anchor="w").pack(side="left")

            # Left anchor label
            tk.Label(smooth_row, text="0", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))

            def _on_smooth_change(val):
                level = int(float(val))
                alpha = self.EMA_ALPHA_TABLE[level]
                self.ema_alpha_var.set(alpha)
                # Reset EMA state on both bars so the preview responds immediately
                for _prefix in ("tilt", "whammy"):
                    d = self._sp_combos.get(_prefix)
                    if d and len(d) > 13 and d[13] is not None:
                        d[13].reset_ema()

            smooth_slider = tk.Scale(
                smooth_row, from_=0, to=9, orient="horizontal",
                variable=self.smooth_level_var, showvalue=False,
                bg=BG_CARD, fg=TEXT, troughcolor=BG_INPUT,
                highlightthickness=0, length=160, sliderlength=14,
                resolution=1, command=_on_smooth_change)
            smooth_slider.pack(side="left", padx=(0, 2))
            self._all_widgets.append(smooth_slider)

            # Right anchor label
            tk.Label(smooth_row, text="9", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 8))

            # Live readout: shows the current level number and its alpha value
            smooth_readout = tk.Label(smooth_row, text="", bg=BG_CARD, fg=TEXT_DIM,
                                      font=(FONT_UI, 8), width=22, anchor="w")
            smooth_readout.pack(side="left")

            def _update_readout(*_):
                level = self.smooth_level_var.get()
                alpha = self.EMA_ALPHA_TABLE[level]
                if level == 0:
                    smooth_readout.config(text=f"Level {level}  (no smoothing)")
                else:
                    smooth_readout.config(text=f"Level {level}  (alpha {alpha})")
            self.smooth_level_var.trace_add("write", _update_readout)
            _update_readout()   # initialise on build

        # ── Sensitivity / calibration controls — only shown for analog/I2C modes ──
        if prefix == "tilt":
            # Tilt keeps manual min/max sliders, Set Min/Max, Invert
            min_str = tk.StringVar(value=str(sens_min_var.get()))
            max_str = tk.StringVar(value=str(sens_max_var.get()))

            sens_min_var.trace_add("write", lambda *_: min_str.set(str(sens_min_var.get())))
            sens_max_var.trace_add("write", lambda *_: max_str.set(str(sens_max_var.get())))

            sens_frame = tk.Frame(inner, bg=BG_CARD)
            sens_frame.pack(fill="x", pady=(4, 0))

            tk.Label(sens_frame, text="Sensitivity:", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8), width=12, anchor="w").pack(side="left")

            tk.Label(sens_frame, text="Min", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))

            min_entry = tk.Entry(sens_frame, textvariable=min_str, width=5,
                                 font=(FONT_UI, 8), fg="#000000", bg="#ffffff",
                                 insertbackground="#000000", relief="flat")
            min_entry.pack(side="left", padx=(0, 2))
            self._all_widgets.append(min_entry)

            min_slider = tk.Scale(sens_frame, from_=0, to=4095, orient="horizontal",
                                  variable=sens_min_var, showvalue=False,
                                  bg=BG_CARD, fg=TEXT, troughcolor=BG_INPUT,
                                  highlightthickness=0, length=110, sliderlength=12,
                                  command=lambda v, sv=min_str, mx_var=sens_max_var,
                                  mn_var=sens_min_var: self._on_sens_min_change(
                                      v, sv, mn_var, mx_var))
            min_slider.pack(side="left", padx=(0, 10))
            self._all_widgets.append(min_slider)

            tk.Label(sens_frame, text="Max", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))

            max_entry = tk.Entry(sens_frame, textvariable=max_str, width=5,
                                 font=(FONT_UI, 8), fg="#000000", bg="#ffffff",
                                 insertbackground="#000000", relief="flat")
            max_entry.pack(side="left", padx=(0, 2))
            self._all_widgets.append(max_entry)

            max_slider = tk.Scale(sens_frame, from_=0, to=4095, orient="horizontal",
                                  variable=sens_max_var, showvalue=False,
                                  bg=BG_CARD, fg=TEXT, troughcolor=BG_INPUT,
                                  highlightthickness=0, length=110, sliderlength=12,
                                  command=lambda v, sv=max_str, mx_var=sens_max_var,
                                  mn_var=sens_min_var: self._on_sens_max_change(
                                      v, sv, mn_var, mx_var))
            max_slider.pack(side="left", padx=(0, 6))
            self._all_widgets.append(max_slider)

            min_entry.bind("<FocusOut>", lambda _e, sv=min_str, mn=sens_min_var,
                           mx=sens_max_var: self._on_sens_entry(sv, mn, mx, "min"))
            min_entry.bind("<Return>",   lambda _e, sv=min_str, mn=sens_min_var,
                           mx=sens_max_var: self._on_sens_entry(sv, mn, mx, "min"))
            max_entry.bind("<FocusOut>", lambda _e, sv=max_str, mn=sens_min_var,
                           mx=sens_max_var: self._on_sens_entry(sv, mn, mx, "max"))
            max_entry.bind("<Return>",   lambda _e, sv=max_str, mn=sens_min_var,
                           mx=sens_max_var: self._on_sens_entry(sv, mn, mx, "max"))

            set_min_btn = RoundedButton(
                sens_frame, text="Set Min", btn_width=58, btn_height=20,
                bg_color="#555560", btn_font=(FONT_UI, 7, "bold"),
                command=lambda p=prefix, mn=sens_min_var, sv=min_str,
                mx=sens_max_var: self._set_sens_from_live(p, "min", mn, sv, mx))
            set_min_btn.pack(side="left", padx=(0, 3))
            self._all_widgets.append(set_min_btn)

            set_max_btn = RoundedButton(
                sens_frame, text="Set Max", btn_width=58, btn_height=20,
                bg_color="#555560", btn_font=(FONT_UI, 7, "bold"),
                command=lambda p=prefix, mx=sens_max_var, sv=max_str,
                mn=sens_min_var: self._set_sens_from_live(p, "max", mx, sv, mn))
            set_max_btn.pack(side="left", padx=(0, 3))
            self._all_widgets.append(set_max_btn)

            reset_btn = RoundedButton(
                sens_frame, text="Reset", btn_width=48, btn_height=20,
                bg_color="#555560", btn_font=(FONT_UI, 7, "bold"),
                command=lambda mn=sens_min_var, mx=sens_max_var,
                mn_sv=min_str, mx_sv=max_str: self._reset_sensitivity(
                    mn, mx, mn_sv, mx_sv))
            reset_btn.pack(side="left")
            self._all_widgets.append(reset_btn)

            invert_cb = ttk.Checkbutton(sens_frame, text="Invert",
                                        variable=self.tilt_invert)
            invert_cb.pack(side="left", padx=(10, 0))
            self._all_widgets.append(invert_cb)

        else:
            # Whammy uses guided 2-step calibration; auto-computes min/max/invert
            sens_frame = tk.Frame(inner, bg=BG_CARD)
            sens_frame.pack(fill="x", pady=(4, 0))

            _rest_str = tk.StringVar(value="" if self._whammy_rest_raw is None
                                     else str(self._whammy_rest_raw))
            _act_str  = tk.StringVar(value="" if self._whammy_act_raw  is None
                                     else str(self._whammy_act_raw))

            def _apply_wh_calibration():
                """20% deadzone guided calibration — mirrors EasyConfigScreen logic."""
                rest = self._whammy_rest_raw
                act  = self._whammy_act_raw
                if rest is None or act is None or rest == act:
                    return
                raw_range = abs(act - rest)
                deadzone  = int(0.20 * raw_range)
                if rest <= act:
                    new_min    = max(0, rest + deadzone)
                    new_max    = min(4095, act)
                    new_invert = False
                else:
                    new_min    = max(0, act)
                    new_max    = min(4095, rest - deadzone)
                    new_invert = True
                if new_min >= new_max:
                    new_min = max(0, new_max - 1)
                self.whammy_min.set(new_min)
                self.whammy_max.set(new_max)
                self.whammy_invert.set(new_invert)

            def _on_rest_entry(*_):
                try:
                    v = max(0, min(4095, int(_rest_str.get())))
                except ValueError:
                    return
                self._whammy_rest_raw = v
                _apply_wh_calibration()

            def _on_act_entry(*_):
                try:
                    v = max(0, min(4095, int(_act_str.get())))
                except ValueError:
                    return
                self._whammy_act_raw = v
                _apply_wh_calibration()

            def _snap_rest():
                data = self._sp_combos.get("whammy")
                if not data:
                    return
                if self._monitoring and self._monitor_prefix == "whammy":
                    v = data[10]._value
                else:
                    v = self._one_shot_monitor_read("whammy")
                    if v is None:
                        return
                self._whammy_rest_raw = v
                _rest_str.set(str(v))
                _apply_wh_calibration()

            def _snap_act():
                data = self._sp_combos.get("whammy")
                if not data:
                    return
                if self._monitoring and self._monitor_prefix == "whammy":
                    v = data[10]._value
                else:
                    v = self._one_shot_monitor_read("whammy")
                    if v is None:
                        return
                self._whammy_act_raw = v
                _act_str.set(str(v))
                _apply_wh_calibration()

            def _reset_wh():
                self._whammy_rest_raw = None
                self._whammy_act_raw  = None
                _rest_str.set("")
                _act_str.set("")
                self.whammy_min.set(0)
                self.whammy_max.set(4095)
                self.whammy_invert.set(False)

            # Row 1 — rest snapshot
            rest_row = tk.Frame(sens_frame, bg=BG_CARD)
            rest_row.pack(anchor="w", pady=(4, 2), fill="x")
            tk.Label(rest_row, text="Put whammy at rest, then click:",
                     bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left",
                                                                        padx=(0, 6))
            rest_entry = tk.Entry(rest_row, textvariable=_rest_str, width=6,
                                  font=(FONT_UI, 8), fg="#000000", bg="#ffffff",
                                  insertbackground="#000000", relief="flat")
            rest_entry.pack(side="left", padx=(0, 6))
            rest_entry.bind("<FocusOut>", _on_rest_entry)
            rest_entry.bind("<Return>",   _on_rest_entry)
            self._all_widgets.append(rest_entry)

            rest_btn = RoundedButton(rest_row, text="Whammy at Rest",
                                     bg_color=ACCENT_BLUE, btn_width=120, btn_height=20,
                                     btn_font=(FONT_UI, 7, "bold"), command=_snap_rest)
            rest_btn.pack(side="left", padx=(0, 6))
            self._all_widgets.append(rest_btn)

            reset_btn = RoundedButton(rest_row, text="Reset",
                                      bg_color="#555560", btn_width=48, btn_height=20,
                                      btn_font=(FONT_UI, 7, "bold"), command=_reset_wh)
            reset_btn.pack(side="left")
            self._all_widgets.append(reset_btn)

            # Row 2 — actuated snapshot
            act_row = tk.Frame(sens_frame, bg=BG_CARD)
            act_row.pack(anchor="w", pady=(2, 4), fill="x")
            tk.Label(act_row, text="Push whammy all the way in, then click:",
                     bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left",
                                                                        padx=(0, 6))
            act_entry = tk.Entry(act_row, textvariable=_act_str, width=6,
                                 font=(FONT_UI, 8), fg="#000000", bg="#ffffff",
                                 insertbackground="#000000", relief="flat")
            act_entry.pack(side="left", padx=(0, 6))
            act_entry.bind("<FocusOut>", _on_act_entry)
            act_entry.bind("<Return>",   _on_act_entry)
            self._all_widgets.append(act_entry)

            act_btn = RoundedButton(act_row, text="Whammy Actuated",
                                    bg_color=ACCENT_BLUE, btn_width=120, btn_height=20,
                                    btn_font=(FONT_UI, 7, "bold"), command=_snap_act)
            act_btn.pack(side="left")
            self._all_widgets.append(act_btn)

        self._sp_combos[prefix] = (combo, mode_var, pin_var, enable_var, rd, ra, det_btn,
                                    pin_row, i2c_row, ri, bar, monitor_btn, sens_frame, cal_bar)
        self._refresh_analog_combo(prefix)

    def _make_joystick_section(self):
        """5-pin analog joystick: VRx → ADC, VRy → ADC, SW → digital GPIO."""
        _card, inner = self._make_collapsible_card("5-PIN ANALOG JOYSTICK", collapsed=True)
        tk.Label(inner,
                 text="Connect VRx/VRy to ADC pins (GP26–28). SW click is optional digital input. "
                      "X/Y axes can drive DPad directions and/or act as a bi-directional whammy "
                      "(both + and − deflection produce whammy output).",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 6))

        # ── Pin assignments ──────────────────────────────────────────────────
        pin_frame = tk.Frame(inner, bg=BG_CARD)
        pin_frame.pack(fill="x", pady=(0, 4))

        def _make_adc_row(parent, label, pin_var, enabled_var, target_key):
            row = tk.Frame(parent, bg=BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=BG_CARD, fg=TEXT, width=16,
                     anchor="w", font=(FONT_UI, 9)).pack(side="left")
            cb = ttk.Checkbutton(row, text="Enabled", variable=enabled_var,
                                  command=lambda: _refresh_joy_combos())
            cb.pack(side="left", padx=(0, 8))
            self._all_widgets.append(cb)
            combo = CustomDropdown(row, state="readonly", width=18,
                                  values=[ANALOG_PIN_LABELS[p] for p in ANALOG_PINS])
            combo.current(0)
            combo.pack(side="left", padx=(0, 8))
            combo.bind("<<ComboboxSelected>>",
                       lambda _e, pv=pin_var, c=combo: pv.set(ANALOG_PINS[c.current()]))
            self._all_widgets.append(combo)
            det_btn = ttk.Button(row, text="Detect", style="Det.TButton", width=7,
                                  command=lambda tk=target_key, lbl=label:
                                      self._start_detect(tk, lbl))
            det_btn.pack(side="left")
            self._det_btns[target_key] = det_btn
            return combo

        self._joy_x_combo = _make_adc_row(pin_frame, "VRx (X axis):",
                                           self.joy_pin_x, self.joy_x_enabled, "joy_x")
        self._joy_y_combo = _make_adc_row(pin_frame, "VRy (Y axis):",
                                           self.joy_pin_y, self.joy_y_enabled, "joy_y")

        # Switch row (digital pin)
        sw_row = tk.Frame(pin_frame, bg=BG_CARD)
        sw_row.pack(fill="x", pady=2)
        tk.Label(sw_row, text="SW (click):", bg=BG_CARD, fg=TEXT, width=16,
                 anchor="w", font=(FONT_UI, 9)).pack(side="left")
        sw_cb = ttk.Checkbutton(sw_row, text="Enabled", variable=self.joy_sw_enabled,
                                  command=lambda: _refresh_joy_combos())
        sw_cb.pack(side="left", padx=(0, 8))
        self._all_widgets.append(sw_cb)
        self._joy_sw_combo = CustomDropdown(sw_row, state="readonly", width=18,
                                           values=[DIGITAL_PIN_LABELS[p]
                                                   for p in DIGITAL_PINS])
        self._joy_sw_combo.current(0)
        self._joy_sw_combo.pack(side="left", padx=(0, 8))
        self._joy_sw_combo.bind("<<ComboboxSelected>>",
                                lambda _e: self._apply_guide_pin(
                                    DIGITAL_PINS[self._joy_sw_combo.current()]))
        self._all_widgets.append(self._joy_sw_combo)
        sw_det_btn = ttk.Button(sw_row, text="Detect", style="Det.TButton", width=7,
                                 command=lambda: self._start_detect("joy_sw", "SW Click"))
        sw_det_btn.pack(side="left", padx=(0, 8))
        self._det_btns["joy_sw"] = sw_det_btn
        tk.Label(sw_row, text="→ maps to Guide button", bg=BG_CARD,
                 fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left")

        # ── Whammy mapping ───────────────────────────────────────────────────
        sep = tk.Frame(inner, bg=BORDER, height=1)
        sep.pack(fill="x", pady=6)

        whammy_frame = tk.Frame(inner, bg=BG_CARD)
        whammy_frame.pack(fill="x", pady=(0, 4))
        tk.Label(whammy_frame, text="Whammy axis:", bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 10))

        def _on_whammy_changed():
            axis = self.joy_whammy_axis.get()
            if axis == 1:
                self.joy_dpad_x.set(False)
            elif axis == 2:
                self.joy_dpad_y.set(False)

        for val, lbl in [(0, "None"), (1, "X axis"), (2, "Y axis")]:
            rb = ttk.Radiobutton(whammy_frame, text=lbl, variable=self.joy_whammy_axis,
                                  value=val, command=_on_whammy_changed)
            rb.pack(side="left", padx=(0, 12))
            self._all_widgets.append(rb)
        tk.Label(whammy_frame,
                 text="(both ±deflection → whammy, with deadzone at rest)",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left")

        # ── DPad mapping ─────────────────────────────────────────────────────
        dpad_frame = tk.Frame(inner, bg=BG_CARD)
        dpad_frame.pack(fill="x", pady=(4, 0))
        tk.Label(dpad_frame, text="DPad mapping:", bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 10))

        def _on_dpad_x_changed():
            if self.joy_dpad_x.get() and self.joy_whammy_axis.get() == 1:
                self.joy_whammy_axis.set(0)

        def _on_dpad_y_changed():
            if self.joy_dpad_y.get() and self.joy_whammy_axis.get() == 2:
                self.joy_whammy_axis.set(0)

        # X axis column — checkbox + invert sub-checkbox stacked vertically
        dx_col = tk.Frame(dpad_frame, bg=BG_CARD)
        dx_col.pack(side="left", padx=(0, 20))
        dx_cb = ttk.Checkbutton(dx_col, text="X axis → DPad Left/Right",
                                  variable=self.joy_dpad_x,
                                  command=_on_dpad_x_changed)
        dx_cb.pack(anchor="w")
        self._all_widgets.append(dx_cb)
        dx_inv_cb = ttk.Checkbutton(dx_col, text="    X Invert",
                                     variable=self.joy_dpad_x_invert)
        dx_inv_cb.pack(anchor="w")
        self._all_widgets.append(dx_inv_cb)

        # Y axis column — checkbox + invert sub-checkbox stacked vertically
        dy_col = tk.Frame(dpad_frame, bg=BG_CARD)
        dy_col.pack(side="left")
        dy_cb = ttk.Checkbutton(dy_col, text="Y axis → DPad Up/Down",
                                  variable=self.joy_dpad_y,
                                  command=_on_dpad_y_changed)
        dy_cb.pack(anchor="w")
        self._all_widgets.append(dy_cb)
        dy_inv_cb = ttk.Checkbutton(dy_col, text="    Y Invert",
                                     variable=self.joy_dpad_y_invert)
        dy_inv_cb.pack(anchor="w")
        self._all_widgets.append(dy_inv_cb)

        # ── Deadzone ─────────────────────────────────────────────────────────
        dz_frame = tk.Frame(inner, bg=BG_CARD)
        dz_frame.pack(fill="x", pady=(6, 0))
        tk.Label(dz_frame, text="Deadzone (ADC units):", bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 6))
        dz_spin = ttk.Spinbox(dz_frame, from_=0, to=1000, width=6,
                               textvariable=self.joy_deadzone)
        dz_spin.pack(side="left", padx=(0, 6))
        self._all_widgets.append(dz_spin)
        tk.Label(dz_frame,
                 text="(default 205 ≈ 5% of 4095; increase if stick drifts at rest)",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left")

        def _refresh_joy_combos(restore=False):
            """Enable/disable combos based on checkbox state.

            restore=True: only update widget states, never wipe pin vars.
                          Used when loading config so the loaded pins are preserved.
            restore=False (default): also clear pin vars when a channel is disabled,
                          matching user intent when they uncheck the box.
            """
            state_x  = "readonly" if self.joy_x_enabled.get()  else "disabled"
            state_y  = "readonly" if self.joy_y_enabled.get()   else "disabled"
            state_sw = "readonly" if self.joy_sw_enabled.get()  else "disabled"
            self._joy_x_combo.configure(state=state_x)
            self._joy_y_combo.configure(state=state_y)
            self._joy_sw_combo.configure(state=state_sw)
            if not restore:
                if not self.joy_x_enabled.get():
                    self.joy_pin_x.set(-1)
                if not self.joy_y_enabled.get():
                    self.joy_pin_y.set(-1)
                if not self.joy_sw_enabled.get():
                    self.joy_pin_sw.set(-1)

        self._refresh_joy_combos = _refresh_joy_combos
        _refresh_joy_combos()

    def _make_debounce_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="DEBOUNCE", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 4))
        row = tk.Frame(inner, bg=BG_CARD)
        row.pack(fill="x")
        tk.Label(row, text="Debounce time:", bg=BG_CARD, fg=TEXT).pack(side="left", padx=(0, 5))
        sp = ttk.Spinbox(row, from_=0, to=50, width=5, textvariable=self.debounce_var)
        sp.pack(side="left", padx=(0, 5))
        self._all_widgets.append(sp)
        tk.Label(row, text="ms  (0 = none, 3-5 typical)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left")

    # ── Enable/Disable Logic ────────────────────────────────

    def _make_device_name_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="DEVICE NAME", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner, text="Custom USB device name. "
                 "Note: joy.cpl always shows 'Controller (XBOX 360 For Windows)' "
                 "— this name appears in Device Manager USB properties.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 6))

        row = tk.Frame(inner, bg=BG_CARD)
        row.pack(fill="x")
        tk.Label(row, text="Name:", bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 6))
        _vcmd = (self.root.register(
            lambda P: len(P) <= 20 and all(c in VALID_NAME_CHARS for c in P)), '%P')
        self._name_entry = tk.Entry(row, textvariable=self.device_name,
                                     bg=BG_INPUT, fg=TEXT, insertbackground=TEXT,
                                     font=(FONT_UI, 10), width=30, bd=1, relief="solid",
                                     validate="key", validatecommand=_vcmd)
        self._name_entry.pack(side="left")
        self._all_widgets.append(self._name_entry)
        tk.Label(row, text="(letters, numbers, spaces only  ·  max 20 chars)",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left", padx=(8, 0))

    def _make_led_section(self):
        style = ttk.Style()
        style.configure(LED_PIN_COMBO_STYLE, foreground="#000000", fieldbackground="#ffffff")
        style.map(LED_PIN_COMBO_STYLE,
                  foreground=[("readonly", "#000000")],
                  fieldbackground=[("readonly", "#ffffff")],
                  selectforeground=[("readonly", "#000000")],
                  selectbackground=[("readonly", "#ffffff")])
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)
        tk.Label(inner, text="LED STRIP  (APA102 / SK9822 / Dotstar)",
                 bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(inner, text="Wire SCK (CI) → GP6, MOSI (DI) → GP3. Chain LEDs in series. "
                 "VCC → VBUS (5V), GND → GND. Defaults are DI -> GP3 and CI -> GP6. "
                 "WARNING: The selected LED pins are reserved for LEDs when enabled — "
                 "do not assign buttons to these pins.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 6))

        top = tk.Frame(inner, bg=BG_CARD)
        top.pack(fill="x", pady=2)

        en_cb = ttk.Checkbutton(top, text="Enable LEDs", variable=self.led_enabled,
                                 command=self._on_led_toggle)
        en_cb.pack(side="left", padx=(0, 14))
        self._all_widgets.append(en_cb)

        tk.Label(top, text="Count:", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(
            side="left", padx=(0, 3))
        # Fixed-pixel wrapper keeps the spinbox from stretching on high-DPI screens
        cnt_wrap = tk.Frame(top, bg=BG_CARD, width=52, height=22)
        cnt_wrap.pack(side="left", padx=(0, 12))
        cnt_wrap.pack_propagate(False)
        _cvcmd = (self.root.register(lambda P: P == "" or P.isdigit()), '%P')
        cnt_sp = ttk.Spinbox(cnt_wrap, from_=1, to=MAX_LEDS, width=4,
                              textvariable=self.led_count,
                              command=self._on_led_count_change,
                              validate="key", validatecommand=_cvcmd)
        cnt_sp.pack(fill="both", expand=True)
        cnt_sp.bind("<KeyRelease>", lambda _e, widget=cnt_sp: self._on_led_count_live_change(widget))
        cnt_sp.bind("<Return>", lambda _e: self._on_led_count_change())
        cnt_sp.bind("<FocusOut>", lambda _e: self._on_led_count_change())
        self._all_widgets.append(cnt_sp)
        self._led_widgets.append(cnt_sp)

        tk.Label(top, text=f"(max {MAX_LEDS})", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(0, 10))

        tk.Label(top, text="Base brightness:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        br_wrap = tk.Frame(top, bg=BG_CARD, width=52, height=22)
        br_wrap.pack(side="left", padx=(0, 0))
        br_wrap.pack_propagate(False)
        _bvcmd = (self.root.register(lambda P: P == "" or (P.isdigit() and 0 <= int(P) <= 9)), '%P')
        br_sp = ttk.Spinbox(br_wrap, from_=0, to=9, width=4,
                             textvariable=self.led_base_brightness,
                             validate="key", validatecommand=_bvcmd)
        br_sp.pack(fill="both", expand=True)
        self._all_widgets.append(br_sp)
        self._led_widgets.append(br_sp)
        tk.Label(top, text="(0=off, 9=max)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(4, 0))

        pin_row = tk.Frame(inner, bg=BG_CARD)
        pin_row.pack(fill="x", pady=(6, 0))
        tk.Label(pin_row, text="Data (DI):", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        data_combo = ttk.Combobox(pin_row, state="readonly", width=8, style=LED_PIN_COMBO_STYLE,
                                  values=[f"GPIO {p}" for p in LED_DATA_PINS])
        data_combo.current(LED_DATA_PINS.index(3))
        data_combo.pack(side="left", padx=(0, 16))
        data_combo.bind("<<ComboboxSelected>>",
                        lambda _e, c=data_combo: self.led_data_pin.set(LED_DATA_PINS[c.current()]))
        self._led_data_combo = data_combo
        self._all_widgets.append(data_combo)

        tk.Label(pin_row, text="Clock (CI):", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        clock_combo = ttk.Combobox(pin_row, state="readonly", width=8, style=LED_PIN_COMBO_STYLE,
                                   values=[f"GPIO {p}" for p in LED_CLOCK_PINS])
        clock_combo.current(LED_CLOCK_PINS.index(6))
        clock_combo.pack(side="left")
        clock_combo.bind("<<ComboboxSelected>>",
                         lambda _e, c=clock_combo: self.led_clock_pin.set(LED_CLOCK_PINS[c.current()]))
        self._led_clock_combo = clock_combo
        self._all_widgets.append(clock_combo)

        self._led_colors_frame = tk.Frame(inner, bg=BG_CARD)
        self._led_colors_frame.pack(fill="x", pady=(6, 0))
        self._led_widgets.append(self._led_colors_frame)
        self._rebuild_led_color_grid()

        # ── LED Color Loop sub-card ────────────────────────────────────────
        loop_card, loop_body = self._make_sub_collapsible(inner, "LED COLOR LOOP", collapsed=True)
        self._led_sub_cards.append(loop_card)

        lc_left = tk.Frame(loop_body, bg=BG_CARD)
        lc_left.pack(side="left", fill="y", padx=(0, 20))
        lc_right = tk.Frame(loop_body, bg=BG_CARD)
        lc_right.pack(side="left")

        loop_cb = ttk.Checkbutton(lc_left, text="Enable LED Color Loop",
                                   variable=self.led_loop_enabled)
        loop_cb.pack(anchor="w", pady=(0, 4))
        self._all_widgets.append(loop_cb)

        tk.Label(lc_left, text="Effect Range", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="w").pack(anchor="w", pady=(4, 1))
        loop_range_row = tk.Frame(lc_left, bg=BG_CARD)
        loop_range_row.pack(anchor="w", pady=(0, 4))
        tk.Label(loop_range_row, text="From LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        loop_start_wrap = tk.Frame(loop_range_row, bg=BG_CARD, width=52, height=22)
        loop_start_wrap.pack(side="left", padx=(0, 8))
        loop_start_wrap.pack_propagate(False)
        loop_start_sp = ttk.Spinbox(loop_start_wrap, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_loop_start)
        loop_start_sp.pack(fill="both", expand=True)
        self._all_widgets.append(loop_start_sp)
        tk.Label(loop_range_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        loop_end_wrap = tk.Frame(loop_range_row, bg=BG_CARD, width=52, height=22)
        loop_end_wrap.pack(side="left")
        loop_end_wrap.pack_propagate(False)
        loop_end_sp = ttk.Spinbox(loop_end_wrap, from_=1, to=MAX_LEDS, width=4,
                                   textvariable=self.led_loop_end)
        loop_end_sp.pack(fill="both", expand=True)
        self._all_widgets.append(loop_end_sp)

        tk.Label(lc_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        loop_speed_sl = SpeedSlider(lc_right, self.led_loop_speed,
                                    notch_ms=[9999, 5000, 3000, 1000, 100])
        loop_speed_sl.pack()
        self._all_widgets.append(loop_speed_sl)
        # ── end LED Color Loop sub-card ────────────────────────────────────

        # ── LED Breathe sub-card ───────────────────────────────────────────
        breathe_card, breathe_body = self._make_sub_collapsible(inner, "LED BREATHE", collapsed=True)
        self._led_sub_cards.append(breathe_card)

        br_left = tk.Frame(breathe_body, bg=BG_CARD)
        br_left.pack(side="left", fill="y", padx=(0, 20))
        br_right = tk.Frame(breathe_body, bg=BG_CARD)
        br_right.pack(side="left")

        breathe_cb = ttk.Checkbutton(br_left, text="Enable LED Breathe",
                                     variable=self.led_breathe_enabled,
                                     command=lambda: self.led_wave_enabled.set(False) if self.led_breathe_enabled.get() else None)
        breathe_cb.pack(anchor="w", pady=(0, 4))
        self._all_widgets.append(breathe_cb)

        tk.Label(br_left, text="Effect Range", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="w").pack(anchor="w", pady=(4, 1))
        breathe_range_row = tk.Frame(br_left, bg=BG_CARD)
        breathe_range_row.pack(anchor="w", pady=(0, 4))
        tk.Label(breathe_range_row, text="From LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_start_wrap = tk.Frame(breathe_range_row, bg=BG_CARD, width=52, height=22)
        breathe_start_wrap.pack(side="left", padx=(0, 8))
        breathe_start_wrap.pack_propagate(False)
        breathe_start_sp = ttk.Spinbox(breathe_start_wrap, from_=1, to=MAX_LEDS, width=4,
                                       textvariable=self.led_breathe_start)
        breathe_start_sp.pack(fill="both", expand=True)
        self._all_widgets.append(breathe_start_sp)
        tk.Label(breathe_range_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_end_wrap = tk.Frame(breathe_range_row, bg=BG_CARD, width=52, height=22)
        breathe_end_wrap.pack(side="left")
        breathe_end_wrap.pack_propagate(False)
        breathe_end_sp = ttk.Spinbox(breathe_end_wrap, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_breathe_end)
        breathe_end_sp.pack(fill="both", expand=True)
        self._all_widgets.append(breathe_end_sp)

        tk.Label(br_left, text="Effect Brightness", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="w").pack(anchor="w", pady=(4, 1))
        breathe_bright_row = tk.Frame(br_left, bg=BG_CARD)
        breathe_bright_row.pack(anchor="w", pady=(0, 4))
        tk.Label(breathe_bright_row, text="Min:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_min_wrap = tk.Frame(breathe_bright_row, bg=BG_CARD, width=52, height=22)
        breathe_min_wrap.pack(side="left", padx=(0, 8))
        breathe_min_wrap.pack_propagate(False)
        breathe_min_sp = ttk.Spinbox(breathe_min_wrap, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_min,
                                     validate="key", validatecommand=_bvcmd)
        breathe_min_sp.pack(fill="both", expand=True)
        self._all_widgets.append(breathe_min_sp)
        tk.Label(breathe_bright_row, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_max_wrap = tk.Frame(breathe_bright_row, bg=BG_CARD, width=52, height=22)
        breathe_max_wrap.pack(side="left")
        breathe_max_wrap.pack_propagate(False)
        breathe_max_sp = ttk.Spinbox(breathe_max_wrap, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_max,
                                     validate="key", validatecommand=_bvcmd)
        breathe_max_sp.pack(fill="both", expand=True)
        self._all_widgets.append(breathe_max_sp)

        tk.Label(br_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        breathe_speed_sl = SpeedSlider(br_right, self.led_breathe_speed,
                                       notch_ms=[9999, 5000, 3000, 1000, 100])
        breathe_speed_sl.pack()
        self._all_widgets.append(breathe_speed_sl)
        # ── end LED Breathe sub-card ───────────────────────────────────────

        # ── LED Ripple sub-card ────────────────────────────────────────────
        wave_card, wave_body = self._make_sub_collapsible(inner, "LED RIPPLE", collapsed=True)
        self._led_sub_cards.append(wave_card)

        wv_left = tk.Frame(wave_body, bg=BG_CARD)
        wv_left.pack(side="left", fill="y", padx=(0, 20))
        wv_right = tk.Frame(wave_body, bg=BG_CARD)
        wv_right.pack(side="left")

        wave_cb = ttk.Checkbutton(wv_left, text="Enable LED Ripple",
                                  variable=self.led_wave_enabled,
                                  command=lambda: self.led_breathe_enabled.set(False) if self.led_wave_enabled.get() else None)
        wave_cb.pack(anchor="w", pady=(0, 4))
        self._all_widgets.append(wave_cb)

        wave_origin_row = tk.Frame(wv_left, bg=BG_CARD)
        wave_origin_row.pack(anchor="w", pady=(0, 4))
        tk.Label(wave_origin_row, text="Origin LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        wave_origin_wrap = tk.Frame(wave_origin_row, bg=BG_CARD, width=52, height=22)
        wave_origin_wrap.pack(side="left")
        wave_origin_wrap.pack_propagate(False)
        wave_origin_sp = ttk.Spinbox(wave_origin_wrap, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_wave_origin)
        wave_origin_sp.pack(fill="both", expand=True)
        self._all_widgets.append(wave_origin_sp)

        tk.Label(wv_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        wave_speed_sl = SpeedSlider(wv_right, self.led_wave_speed,
                                    notch_ms=[9999, 2500, 800, 250, 100])
        wave_speed_sl.pack()
        self._all_widgets.append(wave_speed_sl)
        # ── end LED Ripple sub-card ────────────────────────────────────────

        # ── Reactive LED sub-card ──────────────────────────────────────────
        react_card, react_body = self._make_sub_collapsible(
            inner, "REACTIVE LED ON KEYPRESS", collapsed=False)
        self._led_sub_cards.append(react_card)

        react_row = tk.Frame(react_body, bg=BG_CARD)
        react_row.pack(fill="x", pady=(0, 4))
        react_cb = ttk.Checkbutton(react_row, text="Reactive LEDs on keypress",
                                    variable=self.led_reactive,
                                    command=self._on_reactive_toggle)
        react_cb.pack(side="left", padx=(0, 10))
        self._all_widgets.append(react_cb)
        tk.Label(react_row,
                 text="When enabled, LEDs light up when their mapped input is pressed",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")

        lbl = tk.Label(react_body,
                       text="Input \u2192 LED Mapping  (select which LEDs respond to each input)",
                       bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8, "bold"), anchor="w")
        lbl.pack(fill="x", pady=(0, 4))
        self._led_map_widgets.append(lbl)

        self._led_map_frame = tk.Frame(react_body, bg=BG_CARD)
        self._led_map_frame.pack(fill="x")
        self._led_map_widgets.append(self._led_map_frame)
        self._rebuild_led_map_grid()
        # ── end Reactive LED sub-card ──────────────────────────────────────

        self._on_led_toggle()

    def _on_led_toggle(self):
        show = self.led_enabled.get()
        for w in self._led_widgets:
            if show:
                if not w.winfo_ismapped():
                    w.pack(fill="x")
            else:
                w.pack_forget()
        for card in self._led_sub_cards:
            if show:
                if not card.winfo_ismapped():
                    card.pack(fill="x", pady=(2, 2))
            else:
                card.pack_forget()
        if show:
            self._led_colors_frame.pack(fill="x", pady=(6, 0))
            self._rebuild_led_color_grid()
            self._rebuild_led_map_grid()
            self._on_reactive_toggle()

    def _on_reactive_toggle(self):
        reactive = self.led_reactive.get()
        if not reactive:
            for i in range(self._led_input_count):
                cur = self.led_maps[i].get()
                if cur != 0:
                    self._led_maps_backup[i] = cur
                self.led_maps[i].set(0)
        else:
            for i in range(self._led_input_count):
                if self.led_maps[i].get() == 0 and self._led_maps_backup[i] != 0:
                    self.led_maps[i].set(self._led_maps_backup[i])

        for w in self._led_map_widgets:
            if reactive:
                if not w.winfo_ismapped():
                    w.pack(fill="x")
            else:
                if w.winfo_ismapped():
                    w.pack_forget()

        if reactive and self.led_enabled.get():
            self._rebuild_led_map_grid()

    def _on_led_count_change(self):
        count = self.led_count.get()
        if count > MAX_LEDS:
            self.led_count.set(MAX_LEDS)
        elif count < 1:
            self.led_count.set(1)
        self._rebuild_led_color_grid()
        if self.led_reactive.get():
            self._rebuild_led_map_grid()

    def _on_led_count_live_change(self, widget):
        raw = widget.get().strip()
        if not raw:
            return
        try:
            self.led_count.set(int(raw))
        except (ValueError, tk.TclError):
            return
        self._on_led_count_change()

    def _rebuild_led_color_grid(self):
        for w in self._led_colors_frame.winfo_children():
            w.destroy()
        self._led_color_btns = []

        count = self.led_count.get()
        if count < 1:
            return

        tk.Label(self._led_colors_frame, text="LED Colors  (click swatch to change, "
                 "Identify flashes the physical LED):",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 3))

        grid = tk.Frame(self._led_colors_frame, bg=BG_CARD)
        grid.pack(fill="x")

        for i in range(min(count, MAX_LEDS)):
            col = i % 4
            row_num = i // 4
            cell = tk.Frame(grid, bg=BG_CARD)
            cell.grid(row=row_num, column=col, padx=4, pady=3, sticky="w")

            tk.Label(cell, text=f"LED {i+1}", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 7), width=5).pack(side="left")

            color_hex = self.led_colors[i].get()
            try:
                display_color = f"#{color_hex}"
                int(color_hex, 16)
            except Exception:
                display_color = "#FFFFFF"

            swatch = tk.Canvas(cell, width=22, height=22, bg=BG_CARD,
                               highlightthickness=1, highlightbackground=BORDER, bd=0)
            swatch.create_rectangle(2, 2, 20, 20, fill=display_color, outline=display_color,
                                     tags="fill")
            swatch.pack(side="left", padx=(2, 4))
            swatch.bind("<Button-1>", lambda e, idx=i: self._pick_led_color(idx))
            self._led_color_btns.append(swatch)

            id_btn = ttk.Button(cell, text="Identify", style="Det.TButton", width=7,
                                 command=lambda idx=i: self._identify_led(idx))
            id_btn.pack(side="left")
            self._all_widgets.append(id_btn)

    def _identify_led(self, led_idx):
        if not self.pico.connected:
            return
        try:
            self.pico.led_flash(led_idx)
        except Exception as exc:
            messagebox.showerror("LED Flash", str(exc))

    def _pick_led_color(self, led_idx):
        dlg = tk.Toplevel(self.root)
        dlg.title(f"LED #{led_idx+1} Color")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)

        f = tk.Frame(dlg, bg=BG_CARD)
        f.pack(fill="both", expand=True, padx=16, pady=12)

        tk.Label(f, text=f"Color for LED #{led_idx+1}", bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 11, "bold")).pack(pady=(0, 8))

        cur_hex = self.led_colors[led_idx].get()
        try:
            cr = int(cur_hex[0:2], 16)
            cg = int(cur_hex[2:4], 16)
            cb = int(cur_hex[4:6], 16)
        except Exception:
            cr, cg, cb = 255, 255, 255

        r_var = tk.IntVar(value=cr)
        g_var = tk.IntVar(value=cg)
        b_var = tk.IntVar(value=cb)

        preview = tk.Canvas(f, width=80, height=50, bg=BG_CARD, highlightthickness=1,
                            highlightbackground=BORDER, bd=0)
        preview.create_rectangle(2, 2, 78, 48, fill=f"#{cur_hex}", outline=f"#{cur_hex}",
                                  tags="fill")
        preview.pack(pady=(0, 10))

        hex_lbl = tk.Label(f, text=f"#{cur_hex}", bg=BG_CARD, fg=TEXT_DIM,
                           font=("Consolas", 9))
        hex_lbl.pack(pady=(0, 6))

        def update_preview(*_args):
            rv = max(0, min(255, r_var.get()))
            gv = max(0, min(255, g_var.get()))
            bv = max(0, min(255, b_var.get()))
            h = f"#{rv:02X}{gv:02X}{bv:02X}"
            preview.itemconfig("fill", fill=h, outline=h)
            hex_lbl.config(text=h)

        # ── Preset colour swatches ────────────────────────────────────────────
        PRESET_COLORS = [
            ("Green",  "00FF00"),
            ("Red",    "FF0000"),
            ("Yellow", "FFFF00"),
            ("Blue",   "0000FF"),
            ("Orange", "FF4600"),
            ("Purple", "FF00FF"),
            ("Cyan",   "00FFFF"),
            ("White",  "FFFFFF"),
        ]

        tk.Label(f, text="Presets:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(anchor="w", pady=(0, 4))

        swatch_row = tk.Frame(f, bg=BG_CARD)
        swatch_row.pack(anchor="w", pady=(0, 8))

        def _apply_preset(hex_rgb):
            r_var.set(int(hex_rgb[0:2], 16))
            g_var.set(int(hex_rgb[2:4], 16))
            b_var.set(int(hex_rgb[4:6], 16))
            update_preview()

        for name, hex_rgb in PRESET_COLORS:
            display = f"#{hex_rgb}"
            # Choose black or white label text based on background luminance
            rc, gc, bc = int(hex_rgb[0:2], 16), int(hex_rgb[2:4], 16), int(hex_rgb[4:6], 16)
            lum = 0.2126 * rc + 0.7152 * gc + 0.0722 * bc
            fg_text = "#000000" if lum > 100 else "#FFFFFF"

            sw = tk.Canvas(swatch_row, width=32, height=32, bg=BG_CARD,
                           highlightthickness=1, highlightbackground=BORDER,
                           cursor="hand2", bd=0)
            sw.create_rectangle(1, 1, 31, 31, fill=display, outline=display, tags="fill")
            sw.create_text(16, 22, text=name[:3], fill=fg_text,
                           font=(FONT_UI, 6, "bold"), tags="lbl")
            sw.pack(side="left", padx=(0, 4))
            sw.bind("<Button-1>", lambda _e, h=hex_rgb: _apply_preset(h))

            def _on_enter(e, canvas=sw, color=display):
                canvas.config(highlightbackground=ACCENT_BLUE, highlightthickness=2)
            def _on_leave(e, canvas=sw):
                canvas.config(highlightbackground=BORDER, highlightthickness=1)
            sw.bind("<Enter>", _on_enter)
            sw.bind("<Leave>", _on_leave)

        # ── Separator ─────────────────────────────────────────────────────────
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))

        for label_text, var, accent in [("Red", r_var, "#e74c3c"),
                                         ("Green", g_var, "#2ecc71"),
                                         ("Blue", b_var, "#3498db")]:
            row = tk.Frame(f, bg=BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label_text, bg=BG_CARD, fg=accent, width=6,
                     font=(FONT_UI, 8, "bold"), anchor="w").pack(side="left")
            scale = tk.Scale(row, from_=0, to=255, orient="horizontal", variable=var,
                             bg=BG_CARD, fg=TEXT, troughcolor=accent,
                             highlightthickness=0, bd=2, sliderrelief="raised", relief="flat",
                             activebackground=BG_INPUT, length=180,
                             showvalue=False, command=lambda _v: update_preview())
            scale.pack(side="left", padx=(4, 4))
            val_lbl = tk.Label(row, textvariable=var, bg=BG_CARD, fg=TEXT,
                               font=("Consolas", 9), width=4)
            val_lbl.pack(side="left")

        def apply():
            rv = max(0, min(255, r_var.get()))
            gv = max(0, min(255, g_var.get()))
            bv = max(0, min(255, b_var.get()))
            self.led_colors[led_idx].set(f"{rv:02X}{gv:02X}{bv:02X}")
            self._rebuild_led_color_grid()
            if self.led_reactive.get():
                self._rebuild_led_map_grid()
            dlg.destroy()

        btn_row = tk.Frame(f, bg=BG_CARD)
        btn_row.pack(pady=(10, 0))
        RoundedButton(btn_row, text="Apply", command=apply,
                      bg_color=ACCENT_BLUE, btn_width=80, btn_height=28,
                      btn_font=(FONT_UI, 8, "bold")).pack(side="left", padx=(0, 8))
        RoundedButton(btn_row, text="Cancel", command=dlg.destroy,
                      bg_color="#555560", btn_width=80, btn_height=28,
                      btn_font=(FONT_UI, 8, "bold")).pack(side="left")
        _center_window(dlg, self.root)
        dlg.grab_set()
        dlg.wait_window()

    @staticmethod
    def _text_color_for_bg(hex_rgb):
        try:
            r = int(hex_rgb[0:2], 16)
            g = int(hex_rgb[2:4], 16)
            b = int(hex_rgb[4:6], 16)
        except Exception:
            return "#FFFFFF"
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return "#000000" if lum > 140 else "#FFFFFF"

    def _rebuild_led_map_grid(self):
        for w in self._led_map_frame.winfo_children():
            w.destroy()
        self._led_map_cbs = {}
        self._led_map_pin_labels = {}

        count = self.led_count.get()
        if count < 1:
            return

        grid = tk.Frame(self._led_map_frame, bg=BG_CARD)
        grid.pack(fill="x")

        led_col_start = 2
        bright_col = led_col_start + min(count, MAX_LEDS)

        tk.Label(grid, text="Input", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 2))
        tk.Label(grid, text="Pin", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(0, 4))

        for j in range(min(count, MAX_LEDS)):
            color_hex = self.led_colors[j].get().strip()
            if len(color_hex) != 6:
                color_hex = "FFFFFF"
            try:
                bg_color = f"#{color_hex}"
                int(color_hex, 16)
            except Exception:
                bg_color = "#FFFFFF"
                color_hex = "FFFFFF"

            fg_color = self._text_color_for_bg(color_hex)
            badge = tk.Label(grid, text=f" {j} ", bg=bg_color, fg=fg_color,
                             font=(FONT_UI, 7, "bold"),
                             relief="flat", bd=0, padx=1, pady=0)
            badge.grid(row=0, column=led_col_start + j, padx=1, pady=(0, 3))

        tk.Label(grid, text="Bright", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold")).grid(
            row=0, column=bright_col, padx=(6, 0))

        _bvcmd = (self.root.register(lambda P: P == "" or (P.isdigit() and 0 <= int(P) <= 9)), '%P')
        for inp_idx in range(self._led_input_count):
            grid_row = inp_idx + 1

            name_frame = tk.Frame(grid, bg=BG_CARD)
            name_frame.grid(row=grid_row, column=0, sticky="w", padx=(0, 2), pady=1)

            color = self._fret_colors.get(self._led_input_names[inp_idx])
            if color:
                dot = tk.Canvas(name_frame, width=10, height=10, bg=BG_CARD,
                                highlightthickness=0, bd=0)
                dot.create_oval(1, 1, 9, 9, fill=color, outline=color)
                dot.pack(side="left", padx=(0, 2))

            tk.Label(name_frame, text=self._led_input_labels[inp_idx], bg=BG_CARD, fg=TEXT,
                     font=(FONT_UI, 7), anchor="w").pack(side="left")

            pin_text = self._get_input_pin_text(inp_idx)
            pin_lbl = tk.Label(grid, text=pin_text, bg=BG_INPUT, fg=TEXT_DIM,
                               font=("Consolas", 7), width=4, anchor="center",
                               relief="flat", bd=0)
            pin_lbl.grid(row=grid_row, column=1, padx=(0, 4), pady=1)
            self._led_map_pin_labels[inp_idx] = pin_lbl

            cb_vars = []
            current_mask = self.led_maps[inp_idx].get()
            for j in range(min(count, MAX_LEDS)):
                var = tk.BooleanVar(value=bool(current_mask & (1 << j)))
                cb = ttk.Checkbutton(grid, variable=var,
                                      command=lambda i=inp_idx: self._update_led_map(i))
                cb.grid(row=grid_row, column=led_col_start + j, padx=0, pady=1)
                self._all_widgets.append(cb)
                cb_vars.append(var)
            self._led_map_cbs[inp_idx] = cb_vars

            br_sp = ttk.Spinbox(grid, from_=0, to=9, width=3,
                                 textvariable=self.led_active_br[inp_idx],
                                 validate="key", validatecommand=_bvcmd)
            br_sp.grid(row=grid_row, column=bright_col, padx=(6, 0), pady=1)
            self._all_widgets.append(br_sp)

        self._schedule_pin_label_refresh()

    def _get_input_pin_text(self, inp_idx):
        name = self._led_input_names[inp_idx]
        if inp_idx < len(self._button_defs):
            key = self._button_defs[inp_idx][0]
            if key in self.pin_vars:
                pin = self.pin_vars[key].get()
                if key in self.enable_vars and not self.enable_vars[key].get():
                    return "off"
                if pin == -1:
                    return "off"
                return str(pin)
        elif name == "tilt":
            if not self.tilt_enabled.get():
                return "off"
            if self.tilt_mode.get() == "i2c":
                return "I2C"
            return str(self.tilt_pin.get())
        elif name == "whammy":
            if not self.whammy_enabled.get():
                return "off"
            return str(self.whammy_pin.get())
        return "—"

    def _schedule_pin_label_refresh(self):
        if not hasattr(self, '_led_map_pin_labels') or not self._led_map_pin_labels:
            return
        if not self.led_enabled.get() or not self.led_reactive.get():
            return
        for inp_idx, lbl in self._led_map_pin_labels.items():
            try:
                if lbl.winfo_exists():
                    new_text = self._get_input_pin_text(inp_idx)
                    lbl.config(text=new_text)
            except tk.TclError:
                pass
        self.root.after(500, self._schedule_pin_label_refresh)

    def _update_led_map(self, inp_idx):
        if inp_idx not in self._led_map_cbs:
            return
        mask = 0
        for j, var in enumerate(self._led_map_cbs[inp_idx]):
            if var.get():
                mask |= (1 << j)
        self.led_maps[inp_idx].set(mask)

    def _on_toggle_button(self, key):
        enabled = self.enable_vars[key].get()
        combo, det = self._row_w[key]
        if enabled:
            combo.config(state="readonly")
            det.config(state="normal")
            if self.pin_vars[key].get() == -1:
                combo.current(1)
                self.pin_vars[key].set(0)
        else:
            self.pin_vars[key].set(-1)
            combo.current(0)
            combo.config(state="readonly")
            # det stays enabled — user can Detect to re-enable

    def _on_toggle_analog(self, prefix):
        if prefix not in self._sp_combos:
            return
        data = self._sp_combos[prefix]
        combo, mode_var, pin_var, enable_var, rd, ra, det = data[:7]
        pin_row = data[7]
        i2c_row = data[8]
        ri = data[9]

        enabled = enable_var.get()
        st_combo = "readonly" if enabled else "disabled"
        st_btn = "normal" if enabled else "disabled"
        combo.config(state=st_combo)
        rd.config(state=st_btn)
        ra.config(state=st_btn)
        # det stays always enabled — user can detect even when input is toggled off
        if ri:
            ri.config(state=st_btn)
        if not enabled:
            pin_var.set(-1)

    def _refresh_analog_combo(self, prefix):
        if prefix not in self._sp_combos:
            return
        data = self._sp_combos[prefix]
        combo, mode_var, pin_var, enable_var, rd, ra, det = data[:7]
        pin_row = data[7]
        i2c_row = data[8]
        sens_frame = data[12] if len(data) > 12 else None

        mode = mode_var.get()

        if mode == "i2c":
            # Hide pin row, show I2C row
            pin_row.pack_forget()
            if i2c_row.winfo_children():
                i2c_row.pack(fill="x", pady=2)
                # Sync combo positions
                self._sync_i2c_combos()
            if sens_frame:
                if not sens_frame.winfo_ismapped():
                    sens_frame.pack(fill="x", pady=(4, 0))
        elif mode == "analog":
            # Show pin row with analog pins, hide I2C row
            axis_analog_pins = self._axis_analog_pins()
            i2c_row.pack_forget()
            if not pin_row.winfo_ismapped():
                pin_row.pack(fill="x", pady=2)
            combo["values"] = [ANALOG_PIN_LABELS[p] for p in axis_analog_pins]
            cur = pin_var.get()
            if cur in axis_analog_pins:
                combo.current(axis_analog_pins.index(cur))
            else:
                combo.current(0)
                pin_var.set(axis_analog_pins[0])
            if sens_frame:
                if not sens_frame.winfo_ismapped():
                    sens_frame.pack(fill="x", pady=(4, 0))
        else:
            # Digital mode — show pin row with digital pins, hide I2C row and sens
            axis_digital_pins = self._axis_digital_pins()
            i2c_row.pack_forget()
            if not pin_row.winfo_ismapped():
                pin_row.pack(fill="x", pady=2)
            combo["values"] = [DIGITAL_PIN_LABELS[p] for p in axis_digital_pins]
            cur = pin_var.get()
            if cur in axis_digital_pins:
                combo.current(axis_digital_pins.index(cur))
            else:
                combo.current(1)
                pin_var.set(0)
            if sens_frame:
                sens_frame.pack_forget()

        combo.bind("<<ComboboxSelected>>",
                   lambda _e, p=prefix: self._on_analog_combo(p))

    def _sync_i2c_combos(self):
        """Sync I2C combo positions with current variable values."""
        if self._i2c_widgets and len(self._i2c_widgets) >= 4:
            sda_combo   = self._i2c_widgets[1]
            scl_combo   = self._i2c_widgets[2]
            axis_combo  = self._i2c_widgets[3]

            sda = self.i2c_sda_pin.get()
            if sda in I2C0_SDA_PINS:
                sda_combo.current(I2C0_SDA_PINS.index(sda))

            scl = self.i2c_scl_pin.get()
            if scl in I2C0_SCL_PINS:
                scl_combo.current(I2C0_SCL_PINS.index(scl))

            axis = self.adxl345_axis.get()
            if 0 <= axis <= 2:
                axis_combo.current(axis)

            if len(self._i2c_widgets) >= 5:
                model_combo = self._i2c_widgets[4]
                model = self.i2c_model.get()
                if model in I2C_MODEL_VALUES:
                    model_combo.current(I2C_MODEL_VALUES.index(model))

    def _apply_guide_pin(self, pin):
        """Sync both the Guide nav combo and the joystick SW combo to the same pin."""
        enabled = (pin != -1)
        if "guide" in self._pin_combos:
            idx = DIGITAL_PINS.index(pin) if pin in DIGITAL_PINS else 0
            self._pin_combos["guide"].current(idx)
            self.pin_vars["guide"].set(pin)
            self.enable_vars["guide"].set(enabled)
            if "guide" in self._row_w:
                c, _d = self._row_w["guide"]
                c.config(state="readonly" if enabled else "disabled")
        if pin in DIGITAL_PINS:
            self._joy_sw_combo.current(DIGITAL_PINS.index(pin))
        self.joy_pin_sw.set(pin)
        self.joy_sw_enabled.set(enabled)
        if hasattr(self, "_refresh_joy_combos"):
            self._refresh_joy_combos(restore=True)

    def _on_pin_combo(self, key, combo):
        idx = combo.current()
        if idx >= 0:
            pin = DIGITAL_PINS[idx]
            self.pin_vars[key].set(pin)
            enabled = (pin != -1)
            self.enable_vars[key].set(enabled)
            if key == "guide":
                self._apply_guide_pin(pin)
            # Detect stays always lit

    def _on_analog_combo(self, prefix):
        combo, mode_var, pin_var = self._sp_combos[prefix][:3]
        idx = combo.current()
        if mode_var.get() == "analog":
            pin_var.set(self._axis_analog_pins()[idx])
        else:
            pin_var.set(self._axis_digital_pins()[idx])

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for w in self._all_widgets:
            try:
                if isinstance(w, CustomDropdown):
                    w.config(state="readonly")  # always openable
                else:
                    w.config(state=state)
            except Exception:
                pass
        btn_state = "normal" if enabled else "disabled"
        self.defaults_btn.set_state(btn_state)

    # ── Status ──────────────────────────────────────────────

    def _set_status(self, text, color=TEXT_DIM):
        self.status_label.config(text=text, fg=color)
        self.root.update_idletasks()

    @staticmethod
    def _brightness_to_hw(user_val):
        user_val = max(0, min(9, int(user_val)))
        table = [0, 1, 2, 3, 5, 7, 11, 16, 23, 31]
        return table[user_val]

    @staticmethod
    def _brightness_from_hw(hw_val):
        hw_val = max(0, min(31, int(hw_val)))
        table = [0, 1, 2, 3, 5, 7, 11, 16, 23, 31]
        best = 0
        for i, v in enumerate(table):
            if abs(v - hw_val) <= abs(table[best] - hw_val):
                best = i
        return best

    # ── Live Monitoring ─────────────────────────────────────

    def _push_monitor_prereqs(self, prefix):
        """Push only the settings the firmware needs to monitor tilt or whammy.

        Called automatically when the user clicks Monitor, so the firmware is
        always told about the current UI pin/mode selections before a monitoring
        session begins — no Save required.

        For I2C mode this includes: i2c_sda, i2c_scl, i2c_model, adxl345_axis,
        tilt_mode, and tilt_pin (set to -1 to signal I2C path to firmware).
        For analog/digital modes this includes just the mode and pin for the
        selected prefix (tilt or whammy).
        """
        if prefix == "tilt":
            mode = self.tilt_mode.get()
            self.pico.set_value("tilt_mode", mode)
            if mode == "i2c":
                # I2C mode — firmware needs SDA/SCL/model/axis; pin is not used
                self.pico.set_value("i2c_sda",      str(self.i2c_sda_pin.get()))
                self.pico.set_value("i2c_scl",      str(self.i2c_scl_pin.get()))
                self.pico.set_value("i2c_model",    str(self.i2c_model.get()))
                self.pico.set_value("adxl345_axis", str(self.adxl345_axis.get()))
                self.pico.set_value("tilt_pin",     "-1")
            else:
                tp = self.tilt_pin.get() if self.tilt_enabled.get() else -1
                self.pico.set_value("tilt_pin", str(tp))

        elif prefix == "whammy":
            mode = self.whammy_mode.get()
            self.pico.set_value("whammy_mode", mode)
            wp = self.whammy_pin.get() if self.whammy_enabled.get() else -1
            self.pico.set_value("whammy_pin", str(wp))
            if mode == "analog":
                # Also push the smoothing/EMA value so the firmware uses the
                # current slider setting during monitoring
                ema_val = self.ema_alpha_var.get()
                self.pico.set_value("ema_alpha", "0" if ema_val >= 255 else str(ema_val))

    def _toggle_monitor(self, prefix):
        """Toggle live monitoring for tilt or whammy."""
        if self._monitoring:
            self._stop_monitoring()
            return

        if not self.pico.connected:
            return

        data = self._sp_combos.get(prefix)
        if not data:
            return

        mode_var = data[1]
        pin_var = data[2]
        enable_var = data[3]
        bar = data[10]
        monitor_btn = data[11]
        cal_bar = data[13] if len(data) > 13 else None

        if not enable_var.get():
            messagebox.showinfo("Monitor", f"{prefix.title()} is disabled.")
            return

        mode = mode_var.get()
        self._monitoring = True
        self._monitor_prefix = prefix
        monitor_btn._label = "Stop"
        monitor_btn._bg = ACCENT_RED
        monitor_btn._render(ACCENT_RED)

        # Reset EMA state on the calibrated bar so smoothing starts fresh
        if cal_bar is not None:
            cal_bar.reset_ema()

        # Push the current tilt/whammy pin settings to firmware immediately so
        # the monitor sees the current UI values without requiring a Save first.
        try:
            self._push_monitor_prereqs(prefix)
        except Exception as exc:
            self._monitoring = False
            monitor_btn._label = "Monitor"
            monitor_btn._bg = "#555560"
            monitor_btn._render("#555560")
            messagebox.showerror("Monitor Error", f"Could not apply settings: {exc}")
            return

        def monitor_thread():
            try:
                if mode == "i2c":
                    # Pass the selected axis so firmware sends only MVAL: at 50 Hz
                    axis = self.adxl345_axis.get()
                    self.pico.start_monitor_i2c(axis=axis)
                elif mode == "analog":
                    pin = pin_var.get()
                    self.pico.start_monitor_adc(pin)
                else:
                    pin = pin_var.get()
                    self.pico.start_monitor_digital(pin)

                while self._monitoring:
                    # Drain all buffered lines — only the most recent value is
                    # used for the bar graph so the display never lags behind.
                    val, others = self.pico.drain_monitor_latest(0.05)
                    for raw in others:
                        self.root.after(0, lambda r=raw: self._debug_log(r))
                    if val is not None:
                        self.root.after(0, lambda v=val: bar.set_value(v))
                        if cal_bar is not None:
                            self.root.after(0, lambda v=val: cal_bar.set_raw(v))
            except Exception as exc:
                self.root.after(0, lambda: self._on_monitor_error(str(exc)))

        self._monitor_thread = threading.Thread(target=monitor_thread, daemon=True)
        self._monitor_thread.start()

    def _stop_monitoring(self):
        if not self._monitoring:
            return
        self._monitoring = False

        try:
            self.pico.stop_monitor()
        except Exception:
            pass

        # Wait for monitor thread to finish — prevents it racing on readline
        # with the next serial command (e.g. SET:pin_green=...)
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=0.3)

        # Discard any stale MVAL bytes still in the OS buffer
        self.pico.flush_input()

        # Reset button appearance
        prefix = getattr(self, '_monitor_prefix', None)
        if prefix and prefix in self._sp_combos:
            monitor_btn = self._sp_combos[prefix][11]
            monitor_btn._label = "Monitor"
            monitor_btn._bg = "#555560"
            monitor_btn._render("#555560")

    def _on_monitor_error(self, msg):
        self._monitoring = False
        prefix = getattr(self, '_monitor_prefix', None)
        if prefix and prefix in self._sp_combos:
            monitor_btn = self._sp_combos[prefix][11]
            monitor_btn._label = "Monitor"
            monitor_btn._bg = "#555560"
            monitor_btn._render("#555560")
        messagebox.showerror("Monitor Error", msg)

    # ── Sensitivity helpers ──────────────────────────────────

    def _on_sens_min_change(self, val, str_var, min_var, max_var):
        """Slider moved — update entry box, clamp so min < max."""
        v = int(float(val))
        if v >= max_var.get():
            v = max_var.get() - 1
            min_var.set(v)
        str_var.set(str(v))

    def _on_sens_max_change(self, val, str_var, min_var, max_var):
        """Slider moved — update entry box, clamp so max > min."""
        v = int(float(val))
        if v <= min_var.get():
            v = min_var.get() + 1
            max_var.set(v)
        str_var.set(str(v))

    def _on_sens_entry(self, str_var, int_var, other_var, which):
        """User typed a value — validate, clamp, and move the slider to match."""
        try:
            v = int(str_var.get().strip())
        except ValueError:
            # Not a valid integer — restore the current good value
            str_var.set(str(int_var.get()))
            return
        v = max(0, min(4095, v))
        if which == "min" and v >= other_var.get():
            v = other_var.get() - 1
        elif which == "max" and v <= other_var.get():
            v = other_var.get() + 1
        v = max(0, min(4095, v))
        int_var.set(v)
        str_var.set(str(v))   # normalise (e.g. remove leading zeros)

    def _reset_sensitivity(self, min_var, max_var, min_sv, max_sv):
        min_var.set(0)
        max_var.set(4095)
        min_sv.set("0")
        max_sv.set("4095")

    def _one_shot_monitor_read(self, prefix):
        """Start monitor for prefix, grab one live MVAL, stop. Returns int or None."""
        if not self.pico.connected:
            return None
        data = self._sp_combos.get(prefix)
        if not data:
            return None

        mode_var   = data[1]
        pin_var    = data[2]
        enable_var = data[3]

        if not enable_var.get():
            messagebox.showinfo("Monitor", f"{prefix.title()} is disabled — enable it first.")
            return None

        # Stop any other active monitor so we own the serial port
        if self._monitoring:
            self._stop_monitoring()

        mode = mode_var.get()
        try:
            self._push_monitor_prereqs(prefix)
            if mode == "i2c":
                self.pico.start_monitor_i2c(axis=self.adxl345_axis.get())
            elif mode == "analog":
                self.pico.start_monitor_adc(pin_var.get())
            else:
                self.pico.start_monitor_digital(pin_var.get())

            # 0.3s timeout — firmware streams at 50 Hz so first MVAL arrives in ~20ms
            val, _ = self.pico.drain_monitor_latest(0.3)

            self.pico.stop_monitor()
            self.pico.flush_input()
            return val
        except Exception as exc:
            messagebox.showerror("Monitor Error", f"Could not read {prefix}: {exc}")
            try:
                self.pico.stop_monitor()
            except Exception:
                pass
            self.pico.flush_input()
            return None

    def _set_sens_from_live(self, prefix, which, var, str_var, other_var):
        """Snap min or max to the current live monitor reading."""
        data = self._sp_combos.get(prefix)
        if not data:
            return

        if self._monitoring and self._monitor_prefix == prefix:
            live_val = data[10]._value
        else:
            live_val = self._one_shot_monitor_read(prefix)
            if live_val is None:
                return

        if which == "min":
            clamped = max(0, min(live_val, other_var.get() - 1))
            var.set(clamped)
            str_var.set(str(clamped))
        else:
            clamped = min(4095, max(live_val, other_var.get() + 1))
            var.set(clamped)
            str_var.set(str(clamped))

    # ── Connection ──────────────────────────────────────────

    def _connect_clicked(self):
        port = PicoSerial.find_config_port()
        if port:
            self._connect_serial(port)
            return
        if XINPUT_AVAILABLE:
            self._connect_xinput()
        else:
            messagebox.showinfo(CONTROLLER_SIGNAL_LABEL,
                _signal_unavailable_message() + "\n"
                "Use 'Manual COM Port' if the controller is already in config mode.")

    def _connect_xinput(self):
        self._set_status(f"   Scanning for {PLAY_MODE_LABEL} controllers...", ACCENT_BLUE)
        controllers = xinput_get_connected()
        if not controllers:
            self._set_status("   No controllers found", ACCENT_RED)
            messagebox.showwarning("No Controllers",
                "No supported play-mode controllers detected.\n"
                f"Make sure the guitar is plugged in and recognized by {HOST_SYSTEM_LABEL}.")
            return

        if len(controllers) == 1:
            slot = controllers[0][0]
        else:
            slot = self._pick_slot(controllers)
            if slot is None:
                self._set_status("   Cancelled", TEXT_DIM)
                return

        self._set_status(f"   Sending config signal (slot {slot + 1})...", ACCENT_BLUE)
        self.root.update_idletasks()

        for left, right in MAGIC_STEPS:
            result = xinput_send_vibration(slot, left, right)
            if result != ERROR_SUCCESS:
                self._set_status("   Vibration send failed", ACCENT_RED)
                return
            time.sleep(0.08)
        xinput_send_vibration(slot, 0, 0)

        self._set_status("   Waiting for config mode...", ACCENT_BLUE)
        self.root.update_idletasks()

        port = self._wait_for_port(8.0)
        if port:
            self._connect_serial(port)
        else:
            self._set_status("   Controller didn't enter config mode", ACCENT_RED)
            messagebox.showwarning("Timeout",
                "The controller didn't switch to config mode.\n"
                "Close any games or apps using the controller and retry.")

    def _pick_slot(self, controllers):
        SUBTYPE_NAMES = {
            1: "Gamepad", 2: "Wheel", 3: "Arcade Stick", 4: "Flight Stick",
            5: "Dance Pad", 6: "Guitar", 7: "Guitar Alt", 8: "Drum Kit", 0x13: "Arcade Pad",
        }
        dlg = tk.Toplevel(self.root)
        dlg.title("Select Controller")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)

        chosen = [None]
        frame = tk.Frame(dlg, bg=BG_CARD)
        frame.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(frame, text="Multiple controllers found.\nSelect the guitar:",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 10), justify="center").pack(pady=(0, 12))

        for slot_num, subtype in controllers:
            label = f"Slot {slot_num + 1}: {SUBTYPE_NAMES.get(subtype, f'Type 0x{subtype:02X}')}"
            RoundedButton(frame, text=label,
                          command=lambda s=slot_num: (chosen.__setitem__(0, s), dlg.destroy()),
                          bg_color=ACCENT_BLUE, btn_width=260, btn_height=32).pack(pady=3)

        RoundedButton(frame, text="Cancel", command=dlg.destroy,
                      bg_color="#555560", btn_width=120, btn_height=30,
                      btn_font=(FONT_UI, 8, "bold")).pack(pady=(10, 0))
        _center_window(dlg, self.root)
        dlg.grab_set()
        dlg.wait_window()
        return chosen[0]

    def _wait_for_port(self, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            port = PicoSerial.find_config_port()
            if port:
                time.sleep(0.5)
                if PicoSerial.find_config_port() == port:
                    return port
            time.sleep(0.3)
        return None

    def _connect_serial(self, port):
        try:
            self.pico.connect(port)
            for _ in range(5):
                if self.pico.ping():
                    break
                time.sleep(0.3)
            else:
                self.pico.disconnect()
                self._set_status("   Not responding", ACCENT_RED)
                return

            self._set_status(f"   Connected  —  {port}", ACCENT_GREEN)
            self.connect_btn.set_state("disabled")
            self.manual_btn.set_state("disabled")
            self.save_reboot_btn.set_state("normal")
            self._set_controls_enabled(True)
            self._load_config()
        except Exception as exc:
            self._set_status("   Connection failed", ACCENT_RED)
            messagebox.showerror("Error", str(exc))

    def _manual_connect(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Manual COM Port")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)

        frame = tk.Frame(dlg, bg=BG_CARD)
        frame.pack(fill="both", expand=True, padx=16, pady=14)

        tk.Label(frame, text="Select COM port:", bg=BG_CARD, fg=TEXT).pack(anchor="w", pady=(0, 6))
        ports = PicoSerial.list_ports()
        port_labels = [label for _, label, _ in ports]
        port_devices = [dev for dev, _, _ in ports]

        combo = CustomDropdown(frame, state="readonly", width=50, values=port_labels)
        combo.pack(fill="x", pady=(0, 12))

        for i, (_, _, is_pico) in enumerate(ports):
            if is_pico:
                combo.current(i)
                break
        else:
            if ports:
                combo.current(0)

        def do_connect():
            idx = combo.current()
            if 0 <= idx < len(port_devices):
                dlg.destroy()
                self._connect_serial(port_devices[idx])

        btn_row = tk.Frame(frame, bg=BG_CARD)
        btn_row.pack(fill="x")
        RoundedButton(btn_row, text="Connect", command=do_connect,
                      bg_color=ACCENT_BLUE, btn_width=100, btn_height=30).pack(side="left")
        RoundedButton(btn_row, text="Cancel", command=dlg.destroy,
                      bg_color="#555560", btn_width=100, btn_height=30,
                      btn_font=(FONT_UI, 8, "bold")).pack(side="right")
        _center_window(dlg, self.root)
        dlg.grab_set()
        dlg.wait_window()

    # ── Config I/O ──────────────────────────────────────────

    def _load_config(self):
        try:
            cfg = self.pico.get_config()
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read config: {exc}")
            return
        self._last_raw_cfg = cfg  # cache full response for export (includes sync_pin, wireless_default_mode)

        # ── Device type gate ──────────────────────────────────────────────
        # Route to the correct config UI based on what the firmware reports.
        # This App class is the guitar_alternate configurator.
        # Future device types (drum_kit, classic_controller, etc.) will need
        # their own screen class and a routing branch here in MainMenu.
        device_type = cfg.get("device_type", "unknown")
        SUPPORTED_TYPES = self._supported_types
        if device_type not in SUPPORTED_TYPES:
            messagebox.showerror(
                "Unsupported Device",
                f"This configurator does not support the connected device type:\n\n"
                f"  \"{device_type}\"\n\n"
                f"Supported types: {', '.join(sorted(SUPPORTED_TYPES))}\n\n"
                f"Make sure you have the correct version of the configurator "
                f"for this firmware."
            )
            self.pico.disconnect()
            self._set_status("   Unsupported device type", ACCENT_RED)
            return
        # ─────────────────────────────────────────────────────────────────

        # Track which variant is connected (guitar vs guitar-for-dongle vs guitar-combined)
        self._loaded_device_type = device_type
        is_dongle_guitar  = (device_type == "guitar_alternate_dongle")
        is_combined       = (device_type == "guitar_combined")
        is_six_fret       = (device_type == "guitar_live_6fret")

        # Update status text to indicate variant
        port_name = self.pico.ser.port if self.pico.connected else "?"
        if is_dongle_guitar:
            self._set_status(f"   Guitar for Dongle  —  {port_name}", ACCENT_GREEN)
        elif is_combined:
            self._set_status(f"   Guitar (Combined Wireless)  —  {port_name}", ACCENT_GREEN)

        elif is_six_fret:
            self._set_status(f"   6-Fret Guitar  ·  {port_name}", ACCENT_GREEN)

        for key, _, _ in self._button_defs:
            if key in cfg:
                pin = int(cfg[key])
                self.pin_vars[key].set(pin)
                enabled = (pin != -1)
                self.enable_vars[key].set(enabled)
                if key in self._pin_combos:
                    idx = DIGITAL_PINS.index(pin) if pin in DIGITAL_PINS else 0
                    self._pin_combos[key].current(idx)
                if key in self._row_w:
                    c, d = self._row_w[key]
                    c.config(state="readonly" if enabled else "disabled")
                    d.config(state="normal")

        # Load I2C pins BEFORE calling _refresh_analog_combo("tilt") so that
        # _sync_i2c_combos() inside it already has the correct pin values.
        # The on_open callback on the tilt collapsible card also calls _sync_i2c_combos
        # when the user expands the section, covering the collapsed-at-load case.
        if "i2c_sda" in cfg:
            self.i2c_sda_pin.set(int(cfg["i2c_sda"]))
        if "i2c_scl" in cfg:
            self.i2c_scl_pin.set(int(cfg["i2c_scl"]))
        if "adxl345_axis" in cfg:
            self.adxl345_axis.set(int(cfg["adxl345_axis"]))
        if "i2c_model" in cfg:
            self.i2c_model.set(int(cfg["i2c_model"]))
        self._sync_i2c_combos()

        if "tilt_mode" in cfg:
            self.tilt_mode.set(cfg["tilt_mode"])
        if "tilt_pin" in cfg:
            tp = int(cfg["tilt_pin"])
            self.tilt_pin.set(tp)
            # In I2C mode the pin is always -1 (no GPIO needed), so tilt is
            # still enabled.  Only treat pin==-1 as "disabled" for digital/analog.
            if self.tilt_mode.get() == "i2c":
                self.tilt_enabled.set(True)
            else:
                self.tilt_enabled.set(tp != -1)
        self._refresh_analog_combo("tilt")
        self._on_toggle_analog("tilt")

        if "whammy_mode" in cfg:
            self.whammy_mode.set(cfg["whammy_mode"])
        if "whammy_pin" in cfg:
            wp = int(cfg["whammy_pin"])
            self.whammy_pin.set(wp)
            self.whammy_enabled.set(wp != -1)
        self._refresh_analog_combo("whammy")
        self._on_toggle_analog("whammy")

        if "debounce" in cfg:
            self.debounce_var.set(int(cfg["debounce"]))

        # Analog smoothing — reverse-lookup firmware alpha → slider level
        if "ema_alpha" in cfg:
            raw = int(cfg["ema_alpha"])
            # Firmware stores 0 as "255 (no smoothing)"; normalise
            fw_alpha = 255 if raw == 0 else raw
            # Find nearest level in the table
            best_level = min(range(len(self.EMA_ALPHA_TABLE)),
                             key=lambda i: abs(self.EMA_ALPHA_TABLE[i] - fw_alpha))
            self.smooth_level_var.set(best_level)
            self.ema_alpha_var.set(self.EMA_ALPHA_TABLE[best_level])

        # Sensitivity
        if "tilt_min" in cfg:
            self.tilt_min.set(int(cfg["tilt_min"]))
        if "tilt_max" in cfg:
            self.tilt_max.set(int(cfg["tilt_max"]))
        if "whammy_min" in cfg:
            self.whammy_min.set(int(cfg["whammy_min"]))
        if "whammy_max" in cfg:
            self.whammy_max.set(int(cfg["whammy_max"]))
        if "tilt_invert" in cfg:
            self.tilt_invert.set(int(cfg["tilt_invert"]) != 0)
        if "whammy_invert" in cfg:
            self.whammy_invert.set(int(cfg["whammy_invert"]) != 0)

        # Joystick
        if "joy_pin_x" in cfg:
            px = int(cfg["joy_pin_x"])
            enabled = px >= 0
            actual_pin = px if enabled else ANALOG_PINS[0]
            self.joy_pin_x.set(actual_pin)
            self.joy_x_enabled.set(enabled)
            if actual_pin in ANALOG_PINS:
                self._joy_x_combo.current(ANALOG_PINS.index(actual_pin))
                # .current() does NOT fire <<ComboboxSelected>>, so sync var manually
                self.joy_pin_x.set(ANALOG_PINS[self._joy_x_combo.current()])
        if "joy_pin_y" in cfg:
            py = int(cfg["joy_pin_y"])
            enabled = py >= 0
            actual_pin = py if enabled else ANALOG_PINS[0]
            self.joy_pin_y.set(actual_pin)
            self.joy_y_enabled.set(enabled)
            if actual_pin in ANALOG_PINS:
                self._joy_y_combo.current(ANALOG_PINS.index(actual_pin))
                self.joy_pin_y.set(ANALOG_PINS[self._joy_y_combo.current()])
        if "joy_pin_sw" in cfg:
            ps = int(cfg["joy_pin_sw"])
            enabled = ps >= 0
            actual_pin = ps if enabled else DIGITAL_PINS[0]
            self.joy_pin_sw.set(actual_pin)
            self.joy_sw_enabled.set(enabled)
            if actual_pin in DIGITAL_PINS:
                self._joy_sw_combo.current(DIGITAL_PINS.index(actual_pin))
                self.joy_pin_sw.set(DIGITAL_PINS[self._joy_sw_combo.current()])
        # Sync both guide combos to show the same pin (prefer guide if set, else joy_sw)
        _g = self.pin_vars["guide"].get() if "guide" in self.pin_vars else -1
        _sw = self.joy_pin_sw.get()
        self._apply_guide_pin(_g if _g != -1 else _sw)
        if "joy_whammy_axis" in cfg:
            self.joy_whammy_axis.set(int(cfg["joy_whammy_axis"]))
        if "joy_dpad_x" in cfg:
            self.joy_dpad_x.set(int(cfg["joy_dpad_x"]) != 0)
        if "joy_dpad_y" in cfg:
            self.joy_dpad_y.set(int(cfg["joy_dpad_y"]) != 0)
        if "joy_dpad_x_invert" in cfg:
            self.joy_dpad_x_invert.set(int(cfg["joy_dpad_x_invert"]) != 0)
        if "joy_dpad_y_invert" in cfg:
            self.joy_dpad_y_invert.set(int(cfg["joy_dpad_y_invert"]) != 0)
        if "joy_deadzone" in cfg:
            self.joy_deadzone.set(int(cfg["joy_deadzone"]))
        # Update combo enable states without wiping pins (pass restore=True)
        if hasattr(self, "_refresh_joy_combos"):
            self._refresh_joy_combos(restore=True)

        # (I2C config is loaded earlier — before tilt refresh — see above)

        if "device_name" in cfg:
            self.device_name.set(cfg["device_name"])

        # LED config
        if "led_enabled" in cfg:
            self.led_enabled.set(int(cfg["led_enabled"]) != 0)
        if "led_count" in cfg:
            self.led_count.set(int(cfg["led_count"]))
        if "led_brightness" in cfg:
            self.led_base_brightness.set(self._brightness_from_hw(int(cfg["led_brightness"])))
        if "led_data_pin" in cfg:
            self.led_data_pin.set(int(cfg["led_data_pin"]))
        if "led_clock_pin" in cfg:
            self.led_clock_pin.set(int(cfg["led_clock_pin"]))
        if self._loaded_device_type == "guitar_combined" and self.led_data_pin.get() == 23:
            self.led_data_pin.set(3)
        if self._led_data_combo is not None and self.led_data_pin.get() in LED_DATA_PINS:
            self._led_data_combo.current(LED_DATA_PINS.index(self.led_data_pin.get()))
        if self._led_clock_combo is not None and self.led_clock_pin.get() in LED_CLOCK_PINS:
            self._led_clock_combo.current(LED_CLOCK_PINS.index(self.led_clock_pin.get()))

        # LED loop / breathe / wave
        if "led_loop_enabled" in cfg:
            self.led_loop_enabled.set(int(cfg["led_loop_enabled"]) != 0)
        if "led_loop_start" in cfg:
            self.led_loop_start.set(int(cfg["led_loop_start"]) + 1)
        if "led_loop_end" in cfg:
            self.led_loop_end.set(int(cfg["led_loop_end"]) + 1)
        if "led_breathe_enabled" in cfg:
            self.led_breathe_enabled.set(int(cfg["led_breathe_enabled"]) != 0)
        if "led_breathe_start" in cfg:
            self.led_breathe_start.set(int(cfg["led_breathe_start"]) + 1)
        if "led_breathe_end" in cfg:
            self.led_breathe_end.set(int(cfg["led_breathe_end"]) + 1)
        if "led_breathe_min" in cfg:
            self.led_breathe_min.set(round(int(cfg["led_breathe_min"]) * 9 / 31))
        if "led_breathe_max" in cfg:
            self.led_breathe_max.set(round(int(cfg["led_breathe_max"]) * 9 / 31))
        if "led_wave_enabled" in cfg:
            self.led_wave_enabled.set(int(cfg["led_wave_enabled"]) != 0)
        if "led_wave_origin" in cfg:
            self.led_wave_origin.set(int(cfg["led_wave_origin"]) + 1)
        if "led_loop_speed" in cfg:
            self.led_loop_speed.set(max(100, min(9999, int(cfg["led_loop_speed"]))))
        if "led_breathe_speed" in cfg:
            self.led_breathe_speed.set(max(100, min(9999, int(cfg["led_breathe_speed"]))))
        if "led_wave_speed" in cfg:
            self.led_wave_speed.set(max(100, min(9999, int(cfg["led_wave_speed"]))))

        if "led_colors_raw" in cfg:
            colors = cfg["led_colors_raw"].split(",")
            for i, c in enumerate(colors):
                c = c.strip()
                if i < MAX_LEDS and len(c) == 6:
                    self.led_colors[i].set(c.upper())

        if "led_map_raw" in cfg:
            for pair in cfg["led_map_raw"].split(","):
                pair = pair.strip()
                if "=" not in pair:
                    continue
                name, rest = pair.split("=", 1)
                name = name.strip()
                if name in self._led_input_names:
                    idx = self._led_input_names.index(name)
                    if ":" in rest:
                        hex_mask, bright = rest.split(":", 1)
                        self.led_maps[idx].set(int(hex_mask, 16))
                        self.led_active_br[idx].set(self._brightness_from_hw(int(bright)))

        any_mapped = any(self.led_maps[i].get() != 0 for i in range(self._led_input_count))
        self.led_reactive.set(any_mapped)
        for i in range(self._led_input_count):
            self._led_maps_backup[i] = self.led_maps[i].get()

        self._on_led_toggle()
        if self.led_enabled.get():
            self._rebuild_led_color_grid()
            if self.led_reactive.get():
                self._rebuild_led_map_grid()

    def _push_all_values(self):
        for key, _, _ in self._button_defs:
            pin = self.pin_vars[key].get() if self.enable_vars[key].get() else -1
            self.pico.set_value(key, str(pin))

        self.pico.set_value("tilt_mode", self.tilt_mode.get())
        tp = self.tilt_pin.get() if self.tilt_enabled.get() else -1
        if self.tilt_mode.get() == "i2c":
            tp = -1  # Pin is irrelevant for I2C mode
        self.pico.set_value("tilt_pin", str(tp))

        self.pico.set_value("whammy_mode", self.whammy_mode.get())
        wp = self.whammy_pin.get() if self.whammy_enabled.get() else -1
        self.pico.set_value("whammy_pin", str(wp))

        self.pico.set_value("debounce", str(self.debounce_var.get()))

        # Analog smoothing — firmware stores 255 as 0 (uint8_t: level 0 = no smoothing)
        ema_val = self.ema_alpha_var.get()
        self.pico.set_value("ema_alpha", "0" if ema_val >= 255 else str(ema_val))

        # I2C settings
        self.pico.set_value("i2c_sda", str(self.i2c_sda_pin.get()))
        self.pico.set_value("i2c_scl", str(self.i2c_scl_pin.get()))
        self.pico.set_value("adxl345_axis", str(self.adxl345_axis.get()))
        self.pico.set_value("i2c_model", str(self.i2c_model.get()))

        # Sensitivity
        self.pico.set_value("tilt_min", str(self.tilt_min.get()))
        self.pico.set_value("tilt_max", str(self.tilt_max.get()))
        self.pico.set_value("whammy_min", str(self.whammy_min.get()))
        self.pico.set_value("whammy_max", str(self.whammy_max.get()))
        self.pico.set_value("tilt_invert", "1" if self.tilt_invert.get() else "0")
        self.pico.set_value("whammy_invert", "1" if self.whammy_invert.get() else "0")

        # Joystick
        px = self.joy_pin_x.get() if self.joy_x_enabled.get() else -1
        py = self.joy_pin_y.get() if self.joy_y_enabled.get() else -1
        ps = self.joy_pin_sw.get() if self.joy_sw_enabled.get() else -1
        self.pico.set_value("joy_pin_x",  str(px))
        self.pico.set_value("joy_pin_y",  str(py))
        self.pico.set_value("joy_pin_sw", str(ps))
        self.pico.set_value("joy_whammy_axis", str(self.joy_whammy_axis.get()))
        self.pico.set_value("joy_dpad_x", "1" if self.joy_dpad_x.get() else "0")
        self.pico.set_value("joy_dpad_y", "1" if self.joy_dpad_y.get() else "0")
        self.pico.set_value("joy_dpad_x_invert", "1" if self.joy_dpad_x_invert.get() else "0")
        self.pico.set_value("joy_dpad_y_invert", "1" if self.joy_dpad_y_invert.get() else "0")
        self.pico.set_value("joy_deadzone", str(self.joy_deadzone.get()))

        # Device name — strip any invalid chars (belt-and-suspenders over the Entry vcmd)
        name = ''.join(c for c in self.device_name.get() if c in VALID_NAME_CHARS).strip()
        if not name:
            name = self._default_device_name
        try:
            self.pico.set_value("device_name", name[:20])
        except ValueError:
            pass
        self.pico.set_value("led_data_pin", str(self.led_data_pin.get()))
        self.pico.set_value("led_clock_pin", str(self.led_clock_pin.get()))

        # LED settings
        self.pico.set_value("led_enabled", "1" if self.led_enabled.get() else "0")
        self.pico.set_value("led_count", str(self.led_count.get()))
        self.pico.set_value("led_brightness",
                           str(self._brightness_to_hw(self.led_base_brightness.get())))

        count = self.led_count.get()
        for i in range(min(count, MAX_LEDS)):
            color = self.led_colors[i].get().strip().upper()
            if len(color) != 6:
                color = "FFFFFF"
            self.pico.set_value(f"led_color_{i}", color)

        for i in range(self._led_input_count):
            self.pico.set_value(f"led_map_{i}", f"{self.led_maps[i].get():04X}")
            self.pico.set_value(f"led_active_{i}",
                               str(self._brightness_to_hw(self.led_active_br[i].get())))

        # LED loop / breathe / wave
        self.pico.set_value("led_loop_enabled", "1" if self.led_loop_enabled.get() else "0")
        self.pico.set_value("led_loop_start", str(self.led_loop_start.get() - 1))
        self.pico.set_value("led_loop_end",   str(self.led_loop_end.get() - 1))
        self.pico.set_value("led_breathe_enabled", "1" if self.led_breathe_enabled.get() else "0")
        self.pico.set_value("led_breathe_start", str(self.led_breathe_start.get() - 1))
        self.pico.set_value("led_breathe_end",   str(self.led_breathe_end.get() - 1))
        self.pico.set_value("led_breathe_min",   str(round(self.led_breathe_min.get() * 31 / 9)))
        self.pico.set_value("led_breathe_max",   str(round(self.led_breathe_max.get() * 31 / 9)))
        self.pico.set_value("led_wave_enabled", "1" if self.led_wave_enabled.get() else "0")
        self.pico.set_value("led_wave_origin",  str(self.led_wave_origin.get() - 1))
        for _k, _v in [("led_loop_speed",    str(self.led_loop_speed.get())),
                       ("led_breathe_speed", str(self.led_breathe_speed.get())),
                       ("led_wave_speed",    str(self.led_wave_speed.get()))]:
            try:
                self.pico.set_value(_k, _v)
            except ValueError:
                pass  # old firmware — skip

    # ── Export / Import Configuration ──────────────────────────────

    def _normalized_device_name(self, name=None):
        raw_name = self.device_name.get() if name is None else name
        cleaned = ''.join(c for c in raw_name if c in VALID_NAME_CHARS).strip()
        if not cleaned:
            cleaned = self._default_device_name
        return cleaned[:20]

    def _is_wireless_guitar_firmware(self):
        return getattr(self, "_loaded_device_type", "") == "guitar_combined"

    def _should_rotate_ble_identity_for_name_change(self):
        if not self._is_wireless_guitar_firmware():
            return False
        raw_cfg = getattr(self, "_last_raw_cfg", {})
        current_name = self._normalized_device_name(raw_cfg.get("device_name", ""))
        pending_name = self._normalized_device_name()
        return pending_name != current_name

    def _reset_after_disconnect(self, status_text):
        self._set_status(status_text, ACCENT_GREEN)
        self.connect_btn.set_state("normal")
        self.manual_btn.set_state("normal")
        self.save_reboot_btn.set_state("disabled")
        self._set_controls_enabled(False)

    def _save_configuration_common(self, reboot_after_save):
        rotate_identity = self._should_rotate_ble_identity_for_name_change()
        if rotate_identity:
            if not messagebox.askyesno(
                "Bluetooth Re-Pair Required",
                "Changing the name of a wireless guitar will also rotate its "
                "Bluetooth identity.\n\nAfter saving, the controller will appear "
                "as a new Bluetooth device and must be paired again.\n\nContinue?"):
                return False

        self._stop_monitoring()
        self._push_all_values()
        self.pico.save()

        raw_cfg = dict(getattr(self, "_last_raw_cfg", {}))
        raw_cfg["device_name"] = self._normalized_device_name()
        self._last_raw_cfg = raw_cfg

        if rotate_identity:
            self.pico.rotate_ble_identity()
            self.pico.disconnect()
            self._reset_after_disconnect("   Saved and rebooted to Play Mode")
            messagebox.showinfo(
                "Saved",
                "Configuration saved.\n\nThe wireless guitar rebooted with a new "
                "Bluetooth identity and now needs to be paired again.")
            return True

        if reboot_after_save:
            try:
                self.pico.reboot()
            except Exception:
                pass
            self._reset_after_disconnect("   Rebooted to Play Mode")
        else:
            messagebox.showinfo("Saved", "Configuration saved to controller!")
        return True

    def _export_config(self):
        """Snapshot all current UI values to a JSON file."""
        device_name = self.device_name.get().strip() or self._default_device_name
        date_str = datetime.datetime.now().strftime("%m-%d-%Y")
        default_name = f"{device_name} {date_str}"

        path = filedialog.asksaveasfilename(
            title="Export Configuration",
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        cfg = {}

        # Buttons
        for key, _, _ in self._button_defs:
            cfg[key] = self.pin_vars[key].get() if self.enable_vars[key].get() else -1

        # Tilt / whammy
        cfg["tilt_mode"]   = self.tilt_mode.get()
        cfg["tilt_pin"]    = self.tilt_pin.get() if self.tilt_enabled.get() else -1
        cfg["whammy_mode"] = self.whammy_mode.get()
        cfg["whammy_pin"]  = self.whammy_pin.get() if self.whammy_enabled.get() else -1

        cfg["debounce"]       = self.debounce_var.get()
        cfg["ema_alpha"]      = self.ema_alpha_var.get()
        cfg["smooth_level"]   = self.smooth_level_var.get()

        # I2C
        cfg["i2c_sda"]      = self.i2c_sda_pin.get()
        cfg["i2c_scl"]      = self.i2c_scl_pin.get()
        cfg["adxl345_axis"] = self.adxl345_axis.get()
        cfg["i2c_model"]    = self.i2c_model.get()

        # Sensitivity / invert
        cfg["tilt_min"]      = self.tilt_min.get()
        cfg["tilt_max"]      = self.tilt_max.get()
        cfg["whammy_min"]    = self.whammy_min.get()
        cfg["whammy_max"]    = self.whammy_max.get()
        cfg["tilt_invert"]   = 1 if self.tilt_invert.get()   else 0
        cfg["whammy_invert"] = 1 if self.whammy_invert.get() else 0

        # Joystick
        cfg["joy_pin_x"]        = self.joy_pin_x.get() if self.joy_x_enabled.get() else -1
        cfg["joy_pin_y"]        = self.joy_pin_y.get() if self.joy_y_enabled.get() else -1
        cfg["joy_pin_sw"]       = self.joy_pin_sw.get() if self.joy_sw_enabled.get() else -1
        cfg["joy_whammy_axis"]  = self.joy_whammy_axis.get()
        cfg["joy_dpad_x"]       = 1 if self.joy_dpad_x.get()       else 0
        cfg["joy_dpad_y"]       = 1 if self.joy_dpad_y.get()       else 0
        cfg["joy_dpad_x_invert"]= 1 if self.joy_dpad_x_invert.get() else 0
        cfg["joy_dpad_y_invert"]= 1 if self.joy_dpad_y_invert.get() else 0
        cfg["joy_deadzone"]     = self.joy_deadzone.get()

        # Device name
        cfg["device_name"] = self.device_name.get().strip() or self._default_device_name

        # LEDs
        cfg["led_enabled"]    = 1 if self.led_enabled.get() else 0
        cfg["led_count"]      = self.led_count.get()
        cfg["led_brightness"] = self._brightness_to_hw(self.led_base_brightness.get())
        cfg["led_loop_enabled"]    = 1 if self.led_loop_enabled.get() else 0
        cfg["led_loop_start"]      = self.led_loop_start.get() - 1
        cfg["led_loop_end"]        = self.led_loop_end.get() - 1
        cfg["led_breathe_enabled"] = 1 if self.led_breathe_enabled.get() else 0
        cfg["led_breathe_start"]   = self.led_breathe_start.get() - 1
        cfg["led_breathe_end"]     = self.led_breathe_end.get() - 1
        cfg["led_breathe_min"]     = self.led_breathe_min.get()
        cfg["led_breathe_max"]     = self.led_breathe_max.get()
        cfg["led_wave_enabled"]    = 1 if self.led_wave_enabled.get() else 0
        cfg["led_wave_origin"]     = self.led_wave_origin.get() - 1
        cfg["led_colors"] = [self.led_colors[i].get().upper() for i in range(MAX_LEDS)]
        cfg["led_maps"]   = [self.led_maps[i].get() for i in range(self._led_input_count)]
        cfg["led_active_br"] = [
            self._brightness_to_hw(self.led_active_br[i].get())
            for i in range(self._led_input_count)
        ]

        # sync_pin and wireless_default_mode have no dedicated UI widgets —
        # pull from the cached GET_CONFIG response so they round-trip correctly.
        raw = getattr(self, "_last_raw_cfg", {})
        cfg["sync_pin"]              = int(raw.get("sync_pin", 15))
        cfg["wireless_default_mode"] = int(raw.get("wireless_default_mode", 0))
        # device_type makes exports self-describing (needed for preset filtering)
        cfg["device_type"] = raw.get("device_type", self._default_device_type)
        cfg["quick_tune_enabled"] = 1 if self.quick_tune_enabled.get() else 0

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            messagebox.showinfo("Export Successful",
                                f"Configuration exported to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _apply_config_dict(self, cfg):
        """Apply a config dict to the UI. Raises on error - callers wrap in try/except."""
        self.quick_tune_enabled.set(
            str(cfg.get("quick_tune_enabled", "")).strip().lower()
            in ("1", "true", "yes", "on")
        )

        # Buttons
        for key, _, _ in self._button_defs:
            if key in cfg:
                pin = int(cfg[key])
                enabled = (pin != -1)
                self.pin_vars[key].set(pin if enabled else DIGITAL_PINS[1])
                self.enable_vars[key].set(enabled)
                if key in self._pin_combos:
                    actual = pin if enabled else DIGITAL_PINS[1]
                    idx = DIGITAL_PINS.index(actual) if actual in DIGITAL_PINS else 0
                    self._pin_combos[key].current(idx)
                if key in self._row_w:
                    combo, disable_cb = self._row_w[key]
                    combo.config(state="readonly" if enabled else "disabled")
                    disable_cb.config(state="normal")

        # Tilt
        if "tilt_mode" in cfg:
            self.tilt_mode.set(cfg["tilt_mode"])
        if "tilt_pin" in cfg:
            tp = int(cfg["tilt_pin"])
            self.tilt_pin.set(tp if tp >= 0 else 27)
            # In I2C mode the pin is always -1 — tilt is still enabled.
            if self.tilt_mode.get() == "i2c":
                self.tilt_enabled.set(True)
            else:
                self.tilt_enabled.set(tp >= 0)
        self._refresh_analog_combo("tilt")
        self._on_toggle_analog("tilt")

        # Whammy
        if "whammy_mode" in cfg:
            self.whammy_mode.set(cfg["whammy_mode"])
        if "whammy_pin" in cfg:
            wp = int(cfg["whammy_pin"])
            self.whammy_pin.set(wp if wp >= 0 else 26)
            self.whammy_enabled.set(wp >= 0)
        self._refresh_analog_combo("whammy")
        self._on_toggle_analog("whammy")

        if "debounce" in cfg:
            self.debounce_var.set(int(cfg["debounce"]))
        # Smoothing: prefer smooth_level; fall back to reverse-lookup ema_alpha
        if "smooth_level" in cfg:
            level = max(0, min(9, int(cfg["smooth_level"])))
            self.smooth_level_var.set(level)
            self.ema_alpha_var.set(self.EMA_ALPHA_TABLE[level])
        elif "ema_alpha" in cfg:
            fw_alpha = max(5, min(255, int(cfg["ema_alpha"])))
            best_level = min(range(len(self.EMA_ALPHA_TABLE)),
                             key=lambda i: abs(self.EMA_ALPHA_TABLE[i] - fw_alpha))
            self.smooth_level_var.set(best_level)
            self.ema_alpha_var.set(self.EMA_ALPHA_TABLE[best_level])

        # I2C
        if "i2c_sda" in cfg:
            self.i2c_sda_pin.set(int(cfg["i2c_sda"]))
        if "i2c_scl" in cfg:
            self.i2c_scl_pin.set(int(cfg["i2c_scl"]))
        if "adxl345_axis" in cfg:
            self.adxl345_axis.set(int(cfg["adxl345_axis"]))
        if "i2c_model" in cfg:
            self.i2c_model.set(int(cfg["i2c_model"]))
        self._sync_i2c_combos()

        # Sensitivity / invert
        for attr in ("tilt_min", "tilt_max", "whammy_min", "whammy_max"):
            if attr in cfg:
                getattr(self, attr).set(int(cfg[attr]))
        if "tilt_invert" in cfg:
            self.tilt_invert.set(int(cfg["tilt_invert"]) != 0)
        if "whammy_invert" in cfg:
            self.whammy_invert.set(int(cfg["whammy_invert"]) != 0)

        # Joystick
        if "joy_pin_x" in cfg:
            px = int(cfg["joy_pin_x"])
            self.joy_pin_x.set(px if px >= 0 else ANALOG_PINS[0])
            self.joy_x_enabled.set(px >= 0)
            actual = px if px >= 0 else ANALOG_PINS[0]
            if actual in ANALOG_PINS:
                self._joy_x_combo.current(ANALOG_PINS.index(actual))
                self.joy_pin_x.set(ANALOG_PINS[self._joy_x_combo.current()])
        if "joy_pin_y" in cfg:
            py = int(cfg["joy_pin_y"])
            self.joy_pin_y.set(py if py >= 0 else ANALOG_PINS[0])
            self.joy_y_enabled.set(py >= 0)
            actual = py if py >= 0 else ANALOG_PINS[0]
            if actual in ANALOG_PINS:
                self._joy_y_combo.current(ANALOG_PINS.index(actual))
                self.joy_pin_y.set(ANALOG_PINS[self._joy_y_combo.current()])
        if "joy_pin_sw" in cfg:
            ps = int(cfg["joy_pin_sw"])
            self.joy_pin_sw.set(ps if ps >= 0 else DIGITAL_PINS[1])
            self.joy_sw_enabled.set(ps >= 0)
            actual = ps if ps >= 0 else DIGITAL_PINS[1]
            if actual in DIGITAL_PINS:
                self._joy_sw_combo.current(DIGITAL_PINS.index(actual))
                self.joy_pin_sw.set(DIGITAL_PINS[self._joy_sw_combo.current()])
        # Sync both guide combos to show the same pin (prefer guide if set, else joy_sw)
        _g = self.pin_vars["guide"].get() if "guide" in self.pin_vars else -1
        _sw = self.joy_pin_sw.get()
        self._apply_guide_pin(_g if _g != -1 else _sw)
        for attr in ("joy_whammy_axis", "joy_deadzone"):
            if attr in cfg:
                getattr(self, attr).set(int(cfg[attr]))
        for attr in ("joy_dpad_x", "joy_dpad_y", "joy_dpad_x_invert", "joy_dpad_y_invert"):
            if attr in cfg:
                getattr(self, attr).set(int(cfg[attr]) != 0)
        if hasattr(self, "_refresh_joy_combos"):
            self._refresh_joy_combos(restore=True)

        # Device name
        if "device_name" in cfg:
            self.device_name.set(cfg["device_name"])

        # LEDs
        if "led_enabled" in cfg:
            self.led_enabled.set(int(cfg["led_enabled"]) != 0)
        if "led_count" in cfg:
            self.led_count.set(int(cfg["led_count"]))
        if "led_brightness" in cfg:
            self.led_base_brightness.set(
                self._brightness_from_hw(int(cfg["led_brightness"])))
        if "led_loop_enabled" in cfg:
            self.led_loop_enabled.set(int(cfg["led_loop_enabled"]) != 0)
        if "led_loop_start" in cfg:
            self.led_loop_start.set(int(cfg["led_loop_start"]) + 1)
        if "led_loop_end" in cfg:
            self.led_loop_end.set(int(cfg["led_loop_end"]) + 1)
        if "led_breathe_enabled" in cfg:
            self.led_breathe_enabled.set(int(cfg["led_breathe_enabled"]) != 0)
        if "led_breathe_start" in cfg:
            self.led_breathe_start.set(int(cfg["led_breathe_start"]) + 1)
        if "led_breathe_end" in cfg:
            self.led_breathe_end.set(int(cfg["led_breathe_end"]) + 1)
        if "led_breathe_min" in cfg:
            self.led_breathe_min.set(int(cfg["led_breathe_min"]))
        if "led_breathe_max" in cfg:
            self.led_breathe_max.set(int(cfg["led_breathe_max"]))
        if "led_wave_enabled" in cfg:
            self.led_wave_enabled.set(int(cfg["led_wave_enabled"]) != 0)
        if "led_wave_origin" in cfg:
            self.led_wave_origin.set(int(cfg["led_wave_origin"]) + 1)
        if "led_loop_speed" in cfg:
            self.led_loop_speed.set(max(100, min(9999, int(cfg["led_loop_speed"]))))
        if "led_breathe_speed" in cfg:
            self.led_breathe_speed.set(max(100, min(9999, int(cfg["led_breathe_speed"]))))
        if "led_wave_speed" in cfg:
            self.led_wave_speed.set(max(100, min(9999, int(cfg["led_wave_speed"]))))
        if "led_colors" in cfg:
            for i, c in enumerate(cfg["led_colors"]):
                if i < MAX_LEDS and len(str(c)) == 6:
                    self.led_colors[i].set(str(c).upper())
        if "led_maps" in cfg:
            for i, m in enumerate(cfg["led_maps"]):
                if i < self._led_input_count:
                    self.led_maps[i].set(int(m))
        if "led_active_br" in cfg:
            for i, b in enumerate(cfg["led_active_br"]):
                if i < self._led_input_count:
                    self.led_active_br[i].set(self._brightness_from_hw(int(b)))

        any_mapped = any(self.led_maps[i].get() != 0 for i in range(self._led_input_count))
        self.led_reactive.set(any_mapped)
        for i in range(self._led_input_count):
            self._led_maps_backup[i] = self.led_maps[i].get()

        self._on_led_toggle()
        if self.led_enabled.get():
            self._rebuild_led_color_grid()
            if self.led_reactive.get():
                self._rebuild_led_map_grid()

        # sync_pin and wireless_default_mode have no UI widgets — push
        # directly to the firmware now if connected, and update the cache
        # so a subsequent export round-trips the imported values correctly.
        raw_cache = getattr(self, "_last_raw_cfg", {})
        if "sync_pin" in cfg:
            raw_cache["sync_pin"] = str(int(cfg["sync_pin"]))
            if self.pico.connected:
                try:
                    self.pico.set_value("sync_pin", raw_cache["sync_pin"])
                except Exception:
                    pass
        if "wireless_default_mode" in cfg:
            raw_cache["wireless_default_mode"] = str(int(cfg["wireless_default_mode"]))
            if self.pico.connected:
                try:
                    self.pico.set_value("wireless_default_mode",
                                        raw_cache["wireless_default_mode"])
                except Exception:
                    pass
        self._last_raw_cfg = raw_cache

    def _import_config(self):
        """Load a JSON config file and apply it to the UI (does NOT auto-save)."""
        path = filedialog.askopenfilename(
            title="Import Configuration",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as exc:
            messagebox.showerror("Import Error", f"Could not read file:\n{exc}")
            return

        try:
            self._apply_config_dict(cfg)
            messagebox.showinfo("Import Successful",
                                "Configuration loaded into UI.\n"
                                "Click Save or Save & Play to apply it to the controller.")
        except Exception as exc:
            messagebox.showerror("Import Error", f"Failed to apply config:\n{exc}")

    def _import_preset(self, filepath):
        """Load a preset JSON directly into the UI (same as import but no file dialog)."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as exc:
            messagebox.showerror("Preset Error", f"Could not read preset:\n{exc}")
            return

        try:
            self._apply_config_dict(cfg)
            messagebox.showinfo("Preset Loaded",
                                "Preset applied to UI.\n"
                                "Click Save or Save & Play to apply it to the controller.")
        except Exception as exc:
            messagebox.showerror("Preset Error", f"Failed to apply preset:\n{exc}")

    def _save_config(self):
        if not self.pico.connected:
            return
        try:
            self._save_configuration_common(reboot_after_save=False)
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    def _save_and_reboot(self):
        if not self.pico.connected:
            return
        if not messagebox.askyesno("Save & Play",
                "Save configuration and return to Play Mode?"):
            return
        try:
            saved = self._save_configuration_common(reboot_after_save=True)
        except Exception as exc:
            messagebox.showerror("Error", f"Save failed: {exc}")
            return
        if not saved:
            return

    def _reset_defaults(self):
        if not self.pico.connected:
            return
        if not messagebox.askyesno("Reset", "Reset all to factory defaults?"):
            return
        try:
            self._stop_monitoring()
            self.pico.defaults()
            self._load_config()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    # ── Pin Detection ───────────────────────────────────────

    def _start_detect(self, target_key, target_name):
        if not self.pico.connected:
            return
        if self.scanning:
            self._cancel_detect()
            return

        # Stop monitoring if active
        self._stop_monitoring()

        self.scan_target = target_key
        self.scanning = True
        self._scan_i2c_found = False

        for key, btn in self._det_btns.items():
            try:
                btn.config(state="disabled" if key != target_key else "normal",
                           text="Stop" if key == target_key else "Detect")
            except Exception:
                pass

        self._set_status(f"   Detecting pin for {target_name} — press the button now...", ACCENT_BLUE)
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        try:
            pre_lines = self.pico.start_scan()
            # Check for I2C detection in pre-lines
            for line in pre_lines:
                if line.startswith("I2C:"):
                    self._scan_i2c_found = True
                    device = line[4:]
                    # If we're detecting a tilt pin, auto-select I2C
                    if self.scan_target == "tilt_pin":
                        self.root.after(0, lambda d=device: self._on_i2c_detected(d))
                        return
                    else:
                        # Update status to show I2C was found
                        self.root.after(0, lambda d=device:
                            self._set_status(f"   Found {d} on I2C — waiting for GPIO/ADC...", ACCENT_BLUE))
        except Exception as exc:
            self.root.after(0, lambda: self._on_scan_error(str(exc)))
            return

        # For whammy, fire on the first APIN the firmware sends. The firmware's own
        # threshold already filters ADC noise, so no extra delta check is needed here.
        # (Adding a second delta hurdle breaks narrow-range whammies like 1900–2050.)
        _apin_baseline = {}   # kept for reference but no longer used as a gate

        while self.scanning:
            try:
                line = self.pico.read_scan_line(0.2)
                if line:
                    if line.startswith("PIN:"):
                        pin_num = int(line[4:])
                        self.root.after(0, lambda p=pin_num: self._on_pin_detected(p))
                        break
                    elif line.startswith("APIN:"):
                        # APIN:pin:value — fire immediately on first report from firmware
                        parts = line[5:].split(":")
                        pin_num = int(parts[0])
                        # For all targets: fire on first APIN
                        self.root.after(0, lambda p=pin_num: self._on_pin_detected(p))
                        break
            except Exception:
                if self.scanning:
                    self.root.after(0, lambda: self._on_scan_error("Lost connection"))
                return

    def _on_i2c_detected(self, device_name):
        """Handle I2C device detection during scan."""
        try:
            self.pico.stop_scan()
        except Exception:
            pass
        self.scanning = False
        target = self.scan_target

        if target == "tilt_pin":
            # Set tilt to I2C mode and select the correct chip model
            self.tilt_mode.set("i2c")
            self.tilt_enabled.set(True)
            # Map detected chip name to i2c_model value
            chip_name_upper = device_name.upper()
            if "LIS3DH" in chip_name_upper:
                self.i2c_model.set(1)
            else:
                self.i2c_model.set(0)   # default to ADXL345
            self._refresh_analog_combo("tilt")
            self._on_toggle_analog("tilt")
            self._sync_i2c_combos()

        self._restore_detect_buttons()
        self._set_status(
            f"   Found {device_name} accelerometer — tilt set to I2C "
            f"(SDA: GPIO {self.i2c_sda_pin.get()}, SCL: GPIO {self.i2c_scl_pin.get()})",
            ACCENT_GREEN)

    def _on_pin_detected(self, pin):
        try:
            self.pico.stop_scan()
        except Exception:
            pass
        self.scanning = False
        target = self.scan_target

        if target in self.pin_vars and target in self._pin_combos:
            self.pin_vars[target].set(pin)
            self.enable_vars[target].set(True)
            if pin in DIGITAL_PINS:
                self._pin_combos[target].current(DIGITAL_PINS.index(pin))
            if target in self._row_w:
                c, d = self._row_w[target]
                c.config(state="readonly")
                d.config(state="normal")
            if target == "guide":
                self._apply_guide_pin(pin)
        elif target in ("tilt_pin", "whammy_pin"):
            prefix = target.replace("_pin", "")
            if prefix in self._sp_combos:
                combo, mode_var, pin_var, enable_var = self._sp_combos[prefix][:4]
                pin_var.set(pin)
                enable_var.set(True)
                if pin in self._axis_analog_pins():
                    mode_var.set("analog")
                self._refresh_analog_combo(prefix)
                self._on_toggle_analog(prefix)
        elif target in ("joy_x", "joy_y"):
            # Joystick analog axis detect — pin must be an ADC pin
            if pin in ANALOG_PINS:
                if target == "joy_x":
                    self.joy_pin_x.set(pin)
                    self.joy_x_enabled.set(True)
                    self._joy_x_combo.current(ANALOG_PINS.index(pin))
                else:
                    self.joy_pin_y.set(pin)
                    self.joy_y_enabled.set(True)
                    self._joy_y_combo.current(ANALOG_PINS.index(pin))
                if hasattr(self, "_refresh_joy_combos"):
                    self._refresh_joy_combos(restore=True)
            else:
                self._restore_detect_buttons()
                self._set_status(
                    f"   GPIO {pin} is not an ADC pin — joystick VRx/VRy need GP26–28",
                    ACCENT_ORANGE)
                return
        elif target == "joy_sw":
            # Joystick click switch — any digital GPIO; syncs guide combo too
            self._apply_guide_pin(pin)

        self._restore_detect_buttons()

        label = DIGITAL_PIN_LABELS.get(pin, f"GPIO {pin}")
        extra = "  (analog)" if pin in self._axis_analog_pins() else ""
        self._set_status(f"   Detected {label}{extra}", ACCENT_GREEN)

    def _cancel_detect(self):
        self.scanning = False
        try:
            self.pico.stop_scan()
        except Exception:
            pass
        self._restore_detect_buttons()
        self._set_status("")

    def _on_scan_error(self, msg):
        self.scanning = False
        self._restore_detect_buttons()
        self._set_status(f"   Scan error: {msg}", ACCENT_ORANGE)

    def _restore_detect_buttons(self):
        for btn in self._det_btns.values():
            try:
                btn.config(state="normal", text="Detect")
            except Exception:
                pass

    # ── Firmware Menu ───────────────────────────────────────

    def _flash_firmware(self, uf2=None):
        """One-click firmware flash. Detects device state automatically and
        handles the full sequence: XInput magic → config mode → BOOTSEL → flash."""
        if not uf2:
            uf2 = filedialog.askopenfilename(
                title="Select UF2 Firmware File",
                filetypes=[("UF2 Firmware", "*.uf2"), ("All Files", "*.*")])
            if not uf2:
                return

        # Warn if flashing mismatched firmware family (wired ↔ wireless)
        _selected_base = os.path.basename(uf2)
        _current_is_wired = getattr(self, "_loaded_device_type", None) not in ("guitar_combined",)
        _flashing_wireless = _selected_base.startswith("Wireless_")
        _flashing_wired    = _selected_base.startswith("Wired_")

        if _current_is_wired and _flashing_wireless:
            if not messagebox.askyesno(
                "Firmware Mismatch",
                "Wired firmware is currently installed.\n\n"
                "Are you sure you want to install wireless firmware?"):
                return

        if not _current_is_wired and _flashing_wired:
            if not messagebox.askyesno(
                "Firmware Mismatch",
                "Wireless firmware is currently installed.\n\n"
                "Are you sure you want to install wired firmware?"):
                return

        # Send BOOTSEL now if in config mode — before hide() reboots to play mode.
        # hide() checks self.pico.connected; if we disconnect first it skips reboot.
        _booting_from_config = False
        if self.pico.connected:
            try:
                self.pico.bootsel()
                self.pico.disconnect()
                _booting_from_config = True
            except Exception:
                pass

        # Go to main menu immediately and show flash status popup
        if self._on_back:
            self._on_back()
        _flash_popup, _close_flash_popup = _make_flash_popup(self.root)
        def _worker():
            # ── Step 1: get to BOOTSEL drive ────────────────────────────
            drive = find_rpi_rp2_drive()

            if not drive:
                if _booting_from_config:
                    # Already sent BOOTSEL before navigating away — wait for drive
                    drive = self._wait_for_drive(12.0)
                elif self.pico.connected:
                    # Config mode → send BOOTSEL directly
                    self.root.after(0, lambda: self._set_status(
                        "   Entering BOOTSEL mode...", ACCENT_ORANGE))
                    try:
                        self.pico.bootsel()
                        self.pico.disconnect()
                    except Exception:
                        pass
                    self.root.after(0, lambda: [
                        self.connect_btn.set_state("normal"),
                        self.manual_btn.set_state("normal"),
                        self.save_reboot_btn.set_state("disabled"),
                        self._set_controls_enabled(False),
                    ])
                    drive = self._wait_for_drive(12.0)

                elif XINPUT_AVAILABLE:
                    # XInput play mode → magic sequence → config mode → BOOTSEL
                    self.root.after(0, lambda: self._set_status(
                        "   Scanning for XInput controller...", ACCENT_BLUE))
                    controllers = xinput_get_connected()
                    occ = [c for c in controllers if c[1] in OCC_SUBTYPES]
                    if not occ:
                        self.root.after(0, lambda: [
                            self._set_status("   No OCC controller found", ACCENT_RED),
                            messagebox.showwarning("Not Found",
                                "No OCC controller detected in play mode.\n\n"
                                "Make sure the controller is plugged in, then try again.\n"
                                "If the problem persists, hold BOOTSEL while plugging in.")
                        ])
                        return
                    slot = occ[0][0]
                    self.root.after(0, lambda: self._set_status(
                        "   Sending config signal...", ACCENT_BLUE))
                    for left, right in MAGIC_STEPS:
                        xinput_send_vibration(slot, left, right)
                        time.sleep(0.08)
                    xinput_send_vibration(slot, 0, 0)

                    self.root.after(0, lambda: self._set_status(
                        "   Waiting for config mode...", ACCENT_BLUE))
                    port = self._wait_for_port(10.0)
                    if not port:
                        self.root.after(0, lambda: [
                            self._set_status("   Controller didn't enter config mode", ACCENT_RED),
                            messagebox.showwarning("Timeout",
                                "The controller didn't switch to config mode.\n"
                                "Close any games using the controller and try again.")
                        ])
                        return

                    self.root.after(0, lambda: self._set_status(
                        "   Entering BOOTSEL mode...", ACCENT_ORANGE))
                    try:
                        tmp = PicoSerial()
                        tmp.connect(port)
                        for _ in range(3):
                            if tmp.ping():
                                break
                            time.sleep(0.3)
                        tmp.bootsel()
                        tmp.disconnect()
                    except Exception as exc:
                        self.root.after(0, lambda e=str(exc): [
                            self._set_status(f"   BOOTSEL failed: {e}", ACCENT_RED),
                            messagebox.showerror("BOOTSEL Error",
                                f"Could not enter BOOTSEL mode:\n{e}")
                        ])
                        return
                    drive = self._wait_for_drive(12.0)

                else:
                    # Not connected, no XInput available
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Controller Not Found",
                        "No controller detected.\n\n"
                        "To flash firmware manually:\n"
                        "  1. Hold the BOOTSEL button on the Pico\n"
                        "  2. Plug it in while holding BOOTSEL\n"
                        "  3. The RPI-RP2 drive will appear\n"
                        "  4. Try Flash Firmware again\n\n"
                        "Or connect the controller first via the Connect button."))
                    return

            if not drive:
                self.root.after(0, lambda: [
                    self._set_status("   RPI-RP2 drive not found", ACCENT_RED),
                    messagebox.showwarning("Timeout",
                        "The RPI-RP2 drive didn't appear.\n"
                        "Try holding BOOTSEL while plugging in manually.")
                ])
                return

            # ── Step 2: flash the UF2 ───────────────────────────────────
            self.root.after(0, lambda d=drive: self._set_status(
                f"   Flashing firmware to {d}...", ACCENT_ORANGE))
            try:
                def _flash_status(msg):
                    self.root.after(0, lambda m=msg: self._set_status(
                        f"   {m}", ACCENT_ORANGE))
                flash_uf2_with_reboot(uf2, drive, status_cb=_flash_status)
                self.root.after(0, lambda: [
                    self._set_status("   Firmware flashed!", ACCENT_GREEN),
                    messagebox.showinfo("Success",
                        f"Firmware flashed successfully!\n\n"
                        f"File: {os.path.basename(uf2)}\n"
                        f"Drive: {drive}\n\n"
                        "The Pico will reboot into play mode.\n"
                        "Click 'Connect' to configure it.")
                ])
            except Exception as exc:
                self.root.after(0, lambda e=str(exc): [
                    self._set_status("   Flash failed", ACCENT_RED),
                    messagebox.showerror("Flash Error", e)
                ])

        def _worker_wrapper():
            try:
                _worker()
            finally:
                self.root.after(0, _close_flash_popup)
        threading.Thread(target=_worker_wrapper, daemon=True).start()

    def _wait_for_drive(self, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            drive = find_rpi_rp2_drive()
            if drive:
                time.sleep(0.5)
                return drive
            time.sleep(0.5)
            self.root.update_idletasks()
        return None

    def _enter_bootsel(self):
        was_connected = self.pico.connected
        enter_bootsel_for(self)
        # If we were connected and just entered BOOTSEL, the device is gone —
        # disable the guitar-specific config controls so the UI reflects this.
        if was_connected and not self.pico.connected:
            self.connect_btn.set_state("normal")
            self.manual_btn.set_state("normal")
            self.save_reboot_btn.set_state("disabled")
            self._set_controls_enabled(False)

    # ── Serial Debug Console ─────────────────────────────────

    def _debug_log(self, line):
        """Append a line to the debug console text widget (called from any thread)."""
        txt = getattr(self, '_debug_text', None)
        if txt is None:
            return
        try:
            txt.configure(state="normal")
            txt.insert("end", line + "\n")
            # Trim to last 500 lines so the widget never grows unbounded
            total = int(txt.index("end-1c").split(".")[0])
            if total > 500:
                txt.delete("1.0", f"{total - 500}.0")
            txt.see("end")
            txt.configure(state="disabled")
        except Exception:
            pass

    def _show_serial_debug(self):
        """Open a resizable serial debug console.

        • All raw bytes from the Pico are displayed in the output pane.
        • Type any command in the entry box and press Enter or click Send.
        • Quick-buttons cover the most common diagnostic commands.
        • A background thread drains the serial buffer when not monitoring,
          so spontaneous Pico output still appears.
        """
        # If already open just bring it forward
        if getattr(self, '_debug_win', None):
            try:
                if self._debug_win.winfo_exists():
                    self._debug_win.lift()
                    self._debug_win.focus_force()
                    return
            except Exception:
                pass

        # ── Create window — NOT transient so it gets its own taskbar entry
        # and never has its keyboard focus stolen by the main window.
        win = tk.Toplevel()          # no parent → independent window
        win.title("Serial Debug Console")
        win.configure(bg=BG_MAIN)
        win.geometry("700x520")
        win.minsize(500, 380)
        win.resizable(True, True)
        self._debug_win = win

        # ── Thread-safe output queue — only the reader thread touches ser ──
        import queue as _queue
        _send_queue = _queue.Queue()

        # ── Helper: write one tagged line to the output pane ──────────────
        TAG_OUT  = "out"    # lines we send  → dim green
        TAG_IN   = "in"     # lines received → bright green
        TAG_ERR  = "err"    # errors         → red
        TAG_INFO = "info"   # local notes    → blue/grey

        def _log(line, tag=TAG_IN):
            txt = getattr(self, '_debug_text', None)
            if txt is None:
                return
            try:
                txt.configure(state="normal")
                txt.insert("end", line + "\n", tag)
                total = int(txt.index("end-1c").split(".")[0])
                if total > 600:
                    txt.delete("1.0", f"{total - 600}.0")
                txt.see("end")
                txt.configure(state="disabled")
            except Exception:
                pass

        # ── Send a command — just enqueues it; reader thread does the I/O ──
        def _send_raw(cmd):
            _log(f">> {cmd}", TAG_OUT)
            if not self.pico.connected:
                _log("!! Not connected — open the main configurator and connect first.", TAG_ERR)
                return
            _send_queue.put(cmd.strip())

        # ── Current config info bar ────────────────────────────────────────
        info_frame = tk.Frame(win, bg=BG_CARD)
        info_frame.pack(fill="x", padx=8, pady=(8, 0), ipady=5)
        tk.Label(info_frame, text="Config:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8, "bold")).pack(side="left", padx=(8, 4))
        info_lbl = tk.Label(info_frame, text="", bg=BG_CARD, fg=TEXT,
                            font=("Consolas", 8))
        info_lbl.pack(side="left", fill="x", expand=True)

        def _refresh_info():
            parts = []
            mode  = getattr(self, 'tilt_mode', None)
            sda   = getattr(self, 'i2c_sda_pin', None)
            scl   = getattr(self, 'i2c_scl_pin', None)
            axis  = getattr(self, 'adxl345_axis', None)
            model = getattr(self, 'i2c_model', None)
            conn  = getattr(self, 'pico', None)
            parts.append("connected" if (conn and conn.connected) else "NOT connected")
            if mode:  parts.append(f"tilt={mode.get()}")
            if mode and mode.get() == "i2c":
                if model is not None:
                    m = model.get()
                    chip = I2C_MODEL_LABELS[I2C_MODEL_VALUES.index(m)] if m in I2C_MODEL_VALUES else f"model={m}"
                    parts.append(f"chip={chip}")
                if sda:  parts.append(f"SDA=GP{sda.get()}")
                if scl:  parts.append(f"SCL=GP{scl.get()}")
                if axis is not None:
                    parts.append(f"axis={'XYZ'[axis.get()]}")
            info_lbl.config(text="   |   ".join(parts))

        _refresh_info()
        tk.Button(info_frame, text="↺ Refresh", bg=BG_INPUT, fg=TEXT_DIM,
                  font=(FONT_UI, 7), relief="flat", bd=0, padx=6,
                  command=_refresh_info).pack(side="right", padx=6)

        # ── Quick-command button bar ───────────────────────────────────────
        qbar = tk.Frame(win, bg=BG_MAIN)
        qbar.pack(fill="x", padx=8, pady=(6, 0))

        QUICK = [
            ("PING",        "PING",        ACCENT_BLUE),
            ("GET CONFIG",  "GET_CONFIG",  ACCENT_BLUE),
            ("SCAN",        "SCAN",        ACCENT_BLUE),
            ("MONITOR I2C", "MONITOR_I2C", ACCENT_GREEN),
            ("STOP",        "STOP",        ACCENT_ORANGE),
            ("REBOOT",      "REBOOT",      ACCENT_RED),
        ]
        for lbl, cmd, color in QUICK:
            RoundedButton(qbar, text=lbl, command=lambda c=cmd: _send_raw(c),
                          bg_color=color, btn_width=90, btn_height=24,
                          btn_font=(FONT_UI, 7, "bold")).pack(
                side="left", padx=(0, 4), pady=2)

        # ── Command reference (collapsible) ───────────────────────────────
        ref_frame = tk.Frame(win, bg=BG_CARD)
        ref_frame.pack(fill="x", padx=8, pady=(4, 0))

        REF_LINES = [
            "PING                         → PONG  (connection check)",
            "GET_CONFIG                   → CFG:/LED:/LED_COLORS:/LED_MAP: lines",
            "SCAN                         → streams PIN:N or APIN:N:val on input change; send STOP to end",
            "STOP                         → ends SCAN or MONITOR mode",
            "MONITOR_I2C                  → streams MVAL_X/Y/Z: lines at 20 Hz (debug); send STOP to end",
            "MONITOR_I2C:<0|1|2>          → streams MVAL: for one axis at 50 Hz; send STOP to end",
            "MONITOR_ADC:<pin>            → streams MVAL:<val> for GP26/27/28/29; send STOP to end",
            "MONITOR_DIG:<pin>            → streams MVAL:0 or MVAL:4095; send STOP to end",
            "SET:<key>=<value>            → set one config value, replies OK or ERR:reason",
            "  e.g.  SET:i2c_sda=4       → set SDA pin to GP4",
            "  e.g.  SET:adxl345_axis=0  → 0=X  1=Y  2=Z",
            "  e.g.  SET:tilt_mode=i2c   → enable I2C accelerometer tilt",
            "  e.g.  SET:i2c_model=0     → 0=ADXL345/GY-291  1=LIS3DH",
            "SAVE                         → write current config to flash",
            "DEFAULTS                     → reset all config to factory defaults",
            "REBOOT                       → restart into play mode",
            "BOOTSEL                      → restart into USB mass-storage (UF2 flash) mode",
        ]

        ref_visible = tk.BooleanVar(value=False)
        ref_body = tk.Frame(win, bg=BG_CARD)

        ref_text = tk.Text(ref_body, bg="#111116", fg="#8888aa",
                           font=("Consolas", 8), height=len(REF_LINES),
                           state="normal", wrap="none", relief="flat",
                           bd=0, highlightthickness=0)
        ref_text.pack(fill="x", padx=8, pady=(0, 6))
        for ln in REF_LINES:
            ref_text.insert("end", ln + "\n")
        ref_text.configure(state="disabled")

        def _toggle_ref():
            if ref_visible.get():
                ref_body.pack_forget()
                ref_visible.set(False)
                ref_toggle_btn.config(text="▶ Command Reference")
            else:
                ref_body.pack(fill="x", padx=8, after=ref_frame)
                ref_visible.set(True)
                ref_toggle_btn.config(text="▼ Command Reference")

        ref_toggle_btn = tk.Button(
            ref_frame, text="▶ Command Reference",
            bg=BG_CARD, fg=ACCENT_BLUE, font=(FONT_UI, 8),
            relief="flat", bd=0, anchor="w", padx=8, pady=4,
            command=_toggle_ref)
        ref_toggle_btn.pack(fill="x")

        # ── Output pane ───────────────────────────────────────────────────
        out_frame = tk.Frame(win, bg=BG_MAIN)
        out_frame.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        vsb = ttk.Scrollbar(out_frame, orient="vertical")
        vsb.pack(side="right", fill="y")
        hsb = ttk.Scrollbar(out_frame, orient="horizontal")
        hsb.pack(side="bottom", fill="x")

        self._debug_text = tk.Text(
            out_frame, bg="#0d0d12", fg="#b0ffb0",
            font=("Consolas", 9), state="disabled",
            wrap="none", relief="flat", bd=0,
            highlightthickness=1, highlightbackground=BORDER,
            yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._debug_text.pack(fill="both", expand=True)
        vsb.config(command=self._debug_text.yview)
        hsb.config(command=self._debug_text.xview)

        # Colour tags
        self._debug_text.tag_config(TAG_OUT,  foreground="#668866")  # sent  - dim green
        self._debug_text.tag_config(TAG_IN,   foreground="#b0ffb0")  # recv  - bright green
        self._debug_text.tag_config(TAG_ERR,  foreground="#ff6060")  # error - red
        self._debug_text.tag_config(TAG_INFO, foreground="#6699cc")  # info  - blue

        # ── Send row ──────────────────────────────────────────────────────
        send_frame = tk.Frame(win, bg=BG_MAIN)
        send_frame.pack(fill="x", padx=8, pady=6)

        # Prompt label so it's obvious the box is for input
        tk.Label(send_frame, text="CMD:", bg=BG_MAIN, fg=TEXT_DIM,
                 font=("Consolas", 9, "bold")).pack(side="left", padx=(0, 4))

        entry_var = tk.StringVar()
        entry = tk.Entry(
            send_frame, textvariable=entry_var,
            bg=BG_INPUT, fg="#ffffff",
            insertbackground="#ffffff",   # cursor colour
            font=("Consolas", 10),
            relief="flat",
            highlightthickness=2,
            highlightcolor=ACCENT_BLUE,
            highlightbackground=BORDER)
        entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))

        def _do_send(_event=None):
            cmd = entry_var.get().strip()
            if not cmd:
                return
            entry_var.set("")
            entry.focus_set()
            _send_raw(cmd)

        entry.bind("<Return>", _do_send)

        RoundedButton(send_frame, text="Send ↵", command=_do_send,
                      bg_color=ACCENT_GREEN, btn_width=75, btn_height=30,
                      btn_font=(FONT_UI, 8, "bold")).pack(side="left", padx=(0, 4))

        def _clear():
            self._debug_text.configure(state="normal")
            self._debug_text.delete("1.0", "end")
            self._debug_text.configure(state="disabled")

        RoundedButton(send_frame, text="Clear", command=_clear,
                      bg_color="#555560", btn_width=60, btn_height=30,
                      btn_font=(FONT_UI, 8, "bold")).pack(side="left")

        # ── Combined send/receive thread — owns serial exclusively ───────
        # This thread is the ONLY place that touches ser.read/write while
        # the debug console is open, so there's no timeout contention with
        # the main thread and no blocking of the Tk event loop.
        self._debug_reader_running = True

        def _reader_thread():
            while self._debug_reader_running:
                if not getattr(self, '_debug_win', None):
                    break
                try:
                    if not self.pico.connected:
                        time.sleep(0.2)
                        continue

                    ser = self.pico.ser

                    # Drain any pending send first (non-blocking check)
                    try:
                        cmd = _send_queue.get_nowait()
                        try:
                            ser.write((cmd + "\n").encode())
                            ser.flush()
                        except Exception as exc:
                            win.after(0, lambda e=str(exc): _log(f"!! Write error: {e}", TAG_ERR))
                    except _queue.Empty:
                        pass

                    # Read any waiting bytes (short timeout so we loop fast)
                    old_to = ser.timeout
                    ser.timeout = 0.05
                    try:
                        raw = ser.readline()
                    finally:
                        ser.timeout = old_to

                    line = raw.decode("ascii", errors="replace").strip() if raw else ""
                    if line:
                        win.after(0, lambda l=line: _log(f"<< {l}", TAG_IN))

                except Exception:
                    time.sleep(0.1)

        reader = threading.Thread(target=_reader_thread, daemon=True)
        reader.start()

        # ── Cleanup ───────────────────────────────────────────────────────
        def _on_close():
            self._debug_reader_running = False
            self._debug_text = None
            self._debug_win  = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)

        # ── Initial messages ──────────────────────────────────────────────
        _log("=== Serial Debug Console ===", TAG_INFO)
        _log("Type a command below and press Enter, or use the quick buttons above.", TAG_INFO)
        _log("Click '▶ Command Reference' to see all available commands.", TAG_INFO)
        _log("", TAG_INFO)

        # Give the entry keyboard focus immediately
        win.after(50, entry.focus_set)

    def _show_about(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("About")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)

        frame = tk.Frame(dlg, bg=BG_CARD)
        frame.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(frame, text="OCC - Open Controller Configurator", bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 14, "bold")).pack(pady=(0, 4))
        tk.Label(frame, text="Configurator v5", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 11)).pack(pady=(0, 12))
        tk.Label(frame,
                 text="XInput Guitar Alternate firmware\n"
                      "for Raspberry Pi Pico\n"
                      "with one-click config and firmware flashing.\n\n"
                      "Supports: ADXL345 & LIS3DH I2C accelerometers,\n"
                      "OH49E hall sensor, live sensor monitoring.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9), justify="center").pack()
        RoundedButton(frame, text="OK", command=dlg.destroy,
                      bg_color=ACCENT_BLUE, btn_width=80, btn_height=28,
                      btn_font=(FONT_UI, 8, "bold")).pack(pady=(12, 0))
        _center_window(dlg, self.root)
        dlg.grab_set()
        dlg.wait_window()
