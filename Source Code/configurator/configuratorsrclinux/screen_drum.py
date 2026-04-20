import sys, os, time, threading, json, datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .constants import (BG_MAIN, BG_CARD, BG_INPUT, BG_HOVER, BORDER, TEXT, TEXT_DIM,
                         TEXT_HEADER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
                         DIGITAL_PINS, DIGITAL_PIN_LABELS, ANALOG_PINS, MAX_LEDS, LED_INPUT_NAMES,
                         LED_INPUT_LABELS, VALID_NAME_CHARS, OCC_SUBTYPES,
                         DRUM_LED_INPUT_NAMES as FW_DRUM_LED_INPUT_NAMES,
                         DRUM_LED_INPUT_LABELS as FW_DRUM_LED_INPUT_LABELS,
                         DRUM_INPUT_COLORS)
from .fonts import FONT_UI, APP_VERSION
from .widgets import (RoundedButton, HelpButton, HelpDialog, CustomDropdown,
                       SpeedSlider, LiveBarGraph, _help_text)
from .serial_comms import PicoSerial
from .firmware_utils import (flash_uf2_with_reboot, enter_bootsel_for,
                              find_uf2_files, find_uf2_for_device_type,
                              get_bundled_fw_date_str, find_rpi_rp2_drive,
                              apply_config_to_pico)
from .xinput_utils import (XINPUT_AVAILABLE, ERROR_SUCCESS, xinput_get_connected,
                           MAGIC_STEPS, xinput_send_vibration)
