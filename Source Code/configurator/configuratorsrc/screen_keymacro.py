import sys, os, time, threading, json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .constants import (BG_MAIN, BG_CARD, BG_INPUT, BG_HOVER, BORDER, TEXT, TEXT_DIM,
                         TEXT_HEADER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
                         DIGITAL_PINS, DIGITAL_PIN_LABELS, VALID_NAME_CHARS)
from .fonts import FONT_UI, APP_VERSION
from .widgets import RoundedButton, HelpButton, HelpDialog, CustomDropdown, _help_text
from .serial_comms import PicoSerial
from .firmware_utils import (flash_uf2_with_reboot, enter_bootsel_for,
                              find_uf2_files, find_uf2_for_device_type,
                              get_bundled_fw_date_str, find_rpi_rp2_drive)
from .xinput_utils import XINPUT_AVAILABLE
from .utils import _centered_dialog, _center_window, _make_flash_popup, _find_preset_configs
class KeyMacroApp:
    """Keyboard Macro Pad configurator screen.

    Composite HID keyboard + CDC serial — always in config mode,
    no reboot needed. Save does NOT disconnect the device.
    """

    MACRO_COUNT    = 20
    MACRO_STR_LEN  = 180
    TRIGGER_LABELS = ["On Press", "On Release", "Hold (Repeat)"]

    def __init__(self, root, on_back=None):
        self.root     = root
        self._on_back = on_back
        self.root.configure(bg=BG_MAIN)

        self.pico = PicoSerial()
        self.frame = tk.Frame(root, bg=BG_MAIN)
        self._status_var = tk.StringVar(value="")
        self._debug_win  = None
        self._debug_text = None
        self._debug_reader_running = False

        self._pin_vars    = [tk.IntVar(value=-1) for _ in range(self.MACRO_COUNT)]
        self._pin_combos  = [None] * self.MACRO_COUNT
        self._mode_vars   = [tk.IntVar(value=0)  for _ in range(self.MACRO_COUNT)]
        self._mode_combos = [None] * self.MACRO_COUNT
        self._text_vars   = [tk.StringVar(value="") for _ in range(self.MACRO_COUNT)]
        self._text_entries = [None] * self.MACRO_COUNT
        self._enter_vars  = [tk.BooleanVar(value=False) for _ in range(self.MACRO_COUNT)]
        self._det_btns    = [None] * self.MACRO_COUNT
        self._all_widgets = []

        self.debounce_var = tk.IntVar(value=5)
        self.device_name  = tk.StringVar(value="Macro Pad")

        self.scanning         = False
        self.scan_target      = None
        self._scan_gen        = 0
        self._save_in_progress = False

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
        presets = _find_preset_configs({"keyboard_macro"})
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
                 text="The keyboard macro pad is always in config mode — connect any time.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(anchor="w", padx=14, pady=(0, 6))

        btn_bar = tk.Frame(conn_card, bg=BG_CARD)
        btn_bar.pack(fill="x", padx=14)

        self._connect_btn = RoundedButton(
            btn_bar, text="Connect to Controller",
            command=self._connect_clicked,
            bg_color=ACCENT_BLUE, btn_width=190, btn_height=34)
        self._connect_btn.pack(side="left", padx=(0, 8))

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

        # ── Sections ─────────────────────────────────────────────────
        self._make_device_name_section()
        self._make_macro_section()
        self._make_debounce_section()

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
            bottom, text="Save Configuration",
            command=self._save,
            bg_color=ACCENT_GREEN, btn_width=180, btn_height=34)
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

    def _make_card(self):
        card = tk.Frame(self.content, bg=BG_CARD,
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

    # ── Section: Macro Buttons ───────────────────────────────────────

    def _make_macro_section(self):
        card = self._make_card()
        inner = tk.Frame(card, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="MACRO BUTTONS", bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w")
        tk.Label(inner,
                 text="Assign a GPIO pin and keystroke string to each macro. "
                      "Wire each button between the GPIO pin and GND (active-low, internal pull-ups). "
                      "Press Detect and press the button to auto-assign the pin. "
                      "Max 180 characters per macro. "
                      "Tip: use \\n for newline or \\t for tab in your keystroke string.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), wraplength=820,
                 justify="left", anchor="w").pack(fill="x", pady=(0, 8))

        # Column headers
        hdr = tk.Frame(inner, bg=BG_CARD)
        hdr.pack(fill="x", pady=(0, 2))
        tk.Frame(hdr, width=86, bg=BG_CARD).pack(side="left")
        tk.Label(hdr, text="GPIO Pin", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), width=21, anchor="w").pack(side="left")
        tk.Frame(hdr, width=60, bg=BG_CARD).pack(side="left")
        tk.Label(hdr, text="Trigger", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), width=16, anchor="w").pack(side="left")
        tk.Label(hdr, text="Keystrokes  (max 180 chars)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7, "bold"), anchor="w").pack(side="left")

        for i in range(self.MACRO_COUNT):
            self._make_macro_row(inner, i)

    def _make_macro_row(self, parent, idx):
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=f"Macro {idx + 1}", bg=BG_CARD, fg=TEXT,
                 width=8, anchor="w",
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 8))

        tk.Label(row, text="Pin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        pin_combo = CustomDropdown(
            row, state="readonly", width=18,
            values=[DIGITAL_PIN_LABELS[p] for p in DIGITAL_PINS])
        pin_combo.current(0)  # Disabled
        pin_combo.pack(side="left", padx=(0, 4))
        pin_combo.bind("<<ComboboxSelected>>",
                       lambda _e, i=idx, c=pin_combo: self._on_pin_combo(i, c))
        self._pin_combos[idx] = pin_combo
        self._all_widgets.append(pin_combo)

        det_btn = ttk.Button(
            row, text="Detect", style="Det.TButton", width=7,
            command=lambda i=idx: self._start_detect(i))
        det_btn.pack(side="left", padx=(0, 10))
        self._det_btns[idx] = det_btn
        self._all_widgets.append(det_btn)

        tk.Label(row, text="Mode:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        mode_combo = CustomDropdown(
            row, state="readonly", width=12,
            values=self.TRIGGER_LABELS)
        mode_combo.current(0)
        mode_combo.pack(side="left", padx=(0, 10))
        mode_combo.bind("<<ComboboxSelected>>",
                        lambda _e, i=idx, c=mode_combo: self._on_mode_combo(i, c))
        self._mode_combos[idx] = mode_combo
        self._all_widgets.append(mode_combo)

        tk.Label(row, text="Keystrokes:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 4))
        _vcmd = (self.root.register(
            lambda P: len(P) <= self.MACRO_STR_LEN), '%P')
        entry = tk.Entry(
            row, textvariable=self._text_vars[idx],
            bg=BG_INPUT, fg=TEXT, insertbackground=TEXT,
            font=(FONT_UI, 9), width=38, bd=1, relief="solid",
            validate="key", validatecommand=_vcmd)
        entry.pack(side="left", padx=(0, 4))
        self._text_entries[idx] = entry
        self._all_widgets.append(entry)

        tk.Label(row, text="(180)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(0, 6))

        enter_cb = ttk.Checkbutton(
            row, text="↵ Enter",
            variable=self._enter_vars[idx])
        enter_cb.pack(side="left")
        self._all_widgets.append(enter_cb)

    def _on_pin_combo(self, idx, combo):
        self._pin_vars[idx].set(DIGITAL_PINS[combo.current()])

    def _on_mode_combo(self, idx, combo):
        self._mode_vars[idx].set(combo.current())

    # ── Section: Debounce ────────────────────────────────────────────

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

    def _load_config(self):
        """Kick off a background thread to read config, then apply to UI."""
        def _worker():
            try:
                self.pico.ser.write(b"GET_CONFIG\n")
                self.pico.ser.flush()
                lines = []
                while True:
                    raw  = self.pico.ser.readline()
                    line = raw.decode("ascii", errors="replace").strip() if raw else ""
                    if not line:
                        break
                    lines.append(line)
            except Exception as exc:
                self.root.after(0, lambda e=str(exc): messagebox.showerror(
                    "Error", f"Failed to read config: {e}"))
                return
            self.root.after(0, lambda: self._apply_config(lines))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_config(self, lines):
        """Parse config lines (from worker thread) and update UI. Runs on main thread."""
        cfg    = {}
        macros = {}
        for line in lines:
            if line.startswith("CFG:"):
                for kv in line[4:].split(","):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        cfg[k.strip()] = v.strip()
            elif line.startswith("MACRO:"):
                # MACRO:N,pin=X,mode=Y,text=Z  (text last — may contain commas)
                rest = line[6:]
                try:
                    comma    = rest.index(",")
                    slot_idx = int(rest[:comma])
                    params   = rest[comma + 1:]
                    text_pos = params.index("text=")
                    kv_part  = params[:text_pos].rstrip(",")
                    text     = params[text_pos + 5:]
                    slot     = {}
                    for kv in kv_part.split(","):
                        if "=" in kv:
                            k, v = kv.split("=", 1)
                            slot[k.strip()] = v.strip()
                    slot["text"] = text
                    macros[slot_idx] = slot
                except (ValueError, IndexError):
                    pass

        for i in range(self.MACRO_COUNT):
            m     = macros.get(i, {"pin": "-1", "mode": "0", "enter": "0", "text": ""})
            pin   = int(m.get("pin",   -1))
            mode  = int(m.get("mode",   0))
            enter = int(m.get("enter",  0)) != 0
            text  = m.get("text", "")

            self._pin_vars[i].set(pin)
            combo = self._pin_combos[i]
            if combo is not None:
                combo.current(DIGITAL_PINS.index(pin) if pin in DIGITAL_PINS else 0)
                self._pin_vars[i].set(pin)   # re-sync after .current()

            self._mode_vars[i].set(mode)
            if self._mode_combos[i] is not None:
                safe_mode = mode if 0 <= mode < len(self.TRIGGER_LABELS) else 0
                self._mode_combos[i].current(safe_mode)
                self._mode_vars[i].set(mode)

            self._text_vars[i].set(text)
            self._enter_vars[i].set(enter)

        self.debounce_var.set(int(cfg.get("debounce", 5)))
        self.device_name.set(cfg.get("device_name", "Macro Pad"))
        self._update_scroll_state()

    # ── Push all values to firmware ───────────────────────────────────

    def _push_all_values(self):
        for i in range(self.MACRO_COUNT):
            self.pico.set_value(f"macro{i}_pin",   str(self._pin_vars[i].get()))
            self.pico.set_value(f"macro{i}_mode",  str(self._mode_vars[i].get()))
            text = self._text_vars[i].get()[:self.MACRO_STR_LEN]
            self.pico.set_value(f"macro{i}_text",  text)
            self.pico.set_value(f"macro{i}_enter", "1" if self._enter_vars[i].get() else "0")
        self.pico.set_value("debounce", str(self.debounce_var.get()))
        name = ''.join(c for c in self.device_name.get()
                       if c in VALID_NAME_CHARS).strip() or "Macro Pad"
        self.pico.set_value("device_name", name[:20])

    # ── Save (no reboot) ──────────────────────────────────────────────

    def _save(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected", "Connect before saving.")
            return
        if self._save_in_progress:
            return
        self._stop_detect()
        self._save_in_progress = True
        self._set_status("   Saving...", ACCENT_ORANGE)
        try:
            self._save_btn.set_state("disabled")
        except Exception:
            pass

        def _worker():
            try:
                self._push_all_values()
                self.pico.save()
                self.root.after(0, lambda: self._set_status(
                    "   Saved. Macros are now active.", ACCENT_GREEN))
            except Exception as exc:
                self.root.after(0, lambda e=str(exc): messagebox.showerror(
                    "Save Error", e))
            finally:
                self._save_in_progress = False
                self.root.after(0, lambda: self._save_btn.set_state("normal"))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Reset to Defaults ─────────────────────────────────────────────

    def _reset_defaults(self):
        if not self.pico.connected:
            return
        if not messagebox.askyesno("Reset to Defaults",
                "Reset all macro settings to factory defaults?\n\n"
                "This will clear all pin assignments and keystroke strings."):
            return
        self._set_status("   Resetting to defaults...", ACCENT_ORANGE)

        def _worker():
            try:
                self.pico.ser.write(b"DEFAULTS\n")
                self.pico.ser.flush()
                time.sleep(0.3)
            except Exception as exc:
                self.root.after(0, lambda e=str(exc): messagebox.showerror(
                    "Reset Error", e))
                return
            self.root.after(0, lambda: [
                self._load_config(),
                self._set_status("   Reset to defaults.", ACCENT_ORANGE),
            ])

        threading.Thread(target=_worker, daemon=True).start()

    # ── Pin detection (SCAN) ─────────────────────────────────────────

    def _start_detect(self, idx):
        if not self.pico.connected:
            return
        if self.scanning:
            self._stop_detect()
            return
        self._scan_gen  += 1
        my_gen           = self._scan_gen
        self.scanning    = True
        self.scan_target = idx

        for i, btn in enumerate(self._det_btns):
            try:
                btn.config(state="disabled" if i != idx else "normal",
                           text="Stop" if i == idx else "Detect")
            except Exception:
                pass

        self._set_status(
            f"   Detecting pin for Macro {idx + 1} — press the button now...",
            ACCENT_BLUE)

        def _scan_worker():
            try:
                self.pico.start_scan()   # sends SCAN, reads OK
            except Exception:
                if self._scan_gen == my_gen:
                    self.root.after(0, self._stop_detect)
                return
            deadline = time.time() + 15.0
            while time.time() < deadline and self.scanning and self._scan_gen == my_gen:
                line = self.pico.read_scan_line(0.2)
                if line and line.startswith("PIN:"):
                    pin = int(line[4:])
                    if self._scan_gen == my_gen:
                        self.root.after(0, lambda p=pin: self._detect_result(idx, p))
                    return
            # only act if we still own the scan
            if self._scan_gen == my_gen:
                timed_out = time.time() >= deadline
                def _on_timeout(to=timed_out):
                    self._stop_detect()
                    if to:
                        self._set_status(
                            "   No input detected within timeout window.", ACCENT_ORANGE)
                self.root.after(0, _on_timeout)

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _detect_result(self, idx, pin):
        self._stop_detect()
        if pin in DIGITAL_PINS:
            combo = self._pin_combos[idx]
            if combo:
                combo.current(DIGITAL_PINS.index(pin))
            self._pin_vars[idx].set(pin)   # re-sync after .current() (doesn't fire event)
            self._set_status(f"   Detected GPIO {pin} for Macro {idx + 1}", ACCENT_GREEN)

    def _stop_detect(self):
        was_scanning     = self.scanning
        self.scanning    = False
        self.scan_target = None
        if was_scanning:
            try:
                self.pico.stop_scan()   # sends STOP, drains OK
            except Exception:
                pass
        for btn in self._det_btns:
            try:
                btn.config(state="normal", text="Detect")
            except Exception:
                pass

    # ── Status bar ────────────────────────────────────────────────────

    def _set_status(self, text, color=TEXT_DIM):
        self._status_var.set(text)
        try:
            self._status_lbl.config(fg=color)
        except Exception:
            pass

    # ── Navigation / lifecycle ───────────────────────────────────────

    def _go_back(self):
        self._stop_detect()
        if self.pico.connected:
            self._set_status("   Saving configuration...", ACCENT_ORANGE)
            try:
                self._push_all_values()
                self.pico.save()
            except Exception:
                pass
        if self._on_back:
            self.hide()
            self._on_back()

    def _on_close(self):
        self.root.destroy()

    def show(self):
        self.root.title("OCC - Keyboard Macro Pad Configurator")
        self.root.config(menu=self._menu_bar)
        self.frame.pack(fill="both", expand=True)
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def hide(self):
        """Hide screen without rebooting — device stays active as a keyboard."""
        self._scroll_canvas.unbind_all("<MouseWheel>")
        if self.pico.connected:
            self.pico.disconnect()
        self.frame.pack_forget()

    # ── Connection ────────────────────────────────────────────────────

    def _connect_clicked(self):
        if self.pico.connected:
            self._stop_detect()
            self.pico.disconnect()
            self._set_status("   Disconnected", TEXT_DIM)
            self._set_controls_enabled(False)
            self._connect_btn.set_state("normal")
            return
        port = PicoSerial.find_config_port()
        if port:
            self._connect_serial(port)
        else:
            self._set_status("   No Keyboard Macro device found.", TEXT_DIM)

    def _connect_serial(self, port):
        """Kick off background thread to connect + ping + load config."""
        self._set_status("   Connecting...", TEXT_DIM)
        try:
            self._connect_btn.set_state("disabled")
        except Exception:
            pass

        def _worker():
            try:
                self.pico.connect(port)
                for _ in range(5):
                    if self.pico.ping():
                        break
                    time.sleep(0.3)
                else:
                    self.pico.disconnect()
                    self.root.after(0, lambda: [
                        self._set_status("   Not responding", ACCENT_RED),
                        self._connect_btn.set_state("normal"),
                    ])
                    return
            except Exception as exc:
                self.root.after(0, lambda e=str(exc): [
                    self._set_status(f"   Connection failed: {e}", ACCENT_RED),
                    self._connect_btn.set_state("normal"),
                ])
                return
            self.root.after(0, lambda: [
                self._set_status(f"   Connected  —  {port}", ACCENT_GREEN),
                self._set_controls_enabled(True),
                self._load_config(),
            ])

        threading.Thread(target=_worker, daemon=True).start()

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
                        "The Pico will reboot and reconnect as the keyboard macro pad.\n"
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
                "Connect to the macro pad before exporting.")
            return
        device_name = self.device_name.get().strip() or "Macro Pad"
        date_str = datetime.datetime.now().strftime("%m-%d-%Y")
        default_name = f"{device_name} {date_str}"
        path = filedialog.asksaveasfilename(
            title="Export Macro Pad Configuration",
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            # Build config dict from current UI state using SET-compatible key names
            cfg = {}
            for i in range(self.MACRO_COUNT):
                cfg[f"macro{i}_pin"]   = str(self._pin_vars[i].get())
                cfg[f"macro{i}_mode"]  = str(self._mode_vars[i].get())
                cfg[f"macro{i}_text"]  = self._text_vars[i].get()
                cfg[f"macro{i}_enter"] = "1" if self._enter_vars[i].get() else "0"
            cfg["debounce"]    = str(self.debounce_var.get())
            cfg["device_name"] = self.device_name.get()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            messagebox.showinfo("Export Successful",
                                f"Configuration exported to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _apply_config_dict(self, cfg):
        """Push all SET-able keys from cfg to firmware. Returns list of error strings."""
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
                "Connect to the macro pad before importing.")
            return
        path = filedialog.askopenfilename(
            title="Import Macro Pad Configuration",
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
        self._load_config()   # re-read firmware state so UI fields reflect the import
        if errors:
            messagebox.showwarning("Import Partial",
                "Some keys could not be set:\n" + "\n".join(errors[:10]))
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
                "Connect to the macro pad before loading a preset.")
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as exc:
            messagebox.showerror("Preset Error", f"Could not read preset:\n{exc}")
            return

        errors = self._apply_config_dict(cfg)
        self._load_config()   # re-read firmware state so UI fields reflect the preset
        if errors:
            messagebox.showwarning("Preset Partial",
                "Some keys could not be set:\n" + "\n".join(errors[:10]))
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
        win.title("Serial Debug Console — Keyboard Macro Pad")
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
            "PING                              → PONG  (connection check)",
            "GET_CONFIG                        → DEVTYPE:keyboard_macro + CFG: + 20 MACRO: lines",
            "GET_FW_DATE                       → FW_DATE:YYYY-MM-DD",
            "SCAN                              → streams PIN:N on button press; send STOP to end",
            "STOP                              → ends SCAN mode",
            "SET:macro0_pin=<-1..28>           → assign GPIO pin to Macro 1 (-1 = disabled)",
            "SET:macro0_mode=<0-2>             → 0=On Press, 1=On Release, 2=Hold (Repeat)",
            "SET:macro0_text=<string>          → keystroke string for Macro 1 (max 180 chars)",
            "SET:debounce=<0-50>               → debounce time in ms",
            "SET:device_name=<name>            → custom USB device name (max 20 chars)",
            "SAVE                              → write current config to flash",
            "DEFAULTS                          → reset all config to factory defaults",
            "REBOOT                            → restart firmware",
            "BOOTSEL                           → restart into USB mass-storage (UF2 flash) mode",
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
        _log("=== Serial Debug Console — Keyboard Macro Pad ===", TAG_INFO)
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

