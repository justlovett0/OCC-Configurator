"""
OCC - Open Controller Configurator

Dependencies:
pyserial>=3.5
pyinstaller>=6.0
Pillow>=9.0

Build EXE:    See build_exe.bat
"""

import tkinter as tk
from tkinter import messagebox
import threading, time, sys, ctypes

from configuratorsrc.constants import *
from configuratorsrc.fonts import _load_fonts, APP_VERSION
from configuratorsrc.xinput_utils import (XINPUT_AVAILABLE, xinput_get_connected,
                                           xinput_send_vibration, MAGIC_STEPS)
from configuratorsrc.serial_comms import PicoSerial
from configuratorsrc.firmware_utils import flash_uf2_with_reboot
from configuratorsrc.utils import _fetch_latest_release, _version_is_newer, _show_update_dialog
from configuratorsrc.widgets import _DD_HEIGHT, _DD_CHAR_PX, _DD_PAD
from configuratorsrc.screen_flash import FlashFirmwareScreen
from configuratorsrc.screen_easy_config import EasyConfigScreen
from configuratorsrc.screen_main_menu import MainMenu
from configuratorsrc.screen_app import App
from configuratorsrc.screen_drum import DrumApp
from configuratorsrc.screen_pedal import PedalApp
from configuratorsrc.screen_retro import RetroApp
from configuratorsrc.screen_keymacro import KeyMacroApp
from configuratorsrc.screen_splash import SplashOverlay, _find_icon, play_startup_sound
import configuratorsrc.widgets as _widgets_mod
import configuratorsrc.screen_easy_config as _easy_config_mod

DEBUG_SCREEN_LABELS = (
  ("menu", "Main Menu"),
  ("flash", "Flash Firmware"),
  ("easy", "Easy Configuration"),
  ("guitar_alternate", "Guitar Config"),
  ("guitar_live_6fret", "6-Fret Guitar Config"),
  ("drum_kit", "Drum Config"),
  ("pedal", "Pedal Config"),
  ("pico_retro", "Retro Config"),
  ("keyboard_macro", "Keyboard Macro Config"),
)

#  DEVICE TYPE → SCREEN CLASS  routing table
#
#  To add a new device type:
#    1. Create a new App class (e.g. BassApp) above.
#    2. Add an entry here:  "bass_guitar": BassApp
#


DEVICE_SCREEN_MAP = {
  "guitar_alternate":        None,   # filled in main() once App is instantiated
  "guitar_alternate_dongle": None,   # dongle guitar variant → same App screen
  "guitar_live_6fret":       None,   # filled in main() once App is instantiated
  "drum_kit":                None,   # filled in main() once DrumApp is instantiated
  "pedal":                   None,   # filled in main() once PedalApp is instantiated
  "pico_retro":              None,   # filled in main() once RetroApp is instantiated
  "keyboard_macro":          None,   # filled in main() once KeyMacroApp is instantiated
}

# Map device_type → the constructor to call (used to build instances in main())
DEVICE_SCREEN_CLASSES = {
  "guitar_alternate":        lambda root, on_back: App(root, on_back=on_back, guitar_profile="standard"),
  "guitar_alternate_dongle": lambda root, on_back: App(root, on_back=on_back, guitar_profile="standard"),
  "guitar_combined":         lambda root, on_back: App(root, on_back=on_back, guitar_profile="standard"),
  "guitar_live_6fret":       lambda root, on_back: App(root, on_back=on_back, guitar_profile="six_fret"),
  "drum_kit":                DrumApp,
  "pedal":                   PedalApp,
  "pico_retro":              RetroApp,
  "keyboard_macro":          KeyMacroApp,
}


