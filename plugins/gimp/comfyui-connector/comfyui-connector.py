#!/usr/bin/env python3
"""Spellcaster GIMP Plugin — Crash-Safe Boot Shim.

THIS FILE IS IMMUTABLE. The auto-updater will NEVER overwrite it.
All plugin code lives in _spellcaster_main.py, which IS auto-updated.

Boot sequence:
  1. Apply any staged .update files (from previous auto-update)
  2. Back up _spellcaster_main.py → .bak
  3. Try to import Spellcaster class from _spellcaster_main
  4. On crash → restore from .bak and retry
  5. On crash → download fresh copy from GitHub and retry
  6. On crash → register a minimal error-reporting plugin so the user
     sees "Spellcaster CRASHED" in the menu instead of nothing

This guarantees the plugin NEVER silently disappears from GIMP,
no matter how badly a code update breaks things.
"""

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gegl', '0.4')

import sys
import os
import json
import shutil
import platform
import urllib.request
from pathlib import Path
from gi.repository import Gimp, GLib

_DIR = Path(__file__).parent
_MAIN = _DIR / "_spellcaster_main.py"
_BAK = _DIR / "_spellcaster_main.py.bak"

_GITHUB_RAW = (
    "https://raw.githubusercontent.com/laboratoiresonore/spellcaster_NSFW"
    "/main/plugins/gimp/comfyui-connector/_spellcaster_main.py"
)


# ═══════════════════════════════════════════════════════════════════════
#  Stage 1 — Apply .update files left by a previous auto-update
# ═══════════════════════════════════════════════════════════════════════

def _apply_staged_updates():
    """Swap every *.update file to its real name before Python imports."""
    applied = 0
    for update_file in sorted(_DIR.rglob("*.update")):
        target = update_file.with_suffix("")  # foo.py.update → foo.py
        try:
            if target.exists():
                target.unlink()
            update_file.rename(target)
            applied += 1
        except Exception as e:
            print(f"[Spellcaster Shim] Failed to stage {update_file.name}: {e}",
                  file=sys.stderr)
    if applied:
        # Force GIMP to re-scan procedures on next restart
        _delete_pluginrc()
    return applied


def _delete_pluginrc():
    """Delete GIMP's pluginrc cache so it re-scans on next launch."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "GIMP"
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "GIMP"
    else:
        base = Path.home() / ".config" / "GIMP"
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir() and d.name.startswith("3"):
                rc = d / "pluginrc"
                if rc.exists():
                    try:
                        rc.unlink()
                    except Exception:
                        pass


# ═══════════════════════════════════════════════════════════════════════
#  Stage 2 — Download a fresh _spellcaster_main.py from GitHub
# ═══════════════════════════════════════════════════════════════════════

def _read_config():
    """Read config.json (for NSFW repo URL override and auth token)."""
    try:
        return json.loads((_DIR / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _download_fresh():
    """Download _spellcaster_main.py from GitHub. Returns True on success."""
    cfg = _read_config()
    url = cfg.get("_main_url", _GITHUB_RAW)
    headers = {"User-Agent": "spellcaster-gimp/2.0"}
    # NSFW builds inject an auth token into config
    token = cfg.get("_github_token")
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        # Reject empty/corrupt downloads
        if len(data) < 5000:
            return False
        # Scrub NTFS null-byte corruption
        data = data.replace(b"\x00", b"")
        _MAIN.write_bytes(data)
        print("[Spellcaster Shim] Downloaded fresh _spellcaster_main.py",
              file=sys.stderr)
        return True
    except Exception as e:
        print(f"[Spellcaster Shim] Download failed: {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  Stage 3 — Try to import the Spellcaster class (with retries)
# ═══════════════════════════════════════════════════════════════════════

def _try_import():
    """Import _spellcaster_main and return the Spellcaster class."""
    d = str(_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    # Force fresh import (in case a previous attempt left a broken module)
    sys.modules.pop("_spellcaster_main", None)
    from _spellcaster_main import Spellcaster
    return Spellcaster


# ═══════════════════════════════════════════════════════════════════════
#  Boot — the actual entry point
# ═══════════════════════════════════════════════════════════════════════

_apply_staged_updates()

# Back up before loading so we can roll back if the update is broken
if _MAIN.exists():
    try:
        shutil.copy2(str(_MAIN), str(_BAK))
    except Exception:
        pass

SpellcasterClass = None
_boot_error = None

# ── Attempt 1: normal import ─────────────────────────────────────────
try:
    SpellcasterClass = _try_import()
except Exception as e:
    _boot_error = f"Import failed: {e}"
    print(f"[Spellcaster Shim] {_boot_error}", file=sys.stderr)

    # ── Attempt 2: rollback to backup ────────────────────────────────
    if _BAK.exists():
        try:
            shutil.copy2(str(_BAK), str(_MAIN))
            SpellcasterClass = _try_import()
            _boot_error = None
            print("[Spellcaster Shim] Restored from backup", file=sys.stderr)
        except Exception as e2:
            _boot_error = f"Backup also broken: {e2}"
            print(f"[Spellcaster Shim] {_boot_error}", file=sys.stderr)

    # ── Attempt 3: download from GitHub ──────────────────────────────
    if SpellcasterClass is None and _download_fresh():
        try:
            SpellcasterClass = _try_import()
            _boot_error = None
            print("[Spellcaster Shim] Self-healed from GitHub", file=sys.stderr)
        except Exception as e3:
            _boot_error = f"Fresh download also crashed: {e3}"
            print(f"[Spellcaster Shim] {_boot_error}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════════
#  Launch — either the real plugin or a crash reporter
# ═══════════════════════════════════════════════════════════════════════

if SpellcasterClass is not None:
    # Normal boot — hand off to the real plugin
    Gimp.main(SpellcasterClass.__gtype__, sys.argv)
else:
    # All recovery failed — register a visible error so the user
    # sees "Spellcaster CRASHED" in the Filters menu instead of
    # the plugin silently vanishing.
    class SpellcasterCrashed(Gimp.PlugIn):
        def do_set_i18n(self, name):
            return False

        def do_query_procedures(self):
            return ["spellcaster-crashed"]

        def do_create_procedure(self, name):
            proc = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN,
                self._show_error, None)
            proc.set_menu_label(
                "!! Spellcaster CRASHED — click for recovery !!")
            proc.add_menu_path("<Image>/Filters")
            proc.set_documentation(
                "Spellcaster failed to load", _boot_error or "Unknown error", name)
            proc.set_attribution("Spellcaster", "Spellcaster", "2026")
            proc.set_image_types("*")
            return proc

        def _show_error(self, proc, run_mode, image, drawables, config, data):
            Gimp.message(
                f"Spellcaster failed to load:\n\n"
                f"{_boot_error}\n\n"
                f"Recovery was attempted automatically but failed.\n"
                f"Run spellcaster-manual-update.exe to repair,\n"
                f"or delete the plugin folder and reinstall:\n"
                f"  {_DIR}\n")
            return proc.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

    Gimp.main(SpellcasterCrashed.__gtype__, sys.argv)
