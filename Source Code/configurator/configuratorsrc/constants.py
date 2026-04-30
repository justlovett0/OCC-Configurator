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

STANDARD_GUITAR_BUTTON_DEFS = [
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

STANDARD_GUITAR_LED_INPUT_NAMES = [
    "green", "red", "yellow", "blue", "orange",
    "strum_up", "strum_down", "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "guide",
]

STANDARD_GUITAR_LED_INPUT_LABELS = [
    "Green Fret", "Red Fret", "Yellow Fret", "Blue Fret", "Orange Fret",
    "Strum Up", "Strum Down", "Start", "Select",
    "D-Pad Up", "D-Pad Down", "D-Pad Left", "D-Pad Right",
    "Guide",
]

SIX_FRET_FRET_COLORS = {
    "white1": "#f2f2f2",
    "black1": "#5050ff",
    "black2": "#7878ff",
    "black3": "#b4b4ff",
    "white2": "#f2f2f2",
    "white3": "#f2f2f2",
}

SIX_FRET_GUITAR_BUTTON_DEFS = [
    ("white1",     "White 1",      "frets"),
    ("white2",     "White 2",      "frets"),
    ("white3",     "White 3",      "frets"),
    ("black1",     "Black 1",      "frets"),
    ("black2",     "Black 2",      "frets"),
    ("black3",     "Black 3",      "frets"),
    ("strum_up",   "Strum Up",     "strum"),
    ("strum_down", "Strum Down",   "strum"),
    ("start",      "Start",        "nav"),
    ("hero_power", "Hero Power",   "nav"),
    ("ghtv",       "GHTV",         "nav2"),
    ("dpad_up",    "D-Pad Up",     "dpad"),
    ("dpad_down",  "D-Pad Down",   "dpad"),
    ("dpad_left",  "D-Pad Left",   "dpad"),
    ("dpad_right", "D-Pad Right",  "dpad"),
    ("guide",      "Guide",        "nav2"),
]

SIX_FRET_GUITAR_LED_INPUT_NAMES = [
    "white1", "white2", "white3", "black1", "black2", "black3",
    "strum_up", "strum_down", "start", "hero_power", "ghtv",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "guide",
]

SIX_FRET_GUITAR_LED_INPUT_LABELS = [
    "White 1", "White 2", "White 3", "Black 1", "Black 2", "Black 3",
    "Strum Up", "Strum Down", "Start", "Hero Power", "GHTV",
    "D-Pad Up", "D-Pad Down", "D-Pad Left", "D-Pad Right",
    "Guide",
]

PEDAL_LED_INPUT_NAMES = [
    "pedal1", "pedal2", "pedal3", "pedal4",
]

PEDAL_LED_INPUT_LABELS = [
    "Pedal 1", "Pedal 2", "Pedal 3", "Pedal 4",
]

DRUM_LED_INPUT_NAMES = [
    "red_drum", "yellow_drum", "blue_drum", "green_drum",
    "yellow_cym", "blue_cym", "green_cym",
    "start", "select",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "foot_pedal",
]

DRUM_LED_INPUT_LABELS = [
    "Red Drum", "Yellow Drum", "Blue Drum", "Green Drum",
    "Yellow Cymbal", "Blue Cymbal", "Green Cymbal",
    "Start", "Select",
    "D-Pad Up", "D-Pad Down", "D-Pad Left", "D-Pad Right",
    "Foot Pedal",
]

DRUM_INPUT_COLORS = {
    "red_drum": "#e74c3c",
    "yellow_drum": "#f1c40f",
    "blue_drum": "#3498db",
    "green_drum": "#2ecc71",
    "yellow_cym": "#d4a017",
    "blue_cym": "#2980b9",
    "green_cym": "#27ae60",
    "foot_pedal": "#d4944a",
}

GUITAR_PROFILE_DEFS = {
    "standard": {
        "title": "Guitar Configurator",
        "device_name": "Guitar Controller",
        "button_defs": STANDARD_GUITAR_BUTTON_DEFS,
        "led_input_names": STANDARD_GUITAR_LED_INPUT_NAMES,
        "led_input_labels": STANDARD_GUITAR_LED_INPUT_LABELS,
        "fret_colors": FRET_COLORS,
        "supported_types": {"guitar_alternate", "guitar_alternate_dongle", "guitar_combined"},
    },
    "six_fret": {
        "title": "6-Fret Guitar Configurator",
        "device_name": "6 Fret Guitar",
        "button_defs": SIX_FRET_GUITAR_BUTTON_DEFS,
        "led_input_names": SIX_FRET_GUITAR_LED_INPUT_NAMES,
        "led_input_labels": SIX_FRET_GUITAR_LED_INPUT_LABELS,
        "fret_colors": SIX_FRET_FRET_COLORS,
        "supported_types": {"guitar_live_6fret"},
    },
}

DEVICE_TYPE_TO_GUITAR_PROFILE = {
    "guitar_alternate": "standard",
    "guitar_alternate_dongle": "standard",
    "guitar_combined": "standard",
    "guitar_live_6fret": "six_fret",
}

XINPUT_SUBTYPE_TO_GUITAR_PROFILE = {
    6: "six_fret",
    7: "standard",
}


def get_guitar_profile_name_for_device_type(device_type):
    return DEVICE_TYPE_TO_GUITAR_PROFILE.get(device_type, "standard")


def get_guitar_profile_for_device_type(device_type):
    return GUITAR_PROFILE_DEFS[get_guitar_profile_name_for_device_type(device_type)]


def get_led_input_names_for_device_type(device_type):
    return list(get_guitar_profile_for_device_type(device_type)["led_input_names"])
GITHUB_REPO   = "justlovett0/OCC-Configurator"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"
#  CONSTANTS


CONFIG_MODE_VID = 0x2E8A
ESP_CONFIG_MODE_VID = 0x303A
ESP_DOWNLOAD_MODE_VID = 0x303A

# All OCC config-mode USB IDs recognised by this configurator.
# Key = (vid, pid), Value = metadata used for port detection and UI labels.
CONFIG_MODE_USB_IDS = {
    (0x2E8A, 0xF00D): {"label": "Guitar Config", "platform": "rp2040"},
    (0x2E8A, 0xF00E): {"label": "Drum Kit Config", "platform": "rp2040"},
    (0x2E8A, 0xF00F): {"label": "Retro Gamepad Config", "platform": "rp2040"},
    (0x2E8A, 0xF010): {"label": "Pedal Config", "platform": "rp2040"},
    (0x2E8A, 0xF011): {"label": "Keyboard Macro Config", "platform": "rp2040"},
    (0x2E8A, 0xF012): {"label": "Arcade Stick Config", "platform": "rp2040"},
    (0x303A, 0x10D1): {"label": "ESP32-S3 Guitar Config", "platform": "esp32s3"},
    (0x303A, 0x10D2): {"label": "ESP32-S3 Wireless Guitar Config", "platform": "esp32s3"},
}

# Back-compat helpers used by older configurator code paths.
CONFIG_MODE_PIDS = {
    pid: meta["label"]
    for (vid, pid), meta in CONFIG_MODE_USB_IDS.items()
    if vid == CONFIG_MODE_VID
}


def get_occ_port_metadata(vid, pid):
    return CONFIG_MODE_USB_IDS.get((vid, pid))


ESP_DOWNLOAD_USB_IDS = {
    (0x303A, 0x1001): {"label": "ESP32-S3 Download Mode", "platform": "esp32s3"},
}


def get_esp_download_metadata(vid, pid):
    return ESP_DOWNLOAD_USB_IDS.get((vid, pid))
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
    "guitar_live_6fret":       "6fret",
    "drum_kit":                "drum",
    "drum_combined":           "drum",
    "dongle":                  "dongle",
    "pedal":                   "pedal",
    "pico_retro":              "retro",
    "pico_arcadestick":        "arcadestick",
    "keyboard_macro":          "keyboard",
}

