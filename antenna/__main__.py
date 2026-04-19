"""Top-level entry for `python -m antenna`.

Picks the best shell automatically:
  - Windows + pystray installed → antenna.tray (system tray + toasts)
  - everything else             → antenna.agent (console)

Users who want to force console mode on Windows can do
    python -m antenna.agent
or set the env var SPELLCASTER_ANTENNA_NO_TRAY=1 before launch.
"""

from __future__ import annotations

import os
import sys
import traceback


# ── Crash trap — windowless exe has no stderr, so any startup
# exception disappears. Mirror the traceback to a file inside
# ~/.spellcaster/ so we can debug "nothing happens when I launch the
# .exe". The hook is installed BEFORE we touch anything that could
# fail (tray backends, tkinter, pystray, PIL), so even an import-
# error in one of those lands here.

def _install_crash_trap() -> None:
    home = os.path.expanduser("~")
    log_dir = os.path.join(home, ".spellcaster")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        return
    log_path = os.path.join(log_dir, "antenna-crash.log")

    def hook(exc_type, exc, tb):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                import datetime as _dt
                f.write(f"\n\n=== {_dt.datetime.now().isoformat()} ===\n")
                f.write(f"python  : {sys.version}\n")
                f.write(f"argv    : {sys.argv}\n")
                f.write(f"frozen  : {getattr(sys, 'frozen', False)}\n")
                f.write(f"meipass : {getattr(sys, '_MEIPASS', '')}\n\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        # Also re-raise so normal handling (console stderr) still works.
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


_install_crash_trap()


def _log_startup_note(msg: str) -> None:
    """Append a single diagnostic line to antenna-crash.log. Used by
    _prefer_tray so "tray didn't start" is debuggable on a --noconsole
    exe where stderr goes nowhere."""
    try:
        home = os.path.expanduser("~")
        log_path = os.path.join(home, ".spellcaster", "antenna-crash.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        import datetime as _dt
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{_dt.datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def _show_user_warning(title: str, msg: str) -> None:
    """Pop a native Windows message box with the warning so the user
    isn't left staring at nothing. Uses ctypes (stdlib) so we don't
    need pystray or tkinter — those might be the things that failed.
    Silent no-op on non-Windows or when user32 isn't reachable."""
    if os.name != "nt":
        return
    try:
        import ctypes
        MB_ICONWARNING = 0x30
        MB_OK = 0x0
        MB_TOPMOST = 0x40000
        # MessageBoxW unicode variant
        ctypes.windll.user32.MessageBoxW(
            0, msg, title, MB_ICONWARNING | MB_OK | MB_TOPMOST)
    except Exception:
        pass


def _prefer_tray() -> bool:
    if os.name != "nt":
        _log_startup_note(f"tray skipped: os.name={os.name} (Windows only)")
        return False
    if os.environ.get("SPELLCASTER_ANTENNA_NO_TRAY", "").strip() in ("1", "true", "yes"):
        _log_startup_note("tray skipped: SPELLCASTER_ANTENNA_NO_TRAY set")
        return False
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as e:  # noqa: BLE001
        _log_startup_note(
            f"tray disabled: pystray/PIL import failed "
            f"({type(e).__name__}: {e})")
        # On the compiled --noconsole .exe the antenna would otherwise
        # just… run invisibly. Pop a visible warning so the user knows
        # what broke and where to look for the full log.
        _show_user_warning(
            "Spellcaster Antenna — tray disabled",
            "The tray icon couldn't start because a required package "
            "(pystray or Pillow) is missing.\n\n"
            f"Reason: {type(e).__name__}: {e}\n\n"
            "The antenna is still running in console mode on port 7334 "
            "and will pair with the Wizard Guild normally — you just "
            "won't see a tray icon.\n\n"
            "Full log: %USERPROFILE%\\.spellcaster\\antenna-crash.log")
        return False
    _log_startup_note("tray path selected")
    return True


def _first_run_shortcut_prompt() -> None:
    """Windows-only: on the very first launch of the tray-only .exe,
    pop a tk dialog asking whether to create a desktop icon, a Start
    Menu entry, and / or launch at Windows startup. The compiled
    binary has no console, so the install_antenna.bat's text prompt
    can't surface these choices anymore — this dialog replaces it.

    Gated by a sentinel at ~/.spellcaster/antenna_shortcuts_done so
    it fires exactly once. Users can revisit the choice any time via
    the tray menu's Reinstall / Enable-at-startup entries.
    """
    if os.name != "nt":
        return
    home = os.path.expanduser("~")
    sentinel_dir = os.path.join(home, ".spellcaster")
    sentinel = os.path.join(sentinel_dir, "antenna_shortcuts_done")
    if os.path.isfile(sentinel):
        return
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as _e:  # noqa: BLE001
        # Log AND surface — silent "dialog didn't appear, sentinel
        # got written anyway" was exactly the bug the audit flagged:
        # future launches would skip the prompt forever. We neither
        # write the sentinel nor swallow silently.
        _log_startup_note(
            f"first-run dialog skipped: tkinter import failed "
            f"({type(_e).__name__}: {_e})")
        _show_user_warning(
            "Spellcaster Antenna — setup skipped",
            "The first-run setup dialog couldn't start because Tcl/Tk "
            "(tkinter) isn't bundled in this build.\n\n"
            f"Reason: {type(_e).__name__}: {_e}\n\n"
            "The antenna will start normally. To create a desktop icon, "
            "a Start Menu entry, or launch-at-login later, right-click "
            "the tray icon (if present) and pick the matching menu "
            "entry. You can re-run this prompt by deleting "
            "%USERPROFILE%\\.spellcaster\\antenna_shortcuts_done and "
            "relaunching the antenna.")
        return
    try:
        from . import install_shortcuts as _shc
    except Exception:  # noqa: BLE001
        return

    choices = {"desktop": True, "start_menu": True, "startup": False}

    root = tk.Tk()
    root.title("Spellcaster Antenna — setup")
    root.attributes("-topmost", True)
    root.configure(bg="#12101d")
    root.minsize(420, 250)

    frm = ttk.Frame(root, padding=22)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Welcome — how should the antenna launch?",
               foreground="#ffd700", background="#12101d",
               font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(frm, text=(
                "Pick any combination. You can change this any time\n"
                "from the tray icon → right-click → Reinstall / Startup."),
               foreground="#c4b8e3", background="#12101d",
               font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 14))

    vars_ = {}
    for key, label, default in (
        ("desktop",    "Create a desktop icon",                       True),
        ("start_menu", "Add to the Start Menu \u2192 Programs",          True),
        ("startup",    "Launch automatically at every Windows login", False),
    ):
        v = tk.BooleanVar(value=default)
        cb = tk.Checkbutton(frm, text=label, variable=v,
                             bg="#12101d", fg="#e8e6f5",
                             activebackground="#1a1730",
                             activeforeground="#ffffff",
                             selectcolor="#1a1730",
                             font=("Segoe UI", 10))
        cb.pack(anchor="w", pady=2)
        vars_[key] = v

    status_text = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status_text,
               foreground="#8a7eaf", background="#12101d",
               font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 0))

    def apply_and_close():
        for k in choices:
            choices[k] = bool(vars_[k].get())
        result = _shc.install_shortcuts(
            desktop=choices["desktop"],
            start_menu=choices["start_menu"],
            startup=choices["startup"],
        )
        ok = sum(1 for k in ("desktop", "start_menu", "startup")
                  if result.get(k))
        if result.get("errors"):
            status_text.set(
                f"Created {ok}/3. Issues: "
                + ", ".join(result["errors"])[:120])
            root.after(2500, root.destroy)
        else:
            try:
                os.makedirs(sentinel_dir, exist_ok=True)
                with open(sentinel, "w", encoding="utf-8") as f:
                    f.write("done\n")
            except Exception:  # noqa: BLE001
                pass
            root.destroy()

    def skip_and_close():
        # Still write the sentinel so we don't nag next boot.
        try:
            os.makedirs(sentinel_dir, exist_ok=True)
            with open(sentinel, "w", encoding="utf-8") as f:
                f.write("skipped\n")
        except Exception:  # noqa: BLE001
            pass
        root.destroy()

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(18, 0))
    ttk.Button(btns, text="Skip", command=skip_and_close).pack(side="left")
    ttk.Button(btns, text="Install",
                command=apply_and_close).pack(side="right")

    # Centre on screen
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw = root.winfo_screenwidth(); sh = root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
    root.mainloop()


def main() -> int:
    # Crash logger for EVERY code path below — if pystray or tkinter
    # fails silently on a windowless exe, the crash log is the only
    # way to tell the user what happened without recompiling a
    # console build.
    try:
        if _prefer_tray():
            _first_run_shortcut_prompt()
            from . import tray
            return tray.main()
        # Console mode — run the agent's serve loop
        from . import agent, config
        agent.serve(config.bootstrap(), block=True)
        return 0
    except Exception:
        import datetime as _dt
        log_path = os.path.join(os.path.expanduser("~"),
                                  ".spellcaster",
                                  "antenna-crash.log")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n=== {_dt.datetime.now().isoformat()} "
                        f"antenna __main__ crashed ===\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        # Surface the traceback to the default hook (logs to stderr
        # when a console is attached).
        raise


if __name__ == "__main__":
    sys.exit(main())
