#!/usr/bin/env python3
"""
Spellcaster SillyTavern Patcher
================================
Installs the Spellcaster server plugin and UI extension into a
SillyTavern installation. Safe to run multiple times (idempotent).

Usage:
    python patch_sillytavern.py                          # Auto-detect ST location
    python patch_sillytavern.py --st-dir /path/to/ST     # Explicit path
    python patch_sillytavern.py --st-dir /path/to/ST --comfyui-url http://192.168.1.50:8188
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# Resolve paths relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PLUGIN_SRC = REPO_ROOT / "plugins" / "sillytavern" / "spellcaster-st"


def find_sillytavern(explicit_dir=None):
    """Locate a SillyTavern installation.

    Searches common locations for a directory containing server.js.
    Returns the path or None.
    """
    if explicit_dir:
        d = Path(explicit_dir).resolve()
        if (d / "server.js").is_file():
            return d
        print(f"  WARNING: {d} has no server.js")

    home = Path.home()
    candidates = [
        # Sibling directories
        REPO_ROOT.parent / "whimweaver-st",
        REPO_ROOT.parent / "SillyTavern",
        REPO_ROOT.parent / "sillytavern",
        REPO_ROOT / "sillytavern",
        # Common locations
        home / "SillyTavern",
        home / "Documents" / "SillyTavern",
        home / "Desktop" / "SillyTavern",
    ]

    for c in candidates:
        if c.is_dir() and (c / "server.js").is_file():
            return c
    return None


def install_server_plugin(st_dir, comfyui_url=None):
    """Install the Spellcaster server plugin into ST's plugins directory.

    Creates: ST/plugins/spellcaster/index.js + package.json
    """
    plugin_dest = st_dir / "plugins" / "spellcaster"
    plugin_dest.mkdir(parents=True, exist_ok=True)

    # Copy server plugin
    src_js = PLUGIN_SRC / "server-plugin.js"
    if not src_js.exists():
        print(f"  ERROR: Server plugin source not found: {src_js}")
        return False

    dest_js = plugin_dest / "index.js"
    shutil.copy2(src_js, dest_js)
    print(f"  Installed: {dest_js}")

    # Write package.json (ESM module)
    pkg = {
        "name": "spellcaster",
        "version": "2.0.0",
        "description": "Spellcaster ComfyUI integration — living scenes, restyling, autonomous generation",
        "main": "index.js",
        "type": "module",
        "author": "Laboratoire Sonore",
        "license": "GPL-2.0",
    }
    pkg_path = plugin_dest / "package.json"
    pkg_path.write_text(json.dumps(pkg, indent=4), encoding="utf-8")
    print(f"  Installed: {pkg_path}")

    # If ComfyUI URL provided, patch it into the plugin
    if comfyui_url:
        content = dest_js.read_text(encoding="utf-8")
        content = content.replace(
            "let COMFYUI_URL = 'http://127.0.0.1:8188'",
            f"let COMFYUI_URL = '{comfyui_url}'"
        )
        dest_js.write_text(content, encoding="utf-8")
        print(f"  Patched ComfyUI URL: {comfyui_url}")

    return True


def install_ui_extension(st_dir):
    """Install the Spellcaster UI extension into ST's extensions directory.

    Creates: ST/data/default-user/extensions/spellcaster-st/
    """
    ext_dest = st_dir / "data" / "default-user" / "extensions" / "spellcaster-st"
    ext_dest.mkdir(parents=True, exist_ok=True)

    files = ["index.js", "manifest.json", "styles.css"]
    for fname in files:
        src = PLUGIN_SRC / fname
        if src.exists():
            shutil.copy2(src, ext_dest / fname)
            print(f"  Installed: {ext_dest / fname}")
        else:
            print(f"  WARNING: Source not found: {src}")

    return True


def enable_server_plugins(st_dir):
    """Ensure enableServerPlugins is true in ST's config.yaml."""
    config_path = st_dir / "config.yaml"
    if not config_path.exists():
        print("  WARNING: config.yaml not found — plugins may not load")
        return

    content = config_path.read_text(encoding="utf-8")
    if "enableServerPlugins: false" in content:
        content = content.replace(
            "enableServerPlugins: false",
            "enableServerPlugins: true"
        )
        config_path.write_text(content, encoding="utf-8")
        print("  Enabled server plugins in config.yaml")
    elif "enableServerPlugins: true" in content:
        print("  Server plugins already enabled in config.yaml")
    else:
        print("  WARNING: enableServerPlugins not found in config.yaml")


def verify_installation(st_dir):
    """Verify the installation is correct."""
    checks = [
        ("Server plugin", st_dir / "plugins" / "spellcaster" / "index.js"),
        ("Server package.json", st_dir / "plugins" / "spellcaster" / "package.json"),
        ("UI extension", st_dir / "data" / "default-user" / "extensions" / "spellcaster-st" / "index.js"),
        ("UI manifest", st_dir / "data" / "default-user" / "extensions" / "spellcaster-st" / "manifest.json"),
        ("UI styles", st_dir / "data" / "default-user" / "extensions" / "spellcaster-st" / "styles.css"),
    ]

    all_ok = True
    print("\n  Verification:")
    for name, path in checks:
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        icon = "OK" if exists and size > 100 else "MISSING"
        print(f"    [{icon}] {name}: {path.name} ({size} bytes)")
        if not exists or size < 100:
            all_ok = False

    return all_ok


def patch_sillytavern(st_dir, comfyui_url=None):
    """Full patching pipeline: server plugin + UI extension + config."""
    print(f"\n  SillyTavern: {st_dir}")
    print(f"  Spellcaster source: {PLUGIN_SRC}")
    print()

    print("  Installing server plugin...")
    if not install_server_plugin(st_dir, comfyui_url):
        return False

    print("\n  Installing UI extension...")
    if not install_ui_extension(st_dir):
        return False

    print("\n  Configuring...")
    enable_server_plugins(st_dir)

    ok = verify_installation(st_dir)
    if ok:
        print("\n  Spellcaster installed into SillyTavern.")
        print("  Restart SillyTavern to activate the plugin.")
    else:
        print("\n  WARNING: Installation incomplete — check errors above.")

    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Install Spellcaster plugin into SillyTavern")
    parser.add_argument("--st-dir", type=str, default=None,
                        help="Path to SillyTavern directory")
    parser.add_argument("--comfyui-url", type=str, default=None,
                        help="ComfyUI server URL to configure")
    args = parser.parse_args()

    print("=" * 50)
    print("  Spellcaster SillyTavern Patcher")
    print("=" * 50)

    st_dir = find_sillytavern(args.st_dir)
    if not st_dir:
        print("\n  SillyTavern not found.")
        print("  Use --st-dir to specify the location.")
        sys.exit(1)

    ok = patch_sillytavern(st_dir, args.comfyui_url)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
