"""AntiSlop — cross-platform privacy patcher GUI.

Launches, auto-detects the host OS, and switches to an OS-specific
screen listing privacy patches. If the OS can't be detected, the user
is asked to pick one of: Windows, Linux, BSD, macOS.

Patch actions are defined in the PATCHES registry below; each entry's
`apply` callable does the actual work and returns a status string.
"""

import platform
import sys
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "AntiSlop Privacy Patcher"
SUPPORTED = ("Windows", "Linux", "BSD", "macOS")


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


PATCHES = {
    "Windows": [
        {"name": "Disable telemetry service",
         "desc": "Stops and disables the DiagTrack (Connected User Experiences) service.",
         "apply": _stub("DiagTrack service disabled (stub)")},
        {"name": "Disable advertising ID",
         "desc": "Turns off the per-user advertising identifier used for ad tracking.",
         "apply": _stub("Advertising ID disabled (stub)")},
        {"name": "Disable Cortana / online search",
         "desc": "Prevents Start Menu searches from being sent to Bing.",
         "apply": _stub("Web search in Start Menu disabled (stub)")},
        {"name": "Disable activity history upload",
         "desc": "Stops Timeline/activity history from syncing to Microsoft.",
         "apply": _stub("Activity history upload disabled (stub)")},
        {"name": "Disable diagnostic data (set to Required only)",
         "desc": "Sets telemetry level to the minimum allowed by the edition.",
         "apply": _stub("Diagnostic data set to Required (stub)")},
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

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("640x560")
        self.minsize(520, 420)

        self._frame = None
        detected = detect_os()
        if detected:
            self.show_patch_screen(detected, auto=True)
        else:
            self.show_select_screen()

    def _swap(self, frame):
        if self._frame is not None:
            self._frame.destroy()
        self._frame = frame
        self._frame.pack(fill="both", expand=True)

    def show_select_screen(self):
        self._swap(OSSelectFrame(self))

    def show_patch_screen(self, os_name, auto=False):
        self._swap(PatchFrame(self, os_name, auto=auto))


class OSSelectFrame(ttk.Frame):
    """Shown only when auto-detection fails."""

    def __init__(self, master):
        super().__init__(master, padding=24)
        ttk.Label(self, text=APP_NAME, font=("TkDefaultFont", 16, "bold")).pack(pady=(8, 4))
        ttk.Label(
            self,
            text="Could not detect your operating system.\nWhich OS are you running?",
            justify="center",
        ).pack(pady=(0, 16))

        for os_name in SUPPORTED:
            ttk.Button(
                self, text=os_name, width=24,
                command=lambda n=os_name: master.show_patch_screen(n),
            ).pack(pady=4)


class PatchFrame(ttk.Frame):
    """OS-specific screen listing that OS's privacy patches."""

    def __init__(self, master, os_name, auto=False):
        super().__init__(master, padding=16)
        self.os_name = os_name

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text=f"{os_name} Privacy Patches",
                  font=("TkDefaultFont", 15, "bold")).pack(side="left")
        ttk.Button(header, text="Change OS",
                   command=master.show_select_screen).pack(side="right")

        detect_note = "auto-detected" if auto else "manually selected"
        ttk.Label(self, text=f"Operating system: {os_name} ({detect_note})",
                  foreground="gray").pack(anchor="w", pady=(2, 10))

        # Patch checkboxes
        box = ttk.LabelFrame(self, text="Available patches", padding=10)
        box.pack(fill="both", expand=False)

        self.vars = []
        for patch in PATCHES[self.os_name]:
            var = tk.BooleanVar(value=True)
            row = ttk.Frame(box)
            row.pack(fill="x", pady=2)
            ttk.Checkbutton(row, text=patch["name"], variable=var).pack(anchor="w")
            ttk.Label(row, text=patch["desc"], foreground="gray",
                      wraplength=540, justify="left").pack(anchor="w", padx=(24, 0))
            self.vars.append(var)

        # Action buttons
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=10)
        ttk.Button(actions, text="Select All",
                   command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(actions, text="Select None",
                   command=lambda: self._set_all(False)).pack(side="left", padx=6)
        ttk.Button(actions, text="Apply Selected Patches",
                   command=self.apply_selected).pack(side="right")

        # Log output
        log_box = ttk.LabelFrame(self, text="Log", padding=6)
        log_box.pack(fill="both", expand=True)
        self.log = tk.Text(log_box, height=8, state="disabled", wrap="word")
        scroll = ttk.Scrollbar(log_box, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self._log(f"Ready. {len(PATCHES[self.os_name])} patches available for {os_name}.")

    def _set_all(self, value):
        for var in self.vars:
            var.set(value)

    def _log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
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

        ok = failed = 0
        for patch in selected:
            try:
                result = patch["apply"]()
                self._log(f"[OK] {patch['name']}: {result}")
                ok += 1
            except Exception as exc:  # keep going if one patch fails
                self._log(f"[FAILED] {patch['name']}: {exc}")
                failed += 1
        self._log(f"Done — {ok} applied, {failed} failed.")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
