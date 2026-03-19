"""
OCC - Open Controller Configurator

Dependencies:
pyserial>=3.5
pyinstaller>=6.0
Pillow>=9.0

Build EXE:    See build_exe.bat
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont
import json
import serial
import serial.tools.list_ports
import threading
import time
import datetime
import sys
import os
import string
import shutil
import ctypes

#  THEME COLORS

BG_MAIN     = "#1f1f23"
BG_CARD     = "#2a2a2e"
BG_INPUT    = "#38383c"
BG_HOVER    = "#44444a"
BORDER      = "#4a4a50"
TEXT         = "#d4d4d8"
TEXT_DIM     = "#8b8b92"
TEXT_HEADER  = "#e8e8ec"

ACCENT_BLUE = "#4a9eff"
ACCENT_GREEN = "#3dbf7d"
ACCENT_RED  = "#e54545"
ACCENT_ORANGE = "#d4944a"

FRET_COLORS = {
    "green": "#2ecc71", "red": "#e74c3c", "yellow": "#f1c40f",
    "blue": "#3498db", "orange": "#e67e22",
}

#  FONT LOADING
#  Helvetica TTFs are bundled inside the EXE (PyInstaller _MEIPASS)
#  or live in a "font/" subfolder next to the script/exe.

# Will be populated by _load_fonts() after Tk root is created.
FONT_UI      = "Helvetica" 
FONT_UI_BOLD = "Helvetica"   #weight="bold" is applied per-widget

# Map: variant tag → filename inside the font/ folder
_FONT_FILES = {
    "regular":      "Helvetica.ttf",
    "bold":         "Helvetica-Bold.ttf",
    "italic":       "Helvetica-Oblique.ttf",
    "bold-italic":  "Helvetica-BoldOblique.ttf",
    "light":        "helvetica-light.ttf",
}

def _resource_path(*parts):
    """Resolve path relative to the bundle root (PyInstaller) or script dir."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def _load_fonts():
    """Register bundled Helvetica font files with the OS and Tkinter.

    Windows (GDI AddFontResourceEx), macOS (CoreText via ctypes),
    Linux (fontconfig via fc-cache / Xft).  Tkinter is told to use
    the family via tkfont
    """
    global FONT_UI, FONT_UI_BOLD

    # Collect candidate directories
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(os.path.join(sys._MEIPASS, "font"))
        search_dirs.append(sys._MEIPASS)          # flat bundle layout fallback
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    search_dirs.append(os.path.join(exe_dir, "font"))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    if src_dir != exe_dir:
        search_dirs.append(os.path.join(src_dir, "font"))

    def _find_font_file(filename):
        for d in search_dirs:
            p = os.path.join(d, filename)
            if os.path.isfile(p):
                return p
        return None

    loaded_paths = []
    for _variant, fname in _FONT_FILES.items():
        path = _find_font_file(fname)
        if path:
            loaded_paths.append(path)

    if not loaded_paths:
        # if no font files found — keep system fallback
        _set_fallback_fonts()
        return

    platform = sys.platform

    if platform == "win32":
        # AddFontResourceExW loads fonts into the current process session.
        gdi = ctypes.windll.gdi32
        FR_PRIVATE = 0x10
        for p in loaded_paths:
            try:
                gdi.AddFontResourceExW(p, FR_PRIVATE, 0)
            except Exception:
                pass

    elif platform == "darwin":
        # CoreText: CTFontManagerRegisterFontsForURL (macOS 10.6+)
        try:
            ct = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreText.framework/CoreText")
            cf = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
            cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            ct.CTFontManagerRegisterFontsForURL.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            kCTFontManagerScopeProcess = 1
            for p in loaded_paths:
                url = cf.CFURLCreateFromFileSystemRepresentation(
                    None, p.encode("utf-8"), len(p), False)
                if url:
                    ct.CTFontManagerRegisterFontsForURL(
                        url, kCTFontManagerScopeProcess, None)
        except Exception:
            pass

    else:
        # Linux / other X11: copy fonts to a temp dir and point fontconfig at it.
        try:
            import tempfile
            font_tmp = os.path.join(tempfile.gettempdir(), "occ_fonts")
            os.makedirs(font_tmp, exist_ok=True)
            for p in loaded_paths:
                dest = os.path.join(font_tmp, os.path.basename(p))
                if not os.path.exists(dest):
                    shutil.copy2(p, dest)
            # Write a minimal fonts.conf so Xft/fontconfig picks up the folder
            conf_path = os.path.join(font_tmp, "fonts.conf")
            if not os.path.exists(conf_path):
                with open(conf_path, "w") as fh:
                    fh.write(f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{font_tmp}</dir>
</fontconfig>
""")
            # Tell fontconfig about the new directory
            os.environ.setdefault("FONTCONFIG_FILE", conf_path)
            try:
                import subprocess
                subprocess.run(["fc-cache", font_tmp],
                               capture_output=True, timeout=5)
            except Exception:
                pass
        except Exception:
            pass

    # Confirm Tkinter can see the font fam
    try:
        families = [f.lower() for f in tkfont.families()]
        target = "helvetica"
        if target in families:
            FONT_UI = FONT_UI_BOLD = "Helvetica"
            return
        # Look for a close match (e.g. "Helvetica Neue", "HelveticaNeue")
        for f in tkfont.families():
            if "helvetica" in f.lower():
                FONT_UI = FONT_UI_BOLD = f
                return
    except Exception:
        pass

    if loaded_paths:
        FONT_UI = FONT_UI_BOLD = "Helvetica"
        return

    _set_fallback_fonts()


def _set_fallback_fonts():
    """Set FONT_UI / FONT_UI_BOLD to the best available system sans-serif."""
    global FONT_UI, FONT_UI_BOLD
    platform = sys.platform
    if platform == "win32":
        FONT_UI = FONT_UI_BOLD = FONT_UI
    elif platform == "darwin":
        FONT_UI = FONT_UI_BOLD = "SF Pro Text"
    else:
        FONT_UI = FONT_UI_BOLD = "DejaVu Sans"

#  CENTERED DIALOG HELPER

def _centered_dialog(parent, title, message, kind="info"):
    """Show a modal dialog centered over *parent*.

    kind can be "info", "yesno", or "error".
    Returns True/False for "yesno", None otherwise.
    """
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=BG_CARD)
    dlg.resizable(False, False)
    dlg.transient(parent)

    # Build content
    tk.Label(dlg, text=message, bg=BG_CARD, fg=TEXT,
             font=(FONT_UI, 10), justify="left",
             wraplength=360, padx=24, pady=20).pack()

    result = [None]

    btn_frame = tk.Frame(dlg, bg=BG_CARD, pady=12)
    btn_frame.pack()

    def _yes():
        result[0] = True
        dlg.destroy()

    def _no():
        result[0] = False
        dlg.destroy()

    def _ok():
        result[0] = None
        dlg.destroy()

    if kind == "yesno":
        RoundedButton(btn_frame, text="Yes", command=_yes,
                      bg_color=ACCENT_BLUE, btn_width=90, btn_height=30).pack(
                          side="left", padx=(0, 8))
        RoundedButton(btn_frame, text="No", command=_no,
                      bg_color=BG_INPUT, btn_width=90, btn_height=30).pack(
                          side="left")
    elif kind == "error":
        RoundedButton(btn_frame, text="OK", command=_ok,
                      bg_color=ACCENT_RED, btn_width=90, btn_height=30).pack()
    else:  
        RoundedButton(btn_frame, text="OK", command=_ok,
                      bg_color=ACCENT_BLUE, btn_width=90, btn_height=30).pack()

    # Center over parent window once the dialog has been laid out
    dlg.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    dw = dlg.winfo_width()
    dh = dlg.winfo_height()
    x = px + (pw - dw) // 2
    y = py + (ph - dh) // 2
    dlg.geometry(f"+{x}+{y}")

    dlg.grab_set()
    parent.wait_window(dlg)
    return result[0]



#  ROUNDED BUTTON  (plain tk.Canvas — no Frame wrapper)

class RoundedButton(tk.Canvas):
    """A clickable rounded-rectangle button drawn on a Canvas."""

    def __init__(self, parent, text="", command=None, bg_color=ACCENT_BLUE,
                 text_color="#ffffff", btn_width=140, btn_height=34,
                 radius=10, btn_font=(FONT_UI, 9, "bold")):
        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG_CARD

        super().__init__(parent, width=btn_width, height=btn_height,
                         bg=parent_bg, highlightthickness=0, bd=0)

        self._command = command
        self._bg = bg_color
        self._hover_bg = self._adjust(bg_color, 25)
        self._press_bg = self._adjust(bg_color, -25)
        self._disabled_bg = "#505055"
        self._text_color = text_color
        self._btn_w = btn_width
        self._btn_h = btn_height
        self._radius = radius
        self._btn_font = btn_font
        self._label = text
        self._enabled = True

        self._render(self._bg)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    @staticmethod
    def _adjust(hex_color, amount):
        try:
            r = max(0, min(255, int(hex_color[1:3], 16) + amount))
            g = max(0, min(255, int(hex_color[3:5], 16) + amount))
            b = max(0, min(255, int(hex_color[5:7], 16) + amount))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _render(self, fill_color):
        self.delete("all")
        w, h, r = self._btn_w, self._btn_h, self._radius
        self.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=fill_color, outline=fill_color)
        self.create_arc(w-2*r, 0, w, 2*r, start=0, extent=90, fill=fill_color, outline=fill_color)
        self.create_arc(0, h-2*r, 2*r, h, start=180, extent=90, fill=fill_color, outline=fill_color)
        self.create_arc(w-2*r, h-2*r, w, h, start=270, extent=90, fill=fill_color, outline=fill_color)
        self.create_rectangle(r, 0, w-r, h, fill=fill_color, outline=fill_color)
        self.create_rectangle(0, r, w, h-r, fill=fill_color, outline=fill_color)
        tc = self._text_color if self._enabled else "#888888"
        self.create_text(w // 2, h // 2, text=self._label, fill=tc, font=self._btn_font)

    def _on_enter(self, _event):
        if self._enabled:
            self._render(self._hover_bg)

    def _on_leave(self, _event):
        self._render(self._bg if self._enabled else self._disabled_bg)

    def _on_press(self, _event):
        if self._enabled:
            self._render(self._press_bg)

    def _on_release(self, _event):
        if self._enabled:
            self._render(self._hover_bg)
            if self._command:
                self._command()

    def set_state(self, state):
        self._enabled = (state != "disabled")
        self._render(self._bg if self._enabled else self._disabled_bg)

    def update_color(self, new_bg):
        """Change the button's base colour and re-render."""
        self._bg = new_bg
        self._hover_bg = self._adjust(new_bg, 25)
        self._press_bg = self._adjust(new_bg, -25)
        self._render(self._bg if self._enabled else self._disabled_bg)



#  CUSTOM DROPDOWN  (replaces ttk.Combobox throughout the UI)


# Design constants for the custom dropdown
_DD_BG          = "#3a3a3e"   # main bar background
_DD_ARROW_BG    = "#2e2e32"   # darker arrow box on the right
_DD_DISABLED_BG = "#2a2a2d"   # greyed-out bar
_DD_TEXT        = "#e8e8ec"   # text colour
_DD_TEXT_DIM    = "#777780"   # disabled text colour
_DD_POPUP_BG    = "#303035"   # popup list background
_DD_SELECTED_BG = "#2e6e68"   # muted teal-green for active selection
_DD_HOVER_BG    = "#46464d"   # hover highlight in popup
_DD_BORDER      = "#55555c"   # thin border colour
_DD_HEIGHT      = 30          # widget height in pixels
_DD_CHAR_PX     = 7           # pixels per character (for width= kwarg)
_DD_PAD         = 10          # horizontal text padding inside bar


class CustomDropdown(tk.Frame):
    """
    Drop-in replacement for ttk.Combobox with custom dark muted-gray style.

    API parity with ttk.Combobox:
      • values=, width= at construction
      • .current(idx)  / .current() → int
      • .get()         → str
      • .set(text)
      • .config(values=..., state="readonly"|"disabled"|"normal")
      • .configure(...)  (alias for config)
      • .bind("<<ComboboxSelected>>", callback)
      • textvariable=  (tk.StringVar linked to displayed value)
    """

    def __init__(self, parent, values=None, width=18, state="readonly",
                 textvariable=None, **kw):
        # Ignore unsupported ttk kwargs
        for _k in ("font", "style", "exportselection", "postcommand"):
            kw.pop(_k, None)

        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG_CARD

        super().__init__(parent, bg=parent_bg, highlightthickness=0, bd=0, **kw)

        self._values      = list(values) if values else []
        self._state       = state          
        self._current_idx = 0
        self._textvar     = textvariable
        self._callbacks   = []             # <<ComboboxSelected>> listeners
        self._popup       = None           # active Toplevel, or None

        # Pixel width of the main bar area
        self._bar_w = width * _DD_CHAR_PX + _DD_PAD * 2
        self._arrow_w = _DD_HEIGHT          # square arrow box
        self._total_w = self._bar_w + self._arrow_w

        # Canvas that draws the whole widget
        self._canvas = tk.Canvas(self, width=self._total_w, height=_DD_HEIGHT,
                                 bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.pack()

        self._render()

        # If textvariable already has a value, honor it
        if self._textvar:
            v = self._textvar.get()
            if v and self._values and v in self._values:
                self._current_idx = self._values.index(v)
            self._textvar.trace_add("write", self._on_textvar_write)

        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Enter>",    self._on_enter)
        self._canvas.bind("<Leave>",    self._on_leave)

    # Internal helpers

    def _display_text(self):
        if self._values and 0 <= self._current_idx < len(self._values):
            return self._values[self._current_idx]
        if self._textvar:
            return self._textvar.get()
        return ""

    def _render(self, hover=False):
        c = self._canvas
        c.delete("all")
        w, h = self._total_w, _DD_HEIGHT
        aw  = self._arrow_w
        bw  = self._bar_w
        r   = 4   # corner radius

        val_disabled = (self._display_text() == "Disabled")
        bar_fill  = _DD_DISABLED_BG if val_disabled else (_DD_HOVER_BG if hover else _DD_BG)
        arr_fill  = _DD_DISABLED_BG if val_disabled else _DD_ARROW_BG
        text_col  = _DD_TEXT_DIM if val_disabled else _DD_TEXT

        # Main bar (left side, rounded left corners only)
        # Full rounded rect for bar+arrow together first
        c.create_arc(0,   0,   2*r, 2*r, start=90,  extent=90,  fill=bar_fill, outline=bar_fill)
        c.create_arc(0,   h-2*r, 2*r, h, start=180, extent=90,  fill=bar_fill, outline=bar_fill)
        c.create_rectangle(r, 0, w-aw, h,            fill=bar_fill, outline=bar_fill)
        c.create_rectangle(0, r, bw,   h-r,          fill=bar_fill, outline=bar_fill)

        # Arrow box (right side, rounded right corners)
        c.create_arc(w-2*r, 0,   w, 2*r,   start=0,   extent=90,  fill=arr_fill, outline=arr_fill)
        c.create_arc(w-2*r, h-2*r, w, h,   start=270, extent=90,  fill=arr_fill, outline=arr_fill)
        c.create_rectangle(w-aw, 0,    w-r, h,         fill=arr_fill, outline=arr_fill)
        c.create_rectangle(w-aw, r,    w,   h-r,       fill=arr_fill, outline=arr_fill)

        # Thin divider line between bar and arrow box
        c.create_line(bw, 3, bw, h-3, fill=_DD_BORDER, width=1)

        # Outer border
        c.create_arc(0,   0,   2*r, 2*r, start=90,  extent=90, outline=_DD_BORDER, style="arc")
        c.create_arc(w-2*r, 0, w,   2*r, start=0,   extent=90, outline=_DD_BORDER, style="arc")
        c.create_arc(0,   h-2*r, 2*r, h, start=180, extent=90, outline=_DD_BORDER, style="arc")
        c.create_arc(w-2*r, h-2*r, w, h, start=270, extent=90, outline=_DD_BORDER, style="arc")
        c.create_line(r, 0,   w-r, 0,   fill=_DD_BORDER)
        c.create_line(r, h-1, w-r, h-1, fill=_DD_BORDER)
        c.create_line(0, r,   0,   h-r, fill=_DD_BORDER)
        c.create_line(w-1, r, w-1, h-r, fill=_DD_BORDER)

        # Label text (truncated to fit)
        txt = self._display_text()
        # Truncate if too long
        max_chars = (bw - _DD_PAD * 2) // _DD_CHAR_PX
        if len(txt) > max_chars:
            txt = txt[:max_chars - 1] + "…"
        c.create_text(_DD_PAD, h // 2, text=txt, anchor="w",
                      fill=text_col, font=(FONT_UI, 9, "bold"))

        # Down-arrow (▼) centred in arrow box
        ax = bw + aw // 2
        ay = h // 2
        arr_col = _DD_TEXT_DIM if val_disabled else "#ffffff"
        # Draw a filled triangle
        s = 5   # half-base size
        c.create_polygon(ax-s, ay-3, ax+s, ay-3, ax, ay+4,
                         fill=arr_col, outline=arr_col)

    def _on_enter(self, _e):
        self._render(hover=True)

    def _on_leave(self, _e):
        self._render(hover=False)

    def _on_click(self, _e):
        if self._popup and self._popup.winfo_exists():
            self._close_popup()
            return
        self._open_popup()

    def _open_popup(self):
        if not self._values:
            return

        # Position popup directly below the widget
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + _DD_HEIGHT

        item_h   = 26
        max_vis  = 12                          # max visible rows before scrolling
        n        = len(self._values)
        visible  = min(n, max_vis)
        sb_w     = 6                           # thin scrollbar width in pixels
        pw       = self._total_w
        inner_w  = pw - 2                      # inside the 1px border
        canvas_w = inner_w - sb_w - 1          # canvas content width (leave room for scrollbar)
        total_h  = n * item_h                  # full scrollable height
        ph       = visible * item_h + 2        # popup window height

        pop = tk.Toplevel(self)
        pop.wm_overrideredirect(True)
        pop.geometry(f"{pw}x{ph}+{x}+{y}")
        pop.configure(bg=_DD_BORDER)           # border colour as window bg
        # No transparency — plain opaque popup

        # 1px border provided by the window bg showing through
        inner = tk.Frame(pop, bg=_DD_POPUP_BG, bd=0)
        inner.place(x=1, y=1, width=pw-2, height=ph-2)

        # Scrollable canvas for items
        canvas = tk.Canvas(inner, bg=_DD_POPUP_BG, highlightthickness=0,
                           bd=0, width=canvas_w, height=ph-2)
        canvas.place(x=0, y=0, width=canvas_w, height=ph-2)

        # Thin custom scrollbar (canvas-drawn)
        sb_canvas = tk.Canvas(inner, bg=_DD_ARROW_BG, highlightthickness=0,
                              bd=0, width=sb_w, height=ph-2)
        sb_canvas.place(x=canvas_w+1, y=0, width=sb_w, height=ph-2)

        # Scroll state
        scroll_offset = [0]   # top pixel offset into the full item list

        def _max_offset():
            return max(0, total_h - (ph - 2))

        def _draw_scrollbar():
            sb_canvas.delete("all")
            if total_h <= ph - 2:
                return   # no scrollbar needed
            track_h = ph - 2
            thumb_h = max(16, int(track_h * (ph - 2) / total_h))
            thumb_y = int(scroll_offset[0] / total_h * track_h)
            sb_canvas.create_rectangle(
                0, thumb_y, sb_w, thumb_y + thumb_h,
                fill="#666672", outline="#666672"
            )

        def _clamp_offset(v):
            return max(0, min(_max_offset(), v))

        # Draw all items onto the canvas at full height
        item_rects = []
        item_texts = []

        def _item_y(i):
            return i * item_h - scroll_offset[0]

        def _draw_all_items():
            canvas.delete("all")
            for i, val in enumerate(self._values):
                iy = _item_y(i)
                is_sel = (i == self._current_idx)
                is_hov = (i == hover_idx[0])
                if is_sel:
                    bg = _DD_SELECTED_BG
                elif is_hov:
                    bg = _DD_HOVER_BG
                else:
                    bg = _DD_POPUP_BG
                tc = "#ffffff" if (is_sel or is_hov) else _DD_TEXT
                canvas.create_rectangle(0, iy, canvas_w, iy + item_h,
                                        fill=bg, outline=bg, tags=f"item{i}")
                canvas.create_text(_DD_PAD, iy + item_h // 2, text=val,
                                   anchor="w", fill=tc, font=(FONT_UI, 9),
                                   tags=f"item{i}")

        hover_idx = [None]

        def _idx_at(y_canvas):
            return (y_canvas + scroll_offset[0]) // item_h

        def _on_motion(event):
            i = _idx_at(event.y)
            if 0 <= i < n:
                if hover_idx[0] != i:
                    hover_idx[0] = i
                    _draw_all_items()
            else:
                if hover_idx[0] is not None:
                    hover_idx[0] = None
                    _draw_all_items()

        def _on_select(event):
            i = _idx_at(event.y)
            if 0 <= i < n:
                self._current_idx = i
                if self._textvar:
                    self._textvar.set(self._values[i])
                self._render()
                self._close_popup()
                self.event_generate("<<ComboboxSelected>>")
                for cb in self._callbacks:
                    try:
                        cb(None)
                    except Exception:
                        pass

        def _scroll_by(delta):
            scroll_offset[0] = _clamp_offset(scroll_offset[0] + delta)
            _draw_all_items()
            _draw_scrollbar()

        def _on_mousewheel(event):
            # Windows sends delta in multiples of 120; Linux sends Button-4/5
            if hasattr(event, "delta") and event.delta:
                _scroll_by(-int(event.delta / 120) * item_h)
            elif event.num == 4:
                _scroll_by(-item_h)
            elif event.num == 5:
                _scroll_by(item_h)

        canvas.bind("<Motion>",     _on_motion)
        canvas.bind("<Button-1>",   _on_select)
        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Button-4>",   _on_mousewheel)
        canvas.bind("<Button-5>",   _on_mousewheel)

        # Scrollbar drag
        sb_drag = [False, 0]
        def _sb_press(event):
            sb_drag[0] = True
            sb_drag[1] = event.y
        def _sb_release(_event):
            sb_drag[0] = False
        def _sb_drag_move(event):
            if sb_drag[0]:
                dy = event.y - sb_drag[1]
                sb_drag[1] = event.y
                ratio = dy / max(1, ph - 2)
                _scroll_by(int(ratio * total_h))
        sb_canvas.bind("<ButtonPress-1>",   _sb_press)
        sb_canvas.bind("<ButtonRelease-1>", _sb_release)
        sb_canvas.bind("<B1-Motion>",       _sb_drag_move)
        sb_canvas.bind("<MouseWheel>",      _on_mousewheel)
        sb_canvas.bind("<Button-4>",        _on_mousewheel)
        sb_canvas.bind("<Button-5>",        _on_mousewheel)

        # Scroll to show selected item initially
        sel_y = self._current_idx * item_h
        vis_h = ph - 2
        if sel_y < 0:
            scroll_offset[0] = sel_y
        elif sel_y + item_h > vis_h:
            scroll_offset[0] = _clamp_offset(sel_y + item_h - vis_h)

        _draw_all_items()
        _draw_scrollbar()

        pop.bind("<FocusOut>", lambda _e: self._close_popup())
        pop.bind("<Escape>",   lambda _e: self._close_popup())
        pop.bind("<MouseWheel>", _on_mousewheel)

        self._popup = pop
        pop.focus_set()

        # Close if root moves/resizes
        def _on_root_event(_e):
            if self._popup and self._popup.winfo_exists():
                self._close_popup()
        try:
            self.winfo_toplevel().bind("<Configure>", _on_root_event, add="+")
        except Exception:
            pass

    def _close_popup(self):
        if self._popup:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None
        self._render()

    def _on_textvar_write(self, *_args):
        if self._textvar:
            v = self._textvar.get()
            if v in self._values:
                self._current_idx = self._values.index(v)
            self._render()

    # Public API

    def current(self, idx=None):
        """Set or get the current index (like ttk.Combobox.current)."""
        if idx is None:
            return self._current_idx
        if 0 <= idx < len(self._values):
            self._current_idx = idx
            if self._textvar:
                self._textvar.set(self._values[idx])
            self._render()
        return self._current_idx

    def get(self):
        return self._display_text()

    def set(self, value):
        if value in self._values:
            self._current_idx = self._values.index(value)
        if self._textvar:
            self._textvar.set(value)
        self._render()

    def config(self, **kw):
        if "values" in kw:
            self._values = list(kw.pop("values"))
            # Keep index in bounds
            if self._current_idx >= len(self._values):
                self._current_idx = 0
        if "state" in kw:
            s = kw.pop("state")
            # Map "normal" and "readonly" both to enabled
            self._state = "disabled" if s == "disabled" else "readonly"
        if "textvariable" in kw:
            self._textvar = kw.pop("textvariable")
        # Ignore unrecognised options silently
        kw.pop("width", None)
        kw.pop("font", None)
        self._render()

    def configure(self, **kw):
        self.config(**kw)

    def __setitem__(self, key, value):
        """Support combo['values'] = [...] and combo['state'] = '...' syntax."""
        self.config(**{key: value})

    def __getitem__(self, key):
        """Support combo['values'] and combo['state'] read access."""
        if key == "values":
            return list(self._values)
        if key == "state":
            return self._state
        raise KeyError(key)

    def bind(self, sequence, callback, add=None):
        if sequence == "<<ComboboxSelected>>":
            self._callbacks.append(callback)
        else:
            super().bind(sequence, callback, add)



#  XINPUT API (WINDOWS)


XINPUT_AVAILABLE = False
xinput_dll = None

if sys.platform == "win32":
    for dll_name in ["xinput1_4", "xinput9_1_0", "xinput1_3"]:
        try:
            xinput_dll = ctypes.WinDLL(dll_name)
            XINPUT_AVAILABLE = True
            break
        except OSError:
            continue

if XINPUT_AVAILABLE:
    class XINPUT_GAMEPAD(ctypes.Structure):
        _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte),
                     ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                     ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                     ("sThumbRY", ctypes.c_short)]

    class XINPUT_STATE(ctypes.Structure):
        _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", XINPUT_GAMEPAD)]

    class XINPUT_VIBRATION(ctypes.Structure):
        _fields_ = [("wLeftMotorSpeed", ctypes.c_ushort), ("wRightMotorSpeed", ctypes.c_ushort)]

    class XINPUT_CAPABILITIES(ctypes.Structure):
        _fields_ = [("Type", ctypes.c_ubyte), ("SubType", ctypes.c_ubyte),
                     ("Flags", ctypes.c_ushort), ("Gamepad", XINPUT_GAMEPAD),
                     ("Vibration", XINPUT_VIBRATION)]

    ERROR_SUCCESS = 0

    def xinput_get_connected():
        slots = []
        state = XINPUT_STATE()
        for i in range(4):
            if xinput_dll.XInputGetState(i, ctypes.byref(state)) == ERROR_SUCCESS:
                caps = XINPUT_CAPABILITIES()
                cr = xinput_dll.XInputGetCapabilities(i, 1, ctypes.byref(caps))
                slots.append((i, caps.SubType if cr == ERROR_SUCCESS else 0))
        return slots

    def xinput_send_vibration(slot, left, right):
        return xinput_dll.XInputSetState(int(slot),
            ctypes.byref(XINPUT_VIBRATION(int(left), int(right))))

    MAGIC_STEPS = [(0x4700, 0x4300), (0x4300, 0x4700), (0x4F00, 0x4B00)]



#  CONSTANTS


CONFIG_MODE_VID = 0x2E8A

# All config-mode PIDs recognised by this configurator.
# Add a new entry here whenever a new firmware variant is created.
# Key = PID (int), Value = human-readable device label shown in port list.
CONFIG_MODE_PIDS = {
    0xF00D: "Guitar Config",
    0xF00E: "Drum Kit Config",
    0xF010: "Pedal Config",
}
BAUD_RATE = 115200
TIMEOUT = 2.0

# Alternatefw firmware USB identifiers (from Alternatefw/include/endpoints.h)
ALTERNATEFW_VID = 0x1209
ALTERNATEFW_PID = 0x2882
# USB control transfer command to jump to BOOTSEL (from Alternatefw/include/commands.h)
# COMMAND_REBOOT=0x30, COMMAND_JUMP_BOOTLOADER=0x31
_ALTERNATEFW_CMD_JUMP_BOOTLOADER = 0x31
# bmRequestType = Host->Device | Class | Interface = 0x00 | 0x20 | 0x01 = 0x21
_ALTERNATEFW_BM_REQUEST_TYPE = 0x21

# GP2040-CE web configurator USB identifiers (RNDIS virtual Ethernet, web config mode)
GP2040CE_VID = 0xCAFE
GP2040CE_PID = 0x4028
# HTTP API: POST http://<IP>/api/reboot  body: {"bootMode": <n>}
# bootMode integers sourced from GP2040-CE www frontend (Navigation.jsx):
#   GAMEPAD=0, WEBCONFIG=1, BOOTSEL=2
# The webconfig handler maps these small integers to the BootMode enum values
# internally before writing to watchdog scratch[5].  Sending the raw enum
# value (0xf737e4e1) overflows ArduinoJson's signed int read and arrives as 0,
# which maps to DEFAULT/GAMEPAD — hence the device rebooting as a controller.
GP2040CE_WEBCONFIG_IP     = "192.168.7.1"
GP2040CE_BOOTMODE_BOOTSEL = 2
NUKE_UF2_FILENAME = "nuke.uf2"

# Maps DEVTYPE strings → substrings expected in the UF2 filename.
# The first UF2 whose lowercase filename contains the substring wins.
# Add a new entry here whenever a new firmware variant is created.
DEVICE_TYPE_UF2_HINTS = {
    "guitar_alternate":        "guitar",
    "guitar_alternate_dongle": "guitar",
    "guitar_combined":         "guitar",
    "drum_kit":                "drum",
    "dongle":                  "dongle",
    "pedal":                   "pedal",
}

# Maps XInput subtype → DEVTYPE string (used before serial connection is open)
XINPUT_SUBTYPE_TO_DEVTYPE = {
    8: "drum_kit",
    6: "guitar_alternate",
    7: "guitar_alternate",
    11: "dongle",           # Dongle uses subtype 0x0B=11 (XINPUT_DEVSUBTYPE_GUITAR_BASS)
}

# All XInput subtypes recognised as OCC devices.
# Used when scanning for controllers without a serial connection.
OCC_SUBTYPES = {8, 6, 7, 11}   # Drum Kit (8), Guitar (6/7), Dongle (11=0x0B)

# Subtype(s) that identify a dongle — configurable separately, no serial config mode.
DONGLE_XINPUT_SUBTYPES = {11}

DIGITAL_PINS = [-1] + list(range(0, 23)) + [26, 27, 28]
ANALOG_PINS = [26, 27, 28]

DIGITAL_PIN_LABELS = {-1: "Disabled"}
for _p in range(0, 23):
    DIGITAL_PIN_LABELS[_p] = f"GPIO {_p}"
for _p in (26, 27, 28):
    DIGITAL_PIN_LABELS[_p] = f"GPIO {_p}  (ADC{_p - 26})"

ANALOG_PIN_LABELS = {
    26: "GPIO 26  (ADC0)", 27: "GPIO 27  (ADC1)", 28: "GPIO 28  (ADC2)"
}

# Valid I2C0 SDA pins on RP2040
I2C0_SDA_PINS = [0, 4, 8, 12, 16, 20]
I2C0_SCL_PINS = [1, 5, 9, 13, 17, 21]

I2C_SDA_LABELS = {p: f"GPIO {p}  (I2C0 SDA)" for p in I2C0_SDA_PINS}
I2C_SCL_LABELS = {p: f"GPIO {p}  (I2C0 SCL)" for p in I2C0_SCL_PINS}

ADXL345_AXIS_LABELS = {0: "X axis", 1: "Y axis", 2: "Z axis"}

# I2C accelerometer model options — add new chips here in future
I2C_MODEL_OPTIONS = [
    (0, "ADXL345 / GY-291"),
    (1, "LIS3DH"),
]
I2C_MODEL_LABELS  = [label for _, label in I2C_MODEL_OPTIONS]
I2C_MODEL_VALUES  = [val   for val, _   in I2C_MODEL_OPTIONS]

