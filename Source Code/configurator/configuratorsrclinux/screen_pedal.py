import sys, os, time, threading, json, datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .constants import (BG_MAIN, BG_CARD, BG_INPUT, BG_HOVER, BORDER, TEXT, TEXT_DIM,
                         TEXT_HEADER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
                         DIGITAL_PINS, DIGITAL_PIN_LABELS, VALID_NAME_CHARS, OCC_SUBTYPES,
                         MAX_LEDS, PEDAL_LED_INPUT_NAMES, PEDAL_LED_INPUT_LABELS)
from .fonts import FONT_UI, APP_VERSION
from .widgets import (RoundedButton, HelpButton, HelpDialog, CustomDropdown,
                       SpeedSlider, LiveBarGraph, CalibratedBarGraph, _help_text)
from .serial_comms import PicoSerial
from .firmware_utils import (flash_uf2_with_reboot, enter_bootsel_for,
                              find_uf2_files, find_uf2_for_device_type,
                              get_bundled_fw_date_str, find_rpi_rp2_drive,
                              apply_config_to_pico)
from .xinput_utils import (XINPUT_AVAILABLE, ERROR_SUCCESS, xinput_get_connected,
                           MAGIC_STEPS, xinput_send_vibration)
from .utils import _centered_dialog, _center_window, _make_flash_popup, _find_preset_configs
class PedalApp:
    """
    Pedal Controller configurator screen.

    Configures up to 4 pedal buttons, 2 analog inputs, USB host settings,
    and pedal LED lighting.
    """

    PEDAL_COUNT = 4

    # Human-readable names for each button_index_t value (0-13), matching firmware enum.
    BUTTON_INDEX_LABELS = [
        "Green (A)",      # 0
        "Red (B)",        # 1
        "Yellow (Y)",     # 2
        "Blue (X)",       # 3
        "Orange (LB)",    # 4
        "Strum Up",       # 5
        "Strum Down",     # 6
        "Start",          # 7
        "Select",         # 8
        "D-Pad Up",       # 9
        "D-Pad Down",     # 10
        "D-Pad Left",     # 11
        "D-Pad Right",    # 12
        "Guide",          # 13
        "Whammy (100%)",  # 14 — drives right_stick_x to +32767 while held
        "Tilt (100%)",    # 15 — drives right_stick_y to +32767 while held
    ]

    # ADC-capable GPIO pins only (RP2040 ADC0–ADC2)
    ADC_PINS        = [-1, 26, 27, 28]
    ADC_PIN_LABELS  = ["Disabled", "GPIO 26  (ADC0)", "GPIO 27  (ADC1)", "GPIO 28  (ADC2)"]
    ADC_AXIS_LABELS = ["Whammy", "Tilt"]
    USB_HOST_START_PINS = [p for p in DIGITAL_PINS if p >= 0 and (p + 1) in DIGITAL_PINS]
    USB_HOST_START_LABELS = [f"GPIO {p} / GPIO {p + 1}" for p in USB_HOST_START_PINS]
    USB_HOST_ORDER_LABELS = [
        "D+ on first pin, D- on second",
        "D- on first pin, D+ on second",
    ]
    LED_SPI_PINS = {6, 7}
    PEDAL_LED_INPUT_INDICES = [0, 1, 2, 3]

    def __init__(self, root, on_back=None):
        self.root = root
        self._on_back = on_back
        self.root.configure(bg=BG_MAIN)

        self.pico = PicoSerial()
        self.frame = tk.Frame(root, bg=BG_MAIN)
        self._status_var = tk.StringVar(value="")
        self._debug_win  = None
        self._debug_text = None
        self._debug_reader_running = False
        self._help_dialog = None

        self._build_menu()
        self._build_ui()

    # ── Menu bar ────────────────────────────────────────────────────

    def _build_menu(self):
        mb = tk.Menu(self.root, bg=BG_CARD, fg=TEXT,
                     activebackground=ACCENT_BLUE, activeforeground="#fff", bd=0)

        adv = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT,
                      activebackground=ACCENT_BLUE, activeforeground="#fff")

        uf2_list = find_uf2_files()
        if uf2_list:
            flash_sub = tk.Menu(adv, tearoff=0, bg=BG_CARD, fg=TEXT,
                                activebackground=ACCENT_BLUE, activeforeground="#fff")
            for display_name, full_path in uf2_list:
                flash_sub.add_command(
                    label=display_name,
                    command=lambda p=full_path: self._flash_firmware(p))
            flash_sub.add_separator()
            flash_sub.add_command(label="Browse for .uf2...",
                                  command=lambda: self._flash_firmware(None))
            adv.add_cascade(label="Flash Firmware to Pico...", menu=flash_sub)
        else:
            adv.add_command(label="Flash Firmware to Pico...",
                            command=lambda: self._flash_firmware(None))

        adv.add_command(label="Enter BOOTSEL Mode", command=self._enter_bootsel)
        adv.add_separator()
        adv.add_command(label="Export Configuration...", command=self._export_config)
        adv.add_command(label="Import Configuration...", command=self._import_config)
        adv.add_separator()
        adv.add_command(label="Serial Debug Console", command=self._show_serial_debug)
        adv.add_separator()
        adv.add_command(label="Exit", command=self._on_close)
        mb.add_cascade(label="Advanced", menu=adv)

        pm = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT,
                     activebackground=ACCENT_BLUE, activeforeground="#fff")
        presets = _find_preset_configs({"pedal"})
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

        self._menu_bar = mb

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
                    ("Controller LEDs are communicated through GPIO 6 and GPIO 7. Tell OCC how many LEDs are in series on those LED pins, and you can individually address each one.", None),
                    ("\n\n", None),
                    ("OCC has multiple lighting effects programmed in:", "bold"),
                    ("\n\n", None),
                    ("LED Color Loop", "bold"),
                    ("\n\n", None),
                    ("Set the starting and ending LED you'd like to loop, and while the controller is on, it will make the LEDs gradually fade into each other's color, looping.", None),
                    ("\n\n", None),
                    ("LED Breathe", "bold"),
                    ("\n\n", None),
                    ("Set the starting to ending LEDs you'd like to be affected, set their low and high brightness, and while the controller is on, the LEDs will gradually turn their brightness up and back down, looping.", None),
                    ("\n\n", None),
                    ("LED Wave", "bold"),
                    ("\n\n", None),
                    ("Set the LED origin point and on any pedal press, a ripple of brightness will wave through the LEDs in line from the pre-set origin point.", None),
                    ("\n\n", None),
                    ("Reactive LEDs", "bold"),
                    ("\n\n", None),
                    ("Rows in the reactive LED grid are Pedal 1 through Pedal 4. Match up in the grid which pedal goes with which LED number. On pedal press, the corresponding LED will get brighter.", None),
                    ("\n\n", None),
                    ("Analog inputs do not participate in reactive LED mappings for the pedal configurator.", None),
                )),
            ])
        self._help_dialog.open()

    # ── Full UI build ────────────────────────────────────────────────

    def _build_ui(self):
        self._pin_vars    = [tk.IntVar(value=-1) for _ in range(self.PEDAL_COUNT)]
        self._pin_combos  = [None] * self.PEDAL_COUNT
        self._map_vars    = [tk.IntVar(value=i) for i in range(self.PEDAL_COUNT)]
        self._map_combos  = [None] * self.PEDAL_COUNT
        self._det_btns    = [None] * self.PEDAL_COUNT
        self._all_widgets = []
        self._usb_host_pin_var = tk.IntVar(value=2)
        self._usb_host_dm_first_var = tk.IntVar(value=0)
        self._usb_host_pin_combo = None
        self._usb_host_order_combo = None

        # Analog (ADC) input state — 2 slots
        self._adc_pin_vars    = [tk.IntVar(value=-1) for _ in range(2)]
        self._adc_pin_combos  = [None, None]
        self._adc_axis_vars   = [tk.IntVar(value=0) for _ in range(2)]
        self._adc_axis_combos = [None, None]
        self._adc_invert_vars = [tk.BooleanVar(value=False) for _ in range(2)]
        self._adc_min_vars    = [tk.IntVar(value=0) for _ in range(2)]
        self._adc_max_vars    = [tk.IntVar(value=4095) for _ in range(2)]
        self._adc_det_btns    = [None, None]
        self._adc_min_str_vars = [tk.StringVar(value="0") for _ in range(2)]
        self._adc_max_str_vars = [tk.StringVar(value="4095") for _ in range(2)]
        self._adc_bars         = [None, None]
        self._adc_cal_bars     = [None, None]
        self._adc_monitor_btns = [None, None]
        self._adc_monitoring   = False
        self._adc_monitor_idx  = None
        self._adc_monitor_thread = None

        # Keep str_vars in sync with int_vars (e.g. after load_config)
        for i in range(2):
            self._adc_min_vars[i].trace_add(
                "write", lambda *_, i=i: self._adc_min_str_vars[i].set(
                    str(self._adc_min_vars[i].get())))
            self._adc_max_vars[i].trace_add(
                "write", lambda *_, i=i: self._adc_max_str_vars[i].set(
                    str(self._adc_max_vars[i].get())))

        self.debounce_var = tk.IntVar(value=5)
        self.device_name  = tk.StringVar(value="Pedal Controller")
        self.led_enabled = tk.BooleanVar(value=False)
        self.led_count = tk.IntVar(value=0)
        self.led_base_brightness = tk.IntVar(value=5)
        self.led_colors = [tk.StringVar(value="FFFFFF") for _ in range(MAX_LEDS)]
        self.led_maps = [tk.IntVar(value=0) for _ in range(len(self.PEDAL_LED_INPUT_INDICES))]
        self.led_active_br = [tk.IntVar(value=7) for _ in range(len(self.PEDAL_LED_INPUT_INDICES))]
        self.led_reactive = tk.BooleanVar(value=True)
        self._led_maps_backup = [0] * len(self.PEDAL_LED_INPUT_INDICES)
        self.led_loop_enabled = tk.BooleanVar(value=False)
        self.led_loop_start = tk.IntVar(value=1)
        self.led_loop_end = tk.IntVar(value=1)
        self.led_breathe_enabled = tk.BooleanVar(value=False)
        self.led_breathe_start = tk.IntVar(value=1)
        self.led_breathe_end = tk.IntVar(value=1)
        self.led_breathe_min = tk.IntVar(value=1)
        self.led_breathe_max = tk.IntVar(value=9)
        self.led_wave_enabled = tk.BooleanVar(value=False)
        self.led_wave_origin = tk.IntVar(value=1)
        self.led_loop_speed = tk.IntVar(value=3000)
        self.led_breathe_speed = tk.IntVar(value=3000)
        self.led_wave_speed = tk.IntVar(value=800)
        self._led_widgets = []
        self._led_sub_cards = []
        self._led_color_btns = []
        self._led_map_cbs = {}
        self._led_map_widgets = []
        self._led_map_pin_lbls = {}

        self.scanning     = False
        self.scan_target  = None

        outer = self.frame
        outer.configure(bg=BG_MAIN)

        # ── Connection card ──────────────────────────────────────────
        conn_card = tk.Frame(outer, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        conn_card.pack(fill="x", pady=(8, 6), padx=12, ipady=6, ipadx=14)

        tk.Label(conn_card, text="CONNECTION", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=14, pady=(6, 0))
        tk.Label(conn_card,
                 text="Click Connect to switch the pedal controller to config mode.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(anchor="w", padx=14, pady=(0, 6))

        btn_bar = tk.Frame(conn_card, bg=BG_CARD)
        btn_bar.pack(fill="x", padx=14)

        self._connect_btn = RoundedButton(
            btn_bar, text="Connect to Controller",
            command=self._connect_clicked,
            bg_color=ACCENT_BLUE, btn_width=190, btn_height=34)
        self._connect_btn.pack(side="left", padx=(0, 8))

        HelpButton(btn_bar, command=self._open_help).pack(side="right", anchor="center", padx=(0, 4))

        self._status_lbl = tk.Label(
            conn_card, textvariable=self._status_var,
            bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        self._status_lbl.pack(anchor="w", padx=14, pady=(8, 6))
        tab_bar = tk.Frame(outer, bg=BG_MAIN)
        tab_bar.pack(fill="x")
        _TAB_NAMES = ["Pedal Controls", "Lighting"]
        self._tab_labels = []
        for _i, _name in enumerate(_TAB_NAMES):
            _lbl = tk.Label(tab_bar, text=_name, bg=BG_MAIN, fg=TEXT_DIM,
                            font=(FONT_UI, 10, "bold"), padx=18, pady=10,
                            cursor="hand2")
            _lbl.pack(side="left")
            _lbl.bind("<Button-1>", lambda e, idx=_i: self._switch_tab(idx))
            self._tab_labels.append(_lbl)
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x")

        # ── Scrollable content area ──────────────────────────────────
        scroll_outer = tk.Frame(outer, bg=BG_MAIN)
        scroll_outer.pack(fill="both", expand=True, padx=12)

        self._scroll_canvas = tk.Canvas(scroll_outer, bg=BG_MAIN,
                                        highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(scroll_outer, orient="vertical",
                                        command=self._on_yview)
        self.content = tk.Frame(self._scroll_canvas, bg=BG_MAIN)
        self._scroll_enabled   = True
        self._scroll_animating = False
        self._scroll_target    = None

        self.content.bind("<Configure>", self._on_content_configure)
        self._content_window = self._scroll_canvas.create_window(
            (0, 0), window=self.content, anchor="nw")
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")
        self._scroll_canvas.bind("<Configure>", self._on_canvas_resize)
        self._tab_frames = [tk.Frame(self.content, bg=BG_MAIN),
                            tk.Frame(self.content, bg=BG_MAIN)]
        self._active_tab = 0
        self._tab_content = self._tab_frames[0]

        # ── Sections ─────────────────────────────────────────────────
        self._make_device_name_section()
        self._make_usb_host_section()
        self._make_pedal_buttons_section()
        self._make_analog_inputs_section()
        self._make_debounce_section()
        self._tab_content = self._tab_frames[1]
        self._make_led_section()
        self._tab_content = self._tab_frames[0]
        self._tab_frames[0].pack(fill="both", expand=True)
        self._update_tab_styling()

        # ── Bottom action bar ─────────────────────────────────────────
        bottom = tk.Frame(outer, bg=BG_MAIN)
        bottom.pack(fill="x", pady=(6, 8), padx=12)

        RoundedButton(
            bottom, text="◀  Main Menu", command=self._go_back,
            bg_color="#555560", btn_width=130, btn_height=32,
            btn_font=(FONT_UI, 8, "bold")).pack(side="left", padx=(0, 8))

        self._defaults_btn = RoundedButton(
            bottom, text="Reset to Defaults", command=self._reset_defaults,
            bg_color="#555560", btn_width=155, btn_height=32,
            btn_font=(FONT_UI, 8, "bold"))
        self._defaults_btn.pack(side="left")
        self._defaults_btn.set_state("disabled")

        self._save_btn = RoundedButton(
            bottom, text="Save & Enter Play Mode",
            command=self._save_and_reboot,
            bg_color=ACCENT_GREEN, btn_width=200, btn_height=34)
        self._save_btn.pack(side="right")
        self._save_btn.set_state("disabled")

        self._set_controls_enabled(False)

    # ── Scroll helpers ───────────────────────────────────────────────

    def _switch_tab(self, idx):
        if idx == self._active_tab:
            return
        self._tab_frames[self._active_tab].pack_forget()
        self._tab_frames[idx].pack(fill="both", expand=True)
        self._active_tab = idx
        self._tab_content = self._tab_frames[idx]
        self._scroll_target = None
        self._scroll_animating = False
        self._update_tab_styling()
        self._update_scroll_state()

    def _update_tab_styling(self):
        for i, lbl in enumerate(self._tab_labels):
            lbl.config(bg=BG_CARD if i == self._active_tab else BG_MAIN,
                       fg=TEXT if i == self._active_tab else TEXT_DIM)

    def _update_scroll_state(self):
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

    def _on_content_configure(self, _event):
        self._update_scroll_state()

    def _on_canvas_resize(self, event):
        self._scroll_canvas.itemconfig(self._content_window, width=event.width)
        self._update_scroll_state()

    def _on_yview(self, *args):
        self._scroll_target = None
        self._scroll_canvas.yview(*args)

    def _on_mousewheel(self, event):
        if not self._scroll_enabled:
            return
        if getattr(event, "delta", 0):
            delta = int(-1 * (event.delta / 120))
        elif getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            return
        content_h = max(1, self.content.winfo_reqheight())
        cur_frac  = self._scroll_canvas.yview()[0]
        new_frac  = cur_frac + delta * 60 / content_h
        new_frac  = max(0.0, min(1.0, new_frac))
        self._scroll_target = new_frac
        if not self._scroll_animating:
            self._scroll_animating = True
            self._do_scroll_step()

    def _do_scroll_step(self):
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

    # ── Card helper ──────────────────────────────────────────────────

    def _make_card(self):
        card = tk.Frame(self._tab_content, bg=BG_CARD,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 6), padx=2)
        return card

    # ── Section: Device Name ─────────────────────────────────────────

    def _make_device_name_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="DEVICE NAME", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Custom USB device name. Appears in Device Manager USB properties.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 6))

        row = tk.Frame(inner, bg=BG_CARD)
        row.pack(fill="x")
        tk.Label(row, text="Name:", bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 6))
        _vcmd = (self.root.register(
            lambda P: len(P) <= 20 and all(c in VALID_NAME_CHARS for c in P)), '%P')
        self._name_entry = tk.Entry(
            row, textvariable=self.device_name,
            bg=BG_INPUT, fg=TEXT, insertbackground=TEXT,
            font=(FONT_UI, 10), width=30, bd=1, relief="solid",
            validate="key", validatecommand=_vcmd)
        self._name_entry.pack(side="left")
        self._all_widgets.append(self._name_entry)
        tk.Label(row, text="(letters, numbers, spaces only  ·  max 20 chars)",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left", padx=(8, 0))

    # ── Section: Pedal Button Mapping ────────────────────────────────

    def _current_usb_host_reserved_pins(self, host_pin=None):
        if host_pin is None:
            host_pin = self._usb_host_pin_var.get()
        if host_pin not in self.USB_HOST_START_PINS:
            return set()
        return {host_pin, host_pin + 1}

    def _validate_usb_host_conflicts(self, host_pin=None, cfg=None):
        if cfg is not None:
            try:
                host_pin = int(cfg.get("usb_host_pin", self._usb_host_pin_var.get()))
            except (TypeError, ValueError):
                return "USB host pair start pin must be a valid GPIO pair."
            try:
                dm_first = int(cfg.get("usb_host_dm_first", self._usb_host_dm_first_var.get()))
            except (TypeError, ValueError):
                return "USB host pin order must be 0 or 1."
            if dm_first not in (0, 1):
                return "USB host pin order must be 0 or 1."
            try:
                pedal_pins = [int(cfg.get(f"pedal{i}", self._pin_vars[i].get()))
                              for i in range(self.PEDAL_COUNT)]
                adc_pins = [int(cfg.get(f"adc{i}", self._adc_pin_vars[i].get()))
                            for i in range(2)]
                leds_enabled = int(cfg.get("led_enabled", 1 if self.led_enabled.get() else 0)) != 0
            except (TypeError, ValueError):
                return "One or more assigned GPIO pins are invalid."
        else:
            if host_pin is None:
                host_pin = self._usb_host_pin_var.get()
            pedal_pins = [v.get() for v in self._pin_vars]
            adc_pins = [v.get() for v in self._adc_pin_vars]
            leds_enabled = self.led_enabled.get()

        if host_pin not in self.USB_HOST_START_PINS:
            return "USB host pair must use a valid consecutive GPIO pair."

        reserved = self._current_usb_host_reserved_pins(host_pin)
        if leds_enabled and (reserved & self.LED_SPI_PINS):
            pins_txt = ", ".join(f"GPIO {pin}" for pin in sorted(reserved & self.LED_SPI_PINS))
            return f"LEDs use GP6 and GP7. Choose a different USB host pair because it overlaps {pins_txt}."
        for idx, pin in enumerate(pedal_pins):
            if pin in reserved:
                return f"Pedal {idx + 1} uses GPIO {pin}, which is reserved for the USB host port."
            if leds_enabled and pin in self.LED_SPI_PINS:
                return f"Pedal {idx + 1} uses GPIO {pin}, which is reserved for LEDs when lighting is enabled."
        for idx, pin in enumerate(adc_pins):
            if pin in reserved:
                return f"Analog {idx + 1} uses GPIO {pin}, which is reserved for the USB host port."
        return None

    def _show_usb_host_conflict(self, message):
        messagebox.showwarning("USB Host Pin Conflict", message)

    def _make_usb_host_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="USB HOST PORT", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Select the consecutive GPIO pair used by the pedal USB host port, "
                      "then choose whether D+ or D- is wired to the first pin in that pair.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        row = tk.Frame(inner, bg=BG_CARD)
        row.pack(fill="x")

        tk.Label(row, text="Pair:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        pin_combo = CustomDropdown(row, state="readonly", width=18,
                                   values=self.USB_HOST_START_LABELS)
        pin_combo.current(self.USB_HOST_START_PINS.index(2))
        pin_combo.pack(side="left", padx=(0, 12))
        pin_combo.bind("<<ComboboxSelected>>", self._on_usb_host_pin_combo)
        self._usb_host_pin_combo = pin_combo
        self._all_widgets.append(pin_combo)

        tk.Label(row, text="Order:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        order_combo = CustomDropdown(row, state="readonly", width=30,
                                     values=self.USB_HOST_ORDER_LABELS)
        order_combo.current(0)
        order_combo.pack(side="left")
        order_combo.bind("<<ComboboxSelected>>", self._on_usb_host_order_combo)
        self._usb_host_order_combo = order_combo
        self._all_widgets.append(order_combo)

    def _on_usb_host_pin_combo(self, _event=None):
        combo = self._usb_host_pin_combo
        if combo is None or combo.current() < 0:
            return
        new_pin = self.USB_HOST_START_PINS[combo.current()]
        error = self._validate_usb_host_conflicts(host_pin=new_pin)
        if error:
            current_pin = self._usb_host_pin_var.get()
            if current_pin in self.USB_HOST_START_PINS:
                combo.current(self.USB_HOST_START_PINS.index(current_pin))
            self._show_usb_host_conflict(error)
            return
        self._usb_host_pin_var.set(new_pin)

    def _on_usb_host_order_combo(self, _event=None):
        combo = self._usb_host_order_combo
        if combo is None or combo.current() < 0:
            return
        self._usb_host_dm_first_var.set(combo.current())

    def _make_pedal_buttons_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="PEDAL BUTTONS", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Assign a GPIO pin and XInput button to each pedal. "
                      "All inputs use internal pull-ups — wire each pedal switch to connect GPIO to GND. "
                      "Press Detect and step on the pedal to auto-assign the pin.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        # Column headers
        hdr = tk.Frame(inner, bg=BG_CARD)
        hdr.pack(fill="x", pady=(0, 2))
        tk.Frame(hdr, width=86, bg=BG_CARD).pack(side="left")
        tk.Label(hdr, text="GPIO Pin", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), width=21, anchor="w").pack(side="left")
        tk.Label(hdr, text="Maps to Button", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), anchor="w").pack(side="left")

        DEFAULT_PINS = [4, 5, 6, 7]
        DEFAULT_MAPS = [0, 1, 2, 3]  # Green, Red, Yellow, Blue

        for i in range(self.PEDAL_COUNT):
            self._pin_vars[i].set(DEFAULT_PINS[i])
            self._map_vars[i].set(DEFAULT_MAPS[i])
            self._make_pedal_row(inner, i, DEFAULT_PINS[i], DEFAULT_MAPS[i])

    def _make_pedal_row(self, parent, idx, default_pin, default_map):
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=f"Pedal {idx + 1}", bg=BG_CARD, fg=TEXT,
                 width=10, anchor="w",
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 8))

        tk.Label(row, text="Pin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        pin_combo = CustomDropdown(
            row, state="readonly", width=18,
            values=[DIGITAL_PIN_LABELS[p] for p in DIGITAL_PINS])
        default_idx = DIGITAL_PINS.index(default_pin) if default_pin in DIGITAL_PINS else 0
        pin_combo.current(default_idx)
        pin_combo.pack(side="left", padx=(0, 6))
        pin_combo.bind("<<ComboboxSelected>>",
                       lambda _e, i=idx, c=pin_combo: self._on_pin_combo(i, c))
        self._pin_combos[idx] = pin_combo
        self._all_widgets.append(pin_combo)

        det_btn = ttk.Button(
            row, text="Detect", style="Det.TButton", width=7,
            command=lambda i=idx: self._start_detect(i))
        det_btn.pack(side="left", padx=(0, 16))
        self._det_btns[idx] = det_btn
        self._all_widgets.append(det_btn)

        tk.Label(row, text="Button:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        map_combo = CustomDropdown(
            row, state="readonly", width=16,
            values=self.BUTTON_INDEX_LABELS)
        map_combo.current(default_map)
        map_combo.pack(side="left")
        map_combo.bind("<<ComboboxSelected>>",
                       lambda _e, i=idx, c=map_combo: self._on_map_combo(i, c))
        self._map_combos[idx] = map_combo
        self._all_widgets.append(map_combo)

    def _on_pin_combo(self, idx, combo):
        pin = DIGITAL_PINS[combo.current()]
        if pin in self._current_usb_host_reserved_pins():
            current_pin = self._pin_vars[idx].get()
            if current_pin in DIGITAL_PINS:
                combo.current(DIGITAL_PINS.index(current_pin))
            self._show_usb_host_conflict(
                f"GPIO {pin} is reserved for the USB host port. "
                f"Choose a different pin for Pedal {idx + 1}."
            )
            return
        if self.led_enabled.get() and pin in self.LED_SPI_PINS:
            current_pin = self._pin_vars[idx].get()
            if current_pin in DIGITAL_PINS:
                combo.current(DIGITAL_PINS.index(current_pin))
            self._show_usb_host_conflict(
                f"GPIO {pin} is reserved for the LED strip when lighting is enabled. "
                f"Choose a different pin for Pedal {idx + 1}."
            )
            return
        self._pin_vars[idx].set(pin)

    def _on_map_combo(self, idx, combo):
        self._map_vars[idx].set(combo.current())

    # ── Pin detection (SCAN) ─────────────────────────────────────────

    def _start_detect(self, idx):
        if not self.pico.connected:
            return
        if self._adc_monitoring:
            self._stop_adc_monitoring()
        if self.scanning:
            self._stop_detect()
            return
        self.scanning = True
        self.scan_target = ('digital', idx)

        # Disable all detect buttons (digital + ADC) except the active one
        for i, btn in enumerate(self._det_btns):
            try:
                btn.config(state="disabled" if i != idx else "normal",
                           text="Stop" if i == idx else "Detect")
            except Exception:
                pass
        for btn in self._adc_det_btns:
            try:
                btn.config(state="disabled")
            except Exception:
                pass

        self._set_status(
            f"   Detecting pin for Pedal {idx + 1} — step on the pedal now...",
            ACCENT_BLUE)

        def _scan_worker():
            try:
                self.pico.ser.write(b"SCAN\n")
                self.pico.ser.flush()
                deadline = time.time() + 15.0
                while time.time() < deadline and self.scanning:
                    raw = self.pico.ser.readline()
                    line = raw.decode("ascii", errors="replace").strip() if raw else ""
                    if line.startswith("PIN:"):
                        pin = int(line[4:])
                        self.root.after(0, lambda p=pin: self._detect_result(idx, p))
                        return
            except Exception:
                pass
            self.root.after(0, self._stop_detect)

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _detect_result(self, idx, pin):
        self._stop_detect()
        if pin in DIGITAL_PINS:
            self._pin_vars[idx].set(pin)
            combo = self._pin_combos[idx]
            if combo:
                combo.current(DIGITAL_PINS.index(pin))
            self._set_status(f"   Detected GPIO {pin} for Pedal {idx + 1}", ACCENT_GREEN)

    def _start_adc_detect(self, idx):
        if not self.pico.connected:
            return
        if self._adc_monitoring:
            self._stop_adc_monitoring()
        if self.scanning:
            self._stop_detect()
            return
        self.scanning = True
        self.scan_target = ('adc', idx)

        # Disable all detect buttons (digital + ADC) except the active one
        for btn in self._det_btns:
            try:
                btn.config(state="disabled")
            except Exception:
                pass
        for i, btn in enumerate(self._adc_det_btns):
            try:
                btn.config(state="disabled" if i != idx else "normal",
                           text="Stop" if i == idx else "Detect")
            except Exception:
                pass

        self._set_status(
            f"   Detecting pin for Analog {idx + 1} — press the analog pedal fully...",
            ACCENT_BLUE)

        def _scan_worker():
            try:
                self.pico.ser.write(b"SCAN\n")
                self.pico.ser.flush()
                deadline = time.time() + 15.0
                while time.time() < deadline and self.scanning:
                    raw = self.pico.ser.readline()
                    line = raw.decode("ascii", errors="replace").strip() if raw else ""
                    if line.startswith("PIN:"):
                        pin = int(line[4:])
                        self.root.after(0, lambda p=pin: self._adc_detect_result(idx, p))
                        return
            except Exception:
                pass
            self.root.after(0, self._stop_detect)

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _adc_detect_result(self, idx, pin):
        self._stop_detect()
        if pin in self.ADC_PINS and pin != -1:
            self._adc_pin_vars[idx].set(pin)
            combo = self._adc_pin_combos[idx]
            if combo:
                combo.current(self.ADC_PINS.index(pin))
            self._set_status(f"   Detected GPIO {pin} for Analog {idx + 1}", ACCENT_GREEN)
        else:
            self._set_status(
                f"   GPIO {pin} is not an ADC-capable pin — need GP26, 27, or 28",
                ACCENT_ORANGE)

    def _stop_detect(self):
        was_active = self.scanning or self._adc_monitoring
        self.scanning = False
        self.scan_target = None
        # Also stop any active ADC monitor (they share the serial line)
        if self._adc_monitoring:
            self._adc_monitoring = False
            idx = self._adc_monitor_idx
            self._adc_monitor_idx = None
            if idx is not None and self._adc_monitor_btns[idx] is not None:
                btn = self._adc_monitor_btns[idx]
                btn._label = "Monitor"
                btn._bg = "#555560"
                btn._render("#555560")
        # Only send STOP if a scan or monitor was actually running — sending STOP
        # to an idle firmware produces ERR:unknown command which pollutes the
        # read buffer and causes the next command to misread its response.
        if was_active:
            try:
                self.pico.ser.write(b"STOP\n")
                self.pico.ser.flush()
            except Exception:
                pass
        for btn in self._det_btns:
            try:
                btn.config(state="normal", text="Detect")
            except Exception:
                pass
        for btn in self._adc_det_btns:
            try:
                btn.config(state="normal", text="Detect")
            except Exception:
                pass

    # ── Section: Analog Inputs ───────────────────────────────────────

    def _make_analog_inputs_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="ANALOG INPUTS", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Connect an expression pedal or potentiometer to GP26, GP27, or GP28 "
                      "(ADC-capable pins). Wire wiper → GPIO, one end → GND, other end → 3.3V. "
                      "Each slot maps to Whammy or Tilt and max-merges with the guitar passthrough — "
                      "whichever source is pressed further wins.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        for i in range(2):
            self._make_analog_row(inner, i)

    def _make_analog_row(self, parent, idx):
        outer_row = tk.Frame(parent, bg=BG_CARD)
        outer_row.pack(fill="x", pady=(0, 10))

        # ── Row 1: label, pin, detect ──────────────────────────────
        row1 = tk.Frame(outer_row, bg=BG_CARD)
        row1.pack(fill="x", pady=(0, 3))

        tk.Label(row1, text=f"Analog {idx + 1}", bg=BG_CARD, fg=TEXT,
                 width=10, anchor="w",
                 font=(FONT_UI, 9, "bold")).pack(side="left", padx=(0, 8))

        tk.Label(row1, text="Pin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        pin_combo = CustomDropdown(
            row1, state="readonly", width=20,
            values=self.ADC_PIN_LABELS)
        pin_combo.current(0)   # "Disabled"
        pin_combo.pack(side="left", padx=(0, 6))
        pin_combo.bind("<<ComboboxSelected>>",
                       lambda _e, i=idx, c=pin_combo: self._on_adc_pin_combo(i, c))
        self._adc_pin_combos[idx] = pin_combo
        self._all_widgets.append(pin_combo)

        det_btn = ttk.Button(
            row1, text="Detect", style="Det.TButton", width=7,
            command=lambda i=idx: self._start_adc_detect(i))
        det_btn.pack(side="left", padx=(0, 16))
        self._adc_det_btns[idx] = det_btn
        self._all_widgets.append(det_btn)

        # ── Row 2: axis, invert ────────────────────────────────────
        row2 = tk.Frame(outer_row, bg=BG_CARD)
        row2.pack(fill="x", pady=(0, 3))

        tk.Frame(row2, width=86, bg=BG_CARD).pack(side="left")  # indent

        tk.Label(row2, text="Axis:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        axis_combo = CustomDropdown(
            row2, state="readonly", width=10,
            values=self.ADC_AXIS_LABELS)
        axis_combo.current(0)  # Whammy
        axis_combo.pack(side="left", padx=(0, 12))
        axis_combo.bind("<<ComboboxSelected>>",
                        lambda _e, i=idx, c=axis_combo: self._on_adc_axis_combo(i, c))
        self._adc_axis_combos[idx] = axis_combo
        self._all_widgets.append(axis_combo)

        invert_cb = ttk.Checkbutton(
            row2, text="Invert",
            variable=self._adc_invert_vars[idx])
        invert_cb.pack(side="left")
        self._all_widgets.append(invert_cb)

        # ── Row 3: live raw bar + Monitor button ───────────────────
        row3 = tk.Frame(outer_row, bg=BG_CARD)
        row3.pack(fill="x", pady=(2, 0))

        tk.Frame(row3, width=24, bg=BG_CARD).pack(side="left")

        bar = LiveBarGraph(row3, label="Original Value", width=380, height=24,
                           min_marker_var=self._adc_min_vars[idx],
                           max_marker_var=self._adc_max_vars[idx])
        bar.pack(side="left", padx=(0, 8))
        self._adc_bars[idx] = bar

        monitor_btn = RoundedButton(
            row3, text="Monitor",
            command=lambda i=idx: self._toggle_adc_monitor(i),
            bg_color="#555560", btn_width=80, btn_height=24,
            btn_font=(FONT_UI, 7, "bold"))
        monitor_btn.pack(side="left")
        self._adc_monitor_btns[idx] = monitor_btn
        self._all_widgets.append(monitor_btn)

        # ── Row 4: calibrated output bar ──────────────────────────
        row4 = tk.Frame(outer_row, bg=BG_CARD)
        row4.pack(fill="x", pady=(2, 2))

        tk.Frame(row4, width=24, bg=BG_CARD).pack(side="left")

        cal_bar = CalibratedBarGraph(row4, label="Calibrated Value", width=380, height=24,
                                     min_var=self._adc_min_vars[idx],
                                     max_var=self._adc_max_vars[idx],
                                     invert_var=self._adc_invert_vars[idx],
                                     ema_alpha_var=None)
        cal_bar.pack(side="left", padx=(0, 8))
        self._adc_cal_bars[idx] = cal_bar

        # Redraw bars when min/max/invert change
        def _on_cal_change(*_, i=idx):
            self._adc_bars[i].redraw_markers()
            self._adc_cal_bars[i].redraw()
        self._adc_min_vars[idx].trace_add("write", _on_cal_change)
        self._adc_max_vars[idx].trace_add("write", _on_cal_change)
        self._adc_invert_vars[idx].trace_add("write", _on_cal_change)

        # ── Row 5: min/max entries + Set Min / Set Max / Reset ─────
        row5 = tk.Frame(outer_row, bg=BG_CARD)
        row5.pack(fill="x", pady=(0, 2))

        tk.Frame(row5, width=24, bg=BG_CARD).pack(side="left")

        tk.Label(row5, text="Min:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        min_entry = tk.Entry(row5, textvariable=self._adc_min_str_vars[idx], width=5,
                             font=(FONT_UI, 8), fg="#000000", bg="#ffffff",
                             insertbackground="#000000", relief="flat")
        min_entry.pack(side="left", padx=(0, 6))
        min_entry.bind("<FocusOut>",
                       lambda _e, i=idx: self._on_adc_min_entry(i))
        min_entry.bind("<Return>",
                       lambda _e, i=idx: self._on_adc_min_entry(i))
        self._all_widgets.append(min_entry)

        tk.Label(row5, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        max_entry = tk.Entry(row5, textvariable=self._adc_max_str_vars[idx], width=5,
                             font=(FONT_UI, 8), fg="#000000", bg="#ffffff",
                             insertbackground="#000000", relief="flat")
        max_entry.pack(side="left", padx=(0, 10))
        max_entry.bind("<FocusOut>",
                       lambda _e, i=idx: self._on_adc_max_entry(i))
        max_entry.bind("<Return>",
                       lambda _e, i=idx: self._on_adc_max_entry(i))
        self._all_widgets.append(max_entry)

        set_min_btn = RoundedButton(
            row5, text="Set Min", btn_width=58, btn_height=20,
            bg_color="#555560", btn_font=(FONT_UI, 7, "bold"),
            command=lambda i=idx: self._set_adc_min_from_live(i))
        set_min_btn.pack(side="left", padx=(0, 3))
        self._all_widgets.append(set_min_btn)

        set_max_btn = RoundedButton(
            row5, text="Set Max", btn_width=58, btn_height=20,
            bg_color="#555560", btn_font=(FONT_UI, 7, "bold"),
            command=lambda i=idx: self._set_adc_max_from_live(i))
        set_max_btn.pack(side="left", padx=(0, 3))
        self._all_widgets.append(set_max_btn)

        reset_btn = RoundedButton(
            row5, text="Reset", btn_width=48, btn_height=20,
            bg_color="#555560", btn_font=(FONT_UI, 7, "bold"),
            command=lambda i=idx: self._reset_adc_calibration(i))
        reset_btn.pack(side="left")
        self._all_widgets.append(reset_btn)

    def _on_adc_pin_combo(self, idx, combo):
        pin = self.ADC_PINS[combo.current()]
        if pin in self._current_usb_host_reserved_pins():
            current_pin = self._adc_pin_vars[idx].get()
            if current_pin in self.ADC_PINS:
                combo.current(self.ADC_PINS.index(current_pin))
            self._show_usb_host_conflict(
                f"GPIO {pin} is reserved for the USB host port. "
                f"Choose a different pin for Analog {idx + 1}."
            )
            return
        self._adc_pin_vars[idx].set(pin)

    def _on_adc_axis_combo(self, idx, combo):
        self._adc_axis_vars[idx].set(combo.current())

    def _on_adc_min_entry(self, idx):
        try:
            v = int(self._adc_min_str_vars[idx].get().strip())
        except ValueError:
            self._adc_min_str_vars[idx].set(str(self._adc_min_vars[idx].get()))
            return
        v = max(0, min(4095, v))
        if v >= self._adc_max_vars[idx].get():
            v = self._adc_max_vars[idx].get() - 1
        v = max(0, v)
        self._adc_min_vars[idx].set(v)
        self._adc_min_str_vars[idx].set(str(v))

    def _on_adc_max_entry(self, idx):
        try:
            v = int(self._adc_max_str_vars[idx].get().strip())
        except ValueError:
            self._adc_max_str_vars[idx].set(str(self._adc_max_vars[idx].get()))
            return
        v = max(0, min(4095, v))
        if v <= self._adc_min_vars[idx].get():
            v = self._adc_min_vars[idx].get() + 1
        v = min(4095, v)
        self._adc_max_vars[idx].set(v)
        self._adc_max_str_vars[idx].set(str(v))

    # ── Analog monitor ────────────────────────────────────────────────

    def _toggle_adc_monitor(self, idx):
        if self._adc_monitoring:
            if self._adc_monitor_idx == idx:
                self._stop_adc_monitoring()
            return

        if not self.pico.connected:
            return

        if self.scanning:
            self._stop_detect()
            return

        pin = self._adc_pin_vars[idx].get()
        if pin not in (26, 27, 28):
            messagebox.showinfo("Monitor",
                                "Select an ADC-capable pin (GP26, 27, or 28) first.")
            return

        self._adc_monitoring = True
        self._adc_monitor_idx = idx

        btn = self._adc_monitor_btns[idx]
        btn._label = "Stop"
        btn._bg = ACCENT_RED
        btn._render(ACCENT_RED)

        bar = self._adc_bars[idx]
        cal_bar = self._adc_cal_bars[idx]

        def _monitor_thread():
            try:
                self.pico.start_monitor_adc(pin)
                while self._adc_monitoring:
                    val, others = self.pico.drain_monitor_latest(0.05)
                    for raw in others:
                        self.root.after(0, lambda r=raw: self._debug_log(r))
                    if val is not None:
                        self.root.after(0, lambda v=val: bar.set_value(v))
                        self.root.after(0, lambda v=val: cal_bar.set_raw(v))
            except Exception as exc:
                self.root.after(0, lambda: self._on_adc_monitor_error(str(exc)))

        self._adc_monitor_thread = threading.Thread(
            target=_monitor_thread, daemon=True)
        self._adc_monitor_thread.start()

    def _stop_adc_monitoring(self):
        if not self._adc_monitoring:
            return
        self._adc_monitoring = False
        try:
            self.pico.stop_monitor()
        except Exception:
            pass
        idx = self._adc_monitor_idx
        self._adc_monitor_idx = None
        if idx is not None and self._adc_monitor_btns[idx] is not None:
            btn = self._adc_monitor_btns[idx]
            btn._label = "Monitor"
            btn._bg = "#555560"
            btn._render("#555560")

    def _on_adc_monitor_error(self, msg):
        idx = self._adc_monitor_idx
        self._adc_monitoring = False
        self._adc_monitor_idx = None
        if idx is not None and self._adc_monitor_btns[idx] is not None:
            btn = self._adc_monitor_btns[idx]
            btn._label = "Monitor"
            btn._bg = "#555560"
            btn._render("#555560")
        messagebox.showerror("Monitor Error", msg)

    def _set_adc_min_from_live(self, idx):
        bar = self._adc_bars[idx]
        if bar is None:
            return
        live_val = bar._value
        clamped = max(0, min(live_val, self._adc_max_vars[idx].get() - 1))
        self._adc_min_vars[idx].set(clamped)
        self._adc_min_str_vars[idx].set(str(clamped))

    def _set_adc_max_from_live(self, idx):
        bar = self._adc_bars[idx]
        if bar is None:
            return
        live_val = bar._value
        clamped = min(4095, max(live_val, self._adc_min_vars[idx].get() + 1))
        self._adc_max_vars[idx].set(clamped)
        self._adc_max_str_vars[idx].set(str(clamped))

    def _reset_adc_calibration(self, idx):
        self._adc_min_vars[idx].set(0)
        self._adc_max_vars[idx].set(4095)
        self._adc_min_str_vars[idx].set("0")
        self._adc_max_str_vars[idx].set("4095")

    # ── Section: Debounce ─────────────────────────────────────────────

    def _make_debounce_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="DEBOUNCE", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 4))
        row = tk.Frame(inner, bg=BG_CARD)
        row.pack(fill="x")
        tk.Label(row, text="Debounce time:", bg=BG_CARD, fg=TEXT).pack(
            side="left", padx=(0, 5))
        sp = ttk.Spinbox(row, from_=0, to=50, width=5,
                         textvariable=self.debounce_var)
        sp.pack(side="left", padx=(0, 5))
        self._all_widgets.append(sp)
        tk.Label(row, text="ms  (0 = none, 3-5 typical)", bg=BG_CARD,
                 fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left")

    # ── Enable/disable all controls ───────────────────────────────────

    def _make_sub_collapsible(self, parent, title, collapsed=True):
        card = tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(2, 2))
        header = tk.Frame(card, bg=BG_CARD, cursor="hand2")
        header.pack(fill="x", padx=10, pady=(6, 0))
        arrow_var = tk.StringVar(value="\u25b6" if collapsed else "\u25bc")
        arrow_lbl = tk.Label(header, textvariable=arrow_var, bg=BG_CARD, fg=ACCENT_BLUE,
                             font=(FONT_UI, 8, "bold"))
        arrow_lbl.pack(side="left", padx=(0, 5))
        title_lbl = tk.Label(header, text=title, bg=BG_CARD, fg=ACCENT_BLUE,
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

    def _make_led_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)
        tk.Label(inner, text="LED STRIP  (APA102 / SK9822 / Dotstar)",
                 bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(inner,
                 text="Wire SCK (CI) -> GP6, MOSI (DI) -> GP7. Chain LEDs in series. "
                      "VCC -> VBUS (5V), GND -> GND. "
                      "WARNING: GP6 and GP7 are reserved for LEDs when enabled. "
                      "Reactive LED mappings are available for Pedal 1-4 only; analog inputs do not trigger LED reactions.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 6))

        top = tk.Frame(inner, bg=BG_CARD)
        top.pack(fill="x", pady=2)
        en_cb = ttk.Checkbutton(top, text="Enable LEDs", variable=self.led_enabled,
                                command=self._on_led_toggle)
        en_cb.pack(side="left", padx=(0, 14))
        self._all_widgets.append(en_cb)
        tk.Label(top, text="Count:", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        cnt_wrap = tk.Frame(top, bg=BG_CARD, width=52, height=22)
        cnt_wrap.pack(side="left", padx=(0, 12))
        cnt_wrap.pack_propagate(False)
        _cvcmd = (self.root.register(lambda P: P == "" or P.isdigit()), '%P')
        cnt_sp = ttk.Spinbox(cnt_wrap, from_=1, to=MAX_LEDS, width=4, textvariable=self.led_count,
                             command=self._on_led_count_change,
                             validate="key", validatecommand=_cvcmd)
        cnt_sp.pack(fill="both", expand=True)
        cnt_sp.bind("<KeyRelease>", lambda _e, widget=cnt_sp: self._on_led_count_live_change(widget))
        cnt_sp.bind("<Return>", lambda _e: self._on_led_count_change())
        cnt_sp.bind("<FocusOut>", lambda _e: self._on_led_count_change())
        self._all_widgets.append(cnt_sp)
        self._led_widgets.append(cnt_sp)
        tk.Label(top, text=f"(max {MAX_LEDS})", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left", padx=(0, 10))
        tk.Label(top, text="Base brightness:", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        _bvcmd = (self.root.register(lambda P: P == "" or (P.isdigit() and 0 <= int(P) <= 9)), '%P')
        br_wrap = tk.Frame(top, bg=BG_CARD, width=52, height=22)
        br_wrap.pack(side="left")
        br_wrap.pack_propagate(False)
        br_sp = ttk.Spinbox(br_wrap, from_=0, to=9, width=4, textvariable=self.led_base_brightness,
                            validate="key", validatecommand=_bvcmd)
        br_sp.pack(fill="both", expand=True)
        self._all_widgets.append(br_sp)
        self._led_widgets.append(br_sp)
        tk.Label(top, text="(0=off, 9=max)", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left", padx=(4, 0))

        self._led_colors_frame = tk.Frame(inner, bg=BG_CARD)
        self._led_colors_frame.pack(fill="x", pady=(6, 0))
        self._led_widgets.append(self._led_colors_frame)
        self._rebuild_led_color_grid()

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
        loop_start_sp = ttk.Spinbox(loop_range_row, from_=1, to=MAX_LEDS, width=4,
                                    textvariable=self.led_loop_start)
        loop_start_sp.pack(side="left", padx=(0, 8))
        self._all_widgets.append(loop_start_sp)
        tk.Label(loop_range_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        loop_end_sp = ttk.Spinbox(loop_range_row, from_=1, to=MAX_LEDS, width=4,
                                  textvariable=self.led_loop_end)
        loop_end_sp.pack(side="left")
        self._all_widgets.append(loop_end_sp)
        tk.Label(lc_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        loop_speed_sl = SpeedSlider(lc_right, self.led_loop_speed,
                                    notch_ms=[9999, 5000, 3000, 1000, 100])
        loop_speed_sl.pack()
        self._all_widgets.append(loop_speed_sl)

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
        breathe_start_sp = ttk.Spinbox(breathe_range_row, from_=1, to=MAX_LEDS, width=4,
                                       textvariable=self.led_breathe_start)
        breathe_start_sp.pack(side="left", padx=(0, 8))
        self._all_widgets.append(breathe_start_sp)
        tk.Label(breathe_range_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_end_sp = ttk.Spinbox(breathe_range_row, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_breathe_end)
        breathe_end_sp.pack(side="left")
        self._all_widgets.append(breathe_end_sp)
        tk.Label(br_left, text="Effect Brightness", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="w").pack(anchor="w", pady=(4, 1))
        breathe_bright_row = tk.Frame(br_left, bg=BG_CARD)
        breathe_bright_row.pack(anchor="w", pady=(0, 4))
        tk.Label(breathe_bright_row, text="Min:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_min_sp = ttk.Spinbox(breathe_bright_row, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_min,
                                     validate="key", validatecommand=_bvcmd)
        breathe_min_sp.pack(side="left", padx=(0, 8))
        self._all_widgets.append(breathe_min_sp)
        tk.Label(breathe_bright_row, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_max_sp = ttk.Spinbox(breathe_bright_row, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_max,
                                     validate="key", validatecommand=_bvcmd)
        breathe_max_sp.pack(side="left")
        self._all_widgets.append(breathe_max_sp)
        tk.Label(br_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        breathe_speed_sl = SpeedSlider(br_right, self.led_breathe_speed,
                                       notch_ms=[9999, 5000, 3000, 1000, 100])
        breathe_speed_sl.pack()
        self._all_widgets.append(breathe_speed_sl)

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
        wave_origin_sp = ttk.Spinbox(wave_origin_row, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_wave_origin)
        wave_origin_sp.pack(side="left")
        self._all_widgets.append(wave_origin_sp)
        tk.Label(wv_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        wave_speed_sl = SpeedSlider(wv_right, self.led_wave_speed,
                                    notch_ms=[9999, 2500, 800, 250, 100])
        wave_speed_sl.pack()
        self._all_widgets.append(wave_speed_sl)

        react_card, react_body = self._make_sub_collapsible(inner, "REACTIVE LED ON KEYPRESS", collapsed=False)
        self._led_sub_cards.append(react_card)
        react_cb = ttk.Checkbutton(react_body, text="Reactive LEDs on keypress",
                                   variable=self.led_reactive, command=self._on_reactive_toggle)
        react_cb.pack(anchor="w", pady=(0, 4))
        self._all_widgets.append(react_cb)
        react_info = tk.Label(
            react_body,
            text="Input -> LED Mapping  (Pedal 1-4 only. Analog inputs do not trigger LED reactions.)",
            bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8, "bold"), anchor="w")
        react_info.pack(fill="x", pady=(0, 4))
        self._led_map_widgets.append(react_info)
        self._led_map_frame = tk.Frame(react_body, bg=BG_CARD)
        self._led_map_frame.pack(fill="x")
        self._led_map_widgets.append(self._led_map_frame)
        self._rebuild_led_map_grid()
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
            error = self._validate_usb_host_conflicts()
            if error:
                self._set_status(f"   {error}", ACCENT_ORANGE)

    def _on_reactive_toggle(self):
        reactive = self.led_reactive.get()
        if not reactive:
            for i in range(len(self.PEDAL_LED_INPUT_INDICES)):
                cur = self.led_maps[i].get()
                if cur != 0:
                    self._led_maps_backup[i] = cur
                self.led_maps[i].set(0)
        else:
            for i in range(len(self.PEDAL_LED_INPUT_INDICES)):
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
        tk.Label(self._led_colors_frame,
                 text="LED Colors  (click swatch to change, Identify flashes the physical LED):",
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
            color_hex = self.led_colors[i].get().strip().upper()
            try:
                display_color = f"#{color_hex}"
                int(color_hex, 16)
            except Exception:
                display_color = "#FFFFFF"
            swatch = tk.Canvas(cell, width=22, height=22, bg=BG_CARD,
                               highlightthickness=1, highlightbackground=BORDER, bd=0)
            swatch.create_rectangle(2, 2, 20, 20, fill=display_color, outline=display_color, tags="fill")
            swatch.pack(side="left", padx=(2, 4))
            swatch.bind("<Button-1>", lambda _e, idx=i: self._pick_led_color(idx))
            self._led_color_btns.append(swatch)
            id_btn = ttk.Button(cell, text="Identify", style="Det.TButton", width=7,
                                command=lambda idx=i: self._identify_led(idx))
            id_btn.pack(side="left")
            self._all_widgets.append(id_btn)

    def _rebuild_led_map_grid(self):
        for w in self._led_map_frame.winfo_children():
            w.destroy()
        self._led_map_cbs = {}
        self._led_map_pin_lbls = {}
        count = self.led_count.get()
        if count < 1:
            return
        grid = tk.Frame(self._led_map_frame, bg=BG_CARD)
        grid.pack(fill="x")
        led_col_start = 2
        bright_col = led_col_start + min(count, MAX_LEDS)
        tk.Label(grid, text="Input", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 2))
        tk.Label(grid, text="Pin", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), anchor="w").grid(row=0, column=1, sticky="w", padx=(0, 4))
        for j in range(min(count, MAX_LEDS)):
            color_hex = self.led_colors[j].get().strip().upper()
            if len(color_hex) != 6:
                color_hex = "FFFFFF"
            try:
                bg_color = f"#{color_hex}"
                int(color_hex, 16)
            except Exception:
                bg_color = "#FFFFFF"
                color_hex = "FFFFFF"
            fg_color = self._text_color_for_bg(color_hex)
            tk.Label(grid, text=f" {j + 1} ", bg=bg_color, fg=fg_color,
                     font=(FONT_UI, 7, "bold"), relief="flat", bd=0, padx=1, pady=0).grid(
                         row=0, column=led_col_start + j, padx=1, pady=(0, 3))
        tk.Label(grid, text="Bright", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold")).grid(row=0, column=bright_col, padx=(6, 0))
        _bvcmd = (self.root.register(lambda P: P == "" or (P.isdigit() and 0 <= int(P) <= 9)), '%P')
        for inp_idx, label in enumerate(PEDAL_LED_INPUT_LABELS):
            grid_row = inp_idx + 1
            tk.Label(grid, text=label, bg=BG_CARD, fg=TEXT,
                     font=(FONT_UI, 7), anchor="w").grid(row=grid_row, column=0, sticky="w", padx=(0, 2), pady=1)
            pin_lbl = tk.Label(grid, text=str(self._pin_vars[inp_idx].get()), bg=BG_INPUT, fg=TEXT_DIM,
                               font=("Consolas", 7), width=4, anchor="center", relief="flat", bd=0)
            pin_lbl.grid(row=grid_row, column=1, padx=(0, 4), pady=1)
            self._led_map_pin_lbls[inp_idx] = pin_lbl
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
        cur_hex = self.led_colors[led_idx].get().strip().upper()
        try:
            cr = int(cur_hex[0:2], 16)
            cg = int(cur_hex[2:4], 16)
            cb = int(cur_hex[4:6], 16)
        except Exception:
            cr, cg, cb = 255, 255, 255
        r_var = tk.IntVar(value=cr)
        g_var = tk.IntVar(value=cg)
        b_var = tk.IntVar(value=cb)
        preview = tk.Canvas(f, width=80, height=50, bg=BG_CARD,
                            highlightthickness=1, highlightbackground=BORDER, bd=0)
        preview.create_rectangle(2, 2, 78, 48, fill=f"#{cur_hex}", outline=f"#{cur_hex}", tags="fill")
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
        preset_colors = [
            ("Green", "00FF00"), ("Red", "FF0000"), ("Yellow", "FFFF00"),
            ("Blue", "0000FF"), ("Orange", "FF4600"), ("Purple", "FF00FF"),
            ("Cyan", "00FFFF"), ("White", "FFFFFF"),
        ]
        tk.Label(f, text="Presets:", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(anchor="w", pady=(0, 4))
        swatch_row = tk.Frame(f, bg=BG_CARD)
        swatch_row.pack(anchor="w", pady=(0, 8))
        def _apply_preset(hex_rgb):
            r_var.set(int(hex_rgb[0:2], 16))
            g_var.set(int(hex_rgb[2:4], 16))
            b_var.set(int(hex_rgb[4:6], 16))
            update_preview()
        for name, hex_rgb in preset_colors:
            display = f"#{hex_rgb}"
            rc2, gc2, bc2 = int(hex_rgb[0:2], 16), int(hex_rgb[2:4], 16), int(hex_rgb[4:6], 16)
            lum = 0.2126 * rc2 + 0.7152 * gc2 + 0.0722 * bc2
            fg_text = "#000000" if lum > 100 else "#FFFFFF"
            sw = tk.Canvas(swatch_row, width=32, height=32, bg=BG_CARD,
                           highlightthickness=1, highlightbackground=BORDER, cursor="hand2", bd=0)
            sw.create_rectangle(1, 1, 31, 31, fill=display, outline=display, tags="fill")
            sw.create_text(16, 22, text=name[:3], fill=fg_text, font=(FONT_UI, 6, "bold"), tags="lbl")
            sw.pack(side="left", padx=(0, 4))
            sw.bind("<Button-1>", lambda _e, h=hex_rgb: _apply_preset(h))
            sw.bind("<Enter>", lambda _e, canvas=sw: canvas.config(highlightbackground=ACCENT_BLUE, highlightthickness=2))
            sw.bind("<Leave>", lambda _e, canvas=sw: canvas.config(highlightbackground=BORDER, highlightthickness=1))
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))
        for label_text, var, accent in [("Red", r_var, "#e74c3c"),
                                        ("Green", g_var, "#2ecc71"),
                                        ("Blue", b_var, "#3498db")]:
            row = tk.Frame(f, bg=BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label_text, bg=BG_CARD, fg=accent,
                     width=6, font=(FONT_UI, 8, "bold"), anchor="w").pack(side="left")
            tk.Scale(row, from_=0, to=255, orient="horizontal", variable=var,
                     bg=BG_CARD, fg=TEXT, troughcolor=accent, highlightthickness=0,
                     bd=2, sliderrelief="raised", relief="flat", activebackground=BG_INPUT,
                     length=180, showvalue=False, command=lambda _v: update_preview()).pack(side="left", padx=(4, 4))
            tk.Label(row, textvariable=var, bg=BG_CARD, fg=TEXT,
                     font=("Consolas", 9), width=4).pack(side="left")
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

    def _update_led_map(self, inp_idx):
        if inp_idx not in self._led_map_cbs:
            return
        mask = 0
        for j, var in enumerate(self._led_map_cbs[inp_idx]):
            if var.get():
                mask |= (1 << j)
        self.led_maps[inp_idx].set(mask)

    def _schedule_pin_label_refresh(self):
        if not hasattr(self, '_led_map_pin_lbls') or not self._led_map_pin_lbls:
            return
        if not self.led_enabled.get() or not self.led_reactive.get():
            return
        for inp_idx, lbl in self._led_map_pin_lbls.items():
            try:
                if lbl.winfo_exists():
                    lbl.config(text=str(self._pin_vars[inp_idx].get()))
            except tk.TclError:
                pass
        self.root.after(500, self._schedule_pin_label_refresh)

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

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for w in self._all_widgets:
            try:
                w.config(state=state)
            except Exception:
                pass
        try:
            self._defaults_btn.set_state(state)
            self._save_btn.set_state(state)
        except Exception:
            pass

    # ── Config load ───────────────────────────────────────────────────

    def _load_config(self, cfg=None):
        if cfg is None:
            try:
                cfg = self.pico.get_config()
            except Exception as exc:
                messagebox.showerror("Error", f"Failed to read config: {exc}")
                return

        host_pin = int(cfg.get("usb_host_pin", self._usb_host_pin_var.get()))
        dm_first = int(cfg.get("usb_host_dm_first", self._usb_host_dm_first_var.get()))
        self._usb_host_pin_var.set(host_pin)
        self._usb_host_dm_first_var.set(dm_first)
        if host_pin in self.USB_HOST_START_PINS and self._usb_host_pin_combo is not None:
            self._usb_host_pin_combo.current(self.USB_HOST_START_PINS.index(host_pin))
        if dm_first in (0, 1) and self._usb_host_order_combo is not None:
            self._usb_host_order_combo.current(dm_first)

        for i in range(self.PEDAL_COUNT):
            pin_key = f"pedal{i}"
            map_key = f"pedal{i}_map"
            if pin_key in cfg:
                pin = int(cfg[pin_key])
                self._pin_vars[i].set(pin)
                if pin in DIGITAL_PINS:
                    self._pin_combos[i].current(DIGITAL_PINS.index(pin))
            if map_key in cfg:
                mapping = int(cfg[map_key])
                self._map_vars[i].set(mapping)
                if 0 <= mapping < len(self.BUTTON_INDEX_LABELS):
                    self._map_combos[i].current(mapping)

        if "debounce" in cfg:
            self.debounce_var.set(int(cfg["debounce"]))
        if "device_name" in cfg:
            self.device_name.set(cfg["device_name"])

        # ADC analog input slots
        for i in range(2):
            pin_key    = f"adc{i}"
            axis_key   = f"adc{i}_axis"
            invert_key = f"adc{i}_invert"
            min_key    = f"adc{i}_min"
            max_key    = f"adc{i}_max"

            if pin_key in cfg:
                pin = int(cfg[pin_key])
                self._adc_pin_vars[i].set(pin)
                if pin in self.ADC_PINS:
                    self._adc_pin_combos[i].current(self.ADC_PINS.index(pin))
            if axis_key in cfg:
                axis = int(cfg[axis_key])
                self._adc_axis_vars[i].set(axis)
                if 0 <= axis < len(self.ADC_AXIS_LABELS):
                    self._adc_axis_combos[i].current(axis)
            if invert_key in cfg:
                self._adc_invert_vars[i].set(int(cfg[invert_key]) != 0)
            if min_key in cfg:
                self._adc_min_vars[i].set(int(cfg[min_key]))
            if max_key in cfg:
                self._adc_max_vars[i].set(int(cfg[max_key]))

        if "led_enabled" in cfg:
            self.led_enabled.set(int(cfg["led_enabled"]) != 0)
        if "led_count" in cfg:
            self.led_count.set(int(cfg["led_count"]))
        if "led_brightness" in cfg:
            self.led_base_brightness.set(self._brightness_from_hw(int(cfg["led_brightness"])))
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
        for i in range(len(self.PEDAL_LED_INPUT_INDICES)):
            self.led_maps[i].set(0)
        if "led_map_raw" in cfg:
            for pair in cfg["led_map_raw"].split(","):
                pair = pair.strip()
                if "=" not in pair:
                    continue
                name, rest = pair.split("=", 1)
                name = name.strip()
                if name not in PEDAL_LED_INPUT_NAMES:
                    continue
                idx = PEDAL_LED_INPUT_NAMES.index(name)
                if ":" in rest:
                    hex_mask, bright = rest.split(":", 1)
                    self.led_maps[idx].set(int(hex_mask, 16))
                    self.led_active_br[idx].set(self._brightness_from_hw(int(bright)))
        any_mapped = any(self.led_maps[i].get() != 0 for i in range(len(self.PEDAL_LED_INPUT_INDICES)))
        self.led_reactive.set(any_mapped)
        for i in range(len(self.PEDAL_LED_INPUT_INDICES)):
            self._led_maps_backup[i] = self.led_maps[i].get()
        self._on_led_toggle()
        if self.led_enabled.get():
            self._rebuild_led_color_grid()
            if self.led_reactive.get():
                self._rebuild_led_map_grid()

    # ── Push all values to firmware ───────────────────────────────────

    def _push_all_values(self):
        self.pico.set_value("usb_host_pin", str(self._usb_host_pin_var.get()))
        self.pico.set_value("usb_host_dm_first", str(self._usb_host_dm_first_var.get()))
        for i in range(self.PEDAL_COUNT):
            self.pico.set_value(f"pedal{i}", str(self._pin_vars[i].get()))
            self.pico.set_value(f"pedal{i}_map", str(self._map_vars[i].get()))
        for i in range(2):
            self.pico.set_value(f"adc{i}", str(self._adc_pin_vars[i].get()))
            self.pico.set_value(f"adc{i}_axis", str(self._adc_axis_vars[i].get()))
            self.pico.set_value(f"adc{i}_invert",
                                "1" if self._adc_invert_vars[i].get() else "0")
            self.pico.set_value(f"adc{i}_min", str(self._adc_min_vars[i].get()))
            self.pico.set_value(f"adc{i}_max", str(self._adc_max_vars[i].get()))
        self.pico.set_value("debounce", str(self.debounce_var.get()))
        name = ''.join(c for c in self.device_name.get() if c in VALID_NAME_CHARS).strip() or "Pedal Controller"
        self.pico.set_value("device_name", name[:20])
        self.pico.set_value("led_enabled", "1" if self.led_enabled.get() else "0")
        self.pico.set_value("led_count", str(self.led_count.get()))
        self.pico.set_value("led_brightness", str(self._brightness_to_hw(self.led_base_brightness.get())))
        count = self.led_count.get()
        for i in range(min(count, MAX_LEDS)):
            color = self.led_colors[i].get().strip().upper()
            if len(color) != 6:
                color = "FFFFFF"
            self.pico.set_value(f"led_color_{i}", color)
        for ui_idx, fw_idx in enumerate(self.PEDAL_LED_INPUT_INDICES):
            self.pico.set_value(f"led_map_{fw_idx}", f"{self.led_maps[ui_idx].get():04X}")
            self.pico.set_value(f"led_active_{fw_idx}",
                                str(self._brightness_to_hw(self.led_active_br[ui_idx].get())))
        self.pico.set_value("led_loop_enabled", "1" if self.led_loop_enabled.get() else "0")
        self.pico.set_value("led_loop_start", str(self.led_loop_start.get() - 1))
        self.pico.set_value("led_loop_end", str(self.led_loop_end.get() - 1))
        self.pico.set_value("led_breathe_enabled", "1" if self.led_breathe_enabled.get() else "0")
        self.pico.set_value("led_breathe_start", str(self.led_breathe_start.get() - 1))
        self.pico.set_value("led_breathe_end", str(self.led_breathe_end.get() - 1))
        self.pico.set_value("led_breathe_min", str(round(self.led_breathe_min.get() * 31 / 9)))
        self.pico.set_value("led_breathe_max", str(round(self.led_breathe_max.get() * 31 / 9)))
        self.pico.set_value("led_wave_enabled", "1" if self.led_wave_enabled.get() else "0")
        self.pico.set_value("led_wave_origin", str(self.led_wave_origin.get() - 1))
        for _k, _v in [("led_loop_speed", str(self.led_loop_speed.get())),
                       ("led_breathe_speed", str(self.led_breathe_speed.get())),
                       ("led_wave_speed", str(self.led_wave_speed.get()))]:
            try:
                self.pico.set_value(_k, _v)
            except ValueError:
                pass

    # ── Save & Play Mode ──────────────────────────────────────────────

    def _save_and_reboot(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the pedal controller before saving.")
            return
        self._stop_adc_monitoring()
        self._stop_detect()
        error = self._validate_usb_host_conflicts()
        if error:
            self._show_usb_host_conflict(error)
            return
        try:
            self._push_all_values()
            self.pico.save()
            self._set_status("   Saved — rebooting to play mode...", ACCENT_GREEN)
            self.root.update_idletasks()
            time.sleep(0.4)
            self.pico.reboot()
            self.pico.disconnect()
            self._set_status("   Saved. Returning to main menu...", ACCENT_GREEN)
            self._set_controls_enabled(False)
            self._connect_btn.set_state("normal")
            if self._on_back:
                self.hide()
                self._on_back()
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    # ── Reset to Defaults ─────────────────────────────────────────────

    def _reset_defaults(self):
        if not self.pico.connected:
            return
        if not messagebox.askyesno("Reset to Defaults",
                "Reset all pedal settings to factory defaults?\n\n"
                "This will overwrite pin assignments and button mappings."):
            return
        try:
            self.pico.ser.write(b"DEFAULTS\n")
            self.pico.ser.flush()
            time.sleep(0.3)
            self._load_config()
            self._set_status("   Reset to defaults.", ACCENT_ORANGE)
        except Exception as exc:
            messagebox.showerror("Reset Error", str(exc))

    # ── Status bar ────────────────────────────────────────────────────

    def _set_status(self, text, color=TEXT_DIM):
        self._status_var.set(text)
        try:
            self._status_lbl.config(fg=color)
        except Exception:
            pass
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    # ── Navigation / lifecycle ───────────────────────────────────────

    def _go_back(self):
        self._stop_adc_monitoring()
        self._stop_detect()
        if self.pico.connected:
            error = self._validate_usb_host_conflicts()
            if error:
                self._show_usb_host_conflict(error)
                return
            self._set_status("   Saving configuration...", ACCENT_ORANGE)
            try:
                self._push_all_values()
                self.pico.save()
                self._set_status("   Configuration saved.", ACCENT_GREEN)
            except Exception:
                pass
        if self._on_back:
            self.hide()
            self._on_back()

    def _on_close(self):
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
        self.root.destroy()

    def show(self):
        self.root.title("OCC - Pedal Controller Configurator")
        self.root.config(menu=self._menu_bar)
        self.frame.pack(fill="both", expand=True)
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._scroll_canvas.bind_all("<Button-4>", self._on_mousewheel)
        self._scroll_canvas.bind_all("<Button-5>", self._on_mousewheel)

    def hide(self):
        """Hide this screen; reboot device to play mode if connected."""
        self._scroll_canvas.unbind_all("<MouseWheel>")
        self._scroll_canvas.unbind_all("<Button-4>")
        self._scroll_canvas.unbind_all("<Button-5>")
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
            self.pico.disconnect()
        self.frame.pack_forget()

    # ── Connection entry points (called by go_to_configurator) ───────

    def _connect_clicked(self):
        if self.pico.connected:
            self._stop_adc_monitoring()
            self._stop_detect()
            self.pico.reboot()
            self.pico.disconnect()
            self._set_status("   Disconnected", TEXT_DIM)
            self._set_controls_enabled(False)
            self._connect_btn.set_state("normal")
            return
        port = PicoSerial.find_config_port()
        if port:
            self._connect_serial(port)
        else:
            self._connect_xinput()

    def _connect_serial(self, port):
        """Called when device is already in config mode."""
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
            cfg = self.pico.get_config()
            if cfg.get("device_type") != "pedal":
                self.pico.disconnect()
                self._set_status("   Wrong device on config port", ACCENT_RED)
                messagebox.showwarning(
                    "Wrong Device",
                    f"The configurator found '{cfg.get('device_type', 'unknown')}' on {port}, not a pedal.")
                return
            self._set_status(f"   Connected  —  {port}", ACCENT_GREEN)
            try:
                self._connect_btn.set_state("disabled")
            except Exception:
                pass
            self._set_controls_enabled(True)
            self._load_config(cfg=cfg)
        except Exception as exc:
            self._set_status(f"   Connection failed: {exc}", ACCENT_RED)

    def _connect_xinput(self):
        """Called when device is in XInput play mode — send magic, wait for port."""
        self._set_status("   Scanning for play-mode controllers...", ACCENT_BLUE)
        controllers = xinput_get_connected() if XINPUT_AVAILABLE else []
        if not controllers:
            self._set_status("   No controllers found", ACCENT_RED)
            messagebox.showwarning("No Controllers",
                "No supported play-mode controllers detected.\n"
                "Make sure the pedal controller is plugged in and recognised by the system.")
            return

        slot = controllers[0][0]
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
                "The pedal controller didn't switch to config mode.\n"
                "Close any games or apps using the controller and retry.")

    def _wait_for_port(self, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            port = PicoSerial.find_config_port()
            if port:
                time.sleep(0.5)
                if PicoSerial.find_config_port() == port:
                    return port
            time.sleep(0.2)
        return None

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

    # ── Advanced > Flash Firmware ────────────────────────────────────

    def _flash_firmware(self, uf2=None):
        if not uf2:
            uf2 = filedialog.askopenfilename(
                title="Select UF2 Firmware File",
                filetypes=[("UF2 Firmware", "*.uf2"), ("All Files", "*.*")])
            if not uf2:
                return

        # Warn before flashing wireless firmware — prevents accidental wireless flash on non-wireless Picos
        if os.path.basename(uf2).startswith("Wireless_"):
            if not messagebox.askyesno(
                "Firmware Mismatch",
                "Wired firmware is currently installed.\n\n"
                "Are you sure you want to install wireless firmware?"):
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
            drive = find_rpi_rp2_drive()

            if not drive:
                if _booting_from_config:
                    # Already sent BOOTSEL before navigating away — wait for drive
                    drive = self._wait_for_drive(12.0)
                elif self.pico.connected:
                    self.root.after(0, lambda: self._set_status(
                        "   Entering BOOTSEL mode...", ACCENT_ORANGE))
                    try:
                        self.pico.bootsel()
                        self.pico.disconnect()
                    except Exception:
                        pass
                    self.root.after(0, lambda: [
                        self._connect_btn.set_state("normal"),
                        self._set_controls_enabled(False),
                    ])
                    drive = self._wait_for_drive(12.0)

                elif XINPUT_AVAILABLE:
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

    # ── Advanced > Enter BOOTSEL Mode ───────────────────────────────

    def _enter_bootsel(self):
        enter_bootsel_for(self)

    # ── Advanced > Export / Import Configuration ────────────────────

    def _export_config(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the pedal controller before exporting.")
            return
        device_name = self.device_name.get().strip() or "Pedal Controller"
        date_str = datetime.datetime.now().strftime("%m-%d-%Y")
        default_name = f"{device_name} {date_str}"
        path = filedialog.asksaveasfilename(
            title="Export Pedal Configuration",
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            cfg = self.pico.get_config()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            messagebox.showinfo("Export Successful",
                                f"Configuration exported to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _apply_config_dict(self, cfg):
        """Push all SET-able keys from cfg to the firmware. Returns list of error strings."""
        merged_cfg = {
            "usb_host_pin": self._usb_host_pin_var.get(),
            "usb_host_dm_first": self._usb_host_dm_first_var.get(),
        }
        for i in range(self.PEDAL_COUNT):
            merged_cfg[f"pedal{i}"] = self._pin_vars[i].get()
        for i in range(2):
            merged_cfg[f"adc{i}"] = self._adc_pin_vars[i].get()
        merged_cfg.update(cfg)
        conflict = self._validate_usb_host_conflicts(cfg=merged_cfg)
        if conflict:
            return [conflict]
        return apply_config_to_pico(self.pico, cfg, led_input_names=PEDAL_LED_INPUT_NAMES)

    def _import_config(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the pedal controller before importing.")
            return
        path = filedialog.askopenfilename(
            title="Import Pedal Configuration",
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

        errors = self._apply_config_dict(cfg)
        if errors:
            messagebox.showwarning("Import Partial",
                f"Some keys could not be set:\n" + "\n".join(errors[:10]))
        else:
            self._load_config()
            if messagebox.askyesno("Import Successful",
                    "Configuration imported.\n\nSave to flash now?"):
                try:
                    self.pico.save()
                    self._set_status("   Config saved to flash", ACCENT_GREEN)
                except Exception as exc:
                    messagebox.showerror("Save Error", str(exc))

    def _import_preset(self, filepath):
        """Load a preset JSON directly and push to firmware (no file dialog)."""
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the pedal controller before loading a preset.")
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as exc:
            messagebox.showerror("Preset Error", f"Could not read preset:\n{exc}")
            return

        errors = self._apply_config_dict(cfg)
        if errors:
            messagebox.showwarning("Preset Partial",
                f"Some keys could not be set:\n" + "\n".join(errors[:10]))
        else:
            self._load_config()
            if messagebox.askyesno("Preset Loaded",
                    "Preset applied.\n\nSave to flash now?"):
                try:
                    self.pico.save()
                    self._set_status("   Config saved to flash", ACCENT_GREEN)
                except Exception as exc:
                    messagebox.showerror("Save Error", str(exc))

    # ── Advanced > Serial Debug Console ─────────────────────────────

    def _debug_log(self, line):
        txt = getattr(self, '_debug_text', None)
        if txt is None:
            return
        try:
            txt.configure(state="normal")
            txt.insert("end", line + "\n")
            total = int(txt.index("end-1c").split(".")[0])
            if total > 500:
                txt.delete("1.0", f"{total - 500}.0")
            txt.see("end")
            txt.configure(state="disabled")
        except Exception:
            pass

    def _show_serial_debug(self):
        if getattr(self, '_debug_win', None):
            try:
                if self._debug_win.winfo_exists():
                    self._debug_win.lift()
                    self._debug_win.focus_force()
                    return
            except Exception:
                pass

        win = tk.Toplevel()
        win.title("Serial Debug Console — Pedal Controller")
        win.configure(bg=BG_MAIN)
        win.geometry("700x520")
        win.minsize(500, 380)
        win.resizable(True, True)
        self._debug_win = win

        import queue as _queue
        _send_queue = _queue.Queue()

        TAG_OUT  = "out"
        TAG_IN   = "in"
        TAG_ERR  = "err"
        TAG_INFO = "info"

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

        def _send_raw(cmd):
            _log(f">> {cmd}", TAG_OUT)
            if not self.pico.connected:
                _log("!! Not connected — connect first.", TAG_ERR)
                return
            _send_queue.put(cmd.strip())

        info_frame = tk.Frame(win, bg=BG_CARD)
        info_frame.pack(fill="x", padx=8, pady=(8, 0), ipady=5)
        tk.Label(info_frame, text="Config:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8, "bold")).pack(side="left", padx=(8, 4))
        info_lbl = tk.Label(info_frame, text="", bg=BG_CARD, fg=TEXT,
                            font=("Consolas", 8))
        info_lbl.pack(side="left", fill="x", expand=True)

        def _refresh_info():
            conn = getattr(self, 'pico', None)
            info_lbl.config(text="connected" if (conn and conn.connected) else "NOT connected")

        _refresh_info()
        tk.Button(info_frame, text="↺ Refresh", bg=BG_INPUT, fg=TEXT_DIM,
                  font=(FONT_UI, 7), relief="flat", bd=0, padx=6,
                  command=_refresh_info).pack(side="right", padx=6)

        qbar = tk.Frame(win, bg=BG_MAIN)
        qbar.pack(fill="x", padx=8, pady=(6, 0))
        QUICK = [
            ("PING",       "PING",       ACCENT_BLUE),
            ("GET CONFIG", "GET_CONFIG", ACCENT_BLUE),
            ("SCAN",       "SCAN",       ACCENT_BLUE),
            ("STOP",       "STOP",       ACCENT_ORANGE),
            ("REBOOT",     "REBOOT",     ACCENT_RED),
        ]
        for lbl, cmd, color in QUICK:
            RoundedButton(qbar, text=lbl, command=lambda c=cmd: _send_raw(c),
                          bg_color=color, btn_width=90, btn_height=24,
                          btn_font=(FONT_UI, 7, "bold")).pack(
                side="left", padx=(0, 4), pady=2)

        ref_frame = tk.Frame(win, bg=BG_CARD)
        ref_frame.pack(fill="x", padx=8, pady=(4, 0))

        REF_LINES = [
            "SET:usb_host_pin=<0-27>      -> choose the first GPIO in the USB host pair",
            "SET:usb_host_dm_first=<0|1>  -> 0=D+/D-, 1=D-/D+ on the selected pair",
            "PING                         → PONG  (connection check)",
            "GET_CONFIG                   → DEVTYPE:pedal + CFG: line",
            "SCAN                         → streams PIN:N on button press; send STOP to end",
            "STOP                         → ends SCAN mode",
            "SET:pedal0=<pin>             → assign GPIO pin (-1 to 28) to Pedal 1",
            "SET:pedal0_map=<0-13>        → map Pedal 1 to XInput button (0=Green … 13=Guide)",
            "SET:debounce=<0-50>          → debounce time in ms",
            "SET:device_name=<name>       → custom USB device name (max 31 chars)",
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
        self._debug_text.tag_config(TAG_OUT,  foreground="#668866")
        self._debug_text.tag_config(TAG_IN,   foreground="#b0ffb0")
        self._debug_text.tag_config(TAG_ERR,  foreground="#ff6060")
        self._debug_text.tag_config(TAG_INFO, foreground="#6699cc")

        send_frame = tk.Frame(win, bg=BG_MAIN)
        send_frame.pack(fill="x", padx=8, pady=6)
        tk.Label(send_frame, text="CMD:", bg=BG_MAIN, fg=TEXT_DIM,
                 font=("Consolas", 9, "bold")).pack(side="left", padx=(0, 4))
        entry_var = tk.StringVar()
        entry = tk.Entry(send_frame, textvariable=entry_var,
                         bg=BG_INPUT, fg="#ffffff", insertbackground="#ffffff",
                         font=("Consolas", 10), relief="flat",
                         highlightthickness=2, highlightcolor=ACCENT_BLUE,
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
                    try:
                        cmd = _send_queue.get_nowait()
                        try:
                            ser.write((cmd + "\n").encode())
                            ser.flush()
                        except Exception as exc:
                            win.after(0, lambda e=str(exc): _log(f"!! Write error: {e}", TAG_ERR))
                    except _queue.Empty:
                        pass
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

        threading.Thread(target=_reader_thread, daemon=True).start()

        def _on_close():
            self._debug_reader_running = False
            self._debug_text = None
            self._debug_win  = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)
        _log("=== Serial Debug Console — Pedal Controller ===", TAG_INFO)
        _log("Type a command below and press Enter, or use the quick buttons above.", TAG_INFO)
        _log("Click '▶ Command Reference' to see all available commands.", TAG_INFO)
        _log("", TAG_INFO)
        win.after(50, entry.focus_set)

    # ── Help > About ────────────────────────────────────────────────

    def _show_about(self):
        messagebox.showinfo("About",
            "OCC — Open Controller Configurator\n"
            "Guitars, Drums, Whatever you want I guess\n"
            "threepieces.nut")
