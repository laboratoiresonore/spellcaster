"""Installer step: ask per-service "local or remote?" and generate antenna.bat files.

Flow
----
After path detection, the installer calls `step_ask_remote_services(args)`
which loops over the dynamic service registry (remote_services.json) and
asks, per service, whether it lives:
  [1] Local        — on THIS machine
  [2] Remote       — on another machine on the LAN (prompts for IP)
  [3] Skip/absent  — not used in this install

Remote selections are grouped by IP so one `antenna_for_<ip>.bat` is
generated per machine, not per service. A box that hosts both ComfyUI
and KoboldCpp gets one bat file, managing both.

The generated bat contains:
  - The hub URL (the machine running this installer)
  - A fresh per-machine auth token
  - The list of services the antenna should advertise
  - A bootstrap that fetches the antenna bundle from the hub
  - A launch command

The `.sh` equivalent is emitted alongside for Linux/macOS remote boxes.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import stat
import sys
from pathlib import Path
from typing import Any

from . import remote_services


# Output marker used in messages / logs / Guild UI. Kept here so it can be
# referenced without circular imports.
ANTENNA_BAT_DIR_NAME = "antennas"


# ─── Prompts ──────────────────────────────────────────────────────────────

def _ask_with_default(prompt: str, default: str = "", auto_yes: bool = False) -> str:
    """ask_text-equivalent; duplicated here to avoid circular import with install.py."""
    if auto_yes:
        return default
    try:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        return raw or default
    except (EOFError, KeyboardInterrupt):
        print()
        return default


def _ask_choice(prompt: str, choices: list[str], default: int = 0,
                auto_yes: bool = False) -> int:
    if auto_yes:
        return default
    print(f"\n  {prompt}")
    for i, c in enumerate(choices, start=1):
        marker = " (default)" if (i - 1) == default else ""
        print(f"    [{i}] {c}{marker}")
    try:
        raw = input("  > ").strip()
        if not raw:
            return default
        idx = int(raw) - 1
        if 0 <= idx < len(choices):
            return idx
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return default


# ─── Main step ────────────────────────────────────────────────────────────

def step_ask_remote_services(args) -> dict[str, Any]:
    """Ask the user, per service, whether it's local / remote / skip.

    Returns a dict:
      {
        "local":   ["comfyui", "gimp", ...],
        "skip":    ["darktable", ...],
        "remotes": {
          "192.168.1.100": {"services": ["comfyui", "ollama"], "hostname_hint": ""},
          "192.168.1.101": {"services": ["sillytavern"], "hostname_hint": ""},
        }
      }

    The caller (install.py) passes this to generate_antenna_files() after
    the main install completes.
    """
    services = remote_services.load_services()

    print()
    print("=" * 60)
    print("  Multi-machine setup")
    print("=" * 60)
    print("  Spellcaster can coordinate services running on different")
    print("  machines on your local network. For each service below,")
    print("  tell us where it runs.\n")
    print("  Common pattern:")
    print("    - Powerful GPU box      → ComfyUI + LLM (remote)")
    print("    - Your workstation      → GIMP / Darktable (local)")
    print("    - Video editing station → DaVinci Resolve (remote)\n")

    result: dict[str, Any] = {"local": [], "skip": [], "remotes": {}}

    for svc in services:
        key = svc["key"]
        label = svc["label"]
        desc = svc["description"]
        port = svc.get("default_port", 0)
        port_str = f" — default port {port}" if port else " (desktop app)"

        print(f"\n  {label}{port_str}")
        print(f"    {desc}")

        idx = _ask_choice(
            f"Where does {label} run?",
            [
                "Local — on THIS machine",
                "Remote — on another machine on my network",
                "Skip — I'm not using this",
            ],
            default=0,
            auto_yes=getattr(args, 'yes', False),
        )

        if idx == 0:
            result["local"].append(key)
        elif idx == 2:
            result["skip"].append(key)
        else:
            ip = _ask_with_default(
                f"    IP or hostname of the {label} machine",
                default="",
                auto_yes=getattr(args, 'yes', False),
            ).strip()
            if not ip:
                print(f"    (no IP entered — treating as Skip)")
                result["skip"].append(key)
                continue
            bucket = result["remotes"].setdefault(
                ip, {"services": [], "hostname_hint": ""})
            bucket["services"].append(key)

    # Summary
    print()
    print("=" * 60)
    print("  Summary")
    print("=" * 60)
    if result["local"]:
        print(f"  Local:    {', '.join(result['local'])}")
    if result["skip"]:
        print(f"  Skipped:  {', '.join(result['skip'])}")
    if result["remotes"]:
        print(f"  Remote machines ({len(result['remotes'])}):")
        for ip, info in result["remotes"].items():
            svcs = ", ".join(info["services"])
            print(f"    {ip}  → {svcs}")
    else:
        print("  (no remote services — antenna bat files won't be generated)")

    return result


# ─── Antenna bat/sh generation ────────────────────────────────────────────

_ANTENNA_BAT_TEMPLATE = r"""@echo off
REM Spellcaster Antenna launcher for {remote_ip}
REM ==========================================================
REM  Auto-generated by the Spellcaster installer on {hub_host}.
REM  This .bat runs on the REMOTE machine and turns it into a
REM  Spellcaster antenna — a secure HTTPS service that lets
REM  the Spellcaster hub remotely manage the services below.
REM
REM  Services this machine will advertise:
REM    {services_list}
REM
REM  Hub:   {hub_url}
REM ==========================================================

