import sys, os, time, threading, json
import tkinter as tk
from tkinter import messagebox, filedialog
from .constants import (BG_MAIN, BG_CARD, BG_INPUT, BG_HOVER, BORDER, TEXT, TEXT_DIM,
                         TEXT_HEADER, ACCENT_BLUE, ACCENT_GREEN, ACCENT_RED, ACCENT_ORANGE,
                         CONFIG_MODE_VID, CONFIG_MODE_PIDS, ALTERNATEFW_VID, ALTERNATEFW_PID,
                         GP2040CE_VID, GP2040CE_PID, GP2040CE_WEBCONFIG_IP,
                         GP2040CE_BOOTMODE_BOOTSEL, XINPUT_SUBTYPE_TO_DEVTYPE,
                         OCC_SUBTYPES, DONGLE_XINPUT_SUBTYPES, MAX_LEDS,
                         get_led_input_names_for_device_type,
                         _ALTERNATEFW_CMD_JUMP_BOOTLOADER, _ALTERNATEFW_BM_REQUEST_TYPE)
from .fonts import FONT_UI, APP_VERSION
from .widgets import RoundedButton, CustomDropdown, HelpDialog, HelpButton, _help_text, _help_placeholder
from .serial_comms import PicoSerial
from .firmware_utils import (find_rpi_rp2_drive, find_rpi_rp2_drive_info,
                              get_bundled_fw_date, get_bundled_fw_date_str, parse_fw_date,
                              flash_uf2, flash_uf2_with_reboot, enter_bootsel_for,
                              find_uf2_files, find_resetFW_uf2,
                              find_uf2_for_device_type)