MAX_LEDS = 16
LED_INPUT_COUNT = 16   # 14 buttons + tilt + whammy

VALID_NAME_CHARS = set(string.ascii_letters + string.digits + ' ')

LED_INPUT_NAMES = [
    "green", "red", "yellow", "blue", "orange",
    "strum_up", "strum_down", "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "guide", "tilt", "whammy",
]

LED_INPUT_LABELS = [
    "Green Fret", "Red Fret", "Yellow Fret", "Blue Fret", "Orange Fret",
    "Strum Up", "Strum Down", "Start", "Select",
    "D-Pad Up", "D-Pad Down", "D-Pad Left", "D-Pad Right",
    "Guide", "Tilt", "Whammy",
]

BUTTON_DEFS = [
    ("green",      "Green Fret",    "frets"),
    ("red",        "Red Fret",      "frets"),
    ("yellow",     "Yellow Fret",   "frets"),
    ("blue",       "Blue Fret",     "frets"),
    ("orange",     "Orange Fret",   "frets"),
    ("strum_up",   "Strum Up",      "strum"),
    ("strum_down", "Strum Down",    "strum"),
    ("start",      "Start",         "nav"),
    ("select",     "Select / Back", "nav"),
    ("dpad_up",    "D-Pad Up",      "dpad"),
    ("dpad_down",  "D-Pad Down",    "dpad"),
    ("dpad_left",  "D-Pad Left",    "dpad"),
    ("dpad_right", "D-Pad Right",   "dpad"),
    ("guide",      "Guide",         "nav2"),
]



#  UF2 FLASHING


def find_uf2_files():
    found = {}
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir:
        for f in os.listdir(bundle_dir):
            if f.lower().endswith('.uf2') and f.lower() != NUKE_UF2_FILENAME.lower():
                found[f] = os.path.join(bundle_dir, f)
    return sorted(found.items())


def find_uf2_for_device_type(device_type):
    """Return the path of the UF2 that best matches device_type, or None.

    Matches by looking for the hint substring from DEVICE_TYPE_UF2_HINTS
    inside each available UF2 filename (case-insensitive).  Falls back to
    the first available UF2 if no hint matches.
    """
    files = find_uf2_files()   # list of (display_name, path) sorted by name
    if not files:
        return None
    hint = DEVICE_TYPE_UF2_HINTS.get(device_type, "")
    if hint:
        for name, path in files:
            if hint in name.lower():
                return path
    # Fallback — return first UF2 (better than nothing)
    return files[0][1]


def find_nuke_uf2():
    """Search for nuke.uf2 (case-insensitive) alongside the exe/script."""
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    if src_dir not in search_dirs:
        search_dirs.append(src_dir)
    for d in search_dirs:
        try:
            for f in os.listdir(d):
                if f.lower() == NUKE_UF2_FILENAME.lower():
                    return os.path.join(d, f)
        except Exception:
            pass
    return None


# ── Firmware build-date helpers ──────────────────────────────────

# Month abbreviations used by C's __DATE__ and our CMake sidecar files
_MONTH_ABBR = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def parse_fw_date(date_str):
    """Parse a firmware date string like 'Jun 15 2025' → datetime.date.

    Returns None if the string can't be parsed.
    """
    if not date_str:
        return None
    try:
        parts = date_str.strip().split()
        if len(parts) == 3:
            month = _MONTH_ABBR.get(parts[0])
            day = int(parts[1])
            year = int(parts[2])
            if month:
                return datetime.date(year, month, day)
    except (ValueError, KeyError):
        pass
    return None


def load_bundled_fw_dates():
    """Load fw_dates.json from the PyInstaller bundle (or script dir).

    Returns a dict mapping UF2 filename → date string, e.g.
        {"pico_guitar_controller.uf2": "Jun 15 2025"}
    Returns empty dict if the file isn't found.
    """
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    if src_dir not in search_dirs:
        search_dirs.append(src_dir)
    for d in search_dirs:
        path = os.path.join(d, "fw_dates.json")
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def get_bundled_fw_date(uf2_path):
    """Return the build date (datetime.date) for a bundled UF2, or None.

    Looks up the UF2 filename in the loaded fw_dates.json data.
    """
    if not uf2_path:
        return None
    filename = os.path.basename(uf2_path)
    dates = load_bundled_fw_dates()
    date_str = dates.get(filename)
    return parse_fw_date(date_str)


def get_bundled_fw_date_str(uf2_path):
    """Return the raw date string for a bundled UF2, or 'Unknown'."""
    if not uf2_path:
        return "Unknown"
    filename = os.path.basename(uf2_path)
    dates = load_bundled_fw_dates()
    return dates.get(filename, "Unknown")


def find_rpi_rp2_drive():
    """Return the drive path of the first RPI-RP2 mass-storage device, or None."""
    info = find_rpi_rp2_drive_info()
    return info[0] if info else None


def find_rpi_rp2_drive_info():
    """
    Return (drive_path, display_label) for the first RPI-RP2 bootloader drive,
    or None if none is found.
    display_label is built from INFO_UF2.TXT, e.g. "RPI-RP2  (G:)"
    """
    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            info_path = os.path.join(f"{letter}:\\", "INFO_UF2.TXT")
            if os.path.exists(info_path):
                try:
                    with open(info_path) as f:
                        contents = f.read()
                    if "RP2" not in contents:
                        continue
                    board_id = "RPI-RP2"
                    for line in contents.splitlines():
                        if line.lower().startswith("board-id"):
                            parts = line.split(":", 1)
                            if len(parts) == 2:
                                board_id = parts[1].strip()
                            break
                    drive = f"{letter}:\\"
                    label = f"{board_id}  ({letter}:)"
                    return (drive, label)
                except Exception:
                    pass
    else:
        for base in ["/media", "/mnt", "/Volumes"]:
            if not os.path.exists(base):
                continue
            for root, dirs, files in os.walk(base):
                if "INFO_UF2.TXT" in files:
                    info_path = os.path.join(root, "INFO_UF2.TXT")
                    board_id = "RPI-RP2"
                    try:
                        with open(info_path) as f:
                            for line in f:
                                if line.lower().startswith("board-id"):
                                    parts = line.split(":", 1)
                                    if len(parts) == 2:
                                        board_id = parts[1].strip()
                                    break
                    except Exception:
                        pass
                    label = f"{board_id}  ({root})"
                    return (root, label)
                if root.count(os.sep) - base.count(os.sep) > 2:
                    break
    return None


def flash_uf2(uf2_path, drive_path):
    dest = os.path.join(drive_path, os.path.basename(uf2_path))
    shutil.copy2(uf2_path, dest)


def _build_rp2040_reboot_uf2():
    """
    Build a minimal single-block UF2 payload that tells the RP2040 bootloader
    to cycle back into BOOTSEL mode.  Uses the NOT_MAIN_FLASH + FAMILY_ID flags
    so no data is actually written to flash — the bootloader simply reboots.
    Returns a 512-byte bytes object.
    """
    import struct
    UF2_MAGIC_START0 = 0x0A324655
    UF2_MAGIC_START1 = 0x9E5D5157
    UF2_MAGIC_END    = 0x0AB16F30
    RP2040_FAMILY_ID = 0xE48BFF56
    FLAG_NOT_MAIN_FLASH = 0x00000001
    FLAG_FAMILY_ID      = 0x00002000

    flags   = FLAG_NOT_MAIN_FLASH | FLAG_FAMILY_ID
    payload = bytes(256)   # 256 zero bytes — not written to flash
    header  = struct.pack('<IIIIIIII',
        UF2_MAGIC_START0, UF2_MAGIC_START1,
        flags,
        0x20000000,   # target address (SRAM — irrelevant, not flashed)
        256,          # payload size
        0,            # block index
        1,            # total blocks
        RP2040_FAMILY_ID,
    )
    block = header + payload + struct.pack('<I', UF2_MAGIC_END)
    return block.ljust(512, b'\x00')


def flash_uf2_with_reboot(uf2_path, drive_path, status_cb=None):
    """
    Flash a UF2 file with a clean BOOTSEL reboot cycle first.

    Problem: after switching from Alternatefw firmware the Pico's USB stack
    can be in a dirty state.  Writing the UF2 directly sometimes leaves the
    firmware in a broken state.

    Solution:
      1. Write a minimal reboot UF2 to the BOOTSEL drive  → Pico reboots
      2. Wait for the BOOTSEL drive to disappear            (up to 8 s)
      3. Wait for it to reappear fresh                     (up to 15 s)
      4. Write the real UF2 to the new, clean drive

    status_cb(msg): optional callable for progress text updates.
    Raises RuntimeError if the drive does not come back in time.
    """
    def _status(msg):
        if status_cb:
            status_cb(msg)

    # ── Step 1: trigger a clean reboot ───────────────────────────────────
    _status("Rebooting Pico for a clean flash cycle…")
    reboot_payload = _build_rp2040_reboot_uf2()
    reboot_dest = os.path.join(drive_path, "_reboot_.uf2")
    try:
        with open(reboot_dest, "wb") as f:
            f.write(reboot_payload)
    except Exception:
        pass   # drive may disconnect mid-write — that's expected

    # ── Step 2: wait for the drive to disappear ───────────────────────────
    _status("Waiting for Pico to reboot…")
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if not find_rpi_rp2_drive():
            break
        time.sleep(0.3)

    # ── Step 3: wait for it to reappear ──────────────────────────────────
    _status("Waiting for BOOTSEL drive to reappear…")
    new_drive = None
    deadline = time.time() + 15.0
    while time.time() < deadline:
        new_drive = find_rpi_rp2_drive()
        if new_drive:
            break
        time.sleep(0.3)

    if not new_drive:
        raise RuntimeError(
            "Pico did not reappear as a BOOTSEL drive after reboot.\n"
            "Try unplugging and re-plugging the Pico while holding BOOTSEL.")

    time.sleep(0.5)   # brief settle after the drive mounts

    # ── Step 4: flash the real UF2 ───────────────────────────────────────
    _status("Flashing firmware…")
    flash_uf2(uf2_path, new_drive)


def enter_bootsel_for(screen):
    """
    Device-agnostic BOOTSEL helper shared by all configurator screens.

    `screen` must have:  .pico (PicoSerial), ._set_status(), ._wait_for_port()

    Two paths:
      • Already in config mode (pico.connected) → send BOOTSEL directly.
      • Not connected → send XInput magic sequence, wait for CDC port, then BOOTSEL.
    """
    if screen.pico.connected:
        if messagebox.askyesno("BOOTSEL Mode",
                "Enter BOOTSEL mode?\n\n"
                "The controller will appear as a USB drive (RPI-RP2)\n"
                "for firmware flashing."):
            screen.pico.bootsel()
            screen._set_status("   BOOTSEL mode — RPI-RP2 drive should appear", ACCENT_ORANGE)
        return

    if not XINPUT_AVAILABLE:
        messagebox.showinfo("Not Connected",
            "Connect to the controller first,\n"
            "or hold BOOTSEL while plugging in.")
        return

    if not messagebox.askyesno("BOOTSEL via XInput",
            "The controller isn't in Config Mode.\n\n"
            "Switch via XInput then enter BOOTSEL?"):
        return

    screen._set_status("   Switching to config mode...", ACCENT_BLUE)
    controllers = xinput_get_connected()
    if not controllers:
        screen._set_status("   No controllers found", ACCENT_RED)
        return

    slot = controllers[0][0]
    for left, right in MAGIC_STEPS:
        xinput_send_vibration(slot, left, right)
        time.sleep(0.08)
    xinput_send_vibration(slot, 0, 0)

    screen._set_status("   Waiting for config port...", ACCENT_BLUE)
    port = screen._wait_for_port(8.0)
    if not port:
        screen._set_status("   Failed to enter config mode", ACCENT_RED)
        return

    screen._set_status("   Sending BOOTSEL command...", ACCENT_ORANGE)
    try:
        screen.pico.connect(port)
        for _ in range(3):
            if screen.pico.ping():
                break
            time.sleep(0.3)
        screen.pico.bootsel()
        screen._set_status("   BOOTSEL mode — RPI-RP2 drive should appear", ACCENT_ORANGE)
    except Exception as exc:
        screen._set_status(f"   BOOTSEL failed: {exc}", ACCENT_RED)



#  SERIAL COMMUNICATION


