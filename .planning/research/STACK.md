# Stack Research

**Domain:** Embedded controller firmware (RP2040) + Windows GUI configurator
**Researched:** 2026-03-19
**Confidence:** HIGH (core stack verified against existing codebase and official sources)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Pico SDK | 2.2.0 | RP2040/RP2350 hardware abstraction, build system, USB stack integration | Latest stable release (July 2024). Adds RP2350 support, encrypted binary support, improved BTstack async context. All existing OCC variants use SDK — pico-retro must continue to use it. |
| TinyUSB | 0.18.0 (bundled) | Dual-mode USB (XInput vendor class + CDC ACM config mode) | Bundled with Pico SDK 2.2.0. The XInput vendor-class driver (xinput_driver.c) is custom-built on top of TinyUSB's raw vendor interface — this pattern is proven across every existing OCC variant. Do not use TinyUSB's HID class for XInput; the XInput protocol requires a non-standard vendor interface. |
| BTstack | SDK-bundled | BLE HID peripheral (Pico W wireless path) | Bundled with Pico SDK. Used in guitar-wireless variant. pico-retro v1 does not implement BLE but must use `PICO_BOARD pico_w` and link BTstack libraries to stay structurally ready. |
| CMake | 3.13+ | Build system for all firmware variants | Required by Pico SDK. Minimum version 3.13 per every existing CMakeLists.txt. Each firmware variant is a standalone CMake project. |
| C11 / C++17 | — | Firmware language standards | Set via `CMAKE_C_STANDARD 11` and `CMAKE_CXX_STANDARD 17` in all existing variants. Firmware is C-only in practice; C++ standard set for potential SDK headers. |
| Python 3.11+ | 3.11 | Configurator GUI | Required for match-statements and modern type annotations. PyInstaller 6.x targets Python 3.8+ but Python 3.11 is the tested deployment target. Windows-only. |
| Tkinter | stdlib | Configurator UI framework | Ships with CPython, no additional install. All five existing screens use tk.Frame in a single-root-window pattern. This is a hard constraint — do not introduce Qt, wxPython, or any other GUI framework. |
| PyInstaller | 6.x (>=6.0) | Package configurator as Windows .exe | Current major version. The build_exe.bat workflow depends on PyInstaller 6 behavior (spec file deletion required before each run). Do not downgrade to 5.x. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pyserial | 3.5 | Serial port communication (config mode protocol) | Required. Configurator communicates with firmware via CDC serial at 115200 baud. Used for PING, GET_CONFIG, SET:key=value, SAVE, REBOOT, BOOTSEL commands. |
| Pillow | >=9.0 | Image loading for configurator UI assets | Required for GIF animation playback (firmware tile animations) and PNG splash screen. |
| hardware_adc | SDK | Analog-to-digital conversion for trigger inputs | Use for analog LT/RT trigger inputs in pico-retro. Same pattern as guitar whammy (12-bit ADC on GP26/GP27/GP28). |
| hardware_gpio | SDK | Digital button inputs | Active-low with internal pull-ups. pico-retro has 13 digital inputs — identical pattern to guitar's 14 buttons. |
| hardware_watchdog | SDK | Config mode entry trigger via scratch register | All variants use `watchdog_hw->scratch[0] == WATCHDOG_CONFIG_MAGIC` to detect reboot-into-config. pico-retro must replicate this. |
| hardware_flash + hardware_sync | SDK | Config struct persistence to last flash sector | Proven pattern across all variants. pico-retro config struct (retro_config_t) should follow the same packed-struct + CRC + magic + version approach. |
| pico_unique_id | SDK | USB serial number string from device unique ID | Used in all variants for the USB iSerialNumber descriptor. |
| pico_cyw43_arch_poll | SDK (Pico W only) | CYW43 chip management without RTOS | Used in guitar-wireless. pico-retro Pico W build links this even in v1 (no BLE impl) to satisfy cyw43 init if needed. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| ARM GCC toolchain (arm-none-eabi-gcc) | Cross-compile C firmware for RP2040 | Required by Pico SDK. Version bundled with Pico SDK environment recommended. Do not use a mismatched toolchain version. |
| CMake 3.13+ | Configure and generate firmware build | Run with `-DPICO_SDK_PATH=...` pointing to SDK root. Each variant has its own build directory. |
| Ninja or make | Build driver | Ninja preferred for speed on Windows. |
| picotool | Flash, inspect, and reboot Pico devices | Useful for development — not required for end-user workflow (configurator uses BOOTSEL UF2 drag-drop). |
| Python 3.11 (Windows) | Run configurator in development | Must match the version used for PyInstaller packaging. |
| PyInstaller 6.x | Build `OCC - Configurator.exe` | Run via `build_exe.bat`. Spec files must be deleted before each run (enforced in bat). |
| compile_gatt.py | Generate `profile_data[]` for BLE GATT profile | Required for Pico W BLE variants. pico-retro v1 does not need this but must not hand-write GATT bytes if BLE is added in Phase 3+. |
| _gen_fw_dates.py | Generate fw_dates.json sidecar for build dates | Part of configurator build pipeline. Reads .uf2.date sidecars written by CMake post-build step. |

