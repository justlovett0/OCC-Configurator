import sys, os, json, threading
import tkinter as tk
from .constants import (BG_CARD, BG_INPUT, TEXT, TEXT_DIM, ACCENT_BLUE,
                         ACCENT_RED, GITHUB_REPO, RELEASES_PAGE)
from .fonts import FONT_UI, APP_VERSION
from .widgets import RoundedButton

# Scans PresetConfigs/ for <json> files; missing device_type = shows on all screens
def _find_preset_configs(device_types=None):
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(os.path.join(sys._MEIPASS, "PresetConfigs"))
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    search_dirs.append(os.path.join(exe_dir, "PresetConfigs"))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(src_dir, "PresetConfigs")
    if candidate not in search_dirs:
        search_dirs.append(candidate)

    found_dir = next((d for d in search_dirs if os.path.isdir(d)), None)
    if not found_dir:
        return []

    results = []
    for fname in sorted(os.listdir(found_dir)):
        if not fname.lower().endswith(".json"):
            continue
        fpath = os.path.join(found_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        file_devtype = data.get("device_type")
        # missing device_type = show on all screens
        if device_types is not None and file_devtype is not None:
            if file_devtype not in device_types:
                continue
        results.append((os.path.splitext(fname)[0], fpath))
    return results
    
# Centered dialog helpers

# Center dlg over root; call before grab_set/wait
def _center_window(dlg, root):
    dlg.update_idletasks()
    dw = dlg.winfo_reqwidth()
    dh = dlg.winfo_reqheight()
    px = root.winfo_rootx()
    py = root.winfo_rooty()
    pw = root.winfo_width()
    ph = root.winfo_height()
    x = px + (pw - dw) // 2
    y = py + (ph - dh) // 2
    dlg.geometry(f"{dw}x{dh}+{x}+{y}")


# Modal dialog (info, yesno, error); returns True/False or None
def _centered_dialog(parent, title, message, kind="info"):
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=BG_CARD)
    dlg.resizable(False, False)
    dlg.transient(parent)

    # Build content
    tk.Label(dlg, text=message, bg=BG_CARD, fg=TEXT,
             font=(FONT_UI, 10), justify="left",
             wraplength=360, padx=24, pady=20).pack()

    result = [None]

    btn_frame = tk.Frame(dlg, bg=BG_CARD, pady=12)
    btn_frame.pack()

    def _yes():
        result[0] = True
        dlg.destroy()

    def _no():
        result[0] = False
        dlg.destroy()

    def _ok():
        result[0] = None
        dlg.destroy()

    if kind == "yesno":
        RoundedButton(btn_frame, text="Yes", command=_yes,
                      bg_color=ACCENT_BLUE, btn_width=90, btn_height=30).pack(
                          side="left", padx=(0, 8))
        RoundedButton(btn_frame, text="No", command=_no,
                      bg_color=BG_INPUT, btn_width=90, btn_height=30).pack(
                          side="left")
    elif kind == "error":
        RoundedButton(btn_frame, text="OK", command=_ok,
                      bg_color=ACCENT_RED, btn_width=90, btn_height=30).pack()
    else:  
        RoundedButton(btn_frame, text="OK", command=_ok,
                      bg_color=ACCENT_BLUE, btn_width=90, btn_height=30).pack()

    # Center over parent window once the dialog has been laid out
    dlg.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    dw = dlg.winfo_reqwidth()
    dh = dlg.winfo_reqheight()
    x = px + (pw - dw) // 2
    y = py + (ph - dh) // 2
    dlg.geometry(f"+{x}+{y}")

    dlg.grab_set()
    parent.wait_window(dlg)
    return result[0]


