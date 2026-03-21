<p align="center">
  <img alt="OCC" src="https://raw.githubusercontent.com/justlovett0/OCC-Configurator/master/Source%20Code/configurator/OCCLogo.png" />
</p>

<p align="center">
  Pico Music &amp; Conventional Controller Firmware with Windows Configurator
</p>

<p align="center">
  <img src="https://img.shields.io/github/license/justlovett0/OCC-Configurator" />
  <img src="https://img.shields.io/github/v/release/justlovett0/OCC-Configurator" />
</p>

<p align="center">
  <strong>I have some coding experience, but I am no expert.</strong>
</p>

<p align="center">
  <strong>This project uses AI/LLM assistance for coding efforts. I am however proud of this project and it works great.</strong>
</p>

<p>
  OCC (Open Controller Configurator) is a collection of XInput controller firmware variants for the Raspberry Pi Pico (RP2040) and Pico W (RP2040 + CYW43), paired with a Windows configurator application. Originally created for guitar and drum kit peripherals for use with games like Clone Hero and Rock Band, I am also working to expand scope to other controller and input devices, supporting wired XInput, wireless Bluetooth HID, and wireless dongle operation.
</p>

<p>
  OCC is compatible with PC (XInput / Bluetooth HID), Clone Hero, Rock Band, and any game that supports Xbox 360-style guitar or drum controllers. Support for MacOS and Linux is planned for the future.
</p>

## Links

[Releases](https://github.com/justlovett0/OCC-Configurator/releases) | [Source Code](https://github.com/justlovett0/OCC-Configurator)

## Features

- Multiple firmware variants: wired guitar, wired drums, wireless guitar (BLE HID + dongle), single-channel dongle, and 4-channel dongle
- Windows configurator EXE — Detects your controller firmware, connects over comm, configure, and flash your button mappings
- Fully configurable GPIO pin assignments for all digital button inputs
- Analog and digital tilt sensor and whammy bar inputs, with per-channel min/max sensitivity range and EMA smoothing
- Optional I2C accelerometer support (ADXL345 or LIS3DH) for tilt input
- Optional 5-pin analog joystick input
- APA102/SK9822 LED strip support: up to 16 LEDs, per-button mapping, active brightness on keypresses, and LED effects
- Wireless guitar firmware supports both BLE HID peripheral and BLE dongle modes
- BLE dongle architecture: passive advertisement scanning, no pairing required
- 4-channel dongle variant supports up to four simultaneous wireless controllers
- Step-by-step Easy Config wizard for first-time setup with live button detection and calibration
- Easy controller firmware updater: backs up config to JSON, flashes new UF2, and restores config automatically
- Custom device naming for BLE advertisements
- Config stored in flash with CRC checksum and versioned struct
- Configurable per-input debounce (0–50 ms)

## Firmware Variants

| Firmware | Device Type | Protocol | Wireless | Config Mode | Multi-Controller |
|----------|-------------|----------|----------|-------------|------------------|
| Wired Guitar Controller | Guitar (XInput subtype 0x07) | USB XInput | No | CDC Serial | No |
| Wired Drum Controller | Drum Kit (XInput subtype 0x08) | USB XInput | No | CDC Serial | No |
| Wireless Guitar Controller | Guitar (XInput subtype 0x07) | USB XInput + BLE HID | Yes — BLE HID or Dongle | CDC Serial | No |
| Wireless Dongle | Dongle (XInput subtype 0x0B) | USB XInput (relay) | Yes — BLE central | None | No (1 controller) |
| Wireless Dongle 4-Channel | Dongle (XInput subtype 0x0B) | USB XInput (relay) | Yes — BLE central | None | Yes (up to 4) |

## Getting Started

1. Download the latest release from the [Releases](https://github.com/justlovett0/OCC-Configurator/releases) page.
2. Run `OCC_Configurator.exe` — no installation needed.
3. Hold BOOTSEL on your Pico and plug it in via USB. The configurator will detect it and display the firmware selection screen.
4. Select the firmware variant that matches your controller/device type and click it to flash.
5. Once flashed, click either of the **Configure Controller** options from the main menu to open the configurator and assign your button pins.
6. Click **Save & Play Mode** to write the config to flash and return to play mode.

For new users, I recommend you use the **Easy Config** wizard for guided step-by-step pin assignment, whammy calibration, tilt setup, and LED configuration.

## Building from Source

### Firmware

Requires: Pico SDK, CMake, ARM GCC toolchain, Ninja.

Each firmware folder contains a `build.bat` that builds that variant individually. To build all five variants and package them into the configurator EXE in one step:

```
Source Code\build_all_and_package.bat
```

### Configurator

Requires: Python 3.8+, pyserial (`pip install -r requirements.txt`).

To build the standalone EXE:

```
Source Code\configurator\build_exe.bat
```

## Support

For issues or feature requests, please [open an issue](https://github.com/justlovett0/OCC-Configurator/issues).
