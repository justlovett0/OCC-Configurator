import sys, os, threading, ctypes
import tkinter as tk
from .constants import BG_CARD, TEXT, ACCENT_BLUE, BG_MAIN, TEXT_HEADER
from .fonts import FONT_UI
#  SPLASH IMAGE FINDER


def _find_icon():
    """Find a .ico file alongside the exe or script for the window icon."""
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if src_dir not in search_dirs:
        search_dirs.append(src_dir)
    for d in search_dirs:
        for f in os.listdir(d):
            if f.lower().endswith('.ico'):
                return os.path.join(d, f)
    return None


def find_splash_image():
    """Search the exe/script directory for splash.png or splash.jpg."""
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if src_dir not in search_dirs:
        search_dirs.append(src_dir)

    for d in search_dirs:
        for name in ("splash.png", "splash.PNG"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None



#  STARTUP SOUND


def find_startup_sound():
    """Search the exe/script directory for a startup audio file named 'startup.*'."""
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if src_dir not in search_dirs:
        search_dirs.append(src_dir)

    extensions = (".wav", ".mp3", ".ogg", ".flac", ".aac", ".wma",
                  ".WAV", ".MP3", ".OGG", ".FLAC", ".AAC", ".WMA")
    for d in search_dirs:
        for ext in extensions:
            p = os.path.join(d, "startup" + ext)
            if os.path.isfile(p):
                return p
    return None


def play_startup_sound():
    """
    Play the startup sound asynchronously from within the process.
    Uses MCI (Media Control Interface) via winmm.dll -- already loaded,
    zero extra dependencies, handles WAV/MP3/WMA/AIFF natively.
    OGG/FLAC fall back to PlaySound (WAV only) and are silently skipped
    if not natively supported by the Windows MCI stack.
    Silent no-op on non-Windows or if no sound file is found.
    """
    if sys.platform != "win32":
        return
    path = find_startup_sound()
    if not path:
        return

    def _mci_play(filepath):
        """Open and play via MCI in a daemon thread so startup isn't blocked."""
        mci = ctypes.windll.winmm.mciSendStringW
        alias = "startup_snd"
        try:
            # Use short (8.3-safe) path to avoid MCI quoting issues
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.kernel32.GetShortPathNameW(filepath, buf, 512)
            short_path = buf.value or filepath

            mci(f'open "{short_path}" alias {alias}', None, 0, None)
            mci(f'play {alias} wait', None, 0, None)
        except Exception:
            pass
        finally:
            try:
                mci(f'close {alias}', None, 0, None)
            except Exception:
                pass

    t = threading.Thread(target=_mci_play, args=(path,), daemon=True)
    t.start()
class SplashOverlay:
    """
    A borderless Toplevel that sits on top of the main window,
    exactly covering it, showing a splash image (or fallback text).
    After HOLD_MS it fades out over FADE_MS, then destroys itself.

    The main window is shown normally the whole time — its controls
    load behind the overlay and are revealed as the splash fades away.
    """

    HOLD_MS    = 3000   # fully visible duration (ms)
    FADE_MS    = 500    # fade-out duration (ms)
    FADE_STEPS = 30     # opacity steps during fade

    def __init__(self, root, geometry=None):
        """Create the splash overlay.

        geometry: optional (w, h, x, y) tuple.  Pass this when the root
        window is still withdrawn so winfo_* calls would return stale values.
        If omitted the geometry is read from the live root window as before.
        """
        self._root = root

        if geometry is not None:
            w, h, x, y = geometry
        else:
            # ── Wait for the root window to be mapped so we can read its geometry ──
            root.update_idletasks()
            x = root.winfo_x()
            y = root.winfo_y()
            w = root.winfo_width()
            h = root.winfo_height()

        # ── Create the overlay Toplevel ───────────────────────
        self._overlay = tk.Toplevel(root)
        self._overlay.overrideredirect(True)
        self._overlay.configure(bg=BG_MAIN)
        self._overlay.attributes("-topmost", True)
        self._overlay.attributes("-alpha", 1.0)
        self._overlay.geometry(f"{w}x{h}+{x}+{y}")

        # Keep the overlay glued to the main window if it moves/resizes
        root.bind("<Configure>", self._reposition, add="+")

        # ── Canvas filling the overlay ────────────────────────
        self._canvas = tk.Canvas(self._overlay, bg=BG_MAIN,
                                 highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)

        # ── Load splash image (scaled once to window size) ───────────
        self._photo = None
        img_path = find_splash_image()

        if img_path and img_path.lower().endswith(".png"):
            try:
                from PIL import Image, ImageTk
                self._photo = ImageTk.PhotoImage(
                    Image.open(img_path).resize((w, h)))
            except Exception:
                self._photo = None
            if self._photo is None:
                try:
                    self._photo = tk.PhotoImage(file=img_path)
                except Exception:
                    self._photo = None

        self._draw(w, h)
        # Force the overlay to be fully painted before the caller shows the
        # root window.  update() flushes geometry + expose events so the
        # canvas pixels are on-screen before deiconify() is called.
        self._overlay.update()

        # ── Kick off the hold → fade sequence ─────────────────
        self._alpha       = 1.0
        self._alpha_step  = 1.0 / self.FADE_STEPS
        self._fade_delay  = self.FADE_MS // self.FADE_STEPS
        self._overlay.after(self.HOLD_MS, self._start_fade)

        # Schedule an immediate reposition so that after deiconify() maps
        # the root window we snap to the real client-area coordinates before
        # the first frame is rendered.  The <Configure> binding handles
        # subsequent moves; this handles the very first mapping.
        self._overlay.after(1, self._reposition)

    # ── Drawing ───────────────────────────────────────────────────

    def _draw(self, w, h):
        self._canvas.delete("all")
        if self._photo:
            self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        else:
            # Fallback: styled text centred in the window
            self._canvas.create_text(
                w // 2, h // 2 - 16,
                text="OCC",
                fill=TEXT_HEADER, font=(FONT_UI, 20, "bold"))
            self._canvas.create_text(
                w // 2, h // 2 + 18,
                text="Open Controller Configurator",
                fill=ACCENT_BLUE, font=(FONT_UI, 13))

    # ── Keep overlay covering the main window ─────────────────────

    def _reposition(self, event=None):
        if not self._overlay.winfo_exists():
            return
        try:
            # winfo_rootx/y = client-area origin (excludes invisible DWM shadow).
            # winfo_x/y     = outer frame origin (includes title bar above client).
            # We want the overlay to cover title bar + client area, so:
            #   x = client left  (avoids invisible shadow gap on the right)
            #   y = outer top    (starts above the title bar)
            #   w = client width
            #   h = (title bar height) + client height
            rx = self._root.winfo_rootx()
            ry = self._root.winfo_rooty()
            oy = self._root.winfo_y()
            w  = self._root.winfo_width()
            h  = self._root.winfo_height()
            titlebar_h = ry - oy          # pixels from outer top to client top
            self._overlay.geometry(f"{w}x{h + titlebar_h}+{rx}+{oy}")
        except Exception:
            pass

    # ── Fade sequence ─────────────────────────────────────────────

    def _start_fade(self):
        self._root.unbind("<Configure>")   # stop repositioning during fade
        self._do_fade_step()

    def _do_fade_step(self):
        self._alpha -= self._alpha_step
        if self._alpha <= 0:
            self._finish()
            return
        try:
            self._overlay.attributes("-alpha", max(0.0, self._alpha))
        except Exception:
            pass
        self._overlay.after(self._fade_delay, self._do_fade_step)

    def _finish(self):
        try:
            self._overlay.destroy()
        except Exception:
            pass

