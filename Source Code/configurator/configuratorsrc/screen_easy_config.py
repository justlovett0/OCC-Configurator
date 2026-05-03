import sys, os, time, threading, datetime, json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .constants import (BG_MAIN, BG_CARD, BG_INPUT, BG_HOVER, BORDER, TEXT, TEXT_DIM,
                         TEXT_HEADER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
                         FRET_COLORS, DIGITAL_PINS, DIGITAL_PIN_LABELS, ANALOG_PINS,
                         ANALOG_PIN_LABELS, I2C0_SDA_PINS, I2C0_SCL_PINS, I2C_SDA_LABELS,
                         I2C_SCL_LABELS, I2C_MODEL_LABELS, I2C_MODEL_VALUES,
                         MAX_LEDS, LED_INPUT_COUNT, LED_INPUT_NAMES, LED_INPUT_LABELS,
                         VALID_NAME_CHARS, BAUD_RATE)
from .fonts import FONT_UI, _resource_path
from .widgets import (RoundedButton, HelpButton, HelpDialog, CustomDropdown,
                       LiveBarGraph, LiveBarGraphVertical, CalibratedBarGraph,
                       _help_text)
from .serial_comms import PicoSerial
from .utils import _centered_dialog, _center_window, _find_preset_configs
from .firmware_utils import enter_bootsel_for
#  EASY CONFIGURATION SCREEN  — step-by-step walkthrough (17 pages)


# ─────────────────────────────────────────────────────────────────────────────
#  BUTTON GIF ANIMATION  (used on applicable EasyConfigScreen pages)
#
#  Loads a single animated GIF from the buttons\ subfolder and loops it on a
#  tk.Canvas, respecting each frame's own duration from the GIF metadata.
#  Requires Pillow.  If Pillow is missing or the file is not found the canvas
#  stays blank — no crash.
# ─────────────────────────────────────────────────────────────────────────────

_BTN_DISP_W = 90   # canvas display width  (px)
_BTN_DISP_H = 70   # canvas display height (px) — matches 4:3 source GIFs
_BTN_FALLBACK_MS = 70  # frame delay used when GIF metadata has no duration

class _GifAnim:
    """
    Loops a single animated GIF on a tk.Canvas.

    Reads per-frame durations directly from the GIF so playback speed is
    exactly what the artist intended.  All PIL work (decode + resize) runs
    once in __init__; the tick loop only swaps pre-built PhotoImages.

    Usage:
        anim = _GifAnim(root, canvas, gif_path)
        anim.start()   # begin looping
        anim.stop()    # cancel — call before navigating away from the page
    """

    def __init__(self, root, canvas, gif_path,
                 disp_w=_BTN_DISP_W, disp_h=_BTN_DISP_H):
        self.root      = root
        self.canvas    = canvas
        self._running  = False
        self._after_id = None
        self._frames   = []   # list of (PhotoImage, delay_ms)
        self._idx      = 0

        try:
            self._frames = self._load(gif_path, disp_w, disp_h)
        except Exception as exc:
            print(f"[GifAnim] failed to load {gif_path}: {exc}")

    def _load(self, path, dw, dh):
        from PIL import Image, ImageTk, ImageSequence
        frames = []
        with Image.open(path) as src:
            for frame in ImageSequence.Iterator(src):
                delay = frame.info.get("duration", _BTN_FALLBACK_MS)
                delay = max(delay, 20)   # clamp — avoid runaway 0-ms frames
                img = frame.convert("RGBA").resize((dw, dh), Image.LANCZOS)
                frames.append((ImageTk.PhotoImage(img), delay))
        return frames

    def start(self):
        if not self._frames:
            return
        self._running = True
        self._idx = 0
        self._tick()

    def stop(self):
        self._running = False
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _tick(self):
        if not self._running or not self._frames:
            return
        photo, delay = self._frames[self._idx]
        cw = self.canvas.winfo_width()  or _BTN_DISP_W
        ch = self.canvas.winfo_height() or _BTN_DISP_H
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=photo, anchor="center")
        self.canvas._cur = photo          # prevent garbage collection
        self._idx = (self._idx + 1) % len(self._frames)
        self._after_id = self.root.after(delay, self._tick)