# Maps XInput subtype → DEVTYPE string (used before serial connection is open)
XINPUT_SUBTYPE_TO_DEVTYPE = {
    3: "pico_arcadestick",
    8: "drum_kit",
    6: "guitar_live_6fret",
    7: "guitar_alternate",
    11: "dongle",           # Dongle uses subtype 0x0B=11 (XINPUT_DEVSUBTYPE_GUITAR_BASS)
    1: "pico_retro",        # Retro Gamepad uses subtype 0x01 (XINPUT_DEVSUBTYPE_GAMEPAD)
}

# All XInput subtypes recognised as OCC devices.
# Used when scanning for controllers without a serial connection.
OCC_SUBTYPES = {8, 6, 7, 11, 3, 1}   # Drum Kit (8), Guitar (6/7), Dongle (11), Arcade Stick (3), Retro (1)

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
LED_INPUT_COUNT = len(STANDARD_GUITAR_LED_INPUT_NAMES)

VALID_NAME_CHARS = set(string.ascii_letters + string.digits + ' ')

LED_INPUT_NAMES = STANDARD_GUITAR_LED_INPUT_NAMES
LED_INPUT_LABELS = STANDARD_GUITAR_LED_INPUT_LABELS
BUTTON_DEFS = STANDARD_GUITAR_BUTTON_DEFS