# Pick wired vs wireless firmware; greys out unavailable types
def _ask_wired_or_wireless(parent, has_wired=True, has_wireless=True):
    dlg = tk.Toplevel(parent)
    dlg.title("Select Firmware Type")
    dlg.configure(bg=BG_CARD)
    dlg.resizable(False, False)
    dlg.transient(parent)

    tk.Label(dlg, text="Select firmware to install:",
             bg=BG_CARD, fg=TEXT, font=(FONT_UI, 10),
             justify="center", padx=24, pady=16).pack()

    result = [None]

    btn_frame = tk.Frame(dlg, bg=BG_CARD, pady=12)
    btn_frame.pack()

    def _pick(val):
        result[0] = val
        dlg.destroy()

    ACCENT_BLUE_HOVER = "#2e7fd4"

    def _make_fw_btn(frame, text, enabled, command):
        bg_normal = ACCENT_BLUE if enabled else BG_CARD
        bg_hover  = ACCENT_BLUE_HOVER if enabled else BG_CARD
        fg_color  = "white" if enabled else TEXT_DIM
        btn = tk.Label(frame, text=text, width=12,
                       bg=bg_normal, fg=fg_color,
                       font=(FONT_UI, 10, "bold"),
                       relief="flat", padx=8, pady=6,
                       cursor="hand2" if enabled else "arrow")
        if enabled:
            btn.bind("<Enter>", lambda e: btn.config(bg=bg_hover))
            btn.bind("<Leave>", lambda e: btn.config(bg=bg_normal))
            btn.bind("<Button-1>", lambda e: command())
        btn.pack(side="left", padx=8)
        return btn

    _make_fw_btn(btn_frame, "Wired",    has_wired,    lambda: _pick("wired"))
    _make_fw_btn(btn_frame, "Wireless", has_wireless, lambda: _pick("wireless"))

    dlg.update_idletasks()
    pw = parent.winfo_width();  ph = parent.winfo_height()
    px = parent.winfo_rootx(); py = parent.winfo_rooty()
    dw = dlg.winfo_reqwidth(); dh = dlg.winfo_reqheight()
    dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")

    dlg.grab_set()
    parent.wait_window(dlg)
    return result[0]


# Update check

# Fetch latest tag/URL; tries /releases/latest then fallback to /tags
def _fetch_latest_release():
    import urllib.request, json
    headers = {"User-Agent": "OCC-Configurator"}

    # Try published releases first
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            tag = data.get("tag_name", "").lstrip("v")
            if tag:
                return tag, data.get("html_url", RELEASES_PAGE)
    except Exception:
        pass

    # Fall back to tags list
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data:
                tag = data[0]["name"].lstrip("v")
                html_url = f"https://github.com/{GITHUB_REPO}/releases/tag/{data[0]['name']}"
                return tag, html_url
    except Exception:
        pass

    return None, None

# Check if latest version > current (dot-separated)
def _version_is_newer(latest, current):
    try:
        return tuple(int(x) for x in latest.split(".")) > \
               tuple(int(x) for x in current.split("."))
    except Exception:
        return False

# Notify user of update; opens browser on OK
def _show_update_dialog(root, latest_version, download_url):
    import tkinter.messagebox as mb
    import webbrowser
    msg = (
        f"A newer version of OCC is available!\n\n"
        f"Your version:  {APP_VERSION}\n"
        f"Latest version:  {latest_version}\n\n"
        "Click OK to open the download page."
    )
    if mb.askokcancel("Update Available", msg, parent=root):
        webbrowser.open(download_url)


# Flashing overlay; returns (dlg, close_fn)
def _make_flash_popup(root):
    dlg = tk.Toplevel(root)
    dlg.title("Flashing Firmware")
    dlg.configure(bg=BG_CARD)
    dlg.resizable(False, False)
    dlg.transient(root)
    dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # user can't close mid-flash
    tk.Label(dlg, text="⚡  Flashing firmware…\nplease wait",
             bg=BG_CARD, fg=TEXT, font=(FONT_UI, 11),
             justify="center", padx=32, pady=28).pack()
    dlg.update_idletasks()
    pw = root.winfo_width();  ph = root.winfo_height()
    rx = root.winfo_rootx(); ry = root.winfo_rooty()
    dw = dlg.winfo_reqwidth(); dh = dlg.winfo_reqheight()
    dlg.geometry(f"+{rx + (pw - dw) // 2}+{ry + (ph - dh) // 2}")
    dlg.grab_set()

    def _close():
        if dlg.winfo_exists():
            dlg.grab_release()
            dlg.destroy()

    return dlg, _close