---

## Installation

```bash
# Firmware — Linux/macOS build (WSL on Windows)
# Install Pico SDK 2.2.0
git clone -b 2.2.0 https://github.com/raspberrypi/pico-sdk.git --recurse-submodules
export PICO_SDK_PATH=/path/to/pico-sdk

# Build pico-retro (once CMakeLists.txt exists)
mkdir build && cd build
cmake .. -DPICO_BOARD=pico   # or pico_w for wireless-ready build
make -j$(nproc)

# Configurator — Windows
pip install pyserial>=3.5 pyinstaller>=6.0 Pillow>=9.0

# Build exe
# (from configurator/ directory, with .uf2 files present)
build_exe.bat
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Pico SDK 2.2.0 | Pico SDK 1.5.x | Only if targeting RP2040-only with no interest in RP2350 support. OCC will eventually target Pico 2; stay on 2.x. |
| TinyUSB (bundled, vendor class) | TinyUSB HID class | Never for XInput. Windows XInput requires vendor-class USB with specific VID/PID and descriptor format. HID class produces a standard gamepad, not an XInput device. |
| Tkinter (stdlib) | CustomTkinter | Only if a major visual refresh of the configurator is planned. CustomTkinter requires bundling extra assets and adds PyInstaller complexity. Not worth it for incremental screen additions. |
| PyInstaller 6.x --onefile | Nuitka | Nuitka produces faster startup but requires C compiler on build machine. PyInstaller is simpler and proven for this project. Use Nuitka only if startup time becomes a user complaint. |
| pyserial 3.5 | pyserial-asyncio-fast | Only relevant if the configurator moves to an asyncio architecture. Current threading model (background thread + _backup_in_progress flag) works correctly. Do not change serial model for pico-retro. |
| Python 3.11 | Python 3.12/3.13 | Python 3.12+ is fine but introduces minor deprecation warnings in some Tkinter internals. 3.11 is the tested stable target for the existing exe. Validate packaging before upgrading. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| TinyUSB HID class for XInput output | XInput is not standard HID. Windows will enumerate it as a generic gamepad without force-feedback or subtype recognition. The XInput driver model requires Vendor class with specific report format. | Custom xinput_driver.c (already exists — replicate it for pico-retro) |
| Hand-written GATT profile bytes | BTstack GATT profiles must be generated by compile_gatt.py. Hand-written bytes break silently when the library version changes. | compile_gatt.py (used in guitar-wireless) |
| `Toplevel` windows for configurator screens | Violates the established single-root-window architecture. Creates z-order issues, geometry conflicts, and breaks the unified menu bar pattern. | tk.Frame subclasses shown/hidden via pack/pack_forget |
| Rebuilding UI cards on every poll cycle | Causes combo dropdowns to collapse during active configuration sessions. | State-tuple comparison before rebuild (existing _update_scroll_state pattern) |
| FetchContent for Pico-PIO-USB | Re-configure loop bug in CMake causes slow builds and occasional cache corruption. | Local copy in lib/Pico-PIO-USB/ (established in pico-pedal variant) |
| `nuke.uf2` in find_uf2_files() | Nuke firmware must be bundled separately and never appear in the tile grid or firmware selection UI. | Separate NUKE_ARG path in build_exe.bat |
| Redefining LED_INPUT_COUNT | apa102_leds.h defines LED_INPUT_COUNT=16 as a fixed constant. Device config headers must not override it. | Use the constant as-is from apa102_leds.h |
| Direct ATT buffer writes at report rate (BLE) | Windows BLE stack drops reports sent without checking can_send_now. | can_send_now callback pattern (guitar-wireless) |

---

## Stack Patterns by Variant

**If building wired-only (Pico, not Pico W):**
- Set `PICO_BOARD=pico` in CMake
- No CYW43/BTstack libraries needed
- Simpler CMakeLists.txt (see pico-drums-wired as reference)
- CONFIG_MODE_PID must be unique per variant (see VID/PID table below)

**If building wireless-ready (Pico W, BLE deferred):**
- Set `PICO_BOARD=pico_w` in CMake
- Add `CYW43_LWIP=0` and `PICO_W_BT=1` compile definitions
- Link `pico_cyw43_arch_poll`, `pico_btstack_ble`, `pico_btstack_cyw43`, `pico_btstack_flash_bank`
- USB host detection at boot determines which path to take (USB detected → XInput, no USB → BLE)
- See guitar-wireless as the reference implementation

**If adding config mode (required for all OCC variants):**
- Link `tinyusb_device tinyusb_board hardware_flash hardware_sync hardware_watchdog`
- Enable CDC in tusb_config.h: `CFG_TUD_CDC 1`, buffers 256 bytes each
- All other TinyUSB classes disabled (HID=0, MSC=0, MIDI=0, VENDOR=0)
- Emit `DEVTYPE:<type>` as the first line of GET_CONFIG response
- New DEVTYPE string must be registered in configurator's DEVICE_SCREEN_CLASSES dict

**If using analog inputs (triggers, sticks):**
- Use hardware_adc with GP26/GP27/GP28 (the three ADC-capable pins)
- Apply EMA smoothing (guitar-wired's ema_alpha pattern)
- Store min/max calibration in config struct (proven in guitar whammy + pedal ADC)
- Invert flag in config struct for reversed sensor orientation

---

## VID/PID Assignment

All XInput mode builds share `VID=0x045E PID=0x028E` — this is the Xbox 360 controller identity required for XInput enumeration on Windows.

Config mode PIDs are unique per device type (same VID=0x2E8A):

| Variant | Config Mode PID | DEVTYPE string | XInput Subtype |
|---------|----------------|----------------|----------------|
| guitar-wired | 0xF00D | guitar_alternate | 0x07 |
| guitar-wireless | 0xF00D | guitar_combined | 0x07 |
| pico-drums-wired | 0xF00E | drum_kit | 0x08 |
| pico-dongle-4channel | (no config mode) | — | 0x0B |
| pico-pedal | 0xF010 | pedal | 0x07 (reuses guitar alt) |
| **pico-retro (new)** | **0xF011** | **retro_gamepad** | **0x01** |

pico-retro should use:
- XInput subtype `0x01` (`XINPUT_DEVSUBTYPE_GAMEPAD`) — the standard gamepad subtype. This is correct for a retro-style controller with DPad, ABXY, Start, Select, Guide, LB, RB, LT, RT.
- Config mode PID `0xF011` — next available in the OCC sequence after pedal's `0xF010`.
- DEVTYPE string `"retro_gamepad"` — follows the `noun_type` naming convention.
- OCC_SUBTYPES in configurator must add `1` (0x01) to detect pico-retro in XInput mode before serial connection.

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| Pico SDK 2.2.0 | TinyUSB 0.18.0 | TinyUSB is a submodule of pico-sdk — versions are locked together. Do not use a standalone TinyUSB install alongside pico-sdk. |
| Pico SDK 2.2.0 | BTstack (SDK-bundled) | BTstack version is locked to SDK version. An open GitHub issue (#2756) requests TinyUSB bump to 0.20.0, but 0.18.0 is what ships with 2.2.0. |
| PyInstaller 6.x | Python 3.8–3.12 | Python 3.11 is the tested target. PyInstaller 6.14.x is the current release. |
| pyserial 3.5 | Python 3.6+ | No major version updates since 3.5 (released 2017). API stable. |
| Pillow >=9.0 | Python 3.8+ | Pillow 10.x (2023) and 11.x (2024) are current. Specify >=9.0 for compatibility; current installs will get 10.x or 11.x. |

---

## Sources

- [Pico SDK Releases — GitHub](https://github.com/raspberrypi/pico-sdk/releases) — SDK 2.2.0 confirmed latest stable; HIGH confidence
- [pico-sdk 2.2.0 Forum Announcement](https://forums.raspberrypi.com/viewtopic.php?t=390503) — 2.2.0 release notes; HIGH confidence
- [Pico SDK 2.1.1 CNX Software](https://www.cnx-software.com/2025/02/20/raspberry-pi-pico-sdk-2-1-1-release-adds-200mhz-clock-option-for-rp2040-various-waveshare-boards-new-code-samples/) — 2.1.1 feature summary; MEDIUM confidence
- [TinyUSB Releases — GitHub](https://github.com/hathach/tinyusb/releases) — 0.20.0 latest standalone; HIGH confidence
- [TinyUSB bump issue #2756 — pico-sdk](https://github.com/raspberrypi/pico-sdk/issues/2756) — confirms pico-sdk 2.2.0 ships TinyUSB 0.18.0; HIGH confidence
- [XINPUT and Controller Subtypes — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/xinput/xinput-and-controller-subtypes) — subtype 0x01=GAMEPAD official; HIGH confidence
- [PyInstaller Changelog](https://pyinstaller.org/en/v6.14.2/CHANGES.html) — 6.x current series confirmed; HIGH confidence
- [pyserial PyPI](https://pypi.org/project/pyserial/) — 3.5 current stable; HIGH confidence
- Existing OCC codebase (`requirements.txt`, CMakeLists.txt files, usb_descriptors.h) — direct inspection; HIGH confidence

---
*Stack research for: OCC pico-retro firmware variant + configurator extension*
*Researched: 2026-03-19*
