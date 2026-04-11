#!/usr/bin/env python3
"""Spellcaster Launcher — single entry point for the entire app.

First run: opens the Wizard Guild with the Installer Wizard (setup guide).
After install: shows an app selector with detected/installed apps.

Options:
  - Wizard Guild (always available)
  - GIMP (if detected and Spellcaster plugin installed)
  - Darktable (if detected and Spellcaster plugin installed)
  - SillyTavern (if detected and Spellcaster extension installed)
  - Settings (open Travelling Wizard config)
"""

import os
import sys
import subprocess
import platform
import json
import webbrowser
import time

# ═══════════════════════════════════════════════════════════════════════
#  Paths
# ═══════════════════════════════════════════════════════════════════════

if getattr(sys, 'frozen', False):
    BUNDLE_DIR = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

TAVERN_DIR = os.path.join(BUNDLE_DIR, "tavern")
CONFIG_PATH = os.path.join(TAVERN_DIR, "guild_config.json")
STATE_DIR = os.path.join(TAVERN_DIR, ".guild_state")


def _load_config():
    for p in [CONFIG_PATH, os.path.join(BUNDLE_DIR, "guild_config.json")]:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


# ═══════════════════════════════════════════════════════════════════════
#  App detection
# ═══════════════════════════════════════════════════════════════════════

def _detect_gimp():
    """Check if GIMP is installed and has the Spellcaster plugin."""
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        for ver in ["3.2", "3.0"]:
            plugin = os.path.join(appdata, "GIMP", ver, "plug-ins",
                                  "comfyui-connector", "comfyui-connector.py")
            if os.path.isfile(plugin):
                return {"installed": True, "version": ver, "plugin": True}
    elif platform.system() == "Darwin":
        plugin = os.path.expanduser(
            "~/Library/Application Support/GIMP/3.0/plug-ins/comfyui-connector/comfyui-connector.py")
        if os.path.isfile(plugin):
            return {"installed": True, "plugin": True}
    else:
        for ver in ["3.2", "3.0"]:
            plugin = os.path.expanduser(
                f"~/.config/GIMP/{ver}/plug-ins/comfyui-connector/comfyui-connector.py")
            if os.path.isfile(plugin):
                return {"installed": True, "version": ver, "plugin": True}
    return {"installed": False, "plugin": False}


def _detect_darktable():
    """Check if Darktable has the Spellcaster plugin."""
    if platform.system() == "Windows":
        plugin = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                              "darktable", "lua", "contrib", "comfyui_connector.lua")
    elif platform.system() == "Darwin":
        plugin = os.path.expanduser(
            "~/Library/Application Support/darktable/lua/contrib/comfyui_connector.lua")
    else:
        plugin = os.path.expanduser(
            "~/.config/darktable/lua/contrib/comfyui_connector.lua")
    return {"installed": os.path.isfile(plugin), "plugin": os.path.isfile(plugin)}


def _detect_sillytavern():
    """Check if SillyTavern is installed with Spellcaster extension."""
    config = _load_config()
    st_dir = config.get("sillytavern_dir", "")
    if st_dir and os.path.isdir(st_dir):
        plugin = os.path.join(st_dir, "plugins", "spellcaster", "index.js")
        return {"installed": True, "dir": st_dir, "plugin": os.path.isfile(plugin)}
    # Search common locations
    home = os.path.expanduser("~")
    for candidate in [
        os.path.join(home, "SillyTavern"),
        os.path.join(home, "Documents", "SillyTavern"),
        os.path.join(BUNDLE_DIR, "..", "SillyTavern"),
    ]:
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "server.js")):
            return {"installed": True, "dir": candidate, "plugin": False}
    return {"installed": False}


def _is_first_run():
    """Check if this is the first run (no calibration done)."""
    return not os.path.exists(os.path.join(STATE_DIR, "calibration_matrix.json"))


# ═══════════════════════════════════════════════════════════════════════
#  Launch actions
# ═══════════════════════════════════════════════════════════════════════

def _launch_guild():
    """Start the Wizard Guild server and open browser."""
    launcher = os.path.join(TAVERN_DIR, "guild_launcher.py")
    if os.path.isfile(launcher):
        subprocess.Popen([sys.executable, launcher], cwd=TAVERN_DIR)
        time.sleep(3)
        config = _load_config()
        port = config.get("port", 7777)
        webbrowser.open(f"http://127.0.0.1:{port}")
    else:
        print("ERROR: guild_launcher.py not found")


def _launch_gimp():
    """Launch GIMP."""
    if platform.system() == "Windows":
        # Try common GIMP paths
        for path in [
            r"C:\Program Files\GIMP 3\bin\gimp-3.2.exe",
            r"C:\Program Files\GIMP 3\bin\gimp-3.0.exe",
            r"C:\Program Files\GIMP\bin\gimp-3.2.exe",
        ]:
            if os.path.isfile(path):
                subprocess.Popen([path])
                return
        os.startfile("gimp")  # Let Windows find it
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", "-a", "GIMP"])
    else:
        subprocess.Popen(["gimp"])


def _launch_darktable():
    """Launch Darktable."""
    if platform.system() == "Windows":
        for path in [
            r"C:\Program Files\darktable\bin\darktable.exe",
        ]:
            if os.path.isfile(path):
                subprocess.Popen([path])
                return
        os.startfile("darktable")
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", "-a", "darktable"])
    else:
        subprocess.Popen(["darktable"])


