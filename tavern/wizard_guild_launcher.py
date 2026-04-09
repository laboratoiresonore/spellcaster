#!/usr/bin/env python3
"""
Wizard Guild Launcher — entry point for the standalone .exe
============================================================
Thin wrapper that bootstraps the guild_launcher module from the
correct relative paths, whether running from source or from a
PyInstaller --onefile bundle.

This file exists so PyInstaller has a clean entry point that
doesn't interfere with the guild_launcher's own module-level code.
"""

import os
import sys

def main():
    # Resolve paths: PyInstaller extracts to _MEIPASS, source runs from tavern/
    if getattr(sys, '_MEIPASS', None):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    # Ensure tavern/ and parent (for scaffold/) are on sys.path
    tavern_dir = base if os.path.isfile(os.path.join(base, 'server.py')) else os.path.join(base, 'tavern')
    parent_dir = os.path.dirname(tavern_dir)

    for d in [tavern_dir, parent_dir]:
        if d not in sys.path:
            sys.path.insert(0, d)

    # Also add the GIMP plugin dir for _workflows_v2 imports
    plugin_dir = os.path.join(parent_dir, 'plugins', 'gimp', 'comfyui-connector')
    if os.path.isdir(plugin_dir) and plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)

    # Change to tavern/ so relative paths work
    os.chdir(tavern_dir)

    # Import and run the real launcher
    import guild_launcher
    guild_launcher.main()


if __name__ == '__main__':
    main()
