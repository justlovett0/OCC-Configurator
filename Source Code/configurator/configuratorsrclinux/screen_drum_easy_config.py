import datetime
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .constants import (
    BG_CARD, BG_INPUT, BORDER, TEXT, TEXT_DIM, TEXT_HEADER,
    ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
    DIGITAL_PINS, MAX_LEDS, VALID_NAME_CHARS,
    DRUM_LED_INPUT_NAMES, DRUM_LED_INPUT_LABELS, DRUM_INPUT_COLORS,
)
from .fonts import FONT_UI
from .widgets import RoundedButton, HelpDialog, _help_text
from .screen_easy_config import EasyConfigScreen
from .utils import _center_window


_DRUM_INPUTS = [
    ("red_drum", "Red Drum", "#e74c3c", "Drum Pad"),
    ("yellow_drum", "Yellow Drum", "#f1c40f", "Drum Pad"),
    ("blue_drum", "Blue Drum", "#3498db", "Drum Pad"),
    ("green_drum", "Green Drum", "#2ecc71", "Drum Pad"),
    ("yellow_cym", "Yellow Cymbal", "#d4a017", "Cymbal"),
    ("blue_cym", "Blue Cymbal", "#2980b9", "Cymbal"),
    ("green_cym", "Green Cymbal", "#27ae60", "Cymbal"),
    ("foot_pedal", "Foot Pedal", "#d4944a", "Pedal"),
    ("start", "Start", None, "Navigation"),
    ("select", "Select", None, "Navigation"),
]
_DRUM_DPAD_INPUTS = [
    ("dpad_up", "D-Pad Up"),
    ("dpad_down", "D-Pad Down"),
    ("dpad_left", "D-Pad Left"),
    ("dpad_right", "D-Pad Right"),
]
_DRUM_PAGE_DEFS = [
    *[("digital", key, label, color or ACCENT_BLUE, category)
      for key, label, color, category in _DRUM_INPUTS],
    ("dpad", None, "D-Pad", ACCENT_BLUE, "Navigation"),
    ("led", None, "LED Configuration", ACCENT_BLUE, "LED Setup"),
    ("placeholder", None, "Review & Save", ACCENT_BLUE, "Finishing Up"),
]
_DRUM_LABELS = {
    **{key: label for key, label, _color, _category in _DRUM_INPUTS},
    **{key: label for key, label in _DRUM_DPAD_INPUTS},
}
_DRUM_PIN_PAGE = {
    **{key: idx for idx, (_ptype, key, _name, _accent, _category) in enumerate(_DRUM_PAGE_DEFS)
       if key is not None},
    **{key: 10 for key, _label in _DRUM_DPAD_INPUTS},
}


