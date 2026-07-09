"""PrivacyWarden — cross-platform privacy patcher GUI.

Launches, auto-detects the host OS, and switches to an OS-specific
screen listing privacy patches. If the OS can't be detected, the user
is asked to pick one of: Windows, Linux, BSD, macOS.

Patch actions are defined in the PATCHES registry below; each entry's
`apply` callable does the actual work and returns a status string.
"""

import ctypes
import datetime
import json
import os
import platform
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

if platform.system() == "Windows":
    import winreg

APP_NAME = "PrivacyWarden"
SUPPORTED = ("Windows", "Linux", "BSD", "macOS")

LOG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output.out")
SETTINGS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch_settings.json")

# Material You (Material Design 3) tonal palettes — seed color: purple (#6750A4)
LIGHT_PALETTE = {
    "bg": "#FEF7FF",              # surface / surface-dim
    "card": "#F7F2FA",            # surface container
    "border": "#CAC4D0",          # outline-variant
    "accent": "#6750A4",          # primary
    "accent_dark": "#4F378B",     # primary (pressed/hover tonal step)
    "accent_container": "#EADDFF",  # primary container
    "on_accent": "#FFFFFF",       # text/icons drawn on top of "accent"
    "on_accent_container": "#21005D",
    "text": "#1D1B20",            # on-surface
    "muted": "#49454F",           # on-surface-variant
    "success": "#146C2E",         # tertiary-ish green, M3-friendly contrast
    "error": "#B3261E",           # error
    "warning": "#7D5700",         # on tonal warning container
    "warning_container": "#FFE08A",
}

DARK_PALETTE = {
    "bg": "#141218",              # surface (dark)
    "card": "#211F26",            # surface container (dark)
    "border": "#49454F",          # outline-variant (dark)
    "accent": "#D0BCFF",          # primary (dark theme uses a light tone)
    "accent_dark": "#B69DF8",     # primary (pressed/hover tonal step)
    "accent_container": "#4F378B",  # primary container (dark)
    "on_accent": "#381E72",       # text/icons drawn on top of "accent"
    "on_accent_container": "#EADDFF",
    "text": "#E6E0E9",            # on-surface (dark)
    "muted": "#CAC4D0",           # on-surface-variant (dark)
    "success": "#81D993",
    "error": "#F2B8B5",
    "warning": "#FFDEA1",
    "warning_container": "#4A3800",
}

PALETTE = LIGHT_PALETTE


def _set_active_palette(dark):
    global PALETTE
    PALETTE = DARK_PALETTE if dark else LIGHT_PALETTE


def _write_log_line(line):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE_PATH, "a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {line}\n")