class EasyConfigScreen:
    """
    Step-by-step walkthrough configuration screen.

    17 pages:
      0–8   — individual button bindings (digital GPIO 0–22)
      9     — D-Pad (4 directions, one page)
      10–11 — joystick axes (digital or analog)
      12    — Guide button / joystick click (digital)
      13    — Whammy bar (digital or analog)
      14    — Tilt sensor (digital, analog, or I2C)
      15–16 — LED configuration and Review & Save (placeholders)
    """

    # ── Page definitions ─────────────────────────────────────────
    # (page_type, config_key, display_name, accent_color, category_label)
    PAGE_DEFS = [
        ("digital",     "green",      "Green Fret",                    "#2ecc71",  "Button Binding"),
        ("digital",     "red",        "Red Fret",                      "#e74c3c",  "Button Binding"),
        ("digital",     "yellow",     "Yellow Fret",                   "#f1c40f",  "Button Binding"),
        ("digital",     "blue",       "Blue Fret",                     "#3498db",  "Button Binding"),
        ("digital",     "orange",     "Orange Fret",                   "#e67e22",  "Button Binding"),
        ("digital",     "strum_up",   "Strum Up",                      ACCENT_BLUE, "Button Binding"),
        ("digital",     "strum_down", "Strum Down",                    ACCENT_BLUE, "Button Binding"),
        ("digital",     "start",      "Start Button",                  ACCENT_BLUE, "Button Binding"),
        ("digital",     "select",     "Select / Star Power",           ACCENT_BLUE, "Button Binding"),
        ("dpad",        None,         "D-Pad",                         ACCENT_BLUE, "Button Binding"),
        ("joy_axis",    "joy_x",      "Joystick \u2014 Left / Right Axis", ACCENT_BLUE, "Joystick Binding"),
        ("joy_axis",    "joy_y",      "Joystick \u2014 Up / Down Axis",    ACCENT_BLUE, "Joystick Binding"),
        ("digital",     "joy_sw",     "Guide Button (Joystick Click)", ACCENT_BLUE, "Button Binding"),
        ("whammy",      "whammy",     "Whammy Bar",                    ACCENT_BLUE, "Analog Input"),
        ("tilt",        "tilt",       "Tilt Sensor",                   ACCENT_BLUE, "Analog Input"),
        ("led",         None,         "LED Configuration",             ACCENT_BLUE, "LED Setup"),
        ("placeholder", None,         "Review & Save",                 ACCENT_BLUE, "Finishing Up"),
    ]

    _PIN_KEY_TO_LABEL = {
        "green": "Green Fret",
        "red": "Red Fret",
        "yellow": "Yellow Fret",
        "blue": "Blue Fret",
        "orange": "Orange Fret",
        "strum_up": "Strum Up",
        "strum_down": "Strum Down",
        "start": "Start Button",
        "select": "Select / Star Power",
        "dpad_up": "D-Pad Up",
        "dpad_right": "D-Pad Right",
        "dpad_down": "D-Pad Down",
        "dpad_left": "D-Pad Left",
        "joy_x": "Joystick — Left / Right Axis",
        "joy_y": "Joystick — Up / Down Axis",
        "joy_sw": "Guide Button (Joystick Click)",
        "whammy_pin": "Whammy Bar",
        "tilt_pin": "Tilt Sensor",
    }

    _PIN_KEY_TO_PAGE = {
        "green": 0,
        "red": 1,
        "yellow": 2,
        "blue": 3,
        "orange": 4,
        "strum_up": 5,
        "strum_down": 6,
        "start": 7,
        "select": 8,
        "dpad_up": 9,
        "dpad_right": 9,
        "dpad_down": 9,
        "dpad_left": 9,
        "joy_x": 10,
        "joy_y": 11,
        "joy_sw": 12,
        "whammy_pin": 13,
        "tilt_pin": 14,
    }

    _PIN_ASSIGNMENT_KEYS = (
        "green", "red", "yellow", "blue", "orange",
        "strum_up", "strum_down", "start", "select",
        "dpad_up", "dpad_right", "dpad_down", "dpad_left",
        "joy_x", "joy_y", "joy_sw",
        "whammy_pin", "tilt_pin",
    )

    def __init__(self, root, on_back=None):
        self.root = root
        self._on_back = on_back
        self._current_page = 0
        self._page_token = 0

        # Serial connection
        self.pico = PicoSerial()

        # Scan / monitor state
        self.scanning = False
        self.scan_target = None
        self._monitoring = False
        self._monitor_thread = None
        self._preview_active = False
        self._preview_seen = {}
        self._help_dialog = None
        self._auto_detect_after_id = None
        self._scan_timeout_after_id = None
        self._page_detection_reset = None
        self._override_origin_page = None
        self._override_repair_page = None
        self._override_return_page = None
        self._override_repair_key = None

        # Detected values persist across page navigation
        # Keys match firmware config keys: green, red, ..., dpad_up, joy_x, whammy_pin, tilt_pin …
        self.detected = {}

        self.frame = tk.Frame(root, bg=BG_MAIN)
        self._build()

    # ── Serial connection ─────────────────────────────────────────

    def _connect_serial(self, port):
        """Called by main() after the XInput magic sequence completes."""
        try:
            self.pico.connect(port)
            for _ in range(3):
                if self.pico.ping():
                    return
                time.sleep(0.3)
            self.pico.disconnect()
        except Exception:
            pass

    def _open_help(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self.root, [
                ("Overview",        _help_text(
                    ("This is the easy configurator for guitar controllers.", None),
                    ("It will walk you through step by step on mapping buttons for your controller.", None),
                    ("Click the BIG BOX that says \"Click here to start Input Detection\" to start input detection if not already started.", None),
                    ("\n\n", None),
                    ("Pressed the wrong button?", "bold"),
                    ("\n\n", None),
                    ("Simply click the detection box again and re-press the button.", None),
                    ("You can click \"<-- Go Back\" to go back pages.", None),
                    ("\n\n", None),
                    ("Clicking \"Back to Menu\" will not save your button presses, and the controller will revert to previous configuration.", None),
                )),
                ("Button Detection", _help_text(
                    ("Button detection is automatic. You can always go back and re-do button inputs if needed.", None),
                    ("\n\n", None),
                    ("On guitars, the only required buttons are Frets, Strum Up/Down, and Start button.", None),
                    ("You don't NEED to map those buttons in the advanced configurator, it is only a requirement in the easy configurator.", None),
                )),
                ("Analog Inputs",   _help_text(
                    ("Some buttons, such as Joystick, Whammy, Tilt, could be digital or analog inputs.", None),
                    ("An analog input is on the uppermost GPIO pins of the Pi.", None),
                    ("\n\n", None),
                    ("Mapping an analog input could need input inversion, so check the \"Invert\" box to invert the controller output.", None),
                    ("\n\n", None),
                    ("Mapping an analog input could need calibration for at rest and at full actuation.", None),
                    ("\"Set Min\" is to set your analog input at rest.", None),
                    ("\"Set Max\" is to set your analog input at full actuation. (Tilted all the way up, or Whammy pressed all the way in)", None),
                    ("The Calibrated output will show you the new output, what the game will use, according to your min and max values.", None),
                )),
                ("Review & Save",   _help_text(
                    ("The Review and Save section is in beta, but will attempt to show you some basic inputs from your controller live.", None),
                    ("\n\n", None),
                    ("Feel free to export your controller configuration for later if you ever reset it and want to import it later. (From advanced configuration tab)", None),
                    ("\n\n", None),
                    ("\"Wireless Dongle\" mode is for your wireless controller to default to connecting to an OCC Dongle.", None),
                    ("\"Wireless Bluetooth\" mode is for your wireless controller to default to standard BT connections.", None),
                )),
            ])
        self._help_dialog.open()

    # ── Static layout (built once) ────────────────────────────────

    def _build(self):
        # Title bar
        title_bar = tk.Frame(self.frame, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        title_bar.pack(fill="x")
        inner_title = tk.Frame(title_bar, bg=BG_CARD)
        inner_title.pack(fill="x", padx=24, pady=16)
        HelpButton(inner_title, command=self._open_help).pack(side="right", anchor="n", pady=4)
        tk.Label(inner_title, text="OCC", bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 18, "bold")).pack(anchor="w")
        tk.Label(inner_title, text="Easy Configuration \u2014 Step-by-Step Walkthrough",
                 bg=BG_CARD, fg=ACCENT_BLUE, font=(FONT_UI, 13)).pack(anchor="w")

        # Progress bar
        prog_frame = tk.Frame(self.frame, bg=BG_MAIN)
        prog_frame.pack(fill="x", padx=60, pady=(20, 0))
        self._progress_canvas = tk.Canvas(prog_frame, height=8, bg=BG_INPUT,
                                          highlightthickness=0, bd=0)
        self._progress_canvas.pack(fill="x")
        self._prog_label = tk.Label(prog_frame, text="", bg=BG_MAIN, fg=TEXT_DIM,
                                    font=(FONT_UI, 8))
        self._prog_label.pack(anchor="e", pady=(4, 0))

        # Center column
        self._center = tk.Frame(self.frame, bg=BG_MAIN)
        self._center.pack(expand=True, fill="both", padx=60, pady=(16, 0))

        # Content card
        content_card = tk.Frame(self._center, bg=BG_CARD,
                                highlightbackground=BORDER, highlightthickness=1)
        content_card.pack(fill="both", expand=True, pady=(0, 16))

        # Page header — left: text labels, right: strumbar animation canvas
        hdr_frame = tk.Frame(content_card, bg=BG_CARD)
        hdr_frame.pack(fill="x", padx=28, pady=(24, 4))

        # Animation canvas — always present, only populated on pages 5 & 6
        self._strum_canvas = tk.Canvas(
            hdr_frame, width=_BTN_DISP_W, height=_BTN_DISP_H,
            bg=BG_CARD, highlightthickness=0, bd=0)
        self._strum_canvas.pack(side="right", padx=(16, 0))
        self._strum_anim = None   # _StrumbarAnim instance; set per page

        # Text column (title + subtitle)
        text_col = tk.Frame(hdr_frame, bg=BG_CARD)
        text_col.pack(side="left", fill="both", expand=True)
        self._page_title_lbl = tk.Label(text_col, text="", bg=BG_CARD, fg=TEXT_HEADER,
                                         font=(FONT_UI, 20, "bold"), anchor="w")
        self._page_title_lbl.pack(anchor="w")
        self._page_sub_lbl = tk.Label(text_col, text="", bg=BG_CARD, fg=ACCENT_BLUE,
                                       font=(FONT_UI, 10), anchor="w")
        self._page_sub_lbl.pack(anchor="w", pady=(2, 0))

        # Separator
        tk.Frame(content_card, bg=BORDER, height=1).pack(fill="x", padx=28, pady=(12, 0))

        # Body — cleared and rebuilt on every page change
        self._body_frame = tk.Frame(content_card, bg=BG_CARD)
        self._body_frame.pack(fill="both", expand=True, padx=28, pady=20)

        # Navigation row
        nav_frame = tk.Frame(self._center, bg=BG_MAIN)
        nav_frame.pack(fill="x", pady=(0, 20))
        self._back_btn = RoundedButton(nav_frame, text="\u2190 Back to Menu",
                                       command=self._go_back, bg_color=BG_INPUT,
                                       btn_width=160, btn_height=36)
        self._back_btn.pack(side="left")
        self._prev_btn = RoundedButton(nav_frame, text="\u2190 Go Back",
                                       command=self._prev_page, bg_color=BG_INPUT,
                                       btn_width=120, btn_height=36)
        self._prev_btn.pack(side="left", padx=(10, 0))
        self._skip_btn = RoundedButton(nav_frame, text="Skip to next screen \u2192",
                                       command=self._next_page, bg_color=ACCENT_BLUE,
                                       btn_width=215, btn_height=36)
        self._skip_btn.pack(side="right")

    # ── Page management ───────────────────────────────────────────

    def _show_page(self, idx):
        self._stop_scan_and_monitor(reset_detection_ui=True)
        self._current_page = idx
        self._page_token += 1
        self._page_detection_reset = None

        # Rebuild body
        for w in self._body_frame.winfo_children():
            w.destroy()

        ptype, key, name, accent, category = self.PAGE_DEFS[idx]
        total = len(self.PAGE_DEFS)

        # Header text
        self._page_title_lbl.config(text=name)
        self._page_sub_lbl.config(text=f"{category}  \u00b7  Page {idx + 1} of {total}")

        # Progress bar
        fraction = (idx + 1) / total
        self._progress_canvas.update_idletasks()
        bar_w = self._progress_canvas.winfo_width() or 1060
        fill_w = max(8, int(bar_w * fraction))
        self._progress_canvas.delete("all")
        self._progress_canvas.create_rectangle(0, 0, bar_w, 8, fill=BG_INPUT, outline="")
        self._progress_canvas.create_rectangle(0, 0, fill_w, 8, fill=ACCENT_BLUE, outline="")
        self._prog_label.config(text=f"Step {idx + 1} of {total}")

        # ── Strumbar animation — page 5 = Strum Up, page 6 = Strum Down ──
        # Stop any animation that was running on the previous page
        if getattr(self, '_strum_anim', None):
            self._strum_anim.stop()
            self._strum_anim = None
        self._strum_canvas.delete("all")

        # Map PAGE_DEFS index → GIF filename in the buttons\ subfolder.
        # Pages with no entry get a blank canvas.
        _PAGE_GIFS = {
            0:  "green_fret.gif",       # Green Fret
            1:  "red_fret.gif",         # Red Fret
            2:  "yellow_fret.gif",      # Yellow Fret
            3:  "blue_fret.gif",        # Blue Fret
            4:  "orange_fret.gif",      # Orange Fret
            5:  "strumbar_up.gif",      # Strum Up
            6:  "strumbar_down.gif",    # Strum Down
            7:  "start_button.gif",     # Start Button
            8:  "select_button.gif",    # Select / Star Power
            9:  "dpad.gif",             # D-Pad
            13: "whammy.gif",           # Whammy Bar
        }

        gif_name = _PAGE_GIFS.get(idx)
        if gif_name:
            gif_path = _resource_path("buttons", gif_name)
            if os.path.isfile(gif_path):
                self._strum_anim = _GifAnim(self.root, self._strum_canvas, gif_path)
                self._strum_anim.start()

        # Skip / Finish button label
        if idx == total - 1:
            self._skip_btn._label = "Finish & Return to Menu"
        else:
            self._skip_btn._label = "Skip to next screen \u2192"
        self._skip_btn._render(self._skip_btn._bg)

        # Go Back button — disabled on first page
        self._prev_btn.set_state("disabled" if idx == 0 else "normal")

        # Dispatch to page builder
        if ptype == "digital":
            self._build_digital_content(key, name, accent)
        elif ptype == "dpad":
            self._build_dpad_content()
        elif ptype == "joy_axis":
            self._build_joy_axis_content(key, name)
        elif ptype == "whammy":
            self._build_whammy_content()
        elif ptype == "tilt":
            self._build_tilt_content()
        elif ptype == "led":
            self._build_led_content()
        else:
            self._build_placeholder_content(name)

    def _cancel_detection_jobs(self):
        """Cancel any delayed auto-start or timeout callback for the current page."""
        if self._auto_detect_after_id is not None:
            try:
                self.root.after_cancel(self._auto_detect_after_id)
            except Exception:
                pass
            self._auto_detect_after_id = None
        if self._scan_timeout_after_id is not None:
            try:
                self.root.after_cancel(self._scan_timeout_after_id)
            except Exception:
                pass
            self._scan_timeout_after_id = None

    def _schedule_auto_detect(self, callback, delay_ms=75):
        self._cancel_detection_jobs()
        def _run():
            self._auto_detect_after_id = None
            callback()
        self._auto_detect_after_id = self.root.after(delay_ms, _run)

    def _start_scan_timeout(self, callback, timeout_ms=10000):
        if self._scan_timeout_after_id is not None:
            try:
                self.root.after_cancel(self._scan_timeout_after_id)
            except Exception:
                pass
        def _run():
            self._scan_timeout_after_id = None
            callback()
        self._scan_timeout_after_id = self.root.after(timeout_ms, _run)

    def _clear_scan_timeout(self):
        if self._scan_timeout_after_id is not None:
            try:
                self.root.after_cancel(self._scan_timeout_after_id)
            except Exception:
                pass
            self._scan_timeout_after_id = None

    def _stop_scan_and_monitor(self, reset_detection_ui=False):
        """Stop any active scan or monitor thread safely."""
        self._cancel_detection_jobs()
        need_stop_scan = self.scanning or self._preview_active
        self.scanning = False
        self._preview_active = False
        if need_stop_scan:
            self._request_stop_scan()
        if self._monitoring:
            self._monitoring = False
            self._request_stop_monitor()
        if reset_detection_ui and callable(self._page_detection_reset):
            try:
                self._page_detection_reset()
            except Exception:
                pass
        if reset_detection_ui:
            self._page_detection_reset = None

    def _request_stop_scan(self):
        try:
            if hasattr(self.pico, "request_stop_scan"):
                self.pico.request_stop_scan()
            else:
                self.pico.stop_scan()
        except Exception:
            pass

    def _request_stop_monitor(self):
        try:
            if hasattr(self.pico, "request_stop_monitor"):
                self.pico.request_stop_monitor()
            elif hasattr(self.pico, "request_stop_scan"):
                self.pico.request_stop_scan()
            else:
                self.pico.stop_monitor()
        except Exception:
            pass

    def _page_is_active(self, token, *widgets):
        if token != self._page_token:
            return False
        for widget in widgets:
            try:
                if not widget.winfo_exists():
                    return False
            except Exception:
                return False
        return True

    def _clear_override_flow(self):
        self._override_origin_page = None
        self._override_repair_page = None
        self._override_return_page = None
        self._override_repair_key = None

    def _reset_easy_config_state(self):
        self.detected.clear()
        self._clear_override_flow()

    def _get_pin_input_label(self, pin_key):
        return self._PIN_KEY_TO_LABEL.get(pin_key, pin_key)

    def _get_pin_input_page(self, pin_key):
        return self._PIN_KEY_TO_PAGE.get(pin_key)

    def _clear_detected_pin(self, pin_key):
        self.detected.pop(pin_key, None)

    def _find_existing_pin_assignment(self, pin, current_key):
        for key in self._PIN_ASSIGNMENT_KEYS:
            if key == current_key:
                continue
            existing_pin = self.detected.get(key)
            if existing_pin == pin:
                return key
        return None

    def _show_duplicate_override_dialog(self, pin, existing_key, same_page=False):
        dlg = tk.Toplevel(self.root)
        dlg.title("GPIO Already Mapped")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)

        existing_label = self._get_pin_input_label(existing_key)
        followup = ("(Will keep Easy Configurator on this page so you can rebind it.)"
                    if same_page else
                    f"(Will set Easy Configurator back to {existing_label} page)")
        msg = (f"GPIO {pin} has already been mapped to {existing_label}. "
               f"Do you want to override {existing_label}'s GPIO pin?\n{followup}")
        tk.Label(dlg, text=msg, bg=BG_CARD, fg=TEXT, font=(FONT_UI, 10),
                 justify="center", padx=28, pady=20, wraplength=420).pack()

        result = [False]
        btn_f = tk.Frame(dlg, bg=BG_CARD, pady=10)
        btn_f.pack()

        def _override():
            result[0] = True
            dlg.destroy()

        RoundedButton(btn_f, text="Cancel", bg_color=BG_INPUT,
                      btn_width=110, btn_height=30,
                      command=dlg.destroy).pack(side="left", padx=(0, 10))
        RoundedButton(btn_f, text="Override Input", bg_color=ACCENT_BLUE,
                      btn_width=130, btn_height=30,
                      command=_override).pack(side="left")

        dlg.update_idletasks()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        px, py = self.root.winfo_rootx(), self.root.winfo_rooty()
        dw, dh = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
        dlg.grab_set()
        self.root.wait_window(dlg)
        return result[0]

    def _show_crossed_inputs_dialog(self, pin, existing_key):
        dlg = tk.Toplevel(self.root)
        dlg.title("GPIO Conflict Detected")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)

        existing_label = self._get_pin_input_label(existing_key)
        msg = (
            f"GPIO {pin} has already been mapped to {existing_label}.\n"
            "It seems something is wrong here... buttons may be getting crossed in your "
            "controller. Would you like to restart Easy Configurator over, or go to Main "
            "Menu without saving configuration?"
        )
        tk.Label(dlg, text=msg, bg=BG_CARD, fg=TEXT, font=(FONT_UI, 10),
                 justify="center", padx=28, pady=20, wraplength=450).pack()

        result = [None]
        btn_f = tk.Frame(dlg, bg=BG_CARD, pady=10)
        btn_f.pack()

        def _restart():
            result[0] = "restart"
            dlg.destroy()

        def _menu():
            result[0] = "menu"
            dlg.destroy()

        RoundedButton(btn_f, text="Restart Easy Config", bg_color=ACCENT_BLUE,
                      btn_width=150, btn_height=30,
                      command=_restart).pack(side="left", padx=(0, 10))
        RoundedButton(btn_f, text="Back to Main Menu", bg_color=BG_INPUT,
                      btn_width=145, btn_height=30,
                      command=_menu).pack(side="left")

        dlg.update_idletasks()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        px, py = self.root.winfo_rootx(), self.root.winfo_rooty()
        dw, dh = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
        dlg.grab_set()
        self.root.wait_window(dlg)
        return result[0]

    def _finish_without_saving(self):
        self._clear_override_flow()
        self._stop_scan_and_monitor(reset_detection_ui=True)
        if self.pico.connected:
            try:
                self.pico.reboot()   # return to play mode
            except Exception:
                pass
            try:
                self.pico.disconnect()
            except Exception:
                pass
        if self._on_back:
            self._on_back()

    def _restart_easy_config(self):
        self._stop_scan_and_monitor(reset_detection_ui=True)
        self._reset_easy_config_state()
        self._show_page(0)

    def _begin_override_repair(self, current_key, conflict_key):
        origin_page = self._current_page
        repair_page = self._get_pin_input_page(conflict_key)
        if repair_page is None:
            return

        self._clear_detected_pin(conflict_key)
        self._override_origin_page = origin_page
        self._override_repair_page = repair_page
        self._override_return_page = origin_page if repair_page != origin_page else None
        self._override_repair_key = conflict_key

        self._stop_scan_and_monitor(reset_detection_ui=True)
        self._show_page(repair_page)

    def _handle_detected_pin(self, current_key, pin, commit, reset_ui):
        conflict_key = self._find_existing_pin_assignment(pin, current_key)
        if conflict_key is None:
            commit()
            return True

        if self._override_repair_page == self._current_page and self._override_repair_key is not None:
            action = self._show_crossed_inputs_dialog(pin, conflict_key)
            if action == "restart":
                self._restart_easy_config()
            elif action == "menu":
                self._finish_without_saving()
            else:
                reset_ui()
            return False

        repair_page = self._get_pin_input_page(conflict_key)
        same_page = repair_page == self._current_page
        if not self._show_duplicate_override_dialog(pin, conflict_key, same_page=same_page):
            reset_ui()
            return False

        commit()
        self._begin_override_repair(current_key, conflict_key)
        return False

    # ── Shared helpers ────────────────────────────────────────────

    def _make_status_box(self, parent, idle_text="Click Here to Start Input Detection"):
        """Create the combined detect/status box.

        The entire gray box is clickable and starts detection.
        Cancel button sits top-right. Returns (frame, status_lbl, gpio_lbl).
        detect_btn and cancel_btn are attached as sf.detect_btn / sf.cancel_btn.
        detect_btn here is a simple namespace object with .set_state(), ._command,
        and ._state so the rest of the code that calls detect_btn.set_state() works.
        """
        sf = tk.Frame(parent, bg=BG_INPUT,
                      highlightbackground=BORDER, highlightthickness=1)
        sf.pack(fill="x", pady=(0, 10))

        # ── Top row: cancel button floats right ───────────────────────
        top_row = tk.Frame(sf, bg=BG_INPUT)
        top_row.pack(fill="x", padx=8, pady=(8, 0))
        tk.Frame(top_row, bg=BG_INPUT).pack(side="left", fill="x", expand=True)  # spacer

        can = RoundedButton(top_row, text="Cancel Input Detection",
                            bg_color="#555560", btn_width=185, btn_height=26,
                            btn_font=(FONT_UI, 8, "bold"))
        can.pack(side="right")
        can.set_state("disabled")

        # ── Centre: status label and GPIO result label ────────────────
        slbl = tk.Label(sf, text=idle_text,
                        bg=BG_INPUT, fg=ACCENT_BLUE,
                        font=(FONT_UI, 13, "bold"), cursor="hand2")
        slbl.pack(pady=(10, 2))

        glbl = tk.Label(sf, text="", bg=BG_INPUT, fg=ACCENT_GREEN,
                        font=(FONT_UI, 13, "bold"))
        glbl.pack(pady=(0, 12))

        # ── Proxy object that mimics a RoundedButton for callers ──────
        class _DetectProxy:
            def __init__(self):
                self._command = None
                self._state   = "normal"
                self._bg      = None   # callers do _render(det._bg) — needs to exist
            def set_state(self, s):
                self._state = s
                # Reflect disabled/normal on the status label cursor
                try:
                    slbl.config(cursor="hand2" if s == "normal" else "")
                except Exception:
                    pass
            def _render(self, *_):  # no-op — callers call this after setting _command
                pass

        det = _DetectProxy()

        # ── Wire clicks across every widget in the box ────────────────
        def _click(e):
            if det._state == "normal" and det._command:
                det._command()

        def _enter(e):
            sf.config(highlightbackground=ACCENT_BLUE, highlightthickness=2)

        def _leave(e):
            sf.config(highlightbackground=BORDER, highlightthickness=1)

        # Bind the outer frame and the two content labels directly.
        # top_row is intentionally NOT bound so cancel button area doesn't
        # accidentally trigger detection. The large padding below top_row
        # (slbl + glbl + their pady) makes the box feel fully clickable.
        for widget in (sf, slbl, glbl):
            widget.bind("<Button-1>", _click)
            widget.bind("<Enter>",    _enter)
            widget.bind("<Leave>",    _leave)

        # Prevent the cancel button from bubbling a click up to sf
        can.bind("<Button-1>", lambda e: "break")

        sf.detect_btn = det
        sf.cancel_btn = can
        return sf, slbl, glbl

    def _make_detect_cancel_row(self, parent, accent):
        """Compatibility shim — find the status box already packed into parent
        and return its (detect_btn, cancel_btn) proxy objects."""
        for child in parent.winfo_children():
            if hasattr(child, "detect_btn"):
                return child.detect_btn, child.cancel_btn
        # Should never reach here, but provide a working fallback just in case
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(anchor="w")
        det_btn = RoundedButton(row, text="Start Input Detection",
                                bg_color=accent, btn_width=200, btn_height=36)
        det_btn.pack(side="left")
        can_btn = RoundedButton(row, text="Cancel Input Detection",
                                bg_color="#555560", btn_width=185, btn_height=36)
        can_btn.pack(side="left", padx=(12, 0))
        can_btn.set_state("disabled")
        return det_btn, can_btn

    def _make_live_bar(self, parent, label):
        """Create a hidden live bar container. Returns (bar_frame, bar, header_lbl)."""
        bf = tk.Frame(parent, bg=BG_CARD)
        hdr = tk.Label(bf, text="Live Value:", bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        b = LiveBarGraph(bf, label=label, width=760, height=32)
        return bf, b, hdr

    def _show_bar(self, bar_frame, bar, hdr):
        """Pack the live bar into view."""
        hdr.pack(anchor="w", pady=(12, 4))
        bar.pack(fill="x")
        bar_frame.pack(fill="x", pady=(8, 0))

    def _push_monitor_prereqs(self, prefix, pin, mode):
        """Tell firmware the current pin/mode before starting a monitor session.
        Mirrors App._push_monitor_prereqs so MONITOR_ADC/DIG sees correct config."""
        if prefix == "whammy":
            self.pico.set_value("whammy_mode", mode)
            self.pico.set_value("whammy_pin", str(pin) if pin is not None else "-1")
        elif prefix == "tilt":
            self.pico.set_value("tilt_mode", mode)
            if mode == "i2c":
                self.pico.set_value("i2c_model",    str(self.detected.get("i2c_model", 0)))
                self.pico.set_value("adxl345_axis", str(self.detected.get("tilt_axis", 0)))
                self.pico.set_value("tilt_pin",     "-1")
            else:
                self.pico.set_value("tilt_pin", str(pin) if pin is not None else "-1")
        # joystick axes don't need prereqs — MONITOR_ADC just uses the pin directly

    def _start_monitor(self, mode, pin, bar, prefix=None, axis=0):
        """Start a background monitor thread that feeds *bar*.
        Pushes required prereqs to firmware first if prefix is given."""
        self._monitoring = True

        def _thread():
            try:
                if prefix:
                    try:
                        self._push_monitor_prereqs(prefix, pin, mode)
                    except Exception:
                        pass
                if mode == "i2c":
                    self.pico.start_monitor_i2c(axis=axis)
                elif mode == "analog":
                    self.pico.start_monitor_adc(pin)
                else:
                    self.pico.start_monitor_digital(pin)
                while self._monitoring:
                    val, _ = self.pico.drain_monitor_latest(0.05)
                    if val is not None:
                        self.root.after(0, lambda v=val: bar.set_value(v))
            except Exception:
                pass

        self._monitor_thread = threading.Thread(target=_thread, daemon=True)
        self._monitor_thread.start()

    # ── Digital button page ───────────────────────────────────────

    def _build_digital_content(self, key, name, accent):
        f = self._body_frame
        page_token = self._page_token
        idle_text = "Click Here to Start Input Detection"
        timeout_text = "No button press detected within timeout window. Click here to restart detection."

        # Fret colour dot for fret pages
        fret_color = FRET_COLORS.get(key)
        top = tk.Frame(f, bg=BG_CARD)
        top.pack(anchor="w", pady=(0, 4))
        if fret_color:
            dot = tk.Canvas(top, width=18, height=18, bg=BG_CARD, highlightthickness=0, bd=0)
            dot.create_oval(2, 2, 16, 16, fill=fret_color, outline=fret_color)
            dot.pack(side="left", padx=(0, 8))
        tk.Label(top, text=f"Press and release the {name} button on your controller.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(side="left")

        tk.Label(f,
                 text="The configurator listens for any GPIO 0\u201322 input change.\n"
                      "Make sure no other buttons are pressed during detection.",
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

        # Restore previous detection if present
        if key in self.detected:
            pin = self.detected[key]
            status_lbl.config(text=f"\u2713 Previously set to GPIO {pin}.", fg=ACCENT_GREEN)
            gpio_lbl.config(text=f"GPIO {pin}")

        detect_btn, cancel_btn = self._make_detect_cancel_row(f, accent)
        self._page_detection_reset = _restore_idle

        def start_detect():
            if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                return
            if not self.pico.connected:
                status_lbl.config(text="\u26a0  Not connected to controller.", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                return
            self._clear_scan_timeout()
            self.scanning = True
            self.scan_target = key
            detect_btn.set_state("disabled")
            cancel_btn.set_state("normal")
            status_lbl.config(text=f"Waiting for {name}\u2026  Press the button now.", fg=ACCENT_BLUE)
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
                    status_lbl.config(text="\u2713 Detection successful! Ready for next step.",
                                       fg=ACCENT_GREEN)
                    gpio_lbl.config(text=f"GPIO {pin}")

                self._handle_detected_pin(key, pin, _commit, _restore_idle)

            def _on_error(msg):
                if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                    return
                self.scanning = False
                self._clear_scan_timeout()
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text=f"\u26a0  Scan error: {msg}", fg=ACCENT_RED)

            def _on_timeout():
                if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                    return
                if not self.scanning:
                    return
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                self._clear_scan_timeout()
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text=timeout_text, fg=ACCENT_ORANGE)
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
                            if 0 <= pin <= 22:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p))
                                return
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): _on_error(e))

            def _cancel():
                if not self._page_is_active(page_token, status_lbl, gpio_lbl):
                    return
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                _restore_idle()

            cancel_btn._command = _cancel
            cancel_btn._render(cancel_btn._bg)
            self._start_scan_timeout(_on_timeout, timeout_ms=10000)
            threading.Thread(target=_thread, daemon=True).start()

        detect_btn._command = start_detect
        detect_btn._render(detect_btn._bg)
        if key not in self.detected:
            def _auto_start():
                self._auto_detect_after_id = None
                if self._page_is_active(page_token, status_lbl, gpio_lbl) and key not in self.detected:
                    start_detect()
            self._schedule_auto_detect(_auto_start, delay_ms=75)

    # ── D-Pad page ────────────────────────────────────────────────

    def _build_dpad_content(self):
        f = self._body_frame
        tk.Label(f, text="Press each D-Pad direction one at a time.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(anchor="w", pady=(0, 4))
        tk.Label(f,
                 text="Click the detection button for a direction, then press it on the controller.\n"
                      "Only one direction can be detected at a time.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(0, 14))

        grid = tk.Frame(f, bg=BG_CARD)
        grid.pack(fill="x")
        directions = [
            ("dpad_up",    "D-Pad Up"),
            ("dpad_right", "D-Pad Right"),
            ("dpad_down",  "D-Pad Down"),
            ("dpad_left",  "D-Pad Left"),
        ]
        for col in range(2):
            grid.columnconfigure(col, weight=1)

        for i, (key, label) in enumerate(directions):
            col = i % 2
            row_i = i // 2
            cell = tk.Frame(grid, bg=BG_INPUT, highlightbackground=BORDER, highlightthickness=1)
            cell.grid(row=row_i, column=col,
                      padx=(0, 10) if col == 0 else 0,
                      pady=(0, 10), sticky="nsew")

            tk.Label(cell, text=label, bg=BG_INPUT, fg=TEXT_HEADER,
                     font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

            gpio_lbl = tk.Label(cell, text="—", bg=BG_INPUT, fg=TEXT_DIM,
                                 font=(FONT_UI, 11, "bold"))
            gpio_lbl.pack(anchor="w", padx=12)

            status_lbl = tk.Label(cell, text="Not yet detected", bg=BG_INPUT,
                                   fg=TEXT_DIM, font=(FONT_UI, 8))
            status_lbl.pack(anchor="w", padx=12, pady=(2, 8))

            if key in self.detected:
                gpio_lbl.config(text=f"GPIO {self.detected[key]}", fg=ACCENT_GREEN)
                status_lbl.config(text="\u2713 Detected", fg=ACCENT_GREEN)

            btn_row = tk.Frame(cell, bg=BG_INPUT)
            btn_row.pack(anchor="w", padx=12, pady=(0, 10))

            det_btn = RoundedButton(btn_row, text="Detect",
                                     bg_color=ACCENT_BLUE, btn_width=110, btn_height=30,
                                     btn_font=(FONT_UI, 8, "bold"))
            det_btn.pack(side="left")
            can_btn = RoundedButton(btn_row, text="Cancel",
                                     bg_color=BG_HOVER, btn_width=80, btn_height=30,
                                     btn_font=(FONT_UI, 8, "bold"))
            can_btn.pack(side="left", padx=(8, 0))
            can_btn.set_state("disabled")

            self._wire_dpad_cell(key, label, det_btn, can_btn, gpio_lbl, status_lbl)

    def _wire_dpad_cell(self, key, label, det_btn, can_btn, gpio_lbl, status_lbl):
        """Wire up one D-Pad cell's detect / cancel buttons."""

        def start_detect():
            if not self.pico.connected:
                status_lbl.config(text="\u26a0 Not connected", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                status_lbl.config(text="\u26a0 Another detection is active", fg=ACCENT_ORANGE)
                return
            self.scanning = True
            self.scan_target = key
            det_btn.set_state("disabled")
            can_btn.set_state("normal")
            status_lbl.config(text=f"Press {label} now\u2026", fg=ACCENT_BLUE)
            gpio_lbl.config(text="\u2026", fg=ACCENT_BLUE)

            def _restore_idle():
                det_btn.set_state("normal")
                can_btn.set_state("disabled")
                prev = self.detected.get(key)
                if prev is not None:
                    gpio_lbl.config(text=f"GPIO {prev}", fg=ACCENT_GREEN)
                    status_lbl.config(text="\u2713 Detected", fg=ACCENT_GREEN)
                else:
                    gpio_lbl.config(text="\u2014", fg=TEXT_DIM)
                    status_lbl.config(text="Not yet detected", fg=TEXT_DIM)

            def _on_detected(pin):
                def _commit():
                    self.detected[key] = pin
                    self.scanning = False
                    det_btn.set_state("normal")
                    can_btn.set_state("disabled")
                    gpio_lbl.config(text=f"GPIO {pin}", fg=ACCENT_GREEN)
                    status_lbl.config(text="\u2713 Detected", fg=ACCENT_GREEN)

                self._handle_detected_pin(key, pin, _commit, _restore_idle)

            def _on_error(msg):
                self.scanning = False
                gpio_lbl.config(text="Error", fg=ACCENT_RED)
                status_lbl.config(text=f"\u26a0 {msg}", fg=ACCENT_RED)
                det_btn.set_state("normal")
                can_btn.set_state("disabled")

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
                            if 0 <= pin <= 22:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p))
                                return
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): _on_error(e))

            def _cancel():
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                _restore_idle()

            can_btn._command = _cancel
            can_btn._render(can_btn._bg)
            threading.Thread(target=_thread, daemon=True).start()

        det_btn._command = start_detect
        det_btn._render(det_btn._bg)

    # ── Joystick axis page ────────────────────────────────────────

    def _build_joy_axis_content(self, key, name):
        """Dispatch to the right axis builder."""
        if key == "joy_x":
            self._build_joy_x_content()
        else:
            self._build_joy_y_content()

    def _build_joy_x_content(self):
        """Joystick Left/Right axis — horizontal bar + Swap Left & Right checkbox."""
        key      = "joy_x"
        mode_key = "joy_x_mode"
        invert_key = "joy_dpad_x_invert"
        f = self._body_frame

        tk.Label(f, text="Assign a pin to the Joystick \u2014 Left / Right Axis.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(anchor="w", pady=(0, 4))
        tk.Label(f,
                 text="Digital: any GPIO 0\u201322 (on/off axis, less precise).\n"
                      "Analog: ADC pins GPIO 26\u201328 (potentiometer VRx \u2014 recommended).",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(0, 14))

        mode_var   = tk.StringVar(value=self.detected.get(mode_key, "analog"))
        invert_var = tk.BooleanVar(value=bool(self.detected.get(invert_key, False)))

        mode_row = tk.Frame(f, bg=BG_CARD)
        mode_row.pack(anchor="w", pady=(0, 8))
        tk.Label(mode_row, text="Mode:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 10))
        for val, lbl in [("digital", "Digital  (GPIO 0\u201322)"),
                          ("analog",  "Analog   (GPIO 26\u201328, recommended)")]:
            tk.Radiobutton(mode_row, text=lbl, variable=mode_var, value=val,
                            bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                            activebackground=BG_CARD, activeforeground=TEXT,
                            font=(FONT_UI, 9)).pack(side="left", padx=(0, 16))

        _sf, status_lbl, gpio_lbl = self._make_status_box(
            f, idle_text="Choose Digital or Analog, then Click to Start Input Detection")
        idle_text = "Choose Digital or Analog, then Click to Start Input Detection"

        # ── Live bar (respects invert_var visually) ───────────────
        bar_frame = tk.Frame(f, bg=BG_CARD)
        bar_hdr   = tk.Label(bar_frame, text="Live Value:", bg=BG_CARD, fg=TEXT_DIM,
                              font=(FONT_UI, 9))
        bar = LiveBarGraph(bar_frame, label="Left / Right Axis", width=700, height=32,
                           invert_var=invert_var)

        detect_btn, cancel_btn = self._make_detect_cancel_row(f, ACCENT_BLUE)

        def _restore_idle():
            detect_btn.set_state("normal")
            cancel_btn.set_state("disabled")
            status_lbl.config(text=idle_text, fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

        # ── Invert checkbox (near the monitor bar) ────────────────
        inv_row = tk.Frame(f, bg=BG_CARD)
        inv_row.pack(anchor="w", pady=(6, 0))
        def _on_invert_toggle():
            self.detected[invert_key] = invert_var.get()
            if bar.winfo_exists():
                bar.refresh()
        tk.Checkbutton(inv_row, text="Swap Left \u2194 Right  (invert axis signal)",
                        variable=invert_var, command=_on_invert_toggle,
                        bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                        activebackground=BG_CARD, activeforeground=TEXT,
                        font=(FONT_UI, 9)).pack(side="left")

        def start_detect():
            if not self.pico.connected:
                status_lbl.config(text="\u26a0  Not connected to controller.", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                return
            # Stop any active monitor before starting a new scan
            if self._monitoring:
                self._monitoring = False
                try:
                    self.pico.stop_monitor()
                except Exception:
                    pass
            mode = mode_var.get()
            self.scanning = True
            self.scan_target = key
            detect_btn.set_state("disabled")
            cancel_btn.set_state("normal")
            hint = "Move the joystick left/right fully." if mode == "analog" else "Deflect the joystick left or right."
            status_lbl.config(text=f"Waiting\u2026  {hint}", fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

            def _on_detected(pin, det_mode):
                def _commit():
                    self.scanning = False
                    self.detected[key] = pin
                    self.detected[mode_key] = det_mode
                    detect_btn.set_state("normal")
                    cancel_btn.set_state("disabled")
                    status_lbl.config(text=f"\u2713 Detected on GPIO {pin} ({det_mode})!", fg=ACCENT_GREEN)
                    gpio_lbl.config(text=f"GPIO {pin}")
                    if det_mode == "analog":
                        self._show_bar(bar_frame, bar, bar_hdr)
                        self._start_monitor("analog", pin, bar)

                self._handle_detected_pin(key, pin, _commit, _restore_idle)

            def _on_error(msg):
                self.scanning = False
                status_lbl.config(text=f"\u26a0  Scan error: {msg}", fg=ACCENT_RED)
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")

            def _thread():
                try:
                    self.pico.start_scan()
                    while self.scanning:
                        line = self.pico.read_scan_line(0.1)
                        if not line:
                            continue
                        if line.startswith("PIN:"):
                            try:
                                pin = int(line[4:])
                            except ValueError:
                                continue
                            if mode == "digital" and 0 <= pin <= 22:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p, "digital"))
                                return
                        elif line.startswith("APIN:"):
                            try:
                                pin = int(line[5:].split(":")[0])
                            except (ValueError, IndexError):
                                continue
                            if mode == "analog" and 26 <= pin <= 28:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p, "analog"))
                                return
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): _on_error(e))

            def _cancel():
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                _restore_idle()

            cancel_btn._command = _cancel
            cancel_btn._render(cancel_btn._bg)
            threading.Thread(target=_thread, daemon=True).start()

        detect_btn._command = start_detect
        detect_btn._render(detect_btn._bg)

    def _build_joy_y_content(self):
        """Joystick Up/Down axis — vertical bar + Swap Up & Down checkbox."""
        key        = "joy_y"
        mode_key   = "joy_y_mode"
        invert_key = "joy_dpad_y_invert"
        f = self._body_frame

        tk.Label(f, text="Assign a pin to the Joystick \u2014 Up / Down Axis.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(anchor="w", pady=(0, 4))
        tk.Label(f,
                 text="Digital: any GPIO 0\u201322 (on/off axis, less precise).\n"
                      "Analog: ADC pins GPIO 26\u201328 (potentiometer VRy \u2014 recommended).\n"
                      "The vertical bar below shows which direction XInput will see.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(0, 12))

        mode_var   = tk.StringVar(value=self.detected.get(mode_key, "analog"))
        invert_var = tk.BooleanVar(value=bool(self.detected.get(invert_key, False)))

        mode_row = tk.Frame(f, bg=BG_CARD)
        mode_row.pack(anchor="w", pady=(0, 8))
        tk.Label(mode_row, text="Mode:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 10))
        for val, lbl in [("digital", "Digital  (GPIO 0\u201322)"),
                          ("analog",  "Analog   (GPIO 26\u201328, recommended)")]:
            tk.Radiobutton(mode_row, text=lbl, variable=mode_var, value=val,
                            bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                            activebackground=BG_CARD, activeforeground=TEXT,
                            font=(FONT_UI, 9)).pack(side="left", padx=(0, 16))

        _sf, status_lbl, gpio_lbl = self._make_status_box(
            f, idle_text="Choose Digital or Analog, then Click to Start Input Detection")
        idle_text = "Choose Digital or Analog, then Click to Start Input Detection"
        detect_btn, cancel_btn = self._make_detect_cancel_row(f, ACCENT_BLUE)

        # ── Invert checkbox (near the monitor bar) ────────────────
        vbar_ref = [None]   # forward reference so checkbox can call refresh
        inv_row = tk.Frame(f, bg=BG_CARD)
        inv_row.pack(anchor="w", pady=(6, 0))
        def _on_invert_toggle():
            self.detected[invert_key] = invert_var.get()
            if vbar_ref[0]:
                vbar_ref[0].refresh()
        tk.Checkbutton(inv_row, text="Swap Up \u2194 Down  (invert axis signal)",
                        variable=invert_var, command=_on_invert_toggle,
                        bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                        activebackground=BG_CARD, activeforeground=TEXT,
                        font=(FONT_UI, 9)).pack(side="left")

        def _restore_idle():
            detect_btn.set_state("normal")
            cancel_btn.set_state("disabled")
            status_lbl.config(text=idle_text, fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

        # Vertical live bar — half height to fit UI better
        vbar_outer = tk.Frame(f, bg=BG_CARD)
        vbar_outer.pack(anchor="w", pady=(14, 0))
        vbar_hdr = tk.Label(vbar_outer, text="Live Value (Up/Down):",
                             bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        vbar = LiveBarGraphVertical(vbar_outer, label="Y Axis",
                                     width=80, height=90, invert_var=invert_var)
        vbar_ref[0] = vbar

        def start_detect():
            if not self.pico.connected:
                status_lbl.config(text="\u26a0  Not connected to controller.", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                return
            # Stop any active monitor before starting a new scan
            if self._monitoring:
                self._monitoring = False
                try:
                    self.pico.stop_monitor()
                except Exception:
                    pass
            mode = mode_var.get()
            self.scanning = True
            self.scan_target = key
            detect_btn.set_state("disabled")
            cancel_btn.set_state("normal")
            hint = "Move the joystick up/down fully." if mode == "analog" else "Deflect the joystick up or down."
            status_lbl.config(text=f"Waiting\u2026  {hint}", fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

            def _on_detected(pin, det_mode):
                def _commit():
                    self.scanning = False
                    self.detected[key] = pin
                    self.detected[mode_key] = det_mode
                    detect_btn.set_state("normal")
                    cancel_btn.set_state("disabled")
                    status_lbl.config(text=f"\u2713 Detected on GPIO {pin} ({det_mode})!", fg=ACCENT_GREEN)
                    gpio_lbl.config(text=f"GPIO {pin}")
                    if det_mode == "analog":
                        vbar_hdr.pack(anchor="w", pady=(0, 4))
                        vbar.pack()
                        vbar_outer.pack(anchor="w", pady=(14, 0))
                        self._start_monitor("analog", pin, vbar)

                self._handle_detected_pin(key, pin, _commit, _restore_idle)

            def _on_error(msg):
                self.scanning = False
                status_lbl.config(text=f"\u26a0  Scan error: {msg}", fg=ACCENT_RED)
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")

            def _thread():
                try:
                    self.pico.start_scan()
                    while self.scanning:
                        line = self.pico.read_scan_line(0.1)
                        if not line:
                            continue
                        if line.startswith("PIN:"):
                            try:
                                pin = int(line[4:])
                            except ValueError:
                                continue
                            if mode == "digital" and 0 <= pin <= 22:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p, "digital"))
                                return
                        elif line.startswith("APIN:"):
                            try:
                                pin = int(line[5:].split(":")[0])
                            except (ValueError, IndexError):
                                continue
                            if mode == "analog" and 26 <= pin <= 28:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p, "analog"))
                                return
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): _on_error(e))

            def _cancel():
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                _restore_idle()

            cancel_btn._command = _cancel
            cancel_btn._render(cancel_btn._bg)
            threading.Thread(target=_thread, daemon=True).start()

        detect_btn._command = start_detect
        detect_btn._render(detect_btn._bg)

    # ── Whammy bar page ───────────────────────────────────────────

    def _build_whammy_content(self):
        f = self._body_frame
        tk.Label(f, text="Assign a pin to the Whammy Bar.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(anchor="w", pady=(0, 4))
        tk.Label(f,
                 text="Digital: any GPIO 0\u201322 (on/off).\n"
                      "Analog: ADC pins GPIO 26\u201329 (potentiometer \u2014 recommended for full range).",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(0, 14))

        mode_var = tk.StringVar(value=self.detected.get("whammy_mode", "analog"))
        mode_row = tk.Frame(f, bg=BG_CARD)
        mode_row.pack(anchor="w", pady=(0, 12))
        tk.Label(mode_row, text="Mode:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 10))
        for val, lbl in [("digital", "Digital  (GPIO 0\u201322)"),
                          ("analog",  "Analog   (GPIO 26\u201329, recommended)")]:
            tk.Radiobutton(mode_row, text=lbl, variable=mode_var, value=val,
                            bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                            activebackground=BG_CARD, activeforeground=TEXT,
                            font=(FONT_UI, 9)).pack(side="left", padx=(0, 16))

        # ── Calibration state (persisted in self.detected) ──────────
        EMA_TABLE = [256, 230, 200, 170, 140, 110, 80, 55, 35, 20]
        wh_min_var    = tk.IntVar(value=self.detected.get("whammy_min",    0))
        wh_max_var    = tk.IntVar(value=self.detected.get("whammy_max",    4095))
        wh_invert_var = tk.BooleanVar(value=bool(self.detected.get("whammy_invert", False)))
        wh_smooth_var = tk.IntVar(value=self.detected.get("whammy_smooth", 4))
        _ema_alpha_var = tk.IntVar(value=EMA_TABLE[self.detected.get("whammy_smooth", 4)])

        # Stored raw snapshots for guided calibration (survive page revisits)
        _rest_raw = [self.detected.get("whammy_rest_raw", None)]
        _act_raw  = [self.detected.get("whammy_act_raw",  None)]

        def _sync_wh_detected(*_):
            self.detected["whammy_min"]       = wh_min_var.get()
            self.detected["whammy_max"]       = wh_max_var.get()
            self.detected["whammy_invert"]    = wh_invert_var.get()
            lvl = wh_smooth_var.get()
            self.detected["whammy_smooth"]    = lvl
            self.detected["whammy_ema_alpha"] = EMA_TABLE[lvl]
            _ema_alpha_var.set(EMA_TABLE[lvl])
        wh_min_var.trace_add("write",    _sync_wh_detected)
        wh_max_var.trace_add("write",    _sync_wh_detected)
        wh_invert_var.trace_add("write", _sync_wh_detected)
        wh_smooth_var.trace_add("write", _sync_wh_detected)

        # ── Status box ───────────────────────────────────────────────
        _sf, status_lbl, gpio_lbl = self._make_status_box(
            f, idle_text="Choose Digital or Analog, then Click to Start Input Detection")
        idle_text = "Choose Digital or Analog, then Click to Start Input Detection"
        if "whammy_pin" in self.detected:
            pin  = self.detected["whammy_pin"]
            mstr = self.detected.get("whammy_mode", "analog")
            status_lbl.config(text=f"\u2713 Previously set to GPIO {pin} ({mstr}).", fg=ACCENT_GREEN)
            gpio_lbl.config(text=f"GPIO {pin}")

        # ── Detect / Cancel buttons ─────────────────────────────────
        detect_btn, cancel_btn = self._make_detect_cancel_row(f, ACCENT_BLUE)

        def _restore_idle():
            detect_btn.set_state("normal")
            cancel_btn.set_state("disabled")
            status_lbl.config(text=idle_text, fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

        # ── Two-column calibration panel (hidden until detection) ────
        col_outer = tk.Frame(f, bg=BG_CARD)
        _live_val = [0]

        left_col  = tk.Frame(col_outer, bg=BG_CARD)
        right_col = tk.Frame(col_outer, bg=BG_CARD)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right_col.pack(side="left", fill="both", expand=True)

        # ── LEFT: live raw bar ────────────────────────────────────────
        tk.Label(left_col, text="Live Value:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9)).pack(anchor="w", pady=(8, 2))
        bar = LiveBarGraph(left_col, label="Whammy", width=430, height=28,
                           min_marker_var=wh_min_var, max_marker_var=wh_max_var)
        bar.pack(fill="x")

        calib_frame = tk.Frame(left_col, bg=BG_CARD)
        calib_frame.pack(anchor="w", fill="x")

        # ── Guided calibration rows ───────────────────────────────────
        def _fmt_recorded(raw):
            return f"Recorded: {raw}" if raw is not None else "Not recorded yet"

        # Row 1 — rest position
        rest_row = tk.Frame(calib_frame, bg=BG_CARD)
        rest_row.pack(anchor="w", pady=(8, 2), fill="x")
        tk.Label(rest_row,
                 text="Put whammy in resting position, then click here:",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9)).pack(side="left", padx=(0, 8))

        rest_status = tk.Label(rest_row, text=_fmt_recorded(_rest_raw[0]),
                                bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        rest_status.pack(side="left")

        rest_btn_row = tk.Frame(calib_frame, bg=BG_CARD)
        rest_btn_row.pack(anchor="w", pady=(0, 4))

        # Row 2 — full actuation
        act_row = tk.Frame(calib_frame, bg=BG_CARD)
        act_row.pack(anchor="w", pady=(4, 2), fill="x")
        tk.Label(act_row,
                 text="Push whammy all the way in, then click here:",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9)).pack(side="left", padx=(0, 8))

        act_status = tk.Label(act_row, text=_fmt_recorded(_act_raw[0]),
                               bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        act_status.pack(side="left")

        act_btn_row = tk.Frame(calib_frame, bg=BG_CARD)
        act_btn_row.pack(anchor="w", pady=(0, 4))

        def _apply_calibration():
            """Compute min/max/invert from rest and actuated snapshots with 20% deadzone."""
            rest = _rest_raw[0]
            act  = _act_raw[0]
            if rest is None or act is None:
                return
            if rest == act:
                return  # degenerate — ignore

            raw_range = abs(act - rest)
            deadzone  = int(0.20 * raw_range)

            if rest <= act:
                # Signal increases with actuation — push deadzone into rest end
                new_min    = max(0, rest + deadzone)
                new_max    = min(4095, act)
                new_invert = False
            else:
                # Signal decreases with actuation — push deadzone into rest end
                new_min    = max(0, act)
                new_max    = min(4095, rest - deadzone)
                new_invert = True

            if new_min >= new_max:
                new_min = max(0, new_max - 1)

            wh_min_var.set(new_min)
            wh_max_var.set(new_max)
            wh_invert_var.set(new_invert)

        def _record_rest():
            v = _live_val[0]
            _rest_raw[0] = v
            self.detected["whammy_rest_raw"] = v
            rest_status.config(text=_fmt_recorded(v), fg=ACCENT_GREEN)
            _apply_calibration()

        def _record_act():
            v = _live_val[0]
            _act_raw[0] = v
            self.detected["whammy_act_raw"] = v
            act_status.config(text=_fmt_recorded(v), fg=ACCENT_GREEN)
            _apply_calibration()

        RoundedButton(rest_btn_row, text="Whammy at Rest",
                      bg_color=ACCENT_BLUE,
                      btn_width=140, btn_height=28, btn_font=(FONT_UI, 9, "bold"),
                      command=_record_rest).pack(side="left")

        RoundedButton(act_btn_row, text="Whammy Actuated",
                      bg_color=ACCENT_BLUE,
                      btn_width=140, btn_height=28, btn_font=(FONT_UI, 9, "bold"),
                      command=_record_act).pack(side="left")

        # Restore recorded-status colours if values already exist from a prior visit
        if _rest_raw[0] is not None:
            rest_status.config(fg=ACCENT_GREEN)
        if _act_raw[0] is not None:
            act_status.config(fg=ACCENT_GREEN)

        # ── RIGHT: calibrated output bar + smoothing slider ──────────
        tk.Label(right_col, text="Calibrated Output:", bg=BG_CARD,
                 fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(8, 2))
        cal_bar = CalibratedBarGraph(right_col, label="Whammy Cal",
                                     width=430, height=28,
                                     min_var=wh_min_var, max_var=wh_max_var,
                                     invert_var=wh_invert_var,
                                     ema_alpha_var=_ema_alpha_var)
        cal_bar.pack(fill="x")

        # ── Smoothing slider ─────────────────────────────────────────
        sm_row = tk.Frame(right_col, bg=BG_CARD)
        sm_row.pack(anchor="w", pady=(6, 0))
        tk.Label(sm_row, text="Smoothing:", bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 4))
        tk.Label(sm_row, text="0", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
        smooth_readout = tk.Label(sm_row, text="", bg=BG_CARD, fg=TEXT_DIM,
                                   font=(FONT_UI, 8), width=14, anchor="w")

        def _on_smooth(val):
            lvl = int(float(val))
            _sync_wh_detected()
            txt = f"Lv{lvl}" if lvl == 0 else f"Lv{lvl} (\u03b1{EMA_TABLE[lvl]})"
            smooth_readout.config(text=txt)

        smooth_slider = tk.Scale(sm_row, from_=0, to=9, orient="horizontal",
                                  variable=wh_smooth_var, showvalue=False,
                                  bg=BG_CARD, fg=TEXT, troughcolor=BG_INPUT,
                                  highlightthickness=0, length=90, sliderlength=14,
                                  resolution=1, command=_on_smooth)
        smooth_slider.pack(side="left", padx=(0, 2))
        tk.Label(sm_row, text="9", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 6))
        smooth_readout.pack(side="left")
        _on_smooth(wh_smooth_var.get())

        def _on_cal_change(*_):
            if cal_bar.winfo_exists():
                cal_bar.redraw()
            if bar.winfo_exists():
                bar.redraw_markers()
        wh_min_var.trace_add("write",    _on_cal_change)
        wh_max_var.trace_add("write",    _on_cal_change)
        wh_invert_var.trace_add("write", _on_cal_change)

        _orig_set = bar.set_value
        def _patched_set(v):
            _orig_set(v)
            _live_val[0] = int(v)
            if cal_bar.winfo_exists():
                cal_bar.set_raw(v)
        bar.set_value = _patched_set

        # Helper: reveal the two-column panel
        def _show_whammy_bars(pin, det_mode):
            if det_mode == "analog":
                calib_frame.pack(anchor="w", fill="x")
                right_col.pack(side="left", fill="both", expand=True)
                cal_bar.reset_ema()
            else:
                calib_frame.pack_forget()
                right_col.pack_forget()
            col_outer.pack(fill="x", pady=(8, 0))

        # ── Detection logic ──────────────────────────────────────────
        def start_detect():
            if not self.pico.connected:
                status_lbl.config(text="\u26a0  Not connected to controller.", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                return
            # Stop any active monitor before starting a new scan
            self._stop_scan_and_monitor()
            mode = mode_var.get()
            self.scanning = True
            self.scan_target = "whammy_pin"
            detect_btn.set_state("disabled")
            cancel_btn.set_state("normal")
            hint = ("Move the whammy bar fully." if mode == "analog"
                    else "Press or toggle the whammy input.")
            status_lbl.config(text=f"Waiting\u2026  {hint}", fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

            def _on_detected(pin, det_mode):
                def _commit():
                    self.scanning = False
                    self.detected["whammy_pin"]  = pin
                    self.detected["whammy_mode"] = det_mode
                    detect_btn.set_state("normal")
                    cancel_btn.set_state("disabled")
                    status_lbl.config(
                        text=f"\u2713 Detected on GPIO {pin} ({det_mode})!", fg=ACCENT_GREEN)
                    gpio_lbl.config(text=f"GPIO {pin}")
                    _show_whammy_bars(pin, det_mode)
                    self._start_monitor(det_mode, pin, bar, prefix="whammy")

                self._handle_detected_pin("whammy_pin", pin, _commit, _restore_idle)

            def _on_error(msg):
                self.scanning = False
                status_lbl.config(text=f"\u26a0  Scan error: {msg}", fg=ACCENT_RED)
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")

            def _thread():
                # The firmware's SCAN mode already applies its own threshold before
                # sending APIN lines, so we fire on the very first APIN received for
                # the correct pin. No extra delta-tracking needed — that was adding a
                # second hurdle that made narrow-range whammies (e.g. ~150 ADC counts)
                # very hard to trigger.
                try:
                    self.pico.start_scan()
                    while self.scanning:
                        line = self.pico.read_scan_line(0.1)
                        if not line:
                            continue
                        if line.startswith("PIN:"):
                            try:
                                pin = int(line[4:])
                            except ValueError:
                                continue
                            if mode == "digital" and 0 <= pin <= 22:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p, "digital"))
                                return
                        elif line.startswith("APIN:"):
                            try:
                                parts = line[5:].split(":")
                                pin = int(parts[0])
                            except (ValueError, IndexError):
                                continue
                            if mode == "analog" and 26 <= pin <= 29:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p, "analog"))
                                return
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): _on_error(e))

            def _cancel():
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                _restore_idle()

            cancel_btn._command = _cancel
            cancel_btn._render(cancel_btn._bg)
            threading.Thread(target=_thread, daemon=True).start()

        detect_btn._command = start_detect
        detect_btn._render(detect_btn._bg)

        # Restore live bars if already detected on this session
        if "whammy_pin" in self.detected:
            _det_mode = self.detected.get("whammy_mode", "analog")
            _show_whammy_bars(self.detected["whammy_pin"], _det_mode)
            self._start_monitor(_det_mode, self.detected["whammy_pin"], bar, prefix="whammy")

    # ── LED configuration page ────────────────────────────────────

    def _build_led_content(self):
        """LED configurator — compact 2-column layout to fit the easy config window."""
        f = self._body_frame

        # ── Init per-LED state if not already present ───────────────
        if "led_enabled" not in self.detected:
            self.detected["led_enabled"]      = False
            self.detected["led_count"]        = 9
            self.detected["led_brightness"]   = 2
            self.detected["led_loop_enabled"] = False
            self.detected["led_loop_start"]   = 0
            self.detected["led_loop_end"]     = 0
            self.detected["led_reactive"]     = False
            self.detected["led_colors"]       = ["FFFFFF"] * MAX_LEDS
            self.detected["led_maps"]         = [0] * LED_INPUT_COUNT
            self.detected["led_active_br"]    = [8] * LED_INPUT_COUNT
        # Breathe/wave may be absent if detected was populated before these fields existed
        self.detected.setdefault("led_breathe_enabled", False)
        self.detected.setdefault("led_breathe_start",   0)   # 0-indexed
        self.detected.setdefault("led_breathe_end",     0)   # 0-indexed
        self.detected.setdefault("led_breathe_min",     0)   # 0–31 firmware scale
        self.detected.setdefault("led_breathe_max",     31)  # 0–31 firmware scale
        self.detected.setdefault("led_wave_enabled",    False)
        self.detected.setdefault("led_wave_origin",     0)   # 0-indexed

        MAX_LED_COUNT = MAX_LEDS

        # ── Tk vars ──────────────────────────────────────────────────
        led_enabled_var    = tk.BooleanVar(value=self.detected["led_enabled"])
        led_count_var      = tk.IntVar(value=self.detected["led_count"])
        led_brightness_var = tk.IntVar(value=self.detected["led_brightness"])
        led_loop_var       = tk.BooleanVar(value=self.detected["led_loop_enabled"])
        led_loop_start_var = tk.IntVar(value=self.detected["led_loop_start"] + 1)
        led_loop_end_var   = tk.IntVar(value=self.detected["led_loop_end"] + 1)
        led_reactive_var   = tk.BooleanVar(value=self.detected["led_reactive"])
        led_color_vars     = [tk.StringVar(value=c) for c in self.detected["led_colors"]]
        led_map_vars       = [tk.IntVar(value=m) for m in self.detected["led_maps"]]
        led_active_vars    = [tk.IntVar(value=b) for b in self.detected["led_active_br"]]
        # Breathe/wave vars — LED indices displayed 1-indexed; brightness displayed 0–9
        led_breathe_var       = tk.BooleanVar(value=self.detected["led_breathe_enabled"])
        led_breathe_start_var = tk.IntVar(value=self.detected["led_breathe_start"] + 1)
        led_breathe_end_var   = tk.IntVar(value=self.detected["led_breathe_end"] + 1)
        led_breathe_min_var   = tk.IntVar(value=round(self.detected["led_breathe_min"] * 9 / 31))
        led_breathe_max_var   = tk.IntVar(value=round(self.detected["led_breathe_max"] * 9 / 31))
        led_wave_var          = tk.BooleanVar(value=self.detected["led_wave_enabled"])
        led_wave_origin_var   = tk.IntVar(value=self.detected["led_wave_origin"] + 1)

        def _sync(*_):
            self.detected["led_enabled"]      = led_enabled_var.get()
            count = max(1, min(MAX_LEDS, led_count_var.get()))
            led_count_var.set(count)
            self.detected["led_count"]        = count
            self.detected["led_brightness"]   = led_brightness_var.get()
            self.detected["led_loop_enabled"] = led_loop_var.get()
            self.detected["led_loop_start"]   = led_loop_start_var.get() - 1
            self.detected["led_loop_end"]     = led_loop_end_var.get() - 1
            self.detected["led_reactive"]     = led_reactive_var.get()
            self.detected["led_colors"]       = [v.get() for v in led_color_vars]
            self.detected["led_maps"]         = [v.get() for v in led_map_vars]
            self.detected["led_active_br"]    = [v.get() for v in led_active_vars]
            self.detected["led_breathe_enabled"] = led_breathe_var.get()
            self.detected["led_breathe_start"]   = led_breathe_start_var.get() - 1
            self.detected["led_breathe_end"]     = led_breathe_end_var.get() - 1
            self.detected["led_breathe_min"]     = round(led_breathe_min_var.get() * 31 / 9)
            self.detected["led_breathe_max"]     = round(led_breathe_max_var.get() * 31 / 9)
            self.detected["led_wave_enabled"]    = led_wave_var.get()
            self.detected["led_wave_origin"]     = led_wave_origin_var.get() - 1

        def _text_for_bg(hex_rgb):
            try:
                r = int(hex_rgb[0:2], 16)
                g = int(hex_rgb[2:4], 16)
                b = int(hex_rgb[4:6], 16)
            except Exception:
                return "#FFFFFF"
            return "#000000" if (0.2126*r + 0.7152*g + 0.0722*b) > 140 else "#FFFFFF"

        def _open_color_dialog(led_idx):
            cur_hex = led_color_vars[led_idx].get().strip()
            if len(cur_hex) != 6:
                cur_hex = "FFFFFF"
            try:
                cr = int(cur_hex[0:2], 16)
                cg = int(cur_hex[2:4], 16)
                cb = int(cur_hex[4:6], 16)
            except Exception:
                cr = cg = cb = 255

            dlg = tk.Toplevel(f.winfo_toplevel())
            dlg.title(f"LED #{led_idx+1} Color")
            dlg.configure(bg=BG_CARD)
            dlg.resizable(False, False)
            dlg.transient(f.winfo_toplevel())

            inner = tk.Frame(dlg, bg=BG_CARD)
            inner.pack(fill="both", expand=True, padx=16, pady=12)

            tk.Label(inner, text=f"Color for LED #{led_idx+1}", bg=BG_CARD, fg=TEXT_HEADER,
                     font=(FONT_UI, 11, "bold")).pack(pady=(0, 8))

            r_var = tk.IntVar(value=cr)
            g_var = tk.IntVar(value=cg)
            b_var = tk.IntVar(value=cb)

            preview = tk.Canvas(inner, width=80, height=50, bg=BG_CARD,
                                highlightthickness=1, highlightbackground=BORDER, bd=0)
            preview.create_rectangle(2, 2, 78, 48, fill=f"#{cur_hex}", outline=f"#{cur_hex}",
                                      tags="fill")
            preview.pack(pady=(0, 6))

            hex_lbl = tk.Label(inner, text=f"#{cur_hex}", bg=BG_CARD, fg=TEXT_DIM,
                               font=("Consolas", 9))
            hex_lbl.pack(pady=(0, 6))

            def _upd(*_):
                rv = max(0, min(255, r_var.get()))
                gv = max(0, min(255, g_var.get()))
                bv = max(0, min(255, b_var.get()))
                h = f"#{rv:02X}{gv:02X}{bv:02X}"
                preview.itemconfig("fill", fill=h, outline=h)
                hex_lbl.config(text=h)

            # ── Preset swatches ────────────────────────────────────────
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

            tk.Label(inner, text="Presets:", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(anchor="w", pady=(0, 4))

            swatch_row = tk.Frame(inner, bg=BG_CARD)
            swatch_row.pack(anchor="w", pady=(0, 8))

            def _apply_preset(hex_rgb):
                r_var.set(int(hex_rgb[0:2], 16))
                g_var.set(int(hex_rgb[2:4], 16))
                b_var.set(int(hex_rgb[4:6], 16))
                _upd()

            for p_name, p_hex in PRESET_COLORS:
                rc2, gc2, bc2 = int(p_hex[0:2],16), int(p_hex[2:4],16), int(p_hex[4:6],16)
                lum = 0.2126*rc2 + 0.7152*gc2 + 0.0722*bc2
                fg_text = "#000000" if lum > 100 else "#FFFFFF"
                display = f"#{p_hex}"
                sw = tk.Canvas(swatch_row, width=32, height=32, bg=BG_CARD,
                               highlightthickness=1, highlightbackground=BORDER,
                               cursor="hand2", bd=0)
                sw.create_rectangle(1, 1, 31, 31, fill=display, outline=display, tags="fill")
                sw.create_text(16, 22, text=p_name[:3], fill=fg_text,
                               font=(FONT_UI, 6, "bold"), tags="lbl")
                sw.pack(side="left", padx=(0, 4))
                sw.bind("<Button-1>", lambda _e, h=p_hex: _apply_preset(h))
                def _on_enter(e, canvas=sw):
                    canvas.config(highlightbackground=ACCENT_BLUE, highlightthickness=2)
                def _on_leave(e, canvas=sw):
                    canvas.config(highlightbackground=BORDER, highlightthickness=1)
                sw.bind("<Enter>", _on_enter)
                sw.bind("<Leave>", _on_leave)

            tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))

            # ── RGB sliders ────────────────────────────────────────────
            for lbl_t, var, acc in [("Red",   r_var, "#e74c3c"),
                                     ("Green", g_var, "#2ecc71"),
                                     ("Blue",  b_var, "#3498db")]:
                row = tk.Frame(inner, bg=BG_CARD)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=lbl_t, bg=BG_CARD, fg=acc,
                         width=6, font=(FONT_UI, 8, "bold"), anchor="w").pack(side="left")
                tk.Scale(row, from_=0, to=255, orient="horizontal", variable=var,
                         bg=BG_CARD, fg=TEXT, troughcolor=acc,
                         highlightthickness=0, bd=2, sliderrelief="raised", relief="flat",
                         activebackground=BG_INPUT, length=180,
                         showvalue=False, command=lambda _v: _upd()).pack(side="left", padx=(4,4))
                tk.Label(row, textvariable=var, bg=BG_CARD, fg=TEXT,
                         font=("Consolas", 9), width=4).pack(side="left")

            btn_row = tk.Frame(inner, bg=BG_CARD)
            btn_row.pack(pady=(10, 0))

            def _apply():
                led_color_vars[led_idx].set(
                    f"{max(0,min(255,r_var.get())):02X}"
                    f"{max(0,min(255,g_var.get())):02X}"
                    f"{max(0,min(255,b_var.get())):02X}")
                _sync(); _rebuild_colors(); _rebuild_map(); dlg.destroy()

            RoundedButton(btn_row, text="Apply", command=_apply,
                          bg_color=ACCENT_BLUE, btn_width=80, btn_height=28,
                          btn_font=(FONT_UI, 8, "bold")).pack(side="left", padx=(0,8))
            RoundedButton(btn_row, text="Cancel", command=dlg.destroy,
                          bg_color="#555560", btn_width=80, btn_height=28,
                          btn_font=(FONT_UI, 8, "bold")).pack(side="left")
            _center_window(dlg, f.winfo_toplevel())
            dlg.grab_set()
            dlg.wait_window()

        # ══════════════════════════════════════════════════════════════
        # TWO-COLUMN LAYOUT
        #   left_col  (~370px) : wire note, enable/count/br, colors, loop
        #   right_col (rest)   : reactive toggle + mapping table
        # ══════════════════════════════════════════════════════════════
        two_col = tk.Frame(f, bg=BG_CARD)
        two_col.pack(fill="both", expand=True)
        two_col.columnconfigure(0, weight=0, minsize=370)
        two_col.columnconfigure(1, weight=0)
        two_col.columnconfigure(2, weight=1)

        left_col = tk.Frame(two_col, bg=BG_CARD)
        left_col.grid(row=0, column=0, sticky="nsw", padx=(0, 10))

        tk.Frame(two_col, bg=BORDER, width=1).grid(row=0, column=1, sticky="ns", padx=(0, 10))

        right_col = tk.Frame(two_col, bg=BG_CARD)
        right_col.grid(row=0, column=2, sticky="nsew")

        # ── LEFT: wire note ───────────────────────────────────────────
        tk.Label(left_col,
                 text="Wire SCK\u2192GP6, MOSI\u2192GP3, VCC\u2192VBUS(5V), GND\u2192GND.\n"
                      "GP3 & GP6 are reserved when LEDs are enabled.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7),
                 wraplength=355, justify="left").pack(anchor="w", pady=(0, 6))

        # ── LEFT: enable / count / brightness ────────────────────────
        ctrl_row = tk.Frame(left_col, bg=BG_CARD)
        ctrl_row.pack(anchor="w", pady=(0, 5))
        ttk.Checkbutton(ctrl_row, text="Enable LEDs",
                         variable=led_enabled_var, command=_sync).pack(side="left", padx=(0,10))
        tk.Label(ctrl_row, text="Count:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0,3))
        cnt_w = tk.Frame(ctrl_row, bg=BG_CARD, width=52, height=24)
        cnt_w.pack(side="left", padx=(0,8)); cnt_w.pack_propagate(False)
        _cvcmd = (self.root.register(lambda P: P == "" or P.isdigit()), '%P')
        cnt_sp = ttk.Spinbox(cnt_w, from_=1, to=MAX_LED_COUNT, width=4,
                              textvariable=led_count_var,
                              command=lambda: [_sync(), _rebuild_colors(), _rebuild_map()],
                              validate="key", validatecommand=_cvcmd)
        cnt_sp.pack(fill="both", expand=True)
        cnt_sp.bind("<KeyRelease>", lambda _e, widget=cnt_sp: _on_count_live_change(widget))
        cnt_sp.bind("<Return>",   lambda _e: [_sync(), _rebuild_colors(), _rebuild_map()])
        cnt_sp.bind("<FocusOut>", lambda _e: [_sync(), _rebuild_colors(), _rebuild_map()])
        tk.Label(ctrl_row, text=f"(max {MAX_LEDS})", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(0, 8))
        tk.Label(ctrl_row, text="Brightness:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0,3))
        br_w = tk.Frame(ctrl_row, bg=BG_CARD, width=52, height=24)
        br_w.pack(side="left", padx=(0,4)); br_w.pack_propagate(False)
        _bvcmd = (self.root.register(lambda P: P == "" or (P.isdigit() and 0 <= int(P) <= 9)), '%P')
        ttk.Spinbox(br_w, from_=0, to=9, width=4,
                    textvariable=led_brightness_var, command=_sync,
                    validate="key", validatecommand=_bvcmd).pack(fill="both", expand=True)
        tk.Label(ctrl_row, text="(0-9)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(3,0))

        # ── LEFT: LED color swatches ─────────────────────────────────
        colors_frame = tk.Frame(left_col, bg=BG_CARD)
        colors_frame.pack(anchor="w", pady=(0, 2))

        def _rebuild_colors():
            for w in colors_frame.winfo_children():
                w.destroy()
            count = led_count_var.get()
            if count < 1:
                return
            tk.Label(colors_frame,
                     text="LED Colors  (click swatch to change, ID button flashes LED):",
                     bg=BG_CARD, fg=TEXT, font=(FONT_UI, 7, "bold")).pack(
                anchor="w", pady=(0,3))
            grid_f = tk.Frame(colors_frame, bg=BG_CARD)
            grid_f.pack(anchor="w")
            COLS = 3
            for i in range(min(count, MAX_LED_COUNT)):
                col_i = i % COLS
                row_i = i // COLS
                cell = tk.Frame(grid_f, bg=BG_CARD)
                cell.grid(row=row_i, column=col_i, padx=2, pady=2, sticky="w")
                tk.Label(cell, text=f"LED {i+1}", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 7), width=5).pack(side="left")
                hex_c = led_color_vars[i].get().strip()
                if len(hex_c) != 6: hex_c = "FFFFFF"
                try:  bg_c = f"#{hex_c}"; int(hex_c, 16)
                except Exception: bg_c = "#FFFFFF"; hex_c = "FFFFFF"
                sw = tk.Canvas(cell, width=24, height=18, bg=bg_c,
                               highlightbackground=BORDER, highlightthickness=1,
                               cursor="hand2")
                sw.create_rectangle(0, 0, 24, 18, fill=bg_c, outline=bg_c)
                sw.pack(side="left", padx=(1,2))
                sw.bind("<Button-1>", lambda _e, idx=i: _open_color_dialog(idx))
                ib = RoundedButton(cell, text="Flash",
                                   bg_color=BG_INPUT, btn_width=40, btn_height=18,
                                   btn_font=(FONT_UI, 6, "bold"))
                def _ident(idx=i):
                    try: self.pico.led_flash(idx)
                    except Exception: pass
                ib._command = _ident; ib._render(ib._bg)
                ib.pack(side="left")

        _rebuild_colors()

        # ── LEFT: color loop row ──────────────────────────────────────
        tk.Frame(left_col, bg=BORDER, height=1).pack(fill="x", pady=(5, 4))
        loop_row = tk.Frame(left_col, bg=BG_CARD)
        loop_row.pack(anchor="w")
        ttk.Checkbutton(loop_row, text="Color Loop",
                         variable=led_loop_var, command=_sync).pack(side="left", padx=(0,8))
        tk.Label(loop_row, text="From:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0,2))
        lsw = tk.Frame(loop_row, bg=BG_CARD, width=48, height=22)
        lsw.pack(side="left", padx=(0,6)); lsw.pack_propagate(False)
        ttk.Spinbox(lsw, from_=1, to=MAX_LED_COUNT, width=3,
                    textvariable=led_loop_start_var, command=_sync).pack(fill="both", expand=True)
        tk.Label(loop_row, text="To:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0,2))
        lew = tk.Frame(loop_row, bg=BG_CARD, width=48, height=22)
        lew.pack(side="left", padx=(0,4)); lew.pack_propagate(False)
        ttk.Spinbox(lew, from_=1, to=MAX_LED_COUNT, width=3,
                    textvariable=led_loop_end_var, command=_sync).pack(fill="both", expand=True)
        tk.Label(loop_row, text="(smooth 1x/sec)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(4,0))

        # ── LEFT: breathe effect row ──────────────────────────────────
        def _on_breathe():
            if led_breathe_var.get():
                led_wave_var.set(False)
            _sync()

        def _on_wave():
            if led_wave_var.get():
                led_breathe_var.set(False)
            _sync()

        breathe_row = tk.Frame(left_col, bg=BG_CARD)
        breathe_row.pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(breathe_row, text="Breathe",
                         variable=led_breathe_var, command=_on_breathe).pack(side="left", padx=(0, 8))
        tk.Label(breathe_row, text="From:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
        bsw = tk.Frame(breathe_row, bg=BG_CARD, width=48, height=22)
        bsw.pack(side="left", padx=(0, 6)); bsw.pack_propagate(False)
        ttk.Spinbox(bsw, from_=1, to=MAX_LED_COUNT, width=3,
                    textvariable=led_breathe_start_var, command=_sync).pack(fill="both", expand=True)
        tk.Label(breathe_row, text="To:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
        bew = tk.Frame(breathe_row, bg=BG_CARD, width=48, height=22)
        bew.pack(side="left", padx=(0, 6)); bew.pack_propagate(False)
        ttk.Spinbox(bew, from_=1, to=MAX_LED_COUNT, width=3,
                    textvariable=led_breathe_end_var, command=_sync).pack(fill="both", expand=True)
        tk.Label(breathe_row, text="Min:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
        bminw = tk.Frame(breathe_row, bg=BG_CARD, width=48, height=22)
        bminw.pack(side="left", padx=(0, 6)); bminw.pack_propagate(False)
        ttk.Spinbox(bminw, from_=0, to=9, width=3,
                    textvariable=led_breathe_min_var, command=_sync,
                    validate="key", validatecommand=_bvcmd).pack(fill="both", expand=True)
        tk.Label(breathe_row, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
        bmaxw = tk.Frame(breathe_row, bg=BG_CARD, width=48, height=22)
        bmaxw.pack(side="left", padx=(0, 4)); bmaxw.pack_propagate(False)
        ttk.Spinbox(bmaxw, from_=0, to=9, width=3,
                    textvariable=led_breathe_max_var, command=_sync,
                    validate="key", validatecommand=_bvcmd).pack(fill="both", expand=True)
        tk.Label(breathe_row, text="(0–9)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(3, 0))

        # ── LEFT: wave effect row ─────────────────────────────────────
        wave_row = tk.Frame(left_col, bg=BG_CARD)
        wave_row.pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(wave_row, text="Ripple",
                         variable=led_wave_var, command=_on_wave).pack(side="left", padx=(0, 8))
        tk.Label(wave_row, text="Origin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
        wow = tk.Frame(wave_row, bg=BG_CARD, width=48, height=22)
        wow.pack(side="left", padx=(0, 6)); wow.pack_propagate(False)
        ttk.Spinbox(wow, from_=1, to=MAX_LED_COUNT, width=3,
                    textvariable=led_wave_origin_var, command=_sync).pack(fill="both", expand=True)
        tk.Label(wave_row, text="(brightness pulse radiates from origin on keypress)",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left", padx=(4, 0))

        # ── RIGHT: reactive toggle + mapping table ────────────────────
        react_hdr = tk.Frame(right_col, bg=BG_CARD)
        react_hdr.pack(anchor="w", pady=(0, 4))
        ttk.Checkbutton(react_hdr, text="Reactive LEDs on keypress",
                         variable=led_reactive_var,
                         command=lambda: [_sync(), _rebuild_map()]).pack(
            side="left", padx=(0, 8))
        tk.Label(react_hdr, text="LEDs light up when input pressed",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")

        map_outer = tk.Frame(right_col, bg=BG_CARD)
        map_outer.pack(fill="both", expand=True)

        def _rebuild_map():
            for w in map_outer.winfo_children():
                w.destroy()
            if not led_reactive_var.get():
                return
            count = led_count_var.get()
            if count < 1:
                return

            tk.Label(map_outer, text="Input \u2192 LED Mapping",
                     bg=BG_CARD, fg=TEXT, font=(FONT_UI, 7, "bold")).pack(
                anchor="w", pady=(2, 2))

            grid = tk.Frame(map_outer, bg=BG_CARD)
            grid.pack(anchor="w")

            led_col_start = 1
            bright_col    = led_col_start + min(count, MAX_LED_COUNT)

            tk.Label(grid, text="Input", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 7, "bold"), anchor="w", width=10).grid(
                row=0, column=0, sticky="w", padx=(0, 2))
            for j in range(min(count, MAX_LED_COUNT)):
                hex_c = led_color_vars[j].get().strip()
                if len(hex_c) != 6: hex_c = "FFFFFF"
                try:  bg_c = f"#{hex_c}"; int(hex_c, 16)
                except Exception: bg_c = "#FFFFFF"; hex_c = "FFFFFF"
                tk.Label(grid, text=f"{j}", bg=bg_c, fg=_text_for_bg(hex_c),
                         font=(FONT_UI, 6, "bold"),
                         relief="flat", bd=0, padx=2, pady=0).grid(
                    row=0, column=led_col_start + j, padx=1, pady=(0, 2))
            tk.Label(grid, text="Brightness", bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 7, "bold")).grid(
                row=0, column=bright_col, padx=(4, 0))

            _EASY_ROWS = [0, 1, 2, 3, 4, 5, 6, 7, 8]
            _GROUP_LABELS = {0: "Frets", 5: "Strum", 7: "Start/Select"}

            grid_row = 1
            for inp_idx in _EASY_ROWS:
                if inp_idx in _GROUP_LABELS:
                    tk.Label(grid, text=_GROUP_LABELS[inp_idx],
                             bg=BG_CARD, fg=TEXT_DIM,
                             font=(FONT_UI, 6, "bold")).grid(
                        row=grid_row, column=0,
                        columnspan=bright_col + 1, sticky="w",
                        padx=(0, 0), pady=(3, 0))
                    grid_row += 1

                name_fr = tk.Frame(grid, bg=BG_CARD)
                name_fr.grid(row=grid_row, column=0, sticky="w", padx=(6, 2), pady=0)
                color = FRET_COLORS.get(LED_INPUT_NAMES[inp_idx])
                if color:
                    dot = tk.Canvas(name_fr, width=8, height=8, bg=BG_CARD,
                                    highlightthickness=0, bd=0)
                    dot.create_oval(1, 1, 7, 7, fill=color, outline=color)
                    dot.pack(side="left", padx=(0, 2))
                tk.Label(name_fr, text=LED_INPUT_LABELS[inp_idx],
                         bg=BG_CARD, fg=TEXT,
                         font=(FONT_UI, 7), anchor="w").pack(side="left")

                current_mask = led_map_vars[inp_idx].get()
                cb_vars_row = []
                for j in range(min(count, MAX_LED_COUNT)):
                    var = tk.BooleanVar(value=bool(current_mask & (1 << j)))
                    def _update_map(i=inp_idx, cvs=cb_vars_row):
                        mask = sum((1 << jj) for jj, v in enumerate(cvs) if v.get())
                        led_map_vars[i].set(mask); _sync()
                    cb = ttk.Checkbutton(grid, variable=var, command=_update_map)
                    cb.grid(row=grid_row, column=led_col_start + j, padx=0, pady=0)
                    cb_vars_row.append(var)

                bw = tk.Frame(grid, bg=BG_CARD, width=52, height=22)
                bw.grid(row=grid_row, column=bright_col, padx=(4, 0), pady=1)
                bw.pack_propagate(False)
                ttk.Spinbox(bw, from_=0, to=9, width=3,
                            textvariable=led_active_vars[inp_idx],
                            command=_sync,
                            validate="key", validatecommand=_bvcmd).pack(fill="both", expand=True)
                grid_row += 1

        def _on_count_live_change(widget):
            raw = widget.get().strip()
            if not raw:
                return
            try:
                led_count_var.set(int(raw))
            except (ValueError, tk.TclError):
                return
            _sync()
            _rebuild_colors()
            _rebuild_map()

        _rebuild_map()


    def _build_placeholder_content(self, name):
        f = self._body_frame

        if name != "Review & Save":
            tk.Label(f,
                     text=f"{name} configuration is not yet implemented.\nCheck back in a future update.",
                     bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 12), justify="left").pack(anchor="nw", pady=(30, 20))
            return

        # ── ASCII art live button preview ─────────────────────────────────────
        _ART_LINES = [
            "                          ____  Whammy ___",
            "                        ,' __ ``.._..''   `.",
            "                        `.`. ``-.___..-.    :",
            " ,---..____________________>/  Up      _,'_  |",
            " `-:._,:G|R|Y|B|O|_|_|_|_|_|_|.:===:.:|-|(/  |",
            "                       _.' ) Down__  '-'    ;",
            "                      (    `-''  __``-'    /",
            "                       ``-....-''  ``-..-''",
            "                        Select   Start",
        ]
        _ART_BUTTON_MAP = [
            ("green",      "G",      4),
            ("red",        "R",      4),
            ("yellow",     "Y",      4),
            ("blue",       "B",      4),
            ("orange",     "O",      4),
            ("strum_up",   "Up",     3),
            ("strum_down", "Down",   5),
            ("select",     "Select", 8),
            ("start",      "Start",  8),
        ]

        # Precompute char positions: {key: (line_idx, col, length)}
        _label_pos = {}
        for key, label, line_idx in _ART_BUTTON_MAP:
            col = _ART_LINES[line_idx].find(label)
            if col >= 0:
                _label_pos[key] = (line_idx, col, len(label))

        # Build pin → key map from currently detected assignments
        _pin_to_key = {}
        for key, _lbl, _li in _ART_BUTTON_MAP:
            pin = self.detected.get(key, -1)
            if isinstance(pin, int) and pin >= 0:
                _pin_to_key[pin] = key

        txt = tk.Text(f, bg=BG_CARD, fg=TEXT_DIM,
                      font=("Courier New", 10), bd=0, highlightthickness=0,
                      cursor="arrow", wrap="none",
                      height=len(_ART_LINES),
                      width=max(len(l) for l in _ART_LINES))
        txt.tag_configure("lit", foreground="white", font=("Courier New", 10, "bold"))
        txt.insert("1.0", "\n".join(_ART_LINES))
        txt.config(state="disabled")
        txt.pack(anchor="nw", pady=(16, 8))

        def _redraw(active_keys):
            txt.config(state="normal")
            txt.tag_remove("lit", "1.0", "end")
            for key in active_keys:
                if key in _label_pos:
                    li, col, length = _label_pos[key]
                    txt.tag_add("lit", f"{li+1}.{col}", f"{li+1}.{col+length}")
            txt.config(state="disabled")

        def _poll():
            if not self._preview_active:
                return
            now = time.time()
            # 500ms window — firmware repeats PIN every 300ms while held.
            # 500ms gives 200ms of headroom for USB-CDC jitter so the label
            # stays lit continuously during a hold and clears ~500ms after release.
            active = {_pin_to_key[p] for p, ts in self._preview_seen.items()
                      if now - ts < 0.50 and p in _pin_to_key}
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

        def _stop_preview():
            if self._preview_active:
                self._preview_active = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass

        def _wireless_action(mode):
            _stop_preview()
            mode_name = "Wireless Dongle" if mode == 0 else "Wireless Bluetooth"

            def _worker():
                # The scan thread has a 50 ms read timeout; give it time to exit
                # before we take the serial port for the wireless-mode write.
                time.sleep(0.2)
                # Flush any PIN: lines that accumulated in the OS receive buffer
                # while the scan was running.  Without this, send() reads a stale
                # PIN: line instead of the DEVTYPE: response to GET_CONFIG.
                self.pico.flush_input()
                last_exc = None
                for attempt in range(3):
                    if attempt > 0:
                        time.sleep(0.3)
                    try:
                        if not self.pico.connected:
                            raise RuntimeError("Not connected")
                        cfg = self.pico.get_config()
                        if "wireless_default_mode" not in cfg:
                            self.root.after(0, lambda: messagebox.showinfo(
                                "Not Supported",
                                "This setting is only available for wireless guitar firmware.\n\n"
                                "Wired controllers and older firmware do not support this option."
                            ))
                            self.root.after(0, _start_preview)
                            return
                        self.pico.set_value("wireless_default_mode", str(mode))
                        self.pico.save()
                        self.root.after(0, lambda: messagebox.showinfo(
                            "Wireless Mode Set",
                            f"Default wireless mode set to:  {mode_name}\n\n"
                            f"The controller will boot in {mode_name} mode by default\n"
                            f"when not connected via USB."
                        ))
                        self.root.after(0, _start_preview)
                        return
                    except Exception as exc:
                        last_exc = exc
                # All 3 attempts failed
                self.root.after(0, lambda e=str(last_exc): messagebox.showerror(
                    "Error",
                    f"Could not set wireless mode after 3 attempts:\n{e}"
                ))
                self.root.after(0, _start_preview)

            threading.Thread(target=_worker, daemon=True).start()

        _start_preview()

        # ── Export convenience block ──────────────────────────────────────────
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(0, 20))

        tk.Label(f,
                 text="Here is an export configuration button for your convenience.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11),
                 justify="left").pack(anchor="nw", pady=(0, 14))

        RoundedButton(f, text="Export Configuration\u2026",
                      command=self._easy_export_config,
                      bg_color=ACCENT_BLUE,
                      btn_width=200, btn_height=36).pack(anchor="nw")

        # ── Wireless mode selection ───────────────────────────────────────────
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(20, 0))

        tk.Label(f,
                 text="Choose default wireless mode.\n"
                      "Will do nothing for a wired controller.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11),
                 justify="left").pack(anchor="nw", pady=(14, 10))

        btn_frame = tk.Frame(f, bg=BG_CARD)
        btn_frame.pack(anchor="nw")

        RoundedButton(btn_frame, text="Wireless Dongle",
                      command=lambda: _wireless_action(0),
                      bg_color=ACCENT_BLUE,
                      btn_width=160, btn_height=36).pack(side="left", padx=(0, 10))

        RoundedButton(btn_frame, text="Wireless Bluetooth",
                      command=lambda: _wireless_action(1),
                      bg_color=ACCENT_GREEN,
                      btn_width=180, btn_height=36).pack(side="left")

        tk.Label(f,
                 text="Hold guide for 3 seconds to switch wireless modes on the fly.",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9),
                 justify="left").pack(anchor="nw", pady=(8, 0))


    # ── Easy Config export ───────────────────────────────────────

    def _easy_export_config(self):
        """
        Save all values collected during the Easy Config walkthrough to a
        JSON file.  Uses the same data dict (self.detected) that _finish_and_save
        pushes to the firmware, so the exported file always matches what was
        configured.  Does NOT require a live controller connection.
        """
        d = self.detected
        date_str = datetime.datetime.now().strftime("%m-%d-%Y")
        default_name = f"Easy Config {date_str}"

        path = filedialog.asksaveasfilename(
            title="Export Configuration",
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        def _pin(key):
            v = d.get(key, -1)
            return v if v is not None else -1

        cfg = {}

        # -- Digital button pins
        for key in ("green", "red", "yellow", "blue", "orange",
                    "strum_up", "strum_down", "start", "select",
                    "dpad_up", "dpad_down", "dpad_left", "dpad_right"):
            cfg[key] = _pin(key)

        # -- Guide / joystick SW
        cfg["guide"]      = _pin("guide")
        cfg["joy_pin_sw"] = _pin("joy_sw")

        # -- Joystick axes
        cfg["joy_pin_x"]         = _pin("joy_x")
        cfg["joy_pin_y"]         = _pin("joy_y")
        cfg["joy_dpad_x"]        = 1 if _pin("joy_x") not in (-1, None) else 0
        cfg["joy_dpad_y"]        = 1 if _pin("joy_y") not in (-1, None) else 0
        cfg["joy_dpad_x_invert"] = 1 if d.get("joy_dpad_x_invert") else 0
        cfg["joy_dpad_y_invert"] = 1 if d.get("joy_dpad_y_invert") else 0
        cfg["joy_whammy_axis"]   = 0
        cfg["joy_deadzone"]      = 410

        # -- Whammy
        cfg["whammy_mode"]   = d.get("whammy_mode", "digital")
        cfg["whammy_pin"]    = _pin("whammy_pin")
        cfg["whammy_min"]    = d.get("whammy_min", 0)
        cfg["whammy_max"]    = d.get("whammy_max", 4095)
        cfg["whammy_invert"] = 1 if d.get("whammy_invert") else 0

        # -- Tilt
        cfg["tilt_mode"]    = d.get("tilt_mode", "digital")
        cfg["tilt_pin"]     = _pin("tilt_pin")
        cfg["tilt_min"]     = d.get("tilt_min", 0)
        cfg["tilt_max"]     = d.get("tilt_max", 4095)
        cfg["tilt_invert"]  = 1 if d.get("tilt_invert") else 0
        cfg["i2c_model"]    = d.get("i2c_model", 0)
        cfg["adxl345_axis"] = d.get("tilt_axis", 0)
        cfg["i2c_sda"]      = d.get("i2c_sda", 4)
        cfg["i2c_scl"]      = d.get("i2c_scl", 5)

        # -- Smoothing
        tilt_ema   = d.get("tilt_ema_alpha")
        whammy_ema = d.get("whammy_ema_alpha")
        cfg["ema_alpha"] = (tilt_ema if tilt_ema is not None
                            else (whammy_ema if whammy_ema is not None else 140))

        # -- LEDs
        cfg["led_enabled"]      = 1 if d.get("led_enabled") else 0
        cfg["led_count"]        = d.get("led_count", 9)
        cfg["led_brightness"]   = d.get("led_brightness", 2)
        cfg["led_loop_enabled"]    = 1 if d.get("led_loop_enabled") else 0
        cfg["led_loop_start"]      = d.get("led_loop_start", 0)
        cfg["led_loop_end"]        = d.get("led_loop_end", 0)
        cfg["led_breathe_enabled"] = 1 if d.get("led_breathe_enabled") else 0
        cfg["led_breathe_start"]   = d.get("led_breathe_start", 0)
        cfg["led_breathe_end"]     = d.get("led_breathe_end", 0)
        cfg["led_breathe_min"]     = d.get("led_breathe_min", 0)
        cfg["led_breathe_max"]     = d.get("led_breathe_max", 31)
        cfg["led_wave_enabled"]    = 1 if d.get("led_wave_enabled") else 0
        cfg["led_wave_origin"]     = d.get("led_wave_origin", 0)
        colors = d.get("led_colors", ["FFFFFF"] * MAX_LEDS)
        cfg["led_colors"] = [str(c).strip().upper().lstrip("#").zfill(6)
                             for c in colors[:MAX_LEDS]]
        maps = d.get("led_maps", [0] * LED_INPUT_COUNT)
        cfg["led_maps"] = [int(m) for m in maps[:LED_INPUT_COUNT]]
        active_br = d.get("led_active_br", [8] * LED_INPUT_COUNT)
        cfg["led_active_br"] = [int(b) for b in active_br[:LED_INPUT_COUNT]]

        cfg["device_name"] = "Guitar Controller"

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
            messagebox.showinfo("Export Successful",
                                f"Configuration exported to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    # ── Wireless mode default ─────────────────────────────────────

    def _set_wireless_default(self, mode):
        """Set wireless_default_mode: 0=Dongle, 1=Bluetooth. Saves immediately.

        Only meaningful for combined wireless guitar firmware; shows a friendly
        message for wired controllers or firmware that doesn't support the key.
        """
        if not self.pico.connected:
            messagebox.showinfo("Not Connected",
                                "Connect to the controller first, then try again.")
            return

        try:
            cfg = self.pico.get_config()
        except Exception as exc:
            messagebox.showerror("Read Error",
                                 f"Could not read configuration:\n{exc}")
            return

        if "wireless_default_mode" not in cfg:
            messagebox.showinfo(
                "Not Supported",
                "This setting is only available for wireless guitar firmware.\n\n"
                "Wired controllers and older firmware do not support this option."
            )
            return

        mode_name = "Wireless Dongle" if mode == 0 else "Wireless Bluetooth"
        try:
            self.pico.set_value("wireless_default_mode", str(mode))
            self.pico.save()
        except Exception as exc:
            messagebox.showerror("Write Error",
                                 f"Could not save setting:\n{exc}")
            return

        messagebox.showinfo(
            "Wireless Mode Set",
            f"Default wireless mode set to:  {mode_name}\n\n"
            f"The controller will boot in {mode_name} mode by default\n"
            f"when not connected via USB."
        )

    # ── Tilt sensor page ──────────────────────────────────────────

    def _build_tilt_content(self):
        f = self._body_frame

        EMA_TABLE = [256, 230, 200, 170, 140, 110, 80, 55, 35, 20]

        tk.Label(f, text="Assign an input to the Tilt Sensor.",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11)).pack(anchor="w", pady=(0, 4))
        tk.Label(f,
                 text="Digital: any GPIO 0\u201322 (tilt switch).\n"
                      "Analog: ADC pins GPIO 26\u201329 (sensor on ADC pin).\n"
                      "I2C Accelerometer: ADXL345 or LIS3DH connected via I2C0 (auto-detected on scan).",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(0, 12))

        mode_var = tk.StringVar(value=self.detected.get("tilt_mode", "i2c"))
        mode_row = tk.Frame(f, bg=BG_CARD)
        mode_row.pack(anchor="w", pady=(0, 10))
        tk.Label(mode_row, text="Mode:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 10))
        for val, lbl in [("digital", "Digital"),
                          ("analog",  "Analog"),
                          ("i2c",     "I2C Accelerometer")]:
            tk.Radiobutton(mode_row, text=lbl, variable=mode_var, value=val,
                            bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                            activebackground=BG_CARD, activeforeground=TEXT,
                            font=(FONT_UI, 9)).pack(side="left", padx=(0, 14))

        # ── Calibration vars (stored in detected on change) ───────────────────
        tilt_min_var    = tk.IntVar(value=self.detected.get("tilt_min", 0))
        tilt_max_var    = tk.IntVar(value=self.detected.get("tilt_max", 4095))
        tilt_invert_var = tk.BooleanVar(value=bool(self.detected.get("tilt_invert", False)))
        tilt_smooth_var = tk.IntVar(value=self.detected.get("tilt_smooth", 4))
        _ema_alpha_var  = tk.IntVar(value=EMA_TABLE[self.detected.get("tilt_smooth", 4)])

        def _sync_tilt_cal(*_):
            self.detected["tilt_min"]       = tilt_min_var.get()
            self.detected["tilt_max"]       = tilt_max_var.get()
            self.detected["tilt_invert"]    = tilt_invert_var.get()
            lvl = tilt_smooth_var.get()
            self.detected["tilt_smooth"]    = lvl
            self.detected["tilt_ema_alpha"] = EMA_TABLE[lvl]
            _ema_alpha_var.set(EMA_TABLE[lvl])

        tilt_min_var.trace_add("write",    _sync_tilt_cal)
        tilt_max_var.trace_add("write",    _sync_tilt_cal)
        tilt_invert_var.trace_add("write", _sync_tilt_cal)
        tilt_smooth_var.trace_add("write", _sync_tilt_cal)

        # I2C chip info + axis selector (hidden until I2C detection)
        i2c_row = tk.Frame(f, bg=BG_CARD)
        i2c_chip_lbl = tk.Label(i2c_row, text="", bg=BG_CARD, fg=ACCENT_GREEN,
                                 font=(FONT_UI, 9, "bold"))
        i2c_chip_lbl.pack(side="left", padx=(0, 14))
        axis_var = tk.IntVar(value=self.detected.get("tilt_axis", 0))
        tk.Label(i2c_row, text="Monitor Axis:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 6))
        for av, al in [(0, "X"), (1, "Y"), (2, "Z")]:
            tk.Radiobutton(i2c_row, text=al, variable=axis_var, value=av,
                            bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                            activebackground=BG_CARD, font=(FONT_UI, 9)).pack(side="left", padx=(0, 10))

        _sf, status_lbl, gpio_lbl = self._make_status_box(
            f, idle_text="Choose Digital or Analog, then Click to Start Input Detection")
        idle_text = "Choose Digital or Analog, then Click to Start Input Detection"
        tmode = self.detected.get("tilt_mode")
        if tmode == "i2c":
            chip = "LIS3DH" if self.detected.get("i2c_model", 0) == 1 else "ADXL345"
            status_lbl.config(text=f"\u2713 I2C accelerometer: {chip}", fg=ACCENT_GREEN)
            gpio_lbl.config(text=chip)
            i2c_chip_lbl.config(text=f"Chip: {chip}")
            i2c_row.pack(anchor="w", pady=(0, 8))
        elif tmode in ("analog", "digital") and "tilt_pin" in self.detected:
            pin = self.detected["tilt_pin"]
            status_lbl.config(text=f"\u2713 Previously set to GPIO {pin} ({tmode}).", fg=ACCENT_GREEN)
            gpio_lbl.config(text=f"GPIO {pin}")

        # ── Two-column calibration panel (hidden until detection) ───────────
        # col_outer is the full-width container; it houses left and right columns.
        col_outer = tk.Frame(f, bg=BG_CARD)
        _live_val = [0]

        left_col  = tk.Frame(col_outer, bg=BG_CARD)
        right_col = tk.Frame(col_outer, bg=BG_CARD)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right_col.pack(side="left", fill="both", expand=True)

        # ── LEFT: live raw bar ────────────────────────────────────────
        tk.Label(left_col, text="Live Value:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9)).pack(anchor="w", pady=(8, 2))
        bar = LiveBarGraph(left_col, label="Tilt", width=430, height=28,
                           min_marker_var=tilt_min_var, max_marker_var=tilt_max_var)
        bar.pack(fill="x")

        # Controls row below bar
        btn_row = tk.Frame(left_col, bg=BG_CARD)
        btn_row.pack(anchor="w", pady=(6, 0))

        def _set_tilt_min():
            tilt_min_var.set(max(0, min(4094, _live_val[0])))
        def _set_tilt_max():
            tilt_max_var.set(max(1, min(4095, _live_val[0])))
        def _reset_tilt_sens():
            tilt_min_var.set(0)
            tilt_max_var.set(4095)

        RoundedButton(btn_row, text="Set Min", bg_color="#555560",
                      btn_width=62, btn_height=22, btn_font=(FONT_UI, 8, "bold"),
                      command=_set_tilt_min).pack(side="left", padx=(0, 4))
        RoundedButton(btn_row, text="Set Max", bg_color="#555560",
                      btn_width=62, btn_height=22, btn_font=(FONT_UI, 8, "bold"),
                      command=_set_tilt_max).pack(side="left", padx=(0, 4))
        RoundedButton(btn_row, text="Reset",   bg_color="#555560",
                      btn_width=48, btn_height=22, btn_font=(FONT_UI, 8, "bold"),
                      command=_reset_tilt_sens).pack(side="left", padx=(0, 8))
        tk.Checkbutton(btn_row, text="Invert", variable=tilt_invert_var,
                        bg=BG_CARD, fg=TEXT, selectcolor=BG_INPUT,
                        activebackground=BG_CARD, activeforeground=TEXT,
                        font=(FONT_UI, 9)).pack(side="left")

        # Min/Max readout
        range_row = tk.Frame(left_col, bg=BG_CARD)
        range_row.pack(anchor="w", pady=(4, 0))
        min_lbl = tk.Label(range_row, text=f"Min: {tilt_min_var.get()}",
                            bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8))
        min_lbl.pack(side="left")
        max_lbl = tk.Label(range_row, text=f"Max: {tilt_max_var.get()}",
                            bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8))
        max_lbl.pack(side="left", padx=(12, 0))
        tilt_min_var.trace_add("write", lambda *_: min_lbl.config(text=f"Min: {tilt_min_var.get()}"))
        tilt_max_var.trace_add("write", lambda *_: max_lbl.config(text=f"Max: {tilt_max_var.get()}"))

        # Smoothing slider
        sm_row = tk.Frame(left_col, bg=BG_CARD)
        sm_row.pack(anchor="w", pady=(4, 0))
        tk.Label(sm_row, text="Smoothing:", bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 4))
        tk.Label(sm_row, text="0", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
        smooth_readout = tk.Label(sm_row, text="", bg=BG_CARD, fg=TEXT_DIM,
                                   font=(FONT_UI, 8), width=14, anchor="w")

        def _on_smooth(val):
            lvl = int(float(val))
            _sync_tilt_cal()
            txt = f"Lv{lvl}" if lvl == 0 else f"Lv{lvl} (\u03b1{EMA_TABLE[lvl]})"
            smooth_readout.config(text=txt)

        smooth_slider = tk.Scale(sm_row, from_=0, to=9, orient="horizontal",
                                  variable=tilt_smooth_var, showvalue=False,
                                  bg=BG_CARD, fg=TEXT, troughcolor=BG_INPUT,
                                  highlightthickness=0, length=90, sliderlength=14,
                                  resolution=1, command=_on_smooth)
        smooth_slider.pack(side="left", padx=(0, 2))
        tk.Label(sm_row, text="9", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 6))
        smooth_readout.pack(side="left")
        _on_smooth(tilt_smooth_var.get())

        # ── RIGHT: calibrated output bar ─────────────────────────────
        tk.Label(right_col, text="Calibrated Output:", bg=BG_CARD,
                 fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(8, 2))
        cal_bar = CalibratedBarGraph(right_col, label="Tilt Cal",
                                     width=430, height=28,
                                     min_var=tilt_min_var, max_var=tilt_max_var,
                                     invert_var=tilt_invert_var,
                                     ema_alpha_var=_ema_alpha_var)
        cal_bar.pack(fill="x")

        # ── Shared change handlers ────────────────────────────────────
        def _on_cal_change(*_):
            if cal_bar.winfo_exists():
                cal_bar.redraw()
            if bar.winfo_exists():
                bar.redraw_markers()
        tilt_min_var.trace_add("write",    _on_cal_change)
        tilt_max_var.trace_add("write",    _on_cal_change)
        tilt_invert_var.trace_add("write", _on_cal_change)

        _orig_set = bar.set_value
        def _patched_set(v):
            _orig_set(v)
            _live_val[0] = int(v)
            if cal_bar.winfo_exists():
                cal_bar.set_raw(v)
        bar.set_value = _patched_set

        # Helper: reveal the two-column panel
        def _show_tilt_cal():
            col_outer.pack(fill="x", pady=(8, 0))
            cal_bar.reset_ema()

        detect_btn, cancel_btn = self._make_detect_cancel_row(f, ACCENT_BLUE)

        def _restore_idle():
            detect_btn.set_state("normal")
            cancel_btn.set_state("disabled")
            status_lbl.config(text=idle_text, fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

        def start_detect():
            if not self.pico.connected:
                status_lbl.config(text="\u26a0  Not connected to controller.", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                return
            mode = mode_var.get()
            self.scanning = True
            self.scan_target = "tilt_pin"
            detect_btn.set_state("disabled")
            cancel_btn.set_state("normal")
            if mode == "i2c":
                status_lbl.config(text="Probing I2C pins\u2026 (checking GP4/5, GP0/1, and more)", fg=ACCENT_BLUE)
            elif mode == "analog":
                status_lbl.config(text="Waiting\u2026  Move the tilt sensor now.", fg=ACCENT_BLUE)
            else:
                status_lbl.config(text="Waiting\u2026  Tilt the controller now.", fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

            def _on_i2c(device_name):
                chip = "LIS3DH" if "LIS3DH" in device_name.upper() else "ADXL345"
                self.detected["tilt_mode"] = "i2c"
                self.detected["i2c_model"] = 1 if chip == "LIS3DH" else 0
                self.detected.pop("tilt_pin", None)
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text=f"\u2713 I2C accelerometer detected: {chip}!", fg=ACCENT_GREEN)
                gpio_lbl.config(text=chip)
                i2c_chip_lbl.config(text=f"Chip: {chip}")
                i2c_row.pack(anchor="w", pady=(0, 8))
                _show_tilt_cal()
                self._start_monitor("i2c", None, bar, prefix="tilt", axis=axis_var.get())

            def _on_detected(pin, det_mode):
                def _commit():
                    self.detected["tilt_pin"] = pin
                    self.detected["tilt_mode"] = det_mode
                    detect_btn.set_state("normal")
                    cancel_btn.set_state("disabled")
                    status_lbl.config(text=f"\u2713 Detected on GPIO {pin} ({det_mode})!", fg=ACCENT_GREEN)
                    gpio_lbl.config(text=f"GPIO {pin}")
                    if det_mode == "analog":
                        _show_tilt_cal()
                        self._start_monitor("analog", pin, bar, prefix="tilt")

                self._handle_detected_pin("tilt_pin", pin, _commit, _restore_idle)

            def _on_error(msg):
                self.scanning = False
                status_lbl.config(text=f"\u26a0  Scan error: {msg}", fg=ACCENT_RED)
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")

            # Common Pico I2C0 SDA/SCL pin pairs to auto-probe
            _I2C_PIN_PAIRS = [(4, 5), (0, 1), (8, 9), (12, 13), (16, 17), (20, 21)]

            def _show_manual_pin_dialog():
                """Pop-up so the user can manually specify SDA + SCL if auto fails."""
                dlg = tk.Toplevel(f.winfo_toplevel())
                dlg.title("Manual I2C Pin Assignment")
                dlg.configure(bg=BG_CARD)
                dlg.resizable(False, False)
                dlg.transient(f.winfo_toplevel())

                inner = tk.Frame(dlg, bg=BG_CARD)
                inner.pack(padx=20, pady=16)

                tk.Label(inner, text="I2C Accelerometer Not Auto-Detected",
                         bg=BG_CARD, fg=TEXT_HEADER,
                         font=(FONT_UI, 11, "bold")).pack(anchor="w", pady=(0, 6))
                tk.Label(inner,
                         text="Auto-scan checked all common I2C pin pairs and found nothing.\n"
                              "Enter the SDA and SCL GPIO pins your accelerometer is wired to:",
                         bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 9), wraplength=320,
                         justify="left").pack(anchor="w", pady=(0, 12))

                pin_row = tk.Frame(inner, bg=BG_CARD)
                pin_row.pack(anchor="w", pady=(0, 12))
                tk.Label(pin_row, text="SDA (GPIO):", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 9)).pack(side="left", padx=(0, 6))
                sda_w = tk.Frame(pin_row, bg=BG_CARD, width=60, height=24)
                sda_w.pack(side="left", padx=(0, 16)); sda_w.pack_propagate(False)
                sda_var = tk.IntVar(value=self.detected.get("i2c_sda", 4))
                ttk.Spinbox(sda_w, from_=0, to=22, width=4,
                            textvariable=sda_var).pack(fill="both", expand=True)
                tk.Label(pin_row, text="SCL (GPIO):", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 9)).pack(side="left", padx=(0, 6))
                scl_w = tk.Frame(pin_row, bg=BG_CARD, width=60, height=24)
                scl_w.pack(side="left"); scl_w.pack_propagate(False)
                scl_var = tk.IntVar(value=self.detected.get("i2c_scl", 5))
                ttk.Spinbox(scl_w, from_=0, to=22, width=4,
                            textvariable=scl_var).pack(fill="both", expand=True)

                result = [None]

                btn_row = tk.Frame(inner, bg=BG_CARD)
                btn_row.pack(pady=(0, 0))

                def _try_manual():
                    sda = sda_var.get()
                    scl = scl_var.get()
                    result[0] = (sda, scl)
                    dlg.destroy()

                def _skip():
                    dlg.destroy()

                RoundedButton(btn_row, text="Try These Pins", command=_try_manual,
                              bg_color=ACCENT_BLUE, btn_width=130, btn_height=28,
                              btn_font=(FONT_UI, 8, "bold")).pack(side="left", padx=(0, 8))
                RoundedButton(btn_row, text="Skip", command=_skip,
                              bg_color="#555560", btn_width=70, btn_height=28,
                              btn_font=(FONT_UI, 8, "bold")).pack(side="left")

                root_win = f.winfo_toplevel()
                dlg.update_idletasks()
                dlg.geometry(
                    f"+{root_win.winfo_rootx()+(root_win.winfo_width()-dlg.winfo_reqwidth())//2}"
                    f"+{root_win.winfo_rooty()+(root_win.winfo_height()-dlg.winfo_reqheight())//2}")
                dlg.grab_set(); dlg.wait_window()
                return result[0]

            def _thread():
                try:
                    if mode == "i2c":
                        # Try all common I2C pin pairs automatically
                        found_device = None
                        tried_pairs = list(_I2C_PIN_PAIRS)
                        # Also include the currently-configured pins if not already in list
                        cur_sda = self.detected.get("i2c_sda", 4)
                        cur_scl = self.detected.get("i2c_scl", 5)
                        if (cur_sda, cur_scl) not in tried_pairs:
                            tried_pairs.insert(0, (cur_sda, cur_scl))

                        for sda, scl in tried_pairs:
                            if not self.scanning:
                                return
                            try:
                                self.pico.set_value("i2c_sda", str(sda))
                                self.pico.set_value("i2c_scl", str(scl))
                            except Exception:
                                continue
                            try:
                                pre_lines = self.pico.start_scan()
                                found_i2c = None
                                for pl in pre_lines:
                                    if pl.startswith("I2C:"):
                                        found_i2c = pl[4:]
                                        break
                                if found_i2c is None:
                                    # Poll briefly for a response
                                    import time as _time
                                    deadline = _time.time() + 1.5
                                    while self.scanning and _time.time() < deadline:
                                        line = self.pico.read_scan_line(0.15)
                                        if line and line.startswith("I2C:"):
                                            found_i2c = line[4:]
                                            break
                                self.pico.stop_scan()
                                if found_i2c:
                                    self.detected["i2c_sda"] = sda
                                    self.detected["i2c_scl"] = scl
                                    self.scanning = False
                                    self.root.after(0, lambda d=found_i2c: _on_i2c(d))
                                    return
                            except Exception:
                                try: self.pico.stop_scan()
                                except Exception: pass

                        # No pair worked — offer manual entry on the UI thread
                        if not self.scanning:
                            return
                        self.scanning = False
                        self.root.after(0, lambda: _no_i2c_found())
                        return

                    # Digital / analog modes
                    pre_lines = self.pico.start_scan()
                    while self.scanning:
                        line = self.pico.read_scan_line(0.1)
                        if not line:
                            continue
                        if line.startswith("PIN:"):
                            try:
                                pin = int(line[4:])
                            except ValueError:
                                continue
                            if mode == "digital" and 0 <= pin <= 22:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p, "digital"))
                                return
                        elif line.startswith("APIN:"):
                            try:
                                pin = int(line[5:].split(":")[0])
                            except (ValueError, IndexError):
                                continue
                            if mode == "analog" and 26 <= pin <= 29:
                                self.pico.stop_scan()
                                self.scanning = False
                                self.root.after(0, lambda p=pin: _on_detected(p, "analog"))
                                return
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): _on_error(e))

            def _no_i2c_found():
                """Called on main thread when all auto-probe pairs failed."""
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(
                    text="⚠  Auto-detection failed. Checked all common I2C pin pairs.",
                    fg=ACCENT_ORANGE)
                gpio_lbl.config(text="")
                # Open the manual pin dialog
                pins = _show_manual_pin_dialog()
                if pins is None:
                    return  # user skipped
                sda, scl = pins
                # Retry with the user-specified pins
                status_lbl.config(text=f"Retrying with SDA=GP{sda}, SCL=GP{scl}…",
                                   fg=ACCENT_BLUE)
                gpio_lbl.config(text="")
                detect_btn.set_state("disabled")
                cancel_btn.set_state("normal")
                self.scanning = True

                def _manual_thread():
                    try:
                        self.pico.set_value("i2c_sda", str(sda))
                        self.pico.set_value("i2c_scl", str(scl))
                        pre_lines = self.pico.start_scan()
                        found_i2c = None
                        for pl in pre_lines:
                            if pl.startswith("I2C:"):
                                found_i2c = pl[4:]
                                break
                        if found_i2c is None:
                            import time as _time
                            deadline = _time.time() + 2.0
                            while self.scanning and _time.time() < deadline:
                                line = self.pico.read_scan_line(0.15)
                                if line and line.startswith("I2C:"):
                                    found_i2c = line[4:]
                                    break
                        self.pico.stop_scan()
                        self.scanning = False
                        if found_i2c:
                            self.detected["i2c_sda"] = sda
                            self.detected["i2c_scl"] = scl
                            self.root.after(0, lambda d=found_i2c: _on_i2c(d))
                        else:
                            self.root.after(0, lambda: [
                                detect_btn.set_state("normal"),
                                cancel_btn.set_state("disabled"),
                                status_lbl.config(
                                    text=f"⚠  Still not found on SDA=GP{sda}, SCL=GP{scl}. "
                                         "Check wiring and try again.",
                                    fg=ACCENT_RED),
                                gpio_lbl.config(text="")])
                    except Exception as exc:
                        self.root.after(0, lambda e=str(exc): _on_error(e))

                threading.Thread(target=_manual_thread, daemon=True).start()

            def _cancel():
                self.scanning = False
                try:
                    self.pico.stop_scan()
                except Exception:
                    pass
                _restore_idle()

            cancel_btn._command = _cancel
            cancel_btn._render(cancel_btn._bg)
            threading.Thread(target=_thread, daemon=True).start()

        detect_btn._command = start_detect
        detect_btn._render(detect_btn._bg)

        # Restore monitoring if previously detected (won't fire — detected cleared on show)
        tmode_now = self.detected.get("tilt_mode")
        if tmode_now == "i2c":
            _show_tilt_cal()
            self._start_monitor("i2c", None, bar, prefix="tilt", axis=axis_var.get())
        elif tmode_now == "analog" and "tilt_pin" in self.detected:
            _show_tilt_cal()
            self._start_monitor("analog", self.detected["tilt_pin"], bar, prefix="tilt")

    # ── Navigation ────────────────────────────────────────────────

    def _prev_page(self):
        self._clear_override_flow()
        if self._current_page > 0:
            self._show_page(self._current_page - 1)

    # Pages whose config key MUST be bound before the user can advance.
    # Index matches PAGE_DEFS order: 0=green … 7=start
    _REQUIRED_PAGES = {0, 1, 2, 3, 4, 5, 6, 7}

    def _next_page(self):
        idx = self._current_page
        ptype, key, name, accent, category = self.PAGE_DEFS[idx]
        self._stop_scan_and_monitor(reset_detection_ui=True)

        # Enforce required bindings for digital button pages 0-7
        if idx in self._REQUIRED_PAGES:
            if ptype == "digital" and key not in self.detected:
                # Show themed popup — cannot advance
                dlg = tk.Toplevel(self.root)
                dlg.title("Binding Required")
                dlg.configure(bg=BG_CARD)
                dlg.resizable(False, False)
                dlg.transient(self.root)
                tk.Label(dlg,
                         text=f"You must bind a button to\n\"{name}\" before continuing.",
                         bg=BG_CARD, fg=TEXT, font=(FONT_UI, 10),
                         justify="center", padx=28, pady=20).pack()
                btn_f = tk.Frame(dlg, bg=BG_CARD, pady=10)
                btn_f.pack()
                RoundedButton(btn_f, text="OK", bg_color=ACCENT_BLUE,
                              btn_width=90, btn_height=30,
                              command=dlg.destroy).pack()
                dlg.update_idletasks()
                pw, ph = self.root.winfo_width(), self.root.winfo_height()
                px, py = self.root.winfo_rootx(), self.root.winfo_rooty()
                dw, dh = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
                dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
                dlg.grab_set()
                self.root.wait_window(dlg)
                return   # do NOT advance

        if self._override_repair_page == idx and self._override_repair_key is not None:
            return_page = self._override_return_page
            self._clear_override_flow()
            if return_page is not None:
                self._show_page(return_page)
                return

        if idx < len(self.PAGE_DEFS) - 1:
            self._show_page(idx + 1)
        else:
            self._finish_and_save()

    def _finish_and_save(self):
        """Push all detected config to the firmware, save, reboot to play mode, return to menu."""
        self._stop_scan_and_monitor()

        if not self.pico.connected:
            # Not connected — just go back to menu
            self._go_back()
            return

        # Show a brief saving overlay on the body frame
        for w in self._body_frame.winfo_children():
            w.destroy()
        saving_lbl = tk.Label(self._body_frame,
                               text="Saving configuration and rebooting controller\u2026",
                               bg=BG_CARD, fg=ACCENT_BLUE, font=(FONT_UI, 12))
        saving_lbl.pack(anchor="nw", pady=30)
        self._body_frame.update_idletasks()

        def _worker():
            # The review page runs a live-preview scan thread (50 ms read loop).
            # Give it time to fully exit before we take the serial port.
            time.sleep(0.2)
            # Flush any PIN: lines that accumulated in the OS receive buffer
            # while the scan was running.  Without this, send() reads a stale
            # PIN: line instead of the expected SET/SAVE response.
            self.pico.flush_input()

            d = self.detected
            last_exc = None

            for attempt in range(3):
                if attempt > 0:
                    self.root.after(0, lambda a=attempt: saving_lbl.config(
                        text=f"Retrying\u2026  (attempt {a + 1} of 3)"
                    ))
                    time.sleep(0.3)
                try:
                    # ── Digital button pins ──────────────────────────────────
                    for key in ("green", "red", "yellow", "blue", "orange",
                                "strum_up", "strum_down", "start", "select",
                                "dpad_up", "dpad_down", "dpad_left", "dpad_right"):
                        pin = d.get(key, -1)
                        self.pico.set_value(key, str(pin if pin is not None else -1))

                    # ── Guide / joystick SW ───────────────────────────────────
                    guide_pin = d.get("joy_sw", -1)
                    self.pico.set_value("guide",       str(d.get("guide", -1)))
                    self.pico.set_value("joy_pin_sw",  str(guide_pin if guide_pin is not None else -1))

                    # ── Joystick X axis ───────────────────────────────────────
                    jx_pin  = d.get("joy_x", -1)
                    self.pico.set_value("joy_pin_x",        str(jx_pin if jx_pin is not None else -1))
                    self.pico.set_value("joy_dpad_x",       "1" if jx_pin not in (None, -1) else "0")
                    self.pico.set_value("joy_dpad_x_invert","1" if d.get("joy_dpad_x_invert") else "0")

                    # ── Joystick Y axis ───────────────────────────────────────
                    jy_pin  = d.get("joy_y", -1)
                    self.pico.set_value("joy_pin_y",        str(jy_pin if jy_pin is not None else -1))
                    self.pico.set_value("joy_dpad_y",       "1" if jy_pin not in (None, -1) else "0")
                    self.pico.set_value("joy_dpad_y_invert","1" if d.get("joy_dpad_y_invert") else "0")

                    # Joystick defaults not touched by Easy Config
                    self.pico.set_value("joy_whammy_axis", "0")
                    self.pico.set_value("joy_deadzone",    "410")   # 10% of 4095

                    # ── Whammy ────────────────────────────────────────────────
                    wh_pin  = d.get("whammy_pin", -1)
                    wh_mode = d.get("whammy_mode", "digital")
                    self.pico.set_value("whammy_mode",   wh_mode)
                    self.pico.set_value("whammy_pin",    str(wh_pin if wh_pin is not None else -1))
                    self.pico.set_value("whammy_min",    str(d.get("whammy_min", 0)))
                    self.pico.set_value("whammy_max",    str(d.get("whammy_max", 4095)))
                    self.pico.set_value("whammy_invert", "1" if d.get("whammy_invert") else "0")
                    # EMA smoothing (shared with tilt in firmware)
                    ema_alpha = d.get("whammy_ema_alpha", 140)   # default level 4
                    self.pico.set_value("ema_alpha", str(ema_alpha))

                    # ── Tilt ──────────────────────────────────────────────────
                    tilt_mode = d.get("tilt_mode", "digital")
                    self.pico.set_value("tilt_mode", tilt_mode)
                    if tilt_mode == "i2c":
                        self.pico.set_value("i2c_model",    str(d.get("i2c_model", 0)))
                        self.pico.set_value("adxl345_axis", str(d.get("tilt_axis", 0)))
                        self.pico.set_value("tilt_pin",     "-1")
                        self.pico.set_value("i2c_sda", str(d.get("i2c_sda", 4)))
                        self.pico.set_value("i2c_scl", str(d.get("i2c_scl", 5)))
                    else:
                        tilt_pin = d.get("tilt_pin", -1)
                        self.pico.set_value("tilt_pin", str(tilt_pin if tilt_pin is not None else -1))
                    self.pico.set_value("tilt_min",    str(d.get("tilt_min", 0)))
                    self.pico.set_value("tilt_max",    str(d.get("tilt_max", 4095)))
                    self.pico.set_value("tilt_invert", "1" if d.get("tilt_invert") else "0")
                    # EMA smoothing — tilt uses same ema_alpha as whammy in firmware.
                    # Prefer tilt's value if set, fall back to whammy's, then default level 4.
                    tilt_ema   = d.get("tilt_ema_alpha")
                    whammy_ema = d.get("whammy_ema_alpha")
                    ema_alpha  = tilt_ema if tilt_ema is not None else (whammy_ema if whammy_ema is not None else 140)
                    self.pico.set_value("ema_alpha", str(ema_alpha))

                    # ── LEDs ──────────────────────────────────────────────────
                    # led_reactive is UI-only — the firmware has no such key.
                    # led_color_N expects exactly 6 uppercase hex chars (RRGGBB).
                    # led_map_N expects a 4-digit uppercase hex mask.
                    try:
                        self.pico.set_value("led_enabled",    "1" if d.get("led_enabled") else "0")
                        self.pico.set_value("led_count",      str(d.get("led_count", 9)))
                        self.pico.set_value("led_brightness", str(d.get("led_brightness", 2)))
                        self.pico.set_value("led_loop_enabled", "1" if d.get("led_loop_enabled") else "0")
                        self.pico.set_value("led_loop_start", str(d.get("led_loop_start", 0)))
                        self.pico.set_value("led_loop_end",   str(d.get("led_loop_end", 0)))
                        self.pico.set_value("led_breathe_enabled", "1" if d.get("led_breathe_enabled") else "0")
                        self.pico.set_value("led_breathe_start", str(d.get("led_breathe_start", 0)))
                        self.pico.set_value("led_breathe_end",   str(d.get("led_breathe_end", 0)))
                        self.pico.set_value("led_breathe_min",   str(d.get("led_breathe_min", 0)))
                        self.pico.set_value("led_breathe_max",   str(d.get("led_breathe_max", 31)))
                        self.pico.set_value("led_wave_enabled", "1" if d.get("led_wave_enabled") else "0")
                        self.pico.set_value("led_wave_origin",  str(d.get("led_wave_origin", 0)))
                        colors = d.get("led_colors", ["FFFFFF"] * MAX_LEDS)
                        for i, c in enumerate(colors[:MAX_LEDS]):
                            hex_c = str(c).strip().upper().lstrip("#")
                            if len(hex_c) != 6:
                                hex_c = "FFFFFF"
                            self.pico.set_value(f"led_color_{i}", hex_c)
                        maps = d.get("led_maps", [0] * LED_INPUT_COUNT)
                        for i, m in enumerate(maps[:LED_INPUT_COUNT]):
                            self.pico.set_value(f"led_map_{i}", f"{int(m):04X}")
                        active_br = d.get("led_active_br", [8] * LED_INPUT_COUNT)
                        for i, b in enumerate(active_br[:LED_INPUT_COUNT]):
                            self.pico.set_value(f"led_active_{i}", str(b))
                    except ValueError as led_err:
                        if "unknown key" in str(led_err).lower():
                            raise ValueError(
                                "LED settings could not be saved — your firmware does not support "
                                "LED configuration. Please flash the latest firmware and try again."
                            )
                        raise

                    # ── Save to flash ─────────────────────────────────────────
                    self.pico.save()
                    last_exc = None
                    break   # success — exit retry loop

                except Exception as exc:
                    # Firmware version mismatch is permanent, not transient — don't retry
                    if "firmware does not support" in str(exc):
                        self.root.after(0, lambda e=str(exc): self._on_save_error(e))
                        return
                    last_exc = exc

            if last_exc is not None:
                self.root.after(0, lambda e=str(last_exc): self._on_save_error(e))
                return

            # ── Reboot to play/XInput mode ────────────────────────────────
            try:
                self.pico.reboot()
            except Exception:
                pass   # reboot disconnects — that's expected

            self.root.after(0, self._direct_go_back)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_save_error(self, msg):
        for w in self._body_frame.winfo_children():
            w.destroy()
        tk.Label(self._body_frame, text=f"\u26a0  Save failed: {msg}",
                  bg=BG_CARD, fg=ACCENT_RED, font=(FONT_UI, 11),
                  wraplength=800, justify="left").pack(anchor="nw", pady=20)
        RoundedButton(self._body_frame, text="Back to Menu",
                       command=self._go_back, bg_color=BG_INPUT,
                       btn_width=160, btn_height=36).pack(anchor="nw", pady=(10, 0))

    def _direct_go_back(self):
        """Go back to menu immediately without a confirmation dialog.
        Used after a successful save — no unsaved data to warn about."""
        self._stop_scan_and_monitor()
        if self.pico.connected:
            try:
                self.pico.reboot()   # return to play mode
            except Exception:
                pass
            try:
                self.pico.disconnect()
            except Exception:
                pass
        if self._on_back:
            self._on_back()

    def _go_back(self):
        # Show a themed confirmation — unsaved work will be lost
        dlg = tk.Toplevel(self.root)
        dlg.title("Exit Easy Configuration")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        tk.Label(dlg,
                 text="Exiting to the main menu will not save\nany configuration changes.\n\n"
                      "Are you sure you want to go back?",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 10),
                 justify="center", padx=28, pady=20).pack()
        _confirmed = [False]
        btn_frame = tk.Frame(dlg, bg=BG_CARD, pady=12)
        btn_frame.pack()
        def _ok():
            _confirmed[0] = True
            dlg.destroy()
        def _cancel():
            dlg.destroy()
        RoundedButton(btn_frame, text="Ok, go to Menu", command=_ok,
                      bg_color=ACCENT_BLUE, btn_width=140, btn_height=32).pack(
                          side="left", padx=(0, 10))
        RoundedButton(btn_frame, text="Nevermind", command=_cancel,
                      bg_color=BG_INPUT, btn_width=110, btn_height=32).pack(side="left")
        dlg.update_idletasks()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        px, py = self.root.winfo_rootx(), self.root.winfo_rooty()
        dw, dh = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
        dlg.grab_set()
        self.root.wait_window(dlg)
        if not _confirmed[0]:
            return
        self._finish_without_saving()

    # ── Show / Hide ───────────────────────────────────────────────

    def show(self):
        self.root.title("OCC - Easy Configuration")
        self._empty_menu = getattr(self, '_empty_menu', None) or tk.Menu(self.root)
        self.root.config(menu=self._empty_menu)
        self._reset_easy_config_state()   # always start fresh — no "Previously set" state
        self._show_page(0)
        self.frame.pack(fill="both", expand=True)

    def hide(self):
        self._clear_override_flow()
        self._stop_scan_and_monitor()
        if getattr(self, '_strum_anim', None):
            self._strum_anim.stop()
            self._strum_anim = None
        self.frame.pack_forget()
