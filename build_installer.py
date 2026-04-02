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

# Absolute path to the spellcaster/ directory (where this script lives).
# All relative paths (manifest.json, assets/, plugins/) are resolved from here.
HERE = Path(__file__).resolve().parent


def ensure_pyinstaller():
    """Check that PyInstaller is installed; pip-install it if missing."""
    try:
        import PyInstaller  # noqa
    except ImportError:
        print("PyInstaller not found — installing…")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"],
                       check=True)


def build(target_platform: str, onedir: bool = False):
    """
    Assemble the PyInstaller command and run it.

    Parameters
    ----------
    target_platform : str
        One of "windows", "macos", or "linux".
    onedir : bool
        If True, produce a directory/app-bundle (--onedir) instead of a
        single self-extracting binary (--onefile).

        macOS note: --onedir + --windowed produces a proper .app bundle
        (with Info.plist, icon, etc.) that can be dragged into /Applications.
        --onefile produces a single Mach-O binary with no .app wrapper,
        which is easier to distribute via curl but lacks Finder integration.
    """
    # os.pathsep is the PyInstaller --add-data separator: ';' on Windows, ':' elsewhere
    sep = os.pathsep

    # ----- Base command shared across all platforms --------------------------------
    common = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",                              # overwrite previous build without prompting
        # Hidden imports: modules that PyInstaller's static analysis cannot detect
        # because they are imported dynamically or inside functions.
        "--hidden-import", "tkinter",               # stdlib GUI toolkit
        "--hidden-import", "tkinter.scrolledtext",  # used by installer_gui log pane
        "--hidden-import", "tkinter.ttk",           # themed widgets
        "--hidden-import", "installer_gui",         # our GUI module, loaded at runtime
        "--collect-all", "customtkinter",             # third-party modern tkinter theme (needs data files + submodules)
        "--hidden-import", "darkdetect",             # customtkinter dependency
        "--hidden-import", "PIL",                   # Pillow — image handling for icons/splash
        "--hidden-import", "requests",              # HTTP downloads during installation
        # --add-data bundles non-Python files into the frozen app.
        # Format: "source<sep>dest_folder_inside_bundle"
        "--add-data", f"manifest.json{sep}.",       # install manifest (copied to bundle root)
        "--add-data", f"installer_gui.py{sep}.",    # GUI source (loaded dynamically by install.py)
        "--add-data", f"plugins{sep}plugins",       # plugin directory tree
    ]

    # Conditionally bundle the assets/ folder (icons, images) if it exists
    if "assets" in [p.name for p in HERE.iterdir()]:
        common += ["--add-data", f"assets{sep}assets"]

    # ----- Platform-specific flags -------------------------------------------------

    if target_platform == "windows":
        print("Building Windows installer…")
        icon_flag = []
        icon_path = HERE / "assets" / "spellcaster.ico"  # Windows requires .ico format
        if icon_path.exists():
            icon_flag = ["--icon", str(icon_path)]

        cmd = common + icon_flag + [
            "--onefile" if not onedir else "--onedir",
            "--windowed",                           # suppress console window (use -w / --noconsole equivalent)
            "--name", "spellcaster-installer",      # output filename (PyInstaller appends .exe)
            "install.py",                           # entry-point script
        ]
        output = "dist/spellcaster-installer.exe"

    elif target_platform == "macos":
        print("Building macOS installer…")
        icon_flag = []
        icon_path = HERE / "assets" / "spellcaster.icns"  # macOS requires .icns format
        if icon_path.exists():
            icon_flag = ["--icon", str(icon_path)]

        if onedir:
            # --onedir + --windowed on macOS produces a proper .app bundle
            # (Spellcaster Installer.app/) with Info.plist, icon, and all
            # resources inside Contents/MacOS/ and Contents/Resources/.
            # This is the preferred format for drag-and-drop distribution.
            cmd = common + icon_flag + [
                "--onedir",
                "--windowed",
                "--name", "Spellcaster Installer",  # spaces allowed — becomes the .app name
                "--osx-bundle-identifier", "com.laboratoiresonore.spellcaster",
                "install.py",
            ]
            output = "dist/Spellcaster Installer.app"
        else:
            # --onefile on macOS produces a single Mach-O binary (no .app wrapper).
            # Simpler to distribute (e.g. curl download) but no Finder icon or
            # bundle metadata. Still runs windowed (no terminal needed).
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
        # No icon flag for Linux — .ico/.icns are not used by the OS.
        cmd = common + [
            "--onefile" if not onedir else "--onedir",
            "--windowed",                           # still suppresses any console attachment
            "--name", "spellcaster-installer",
            "install.py",
        ]
        output = "dist/spellcaster-installer"

    else:
        print(f"Unknown platform: {target_platform}")
        sys.exit(1)

    # Log the full command for debugging / CI logs
    print("Command:", " ".join(str(c) for c in cmd))
    print()

    # Run PyInstaller from the spellcaster/ directory so relative data paths resolve
    result = subprocess.run(cmd, cwd=str(HERE))

    # ----- Post-build summary ------------------------------------------------------
    if result.returncode == 0:
        print(f"\nBuild complete: {output}")
        print(f"  Full path: {HERE / output}")

        # Print platform-specific distribution hints
        if target_platform == "macos" and onedir:
            print("\nTo create a distributable DMG:")
            print("  brew install create-dmg")
            print('  create-dmg "dist/Spellcaster Installer.app" dist/')
        elif target_platform == "windows":
            print("\nTo distribute: share dist/spellcaster-installer.exe")
        else:
            print(f"\nTo distribute: share {output}")
    else:
        print(f"\nBuild failed (exit code {result.returncode})")
        sys.exit(result.returncode)


def build_manual_update():
    """Build the lightweight manual update/repair tool.

    This is a simple console app with no bundled data — it downloads
    everything from GitHub at runtime.  Produces a small standalone exe.
    """
    print("Building manual update tool…")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--console",
        "--name", "spellcaster-manual-update",
        "manual_update.py",
    ]
    # Add icon on Windows if available
    icon_path = HERE / "assets" / "spellcaster.ico"
    if icon_path.exists():
        cmd += ["--icon", str(icon_path)]

    print("Command:", " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, cwd=str(HERE))
    if result.returncode == 0:
        print("\nManual update tool built: dist/spellcaster-manual-update")
    else:
        print(f"\nManual update build failed (exit code {result.returncode})")
    return result.returncode


def main():
    """Parse CLI arguments, auto-detect platform if needed, and kick off the build."""
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
    parser.add_argument(
        "--update-tool", action="store_true",
        help="Also build the manual update/repair tool",
    )
    args = parser.parse_args()

    # Auto-detect platform from the current OS if not explicitly provided
    target = args.platform
    if not target:
        current_os = platform.system()  # returns "Windows", "Darwin", or "Linux"
        if current_os == "Windows":
            target = "windows"
        elif current_os == "Darwin":
            target = "macos"
        else:
            target = "linux"
        print(f"Auto-detected platform: {target}")

    ensure_pyinstaller()
    build(target, onedir=args.onedir)

    if args.update_tool:
        build_manual_update()


if __name__ == "__main__":
    main()
