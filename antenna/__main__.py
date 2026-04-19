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


def _prefer_tray() -> bool:
    if os.name != "nt":
        return False
    if os.environ.get("SPELLCASTER_ANTENNA_NO_TRAY", "").strip() in ("1", "true", "yes"):
        return False
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
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
    except Exception:  # noqa: BLE001
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
    if _prefer_tray():
        _first_run_shortcut_prompt()
        from . import tray
        return tray.main()
    # Console mode — run the agent's serve loop
    from . import agent, config
    agent.serve(config.bootstrap(), block=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
