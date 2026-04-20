import threading
import time
import sys
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser

from .constants import (
    BG_CARD, BG_INPUT, BG_MAIN, BORDER, TEXT, TEXT_DIM, TEXT_HEADER,
    ACCENT_BLUE, ACCENT_RED, ACCENT_ORANGE, ACCENT_GREEN, MAX_LEDS,
    I2C_MODEL_LABELS, I2C_MODEL_VALUES,
    get_led_input_names_for_device_type,
)
from .fonts import FONT_UI
from .widgets import RoundedButton, LiveBarGraph, CalibratedBarGraph
from .utils import _center_window


def _as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value, default=0, low=None, high=None):
    try:
        result = int(value)
    except Exception:
        result = default
    if low is not None:
        result = max(low, result)
    if high is not None:
        result = min(high, result)
    return result


def _clean_color(value):
    color = str(value).strip().upper().lstrip("#")
    if len(color) != 6:
        return "FFFFFF"
    try:
        int(color, 16)
    except Exception:
        return "FFFFFF"
    return color


def _disable_native_close_button(win):
    win.protocol("WM_DELETE_WINDOW", lambda: None)
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = int(win.winfo_id())
        parent_hwnd = ctypes.windll.user32.GetParent(hwnd)
        if parent_hwnd:
            hwnd = parent_hwnd
        gcl_style = -16
        ws_sysmenu = 0x00080000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, gcl_style)
        ctypes.windll.user32.SetWindowLongW(hwnd, gcl_style, style & ~ws_sysmenu)
        ctypes.windll.user32.DrawMenuBar(hwnd)
    except Exception:
        pass


