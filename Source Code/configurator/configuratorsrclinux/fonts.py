import sys, os, ctypes, shutil
from tkinter import font as tkfont
#  FONT LOADING
#  Helvetica TTFs are bundled inside the EXE (PyInstaller _MEIPASS)
#  or live in a "font/" subfolder next to the script/exe.

# Will be populated by _load_fonts() after Tk root is created.
FONT_UI      = "Helvetica" 
FONT_UI_BOLD = "Helvetica"   #weight="bold" is applied per-widget

# Map: variant tag → filename inside the font/ folder
_FONT_FILES = {
    "regular":      "Helvetica.ttf",
    "bold":         "Helvetica-Bold.ttf",
    "italic":       "Helvetica-Oblique.ttf",
    "bold-italic":  "Helvetica-BoldOblique.ttf",
    "light":        "helvetica-light.ttf",
}

def _resource_path(*parts):
    """Resolve path relative to the bundle root (PyInstaller) or script dir."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)
def _load_app_version():
    """Read version.txt bundled by build_exe.bat. Falls back to 'dev' if missing."""
    try:
        with open(_resource_path("version.txt"), "r") as f:
            return f.read().strip()
    except Exception:
        return "dev"

APP_VERSION = _load_app_version()
def _load_fonts():
    """Register bundled Helvetica font files with the OS and Tkinter.

    Windows (GDI AddFontResourceEx), macOS (CoreText via ctypes),
    Linux (fontconfig via fc-cache / Xft).  Tkinter is told to use
    the family via tkfont
    """
    global FONT_UI, FONT_UI_BOLD

    # Collect candidate directories
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(os.path.join(sys._MEIPASS, "font"))
        search_dirs.append(sys._MEIPASS)          # flat bundle layout fallback
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    search_dirs.append(os.path.join(exe_dir, "font"))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    if src_dir != exe_dir:
        search_dirs.append(os.path.join(src_dir, "font"))

    def _find_font_file(filename):
        for d in search_dirs:
            p = os.path.join(d, filename)
            if os.path.isfile(p):
                return p
        return None

    loaded_paths = []
    for _variant, fname in _FONT_FILES.items():
        path = _find_font_file(fname)
        if path:
            loaded_paths.append(path)

    if not loaded_paths:
        # if no font files found — keep system fallback
        _set_fallback_fonts()
        return

    platform = sys.platform

    if platform == "win32":
        # AddFontResourceExW loads fonts into the current process session.
        gdi = ctypes.windll.gdi32
        FR_PRIVATE = 0x10
        for p in loaded_paths:
            try:
                gdi.AddFontResourceExW(p, FR_PRIVATE, 0)
            except Exception:
                pass

    elif platform == "darwin":
        # CoreText: CTFontManagerRegisterFontsForURL (macOS 10.6+)
        try:
            ct = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreText.framework/CoreText")
            cf = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
            cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            ct.CTFontManagerRegisterFontsForURL.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            kCTFontManagerScopeProcess = 1
            for p in loaded_paths:
                url = cf.CFURLCreateFromFileSystemRepresentation(
                    None, p.encode("utf-8"), len(p), False)
                if url:
                    ct.CTFontManagerRegisterFontsForURL(
                        url, kCTFontManagerScopeProcess, None)
        except Exception:
            pass

    else:
        # Linux / other X11: copy fonts to a temp dir and point fontconfig at it.
        try:
            import tempfile
            font_tmp = os.path.join(tempfile.gettempdir(), "occ_fonts")
            os.makedirs(font_tmp, exist_ok=True)
            for p in loaded_paths:
                dest = os.path.join(font_tmp, os.path.basename(p))
                if not os.path.exists(dest):
                    shutil.copy2(p, dest)
            # Write a minimal fonts.conf so Xft/fontconfig picks up the folder
            conf_path = os.path.join(font_tmp, "fonts.conf")
            if not os.path.exists(conf_path):
                with open(conf_path, "w") as fh:
                    fh.write(f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{font_tmp}</dir>
</fontconfig>
""")
            # Tell fontconfig about the new directory
            os.environ.setdefault("FONTCONFIG_FILE", conf_path)
            try:
                import subprocess
                subprocess.run(["fc-cache", font_tmp],
                               capture_output=True, timeout=5)
            except Exception:
                pass
        except Exception:
            pass

    # Confirm Tkinter can see the font fam
    try:
        families = [f.lower() for f in tkfont.families()]
        target = "helvetica"
        if target in families:
            FONT_UI = FONT_UI_BOLD = "Helvetica"
            return
        # Look for a close match (e.g. "Helvetica Neue", "HelveticaNeue")
        for f in tkfont.families():
            if "helvetica" in f.lower():
                FONT_UI = FONT_UI_BOLD = f
                return
    except Exception:
        pass

    if loaded_paths:
        FONT_UI = FONT_UI_BOLD = "Helvetica"
        return

    _set_fallback_fonts()


def _set_fallback_fonts():
    """Set FONT_UI / FONT_UI_BOLD to the best available system sans-serif."""
    global FONT_UI, FONT_UI_BOLD
    platform = sys.platform
    if platform == "win32":
        FONT_UI = FONT_UI_BOLD = FONT_UI
    elif platform == "darwin":
        FONT_UI = FONT_UI_BOLD = "SF Pro Text"
    else:
        FONT_UI = FONT_UI_BOLD = "DejaVu Sans"
