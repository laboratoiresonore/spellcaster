#!/usr/bin/env python3
"""Spellcaster GIMP Plugin Emergency Repair

Run this on any machine where the GIMP plugin is bricked.
It downloads the latest version of ALL plugin files directly from
GitHub and installs them to the correct GIMP plugin directory.

Usage:
    python repair_gimp_plugin.py

No arguments needed — it auto-detects your GIMP version and OS.
"""
import json
import os
import sys
import urllib.request

GITHUB_REPO = "laboratoiresonore/spellcaster"
GITHUB_TREE = f"https://api.github.com/repos/{GITHUB_REPO}/git/trees/main?recursive=1"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"
GIMP_PLUGIN_PREFIX = "plugins/gimp/comfyui-connector/"
CORE_LIB_PREFIX = "comfyui-spellcaster/spellcaster_core/"


def find_gimp_plugin_dir():
    """Find the GIMP plugin directory on this machine."""
    candidates = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            for ver in ("3.2", "3.0", "2.99"):
                p = os.path.join(appdata, "GIMP", ver, "plug-ins", "comfyui-connector")
                if os.path.isdir(p):
                    candidates.append(p)
    elif sys.platform == "darwin":
        home = os.path.expanduser("~")
        for ver in ("3.2", "3.0"):
            p = os.path.join(home, "Library", "Application Support", "GIMP", ver, "plug-ins", "comfyui-connector")
            if os.path.isdir(p):
                candidates.append(p)
    else:
        home = os.path.expanduser("~")
        for ver in ("3.2", "3.0"):
            p = os.path.join(home, ".config", "GIMP", ver, "plug-ins", "comfyui-connector")
            if os.path.isdir(p):
                candidates.append(p)
    return candidates


def repair():
    dirs = find_gimp_plugin_dir()
    if not dirs:
        print("ERROR: Could not find any GIMP plugin directory.")
        print("Make sure GIMP is installed and Spellcaster was installed at least once.")
        sys.exit(1)

    for plugin_dir in dirs:
        print(f"\nRepairing: {plugin_dir}")
        print("Fetching file list from GitHub...")

        req = urllib.request.Request(GITHUB_TREE, headers={"User-Agent": "Spellcaster-Repair"})
        with urllib.request.urlopen(req, timeout=30) as r:
            tree = json.loads(r.read())

        # Build file list — canonical source wins over bundled copy
        remote_files = []
        seen = set()
        for item in tree.get("tree", []):
            if item["type"] != "blob":
                continue
            if item["path"].startswith(CORE_LIB_PREFIX):
                remainder = item["path"][len("comfyui-spellcaster/"):]
                if remainder and remainder not in seen:
                    remote_files.append((item["path"], remainder))
                    seen.add(remainder)
            elif item["path"].startswith(GIMP_PLUGIN_PREFIX):
                remainder = item["path"][len(GIMP_PLUGIN_PREFIX):]
                if remainder and remainder not in seen:
                    remote_files.append((item["path"], remainder))
                    seen.add(remainder)

        print(f"Found {len(remote_files)} files to sync.")
        updated = 0
        failed = 0

        for rel_path, remainder in remote_files:
            url = f"{RAW_BASE}/{rel_path}"
            dest = os.path.join(plugin_dir, remainder.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                req_dl = urllib.request.Request(url, headers={"User-Agent": "Spellcaster-Repair"})
                with urllib.request.urlopen(req_dl, timeout=60) as r2:
                    blob = r2.read()
                # Scrub null bytes from text files
                if remainder.endswith((".py", ".json", ".md", ".txt", ".html", ".css", ".js")):
                    blob = blob.replace(b"\x00", b"")
                # Remove any stale .update staging files
                update_path = dest + ".update"
                if os.path.exists(update_path):
                    os.remove(update_path)
                with open(dest, "wb") as f:
                    f.write(blob)
                updated += 1
                print(f"  OK: {remainder}")
            except Exception as e:
                failed += 1
                print(f"  FAIL: {remainder} — {e}")

        # Write version marker
        try:
            req_sha = urllib.request.Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/commits?sha=main&per_page=1",
                headers={"User-Agent": "Spellcaster-Repair"})
            with urllib.request.urlopen(req_sha, timeout=10) as r:
                sha = json.loads(r.read())[0]["sha"]
            ver_path = os.path.join(plugin_dir, ".spellcaster_version")
            with open(ver_path, "w") as f:
                f.write(sha)
            print(f"\nVersion marker set: {sha[:7]}")
        except Exception:
            pass

        # Delete pluginrc cache to force GIMP menu rescan
        for ver in ("3.2", "3.0"):
            if sys.platform == "win32":
                prc = os.path.join(os.environ.get("APPDATA", ""), "GIMP", ver, "pluginrc")
            else:
                prc = os.path.join(os.path.expanduser("~"), ".config", "GIMP", ver, "pluginrc")
            if os.path.exists(prc):
                try:
                    os.remove(prc)
                    print(f"Cleared pluginrc cache: {prc}")
                except Exception:
                    pass

        print(f"\nDone: {updated} files updated, {failed} failed.")
        if failed == 0:
            print("Repair complete. Restart GIMP to apply.")
        else:
            print("Some files failed — check your internet connection and try again.")


if __name__ == "__main__":
    print("=" * 60)
    print("Spellcaster GIMP Plugin Emergency Repair")
    print("=" * 60)
    repair()