class PicoSerial:
    def __init__(self):
        self.ser = None

    @staticmethod
    def find_config_port():
        """Return the first COM port that belongs to any known OCC firmware variant."""
        for p in serial.tools.list_ports.comports():
            if p.vid == CONFIG_MODE_VID and p.pid in CONFIG_MODE_PIDS:
                return p.device
        return None

    @staticmethod
    def list_ports():
        result = []
        for p in serial.tools.list_ports.comports():
            is_pico = (p.vid == CONFIG_MODE_VID and p.pid in CONFIG_MODE_PIDS)
            device_label = CONFIG_MODE_PIDS.get(p.pid, "OCC Device") if is_pico else p.description
            label = f"{p.device} — {device_label}" if is_pico else f"{p.device} — {p.description}"
            result.append((p.device, label, is_pico))
        return result

    def connect(self, port):
        self.disconnect()
        last_exc = None
        for attempt in range(5):
            try:
                self.ser = serial.Serial(port, BAUD_RATE, timeout=TIMEOUT)
                time.sleep(0.2)
                self.ser.reset_input_buffer()
                return
            except (serial.SerialException, OSError) as exc:
                last_exc = exc
                if attempt < 4:
                    time.sleep(0.4)
        raise last_exc

    def flush_input(self):
        """Discard any bytes sitting in the OS receive buffer.

        Call this after stopping a SCAN/MONITOR session and before sending new
        commands.  The firmware streams PIN:/MVAL: lines continuously while in
        scan mode; those lines accumulate in the OS buffer and will be returned
        by the next readline() call — corrupting the response to whatever
        command follows.  reset_input_buffer() atomically discards them all.
        """
        try:
            if self.connected:
                self.ser.reset_input_buffer()
        except Exception:
            pass

    def disconnect(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    @property
    def connected(self):
        return self.ser is not None and self.ser.is_open

    def send(self, cmd):
        if not self.connected:
            raise ConnectionError("Not connected")
        self.ser.write((cmd + "\n").encode("ascii"))
        self.ser.flush()
        return self.ser.readline().decode("ascii", errors="replace").strip()

    def ping(self):
        try:
            return self.send("PING") == "PONG"
        except Exception:
            return False

    def get_fw_date(self):
        """Query the firmware build date via GET_FW_DATE.

        Returns the raw date string (e.g. 'Jun 15 2025') or None if
        the firmware doesn't support this command (older builds).
        """
        try:
            r = self.send("GET_FW_DATE")
            if r.startswith("FW_DATE:"):
                return r[8:].strip()
        except Exception:
            pass
        return None

    def get_config(self):
        """Read config.
        Firmware sends:
          DEVTYPE:<type>
          CFG:...
          LED:...
          LED_COLORS:...
          LED_MAP:...
        Returns a dict with all key/value pairs plus 'device_type'.
        """
        # First line is now DEVTYPE (added in firmware v12+).
        # For backward compatibility with older firmware that sends CFG: directly,
        # we peek at the first line and handle both cases.
        r = self.send("GET_CONFIG")

        device_type = "unknown"
        cfg_line = None

        if r.startswith("DEVTYPE:"):
            device_type = r[8:].strip()
            # Next line should be CFG:
            cfg_line = self.ser.readline().decode("ascii", errors="replace").strip()
        elif r.startswith("CFG:"):
            # Old firmware without DEVTYPE — treat as unknown
            cfg_line = r
        else:
            raise ValueError(f"Bad response: {r}")

        if not cfg_line.startswith("CFG:"):
            raise ValueError(f"Expected CFG: line, got: {cfg_line}")

        cfg = {"device_type": device_type}
        for kv in cfg_line[4:].split(","):
            kv = kv.strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                cfg[k.strip()] = v.strip()
        for _ in range(3):
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            if line.startswith("LED:"):
                for kv in line[4:].split(","):
                    kv = kv.strip()
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        cfg["led_" + k.strip()] = v.strip()
            elif line.startswith("LED_COLORS:"):
                cfg["led_colors_raw"] = line[11:]
            elif line.startswith("LED_MAP:"):
                cfg["led_map_raw"] = line[8:]
        return cfg

    def set_value(self, key, val):
        r = self.send(f"SET:{key}={val}")
        if r != "OK":
            raise ValueError(f"SET {key}: {r}")

    def save(self):
        if self.send("SAVE") != "OK":
            raise ValueError("SAVE failed")

    def defaults(self):
        if self.send("DEFAULTS") != "OK":
            raise ValueError("DEFAULTS failed")

    def start_scan(self):
        """Start SCAN. Returns list of pre-scan lines (like I2C:ADXL345) before OK."""
        self.ser.write(b"SCAN\n")
        self.ser.flush()
        pre_lines = []
        deadline = time.time() + 5.0
        while time.time() < deadline:
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            if line == "OK":
                return pre_lines
            elif line:
                pre_lines.append(line)
        raise ValueError("SCAN: no OK response")

    def stop_scan(self):
        self.ser.write(b"STOP\n")
        self.ser.flush()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            if line == "OK":
                return

    def read_scan_line(self, timeout=0.15):
        old_timeout = self.ser.timeout
        self.ser.timeout = timeout
        try:
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            return line if line else None
        finally:
            self.ser.timeout = old_timeout

    def start_monitor_adc(self, pin):
        """Start ADC monitoring. Returns 'OK' or raises."""
        r = self.send(f"MONITOR_ADC:{pin}")
        if r != "OK":
            raise ValueError(f"MONITOR_ADC: {r}")

    def start_monitor_i2c(self, axis=None):
        """Start I2C accelerometer monitoring.

        axis=0/1/2 — single-axis mode (MONITOR_I2C:<axis>): firmware sends only
        MVAL:<value> at 50 Hz. Used by the live bar graph in the configurator.

        axis=None — all-axes debug mode (MONITOR_I2C): firmware sends MVAL_X/Y/Z
        at 20 Hz. Used by the debug console MONITOR I2C button.
        """
        cmd = f"MONITOR_I2C:{axis}" if axis is not None else "MONITOR_I2C"
        r = self.send(cmd)
        if r != "OK":
            raise ValueError(f"{cmd}: {r}")

    def start_monitor_digital(self, pin):
        """Start digital pin monitoring."""
        r = self.send(f"MONITOR_DIG:{pin}")
        if r != "OK":
            raise ValueError(f"MONITOR_DIG: {r}")

    def stop_monitor(self):
        """Stop monitoring (same as stop_scan)."""
        self.stop_scan()

    def drain_monitor_latest(self, timeout=0.05):
        """Drain ALL buffered MVAL lines and return only the most recent value.

        This prevents the serial buffer from building up a backlog of stale
        readings. If the consumer (UI) is slower than the producer (firmware),
        older queued values are discarded so the bar graph always shows the
        current sensor state.

        Returns (latest_int_value_or_None, list_of_non_mval_lines).
        The non-MVAL lines (ERR:, etc.) are returned for the debug console.
        """
        latest_val = None
        passthrough = []

        try:
            # Block briefly waiting for at least one line to arrive
            old_timeout = self.ser.timeout
            self.ser.timeout = timeout
            try:
                raw = self.ser.readline()
                line = raw.decode("ascii", errors="replace").strip() if raw else ""
                if line.startswith("MVAL:"):
                    try:
                        latest_val = int(line[5:])
                    except ValueError:
                        pass
                elif line:
                    passthrough.append(line)
            finally:
                self.ser.timeout = old_timeout

            # Now drain everything else already sitting in the OS buffer —
            # no blocking, just consume what's there right now.
            self.ser.timeout = 0
            try:
                while self.ser.in_waiting:
                    raw = self.ser.readline()
                    line = raw.decode("ascii", errors="replace").strip() if raw else ""
                    if not line:
                        break
                    if line.startswith("MVAL:"):
                        try:
                            latest_val = int(line[5:])
                        except ValueError:
                            pass
                    else:
                        passthrough.append(line)
            finally:
                self.ser.timeout = old_timeout

        except Exception:
            pass

        return latest_val, passthrough

    def reboot(self):
        try:
            self.send("REBOOT")
        except Exception:
            pass
        self.disconnect()

    def bootsel(self):
        try:
            self.send("BOOTSEL")
        except Exception:
            pass
        self.disconnect()

    def led_flash(self, idx):
        r = self.send(f"LED_FLASH:{idx}")
        if r != "OK":
            raise ValueError(f"LED_FLASH: {r}")

    def led_solid(self, idx):
        r = self.send(f"LED_SOLID:{idx}")
        if r != "OK":
            raise ValueError(f"LED_SOLID: {r}")

    def led_off(self):
        r = self.send("LED_OFF")
        if r != "OK":
            raise ValueError(f"LED_OFF: {r}")



#  LIVE MONITOR BAR WIDGET


class LiveBarGraph(tk.Canvas):
    """A horizontal bar graph for displaying live 0-4095 sensor values.

    Optional min_marker_var / max_marker_var: tk.IntVar instances whose
    current values are drawn as red vertical lines on the bar so the user
    can see their sensitivity window at a glance.
    """

    BAR_COLOR_LOW  = "#3dbf7d"
    BAR_COLOR_MID  = "#4a9eff"
    BAR_COLOR_HIGH = "#e54545"
    MARKER_COLOR   = "#e54545"

    def __init__(self, parent, label="", width=300, height=28, max_val=4095,
                 min_marker_var=None, max_marker_var=None, invert_var=None):
        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG_CARD
        super().__init__(parent, width=width, height=height,
                         bg=parent_bg, highlightthickness=0, bd=0)
        self._width          = width
        self._height         = height
        self._max_val        = max_val
        self._label          = label
        self._value          = 0
        self._min_marker_var = min_marker_var
        self._max_marker_var = max_marker_var
        self._invert_var     = invert_var
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self._width, self._height
        pad = 2
        inner_w = w - 2 * pad - 2

        inverted = bool(self._invert_var and self._invert_var.get())

        # Background trough
        self.create_rectangle(pad, pad, w - pad, h - pad,
                              fill=BG_INPUT, outline=BORDER, width=1)

        # Value bar
        if self._max_val > 0:
            fraction = min(1.0, max(0.0, self._value / self._max_val))
        else:
            fraction = 0

        # When inverted, flip the fraction so low raw value = full bar
        # (same logic as LiveBarGraphVertical — mirrors firmware inversion)
        disp_fraction = (1.0 - fraction) if inverted else fraction

        bar_w = int(inner_w * disp_fraction)

        if disp_fraction < 0.33:
            color = self.BAR_COLOR_LOW
        elif disp_fraction < 0.66:
            color = self.BAR_COLOR_MID
        else:
            color = self.BAR_COLOR_HIGH

        if bar_w > 0:
            # Always draw from left edge — inversion is already in disp_fraction
            self.create_rectangle(pad + 1, pad + 1, pad + 1 + bar_w, h - pad - 1,
                                  fill=color, outline="")

        # Center line (midpoint marker)
        mid_x = w // 2
        self.create_line(mid_x, pad, mid_x, h - pad, fill="#666670", dash=(2, 2))

        # Min / Max sensitivity markers (red vertical lines)
        if self._min_marker_var is not None and self._max_val > 0:
            try:
                mv = int(self._min_marker_var.get())
                mx = pad + 1 + int(inner_w * min(1.0, max(0.0, mv / self._max_val)))
                self.create_line(mx, pad, mx, h - pad, fill=self.MARKER_COLOR, width=2)
            except Exception:
                pass
        if self._max_marker_var is not None and self._max_val > 0:
            try:
                mv = int(self._max_marker_var.get())
                mx = pad + 1 + int(inner_w * min(1.0, max(0.0, mv / self._max_val)))
                self.create_line(mx, pad, mx, h - pad, fill=self.MARKER_COLOR, width=2)
            except Exception:
                pass

        # Text overlay — percentage matches the displayed bar direction
        pct = int(disp_fraction * 100)
        self.create_text(w // 2, h // 2,
                         text=f"{self._label}  {self._value}  ({pct}%)",
                         fill=TEXT, font=("Consolas", 8))

    def set_value(self, value):
        self._value = max(0, min(self._max_val, int(value)))
        self._draw()

    def redraw_markers(self):
        """Call when min/max vars change so marker lines refresh immediately."""
        self._draw()

    def refresh(self):
        """Redraw without changing the value — call after invert toggle."""
        self._draw()


class LiveBarGraphVertical(tk.Canvas):
    """
    Vertical bar graph for displaying live 0-4095 joystick axis values.

    The bar grows upward from the bottom.  A centre-line at 50% shows the
    neutral/rest position.  The label at the top indicates the current raw
    value and percentage.  When invert_var is set and True the bar is drawn
    inverted (top = 0, bottom = 4095) so the user can see how inversion
    will affect the XInput output.
    """

    BAR_COLOR_LOW  = "#3dbf7d"
    BAR_COLOR_MID  = "#4a9eff"
    BAR_COLOR_HIGH = "#e54545"
    UP_LABEL   = "UP ▲"
    DOWN_LABEL = "▼ DOWN"

    def __init__(self, parent, label="", width=60, height=220, max_val=4095,
                 invert_var=None):
        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG_CARD
        super().__init__(parent, width=width, height=height,
                         bg=parent_bg, highlightthickness=0, bd=0)
        self._width      = width
        self._height     = height
        self._max_val    = max_val
        self._label      = label
        self._value      = 0
        self._invert_var = invert_var
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self._width, self._height
        pad = 4
        inner_h = h - 2 * pad - 24   # reserve top for text

        inverted = bool(self._invert_var and self._invert_var.get())

        # Background trough
        self.create_rectangle(pad, pad + 20, w - pad, h - pad,
                              fill=BG_INPUT, outline=BORDER, width=1)

        # Fraction of range
        fraction = min(1.0, max(0.0, self._value / self._max_val)) if self._max_val else 0
        if inverted:
            fraction = 1.0 - fraction

        bar_h = int(inner_h * fraction)

        # Colour by zone
        if fraction < 0.33:
            color = self.BAR_COLOR_LOW
        elif fraction < 0.66:
            color = self.BAR_COLOR_MID
        else:
            color = self.BAR_COLOR_HIGH

        # Bar grows upward
        if bar_h > 0:
            top = pad + 20 + (inner_h - bar_h)
            bot = h - pad - 1
            self.create_rectangle(pad + 1, top, w - pad - 1, bot,
                                  fill=color, outline="")

        # Centre marker
        mid_y = pad + 20 + inner_h // 2
        self.create_line(pad, mid_y, w - pad, mid_y, fill="#666670", dash=(2, 2))

        # Direction labels
        self.create_text(w // 2, pad + 24, text=self.UP_LABEL,
                         fill=TEXT_DIM, font=("Consolas", 7), anchor="n")
        self.create_text(w // 2, h - pad - 2, text=self.DOWN_LABEL,
                         fill=TEXT_DIM, font=("Consolas", 7), anchor="s")

        # Value text at top
        pct = int(fraction * 100)
        self.create_text(w // 2, pad + 2,
                         text=f"{self._value} ({pct}%)",
                         fill=TEXT, font=("Consolas", 7), anchor="n")

    def set_value(self, value):
        self._value = max(0, min(self._max_val, int(value)))
        self._draw()

    def refresh(self):
        """Redraw without changing the value — call after invert toggle."""
        self._draw()


class CalibratedBarGraph(tk.Canvas):
    """Shows the post-sensitivity, post-deadzone processed output (0-65535).

    Applies the same pipeline as the firmware:
      1. Clamp raw to [min_val, max_val] and remap to [0, 4095].
      2. Apply a silent 5% deadzone at the low end.
      3. Apply EMA smoothing using ema_alpha_var (mirrors firmware logic).
      4. Map remainder to [0, 65535] for display.
    """

    BAR_COLOR   = "#4a9eff"
    _DZ_FRAC    = 0.05   # 5% silent deadzone

    def __init__(self, parent, label="Calibrated Value", width=300, height=24,
                 min_var=None, max_var=None, invert_var=None, ema_alpha_var=None):
        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG_CARD
        super().__init__(parent, width=width, height=height,
                         bg=parent_bg, highlightthickness=0, bd=0)
        self._width        = width
        self._height       = height
        self._label        = label
        self._raw          = 0
        self._min_var      = min_var
        self._max_var      = max_var
        self._invert_var   = invert_var
        self._ema_alpha_var = ema_alpha_var
        # EMA state (fixed-point * 256) mirroring firmware ema_state_t
        self._ema_state    = 0
        self._ema_seeded   = False
        self._draw()

    def _get_alpha(self):
        """Return alpha in [5..256]. 256 = no smoothing (pass-through)."""
        if self._ema_alpha_var is None:
            return 256
        try:
            v = int(self._ema_alpha_var.get())
            return max(5, min(256, v))
        except Exception:
            return 256

    def _apply_ema(self, calibrated):
        """Apply EMA to a calibrated [0..65535] value. Mirrors firmware ema_update()."""
        alpha = self._get_alpha()
        raw32 = calibrated << 8
        if not self._ema_seeded:
            self._ema_state  = raw32
            self._ema_seeded = True
        else:
            if alpha >= 256:
                self._ema_state = raw32
            elif raw32 > self._ema_state:
                self._ema_state += (alpha * (raw32 - self._ema_state)) >> 8
            else:
                self._ema_state -= (alpha * (self._ema_state - raw32)) >> 8
        return self._ema_state >> 8

    def reset_ema(self):
        """Reset EMA state (call when monitoring restarts)."""
        self._ema_seeded = False
        self._ema_state  = 0

    def _calibrate(self, raw):
        try:
            mn  = int(self._min_var.get())    if self._min_var    else 0
            mx  = int(self._max_var.get())    if self._max_var    else 4095
            inv = bool(self._invert_var.get()) if self._invert_var else False
        except Exception:
            mn, mx, inv = 0, 4095, False

        if mx <= mn:
            scaled = raw
        elif raw <= mn:
            scaled = 0
        elif raw >= mx:
            scaled = 4095
        else:
            scaled = int((raw - mn) * 4095 / (mx - mn))

        if inv:
            scaled = 4095 - scaled

        dz = int(4095 * self._DZ_FRAC)   # 204
        if scaled <= dz:
            return 0
        return max(0, min(65535, int((scaled - dz) * 65535 / (4095 - dz))))

    def _draw(self):
        self.delete("all")
        w, h = self._width, self._height
        pad  = 2

        cal_raw = self._calibrate(self._raw)
        cal     = self._apply_ema(cal_raw)
        frac = cal / 65535.0

        self.create_rectangle(pad, pad, w - pad, h - pad,
                              fill=BG_INPUT, outline=BORDER, width=1)

        bar_w = int((w - 2 * pad - 2) * frac)
        if bar_w > 0:
            self.create_rectangle(pad + 1, pad + 1, pad + 1 + bar_w, h - pad - 1,
                                  fill=self.BAR_COLOR, outline="")

        pct = int(frac * 100)
        self.create_text(w // 2, h // 2,
                         text=f"{self._label}  {cal}  ({pct}%)",
                         fill=TEXT, font=("Consolas", 8))

    def set_raw(self, raw_value):
        self._raw = int(raw_value)
        self._draw()

    def redraw(self):
        self._draw()



#  SCREENS


class FlashFirmwareScreen:
    """
    Shown automatically when a Pico in BOOTSEL (USB mass-storage) mode is
    detected.  Displays a scrollable tile grid of available .uf2 files and
    lets the user flash one with a single click.  Disappears back to the
    main menu when the drive is unplugged.
    """

    POLL_MS    = 1000   # how often to re-check for the drive
    TILE_IMG_H = 140    # height of the image area inside the tile (px)
    TILE_LBL_H = 28     # height of the label area below the image (px)
    TILE_PAD   = 10     # gap between tiles
    COLS       = 4      # columns in the grid
    FIXED_ROWS = 3      # always show exactly this many rows

    def __init__(self, root, on_back):
        self.root    = root
        self._on_back = on_back   # called when we want to return to main menu
        self._poll_job   = None
        self._last_drive = None

        self.frame = tk.Frame(root, bg=BG_MAIN)
        self._build()

    # ── Layout ────────────────────────────────────────────────────

    def _build(self):
        # ── Title bar — identical to MainMenu ─────────────────
        title_bar = tk.Frame(self.frame, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        title_bar.pack(fill="x", padx=0, pady=(0, 0))

        inner_title = tk.Frame(title_bar, bg=BG_CARD)
        inner_title.pack(fill="x", padx=24, pady=16)

        tk.Label(inner_title, text="OCC",
                 bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 18, "bold")).pack(anchor="w")
        tk.Label(inner_title, text="Open Controller Configurator",
                 bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 13)).pack(anchor="w")

        # ── Page heading ──────────────────────────────────────
        heading_frame = tk.Frame(self.frame, bg=BG_MAIN)
        heading_frame.pack(fill="x", pady=(16, 4))

        tk.Label(heading_frame, text="Firmware Installation",
                 bg=BG_MAIN, fg=ACCENT_BLUE,
                 font=(FONT_UI, 16, "bold")).pack()

        self._subtitle = tk.Label(heading_frame,
                                  text="Pico in BOOTSEL detected!\nConfirm device and choose firmware.",
                                  bg=BG_MAIN, fg=TEXT_HEADER,
                                  font=(FONT_UI, 10), justify="center")
        self._subtitle.pack()

        # ── Device dropdown ───────────────────────────────────
        combo_frame = tk.Frame(self.frame, bg=BG_MAIN)
        combo_frame.pack(pady=(8, 14))

        self._device_var = tk.StringVar(value="Scanning for USB devices…")
        self._device_combo = CustomDropdown(combo_frame, state="readonly",
                                          textvariable=self._device_var,
                                          width=32,
                                          values=[])
        self._device_combo.pack()
        self._refresh_device_combo()

        # ── Scrollable tile grid ──────────────────────────────
        grid_outer = tk.Frame(self.frame, bg=BORDER,
                              highlightbackground=BORDER, highlightthickness=1)
        grid_outer.pack(fill="both", expand=True, padx=40, pady=(0, 14))

        self._canvas = tk.Canvas(grid_outer, bg=BG_MAIN,
                                 highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(grid_outer, orient="vertical",
                                 command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._tile_frame = tk.Frame(self._canvas, bg=BG_MAIN)
        self._tile_window = self._canvas.create_window(
            (0, 0), window=self._tile_frame, anchor="nw")

        self._tile_frame.bind("<Configure>", self._on_tile_frame_configure)
        self._canvas.bind("<Configure>",     self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>",    self._on_mousewheel)
        self._tile_frame.bind("<MouseWheel>", self._on_mousewheel)

        self._build_tiles()
        # Trigger initial reflow after the window is drawn
        self.frame.after(50, self._reflow_tiles)

        # ── Reset Pico card (bottom) ──────────────────────────
        rst_card = tk.Frame(self.frame, bg=BG_CARD,
                            highlightbackground=BORDER, highlightthickness=1)
        rst_card.pack(fill="x", padx=40, pady=(0, 10))

        rst_inner = tk.Frame(rst_card, bg=BG_CARD)
        rst_inner.pack(fill="x", padx=20, pady=14)

        tk.Label(rst_inner, text="Reset Pico",
                 bg=BG_CARD, fg=ACCENT_RED,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 4))

        rst_body = tk.Frame(rst_inner, bg=BG_CARD)
        rst_body.pack(fill="x")

        self._rst_icon = tk.Label(rst_body, text="●", bg=BG_CARD,
                                  fg=ACCENT_RED, font=(FONT_UI, 14))
        self._rst_icon.pack(side="left", padx=(0, 10))

        rst_text = tk.Frame(rst_body, bg=BG_CARD)
        rst_text.pack(side="left", fill="x", expand=True)

        self._rst_drive_label = tk.Label(rst_text,
                                         text="Pico USB Detected: —",
                                         bg=BG_CARD, fg=ACCENT_GREEN,
                                         font=(FONT_UI, 9), anchor="w")
        self._rst_drive_label.pack(anchor="w")

        tk.Label(rst_text, text="Want to wipe pico flash to factory?",
                 bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 10, "bold"), anchor="w").pack(anchor="w")

        tk.Label(rst_text, text="Will use Nuke.uf2 and wipe storage.",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), anchor="w").pack(anchor="w")

        self._rst_btn = RoundedButton(rst_body, text="Factory Reset",
                                      command=self._do_factory_reset,
                                      bg_color=ACCENT_BLUE,
                                      btn_width=160, btn_height=36)
        self._rst_btn.pack(side="right")

        # ── Alpha hint ────────────────────────────────────────
        tk.Label(self.frame,
                 text="Firmware is in ALPHA Development. Nothing is final, get over it.",
                 bg=BG_MAIN, fg=TEXT_DIM, font=(FONT_UI, 8)).pack(
                     anchor="e", padx=40, pady=(0, 8))

    # ── Tile grid helpers ─────────────────────────────────────────

    def _refresh_device_combo(self):
        """Populate the device dropdown from live USB detection."""
        info = find_rpi_rp2_drive_info()
        if info:
            drive, label = info
            self._device_combo.config(values=[label])
            self._device_var.set(label)
            self._device_combo.current(0)
        else:
            self._device_combo.config(values=["No USB device detected"])
            self._device_var.set("No USB device detected")

    def _build_tiles(self):
        """Build the firmware tile grid from available .uf2 files."""
        # Cancel any running GIF animations from a previous build
        # Signal all running GIF loops to stop
        for stop_flag in getattr(self, '_gif_jobs', []):
            try:
                stop_flag[0] = True
            except Exception:
                pass
        self._gif_jobs = []
        self._gif_refs = []   # keep PhotoImage refs alive to prevent GC

        for w in self._tile_frame.winfo_children():
            w.destroy()

        uf2_files = find_uf2_files()   # list of (name, path) tuples
        tile_total_h = self.TILE_IMG_H + self.TILE_LBL_H

        # Always show exactly COLS * FIXED_ROWS tiles
        total = self.COLS * self.FIXED_ROWS

        for idx in range(total):
            row = idx // self.COLS
            col = idx  % self.COLS

            tile_outer = tk.Frame(self._tile_frame, bg=BORDER,
                                  highlightthickness=0,
                                  width=200, height=tile_total_h)
            tile_outer.grid(row=row, column=col,
                            padx=self.TILE_PAD, pady=self.TILE_PAD,
                            sticky="nsew")
            tile_outer.grid_propagate(False)

            # Image area (top portion of tile)
            img_area = tk.Frame(tile_outer, bg=BG_CARD,
                                width=198, height=self.TILE_IMG_H - 1)
            img_area.place(x=1, y=1, width=198, height=self.TILE_IMG_H - 1)
            img_area.pack_propagate(False)

            # Label area (bottom strip)
            lbl_area = tk.Frame(tile_outer, bg="#222226",
                                width=198, height=self.TILE_LBL_H)
            lbl_area.place(x=1, y=self.TILE_IMG_H,
                           width=198, height=self.TILE_LBL_H)
            lbl_area.pack_propagate(False)

            # ── Rounded corners via overlay corner masks ──────────
            # Each canvas is _cr x _cr, placed over a tile corner.
            # A full oval (_d x _d) is offset so only the correct
            # quadrant shows — colored to match the adjacent interior
            # area so the corner blends seamlessly into the background.
            _cr = 10
            _d  = _cr * 2
            _th = tile_total_h
            for (cx, cy, ox, oy, oval_color) in [
                (0,        0,        0,    0,    BG_CARD),    # top-left:     image area color
                (200-_cr,  0,        -_cr, 0,    BG_CARD),    # top-right:    image area color
                (0,        _th-_cr,  0,    -_cr, "#222226"),  # bottom-left:  label area color
                (200-_cr,  _th-_cr,  -_cr, -_cr, "#222226"),  # bottom-right: label area color
            ]:
                cm = tk.Canvas(tile_outer, width=_cr, height=_cr,
                               bg=BG_MAIN, highlightthickness=0, bd=0)
                cm.place(x=cx, y=cy)
                cm.create_oval(ox, oy, ox + _d, oy + _d,
                               fill=oval_color, outline=oval_color)

            if idx < len(uf2_files):
                name, path = uf2_files[idx]

                # ── GIF / image area ──────────────────────────────
                gif_path = self._find_gif_for_uf2(path)
                img_label = tk.Label(img_area, bg=BG_CARD, cursor="hand2")
                img_label.place(relx=0.5, rely=0.5, anchor="center")

                if gif_path:
                    self._start_gif(img_label, gif_path, img_area)
                else:
                    # No GIF — show a dim placeholder icon
                    img_label.config(text="▶", fg=TEXT_DIM,
                                     font=(FONT_UI, 28))

                # ── Name label below the image ────────────────────
                name_lbl = tk.Label(lbl_area, text=name,
                                    bg="#222226", fg=TEXT_HEADER,
                                    font=(FONT_UI, 8, "bold"),
                                    anchor="center", justify="center")
                name_lbl.place(relx=0.5, rely=0.5, anchor="center")

                # ── Hover + click on the whole tile ──────────────
                hover_bg   = "#3a3a3f"
                lbl_hover  = "#2a2a2e"

                def _enter(e, ia=img_area, la=lbl_area, il=img_label, nl=name_lbl):
                    ia.config(bg=hover_bg)
                    il.config(bg=hover_bg)
                    la.config(bg=lbl_hover)
                    nl.config(bg=lbl_hover)
                def _leave(e, ia=img_area, la=lbl_area, il=img_label, nl=name_lbl):
                    ia.config(bg=BG_CARD)
                    il.config(bg=BG_CARD)
                    la.config(bg="#222226")
                    nl.config(bg="#222226")
                def _click(e, p=path):
                    drive = find_rpi_rp2_drive()
                    if drive:
                        self._do_flash(p, drive)

                for widget in (img_area, lbl_area, img_label, name_lbl):
                    widget.bind("<Enter>",    _enter)
                    widget.bind("<Leave>",    _leave)
                    widget.bind("<Button-1>", _click)
                    widget.config(cursor="hand2")
            # else: empty dark tile

    def _find_gif_for_uf2(self, uf2_path):
        """
        Look for a .gif with the same base name as the .uf2 file.
        Searches the same directories find_uf2_files() uses.
        Returns the full path if found, else None.
        """
        base = os.path.splitext(os.path.basename(uf2_path))[0]
        gif_name = base + ".gif"
        search_dirs = []
        bundle_dir = getattr(sys, '_MEIPASS', None)
        if bundle_dir:
            search_dirs.append(bundle_dir)
        exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        search_dirs.append(exe_dir)
        src_dir = os.path.dirname(os.path.abspath(__file__))
        if src_dir != exe_dir:
            search_dirs.append(src_dir)
        for d in search_dirs:
            candidate = os.path.join(d, gif_name)
            if os.path.isfile(candidate):
                return candidate
        return None

    def _start_gif(self, label, gif_path, container):
        """
        Load all GIF frames and loop continuously for as long as the
        Firmware screen is visible.  No hover logic — plays immediately.
        """
        try:
            frames = []
            idx = 0
            while True:
                try:
                    frame = tk.PhotoImage(file=gif_path,
                                         format=f"gif -index {idx}")
                    frames.append(frame)
                    idx += 1
                except tk.TclError:
                    break
            if not frames:
                return

            # Keep every frame reference alive — tkinter GCs PhotoImages
            # as soon as the Python object is collected.
            self._gif_refs.extend(frames)

            n     = len(frames)
            delay = 80          # ms per frame
            stop  = [False]
            self._gif_jobs.append(stop)

            def _animate(frame_idx=0):
                if stop[0] or not label.winfo_exists():
                    return
                label.config(image=frames[frame_idx])
                self.root.after(delay, _animate, (frame_idx + 1) % n)

            _animate()

        except Exception:
            pass   # silently fall back to placeholder icon

    def _on_tile_frame_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._tile_window, width=event.width)
        self._reflow_tiles(event.width)

    def _reflow_tiles(self, canvas_width=None):
        """Resize tile widgets so they fill the canvas width evenly."""
        if canvas_width is None:
            canvas_width = self._canvas.winfo_width()
        if canvas_width <= 1:
            return  # not yet rendered
        scrollbar_w = 18   # reserve space so scrollbar never overlaps tiles
        pad_total = self.TILE_PAD * (self.COLS + 1)
        tile_w = max(80, (canvas_width - pad_total - scrollbar_w) // self.COLS)
        tile_total_h = self.TILE_IMG_H + self.TILE_LBL_H
        inner_w = tile_w - 2
        _cr = 10
        for tile_outer in self._tile_frame.winfo_children():
            tile_outer.config(width=tile_w, height=tile_total_h)
            children = tile_outer.winfo_children()
            if len(children) >= 1:
                children[0].place_configure(width=inner_w,
                                             height=self.TILE_IMG_H - 1)
            if len(children) >= 2:
                children[1].place_configure(y=self.TILE_IMG_H, width=inner_w,
                                             height=self.TILE_LBL_H)
            corner_positions = [
                (0,           0),
                (tile_w-_cr,  0),
                (0,           tile_total_h-_cr),
                (tile_w-_cr,  tile_total_h-_cr),
            ]
            for i, (cx, cy) in enumerate(corner_positions):
                ci = i + 2
                if ci < len(children):
                    children[ci].place_configure(x=cx, y=cy)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── Flashing ──────────────────────────────────────────────────

    def _do_flash(self, uf2_path, drive):
        # ── 1. Show a non-blocking "please wait" popup ──────────────
        wait_dlg = tk.Toplevel(self.root)
        wait_dlg.title("Flashing Firmware")
        wait_dlg.configure(bg=BG_CARD)
        wait_dlg.resizable(False, False)
        wait_dlg.transient(self.root)
        wait_dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # prevent closing

        tk.Label(wait_dlg, text="⚡  Flashing firmware… please wait",
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11),
                 padx=32, pady=28).pack()

        wait_dlg.update_idletasks()
        # Center over parent
        pw = self.root.winfo_width();  ph = self.root.winfo_height()
        px = self.root.winfo_rootx(); py = self.root.winfo_rooty()
        dw = wait_dlg.winfo_width();  dh = wait_dlg.winfo_height()
        wait_dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
        wait_dlg.grab_set()

        # ── 2. Run the flash in a background thread ──────────────────
        def _worker():
            error = None
            try:
                flash_uf2_with_reboot(uf2_path, drive)
            except Exception as e:
                error = e
            # Hand results back to the UI thread
            self.root.after(0, lambda: _on_done(error))

        def _on_done(error):
            wait_dlg.destroy()

            if error:
                _centered_dialog(self.root, "Flash Error",
                                 f"Failed to copy firmware:\n{error}", kind="error")
                return

            # ── 3. Success dialog — auto-closes after 3 seconds ─────
            done_dlg = tk.Toplevel(self.root)
            done_dlg.title("Done")
            done_dlg.configure(bg=BG_CARD)
            done_dlg.resizable(False, False)
            done_dlg.transient(self.root)
            done_dlg.protocol("WM_DELETE_WINDOW", done_dlg.destroy)

            tk.Label(done_dlg, text="✅  Firmware flashed successfully!\n",
                     bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11),
                     justify="center", padx=32, pady=24).pack()

            done_dlg.update_idletasks()
            pw = self.root.winfo_width();  ph = self.root.winfo_height()
            px = self.root.winfo_rootx(); py = self.root.winfo_rooty()
            dw = done_dlg.winfo_width();  dh = done_dlg.winfo_height()
            done_dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")

            # Auto-close after 3 000 ms
            self.root.after(3000, lambda: done_dlg.destroy() if done_dlg.winfo_exists() else None)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Factory Reset ─────────────────────────────────────────────

    def _do_factory_reset(self):
        drive = find_rpi_rp2_drive()
        if not drive:
            messagebox.showwarning("Not Found",
                                   "No Pico in USB mode detected.")
            return
        nuke = find_nuke_uf2()
        if not nuke:
            messagebox.showwarning("Missing File",
                                   "nuke.uf2 not found.\n"
                                   "Place it alongside this exe and try again.")
            return
        if not messagebox.askyesno("Factory Reset",
                                   "This will COMPLETELY ERASE all firmware and "
                                   "settings on the Pico.\n\n"
                                   "Continue?", icon="warning"):
            return
        try:
            flash_uf2(nuke, drive)
        except Exception as e:
            messagebox.showerror("Reset Error", f"Failed:\n{e}")

    # ── Polling ───────────────────────────────────────────────────

    def _poll(self):
        info = find_rpi_rp2_drive_info()
        if info:
            drive, label = info
            self._rst_drive_label.config(text=f"Pico USB Detected: {label}")
            self._last_drive = drive
            self._refresh_device_combo()
        else:
            # Drive gone — return to main menu
            self._on_back()
            return
        self._poll_job = self.root.after(self.POLL_MS, self._poll)

    # ── Show / Hide ───────────────────────────────────────────────

    def show(self, drive=None):
        self.root.title("OCC - Firmware Installation")
        # Clear any configurator menu bar left over from App / DrumApp
        self._empty_menu = getattr(self, '_empty_menu', None) or tk.Menu(self.root)
        self.root.config(menu=self._empty_menu)
        self._refresh_device_combo()
        info = find_rpi_rp2_drive_info()
        if info:
            _, label = info
            self._rst_drive_label.config(text=f"Pico USB Detected: {label}")
        elif drive:
            self._rst_drive_label.config(text=f"Pico USB Detected: {drive}")
        self._build_tiles()   # refresh tile list each time we appear
        self.frame.pack(fill="both", expand=True)
        self.frame.after(60, self._reflow_tiles)  # size tiles to fit after render
        self._poll_job = self.root.after(self.POLL_MS, self._poll)

    def hide(self):
        if self._poll_job:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self.frame.pack_forget()



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

    def __init__(self, root, on_back=None):
        self.root = root
        self._on_back = on_back
        self._current_page = 0

        # Serial connection
        self.pico = PicoSerial()

        # Scan / monitor state
        self.scanning = False
        self.scan_target = None
        self._monitoring = False
        self._monitor_thread = None
        self._preview_active = False
        self._preview_seen = {}

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

    # ── Static layout (built once) ────────────────────────────────

    def _build(self):
        # Title bar
        title_bar = tk.Frame(self.frame, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        title_bar.pack(fill="x")
        inner_title = tk.Frame(title_bar, bg=BG_CARD)
        inner_title.pack(fill="x", padx=24, pady=16)
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
        self._stop_scan_and_monitor()
        self._current_page = idx

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

    def _stop_scan_and_monitor(self):
        """Stop any active scan or monitor thread safely."""
        need_stop_scan = self.scanning or self._preview_active
        self.scanning = False
        self._preview_active = False
        if need_stop_scan:
            try:
                self.pico.stop_scan()
            except Exception:
                pass
        if self._monitoring:
            self._monitoring = False
            try:
                self.pico.stop_monitor()
            except Exception:
                pass

    # ── Shared helpers ────────────────────────────────────────────

    def _make_status_box(self, parent):
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
        slbl = tk.Label(sf, text="Click here to start Input Detection",
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

        _sf, status_lbl, gpio_lbl = self._make_status_box(f)

        # Restore previous detection if present
        if key in self.detected:
            pin = self.detected[key]
            status_lbl.config(text=f"\u2713 Previously set to GPIO {pin}.", fg=ACCENT_GREEN)
            gpio_lbl.config(text=f"GPIO {pin}")

        detect_btn, cancel_btn = self._make_detect_cancel_row(f, accent)

        def start_detect():
            if not self.pico.connected:
                status_lbl.config(text="\u26a0  Not connected to controller.", fg=ACCENT_ORANGE)
                return
            if self.scanning:
                return
            self.scanning = True
            self.scan_target = key
            detect_btn.set_state("disabled")
            cancel_btn.set_state("normal")
            status_lbl.config(text=f"Waiting for {name}\u2026  Press the button now.", fg=ACCENT_BLUE)
            gpio_lbl.config(text="")

            def _on_detected(pin):
                self.detected[key] = pin
                self.scanning = False
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text="\u2713 Detection successful! Ready for next step.",
                                   fg=ACCENT_GREEN)
                gpio_lbl.config(text=f"GPIO {pin}")

            def _on_error(msg):
                self.scanning = False
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text=f"\u26a0  Scan error: {msg}", fg=ACCENT_RED)

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
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text="Detection cancelled.", fg=TEXT_DIM)

            cancel_btn._command = _cancel
            cancel_btn._render(cancel_btn._bg)
            threading.Thread(target=_thread, daemon=True).start()

        detect_btn._command = start_detect
        detect_btn._render(detect_btn._bg)

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

            def _on_detected(pin):
                self.detected[key] = pin
                self.scanning = False
                det_btn.set_state("normal")
                can_btn.set_state("disabled")
                gpio_lbl.config(text=f"GPIO {pin}", fg=ACCENT_GREEN)
                status_lbl.config(text="\u2713 Detected", fg=ACCENT_GREEN)

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
                det_btn.set_state("normal")
                can_btn.set_state("disabled")
                status_lbl.config(text="Cancelled", fg=TEXT_DIM)
                prev = self.detected.get(key)
                gpio_lbl.config(text=f"GPIO {prev}" if prev is not None else "\u2014",
                                 fg=ACCENT_GREEN if prev is not None else TEXT_DIM)

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

        _sf, status_lbl, gpio_lbl = self._make_status_box(f)

        # ── Live bar (respects invert_var visually) ───────────────
        bar_frame = tk.Frame(f, bg=BG_CARD)
        bar_hdr   = tk.Label(bar_frame, text="Live Value:", bg=BG_CARD, fg=TEXT_DIM,
                              font=(FONT_UI, 9))
        bar = LiveBarGraph(bar_frame, label="Left / Right Axis", width=700, height=32,
                           invert_var=invert_var)

        detect_btn, cancel_btn = self._make_detect_cancel_row(f, ACCENT_BLUE)

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
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text="Detection cancelled.", fg=TEXT_DIM)

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

        _sf, status_lbl, gpio_lbl = self._make_status_box(f)
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
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text="Detection cancelled.", fg=TEXT_DIM)

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
                      "Analog: ADC pins GPIO 26\u201328 (potentiometer \u2014 recommended for full range).",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", pady=(0, 14))

        mode_var = tk.StringVar(value=self.detected.get("whammy_mode", "analog"))
        mode_row = tk.Frame(f, bg=BG_CARD)
        mode_row.pack(anchor="w", pady=(0, 12))
        tk.Label(mode_row, text="Mode:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 10))
        for val, lbl in [("digital", "Digital  (GPIO 0\u201322)"),
                          ("analog",  "Analog   (GPIO 26\u201328, recommended)")]:
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
        _sf, status_lbl, gpio_lbl = self._make_status_box(f)
        if "whammy_pin" in self.detected:
            pin  = self.detected["whammy_pin"]
            mstr = self.detected.get("whammy_mode", "analog")
            status_lbl.config(text=f"\u2713 Previously set to GPIO {pin} ({mstr}).", fg=ACCENT_GREEN)
            gpio_lbl.config(text=f"GPIO {pin}")

        # ── Detect / Cancel buttons ─────────────────────────────────
        detect_btn, cancel_btn = self._make_detect_cancel_row(f, ACCENT_BLUE)

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
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text="Detection cancelled.", fg=TEXT_DIM)

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
            dlg.geometry("335x400")
            dlg.resizable(False, False)
            dlg.transient(f.winfo_toplevel())
            dlg.grab_set()

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
        cnt_sp = ttk.Spinbox(cnt_w, from_=1, to=MAX_LED_COUNT, width=4,
                              textvariable=led_count_var,
                              command=lambda: [_sync(), _rebuild_colors(), _rebuild_map()])
        cnt_sp.pack(fill="both", expand=True)
        cnt_sp.bind("<Return>",   lambda _e: [_sync(), _rebuild_colors(), _rebuild_map()])
        cnt_sp.bind("<FocusOut>", lambda _e: [_sync(), _rebuild_colors(), _rebuild_map()])
        tk.Label(ctrl_row, text=f"(max {MAX_LEDS})", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(0, 8))
        tk.Label(ctrl_row, text="Brightness:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0,3))
        br_w = tk.Frame(ctrl_row, bg=BG_CARD, width=52, height=24)
        br_w.pack(side="left", padx=(0,4)); br_w.pack_propagate(False)
        ttk.Spinbox(br_w, from_=0, to=9, width=4,
                    textvariable=led_brightness_var, command=_sync).pack(fill="both", expand=True)
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
                    textvariable=led_breathe_min_var, command=_sync).pack(fill="both", expand=True)
        tk.Label(breathe_row, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 2))
        bmaxw = tk.Frame(breathe_row, bg=BG_CARD, width=48, height=22)
        bmaxw.pack(side="left", padx=(0, 4)); bmaxw.pack_propagate(False)
        ttk.Spinbox(bmaxw, from_=0, to=9, width=3,
                    textvariable=led_breathe_max_var, command=_sync).pack(fill="both", expand=True)
        tk.Label(breathe_row, text="(0–9)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(3, 0))

        # ── LEFT: wave effect row ─────────────────────────────────────
        wave_row = tk.Frame(left_col, bg=BG_CARD)
        wave_row.pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(wave_row, text="Wave",
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
                            command=_sync).pack(fill="both", expand=True)
                grid_row += 1

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
                      "Analog: ADC pins GPIO 26\u201328 (sensor on ADC pin).\n"
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

        _sf, status_lbl, gpio_lbl = self._make_status_box(f)
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
                self.detected["tilt_pin"] = pin
                self.detected["tilt_mode"] = det_mode
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text=f"\u2713 Detected on GPIO {pin} ({det_mode})!", fg=ACCENT_GREEN)
                gpio_lbl.config(text=f"GPIO {pin}")
                if det_mode == "analog":
                    _show_tilt_cal()
                    self._start_monitor("analog", pin, bar, prefix="tilt")

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
                    f"+{root_win.winfo_rootx()+(root_win.winfo_width()-dlg.winfo_width())//2}"
                    f"+{root_win.winfo_rooty()+(root_win.winfo_height()-dlg.winfo_height())//2}")
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
                            if mode == "analog" and 26 <= pin <= 28:
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
                detect_btn.set_state("normal")
                cancel_btn.set_state("disabled")
                status_lbl.config(text="Detection cancelled.", fg=TEXT_DIM)

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
        if self._current_page > 0:
            self._show_page(self._current_page - 1)

    # Pages whose config key MUST be bound before the user can advance.
    # Index matches PAGE_DEFS order: 0=green … 7=start
    _REQUIRED_PAGES = {0, 1, 2, 3, 4, 5, 6, 7}

    def _next_page(self):
        idx = self._current_page
        ptype, key, name, accent, category = self.PAGE_DEFS[idx]

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
                dw, dh = dlg.winfo_width(), dlg.winfo_height()
                dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
                dlg.grab_set()
                self.root.wait_window(dlg)
                return   # do NOT advance

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
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
        dlg.grab_set()
        self.root.wait_window(dlg)
        if not _confirmed[0]:
            return
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

    # ── Show / Hide ───────────────────────────────────────────────

    def show(self):
        self.root.title("OCC - Easy Configuration")
        self._empty_menu = getattr(self, '_empty_menu', None) or tk.Menu(self.root)
        self.root.config(menu=self._empty_menu)
        self.detected.clear()   # always start fresh — no "Previously set" state
        self._show_page(0)
        self.frame.pack(fill="both", expand=True)

    def hide(self):
        self._stop_scan_and_monitor()
        if getattr(self, '_strum_anim', None):
            self._strum_anim.stop()
            self._strum_anim = None
        self.frame.pack_forget()


