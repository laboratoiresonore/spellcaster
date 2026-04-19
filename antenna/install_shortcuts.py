"""Windows shortcut installer for the Spellcaster Antenna.

Offers to place three .lnk files so the antenna feels like a proper
native app rather than a one-off bat file:

  1. Desktop                                  — double-click to launch
  2. Start Menu → Programs                    — keyboard-reachable via
                                                 the Windows search box
  3. Start Menu → Programs → Startup          — launch automatically at
                                                 every login (optional)

All .lnk creation shells out to PowerShell's WScript.Shell COM object
so we stay stdlib-only — no pywin32 dependency. Each shortcut points
at `pythonw.exe -m antenna` (windowless launcher) with the repo dir
as the working directory, so the tray icon spawns without a console.

Public API
──────────
    install_shortcuts(desktop=True, start_menu=True, startup=False)
        → dict with {"desktop": path|None, "start_menu": path|None,
                     "startup": path|None, "errors": [...] }
    remove_shortcuts()
        → dict with the same shape, paths that were removed

    prompt_and_install()
        → interactive console prompt (y/N per option) suitable for
          the antenna.bat first-run flow.

Graceful behaviour on non-Windows: every function returns an empty
result with a warning — macOS / Linux users don't get .lnk files but
the antenna still runs fine from the shell.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


APP_NAME = "Spellcaster Antenna"
_LNK_BASENAME = "Spellcaster Antenna.lnk"


def _is_windows() -> bool:
    return os.name == "nt"


def _antenna_repo_root() -> Path:
    """Return the directory that contains the `antenna` package so we
    can launch `python -m antenna` from there without needing the
    module to be on PYTHONPATH at login time."""
    # antenna/__file__ → …/antenna/install_shortcuts.py
    return Path(__file__).resolve().parent.parent


def _python_launcher() -> str:
    """Return the pythonw.exe that should own the tray. Prefer the
    windowless launcher so no console flashes on login; fall back to
    the current interpreter if pythonw isn't bundled."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    if pyw.is_file():
        return str(pyw)
    return sys.executable


def _shortcut_target() -> dict:
    """Everything the WScript.Shell CreateShortcut call needs. Split
    out so tests + callers can introspect without invoking PowerShell."""
    return {
        "target":       _python_launcher(),
        "arguments":    '-m antenna',
        "working_dir":  str(_antenna_repo_root()),
        "description":  "Spellcaster Antenna — bridges this machine to the "
                         "Wizard Guild.",
        "icon":         _python_launcher() + ",0",
    }


def _create_lnk(path: Path) -> Optional[str]:
    """Create one .lnk via PowerShell. Returns None on success, error
    string on failure."""
    if not _is_windows():
        return "not-windows"
    spec = _shortcut_target()
    # Escape ALL single quotes in any path by doubling them — PowerShell
    # single-quoted literals need the double-quote-escape treatment.
    def q(s: str) -> str:
        return s.replace("'", "''")
    ps = (
        "$s = New-Object -ComObject WScript.Shell;"
        f"$l = $s.CreateShortcut('{q(str(path))}');"
        f"$l.TargetPath = '{q(spec['target'])}';"
        f"$l.Arguments = '{q(spec['arguments'])}';"
        f"$l.WorkingDirectory = '{q(spec['working_dir'])}';"
        f"$l.Description = '{q(spec['description'])}';"
        f"$l.IconLocation = '{q(spec['icon'])}';"
        "$l.Save();"
    )
    try:
        # CREATE_NO_WINDOW so PowerShell doesn't flash a console.
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
              "-ExecutionPolicy", "Bypass", "-Command", ps],
            check=True, capture_output=True, timeout=15,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return None
    except subprocess.CalledProcessError as e:
        return (e.stderr.decode("utf-8", "replace")
                 or e.stdout.decode("utf-8", "replace")
                 or f"exit {e.returncode}")[:200]
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:200]


def _desktop_path() -> Path:
    # USERPROFILE\Desktop is the canonical per-user Desktop; falls back
    # to HOME/Desktop on non-Windows for symmetry.
    if _is_windows():
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    return Path.home() / "Desktop"


