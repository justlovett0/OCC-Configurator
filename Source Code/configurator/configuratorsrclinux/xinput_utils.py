import ctypes
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# XINPUT / PLAY-MODE SHIM
#
# This package keeps the historical xinput_* API so the copied Linux screens
# do not need a wide refactor. On Linux we discover OCC controllers through the
# input/sysfs stack and send the same rumble sequence through EV_FF so firmware
# still sees the expected magic pattern.

ERROR_SUCCESS = 0
ERROR_DEVICE_NOT_CONNECTED = 1167
ERROR_NOT_SUPPORTED = 50

MAGIC_STEPS = [(0x4700, 0x4300), (0x4300, 0x4700), (0x4F00, 0x4B00)]

XINPUT_AVAILABLE = False


def xinput_get_connected():
    return []


def xinput_send_vibration(slot, left, right):
    return ERROR_DEVICE_NOT_CONNECTED


if sys.platform == "win32":
    xinput_dll = None
    for dll_name in ["xinput1_4", "xinput9_1_0", "xinput1_3"]:
        try:
            xinput_dll = ctypes.WinDLL(dll_name)
            XINPUT_AVAILABLE = True
            break
        except OSError:
            continue

    if XINPUT_AVAILABLE:
        class XINPUT_GAMEPAD(ctypes.Structure):
            _fields_ = [
                ("wButtons", ctypes.c_ushort),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short),
            ]

        class XINPUT_STATE(ctypes.Structure):
            _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", XINPUT_GAMEPAD)]

        class XINPUT_VIBRATION(ctypes.Structure):
            _fields_ = [("wLeftMotorSpeed", ctypes.c_ushort), ("wRightMotorSpeed", ctypes.c_ushort)]

        class XINPUT_CAPABILITIES(ctypes.Structure):
            _fields_ = [
                ("Type", ctypes.c_ubyte),
                ("SubType", ctypes.c_ubyte),
                ("Flags", ctypes.c_ushort),
                ("Gamepad", XINPUT_GAMEPAD),
                ("Vibration", XINPUT_VIBRATION),
            ]

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
            return xinput_dll.XInputSetState(
                int(slot),
                ctypes.byref(XINPUT_VIBRATION(int(left), int(right))),
            )