class MainMenu:
    """
    Landing screen shown on startup.
    Polls USB every second to detect:
      - RPI-RP2 bootloader drive  → show UF2 flash controls
      - Config-mode serial device → show device name + Configure button
    """

    POLL_MS = 1000

    def __init__(self, root, on_configure):
        self.root = root
        self._on_configure = on_configure   # callback: on_configure(port)
        self._on_flash_screen = None        # set by main() to switch to FlashFirmwareScreen
        self._on_easy_config  = None        # set by main() to switch to EasyConfigScreen
        self._poll_job = None
        self._uf2_files = find_uf2_files()
        self._xinput_count = 0
        self._xinput_dongle_count = 0
        self._backup_in_progress = False  # suppress poll's serial open during worker
        self._check_in_progress = False   # suppress poll rebuilds during update check
        # BOOTSEL debounce: drive must be seen for this many consecutive polls
        # before we switch screens.  POLL_MS=1000ms so 2 polls = ~2s minimum.
        self._bootsel_stable_count = 0
        self._BOOTSEL_STABLE_NEEDED = 2   # polls required (~2s at 1000ms each)
        # Alternatefw one-time popup: shown at most once per session
        self._alternatefw_popup_shown = False
        # GP2040-CE one-time popup: shown at most once per session
        self._gp2040ce_popup_shown = False

        self.frame = tk.Frame(root, bg=BG_MAIN)

        self._build()
        self._poll()

    # ── Layout ────────────────────────────────────────────────────

    def _build(self):
        # ── Title bar ────────────────────────────────────────
        title_bar = tk.Frame(self.frame, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        title_bar.pack(fill="x", padx=0, pady=(0, 16))

        inner_title = tk.Frame(title_bar, bg=BG_CARD)
        inner_title.pack(fill="x", padx=24, pady=16)

        tk.Label(inner_title, text="OCC",
                 bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 18, "bold")).pack(anchor="w")
        tk.Label(inner_title, text="Open Controller Configurator",
                 bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 13)).pack(anchor="w")

        # ── Center content column ─────────────────────────────
        center = tk.Frame(self.frame, bg=BG_MAIN)
        center.pack(expand=True, fill="both", padx=60, pady=0)

        # ── Controller status card ────────────────────────────
        ctrl_card = tk.Frame(center, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        ctrl_card.pack(fill="x", pady=(0, 16), ipady=4)

        ctrl_inner = tk.Frame(ctrl_card, bg=BG_CARD)
        ctrl_inner.pack(fill="x", padx=20, pady=18)

        tk.Label(ctrl_inner, text="CONTROLLER",
                 bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 8))

        self._ctrl_icon  = tk.Label(ctrl_inner, text="○", bg=BG_CARD, fg=TEXT_DIM,
                                    font=(FONT_UI, 14))
        self._ctrl_icon.pack(side="left", padx=(0, 10))

        ctrl_text_col = tk.Frame(ctrl_inner, bg=BG_CARD)
        ctrl_text_col.pack(side="left", fill="x", expand=True)

        self._ctrl_status = tk.Label(ctrl_text_col, text="No device detected",
                                     bg=BG_CARD, fg=TEXT_DIM,
                                     font=(FONT_UI, 10, "bold"), anchor="w")
        self._ctrl_status.pack(anchor="w")

        self._ctrl_detail = tk.Label(ctrl_text_col, text="",
                                     bg=BG_CARD, fg=TEXT_DIM,
                                     font=(FONT_UI, 8), anchor="w")
        self._ctrl_detail.pack(anchor="w")

        # Two-button group on the right of the controller card
        _ctrl_btn_frame = tk.Frame(ctrl_inner, bg=BG_CARD)
        _ctrl_btn_frame.pack(side="right")

        self._easy_cfg_btn = RoundedButton(
            _ctrl_btn_frame, text="Easy Configuration",
            command=self._open_easy_config,
            bg_color=ACCENT_GREEN,
            btn_width=175, btn_height=36)
        self._easy_cfg_btn.pack(side="left", padx=(0, 8))
        self._easy_cfg_btn.set_state("disabled")

        self._cfg_btn = RoundedButton(
            _ctrl_btn_frame, text="Advanced Configuration",
            command=self._open_configurator,
            bg_color=ACCENT_BLUE,
            btn_width=195, btn_height=36)
        self._cfg_btn.pack(side="left")
        self._cfg_btn.set_state("disabled")

        # ── Firmware card ─────────────────────────────────────
        fw_card = tk.Frame(center, bg=BG_CARD,
                           highlightbackground=BORDER, highlightthickness=1)
        fw_card.pack(fill="x", pady=(0, 16), ipady=4)

        fw_inner = tk.Frame(fw_card, bg=BG_CARD)
        fw_inner.pack(fill="x", padx=20, pady=18)

        tk.Label(fw_inner, text="FIRMWARE",
                 bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 8))

        self._fw_icon   = tk.Label(fw_inner, text="○", bg=BG_CARD, fg=TEXT_DIM,
                                   font=(FONT_UI, 14))
        self._fw_icon.pack(side="left", padx=(0, 10))

        fw_text_col = tk.Frame(fw_inner, bg=BG_CARD)
        fw_text_col.pack(side="left", fill="x", expand=True)

        self._fw_status = tk.Label(fw_text_col, text="No Pico in USB mode detected",
                                   bg=BG_CARD, fg=TEXT_DIM,
                                   font=(FONT_UI, 10, "bold"), anchor="w")
        self._fw_status.pack(anchor="w")

        self._fw_detail = tk.Label(fw_text_col,
                                   text="Hold BOOTSEL while plugging in to enter USB mode.",
                                   bg=BG_CARD, fg=TEXT_DIM,
                                   font=(FONT_UI, 8), anchor="w",
                                   wraplength=340, justify="left")
        self._fw_detail.pack(anchor="w")

        # Flash button area — rebuilt dynamically when UF2s are found
        self._fw_btn_frame = tk.Frame(fw_inner, bg=BG_CARD)
        self._fw_btn_frame.pack(side="right")
        self._flash_btn = None

        # ── Reset Pico card ───────────────────────────────────
        rst_card = tk.Frame(center, bg=BG_CARD,
                            highlightbackground=BORDER, highlightthickness=1)
        rst_card.pack(fill="x", pady=(0, 16), ipady=4)

        rst_inner = tk.Frame(rst_card, bg=BG_CARD)
        rst_inner.pack(fill="x", padx=20, pady=18)

        tk.Label(rst_inner, text="Reset Pico",
                 bg=BG_CARD, fg=ACCENT_RED,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(0, 8))

        self._rst_icon = tk.Label(rst_inner, text="○", bg=BG_CARD, fg=TEXT_DIM,
                                  font=(FONT_UI, 14))
        self._rst_icon.pack(side="left", padx=(0, 10))

        rst_text_col = tk.Frame(rst_inner, bg=BG_CARD)
        rst_text_col.pack(side="left", fill="x", expand=True)

        self._rst_status = tk.Label(rst_text_col,
                                    text="No Pico in USB mode detected",
                                    bg=BG_CARD, fg=TEXT_DIM,
                                    font=(FONT_UI, 10, "bold"), anchor="w")
        self._rst_status.pack(anchor="w")

        self._rst_detail = tk.Label(rst_text_col,
                                    text="Hold BOOTSEL while plugging in, then click Factory Reset.",
                                    bg=BG_CARD, fg=TEXT_DIM,
                                    font=(FONT_UI, 8), anchor="w",
                                    wraplength=340, justify="left")
        self._rst_detail.pack(anchor="w")

        self._rst_btn = RoundedButton(rst_inner, text="Factory Reset",
                                      command=self._do_factory_reset,
                                      bg_color=ACCENT_BLUE,
                                      btn_width=160, btn_height=36)
        self._rst_btn.pack(side="right")
        self._rst_btn.set_state("disabled")

        # ── Help hint ─────────────────────────────────────────
        hint_frame = tk.Frame(center, bg=BG_MAIN)
        hint_frame.pack(fill="x", pady=(4, 0))
        tk.Label(hint_frame,
                 text="Firmware is in ALPHA Development. "
                      "Nothing is final, get over it.",
                 bg=BG_MAIN, fg=TEXT_DIM, font=(FONT_UI, 8),
                 justify="left").pack(anchor="w")

    # ── USB polling ───────────────────────────────────────────────

    def _poll(self):
        # If a Pico is in BOOTSEL (USB mass-storage) mode, wait for it to be
        # stable for _BOOTSEL_STABLE_NEEDED consecutive polls before switching
        # screens.  This prevents bouncing when the drive briefly appears and
        # disappears during a factory reset / reboot cycle.
        drive = find_rpi_rp2_drive()
        if drive:
            self._bootsel_stable_count += 1
            if self._bootsel_stable_count >= self._BOOTSEL_STABLE_NEEDED                     and self._on_flash_screen:
                self._bootsel_stable_count = 0
                self._on_flash_screen(drive)
                return   # poll stops here; flash screen has its own poll loop
        else:
            self._bootsel_stable_count = 0   # reset on any miss
        self._refresh_controller_status()
        self._refresh_firmware_status()
        self._refresh_reset_card()
        self._apply_alternatefw_lockout()   # grey out Controller/Firmware if Alternatefw present
        self._check_alternatefw_popup()
        self._apply_gp2040ce_lockout()      # grey out cards if GP2040-CE web config detected
        self._check_gp2040ce_popup()
        self._poll_job = self.root.after(self.POLL_MS, self._poll)

    def _refresh_controller_status(self):
        port = PicoSerial.find_config_port()
        if port:
            # Skip opening the serial port while a background worker owns it —
            # opening it here would race and cause PermissionError in the worker.
            if not self._backup_in_progress:
                try:
                    ps = PicoSerial()
                    ps.connect(port)
                    cfg = ps.get_config()
                    ps.disconnect()
                    name = cfg.get("device_name", "Controller")
                    dtype = cfg.get("device_type", "unknown")
                except Exception:
                    name = "Controller"
                    dtype = "unknown"
            else:
                name = "Controller"
                dtype = "unknown"
            self._ctrl_icon.config(text="●", fg=ACCENT_GREEN)
            self._ctrl_status.config(text=name, fg=ACCENT_GREEN)
            if dtype == "dongle":
                self._ctrl_status.config(
                    text="Dongle detected, no configuration options available.",
                    fg=ACCENT_ORANGE)
                self._ctrl_detail.config(text="", fg=TEXT_DIM)
                self._cfg_btn.set_state("disabled")
                self._easy_cfg_btn.set_state("disabled")
            elif dtype == "guitar_alternate_dongle":
                detail_text = f"Guitar for Dongle  ·  Config mode  ·  {port}"
                self._ctrl_detail.config(text=detail_text, fg=TEXT_DIM)
                self._cfg_btn.set_state("normal")
                self._easy_cfg_btn.set_state("normal")
            elif dtype == "guitar_combined":
                detail_text = f"Guitar (Combined)  ·  Config mode  ·  {port}"
                self._ctrl_detail.config(text=detail_text, fg=TEXT_DIM)
                self._cfg_btn.set_state("normal")
                self._easy_cfg_btn.set_state("normal")
            elif dtype == "drum_kit":
                detail_text = f"Drum Kit  ·  Config mode  ·  {port}  ·  No Easy Configurator for Drums yet"
                self._ctrl_detail.config(text=detail_text, fg=TEXT_DIM)
                self._cfg_btn.set_state("normal")
                self._easy_cfg_btn.set_state("disabled")
            elif dtype == "pedal":
                detail_text = f"Pedal Controller  ·  Config mode  ·  {port}"
                self._ctrl_detail.config(text=detail_text, fg=TEXT_DIM)
                self._cfg_btn.set_state("normal")
                self._easy_cfg_btn.set_state("disabled")
            else:
                detail_text = f"Config mode  ·  {port}"
                self._ctrl_detail.config(text=detail_text, fg=TEXT_DIM)
                self._cfg_btn.set_state("normal")
                self._easy_cfg_btn.set_state("normal")
            self._pending_port = port
            self._xinput_count = 0
            self._xinput_dongle_count = 0
        else:
            # Check for XInput controller
            has_xinput = False
            self._xinput_count = 0
            self._xinput_device_label = "Controller"
            if XINPUT_AVAILABLE:
                try:
                    controllers = xinput_get_connected()
                    SUBTYPE_LABELS = {8: "Drum Kit", 6: "Guitar", 7: "Guitar", 5: "Dongle"}
                    occ_devices = [c for c in controllers if c[1] in OCC_SUBTYPES]
                    # Separate dongles from configurable devices (guitar / drum kit).
                    dongle_devices    = [c for c in occ_devices if c[1] in DONGLE_XINPUT_SUBTYPES]
                    config_devices    = [c for c in occ_devices if c[1] not in DONGLE_XINPUT_SUBTYPES]
                    if config_devices:
                        # One or more configurable controllers present — normal path.
                        has_xinput = True
                        count = len(config_devices)
                        self._xinput_count = count
                        first_label = SUBTYPE_LABELS.get(config_devices[0][1], "Controller")
                        self._xinput_device_label  = first_label
                        self._xinput_first_subtype = config_devices[0][1]
                        self._xinput_dongle_count  = len(dongle_devices)
                        self._ctrl_icon.config(text="●", fg=ACCENT_GREEN)
                        self._ctrl_status.config(
                            text=f"{first_label} detected via XInput  ({count} device{'s' if count > 1 else ''})",
                            fg=ACCENT_GREEN)
                        is_drum = (config_devices[0][1] == 8)
                        detail = (
                            "No Easy Configurator for Drums yet.  "
                            "Click Advanced Configuration to switch to Config Mode."
                            if is_drum else
                            "Click either Configure option to switch to Config Mode."
                        )
                        self._ctrl_detail.config(text=detail, fg=TEXT_DIM)
                        self._cfg_btn.set_state("normal")
                        self._easy_cfg_btn.set_state("disabled" if is_drum else "normal")
                        self._pending_port = None
                    elif dongle_devices:
                        # Only dongle(s) present — show info but no configure option.
                        has_xinput = True
                        count = len(dongle_devices)
                        self._xinput_count = 0          # exclude from config/update flows
                        self._xinput_dongle_count = count
                        self._xinput_device_label  = "Dongle"
                        self._xinput_first_subtype = dongle_devices[0][1]
                        self._ctrl_icon.config(text="●", fg=ACCENT_GREEN)
                        self._ctrl_status.config(
                            text=f"Dongle detected via XInput  ({count} device{'s' if count > 1 else ''})",
                            fg=ACCENT_GREEN)
                        self._ctrl_detail.config(
                            text="Dongle relays a wireless controller — no configuration available here.",
                            fg=TEXT_DIM)
                        self._cfg_btn.set_state("disabled")
                        self._easy_cfg_btn.set_state("disabled")
                        self._pending_port = None
                except Exception:
                    pass

            if not has_xinput:
                self._ctrl_icon.config(text="○", fg=TEXT_DIM)
                self._ctrl_status.config(text="No device detected", fg=TEXT_DIM)
                self._ctrl_detail.config(text="", fg=TEXT_DIM)
                self._cfg_btn.set_state("disabled")
                self._easy_cfg_btn.set_state("disabled")
                self._pending_port = None
                self._xinput_first_subtype = None
                self._xinput_dongle_count  = 0

    def _refresh_firmware_status(self):
        """Update the FIRMWARE card on the main menu each poll cycle."""
        # Don't rebuild while the update-check thread is working — it manages
        # the card's detail text and button state directly.
        if getattr(self, '_check_in_progress', False):
            return
        drive         = find_rpi_rp2_drive()
        config_port   = PicoSerial.find_config_port()
        xinput_count  = getattr(self, '_xinput_count', 0)        # non-dongle OCC devices
        dongle_count  = getattr(self, '_xinput_dongle_count', 0)
        xinput_label  = getattr(self, '_xinput_device_label', 'Controller')
        # _xinput_first_subtype is set by _refresh_controller_status so we know
        # which device type is connected without opening a serial port.
        xinput_subtype = getattr(self, '_xinput_first_subtype', None)

        # Determine which state we're in, in priority order:
        #   1. BOOTSEL drive present
        #   2. Config-mode serial port present
        #   3. XInput configurable OCC device present (guitar / drum)
        #   4. XInput dongle present (no serial config mode — flash via BOOTSEL only)
        #   5. Nothing detected
        if drive:
            new_state = ("bootsel", drive)
        elif config_port and not self._backup_in_progress:
            new_state = ("config", config_port)
        elif xinput_count:
            new_state = ("xinput", xinput_label)
        elif dongle_count:
            new_state = ("dongle_xinput", dongle_count)
        else:
            new_state = ("none", None)

        last = getattr(self, '_last_fw_state', None)
        if new_state == last:
            return   # nothing changed — skip rebuild

        self._last_fw_state = new_state
        state, value = new_state

        # Clear the button area
        for w in self._fw_btn_frame.winfo_children():
            w.destroy()
        self._flash_btn = None

        if state == "bootsel":
            self._fw_icon.config(text="●", fg=ACCENT_GREEN)
            self._fw_status.config(
                text=f"Pico in USB mode  ·  {value}", fg=ACCENT_GREEN)
            self._fw_detail.config(
                text="Ready to flash firmware.", fg=TEXT_DIM)
            self._build_flash_button(value)

        elif state == "config":
            # Try to read device name and type from the connected port
            device_name = "Controller"
            device_type = "unknown"
            try:
                ps = PicoSerial()
                ps.connect(value)
                cfg = ps.get_config()
                ps.disconnect()
                device_name = cfg.get("device_name", device_name)
                device_type = cfg.get("device_type", "unknown")
            except Exception:
                pass

            uf2 = find_uf2_for_device_type(device_type)
            self._fw_icon.config(text="●", fg=ACCENT_GREEN)
            self._fw_status.config(
                text=f"{device_name}  —  Config mode  ·  {value}", fg=ACCENT_GREEN)
            if uf2:
                bundled_date_str = get_bundled_fw_date_str(uf2)
                self._fw_detail.config(
                    text=f"Firmware: {os.path.basename(uf2)}  (built {bundled_date_str})  —  click Check for Updates.",
                    fg=TEXT_DIM)
                # Store for use by the backup worker
                self._pending_fw_uf2  = uf2
                self._pending_fw_type = device_type
                self._pending_fw_via  = "config"
                self._pending_fw_port = value
                check_btn = RoundedButton(
                    self._fw_btn_frame, text="Check for Updates",
                    command=self._check_for_updates,
                    bg_color=ACCENT_BLUE, btn_width=160, btn_height=36)
                check_btn.pack(side="left", padx=(0, 8))
                bk_btn = RoundedButton(
                    self._fw_btn_frame, text="Backup & Update",
                    command=self._backup_and_update_prompt,
                    bg_color="#555560", btn_width=160, btn_height=36)
                bk_btn.pack(side="left")
                bk_btn.set_state("disabled")
                self._backup_update_btn = bk_btn
            else:
                self._fw_detail.config(
                    text="No matching UF2 firmware file found alongside this exe.",
                    fg=ACCENT_ORANGE)

        elif state == "xinput":
            # Infer device type from the XInput subtype we already read
            device_type = XINPUT_SUBTYPE_TO_DEVTYPE.get(xinput_subtype, "unknown")
            uf2 = find_uf2_for_device_type(device_type)
            self._fw_icon.config(text="●", fg=ACCENT_GREEN)
            self._fw_status.config(
                text=f"{value} detected via XInput  ({xinput_count} device{'s' if xinput_count > 1 else ''})",
                fg=ACCENT_GREEN)
            if uf2:
                bundled_date_str = get_bundled_fw_date_str(uf2)
                self._fw_detail.config(
                    text=f"Firmware: {os.path.basename(uf2)}  (built {bundled_date_str})  —  click Check for Updates.",
                    fg=TEXT_DIM)
                self._pending_fw_uf2  = uf2
                self._pending_fw_type = device_type
                self._pending_fw_via  = "xinput"
                self._pending_fw_port = None
                check_btn = RoundedButton(
                    self._fw_btn_frame, text="Check for Updates",
                    command=self._check_for_updates,
                    bg_color=ACCENT_BLUE, btn_width=160, btn_height=36)
                check_btn.pack(side="left", padx=(0, 8))
                bk_btn = RoundedButton(
                    self._fw_btn_frame, text="Backup & Update",
                    command=self._backup_and_update_prompt,
                    bg_color="#555560", btn_width=160, btn_height=36)
                bk_btn.pack(side="left")
                bk_btn.set_state("disabled")
                self._backup_update_btn = bk_btn
            else:
                self._fw_detail.config(
                    text="No matching UF2 firmware file found alongside this exe.",
                    fg=ACCENT_ORANGE)

        elif state == "dongle_xinput":
            # Dongle has no serial config mode — cannot use magic sequence or Backup & Update.
            # The user must manually enter BOOTSEL to flash new dongle firmware.
            count = value
            self._fw_icon.config(text="●", fg=ACCENT_GREEN)
            self._fw_status.config(
                text=f"Dongle detected via XInput  ({count} device{'s' if count > 1 else ''})",
                fg=ACCENT_GREEN)
            self._fw_detail.config(
                text="To flash dongle firmware: hold BOOTSEL while plugging in the dongle.",
                fg=TEXT_DIM)

        else:  # none
            self._fw_icon.config(text="○", fg=TEXT_DIM)
            self._fw_status.config(text="No controller detected", fg=TEXT_DIM)
            self._fw_detail.config(
                text="Connect a controller or hold BOOTSEL while plugging in.",
                fg=TEXT_DIM)


    def _refresh_reset_card(self):
        """Update the Reset Pico card every poll cycle.

        The Factory Reset button is enabled whenever ANY supported device is
        detected — BOOTSEL drive, config-mode serial port, or XInput OCC
        controller. The user never needs to manually enter BOOTSEL first;
        _do_factory_reset() handles getting there automatically.
        """
        drive        = find_rpi_rp2_drive()
        config_port  = PicoSerial.find_config_port()
        xinput_count = getattr(self, '_xinput_count', 0)
        xinput_label = getattr(self, '_xinput_device_label', 'Controller')
        nuke         = find_nuke_uf2()

        if drive:
            self._rst_icon.config(text="●", fg=ACCENT_GREEN)
            self._rst_status.config(
                text=f"Pico in USB mode  ·  {drive}", fg=ACCENT_GREEN)
            if nuke:
                self._rst_detail.config(
                    text="Will use Nuke.uf2 and wipe all storage.",
                    fg=TEXT_DIM)
                self._rst_btn.set_state("normal")
                self._rst_btn._drive = drive
                self._rst_btn._via   = "bootsel"
            else:
                self._rst_detail.config(
                    text="nuke.uf2 not found — place it alongside this exe.",
                    fg=ACCENT_ORANGE)
                self._rst_btn.set_state("disabled")

        elif config_port:
            device_label = getattr(self, '_xinput_device_label', 'Controller')
            # Use the label from the controller card if we already have it,
            # otherwise fall back to a generic name.
            self._rst_icon.config(text="●", fg=ACCENT_GREEN)
            self._rst_status.config(
                text=f"Controller in config mode  ·  {config_port}",
                fg=ACCENT_GREEN)
            if nuke:
                self._rst_detail.config(
                    text="Will send BOOTSEL command, then wipe storage with Nuke.uf2.",
                    fg=TEXT_DIM)
                self._rst_btn.set_state("normal")
                self._rst_btn._drive       = None
                self._rst_btn._via         = "config"
                self._rst_btn._config_port = config_port
            else:
                self._rst_detail.config(
                    text="nuke.uf2 not found — place it alongside this exe.",
                    fg=ACCENT_ORANGE)
                self._rst_btn.set_state("disabled")

        elif xinput_count:
            count = xinput_count
            self._rst_icon.config(text="●", fg=ACCENT_GREEN)
            self._rst_status.config(
                text=f"{xinput_label} detected via XInput  ({count} device{'s' if count > 1 else ''})",
                fg=ACCENT_GREEN)
            if nuke:
                self._rst_detail.config(
                    text="Will send config signal, enter BOOTSEL, then wipe storage with Nuke.uf2.",
                    fg=TEXT_DIM)
                self._rst_btn.set_state("normal")
                self._rst_btn._drive = None
                self._rst_btn._via   = "xinput"
            else:
                self._rst_detail.config(
                    text="nuke.uf2 not found — place it alongside this exe.",
                    fg=ACCENT_ORANGE)
                self._rst_btn.set_state("disabled")

        elif getattr(self, '_xinput_dongle_count', 0):
            # Dongle has no config mode — can't send magic sequence to reach BOOTSEL.
            # The BOOTSEL path (above) already handles a manually-booted dongle.
            dongle_count = self._xinput_dongle_count
            self._rst_icon.config(text="●", fg=ACCENT_GREEN)
            self._rst_status.config(
                text=f"Dongle detected via XInput  ({dongle_count} device{'s' if dongle_count > 1 else ''})",
                fg=ACCENT_GREEN)
            self._rst_detail.config(
                text="Hold BOOTSEL while plugging in the dongle to enable factory reset.",
                fg=TEXT_DIM)
            self._rst_btn.set_state("disabled")

        else:
            self._rst_icon.config(text="○", fg=TEXT_DIM)
            self._rst_status.config(text="No device detected", fg=TEXT_DIM)
            self._rst_detail.config(
                text="Connect a controller or hold BOOTSEL while plugging in.",
                fg=TEXT_DIM)
            self._rst_btn.set_state("disabled")


    # ── Alternatefw detection & de-Alternatefwify ───────────────────

    # ── Alternatefw detection helpers (Windows SetupAPI / WinUSB) ──────

    # ── Alternatefw: cached async detection ──────────────────────────
    # _alternatefw_cached is set by a background thread so the 1-second
    # poll loop never blocks the GUI.  It holds:
    #   None  — not yet scanned / no device
    #   dict  — {"path": <str|None>, "mi": <int>}
    _alternatefw_cached = None
    _alternatefw_scan_running = False

    # ── GP2040-CE: cached async detection ────────────────────────────
    # _gp2040ce_detected is set by a background thread; True = device found.
    _gp2040ce_detected = False
    _gp2040ce_scan_running = False

    @staticmethod
    def _alternatefw_find_device_path():
        """
        Detect a Alternatefw device (VID_1209 / PID_2882) on Windows and
        return {"path": <str|None>, "mi": <int>} or None.

        Uses three strategies in order:
          1. SetupAPI interface enumeration (gives openable path)
          2. PowerShell Get-PnpDevice + device interface path query
          3. SetupAPI DIGCF_ALLCLASSES registry scan
        """
        if sys.platform != "win32":
            return None

        import ctypes, ctypes.wintypes, re, subprocess

        setupapi = ctypes.windll.setupapi
        target = "vid_1209&pid_2882"

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.wintypes.DWORD),
                        ("Data2", ctypes.wintypes.WORD),
                        ("Data3", ctypes.wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
            _fields_ = [("cbSize",             ctypes.wintypes.DWORD),
                        ("InterfaceClassGuid", GUID),
                        ("Flags",              ctypes.wintypes.DWORD),
                        ("Reserved",           ctypes.c_void_p)]

        class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
            _fields_ = [("cbSize",     ctypes.wintypes.DWORD),
                        ("DevicePath", ctypes.c_wchar * 512)]

        class SP_DEVINFO_DATA(ctypes.Structure):
            _fields_ = [("cbSize",    ctypes.wintypes.DWORD),
                        ("ClassGuid", GUID),
                        ("DevInst",   ctypes.wintypes.DWORD),
                        ("Reserved",  ctypes.c_void_p)]

        DIGCF_PRESENT         = 0x00000002
        DIGCF_DEVICEINTERFACE = 0x00000010
        DIGCF_ALLCLASSES      = 0x00000004
        INVALID_HANDLE        = ctypes.c_void_p(-1).value

        guids = [
            # Alternatefw DeviceInterfaceGUID from MS OS 2.0 descriptors
            GUID(0xDF59037D, 0x7C92, 0x4155,
                 (ctypes.c_ubyte * 8)(0xAC, 0x12, 0x7D, 0x70,
                                      0x0A, 0x31, 0x3D, 0x79)),
            # GUID_DEVINTERFACE_USB_DEVICE
            GUID(0xA5DCBF10, 0x6530, 0x11D2,
                 (ctypes.c_ubyte * 8)(0x90, 0x1F, 0x00, 0xC0,
                                      0x4F, 0xB9, 0x51, 0xED)),
            # GUID_DEVINTERFACE_WINUSB
            GUID(0x3FE809AB, 0xFB91, 0x4162,
                 (ctypes.c_ubyte * 8)(0x80, 0x99, 0xFF, 0x89,
                                      0xB2, 0x8A, 0x4E, 0x50)),
        ]

        # ── Strategy 1: SetupAPI device interface enumeration ─────────
        for guid in guids:
            hdi = setupapi.SetupDiGetClassDevsW(
                ctypes.byref(guid), None, None,
                DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
            if hdi == INVALID_HANDLE:
                continue
            try:
                iface = SP_DEVICE_INTERFACE_DATA()
                iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
                i = 0
                while setupapi.SetupDiEnumDeviceInterfaces(
                        hdi, None, ctypes.byref(guid), i,
                        ctypes.byref(iface)):
                    i += 1
                    detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
                    detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                    setupapi.SetupDiGetDeviceInterfaceDetailW(
                        hdi, ctypes.byref(iface),
                        ctypes.byref(detail), ctypes.sizeof(detail),
                        None, None)
                    path = detail.DevicePath
                    if target in path.lower():
                        m = re.search(r'mi_(\d+)', path.lower())
                        mi = int(m.group(1)) if m else 2
                        return {"path": path, "mi": mi}
            finally:
                setupapi.SetupDiDestroyDeviceInfoList(hdi)

        # ── Strategy 2: Direct WinUSB interface lookup ────────────────────────
        # We now know the Alternatefw composite device has 4 interfaces:
        #   MI_00 = unknown, MI_01 = XInput (xusb22),
        #   MI_02 = WinUSB command interface, MI_03 = Xbox Security
        # Scan all MI_XX siblings for the one with Service=WINUSB, then
        # retrieve its device interface path via cfgmgr32 using the
        # USBDevice class GUID {88BAE032-5A81-49F0-BC3D-A4FF138216D6}
        # which is exactly what Windows registers for the WINUSB interface.
        USBDevice_GUID = GUID(0x88BAE032, 0x5A81, 0x49F0,
                              (ctypes.c_ubyte * 8)(0xBC, 0x3D, 0xA4, 0xFF,
                                                   0x13, 0x82, 0x16, 0xD6))
        cfgmgr32 = ctypes.windll.cfgmgr32
        CR_SUCCESS = 0
        for mi_num in range(4):
            try:
                ps_iid = (
                    f"Get-PnpDevice -PresentOnly "
                    f"-InstanceId '*VID_1209&PID_2882&MI_0{mi_num}*' "
                    f"| Where-Object {{ $_.Service -eq 'WINUSB' }} "
                    f"| Select-Object -First 1 -ExpandProperty InstanceId"
                )
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_iid],
                    capture_output=True, text=True, timeout=8,
                    creationflags=0x08000000)
                iid = r.stdout.strip()
                if "VID_1209" not in iid.upper():
                    continue
                # Found the WINUSB interface — get its device interface path
                buf_len = ctypes.wintypes.DWORD(0)
                ret = cfgmgr32.CM_Get_Device_Interface_List_SizeW(
                    ctypes.byref(buf_len),
                    ctypes.byref(USBDevice_GUID),
                    iid, 0)
                if ret == CR_SUCCESS and buf_len.value >= 2:
                    buf = ctypes.create_unicode_buffer(buf_len.value)
                    ret = cfgmgr32.CM_Get_Device_Interface_ListW(
                        ctypes.byref(USBDevice_GUID),
                        iid, buf, buf_len, 0)
                    if ret == CR_SUCCESS and buf.value:
                        return {"path": buf.value, "mi": mi_num,
                                "instance_id": iid}
                # cfgmgr32 failed — try the generic path helper
                path = MainMenu._get_winusb_path_from_instance_id(iid)
                if path:
                    return {"path": path, "mi": mi_num, "instance_id": iid}
                # Path unknown but device exists — still return so UI
                # shows Alternatefw detected and send can try its strategies
                return {"path": None, "mi": mi_num, "instance_id": iid}
            except Exception:
                continue

        # ── Strategy 3: SetupAPI with USBDevice class GUID ────────────
        # Enumerate with exactly the GUID Windows uses for the Alternatefw
        # WinUSB interface — no VID/PID string matching in the path needed.
        USBDevice_GUID2 = GUID(0x88BAE032, 0x5A81, 0x49F0,
                               (ctypes.c_ubyte * 8)(0xBC, 0x3D, 0xA4, 0xFF,
                                                    0x13, 0x82, 0x16, 0xD6))
        hdi2 = setupapi.SetupDiGetClassDevsW(
            ctypes.byref(USBDevice_GUID2), None, None,
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if hdi2 != INVALID_HANDLE:
            try:
                iface2 = SP_DEVICE_INTERFACE_DATA()
                iface2.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
                idx2 = 0
                while setupapi.SetupDiEnumDeviceInterfaces(
                        hdi2, None, ctypes.byref(USBDevice_GUID2),
                        idx2, ctypes.byref(iface2)):
                    idx2 += 1
                    detail2 = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
                    detail2.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                    setupapi.SetupDiGetDeviceInterfaceDetailW(
                        hdi2, ctypes.byref(iface2),
                        ctypes.byref(detail2), ctypes.sizeof(detail2),
                        None, None)
                    path2 = detail2.DevicePath
                    if target in path2.lower():
                        m2 = re.search(r'mi_(\d+)', path2.lower())
                        mi2 = int(m2.group(1)) if m2 else 2
                        return {"path": path2, "mi": mi2}
            finally:
                setupapi.SetupDiDestroyDeviceInfoList(hdi2)

        # ── Strategy 3b: presence-only fallback ───────────────────────
        try:
            result = subprocess.run(
                ["pnputil", "/enum-devices", "/connected",
                 "/ids", "VID_1209&PID_2882"],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000)
            if "VID_1209" in result.stdout.upper():
                return {"path": None, "mi": 2}
        except Exception:
            pass

        return None

    @staticmethod
    def _get_winusb_path_from_instance_id(instance_id):
        """Given a device instance ID like 'USB\\VID_1209&PID_2882&MI_02\\...',
        find the device interface path that can be opened with CreateFile +
        WinUsb_Initialize.

        Strategy:
          1. Ask PowerShell for the device's actual interface class GUID
             via Get-PnpDeviceProperty, then use cfgmgr32 with that GUID.
          2. Try well-known GUIDs with cfgmgr32.
          3. Enumerate ALL device interfaces with SetupAPI DIGCF_ALLCLASSES
             and filter by VID/PID in the path string.
        """
        import ctypes, ctypes.wintypes, re, subprocess

        target = "vid_1209&pid_2882"

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.wintypes.DWORD),
                        ("Data2", ctypes.wintypes.WORD),
                        ("Data3", ctypes.wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        # ── Strategy A: ask PowerShell for the real interface GUID ────
        try:
            # DEVPKEY_Device_ClassGuid gives us the actual device setup class,
            # but we need the *interface* GUID.  The device interface path
            # can be retrieved via CIM/WMI:
            ps_script = (
                f"(Get-PnpDeviceProperty -InstanceId '{instance_id}' "
                f"-KeyName 'DEVPKEY_Device_ClassGuid').Data"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000)
            class_guid_str = result.stdout.strip().strip('{}').lower()
            if class_guid_str and len(class_guid_str) == 36:
                # Parse the GUID string into parts
                parts = class_guid_str.split('-')
                if len(parts) == 5:
                    d1 = int(parts[0], 16)
                    d2 = int(parts[1], 16)
                    d3 = int(parts[2], 16)
                    d4_bytes = bytes.fromhex(parts[3] + parts[4])
                    real_guid = GUID(d1, d2, d3,
                                     (ctypes.c_ubyte * 8)(*d4_bytes))

                    # Now try cfgmgr32 with this GUID
                    path = MainMenu._cfgmgr32_get_interface(
                        instance_id, real_guid)
                    if path:
                        return path
        except Exception:
            pass

        # ── Strategy B: try well-known GUIDs with cfgmgr32 ───────────
        known_guids = [
            # GUID_DEVINTERFACE_USB_DEVICE
            GUID(0xA5DCBF10, 0x6530, 0x11D2,
                 (ctypes.c_ubyte * 8)(0x90, 0x1F, 0x00, 0xC0,
                                      0x4F, 0xB9, 0x51, 0xED)),
            # GUID_DEVINTERFACE_WINUSB
            GUID(0x3FE809AB, 0xFB91, 0x4162,
                 (ctypes.c_ubyte * 8)(0x80, 0x99, 0xFF, 0x89,
                                      0xB2, 0x8A, 0x4E, 0x50)),
            # USBDevice class GUID {88BAE032-5A81-49F0-BC3D-A4FF138216D6}
            GUID(0x88BAE032, 0x5A81, 0x49F0,
                 (ctypes.c_ubyte * 8)(0xBC, 0x3D, 0xA4, 0xFF,
                                      0x13, 0x82, 0x16, 0xD6)),
        ]
        for guid in known_guids:
            path = MainMenu._cfgmgr32_get_interface(instance_id, guid)
            if path:
                return path

        # ── Strategy C: cfgmgr32 NULL-GUID enumeration ────────────────
        # Enumerate ALL device interfaces for this device node using
        # cfgmgr32 with a NULL GUID.
        try:
            cfgmgr32 = ctypes.windll.cfgmgr32
            CR_SUCCESS = 0

            # Locate the device node
            devInst = ctypes.wintypes.DWORD(0)
            ret = cfgmgr32.CM_Locate_DevNodeW(
                ctypes.byref(devInst), instance_id, 0)
            if ret == CR_SUCCESS:
                buf_len = ctypes.wintypes.DWORD(0)
                ret = cfgmgr32.CM_Get_Device_Interface_List_SizeW(
                    ctypes.byref(buf_len),
                    None,  # NULL GUID = all interfaces
                    instance_id,
                    0)  # CM_GET_DEVICE_INTERFACE_LIST_PRESENT
                if ret == CR_SUCCESS and buf_len.value >= 2:
                    buf = ctypes.create_unicode_buffer(buf_len.value)
                    ret = cfgmgr32.CM_Get_Device_Interface_ListW(
                        None,  # NULL GUID
                        instance_id,
                        buf,
                        buf_len,
                        0)
                    if ret == CR_SUCCESS:
                        # buf contains null-separated paths, double-null terminated
                        raw = ctypes.string_at(
                            ctypes.addressof(buf),
                            buf_len.value * 2).decode('utf-16-le', errors='ignore')
                        paths = [p for p in raw.split('\x00') if p]
                        for p in paths:
                            if target in p.lower():
                                return p
        except Exception:
            pass

        return None

    @staticmethod
    def _cfgmgr32_get_interface(instance_id, guid):
        """Try cfgmgr32 CM_Get_Device_Interface_ListW with a specific GUID."""
        try:
            import ctypes, ctypes.wintypes
            cfgmgr32 = ctypes.windll.cfgmgr32
            CR_SUCCESS = 0
            buf_len = ctypes.wintypes.DWORD(0)
            ret = cfgmgr32.CM_Get_Device_Interface_List_SizeW(
                ctypes.byref(buf_len),
                ctypes.byref(guid),
                instance_id,
                0)
            if ret != CR_SUCCESS or buf_len.value < 2:
                return None
            buf = ctypes.create_unicode_buffer(buf_len.value)
            ret = cfgmgr32.CM_Get_Device_Interface_ListW(
                ctypes.byref(guid),
                instance_id,
                buf,
                buf_len,
                0)
            if ret == CR_SUCCESS and buf.value:
                return buf.value
        except Exception:
            pass
        return None

    @staticmethod
    def _alternatefw_send_bootloader_win32(cached_info=None, log=None):
        """Send COMMAND_JUMP_BOOTLOADER with full diagnostic logging."""
        import ctypes, ctypes.wintypes, re

        if log is None:
            log = []
        def L(msg):
            log.append(f"  [send] {msg}")

        kernel32 = ctypes.windll.kernel32

        INVALID_HANDLE        = ctypes.c_void_p(-1).value
        GENERIC_READ          = 0x80000000
        GENERIC_WRITE         = 0x40000000
        FILE_SHARE_READ       = 0x00000001
        FILE_SHARE_WRITE      = 0x00000002
        FILE_FLAG_OVERLAPPED  = 0x40000000
        OPEN_EXISTING         = 3

        class WINUSB_SETUP_PACKET(ctypes.Structure):
            _fields_ = [("RequestType", ctypes.c_ubyte),
                        ("Request",     ctypes.c_ubyte),
                        ("Value",       ctypes.c_ushort),
                        ("Index",       ctypes.c_ushort),
                        ("Length",      ctypes.c_ushort)]

        def _try_winusb_path(path, mi):
            L(f"_try_winusb_path(path={path!r}, mi={mi})")
            h = kernel32.CreateFileW(
                path, GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
            if h == INVALID_HANDLE:
                L(f"  CreateFileW FAILED, LastError={kernel32.GetLastError()}")
                return False
            L(f"  CreateFileW OK, handle=0x{h:X}")
            try:
                winusb = ctypes.windll.winusb
                wh = ctypes.c_void_p()
                ok = winusb.WinUsb_Initialize(h, ctypes.byref(wh))
                if not ok:
                    L(f"  WinUsb_Initialize FAILED, LastError={kernel32.GetLastError()}")
                    return False
                L(f"  WinUsb_Initialize OK")
                try:
                    pkt = WINUSB_SETUP_PACKET(
                        RequestType=_ALTERNATEFW_BM_REQUEST_TYPE,
                        Request=_ALTERNATEFW_CMD_JUMP_BOOTLOADER,
                        Value=0, Index=mi, Length=0)
                    L(f"  ControlTransfer: bmReqType=0x{pkt.RequestType:02X} "
                      f"bReq=0x{pkt.Request:02X} wVal=0x{pkt.Value:04X} "
                      f"wIdx=0x{pkt.Index:04X} wLen={pkt.Length}")
                    transferred = ctypes.c_ulong(0)
                    ret = winusb.WinUsb_ControlTransfer(
                        wh, pkt, None, 0, ctypes.byref(transferred), None)
                    L(f"  ControlTransfer ret={ret}, transferred={transferred.value}, "
                      f"LastError={kernel32.GetLastError()}")
                    return True
                except Exception as exc:
                    L(f"  ControlTransfer exception (device may have reset): {exc}")
                    return True
                finally:
                    try: winusb.WinUsb_Free(wh)
                    except: pass
            except Exception as exc:
                L(f"  WinUsb exception: {exc}")
                return False
            finally:
                kernel32.CloseHandle(h)

        # -- Strategy 1: use cached path / known instance_id
        L(f"Strategy 1: cached_info={cached_info}")
        if cached_info and cached_info.get("path"):
            if _try_winusb_path(cached_info["path"], cached_info.get("mi", 2)):
                L("Strategy 1 SUCCEEDED"); return True

        # -- Strategy 1b: re-fetch path from known instance_id via cfgmgr32
        # If the path in cache is None but we have the instance_id, try to
        # get the path fresh right now using the USBDevice class GUID.
        if cached_info and cached_info.get("instance_id"):
            L(f"Strategy 1b: instance_id re-fetch for {cached_info['instance_id']!r}")
            try:
                import ctypes.wintypes as _wt
                class _GUID1b(ctypes.Structure):
                    _fields_ = [("Data1", _wt.DWORD), ("Data2", _wt.WORD),
                                 ("Data3", _wt.WORD), ("Data4", ctypes.c_ubyte * 8)]
                usbdev_guid = _GUID1b(0x88BAE032, 0x5A81, 0x49F0,
                                      (ctypes.c_ubyte * 8)(0xBC,0x3D,0xA4,0xFF,
                                                           0x13,0x82,0x16,0xD6))
                cfgmgr32 = ctypes.windll.cfgmgr32
                CR_SUCCESS = 0
                iid = cached_info["instance_id"]
                buf_len = _wt.DWORD(0)
                ret = cfgmgr32.CM_Get_Device_Interface_List_SizeW(
                    ctypes.byref(buf_len), ctypes.byref(usbdev_guid), iid, 0)
                L(f"  CM_Size ret={ret}, buf_len={buf_len.value}")
                if ret == CR_SUCCESS and buf_len.value >= 2:
                    buf = ctypes.create_unicode_buffer(buf_len.value)
                    ret = cfgmgr32.CM_Get_Device_Interface_ListW(
                        ctypes.byref(usbdev_guid), iid, buf, buf_len, 0)
                    fresh_path = buf.value if ret == CR_SUCCESS else None
                    L(f"  CM_List ret={ret}, path={fresh_path!r}")
                    if fresh_path:
                        mi = cached_info.get("mi", 2)
                        if _try_winusb_path(fresh_path, mi):
                            L("Strategy 1b SUCCEEDED"); return True
            except Exception as exc:
                L(f"  Strategy 1b exception: {exc}")

        # -- Strategy 2: SetupAPI re-enumerate
        setupapi = ctypes.windll.setupapi
        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.wintypes.DWORD),
                        ("Data2", ctypes.wintypes.WORD),
                        ("Data3", ctypes.wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]
        class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.wintypes.DWORD),
                        ("InterfaceClassGuid", GUID),
                        ("Flags", ctypes.wintypes.DWORD),
                        ("Reserved", ctypes.c_void_p)]
        class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.wintypes.DWORD),
                        ("DevicePath", ctypes.c_wchar * 512)]

        DIGCF_PRESENT = 0x00000002
        DIGCF_DEVICEINTERFACE = 0x00000010
        target = "vid_1209&pid_2882"

        guid_names = ["ALTERNATEFW", "USB_DEVICE", "WINUSB"]
        guids = [
            GUID(0xDF59037D, 0x7C92, 0x4155,
                 (ctypes.c_ubyte * 8)(0xAC,0x12,0x7D,0x70,0x0A,0x31,0x3D,0x79)),
            GUID(0xA5DCBF10, 0x6530, 0x11D2,
                 (ctypes.c_ubyte * 8)(0x90,0x1F,0x00,0xC0,0x4F,0xB9,0x51,0xED)),
            GUID(0x3FE809AB, 0xFB91, 0x4162,
                 (ctypes.c_ubyte * 8)(0x80,0x99,0xFF,0x89,0xB2,0x8A,0x4E,0x50)),
        ]
        for gn, guid in zip(guid_names, guids):
            L(f"Strategy 2: enum {gn}")
            hdi = setupapi.SetupDiGetClassDevsW(
                ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
            if hdi == INVALID_HANDLE: L("  INVALID_HANDLE"); continue
            try:
                iface = SP_DEVICE_INTERFACE_DATA()
                iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
                i = 0
                while setupapi.SetupDiEnumDeviceInterfaces(
                        hdi, None, ctypes.byref(guid), i, ctypes.byref(iface)):
                    i += 1
                    detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
                    detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                    setupapi.SetupDiGetDeviceInterfaceDetailW(
                        hdi, ctypes.byref(iface),
                        ctypes.byref(detail), ctypes.sizeof(detail), None, None)
                    path = detail.DevicePath
                    if target in path.lower():
                        L(f"  Found: {path}")
                        m = re.search(r'mi_(\d+)', path.lower())
                        mi = int(m.group(1)) if m else 2
                        if _try_winusb_path(path, mi):
                            L("Strategy 2 SUCCEEDED"); return True
                L(f"  Enumerated {i}, no Alternatefw match")
            finally:
                setupapi.SetupDiDestroyDeviceInfoList(hdi)

        # -- Strategy 3: PowerShell + registry GUID + cfgmgr32
        L("Strategy 3: PowerShell + registry DeviceInterfaceGUID")
        try:
            import subprocess
            ps = (
                "Get-PnpDevice -PresentOnly -InstanceId '*VID_1209&PID_2882*' "
                "| Where-Object { $_.Service -eq 'WINUSB' } "
                "| Select-Object -First 1 -ExpandProperty InstanceId"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=8,
                creationflags=0x08000000)
            iid = result.stdout.strip()
            L(f"  Instance ID: {iid!r}")
            if "VID_1209" in iid.upper():
                # Query DeviceInterfaceGUID (SINGULAR — this is what
                # Alternatefw's MS OS 2.0 descriptors register)
                ps_guid = (
                    "Get-ItemProperty -Path "
                    f"'HKLM:\\SYSTEM\\CurrentControlSet\\Enum\\{iid}\\Device Parameters' "
                    "-Name 'DeviceInterfaceGUID' -ErrorAction SilentlyContinue "
                    "| Select-Object -ExpandProperty DeviceInterfaceGUID"
                )
                r_guid = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_guid],
                    capture_output=True, text=True, timeout=5,
                    creationflags=0x08000000)
                iface_guid_str = r_guid.stdout.strip().strip('{}').lower()
                L(f"  DeviceInterfaceGUID (singular): {iface_guid_str!r}")

                # Also try plural form as fallback
                if not iface_guid_str or len(iface_guid_str) != 36:
                    ps_guids = (
                        "Get-ItemProperty -Path "
                        f"'HKLM:\\SYSTEM\\CurrentControlSet\\Enum\\{iid}\\Device Parameters' "
                        "-Name 'DeviceInterfaceGUIDs' -ErrorAction SilentlyContinue "
                        "| Select-Object -ExpandProperty DeviceInterfaceGUIDs"
                    )
                    r_guids = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", ps_guids],
                        capture_output=True, text=True, timeout=5,
                        creationflags=0x08000000)
                    iface_guid_str = r_guids.stdout.strip().split('\n')[0].strip().strip('{}').lower()
                    L(f"  DeviceInterfaceGUIDs (plural): {iface_guid_str!r}")

                if iface_guid_str and len(iface_guid_str) == 36:
                    # Parse the GUID and use cfgmgr32 to get the interface path
                    parts = iface_guid_str.split('-')
                    if len(parts) == 5:
                        d1 = int(parts[0], 16)
                        d2 = int(parts[1], 16)
                        d3 = int(parts[2], 16)
                        d4 = bytes.fromhex(parts[3] + parts[4])
                        real_guid = GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))
                        L(f"  Parsed GUID: {{{iface_guid_str}}}")

                        # Use cfgmgr32 with the real GUID
                        cfgmgr32 = ctypes.windll.cfgmgr32
                        CR_SUCCESS = 0
                        buf_len = ctypes.wintypes.DWORD(0)
                        ret = cfgmgr32.CM_Get_Device_Interface_List_SizeW(
                            ctypes.byref(buf_len),
                            ctypes.byref(real_guid),
                            iid, 0)
                        L(f"  CM_Get_Device_Interface_List_SizeW ret={ret}, buf_len={buf_len.value}")
                        if ret == CR_SUCCESS and buf_len.value >= 2:
                            buf = ctypes.create_unicode_buffer(buf_len.value)
                            ret = cfgmgr32.CM_Get_Device_Interface_ListW(
                                ctypes.byref(real_guid),
                                iid, buf, buf_len, 0)
                            L(f"  CM_Get_Device_Interface_ListW ret={ret}")
                            if ret == CR_SUCCESS and buf.value:
                                dev_path = buf.value
                                L(f"  Device path from cfgmgr32: {dev_path!r}")
                                m_obj = re.search(r'mi_(\d+)', iid, re.IGNORECASE)
                                mi = int(m_obj.group(1)) if m_obj else 2
                                if _try_winusb_path(dev_path, mi):
                                    L("Strategy 3 SUCCEEDED via cfgmgr32")
                                    return True

                        # Also try SetupAPI with the discovered GUID
                        L("  Trying SetupAPI with discovered GUID")
                        hdi = setupapi.SetupDiGetClassDevsW(
                            ctypes.byref(real_guid), None, None,
                            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
                        if hdi != INVALID_HANDLE:
                            try:
                                iface = SP_DEVICE_INTERFACE_DATA()
                                iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
                                si = 0
                                while setupapi.SetupDiEnumDeviceInterfaces(
                                        hdi, None, ctypes.byref(real_guid), si,
                                        ctypes.byref(iface)):
                                    si += 1
                                    detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
                                    detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                                    setupapi.SetupDiGetDeviceInterfaceDetailW(
                                        hdi, ctypes.byref(iface),
                                        ctypes.byref(detail), ctypes.sizeof(detail),
                                        None, None)
                                    spath = detail.DevicePath
                                    L(f"  SetupAPI found: {spath}")
                                    if target in spath.lower():
                                        m2 = re.search(r'mi_(\d+)', spath.lower())
                                        smi = int(m2.group(1)) if m2 else 2
                                        if _try_winusb_path(spath, smi):
                                            L("Strategy 3 SUCCEEDED via SetupAPI+real GUID")
                                            return True
                                L(f"  SetupAPI enumerated {si} with real GUID")
                            finally:
                                setupapi.SetupDiDestroyDeviceInfoList(hdi)
                else:
                    L(f"  No valid GUID found in registry")
        except Exception as exc:
            L(f"  Strategy 3 exception: {exc}")

        # -- Strategy 4: HID fallback
        L("Strategy 4: HID fallback")
        HID_GUID = GUID(0x4D1E55B2, 0xF16F, 0x11CF,
                        (ctypes.c_ubyte * 8)(0x88,0xCB,0x00,0x11,0x11,0x00,0x00,0x30))
        hdi = setupapi.SetupDiGetClassDevsW(
            ctypes.byref(HID_GUID), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if hdi == INVALID_HANDLE: L("  HID INVALID_HANDLE"); return False
        try:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            i = 0; matches = 0
            while setupapi.SetupDiEnumDeviceInterfaces(
                    hdi, None, ctypes.byref(HID_GUID), i, ctypes.byref(iface)):
                i += 1
                detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
                detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdi, ctypes.byref(iface),
                    ctypes.byref(detail), ctypes.sizeof(detail), None, None)
                path = detail.DevicePath
                if target not in path.lower(): continue
                matches += 1; L(f"  HID #{matches}: {path}")
                h = kernel32.CreateFileW(
                    path, GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None, OPEN_EXISTING, 0, None)
                if h == INVALID_HANDLE:
                    L(f"    CreateFileW FAILED err={kernel32.GetLastError()}"); continue
                try:
                    buf = (ctypes.c_ubyte * 65)(0)
                    buf[0] = 0x00; buf[1] = _ALTERNATEFW_CMD_JUMP_BOOTLOADER
                    written = ctypes.c_ulong(0)
                    ok = kernel32.WriteFile(h, buf, 65, ctypes.byref(written), None)
                    err = kernel32.GetLastError()
                    L(f"    WriteFile={ok}, written={written.value}, LastError={err}")
                    if ok and written.value == 65:
                        L("  Strategy 4 (HID WriteFile) SUCCEEDED")
                        return True
                    else:
                        L(f"    WriteFile FAILED (ok={ok}, written={written.value}, err={err})")
                        continue
                except Exception as exc:
                    L(f"    WriteFile exc: {exc}"); continue
                finally:
                    kernel32.CloseHandle(h)
            L(f"  Enumerated {i} HID, {matches} matched")
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(hdi)

        # -- Strategy 5: USB device interface (GUID_DEVINTERFACE_USB_DEVICE)
        # Alternatefw on some systems is visible only as a raw USB device,
        # not as a WinUSB or HID interface.  Try opening via the USB device
        # GUID with FILE_FLAG_OVERLAPPED=0 and sending a vendor control
        # request by prepending it as a raw 9-byte buffer (SETUP packet).
        # This is a last-ditch attempt before giving up.
        L("Strategy 5: USB raw device interface")
        USB_DEVICE_GUID = GUID(0xA5DCBF10, 0x6530, 0x11D2,
                               (ctypes.c_ubyte * 8)(0x90,0x1F,0x00,0xC0,
                                                    0x4F,0xB9,0x51,0xED))
        hdi5 = setupapi.SetupDiGetClassDevsW(
            ctypes.byref(USB_DEVICE_GUID), None, None,
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if hdi5 != INVALID_HANDLE:
            try:
                iface5 = SP_DEVICE_INTERFACE_DATA()
                iface5.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
                i5 = 0
                while setupapi.SetupDiEnumDeviceInterfaces(
                        hdi5, None, ctypes.byref(USB_DEVICE_GUID), i5,
                        ctypes.byref(iface5)):
                    i5 += 1
                    detail5 = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
                    detail5.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                    setupapi.SetupDiGetDeviceInterfaceDetailW(
                        hdi5, ctypes.byref(iface5),
                        ctypes.byref(detail5), ctypes.sizeof(detail5),
                        None, None)
                    path5 = detail5.DevicePath
                    if target not in path5.lower():
                        continue
                    L(f"  USB device: {path5}")
                    # Try WinUSB control transfer first
                    if _try_winusb_path(path5, 2):
                        L("Strategy 5 WinUSB SUCCEEDED"); return True
                    # Fallback: raw HID-style write
                    h5 = kernel32.CreateFileW(
                        path5, GENERIC_READ | GENERIC_WRITE,
                        FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, 0, None)
                    if h5 != INVALID_HANDLE:
                        try:
                            buf5 = (ctypes.c_ubyte * 65)(0)
                            buf5[0] = 0x00; buf5[1] = _ALTERNATEFW_CMD_JUMP_BOOTLOADER
                            written5 = ctypes.c_ulong(0)
                            ok5 = kernel32.WriteFile(
                                h5, buf5, 65, ctypes.byref(written5), None)
                            L(f"  S5 WriteFile={ok5}, written={written5.value}, "
                              f"err={kernel32.GetLastError()}")
                            if ok5 and written5.value == 65:
                                L("Strategy 5 raw WriteFile SUCCEEDED"); return True
                        finally:
                            kernel32.CloseHandle(h5)
                L(f"  S5 enumerated {i5}")
            finally:
                setupapi.SetupDiDestroyDeviceInfoList(hdi5)

        L("ALL STRATEGIES FAILED")
        return False

    def _find_alternatefw_device(self):
        """Return True if a Alternatefw device is present, False otherwise."""
        if sys.platform == "win32":
            return self._alternatefw_cached is not None
        try:
            import usb.core
            return usb.core.find(idVendor=ALTERNATEFW_VID, idProduct=ALTERNATEFW_PID) is not None
        except Exception:
            return False

    def _apply_alternatefw_lockout(self):
        """If a Alternatefw device is active, grey out the Controller, Firmware,
        and Reset Pico cards so the user can't accidentally try to configure,
        flash, or factory-reset it as an OCC device.
        Has no effect when no Alternatefw is detected — normal OCC detection still
        runs as usual via _refresh_controller_status / _refresh_firmware_status."""
        if not self._find_alternatefw_device():
            return   # normal OCC device (or nothing) — do not interfere

        # Override Controller card
        self._ctrl_icon.config(text="●", fg=ACCENT_ORANGE)
        self._ctrl_status.config(
            text="Incompatible firmware detected", fg=ACCENT_ORANGE)
        self._ctrl_detail.config(
            text="Use the Firmware Switcher popup to convert this device to OCC firmware.",
            fg=TEXT_DIM)
        self._cfg_btn.set_state("disabled")
        self._easy_cfg_btn.set_state("disabled")
        for w in self._fw_btn_frame.winfo_children():
            w.destroy()
        self._flash_btn = None
        self._fw_icon.config(text="●", fg=ACCENT_ORANGE)
        self._fw_status.config(
            text="Incompatible firmware detected", fg=ACCENT_ORANGE)
        self._fw_detail.config(
            text="Firmware update is unavailable until the device is converted to OCC firmware.",
            fg=TEXT_DIM)
        # Also reset the cached fw state so it rebuilds correctly once the
        # Alternatefw is gone and a normal OCC device is connected instead.
        self._last_fw_state = None

        # Override Reset Pico card — disable the Factory Reset button and show
        # the same incompatible-firmware message so the user knows why it's greyed.
        self._rst_icon.config(text="●", fg=ACCENT_ORANGE)
        self._rst_status.config(
            text="Incompatible firmware detected", fg=ACCENT_ORANGE)
        self._rst_detail.config(
            text="Factory Reset is unavailable until the device is converted to OCC firmware.",
            fg=TEXT_DIM)
        self._rst_btn.set_state("disabled")

    def _check_alternatefw_popup(self):
        """Check for a Alternatefw device and show a one-time popup per session.
        Detection runs in a background thread to avoid blocking the GUI.
        Once the popup has been shown (yes or no), it will not appear again
        until the user restarts OCC Configurator."""

        # Never show the popup more than once per session
        if self._alternatefw_popup_shown:
            return

        # Kick off a background scan if one isn't already running
        if sys.platform == "win32" and not self._alternatefw_scan_running:
            self._alternatefw_scan_running = True
            def _bg_scan():
                try:
                    result = self._alternatefw_find_device_path()
                    self._alternatefw_cached = result
                finally:
                    self._alternatefw_scan_running = False
            threading.Thread(target=_bg_scan, daemon=True).start()

        found = self._find_alternatefw_device()
        if not found:
            return  # Not detected yet — keep polling, popup not shown yet

        # Device found — show the one-time popup (mark shown first to prevent
        # re-entry if the poll fires again before the dialog closes)
        self._alternatefw_popup_shown = True

        answer = _centered_dialog(
            self.root,
            "Firmware Switcher",
            "A device with different firmware was detected.\n\n"
            "Switch from old device firmware to OCC firmware?\n"
			"This popup will not show up again.",
            kind="yesno"
        )

        if answer:
            self._dealternatefwify()


    def _dealternatefwify(self):
        """Send the COMMAND_JUMP_BOOTLOADER USB control transfer to a Alternatefw device."""
        # If the background scan is still running, wait up to 5 seconds for it.
        deadline = time.time() + 5.0
        while self._alternatefw_scan_running and time.time() < deadline:
            time.sleep(0.1)

        if not self._find_alternatefw_device():
            messagebox.showerror(
                "No Alternatefw Found",
                "No Alternatefw device was detected.\n\n"
                "Make sure the device is plugged in.")
            return

        cached = self._alternatefw_cached
        success = False
        log = []
        try:
            if sys.platform == "win32":
                success = self._alternatefw_send_bootloader_win32(cached, log=log)
            else:
                import usb.core, usb.util
                dev = usb.core.find(idVendor=ALTERNATEFW_VID, idProduct=ALTERNATEFW_PID)
                if dev:
                    mi = 2
                    try:
                        cfg = dev.get_active_configuration()
                        for intf in cfg:
                            if (intf.bInterfaceClass == 0xFF and
                                    intf.bInterfaceSubClass not in (0x5D, 0x47)):
                                mi = intf.bInterfaceNumber
                                break
                    except Exception:
                        pass
                    try:
                        dev.ctrl_transfer(
                            _ALTERNATEFW_BM_REQUEST_TYPE,
                            _ALTERNATEFW_CMD_JUMP_BOOTLOADER,
                            0x0000, mi, None)
                    except Exception:
                        pass
                    success = True
        except Exception as exc:
            log.append(f"  [send] Top-level exception: {exc}")

        if success:
            nuke_path = find_nuke_uf2()
            if nuke_path:
                # Update status label so user knows what's happening
                try:
                    self._ctrl_status.config(text="Waiting for RPI-RP2…", fg=ACCENT_ORANGE)
                    self._ctrl_detail.config(
                        text="Will flash nuke.uf2 automatically when drive appears.", fg=TEXT_DIM)
                except Exception:
                    pass

                def _nuke_watcher():
                    """Background thread: flash nuke.uf2 the FIRST time RPI-RP2 appears."""
                    nuke_flashed = False
                    deadline = time.time() + 30.0   # wait up to 30 s

                    while time.time() < deadline and not nuke_flashed:
                        drive = find_rpi_rp2_drive()
                        if drive:
                            nuke_flashed = True   # set flag BEFORE writing so we only try once
                            try:
                                flash_uf2(nuke_path, drive)
                                self.root.after(0, lambda: _centered_dialog(
                                    self.root,
                                    "Firmware Switcher",
                                    "nuke.uf2 flashed successfully!\n\n"
                                    "The Pico will reboot clean.\n\n"   
									"!!WAIT 10 seconds!! for software \n"
									"to catch up. ALPHA BUGGINESS.\n\n"
									"PLEASE power off and power on your controller!\n"
                                    "Unplug and plug in, then flash your OCC firmware normally.",
                                    kind="info"
                                ))
                            except Exception as exc:
                                self.root.after(0, lambda e=exc: _centered_dialog(
                                    self.root,
                                    "Firmware Switcher",
                                    f"RPI-RP2 found but nuke.uf2 flash failed:\n{e}",
                                    kind="error"
                                ))
                        else:
                            time.sleep(0.3)

                    if not nuke_flashed:
                        self.root.after(0, lambda: _centered_dialog(
                            self.root,
                            "Firmware Switcher",
                            "RPI-RP2 drive did not appear within 30 seconds.\n\n"
                            "Try unplugging and re-plugging the Pico while holding BOOTSEL,\n"
                            "then manually copy nuke.uf2 to the drive.",
                            kind="error"
                        ))

                threading.Thread(target=_nuke_watcher, daemon=True).start()

            else:
                # nuke.uf2 not found — fall back to the old informational dialog
                _centered_dialog(
                    self.root,
                    "Firmware Switcher",
                    "BOOTSEL command sent!\n\n"
                    "The device should reappear as an RPI-RP2 drive shortly.\n\n"
                    "Note: nuke.uf2 was not found alongside this exe, so the\n"
                    "automatic flash step was skipped. Place nuke.uf2 next to\n"
                    "the configurator to enable automatic memory wipe.",
                    kind="info"
                )
        else:
            log_text = "\n".join(log[-20:]) if log else "(no diagnostic log)"
            _centered_dialog(
                self.root,
                "Firmware Switcher — BOOTSEL Failed",
                "Failed to send BOOTSEL command to the Alternatefw device.\n\n"
                "This usually means one of:\n"
                "  • The device is driven by the Xbox 360 XInput driver instead\n"
                "    of WinUSB — Windows may not allow direct USB control access.\n"
                "  • The device was unplugged before the command was sent.\n"
                "  • You need to run this configurator as Administrator.\n\n"
                "Manual fix: Hold the BOOTSEL button on the Pico while\n"
                "plugging in the USB cable — it will appear as RPI-RP2.\n\n"
                f"Diagnostic log (last 20 lines):\n{log_text}",
                kind="error"
            )

    # ── GP2040-CE detection & BOOTSEL via HTTP ───────────────────────

    @staticmethod
    def _gp2040ce_find_device():
        """Return True if a GP2040-CE device in web configurator mode is present.

        Detection strategy: HTTP GET to http://192.168.7.1/api/getFirmwareVersion.
        When GP2040-CE is in webconfig mode it always exposes an RNDIS virtual
        Ethernet adapter at 192.168.7.1 and serves this endpoint.  This approach
        works regardless of USB VID/PID (which has varied across GP2040-CE versions
        and board configs) and requires no USB driver access.
        """
        import urllib.request, urllib.error
        try:
            url = f"http://{GP2040CE_WEBCONFIG_IP}/api/getFirmwareVersion"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status < 400
        except urllib.error.HTTPError as e:
            # Device responded — it's there even if the status is unexpected
            return e.code < 500
        except Exception:
            return False

    @staticmethod
    def _gp2040ce_send_bootsel():
        """POST {"bootMode": 2} to the GP2040-CE web configurator reboot API
        to trigger BOOTSEL (UF2 flash) mode.

        bootMode=2 is the BOOTSEL value used by the GP2040-CE web frontend
        (Navigation.jsx).  The webconfig handler maps it to BootMode::USB
        internally before writing to watchdog scratch[5] and resetting.
        Sending the raw enum value (0xf737e4e1) would overflow ArduinoJson's
        signed int read and arrive as 0 (DEFAULT/GAMEPAD), causing a normal
        gamepad reboot instead of BOOTSEL.

        The RNDIS virtual Ethernet interface may need a moment after USB
        enumeration before the HTTP stack is reachable, so we retry for up
        to 5 seconds before giving up.

        Returns True if the request was accepted, False otherwise.
        """
        import urllib.request, json, time
        url  = f"http://{GP2040CE_WEBCONFIG_IP}/api/reboot"
        data = json.dumps({"bootMode": GP2040CE_BOOTMODE_BOOTSEL}).encode("utf-8")
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                req = urllib.request.Request(
                    url, data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status < 400:
                        return True
            except urllib.error.HTTPError as e:
                if e.code < 400:
                    return True
                # 4xx/5xx — device is there but rejected; no point retrying
                return False
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _apply_gp2040ce_lockout(self):
        """If a GP2040-CE device is in web configurator mode, grey out the
        Controller, Firmware, and Reset Pico cards."""
        if not self._gp2040ce_detected:
            return
        self._ctrl_icon.config(text="●", fg=ACCENT_ORANGE)
        self._ctrl_status.config(
            text="GP2040-CE firmware detected", fg=ACCENT_ORANGE)
        self._ctrl_detail.config(
            text="Use the Firmware Switcher popup to convert this device to OCC firmware.",
            fg=TEXT_DIM)
        self._cfg_btn.set_state("disabled")
        self._easy_cfg_btn.set_state("disabled")
        for w in self._fw_btn_frame.winfo_children():
            w.destroy()
        self._flash_btn = None
        self._fw_icon.config(text="●", fg=ACCENT_ORANGE)
        self._fw_status.config(
            text="GP2040-CE firmware detected", fg=ACCENT_ORANGE)
        self._fw_detail.config(
            text="Firmware update is unavailable until the device is converted to OCC firmware.",
            fg=TEXT_DIM)
        self._last_fw_state = None
        self._rst_icon.config(text="●", fg=ACCENT_ORANGE)
        self._rst_status.config(
            text="GP2040-CE firmware detected", fg=ACCENT_ORANGE)
        self._rst_detail.config(
            text="Factory Reset is unavailable until the device is converted to OCC firmware.",
            fg=TEXT_DIM)
        self._rst_btn.set_state("disabled")

    def _check_gp2040ce_popup(self):
        """Check for a GP2040-CE device in web config mode and show a
        one-time popup per session.  Detection runs in a background thread
        to avoid blocking the GUI."""
        if self._gp2040ce_popup_shown:
            return

        if not self._gp2040ce_scan_running and not self._gp2040ce_detected:
            self._gp2040ce_scan_running = True
            def _bg_scan():
                try:
                    found = self._gp2040ce_find_device()
                    if found:
                        self._gp2040ce_detected = True
                finally:
                    self._gp2040ce_scan_running = False
            threading.Thread(target=_bg_scan, daemon=True).start()

        if not self._gp2040ce_detected:
            return

        self._gp2040ce_popup_shown = True

        answer = _centered_dialog(
            self.root,
            "Firmware Switcher",
            "A GP2040-CE device was detected in web configurator mode.\n\n"
            "Switch from GP2040-CE to OCC firmware?\n"
            "This popup will not show up again.",
            kind="yesno"
        )
        if answer:
            self._degp2040ceify()

    def _degp2040ceify(self):
        """Send the BOOTSEL reboot command to a GP2040-CE device via its
        web configurator HTTP API, then watch for RPI-RP2 and flash nuke.uf2."""
        deadline = time.time() + 5.0
        while self._gp2040ce_scan_running and time.time() < deadline:
            time.sleep(0.1)

        if not self._gp2040ce_detected:
            messagebox.showerror(
                "No GP2040-CE Found",
                "No GP2040-CE device was detected.\n\n"
                "Make sure the device is plugged in and in web configurator mode\n"
                "(hold S2 while plugging in, or hold S2+B3+B4 for 5 seconds).")
            return

        try:
            self._ctrl_status.config(text="Sending BOOTSEL command…", fg=ACCENT_ORANGE)
            self._ctrl_detail.config(
                text="Contacting GP2040-CE web API at 192.168.7.1…", fg=TEXT_DIM)
        except Exception:
            pass

        def _worker():
            success = self._gp2040ce_send_bootsel()

            if success:
                nuke_path = find_nuke_uf2()
                if nuke_path:
                    try:
                        self._ctrl_status.config(
                            text="Waiting for RPI-RP2…", fg=ACCENT_ORANGE)
                        self._ctrl_detail.config(
                            text="Will flash nuke.uf2 automatically when drive appears.",
                            fg=TEXT_DIM)
                    except Exception:
                        pass

                    nuke_flashed = False
                    deadline2 = time.time() + 30.0
                    while time.time() < deadline2 and not nuke_flashed:
                        drive = find_rpi_rp2_drive()
                        if drive:
                            nuke_flashed = True
                            try:
                                flash_uf2(nuke_path, drive)
                                self.root.after(0, lambda: _centered_dialog(
                                    self.root,
                                    "Firmware Switcher",
                                    "nuke.uf2 flashed successfully!\n\n"
                                    "The Pico will reboot clean.\n\n"
                                    "!!WAIT 10 seconds!! for software \n"
                                    "to catch up. ALPHA BUGGINESS.\n\n"
                                    "PLEASE power off and power on your controller!\n"
                                    "Unplug and plug in, then flash your OCC firmware normally.",
                                    kind="info"
                                ))
                            except Exception as exc:
                                self.root.after(0, lambda e=exc: _centered_dialog(
                                    self.root,
                                    "Firmware Switcher",
                                    f"RPI-RP2 found but nuke.uf2 flash failed:\n{e}",
                                    kind="error"
                                ))
                        else:
                            time.sleep(0.3)

                    if not nuke_flashed:
                        self.root.after(0, lambda: _centered_dialog(
                            self.root,
                            "Firmware Switcher",
                            "RPI-RP2 drive did not appear within 30 seconds.\n\n"
                            "Try unplugging and re-plugging the Pico while holding BOOTSEL,\n"
                            "then manually copy nuke.uf2 to the drive.",
                            kind="error"
                        ))
                else:
                    self.root.after(0, lambda: _centered_dialog(
                        self.root,
                        "Firmware Switcher",
                        "BOOTSEL command sent!\n\n"
                        "The device should reappear as an RPI-RP2 drive shortly.\n\n"
                        "Note: nuke.uf2 was not found alongside this exe, so the\n"
                        "automatic flash step was skipped. Place nuke.uf2 next to\n"
                        "the configurator to enable automatic memory wipe.",
                        kind="info"
                    ))
            else:
                self.root.after(0, lambda: _centered_dialog(
                    self.root,
                    "Firmware Switcher — BOOTSEL Failed",
                    "Failed to reach the GP2040-CE web configurator API.\n\n"
                    "Make sure the device is still in web configurator mode:\n"
                    "  • Hold S2 while plugging in, OR\n"
                    "  • Hold S2+B3+B4 for 5 seconds while plugged in\n\n"
                    "The web interface at http://192.168.7.1 must be reachable.\n\n"
                    "Manual fix: Hold the BOOTSEL button on the Pico while\n"
                    "plugging in the USB cable — it will appear as RPI-RP2.",
                    kind="error"
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _build_flash_button(self, drive):
        # Clear old button(s)
        for w in self._fw_btn_frame.winfo_children():
            w.destroy()
        self._flash_btn = None

        # Route to the dedicated FlashFirmwareScreen instead of flashing inline.
        # Show a "loading" label briefly, then switch screens.
        lbl = tk.Label(self._fw_btn_frame,
                       text="Loading firmware menu, please wait…",
                       bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8))
        lbl.pack()

        def _go():
            if self._on_flash_screen:
                self._on_flash_screen(drive)

        # Small delay so the label is visible before the screen switches
        self._fw_btn_frame.after(400, _go)

    # ── Check for Updates ─────────────────────────────────────────
    def _check_for_updates(self):
        """Query the controller's firmware date and compare with the bundled UF2.

        If the controller is in XInput mode, switch it to config mode first,
        read the date, then reboot it back to play mode.  If already in config
        mode, just read and leave it alone.

        On completion, if the bundled firmware is newer the Backup & Update
        button is enabled.  Otherwise a 'firmware is up to date' message is shown.
        """
        uf2_path    = getattr(self, '_pending_fw_uf2',  None)
        via         = getattr(self, '_pending_fw_via',  'xinput')
        cfg_port    = getattr(self, '_pending_fw_port', None)

        if not uf2_path:
            messagebox.showerror("Check for Updates",
                "No matching firmware UF2 file found.\n"
                "Place the .uf2 file alongside this exe and try again.")
            return

        bundled_date = get_bundled_fw_date(uf2_path)
        bundled_date_str = get_bundled_fw_date_str(uf2_path)

        self._check_in_progress = True

        def worker():
            pico = PicoSerial()
            switched_from_xinput = False

            def ui_detail(msg, color=TEXT_DIM):
                self.root.after(0, lambda: self._fw_detail.config(text=msg, fg=color))

            def finish():
                """Clear the in-progress flag and allow polling to resume."""
                self._check_in_progress = False
                self._last_fw_state = None   # force card refresh on next poll

            try:
                # ── Get into config mode if needed ──
                if via == 'xinput':
                    if not XINPUT_AVAILABLE:
                        self.root.after(0, lambda: messagebox.showerror(
                            "Check for Updates",
                            "XInput is not available on this system."))
                        finish()
                        return
                    controllers = xinput_get_connected() if XINPUT_AVAILABLE else []
                    occ_devices = [c for c in controllers if c[1] in OCC_SUBTYPES]
                    if not occ_devices:
                        self.root.after(0, lambda: messagebox.showwarning(
                            "Check for Updates",
                            "No supported OCC controller detected."))
                        finish()
                        return
                    slot = occ_devices[0][0]

                    ui_detail("Switching controller to config mode to read firmware date…")
                    try:
                        for left, right in MAGIC_STEPS:
                            result = xinput_send_vibration(slot, left, right)
                            if result != ERROR_SUCCESS:
                                ui_detail("Failed to send config signal.", ACCENT_RED)
                                finish()
                                return
                            time.sleep(0.08)
                        xinput_send_vibration(slot, 0, 0)
                    except Exception as exc:
                        ui_detail(f"Error sending XInput signal: {exc}", ACCENT_RED)
                        finish()
                        return

                    port = None
                    deadline = time.time() + 8.0
                    while time.time() < deadline:
                        port = PicoSerial.find_config_port()
                        if port:
                            time.sleep(0.5)
                            break
                        time.sleep(0.3)
                    if not port:
                        ui_detail("Timeout: controller did not enter config mode.", ACCENT_RED)
                        finish()
                        return
                    switched_from_xinput = True
                else:
                    port = cfg_port or PicoSerial.find_config_port()
                    if not port:
                        ui_detail("Config mode port not found.", ACCENT_RED)
                        finish()
                        return

                # ── Read firmware date ──
                ui_detail("Reading firmware date from controller…")
                pico.connect(port)
                for _ in range(3):
                    if pico.ping():
                        break
                    time.sleep(0.3)

                fw_date_str = pico.get_fw_date()
                fw_date = parse_fw_date(fw_date_str) if fw_date_str else None

                # ── Reboot back to play mode if we came from XInput ──
                if switched_from_xinput:
                    ui_detail("Returning controller to play mode…")
                    try:
                        pico.reboot()
                    except Exception:
                        pass
                else:
                    pico.disconnect()

                # ── Compare dates and update UI ──
                if fw_date_str is None:
                    # Firmware too old to have GET_FW_DATE — treat as needing update
                    def _enable():
                        _centered_dialog(
                            self.root, "Check for Updates",
                            f"Controller firmware does not report a build date (older build).\n\n"
                            f"Bundled firmware: {bundled_date_str}\n\n"
                            f"An update is recommended.",
                            kind="info")
                        self._fw_detail.config(
                            text=f"Update recommended  —  Bundled: {bundled_date_str}",
                            fg=ACCENT_ORANGE)
                        btn = getattr(self, '_backup_update_btn', None)
                        if btn:
                            btn.set_state("normal")
                            btn.update_color(ACCENT_BLUE)
                    self.root.after(0, _enable)
                    finish()
                    return

                needs_update = False
                if bundled_date and fw_date:
                    needs_update = bundled_date > fw_date
                elif bundled_date and not fw_date:
                    needs_update = True  # can't parse controller date — offer update

                if needs_update:
                    def _enable():
                        _centered_dialog(
                            self.root, "Update Available",
                            f"A firmware update is available.\n\n"
                            f"Controller firmware:  {fw_date_str}\n"
                            f"Bundled firmware:     {bundled_date_str}\n\n"
                            f"Click  Backup & Update  to install.",
                            kind="info")
                        self._fw_detail.config(
                            text=f"Update available!  Controller: {fw_date_str}  →  Bundled: {bundled_date_str}",
                            fg=ACCENT_ORANGE)
                        btn = getattr(self, '_backup_update_btn', None)
                        if btn:
                            btn.set_state("normal")
                            btn.update_color(ACCENT_BLUE)
                    self.root.after(0, _enable)
                else:
                    def _up_to_date():
                        _centered_dialog(
                            self.root, "Firmware Up to Date",
                            f"Your controller firmware is up to date.\n\n"
                            f"Controller firmware:  {fw_date_str}\n"
                            f"Bundled firmware:     {bundled_date_str}",
                            kind="info")
                        self._fw_detail.config(
                            text=f"Firmware is up to date  —  {fw_date_str}",
                            fg=ACCENT_GREEN)
                    self.root.after(0, _up_to_date)

                finish()

            except Exception as exc:
                ui_detail(f"Error checking firmware date: {exc}", ACCENT_RED)
                try:
                    pico.disconnect()
                except Exception:
                    pass
                finish()

        threading.Thread(target=worker, daemon=True).start()

    def _backup_and_update_prompt(self):
        """
        Device-type-aware Backup & Update flow:
          - Identifies the connected device type (guitar or drum)
          - Picks the matching UF2 automatically
          - Backs up config, flashes firmware, restores config
          - Works whether device is in XInput mode or already in config mode

        Entry point state is read from _pending_fw_* attrs set by
        _refresh_firmware_status().
        """
        uf2_path   = getattr(self, '_pending_fw_uf2',  None)
        via        = getattr(self, '_pending_fw_via',  'xinput')   # 'xinput' or 'config'
        cfg_port   = getattr(self, '_pending_fw_port', None)
        device_type = getattr(self, '_pending_fw_type', 'unknown')

        if not uf2_path:
            messagebox.showerror("Backup & Update",
                "No matching firmware UF2 file found.\n"
                "Place the .uf2 file alongside this exe and try again.")
            return

        if via == 'xinput' and not XINPUT_AVAILABLE:
            messagebox.showerror("Backup & Update",
                "XInput is not available on this system.\n"
                "Cannot send the config-mode signal to the controller.")
            return

        if via == 'xinput':
            controllers = xinput_get_connected() if XINPUT_AVAILABLE else []
            occ_devices = [c for c in controllers if c[1] in OCC_SUBTYPES]
            if not occ_devices:
                messagebox.showwarning("Backup & Update",
                    "No supported OCC controller detected.\n"
                    "Make sure the controller is plugged in and try again.")
                return
            slot = occ_devices[0][0]
        else:
            slot = None

        # ── Progress dialog ───────────────────────────────────────
        dlg = tk.Toplevel(self.root)
        dlg.title("Backup & Update")
        dlg.configure(bg=BG_CARD)
        dlg.geometry("460x220")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        dlg_frame = tk.Frame(dlg, bg=BG_CARD)
        dlg_frame.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(dlg_frame, text="Backup & Update",
                 bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", pady=(0, 12))

        status_var = tk.StringVar(value="Starting…")
        status_lbl = tk.Label(dlg_frame, textvariable=status_var,
                              bg=BG_CARD, fg=ACCENT_BLUE,
                              font=(FONT_UI, 9), anchor="w", wraplength=410, justify="left")
        status_lbl.pack(anchor="w", pady=(0, 8))

        detail_var = tk.StringVar(value="")
        detail_lbl = tk.Label(dlg_frame, textvariable=detail_var,
                              bg=BG_CARD, fg=TEXT_DIM,
                              font=(FONT_UI, 8), anchor="w", wraplength=410, justify="left")
        detail_lbl.pack(anchor="w")

        close_btn = RoundedButton(dlg_frame, text="Close",
                                  command=dlg.destroy,
                                  bg_color="#555560", btn_width=100, btn_height=30,
                                  btn_font=(FONT_UI, 8, "bold"))
        close_btn.pack(side="right", pady=(16, 0))
        close_btn.set_state("disabled")

        def set_status(msg, detail="", color=ACCENT_BLUE):
            status_var.set(msg)
            detail_var.set(detail)
            status_lbl.config(fg=color)
            dlg.update_idletasks()

        def worker():
            backup_path = None
            pico = PicoSerial()

            def fail(msg, detail=""):
                def _f():
                    self._backup_in_progress = False
                    self._last_fw_state = None  # force firmware card refresh
                    set_status(msg, detail, ACCENT_RED)
                    close_btn.set_state("normal")
                    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
                self.root.after(0, _f)

            def succeed(msg, detail=""):
                def _f():
                    self._backup_in_progress = False
                    self._last_fw_state = None
                    set_status(msg, detail, ACCENT_GREEN)
                    close_btn.set_state("normal")
                    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
                self.root.after(0, _f)

            self._backup_in_progress = True

            # ── Step 1: get into config mode ──────────────────
            if via == 'config':
                # Already there — use the port we already know
                port = cfg_port or PicoSerial.find_config_port()
                if not port:
                    fail("Config mode device not found.",
                         "The controller may have disconnected.")
                    return
                self.root.after(0, lambda p=port: set_status(
                    "Step 1 / 6  —  Connecting to controller…",
                    f"Config mode port: {p}"))
            else:
                # XInput mode — send magic sequence
                total_steps = 7
                self.root.after(0, lambda: set_status(
                    f"Step 1 / {total_steps}  —  Switching controller to config mode…",
                    f"Sending signal to XInput slot {slot + 1}"))
                try:
                    for left, right in MAGIC_STEPS:
                        result = xinput_send_vibration(slot, left, right)
                        if result != ERROR_SUCCESS:
                            fail("Failed to send config signal.",
                                 "Make sure no game is using the controller.")
                            return
                        time.sleep(0.08)
                    xinput_send_vibration(slot, 0, 0)
                except Exception as exc:
                    fail("Error sending XInput signal.", str(exc))
                    return

                self.root.after(0, lambda: set_status(
                    f"Step 2 / {total_steps}  —  Waiting for config mode port…",
                    "Controller rebooting into serial config mode (up to 8s)"))
                port = None
                deadline = time.time() + 8.0
                while time.time() < deadline:
                    port = PicoSerial.find_config_port()
                    if port:
                        time.sleep(0.5)
                        break
                    time.sleep(0.3)
                if not port:
                    fail("Timeout: controller did not enter config mode.",
                         "Close any games or apps that may be holding the XInput device.")
                    return

            # Set step labels based on entry path
            step_read   = "Step 2 / 6" if via == 'config' else "Step 3 / 7"
            step_boot   = "Step 3 / 6" if via == 'config' else "Step 4 / 7"
            step_wait   = "Step 4 / 6" if via == 'config' else "Step 5 / 7"
            step_flash  = "Step 4 / 6" if via == 'config' else "Step 5 / 7"
            step_reboot = "Step 5 / 6" if via == 'config' else "Step 6 / 7"
            step_restore= "Step 6 / 6" if via == 'config' else "Step 7 / 7"

            # ── Step: connect + read + backup config ──────────
            self.root.after(0, lambda: set_status(
                f"{step_read}  —  Reading configuration…",
                f"Connected on {port}"))
            try:
                pico.connect(port)
                for _ in range(3):
                    if pico.ping():
                        break
                    time.sleep(0.3)
                else:
                    pico.disconnect()
                    fail("Controller connected but did not respond to PING.")
                    return
                raw_cfg = pico.get_config()
            except Exception as exc:
                pico.disconnect()
                fail("Failed to read configuration.", str(exc))
                return

            try:
                ts = time.strftime("%Y%m%d_%H%M%S")
                exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                backup_path = os.path.join(exe_dir, f"occ_backup_{ts}.json")
                with open(backup_path, "w", encoding="utf-8") as f:
                    json.dump(raw_cfg, f, indent=2)
                self.root.after(0, lambda p=backup_path: set_status(
                    f"{step_read}  —  Configuration backed up.",
                    f"Saved to: {p}"))
            except Exception as exc:
                pico.disconnect()
                fail("Could not save backup JSON.", str(exc))
                return

            # ── Step: BOOTSEL ─────────────────────────────────
            self.root.after(0, lambda: set_status(
                f"{step_boot}  —  Rebooting to USB mass storage…",
                "Sending BOOTSEL command"))
            try:
                pico.bootsel()
            except Exception:
                pass   # disconnect is expected here

            # ── Step: wait for RPI-RP2 drive ──────────────────
            self.root.after(0, lambda: set_status(
                f"{step_wait}  —  Waiting for Pico USB drive…",
                "Looking for RPI-RP2 mass storage drive (up to 15s)"))
            drive = None
            deadline = time.time() + 15.0
            while time.time() < deadline:
                drive = find_rpi_rp2_drive()
                if drive:
                    break
                time.sleep(0.5)
            if not drive:
                fail("Pico USB drive did not appear.",
                     f"Backup saved to:\n{backup_path}\n\n"
                     "You can import it manually after re-flashing firmware.")
                return

            # ── Step: flash UF2 ───────────────────────────────
            self.root.after(0, lambda: set_status(
                f"{step_flash}  —  Flashing firmware…",
                f"Writing {os.path.basename(uf2_path)} to {drive}"))
            try:
                def _flash_status(msg):
                    self.root.after(0, lambda m=msg: set_status(
                        f"{step_flash}  —  {m}",
                        f"Writing {os.path.basename(uf2_path)}…"))
                flash_uf2_with_reboot(uf2_path, drive, status_cb=_flash_status)
            except Exception as exc:
                fail("Firmware flash failed.",
                     f"Backup saved to:\n{backup_path}\n\nError: {exc}")
                return

            # ── Step: wait for controller to reappear ─────────
            self.root.after(0, lambda: set_status(
                f"{step_reboot}  —  Waiting for controller to reboot…",
                "Pico is flashing and rebooting (up to 30s)"))
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if not find_rpi_rp2_drive():
                    break
                time.sleep(0.5)

            # For config-mode entry we can wait directly for the CDC port to
            # reappear instead of going through XInput — faster and more reliable.
            if via == 'config':
                port2 = None
                deadline = time.time() + 20.0
                while time.time() < deadline:
                    port2 = PicoSerial.find_config_port()
                    if port2:
                        time.sleep(0.5)
                        break
                    time.sleep(0.3)
                if not port2:
                    fail("Controller did not return to play mode.",
                         f"Firmware was flashed successfully.\n"
                         f"Backup saved to:\n{backup_path}\n\n"
                         "Import it manually via Configure Controller → Import Configuration.")
                    return
            else:
                # XInput path — wait for controller to reappear via XInput
                xinput_slot2 = None
                deadline = time.time() + 30.0
                while time.time() < deadline:
                    try:
                        connected = xinput_get_connected()
                        if any(c[0] == slot for c in connected):
                            xinput_slot2 = slot
                            break
                        occ_back = [c for c in connected if c[1] in OCC_SUBTYPES]
                        if occ_back:
                            xinput_slot2 = occ_back[0][0]
                            break
                        if connected:
                            xinput_slot2 = connected[0][0]
                    except Exception:
                        pass
                    time.sleep(0.75)

                if xinput_slot2 is not None:
                    self.root.after(0, lambda: set_status(
                        f"{step_reboot}  —  Controller detected, waiting for enumeration…",
                        "Giving Windows time to fully recognise the controller"))
                    time.sleep(3.0)

                if xinput_slot2 is None:
                    fail("Controller did not reappear as an XInput device.",
                         f"Firmware was flashed successfully.\n"
                         f"Backup saved to:\n{backup_path}\n\n"
                         "Import it manually via Configure Controller → Import Configuration.")
                    return

                # Send magic sequence to switch back to config mode
                self.root.after(0, lambda: set_status(
                    f"{step_restore}  —  Restoring configuration…",
                    "Switching back to config mode to restore settings"))
                try:
                    for left, right in MAGIC_STEPS:
                        xinput_send_vibration(xinput_slot2, left, right)
                        time.sleep(0.08)
                    xinput_send_vibration(xinput_slot2, 0, 0)
                except Exception as exc:
                    fail("Could not send config signal after update.",
                         f"Firmware was flashed successfully.\n"
                         f"Backup saved to:\n{backup_path}\n\n"
                         f"Import it manually. Error: {exc}")
                    return

                port2 = None
                deadline = time.time() + 10.0
                while time.time() < deadline:
                    port2 = PicoSerial.find_config_port()
                    if port2:
                        time.sleep(0.5)
                        break
                    time.sleep(0.3)
                if not port2:
                    fail("Timeout waiting for config mode after update.",
                         f"Firmware was flashed successfully.\n"
                         f"Backup saved to:\n{backup_path}\n\n"
                         "Import it manually via Configure Controller → Import Configuration.")
                    return

            # ── Step: restore config ───────────────────────────
            self.root.after(0, lambda: set_status(
                f"{step_restore}  —  Restoring configuration…",
                f"Pushing settings to {port2}"))
            try:
                pico2 = PicoSerial()
                connect_deadline = time.time() + 15.0
                connected2 = False
                last_exc = None
                while time.time() < connect_deadline:
                    try:
                        pico2.connect(port2)
                        connected2 = True
                        break
                    except PermissionError:
                        self.root.after(0, lambda: set_status(
                            f"{step_restore}  —  Restoring configuration…",
                            "Waiting for Windows to release the COM port…"))
                        time.sleep(1.5)
                    except Exception as exc:
                        last_exc = exc
                        break

                if not connected2:
                    fail("Could not open COM port after update.",
                         f"Firmware was flashed successfully.\n"
                         f"Backup saved to:\n{backup_path}\n\n"
                         f"Import it manually. Error: {last_exc or 'Access denied'}")
                    return

                for _ in range(3):
                    if pico2.ping():
                        break
                    time.sleep(0.3)
                else:
                    pico2.disconnect()
                    fail("Controller did not respond after update.",
                         f"Backup saved to:\n{backup_path}\n\n"
                         "Import it manually via Configure Controller → Import Configuration.")
                    return

                _SKIP_KEYS = {"device_type", "led_colors_raw", "led_map_raw"}
                for key, val in raw_cfg.items():
                    if key in _SKIP_KEYS:
                        continue
                    if key.startswith("led_") and key.endswith("_raw"):
                        continue
                    try:
                        pico2.set_value(key, str(val))
                    except Exception:
                        pass

                if "led_colors_raw" in raw_cfg:
                    colors = raw_cfg["led_colors_raw"].split(",")
                    for i, c in enumerate(colors):
                        c = c.strip()
                        if len(c) == 6 and i < MAX_LEDS:
                            try:
                                pico2.set_value(f"led_color_{i}", c.upper())
                            except Exception:
                                pass

                if "led_map_raw" in raw_cfg:
                    for pair in raw_cfg["led_map_raw"].split(","):
                        pair = pair.strip()
                        if "=" not in pair:
                            continue
                        name_part, rest = pair.split("=", 1)
                        name_part = name_part.strip()
                        if name_part in LED_INPUT_NAMES and ":" in rest:
                            idx = LED_INPUT_NAMES.index(name_part)
                            hex_mask, bright = rest.split(":", 1)
                            try:
                                pico2.set_value(f"led_map_{idx}", hex_mask.strip())
                                pico2.set_value(f"led_active_{idx}", bright.strip())
                            except Exception:
                                pass

                pico2.save()
                pico2.reboot()
                pico2.disconnect()
            except Exception as exc:
                fail("Failed to restore configuration.",
                     f"Firmware was flashed successfully.\n"
                     f"Backup saved to:\n{backup_path}\n\n"
                     f"Import it manually. Error: {exc}")
                return

            succeed(
                "✓  Backup & Update complete!",
                f"Firmware flashed and settings restored.\n"
                f"Backup saved to: {backup_path}")

        threading.Thread(target=worker, daemon=True).start()


    def _clear_flash_button(self):
        for w in self._fw_btn_frame.winfo_children():
            w.destroy()
        self._flash_btn = None

    def _do_flash(self, uf2_path, drive):
        if not uf2_path or not drive:
            return
        try:
            flash_uf2_with_reboot(uf2_path, drive)
            messagebox.showinfo("Success",
                f"Firmware flashed successfully!\n\n"
                f"File: {os.path.basename(uf2_path)}\n"
                f"Drive: {drive}\n\n"
                "The Pico will reboot. Once it appears as a controller,\n"
                "click Configure Controller.")
        except Exception as exc:
            messagebox.showerror("Flash Error", str(exc))

    def _browse_and_flash(self, drive):
        path = filedialog.askopenfilename(
            title="Select UF2 Firmware File",
            filetypes=[("UF2 Firmware", "*.uf2"), ("All Files", "*.*")])
        if path:
            self._do_flash(path, drive)

    def _do_factory_reset(self):
        """Factory reset — works from BOOTSEL drive, config mode, or XInput mode."""
        nuke_path = find_nuke_uf2()
        if not nuke_path:
            messagebox.showerror("Factory Reset",
                "nuke.uf2 not found.\n"
                "Place nuke.uf2 alongside this exe and try again.")
            return

        via = getattr(self._rst_btn, '_via', 'bootsel')

        # ── Already in BOOTSEL: flash directly ───────────────────────────
        if via == "bootsel":
            drive = getattr(self._rst_btn, '_drive', None)
            if not drive:
                messagebox.showerror("Factory Reset",
                    "No Pico in USB mode detected.\n"
                    "Hold BOOTSEL while plugging in, then try again.")
                return
            confirmed = messagebox.askyesno(
                "Factory Reset — Are you sure?",
                "This will COMPLETELY ERASE all firmware and settings on the Pico.\n\n"
                f"File: {os.path.basename(nuke_path)}\n"
                f"Drive: {drive}\n\n"
                "The Pico will be wiped. You will need to re-flash firmware afterwards.\n\n"
                "Continue?",
                icon="warning")
            if not confirmed:
                return
            try:
                flash_uf2(nuke_path, drive)
                messagebox.showinfo("Factory Reset Complete",
                    "Pico flash has been wiped.\n\n"
                    "To use the controller again, plug the Pico back in\n"
                    "(hold BOOTSEL) and flash the guitar firmware.")
            except Exception as exc:
                messagebox.showerror("Factory Reset Error", str(exc))
            return

        # ── Config mode or XInput: need to get to BOOTSEL first ──────────
        if via == "config":
            source_desc = "config mode serial connection"
        else:
            source_desc = "XInput"

        confirmed = messagebox.askyesno(
            "Factory Reset — Are you sure?",
            "This will COMPLETELY ERASE all firmware and settings on the Pico.\n\n"
            f"File: {os.path.basename(nuke_path)}\n"
            f"Detected via: {source_desc}\n\n"
            "The configurator will switch the Pico to BOOTSEL mode automatically,\n"
            "then flash nuke.uf2 to wipe the device.\n\n"
            "You will need to re-flash firmware afterwards.\n\n"
            "Continue?",
            icon="warning")
        if not confirmed:
            return

        self._rst_btn.set_state("disabled")
        self._do_factory_reset_via_device(via, nuke_path)

    def _do_factory_reset_via_device(self, via, nuke_path):
        """Run the BOOTSEL → nuke flow in a background thread with a progress dialog."""

        dlg = tk.Toplevel(self.root)
        dlg.title("Factory Reset")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.update_idletasks()
        dw, dh = 460, 220
        px = self.root.winfo_rootx() + (self.root.winfo_width()  - dw) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - dh) // 2
        dlg.geometry(f"{dw}x{dh}+{px}+{py}")
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # block close during operation

        dlg_frame = tk.Frame(dlg, bg=BG_CARD)
        dlg_frame.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(dlg_frame, text="Factory Reset",
                 bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", pady=(0, 12))

        status_var = tk.StringVar(value="Starting…")
        status_lbl = tk.Label(dlg_frame, textvariable=status_var,
                              bg=BG_CARD, fg=ACCENT_BLUE,
                              font=(FONT_UI, 9), anchor="w", wraplength=410, justify="left")
        status_lbl.pack(anchor="w", pady=(0, 8))

        detail_var = tk.StringVar(value="")
        tk.Label(dlg_frame, textvariable=detail_var,
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), anchor="w", wraplength=410, justify="left").pack(anchor="w")

        close_btn = RoundedButton(dlg_frame, text="Close",
                                  command=dlg.destroy,
                                  bg_color="#555560", btn_width=100, btn_height=30,
                                  btn_font=(FONT_UI, 8, "bold"))
        close_btn.pack(side="right", pady=(16, 0))
        close_btn.set_state("disabled")

        def set_status(msg, detail="", color=ACCENT_BLUE):
            status_var.set(msg)
            detail_var.set(detail)
            status_lbl.config(fg=color)
            dlg.update_idletasks()

        def finish_ok():
            set_status("✓  Factory reset complete!", "", ACCENT_GREEN)
            close_btn.set_state("normal")
            dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
            dlg.after(2000, lambda: dlg.destroy() if dlg.winfo_exists() else None)

        def finish_err(msg, detail=""):
            set_status(msg, detail, ACCENT_RED)
            close_btn.set_state("normal")
            dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

        def worker():
            pico = PicoSerial()

            # ── Step 1: ensure we are in config mode ─────────────────────
            if via == "xinput":
                # ── XInput path: send magic signal → wait for config port ──
                self.root.after(0, lambda: set_status(
                    "Step 1 / 3  —  Switching to config mode…",
                    "Sending magic XInput signal"))
                try:
                    controllers = xinput_get_connected() if XINPUT_AVAILABLE else []
                    occ_devices = [c for c in controllers if c[1] in OCC_SUBTYPES]
                    if not occ_devices:
                        self.root.after(0, lambda: finish_err(
                            "No supported OCC controller detected.",
                            "Make sure the controller is plugged in and not in use by a game."))
                        return
                    slot = occ_devices[0][0]
                    for left, right in MAGIC_STEPS:
                        xinput_send_vibration(slot, left, right)
                        time.sleep(0.08)
                    xinput_send_vibration(slot, 0, 0)
                except Exception as exc:
                    self.root.after(0, lambda: finish_err("XInput signal failed.", str(exc)))
                    return

                self.root.after(0, lambda: set_status(
                    "Step 1 / 3  —  Waiting for config mode port…",
                    "Up to 10 seconds"))
                port = None
                deadline = time.time() + 10.0
                while time.time() < deadline:
                    port = PicoSerial.find_config_port()
                    if port:
                        time.sleep(0.5)
                        break
                    time.sleep(0.3)
                if not port:
                    self.root.after(0, lambda: finish_err(
                        "Timeout: controller did not enter config mode.",
                        "Close any games using the controller and try again."))
                    return

            else:
                # ── Config mode path: re-verify port is still present ──────
                port = getattr(self._rst_btn, '_config_port', None)
                # Always re-scan in case the cached port is stale
                live_port = PicoSerial.find_config_port()
                if live_port:
                    port = live_port
                if not port:
                    # Device may have switched to XInput mode between poll and click —
                    # try XInput path if available
                    if XINPUT_AVAILABLE:
                        controllers = []
                        try:
                            controllers = xinput_get_connected()
                        except Exception:
                            pass
                        occ_devices = [c for c in controllers if c[1] in OCC_SUBTYPES]
                        if occ_devices:
                            self.root.after(0, lambda: set_status(
                                "Step 1 / 2  —  Switching to config mode…",
                                "Controller found via XInput — sending config signal"))
                            try:
                                slot = occ_devices[0][0]
                                for left, right in MAGIC_STEPS:
                                    xinput_send_vibration(slot, left, right)
                                    time.sleep(0.08)
                                xinput_send_vibration(slot, 0, 0)
                            except Exception as exc:
                                self.root.after(0, lambda: finish_err(
                                    "Could not reach controller.", str(exc)))
                                return
                            deadline = time.time() + 10.0
                            while time.time() < deadline:
                                port = PicoSerial.find_config_port()
                                if port:
                                    time.sleep(0.5)
                                    break
                                time.sleep(0.3)

                if not port:
                    self.root.after(0, lambda: finish_err(
                        "Controller not found.",
                        "The controller may have disconnected. Replug and try again."))
                    return

            # ── Step 2: connect and send BOOTSEL ─────────────────────────
            step_n = "Step 2 / 3" if via == "xinput" else "Step 1 / 2"
            self.root.after(0, lambda: set_status(
                f"{step_n}  —  Sending BOOTSEL command…",
                f"Connected on {port}"))
            try:
                pico.connect(port)
                # Ping up to 3× to confirm the port is live before issuing BOOTSEL
                ping_ok = False
                for _ in range(3):
                    if pico.ping():
                        ping_ok = True
                        break
                    time.sleep(0.3)
                if not ping_ok:
                    pico.disconnect()
                    self.root.after(0, lambda: finish_err(
                        "Controller did not respond on the config port.",
                        "The device may be in the wrong mode. Replug and try again."))
                    return
                pico.bootsel()
            except Exception as exc:
                self.root.after(0, lambda e=exc: finish_err(
                    "Failed to send BOOTSEL command.", str(e)))
                return

            # ── Step 3: wait for RPI-RP2 drive with explicit timeout msg ──
            step_n = "Step 3 / 3" if via == "xinput" else "Step 2 / 2"
            BOOTSEL_TIMEOUT = 15.0
            self.root.after(0, lambda: set_status(
                f"{step_n}  —  Waiting for Pico USB drive…",
                f"Looking for RPI-RP2 drive (up to {int(BOOTSEL_TIMEOUT)}s)"))
            drive = None
            deadline = time.time() + BOOTSEL_TIMEOUT
            while time.time() < deadline:
                drive = find_rpi_rp2_drive()
                if drive:
                    break
                time.sleep(0.5)

            if not drive:
                self.root.after(0, lambda: finish_err(
                    "Sending BOOTSEL timed out, please try again.",
                    "The Pico did not appear as a USB drive within "
                    f"{int(BOOTSEL_TIMEOUT)} seconds.\n"
                    "Try unplugging and re-plugging while holding the BOOTSEL button, "
                    "then run Factory Reset again."))
                return

            # ── Flash nuke.uf2 ────────────────────────────────────────────
            self.root.after(0, lambda: set_status(
                f"{step_n}  —  Flashing nuke.uf2…",
                f"Writing to {drive}"))
            try:
                flash_uf2(nuke_path, drive)
            except Exception as exc:
                self.root.after(0, lambda e=exc: finish_err("Flash failed.", str(e)))
                return

            self.root.after(0, finish_ok)

        threading.Thread(target=worker, daemon=True).start()

    # ── Navigation ────────────────────────────────────────────────

    def _open_easy_config(self):
        if self._poll_job:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        if self._on_easy_config:
            self._on_easy_config(getattr(self, "_pending_port", None))

    def _open_configurator(self):
        if self._poll_job:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self._on_configure(getattr(self, "_pending_port", None))

    def show(self):
        self.root.title("OCC - Open Controller Configurator")
        # Clear any configurator menu bar left over from App / DrumApp
        self._empty_menu = getattr(self, '_empty_menu', None) or tk.Menu(self.root)
        self.root.config(menu=self._empty_menu)
        self._bootsel_stable_count = 0   # always start fresh debounce on show
        # Reset Alternatefw detection so incompatible-firmware check reruns
        # fresh every time the main menu is shown (e.g. after firmware switch).
        self._alternatefw_popup_shown = False
        self._alternatefw_cached = None
        # Same reset for GP2040-CE detection.
        self._gp2040ce_popup_shown = False
        self._gp2040ce_detected = False
        # Clear cached device state so cards always re-render from scratch on show.
        # Without this, returning from a config screen leaves stale "Config mode"
        # state visible for up to POLL_MS even after the device has rebooted to XInput.
        self._last_fw_state = None
        self._pending_port = None
        self.frame.pack(fill="both", expand=True)
        # First poll fires quickly so cards are up-to-date immediately on show,
        # then settles into the normal POLL_MS cadence.
        self._poll_job = self.root.after(50, self._poll)

    def hide(self):
        if self._poll_job:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self.frame.pack_forget()


class App:
    def __init__(self, root, on_back=None):
        self.root = root
        self._on_back = on_back
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

        self._loaded_device_type = "guitar_alternate"  # updated by _load_config

        # LED state
        self.led_enabled = tk.BooleanVar(value=False)
        self.led_count = tk.IntVar(value=0)
        self.led_base_brightness = tk.IntVar(value=5)
        self.led_colors = [tk.StringVar(value="FFFFFF") for _ in range(MAX_LEDS)]
        self.led_maps = [tk.IntVar(value=0) for _ in range(LED_INPUT_COUNT)]
        self.led_active_br = [tk.IntVar(value=7) for _ in range(LED_INPUT_COUNT)]
        self.led_reactive = tk.BooleanVar(value=True)
        self._led_maps_backup = [0] * LED_INPUT_COUNT

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

        # Device name
        self.device_name = tk.StringVar(value="Guitar Controller")

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

        # Widget tracking
        self._all_widgets = []
        self._det_btns = {}
        self._pin_combos = {}
        self._sp_combos = {}
        self._row_w = {}
        self._led_widgets = []
        self._led_color_btns = []
        self._led_map_cbs = {}
        self._led_map_widgets = []
        self._i2c_widgets = []  # I2C-specific widgets (show/hide with mode)

        self._apply_theme()
        self._build_menubar()
        self._build_ui()
        self._set_controls_enabled(False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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
        self.root.title("OCC - Guitar Configurator")
        self.root.config(menu=self._menu_bar)
        self._outer_frame.pack(fill="both", expand=True)
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.update_idletasks()

    def hide(self):
        """Hide the configurator UI (return to main menu)."""
        self._scroll_canvas.unbind_all("<MouseWheel>")
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
        fw.add_command(label="Switch Dongle/BT Default", command=self._switch_wireless_default)
        fw.add_separator()
        fw.add_command(label="Serial Debug Console", command=self._show_serial_debug)
        fw.add_separator()
        fw.add_command(label="Exit", command=self._on_close)
        mb.add_cascade(label="Advanced", menu=fw)

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

        self.status_label = tk.Label(conn_card, text="   Not connected",
                                      bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9))
        self.status_label.pack(anchor="w", padx=14, pady=(8, 6))

        # Scrollable area
        scroll_outer = tk.Frame(outer, bg=BG_MAIN)
        scroll_outer.pack(fill="both", expand=True)

        self._scroll_canvas = tk.Canvas(scroll_outer, bg=BG_MAIN, highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(scroll_outer, orient="vertical",
                                        command=self._on_yview)
        self.content = tk.Frame(self._scroll_canvas, bg=BG_MAIN)
        self._scroll_enabled   = True   # tracks whether scrollbar is currently shown
        self._scroll_animating = False  # True while mousewheel ease animation is running
        self._scroll_target    = None   # target yview fraction for the animation

        self.content.bind("<Configure>", self._on_content_configure)
        self._content_window = self._scroll_canvas.create_window(
            (0, 0), window=self.content, anchor="nw")
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")
        self._scroll_canvas.bind("<Configure>", self._on_canvas_resize)

        # Sections
        self._make_device_name_section()
        self._make_section("FRET BUTTONS", ["frets"])
        self._make_section("STRUM", ["strum"])
        self._make_section("D-PAD / DIRECTIONAL STICK", ["dpad"],
                           hint="For controllers with a navigation stick. "
                                "D-Pad Up/Down share XInput bits with Strum Up/Down.")
        self._make_section("NAVIGATION", ["nav", "nav2"])

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

        self._make_joystick_section()

        self._make_led_section()
        self._make_debounce_section()

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
        delta = int(-1 * (event.delta / 120))
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

        for key, name, sec in BUTTON_DEFS:
            if sec in sections:
                self._make_button_row(inner, key, name)

    def _make_button_row(self, parent, key, name):
        self.pin_vars[key] = tk.IntVar(value=-1)
        self.enable_vars[key] = tk.BooleanVar(value=True)

        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=3)

        # enable_vars still used internally for save/load; no visible checkbox
        self.enable_vars[key].set(True)

        fc = FRET_COLORS.get(key)
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
            # Spacer so non-fret rows align with fret rows (icon width + padx)
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

        # ── Sensitivity (min/max ADC range) — only shown for analog/I2C modes ──
        # (sens_min_var / sens_max_var already set above)

        # StringVars mirror the IntVars and drive the Entry boxes
        min_str = tk.StringVar(value=str(sens_min_var.get()))
        max_str = tk.StringVar(value=str(sens_max_var.get()))

        # Keep entry boxes in sync whenever the IntVar is set externally (e.g. load config)
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

        # Typing in the entry box updates the IntVar and moves the slider
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

        invert_var = self.tilt_invert if prefix == "tilt" else self.whammy_invert
        invert_cb = ttk.Checkbutton(sens_frame, text="Invert", variable=invert_var)
        invert_cb.pack(side="left", padx=(10, 0))
        self._all_widgets.append(invert_cb)

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
        _card, inner = self._make_collapsible_card(
            "LED STRIP  (APA102 / SK9822 / Dotstar)", collapsed=True)
        tk.Label(inner, text="Wire SCK (CI) → GP6, MOSI (DI) → GP3. Chain LEDs in series. "
                 "VCC → VBUS (5V), GND → GND. "
                 "WARNING: GP3 and GP6 are reserved for LEDs when enabled — "
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
        cnt_sp = ttk.Spinbox(cnt_wrap, from_=1, to=MAX_LEDS, width=4,
                              textvariable=self.led_count,
                              command=self._on_led_count_change)
        cnt_sp.pack(fill="both", expand=True)
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
        br_sp = ttk.Spinbox(br_wrap, from_=0, to=9, width=4,
                             textvariable=self.led_base_brightness)
        br_sp.pack(fill="both", expand=True)
        self._all_widgets.append(br_sp)
        self._led_widgets.append(br_sp)
        tk.Label(top, text="(0=off, 9=max)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(4, 0))

        self._led_colors_frame = tk.Frame(inner, bg=BG_CARD)
        self._led_colors_frame.pack(fill="x", pady=(6, 0))
        self._led_widgets.append(self._led_colors_frame)
        self._rebuild_led_color_grid()

        # ── LED Loop row ───────────────────────────────────────────────────
        loop_row = tk.Frame(inner, bg=BG_CARD)
        loop_row.pack(fill="x", pady=(6, 2))
        self._led_widgets.append(loop_row)

        loop_cb = ttk.Checkbutton(loop_row, text="Enable LED Color Loop",
                                   variable=self.led_loop_enabled)
        loop_cb.pack(side="left", padx=(0, 12))
        self._all_widgets.append(loop_cb)

        tk.Label(loop_row, text="From LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        loop_start_sp = ttk.Spinbox(loop_row, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_loop_start)
        loop_start_sp.pack(side="left", padx=(0, 8))
        self._all_widgets.append(loop_start_sp)

        tk.Label(loop_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        loop_end_sp = ttk.Spinbox(loop_row, from_=1, to=MAX_LEDS, width=4,
                                   textvariable=self.led_loop_end)
        loop_end_sp.pack(side="left", padx=(0, 10))
        self._all_widgets.append(loop_end_sp)

        tk.Label(loop_row,
                 text="Rotates colors through these LEDs once/sec with smooth crossfade",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")
        # ── end LED Loop row ───────────────────────────────────────────────

        # ── LED Breathe row ────────────────────────────────────────────────
        breathe_row = tk.Frame(inner, bg=BG_CARD)
        breathe_row.pack(fill="x", pady=(4, 2))
        self._led_widgets.append(breathe_row)

        breathe_cb = ttk.Checkbutton(breathe_row, text="Enable LED Breathe",
                                     variable=self.led_breathe_enabled,
                                     command=lambda: self.led_wave_enabled.set(False) if self.led_breathe_enabled.get() else None)
        breathe_cb.pack(side="left", padx=(0, 12))
        self._all_widgets.append(breathe_cb)

        tk.Label(breathe_row, text="From LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_start_sp = ttk.Spinbox(breathe_row, from_=1, to=MAX_LEDS, width=4,
                                       textvariable=self.led_breathe_start)
        breathe_start_sp.pack(side="left", padx=(0, 8))
        self._all_widgets.append(breathe_start_sp)

        tk.Label(breathe_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_end_sp = ttk.Spinbox(breathe_row, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_breathe_end)
        breathe_end_sp.pack(side="left", padx=(0, 12))
        self._all_widgets.append(breathe_end_sp)

        tk.Label(breathe_row, text="Min:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_min_sp = ttk.Spinbox(breathe_row, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_min)
        breathe_min_sp.pack(side="left", padx=(0, 8))
        self._all_widgets.append(breathe_min_sp)

        tk.Label(breathe_row, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_max_sp = ttk.Spinbox(breathe_row, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_max)
        breathe_max_sp.pack(side="left", padx=(0, 10))
        self._all_widgets.append(breathe_max_sp)

        tk.Label(breathe_row, text="Fades brightness slowly between Min and Max (3 s cycle)",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")
        # ── end LED Breathe row ────────────────────────────────────────────

        # ── LED Wave row ───────────────────────────────────────────────────
        wave_row = tk.Frame(inner, bg=BG_CARD)
        wave_row.pack(fill="x", pady=(4, 2))
        self._led_widgets.append(wave_row)

        wave_cb = ttk.Checkbutton(wave_row, text="Enable LED Wave",
                                  variable=self.led_wave_enabled,
                                  command=lambda: self.led_breathe_enabled.set(False) if self.led_wave_enabled.get() else None)
        wave_cb.pack(side="left", padx=(0, 12))
        self._all_widgets.append(wave_cb)

        tk.Label(wave_row, text="Origin LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        wave_origin_sp = ttk.Spinbox(wave_row, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_wave_origin)
        wave_origin_sp.pack(side="left", padx=(0, 10))
        self._all_widgets.append(wave_origin_sp)

        tk.Label(wave_row,
                 text="On keypress: brightness pulse radiates outward from origin LED",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")
        # ── end LED Wave row ───────────────────────────────────────────────

        sep = tk.Frame(inner, bg=BORDER, height=1)
        sep.pack(fill="x", pady=(8, 4))
        self._led_widgets.append(sep)

        react_row = tk.Frame(inner, bg=BG_CARD)
        react_row.pack(fill="x", pady=(0, 4))
        self._led_widgets.append(react_row)

        react_cb = ttk.Checkbutton(react_row, text="Reactive LEDs on keypress",
                                    variable=self.led_reactive,
                                    command=self._on_reactive_toggle)
        react_cb.pack(side="left", padx=(0, 10))
        self._all_widgets.append(react_cb)

        react_hint = tk.Label(react_row,
                              text="When enabled, LEDs light up when their mapped input is pressed",
                              bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7))
        react_hint.pack(side="left")

        lbl = tk.Label(inner, text="Input → LED Mapping  (select which LEDs respond to each input)",
                       bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8, "bold"), anchor="w")
        lbl.pack(fill="x", pady=(0, 4))
        self._led_widgets.append(lbl)
        self._led_map_widgets.append(lbl)

        self._led_map_frame = tk.Frame(inner, bg=BG_CARD)
        self._led_map_frame.pack(fill="x")
        self._led_widgets.append(self._led_map_frame)
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
        if show:
            self._led_colors_frame.pack(fill="x", pady=(6, 0))
            self._rebuild_led_color_grid()
            self._rebuild_led_map_grid()
            self._on_reactive_toggle()

    def _on_reactive_toggle(self):
        reactive = self.led_reactive.get()
        if not reactive:
            for i in range(LED_INPUT_COUNT):
                cur = self.led_maps[i].get()
                if cur != 0:
                    self._led_maps_backup[i] = cur
                self.led_maps[i].set(0)
        else:
            for i in range(LED_INPUT_COUNT):
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
        dlg.geometry("335x370")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

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

        for inp_idx in range(LED_INPUT_COUNT):
            grid_row = inp_idx + 1

            name_frame = tk.Frame(grid, bg=BG_CARD)
            name_frame.grid(row=grid_row, column=0, sticky="w", padx=(0, 2), pady=1)

            color = FRET_COLORS.get(LED_INPUT_NAMES[inp_idx])
            if color:
                dot = tk.Canvas(name_frame, width=10, height=10, bg=BG_CARD,
                                highlightthickness=0, bd=0)
                dot.create_oval(1, 1, 9, 9, fill=color, outline=color)
                dot.pack(side="left", padx=(0, 2))

            tk.Label(name_frame, text=LED_INPUT_LABELS[inp_idx], bg=BG_CARD, fg=TEXT,
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
                                 textvariable=self.led_active_br[inp_idx])
            br_sp.grid(row=grid_row, column=bright_col, padx=(6, 0), pady=1)
            self._all_widgets.append(br_sp)

        self._schedule_pin_label_refresh()

    def _get_input_pin_text(self, inp_idx):
        name = LED_INPUT_NAMES[inp_idx]
        if inp_idx < len(BUTTON_DEFS):
            key = BUTTON_DEFS[inp_idx][0]
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
            i2c_row.pack_forget()
            if not pin_row.winfo_ismapped():
                pin_row.pack(fill="x", pady=2)
            combo["values"] = [ANALOG_PIN_LABELS[p] for p in ANALOG_PINS]
            cur = pin_var.get()
            if cur in ANALOG_PINS:
                combo.current(ANALOG_PINS.index(cur))
            else:
                combo.current(0)
                pin_var.set(ANALOG_PINS[0])
            if sens_frame:
                if not sens_frame.winfo_ismapped():
                    sens_frame.pack(fill="x", pady=(4, 0))
        else:
            # Digital mode — show pin row with digital pins, hide I2C row and sens
            i2c_row.pack_forget()
            if not pin_row.winfo_ismapped():
                pin_row.pack(fill="x", pady=2)
            combo["values"] = [DIGITAL_PIN_LABELS[p] for p in DIGITAL_PINS]
            cur = pin_var.get()
            if cur in DIGITAL_PINS:
                combo.current(DIGITAL_PINS.index(cur))
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
            pin_var.set(ANALOG_PINS[idx])
        else:
            pin_var.set(DIGITAL_PINS[idx])

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

    def _set_sens_from_live(self, prefix, which, var, str_var, other_var):
        """Snap min or max to the current live monitor reading."""
        data = self._sp_combos.get(prefix)
        if not data:
            return
        bar = data[10]
        live_val = bar._value
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
            messagebox.showinfo("XInput",
                "XInput not available on this system.\n"
                "Use 'Manual COM Port' if the controller is already in config mode.")

    def _connect_xinput(self):
        self._set_status("   Scanning for XInput controllers...", ACCENT_BLUE)
        controllers = xinput_get_connected()
        if not controllers:
            self._set_status("   No controllers found", ACCENT_RED)
            messagebox.showwarning("No Controllers",
                "No XInput controllers detected.\n"
                "Make sure the guitar is plugged in and recognized by Windows.")
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
        dlg.geometry("340x240")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

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
        dlg.geometry("440x170")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

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
        SUPPORTED_TYPES = {"guitar_alternate", "guitar_alternate_dongle", "guitar_combined"}
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

        # Update status text to indicate variant
        port_name = self.pico.ser.port if self.pico.connected else "?"
        if is_dongle_guitar:
            self._set_status(f"   Guitar for Dongle  —  {port_name}", ACCENT_GREEN)
        elif is_combined:
            self._set_status(f"   Guitar (Combined Wireless)  —  {port_name}", ACCENT_GREEN)

        for key, _, _ in BUTTON_DEFS:
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
                if name in LED_INPUT_NAMES:
                    idx = LED_INPUT_NAMES.index(name)
                    if ":" in rest:
                        hex_mask, bright = rest.split(":", 1)
                        self.led_maps[idx].set(int(hex_mask, 16))
                        self.led_active_br[idx].set(self._brightness_from_hw(int(bright)))

        any_mapped = any(self.led_maps[i].get() != 0 for i in range(LED_INPUT_COUNT))
        self.led_reactive.set(any_mapped)
        for i in range(LED_INPUT_COUNT):
            self._led_maps_backup[i] = self.led_maps[i].get()

        self._on_led_toggle()
        if self.led_enabled.get():
            self._rebuild_led_color_grid()
            if self.led_reactive.get():
                self._rebuild_led_map_grid()

    def _push_all_values(self):
        for key, _, _ in BUTTON_DEFS:
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
            name = "Guitar Controller"
        try:
            self.pico.set_value("device_name", name[:20])
        except ValueError:
            pass

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

        for i in range(LED_INPUT_COUNT):
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

    # ── Export / Import Configuration ──────────────────────────────

    def _export_config(self):
        """Snapshot all current UI values to a JSON file."""
        device_name = self.device_name.get().strip() or "Guitar Controller"
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
        for key, _, _ in BUTTON_DEFS:
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
        cfg["device_name"] = self.device_name.get().strip() or "Guitar Controller"

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
        cfg["led_maps"]   = [self.led_maps[i].get() for i in range(LED_INPUT_COUNT)]
        cfg["led_active_br"] = [
            self._brightness_to_hw(self.led_active_br[i].get())
            for i in range(LED_INPUT_COUNT)
        ]

        # sync_pin and wireless_default_mode have no dedicated UI widgets —
        # pull from the cached GET_CONFIG response so they round-trip correctly.
        raw = getattr(self, "_last_raw_cfg", {})
        cfg["sync_pin"]              = int(raw.get("sync_pin", 15))
        cfg["wireless_default_mode"] = int(raw.get("wireless_default_mode", 0))

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            messagebox.showinfo("Export Successful",
                                f"Configuration exported to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

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
            # Buttons
            for key, _, _ in BUTTON_DEFS:
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
            if "led_colors" in cfg:
                for i, c in enumerate(cfg["led_colors"]):
                    if i < MAX_LEDS and len(str(c)) == 6:
                        self.led_colors[i].set(str(c).upper())
            if "led_maps" in cfg:
                for i, m in enumerate(cfg["led_maps"]):
                    if i < LED_INPUT_COUNT:
                        self.led_maps[i].set(int(m))
            if "led_active_br" in cfg:
                for i, b in enumerate(cfg["led_active_br"]):
                    if i < LED_INPUT_COUNT:
                        self.led_active_br[i].set(self._brightness_from_hw(int(b)))

            any_mapped = any(self.led_maps[i].get() != 0 for i in range(LED_INPUT_COUNT))
            self.led_reactive.set(any_mapped)
            for i in range(LED_INPUT_COUNT):
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

            messagebox.showinfo("Import Successful",
                                "Configuration loaded into UI.\n"
                                "Click Save or Save & Play to apply it to the controller.")
        except Exception as exc:
            messagebox.showerror("Import Error", f"Failed to apply config:\n{exc}")

    def _save_config(self):
        if not self.pico.connected:
            return
        try:
            self._stop_monitoring()
            self._push_all_values()
            self.pico.save()
            messagebox.showinfo("Saved", "Configuration saved to controller!")
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    def _save_and_reboot(self):
        if not self.pico.connected:
            return
        if not messagebox.askyesno("Save & Play",
                "Save configuration and return to Play Mode?"):
            return
        try:
            self._stop_monitoring()
            self._push_all_values()
            self.pico.save()
        except Exception as exc:
            messagebox.showerror("Error", f"Save failed: {exc}")
            return
        try:
            self.pico.reboot()
        except Exception:
            pass
        self._set_status("   Rebooted to Play Mode", ACCENT_GREEN)
        self.connect_btn.set_state("normal")
        self.manual_btn.set_state("normal")
        self.save_reboot_btn.set_state("disabled")
        self._set_controls_enabled(False)

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
        if not self.pico.connected or self.scanning:
            return

        # Stop monitoring if active
        self._stop_monitoring()

        self.scan_target = target_key
        self.scanning = True
        self._scan_i2c_found = False
        for btn in self._det_btns.values():
            btn.config(state="disabled")

        self._detect_dlg = tk.Toplevel(self.root)
        self._detect_dlg.title("Detecting Pin")
        self._detect_dlg.configure(bg=BG_CARD)
        self._detect_dlg.geometry("420x230")
        self._detect_dlg.resizable(False, False)
        self._detect_dlg.transient(self.root)
        self._detect_dlg.grab_set()
        self._detect_dlg.protocol("WM_DELETE_WINDOW", self._cancel_detect)

        frame = tk.Frame(self._detect_dlg, bg=BG_CARD)
        frame.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(frame, text=f"Detecting: {target_name}", bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 12, "bold")).pack(pady=(0, 10))
        tk.Label(frame,
                 text="Digital: press the button (connects GPIO to GND)\n"
                      "Analog: move the whammy / tilt the guitar\n"
                      "I2C: ADXL345 or LIS3DH auto-detected on SDA/SCL pins",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9), justify="center").pack(pady=(0, 8))

        self._detect_status = tk.Label(frame, text="Waiting for input...",
                                        bg=BG_CARD, fg=ACCENT_BLUE,
                                        font=(FONT_UI, 10))
        self._detect_status.pack(pady=(0, 12))

        RoundedButton(frame, text="Cancel", command=self._cancel_detect,
                      bg_color="#555560", btn_width=100, btn_height=30,
                      btn_font=(FONT_UI, 8, "bold")).pack()

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
                            self._detect_status.config(
                                text=f"Found {d} on I2C. Waiting for GPIO/ADC..."))
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

        self._close_detect_dialog()
        self._restore_detect_buttons()
        messagebox.showinfo("Detected",
            f"Found {device_name} accelerometer on I2C!\n\n"
            f"Tilt mode set to I2C Accelerometer.\n"
            f"SDA: GPIO {self.i2c_sda_pin.get()}, "
            f"SCL: GPIO {self.i2c_scl_pin.get()}")

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
                if 26 <= pin <= 28:
                    mode_var.set("analog")
                self._refresh_analog_combo(prefix)
                self._on_toggle_analog(prefix)
        elif target in ("joy_x", "joy_y"):
            # Joystick analog axis detect — pin must be an ADC pin
            if 26 <= pin <= 28:
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
                messagebox.showwarning("Detect",
                    f"GPIO {pin} is not an ADC pin (GP26–28).\n"
                    "Joystick VRx/VRy require an analog-capable pin.")
                return
        elif target == "joy_sw":
            # Joystick click switch — any digital GPIO; syncs guide combo too
            self._apply_guide_pin(pin)

        self._close_detect_dialog()
        self._restore_detect_buttons()

        label = DIGITAL_PIN_LABELS.get(pin, f"GPIO {pin}")
        extra = "  (analog)" if 26 <= pin <= 28 else ""

    def _cancel_detect(self):
        self.scanning = False
        try:
            self.pico.stop_scan()
        except Exception:
            pass
        self._close_detect_dialog()
        self._restore_detect_buttons()

    def _on_scan_error(self, msg):
        self.scanning = False
        self._close_detect_dialog()
        self._restore_detect_buttons()
        messagebox.showerror("Scan Error", msg)

    def _close_detect_dialog(self):
        if hasattr(self, '_detect_dlg') and self._detect_dlg.winfo_exists():
            self._detect_dlg.destroy()

    def _restore_detect_buttons(self):
        for btn in self._det_btns.values():
            btn.config(state="normal")

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

        def _worker():
            # ── Step 1: get to BOOTSEL drive ────────────────────────────
            drive = find_rpi_rp2_drive()

            if not drive:
                if self.pico.connected:
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

        threading.Thread(target=_worker, daemon=True).start()

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
            "MONITOR_ADC:<pin>            → streams MVAL:<val> for GP26/27/28; send STOP to end",
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
        dlg.geometry("380x280")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

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
        dlg.wait_window()



#  SPLASH IMAGE FINDER


def _find_icon():
    """Find a .ico file alongside the exe or script for the window icon."""
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    if src_dir not in search_dirs:
        search_dirs.append(src_dir)
    for d in search_dirs:
        for f in os.listdir(d):
            if f.lower().endswith('.ico'):
                return os.path.join(d, f)
    return None


def find_splash_image():
    """Search the exe/script directory for splash.png or splash.jpg."""
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    if src_dir not in search_dirs:
        search_dirs.append(src_dir)

    for d in search_dirs:
        for name in ("splash.png", "splash.PNG"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None



#  STARTUP SOUND


def find_startup_sound():
    """Search the exe/script directory for a startup audio file named 'startup.*'."""
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    if src_dir not in search_dirs:
        search_dirs.append(src_dir)

    extensions = (".wav", ".mp3", ".ogg", ".flac", ".aac", ".wma",
                  ".WAV", ".MP3", ".OGG", ".FLAC", ".AAC", ".WMA")
    for d in search_dirs:
        for ext in extensions:
            p = os.path.join(d, "startup" + ext)
            if os.path.isfile(p):
                return p
    return None


def play_startup_sound():
    """
    Play the startup sound asynchronously from within the process.
    Uses MCI (Media Control Interface) via winmm.dll -- already loaded,
    zero extra dependencies, handles WAV/MP3/WMA/AIFF natively.
    OGG/FLAC fall back to PlaySound (WAV only) and are silently skipped
    if not natively supported by the Windows MCI stack.
    Silent no-op on non-Windows or if no sound file is found.
    """
    if sys.platform != "win32":
        return
    path = find_startup_sound()
    if not path:
        return

    def _mci_play(filepath):
        """Open and play via MCI in a daemon thread so startup isn't blocked."""
        mci = ctypes.windll.winmm.mciSendStringW
        alias = "startup_snd"
        try:
            # Use short (8.3-safe) path to avoid MCI quoting issues
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.kernel32.GetShortPathNameW(filepath, buf, 512)
            short_path = buf.value or filepath

            mci(f'open "{short_path}" alias {alias}', None, 0, None)
            mci(f'play {alias} wait', None, 0, None)
        except Exception:
            pass
        finally:
            try:
                mci(f'close {alias}', None, 0, None)
            except Exception:
                pass

    t = threading.Thread(target=_mci_play, args=(path,), daemon=True)
    t.start()



#  SPLASH OVERLAY


class SplashOverlay:
    """
    A borderless Toplevel that sits on top of the main window,
    exactly covering it, showing a splash image (or fallback text).
    After HOLD_MS it fades out over FADE_MS, then destroys itself.

    The main window is shown normally the whole time — its controls
    load behind the overlay and are revealed as the splash fades away.
    """

    HOLD_MS    = 1000   # fully visible duration (ms)
    FADE_MS    = 500    # fade-out duration (ms)
    FADE_STEPS = 30     # opacity steps during fade

    def __init__(self, root, geometry=None):
        """Create the splash overlay.

        geometry: optional (w, h, x, y) tuple.  Pass this when the root
        window is still withdrawn so winfo_* calls would return stale values.
        If omitted the geometry is read from the live root window as before.
        """
        self._root = root

        if geometry is not None:
            w, h, x, y = geometry
        else:
            # ── Wait for the root window to be mapped so we can read its geometry ──
            root.update_idletasks()
            x = root.winfo_x()
            y = root.winfo_y()
            w = root.winfo_width()
            h = root.winfo_height()

        # ── Create the overlay Toplevel ───────────────────────
        self._overlay = tk.Toplevel(root)
        self._overlay.overrideredirect(True)
        self._overlay.configure(bg=BG_MAIN)
        self._overlay.attributes("-topmost", True)
        self._overlay.attributes("-alpha", 1.0)
        self._overlay.geometry(f"{w}x{h}+{x}+{y}")

        # Keep the overlay glued to the main window if it moves/resizes
        root.bind("<Configure>", self._reposition, add="+")

        # ── Canvas filling the overlay ────────────────────────
        self._canvas = tk.Canvas(self._overlay, bg=BG_MAIN,
                                 highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)

        # ── Load splash image (scaled once to window size) ───────────
        self._photo = None
        img_path = find_splash_image()

        if img_path and img_path.lower().endswith(".png"):
            try:
                from PIL import Image, ImageTk
                self._photo = ImageTk.PhotoImage(
                    Image.open(img_path).resize((w, h)))
            except Exception:
                self._photo = None
            if self._photo is None:
                try:
                    self._photo = tk.PhotoImage(file=img_path)
                except Exception:
                    self._photo = None

        self._draw(w, h)
        # Force the overlay to be fully painted before the caller shows the
        # root window.  update() flushes geometry + expose events so the
        # canvas pixels are on-screen before deiconify() is called.
        self._overlay.update()

        # ── Kick off the hold → fade sequence ─────────────────
        self._alpha       = 1.0
        self._alpha_step  = 1.0 / self.FADE_STEPS
        self._fade_delay  = self.FADE_MS // self.FADE_STEPS
        self._overlay.after(self.HOLD_MS, self._start_fade)

        # Schedule an immediate reposition so that after deiconify() maps
        # the root window we snap to the real client-area coordinates before
        # the first frame is rendered.  The <Configure> binding handles
        # subsequent moves; this handles the very first mapping.
        self._overlay.after(1, self._reposition)

    # ── Drawing ───────────────────────────────────────────────────

    def _draw(self, w, h):
        self._canvas.delete("all")
        if self._photo:
            self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        else:
            # Fallback: styled text centred in the window
            self._canvas.create_text(
                w // 2, h // 2 - 16,
                text="OCC",
                fill=TEXT_HEADER, font=(FONT_UI, 20, "bold"))
            self._canvas.create_text(
                w // 2, h // 2 + 18,
                text="Open Controller Configurator",
                fill=ACCENT_BLUE, font=(FONT_UI, 13))

    # ── Keep overlay covering the main window ─────────────────────

    def _reposition(self, event=None):
        if not self._overlay.winfo_exists():
            return
        try:
            # winfo_rootx/y = client-area origin (excludes invisible DWM shadow).
            # winfo_x/y     = outer frame origin (includes title bar above client).
            # We want the overlay to cover title bar + client area, so:
            #   x = client left  (avoids invisible shadow gap on the right)
            #   y = outer top    (starts above the title bar)
            #   w = client width
            #   h = (title bar height) + client height
            rx = self._root.winfo_rootx()
            ry = self._root.winfo_rooty()
            oy = self._root.winfo_y()
            w  = self._root.winfo_width()
            h  = self._root.winfo_height()
            titlebar_h = ry - oy          # pixels from outer top to client top
            self._overlay.geometry(f"{w}x{h + titlebar_h}+{rx}+{oy}")
        except Exception:
            pass

    # ── Fade sequence ─────────────────────────────────────────────

    def _start_fade(self):
        self._root.unbind("<Configure>")   # stop repositioning during fade
        self._do_fade_step()

    def _do_fade_step(self):
        self._alpha -= self._alpha_step
        if self._alpha <= 0:
            self._finish()
            return
        try:
            self._overlay.attributes("-alpha", max(0.0, self._alpha))
        except Exception:
            pass
        self._overlay.after(self._fade_delay, self._do_fade_step)

    def _finish(self):
        try:
            self._overlay.destroy()
        except Exception:
            pass



#  DRUM APP  (placeholder — replace with full drum configurator UI)


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
        adv.add_separator()
        adv.add_command(label="Export Configuration...", command=self._export_config)
        adv.add_command(label="Import Configuration...", command=self._import_config)
        adv.add_separator()
        adv.add_command(label="Serial Debug Console", command=self._show_serial_debug)
        adv.add_separator()
        adv.add_command(label="Exit", command=self._on_close)
        mb.add_cascade(label="Advanced", menu=adv)

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
    DRUM_LED_INPUT_NAMES = [
        "red_drum", "yellow_drum", "blue_drum", "green_drum",
        "yellow_cym", "blue_cym", "green_cym", "foot_pedal",
        "start", "select",
        "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    ]
    DRUM_LED_INPUT_LABELS = [
        "Red Drum", "Yellow Drum", "Blue Drum", "Green Drum",
        "Yellow Cymbal", "Blue Cymbal", "Green Cymbal", "Foot Pedal",
        "Start", "Select",
        "D-Pad Up", "D-Pad Down", "D-Pad Left", "D-Pad Right",
    ]

    # ── Full UI build ────────────────────────────────────────────────

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

        self._led_widgets      = []
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
        self._make_drum_pins_section()
        self._make_drum_led_section()
        self._make_drum_debounce_section()

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

    def _make_drum_pins_section(self):
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
            # Section separators
            if key == "foot_pedal":
                tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
                tk.Label(inner, text="FOOT PEDAL", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 4))
            elif key == "start":
                tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
                tk.Label(inner, text="START / SELECT", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 4))
            elif key == "dpad_up":
                tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
                tk.Label(inner, text="D-PAD", bg=BG_CARD, fg=TEXT_DIM,
                         font=(FONT_UI, 8, "bold")).pack(anchor="w", pady=(0, 4))
            self._make_drum_pin_row(inner, key, label, dot_color)

    def _make_drum_pin_row(self, parent, key, label, dot_color):
        self._drum_pin_vars[key] = tk.IntVar(value=0)

        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=3)

        if dot_color:
            is_cym = key.endswith("_cym")
            if is_cym:
                # Cymbals: hollow ring character to distinguish from pad dots
                tk.Label(row, text="◎", bg=BG_CARD, fg=dot_color,
                         font=(FONT_UI, 11)).pack(side="left", padx=(0, 4))
            else:
                dot = tk.Canvas(row, width=16, height=16, bg=BG_CARD,
                                highlightthickness=0, bd=0)
                dot.create_oval(2, 2, 14, 14, fill=dot_color, outline=dot_color)
                dot.pack(side="left", padx=(0, 6))
        else:
            tk.Frame(row, width=22, bg=BG_CARD).pack(side="left")

        tk.Label(row, text=label, bg=BG_CARD, fg=TEXT,
                 width=14, anchor="w",
                 font=(FONT_UI, 9)).pack(side="left", padx=(0, 8))
        tk.Label(row, text="Pin:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))

        combo = CustomDropdown(
            row, state="readonly", width=18,
            values=[DIGITAL_PIN_LABELS[p] for p in DIGITAL_PINS])
        # Default pins match drum_config.c defaults; anything not listed defaults to Disabled (-1)
        _default_pins = {
            "red_drum": 0, "yellow_drum": 1, "blue_drum": 2, "green_drum": 3,
            "yellow_cym": 4, "blue_cym": 5, "green_cym": 6,
            "start": 7, "select": 8,
        }
        default_pin = _default_pins.get(key, -1)
        default_combo_idx = DIGITAL_PINS.index(default_pin) if default_pin in DIGITAL_PINS else 0
        combo.current(default_combo_idx)
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
        self._drum_pin_vars[key].set(DIGITAL_PINS[idx])

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
        if pin in DIGITAL_PINS:
            idx = DIGITAL_PINS.index(pin)
            self._drum_pin_vars[key].set(pin)
            combo = self._drum_pin_combos.get(key)
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
        _card, inner = self._make_collapsible_card(
            "LED STRIP  (APA102 / SK9822 / Dotstar)", collapsed=True)

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
        cnt_sp = ttk.Spinbox(cnt_wrap, from_=1, to=MAX_LEDS, width=4,
                              textvariable=self.led_count,
                              command=self._on_drum_led_count_change)
        cnt_sp.pack(fill="both", expand=True)
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
        br_sp = ttk.Spinbox(br_wrap, from_=0, to=9, width=4,
                             textvariable=self.led_base_brightness)
        br_sp.pack(fill="both", expand=True)
        self._drum_all_widgets.append(br_sp)
        self._led_widgets.append(br_sp)
        tk.Label(top, text="(0=off, 9=max)", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 7)).pack(side="left", padx=(4, 0))

        self._led_colors_frame = tk.Frame(inner, bg=BG_CARD)
        self._led_colors_frame.pack(fill="x", pady=(6, 0))
        self._led_widgets.append(self._led_colors_frame)
        self._rebuild_drum_led_color_grid()

        # LED Loop row
        loop_row = tk.Frame(inner, bg=BG_CARD)
        loop_row.pack(fill="x", pady=(6, 2))
        self._led_widgets.append(loop_row)

        loop_cb = ttk.Checkbutton(loop_row, text="Enable LED Color Loop",
                                   variable=self.led_loop_enabled)
        loop_cb.pack(side="left", padx=(0, 12))
        self._drum_all_widgets.append(loop_cb)

        tk.Label(loop_row, text="From LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        loop_start_sp = ttk.Spinbox(loop_row, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_loop_start)
        loop_start_sp.pack(side="left", padx=(0, 8))
        self._drum_all_widgets.append(loop_start_sp)

        tk.Label(loop_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        loop_end_sp = ttk.Spinbox(loop_row, from_=1, to=MAX_LEDS, width=4,
                                   textvariable=self.led_loop_end)
        loop_end_sp.pack(side="left", padx=(0, 10))
        self._drum_all_widgets.append(loop_end_sp)

        tk.Label(loop_row,
                 text="Rotates colors through these LEDs once/sec with smooth crossfade",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")

        # LED Breathe row
        breathe_row = tk.Frame(inner, bg=BG_CARD)
        breathe_row.pack(fill="x", pady=(4, 2))
        self._led_widgets.append(breathe_row)

        breathe_cb = ttk.Checkbutton(breathe_row, text="Enable LED Breathe",
                                     variable=self.led_breathe_enabled,
                                     command=lambda: self.led_wave_enabled.set(False) if self.led_breathe_enabled.get() else None)
        breathe_cb.pack(side="left", padx=(0, 12))
        self._drum_all_widgets.append(breathe_cb)

        tk.Label(breathe_row, text="From LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_start_sp = ttk.Spinbox(breathe_row, from_=1, to=MAX_LEDS, width=4,
                                       textvariable=self.led_breathe_start)
        breathe_start_sp.pack(side="left", padx=(0, 8))
        self._drum_all_widgets.append(breathe_start_sp)

        tk.Label(breathe_row, text="To LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_end_sp = ttk.Spinbox(breathe_row, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_breathe_end)
        breathe_end_sp.pack(side="left", padx=(0, 12))
        self._drum_all_widgets.append(breathe_end_sp)

        tk.Label(breathe_row, text="Min:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_min_sp = ttk.Spinbox(breathe_row, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_min)
        breathe_min_sp.pack(side="left", padx=(0, 8))
        self._drum_all_widgets.append(breathe_min_sp)

        tk.Label(breathe_row, text="Max:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        breathe_max_sp = ttk.Spinbox(breathe_row, from_=0, to=9, width=4,
                                     textvariable=self.led_breathe_max)
        breathe_max_sp.pack(side="left", padx=(0, 10))
        self._drum_all_widgets.append(breathe_max_sp)

        tk.Label(breathe_row, text="Fades brightness slowly between Min and Max (3 s cycle)",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")

        # LED Wave row
        wave_row = tk.Frame(inner, bg=BG_CARD)
        wave_row.pack(fill="x", pady=(4, 2))
        self._led_widgets.append(wave_row)

        wave_cb = ttk.Checkbutton(wave_row, text="Enable LED Wave",
                                  variable=self.led_wave_enabled,
                                  command=lambda: self.led_breathe_enabled.set(False) if self.led_wave_enabled.get() else None)
        wave_cb.pack(side="left", padx=(0, 12))
        self._drum_all_widgets.append(wave_cb)

        tk.Label(wave_row, text="Origin LED:", bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8)).pack(side="left", padx=(0, 3))
        wave_origin_sp = ttk.Spinbox(wave_row, from_=1, to=MAX_LEDS, width=4,
                                     textvariable=self.led_wave_origin)
        wave_origin_sp.pack(side="left", padx=(0, 10))
        self._drum_all_widgets.append(wave_origin_sp)

        tk.Label(wave_row,
                 text="On keypress: brightness pulse radiates outward from origin LED",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")

        sep = tk.Frame(inner, bg=BORDER, height=1)
        sep.pack(fill="x", pady=(8, 4))
        self._led_widgets.append(sep)

        react_row = tk.Frame(inner, bg=BG_CARD)
        react_row.pack(fill="x", pady=(0, 4))
        self._led_widgets.append(react_row)

        react_cb = ttk.Checkbutton(react_row, text="Reactive LEDs on keypress",
                                    variable=self.led_reactive,
                                    command=self._on_drum_reactive_toggle)
        react_cb.pack(side="left", padx=(0, 10))
        self._drum_all_widgets.append(react_cb)
        tk.Label(react_row,
                 text="When enabled, LEDs light up when their mapped input is pressed",
                 bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 7)).pack(side="left")

        lbl = tk.Label(inner,
                       text="Input → LED Mapping  (select which LEDs respond to each input)",
                       bg=BG_CARD, fg=TEXT, font=(FONT_UI, 8, "bold"), anchor="w")
        lbl.pack(fill="x", pady=(0, 4))
        self._led_widgets.append(lbl)
        self._led_map_widgets.append(lbl)

        self._led_map_frame = tk.Frame(inner, bg=BG_CARD)
        self._led_map_frame.pack(fill="x")
        self._led_widgets.append(self._led_map_frame)
        self._led_map_widgets.append(self._led_map_frame)
        self._rebuild_drum_led_map_grid()

        self._on_drum_led_toggle()

    def _on_drum_led_toggle(self):
        show = self.led_enabled.get()
        for w in self._led_widgets:
            if show:
                if not w.winfo_ismapped():
                    w.pack(fill="x")
            else:
                w.pack_forget()
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
        dlg.geometry("335x370")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

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

        for inp_idx in range(self.DRUM_INPUT_COUNT):
            grid_row = inp_idx + 1
            key, lbl_text, dot_color = self.DRUM_BUTTON_DEFS[inp_idx]

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
                                 textvariable=self.led_active_br[inp_idx])
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

        # Load drum pin assignments
        for key, _, _ in self.DRUM_BUTTON_DEFS:
            serial_key = self.DRUM_KEY_MAP.get(key, key)
            if serial_key in cfg:
                pin = int(cfg[serial_key])
                self._drum_pin_vars[key].set(pin)
                combo = self._drum_pin_combos.get(key)
                if combo and pin in DIGITAL_PINS:
                    combo.current(DIGITAL_PINS.index(pin))

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

    def hide(self):
        """Hide this screen; reboot device to play mode if connected."""
        self._scroll_canvas.unbind_all("<MouseWheel>")
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
        self._set_status("   Scanning for XInput controllers...", ACCENT_BLUE)
        controllers = xinput_get_connected() if XINPUT_AVAILABLE else []
        if not controllers:
            self._set_status("   No controllers found", ACCENT_RED)
            messagebox.showwarning("No Controllers",
                "No XInput controllers detected.\n"
                "Make sure the drum kit is plugged in and recognised by Windows.")
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
        """One-click firmware flash. Detects device state automatically and
        handles the full sequence: XInput magic → config mode → BOOTSEL → flash."""
        if not uf2:
            uf2 = filedialog.askopenfilename(
                title="Select UF2 Firmware File",
                filetypes=[("UF2 Firmware", "*.uf2"), ("All Files", "*.*")])
            if not uf2:
                return

        def _worker():
            # ── Step 1: get to BOOTSEL drive ────────────────────────────
            drive = find_rpi_rp2_drive()

            if not drive:
                if self.pico.connected:
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

        threading.Thread(target=_worker, daemon=True).start()

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

        # Push all SET-able keys from the saved config back to the firmware.
        # Skip meta keys that aren't firmware SET keys.
        SKIP_KEYS = {"device_type", "led_colors_raw", "led_map_raw"}
        errors = []
        for key, val in cfg.items():
            if key in SKIP_KEYS:
                continue
            try:
                self.pico.set_value(key, val)
            except Exception as exc:
                errors.append(f"{key}: {exc}")

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



#  (DongleApp removed — dongle firmware has no config serial mode)



class PedalApp:
    """
    Pedal Controller configurator screen.

    Configures up to 4 pedal buttons: GPIO pin assignment and XInput button mapping.
    The pedal firmware has no LED support, so this screen is intentionally simple.
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

        hm = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT,
                     activebackground=ACCENT_BLUE, activeforeground="#fff")
        hm.add_command(label="About", command=self._show_about)
        mb.add_cascade(label="Help", menu=hm)

        self._menu_bar = mb

    # ── Full UI build ────────────────────────────────────────────────

    def _build_ui(self):
        self._pin_vars    = [tk.IntVar(value=-1) for _ in range(self.PEDAL_COUNT)]
        self._pin_combos  = [None] * self.PEDAL_COUNT
        self._map_vars    = [tk.IntVar(value=i) for i in range(self.PEDAL_COUNT)]
        self._map_combos  = [None] * self.PEDAL_COUNT
        self._det_btns    = [None] * self.PEDAL_COUNT
        self._all_widgets = []

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
        self._make_pedal_buttons_section()
        self._make_analog_inputs_section()
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

    # ── Section: Pedal Button Mapping ────────────────────────────────

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

        DEFAULT_PINS = [2, 3, 4, 5]
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
        self._pin_vars[idx].set(DIGITAL_PINS[combo.current()])

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
        self._adc_pin_vars[idx].set(self.ADC_PINS[combo.current()])

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
        try:
            cfg = self.pico.get_config()
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read config: {exc}")
            return

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

    # ── Push all values to firmware ───────────────────────────────────

    def _push_all_values(self):
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

    # ── Save & Play Mode ──────────────────────────────────────────────

    def _save_and_reboot(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected",
                "Connect to the pedal controller before saving.")
            return
        self._stop_adc_monitoring()
        self._stop_detect()
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

    def hide(self):
        """Hide this screen; reboot device to play mode if connected."""
        self._scroll_canvas.unbind_all("<MouseWheel>")
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
                "Make sure the pedal controller is plugged in and recognised by Windows.")
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

        def _worker():
            drive = find_rpi_rp2_drive()

            if not drive:
                if self.pico.connected:
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

        threading.Thread(target=_worker, daemon=True).start()

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

        SKIP_KEYS = {"device_type"}
        errors = []
        for key, val in cfg.items():
            if key in SKIP_KEYS:
                continue
            try:
                self.pico.set_value(key, val)
            except Exception as exc:
                errors.append(f"{key}: {exc}")

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



#  DEVICE TYPE → SCREEN CLASS  routing table
#
#  To add a new device type:
#    1. Create a new App class (e.g. BassApp) above.
#    2. Add an entry here:  "bass_guitar": BassApp
#


DEVICE_SCREEN_MAP = {
    "guitar_alternate":        None,   # filled in main() once App is instantiated
    "guitar_alternate_dongle": None,   # dongle guitar variant → same App screen
    "drum_kit":                None,   # filled in main() once DrumApp is instantiated
    "pedal":                   None,   # filled in main() once PedalApp is instantiated
}

# Map device_type → the constructor to call (used to build instances in main())
DEVICE_SCREEN_CLASSES = {
    "guitar_alternate":        App,
    "guitar_alternate_dongle": App,
    "guitar_combined":         App,
    "drum_kit":                DrumApp,
    "pedal":                   PedalApp,
}



#  ENTRY POINT


def main():
    root = tk.Tk()
    # Hide the window immediately so the blank white frame is never visible
    # while Python/tkinter finishes initialising.  We reveal it below once
    # everything is built and ready.
    root.withdraw()

    # Load and register bundled Helvetica fonts.  Must be called after Tk()
    # so that tkfont.families() is available, but before any widgets are built.
    _load_fonts()

    root.title("OCC - Open Controller Configurator")

    # ── Unified window geometry — set once, never changed by screens ──
    w, h = 1180, 820
    root.update_idletasks()   # ensure Tk has the real screen dimensions
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.resizable(False, False)   # fixed size on all axes

    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    # Apply custom .ico if one exists alongside the exe / script
    _ico = _find_icon()
    if _ico:
        try:
            root.iconbitmap(_ico)
        except Exception:
            pass

    # Play startup sound immediately (async, non-blocking)
    play_startup_sound()

    # ── Build lightweight screens first ─────────────────────────────
    # MainMenu, EasyConfig and FlashScreen are fast to construct.
    # The heavy device configurator screens (App, DrumApp) are deferred
    # until after the window is visible so the splash appears instantly.

    menu = MainMenu(root, on_configure=None)   # on_configure set below

    easy_config_screen = EasyConfigScreen(root, on_back=None)
    easy_config_screen.hide()

    flash_screen = FlashFirmwareScreen(root, on_back=None)
    flash_screen.hide()

    # ── Show splash first, then reveal the window behind it ──────────
    # SplashOverlay is created while root is still withdrawn so the
    # overlay is fully painted before deiconify() makes everything visible.
    menu.show()
    SplashOverlay(root, geometry=(w, h, x, y))
    root.deiconify()

    # ── Deferred device screen construction ─────────────────────────
    device_screens = {}

    def go_to_menu():
        for s in device_screens.values():
            s.hide()
        flash_screen.hide()
        easy_config_screen.hide()
        menu.show()

    def go_to_easy_config(port):
        """
        Route to Easy Configuration.  Mirrors go_to_configurator() — handles
        both config-mode (port given) and XInput play mode (port=None).
        """
        if menu._poll_job:
            menu.root.after_cancel(menu._poll_job)
            menu._poll_job = None

        if port:
            # Already in config mode
            menu.hide()
            easy_config_screen.show()
            easy_config_screen._connect_serial(port)

        elif XINPUT_AVAILABLE:
            # XInput play mode — stay on menu, run magic sequence in background
            menu._cfg_btn.set_state("disabled")
            menu._easy_cfg_btn.set_state("disabled")
            menu._ctrl_icon.config(text="\u25cc", fg=ACCENT_BLUE)
            menu._ctrl_status.config(text="Connecting\u2026", fg=ACCENT_BLUE)
            menu._ctrl_detail.config(text="Sending config signal\u2026", fg=TEXT_DIM)
            root.update_idletasks()

            def _worker():
                try:
                    controllers = xinput_get_connected()
                    if not controllers:
                        root.after(0, lambda: [
                            menu._ctrl_icon.config(text="\u25cb", fg=TEXT_DIM),
                            menu._ctrl_status.config(text="No device found", fg=ACCENT_RED),
                            menu._ctrl_detail.config(text="", fg=TEXT_DIM),
                            menu._cfg_btn.set_state("disabled"),
                            menu._easy_cfg_btn.set_state("disabled"),
                        ])
                        return
                    slot = controllers[0][0]
                    for left, right in MAGIC_STEPS:
                        xinput_send_vibration(slot, left, right)
                        time.sleep(0.08)
                    xinput_send_vibration(slot, 0, 0)
                except Exception as exc:
                    root.after(0, lambda e=exc: [
                        menu._ctrl_icon.config(text="\u25cb", fg=TEXT_DIM),
                        menu._ctrl_status.config(text=f"Signal failed: {e}", fg=ACCENT_RED),
                        menu._ctrl_detail.config(text="", fg=TEXT_DIM),
                        menu._cfg_btn.set_state("normal"),
                        menu._easy_cfg_btn.set_state("normal"),
                    ])
                    return

                root.after(0, lambda: menu._ctrl_detail.config(
                    text="Waiting for config port\u2026", fg=TEXT_DIM))

                deadline = time.time() + 10.0
                found_port = None
                while time.time() < deadline:
                    found_port = PicoSerial.find_config_port()
                    if found_port:
                        break
                    time.sleep(0.2)

                if not found_port:
                    root.after(0, lambda: [
                        menu._ctrl_icon.config(text="\u25cb", fg=TEXT_DIM),
                        menu._ctrl_status.config(text="Config mode timed out", fg=ACCENT_RED),
                        menu._ctrl_detail.config(
                            text="Close any games using the controller and retry.", fg=TEXT_DIM),
                        menu._cfg_btn.set_state("normal"),
                        menu._easy_cfg_btn.set_state("normal"),
                    ])
                    return

                time.sleep(0.5)

                def _finish(fp=found_port):
                    menu.hide()
                    easy_config_screen.show()
                    easy_config_screen._connect_serial(fp)

                root.after(0, _finish)

            threading.Thread(target=_worker, daemon=True).start()

    def go_to_flash_screen(drive):
        menu.hide()
        flash_screen.show(drive=drive)

    def _route_to_screen(device_type, port):
        """Called on the Tk thread once DEVTYPE is known. Shows the right screen."""
        if device_type == "dongle":
            menu._ctrl_icon.config(text="●", fg=ACCENT_ORANGE)
            menu._ctrl_status.config(
                text="Dongle detected, no configuration options available.",
                fg=ACCENT_ORANGE)
            menu._ctrl_detail.config(text="", fg=TEXT_DIM)
            menu._cfg_btn.set_state("disabled")
            menu._easy_cfg_btn.set_state("disabled")
            return
        screen = device_screens.get(device_type)
        if screen is None:
            menu._ctrl_icon.config(text="●", fg=ACCENT_ORANGE)
            menu._ctrl_status.config(text="Unsupported device type", fg=ACCENT_ORANGE)
            menu._ctrl_detail.config(text=f'Type reported: "{device_type}"', fg=TEXT_DIM)
            menu._cfg_btn.set_state("normal")
            menu._easy_cfg_btn.set_state("normal")
            if device_type == "unknown":
                messagebox.showerror(
                    "Device Type Unknown",
                    "The connected device did not report its type.\n\n"
                    "This usually means the firmware is outdated and is missing\n"
                    "the DEVTYPE line in its GET_CONFIG response.\n\n"
                    "Fix: add  serial_writeln(\"DEVTYPE:\" DEVICE_TYPE);  as the\n"
                    "first line of send_config() in config_serial.c, then\n"
                    "rebuild and reflash the firmware."
                )
            else:
                messagebox.showerror(
                    "Unsupported Device",
                    f"Connected device reports an unrecognised type:\n"
                    f"  \"{device_type}\"\n\n"
                    f"Supported types: {', '.join(sorted(DEVICE_SCREEN_CLASSES.keys()))}\n\n"
                    "Make sure you are running the latest configurator."
                )
            return
        menu.hide()
        screen.show()
        screen._connect_serial(port)

    def go_to_configurator(port):
        """
        Route to the correct configurator screen based on DEVTYPE.
        If device screens are not yet built, wait for them first.
        """
        if menu._poll_job:
            menu.root.after_cancel(menu._poll_job)
            menu._poll_job = None

        if port:
            try:
                ps = PicoSerial()
                ps.connect(port)
                cfg = ps.get_config()
                ps.disconnect()
                device_type = cfg.get("device_type", "unknown")
            except Exception:
                device_type = "unknown"
            _route_to_screen(device_type, port)

        elif XINPUT_AVAILABLE:
            menu._cfg_btn.set_state("disabled")
            menu._easy_cfg_btn.set_state("disabled")
            menu._ctrl_icon.config(text="◌", fg=ACCENT_BLUE)
            menu._ctrl_status.config(text="Connecting…", fg=ACCENT_BLUE)
            menu._ctrl_detail.config(text="Sending config signal…", fg=TEXT_DIM)
            root.update_idletasks()

            def _worker():
                try:
                    controllers = xinput_get_connected()
                    if not controllers:
                        root.after(0, lambda: [
                            menu._ctrl_icon.config(text="○", fg=TEXT_DIM),
                            menu._ctrl_status.config(text="No device found", fg=ACCENT_RED),
                            menu._ctrl_detail.config(text="", fg=TEXT_DIM),
                            menu._cfg_btn.set_state("disabled"),
                            menu._easy_cfg_btn.set_state("disabled"),
                        ])
                        return
                    slot = controllers[0][0]
                    for left, right in MAGIC_STEPS:
                        xinput_send_vibration(slot, left, right)
                        time.sleep(0.08)
                    xinput_send_vibration(slot, 0, 0)
                except Exception as exc:
                    root.after(0, lambda e=exc: [
                        menu._ctrl_icon.config(text="○", fg=TEXT_DIM),
                        menu._ctrl_status.config(text=f"Signal failed: {e}", fg=ACCENT_RED),
                        menu._ctrl_detail.config(text="", fg=TEXT_DIM),
                        menu._cfg_btn.set_state("normal"),
                        menu._easy_cfg_btn.set_state("normal"),
                    ])
                    return

                root.after(0, lambda: menu._ctrl_detail.config(
                    text="Waiting for config port…", fg=TEXT_DIM))

                deadline = time.time() + 10.0
                found_port = None
                while time.time() < deadline:
                    found_port = PicoSerial.find_config_port()
                    if found_port:
                        break
                    time.sleep(0.2)

                if not found_port:
                    root.after(0, lambda: [
                        menu._ctrl_icon.config(text="○", fg=TEXT_DIM),
                        menu._ctrl_status.config(text="Config mode timed out", fg=ACCENT_RED),
                        menu._ctrl_detail.config(
                            text="Close any games using the controller and retry.", fg=TEXT_DIM),
                        menu._cfg_btn.set_state("normal"),
                        menu._easy_cfg_btn.set_state("normal"),
                    ])
                    return

                time.sleep(0.5)  # let the port settle

                root.after(0, lambda: menu._ctrl_detail.config(
                    text="Identifying device…", fg=TEXT_DIM))

                try:
                    ps = PicoSerial()
                    ps.connect(found_port)
                    cfg = ps.get_config()
                    ps.disconnect()
                    device_type = cfg.get("device_type", "unknown")
                except Exception:
                    device_type = "unknown"

                root.after(0, lambda dt=device_type, fp=found_port:
                    _route_to_screen(dt, fp))

            threading.Thread(target=_worker, daemon=True).start()

    def _build_device_screens():
        """Build the heavy configurator screens after the splash is showing."""
        for dtype, cls in DEVICE_SCREEN_CLASSES.items():
            screen = cls(root, on_back=go_to_menu)
            screen.hide()
            device_screens[dtype] = screen

        flash_screen._on_back = go_to_menu
        easy_config_screen._on_back = go_to_menu
        menu._on_configure = go_to_configurator
        menu._on_flash_screen = go_to_flash_screen
        menu._on_easy_config = go_to_easy_config

    # Schedule device screen construction on the next event loop tick
    # so the splash overlay renders first
    root.after(50, _build_device_screens)

    root.mainloop()


if __name__ == "__main__":
    main()