def _load_selections():
    """Return {os_name: {patch_name: bool}}, or {} if no/invalid settings file."""
    try:
        with open(SETTINGS_FILE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_settings(settings):
    try:
        with open(SETTINGS_FILE_PATH, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2, sort_keys=True)
    except OSError:
        pass


def _save_selection(os_name, patch_name, enabled):
    selections = _load_selections()
    selections.setdefault(os_name, {})[patch_name] = enabled
    _write_settings(selections)


def _load_theme():
    """Return 'dark' or 'light' from the settings file's top-level "theme" key."""
    theme = _load_selections().get("theme")
    return theme if theme in ("light", "dark") else "dark"


def _save_theme(theme):
    selections = _load_selections()
    selections["theme"] = theme
    _write_settings(selections)


# --------------------------------------------------------------------------
# OS detection
# --------------------------------------------------------------------------

def detect_os():
    """Return one of SUPPORTED, or None if the OS can't be identified."""
    system = platform.system().lower()
    plat = sys.platform.lower()

    if system == "windows" or plat.startswith("win") or plat == "cygwin":
        return "Windows"
    if system == "darwin" or plat == "darwin":
        return "macOS"
    if "bsd" in system or "bsd" in plat or plat.startswith("dragonfly"):
        return "BSD"
    if system == "linux" or plat.startswith("linux"):
        return "Linux"
    return None


# --------------------------------------------------------------------------
# Window chrome theming (Windows only — DWM border/title bar colors)
# --------------------------------------------------------------------------

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def _colorref(hex_color):
    """Convert a "#RRGGBB" string to a Windows COLORREF (0x00BBGGRR) int."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return r | (g << 8) | (b << 16)


def _apply_window_chrome(root, dark):
    """Tint the native window border/title bar to match the app theme.

    Only supported on Windows 11 (DWMWA_BORDER_COLOR/CAPTION_COLOR are
    22H2+); silently does nothing elsewhere or on older Windows builds.
    """
    if platform.system() != "Windows":
        return
    try:
        # The toplevel's real HWND doesn't exist until Tk has realized/mapped
        # the window — querying it any earlier makes GetParent return NULL
        # and every DwmSetWindowAttribute call below silently no-op.
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        dwmapi = ctypes.windll.dwmapi
        for attribute, value in (
            (_DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0),
            (_DWMWA_BORDER_COLOR, _colorref(PALETTE["accent"])),
            (_DWMWA_CAPTION_COLOR, _colorref(PALETTE["bg"])),
            (_DWMWA_TEXT_COLOR, _colorref(PALETTE["text"])),
        ):
            c_value = ctypes.c_int(value)
            dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(c_value), ctypes.sizeof(c_value))
    except OSError:
        pass


# --------------------------------------------------------------------------
# Patch registry
#
# Each patch: {"name": ..., "desc": ..., "apply": callable() -> str}
# The apply callable should perform the change and return a short status
# message; raise an exception on failure. Stubs below are where the real
# OS-specific logic gets plugged in.
# --------------------------------------------------------------------------

def _stub(msg):
    def apply():
        # TODO: replace stub with the real patch implementation
        return msg
    return apply


# --------------------------------------------------------------------------
# Windows patch implementations
# --------------------------------------------------------------------------

def _win_is_admin():
    if platform.system() != "Windows":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _win_require_admin():
    if not _win_is_admin():
        raise PermissionError(
            "Administrator privileges required — re-run PrivacyWarden as Administrator."
        )


def _win_set_reg_dword(hive, path, name, value):
    key = winreg.CreateKeyEx(hive, path, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
    finally:
        winreg.CloseKey(key)


def _win_run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result.stdout.strip()


def _win_disable_telemetry_service():
    def apply():
        _win_require_admin()
        _win_run(["sc", "config", "DiagTrack", "start=", "disabled"])
        try:
            _win_run(["sc", "stop", "DiagTrack"])
        except RuntimeError as exc:
            if "1062" not in str(exc):  # 1062: service not started, already stopped
                raise
        return "DiagTrack service stopped and disabled"
    return apply


def _win_disable_advertising_id():
    def apply():
        _win_set_reg_dword(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo",
            "Enabled", 0,
        )
        return "Advertising ID disabled for current user"
    return apply


def _win_disable_cortana_search():
    def apply():
        path = r"Software\Microsoft\Windows\CurrentVersion\Search"
        _win_set_reg_dword(winreg.HKEY_CURRENT_USER, path, "BingSearchEnabled", 0)
        _win_set_reg_dword(winreg.HKEY_CURRENT_USER, path, "CortanaConsent", 0)
        return "Bing web search and Cortana consent disabled"
    return apply


def _win_disable_activity_history():
    def apply():
        _win_require_admin()
        path = r"SOFTWARE\Policies\Microsoft\Windows\System"
        for name in ("EnableActivityFeed", "PublishUserActivities", "UploadUserActivities"):
            _win_set_reg_dword(winreg.HKEY_LOCAL_MACHINE, path, name, 0)
        return "Activity history publishing and upload disabled via policy"
    return apply


def _win_set_diagnostic_data_minimum():
    def apply():
        _win_require_admin()
        _win_set_reg_dword(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Policies\Microsoft\Windows\DataCollection",
            "AllowTelemetry", 1,
        )
        return "Diagnostic data level set to Required/Basic (AllowTelemetry=1)"
    return apply


def _win_create_restore_point():
    """Create a System Restore point via PowerShell's Checkpoint-Computer.

    Note: Windows throttles this to one restore point per 24 hours by
    default, and System Protection must be enabled on the system drive.
    """
    _win_require_admin()
    _win_run([
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "Checkpoint-Computer -Description 'PrivacyWarden Backup' "
        "-RestorePointType MODIFY_SETTINGS",
    ])
    return "System Restore point created"


PATCHES = {
    "Windows": [
        {"name": "Disable telemetry service",
         "desc": "Stops and disables the DiagTrack (Connected User Experiences) service. Requires Administrator.",
         "apply": _win_disable_telemetry_service()},
        {"name": "Disable advertising ID",
         "desc": "Turns off the per-user advertising identifier used for ad tracking.",
         "apply": _win_disable_advertising_id()},
        {"name": "Disable Cortana / online search",
         "desc": "Prevents Start Menu searches from being sent to Bing.",
         "apply": _win_disable_cortana_search()},
        {"name": "Disable activity history upload",
         "desc": "Stops Timeline/activity history from syncing to Microsoft. Requires Administrator.",
         "apply": _win_disable_activity_history()},
        {"name": "Disable diagnostic data (set to Required only)",
         "desc": "Sets telemetry level to the minimum allowed by the edition. Requires Administrator.",
         "apply": _win_set_diagnostic_data_minimum()},
    ],
    "Linux": [
        {"name": "Disable systemd whoopsie/apport crash reporting",
         "desc": "Turns off distro crash reporters that upload core dumps.",
         "apply": _stub("Crash reporting disabled (stub)")},
        {"name": "Disable popularity-contest / package usage stats",
         "desc": "Stops the package popularity survey from phoning home.",
         "apply": _stub("Package usage stats disabled (stub)")},
        {"name": "Harden DNS (enable DNS-over-TLS in systemd-resolved)",
         "desc": "Encrypts DNS lookups to prevent ISP-level snooping.",
         "apply": _stub("DNS-over-TLS enabled (stub)")},
        {"name": "Clear shell history on logout",
         "desc": "Adds history clearing to shell logout scripts.",
         "apply": _stub("Shell history clearing configured (stub)")},
    ],
    "BSD": [
        {"name": "Harden sysctl privacy settings",
         "desc": "Applies privacy-oriented kern/net sysctl values.",
         "apply": _stub("sysctl privacy values applied (stub)")},
        {"name": "Disable sendmail daemon",
         "desc": "Stops the default sendmail service from listening.",
         "apply": _stub("sendmail disabled (stub)")},
        {"name": "Enable firewall (pf) with default-deny inbound",
         "desc": "Loads a minimal pf ruleset blocking unsolicited inbound traffic.",
         "apply": _stub("pf enabled with default-deny inbound (stub)")},
    ],
    "macOS": [
        {"name": "Disable Siri analytics & suggestions",
         "desc": "Turns off Siri data sharing and Spotlight suggestions.",
         "apply": _stub("Siri analytics disabled (stub)")},
        {"name": "Disable diagnostic & usage data submission",
         "desc": "Opts out of sending analytics to Apple and app developers.",
         "apply": _stub("Diagnostics submission disabled (stub)")},
        {"name": "Disable personalized ads",
         "desc": "Turns off Apple's ad personalization for this user.",
         "apply": _stub("Personalized ads disabled (stub)")},
        {"name": "Disable Spotlight web suggestions",
         "desc": "Stops Spotlight queries from being sent to Apple.",
         "apply": _stub("Spotlight web suggestions disabled (stub)")},
    ],
}


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

def _body_font_family():
    """Prefer Roboto (Material's type family); fall back to a Segoe UI variant."""
    try:
        import tkinter.font as tkfont
        families = set(tkfont.families())
    except Exception:
        families = set()
    for candidate in ("Roboto", "Segoe UI Variable Text", "Segoe UI"):
        if candidate in families:
            return candidate
    return "Segoe UI"


def _configure_style(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    font_family = _body_font_family()

    root.configure(background=PALETTE["bg"])

    style.configure("TFrame", background=PALETTE["bg"])
    style.configure("Card.TFrame", background=PALETTE["card"])
    style.configure("Banner.TFrame", background=PALETTE["warning_container"])

    style.configure("TLabel", background=PALETTE["bg"], foreground=PALETTE["text"],
                     font=(font_family, 10))
    style.configure("Card.TLabel", background=PALETTE["card"], foreground=PALETTE["text"],
                     font=(font_family, 10, "bold"))
    style.configure("CardDesc.TLabel", background=PALETTE["card"], foreground=PALETTE["muted"],
                     font=(font_family, 9))
    style.configure("Muted.TLabel", foreground=PALETTE["muted"], font=(font_family, 9))
    style.configure("Banner.TLabel", background=PALETTE["warning_container"], foreground=PALETTE["warning"],
                     font=(font_family, 9, "bold"))
    style.configure("Title.TLabel", font=(font_family, 17, "bold"), foreground=PALETTE["text"])
    style.configure("Subtitle.TLabel", font=(font_family, 10), foreground=PALETTE["muted"])
    style.configure("Badge.TLabel", background=PALETTE["accent"], foreground=PALETTE["on_accent"],
                     font=(font_family, 14, "bold"), anchor="center")
    style.configure("Selected.TLabel", background=PALETTE["card"], foreground=PALETTE["accent"],
                     font=(font_family, 8, "bold"))

    # Filled buttons (M3 "Filled button" — primary color, no border, tonal hover/press)
    style.configure("Accent.TButton", font=(font_family, 10, "bold"), padding=(16, 10),
                     background=PALETTE["accent"], foreground=PALETTE["on_accent"], borderwidth=0,
                     focuscolor=PALETTE["accent"])
    style.map("Accent.TButton",
              background=[("active", PALETTE["accent_dark"]), ("disabled", PALETTE["accent_container"])],
              foreground=[("disabled", PALETTE["on_accent_container"])])

    # Outlined/tonal button (M3 "Outlined button")
    style.configure("TButton", font=(font_family, 9), padding=(12, 7),
                     background=PALETTE["card"], foreground=PALETTE["accent"],
                     bordercolor=PALETTE["border"], borderwidth=1, focuscolor=PALETTE["accent"])
    style.map("TButton",
              background=[("active", PALETTE["accent_container"])],
              bordercolor=[("active", PALETTE["accent"])])

    style.configure("TCheckbutton", background=PALETTE["card"], font=(font_family, 10, "bold"),
                     foreground=PALETTE["text"])
    style.map("TCheckbutton", background=[("active", PALETTE["card"])],
              foreground=[("selected", PALETTE["accent"])])

    style.configure("TLabelframe", background=PALETTE["bg"], bordercolor=PALETTE["border"])
    style.configure("TLabelframe.Label", background=PALETTE["bg"], foreground=PALETTE["muted"],
                     font=(font_family, 9, "bold"))
    style.configure("Vertical.TScrollbar", background=PALETTE["bg"], troughcolor=PALETTE["bg"],
                     bordercolor=PALETTE["bg"], arrowcolor=PALETTE["muted"])
    return style


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self._center_window(920, 860)
        self.minsize(900, 820)

        self.dark_mode = _load_theme() == "dark"
        _set_active_palette(self.dark_mode)
        _configure_style(self)
        _apply_window_chrome(self, self.dark_mode)

        self.attributes("-alpha", 0.0)
        self.protocol("WM_DELETE_WINDOW", self._close_with_fade)

        self._frame = None
        self._screen_state = None
        detected = detect_os()
        if detected:
            self.show_patch_screen(detected, auto=True)
        else:
            self.show_select_screen()

        self._fade(target=1.0)

    def _center_window(self, width, height):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _fade(self, target, step=0.08, delay_ms=15, on_done=None):
        alpha = self.attributes("-alpha")
        if target > alpha:
            alpha = min(alpha + step, target)
        else:
            alpha = max(alpha - step, target)
        self.attributes("-alpha", alpha)
        if alpha != target:
            self.after(delay_ms, self._fade, target, step, delay_ms, on_done)
        elif on_done is not None:
            on_done()

    def _close_with_fade(self):
        self._fade(target=0.0, on_done=self.destroy)

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        _set_active_palette(self.dark_mode)
        _configure_style(self)
        _apply_window_chrome(self, self.dark_mode)
        _save_theme("dark" if self.dark_mode else "light")

        kind = self._screen_state[0]
        if kind == "patch":
            _, os_name, auto = self._screen_state
            self.show_patch_screen(os_name, auto=auto)
        else:
            self.show_select_screen()

    def _swap(self, frame):
        if self._frame is not None:
            self._frame.destroy()
        self._frame = frame
        self._frame.pack(fill="both", expand=True)

    def show_select_screen(self):
        self._screen_state = ("select",)
        self._swap(OSSelectFrame(self))

    def show_patch_screen(self, os_name, auto=False):
        self._screen_state = ("patch", os_name, auto)
        self._swap(PatchFrame(self, os_name, auto=auto))


class OSSelectFrame(ttk.Frame):
    """Shown only when auto-detection fails."""

    def __init__(self, master):
        super().__init__(master, padding=32)

        badge = ttk.Label(self, text="PW", style="Badge.TLabel", width=4)
        badge.pack(pady=(16, 12))
        ttk.Label(self, text=APP_NAME, style="Title.TLabel").pack()
        ttk.Label(
            self,
            text="Could not detect your operating system.\nWhich OS are you running?",
            style="Subtitle.TLabel", justify="center",
        ).pack(pady=(6, 24))

        for os_name in SUPPORTED:
            ttk.Button(
                self, text=os_name, width=28, style="Accent.TButton",
                command=lambda n=os_name: master.show_patch_screen(n),
            ).pack(pady=5)

        theme_text = "☀ Light Mode" if master.dark_mode else "🌙 Dark Mode"
        ttk.Button(self, text=theme_text, command=master.toggle_theme).pack(pady=(20, 0))


class PatchFrame(ttk.Frame):
    """OS-specific screen listing that OS's privacy patches."""

    def __init__(self, master, os_name, auto=False):
        super().__init__(master, padding=24)
        self.os_name = os_name

        # Header
        header = ttk.Frame(self)
        header.pack(fill="x")

        badge = ttk.Label(header, text="PW", style="Badge.TLabel", width=3)
        badge.pack(side="left", padx=(0, 12), ipady=4)

        title_col = ttk.Frame(header)
        title_col.pack(side="left", fill="x", expand=True)
        ttk.Label(title_col, text=f"{os_name} Privacy Patches", style="Title.TLabel").pack(anchor="w")
        detect_note = "auto-detected" if auto else "manually selected"
        ttk.Label(title_col, text=f"Operating system: {os_name} ({detect_note})",
                  style="Subtitle.TLabel").pack(anchor="w")

        ttk.Button(header, text="Change OS",
                   command=master.show_select_screen).pack(side="right", anchor="n")

        theme_text = "☀ Light Mode" if master.dark_mode else "🌙 Dark Mode"
        ttk.Button(header, text=theme_text,
                   command=master.toggle_theme).pack(side="right", padx=(0, 8), anchor="n")

        if os_name == "Windows":
            ttk.Button(header, text="Create Windows Backup",
                       command=self._create_windows_backup).pack(side="right", padx=(0, 8), anchor="n")

        ttk.Separator(self).pack(fill="x", pady=16)

        if os_name == "Windows" and not _win_is_admin():
            banner = ttk.Frame(self, style="Banner.TFrame", padding=10)
            banner.pack(fill="x", pady=(0, 16))
            ttk.Label(
                banner,
                text="⚠ Not running as Administrator — some patches will fail.",
                style="Banner.TLabel",
            ).pack(side="left")
            ttk.Button(banner, text="Relaunch as Administrator",
                       command=self._relaunch_as_admin).pack(side="right")

        # Patch cards (fixed-height scrollable area — keeps the log/buttons
        # visible regardless of how many patches an OS has)
        ttk.Label(self, text="AVAILABLE PATCHES", style="Muted.TLabel").pack(anchor="w")

        list_wrap = ttk.Frame(self)
        list_wrap.pack(fill="x", pady=(4, 0))

        canvas = tk.Canvas(list_wrap, background=PALETTE["bg"], highlightthickness=0,
                            height=230)
        list_scroll = ttk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=list_scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")

        box = ttk.Frame(canvas)
        box_id = canvas.create_window((0, 0), window=box, anchor="nw")

        def _on_box_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfigure(box_id, width=event.width)

        box.bind("<Configure>", _on_box_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        saved_selections = _load_selections().get(self.os_name, {})

        self.vars = []
        for patch in PATCHES[self.os_name]:
            enabled = saved_selections.get(patch["name"], False)
            var = tk.BooleanVar(value=enabled)
            card = ttk.Frame(box, style="Card.TFrame", padding=12)
            card.pack(fill="x", pady=4, padx=2)

            selected_label = ttk.Label(card, text="SELECTED", style="Selected.TLabel")
            if enabled:
                selected_label.pack(side="right", padx=(12, 4))

            left = ttk.Frame(card, style="Card.TFrame")
            left.pack(side="left", fill="x", expand=True)
            ttk.Checkbutton(left, text=patch["name"], variable=var,
                             style="TCheckbutton").pack(anchor="w")
            ttk.Label(left, text=patch["desc"], style="CardDesc.TLabel",
                      wraplength=650, justify="left").pack(anchor="w", padx=(24, 0), pady=(2, 0))

            def _on_toggle(*_args, v=var, lbl=selected_label, name=patch["name"]):
                is_on = v.get()
                if is_on:
                    lbl.pack(side="right", padx=(12, 4))
                else:
                    lbl.pack_forget()
                _save_selection(self.os_name, name, is_on)

            var.trace_add("write", _on_toggle)
            self.vars.append(var)

        # Action buttons
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=14)
        ttk.Button(actions, text="Select All",
                   command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(actions, text="Select None",
                   command=lambda: self._set_all(False)).pack(side="left", padx=6)
        ttk.Button(actions, text="Apply Selected Patches", style="Accent.TButton",
                   command=self.apply_selected).pack(side="right")

        # Log output
        log_box = ttk.LabelFrame(self, text="LOG", padding=8)
        log_box.pack(fill="both", expand=True)
        self.log = tk.Text(log_box, height=6, state="disabled", wrap="word",
                            background=PALETTE["card"], foreground=PALETTE["text"],
                            font=("Consolas", 9), borderwidth=0, relief="flat",
                            padx=8, pady=6)
        self.log.tag_configure("ok", foreground=PALETTE["success"])
        self.log.tag_configure("failed", foreground=PALETTE["error"])
        self.log.tag_configure("muted", foreground=PALETTE["muted"])
        scroll = ttk.Scrollbar(log_box, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self._log(f"Ready. {len(PATCHES[self.os_name])} patches available for {os_name}.", "muted")

    def _relaunch_as_admin(self):
        try:
            params = " ".join(f'"{arg}"' for arg in sys.argv)
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not relaunch as Administrator: {exc}")
            return
        self.master.destroy()

    def _create_windows_backup(self):
        if not messagebox.askyesno(
            APP_NAME,
            "Create a Windows System Restore point now?\n\n"
            "This lets you roll back registry/service changes via "
            "System Restore if a patch causes problems. Windows allows "
            "only one restore point per 24 hours by default.",
        ):
            return
        try:
            result = _win_create_restore_point()
            self._log(f"[OK] Windows backup: {result}", "ok")
            _write_log_line(f"Windows System Backup - SUCCESS - {result}")
        except Exception as exc:
            self._log(f"[FAILED] Windows backup: {exc}", "failed")
            _write_log_line(f"Windows System Backup - FAILED - {exc}")
            messagebox.showerror(APP_NAME, f"Could not create restore point: {exc}")

    def _set_all(self, value):
        for var in self.vars:
            var.set(value)

    def _log(self, message, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def apply_selected(self):
        selected = [p for p, v in zip(PATCHES[self.os_name], self.vars) if v.get()]
        if not selected:
            messagebox.showinfo(APP_NAME, "No patches selected.")
            return
        if not messagebox.askyesno(
            APP_NAME,
            f"Apply {len(selected)} patch(es) to this {self.os_name} system?",
        ):
            return

        _write_log_line(f"=== Applying {len(selected)} patch(es) for {self.os_name} ===")

        ok = failed = 0
        for patch in selected:
            try:
                result = patch["apply"]()
                self._log(f"[OK] {patch['name']}: {result}", "ok")
                _write_log_line(f"{patch['name']} - SUCCESS - {result}")
                ok += 1
            except Exception as exc:  # keep going if one patch fails
                self._log(f"[FAILED] {patch['name']}: {exc}", "failed")
                _write_log_line(f"{patch['name']} - FAILED - {exc}")
                failed += 1
        self._log(f"Done — {ok} applied, {failed} failed.", "muted")
        _write_log_line(f"Done - {ok} applied, {failed} failed.")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