elif sys.platform.startswith("linux"):
    import fcntl

    _XINPUT_VID = 0x045E
    _XINPUT_PID = 0x028E
    _XINPUT_IF_CLASS = 0xFF
    _XINPUT_IF_SUBCLASS = 0x5D
    _OCC_SUBTYPES = {1, 3, 6, 7, 8, 11}

    _EV_FF = 0x15
    _EV_SYN = 0x00
    _SYN_REPORT = 0
    _FF_RUMBLE = 0x50
    _INPUT_EVENT_FORMAT = "llHHi"

    _IOC_NRBITS = 8
    _IOC_TYPEBITS = 8
    _IOC_SIZEBITS = 14
    _IOC_DIRBITS = 2
    _IOC_NRSHIFT = 0
    _IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
    _IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
    _IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
    _IOC_WRITE = 1

    def _IOC(direction, ioc_type, number, size):
        return (
            (direction << _IOC_DIRSHIFT)
            | (ioc_type << _IOC_TYPESHIFT)
            | (number << _IOC_NRSHIFT)
            | (size << _IOC_SIZESHIFT)
        )

    def _IOW(ioc_type, number, size):
        return _IOC(_IOC_WRITE, ord(ioc_type), number, size)

    class _FFTrigger(ctypes.Structure):
        _fields_ = [("button", ctypes.c_uint16), ("interval", ctypes.c_uint16)]

    class _FFReplay(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint16), ("delay", ctypes.c_uint16)]

    class _FFRumble(ctypes.Structure):
        _fields_ = [("strong_magnitude", ctypes.c_uint16), ("weak_magnitude", ctypes.c_uint16)]

    class _FFUnion(ctypes.Union):
        _fields_ = [
            ("rumble", _FFRumble),
            ("_padding", ctypes.c_uint8 * 32),
        ]

    class _FFEffect(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_uint16),
            ("id", ctypes.c_int16),
            ("direction", ctypes.c_uint16),
            ("trigger", _FFTrigger),
            ("replay", _FFReplay),
            ("u", _FFUnion),
        ]

    EVIOCSFF = _IOW("E", 0x80, ctypes.sizeof(_FFEffect))

    @dataclass(frozen=True)
    class _LinuxPlayModeDevice:
        slot: int
        event_name: str
        event_path: Path
        usb_path: Path
        subtype: int
        product_name: str
        serial: str

    _DEVICE_CACHE = []
    _EFFECT_IDS = {}

    def _read_text(path):
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""

    def _read_hex(path):
        raw = _read_text(path)
        if not raw:
            return None
        try:
            return int(raw, 16)
        except ValueError:
            return None

    def _event_sort_key(path):
        match = re.search(r"(\d+)$", path.name)
        return int(match.group(1)) if match else 0

    def _find_usb_parent(path):
        try:
            current = Path(path).resolve()
        except OSError:
            current = Path(path)
        for candidate in (current, *current.parents):
            if (candidate / "idVendor").is_file() and (candidate / "idProduct").is_file():
                return candidate
        return None

    def _infer_subtype(name):
        lowered = (name or "").lower()
        if "6-fret" in lowered or "6 fret" in lowered or "gh live" in lowered:
            return 6
        if "drum" in lowered:
            return 8
        if "arcade" in lowered or "fight stick" in lowered:
            return 3
        if "retro" in lowered or "gamepad" in lowered:
            return 1
        if "dongle" in lowered:
            return 11
        if "guitar" in lowered or "pedal" in lowered:
            return 7
        return None

    def _parse_subtype_from_descriptors(usb_path):
        try:
            data = (usb_path / "descriptors").read_bytes()
        except OSError:
            return None

        offset = 0
        xinput_interface = False
        while offset + 2 <= len(data):
            desc_len = data[offset]
            if desc_len < 2:
                break

            desc_end = offset + desc_len
            if desc_end > len(data):
                break

            desc_type = data[offset + 1]
            desc = data[offset:desc_end]

            if desc_type == 0x04 and desc_len >= 9:
                xinput_interface = (
                    desc[5] == _XINPUT_IF_CLASS and desc[6] == _XINPUT_IF_SUBCLASS
                )
            elif xinput_interface and desc_type == 0x21 and desc_len >= 5:
                subtype = desc[4]
                if subtype in _OCC_SUBTYPES:
                    return subtype

            offset = desc_end

        return None

    def _enumerate_linux_devices():
        devices = []
        sysfs_root = Path("/sys/class/input")
        dev_root = Path("/dev/input")
        if not sysfs_root.is_dir() or not dev_root.is_dir():
            return devices

        for event_entry in sorted(sysfs_root.glob("event*"), key=_event_sort_key):
            event_path = dev_root / event_entry.name
            if not event_path.exists():
                continue

            input_dev = event_entry / "device"
            usb_path = _find_usb_parent(input_dev)
            if usb_path is None:
                continue

            vendor = _read_hex(usb_path / "idVendor")
            product = _read_hex(usb_path / "idProduct")
            if vendor != _XINPUT_VID or product != _XINPUT_PID:
                continue

            product_name = _read_text(usb_path / "product") or _read_text(input_dev / "name")
            subtype = _parse_subtype_from_descriptors(usb_path)
            if subtype is None:
                subtype = _infer_subtype(product_name)
            if subtype not in _OCC_SUBTYPES:
                continue

            devices.append(
                _LinuxPlayModeDevice(
                    slot=len(devices),
                    event_name=event_entry.name,
                    event_path=event_path,
                    usb_path=usb_path,
                    subtype=subtype,
                    product_name=product_name or event_entry.name,
                    serial=_read_text(usb_path / "serial"),
                )
            )

        return devices

    def _refresh_devices():
        global _DEVICE_CACHE
        devices = _enumerate_linux_devices()
        _DEVICE_CACHE = devices
        return devices

    def _device_for_slot(slot):
        try:
            slot_index = int(slot)
        except (TypeError, ValueError):
            return None

        devices = _refresh_devices()
        if 0 <= slot_index < len(devices):
            return devices[slot_index]
        return None

    def _send_rumble(device, left, right):
        flags = os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC

        try:
            fd = os.open(str(device.event_path), flags)
        except OSError:
            return False

        try:
            effect = _FFEffect()
            effect.type = _FF_RUMBLE
            effect.id = _EFFECT_IDS.get(str(device.event_path), -1)
            effect.direction = 0
            effect.trigger.button = 0
            effect.trigger.interval = 0
            effect.replay.length = 80
            effect.replay.delay = 0
            effect.u.rumble.strong_magnitude = max(0, min(0xFFFF, int(left)))
            effect.u.rumble.weak_magnitude = max(0, min(0xFFFF, int(right)))

            buf = bytearray(ctypes.string_at(ctypes.addressof(effect), ctypes.sizeof(effect)))
            fcntl.ioctl(fd, EVIOCSFF, buf, True)
            effect = _FFEffect.from_buffer_copy(bytes(buf))
            _EFFECT_IDS[str(device.event_path)] = effect.id

            os.write(fd, struct.pack(_INPUT_EVENT_FORMAT, 0, 0, _EV_FF, effect.id, 1))
            os.write(fd, struct.pack(_INPUT_EVENT_FORMAT, 0, 0, _EV_SYN, _SYN_REPORT, 0))
            return True
        except OSError:
            return False
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    XINPUT_AVAILABLE = Path("/sys/class/input").is_dir() and Path("/dev/input").is_dir()

    def xinput_get_connected():
        if not XINPUT_AVAILABLE:
            return []
        return [(device.slot, device.subtype) for device in _refresh_devices()]

    def xinput_send_vibration(slot, left, right):
        if not XINPUT_AVAILABLE:
            return ERROR_NOT_SUPPORTED

        device = _device_for_slot(slot)
        if device is None:
            return ERROR_DEVICE_NOT_CONNECTED

        return ERROR_SUCCESS if _send_rumble(device, left, right) else ERROR_NOT_SUPPORTED
