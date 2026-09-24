#!/usr/bin/env python3
"""
Wizard Guild Launcher — thin wrapper that runs start_guild.bat.

This is the entry point for Wizard_Guild.exe (built by PyInstaller).
It locates and runs tavern/start_guild.bat, which handles Python
detection, config, and the full guild_launcher.py startup sequence.
"""

import os
import sys
import subprocess


def main():
    # Find the tavern/ directory relative to this exe (or script)
    if getattr(sys, '_MEIPASS', None):
        # Running from PyInstaller bundle — exe sits at repo root
        base = os.path.dirname(sys.executable)
    else:
        # Running from source — this file is in tavern/
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    bat = os.path.join(base, 'tavern', 'start_guild.bat')

    if not os.path.isfile(bat):
        # Maybe we're already inside tavern/
        bat = os.path.join(base, 'start_guild.bat')

    if not os.path.isfile(bat):
        print(f"ERROR: Cannot find start_guild.bat")
        print(f"  Searched: {os.path.join(base, 'tavern')}")
        print(f"  and:      {base}")
        input("Press Enter to exit...")
        sys.exit(1)

    # Run the bat in its own directory.
    # CREATE_NO_WINDOW avoids allocating a fresh conhost.exe for the child
    # cmd — it inherits the parent's console instead. Without this, a single
    # user launch stacked three conhost instances (Wizard Guild.bat →
    # wizard-guild.exe → cmd /c start_guild.bat), and the third failed with
    # 0xc000012d (STATUS_COMMITMENT_LIMIT) under memory pressure from
    # co-tenants like ComfyUI + LM Studio + GIMP. See issue #175.
    creationflags = 0
    if sys.platform == 'win32':
        # CREATE_NO_WINDOW = 0x08000000 (added to subprocess in 3.7)
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    subprocess.run(['cmd', '/c', bat], cwd=os.path.dirname(bat),
                   creationflags=creationflags)


if __name__ == '__main__':
    main()