from .xinput_utils import XINPUT_AVAILABLE, xinput_get_connected, MAGIC_STEPS, xinput_send_vibration, ERROR_SUCCESS
from .utils import _centered_dialog, _center_window, _find_preset_configs

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
        self._probing_ctrl = False        # background serial probe in flight
        self._factory_reset_in_progress = False  # suppress flash screen during factory reset
        self._flash_screen_job = None           # delayed auto-open from firmware card
        # BOOTSEL debounce: drive must be seen for this many consecutive polls
        # before we switch screens.  POLL_MS=1000ms so 2 polls = ~2s minimum.
        self._bootsel_stable_count = 0
        self._BOOTSEL_STABLE_NEEDED = 2   # polls required (~2s at 1000ms each)
        # Alternatefw one-time popup: shown at most once per session
        self._alternatefw_popup_shown = False
        # GP2040-CE one-time popup: shown at most once per session
        self._gp2040ce_popup_shown = False
        self._help_dialog = None

        self.frame = tk.Frame(root, bg=BG_MAIN)

        self._build()
        # poll starts in show() via after(50, self._poll) — don't call here or
        # the job it schedules gets orphaned when show() overwrites _poll_job

    def _open_help(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self.root, [
                ("Getting Started",       _help_text(
                    ("Welcome to OCC, Open Controller Configurator!", "bold"),
                    ("\n\n", None),
                    ("This program is loaded with firmwares made for the Raspberry Pi Pico and Pico W. It comes bundled with a configurator screen to set up your button inputs and other settings for game controllers and peripherals.", None),
                    ("\n\n", None),
                    ("Check out the other tabs in this help menu for more information about the functions of this Main Menu screen.", None),
                    ("\n\n", None),
                    ("OCC was made by LovettCustoms as a free, open source, alternative option for Rythm Controllers, Game Controllers, and Peripherals for anyone to use for any purpose.", None),
                    ("You do not need a license or need to pay me to sell products with my firmware. Enjoy.", None),
                    ("\n\n", None),
                    ("Special thanks to roadsidebomb of threepieces.net for inspiring me to make this project.", "italic"),
                    ("\n\n", None),
                    ("Also check out my website, LovettCustoms.com. Thanks!", None),
                )),
                ("Connecting a Device",   _help_text(
                    ("If a Pico is detected in BOOTSEL mode,", "bold"),
                    ("OCC should automatically switch to the firmware selection screen.", None),
                    ("\n", None),
                    ("If OCC detects a firmware already installed,", "bold"),
                    ("You'll see the options to check for firmware updates and go into configuration screens.", None),
                    ("\n", None),
                    ("Check the Configuration Screens help tab for more information about Easy vs Advanced configurator.", None),
                )),
                ("Configuration Screens", _help_text(
                    ("Easy Configurator", "bold"),
                    ("Will walk you through the process of binding buttons of your controller one by one. It'll show you a screen to detect each button press, and at the end allow you to save your controller configuration. Simple!", None),
                    ("\n", None),
                    ("Advanced Configurator", "bold"),
                    ("Will show you all options at once. It is a much denser menu that still lets you assign each button to a pin on your Pico, but it will not walk you through the process.", None),
                )),
            ])
        self._help_dialog.open()

    # ── Layout ────────────────────────────────────────────────────

    def _build(self):
        # ── Title bar ────────────────────────────────────────
        title_bar = tk.Frame(self.frame, bg=BG_CARD,
                             highlightbackground=BORDER, highlightthickness=1)
        title_bar.pack(fill="x", padx=0, pady=(0, 16))

        inner_title = tk.Frame(title_bar, bg=BG_CARD)
        inner_title.pack(fill="x", padx=24, pady=16)

        HelpButton(inner_title, command=self._open_help).pack(side="right", anchor="n", pady=4)
        tk.Label(inner_title, text="OCC",
                 bg=BG_CARD, fg=TEXT_HEADER,
                 font=(FONT_UI, 18, "bold")).pack(anchor="w")
        tk.Label(inner_title, text="Open Controller Configurator",
                 bg=BG_CARD, fg=ACCENT_BLUE,
                 font=(FONT_UI, 13)).pack(anchor="w")
        if APP_VERSION != "dev":
            tk.Label(inner_title, text=f"v{APP_VERSION}",
                     bg=BG_CARD, fg=TEXT_DIM,
                     font=(FONT_UI, 8)).pack(anchor="e")

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
            if self._bootsel_stable_count >= self._BOOTSEL_STABLE_NEEDED \
                    and self._on_flash_screen \
                    and not self._factory_reset_in_progress:
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
            # Skip opening the serial port while a background worker owns it,
            # or while a probe is already in flight.
            if not self._backup_in_progress and not self._probing_ctrl:
                self._probing_ctrl = True
                def _probe(captured_port=port):
                    try:
                        ps = PicoSerial()
                        ps.connect(captured_port)
                        cfg = ps.get_config()
                        ps.disconnect()
                        name  = cfg.get("device_name", "Controller")
                        dtype = cfg.get("device_type", "unknown")
                    except Exception:
                        name, dtype = "Controller", "unknown"
                    finally:
                        self._probing_ctrl = False
                    self.root.after(0, lambda n=name, d=dtype, p=captured_port:
                        self._apply_ctrl_status(n, d, p))
                threading.Thread(target=_probe, daemon=True).start()
            # UI update arrives via _apply_ctrl_status callback; nothing to do here
            return
        else:
            # Check for XInput controller
            has_xinput = False
            self._xinput_count = 0
            self._xinput_device_label = "Controller"
            if XINPUT_AVAILABLE:
                try:
                    controllers = xinput_get_connected()
                    SUBTYPE_LABELS = {8: "Drum Kit", 6: "6-Fret Guitar", 7: "Standard Guitar", 5: "Dongle"}
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
                        subtype = config_devices[0][1]
                        EASY_CONFIG_SUBTYPES = {7}  # standard guitar only
                        has_easy = subtype in EASY_CONFIG_SUBTYPES
                        detail = (
                            "Click either Configure option to switch to Config Mode."
                            if has_easy else
                            "No Easy Configurator for this device yet.  "
                            "Click Advanced Configuration to switch to Config Mode."
                        )
                        self._ctrl_detail.config(text=detail, fg=TEXT_DIM)
                        self._cfg_btn.set_state("normal")
                        self._easy_cfg_btn.set_state("normal" if has_easy else "disabled")
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

    def _apply_ctrl_status(self, name, dtype, port):
        """Apply serial probe result to the controller card. Runs on main thread."""
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
            self._ctrl_detail.config(
                text=f"Guitar for Dongle  ·  Config mode  ·  {port}", fg=TEXT_DIM)
            self._cfg_btn.set_state("normal")
            self._easy_cfg_btn.set_state("normal")
        elif dtype == "guitar_combined":
            self._ctrl_detail.config(
                text=f"Guitar (Combined)  ·  Config mode  ·  {port}", fg=TEXT_DIM)
            self._cfg_btn.set_state("normal")
            self._easy_cfg_btn.set_state("normal")
        elif dtype == "guitar_live_6fret":
            self._ctrl_detail.config(
                text=f"6-Fret Guitar  ·  Config mode  ·  {port}  ·  No Easy Configurator for 6-Fret yet",
                fg=TEXT_DIM)
            self._cfg_btn.set_state("normal")
            self._easy_cfg_btn.set_state("disabled")
        elif dtype == "drum_kit":
            self._ctrl_detail.config(
                text=f"Drum Kit  ·  Config mode  ·  {port}  ·  No Easy Configurator for Drums yet",
                fg=TEXT_DIM)
            self._cfg_btn.set_state("normal")
            self._easy_cfg_btn.set_state("disabled")
        elif dtype == "guitar_alternate":
            self._ctrl_detail.config(
                text=f"Guitar  ·  Config mode  ·  {port}", fg=TEXT_DIM)
            self._cfg_btn.set_state("normal")
            self._easy_cfg_btn.set_state("normal")
        elif dtype == "pedal":
            self._ctrl_detail.config(
                text=f"Pedal Controller  ·  Config mode  ·  {port}", fg=TEXT_DIM)
            self._cfg_btn.set_state("normal")
            self._easy_cfg_btn.set_state("disabled")
        else:
            # Unknown/unhandled type — advanced config only, no easy configurator
            self._ctrl_detail.config(
                text=f"Config mode  ·  {port}  ·  No Easy Configurator for this device yet",
                fg=TEXT_DIM)
            self._cfg_btn.set_state("normal")
            self._easy_cfg_btn.set_state("disabled")
        self._pending_port = port
        self._xinput_count = 0
        self._xinput_dongle_count = 0

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

        # Determine which state device is in, in priority order:
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
        resetFW         = find_resetFW_uf2()

        if drive:
            self._rst_icon.config(text="●", fg=ACCENT_GREEN)
            self._rst_status.config(
                text=f"Pico in USB mode  ·  {drive}", fg=ACCENT_GREEN)
            if resetFW:
                self._rst_detail.config(
                    text="Will use resetFW.uf2 and wipe all storage.",
                    fg=TEXT_DIM)
                self._rst_btn.set_state("normal")
                self._rst_btn._drive = drive
                self._rst_btn._via   = "bootsel"
            else:
                self._rst_detail.config(
                    text="resetFW.uf2 not found — place it alongside this exe.",
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
            if resetFW:
                self._rst_detail.config(
                    text="Will send BOOTSEL command, then wipe storage with resetFW.uf2.",
                    fg=TEXT_DIM)
                self._rst_btn.set_state("normal")
                self._rst_btn._drive       = None
                self._rst_btn._via         = "config"
                self._rst_btn._config_port = config_port
            else:
                self._rst_detail.config(
                    text="resetFW.uf2 not found — place it alongside this exe.",
                    fg=ACCENT_ORANGE)
                self._rst_btn.set_state("disabled")

        elif xinput_count:
            count = xinput_count
            self._rst_icon.config(text="●", fg=ACCENT_GREEN)
            self._rst_status.config(
                text=f"{xinput_label} detected via XInput  ({count} device{'s' if count > 1 else ''})",
                fg=ACCENT_GREEN)
            if resetFW:
                self._rst_detail.config(
                    text="Will send config signal, enter BOOTSEL, then wipe storage with resetFW.uf2.",
                    fg=TEXT_DIM)
                self._rst_btn.set_state("normal")
                self._rst_btn._drive = None
                self._rst_btn._via   = "xinput"
            else:
                self._rst_detail.config(
                    text="resetFW.uf2 not found — place it alongside this exe.",
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
        # Some Alternatefw composite devices use 4 interfaces:
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
            resetFW_path = find_resetFW_uf2()
            if resetFW_path:
                # Update status label so user knows what's happening
                try:
                    self._ctrl_status.config(text="Waiting for RPI-RP2…", fg=ACCENT_ORANGE)
                    self._ctrl_detail.config(
                        text="Will flash resetFW.uf2 automatically when drive appears.", fg=TEXT_DIM)
                except Exception:
                    pass

                def _resetFW_watcher():
                    """Background thread: flash resetFW.uf2 the FIRST time RPI-RP2 appears."""
                    resetFW_flashed = False
                    deadline = time.time() + 30.0   # wait up to 30 s

                    while time.time() < deadline and not resetFW_flashed:
                        drive = find_rpi_rp2_drive()
                        if drive:
                            resetFW_flashed = True   # set flag BEFORE writing so we only try once
                            try:
                                flash_uf2(resetFW_path, drive)
                                self.root.after(0, lambda: _centered_dialog(
                                    self.root,
                                    "Firmware Switcher",
                                    "resetFW.uf2 flashed successfully!\n\n"
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
                                    f"RPI-RP2 found but resetFW.uf2 flash failed:\n{e}",
                                    kind="error"
                                ))
                        else:
                            time.sleep(0.3)

                    if not resetFW_flashed:
                        self.root.after(0, lambda: _centered_dialog(
                            self.root,
                            "Firmware Switcher",
                            "RPI-RP2 drive did not appear within 30 seconds.\n\n"
                            "Try unplugging and re-plugging the Pico while holding BOOTSEL,\n"
                            "then manually copy resetFW.uf2 to the drive.",
                            kind="error"
                        ))

                threading.Thread(target=_resetFW_watcher, daemon=True).start()

            else:
                # resetFW.uf2 not found — fall back to the old informational dialog
                _centered_dialog(
                    self.root,
                    "Firmware Switcher",
                    "BOOTSEL command sent!\n\n"
                    "The device should reappear as an RPI-RP2 drive shortly.\n\n"
                    "Note: resetFW.uf2 was not found alongside this exe, so the\n"
                    "automatic flash step was skipped. Place resetFW.uf2 next to\n"
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
        web configurator HTTP API, then watch for RPI-RP2 and flash resetFW.uf2."""
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
                resetFW_path = find_resetFW_uf2()
                if resetFW_path:
                    try:
                        self._ctrl_status.config(
                            text="Waiting for RPI-RP2…", fg=ACCENT_ORANGE)
                        self._ctrl_detail.config(
                            text="Will flash resetFW.uf2 automatically when drive appears.",
                            fg=TEXT_DIM)
                    except Exception:
                        pass

                    resetFW_flashed = False
                    deadline2 = time.time() + 30.0
                    while time.time() < deadline2 and not resetFW_flashed:
                        drive = find_rpi_rp2_drive()
                        if drive:
                            resetFW_flashed = True
                            try:
                                flash_uf2(resetFW_path, drive)
                                self.root.after(0, lambda: _centered_dialog(
                                    self.root,
                                    "Firmware Switcher",
                                    "resetFW.uf2 flashed successfully!\n\n"
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
                                    f"RPI-RP2 found but resetFW.uf2 flash failed:\n{e}",
                                    kind="error"
                                ))
                        else:
                            time.sleep(0.3)

                    if not resetFW_flashed:
                        self.root.after(0, lambda: _centered_dialog(
                            self.root,
                            "Firmware Switcher",
                            "RPI-RP2 drive did not appear within 30 seconds.\n\n"
                            "Try unplugging and re-plugging the Pico while holding BOOTSEL,\n"
                            "then manually copy resetFW.uf2 to the drive.",
                            kind="error"
                        ))
                else:
                    self.root.after(0, lambda: _centered_dialog(
                        self.root,
                        "Firmware Switcher",
                        "BOOTSEL command sent!\n\n"
                        "The device should reappear as an RPI-RP2 drive shortly.\n\n"
                        "Note: resetFW.uf2 was not found alongside this exe, so the\n"
                        "automatic flash step was skipped. Place resetFW.uf2 next to\n"
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
        if self._flash_screen_job:
            try:
                self._fw_btn_frame.after_cancel(self._flash_screen_job)
            except Exception:
                pass
            self._flash_screen_job = None
        for w in self._fw_btn_frame.winfo_children():
            w.destroy()
        self._flash_btn = None

        if self._factory_reset_in_progress:
            return

        # Route to the dedicated FlashFirmwareScreen instead of flashing inline.
        # Show a "loading" label briefly, then switch screens.
        lbl = tk.Label(self._fw_btn_frame,
                       text="Loading firmware menu, please wait…",
                       bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8))
        lbl.pack()

        def _go():
            self._flash_screen_job = None
            if self._on_flash_screen and not self._factory_reset_in_progress:
                self._on_flash_screen(drive)

        # Small delay so the label is visible before the screen switches
        self._flash_screen_job = self._fw_btn_frame.after(400, _go)

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
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        dlg_frame = tk.Frame(dlg, bg=BG_CARD)
        dlg_frame.pack(fill="both", expand=True, padx=24, pady=(20, 32))

        # Force a minimum dialog width so long status messages aren't clipped
        tk.Frame(dlg_frame, bg=BG_CARD, width=520, height=1).pack()

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

        _center_window(dlg, self.root)
        dlg.grab_set()

        def set_status(msg, detail="", color=ACCENT_BLUE):
            status_var.set(msg)
            detail_var.set(detail)
            status_lbl.config(fg=color)
            # Reset geometry so the window re-fits its content on every update.
            # Without this the window locks to its initial size ("Starting…")
            # and longer messages (e.g. backup file paths) get clipped vertically.
            dlg.geometry("")
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

            # After a fresh flash the Pico always boots into XInput (play) mode
            # first — it does NOT come back in config mode directly.
            # So for both entry paths we need to:
            #   1. Wait for the device to reappear via XInput
            #   2. Send the magic vibration sequence to switch it to config mode
            #   3. Wait for the config-mode serial port
            if via == 'config':
                port2 = None

                if XINPUT_AVAILABLE:
                    # Wait for the controller to reappear as an XInput device
                    xinput_slot2 = None
                    self.root.after(0, lambda: set_status(
                        f"{step_reboot}  —  Waiting for controller to reboot…",
                        "Pico is flashing and rebooting (up to 30s)"))
                    deadline = time.time() + 30.0
                    while time.time() < deadline:
                        try:
                            connected = xinput_get_connected()
                            occ_back = [c for c in connected if c[1] in OCC_SUBTYPES]
                            if occ_back:
                                xinput_slot2 = occ_back[0][0]
                                break
                        except Exception:
                            pass
                        time.sleep(0.75)

                    if xinput_slot2 is not None:
                        self.root.after(0, lambda: set_status(
                            f"{step_reboot}  —  Controller detected, switching to config mode…",
                            "Sending config signal via XInput"))
                        time.sleep(2.0)   # give Windows time to fully enumerate
                        try:
                            for left, right in MAGIC_STEPS:
                                xinput_send_vibration(xinput_slot2, left, right)
                                time.sleep(0.08)
                            xinput_send_vibration(xinput_slot2, 0, 0)
                        except Exception:
                            pass
                        deadline = time.time() + 10.0
                        while time.time() < deadline:
                            port2 = PicoSerial.find_config_port()
                            if port2:
                                time.sleep(0.5)
                                break
                            time.sleep(0.3)

                if not port2:
                    # Fallback: some devices may re-enter config mode on their own
                    # (e.g. if the config button is held), so give it one more chance.
                    deadline = time.time() + 15.0
                    while time.time() < deadline:
                        port2 = PicoSerial.find_config_port()
                        if port2:
                            time.sleep(0.5)
                            break
                        time.sleep(0.3)

                if not port2:
                    fail("Controller did not return to config mode after update.",
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

                for _ in range(5):
                    if pico2.ping():
                        break
                    time.sleep(0.5)
                else:
                    pico2.disconnect()
                    fail("Controller did not respond after update.",
                         f"Backup saved to:\n{backup_path}\n\n"
                         "Import it manually via Configure Controller → Import Configuration.")
                    return

                # Flush any startup chatter the firmware may have sent, then
                # give it a moment to fully initialise before sending SET commands.
                pico2.flush_input()
                time.sleep(1.5)

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
                    led_input_names = get_led_input_names_for_device_type(
                        raw_cfg.get("device_type", "guitar_alternate")
                    )
                    for pair in raw_cfg["led_map_raw"].split(","):
                        pair = pair.strip()
                        if "=" not in pair:
                            continue
                        name_part, rest = pair.split("=", 1)
                        name_part = name_part.strip()
                        if name_part in led_input_names and ":" in rest:
                            idx = led_input_names.index(name_part)
                            hex_mask, bright = rest.split(":", 1)
                            try:
                                pico2.set_value(f"led_map_{idx}", hex_mask.strip())
                                pico2.set_value(f"led_active_{idx}", bright.strip())
                            except Exception:
                                pass

                # save() raises ValueError if it gets anything other than "OK".
                # Retry a few times with a short delay in case the firmware is
                # still processing the last SET command when SAVE arrives.
                save_ok = False
                for _attempt in range(3):
                    try:
                        pico2.save()
                        save_ok = True
                        break
                    except Exception:
                        time.sleep(0.5)
                if not save_ok:
                    pico2.disconnect()
                    fail("Configuration was pushed but could not be saved.",
                         f"Firmware was flashed successfully.\n"
                         f"Backup saved to:\n{backup_path}\n\n"
                         "Import it manually via Configure Controller → Import Configuration.")
                    return
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
        resetFW_path = find_resetFW_uf2()
        if not resetFW_path:
            messagebox.showerror("Factory Reset",
                "resetFW.uf2 not found.\n"
                "Place resetFW.uf2 alongside this exe and try again.")
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
                "Factory Reset.. Are you sure?",
                "This will COMPLETELY ERASE all firmware, data, and settings.\n\n"
                f"File: {os.path.basename(resetFW_path)}\n"
                f"Drive: {drive}\n\n"
                "The Pico will be wiped. You will need to re-flash firmware afterwards.\n\n"
                "Continue?",
                icon="warning")
            if not confirmed:
                return
            try:
                flash_uf2(resetFW_path, drive)
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
            "Factory Reset.. Are you sure?",
            "This will COMPLETELY ERASE all firmware, data, and settings.\n\n"
            f"File: {os.path.basename(resetFW_path)}\n"
            f"Detected via: {source_desc}\n\n"
            "The configurator will switch the Pico to\nBOOTSEL mode automatically, "
            "then flash resetFW.uf2\nto wipe the device.\n\n"
            "You will need to re-flash firmware afterwards.\n\n"
            "Continue?",
            icon="warning")
        if not confirmed:
            return

        self._rst_btn.set_state("disabled")
        self._do_factory_reset_via_device(via, resetFW_path)

    def _do_factory_reset_via_device(self, via, resetFW_path):
        """Run the BOOTSEL → resetFW flow in a background thread with a progress dialog."""

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

        def _handoff_to_flash_screen():
            drive = find_rpi_rp2_drive()
            self._bootsel_stable_count = 0
            self._factory_reset_in_progress = False

            if drive and self._on_flash_screen:
                if self._poll_job:
                    self.root.after_cancel(self._poll_job)
                    self._poll_job = None
                if dlg.winfo_exists():
                    dlg.destroy()
                self._on_flash_screen(drive)
                return

            if dlg.winfo_exists():
                dlg.destroy()

        def finish_ok():
            set_status("✓  Factory reset complete!", "", ACCENT_GREEN)
            close_btn.set_state("normal")
            dlg.protocol("WM_DELETE_WINDOW", _handoff_to_flash_screen)
            self.root.after(0, _handoff_to_flash_screen)

        def finish_err(msg, detail=""):
            self._factory_reset_in_progress = False
            set_status(msg, detail, ACCENT_RED)
            close_btn.set_state("normal")
            dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

        self._factory_reset_in_progress = True
        self._bootsel_stable_count = 0

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

            # ── Flash resetFW.uf2 ────────────────────────────────────────────
            self.root.after(0, lambda: set_status(
                f"{step_n}  —  Flashing resetFW.uf2…",
                f"Writing to {drive}"))
            try:
                flash_uf2(resetFW_path, drive)
            except Exception as exc:
                self.root.after(0, lambda e=exc: finish_err("Flash failed.", str(e)))
                return

            # resetFW.uf2 keeps running after file copy — wait for drive to vanish
            self.root.after(0, lambda: set_status(
                f"{step_n}  —  Waiting for Pico to restart…",
                "ResetFW in progress — do not unplug"))
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if not find_rpi_rp2_drive():
                    break
                time.sleep(0.5)

            # now wait for the fresh BOOTSEL drive to appear
            self.root.after(0, lambda: set_status(
                f"{step_n}  —  Waiting for Pico to restart…",
                "Waiting for fresh boot"))
            deadline = time.time() + 15.0
            while time.time() < deadline:
                if find_rpi_rp2_drive():
                    break
                time.sleep(0.5)

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
        if self._flash_screen_job:
            try:
                self._fw_btn_frame.after_cancel(self._flash_screen_job)
            except Exception:
                pass
            self._flash_screen_job = None
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
        if self._flash_screen_job:
            try:
                self._fw_btn_frame.after_cancel(self._flash_screen_job)
            except Exception:
                pass
            self._flash_screen_job = None
        self.frame.pack_forget()
