import sys, os, time, threading, json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .constants import (BG_MAIN, BG_CARD, BG_INPUT, BG_HOVER, BORDER, TEXT, TEXT_DIM,
                         TEXT_HEADER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
                         DIGITAL_PINS, DIGITAL_PIN_LABELS)
from .fonts import FONT_UI, APP_VERSION
from .widgets import RoundedButton, HelpButton, HelpDialog, CustomDropdown, _help_text, _help_placeholder
from .serial_comms import PicoSerial
from .firmware_utils import (flash_uf2_with_reboot, enter_bootsel_for,
                              find_uf2_files, find_uf2_for_device_type,
                              get_bundled_fw_date_str, find_rpi_rp2_drive)
from .xinput_utils import XINPUT_AVAILABLE
from .utils import _centered_dialog, _center_window, _make_flash_popup, _find_preset_configs
class RetroApp:
    """Retro Controller configurator screen."""

    RETRO_BUTTON_DEFS = [
        ("btn0",  "D-Pad Up"),
        ("btn1",  "D-Pad Down"),
        ("btn2",  "D-Pad Left"),
        ("btn3",  "D-Pad Right"),
        ("btn4",  "A"),
        ("btn5",  "B"),
        ("btn6",  "X"),
        ("btn7",  "Y"),
        ("btn8",  "Start"),
        ("btn9",  "Select"),
        ("btn10", "Guide"),
        ("btn11", "LB"),
        ("btn12", "RB"),
    ]

    # GPIO options: -1 (disabled) then 0-27
    GPIO_OPTIONS = ["-1"] + [str(i) for i in range(28)]
    GPIO_LABELS  = ["Disabled"] + [f"GPIO {i}" for i in range(28)]

    # ADC-capable pins only (for analog trigger pin selectors)
    ADC_OPTIONS = ["-1", "26", "27", "28"]
    ADC_LABELS  = ["Disabled", "GPIO 26  (ADC0)", "GPIO 27  (ADC1)", "GPIO 28  (ADC2)"]

    def __init__(self, root, on_back=None):
        self.root     = root
        self._on_back = on_back
        self.root.configure(bg=BG_MAIN)

        self.pico  = PicoSerial()
        self.frame = tk.Frame(root, bg=BG_MAIN)

        # ── tk.Vars: button GPIO pins ──────────────────────────────
        self._pin_vars = {}
        for key, _ in self.RETRO_BUTTON_DEFS:
            self._pin_vars[key] = tk.IntVar(value=-1)

        # ── tk.Vars: trigger pins and modes ───────────────────────
        self._pin_lt  = tk.IntVar(value=26)
        self._pin_rt  = tk.IntVar(value=27)
        self._mode_lt = tk.IntVar(value=0)   # 0=digital, 1=analog
        self._mode_rt = tk.IntVar(value=0)

        # ── tk.Vars: trigger calibration ──────────────────────────
        self._lt_min    = tk.IntVar(value=0)
        self._lt_max    = tk.IntVar(value=4095)
        self._rt_min    = tk.IntVar(value=0)
        self._rt_max    = tk.IntVar(value=4095)
        self._lt_ema    = tk.IntVar(value=0)   # 0-100 linear percent, NOT lookup table
        self._rt_ema    = tk.IntVar(value=0)
        self._lt_invert = tk.BooleanVar(value=False)
        self._rt_invert = tk.BooleanVar(value=False)

        # ── tk.Vars: misc ─────────────────────────────────────────
        self._debounce  = tk.IntVar(value=5)
        self.device_name = tk.StringVar(value="Retro Controller")

        # ── State ─────────────────────────────────────────────────
        self._status_var          = tk.StringVar(value="")
        self._debug_win           = None
        self._help_dialog         = None
        self._debug_text          = None
        self._debug_reader_running = False
        self.scanning             = False
        self._monitoring          = False
        self._monitor_thread      = None

        # ── Widget tracking ───────────────────────────────────────
        self._all_widgets        = []
        self._btn_detect_buttons = {}
        self._btn_combos         = {}

        # ── Trigger UI refs (for show/hide on mode switch) ────────
        self._lt_analog_frame = None
        self._rt_analog_frame = None
        self._lt_pin_combo    = None
        self._rt_pin_combo    = None
        self._lt_monitor_bar  = None
        self._rt_monitor_bar  = None
        self._lt_detect_btn   = None
        self._rt_detect_btn   = None

        # ── Active scan tracking ──────────────────────────────────
        self._scan_det_btn    = None   # detect button currently acting as cancel

        # ── Scroll state ──────────────────────────────────────────
        self._scroll_enabled   = True
        self._scroll_animating = False
        self._scroll_target    = None

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
        presets = _find_preset_configs({"pico_retro"})
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

        self._menubar = mb

    def _open_help(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self.root, [
                ("Overview",       _help_placeholder()),
                ("Button Mapping", _help_placeholder()),
                ("Triggers",       _help_placeholder()),
            ])
        self._help_dialog.open()

    # ── Full UI build ────────────────────────────────────────────────

    def _build_ui(self):
        outer = self.frame
        outer.configure(bg=BG_MAIN)

        # ── Connection card ──────────────────────────────────────────
        conn_card = tk.Frame(outer, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        conn_card.pack(fill="x", pady=(8, 6), padx=12, ipady=6, ipadx=14)

        tk.Label(conn_card, text="CONNECTION", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=14, pady=(6, 0))
        tk.Label(conn_card,
                 text="Click Connect to switch the retro controller to config mode.",
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

        # ── Scrollable content area ──────────────────────────────────
        scroll_outer = tk.Frame(outer, bg=BG_MAIN)
        scroll_outer.pack(fill="both", expand=True, padx=12)

        self._scroll_canvas = tk.Canvas(scroll_outer, bg=BG_MAIN,
                                        highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(scroll_outer, orient="vertical",
                                        command=self._on_yview)
        self.content = tk.Frame(self._scroll_canvas, bg=BG_MAIN)

        self.content.bind("<Configure>", self._on_content_configure)
        self._content_window = self._scroll_canvas.create_window(
            (0, 0), window=self.content, anchor="nw")
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")
        self._scroll_canvas.bind("<Configure>", self._on_canvas_resize)

        # ── Sections ─────────────────────────────────────────────────
        self._make_device_name_section(self.content)
        self._build_buttons_section(self.content)
        self._build_triggers_section(self.content)
        self._make_debounce_section(self.content)

        # ── Bottom action bar ─────────────────────────────────────────
        bottom = tk.Frame(outer, bg=BG_MAIN)
        bottom.pack(fill="x", pady=(6, 8), padx=12)

        RoundedButton(
            bottom, text="◀  Main Menu", command=self._go_back,
            bg_color="#555560", btn_width=130, btn_height=32,
            btn_font=(FONT_UI, 8, "bold")).pack(side="left", padx=(0, 8))

        self._save_btn = RoundedButton(
            bottom, text="Save & Enter Play Mode",
            command=self._save_and_reboot,
            bg_color=ACCENT_GREEN, btn_width=200, btn_height=34)
        self._save_btn.pack(side="right")
        self._save_btn.set_state("disabled")

        self._set_controls_enabled(False)

    # ── Scroll helpers ───────────────────────────────────────────────

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
        delta = int(-1 * (event.delta / 120))
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

    def _make_card(self, parent=None):
        if parent is None:
            parent = self.content
        card = tk.Frame(parent, bg=BG_CARD,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 6), padx=2)
        return card

    # ── Section: Device Name ─────────────────────────────────────────

    def _make_device_name_section(self, parent):
        card = self._make_card(parent)
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

    # ── Section: Button Pin Mapping ──────────────────────────────────

    def _build_buttons_section(self, parent):
        card = self._make_card(parent)
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="BUTTON PIN MAPPING", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Assign a GPIO pin to each button. "
                      "All inputs use internal pull-ups — wire each button to connect GPIO to GND. "
                      "Press Detect and press the button to auto-assign the pin.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        # Column headers
        hdr = tk.Frame(inner, bg=BG_CARD)
        hdr.pack(fill="x", pady=(0, 2))
        tk.Frame(hdr, width=100, bg=BG_CARD).pack(side="left")
        tk.Label(hdr, text="GPIO Pin", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), width=22, anchor="w").pack(side="left")
        tk.Label(hdr, text="Detect", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), anchor="w").pack(side="left")

        for key, label in self.RETRO_BUTTON_DEFS:
            self._make_button_row(inner, key, label)

    def _make_button_row(self, parent, key, label):
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=label, bg=BG_CARD, fg=TEXT,
                 width=12, anchor="w",
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 8))

        pin_combo = CustomDropdown(
            row, state="readonly", width=20,
            values=self.GPIO_LABELS)
        # Default to "Disabled" (-1 → index 0)
        pin_combo.current(0)
        # Manually sync IntVar after .current() — CLAUDE.md rule
        self._pin_vars[key].set(-1)
        pin_combo.pack(side="left", padx=(0, 6))
        pin_combo.bind("<<ComboboxSelected>>",
                       lambda _e, k=key, c=pin_combo: self._on_btn_combo(k, c))
        self._btn_combos[key] = pin_combo
        self._all_widgets.append(pin_combo)

        det_btn = RoundedButton(
            row, text="Detect",
            command=lambda k=key: self._start_btn_detect(k),
            bg_color="#555560", btn_width=70, btn_height=24,
            btn_font=(FONT_UI, 7, "bold"))
        det_btn.pack(side="left", padx=(0, 8))
        self._btn_detect_buttons[key] = det_btn
        self._all_widgets.append(det_btn)

    def _on_btn_combo(self, key, combo):
        idx = combo.current()
        # GPIO_OPTIONS: index 0 = "-1" (disabled), index N+1 = str(N)
        try:
            self._pin_vars[key].set(int(self.GPIO_OPTIONS[idx]))
        except (ValueError, IndexError):
            self._pin_vars[key].set(-1)

    # ── Section: Trigger Configuration ──────────────────────────────

    def _build_triggers_section(self, parent):
        card = self._make_card(parent)
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="TRIGGER CONFIGURATION", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Select Digital mode for a simple button trigger, "
                      "or Analog mode for a variable-pressure trigger with calibration.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        nb = ttk.Notebook(inner)
        nb.pack(fill="x", expand=False)

        lt_tab = tk.Frame(nb, bg=BG_CARD)
        rt_tab = tk.Frame(nb, bg=BG_CARD)
        nb.add(lt_tab, text=" LT Trigger ")
        nb.add(rt_tab, text=" RT Trigger ")

        self._build_trigger_tab(lt_tab, "lt")
        self._build_trigger_tab(rt_tab, "rt")

    def _build_trigger_tab(self, parent, prefix):
        """Build the UI for one trigger tab. prefix is 'lt' or 'rt'."""
        mode_var = self._mode_lt if prefix == "lt" else self._mode_rt
        pin_var  = self._pin_lt  if prefix == "lt" else self._pin_rt

        # ── Mode selector ────────────────────────────────────────────
        mode_row = tk.Frame(parent, bg=BG_CARD)
        mode_row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(mode_row, text="Mode:", bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 8))
        tk.Radiobutton(mode_row, text="Digital", variable=mode_var, value=0,
                       bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                       activebackground=BG_CARD, activeforeground=TEXT,
                       font=(FONT_UI, 9),
                       command=lambda p=prefix: self._refresh_trigger_tab(p)
                       ).pack(side="left", padx=(0, 8))
        tk.Radiobutton(mode_row, text="Analog", variable=mode_var, value=1,
                       bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                       activebackground=BG_CARD, activeforeground=TEXT,
                       font=(FONT_UI, 9),
                       command=lambda p=prefix: self._refresh_trigger_tab(p)
                       ).pack(side="left")

        # ── GPIO pin row ─────────────────────────────────────────────
        pin_row = tk.Frame(parent, bg=BG_CARD)
        pin_row.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(pin_row, text="Pin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 4))

        # Start with GPIO labels (digital default); switch to ADC labels in analog mode
        pin_combo = CustomDropdown(pin_row, state="readonly", width=22,
                                   values=self.GPIO_LABELS)
        # Sync initial pin var to display
        init_pin = pin_var.get()
        if str(init_pin) in self.GPIO_OPTIONS:
            init_idx = self.GPIO_OPTIONS.index(str(init_pin))
        else:
            init_idx = 0
        pin_combo.current(init_idx)
        pin_var.set(init_pin)   # re-sync after .current() — CLAUDE.md rule
        pin_combo.pack(side="left", padx=(0, 6))
        pin_combo.bind("<<ComboboxSelected>>",
                       lambda _e, pv=pin_var, c=pin_combo, px=prefix:
                           self._on_trigger_pin_combo(pv, c, px))
        self._all_widgets.append(pin_combo)

        det_btn = RoundedButton(
            pin_row, text="Detect",
            command=lambda p=prefix: self._start_trigger_detect(p),
            bg_color="#555560", btn_width=70, btn_height=24,
            btn_font=(FONT_UI, 7, "bold"))
        det_btn.pack(side="left")
        self._all_widgets.append(det_btn)

        if prefix == "lt":
            self._lt_pin_combo  = pin_combo
            self._lt_detect_btn = det_btn
        else:
            self._rt_pin_combo  = pin_combo
            self._rt_detect_btn = det_btn

        # ── Analog-only frame ────────────────────────────────────────
        analog_frame = tk.Frame(parent, bg=BG_CARD)
        # (packed/forgotten by _refresh_trigger_tab)

        min_var    = self._lt_min    if prefix == "lt" else self._rt_min
        max_var    = self._lt_max    if prefix == "lt" else self._rt_max
        ema_var    = self._lt_ema    if prefix == "lt" else self._rt_ema
        invert_var = self._lt_invert if prefix == "lt" else self._rt_invert

        # Min slider
        min_row = tk.Frame(analog_frame, bg=BG_CARD)
        min_row.pack(fill="x", padx=10, pady=(4, 2))
        tk.Label(min_row, text="Min:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), width=14, anchor="w").pack(side="left")
        ttk.Scale(min_row, from_=0, to=4095, orient="horizontal",
                  variable=min_var, length=300).pack(side="left", padx=(0, 6))
        tk.Label(min_row, textvariable=min_var,
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8), width=5).pack(side="left")

        # Max slider
        max_row = tk.Frame(analog_frame, bg=BG_CARD)
        max_row.pack(fill="x", padx=10, pady=(0, 2))
        tk.Label(max_row, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), width=14, anchor="w").pack(side="left")
        ttk.Scale(max_row, from_=0, to=4095, orient="horizontal",
                  variable=max_var, length=300).pack(side="left", padx=(0, 6))
        tk.Label(max_row, textvariable=max_var,
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8), width=5).pack(side="left")

        # EMA alpha slider (0-100 percent)
        ema_row = tk.Frame(analog_frame, bg=BG_CARD)
        ema_row.pack(fill="x", padx=10, pady=(0, 2))
        tk.Label(ema_row, text="Smoothing %:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), width=14, anchor="w").pack(side="left")
        ttk.Scale(ema_row, from_=0, to=100, orient="horizontal",
                  variable=ema_var, length=300).pack(side="left", padx=(0, 6))
        tk.Label(ema_row, textvariable=ema_var,
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8), width=5).pack(side="left")

        # Invert checkbox
        inv_row = tk.Frame(analog_frame, bg=BG_CARD)
        inv_row.pack(fill="x", padx=10, pady=(0, 6))
        tk.Checkbutton(inv_row, text="Invert axis", variable=invert_var,
                       bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                       activebackground=BG_CARD, activeforeground=TEXT,
                       font=(FONT_UI, 9)).pack(side="left")

        # Monitor bar placeholder (Plan 03 wires a LiveBarGraph here)
        monitor_placeholder = tk.Frame(analog_frame, bg=BG_CARD, height=24)
        monitor_placeholder.pack(fill="x", padx=10, pady=(0, 4))
        if prefix == "lt":
            self._lt_monitor_bar  = monitor_placeholder
            self._lt_analog_frame = analog_frame
        else:
            self._rt_monitor_bar  = monitor_placeholder
            self._rt_analog_frame = analog_frame

    def _on_trigger_pin_combo(self, pin_var, combo, prefix):
        """Sync pin_var from the combo selection."""
        idx = combo.current()
        options = self.ADC_OPTIONS if (
            (prefix == "lt" and self._mode_lt.get() == 1) or
            (prefix == "rt" and self._mode_rt.get() == 1)
        ) else self.GPIO_OPTIONS
        try:
            pin_var.set(int(options[idx]))
        except (ValueError, IndexError):
            pin_var.set(-1)

    def _refresh_trigger_tab(self, prefix):
        """Show or hide the analog frame and swap pin dropdown labels based on mode."""
        mode      = self._mode_lt.get() if prefix == "lt" else self._mode_rt.get()
        a_frame   = self._lt_analog_frame if prefix == "lt" else self._rt_analog_frame
        pin_combo = self._lt_pin_combo    if prefix == "lt" else self._rt_pin_combo

        if a_frame is not None:
            if mode == 1:
                # Analog mode: show frame, use ADC options
                a_frame.pack(fill="x")
                if pin_combo is not None:
                    pin_combo.config(values=self.ADC_LABELS)
                    pin_combo.current(0)
                    (self._pin_lt if prefix == "lt" else self._pin_rt).set(-1)
            else:
                # Digital mode: hide frame, use GPIO options
                a_frame.pack_forget()
                if pin_combo is not None:
                    pin_combo.config(values=self.GPIO_LABELS)
                    pin_combo.current(0)
                    (self._pin_lt if prefix == "lt" else self._pin_rt).set(-1)

        self._update_scroll_state()

    # ── Section: Debounce ─────────────────────────────────────────────

    def _make_debounce_section(self, parent):
        card = self._make_card(parent)
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="DEBOUNCE", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 4))
        row = tk.Frame(inner, bg=BG_CARD)
        row.pack(fill="x")
        tk.Label(row, text="Debounce time:", bg=BG_CARD, fg=TEXT).pack(
            side="left", padx=(0, 5))
        sp = ttk.Spinbox(row, from_=0, to=255, width=5,
                         textvariable=self._debounce)
        sp.pack(side="left", padx=(0, 5))
        self._all_widgets.append(sp)
        tk.Label(row, text="ms  (0 = none, 3-5 typical)", bg=BG_CARD,
                 fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left")

    # ── Enable/disable all controls ───────────────────────────────────

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for w in self._all_widgets:
            try:
                w.config(state=state)
            except Exception:
                pass
        try:
            self._save_btn.set_state(state)
        except Exception:
            pass

    # ── Config load ───────────────────────────────────────────────────

    def _load_config(self):
        try:
            cfg = self.pico.get_config()
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read config: {exc}")
            return

        for key, _ in self.RETRO_BUTTON_DEFS:
            pin = int(cfg.get(key, -1))
            self._pin_vars[key].set(pin)
            combo = self._btn_combos.get(key)
            if combo is not None:
                pin_str = str(pin)
                if pin_str in self.GPIO_OPTIONS:
                    idx = self.GPIO_OPTIONS.index(pin_str)
                    combo.current(idx)
                    self._pin_vars[key].set(pin)  # re-sync after .current()

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
        self._debounce.set(int(cfg.get("debounce", 5)))
        self.device_name.set(cfg.get("device_name", "Retro Controller"))

        self._refresh_trigger_tab("lt")
        self._refresh_trigger_tab("rt")
        self._update_scroll_state()

    # ── Push all values to firmware ───────────────────────────────────

    def _push_all_values(self):
        for key, _ in self.RETRO_BUTTON_DEFS:
            self.pico.set_value(key, str(self._pin_vars[key].get()))
        self.pico.set_value("mode_lt",      str(self._mode_lt.get()))
        self.pico.set_value("mode_rt",      str(self._mode_rt.get()))
        self.pico.set_value("pin_lt",       str(self._pin_lt.get()))
        self.pico.set_value("pin_rt",       str(self._pin_rt.get()))
        self.pico.set_value("lt_min",       str(self._lt_min.get()))
        self.pico.set_value("lt_max",       str(self._lt_max.get()))
        self.pico.set_value("rt_min",       str(self._rt_min.get()))
        self.pico.set_value("rt_max",       str(self._rt_max.get()))
        self.pico.set_value("lt_ema_alpha", str(self._lt_ema.get()))
        self.pico.set_value("rt_ema_alpha", str(self._rt_ema.get()))
        self.pico.set_value("lt_invert",    "1" if self._lt_invert.get() else "0")
        self.pico.set_value("rt_invert",    "1" if self._rt_invert.get() else "0")
        self.pico.set_value("debounce",     str(self._debounce.get()))
        name = ''.join(c for c in self.device_name.get()
                       if c in VALID_NAME_CHARS).strip()
        self.pico.set_value("device_name",
                            (name or "Retro Controller")[:20])

    # ── Save & Play Mode ──────────────────────────────────────────────

    def _save_and_reboot(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the retro controller before saving.")
            return
        try:
            self._push_all_values()
            self.pico.save()
            self._set_status("   Saved — rebooting to play mode...", ACCENT_GREEN)
            self.root.update_idletasks()
            time.sleep(0.4)
            self.pico.reboot()
            self.pico.disconnect()
            self._set_status("   Saved. Controller is in play mode.", ACCENT_GREEN)
            self._set_controls_enabled(False)
            self._connect_btn.set_state("normal")
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

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
        if self.pico.connected:
            self._set_status("   Saving configuration...", ACCENT_ORANGE)
            try:
                self._push_all_values()
                self.pico.save()
                self.pico.reboot()
                self.pico.disconnect()
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
        self.root.title("OCC Configurator - Retro Controller")
        self.root.config(menu=self._menubar)
        self.frame.pack(fill="both", expand=True)
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def hide(self):
        self._scroll_canvas.unbind_all("<MouseWheel>")
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
            self.pico.disconnect()
        self.frame.pack_forget()

    # ── Connection ────────────────────────────────────────────────────

    def _connect_clicked(self):
        if self.pico.connected:
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
            self._set_status(f"   Connected  —  {port}", ACCENT_GREEN)
            try:
                self._connect_btn.set_state("disabled")
            except Exception:
                pass
            self._set_controls_enabled(True)
            self._load_config()
        except Exception as exc:
            self._set_status(f"   Connection failed: {exc}", ACCENT_RED)

    def _connect_xinput(self):
        """Called when device is in XInput play mode — send magic, wait for port."""
        self._set_status("   Scanning for XInput controllers...", ACCENT_BLUE)
        controllers = xinput_get_connected() if XINPUT_AVAILABLE else []
        if not controllers:
            self._set_status("   No controllers found", ACCENT_RED)
            messagebox.showwarning("No Controllers",
                "No XInput controllers detected.\n"
                "Make sure the retro controller is plugged in and recognised by Windows.")
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
                "The retro controller didn't switch to config mode.\n"
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

    # ── Detect helpers ───────────────────────────────────────────────

    def _set_det_btn_stop(self, det_btn, cancel_fn):
        """Convert a detect button to a Stop button in-place."""
        det_btn._label     = "Stop"
        det_btn._bg        = ACCENT_ORANGE
        det_btn._hover_bg  = det_btn._adjust(ACCENT_ORANGE, 25)
        det_btn._press_bg  = det_btn._adjust(ACCENT_ORANGE, -25)
        det_btn._command   = cancel_fn
        det_btn._render(det_btn._bg)
        self._scan_det_btn = det_btn

    def _restore_all_detect_btns(self):
        """Re-enable and reset every detect button (button rows + triggers)."""
        all_btns = list(self._btn_detect_buttons.values())
        for btn in [self._lt_detect_btn, self._rt_detect_btn]:
            if btn:
                all_btns.append(btn)
        for btn in all_btns:
            try:
                btn._label    = "Detect"
                btn._bg       = "#555560"
                btn._hover_bg = btn._adjust("#555560", 25)
                btn._press_bg = btn._adjust("#555560", -25)
                btn.set_state("normal")
                btn._render(btn._bg)
            except Exception:
                pass
        self._scan_det_btn = None

    # ── Button detect ────────────────────────────────────────────────

    def _start_btn_detect(self, key):
        """Start a SCAN to detect which GPIO pin a button press comes from."""
        if not self.pico.connected:
            self._set_status("   Not connected to controller.", ACCENT_ORANGE)
            return

        det_btn = self._btn_detect_buttons.get(key)

        # If already scanning, cancel
        if self.scanning:
            self.scanning = False
            try:
                self.pico.stop_scan()
            except Exception:
                pass
            self._restore_all_detect_btns()
            self._set_status("")
            return

        label = dict(self.RETRO_BUTTON_DEFS).get(key, key)
        self.scanning = True

        # Active button → Stop; all others → disabled
        if det_btn:
            self._set_det_btn_stop(det_btn, lambda: self._start_btn_detect(key))
        for k, btn in self._btn_detect_buttons.items():
            if k != key:
                try:
                    btn.set_state("disabled")
                except Exception:
                    pass
        for btn in [self._lt_detect_btn, self._rt_detect_btn]:
            if btn:
                try:
                    btn.set_state("disabled")
                except Exception:
                    pass

        self._set_status(f"   Detecting pin for {label} — press the button now...", ACCENT_BLUE)

        def _on_detected(pin):
            self._restore_all_detect_btns()
            combo = self._btn_combos.get(key)
            if combo:
                pin_str = str(pin)
                if pin_str in self.GPIO_OPTIONS:
                    idx = self.GPIO_OPTIONS.index(pin_str)
                    combo.current(idx)
                    self._pin_vars[key].set(pin)
            self._set_status(f"   Detected GPIO {pin} for {label}", ACCENT_GREEN)

        def _on_error(msg):
            self._restore_all_detect_btns()
            self._set_status(f"   Scan error: {msg}", ACCENT_ORANGE)

        def _thread():
            try:
                self.pico.start_scan()
                deadline = time.time() + 15.0
                while self.scanning and time.time() < deadline:
                    line = self.pico.read_scan_line(0.1)
                    if line and line.startswith("PIN:"):
                        try:
                            pin = int(line[4:])
                        except ValueError:
                            continue
                        if 0 <= pin <= 28 and pin not in (23, 24, 25):
                            self.pico.stop_scan()
                            self.scanning = False
                            self.root.after(0, lambda p=pin: _on_detected(p))
                            return
            except Exception as exc:
                self.root.after(0, lambda e=str(exc): _on_error(e))
                return
            if self.scanning:
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                self.root.after(0, self._restore_all_detect_btns)
                self.root.after(0, lambda: self._set_status(""))

        threading.Thread(target=_thread, daemon=True).start()

    # ── Trigger detect ───────────────────────────────────────────────

    def _start_trigger_detect(self, prefix):
        """Start a SCAN to detect which GPIO pin a trigger press comes from."""
        if not self.pico.connected:
            self._set_status("   Not connected to controller.", ACCENT_ORANGE)
            return

        det_btn = self._lt_detect_btn if prefix == "lt" else self._rt_detect_btn
        mode    = self._mode_lt.get() if prefix == "lt" else self._mode_rt.get()
        label   = "LT" if prefix == "lt" else "RT"

        # If already scanning, cancel
        if self.scanning:
            self.scanning = False
            try:
                self.pico.stop_scan()
            except Exception:
                pass
            self._restore_all_detect_btns()
            self._set_status("")
            return

        self.scanning = True
        hint = "press the trigger" if mode == 0 else "move the trigger (analog)"

        # Active button → Stop; all others → disabled
        if det_btn:
            self._set_det_btn_stop(det_btn, lambda p=prefix: self._start_trigger_detect(p))
        for btn in self._btn_detect_buttons.values():
            try:
                btn.set_state("disabled")
            except Exception:
                pass
        other_trig = self._rt_detect_btn if prefix == "lt" else self._lt_detect_btn
        if other_trig:
            try:
                other_trig.set_state("disabled")
            except Exception:
                pass

        self._set_status(f"   Detecting pin for {label} trigger — {hint}...", ACCENT_BLUE)

        pin_var   = self._pin_lt  if prefix == "lt" else self._pin_rt
        pin_combo = self._lt_pin_combo if prefix == "lt" else self._rt_pin_combo

        def _on_detected(pin):
            self._restore_all_detect_btns()
            if pin_combo:
                if mode == 1:  # analog
                    pin_str = str(pin)
                    if pin_str in self.ADC_OPTIONS:
                        pin_combo.current(self.ADC_OPTIONS.index(pin_str))
                        pin_var.set(pin)
                else:  # digital
                    pin_str = str(pin)
                    if pin_str in self.GPIO_OPTIONS:
                        pin_combo.current(self.GPIO_OPTIONS.index(pin_str))
                        pin_var.set(pin)
            mode_str = "analog" if mode == 1 else "digital"
            self._set_status(f"   Detected GPIO {pin} for {label} trigger ({mode_str})", ACCENT_GREEN)

        def _on_error(msg):
            self._restore_all_detect_btns()
            self._set_status(f"   Scan error: {msg}", ACCENT_ORANGE)

        def _thread():
            try:
                self.pico.start_scan()
                deadline = time.time() + 15.0
                while self.scanning and time.time() < deadline:
                    line = self.pico.read_scan_line(0.1)
                    if line and line.startswith("PIN:"):
                        try:
                            pin = int(line[4:])
                        except ValueError:
                            continue
                        if mode == 1:  # analog — ADC pins only
                            if pin in (26, 27, 28):
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p))
                                return
                        else:  # digital — any non-reserved GPIO
                            if 0 <= pin <= 28 and pin not in (23, 24, 25):
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p))
                                return
            except Exception as exc:
                self.root.after(0, lambda e=str(exc): _on_error(e))
                return
            if self.scanning:
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                self.root.after(0, self._restore_all_detect_btns)
                self.root.after(0, lambda: self._set_status(""))

        threading.Thread(target=_thread, daemon=True).start()

    def _stop_monitor(self):
        """Placeholder for monitor stop — implemented in Plan 03."""
        self._monitoring = False

    # ── Advanced > Flash Firmware ────────────────────────────────────

    def _flash_firmware(self, uf2=None):
        if not uf2:
            uf2 = filedialog.askopenfilename(
                title="Select UF2 Firmware File",
                filetypes=[("UF2 Firmware", "*.uf2"), ("All Files", "*.*")])
            if not uf2:
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
                            self._set_status(
                                "   Controller didn't enter config mode", ACCENT_RED),
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
                "Connect to the retro controller before exporting.")
            return
        device_name = self.device_name.get().strip() or "Retro Controller"
        date_str = datetime.datetime.now().strftime("%m-%d-%Y")
        default_name = f"{device_name} {date_str}"
        path = filedialog.asksaveasfilename(
            title="Export Retro Controller Configuration",
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
        SKIP_KEYS = {"device_type"}
        errors = []
        for key, val in cfg.items():
            if key in SKIP_KEYS:
                continue
            try:
                self.pico.set_value(key, val)
            except Exception as exc:
                errors.append(f"{key}: {exc}")
        return errors

    def _import_config(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the retro controller before importing.")
            return
        path = filedialog.askopenfilename(
            title="Import Retro Controller Configuration",
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
                "Connect to the retro controller before loading a preset.")
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
        win.title("Serial Debug Console — Retro Controller")
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
            info_lbl.config(
                text="connected" if (conn and conn.connected) else "NOT connected")

        _refresh_info()
        tk.Button(info_frame, text="↺ Refresh", bg=BG_INPUT, fg=TEXT_DIM,
                  font=(FONT_UI, 7), relief="flat", bd=0, padx=6,
                  command=_refresh_info).pack(side="right", padx=6)

        qbar = tk.Frame(win, bg=BG_MAIN)
        qbar.pack(fill="x", padx=8, pady=(6, 0))
        QUICK = [
            ("PING",       "PING",       ACCENT_BLUE),
            ("GET CONFIG", "GET_CONFIG", ACCENT_BLUE),
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
            "PING                               → PONG  (connection check)",
            "GET_CONFIG                         → DEVTYPE:pico_retro + CFG: line",
            "SET:btn0=<pin>                     → assign GPIO to D-Pad Up (-1 = disabled)",
            "SET:mode_lt=<0|1>                  → 0=digital, 1=analog for LT",
            "SET:pin_lt=<pin>                   → LT trigger GPIO pin",
            "SET:lt_min=<0-4095>                → LT analog calibration min",
            "SET:lt_max=<0-4095>                → LT analog calibration max",
            "SET:lt_ema_alpha=<0-100>           → LT EMA smoothing percent",
            "SET:lt_invert=<0|1>                → invert LT axis",
            "SET:debounce=<0-255>               → debounce time in ms",
            "SET:device_name=<name>             → custom USB device name (max 20 chars)",
            "SAVE                               → write current config to flash",
            "DEFAULTS                           → reset all config to factory defaults",
            "REBOOT                             → restart into play mode",
            "BOOTSEL                            → restart into USB mass-storage mode",
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
                            win.after(0, lambda e=str(exc):
                                      _log(f"!! Write error: {e}", TAG_ERR))
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
        _log("=== Serial Debug Console — Retro Controller ===", TAG_INFO)
        _log("Type a command below and press Enter, or use the quick buttons above.",
             TAG_INFO)
        _log("Click '▶ Command Reference' to see all available commands.", TAG_INFO)
        _log("", TAG_INFO)
        win.after(50, entry.focus_set)

    # ── Help > About ────────────────────────────────────────────────

    def _show_about(self):
        messagebox.showinfo("About",
            "OCC — Open Controller Configurator\n"
            "Guitars, Drums, Whatever you want I guess\n"
            "threepieces.nut")