def _launch_sillytavern():
    """Launch SillyTavern."""
    st = _detect_sillytavern()
    if not st.get("dir"):
        print("SillyTavern not found")
        return
    st_dir = st["dir"]
    if platform.system() == "Windows":
        bat = os.path.join(st_dir, "start.bat")
        if os.path.isfile(bat):
            subprocess.Popen(["cmd", "/c", "start", "", bat], cwd=st_dir)
        else:
            subprocess.Popen(["node", "server.js"], cwd=st_dir)
    else:
        sh = os.path.join(st_dir, "start.sh")
        if os.path.isfile(sh):
            subprocess.Popen(["bash", sh], cwd=st_dir)
        else:
            subprocess.Popen(["node", "server.js"], cwd=st_dir)
    time.sleep(3)
    webbrowser.open("http://127.0.0.1:8000")


# ═══════════════════════════════════════════════════════════════════════
#  CLI menu (fallback when no GUI available)
# ═══════════════════════════════════════════════════════════════════════

def cli_menu():
    """Text-based app selector for terminal use."""
    first_run = _is_first_run()
    gimp = _detect_gimp()
    dt = _detect_darktable()
    st = _detect_sillytavern()

    print()
    print("  ========================================")
    print("    Spellcaster")
    print("  ========================================")
    print()

    if first_run:
        print("  First run detected! Starting setup wizard...")
        print()
        _launch_guild()
        return

    options = []

    options.append(("Wizard Guild", _launch_guild, "AI chat interface"))
    if gimp["installed"] and gimp.get("plugin"):
        options.append(("GIMP", _launch_gimp, "Image editor + Spellcaster plugin"))
    if dt["installed"] and dt.get("plugin"):
        options.append(("Darktable", _launch_darktable, "Photo editor + Spellcaster plugin"))
    if st.get("installed"):
        label = "SillyTavern" + (" + Spellcaster" if st.get("plugin") else "")
        options.append((label, _launch_sillytavern, "AI character chat"))

    for i, (name, _, desc) in enumerate(options):
        print(f"  {i+1}. {name}")
        print(f"     {desc}")
        print()

    print(f"  0. Exit")
    print()

    try:
        choice = input("  Choose [1]: ").strip()
        if not choice:
            choice = "1"
        if choice == "0":
            return
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            print(f"\n  Launching {options[idx][0]}...")
            options[idx][1]()
        else:
            print("  Invalid choice")
    except (ValueError, EOFError, KeyboardInterrupt):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  GUI menu (tkinter — built into Python)
# ═══════════════════════════════════════════════════════════════════════

def gui_menu():
    """Graphical app selector using tkinter."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return cli_menu()

    first_run = _is_first_run()
    gimp = _detect_gimp()
    dt = _detect_darktable()
    st = _detect_sillytavern()

    if first_run:
        _launch_guild()
        return

    root = tk.Tk()
    root.title("Spellcaster")
    root.geometry("400x500")
    root.configure(bg="#0e0d18")
    root.resizable(False, False)

    # Center on screen
    root.update_idletasks()
    x = (root.winfo_screenwidth() - 400) // 2
    y = (root.winfo_screenheight() - 500) // 2
    root.geometry(f"+{x}+{y}")

    # Title
    title = tk.Label(root, text="Spellcaster", font=("Segoe UI", 24, "bold"),
                     fg="#B246F2", bg="#0e0d18")
    title.pack(pady=(30, 5))

    subtitle = tk.Label(root, text="Choose your workspace", font=("Segoe UI", 11),
                        fg="#8F8C9E", bg="#0e0d18")
    subtitle.pack(pady=(0, 20))

    # Button style
    btn_style = {"font": ("Segoe UI", 13), "width": 30, "height": 2,
                 "bg": "#1a1730", "fg": "#E2DFEB", "activebackground": "#2a2548",
                 "activeforeground": "#fff", "relief": "flat", "cursor": "hand2",
                 "bd": 0}

    def make_btn(text, desc, command, enabled=True):
        frame = tk.Frame(root, bg="#0e0d18")
        frame.pack(pady=4, padx=30, fill="x")
        btn = tk.Button(frame, text=text, command=lambda: [command(), root.destroy()],
                        **btn_style)
        if not enabled:
            btn.configure(state="disabled", fg="#4a4760")
        btn.pack(fill="x")
        lbl = tk.Label(frame, text=desc, font=("Segoe UI", 9),
                       fg="#6b6881", bg="#0e0d18")
        lbl.pack()

    make_btn("Wizard Guild", "AI-powered image & video generation",
             _launch_guild)

    make_btn("GIMP", "Image editor with Spellcaster plugin",
             _launch_gimp, enabled=gimp.get("plugin", False))

    make_btn("Darktable", "Photo editor with Spellcaster plugin",
             _launch_darktable, enabled=dt.get("plugin", False))

    make_btn("SillyTavern", "AI character chat with 13 wizards",
             _launch_sillytavern, enabled=st.get("installed", False))

    # Exit
    exit_btn = tk.Button(root, text="Exit", command=root.destroy,
                         font=("Segoe UI", 10), bg="#0e0d18", fg="#4a4760",
                         activebackground="#0e0d18", activeforeground="#8F8C9E",
                         relief="flat", bd=0, cursor="hand2")
    exit_btn.pack(pady=(20, 10))

    root.mainloop()


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    # First run always goes to Wizard Guild (Installer Wizard appears)
    if _is_first_run():
        print("  First run — launching Wizard Guild setup...")
        _launch_guild()
        return

    # Try GUI, fall back to CLI
    if sys.stdin and sys.stdin.isatty():
        try:
            gui_menu()
        except Exception:
            cli_menu()
    else:
        try:
            gui_menu()
        except Exception:
            pass


if __name__ == "__main__":
    main()