def _start_menu_programs_path() -> Path:
    if _is_windows():
        return (Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
                / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return Path.home() / ".local" / "share" / "applications"


def _startup_folder_path() -> Path:
    if _is_windows():
        return _start_menu_programs_path() / "Startup"
    return Path.home() / ".config" / "autostart"


def install_shortcuts(desktop: bool = True,
                       start_menu: bool = True,
                       startup: bool = False) -> dict:
    """Create the requested shortcuts. Returns a summary dict describing
    what was written + any errors. Caller's responsibility to present
    the result (tray toast, console log, etc.)."""
    if not _is_windows():
        return {
            "desktop": None, "start_menu": None, "startup": None,
            "errors": ["shortcuts are only supported on Windows; "
                        "run `python -m antenna` directly on this OS."],
        }
    result = {"desktop": None, "start_menu": None, "startup": None,
              "errors": []}
    targets: list[tuple[str, Path]] = []
    if desktop:
        targets.append(("desktop", _desktop_path() / _LNK_BASENAME))
    if start_menu:
        targets.append(("start_menu",
                         _start_menu_programs_path() / _LNK_BASENAME))
    if startup:
        targets.append(("startup",
                         _startup_folder_path() / _LNK_BASENAME))
    for tag, path in targets:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            result["errors"].append(f"{tag}: mkdir failed: {e}")
            continue
        err = _create_lnk(path)
        if err:
            result["errors"].append(f"{tag}: {err}")
        else:
            result[tag] = str(path)
    return result


def remove_shortcuts() -> dict:
    """Delete any shortcuts we previously installed. Silent if they
    don't exist — idempotent."""
    removed = {"desktop": None, "start_menu": None, "startup": None,
                "errors": []}
    for tag, root in (("desktop",    _desktop_path()),
                       ("start_menu", _start_menu_programs_path()),
                       ("startup",    _startup_folder_path())):
        path = root / _LNK_BASENAME
        if path.is_file():
            try:
                path.unlink()
                removed[tag] = str(path)
            except Exception as e:  # noqa: BLE001
                removed["errors"].append(f"{tag}: {e}")
    return removed


def current_status() -> dict:
    """Return which shortcuts currently exist — used by the tray menu
    to render "✓ installed" vs "(install)" labels."""
    return {
        "desktop":    (_desktop_path() / _LNK_BASENAME).is_file(),
        "start_menu": (_start_menu_programs_path() / _LNK_BASENAME).is_file(),
        "startup":    (_startup_folder_path() / _LNK_BASENAME).is_file(),
    }


def prompt_and_install(auto_yes: bool = False) -> dict:
    """Interactive flow for the antenna.bat first-run path. Asks the
    user three y/N questions and writes every "yes" answer."""
    if not _is_windows():
        print("[antenna] shortcuts: non-Windows OS, skipping.")
        return install_shortcuts(False, False, False)

    def _ask(prompt: str, default: bool = True) -> bool:
        if auto_yes:
            return True
        suffix = " [Y/n]: " if default else " [y/N]: "
        try:
            raw = input(prompt + suffix).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not raw:
            return default
        return raw.startswith("y")

    print()
    print("  Spellcaster Antenna — Windows shortcut setup")
    print("  ---------------------------------------------")
    desktop = _ask("  Create a desktop icon?", True)
    start_menu = _ask("  Add to Start Menu → Programs?", True)
    startup = _ask("  Launch automatically at every Windows login?", False)

    result = install_shortcuts(desktop=desktop,
                                start_menu=start_menu,
                                startup=startup)
    for tag in ("desktop", "start_menu", "startup"):
        if result.get(tag):
            print(f"  ✓ {tag:10s} {result[tag]}")
    for err in result.get("errors") or []:
        print(f"  ✗ {err}")
    print()
    return result


__all__ = [
    "install_shortcuts",
    "remove_shortcuts",
    "current_status",
    "prompt_and_install",
    "APP_NAME",
]


if __name__ == "__main__":
    # `python -m antenna.install_shortcuts` runs the interactive flow,
    # useful from the antenna.bat's first-run path.
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--yes", action="store_true",
                    help="accept all defaults (non-interactive).")
    p.add_argument("--remove", action="store_true",
                    help="remove installed shortcuts instead of creating.")
    args = p.parse_args()
    if args.remove:
        print(remove_shortcuts())
    else:
        prompt_and_install(auto_yes=args.yes)
