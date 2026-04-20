"""ComfyUI-Spellcaster — Architecture-aware nodes for AI image generation.

ONE SOURCE OF TRUTH: All architecture definitions, model detection,
prompt enhancement, and workflow construction live in spellcaster_core/.
GIMP plugin, Darktable plugin, and Wizard Guild all import from there.

Nodes:
  - SpellcasterLoader:        Auto-detect arch, load MODEL + CLIP + VAE
  - SpellcasterPromptEnhance: LLM-powered prompt rewriting per architecture
  - SpellcasterSampler:       Auto-select KSampler vs custom_advanced
  - SpellcasterOutput:        VAE decode + privacy-aware save
"""

import os
import sys
import textwrap

# Ensure spellcaster_core is importable (it lives inside this package)
_pack_dir = os.path.dirname(os.path.abspath(__file__))
if _pack_dir not in sys.path:
    sys.path.insert(0, _pack_dir)

from .nodes.loader import SpellcasterLoader
from .nodes.prompt import SpellcasterPromptEnhance
from .nodes.sampler import SpellcasterSampler
from .nodes.output import SpellcasterOutput

# Presence broker — lets sibling plugins (GIMP, Darktable, ST, Resolve)
# discover each other through ComfyUI instead of requiring the Wizard
# Guild to be running. See AUDIT_CROSS_APP_DISCOVERY.md §6.5.
from . import presence as _presence