from .utils import (_centered_dialog, _center_window, _make_flash_popup, _find_preset_configs)
class DrumApp:
    """
    Drum Kit configurator screen.

    Currently shows a 'Coming Soon' panel while the full drum UI is built.
    The Advanced menu (Flash Firmware, BOOTSEL, Export/Import, Serial Debug)
    is fully functional.  Replace _build_ui() with real drum configuration
    widgets when ready.
    """

    def __init__(self, root, on_back=None):
        self.root = root
        self._on_back = on_back
        # Title is set in show() so it doesn't get overwritten by other screens at startup
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

        # Flash Firmware submenu — same logic as guitar App
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
        adv.add_command(label="Switch Dongle/BT Default", command=self._switch_wireless_default)
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
        presets = _find_preset_configs({"drum_kit", "drum_combined"})
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

    # ── Drum button definitions (key, label, dot-color) ─────────────
    DRUM_BUTTON_DEFS = [
        # Pads
        ("red_drum",    "Red Drum",      "#e74c3c"),
        ("yellow_drum", "Yellow Drum",   "#f1c40f"),
        ("blue_drum",   "Blue Drum",     "#3498db"),
        ("green_drum",  "Green Drum",    "#2ecc71"),
        # Cymbals
        ("yellow_cym",  "Yellow Cymbal", "#d4a017"),
        ("blue_cym",    "Blue Cymbal",   "#2980b9"),
        ("green_cym",   "Green Cymbal",  "#27ae60"),
        # Foot pedal (with cymbals group)
        ("foot_pedal",  "Foot Pedal",    "#d4944a"),
        # Navigation
        ("start",       "Start",         None),
        ("select",      "Select",        None),
        # D-Pad
        ("dpad_up",     "D-Pad Up",      None),
        ("dpad_down",   "D-Pad Down",    None),
        ("dpad_left",   "D-Pad Left",    None),
        ("dpad_right",  "D-Pad Right",   None),
    ]
    DRUM_INPUT_COUNT = 14

    # Serial keys match drum_config_serial.c SET handler names
    DRUM_KEY_MAP = {
        "red_drum":    "red_drum",
        "yellow_drum": "yellow_drum",
        "blue_drum":   "blue_drum",
        "green_drum":  "green_drum",
        "yellow_cym":  "yellow_cym",
        "blue_cym":    "blue_cym",
        "green_cym":   "green_cym",
        "foot_pedal":  "foot_pedal",
        "start":       "start",
        "select":      "select",
        "dpad_up":     "dpad_up",
        "dpad_down":   "dpad_down",
        "dpad_left":   "dpad_left",
        "dpad_right":  "dpad_right",
    }

    # LED input names parallel to drum buttons (for LED map grid)
    DRUM_LED_INPUT_NAMES = list(FW_DRUM_LED_INPUT_NAMES)
    DRUM_LED_INPUT_LABELS = list(FW_DRUM_LED_INPUT_LABELS)

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
            ])
        self._help_dialog.open()

    # ── Full UI build ────────────────────────────────────────────────

    def _switch_wireless_default(self):
        if not self.pico.connected:
            messagebox.showerror("Not Connected",
                                 "No drum controller is connected. Please connect first.")
            return

        try:
            cfg = self.pico.get_config()
        except Exception as exc:
            messagebox.showerror("Read Error",
                                 f"Could not read configuration from controller:\n{exc}")
            return

        if "wireless_default_mode" not in cfg:
            messagebox.showinfo(
                "Wireless Setting Not Available",
                "This setting is only available for wireless drum firmware.\n\n"
                "Flash Wireless Drum Controller firmware to use Dongle/BT defaults."
            )
            return

        try:
            current = int(cfg["wireless_default_mode"])
        except ValueError:
            current = 0
        if current not in (0, 1):
            current = 0

        new_val = 1 - current
        mode_name = "Bluetooth HID" if new_val == 1 else "Dongle"
        old_name = "Dongle" if new_val == 1 else "Bluetooth HID"

        if not messagebox.askyesno(
            "Switch Wireless Default",
            f"Current default:  {old_name}\n"
            f"Switch to:        {mode_name}\n\n"
            f"After saving, the drum controller will boot into {mode_name} mode\n"
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
            "Hold Start+Select for 3 seconds during wireless play to switch\n"
            "modes for the current session without changing this default."
        )

    def _build_ui(self):
        # Init drum-specific state variables
        self._drum_pin_vars   = {}   # key → tk.IntVar
        self._drum_pin_combos = {}   # key → CustomDropdown (was ttk.Combobox)
        self._drum_det_btns   = {}   # key → ttk.Button
        self._drum_all_widgets = []

        self.debounce_var        = tk.IntVar(value=5)
        self.device_name         = tk.StringVar(value="Drum Controller")

        self.led_enabled         = tk.BooleanVar(value=False)
        self.led_count           = tk.IntVar(value=0)
        self.led_base_brightness = tk.IntVar(value=5)
        self.led_colors          = [tk.StringVar(value="FFFFFF") for _ in range(MAX_LEDS)]
        self.led_maps            = [tk.IntVar(value=0) for _ in range(self.DRUM_INPUT_COUNT)]
        self.led_active_br       = [tk.IntVar(value=7) for _ in range(self.DRUM_INPUT_COUNT)]
        self.led_reactive        = tk.BooleanVar(value=True)
        self._led_maps_backup    = [0] * self.DRUM_INPUT_COUNT
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

        self._led_widgets      = []
        self._led_sub_cards    = []
        self._led_color_btns   = []
        self._led_map_cbs      = {}
        self._led_map_widgets  = []
        self._led_map_pin_lbls = {}

        self.scanning       = False
        self.scan_target    = None

        outer = self.frame
        outer.configure(bg=BG_MAIN)

        # ── Connection card ──────────────────────────────────────────
        conn_card = tk.Frame(outer, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        conn_card.pack(fill="x", pady=(8, 6), padx=12, ipady=6, ipadx=14)

        tk.Label(conn_card, text="CONNECTION", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=14, pady=(6, 0))
        tk.Label(conn_card,
                 text="Click Connect to switch the drum kit to config mode.",
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

        # ── Tab bar ──────────────────────────────────────────────────
        tab_bar = tk.Frame(outer, bg=BG_MAIN)
        tab_bar.pack(fill="x")
        _TAB_NAMES = ["Pads & Controls", "D-Pad", "Lighting"]
        self._tab_labels = []
        for _i, _name in enumerate(_TAB_NAMES):
            _lbl = tk.Label(tab_bar, text=_name, bg=BG_MAIN, fg=TEXT_DIM,
                            font=(FONT_UI, 10, "bold"), padx=18, pady=10,
                            cursor="hand2")
            _lbl.pack(side="left")
            _lbl.bind("<Button-1>", lambda e, idx=_i: self._switch_tab(idx))
            self._tab_labels.append(_lbl)
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x")

        # ── Scrollable area — one slot per tab ───────────────────────
        scroll_outer = tk.Frame(outer, bg=BG_MAIN)
        scroll_outer.pack(fill="both", expand=True)

        self._tab_slots   = []
        self._tab_widgets = []
        for _ in range(3):
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

        # Build Tab 0: Pads & Controls
        self._set_active_tab_refs(0)
        self._make_device_name_section()
        self._make_drum_pads_section()
        self._make_drum_debounce_section()

        # Build Tab 1: D-Pad
        self._set_active_tab_refs(1)
        self._make_drum_dpad_section()

        # Build Tab 2: Lighting
        self._set_active_tab_refs(2)
        self._make_drum_led_section()

        # Activate tab 0 as default
        self._active_tab = 0
        self._tab_slots[0].pack(fill="both", expand=True)
        self._set_active_tab_refs(0)
        self._scroll_enabled   = True
        self._scroll_animating = False
        self._scroll_target    = None
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

    # ── Tab management ───────────────────────────────────────────────

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
        """Direct scrollbar command — moves canvas and cancels any
        in-flight mousewheel animation so the bar always wins."""
        self._scroll_target = None
        self._scroll_canvas.yview(*args)

    def _on_mousewheel(self, event):
        """Eased mousewheel scroll — animates toward the target fraction
        so scrolling feels smooth rather than jumping by whole units."""
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

    # ── Card helpers ─────────────────────────────────────────────────

    def _make_card(self):
        card = tk.Frame(self.content, bg=BG_CARD,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 6), padx=2)
        return card

    def _make_collapsible_card(self, title, collapsed=False):
        card = tk.Frame(self.content, bg=BG_CARD,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 6), padx=2)

        header = tk.Frame(card, bg=BG_CARD, cursor="hand2")
        header.pack(fill="x", padx=12, pady=6)

        arrow_var = tk.StringVar(value="▶" if collapsed else "▼")
        arrow_lbl = tk.Label(header, textvariable=arrow_var, bg=BG_CARD,
                             fg=ACCENT_BLUE, font=(FONT_UI, 8, "bold"), width=2)
        arrow_lbl.pack(side="left")
        tk.Label(header, text=title, bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(side="left")

        body = tk.Frame(card, bg=BG_CARD)
        body_inner = tk.Frame(body, bg=BG_CARD)
        body_inner.pack(fill="x", padx=12, pady=(0, 10))

        _collapsed = [collapsed]

        def _toggle(_event=None):
            if _collapsed[0]:
                body.pack(fill="x")
                arrow_var.set("▼")
                _collapsed[0] = False
            else:
                body.pack_forget()
                arrow_var.set("▶")
                _collapsed[0] = True
            self._update_scroll_state()

        header.bind("<Button-1>", _toggle)
        arrow_lbl.bind("<Button-1>", _toggle)
        for child in header.winfo_children():
            child.bind("<Button-1>", _toggle)

        if not collapsed:
            body.pack(fill="x")

        return card, body_inner

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
        self._drum_all_widgets.append(self._name_entry)
        tk.Label(row, text="(letters, numbers, spaces only  ·  max 20 chars)",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left", padx=(8, 0))

    # ── Section: Drum Pin Mapping ─────────────────────────────────────

    def _make_drum_pads_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="PIN MAPPING", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Assign a GPIO pin to each drum pad and cymbal. "
                      "All inputs use internal pull-ups — wire each pad to connect GPIO to GND. "
                      "Press Detect and hit the pad to auto-assign.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        for key, label, dot_color in self.DRUM_BUTTON_DEFS:
            if key == "dpad_up":
                break
            if key == "foot_pedal":
                tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
                tk.Label(inner, text="FOOT PEDAL", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 4))
            elif key == "start":
                tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
                tk.Label(inner, text="START / SELECT", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 4))
            self._make_drum_pin_row(inner, key, label, dot_color)

    def _make_drum_dpad_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="D-PAD", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Assign GPIO pins to D-Pad directions.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(anchor="w", pady=(0, 8))

        dpad_keys = {"dpad_up", "dpad_down", "dpad_left", "dpad_right"}
        for key, label, dot_color in self.DRUM_BUTTON_DEFS:
            if key in dpad_keys:
                self._make_drum_pin_row(inner, key, label, dot_color)

    def _make_drum_pin_row(self, parent, key, label, dot_color):
        self._drum_pin_vars[key] = tk.IntVar(value=0)

        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=3)

        # Fixed-width dot container so all rows' Pin:/dropdown/Detect align
        dot_frame = tk.Frame(row, width=22, height=16, bg=BG_CARD)
        dot_frame.pack(side="left", padx=(0, 6))
        dot_frame.pack_propagate(False)
        if dot_color:
            is_cym = key.endswith("_cym")
            if is_cym:
                tk.Label(dot_frame, text="◎", bg=BG_CARD, fg=dot_color,
                         font=(FONT_UI, 11)).place(relx=0.5, rely=0.5, anchor="center")
            else:
                dot = tk.Canvas(dot_frame, width=16, height=16, bg=BG_CARD,
                                highlightthickness=0, bd=0)
                dot.create_oval(2, 2, 14, 14, fill=dot_color, outline=dot_color)
                dot.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(row, text=label, bg=BG_CARD, fg=TEXT,
                 width=14, anchor="w",
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 8))
        tk.Label(row, text="Pin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))

        # Drum/cymbal inputs are all digital — exclude ADC-capable pins (26-28)
        _digital_only = [p for p in DIGITAL_PINS if p not in ANALOG_PINS]
        combo = CustomDropdown(
            row, state="readonly", width=18,
            values=[DIGITAL_PIN_LABELS[p] for p in _digital_only])
        # Default pins match drum_config.c defaults; anything not listed defaults to Disabled (-1)
        _default_pins = {
            "red_drum": 0, "yellow_drum": 1, "blue_drum": 2, "green_drum": 3,
            "yellow_cym": 4, "blue_cym": 5, "green_cym": 6,
            "start": 7, "select": 8,
        }
        default_pin = _default_pins.get(key, -1)
        default_combo_idx = _digital_only.index(default_pin) if default_pin in _digital_only else 0
        combo.current(default_combo_idx)
        combo._pin_list = _digital_only  # stash so the callback can resolve idx → pin
        self._drum_pin_vars[key].set(default_pin)
        combo.pack(side="left", padx=(0, 8))
        combo.bind("<<ComboboxSelected>>",
                   lambda _e, k=key, c=combo: self._on_drum_pin_combo(k, c))
        self._drum_pin_combos[key] = combo
        self._drum_all_widgets.append(combo)

        det_btn = ttk.Button(
            row, text="Detect", style="Det.TButton", width=7,
            command=lambda k=key, n=label: self._start_drum_detect(k, n))
        det_btn.pack(side="left")
        self._drum_all_widgets.append(det_btn)
        self._drum_det_btns[key] = det_btn

    def _on_drum_pin_combo(self, key, combo):
        idx = combo.current()
        pin_list = getattr(combo, "_pin_list", DIGITAL_PINS)
        self._drum_pin_vars[key].set(pin_list[idx])

    def _start_drum_detect(self, key, name):
        if not self.pico.connected:
            return
        if self.scanning:
            self._stop_drum_detect()
            return
        self.scanning = True
        self.scan_target = key

        for k, btn in self._drum_det_btns.items():
            try:
                btn.config(state="disabled" if k != key else "normal",
                           text="Stop" if k == key else "Detect")
            except Exception:
                pass

        self._set_status(f"   Detecting pin for {name} — press the button/pad now...",
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
                        self.root.after(0, lambda p=pin: self._drum_detect_result(key, p))
                        return
            except Exception:
                pass
            self.root.after(0, self._stop_drum_detect)

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _drum_detect_result(self, key, pin):
        self._stop_drum_detect()
        combo = self._drum_pin_combos.get(key)
        pin_list = getattr(combo, "_pin_list", DIGITAL_PINS) if combo else DIGITAL_PINS
        if pin in pin_list:
            idx = pin_list.index(pin)
            self._drum_pin_vars[key].set(pin)
            if combo:
                combo.current(idx)
            self._set_status(
                f"   Detected GPIO {pin} for "
                f"{next(lbl for k, lbl, _ in self.DRUM_BUTTON_DEFS if k == key)}",
                ACCENT_GREEN)
        self._schedule_drum_pin_label_refresh()

    def _stop_drum_detect(self):
        self.scanning = False
        self.scan_target = None
        try:
            self.pico.ser.write(b"STOP\n")
            self.pico.ser.flush()
        except Exception:
            pass
        for btn in self._drum_det_btns.values():
            try:
                btn.config(state="normal", text="Detect")
            except Exception:
                pass

    # ── Section: Debounce ─────────────────────────────────────────────

    def _make_drum_debounce_section(self):
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
        self._drum_all_widgets.append(sp)
        tk.Label(row, text="ms  (0 = none, 3-5 typical)", bg=BG_CARD,
                 fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left")

    # ── Section: LED Strip (mirrors guitar App) ───────────────────────

    def _make_drum_led_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)
        tk.Label(inner, text="LED STRIP  (APA102 / SK9822 / Dotstar)",
                 bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 4))

        tk.Label(inner,
                 text="Wire SCK (CI) → GP6, MOSI (DI) → GP3. Chain LEDs in series. "
                      "VCC → VBUS (5V), GND → GND. "
                      "WARNING: GP3 and GP6 are reserved for LEDs when enabled — "
                      "do not assign pads to these pins.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 6))

        top = tk.Frame(inner, bg=BG_CARD)
        top.pack(fill="x", pady=2)

        en_cb = ttk.Checkbutton(top, text="Enable LEDs", variable=self.led_enabled,
                                 command=self._on_drum_led_toggle)
        en_cb.pack(side="left", padx=(0, 14))
        self._drum_all_widgets.append(en_cb)

        tk.Label(top, text="Count:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        cnt_wrap = tk.Frame(top, bg=BG_CARD, width=52, height=22)
        cnt_wrap.pack(side="left", padx=(0, 12))
        cnt_wrap.pack_propagate(False)
        _cvcmd = (self.root.register(lambda P: P == "" or P.isdigit()), '%P')
        cnt_sp = ttk.Spinbox(cnt_wrap, from_=1, to=MAX_LEDS, width=4,
                              textvariable=self.led_count,
                              command=self._on_drum_led_count_change,
                              validate="key", validatecommand=_cvcmd)
        cnt_sp.pack(fill="both", expand=True)
        cnt_sp.bind("<KeyRelease>", lambda _e, widget=cnt_sp: self._on_drum_led_count_live_change(widget))
        cnt_sp.bind("<Return>", lambda _e: self._on_drum_led_count_change())
        cnt_sp.bind("<FocusOut>", lambda _e: self._on_drum_led_count_change())
        self._drum_all_widgets.append(cnt_sp)
        self._led_widgets.append(cnt_sp)

        tk.Label(top, text=f"(max {MAX_LEDS})", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(0, 10))

        tk.Label(top, text="Base brightness:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        br_wrap = tk.Frame(top, bg=BG_CARD, width=52, height=22)
        br_wrap.pack(side="left")
        br_wrap.pack_propagate(False)
        _bvcmd = (self.root.register(lambda P: P == "" or (P.isdigit() and 0 <= int(P) <= 9)), '%P')
        br_sp = ttk.Spinbox(br_wrap, from_=0, to=9, width=4,
                             textvariable=self.led_base_brightness,
                             validate="key", validatecommand=_bvcmd)
        br_sp.pack(fill="both", expand=True)
        self._drum_all_widgets.append(br_sp)
        self._led_widgets.append(br_sp)
        tk.Label(top, text="(0=off, 9=max)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(4, 0))

        self._led_colors_frame = tk.Frame(inner, bg=BG_CARD)
        self._led_colors_frame.pack(fill="x", pady=(6, 0))
        self._led_widgets.append(self._led_colors_frame)
        self._rebuild_drum_led_color_grid()

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
        self._drum_all_widgets.append(loop_cb)

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
        self._drum_all_widgets.append(loop_start_sp)
        tk.Label(loop_range_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        loop_end_wrap = tk.Frame(loop_range_row, bg=BG_CARD, width=52, height=22)
        loop_end_wrap.pack(side="left")
        loop_end_wrap.pack_propagate(False)
        loop_end_sp = ttk.Spinbox(loop_end_wrap, from_=1, to=MAX_LEDS, width=4,
                                   textvariable=self.led_loop_end)
        loop_end_sp.pack(fill="both", expand=True)
        self._drum_all_widgets.append(loop_end_sp)

        tk.Label(lc_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        loop_speed_sl = SpeedSlider(lc_right, self.led_loop_speed,
                                    notch_ms=[9999, 5000, 3000, 1000, 100])
        loop_speed_sl.pack()
        self._drum_all_widgets.append(loop_speed_sl)
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
        self._drum_all_widgets.append(breathe_cb)

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
        self._drum_all_widgets.append(breathe_start_sp)
        tk.Label(breathe_range_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_end_wrap = tk.Frame(breathe_range_row, bg=BG_CARD, width=52, height=22)
        breathe_end_wrap.pack(side="left")
        breathe_end_wrap.pack_propagate(False)
        breathe_end_sp = ttk.Spinbox(breathe_end_wrap, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_breathe_end)
        breathe_end_sp.pack(fill="both", expand=True)
        self._drum_all_widgets.append(breathe_end_sp)

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
        self._drum_all_widgets.append(breathe_min_sp)
        tk.Label(breathe_bright_row, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_max_wrap = tk.Frame(breathe_bright_row, bg=BG_CARD, width=52, height=22)
        breathe_max_wrap.pack(side="left")
        breathe_max_wrap.pack_propagate(False)
        breathe_max_sp = ttk.Spinbox(breathe_max_wrap, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_max,
                                     validate="key", validatecommand=_bvcmd)
        breathe_max_sp.pack(fill="both", expand=True)
        self._drum_all_widgets.append(breathe_max_sp)

        tk.Label(br_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        breathe_speed_sl = SpeedSlider(br_right, self.led_breathe_speed,
                                       notch_ms=[9999, 5000, 3000, 1000, 100])
        breathe_speed_sl.pack()
        self._drum_all_widgets.append(breathe_speed_sl)
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
        self._drum_all_widgets.append(wave_cb)

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
        self._drum_all_widgets.append(wave_origin_sp)

        tk.Label(wv_right, text="Effect Speed", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7), anchor="center").pack(pady=(4, 1))
        wave_speed_sl = SpeedSlider(wv_right, self.led_wave_speed,
                                    notch_ms=[9999, 2500, 800, 250, 100])
        wave_speed_sl.pack()
        self._drum_all_widgets.append(wave_speed_sl)
        # ── end LED Ripple sub-card ────────────────────────────────────────

        # ── Reactive LED sub-card ──────────────────────────────────────────
        react_card, react_body = self._make_sub_collapsible(
            inner, "REACTIVE LED ON KEYPRESS", collapsed=False)
        self._led_sub_cards.append(react_card)

        react_row = tk.Frame(react_body, bg=BG_CARD)
        react_row.pack(fill="x", pady=(0, 4))
        react_cb = ttk.Checkbutton(react_row, text="Reactive LEDs on keypress",
                                    variable=self.led_reactive,
                                    command=self._on_drum_reactive_toggle)
        react_cb.pack(side="left", padx=(0, 10))
        self._drum_all_widgets.append(react_cb)
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
        self._rebuild_drum_led_map_grid()
        # ── end Reactive LED sub-card ──────────────────────────────────────

        self._on_drum_led_toggle()

    def _on_drum_led_toggle(self):
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
            self._rebuild_drum_led_color_grid()
            self._rebuild_drum_led_map_grid()
            self._on_drum_reactive_toggle()

    def _on_drum_reactive_toggle(self):
        reactive = self.led_reactive.get()
        if not reactive:
            for i in range(self.DRUM_INPUT_COUNT):
                cur = self.led_maps[i].get()
                if cur != 0:
                    self._led_maps_backup[i] = cur
                self.led_maps[i].set(0)
        else:
            for i in range(self.DRUM_INPUT_COUNT):
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
            self._rebuild_drum_led_map_grid()

    def _on_drum_led_count_change(self):
        count = self.led_count.get()
        if count > MAX_LEDS:
            self.led_count.set(MAX_LEDS)
        elif count < 1:
            self.led_count.set(1)
        self._rebuild_drum_led_color_grid()
        if self.led_reactive.get():
            self._rebuild_drum_led_map_grid()

    def _on_drum_led_count_live_change(self, widget):
        raw = widget.get().strip()
        if not raw:
            return
        try:
            self.led_count.set(int(raw))
        except (ValueError, tk.TclError):
            return
        self._on_drum_led_count_change()

    def _rebuild_drum_led_color_grid(self):
        for w in self._led_colors_frame.winfo_children():
            w.destroy()
        self._led_color_btns = []

        count = self.led_count.get()
        if count < 1:
            return

        tk.Label(self._led_colors_frame,
                 text="LED Colors  (click swatch to change, Identify flashes the physical LED):",
                 bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 3))

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
            swatch.create_rectangle(2, 2, 20, 20,
                                     fill=display_color, outline=display_color, tags="fill")
            swatch.pack(side="left", padx=(2, 4))
            swatch.bind("<Button-1>", lambda e, idx=i: self._pick_drum_led_color(idx))
            self._led_color_btns.append(swatch)

            id_btn = ttk.Button(cell, text="Identify", style="Det.TButton", width=7,
                                 command=lambda idx=i: self._identify_drum_led(idx))
            id_btn.pack(side="left")
            self._drum_all_widgets.append(id_btn)

    def _identify_drum_led(self, led_idx):
        if not self.pico.connected:
            return
        try:
            self.pico.led_flash(led_idx)
        except Exception as exc:
            messagebox.showerror("LED Flash", str(exc))

    def _pick_drum_led_color(self, led_idx):
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

        preview = tk.Canvas(f, width=80, height=50, bg=BG_CARD,
                            highlightthickness=1, highlightbackground=BORDER, bd=0)
        preview.create_rectangle(2, 2, 78, 48, fill=f"#{cur_hex}",
                                  outline=f"#{cur_hex}", tags="fill")
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

        PRESET_COLORS = [
            ("Green",  "00FF00"), ("Red",    "FF0000"), ("Yellow", "FFFF00"),
            ("Blue",   "0000FF"), ("Orange", "FF4600"), ("Purple", "FF00FF"),
            ("Cyan",   "00FFFF"), ("White",  "FFFFFF"),
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
            rc2, gc2, bc2 = int(hex_rgb[0:2], 16), int(hex_rgb[2:4], 16), int(hex_rgb[4:6], 16)
            lum = 0.2126 * rc2 + 0.7152 * gc2 + 0.0722 * bc2
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

        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))

        for label_text, var, accent in [("Red", r_var, "#e74c3c"),
                                         ("Green", g_var, "#2ecc71"),
                                         ("Blue", b_var, "#3498db")]:
            row2 = tk.Frame(f, bg=BG_CARD)
            row2.pack(fill="x", pady=2)
            tk.Label(row2, text=label_text, bg=BG_CARD, fg=accent,
                     width=6, font=(FONT_UI, 8, "bold"), anchor="w").pack(side="left")
            scale = tk.Scale(row2, from_=0, to=255, orient="horizontal", variable=var,
                             bg=BG_CARD, fg=TEXT, troughcolor=accent,
                             highlightthickness=0, bd=2, sliderrelief="raised",
                             relief="flat", activebackground=BG_INPUT, length=180,
                             showvalue=False, command=lambda _v: update_preview())
            scale.pack(side="left", padx=(4, 4))
            tk.Label(row2, textvariable=var, bg=BG_CARD, fg=TEXT,
                     font=("Consolas", 9), width=4).pack(side="left")

        def apply():
            rv = max(0, min(255, r_var.get()))
            gv = max(0, min(255, g_var.get()))
            bv = max(0, min(255, b_var.get()))
            self.led_colors[led_idx].set(f"{rv:02X}{gv:02X}{bv:02X}")
            self._rebuild_drum_led_color_grid()
            if self.led_reactive.get():
                self._rebuild_drum_led_map_grid()
            dlg.destroy()

        btn_row2 = tk.Frame(f, bg=BG_CARD)
        btn_row2.pack(pady=(10, 0))
        RoundedButton(btn_row2, text="Apply", command=apply,
                      bg_color=ACCENT_BLUE, btn_width=80, btn_height=28,
                      btn_font=(FONT_UI, 8, "bold")).pack(side="left", padx=(0, 8))
        RoundedButton(btn_row2, text="Cancel", command=dlg.destroy,
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

    def _rebuild_drum_led_map_grid(self):
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
        for inp_idx in range(self.DRUM_INPUT_COUNT):
            grid_row = inp_idx + 1
            key = self.DRUM_LED_INPUT_NAMES[inp_idx]
            lbl_text = self.DRUM_LED_INPUT_LABELS[inp_idx]
            dot_color = DRUM_INPUT_COLORS.get(key)

            name_frame = tk.Frame(grid, bg=BG_CARD)
            name_frame.grid(row=grid_row, column=0, sticky="w", padx=(0, 2), pady=1)

            if dot_color:
                is_cym = key.endswith("_cym")
                if is_cym:
                    tk.Label(name_frame, text="◎", bg=BG_CARD, fg=dot_color,
                             font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
                else:
                    dot = tk.Canvas(name_frame, width=10, height=10, bg=BG_CARD,
                                    highlightthickness=0, bd=0)
                    dot.create_oval(1, 1, 9, 9, fill=dot_color, outline=dot_color)
                    dot.pack(side="left", padx=(0, 2))

            tk.Label(name_frame, text=lbl_text, bg=BG_CARD, fg=TEXT,
                     font=(FONT_UI, 7), anchor="w").pack(side="left")

            pin_val = self._drum_pin_vars.get(key)
            pin_text = str(pin_val.get()) if pin_val else "—"
            pin_lbl = tk.Label(grid, text=pin_text, bg=BG_INPUT, fg=TEXT_DIM,
                               font=("Consolas", 7), width=4, anchor="center",
                               relief="flat", bd=0)
            pin_lbl.grid(row=grid_row, column=1, padx=(0, 4), pady=1)
            self._led_map_pin_lbls[inp_idx] = pin_lbl

            cb_vars = []
            current_mask = self.led_maps[inp_idx].get()
            for j in range(min(count, MAX_LEDS)):
                var = tk.BooleanVar(value=bool(current_mask & (1 << j)))
                cb = ttk.Checkbutton(grid, variable=var,
                                      command=lambda i=inp_idx: self._update_drum_led_map(i))
                cb.grid(row=grid_row, column=led_col_start + j, padx=0, pady=1)
                self._drum_all_widgets.append(cb)
                cb_vars.append(var)
            self._led_map_cbs[inp_idx] = cb_vars

            br_sp = ttk.Spinbox(grid, from_=0, to=9, width=3,
                                 textvariable=self.led_active_br[inp_idx],
                                 validate="key", validatecommand=_bvcmd)
            br_sp.grid(row=grid_row, column=bright_col, padx=(6, 0), pady=1)
            self._drum_all_widgets.append(br_sp)

        self._schedule_drum_pin_label_refresh()

    def _update_drum_led_map(self, inp_idx):
        if inp_idx not in self._led_map_cbs:
            return
        mask = 0
        for j, var in enumerate(self._led_map_cbs[inp_idx]):
            if var.get():
                mask |= (1 << j)
        self.led_maps[inp_idx].set(mask)

    def _schedule_drum_pin_label_refresh(self):
        if not hasattr(self, '_led_map_pin_lbls') or not self._led_map_pin_lbls:
            return
        if not self.led_enabled.get() or not self.led_reactive.get():
            return
        for inp_idx, lbl in self._led_map_pin_lbls.items():
            try:
                if lbl.winfo_exists():
                    key = self.DRUM_BUTTON_DEFS[inp_idx][0]
                    pin_val = self._drum_pin_vars.get(key)
                    new_text = str(pin_val.get()) if pin_val else "—"
                    lbl.config(text=new_text)
            except tk.TclError:
                pass
        self.root.after(500, self._schedule_drum_pin_label_refresh)

    # ── Enable/disable all controls ───────────────────────────────────

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for w in self._drum_all_widgets:
            try:
                w.config(state=state)
            except Exception:
                pass
        try:
            self._defaults_btn.set_state(state)
            self._save_btn.set_state(state)
        except Exception:
            pass

    # ── Connect / Disconnect ──────────────────────────────────────────

    def _connect_clicked(self):
        """Manual connect via XInput magic or scan for config port."""
        if self.pico.connected:
            self.pico.reboot()
            self.pico.disconnect()
            self._set_status("   Disconnected", TEXT_DIM)
            self._set_controls_enabled(False)
            self._connect_btn.set_state("normal")
            return
        # Try to find a config-mode port first
        port = PicoSerial.find_config_port()
        if port:
            self._connect_serial(port)
        else:
            self._connect_xinput()

    # ── Config load ───────────────────────────────────────────────────

    def _load_config(self):
        try:
            cfg = self.pico.get_config()
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read config: {exc}")
            return
        self._last_raw_cfg = cfg

        device_type = cfg.get("device_type", "drum_kit")
        if device_type == "drum_combined" and self.pico.connected:
            self._set_status(f"   Wireless Drum Kit  —  {self.pico.ser.port}", ACCENT_GREEN)

        # Load drum pin assignments
        for key, _, _ in self.DRUM_BUTTON_DEFS:
            serial_key = self.DRUM_KEY_MAP.get(key, key)
            if serial_key in cfg:
                pin = int(cfg[serial_key])
                self._drum_pin_vars[key].set(pin)
                combo = self._drum_pin_combos.get(key)
                if combo:
                    pin_list = getattr(combo, "_pin_list", DIGITAL_PINS)
                    if pin in pin_list:
                        combo.current(pin_list.index(pin))

        if "debounce" in cfg:
            self.debounce_var.set(int(cfg["debounce"]))

        if "device_name" in cfg:
            self.device_name.set(cfg["device_name"])

        # LED config
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
                if name in self.DRUM_LED_INPUT_NAMES:
                    idx = self.DRUM_LED_INPUT_NAMES.index(name)
                    if ":" in rest:
                        hex_mask, bright = rest.split(":", 1)
                        self.led_maps[idx].set(int(hex_mask, 16))
                        self.led_active_br[idx].set(
                            self._brightness_from_hw(int(bright)))

        any_mapped = any(self.led_maps[i].get() != 0
                         for i in range(self.DRUM_INPUT_COUNT))
        self.led_reactive.set(any_mapped)
        for i in range(self.DRUM_INPUT_COUNT):
            self._led_maps_backup[i] = self.led_maps[i].get()

        self._on_drum_led_toggle()
        if self.led_enabled.get():
            self._rebuild_drum_led_color_grid()
            if self.led_reactive.get():
                self._rebuild_drum_led_map_grid()

    # ── Push all values to firmware ───────────────────────────────────

    def _push_all_values(self):
        for key, _, _ in self.DRUM_BUTTON_DEFS:
            serial_key = self.DRUM_KEY_MAP.get(key, key)
            pin = self._drum_pin_vars[key].get()
            self.pico.set_value(serial_key, str(pin))

        self.pico.set_value("debounce", str(self.debounce_var.get()))

        name = ''.join(c for c in self.device_name.get() if c in VALID_NAME_CHARS).strip() or "Drum Controller"
        self.pico.set_value("device_name", name[:20])

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

        for i in range(self.DRUM_INPUT_COUNT):
            self.pico.set_value(f"led_map_{i}", f"{self.led_maps[i].get():04X}")
            self.pico.set_value(f"led_active_{i}",
                                str(self._brightness_to_hw(self.led_active_br[i].get())))

        self.pico.set_value("led_loop_enabled",
                            "1" if self.led_loop_enabled.get() else "0")
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

    # ── Save & Play Mode ──────────────────────────────────────────────

    def _save_and_reboot(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the drum kit before saving.")
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

    # ── Reset to Defaults ─────────────────────────────────────────────

    def _reset_defaults(self):
        if not self.pico.connected:
            return
        if not messagebox.askyesno("Reset to Defaults",
                "Reset all drum kit settings to factory defaults?\n\n"
                "This will overwrite pin assignments and LED config."):
            return
        try:
            self.pico.ser.write(b"DEFAULTS\n")
            self.pico.ser.flush()
            time.sleep(0.3)
            self._load_config()
            self._set_status("   Reset to defaults.", ACCENT_ORANGE)
        except Exception as exc:
            messagebox.showerror("Reset Error", str(exc))

    # ── Brightness helpers (same table as guitar App) ─────────────────

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


    # ── Navigation / lifecycle ──────────────────────────────────────

    def _reboot_to_play(self):
        """Send REBOOT command then go back to main menu."""
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
        self._go_back()

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
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
        self.root.destroy()

    def show(self):
        self.root.title("OCC - Drum Kit Configurator")
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

    # ── Connection entry points (called by go_to_configurator) ──────

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
        self._set_status("   Scanning for play-mode controllers...", ACCENT_BLUE)
        controllers = xinput_get_connected() if XINPUT_AVAILABLE else []
        if not controllers:
            self._set_status("   No controllers found", ACCENT_RED)
            messagebox.showwarning("No Controllers",
                "No supported play-mode controllers detected.\n"
                "Make sure the drum kit is plugged in and recognised by the system.")
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
                "The drum kit didn't switch to config mode.\n"
                "Close any games or apps using the controller and retry.\n\n"
                "If this is a wireless drum connected through an OCC dongle, "
                "plug the drum controller directly into USB and try Connect again.")

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
        """One-click firmware flash. Detects device state automatically and
        handles the full sequence: XInput magic → config mode → BOOTSEL → flash."""
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
                        self._connect_btn.set_state("normal"),
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

    # ── Advanced > Enter BOOTSEL Mode ───────────────────────────────

    def _enter_bootsel(self):
        enter_bootsel_for(self)

    # ── Advanced > Export / Import Configuration ────────────────────
    # Drum config is simpler than guitar — we export/import via raw
    # GET_CONFIG key-value pairs rather than guitar-specific UI vars.

    def _export_config(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the drum kit before exporting.")
            return
        device_name = self.device_name.get().strip() or "Drum Controller"
        date_str = datetime.datetime.now().strftime("%m-%d-%Y")
        default_name = f"{device_name} {date_str}"
        path = filedialog.asksaveasfilename(
            title="Export Drum Configuration",
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
        return apply_config_to_pico(self.pico, cfg, led_input_names=self.DRUM_LED_INPUT_NAMES)

    def _import_config(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the drum kit before importing.")
            return
        path = filedialog.askopenfilename(
            title="Import Drum Configuration",
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
                "Connect to the drum kit before loading a preset.")
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
        win.title("Serial Debug Console — Drum Kit")
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
            conn = getattr(self, 'pico', None)
            parts.append("connected" if (conn and conn.connected) else "NOT connected")
            info_lbl.config(text="   |   ".join(parts))

        _refresh_info()
        tk.Button(info_frame, text="↺ Refresh", bg=BG_INPUT, fg=TEXT_DIM,
                  font=(FONT_UI, 7), relief="flat", bd=0, padx=6,
                  command=_refresh_info).pack(side="right", padx=6)

        # Quick-command bar
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
            "MONITOR_ADC:<pin>            → streams MVAL:<val> for GP26/27/28; send STOP to end",
            "MONITOR_DIG:<pin>            → streams MVAL:0 or MVAL:4095; send STOP to end",
            "SET:<key>=<value>            → set one config value, replies OK or ERR:reason",
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

        # Output pane
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

        # Send row
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

        # Reader thread
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
        _log("=== Serial Debug Console — Drum Kit ===", TAG_INFO)
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
