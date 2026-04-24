import tkinter as tk
from .constants import (BG_CARD, BG_INPUT, BG_HOVER, BG_MAIN, BORDER,
                         TEXT, TEXT_DIM, TEXT_HEADER, ACCENT_BLUE)
from .fonts import FONT_UI
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


class HelpButton(tk.Canvas):
    """Circle '?' button for screen headers. Canvas subclass, mirrors RoundedButton pattern."""

    def __init__(self, parent, command, size=26):
        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG_CARD
        super().__init__(parent, width=size, height=size,
                         bg=parent_bg, highlightthickness=0, bd=0, cursor="hand2")
        self._size = size
        self._cmd  = command
        self._normal = BG_INPUT
        self._hover  = BG_HOVER
        self._press  = BORDER
        self._render(self._normal)
        self.bind("<Enter>",           lambda e: self._render(self._hover))
        self.bind("<Leave>",           lambda e: self._render(self._normal))
        self.bind("<ButtonPress-1>",   lambda e: self._render(self._press))
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_release(self, _event):
        self._render(self._hover)
        if self._cmd:
            self._cmd()

    def _render(self, fill):
        self.delete("all")
        s = self._size
        self.create_oval(1, 1, s - 1, s - 1, fill=fill, outline=BORDER)
        self.create_text(s // 2, s // 2, text="?", fill=TEXT_HEADER,
                         font=(FONT_UI, 10, "bold"))


def _help_placeholder(text="Help content coming soon."):
    """Returns a tab content builder that shows a placeholder label."""
    def _build(frame):
        tk.Label(frame, text=text, bg=BG_CARD, fg=TEXT,
                 font=(FONT_UI, 10), wraplength=700, justify="left",
                 anchor="nw", padx=20, pady=20).pack(anchor="nw")
    return _build


def _help_text(*segments):
    """
    Returns a tab content builder with per-segment formatting.
    Each segment is a (text, style) tuple. Use "\n" text for blank lines.
    Styles: None (normal), "bold", "dim", "header", "italic"
    Example: _help_text(("Bold title", "bold"), ("\n", None), ("Body text.", None))
    """
    def _build(frame):
        inner = tk.Frame(frame, bg=BG_CARD)
        inner.pack(anchor="nw", padx=20, pady=20)
        prev_style = None
        for text, style in segments:
            if text == "\n" or text == "\n\n":
                # blank spacer line
                if prev_style not in ("bold", "header"):
                    tk.Label(inner, text="", bg=BG_CARD, height=1).pack(anchor="w")
            else:
                if style == "bold":
                    font_spec = (FONT_UI, 9, "bold")
                elif style == "header":
                    font_spec = (FONT_UI, 11, "bold")
                elif style == "italic":
                    font_spec = (FONT_UI, 9, "italic")
                else:
                    font_spec = (FONT_UI, 9)
                fg = TEXT_DIM if style == "dim" else TEXT
                tk.Label(inner, text=text, bg=BG_CARD, fg=fg,
                         font=font_spec, wraplength=700,
                         justify="left", anchor="w").pack(anchor="w")
            prev_style = style
    return _build


class HelpDialog:
    """
    Non-modal help popup. 760x600, centered over root.
    Tabs: same pack/pack_forget pattern as App._switch_tab.
    Re-opening lifts existing window instead of opening a second one.
    """
    W, H = 760, 600

    def __init__(self, root, tabs):
        # tabs: list of (name: str, builder: callable(frame) -> None)
        self.root = root
        self.tabs = tabs
        self._win = None

    def open(self):
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._build()

    def _build(self):
        win = tk.Toplevel(self.root)
        self._win = win
        win.title("Help")
        win.configure(bg=BG_CARD)
        win.resizable(False, False)
        win.transient(self.root)

        # Center over root
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width()  - self.W) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - self.H) // 2
        win.geometry(f"{self.W}x{self.H}+{x}+{y}")

        # Tab bar — same label+pack pattern as App
        tab_bar = tk.Frame(win, bg=BG_MAIN)
        tab_bar.pack(fill="x")
        self._tab_labels = []
        for i, (name, _) in enumerate(self.tabs):
            lbl = tk.Label(tab_bar, text=name, bg=BG_MAIN, fg=TEXT_DIM,
                           font=(FONT_UI, 10, "bold"), padx=16, pady=8, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, idx=i: self._switch_tab(idx))
            self._tab_labels.append(lbl)
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x")

        # Content area — one frame per tab, built once
        container = tk.Frame(win, bg=BG_CARD)
        container.pack(fill="both", expand=True)
        self._tab_frames = []
        for _, builder in self.tabs:
            f = tk.Frame(container, bg=BG_CARD)
            builder(f)
            self._tab_frames.append(f)

        # Close button row
        btn_row = tk.Frame(win, bg=BG_CARD)
        btn_row.pack(fill="x", pady=(0, 10))
        RoundedButton(btn_row, text="Close", command=win.destroy,
                      bg_color=BG_INPUT, btn_width=90, btn_height=30).pack(side="right", padx=12)

        # Show first tab
        self._active = 0
        self._tab_frames[0].pack(fill="both", expand=True)
        self._update_tab_styling()
        win.protocol("WM_DELETE_WINDOW", win.destroy)

    def _switch_tab(self, idx):
        if idx == self._active:
            return
        self._tab_frames[self._active].pack_forget()
        self._tab_frames[idx].pack(fill="both", expand=True)
        self._active = idx
        self._update_tab_styling()

    def _update_tab_styling(self):
        for i, lbl in enumerate(self._tab_labels):
            lbl.config(bg=BG_CARD if i == self._active else BG_MAIN,
                       fg=TEXT     if i == self._active else TEXT_DIM)


