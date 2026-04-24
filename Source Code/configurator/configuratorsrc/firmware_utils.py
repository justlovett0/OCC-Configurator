import sys, os, time, struct, ctypes, json, shutil, datetime, string
from tkinter import messagebox
from .constants import (NUKE_UF2_FILENAME, DEVICE_TYPE_UF2_HINTS,
                         CONFIG_MODE_VID, CONFIG_MODE_PIDS, MAX_LEDS,
                         PEDAL_LED_INPUT_NAMES, get_led_input_names_for_device_type,
                         ACCENT_BLUE, ACCENT_RED, ACCENT_ORANGE)
from .xinput_utils import (XINPUT_AVAILABLE, xinput_get_connected,
                             xinput_send_vibration, MAGIC_STEPS)
from .utils import CONTROLLER_SIGNAL_LABEL
#  UF2 FLASHING


def find_uf2_files():
    found = {}
    search_dirs = []
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir:
        search_dirs.append(bundle_dir)
    # When running from source, look alongside the script and one level up (configurator/)
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(src_dir)
    for d in (script_dir, parent_dir, src_dir):
        if d not in search_dirs:
            search_dirs.append(d)
    for d in search_dirs:
        try:
            for f in os.listdir(d):
                if f.lower().endswith('.uf2') and f.lower() != NUKE_UF2_FILENAME.lower():
                    if f not in found:
                        found[f] = os.path.join(d, f)
        except OSError:
            pass
    return sorted(found.items())


def _group_uf2_files(uf2_files):
    """Group wired/wireless UF2 pairs into logical firmware families.

    Strips 'Wired_'/'Wireless_' prefix to find the core name and pair variants.
    Unprefixed files are treated as wired-only.

    Returns list of (display_name, wired_path, wireless_path) in insertion order.
    """
    groups = {}
    order = []
    for fname, path in uf2_files:
        stem = os.path.splitext(fname)[0]
        ls = stem.lower()
        if ls.startswith("wired_"):
            core, variant = stem[6:], "wired"
        elif ls.startswith("wireless_"):
            core, variant = stem[9:], "wireless"
        else:
            core, variant = stem, "wired"
        if core not in groups:
            groups[core] = {"wired": None, "wireless": None}
            order.append(core)
        groups[core][variant] = path
    return [(c.replace("_", " "), groups[c]["wired"], groups[c]["wireless"]) for c in order]


def load_fw_presets():
    """Load ControllerFWPresets.json. Returns (dict, base_dir) or ({}, None)."""
    filename = "ControllerFWPresets.json"
    candidates = []
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir:
        candidates.append(bundle_dir)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(script_dir)
    candidates.append(os.path.dirname(script_dir))
    for d in candidates:
        path = os.path.join(d, filename)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f), d
            except Exception:
                pass
    return {}, None


def _get_led_input_names_for_config(cfg, led_input_names=None):
    if led_input_names is not None:
        return list(led_input_names)
    device_type = str(cfg.get("device_type", "")).strip()
    if device_type == "pedal":
        return list(PEDAL_LED_INPUT_NAMES)
    return list(get_led_input_names_for_device_type(device_type))


def apply_config_to_pico(pico, cfg, led_input_names=None):
    """Send a config dict to firmware, including exported raw LED fields."""
    skip = {
        "device_type",
        "quick_tune_enabled",
        "led_colors",
        "led_maps",
        "led_active_br",
        "led_colors_raw",
        "led_map_raw",
    }
    errors = []

    for key, val in cfg.items():
        if key in skip:
            continue
        try:
            pico.set_value(key, str(val))
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    colors_raw = cfg.get("led_colors_raw")
    if colors_raw is not None:
        for i, color in enumerate(str(colors_raw).split(",")):
            color = color.strip().upper()
            if i >= MAX_LEDS or len(color) != 6:
                continue
            try:
                pico.set_value(f"led_color_{i}", color)
            except Exception as exc:
                errors.append(f"led_color_{i}: {exc}")
    else:
        for i, color in enumerate(cfg.get("led_colors", [])):
            if i >= MAX_LEDS:
                continue
            try:
                pico.set_value(f"led_color_{i}", str(color).upper())
            except Exception as exc:
                errors.append(f"led_color_{i}: {exc}")

    maps_raw = cfg.get("led_map_raw")
    if maps_raw is not None:
        led_names = _get_led_input_names_for_config(cfg, led_input_names=led_input_names)
        for pair in str(maps_raw).split(","):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, rest = pair.split("=", 1)
            name = name.strip()
            if name not in led_names or ":" not in rest:
                continue
            idx = led_names.index(name)
            hex_mask, bright = rest.split(":", 1)
            try:
                pico.set_value(f"led_map_{idx}", hex_mask.strip().upper())
            except Exception as exc:
                errors.append(f"led_map_{idx}: {exc}")
            try:
                pico.set_value(f"led_active_{idx}", bright.strip())
            except Exception as exc:
                errors.append(f"led_active_{idx}: {exc}")
    else:
        for i, m in enumerate(cfg.get("led_maps", [])):
            try:
                pico.set_value(f"led_map_{i}", f"{int(m):04X}")
            except Exception as exc:
                errors.append(f"led_map_{i}: {exc}")

        for i, b in enumerate(cfg.get("led_active_br", [])):
            try:
                pico.set_value(f"led_active_{i}", str(b))
            except Exception as exc:
                errors.append(f"led_active_{i}: {exc}")

    return errors


def _apply_preset_config(pico, cfg_path):
    """Send all SET commands from a preset JSON to an already-connected PicoSerial."""
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    apply_config_to_pico(pico, cfg)


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


def find_resetFW_uf2():
    """Search for resetFW.uf2 (case-insensitive) alongside the exe/script."""
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


def flash_resetfw_and_wait(resetFW_path, drive_path, status_cb=None):
    """
    Flash resetFW.uf2, then wait for the Pico to finish wiping and return as a
    fresh BOOTSEL drive. Returns the new drive path.
    """
    def _status(msg):
        if status_cb:
            status_cb(msg)

    _status("Flashing resetFW.uf2...")
    flash_uf2(resetFW_path, drive_path)

    _status("Waiting for Pico to restart...")
    disappeared = False
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if not find_rpi_rp2_drive():
            disappeared = True
            break
        time.sleep(0.3)

    if not disappeared:
        raise RuntimeError(
            "resetFW.uf2 was copied, but the Pico did not restart into a "
            "fresh BOOTSEL cycle.")

    _status("Waiting for fresh BOOTSEL drive...")
    new_drive = None
    deadline = time.time() + 15.0
    while time.time() < deadline:
        new_drive = find_rpi_rp2_drive()
        if new_drive:
            break
        time.sleep(0.3)

    if not new_drive:
        raise RuntimeError(
            "resetFW.uf2 was copied, but the Pico did not reappear as a "
            "BOOTSEL drive after reset.")

    time.sleep(0.5)
    return new_drive


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
      • Not connected → send the play-mode magic sequence, wait for CDC port, then BOOTSEL.
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

    if sys.platform == "win32":
        bootsel_prompt = "The controller isn't in Config Mode.\n\nSwitch via XInput then enter BOOTSEL?"
    else:
        bootsel_prompt = "The controller isn't in Config Mode.\n\nSwitch from play mode, then enter BOOTSEL?"

    if not messagebox.askyesno(f"BOOTSEL via {CONTROLLER_SIGNAL_LABEL}", bootsel_prompt):
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
