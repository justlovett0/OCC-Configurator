import sys, os, json, threading, tempfile, subprocess, uuid
import tkinter as tk
from .constants import (BG_CARD, BG_INPUT, TEXT, TEXT_DIM, ACCENT_BLUE,
                         ACCENT_RED, GITHUB_REPO, RELEASES_PAGE)
from .fonts import FONT_UI, APP_VERSION
from .widgets import RoundedButton

IS_WINDOWS = sys.platform == "win32"
CONTROLLER_SIGNAL_LABEL = "XInput" if IS_WINDOWS else "Controller Signal"
PLAY_MODE_LABEL = "XInput" if IS_WINDOWS else "play mode"
PLAY_MODE_DETECTED_TEXT = "via XInput" if IS_WINDOWS else "in play mode"
HOST_SYSTEM_LABEL = "Windows" if IS_WINDOWS else "the system"


def _format_detected_status(label, count):
    return f"{label} detected {PLAY_MODE_DETECTED_TEXT}  ({count} device{'s' if count > 1 else ''})"


def _signal_unavailable_message():
    if IS_WINDOWS:
        return "XInput is not available on this system."
    return "Play-mode controller signaling is not available on this system."


def _mousewheel_units(event):
    delta = getattr(event, "delta", 0)
    if delta:
        return int(-1 * (delta / 120))
    event_num = getattr(event, "num", None)
    if event_num == 4:
        return -1
    if event_num == 5:
        return 1
    return None


def _bind_global_mousewheel(widget, callback):
    widget.bind_all("<MouseWheel>", callback)
    widget.bind_all("<Button-4>", callback)
    widget.bind_all("<Button-5>", callback)


def _unbind_global_mousewheel(widget):
    widget.unbind_all("<MouseWheel>")
    widget.unbind_all("<Button-4>")
    widget.unbind_all("<Button-5>")


def _bind_mousewheel(widget, callback):
    widget.bind("<MouseWheel>", callback)
    widget.bind("<Button-4>", callback)
    widget.bind("<Button-5>", callback)

# Scans PresetConfigs/ for <json> files; missing device_type can optionally show on all screens
def _find_preset_configs(device_types=None, allow_unspecified=True):
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
        if device_types is not None:
            if file_devtype is None:
                if not allow_unspecified:
                    continue
            elif file_devtype not in device_types:
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

    dlg.deiconify()
    dlg.lift(parent)
    dlg.focus_force()
    dlg.grab_set()
    parent.wait_window(dlg)
    return result[0]


# Update check

def _is_packaged_windows_exe():
    if not IS_WINDOWS:
        return False
    if not getattr(sys, "frozen", False):
        return False
    exe_path = sys.executable
    return bool(exe_path and exe_path.lower().endswith(".exe") and os.path.isfile(exe_path))


def _select_windows_configurator_asset(assets):
    for asset in assets or []:
        name = str(asset.get("name", ""))
        lowered = name.lower()
        if not lowered.endswith(".exe"):
            continue
        if "configurator" not in lowered:
            continue
        if "installer" in lowered or "setup" in lowered:
            continue
        download_url = asset.get("browser_download_url")
        if download_url:
            return {
                "asset_name": name,
                "asset_url": download_url,
            }
    return {
        "asset_name": None,
        "asset_url": None,
    }


# Fetch latest release metadata. Falls back to tags for manual-download links.
def _fetch_latest_release():
    import urllib.request

    headers = {
        "User-Agent": "OCC-Configurator",
        "Accept": "application/vnd.github+json",
    }

    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list):
                for release in data:
                    if release.get("draft"):
                        continue
                    tag_name = str(release.get("tag_name", "")).strip()
                    version = tag_name.lstrip("v")
                    if not version:
                        continue
                    asset_info = _select_windows_configurator_asset(release.get("assets"))
                    return {
                        "version": version,
                        "page_url": release.get("html_url", RELEASES_PAGE),
                        "asset_name": asset_info["asset_name"],
                        "asset_url": asset_info["asset_url"],
                    }
    except Exception:
        pass

    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data:
                tag_name = str(data[0].get("name", "")).strip()
                version = tag_name.lstrip("v")
                if version:
                    return {
                        "version": version,
                        "page_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}",
                        "asset_name": None,
                        "asset_url": None,
                    }
    except Exception:
        pass

    return None

# Check if latest version > current (dot-separated)
def _version_is_newer(latest, current):
    try:
        return tuple(int(x) for x in latest.split(".")) > \
               tuple(int(x) for x in current.split("."))
    except Exception:
        return False

