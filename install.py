#!/usr/bin/env python3
"""
Spellcaster Installer
=====================
Interactive installer for the Spellcaster ComfyUI connector plugins for GIMP 3
and Darktable. Downloads and installs models, custom nodes, and patches the
host applications.

Usage:
    python install.py                          # Interactive wizard (GUI)
    python install.py --cli                    # Force terminal mode
    python install.py --dry-run                # Preview without changes
    python install.py --yes                    # Auto-accept all defaults
    python install.py --server-url http://192.168.1.50:8188  # Remote ComfyUI
    python install.py --features img2img,inpaint,face_swap_reactor
    python install.py --comfyui ~/ComfyUI --gimp ~/.config/GIMP/3.0/plug-ins
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

if getattr(sys, 'frozen', False):
    SCRIPT_DIR = Path(sys._MEIPASS)
else:
    SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPT_DIR / "manifest.json"
VERSION = "1.0.0"
DEFAULT_SERVER_URL = "http://127.0.0.1:8188"

# ANSI colors (disabled on Windows without VT support)
if sys.stdout.isatty() and (os.name != "nt" or os.environ.get("WT_SESSION")):
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
    print(f"""
{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════╗
║     ✦  SPELLCASTER INSTALLER  v{VERSION}  ✦     ║
║                                              ║
║  ComfyUI connectors for GIMP 3 & Darktable  ║
╚══════════════════════════════════════════════╝{C_RESET}
""")


def fmt_size(mb: float) -> str:
    if mb < 1:
        return f"{mb * 1024:.0f} KB"
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def ask_yn(prompt: str, default: bool = True, auto_yes: bool = False) -> bool:
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
    if auto_yes and default:
        print(f"{C_BOLD}{prompt} [{default}]:{C_RESET} {default} (auto)")
        return default
    hint = f" [{default}]" if default else ""
    raw = input(f"{C_BOLD}{prompt}{hint}:{C_RESET} ").strip()
    return raw if raw else default


# ─── Application path detection ───────────────────────────────────────────────

def find_default_comfyui() -> str:
    home = Path.home()
    if platform.system() == "Windows":
        candidates = [
            home / "ComfyUI",
            Path("C:/ComfyUI"),
            home / "Desktop" / "ComfyUI",
            home / "Documents" / "ComfyUI",
            Path("D:/ComfyUI"),
            Path("E:/ComfyUI"),
        ]
    elif platform.system() == "Darwin":
        candidates = [
            home / "ComfyUI",
            Path("/Applications/ComfyUI"),
            home / "Documents" / "ComfyUI",
        ]
    else:
        candidates = [
            home / "ComfyUI",
            Path("/opt/ComfyUI"),
            home / "Documents" / "ComfyUI",
        ]
    for c in candidates:
        if (c / "main.py").is_file() or (c / "comfy" / "cli_args.py").is_file():
            return str(c)
    return ""


def find_default_gimp() -> str:
    home = Path.home()
    if platform.system() == "Windows":
        candidates = [
            home / "AppData" / "Roaming" / "GIMP" / "3.0" / "plug-ins",
            home / "AppData" / "Roaming" / "GIMP" / "2.99" / "plug-ins",
        ]
    elif platform.system() == "Darwin":
        candidates = [
            home / "Library" / "Application Support" / "GIMP" / "3.0" / "plug-ins",
            home / ".config" / "GIMP" / "3.0" / "plug-ins",
        ]
    else:
        candidates = [
            home / ".config" / "GIMP" / "3.0" / "plug-ins",
            home / ".config" / "GIMP" / "2.99" / "plug-ins",
        ]
    for c in candidates:
        if c.is_dir():
            return str(c)
    return ""


def find_default_darktable() -> str:
    home = Path.home()
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
            return str(c)
    return ""


# ─── Download & install helpers ───────────────────────────────────────────────

def download_file(url: str, dest: Path, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"  {C_DIM}[dry-run] Would download: {url}{C_RESET}")
        print(f"  {C_DIM}         → {dest}{C_RESET}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  {C_CYAN}Downloading:{C_RESET} {dest.name}")
    print(f"  {C_DIM}From: {url}{C_RESET}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Spellcaster-Installer/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
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
                        pct = downloaded * 100 // total
                        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                        print(f"\r  [{bar}] {pct}% ({fmt_size(downloaded / 1048576)}/{fmt_size(total / 1048576)})",
                              end="", flush=True)
            if total > 0:
                print()
        print(f"  {C_GREEN}✓ Saved to {dest}{C_RESET}")
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"\n  {C_RED}✗ Download failed: {e}{C_RESET}")
        if dest.exists():
            dest.unlink()
        return False


def git_clone(repo_url: str, dest: Path, dry_run: bool = False) -> bool:
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
            return True  # already exists
    print(f"  {C_CYAN}Cloning:{C_RESET} {dest.name}")
    print(f"  {C_DIM}From: {repo_url}{C_RESET}")
    try:
        subprocess.run(["git", "clone", "--depth", "1", repo_url, str(dest)],
                       capture_output=True, check=True, timeout=300)
        print(f"  {C_GREEN}✓ Cloned {dest.name}{C_RESET}")
        return True
    except FileNotFoundError:
        return _download_and_extract_github_zip(repo_url, dest)
    except subprocess.CalledProcessError as e:
        print(f"  {C_RED}✗ Clone failed: {e.stderr.decode(errors='replace')}{C_RESET}")
        return False


def _download_and_extract_github_zip(repo_url: str, dest: Path) -> bool:
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
                top = zf.namelist()[0].split('/')[0] + '/'
                for member in zf.infolist():
                    if member.filename == top:
                        continue
                    if member.filename.startswith(top):
                        rel = member.filename[len(top):]
                        if not rel:
                            continue
                        tp = dest / rel
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
                continue
            print(f"  {C_RED}✗ ZIP download failed ({e.code}){C_RESET}")
            return False
        except Exception as e:
            print(f"  {C_RED}✗ Extraction failed: {e}{C_RESET}")
            return False
    print(f"  {C_RED}✗ Could not find repo ZIP for {repo_url}{C_RESET}")
    return False


def get_comfy_python(comfyui_path: Path) -> str:
    if not comfyui_path:
        return sys.executable
    embed = comfyui_path / "python_embeded" / "python.exe"
    if embed.exists():
        return str(embed)
    for venv in ["venv", ".venv"]:
        for rel in [("Scripts", "python.exe"), ("bin", "python3"), ("bin", "python")]:
            vp = comfyui_path / venv / rel[0] / rel[1]
            if vp.exists():
                return str(vp)
    if hasattr(sys, 'frozen'):
        sys_py = shutil.which("python") or shutil.which("python3")
        if sys_py:
            return sys_py
    return sys.executable


def install_node_requirements(node_dir: Path, comfyui_path: Path, dry_run: bool = False) -> bool:
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


def patch_plugin_server_url(file_path: Path, server_url: str, dry_run: bool = False) -> bool:
    """Patch the default ComfyUI server URL in a plugin file."""
    if server_url == DEFAULT_SERVER_URL:
        return True  # no-op, already localhost
    if dry_run:
        print(f"  {C_DIM}[dry-run] Would patch server URL in {file_path.name}: → {server_url}{C_RESET}")
        return True
    try:
        text = file_path.read_text(encoding="utf-8")
        if file_path.suffix == ".lua":
            # Darktable Lua plugin (dt.preferences.register default URL)
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
    total = 0.0
    for m in collect_models_for_feature(feature):
        if required_only and m.get("optional", False):
            continue
        total += m.get("size_mb", 0)
    return total


def print_feature_summary(key: str, feature: dict[str, Any], selected: bool):
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

def step_detect_server(args) -> str:
    """Step 0: Determine ComfyUI server URL."""
    print(f"\n{C_BOLD}{'═' * 50}{C_RESET}")
    print(f"{C_BOLD}  STEP 1: ComfyUI Server{C_RESET}")
    print(f"{C_BOLD}{'═' * 50}{C_RESET}\n")

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
        print(f"\n  {C_DIM}Example: 192.168.1.50:8188{C_RESET}")
        raw = ask_text("  Enter IP:port of the ComfyUI machine", auto_yes=args.yes)
        raw = raw.strip().rstrip("/")
        if not raw.startswith("http"):
            raw = "http://" + raw
        return raw
    else:
        raw = ask_text("  Enter full ComfyUI URL", default=DEFAULT_SERVER_URL, auto_yes=args.yes)
        return raw.strip().rstrip("/")


def step_detect_paths(args) -> dict:
    """Step 2: Detect or ask for application paths."""
    print(f"\n{C_BOLD}{'═' * 50}{C_RESET}")
    print(f"{C_BOLD}  STEP 2: Application Paths{C_RESET}")
    print(f"{C_BOLD}{'═' * 50}{C_RESET}\n")

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
            print(f"  {C_GREEN}Found ComfyUI at:{C_RESET} {default_comfyui}")
            if ask_yn("  Use this path?", auto_yes=args.yes):
                comfyui_path = Path(default_comfyui)
            else:
                comfyui_path = ask_path("  Enter ComfyUI root directory")
        else:
            print(f"  {C_YELLOW}ComfyUI not found automatically.{C_RESET}")
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
            print(f"  {C_GREEN}Found GIMP plug-ins at:{C_RESET} {default_gimp}")
            if ask_yn("  Install GIMP plugin here?", auto_yes=args.yes):
                gimp_path = Path(default_gimp)
            else:
                if ask_yn("  Install GIMP plugin to a different path?", default=False):
                    gimp_path = ask_path("  Enter GIMP 3 plug-ins directory")
        else:
            print(f"  {C_YELLOW}GIMP 3 plug-ins directory not found automatically.{C_RESET}")
            if ask_yn("  Install the GIMP plugin?", auto_yes=args.yes):
                print(f"  {C_DIM}Typical locations:{C_RESET}")
                if platform.system() == "Windows":
                    print(f"    Windows: %APPDATA%\\GIMP\\3.0\\plug-ins")
                elif platform.system() == "Darwin":
                    print(f"    macOS:   ~/Library/Application Support/GIMP/3.0/plug-ins")
                else:
                    print(f"    Linux:   ~/.config/GIMP/3.0/plug-ins")
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
            print(f"  {C_GREEN}Found darktable lua/contrib at:{C_RESET} {default_dt}")
            if ask_yn("  Install Darktable plugin here?", auto_yes=args.yes):
                dt_path = Path(default_dt)
            else:
                if ask_yn("  Install Darktable plugin to a different path?", default=False):
                    dt_path = ask_path("  Enter darktable lua/contrib directory")
        else:
            print(f"  {C_YELLOW}Darktable lua/contrib directory not found automatically.{C_RESET}")
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


def step_select_features(manifest: dict, paths: dict, args) -> dict[str, bool]:
    """Step 3: Feature selection."""
    print(f"\n{C_BOLD}{'═' * 50}{C_RESET}")
    print(f"{C_BOLD}  STEP 3: Select Features{C_RESET}")
    print(f"{C_BOLD}{'═' * 50}{C_RESET}\n")

    # Pre-selected features from --features flag
    forced_features: set[str] | None = None
    if args.features:
        forced_features = {f.strip() for f in args.features.split(",")}

    has_gimp = paths["gimp"] is not None
    has_dt = paths["darktable"] is not None
    features = manifest["features"]
    selected: dict[str, bool] = {}

    # Track which features we've already handled (for grouped prompts)
    handled = set()

    for key, feat in features.items():
        if key in handled:
            continue

        plugins = feat.get("plugins", [])
        available = ("gimp" in plugins and has_gimp) or ("darktable" in plugins and has_dt)
        if not available:
            selected[key] = False
            handled.add(key)
            continue

        # ── Special case: face swap systems grouped together ──
        if key in ("face_swap_reactor", "face_swap_mtb"):
            handled.add("face_swap_reactor")
            handled.add("face_swap_mtb")

            reactor_feat = features.get("face_swap_reactor", {})
            mtb_feat = features.get("face_swap_mtb", {})
            reactor_size = estimate_feature_size(reactor_feat, required_only=True)
            mtb_size = estimate_feature_size(mtb_feat, required_only=True)

            print(f"\n  {C_BOLD}Face Swap Systems{C_RESET}")
            print(f"  {C_DIM}ReActor: industry-standard swap, CodeFormer restore (~{fmt_size(reactor_size)}){C_RESET}")
            print(f"  {C_DIM}MTB:     lightweight alternative, auto-downloads models{C_RESET}")

            if forced_features is not None:
                selected["face_swap_reactor"] = "face_swap_reactor" in forced_features
                selected["face_swap_mtb"] = "face_swap_mtb" in forced_features
            else:
                choice = ask_choice(
                    "Which face swap system(s) would you like to install?",
                    [
                        "Both ReActor and MTB  (recommended — different strengths)",
                        f"ReActor only  (~{fmt_size(reactor_size)} downloads)",
                        "MTB only  (no model downloads required)",
                        "Neither — skip face swap",
                    ],
                    default=0,
                    auto_yes=args.yes,
                )
                selected["face_swap_reactor"] = choice in (0, 1)
                selected["face_swap_mtb"] = choice in (0, 2)
            continue

        # ── Standard feature prompt ──
        if forced_features is not None:
            selected[key] = key in forced_features
            handled.add(key)
            continue

        req_size = estimate_feature_size(feat, required_only=True)
        full_size = estimate_feature_size(feat)
        size_str = ""
        if full_size > 0:
            size_str = f" [{C_YELLOW}{fmt_size(req_size)}{C_RESET} min"
            if full_size > req_size:
                size_str += f", {fmt_size(full_size)} with optionals"
            size_str += "]"

        nodes = feat.get("custom_nodes", [])
        node_str = f" ({len(nodes)} custom node{'s' if len(nodes) != 1 else ''})" if nodes else ""

        selected[key] = ask_yn(
            f"  Install {C_BOLD}{feat['label']}{C_RESET}{node_str}{size_str}?",
            auto_yes=args.yes,
        )
        handled.add(key)

    # ── Summary ──
    print(f"\n{C_BOLD}── Selected Features ──{C_RESET}\n")
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
                       dry_run: bool = False):
    """Step 4: Install required custom nodes."""
    if not paths["comfyui"]:
        print(f"\n  {C_YELLOW}Skipping custom node installation (no ComfyUI path).{C_RESET}")
        return

    print(f"\n{C_BOLD}{'═' * 50}{C_RESET}")
    print(f"{C_BOLD}  STEP 4: Install Custom Nodes{C_RESET}")
    print(f"{C_BOLD}{'═' * 50}{C_RESET}\n")

    custom_nodes_dir = paths["comfyui"] / "custom_nodes"
    if not dry_run:
        custom_nodes_dir.mkdir(parents=True, exist_ok=True)

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

    for node_name in sorted(needed_nodes):
        node_info = node_defs.get(node_name)
        if not node_info:
            print(f"  {C_YELLOW}⚠ Unknown node: {node_name}{C_RESET}")
            continue

        dest = custom_nodes_dir / node_name
        success = git_clone(node_info["repo"], dest, dry_run)

        if not success and "alt_repo" in node_info:
            print(f"  {C_YELLOW}Trying alternative repo…{C_RESET}")
            success = git_clone(node_info["alt_repo"], dest, dry_run)

        if success and not dry_run:
            install_node_requirements(dest, paths["comfyui"], dry_run)
        elif not success:
            failed_nodes.append(node_name)

        if "note" in node_info:
            print(f"  {C_DIM}Note: {node_info['note']}{C_RESET}")

    if failed_nodes:
        print(f"\n  {C_RED}Failed to install nodes: {', '.join(failed_nodes)}{C_RESET}")
        print(f"  Install these manually into: {custom_nodes_dir}")


def step_install_models(manifest: dict, selected: dict[str, bool], paths: dict,
                        args) -> None:
    """Step 5: Download and install models."""
    if not paths["comfyui"]:
        print(f"\n  {C_YELLOW}Skipping model installation (no ComfyUI path).{C_RESET}")
        return

    print(f"\n{C_BOLD}{'═' * 50}{C_RESET}")
    print(f"{C_BOLD}  STEP 5: Download Models{C_RESET}")
    print(f"{C_BOLD}{'═' * 50}{C_RESET}\n")

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

            if url:
                success = download_file(url, dest, args.dry_run)
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
                warnings.append(
                    f"  {C_YELLOW}⚠{C_RESET} {C_BOLD}{rel_path}{C_RESET}{opt_tag}\n"
                    f"    {note}\n"
                    f"    {C_YELLOW}No direct download URL — search CivitAI or HuggingFace.{C_RESET}\n"
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


def step_install_plugins(paths: dict, server_url: str, dry_run: bool = False):
    """Step 6: Copy plugin files, patching the server URL."""
    print(f"\n{C_BOLD}{'═' * 50}{C_RESET}")
    print(f"{C_BOLD}  STEP 6: Install Plugins{C_RESET}")
    print(f"{C_BOLD}{'═' * 50}{C_RESET}\n")

    gimp_src = _find_gimp_plugin_src()
    dt_src = _find_darktable_plugin_src()

    # ── GIMP ──
    if paths["gimp"]:
        if gimp_src:
            dest = paths["gimp"] / gimp_src.name
            print(f"  {C_CYAN}Installing GIMP plugin…{C_RESET}")
            copy_plugin(gimp_src, dest, dry_run)
            
            if not dry_run:
                # Write config.json instead of source patching
                config_path = dest / "config.json"
                if dest.is_dir():
                    try:
                        cfg = {"server_url": server_url}
                        config_path.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
                        print(f"  {C_GREEN}✓ Wrote server configuration to config.json{C_RESET}")
                    except OSError as e:
                        print(f"  {C_YELLOW}⚠ Failed to write config.json: {e}{C_RESET}")

                if os.name != "nt":
                    py_file = (dest / "comfyui-connector.py") if dest.is_dir() else dest
                    if py_file.exists():
                        py_file.chmod(0o755)
        else:
            print(f"  {C_YELLOW}⚠ GIMP plugin source not found.{C_RESET}")
            print(f"    Expected: plugins/gimp/comfyui-connector/comfyui-connector.py")
            print(f"    Copy manually to: {paths['gimp']}/comfyui-connector/")

    # ── Darktable ──
    if paths["darktable"]:
        if dt_src:
            dest = paths["darktable"] / dt_src.name
            print(f"  {C_CYAN}Installing Darktable plugin…{C_RESET}")

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

            # luarc check
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


def step_final_summary(manifest: dict, selected: dict[str, bool], paths: dict, server_url: str):
    """Step 7: Print final summary."""
    print(f"\n{C_BOLD}{'═' * 50}{C_RESET}")
    print(f"{C_BOLD}  INSTALLATION COMPLETE{C_RESET}")
    print(f"{C_BOLD}{'═' * 50}{C_RESET}\n")

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

    print(f"\n  {C_BOLD}Troubleshooting:{C_RESET}")
    print(f"    • 'Node not found' — install the missing custom node into ComfyUI")
    print(f"    • 'Cannot connect' — check ComfyUI is running and the URL is correct")
    print(f"    • Missing model — see warnings above for exact install paths")
    print(f"    • Report issues: https://github.com/laboratoiresonore/spellcaster/issues")
    print()


# ─── Entry point ──────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        print(f"{C_RED}Error: manifest.json not found at {MANIFEST_PATH}{C_RESET}")
        sys.exit(1)
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Spellcaster — ComfyUI connectors for GIMP 3 & Darktable",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python install.py
              python install.py --cli --yes
              python install.py --server-url http://192.168.1.50:8188
              python install.py --features img2img,inpaint,face_swap_reactor
              python install.py --comfyui ~/ComfyUI --gimp ~/.config/GIMP/3.0/plug-ins
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
                             "face_swap_mtb, faceid_img2img, pulid_flux, klein_flux2, wan_i2v")
    parser.add_argument("--comfyui", metavar="PATH",
                        help="Path to ComfyUI root directory")
    parser.add_argument("--gimp", metavar="PATH",
                        help="Path to GIMP 3 plug-ins directory")
    parser.add_argument("--darktable", metavar="PATH",
                        help="Path to Darktable lua/contrib directory")
    parser.add_argument("--skip-models", action="store_true",
                        help="Skip model downloads (install plugins and nodes only)")
    parser.add_argument("--skip-nodes", action="store_true",
                        help="Skip custom node installation")
    parser.add_argument("--version", action="version",
                        version=f"Spellcaster Installer v{VERSION}")
    return parser


def main():
    args = build_arg_parser().parse_args()

    banner()

    if args.dry_run:
        print(f"  {C_YELLOW}DRY RUN MODE — no changes will be made{C_RESET}\n")

    manifest = load_manifest()

    server_url = step_detect_server(args)
    paths = step_detect_paths(args)
    selected = step_select_features(manifest, paths, args)

    if not args.skip_nodes:
        step_install_nodes(manifest, selected, paths, args.dry_run)
    else:
        print(f"\n  {C_YELLOW}--skip-nodes specified — skipping custom node installation.{C_RESET}")

    step_install_models(manifest, selected, paths, args)
    step_install_plugins(paths, server_url, args.dry_run)
    step_final_summary(manifest, selected, paths, server_url)


# ─── GUI wrapper ──────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading as _threading
import traceback

class OutputRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self._ansi = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    def write(self, text):
        self.text_widget.after(0, self._write, text)
    def _write(self, text):
        self.text_widget.config(state="normal")
        clean = self._ansi.sub('', text)
        self.text_widget.insert(tk.END, clean)
        self.text_widget.see(tk.END)
        self.text_widget.config(state="disabled")
    def flush(self):
        pass

class ModernTkinterWizard(tk.Tk):
    def __init__(self, args_ns, manifest):
        super().__init__()
        self.title(f"Spellcaster Installer v{VERSION}")
        self.geometry("800x640")
        self.configure(bg="#2b2d30")
        self.args = args_ns
        self.manifest = manifest
        self.args.yes = True  # force non-interactive for basic step functions

        # State vars
        self.server_url_var = tk.StringVar(value=DEFAULT_SERVER_URL)
        self.comfy_path_var = tk.StringVar(value=find_default_comfyui())
        self.gimp_path_var = tk.StringVar(value=find_default_gimp())
        self.dt_path_var = tk.StringVar(value=find_default_darktable())
        
        self.features_vars = {}
        for key in manifest["features"]:
            self.features_vars[key] = tk.BooleanVar(value=True)

        self.setup_ui()

    def setup_ui(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#2b2d30')
        style.configure('TLabel', background='#2b2d30', foreground='#a9b7c6', font=('Segoe UI', 10))
        style.configure('Header.TLabel', font=('Segoe UI', 14, 'bold'), foreground='#cc7832')
        style.configure('TButton', background='#4c5052', foreground='#a9b7c6')
        style.configure('TCheckbutton', background='#2b2d30', foreground='#a9b7c6')

        # Pages
        self.page1 = ttk.Frame(self.notebook)
        self.page2 = ttk.Frame(self.notebook)
        self.page3 = ttk.Frame(self.notebook)

        self.notebook.add(self.page1, text="1. Paths")
        self.notebook.add(self.page2, text="2. Features")
        self.notebook.add(self.page3, text="3. Install", state="disabled")

        self.build_paths_page()
        self.build_features_page()
        self.build_install_page()

    def build_paths_page(self):
        f = self.page1
        ttk.Label(f, text="ComfyUI & Host Paths", style='Header.TLabel').pack(pady=(20, 10))

        def add_dir_row(parent, label, var):
            row = ttk.Frame(parent)
            row.pack(fill="x", padx=40, pady=5)
            ttk.Label(row, text=label, width=20).pack(side="left")
            ttk.Entry(row, textvariable=var, width=50).pack(side="left", padx=5)
            ttk.Button(row, text="Browse...", command=lambda: var.set(filedialog.askdirectory() or var.get())).pack(side="left")

        # Server
        row = ttk.Frame(f)
        row.pack(fill="x", padx=40, pady=5)
        ttk.Label(row, text="ComfyUI Server URL:", width=20).pack(side="left")
        ttk.Entry(row, textvariable=self.server_url_var, width=50).pack(side="left", padx=5)

        add_dir_row(f, "ComfyUI Directory:", self.comfy_path_var)
        add_dir_row(f, "GIMP Plug-ins:", self.gimp_path_var)
        add_dir_row(f, "Darktable lua/contrib:", self.dt_path_var)

        btn_box = ttk.Frame(f)
        btn_box.pack(side="bottom", fill="x", pady=20, padx=20)
        ttk.Button(btn_box, text="Next >", command=lambda: self.notebook.select(self.page2)).pack(side="right")

    def build_features_page(self):
        f = self.page2
        ttk.Label(f, text="Select Features", style='Header.TLabel').pack(pady=(20, 10))

        scroll_frame = ttk.Frame(f)
        scroll_frame.pack(fill="both", expand=True, padx=40, pady=10)
        
        canvas = tk.Canvas(scroll_frame, bg="#2b2d30", highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        scrollable_content = ttk.Frame(canvas)
        scrollable_content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for key, feat in self.manifest["features"].items():
            ttk.Checkbutton(scrollable_content, text=feat["label"], variable=self.features_vars[key]).pack(anchor="w", pady=2)
            ttk.Label(scrollable_content, text=feat.get("description", ""), foreground="#808080").pack(anchor="w", padx=20)

        btn_box = ttk.Frame(f)
        btn_box.pack(side="bottom", fill="x", pady=20, padx=20)
        ttk.Button(btn_box, text="< Back", command=lambda: self.notebook.select(self.page1)).pack(side="left")
        ttk.Button(btn_box, text="Install", command=self.start_install).pack(side="right")

    def build_install_page(self):
        f = self.page3
        ttk.Label(f, text="Installation Progress", style='Header.TLabel').pack(pady=(10, 5))
        
        self.progress = ttk.Progressbar(f, mode="indeterminate")
        self.progress.pack(fill="x", padx=20, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(f, bg="#1e1f22", fg="#a9b7c6", font=("Consolas", 10), state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.finish_btn = ttk.Button(f, text="Close", command=self.destroy, state="disabled")
        self.finish_btn.pack(pady=10)
        
        sys.stdout = OutputRedirector(self.log_text)

    def start_install(self):
        self.notebook.tab(self.page1, state="disabled")
        self.notebook.tab(self.page2, state="disabled")
        self.notebook.tab(self.page3, state="normal")
        self.notebook.select(self.page3)
        self.progress.start(15)
        
        _threading.Thread(target=self.run_install_thread, daemon=True).start()

    def run_install_thread(self):
        try:
            print("Starting setup...")
            
            server_url = self.server_url_var.get().strip().rstrip("/")
            if not server_url.startswith("http"):
                server_url = "http://" + server_url
                
            c_path = self.comfy_path_var.get().strip()
            g_path = self.gimp_path_var.get().strip()
            d_path = self.dt_path_var.get().strip()
            
            paths = {
                "comfyui": Path(c_path) if c_path else None,
                "gimp": Path(g_path) if g_path else None,
                "darktable": Path(d_path) if d_path else None
            }
            
            selected = {k: v.get() for k, v in self.features_vars.items()}
            
            print("Checking nodes...")
            if not self.args.skip_nodes:
                step_install_nodes(self.manifest, selected, paths, self.args.dry_run)
                
            print("Checking models...")
            step_install_models(self.manifest, selected, paths, self.args)
            
            print("Installing plugins...")
            step_install_plugins(paths, server_url, self.args.dry_run)
            step_final_summary(self.manifest, selected, paths, server_url)
            
            print("\nSetup fully completed successsfully!")
        except Exception as e:
            print(f"\nFATAL ERROR: {traceback.format_exc()}")
            messagebox.showerror("Installation Error", str(e))
        finally:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=100)
            self.finish_btn.configure(state="normal")


if __name__ == "__main__":
    _args = build_arg_parser().parse_args()
    if _args.cli or not sys.stdin.isatty():
        main()
    else:
        try:
            app = ModernTkinterWizard(_args, load_manifest())
            app.mainloop()
        except Exception as e:
            print(f"Failed to load GUI: {e}")
            main()
