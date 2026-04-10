import sys, os, time, threading
import tkinter as tk
from tkinter import messagebox, filedialog
from .constants import (BG_MAIN, BG_CARD, BG_INPUT, BG_HOVER, BORDER, TEXT, TEXT_DIM,
                         TEXT_HEADER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
                         NUKE_UF2_FILENAME, OCC_SUBTYPES)
from .fonts import FONT_UI, _resource_path
from .widgets import RoundedButton, CustomDropdown, HelpDialog, HelpButton, _help_text, _help_placeholder
from .firmware_utils import (find_uf2_files, _group_uf2_files, load_fw_presets,
                              _apply_preset_config, flash_uf2, flash_uf2_with_reboot,
                              find_rpi_rp2_drive, find_rpi_rp2_drive_info,
                              get_bundled_fw_date_str, find_resetFW_uf2)
from .serial_comms import PicoSerial
from .xinput_utils import xinput_get_connected, MAGIC_STEPS, xinput_send_vibration
from .utils import _centered_dialog, _center_window, _ask_wired_or_wireless, _make_flash_popup, _find_preset_configs
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
        self._help_dialog = None
        self._busy = False        # suppresses _poll navigation during preset install

        self.frame = tk.Frame(root, bg=BG_MAIN)
        self._build()

    # ── Layout ────────────────────────────────────────────────────

    def _open_help(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self.root, [
                ("Overview",          _help_text(
                    ("Welcome to the Firmware flash screen!", "bold"),
                    ("\n\n", None),
                    ("This is what you'll see if your Pico controller is detected to be in BOOTSEL/USB mode. You can use this screen to select an OCC firmware to install to your Pico, and then you will be automatically redirected to the main menu. Check out the \"Choosing Firmwares\" help tab for more information about the firmwares available here.", None),
                )),
                ("Choosing Firmwares", _help_placeholder("OCC has firmwares for typical game controllers, rhythm controllers, proprietary wireless dongles, and more! Depending on what controller you have plugged in right now, or what this Pi Pico will be used for, go ahead and select a firmware that suits your need. Different firmwares have different configurable settings, and will appear as different device types to your PC.")),
                ("Wireless or Wired",  _help_placeholder("(Feature still in progress)\nOCC has firmwares for both wired Picos and wireless capable PicoWs! Clicking a firmware for a controller will automatically install the wireless or wired version of it, depending on what type of Pi Pico you have connected. If you want to manually pick a wired or wireless firmware yourself, right click the firmware you want, then make your pick.")),
            ])
        self._help_dialog.open()

    def _build(self):
        # ── Title bar — identical to MainMenu ─────────────────
        title_bar = tk.Frame(self.frame, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        title_bar.pack(fill="x", padx=0, pady=(0, 0))

        inner_title = tk.Frame(title_bar, bg=BG_CARD)
        inner_title.pack(fill="x", padx=24, pady=16)

        HelpButton(inner_title, command=self._open_help).pack(side="right", anchor="n", pady=4)
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

        # ── Tabbed panel (OCC Firmware / Controller Presets) ─────
        tab_outer = tk.Frame(self.frame, bg=BORDER,
                             highlightbackground=BORDER, highlightthickness=1)
        tab_outer.pack(fill="both", expand=True, padx=40, pady=(0, 14))

        # Tab bar
        tab_bar = tk.Frame(tab_outer, bg=BG_CARD)
        tab_bar.pack(fill="x")
        tab_bar.columnconfigure(0, weight=1)
        tab_bar.columnconfigure(1, weight=1)

        self._fw_content      = tk.Frame(tab_outer, bg=BG_MAIN)
        self._presets_content = tk.Frame(tab_outer, bg=BG_MAIN)

        def _make_tab(parent, text, col, cmd):
            f = tk.Frame(parent, bg=BG_CARD, cursor="hand2")
            f.grid(row=0, column=col, sticky="nsew")
            lbl = tk.Label(f, text=text, bg=BG_CARD, fg=TEXT_DIM,
                           font=(FONT_UI, 12, "bold"), pady=12)
            lbl.pack(fill="x")
            line = tk.Frame(f, bg=ACCENT_BLUE, height=3)
            for w in (f, lbl):
                w.bind("<Button-1>", lambda e, c=cmd: c())
                w.bind("<Enter>", lambda e, l=lbl: l.config(fg=TEXT_HEADER))
                w.bind("<Leave>", lambda e, l=lbl, c=cmd: None)  # reset handled by _switch_tab
            return f, lbl, line

        self._fw_tab_f,   self._fw_tab_lbl,   self._fw_tab_line   = _make_tab(tab_bar, "OCC Firmware",       0, lambda: self._switch_tab("firmware"))
        self._pres_tab_f, self._pres_tab_lbl, self._pres_tab_line = _make_tab(tab_bar, "Controller Presets", 1, lambda: self._switch_tab("presets"))

        # Divider between tab bar and content
        tk.Frame(tab_outer, bg=BORDER, height=1).pack(fill="x")

        self._build_fw_tab(self._fw_content)
        self._build_presets_tab(self._presets_content)
        self._switch_tab("firmware")

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

        tk.Label(rst_text, text="Will use resetFW.uf2 and wipe storage.",
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

    # ── Tab management ────────────────────────────────────────────

    def _switch_tab(self, name):
        """Show the named tab ('firmware' or 'presets'), hide the other.
        Resets the target tab to its original state each time it is shown."""
        if name == "firmware":
            self._presets_content.pack_forget()
            self._fw_content.pack(fill="both", expand=True)
            self._fw_tab_lbl.config(fg=TEXT_HEADER)
            self._fw_tab_line.pack(fill="x")
            self._pres_tab_lbl.config(fg=TEXT_DIM)
            self._pres_tab_line.pack_forget()
            # Reset firmware tab: scroll back to top
            if hasattr(self, "_canvas"):
                self._canvas.yview_moveto(0)
        else:
            self._fw_content.pack_forget()
            self._presets_content.pack(fill="both", expand=True)
            self._pres_tab_lbl.config(fg=TEXT_HEADER)
            self._pres_tab_line.pack(fill="x")
            self._fw_tab_lbl.config(fg=TEXT_DIM)
            self._fw_tab_line.pack_forget()
            # Reset presets tab: close all accordion sections and scroll to top
            if hasattr(self, "_accordion_closers"):
                for close_fn in self._accordion_closers:
                    close_fn()
            if hasattr(self, "_presets_canvas"):
                self._presets_canvas.yview_moveto(0)

    def _build_fw_tab(self, parent):
        """Build the scrollable firmware tile grid into parent."""
        self._canvas = tk.Canvas(parent, bg=BG_MAIN,
                                 highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical",
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
        self.frame.after(50, self._reflow_tiles)

    def _build_presets_tab(self, parent):
        """Scrollable accordion of controller preset sections."""
        canvas = tk.Canvas(parent, bg=BG_MAIN, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Store canvas reference so _switch_tab can reset scroll position
        self._presets_canvas = canvas

        inner = tk.Frame(canvas, bg=BG_MAIN)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _update_scrollregion(e=None):
            # Force scrollregion to always start at y=0 so the user cannot
            # scroll up into empty space above the content.
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=(0, 0, bbox[2], bbox[3]))

        inner.bind("<Configure>", _update_scrollregion)
        canvas.bind("<Configure>",
                    lambda e: (canvas.itemconfig(inner_id, width=e.width),
                               canvas.after(1, _update_scrollregion)))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        inner.bind("<MouseWheel>",
                   lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        presets, base_dir = load_fw_presets()
        uf2_groups = {name: (w, wl) for name, w, wl in _group_uf2_files(find_uf2_files())}

        # Track accordion toggle functions so _switch_tab can close them all
        self._accordion_closers = []

        for section_name, section_data in presets.items():
            self._build_accordion_section(inner, canvas, section_name,
                                          section_data, uf2_groups, base_dir)

        # Bottom padding
        tk.Frame(inner, bg=BG_MAIN, height=12).pack()

        # Clamp scrollregion once layout has settled so y=0 is always the top
        canvas.after(50, _update_scrollregion)

    def _build_accordion_section(self, parent, canvas, title, section_data, uf2_groups, base_dir):
        """One collapsible accordion section with item buttons.
        section_data: {item_name: {firmware, preset_config}} from ControllerFWPresets.json.
        Items with preset_config=None are greyed-out stubs.
        """
        is_open = [False]

        section = tk.Frame(parent, bg=BG_MAIN)
        section.pack(fill="x", padx=16, pady=(8, 0))

        # Header row
        hdr = tk.Frame(section, bg=BG_CARD, cursor="hand2")
        hdr.pack(fill="x")

        arrow = tk.Label(hdr, text="▶", bg=BG_CARD, fg=ACCENT_BLUE,
                         font=(FONT_UI, 10), width=2, anchor="center")
        arrow.pack(side="left", padx=(12, 4), pady=10)

        # Section icon — load PresetConfigs/<title>.gif at 24×24.
        # Falls back to a blank spacer if the file is missing or unreadable.
        _icon_img = None
        _icon_path = _resource_path("PresetConfigs", title + ".gif")
        if os.path.isfile(_icon_path):
            try:
                from PIL import Image, ImageTk
                _pil = Image.open(_icon_path).convert("RGBA").resize((24, 24), Image.LANCZOS)
                _icon_img = ImageTk.PhotoImage(_pil)
                if not hasattr(self, "_preset_icon_refs"):
                    self._preset_icon_refs = []
                self._preset_icon_refs.append(_icon_img)
            except Exception:
                _icon_img = None
        icon_lbl = tk.Label(hdr, image=_icon_img, bg=BG_CARD)
        icon_lbl.pack(side="left", padx=(0, 8), pady=10)

        tk.Label(hdr, text=title, bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 11, "bold"), anchor="w").pack(
                     side="left", fill="x", expand=True, pady=10)

        # Items frame — hidden until expanded
        items_frame = tk.Frame(section, bg=BG_MAIN)

        for item_name, item_info in section_data.items():
            cfg_rel  = item_info.get("preset_config")   # None = stub
            fw_name  = item_info.get("firmware", "")
            wired, wireless = uf2_groups.get(fw_name, (None, None))
            cfg_abs  = os.path.join(base_dir, cfg_rel) if cfg_rel and base_dir else None
            is_stub  = cfg_abs is None

            row = tk.Frame(items_frame, bg=BG_MAIN,
                           cursor="arrow" if is_stub else "hand2")
            row.pack(fill="x", padx=(40, 0), pady=1)
            lbl = tk.Label(row, text=item_name, bg=BG_MAIN,
                           fg=TEXT_DIM if is_stub else TEXT,
                           font=(FONT_UI, 10), anchor="w", padx=16, pady=8)
            lbl.pack(fill="x")

            # Forward scroll events from every item widget up to the canvas
            for w in (row, lbl):
                w.bind("<MouseWheel>",
                       lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
                w.bind("<Button-4>",
                       lambda e: canvas.yview_scroll(-1, "units"))
                w.bind("<Button-5>",
                       lambda e: canvas.yview_scroll(1, "units"))

            if not is_stub:
                for w in (row, lbl):
                    w.bind("<Enter>", lambda e, r=row, l=lbl: (r.config(bg=BG_CARD), l.config(bg=BG_CARD)))
                    w.bind("<Leave>", lambda e, r=row, l=lbl: (r.config(bg=BG_MAIN), l.config(bg=BG_MAIN)))
                    w.bind("<Button-1>",
                           lambda e, n=item_name, wp=wired, wl=wireless, p=cfg_abs:
                           self._do_preset_flash(n, wp, wl, p))

        def _update_scrollregion():
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=(0, 0, bbox[2], bbox[3]))

        def _close():
            """Close this accordion section (used by _switch_tab to reset state)."""
            if is_open[0]:
                is_open[0] = False
                items_frame.pack_forget()
                arrow.config(text="▶")
                canvas.after(1, _update_scrollregion)

        def _toggle(e=None):
            is_open[0] = not is_open[0]
            if is_open[0]:
                items_frame.pack(fill="x")
                arrow.config(text="▼")
            else:
                items_frame.pack_forget()
                arrow.config(text="▶")
            canvas.after(1, _update_scrollregion)

        # Register close callback so the tab reset can collapse all sections
        if hasattr(self, "_accordion_closers"):
            self._accordion_closers.append(_close)

        def _scroll(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")

        def _scroll_up(e):
            canvas.yview_scroll(-1, "units")

        def _scroll_down(e):
            canvas.yview_scroll(1, "units")

        # Forward scroll from every widget in the section up to the canvas
        for w in (section, items_frame, hdr, arrow) + tuple(hdr.winfo_children()):
            w.bind("<MouseWheel>", _scroll)
            w.bind("<Button-4>",   _scroll_up)
            w.bind("<Button-5>",   _scroll_down)

        # Toggle binding only on header widgets (not section/items_frame)
        for w in (hdr, arrow) + tuple(hdr.winfo_children()):
            w.bind("<Button-1>", _toggle)

    def _do_preset_flash(self, preset_name, wired_path, wireless_path, preset_cfg_path):
        """Wired/wireless popup → flash firmware → XInput boot → config mode → apply preset → save."""
        drive = find_rpi_rp2_drive()
        if not drive:
            return

        choice = _ask_wired_or_wireless(self.root,
                                        has_wired=bool(wired_path),
                                        has_wireless=bool(wireless_path))
        if not choice:
            return
        uf2_path = wired_path if choice == "wired" else wireless_path
        if not uf2_path:
            return

        # ── Progress popup ────────────────────────────────────────────
        dlg = tk.Toplevel(self.root)
        dlg.title("Installing Preset")
        dlg.configure(bg=BG_CARD)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # block close during install

        dlg_frame = tk.Frame(dlg, bg=BG_CARD)
        dlg_frame.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(dlg_frame, text=f"Installing: {preset_name}",
                 bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", pady=(0, 12))

        status_var = tk.StringVar(value="Starting…")
        status_lbl = tk.Label(dlg_frame, textvariable=status_var,
                              bg=BG_CARD, fg=ACCENT_BLUE,
                              font=(FONT_UI, 9), anchor="w", wraplength=1100, justify="left")
        status_lbl.pack(anchor="w", pady=(0, 6))

        detail_var = tk.StringVar(value="")
        tk.Label(dlg_frame, textvariable=detail_var,
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=(FONT_UI, 8), anchor="w", wraplength=1100, justify="left").pack(anchor="w")

        close_btn = RoundedButton(dlg_frame, text="Close", command=dlg.destroy,
                                  bg_color="#555560", btn_width=100, btn_height=30,
                                  btn_font=(FONT_UI, 8, "bold"))
        close_btn.pack(side="right", pady=(16, 0))
        close_btn.set_state("disabled")

        dlg.update_idletasks()
        req_w = int(dlg.winfo_reqwidth() * 2.5)
        req_h = int(dlg.winfo_reqheight() * 1.4)
        px = self.root.winfo_rootx()
        py = self.root.winfo_rooty()
        pw = self.root.winfo_width()
        ph = self.root.winfo_height()
        dlg.geometry(f"{req_w}x{req_h}+{px + (pw - req_w) // 2}+{py + (ph - req_h) // 2}")
        dlg.grab_set()

        def set_status(msg, detail="", color=ACCENT_BLUE):
            status_var.set(msg)
            detail_var.set(detail)
            status_lbl.config(fg=color)
            dlg.update_idletasks()

        def fail(msg, detail=""):
            def _f():
                self._busy = False
                set_status(msg, detail, ACCENT_RED)
                close_btn.set_state("normal")
                dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
            self.root.after(0, _f)

        def succeed(msg, detail=""):
            def _f():
                self._busy = False
                set_status(msg, detail, ACCENT_GREEN)
                close_btn.set_state("normal")
                dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
            self.root.after(0, _f)

        self._busy = True

        def worker():
            # ── Step 1 / 5: Flash firmware ────────────────────────
            self.root.after(0, lambda: set_status(
                "Step 1 / 5  —  Flashing firmware…",
                f"Installing firmware for {preset_name}"))
            try:
                flash_uf2_with_reboot(uf2_path, drive)
            except Exception as exc:
                fail("Firmware flash failed.", str(exc))
                return

            # ── Step 2 / 5: Wait for XInput boot ─────────────────
            self.root.after(0, lambda: set_status(
                "Step 2 / 5  —  Waiting for controller to boot…",
                "Up to 30 seconds after firmware loads"))
            xinput_slot = None
            deadline = time.time() + 30.0
            while time.time() < deadline:
                try:
                    connected = xinput_get_connected()
                    occ = [c for c in connected if c[1] in OCC_SUBTYPES]
                    if occ:
                        xinput_slot = occ[0][0]
                        break
                except Exception:
                    pass
                time.sleep(0.75)

            if xinput_slot is None:
                fail("Controller did not appear as an XInput device.",
                     "Firmware was flashed. Apply the preset manually\n"
                     "via Configure Controller → Import Configuration.")
                return

            time.sleep(2.0)   # let Windows fully enumerate

            # ── Step 3 / 5: Enter config mode ────────────────────
            self.root.after(0, lambda: set_status(
                "Step 3 / 5  —  Entering configuration mode…",
                "Sending config signal to controller"))
            try:
                for left, right in MAGIC_STEPS:
                    xinput_send_vibration(xinput_slot, left, right)
                    time.sleep(0.08)
                xinput_send_vibration(xinput_slot, 0, 0)
            except Exception as exc:
                fail("Could not send config mode signal.", str(exc))
                return

            port = None
            deadline = time.time() + 12.0
            while time.time() < deadline:
                port = PicoSerial.find_config_port()
                if port:
                    time.sleep(0.5)
                    break
                time.sleep(0.3)
            if not port:
                fail("Controller did not enter config mode.",
                     "Firmware was flashed. Apply the preset manually\n"
                     "via Configure Controller → Import Configuration.")
                return

            # ── Step 4 / 5: Apply preset config ──────────────────
            self.root.after(0, lambda: set_status(
                "Step 4 / 5  —  Applying preset configuration…",
                f"Sending settings for {preset_name}"))
            try:
                pico = PicoSerial()
                deadline = time.time() + 15.0
                connected_ok = False
                while time.time() < deadline:
                    try:
                        pico.connect(port)
                        connected_ok = True
                        break
                    except PermissionError:
                        self.root.after(0, lambda: set_status(
                            "Step 4 / 5  —  Applying preset configuration…",
                            "Waiting for Windows to release the COM port…"))
                        time.sleep(1.5)
                    except Exception as exc:
                        fail("Could not open config port.", str(exc))
                        return
                if not connected_ok:
                    fail("Config port access denied.", "Try re-plugging the controller.")
                    return

                for _ in range(3):
                    if pico.ping():
                        break
                    time.sleep(0.3)
                else:
                    pico.disconnect()
                    fail("Controller not responding in config mode.")
                    return

                _apply_preset_config(pico, preset_cfg_path)

                # ── Step 5 / 5: Save ──────────────────────────────
                self.root.after(0, lambda: set_status(
                    "Step 5 / 5  —  Saving configuration…",
                    "Writing settings to flash"))
                pico.save()
                pico.reboot()
                pico.disconnect()
            except Exception as exc:
                fail("Failed to apply preset.", str(exc))
                return

            succeed(f"'{preset_name}' preset installed!",
                    "Controller is now in play mode.")

        threading.Thread(target=worker, daemon=True).start()

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

        groups = _group_uf2_files(find_uf2_files())
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

            if idx < len(groups):
                display_name, wired_path, wireless_path = groups[idx]

                # ── GIF: try wired path, then wireless path, then core name ──
                # GIFs may be named after the core firmware name (no Wired_/Wireless_ prefix)
                # e.g. Guitar_Controller.gif instead of Wired_Guitar_Controller.gif
                gif_path = None
                if wired_path:
                    gif_path = self._find_gif_for_uf2(wired_path)
                if not gif_path and wireless_path:
                    gif_path = self._find_gif_for_uf2(wireless_path)
                if not gif_path:
                    gif_path = self._find_gif_for_uf2(display_name.replace(" ", "_") + ".gif")

                img_label = tk.Label(img_area, bg=BG_CARD, cursor="hand2")
                img_label.place(relx=0.5, rely=0.5, anchor="center")

                if gif_path:
                    self._start_gif(img_label, gif_path, img_area)
                else:
                    # No GIF — show a dim placeholder icon
                    img_label.config(text="▶", fg=TEXT_DIM,
                                     font=(FONT_UI, 28))

                # ── Name label below the image ────────────────────
                name_lbl = tk.Label(lbl_area, text=display_name,
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
                def _click(e, wired=wired_path, wireless=wireless_path, dname=display_name):
                    drive = find_rpi_rp2_drive()
                    if not drive:
                        return
                    choice = _ask_wired_or_wireless(self.root, has_wired=bool(wired), has_wireless=bool(wireless))
                    if choice == "wireless":
                        self._do_flash(wireless, drive, "Wireless")
                    elif choice == "wired":
                        self._do_flash(wired, drive, "Wired")

                def _rclick(e, wired=wired_path, wireless=wireless_path, dname=display_name):
                    self._on_tile_right_click(wired, wireless, dname, e.x_root, e.y_root)

                for widget in (img_area, lbl_area, img_label, name_lbl):
                    widget.bind("<Enter>",    _enter)
                    widget.bind("<Leave>",    _leave)
                    widget.bind("<Button-1>", _click)
                    widget.bind("<Button-3>", _rclick)
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

    def _on_tile_right_click(self, wired_path, wireless_path, display_name, x, y):
        """Right-click context menu on a firmware tile — manually pick wired or wireless."""
        drive = find_rpi_rp2_drive()
        if not drive:
            return

        def _flash_wireless():
            # User explicitly picked Wireless from context menu — just flash it
            self._do_flash(wireless_path, drive, "Wireless")

        menu = tk.Menu(self.root, tearoff=0, bg=BG_CARD, fg=TEXT,
                       activebackground=ACCENT_BLUE, activeforeground="white")
        if wired_path:
            menu.add_command(label="Wired",
                             command=lambda: self._do_flash(wired_path, drive, "Wired"))
        else:
            menu.add_command(label="Wired  (not available)", state="disabled")
        if wireless_path:
            menu.add_command(label="Wireless", command=_flash_wireless)
        else:
            menu.add_command(label="Wireless  (not available)", state="disabled")
        menu.tk_popup(x, y)

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

    def _do_flash(self, uf2_path, drive, variant_label="", no_wireless_note=False):
        # Go back to main menu before flashing — prevents stale config screen
        if self._on_back:
            self._on_back()
        # ── 1. Show a non-blocking "please wait" popup ──────────────
        wait_dlg = tk.Toplevel(self.root)
        wait_dlg.title("Flashing Firmware")
        wait_dlg.configure(bg=BG_CARD)
        wait_dlg.resizable(False, False)
        wait_dlg.transient(self.root)
        wait_dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # prevent closing

        if no_wireless_note:
            wait_text = "⚡  Wired Firmware Installing…\nNo wireless version available."
        elif variant_label:
            wait_text = f"⚡  Flashing {variant_label} Firmware…\nplease wait"
        else:
            wait_text = "⚡  Flashing firmware… please wait"

        tk.Label(wait_dlg, text=wait_text,
                 bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11),
                 justify="center", padx=32, pady=28).pack()

        wait_dlg.update_idletasks()
        # Center over parent
        pw = self.root.winfo_width();  ph = self.root.winfo_height()
        px = self.root.winfo_rootx(); py = self.root.winfo_rooty()
        dw = int(wait_dlg.winfo_reqwidth() * 2.5)
        dh = int(wait_dlg.winfo_reqheight() * 1.4)
        wait_dlg.geometry(f"{dw}x{dh}+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
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
            dw = done_dlg.winfo_reqwidth();  dh = done_dlg.winfo_reqheight()
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
        resetFW = find_resetFW_uf2()
        if not resetFW:
            messagebox.showwarning("Missing File",
                                   "resetFW.uf2 not found.\n"
                                   "Place it alongside this exe and try again.")
            return
        if not messagebox.askyesno("Factory Reset",
                                   "This will COMPLETELY ERASE all firmware and "
                                   "settings on the Pico.\n\n"
                                   "Continue?", icon="warning"):
            return
        try:
            flash_uf2(resetFW, drive)
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
            if not self._busy:   # stay on screen during preset install
                self._on_back()
                return
        self._poll_job = self.root.after(self.POLL_MS, self._poll)

    # ── Show / Hide ───────────────────────────────────────────────

    def show(self, drive=None):
        self.root.title("OCC - Firmware Installation")
        # Clear any configurator menu bar left over from App / DrumApp
        self._empty_menu = getattr(self, '_empty_menu', None) or tk.Menu(self.root)
        self.root.config(menu=self._empty_menu)
        self._switch_tab("firmware")
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