NODE_CLASS_MAPPINGS = {
    "SpellcasterLoader": SpellcasterLoader,
    "SpellcasterPromptEnhance": SpellcasterPromptEnhance,
    "SpellcasterSampler": SpellcasterSampler,
    "SpellcasterOutput": SpellcasterOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SpellcasterLoader": "Spellcaster Loader (Auto-Arch)",
    "SpellcasterPromptEnhance": "Spellcaster Prompt Enhance (LLM)",
    "SpellcasterSampler": "Spellcaster Sampler (Auto-Config)",
    "SpellcasterOutput": "Spellcaster Output (Privacy)",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


# ── Full-suite installer nudge ───────────────────────────────────────
# When someone installs via ComfyUI Manager (git clone), they only get
# the nodes. The full Spellcaster suite (Wizard Guild, GIMP + Darktable
# plugins, desktop shortcut, model downloader) requires running the
# installer. We detect this and:
#   1. Drop a clickable .bat into custom_nodes/ so it's obvious
#   2. Print a console banner
#   3. Signal the web frontend to show a toast (via a marker file)

def _check_full_suite_installed():
    """Return True if the full Spellcaster suite is installed."""
    # The installer writes spellcaster_settings.json when it runs.
    # If that file exists anywhere up the tree, the suite is installed.
    # Also check for the tavern/ dir (Wizard Guild) as a secondary signal.
    comfyui_root = os.path.dirname(os.path.dirname(_pack_dir))  # custom_nodes/../
    settings_path = os.path.join(comfyui_root, "spellcaster_settings.json")
    tavern_marker = os.path.join(_pack_dir, ".suite_installed")
    return os.path.exists(settings_path) or os.path.exists(tavern_marker)


def _drop_installer_bat():
    """Create a convenient .bat in the custom_nodes folder that clones
    the full repo and runs the installer. Idempotent — skips if exists."""
    custom_nodes_dir = os.path.dirname(_pack_dir)
    bat_path = os.path.join(custom_nodes_dir, "Install_Spellcaster_Suite.bat")
    if os.path.exists(bat_path):
        return bat_path

    bat_content = textwrap.dedent(r"""
        @echo off
        title Spellcaster Suite Installer
        echo.
        echo  ============================================
        echo   Spellcaster Suite Installer
        echo  ============================================
        echo.
        echo  This will install the full Spellcaster suite:
        echo    - Wizard Guild (AI chat interface)
        echo    - GIMP 3 plugin (ComfyUI connector)
        echo    - Darktable plugin (ComfyUI connector)
        echo    - Desktop shortcuts
        echo    - Model downloader
        echo.
        echo  Your ComfyUI Spellcaster nodes are already installed.
        echo  This adds the extra tools on top.
        echo.
        pause

        set "INSTALL_DIR=%~dp0_spellcaster_installer"

        :: Check if git is available
        where git >nul 2>nul
        if errorlevel 1 (
            echo.
            echo  [!] Git not found. Trying direct download...
            echo.
            goto :direct_download
        )

        :: Clone the full repo
        if not exist "%INSTALL_DIR%" (
            echo  Cloning Spellcaster repository...
            git clone https://github.com/laboratoiresonore/spellcaster.git "%INSTALL_DIR%"
        ) else (
            echo  Updating existing Spellcaster install...
            cd /d "%INSTALL_DIR%" && git pull
        )
        goto :run_installer

        :direct_download
        if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
        echo  Downloading installer...
        powershell -Command "Invoke-WebRequest -Uri 'https://github.com/laboratoiresonore/spellcaster/archive/refs/heads/main.zip' -OutFile '%INSTALL_DIR%\spellcaster.zip'"
        echo  Extracting...
        powershell -Command "Expand-Archive -Force '%INSTALL_DIR%\spellcaster.zip' '%INSTALL_DIR%'"
        :: The zip extracts to spellcaster-main/
        if exist "%INSTALL_DIR%\spellcaster-main\installer\install.py" (
            move "%INSTALL_DIR%\spellcaster-main\*" "%INSTALL_DIR%\" >nul 2>nul
            rmdir "%INSTALL_DIR%\spellcaster-main" 2>nul
        )

        :run_installer
        echo.

        :: Find Python
        where python >nul 2>nul
        if not errorlevel 1 (
            set "PY=python"
        ) else (
            where python3 >nul 2>nul
            if not errorlevel 1 (
                set "PY=python3"
            ) else (
                echo  [!] Python not found. Please install Python 3.10+ and try again.
                pause
                exit /b 1
            )
        )

        :: Run the installer, auto-detecting ComfyUI path from our location
        set "COMFYUI_ROOT=%~dp0.."
        echo  Running installer...
        %PY% "%INSTALL_DIR%\installer\install.py" --comfyui "%COMFYUI_ROOT%"

        echo.
        echo  Done! You can delete this bat file now.
        echo.
        pause
    """).lstrip()

    try:
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write(bat_content)
        return bat_path
    except Exception as e:
        print(f"\033[33m[Spellcaster]\033[0m Could not create installer bat: {e}")
        return None


def _write_web_marker(installed: bool):
    """Write a tiny JSON marker that the web extension reads to decide
    whether to show the install toast. Lives in our web/ dir so it's
    served automatically by ComfyUI."""
    marker_path = os.path.join(_pack_dir, "web", "spellcaster_status.json")
    try:
        import json
        with open(marker_path, 'w', encoding='utf-8') as f:
            json.dump({"suite_installed": installed}, f)
    except Exception:
        pass


# Run the check at import time (ComfyUI startup)
_suite_ok = _check_full_suite_installed()
_write_web_marker(_suite_ok)

# Register the presence broker routes on ComfyUI's HTTP server. Silent
# no-op if PromptServer isn't available (bare-import contexts).
_presence_ok = _presence.install()

if _suite_ok:
    print("\033[36m[Spellcaster]\033[0m Node pack loaded — 4 nodes registered"
          + ("  •  presence broker ON" if _presence_ok else ""))
else:
    _bat = _drop_installer_bat()
    print("")
    print("\033[36m" + "=" * 58 + "\033[0m")
    print("\033[36m  [Spellcaster]\033[0m Nodes loaded — 4 nodes registered")
    print("")
    print("  \033[33mFull suite not detected.\033[0m")
    print("  For \033[1mWizard Guild\033[0m, \033[1mGIMP/Darktable plugins\033[0m,")
    print("  desktop shortcuts, and the model downloader:")
    print("")
    if _bat:
        print(f"    \033[32m>>> Run: {os.path.basename(_bat)}\033[0m")
        print(f"    \033[90m    (in your custom_nodes folder)\033[0m")
    else:
        print("    \033[32m>>> python install.py\033[0m")
        print("    \033[90m    github.com/laboratoiresonore/spellcaster\033[0m")
    print("")
    print("\033[36m" + "=" * 58 + "\033[0m")
    print("")
