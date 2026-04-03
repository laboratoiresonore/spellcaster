#!/usr/bin/env python3
"""
Spellcaster Manual Update & Repair Tool
========================================
Finds existing Spellcaster plugin installations (correct or broken),
repairs misnamed folders, and updates plugin files to the latest version
from GitHub.

Run this if:
  - The plugin doesn't appear in GIMP's Filters menu
  - You want to update to the latest version without re-running the installer
  - The installer put files in the wrong location

Usage:
    manual_update.exe           (standalone — double-click)
    python manual_update.py     (from source)
"""

from __future__ import annotations

import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.0"
GITHUB_RAW = "https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main"
GITHUB_API = "https://api.github.com/repos/laboratoiresonore/spellcaster/commits?sha=main&per_page=1"
GITHUB_TREE = "https://api.github.com/repos/laboratoiresonore/spellcaster/git/trees/main?recursive=1"

# Prefixes for dynamic file discovery via GitHub Tree API
GIMP_PLUGIN_PREFIX = "plugins/gimp/comfyui-connector/"
DARKTABLE_PLUGIN_PREFIX = "plugins/darktable/"

# Static fallback lists (used when Tree API is unavailable)
GIMP_PLUGIN_FILES = [
    "plugins/gimp/comfyui-connector/comfyui-connector.py",
    "plugins/gimp/comfyui-connector/spellcaster_steg.py",
    "plugins/gimp/comfyui-connector/spellcaster-theme.css",
    "plugins/gimp/comfyui-connector/gimp_banner.png",
    "plugins/gimp/comfyui-connector/installer_background.png",
]

DARKTABLE_PLUGIN_FILES = [
    "plugins/darktable/comfyui_connector.lua",
    "plugins/darktable/spellcaster_steg.py",
    "plugins/darktable/spellcaster-darktable.css",
    "plugins/darktable/splash.py",
    "plugins/darktable/darktable_splash.jpg",
    "plugins/darktable/installer_background.png",
]

# ANSI colors
if sys.stdout and sys.stdout.isatty() and (os.name != "nt" or os.environ.get("WT_SESSION")):
    B = "\033[1m"; G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
    C = "\033[96m"; D = "\033[2m"; X = "\033[0m"
else:
    B = G = Y = R = C = D = X = ""