class DebugLauncher:
  """Simple debug-only screen launcher window."""

  def __init__(self, root, on_show_screen):
      self.root = root
      self._on_show_screen = on_show_screen
      self.window = tk.Toplevel(root)
      self.window.title("OCC Debug Launcher")
      self.window.configure(bg=BG_MAIN)
      self.window.resizable(False, False)
      self.window.transient(root)
      self.window.attributes("-topmost", True)
      self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

      outer = tk.Frame(self.window, bg=BG_MAIN, padx=14, pady=14)
      outer.pack(fill="both", expand=True)

      tk.Label(
          outer,
          text="DEBUG SCREEN LAUNCHER",
          bg=BG_MAIN,
          fg=ACCENT_BLUE,
          font=("Helvetica", 10, "bold"),
      ).pack(anchor="w")
      tk.Label(
          outer,
          text="Click a button to swap the main configurator window.",
          bg=BG_MAIN,
          fg=TEXT_DIM,
          font=("Helvetica", 8),
      ).pack(anchor="w", pady=(2, 10))

      grid = tk.Frame(outer, bg=BG_MAIN)
      grid.pack(fill="both", expand=True)

      for idx, (screen_key, label) in enumerate(DEBUG_SCREEN_LABELS):
          btn = tk.Button(
              grid,
              text=label,
              command=lambda key=screen_key: self._on_show_screen(key),
              bg=BG_CARD,
              fg=TEXT,
              activebackground=BG_HOVER,
              activeforeground=TEXT,
              relief="flat",
              bd=1,
              highlightbackground=BORDER,
              highlightthickness=1,
              width=24,
              padx=8,
              pady=8,
          )
          btn.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=4, pady=4)

      for col in range(2):
          grid.grid_columnconfigure(col, weight=1)

      self.window.update_idletasks()
      self.window.geometry(f"+{root.winfo_rootx() + 40}+{root.winfo_rooty() + 40}")



def _show_startup_error(message):
  """Display a launch-time error before the Tk root exists."""
  print(message, file=sys.stderr)
  if sys.platform == "win32":
      try:
          ctypes.windll.user32.MessageBoxW(None, message, "OCC Startup Error", 0x10)
      except Exception:
          pass


def _parse_manual_scale(argv):
  """Parse an optional -scale override from the command line."""
  args = [arg.strip() for arg in argv]
  idx = 0
  while idx < len(args):
      arg = args[idx]
      if arg.lower() != "-scale":
          idx += 1
          continue

      if idx + 1 >= len(args):
          raise ValueError("Missing value after -scale. Use a number from 0.5 to 2.5.")

      raw_value = args[idx + 1]
      try:
          scale = float(raw_value)
      except ValueError as exc:
          raise ValueError(
              f"Invalid -scale value '{raw_value}'. Use a number from 0.5 to 2.5."
          ) from exc

      if not 0.5 <= scale <= 2.5:
          raise ValueError(
              f"Invalid -scale value '{raw_value}'. Scale must be between 0.5 and 2.5."
          )
      return scale

  return None


#  ENTRY POINT