title Spellcaster Antenna ({remote_ip})
cd /d "%~dp0"

REM ── Check Python is available ──
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   Python is required. Install Python 3.10+ from https://python.org
    echo   then re-run this file.
    echo.
    pause
    exit /b 1
)

REM ── Check git is available (for first-clone and /self-update) ──
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   Git is required. Install Git for Windows from https://git-scm.com
    echo   (it also bundles openssl, which the antenna needs for TLS).
    echo.
    pause
    exit /b 1
)

REM ── Clone the antenna source on first launch, git pull thereafter ──
if not exist antenna\agent.py (
    echo Cloning Spellcaster antenna source...
    git clone --depth 1 https://github.com/laboratoiresonore/spellcaster.git . || goto :clone_failed
) else (
    git pull --ff-only >nul 2>&1
)

REM ── Install the tray UI's pip deps (pystray + Pillow). Best-effort;
REM  the antenna degrades to console mode if these aren't available. ──
python -c "import pystray, PIL" 2>nul || (
    echo Installing tray UI deps (pystray + Pillow)...
    python -m pip install --quiet --disable-pip-version-check pystray Pillow 2>nul
)

REM ── Write config + token on first launch ──
if not exist "%USERPROFILE%\.spellcaster\antenna_config.json" (
    mkdir "%USERPROFILE%\.spellcaster" 2>nul
    python -c "import json, os; d=os.path.expanduser('~/.spellcaster'); os.makedirs(d, exist_ok=True); json.dump({cfg_json}, open(os.path.join(d, 'antenna_config.json'), 'w'), indent=2)"
    echo {token}> "%USERPROFILE%\.spellcaster\antenna_token"
    echo.
    echo   ========================================================
    echo     First-time bootstrap complete for {remote_ip}
    echo   ========================================================
    echo     Services: {services_list}
    echo     Hub:      {hub_url}
    echo     Token:    {token}
    echo     Config:   %%USERPROFILE%%\.spellcaster\antenna_config.json
    echo   ========================================================
    echo.
    echo   Share the token with the hub's installer when prompted, or
    echo   find it later at %%USERPROFILE%%\.spellcaster\antenna_token
    echo.
)

REM ── First-run Windows shortcut setup ──
REM  On the VERY FIRST launch, offer to create a desktop icon, a Start
REM  Menu entry, and optionally add the antenna to Windows startup.
REM  A sentinel file under %%USERPROFILE%%\.spellcaster\ flags that the
REM  prompt has been shown so repeat launches don't nag.
set SHORTCUTS_SENTINEL=%USERPROFILE%\.spellcaster\antenna_shortcuts_done
if not exist "%SHORTCUTS_SENTINEL%" (
    echo.
    python -m antenna.install_shortcuts
    if %errorlevel% equ 0 (
        echo.> "%SHORTCUTS_SENTINEL%"
    )
)

REM ── Launch the antenna ──
REM  `python -m antenna` auto-picks: tray (Windows + pystray installed)
REM  or console (otherwise). Tray gives a system-tray icon + toast
REM  notifications + one-click Start/Stop on ComfyUI, Ollama, Kobold,
REM  hidden-window subprocesses so the user's screen isn't cluttered
REM  with cmd.exe flashes. Everything else — HTTP endpoints, heartbeats,
REM  self-update, auth — is identical.
REM  To force console mode: set SPELLCASTER_ANTENNA_NO_TRAY=1 first.
python -m antenna
goto :end

:clone_failed
echo.
echo   Could not clone the Spellcaster repo.
echo   - Check this machine has internet access.
echo   - If you're behind a firewall, manually run:
echo       git clone https://github.com/laboratoiresonore/spellcaster.git
echo     in this directory, then re-run this .bat.
echo.
pause
exit /b 2

:end
if %errorlevel% neq 0 (
    echo.
    echo   Antenna exited with an error. See output above.
    echo.
    pause
)
"""


_ANTENNA_SH_TEMPLATE = r"""#!/bin/sh
# Spellcaster Antenna launcher for {remote_ip}
# ==========================================================
# Auto-generated by the Spellcaster installer on {hub_host}.
# Services this machine advertises: {services_list}
# Hub: {hub_url}
# ==========================================================

set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null 2>&1 || {{
    echo "Python 3 required. Install from your package manager then re-run."
    exit 1
}}

command -v git >/dev/null 2>&1 || {{
    echo "Git required. Install via your package manager (apt/yum/brew) then re-run."
    exit 1
}}

