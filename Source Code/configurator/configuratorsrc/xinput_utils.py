import sys, ctypes
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

