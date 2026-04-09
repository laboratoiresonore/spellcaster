#!/usr/bin/env python3
"""
Wizard Guild - Cross-Platform Build Script
============================================
Builds standalone executables for Windows, macOS, and Linux using PyInstaller.

Usage:
    python build_guild.py                    # Auto-detect platform
    python build_guild.py --platform windows
    python build_guild.py --platform macos
    python build_guild.py --platform linux
    python build_guild.py --all              # Build instructions for all platforms

Output:
    dist/wizard-guild.exe           (Windows)
    dist/Wizard Guild.app           (macOS - .app bundle)
    dist/wizard-guild               (Linux)

The Wizard Guild is a lightweight standalone HTTP server (no external pip
dependencies beyond PyInstaller itself). It bundles:
    - tavern/server.py          HTTP server + API
    - tavern/guild_launcher.py  Entry point with auto-update + instance management
    - tavern/static/            Frontend (HTML, JS, CSS, JSX)
    - scaffold/                 Spellcaster node introspection + workflow parsing
    - scaffold/workflows/       Bundled workflow JSON files
    - _workflows_v2.py          Advanced ComfyUI pipeline builders (optional)
"""

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

# This script lives in tavern/; spellcaster root is one level up
HERE = Path(__file__).resolve().parent          # tavern/
SPELLCASTER_ROOT = HERE.parent                  # spellcaster/
DIST_DIR = SPELLCASTER_ROOT / "dist"

# Data separator for --add-data (';' on Windows, ':' elsewhere)
SEP = os.pathsep