class DrumEasyConfigScreen(EasyConfigScreen):
    """Step-by-step easy configurator for the wired drum firmware."""

    DRUM_INPUTS = _DRUM_INPUTS
    DPAD_INPUTS = _DRUM_DPAD_INPUTS
    PAGE_DEFS = _DRUM_PAGE_DEFS
    _PIN_KEY_TO_LABEL = _DRUM_LABELS
    _PIN_KEY_TO_PAGE = _DRUM_PIN_PAGE
    _PIN_ASSIGNMENT_KEYS = tuple(_DRUM_LABELS.keys())
    _REQUIRED_PAGES = set()
    DRUM_DEFAULT_COLORS = [
        "FF0000", "FF8000", "0000FF", "00FF00",
        "FF8000", "0000FF", "00FF00",
        "FFFFFF", "FFFFFF",
        "FFFFFF", "FFFFFF", "FFFFFF", "FFFFFF",
        "FF5000", "FFFFFF", "FFFFFF",
    ]
    LED_SPI_PINS = {3, 6}

    @staticmethod
    def _brightness_to_hw(user_val):
        user_val = max(0, min(9, int(user_val)))
        return [0, 1, 2, 3, 5, 7, 11, 16, 23, 31][user_val]

    def _open_help(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self.root, [
                ("Overview", _help_text(
                    ("This is the easy configurator for drum controllers.", None),
                    ("It walks through every pad, cymbal, foot pedal, navigation button, and D-Pad direction.", None),
                    ("\n\n", None),
                    ("Every control can be skipped. Skipped controls are saved as Disabled.", None),
                )),
                ("Detection", _help_text(
                    ("Press the large detection box, then press the requested drum control.", None),
                    ("If detection times out, click the detection box again and re-press the control.", None),
                    ("\n\n", None),
                    ("If LEDs are enabled, GP3 and GP6 are reserved for the LED strip.", None),
                )),
                ("LEDs", _help_text(
                    ("Drum LEDs use APA102 / SK9822 / Dotstar wiring: MOSI to GP3 and SCK to GP6.", None),
                    ("Reactive LED rows follow the firmware input order so each drum control lights the intended LEDs.", None),
                )),
                ("Review & Save", _help_text(
                    ("The review page shows a live preview of mapped drum inputs before saving.", None),
                    ("Finish saves the configuration, reboots the controller to play mode, and returns to the menu.", None),
                )),
            ])
        self._help_dialog.open()

    def _show_page(self, idx):
        self._stop_scan_and_monitor(reset_detection_ui=True)
        self._current_page = idx
        self._page_token += 1
        self._page_detection_reset = None
        for widget in self._body_frame.winfo_children():
            widget.destroy()

        ptype, key, name, accent, category = self.PAGE_DEFS[idx]
        total = len(self.PAGE_DEFS)
        self._page_title_lbl.config(text=name)
        self._page_sub_lbl.config(text=f"{category}  -  Page {idx + 1} of {total}")
        self._progress_canvas.update_idletasks()
        bar_w = self._progress_canvas.winfo_width() or 1060
        fill_w = max(8, int(bar_w * ((idx + 1) / total)))
        self._progress_canvas.delete("all")
        self._progress_canvas.create_rectangle(0, 0, bar_w, 8, fill=BG_INPUT, outline="")
        self._progress_canvas.create_rectangle(0, 0, fill_w, 8, fill=ACCENT_BLUE, outline="")
        self._prog_label.config(text=f"Step {idx + 1} of {total}")

        if getattr(self, "_strum_anim", None):
            self._strum_anim.stop()
            self._strum_anim = None
        self._strum_canvas.delete("all")
        self._skip_btn._label = "Finish & Return to Menu" if idx == total - 1 else "Skip to next screen ->"
        self._skip_btn._render(self._skip_btn._bg)
        self._prev_btn.set_state("disabled" if idx == 0 else "normal")

        if ptype == "digital":
            self._build_digital_content(key, name, accent)
        elif ptype == "dpad":
            self._build_dpad_content()
        elif ptype == "led":
            self._build_led_content()
        else:
            self._build_placeholder_content(name)

    def _build_digital_content(self, key, name, accent):
        f = self._body_frame
        page_token = self._page_token
        idle_text = "Click Here to Start Input Detection"

        top = tk.Frame(f, bg=BG_CARD)
        top.pack(anchor="w", pady=(0, 4))
        color = DRUM_INPUT_COLORS.get(key)
        if color:
            dot = tk.Canvas(top, width=18, height=18, bg=BG_CARD, highlightthickness=0, bd=0)
            if key.endswith("_cym"):
                dot.create_oval(2, 2, 16, 16, outline=color, width=3)
            else:
                dot.create_oval(2, 2, 16, 16, fill=color, outline=color)
            dot.pack(side="left", padx=(0, 8))
        tk.Label(top, text=f"Press and release {name} on your drum controller.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(side="left")
        tk.Label(f,
                 text="Detection listens for GPIO input changes. Make sure no other controls are pressed.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(0, 14))

        _sf, status_lbl, gpio_lbl = self._make_status_box(f, idle_text=idle_text)

        def _restore_idle():
            if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                return
            self._clear_scan_timeout()
            detect_btn.set_state("normal")
            cancel_btn.set_state("disabled")
            status_lbl.config(text=idle_text, fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

        if key in self.detected:
            pin = self.detected.get(key, -1)
            if pin == -1:
                status_lbl.config(text="Previously set to Disabled.", fg=ACCENT_ORANGE)
                gpio_lbl.config(text="Disabled")
            else:
                status_lbl.config(text=f"Previously set to GPIO {pin}.", fg=ACCENT_GREEN)
                gpio_lbl.config(text=f"GPIO {pin}")

        detect_btn, cancel_btn = self._make_detect_cancel_row(f, accent)
        self._page_detection_reset = _restore_idle

        def start_detect():
            if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                return
            if not self.pico.connected:
                status_lbl.config(text="Not connected to controller.", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                return
            self._clear_scan_timeout()
            self.scanning = True
            self.scan_target = key
            detect_btn.set_state("disabled")
            cancel_btn.set_state("normal")
            status_lbl.config(text=f"Waiting for {name}. Press it now.", fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

            def _on_detected(pin):
                if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                    return

                def _commit():
                    self.detected[key] = pin
                    self.scanning = False
                    self._clear_scan_timeout()
                    detect_btn.set_state("normal")
                    cancel_btn.set_state("disabled")
                    status_lbl.config(text="Detection successful. Ready for next step.", fg=ACCENT_GREEN)
                    gpio_lbl.config(text=f"GPIO {pin}")
                self._handle_detected_pin(key, pin, _commit, _restore_idle)

            def _on_error(msg):
                if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                    return
                self.scanning = False
                self._clear_scan_timeout()
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text=f"Scan error: {msg}", fg=ACCENT_RED)

            def _on_timeout():
                if not self._page_is_active(page_token, status_lbl, gpio_lbl) or not self.scanning:
                    return
                self.scanning = False
                self._request_stop_scan()
                self._clear_scan_timeout()
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text="No button press detected. Click here to restart detection.", fg=ACCENT_ORANGE)
                gpio_lbl.config(text="")

            def _thread():
                try:
                    self.pico.start_scan()
                    while self.scanning:
                        line = self.pico.read_scan_line(0.1)
                        if line and line.startswith("PIN:"):
                            try:
                                pin = int(line[4:])
                            except ValueError:
                                continue
                            if pin in DIGITAL_PINS and pin != -1:
                                self._request_stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p))
                                return
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): _on_error(e))

            def _cancel():
                if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                    return
                self.scanning = False
                self._request_stop_scan()
                _restore_idle()

            cancel_btn._command = _cancel
            cancel_btn._render(cancel_btn._bg)
            self._start_scan_timeout(_on_timeout, timeout_ms=10000)
            threading.Thread(target=_thread, daemon=True).start()

        detect_btn._command = start_detect
        detect_btn._render(detect_btn._bg)
        if key not in self.detected:
            self._schedule_auto_detect(start_detect, delay_ms=75)

    def _build_dpad_content(self):
        f = self._body_frame
        tk.Label(f, text="Map each D-Pad direction, or leave directions disabled.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(anchor="w", pady=(0, 4))
        tk.Label(f, text="Click a direction box to detect it. Any skipped direction remains disabled.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(0, 14))

        grid = tk.Frame(f, bg=BG_CARD)
        grid.pack(fill="x")
        directions = [
            ("dpad_up", "D-Pad Up"),
            ("dpad_right", "D-Pad Right"),
            ("dpad_down", "D-Pad Down"),
            ("dpad_left", "D-Pad Left"),
        ]
        for col in range(2):
            grid.columnconfigure(col, weight=1)

        for idx, (key, label) in enumerate(directions):
            cell = tk.Frame(grid, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
            col = idx % 2
            row = idx // 2
            cell.grid(row=row, column=col,
                      padx=(0, 10) if col == 0 else 0,
                      pady=(0, 10), sticky="nsew")
            inner = tk.Frame(cell, bg=BG_CARD)
            inner.pack(fill="both", expand=True, padx=12, pady=10)
            tk.Label(inner, text=label, bg=BG_CARD, fg=TEXT_HEADER,
                     font=(FONT_UI, 11, "bold")).pack(anchor="w", pady=(0, 8))
            self._build_dpad_cell(inner, key, label)

    def _build_dpad_cell(self, parent, key, label):
        page_token = self._page_token
        idle_text = "Click Here to Detect"
        _sf, status_lbl, gpio_lbl = self._make_status_box(parent, idle_text=idle_text)
        detect_btn, cancel_btn = self._make_detect_cancel_row(parent, ACCENT_BLUE)

        def _restore_idle():
            if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                return
            self._clear_scan_timeout()
            detect_btn.set_state("normal")
            cancel_btn.set_state("disabled")
            status_lbl.config(text=idle_text, fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

        if key in self.detected:
            pin = self.detected.get(key, -1)
            status_lbl.config(text="Disabled." if pin == -1 else f"GPIO {pin}.",
                              fg=ACCENT_ORANGE if pin == -1 else ACCENT_GREEN)
            gpio_lbl.config(text="Disabled" if pin == -1 else f"GPIO {pin}")

        def start_detect():
            if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                return
            if not self.pico.connected:
                status_lbl.config(text="Not connected.", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                return
            self._clear_scan_timeout()
            self.scanning = True
            self.scan_target = key
            detect_btn.set_state("disabled")
            cancel_btn.set_state("normal")
            status_lbl.config(text=f"Waiting for {label}.", fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

            def _finish(pin):
                if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                    return

                def _commit():
                    self.detected[key] = pin
                    self.scanning = False
                    self._clear_scan_timeout()
                    detect_btn.set_state("normal")
                    cancel_btn.set_state("disabled")
                    status_lbl.config(text="Detection successful.", fg=ACCENT_GREEN)
                    gpio_lbl.config(text=f"GPIO {pin}")
                self._handle_detected_pin(key, pin, _commit, _restore_idle)

            def _timeout():
                if not self._page_is_active(page_token, status_lbl, gpio_lbl) or not self.scanning:
                    return
                self.scanning = False
                self._request_stop_scan()
                self._clear_scan_timeout()
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text="No press detected.", fg=ACCENT_ORANGE)
                gpio_lbl.config(text="")

            def _thread():
                try:
                    self.pico.start_scan()
                    while self.scanning:
                        line = self.pico.read_scan_line(0.1)
                        if line and line.startswith("PIN:"):
                            try:
                                pin = int(line[4:])
                            except ValueError:
                                continue
                            if pin in DIGITAL_PINS and pin != -1:
                                self._request_stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _finish(p))
                                return
                except Exception:
                    self.root.after(0, _timeout)

            def _cancel():
                self.scanning = False
                self._request_stop_scan()
                _restore_idle()

            cancel_btn._command = _cancel
            cancel_btn._render(cancel_btn._bg)
            self._start_scan_timeout(_timeout, timeout_ms=10000)
            threading.Thread(target=_thread, daemon=True).start()

        detect_btn._command = start_detect
        detect_btn._render(detect_btn._bg)

    def _init_led_defaults(self):
        if "led_enabled" not in self.detected:
            self.detected["led_enabled"] = False
            self.detected["led_count"] = 0
            self.detected["led_brightness"] = 5
            self.detected["led_reactive"] = True
            self.detected["led_colors"] = list(self.DRUM_DEFAULT_COLORS)
            self.detected["led_maps"] = [(1 << i) if i < MAX_LEDS else 0
                                          for i in range(len(DRUM_LED_INPUT_NAMES))]
            self.detected["led_active_br"] = [7] * len(DRUM_LED_INPUT_NAMES)
        self.detected.setdefault("led_loop_enabled", False)
        self.detected.setdefault("led_loop_start", 0)
        self.detected.setdefault("led_loop_end", 0)
        self.detected.setdefault("led_breathe_enabled", False)
        self.detected.setdefault("led_breathe_start", 0)
        self.detected.setdefault("led_breathe_end", 0)
        self.detected.setdefault("led_breathe_min", 1)
        self.detected.setdefault("led_breathe_max", 9)
        self.detected.setdefault("led_wave_enabled", False)
        self.detected.setdefault("led_wave_origin", 0)

    def _build_led_content(self):
        self._init_led_defaults()
        f = self._body_frame

        led_enabled_var = tk.BooleanVar(value=self.detected["led_enabled"])
        led_count_var = tk.IntVar(value=self.detected["led_count"])
        led_brightness_var = tk.IntVar(value=self.detected["led_brightness"])
        led_reactive_var = tk.BooleanVar(value=self.detected["led_reactive"])
        led_color_vars = [tk.StringVar(value=c) for c in self.detected["led_colors"]]
        led_map_vars = [tk.IntVar(value=m) for m in self.detected["led_maps"]]
        led_active_vars = [tk.IntVar(value=b) for b in self.detected["led_active_br"]]
        led_loop_var = tk.BooleanVar(value=self.detected["led_loop_enabled"])
        led_loop_start_var = tk.IntVar(value=self.detected["led_loop_start"] + 1)
        led_loop_end_var = tk.IntVar(value=self.detected["led_loop_end"] + 1)
        led_breathe_var = tk.BooleanVar(value=self.detected["led_breathe_enabled"])
        led_breathe_start_var = tk.IntVar(value=self.detected["led_breathe_start"] + 1)
        led_breathe_end_var = tk.IntVar(value=self.detected["led_breathe_end"] + 1)
        led_breathe_min_var = tk.IntVar(value=self.detected["led_breathe_min"])
        led_breathe_max_var = tk.IntVar(value=self.detected["led_breathe_max"])
        led_wave_var = tk.BooleanVar(value=self.detected["led_wave_enabled"])
        led_wave_origin_var = tk.IntVar(value=self.detected["led_wave_origin"] + 1)

        def _sync():
            if led_enabled_var.get() and led_count_var.get() <= 0:
                led_count_var.set(14)
            max_count = MAX_LEDS if led_enabled_var.get() else 0
            count = max(0, min(max_count, led_count_var.get()))
            led_count_var.set(count)
            self.detected["led_enabled"] = led_enabled_var.get()
            self.detected["led_count"] = count
            self.detected["led_brightness"] = max(0, min(9, led_brightness_var.get()))
            self.detected["led_reactive"] = led_reactive_var.get()
            self.detected["led_colors"] = [v.get().strip().upper() for v in led_color_vars]
            self.detected["led_maps"] = [v.get() for v in led_map_vars]
            self.detected["led_active_br"] = [max(0, min(9, v.get())) for v in led_active_vars]
            self.detected["led_loop_enabled"] = led_loop_var.get()
            self.detected["led_loop_start"] = max(0, led_loop_start_var.get() - 1)
            self.detected["led_loop_end"] = max(0, led_loop_end_var.get() - 1)
            self.detected["led_breathe_enabled"] = led_breathe_var.get()
            self.detected["led_breathe_start"] = max(0, led_breathe_start_var.get() - 1)
            self.detected["led_breathe_end"] = max(0, led_breathe_end_var.get() - 1)
            self.detected["led_breathe_min"] = max(0, min(9, led_breathe_min_var.get()))
            self.detected["led_breathe_max"] = max(0, min(9, led_breathe_max_var.get()))
            self.detected["led_wave_enabled"] = led_wave_var.get()
            self.detected["led_wave_origin"] = max(0, led_wave_origin_var.get() - 1)

        def _text_for_bg(hex_rgb):
            try:
                r = int(hex_rgb[0:2], 16)
                g = int(hex_rgb[2:4], 16)
                b = int(hex_rgb[4:6], 16)
            except Exception:
                return "#FFFFFF"
            return "#000000" if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 140 else "#FFFFFF"

        two_col = tk.Frame(f, bg=BG_CARD)
        two_col.pack(fill="both", expand=True)
        left_col = tk.Frame(two_col, bg=BG_CARD, width=380)
        left_col.pack(side="left", fill="y", padx=(0, 12))
        tk.Frame(two_col, bg=BORDER, width=1).pack(side="left", fill="y", padx=(0, 12))
        right_col = tk.Frame(two_col, bg=BG_CARD)
        right_col.pack(side="left", fill="both", expand=True)

        tk.Label(left_col,
                 text="Wire MOSI (DI) to GP3 and SCK (CI) to GP6. GP3 and GP6 are reserved when LEDs are enabled.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8),
                 wraplength=360, justify="left").pack(anchor="w", pady=(0, 8))

        controls = tk.Frame(left_col, bg=BG_CARD)
        controls.pack(anchor="w", pady=(0, 8))
        colors_frame = tk.Frame(left_col, bg=BG_CARD)
        colors_frame.pack(anchor="w", pady=(0, 6))
        effects_frame = tk.Frame(left_col, bg=BG_CARD)
        effects_frame.pack(anchor="w", fill="x")

        react_frame = tk.Frame(right_col, bg=BG_CARD)
        react_frame.pack(anchor="w", pady=(0, 5))
        map_frame = tk.Frame(right_col, bg=BG_CARD)
        map_frame.pack(fill="both", expand=True)
        _bvcmd = (self.root.register(lambda P: P == "" or (P.isdigit() and 0 <= int(P) <= 9)), "%P")

        def _identify_led(led_idx):
            try:
                if self.pico.connected:
                    self.pico.led_flash(led_idx)
            except Exception:
                pass

        def _open_color_dialog(led_idx):
            cur_hex = led_color_vars[led_idx].get().strip().upper()
            if len(cur_hex) != 6:
                cur_hex = "FFFFFF"
            try:
                int(cur_hex, 16)
            except Exception:
                cur_hex = "FFFFFF"
            dlg = tk.Toplevel(f.winfo_toplevel())
            dlg.title(f"LED #{led_idx + 1} Color")
            dlg.configure(bg=BG_CARD)
            dlg.resizable(False, False)
            dlg.transient(f.winfo_toplevel())
            inner = tk.Frame(dlg, bg=BG_CARD)
            inner.pack(fill="both", expand=True, padx=16, pady=12)
            tk.Label(inner, text=f"Color for LED #{led_idx + 1}",
                     bg=BG_CARD, fg=TEXT_HEADER,
                     font=(FONT_UI, 11, "bold")).pack(pady=(0, 8))
            r_var = tk.IntVar(value=int(cur_hex[0:2], 16))
            g_var = tk.IntVar(value=int(cur_hex[2:4], 16))
            b_var = tk.IntVar(value=int(cur_hex[4:6], 16))
            preview = tk.Canvas(inner, width=80, height=50, bg=BG_CARD,
                                highlightthickness=1, highlightbackground=BORDER, bd=0)
            preview.pack(pady=(0, 6))
            hex_lbl = tk.Label(inner, text=f"#{cur_hex}", bg=BG_CARD, fg=TEXT_DIM,
                               font=("Consolas", 9))
            hex_lbl.pack(pady=(0, 8))

            def _upd(*_args):
                h = f"#{r_var.get():02X}{g_var.get():02X}{b_var.get():02X}"
                preview.delete("all")
                preview.create_rectangle(2, 2, 78, 48, fill=h, outline=h)
                hex_lbl.config(text=h)

            _upd()
            for label, var, color in (("Red", r_var, "#e74c3c"),
                                      ("Green", g_var, "#2ecc71"),
                                      ("Blue", b_var, "#3498db")):
                row = tk.Frame(inner, bg=BG_CARD)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=label, bg=BG_CARD, fg=color,
                         width=6, font=(FONT_UI, 8, "bold"), anchor="w").pack(side="left")
                tk.Scale(row, from_=0, to=255, orient="horizontal", variable=var,
                         bg=BG_CARD, fg=TEXT, troughcolor=color,
                         highlightthickness=0, bd=2, sliderrelief="raised",
                         activebackground=BG_INPUT, length=180,
                         showvalue=False, command=lambda _v: _upd()).pack(side="left", padx=(4, 4))
                tk.Label(row, textvariable=var, bg=BG_CARD, fg=TEXT,
                         font=("Consolas", 9), width=4).pack(side="left")
            btn_row = tk.Frame(inner, bg=BG_CARD)
            btn_row.pack(pady=(10, 0))

            def _apply():
                led_color_vars[led_idx].set(f"{r_var.get():02X}{g_var.get():02X}{b_var.get():02X}")
                _sync()
                _rebuild_colors()
                _rebuild_map()
                dlg.destroy()

            RoundedButton(btn_row, text="Apply", command=_apply,
                          bg_color=ACCENT_BLUE, btn_width=80, btn_height=28).pack(side="left", padx=(0, 8))
            RoundedButton(btn_row, text="Cancel", command=dlg.destroy,
                          bg_color=BG_INPUT, btn_width=80, btn_height=28).pack(side="left")
            _center_window(dlg, f.winfo_toplevel())
            dlg.grab_set()
            dlg.wait_window()

        def _rebuild_colors():
            for widget in colors_frame.winfo_children():
                widget.destroy()
            count = led_count_var.get()
            if count <= 0:
                tk.Label(colors_frame, text="LEDs are disabled.",
                         bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w")
                return
            tk.Label(colors_frame, text="LED Colors",
                     bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 4))
            grid = tk.Frame(colors_frame, bg=BG_CARD)
            grid.pack(anchor="w")
            for i in range(min(count, MAX_LEDS)):
                cell = tk.Frame(grid, bg=BG_CARD)
                cell.grid(row=i // 3, column=i % 3, padx=2, pady=2, sticky="w")
                tk.Label(cell, text=f"LED {i + 1}", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 7), width=5).pack(side="left")
                hex_c = led_color_vars[i].get().strip().upper()
                if len(hex_c) != 6:
                    hex_c = "FFFFFF"
                try:
                    int(hex_c, 16)
                except Exception:
                    hex_c = "FFFFFF"
                sw = tk.Canvas(cell, width=24, height=18, bg=f"#{hex_c}",
                               highlightbackground=BORDER, highlightthickness=1,
                               cursor="hand2")
                sw.create_rectangle(0, 0, 24, 18, fill=f"#{hex_c}", outline=f"#{hex_c}")
                sw.pack(side="left", padx=(1, 2))
                sw.bind("<Button-1>", lambda _e, idx=i: _open_color_dialog(idx))
                ib = RoundedButton(cell, text="Flash", bg_color=BG_INPUT,
                                   btn_width=40, btn_height=18,
                                   btn_font=(FONT_UI, 6, "bold"))
                ib._command = lambda idx=i: _identify_led(idx)
                ib._render(ib._bg)
                ib.pack(side="left")

        def _rebuild_map():
            for widget in map_frame.winfo_children():
                widget.destroy()
            if not led_reactive_var.get():
                return
            count = led_count_var.get()
            if count <= 0:
                return
            tk.Label(map_frame, text="Reactive Input -> LED Mapping",
                     bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 4))
            grid = tk.Frame(map_frame, bg=BG_CARD)
            grid.pack(anchor="w")
            led_col_start = 1
            bright_col = led_col_start + min(count, MAX_LEDS)
            tk.Label(grid, text="Input", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 7, "bold"), anchor="w", width=13).grid(row=0, column=0, sticky="w")
            for j in range(min(count, MAX_LEDS)):
                hex_c = led_color_vars[j].get().strip().upper()
                if len(hex_c) != 6:
                    hex_c = "FFFFFF"
                try:
                    int(hex_c, 16)
                except Exception:
                    hex_c = "FFFFFF"
                tk.Label(grid, text=f"{j}", bg=f"#{hex_c}", fg=_text_for_bg(hex_c),
                         font=(FONT_UI, 6, "bold")).grid(row=0, column=led_col_start + j, padx=1, pady=(0, 2))
            tk.Label(grid, text="Bright", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 7, "bold")).grid(row=0, column=bright_col, padx=(5, 0))

            for inp_idx, (key, label) in enumerate(zip(DRUM_LED_INPUT_NAMES, DRUM_LED_INPUT_LABELS)):
                name_frame = tk.Frame(grid, bg=BG_CARD)
                name_frame.grid(row=inp_idx + 1, column=0, sticky="w", padx=(0, 2), pady=1)
                color = DRUM_INPUT_COLORS.get(key)
                if color:
                    dot = tk.Canvas(name_frame, width=9, height=9, bg=BG_CARD,
                                    highlightthickness=0, bd=0)
                    if key.endswith("_cym"):
                        dot.create_oval(1, 1, 8, 8, outline=color, width=2)
                    else:
                        dot.create_oval(1, 1, 8, 8, fill=color, outline=color)
                    dot.pack(side="left", padx=(0, 2))
                tk.Label(name_frame, text=label, bg=BG_CARD, fg=TEXT,
                         font=(FONT_UI, 7), anchor="w").pack(side="left")

                row_vars = []
                current_mask = led_map_vars[inp_idx].get()
                for j in range(min(count, MAX_LEDS)):
                    var = tk.BooleanVar(value=bool(current_mask & (1 << j)))
                    row_vars.append(var)

                    def _update(i=inp_idx, vars_ref=row_vars):
                        mask = sum((1 << bit) for bit, var_ref in enumerate(vars_ref) if var_ref.get())
                        led_map_vars[i].set(mask)
                        _sync()

                    ttk.Checkbutton(grid, variable=var, command=_update).grid(
                        row=inp_idx + 1, column=led_col_start + j, padx=0, pady=0)

                bw = tk.Frame(grid, bg=BG_CARD, width=48, height=22)
                bw.grid(row=inp_idx + 1, column=bright_col, padx=(5, 0), pady=1)
                bw.pack_propagate(False)
                ttk.Spinbox(bw, from_=0, to=9, width=3,
                            textvariable=led_active_vars[inp_idx],
                            command=_sync, validate="key",
                            validatecommand=_bvcmd).pack(fill="both", expand=True)

        def _on_count_change():
            _sync()
            _rebuild_colors()
            _rebuild_map()

        def _on_count_live_change(widget):
            raw = widget.get().strip()
            if not raw:
                return
            try:
                led_count_var.set(int(raw))
            except (ValueError, tk.TclError):
                return
            _on_count_change()

        def _on_enable():
            _sync()
            _rebuild_controls()
            _rebuild_colors()
            _rebuild_map()

        def _rebuild_controls():
            for widget in controls.winfo_children():
                widget.destroy()
            ttk.Checkbutton(controls, text="Enable LEDs",
                            variable=led_enabled_var, command=_on_enable).pack(side="left", padx=(0, 10))
            tk.Label(controls, text="Count:", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
            _cvcmd = (self.root.register(lambda P: P == "" or P.isdigit()), "%P")
            count_spin = ttk.Spinbox(controls, from_=0, to=MAX_LEDS, width=4,
                                     textvariable=led_count_var, command=_on_count_change,
                                     validate="key", validatecommand=_cvcmd)
            count_spin.pack(side="left", padx=(0, 8))
            count_spin.bind("<KeyRelease>", lambda _e, widget=count_spin: _on_count_live_change(widget))
            count_spin.bind("<Return>", lambda _e: _on_count_change())
            count_spin.bind("<FocusOut>", lambda _e: _on_count_change())
            tk.Label(controls, text="Brightness:", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
            ttk.Spinbox(controls, from_=0, to=9, width=3,
                        textvariable=led_brightness_var, command=_sync,
                        validate="key", validatecommand=_bvcmd).pack(side="left")

        def _build_effects():
            for widget in effects_frame.winfo_children():
                widget.destroy()
            for widget in react_frame.winfo_children():
                widget.destroy()
            tk.Frame(effects_frame, bg=BORDER, height=1).pack(fill="x", pady=(4, 6))
            loop = tk.Frame(effects_frame, bg=BG_CARD)
            loop.pack(anchor="w", pady=2)
            ttk.Checkbutton(loop, text="Color Loop", variable=led_loop_var, command=_sync).pack(side="left", padx=(0, 8))
            for text, var in (("From:", led_loop_start_var), ("To:", led_loop_end_var)):
                tk.Label(loop, text=text, bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
                ttk.Spinbox(loop, from_=1, to=MAX_LEDS, width=3, textvariable=var, command=_sync).pack(side="left", padx=(0, 6))

            breathe = tk.Frame(effects_frame, bg=BG_CARD)
            breathe.pack(anchor="w", pady=2)

            def _breathe_toggle():
                if led_breathe_var.get():
                    led_wave_var.set(False)
                _sync()

            ttk.Checkbutton(breathe, text="Breathe", variable=led_breathe_var, command=_breathe_toggle).pack(side="left", padx=(0, 8))
            for text, var in (("From:", led_breathe_start_var), ("To:", led_breathe_end_var),
                              ("Min:", led_breathe_min_var), ("Max:", led_breathe_max_var)):
                tk.Label(breathe, text=text, bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
                if text in ("Min:", "Max:"):
                    ttk.Spinbox(breathe, from_=0, to=9, width=3,
                                textvariable=var, command=_sync,
                                validate="key", validatecommand=_bvcmd).pack(side="left", padx=(0, 5))
                else:
                    ttk.Spinbox(breathe, from_=1, to=MAX_LEDS, width=3,
                                textvariable=var, command=_sync).pack(side="left", padx=(0, 5))

            wave = tk.Frame(effects_frame, bg=BG_CARD)
            wave.pack(anchor="w", pady=2)

            def _wave_toggle():
                if led_wave_var.get():
                    led_breathe_var.set(False)
                _sync()

            ttk.Checkbutton(wave, text="Ripple", variable=led_wave_var, command=_wave_toggle).pack(side="left", padx=(0, 8))
            tk.Label(wave, text="Origin:", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
            ttk.Spinbox(wave, from_=1, to=MAX_LEDS, width=3,
                        textvariable=led_wave_origin_var, command=_sync).pack(side="left")

            ttk.Checkbutton(react_frame, text="Reactive LEDs on keypress",
                            variable=led_reactive_var,
                            command=lambda: [_sync(), _rebuild_map()]).pack(side="left", padx=(0, 8))
            tk.Label(react_frame, text="Rows use drum firmware input order.",
                     bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")

        _rebuild_controls()
        _build_effects()
        _rebuild_colors()
        _rebuild_map()
        _sync()

    def _build_placeholder_content(self, name):
        if name != "Review & Save":
            return super()._build_placeholder_content(name)

        f = self._body_frame
        tk.Label(f, text="Review your drum controls before saving.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(anchor="nw", pady=(0, 8))
        canvas = tk.Canvas(f, width=720, height=290, bg=BG_INPUT,
                           highlightthickness=1, highlightbackground=BORDER, bd=0)
        canvas.pack(anchor="nw", pady=(0, 12))
        shapes = {}

        def _add_circle(key, label, x, y, r, color):
            tag = f"input_{key}"
            canvas.create_oval(x - r, y - r, x + r, y + r,
                               fill=BG_CARD, outline=color, width=3, tags=(tag,))
            canvas.create_text(x, y, text=label, fill=TEXT, font=(FONT_UI, 9, "bold"), tags=(tag,))
            shapes[key] = tag

        def _add_rect(key, label, x, y, w, h):
            tag = f"input_{key}"
            canvas.create_rectangle(x, y, x + w, y + h,
                                    fill=BG_CARD, outline=BORDER, width=2, tags=(tag,))
            canvas.create_text(x + w / 2, y + h / 2, text=label,
                               fill=TEXT, font=(FONT_UI, 8, "bold"), tags=(tag,))
            shapes[key] = tag

        _add_circle("yellow_cym", "Y Cym", 190, 70, 42, "#d4a017")
        _add_circle("blue_cym", "B Cym", 360, 58, 42, "#2980b9")
        _add_circle("green_cym", "G Cym", 530, 70, 42, "#27ae60")
        _add_circle("red_drum", "Red", 155, 170, 42, "#e74c3c")
        _add_circle("yellow_drum", "Yellow", 285, 175, 42, "#f1c40f")
        _add_circle("blue_drum", "Blue", 420, 175, 42, "#3498db")
        _add_circle("green_drum", "Green", 555, 170, 42, "#2ecc71")
        _add_rect("foot_pedal", "Foot Pedal", 305, 235, 115, 34)
        _add_rect("select", "Select", 40, 235, 74, 30)
        _add_rect("start", "Start", 604, 235, 74, 30)
        _add_rect("dpad_up", "Up", 57, 70, 52, 28)
        _add_rect("dpad_left", "Left", 10, 103, 52, 28)
        _add_rect("dpad_right", "Right", 104, 103, 52, 28)
        _add_rect("dpad_down", "Down", 57, 136, 52, 28)

        pin_to_key = {}
        for key in self._PIN_ASSIGNMENT_KEYS:
            pin = self.detected.get(key, -1)
            if isinstance(pin, int) and pin >= 0:
                pin_to_key[pin] = key

        def _redraw(active_keys):
            for key, tag in shapes.items():
                color = DRUM_INPUT_COLORS.get(key, ACCENT_BLUE)
                items = canvas.find_withtag(tag)
                if not items:
                    continue
                canvas.itemconfig(items[0], fill=ACCENT_BLUE if key in active_keys else BG_CARD)
                canvas.itemconfig(items[0], outline=color if key in active_keys or key in DRUM_INPUT_COLORS else BORDER)
                for item in items[1:]:
                    canvas.itemconfig(item, fill="white" if key in active_keys else TEXT)

        def _poll():
            if not self._preview_active:
                return
            now = time.time()
            active = {pin_to_key[p] for p, ts in self._preview_seen.items()
                      if now - ts < 0.50 and p in pin_to_key}
            _redraw(active)
            self.root.after(80, _poll)

        def _start_preview():
            if not self.pico.connected:
                return
            self._preview_active = True
            self._preview_seen = {}

            def _thread():
                try:
                    self.pico.start_scan()
                    while self._preview_active:
                        line = self.pico.read_scan_line(0.05)
                        if line and line.startswith("PIN:"):
                            try:
                                self._preview_seen[int(line[4:])] = time.time()
                            except ValueError:
                                pass
                except Exception:
                    pass

            threading.Thread(target=_thread, daemon=True).start()
            self.root.after(80, _poll)

        _start_preview()
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(0, 16))
        RoundedButton(f, text="Export Configuration...",
                      command=self._easy_export_config,
                      bg_color=ACCENT_BLUE, btn_width=200, btn_height=36).pack(anchor="nw")

    def _easy_export_config(self):
        self._init_led_defaults()
        date_str = datetime.datetime.now().strftime("%m-%d-%Y")
        path = filedialog.asksaveasfilename(
            title="Export Drum Easy Configuration",
            initialfile=f"Easy Drum Config {date_str}",
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        cfg = {"device_type": "drum_kit", "device_name": "Drum Controller", "debounce": 5}
        for key in self._PIN_ASSIGNMENT_KEYS:
            pin = self.detected.get(key, -1)
            cfg[key] = pin if pin is not None else -1
        cfg.update({
            "led_enabled": 1 if self.detected.get("led_enabled") else 0,
            "led_count": self.detected.get("led_count", 0),
            "led_brightness": self._brightness_to_hw(self.detected.get("led_brightness", 5)),
            "led_loop_enabled": 1 if self.detected.get("led_loop_enabled") else 0,
            "led_loop_start": self.detected.get("led_loop_start", 0),
            "led_loop_end": self.detected.get("led_loop_end", 0),
            "led_breathe_enabled": 1 if self.detected.get("led_breathe_enabled") else 0,
            "led_breathe_start": self.detected.get("led_breathe_start", 0),
            "led_breathe_end": self.detected.get("led_breathe_end", 0),
            "led_breathe_min": self._brightness_to_hw(self.detected.get("led_breathe_min", 1)),
            "led_breathe_max": self._brightness_to_hw(self.detected.get("led_breathe_max", 9)),
            "led_wave_enabled": 1 if self.detected.get("led_wave_enabled") else 0,
            "led_wave_origin": self.detected.get("led_wave_origin", 0),
            "led_loop_speed": 3000,
            "led_breathe_speed": 3000,
            "led_wave_speed": 800,
            "led_colors": self.detected.get("led_colors", list(self.DRUM_DEFAULT_COLORS))[:MAX_LEDS],
            "led_maps": self.detected.get("led_maps", [0] * len(DRUM_LED_INPUT_NAMES)),
            "led_active_br": [
                self._brightness_to_hw(v)
                for v in self.detected.get("led_active_br", [7] * len(DRUM_LED_INPUT_NAMES))
            ],
        })
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
            messagebox.showinfo("Export Successful", f"Configuration exported to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _validate_led_pin_reservations(self):
        if not self.detected.get("led_enabled"):
            return True
        conflicts = []
        for key in self._PIN_ASSIGNMENT_KEYS:
            if self.detected.get(key) in self.LED_SPI_PINS:
                conflicts.append(f"{self._get_pin_input_label(key)} -> GPIO {self.detected[key]}")
        if not conflicts:
            return True
        messagebox.showerror(
            "LED Pin Conflict",
            "LEDs reserve GPIO 3 and GPIO 6 on the drum firmware.\n\n"
            "Move these inputs to different pins or disable LEDs before saving:\n"
            + "\n".join(conflicts)
        )
        return False

    def _finish_and_save(self):
        self._stop_scan_and_monitor()
        self._init_led_defaults()
        if not self._validate_led_pin_reservations():
            self._show_page(self._current_page)
            return
        if not self.pico.connected:
            self._go_back()
            return

        for widget in self._body_frame.winfo_children():
            widget.destroy()
        saving_lbl = tk.Label(self._body_frame,
                              text="Saving drum configuration and rebooting controller...",
                              bg=BG_CARD, fg=ACCENT_BLUE, font=(FONT_UI, 12))
        saving_lbl.pack(anchor="nw", pady=30)
        self._body_frame.update_idletasks()

        def _worker():
            time.sleep(0.2)
            self.pico.flush_input()
            d = self.detected
            last_exc = None
            for attempt in range(3):
                if attempt > 0:
                    self.root.after(0, lambda a=attempt: saving_lbl.config(
                        text=f"Retrying...  (attempt {a + 1} of 3)"
                    ))
                    time.sleep(0.3)
                try:
                    for key in self._PIN_ASSIGNMENT_KEYS:
                        pin = d.get(key, -1)
                        self.pico.set_value(key, str(pin if pin is not None else -1))
                    self.pico.set_value("debounce", "5")
                    name = "".join(c for c in "Drum Controller" if c in VALID_NAME_CHARS)
                    self.pico.set_value("device_name", name[:20])
                    self.pico.set_value("led_enabled", "1" if d.get("led_enabled") else "0")
                    self.pico.set_value("led_count", str(d.get("led_count", 0)))
                    self.pico.set_value("led_brightness", str(self._brightness_to_hw(d.get("led_brightness", 5))))

                    colors = d.get("led_colors", list(self.DRUM_DEFAULT_COLORS))
                    for i, color in enumerate(colors[:MAX_LEDS]):
                        hex_c = str(color).strip().upper().lstrip("#")
                        if len(hex_c) != 6:
                            hex_c = "FFFFFF"
                        self.pico.set_value(f"led_color_{i}", hex_c)
                    maps = d.get("led_maps", [0] * len(DRUM_LED_INPUT_NAMES))
                    active = d.get("led_active_br", [7] * len(DRUM_LED_INPUT_NAMES))
                    for i in range(len(DRUM_LED_INPUT_NAMES)):
                        self.pico.set_value(f"led_map_{i}", f"{int(maps[i]):04X}")
                        self.pico.set_value(f"led_active_{i}", str(self._brightness_to_hw(active[i])))

                    self.pico.set_value("led_loop_enabled", "1" if d.get("led_loop_enabled") else "0")
                    self.pico.set_value("led_loop_start", str(d.get("led_loop_start", 0)))
                    self.pico.set_value("led_loop_end", str(d.get("led_loop_end", 0)))
                    self.pico.set_value("led_breathe_enabled", "1" if d.get("led_breathe_enabled") else "0")
                    self.pico.set_value("led_breathe_start", str(d.get("led_breathe_start", 0)))
                    self.pico.set_value("led_breathe_end", str(d.get("led_breathe_end", 0)))
                    self.pico.set_value("led_breathe_min", str(self._brightness_to_hw(d.get("led_breathe_min", 1))))
                    self.pico.set_value("led_breathe_max", str(self._brightness_to_hw(d.get("led_breathe_max", 9))))
                    self.pico.set_value("led_wave_enabled", "1" if d.get("led_wave_enabled") else "0")
                    self.pico.set_value("led_wave_origin", str(d.get("led_wave_origin", 0)))
                    for key, val in (("led_loop_speed", "3000"),
                                     ("led_breathe_speed", "3000"),
                                     ("led_wave_speed", "800")):
                        try:
                            self.pico.set_value(key, val)
                        except ValueError as exc:
                            if "unknown key" not in str(exc).lower():
                                raise
                    self.pico.save()
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
            if last_exc is not None:
                self.root.after(0, lambda e=str(last_exc): self._on_save_error(e))
                return
            try:
                self.pico.reboot()
            except Exception:
                pass
            self.root.after(0, self._direct_go_back)

        threading.Thread(target=_worker, daemon=True).start()

    def show(self):
        self.root.title("OCC - Easy Drum Configuration")
        self._empty_menu = getattr(self, "_empty_menu", None) or tk.Menu(self.root)
        self.root.config(menu=self._empty_menu)
        self._reset_easy_config_state()
        self._show_page(0)
        self.frame.pack(fill="both", expand=True)