class SpeedSlider(tk.Canvas):
    """Speed slider with 5 named notches. Left=slow (high ms), right=fast (low ms)."""
    _LABELS = ["snail", "slow", "normal", "fast", "sonic"]

    def __init__(self, parent, variable, notch_ms, width=260, height=58):
        try:
            bg = parent.cget("bg")
        except Exception:
            bg = BG_CARD
        super().__init__(parent, width=width, height=height,
                         bg=bg, highlightthickness=0, bd=0)
        self._var      = variable
        self._notch_ms = notch_ms   # [uber_slow, slow, normal, fast, sonic_fast]
        self._W        = width
        self._H        = height
        self._PAD      = 10         # left/right track padding
        self._TY       = 26         # track y-center
        self._enabled  = True

        self._var.trace_add("write", lambda *_: self._redraw())
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._redraw()

    # ms <-> x conversion (piecewise linear across 4 segments)

    def _ms_to_x(self, ms):
        tw = self._W - 2 * self._PAD
        n  = self._notch_ms
        for i in range(4):
            if ms >= n[i + 1]:
                t = (n[i] - ms) / (n[i] - n[i + 1])   # 0=left notch, 1=right notch
                t = max(0.0, min(1.0, t))
                frac = (i + t) / 4.0
                return self._PAD + frac * tw
        return self._PAD + tw   # at sonic end

    def _x_to_ms(self, x):
        tw   = self._W - 2 * self._PAD
        frac = max(0.0, min(1.0, (x - self._PAD) / tw))
        seg  = min(int(frac * 4), 3)
        t    = frac * 4 - seg
        n    = self._notch_ms
        return int(round(n[seg] - t * (n[seg] - n[seg + 1])))

    def _zone(self, ms):
        n = self._notch_ms
        for i in range(4):
            if ms >= (n[i] + n[i + 1]) / 2:
                return self._LABELS[i]
        return self._LABELS[4]

    def _redraw(self):
        self.delete("all")
        W, H, PAD, TY = self._W, self._H, self._PAD, self._TY
        tw = W - 2 * PAD
        dim = self._enabled

        track_col = "#555" if dim else "#333"
        tick_col  = "#888" if dim else "#444"
        lbl_col   = TEXT_DIM if dim else "#444"

        self.create_line(PAD, TY, PAD + tw, TY, fill=track_col, width=2)

        for i, (label, ms) in enumerate(zip(self._LABELS, self._notch_ms)):
            x = PAD + i * tw / 4
            self.create_line(x, TY - 6, x, TY + 6, fill=tick_col, width=1)
            # anchor edge labels inward so they don't clip the canvas border
            anc = "sw" if i == 0 else ("se" if i == 4 else "s")
            self.create_text(x, TY - 8, text=label, fill=lbl_col,
                             font=(FONT_UI, 7), anchor=anc)

        ms  = max(self._notch_ms[-1], min(self._notch_ms[0], self._var.get()))
        tx  = self._ms_to_x(ms)
        col = ACCENT_BLUE if dim else "#2d4a6a"
        self.create_rectangle(tx - 5, TY - 8, tx + 5, TY + 8,
                              fill=col, outline="", tags="thumb")

        zone = self._zone(ms)
        by   = TY + 12
        self.create_text(tx, by, text=zone, fill=TEXT if dim else "#444",
                         font=(FONT_UI, 8), anchor="n", tags="badge")

    def _on_press(self, e):
        if self._enabled:
            self._set_from_x(e.x)

    def _on_drag(self, e):
        if self._enabled:
            self._set_from_x(e.x)

    def _on_release(self, e):
        pass

    def _set_from_x(self, x):
        ms = self._x_to_ms(x)
        ms = max(self._notch_ms[-1], min(self._notch_ms[0], ms))
        self._var.set(ms)

    def config(self, **kwargs):
        if "state" in kwargs:
            self._enabled = kwargs.pop("state") != "disabled"
            self._redraw()
        if kwargs:
            super().config(**kwargs)

    configure = config


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