def ensure_pyinstaller():
    """Install PyInstaller if not already available."""
    try:
        import PyInstaller  # noqa: F401
        print(f"  PyInstaller found: {PyInstaller.__version__}")
    except ImportError:
        print("  PyInstaller not found - installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                       check=True)


def generate_browser_jsx():
    """Generate browser-ready JSX from the installer's React component.

    Transforms ES6 module imports into global React references and
    removes the default export, adding a window assignment instead.
    """
    jsx_source = SPELLCASTER_ROOT / "installer" / "signal_bridge_settings.jsx"
    if not jsx_source.exists():
        print("  No signal_bridge_settings.jsx found, skipping JSX generation")
        return

    import re
    jsx_content = jsx_source.read_text(encoding="utf-8")
    jsx_content = jsx_content.replace(
        'import { useState, useCallback, useRef, useEffect, useMemo } '
        'from "react";',
        'const { useState, useCallback, useRef, useEffect, useMemo } '
        '= React;'
    )
    jsx_content = jsx_content.replace(
        'export default function SignalBridgeSettings()',
        'function SignalBridgeSettings()'
    )
    jsx_content += '\nwindow.SignalBridgeSettings = SignalBridgeSettings;\n'
    browser_jsx = HERE / "static" / "travelling_wizard.jsx"
    browser_jsx.write_text(jsx_content, encoding="utf-8")
    print(f"  Generated browser JSX: {browser_jsx.name} "
          f"({len(jsx_content)//1024}KB)")


def build(target_platform: str, onedir: bool = False):
    """Build the Wizard Guild executable for the given platform."""
    print(f"\n{'='*60}")
    print(f"  Building Wizard Guild for {target_platform}")
    print(f"{'='*60}\n")

    # Generate browser-ready JSX before bundling
    generate_browser_jsx()

    # -- Common PyInstaller arguments --
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        # Hidden imports - modules loaded dynamically or conditionally
        "--hidden-import", "scaffold",
        "--hidden-import", "scaffold.meta_wizard",
        "--hidden-import", "scaffold.introspector",
        "--hidden-import", "scaffold.workflow_wizard",
        "--hidden-import", "scaffold.workflow_parser",
        "--hidden-import", "scaffold.comfyui_runner",
        "--hidden-import", "scaffold.presets",
        "--hidden-import", "scaffold.prompt_builder",
        "--hidden-import", "scaffold.wizard",
        "--hidden-import", "scaffold.bridge_launcher",
        "--hidden-import", "scaffold.pipeline_wizard",
        "--hidden-import", "server",
        "--hidden-import", "http.server",
        "--hidden-import", "__future__",
        # Bundle static frontend files
        "--add-data", f"static{SEP}static",
    ]

    # Bundle scaffold package from parent directory
    scaffold_dir = SPELLCASTER_ROOT / "scaffold"
    if scaffold_dir.is_dir():
        cmd += ["--add-data", f"{scaffold_dir}{SEP}scaffold"]
        workflow_dir = scaffold_dir / "workflows"
        if workflow_dir.is_dir():
            cmd += ["--add-data", f"{workflow_dir}{SEP}scaffold/workflows"]

    # Optionally bundle _workflows_v2.py if available
    workflows_v2 = (SPELLCASTER_ROOT / "plugins" / "gimp"
                     / "comfyui-connector" / "_workflows_v2.py")
    if workflows_v2.exists():
        cmd += ["--add-data", f"{workflows_v2}{SEP}."]
        cmd += ["--hidden-import", "_workflows_v2"]

    # Also bundle _nodes.py if it exists (dependency of _workflows_v2)
    nodes_py = (workflows_v2.parent / "_nodes.py"
                if workflows_v2.exists() else None)
    if nodes_py and nodes_py.exists():
        cmd += ["--add-data", f"{nodes_py}{SEP}."]
        cmd += ["--hidden-import", "_nodes"]

    # -- Platform-specific flags --
    if target_platform == "windows":
        icon_path = SPELLCASTER_ROOT / "assets" / "spellcaster.ico"
        icon_flag = (["--icon", str(icon_path)]
                     if icon_path.exists() else [])
        cmd += icon_flag + [
            "--onefile" if not onedir else "--onedir",
            "--console",
            "--name", "wizard-guild",
            "guild_launcher.py",
        ]
        output_name = "wizard-guild.exe"

    elif target_platform == "macos":
        icon_path = SPELLCASTER_ROOT / "assets" / "spellcaster.icns"
        icon_flag = (["--icon", str(icon_path)]
                     if icon_path.exists() else [])
        if onedir:
            cmd += icon_flag + [
                "--onedir",
                "--windowed",
                "--name", "Wizard Guild",
                "--osx-bundle-identifier",
                "com.laboratoiresonore.wizard-guild",
                "guild_launcher.py",
            ]
            output_name = "Wizard Guild.app"
        else:
            cmd += icon_flag + [
                "--onefile",
                "--console",
                "--name", "wizard-guild",
                "--osx-bundle-identifier",
                "com.laboratoiresonore.wizard-guild",
                "guild_launcher.py",
            ]
            output_name = "wizard-guild"

    elif target_platform == "linux":
        cmd += [
            "--onefile" if not onedir else "--onedir",
            "--console",
            "--name", "wizard-guild",
            "guild_launcher.py",
        ]
        output_name = "wizard-guild"

    else:
        print(f"  ERROR: Unknown platform '{target_platform}'")
        sys.exit(1)

    # -- Output directory --
    cmd += ["--distpath", str(DIST_DIR)]

    # -- Execute --
    print("Command:")
    print(f"  {' '.join(str(c) for c in cmd)}")
    print()

    result = subprocess.run(cmd, cwd=str(HERE))

    if result.returncode == 0:
        output_path = DIST_DIR / output_name
        print(f"\n  BUILD SUCCESSFUL")
        print(f"  Output: {output_path}")

        if target_platform == "linux":
            os.chmod(str(output_path), 0o755)
            print(f"\n  Install system-wide:")
            print(f"    sudo cp {output_path} /usr/local/bin/")
        elif target_platform == "macos" and onedir:
            print(f"\n  Create distributable DMG:")
            print(f"    brew install create-dmg")
            print(f'    create-dmg "{output_path}" {DIST_DIR}/')
        elif target_platform == "windows":
            print(f"\n  Distribute: share {output_path}")
    else:
        print(f"\n  BUILD FAILED (exit code {result.returncode})")
        sys.exit(result.returncode)

    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Build Wizard Guild standalone executables",
    )
    parser.add_argument(
        "--platform",
        choices=["windows", "macos", "linux"],
        help="Target platform (default: auto-detect)",
    )
    parser.add_argument(
        "--onedir", action="store_true",
        help="Build as directory instead of single file "
             "(macOS: creates .app bundle)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Print build instructions for all platforms",
    )
    args = parser.parse_args()

    if args.all:
        print("Cross-platform build instructions:")
        print()
        print("  Windows (run on Windows):")
        print("    python build_guild.py --platform windows")
        print()
        print("  macOS (run on macOS):")
        print("    python build_guild.py --platform macos --onedir")
        print("    python build_guild.py --platform macos   # single binary")
        print()
        print("  Linux (run on Linux):")
        print("    python build_guild.py --platform linux")
        print()
        print("  NOTE: PyInstaller cannot cross-compile. Each platform")
        print("  must be built on its native OS.")
        return

    # Auto-detect platform
    target = args.platform
    if not target:
        current_os = platform.system()
        if current_os == "Windows":
            target = "windows"
        elif current_os == "Darwin":
            target = "macos"
        else:
            target = "linux"
        print(f"  Auto-detected platform: {target}")

    ensure_pyinstaller()
    build(target, onedir=args.onedir)


if __name__ == "__main__":
    main()
