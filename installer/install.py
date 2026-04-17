#!/usr/bin/env python3
"""
Spellcaster Installer
=====================
Interactive installer for Spellcaster — AI superpowers for GIMP 3 and Darktable.
Downloads and installs models, custom nodes, and patches the host applications.

Usage:
    python install.py                          # Interactive wizard (GUI)
    python install.py --cli                    # Force terminal mode
    python install.py --dry-run                # Preview without changes
    python install.py --yes                    # Auto-accept all defaults
    python install.py --server-url http://<SERVER-IP>:8188  # Remote ComfyUI
    python install.py --features img2img,inpaint,face_swap_reactor
    python install.py --comfyui ~/ComfyUI --gimp ~/.config/GIMP/3.2/plug-ins
    python install.py --skip-models            # Plugins + nodes only
    python install.py --skip-nodes             # Plugins + models only
    python install.py --help

https://github.com/laboratoiresonore/spellcaster
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ─── Constants ────────────────────────────────────────────────────────────────

# When bundled with PyInstaller, _MEIPASS points to the temp extraction dir;
# otherwise use the script's own directory as the base for finding assets.
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = Path(sys._MEIPASS)
else:
    SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPT_DIR / "manifest.json"
VERSION = "2.2"
DEFAULT_SERVER_URL = "http://127.0.0.1:8188"
DEFAULT_LLM_URL = "http://127.0.0.1:5001"
_BOX_LINE = "═" * 50

# ANSI colors — enabled on real terminals, but only on Windows when running
# inside Windows Terminal (WT_SESSION), which supports VT100 escape sequences.
if sys.stdout and sys.stdout.isatty() and (os.name != "nt" or os.environ.get("WT_SESSION")):
    C_BOLD    = "\033[1m"
    C_GREEN   = "\033[92m"
    C_YELLOW  = "\033[93m"
    C_RED     = "\033[91m"
    C_CYAN    = "\033[96m"
    C_DIM     = "\033[2m"
    C_RESET   = "\033[0m"
else:
    C_BOLD = C_GREEN = C_YELLOW = C_RED = C_CYAN = C_DIM = C_RESET = ""


# ─── Utility functions ────────────────────────────────────────────────────────

def banner():
    """Print the decorative installer header with version number."""
    print(f"""
{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════════╗
║       ✦  SPELLCASTER INSTALLER  v{VERSION}  ✦       ║
║                                                  ║
║  AI superpowers for GIMP 3 & Darktable           ║
║  Every preset expertly tuned for instant results ║
╚══════════════════════════════════════════════════╝{C_RESET}
""")


def fmt_size(mb: float) -> str:
    """Format a size in megabytes to a human-readable string (KB / MB / GB)."""
    if mb < 1:
        return f"{mb * 1024:.0f} KB"
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def ask_yn(prompt: str, default: bool = True, auto_yes: bool = False) -> bool:
    """Prompt user for yes/no input. Returns *default* when --yes is active."""
    if auto_yes:
        print(f"{C_BOLD}{prompt} [Y/n]:{C_RESET} Y (auto)")
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input(f"{C_BOLD}{prompt} {suffix}:{C_RESET} ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def ask_path(prompt: str, must_exist: bool = True, default: str = "",
             auto_yes: bool = False) -> Path:
    """Prompt for a filesystem path, optionally validating that it exists."""
    if auto_yes and default:
        print(f"{C_BOLD}{prompt} [{default}]:{C_RESET} {default} (auto)")
        return Path(default).expanduser().resolve()
    while True:
        hint = f" [{default}]" if default else ""
        raw = input(f"{C_BOLD}{prompt}{hint}:{C_RESET} ").strip()
        if not raw and default:
            raw = default
        if not raw:
            print(f"  {C_RED}Path cannot be empty.{C_RESET}")
            continue
        p = Path(raw).expanduser().resolve()
        if must_exist and not p.is_dir():
            print(f"  {C_RED}Directory not found: {p}{C_RESET}")
            continue
        return p


def ask_choice(prompt: str, options: list[str], default: int = 0,
               auto_yes: bool = False) -> int:
    """Display a numbered menu and return the 0-based index of the user's choice."""
    print(f"\n{C_BOLD}{prompt}{C_RESET}")
    for i, opt in enumerate(options):
        marker = f" {C_DIM}(default){C_RESET}" if i == default else ""
        print(f"  {C_CYAN}{i + 1}{C_RESET}) {opt}{marker}")
    if auto_yes:
        print(f"{C_BOLD}Choice [1-{len(options)}]:{C_RESET} {default + 1} (auto)")
        return default
    while True:
        raw = input(f"{C_BOLD}Choice [1-{len(options)}]:{C_RESET} ").strip()
        if not raw:
            return default
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass
        print(f"  Please enter a number 1-{len(options)}.")


def ask_text(prompt: str, default: str = "", auto_yes: bool = False) -> str:
    """Prompt for free-form text input with an optional default value."""
    if auto_yes and default:
        print(f"{C_BOLD}{prompt} [{default}]:{C_RESET} {default} (auto)")
        return default
    hint = f" [{default}]" if default else ""
    raw = input(f"{C_BOLD}{prompt}{hint}:{C_RESET} ").strip()
    return raw if raw else default


# ─── Application path detection ───────────────────────────────────────────────

def _is_comfyui_dir(p: Path) -> bool:
    """Validate that a directory contains a ComfyUI installation.

    Checks for markers found in all distribution flavours:
      - main.py                    (git clone, portable, comfy-cli, StabilityMatrix)
      - comfy/cli_args.py          (post-refactor source tree)
      - custom_nodes/              (every install that has run at least once)
      - ComfyUI/main.py            (parent wrapper dirs — portable, Desktop data)
      - extra_models_config.yaml   (ComfyUI Desktop data directory)
    """
    try:
        return ((p / "main.py").is_file()
                or (p / "comfy" / "cli_args.py").is_file()
                or (p / "custom_nodes").is_dir()
                or (p / "ComfyUI" / "main.py").is_file()
                or (p / "extra_models_config.yaml").is_file())
    except (PermissionError, OSError):
        return False


def _win_all_drives() -> list[str]:
    """Return all accessible drive letters on Windows (A:-Z:).

    Filters out drives that raise PermissionError (e.g. mapped network
    drives that require elevated privileges).
    """
    drives = []
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                letter = f"{chr(65 + i)}:"
                # Skip drives we can't access (network/restricted)
                try:
                    Path(f"{letter}/").exists()
                    drives.append(letter)
                except (PermissionError, OSError):
                    pass
    except Exception:
        drives = ["C:", "D:", "E:", "F:", "G:", "H:"]
    return drives


def _win_registry_gimp() -> str:
    """Query Windows Registry for GIMP installation path."""
    try:
        import winreg
        for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for subkey in [r"SOFTWARE\GIMP\3", r"SOFTWARE\GIMP\3.0",
                           r"SOFTWARE\GIMP\3.2", r"SOFTWARE\GIMP"]:
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        val, _ = winreg.QueryValueEx(key, "InstallPath")
                        if val and Path(val).is_dir():
                            return val
                except (OSError, FileNotFoundError):
                    continue
    except ImportError:
        pass
    return ""


def _gimp_config_from_executable() -> str:
    """Infer GIMP config directory from the gimp executable location."""
    import shutil
    for name in ["gimp-3.2", "gimp-3.0", "gimp3", "gimp-2.99", "gimp"]:
        exe = shutil.which(name)
        if exe:
            # GIMP config is in %APPDATA%/GIMP or ~/.config/GIMP
            # The exe tells us GIMP exists — let the main scan find config
            return exe
    return ""


def _scan_gimp_versions(root: Path) -> list[Path]:
    """Scan a GIMP config root for version directories (3.x, 2.99)."""
    results = []
    if not root.is_dir():
        return results
    try:
        for d in sorted(root.iterdir(), reverse=True):
            if d.is_dir() and (d.name.startswith("3.") or d.name.startswith("2.99")):
                plugins = d / "plug-ins"
                results.append(plugins)
    except (PermissionError, OSError):
        pass
    return results


def find_default_comfyui() -> str:
    """Auto-detect ComfyUI installation using multiple strategies.

    Strategy order:
      1. Environment variable COMFYUI_ROOT / COMFYUI_PATH
      2. shutil.which() for 'comfy' executable on PATH
      3. Common filesystem locations (all drives on Windows)
      4. Portable distribution glob patterns
      5. Running process detection (if psutil available)

    Validates candidates by checking for main.py, comfy/cli_args.py, or custom_nodes/.
    """
    import shutil

    home = Path.home()
    candidates: list[Path] = []

    # Strategy 1: Environment variables
    for env_key in ["COMFYUI_ROOT", "COMFYUI_PATH", "COMFYUI_DIR"]:
        val = os.environ.get(env_key, "")
        if val:
            candidates.append(Path(val))

    # Strategy 2: shutil.which() — find 'comfy' or 'python' running ComfyUI
    for name in ["comfy", "comfyui"]:
        exe = shutil.which(name)
        if exe:
            # The executable might be in bin/ or scripts/ — go up to find the root
            p = Path(exe).resolve().parent
            for _ in range(4):
                if _is_comfyui_dir(p):
                    candidates.append(p)
                    break
                p = p.parent

    # comfy-cli default workspace (all platforms)
    candidates.append(home / "comfy" / "ComfyUI")
    candidates.append(home / "comfy")

    if platform.system() == "Windows":
        # Strategy 3: Filesystem scan — ALL drives
        drives = _win_all_drives()
        for drive in drives:
            root = Path(f"{drive}/")
            candidates.append(root / "ComfyUI")
            candidates.append(root / "ComfyUI_windows_portable" / "ComfyUI")
            # StabilityMatrix common location
            candidates.append(root / "StabilityMatrix" / "Data" / "Packages" / "ComfyUI")
        # ComfyUI Desktop (Electron app) — engine in LOCALAPPDATA, data in APPDATA
        localappdata = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        if localappdata:
            candidates.append(Path(localappdata) / "ComfyUI" / "ComfyUI")
            candidates.append(Path(localappdata) / "ComfyUI")
            candidates.append(Path(localappdata) / "Programs" / "ComfyUI_Desktop" / "ComfyUI")
            candidates.append(Path(localappdata) / "Programs" / "comfyui-electron" / "ComfyUI")
        if appdata:
            candidates.append(Path(appdata) / "ComfyUI")
        candidates += [
            home / "ComfyUI",
            home / "Desktop" / "ComfyUI",
            home / "Documents" / "ComfyUI",
            home / "Downloads" / "ComfyUI",
            home / "Documents" / "AI" / "ComfyUI",
        ]
        # Pinokio
        candidates.append(home / "pinokio" / "api" / "comfy.git" / "app")
        # Strategy 4: Glob for portable/StabilityMatrix/Pinokio distributions
        for drive in drives:
            drive_root = Path(f"{drive}/")
            try:
                if not drive_root.exists():
                    continue
            except (PermissionError, OSError):
                continue
            try:
                for d in drive_root.glob("ComfyUI*portable*/ComfyUI"):
                    candidates.append(d)
                for d in drive_root.glob("ComfyUI*/ComfyUI"):
                    candidates.append(d)
                # StabilityMatrix in non-standard locations
                for d in drive_root.glob("StabilityMatrix*/Data/Packages/ComfyUI"):
                    candidates.append(d)
            except (PermissionError, OSError):
                pass
        for user_dir in ["Desktop", "Downloads", "Documents"]:
            try:
                for d in (home / user_dir).glob("ComfyUI*portable*/ComfyUI"):
                    candidates.append(d)
                for d in (home / user_dir).glob("ComfyUI*/ComfyUI"):
                    candidates.append(d)
            except (PermissionError, OSError):
                pass
    elif platform.system() == "Darwin":
        candidates += [
            home / "ComfyUI",
            Path("/Applications/ComfyUI"),
            home / "Documents" / "ComfyUI",
            home / "Desktop" / "ComfyUI",
            home / "Downloads" / "ComfyUI",
            # ComfyUI Desktop (Electron app)
            home / "Library" / "Application Support" / "ComfyUI" / "ComfyUI",
            home / "Library" / "Application Support" / "ComfyUI",
            # Pinokio
            home / "pinokio" / "api" / "comfy.git" / "app",
        ]
    else:
        candidates += [
            home / "ComfyUI",
            Path("/opt/ComfyUI"),
            home / "Documents" / "ComfyUI",
            home / "Desktop" / "ComfyUI",
            Path("/usr/local/share/ComfyUI"),
            # ComfyUI Desktop (Linux)
            home / ".config" / "ComfyUI",
            # Pinokio
            home / "pinokio" / "api" / "comfy.git" / "app",
        ]

    # Strategy 5: Running-process detection (psutil, then /proc fallback)
    # If ComfyUI is currently running we can read its working directory
    _proc_found = False
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                joined = " ".join(cmdline).lower()
                if "main.py" in joined and ("comfy" in joined or "custom_nodes" in joined):
                    cwd = proc.info.get("cwd", "")
                    if cwd:
                        candidates.append(Path(cwd))
                    for arg in cmdline:
                        if "main.py" in arg:
                            candidates.append(Path(arg).resolve().parent)
                    _proc_found = True
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
    except ImportError:
        pass

    # /proc fallback for Linux when psutil is not installed
    if not _proc_found and platform.system() == "Linux":
        proc_dir = Path("/proc")
        if proc_dir.is_dir():
            try:
                for pid_dir in proc_dir.iterdir():
                    if not pid_dir.name.isdigit():
                        continue
                    cmdline_file = pid_dir / "cmdline"
                    try:
                        raw = cmdline_file.read_bytes()
                        if b"main.py" in raw and b"comfy" in raw.lower():
                            # Read cwd symlink
                            cwd_link = pid_dir / "cwd"
                            if cwd_link.is_symlink():
                                candidates.append(Path(os.readlink(cwd_link)))
                            # Parse script path from cmdline
                            parts = raw.split(b"\x00")
                            for part in parts:
                                if b"main.py" in part:
                                    try:
                                        candidates.append(Path(part.decode()).resolve().parent)
                                    except (UnicodeDecodeError, OSError):
                                        pass
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError):
                pass

    # Deduplicate and validate
    seen: set[str] = set()
    for c in candidates:
        try:
            cs = str(c.resolve()) if c.exists() else str(c)
        except (PermissionError, OSError, ValueError):
            cs = str(c)
        if cs in seen:
            continue
        seen.add(cs)
        try:
            if _is_comfyui_dir(c):
                return str(c)
        except (PermissionError, OSError):
            continue
    return ""


