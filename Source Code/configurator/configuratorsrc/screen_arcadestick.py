import datetime
import json
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from .constants import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_CARD,
    BG_MAIN,
    BORDER,
    TEXT,
    TEXT_DIM,
    VALID_NAME_CHARS,
)
from .firmware_utils import enter_bootsel_for
from .fonts import FONT_UI
from .serial_comms import PicoSerial
from .utils import _find_preset_configs
from .widgets import CustomDropdown, HelpButton, HelpDialog, RoundedButton, _help_text
from .xinput_utils import ERROR_SUCCESS, MAGIC_STEPS, XINPUT_AVAILABLE, xinput_get_connected, xinput_send_vibration


class ArcadeStickApp:
    DEVICE_TYPE = "pico_arcadestick"
    PIN_OPTIONS = [(-1, "Disabled")] + [(i, f"GPIO {i}") for i in range(28)]
    USB_MODE_OPTIONS = [(0, "XInput (Recommended)"), (1, "HID Gamepad")]
    STICK_MODE_OPTIONS = [(0, "D-Pad"), (1, "Left Stick"), (2, "Right Stick")]
    CONTROL_DEFS = [
        ("pin_up", "Up", "Joystick Up"),
        ("pin_down", "Down", "Joystick Down"),
        ("pin_left", "Left", "Joystick Left"),
        ("pin_right", "Right", "Joystick Right"),
        ("pin_b1", "1P", "X"),
        ("pin_b2", "2P", "Y"),
        ("pin_b3", "3P", "RB"),
        ("pin_b4", "4P", "LB"),
        ("pin_b5", "1K", "A"),
        ("pin_b6", "2K", "B"),
        ("pin_b7", "3K", "RT"),
        ("pin_b8", "4K", "LT"),
        ("pin_start", "Start", "Start / Options"),
        ("pin_select", "Select", "Back / Share"),
        ("pin_guide", "Guide", "Guide / Home / PS"),
        ("pin_l3", "L3", "L3"),
        ("pin_r3", "R3", "R3"),
    ]

    def __init__(self, root, on_back=None):
        self.root = root
        self._on_back = on_back
        self.pico = PicoSerial()
        self.frame = tk.Frame(root, bg=BG_MAIN)
        self._widgets = []
        self._help_dialog = None

        self._status_var = tk.StringVar(value="")
        self.device_name = tk.StringVar(value="Arcade Stick")
        self._usb_mode = tk.IntVar(value=0)
        self._stick_mode = tk.IntVar(value=0)
        self._debounce = tk.IntVar(value=5)
        self._pin_vars = {key: tk.IntVar(value=-1) for key, _, _ in self.CONTROL_DEFS}
        self._pin_mode_a = tk.IntVar(value=-1)
        self._pin_mode_b = tk.IntVar(value=-1)
        self._combos = {}

        self._build_menu()
        self._build_ui()

    def _build_menu(self):
        mb = tk.Menu(self.root, bg=BG_CARD, fg=TEXT, activebackground=ACCENT_BLUE, activeforeground="#fff", bd=0)

        adv = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT, activebackground=ACCENT_BLUE, activeforeground="#fff")
        adv.add_command(label="Enter BOOTSEL Mode", command=self._enter_bootsel)
        adv.add_separator()
        adv.add_command(label="Export Configuration...", command=self._export_config)
        adv.add_command(label="Import Configuration...", command=self._import_config)
        adv.add_separator()
        adv.add_command(label="Exit", command=self._go_back)
        mb.add_cascade(label="Advanced", menu=adv)

        pm = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT, activebackground=ACCENT_BLUE, activeforeground="#fff")
        presets = _find_preset_configs({self.DEVICE_TYPE})
        if presets:
            for display_name, fpath in presets:
                pm.add_command(label=display_name, command=lambda p=fpath: self._import_preset(p))
        else:
            pm.add_command(label="No preset configs found", state="disabled")
        mb.add_cascade(label="Preset Config", menu=pm)

        hm = tk.Menu(mb, tearoff=0, bg=BG_CARD, fg=TEXT, activebackground=ACCENT_BLUE, activeforeground="#fff")
        hm.add_command(label="About", command=self._show_about)
        mb.add_cascade(label="Help", menu=hm)
        self._menubar = mb

    def _build_ui(self):
        outer = self.frame
        outer.configure(bg=BG_MAIN)

        conn = tk.Frame(outer, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        conn.pack(fill="x", padx=12, pady=(8, 6), ipadx=14, ipady=6)
        tk.Label(conn, text="CONNECTION", bg=BG_CARD, fg=ACCENT_BLUE, font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=14, pady=(6, 0))
        

        btn_bar = tk.Frame(conn, bg=BG_CARD)
        btn_bar.pack(fill="x", padx=14)
        self._connect_btn = RoundedButton(btn_bar, text="Connect to Arcade Stick", command=self._connect_clicked, bg_color=ACCENT_BLUE, btn_width=210, btn_height=34)
        self._connect_btn.pack(side="left", padx=(0, 8))
        HelpButton(btn_bar, command=self._open_help).pack(side="right", padx=(0, 4))
        tk.Label(conn, textvariable=self._status_var, bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 9)).pack(anchor="w", padx=14, pady=(8, 6))

        content = tk.Frame(outer, bg=BG_MAIN)
        content.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        left = tk.Frame(content, bg=BG_MAIN)
        right = tk.Frame(content, bg=BG_MAIN)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        self._build_settings_card(left)
        self._build_direction_card(left)
        self._build_attack_card(left, self.CONTROL_DEFS[4:8], "Top Row")
        self._build_attack_card(right, self.CONTROL_DEFS[8:12], "Bottom Row")
        self._build_aux_card(right)

        bottom = tk.Frame(outer, bg=BG_MAIN)
        bottom.pack(fill="x", padx=12, pady=(0, 8))
        RoundedButton(bottom, text="Main Menu", command=self._go_back, bg_color="#555560", btn_width=130, btn_height=32, btn_font=(FONT_UI, 8, "bold")).pack(side="left")
        self._save_btn = RoundedButton(bottom, text="Save & Enter Play Mode", command=self._save_and_reboot, bg_color=ACCENT_GREEN, btn_width=210, btn_height=34)
        self._save_btn.pack(side="right")
        self._save_btn.set_state("disabled")

        self._set_controls_enabled(False)

    def _make_card(self, parent, title, subtitle=None):
        card = tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 12))
        tk.Label(card, text=title, bg=BG_CARD, fg=ACCENT_BLUE, font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
        if subtitle:
            tk.Label(card, text=subtitle, bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8), wraplength=430, justify="left").pack(anchor="w", padx=14, pady=(2, 8))
        body = tk.Frame(card, bg=BG_CARD)
        body.pack(fill="x", padx=14, pady=(0, 12))
        return body

    def _make_pin_row(self, parent, key, primary_label, host_label):
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=primary_label, bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9, "bold"), width=10, anchor="w").pack(side="left")
        tk.Label(row, text=host_label, bg=BG_CARD, fg=TEXT_DIM, font=(FONT_UI, 8), width=18, anchor="w").pack(side="left")
        combo = self._make_combo(row, self._pin_vars[key], self.PIN_OPTIONS, width=16)
        combo.pack(side="right")
        self._combos[key] = combo

    def _make_combo(self, parent, variable, options, width=18):
        display = [label for _, label in options]
        value_to_index = {value: idx for idx, (value, _) in enumerate(options)}
        combo = CustomDropdown(parent, values=display, state="readonly", width=width)
        combo.current(value_to_index.get(variable.get(), 0))

        def _sync_from_var(*_args):
            idx = value_to_index.get(variable.get(), 0)
            combo.current(idx)

        def _sync_to_var(_event=None):
            variable.set(options[combo.current()][0])

        combo.bind("<<ComboboxSelected>>", _sync_to_var)
        variable.trace_add("write", _sync_from_var)
        self._widgets.append(combo)
        return combo

    def _build_settings_card(self, parent):
        body = self._make_card(parent, "SETTINGS", "")

        row = tk.Frame(body, bg=BG_CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="USB Mode", bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9, "bold"), width=16, anchor="w").pack(side="left")
        self._usb_combo = self._make_combo(row, self._usb_mode, self.USB_MODE_OPTIONS, width=22)
        self._usb_combo.pack(side="right")

        row = tk.Frame(body, bg=BG_CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Joystick Output", bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9, "bold"), width=16, anchor="w").pack(side="left")
        self._stick_combo = self._make_combo(row, self._stick_mode, self.STICK_MODE_OPTIONS, width=22)
        self._stick_combo.pack(side="right")

        row = tk.Frame(body, bg=BG_CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Mode Switch A", bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9, "bold"), width=16, anchor="w").pack(side="left")
        self._mode_a_combo = self._make_combo(row, self._pin_mode_a, self.PIN_OPTIONS, width=22)
        self._mode_a_combo.pack(side="right")

        row = tk.Frame(body, bg=BG_CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Mode Switch B", bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9, "bold"), width=16, anchor="w").pack(side="left")
        self._mode_b_combo = self._make_combo(row, self._pin_mode_b, self.PIN_OPTIONS, width=22)
        self._mode_b_combo.pack(side="right")

        row = tk.Frame(body, bg=BG_CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Device Name", bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9, "bold"), width=16, anchor="w").pack(side="left")
        self._name_entry = tk.Entry(row, textvariable=self.device_name, bg="#38383c", fg=TEXT, insertbackground=TEXT, relief="flat", width=24)
        self._name_entry.pack(side="right")
        self._widgets.append(self._name_entry)

        row = tk.Frame(body, bg=BG_CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Debounce (ms)", bg=BG_CARD, fg=TEXT, font=(FONT_UI, 9, "bold"), width=16, anchor="w").pack(side="left")
        self._debounce_spin = tk.Spinbox(row, from_=0, to=255, textvariable=self._debounce, width=8, bg="#38383c", fg=TEXT, insertbackground=TEXT, relief="flat")
        self._debounce_spin.pack(side="right")
        self._widgets.append(self._debounce_spin)

    def _build_direction_card(self, parent):
        body = self._make_card(parent, "DIRECTIONS", "")
        for key, primary, host in self.CONTROL_DEFS[:4]:
            self._make_pin_row(body, key, primary, host)

    def _build_attack_card(self, parent, defs, title):
        body = self._make_card(parent, title, "")
        for key, primary, host in defs:
            self._make_pin_row(body, key, primary, host)

    def _build_aux_card(self, parent):
        body = self._make_card(parent, "AUX BUTTONS", "")
        for key, primary, host in self.CONTROL_DEFS[12:]:
            self._make_pin_row(body, key, primary, host)

    def _open_help(self):
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self.root, [
                ("Arcade Stick", _help_text(
                    ("This screen configures the OCC arcade-stick firmware.", "bold"),
                    ("\n\n", None),
                    ("The eight main buttons are labelled with fightstick-first names (1P-4P and 1K-4K). The host mapping shown beside them is the default XInput layout.", None),
                    ("\n\n", None),
                    ("XInput mode can be switched into config mode from Windows automatically. HID mode uses the Start + Select + Guide boot shortcut to enter config mode.", None),
                )),
                ("Stick Mode", _help_text(
                    ("Joystick output mode", "bold"),
                    ("\n\n", None),
                    ("D-Pad is the default for many fightsticks, while some games expect Left Stick or Right Stick. You can save a default and optionally wire a physical DP/LS/RS selector using the two Mode Switch pins.", None),
                    ("\n\n", None),
                    ("When both opposite directions are pressed at once, the firmware resolves that axis to neutral.", None),
                )),
            ])
        self._help_dialog.open()

    def _set_status(self, text, color=TEXT_DIM):
        self._status_var.set(text)

    def _set_controls_enabled(self, enabled):
        state = "readonly" if enabled else "disabled"
        for combo in self._widgets:
            try:
                if isinstance(combo, CustomDropdown):
                    combo.configure(state=state)
                else:
                    combo.configure(state="normal" if enabled else "disabled")
            except Exception:
                pass
        self._save_btn.set_state("normal" if enabled else "disabled")

    def show(self):
        self.root.title("OCC - Arcade Stick Configurator")
        self.root.config(menu=self._menubar)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.frame.pack(fill="both", expand=True)

    def hide(self):
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
            self.pico.disconnect()
        self.frame.pack_forget()

    def _wait_for_port(self, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            port = PicoSerial.find_config_port()
            if port:
                return port
            time.sleep(0.2)
        return None

    def _connect_clicked(self):
        if self.pico.connected:
            self.pico.reboot()
            self.pico.disconnect()
            self._set_controls_enabled(False)
            self._set_status("Disconnected")
            return

        port = PicoSerial.find_config_port()
        if port:
            self._connect_serial(port)
        else:
            self._connect_xinput()

    def _connect_serial(self, port):
        try:
            self.pico.connect(port)
            for _ in range(5):
                if self.pico.ping():
                    break
                time.sleep(0.2)
            cfg = self.pico.get_config()
            if cfg.get("device_type") != self.DEVICE_TYPE:
                self.pico.disconnect()
                raise ValueError(f"Wrong device type: {cfg.get('device_type', 'unknown')}")
            self._load_config(cfg)
            self._set_controls_enabled(True)
            self._set_status(f"Connected on {port}")
        except Exception as exc:
            self._set_status(f"Connection failed: {exc}")
            try:
                self.pico.disconnect()
            except Exception:
                pass

    def _connect_xinput(self):
        if not XINPUT_AVAILABLE:
            messagebox.showwarning("XInput Unavailable", "No XInput support is available. Put the controller in config mode with the boot shortcut and connect again.")
            return
        controllers = xinput_get_connected()
        if not controllers:
            messagebox.showwarning("No Controllers", "No XInput controllers were detected. If the arcade stick is in HID mode, hold Start + Select + Guide while plugging it in to enter config mode.")
            return

        self._set_status("Sending config signal over XInput...")
        slot = controllers[0][0]
        try:
            for left, right in MAGIC_STEPS:
                xinput_send_vibration(slot, left, right)
                time.sleep(0.08)
            xinput_send_vibration(slot, 0, 0)
        except Exception as exc:
            self._set_status(f"XInput signal failed: {exc}")
            return

        port = self._wait_for_port(10.0)
        if not port:
            self._set_status("Config mode timed out")
            messagebox.showwarning("Timeout", "The arcade stick did not switch to config mode. Close any game using the controller and try again.")
            return
        time.sleep(0.4)
        self._connect_serial(port)

    def _load_config(self, cfg):
        for key, _, _ in self.CONTROL_DEFS:
            self._pin_vars[key].set(int(cfg.get(key, -1)))
        self._pin_mode_a.set(int(cfg.get("pin_mode_a", -1)))
        self._pin_mode_b.set(int(cfg.get("pin_mode_b", -1)))
        self._usb_mode.set(int(cfg.get("usb_mode", 0)))
        self._stick_mode.set(int(cfg.get("stick_mode", 0)))
        self._debounce.set(int(cfg.get("debounce", 5)))
        self.device_name.set(cfg.get("device_name", "Arcade Stick") or "Arcade Stick")

    def _filtered_name(self):
        raw = self.device_name.get().strip()
        allowed = VALID_NAME_CHARS.union({"-", "_"})
        cleaned = "".join(ch for ch in raw if ch in allowed)
        return cleaned[:20]

    def _config_payload(self):
        payload = {key: str(var.get()) for key, var in self._pin_vars.items()}
        payload["pin_mode_a"] = str(self._pin_mode_a.get())
        payload["pin_mode_b"] = str(self._pin_mode_b.get())
        payload["usb_mode"] = str(self._usb_mode.get())
        payload["stick_mode"] = str(self._stick_mode.get())
        payload["debounce"] = str(self._debounce.get())
        payload["device_name"] = self._filtered_name()
        return payload

    def _push_config(self, payload):
        for key, value in payload.items():
            self.pico.set_value(key, value)

    def _save_and_reboot(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected", "Connect to the arcade stick before saving.")
            return
        try:
            self._push_config(self._config_payload())
            self.pico.save()
            self._set_status("Saved - rebooting to play mode...")
            self.root.update_idletasks()
            time.sleep(0.4)
            self.pico.reboot()
            self.pico.disconnect()
            self._set_status("Saved. Returning to main menu...")
            self._set_controls_enabled(False)
            if self._on_back:
                self.hide()
                self._on_back()
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    def _export_config(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected", "Connect to the arcade stick before exporting.")
            return
        date_str = datetime.datetime.now().strftime("%m-%d-%Y")
        default_name = f"{self._filtered_name() or 'Arcade Stick'} {date_str}"
        path = filedialog.asksaveasfilename(
            title="Export Arcade Stick Configuration",
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            cfg = self.pico.get_config()
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(cfg, handle, indent=2)
            messagebox.showinfo("Export Successful", f"Configuration exported to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _apply_config_dict(self, cfg):
        errors = []
        for key, value in cfg.items():
            if key == "device_type":
                continue
            try:
                self.pico.set_value(key, value)
            except Exception as exc:
                errors.append(f"{key}: {exc}")
        return errors

    def _import_config(self):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected", "Connect to the arcade stick before importing.")
            return
        path = filedialog.askopenfilename(title="Import Arcade Stick Configuration", filetypes=[("JSON config", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                cfg = json.load(handle)
        except Exception as exc:
            messagebox.showerror("Import Error", f"Could not read file:\n{exc}")
            return

        errors = self._apply_config_dict(cfg)
        if errors:
            messagebox.showwarning("Import Partial", "\n".join(errors[:10]))
        else:
            self._load_config(self.pico.get_config())
            messagebox.showinfo("Import Successful", "Configuration imported into the connected arcade stick.")

    def _import_preset(self, filepath):
        if not self.pico.connected:
            messagebox.showwarning("Not Connected", "Connect to the arcade stick before loading a preset.")
            return
        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                cfg = json.load(handle)
        except Exception as exc:
            messagebox.showerror("Preset Error", f"Could not read preset:\n{exc}")
            return
        errors = self._apply_config_dict(cfg)
        if errors:
            messagebox.showwarning("Preset Partial", "\n".join(errors[:10]))
        else:
            self._load_config(self.pico.get_config())
            messagebox.showinfo("Preset Loaded", "Preset applied to the connected arcade stick.")

    def _enter_bootsel(self):
        enter_bootsel_for(self)

    def _show_about(self):
        messagebox.showinfo("About", "OCC Arcade Stick Configurator\nTournament-standard arcade-stick mapping for OCC firmware.")

    def _go_back(self):
        if self._on_back:
            self._on_back()

    def _on_close(self):
        if self.pico.connected:
            try:
                self.pico.reboot()
            except Exception:
                pass
            self.pico.disconnect()
        self.root.destroy()