# Notify user of update; offers manual download or in-place Windows EXE update
def _show_update_dialog(root, release_info):
    import webbrowser
    import tkinter.messagebox as mb

    if not release_info:
        return

    latest_version = release_info.get("version", "?")
    page_url = release_info.get("page_url") or RELEASES_PAGE
    auto_update_ready = (
        APP_VERSION != "dev"
        and _is_packaged_windows_exe()
        and bool(release_info.get("asset_url"))
    )

    dlg = tk.Toplevel(root)
    dlg.title("Update Available")
    dlg.configure(bg=BG_CARD)
    dlg.resizable(False, False)
    dlg.transient(root)

    body = tk.Frame(dlg, bg=BG_CARD, padx=24, pady=20)
    body.pack(fill="both", expand=True)

    tk.Label(
        body,
        text="A newer version of OCC is available!",
        bg=BG_CARD,
        fg=TEXT,
        font=(FONT_UI, 11, "bold"),
        anchor="w",
        justify="left",
    ).pack(anchor="w")

    tk.Label(
        body,
        text=(
            f"Your version:  {APP_VERSION}\n"
            f"Latest version:  {latest_version}"
        ),
        bg=BG_CARD,
        fg=TEXT,
        font=(FONT_UI, 10),
        anchor="w",
        justify="left",
        pady=12,
    ).pack(anchor="w")

    status_text = (
        "Choose how you want to install the update."
        if auto_update_ready else
        "Automatic install is unavailable for this build. You can still open the GitHub release page."
    )
    status_var = tk.StringVar(value=status_text)
    tk.Label(
        body,
        textvariable=status_var,
        bg=BG_CARD,
        fg=TEXT_DIM,
        font=(FONT_UI, 9),
        wraplength=420,
        justify="left",
        anchor="w",
        height=4,
    ).pack(anchor="w", pady=(0, 14))

    btn_frame = tk.Frame(body, bg=BG_CARD)
    btn_frame.pack(fill="x")

    update_btn_ref = {"btn": None}
    manual_btn_ref = {"btn": None}
    cancel_btn_ref = {"btn": None}
    busy = {"value": False}

    def _set_buttons_enabled(enabled):
        state = "normal" if enabled else "disabled"
        if manual_btn_ref["btn"] is not None:
            manual_btn_ref["btn"].set_state(state)
        if cancel_btn_ref["btn"] is not None:
            cancel_btn_ref["btn"].set_state(state)
        if update_btn_ref["btn"] is not None:
            update_btn_ref["btn"].set_state("normal" if enabled and auto_update_ready else "disabled")

    def _open_download_page():
        if busy["value"]:
            return
        webbrowser.open(page_url)

    def _cancel():
        if busy["value"]:
            return
        dlg.destroy()

    def _begin_restart(script_path):
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", "/min", script_path],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                close_fds=True,
            )
        except Exception as exc:
            mb.showerror(
                "Update Failed",
                f"The updater was downloaded, but OCC could not launch the replacement helper.\n\n{exc}",
                parent=dlg,
            )
            status_var.set("Automatic install failed to launch. You can still use manual download.")
            busy["value"] = False
            _set_buttons_enabled(True)
            return

        dlg.destroy()
        root.after(50, root.destroy)

    def _finish_update(result):
        if not dlg.winfo_exists():
            return
        if result.get("ok"):
            _begin_restart(result["script_path"])
            return

        busy["value"] = False
        _set_buttons_enabled(True)
        status_var.set("Automatic install failed. You can retry or use manual download.")
        mb.showerror("Update Failed", result.get("error", "Unknown update error."), parent=dlg)

    def _download_update_worker():
        result = _prepare_windows_self_update(release_info)
        root.after(0, lambda: _finish_update(result))

    def _update_now():
        if busy["value"]:
            return
        if not auto_update_ready:
            status_var.set("Automatic install is unavailable for this build. Opening the release page instead.")
            _open_download_page()
            return

        busy["value"] = True
        status_var.set("Downloading the latest OCC Configurator and preparing the updater...")
        _set_buttons_enabled(False)
        threading.Thread(target=_download_update_worker, daemon=True).start()

    update_btn_ref["btn"] = RoundedButton(
        btn_frame,
        text="Update Now",
        command=_update_now,
        bg_color=ACCENT_RED if auto_update_ready else BG_INPUT,
        btn_width=120,
        btn_height=32,
    )
    update_btn_ref["btn"].pack(side="left", padx=(0, 8))

    manual_btn_ref["btn"] = RoundedButton(
        btn_frame,
        text="Open Download Page",
        command=_open_download_page,
        bg_color=ACCENT_BLUE,
        btn_width=173,
        btn_height=32,
    )
    manual_btn_ref["btn"].pack(side="left", padx=(0, 8))

    cancel_btn_ref["btn"] = RoundedButton(
        btn_frame,
        text="Cancel",
        command=_cancel,
        bg_color=BG_INPUT,
        btn_width=90,
        btn_height=32,
    )
    cancel_btn_ref["btn"].pack(side="left")

    _set_buttons_enabled(True)

    dlg.protocol("WM_DELETE_WINDOW", _cancel)
    _center_window(dlg, root)
    dlg.grab_set()
    dlg.focus_force()
    root.wait_window(dlg)