def find_default_gimp() -> str:
    """Auto-detect GIMP 3 user plug-ins directory using multiple strategies.

    Strategy order:
      1. Environment variable GIMP_PLUGIN_PATH / GIMP_DIR
      2. Windows Registry (HKLM/HKCU SOFTWARE\\GIMP)
      3. shutil.which() for gimp executable
      4. Config directory scanning (Roaming, Local, XDG, Flatpak, Snap)
      5. Hardcoded fallback paths for all known versions

    Returns the plug-ins directory path, or empty string.
    """
    import shutil

    home = Path.home()
    candidates: list[Path] = []

    # Strategy 1: Environment variables (GIMP3_DIRECTORY is GIMP's own override)
    for env_key in ["GIMP_PLUGIN_PATH", "GIMP_DIR", "GIMP3_DIR",
                     "GIMP3_DIRECTORY", "XDG_CONFIG_HOME"]:
        val = os.environ.get(env_key, "")
        if not val:
            continue
        p = Path(val)
        if env_key == "XDG_CONFIG_HOME":
            # XDG override: config root may contain GIMP/3.x/
            candidates.extend(_scan_gimp_versions(p / "GIMP"))
        elif p.is_dir() or p.parent.is_dir():
            # If it's already a plug-ins dir, use directly
            if p.name == "plug-ins":
                candidates.append(p)
            else:
                candidates.append(p / "plug-ins")
                candidates.append(p)

    # Strategy 2: Windows Registry — use install path to locate config
    _gimp_confirmed = False
    if platform.system() == "Windows":
        reg_path = _win_registry_gimp()
        if reg_path:
            _gimp_confirmed = True
        # Also check Uninstall keys (covers MSI installer, MSIX, winget)
        if not _gimp_confirmed:
            try:
                import winreg
                for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                    for uninstall_root in [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                            r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]:
                        try:
                            with winreg.OpenKey(hive, uninstall_root) as root_key:
                                i = 0
                                while True:
                                    try:
                                        sub_name = winreg.EnumKey(root_key, i)
                                        if "gimp" in sub_name.lower():
                                            _gimp_confirmed = True
                                            break
                                        i += 1
                                    except OSError:
                                        break
                        except (OSError, FileNotFoundError):
                            continue
                        if _gimp_confirmed:
                            break
                    if _gimp_confirmed:
                        break
            except ImportError:
                pass
        # Also check Program Files for GIMP install dir
        if not _gimp_confirmed:
            for pf_key in ["ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"]:
                pf = os.environ.get(pf_key, "")
                if pf:
                    for gdir in ["GIMP 3", "GIMP3", "GIMP"]:
                        if (Path(pf) / gdir / "bin" / "gimp-3.0.exe").is_file() \
                           or (Path(pf) / gdir / "bin" / "gimp-3.2.exe").is_file() \
                           or (Path(pf) / gdir / "bin" / "gimp.exe").is_file():
                            _gimp_confirmed = True
                            break
                if _gimp_confirmed:
                    break
        if _gimp_confirmed:
            # We know GIMP is installed — aggressively scan all config locations
            for appdata_key in ["APPDATA", "LOCALAPPDATA"]:
                appdata = os.environ.get(appdata_key, "")
                if appdata:
                    candidates.extend(_scan_gimp_versions(Path(appdata) / "GIMP"))

    # Strategy 3: shutil.which() — confirms GIMP is installed, use to seed search
    for name in ["gimp-3.2", "gimp-3.0", "gimp3", "gimp-2.99", "gimp"]:
        exe = shutil.which(name)
        if exe:
            # GIMP exists on PATH — its config will be in the standard locations
            break

    # Strategy 4: Config directory scanning
    if platform.system() == "Windows":
        # Check BOTH Roaming and Local AppData
        for appdata_key in ["APPDATA", "LOCALAPPDATA"]:
            appdata = os.environ.get(appdata_key, "")
            if appdata:
                gimp_root = Path(appdata) / "GIMP"
                candidates.extend(_scan_gimp_versions(gimp_root))
        # Also check the home-relative paths (for edge cases)
        candidates.extend(_scan_gimp_versions(home / "AppData" / "Roaming" / "GIMP"))
        candidates.extend(_scan_gimp_versions(home / "AppData" / "Local" / "GIMP"))
        # Hardcoded fallbacks (include 3.4 for future-proofing)
        for ver in ["3.4", "3.2", "3.0", "2.99"]:
            candidates.append(home / "AppData" / "Roaming" / "GIMP" / ver / "plug-ins")
            candidates.append(home / "AppData" / "Local" / "GIMP" / ver / "plug-ins")
        # PortableApps (USB / portable GIMP on any drive)
        drives = _win_all_drives()
        for drive in drives:
            try:
                for d in Path(f"{drive}/").glob("PortableApps/GIMPPortable*/Data"):
                    if d.is_dir():
                        candidates.extend(_scan_gimp_versions(d / "GimpAppData"))
            except (PermissionError, OSError):
                pass

    elif platform.system() == "Darwin":
        app_support = home / "Library" / "Application Support" / "GIMP"
        candidates.extend(_scan_gimp_versions(app_support))
        candidates.extend(_scan_gimp_versions(home / ".config" / "GIMP"))
        # Some macOS builds use ~/Library/GIMP directly
        candidates.extend(_scan_gimp_versions(home / "Library" / "GIMP"))
        for ver in ["3.4", "3.2", "3.0", "2.99"]:
            candidates.append(app_support / ver / "plug-ins")
            candidates.append(home / ".config" / "GIMP" / ver / "plug-ins")
            candidates.append(home / "Library" / "GIMP" / ver / "plug-ins")

    else:  # Linux
        # XDG_CONFIG_HOME override (already handled in env vars, but belt-and-suspenders)
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
        if xdg_config:
            candidates.extend(_scan_gimp_versions(Path(xdg_config) / "GIMP"))
        candidates.extend(_scan_gimp_versions(home / ".config" / "GIMP"))
        # Flatpak
        flatpak = home / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP"
        candidates.extend(_scan_gimp_versions(flatpak))
        # Snap (multiple revisions)
        snap_base = home / "snap" / "gimp"
        if snap_base.is_dir():
            try:
                for rev in sorted(snap_base.iterdir(), reverse=True):
                    candidates.extend(_scan_gimp_versions(rev / ".config" / "GIMP"))
            except (PermissionError, OSError):
                pass
        # Hardcoded fallbacks
        for ver in ["3.4", "3.2", "3.0", "2.99"]:
            candidates.append(home / ".config" / "GIMP" / ver / "plug-ins")
            candidates.append(flatpak / ver / "plug-ins")

    # Deduplicate and validate
    # IMPORTANT: On a fresh GIMP install the plug-ins/ subdir may not exist
    # yet — GIMP only creates it when plugins are added.  If the parent
    # version directory exists (e.g. .../GIMP/3.2/) we accept the path and
    # the installer will mkdir it during deployment.
    seen: set[str] = set()
    for c in candidates:
        cs = str(c)
        if cs in seen:
            continue
        seen.add(cs)
        if c.is_dir():
            return cs
        # Accept if the version dir exists even though plug-ins/ doesn't yet
        if c.name == "plug-ins" and c.parent.is_dir():
            return cs
    return ""


def find_default_darktable() -> str:
    """Auto-detect Darktable's lua/contrib directory using multiple strategies.

    Strategy order:
      1. Environment variable DARKTABLE_DIR
      2. shutil.which() for darktable executable
      3. Config directory scanning (Windows, macOS, Linux, Flatpak)
      4. System package paths
    """
    import shutil

    home = Path.home()
    candidates: list[Path] = []

    # Strategy 1: Environment variables
    for env_key in ["DARKTABLE_DIR", "DARKTABLE_CONFIG"]:
        val = os.environ.get(env_key, "")
        if val:
            p = Path(val)
            candidates.append(p / "lua" / "contrib")
            candidates.append(p)

    # Strategy 2: shutil.which() — confirms darktable exists
    for name in ["darktable", "darktable-cli"]:
        if shutil.which(name):
            break

    # Strategy 2b: Windows Registry — check Uninstall keys for darktable
    # If found, we know darktable is installed → seed the standard config paths
    if platform.system() == "Windows":
        _dt_confirmed = False
        try:
            import winreg
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                for uninstall_root in [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                        r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]:
                    try:
                        with winreg.OpenKey(hive, uninstall_root) as root_key:
                            i = 0
                            while True:
                                try:
                                    sub_name = winreg.EnumKey(root_key, i)
                                    if "darktable" in sub_name.lower():
                                        _dt_confirmed = True
                                    i += 1
                                except OSError:
                                    break
                    except (OSError, FileNotFoundError):
                        continue
        except ImportError:
            pass
        if _dt_confirmed:
            # Registry confirms install — aggressively add all standard config paths
            for appdata_key in ["LOCALAPPDATA", "APPDATA"]:
                appdata = os.environ.get(appdata_key, "")
                if appdata:
                    candidates.append(Path(appdata) / "darktable" / "lua" / "contrib")

    # Strategy 3: Config directory scanning
    if platform.system() == "Windows":
        for appdata_key in ["LOCALAPPDATA", "APPDATA"]:
            appdata = os.environ.get(appdata_key, "")
            if appdata:
                candidates.append(Path(appdata) / "darktable" / "lua" / "contrib")
        candidates.append(home / "AppData" / "Local" / "darktable" / "lua" / "contrib")
        candidates.append(home / "AppData" / "Roaming" / "darktable" / "lua" / "contrib")
        candidates.append(home / ".config" / "darktable" / "lua" / "contrib")
    elif platform.system() == "Darwin":
        candidates += [
            home / "Library" / "Application Support" / "darktable" / "lua" / "contrib",
            home / ".config" / "darktable" / "lua" / "contrib",
        ]
    else:  # Linux
        # XDG override
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
        if xdg_config:
            candidates.append(Path(xdg_config) / "darktable" / "lua" / "contrib")
        candidates += [
            home / ".config" / "darktable" / "lua" / "contrib",
            # Flatpak (note: org.darktable.Darktable with capital D)
            home / ".var" / "app" / "org.darktable.darktable" / "config" / "darktable" / "lua" / "contrib",
            home / ".var" / "app" / "org.darktable.Darktable" / "config" / "darktable" / "lua" / "contrib",
            # System-wide
            Path("/usr/share/darktable/lua/contrib"),
            Path("/usr/local/share/darktable/lua/contrib"),
        ]

    # Strategy 4: Config-root marker detection
    # Even without lua/contrib, darktable creates darktablerc and library.db
    # on first run.  If we find these, we know the config root → derive lua/contrib.
    _dt_config_roots: list[Path] = []
    if platform.system() == "Windows":
        for appdata_key in ["LOCALAPPDATA", "APPDATA"]:
            appdata = os.environ.get(appdata_key, "")
            if appdata:
                _dt_config_roots.append(Path(appdata) / "darktable")
        _dt_config_roots.append(home / ".config" / "darktable")
    elif platform.system() == "Darwin":
        _dt_config_roots += [
            home / "Library" / "Application Support" / "darktable",
            home / ".config" / "darktable",
        ]
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
        if xdg_config:
            _dt_config_roots.append(Path(xdg_config) / "darktable")
        _dt_config_roots.append(home / ".config" / "darktable")
        _dt_config_roots.append(
            home / ".var" / "app" / "org.darktable.Darktable" / "config" / "darktable")
        _dt_config_roots.append(
            home / ".var" / "app" / "org.darktable.darktable" / "config" / "darktable")

    for dt_root in _dt_config_roots:
        if dt_root.is_dir() and (
            (dt_root / "darktablerc").is_file()
            or (dt_root / "library.db").is_file()
            or (dt_root / "data.db").is_file()
        ):
            lua_contrib = dt_root / "lua" / "contrib"
            cs = str(lua_contrib)
            if cs not in {str(c) for c in candidates}:
                candidates.append(lua_contrib)

    # Deduplicate and validate
    # A fresh Darktable install may not have lua/ or lua/contrib/.
    # If we can see the darktable config root we accept the path — the
    # installer will mkdir -p the full chain during deployment.
    seen: set[str] = set()
    for c in candidates:
        cs = str(c)
        if cs in seen:
            continue
        seen.add(cs)
        if c.is_dir():
            return str(c)
        # Accept if the darktable config root exists (lua/contrib will be created)
        # Walk up: contrib → lua → darktable-config-root
        dt_root = c
        for _ in range(3):
            dt_root = dt_root.parent
            if dt_root.is_dir() and dt_root.name.lower() in ("darktable",):
                return str(c)
    return ""


# ─── Download & install helpers ───────────────────────────────────────────────

def detect_gpu_vram() -> tuple[str, int]:
    """Detect primary GPU name and VRAM in MB. Returns ('Unknown', 0) on failure."""
    # ── Strategy 1: NVIDIA via nvidia-smi (most reliable for NVIDIA GPUs) ──
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            # Output format: "NVIDIA GeForce RTX 4090, 24564" (name, VRAM in MB)
            parts = r.stdout.strip().splitlines()[0].split(",")
            return parts[0].strip(), int(parts[1].strip())
    except Exception:
        pass
    # ── Strategy 2: AMD via rocm-smi (Linux ROCm driver) ──
    try:
        r = subprocess.run(["rocm-smi", "--showmeminfo", "vram"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if "Total Memory" in line or "total memory" in line:
                    val = line.split(":")[-1].strip().split()[0]
                    mb = int(val) // 1024  # rocm-smi reports in KB
                    return "AMD GPU", mb
    except Exception:
        pass
    # ── Strategy 3: Windows WMIC fallback (works for any GPU on Windows) ──
    if platform.system() == "Windows":
        try:
            r = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "AdapterRAM,Name", "/format:csv"],
                capture_output=True, text=True, timeout=5
            )
            best = 0
            best_name = ""
            for line in r.stdout.strip().splitlines():
                if not line or "Node" in line:  # skip CSV header row
                    continue
                parts = line.split(",")
                if len(parts) >= 3:
                    try:
                        ram = int(parts[1]) // (1024 * 1024)  # AdapterRAM is in bytes
                        if ram > best:
                            best, best_name = ram, parts[2].strip()
                    except ValueError:
                        pass
            # Ignore tiny values (<1 GB) — likely integrated GPUs or reporting errors
            if best > 1024:
                return best_name, best
        except Exception:
            pass
    return "Unknown GPU", 0


def vram_tier(vram_mb: int) -> str:
    """Classify VRAM into model-selection tier.

    Thresholds are tuned to match typical Stable Diffusion / Flux model
    precision requirements, where lower VRAM forces quantized model variants.
    """
    if vram_mb == 0:    return "unknown"
    if vram_mb < 8192:  return "low"      # <8 GB → Q4/Q5 GGUF only
    if vram_mb < 12288: return "medium"   # 8–12 GB → Q8/fp8
    if vram_mb < 20480: return "high"     # 12–20 GB → fp8 or bf16 small
    return "ultra"                         # 20+ GB → full bf16


def feature_compatible(feat: dict, vram_mb: int) -> tuple[str, str]:
    """Check if a feature is compatible with the user's VRAM.

    Returns (status, reason):
      ("ok", "")           -- fully compatible
      ("warn", "...")      -- works but may be slow/limited
      ("no", "...")        -- won't work at all
      ("nogpu", "...")     -- no GPU detected
    """
    if vram_mb == 0:
        return ("nogpu", "No GPU detected")

    vram_gb = vram_mb / 1024
    min_gb = feat.get("vram_min_gb", 0)
    rec_gb = feat.get("vram_recommended_gb", min_gb)

    if min_gb == 0:
        return ("ok", "")
    if vram_gb < min_gb:
        return ("no", f"Requires {min_gb} GB VRAM (you have {vram_gb:.0f} GB)")
    if vram_gb < rec_gb:
        return ("warn", f"May be slow -- {rec_gb} GB+ recommended (you have {vram_gb:.0f} GB)")
    return ("ok", "")


def feature_already_installed(feat: dict, manifest: dict,
                              server_info: dict) -> tuple[bool, str]:
    """Check if a feature's components are already present on the ComfyUI server.

    Cross-references the feature's custom_nodes (via their 'provides' node
    class names) and required models against what server probing detected.

    Returns:
        (True, reason)  — all required components are installed
        (False, "")     — something is missing
    """
    if not server_info.get('reachable'):
        return (False, "")

    available_nodes = server_info.get('available_nodes', set())

    # ── Check custom nodes ──
    # Each feature lists node pack names (e.g., "comfyui-reactor-node")
    # which have a "provides" array of node class names in the manifest.
    node_packs = feat.get("custom_nodes", [])
    for pack_name in node_packs:
        pack_def = manifest.get("custom_nodes", {}).get(pack_name, {})
        provides = pack_def.get("provides", [])
        if provides and not any(p in available_nodes for p in provides):
            return (False, "")

    # ── Check required models ──
    # Collect all model names that the server reports (flatten all lists).
    # Model paths in the manifest use subdirectory prefixes like
    # "checkpoints/SDXL/model.safetensors" but ComfyUI returns just the
    # relative path from the model root (e.g., "SDXL\\model.safetensors"
    # or "SDXL/model.safetensors").
    server_models: set[str] = set()
    for key in ('checkpoints', 'unet_models', 'loras', 'vaes',
                'clip_models', 'controlnets'):
        for m in server_info.get(key, []):
            # Normalize to lowercase for comparison
            server_models.add(m.lower())
            # Also add just the filename for loose matching
            basename = m.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
            server_models.add(basename.lower())

    models = collect_models_for_feature(feat)
    required_models = [m for m in models if not m.get("optional", False)]

    if required_models:
        missing = 0
        for model in required_models:
            rel_path = model["path"]
            # Strip the top-level ComfyUI model type dir
            # e.g., "checkpoints/SDXL/foo.safetensors" → "SDXL/foo.safetensors"
            parts = rel_path.split("/", 1)
            inner_path = parts[1] if len(parts) > 1 else parts[0]
            basename = rel_path.rsplit("/", 1)[-1]

            # Check multiple matching strategies
            found = (
                inner_path.lower() in server_models
                or inner_path.replace("/", "\\").lower() in server_models
                or basename.lower() in server_models
                or rel_path.lower() in server_models
            )
            if not found:
                missing += 1

        if missing > 0:
            return (False, "")

    # Everything is present
    parts = []
    if node_packs:
        parts.append(f"{len(node_packs)} node pack(s)")
    if required_models:
        parts.append(f"{len(required_models)} model(s)")
    reason = "Already on server: " + " + ".join(parts) if parts else "Already installed"
    return (True, reason)


