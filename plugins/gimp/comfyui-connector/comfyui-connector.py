#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ═══════════════════════════════════════════════════════════════════════════
#  Spellcaster — AI Superpowers for GIMP 3
# ═══════════════════════════════════════════════════════════════════════════
#
# Spellcaster lets artists run AI image generation workflows
# directly from the GIMP canvas. Supports:
#   - img2img, txt2img, inpainting with 35+ model presets
#   - Face swap (ReActor, mtb, IPAdapter FaceID, PuLID Flux)
#   - Wan 2.2 image-to-video generation
#   - Flux 2 Klein distilled img2img
#   - Custom workflow JSON pass-through
#
# Architecture:
#   1. Export GIMP canvas/selection to temp PNG
#   2. Upload to ComfyUI server via HTTP multipart POST
#   3. Build a ComfyUI workflow JSON (node graph) from presets
#   4. Submit workflow, poll for completion, download result
#   5. Import result as a new GIMP layer
#
# All HTTP communication uses stdlib urllib (no pip installs needed).
# GTK dialogs use GObject Introspection bindings for GIMP 3's GTK 3 API.
#

# ── GObject Introspection version locks ────────────────────────────────
# These gi.require_version() calls must happen before any gi.repository
# imports. They pin the typelib versions so GIMP 3's Python environment
# loads the correct shared libraries.
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GimpUi, Gtk, GLib, Gio, GObject, GdkPixbuf, Gegl

import sys
import json
import os
import tempfile
import uuid
import time
import random
import struct          # for pure-Python PNG writer (IHDR/IDAT chunk packing)
import zlib            # for PNG IDAT compression and CRC32 checksums

import urllib.request
import urllib.parse
import urllib.error
import threading
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
#  Auto-updater — runs once per GIMP session in the background
# ═══════════════════════════════════════════════════════════════════════════
_PLUGIN_DIR    = Path(__file__).parent
_VERSION_FILE  = _PLUGIN_DIR / ".spellcaster_version"
_GITHUB_API    = "https://api.github.com/repos/laboratoiresonore/spellcaster/commits?sha=main&per_page=1"
_GITHUB_TREE   = "https://api.github.com/repos/laboratoiresonore/spellcaster/git/trees/main?recursive=1"
_RAW_BASE      = "https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main"
_GIMP_PLUGIN_PREFIX = "plugins/gimp/comfyui-connector/"

def _apply_spellcaster_theme():
    """Inject a magical, premium dark mode CSS into GIMP's GTK3 environment for all plugin dialogs."""
    try:
        from gi.repository import Gdk, Gtk
        css = b'''
        /* Spellcaster Premium GTK3 Theme */

        /* Base window & dialog */
        window, dialog {
            background-color: #0B0715;
            background-image: linear-gradient(180deg, #0B0715 0%, #110A20 100%);
        }

        /* Typography */
        label {
            color: #E2DFEB;
            font-family: "Segoe UI", "Inter", "Cantarell", sans-serif;
            font-size: 13px;
        }
        label.header-label, label.spellcaster-title {
            font-size: 16px;
            font-weight: bold;
            color: #D122E3;
            margin-bottom: 8px;
        }
        label.spellcaster-subtitle {
            font-size: 11px;
            color: #8B7CA8;
            margin-bottom: 6px;
        }
        label.section-header {
            font-size: 14px;
            font-weight: bold;
            color: #B060D0;
            padding: 4px 0px;
        }

        /* -- Buttons -- */
        button {
            background-image: none;
            background-color: #3A2863;
            color: white;
            border-radius: 6px;
            border: 1px solid #5A3A8A;
            padding: 8px 16px;
            font-weight: bold;
            transition: all 200ms ease-in-out;
        }
        button:hover {
            background-color: #D122E3;
            color: #0B0715;
            border-color: #D122E3;
            box-shadow: 0 0 12px rgba(209, 34, 227, 0.6);
        }
        button:active {
            background-color: #A01AB5;
            border-color: #A01AB5;
        }
        /* Primary action buttons (OK/Run/Generate/Swap) */
        button.suggested-action, button.spellcaster-primary {
            background-color: #D122E3;
            color: white;
            border: 1px solid #E855F5;
            padding: 10px 24px;
            font-size: 14px;
            font-weight: bold;
            box-shadow: 0 2px 8px rgba(209, 34, 227, 0.35);
        }
        button.suggested-action:hover, button.spellcaster-primary:hover {
            background-color: #E855F5;
            box-shadow: 0 4px 16px rgba(209, 34, 227, 0.55);
        }
        /* Destructive / Cancel buttons */
        button.destructive-action {
            background-color: #2A1A3E;
            color: #A090B8;
            border: 1px solid #3A2863;
            padding: 10px 24px;
            font-size: 14px;
        }
        button.destructive-action:hover {
            background-color: #3A2863;
            color: white;
        }

        /* -- Text inputs -- */
        entry, spinbutton, textview text, combobox {
            background-color: #150D26;
            color: white;
            border-radius: 4px;
            border: 1px solid #3A2863;
            padding: 4px;
            caret-color: #D122E3;
            transition: border-color 150ms ease;
        }
        entry:focus, spinbutton:focus, textview text:focus {
            border-color: #D122E3;
            box-shadow: 0 0 6px rgba(209, 34, 227, 0.4);
        }

        /* -- Notebook (tabs) -- */
        notebook {
            background-color: #0B0715;
        }
        notebook header {
            background-color: #110A20;
            border-bottom: 2px solid #21153B;
        }
        notebook header tab {
            background-color: #150D26;
            color: #8B7CA8;
            border: 1px solid #21153B;
            border-bottom: none;
            padding: 6px 14px;
            border-radius: 6px 6px 0 0;
            margin: 0 1px;
        }
        notebook header tab:checked {
            background-color: #21153B;
            color: #D122E3;
            border-color: #3A2863;
            border-bottom: 2px solid #D122E3;
        }
        notebook header tab:hover {
            background-color: #1E1435;
            color: #E2DFEB;
        }
        notebook stack { background-color: #0B0715; }

        /* -- TreeView (lists) -- */
        treeview {
            background-color: #110A20;
            color: #E2DFEB;
        }
        treeview:selected {
            background-color: #3A2863;
            color: white;
        }
        treeview header button {
            background-color: #150D26;
            color: #B060D0;
            border: none;
            border-bottom: 1px solid #3A2863;
            font-weight: bold;
            padding: 4px 8px;
        }

        /* -- MenuBar -- */
        menubar {
            background-color: #110A20;
            border-bottom: 1px solid #21153B;
        }
        menubar > menuitem {
            color: #C0B8D0;
            padding: 4px 10px;
        }
        menubar > menuitem:hover {
            background-color: #3A2863;
            color: white;
        }
        menu {
            background-color: #150D26;
            border: 1px solid #3A2863;
            border-radius: 4px;
        }
        menu menuitem {
            color: #E2DFEB;
            padding: 6px 12px;
        }
        menu menuitem:hover {
            background-color: #3A2863;
            color: white;
        }

        /* -- Sliders (GtkScale) -- */
        scale {
            color: #E2DFEB;
        }
        scale trough {
            background-color: #21153B;
            border-radius: 4px;
            min-height: 6px;
            border: none;
        }
        scale trough highlight {
            background-color: #D122E3;
            border-radius: 4px;
            min-height: 6px;
        }
        scale slider {
            background-color: #D122E3;
            border-radius: 50%;
            min-width: 16px;
            min-height: 16px;
            border: 2px solid #E855F5;
            box-shadow: 0 0 4px rgba(209, 34, 227, 0.5);
        }
        scale slider:hover {
            background-color: #E855F5;
            box-shadow: 0 0 8px rgba(209, 34, 227, 0.7);
        }

        /* -- Switches & Checkboxes -- */
        switch {
            background-color: #21153B;
            border-radius: 12px;
            border: 1px solid #3A2863;
            min-width: 40px;
            min-height: 20px;
        }
        switch:checked {
            background-color: #D122E3;
            border-color: #E855F5;
        }
        switch slider {
            background-color: #E2DFEB;
            border-radius: 50%;
            min-width: 16px;
            min-height: 16px;
        }
        checkbutton check, radiobutton radio {
            background-color: #150D26;
            border: 2px solid #3A2863;
            border-radius: 3px;
            min-width: 18px;
            min-height: 18px;
        }
        checkbutton check:checked, radiobutton radio:checked {
            background-color: #D122E3;
            border-color: #D122E3;
            color: white;
        }
        checkbutton check:hover, radiobutton radio:hover {
            border-color: #D122E3;
            box-shadow: 0 0 4px rgba(209, 34, 227, 0.4);
        }

        /* -- Scrollbars -- */
        scrollbar {
            background-color: #0B0715;
        }
        scrollbar slider {
            background-color: #3A2863;
            border-radius: 8px;
            min-width: 8px;
            min-height: 8px;
            border: none;
        }
        scrollbar slider:hover {
            background-color: #5A3A8A;
        }
        scrollbar slider:active {
            background-color: #D122E3;
        }

        /* -- Combobox dropdown -- */
        combobox button {
            background-color: #150D26;
            border: 1px solid #3A2863;
            color: white;
            padding: 4px 8px;
        }
        combobox button:hover {
            border-color: #D122E3;
        }
        combobox arrow {
            color: #D122E3;
        }

        /* -- Progress bar -- */
        progressbar text { color: white; font-weight: bold; }
        progressbar trough {
            background-color: #150D26;
            border-radius: 4px;
            border: 1px solid #3A2863;
            min-height: 12px;
        }
        progressbar progress {
            background-color: #D122E3;
            border-radius: 4px;
            background-image: linear-gradient(90deg, #D122E3, #E855F5, #D122E3);
        }

        /* -- Separator -- */
        separator {
            background-color: #21153B;
            min-height: 1px;
            min-width: 1px;
        }

        /* -- Tooltip -- */
        tooltip {
            background-color: #1E1435;
            color: #E2DFEB;
            border: 1px solid #3A2863;
            border-radius: 4px;
        }

        /* -- File chooser -- */
        filechooser {
            background-color: #0B0715;
        }
        placessidebar row {
            color: #C0B8D0;
        }
        placessidebar row:selected {
            background-color: #3A2863;
            color: white;
        }

        /* -- Dialog action area styling -- */
        dialog .dialog-action-area button {
            min-width: 100px;
            min-height: 36px;
            font-size: 14px;
            margin: 4px;
        }

        /* -- Spellcaster branded header -- */
        .spellcaster-header-box {
            padding: 6px 12px;
            background-color: #110A20;
            border-bottom: 2px solid #D122E3;
            margin-bottom: 6px;
        }
        '''
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    except Exception as e:
        print(f"Warning: Failed to load premium UI theme: {e}")


def _make_branded_header():
    """Create a branded Spellcaster header widget for dialog tops."""
    try:
        from gi.repository import Gtk
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctx = hbox.get_style_context()
        ctx.add_class("spellcaster-header-box")

        title = Gtk.Label()
        title.set_markup('<span size="14000" weight="bold" color="#D122E3">Spellcaster</span>')
        title.set_xalign(0)
        hbox.pack_start(title, False, False, 0)

        tagline = Gtk.Label()
        tagline.set_markup('<span size="9000" color="#8B7CA8">AI Superpowers</span>')
        tagline.set_xalign(0)
        tagline.set_valign(Gtk.Align.END)
        hbox.pack_start(tagline, False, False, 0)

        return hbox
    except Exception:
        return None


def _style_dialog_buttons(dialog):
    """Apply premium styling to a dialog's OK/Cancel action buttons.

    Marks the OK button as suggested-action and the Cancel button as
    destructive-action so the CSS theme can make them prominent and branded.
    """
    try:
        for btn in dialog.get_action_area().get_children():
            resp = dialog.get_response_for_widget(btn)
            ctx = btn.get_style_context()
            if resp == Gtk.ResponseType.OK:
                ctx.add_class("suggested-action")
                ctx.add_class("spellcaster-primary")
            elif resp == Gtk.ResponseType.CANCEL:
                ctx.add_class("destructive-action")
    except Exception:
        pass


_apply_spellcaster_theme()

def _auto_update():
    """Check GitHub for a newer commit and download ALL plugin files dynamically.

    Uses the GitHub Tree API to discover every file under the plugin directory,
    so new files, renamed files, and removed files are handled automatically.
    This means the updater can absorb arbitrarily large updates — new modules,
    assets, whatever gets added to the repo.

    Flow:
      1. GET /commits → latest SHA (quick, 1 API call)
      2. Compare with local .spellcaster_version
      3. If different: GET /git/trees/main?recursive=1
      4. Filter for files under plugins/gimp/comfyui-connector/
      5. Download each via raw.githubusercontent.com (atomic tmp→rename)
      6. Remove local files that no longer exist in the repo
      7. Write new SHA to .spellcaster_version
    """
    import sys as _sys
    _ua = "spellcaster-gimp/2.0"

    try:
        # Step 1: Check latest commit SHA
        local_sha = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else ""
        req = urllib.request.Request(_GITHUB_API, headers={"User-Agent": _ua})
        with urllib.request.urlopen(req, timeout=8) as r:
            latest_sha = json.loads(r.read())[0]["sha"]

        if latest_sha == local_sha:
            return

        # Step 2: Fetch full repo tree to discover ALL plugin files
        req_tree = urllib.request.Request(_GITHUB_TREE, headers={"User-Agent": _ua})
        with urllib.request.urlopen(req_tree, timeout=15) as r:
            tree = json.loads(r.read())

        # Step 3: Filter for files in our plugin directory (including subdirectories)
        remote_files = []
        for item in tree.get("tree", []):
            if item["type"] == "blob" and item["path"].startswith(_GIMP_PLUGIN_PREFIX):
                remainder = item["path"][len(_GIMP_PLUGIN_PREFIX):]
                if remainder:
                    remote_files.append(item["path"])

        if not remote_files:
            return  # Something went wrong with API, don't touch local files

        # Step 4: Download all remote files (supports subdirectories)
        updated = 0
        failed = 0
        remote_filenames = set()
        for rel_path in remote_files:
            # Preserve subdirectory structure relative to plugin dir
            remainder = rel_path[len(_GIMP_PLUGIN_PREFIX):]
            remote_filenames.add(remainder)
            try:
                url = f"{_RAW_BASE}/{rel_path}"
                dest = _PLUGIN_DIR / remainder
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(dest.suffix + ".tmp")
                req_dl = urllib.request.Request(url, headers={"User-Agent": _ua})
                with urllib.request.urlopen(req_dl, timeout=60) as r2:
                    tmp.write_bytes(r2.read())
                tmp.replace(dest)
                updated += 1
            except Exception as e:
                failed += 1
                print(f"[Spellcaster] Failed to download {remainder}: {e}", file=_sys.stderr)

        # Step 5: Remove local files that no longer exist in the repo
        protected = {"config.json", ".spellcaster_version"}
        for local_file in _PLUGIN_DIR.rglob("*"):
            if not local_file.is_file():
                continue
            rel = local_file.relative_to(_PLUGIN_DIR).as_posix()
            if rel in protected or local_file.name in protected \
               or local_file.name.endswith(".pyc"):
                continue
            if rel not in remote_filenames:
                try:
                    local_file.unlink()
                except Exception:
                    pass

        # Step 6: Record version and notify user
        if updated > 0:
            _VERSION_FILE.write_text(latest_sha)
            sha7 = latest_sha[:7]
            msg = f"Spellcaster updated to {sha7} ({updated} files)."
            if failed > 0:
                msg += f"\n{failed} file(s) failed to download."
            msg += "\nRestart GIMP to use the new version."
            GLib.idle_add(lambda: Gimp.message(msg) or False)
    except Exception as e:
        print(f"[Spellcaster] Auto-update check failed: {e}", file=_sys.stderr)

# Fire-and-forget: runs once per GIMP session, daemon=True so it
# won't prevent GIMP from exiting
threading.Thread(target=_auto_update, daemon=True).start()

# ═══════════════════════════════════════════════════════════════════════════
#  Configuration loading — server URL and user-saved presets
# ═══════════════════════════════════════════════════════════════════════════

def _load_config():
    """Load config.json from the plugin directory. Returns {} on any error."""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# Default ComfyUI server URL — overridable via config.json {"server_url": "..."}
# Updated at runtime whenever the user successfully runs a workflow with a different URL.
COMFYUI_DEFAULT_URL = _load_config().get("server_url", "http://127.0.0.1:8188")

def _save_config(data):
    """Write config.json to the plugin directory, merging with existing config."""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    existing = _load_config()
    existing.update(data)
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

def _propagate_server_url(new_url):
    """Update the session-wide default server URL and persist to config.json."""
    global COMFYUI_DEFAULT_URL
    new_url = new_url.strip().rstrip("/")
    if new_url and new_url != COMFYUI_DEFAULT_URL:
        COMFYUI_DEFAULT_URL = new_url
        _save_config({"server_url": new_url})

# ── Session state — remembers last-used settings per dialog ──────────
# In-memory only: forgotten when GIMP restarts. Each dialog type stores
# its last-used values here so reopening the same tool pre-fills with
# the user's previous settings. NOT saved to disk.
_SESSION = {}

# User presets persist prompt/model/LoRA combinations across sessions
_USER_PRESETS_PATH = Path(__file__).parent / "user_presets.json"

def _load_user_presets(dialog_key="preset_dialog"):
    """Load user-saved preset configurations from user_presets.json.

    Supports keyed dict format (multiple dialog types) and auto-migrates
    the old flat list format under the "preset_dialog" key.
    """
    try:
        all_data = json.loads(_USER_PRESETS_PATH.read_text(encoding="utf-8"))
        if isinstance(all_data, list):
            # Old format: flat list belongs to preset_dialog
            return all_data if dialog_key == "preset_dialog" else []
        return all_data.get(dialog_key, [])
    except Exception:
        return []

def _save_user_presets(presets, dialog_key="preset_dialog"):
    """Persist user presets to disk. Fails silently on write errors.

    Stores presets in a keyed dict so different dialogs don't collide.
    Auto-migrates old flat list format on first write.
    """
    try:
        all_data = {}
        try:
            raw = json.loads(_USER_PRESETS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                all_data = {"preset_dialog": raw}
            else:
                all_data = raw
        except Exception:
            pass
        all_data[dialog_key] = presets
        _USER_PRESETS_PATH.write_text(
            json.dumps(all_data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ── Reusable user-preset UI helpers ──────────────────────────────────────
# These functions add Save / Load / Delete preset functionality to any
# dialog class.  The dialog must implement two methods:
#   _collect_user_preset()  → dict of saveable widget values
#   _apply_user_preset(p)   → restore widget values from a dict
#
# Usage in __init__:  _add_preset_ui(self, parent_box, "my_dialog_key")

def _add_preset_ui(dialog, box, dialog_key):
    """Add a My Presets bar (combo + Load / Save / Delete) to *dialog*.

    Stores helper state on the dialog instance:
      dialog._up_key      — storage key in user_presets.json
      dialog._up_presets  — in-memory list of presets for this key
      dialog._up_combo    — the GtkComboBoxText widget
    """
    dialog._up_key = dialog_key
    dialog._up_presets = _load_user_presets(dialog_key)

    up_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    up_hb.pack_start(Gtk.Label(label="My Presets:"), False, False, 0)
    dialog._up_combo = Gtk.ComboBoxText()
    dialog._up_combo.set_hexpand(True)
    dialog._up_combo.set_tooltip_text("Your saved parameter presets. Save and load your favorite settings.")
    up_hb.pack_start(dialog._up_combo, True, True, 0)

    load_btn = Gtk.Button(label="Load")
    load_btn.set_tooltip_text("Load the selected preset into all fields")
    load_btn.connect("clicked", lambda _b: _up_load(dialog))
    up_hb.pack_start(load_btn, False, False, 0)

    save_btn = Gtk.Button(label="Save\u2026")
    save_btn.set_tooltip_text("Save current settings as a named preset")
    save_btn.connect("clicked", lambda _b: _up_save(dialog))
    up_hb.pack_start(save_btn, False, False, 0)

    del_btn = Gtk.Button(label="\u2715")
    del_btn.set_tooltip_text("Delete selected preset")
    del_btn.connect("clicked", lambda _b: _up_delete(dialog))
    up_hb.pack_start(del_btn, False, False, 0)

    box.pack_start(up_hb, False, False, 0)
    _up_refresh(dialog)


def _up_refresh(dialog):
    """Repopulate the preset combo from the in-memory list."""
    dialog._up_combo.remove_all()
    for p in dialog._up_presets:
        dialog._up_combo.append_text(p["name"])
    if dialog._up_presets:
        dialog._up_combo.set_active(0)


def _up_load(dialog):
    """Load the currently selected preset into dialog widgets."""
    idx = dialog._up_combo.get_active()
    if idx < 0 or idx >= len(dialog._up_presets):
        return
    if hasattr(dialog, "_apply_user_preset"):
        dialog._apply_user_preset(dialog._up_presets[idx])


def _up_save(dialog):
    """Prompt for a name and save the current dialog state as a preset."""
    dlg = Gtk.Dialog(title="Save Preset", transient_for=dialog, modal=True)
    dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
    dlg.add_button("_Save", Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    area = dlg.get_content_area()
    area.set_spacing(8)
    area.set_margin_start(12); area.set_margin_end(12)
    area.set_margin_top(12); area.set_margin_bottom(12)
    area.pack_start(Gtk.Label(label="Preset name:"), False, False, 0)
    name_entry = Gtk.Entry()
    name_entry.set_activates_default(True)
    cur_idx = dialog._up_combo.get_active()
    if 0 <= cur_idx < len(dialog._up_presets):
        name_entry.set_text(dialog._up_presets[cur_idx]["name"])
    area.pack_start(name_entry, False, False, 0)
    area.show_all()
    resp = dlg.run()
    name = name_entry.get_text().strip()
    dlg.destroy()
    if resp != Gtk.ResponseType.OK or not name:
        return
    data = dialog._collect_user_preset()
    data["name"] = name
    existing = next((i for i, p in enumerate(dialog._up_presets) if p["name"] == name), None)
    if existing is not None:
        dialog._up_presets[existing] = data
    else:
        dialog._up_presets.append(data)
    _save_user_presets(dialog._up_presets, dialog._up_key)
    _up_refresh(dialog)
    new_idx = next((i for i, p in enumerate(dialog._up_presets) if p["name"] == name), 0)
    dialog._up_combo.set_active(new_idx)


def _up_delete(dialog):
    """Delete the selected preset after confirmation."""
    idx = dialog._up_combo.get_active()
    if idx < 0 or idx >= len(dialog._up_presets):
        return
    name = dialog._up_presets[idx]["name"]
    dlg = Gtk.MessageDialog(transient_for=dialog, modal=True,
                            message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.YES_NO,
                            text=f'Delete preset "{name}"?')
    resp = dlg.run()
    dlg.destroy()
    if resp == Gtk.ResponseType.YES:
        del dialog._up_presets[idx]
        _save_user_presets(dialog._up_presets, dialog._up_key)
        _up_refresh(dialog)

# ── Runs spinner helper ────────────────────────────────────────────────
# Adds a "Runs" spinner (1-99) to any dialog so users can queue multiple
# generations from one dialog submit.  Each run gets a fresh random seed.

def _add_runs_spinner(dialog, box):
    """Add a 'Runs' spinner (1-99) to the bottom of any dialog.

    Lets the user queue multiple generations from one dialog submit.
    Each run gets a fresh random seed (unless the user set a specific seed).
    """
    hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
    dialog._runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
    dialog._runs_spin.set_value(1)
    dialog._runs_spin.set_tooltip_text(
        "Number of times to run this generation. Each run uses a fresh random seed.")
    hb.pack_start(dialog._runs_spin, False, False, 0)
    hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
    box.pack_start(hb, False, False, 0)


# ═══════════════════════════════════════════════════════════════════════════
#  MODEL PRESETS — one img2img workflow per checkpoint, tuned per arch
# ═══════════════════════════════════════════════════════════════════════════
# Each preset defines a complete set of generation parameters for a specific
# checkpoint model. Fields:
#   label      — display name in the UI dropdown
#   arch       — architecture key (sd15/sdxl/flux1dev/flux2klein/flux_kontext/zit)
#                used to filter compatible LoRAs via ARCH_LORA_PREFIXES
#   ckpt       — checkpoint filename relative to ComfyUI's models/checkpoints/
#   width/height — native resolution for this model (512 for SD1.5, 1024 for SDXL/Flux)
#   steps      — denoising steps (more = slower but more detailed)
#   cfg        — classifier-free guidance scale (how strictly to follow the prompt)
#   denoise    — denoising strength for img2img (0=no change, 1=full regeneration)
#   sampler    — sampling algorithm (euler, dpmpp_2m, euler_ancestral, etc.)
#   scheduler  — noise schedule (karras, normal, simple, sgm_uniform, etc.)
#   prompt_hint    — example positive prompt pre-filled for the user
#   negative_hint  — example negative prompt (empty for Flux/Klein which don't use negatives)

MODEL_PRESETS = [
    # ── SD 1.5 ──────────────────────────────────────────────────────────
    {
        "label": "SD1.5 — Juggernaut Reborn (realistic)",
        "arch": "sd15",
        "ckpt": "SD-1.5\\juggernaut_reborn.safetensors",
        "width": 512, "height": 512,
        "steps": 25, "cfg": 7.0, "denoise": 0.62,
        "sampler": "dpmpp_2m", "scheduler": "karras",
        "prompt_hint": "photorealistic, highly detailed, sharp focus",
        "negative_hint": "cartoon, painting, blurry, deformed",
    },
    {
        "label": "SD1.5 — Realistic Vision v5.1 (photo)",
        "arch": "sd15",
        "ckpt": "SD-1.5\\realisticVisionV51_v51VAE.safetensors",
        "width": 512, "height": 512,
        "steps": 25, "cfg": 7.0, "denoise": 0.60,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "RAW photo, photorealistic, ultra detailed skin",
        "negative_hint": "(deformed, distorted, disfigured:1.3), blurry, bad anatomy",
    },
    {
        "label": "SD1.5 — Base v1.5 (general)",
        "arch": "sd15",
        "ckpt": "SD-1.5\\v1-5-pruned-emaonly.safetensors",
        "width": 512, "height": 512,
        "steps": 20, "cfg": 7.5, "denoise": 0.65,
        "sampler": "euler", "scheduler": "normal",
        "prompt_hint": "high quality, detailed",
        "negative_hint": "lowres, bad anatomy, worst quality",
    },
    # ── SDXL Anime ──────────────────────────────────────────────────────
    {
        "label": "SDXL — NoobAI-XL v1.1 (anime)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Anime\\NoobAI-XL-v1.1.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 6.0, "denoise": 0.60,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "masterpiece, best quality, anime style, detailed",
        "negative_hint": "worst quality, low quality, blurry, bad anatomy",
    },
    {
        "label": "SDXL — Nova Anime XL v1.70 (anime)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Anime\\novaAnimeXL_ilV170.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 6.5, "denoise": 0.60,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "anime, masterpiece, vivid colors, detailed illustration",
        "negative_hint": "worst quality, low quality, realistic, 3d",
    },
    {
        "label": "SDXL — Wai Illustrious SDXL (anime)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Anime\\waiIllustriousSDXL_v160-a5f5.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 5.5, "denoise": 0.58,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "masterpiece, best quality, very aesthetic, absurdres",
        "negative_hint": "worst quality, low quality, lowres, bad anatomy",
    },
    # ── SDXL Base ───────────────────────────────────────────────────────
    {
        "label": "SDXL — Albedo Base XL (versatile)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Base\\AlbedoBaseXL.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0, "denoise": 0.62,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "high quality, detailed, professional",
        "negative_hint": "lowres, bad anatomy, worst quality, blurry",
    },
    {
        "label": "SDXL — Base 1.0 (reference)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Base\\sd_xl_base_1.0.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "normal",
        "prompt_hint": "high quality, detailed",
        "negative_hint": "lowres, worst quality, blurry",
    },
    # ── SDXL Cartoon / 3D ──────────────────────────────────────────────
    {
        "label": "SDXL — Modern Disney XL v3 (cartoon/3D)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Cartoon-3D\\modernDisneyXL_v3.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 7.0, "denoise": 0.60,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "disney style, 3d render, cartoon, vibrant colors, cinematic lighting",
        "negative_hint": "photorealistic, blurry, low quality, deformed",
    },
    {
        "label": "SDXL — Nova Cartoon XL v6 (cartoon/3D)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Cartoon-3D\\novaCartoonXL_v60.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 7.0, "denoise": 0.58,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "cartoon style, vibrant, illustration, detailed",
        "negative_hint": "photorealistic, blurry, deformed, low quality",
    },
    # ── SDXL Realistic ─────────────────────────────────────────────────
    {
        "label": "SDXL — CyberRealistic Pony v1.6 (realistic)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\cyberrealisticPony_v160.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 6.5, "denoise": 0.58,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "score_9, score_8_up, photorealistic, ultra detailed, sharp",
        "negative_hint": "score_4, score_3, blurry, cartoon, deformed",
    },
    {
        "label": "SDXL — JibMix Realistic XL v1.8 (photo)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\jibMixRealisticXL_v180SkinSupreme.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 6.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "photorealistic, professional photography, natural skin, sharp focus",
        "negative_hint": "painting, cartoon, deformed, blurry, overexposed",
    },
    {
        "label": "SDXL — Juggernaut XL Ragnarok (realistic)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\juggernautXL_ragnarok.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 6.0, "denoise": 0.58,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "photorealistic, cinematic, highly detailed, professional",
        "negative_hint": "cartoon, anime, blurry, deformed, low quality",
    },
    {
        "label": "SDXL — Juggernaut XL v9 (photo)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 6.5, "denoise": 0.58,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "photorealistic, cinematic lighting, sharp focus, professional",
        "negative_hint": "cartoon, painting, deformed, blurry, worst quality",
    },
    {
        "label": "SDXL — ZavyChroma XL v10 (realistic)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\zavychromaxl_v100.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 6.5, "denoise": 0.60,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "photorealistic, vivid, cinematic, highly detailed",
        "negative_hint": "cartoon, blurry, deformed, worst quality",
    },
    # ── Illustrious ────────────────────────────────────────────────────
    {
        "label": "Illustrious — IlustReal v5 (semi-real)",
        "arch": "sdxl",
        "ckpt": "Illustrious\\ilustreal_v50VAE.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 5.0, "denoise": 0.58,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "masterpiece, best quality, very aesthetic, semi-realistic",
        "negative_hint": "worst quality, low quality, blurry, bad anatomy",
    },
    {
        "label": "Illustrious — Sloppy Messy Mix v1 (artistic)",
        "arch": "sdxl",
        "ckpt": "Illustrious\\sloppyMessyMix_sloppyMessyMixV1.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 5.5, "denoise": 0.60,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "masterpiece, best quality, painterly, expressive",
        "negative_hint": "worst quality, low quality, blurry",
    },
    # ── Z-Image-Turbo (ZIT) ──────────────────────────────────────────
    # Fast distilled SDXL. Low steps (4-12), low CFG (1.0-3.0).
    # Supports standard SDXL LoRAs + its own ZIT LoRAs.
    {
        "label": "ZIT — Photo (fast 6-step)",
        "arch": "zit",
        "ckpt": "ZIT\\gonzalomoZpop_v30AIO.safetensors",
        "width": 1024, "height": 1024,
        "steps": 6, "cfg": 2.0, "denoise": 0.60,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "professional photograph of [subject], sharp focus, natural lighting, "
                       "realistic skin texture, high detail, 8k resolution",
        "negative_hint": "blurry, low quality, deformed, cartoon, painting, worst quality",
    },
    {
        "label": "ZIT — Portrait (fast 8-step)",
        "arch": "zit",
        "ckpt": "ZIT\\gonzalomoZpop_v30AIO.safetensors",
        "width": 832, "height": 1216,
        "steps": 8, "cfg": 2.5, "denoise": 0.55,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "close-up portrait photograph of [person], 85mm lens, soft bokeh, "
                       "natural studio lighting, detailed skin pores, sharp eyes, professional",
        "negative_hint": "blurry, deformed face, bad anatomy, cartoon, low quality",
    },
    {
        "label": "ZIT — Cinematic (8-step)",
        "arch": "zit",
        "ckpt": "ZIT\\gonzalomoZpop_v30AIO.safetensors",
        "width": 1216, "height": 832,
        "steps": 8, "cfg": 2.5, "denoise": 0.62,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "cinematic still of [scene], anamorphic lens, dramatic lighting, "
                       "shallow depth of field, film grain, color graded, 35mm film look",
        "negative_hint": "flat lighting, overexposed, blurry, low quality, cartoon",
    },
    {
        "label": "ZIT — Anime / Illustration (6-step)",
        "arch": "zit",
        "ckpt": "ZIT\\gonzalomoZpop_v30AIO.safetensors",
        "width": 1024, "height": 1024,
        "steps": 6, "cfg": 2.0, "denoise": 0.58,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "masterpiece, best quality, detailed anime illustration, vibrant colors, "
                       "sharp linework, dynamic lighting",
        "negative_hint": "worst quality, low quality, blurry, realistic, 3d, photograph",
    },
    {
        "label": "ZIT — Quality (12-step)",
        "arch": "zit",
        "ckpt": "ZIT\\gonzalomoZpop_v30AIO.safetensors",
        "width": 1024, "height": 1024,
        "steps": 12, "cfg": 3.0, "denoise": 0.60,
        "sampler": "dpmpp_2m", "scheduler": "karras",
        "prompt_hint": "ultra detailed, professional quality, sharp focus, vivid colors, "
                       "intricate details, high resolution",
        "negative_hint": "blurry, low quality, deformed, worst quality, low detail",
    },
    # ── Flux 2 Klein ───────────────────────────────────────────────────
    # No negative prompts — describe what you WANT, not what to avoid.
    # Prompts: natural language prose, no quality-tag stacking, first words matter most.
    {
        "label": "Flux 2 Klein 4B — Photo (fast)",
        "arch": "flux2klein",
        "ckpt": "Flux-2-Klein/flux2-klein-4b.safetensors",
        "width": 1024, "height": 1024,
        "steps": 4, "cfg": 1.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Photograph of [subject], natural light, sharp focus, realistic skin texture",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Photo (quality)",
        "arch": "flux2klein",
        "ckpt": "Flux-2-Klein/flux2-klein-9b.safetensors",
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 1.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Photograph of [subject], natural light, sharp focus, realistic skin texture",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Portrait",
        "arch": "flux2klein",
        "ckpt": "Flux-2-Klein/flux2-klein-9b.safetensors",
        "width": 896, "height": 1152,
        "steps": 20, "cfg": 1.0, "denoise": 0.60,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Portrait photograph of [person], 85mm lens, soft bokeh background, natural studio lighting, ultra-detailed skin texture, sharp eyes",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Artistic / Painterly",
        "arch": "flux2klein",
        "ckpt": "Flux-2-Klein/flux2-klein-9b.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 1.0, "denoise": 0.72,
        "sampler": "euler", "scheduler": "beta",
        "prompt_hint": "Oil painting of [subject], dramatic lighting, expressive brushwork, rich colors, gallery quality",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Cinematic",
        "arch": "flux2klein",
        "ckpt": "Flux-2-Klein/flux2-klein-9b.safetensors",
        "width": 1280, "height": 720,
        "steps": 20, "cfg": 1.0, "denoise": 0.68,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Cinematic still of [scene], anamorphic lens, golden hour light, shallow depth of field, film grain, 35mm",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Inpaint / Refinement",
        "arch": "flux2klein",
        "ckpt": "Flux-2-Klein/flux2-klein-9b.safetensors",
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 1.0, "denoise": 0.50,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Seamlessly continuing the existing image, matching lighting and style",
        "negative_hint": "",
    },
    # ── Flux 1 Dev ─────────────────────────────────────────────────────
    # Natural prose prompts — no keyword stacking, no parenthesis weights.
    # No negative prompt support (leave empty); use positive framing instead.
    # Stubborn about realism — explicitly request "flat illustration", "anime",
    # "oil painting" etc. for non-photorealistic output.
    {
        "label": "Flux 1 Dev — Photo / Realistic",
        "arch": "flux1dev",
        "ckpt": "Flux\\FLUX1 Dev fp8.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 3.5, "denoise": 0.65,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "A photograph of [subject], natural light, sharp focus, "
                       "professional photography, realistic skin texture, "
                       "shallow depth of field",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Portrait",
        "arch": "flux1dev",
        "ckpt": "Flux\\FLUX1 Dev fp8.safetensors",
        "width": 896, "height": 1152,
        "steps": 25, "cfg": 3.0, "denoise": 0.60,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Close-up portrait of [person], 85mm lens, soft bokeh background, "
                       "three-point studio lighting, ultra-detailed skin texture, "
                       "sharp eyes with catchlights",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Landscape / Scene",
        "arch": "flux1dev",
        "ckpt": "Flux\\FLUX1 Dev fp8.safetensors",
        "width": 1280, "height": 768,
        "steps": 25, "cfg": 3.0, "denoise": 0.68,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "A wide establishing shot of [scene], golden hour light, "
                       "dramatic sky, deep depth of field, landscape photography",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Anime / Illustration",
        "arch": "flux1dev",
        "ckpt": "Flux\\FLUX1 Dev fp8.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 3.5, "denoise": 0.72,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Anime illustration of [subject], flat cel shading, "
                       "thick outlines, vibrant colors, manga style, hand-drawn",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Cinematic",
        "arch": "flux1dev",
        "ckpt": "Flux\\FLUX1 Dev fp8.safetensors",
        "width": 1280, "height": 720,
        "steps": 25, "cfg": 3.0, "denoise": 0.65,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Cinematic movie still of [scene], anamorphic lens flare, "
                       "warm color grading, 35mm film grain, dramatic lighting, "
                       "shallow depth of field",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Artistic / Painterly",
        "arch": "flux1dev",
        "ckpt": "Flux\\FLUX1 Dev fp8.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 3.5, "denoise": 0.75,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Oil painting of [subject], visible brushstrokes, "
                       "thick impasto texture, rich color palette, "
                       "gallery quality, impressionist style",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Detail / Upscale Pass",
        "arch": "flux1dev",
        "ckpt": "Flux\\FLUX1 Dev fp8.safetensors",
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 4.5, "denoise": 0.35,
        "sampler": "dpmpp_2m", "scheduler": "exponential",
        "prompt_hint": "Ultra sharp, highly detailed, enhanced textures, "
                       "crisp edges, high definition, matching existing style",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Schnell (fast)",
        "arch": "flux1dev",
        "ckpt": "Flux-1-Dev/flux1-schnell.safetensors",
        "width": 1024, "height": 1024,
        "steps": 4, "cfg": 1.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "A photograph of [subject], natural light, sharp focus",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Fill / Inpaint",
        "arch": "flux1dev",
        "ckpt": "Flux-1-Dev/flux1-fill-dev.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 3.0, "denoise": 0.85,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Replace [selected area] with [description], "
                       "seamlessly matching surrounding lighting and style",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Inpaint / Light Touch",
        "arch": "flux1dev",
        "ckpt": "Flux\\FLUX1 Dev fp8.safetensors",
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 2.5, "denoise": 0.45,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Refine [area], preserve surrounding style and lighting, "
                       "seamless result",
        "negative_hint": "",
    },
    # ── Flux Kontext ───────────────────────────────────────────────────
    # Instruction-based editing: describe WHAT to change, WHAT to preserve.
    # Formula: "[Change X] while [keeping/preserving Y], [style note]"
    # No negative prompts. Up to 3 LoRAs supported (Flux-1-Dev LoRAs compatible).
    # Requires ComfyUI v0.3.42+.
    {
        "label": "Flux Kontext Dev — Edit / Modify",
        "arch": "flux_kontext",
        "ckpt": "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 3.0, "denoise": 0.70,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Change [element] to [description] while keeping the rest "
                       "of the image exactly the same",
        "negative_hint": "",
    },
    {
        "label": "Flux Kontext Dev — Replace Element",
        "arch": "flux_kontext",
        "ckpt": "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 3.0, "denoise": 0.75,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Replace [object/person] with [description], "
                       "maintaining the same lighting, perspective, and background",
        "negative_hint": "",
    },
    {
        "label": "Flux Kontext Dev — Style Transfer",
        "arch": "flux_kontext",
        "ckpt": "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 3.5, "denoise": 0.80,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Render the image in [target style, e.g. oil painting / anime / "
                       "watercolor] while preserving the composition and subjects",
        "negative_hint": "",
    },
    {
        "label": "Flux Kontext Dev — Background Swap",
        "arch": "flux_kontext",
        "ckpt": "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 3.0, "denoise": 0.75,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Replace the background with [new environment], "
                       "keeping the subject, pose, and lighting direction identical",
        "negative_hint": "",
    },
    {
        "label": "Flux Kontext Dev — Portrait Retouch",
        "arch": "flux_kontext",
        "ckpt": "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
        "width": 896, "height": 1152,
        "steps": 20, "cfg": 2.5, "denoise": 0.55,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Refine the portrait — [change description] — "
                       "while preserving the person's identity and expression",
        "negative_hint": "",
    },
    {
        "label": "Flux Kontext Dev — Localized Inpaint",
        "arch": "flux_kontext",
        "ckpt": "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 2.5, "denoise": 0.60,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Fix [selected region] to show [description], "
                       "seamlessly blending with the surrounding image",
        "negative_hint": "",
    },
    {
        "label": "Flux Kontext Dev — Preserve / Light Touch",
        "arch": "flux_kontext",
        "ckpt": "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 2.5, "denoise": 0.35,
        "sampler": "dpmpp_2m", "scheduler": "sgm_uniform",
        "prompt_hint": "Subtly [enhancement] while preserving the overall image, "
                       "matching existing lighting and color exactly",
        "negative_hint": "",
    },
]

# ═══════════════════════════════════════════════════════════════════════════
#  Architecture → compatible LoRA folder prefixes
# ═══════════════════════════════════════════════════════════════════════════

ARCH_LORA_PREFIXES = {
    # Maps each model architecture to the LoRA subfolder prefixes it's
    # compatible with. When the user selects a model preset, only LoRAs
    # whose server-reported path starts with one of these prefixes are
    # shown in the UI dropdown. This prevents mismatches (e.g. SDXL LoRAs
    # on a Flux model) which would cause ComfyUI errors.
    "sd15":         [],                                                      # no dedicated LoRA folders yet
    "sdxl":         ["SDXL/", "Illustrious/", "Illustrious-Pony/", "Pony/"],
    "zit":          ["Z-Image-Turbo/"],
    "flux2klein":   ["Flux-2-Klein/"],
    "flux1dev":     ["Flux-1-Dev/"],
    "flux_kontext": ["Flux-Kontext/", "Flux-1-Dev/"],                      # Kontext can use Dev LoRAs too
}


# ═══════════════════════════════════════════════════════════════════════════
#  Scene / Subject Presets — beginner-friendly prompt templates per category
# ═══════════════════════════════════════════════════════════════════════════
# Keyed by (architecture, category). When a user picks a scene preset,
# the prompt and negative are filled in automatically — zero typing needed.
# The first entry "(custom)" means the user writes their own prompt.
#
# Architecture groups:
#   "sd15"         — SD 1.5 models (Juggernaut Reborn, Realistic Vision, etc.)
#   "sdxl"         — SDXL realistic/general models
#   "sdxl_anime"   — SDXL anime/pony models (NoobAI, Nova Anime, Wai, CyberRealistic Pony)
#   "sdxl_cartoon" — SDXL cartoon/3D (Modern Disney, Nova Cartoon)
#   "flux"         — Flux 1 Dev and Flux 2 Klein (natural language, no quality tags)
#   "flux_kontext" — Flux Kontext (edit instructions, not descriptions)

def _scene_arch(model_arch, model_label=""):
    """Map a MODEL_PRESETS arch + label to the scene preset architecture group."""
    label_lower = model_label.lower()
    if model_arch in ("flux1dev", "flux2klein"):
        return "flux"
    if model_arch == "flux_kontext":
        return "flux_kontext"
    if model_arch == "zit":
        return "sdxl"  # ZIT uses SDXL-style prompts
    if model_arch == "sd15":
        return "sd15"
    # SDXL sub-groups
    if any(kw in label_lower for kw in ("anime", "noob", "nova anime", "wai", "pony", "cyberrealistic pony")):
        return "sdxl_anime"
    if any(kw in label_lower for kw in ("disney", "cartoon", "nova cartoon")):
        return "sdxl_cartoon"
    return "sdxl"  # default for SDXL/Illustrious realistic

SCENE_PRESETS = [
    # ── Index 0: Custom (no auto-fill) ─────────────────────────────────
    {"label": "(custom — write your own)"},

    # ══════════════════════════════════════════════════════════════════════
    #  REALISTIC / PHOTO presets (sd15, sdxl, flux)
    # ══════════════════════════════════════════════════════════════════════

    # 1 ── Portrait (Headshot) ─────────────────────────────────────────
    {
        "label": "Portrait — Headshot",
        "prompts": {
            "sd15": (
                "close-up portrait photograph of [subject], 85mm lens, f/1.8, shallow depth of field, "
                "soft studio lighting, catchlights in eyes, ultra-detailed skin texture, sharp focus, "
                "photorealistic, professional headshot, RAW photo",
                "(deformed, distorted, disfigured:1.3), poorly drawn face, bad anatomy, extra limbs, "
                "blurry, out of focus, low quality, cartoon, painting"
            ),
            "sdxl": (
                "close-up portrait photograph of [subject], shot on Canon EOS R5 with 85mm f/1.4 lens, "
                "shallow depth of field, soft directional studio lighting, catchlights in eyes, "
                "ultra-detailed skin pores and texture, sharp focus on eyes, professional headshot, "
                "natural skin tones, 8k resolution",
                "(deformed, distorted, disfigured:1.3), poorly drawn face, mutation, extra limbs, "
                "blurry, bokeh on face, watermark, text, low quality, worst quality, cartoon"
            ),
            "flux": (
                "Professional headshot portrait of [subject]. Shot on a Canon EOS R5 with an 85mm "
                "f/1.4 lens at close range. Soft directional studio lighting creates gentle shadows "
                "on one side of the face. Sharp focus on the eyes with beautiful catchlights. "
                "Shallow depth of field blurs the background into creamy bokeh. Natural skin tones, "
                "visible pores and fine details. 8K resolution.",
                ""
            ),
        },
    },
    # 2 ── Portrait (Full Body) ────────────────────────────────────────
    {
        "label": "Portrait — Full Body",
        "prompts": {
            "sd15": (
                "full body portrait of [subject], standing pose, natural environment, "
                "35mm lens, f/2.8, soft natural lighting, sharp focus, detailed clothing, "
                "photorealistic, professional photography, RAW photo",
                "(deformed:1.3), bad anatomy, extra limbs, missing limbs, blurry, "
                "low quality, cropped, watermark"
            ),
            "sdxl": (
                "full body portrait of [subject], standing in [environment], shot on 35mm f/2.8, "
                "natural golden hour lighting, sharp focus head to toe, detailed clothing texture, "
                "photorealistic, editorial photography, high resolution",
                "(deformed, distorted:1.3), bad anatomy, bad proportions, extra limbs, "
                "missing limbs, blurry, watermark, worst quality, cartoon"
            ),
            "flux": (
                "Full body portrait of [subject] standing in [environment]. Shot on a 35mm lens "
                "at f/2.8. Golden hour natural lighting casts warm tones. Sharp focus from head "
                "to toe with detailed clothing texture. Professional editorial photography style. "
                "Natural body proportions and relaxed pose.",
                ""
            ),
        },
    },
    # 3 ── Product Photo ───────────────────────────────────────────────
    {
        "label": "Product Photo",
        "prompts": {
            "sd15": (
                "professional product photography of [product], centered on clean white background, "
                "soft box lighting, sharp focus, high detail, commercial photography, "
                "studio lighting setup, no shadows, RAW photo",
                "blurry, low quality, dark, cluttered background, text, watermark"
            ),
            "sdxl": (
                "professional commercial product photography of [product], centered on seamless "
                "white gradient background, three-point studio lighting with soft fill, "
                "crisp sharp focus, 100mm macro lens, high detail textures, clean minimalist "
                "composition, advertising quality, 8k",
                "blurry, dark, shadows, cluttered, text, watermark, worst quality, low quality"
            ),
            "flux": (
                "Professional commercial product photograph of [product] centered on a seamless "
                "white gradient background. Three-point studio lighting with soft diffused fill "
                "light. Shot with a 100mm macro lens for crisp detail. Clean minimalist composition. "
                "Advertising quality, suitable for e-commerce listing. 8K resolution.",
                ""
            ),
        },
    },
    # 4 ── Landscape ───────────────────────────────────────────────────
    {
        "label": "Landscape / Scenic",
        "prompts": {
            "sd15": (
                "breathtaking landscape photograph of [scene], golden hour lighting, "
                "dramatic sky, wide angle lens, deep depth of field, sharp throughout, "
                "vivid colors, National Geographic quality, RAW photo, 8k",
                "blurry, hazy, overexposed, flat lighting, low quality, watermark"
            ),
            "sdxl": (
                "breathtaking landscape photograph of [scene], shot during golden hour, "
                "dramatic cloud formations, wide-angle 16mm lens at f/11 for maximum sharpness, "
                "deep depth of field, vivid natural colors, leading lines, "
                "National Geographic quality, 8k ultrawide",
                "blurry, hazy, overexposed, flat lighting, desaturated, "
                "worst quality, low quality, watermark"
            ),
            "flux": (
                "Breathtaking landscape photograph of [scene] during golden hour. Shot with a "
                "16mm wide-angle lens at f/11 for maximum depth of field. Dramatic cloud "
                "formations in the sky with warm golden light. Vivid natural colors with "
                "leading lines drawing the eye into the scene. National Geographic quality "
                "with stunning detail from foreground to horizon.",
                ""
            ),
        },
    },
    # 5 ── Food Photography ────────────────────────────────────────────
    {
        "label": "Food Photography",
        "prompts": {
            "sd15": (
                "professional food photography of [dish], overhead angle, "
                "soft natural window light, shallow depth of field, appetizing presentation, "
                "rustic wooden table, garnish details, sharp focus, RAW photo",
                "blurry, dark, overcooked, unappetizing, low quality, messy"
            ),
            "sdxl": (
                "professional food photography of [dish], overhead 45-degree angle, "
                "soft natural window light with white bounce card, shallow depth of field, "
                "steam rising, appetizing presentation on rustic ceramic plate, "
                "garnish micro-herbs, wooden table, sharp focus, editorial quality, 8k",
                "blurry, dark, unappetizing, low quality, worst quality, overexposed"
            ),
            "flux": (
                "Professional food photograph of [dish] from a 45-degree overhead angle. "
                "Soft natural window light with a white bounce card for fill. Shallow depth "
                "of field focuses on the main dish with gentle steam rising. Appetizing "
                "presentation on a rustic ceramic plate with micro-herb garnish. "
                "Warm wooden table surface. Editorial quality food styling.",
                ""
            ),
        },
    },
    # 6 ── Architecture / Interior ─────────────────────────────────────
    {
        "label": "Architecture / Interior",
        "prompts": {
            "sd15": (
                "professional architectural photograph of [building/interior], "
                "symmetrical composition, dramatic lighting, tilt-shift lens, "
                "sharp lines, deep depth of field, clean modern design, "
                "Architectural Digest quality, RAW photo",
                "blurry, distorted, cluttered, low quality, watermark"
            ),
            "sdxl": (
                "professional architectural photograph of [building/interior], "
                "symmetrical composition, 24mm tilt-shift lens, dramatic natural lighting "
                "streaming through windows, sharp geometric lines, deep depth of field, "
                "clean design, Architectural Digest quality, 8k resolution",
                "blurry, distorted, cluttered, fisheye, worst quality, low quality, watermark"
            ),
            "flux": (
                "Professional architectural photograph of [building/interior]. Symmetrical "
                "composition shot with a 24mm tilt-shift lens. Dramatic natural light streams "
                "through large windows creating strong shadow patterns. Sharp geometric lines "
                "and deep depth of field. Clean modern design aesthetic. Architectural Digest "
                "magazine quality.",
                ""
            ),
        },
    },
    # 7 ── Fashion Editorial ───────────────────────────────────────────
    {
        "label": "Fashion Editorial",
        "prompts": {
            "sd15": (
                "high fashion editorial photograph of [model/outfit], dramatic studio lighting, "
                "dynamic pose, sharp focus on fabric texture, Vogue magazine quality, "
                "professional fashion photography, RAW photo",
                "(deformed:1.3), bad anatomy, blurry, low quality, amateur, watermark"
            ),
            "sdxl": (
                "high fashion editorial photograph of [model/outfit], dramatic Rembrandt lighting, "
                "dynamic pose showing garment flow, sharp focus on fabric texture and stitching, "
                "70mm lens, clean studio backdrop, Vogue magazine cover quality, "
                "professional retouching, 8k",
                "(deformed, distorted:1.3), bad anatomy, bad proportions, blurry, "
                "worst quality, amateur, watermark"
            ),
            "flux": (
                "High fashion editorial photograph of [model/outfit]. Dramatic Rembrandt "
                "lighting creates bold shadows. Dynamic pose shows the flow and drape of "
                "the garment. Shot on a 70mm lens with sharp focus on fabric texture. "
                "Clean studio backdrop. Vogue magazine cover quality with professional "
                "color grading.",
                ""
            ),
        },
    },
    # 8 ── Fantasy Art ─────────────────────────────────────────────────
    {
        "label": "Fantasy Art / Epic Scene",
        "prompts": {
            "sd15": (
                "epic fantasy art of [scene], dramatic volumetric lighting, "
                "magical atmosphere, highly detailed, cinematic composition, "
                "concept art quality, digital painting, masterpiece",
                "blurry, low quality, bad anatomy, amateur, flat lighting"
            ),
            "sdxl": (
                "epic fantasy art of [scene], dramatic god rays and volumetric lighting, "
                "magical glowing particles, cinematic wide composition, rich color palette, "
                "highly detailed environment and characters, concept art quality, "
                "digital painting masterpiece, trending on ArtStation, 8k",
                "blurry, low quality, bad anatomy, amateur, flat lighting, "
                "worst quality, deformed, text, watermark"
            ),
            "flux": (
                "Epic fantasy art depicting [scene]. Dramatic god rays pierce through clouds "
                "creating volumetric lighting. Magical glowing particles float in the air. "
                "Cinematic wide composition with rich jewel-tone color palette. Highly detailed "
                "environment with intricate architectural elements. Concept art quality with "
                "painterly brushwork. Award-winning fantasy illustration.",
                ""
            ),
        },
    },
    # 9 ── Cinematic / Film Still ──────────────────────────────────────
    {
        "label": "Cinematic / Film Still",
        "prompts": {
            "sd15": (
                "cinematic film still of [scene], anamorphic lens, dramatic lighting, "
                "shallow depth of field, film grain, color graded, 35mm film, "
                "movie scene quality, RAW photo",
                "blurry, flat lighting, overexposed, low quality, amateur"
            ),
            "sdxl": (
                "cinematic film still of [scene], shot on anamorphic 40mm lens, "
                "dramatic chiaroscuro lighting, shallow depth of field with oval bokeh, "
                "subtle film grain, teal and orange color grading, 35mm celluloid look, "
                "directed by Roger Deakins, IMAX quality, 8k",
                "blurry, flat lighting, overexposed, desaturated, "
                "worst quality, low quality, watermark, text"
            ),
            "flux": (
                "Cinematic film still of [scene]. Shot on an anamorphic 40mm lens with "
                "characteristic oval bokeh and lens flares. Dramatic chiaroscuro lighting "
                "with deep shadows and selective highlights. Subtle film grain texture. "
                "Teal and orange color grading reminiscent of a Roger Deakins production. "
                "35mm celluloid look. Widescreen 2.39:1 composition.",
                ""
            ),
        },
    },
    # 10 ── Street Photography ─────────────────────────────────────────
    {
        "label": "Street Photography",
        "prompts": {
            "sd15": (
                "candid street photograph of [scene], natural light, documentary style, "
                "35mm lens, f/5.6, decisive moment, urban environment, "
                "sharp focus, Henri Cartier-Bresson style, RAW photo",
                "posed, blurry, studio lighting, low quality, watermark"
            ),
            "sdxl": (
                "candid street photograph of [scene], natural ambient light, documentary style, "
                "35mm lens at f/5.6, decisive moment captured mid-action, busy urban environment, "
                "sharp focus with environmental context, authentic atmosphere, "
                "Henri Cartier-Bresson inspired, black and white optional, 8k",
                "posed, staged, blurry, studio lighting, worst quality, low quality, watermark"
            ),
            "flux": (
                "Candid street photograph of [scene] in a busy urban environment. Shot on a "
                "35mm lens at f/5.6 to keep both subject and environment in focus. Natural "
                "ambient light. A decisive moment captured mid-action. Documentary style with "
                "authentic atmosphere. Henri Cartier-Bresson inspired composition with leading "
                "lines and geometric framing.",
                ""
            ),
        },
    },
    # 11 ── Macro / Close-Up ───────────────────────────────────────────
    {
        "label": "Macro / Close-Up Detail",
        "prompts": {
            "sd15": (
                "extreme macro photograph of [subject], 100mm macro lens, f/2.8, "
                "ring light, incredible fine detail, shallow depth of field, "
                "sharp focus on subject, creamy bokeh background, RAW photo",
                "blurry, out of focus, low quality, noisy, watermark"
            ),
            "sdxl": (
                "extreme macro photograph of [subject], Canon 100mm f/2.8L macro lens, "
                "ring light with diffuser, incredible fine detail showing texture and structure, "
                "paper-thin depth of field, tack-sharp focus on subject, creamy pastel bokeh, "
                "scientific precision, 8k resolution",
                "blurry, out of focus, noisy, worst quality, low quality, watermark"
            ),
            "flux": (
                "Extreme macro photograph of [subject] shot with a Canon 100mm f/2.8L macro lens. "
                "Ring light with diffuser provides even illumination. Incredible fine detail "
                "showing texture, structure, and surface characteristics. Paper-thin depth of "
                "field with only the focal plane razor-sharp. Creamy pastel bokeh background. "
                "Scientific precision meets artistic composition.",
                ""
            ),
        },
    },

    # ══════════════════════════════════════════════════════════════════════
    #  ANIME / ILLUSTRATION presets (sdxl_anime)
    # ══════════════════════════════════════════════════════════════════════
    # 12
    {
        "label": "Anime — Character Portrait",
        "prompts": {
            "sdxl_anime": (
                "masterpiece, best quality, very aesthetic, absurdres, "
                "1girl/1boy, [character description], detailed face, beautiful detailed eyes, "
                "looking at viewer, upper body, dynamic lighting, vibrant colors, "
                "sharp linework, anime illustration",
                "worst quality, low quality, lowres, bad anatomy, bad hands, "
                "extra fingers, fewer fingers, cropped, username, watermark, "
                "blurry, jpeg artifacts, realistic, 3d"
            ),
        },
    },
    # 13
    {
        "label": "Anime — Action Scene",
        "prompts": {
            "sdxl_anime": (
                "masterpiece, best quality, very aesthetic, absurdres, "
                "1girl/1boy, [action description], dynamic pose, motion blur effects, "
                "speed lines, energy aura, dramatic angle from below, "
                "cinematic lighting, vivid colors, action anime style",
                "worst quality, low quality, lowres, bad anatomy, bad hands, "
                "stiff pose, static, blurry, jpeg artifacts, realistic"
            ),
        },
    },
    # 14
    {
        "label": "Anime — Slice of Life",
        "prompts": {
            "sdxl_anime": (
                "masterpiece, best quality, very aesthetic, absurdres, "
                "1girl/1boy, [everyday scene], soft warm lighting, cozy atmosphere, "
                "detailed background, school/cafe/park/room, gentle expression, "
                "pastel color palette, anime illustration",
                "worst quality, low quality, lowres, bad anatomy, dark, gloomy, "
                "blurry, cropped, watermark"
            ),
        },
    },
    # 15
    {
        "label": "Anime — Fantasy / Isekai",
        "prompts": {
            "sdxl_anime": (
                "masterpiece, best quality, very aesthetic, absurdres, "
                "1girl/1boy, [fantasy description], magical environment, glowing effects, "
                "floating particles, epic landscape, detailed armor/costume, "
                "dramatic sky, volumetric lighting, fantasy anime illustration",
                "worst quality, low quality, lowres, bad anatomy, modern clothing, "
                "realistic, photograph, blurry, watermark"
            ),
        },
    },
    # 16
    {
        "label": "Anime — Chibi / Cute",
        "prompts": {
            "sdxl_anime": (
                "masterpiece, best quality, very aesthetic, "
                "chibi, 1girl/1boy, [character], super deformed, big head, small body, "
                "cute expression, sparkle eyes, pastel colors, simple background, "
                "kawaii, adorable, sticker style",
                "worst quality, low quality, realistic, detailed anatomy, "
                "normal proportions, dark, scary, blurry"
            ),
        },
    },
    # 17
    {
        "label": "Anime — Wallpaper / Key Visual",
        "prompts": {
            "sdxl_anime": (
                "masterpiece, best quality, very aesthetic, absurdres, "
                "official art, [scene/character], incredibly detailed background, "
                "cinematic composition, dramatic lighting, vibrant saturated colors, "
                "wallpaper quality, key visual, anime illustration",
                "worst quality, low quality, lowres, bad anatomy, simple background, "
                "blurry, jpeg artifacts, watermark, text"
            ),
        },
    },

    # ══════════════════════════════════════════════════════════════════════
    #  CARTOON / 3D presets (sdxl_cartoon — Disney, Nova Cartoon)
    # ══════════════════════════════════════════════════════════════════════
    # 18
    {
        "label": "Cartoon — Character Design",
        "prompts": {
            "sdxl_cartoon": (
                "disney style, 3d render, [character description], expressive face, "
                "big eyes, smooth skin, vibrant colors, cinematic lighting, "
                "character design sheet, clean background, Pixar quality, "
                "cartoon, high detail",
                "photorealistic, blurry, deformed, low quality, dark, scary, "
                "bad anatomy, ugly"
            ),
        },
    },
    # 19
    {
        "label": "Cartoon — Scene / Environment",
        "prompts": {
            "sdxl_cartoon": (
                "disney style, 3d render, [scene description], vibrant colorful environment, "
                "whimsical architecture, magical atmosphere, volumetric lighting, "
                "Pixar movie scene, detailed background, cinematic composition, cartoon",
                "photorealistic, dark, gritty, blurry, low quality, flat lighting"
            ),
        },
    },
    # 20
    {
        "label": "Cartoon — Cute Animal / Mascot",
        "prompts": {
            "sdxl_cartoon": (
                "disney style, 3d render, adorable [animal/creature], big expressive eyes, "
                "soft fur/skin, rounded shapes, warm lighting, cute expression, "
                "Pixar character design, vibrant pastel colors, cartoon",
                "photorealistic, scary, dark, blurry, low quality, deformed, ugly"
            ),
        },
    },

    # ══════════════════════════════════════════════════════════════════════
    #  FLUX KONTEXT presets (edit instructions, not descriptions)
    # ══════════════════════════════════════════════════════════════════════
    # 21
    {
        "label": "Kontext — Change Outfit / Clothing",
        "prompts": {
            "flux_kontext": (
                "Change the person's outfit to [clothing description]. Keep the face, pose, "
                "and background exactly the same. Only modify the clothing.",
                ""
            ),
        },
    },
    # 22
    {
        "label": "Kontext — Change Background",
        "prompts": {
            "flux_kontext": (
                "Replace the background with [new background]. Keep the subject exactly the "
                "same, including their pose, expression, and lighting on their face.",
                ""
            ),
        },
    },
    # 23
    {
        "label": "Kontext — Age / Appearance Edit",
        "prompts": {
            "flux_kontext": (
                "Make the person look [younger/older/description]. Keep everything else "
                "about the image the same, including background and clothing.",
                ""
            ),
        },
    },
    # 24
    {
        "label": "Kontext — Add Object / Element",
        "prompts": {
            "flux_kontext": (
                "Add [object/element] to the scene. Place it [location]. Keep everything "
                "else in the image unchanged.",
                ""
            ),
        },
    },
    # 25
    {
        "label": "Kontext — Style / Color Shift",
        "prompts": {
            "flux_kontext": (
                "Transform this image into [style: e.g. watercolor painting, pencil sketch, "
                "pop art, oil painting, noir]. Keep the composition and subject the same.",
                ""
            ),
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  Inpaint Refinement Presets — body-part-specific prompts, LoRAs, settings
# ═══════════════════════════════════════════════════════════════════════════
# These presets auto-fill the inpaint dialog with optimized prompts, LoRAs,
# and generation parameters for fixing specific body parts or applying
# creative effects. When the user selects one, _on_refinement_changed()
# populates all relevant fields.
#
# Each entry:
#   label          — display name in the inpaint refinement dropdown
#   prompt         — positive prompt text (overwrites user's prompt)
#   negative       — negative prompt text
#   denoise        — override denoise strength (None = keep model default)
#   cfg_boost      — added to the model's base CFG (e.g. +1.0 for stronger guidance)
#   steps_override — override step count (None = keep model default)
#   loras          — dict of arch → [(lora_path, model_strength, clip_strength), ...]
#                    auto-selected if the LoRA exists on the server
# The first LoRA in each list is the primary recommendation; extras are stacked.

INPAINT_REFINEMENTS = [
    {
        "label": "(none — manual prompt)",
        "prompt": "",
        "negative": "",
        "denoise": None,
        "cfg_boost": 0,
        "steps_override": None,
        "loras": {},
    },
    # ── Hands & Fingers ────────────────────────────────────────────────
    {
        "label": "Fix Hands / Fingers",
        "prompt": "perfect hands, five fingers on each hand, correct finger count, natural hand pose, "
                  "realistic hand anatomy, detailed knuckles and nails, well-proportioned fingers",
        "negative": "bad hands, extra fingers, fewer fingers, fused fingers, mutated hands, "
                    "deformed fingers, missing fingers, ugly hands, extra digit, too many fingers",
        "denoise": 0.78,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Body\\HandFineTuning_XL.safetensors", 0.85, 0.85),
                           ("SDXL\\Body\\hand 5.5.safetensors", 0.6, 0.6)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Eyes ───────────────────────────────────────────────────────────
    {
        "label": "Fix Eyes / Iris Detail",
        "prompt": "beautiful detailed eyes, perfect symmetrical eyes, clear sharp iris, "
                  "realistic eye reflections, natural eye color, correct eye anatomy, "
                  "detailed eyelashes, properly aligned pupils",
        "negative": "asymmetric eyes, misaligned eyes, deformed iris, bad eyes, "
                    "cross-eyed, glowing eyes, empty eyes, dead eyes, uneven eyes",
        "denoise": 0.65,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Eyes_High_Definition-000007.safetensors", 0.8, 0.8)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Face / Portrait ───────────────────────────────────────────────
    {
        "label": "Refine Face / Portrait",
        "prompt": "beautiful face, perfect facial features, natural skin texture, "
                  "detailed facial structure, clear complexion, realistic portrait, "
                  "well-defined jawline, natural expression, symmetrical face",
        "negative": "deformed face, ugly face, asymmetric face, blurry face, "
                    "distorted features, bad proportions, uncanny valley, disfigured",
        "denoise": 0.62,
        "cfg_boost": 0.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/BFS_head_v1_flux-klein_9b_rank128.safetensors", 0.8, 0.8)],
            "flux1dev":   [("Flux-1-Dev/Detail/flux_face_detail.safetensors", 0.7, 0.7)],
            "flux_kontext": [],
        },
    },
    # ── Teeth / Mouth ─────────────────────────────────────────────────
    {
        "label": "Fix Teeth / Mouth",
        "prompt": "perfect teeth, natural white teeth, correct dental anatomy, "
                  "properly aligned teeth, realistic mouth, natural lips, "
                  "healthy gums, natural smile",
        "negative": "bad teeth, missing teeth, extra teeth, deformed mouth, "
                    "broken teeth, ugly teeth, distorted jaw, melted lips",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Teefs-000007.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Skin Texture / Detail ─────────────────────────────────────────
    {
        "label": "Enhance Skin Texture",
        "prompt": "detailed skin texture, realistic skin pores, natural skin surface, "
                  "subsurface scattering, high definition skin, photorealistic skin detail",
        "negative": "plastic skin, smooth plastic, waxy skin, artificial skin, "
                    "airbrushed, oversmoothed, blurry skin, painted skin",
        "denoise": 0.45,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\skin texture style v4.safetensors", 0.75, 0.75),
                           ("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/K9bSh4rpD3tails.safetensors", 0.7, 0.7)],
            "flux1dev":   [("Flux-1-Dev/Detail/add_detail.safetensors", 0.7, 0.7)],
            "flux_kontext": [],
        },
    },
    # ── Hair ──────────────────────────────────────────────────────────
    {
        "label": "Fix Hair / Hairstyle",
        "prompt": "beautiful detailed hair, natural hair strands, realistic hair texture, "
                  "individual hair strands visible, shiny healthy hair, well-groomed hair, "
                  "natural hair flow, volumetric hair",
        "negative": "bad hair, plastic hair, merged hair clumps, bald patches, "
                    "unnatural hair, wig-like, stiff hair, flat hair, no hair detail",
        "denoise": 0.68,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.65, 0.65)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/K9bSh4rpD3tails.safetensors", 0.6, 0.6)],
            "flux1dev":   [("Flux-1-Dev/Detail/add_detail.safetensors", 0.6, 0.6)],
            "flux_kontext": [],
        },
    },
    # ── Feet / Toes ───────────────────────────────────────────────────
    {
        "label": "Fix Feet / Toes",
        "prompt": "perfect feet, five toes on each foot, correct toe count, "
                  "natural foot anatomy, detailed toes and toenails, realistic feet, "
                  "well-proportioned feet",
        "negative": "bad feet, extra toes, fused toes, deformed feet, "
                    "missing toes, ugly feet, malformed toes, mutated feet",
        "denoise": 0.75,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [],
            "zit":        [("Z-Image-Turbo\\feet v2.1.safetensors", 0.8, 0.8)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Body Anatomy / Proportions ────────────────────────────────────
    {
        "label": "Fix Body Anatomy",
        "prompt": "correct human anatomy, natural body proportions, realistic body structure, "
                  "proper limb length, natural muscle definition, anatomically correct, "
                  "well-proportioned body",
        "negative": "bad anatomy, extra limbs, missing limbs, deformed body, "
                    "disproportionate, mutated, fused limbs, twisted torso, broken anatomy",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Body\\HandFineTuning_XL.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/Sliders/klein_slider_anatomy_9B_v1.5.safetensors", 0.8, 0.8)],
            "flux1dev":   [("Flux-1-Dev/Detail/add_detail.safetensors", 0.5, 0.5)],
            "flux_kontext": [],
        },
    },
    # ── Ears ──────────────────────────────────────────────────────────
    {
        "label": "Fix Ears",
        "prompt": "perfect ears, natural ear shape, detailed ear anatomy, "
                  "realistic ear, symmetrical ears, properly attached ears, correct ear placement",
        "negative": "deformed ears, missing ears, extra ears, melted ears, "
                    "oversized ears, badly shaped ears, asymmetric ears",
        "denoise": 0.65,
        "cfg_boost": 0.5,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.6, 0.6)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Nose ──────────────────────────────────────────────────────────
    {
        "label": "Fix Nose",
        "prompt": "perfect nose, natural nose shape, detailed nostril anatomy, "
                  "realistic nose, well-defined nose bridge, natural nose proportions, "
                  "symmetrical nose",
        "negative": "deformed nose, crooked nose, melted nose, flat nose, "
                    "missing nose, blob nose, badly shaped nose",
        "denoise": 0.62,
        "cfg_boost": 0.5,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Neck / Shoulders ──────────────────────────────────────────────
    {
        "label": "Fix Neck / Shoulders",
        "prompt": "natural neck, correct neck proportions, realistic shoulder anatomy, "
                  "proper collarbone detail, natural neck-to-shoulder transition, "
                  "well-defined shoulders",
        "negative": "long neck, broken neck, deformed shoulders, missing neck, "
                    "twisted neck, extra shoulders, giraffe neck, merged neck",
        "denoise": 0.68,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/Sliders/klein_slider_anatomy_9B_v1.5.safetensors", 0.6, 0.6)],
            "flux1dev":   [("Flux-1-Dev/Detail/add_detail.safetensors", 0.4, 0.4)],
            "flux_kontext": [],
        },
    },
    # ── Clothing / Fabric ─────────────────────────────────────────────
    {
        "label": "Fix Clothing / Fabric",
        "prompt": "detailed clothing, realistic fabric texture, natural cloth folds, "
                  "proper garment draping, wrinkle detail, high quality textile, "
                  "correct clothing anatomy",
        "negative": "deformed clothing, melted fabric, missing clothing parts, "
                    "bad cloth physics, floating clothing, clipping, merged clothing",
        "denoise": 0.65,
        "cfg_boost": 0.5,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/FTextureTransfer_F29B_V2.1.safetensors", 0.6, 0.6)],
            "flux1dev":   [("Flux-1-Dev/Detail/add_detail.safetensors", 0.5, 0.5)],
            "flux_kontext": [],
        },
    },
    # ── Background / Scene ────────────────────────────────────────────
    {
        "label": "Fix Background / Scene",
        "prompt": "detailed background, realistic environment, natural scenery, "
                  "high quality background, sharp background detail, "
                  "consistent perspective, proper lighting",
        "negative": "blurry background, distorted background, bad perspective, "
                    "floating objects, impossible architecture, warped scene",
        "denoise": 0.72,
        "cfg_boost": 0.5,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.6, 0.6)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
            "flux1dev":   [("Flux-1-Dev/Detail/add_detail.safetensors", 0.5, 0.5)],
            "flux_kontext": [],
        },
    },
    # ── General Detail Enhancer ───────────────────────────────────────
    {
        "label": "Sharpen / Add Detail",
        "prompt": "ultra sharp, highly detailed, intricate details, "
                  "enhanced textures, crisp edges, high definition, 8k quality",
        "negative": "blurry, soft, low detail, smooth, flat, low resolution, "
                    "out of focus, motion blur",
        "denoise": 0.40,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.8, 0.8),
                           ("SDXL\\Detail\\rdtdrp.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/K9bSh4rpD3tails.safetensors", 0.8, 0.8)],
            "flux1dev":   [("Flux-1-Dev/Detail/add_detail.safetensors", 0.8, 0.8)],
            "flux_kontext": [],
        },
    },
    # ── Realism Boost ─────────────────────────────────────────────────
    {
        "label": "Boost Realism / Photo Quality",
        "prompt": "photorealistic, RAW photo, DSLR quality, natural lighting, "
                  "realistic texture, professional photography, film grain, "
                  "natural color grading",
        "negative": "cartoon, anime, painting, illustration, digital art, "
                    "artificial, fake, CGI, unrealistic, oversaturated",
        "denoise": 0.50,
        "cfg_boost": 0.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.65, 0.65),
                           ("SDXL\\Detail\\skin texture style v4.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/ultra_real_v2.safetensors", 0.7, 0.7)],
            "flux1dev":   [("Flux-1-Dev/Realism/flux_realism.safetensors", 0.7, 0.7)],
            "flux_kontext": [],
        },
    },
    # ── Remove Artifacts / Clean Up ───────────────────────────────────
    {
        "label": "Remove Artifacts / Clean Up",
        "prompt": "clean image, artifact free, smooth transition, natural appearance, "
                  "correct details, consistent style, seamless",
        "negative": "artifacts, glitch, noise, compression artifacts, "
                    "banding, jpeg artifacts, posterization, pixelation",
        "denoise": 0.55,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/FK4B_Image_Repair_V1.safetensors", 0.8, 0.8)],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },

    # ═══════════════════════════════════════════════════════════════════
    #  CREATIVE / EFFECT RENDERS
    # ═══════════════════════════════════════════════════════════════════

    # ── Oily / Wet Skin ───────────────────────────────────────────────
    {
        "label": "✦ Oily / Wet Skin Effect",
        "prompt": "oily skin, wet skin, glistening skin, shiny skin, dewy skin, "
                  "wet body, skin highlights, sweat, glossy complexion, moisture on skin",
        "negative": "dry skin, matte skin, powder, flat lighting, dull skin",
        "denoise": 0.55,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Oily skin style xl v1.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Effect\\OiledSkin_Zit_Turbo_V1.safetensors", 0.85, 0.85)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Sweat / Exertion ──────────────────────────────────────────────
    {
        "label": "✦ Sweat / Exertion Effect",
        "prompt": "sweaty skin, beads of sweat, perspiration, glistening with sweat, "
                  "exertion, post-workout, wet with sweat, sweat dripping, athletic",
        "negative": "dry skin, clean, powder, matte, cold, frozen",
        "denoise": 0.55,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Sweating my balls of mate.safetensors", 0.8, 0.8),
                           ("SDXL\\Oily skin style xl v1.safetensors", 0.4, 0.4)],
            "zit":        [("Z-Image-Turbo\\Effect\\OiledSkin_Zit_Turbo_V1.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Water Droplets ────────────────────────────────────────────────
    {
        "label": "✦ Water Droplets Effect",
        "prompt": "water droplets on skin, water drops, dew drops, rain drops, "
                  "wet surface, water beading, crystal clear droplets, morning dew, "
                  "water splash, droplet reflections",
        "negative": "dry, dusty, matte, powder, no water, arid",
        "denoise": 0.58,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Oily skin style xl v1.safetensors", 0.5, 0.5)],
            "zit":        [("Z-Image-Turbo\\Effect\\water_droplet_effect_zit_v1.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Chrome / Metallic Skin ────────────────────────────────────────
    {
        "label": "✦ Chrome / Metallic Skin",
        "prompt": "chrome skin, metallic skin, liquid metal surface, silver chrome body, "
                  "reflective metallic, mercury skin, shiny metal texture, "
                  "polished chrome, mirror-like skin",
        "negative": "matte, natural skin, realistic skin, dull, flat, organic, flesh tone",
        "denoise": 0.75,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\MetallicGoldSilver_skinbody_paint-000019.safetensors", 0.9, 0.9)],
            "zit":        [("Z-Image-Turbo\\Effect\\93PXB5SENBFN8NEYSRYZA1DVX0-Chrome skin.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Cyborg / Robot Parts ──────────────────────────────────────────
    {
        "label": "✦ Cyborg / Robot Parts",
        "prompt": "cyborg, mechanical parts, robotic body, cybernetic implants, "
                  "exposed machinery, glowing circuits, metal plates, bionic, "
                  "android, tech implants, wires under skin, LED accents",
        "negative": "fully human, natural, organic only, no technology, medieval, rustic",
        "denoise": 0.78,
        "cfg_boost": 1.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Concept\\ARobotGirls_Concept-12.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Effect\\Z-cyborg.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Gothic Dark Fantasy ───────────────────────────────────────────
    {
        "label": "✦ Gothic Dark Fantasy",
        "prompt": "gothic dark fantasy, ethereal gothic elegance, dark atmosphere, "
                  "moody shadows, dramatic dark lighting, mystical, dark beauty, "
                  "occult aesthetic, dark romantic, candlelight, velvet darkness",
        "negative": "bright, cheerful, colorful, sunny, cartoon, daytime, flat lighting",
        "denoise": 0.68,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\Ethereal_Gothic_Elegance.safetensors", 0.85, 0.85),
                           ("SDXL\\Style\\dark.safetensors", 0.5, 0.5)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Chiaroscuro Lighting ──────────────────────────────────────────
    {
        "label": "✦ Chiaroscuro / Dramatic Lighting",
        "prompt": "chiaroscuro lighting, dramatic light and shadow, Rembrandt lighting, "
                  "high contrast, deep shadows, single light source, volumetric light, "
                  "film noir lighting, baroque lighting, tenebrism",
        "negative": "flat lighting, even lighting, overexposed, no shadows, "
                    "bright everywhere, flash photography, washed out",
        "denoise": 0.62,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\Chiaroscuro  film style pony v1.safetensors", 0.85, 0.85),
                           ("SDXL\\Slider\\Dramatic Lighting Slider.safetensors", 0.6, 0.6)],
            "zit":        [("Z-Image-Turbo\\Style\\zy_CinematicShot_zit.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Cinematic Film Look ───────────────────────────────────────────
    {
        "label": "✦ Cinematic Film Look",
        "prompt": "cinematic photography, film grain, anamorphic lens, "
                  "cinematic color grading, movie still, depth of field, "
                  "professional cinematography, 35mm film, warm color palette",
        "negative": "amateur, smartphone, flat, digital noise, harsh flash, "
                    "oversaturated, snapshot, selfie",
        "denoise": 0.55,
        "cfg_boost": 0.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\Cinematic Photography Style pony v1.safetensors", 0.8, 0.8),
                           ("SDXL\\Style\\epiCPhotoXL-Derp2.safetensors", 0.4, 0.4)],
            "zit":        [("Z-Image-Turbo\\Style\\zy_CinematicShot_zit.safetensors", 0.85, 0.85)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Raw Camera / DSLR ─────────────────────────────────────────────
    {
        "label": "✦ Raw Camera / DSLR Photo",
        "prompt": "RAW photo, DSLR, professional camera, natural lighting, "
                  "shallow depth of field, bokeh, lens flare, sharp focus, "
                  "unedited photograph, authentic colors, film emulation",
        "negative": "painting, illustration, digital art, CGI, airbrushed, "
                    "overprocessed, HDR, cartoon, anime",
        "denoise": 0.50,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Style\\RawCam_250_v1.safetensors", 0.8, 0.8),
                           ("SDXL\\Style\\epicNewPhoto.safetensors", 0.4, 0.4)],
            "zit":        [("Z-Image-Turbo\\Style\\SonyAlpha_ZImage.safetensors", 0.8, 0.8)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── 35mm Telephoto Lens ───────────────────────────────────────────
    {
        "label": "✦ Telephoto / 600mm Lens",
        "prompt": "600mm telephoto lens, extreme bokeh, compressed perspective, "
                  "subject isolation, creamy background blur, long focal length, "
                  "professional sports photography, wildlife photography style",
        "negative": "wide angle, fisheye, everything in focus, deep DOF, "
                    "distortion, flat, no blur",
        "denoise": 0.52,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Style\\epiCPhotoXL-Derp2.safetensors", 0.6, 0.6)],
            "zit":        [("Z-Image-Turbo\\Style\\600mm_Lens-V2_TriggerIs_600mm.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Ghibli / Anime Style ─────────────────────────────────────────
    {
        "label": "✦ Ghibli / Anime Painterly",
        "prompt": "studio ghibli style, anime painting, hand-drawn animation, "
                  "soft watercolor, whimsical, miyazaki, painterly anime, "
                  "cel shading, warm natural palette, gentle atmosphere",
        "negative": "photorealistic, 3d render, CGI, harsh shadows, "
                    "sharp edges, dark, horror, gritty",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Style\\ghibli_last.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Style\\ZiTD3tailed4nime.safetensors", 0.8, 0.8)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── FaeTastic Fantasy ─────────────────────────────────────────────
    {
        "label": "✦ Fairy Tale / Fantasy Art",
        "prompt": "fairy tale illustration, fantasy art, magical atmosphere, "
                  "ethereal glow, enchanted, whimsical fantasy, storybook illustration, "
                  "dreamy, luminous, fantasy landscape, magical particles",
        "negative": "realistic, modern, urban, gritty, dark, horror, mundane, "
                    "photographic, plain",
        "denoise": 0.70,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Style\\SDXLFaeTastic2400.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Style\\z-image-illustria-01.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── 80s Fantasy Movie ─────────────────────────────────────────────
    {
        "label": "✦ 80s Fantasy Movie Style",
        "prompt": "80s fantasy movie, retro fantasy, practical effects, "
                  "1980s film aesthetic, sword and sorcery, VHS quality, "
                  "vintage fantasy, Conan the Barbarian style, matte painting background, "
                  "old school special effects, film grain, warm tones",
        "negative": "modern, clean digital, CGI, photorealistic, contemporary, "
                    "minimalist, sleek",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Glitch / Digital Error ────────────────────────────────────────
    {
        "label": "✦ Glitch / Digital Error",
        "prompt": "glitch art, digital corruption, pixel sorting, data moshing, "
                  "RGB split, scan lines, corrupted image, VHS glitch, "
                  "digital artifact aesthetic, broken data, cyberpunk glitch",
        "negative": "clean, perfect, smooth, natural, analog, traditional, "
                    "high quality, no artifacts",
        "denoise": 0.70,
        "cfg_boost": 1.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Concept\\err0rFv1.6.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Effect\\EFFECTSp001_zit.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Slime / Wet & Messy ───────────────────────────────────────────
    {
        "label": "✦ Slime / Wet & Messy (WAM)",
        "prompt": "covered in slime, green slime, gunge, wet and messy, "
                  "dripping slime, splattered, gooey, splosh, viscous liquid, "
                  "slime dripping from body",
        "negative": "clean, dry, pristine, neat, tidy, powder, matte",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 28,
        "loras": {
            "sdxl":       [],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Freckles / Skin Detail ────────────────────────────────────────
    {
        "label": "✦ Add Freckles",
        "prompt": "freckles, natural freckles, sun-kissed freckles across cheeks, "
                  "detailed skin with freckles, cute freckle pattern, "
                  "beauty marks, speckled skin, natural imperfections",
        "negative": "airbrushed, smooth porcelain skin, no marks, plastic skin, "
                    "flawless, oversmoothed",
        "denoise": 0.48,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\skin texture style v4.safetensors", 0.6, 0.6)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Hyperdetailed Realism ─────────────────────────────────────────
    {
        "label": "✦ Hyperdetailed Realism",
        "prompt": "hyperdetailed, hyperrealistic, extreme detail, micro details, "
                  "pore-level detail, ultra sharp focus, photographic perfection, "
                  "8k resolution, extremely detailed textures",
        "negative": "soft, blurry, painterly, illustration, low detail, "
                    "flat, smooth, anime, cartoon",
        "denoise": 0.52,
        "cfg_boost": 1.0,
        "steps_override": 35,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\HyperdetailedRealismMJ7Pony.safetensors", 0.8, 0.8),
                           ("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.5, 0.5)],
            "zit":        [("Z-Image-Turbo\\Style\\Z-Image-Professional_Photographer_3500.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/K9bSR3al.safetensors", 0.7, 0.7),
                           ("Flux-2-Klein/K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
            "flux1dev":   [("Flux-1-Dev/Realism/flux_realism.safetensors", 0.7, 0.7),
                           ("Flux-1-Dev/Detail/add_detail.safetensors", 0.5, 0.5)],
            "flux_kontext": [],
        },
    },
    # ── 3D CG / Hi-Poly Render ────────────────────────────────────────
    {
        "label": "✦ 3D CG / Hi-Poly Render",
        "prompt": "3d cg render, hi-poly 3d model, subsurface scattering, "
                  "ray tracing, physically based rendering, unreal engine quality, "
                  "octane render, smooth 3d surface, studio lighting 3d",
        "negative": "2d, flat, painting, sketch, hand-drawn, low poly, "
                    "pixel art, traditional art, photograph",
        "denoise": 0.68,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\polyhedron_all_sdxl-000004.safetensors", 0.7, 0.7)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/hipoly_3dcg_v7-epoch-000012.safetensors", 0.85, 0.85)],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Amateur / Candid Photo ────────────────────────────────────────
    {
        "label": "✦ Amateur / Candid Photo",
        "prompt": "amateur photo, candid shot, casual snapshot, natural pose, "
                  "real photography, unposed, everyday life, authentic, "
                  "slightly imperfect, natural lighting, no filter",
        "negative": "professional, studio, posed, perfect, airbrushed, "
                    "magazine, retouched, glamour, high fashion",
        "denoise": 0.55,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Style\\zy_AmateurStyle_v2.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Style\\SonyAlpha_ZImage.safetensors", 0.6, 0.6)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Alien / Extraterrestrial ──────────────────────────────────────
    {
        "label": "✦ Alien / Extraterrestrial",
        "prompt": "alien, extraterrestrial being, alien skin texture, otherworldly, "
                  "sci-fi alien, non-human features, bioluminescent, "
                  "exotic alien anatomy, space creature, xenomorph-inspired",
        "negative": "human, normal, mundane, realistic human, everyday, "
                    "natural, earthly",
        "denoise": 0.78,
        "cfg_boost": 1.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Concept\\Aliens_AILF_SDXL.safetensors", 0.85, 0.85)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Shadow Circuit / Tech Pattern ─────────────────────────────────
    {
        "label": "✦ Circuit / Tech Pattern",
        "prompt": "circuit board pattern, tech circuits on skin, glowing circuit lines, "
                  "electronic pathways, neon traces, cybernetic tattoo, "
                  "tech vein pattern, digital circuitry, Tron-like lines",
        "negative": "organic, natural, no technology, plain, simple, "
                    "traditional tattoo, medieval",
        "denoise": 0.68,
        "cfg_boost": 1.0,
        "steps_override": 28,
        "loras": {
            "sdxl":       [],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Glow / Ethereal Light ─────────────────────────────────────────
    {
        "label": "✦ Glow / Ethereal Light",
        "prompt": "ethereal glow, soft radiant light, inner glow, angelic light, "
                  "bioluminescent, aura, glowing skin, divine light, "
                  "warm ethereal illumination, light particles",
        "negative": "dark, shadowy, gloomy, flat lighting, harsh shadows, "
                    "no glow, matte, dull",
        "denoise": 0.58,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/Sliders/klein_slider_glow.safetensors", 0.8, 0.8)],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Tentacles / Lovecraftian ──────────────────────────────────────
    {
        "label": "✦ Tentacles / Lovecraftian",
        "prompt": "tentacles, eldritch tentacles, lovecraftian horror, "
                  "organic tentacle growth, writhing tentacles, cosmic horror, "
                  "cthulhu inspired, deep sea creature, tentacle embrace",
        "negative": "clean, normal, mundane, no tentacles, ordinary, "
                    "cheerful, bright, simple",
        "denoise": 0.78,
        "cfg_boost": 1.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [],
            "zit":        [("Z-Image-Turbo\\Effect\\Tentacledv1.safetensors", 0.85, 0.85)],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Spaceship / Sci-Fi Vehicle ────────────────────────────────────
    {
        "label": "✦ Spaceship / Sci-Fi Vehicle",
        "prompt": "spaceship, sci-fi vehicle, futuristic spacecraft, "
                  "space cruiser, starship, detailed hull plating, "
                  "engine glow, space background, concept art spacecraft",
        "negative": "medieval, fantasy, modern car, realistic, natural, "
                    "low quality, blurry",
        "denoise": 0.75,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Concept\\Space_ship_concept.safetensors", 0.85, 0.85)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Portrait Upscale / Enhancement ────────────────────────────────
    {
        "label": "✦ Portrait Enhancement (Klein)",
        "prompt": "beautiful portrait, enhanced facial features, crisp details, "
                  "professional portrait photography, catchlights in eyes, "
                  "natural skin, high resolution face",
        "negative": "blurry, soft, low resolution, artifacts, distorted, "
                    "plastic, airbrushed, flat",
        "denoise": 0.42,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\StS_PonyXL_Detail_Slider_v1.4_iteration_3.safetensors", 0.7, 0.7)],
            "zit":        [("Z-Image-Turbo\\Style\\Z-Image-Professional_Photographer_3500.safetensors", 0.6, 0.6)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/upscale_portrait_9bklein.safetensors", 0.8, 0.8),
                           ("Flux-2-Klein/K9bSh4rpD3tails.safetensors", 0.4, 0.4)],
            "flux1dev":   [("Flux-1-Dev/Detail/add_detail.safetensors", 0.6, 0.6)],
            "flux_kontext": [],
        },
    },
    # ── Color Tone / Grading ──────────────────────────────────────────
    {
        "label": "✦ Color Tone / Grading (Klein)",
        "prompt": "color graded, beautiful color palette, professional color correction, "
                  "cinematic color tone, warm highlights cool shadows, "
                  "complementary colors, mood lighting",
        "negative": "flat colors, oversaturated, undersaturated, grey, "
                    "washed out, neon, ugly colors",
        "denoise": 0.40,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Style\\sd_xl_offset_example-lora_1.0.safetensors", 0.6, 0.6)],
            "zit":        [("Z-Image-Turbo\\Style\\zy_CinematicShot_zit.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/Sliders/ColorTone_Standard.safetensors", 0.7, 0.7)],
            "flux1dev":   [],
            "flux_kontext": [],
        },
    },
    # ── Anything to Realistic (Klein) ─────────────────────────────────
    {
        "label": "✦ Anything → Realistic (Klein)",
        "prompt": "photorealistic, real person, natural skin, realistic features, "
                  "real photograph, authentic human, natural imperfections, "
                  "professional portrait, real-life",
        "negative": "anime, cartoon, illustration, painting, 3d render, "
                    "artificial, CGI, plastic, doll-like",
        "denoise": 0.65,
        "cfg_boost": 0.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Style\\epiCRealnessRC1.safetensors", 0.8, 0.8)],
            "zit":        [("Z-Image-Turbo\\Style\\Z-Image-Professional_Photographer_3500.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein/Character/Flux2Klein_AnythingtoRealCharacters.safetensors", 0.85, 0.85),
                           ("Flux-2-Klein/K9bSR3al.safetensors", 0.5, 0.5)],
            "flux1dev":   [("Flux-1-Dev/Realism/flux_realism.safetensors", 0.8, 0.8)],
            "flux_kontext": [],
        },
    },
]


def _filter_loras_for_arch(all_loras, arch):
    """Return only LoRAs whose full path starts with a compatible prefix."""
    prefixes = ARCH_LORA_PREFIXES.get(arch, [])
    if not prefixes:
        return []
    return [l for l in all_loras if any(l.startswith(p) or l == p.rstrip("/") for p in prefixes)]


# ═══════════════════════════════════════════════════════════════════════════
#  HTTP helpers — pure urllib, no pip installs needed
# ═══════════════════════════════════════════════════════════════════════════
# All communication with the ComfyUI server uses Python's built-in urllib,
# avoiding any dependency on requests/aiohttp. This is critical because
# GIMP 3 plugins run in a restricted Python environment where pip-installed
# packages may not be available.
#
# Model/LoRA discovery: Each _fetch_* function queries ComfyUI's /object_info
# endpoint for a specific node type, extracting the list of available models
# from that node's input schema. This is how the plugin discovers what
# checkpoints, LoRAs, and other models are installed on the server.

def _fetch_loras(server):
    """Fetch available LoRA names from ComfyUI server."""
    try:
        info = _api_get(server, "/object_info/LoraLoader")
        return info["LoraLoader"]["input"]["required"]["lora_name"][0]
    except Exception:
        return []

def _fetch_reactor_models(server):
    """Fetch available ReActor swap_model and face_restore_model lists from the server."""
    try:
        info = _api_get(server, "/object_info/ReActorFaceSwap")
        inputs = info["ReActorFaceSwap"]["input"]["required"]
        swap = inputs.get("swap_model", [[]])[0]
        restore = inputs.get("face_restore_model", [[]])[0]
        return swap, restore
    except Exception:
        return [], []

def _fetch_face_models(server):
    """Fetch saved face model names from ReActorLoadFaceModel on the server."""
    try:
        info = _api_get(server, "/object_info/ReActorLoadFaceModel")
        models = info["ReActorLoadFaceModel"]["input"]["required"]["face_model"][0]
        return [m for m in models if m != "none"]
    except Exception:
        return []

def _fetch_wan_video_models(server):
    """Fetch available diffusion models from WanVideoModelLoader."""
    try:
        info = _api_get(server, "/object_info/WanVideoModelLoader")
        return info["WanVideoModelLoader"]["input"]["required"]["model"][0]
    except Exception:
        return []

def _fetch_wan_video_loras(server):
    """Fetch Wan LoRAs from the server (via LoraLoaderModelOnly).

    Returns only LoRAs whose path starts with 'Wan/' — i.e. those
    in the dedicated loras/Wan/ subfolder on the ComfyUI server.
    """
    try:
        info = _api_get(server, "/object_info/LoraLoaderModelOnly")
        all_loras = info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0]
        return [l for l in all_loras if l.startswith("Wan/") or l.startswith("Wan/")]
    except Exception:
        return []

def _fetch_wan_video_vaes(server):
    """Fetch available VAE models from WanVideoVAELoader."""
    try:
        info = _api_get(server, "/object_info/WanVideoVAELoader")
        return info["WanVideoVAELoader"]["input"]["required"]["model_name"][0]
    except Exception:
        return []

def _fetch_clip_vision_models(server):
    """Fetch available CLIP vision models."""
    try:
        info = _api_get(server, "/object_info/CLIPVisionLoader")
        return info["CLIPVisionLoader"]["input"]["required"]["clip_name"][0]
    except Exception:
        return []

def _fetch_mtb_analysis_models(server):
    """Fetch face analysis models from mtb Face Swap."""
    try:
        info = _api_get(server, "/object_info/Load Face Analysis Model (mtb)")
        return info["Load Face Analysis Model (mtb)"]["input"]["required"]["faceswap_model"][0]
    except Exception:
        return ["antelopev2", "buffalo_l"]

def _fetch_mtb_swap_models(server):
    """Fetch face swap models from mtb."""
    try:
        info = _api_get(server, "/object_info/Load Face Swap Model (mtb)")
        return info["Load Face Swap Model (mtb)"]["input"]["required"]["faceswap_model"][0]
    except Exception:
        return ["inswapper_128.onnx"]

def _fetch_checkpoints(server):
    """Fetch available checkpoints from the server."""
    try:
        info = _api_get(server, "/object_info/CheckpointLoaderSimple")
        return info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except Exception:
        return []

def _fetch_faceid_presets(server):
    """Fetch IPAdapter FaceID preset names."""
    try:
        info = _api_get(server, "/object_info/IPAdapterUnifiedLoaderFaceID")
        return info["IPAdapterUnifiedLoaderFaceID"]["input"]["required"]["preset"][0]
    except Exception:
        return ["FACEID", "FACEID PLUS V2", "FACEID PORTRAIT (style transfer)"]

def _fetch_pulid_models(server):
    """Fetch PuLID Flux model files."""
    try:
        info = _api_get(server, "/object_info/PulidFluxModelLoader")
        return info["PulidFluxModelLoader"]["input"]["required"]["pulid_file"][0]
    except Exception:
        return ["pulid_flux_v0.9.1.safetensors"]

def _api_get(server, path):
    """HTTP GET to ComfyUI server, returns parsed JSON."""
    url = f"{server.rstrip('/')}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _api_post_json(server, path, data):
    """HTTP POST JSON to ComfyUI server. Extracts error detail on failure."""
    url = f"{server.rstrip('/')}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code} from {path}: {detail}") from e

# ── Async upload buffering pattern ─────────────────────────────────────
# Problem: uploading large PNGs over HTTP blocks the GTK main thread,
# freezing GIMP's UI. Solution: _upload_image() reads the file data into
# memory (fast local I/O) and appends to _pending_uploads. The actual
# HTTP POST happens later in _flush_pending_uploads(), which runs inside
# _run_comfyui_workflow()'s background thread. This keeps the UI responsive
# while still ensuring uploads complete before the workflow is submitted.
_pending_uploads = []  # list of (server, file_data, filename, image_type, overwrite)

def _upload_image(server, filepath, filename=None, image_type="input", overwrite=True):
    """Buffer file data into memory and queue the HTTP POST for later.

    Returns {"name": filename} immediately so the caller can reference
    the filename in workflow construction before the upload actually happens.
    The upload is flushed by _flush_pending_uploads() in the background thread.
    """
    if filename is None:
        filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        file_data = f.read()
    _pending_uploads.append((server, file_data, filename, image_type, overwrite))
    return {"name": filename}

def _upload_image_sync(server, filepath, filename=None, image_type="input", overwrite=True):
    """Synchronous upload — used only for standalone 'Upload Image' menu action.

    Unlike _upload_image(), this performs the HTTP POST immediately on the
    calling thread. Only used by _run_send() where there's no subsequent
    workflow to batch with.
    """
    url = f"{server.rstrip('/')}/upload/image"
    if filename is None:
        filename = os.path.basename(filepath)
    # Multipart form-data boundary — random hex ensures no collision with file content
    boundary = uuid.uuid4().hex
    with open(filepath, "rb") as f:
        file_data = f.read()
    body_parts = []
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode())
    body_parts.append(file_data)
    body_parts.append(b"\r\n")
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(f'Content-Disposition: form-data; name="type"\r\n\r\n{image_type}\r\n'.encode())
    body_parts.append(f"--{boundary}\r\n".encode())
    ow = "true" if overwrite else "false"
    body_parts.append(f'Content-Disposition: form-data; name="overwrite"\r\n\r\n{ow}\r\n'.encode())
    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)
    req = urllib.request.Request(url, data=body,
                                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Upload HTTP {e.code}: {detail}") from e

def _flush_pending_uploads():
    """Perform all queued HTTP uploads. Called from background thread.

    This is the second half of the async upload pattern. It runs inside
    _run_comfyui_workflow()'s background thread, right before submitting
    the workflow to ComfyUI. Each upload uses multipart/form-data encoding
    built manually (no external library) to POST the image to /upload/image.
    """
    global _pending_uploads
    for server, file_data, filename, image_type, overwrite in _pending_uploads:
        url = f"{server.rstrip('/')}/upload/image"
        boundary = uuid.uuid4().hex
        body_parts = []
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n".encode())
        body_parts.append(file_data)
        body_parts.append(b"\r\n")
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(f'Content-Disposition: form-data; name="type"\r\n\r\n{image_type}\r\n'.encode())
        body_parts.append(f"--{boundary}\r\n".encode())
        ow = "true" if overwrite else "false"
        body_parts.append(f'Content-Disposition: form-data; name="overwrite"\r\n\r\n{ow}\r\n'.encode())
        body_parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(body_parts)
        req = urllib.request.Request(url, data=body,
                                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Upload HTTP {e.code}: {detail}") from e
    _pending_uploads = []

def _create_selection_mask_png(filepath, image):
    """Export GIMP's actual selection channel as a grayscale PNG mask.
    White = selected (inpaint here), Black = unselected (keep).

    Strategy A: save selection → create layer from channel → export directly.
                No fill operations needed — the selection channel IS the mask.

    Strategy B: duplicate → flatten → grayscale → fill dance → export.
                Classic approach with GIMP 3 fill API compat.

    Strategy C: bounds-aware pixel scan using gimp-selection-value.
                Only scans within the selection bounding box.
    """
    width = image.get_width()
    height = image.get_height()
    errors = []

    # ── Pre-check: does a selection exist? ─────────────────────────────
    sel_x1, sel_y1, sel_x2, sel_y2 = 0, 0, width, height
    try:
        bounds = _pdb_run('gimp-selection-bounds', {'image': image})
        has_sel = bool(bounds.index(1))  # non-empty = True
        if not has_sel:
            raise RuntimeError("No selection — use a selection tool to mark the inpaint area first")
        sel_x1 = int(bounds.index(2))
        sel_y1 = int(bounds.index(3))
        sel_x2 = int(bounds.index(4))
        sel_y2 = int(bounds.index(5))
    except RuntimeError:
        raise
    except Exception as e:
        errors.append(f"bounds check: {e}")

    gfile = Gio.File.new_for_path(filepath.replace("/", "/"))

    def _file_ok():
        try:
            return os.path.getsize(filepath) > 100
        except Exception:
            return False

    # ── Strategy A: export selection channel directly as layer ─────────
    # The selection channel already contains mask data (white=selected).
    # Save it as a channel, create a new grayscale image with a layer
    # from that channel, and export. Zero fill operations.
    new_img = None
    saved_ch = None
    try:
        # Save the selection to a named channel on the original image
        saved_ch = _pdb_run('gimp-selection-save', {'image': image}).index(1)

        # Create a new grayscale image and copy the channel as a layer
        new_img = Gimp.Image.new(width, height, Gimp.ImageBaseType.GRAY)
        new_layer = Gimp.Layer.new_from_drawable(saved_ch, new_img)
        new_layer.set_name("mask")
        new_layer.set_visible(True)
        new_layer.set_opacity(100.0)
        new_img.insert_layer(new_layer, None, 0)

        # Flatten only if there are visible layers, otherwise export directly
        layers = new_img.get_layers()
        visible = [l for l in layers if l.get_visible()]
        if visible:
            new_img.flatten()
            flat = new_img.get_layers()[0]
        else:
            # No visible layers — make the first layer visible and export it
            layers[0].set_visible(True)
            flat = layers[0]
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, new_img, [flat], gfile)

        if _file_ok():
            # Clean up
            new_img.delete()
            image.remove_channel(saved_ch)
            return

        errors.append("Strategy A: exported file too small")
    except Exception as e:
        errors.append(f"Strategy A: {e}")
    finally:
        try:
            if new_img is not None:
                new_img.delete()
        except Exception:
            pass
        try:
            if saved_ch is not None:
                image.remove_channel(saved_ch)
        except Exception:
            pass

    # ── Strategy B: duplicate + fill dance ─────────────────────────────
    dup = None
    try:
        dup = image.duplicate()
        saved_ch2 = _pdb_run('gimp-selection-save', {'image': dup}).index(1)
        dup.flatten()
        _pdb_run('gimp-image-convert-grayscale', {'image': dup})
        layer = dup.get_layers()[0]

        # Set FG = black, BG = white
        _pdb_run('gimp-context-set-default-colors', {})

        # Select all → fill black (try multiple GIMP 3 APIs)
        _pdb_run('gimp-selection-all', {'image': dup})
        fill_ok = False
        for fill_proc, fill_args in [
            ('gimp-drawable-edit-fill', {'drawable': layer, 'fill-type': Gimp.FillType.FOREGROUND}),
            ('gimp-drawable-edit-fill', {'drawable': layer, 'fill-type': 0}),
            ('gimp-edit-fill', {'drawable': layer, 'fill-type': 0}),
        ]:
            try:
                pdb = Gimp.get_pdb()
                if pdb.lookup_procedure(fill_proc) is not None:
                    _pdb_run(fill_proc, fill_args)
                    fill_ok = True
                    break
            except Exception as fe:
                errors.append(f"{fill_proc}: {fe}")
        if not fill_ok:
            raise RuntimeError("No working fill procedure")

        # Reload saved selection
        for op_val in [Gimp.ChannelOps.REPLACE, 2]:
            try:
                _pdb_run('gimp-image-select-item',
                         {'image': dup, 'operation': op_val, 'item': saved_ch2})
                break
            except Exception:
                pass

        # Swap → FG = white → fill selection
        _pdb_run('gimp-context-swap-colors', {})
        for fill_proc, fill_args in [
            ('gimp-drawable-edit-fill', {'drawable': layer, 'fill-type': Gimp.FillType.FOREGROUND}),
            ('gimp-drawable-edit-fill', {'drawable': layer, 'fill-type': 0}),
            ('gimp-edit-fill', {'drawable': layer, 'fill-type': 0}),
        ]:
            try:
                pdb = Gimp.get_pdb()
                if pdb.lookup_procedure(fill_proc) is not None:
                    _pdb_run(fill_proc, fill_args)
                    break
            except Exception as fe:
                errors.append(f"{fill_proc}: {fe}")

        _pdb_run('gimp-selection-none', {'image': dup})
        try:
            dup.remove_channel(saved_ch2)
        except Exception:
            pass

        dup.flatten()
        flat = dup.get_layers()[0]
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, [flat], gfile)

        if _file_ok():
            dup.delete()
            return

        errors.append("Strategy B: exported file too small")
    except Exception as e:
        errors.append(f"Strategy B: {e}")
    finally:
        try:
            if dup is not None:
                dup.delete()
        except Exception:
            pass

    # ── Strategy C: bounds-aware pixel scan ────────────────────────────
    # Only scan pixels inside the selection bounding box.
    sel_w = sel_x2 - sel_x1
    sel_h = sel_y2 - sel_y1
    total_pixels = sel_w * sel_h

    if total_pixels > 6_000_000:
        err_detail = "; ".join(errors) if errors else "unknown"
        raise RuntimeError(
            f"Cannot create selection mask: fast methods failed ({err_detail}) "
            f"and selection area is too large ({sel_w}x{sel_h}) for pixel scan. "
            f"Try a smaller selection or restart GIMP."
        )

    Gimp.progress_set_text("Building selection mask (pixel scan)...")
    rows = []
    mask_total = 0
    for y in range(height):
        row = bytearray(width)
        if sel_y1 <= y < sel_y2:
            for x in range(sel_x1, sel_x2):
                try:
                    res = _pdb_run('gimp-selection-value', {
                        'image': image, 'x': x, 'y': y,
                    })
                    val = int(res.index(1))
                    row[x] = val
                    mask_total += val
                except Exception:
                    row[x] = 0
        rows.append(b'\x00' + bytes(row))
        if y % 32 == 0:
            Gimp.progress_update(y / height)

    if mask_total == 0:
        raise RuntimeError("Selection mask is empty — no area selected")

    _write_grayscale_png(filepath, width, height, rows)


def _write_grayscale_png(filepath, width, height, pixel_rows):
    """Write a grayscale PNG from row data. Pure Python, no dependencies.

    Used by Strategy C of _create_selection_mask_png when GIMP's own export
    fails. Implements minimal PNG spec: magic → IHDR → IDAT → IEND.
    Color type 0 = grayscale, bit depth 8.
    """
    def _png_chunk(chunk_type, data):
        # PNG chunk format: [4-byte length][4-byte type][data][4-byte CRC32]
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    with open(filepath, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')  # PNG magic bytes
        # IHDR: width, height, bit_depth=8, color_type=0(gray), compress=0, filter=0, interlace=0
        ihdr = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
        f.write(_png_chunk(b'IHDR', ihdr))
        # IDAT: zlib-compressed pixel data (each row prefixed with filter byte 0x00)
        compressed = zlib.compress(b''.join(pixel_rows))
        f.write(_png_chunk(b'IDAT', compressed))
        f.write(_png_chunk(b'IEND', b''))

def _download_image(server, filename, subfolder="", folder_type="output"):
    """Download a generated image from ComfyUI's /view endpoint as raw bytes."""
    params = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
    url = f"{server.rstrip('/')}/view?{params}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as resp:
        return resp.read()

def _wait_for_prompt(server, prompt_id, timeout=300):
    """Poll ComfyUI's /history endpoint until the prompt finishes or times out.

    ComfyUI doesn't support webhooks/SSE for prompt completion in the simple
    API mode, so we poll every 1.5 seconds. The prompt_id appears in the
    history dict once generation is complete.

    Checks _cancel_event between polls — if set, attempts to cancel the
    prompt on the server and raises InterruptedError.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check for user cancellation
        if _cancel_event.is_set():
            # Try to cancel the prompt on ComfyUI server
            try:
                _api_post_json(server, "/queue", {"delete": [prompt_id]})
            except Exception:
                pass
            raise InterruptedError("Generation cancelled by user")
        try:
            history = _api_get(server, f"/history/{prompt_id}")
            if prompt_id in history:
                return history[prompt_id]
        except Exception:
            pass
        time.sleep(1.5)
    raise TimeoutError(f"ComfyUI prompt {prompt_id} did not finish within {timeout}s")

def _get_output_images(server, prompt_id, timeout=300):
    """Wait for a prompt to finish and collect all output image references.

    Returns a list of (filename, subfolder, type) tuples. These can be
    passed to _download_image() to fetch the actual pixel data.
    """
    result = _wait_for_prompt(server, prompt_id, timeout)
    images = []
    # Iterate all nodes in the workflow output — any node that produces
    # images (SaveImage, PreviewImage, etc.) will have an "images" key
    for node_id, node_output in result.get("outputs", {}).items():
        for img in node_output.get("images", []):
            images.append((img["filename"], img.get("subfolder", ""), img.get("type", "output")))
    return images

# ═══════════════════════════════════════════════════════════════════════════
#  Workflow builders — construct ComfyUI node graphs as Python dicts
# ═══════════════════════════════════════════════════════════════════════════
# Each _build_* function returns a dict representing a ComfyUI workflow
# (API format). Keys are string node IDs, values are dicts with
# "class_type" and "inputs". Cross-node references use [node_id, output_index]
# tuples — e.g. ["1", 0] means "output 0 of node 1".
#
# Convention: node IDs are assigned by function (1-9 for core pipeline,
# 30+ for conditioning, 50+ for sampling, 90+ for scaling, 100+ for LoRAs).

def _inject_loras(wf, loras, ckpt_node="1", model_ref=None, clip_ref=None):
    """Insert LoRA loader nodes between checkpoint and the rest of the workflow.

    Chains: ckpt -> lora1 -> lora2 -> ... -> (model_out, clip_out).
    Returns (workflow, final_model_ref, final_clip_ref).

    Uses high node IDs (100+) to avoid collision with the caller's nodes.
    model_ref/clip_ref allow overriding the starting references (for Flux/Klein
    where model and clip come from different loader nodes).
    """
    default_model = model_ref or [ckpt_node, 0]
    default_clip = clip_ref or [ckpt_node, 1]
    if not loras:
        return wf, default_model, default_clip

    prev_model = default_model
    prev_clip = default_clip
    base_id = 100  # high IDs to avoid collision with existing nodes

    for i, lora in enumerate(loras):
        nid = str(base_id + i)
        wf[nid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": prev_model,
                "clip": prev_clip,
                "lora_name": lora["name"],
                "strength_model": lora["strength_model"],
                "strength_clip": lora["strength_clip"],
            }
        }
        prev_model = [nid, 0]
        prev_clip = [nid, 1]

    return wf, prev_model, prev_clip


def _build_img2img(image_filename, preset, prompt_text, negative_text, seed, loras=None, controlnet=None):
    """Standard img2img: load checkpoint, encode image to latent, denoise, decode.

    Pipeline: CheckpointLoaderSimple → [LoRA chain] → CLIPTextEncode(+/-)
              LoadImage → VAEEncode → KSampler → VAEDecode → SaveImage
    For flux1dev: UNETLoader + CLIPLoader + VAELoader (Flux uses separate loaders).
    Optional ControlNet injection adds preprocessor + ControlNetApplyAdvanced.
    """
    is_flux = preset.get("arch") == "flux1dev"

    if is_flux:
        # Flux 1 Dev uses UNETLoader (not CheckpointLoaderSimple)
        wf = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": preset["ckpt"], "weight_dtype": "default"}},
            "1b": {"class_type": "DualCLIPLoader",
                   "inputs": {"clip_name1": "clip_l.safetensors",
                              "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                              "type": "flux"}},
            "1c": {"class_type": "VAELoader",
                   "inputs": {"vae_name": "ae.safetensors"}},
        }
        model_ref = ["1", 0]
        clip_ref = ["1b", 0]
        vae_ref = ["1c", 0]
    else:
        wf = {
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": preset["ckpt"]}},
        }
        model_ref = ["1", 0]
        clip_ref = ["1", 1]
        vae_ref = ["1", 2]

    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], model_ref[0], model_ref=model_ref, clip_ref=clip_ref)
    wf.update({
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "4": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "5": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["4", 0], "vae": vae_ref}},
        "6": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref, "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["5", 0], "seed": seed,
                  "steps": preset["steps"], "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"], "scheduler": preset["scheduler"],
                  "denoise": preset["denoise"],
              }},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": vae_ref}},
        "8": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": "gimp_comfy"}},
    })
    # ── ControlNet injection (optional) ──────────────────────────────
    if controlnet and controlnet.get("mode", "Off") != "Off":
        guide = CONTROLNET_GUIDE_MODES[controlnet["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model = guide["cn_models"].get(arch, guide["cn_models"].get("sdxl"))
        preprocessor = guide["preprocessor"]

        cn_image_ref = ["4", 0]  # LoadImage output
        if preprocessor:
            wf["20"] = {"class_type": preprocessor,
                        "inputs": {"image": ["4", 0]}}
            cn_image_ref = ["20", 0]

        wf["21"] = {"class_type": "ControlNetLoader",
                    "inputs": {"control_net_name": cn_model}}

        wf["22"] = {"class_type": "ControlNetApplyAdvanced",
                    "inputs": {
                        "positive": ["2", 0],
                        "negative": ["3", 0],
                        "control_net": ["21", 0],
                        "image": cn_image_ref,
                        "strength": controlnet["strength"],
                        "start_percent": controlnet["start_percent"],
                        "end_percent": controlnet["end_percent"],
                    }}

        # Redirect KSampler to use ControlNet-wrapped conditioning
        wf["6"]["inputs"]["positive"] = ["22", 0]
        wf["6"]["inputs"]["negative"] = ["22", 1]

    return wf


def _build_txt2img(preset, prompt_text, negative_text, seed, loras=None):
    """Text-to-image: generate from empty latent (no input image).

    Same as img2img but uses EmptyLatentImage instead of VAEEncode,
    and denoise is always 1.0 (full generation from noise).
    For flux1dev: uses UNETLoader + DualCLIPLoader + VAELoader.
    """
    is_flux = preset.get("arch") == "flux1dev"

    if is_flux:
        wf = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": preset["ckpt"], "weight_dtype": "default"}},
            "1b": {"class_type": "DualCLIPLoader",
                   "inputs": {"clip_name1": "clip_l.safetensors",
                              "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                              "type": "flux"}},
            "1c": {"class_type": "VAELoader",
                   "inputs": {"vae_name": "ae.safetensors"}},
        }
        model_ref = ["1", 0]
        clip_ref = ["1b", 0]
        vae_ref = ["1c", 0]
    else:
        wf = {
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": preset["ckpt"]}},
        }
        model_ref = ["1", 0]
        clip_ref = ["1", 1]
        vae_ref = ["1", 2]

    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "1", model_ref=model_ref, clip_ref=clip_ref)
    wf.update({
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": preset["width"], "height": preset["height"], "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref, "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["4", 0], "seed": seed,
                  "steps": preset["steps"], "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"], "scheduler": preset["scheduler"],
                  "denoise": 1.0,
              }},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": vae_ref}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": "gimp_comfy"}},
    })
    return wf

def _build_inpaint(image_filename, mask_filename, preset, prompt_text, negative_text, seed, loras=None, controlnet=None):
    """Inpainting: regenerate only the masked region of the image.

    Pipeline: Load image + mask → scale both to working resolution →
    ImageToMask (red channel) → SetLatentNoiseMask → KSampler → scale back
    to original size → SaveImage.
    Optional ControlNet injection adds preprocessor + ControlNetApplyAdvanced.

    Key detail: the mask is loaded as an IMAGE (not directly as a mask)
    because LoadImage output[1] is the alpha channel which may be all-zero.
    Instead we use output[0] (the actual RGB pixels) and convert the red
    channel to a MASK tensor via ImageToMask.
    """
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": preset["ckpt"]}},
    }
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "1")
    wf.update({
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "4": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "5": {"class_type": "LoadImage",
              "inputs": {"image": mask_filename}},
        # Convert the grayscale mask IMAGE to a MASK tensor.
        # LoadImage output [1] is the alpha channel (all-zero if no alpha!).
        # We need output [0] (the actual pixels) → ImageToMask → red channel.
        "51": {"class_type": "ImageToMask",
               "inputs": {"image": ["5", 0], "channel": "red"}},
        # Get original image size for restoring after sampling
        "90": {"class_type": "GetImageSize+",
               "inputs": {"image": ["4", 0]}},
        # Scale image to working resolution
        "91": {"class_type": "ImageScale",
               "inputs": {"image": ["4", 0], "upscale_method": "lanczos",
                           "width": preset["width"], "height": preset["height"],
                           "crop": "disabled"}},
        # Scale mask to same working resolution
        "92": {"class_type": "ImageScale",
               "inputs": {"image": ["5", 0], "upscale_method": "nearest-exact",
                           "width": preset["width"], "height": preset["height"],
                           "crop": "disabled"}},
        "52": {"class_type": "ImageToMask",
               "inputs": {"image": ["92", 0], "channel": "red"}},
        "6": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["91", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SetLatentNoiseMask",
              "inputs": {"samples": ["6", 0], "mask": ["52", 0]}},
        "8": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref, "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["7", 0], "seed": seed,
                  "steps": preset["steps"], "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"], "scheduler": preset["scheduler"],
                  "denoise": preset["denoise"],
              }},
        "9": {"class_type": "VAEDecode",
              "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
        # Restore to original image size
        "95": {"class_type": "ImageScale",
               "inputs": {"image": ["9", 0], "upscale_method": "lanczos",
                           "width": ["90", 0], "height": ["90", 1],
                           "crop": "disabled"}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["95", 0], "filename_prefix": "gimp_inpaint"}},
    })
    # ── ControlNet injection (optional) ──────────────────────────────
    if controlnet and controlnet.get("mode", "Off") != "Off":
        guide = CONTROLNET_GUIDE_MODES[controlnet["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model = guide["cn_models"].get(arch, guide["cn_models"].get("sdxl"))
        preprocessor = guide["preprocessor"]

        cn_image_ref = ["4", 0]  # LoadImage output (original image)
        if preprocessor:
            wf["20"] = {"class_type": preprocessor,
                        "inputs": {"image": ["4", 0]}}
            cn_image_ref = ["20", 0]

        wf["21"] = {"class_type": "ControlNetLoader",
                    "inputs": {"control_net_name": cn_model}}

        wf["22"] = {"class_type": "ControlNetApplyAdvanced",
                    "inputs": {
                        "positive": ["2", 0],
                        "negative": ["3", 0],
                        "control_net": ["21", 0],
                        "image": cn_image_ref,
                        "strength": controlnet["strength"],
                        "start_percent": controlnet["start_percent"],
                        "end_percent": controlnet["end_percent"],
                    }}

        # Redirect KSampler to use ControlNet-wrapped conditioning
        wf["8"]["inputs"]["positive"] = ["22", 0]
        wf["8"]["inputs"]["negative"] = ["22", 1]

    return wf


# ═══════════════════════════════════════════════════════════════════════════
#  Face Swap workflow builders (ReActor, mtb, IPAdapter FaceID, PuLID Flux)
# ═══════════════════════════════════════════════════════════════════════════

# ── Face Swap (ReActor) ──────────────────────────────────────────────────
# Fallback model lists used when the server is unreachable
FACE_SWAP_MODELS = [
    "inswapper_128.onnx",
    "inswapper_128_fp16.onnx",
    "reswapper_128.onnx",
    "reswapper_256.onnx",
    "hyperswap_1a_256.onnx",
    "hyperswap_1b_256.onnx",
    "hyperswap_1c_256.onnx",
]

FACE_RESTORE_MODELS = [
    "none",
    "codeformer-v0.1.0.pth",
    "GFPGANv1.3.pth",
    "GFPGANv1.4.pth",
    "GPEN-BFR-512.onnx",
    "GPEN-BFR-1024.onnx",
    "RestoreFormer_PP.onnx",
]


def _build_faceswap(target_filename, source_filename, swap_model="inswapper_128.onnx",
                     face_restore_model="codeformer-v0.1.0.pth",
                     face_restore_vis=1.0, codeformer_weight=0.5,
                     detect_gender_input="no", detect_gender_source="no",
                     input_face_idx="0", source_face_idx="0"):
    """ReActorFaceSwap: paste the face from source_image onto target_image."""
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": source_filename}},
        "3": {"class_type": "ReActorFaceSwap",
              "inputs": {
                  "enabled": True,
                  "input_image": ["1", 0],
                  "source_image": ["2", 0],
                  "swap_model": swap_model,
                  "facedetection": "retinaface_resnet50",
                  "face_restore_model": face_restore_model,
                  "face_restore_visibility": face_restore_vis,
                  "codeformer_weight": codeformer_weight,
                  "detect_gender_input": detect_gender_input,
                  "detect_gender_source": detect_gender_source,
                  "input_faces_index": input_face_idx,
                  "source_faces_index": source_face_idx,
                  "console_log_level": 1,
              }},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "gimp_faceswap"}},
    }
    return wf


def _build_faceswap_model(target_filename, face_model_name, swap_model="inswapper_128.onnx",
                           face_restore_model="codeformer-v0.1.0.pth",
                           face_restore_vis=1.0, codeformer_weight=0.5,
                           detect_gender_input="no", detect_gender_source="no",
                           input_face_idx="0", source_face_idx="0"):
    """ReActor face swap using a saved face model instead of a source image."""
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "2": {"class_type": "ReActorLoadFaceModel",
              "inputs": {"face_model": face_model_name}},
        "3": {"class_type": "ReActorFaceSwapOpt",
              "inputs": {
                  "enabled": True,
                  "input_image": ["1", 0],
                  "face_model": ["2", 0],
                  "swap_model": swap_model,
                  "facedetection": "retinaface_resnet50",
                  "face_restore_model": face_restore_model,
                  "face_restore_visibility": face_restore_vis,
                  "codeformer_weight": codeformer_weight,
              }},
        "4": {"class_type": "ReActorOptions",
              "inputs": {
                  "input_faces_order": "left-right",
                  "input_faces_index": input_face_idx,
                  "detect_gender_input": detect_gender_input,
                  "source_faces_order": "left-right",
                  "source_faces_index": source_face_idx,
                  "detect_gender_source": detect_gender_source,
                  "console_log_level": 1,
                  "restore_swapped_only": True,
              }},
        "5": {"class_type": "ReActorFaceBoost",
              "inputs": {
                  "enabled": True,
                  "boost_model": face_restore_model,
                  "interpolation": "Bicubic",
                  "visibility": 1.0,
                  "codeformer_weight": codeformer_weight,
                  "restore_with_main_after": False,
              }},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["3", 0], "filename_prefix": "gimp_faceswap_model"}},
    }
    # Connect options and boost to the swap node
    wf["3"]["inputs"]["options"] = ["4", 0]
    wf["3"]["inputs"]["face_boost"] = ["5", 0]
    return wf


def _build_save_face_model(source_filename, model_name, overwrite=True):
    """Build and save a ReActor face model from a source image.

    Uses ReActorBuildFaceModel to extract face embedding from the source
    image, then ReActorSaveFaceModel to persist it to disk under the
    given model_name. The saved model can later be loaded via
    ReActorLoadFaceModel for fast face swapping without re-uploading
    the source image each time.

    If overwrite=True, any existing model with the same name is replaced.
    If overwrite=False and the model already exists, the node will save
    with a numeric suffix to avoid collision.
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": source_filename}},
        "2": {"class_type": "ReActorBuildFaceModel",
              "inputs": {
                  "images": ["1", 0],
                  "face_index": 0,
                  "compute_method": "CPU",
              }},
        "3": {"class_type": "ReActorSaveFaceModel",
              "inputs": {
                  "face_model": ["2", 0],
                  "save_mode": "overwrite" if overwrite else "new",
                  "face_model_name": model_name,
              }},
        # SaveImage as a terminal output node so ComfyUI considers
        # the workflow complete (the save-model nodes have no image output)
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["1", 0],
                         "filename_prefix": "gimp_face_model_src"}},
    }
    return wf


# ── mtb Face Swap (direct swap) ────────────────────────────────────────

def _build_rembg(image_filename):
    """Remove background using Image Rembg node. Returns transparent PNG.

    Settings are hardcoded from validated workflow (Whimweaver REMBG pipeline):
      model=isnet-general-use, transparency=true, alpha_matting=false.
    DO NOT CHANGE — alpha_matting=true causes color fringing on edges.
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "Image Rembg (Remove Background)",
              "inputs": {
                  "images": ["1", 0],
                  "transparency": True,
                  "model": "isnet-general-use",
                  "post_processing": False,
                  "only_mask": False,
                  "alpha_matting": False,
                  "alpha_matting_foreground_threshold": 240,
                  "alpha_matting_background_threshold": 10,
                  "alpha_matting_erode_size": 10,
                  "background_color": "none",
              }},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "spellcaster_rembg"}},
    }
    return wf


# ── Upscale 4x (model-based super resolution) ────────────────────────

UPSCALE_PRESETS = {
    "4x UltraSharp (general)": "4x-UltraSharp.pth",
    "4x RealESRGAN (photo)": "RealESRGAN_x4plus.pth",
    "4x NMKD Superscale (sharp)": "4x_NMKD-Superscale-SP_178000_G.pth",
    "4x Remacri (restoration)": "4x_foolhardy_Remacri.pth",
    "4x RealESRGAN Anime": "RealESRGAN_x4plus_anime_6B.pth",
    "8x NMKD Faces (portraits)": "8x_NMKD-Faces_160000_G.pth",
}

def _build_upscale(image_filename, model_name):
    """Upscale image using a super-resolution model.

    Pipeline: LoadImage → UpscaleModelLoader → ImageUpscaleWithModel → SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": model_name}},
        "3": {"class_type": "ImageUpscaleWithModel",
              "inputs": {
                  "upscale_model": ["2", 0],
                  "image": ["1", 0],
              }},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "spellcaster_upscale"}},
    }
    return wf


# ── LaMa Object Removal (selection-based inpainting without diffusion) ─

def _build_lama_remove(image_filename, mask_filename):
    """Remove objects using LaMa inpainting — no checkpoint, no prompt needed.

    Pipeline: LoadImage(image) → LoadImage(mask) → LaMaInpaint → SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": mask_filename}},
        "3": {"class_type": "LaMaInpaint",
              "inputs": {
                  "image": ["1", 0],
                  "mask": ["2", 0],
              }},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "spellcaster_lama"}},
    }
    return wf


# ── Color Grading / LUT application ──────────────────────────────────

LUT_PRESETS = {
    "Kodak 2383 (cinema warm)": "Rec709_Kodak_2383_D65.cube",
    "Fujifilm 3513DI (cinema cool)": "Rec709_Fujifilm_3513DI_D65.cube",
    "Kodak P3 (wide gamut)": "DCI-P3_Kodak_2383_D65.cube",
    "Fujifilm P3 (wide gamut)": "DCI-P3_Fujifilm_3513DI_D65.cube",
    "ACES (HDR film)": "ACES_LMT_v0.1.1.cube",
}

def _build_lut(image_filename, lut_name, strength):
    """Apply a color LUT to the image for cinematic color grading.

    Pipeline: LoadImage → ImageApplyLUT+ → SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "ImageApplyLUT+",
              "inputs": {
                  "image": ["1", 0],
                  "lut_file": lut_name,
                  "strength": strength,
                  "log": False,
                  "clip_values": True,
                  "gamma_correction": False,
              }},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "spellcaster_lut"}},
    }
    return wf


# ── Outpaint / Extend Canvas ─────────────────────────────────────────

def _build_outpaint(image_filename, preset, prompt_text, negative_text, seed,
                     left, top, right, bottom, feathering, loras=None):
    """Outpaint: extend the canvas by padding and inpainting the new area.

    Pipeline: LoadImage → ImagePadForOutpaint → VAEEncode → SetLatentNoiseMask
              → KSampler → VAEDecode → SaveImage

    ImagePadForOutpaint outputs [0]=padded image, [1]=mask for the new area.
    """
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": preset["ckpt"]}},
    }
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "1")
    wf.update({
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "4": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "5": {"class_type": "ImagePadForOutpaint",
              "inputs": {
                  "image": ["4", 0],
                  "left": left,
                  "top": top,
                  "right": right,
                  "bottom": bottom,
                  "feathering": feathering,
              }},
        "6": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SetLatentNoiseMask",
              "inputs": {"samples": ["6", 0], "mask": ["5", 1]}},
        "8": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref, "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["7", 0], "seed": seed,
                  "steps": preset["steps"], "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"], "scheduler": preset["scheduler"],
                  "denoise": preset["denoise"],
              }},
        "9": {"class_type": "VAEDecode",
              "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["9", 0], "filename_prefix": "spellcaster_outpaint"}},
    })
    return wf


# ── Style Transfer / IPAdapter ────────────────────────────────────────

def _build_style_transfer(target_filename, style_ref_filename, preset,
                           prompt_text, negative_text, seed,
                           ipadapter_preset="PLUS (high strength)",
                           weight=0.8, denoise=0.6):
    """Style transfer using IPAdapter — applies the style of a reference image.

    Pipeline: CheckpointLoaderSimple → IPAdapterUnifiedLoader → LoadImage(style ref)
              → IPAdapterAdvanced(weight_type="style transfer") → LoadImage(target)
              → CLIPTextEncode x2 → VAEEncode → KSampler → VAEDecode → SaveImage
    """
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": preset["ckpt"]}},
        "2": {"class_type": "IPAdapterUnifiedLoader",
              "inputs": {
                  "model": ["1", 0],
                  "preset": ipadapter_preset,
              }},
        "3": {"class_type": "LoadImage",
              "inputs": {"image": style_ref_filename}},
        "4": {"class_type": "IPAdapterAdvanced",
              "inputs": {
                  "model": ["2", 0],
                  "ipadapter": ["2", 1],
                  "image": ["3", 0],
                  "weight": weight,
                  "weight_type": "style transfer",
                  "combine_embeds": "concat",
                  "start_at": 0.0,
                  "end_at": 1.0,
                  "embeds_scaling": "V only",
              }},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["1", 1]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text or "blurry, deformed, bad anatomy", "clip": ["1", 1]}},
        "7": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["7", 0], "vae": ["1", 2]}},
        "9": {"class_type": "KSampler",
              "inputs": {
                  "model": ["4", 0],
                  "positive": ["5", 0],
                  "negative": ["6", 0],
                  "latent_image": ["8", 0],
                  "seed": seed,
                  "steps": preset["steps"],
                  "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"],
                  "scheduler": preset["scheduler"],
                  "denoise": denoise,
              }},
        "10": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": "spellcaster_style"}},
    }
    return wf


# ── Face Restore (ReActorRestoreFace) ───────────────────────────────

FACE_RESTORE_PRESETS = {
    "CodeFormer (best quality)": {"model": "codeformer-v0.1.0.pth", "weight": 0.7},
    "GFPGAN v1.4 (fast, good)": {"model": "GFPGANv1.4.pth", "weight": 0.8},
    "GFPGAN v1.3 (classic)": {"model": "GFPGANv1.3.pth", "weight": 0.8},
    "GPEN 1024 (high-res faces)": {"model": "GPEN-BFR-1024.onnx", "weight": 0.8},
    "GPEN 512 (fast faces)": {"model": "GPEN-BFR-512.onnx", "weight": 0.8},
    "RestoreFormer++ (balanced)": {"model": "RestoreFormer_PP.onnx", "weight": 0.8},
}

def _build_face_restore(image_filename, model_name, facedetection, visibility, codeformer_weight):
    """Restore faces using ReActorRestoreFace node.

    Pipeline: LoadImage → ReActorRestoreFace → SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "ReActorRestoreFace",
              "inputs": {
                  "image": ["1", 0],
                  "facedetection": facedetection,
                  "model": model_name,
                  "visibility": visibility,
                  "codeformer_weight": codeformer_weight,
              }},
        "3": {"class_type": "SaveImage",
              "inputs": {
                  "images": ["2", 0],
                  "filename_prefix": "spellcaster_facerestore",
              }},
    }
    return wf


# ── Photo Restoration Pipeline (Upscale → Face Restore → Sharpen) ───

RESTORE_UPSCALE_PRESETS = {
    "4x Remacri (restoration)": "4x_foolhardy_Remacri.pth",
    "4x RealESRGAN (general)": "RealESRGAN_x4plus.pth",
    "4x UltraSharp (maximum detail)": "4x-UltraSharp.pth",
    "8x NMKD Faces (portrait focus)": "8x_NMKD-Faces_160000_G.pth",
}

def _build_photo_restore(image_filename, upscale_model, face_model, facedetection,
                          visibility, codeformer_weight, sharpen_radius, sigma, alpha):
    """Full photo restoration: Upscale → Face Restore → Sharpen.

    Pipeline: LoadImage → UpscaleModelLoader → ImageUpscaleWithModel
              → ReActorRestoreFace → ImageSharpen → SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": upscale_model}},
        "3": {"class_type": "ImageUpscaleWithModel",
              "inputs": {
                  "upscale_model": ["2", 0],
                  "image": ["1", 0],
              }},
        "4": {"class_type": "ReActorRestoreFace",
              "inputs": {
                  "image": ["3", 0],
                  "facedetection": facedetection,
                  "model": face_model,
                  "visibility": visibility,
                  "codeformer_weight": codeformer_weight,
              }},
        "5": {"class_type": "ImageSharpen",
              "inputs": {
                  "image": ["4", 0],
                  "sharpen_radius": sharpen_radius,
                  "sigma": sigma,
                  "alpha": alpha,
              }},
        "6": {"class_type": "SaveImage",
              "inputs": {"images": ["5", 0], "filename_prefix": "spellcaster_photorestore"}},
    }
    return wf


# ── Detail Hallucination (Upscale + img2img at low denoise) ─────────

HALLUCINATE_PRESETS = {
    "Subtle (preserve original)": {"denoise": 0.25, "cfg": 4.0},
    "Moderate (add detail)": {"denoise": 0.35, "cfg": 5.0},
    "Strong (reimagine details)": {"denoise": 0.45, "cfg": 6.0},
    "Extreme (creative reinterpret)": {"denoise": 0.60, "cfg": 7.0},
}

def _build_detail_hallucinate(image_filename, upscale_model, preset, prompt_text, negative_text,
                               seed, denoise, cfg):
    """Upscale + img2img at low denoise to hallucinate fine detail.

    Pipeline: LoadImage → UpscaleModelLoader → ImageUpscaleWithModel
              → CheckpointLoaderSimple → CLIPTextEncode(+/-) → VAEEncode
              → KSampler → VAEDecode → SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": upscale_model}},
        "3": {"class_type": "ImageUpscaleWithModel",
              "inputs": {
                  "upscale_model": ["2", 0],
                  "image": ["1", 0],
              }},
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": preset["ckpt"]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["4", 1]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": ["4", 1]}},
        "7": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["3", 0], "vae": ["4", 2]}},
        "8": {"class_type": "KSampler",
              "inputs": {
                  "model": ["4", 0],
                  "positive": ["5", 0],
                  "negative": ["6", 0],
                  "latent_image": ["7", 0],
                  "seed": seed,
                  "steps": preset["steps"],
                  "cfg": cfg,
                  "sampler_name": preset["sampler"],
                  "scheduler": preset["scheduler"],
                  "denoise": denoise,
              }},
        "9": {"class_type": "VAEDecode",
              "inputs": {"samples": ["8", 0], "vae": ["4", 2]}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["9", 0], "filename_prefix": "spellcaster_hallucinate"}},
    }
    return wf


# ── SeedV2R Upscaler (upscale + img2img with hallucination control) ──

SEEDV2R_PRESETS = [
    {
        "label": "Faithful (no hallucination)",
        "denoise": 0.15, "cfg": 3.0, "steps": 15,
        "prompt": "ultra detailed, sharp focus, high resolution, same content, faithful reproduction",
        "negative": "different content, changed, altered, blurry, soft",
    },
    {
        "label": "Subtle (minimal hallucination)",
        "denoise": 0.25, "cfg": 4.0, "steps": 20,
        "prompt": "ultra detailed, sharp focus, high resolution, intricate details, fine texture",
        "negative": "blurry, low quality, soft, out of focus",
    },
    {
        "label": "Moderate (add detail)",
        "denoise": 0.35, "cfg": 5.0, "steps": 25,
        "prompt": "ultra detailed, sharp focus, high resolution, intricate details, rich texture, fine detail",
        "negative": "blurry, low quality, soft, out of focus, low detail",
    },
    {
        "label": "Strong (reimagine details)",
        "denoise": 0.45, "cfg": 6.0, "steps": 25,
        "prompt": "masterpiece, ultra detailed, sharp focus, high resolution, intricate details",
        "negative": "blurry, low quality, worst quality, soft, out of focus",
    },
    {
        "label": "Extreme (creative reinterpret)",
        "denoise": 0.60, "cfg": 7.0, "steps": 30,
        "prompt": "masterpiece, best quality, ultra detailed, sharp focus, vivid colors, intricate",
        "negative": "blurry, low quality, worst quality, deformed, bad anatomy",
    },
]

SEEDV2R_SCALE_OPTIONS = [
    ("1x (enhance only)", 1.0),
    ("1.5x", 1.5),
    ("2x", 2.0),
    ("3x", 3.0),
    ("4x", 4.0),
]


def _build_seedv2r(image_filename, upscale_model, preset, prompt_text, negative_text,
                    seed, denoise, cfg, steps, scale_factor, orig_width, orig_height):
    """SeedV2R: upscale + img2img pipeline with user-controlled scale and hallucination.

    For scale > 1x: UpscaleModelLoader → ImageUpscaleWithModel (4x) →
                     ImageScale (to target dims) → VAEEncode → KSampler → ...
    For 1x: skip upscale, go straight to VAEEncode → KSampler.
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
    }

    if scale_factor > 1.0:
        # Upscale with model to 4x, then scale to target dimensions
        target_w = int(orig_width * scale_factor)
        target_h = int(orig_height * scale_factor)
        # Round to nearest 8 for latent compatibility
        target_w = (target_w + 7) // 8 * 8
        target_h = (target_h + 7) // 8 * 8

        wf["2"] = {"class_type": "UpscaleModelLoader",
                   "inputs": {"model_name": upscale_model}}
        wf["3"] = {"class_type": "ImageUpscaleWithModel",
                   "inputs": {
                       "upscale_model": ["2", 0],
                       "image": ["1", 0],
                   }}
        if scale_factor < 4.0:
            # Downscale from 4x to target
            wf["3b"] = {"class_type": "ImageScale",
                        "inputs": {
                            "image": ["3", 0],
                            "width": target_w,
                            "height": target_h,
                            "upscale_method": "lanczos",
                            "crop": "disabled",
                        }}
            img_ref = ["3b", 0]
        else:
            img_ref = ["3", 0]
    else:
        # 1x — no upscale, use original image directly
        img_ref = ["1", 0]

    wf["4"] = {"class_type": "CheckpointLoaderSimple",
               "inputs": {"ckpt_name": preset["ckpt"]}}
    wf["5"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": prompt_text, "clip": ["4", 1]}}
    wf["6"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": negative_text, "clip": ["4", 1]}}
    wf["7"] = {"class_type": "VAEEncode",
               "inputs": {"pixels": img_ref, "vae": ["4", 2]}}
    wf["8"] = {"class_type": "KSampler",
               "inputs": {
                   "model": ["4", 0],
                   "positive": ["5", 0],
                   "negative": ["6", 0],
                   "latent_image": ["7", 0],
                   "seed": seed,
                   "steps": steps,
                   "cfg": cfg,
                   "sampler_name": preset["sampler"],
                   "scheduler": preset["scheduler"],
                   "denoise": denoise,
               }}
    wf["9"] = {"class_type": "VAEDecode",
               "inputs": {"samples": ["8", 0], "vae": ["4", 2]}}
    wf["10"] = {"class_type": "SaveImage",
                "inputs": {"images": ["9", 0], "filename_prefix": "spellcaster_seedv2r"}}
    return wf


# ── Colorize B&W Photo (ControlNet lineart + img2img) ───────────────

CONTROLNET_LINEART_MODELS = {
    "sd15": "control_v11p_sd15_lineart_fp16.safetensors",
    "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
    "flux1dev": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
    "flux2klein": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
    "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
}

CONTROLNET_SCRIBBLE_MODELS = {
    "sd15": "control_v11p_sd15_lineart_fp16.safetensors",
    "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
    "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
}

CONTROLNET_CANNY_MODELS = {
    "sd15": "control_v11p_sd15_lineart_fp16.safetensors",
    "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
    "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
}

CONTROLNET_DEPTH_MODELS = {
    "sd15": "control_v11f1p_sd15_depth_fp16.safetensors",
    "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
    "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
}

CONTROLNET_POSE_MODELS = {
    "sd15": "control_v11p_sd15_openpose_fp16.safetensors",
    "sdxl": "OpenPoseXL2.safetensors",
    "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
}

# ── Merged ControlNet guide modes for img2img / inpaint integration ──
CONTROLNET_GUIDE_MODES = {
    "Off": {"preprocessor": None, "cn_models": None},
    "Canny (edges)": {
        "preprocessor": "CannyEdgePreprocessor",
        "cn_models": {"sd15": "control_v11p_sd15_lineart_fp16.safetensors",
                       "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
                       "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
    },
    "Depth (spatial layout)": {
        "preprocessor": "MiDaS-DepthMapPreprocessor",
        "cn_models": {"sd15": "control_v11f1p_sd15_depth_fp16.safetensors",
                       "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
                       "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
    },
    "Lineart (drawing)": {
        "preprocessor": "LineArtPreprocessor",
        "cn_models": {"sd15": "control_v11p_sd15_lineart_fp16.safetensors",
                       "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
                       "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
    },
    "OpenPose (body pose)": {
        "preprocessor": "DWPreprocessor",
        "cn_models": {"sd15": "control_v11p_sd15_openpose_fp16.safetensors",
                       "sdxl": "OpenPoseXL2.safetensors",
                       "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
    },
    "Scribble (rough sketch)": {
        "preprocessor": "ScribblePreprocessor",
        "cn_models": {"sd15": "control_v11p_sd15_lineart_fp16.safetensors",
                       "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
                       "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
    },
    "Tile (detail upscale)": {
        "preprocessor": None,  # no preprocessor — feeds image directly
        "cn_models": {"sd15": "control_v11f1e_sd15_tile.pth",
                       "sdxl": "SDXL\\ttplanetSDXLControlnet_Tile_v20Fp16.safetensors",
                       "zit": "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
    },
}

ICLIGHT_PRESETS = {
    "Left Side Light": "soft light from the left side, dramatic side lighting, cinematic",
    "Right Side Light": "soft light from the right side, dramatic side lighting, cinematic",
    "Top Light": "overhead lighting, dramatic top light, cinematic shadows below",
    "Bottom Light": "light from below, dramatic uplighting, rim light on chin",
    "Back Light": "strong back lighting, rim light, silhouette edges, halo effect",
    "Front Soft": "soft frontal fill light, even illumination, studio portrait",
    "Golden Hour": "warm golden hour sunlight from the side, orange warm tones",
    "Blue Hour": "cool blue hour lighting, twilight, moody blue tones",
    "Neon": "colorful neon light, pink and blue, cyberpunk lighting",
    "Dramatic": "dramatic chiaroscuro lighting, strong contrast, film noir",
}

def _build_colorize(image_filename, preset, prompt_text, negative_text, seed,
                     controlnet_strength, denoise):
    """Colorize B&W photo using ControlNet lineart to preserve structure.

    Pipeline: LoadImage → LineArtPreprocessor → ControlNetLoader
              → CheckpointLoaderSimple → CLIPTextEncode(+/-) → ControlNetApplyAdvanced
              → VAEEncode(original) → KSampler → VAEDecode → SaveImage
    """
    arch = preset.get("arch", "sdxl")
    cn_model = CONTROLNET_LINEART_MODELS.get(arch, CONTROLNET_LINEART_MODELS["sdxl"])
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "LineArtPreprocessor",
              "inputs": {
                  "image": ["1", 0],
                  "resolution": 512,
                  "coarse": "disable",
              }},
        "3": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": preset["ckpt"]}},
        "4": {"class_type": "ControlNetLoader",
              "inputs": {"control_net_name": cn_model}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["3", 1]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": ["3", 1]}},
        "7": {"class_type": "ControlNetApplyAdvanced",
              "inputs": {
                  "positive": ["5", 0],
                  "negative": ["6", 0],
                  "control_net": ["4", 0],
                  "image": ["2", 0],
                  "strength": controlnet_strength,
                  "start_percent": 0.0,
                  "end_percent": 1.0,
              }},
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["1", 0], "vae": ["3", 2]}},
        "9": {"class_type": "KSampler",
              "inputs": {
                  "model": ["3", 0],
                  "positive": ["7", 0],
                  "negative": ["7", 1],
                  "latent_image": ["8", 0],
                  "seed": seed,
                  "steps": preset["steps"],
                  "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"],
                  "scheduler": preset["scheduler"],
                  "denoise": denoise,
              }},
        "10": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": ["3", 2]}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": "spellcaster_colorize"}},
    }
    return wf


# ── Generic ControlNet generation builder ─────────────────────────────

def _build_controlnet_gen(image_filename, preprocessor_type, controlnet_model,
                           ckpt_name, prompt, negative, seed, width, height,
                           steps, cfg, sampler, scheduler, cn_strength=0.8,
                           loras=None):
    """Generic ControlNet generation: preprocessor -> ControlNet -> KSampler.

    Shared builder for sketch2img, canny2img, depth2img, and pose2img.
    The preprocessor_type determines which preprocessor node is used:
      ScribblePreprocessor, CannyEdgePreprocessor, MiDaS-DepthMapPreprocessor, DWPreprocessor
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": preprocessor_type,
              "inputs": {"image": ["1", 0]}},
        "3": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt_name}},
    }
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "3")
    wf.update({
        "4": {"class_type": "ControlNetLoader",
              "inputs": {"control_net_name": controlnet_model}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": clip_ref}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": clip_ref}},
        "7": {"class_type": "ControlNetApplyAdvanced",
              "inputs": {
                  "positive": ["5", 0], "negative": ["6", 0],
                  "control_net": ["4", 0], "image": ["2", 0],
                  "strength": cn_strength,
                  "start_percent": 0.0, "end_percent": 1.0,
              }},
        "8": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref, "positive": ["7", 0], "negative": ["7", 1],
                  "latent_image": ["8", 0], "seed": seed,
                  "steps": steps, "cfg": cfg,
                  "sampler_name": sampler, "scheduler": scheduler,
                  "denoise": 1.0,
              }},
        "10": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": ["3", 2]}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": "spellcaster_controlnet"}},
    })
    return wf


def _build_sketch2img(image_filename, preset, prompt, negative, seed,
                       cn_strength=0.8, loras=None):
    """ControlNet Sketch to Image using ScribblePreprocessor."""
    arch = preset.get("arch", "sdxl")
    cn_model = CONTROLNET_SCRIBBLE_MODELS.get(arch, CONTROLNET_SCRIBBLE_MODELS["sdxl"])
    return _build_controlnet_gen(
        image_filename, "ScribblePreprocessor", cn_model,
        preset["ckpt"], prompt, negative, seed,
        preset["width"], preset["height"], preset["steps"], preset["cfg"],
        preset["sampler"], preset["scheduler"], cn_strength, loras)


def _build_canny2img(image_filename, preset, prompt, negative, seed,
                      cn_strength=0.8, loras=None):
    """ControlNet Canny Edge to Image using CannyEdgePreprocessor."""
    arch = preset.get("arch", "sdxl")
    cn_model = CONTROLNET_CANNY_MODELS.get(arch, CONTROLNET_CANNY_MODELS["sdxl"])
    return _build_controlnet_gen(
        image_filename, "CannyEdgePreprocessor", cn_model,
        preset["ckpt"], prompt, negative, seed,
        preset["width"], preset["height"], preset["steps"], preset["cfg"],
        preset["sampler"], preset["scheduler"], cn_strength, loras)


def _build_depth2img(image_filename, preset, prompt, negative, seed,
                      cn_strength=0.8, loras=None):
    """ControlNet Depth to Image using MiDaS-DepthMapPreprocessor."""
    arch = preset.get("arch", "sdxl")
    cn_model = CONTROLNET_DEPTH_MODELS.get(arch, CONTROLNET_DEPTH_MODELS["sdxl"])
    return _build_controlnet_gen(
        image_filename, "MiDaS-DepthMapPreprocessor", cn_model,
        preset["ckpt"], prompt, negative, seed,
        preset["width"], preset["height"], preset["steps"], preset["cfg"],
        preset["sampler"], preset["scheduler"], cn_strength, loras)


def _build_pose2img(image_filename, preset, prompt, negative, seed,
                     cn_strength=0.8, loras=None):
    """ControlNet Pose to Image using DWPreprocessor (DWPose)."""
    arch = preset.get("arch", "sdxl")
    cn_model = CONTROLNET_POSE_MODELS.get(arch, CONTROLNET_POSE_MODELS["sdxl"])
    return _build_controlnet_gen(
        image_filename, "DWPreprocessor", cn_model,
        preset["ckpt"], prompt, negative, seed,
        preset["width"], preset["height"], preset["steps"], preset["cfg"],
        preset["sampler"], preset["scheduler"], cn_strength, loras)


# ── IC-Light Relighting builder ───────────────────────────────────────

def _build_iclight(image_filename, ckpt_name, prompt, negative, seed,
                    multiplier=0.18, steps=20, cfg=2.0,
                    sampler="euler", scheduler="normal"):
    """IC-Light relighting: change lighting direction on any photo.

    Pipeline: LoadImage -> VAEEncode (foreground to LATENT) ->
              CheckpointLoaderSimple (SD1.5) ->
              LoadAndApplyICLightUnet -> CLIPTextEncode(+/-) ->
              ICLightConditioning (takes LATENT foreground) ->
              KSampler -> VAEDecode -> SaveImage

    IC-Light only works with SD1.5 models. The IC-Light UNET is at
    SD-1.5/iclight_sd15_fc.safetensors in the unet folder.
    ICLightConditioning.foreground expects LATENT, not IMAGE.
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt_name}},
        # VAEEncode the foreground image to latent (ICLightConditioning expects LATENT)
        "10": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["1", 0], "vae": ["2", 2]}},
        "3": {"class_type": "LoadAndApplyICLightUnet",
              "inputs": {
                  "model": ["2", 0],
                  "model_path": "SD-1.5\\iclight_sd15_fc.safetensors",
              }},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["2", 1]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["2", 1]}},
        "6": {"class_type": "ICLightConditioning",
              "inputs": {
                  "positive": ["4", 0], "negative": ["5", 0],
                  "vae": ["2", 2], "foreground": ["10", 0],
                  "multiplier": multiplier,
              }},
        "7": {"class_type": "KSampler",
              "inputs": {
                  "model": ["3", 0], "positive": ["6", 0], "negative": ["6", 1],
                  "latent_image": ["6", 2], "seed": seed,
                  "steps": steps, "cfg": cfg,
                  "sampler_name": sampler, "scheduler": scheduler,
                  "denoise": 1.0,
              }},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["7", 0], "vae": ["2", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": "spellcaster_iclight"}},
    }
    return wf


# ── SUPIR AI Restoration builder ──────────────────────────────────────

def _build_supir(image_filename, supir_model, sdxl_model, prompt, seed,
                  denoise=0.3, steps=20, scale_by=1.0):
    """SUPIR AI restoration using the all-in-one SUPIR_Upscale node.

    Much simpler than the manual pipeline — handles model loading,
    encoding, sampling, and decoding internally.
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "SUPIR_Upscale",
              "inputs": {
                  "supir_model": supir_model,
                  "sdxl_model": sdxl_model,
                  "image": ["1", 0],
                  "seed": seed,
                  "resize_method": "lanczos",
                  "scale_by": scale_by,
                  "steps": steps,
                  "restoration_scale": -1.0,
                  "cfg_scale": 4.0,
                  "a_prompt": prompt,
                  "n_prompt": "bad quality, blurry, messy",
                  "s_churn": 5,
                  "s_noise": 1.003,
                  "control_scale": denoise,
                  "cfg_scale_start": 4.0,
                  "control_scale_start": 0.0,
                  "color_fix_type": "Wavelet",
                  "keep_model_loaded": False,
                  "use_tiled_vae": True,
                  "encoder_tile_size_pixels": 512,
                  "decoder_tile_size_latent": 64,
                  "sampler": "RestoreEDMSampler",
              }},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "spellcaster_supir"}},
    }
    return wf


def _build_faceswap_mtb(target_filename, source_filename,
                         analysis_model="buffalo_l",
                         swap_model="inswapper_128.onnx",
                         faces_index="0"):
    """Face swap using mtb facetools — direct swap from source image to target.

    Pipeline: LoadImage(target) + LoadImage(source)
              Load Face Analysis Model (mtb) → FACE_ANALYSIS_MODEL
              Load Face Swap Model (mtb) → FACESWAP_MODEL
              Face Swap (mtb) → IMAGE
              SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": source_filename}},
        "3": {"class_type": "Load Face Analysis Model (mtb)",
              "inputs": {"faceswap_model": analysis_model}},
        "4": {"class_type": "Load Face Swap Model (mtb)",
              "inputs": {"faceswap_model": swap_model}},
        "5": {"class_type": "Face Swap (mtb)",
              "inputs": {
                  "image": ["1", 0],
                  "reference": ["2", 0],
                  "faces_index": faces_index,
                  "faceanalysis_model": ["3", 0],
                  "faceswap_model": ["4", 0],
              }},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["5", 0], "filename_prefix": "gimp_faceswap_mtb"}},
    }
    return wf


# ── IPAdapter FaceID (face-guided img2img) ─────────────────────────────

FACEID_PRESETS = {
    "SD1.5 — Juggernaut Reborn": {
        "ckpt": "SD-1.5\\juggernaut_reborn.safetensors",
        "width": 512, "height": 512,
        "steps": 25, "cfg": 7.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
    "SD1.5 — Realistic Vision v5.1": {
        "ckpt": "SD-1.5\\realisticVisionV51_v51VAE.safetensors",
        "width": 512, "height": 512,
        "steps": 25, "cfg": 7.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
    "SDXL — Juggernaut XL Ragnarok": {
        "ckpt": "SDXL\\Realistic\\juggernautXL_ragnarok.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 5.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
    "SDXL — ZavyChroma XL v10": {
        "ckpt": "SDXL\\Realistic\\zavychromaxl_v100.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 5.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
    "SDXL — JibMix Realistic v18": {
        "ckpt": "SDXL\\Realistic\\jibMixRealisticXL_v180SkinSupreme.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 5.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
}

def _build_faceid_img2img(target_filename, face_ref_filename, preset_key,
                           prompt_text, negative_text, seed,
                           faceid_preset="FACEID PLUS V2",
                           lora_strength=0.6, weight=0.85, weight_v2=1.0,
                           denoise=None, steps=None, cfg=None):
    """IPAdapter FaceID img2img — re-generates target image preserving face identity from reference.

    Pipeline: CheckpointLoaderSimple → MODEL, CLIP, VAE
              IPAdapterUnifiedLoaderFaceID(MODEL, preset) → MODEL (with FaceID LoRA), IPADAPTER
              LoadImage(face_ref) → face reference
              IPAdapterFaceID(MODEL, IPADAPTER, face_image) → MODEL (conditioned on face)
              CLIPTextEncode(positive) → CONDITIONING
              CLIPTextEncode(negative) → CONDITIONING
              LoadImage(target) → IMAGE
              VAEEncode(IMAGE, VAE) → LATENT
              KSampler(MODEL, CONDITIONING+, CONDITIONING-, LATENT) → LATENT
              VAEDecode → IMAGE
              SaveImage
    """
    p = FACEID_PRESETS[preset_key]
    steps = steps or p["steps"]
    cfg = cfg or p["cfg"]
    denoise = denoise or p["denoise"]

    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": p["ckpt"]}},
        # FaceID unified loader: loads IPAdapter + LoRA, applies to model
        "2": {"class_type": "IPAdapterUnifiedLoaderFaceID",
              "inputs": {
                  "model": ["1", 0],
                  "preset": faceid_preset,
                  "lora_strength": lora_strength,
                  "provider": "CUDA",
              }},
        # Load face reference image
        "3": {"class_type": "LoadImage",
              "inputs": {"image": face_ref_filename}},
        # Apply FaceID conditioning
        "4": {"class_type": "IPAdapterFaceID",
              "inputs": {
                  "model": ["2", 0],
                  "ipadapter": ["2", 1],
                  "image": ["3", 0],
                  "weight": weight,
                  "weight_faceidv2": weight_v2,
                  "weight_type": "linear",
                  "combine_embeds": "concat",
                  "start_at": 0.0,
                  "end_at": 1.0,
                  "embeds_scaling": "V only",
              }},
        # Text encoding
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["1", 1]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text or "blurry, deformed, bad anatomy", "clip": ["1", 1]}},
        # Load target image and encode to latent
        "7": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["7", 0], "vae": ["1", 2]}},
        # Sample
        "9": {"class_type": "KSampler",
              "inputs": {
                  "model": ["4", 0],
                  "positive": ["5", 0],
                  "negative": ["6", 0],
                  "latent_image": ["8", 0],
                  "seed": seed,
                  "steps": steps,
                  "cfg": cfg,
                  "sampler_name": p["sampler"],
                  "scheduler": p["scheduler"],
                  "denoise": denoise,
              }},
        # Decode
        "11": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "12": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "gimp_faceid"}},
    }
    return wf


# ── PuLID Flux (face identity-preserving generation) ───────────────────

PULID_FLUX_MODELS = [
    "Flux\\FLUX1 Dev fp8.safetensors",
    "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
]

def _build_pulid_flux(target_filename, face_ref_filename,
                       prompt_text, negative_text, seed,
                       flux_model="Flux\\FLUX1 Dev fp8.safetensors",
                       pulid_model="pulid_flux_v0.9.1.safetensors",
                       strength=0.9, steps=20, guidance=3.5,
                       denoise=0.65, width=1024, height=1024):
    """PuLID Flux — preserves face identity from reference while generating with Flux.

    Pipeline: UNETLoader(flux) → MODEL
              PulidFluxModelLoader → PULIDFLUX
              PulidFluxEvaClipLoader → EVA_CLIP
              PulidFluxInsightFaceLoader → FACEANALYSIS
              LoadImage(face_ref) → face reference
              ApplyPulidFlux(MODEL, PULIDFLUX, EVA_CLIP, FACEANALYSIS, face_image) → MODEL
              DualCLIPLoader(clip_l, t5xxl, flux) → CLIP
              CLIPTextEncode(prompt) → CONDITIONING
              LoadImage(target) → IMAGE
              VAELoader → VAE
              VAEEncode → LATENT
              KSampler → LATENT
              VAEDecode → IMAGE
              SaveImage
    """
    wf = {
        # Load Flux UNET
        "1": {"class_type": "UNETLoader",
              "inputs": {
                  "unet_name": flux_model,
                  "weight_dtype": "default",
              }},
        # PuLID model components (using Pulid* lowercase node family)
        "2": {"class_type": "PulidFluxModelLoader",
              "inputs": {"pulid_file": pulid_model}},
        "3": {"class_type": "PulidFluxEvaClipLoader",
              "inputs": {}},
        "4": {"class_type": "PulidFluxInsightFaceLoader",
              "inputs": {"provider": "CUDA"}},
        # Load face reference
        "5": {"class_type": "LoadImage",
              "inputs": {"image": face_ref_filename}},
        # Apply PuLID face identity to model
        "6": {"class_type": "ApplyPulidFlux",
              "inputs": {
                  "model": ["1", 0],
                  "pulid_flux": ["2", 0],
                  "eva_clip": ["3", 0],
                  "face_analysis": ["4", 0],
                  "image": ["5", 0],
                  "weight": strength,
                  "start_at": 0.0,
                  "end_at": 1.0,
              }},
        # Text encoding (Flux uses DualCLIPLoader: clip_name1=clip_l, clip_name2=t5)
        "7": {"class_type": "DualCLIPLoader",
              "inputs": {
                  "clip_name1": "clip_l.safetensors",
                  "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                  "type": "flux",
              }},
        "8": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["7", 0]}},
        # Target image for img2img
        "9": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        # VAE
        "10": {"class_type": "VAELoader",
               "inputs": {"vae_name": "ae.safetensors"}},
        "11": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["9", 0], "vae": ["10", 0]}},
        # Sample
        "12": {"class_type": "KSampler",
               "inputs": {
                   "model": ["6", 0],
                   "positive": ["8", 0],
                   "negative": ["8", 0],
                   "latent_image": ["11", 0],
                   "seed": seed,
                   "steps": steps,
                   "cfg": guidance,
                   "sampler_name": "euler",
                   "scheduler": "simple",
                   "denoise": denoise,
               }},
        # Decode and save
        "13": {"class_type": "VAEDecode",
               "inputs": {"samples": ["12", 0], "vae": ["10", 0]}},
        "14": {"class_type": "SaveImage",
               "inputs": {"images": ["13", 0], "filename_prefix": "gimp_pulid_flux"}},
    }
    return wf


# ═══════════════════════════════════════════════════════════════════════════
#  Wan 2.2 Image-to-Video — dual-model GGUF video generation
# ═══════════════════════════════════════════════════════════════════════════

# ── WAN Video Prompt Presets (best-practice templates) ───────────────────
# These fill the video dialog's prompt/negative/settings with tested
# templates for common animation types. Each can override cfg, steps,
# frame count, ping-pong mode, and auto-select LoRAs.
WAN_VIDEO_PRESETS = [
    {
        "label": "(none — manual prompt)",
        "prompt": "",
        "negative": "",
        "cfg_override": None,
        "steps_override": None,
        "length_override": None,
        "pingpong": None,  # None = don't override
        "loras": [],
    },
    # ── Subtle Life / Living Portrait ────────────────────────────────────
    {
        "label": "Living Portrait — subtle breathing & blinks",
        "prompt": "a person subtly breathing, gentle micro-movements, natural blinking, "
                  "soft chest rise and fall, slight head sway, lifelike idle animation, "
                  "photorealistic, cinematic lighting, shallow depth of field",
        "negative": "static, frozen, mannequin, jerky motion, fast movement, "
                    "exaggerated motion, morphing, distorted face, blurry",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Living Portrait — hair & fabric sway",
        "prompt": "person with gently flowing hair, soft fabric movement in breeze, "
                  "subtle clothes ripple, natural hair physics, serene expression, "
                  "photorealistic portrait, gentle wind effect, cinematic",
        "negative": "static, frozen, violent wind, tornado, exaggerated motion, "
                    "morphing, distorted, blurry, unnatural movement",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Living Portrait — smile & expression shift",
        "prompt": "person transitioning from neutral to gentle warm smile, subtle "
                  "expression change, natural facial animation, eyes lighting up, "
                  "slight cheek movement, photorealistic, cinematic close-up",
        "negative": "exaggerated expression, grotesque, morphing, distorted face, "
                    "uncanny valley, rapid change, blurry, jerky",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    # ── Eye & Gaze Movement ──────────────────────────────────────────────
    {
        "label": "Eye Movement — looking around",
        "prompt": "person slowly looking around, natural eye movement, gaze shifting "
                  "left and right, subtle head tracking with eyes, realistic eye motion, "
                  "photorealistic, cinematic portrait, detailed iris",
        "negative": "cross-eyed, spinning eyes, rapid movement, jerky, "
                    "deformed eyes, blurry, morphing face",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Camera Motion ────────────────────────────────────────────────────
    {
        "label": "Camera — slow zoom in",
        "prompt": "slow cinematic zoom in, camera slowly pushing forward, "
                  "gradual close-up, smooth dolly in, professional cinematography, "
                  "steady camera, photorealistic, shallow depth of field",
        "negative": "shaky camera, fast zoom, jerky, jump cut, "
                    "distorted, blurry, fish-eye, warping",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    {
        "label": "Camera — slow orbit / rotate",
        "prompt": "slow cinematic camera orbit around subject, smooth rotating shot, "
                  "gentle lateral dolly, parallax depth, professional steadicam, "
                  "photorealistic, cinematic lighting",
        "negative": "fast rotation, spinning, shaky, jerky, nausea-inducing, "
                    "warping, morphing, distorted perspective",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Camera — slow pan left/right",
        "prompt": "slow cinematic camera pan from left to right, smooth horizontal tracking, "
                  "gentle lateral movement, professional steadicam, photorealistic, "
                  "cinematic widescreen composition",
        "negative": "fast pan, jerky, shaky, vertical movement, zoom, "
                    "warping, morphing, blurry motion",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Nature / Environment ─────────────────────────────────────────────
    {
        "label": "Nature — flowing water & ripples",
        "prompt": "gently flowing water, natural ripples and reflections, "
                  "soft current movement, light dancing on water surface, "
                  "serene river or stream, photorealistic, 4K, cinematic",
        "negative": "static water, frozen, flood, tsunami, rapids, "
                    "distorted reflections, blurry, noisy",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Nature — clouds drifting",
        "prompt": "slowly drifting clouds in sky, gentle cloud movement, "
                  "soft atmospheric motion, time-lapse clouds, golden hour lighting, "
                  "dramatic sky, photorealistic, cinematic landscape",
        "negative": "static sky, storm, tornado, fast clouds, flickering, "
                    "distorted, glitching, blurry",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Nature — trees & foliage swaying",
        "prompt": "trees gently swaying in breeze, leaves rustling, natural foliage "
                  "movement, soft wind through branches, dappled sunlight, "
                  "photorealistic forest or garden, cinematic",
        "negative": "static trees, hurricane, violent wind, falling trees, "
                    "distorted, morphing, blurry",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Nature — fire / candle flicker",
        "prompt": "gently flickering candle flame, warm firelight dancing, "
                  "soft orange glow, natural fire movement, cozy atmosphere, "
                  "photorealistic, cinematic lighting, shallow depth of field",
        "negative": "explosion, inferno, out of control fire, static flame, "
                    "distorted, blurry, flickering artifacts",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Body & Action ────────────────────────────────────────────────────
    {
        "label": "Action — person walking forward",
        "prompt": "person walking forward naturally, smooth gait, realistic body motion, "
                  "natural arm swing, confident stride, photorealistic, "
                  "cinematic tracking shot, urban or nature background",
        "negative": "floating, sliding, moonwalk, jerky movement, "
                    "distorted limbs, extra limbs, blurry, frozen",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    {
        "label": "Action — person turning head",
        "prompt": "person slowly turning head to face camera, natural head rotation, "
                  "smooth neck movement, elegant turn, photorealistic portrait, "
                  "cinematic, shallow depth of field",
        "negative": "snapping head, jerky rotation, exorcist turn, 360 spin, "
                    "morphing, distorted face, blurry, neck distortion",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    {
        "label": "Action — dancing / rhythmic movement",
        "prompt": "person dancing gracefully, smooth rhythmic body movement, "
                  "fluid dance motion, natural choreography, expressive movement, "
                  "photorealistic, cinematic, dynamic lighting",
        "negative": "stiff, robotic, broken limbs, distorted body, "
                    "extra arms, jerky, morphing, blurry",
        "cfg_override": 6.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    # ── Atmospheric / Mood ───────────────────────────────────────────────
    {
        "label": "Atmosphere — rain & droplets",
        "prompt": "gentle rain falling, raindrops on surface, soft rain streaks, "
                  "wet reflections, moody atmosphere, cinematic rain scene, "
                  "photorealistic, shallow depth of field, bokeh raindrops",
        "negative": "flood, hurricane, static, dry, no rain, "
                    "distorted, blurry, noisy",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Atmosphere — snow falling",
        "prompt": "gentle snowfall, soft snowflakes drifting down, peaceful winter scene, "
                  "slow-motion snow, magical winter atmosphere, photorealistic, "
                  "cinematic, cold breath visible",
        "negative": "blizzard, avalanche, static, distorted, "
                    "morphing, blurry, warm, summer",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Atmosphere — particles & dust motes",
        "prompt": "floating dust particles in light beam, atmospheric dust motes, "
                  "volumetric lighting, god rays with floating particles, "
                  "dreamy atmosphere, photorealistic, cinematic",
        "negative": "static, sandstorm, explosion, distorted, "
                    "blurry, noisy, dirty",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Atmosphere — fog / mist rolling",
        "prompt": "gentle fog rolling across scene, soft mist movement, atmospheric haze, "
                  "moody fog tendrils, mysterious atmosphere, volumetric fog, "
                  "photorealistic, cinematic lighting",
        "negative": "static fog, dense smoke, explosion, fire, "
                    "distorted, blurry, noisy",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Cinemagraph Loops ────────────────────────────────────────────────
    {
        "label": "Cinemagraph — ocean waves loop",
        "prompt": "ocean waves gently crashing on shore, rhythmic wave motion, "
                  "sea foam rolling in and out, peaceful beach, golden hour, "
                  "photorealistic, cinematic, seamless loop",
        "negative": "tsunami, storm, static ocean, frozen water, "
                    "distorted, blurry, flickering",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Cinemagraph — city lights & traffic",
        "prompt": "city lights twinkling at night, gentle traffic light trails, "
                  "urban nightscape, bokeh city lights, smooth car headlight streaks, "
                  "photorealistic, cinematic night photography",
        "negative": "static lights, crash, explosion, daytime, "
                    "distorted, blurry, flickering",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Stylized / Creative ──────────────────────────────────────────────
    {
        "label": "Style — painting coming to life",
        "prompt": "painted artwork slowly coming to life, brushstrokes animating, "
                  "oil painting with subtle movement, artistic interpretation, "
                  "painterly animation, museum piece moving, masterwork quality",
        "negative": "photorealistic, modern, digital, jerky, glitching, "
                    "distorted, morphing rapidly, flickering",
        "cfg_override": 6.0,
        "steps_override": 35,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Style — anime / illustration loop",
        "prompt": "anime character with subtle idle animation, gentle breathing, "
                  "hair flowing, soft wind, anime art style, beautiful illustration, "
                  "high quality animation, smooth 2D animation",
        "negative": "3D, photorealistic, live action, jerky, static, "
                    "low quality, distorted, blurry",
        "cfg_override": 6.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Product / Object ─────────────────────────────────────────────────
    {
        "label": "Product — 360° turntable spin",
        "prompt": "product slowly rotating on turntable, smooth 360 degree rotation, "
                  "studio lighting, clean white background, professional product shot, "
                  "photorealistic, commercial quality, even lighting",
        "negative": "shaky, jerky rotation, wobble, distorted shape, "
                    "changing product, morphing, blurry, dirty background",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    {
        "label": "Product — hero shot with sparkle",
        "prompt": "product hero shot with sparkling light effects, lens flare, "
                  "premium presentation, glamorous lighting sweep, "
                  "commercial advertisement quality, photorealistic, cinematic",
        "negative": "dull, flat lighting, dirty, damaged product, "
                    "distorted, morphing, blurry",
        "cfg_override": 6.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Animal / Pet ─────────────────────────────────────────────────────
    {
        "label": "Pet — cat / dog breathing & looking",
        "prompt": "cute pet with subtle breathing, gentle ear twitches, "
                  "natural animal idle motion, soft blinking, whisker movement, "
                  "photorealistic animal portrait, cinematic, warm lighting",
        "negative": "static, frozen, stuffed animal, toy, "
                    "distorted, morphing, extra limbs, blurry",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
]


def _wan_video_dims(src_w, src_h, target_long=720, align=16):
    """Compute video output dimensions preserving aspect ratio.

    Scales so the longest side is ≈ target_long, then rounds both
    dimensions to the nearest multiple of *align* (VAE requirement).
    Examples:
        1920×1080 → 720×400    (landscape)
        1080×1920 → 400×720    (portrait)
        1024×1024 → 720×720    (square — floored to align)
        832×480   → 832×480    (already ≤720 on long side, kept as-is)
    """
    if src_w <= 0 or src_h <= 0:
        return 832, 480
    long = max(src_w, src_h)
    if long <= target_long:
        # Already small enough — just align
        w = max(align, round(src_w / align) * align)
        h = max(align, round(src_h / align) * align)
        return w, h
    scale = target_long / long
    w = max(align, round(src_w * scale / align) * align)
    h = max(align, round(src_h * scale / align) * align)
    return w, h


WAN_I2V_PRESETS = {
    "Wan I2V 14B (GGUF Q4)": {
        "high_model": "Wan\\wan2.2_i2v_high_noise_14B_Q4_K_S.gguf",
        "low_model": "Wan\\wan2.2_i2v_low_noise_14B_Q4_K_S.gguf",
        "clip": "umt5-xxl-encoder-Q8_0.gguf",
        "vae": "wan_2.1_vae.safetensors",
        "steps": 30, "second_step": 20, "cfg": 5.0, "shift": 8.0,
        "lora_prefix": "Wan/14B",
        "high_accel_lora": "Wan\\14B\\lightx2v_wan_4steps_lora_high_noise.safetensors",
        "low_accel_lora": "Wan\\14B\\lightx2v_wan_128_lora_low_noise.safetensors",
        "accel_strength": 1.0,
    },
    "Wan I2V 14B (fp8)": {
        "high_model": "Wan\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "low_model": "Wan\\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        "clip": "umt5-xxl-encoder-Q8_0.gguf",
        "vae": "wan_2.1_vae.safetensors",
        "steps": 30, "second_step": 20, "cfg": 5.0, "shift": 8.0,
        "lora_prefix": "Wan/14B",
    },
    "Wan Enhanced NSFW SVI (fp8)": {
        "high_model": "Wan\\wan22EnhancedNSFWSVICamera_nsfwV2FP8H.safetensors",
        "low_model": "Wan\\wan22EnhancedNSFWSVICamera_nsfwV2FP8L.safetensors",
        "clip": "umt5-xxl-encoder-Q8_0.gguf",
        "vae": "wan_2.1_vae.safetensors",
        "steps": 30, "second_step": 20, "cfg": 5.0, "shift": 8.0,
        "lora_prefix": "Wan/Enhanced",
    },
}

def _filter_wan_loras(all_loras, preset_key=None):
    """Filter LoRAs to only those in the Wan subfolder matching the selected model variant.

    LoRA folder layout:
        loras/Wan/14B/         — LoRAs compatible with standard Wan 2.2 14B
        loras/Wan/Enhanced/    — LoRAs compatible with Wan Enhanced NSFW SVI
    Each preset declares a lora_prefix (e.g. 'Wan/14B') and only LoRAs
    whose path starts with that prefix are shown.
    """
    if not preset_key or preset_key not in WAN_I2V_PRESETS:
        # Fallback: show everything under Wan\
        prefix = "Wan/"
    else:
        prefix = WAN_I2V_PRESETS[preset_key].get("lora_prefix", "Wan/")
        # Normalise to always end with backslash for matching
        if not prefix.endswith("/"):
            prefix += "/"
    return [l for l in all_loras if l.startswith(prefix) or l.startswith(prefix.replace("/", "/"))]


def _build_wan_i2v(image_filename, preset_key, prompt_text, negative_text, seed,
                    width=832, height=480, length=81,
                    steps=None, cfg=None, shift=None, second_step=None,
                    loras=None, upscale=True, upscale_factor=1.5,
                    interpolate=True, pingpong=False, fps=16):
    """Wan 2.2 Image-to-Video — fatberg_slim dual-model GGUF architecture.

    Two-pass pipeline:
      CLIPLoaderGGUF → CLIPTextEncode (pos/neg)
      UnetLoaderGGUF × 2 (high/low noise) → LoRA chains → ModelSamplingSD3
      VAELoader + LoadImage → WanImageToVideo → conditioning + latent
      KSamplerAdvanced pass 1 (high noise, steps 0→second_step)
      KSamplerAdvanced pass 2 (low noise, steps second_step→end, cfg=1.0)
      VAEDecode → [RTXVideoSuperResolution] → [RIFE VFI] → VHS_VideoCombine
    """
    p = WAN_I2V_PRESETS[preset_key]
    steps = steps or p["steps"]
    cfg = cfg or p["cfg"]
    shift = shift or p["shift"]
    second_step = second_step if second_step is not None else p.get("second_step", 20)

    is_gguf_high = p["high_model"].endswith(".gguf")
    is_gguf_low = p["low_model"].endswith(".gguf")

    wf = {
        # CLIP loader (GGUF T5 encoder for Wan)
        "1": {"class_type": "CLIPLoaderGGUF",
              "inputs": {"clip_name": p["clip"], "type": "wan"}},
        # High noise UNet
        "2": {"class_type": "UnetLoaderGGUF" if is_gguf_high else "UNETLoader",
              "inputs": {"unet_name": p["high_model"]}},
        # Low noise UNet
        "3": {"class_type": "UnetLoaderGGUF" if is_gguf_low else "UNETLoader",
              "inputs": {"unet_name": p["low_model"]}},
        # VAE
        "4": {"class_type": "VAELoader",
              "inputs": {"vae_name": p["vae"]}},
        # Positive prompt
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["1", 0]}},
        # Negative prompt
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text or "", "clip": ["1", 0]}},
        # Load source image
        "7": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        # Scale image to target resolution
        "8": {"class_type": "ImageScale",
              "inputs": {"image": ["7", 0], "upscale_method": "lanczos",
                         "width": width, "height": height, "crop": "disabled"}},
    }

    # Add weight_dtype for non-GGUF UNet loaders
    if not is_gguf_high:
        wf["2"]["inputs"]["weight_dtype"] = "default"
    if not is_gguf_low:
        wf["3"]["inputs"]["weight_dtype"] = "default"

    # ── LoRA chains ──────────────────────────────────────────────────
    # Accelerator LoRAs (noise-specific) first, then user content LoRAs
    high_model_ref = ["2", 0]
    low_model_ref = ["3", 0]

    high_lora_list = []
    low_lora_list = []

    # Preset accelerator LoRAs (lightx2v etc.)
    if p.get("high_accel_lora"):
        high_lora_list.append((p["high_accel_lora"], p.get("accel_strength", 1.0)))
    if p.get("low_accel_lora"):
        low_lora_list.append((p["low_accel_lora"], p.get("accel_strength", 1.0)))

    # User-selected content LoRAs (applied to both models)
    if loras:
        for lora_name, lora_str in loras:
            high_lora_list.append((lora_name, lora_str))
            low_lora_list.append((lora_name, lora_str))

    # Chain LoRAs for high-noise model (nodes 100+)
    for i, (lname, lstr) in enumerate(high_lora_list):
        nid = str(100 + i)
        wf[nid] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": high_model_ref,
                               "lora_name": lname, "strength_model": lstr}}
        high_model_ref = [nid, 0]

    # Chain LoRAs for low-noise model (nodes 120+)
    for i, (lname, lstr) in enumerate(low_lora_list):
        nid = str(120 + i)
        wf[nid] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": low_model_ref,
                               "lora_name": lname, "strength_model": lstr}}
        low_model_ref = [nid, 0]

    # ── ModelSamplingSD3 (shift) on both models ──────────────────────
    wf["30"] = {"class_type": "ModelSamplingSD3",
                "inputs": {"model": high_model_ref, "shift": shift}}
    wf["31"] = {"class_type": "ModelSamplingSD3",
                "inputs": {"model": low_model_ref, "shift": shift}}

    # ── WanImageToVideo conditioning ─────────────────────────────────
    wf["40"] = {"class_type": "WanImageToVideo",
                "inputs": {
                    "width": width, "height": height, "length": length,
                    "batch_size": 1,
                    "positive": ["5", 0], "negative": ["6", 0],
                    "vae": ["4", 0], "start_image": ["8", 0],
                }}

    # ── Two-pass KSamplerAdvanced ────────────────────────────────────
    # Pass 1: high-noise model (steps 0 → second_step)
    wf["50"] = {"class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["30", 0],
                    "positive": ["40", 0], "negative": ["40", 1],
                    "latent_image": ["40", 2],
                    "add_noise": "enable",
                    "noise_seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "simple",
                    "start_at_step": 0,
                    "end_at_step": second_step,
                    "return_with_leftover_noise": "enable",
                }}
    # Pass 2: low-noise model (steps second_step → end, cfg=1.0)
    wf["51"] = {"class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["31", 0],
                    "positive": ["40", 0], "negative": ["40", 1],
                    "latent_image": ["50", 0],
                    "add_noise": "disable",
                    "noise_seed": seed,
                    "steps": steps,
                    "cfg": 1.0,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "simple",
                    "start_at_step": second_step,
                    "end_at_step": 10000,
                    "return_with_leftover_noise": "disable",
                }}

    # ── VAE Decode ───────────────────────────────────────────────────
    wf["60"] = {"class_type": "VAEDecode",
                "inputs": {"samples": ["51", 0], "vae": ["4", 0]}}

    video_ref = ["60", 0]

    # ── Optional post-processing ─────────────────────────────────────
    if upscale:
        wf["70"] = {"class_type": "RTXVideoSuperResolution",
                    "inputs": {"images": video_ref,
                               "resize_type": "scale by multiplier",
                               "scale": upscale_factor,
                               "quality": "ULTRA"}}
        video_ref = ["70", 0]

    if interpolate:
        wf["71"] = {"class_type": "RIFE VFI",
                    "inputs": {"frames": video_ref, "ckpt_name": "rife49.pth",
                               "clear_cache_after_n_frames": 10, "multiplier": 2,
                               "fast_mode": True, "ensemble": True,
                               "scale_factor": 1.0}}
        video_ref = ["71", 0]

    # Output FPS: double if RIFE 2× interpolation is active
    output_fps = float(fps * (2 if interpolate else 1))

    wf["12"] = {"class_type": "VHS_VideoCombine",
                "inputs": {"images": video_ref, "frame_rate": output_fps,
                           "loop_count": 0, "filename_prefix": "gimp_wan_i2v",
                           "format": "video/h264-mp4", "pingpong": pingpong,
                           "save_output": True}}

    # Save first frame for GIMP to import
    wf["13"] = {"class_type": "SaveImage",
                "inputs": {"images": ["60", 0],
                           "filename_prefix": "gimp_wan_i2v_frames"}}

    return wf



# ── Klein img2img (Flux 2 Klein) ─────────────────────────────────────────
# Klein uses a different architecture than standard checkpoints:
# UNETLoader (not CheckpointLoaderSimple), CLIPLoader with type="flux2",
# separate VAELoader, and the Flux2-specific nodes (ReferenceLatent,
# CFGGuider, EmptyFlux2LatentImage, Flux2Scheduler, SamplerCustomAdvanced).

KLEIN_MODELS = {
    "Klein 9B": {
        "unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        "clip": "qwen_3_8b_fp8mixed.safetensors",
    },
    "Klein 4B": {
        "unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
        "clip": "qwen_3_4b.safetensors",
    },
    "Klein Base 4B": {
        "unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
        "clip": "qwen_3_4b.safetensors",
    },
}

KLEIN_DEFAULTS = {
    "steps": 4, "cfg": 1.0, "denoise": 0.65,
    "sampler": "euler", "scheduler": "simple",
    "guidance": 1.0,
    "enhancer_magnitude": 1.0, "enhancer_contrast": 0.0,
    "text_ref_balance": 0.5,
}


def _build_klein_img2img(image_filename, klein_model_key, prompt_text, seed,
                          steps=4, denoise=0.65, guidance=1.0,
                          enhancer_mag=1.0, enhancer_contrast=0.0,
                          lora_name=None, lora_strength=1.0):
    """Flux 2 Klein distilled img2img using SamplerCustomAdvanced + ReferenceLatent.

    Architecture (matches working server workflows):
      CLIPLoader(qwen_3_8b, flux2) → CLIPTextEncode → positive cond
      ConditioningZeroOut → negative cond
      LoadImage → ImageScaleToTotalPixels(1MP) → VAEEncode → latent ref
      ReferenceLatent(positive + latent) → CFGGuider
      ReferenceLatent(negative + latent) → CFGGuider
      GetImageSize → EmptyFlux2LatentImage + Flux2Scheduler
      SamplerCustomAdvanced → VAEDecode → SaveImage
    """
    km = KLEIN_MODELS[klein_model_key]

    wf = {
        # Model loaders
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": km["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
                         "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "flux2-vae.safetensors"}},

        # Text conditioning
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["4", 0]}},

        # Input image processing
        "10": {"class_type": "LoadImage",
               "inputs": {"image": image_filename}},
        "11": {"class_type": "ImageScaleToTotalPixels",
               "inputs": {"image": ["10", 0], "upscale_method": "nearest-exact",
                          "megapixels": 1.0, "resolution_steps": 1}},
        "12": {"class_type": "GetImageSize",
               "inputs": {"image": ["11", 0]}},

        # Encode reference image to latent
        "13": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["11", 0], "vae": ["3", 0]}},

        # ReferenceLatent: wrap conditioning with image latent for img2img
        "20": {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["4", 0], "latent": ["13", 0]}},
        "21": {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["5", 0], "latent": ["13", 0]}},

        # Sampler setup
        "30": {"class_type": "CFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["20", 0],
                          "negative": ["21", 0], "cfg": guidance}},
        "31": {"class_type": "KSamplerSelect",
               "inputs": {"sampler_name": "euler"}},
        "32": {"class_type": "Flux2Scheduler",
               "inputs": {"steps": steps,
                          "width": ["12", 0], "height": ["12", 1]}},
        "33": {"class_type": "RandomNoise",
               "inputs": {"noise_seed": seed}},
        "34": {"class_type": "EmptyFlux2LatentImage",
               "inputs": {"width": ["12", 0], "height": ["12", 1],
                          "batch_size": 1}},

        # Sample
        "40": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["33", 0], "guider": ["30", 0],
                          "sampler": ["31", 0], "sigmas": ["32", 0],
                          "latent_image": ["34", 0]}},

        # Decode and save
        "50": {"class_type": "VAEDecode",
               "inputs": {"samples": ["40", 0], "vae": ["3", 0]}},
        "51": {"class_type": "SaveImage",
               "inputs": {"images": ["50", 0], "filename_prefix": "gimp_klein"}},
    }
    return wf


def _build_klein_img2img_ref(image_filename, ref_filename, klein_model_key,
                              prompt_text, seed, steps=4, denoise=0.65,
                              guidance=1.0, enhancer_mag=1.0, enhancer_contrast=0.0,
                              ref_strength=1.0, text_ref_balance=0.5,
                              lora_name=None, lora_strength=1.0):
    """Flux 2 Klein distilled img2img with reference image.

    Same architecture as _build_klein_img2img but uses the reference image
    as the ReferenceLatent source instead of the main input image.
    The main input image is used as the base for editing.
    """
    km = KLEIN_MODELS[klein_model_key]

    wf = {
        # Model loaders
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": km["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
                         "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "flux2-vae.safetensors"}},

        # Text conditioning
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["4", 0]}},

        # Main input image processing
        "10": {"class_type": "LoadImage",
               "inputs": {"image": image_filename}},
        "11": {"class_type": "ImageScaleToTotalPixels",
               "inputs": {"image": ["10", 0], "upscale_method": "nearest-exact",
                          "megapixels": 1.0, "resolution_steps": 1}},
        "12": {"class_type": "GetImageSize",
               "inputs": {"image": ["11", 0]}},

        # Encode main image to latent for reference
        "13": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["11", 0], "vae": ["3", 0]}},

        # Reference image (style/structure source)
        "15": {"class_type": "LoadImage",
               "inputs": {"image": ref_filename}},
        "16": {"class_type": "ImageScaleToTotalPixels",
               "inputs": {"image": ["15", 0], "upscale_method": "nearest-exact",
                          "megapixels": 1.0, "resolution_steps": 1}},
        "17": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["16", 0], "vae": ["3", 0]}},

        # ReferenceLatent: use main image latent for conditioning
        "20": {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["4", 0], "latent": ["13", 0]}},
        "21": {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["5", 0], "latent": ["13", 0]}},

        # Sampler setup
        "30": {"class_type": "CFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["20", 0],
                          "negative": ["21", 0], "cfg": guidance}},
        "31": {"class_type": "KSamplerSelect",
               "inputs": {"sampler_name": "euler"}},
        "32": {"class_type": "Flux2Scheduler",
               "inputs": {"steps": steps,
                          "width": ["12", 0], "height": ["12", 1]}},
        "33": {"class_type": "RandomNoise",
               "inputs": {"noise_seed": seed}},
        "34": {"class_type": "EmptyFlux2LatentImage",
               "inputs": {"width": ["12", 0], "height": ["12", 1],
                          "batch_size": 1}},

        # Sample
        "40": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["33", 0], "guider": ["30", 0],
                          "sampler": ["31", 0], "sigmas": ["32", 0],
                          "latent_image": ["34", 0]}},

        # Decode and save
        "50": {"class_type": "VAEDecode",
               "inputs": {"samples": ["40", 0], "vae": ["3", 0]}},
        "51": {"class_type": "SaveImage",
               "inputs": {"images": ["50", 0], "filename_prefix": "gimp_klein_ref"}},
    }
    return wf


# ═══════════════════════════════════════════════════════════════════════════
#  Image export / import helpers
# ═══════════════════════════════════════════════════════════════════════════
# Exporting from GIMP 3 is surprisingly fragile — different GIMP builds
# support different PDB procedures, and some silently produce 0-byte files.
# The _export_image_to_tmp function tries 4 strategies from fastest to most
# reliable, falling back to pixel-by-pixel reading as a last resort.

def _write_rgb_png(filepath, width, height, pixel_rows):
    """Write an RGB PNG from raw pixel row data. Pure Python, no GIMP calls.

    Used as a fallback when GIMP's own file-save procedures fail.
    Each row in pixel_rows must be b'/x00' (filter byte) + RGB bytes.
    """
    def _png_chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    with open(filepath, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
        f.write(_png_chunk(b'IHDR', ihdr))
        compressed = zlib.compress(b''.join(pixel_rows))
        f.write(_png_chunk(b'IDAT', compressed))
        f.write(_png_chunk(b'IEND', b''))


def _pdb_run(proc_name, props=None):
    """Run a GIMP 3 PDB procedure using the lookup/config/run pattern.

    GIMP 3 replaced the old Script-Fu-style PDB calling convention with a
    three-step pattern:
      1. pdb.lookup_procedure(name) — get the GimpProcedure object
      2. proc.create_config() — create a GimpProcedureConfig to hold arguments
      3. cfg.set_property(key, value) — set each argument by name
      4. proc.run(cfg) — execute and return a Gimp.ValueArray

    Returns the Gimp.ValueArray result. Access values with result.index(N).
    """
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure(proc_name)
    if proc is None:
        raise RuntimeError(f"PDB procedure '{proc_name}' not found")
    cfg = proc.create_config()
    if props:
        for k, v in props.items():
            cfg.set_property(k, v)
    return proc.run(cfg)


def _export_image_to_tmp(image):
    """Export flattened image to a temp PNG.
    Tries multiple strategies from fastest to most reliable.
    Uses GIMP 3 direct methods + lookup/config/run PDB pattern."""
    errors = []

    # --- Duplicate & flatten using direct methods ---------------------------
    try:
        dup = image.duplicate()
    except Exception as e:
        raise RuntimeError(f"image.duplicate() failed: {e}")

    try:
        dup.flatten()
        flat = dup.get_layers()[0]
    except Exception as e:
        dup.delete()
        raise RuntimeError(f"image.flatten() failed: {e}")

    w = dup.get_width()
    h = dup.get_height()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    # CRITICAL: Gio.File only works with forward slashes on Windows
    tmp_path = tmp.name.replace("/", "/")
    gfile = Gio.File.new_for_path(tmp_path)

    def _cleanup_dup():
        try:
            dup.delete()
        except Exception:
            pass

    def _file_ok():
        try:
            return os.path.getsize(tmp.name) > 100
        except Exception:
            return False

    # --- Strategy 1: Gimp.file_save (Python API) ----------------------------
    try:
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, [flat], gfile)
        if _file_ok():
            _cleanup_dup()
            return tmp.name
        errors.append("Gimp.file_save: wrote 0 or too few bytes")
    except Exception as e:
        errors.append(f"Gimp.file_save: {e}")

    # --- Strategy 2: PDB gimp-file-save via config --------------------------
    try:
        _pdb_run('gimp-file-save', {
            'run-mode': Gimp.RunMode.NONINTERACTIVE,
            'image': dup,
            'file': gfile,
        })
        if _file_ok():
            _cleanup_dup()
            return tmp.name
        errors.append("gimp-file-save: wrote 0 or too few bytes")
    except Exception as e:
        errors.append(f"gimp-file-save: {e}")

    # --- Strategy 3: PDB file-png-export / file-png-save via config ---------
    for proc_name in ['file-png-export', 'file-png-save']:
        try:
            pdb = Gimp.get_pdb()
            if pdb.lookup_procedure(proc_name) is None:
                errors.append(f"{proc_name}: not found")
                continue
            _pdb_run(proc_name, {
                'run-mode': Gimp.RunMode.NONINTERACTIVE,
                'image': dup,
                'file': gfile,
            })
            if _file_ok():
                _cleanup_dup()
                return tmp.name
            errors.append(f"{proc_name}: wrote 0 or too few bytes")
        except Exception as e:
            errors.append(f"{proc_name}: {e}")

    # --- Strategy 4: Read pixels + write PNG in pure Python -----------------
    try:
        Gimp.progress_set_text("Reading pixels (fallback export)...")
        rows = []
        for y in range(h):
            row = bytearray()
            for x in range(w):
                res = _pdb_run('gimp-drawable-get-pixel', {
                    'drawable': flat,
                    'x-coord': x,
                    'y-coord': y,
                })
                num_ch = res.index(1)
                pixel = res.index(2)
                if num_ch >= 3:
                    row.extend([pixel[0], pixel[1], pixel[2]])
                elif num_ch == 1:
                    row.extend([pixel[0], pixel[0], pixel[0]])
                else:
                    row.extend([0, 0, 0])
            rows.append(b'\x00' + bytes(row))
            if y % 64 == 0:
                Gimp.progress_update(y / h)

        _cleanup_dup()
        _write_rgb_png(tmp.name, w, h, rows)
        if _file_ok():
            return tmp.name
        errors.append("pixel-read: wrote invalid PNG")
    except Exception as e:
        errors.append(f"pixel-read: {e}")

    # --- All strategies failed -----------------------------------------------
    _cleanup_dup()
    try:
        os.unlink(tmp.name)
    except Exception:
        pass
    raise RuntimeError(
        "All export strategies failed:\n" + "\n".join(f"  {i+1}. {e}" for i, e in enumerate(errors))
    )

def _get_selection_bounds(image):
    """Return (has_selection, x1, y1, x2, y2) for the image's selection.
    Returns (False, 0, 0, w, h) if no selection or the selection covers everything."""
    w, h = image.get_width(), image.get_height()
    try:
        bounds = _pdb_run('gimp-selection-bounds', {'image': image})
        has_sel = bool(bounds.index(1))
        if not has_sel:
            return False, 0, 0, w, h
        x1 = int(bounds.index(2)); y1 = int(bounds.index(3))
        x2 = int(bounds.index(4)); y2 = int(bounds.index(5))
        # If selection covers the entire canvas, treat as no selection
        if x1 == 0 and y1 == 0 and x2 == w and y2 == h:
            return False, 0, 0, w, h
        return True, x1, y1, x2, y2
    except Exception:
        return False, 0, 0, w, h


def _export_selection_to_tmp(image):
    """Export only the selection region of the image as a cropped PNG.
    Duplicates the image, flattens, crops to selection bounds, and exports.
    Returns (tmp_path, sel_width, sel_height) or falls back to full image."""
    has_sel, x1, y1, x2, y2 = _get_selection_bounds(image)
    if not has_sel:
        path = _export_image_to_tmp(image)
        return path, image.get_width(), image.get_height()

    sel_w = x2 - x1
    sel_h = y2 - y1

    try:
        dup = image.duplicate()
    except Exception as e:
        raise RuntimeError(f"image.duplicate() failed: {e}")

    try:
        # Remove the selection so flatten doesn't create marching ants artifacts
        _pdb_run('gimp-selection-none', {'image': dup})
        dup.flatten()
        # Crop to the selection region
        _pdb_run('gimp-image-crop', {
            'image': dup,
            'new-width': sel_w,
            'new-height': sel_h,
            'offx': x1,
            'offy': y1,
        })
    except Exception as e:
        dup.delete()
        raise RuntimeError(f"Crop to selection failed: {e}")

    flat = dup.get_layers()[0]
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    tmp_path = tmp.name.replace("/", "/")
    gfile = Gio.File.new_for_path(tmp_path)

    try:
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, [flat], gfile)
        if os.path.getsize(tmp.name) > 100:
            dup.delete()
            return tmp.name, sel_w, sel_h
    except Exception:
        pass

    # Fallback: PDB save
    try:
        _pdb_run('gimp-file-save', {
            'run-mode': Gimp.RunMode.NONINTERACTIVE,
            'image': dup, 'file': gfile,
        })
        if os.path.getsize(tmp.name) > 100:
            dup.delete()
            return tmp.name, sel_w, sel_h
    except Exception:
        pass

    dup.delete()
    raise RuntimeError("Failed to export selection region")


def _import_result_as_layer(image, image_data, layer_name="ComfyUI Result"):
    """Import raw PNG bytes as a new layer on top of *image*.

    Handles mode mismatches (e.g. ComfyUI returns a grayscale PNG but the
    canvas is RGB) by converting the loaded result to match the destination
    image's colour mode before inserting the layer.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(image_data)
    tmp.close()
    file = Gio.File.new_for_path(tmp.name.replace("/", "/"))
    result_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, file)
    layers = result_image.get_layers()
    if not layers:
        result_image.delete()
        os.unlink(tmp.name)
        return

    # ── Ensure the result image matches the destination colour mode ─────
    dest_type = image.get_base_type()      # e.g. Gimp.ImageBaseType.RGB
    src_type = result_image.get_base_type()
    if src_type != dest_type:
        try:
            if dest_type == Gimp.ImageBaseType.RGB:
                _pdb_run('gimp-image-convert-rgb', {'image': result_image})
            elif dest_type == Gimp.ImageBaseType.GRAY:
                _pdb_run('gimp-image-convert-grayscale', {'image': result_image})
            elif dest_type == Gimp.ImageBaseType.INDEXED:
                _pdb_run('gimp-image-convert-indexed', {
                    'image': result_image,
                    'dither-type': 0, 'palette-type': 0,
                    'num-cols': 256, 'alpha-dither': False,
                    'remove-unused': False, 'palette': "",
                })
        except Exception:
            pass  # best-effort; insert_layer will fail with a clear error

    layers = result_image.get_layers()  # re-fetch after conversion
    new_layer = Gimp.Layer.new_from_drawable(layers[0], image)
    new_layer.set_name(layer_name)
    image.insert_layer(new_layer, None, 0)
    if (new_layer.get_width() != image.get_width() or
            new_layer.get_height() != image.get_height()):
        new_layer.scale(image.get_width(), image.get_height(), False)
    result_image.delete()
    os.unlink(tmp.name)
    Gimp.displays_flush()

# ── Workflow queue serialization ──────────────────────────────────────
# ComfyUI can queue prompts internally, but submitting many at once
# causes VRAM spikes and unpredictable ordering. This lock ensures we
# finish one generation before starting the next. The counter lets the
# spinner show the user's position in the queue.
_workflow_lock = threading.Lock()
_workflow_queue_depth = 0  # how many requests are waiting or running
_cancel_event = threading.Event()  # set when user clicks Cancel in spinner

def _run_comfyui_workflow(server, workflow, timeout=300):
    """Flush pending uploads, submit workflow to ComfyUI, wait for results.

    This is the main execution entry point — called from a background thread
    (via _run_with_spinner) to avoid freezing GIMP's UI.

    Uses a global lock to serialize requests: if another generation is
    already running, this call blocks until it finishes. This prevents
    overloading ComfyUI with simultaneous prompts.
    """
    global _workflow_queue_depth
    _workflow_queue_depth += 1
    try:
        with _workflow_lock:
            _flush_pending_uploads()
            result = _api_post_json(server, "/prompt", {"prompt": workflow})
            prompt_id = result.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI did not return a prompt_id: {result}")
            return _get_output_images(server, prompt_id, timeout)
    finally:
        _workflow_queue_depth -= 1


def _async_fetch(fetch_fn, on_done, on_error):
    """Run fetch_fn in a background thread, dispatch result to GTK main thread.

    Used for non-blocking server queries (e.g. fetching LoRA lists) while
    the dialog is open. GLib.idle_add ensures callbacks run on the main
    thread where GTK widget updates are safe.
    """
    def worker():
        try:
            res = fetch_fn()
            GLib.idle_add(on_done, res)
        except Exception as e:
            GLib.idle_add(on_error, e)
    threading.Thread(target=worker, daemon=True).start()

_BANNER_PATH = str(Path(__file__).parent / "readme_banner.png")
_HERO_PATH = str(Path(__file__).parent / "installer_background.png")
_SPINNER_GIF_PATH = str(Path(__file__).parent / "spinner.gif")
_DIALOG_GIF_PATH = str(Path(__file__).parent / "wizard_banner.gif")

def _make_banner_image(width=220, use_hero=False):
    """Load a Spellcaster image, scaled to `width` px. Returns Gtk.Image or None.

    use_hero=True loads the wizard/mage character (for progress spinners).
    use_hero=False loads the rectangular banner (for dialogs).
    """
    path = _HERO_PATH if use_hero else _BANNER_PATH
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            path, width, -1, True)
        return Gtk.Image.new_from_pixbuf(pixbuf)
    except Exception:
        if use_hero:
            # Fall back to banner if hero image not found
            return _make_banner_image(width, use_hero=False)
        return None


def _make_spinner_image():
    """Load the animated spinner GIF for the processing window.

    Returns a Gtk.Image configured with the animation, or None if
    the GIF file is missing or cannot be loaded.
    """
    try:
        anim = GdkPixbuf.PixbufAnimation.new_from_file(_SPINNER_GIF_PATH)
        img = Gtk.Image()
        img.set_from_animation(anim)
        return img
    except Exception:
        return None


def _make_dialog_banner():
    """Load the animated wizard banner GIF for dialogs.

    Returns a Gtk.Image with the animation, or falls back to the
    static banner PNG if the GIF is missing.
    """
    try:
        anim = GdkPixbuf.PixbufAnimation.new_from_file(_DIALOG_GIF_PATH)
        img = Gtk.Image()
        img.set_from_animation(anim)
        return img
    except Exception:
        return _make_banner_image(360)


def _run_with_spinner(label_text, func, *args):
    """Run func(*args) in a background thread while showing a progress window.

    Creates a GTK window with the Spellcaster banner and a pulsing progress
    bar, runs the function in a daemon thread, and blocks the caller via
    GLib.MainLoop until the function completes. This keeps GTK responsive
    (the progress bar animates) while the potentially slow ComfyUI operation
    runs in the background.

    Uses list-boxes (result_box, error_box, done_box) as mutable containers
    to pass values between the worker thread and the GTK main loop.
    """
    result_box = [None]
    error_box = [None]
    done_box = [False]
    cancel_box = [False]  # set True when user clicks Cancel
    _cancel_event.clear()  # reset from any previous cancellation
    loop = GLib.MainLoop()

    win = Gtk.Window(title="Spellcaster")
    win.set_default_size(300, -1)
    win.set_deletable(False)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.override_background_color(Gtk.StateFlags.NORMAL,
                                   __import__('gi.repository.Gdk', fromlist=['Gdk']).RGBA(0.1, 0.1, 0.1, 1))

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

    # Use animated spinner GIF if available, fall back to static hero image
    spinner_img = _make_spinner_image()
    if spinner_img:
        vbox.pack_start(spinner_img, False, False, 0)
    else:
        banner = _make_banner_image(200, use_hero=True)
        if banner:
            vbox.pack_start(banner, False, False, 0)
        else:
            vbox.pack_start(Gtk.Label(label="Spellcaster"), True, True, 0)

    bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    bottom.set_margin_start(16); bottom.set_margin_end(16)
    bottom.set_margin_top(15); bottom.set_margin_bottom(20)
    label = Gtk.Label(label=label_text)
    label.get_style_context().add_class("header-label")
    pb = Gtk.ProgressBar(); pb.set_pulse_step(0.08)
    bottom.pack_start(label, False, False, 0)
    bottom.pack_start(pb, False, False, 0)

    # Cancel button
    cancel_btn = Gtk.Button(label="Cancel")
    cancel_btn.set_tooltip_text("Cancel the current generation")
    def _on_cancel(_btn):
        cancel_box[0] = True
        _cancel_event.set()  # signal the worker thread to stop polling
        label.set_text("Cancelling...")
        cancel_btn.set_sensitive(False)
    cancel_btn.connect("clicked", _on_cancel)
    bottom.pack_start(cancel_btn, False, False, 4)

    vbox.pack_start(bottom, False, False, 0)

    win.add(vbox); win.show_all()

    def _pulse():
        if not done_box[0]:
            pb.pulse()
            # Show queue position if other jobs are waiting
            depth = _workflow_queue_depth
            if depth > 1:
                label.set_text(f"Queued ({depth - 1} ahead) — {label_text}")
            elif not cancel_box[0] and label.get_text().startswith("Queued"):
                label.set_text(label_text)
            return True
        return False
    GLib.timeout_add(300, _pulse)

    def _worker():
        try:
            result_box[0] = func(*args)
        except Exception as e:
            error_box[0] = e
        finally:
            done_box[0] = True
            GLib.idle_add(loop.quit)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    loop.run()
    win.destroy()

    # If cancelled, try to interrupt ComfyUI (delete the queued prompt)
    if cancel_box[0]:
        raise InterruptedError("Generation cancelled by user")

    if error_box[0]:
        raise error_box[0]
    return result_box[0]


# ═══════════════════════════════════════════════════════════════════════════
#  GTK Dialog system — PresetDialog (main UI for img2img/txt2img/inpaint)
# ═══════════════════════════════════════════════════════════════════════════
# All dialogs inherit from Gtk.Dialog (GTK 3) and follow this pattern:
#   1. Build widgets in __init__ using pack_start/append and Grid layouts
#   2. User interacts, then clicks Run or Cancel
#   3. get_values() extracts all widget states into a plain dict
#   4. Caller uses that dict to build and execute the workflow
#
# GTK widget conventions used throughout:
#   ComboBoxText    — dropdown with string IDs (append(id, label), get_active_id())
#   SpinButton      — numeric input with range/step (new_with_range, get_value())
#   TextView        — multi-line text input (get_buffer().get_text(...))
#   FileChooserButton — file picker (get_filename() or get_file().get_path())
#   Grid            — table layout for aligned parameter rows

class PresetDialog(Gtk.Dialog):
    """Main generation dialog — model preset selector with prompt, params, LoRAs.

    Used for img2img, txt2img, and inpaint modes. Mode affects which widgets
    are shown (e.g. denoise spinner only for img2img/inpaint, refinement
    dropdown only for inpaint).
    """

    def __init__(self, title, mode="img2img", server_url=COMFYUI_DEFAULT_URL):
        # Gtk.Dialog provides built-in OK/Cancel button handling and
        # get_content_area() for the main widget container
        super().__init__(title=title)
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(self)
        self.mode = mode

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Branded header
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

        # Banner (animated GIF with static PNG fallback)
        banner = _make_dialog_banner()
        if banner:
            box.pack_start(banner, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188\nChange this if ComfyUI runs on another machine.")
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        self._conn_label = Gtk.Label()
        self._conn_label.set_xalign(0)
        box.pack_start(self._conn_label, False, False, 0)

        # Model preset
        box.pack_start(Gtk.Label(label="Model Preset:", xalign=0), False, False, 0)
        self.preset_combo = Gtk.ComboBoxText()
        for i, p in enumerate(MODEL_PRESETS):
            self.preset_combo.append(str(i), p["label"])
        self.preset_combo.set_active(0)
        self.preset_combo.connect("changed", self._on_preset_changed)
        self.preset_combo.set_tooltip_text("Select the AI Architecture. FLUX is state-of-the-art, SDXL balances speed/quality.")
        box.pack_start(self.preset_combo, False, False, 0)

        # ── User saved presets ──────────────────────────────────────────
        up_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        up_hb.pack_start(Gtk.Label(label="My Presets:"), False, False, 0)
        self._user_preset_combo = Gtk.ComboBoxText()
        self._user_preset_combo.set_hexpand(True)
        self._user_preset_combo.set_tooltip_text("Your saved parameter presets. Save and load your favorite settings.")
        up_hb.pack_start(self._user_preset_combo, True, True, 0)
        _load_btn = Gtk.Button(label="Load")
        _load_btn.set_tooltip_text("Load the selected preset into all fields")
        _load_btn.connect("clicked", self._on_load_user_preset)
        up_hb.pack_start(_load_btn, False, False, 0)
        _save_btn = Gtk.Button(label="Save…")
        _save_btn.set_tooltip_text("Save current settings as a named preset")
        _save_btn.connect("clicked", self._on_save_user_preset)
        up_hb.pack_start(_save_btn, False, False, 0)
        _del_btn = Gtk.Button(label="✕")
        _del_btn.set_tooltip_text("Delete selected preset")
        _del_btn.connect("clicked", self._on_delete_user_preset)
        up_hb.pack_start(_del_btn, False, False, 0)
        box.pack_start(up_hb, False, False, 0)
        self._user_presets = _load_user_presets()
        self._refresh_user_preset_combo()
        # ────────────────────────────────────────────────────────────────

        # ── Scene / Subject Preset dropdown ───────────────────────────
        self._scene_combo = None
        if mode in ("txt2img", "img2img"):
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
            box.pack_start(Gtk.Label(label="Scene Preset (fills prompt for you):", xalign=0), False, False, 0)
            self._scene_combo = Gtk.ComboBoxText()
            self._scene_combo.set_tooltip_text("Pick a ready-made scene to auto-fill the prompt.\nChoose '(custom)' to write your own prompt from scratch.")
            self._refresh_scene_combo()
            self._scene_combo.set_active(0)
            self._scene_combo.connect("changed", self._on_scene_changed)
            box.pack_start(self._scene_combo, False, False, 0)

        # Inpaint refinement dropdown (only in inpaint mode)
        self._refinement_combo = None
        if mode == "inpaint":
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
            box.pack_start(Gtk.Label(label="Body Part / Refinement Preset:", xalign=0), False, False, 0)
            self._refinement_combo = Gtk.ComboBoxText()
            self._refinement_combo.set_tooltip_text("Pre-configured prompts and settings for refining specific body parts.\nSelect one to auto-fill prompt, denoise, and LoRA settings.")
            for i, ref in enumerate(INPAINT_REFINEMENTS):
                self._refinement_combo.append(str(i), ref["label"])
            self._refinement_combo.set_active(0)
            self._refinement_combo.connect("changed", self._on_refinement_changed)
            box.pack_start(self._refinement_combo, False, False, 0)
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # Prompt
        box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        self.prompt_tv = Gtk.TextView()
        self.prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_tooltip_text("Describe your vision. Be specific about subjects, lighting, and style (e.g. 'cinematic lighting, elegant').")
        sw = Gtk.ScrolledWindow(); sw.set_min_content_height(60); sw.add(self.prompt_tv)
        box.pack_start(sw, False, False, 0)

        # Negative
        box.pack_start(Gtk.Label(label="Negative:", xalign=0), False, False, 0)
        self.neg_tv = Gtk.TextView()
        self.neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.neg_tv.set_tooltip_text("Describe elements you DO NOT want in the image (e.g. 'blurry, distorted, watermark, text').")
        sw2 = Gtk.ScrolledWindow(); sw2.set_min_content_height(40); sw2.add(self.neg_tv)
        box.pack_start(sw2, False, False, 0)

        # Params
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        r = 0
        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, r, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 150, 1)
        self.steps_spin.set_tooltip_text("Generation steps: 20-30 is a good baseline. Higher = slower but cleaner.")
        grid.attach(self.steps_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="CFG:", xalign=1), 2, r, 1, 1)
        self.cfg_spin = Gtk.SpinButton.new_with_range(1.0, 30.0, 0.5)
        self.cfg_spin.set_digits(1)
        self.cfg_spin.set_tooltip_text("CFG Scale: How strictly to follow the prompt. 3.5 to 7.0 is usually best.")
        grid.attach(self.cfg_spin, 3, r, 1, 1)
        r += 1

        if mode in ("img2img", "inpaint"):
            grid.attach(Gtk.Label(label="Denoise:", xalign=1), 0, r, 1, 1)
            self.denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
            self.denoise_spin.set_digits(2)
            self.denoise_spin.set_tooltip_text("Denoising Strength:\n1.0 = Completely replace pixels\n0.3 = Subtle enhancement\n0.7 = Strong alteration")
            grid.attach(self.denoise_spin, 1, r, 1, 1)
            r += 1
        else:
            self.denoise_spin = None

        grid.attach(Gtk.Label(label="Width:", xalign=1), 0, r, 1, 1)
        self.w_spin = Gtk.SpinButton.new_with_range(64, 4096, 64)
        self.w_spin.set_tooltip_text("Output image width in pixels. Must be a multiple of 64.\nSD1.5: 512, SDXL/Flux: 1024. Larger sizes use more VRAM.")
        grid.attach(self.w_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Height:", xalign=1), 2, r, 1, 1)
        self.h_spin = Gtk.SpinButton.new_with_range(64, 4096, 64)
        self.h_spin.set_tooltip_text("Output image height in pixels. Must be a multiple of 64.\nSD1.5: 512, SDXL/Flux: 1024. Larger sizes use more VRAM.")
        grid.attach(self.h_spin, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Seed (-1=rand):", xalign=1), 0, r, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**31, 1)
        self.seed_spin.set_value(-1)
        self.seed_spin.set_tooltip_text("Leave at -1 for a random design, or type a number to lock in a specific layout.")
        grid.attach(self.seed_spin, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Sampler:", xalign=1), 0, r, 1, 1)
        self.sampler_entry = Gtk.Entry()
        self.sampler_entry.set_tooltip_text("Sampling algorithm (e.g. euler, dpmpp_2m, euler_ancestral).\nAuto-filled by model preset. Change only if you know what you want.")
        grid.attach(self.sampler_entry, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Scheduler:", xalign=1), 2, r, 1, 1)
        self.scheduler_entry = Gtk.Entry()
        self.scheduler_entry.set_tooltip_text("Noise schedule (e.g. normal, karras, sgm_uniform).\nAuto-filled by model preset. Karras often gives sharper results.")
        grid.attach(self.scheduler_entry, 3, r, 1, 1)

        box.pack_start(grid, False, False, 0)

        # LoRA section
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        lora_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lora_hdr.pack_start(Gtk.Label(label="LoRA (optional):", xalign=0), False, False, 0)
        self._lora_fetch_btn = Gtk.Button(label="Fetch LoRAs")
        self._lora_fetch_btn.set_tooltip_text("Download the list of available LoRAs from the server.\nLoRAs are small add-on models that adjust style or subject.")
        self._lora_fetch_btn.connect("clicked", self._on_fetch_loras)
        lora_hdr.pack_end(self._lora_fetch_btn, False, False, 0)
        box.pack_start(lora_hdr, False, False, 0)

        self._all_lora_names = []   # full server list (unfiltered)
        self._lora_names = []       # currently displayed (filtered by arch)
        self.lora_rows = []         # list of (combo, model_spin, clip_spin)
        self._lora_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for slot in range(3):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            combo = Gtk.ComboBoxText()
            combo.append("none", "(none)")
            combo.set_active(0)
            combo.set_hexpand(True)
            combo.set_tooltip_text("Select a LoRA to blend into the generation.\nLoRAs adjust style, subject, or detail. Leave as (none) to skip.")
            row.pack_start(combo, True, True, 0)

            row.pack_start(Gtk.Label(label="Str:"), False, False, 0)
            ms = Gtk.SpinButton.new_with_range(-5.0, 5.0, 0.05)
            ms.set_digits(2); ms.set_value(1.0)
            ms.set_tooltip_text("Model strength")
            row.pack_start(ms, False, False, 0)

            row.pack_start(Gtk.Label(label="CLIP:"), False, False, 0)
            cs = Gtk.SpinButton.new_with_range(-5.0, 5.0, 0.05)
            cs.set_digits(2); cs.set_value(1.0)
            cs.set_tooltip_text("CLIP strength")
            row.pack_start(cs, False, False, 0)

            self.lora_rows.append((combo, ms, cs))
            self._lora_box.pack_start(row, False, False, 0)
        box.pack_start(self._lora_box, False, False, 0)

        # ── ControlNet Guide (optional) ──────────────────────────────────
        if mode in ("img2img", "inpaint"):
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
            box.pack_start(Gtk.Label(label="ControlNet Structure Guide:", xalign=0), False, False, 0)

            self._cn_mode_combo = Gtk.ComboBoxText()
            self._cn_mode_combo.set_tooltip_text("ControlNet preserves structure from your image (edges, depth, pose).\n'Off' = no structure guide. 'Canny' = edge detection. 'Depth' = 3D depth map.")
            for key in CONTROLNET_GUIDE_MODES:
                self._cn_mode_combo.append(key, key)
            self._cn_mode_combo.set_active(0)  # "Off" by default
            box.pack_start(self._cn_mode_combo, False, False, 0)

            cn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            cn_row.pack_start(Gtk.Label(label="CN Strength:"), False, False, 0)
            self._cn_strength_spin = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
            self._cn_strength_spin.set_digits(2)
            self._cn_strength_spin.set_value(0.8)
            self._cn_strength_spin.set_tooltip_text("How strongly ControlNet guides the generation.\n0.8 is a good default. Higher = more faithful to structure, lower = more creative.")
            cn_row.pack_start(self._cn_strength_spin, False, False, 0)

            cn_row.pack_start(Gtk.Label(label="Start:"), False, False, 0)
            self._cn_start_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
            self._cn_start_spin.set_digits(2)
            self._cn_start_spin.set_value(0.0)
            self._cn_start_spin.set_tooltip_text("When ControlNet starts influencing (0.0 = from the beginning).\nLeave at 0.0 unless you want late-stage guidance only.")
            cn_row.pack_start(self._cn_start_spin, False, False, 0)

            cn_row.pack_start(Gtk.Label(label="End:"), False, False, 0)
            self._cn_end_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
            self._cn_end_spin.set_digits(2)
            self._cn_end_spin.set_value(1.0)
            self._cn_end_spin.set_tooltip_text("When ControlNet stops influencing (1.0 = until the end).\nLowering this lets the AI improvise in the final steps.")
            cn_row.pack_start(self._cn_end_spin, False, False, 0)

            box.pack_start(cn_row, False, False, 0)
        else:
            self._cn_mode_combo = None
            self._cn_strength_spin = None
            self._cn_start_spin = None
            self._cn_end_spin = None

        # Mode label
        if mode == "img2img":
            box.pack_start(Gtk.Label(label="Sends current canvas through model preset.", xalign=0), False, False, 0)
        elif mode == "txt2img":
            box.pack_start(Gtk.Label(label="Generate new image from prompt only.", xalign=0), False, False, 0)

        # Runs spinner
        _add_runs_spinner(self, box)

        # Advanced custom workflow
        exp = Gtk.Expander(label="Advanced: Custom Workflow JSON (overrides everything)")
        exp.set_tooltip_text("Paste a raw ComfyUI workflow JSON here to bypass all presets.\nOnly for advanced users who export workflows from ComfyUI.")
        self.wf_tv = Gtk.TextView()
        self.wf_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.wf_tv.set_monospace(True)
        sw3 = Gtk.ScrolledWindow(); sw3.set_min_content_height(80); sw3.add(self.wf_tv)
        exp.add(sw3)
        box.pack_start(exp, False, False, 0)

        box.show_all()
        self._apply_preset(0)

        # Auto-fetch LoRAs on dialog open
        GLib.idle_add(self._on_fetch_loras, None)

    def _on_fetch_loras(self, _btn):
        """Fetch LoRA list from server asynchronously, update combos on completion.

        Uses _async_fetch to avoid blocking the dialog while the HTTP request
        runs. The connection status label doubles as a server health indicator.
        """
        server = self.server_entry.get_text().strip(); _propagate_server_url(server)
        self._lora_fetch_btn.set_label("Fetching...")
        def on_done(res):
            self._all_lora_names = res
            self._conn_label.set_markup('<span color="green">● Connected</span>')
            self._refresh_lora_combos()
        def on_err(e):
            self._all_lora_names = []
            self._conn_label.set_markup(f'<span color="red">⚠ Cannot connect to {server}</span>')
            self._refresh_lora_combos()
        _async_fetch(lambda: _fetch_loras(server), on_done, on_err)

    def _refresh_lora_combos(self):
        """Filter cached LoRAs for the currently selected model's architecture."""
        idx = self.preset_combo.get_active()
        arch = MODEL_PRESETS[idx]["arch"] if idx >= 0 else "sdxl"
        self._lora_names = _filter_loras_for_arch(self._all_lora_names, arch)
        for combo, _ms, _cs in self.lora_rows:
            combo.remove_all()
            combo.append("none", "(none)")
            for lname in self._lora_names:
                short = lname.rsplit("/", 1)[-1] if "/" in lname else lname
                combo.append(lname, short)
            combo.set_active(0)
        total = len(self._all_lora_names)
        shown = len(self._lora_names)
        self._lora_fetch_btn.set_label(f"{shown}/{total} LoRAs ({arch})")

    def _on_preset_changed(self, combo):
        idx = combo.get_active()
        if idx >= 0:
            self._apply_preset(idx)
            # Re-filter LoRAs for the new architecture
            if self._all_lora_names:
                self._refresh_lora_combos()
            # Re-filter scene presets for the new architecture
            if self._scene_combo:
                self._refresh_scene_combo()

    def _apply_preset(self, idx):
        """Populate all parameter widgets from a MODEL_PRESETS entry."""
        p = MODEL_PRESETS[idx]
        self.steps_spin.set_value(p["steps"])
        self.cfg_spin.set_value(p["cfg"])
        if self.denoise_spin:
            self.denoise_spin.set_value(p["denoise"])
        self.w_spin.set_value(p["width"])
        self.h_spin.set_value(p["height"])
        self.sampler_entry.set_text(p["sampler"])
        self.scheduler_entry.set_text(p["scheduler"])
        # Pre-fill prompt hints (only if empty)
        buf = self.prompt_tv.get_buffer()
        if buf.get_char_count() == 0:
            buf.set_text(p["prompt_hint"])
        buf2 = self.neg_tv.get_buffer()
        if buf2.get_char_count() == 0:
            buf2.set_text(p["negative_hint"])
        # Re-apply refinement if one is active (to update LoRAs for new arch)
        if self._refinement_combo and self._refinement_combo.get_active() > 0:
            self._on_refinement_changed(self._refinement_combo)

    # ── Scene / Subject preset helpers ────────────────────────────────

    def _current_scene_arch(self):
        """Return the scene architecture group for the currently selected model."""
        idx = self.preset_combo.get_active()
        if idx < 0:
            return "sdxl"
        p = MODEL_PRESETS[idx]
        return _scene_arch(p["arch"], p["label"])

    def _refresh_scene_combo(self):
        """Rebuild the scene combo to show only presets valid for the current model."""
        combo = self._scene_combo
        if not combo:
            return
        arch = self._current_scene_arch()
        combo.remove_all()
        self._scene_index_map = []  # maps combo position → SCENE_PRESETS index
        for i, sp in enumerate(SCENE_PRESETS):
            if i == 0:
                # Always show "(custom)" as first option
                combo.append(str(i), sp["label"])
                self._scene_index_map.append(i)
                continue
            prompts = sp.get("prompts", {})
            # Show this preset if it has prompts for the current arch OR a fallback
            if arch in prompts or self._scene_fallback_arch(arch) in prompts:
                combo.append(str(i), sp["label"])
                self._scene_index_map.append(i)
        combo.set_active(0)

    @staticmethod
    def _scene_fallback_arch(arch):
        """Fallback architecture for scene preset lookups."""
        return {
            "sdxl_anime": "sdxl",
            "sdxl_cartoon": "sdxl",
            "sd15": "sdxl",
        }.get(arch, arch)

    def _on_scene_changed(self, combo):
        """Apply the selected scene preset — fills prompt and negative."""
        pos = combo.get_active()
        if pos <= 0:
            return  # "(custom)" or nothing selected
        sp_idx = self._scene_index_map[pos]
        sp = SCENE_PRESETS[sp_idx]
        prompts = sp.get("prompts", {})
        arch = self._current_scene_arch()
        # Try exact arch, then fallback
        prompt, negative = prompts.get(arch) or prompts.get(
            self._scene_fallback_arch(arch), ("", ""))
        if prompt:
            self.prompt_tv.get_buffer().set_text(prompt)
        if negative is not None:
            self.neg_tv.get_buffer().set_text(negative)

    def _on_refinement_changed(self, combo):
        """Apply an inpaint refinement preset: fill prompt, negative, denoise, settings, LoRAs."""
        ridx = combo.get_active()
        if ridx < 0:
            return
        ref = INPAINT_REFINEMENTS[ridx]
        if ridx == 0:
            return  # "(none)" — don't touch anything

        # Fill prompt and negative (always overwrite for refinements)
        self.prompt_tv.get_buffer().set_text(ref["prompt"])
        self.neg_tv.get_buffer().set_text(ref["negative"])

        # Apply denoise override
        if ref["denoise"] is not None and self.denoise_spin:
            self.denoise_spin.set_value(ref["denoise"])

        # Apply steps override
        if ref["steps_override"] is not None:
            self.steps_spin.set_value(ref["steps_override"])

        # Apply CFG boost (add to model's base CFG)
        if ref["cfg_boost"]:
            midx = self.preset_combo.get_active()
            base_cfg = MODEL_PRESETS[midx]["cfg"] if midx >= 0 else 7.0
            self.cfg_spin.set_value(base_cfg + ref["cfg_boost"])

        # Auto-select matching LoRAs for current model architecture
        midx = self.preset_combo.get_active()
        arch = MODEL_PRESETS[midx]["arch"] if midx >= 0 else "sdxl"
        rec_loras = ref["loras"].get(arch, [])

        # Clear all LoRA slots first
        for combo_w, ms, cs in self.lora_rows:
            combo_w.set_active(0)  # "(none)"
            ms.set_value(1.0)
            cs.set_value(1.0)

        # Fill LoRA slots with recommended LoRAs (if they exist on the server)
        slot = 0
        for lora_path, model_str, clip_str in rec_loras:
            if slot >= len(self.lora_rows):
                break
            combo_w, ms, cs = self.lora_rows[slot]
            # Find this LoRA in the combo items
            found = False
            for j, lname in enumerate(self._lora_names):
                if lname == lora_path:
                    combo_w.set_active(j + 1)  # +1 because index 0 is "(none)"
                    ms.set_value(model_str)
                    cs.set_value(clip_str)
                    found = True
                    slot += 1
                    break
            if not found:
                # LoRA not available — skip this slot, try next recommended LoRA
                continue

    def _refresh_user_preset_combo(self):
        self._user_preset_combo.remove_all()
        for p in self._user_presets:
            self._user_preset_combo.append_text(p["name"])
        if self._user_presets:
            self._user_preset_combo.set_active(0)

    def _on_load_user_preset(self, _btn):
        idx = self._user_preset_combo.get_active()
        if idx < 0 or idx >= len(self._user_presets):
            return
        p = self._user_presets[idx]
        self.preset_combo.set_active(p.get("model_preset_idx", 0))
        self.prompt_tv.get_buffer().set_text(p.get("prompt", ""))
        self.neg_tv.get_buffer().set_text(p.get("negative", ""))
        self.steps_spin.set_value(p.get("steps", 20))
        self.cfg_spin.set_value(p.get("cfg", 7.0))
        if self.denoise_spin:
            self.denoise_spin.set_value(p.get("denoise", 0.75))
        self.w_spin.set_value(p.get("width", 512))
        self.h_spin.set_value(p.get("height", 512))
        self.seed_spin.set_value(p.get("seed", -1))
        self.sampler_entry.set_text(p.get("sampler", ""))
        self.scheduler_entry.set_text(p.get("scheduler", ""))
        if "runs" in p:
            self._runs_spin.set_value(p["runs"])
        loras = p.get("loras", [])
        for i, (combo_w, ms, cs) in enumerate(self.lora_rows):
            if i < len(loras):
                lr = loras[i]
                if not combo_w.set_active_id(lr["name"]):
                    combo_w.append(lr["name"], lr["name"])
                    combo_w.set_active_id(lr["name"])
                ms.set_value(lr.get("strength_model", 1.0))
                cs.set_value(lr.get("strength_clip", 1.0))
            else:
                combo_w.set_active(0)
                ms.set_value(1.0); cs.set_value(1.0)

    def _on_save_user_preset(self, _btn):
        dlg = Gtk.Dialog(title="Save Preset", transient_for=self, modal=True)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Save", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        area = dlg.get_content_area()
        area.set_spacing(8)
        area.set_margin_start(12); area.set_margin_end(12)
        area.set_margin_top(12); area.set_margin_bottom(12)
        area.pack_start(Gtk.Label(label="Preset name:"), False, False, 0)
        name_entry = Gtk.Entry()
        name_entry.set_activates_default(True)
        cur_idx = self._user_preset_combo.get_active()
        if 0 <= cur_idx < len(self._user_presets):
            name_entry.set_text(self._user_presets[cur_idx]["name"])
        area.pack_start(name_entry, False, False, 0)
        area.show_all()
        resp = dlg.run()
        name = name_entry.get_text().strip()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK or not name:
            return
        loras = []
        for combo_w, ms, cs in self.lora_rows:
            lora_id = combo_w.get_active_id()
            if lora_id and lora_id != "none":
                loras.append({"name": lora_id,
                              "strength_model": ms.get_value(),
                              "strength_clip": cs.get_value()})
        midx = self.preset_combo.get_active()
        data = {
            "name": name,
            "model_preset_idx": midx if midx >= 0 else 0,
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "steps": int(self.steps_spin.get_value()),
            "cfg": self.cfg_spin.get_value(),
            "denoise": self.denoise_spin.get_value() if self.denoise_spin else 1.0,
            "width": int(self.w_spin.get_value()),
            "height": int(self.h_spin.get_value()),
            "seed": int(self.seed_spin.get_value()),
            "sampler": self.sampler_entry.get_text().strip(),
            "scheduler": self.scheduler_entry.get_text().strip(),
            "loras": loras,
            "runs": int(self._runs_spin.get_value()),
        }
        existing = next((i for i, p in enumerate(self._user_presets) if p["name"] == name), None)
        if existing is not None:
            self._user_presets[existing] = data
        else:
            self._user_presets.append(data)
        _save_user_presets(self._user_presets)
        self._refresh_user_preset_combo()
        new_idx = next((i for i, p in enumerate(self._user_presets) if p["name"] == name), 0)
        self._user_preset_combo.set_active(new_idx)

    def _on_delete_user_preset(self, _btn):
        idx = self._user_preset_combo.get_active()
        if idx < 0 or idx >= len(self._user_presets):
            return
        name = self._user_presets[idx]["name"]
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.YES_NO,
                                text=f'Delete preset "{name}"?')
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            del self._user_presets[idx]
            _save_user_presets(self._user_presets)
            self._refresh_user_preset_combo()

    def _buf_text(self, tv):
        """Extract full text from a Gtk.TextView widget."""
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _collect_session(self):
        """Collect all widget values for session recall."""
        data = {
            "model_preset_idx": self.preset_combo.get_active(),
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "steps": int(self.steps_spin.get_value()),
            "cfg": self.cfg_spin.get_value(),
            "width": int(self.w_spin.get_value()),
            "height": int(self.h_spin.get_value()),
            "seed": int(self.seed_spin.get_value()),
            "sampler": self.sampler_entry.get_text().strip(),
            "scheduler": self.scheduler_entry.get_text().strip(),
        }
        if self.denoise_spin:
            data["denoise"] = self.denoise_spin.get_value()
        data["runs"] = int(self._runs_spin.get_value())
        # ControlNet
        if self._cn_mode_combo:
            data["cn_mode"] = self._cn_mode_combo.get_active_id()
            data["cn_strength"] = self._cn_strength_spin.get_value()
            data["cn_start"] = self._cn_start_spin.get_value()
            data["cn_end"] = self._cn_end_spin.get_value()
        # Scene preset
        if self._scene_combo:
            data["scene_idx"] = self._scene_combo.get_active()
        return data

    def _apply_session(self, p):
        """Restore widget values from session data."""
        if "model_preset_idx" in p:
            idx = p["model_preset_idx"]
            if 0 <= idx < len(MODEL_PRESETS):
                self.preset_combo.set_active(idx)
        # Apply prompt/negative AFTER preset (since preset change may reset them)
        if "prompt" in p:
            self.prompt_tv.get_buffer().set_text(p["prompt"])
        if "negative" in p:
            self.neg_tv.get_buffer().set_text(p["negative"])
        if "steps" in p:
            self.steps_spin.set_value(p["steps"])
        if "cfg" in p:
            self.cfg_spin.set_value(p["cfg"])
        if self.denoise_spin and "denoise" in p:
            self.denoise_spin.set_value(p["denoise"])
        if "width" in p:
            self.w_spin.set_value(p["width"])
        if "height" in p:
            self.h_spin.set_value(p["height"])
        if "seed" in p:
            self.seed_spin.set_value(p["seed"])
        if "sampler" in p:
            self.sampler_entry.set_text(p["sampler"])
        if "scheduler" in p:
            self.scheduler_entry.set_text(p["scheduler"])
        # ControlNet
        if self._cn_mode_combo and "cn_mode" in p:
            self._cn_mode_combo.set_active_id(p["cn_mode"])
        if self._cn_strength_spin and "cn_strength" in p:
            self._cn_strength_spin.set_value(p["cn_strength"])
        if self._cn_start_spin and "cn_start" in p:
            self._cn_start_spin.set_value(p["cn_start"])
        if self._cn_end_spin and "cn_end" in p:
            self._cn_end_spin.set_value(p["cn_end"])
        # Scene preset
        if self._scene_combo and "scene_idx" in p:
            self._scene_combo.set_active(p["scene_idx"])
        if "runs" in p:
            self._runs_spin.set_value(p["runs"])

    def get_values(self):
        """Collect all dialog widget states into a flat dict for the caller.

        Returns a dict with: server, preset (dict copy with overrides applied),
        prompt, negative, seed (randomized if -1), loras, custom_workflow.
        """
        idx = self.preset_combo.get_active()
        preset = dict(MODEL_PRESETS[idx] if idx >= 0 else MODEL_PRESETS[0])
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        custom_wf = self._buf_text(self.wf_tv).strip()
        preset["steps"] = int(self.steps_spin.get_value())
        preset["cfg"] = self.cfg_spin.get_value()
        preset["denoise"] = self.denoise_spin.get_value() if self.denoise_spin else 1.0
        preset["width"] = int(self.w_spin.get_value())
        preset["height"] = int(self.h_spin.get_value())
        preset["sampler"] = self.sampler_entry.get_text().strip()
        preset["scheduler"] = self.scheduler_entry.get_text().strip()
        # Collect active LoRAs
        loras = []
        for combo, ms, cs in self.lora_rows:
            lora_id = combo.get_active_id()
            if lora_id and lora_id != "none":
                loras.append({
                    "name": lora_id,
                    "strength_model": ms.get_value(),
                    "strength_clip": cs.get_value(),
                })
        # ControlNet
        cn_mode = self._cn_mode_combo.get_active_id() if self._cn_mode_combo else "Off"
        controlnet = {
            "mode": cn_mode,
            "strength": self._cn_strength_spin.get_value() if self._cn_strength_spin else 0.8,
            "start_percent": self._cn_start_spin.get_value() if self._cn_start_spin else 0.0,
            "end_percent": self._cn_end_spin.get_value() if self._cn_end_spin else 1.0,
        }
        return {
            "server": self.server_entry.get_text().strip(),
            "preset": preset,
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "seed": seed,
            "loras": loras,
            "controlnet": controlnet,
            "custom_workflow": custom_wf if custom_wf else None,
            "runs": int(self._runs_spin.get_value()),
        }

# ═══════════════════════════════════════════════════════════════════════════
#  Face Swap Dialog
# ═══════════════════════════════════════════════════════════════════════════

class FaceSwapDialog(Gtk.Dialog):
    """Pick a source face image from disk, choose swap model, run ReActor."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - Face Swap (ReActor)")
        self.set_default_size(500, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Swap", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(self)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Branded header
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Source face file chooser
        box.pack_start(Gtk.Label(label="Source Face Image:", xalign=0), False, False, 0)
        self.face_chooser = Gtk.FileChooserButton(title="Select face source image")
        self.face_chooser.set_tooltip_text("Select an image containing the face you want to paste onto the canvas.\nThe image should have a clearly visible face.")
        self.face_chooser.set_action(Gtk.FileChooserAction.OPEN)
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_pattern("*.png"); ff.add_pattern("*.jpg"); ff.add_pattern("*.jpeg")
        ff.add_pattern("*.webp"); ff.add_pattern("*.bmp")
        self.face_chooser.add_filter(ff)
        box.pack_start(self.face_chooser, False, False, 0)

        # Fetch models button
        self._fetch_btn = Gtk.Button(label="Fetch Models from Server")
        self._fetch_btn.set_tooltip_text("Download available swap and restore models from the server.")
        self._fetch_btn.connect("clicked", self._on_fetch_models)
        box.pack_start(self._fetch_btn, False, False, 0)

        # Swap model
        box.pack_start(Gtk.Label(label="Swap Model:", xalign=0), False, False, 0)
        self.swap_combo = Gtk.ComboBoxText()
        self.swap_combo.set_tooltip_text("AI model used to perform the face swap.\ninswapper_128 is the standard choice.")
        for m in FACE_SWAP_MODELS:
            self.swap_combo.append(m, m)
        self.swap_combo.set_active(0)
        box.pack_start(self.swap_combo, False, False, 0)

        # Face restore
        box.pack_start(Gtk.Label(label="Face Restore Model:", xalign=0), False, False, 0)
        self.restore_combo = Gtk.ComboBoxText()
        self.restore_combo.set_tooltip_text("Post-processing model to clean up the swapped face.\nCodeFormer gives the best quality. GFPGAN is faster.")
        for m in FACE_RESTORE_MODELS:
            self.restore_combo.append(m, m)
        self.restore_combo.set_active(1)  # codeformer default
        box.pack_start(self.restore_combo, False, False, 0)

        # Restore visibility + codeformer weight
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label="Restore Visibility:", xalign=1), 0, 0, 1, 1)
        self.restore_vis = Gtk.SpinButton.new_with_range(0.1, 1.0, 0.05)
        self.restore_vis.set_digits(2); self.restore_vis.set_value(1.0)
        self.restore_vis.set_tooltip_text("How visible the face restoration effect is.\n1.0 = full effect, lower values blend with the raw swap result.")
        grid.attach(self.restore_vis, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="CodeFormer Weight:", xalign=1), 0, 1, 1, 1)
        self.cf_weight = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.cf_weight.set_digits(2); self.cf_weight.set_value(0.5)
        self.cf_weight.set_tooltip_text("CodeFormer fidelity weight (only affects CodeFormer model).\n0.0 = maximum quality, 1.0 = maximum fidelity to input. Default: 0.5")
        grid.attach(self.cf_weight, 1, 1, 1, 1)
        box.pack_start(grid, False, False, 0)

        # Face indices
        grid2 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid2.attach(Gtk.Label(label="Input Face Index:", xalign=1), 0, 0, 1, 1)
        self.input_idx = Gtk.Entry(); self.input_idx.set_text("0")
        self.input_idx.set_tooltip_text("Which face in the target image to replace.\n0 = first detected face. Use comma-separated values for multiple (e.g. 0,1).")
        grid2.attach(self.input_idx, 1, 0, 1, 1)
        grid2.attach(Gtk.Label(label="Source Face Index:", xalign=1), 0, 1, 1, 1)
        self.source_idx = Gtk.Entry(); self.source_idx.set_text("0")
        self.source_idx.set_tooltip_text("Which face in the source image to use.\n0 = first detected face. Usually leave at 0 unless your source has multiple faces.")
        grid2.attach(self.source_idx, 1, 1, 1, 1)
        box.pack_start(grid2, False, False, 0)

        # Gender filter
        grid3 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid3.attach(Gtk.Label(label="Filter Input Gender:", xalign=1), 0, 0, 1, 1)
        self.gender_input = Gtk.ComboBoxText()
        self.gender_input.set_tooltip_text("Only swap faces of this gender in the target image.\n'no' = swap all detected faces regardless of gender.")
        for g in ["no", "female", "male"]:
            self.gender_input.append(g, g)
        self.gender_input.set_active(0)
        grid3.attach(self.gender_input, 1, 0, 1, 1)
        grid3.attach(Gtk.Label(label="Filter Source Gender:", xalign=1), 0, 1, 1, 1)
        self.gender_source = Gtk.ComboBoxText()
        self.gender_source.set_tooltip_text("Only use faces of this gender from the source image.\n'no' = use any detected face regardless of gender.")
        for g in ["no", "female", "male"]:
            self.gender_source.append(g, g)
        self.gender_source.set_active(0)
        grid3.attach(self.gender_source, 1, 1, 1, 1)
        box.pack_start(grid3, False, False, 0)

        # ── Save Face Model section ─────────────────────────────────────
        save_frame = Gtk.Frame(label="Save Face Model")
        save_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        save_box.set_margin_start(8); save_box.set_margin_end(8)
        save_box.set_margin_top(4); save_box.set_margin_bottom(8)

        self.save_model_check = Gtk.CheckButton(label="Save face model for reuse")
        self.save_model_check.set_active(False)
        self.save_model_check.set_tooltip_text(
            "Extract and save a face model from the source image.\n"
            "Saved models can be loaded later without re-uploading the image.")
        self.save_model_check.connect("toggled", self._on_save_toggled)
        save_box.pack_start(self.save_model_check, False, False, 0)

        name_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name_row.pack_start(Gtk.Label(label="Model Name:"), False, False, 0)
        self.save_model_name = Gtk.Entry()
        self.save_model_name.set_text("my_face")
        self.save_model_name.set_placeholder_text("Enter a name for the face model")
        self.save_model_name.set_hexpand(True)
        self.save_model_name.set_sensitive(False)
        self.save_model_name.set_tooltip_text("Name for the saved face model file.\nUse a descriptive name like 'john_doe' so you can find it later.")
        name_row.pack_start(self.save_model_name, True, True, 0)
        save_box.pack_start(name_row, False, False, 0)

        self.overwrite_check = Gtk.CheckButton(label="Overwrite existing model if name matches")
        self.overwrite_check.set_active(True)
        self.overwrite_check.set_sensitive(False)
        self.overwrite_check.set_tooltip_text(
            "If checked, replaces any existing model with the same name.\n"
            "If unchecked, saves with a numeric suffix to avoid collision.")
        save_box.pack_start(self.overwrite_check, False, False, 0)

        save_frame.add(save_box)
        box.pack_start(save_frame, False, False, 0)

        box.show_all()

        # Auto-fetch models on dialog open
        self._on_fetch_models(None)

    def _on_save_toggled(self, check):
        """Enable/disable the save face model name entry and overwrite toggle."""
        active = check.get_active()
        self.save_model_name.set_sensitive(active)
        self.overwrite_check.set_sensitive(active)

    def _on_fetch_models(self, _btn):
        """Fetch swap and restore model lists from the ComfyUI server."""
        server = self.server_entry.get_text().strip(); _propagate_server_url(server)
        try:
            swap_list, restore_list = _fetch_reactor_models(server)
        except Exception:
            swap_list, restore_list = [], []

        if swap_list:
            self.swap_combo.remove_all()
            for m in swap_list:
                self.swap_combo.append(m, m)
            self.swap_combo.set_active(0)

        if restore_list:
            self.restore_combo.remove_all()
            for m in restore_list:
                self.restore_combo.append(m, m)
            # Try to default to codeformer
            for i, m in enumerate(restore_list):
                if "codeformer" in m.lower():
                    self.restore_combo.set_active(i)
                    break
            else:
                self.restore_combo.set_active(0)

        n_swap = len(swap_list) if swap_list else len(FACE_SWAP_MODELS)
        n_rest = len(restore_list) if restore_list else len(FACE_RESTORE_MODELS)
        src = "server" if swap_list else "local"
        self._fetch_btn.set_label(f"Models: {n_swap} swap, {n_rest} restore ({src})")

    def get_values(self):
        face_file = self.face_chooser.get_filename()
        return {
            "server": self.server_entry.get_text().strip(),
            "face_file": face_file,
            "swap_model": self.swap_combo.get_active_id() or FACE_SWAP_MODELS[0],
            "face_restore_model": self.restore_combo.get_active_id() or "codeformer-v0.1.0.pth",
            "face_restore_vis": self.restore_vis.get_value(),
            "codeformer_weight": self.cf_weight.get_value(),
            "input_face_idx": self.input_idx.get_text().strip() or "0",
            "source_face_idx": self.source_idx.get_text().strip() or "0",
            "detect_gender_input": self.gender_input.get_active_id() or "no",
            "detect_gender_source": self.gender_source.get_active_id() or "no",
            "save_face_model": self.save_model_check.get_active(),
            "save_model_name": self.save_model_name.get_text().strip(),
            "save_overwrite": self.overwrite_check.get_active(),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Face Swap with Saved Face Model Dialog
# ═══════════════════════════════════════════════════════════════════════════

class FaceSwapModelDialog(Gtk.Dialog):
    """Face swap using a saved face model from the server (no source image needed)."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - Face Swap (Saved Face Model)")
        self.set_default_size(500, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Swap", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(self)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Branded header
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Fetch button
        self._fetch_btn = Gtk.Button(label="Fetch Models from Server")
        self._fetch_btn.set_tooltip_text("Download available face models, swap models, and restore models from the server.")
        self._fetch_btn.connect("clicked", self._on_fetch_models)
        box.pack_start(self._fetch_btn, False, False, 0)

        # Face model selector
        box.pack_start(Gtk.Label(label="Face Model:", xalign=0), False, False, 0)
        self.face_model_combo = Gtk.ComboBoxText()
        self.face_model_combo.set_tooltip_text("Previously saved face model to use as the swap source.\nSave face models via the 'Face Swap (ReActor)' dialog.")
        self.face_model_combo.append("none", "(none — select a model)")
        self.face_model_combo.set_active(0)
        box.pack_start(self.face_model_combo, False, False, 0)

        # Swap model
        box.pack_start(Gtk.Label(label="Swap Model:", xalign=0), False, False, 0)
        self.swap_combo = Gtk.ComboBoxText()
        self.swap_combo.set_tooltip_text("AI model used to perform the face swap.\ninswapper_128 is the standard choice.")
        for m in FACE_SWAP_MODELS:
            self.swap_combo.append(m, m)
        self.swap_combo.set_active(0)
        box.pack_start(self.swap_combo, False, False, 0)

        # Face restore
        box.pack_start(Gtk.Label(label="Face Restore Model:", xalign=0), False, False, 0)
        self.restore_combo = Gtk.ComboBoxText()
        self.restore_combo.set_tooltip_text("Post-processing model to clean up the swapped face.\nCodeFormer gives the best quality. GFPGAN is faster.")
        for m in FACE_RESTORE_MODELS:
            self.restore_combo.append(m, m)
        self.restore_combo.set_active(1)
        box.pack_start(self.restore_combo, False, False, 0)

        # Restore visibility + codeformer weight
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label="Restore Visibility:", xalign=1), 0, 0, 1, 1)
        self.restore_vis = Gtk.SpinButton.new_with_range(0.1, 1.0, 0.05)
        self.restore_vis.set_digits(2); self.restore_vis.set_value(1.0)
        self.restore_vis.set_tooltip_text("How visible the face restoration effect is.\n1.0 = full effect, lower values blend with the raw swap result.")
        grid.attach(self.restore_vis, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="CodeFormer Weight:", xalign=1), 0, 1, 1, 1)
        self.cf_weight = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.cf_weight.set_digits(2); self.cf_weight.set_value(0.5)
        self.cf_weight.set_tooltip_text("CodeFormer fidelity weight.\n0.0 = maximum quality, 1.0 = maximum fidelity to input. Default: 0.5")
        grid.attach(self.cf_weight, 1, 1, 1, 1)
        box.pack_start(grid, False, False, 0)

        # Face indices
        grid2 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid2.attach(Gtk.Label(label="Input Face Index:", xalign=1), 0, 0, 1, 1)
        self.input_idx = Gtk.Entry(); self.input_idx.set_text("0")
        self.input_idx.set_tooltip_text("Which face in the target image to replace.\n0 = first detected face. Comma-separated for multiple (e.g. 0,1).")
        grid2.attach(self.input_idx, 1, 0, 1, 1)
        grid2.attach(Gtk.Label(label="Source Face Index:", xalign=1), 0, 1, 1, 1)
        self.source_idx = Gtk.Entry(); self.source_idx.set_text("0")
        self.source_idx.set_tooltip_text("Which face in the saved model to use.\n0 = first face. Usually leave at 0.")
        grid2.attach(self.source_idx, 1, 1, 1, 1)
        box.pack_start(grid2, False, False, 0)

        # Gender filter
        grid3 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid3.attach(Gtk.Label(label="Filter Input Gender:", xalign=1), 0, 0, 1, 1)
        self.gender_input = Gtk.ComboBoxText()
        self.gender_input.set_tooltip_text("Only swap faces of this gender in the target image.\n'no' = swap all detected faces regardless of gender.")
        for g in ["no", "female", "male"]:
            self.gender_input.append(g, g)
        self.gender_input.set_active(0)
        grid3.attach(self.gender_input, 1, 0, 1, 1)
        grid3.attach(Gtk.Label(label="Filter Source Gender:", xalign=1), 0, 1, 1, 1)
        self.gender_source = Gtk.ComboBoxText()
        self.gender_source.set_tooltip_text("Only use faces of this gender from the saved model.\n'no' = use any detected face regardless of gender.")
        for g in ["no", "female", "male"]:
            self.gender_source.append(g, g)
        self.gender_source.set_active(0)
        grid3.attach(self.gender_source, 1, 1, 1, 1)
        box.pack_start(grid3, False, False, 0)

        box.show_all()
        self._on_fetch_models(None)

    def _on_fetch_models(self, _btn):
        server = self.server_entry.get_text().strip(); _propagate_server_url(server)
        # Fetch face models
        face_models = _fetch_face_models(server)
        if face_models:
            self.face_model_combo.remove_all()
            for m in face_models:
                self.face_model_combo.append(m, m)
            self.face_model_combo.set_active(0)
        # Fetch swap/restore models
        try:
            swap_list, restore_list = _fetch_reactor_models(server)
        except Exception:
            swap_list, restore_list = [], []
        if swap_list:
            self.swap_combo.remove_all()
            for m in swap_list:
                self.swap_combo.append(m, m)
            self.swap_combo.set_active(0)
        if restore_list:
            self.restore_combo.remove_all()
            for m in restore_list:
                self.restore_combo.append(m, m)
            for i, m in enumerate(restore_list):
                if "codeformer" in m.lower():
                    self.restore_combo.set_active(i); break
            else:
                self.restore_combo.set_active(0)

        n_face = len(face_models) if face_models else 0
        self._fetch_btn.set_label(f"{n_face} face models loaded")

    def get_values(self):
        return {
            "server": self.server_entry.get_text().strip(),
            "face_model": self.face_model_combo.get_active_id(),
            "swap_model": self.swap_combo.get_active_id() or FACE_SWAP_MODELS[0],
            "face_restore_model": self.restore_combo.get_active_id() or "codeformer-v0.1.0.pth",
            "face_restore_vis": self.restore_vis.get_value(),
            "codeformer_weight": self.cf_weight.get_value(),
            "input_face_idx": self.input_idx.get_text().strip() or "0",
            "source_face_idx": self.source_idx.get_text().strip() or "0",
            "detect_gender_input": self.gender_input.get_active_id() or "no",
            "detect_gender_source": self.gender_source.get_active_id() or "no",
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Wan 2.2 Image-to-Video Dialog
# ═══════════════════════════════════════════════════════════════════════════

class WanI2VDialog(Gtk.Dialog):
    """Wan 2.2 Image-to-Video with LoRA management."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - Wan 2.2 Image to Video")
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Generate", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(self)

        self._all_wan_loras = []
        self._wan_loras = []

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Branded header
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Model preset
        box.pack_start(Gtk.Label(label="Model Preset:", xalign=0), False, False, 0)
        self.preset_combo = Gtk.ComboBoxText()
        self.preset_combo.set_tooltip_text("Wan 2.2 video model variant.\nDifferent presets trade off quality vs. speed and VRAM usage.")
        for key in WAN_I2V_PRESETS:
            self.preset_combo.append(key, key)
        self.preset_combo.set_active(0)
        self.preset_combo.connect("changed", self._on_preset_changed)
        box.pack_start(self.preset_combo, False, False, 0)

        # Video prompt preset (template)
        box.pack_start(Gtk.Label(label="Prompt Template:", xalign=0), False, False, 0)
        self._video_preset_combo = Gtk.ComboBoxText()
        self._video_preset_combo.set_tooltip_text("Ready-made motion templates that auto-fill prompt and settings.\nSelect one to get started quickly, or use manual prompt.")
        for i, vp in enumerate(WAN_VIDEO_PRESETS):
            self._video_preset_combo.append(str(i), vp["label"])
        self._video_preset_combo.set_active(0)
        self._video_preset_combo.connect("changed", self._on_video_preset_changed)
        box.pack_start(self._video_preset_combo, False, False, 0)

        # Prompt
        box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(60)
        self.prompt_tv = Gtk.TextView()
        self.prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_tooltip_text("Describe the motion and scene for your video.\nBe specific about camera movement and subject action (e.g. 'slow camera zoom in, hair flowing').")
        sw.add(self.prompt_tv)
        box.pack_start(sw, False, False, 0)

        # Negative prompt
        box.pack_start(Gtk.Label(label="Negative Prompt:", xalign=0), False, False, 0)
        sw2 = Gtk.ScrolledWindow()
        sw2.set_min_content_height(40)
        self.neg_tv = Gtk.TextView()
        self.neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.neg_tv.set_tooltip_text("Describe what you do NOT want in the video (e.g. 'blurry, distorted, static').")
        self.neg_tv.get_buffer().set_text("blurry, distorted, low quality")
        sw2.add(self.neg_tv)
        box.pack_start(sw2, False, False, 0)

        # Parameters grid
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)

        grid.attach(Gtk.Label(label="Width:", xalign=1), 0, 0, 1, 1)
        self.w_spin = Gtk.SpinButton.new_with_range(16, 2048, 16)
        self.w_spin.set_value(832)
        self.w_spin.set_tooltip_text("Video width in pixels. Default: 832.\nLarger = more detail but much more VRAM and time.")
        grid.attach(self.w_spin, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Height:", xalign=1), 2, 0, 1, 1)
        self.h_spin = Gtk.SpinButton.new_with_range(16, 2048, 16)
        self.h_spin.set_value(480)
        self.h_spin.set_tooltip_text("Video height in pixels. Default: 480.\nLarger = more detail but much more VRAM and time.")
        grid.attach(self.h_spin, 3, 0, 1, 1)

        grid.attach(Gtk.Label(label="Frames:", xalign=1), 0, 1, 1, 1)
        self.length_spin = Gtk.SpinButton.new_with_range(1, 257, 4)
        self.length_spin.set_value(81)
        self.length_spin.set_tooltip_text("Total number of video frames to generate.\n81 frames at 16 FPS = ~5 seconds of video. More frames = longer generation.")
        grid.attach(self.length_spin, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="FPS:", xalign=1), 2, 1, 1, 1)
        self.fps_spin = Gtk.SpinButton.new_with_range(1, 60, 1)
        self.fps_spin.set_value(16)
        self.fps_spin.set_tooltip_text("Frames per second for the output video. Default: 16.\nHigher = smoother but shorter video for the same frame count.")
        grid.attach(self.fps_spin, 3, 1, 1, 1)

        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, 2, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.steps_spin.set_value(30)
        self.steps_spin.set_tooltip_text("Denoising steps per frame. Default: 30.\nMore steps = better quality but slower generation.")
        grid.attach(self.steps_spin, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="CFG:", xalign=1), 2, 2, 1, 1)
        self.cfg_spin = Gtk.SpinButton.new_with_range(0.0, 30.0, 0.5)
        self.cfg_spin.set_digits(1); self.cfg_spin.set_value(5.0)
        self.cfg_spin.set_tooltip_text("CFG Scale: How strictly to follow the prompt. Default: 5.0.\nHigher = more literal prompt following, lower = more creative.")
        grid.attach(self.cfg_spin, 3, 2, 1, 1)

        grid.attach(Gtk.Label(label="Shift:", xalign=1), 0, 3, 1, 1)
        self.shift_spin = Gtk.SpinButton.new_with_range(0.0, 100.0, 0.5)
        self.shift_spin.set_digits(1); self.shift_spin.set_value(8.0)
        self.shift_spin.set_tooltip_text("Noise shift parameter. Default: 8.0.\nControls the noise schedule distribution. Higher values can improve temporal coherence.")
        grid.attach(self.shift_spin, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="Switch Step:", xalign=1), 2, 3, 1, 1)
        self.second_step_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.second_step_spin.set_value(20)
        self.second_step_spin.set_tooltip_text(
            "Step at which sampling switches from high-noise to low-noise model")
        grid.attach(self.second_step_spin, 3, 3, 1, 1)

        grid.attach(Gtk.Label(label="Seed:", xalign=1), 0, 4, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32 - 1, 1)
        self.seed_spin.set_value(-1)
        self.seed_spin.set_tooltip_text("-1 = random seed each time.\nSet a specific number to reproduce the exact same video.")
        grid.attach(self.seed_spin, 1, 4, 2, 1)

        box.pack_start(grid, False, False, 0)

        # Post-processing & output options
        pp_frame = Gtk.Frame(label="Post-processing & Output")
        pp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pp_box.set_margin_start(8); pp_box.set_margin_end(8)
        pp_box.set_margin_top(4); pp_box.set_margin_bottom(8)

        # Row 1: RTX upscale toggle + scale value
        rtx_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.upscale_check = Gtk.CheckButton(label="RTX Upscale")
        self.upscale_check.set_active(True)
        self.upscale_check.set_tooltip_text("Apply RTXVideoSuperResolution upscale")
        rtx_row.pack_start(self.upscale_check, False, False, 0)
        rtx_row.pack_start(Gtk.Label(label="Scale:"), False, False, 0)
        self.upscale_spin = Gtk.SpinButton.new_with_range(1.0, 4.0, 0.25)
        self.upscale_spin.set_digits(2); self.upscale_spin.set_value(1.5)
        self.upscale_spin.set_tooltip_text("RTX upscale factor (e.g. 1.5 = 50% larger)")
        rtx_row.pack_start(self.upscale_spin, False, False, 0)
        pp_box.pack_start(rtx_row, False, False, 0)

        # Row 2: RIFE interpolation + ping pong
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.interpolate_check = Gtk.CheckButton(label="RIFE 2× Interpolation")
        self.interpolate_check.set_active(True)
        self.interpolate_check.set_tooltip_text("Apply RIFE VFI 2× frame interpolation (doubles FPS)")
        row2.pack_start(self.interpolate_check, False, False, 0)
        self.pingpong_check = Gtk.CheckButton(label="Ping Pong")
        self.pingpong_check.set_active(False)
        self.pingpong_check.set_tooltip_text("Play video forward then backward for seamless looping")
        row2.pack_start(self.pingpong_check, False, False, 0)
        pp_box.pack_start(row2, False, False, 0)

        pp_frame.add(pp_box)
        box.pack_start(pp_frame, False, False, 0)

        # LoRA section
        lora_frame = Gtk.Frame(label="LoRAs")
        lora_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lora_box.set_margin_start(8); lora_box.set_margin_end(8)
        lora_box.set_margin_top(4); lora_box.set_margin_bottom(8)

        self._lora_fetch_btn = Gtk.Button(label="Fetch Wan LoRAs")
        self._lora_fetch_btn.set_tooltip_text("Download available Wan video LoRAs from the server.\nLoRAs add motion styles like camera pans, zooms, etc.")
        self._lora_fetch_btn.connect("clicked", self._on_fetch_loras)
        lora_box.pack_start(self._lora_fetch_btn, False, False, 0)

        self.lora_rows = []
        for i in range(3):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            combo = Gtk.ComboBoxText()
            combo.append("none", "(none)")
            combo.set_active(0)
            combo.set_hexpand(True)
            combo.set_tooltip_text("Select a video LoRA for motion style (camera, subject movement).\nLeave as (none) to skip.")
            row.pack_start(combo, True, True, 0)

            row.pack_start(Gtk.Label(label="Str:"), False, False, 0)
            strength = Gtk.SpinButton.new_with_range(-2.0, 2.0, 0.05)
            strength.set_digits(2); strength.set_value(1.0)
            strength.set_tooltip_text("LoRA strength. 1.0 = full effect.\nLower for subtlety, higher for exaggeration.")
            row.pack_start(strength, False, False, 0)

            lora_box.pack_start(row, False, False, 0)
            self.lora_rows.append((combo, strength))

        lora_frame.add(lora_box)
        box.pack_start(lora_frame, False, False, 0)

        # ── User saved presets ──────────────────────────────────────────
        _add_preset_ui(self, box, "wan_i2v")

        # Runs spinner
        _add_runs_spinner(self, box)

        box.show_all()

    def _on_fetch_loras(self, _btn):
        server = self.server_entry.get_text().strip(); _propagate_server_url(server)
        try:
            self._all_wan_loras = _fetch_wan_video_loras(server)
        except Exception:
            self._all_wan_loras = []
        self._refresh_lora_combos()

    def _refresh_lora_combos(self):
        preset_key = self.preset_combo.get_active_id() or ""
        self._wan_loras = _filter_wan_loras(self._all_wan_loras, preset_key)
        for combo, _str in self.lora_rows:
            combo.remove_all()
            combo.append("none", "(none)")
            for lname in self._wan_loras:
                short = lname.rsplit("/", 1)[-1] if "/" in lname else lname
                combo.append(lname, short)
            combo.set_active(0)
        total = len(self._all_wan_loras)
        shown = len(self._wan_loras)
        self._lora_fetch_btn.set_label(f"{shown}/{total} Wan LoRAs")

    def _on_preset_changed(self, combo):
        if self._all_wan_loras:
            self._refresh_lora_combos()

    def _on_video_preset_changed(self, combo):
        """Apply a video prompt template: fill prompt, negative, and override settings."""
        vidx = combo.get_active()
        if vidx < 0:
            return
        vp = WAN_VIDEO_PRESETS[vidx]
        if vidx == 0:
            return  # "(none — manual prompt)" — don't touch anything

        # Fill prompt & negative
        self.prompt_tv.get_buffer().set_text(vp["prompt"])
        self.neg_tv.get_buffer().set_text(vp["negative"])

        # Apply optional overrides
        if vp["cfg_override"] is not None:
            self.cfg_spin.set_value(vp["cfg_override"])
        if vp["steps_override"] is not None:
            self.steps_spin.set_value(vp["steps_override"])
        if vp["length_override"] is not None:
            self.length_spin.set_value(vp["length_override"])
        if vp["pingpong"] is not None:
            self.pingpong_check.set_active(vp["pingpong"])

        # Auto-select recommended LoRAs if any & lora list is populated
        if vp["loras"] and self._wan_loras:
            for slot_idx, (lora_name, lora_str) in enumerate(vp["loras"]):
                if slot_idx >= len(self.lora_rows):
                    break
                row_combo, row_strength = self.lora_rows[slot_idx]
                # Find matching lora in combo
                found = False
                for j, name in enumerate(self._wan_loras):
                    if name == lora_name or name.endswith(lora_name):
                        row_combo.set_active(j + 1)  # +1 for "(none)" entry
                        row_strength.set_value(lora_str)
                        found = True
                        break
                if not found:
                    row_combo.set_active(0)

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _collect_user_preset(self):
        """Collect current widget values into a dict for preset storage."""
        return {
            "preset_key": self.preset_combo.get_active_id(),
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "width": int(self.w_spin.get_value()),
            "height": int(self.h_spin.get_value()),
            "length": int(self.length_spin.get_value()),
            "fps": int(self.fps_spin.get_value()),
            "steps": int(self.steps_spin.get_value()),
            "cfg": self.cfg_spin.get_value(),
            "shift": self.shift_spin.get_value(),
            "second_step": int(self.second_step_spin.get_value()),
            "seed": int(self.seed_spin.get_value()),
            "upscale": self.upscale_check.get_active(),
            "upscale_factor": self.upscale_spin.get_value(),
            "interpolate": self.interpolate_check.get_active(),
            "pingpong": self.pingpong_check.get_active(),
            "runs": int(self._runs_spin.get_value()),
        }

    def _apply_user_preset(self, p):
        """Restore widget values from a preset dict."""
        if "preset_key" in p:
            for i, key in enumerate(WAN_I2V_PRESETS):
                if key == p["preset_key"]:
                    self.preset_combo.set_active(i)
                    break
        self.prompt_tv.get_buffer().set_text(p.get("prompt", ""))
        self.neg_tv.get_buffer().set_text(p.get("negative", ""))
        self.w_spin.set_value(p.get("width", 832))
        self.h_spin.set_value(p.get("height", 480))
        self.length_spin.set_value(p.get("length", 81))
        self.fps_spin.set_value(p.get("fps", 16))
        self.steps_spin.set_value(p.get("steps", 30))
        self.cfg_spin.set_value(p.get("cfg", 5.0))
        self.shift_spin.set_value(p.get("shift", 8.0))
        self.second_step_spin.set_value(p.get("second_step", 20))
        self.seed_spin.set_value(p.get("seed", -1))
        self.upscale_check.set_active(p.get("upscale", True))
        self.upscale_spin.set_value(p.get("upscale_factor", 1.5))
        self.interpolate_check.set_active(p.get("interpolate", True))
        self.pingpong_check.set_active(p.get("pingpong", False))
        if "runs" in p:
            self._runs_spin.set_value(p["runs"])

    def get_values(self):
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)

        loras = []
        for combo, strength in self.lora_rows:
            lid = combo.get_active_id()
            if lid and lid != "none":
                loras.append((lid, strength.get_value()))

        return {
            "server": self.server_entry.get_text().strip(),
            "preset_key": self.preset_combo.get_active_id(),
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "width": int(self.w_spin.get_value()),
            "height": int(self.h_spin.get_value()),
            "length": int(self.length_spin.get_value()),
            "fps": int(self.fps_spin.get_value()),
            "steps": int(self.steps_spin.get_value()),
            "cfg": self.cfg_spin.get_value(),
            "shift": self.shift_spin.get_value(),
            "second_step": int(self.second_step_spin.get_value()),
            "seed": seed,
            "loras": loras if loras else None,
            "upscale": self.upscale_check.get_active(),
            "upscale_factor": self.upscale_spin.get_value(),
            "interpolate": self.interpolate_check.get_active(),
            "pingpong": self.pingpong_check.get_active(),
            "runs": int(self._runs_spin.get_value()),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  mtb Face Swap Dialog
# ═══════════════════════════════════════════════════════════════════════════

class MtbFaceSwapDialog(Gtk.Dialog):
    """mtb facetools direct face swap — requires source image file."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - Face Swap (mtb)")
        self.set_default_size(480, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(self)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Branded header
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

        # Server
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Server:"))
        self.server_entry = Gtk.Entry(text=server_url, hexpand=True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        row.append(self.server_entry)
        box.append(row)

        # Source face image file chooser
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Source Face Image:"))
        self.source_chooser = Gtk.FileChooserButton(title="Select source face image")
        self.source_chooser.set_tooltip_text("Select an image containing the face you want to paste onto the canvas.")
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_mime_type("image/png")
        ff.add_mime_type("image/jpeg")
        ff.add_pattern("*.png")
        ff.add_pattern("*.jpg")
        ff.add_pattern("*.jpeg")
        self.source_chooser.add_filter(ff)
        self.source_chooser.set_hexpand(True)
        row.append(self.source_chooser)
        box.append(row)

        # Analysis model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Analysis Model:"))
        self.analysis_combo = Gtk.ComboBoxText()
        self.analysis_combo.set_tooltip_text("Face detection model. buffalo_l is the most accurate.\nSmaller models (buffalo_m, buffalo_sc) are faster but less reliable.")
        for m in ["buffalo_l", "antelopev2", "buffalo_m", "buffalo_sc"]:
            self.analysis_combo.append(m, m)
        self.analysis_combo.set_active_id("buffalo_l")
        self.analysis_combo.set_hexpand(True)
        row.append(self.analysis_combo)
        box.append(row)

        # Swap model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Swap Model:"))
        self.swap_combo = Gtk.ComboBoxText()
        self.swap_combo.set_tooltip_text("Face swap model. inswapper_128 is standard.\nfp16 variant uses less VRAM but may be slightly less accurate.")
        for m in ["inswapper_128.onnx", "inswapper_128_fp16.onnx"]:
            self.swap_combo.append(m, m)
        self.swap_combo.set_active_id("inswapper_128.onnx")
        self.swap_combo.set_hexpand(True)
        row.append(self.swap_combo)
        box.append(row)

        # Face index
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Face Index:"))
        self.face_idx = Gtk.Entry(text="0")
        self.face_idx.set_tooltip_text("0 = first face, comma-separated for multiple")
        self.face_idx.set_hexpand(True)
        row.append(self.face_idx)
        box.append(row)

        # Fetch models from server
        fetch_btn = Gtk.Button(label="Fetch Models from Server")
        fetch_btn.connect("clicked", self._on_fetch)
        box.append(fetch_btn)

        self.show()

    def _on_fetch(self, _btn):
        srv = self.server_entry.get_text().strip(); _propagate_server_url(srv)
        try:
            analysis = _fetch_mtb_analysis_models(srv)
            swaps = _fetch_mtb_swap_models(srv)
            self.analysis_combo.remove_all()
            for m in analysis:
                self.analysis_combo.append(m, m)
            if analysis:
                self.analysis_combo.set_active(0)
            self.swap_combo.remove_all()
            for m in swaps:
                self.swap_combo.append(m, m)
            if swaps:
                self.swap_combo.set_active(0)
        except Exception as e:
            Gimp.message(f"Fetch error: {e}")

    def get_values(self):
        source_path = None
        f = self.source_chooser.get_file()
        if f:
            source_path = f.get_path()
        return {
            "server": self.server_entry.get_text().strip(),
            "source_path": source_path,
            "analysis_model": self.analysis_combo.get_active_id() or "buffalo_l",
            "swap_model": self.swap_combo.get_active_id() or "inswapper_128.onnx",
            "faces_index": self.face_idx.get_text().strip() or "0",
        }


# ═══════════════════════════════════════════════════════════════════════════
#  IPAdapter FaceID img2img Dialog
# ═══════════════════════════════════════════════════════════════════════════

class FaceIDDialog(Gtk.Dialog):
    """IPAdapter FaceID — regenerate image preserving face identity from a reference."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - IPAdapter FaceID img2img")
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(self)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Branded header
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

        # Server
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Server:"))
        self.server_entry = Gtk.Entry(text=server_url, hexpand=True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        row.append(self.server_entry)
        box.append(row)

        # Model preset
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Model Preset:"))
        self.preset_combo = Gtk.ComboBoxText()
        self.preset_combo.set_tooltip_text("Base checkpoint model for generation.\nSD1.5 and SDXL are supported depending on the FaceID type.")
        for key in FACEID_PRESETS:
            self.preset_combo.append(key, key)
        self.preset_combo.set_active(0)
        self.preset_combo.set_hexpand(True)
        row.append(self.preset_combo)
        box.append(row)

        # FaceID preset
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="FaceID Type:"))
        self.faceid_combo = Gtk.ComboBoxText()
        self.faceid_combo.set_tooltip_text("FaceID variant to use. FACEID PLUS V2 is recommended for most cases.\nPORTRAIT modes give stronger face transfer. Some are model-specific.")
        for p in ["FACEID", "FACEID PLUS - SD1.5 only", "FACEID PLUS V2",
                   "FACEID PORTRAIT (style transfer)", "FACEID PORTRAIT UNNORM - SDXL only (strong)"]:
            self.faceid_combo.append(p, p)
        self.faceid_combo.set_active_id("FACEID PLUS V2")
        self.faceid_combo.set_hexpand(True)
        row.append(self.faceid_combo)
        box.append(row)

        # Source face image
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Face Reference:"))
        self.source_chooser = Gtk.FileChooserButton(title="Select face reference image")
        self.source_chooser.set_tooltip_text("Select a photo of the face you want to preserve in the generated image.\nUse a clear, front-facing photo for best results.")
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_mime_type("image/png")
        ff.add_mime_type("image/jpeg")
        ff.add_pattern("*.png")
        ff.add_pattern("*.jpg")
        ff.add_pattern("*.jpeg")
        self.source_chooser.add_filter(ff)
        self.source_chooser.set_hexpand(True)
        row.append(self.source_chooser)
        box.append(row)

        # Prompt
        box.append(Gtk.Label(label="Prompt:", xalign=0))
        self.prompt_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_size_request(-1, 60)
        self.prompt_tv.set_tooltip_text("Describe the scene around the face. The face identity comes from the reference image.\nExample: 'elegant portrait, studio lighting, professional photo'")
        sw = Gtk.ScrolledWindow(child=self.prompt_tv, vexpand=False)
        sw.set_min_content_height(60)
        box.append(sw)

        # Negative
        box.append(Gtk.Label(label="Negative:", xalign=0))
        self.neg_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.neg_tv.set_size_request(-1, 40)
        self.neg_tv.set_tooltip_text("Describe what you do NOT want (e.g. 'blurry, distorted').")
        sw2 = Gtk.ScrolledWindow(child=self.neg_tv, vexpand=False)
        sw2.set_min_content_height(40)
        box.append(sw2)
        self.neg_tv.get_buffer().set_text("blurry, deformed, bad anatomy, disfigured")

        # Spinners grid
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        r = 0
        grid.attach(Gtk.Label(label="Weight:", xalign=1), 0, r, 1, 1)
        self.weight_spin = Gtk.SpinButton.new_with_range(0.0, 3.0, 0.05)
        self.weight_spin.set_value(0.85)
        self.weight_spin.set_digits(2)
        self.weight_spin.set_tooltip_text("IPAdapter weight: how strongly the face identity influences the result.\nDefault: 0.85. Higher = stronger face resemblance.")
        grid.attach(self.weight_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Weight V2:", xalign=1), 2, r, 1, 1)
        self.weight_v2_spin = Gtk.SpinButton.new_with_range(0.0, 5.0, 0.05)
        self.weight_v2_spin.set_value(1.0)
        self.weight_v2_spin.set_digits(2)
        self.weight_v2_spin.set_tooltip_text("Secondary weight for FaceID Plus V2 variant.\nDefault: 1.0. Increase for stronger identity preservation.")
        grid.attach(self.weight_v2_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="LoRA Str:", xalign=1), 0, r, 1, 1)
        self.lora_str_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.lora_str_spin.set_value(0.6)
        self.lora_str_spin.set_digits(2)
        self.lora_str_spin.set_tooltip_text("Strength of the FaceID LoRA. Default: 0.6.\nHigher = more face influence but may reduce image quality.")
        grid.attach(self.lora_str_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Denoise:", xalign=1), 2, r, 1, 1)
        self.denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
        self.denoise_spin.set_value(0.55)
        self.denoise_spin.set_digits(2)
        self.denoise_spin.set_tooltip_text("How much to change the original image.\n0.3 = subtle, 0.55 = balanced (default), 0.8 = major rework.")
        grid.attach(self.denoise_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, r, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.steps_spin.set_value(25)
        self.steps_spin.set_tooltip_text("Generation steps. Default: 25. More = slower but cleaner.")
        grid.attach(self.steps_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="CFG:", xalign=1), 2, r, 1, 1)
        self.cfg_spin = Gtk.SpinButton.new_with_range(1.0, 30.0, 0.5)
        self.cfg_spin.set_value(7.0)
        self.cfg_spin.set_digits(1)
        self.cfg_spin.set_tooltip_text("CFG Scale: prompt adherence. Default: 7.0.\n3-7 is typical. Higher = more literal prompt following.")
        grid.attach(self.cfg_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="Seed:", xalign=1), 0, r, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        self.seed_spin.set_value(-1)
        self.seed_spin.set_tooltip_text("-1 = random")
        grid.attach(self.seed_spin, 1, r, 1, 1)

        box.append(grid)

        # ── User saved presets ──────────────────────────────────────────
        _add_preset_ui(self, box, "faceid")

        # Runs spinner
        _add_runs_spinner(self, box)

        self.show()

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _collect_user_preset(self):
        """Collect current widget values into a dict for preset storage."""
        source_path = None
        f = self.source_chooser.get_file()
        if f:
            source_path = f.get_path()
        return {
            "preset_key": self.preset_combo.get_active_id(),
            "faceid_preset": self.faceid_combo.get_active_id() or "FACEID PLUS V2",
            "source_path": source_path,
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "weight": self.weight_spin.get_value(),
            "weight_v2": self.weight_v2_spin.get_value(),
            "lora_strength": self.lora_str_spin.get_value(),
            "denoise": self.denoise_spin.get_value(),
            "steps": int(self.steps_spin.get_value()),
            "cfg": self.cfg_spin.get_value(),
            "seed": int(self.seed_spin.get_value()),
            "runs": int(self._runs_spin.get_value()),
        }

    def _apply_user_preset(self, p):
        """Restore widget values from a preset dict."""
        if "preset_key" in p:
            self.preset_combo.set_active_id(p["preset_key"])
        if "faceid_preset" in p:
            self.faceid_combo.set_active_id(p["faceid_preset"])
        if p.get("source_path"):
            try:
                self.source_chooser.set_filename(p["source_path"])
            except Exception:
                pass
        self.prompt_tv.get_buffer().set_text(p.get("prompt", ""))
        self.neg_tv.get_buffer().set_text(p.get("negative", ""))
        self.weight_spin.set_value(p.get("weight", 0.85))
        self.weight_v2_spin.set_value(p.get("weight_v2", 1.0))
        self.lora_str_spin.set_value(p.get("lora_strength", 0.6))
        self.denoise_spin.set_value(p.get("denoise", 0.55))
        self.steps_spin.set_value(p.get("steps", 25))
        self.cfg_spin.set_value(p.get("cfg", 7.0))
        self.seed_spin.set_value(p.get("seed", -1))
        if "runs" in p:
            self._runs_spin.set_value(p["runs"])

    def get_values(self):
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        source_path = None
        f = self.source_chooser.get_file()
        if f:
            source_path = f.get_path()
        return {
            "server": self.server_entry.get_text().strip(),
            "preset_key": self.preset_combo.get_active_id(),
            "faceid_preset": self.faceid_combo.get_active_id() or "FACEID PLUS V2",
            "source_path": source_path,
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "weight": self.weight_spin.get_value(),
            "weight_v2": self.weight_v2_spin.get_value(),
            "lora_strength": self.lora_str_spin.get_value(),
            "denoise": self.denoise_spin.get_value(),
            "steps": int(self.steps_spin.get_value()),
            "cfg": self.cfg_spin.get_value(),
            "seed": seed,
            "runs": int(self._runs_spin.get_value()),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  PuLID Flux Face Identity Dialog
# ═══════════════════════════════════════════════════════════════════════════

class PulidFluxDialog(Gtk.Dialog):
    """PuLID Flux — generate image preserving face identity with Flux model."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - PuLID Flux Face Identity")
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(self)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Branded header
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

        # Server
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Server:"))
        self.server_entry = Gtk.Entry(text=server_url, hexpand=True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        row.append(self.server_entry)
        box.append(row)

        # Flux model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Flux Model:"))
        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.set_tooltip_text("Flux checkpoint model for generation.\nRequires a Flux-compatible model file on the server.")
        for m in PULID_FLUX_MODELS:
            label = m.split("/")[-1] if "/" in m else m
            self.model_combo.append(m, label)
        self.model_combo.set_active(0)
        self.model_combo.set_hexpand(True)
        row.append(self.model_combo)
        box.append(row)

        # Face reference image
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Face Reference:"))
        self.source_chooser = Gtk.FileChooserButton(title="Select face reference image")
        self.source_chooser.set_tooltip_text("Select a clear, front-facing photo of the face to preserve.\nThe face identity will be transferred into the generated image.")
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_mime_type("image/png")
        ff.add_mime_type("image/jpeg")
        ff.add_pattern("*.png")
        ff.add_pattern("*.jpg")
        ff.add_pattern("*.jpeg")
        self.source_chooser.add_filter(ff)
        self.source_chooser.set_hexpand(True)
        row.append(self.source_chooser)
        box.append(row)

        # Prompt
        box.append(Gtk.Label(label="Prompt:", xalign=0))
        self.prompt_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_size_request(-1, 60)
        self.prompt_tv.set_tooltip_text("Describe the scene. The face comes from the reference image.\nExample: 'portrait photo, natural lighting, smiling'")
        sw = Gtk.ScrolledWindow(child=self.prompt_tv, vexpand=False)
        sw.set_min_content_height(60)
        box.append(sw)

        # Spinners
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        r = 0
        grid.attach(Gtk.Label(label="Strength:", xalign=1), 0, r, 1, 1)
        self.strength_spin = Gtk.SpinButton.new_with_range(0.0, 2.0, 0.05)
        self.strength_spin.set_value(0.9)
        self.strength_spin.set_digits(2)
        self.strength_spin.set_tooltip_text("PuLID face identity strength. Default: 0.9.\nHigher = stronger face resemblance, lower = more creative freedom.")
        grid.attach(self.strength_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Denoise:", xalign=1), 2, r, 1, 1)
        self.denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
        self.denoise_spin.set_value(0.65)
        self.denoise_spin.set_digits(2)
        self.denoise_spin.set_tooltip_text("How much to change the original image.\n0.3 = subtle, 0.65 = balanced (default), 1.0 = full regeneration.")
        grid.attach(self.denoise_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, r, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.steps_spin.set_value(20)
        self.steps_spin.set_tooltip_text("Generation steps. Default: 20. More = slower but cleaner.")
        grid.attach(self.steps_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Guidance:", xalign=1), 2, r, 1, 1)
        self.guidance_spin = Gtk.SpinButton.new_with_range(1.0, 30.0, 0.5)
        self.guidance_spin.set_value(1.0)
        self.guidance_spin.set_digits(1)
        self.guidance_spin.set_tooltip_text("Flux guidance scale. Default: 1.0 for Flux models.\nUnlike SDXL, Flux typically works best with low guidance values.")
        grid.attach(self.guidance_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="Seed:", xalign=1), 0, r, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        self.seed_spin.set_value(-1)
        self.seed_spin.set_tooltip_text("-1 = random")
        grid.attach(self.seed_spin, 1, r, 1, 1)

        box.append(grid)

        # ── User saved presets ──────────────────────────────────────────
        _add_preset_ui(self, box, "pulid_flux")

        # Runs spinner
        _add_runs_spinner(self, box)

        self.show()

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _collect_user_preset(self):
        """Collect current widget values into a dict for preset storage."""
        source_path = None
        f = self.source_chooser.get_file()
        if f:
            source_path = f.get_path()
        return {
            "flux_model": self.model_combo.get_active_id(),
            "source_path": source_path,
            "prompt": self._buf_text(self.prompt_tv),
            "strength": self.strength_spin.get_value(),
            "denoise": self.denoise_spin.get_value(),
            "steps": int(self.steps_spin.get_value()),
            "guidance": self.guidance_spin.get_value(),
            "seed": int(self.seed_spin.get_value()),
            "runs": int(self._runs_spin.get_value()),
        }

    def _apply_user_preset(self, p):
        """Restore widget values from a preset dict."""
        if "flux_model" in p:
            self.model_combo.set_active_id(p["flux_model"])
        if p.get("source_path"):
            try:
                self.source_chooser.set_filename(p["source_path"])
            except Exception:
                pass
        self.prompt_tv.get_buffer().set_text(p.get("prompt", ""))
        self.strength_spin.set_value(p.get("strength", 0.9))
        self.denoise_spin.set_value(p.get("denoise", 0.65))
        self.steps_spin.set_value(p.get("steps", 20))
        self.guidance_spin.set_value(p.get("guidance", 1.0))
        self.seed_spin.set_value(p.get("seed", -1))
        if "runs" in p:
            self._runs_spin.set_value(p["runs"])

    def get_values(self):
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        source_path = None
        f = self.source_chooser.get_file()
        if f:
            source_path = f.get_path()
        return {
            "server": self.server_entry.get_text().strip(),
            "flux_model": self.model_combo.get_active_id(),
            "source_path": source_path,
            "prompt": self._buf_text(self.prompt_tv),
            "strength": self.strength_spin.get_value(),
            "denoise": self.denoise_spin.get_value(),
            "steps": int(self.steps_spin.get_value()),
            "guidance": self.guidance_spin.get_value(),
            "seed": seed,
            "runs": int(self._runs_spin.get_value()),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Klein img2img Dialog
# ═══════════════════════════════════════════════════════════════════════════

class KleinDialog(Gtk.Dialog):
    """Klein img2img editor dialog. Optionally with reference image."""

    def __init__(self, title, with_reference=False, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title=title)
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(self)
        self.with_reference = with_reference

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Branded header
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Klein model selector
        box.pack_start(Gtk.Label(label="Klein Model:", xalign=0), False, False, 0)
        self.klein_combo = Gtk.ComboBoxText()
        self.klein_combo.set_tooltip_text("Flux 2 Klein model variant.\nKlein models specialize in image editing and enhancement.")
        for key in KLEIN_MODELS:
            self.klein_combo.append(key, key)
        self.klein_combo.set_active(0)
        box.pack_start(self.klein_combo, False, False, 0)

        # Prompt
        box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        self.prompt_tv = Gtk.TextView()
        self.prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_tooltip_text("Describe the desired edit or output.\nBe specific about what you want changed in the image.")
        sw = Gtk.ScrolledWindow(); sw.set_min_content_height(60); sw.add(self.prompt_tv)
        box.pack_start(sw, False, False, 0)

        # Reference image (only for ref mode)
        if with_reference:
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
            box.pack_start(Gtk.Label(label="Reference Image (for structure):", xalign=0), False, False, 0)
            self.ref_chooser = Gtk.FileChooserButton(title="Select reference image")
            self.ref_chooser.set_tooltip_text("Select a reference image whose structure/composition Klein will follow.\nThe AI will use this as a visual guide for layout and form.")
            self.ref_chooser.set_action(Gtk.FileChooserAction.OPEN)
            ff = Gtk.FileFilter(); ff.set_name("Images")
            ff.add_pattern("*.png"); ff.add_pattern("*.jpg"); ff.add_pattern("*.jpeg")
            ff.add_pattern("*.webp"); ff.add_pattern("*.bmp")
            self.ref_chooser.add_filter(ff)
            box.pack_start(self.ref_chooser, False, False, 0)
        else:
            self.ref_chooser = None

        # Parameters
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        r = 0

        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, r, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.steps_spin.set_value(KLEIN_DEFAULTS["steps"])
        self.steps_spin.set_tooltip_text("Generation steps. More = slower but cleaner output.")
        grid.attach(self.steps_spin, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Denoise:", xalign=1), 2, r, 1, 1)
        self.denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
        self.denoise_spin.set_digits(2)
        self.denoise_spin.set_value(KLEIN_DEFAULTS["denoise"])
        self.denoise_spin.set_tooltip_text("How much to change the original image.\nLower = subtle edit, higher = major transformation.")
        grid.attach(self.denoise_spin, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Guidance:", xalign=1), 0, r, 1, 1)
        self.guidance_spin = Gtk.SpinButton.new_with_range(0.0, 30.0, 0.5)
        self.guidance_spin.set_digits(1)
        self.guidance_spin.set_value(KLEIN_DEFAULTS["guidance"])
        self.guidance_spin.set_tooltip_text("Guidance scale: how closely to follow the prompt.\nFlux models typically use low values (1.0-4.0).")
        grid.attach(self.guidance_spin, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Seed (-1=rand):", xalign=1), 2, r, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**31, 1)
        self.seed_spin.set_value(-1)
        self.seed_spin.set_tooltip_text("-1 = random seed each time.\nSet a specific number to reproduce the exact same result.")
        grid.attach(self.seed_spin, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Enhancer Mag:", xalign=1), 0, r, 1, 1)
        self.enh_mag = Gtk.SpinButton.new_with_range(0.0, 10.0, 0.1)
        self.enh_mag.set_digits(1)
        self.enh_mag.set_value(KLEIN_DEFAULTS["enhancer_magnitude"])
        self.enh_mag.set_tooltip_text("Klein enhancer magnitude: boosts detail/sharpness.\n0 = no enhancement. Higher adds more AI-generated detail.")
        grid.attach(self.enh_mag, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Enh. Contrast:", xalign=1), 2, r, 1, 1)
        self.enh_contrast = Gtk.SpinButton.new_with_range(-1.0, 10.0, 0.1)
        self.enh_contrast.set_digits(1)
        self.enh_contrast.set_value(KLEIN_DEFAULTS["enhancer_contrast"])
        self.enh_contrast.set_tooltip_text("Klein enhancer contrast boost.\nNegative = flatten contrast, positive = increase contrast.")
        grid.attach(self.enh_contrast, 3, r, 1, 1)
        r += 1

        if with_reference:
            grid.attach(Gtk.Label(label="Ref Strength:", xalign=1), 0, r, 1, 1)
            self.ref_strength = Gtk.SpinButton.new_with_range(0.0, 5.0, 0.05)
            self.ref_strength.set_digits(2)
            self.ref_strength.set_value(1.0)
            self.ref_strength.set_tooltip_text("How strongly the reference image guides the output.\n1.0 = normal influence. Higher = follow reference more closely.")
            grid.attach(self.ref_strength, 1, r, 1, 1)

            grid.attach(Gtk.Label(label="Text/Ref Balance:", xalign=1), 2, r, 1, 1)
            self.text_ref_bal = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
            self.text_ref_bal.set_digits(2)
            self.text_ref_bal.set_value(KLEIN_DEFAULTS["text_ref_balance"])
            self.text_ref_bal.set_tooltip_text("Balance between text prompt and reference image.\n0.0 = fully reference-guided, 1.0 = fully text-guided, 0.5 = balanced.")
            grid.attach(self.text_ref_bal, 3, r, 1, 1)
            r += 1
        else:
            self.ref_strength = None
            self.text_ref_bal = None

        box.pack_start(grid, False, False, 0)

        # LoRA section
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        lora_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lora_hdr.pack_start(Gtk.Label(label="LoRA (fed to Klein Analyzer):", xalign=0), False, False, 0)
        self._lora_fetch_btn = Gtk.Button(label="Fetch LoRAs")
        self._lora_fetch_btn.set_tooltip_text("Download available Klein-compatible LoRAs from the server.")
        self._lora_fetch_btn.connect("clicked", self._on_fetch_loras)
        lora_hdr.pack_end(self._lora_fetch_btn, False, False, 0)
        box.pack_start(lora_hdr, False, False, 0)

        self._all_lora_names = []
        self._lora_names = []
        self.lora_combo = Gtk.ComboBoxText()
        self.lora_combo.append("none", "(none)")
        self.lora_combo.set_active(0)
        self.lora_combo.set_tooltip_text("Optional LoRA to influence the Klein model's output style.\nLeave as (none) for default behavior.")
        box.pack_start(self.lora_combo, False, False, 0)

        lora_str_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lora_str_box.pack_start(Gtk.Label(label="LoRA Strength:"), False, False, 0)
        self.lora_str_spin = Gtk.SpinButton.new_with_range(-5.0, 5.0, 0.05)
        self.lora_str_spin.set_digits(2); self.lora_str_spin.set_value(1.0)
        self.lora_str_spin.set_tooltip_text("LoRA strength. 1.0 = full effect.\nLower for subtlety, negative values for inverse effect.")
        lora_str_box.pack_start(self.lora_str_spin, False, False, 0)
        box.pack_start(lora_str_box, False, False, 0)

        # ── User saved presets ──────────────────────────────────────────
        _add_preset_ui(self, box, "klein")

        # Runs spinner
        _add_runs_spinner(self, box)

        box.show_all()
        GLib.idle_add(self._on_fetch_loras, None)

    def _on_fetch_loras(self, _btn):
        server = self.server_entry.get_text().strip(); _propagate_server_url(server)
        try:
            self._all_lora_names = _fetch_loras(server)
        except Exception:
            self._all_lora_names = []
        # Klein only shows Flux-2-Klein compatible LoRAs
        self._lora_names = _filter_loras_for_arch(self._all_lora_names, "flux2klein")
        self.lora_combo.remove_all()
        self.lora_combo.append("none", "(none)")
        for lname in self._lora_names:
            short = lname.rsplit("/", 1)[-1] if "/" in lname else lname
            self.lora_combo.append(lname, short)
        self.lora_combo.set_active(0)
        total = len(self._all_lora_names)
        shown = len(self._lora_names)
        self._lora_fetch_btn.set_label(f"{shown}/{total} Klein LoRAs")

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _collect_user_preset(self):
        """Collect current widget values into a dict for preset storage."""
        return {
            "klein_model": self.klein_combo.get_active_id(),
            "prompt": self._buf_text(self.prompt_tv),
            "seed": int(self.seed_spin.get_value()),
            "steps": int(self.steps_spin.get_value()),
            "denoise": self.denoise_spin.get_value(),
            "guidance": self.guidance_spin.get_value(),
            "enhancer_mag": self.enh_mag.get_value(),
            "enhancer_contrast": self.enh_contrast.get_value(),
            "runs": int(self._runs_spin.get_value()),
        }

    def _apply_user_preset(self, p):
        """Restore widget values from a preset dict."""
        if "klein_model" in p:
            self.klein_combo.set_active_id(p["klein_model"])
        self.prompt_tv.get_buffer().set_text(p.get("prompt", ""))
        self.seed_spin.set_value(p.get("seed", -1))
        self.steps_spin.set_value(p.get("steps", KLEIN_DEFAULTS["steps"]))
        self.denoise_spin.set_value(p.get("denoise", KLEIN_DEFAULTS["denoise"]))
        self.guidance_spin.set_value(p.get("guidance", KLEIN_DEFAULTS["guidance"]))
        self.enh_mag.set_value(p.get("enhancer_mag", KLEIN_DEFAULTS["enhancer_magnitude"]))
        self.enh_contrast.set_value(p.get("enhancer_contrast", KLEIN_DEFAULTS["enhancer_contrast"]))
        if "runs" in p:
            self._runs_spin.set_value(p["runs"])

    def get_values(self):
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        lora_id = self.lora_combo.get_active_id()
        lora_name = lora_id if lora_id and lora_id != "none" else None
        vals = {
            "server": self.server_entry.get_text().strip(),
            "klein_model": self.klein_combo.get_active_id() or list(KLEIN_MODELS.keys())[0],
            "prompt": self._buf_text(self.prompt_tv),
            "seed": seed,
            "steps": int(self.steps_spin.get_value()),
            "denoise": self.denoise_spin.get_value(),
            "guidance": self.guidance_spin.get_value(),
            "enhancer_mag": self.enh_mag.get_value(),
            "enhancer_contrast": self.enh_contrast.get_value(),
            "lora_name": lora_name,
            "lora_strength": self.lora_str_spin.get_value(),
            "runs": int(self._runs_spin.get_value()),
        }
        if self.with_reference:
            vals["ref_file"] = self.ref_chooser.get_filename() if self.ref_chooser else None
            vals["ref_strength"] = self.ref_strength.get_value() if self.ref_strength else 1.0
            vals["text_ref_balance"] = self.text_ref_bal.get_value() if self.text_ref_bal else 0.5
        return vals


# ═══════════════════════════════════════════════════════════════════════════
#  GIMP 3 Plug-In class — registers all Spellcaster menu entries
# ═══════════════════════════════════════════════════════════════════════════
# GIMP 3 plugins must subclass Gimp.PlugIn and implement three methods:
#   do_set_i18n()         — return False to disable gettext translation
#   do_query_procedures() — return list of procedure name strings
#   do_create_procedure() — create a GimpImageProcedure for each name
#
# Each procedure gets a menu entry under Filters > Spellcaster and a
# callback method (_run_*) that handles the full lifecycle:
#   1. Show GTK dialog → 2. Export image → 3. Upload to server →
#   4. Build workflow → 5. Execute → 6. Import result as new layer
#
# All _run_* callbacks follow the GIMP 3 ImageProcedure signature:
#   (procedure, run_mode, image, drawables, config, data) → Gimp.ValueArray

class Spellcaster(Gimp.PlugIn):

    def do_set_i18n(self, name):
        """Disable internationalization (i18n) — plugin uses English only."""
        return False

    def do_query_procedures(self):
        """Return the list of PDB procedure names this plugin provides.

        Each name here must have a corresponding entry in do_create_procedure().
        """
        return [
            "spellcaster-img2img", "spellcaster-txt2img", "spellcaster-inpaint", "spellcaster-send-image",
            "spellcaster-faceswap", "spellcaster-faceswap-model",
            "spellcaster-faceswap-mtb", "spellcaster-faceid-img2img", "spellcaster-pulid-flux",
            "spellcaster-klein-img2img", "spellcaster-klein-img2img-ref",
            "spellcaster-wan-i2v", "spellcaster-rembg",
            "spellcaster-embed-watermark", "spellcaster-read-watermark",
            "spellcaster-upscale", "spellcaster-lama-remove",
            "spellcaster-lut", "spellcaster-outpaint", "spellcaster-style-transfer",
            "spellcaster-face-restore", "spellcaster-photo-restore",
            "spellcaster-detail-hallucinate", "spellcaster-colorize",
            "spellcaster-batch-variations",
            "spellcaster-iclight", "spellcaster-supir",
            "spellcaster-seedv2r",
            "spellcaster-settings",
        ]

    def do_create_procedure(self, name):
        menu_map = {
            "spellcaster-img2img": ("Image to Image (presets)...", self._run_img2img,
                                    "Send canvas to ComfyUI with per-model presets"),
            "spellcaster-txt2img": ("Text to Image (presets)...", self._run_txt2img,
                                    "Generate from text with per-model presets"),
            "spellcaster-inpaint": ("Inpaint Selection (presets)...", self._run_inpaint,
                                    "Inpaint selection area with per-model presets"),
            "spellcaster-send-image": ("Upload Image to Server", self._run_send,
                                       "Upload canvas to ComfyUI input folder"),
            "spellcaster-faceswap": ("Face Swap (ReActor)...", self._run_faceswap,
                                     "Swap face on canvas using a source face image"),
            "spellcaster-faceswap-model": ("Face Swap (Saved Face Model)...", self._run_faceswap_model,
                                           "Swap face using a saved face model from the server"),
            "spellcaster-faceswap-mtb": ("Face Swap (mtb)...", self._run_faceswap_mtb,
                                         "Direct face swap using mtb facetools"),
            "spellcaster-faceid-img2img": ("FaceID img2img (IPAdapter)...", self._run_faceid,
                                           "Regenerate image preserving face identity with IPAdapter FaceID"),
            "spellcaster-pulid-flux": ("PuLID Flux Face Identity...", self._run_pulid_flux,
                                       "Generate with Flux preserving face identity via PuLID"),
            "spellcaster-klein-img2img": ("Klein Image Editor...", self._run_klein,
                                          "Edit image with Flux 2 Klein model"),
            "spellcaster-rembg": ("Remove Background...", self._run_rembg,
                                   "Remove image background using AI (transparent PNG)"),
            "spellcaster-embed-watermark": ("Embed Invisible Watermark...", self._run_embed_watermark,
                                             "Hide encrypted metadata inside image pixels (LSB steganography)"),
            "spellcaster-read-watermark": ("Read Invisible Watermark...", self._run_read_watermark,
                                            "Extract hidden metadata from a watermarked image"),
            "spellcaster-klein-img2img-ref": ("Klein Image Editor + Reference...", self._run_klein_ref,
                                              "Edit image with Flux 2 Klein using a reference image"),
            "spellcaster-wan-i2v": ("Wan 2.2 Image to Video...", self._run_wan_i2v,
                                    "Generate video from image using Wan 2.2"),
"spellcaster-upscale": ("Upscale 4x...", self._run_upscale,
                                     "Upscale image using super-resolution model"),
            "spellcaster-lama-remove": ("Object Removal (LaMa)...", self._run_lama_remove,
                                         "Remove selected objects using LaMa inpainting"),
            "spellcaster-lut": ("Color Grading (LUT)...", self._run_lut,
                                 "Apply cinematic color LUT to image"),
            "spellcaster-outpaint": ("Outpaint / Extend Canvas...", self._run_outpaint,
                                      "Extend canvas by AI-generating new content at edges"),
            "spellcaster-style-transfer": ("Style Transfer (IPAdapter)...", self._run_style_transfer,
                                            "Apply style from a reference image using IPAdapter"),
            "spellcaster-face-restore": ("Face Restore...", self._run_face_restore,
                                          "Restore and enhance faces using AI models"),
            "spellcaster-photo-restore": ("Photo Restoration Pipeline...", self._run_photo_restore,
                                           "Full restoration: upscale + face restore + sharpen"),
            "spellcaster-detail-hallucinate": ("Detail Hallucination...", self._run_detail_hallucinate,
                                                "Upscale + low-denoise img2img to add AI detail"),
            "spellcaster-colorize": ("Colorize B&W Photo...", self._run_colorize,
                                      "Add color to black and white photos using ControlNet"),
            "spellcaster-batch-variations": ("Batch Variations (txt2img)...", self._run_batch_variations,
                                              "Generate multiple txt2img variations in one batch"),
            "spellcaster-iclight": ("IC-Light Relighting...", self._run_iclight,
                                     "Change lighting direction on any photo using IC-Light"),
            "spellcaster-supir": ("SUPIR AI Restoration...", self._run_supir,
                                   "Restore and enhance images using SUPIR AI model"),
            "spellcaster-seedv2r": ("SeedV2R Upscale...", self._run_seedv2r,
                                     "Upscale with AI detail hallucination and scale control"),
            "spellcaster-settings": ("Settings...", self._run_settings,
                                      "Configure Spellcaster: server URL, defaults, and preferences"),
        }
        label, callback, doc = menu_map[name]
        # ImageProcedure.new binds a Python callback to a GIMP procedure.
        # The callback receives (procedure, run_mode, image, drawables, config, data).
        proc = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, callback, None)
        proc.set_menu_label(label)
        # "<Image>/Filters/Spellcaster" places all entries under Filters > Spellcaster menu
        proc.add_menu_path("<Image>/Filters/Spellcaster")
        proc.set_documentation(doc, doc, name)
        proc.set_attribution("Spellcaster", "Spellcaster", "2026")
        proc.set_image_types("*")   # accept all image types (RGB, GRAY, INDEXED, with/without alpha)
        return proc

    # ── Procedure callbacks ──────────────────────────────────────────────
    # Each follows the same pattern: guard for INTERACTIVE mode → init GimpUi →
    # show dialog → export canvas → upload → build workflow → execute →
    # import results as layers → flush displays.

    def _run_img2img(self, procedure, run_mode, image, drawables, config, data):
        """Image-to-image: send current canvas through a model preset."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = PresetDialog("Spellcaster — Image to Image", mode="img2img")
        dlg.w_spin.set_value(image.get_width())
        dlg.h_spin.set_value(image.get_height())
        last = _SESSION.get("img2img")
        if last:
            last_no_dims = {k: v for k, v in last.items() if k not in ("width", "height")}
            dlg._apply_session(last_no_dims)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["img2img"] = dlg._collect_session()
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            Gimp.progress_init("img2img: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                     _build_img2img(uname, v["preset"], v["prompt"], v["negative"], seed,
                                    v.get("loras"), controlnet=v.get("controlnet"))
                label = f"img2img run {run_i+1}/{runs}" if runs > 1 else "img2img"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"{v['preset'].get('label','')} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"{v['preset'].get('label','')} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster img2img Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_txt2img(self, procedure, run_mode, image, drawables, config, data):
        """Text-to-image: generate from prompt only (no input image)."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = PresetDialog("Spellcaster — Text to Image", mode="txt2img")
        dlg.w_spin.set_value(image.get_width())
        dlg.h_spin.set_value(image.get_height())
        last = _SESSION.get("txt2img")
        if last:
            dlg._apply_session(last)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["txt2img"] = dlg._collect_session()
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            Gimp.progress_init("txt2img: generating on ComfyUI...")
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                     _build_txt2img(v["preset"], v["prompt"], v["negative"], seed, v.get("loras"))
                label = f"txt2img run {run_i+1}/{runs}" if runs > 1 else "txt2img"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"{v['preset'].get('label','')} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"{v['preset'].get('label','')} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster txt2img Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_inpaint(self, procedure, run_mode, image, drawables, config, data):
        """Inpaint: regenerate only the selected area using a mask from GIMP's selection."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        dlg = PresetDialog("Spellcaster — Inpaint Selection", mode="inpaint")
        # Working resolution for the sampler — full image dims, NOT selection dims.
        # The mask controls which area gets inpainted; ImageScale handles resolution.
        dlg.w_spin.set_value(image.get_width()); dlg.h_spin.set_value(image.get_height())
        last = _SESSION.get("inpaint")
        if last:
            last_no_dims = {k: v for k, v in last.items() if k not in ("width", "height")}
            dlg._apply_session(last_no_dims)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["inpaint"] = dlg._collect_session()
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            Gimp.progress_init("Building selection mask...")
            srv = v["server"]

            # Build mask from GIMP's actual selection channel (not just bounds)
            mtmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False); mtmp.close()
            _create_selection_mask_png(mtmp.name, image)

            Gimp.progress_set_text("Exporting image...")
            # Export current image
            tmp = _export_image_to_tmp(image)
            iname = f"gimp_inp_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, iname); os.unlink(tmp)

            mname = f"gimp_mask_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, mtmp.name, mname); os.unlink(mtmp.name)

            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                     _build_inpaint(iname, mname, v["preset"], v["prompt"], v["negative"], seed,
                                    v.get("loras"), controlnet=v.get("controlnet"))
                label = f"Inpaint run {run_i+1}/{runs}" if runs > 1 else "Inpaint"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Inpaint {v['preset'].get('label','')} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"Inpaint {v['preset'].get('label','')} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Inpaint Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceswap(self, procedure, run_mode, image, drawables, config, data):
        """Face swap via ReActor: paste a face from a source image onto the canvas."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = FaceSwapDialog()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v["face_file"]:
            Gimp.message("No source face image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("Face Swap: exporting images...")
            srv = v["server"]
            # Upload target (current canvas)
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_fstgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            # Upload source face
            src_name = f"gimp_fssrc_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["face_file"], src_name)

            # Optionally save the face model for future reuse
            if v.get("save_face_model") and v.get("save_model_name"):
                model_name = v["save_model_name"]
                overwrite = v.get("save_overwrite", True)
                Gimp.progress_set_text(f"Saving face model '{model_name}'...")
                save_wf = _build_save_face_model(src_name, model_name, overwrite=overwrite)
                _run_with_spinner(f"Saving face model '{model_name}'...",
                                  lambda: list(_run_comfyui_workflow(srv, save_wf)))
                Gimp.message(f"Face model '{model_name}' saved successfully.")

            # Build and run face swap workflow
            wf = _build_faceswap(
                tgt_name, src_name,
                swap_model=v["swap_model"],
                face_restore_model=v["face_restore_model"],
                face_restore_vis=v["face_restore_vis"],
                codeformer_weight=v["codeformer_weight"],
                detect_gender_input=v["detect_gender_input"],
                detect_gender_source=v["detect_gender_source"],
                input_face_idx=v["input_face_idx"],
                source_face_idx=v["source_face_idx"],
            )
            Gimp.progress_set_text("Face Swap: processing on ComfyUI...")
            results = _run_with_spinner("Face Swap: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"FaceSwap #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Face Swap Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceswap_model(self, procedure, run_mode, image, drawables, config, data):
        """Face swap using a saved face model from the server (no source image file)."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = FaceSwapModelDialog()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v["face_model"] or v["face_model"] == "none":
            Gimp.message("No face model selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("Face Swap (Model): exporting image...")
            srv = v["server"]
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_fsm_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            wf = _build_faceswap_model(
                tgt_name, v["face_model"],
                swap_model=v["swap_model"],
                face_restore_model=v["face_restore_model"],
                face_restore_vis=v["face_restore_vis"],
                codeformer_weight=v["codeformer_weight"],
                detect_gender_input=v["detect_gender_input"],
                detect_gender_source=v["detect_gender_source"],
                input_face_idx=v["input_face_idx"],
                source_face_idx=v["source_face_idx"],
            )
            Gimp.progress_set_text("Face Swap (Model): processing on ComfyUI...")
            results = _run_with_spinner("Face Swap (Model): processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"FaceSwap Model #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Face Swap (Model) Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_wan_i2v(self, procedure, run_mode, image, drawables, config, data):
        """Wan 2.2 image-to-video: generate video from canvas or selection."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        # Check for selection — if present, use selection region as start image
        has_sel, sx1, sy1, sx2, sy2 = _get_selection_bounds(image)

        dlg = WanI2VDialog()
        if has_sel:
            src_w, src_h = sx2 - sx1, sy2 - sy1
        else:
            src_w, src_h = image.get_width(), image.get_height()
        vw, vh = _wan_video_dims(src_w, src_h)
        dlg.w_spin.set_value(vw)
        dlg.h_spin.set_value(vh)
        last = _SESSION.get("wan_i2v")
        if last:
            dlg._apply_user_preset(last)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["wan_i2v"] = dlg._collect_user_preset()
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            if has_sel:
                Gimp.progress_init("Wan I2V: exporting selection region...")
                srv = v["server"]
                tmp, _sw, _sh = _export_selection_to_tmp(image)
            else:
                Gimp.progress_init("Wan I2V: exporting image...")
                srv = v["server"]
                tmp = _export_image_to_tmp(image)
            uname = f"gimp_wan_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            base_seed = v["seed"]
            src = "selection" if has_sel else "full image"
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_wan_i2v(
                    uname, v["preset_key"], v["prompt"], v["negative"], seed,
                    width=v["width"], height=v["height"], length=v["length"],
                    steps=v["steps"], cfg=v["cfg"], shift=v["shift"],
                    second_step=v["second_step"], loras=v["loras"],
                    upscale=v["upscale"], upscale_factor=v["upscale_factor"],
                    interpolate=v["interpolate"], pingpong=v["pingpong"],
                    fps=v["fps"],
                )
                label = f"Wan I2V run {run_i+1}/{runs}" if runs > 1 else "Wan I2V"
                results = _run_with_spinner(f"{label}: generating video from {src} on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Wan I2V run {run_i+1} frame #{i+1}" if runs > 1 else f"Wan I2V frame #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            Gimp.message("Video generation complete! Check ComfyUI output folder for the MP4 file.")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Wan I2V Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceswap_mtb(self, procedure, run_mode, image, drawables, config, data):
        """Face swap via mtb facetools: direct swap from source image."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = MtbFaceSwapDialog()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v["source_path"]:
            Gimp.message("No source face image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("Face Swap (mtb): exporting images...")
            srv = v["server"]
            # Export target (current canvas)
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_mtb_tgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            # Upload source face image
            src_name = f"gimp_mtb_src_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["source_path"], src_name)
            wf = _build_faceswap_mtb(tgt_name, src_name,
                                      analysis_model=v["analysis_model"],
                                      swap_model=v["swap_model"],
                                      faces_index=v["faces_index"])
            Gimp.progress_set_text("Face Swap (mtb): processing...")
            results = _run_with_spinner("Face Swap (mtb): processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"FaceSwap mtb #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Face Swap (mtb) Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceid(self, procedure, run_mode, image, drawables, config, data):
        """IPAdapter FaceID img2img: regenerate image preserving face identity."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = FaceIDDialog()
        last = _SESSION.get("faceid")
        if last:
            dlg._apply_user_preset(last)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["faceid"] = dlg._collect_user_preset()
        dlg.destroy()
        if not v["source_path"]:
            Gimp.message("No face reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        runs = v.get("runs", 1)
        try:
            Gimp.progress_init("FaceID: exporting images...")
            srv = v["server"]
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_fid_tgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            src_name = f"gimp_fid_ref_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["source_path"], src_name)
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_faceid_img2img(
                    tgt_name, src_name, v["preset_key"],
                    v["prompt"], v["negative"], seed,
                    faceid_preset=v["faceid_preset"],
                    lora_strength=v["lora_strength"],
                    weight=v["weight"], weight_v2=v["weight_v2"],
                    denoise=v["denoise"], steps=v["steps"], cfg=v["cfg"],
                )
                label = f"FaceID run {run_i+1}/{runs}" if runs > 1 else "FaceID"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"FaceID {v['preset_key']} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"FaceID {v['preset_key']} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster FaceID Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_pulid_flux(self, procedure, run_mode, image, drawables, config, data):
        """PuLID Flux: generate with Flux model while preserving face identity."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = PulidFluxDialog()
        last = _SESSION.get("pulid_flux")
        if last:
            dlg._apply_user_preset(last)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["pulid_flux"] = dlg._collect_user_preset()
        dlg.destroy()
        if not v["source_path"]:
            Gimp.message("No face reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        runs = v.get("runs", 1)
        try:
            Gimp.progress_init("PuLID Flux: exporting images...")
            srv = v["server"]
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_pulid_tgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            src_name = f"gimp_pulid_ref_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["source_path"], src_name)
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_pulid_flux(
                    tgt_name, src_name,
                    v["prompt"], "",
                    seed,
                    flux_model=v["flux_model"],
                    strength=v["strength"],
                    steps=v["steps"],
                    guidance=v["guidance"],
                    denoise=v["denoise"],
                )
                label = f"PuLID Flux run {run_i+1}/{runs}" if runs > 1 else "PuLID Flux"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"PuLID Flux run {run_i+1} #{i+1}" if runs > 1 else f"PuLID Flux #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster PuLID Flux Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_klein(self, procedure, run_mode, image, drawables, config, data):
        """Klein img2img: edit image with Flux 2 Klein distilled model."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = KleinDialog("Spellcaster — Klein Image Editor", with_reference=False)
        last = _SESSION.get("klein")
        if last:
            dlg._apply_user_preset(last)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["klein"] = dlg._collect_user_preset()
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            Gimp.progress_init("Klein: exporting image...")
            srv = v["server"]
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_klein_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_klein_img2img(
                    uname, v["klein_model"], v["prompt"], seed,
                    steps=v["steps"], denoise=v["denoise"], guidance=v["guidance"],
                    enhancer_mag=v["enhancer_mag"], enhancer_contrast=v["enhancer_contrast"],
                    lora_name=v["lora_name"], lora_strength=v["lora_strength"],
                )
                label = f"Klein run {run_i+1}/{runs}" if runs > 1 else "Klein"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Klein {v['klein_model']} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"Klein {v['klein_model']} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Klein Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_klein_ref(self, procedure, run_mode, image, drawables, config, data):
        """Klein img2img + reference: edit image with a structure/style reference."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = KleinDialog("Spellcaster — Klein Editor + Reference", with_reference=True)
        last = _SESSION.get("klein_ref")
        if last:
            dlg._apply_user_preset(last)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["klein_ref"] = dlg._collect_user_preset()
        dlg.destroy()
        if not v.get("ref_file"):
            Gimp.message("No reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        runs = v.get("runs", 1)
        try:
            Gimp.progress_init("Klein+Ref: exporting images...")
            srv = v["server"]
            # Upload main image
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_kleinm_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            # Upload reference image
            ref_name = f"gimp_kleinr_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["ref_file"], ref_name)
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_klein_img2img_ref(
                    uname, ref_name, v["klein_model"], v["prompt"], seed,
                    steps=v["steps"], denoise=v["denoise"], guidance=v["guidance"],
                    enhancer_mag=v["enhancer_mag"], enhancer_contrast=v["enhancer_contrast"],
                    ref_strength=v["ref_strength"], text_ref_balance=v["text_ref_balance"],
                    lora_name=v["lora_name"], lora_strength=v["lora_strength"],
                )
                label = f"Klein+Ref run {run_i+1}/{runs}" if runs > 1 else "Klein+Ref"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Klein+Ref {v['klein_model']} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"Klein+Ref {v['klein_model']} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Klein+Ref Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_embed_watermark(self, procedure, run_mode, image, drawables, config, data):
        """Embed invisible encrypted metadata into the current image using LSB steganography."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        dlg = Gtk.Dialog(title="Spellcaster — Embed Invisible Watermark")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Embed", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)

        bx.pack_start(Gtk.Label(label="Embed encrypted metadata invisibly into the image pixels.\n"
                                      "Data survives metadata stripping but requires PNG output."),
                       False, False, 4)

        # Passphrase
        hb_key = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_key.pack_start(Gtk.Label(label="Passphrase:"), False, False, 0)
        key_entry = Gtk.Entry(); key_entry.set_text("spellcaster-default-v1")
        key_entry.set_visibility(False); key_entry.set_hexpand(True)
        key_entry.set_tooltip_text("Encryption passphrase for the watermark.\nAnyone with this passphrase can read the hidden data. Keep it secret!")
        hb_key.pack_start(key_entry, True, True, 0)
        bx.pack_start(hb_key, False, False, 0)

        # Author
        hb_author = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_author.pack_start(Gtk.Label(label="Author:"), False, False, 0)
        author_entry = Gtk.Entry(); author_entry.set_text(os.environ.get("USERNAME", os.environ.get("USER", "")))
        author_entry.set_hexpand(True)
        author_entry.set_tooltip_text("Your name or identifier to embed in the watermark.\nThis helps prove authorship of the image.")
        hb_author.pack_start(author_entry, True, True, 0)
        bx.pack_start(hb_author, False, False, 0)

        # Custom message
        hb_msg = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_msg.pack_start(Gtk.Label(label="Message:"), False, False, 0)
        msg_entry = Gtk.Entry(); msg_entry.set_placeholder_text("Optional custom message")
        msg_entry.set_hexpand(True)
        msg_entry.set_tooltip_text("Optional free-text message to embed.\nExample: copyright notice, project name, or usage terms.")
        hb_msg.pack_start(msg_entry, True, True, 0)
        bx.pack_start(hb_msg, False, False, 0)

        bx.pack_start(Gtk.Label(label="The watermark is invisible and encrypted.\n"
                                      "Only someone with the passphrase can read it.\n"
                                      "Save as PNG to preserve the watermark."),
                       False, False, 4)
        bx.show_all()

        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        passphrase = key_entry.get_text().strip() or "spellcaster-default-v1"
        author = author_entry.get_text().strip()
        message = msg_entry.get_text().strip()
        dlg.destroy()

        try:
            from spellcaster_steg import embed_metadata as steg_embed

            Gimp.progress_init("Embedding invisible watermark...")

            # Flatten and get pixel data
            flat = image.flatten()
            drawable = image.get_active_drawable()
            w, h = drawable.get_width(), drawable.get_height()

            # Get pixel bytes via GeglBuffer
            buf = drawable.get_buffer()
            rect = Gegl.Rectangle.new(0, 0, w, h)
            pixel_data = buf.get(rect, 1.0, None, Gegl.AbyssPolicy.CLAMP)
            # Gegl returns RGBA or RGB depending on format
            fmt = buf.get_format()
            bpp_gegl = fmt.get_bytes_per_pixel()

            # Convert to RGB bytearray
            if bpp_gegl == 4:
                # RGBA -> RGB
                rgb = bytearray()
                for i in range(0, len(pixel_data), 4):
                    rgb.extend(pixel_data[i:i+3])
                pixels = rgb
            else:
                pixels = bytearray(pixel_data)

            # Build metadata
            import time as _time
            meta = {
                "tool": "Spellcaster",
                "version": "1.0.0",
                "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "image_size": f"{w}x{h}",
            }
            if author:
                meta["author"] = author
            if message:
                meta["message"] = message

            steg_embed(pixels, w, h, meta, passphrase)

            # Write modified pixels back
            if bpp_gegl == 4:
                # Re-insert alpha
                rgba = bytearray()
                pi = 0
                for i in range(0, len(pixel_data), 4):
                    rgba.extend(pixels[pi:pi+3])
                    rgba.append(pixel_data[i+3])  # original alpha
                    pi += 3
                buf.set(rect, fmt, bytes(rgba))
            else:
                buf.set(rect, fmt, bytes(pixels))

            buf.flush()
            Gimp.displays_flush()
            Gimp.progress_end()

            payload_bits = len(json.dumps(meta, separators=(",", ":"))) * 8
            bpp_used = payload_bits / (w * h)
            Gimp.message(f"Invisible watermark embedded!\n\n"
                         f"Bits per pixel: {bpp_used:.5f} (safe limit: 0.05)\n"
                         f"Author: {author or '(none)'}\n\n"
                         f"Save as PNG to preserve the watermark.")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Watermark embedding failed: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_read_watermark(self, procedure, run_mode, image, drawables, config, data):
        """Read and display hidden metadata from a watermarked image."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        # Ask for passphrase
        dlg = Gtk.Dialog(title="Spellcaster — Read Invisible Watermark")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Read", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Passphrase:"), False, False, 0)
        key_entry = Gtk.Entry(); key_entry.set_text("spellcaster-default-v1")
        key_entry.set_visibility(False); key_entry.set_hexpand(True)
        key_entry.set_tooltip_text("Enter the passphrase that was used to embed the watermark.\nMust match exactly or decryption will fail.")
        hb.pack_start(key_entry, True, True, 0)
        bx.pack_start(hb, False, False, 0)
        bx.show_all()

        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        passphrase = key_entry.get_text().strip() or "spellcaster-default-v1"
        dlg.destroy()

        try:
            from spellcaster_steg import extract_metadata as steg_extract

            Gimp.progress_init("Reading invisible watermark...")

            drawable = image.get_active_drawable()
            w, h = drawable.get_width(), drawable.get_height()
            buf = drawable.get_buffer()
            rect = Gegl.Rectangle.new(0, 0, w, h)
            pixel_data = buf.get(rect, 1.0, None, Gegl.AbyssPolicy.CLAMP)
            fmt = buf.get_format()
            bpp_gegl = fmt.get_bytes_per_pixel()

            if bpp_gegl == 4:
                pixels = bytes(pixel_data[i] for i in range(len(pixel_data)) if i % 4 != 3)
            else:
                pixels = bytes(pixel_data)

            result = steg_extract(pixels, w, h, passphrase)
            Gimp.progress_end()

            if result is None:
                Gimp.message("No Spellcaster watermark found.\n\n"
                             "Possible reasons:\n"
                             "- Image has no embedded watermark\n"
                             "- Wrong passphrase\n"
                             "- Image was saved as JPEG (destroys watermark)\n"
                             "- Image was resized or re-encoded")
            else:
                lines = ["Spellcaster Invisible Watermark Found!\n"]
                for k, v in result.items():
                    lines.append(f"  {k}: {v}")
                Gimp.message("\n".join(lines))

            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Watermark reading failed: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_upscale(self, procedure, run_mode, image, drawables, config, data):
        """Upscale 4x: super-resolution using an upscale model."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        # Minimal dialog — dropdown for model preset + server URL
        dlg = Gtk.Dialog(title="Spellcaster — Upscale 4x")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Upscale", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # Model preset dropdown
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="Model:"), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("Super-resolution model to use.\nDifferent models excel at different content (photos, anime, etc).")
        for label in UPSCALE_PRESETS:
            model_combo.append(label, label)
        model_combo.set_active(0)
        model_combo.set_hexpand(True)
        hb2.pack_start(model_combo, True, True, 0); bx.pack_start(hb2, False, False, 0)
        bx.pack_start(Gtk.Label(label="Upscales image using a super-resolution model.\nResult is imported as a new layer."), False, False, 4)
        bx.show_all()
        last = _SESSION.get("upscale")
        if last and "model_id" in last:
            model_combo.set_active_id(last["model_id"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        preset_key = model_combo.get_active_id()
        model_name = UPSCALE_PRESETS[preset_key]
        _SESSION["upscale"] = {"model_id": preset_key}
        dlg.destroy()
        try:
            Gimp.progress_init("Upscale: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_upscale_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_upscale(uname, model_name)
            Gimp.progress_set_text("Upscale: processing on ComfyUI...")
            results = _run_with_spinner("Upscale: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Upscale {preset_key} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Upscale Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_lama_remove(self, procedure, run_mode, image, drawables, config, data):
        """Object removal: LaMa inpainting on selection — no checkpoint, no prompt."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        # Minimal dialog — just server URL and go
        dlg = Gtk.Dialog(title="Spellcaster — Object Removal (LaMa)")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Remove Object", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        bx.pack_start(Gtk.Label(label="Paint a selection over the object to remove.\nUses LaMa inpainting (no AI model/prompt needed)."), False, False, 4)
        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv); dlg.destroy()
        try:
            Gimp.progress_init("LaMa Remove: building selection mask...")
            # Build mask from GIMP's selection channel
            mtmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False); mtmp.close()
            _create_selection_mask_png(mtmp.name, image)
            Gimp.progress_set_text("LaMa Remove: exporting image...")
            tmp = _export_image_to_tmp(image)
            iname = f"gimp_lama_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, iname); os.unlink(tmp)
            mname = f"gimp_lama_mask_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, mtmp.name, mname); os.unlink(mtmp.name)
            wf = _build_lama_remove(iname, mname)
            Gimp.progress_set_text("LaMa Remove: processing on ComfyUI...")
            results = _run_with_spinner("LaMa Remove: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"LaMa Object Removed #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster LaMa Remove Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_lut(self, procedure, run_mode, image, drawables, config, data):
        """Color grading: apply a cinematic LUT to the image."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — Color Grading (LUT)")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Apply LUT", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # LUT preset dropdown
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="LUT:"), False, False, 0)
        lut_combo = Gtk.ComboBoxText()
        lut_combo.set_tooltip_text("Color Look-Up Table preset for cinematic color grading.\nEach LUT gives a different film or mood look.")
        for label in LUT_PRESETS:
            lut_combo.append(label, label)
        lut_combo.set_active(0)
        lut_combo.set_hexpand(True)
        hb2.pack_start(lut_combo, True, True, 0); bx.pack_start(hb2, False, False, 0)
        # Strength slider
        hb3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb3.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        strength_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        strength_spin.set_value(0.7)
        strength_spin.set_digits(2)
        strength_spin.set_tooltip_text("How strongly the LUT color grade is applied.\n0.0 = no effect, 0.7 = default, 1.0 = full strength.")
        hb3.pack_start(strength_spin, True, True, 0); bx.pack_start(hb3, False, False, 0)
        bx.show_all()
        last = _SESSION.get("lut")
        if last:
            if "lut_id" in last:
                lut_combo.set_active_id(last["lut_id"])
            if "strength" in last:
                strength_spin.set_value(last["strength"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        preset_key = lut_combo.get_active_id()
        lut_name = LUT_PRESETS[preset_key]
        strength = strength_spin.get_value()
        _SESSION["lut"] = {"lut_id": preset_key, "strength": strength}
        dlg.destroy()
        try:
            Gimp.progress_init("LUT: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_lut_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_lut(uname, lut_name, strength)
            Gimp.progress_set_text("LUT: processing on ComfyUI...")
            results = _run_with_spinner("LUT: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"LUT {preset_key} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster LUT Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_outpaint(self, procedure, run_mode, image, drawables, config, data):
        """Outpaint: extend canvas by generating new content at the edges."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = PresetDialog("Spellcaster — Outpaint / Extend Canvas", mode="img2img")
        dlg.w_spin.set_value(image.get_width())
        dlg.h_spin.set_value(image.get_height())
        last = _SESSION.get("outpaint")
        if last:
            last_no_dims = {k: v for k, v in last.items() if k not in ("width", "height")}
            dlg._apply_session(last_no_dims)
        # Add padding inputs and feathering to the dialog content area
        outpaint_frame = Gtk.Frame(label="Outpaint Padding (pixels)")
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        grid.set_margin_start(8); grid.set_margin_end(8)
        grid.set_margin_top(8); grid.set_margin_bottom(8)
        grid.attach(Gtk.Label(label="Left:", xalign=1), 0, 0, 1, 1)
        left_spin = Gtk.SpinButton.new_with_range(0, 2048, 8)
        left_spin.set_value(0)
        left_spin.set_tooltip_text("Pixels to extend on the left side.\n0 = no extension. Set a value to generate new content on this edge.")
        grid.attach(left_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Top:", xalign=1), 2, 0, 1, 1)
        top_spin = Gtk.SpinButton.new_with_range(0, 2048, 8)
        top_spin.set_value(0)
        top_spin.set_tooltip_text("Pixels to extend on the top side.\n0 = no extension.")
        grid.attach(top_spin, 3, 0, 1, 1)
        grid.attach(Gtk.Label(label="Right:", xalign=1), 0, 1, 1, 1)
        right_spin = Gtk.SpinButton.new_with_range(0, 2048, 8)
        right_spin.set_value(0)
        right_spin.set_tooltip_text("Pixels to extend on the right side.\n0 = no extension.")
        grid.attach(right_spin, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="Bottom:", xalign=1), 2, 1, 1, 1)
        bottom_spin = Gtk.SpinButton.new_with_range(0, 2048, 8)
        bottom_spin.set_value(256)
        bottom_spin.set_tooltip_text("Pixels to extend on the bottom side.\nDefault: 256. The AI will generate new content here.")
        grid.attach(bottom_spin, 3, 1, 1, 1)
        grid.attach(Gtk.Label(label="Feathering:", xalign=1), 0, 2, 1, 1)
        feather_spin = Gtk.SpinButton.new_with_range(0, 256, 1)
        feather_spin.set_value(40)
        feather_spin.set_tooltip_text("Feathering radius for blending new and old content.\nHigher = smoother transition. Default: 40.")
        grid.attach(feather_spin, 1, 2, 1, 1)
        outpaint_frame.add(grid)
        outpaint_frame.show_all()
        dlg.get_content_area().pack_start(outpaint_frame, False, False, 0)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["outpaint"] = dlg._collect_session()
        pad_left = int(left_spin.get_value())
        pad_top = int(top_spin.get_value())
        pad_right = int(right_spin.get_value())
        pad_bottom = int(bottom_spin.get_value())
        feathering = int(feather_spin.get_value())
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            Gimp.progress_init("Outpaint: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_outpaint_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                     _build_outpaint(uname, v["preset"], v["prompt"], v["negative"], seed,
                                      pad_left, pad_top, pad_right, pad_bottom, feathering, v.get("loras"))
                label = f"Outpaint run {run_i+1}/{runs}" if runs > 1 else "Outpaint"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Outpaint {v['preset'].get('label','')} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"Outpaint {v['preset'].get('label','')} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Outpaint Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_style_transfer(self, procedure, run_mode, image, drawables, config, data):
        """Style transfer: apply the visual style of a reference image using IPAdapter."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        # Dialog similar to FaceID — model preset + file chooser + sliders
        dlg = Gtk.Dialog(title="Spellcaster — Style Transfer (IPAdapter)")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Run", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # Model preset
        bx.pack_start(Gtk.Label(label="Model Preset:", xalign=0), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("Base checkpoint model for style transfer.\nSDXL models generally produce the best style transfer results.")
        for i, p in enumerate(MODEL_PRESETS):
            model_combo.append(str(i), p["label"])
        model_combo.set_active(0)
        bx.pack_start(model_combo, False, False, 0)
        # IPAdapter preset
        hb_ip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_ip.pack_start(Gtk.Label(label="IPAdapter Preset:"), False, False, 0)
        ip_combo = Gtk.ComboBoxText()
        ip_combo.set_tooltip_text("IPAdapter variant for style extraction.\nPLUS = strong style transfer, LIGHT = subtle, FACE = optimized for portraits.")
        for p in ["PLUS (high strength)", "PLUS FACE (portraits)",
                   "LIGHT - SD1.5 only", "STANDARD (medium)", "VIT-G (medium)"]:
            ip_combo.append(p, p)
        ip_combo.set_active(0)
        ip_combo.set_hexpand(True)
        hb_ip.pack_start(ip_combo, True, True, 0); bx.pack_start(hb_ip, False, False, 0)
        # Style reference image file chooser
        hb_fc = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_fc.pack_start(Gtk.Label(label="Style Reference:"), False, False, 0)
        style_chooser = Gtk.FileChooserButton(title="Select style reference image")
        style_chooser.set_tooltip_text("Select an image whose visual style (colors, textures, mood) you want to apply.\nThe AI will transfer the artistic style to your canvas.")
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_mime_type("image/png"); ff.add_mime_type("image/jpeg")
        ff.add_pattern("*.png"); ff.add_pattern("*.jpg"); ff.add_pattern("*.jpeg")
        style_chooser.add_filter(ff)
        style_chooser.set_hexpand(True)
        hb_fc.pack_start(style_chooser, True, True, 0); bx.pack_start(hb_fc, False, False, 0)
        # Prompt
        bx.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 60)
        prompt_tv.set_tooltip_text("Describe the desired output. The style comes from the reference image.\nExample: 'beautiful landscape, golden hour' or leave empty for pure style transfer.")
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(60)
        bx.pack_start(sw, False, False, 0)
        # Negative
        bx.pack_start(Gtk.Label(label="Negative:", xalign=0), False, False, 0)
        neg_tv = Gtk.TextView(); neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        neg_tv.set_size_request(-1, 40)
        neg_tv.set_tooltip_text("Describe what you do NOT want (e.g. 'blurry, distorted').")
        neg_tv.get_buffer().set_text("blurry, deformed, bad anatomy, disfigured")
        sw2 = Gtk.ScrolledWindow(); sw2.add(neg_tv); sw2.set_min_content_height(40)
        bx.pack_start(sw2, False, False, 0)
        # Sliders grid
        sgrid = Gtk.Grid(column_spacing=12, row_spacing=6)
        sgrid.attach(Gtk.Label(label="Weight:", xalign=1), 0, 0, 1, 1)
        weight_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        weight_spin.set_value(0.8); weight_spin.set_digits(2)
        weight_spin.set_tooltip_text("How strongly the reference style is applied.\n0.8 = strong style transfer (default). Lower = subtler effect.")
        sgrid.attach(weight_spin, 1, 0, 1, 1)
        sgrid.attach(Gtk.Label(label="Denoise:", xalign=1), 2, 0, 1, 1)
        denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
        denoise_spin.set_value(0.6); denoise_spin.set_digits(2)
        denoise_spin.set_tooltip_text("How much to change the original image.\n0.3 = subtle, 0.6 = balanced (default), 0.9 = heavy restyle.")
        sgrid.attach(denoise_spin, 3, 0, 1, 1)
        sgrid.attach(Gtk.Label(label="Seed:", xalign=1), 0, 1, 1, 1)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        sgrid.attach(seed_spin, 1, 1, 1, 1)
        bx.pack_start(sgrid, False, False, 0)
        # Runs spinner
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        bx.pack_start(runs_hb, False, False, 0)
        bx.show_all()
        last = _SESSION.get("style_transfer")
        if last:
            if "model_idx" in last:
                model_combo.set_active(last["model_idx"])
            if "ip_id" in last:
                ip_combo.set_active_id(last["ip_id"])
            if "prompt" in last:
                prompt_tv.get_buffer().set_text(last["prompt"])
            if "negative" in last:
                neg_tv.get_buffer().set_text(last["negative"])
            if "weight" in last:
                weight_spin.set_value(last["weight"])
            if "denoise" in last:
                denoise_spin.set_value(last["denoise"])
            if "runs" in last:
                runs_spin.set_value(last["runs"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        idx = model_combo.get_active()
        preset = dict(MODEL_PRESETS[idx] if idx >= 0 else MODEL_PRESETS[0])
        ipadapter_preset = ip_combo.get_active_id() or "PLUS (high strength)"
        style_path = None
        f = style_chooser.get_file()
        if f:
            style_path = f.get_path()
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        nbuf = neg_tv.get_buffer()
        negative = nbuf.get_text(nbuf.get_start_iter(), nbuf.get_end_iter(), False)
        weight = weight_spin.get_value()
        denoise = denoise_spin.get_value()
        base_seed = int(seed_spin.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        runs = int(runs_spin.get_value())
        _SESSION["style_transfer"] = {
            "model_idx": idx, "ip_id": ipadapter_preset,
            "prompt": prompt, "negative": negative,
            "weight": weight, "denoise": denoise,
            "runs": runs,
        }
        dlg.destroy()
        if not style_path:
            Gimp.message("No style reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("Style Transfer: exporting images...")
            # Upload target (current canvas)
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_style_tgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            # Upload style reference
            ref_name = f"gimp_style_ref_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, style_path, ref_name)
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_style_transfer(
                    tgt_name, ref_name, preset,
                    prompt, negative, seed,
                    ipadapter_preset=ipadapter_preset,
                    weight=weight, denoise=denoise,
                )
                label = f"Style Transfer run {run_i+1}/{runs}" if runs > 1 else "Style Transfer"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Style Transfer run {run_i+1} #{i+1}" if runs > 1 else f"Style Transfer #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Style Transfer Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_face_restore(self, procedure, run_mode, image, drawables, config, data):
        """Face restore: enhance and restore faces using ReActorRestoreFace."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — Face Restore")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Restore Faces", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # Restore model preset dropdown
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="Restore Model:"), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("AI model for face restoration.\nCodeFormer preserves identity best. GFPGAN is faster but may alter features.")
        for label in FACE_RESTORE_PRESETS:
            model_combo.append(label, label)
        model_combo.set_active(0)
        model_combo.set_hexpand(True)
        hb2.pack_start(model_combo, True, True, 0); bx.pack_start(hb2, False, False, 0)
        # Face detection dropdown
        hb3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb3.pack_start(Gtk.Label(label="Face Detection:"), False, False, 0)
        det_combo = Gtk.ComboBoxText()
        det_combo.set_tooltip_text("Face detection model. retinaface_resnet50 is most accurate.\nYOLO variants are faster but may miss small or angled faces.")
        for det in ["retinaface_resnet50", "retinaface_mobile0.25", "YOLOv5l", "YOLOv5n"]:
            det_combo.append(det, det)
        det_combo.set_active(0)
        det_combo.set_hexpand(True)
        hb3.pack_start(det_combo, True, True, 0); bx.pack_start(hb3, False, False, 0)
        # Visibility slider
        hb4 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb4.pack_start(Gtk.Label(label="Visibility:"), False, False, 0)
        vis_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        vis_spin.set_value(1.0); vis_spin.set_digits(2)
        vis_spin.set_tooltip_text("How visible the restoration effect is.\n1.0 = full restoration, lower values blend with original.")
        hb4.pack_start(vis_spin, True, True, 0); bx.pack_start(hb4, False, False, 0)
        # Codeformer weight slider
        hb5 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb5.pack_start(Gtk.Label(label="CodeFormer Weight:"), False, False, 0)
        cf_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        cf_spin.set_value(0.5); cf_spin.set_digits(2)
        cf_spin.set_tooltip_text("Only affects CodeFormer model")
        hb5.pack_start(cf_spin, True, True, 0); bx.pack_start(hb5, False, False, 0)
        bx.pack_start(Gtk.Label(label="Restores and enhances faces in the image.\nResult is imported as a new layer."), False, False, 4)
        bx.show_all()
        last = _SESSION.get("face_restore")
        if last:
            if "model_id" in last:
                model_combo.set_active_id(last["model_id"])
            if "det_id" in last:
                det_combo.set_active_id(last["det_id"])
            if "visibility" in last:
                vis_spin.set_value(last["visibility"])
            if "codeformer_weight" in last:
                cf_spin.set_value(last["codeformer_weight"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        preset_key = model_combo.get_active_id()
        fr_preset = FACE_RESTORE_PRESETS[preset_key]
        facedetection = det_combo.get_active_id()
        visibility = vis_spin.get_value()
        codeformer_weight = cf_spin.get_value()
        _SESSION["face_restore"] = {
            "model_id": preset_key, "det_id": facedetection,
            "visibility": visibility, "codeformer_weight": codeformer_weight,
        }
        dlg.destroy()
        try:
            Gimp.progress_init("Face Restore: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_facerestore_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_face_restore(uname, fr_preset["model"], facedetection,
                                      visibility, codeformer_weight)
            Gimp.progress_set_text("Face Restore: processing on ComfyUI...")
            results = _run_with_spinner("Face Restore: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Face Restore {preset_key} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Face Restore Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_photo_restore(self, procedure, run_mode, image, drawables, config, data):
        """Photo restoration pipeline: upscale + face restore + sharpen."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — Photo Restoration Pipeline")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Restore Photo", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # Upscale model dropdown
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="Upscale Model:"), False, False, 0)
        up_combo = Gtk.ComboBoxText()
        up_combo.set_tooltip_text("Super-resolution model for the upscale step.\nThis enlarges the image before face restoration.")
        for label in RESTORE_UPSCALE_PRESETS:
            up_combo.append(label, label)
        up_combo.set_active(0)
        up_combo.set_hexpand(True)
        hb2.pack_start(up_combo, True, True, 0); bx.pack_start(hb2, False, False, 0)
        # Face restore model dropdown
        hb3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb3.pack_start(Gtk.Label(label="Face Restore:"), False, False, 0)
        face_combo = Gtk.ComboBoxText()
        face_combo.set_tooltip_text("AI model for face restoration after upscaling.\nCodeFormer preserves identity best.")
        for label in FACE_RESTORE_PRESETS:
            face_combo.append(label, label)
        face_combo.set_active(0)
        face_combo.set_hexpand(True)
        hb3.pack_start(face_combo, True, True, 0); bx.pack_start(hb3, False, False, 0)
        # Sharpen amount slider
        hb4 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb4.pack_start(Gtk.Label(label="Sharpen Amount:"), False, False, 0)
        sharpen_spin = Gtk.SpinButton.new_with_range(0.0, 2.0, 0.05)
        sharpen_spin.set_value(0.5); sharpen_spin.set_digits(2)
        sharpen_spin.set_tooltip_text("Post-processing sharpening amount.\n0.0 = no sharpening, 0.5 = default, 2.0 = aggressive. Too high can cause artifacts.")
        hb4.pack_start(sharpen_spin, True, True, 0); bx.pack_start(hb4, False, False, 0)
        # Codeformer weight slider
        hb5 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb5.pack_start(Gtk.Label(label="CodeFormer Weight:"), False, False, 0)
        cf_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        cf_spin.set_value(0.5); cf_spin.set_digits(2)
        cf_spin.set_tooltip_text("CodeFormer fidelity weight (only affects CodeFormer model).\n0.0 = max quality, 1.0 = max fidelity to original. Default: 0.5")
        hb5.pack_start(cf_spin, True, True, 0); bx.pack_start(hb5, False, False, 0)
        bx.pack_start(Gtk.Label(label="Full restoration pipeline for old/damaged photos.\nUpscale → Face Restore → Sharpen."), False, False, 4)
        bx.show_all()
        last = _SESSION.get("photo_restore")
        if last:
            if "up_id" in last:
                up_combo.set_active_id(last["up_id"])
            if "face_id" in last:
                face_combo.set_active_id(last["face_id"])
            if "sharpen" in last:
                sharpen_spin.set_value(last["sharpen"])
            if "codeformer_weight" in last:
                cf_spin.set_value(last["codeformer_weight"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        up_key = up_combo.get_active_id()
        upscale_model = RESTORE_UPSCALE_PRESETS[up_key]
        face_key = face_combo.get_active_id()
        fr_preset = FACE_RESTORE_PRESETS[face_key]
        sharpen_amount = sharpen_spin.get_value()
        codeformer_weight = cf_spin.get_value()
        _SESSION["photo_restore"] = {
            "up_id": up_key, "face_id": face_key,
            "sharpen": sharpen_amount, "codeformer_weight": codeformer_weight,
        }
        dlg.destroy()
        try:
            Gimp.progress_init("Photo Restore: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_photorestore_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_photo_restore(uname, upscale_model, fr_preset["model"],
                                       "retinaface_resnet50", 1.0, codeformer_weight,
                                       1, 0.5, sharpen_amount)
            Gimp.progress_set_text("Photo Restore: processing on ComfyUI...")
            results = _run_with_spinner("Photo Restore: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Photo Restore #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Photo Restore Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_detail_hallucinate(self, procedure, run_mode, image, drawables, config, data):
        """Detail hallucination: upscale + low-denoise img2img to add AI detail."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — Detail Hallucination")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Run", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # Detail level preset dropdown
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="Detail Level:"), False, False, 0)
        detail_combo = Gtk.ComboBoxText()
        detail_combo.set_tooltip_text("How much AI detail to hallucinate.\nSubtle = minimal changes, Moderate = balanced, Heavy = significant new detail.")
        for label in HALLUCINATE_PRESETS:
            detail_combo.append(label, label)
        detail_combo.set_active(1)  # default to "Moderate"
        detail_combo.set_hexpand(True)
        hb2.pack_start(detail_combo, True, True, 0); bx.pack_start(hb2, False, False, 0)
        # Upscale model dropdown
        hb3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb3.pack_start(Gtk.Label(label="Upscale Model:"), False, False, 0)
        up_combo = Gtk.ComboBoxText()
        up_combo.set_tooltip_text("Super-resolution model for the initial upscale step.\nThe image is upscaled first, then detail is hallucinated via img2img.")
        for label in UPSCALE_PRESETS:
            up_combo.append(label, label)
        up_combo.set_active(0)
        up_combo.set_hexpand(True)
        hb3.pack_start(up_combo, True, True, 0); bx.pack_start(hb3, False, False, 0)
        # Checkpoint model dropdown
        bx.pack_start(Gtk.Label(label="Checkpoint Model:", xalign=0), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("AI model used for the detail hallucination (img2img) pass.\nMatch this to your image style (photo, anime, etc).")
        for i, p in enumerate(MODEL_PRESETS):
            model_combo.append(str(i), p["label"])
        model_combo.set_active(0)
        bx.pack_start(model_combo, False, False, 0)
        # Prompt
        bx.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 60)
        prompt_tv.set_tooltip_text("Describe the kind of detail you want the AI to add.\nDefault works well for most photos.")
        prompt_tv.get_buffer().set_text("ultra detailed, sharp focus, high resolution, intricate details")
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(60)
        bx.pack_start(sw, False, False, 0)
        # Negative
        bx.pack_start(Gtk.Label(label="Negative:", xalign=0), False, False, 0)
        neg_tv = Gtk.TextView(); neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        neg_tv.set_size_request(-1, 40)
        neg_tv.set_tooltip_text("Describe what you do NOT want (e.g. 'blurry, soft').")
        neg_tv.get_buffer().set_text("blurry, low quality, soft, out of focus")
        sw2 = Gtk.ScrolledWindow(); sw2.add(neg_tv); sw2.set_min_content_height(40)
        bx.pack_start(sw2, False, False, 0)
        # Seed
        hb_seed = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_seed.pack_start(Gtk.Label(label="Seed:"), False, False, 0)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        hb_seed.pack_start(seed_spin, True, True, 0); bx.pack_start(hb_seed, False, False, 0)
        # Runs spinner
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        bx.pack_start(runs_hb, False, False, 0)
        bx.show_all()
        last = _SESSION.get("detail_hallucinate")
        if last:
            if "detail_id" in last:
                detail_combo.set_active_id(last["detail_id"])
            if "up_id" in last:
                up_combo.set_active_id(last["up_id"])
            if "model_idx" in last:
                model_combo.set_active(last["model_idx"])
            if "prompt" in last:
                prompt_tv.get_buffer().set_text(last["prompt"])
            if "negative" in last:
                neg_tv.get_buffer().set_text(last["negative"])
            if "runs" in last:
                runs_spin.set_value(last["runs"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        detail_key = detail_combo.get_active_id()
        h_preset = HALLUCINATE_PRESETS[detail_key]
        up_key = up_combo.get_active_id()
        upscale_model = UPSCALE_PRESETS[up_key]
        idx = model_combo.get_active()
        preset = dict(MODEL_PRESETS[idx] if idx >= 0 else MODEL_PRESETS[0])
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        nbuf = neg_tv.get_buffer()
        negative = nbuf.get_text(nbuf.get_start_iter(), nbuf.get_end_iter(), False)
        base_seed = int(seed_spin.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        runs = int(runs_spin.get_value())
        _SESSION["detail_hallucinate"] = {
            "detail_id": detail_key, "up_id": up_key, "model_idx": idx,
            "prompt": prompt, "negative": negative,
            "runs": runs,
        }
        dlg.destroy()
        try:
            Gimp.progress_init("Detail Hallucinate: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_hallucinate_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_detail_hallucinate(uname, upscale_model, preset, prompt, negative,
                                                seed, h_preset["denoise"], h_preset["cfg"])
                label = f"Detail Hallucinate run {run_i+1}/{runs}" if runs > 1 else "Detail Hallucinate"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Detail Hallucinate {detail_key} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"Detail Hallucinate {detail_key} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Detail Hallucinate Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_seedv2r(self, procedure, run_mode, image, drawables, config, data):
        """SeedV2R Upscale: upscale + img2img with user-controlled scale and hallucination."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — SeedV2R Upscale")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Run", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # Checkpoint model dropdown
        bx.pack_start(Gtk.Label(label="Checkpoint Model:", xalign=0), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("AI model for the img2img hallucination pass.\nMatch this to your image style for best results.")
        for i, p in enumerate(MODEL_PRESETS):
            model_combo.append(str(i), p["label"])
        model_combo.set_active(0)
        bx.pack_start(model_combo, False, False, 0)
        # Upscale model dropdown
        hb_up = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_up.pack_start(Gtk.Label(label="Upscale Model:"), False, False, 0)
        up_combo = Gtk.ComboBoxText()
        up_combo.set_tooltip_text("Super-resolution model for the initial upscale step.\nImage is upscaled first, then refined with AI detail.")
        for label in UPSCALE_PRESETS:
            up_combo.append(label, label)
        up_combo.set_active(0)
        up_combo.set_hexpand(True)
        hb_up.pack_start(up_combo, True, True, 0); bx.pack_start(hb_up, False, False, 0)
        # Scale dropdown
        hb_scale = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_scale.pack_start(Gtk.Label(label="Scale:"), False, False, 0)
        scale_combo = Gtk.ComboBoxText()
        scale_combo.set_tooltip_text("Final output scale relative to original size.\nHigher = larger output. 2x is recommended. 4x uses significantly more VRAM.")
        for i, (lbl, _factor) in enumerate(SEEDV2R_SCALE_OPTIONS):
            scale_combo.append(str(i), lbl)
        scale_combo.set_active(2)  # default to 2x
        scale_combo.set_hexpand(True)
        hb_scale.pack_start(scale_combo, True, True, 0); bx.pack_start(hb_scale, False, False, 0)
        # Hallucination level dropdown
        hb_hall = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_hall.pack_start(Gtk.Label(label="Hallucination Level:"), False, False, 0)
        hall_combo = Gtk.ComboBoxText()
        hall_combo.set_tooltip_text("How much AI-generated detail to add.\nSubtle = faithful upscale, Moderate = balanced, Heavy = significant AI detail added.")
        for i, hp in enumerate(SEEDV2R_PRESETS):
            hall_combo.append(str(i), hp["label"])
        hall_combo.set_active(2)  # default to Moderate
        hall_combo.set_hexpand(True)
        hb_hall.pack_start(hall_combo, True, True, 0); bx.pack_start(hb_hall, False, False, 0)
        # Prompt
        bx.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 60)
        prompt_tv.set_tooltip_text("Describe the detail style to hallucinate.\nAuto-filled by hallucination level. Customize for specific content.")
        prompt_tv.get_buffer().set_text(SEEDV2R_PRESETS[2]["prompt"])
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(60)
        bx.pack_start(sw, False, False, 0)
        # Negative
        bx.pack_start(Gtk.Label(label="Negative:", xalign=0), False, False, 0)
        neg_tv = Gtk.TextView(); neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        neg_tv.set_size_request(-1, 40)
        neg_tv.set_tooltip_text("Describe what you do NOT want (e.g. 'blurry, soft').")
        neg_tv.get_buffer().set_text(SEEDV2R_PRESETS[2]["negative"])
        sw2 = Gtk.ScrolledWindow(); sw2.add(neg_tv); sw2.set_min_content_height(40)
        bx.pack_start(sw2, False, False, 0)

        # Update prompt/negative when hallucination level changes
        def _on_hall_changed(combo):
            idx = combo.get_active()
            if 0 <= idx < len(SEEDV2R_PRESETS):
                prompt_tv.get_buffer().set_text(SEEDV2R_PRESETS[idx]["prompt"])
                neg_tv.get_buffer().set_text(SEEDV2R_PRESETS[idx]["negative"])
        hall_combo.connect("changed", _on_hall_changed)

        # Seed
        hb_seed = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_seed.pack_start(Gtk.Label(label="Seed:"), False, False, 0)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        hb_seed.pack_start(seed_spin, True, True, 0); bx.pack_start(hb_seed, False, False, 0)
        # Runs spinner
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        bx.pack_start(runs_hb, False, False, 0)
        bx.show_all()
        # Session recall
        last = _SESSION.get("seedv2r")
        if last:
            if "model_idx" in last:
                model_combo.set_active(last["model_idx"])
            if "up_id" in last:
                up_combo.set_active_id(last["up_id"])
            if "scale_idx" in last:
                scale_combo.set_active(last["scale_idx"])
            if "hall_idx" in last:
                hall_combo.set_active(last["hall_idx"])
            if "prompt" in last:
                prompt_tv.get_buffer().set_text(last["prompt"])
            if "negative" in last:
                neg_tv.get_buffer().set_text(last["negative"])
            if "runs" in last:
                runs_spin.set_value(last["runs"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        idx = model_combo.get_active()
        preset = dict(MODEL_PRESETS[idx] if idx >= 0 else MODEL_PRESETS[0])
        up_key = up_combo.get_active_id()
        upscale_model = UPSCALE_PRESETS[up_key]
        scale_idx = scale_combo.get_active()
        _scale_label, scale_factor = SEEDV2R_SCALE_OPTIONS[scale_idx]
        hall_idx = hall_combo.get_active()
        hall_preset = SEEDV2R_PRESETS[hall_idx]
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        nbuf = neg_tv.get_buffer()
        negative = nbuf.get_text(nbuf.get_start_iter(), nbuf.get_end_iter(), False)
        base_seed = int(seed_spin.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        runs = int(runs_spin.get_value())
        _SESSION["seedv2r"] = {
            "model_idx": idx, "up_id": up_key, "scale_idx": scale_idx,
            "hall_idx": hall_idx, "prompt": prompt, "negative": negative,
            "runs": runs,
        }
        dlg.destroy()
        try:
            Gimp.progress_init("SeedV2R: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_seedv2r_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            orig_w = image.get_width()
            orig_h = image.get_height()
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_seedv2r(uname, upscale_model, preset, prompt, negative,
                                     seed, hall_preset["denoise"], hall_preset["cfg"],
                                     hall_preset["steps"], scale_factor, orig_w, orig_h)
                label = f"SeedV2R run {run_i+1}/{runs}" if runs > 1 else "SeedV2R"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"SeedV2R {hall_preset['label']} {_scale_label} run {run_i+1} #{i+1}" if runs > 1 \
                          else f"SeedV2R {hall_preset['label']} {_scale_label} #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster SeedV2R Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_colorize(self, procedure, run_mode, image, drawables, config, data):
        """Colorize B&W photo using ControlNet lineart + img2img."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — Colorize B&W Photo")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Colorize", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # Checkpoint model dropdown
        bx.pack_start(Gtk.Label(label="Checkpoint Model:", xalign=0), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("AI model for colorization. Realistic photo models work best.\nThe model generates colors guided by ControlNet lineart.")
        for i, p in enumerate(MODEL_PRESETS):
            model_combo.append(str(i), p["label"])
        model_combo.set_active(0)
        bx.pack_start(model_combo, False, False, 0)
        # ControlNet strength slider
        sgrid = Gtk.Grid(column_spacing=12, row_spacing=6)
        sgrid.attach(Gtk.Label(label="ControlNet Strength:", xalign=1), 0, 0, 1, 1)
        cn_spin = Gtk.SpinButton.new_with_range(0.5, 1.0, 0.05)
        cn_spin.set_value(0.85); cn_spin.set_digits(2)
        cn_spin.set_tooltip_text("How strictly to preserve the original structure/lines.\n0.85 = default. Higher = more faithful to B&W shapes, lower = more creative.")
        sgrid.attach(cn_spin, 1, 0, 1, 1)
        sgrid.attach(Gtk.Label(label="Denoise:", xalign=1), 0, 1, 1, 1)
        denoise_spin = Gtk.SpinButton.new_with_range(0.4, 0.7, 0.05)
        denoise_spin.set_value(0.55); denoise_spin.set_digits(2)
        denoise_spin.set_tooltip_text("How much color to add. Range: 0.4-0.7.\n0.4 = very subtle tinting, 0.55 = balanced (default), 0.7 = vivid colors.")
        sgrid.attach(denoise_spin, 1, 1, 1, 1)
        sgrid.attach(Gtk.Label(label="Seed:", xalign=1), 0, 2, 1, 1)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        sgrid.attach(seed_spin, 1, 2, 1, 1)
        bx.pack_start(sgrid, False, False, 0)
        # Prompt
        bx.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 60)
        prompt_tv.set_tooltip_text("Describe the colors you want. Default works well for natural photos.\nFor specific eras, try: '1970s color film, warm tones' or 'hand-tinted vintage'.")
        prompt_tv.get_buffer().set_text("vivid natural colors, photorealistic, color photograph, warm tones, lifelike colors")
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(60)
        bx.pack_start(sw, False, False, 0)
        # Negative
        bx.pack_start(Gtk.Label(label="Negative:", xalign=0), False, False, 0)
        neg_tv = Gtk.TextView(); neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        neg_tv.set_size_request(-1, 40)
        neg_tv.set_tooltip_text("List unwanted qualities. Keep 'black and white, grayscale' to prevent gray output.")
        neg_tv.get_buffer().set_text("black and white, grayscale, monochrome, desaturated, sepia, low quality")
        sw2 = Gtk.ScrolledWindow(); sw2.add(neg_tv); sw2.set_min_content_height(40)
        bx.pack_start(sw2, False, False, 0)
        # Runs spinner
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        bx.pack_start(runs_hb, False, False, 0)
        bx.show_all()
        last = _SESSION.get("colorize")
        if last:
            if "model_idx" in last:
                model_combo.set_active(last["model_idx"])
            if "cn_strength" in last:
                cn_spin.set_value(last["cn_strength"])
            if "denoise" in last:
                denoise_spin.set_value(last["denoise"])
            if "prompt" in last:
                prompt_tv.get_buffer().set_text(last["prompt"])
            if "negative" in last:
                neg_tv.get_buffer().set_text(last["negative"])
            if "runs" in last:
                runs_spin.set_value(last["runs"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        idx = model_combo.get_active()
        preset = dict(MODEL_PRESETS[idx] if idx >= 0 else MODEL_PRESETS[0])
        cn_strength = cn_spin.get_value()
        denoise = denoise_spin.get_value()
        base_seed = int(seed_spin.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        runs = int(runs_spin.get_value())
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        nbuf = neg_tv.get_buffer()
        negative = nbuf.get_text(nbuf.get_start_iter(), nbuf.get_end_iter(), False)
        _SESSION["colorize"] = {
            "model_idx": idx, "cn_strength": cn_strength, "denoise": denoise,
            "prompt": prompt, "negative": negative,
            "runs": runs,
        }
        dlg.destroy()
        try:
            Gimp.progress_init("Colorize: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_colorize_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_colorize(uname, preset, prompt, negative, seed,
                                      cn_strength, denoise)
                label = f"Colorize run {run_i+1}/{runs}" if runs > 1 else "Colorize"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Colorized run {run_i+1} #{i+1}" if runs > 1 else f"Colorized #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Colorize Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_batch_variations(self, procedure, run_mode, image, drawables, config, data):
        """Batch Variations: generate multiple txt2img outputs by setting batch_size > 1."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = PresetDialog("Spellcaster — Batch Variations (txt2img)", mode="txt2img")
        dlg.w_spin.set_value(image.get_width())
        dlg.h_spin.set_value(image.get_height())
        last = _SESSION.get("batch_variations")
        if last:
            dlg._apply_session(last)
        # Add batch count spinner to the dialog
        batch_frame = Gtk.Frame(label="Batch Variations")
        bhb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bhb.set_margin_start(8); bhb.set_margin_end(8)
        bhb.set_margin_top(8); bhb.set_margin_bottom(8)
        bhb.pack_start(Gtk.Label(label="Number of Variations:"), False, False, 0)
        batch_spin = Gtk.SpinButton.new_with_range(2, 8, 1)
        batch_spin.set_value(4)
        batch_spin.set_tooltip_text("Number of images to generate in one batch (2-8).\nAll variations use the same prompt but different noise. Higher = more VRAM.")
        bhb.pack_start(batch_spin, False, False, 0)
        batch_frame.add(bhb)
        batch_frame.show_all()
        dlg.get_content_area().pack_start(batch_frame, False, False, 0)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["batch_variations"] = dlg._collect_session()
        batch_count = int(batch_spin.get_value())
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            Gimp.progress_init("Batch Variations: generating on ComfyUI...")
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                     _build_txt2img(v["preset"], v["prompt"], v["negative"], seed, v.get("loras"))
                # Patch the EmptyLatentImage node to set batch_size
                for nid, node in wf.items():
                    if node.get("class_type") == "EmptyLatentImage":
                        node["inputs"]["batch_size"] = batch_count
                label = f"Batch Variations run {run_i+1}/{runs}" if runs > 1 else "Batch Variations"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Variation run {run_i+1} #{i+1}" if runs > 1 else f"Variation #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Batch Variations Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_iclight(self, procedure, run_mode, image, drawables, config, data):
        """IC-Light Relighting: change lighting direction on any photo (SD1.5 only)."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — IC-Light Relighting")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Relight", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # SD1.5 model dropdown (filtered to SD1.5 only)
        bx.pack_start(Gtk.Label(label="SD1.5 Checkpoint (IC-Light requires SD1.5):", xalign=0), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("SD1.5 checkpoint model. IC-Light only works with SD1.5 models.\nIf you don't see any, you need to install an SD1.5 checkpoint.")
        sd15_indices = []
        for i, p in enumerate(MODEL_PRESETS):
            if p["arch"] == "sd15":
                model_combo.append(str(i), p["label"])
                sd15_indices.append(i)
        if not sd15_indices:
            # Fallback: show all
            for i, p in enumerate(MODEL_PRESETS):
                model_combo.append(str(i), p["label"])
        model_combo.set_active(0)
        bx.pack_start(model_combo, False, False, 0)
        # Lighting preset dropdown
        bx.pack_start(Gtk.Label(label="Lighting Preset:", xalign=0), False, False, 0)
        light_combo = Gtk.ComboBoxText()
        light_combo.set_tooltip_text("Pre-configured lighting direction and style.\nEach preset auto-fills the prompt with appropriate lighting description.")
        for label in ICLIGHT_PRESETS:
            light_combo.append(label, label)
        light_combo.set_active(0)
        bx.pack_start(light_combo, False, False, 0)
        # Parameters
        sgrid = Gtk.Grid(column_spacing=12, row_spacing=6)
        sgrid.attach(Gtk.Label(label="Multiplier:", xalign=1), 0, 0, 1, 1)
        mult_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.02)
        mult_spin.set_value(0.18); mult_spin.set_digits(2)
        mult_spin.set_tooltip_text("IC-Light multiplier: controls lighting effect intensity.\nDefault: 0.18. Higher = stronger relight effect.")
        sgrid.attach(mult_spin, 1, 0, 1, 1)
        sgrid.attach(Gtk.Label(label="Steps:", xalign=1), 0, 1, 1, 1)
        steps_spin = Gtk.SpinButton.new_with_range(5, 50, 1)
        steps_spin.set_value(20)
        steps_spin.set_tooltip_text("Generation steps. Default: 20. More = better quality but slower.")
        sgrid.attach(steps_spin, 1, 1, 1, 1)
        sgrid.attach(Gtk.Label(label="Seed:", xalign=1), 0, 2, 1, 1)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        sgrid.attach(seed_spin, 1, 2, 1, 1)
        bx.pack_start(sgrid, False, False, 0)
        # Custom prompt override
        bx.pack_start(Gtk.Label(label="Prompt (auto-filled from lighting preset):", xalign=0), False, False, 0)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 50)
        prompt_tv.set_tooltip_text("Lighting description prompt. Auto-filled from lighting preset.\nCustomize to fine-tune the lighting effect.")
        # Fill prompt from first lighting preset
        first_key = list(ICLIGHT_PRESETS.keys())[0]
        prompt_tv.get_buffer().set_text(ICLIGHT_PRESETS[first_key])
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(50)
        bx.pack_start(sw, False, False, 0)
        # Runs spinner
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        bx.pack_start(runs_hb, False, False, 0)
        # Auto-update prompt when lighting preset changes
        def _on_light_changed(combo):
            key = combo.get_active_id()
            if key and key in ICLIGHT_PRESETS:
                prompt_tv.get_buffer().set_text(ICLIGHT_PRESETS[key])
        light_combo.connect("changed", _on_light_changed)
        bx.show_all()
        last = _SESSION.get("iclight")
        if last:
            if "model_id" in last:
                model_combo.set_active_id(last["model_id"])
            if "light_id" in last:
                light_combo.set_active_id(last["light_id"])
            if "multiplier" in last:
                mult_spin.set_value(last["multiplier"])
            if "steps" in last:
                steps_spin.set_value(last["steps"])
            if "prompt" in last:
                prompt_tv.get_buffer().set_text(last["prompt"])
            if "runs" in last:
                runs_spin.set_value(last["runs"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        idx = int(model_combo.get_active_id()) if model_combo.get_active_id() else 0
        ckpt_name = MODEL_PRESETS[idx]["ckpt"]
        multiplier = mult_spin.get_value()
        steps = int(steps_spin.get_value())
        base_seed = int(seed_spin.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        runs = int(runs_spin.get_value())
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        _SESSION["iclight"] = {
            "model_id": model_combo.get_active_id(),
            "light_id": light_combo.get_active_id(),
            "multiplier": multiplier, "steps": steps, "prompt": prompt,
            "runs": runs,
        }
        dlg.destroy()
        try:
            Gimp.progress_init("IC-Light: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_iclight_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_iclight(uname, ckpt_name, prompt, "", seed,
                                     multiplier, steps)
                label = f"IC-Light run {run_i+1}/{runs}" if runs > 1 else "IC-Light"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"IC-Light run {run_i+1} #{i+1}" if runs > 1 else f"IC-Light #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster IC-Light Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_supir(self, procedure, run_mode, image, drawables, config, data):
        """SUPIR AI Restoration: restore and enhance images using SUPIR model."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — SUPIR AI Restoration")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Restore", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        # SDXL model dropdown (SUPIR uses SDXL as its base)
        bx.pack_start(Gtk.Label(label="SDXL Base Model:", xalign=0), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("SDXL checkpoint model. SUPIR uses SDXL as its backbone.\nSelect the SDXL model that matches your content style.")
        for i, p in enumerate(MODEL_PRESETS):
            if p["arch"] == "sdxl":
                model_combo.append(str(i), p["label"])
        model_combo.set_active(0)
        bx.pack_start(model_combo, False, False, 0)
        # Parameters
        sgrid = Gtk.Grid(column_spacing=12, row_spacing=6)
        sgrid.attach(Gtk.Label(label="Denoise:", xalign=1), 0, 0, 1, 1)
        denoise_spin = Gtk.SpinButton.new_with_range(0.1, 1.0, 0.05)
        denoise_spin.set_value(0.3); denoise_spin.set_digits(2)
        denoise_spin.set_tooltip_text("Lower = more faithful to original, higher = more restoration.\nDefault: 0.3 (conservative). Try 0.5+ for heavily degraded images.")
        sgrid.attach(denoise_spin, 1, 0, 1, 1)
        sgrid.attach(Gtk.Label(label="Steps:", xalign=1), 0, 1, 1, 1)
        steps_spin = Gtk.SpinButton.new_with_range(10, 50, 1)
        steps_spin.set_value(20)
        steps_spin.set_tooltip_text("Generation steps. Default: 20. More = better quality but slower.\nSUPIR is already slow, so 20 is usually enough.")
        sgrid.attach(steps_spin, 1, 1, 1, 1)
        sgrid.attach(Gtk.Label(label="Seed:", xalign=1), 0, 2, 1, 1)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        sgrid.attach(seed_spin, 1, 2, 1, 1)
        bx.pack_start(sgrid, False, False, 0)
        # Prompt
        bx.pack_start(Gtk.Label(label="Positive Prompt:", xalign=0), False, False, 0)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 50)
        prompt_tv.set_tooltip_text("Describe the desired quality of the restored image.\nDefault works well. Add specific terms like 'portrait' or 'landscape' for better results.")
        prompt_tv.get_buffer().set_text("high quality, detailed, sharp focus, professional")
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(50)
        bx.pack_start(sw, False, False, 0)
        # Runs spinner
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        bx.pack_start(runs_hb, False, False, 0)
        bx.show_all()
        last = _SESSION.get("supir")
        if last:
            if "model_id" in last:
                model_combo.set_active_id(last["model_id"])
            if "denoise" in last:
                denoise_spin.set_value(last["denoise"])
            if "steps" in last:
                steps_spin.set_value(last["steps"])
            if "prompt" in last:
                prompt_tv.get_buffer().set_text(last["prompt"])
            if "runs" in last:
                runs_spin.set_value(last["runs"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        idx = int(model_combo.get_active_id()) if model_combo.get_active_id() else 0
        sdxl_model = MODEL_PRESETS[idx]["ckpt"]
        denoise = denoise_spin.get_value()
        steps = int(steps_spin.get_value())
        base_seed = int(seed_spin.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        runs = int(runs_spin.get_value())
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        _SESSION["supir"] = {
            "model_id": model_combo.get_active_id(),
            "denoise": denoise, "steps": steps, "prompt": prompt,
            "runs": runs,
        }
        dlg.destroy()
        try:
            Gimp.progress_init("SUPIR: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_supir_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_supir(uname, "Other\\SUPIR-v0Q_fp16.safetensors", sdxl_model,
                                   prompt, seed, denoise, steps)
                label = f"SUPIR run {run_i+1}/{runs}" if runs > 1 else "SUPIR"
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"SUPIR Restored run {run_i+1} #{i+1}" if runs > 1 else f"SUPIR Restored #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster SUPIR Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_rembg(self, procedure, run_mode, image, drawables, config, data):
        """Remove background: one-click, no settings needed.

        Uses the validated isnet-general-use model with alpha_matting=false.
        Result is a new layer with transparent background.
        """
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        # Minimal dialog — just server URL and Go button
        dlg = Gtk.Dialog(title="Spellcaster — Remove Background")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Remove Background", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        bx.pack_start(Gtk.Label(label="Removes background using isnet-general-use model.\nResult is a transparent PNG layer."), False, False, 4)
        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv); dlg.destroy()
        try:
            Gimp.progress_init("Remove Background: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_rembg_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_rembg(uname)
            Gimp.progress_set_text("Remove Background: processing on ComfyUI...")
            results = _run_with_spinner("Remove Background: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Background Removed #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Remove Background Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_send(self, procedure, run_mode, image, drawables, config, data):
        """Upload current canvas to ComfyUI's input folder (no generation)."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Upload to Spellcaster")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Upload", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        se.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        uname = f"gimp_upload_{uuid.uuid4().hex[:8]}.png"
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="Filename:"), False, False, 0)
        ne = Gtk.Entry(); ne.set_text(uname); ne.set_hexpand(True)
        ne.set_tooltip_text("Filename for the uploaded image on the ComfyUI server.\nAuto-generated with a unique ID to avoid overwriting.")
        hb2.pack_start(ne, True, True, 0); bx.pack_start(hb2, False, False, 0)
        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv); fn = ne.get_text().strip(); dlg.destroy()
        try:
            Gimp.progress_init("Uploading...")
            tmp = _export_image_to_tmp(image)
            r = _upload_image_sync(srv, tmp, fn); os.unlink(tmp)
            Gimp.message(f"Uploaded as: {r.get('name', fn)}")
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Upload Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_settings(self, procedure, run_mode, image, drawables, config, data):
        """Spellcaster Settings: configure server URL, defaults, and preferences."""
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        _apply_spellcaster_theme()
        dlg = Gtk.Dialog(title="Spellcaster Settings")
        dlg.set_default_size(520, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Save", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(dlg)
        bx = dlg.get_content_area()
        bx.set_spacing(10); bx.set_margin_start(16); bx.set_margin_end(16)
        bx.set_margin_top(16); bx.set_margin_bottom(16)

        # Header
        _make_branded_header(bx)

        # Load current config
        cfg = _load_config()

        # ── Server URL ──
        bx.pack_start(Gtk.Label(label="ComfyUI Server URL:", xalign=0), False, False, 0)
        server_entry = Gtk.Entry()
        server_entry.set_text(cfg.get("server_url", COMFYUI_DEFAULT_URL))
        server_entry.set_tooltip_text(
            "The URL of your ComfyUI server. This is saved permanently and used\n"
            "as the default for all Spellcaster dialogs.\n\n"
            "Local:  http://127.0.0.1:8188\n"
            "LAN:    http://192.168.x.x:8188\n"
            "Remote: http://your-server:8188")
        bx.pack_start(server_entry, False, False, 0)

        # Test connection button
        test_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        test_btn = Gtk.Button(label="Test Connection")
        test_status = Gtk.Label(label="")
        test_btn.set_tooltip_text("Send a test request to the ComfyUI server to verify connectivity.")
        def on_test(btn):
            url = server_entry.get_text().strip().rstrip("/")
            test_status.set_text("Testing...")
            try:
                req = urllib.request.Request(f"{url}/system_stats", method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    vram = data.get("devices", [{}])[0].get("vram_total", 0)
                    gpu = data.get("devices", [{}])[0].get("name", "Unknown")
                    if vram:
                        test_status.set_markup(f'<span foreground="#00E676">Connected: {gpu} ({vram//1024//1024//1024} GB)</span>')
                    else:
                        test_status.set_markup('<span foreground="#00E676">Connected</span>')
            except Exception as e:
                test_status.set_markup(f'<span foreground="#FF5252">Failed: {e}</span>')
        test_btn.connect("clicked", on_test)
        test_row.pack_start(test_btn, False, False, 0)
        test_row.pack_start(test_status, True, True, 0)
        bx.pack_start(test_row, False, False, 0)

        # ── Default timeout ──
        bx.pack_start(Gtk.Separator(), False, False, 5)
        bx.pack_start(Gtk.Label(label="Default Timeout (seconds):", xalign=0), False, False, 0)
        timeout_adj = Gtk.Adjustment(value=cfg.get("timeout", 300), lower=30, upper=3600, step_increment=30)
        timeout_spin = Gtk.SpinButton(adjustment=timeout_adj, digits=0)
        timeout_spin.set_tooltip_text(
            "Maximum time to wait for ComfyUI to finish a generation.\n"
            "Increase for slow hardware or complex workflows (e.g. video).\n"
            "Default: 300 seconds (5 minutes)")
        bx.pack_start(timeout_spin, False, False, 0)

        # ── Auto-update toggle ──
        bx.pack_start(Gtk.Separator(), False, False, 5)
        auto_update_cb = Gtk.CheckButton(label="Auto-update plugin from GitHub on startup")
        auto_update_cb.set_active(cfg.get("auto_update", True))
        auto_update_cb.set_tooltip_text(
            "When enabled, Spellcaster checks GitHub for updates every time\n"
            "GIMP starts. Disable if you have custom modifications you want\n"
            "to preserve, or if you have no internet connection.")
        bx.pack_start(auto_update_cb, False, False, 0)

        # ── Info ──
        bx.pack_start(Gtk.Separator(), False, False, 5)
        info_label = Gtk.Label()
        info_label.set_markup(
            f'<span size="small" foreground="#888888">'
            f'Config file: {os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")}\n'
            f'Current session URL: {COMFYUI_DEFAULT_URL}\n'
            f'Plugin version: Spellcaster v1.0'
            f'</span>')
        info_label.set_xalign(0)
        bx.pack_start(info_label, False, False, 0)

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        # Save settings
        new_url = server_entry.get_text().strip().rstrip("/")
        new_timeout = int(timeout_spin.get_value())
        new_auto_update = auto_update_cb.get_active()
        dlg.destroy()

        _save_config({
            "server_url": new_url,
            "timeout": new_timeout,
            "auto_update": new_auto_update,
        })
        _propagate_server_url(new_url)
        Gimp.message(f"Settings saved. Server: {new_url}")
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point — register the plugin with GIMP's procedure database
# ═══════════════════════════════════════════════════════════════════════════
# Gimp.main() is the GIMP 3 equivalent of calling register() in Script-Fu.
# It passes the GType of our PlugIn subclass so GIMP can instantiate it
# and call do_query_procedures / do_create_procedure at startup.
Gimp.main(Spellcaster.__gtype__, sys.argv)
