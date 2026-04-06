import string
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
GITHUB_REPO   = "justlovett0/OCC-Configurator"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
#  CONSTANTS


CONFIG_MODE_VID = 0x2E8A

# All config-mode PIDs recognised by this configurator.
# Add a new entry here whenever a new firmware variant is created.
# Key = PID (int), Value = human-readable device label shown in port list.
CONFIG_MODE_PIDS = {
    0xF00D: "Guitar Config",
    0xF00E: "Drum Kit Config",
    0xF00F: "Retro Gamepad Config",
    0xF010: "Pedal Config",
    0xF011: "Keyboard Macro Config",
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
NUKE_UF2_FILENAME = "resetFW.uf2"

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
    "pico_retro":              "retro",
}

# Maps XInput subtype → DEVTYPE string (used before serial connection is open)
XINPUT_SUBTYPE_TO_DEVTYPE = {
    8: "drum_kit",
    6: "guitar_alternate",
    7: "guitar_alternate",
    11: "dongle",           # Dongle uses subtype 0x0B=11 (XINPUT_DEVSUBTYPE_GUITAR_BASS)
    1: "pico_retro",        # Retro Gamepad uses subtype 0x01 (XINPUT_DEVSUBTYPE_GAMEPAD)
}

# All XInput subtypes recognised as OCC devices.
# Used when scanning for controllers without a serial connection.
OCC_SUBTYPES = {8, 6, 7, 11, 1}   # Drum Kit (8), Guitar (6/7), Dongle (11=0x0B), Retro Gamepad (1)

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
LED_INPUT_COUNT = 14

VALID_NAME_CHARS = set(string.ascii_letters + string.digits + ' ')

LED_INPUT_NAMES = [
    "green", "red", "yellow", "blue", "orange",
    "strum_up", "strum_down", "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "guide",
]

LED_INPUT_LABELS = [
    "Green Fret", "Red Fret", "Yellow Fret", "Blue Fret", "Orange Fret",
    "Strum Up", "Strum Down", "Start", "Select",
    "D-Pad Up", "D-Pad Down", "D-Pad Left", "D-Pad Right",
    "Guide",
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