class QuickTuneDialog:
    """Post-preset tuning wizard for guitar firmwares."""

    PAGES = ("Whammy", "Tilt", "LEDs")

    def __init__(self, root, pico, cfg, preset_name=""):
        self.root = root
        self.pico = pico
        self.cfg = dict(cfg or {})
        self.preset_name = preset_name
        self.saved = False
        self._page = 0
        self._monitoring = False
        self._monitor_thread = None
        self._monitor_prefix = None
        self._capture_in_progress = False
        self._axis_widgets = {}
        self._latest_raw = {"whammy": None, "tilt": None}
        self._whammy_rest_raw = None
        self._whammy_act_raw = None
        self._axis_quick_tuned = {"whammy": False, "tilt": False}
        self._axis_bound_captures = {"tilt": set()}

        self.device_type = str(self.cfg.get("device_type", "guitar_alternate")).strip()
        try:
            self.led_input_names = list(get_led_input_names_for_device_type(self.device_type))
        except Exception:
            self.led_input_names = []

        self.whammy_mode = str(self.cfg.get("whammy_mode", "digital")).strip()
        self.whammy_pin = _as_int(self.cfg.get("whammy_pin", -1), -1)
        self.whammy_min = tk.IntVar(value=_as_int(self.cfg.get("whammy_min", 0), 0, 0, 4095))
        self.whammy_max = tk.IntVar(value=_as_int(self.cfg.get("whammy_max", 4095), 4095, 0, 4095))
        self.whammy_invert = tk.BooleanVar(value=_as_bool(self.cfg.get("whammy_invert", 0)))

        self.tilt_mode = str(self.cfg.get("tilt_mode", "digital")).strip()
        self.tilt_pin = _as_int(self.cfg.get("tilt_pin", -1), -1)
        self.tilt_axis = _as_int(self.cfg.get("adxl345_axis", self.cfg.get("tilt_axis", 0)), 0, 0, 2)
        self.i2c_model = tk.IntVar(value=_as_int(self.cfg.get("i2c_model", 0), 0, 0, 1))
        self.tilt_min = tk.IntVar(value=_as_int(self.cfg.get("tilt_min", 0), 0, 0, 4095))
        self.tilt_max = tk.IntVar(value=_as_int(self.cfg.get("tilt_max", 4095), 4095, 0, 4095))
        self.tilt_invert = tk.BooleanVar(value=_as_bool(self.cfg.get("tilt_invert", 0)))
        self._tilt_detecting = False
        self._tilt_detect_started = False
        self._tilt_detect_failed = False
        self._tilt_detect_widgets = {}
        if self.whammy_mode == "analog" and self.whammy_pin >= 0:
            self.whammy_min.set(0)
            self.whammy_max.set(4095)
        if self.tilt_mode == "i2c" or (self.tilt_mode == "analog" and self.tilt_pin >= 0):
            self.tilt_min.set(0)
            self.tilt_max.set(4095)

        ema_alpha = _as_int(self.cfg.get("ema_alpha", 140), 140, 0, 256)
        self.ema_alpha = tk.IntVar(value=256 if ema_alpha == 0 else ema_alpha)

        self.led_enabled = _as_bool(self.cfg.get("led_enabled", 0))
        self.led_count = _as_int(self.cfg.get("led_count", 0), 0, 0, MAX_LEDS)
        self.led_colors = self._load_led_colors()
        self.led_maps = self._load_int_list("led_maps", len(self.led_input_names), 0)
        self.led_active_br = self._load_int_list("led_active_br", len(self.led_input_names), 23)
        self._reactive_backup = list(self.led_maps)
        self.led_reactive = tk.BooleanVar(value=any(m != 0 for m in self.led_maps))
        self.led_loop_enabled = tk.BooleanVar(value=_as_bool(self.cfg.get("led_loop_enabled", 0)))
        self.led_loop_start = tk.IntVar(value=_as_int(self.cfg.get("led_loop_start", 0), 0, 0, MAX_LEDS - 1) + 1)
        self.led_loop_end = tk.IntVar(value=_as_int(self.cfg.get("led_loop_end", max(0, self.led_count - 1)), 0, 0, MAX_LEDS - 1) + 1)
        self.led_breathe_enabled = tk.BooleanVar(value=_as_bool(self.cfg.get("led_breathe_enabled", 0)))
        self.led_breathe_start = tk.IntVar(value=_as_int(self.cfg.get("led_breathe_start", 0), 0, 0, MAX_LEDS - 1) + 1)
        self.led_breathe_end = tk.IntVar(value=_as_int(self.cfg.get("led_breathe_end", max(0, self.led_count - 1)), 0, 0, MAX_LEDS - 1) + 1)
        self.led_breathe_min = tk.IntVar(value=_as_int(self.cfg.get("led_breathe_min", 0), 0, 0, 31))
        self.led_breathe_max = tk.IntVar(value=_as_int(self.cfg.get("led_breathe_max", 31), 31, 0, 31))
        self.led_wave_enabled = tk.BooleanVar(value=_as_bool(self.cfg.get("led_wave_enabled", 0)))
        self.led_wave_origin = tk.IntVar(value=_as_int(self.cfg.get("led_wave_origin", 0), 0, 0, MAX_LEDS - 1) + 1)

        self.win = tk.Toplevel(self.root)
        self.win.title("Quick Tune")
        self.win.configure(bg=BG_MAIN)
        self.win.resizable(False, False)
        self.win.transient(self.root)
        _disable_native_close_button(self.win)

        self._build_shell()

    def _load_led_colors(self):
        raw = self.cfg.get("led_colors", [])
        if "led_colors_raw" in self.cfg:
            raw = str(self.cfg["led_colors_raw"]).split(",")
        colors = [_clean_color(c) for c in raw]
        while len(colors) < MAX_LEDS:
            colors.append("FFFFFF")
        return colors[:MAX_LEDS]

    def _load_int_list(self, key, target_len, default):
        values = self.cfg.get(key, [])
        if not isinstance(values, (list, tuple)):
            values = []
        result = [_as_int(v, default) for v in values[:target_len]]
        while len(result) < target_len:
            result.append(default)
        return result

    def _build_shell(self):
        outer = tk.Frame(self.win, bg=BG_MAIN)
        outer.pack(fill="both", expand=True, padx=16, pady=12)

        header = tk.Frame(outer, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        header.pack(fill="x")
        hinner = tk.Frame(header, bg=BG_CARD)
        hinner.pack(fill="x", padx=14, pady=8)
        tk.Label(hinner, text="Quick Tune", bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 14, "bold")).pack(side="left")
        subtitle = self.preset_name or "Preset installation"
        tk.Label(hinner, text=subtitle, bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9)).pack(side="left", padx=(12, 0))

        self._progress = tk.Label(outer, text="", bg=BG_MAIN, fg=TEXT_DIM,
                                  font=(FONT_UI, 8), anchor="e")
        self._progress.pack(fill="x", pady=(6, 2))

        self._card = tk.Frame(outer, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        self._card.pack(fill="both", expand=True)

        self._title = tk.Label(self._card, text="", bg=BG_CARD, fg=TEXT_HEADER,
                               font=(FONT_UI, 13, "bold"), anchor="w")
        self._title.pack(fill="x", padx=16, pady=(10, 0))
        self._hint = tk.Label(self._card, text="", bg=BG_CARD, fg=TEXT_DIM,
                              font=(FONT_UI, 8), anchor="w", justify="left")
        self._header_sep = tk.Frame(self._card, bg=BORDER, height=1)
        self._header_sep.pack(fill="x", padx=16)

        self._body = tk.Frame(self._card, bg=BG_CARD)
        self._body.pack(fill="both", expand=True, padx=16, pady=10)

        nav = tk.Frame(outer, bg=BG_MAIN)
        nav.pack(fill="x", pady=(8, 0))
        self._prev_btn = RoundedButton(nav, text="Back", command=self._prev_page,
                                       bg_color=BG_INPUT, btn_width=100, btn_height=30)
        self._prev_btn.pack(side="left")
        self._next_btn = RoundedButton(nav, text="Next", command=self._next_page,
                                       bg_color=ACCENT_BLUE, btn_width=210, btn_height=30)
        self._next_btn.pack(side="right")

    def show(self):
        self._show_page(0)
        self.win.update_idletasks()
        _disable_native_close_button(self.win)
        _center_window(self.win, self.root)
        self.win.deiconify()
        self.win.lift(self.root)
        self.win.focus_force()
        self.win.grab_set()
        self.root.wait_window(self.win)
        return self.saved

    def _set_page_header_visible(self, visible):
        if visible:
            if not self._title.winfo_manager():
                self._title.pack(fill="x", padx=16, pady=(10, 0), before=self._body)
            if self._hint.winfo_manager():
                self._hint.pack_forget()
            if not self._header_sep.winfo_manager():
                self._header_sep.pack(fill="x", padx=16, before=self._body)
            self._body.pack_configure(padx=16, pady=10)
            return
        self._title.pack_forget()
        self._hint.pack_forget()
        self._header_sep.pack_forget()
        self._body.pack_configure(padx=16, pady=(6, 8))

    def _fit_window_to_content(self):
        try:
            self.win.update_idletasks()
            req_w = max(800, self.win.winfo_reqwidth())
            req_h = max(450, self.win.winfo_reqheight())
            px = self.root.winfo_rootx()
            py = self.root.winfo_rooty()
            pw = self.root.winfo_width()
            ph = self.root.winfo_height()
            self.win.geometry(f"{req_w}x{req_h}+{px + (pw - req_w) // 2}+{py + (ph - req_h) // 2}")
        except tk.TclError:
            pass

    def _show_page(self, page):
        self._stop_monitoring()
        self._page = page
        for child in self._body.winfo_children():
            child.destroy()
        self._axis_widgets = {}

        title = self.PAGES[page]
        self._progress.config(text=f"Step {page + 1} of {len(self.PAGES)}")
        self._prev_btn.set_state("disabled" if page == 0 else "normal")
        self._next_btn._label = "Save and Enter Play Mode" if page == len(self.PAGES) - 1 else "Next"
        self._next_btn._render(self._next_btn._bg)

        if title == "Whammy":
            self._set_page_header_visible(True)
            self._title.config(text=title)
            self._build_axis_page("whammy")
        elif title == "Tilt":
            self._set_page_header_visible(True)
            self._title.config(text=title)
            self._build_axis_page("tilt")
        else:
            self._set_page_header_visible(False)
            self._build_led_page()
        self.win.after_idle(self._fit_window_to_content)

    def _prev_page(self):
        if self._page > 0:
            self._show_page(self._page - 1)

    def _next_page(self):
        if self._page < len(self.PAGES) - 1:
            self._show_page(self._page + 1)
        else:
            self._save_and_reboot()

    def _axis_values(self, prefix):
        if prefix == "whammy":
            return {
                "mode": self.whammy_mode,
                "pin": self.whammy_pin,
                "min": self.whammy_min,
                "max": self.whammy_max,
                "invert": self.whammy_invert,
                "label": "Whammy",
            }
        return {
            "mode": self.tilt_mode,
            "pin": self.tilt_pin,
            "min": self.tilt_min,
            "max": self.tilt_max,
            "invert": self.tilt_invert,
            "label": "Tilt",
        }

    def _build_axis_page(self, prefix):
        data = self._axis_values(prefix)
        mode = data["mode"]
        pin = data["pin"]
        label = data["label"]
        monitorable = (prefix == "tilt" and mode == "i2c") or (mode == "analog" and pin >= 0)

        info = tk.Frame(self._body, bg=BG_CARD)
        info.pack(fill="x", pady=(0, 10))
        detail = f"Mode: {mode}"
        if mode == "i2c":
            detail += f"   Axis: {self.tilt_axis}"
        elif pin >= 0:
            detail += f"   GPIO: {pin}"
        tk.Label(info, text=detail, bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w")
        if prefix == "tilt" and mode == "i2c":
            self._build_tilt_i2c_detect_row()

        if not monitorable:
            text = f"This preset uses {mode or 'digital'} {label.lower()} input, so there is no analog axis range to tune."
            tk.Label(self._body, text=text, bg=BG_CARD, fg=ACCENT_ORANGE,
                     font=(FONT_UI, 11), wraplength=760, justify="left").pack(anchor="w", pady=24)
            return

        columns = tk.Frame(self._body, bg=BG_CARD)
        columns.pack(fill="both", expand=True)
        left_col = tk.Frame(columns, bg=BG_CARD)
        right_col = tk.Frame(columns, bg="#2f2f35", width=330, height=126,
                             highlightbackground="#6a6a72", highlightthickness=2)
        right_col.pack_propagate(False)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 14), anchor="n")
        right_col.pack(side="left", fill="none", anchor="n", ipadx=10, ipady=10)

        live = LiveBarGraph(left_col, label=f"{label} Raw", width=380, height=30,
                            min_marker_var=data["min"], max_marker_var=data["max"])
        live.pack(fill="x", pady=(0, 8))

        readout = tk.Frame(left_col, bg=BG_CARD)
        readout.pack(fill="x", pady=(0, 8))
        min_lbl = tk.Label(readout, text="", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        max_lbl = tk.Label(readout, text="", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        min_lbl.pack(side="left")
        max_lbl.pack(side="left", padx=(18, 0))

        cal = CalibratedBarGraph(right_col, label=f"{label} Cal", width=280, height=30,
                                 min_var=data["min"], max_var=data["max"],
                                 invert_var=data["invert"], ema_alpha_var=self.ema_alpha)
        cal.pack(fill="x", padx=12, pady=(28, 10))
        monitor_btn = RoundedButton(right_col, text=f"Check {label}",
                                    command=lambda p=prefix: self._toggle_axis_monitor(p),
                                    bg_color=ACCENT_BLUE, btn_width=130, btn_height=30,
                                    btn_font=(FONT_UI, 8, "bold"))
        monitor_btn.pack(side="left", padx=(52, 8), pady=(0, 8))
        invert_check = ttk.Checkbutton(right_col, text="Invert", variable=data["invert"])
        invert_check.pack(side="left", pady=(0, 8))

        def update_labels(*_):
            try:
                captured = self._axis_quick_tuned.get(prefix, False)
                if min_lbl.winfo_exists():
                    min_lbl.config(text=f"Min: {data['min'].get()}" if captured else "Min: not set")
                if max_lbl.winfo_exists():
                    max_lbl.config(text=f"Max: {data['max'].get()}" if captured else "Max: not set")
                if live.winfo_exists():
                    live.redraw_markers()
                if cal.winfo_exists():
                    cal.redraw()
            except tk.TclError:
                pass

        data["min"].trace_add("write", update_labels)
        data["max"].trace_add("write", update_labels)
        data["invert"].trace_add("write", update_labels)
        update_labels()

        btns = tk.Frame(left_col, bg=BG_CARD)
        btns.pack(fill="x")
        if prefix == "whammy":
            rest_status = tk.Label(btns, text="Rest: not recorded", bg=BG_CARD,
                                   fg=TEXT_DIM, font=(FONT_UI, 8))
            act_status = tk.Label(btns, text="Actuated: not recorded", bg=BG_CARD,
                                  fg=TEXT_DIM, font=(FONT_UI, 8))
            RoundedButton(btns, text="Whammy at Rest",
                          command=lambda: self._capture_whammy_position("rest"),
                          bg_color=ACCENT_BLUE, btn_width=145, btn_height=30,
                          btn_font=(FONT_UI, 8, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
            rest_status.grid(row=0, column=1, sticky="w", padx=(0, 18), pady=(0, 4))
            RoundedButton(btns, text="Whammy Actuated",
                          command=lambda: self._capture_whammy_position("actuated"),
                          bg_color=ACCENT_BLUE, btn_width=160, btn_height=30,
                          btn_font=(FONT_UI, 8, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 8))
            act_status.grid(row=1, column=1, sticky="w", padx=(0, 18))
        else:
            min_btn = RoundedButton(btns, text="Set Min",
                                    command=lambda p=prefix: self._capture_axis_bound(p, "min"),
                                    bg_color="#555560", btn_width=90, btn_height=30,
                                    btn_font=(FONT_UI, 8, "bold"))
            max_btn = RoundedButton(btns, text="Set Max",
                                    command=lambda p=prefix: self._capture_axis_bound(p, "max"),
                                    bg_color="#555560", btn_width=90, btn_height=30,
                                    btn_font=(FONT_UI, 8, "bold"))
            min_btn.pack(side="left", padx=(0, 8))
            max_btn.pack(side="left", padx=(0, 8))

        status = tk.Label(left_col, text="Click a calibration button while holding the input position.",
                          bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9), anchor="w")
        status.pack(fill="x", pady=(12, 0))

        self._axis_widgets[prefix] = {
            "live": live,
            "cal": cal,
            "status": status,
            "min_lbl": min_lbl,
            "max_lbl": max_lbl,
            "monitor_panel": right_col,
            "monitor_btn": monitor_btn,
            "invert_check": invert_check,
        }
        if prefix == "whammy":
            self._axis_widgets[prefix]["rest_status"] = rest_status
            self._axis_widgets[prefix]["act_status"] = act_status
        elif prefix == "tilt":
            self._axis_widgets[prefix]["min_btn"] = min_btn
            self._axis_widgets[prefix]["max_btn"] = max_btn
            self._set_tilt_capture_enabled(not self._tilt_detecting)
            if mode == "i2c" and not self._tilt_detect_started:
                self._tilt_detect_started = True
                self.win.after(150, self._start_tilt_i2c_detect)
        self._set_axis_monitor_enabled(prefix, self._axis_quick_tuned.get(prefix, False))

    def _build_tilt_i2c_detect_row(self):
        row = tk.Frame(self._body, bg=BG_CARD)
        row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text="I2C Tilt:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9, "bold")).pack(side="left", padx=(0, 8))
        current = self._i2c_model_label()
        status = tk.Label(row, text=f"Using preset model: {current}", bg=BG_CARD,
                          fg=TEXT_DIM, font=(FONT_UI, 9))
        status.pack(side="left", padx=(0, 10))

        fallback = tk.Frame(row, bg=BG_CARD)
        model_var = tk.StringVar(value=current)
        combo = ttk.Combobox(fallback, state="readonly", width=18,
                             values=I2C_MODEL_LABELS, textvariable=model_var)
        combo.pack(side="left", padx=(0, 8))
        retry = RoundedButton(fallback, text="Retry Tilt Detect",
                              command=self._start_tilt_i2c_detect,
                              bg_color=ACCENT_BLUE, btn_width=135, btn_height=28,
                              btn_font=(FONT_UI, 8, "bold"))
        retry.pack(side="left")

        def on_model_selected(_event=None):
            idx = combo.current()
            if 0 <= idx < len(I2C_MODEL_VALUES):
                self.i2c_model.set(I2C_MODEL_VALUES[idx])
                status.config(text=f"Manual model: {self._i2c_model_label()}",
                              fg=ACCENT_ORANGE)

        combo.bind("<<ComboboxSelected>>", on_model_selected)
        self._tilt_detect_widgets = {
            "status": status,
            "fallback": fallback,
            "combo": combo,
            "retry": retry,
        }
        if self._tilt_detect_failed:
            status.config(text="No I2C chip detected. Select model manually.",
                          fg=ACCENT_ORANGE)
            self._set_tilt_fallback_visible(True)

    def _i2c_model_label(self):
        model = self.i2c_model.get()
        if model in I2C_MODEL_VALUES:
            return I2C_MODEL_LABELS[I2C_MODEL_VALUES.index(model)]
        return f"model {model}"

    def _set_tilt_capture_enabled(self, enabled):
        widgets = self._axis_widgets.get("tilt", {})
        state = "normal" if enabled else "disabled"
        for key in ("min_btn", "max_btn"):
            btn = widgets.get(key)
            if btn:
                btn.set_state(state)
        retry = self._tilt_detect_widgets.get("retry")
        if retry:
            retry.set_state(state)

    def _set_axis_monitor_enabled(self, prefix, enabled):
        widgets = self._axis_widgets.get(prefix, {})
        panel = widgets.get("monitor_panel")
        monitor_btn = widgets.get("monitor_btn")
        invert_check = widgets.get("invert_check")
        if panel:
            color = BG_CARD if enabled else "#2f2f35"
            border = BORDER if enabled else "#6a6a72"
            panel.configure(bg=color, highlightbackground=border)
            for child in panel.winfo_children():
                if isinstance(child, tk.Canvas):
                    try:
                        child.configure(bg=color)
                        if hasattr(child, "redraw"):
                            child.redraw()
                    except Exception:
                        pass
        if monitor_btn:
            monitor_btn.set_state("normal" if enabled else "disabled")
        if invert_check:
            invert_check.configure(state="normal" if enabled else "disabled")

    def _set_tilt_fallback_visible(self, visible):
        fallback = self._tilt_detect_widgets.get("fallback")
        if not fallback:
            return
        if visible:
            if not fallback.winfo_manager():
                fallback.pack(side="left")
            combo = self._tilt_detect_widgets.get("combo")
            if combo and self.i2c_model.get() in I2C_MODEL_VALUES:
                combo.current(I2C_MODEL_VALUES.index(self.i2c_model.get()))
        else:
            fallback.pack_forget()

    def _start_tilt_i2c_detect(self):
        if self.tilt_mode != "i2c" or self._tilt_detecting:
            return
        status = self._tilt_detect_widgets.get("status")
        if not self.pico.connected:
            if status:
                status.config(text="Controller is no longer connected.", fg=ACCENT_RED)
            self._tilt_detect_failed = True
            self._set_tilt_fallback_visible(True)
            return
        self._stop_monitoring()
        self._tilt_detecting = True
        self._tilt_detect_failed = False
        self._set_tilt_capture_enabled(False)
        self._set_tilt_fallback_visible(False)
        if status:
            status.config(text="Detecting I2C accelerometer...", fg=ACCENT_BLUE)

        def worker():
            lines = []
            error = None
            try:
                lines = self.pico.start_scan()
            except Exception as exc:
                error = str(exc)
            finally:
                try:
                    self.pico.request_stop_scan()
                except Exception:
                    pass
                try:
                    self.pico.flush_input()
                except Exception:
                    pass
            self.root.after(0, lambda: self._finish_tilt_i2c_detect(lines, error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_tilt_i2c_detect(self, lines, error):
        self._tilt_detecting = False
        status = self._tilt_detect_widgets.get("status")
        detected = None
        if not error:
            for line in lines or []:
                upper = str(line).upper()
                if upper.startswith("I2C:"):
                    if "LIS3DH" in upper:
                        detected = ("LIS3DH", 1)
                    elif "ADXL345" in upper:
                        detected = ("ADXL345", 0)
                    if detected:
                        break
        if detected:
            name, model = detected
            self.i2c_model.set(model)
            self._tilt_detect_failed = False
            self._set_tilt_fallback_visible(False)
            if status:
                status.config(text=f"Detected: {name}", fg=ACCENT_GREEN)
        else:
            self._tilt_detect_failed = True
            self._set_tilt_fallback_visible(True)
            message = f"Detect failed: {error}" if error else "No I2C chip detected. Select model manually."
            if status:
                status.config(text=message, fg=ACCENT_ORANGE)
        self._set_tilt_capture_enabled(True)
        self._fit_window_to_content()

    def _apply_axis_bound(self, prefix, which, raw):
        data = self._axis_values(prefix)
        raw = max(0, min(4095, int(raw)))
        if which == "min":
            raw = min(raw, data["max"].get() - 1)
            data["min"].set(raw)
        else:
            raw = max(raw, data["min"].get() + 1)
            data["max"].set(raw)

    def _capture_axis_bound(self, prefix, which):
        label = "minimum" if which == "min" else "maximum"
        self._capture_axis_value(
            prefix,
            lambda raw: self._finish_axis_bound(prefix, which, raw),
            f"Capturing {label} value..."
        )

    def _finish_axis_bound(self, prefix, which, raw):
        self._apply_axis_bound(prefix, which, raw)
        captured = self._axis_bound_captures.setdefault(prefix, set())
        captured.add(which)
        self._axis_quick_tuned[prefix] = {"min", "max"}.issubset(captured)
        self._refresh_axis_readout(prefix)
        self._set_axis_monitor_enabled(prefix, self._axis_quick_tuned[prefix])
        widgets = self._axis_widgets.get(prefix, {})
        status = widgets.get("status")
        if status:
            if self._axis_quick_tuned[prefix]:
                status.config(text=f"Captured {which}: {int(raw)}. Calibrated monitor is available.",
                              fg=ACCENT_GREEN)
            else:
                other = "max" if which == "min" else "min"
                status.config(text=f"Captured {which}: {int(raw)}. Capture {other} to unlock monitor.",
                              fg=TEXT_DIM)

    def _capture_whammy_position(self, position):
        label = "resting" if position == "rest" else "actuated"
        self._capture_axis_value(
            "whammy",
            lambda raw: self._finish_whammy_position(position, raw),
            f"Capturing whammy {label} position..."
        )

    def _finish_whammy_position(self, position, raw):
        raw = max(0, min(4095, int(raw)))
        widgets = self._axis_widgets.get("whammy", {})
        if position == "rest":
            self._whammy_rest_raw = raw
            label = widgets.get("rest_status")
            if label:
                label.config(text=f"Rest: {raw}", fg=ACCENT_GREEN)
        else:
            self._whammy_act_raw = raw
            label = widgets.get("act_status")
            if label:
                label.config(text=f"Actuated: {raw}", fg=ACCENT_GREEN)
        self._apply_whammy_guided_calibration()

    def _apply_whammy_guided_calibration(self):
        rest = self._whammy_rest_raw
        act = self._whammy_act_raw
        widgets = self._axis_widgets.get("whammy", {})
        status = widgets.get("status")
        if rest is None or act is None:
            if status:
                status.config(text="Capture both rest and actuated positions to update calibration.",
                              fg=TEXT_DIM)
            return
        if rest == act:
            if status:
                status.config(text="Rest and actuated readings matched. Move the whammy and try again.",
                              fg=ACCENT_ORANGE)
            return

        raw_range = abs(act - rest)
        deadzone = int(0.20 * raw_range)
        if rest <= act:
            new_min = max(0, rest + deadzone)
            new_max = min(4095, act)
            new_invert = False
        else:
            new_min = max(0, act)
            new_max = min(4095, rest - deadzone)
            new_invert = True
        if new_min >= new_max:
            new_min = max(0, new_max - 1)
        self.whammy_min.set(new_min)
        self.whammy_max.set(new_max)
        self.whammy_invert.set(new_invert)
        self._axis_quick_tuned["whammy"] = True
        self._refresh_axis_readout("whammy")
        self._set_axis_monitor_enabled("whammy", True)
        if status:
            status.config(text=f"Whammy calibrated from rest {rest} and actuated {act}.",
                          fg=ACCENT_GREEN)

    def _refresh_axis_readout(self, prefix):
        widgets = self._axis_widgets.get(prefix, {})
        data = self._axis_values(prefix)
        captured = self._axis_quick_tuned.get(prefix, False)
        min_lbl = widgets.get("min_lbl")
        max_lbl = widgets.get("max_lbl")
        try:
            if min_lbl and min_lbl.winfo_exists():
                min_lbl.config(text=f"Min: {data['min'].get()}" if captured else "Min: not set")
            if max_lbl and max_lbl.winfo_exists():
                max_lbl.config(text=f"Max: {data['max'].get()}" if captured else "Max: not set")
        except tk.TclError:
            pass

    def _capture_axis_value(self, prefix, on_value, status_text):
        if self._capture_in_progress:
            return
        if not self.pico.connected:
            messagebox.showerror("Quick Tune", "Controller is no longer connected.")
            return
        self._stop_monitoring()
        data = self._axis_values(prefix)
        mode = data["mode"]
        pin = data["pin"]
        widgets = self._axis_widgets.get(prefix, {})
        status = widgets.get("status")
        if status:
            status.config(text=status_text, fg=ACCENT_BLUE)
        widgets.get("cal") and widgets["cal"].reset_ema()
        self._capture_in_progress = True

        def worker():
            value = None
            error = None
            try:
                if prefix == "tilt" and mode == "i2c":
                    self.pico.set_value("tilt_mode", "i2c")
                    self.pico.set_value("i2c_model", str(self.i2c_model.get()))
                    self.pico.set_value("adxl345_axis", str(self.tilt_axis))
                    self.pico.start_monitor_i2c(axis=self.tilt_axis)
                elif mode == "analog" and pin >= 0:
                    self.pico.start_monitor_adc(pin)
                else:
                    raise ValueError("This input is not an analog axis.")
                deadline = time.time() + 0.8
                while time.time() < deadline:
                    latest, _others = self.pico.drain_monitor_latest(0.05)
                    if latest is not None:
                        value = int(latest)
                if value is None:
                    error = "No live input value was received."
            except Exception as exc:
                error = str(exc)
            finally:
                try:
                    self.pico.request_stop_monitor()
                except Exception:
                    pass
                try:
                    self.pico.flush_input()
                except Exception:
                    pass
            self.root.after(0, lambda: self._finish_axis_capture(prefix, on_value, value, error))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_axis_monitor(self, prefix):
        if not self._axis_quick_tuned.get(prefix, False):
            return
        if self._monitoring and self._monitor_prefix == prefix:
            self._stop_monitoring()
            return
        self._stop_monitoring()
        self._start_axis_monitor(prefix)

    def _start_axis_monitor(self, prefix):
        if not self.pico.connected:
            messagebox.showerror("Quick Tune", "Controller is no longer connected.")
            return
        data = self._axis_values(prefix)
        mode = data["mode"]
        pin = data["pin"]
        widgets = self._axis_widgets.get(prefix, {})
        status = widgets.get("status")
        monitor_btn = widgets.get("monitor_btn")
        if status:
            status.config(text=f"Monitoring calibrated {data['label'].lower()} output...",
                          fg=ACCENT_BLUE)
        if monitor_btn:
            monitor_btn._label = "Stop Check"
            monitor_btn._bg = ACCENT_RED
            monitor_btn._render(ACCENT_RED)
        widgets.get("cal") and widgets["cal"].reset_ema()
        self._monitoring = True
        self._monitor_prefix = prefix

        def worker():
            try:
                if prefix == "tilt" and mode == "i2c":
                    self.pico.set_value("tilt_mode", "i2c")
                    self.pico.set_value("i2c_model", str(self.i2c_model.get()))
                    self.pico.set_value("adxl345_axis", str(self.tilt_axis))
                    self.pico.start_monitor_i2c(axis=self.tilt_axis)
                elif mode == "analog" and pin >= 0:
                    self.pico.start_monitor_adc(pin)
                else:
                    raise ValueError("This input is not an analog axis.")
                while self._monitoring and self._monitor_prefix == prefix:
                    value, _others = self.pico.drain_monitor_latest(0.05)
                    if value is not None:
                        self.root.after(0, lambda v=value, p=prefix: self._update_axis_value(p, v))
            except Exception as exc:
                self.root.after(0, lambda msg=str(exc): self._monitor_error(msg))

        self._monitor_thread = threading.Thread(target=worker, daemon=True)
        self._monitor_thread.start()

    def _finish_axis_capture(self, prefix, on_value, value, error):
        self._capture_in_progress = False
        widgets = self._axis_widgets.get(prefix, {})
        status = widgets.get("status")
        if error:
            if status:
                status.config(text=f"Capture failed: {error}", fg=ACCENT_RED)
            return
        self._update_axis_value(prefix, value)
        on_value(value)

    def _update_axis_value(self, prefix, value):
        self._latest_raw[prefix] = int(value)
        widgets = self._axis_widgets.get(prefix, {})
        if "live" in widgets:
            widgets["live"].set_value(value)
        if "cal" in widgets:
            widgets["cal"].set_raw(value)

    def _monitor_error(self, message):
        self._stop_monitoring()
        messagebox.showerror("Quick Tune Monitor", message)

    def _stop_monitoring(self):
        if not self._monitoring:
            return
        prefix = self._monitor_prefix
        self._monitoring = False
        try:
            self.pico.request_stop_monitor()
        except Exception:
            pass
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=0.4)
        try:
            self.pico.flush_input()
        except Exception:
            pass
        widgets = self._axis_widgets.get(prefix, {})
        status = widgets.get("status")
        monitor_btn = widgets.get("monitor_btn")
        if monitor_btn:
            label = "Check Whammy" if prefix == "whammy" else "Check Tilt"
            monitor_btn._label = label
            monitor_btn._bg = ACCENT_BLUE
            monitor_btn._render(ACCENT_BLUE)
        if status:
            status.config(text="Monitoring stopped.", fg=TEXT_DIM)
        self._monitor_prefix = None
        self._monitor_thread = None

    def _build_led_page(self):
        summary = "LEDs enabled" if self.led_enabled else "LEDs disabled"
        columns = tk.Frame(self._body, bg=BG_CARD)
        columns.pack(fill="both", expand=True)
        left = tk.Frame(columns, bg=BG_CARD)
        right = tk.Frame(columns, bg=BG_CARD)
        left.pack(side="left", fill="x", expand=True, anchor="n", padx=(0, 18))
        right.pack(side="left", fill="x", expand=True, anchor="n")
        tk.Label(left, text=f"{summary}   Count: {self.led_count}",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 12))

        if self.led_count <= 0:
            tk.Label(left, text="This preset has no LEDs to tune.",
                     bg=BG_CARD, fg=ACCENT_ORANGE, font=(FONT_UI, 10)).pack(anchor="w", pady=18)
        else:
            colors_frame = tk.Frame(left, bg=BG_CARD)
            colors_frame.pack(fill="x")
            tk.Label(colors_frame, text="LED Colors",
                     bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 4))
            grid = tk.Frame(colors_frame, bg=BG_CARD)
            grid.pack(anchor="w")
            for idx in range(min(self.led_count, MAX_LEDS)):
                cell = tk.Frame(grid, bg=BG_CARD)
                cell.grid(row=idx // 3, column=idx % 3, sticky="w", padx=(0, 10), pady=5)
                tk.Label(cell, text=f"LED {idx + 1}", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 7), width=5, anchor="w").pack(side="left")
                swatch = tk.Canvas(cell, width=22, height=20, bg=BG_CARD,
                                   highlightbackground=BORDER, highlightthickness=1, bd=0,
                                   cursor="hand2")
                swatch.pack(side="left")
                self._paint_swatch(swatch, self.led_colors[idx])
                swatch.bind("<Button-1>", lambda _e, i=idx, c=swatch: self._pick_led_color(i, c))

        tk.Label(right, text="LED Effects", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8, "bold")).grid(row=0, column=0, columnspan=6,
                                                  sticky="w", pady=(0, 4))

        max_led = max(1, min(self.led_count, MAX_LEDS))
        self._build_effect_row(
            right, 1, self.led_loop_enabled, "Enable LED Color Loop",
            (("From LED:", self.led_loop_start, 1, max_led),
             ("To LED:", self.led_loop_end, 1, max_led)),
        )
        self._build_effect_row(
            right, 4, self.led_breathe_enabled, "Enable LED Breathe",
            (("From LED:", self.led_breathe_start, 1, max_led),
             ("To LED:", self.led_breathe_end, 1, max_led),
             ("Min:", self.led_breathe_min, 0, 31),
             ("Max:", self.led_breathe_max, 0, 31)),
        )
        self._build_effect_row(
            right, 8, self.led_wave_enabled, "Enable LED Ripple",
            (("Origin LED:", self.led_wave_origin, 1, max_led),),
        )
        ttk.Checkbutton(right, text="Reactive LEDs on keypress",
                        variable=self.led_reactive,
                        command=self._on_reactive_toggle).grid(
                            row=11, column=0, columnspan=6, sticky="w", pady=(8, 0))

    def _build_effect_row(self, parent, row, enabled_var, label, fields):
        ttk.Checkbutton(parent, text=label, variable=enabled_var).grid(
            row=row, column=0, columnspan=6, sticky="w", pady=(0, 2))
        for col, (field_label, var, low, high) in enumerate(fields):
            label_col = (col % 2) * 3
            field_row = row + 1 + (col // 2)
            tk.Label(parent, text=field_label, bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8), anchor="e", width=10).grid(
                         row=field_row, column=label_col, sticky="e", padx=(0, 4), pady=1)
            spin = ttk.Spinbox(parent, from_=low, to=high, width=5, textvariable=var)
            spin.grid(row=field_row, column=label_col + 1, sticky="w", padx=(0, 8), pady=1)
        tk.Frame(parent, bg=BORDER, height=1).grid(
            row=row + 2 + ((len(fields) - 1) // 2), column=0, columnspan=6,
            sticky="ew", pady=(6, 6))

    def _paint_swatch(self, swatch, color):
        swatch.delete("all")
        swatch.create_rectangle(3, 3, 19, 17, fill=f"#{_clean_color(color)}", outline="")

    def _pick_led_color(self, index, swatch):
        initial = f"#{self.led_colors[index]}"
        _rgb, hex_color = colorchooser.askcolor(initialcolor=initial, parent=self.win,
                                                title=f"LED {index + 1} Color")
        if not hex_color:
            return
        self.led_colors[index] = _clean_color(hex_color)
        self._paint_swatch(swatch, self.led_colors[index])

    def _default_reactive_maps(self):
        count = min(self.led_count, MAX_LEDS)
        maps = []
        for idx in range(len(self.led_input_names)):
            maps.append((1 << idx) if idx < count and idx < 16 else 0)
        return maps

    def _on_reactive_toggle(self):
        if self.led_reactive.get():
            restored = list(self._reactive_backup)
            if not any(restored):
                restored = self._default_reactive_maps()
            self.led_maps = restored
        else:
            if any(self.led_maps):
                self._reactive_backup = list(self.led_maps)
            self.led_maps = [0] * len(self.led_maps)

    def _save_and_reboot(self):
        self._stop_monitoring()
        self._next_btn.set_state("disabled")
        try:
            required = []
            if self.whammy_mode == "analog" and self.whammy_pin >= 0 and not self._axis_quick_tuned.get("whammy"):
                required.append("Whammy")
            if ((self.tilt_mode == "analog" and self.tilt_pin >= 0) or self.tilt_mode == "i2c") and not self._axis_quick_tuned.get("tilt"):
                required.append("Tilt")
            if required:
                self._next_btn.set_state("normal")
                messagebox.showwarning(
                    "Quick Tune",
                    "Please calibrate these inputs before saving:\n" + "\n".join(required)
                )
                return
            self.pico.flush_input()
            self.pico.set_value("whammy_min", str(self.whammy_min.get()))
            self.pico.set_value("whammy_max", str(self.whammy_max.get()))
            self.pico.set_value("whammy_invert", "1" if self.whammy_invert.get() else "0")
            self.pico.set_value("tilt_min", str(self.tilt_min.get()))
            self.pico.set_value("tilt_max", str(self.tilt_max.get()))
            self.pico.set_value("tilt_invert", "1" if self.tilt_invert.get() else "0")
            if self.tilt_mode == "i2c":
                self.pico.set_value("i2c_model", str(self.i2c_model.get()))

            for idx in range(min(self.led_count, MAX_LEDS)):
                self.pico.set_value(f"led_color_{idx}", _clean_color(self.led_colors[idx]))
            self.pico.set_value("led_loop_enabled", "1" if self.led_loop_enabled.get() else "0")
            self.pico.set_value("led_loop_start", str(self.led_loop_start.get() - 1))
            self.pico.set_value("led_loop_end", str(self.led_loop_end.get() - 1))
            self.pico.set_value("led_breathe_enabled", "1" if self.led_breathe_enabled.get() else "0")
            self.pico.set_value("led_breathe_start", str(self.led_breathe_start.get() - 1))
            self.pico.set_value("led_breathe_end", str(self.led_breathe_end.get() - 1))
            self.pico.set_value("led_breathe_min", str(self.led_breathe_min.get()))
            self.pico.set_value("led_breathe_max", str(self.led_breathe_max.get()))
            self.pico.set_value("led_wave_enabled", "1" if self.led_wave_enabled.get() else "0")
            self.pico.set_value("led_wave_origin", str(self.led_wave_origin.get() - 1))
            for idx, mask in enumerate(self.led_maps):
                self.pico.set_value(f"led_map_{idx}", f"{int(mask):04X}")
            for idx, brightness in enumerate(self.led_active_br):
                self.pico.set_value(f"led_active_{idx}", str(_as_int(brightness, 23, 0, 31)))

            self.pico.save()
            time.sleep(0.1)
            self.pico.reboot()
            self.pico.disconnect()
            self.saved = True
            try:
                self.win.grab_release()
            except Exception:
                pass
            self.win.destroy()
        except Exception as exc:
            self._next_btn.set_state("normal")
            messagebox.showerror("Quick Tune Save", f"Could not save Quick Tune settings:\n{exc}")