# Clone on first launch, pull thereafter
if [ ! -f antenna/agent.py ]; then
    echo "Cloning Spellcaster antenna source..."
    git clone --depth 1 https://github.com/laboratoiresonore/spellcaster.git .
else
    git pull --ff-only >/dev/null 2>&1 || true
fi

SP_DIR="$HOME/.spellcaster"
if [ ! -f "$SP_DIR/antenna_config.json" ]; then
    mkdir -p "$SP_DIR"
    python3 -c "import json; json.dump({cfg_json}, open('$SP_DIR/antenna_config.json', 'w'), indent=2)"
    echo "{token}" > "$SP_DIR/antenna_token"
    chmod 600 "$SP_DIR/antenna_token"
    cat <<EOF

  ========================================================
    First-time bootstrap complete for {remote_ip}
  ========================================================
    Services: {services_list}
    Hub:      {hub_url}
    Token:    {token}
    Config:   \$HOME/.spellcaster/antenna_config.json
  ========================================================

  Share the token with the hub's installer when prompted, or
  find it later at \$HOME/.spellcaster/antenna_token

EOF
fi

exec python3 -m antenna
"""


def _detect_hub_ip() -> str:
    """Best-guess LAN IP for use by remote boxes to reach this hub."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _generate_antenna_config(services: list[str], hub_url: str) -> dict[str, Any]:
    """Build the antenna_config.json payload to embed in the launch script."""
    # Keep default port 7334 across all antennas — one box, one agent
    # covers all services. Services list is what the agent advertises.
    return {
        "port": 7334,
        "bind": "0.0.0.0",
        "services": services,
        "hub_url": hub_url,            # new — antenna heartbeats here
        "comfyui_url": "http://127.0.0.1:8188",
        "llm_engine": "",
        "llm_url": "http://127.0.0.1:5001",
        "rate_limit_rpm": 30,
    }


def generate_antenna_files(remotes: dict[str, Any], output_dir: Path,
                            hub_url: str | None = None) -> list[Path]:
    """Write one antenna.bat + .sh per remote machine. Returns the .bat paths.

    output_dir is typically the Spellcaster install root's "antennas/"
    subdir. The user copies individual files to each remote machine.
    """
    if not remotes:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    if hub_url is None:
        hub_ip = _detect_hub_ip()
        hub_url = f"http://{hub_ip}:7777"  # Wizard Guild default port
    hub_host = socket.gethostname()
    hub_host_ip = hub_url.replace("http://", "").replace("https://", "").split(":", 1)[0]

    bat_paths: list[Path] = []
    for remote_ip, info in remotes.items():
        services = info["services"]
        services_list = ", ".join(services)

        # Each machine gets a UNIQUE token — leaking one bat file doesn't
        # compromise other remotes.
        token = secrets.token_urlsafe(32)
        cfg = _generate_antenna_config(services, hub_url)
        # Embed the config as a Python dict literal so the bat can write
        # it to JSON without touching this file's quoting
        cfg_json = repr(cfg)

        subs = {
            "remote_ip": remote_ip,
            "hub_host": hub_host,
            "hub_host_ip": hub_host_ip,
            "hub_url": hub_url,
            "services_list": services_list,
            "cfg_json": cfg_json,
            "token": token,
        }

        safe_ip = remote_ip.replace(".", "_").replace(":", "_")
        bat_name = f"antenna_for_{safe_ip}.bat"
        sh_name = f"antenna_for_{safe_ip}.sh"

        bat_path = output_dir / bat_name
        sh_path = output_dir / sh_name

        bat_path.write_text(_ANTENNA_BAT_TEMPLATE.format(**subs),
                            encoding="utf-8", newline="\r\n")
        sh_path.write_text(_ANTENNA_SH_TEMPLATE.format(**subs),
                           encoding="utf-8", newline="\n")
        if os.name != "nt":
            sh_path.chmod(sh_path.stat().st_mode | stat.S_IEXEC)

        bat_paths.append(bat_path)

    # Write a README next to the bats so the user knows what to do
    readme = output_dir / "README.txt"
    lines = [
        "Spellcaster Antennas",
        "====================",
        "",
        "These files were generated by the Spellcaster installer for",
        "the remote machines you selected.",
        "",
        "How to use:",
        "  1. Copy the antenna_for_<IP>.bat (or .sh on Linux/Mac) to",
        "     the matching remote machine.",
        "  2. Double-click it (or run it from a terminal).",
        "  3. First launch: the antenna downloads itself from this hub,",
        "     installs, and starts. You'll see 'listening on :7334'.",
        "  4. The remote machine now appears in your Spellcaster Guild",
        "     sidebar as a live interface.",
        "",
        f"Hub:  {hub_url}",
        "",
        "Remote machines:",
    ]
    for remote_ip, info in remotes.items():
        lines.append(f"  {remote_ip}  → {', '.join(info['services'])}")
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return bat_paths
