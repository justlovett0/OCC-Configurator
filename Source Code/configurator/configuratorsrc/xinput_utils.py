import sys


ERROR_SUCCESS = 0
ERROR_DEVICE_NOT_CONNECTED = 1167
ERROR_NOT_SUPPORTED = 50
MAGIC_STEPS = [(0x4700, 0x4300), (0x4300, 0x4700), (0x4F00, 0x4B00)]

XINPUT_AVAILABLE = False


def xinput_get_connected():
    return []


def xinput_send_vibration(_slot, _left, _right):
    return ERROR_DEVICE_NOT_CONNECTED


if sys.platform == "win32":
    from ._xinput_backend_windows import (  # noqa: F401
        XINPUT_AVAILABLE,
        xinput_get_connected,
        xinput_send_vibration,
    )
elif sys.platform.startswith("linux"):
    from ._xinput_backend_linux import (  # noqa: F401
        XINPUT_AVAILABLE,
        xinput_get_connected,
        xinput_send_vibration,
    )