def _prepare_windows_self_update(release_info):
    import urllib.request

    if not _is_packaged_windows_exe():
        return {"ok": False, "error": "Automatic update is only available in the packaged Windows executable."}

    asset_url = release_info.get("asset_url")
    asset_name = release_info.get("asset_name") or ""
    if not asset_url or not asset_name.lower().endswith(".exe"):
        return {"ok": False, "error": "No downloadable configurator executable was found for the latest release."}

    target_exe = os.path.abspath(sys.executable)
    target_name = os.path.basename(target_exe)
    temp_root = os.path.join(tempfile.gettempdir(), f"occ_update_{uuid.uuid4().hex}")
    os.makedirs(temp_root, exist_ok=True)

    download_path = os.path.join(temp_root, target_name)
    script_path = os.path.join(temp_root, "apply_update.cmd")

    try:
        headers = {
            "User-Agent": "OCC-Configurator",
            "Accept": "application/octet-stream",
        }
        req = urllib.request.Request(asset_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp, open(download_path, "wb") as out_f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out_f.write(chunk)
    except Exception as exc:
        return {"ok": False, "error": f"Could not download the latest configurator build.\n\n{exc}"}

    if not os.path.isfile(download_path):
        return {"ok": False, "error": "The updater download did not create a replacement executable."}
    if os.path.getsize(download_path) <= 0:
        return {"ok": False, "error": "The downloaded update was empty."}
    if not download_path.lower().endswith(".exe"):
        return {"ok": False, "error": "The downloaded update was not an executable file."}

    try:
        with open(script_path, "w", encoding="utf-8", newline="\r\n") as script:
            script.write(_build_windows_update_script(target_exe, download_path, temp_root))
    except Exception as exc:
        return {"ok": False, "error": f"Could not create the updater helper script.\n\n{exc}"}

    return {"ok": True, "script_path": script_path}


def _build_windows_update_script(target_exe, download_path, temp_root):
    def _q(value):
        return value.replace('"', '""')

    target_dir = os.path.dirname(target_exe)
    error_message = (
        "OCC Configurator could not complete the automatic update. "
        "Please download the newest version manually from the GitHub releases page."
    )
    return f"""@echo off
setlocal
set "TARGET_EXE={_q(target_exe)}"
set "TARGET_DIR={_q(target_dir)}"
set "DOWNLOAD_EXE={_q(download_path)}"
set "TEMP_ROOT={_q(temp_root)}"
set "ERROR_TEXT={_q(error_message)}"

for /L %%I in (1,1,60) do (
    if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%" >nul 2>&1
    copy /y "%DOWNLOAD_EXE%" "%TARGET_EXE%" >nul 2>&1
    if not errorlevel 1 goto launch
    timeout /t 1 /nobreak >nul
)
goto fail

:launch
set "_MEIPASS2="
set "_PYI_APPLICATION_HOME_DIR="
set "_PYI_ARCHIVE_FILE="
set "_PYI_PARENT_PROCESS_LEVEL="
set "_PYI_SPLASH_IPC="
set "PYINSTALLER_RESET_ENVIRONMENT=1"
start "" /d "%TARGET_DIR%" "%TARGET_EXE%"
del /f /q "%DOWNLOAD_EXE%" >nul 2>&1
rd /s /q "%TEMP_ROOT%" >nul 2>&1
exit /b 0

:fail
> "%TEMP_ROOT%\\update_failed.txt" echo %ERROR_TEXT%
exit /b 1
"""


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
    dw = int(dlg.winfo_reqwidth() * 2.5)
    dh = int(dlg.winfo_reqheight() * 1.4)
    dlg.geometry(f"{dw}x{dh}+{rx + (pw - dw) // 2}+{ry + (ph - dh) // 2}")
    dlg.grab_set()

    def _close():
        if dlg.winfo_exists():
            dlg.grab_release()
            dlg.destroy()

    return dlg, _close