def main():
  debug_mode = any(arg.lower() == "-debug" for arg in sys.argv[1:])
  try:
      manual_scale = _parse_manual_scale(sys.argv[1:])
  except ValueError as exc:
      _show_startup_error(str(exc))
      return 1

  root = tk.Tk()
  # Hide the window immediately so the blank white frame is never visible
  # while Python/tkinter finishes initialising.  We reveal it below once
  # everything is built and ready.
  root.withdraw()

  # Load and register bundled Helvetica fonts.  Must be called after Tk()
  # so that tkfont.families() is available, but before any widgets are built.
  _load_fonts()

  root.title("OCC - Open Controller Configurator")

  # ── DPI awareness + resolution scaling ───────────────────────────
  # Must be set before querying screen size so winfo_screenheight()
  # returns the true physical pixel count on high-DPI displays.
  if sys.platform == "win32":
      try:
          ctypes.windll.shcore.SetProcessDpiAwareness(1)
      except Exception:
          pass

  root.update_idletasks()   # ensure Tk has real screen dimensions
  sw = root.winfo_screenwidth()
  sh = root.winfo_screenheight()

  # Baseline is 1080p tall.  Clamp to 1.0 minimum so 1080p is unchanged.
  auto_scale = max(1.0, sh / 1080)
  _scale = manual_scale if manual_scale is not None else auto_scale

  # Tk's built-in scaling multiplier handles ALL font sizes automatically.
  # Default Tk scaling is 1.0 at 96 DPI; we multiply by our factor.
  _tk_base_scale = root.tk.call('tk', 'scaling')
  root.tk.call('tk', 'scaling', _tk_base_scale * _scale)

  # ── Unified window geometry — set once, never changed by screens ──
  def _S(n):
      """Scale a pixel dimension to the current display resolution."""
      return max(1, round(n * _scale))

  w, h = _S(1180), _S(820)
  x = (sw - w) // 2
  y = (sh - h) // 2
  root.geometry(f"{w}x{h}+{x}+{y}")
  root.resizable(False, False)   # fixed size on all axes

  # Apply custom .ico if one exists alongside the exe / script
  _ico = _find_icon()
  if _ico:
      try:
          root.iconbitmap(_ico)
      except Exception:
          pass

  # Play startup sound immediately (async, non-blocking)
  play_startup_sound()

  # ── Patch pixel-dimension globals to match display scale ─────────
  # Only module-level constants used as pixel sizes need adjusting.
  # Font sizes are handled automatically by tk.scaling() above.
  # Character-width args (Label width=, Entry width=, etc.) are NOT touched.
  if _scale > 1.0:
      _widgets_mod._DD_HEIGHT  = _S(30)
      _widgets_mod._DD_CHAR_PX = _S(7)
      _widgets_mod._DD_PAD     = _S(10)
      _easy_config_mod._BTN_DISP_W = _S(90)
      _easy_config_mod._BTN_DISP_H = _S(70)

      FlashFirmwareScreen.TILE_IMG_H = _S(140)
      FlashFirmwareScreen.TILE_LBL_H = _S(28)
      FlashFirmwareScreen.TILE_PAD   = _S(10)


  # ── Build lightweight screens first ─────────────────────────────
  # MainMenu, EasyConfig and FlashScreen are fast to construct.
  # The heavy device configurator screens (App, DrumApp) are deferred
  # until after the window is visible so the splash appears instantly.

  menu = MainMenu(root, on_configure=None)   # on_configure set below

  easy_config_screen = EasyConfigScreen(root, on_back=None)
  easy_config_screen.hide()

  flash_screen = FlashFirmwareScreen(root, on_back=None)
  flash_screen.hide()

  # ── Show splash first, then reveal the window behind it ──────────
  # SplashOverlay is created while root is still withdrawn so the
  # overlay is fully painted before deiconify() makes everything visible.
  menu.show()
  SplashOverlay(root, geometry=(w, h, x, y))
  root.deiconify()

  # ── Startup update check (background, non-blocking) ──────────────
  def _startup_update_check():
      if APP_VERSION == "dev":
          return
      latest, url = _fetch_latest_release()
      if latest and _version_is_newer(latest, APP_VERSION):
          root.after(0, lambda: _show_update_dialog(root, latest, url))
  threading.Thread(target=_startup_update_check, daemon=True).start()

  # ── Deferred device screen construction ─────────────────────────
  device_screens = {}
  debug_launcher = [None]

  def _cancel_menu_poll():
      if menu._poll_job:
          menu.root.after_cancel(menu._poll_job)
          menu._poll_job = None

  def show_screen(screen_key, *, connect_port=None, drive=None):
      """Central screen switcher used by normal routing and debug mode."""
      _cancel_menu_poll()

      for s in device_screens.values():
          s.hide()
      flash_screen.hide()
      easy_config_screen.hide()
      menu.hide()

      if screen_key == "menu":
          menu.show()
          return

      if screen_key == "flash":
          flash_screen.show(drive=drive)
          return

      if screen_key == "easy":
          easy_config_screen.show()
          if connect_port:
              easy_config_screen._connect_serial(connect_port)
          return

      screen = device_screens.get(screen_key)
      if screen is None:
          raise KeyError(f"Unknown screen key: {screen_key}")

      screen.show()
      if connect_port:
          root.update()   # flush layout + WM_PAINT so canvas widgets render before serial blocks
          screen._connect_serial(connect_port)

  def go_to_menu():
      show_screen("menu")

  def go_to_easy_config(port):
      """
      Route to Easy Configuration.  Mirrors go_to_configurator() — handles
      both config-mode (port given) and XInput play mode (port=None).
      """
      _cancel_menu_poll()

      if port:
          # Already in config mode
          show_screen("easy", connect_port=port)

      elif XINPUT_AVAILABLE:
          # XInput play mode — stay on menu, run magic sequence in background
          menu._cfg_btn.set_state("disabled")
          menu._easy_cfg_btn.set_state("disabled")
          menu._ctrl_icon.config(text="\u25cc", fg=ACCENT_BLUE)
          menu._ctrl_status.config(text="Connecting\u2026", fg=ACCENT_BLUE)
          menu._ctrl_detail.config(text="Sending config signal\u2026", fg=TEXT_DIM)
          root.update_idletasks()

          def _worker():
              try:
                  controllers = xinput_get_connected()
                  if not controllers:
                      root.after(0, lambda: [
                          menu._ctrl_icon.config(text="\u25cb", fg=TEXT_DIM),
                          menu._ctrl_status.config(text="No device found", fg=ACCENT_RED),
                          menu._ctrl_detail.config(text="", fg=TEXT_DIM),
                          menu._cfg_btn.set_state("disabled"),
                          menu._easy_cfg_btn.set_state("disabled"),
                      ])
                      return
                  slot = controllers[0][0]
                  for left, right in MAGIC_STEPS:
                      xinput_send_vibration(slot, left, right)
                      time.sleep(0.08)
                  xinput_send_vibration(slot, 0, 0)
              except Exception as exc:
                  root.after(0, lambda e=exc: [
                      menu._ctrl_icon.config(text="\u25cb", fg=TEXT_DIM),
                      menu._ctrl_status.config(text=f"Signal failed: {e}", fg=ACCENT_RED),
                      menu._ctrl_detail.config(text="", fg=TEXT_DIM),
                      menu._cfg_btn.set_state("normal"),
                      menu._easy_cfg_btn.set_state("normal"),
                  ])
                  return

              root.after(0, lambda: menu._ctrl_detail.config(
                  text="Waiting for config port\u2026", fg=TEXT_DIM))

              deadline = time.time() + 10.0
              found_port = None
              while time.time() < deadline:
                  found_port = PicoSerial.find_config_port()
                  if found_port:
                      break
                  time.sleep(0.2)

              if not found_port:
                  root.after(0, lambda: [
                      menu._ctrl_icon.config(text="\u25cb", fg=TEXT_DIM),
                      menu._ctrl_status.config(text="Config mode timed out", fg=ACCENT_RED),
                      menu._ctrl_detail.config(
                          text="Close any games using the controller and retry.", fg=TEXT_DIM),
                      menu._cfg_btn.set_state("normal"),
                      menu._easy_cfg_btn.set_state("normal"),
                  ])
                  return

              time.sleep(0.5)

              root.after(0, lambda fp=found_port: show_screen("easy", connect_port=fp))

          threading.Thread(target=_worker, daemon=True).start()

  def go_to_flash_screen(drive):
      show_screen("flash", drive=drive)

  def _route_to_screen(device_type, port):
      """Called on the Tk thread once DEVTYPE is known. Shows the right screen."""
      if device_type == "dongle":
          menu._ctrl_icon.config(text="●", fg=ACCENT_ORANGE)
          menu._ctrl_status.config(
              text="Dongle detected, no configuration options available.",
              fg=ACCENT_ORANGE)
          menu._ctrl_detail.config(text="", fg=TEXT_DIM)
          menu._cfg_btn.set_state("disabled")
          menu._easy_cfg_btn.set_state("disabled")
          return
      screen = device_screens.get(device_type)
      if screen is None:
          menu._ctrl_icon.config(text="●", fg=ACCENT_ORANGE)
          menu._ctrl_status.config(text="Unsupported device type", fg=ACCENT_ORANGE)
          menu._ctrl_detail.config(text=f'Type reported: "{device_type}"', fg=TEXT_DIM)
          menu._cfg_btn.set_state("normal")
          menu._easy_cfg_btn.set_state("normal")
          if device_type == "unknown":
              messagebox.showerror(
                  "Device Type Unknown",
                  "The connected device did not report its type.\n\n"
                  "This usually means the firmware is outdated and is missing\n"
                  "the DEVTYPE line in its GET_CONFIG response.\n\n"
                  "Fix: add  serial_writeln(\"DEVTYPE:\" DEVICE_TYPE);  as the\n"
                  "first line of send_config() in config_serial.c, then\n"
                  "rebuild and reflash the firmware."
              )
          else:
              messagebox.showerror(
                  "Unsupported Device",
                  f"Connected device reports an unrecognised type:\n"
                  f"  \"{device_type}\"\n\n"
                  f"Supported types: {', '.join(sorted(DEVICE_SCREEN_CLASSES.keys()))}\n\n"
                  "Make sure you are running the latest configurator."
              )
          return
      show_screen(device_type, connect_port=port)

  def go_to_configurator(port):
      """
      Route to the correct configurator screen based on DEVTYPE.
      If device screens are not yet built, wait for them first.
      """
      _cancel_menu_poll()

      if port:
          try:
              ps = PicoSerial()
              ps.connect(port)
              cfg = ps.get_config()
              ps.disconnect()
              device_type = cfg.get("device_type", "unknown")
          except Exception:
              device_type = "unknown"
          _route_to_screen(device_type, port)

      elif XINPUT_AVAILABLE:
          menu._cfg_btn.set_state("disabled")
          menu._easy_cfg_btn.set_state("disabled")
          menu._ctrl_icon.config(text="◌", fg=ACCENT_BLUE)
          menu._ctrl_status.config(text="Connecting…", fg=ACCENT_BLUE)
          menu._ctrl_detail.config(text="Sending config signal…", fg=TEXT_DIM)
          root.update_idletasks()

          def _worker():
              try:
                  controllers = xinput_get_connected()
                  if not controllers:
                      root.after(0, lambda: [
                          menu._ctrl_icon.config(text="○", fg=TEXT_DIM),
                          menu._ctrl_status.config(text="No device found", fg=ACCENT_RED),
                          menu._ctrl_detail.config(text="", fg=TEXT_DIM),
                          menu._cfg_btn.set_state("disabled"),
                          menu._easy_cfg_btn.set_state("disabled"),
                      ])
                      return
                  slot = controllers[0][0]
                  for left, right in MAGIC_STEPS:
                      xinput_send_vibration(slot, left, right)
                      time.sleep(0.08)
                  xinput_send_vibration(slot, 0, 0)
              except Exception as exc:
                  root.after(0, lambda e=exc: [
                      menu._ctrl_icon.config(text="○", fg=TEXT_DIM),
                      menu._ctrl_status.config(text=f"Signal failed: {e}", fg=ACCENT_RED),
                      menu._ctrl_detail.config(text="", fg=TEXT_DIM),
                      menu._cfg_btn.set_state("normal"),
                      menu._easy_cfg_btn.set_state("normal"),
                  ])
                  return

              root.after(0, lambda: menu._ctrl_detail.config(
                  text="Waiting for config port…", fg=TEXT_DIM))

              deadline = time.time() + 10.0
              found_port = None
              while time.time() < deadline:
                  found_port = PicoSerial.find_config_port()
                  if found_port:
                      break
                  time.sleep(0.2)

              if not found_port:
                  root.after(0, lambda: [
                      menu._ctrl_icon.config(text="○", fg=TEXT_DIM),
                      menu._ctrl_status.config(text="Config mode timed out", fg=ACCENT_RED),
                      menu._ctrl_detail.config(
                          text="Close any games using the controller and retry.", fg=TEXT_DIM),
                      menu._cfg_btn.set_state("normal"),
                      menu._easy_cfg_btn.set_state("normal"),
                  ])
                  return

              time.sleep(0.5)  # let the port settle

              root.after(0, lambda: menu._ctrl_detail.config(
                  text="Identifying device…", fg=TEXT_DIM))

              try:
                  ps = PicoSerial()
                  ps.connect(found_port)
                  cfg = ps.get_config()
                  ps.disconnect()
                  device_type = cfg.get("device_type", "unknown")
              except Exception:
                  device_type = "unknown"

              root.after(0, lambda dt=device_type, fp=found_port:
                  _route_to_screen(dt, fp))

          threading.Thread(target=_worker, daemon=True).start()

  def _build_device_screens():
      """Build the heavy configurator screens after the splash is showing."""
      for dtype, cls in DEVICE_SCREEN_CLASSES.items():
          screen = cls(root, on_back=go_to_menu)
          screen.hide()
          device_screens[dtype] = screen

      flash_screen._on_back = go_to_menu
      easy_config_screen._on_back = go_to_menu
      menu._on_configure = go_to_configurator
      menu._on_flash_screen = go_to_flash_screen
      menu._on_easy_config = go_to_easy_config
      if debug_mode and debug_launcher[0] is None:
          debug_launcher[0] = DebugLauncher(root, lambda key: show_screen(key))

  # Schedule device screen construction on the next event loop tick
  # so the splash overlay renders first
  root.after(50, _build_device_screens)

  root.mainloop()


if __name__ == "__main__":
  sys.exit(main() or 0)