def download_file(url: str, dest: Path, dry_run: bool = False,
                  civitai_key: str = "", hf_token: str = "") -> bool:
    """Download a file from *url* to *dest* with a progress bar.

    Handles authentication for two model hosting platforms:
    - HuggingFace: Bearer token via Authorization header (for gated models)
    - CivitAI: API key appended as a query parameter (their auth mechanism)

    Cleans up partial files on failure to prevent corrupt model loading.
    """
    if dry_run:
        print(f"  {C_DIM}[dry-run] Would download: {url}{C_RESET}")
        print(f"  {C_DIM}         → {dest}{C_RESET}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  {C_CYAN}Downloading:{C_RESET} {dest.name}")
    # ── Inject auth tokens based on the hosting platform ──
    headers = {"User-Agent": "Spellcaster-Installer/1.0"}
    if "huggingface.co" in url and hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    if "civitai.com" in url and civitai_key:
        # CivitAI expects the token as a URL query param, not a header
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={civitai_key}"
    print(f"  {C_DIM}From: {url}{C_RESET}")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        # Render a 20-char wide progress bar with percentage and sizes
                        pct = downloaded * 100 // total
                        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                        print(f"\r  [{bar}] {pct}% ({fmt_size(downloaded / 1048576)}/{fmt_size(total / 1048576)})",
                              end="", flush=True)
            if total > 0:
                print()
        print(f"  {C_GREEN}✓ Saved to {dest}{C_RESET}")
        return True
    except urllib.error.HTTPError as e:
        if dest.exists():
            dest.unlink()
        if e.code == 401:
            if "huggingface.co" in url:
                print(f"\n  {C_RED}✗ 401 Unauthorized — this HuggingFace repo is gated.{C_RESET}")
                print(f"    Visit the model page, accept the license, then re-run with --hf-token YOUR_TOKEN")
            elif "civitai.com" in url:
                print(f"\n  {C_RED}✗ 401 Unauthorized — CivitAI requires an API key.{C_RESET}")
                print(f"    Re-run with --civitai-key YOUR_KEY")
            else:
                print(f"\n  {C_RED}✗ 401 Unauthorized: {e}{C_RESET}")
        elif e.code == 403:
            print(f"\n  {C_RED}✗ 403 Forbidden — access denied. The model may require authentication.{C_RESET}")
        else:
            print(f"\n  {C_RED}✗ Download failed (HTTP {e.code}): {e}{C_RESET}")
        return False
    except (urllib.error.URLError, OSError) as e:
        if dest.exists():
            dest.unlink()
        # Retry once on network errors
        print(f"\n  {C_YELLOW}⟳ Network error, retrying...{C_RESET}")
        try:
            import time; time.sleep(2)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as resp:
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk: break
                        f.write(chunk)
            print(f"  {C_GREEN}✓ Saved to {dest} (retry succeeded){C_RESET}")
            return True
        except Exception as e2:
            if dest.exists():
                dest.unlink()
            print(f"  {C_RED}✗ Download failed after retry: {e2}{C_RESET}")
            return False