def discover_remote_files(prefix: str) -> list[str]:
    """Dynamically discover all files under *prefix* in the repo via GitHub Tree API.

    Returns a list of full repo-relative paths (e.g. "plugins/darktable/splash.py").
    Falls back to None if the API is unavailable so callers can use static lists.
    """
    try:
        req = urllib.request.Request(GITHUB_TREE, headers={"User-Agent": "spellcaster-updater/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            tree = json.loads(resp.read())
        files = []
        for item in tree.get("tree", []):
            if item["type"] == "blob" and item["path"].startswith(prefix):
                # Only include top-level files (skip subdirectory files)
                remainder = item["path"][len(prefix):]
                if "/" not in remainder:
                    files.append(item["path"])
        return files if files else None
    except Exception:
        return None


def banner():
    print(f"""
{B}{C}╔══════════════════════════════════════════════════╗
║    ✦  SPELLCASTER UPDATE & REPAIR  v{VERSION}  ✦    ║
║    Every preset expertly tuned for instant results  ║
╚══════════════════════════════════════════════════╝{X}
""")


# ─── GIMP path detection (aggressive — tries everything) ────────────────────

def _ask_gimp_for_plugin_dirs() -> list[Path]:
    """Ask GIMP directly where its plug-in directories are via Script-Fu."""
    results = []
    gimp_bins = []

    # Find GIMP binary
    if platform.system() == "Windows":
        # Check common Windows install locations
        for prog in [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
                     os.environ.get("LocalAppData", "")]:
            if not prog:
                continue
            for pattern in [f"{prog}\\GIMP*\\bin\\gimp-*.exe",
                            f"{prog}\\GIMP*\\bin\\gimp.exe"]:
                gimp_bins.extend(glob.glob(pattern))
        # Also check PATH
        gimp_path = shutil.which("gimp")
        if gimp_path:
            gimp_bins.append(gimp_path)
    else:
        for name in ["gimp-3.0", "gimp-2.99", "gimp3", "gimp"]:
            p = shutil.which(name)
            if p:
                gimp_bins.append(p)
        # Flatpak
        if shutil.which("flatpak"):
            try:
                r = subprocess.run(["flatpak", "list", "--app", "--columns=application"],
                                   capture_output=True, text=True, timeout=5)
                if "org.gimp.GIMP" in r.stdout:
                    gimp_bins.append("flatpak:org.gimp.GIMP")
            except Exception:
                pass

    # Try to run GIMP in batch mode to get plug-in dirs
    for gimp_bin in gimp_bins[:1]:  # Only try the first one found
        if gimp_bin.startswith("flatpak:"):
            continue  # Can't easily batch-query flatpak GIMP
        try:
            r = subprocess.run(
                [gimp_bin, "--version"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                print(f"  {G}Found GIMP:{X} {gimp_bin}")
                print(f"    {r.stdout.strip()}")
        except Exception:
            pass

    return results


def find_all_gimp_plugin_dirs() -> list[Path]:
    """Find ALL possible GIMP 3 plug-in directories on this system.

    Uses multiple strategies:
    1. Scan known config root directories for version folders
    2. Search for GIMP installations and infer config paths
    3. Brute-force glob for any GIMP directory with plug-ins
    """
    home = Path.home()
    results: list[Path] = []
    seen: set[str] = set()

    def add(p: Path):
        s = str(p)
        if s not in seen:
            seen.add(s)
            results.append(p)

    def scan_gimp_root(root: Path):
        """Scan a GIMP config root for any version directories."""
        if not root.is_dir():
            return
        for d in sorted(root.iterdir(), reverse=True):
            if d.is_dir() and re.match(r"^(3\.|2\.99)", d.name):
                add(d / "plug-ins")

    # ── Strategy 1: Known config roots ──
    if platform.system() == "Windows":
        scan_gimp_root(home / "AppData" / "Roaming" / "GIMP")
        # Some Windows installs use Local instead of Roaming
        scan_gimp_root(home / "AppData" / "Local" / "GIMP")
    elif platform.system() == "Darwin":
        scan_gimp_root(home / "Library" / "Application Support" / "GIMP")
        scan_gimp_root(home / "Library" / "GIMP")
        scan_gimp_root(home / ".config" / "GIMP")
    else:
        scan_gimp_root(home / ".config" / "GIMP")
        # Flatpak
        scan_gimp_root(home / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP")
        # Snap
        snap_base = home / "snap" / "gimp"
        if snap_base.is_dir():
            for snap_rev in sorted(snap_base.iterdir(), reverse=True):
                scan_gimp_root(snap_rev / ".config" / "GIMP")

    # ── Strategy 2: Hardcoded common paths ──
    if platform.system() == "Windows":
        add(home / "AppData" / "Roaming" / "GIMP" / "3.0" / "plug-ins")
        add(home / "AppData" / "Roaming" / "GIMP" / "2.99" / "plug-ins")
    elif platform.system() == "Darwin":
        add(home / "Library" / "Application Support" / "GIMP" / "3.0" / "plug-ins")
        add(home / ".config" / "GIMP" / "3.0" / "plug-ins")
    else:
        add(home / ".config" / "GIMP" / "3.0" / "plug-ins")
        add(home / ".config" / "GIMP" / "2.99" / "plug-ins")
        add(home / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP" / "3.0" / "plug-ins")

    # ── Strategy 3: Brute-force search for GIMP directories ──
    if platform.system() == "Windows":
        # Search all drives for GIMP config
        for drive in ["C:", "D:", "E:"]:
            gimp_glob = f"{drive}\\Users\\*\\AppData\\Roaming\\GIMP\\3.*\\plug-ins"
            for p in glob.glob(gimp_glob):
                add(Path(p))

    return results


def find_all_darktable_dirs() -> list[Path]:
    """Find ALL possible Darktable lua/contrib directories."""
    home = Path.home()
    results: list[Path] = []

    if platform.system() == "Windows":
        candidates = [
            home / "AppData" / "Local" / "darktable" / "lua" / "contrib",
            home / ".config" / "darktable" / "lua" / "contrib",
        ]
    elif platform.system() == "Darwin":
        candidates = [
            home / "Library" / "Application Support" / "darktable" / "lua" / "contrib",
            home / ".config" / "darktable" / "lua" / "contrib",
        ]
    else:
        candidates = [
            home / ".config" / "darktable" / "lua" / "contrib",
        ]

    for c in candidates:
        if c.is_dir():
            results.append(c)
    return results


# ─── Scan for existing installations ────────────────────────────────────────

def deep_scan_for_spellcaster(search_roots: list[Path]) -> list[dict]:
    """Recursively scan for any comfyui-connector.py file under given roots."""
    found = []
    for root in search_roots:
        if not root.is_dir():
            continue
        # Walk up to 3 levels deep
        for depth1 in root.iterdir():
            if depth1.is_file() and depth1.name == "comfyui-connector.py":
                found.append({"path": depth1, "plug_dir": root, "location": str(depth1)})
            if depth1.is_dir():
                for depth2 in depth1.iterdir():
                    if depth2.is_file() and depth2.name == "comfyui-connector.py":
                        found.append({"path": depth2, "plug_dir": root, "location": str(depth2)})
                    if depth2.is_dir():
                        for depth3 in depth2.iterdir():
                            if depth3.is_file() and depth3.name == "comfyui-connector.py":
                                found.append({"path": depth3, "plug_dir": root, "location": str(depth3)})
    return found


def fix_gimprc_plugin_path(gimp_config_dir: Path) -> bool:
    """Fix gimprc to include the user plug-ins directory in plug-in-path.

    Some GIMP installations have a misconfigured plug-in-path that points to
    'plug-ins\\modules' instead of 'plug-ins', which means GIMP never scans
    the user plug-ins directory where we install Spellcaster.

    Also deletes the pluginrc cache to force a full rescan on next launch.
    """
    gimprc = gimp_config_dir / "gimprc"
    pluginrc = gimp_config_dir / "pluginrc"
    fixed_something = False

    if gimprc.exists():
        try:
            content = gimprc.read_text(encoding="utf-8")

            # Check if plug-in-path is misconfigured
            # Common broken pattern: plug-ins\modules or plug-ins/modules
            if "plug-ins\\modules" in content or "plug-ins/modules" in content:
                print(f"  {Y}Found misconfigured plug-in-path in gimprc{X}")
                print(f"    {D}Path points to 'plug-ins/modules' instead of 'plug-ins'{X}")

                # Fix: replace plug-ins\modules or plug-ins/modules with plug-ins
                new_content = content.replace("plug-ins\\\\modules", "plug-ins")
                new_content = new_content.replace("plug-ins\\modules", "plug-ins")
                new_content = new_content.replace("plug-ins/modules", "plug-ins")

                if new_content != content:
                    gimprc.write_text(new_content, encoding="utf-8")
                    print(f"  {G}✓ Fixed gimprc plug-in-path{X}")
                    fixed_something = True

            # Check if user plug-ins dir is in the path at all
            if "plug-in-path" in content:
                # Look for ${gimp_dir} reference (the user config dir)
                if "${gimp_dir}" not in content and "gimp_dir" not in content:
                    print(f"  {Y}gimprc plug-in-path may not include user directory{X}")
                    print(f"    {D}Check: {gimprc}{X}")
            else:
                print(f"  {D}No plug-in-path in gimprc (using GIMP defaults — should be OK){X}")

        except Exception as e:
            print(f"  {R}Error reading gimprc: {e}{X}")
    else:
        print(f"  {D}No gimprc file (GIMP using defaults — should be OK){X}")

    # Delete pluginrc cache to force full rescan
    if pluginrc.exists():
        try:
            pluginrc.unlink()
            print(f"  {G}✓ Deleted pluginrc cache (GIMP will do full plugin scan on restart){X}")
            fixed_something = True
        except Exception as e:
            print(f"  {Y}Could not delete pluginrc: {e}{X}")
            print(f"    {D}Delete manually: {pluginrc}{X}")

    return fixed_something


def diagnose_gimp_install(plug_dir: Path) -> list[str]:
    """Diagnose why a plugin might not be visible in GIMP."""
    issues = []
    plugin_dir = plug_dir / "comfyui-connector"
    script = plugin_dir / "comfyui-connector.py"

    if not plug_dir.exists():
        issues.append(f"plug-ins directory does not exist: {plug_dir}")
        issues.append("  -> GIMP may not have been launched yet (it creates this on first run)")
        return issues

    if not plugin_dir.exists():
        issues.append(f"Plugin folder missing: {plugin_dir}")
        # Check for wrong names
        for sub in plug_dir.iterdir():
            if sub.is_dir() and (sub / "comfyui-connector.py").exists():
                issues.append(f"  -> Found in WRONG folder: {sub.name}/ (GIMP requires 'comfyui-connector/')")
        if (plug_dir / "comfyui-connector.py").exists():
            issues.append(f"  -> Script is loose in plug-ins/ (needs 'comfyui-connector/' subfolder)")
        return issues

    if not script.exists():
        issues.append(f"Script file missing: {script}")
        return issues

    # Check file size (corrupt download?)
    size = script.stat().st_size
    if size < 1000:
        issues.append(f"Script file suspiciously small ({size} bytes) — may be corrupt")

    # Check executable permission on Unix
    if os.name != "nt":
        if not os.access(str(script), os.X_OK):
            issues.append(f"Script is not executable (GIMP requires +x on Unix)")

    # Check for __pycache__ (indicates GIMP has tried to load it before)
    if (plugin_dir / "__pycache__").exists():
        issues.append("__pycache__ exists — GIMP has loaded this before (try restarting GIMP)")

    # Check shebang line
    try:
        with open(script, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if not first_line.startswith("#!"):
            issues.append(f"Missing shebang line (first line: '{first_line[:50]}')")
    except Exception as e:
        issues.append(f"Cannot read script: {e}")

    return issues


# ─── Download from GitHub ───────────────────────────────────────────────────

def download_file(url: str, dest: Path) -> bool:
    """Download a single file from GitHub."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "spellcaster-updater/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
        return True
    except (urllib.error.URLError, OSError) as e:
        print(f"  {R}Failed to download {dest.name}: {e}{X}")
        return False


def get_latest_sha() -> str:
    """Get the latest commit SHA from GitHub."""
    try:
        req = urllib.request.Request(GITHUB_API, headers={"User-Agent": "spellcaster-updater/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data[0]["sha"][:7]
    except Exception:
        return "unknown"


def _ask_yn(prompt, default=True):
    """Ask a yes/no question. Returns bool."""
    hint = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"  {B}{prompt} {hint}:{X} ").strip().lower()
    except (RuntimeError, EOFError):
        return default
    if not raw:
        return default
    return raw[0] == "y"


def _install_gimp_css_theme(gimp_plug_dir: Path):
    """Install the Spellcaster GTK3 CSS theme into GIMP's user theme directory.

    Copies spellcaster-theme.css to:
      - Windows: %APPDATA%/GIMP/3.0/themes/Spellcaster/gtk.css
      - macOS:   ~/Library/Application Support/GIMP/3.0/themes/Spellcaster/gtk.css
      - Linux:   ~/.config/GIMP/3.0/themes/Spellcaster/gtk.css
    """
    import shutil

    connector_dir = gimp_plug_dir / "comfyui-connector"
    css_src = connector_dir / "spellcaster-theme.css"

    # Download CSS if not present locally
    if not css_src.exists():
        css_url = f"{GITHUB_RAW}/plugins/gimp/comfyui-connector/spellcaster-theme.css"
        download_file(css_url, css_src)

    if not css_src.exists():
        print(f"  {Y}spellcaster-theme.css not available{X}")
        return

    # Determine GIMP user theme directory
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            theme_dir = Path(appdata) / "GIMP" / "3.0" / "themes" / "Spellcaster"
        else:
            print(f"  {Y}Cannot determine APPDATA for GIMP theme install{X}")
            return
    elif platform.system() == "Darwin":
        theme_dir = Path.home() / "Library" / "Application Support" / "GIMP" / "3.0" / "themes" / "Spellcaster"
    else:
        theme_dir = Path.home() / ".config" / "GIMP" / "3.0" / "themes" / "Spellcaster"

    try:
        theme_dir.mkdir(parents=True, exist_ok=True)
        dest = theme_dir / "gtk.css"
        shutil.copy2(css_src, dest)
        print(f"  {G}✓ GIMP Spellcaster theme installed:{X} {dest}")
    except OSError as e:
        print(f"  {R}Error installing GIMP theme: {e}{X}")


def apply_spellcaster_theme_gimp(gimp_plug_dir: Path):
    """Replace GIMP splash + icons with Spellcaster branding and install CSS theme."""
    import shutil

    # --- Install the persistent CSS theme ---
    _install_gimp_css_theme(gimp_plug_dir)

    # Find system splash
    candidates = []
    if platform.system() == "Windows":
        for pf in [Path("C:/Program Files/GIMP 3"), Path("C:/Program Files (x86)/GIMP 3")]:
            share = pf / "share" / "gimp" / "3.0" / "images"
            if share.is_dir():
                for f in share.glob("gimp-splash*.png"):
                    candidates.append(f)
    elif platform.system() == "Darwin":
        for app in [Path("/Applications/GIMP-3.0.app"), Path("/Applications/GIMP.app")]:
            share = app / "Contents" / "Resources" / "share" / "gimp" / "3.0" / "images"
            if share.is_dir():
                for f in share.glob("gimp-splash*.png"):
                    candidates.append(f)
    else:
        for base in [Path("/usr/share/gimp/3.0/images"), Path("/usr/local/share/gimp/3.0/images")]:
            if base.is_dir():
                for f in base.glob("gimp-splash*.png"):
                    candidates.append(f)

    connector_dir = gimp_plug_dir / "comfyui-connector"

    # Replace splash
    banner = connector_dir / "gimp_banner.png" if connector_dir.is_dir() else None
    if not banner or not banner.exists():
        # Try to download it
        banner_url = f"{GITHUB_RAW}/plugins/gimp/gimp_banner.png"
        banner = connector_dir / "gimp_banner.png" if connector_dir.is_dir() else Path("gimp_banner.png")
        download_file(banner_url, banner)

    if banner and banner.exists():
        for splash in candidates:
            if splash.exists():
                backup = splash.with_suffix(".orig" + splash.suffix)
                try:
                    if not backup.exists():
                        shutil.copy2(splash, backup)
                    shutil.copy2(banner, splash)
                    print(f"  {G}✓ GIMP splash replaced:{X} {splash.name}")
                except PermissionError:
                    print(f"  {R}Permission denied — try running as Administrator{X}")
                except OSError as e:
                    print(f"  {R}Error: {e}{X}")
                break
        else:
            if candidates:
                print(f"  {Y}GIMP splash file not found at expected location{X}")
    else:
        print(f"  {Y}gimp_banner.png not available{X}")

    # Replace Wilber icon
    icon_url = f"{GITHUB_RAW}/assets/spellcaster_gimp_icon.png"
    icon_dest = connector_dir / "spellcaster_icon.png" if connector_dir.is_dir() else None
    if icon_dest:
        download_file(icon_url, icon_dest)
        print(f"  {G}✓ Wizard Wilber icon installed{X}")

    # Try system icon replacement
    for icon_name in ["gimp-logo.png", "wilber.png"]:
        for d in candidates:
            icon_path = d.parent / icon_name
            if icon_path.exists() and icon_dest and icon_dest.exists():
                backup = icon_path.with_suffix(".orig" + icon_path.suffix)
                try:
                    if not backup.exists():
                        shutil.copy2(icon_path, backup)
                    shutil.copy2(icon_dest, icon_path)
                    print(f"  {G}✓ System icon replaced:{X} {icon_name}")
                except (PermissionError, OSError):
                    pass
                break


def _install_darktable_css_theme(dt_dir: Path):
    """Install the Spellcaster CSS theme into Darktable's user themes directory.

    Copies spellcaster-darktable.css to:
      - Windows: %APPDATA%/darktable/themes/spellcaster-darktable.css
      - macOS:   ~/Library/Application Support/darktable/themes/spellcaster-darktable.css
      - Linux:   ~/.config/darktable/themes/spellcaster-darktable.css
    """
    import shutil

    css_src = dt_dir / "spellcaster-darktable.css"

    # Download CSS if not present locally
    if not css_src.exists():
        css_url = f"{GITHUB_RAW}/plugins/darktable/spellcaster-darktable.css"
        download_file(css_url, css_src)

    if not css_src.exists():
        print(f"  {Y}spellcaster-darktable.css not available{X}")
        return

    # Determine Darktable user themes directory
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            themes_dir = Path(appdata) / "darktable" / "themes"
        else:
            # Fallback: try LocalAppData
            local = os.environ.get("LOCALAPPDATA", "")
            if local:
                themes_dir = Path(local) / "darktable" / "themes"
            else:
                print(f"  {Y}Cannot determine APPDATA for Darktable theme install{X}")
                return
    elif platform.system() == "Darwin":
        themes_dir = Path.home() / "Library" / "Application Support" / "darktable" / "themes"
    else:
        themes_dir = Path.home() / ".config" / "darktable" / "themes"

    try:
        themes_dir.mkdir(parents=True, exist_ok=True)
        dest = themes_dir / "spellcaster-darktable.css"
        shutil.copy2(css_src, dest)
        print(f"  {G}✓ Darktable Spellcaster theme installed:{X} {dest}")
    except OSError as e:
        print(f"  {R}Error installing Darktable theme: {e}{X}")


def apply_spellcaster_theme_darktable(dt_dir: Path):
    """Replace Darktable splash + icons with Spellcaster branding and install CSS theme."""
    import shutil

    # --- Install the persistent CSS theme ---
    _install_darktable_css_theme(dt_dir)

    # Find system splash
    candidates = []
    if platform.system() == "Windows":
        for pf in [Path("C:/Program Files/darktable"), Path("C:/Program Files (x86)/darktable")]:
            p = pf / "share" / "darktable" / "images"
            if p.is_dir():
                for f in p.glob("darktable-splash*"):
                    candidates.append(f)
    elif platform.system() == "Darwin":
        for app in [Path("/Applications/darktable.app")]:
            p = app / "Contents" / "Resources" / "share" / "darktable" / "images"
            if p.is_dir():
                for f in p.glob("darktable-splash*"):
                    candidates.append(f)
    else:
        for base in [Path("/usr/share/darktable/images"), Path("/usr/local/share/darktable/images")]:
            if base.is_dir():
                for f in base.glob("darktable-splash*"):
                    candidates.append(f)

    # Download splash source
    splash_src = dt_dir / "darktable_splash.jpg"
    if not splash_src.exists():
        download_file(f"{GITHUB_RAW}/plugins/darktable/darktable_splash.jpg", splash_src)

    if splash_src.exists():
        for splash in candidates:
            if splash.exists():
                backup = splash.with_suffix(".orig" + splash.suffix)
                try:
                    if not backup.exists():
                        shutil.copy2(splash, backup)
                    shutil.copy2(splash_src, splash)
                    print(f"  {G}✓ Darktable splash replaced:{X} {splash.name}")
                except PermissionError:
                    print(f"  {R}Permission denied — try running as Administrator{X}")
                except OSError as e:
                    print(f"  {R}Error: {e}{X}")
                break
        else:
            if not candidates:
                print(f"  {Y}Darktable system splash not found{X}")
    else:
        print(f"  {Y}darktable_splash.jpg not available{X}")

    # Download and install sparkle icon
    icon_url = f"{GITHUB_RAW}/assets/spellcaster_darktable_icon.png"
    icon_dest = dt_dir / "spellcaster_icon.png"
    download_file(icon_url, icon_dest)
    if icon_dest.exists():
        print(f"  {G}✓ Sparkle lens icon installed{X}")


# ─── Repair & Update ───────────────────────────────────────────────────────

def repair_and_install_gimp(plug_dir: Path, server_url: str = "http://127.0.0.1:8188") -> bool:
    """Full repair: clean up any broken installs, then download fresh plugin files."""
    correct_dir = plug_dir / "comfyui-connector"

    # Step 1: Remove any broken installs (wrong folder names)
    if plug_dir.is_dir():
        for sub in list(plug_dir.iterdir()):
            if sub.is_dir() and sub.name != "comfyui-connector":
                if (sub / "comfyui-connector.py").exists():
                    print(f"  {Y}Removing broken install:{X} {sub.name}/")
                    # Preserve config.json if it has a custom server URL
                    old_config = sub / "config.json"
                    if old_config.exists():
                        try:
                            server_url = json.loads(old_config.read_text()).get("server_url", server_url)
                        except Exception:
                            pass
                    shutil.rmtree(sub)

        # Remove loose script
        loose = plug_dir / "comfyui-connector.py"
        if loose.exists():
            print(f"  {Y}Removing loose script from plug-ins/{X}")
            loose.unlink()

    # Step 2: Create correct directory and download fresh files
    plug_dir.mkdir(parents=True, exist_ok=True)
    correct_dir.mkdir(parents=True, exist_ok=True)

    # Dynamic file discovery: fetch the actual file list from GitHub
    # Falls back to the static list if the API is unavailable
    print(f"  {C}Discovering latest plugin files from GitHub...{X}")
    remote_files = discover_remote_files(GIMP_PLUGIN_PREFIX)
    file_list = remote_files if remote_files else GIMP_PLUGIN_FILES
    if remote_files:
        print(f"    {G}✓{X} Found {len(remote_files)} files via GitHub API")
    else:
        print(f"    {Y}Using static file list (GitHub API unavailable){X}")

    all_ok = True
    for rel_path in file_list:
        filename = Path(rel_path).name
        url = f"{GITHUB_RAW}/{rel_path}"
        dest = correct_dir / filename
        if download_file(url, dest):
            print(f"    {G}✓{X} {filename}")
        else:
            all_ok = False

    # Remove stale local files not present in the remote list
    if remote_files:
        remote_filenames = {Path(p).name for p in remote_files}
        protected = {"config.json", ".spellcaster_version"}
        for local_file in correct_dir.iterdir():
            if (local_file.is_file() and local_file.name not in protected
                    and not local_file.name.endswith(".pyc")
                    and local_file.name not in remote_filenames):
                try:
                    local_file.unlink()
                    print(f"    {Y}Removed stale:{X} {local_file.name}")
                except Exception:
                    pass

    # Step 3: Write config.json
    config_path = correct_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps({"server_url": server_url}, indent=4))
        print(f"    {G}✓{X} config.json (server: {server_url})")
    else:
        print(f"    {G}✓{X} config.json (preserved existing)")

    # Step 4: Set executable on Unix
    if os.name != "nt":
        script = correct_dir / "comfyui-connector.py"
        if script.exists():
            script.chmod(0o755)
            print(f"    {G}✓{X} Set executable permission")

    # Step 5: Verify
    script = correct_dir / "comfyui-connector.py"
    if script.exists() and script.stat().st_size > 1000:
        print(f"\n  {G}✓ Plugin installed correctly:{X}")
        print(f"    {script}")
        print(f"    Size: {script.stat().st_size:,} bytes")
        return True
    else:
        print(f"\n  {R}✗ Installation verification failed{X}")
        return False


def update_darktable_plugin(dt_dir: Path) -> bool:
    """Download latest Darktable plugin files from GitHub.

    Uses dynamic file discovery via GitHub Tree API so new files are
    automatically picked up without hardcoded lists.
    """
    print(f"  {C}Discovering latest plugin files...{X}")
    remote_files = discover_remote_files(DARKTABLE_PLUGIN_PREFIX)
    file_list = remote_files if remote_files else DARKTABLE_PLUGIN_FILES
    if remote_files:
        print(f"    {G}✓{X} Found {len(remote_files)} files via GitHub API")
    else:
        print(f"    {Y}Using static file list (GitHub API unavailable){X}")

    all_ok = True
    for rel_path in file_list:
        filename = Path(rel_path).name
        url = f"{GITHUB_RAW}/{rel_path}"
        dest = dt_dir / filename
        if download_file(url, dest):
            print(f"    {G}✓{X} {filename}")
        else:
            all_ok = False

    # Remove stale local files
    if remote_files:
        remote_filenames = {Path(p).name for p in remote_files}
        protected = {"config.json", ".spellcaster_version"}
        for local_file in dt_dir.iterdir():
            if (local_file.is_file() and local_file.name not in protected
                    and not local_file.name.endswith(".pyc")
                    and local_file.name not in remote_filenames):
                # Only clean up known plugin files, not user files
                if local_file.suffix in (".lua", ".py", ".png", ".jpg"):
                    try:
                        local_file.unlink()
                        print(f"    {Y}Removed stale:{X} {local_file.name}")
                    except Exception:
                        pass
    return all_ok


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    banner()

    print(f"  {B}System:{X} {platform.system()} {platform.release()}")
    print(f"  {B}User:{X}   {Path.home()}")
    sha = get_latest_sha()
    print(f"  {B}Latest:{X} {C}{sha}{X}\n")

    # ══════════════════════════════════════════════════════════════════════
    # GIMP
    # ══════════════════════════════════════════════════════════════════════
    print(f"{B}{'═' * 50}{X}")
    print(f"{B}  GIMP 3 Plugin{X}")
    print(f"{B}{'═' * 50}{X}\n")

    # Try to find GIMP binary
    _ask_gimp_for_plugin_dirs()

    gimp_dirs = find_all_gimp_plugin_dirs()

    if not gimp_dirs:
        print(f"\n  {R}No GIMP 3 plug-in directories found anywhere on this system.{X}")
        print(f"  Possible causes:")
        print(f"    1. GIMP 3 is not installed")
        print(f"    2. GIMP 3 has never been launched (it creates config on first run)")
        print(f"    3. GIMP is installed in a non-standard location")
        print()

        # Offer manual path entry
        print(f"  {B}Enter the path to your GIMP 3 plug-ins directory manually{X}")
        print(f"  {D}(or press Enter to skip):{X}")
        if platform.system() == "Windows":
            print(f"  {D}Example: C:\\Users\\YourName\\AppData\\Roaming\\GIMP\\3.0\\plug-ins{X}")
        elif platform.system() == "Darwin":
            print(f"  {D}Example: ~/Library/Application Support/GIMP/3.0/plug-ins{X}")
        else:
            print(f"  {D}Example: ~/.config/GIMP/3.0/plug-ins{X}")

        try:
            raw = input(f"\n  {B}Path:{X} ").strip()
        except (RuntimeError, EOFError):
            raw = ""
        if raw:
            manual_dir = Path(raw).expanduser().resolve()
            gimp_dirs = [manual_dir]
            print()
        else:
            print(f"\n  {Y}Skipping GIMP plugin installation.{X}\n")

    if gimp_dirs:
        # Show all discovered directories
        print(f"  Scanning {len(gimp_dirs)} location(s):\n")
        for d in gimp_dirs:
            status = f"{G}exists{X}" if d.is_dir() else f"{Y}will create{X}"
            print(f"    {d} [{status}]")

        # Find any existing installs (correct or broken)
        existing = deep_scan_for_spellcaster(
            [d.parent for d in gimp_dirs if d.parent.is_dir()]  # search GIMP config root
            + [d for d in gimp_dirs if d.is_dir()]               # search plug-ins dirs
        )

        if existing:
            print(f"\n  {B}Found existing Spellcaster files:{X}")
            for e in existing:
                print(f"    {e['location']}")

        # Pick the best target directory (prefer existing, then first available)
        target_dir = None
        server_url = "http://127.0.0.1:8188"

        # Check existing installs for server URL
        for d in gimp_dirs:
            for cfg_path in [d / "comfyui-connector" / "config.json",
                             d / "spellcaster" / "config.json"]:
                if cfg_path.exists():
                    try:
                        server_url = json.loads(cfg_path.read_text()).get("server_url", server_url)
                    except Exception:
                        pass

        # Use first directory that exists, or first in list
        for d in gimp_dirs:
            if d.is_dir():
                target_dir = d
                break
        if not target_dir:
            target_dir = gimp_dirs[0]

        # Fix gimprc and delete pluginrc cache BEFORE installing
        # (the config dir is one level above plug-ins/)
        gimp_config_dir = target_dir.parent
        if gimp_config_dir.is_dir():
            print(f"  {B}Checking GIMP configuration:{X} {gimp_config_dir}\n")
            fix_gimprc_plugin_path(gimp_config_dir)
            print()

        print(f"  {B}Installing/repairing in:{X} {target_dir}\n")
        success = repair_and_install_gimp(target_dir, server_url)

        # Run diagnostics
        issues = diagnose_gimp_install(target_dir)
        if issues and success:
            print(f"\n  {Y}Potential issues detected:{X}")
            for issue in issues:
                print(f"    {Y}!{X} {issue}")
        elif not issues and success:
            print(f"  {G}No issues detected — plugin should be visible in GIMP.{X}")

        # Show what GIMP expects
        print(f"\n  {B}GIMP 3 Plugin Requirements:{X}")
        print(f"    1. Folder name MUST be 'comfyui-connector' (matches script name)")
        print(f"    2. Must be inside the plug-ins/ directory shown above")
        print(f"    3. Script must be executable (Unix only)")
        print(f"    4. GIMP must be restarted after installation")
        print(f"    5. Check Filters > Spellcaster after restart")
        print()

        # Final file listing
        final_dir = target_dir / "comfyui-connector"
        if final_dir.is_dir():
            print(f"  {B}Installed files:{X}")
            for f in sorted(final_dir.iterdir()):
                size = f.stat().st_size
                print(f"    {f.name:40s} {size:>10,} bytes")
            print()

        # Personalization prompt
        if success and _ask_yn("Apply Spellcaster visual theme to GIMP? (wizard hat icon + custom splash)"):
            print()
            apply_spellcaster_theme_gimp(target_dir)
            print()

    # ══════════════════════════════════════════════════════════════════════
    # Darktable
    # ══════════════════════════════════════════════════════════════════════
    print(f"{B}{'═' * 50}{X}")
    print(f"{B}  Darktable Plugin{X}")
    print(f"{B}{'═' * 50}{X}\n")

    dt_dirs = find_all_darktable_dirs()
    if not dt_dirs:
        print(f"  {D}No Darktable lua/contrib directory found (skipping).{X}\n")
    else:
        for dt_dir in dt_dirs:
            existing = dt_dir / "comfyui_connector.lua"
            if existing.exists():
                print(f"  {G}✓ Found existing:{X} {existing}")
            print(f"  {B}Updating Darktable plugin in:{X} {dt_dir}")
            success = update_darktable_plugin(dt_dir)
            print()
            if success and _ask_yn("Apply Spellcaster visual theme to Darktable? (sparkle icon + custom splash)"):
                print()
                apply_spellcaster_theme_darktable(dt_dir)
                print()

    # ══════════════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════════════
    print(f"{B}{'═' * 50}{X}")
    print(f"{B}  UPDATE COMPLETE — version {sha}{X}")
    print(f"{B}{'═' * 50}{X}")
    print(f"\n  {B}Next steps:{X}")
    print(f"    1. {B}Restart GIMP 3{X} completely (close all windows first)")
    print(f"    2. Go to {B}Filters > Spellcaster{X}")
    print(f"    3. If still not visible, check {B}Filters > Script-Fu > Console{X}")
    print(f"       and look for error messages about comfyui-connector")
    print(f"    4. Make sure ComfyUI is running on your server")
    print()

    if platform.system() == "Windows":
        try:
            input("Press Enter to close...")
        except (RuntimeError, EOFError):
            pass


if __name__ == "__main__":
    main()
