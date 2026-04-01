#!/usr/bin/env python3
"""
Spellcaster Installer Builder
==============================
Builds a standalone installer binary using PyInstaller.

Usage:
    python build_installer.py              # Auto-detect platform
    python build_installer.py --platform windows
    python build_installer.py --platform macos
    python build_installer.py --platform linux
    python build_installer.py --onedir     # Folder instead of single file

Output:
    dist/spellcaster-installer.exe     (Windows)
    dist/"Spellcaster Installer.app"   (macOS — app bundle)
    dist/spellcaster-installer         (Linux)
"""

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa
    except ImportError:
        print("PyInstaller not found — installing…")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                       check=True)


def build(target_platform: str, onedir: bool = False):
    sep = os.pathsep

    common = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.scrolledtext",
        "--hidden-import", "tkinter.ttk",
        "--add-data", f"manifest.json{sep}.",
        "--add-data", f"plugins{sep}plugins",
    ]

    if "assets" in [p.name for p in HERE.iterdir()]:
        common += ["--add-data", f"assets{sep}assets"]

    if target_platform == "windows":
        print("Building Windows installer…")
        icon_flag = []
        icon_path = HERE / "assets" / "spellcaster.ico"
        if icon_path.exists():
            icon_flag = ["--icon", str(icon_path)]

        cmd = common + icon_flag + [
            "--onefile" if not onedir else "--onedir",
            "--console",
            "--name", "spellcaster-installer",
            "install.py",
        ]
        output = "dist/spellcaster-installer.exe"

    elif target_platform == "macos":
        print("Building macOS installer…")
        icon_flag = []
        icon_path = HERE / "assets" / "spellcaster.icns"
        if icon_path.exists():
            icon_flag = ["--icon", str(icon_path)]

        if onedir:
            # Windowed .app bundle
            cmd = common + icon_flag + [
                "--onedir",
                "--windowed",
                "--name", "Spellcaster Installer",
                "--osx-bundle-identifier", "com.laboratoiresonore.spellcaster",
                "install.py",
            ]
            output = "dist/Spellcaster Installer.app"
        else:
            # Single binary (runs in Terminal — simpler for users who curl|python)
            cmd = common + icon_flag + [
                "--onefile",
                "--windowed",
                "--name", "spellcaster-installer",
                "--osx-bundle-identifier", "com.laboratoiresonore.spellcaster",
                "install.py",
            ]
            output = "dist/spellcaster-installer"

    elif target_platform == "linux":
        print("Building Linux installer…")
        cmd = common + [
            "--onefile" if not onedir else "--onedir",
            "--windowed",
            "--name", "spellcaster-installer",
            "install.py",
        ]
        output = "dist/spellcaster-installer"

    else:
        print(f"Unknown platform: {target_platform}")
        sys.exit(1)

    print("Command:", " ".join(str(c) for c in cmd))
    print()

    result = subprocess.run(cmd, cwd=str(HERE))

    if result.returncode == 0:
        print(f"\n✓ Build complete: {output}")
        print(f"  Full path: {HERE / output}")

        if target_platform == "macos" and onedir:
            print("\nTo create a distributable DMG:")
            print("  brew install create-dmg")
            print('  create-dmg "dist/Spellcaster Installer.app" dist/')
        elif target_platform == "windows":
            print("\nTo distribute: share dist/spellcaster-installer.exe")
        else:
            print(f"\nTo distribute: share {output}")
    else:
        print(f"\n✗ Build failed (exit code {result.returncode})")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Build Spellcaster standalone installer")
    parser.add_argument(
        "--platform",
        choices=["windows", "macos", "linux"],
        help="Target platform (default: auto-detect current OS)",
    )
    parser.add_argument(
        "--onedir", action="store_true",
        help="Build a folder instead of a single file (macOS: creates .app bundle)",
    )
    args = parser.parse_args()

    target = args.platform
    if not target:
        sys = platform.system()
        if sys == "Windows":
            target = "windows"
        elif sys == "Darwin":
            target = "macos"
        else:
            target = "linux"
        print(f"Auto-detected platform: {target}")

    ensure_pyinstaller()
    build(target, onedir=args.onedir)


if __name__ == "__main__":
    main()