def git_clone(repo_url: str, dest: Path, dry_run: bool = False) -> bool:
    """Clone a git repository with --depth 1 (shallow clone to save bandwidth).

    If git is not installed, falls back to downloading a ZIP archive from
    GitHub's archive endpoint. If the repo already exists, pulls latest changes.
    """
    if dry_run:
        print(f"  {C_DIM}[dry-run] Would clone: {repo_url} → {dest}{C_RESET}")
        return True
    if dest.exists():
        print(f"  {C_YELLOW}Already exists:{C_RESET} {dest.name} — pulling latest…")
        try:
            subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"],
                           capture_output=True, check=True, timeout=120)
            print(f"  {C_GREEN}✓ Updated {dest.name}{C_RESET}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return True  # pull failed but the repo exists — treat as success
    print(f"  {C_CYAN}Cloning:{C_RESET} {dest.name}")
    print(f"  {C_DIM}From: {repo_url}{C_RESET}")
    try:
        subprocess.run(["git", "clone", "--depth", "1", repo_url, str(dest)],
                       capture_output=True, check=True, timeout=300)
        print(f"  {C_GREEN}✓ Cloned {dest.name}{C_RESET}")
        return True
    except FileNotFoundError:
        # FileNotFoundError means git binary is not installed — use ZIP fallback
        return _download_and_extract_github_zip(repo_url, dest)
    except subprocess.CalledProcessError as e:
        print(f"  {C_RED}✗ Clone failed: {e.stderr.decode(errors='replace')}{C_RESET}")
        return False


def _download_and_extract_github_zip(repo_url: str, dest: Path) -> bool:
    """Fallback: download a GitHub repo as a ZIP when git is unavailable.

    Tries "main" branch first, then "master", since GitHub repos use either.
    Strips the top-level directory from the ZIP (e.g., "repo-main/") so the
    contents are extracted directly into *dest*.
    """
    import zipfile, io
    base_url = repo_url.rstrip("/")
    if base_url.endswith(".git"):
        base_url = base_url[:-4]
    print(f"  {C_YELLOW}Git not found — falling back to ZIP download…{C_RESET}")
    for branch in ["main", "master"]:
        zip_url = f"{base_url}/archive/refs/heads/{branch}.zip"
        try:
            req = urllib.request.Request(zip_url, headers={"User-Agent": "Spellcaster-Installer/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                # GitHub ZIPs always have a single top-level dir: "reponame-branch/"
                # Strip it so files land directly in dest/
                top = zf.namelist()[0].split('/')[0] + '/'
                dest_resolved = dest.resolve()
                for member in zf.infolist():
                    if member.filename == top:
                        continue
                    if member.filename.startswith(top):
                        rel = member.filename[len(top):]
                        if not rel:
                            continue
                        tp = dest / rel
                        # Path traversal guard — reject entries that escape dest
                        if not tp.resolve().parts[:len(dest_resolved.parts)] == dest_resolved.parts:
                            print(f"  {C_YELLOW}⚠ Skipping suspicious path: {rel}{C_RESET}")
                            continue
                        if member.is_dir():
                            tp.mkdir(parents=True, exist_ok=True)
                        else:
                            tp.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(member) as src, open(tp, "wb") as tgt:
                                shutil.copyfileobj(src, tgt)
            print(f"  {C_GREEN}✓ Extracted {dest.name}{C_RESET}")
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue  # branch name doesn't exist — try next one
            print(f"  {C_RED}✗ ZIP download failed ({e.code}){C_RESET}")
            return False
        except Exception as e:
            print(f"  {C_RED}✗ Extraction failed: {e}{C_RESET}")
            return False
    print(f"  {C_RED}✗ Could not find repo ZIP for {repo_url}{C_RESET}")
    return False


def get_comfy_python(comfyui_path: Path) -> str:
    """Locate the Python interpreter that ComfyUI uses for pip installs.

    Search order:
    1. Embedded Python (Windows portable builds ship python_embeded/)
    2. Embedded Python as sibling (portable layout: python_embeded/ next to ComfyUI/)
    3. Virtual environment (venv/ or .venv/, cross-platform)
    4. System Python via PATH (for PyInstaller-frozen installer builds)
    5. Current interpreter as last resort
    """
    if not comfyui_path:
        return sys.executable
    # Portable ComfyUI on Windows ships its own embedded Python
    embed = comfyui_path / "python_embeded" / "python.exe"
    if embed.exists():
        return str(embed)
    # Portable layout variant: python_embeded/ is a sibling of ComfyUI/
    # e.g., ComfyUI_windows_portable/python_embeded/ alongside .../ComfyUI/
    embed_sibling = comfyui_path.parent / "python_embeded" / "python.exe"
    if embed_sibling.exists():
        return str(embed_sibling)
    # Check common venv locations (Windows uses Scripts/, Unix uses bin/)
    for venv in ["venv", ".venv"]:
        for rel in [("Scripts", "python.exe"), ("bin", "python3"), ("bin", "python")]:
            vp = comfyui_path / venv / rel[0] / rel[1]
            if vp.exists():
                return str(vp)
    # When running as a frozen (PyInstaller) binary, sys.executable is the bundle,
    # not a real Python — look for system Python on PATH instead
    if hasattr(sys, 'frozen'):
        sys_py = shutil.which("python") or shutil.which("python3")
        if sys_py:
            return sys_py
    return sys.executable


def install_node_requirements(node_dir: Path, comfyui_path: Path, dry_run: bool = False) -> bool:
    """Run pip install -r requirements.txt for a custom node, using ComfyUI's Python."""
    req_file = node_dir / "requirements.txt"
    if not req_file.exists():
        return True
    if dry_run:
        print(f"  {C_DIM}[dry-run] Would install requirements from {req_file}{C_RESET}")
        return True
    print(f"  {C_CYAN}Installing requirements for {node_dir.name}…{C_RESET}")
    try:
        subprocess.run(
            [get_comfy_python(comfyui_path), "-m", "pip", "install", "-r", str(req_file)],
            capture_output=True, check=True, timeout=300
        )
        print(f"  {C_GREEN}✓ Requirements installed for {node_dir.name}{C_RESET}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  {C_YELLOW}⚠ Some requirements failed for {node_dir.name}{C_RESET}")
        print(f"    {C_DIM}{e.stderr.decode(errors='replace')[:200]}{C_RESET}")
        return False


def copy_plugin(src: Path, dest: Path, dry_run: bool = False) -> bool:
    """Copy a plugin file or directory to the target location.

    For directories, performs a full replacement (rmtree + copytree) to ensure
    stale files from previous versions are removed.
    """
    if dry_run:
        print(f"  {C_DIM}[dry-run] Would copy: {src} → {dest}{C_RESET}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if src.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        print(f"  {C_GREEN}✓ Installed: {dest}{C_RESET}")
        return True
    except OSError as e:
        print(f"  {C_RED}✗ Copy failed: {e}{C_RESET}")
        return False


_GIMP_TEMPLATE = '''(GimpTemplate "{name}"
    (width {w})
    (height {h})
    (unit pixels)
    (xresolution 72)
    (yresolution 72)
    (resolution-unit inches)
    (image-type rgb)
    (precision u8-non-linear)
    (color-profile NULL)
    (simulation-profile NULL)
    (simulation-bpc no)
    (simulation-intent relative-colorimetric)
    (fill-type background)
    (comment "{comment}")
    (filename ""))'''

# AI-optimized canvas sizes. All dimensions are multiples of 64 for
# broad compatibility across SD1.5 (mod-8), SDXL/ZIT (mod-8),
# Flux (mod-16), LTX Video (mod-32). Grouped by use case.
_AI_TEMPLATES = [
    # ── SD 1.5 native (512px) ──
    ("AI — SD1.5 Square 512×512",           512,  512, "SD 1.5 native. Fastest generation."),
    ("AI — SD1.5 Portrait 512×768",         512,  768, "SD 1.5 portrait (2:3)"),
    ("AI — SD1.5 Landscape 768×512",        768,  512, "SD 1.5 landscape (3:2)"),
    # ── SDXL / ZIT native (1024px) ──
    ("AI — SDXL Square 1024×1024",         1024, 1024, "SDXL / ZIT native. Best quality."),
    ("AI — SDXL Portrait 832×1216",         832, 1216, "SDXL portrait (close to 2:3)"),
    ("AI — SDXL Landscape 1216×832",       1216,  832, "SDXL landscape (close to 3:2)"),
    ("AI — SDXL Wide 1344×768",            1344,  768, "SDXL cinematic widescreen (16:9 approx)"),
    ("AI — SDXL Tall 768×1344",             768, 1344, "SDXL tall/mobile (9:16 approx)"),
    ("AI — SDXL Ultrawide 1536×640",       1536,  640, "SDXL ultrawide banner (2.4:1)"),
    # ── Flux / Klein native (1024px, mod-16) ──
    ("AI — Flux Square 1024×1024",         1024, 1024, "Flux 1 Dev / Klein native"),
    ("AI — Flux Portrait 896×1152",         896, 1152, "Flux portrait"),
    ("AI — Flux Landscape 1152×896",       1152,  896, "Flux landscape"),
    ("AI — Flux Cinematic 1280×720",       1280,  720, "Flux 16:9 cinematic"),
    # ── LTX Video (mod-32, 768px target) ──
    # ── Wan Video (mod-16, 832px target) ──
    ("AI — Wan Video 832×480",              832,  480, "Wan 2.2 Video landscape (default)"),
    ("AI — Wan Video 480×832",              480,  832, "Wan 2.2 Video portrait"),
    # ── Social Media ──
    ("AI — Instagram Square 1080×1080",    1088, 1088, "Instagram post (rounded to mod-64)"),
    ("AI — Instagram Story 1080×1920",     1088, 1920, "Instagram story / TikTok / Reels (9:16)"),
    ("AI — YouTube Thumbnail 1280×720",    1280,  720, "YouTube thumbnail (16:9)"),
    ("AI — Twitter/X Header 1500×500",     1536,  512, "Twitter header (rounded to mod-64)"),
    ("AI — Facebook Cover 820×312",         832,  320, "Facebook cover (rounded to mod-64)"),
    # ── Print-ready AI (upscale from 1024 base) ──
    ("AI — Print A4 Upscale 2048×2896",    2048, 2896, "A4 at 150dpi from SDXL 4x upscale"),
    ("AI — Print Letter Upscale 2048×2656", 2048, 2656, "US Letter at 150dpi from SDXL 4x upscale"),
]

_AI_TEMPLATE_MARKER = "Spellcaster AI"


def _delete_gimp_pluginrc():
    """Delete pluginrc from ALL GIMP versions to force procedure re-scan on next start."""
    home = Path.home()
    roots = []
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            roots.append(Path(appdata) / "GIMP")
    elif platform.system() == "Darwin":
        roots.append(home / "Library" / "Application Support" / "GIMP")
    else:
        roots.append(home / ".config" / "GIMP")
        roots.append(home / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP")

    for root in roots:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if d.is_dir() and (d.name.startswith("3") or d.name.startswith("2.99")):
                rc = d / "pluginrc"
                if rc.exists():
                    try:
                        rc.unlink()
                        print(f"  {C_GREEN}✓ Deleted GIMP {d.name} plugin cache{C_RESET}")
                    except Exception:
                        pass


def install_gimp_ai_templates(gimp_plugins_dir: Path, dry_run: bool = False) -> bool:
    """Append AI generation templates to GIMP's templaterc file.

    Finds the user's GIMP config directory (parent of plug-ins) and
    appends Spellcaster AI templates if not already present. GIMP loads
    templaterc on startup and persists changes on exit, so templates
    survive across sessions.
    """
    # The plug-ins dir is typically <config>/plug-ins, so config is one or two levels up
    # e.g., ~/.config/GIMP/3.0/plug-ins → ~/.config/GIMP/3.0/templaterc
    config_dir = gimp_plugins_dir.parent
    templaterc = config_dir / "templaterc"

    # Also check if plug-ins is nested deeper (e.g., GIMP/3.2/plug-ins → GIMP/3.2/templaterc)
    if not templaterc.exists():
        # Try the parent's parent (in case plug-ins is at <config>/3.0/plug-ins)
        alt = gimp_plugins_dir.parent.parent / "templaterc"
        if alt.exists():
            templaterc = alt
        else:
            # Search common GIMP config locations
            for candidate in [
                Path(os.environ.get("APPDATA", "")) / "GIMP",
                Path.home() / ".config" / "GIMP",
                Path.home() / "Library" / "Application Support" / "GIMP",
            ]:
                if candidate.exists():
                    for version_dir in sorted(candidate.iterdir(), reverse=True):
                        t = version_dir / "templaterc"
                        if t.exists():
                            templaterc = t
                            break
                    if templaterc.exists():
                        break

    if not templaterc.exists():
        print(f"  {C_DIM}  templaterc not found — skipping AI templates{C_RESET}")
        return False

    # Check if already installed
    try:
        existing = templaterc.read_text(encoding="utf-8")
    except Exception:
        existing = ""

    if _AI_TEMPLATE_MARKER in existing:
        print(f"  {C_GREEN}✓ AI templates already present in GIMP{C_RESET}")
        return True

    if dry_run:
        print(f"  {C_DIM}[dry-run] Would add {len(_AI_TEMPLATES)} AI templates to {templaterc}{C_RESET}")
        return True

    # Build template entries
    entries = [f"\n# ── {_AI_TEMPLATE_MARKER} Templates ──"]
    for name, w, h, comment in _AI_TEMPLATES:
        entries.append(_GIMP_TEMPLATE.format(name=name, w=w, h=h, comment=comment))

    # Insert before the "# end of templaterc" line, or append
    marker = "# end of templaterc"
    new_content = "\n".join(entries) + "\n"
    if marker in existing:
        patched = existing.replace(marker, new_content + marker)
    else:
        patched = existing.rstrip() + "\n" + new_content

    try:
        templaterc.write_text(patched, encoding="utf-8")
        print(f"  {C_GREEN}✓ Added {len(_AI_TEMPLATES)} AI canvas templates to GIMP{C_RESET}")
        return True
    except Exception as e:
        print(f"  {C_YELLOW}⚠ Could not write AI templates: {e}{C_RESET}")
        return False


def patch_plugin_server_url(file_path: Path, server_url: str, dry_run: bool = False) -> bool:
    """Patch the default ComfyUI server URL in a plugin file."""
    # Only patch if user specified a non-default (remote) server URL
    if server_url == DEFAULT_SERVER_URL:
        return True
    if dry_run:
        print(f"  {C_DIM}[dry-run] Would patch server URL in {file_path.name}: → {server_url}{C_RESET}")
        return True
    try:
        text = file_path.read_text(encoding="utf-8")
        if file_path.suffix == ".lua":
            # Replace the default URL in Darktable's dt.preferences.register() call
            # so the plugin connects to the remote ComfyUI instance out of the box
            new_text = re.sub(
                r'(dt\.preferences\.register\([^)]*"server_url"[^)]*,\s*")http://[^"]*(")',
                rf'\g<1>{server_url}\g<2>',
                text,
                flags=re.DOTALL
            )
            if new_text != text:
                file_path.write_text(new_text, encoding="utf-8")
                print(f"  {C_GREEN}✓ Patched server URL in {file_path.name}{C_RESET}")
        return True
    except OSError as e:
        print(f"  {C_YELLOW}⚠ Could not patch {file_path.name}: {e}{C_RESET}")
        return False


# ─── Feature size helpers ──────────────────────────────────────────────────────

def collect_models_for_feature(feature: dict[str, Any]) -> list[dict]:
    """Extract all model entries from a feature's manifest definition.

    The manifest "models" section has named groups (e.g., "checkpoints",
    "loras") each containing a list of model dicts, plus an optional "note"
    string that is skipped here.
    """
    models_section = feature.get("models", {})
    all_models = []
    for key, val in models_section.items():
        if key == "note":
            continue
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "path" in item:
                    all_models.append(item)
    return all_models


def estimate_feature_size(feature: dict[str, Any], required_only: bool = False) -> float:
    """Sum the size_mb of all models in a feature (optionally excluding optional ones)."""
    total = 0.0
    for m in collect_models_for_feature(feature):
        if required_only and m.get("optional", False):
            continue
        total += m.get("size_mb", 0)
    return total


def print_feature_summary(key: str, feature: dict[str, Any], selected: bool):
    """Print a formatted summary line for a feature showing selection state and size."""
    status = f"{C_GREEN}✓ SELECTED{C_RESET}" if selected else f"{C_DIM}  skipped{C_RESET}"
    req_size = estimate_feature_size(feature, required_only=True)
    full_size = estimate_feature_size(feature)
    nodes = feature.get("custom_nodes", [])
    node_str = f" + {len(nodes)} custom node(s)" if nodes else ""
    plugins_str = ", ".join(feature.get("plugins", []))
    print(f"  {status}  {C_BOLD}{feature['label']}{C_RESET}")
    print(f"         {C_DIM}{feature['description']}{C_RESET}")
    print(f"         Plugins: {plugins_str}{node_str}")
    if full_size > 0:
        if req_size != full_size:
            print(f"         Size: {C_YELLOW}{fmt_size(req_size)}{C_RESET} required, "
                  f"{fmt_size(full_size)} with all optional models")
        else:
            print(f"         Size: {C_YELLOW}{fmt_size(full_size)}{C_RESET}")


# ─── Installer steps ───────────────────────────────────────────────────────────

def step_api_keys(args) -> None:
    """Optional step: collect CivitAI and HuggingFace tokens for authenticated downloads."""
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  API Keys (Optional){C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")
    print(f"  {C_DIM}API tokens speed up and unlock downloads from CivitAI and HuggingFace.")
    print(f"  They are used only during this install session and never stored on disk.{C_RESET}\n")
    print(f"  {C_DIM}CivitAI token:    civitai.com → Account → API Keys{C_RESET}")
    print(f"  {C_DIM}HuggingFace token: huggingface.co → Settings → Access Tokens{C_RESET}\n")

    if not getattr(args, 'civitai_key', ''):
        args.civitai_key = ask_text(
            "  CivitAI API token (Enter to skip)", auto_yes=args.yes).strip()
    if not getattr(args, 'hf_token', ''):
        args.hf_token = ask_text(
            "  HuggingFace token (Enter to skip)", auto_yes=args.yes).strip()

    if getattr(args, 'civitai_key', ''):
        print(f"  {C_GREEN}✓ CivitAI token set{C_RESET}")
    else:
        print(f"  {C_DIM}  CivitAI token skipped — some models may need manual download{C_RESET}")
    if getattr(args, 'hf_token', ''):
        print(f"  {C_GREEN}✓ HuggingFace token set{C_RESET}")
    else:
        print(f"  {C_DIM}  HuggingFace token skipped{C_RESET}")


def step_system_detection(args) -> tuple[str, int]:
    """Detect GPU/VRAM, show hardware profile, and warn if no GPU found."""
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  System Detection{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    gpu_name, vram_mb = detect_gpu_vram()
    tier = vram_tier(vram_mb)

    if vram_mb > 0:
        vram_gb = vram_mb / 1024
        print(f"  {C_GREEN}GPU:{C_RESET}   {gpu_name}")
        print(f"  {C_GREEN}VRAM:{C_RESET}  {vram_gb:.1f} GB")
        tier_labels = {
            "low":    f"{C_YELLOW}Low (<8 GB) \u2014 SD1.5 + lightweight features{C_RESET}",
            "medium": f"{C_CYAN}Medium (8\u201312 GB) \u2014 core features + fp8/GGUF models{C_RESET}",
            "high":   f"{C_GREEN}High (12\u201320 GB) \u2014 most features + fp8 models{C_RESET}",
            "ultra":  f"{C_GREEN}Power User (24+ GB) \u2014 everything, full precision{C_RESET}",
        }
        print(f"  {C_GREEN}Tier:{C_RESET}  {tier_labels.get(tier, tier)}")

        # Show what this means for feature selection
        if tier == "ultra":
            print(f"\n  {C_GREEN}All features and full-precision models are available.{C_RESET}")
        elif tier == "high":
            print(f"\n  {C_GREEN}Most features work great. fp8 models recommended for video/Flux.{C_RESET}")
        elif tier == "medium":
            print(f"\n  {C_CYAN}Core features work well. GGUF/fp8 models recommended.{C_RESET}")
            print(f"  {C_CYAN}Video features will work but may be slow.{C_RESET}")
        elif tier == "low":
            print(f"\n  {C_YELLOW}SD1.5 and lightweight features recommended.{C_RESET}")
            print(f"  {C_YELLOW}SDXL/Flux/video features may not fit in VRAM.{C_RESET}")
    else:
        # \u2500\u2500 No GPU detected \u2014 prominent warning \u2500\u2500
        print(f"\n  {C_RED}{'=' * 46}{C_RESET}")
        print(f"  {C_RED}  !!  NO COMPATIBLE GPU DETECTED  !!{C_RESET}")
        print(f"  {C_RED}{'=' * 46}{C_RESET}")
        print(f"""
  Spellcaster requires a GPU with at least 4 GB VRAM to function.
  Without a GPU, AI features will either:
    \u2022 Not work at all (most features)
    \u2022 Run extremely slowly on CPU (basic upscaling only)

  If you have a GPU but it wasn't detected:
    \u2022 NVIDIA: Install the latest NVIDIA drivers + CUDA toolkit
    \u2022 AMD:   Install ROCm drivers (Linux) or DirectML (Windows)
    \u2022 Intel: Not currently supported

  You can still install the plugins, but they will need a remote
  ComfyUI server with a GPU to function.
""")
        if not ask_yn("  Continue anyway? (for remote server setups)", default=False, auto_yes=args.yes):
            print(f"\n{C_YELLOW}Installation cancelled.{C_RESET}")
            sys.exit(0)

        # Still let user manually specify their tier if continuing
        print()
        choices = ["No GPU / remote server (skip VRAM-based selection)",
                   "Low (<8 GB VRAM) \u2014 Q4/Q5 GGUF",
                   "Medium (8\u201312 GB) \u2014 fp8 / Q8",
                   "High (12\u201320 GB) \u2014 fp8 or bf16",
                   "Ultra (20+ GB) \u2014 full precision"]
        idx = ask_choice("  If using a remote server, what GPU does it have?",
                         choices, default=0, auto_yes=args.yes)
        if idx == 0:
            tier = "unknown"
            vram_mb = 0
        else:
            tier = ["low", "medium", "high", "ultra"][idx - 1]
            vram_mb = [4096, 10240, 16384, 24576][idx - 1]
            print(f"  Using tier: {tier.upper()}")

    # Stash detection results as private attrs for downstream steps to reference
    args._gpu_name = gpu_name
    args._vram_mb  = vram_mb
    args._vram_tier = tier
    return gpu_name, vram_mb


def step_detect_server(args) -> str:
    """Step 0: Determine ComfyUI server URL."""
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  STEP 1: ComfyUI Server{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    if args.server_url:
        print(f"  {C_GREEN}Using specified server URL:{C_RESET} {args.server_url}")
        return args.server_url

    print(f"  The plugins need to connect to a running ComfyUI instance.")
    print(f"  {C_DIM}Default: {DEFAULT_SERVER_URL} (ComfyUI running on this machine){C_RESET}\n")

    choice = ask_choice(
        "Where is ComfyUI running?",
        [
            f"On this machine  (localhost — {DEFAULT_SERVER_URL})",
            "On another machine on my local network  (enter IP:port)",
            "Custom URL  (enter full URL)",
        ],
        default=0,
        auto_yes=args.yes,
    )

    if choice == 0:
        return DEFAULT_SERVER_URL
    elif choice == 1:
        print(f"\n  {C_DIM}Example: <SERVER-IP>:8188{C_RESET}")
        raw = ask_text("  Enter IP:port of the ComfyUI machine", auto_yes=args.yes)
        raw = raw.strip().rstrip("/")
        if not raw.startswith("http"):
            raw = "http://" + raw
        return raw
    else:
        raw = ask_text("  Enter full ComfyUI URL", default=DEFAULT_SERVER_URL, auto_yes=args.yes)
        return raw.strip().rstrip("/")


def step_detect_llm_server(args, server_url: str = "",
                           server_info: dict | None = None) -> str:
    """Determine LLM configuration.

    Priority:
      1. ComfyUI-native LLM nodes (auto-detected from server probe)
         — installed via the prompt_enhance feature, zero config needed
      2. External LLM server (KoboldCpp / Ollama / OpenAI-compatible)
    """
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  LLM (Prompt Enhancement & Wizard Guild){C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    # Check if ComfyUI already has native LLM nodes
    available = (server_info or {}).get('available_nodes', set())
    if "AILab_QwenVL_GGUF_PromptEnhancer" in available:
        print(f"  {C_GREEN}✓ ComfyUI-native LLM detected on server{C_RESET}")
        print(f"  {C_DIM}  Node: AILab_QwenVL_GGUF_PromptEnhancer{C_RESET}")
        print(f"  {C_DIM}  No separate LLM server needed — ComfyUI manages VRAM automatically.{C_RESET}")
        print(f"  {C_DIM}  Select the 'AI Prompt Enhancement' feature to install the GGUF model.{C_RESET}\n")
        return ""  # No external LLM needed

    print(f"  Spellcaster can enhance prompts using a local LLM.")
    print(f"  {C_GREEN}Recommended:{C_RESET} Select the 'AI Prompt Enhancement' feature")
    print(f"  to install ComfyUI-native LLM nodes (no separate server needed).\n")
    print(f"  {C_DIM}Alternative: use an external LLM server (KoboldCpp, Ollama, etc.){C_RESET}\n")

    if hasattr(args, 'llm_url') and args.llm_url:
        print(f"  {C_GREEN}Using specified LLM URL:{C_RESET} {args.llm_url}")
        return args.llm_url

    choice = ask_choice(
        "External LLM server? (skip if using ComfyUI-native via prompt_enhance feature)",
        [
            "No external server needed  (recommended)",
            f"Yes, on this machine  ({DEFAULT_LLM_URL})",
            "Yes, on another machine  (enter URL)",
        ],
        default=0,
        auto_yes=args.yes,
    )

    if choice == 1:
        return DEFAULT_LLM_URL
    elif choice == 2:
        print(f"\n  {C_DIM}Example: http://<SERVER-IP>:5001{C_RESET}")
        raw = ask_text("  Enter LLM server URL", default=DEFAULT_LLM_URL, auto_yes=args.yes)
        raw = raw.strip().rstrip("/")
        if not raw.startswith("http"):
            raw = "http://" + raw
        return raw
    else:
        return ""


def step_probe_server(server_url: str, args) -> dict:
    """Probe the ComfyUI server to discover installed nodes, models, and LoRAs.

    Returns a dict with:
        - 'available_nodes': set of class_type strings available on the server
        - 'checkpoints': list of checkpoint model names
        - 'unet_models': list of diffusion_model names
        - 'loras': list of LoRA names (full relative paths)
        - 'vaes': list of VAE names
        - 'clip_models': list of text_encoder names
        - 'controlnets': list of controlnet names
        - 'reachable': bool
    """
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  Probing ComfyUI Server{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    result = {
        'available_nodes': set(),
        'checkpoints': [],
        'unet_models': [],
        'loras': [],
        'vaes': [],
        'clip_models': [],
        'controlnets': [],
        'reachable': False,
    }

    print(f"  Connecting to {C_CYAN}{server_url}{C_RESET}...")

    # Test connectivity
    try:
        req = urllib.request.Request(f"{server_url}/system_stats")
        with urllib.request.urlopen(req, timeout=10) as resp:
            stats = json.loads(resp.read().decode('utf-8'))
            vram_total = stats.get('devices', [{}])[0].get('vram_total', 0)
            vram_gb = vram_total / (1024**3) if vram_total else 0
            print(f"  {C_GREEN}✓ Server reachable{C_RESET}")
            if vram_gb > 0:
                print(f"    Remote GPU VRAM: {vram_gb:.1f} GB")
        result['reachable'] = True
    except Exception as e:
        print(f"  {C_YELLOW}⚠ Cannot reach ComfyUI at {server_url}: {e}{C_RESET}")
        print(f"    Features will be based on manifest defaults.")
        return result

    # Fetch installed nodes (class types)
    try:
        req = urllib.request.Request(f"{server_url}/object_info")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            result['available_nodes'] = set(data.keys())
            print(f"    Installed nodes: {len(result['available_nodes'])}")
    except Exception as e:
        print(f"  {C_YELLOW}⚠ Could not fetch node info: {e}{C_RESET}")

    # Fetch model lists from specific node endpoints
    MODEL_QUERIES = {
        'checkpoints': ('CheckpointLoaderSimple', 'ckpt_name'),
        'loras': ('LoraLoader', 'lora_name'),
        'vaes': ('VAELoader', 'vae_name'),
        'controlnets': ('ControlNetLoader', 'control_net_name'),
    }

    for key, (node_type, param_name) in MODEL_QUERIES.items():
        try:
            req = urllib.request.Request(f"{server_url}/object_info/{node_type}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                items = data.get(node_type, {}).get('input', {}).get('required', {}).get(param_name, [None])[0]
                if isinstance(items, list):
                    result[key] = items
                    print(f"    {key}: {len(items)}")
        except Exception:
            pass

    # Fetch UNET/diffusion models
    for node_type in ['UNETLoader', 'UnetLoaderGGUF']:
        if node_type in result['available_nodes']:
            try:
                req = urllib.request.Request(f"{server_url}/object_info/{node_type}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    items = data.get(node_type, {}).get('input', {}).get('required', {}).get('unet_name', [None])[0]
                    if isinstance(items, list):
                        result['unet_models'] = items
                        print(f"    unet_models: {len(items)}")
            except Exception:
                pass
            break

    # Fetch CLIP/text_encoder models
    for node_type in ['CLIPLoader', 'DualCLIPLoader']:
        if node_type in result['available_nodes']:
            try:
                req = urllib.request.Request(f"{server_url}/object_info/{node_type}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    # CLIPLoader uses clip_name, DualCLIPLoader uses clip_name1
                    for pname in ['clip_name', 'clip_name1']:
                        items = data.get(node_type, {}).get('input', {}).get('required', {}).get(pname, [None])[0]
                        if isinstance(items, list):
                            result['clip_models'] = items
                            print(f"    clip_models: {len(items)}")
                            break
            except Exception:
                pass
            break

    return result


def _classify_server_loras(loras: list) -> dict:
    """Classify LoRAs by architecture using ComfyUI path prefixes + name hints.

    Returns dict mapping lora_name → list of compatible arch keys.
    """
    # Try to import from spellcaster_core, but fall back to inline dicts if not available
    try:
        from spellcaster_core.model_detect import LORA_ARCH_PREFIXES, LORA_NAME_ARCH_HINTS
    except ImportError:
        # Fallback: basic architecture classification
        LORA_ARCH_PREFIXES = {
            "sd15": ["models/loras/sd15"],
            "sdxl": ["models/loras/sdxl"],
            "flux": ["models/loras/flux"],
        }
        LORA_NAME_ARCH_HINTS = [
            ("sd15", "sd15"),
            ("sdxl", "sdxl"),
            ("flux", "flux"),
        ]

    result = {}
    for lora in loras:
        archs = []
        for arch, prefixes in LORA_ARCH_PREFIXES.items():
            if not prefixes:
                continue
            for p in prefixes:
                alt = p.replace("\\", "/") if "\\" in p else p.replace("/", "\\")
                if lora.startswith(p) or lora.startswith(alt):
                    archs.append(arch)
                    break

        if not archs:
            lora_lower = lora.lower().replace("\\", "/")
            for hint_kw, hint_arch in LORA_NAME_ARCH_HINTS:
                if hint_kw in lora_lower:
                    archs = [hint_arch]
                    break

        # CRITICAL FIX: Do NOT default to sd15 — unmatched LoRAs get "unknown"
        # so they don't pollute architecture-specific dropdowns.
        # They remain accessible in manual mode but won't auto-appear
        if not archs:
            archs = ["unknown"]

        result[lora] = archs
    return result


def _write_shared_settings(paths: dict, server_url: str, llm_url: str,
                           server_info: dict, dry_run: bool = False):
    """Write spellcaster_settings.json — the ONE shared config all plugins read.

    Stored alongside the installer (or in a platform-appropriate location).
    Each plugin also gets a copy written into its own directory.
    """
    # Classify LoRAs by architecture
    lora_archs = {}
    if server_info.get('loras'):
        try:
            lora_archs = _classify_server_loras(server_info['loras'])
        except Exception as e:
            print(f"  {C_YELLOW}⚠ LoRA classification failed: {e}{C_RESET}")

    settings = {
        "version": VERSION,
        "comfyui_url": server_url,
        "llm_url": llm_url,
        "server_reachable": server_info.get('reachable', False),
        "available_nodes": sorted(server_info.get('available_nodes', set())),
        "models": {
            "checkpoints": server_info.get('checkpoints', []),
            "unet_models": server_info.get('unet_models', []),
            "loras": server_info.get('loras', []),
            "vaes": server_info.get('vaes', []),
            "clip_models": server_info.get('clip_models', []),
            "controlnets": server_info.get('controlnets', []),
        },
        "lora_architectures": lora_archs,
    }

    if dry_run:
        print(f"  {C_DIM}[dry-run] Would write spellcaster_settings.json{C_RESET}")
        return settings

    # Write to installer directory (master copy)
    master_path = SCRIPT_DIR / "spellcaster_settings.json"
    try:
        master_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        print(f"  {C_GREEN}✓ Wrote master settings: {master_path}{C_RESET}")
    except Exception as e:
        print(f"  {C_YELLOW}⚠ Failed to write master settings: {e}{C_RESET}")

    # Copy to GIMP plugin directory
    if paths.get("gimp"):
        gimp_dest = paths["gimp"] / "comfyui-connector" / "spellcaster_settings.json"
        try:
            gimp_dest.parent.mkdir(parents=True, exist_ok=True)
            gimp_dest.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    return settings


def step_detect_paths(args) -> dict:
    """Step 2: Detect or ask for application paths."""
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  STEP 2: Application Paths{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    # ── ComfyUI ──
    comfyui_path = None
    if args.comfyui:
        p = Path(args.comfyui).expanduser().resolve()
        if p.is_dir():
            comfyui_path = p
            print(f"  {C_GREEN}ComfyUI (from args):{C_RESET} {comfyui_path}")
        else:
            print(f"  {C_RED}--comfyui path not found: {p}{C_RESET}")

    if comfyui_path is None:
        default_comfyui = find_default_comfyui()
        if default_comfyui:
            print(f"  {C_GREEN}✓ DETECTED — ComfyUI at:{C_RESET} {default_comfyui}")
            print(f"  {C_DIM}  (Your existing installation will NOT be modified or overwritten.{C_RESET}")
            print(f"  {C_DIM}   We only ADD plugins and models alongside your existing files.){C_RESET}")
            if ask_yn("  Use this path?", auto_yes=args.yes):
                comfyui_path = Path(default_comfyui)
            else:
                comfyui_path = ask_path("  Enter ComfyUI root directory")
        else:
            print(f"  {C_YELLOW}✗ ComfyUI not found automatically.{C_RESET}")
            print(f"  {C_DIM}  Searched: env vars, PATH, all drives, common locations.{C_RESET}")
            choice = ask_choice(
                "ComfyUI setup:",
                [
                    "Specify location manually",
                    "Download & install ComfyUI  (requires git + Python 3.10+)",
                    "Skip — I'll handle models/nodes myself",
                ],
                auto_yes=args.yes,
            )
            if choice == 0:
                comfyui_path = ask_path("  Enter ComfyUI root directory")
            elif choice == 1:
                install_dir = ask_path("  Where to install ComfyUI?", must_exist=True,
                                       default=str(Path.home()))
                comfyui_path = install_dir / "ComfyUI"
                if not args.dry_run:
                    print(f"\n  {C_CYAN}Cloning ComfyUI…{C_RESET}")
                    if not git_clone("https://github.com/comfyanonymous/ComfyUI.git",
                                     comfyui_path, args.dry_run):
                        print(f"  {C_RED}Failed to clone ComfyUI. Continuing without it.{C_RESET}")
                        comfyui_path = None
                    else:
                        req = comfyui_path / "requirements.txt"
                        if req.exists():
                            print(f"  {C_CYAN}Installing ComfyUI Python dependencies…{C_RESET}")
                            subprocess.run(
                                [get_comfy_python(comfyui_path), "-m", "pip", "install", "-r", str(req)],
                                capture_output=True, timeout=600
                            )
            # else: skip

    # ── GIMP ──
    gimp_path = None
    print()
    if args.gimp:
        p = Path(args.gimp).expanduser().resolve()
        if p.is_dir():
            gimp_path = p
            print(f"  {C_GREEN}GIMP plug-ins (from args):{C_RESET} {gimp_path}")
        else:
            print(f"  {C_RED}--gimp path not found: {p}{C_RESET}")

    if gimp_path is None:
        default_gimp = find_default_gimp()
        if default_gimp:
            print(f"  {C_GREEN}✓ DETECTED — GIMP 3 plug-ins at:{C_RESET} {default_gimp}")
            print(f"  {C_DIM}  (Your GIMP installation is safe. We only ADD the Spellcaster plugin.{C_RESET}")
            print(f"  {C_DIM}   No existing plugins or settings will be changed.){C_RESET}")
            if ask_yn("  Install GIMP plugin here?", auto_yes=args.yes):
                gimp_path = Path(default_gimp)
            else:
                if ask_yn("  Install GIMP plugin to a different path?", default=False, auto_yes=args.yes):
                    gimp_path = ask_path("  Enter GIMP 3 plug-ins directory")
        else:
            print(f"  {C_YELLOW}✗ GIMP 3 plug-ins directory not found automatically.{C_RESET}")
            print(f"  {C_DIM}  Searched: env vars, registry, PATH, config dirs (Roaming+Local), Flatpak, Snap.{C_RESET}")
            print(f"  {C_DIM}  Note: GIMP must have been launched at least once to create its config directory.{C_RESET}")
            if ask_yn("  Install the GIMP plugin?", auto_yes=args.yes):
                print(f"  {C_DIM}Typical locations:{C_RESET}")
                if platform.system() == "Windows":
                    print(f"    Windows: %APPDATA%\\GIMP\\3.0\\plug-ins  (or 3.2 for GIMP 3.2+)")
                elif platform.system() == "Darwin":
                    print(f"    macOS:   ~/Library/Application Support/GIMP/3.0/plug-ins  (or 3.2)")
                else:
                    print(f"    Linux:   ~/.config/GIMP/3.0/plug-ins  (or 3.2 for GIMP 3.2+)")
                gimp_path = ask_path("  Enter GIMP 3 plug-ins directory", must_exist=False)
                if not gimp_path.exists():
                    gimp_path.mkdir(parents=True, exist_ok=True)

    # ── Darktable ──
    dt_path = None
    print()
    if args.darktable:
        p = Path(args.darktable).expanduser().resolve()
        if p.is_dir():
            dt_path = p
            print(f"  {C_GREEN}Darktable lua/contrib (from args):{C_RESET} {dt_path}")
        else:
            print(f"  {C_RED}--darktable path not found: {p}{C_RESET}")

    if dt_path is None:
        default_dt = find_default_darktable()
        if default_dt:
            print(f"  {C_GREEN}✓ DETECTED — Darktable lua/contrib at:{C_RESET} {default_dt}")
            print(f"  {C_DIM}  (Your Darktable installation is safe. We only ADD the Spellcaster script.){C_RESET}")
            if ask_yn("  Install Darktable plugin here?", auto_yes=args.yes):
                dt_path = Path(default_dt)
            else:
                if ask_yn("  Install Darktable plugin to a different path?", default=False, auto_yes=args.yes):
                    dt_path = ask_path("  Enter darktable lua/contrib directory")
        else:
            print(f"  {C_YELLOW}✗ Darktable lua/contrib directory not found.{C_RESET}")
            print(f"  {C_DIM}  Searched: env vars, PATH, config dirs, Flatpak, system paths.{C_RESET}")
            if ask_yn("  Install the Darktable plugin?", default=False, auto_yes=args.yes):
                print(f"  {C_DIM}Typical locations:{C_RESET}")
                if platform.system() == "Windows":
                    print(f"    Windows: %LOCALAPPDATA%\\darktable\\lua\\contrib")
                elif platform.system() == "Darwin":
                    print(f"    macOS:   ~/Library/Application Support/darktable/lua/contrib")
                else:
                    print(f"    Linux:   ~/.config/darktable/lua/contrib")
                dt_path = ask_path("  Enter darktable lua/contrib directory", must_exist=False)
                if not dt_path.exists():
                    dt_path.mkdir(parents=True, exist_ok=True)

    if not gimp_path and not dt_path:
        print(f"\n  {C_YELLOW}⚠ No plugin host selected. Plugins will not be installed.{C_RESET}")
        print(f"    You can still install custom nodes and models for ComfyUI.")

    return {"comfyui": comfyui_path, "gimp": gimp_path, "darktable": dt_path}


def step_select_features(manifest: dict, paths: dict, args,
                         server_info: dict | None = None) -> dict[str, bool]:
    """Step 3: Feature selection with VRAM-aware pre-selection."""
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  STEP 3: Select Features{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    vram_gb = getattr(args, '_vram_mb', 0) / 1024

    # ── Smart auto-profile based on VRAM ──────────────────────────
    # Shows the user what we recommend BEFORE the detailed grid.
    if vram_gb >= 12:
        print(f"  {C_GREEN}Your GPU has {vram_gb:.0f} GB VRAM — you can run Flux 2 Klein.{C_RESET}")
        print(f"  {C_BOLD}Recommended: Klein-first install (~37 GB){C_RESET}")
        print(f"  Klein replaces most SDXL/SD1.5 tools with faster, higher-quality")
        print(f"  equivalents. No ControlNet models needed. Dramatically smaller install.\n")
        print(f"  {C_DIM}Alternative: Full install with SDXL+Klein+ControlNet (~150 GB)")
        print(f"  Use this if you need SD1.5/SDXL compatibility or anime models.{C_RESET}\n")
    elif vram_gb >= 8:
        print(f"  {C_GREEN}Your GPU has {vram_gb:.0f} GB VRAM — good for SDXL and video.{C_RESET}")
        print(f"  {C_BOLD}Recommended: SDXL essentials (~45 GB){C_RESET}")
        print(f"  Includes image generation, upscaling, face tools, and video.\n")
    elif vram_gb >= 4:
        print(f"  {C_YELLOW}Your GPU has {vram_gb:.0f} GB VRAM — SD 1.5 is your best bet.{C_RESET}")
        print(f"  {C_BOLD}Recommended: Lightweight install (~15 GB){C_RESET}")
        print(f"  Includes SD 1.5 generation, upscaling, and basic face tools.\n")
    else:
        print(f"  {C_YELLOW}GPU VRAM not detected or very low.{C_RESET}")
        print(f"  {C_BOLD}Recommended: Minimal install (~5 GB){C_RESET}\n")

    print(f"  {C_DIM}You can always re-run this installer later to add more models,")
    print(f"  switch generation engines, or install additional features.{C_RESET}\n")

    if server_info is None:
        server_info = {}

    vram_mb = getattr(args, '_vram_mb', 0)
    features = manifest["features"]

    # When --features is given on the CLI, skip interactive prompts
    forced_features: set[str] | None = None
    if args.features:
        forced_features = {f.strip() for f in args.features.split(",")}

    has_gimp = paths["gimp"] is not None
    has_dt = paths["darktable"] is not None

    # \u2500\u2500 Phase 1: Classify every feature \u2500\u2500
    # Build a list of (key, feat, status, reason, default_checked)
    # Each entry: (key, feat, status, reason, default_checked, locked)
    # locked=True means the feature's nodes+models are already on the server
    # and the user cannot toggle it — it's a no-op to reinstall.
    feature_list: list[tuple[str, dict, str, str, bool, bool]] = []
    feature_compat: dict[str, tuple[str, str]] = {}
    locked_features: set[str] = set()

    for key, feat in features.items():
        status, reason = feature_compatible(feat, vram_mb)

        # Auto-check logic:
        # - "ok"        -> checked by default
        # - "warn"      -> checked but with warning
        # - "no"        -> unchecked, greyed out
        # - "nogpu"     -> unchecked
        # - "installed" -> locked on, already present on server
        default_on = status in ("ok", "warn")

        # Also check if the host app is available
        plugins = feat.get("plugins", [])
        app_available = ("gimp" in plugins and has_gimp) or ("darktable" in plugins and has_dt)
        if not app_available:
            default_on = False
            if status not in ("no", "nogpu"):
                status = "no"
                reason = "No compatible host app detected"

        # Check if feature is already fully installed on the ComfyUI server
        locked = False
        already_ok, installed_reason = feature_already_installed(
            feat, manifest, server_info)
        if already_ok:
            locked = True
            default_on = True
            status = "installed"
            reason = installed_reason
            locked_features.add(key)

        feature_list.append((key, feat, status, reason, default_on, locked))
        feature_compat[key] = (status, reason)

    # \u2500\u2500 Phase 2: Display grouped features with status indicators \u2500\u2500
    categories = {
        "Core (recommended)": ["klein_flux2", "img2img", "txt2img", "inpaint", "upscale",
                                "face_swap_reactor", "rembg", "prompt_enhance"],
        "Enhancement": ["photo_restore", "detail_hallucinate", "seedv2r", "supir",
                         "face_restore", "lama_remove", "colorize"],
        "Style & Lighting": ["style_transfer", "lut_grading", "iclight"],
        "Face (alternatives)": ["face_swap_mtb", "faceid_img2img", "pulid_flux"],
        "Video": ["wan_i2v"],
        "Advanced (power users)": ["outpaint", "batch_variations", "controlnet"],
        "Chat Interface": ["wizard_guild"],
    }

    vram_label = f"{vram_mb/1024:.0f} GB VRAM" if vram_mb > 0 else "no GPU detected"
    print(f"  Features are pre-selected based on your hardware ({vram_label}):\n")

    if locked_features:
        print(f"  {C_CYAN}{len(locked_features)} feature(s) already installed on your"
              f" ComfyUI server — these are locked.{C_RESET}\n")

    for cat_name, cat_keys in categories.items():
        print(f"  {C_BOLD}\u2500\u2500 {cat_name} \u2500\u2500{C_RESET}")
        for key, feat, status, reason, default_on, locked in feature_list:
            if key not in cat_keys:
                continue

            # Status icons
            if status == "installed":
                icon = f"{C_CYAN}[\u2713]{C_RESET}"
            elif status == "ok":
                icon = f"{C_GREEN}[+]{C_RESET}"
            elif status == "warn":
                icon = f"{C_YELLOW}[~]{C_RESET}"
            elif status == "no":
                icon = f"{C_RED}[x]{C_RESET}"
            else:  # nogpu
                icon = f"{C_RED}[x]{C_RESET}"

            label = feat["label"]
            size = estimate_feature_size(feat, required_only=True)
            size_str = f" ({fmt_size(size)})" if size > 0 else ""

            if reason:
                print(f"    {icon} {label}{size_str}  {C_DIM}\u2014 {reason}{C_RESET}")
            else:
                print(f"    {icon} {label}{size_str}")
        print()

    print(f"  {C_CYAN}[\u2713]{C_RESET} = already installed on server (locked)")
    print(f"  {C_GREEN}[+]{C_RESET} = compatible & pre-selected")
    print(f"  {C_YELLOW}[~]{C_RESET} = works but may be slow on your hardware")
    print(f"  {C_RED}[x]{C_RESET} = incompatible with your VRAM or no host app detected\n")

    # \u2500\u2500 Phase 3: Let user customize \u2500\u2500
    selected: dict[str, bool] = {}

    if forced_features is not None:
        # --features flag overrides everything (but locked features stay on)
        for key, feat, status, reason, default_on, locked in feature_list:
            selected[key] = (key in forced_features) or locked
    elif args.yes:
        # Auto mode: use smart defaults
        for key, feat, status, reason, default_on, locked in feature_list:
            selected[key] = default_on
    else:
        # Interactive: show the grid, ask if they want to customize
        for key, feat, status, reason, default_on, locked in feature_list:
            selected[key] = default_on

        if ask_yn("  Use these recommended selections?", default=True):
            pass  # Keep defaults
        else:
            # Let user toggle individual features
            print(f"\n  {C_DIM}Answer y/n for each feature.")
            if locked_features:
                print(f"  Features marked [\u2713] are already on your server and cannot be toggled.")
            print(f"  Features marked [x] are not recommended.{C_RESET}\n")
            handled = set()

            for key, feat, status, reason, default_on, locked in feature_list:
                if key in handled:
                    continue

                # Locked features cannot be toggled — skip the prompt
                if locked:
                    handled.add(key)
                    print(f"    {C_CYAN}[\u2713] {feat['label']}{C_RESET}  {C_DIM}\u2014 {reason}{C_RESET}")
                    continue

                # \u2500\u2500 Special case: ReActor vs MTB face swap grouped choice \u2500\u2500
                if key in ("face_swap_reactor", "face_swap_mtb"):
                    handled.add("face_swap_reactor")
                    handled.add("face_swap_mtb")

                    # If both are locked, skip entirely
                    if "face_swap_reactor" in locked_features and "face_swap_mtb" in locked_features:
                        print(f"    {C_CYAN}[\u2713] Face Swap (ReActor + MTB){C_RESET}  {C_DIM}\u2014 already installed{C_RESET}")
                        continue

                    # Check app availability for face swap
                    fs_plugins = feat.get("plugins", [])
                    fs_available = ("gimp" in fs_plugins and has_gimp) or ("darktable" in fs_plugins and has_dt)
                    if not fs_available:
                        selected["face_swap_reactor"] = "face_swap_reactor" in locked_features
                        selected["face_swap_mtb"] = "face_swap_mtb" in locked_features
                        continue

                    reactor_feat = features.get("face_swap_reactor", {})
                    mtb_feat = features.get("face_swap_mtb", {})
                    reactor_size = estimate_feature_size(reactor_feat, required_only=True)

                    reactor_status = feature_compat.get("face_swap_reactor", ("ok", ""))[0]
                    vram_note = ""
                    if reactor_status == "no":
                        vram_note = f" {C_RED}(NOT RECOMMENDED: {feature_compat['face_swap_reactor'][1]}){C_RESET}"
                    elif reactor_status == "warn":
                        vram_note = f" {C_YELLOW}({feature_compat['face_swap_reactor'][1]}){C_RESET}"

                    print(f"\n  {C_BOLD}Face Swap Systems{C_RESET}{vram_note}")
                    print(f"  {C_DIM}ReActor: industry-standard swap, CodeFormer restore (~{fmt_size(reactor_size)}){C_RESET}")
                    print(f"  {C_DIM}MTB:     lightweight alternative, auto-downloads models{C_RESET}")

                    choice = ask_choice(
                        "Which face swap system(s) would you like to install?",
                        [
                            "Both ReActor and MTB  (recommended \u2014 different strengths)",
                            f"ReActor only  (~{fmt_size(reactor_size)} downloads)",
                            "MTB only  (no model downloads required)",
                            "Neither \u2014 skip face swap",
                        ],
                        default=0 if default_on else 3,
                        auto_yes=args.yes,
                    )
                    selected["face_swap_reactor"] = choice in (0, 1) or "face_swap_reactor" in locked_features
                    selected["face_swap_mtb"] = choice in (0, 2) or "face_swap_mtb" in locked_features
                    if selected.get("face_swap_reactor") or selected.get("face_swap_mtb"):
                        if reactor_status == "no":
                            print(f"    {C_YELLOW}Warning: Overriding recommendation \u2014 this may not work with your VRAM!{C_RESET}")
                    continue

                handled.add(key)

                if status == "no" and not default_on:
                    # Still ask, but warn
                    if ask_yn(f"    {feat['label']} {C_RED}(NOT RECOMMENDED: {reason}){C_RESET}?", default=False):
                        selected[key] = True
                        print(f"    {C_YELLOW}Warning: Overriding recommendation \u2014 this may not work!{C_RESET}")
                else:
                    selected[key] = ask_yn(f"    {feat['label']}?", default=default_on)

    # \u2500\u2500 Hardware profile summary \u2500\u2500
    installed_count = sum(1 for k in selected if selected[k] and k in locked_features)
    ok_count = sum(1 for k in selected if selected[k] and k not in locked_features and feature_compat.get(k, ("ok", ""))[0] == "ok")
    warn_count = sum(1 for k in selected if selected[k] and k not in locked_features and feature_compat.get(k, ("ok", ""))[0] == "warn")
    force_count = sum(1 for k in selected if selected[k] and k not in locked_features and feature_compat.get(k, ("ok", ""))[0] in ("no", "nogpu"))

    print(f"\n  {C_BOLD}Hardware Profile:{C_RESET}")
    print(f"    GPU: {getattr(args, '_gpu_name', 'Unknown')}")
    print(f"    VRAM: {vram_mb/1024:.0f} GB ({getattr(args, '_vram_tier', 'unknown')})")
    if installed_count:
        print(f"    {C_CYAN}{installed_count} feature(s) already installed on server{C_RESET}")
    print(f"    {C_GREEN}{ok_count} feature(s) fully compatible{C_RESET}")
    if warn_count:
        print(f"    {C_YELLOW}{warn_count} feature(s) may be slow{C_RESET}")
    if force_count:
        print(f"    {C_RED}{force_count} feature(s) force-selected despite VRAM limits{C_RESET}")

    # \u2500\u2500 Summary \u2500\u2500
    print(f"\n{C_BOLD}\u2500\u2500 Selected Features \u2500\u2500{C_RESET}\n")
    total_req = total_full = 0
    for k, feat in features.items():
        sel = selected.get(k, False)
        print_feature_summary(k, feat, sel)
        if sel:
            total_req += estimate_feature_size(feat, required_only=True)
            total_full += estimate_feature_size(feat)
        print()

    print(f"  {C_BOLD}Estimated download:{C_RESET} "
          f"{C_YELLOW}{fmt_size(total_req)}{C_RESET} required"
          + (f", up to {fmt_size(total_full)} with optionals" if total_full > total_req else ""))

    if not ask_yn("\n  Proceed with installation?", auto_yes=args.yes):
        print(f"\n{C_YELLOW}Installation cancelled.{C_RESET}")
        sys.exit(0)

    return selected


def step_install_nodes(manifest: dict, selected: dict[str, bool], paths: dict,
                       dry_run: bool = False, server_info: dict | None = None):
    """Step 4: Install required custom nodes."""
    if not paths["comfyui"]:
        print(f"\n  {C_YELLOW}Skipping custom node installation (no ComfyUI path).{C_RESET}")
        return

    if not shutil.which("git"):
        print(f"\n  {C_RED}Error: 'git' is not installed or not found in PATH.{C_RESET}")
        print(f"  {C_YELLOW}Custom nodes require git to clone. Skipping node installation.{C_RESET}")
        print(f"  {C_YELLOW}Install git from https://git-scm.com/ and re-run the installer.{C_RESET}\n")
        return

    if server_info is None:
        server_info = {}
    available_nodes = server_info.get('available_nodes', set())

    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  STEP 4: Install Custom Nodes{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    custom_nodes_dir = paths["comfyui"] / "custom_nodes"
    if not dry_run:
        custom_nodes_dir.mkdir(parents=True, exist_ok=True)

    # Collect the union of all custom nodes required by selected features
    needed_nodes: set[str] = set()
    for key, feat in manifest["features"].items():
        if selected.get(key, False):
            for node_name in feat.get("custom_nodes", []):
                needed_nodes.add(node_name)

    if not needed_nodes:
        print(f"  {C_GREEN}No custom nodes needed for selected features.{C_RESET}")
        return

    node_defs = manifest.get("custom_nodes", {})
    failed_nodes = []
    already_on_server = 0

    for node_name in sorted(needed_nodes):
        node_info = node_defs.get(node_name)
        if not node_info:
            print(f"  {C_YELLOW}⚠ Unknown node: {node_name}{C_RESET}")
            continue

        # Skip node packs whose provided class types are already on the server
        provides = node_info.get("provides", [])
        if provides and available_nodes and all(p in available_nodes for p in provides):
            print(f"  {C_CYAN}✓ Already on server:{C_RESET} {node_name}")
            already_on_server += 1
            continue

        dest = custom_nodes_dir / node_name
        success = git_clone(node_info["repo"], dest, dry_run)

        # Some nodes have a fork/mirror as fallback in case the primary repo is down
        if not success and "alt_repo" in node_info:
            print(f"  {C_YELLOW}Trying alternative repo…{C_RESET}")
            success = git_clone(node_info["alt_repo"], dest, dry_run)

        if success and not dry_run:
            install_node_requirements(dest, paths["comfyui"], dry_run)
        elif not success:
            failed_nodes.append(node_name)

        if "note" in node_info:
            print(f"  {C_DIM}Note: {node_info['note']}{C_RESET}")

    if already_on_server:
        print(f"\n  {C_CYAN}{already_on_server} node pack(s) already on server — skipped.{C_RESET}")

    if failed_nodes:
        print(f"\n  {C_RED}Failed to install nodes: {', '.join(failed_nodes)}{C_RESET}")
        print(f"  Install these manually into: {custom_nodes_dir}")

    # ComfyUI-Spellcaster is now a standard git-cloned repo (auto-updates via git pull)


def step_install_models(manifest: dict, selected: dict[str, bool], paths: dict,
                        args) -> None:
    """Step 5: Download and install models."""
    if not paths["comfyui"]:
        print(f"\n  {C_YELLOW}Skipping model installation (no ComfyUI path).{C_RESET}")
        return

    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  STEP 5: Download Models{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    if args.skip_models:
        print(f"  {C_YELLOW}--skip-models specified — skipping all model downloads.{C_RESET}")
        return

    # Ask about optional models once
    include_optional = True
    if not args.yes:
        include_optional = ask_yn(
            "  Download optional models too? (larger download, more variety)",
            default=False,
        )

    models_dir = paths["comfyui"] / "models"
    warnings: list[str] = []
    downloaded = skipped = already_present = failed = 0

    for feat_key, feat in manifest["features"].items():
        if not selected.get(feat_key, False):
            continue

        print(f"\n  {C_BOLD}── {feat['label']} ──{C_RESET}")
        models = collect_models_for_feature(feat)

        if not models:
            note = feat.get("models", {}).get("note", "")
            if note:
                print(f"  {C_DIM}{note}{C_RESET}")
            continue

        for model in models:
            is_optional = model.get("optional", False)
            if is_optional and not include_optional:
                skipped += 1
                continue

            # VRAM-aware model variant filtering: skip models that exceed the
            # user's VRAM capacity (e.g., skip the 9B model when user has 8 GB)
            model_vram_min = model.get("vram_min_gb", 0)
            user_vram_gb = getattr(args, '_vram_mb', 0) / 1024
            if model_vram_min > 0 and user_vram_gb > 0 and user_vram_gb < model_vram_min:
                rel_path = model["path"]
                note = model.get("note", "")
                print(f"  {C_YELLOW}\u2298 Skipping:{C_RESET} {rel_path}")
                print(f"    {C_DIM}Requires {model_vram_min} GB VRAM (you have {user_vram_gb:.0f} GB){C_RESET}")
                if note:
                    print(f"    {C_DIM}{note}{C_RESET}")
                skipped += 1
                continue

            # Model paths starting with "custom_nodes/" are placed relative to ComfyUI root
            # (e.g., insightface models inside a custom node dir); others go under models/
            rel_path = model["path"]
            if rel_path.startswith("custom_nodes/"):
                dest = paths["comfyui"] / rel_path
            else:
                dest = models_dir / rel_path

            if dest.exists() and not args.dry_run:
                print(f"  {C_GREEN}✓ Already present:{C_RESET} {rel_path}")
                already_present += 1
                continue

            url = model.get("url")
            note = model.get("note", "")

            civitai_key = getattr(args, 'civitai_key', '') or ''
            hf_token    = getattr(args, 'hf_token', '') or ''

            if url:
                success = download_file(url, dest, args.dry_run,
                                        civitai_key=civitai_key, hf_token=hf_token)
                if success:
                    downloaded += 1
                else:
                    failed += 1
                    warnings.append(
                        f"  {C_RED}✗{C_RESET} {C_BOLD}{rel_path}{C_RESET}\n"
                        f"    {note}\n"
                        f"    Failed to download from: {url}\n"
                        f"    {C_YELLOW}Install manually to:{C_RESET} {dest}"
                    )
            else:
                opt_tag = f" {C_DIM}(optional){C_RESET}" if is_optional else f" {C_RED}(REQUIRED){C_RESET}"
                page_url = model.get("page_url", "")
                page_line = (f"    {C_CYAN}Page:{C_RESET} {page_url}\n" if page_url else
                             f"    {C_YELLOW}Search CivitAI or HuggingFace for:{C_RESET} {dest.name}\n")
                warnings.append(
                    f"  {C_YELLOW}⚠{C_RESET} {C_BOLD}{rel_path}{C_RESET}{opt_tag}\n"
                    f"    {note}\n"
                    f"{page_line}"
                    f"    {C_YELLOW}Place the file at:{C_RESET} {dest}"
                )
                skipped += 1

    print(f"\n  {C_BOLD}── Model Summary ──{C_RESET}")
    print(f"  {C_GREEN}Downloaded:{C_RESET}      {downloaded}")
    print(f"  {C_GREEN}Already present:{C_RESET} {already_present}")
    if skipped:
        print(f"  {C_YELLOW}Skipped / manual:{C_RESET} {skipped}")
    if failed:
        print(f"  {C_RED}Failed:{C_RESET}          {failed}")

    if warnings:
        print(f"\n  {C_BOLD}{C_YELLOW}── Models Requiring Attention ──{C_RESET}\n")
        for w in warnings:
            print(w)
            print()


def _find_gimp_plugin_src() -> Path | None:
    """Search for the GIMP plugin source directory relative to the installer.

    Checks multiple possible layouts to handle both development trees and
    packaged distributions where the directory structure may differ.
    """
    search_dirs = [
        SCRIPT_DIR,
        SCRIPT_DIR / "plugins",
        SCRIPT_DIR / "plugins" / "gimp",
        SCRIPT_DIR / "plug-ins",
        SCRIPT_DIR.parent,
        SCRIPT_DIR.parent / "plugins" / "gimp",
    ]
    for d in search_dirs:
        candidate = d / "comfyui-connector" / "comfyui-connector.py"
        if candidate.exists():
            return candidate.parent
    return None


def _find_darktable_plugin_src() -> Path | None:
    """Search for the Darktable Lua plugin source file relative to the installer."""
    search_dirs = [
        SCRIPT_DIR,
        SCRIPT_DIR / "plugins",
        SCRIPT_DIR / "plugins" / "darktable",
        SCRIPT_DIR / "plug-ins",
        SCRIPT_DIR.parent,
        SCRIPT_DIR.parent / "plugins" / "darktable",
    ]
    for d in search_dirs:
        candidate = d / "comfyui_connector.lua"
        if candidate.exists():
            return candidate
    return None


def _find_spellcaster_core() -> Path | None:
    """Locate the spellcaster_core package directory.

    Searched in the comfyui-spellcaster folder relative to the installer
    or repo root.  Returns the directory path if found, else None.
    """
    search_roots = [
        SCRIPT_DIR.parent,           # repo root (installer/ is one level down)
        SCRIPT_DIR,                  # in case we're in the repo root
        SCRIPT_DIR.parent.parent,    # two levels up (dev layouts)
    ]
    for root in search_roots:
        candidate = root / "comfyui-spellcaster" / "spellcaster_core"
        if candidate.is_dir() and (candidate / "__init__.py").exists():
            return candidate
    return None


def step_install_plugins(paths: dict, server_url: str, dry_run: bool = False):
    """Step 6: Copy plugin files, patching the server URL."""
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  STEP 6: Install Plugins{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    gimp_src = _find_gimp_plugin_src()
    dt_src = _find_darktable_plugin_src()

    # ── GIMP ──
    # GIMP 3 plugin naming rule: the folder name MUST match the main script
    # name (minus .py).  So "comfyui-connector/comfyui-connector.py" is the
    # required layout inside plug-ins/.
    if paths["gimp"]:
        if gimp_src:
            # Ensure the plug-ins directory exists (may not on fresh installs)
            if not dry_run:
                paths["gimp"].mkdir(parents=True, exist_ok=True)

            dest = paths["gimp"] / gimp_src.name
            print(f"  {C_CYAN}Installing GIMP plugin…{C_RESET}")
            copy_plugin(gimp_src, dest, dry_run)

            # Bundle spellcaster_core alongside the plugin so the shim
            # imports resolve without needing the full repo tree.
            _core_src = _find_spellcaster_core()
            if _core_src and dest.is_dir():
                core_dest = dest / "spellcaster_core"
                copy_plugin(_core_src, core_dest, dry_run)

            if not dry_run:
                # GIMP plugin reads server URL from config.json at runtime,
                # so we write it there instead of patching the Python source
                config_path = dest / "config.json"
                if dest.is_dir():
                    try:
                        cfg = {"server_url": server_url}
                        config_path.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
                        print(f"  {C_GREEN}✓ Wrote server configuration to config.json{C_RESET}")
                    except OSError as e:
                        print(f"  {C_YELLOW}⚠ Failed to write config.json: {e}{C_RESET}")

                # On Unix, GIMP requires plugin scripts to be executable
                if os.name != "nt":
                    py_file = (dest / "comfyui-connector.py") if dest.is_dir() else dest
                    if py_file.exists():
                        py_file.chmod(0o755)

                # ── Post-install verification ──
                expected_script = dest / "comfyui-connector.py"
                if expected_script.exists():
                    print(f"  {C_GREEN}✓ Verified: {expected_script}{C_RESET}")
                    # Sanity check: folder name must match script name (GIMP 3 requirement)
                    if dest.name != "comfyui-connector":
                        print(f"  {C_RED}⚠ WARNING: Folder name '{dest.name}' does not match "
                              f"script name 'comfyui-connector.py'.{C_RESET}")
                        print(f"    GIMP 3 requires the folder name to match the script name.")
                        print(f"    Rename the folder to 'comfyui-connector' for GIMP to detect it.")
                else:
                    print(f"  {C_RED}⚠ Plugin script not found at expected location:{C_RESET}")
                    print(f"    {expected_script}")
                    print(f"    GIMP will not detect this plugin.")

            # Delete pluginrc cache so GIMP re-scans procedures on next start
            # Scans ALL GIMP versions (3.0, 3.2, etc.)
            _delete_gimp_pluginrc()

            # Install AI canvas size templates into GIMP's template list
            install_gimp_ai_templates(paths["gimp"], dry_run)

        else:
            print(f"  {C_YELLOW}⚠ GIMP plugin source not found.{C_RESET}")
            print(f"    Expected: plugins/gimp/comfyui-connector/comfyui-connector.py")
            print(f"    Copy manually to: {paths['gimp']}/comfyui-connector/")

    # ── Darktable ──
    if paths["darktable"]:
        if dt_src:
            dest = paths["darktable"] / dt_src.name
            print(f"  {C_CYAN}Installing Darktable plugin…{C_RESET}")

            # For Darktable, patch the URL in a temp copy so we don't modify the
            # installer's own source files (they may be read-only in a package)
            if not dry_run and server_url != DEFAULT_SERVER_URL:
                import tempfile, copy
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_file = Path(tmp) / dt_src.name
                    shutil.copy2(dt_src, tmp_file)
                    patch_plugin_server_url(tmp_file, server_url, dry_run)
                    copy_plugin(tmp_file, dest, dry_run)
            else:
                if server_url != DEFAULT_SERVER_URL:
                    print(f"  {C_DIM}[dry-run] Would patch server URL → {server_url}{C_RESET}")
                copy_plugin(dt_src, dest, dry_run)

            # Darktable requires a "luarc" file that lists all Lua modules to load.
            # Navigate up from lua/contrib/ to the darktable config root to find it.
            dt_config_dir = paths["darktable"].parent.parent
            luarc = dt_config_dir / "luarc"
            if not dry_run and luarc.exists():
                content = luarc.read_text(encoding="utf-8")
                if "comfyui_connector" not in content:
                    print(f"\n  {C_YELLOW}⚠ Add this line to your luarc file ({luarc}):{C_RESET}")
                    print(f'    {C_BOLD}require "contrib/comfyui_connector"{C_RESET}')
                else:
                    print(f"  {C_GREEN}✓ comfyui_connector already in luarc{C_RESET}")
            elif not dry_run:
                print(f"\n  {C_YELLOW}⚠ Create a luarc file at:{C_RESET} {dt_config_dir}/luarc")
                print(f'    Content: {C_BOLD}require "contrib/comfyui_connector"{C_RESET}')
        else:
            print(f"  {C_YELLOW}⚠ Darktable plugin source not found.{C_RESET}")
            print(f"    Expected: plugins/darktable/comfyui_connector.lua")
            print(f"    Copy manually to: {paths['darktable']}/")


def _find_gimp_system_splash() -> Path | None:
    """Locate the GIMP system-level splash image file on all platforms."""
    candidates: list[Path] = []
    if platform.system() == "Windows":
        for pf in [Path("C:/Program Files/GIMP 3"), Path("C:/Program Files (x86)/GIMP 3")]:
            for ver in ["3.2", "3.0"]:
                share = pf / f"share/gimp/{ver}/images"
                if share.is_dir():
                    for f in share.glob("gimp-splash*.png"):
                        candidates.append(f)
                    if not candidates:
                        candidates.append(share / "gimp-splash.png")
    elif platform.system() == "Darwin":
        for app_name in ["GIMP-3.2.app", "GIMP-3.0.app", "GIMP.app"]:
            for ver in ["3.2", "3.0"]:
                app = Path(f"/Applications/{app_name}/Contents/Resources/share/gimp/{ver}/images")
                if app.is_dir():
                    for f in app.glob("gimp-splash*.png"):
                        candidates.append(f)
                    if not candidates:
                        candidates.append(app / "gimp-splash.png")
    else:  # Linux
        for ver in ["3.2", "3.0"]:
            for base in [
                Path(f"/usr/share/gimp/{ver}/images"),
                Path(f"/usr/local/share/gimp/{ver}/images"),
                Path(f"/app/share/gimp/{ver}/images"),  # Flatpak
            ]:
                if base.is_dir():
                    for f in base.glob("gimp-splash*.png"):
                        candidates.append(f)
                    if not candidates:
                        candidates.append(base / "gimp-splash.png")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0] if candidates else None


def _find_gimp_system_icon(icon_name: str = "gimp-logo.png") -> Path | None:
    """Locate a GIMP system icon file (Wilber logo, window icon, etc.)."""
    search_dirs = []
    if platform.system() == "Windows":
        for pf in [Path("C:/Program Files/GIMP 3"), Path("C:/Program Files (x86)/GIMP 3")]:
            for ver in ["3.2", "3.0"]:
                search_dirs.append(pf / f"share/gimp/{ver}/images")
            search_dirs.append(pf / "share/icons/hicolor/256x256/apps")
            search_dirs.append(pf / "share/icons/hicolor/48x48/apps")
    elif platform.system() == "Darwin":
        for app_name in ["GIMP-3.2.app", "GIMP-3.0.app", "GIMP.app"]:
            for ver in ["3.2", "3.0"]:
                search_dirs.append(Path(f"/Applications/{app_name}/Contents/Resources/share/gimp/{ver}/images"))
    else:
        for ver in ["3.2", "3.0"]:
            search_dirs.append(Path(f"/usr/share/gimp/{ver}/images"))
        search_dirs.append(Path("/usr/share/icons/hicolor/256x256/apps"))
    for d in search_dirs:
        candidate = d / icon_name
        if candidate.exists():
            return candidate
    return None


def _find_darktable_system_splash() -> Path | None:
    """Locate the Darktable system-level splash image on all platforms."""
    candidates: list[Path] = []
    if platform.system() == "Windows":
        for pf in [Path("C:/Program Files/darktable"), Path("C:/Program Files (x86)/darktable")]:
            p = pf / "share/darktable/images"
            if p.is_dir():
                for f in p.glob("darktable-splash*"):
                    candidates.append(f)
                if not candidates:
                    candidates.append(p / "darktable-splash.jpg")
    elif platform.system() == "Darwin":
        app = Path("/Applications/darktable.app/Contents/Resources/share/darktable/images")
        if app.is_dir():
            for f in app.glob("darktable-splash*"):
                candidates.append(f)
            if not candidates:
                candidates.append(app / "darktable-splash.jpg")
    else:  # Linux
        for base in [
            Path("/usr/share/darktable/images"),
            Path("/usr/local/share/darktable/images"),
            Path("/app/share/darktable/images"),
        ]:
            if base.is_dir():
                for f in base.glob("darktable-splash*"):
                    candidates.append(f)
                if not candidates:
                    candidates.append(base / "darktable-splash.jpg")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0] if candidates else None



def _get_tavern_install_dir() -> Path:
    """Return the platform-specific Wizard Guild installation directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Spellcaster" / "tavern"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Spellcaster" / "tavern"
    else:
        return Path.home() / ".local" / "share" / "spellcaster" / "tavern"


def _find_tavern_src() -> Path | None:
    """Locate the tavern/ source directory relative to the installer."""
    candidates = [
        SCRIPT_DIR / "tavern",
        SCRIPT_DIR.parent / "tavern",
        SCRIPT_DIR / ".." / "tavern",
    ]
    for c in candidates:
        if c.is_dir() and (c / "server.py").exists():
            return c.resolve()
    return None


def _find_scaffold_src() -> Path | None:
    """Locate the scaffold/ source directory relative to the installer."""
    candidates = [
        SCRIPT_DIR / "scaffold",
        SCRIPT_DIR.parent / "scaffold",
        SCRIPT_DIR / ".." / "scaffold",
    ]
    for c in candidates:
        if c.is_dir() and (c / "__init__.py").exists():
            return c.resolve()
    return None


def _create_shortcut_windows(target_script: Path, shortcut_name: str,
                             shortcut_dir: Path, server_url: str,
                             icon_path: Path | None = None):
    """Create a Windows .lnk shortcut using PowerShell (no COM dependency)."""
    shortcut_path = shortcut_dir / f"{shortcut_name}.lnk"
    # Use PowerShell to create the shortcut — avoids win32com dependency
    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$s = $ws.CreateShortcut("{shortcut_path}"); '
        f'$s.TargetPath = "pythonw.exe"; '
        f'$s.Arguments = """{target_script}"" --comfyui {server_url}"; '
        f'$s.WorkingDirectory = "{target_script.parent}"; '
        f'$s.Description = "Launch Spellcaster Wizard Guild"; '
    )
    if icon_path and icon_path.exists():
        ps_script += f'$s.IconLocation = "{icon_path}"; '
    ps_script += '$s.Save()'
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=10
        )
        if shortcut_path.exists():
            return shortcut_path
    except Exception:
        pass
    # Fallback: create a .bat launcher if .lnk fails
    bat_path = shortcut_dir / f"{shortcut_name}.bat"
    bat_path.write_text(
        f'@echo off\r\npython "{target_script}" --comfyui {server_url} %*\r\n',
        encoding="utf-8"
    )
    return bat_path


def _create_shortcut_unix(target_script: Path, shortcut_name: str,
                          shortcut_dir: Path, server_url: str):
    """Create a .desktop file (Linux) or shell alias (macOS)."""
    if sys.platform == "darwin":
        # macOS: create a simple shell script in Applications
        app_path = shortcut_dir / f"{shortcut_name}.command"
        app_path.write_text(
            f'#!/bin/sh\ncd "{target_script.parent}"\n'
            f'python3 "{target_script}" --comfyui {server_url} "$@"\n',
            encoding="utf-8"
        )
        app_path.chmod(0o755)
        return app_path
    else:
        # Linux: .desktop file
        desktop_path = shortcut_dir / f"{shortcut_name.lower().replace(' ', '-')}.desktop"
        desktop_path.write_text(
            f'[Desktop Entry]\n'
            f'Type=Application\n'
            f'Name={shortcut_name}\n'
            f'Comment=Launch Spellcaster Wizard Guild\n'
            f'Exec=python3 "{target_script}" --comfyui {server_url}\n'
            f'Path={target_script.parent}\n'
            f'Terminal=true\n'
            f'Categories=Graphics;Utility;\n',
            encoding="utf-8"
        )
        desktop_path.chmod(0o755)
        return desktop_path


def step_install_tavern(paths: dict, server_url: str, llm_url: str, selected: dict,
                        dry_run: bool = False, auto_yes: bool = False):
    """Deploy the Wizard Guild standalone interface.

    Copies tavern/ and scaffold/ to a platform-specific application directory
    and writes a launcher config with the ComfyUI server URL.
    Asks the user for the install location and shortcut preferences.
    """
    if not selected.get("wizard_guild", False):
        return

    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  Install Wizard Guild{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    tavern_src = _find_tavern_src()
    scaffold_src = _find_scaffold_src()

    if not tavern_src:
        print(f"  {C_YELLOW}\u26a0 Tavern source directory not found, skipping.{C_RESET}")
        return

    # ── Ask install location ──────────────────────────────────────────
    default_dir = _get_tavern_install_dir()
    print(f"  {C_CYAN}Where should Wizard Guild be installed?{C_RESET}")
    print(f"  The app needs a writable directory for its files and settings.\n")
    print(f"  Default: {C_DIM}{default_dir}{C_RESET}\n")

    choice = ask_choice(
        "Install location:",
        [
            f"Default ({default_dir.parent})",
            "Choose a custom directory",
            "Install in current directory",
        ],
        default=0,
        auto_yes=auto_yes,
    )

    if choice == 0:
        dest = default_dir
    elif choice == 1:
        custom_base = ask_path(
            "Enter installation directory",
            must_exist=False,
            default=str(default_dir.parent),
            auto_yes=auto_yes,
        )
        dest = custom_base / "tavern"
    else:
        dest = Path.cwd() / "tavern"

    scaffold_dest = dest.parent / "scaffold"

    if dry_run:
        print(f"  [dry-run] Would install Wizard Guild to: {dest}")
        return

    # ── Copy files ────────────────────────────────────────────────────
    print(f"\n  {C_CYAN}Installing Wizard Guild to:{C_RESET} {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "static").mkdir(parents=True, exist_ok=True)

    copied = 0
    for item in tavern_src.rglob("*"):
        if item.is_file() and "__pycache__" not in str(item) and "build" not in item.parts:
            rel = item.relative_to(tavern_src)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied += 1
    print(f"  {C_GREEN}\u2713 Copied {copied} tavern files{C_RESET}")

    # Copy scaffold files
    if scaffold_src:
        scaffold_dest.mkdir(parents=True, exist_ok=True)
        sc_copied = 0
        for item in scaffold_src.rglob("*"):
            if item.is_file() and "__pycache__" not in str(item):
                rel = item.relative_to(scaffold_src)
                target = scaffold_dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                sc_copied += 1
        print(f"  {C_GREEN}\u2713 Copied {sc_copied} scaffold files{C_RESET}")

    # Write guild config with ComfyUI URL
    guild_config = dest / "guild_config.json"
    if not guild_config.exists():
        guild_config.write_text(json.dumps({
            "comfyui_url": server_url,
            "kobold_url": llm_url or "http://127.0.0.1:5001",
            "prompt_enhance": bool(llm_url),
            "auto_update": True,
        }, indent=2), encoding="utf-8")
        print(f"  {C_GREEN}\u2713 Wrote guild_config.json (ComfyUI: {server_url}){C_RESET}")
    else:
        print(f"  {C_GREEN}\u2713 guild_config.json preserved (existing){C_RESET}")

    # Set executable permissions on Unix
    if os.name != "nt":
        for py in dest.glob("*.py"):
            py.chmod(0o755)

    # Create convenience launcher script
    launcher_path = dest / "guild_launcher.py"
    if sys.platform == "win32":
        bat_path = dest.parent / "wizard-guild.bat"
        bat_path.write_text(
            f'@echo off\r\npython "{launcher_path}" --comfyui {server_url} %*\r\n',
            encoding="utf-8"
        )
        print(f"  {C_GREEN}\u2713 Created launcher: {bat_path}{C_RESET}")
    else:
        sh_path = dest.parent / "wizard-guild"
        sh_path.write_text(
            f'#!/bin/sh\npython3 "{launcher_path}" --comfyui {server_url} "$@"\n',
            encoding="utf-8"
        )
        sh_path.chmod(0o755)
        print(f"  {C_GREEN}\u2713 Created launcher: {sh_path}{C_RESET}")

    # ── Ask about shortcuts ───────────────────────────────────────────
    print()
    # Try to find an icon
    icon_path = dest / "static" / "favicon.ico"
    if not icon_path.exists():
        icon_path = None

    created_shortcuts = []

    # Desktop shortcut
    if ask_yn("Create a Desktop shortcut for Wizard Guild?", default=True,
              auto_yes=auto_yes):
        if sys.platform == "win32":
            desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
        elif sys.platform == "darwin":
            desktop = Path.home() / "Desktop"
        else:
            desktop = Path.home() / "Desktop"

        if desktop.is_dir():
            sc = (_create_shortcut_windows(launcher_path, "Wizard Guild",
                                           desktop, server_url, icon_path)
                  if sys.platform == "win32"
                  else _create_shortcut_unix(launcher_path, "Wizard Guild",
                                              desktop, server_url))
            if sc:
                print(f"  {C_GREEN}\u2713 Desktop shortcut: {sc}{C_RESET}")
                created_shortcuts.append(sc)
        else:
            print(f"  {C_YELLOW}\u26a0 Desktop directory not found ({desktop}), skipping.{C_RESET}")

    # Start Menu shortcut (Windows only)
    if sys.platform == "win32":
        if ask_yn("Add to Windows Start Menu?", default=True,
                  auto_yes=auto_yes):
            start_menu = (Path(os.environ.get("APPDATA", "")) /
                         "Microsoft" / "Windows" / "Start Menu" / "Programs" /
                         "Spellcaster")
            try:
                start_menu.mkdir(parents=True, exist_ok=True)
                sc = _create_shortcut_windows(launcher_path, "Wizard Guild",
                                              start_menu, server_url, icon_path)
                if sc:
                    print(f"  {C_GREEN}\u2713 Start Menu shortcut: {sc}{C_RESET}")
                    created_shortcuts.append(sc)
            except Exception as e:
                print(f"  {C_YELLOW}\u26a0 Start Menu shortcut failed: {e}{C_RESET}")

    # Linux: offer to add to ~/.local/share/applications
    elif sys.platform == "linux":
        apps_dir = Path.home() / ".local" / "share" / "applications"
        if ask_yn("Add to application menu?", default=True,
                  auto_yes=auto_yes):
            try:
                apps_dir.mkdir(parents=True, exist_ok=True)
                sc = _create_shortcut_unix(launcher_path, "Wizard Guild",
                                           apps_dir, server_url)
                if sc:
                    print(f"  {C_GREEN}\u2713 App menu entry: {sc}{C_RESET}")
                    created_shortcuts.append(sc)
            except Exception as e:
                print(f"  {C_YELLOW}\u26a0 App menu entry failed: {e}{C_RESET}")

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n  {C_BOLD}Wizard Guild installed!{C_RESET}")
    print(f"  {C_DIM}Location: {dest}{C_RESET}")
    if created_shortcuts:
        print(f"  {C_DIM}Shortcuts: {len(created_shortcuts)} created{C_RESET}")
    print(f"\n  {C_BOLD}To start:{C_RESET}")
    print(f"    python \"{launcher_path}\"")
    if created_shortcuts:
        print(f"    or double-click the Desktop/Start Menu shortcut")

def step_apply_theme(paths: dict, dry_run: bool = False, auto_yes: bool = False) -> None:
    """Optional step: replace the GIMP/Darktable system splash with Spellcaster artwork.

    Requires write access to the application's installation directory.
    On Windows this means running the installer as Administrator.
    Automatically creates a .orig backup of the original file.
    """
    if not (paths.get("gimp") or paths.get("darktable")):
        return

    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  STEP 7 (Optional): Apply Spellcaster Visual Theme{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")
    print(f"  Replaces the GIMP and/or Darktable default splash screen")
    print(f"  with Spellcaster-themed AI-generated artwork.\n")
    if platform.system() == "Windows":
        print(f"  {C_YELLOW}⚠  Requires Administrator rights on Windows.{C_RESET}")
        print(f"  {C_DIM}   (Re-run the installer as Administrator if this fails.){C_RESET}\n")
    elif platform.system() != "Darwin":
        print(f"  {C_YELLOW}⚠  May require sudo on Linux (writes to /usr/share/).{C_RESET}\n")

    if not ask_yn("  Apply Spellcaster visual theme?", default=False, auto_yes=auto_yes):
        print(f"  {C_DIM}Skipped.{C_RESET}")
        return

    def _try_replace(src: Path, dest: Path, label: str):
        print(f"  {C_CYAN}Replacing {label} splash:{C_RESET}")
        print(f"    {C_DIM}Source: {src}{C_RESET}")
        print(f"    {C_DIM}Target: {dest}{C_RESET}")
        if dry_run:
            print(f"  {C_DIM}[dry-run] Would copy.{C_RESET}")
            return
        try:
            backup = dest.with_suffix(".orig" + dest.suffix)
            if not backup.exists():
                shutil.copy2(dest, backup)
                print(f"  {C_DIM}  Backed up original → {backup.name}{C_RESET}")
            shutil.copy2(src, dest)
            print(f"  {C_GREEN}✓ {label} splash replaced{C_RESET}")
        except PermissionError:
            print(f"  {C_RED}✗ Permission denied — run the installer as Administrator{C_RESET}")
        except OSError as e:
            print(f"  {C_RED}✗ Failed: {e}{C_RESET}")

    # ── GIMP ──
    if paths.get("gimp"):
        gimp_splash_dest = _find_gimp_system_splash()
        gimp_src_dir = _find_gimp_plugin_src()
        if gimp_src_dir:
            # gimp_banner.png lives one level up from the plugin dir
            # i.e. plugins/gimp/gimp_banner.png
            gimp_banner = gimp_src_dir.parent / "gimp_banner.png"
        else:
            gimp_banner = SCRIPT_DIR / "plugins" / "gimp" / "gimp_banner.png"

        if not gimp_banner.exists():
            print(f"  {C_YELLOW}⚠ Spellcaster GIMP banner not found ({gimp_banner}).{C_RESET}")
            print(f"    Run: python generate_showcase.py --only splash")
        elif not gimp_splash_dest:
            print(f"  {C_YELLOW}⚠ GIMP system splash location not found — may need manual replacement.{C_RESET}")
        else:
            _try_replace(gimp_banner, gimp_splash_dest, "GIMP")

    # ── Darktable ──
    if paths.get("darktable"):
        dt_splash_dest = _find_darktable_system_splash()
        dt_src = _find_darktable_plugin_src()
        if dt_src:
            dt_splash = dt_src.parent / "darktable_splash.jpg"
        else:
            dt_splash = SCRIPT_DIR / "plugins" / "darktable" / "darktable_splash.jpg"

        if not dt_splash.exists():
            print(f"  {C_YELLOW}⚠ Spellcaster Darktable splash not found ({dt_splash}).{C_RESET}")
            print(f"    Run: python generate_showcase.py --only splash")
        elif not dt_splash_dest:
            print(f"  {C_YELLOW}⚠ Darktable system splash location not found — may need manual replacement.{C_RESET}")
        else:
            _try_replace(dt_splash, dt_splash_dest, "Darktable")


def step_import_luts(paths: dict, args) -> None:
    """Optional step: copy .cube/.3dl LUT files into ComfyUI's models/luts/ directory.

    Scans the provided folder recursively and copies all recognised LUT files.
    Already-present files (same name) are skipped to avoid overwriting custom edits.
    """
    if not paths.get("comfyui"):
        lut_folder_arg = getattr(args, 'lut_folder', '') or ''
        if lut_folder_arg:
            print(f"  {C_YELLOW}⚠ --lut-folder specified but no ComfyUI path — skipping.{C_RESET}")
        return

    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  STEP 6b (Optional): Import LUT Files{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")
    print(f"  {C_DIM}Import .cube / .3dl LUT files from Davinci Resolve, Lightroom,")
    print(f"  or any other tool. They will appear immediately in the Spellcaster")
    print(f"  Color Grading preset picker as soon as ComfyUI starts.{C_RESET}\n")

    # Determine source folder
    lut_folder: Path | None = None
    lut_folder_arg = getattr(args, 'lut_folder', '') or ''

    if lut_folder_arg:
        p = Path(lut_folder_arg).expanduser().resolve()
        if p.is_dir():
            lut_folder = p
            print(f"  {C_GREEN}LUT source (from --lut-folder):{C_RESET} {lut_folder}")
        else:
            print(f"  {C_RED}--lut-folder path not found: {p}{C_RESET}")
            return
    elif not args.yes:
        if not ask_yn("  Import LUT files from an existing folder?", default=False):
            print(f"  {C_DIM}Skipped.{C_RESET}")
            return
        lut_folder = ask_path("  LUT source folder", must_exist=True)
    else:
        # Auto mode without --lut-folder: skip silently
        print(f"  {C_DIM}Skipped (use --lut-folder PATH to import LUTs automatically).{C_RESET}")
        return

    if not lut_folder:
        return

    # Scan recursively for supported LUT formats
    lut_exts = {".cube", ".3dl", ".lut", ".als", ".clf"}
    found: list[Path] = []
    for ext in lut_exts:
        found.extend(lut_folder.rglob(f"*{ext}"))
        found.extend(lut_folder.rglob(f"*{ext.upper()}"))
    found = sorted(set(found))

    if not found:
        print(f"  {C_YELLOW}⚠ No LUT files found in {lut_folder}{C_RESET}")
        print(f"  {C_DIM}Supported extensions: {', '.join(sorted(lut_exts))}{C_RESET}")
        return

    print(f"  {C_GREEN}Found {len(found)} LUT file(s):{C_RESET}")
    for f in found[:8]:
        print(f"    {C_DIM}{f.name}{C_RESET}")
    if len(found) > 8:
        print(f"    {C_DIM}... and {len(found) - 8} more{C_RESET}")
    print()

    luts_dir = paths["comfyui"] / "models" / "luts"

    if args.dry_run:
        print(f"  {C_DIM}[dry-run] Would copy {len(found)} LUT(s) → {luts_dir}{C_RESET}")
        return

    luts_dir.mkdir(parents=True, exist_ok=True)
    copied = skipped = failed = 0

    for lut in found:
        dest = luts_dir / lut.name
        if dest.exists():
            skipped += 1
            continue
        try:
            shutil.copy2(lut, dest)
            copied += 1
        except OSError as e:
            print(f"  {C_RED}✗ Failed to copy {lut.name}: {e}{C_RESET}")
            failed += 1

    print(f"  {C_GREEN}✓ Imported: {copied}{C_RESET}  |  "
          f"Already present: {skipped}  |  Failed: {failed}")
    print(f"  {C_DIM}  LUT directory: {luts_dir}{C_RESET}")


def step_final_summary(manifest: dict, selected: dict[str, bool], paths: dict, server_url: str):
    """Step 7: Print final summary."""
    print(f"\n{C_BOLD}{_BOX_LINE}{C_RESET}")
    print(f"{C_BOLD}  INSTALLATION COMPLETE{C_RESET}")
    print(f"{C_BOLD}{_BOX_LINE}{C_RESET}\n")

    print(f"  {C_BOLD}Installed features:{C_RESET}")
    for key, feat in manifest["features"].items():
        if selected.get(key, False):
            print(f"    {C_GREEN}✓{C_RESET} {feat['label']}")

    print(f"\n  {C_BOLD}Application paths:{C_RESET}")
    if paths["comfyui"]:
        print(f"    ComfyUI:   {paths['comfyui']}")
    if paths["gimp"]:
        print(f"    GIMP:      {paths['gimp']}")
    if paths["darktable"]:
        print(f"    Darktable: {paths['darktable']}")

    print(f"\n  {C_BOLD}ComfyUI server:{C_RESET} {server_url}")

    print(f"\n  {C_BOLD}Next steps:{C_RESET}")
    print(f"    1. Start ComfyUI on {server_url}")
    if paths["gimp"]:
        print(f"    2. Open GIMP 3 → Filters → Spellcaster to access features")
    if paths["darktable"]:
        print(f"    3. Open Darktable — the Spellcaster panel appears in the lighttable module")
    print(f"    4. On first launch, verify the server URL in the plugin dialog")
    if selected.get("wizard_guild", False):
        tavern_dir = _get_tavern_install_dir()
        print(f"    5. Start the Wizard Guild: python {tavern_dir / 'guild_launcher.py'}")
        print(f"       The launcher will walk you through connecting to your LLM.")
        print(f"       Don't have an LLM? Download KoboldCPP (single .exe, no install):")
        print(f"       https://github.com/LostRuins/koboldcpp/releases")

    print(f"\n  {C_BOLD}Troubleshooting:{C_RESET}")
    print(f"    • 'Node not found' — install the missing custom node into ComfyUI")
    print(f"    • 'Cannot connect' — check ComfyUI is running and the URL is correct")
    print(f"    • Missing model — see warnings above for exact install paths")
    print(f"    • Report issues: https://github.com/laboratoiresonore/spellcaster/issues")
    print()


# ─── Entry point ───────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    """Load the manifest.json that defines all features, models, and custom nodes."""
    if not MANIFEST_PATH.exists():
        print(f"{C_RED}Error: manifest.json not found at {MANIFEST_PATH}{C_RESET}")
        sys.exit(1)
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_arg_parser():
    """Build the argparse parser with all CLI flags."""
    parser = argparse.ArgumentParser(
        description="Spellcaster \u2014 AI superpowers for GIMP 3 & Darktable",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python install.py
              python install.py --cli --yes
              python install.py --server-url http://<SERVER-IP>:8188
              python install.py --features img2img,inpaint,face_swap_reactor
              python install.py --comfyui ~/ComfyUI --gimp ~/.config/GIMP/3.2/plug-ins
              python install.py --dry-run
        """)
    )
    parser.add_argument("--cli", action="store_true",
                        help="Force terminal mode (skip GUI wrapper)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be done without making changes")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Auto-accept all defaults (non-interactive)")
    parser.add_argument("--server-url", metavar="URL",
                        help=f"ComfyUI server URL (default: {DEFAULT_SERVER_URL})")
    parser.add_argument("--features", metavar="FEAT1,FEAT2",
                        help="Comma-separated list of features to install. "
                             "Available: img2img, txt2img, inpaint, face_swap_reactor, "
                             "face_swap_mtb, faceid_img2img, pulid_flux, klein_flux2, "
                             "wan_i2v, rembg, upscale, lama_remove, lut_grading, "
                             "outpaint, style_transfer, face_restore, photo_restore, "
                             "detail_hallucinate, colorize, controlnet, iclight, supir, "
                             "batch_variations, seedv2r, wizard_guild")
    parser.add_argument("--comfyui", metavar="PATH",
                        help="Path to ComfyUI root directory")
    parser.add_argument("--gimp", metavar="PATH",
                        help="Path to GIMP 3 plug-ins directory")
    parser.add_argument("--darktable", metavar="PATH",
                        help="Path to Darktable lua/contrib directory")
    parser.add_argument("--lut-folder", metavar="PATH", default="",
                        help="Source folder containing .cube/.3dl LUT files to import into ComfyUI")
    parser.add_argument("--civitai-key", metavar="TOKEN", default="",
                        help="CivitAI API token for authenticated model downloads")
    parser.add_argument("--hf-token", metavar="TOKEN", default="",
                        help="HuggingFace access token for gated model downloads")
    parser.add_argument("--skip-models", action="store_true",
                        help="Skip model downloads (install plugins and nodes only)")
    parser.add_argument("--skip-nodes", action="store_true",
                        help="Skip custom node installation")
    parser.add_argument("--llm-url", default="",
                        help="Local LLM server URL (KoboldCpp/Ollama). Empty = skip prompt enhancement")
    parser.add_argument("--version", action="version",
                        version=f"Spellcaster Installer v{VERSION}")
    return parser


def main():
    """Run the full CLI installation pipeline."""
    args = build_arg_parser().parse_args()

    banner()

    if args.dry_run:
        print(f"  {C_YELLOW}DRY RUN MODE \u2014 no changes will be made{C_RESET}\n")

    manifest = load_manifest()

    if not hasattr(args, 'civitai_key'):
        args.civitai_key = getattr(args, 'civitai_key', '') or ''
    if not hasattr(args, 'hf_token'):
        args.hf_token = getattr(args, 'hf_token', '') or ''
    if not hasattr(args, 'llm_url'):
        args.llm_url = getattr(args, 'llm_url', '') or ''

    # \u2500\u2500 Execute the installation pipeline \u2500\u2500
    step_system_detection(args)
    step_api_keys(args)
    server_url = step_detect_server(args)
    paths = step_detect_paths(args)
    server_info = step_probe_server(server_url, args)
    llm_url = step_detect_llm_server(args, server_url, server_info)
    selected = step_select_features(manifest, paths, args, server_info)

    if not args.skip_nodes:
        step_install_nodes(manifest, selected, paths, args.dry_run, server_info)
    else:
        print(f"\n  {C_YELLOW}--skip-nodes specified \u2014 skipping custom node installation.{C_RESET}")

    step_install_models(manifest, selected, paths, args)
    settings = _write_shared_settings(paths, server_url, llm_url, server_info, args.dry_run)
    step_install_plugins(paths, server_url, args.dry_run)
    step_install_tavern(paths, server_url, llm_url, selected, args.dry_run, args.yes)
    step_import_luts(paths, args)
    step_apply_theme(paths, args.dry_run, args.yes)
    step_final_summary(manifest, selected, paths, server_url)


# \u2500\u2500\u2500 GUI wrapper \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

if __name__ == "__main__":
    _args = build_arg_parser().parse_args()
    _is_frozen_gui = getattr(sys, 'frozen', False) and not sys.stdin
    _force_cli = getattr(_args, 'cli', False)
    if _force_cli and sys.stdin:
        main()
    elif _is_frozen_gui or (not _force_cli and sys.stdin and sys.stdin.isatty()):
        try:
            from installer_gui import run_gui
            run_gui(_args, load_manifest())
        except Exception as e:
            if sys.stdin:
                import traceback
                print(f"Failed to load premium GUI: {e}")
                traceback.print_exc()
                main()
            else:
                raise
    else:
        main()
