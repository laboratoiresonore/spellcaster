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

def _install_spellcaster_theme_to_disk():
    """Write spellcaster-theme.css as GIMP's user CSS override (gimp.css).

    GIMP 3.x loads gimp.css from the user config directory on every startup,
    applying it ON TOP of the selected color scheme (Dark Colors, etc.).
    This is the correct way to customize the full application appearance.

    Writes to all detected GIMP config versions (3.0, 3.2, etc.).
    """
    try:
        css_src = _PLUGIN_DIR / "spellcaster-theme.css"
        if not css_src.exists():
            return

        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            if not appdata:
                return
            gimp_base = Path(appdata) / "GIMP"
        else:
            gimp_base = Path.home() / ".config" / "GIMP"

        if not gimp_base.is_dir():
            return

        import shutil
        installed = False
        # Write gimp.css to ALL GIMP version directories found
        for version_dir in gimp_base.iterdir():
            if version_dir.is_dir() and version_dir.name[0].isdigit():
                dest = version_dir / "gimp.css"
                if not dest.exists() or css_src.stat().st_mtime > dest.stat().st_mtime:
                    shutil.copy2(css_src, dest)
                    installed = True
        if installed:
            print(f"[Spellcaster] Theme installed as gimp.css")
    except Exception as e:
        print(f"Note: Could not install persistent theme: {e}")


def _apply_spellcaster_theme():
    """Inject the Spellcaster premium dark CSS into GIMP's GTK3 environment.

    1. Load the full theme from spellcaster-theme.css (bundled next to this file).
    2. Apply it to the current GTK screen at APPLICATION priority.
    3. Also install the CSS to GIMP's user theme directory for persistence.
    """
    try:
        from gi.repository import Gdk, Gtk

        # --- Load from the bundled CSS file ---
        css_file = _PLUGIN_DIR / "spellcaster-theme.css"
        if css_file.exists():
            css = css_file.read_bytes()
        else:
            # Minimal fallback if the CSS file is missing
            css = b'''
            window, dialog { background-color: #0B0715; color: #E2DFEB; }
            label { color: #E2DFEB; }
            button { background-image: none; background-color: #1A1030; color: #E2DFEB;
                     border: 1px solid #3A2863; border-radius: 6px; }
            button:hover { background-color: #D122E3; color: white; }
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

    # Also install to GIMP's theme directory for persistence
    _install_spellcaster_theme_to_disk()


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

def _apply_staged_updates():
    """On startup, apply any .update files staged by a previous auto-update.

    On Windows, the running .py file cannot be replaced while GIMP has it loaded.
    The auto-updater writes the new version as 'filename.update' instead.
    This function (called before the updater runs) detects those staged files
    and performs the replacement before the old code is imported.
    """
    try:
        for staged in _PLUGIN_DIR.rglob("*.update"):
            target = staged.with_suffix("")  # remove .update suffix
            try:
                if target.exists():
                    target.unlink()
                staged.rename(target)
            except Exception:
                pass  # Will retry on next startup
    except Exception:
        pass

_apply_staged_updates()


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
      5. Download each via raw.githubusercontent.com
      6. If direct replace fails (Windows file locking), stage as .update
      7. Remove local files that no longer exist in the repo
      8. Write new SHA to .spellcaster_version
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
        staged = 0
        failed = 0
        remote_filenames = set()
        for rel_path in remote_files:
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
                try:
                    tmp.replace(dest)
                    updated += 1
                except PermissionError:
                    # Windows: file is locked by GIMP — stage for next startup
                    stage_path = dest.with_suffix(dest.suffix + ".update")
                    tmp.replace(stage_path)
                    staged += 1
            except Exception as e:
                failed += 1
                print(f"[Spellcaster] Failed to download {remainder}: {e}", file=_sys.stderr)

        # Step 5: Remove local files that no longer exist in the repo
        protected = {"config.json", ".spellcaster_version", "user_presets.json", "session_state.json"}
        for local_file in _PLUGIN_DIR.rglob("*"):
            if not local_file.is_file():
                continue
            rel = local_file.relative_to(_PLUGIN_DIR).as_posix()
            if rel in protected or local_file.name in protected \
               or local_file.name.endswith(".pyc") \
               or local_file.name.endswith(".update"):
                continue
            if rel not in remote_filenames:
                try:
                    local_file.unlink()
                except Exception:
                    pass

        # Step 6: Re-apply appearance assets if user opted in
        cfg = _load_config()
        if cfg.get("apply_theme", cfg.get("auto_update", True)):
            # Re-install gimp.css to all GIMP config dirs
            _install_spellcaster_theme_to_disk()

            # Update the banner GIF in the parent plugins/gimp/ directory
            banner_gif = _PLUGIN_DIR / "gimp_banner.gif"
            if not banner_gif.exists():
                banner_gif = _PLUGIN_DIR.parent / "gimp_banner.gif"
            parent_banner = _PLUGIN_DIR.parent / "gimp_banner.gif"
            if banner_gif.exists() and banner_gif != parent_banner:
                import shutil
                try:
                    shutil.copy2(banner_gif, parent_banner)
                except Exception:
                    pass

            # Re-apply system splash if the banner PNG exists
            banner_png = _PLUGIN_DIR.parent / "gimp_banner.png"
            if not banner_png.exists():
                banner_png = _PLUGIN_DIR / "gimp_banner.png"
            if banner_png.exists():
                # Find and replace GIMP system splash
                import shutil
                splash_candidates = []
                if _sys.platform == "win32":
                    for pf in [Path("C:/Program Files/GIMP 3"), Path("C:/Program Files (x86)/GIMP 3")]:
                        share = pf / "share" / "gimp" / "3.0" / "images"
                        if share.is_dir():
                            for f in share.glob("gimp-splash*.png"):
                                splash_candidates.append(f)
                for splash in splash_candidates:
                    if splash.exists():
                        try:
                            backup = splash.with_suffix(".orig" + splash.suffix)
                            if not backup.exists():
                                shutil.copy2(splash, backup)
                            shutil.copy2(banner_png, splash)
                        except (PermissionError, OSError):
                            pass
                        break

            # Re-apply custom icon
            icon_src = _PLUGIN_DIR / "spellcaster_icon.png"
            if icon_src.exists():
                if _sys.platform == "win32":
                    for pf in [Path("C:/Program Files/GIMP 3"), Path("C:/Program Files (x86)/GIMP 3")]:
                        for icon_name in ["gimp-logo.png", "wilber.png"]:
                            icon_path = pf / "share" / "gimp" / "3.0" / "images" / icon_name
                            if icon_path.exists():
                                try:
                                    import shutil
                                    backup = icon_path.with_suffix(".orig" + icon_path.suffix)
                                    if not backup.exists():
                                        shutil.copy2(icon_path, backup)
                                    shutil.copy2(icon_src, icon_path)
                                except (PermissionError, OSError):
                                    pass

        # Step 8: Record version and notify user
        if updated > 0 or staged > 0:
            _VERSION_FILE.write_text(latest_sha)
            sha7 = latest_sha[:7]
            msg = f"Spellcaster updated to {sha7} ({updated} files"
            if staged > 0:
                msg += f", {staged} staged for next restart"
            msg += ")."
            if failed > 0:
                msg += f"\n{failed} file(s) failed to download."
            if staged > 0:
                msg += "\nRestart GIMP to apply all updates (some files were in use)."
            else:
                msg += "\nRestart GIMP to use the new version."
            def _show_update_msg_once(m=msg):
                Gimp.message(m)
                return False
            GLib.idle_add(_show_update_msg_once)
    except Exception as e:
        print(f"[Spellcaster] Auto-update check failed: {e}", file=_sys.stderr)

# Fire-and-forget: runs once per GIMP session, daemon=True so it
# won't prevent GIMP from exiting. Guard prevents re-runs on module reload.
_auto_update_started = globals().get("_auto_update_started", False)
if not _auto_update_started:
    _auto_update_started = True
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
# the user's previous settings. Persisted to session_state.json on disk.
_SESSION_PATH = Path(__file__).parent / "session_state.json"

def _load_session():
    try:
        return json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_session():
    try:
        _SESSION_PATH.write_text(json.dumps(_SESSION, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass

def _session_to_values(key, image=None):
    """Reconstruct a get_values()-compatible dict from saved session state.

    Used by WITH_LAST_VALS (GIMP Repeat) to re-run without showing the dialog.
    Returns None if no session data exists for this key.
    """
    s = _SESSION.get(key)
    if not s:
        return None
    idx = s.get("model_preset_idx", 0)
    preset = dict(MODEL_PRESETS[idx] if 0 <= idx < len(MODEL_PRESETS) else MODEL_PRESETS[0])
    preset["steps"] = s.get("steps", preset["steps"])
    preset["cfg"] = s.get("cfg", preset["cfg"])
    preset["denoise"] = s.get("denoise", preset.get("denoise", 0.6))
    preset["width"] = s.get("width", image.get_width() if image else preset.get("width", 1024))
    preset["height"] = s.get("height", image.get_height() if image else preset.get("height", 1024))
    preset["sampler"] = s.get("sampler", preset["sampler"])
    preset["scheduler"] = s.get("scheduler", preset["scheduler"])
    seed = s.get("seed", -1)
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
    # Style preset recall
    style_preset = None
    prompt_text = s.get("prompt", preset.get("prompt_hint", ""))
    negative_text = s.get("negative", preset.get("negative_hint", ""))
    loras = s.get("loras", [])
    style_idx = s.get("style_idx", 0)
    if style_idx and 0 < style_idx < len(IMG2IMG_STYLE_PRESETS):
        style_preset = IMG2IMG_STYLE_PRESETS[style_idx]
        if style_preset["prompt"]:
            prompt_text = (prompt_text + ", " + style_preset["prompt"]) if prompt_text else style_preset["prompt"]
        if style_preset["negative"]:
            negative_text = (negative_text + ", " + style_preset["negative"]) if negative_text else style_preset["negative"]
        arch = preset.get("arch", "sdxl")
        style_loras = style_preset["loras"].get(arch, [])
        existing_names = {l["name"] for l in loras} if isinstance(loras, list) and loras else set()
        for lora_path, model_str, clip_str in style_loras:
            if lora_path not in existing_names:
                loras.append({
                    "name": lora_path,
                    "strength_model": model_str,
                    "strength_clip": clip_str,
                })

    return {
        "server": COMFYUI_DEFAULT_URL,
        "preset": preset,
        "prompt": prompt_text,
        "negative": negative_text,
        "seed": seed,
        "loras": loras,
        "controlnet": {
            "mode": s.get("cn_mode", "Off"),
            "strength": s.get("cn_strength", 0.8),
            "start_percent": s.get("cn_start", 0.0),
            "end_percent": s.get("cn_end", 1.0),
        },
        "controlnet_2": {
            "mode": s.get("cn_mode_2", "Off"),
            "strength": s.get("cn_strength_2", 0.6),
            "start_percent": 0.0,
            "end_percent": 1.0,
        },
        "custom_workflow": None,
        "runs": s.get("runs", 1),
        "style_preset": style_preset,
    }

_SESSION = _load_session()

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
        "ckpt": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
        "width": 1024, "height": 1024,
        "steps": 4, "cfg": 1.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Photograph of [subject], natural light, sharp focus, realistic skin texture",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Photo (quality)",
        "arch": "flux2klein",
        "ckpt": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 1.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Photograph of [subject], natural light, sharp focus, realistic skin texture",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Portrait",
        "arch": "flux2klein",
        "ckpt": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        "width": 896, "height": 1152,
        "steps": 20, "cfg": 1.0, "denoise": 0.60,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Portrait photograph of [person], 85mm lens, soft bokeh background, natural studio lighting, ultra-detailed skin texture, sharp eyes",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Artistic / Painterly",
        "arch": "flux2klein",
        "ckpt": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 1.0, "denoise": 0.72,
        "sampler": "euler", "scheduler": "beta",
        "prompt_hint": "Oil painting of [subject], dramatic lighting, expressive brushwork, rich colors, gallery quality",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Cinematic",
        "arch": "flux2klein",
        "ckpt": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        "width": 1280, "height": 720,
        "steps": 20, "cfg": 1.0, "denoise": 0.68,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "Cinematic still of [scene], anamorphic lens, golden hour light, shallow depth of field, film grain, 35mm",
        "negative_hint": "",
    },
    {
        "label": "Flux 2 Klein 9B — Inpaint / Refinement",
        "arch": "flux2klein",
        "ckpt": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
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
        "ckpt": "Flux-1-Dev\\flux1-schnell.safetensors",
        "width": 1024, "height": 1024,
        "steps": 4, "cfg": 1.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "simple",
        "prompt_hint": "A photograph of [subject], natural light, sharp focus",
        "negative_hint": "",
    },
    {
        "label": "Flux 1 Dev — Fill / Inpaint",
        "arch": "flux1dev",
        "ckpt": "Flux-1-Dev\\flux1-fill-dev.safetensors",
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
    # Both slash directions are checked by _filter_loras_for_arch().
    "sd15":         [],                                                      # no dedicated LoRA folders yet
    "sdxl":         ["SDXL\\", "Illustrious\\", "Illustrious-Pony\\", "Pony\\"],
    "zit":          ["Z-Image-Turbo\\"],
    "illustrious":  ["Illustrious\\", "Illustrious-Pony\\"],
    "flux2klein":   ["Flux-2-Klein\\"],
    "flux1dev":     ["Flux-1-Dev\\"],
    "flux_kontext": ["Flux-1-Dev\\"],                                        # Kontext can use Dev LoRAs
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
            "flux2klein": [("Flux-2-Klein\\BFS_head_v1_flux-klein_9b_rank128.safetensors", 0.8, 0.8)],
            "flux1dev":   [("Flux-1-Dev\\Detail/flux_face_detail.safetensors", 0.7, 0.7)],
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
            "flux2klein": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.7, 0.7)],
            "flux1dev":   [("Flux-1-Dev\\Detail/add_detail.safetensors", 0.7, 0.7)],
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
            "flux2klein": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.6, 0.6)],
            "flux1dev":   [("Flux-1-Dev\\Detail/add_detail.safetensors", 0.6, 0.6)],
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
            "flux2klein": [("Flux-2-Klein\\Sliders/klein_slider_anatomy_9B_v1.5.safetensors", 0.8, 0.8)],
            "flux1dev":   [("Flux-1-Dev\\Detail/add_detail.safetensors", 0.5, 0.5)],
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
            "flux2klein": [("Flux-2-Klein\\Sliders/klein_slider_anatomy_9B_v1.5.safetensors", 0.6, 0.6)],
            "flux1dev":   [("Flux-1-Dev\\Detail/add_detail.safetensors", 0.4, 0.4)],
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
            "flux2klein": [("Flux-2-Klein\\FTextureTransfer_F29B_V2.1.safetensors", 0.6, 0.6)],
            "flux1dev":   [("Flux-1-Dev\\Detail/add_detail.safetensors", 0.5, 0.5)],
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
            "flux2klein": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
            "flux1dev":   [("Flux-1-Dev\\Detail/add_detail.safetensors", 0.5, 0.5)],
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
            "flux2klein": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.8, 0.8)],
            "flux1dev":   [("Flux-1-Dev\\Detail/add_detail.safetensors", 0.8, 0.8)],
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
            "flux2klein": [("Flux-2-Klein\\ultra_real_v2.safetensors", 0.7, 0.7)],
            "flux1dev":   [("Flux-1-Dev\\Realism/flux_realism.safetensors", 0.7, 0.7)],
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
            "flux2klein": [("Flux-2-Klein\\FK4B_Image_Repair_V1.safetensors", 0.8, 0.8)],
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
            "flux2klein": [("Flux-2-Klein\\K9bSR3al.safetensors", 0.7, 0.7),
                           ("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
            "flux1dev":   [("Flux-1-Dev\\Realism/flux_realism.safetensors", 0.7, 0.7),
                           ("Flux-1-Dev\\Detail/add_detail.safetensors", 0.5, 0.5)],
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
            "flux2klein": [("Flux-2-Klein\\hipoly_3dcg_v7-epoch-000012.safetensors", 0.85, 0.85)],
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
            "flux2klein": [("Flux-2-Klein\\Sliders/klein_slider_glow.safetensors", 0.8, 0.8)],
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
            "flux2klein": [("Flux-2-Klein\\upscale_portrait_9bklein.safetensors", 0.8, 0.8),
                           ("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.4, 0.4)],
            "flux1dev":   [("Flux-1-Dev\\Detail/add_detail.safetensors", 0.6, 0.6)],
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
            "flux2klein": [("Flux-2-Klein\\Sliders/ColorTone_Standard.safetensors", 0.7, 0.7)],
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
            "flux2klein": [("Flux-2-Klein\\Character/Flux2Klein_AnythingtoRealCharacters.safetensors", 0.85, 0.85),
                           ("Flux-2-Klein\\K9bSR3al.safetensors", 0.5, 0.5)],
            "flux1dev":   [("Flux-1-Dev\\Realism/flux_realism.safetensors", 0.8, 0.8)],
            "flux_kontext": [],
        },
    },
]

# Style presets usable across img2img, txt2img, and inpaint
# References the ✦ presets from INPAINT_REFINEMENTS (style/effect based, not body-part fixes)
IMG2IMG_STYLE_PRESETS = [
    {"label": "(none — no style)", "prompt": "", "negative": "", "denoise": None,
     "cfg_boost": 0, "steps_override": None, "loras": {}},
] + [p for p in INPAINT_REFINEMENTS if p["label"].startswith("\u2726")]


def _filter_loras_for_arch(all_loras, arch):
    """Return only LoRAs whose full path starts with a compatible prefix.

    Checks both backslash and forward-slash variants of each prefix
    since ComfyUI may return either depending on the OS.
    """
    prefixes = ARCH_LORA_PREFIXES.get(arch, [])
    if not prefixes:
        return []
    result = []
    for lora in all_loras:
        for p in prefixes:
            # Check the prefix as-is AND with swapped slashes
            alt = p.replace("\\", "/") if "\\" in p else p.replace("/", "\\")
            if lora.startswith(p) or lora.startswith(alt):
                result.append(lora)
                break
    return result


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

    Returns LoRAs in Wan-related folders. Checks both slash directions
    since ComfyUI returns OS-native separators (backslash on Windows).
    """
    try:
        info = _api_get(server, "/object_info/LoraLoaderModelOnly")
        all_loras = info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0]
        prefixes = ["WAN\\", "WAN/", "Wan\\", "Wan/", "wan\\", "wan/",
                     "Wan-2.2-I2V\\", "Wan-2.2-I2V/"]
        return [l for l in all_loras if any(l.startswith(p) for p in prefixes)]
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

# ── Known ComfyUI error patterns for user-friendly messages ──────────
_KNOWN_ERRORS = {
    "value_not_in_list": "Model not found on the ComfyUI server.\n\nThe model file may not be installed, or the path may be incorrect.\nCheck ComfyUI's models/ directory.",
    "ckpt_name": "Checkpoint model not found.\n\nMake sure the model file exists in ComfyUI/models/checkpoints/.",
    "lora_name": "LoRA not found on the server.\n\nThe LoRA file may not be installed.\nCheck ComfyUI/models/loras/.",
    "unet_name": "UNet model not found.\n\nFor Flux/Klein models, check ComfyUI/models/unet/.",
    "control_net_name": "ControlNet model not found.\n\nDid you try using an SDXL ControlNet on an SD1.5 model (or vice versa)?\nEach architecture needs its own ControlNet.",
    "vae_name": "VAE model not found.\n\nCheck ComfyUI/models/vae/.",
    "required_input_missing": "A required node input is missing.\n\nThis usually means a custom node needs updating.\nTry: cd ComfyUI/custom_nodes/<node> && git pull",
}


def _parse_comfyui_error(error_body):
    """Parse ComfyUI error JSON and return a user-friendly message."""
    try:
        err = json.loads(error_body) if isinstance(error_body, str) else error_body
        node_errors = err.get("node_errors", {})
        messages = []
        for node_id, node_err in node_errors.items():
            for e in node_err.get("errors", []):
                etype = e.get("type", "")
                detail = e.get("details", "")
                extra = e.get("extra_info", {})
                input_name = extra.get("input_name", "")
                received = extra.get("received_value", "")

                # Match known error patterns
                friendly = None
                if etype == "value_not_in_list" and "controlnet" in input_name.lower():
                    friendly = f"ControlNet model mismatch!\n\nYou selected '{received}' but it's not available.\nDid you try using an SDXL ControlNet on an SD1.5 model?"
                elif etype == "value_not_in_list":
                    friendly = _KNOWN_ERRORS.get(input_name, _KNOWN_ERRORS.get("value_not_in_list", ""))
                    friendly += f"\n\nReceived: {received}"
                elif etype in _KNOWN_ERRORS:
                    friendly = _KNOWN_ERRORS[etype]

                if friendly:
                    messages.append(friendly)
                else:
                    messages.append(f"Node {node_id}: {etype} — {detail}")

        return "\n\n".join(messages) if messages else None
    except Exception:
        return None


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
        detail = e.read().decode("utf-8", errors="replace")
        # Try to parse a user-friendly message from ComfyUI's error JSON
        friendly = _parse_comfyui_error(detail) if e.code == 400 else None
        if friendly:
            raise RuntimeError(friendly) from e
        raise RuntimeError(f"HTTP {e.code} from {path}: {detail[:500]}") from e

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

    _update_spinner_status("Building selection mask (pixel scan)...")
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
    # Check for execution errors in the prompt result
    status = result.get("status", {})
    if status.get("status_str") == "error":
        msgs = status.get("messages", [])
        err_text = ""
        for msg_type, msg_data in msgs:
            if msg_type == "execution_error":
                err_text = msg_data.get("message", "") or msg_data.get("exception_message", "")
                node_type = msg_data.get("node_type", "")
                if node_type:
                    err_text = f"[{node_type}] {err_text}"
                break
        if err_text:
            raise RuntimeError(f"ComfyUI execution error: {err_text}")
        raise RuntimeError("ComfyUI workflow failed (no details available)")
    images = []
    for node_id, node_output in result.get("outputs", {}).items():
        for img in node_output.get("images", []):
            images.append((img["filename"], img.get("subfolder", ""), img.get("type", "output")))
        # VHS_VideoCombine outputs under "gifs", SaveVideo under "videos"
        for key in ("gifs", "videos"):
            for item in node_output.get(key, []):
                images.append((item["filename"], item.get("subfolder", ""), item.get("type", "output")))
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

# ── Model recommendation labels ──────────────────────────────────────
# Maps (task, architecture) to recommendation. Used to tag model dropdown labels.
_MODEL_RECOMMENDATIONS = {
    # Generic — recommended starters per arch
    "sdxl": "★ RECOMMENDED",
    "flux2klein": "★ next-gen",
    # Task-specific overrides
    ("img2img", "sdxl"): "★ RECOMMENDED",
    ("img2img", "flux2klein"): "★ next-gen quality",
    ("inpaint", "sdxl"): "★ RECOMMENDED",
    ("txt2img", "sdxl"): "★ RECOMMENDED",
    ("txt2img", "flux2klein"): "★ next-gen quality",
    ("hallucinate", "sdxl"): "★ RECOMMENDED for detail",
    ("seedv2r", "sdxl"): "★ RECOMMENDED",
    ("colorize", "sdxl"): "★ best for color",
    ("supir", "sdxl"): "★ REQUIRED (SDXL backbone)",
    ("style", "sdxl"): "★ RECOMMENDED",
    ("iclight", "sd15"): "★ REQUIRED (SD1.5 only)",
    ("face_restore", "sdxl"): "★ RECOMMENDED",
}

def _model_label(preset, task=None):
    """Return a model preset label with a recommendation tag if applicable."""
    label = preset["label"]
    arch = preset.get("arch", "")
    # Check task-specific first, then generic arch
    tag = _MODEL_RECOMMENDATIONS.get((task, arch)) if task else None
    if not tag:
        tag = _MODEL_RECOMMENDATIONS.get(arch)
    if tag:
        return f"{label}  {tag}"
    return label


def _ensure_mod16(wf, image_ref, preset, scale_node_id="4s"):
    """For Flux architectures, ensure image dimensions are divisible by 16.

    Flux ControlNet uses patch_size=2 on latents (latent = image/8).
    If latent dims are odd, einops rearrange fails with 'can't divide axis'.
    Solution: scale to nearest mod-16 dimensions.

    Returns the (possibly new) image reference to use downstream.
    """
    arch = preset.get("arch", "")
    if arch in ("flux1dev", "flux2klein", "flux_kontext"):
        # Add ImageScaleToTotalPixels which auto-rounds to mod-16
        # Using resolution_steps=16 ensures mod-16 output
        wf[scale_node_id] = {"class_type": "ImageScaleToTotalPixels",
                             "inputs": {
                                 "image": image_ref,
                                 "upscale_method": "nearest-exact",
                                 "megapixels": 1.0,
                                 "resolution_steps": 16,
                             }}
        return [scale_node_id, 0]
    return image_ref


def _make_model_loader(preset, node_id="1"):
    """Create the correct model/CLIP/VAE loader nodes based on architecture.

    Returns (wf_dict, model_ref, clip_ref, vae_ref).
    Handles: CheckpointLoaderSimple (sd15/sdxl/zit/illustrious),
             UNETLoader + CLIPLoader + VAELoader (flux2klein),
             UNETLoader + DualCLIPLoader + VAELoader (flux1dev/flux_kontext).
    """
    arch = preset.get("arch", "")
    if arch == "flux2klein":
        clip_name = "qwen_3_8b_fp8mixed.safetensors" if "9b" in preset["ckpt"].lower() else "qwen_3_4b.safetensors"
        wf = {
            node_id: {"class_type": "UNETLoader",
                      "inputs": {"unet_name": preset["ckpt"], "weight_dtype": "default"}},
            f"{node_id}b": {"class_type": "CLIPLoader",
                            "inputs": {"clip_name": clip_name, "type": "flux2", "device": "default"}},
            f"{node_id}c": {"class_type": "VAELoader",
                            "inputs": {"vae_name": "flux2-vae.safetensors"}},
        }
        return wf, [node_id, 0], [f"{node_id}b", 0], [f"{node_id}c", 0]
    elif arch in ("flux1dev", "flux_kontext"):
        wf = {
            node_id: {"class_type": "UNETLoader",
                      "inputs": {"unet_name": preset["ckpt"], "weight_dtype": "default"}},
            f"{node_id}b": {"class_type": "DualCLIPLoader",
                            "inputs": {"clip_name1": "clip_l.safetensors",
                                       "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                                       "type": "flux"}},
            f"{node_id}c": {"class_type": "VAELoader",
                            "inputs": {"vae_name": "ae.safetensors"}},
        }
        return wf, [node_id, 0], [f"{node_id}b", 0], [f"{node_id}c", 0]
    else:
        wf = {
            node_id: {"class_type": "CheckpointLoaderSimple",
                      "inputs": {"ckpt_name": preset["ckpt"]}},
        }
        return wf, [node_id, 0], [node_id, 1], [node_id, 2]


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


# ── LoRA metadata: trigger words and optimal strengths ───────────────────
# Maps known LoRA basenames to their trigger words and recommended strengths.
# Used by the UI to auto-fill prompt tags and strength spinners when a LoRA
# is selected from the combo box.
LORA_METADATA = {
    "HandFineTuning_XL.safetensors": {"trigger": "perfect hands, detailed fingers", "strength": 0.85},
    "hand 5.5.safetensors": {"trigger": "perfect hands, detailed fingers", "strength": 0.60},
    "Eyes_High_Definition-000007.safetensors": {"trigger": "detailed eyes, sharp iris", "strength": 0.80},
    "RealSkin_xxXL_v1.safetensors": {"trigger": "realistic skin texture, detailed pores", "strength": 0.70},
    "ghibli_last.safetensors": {"trigger": "ghibli style, anime painting", "strength": 0.85},
    "epiCPhotoXL-Derp2.safetensors": {"trigger": "epic photo, cinematic", "strength": 0.60},
    "K9bSh4rpD3tails.safetensors": {"trigger": "sharp details, high resolution", "strength": 0.70},
    "K9bSR3al.safetensors": {"trigger": "realistic, photorealistic", "strength": 0.70},
    "Wonderful_Details_XL_V1a.safetensors": {"trigger": "wonderful details, intricate", "strength": 0.65},
    "Teefs-000007.safetensors": {"trigger": "perfect teeth, natural smile", "strength": 0.90},
    "skin texture style v4.safetensors": {"trigger": "skin texture, detailed pores", "strength": 0.75},
    "RawCam_250_v1.safetensors": {"trigger": "raw photo, camera grain", "strength": 0.80},
    "epicNewPhoto.safetensors": {"trigger": "epic photo, natural lighting", "strength": 0.40},
    "SDXLFaeTastic2400.safetensors": {"trigger": "faetastic, fairy tale, fantasy art", "strength": 0.85},
    "err0rFv1.6.safetensors": {"trigger": "glitch art, digital error", "strength": 0.85},
    "rdtdrp.safetensors": {"trigger": "realistic details, fine textures", "strength": 0.50},
    "epiCRealnessRC1.safetensors": {"trigger": "epic realism, photorealistic", "strength": 0.80},
    "sd_xl_offset_example-lora_1.0.safetensors": {"trigger": "offset noise, high contrast", "strength": 0.60},
    "polyhedron_all_sdxl-000004.safetensors": {"trigger": "polyhedron style, 3D render", "strength": 0.70},
    "zy_AmateurStyle_v2.safetensors": {"trigger": "amateur photo style, casual snapshot", "strength": 0.85},
    "Aliens_AILF_SDXL.safetensors": {"trigger": "alien creature, extraterrestrial", "strength": 0.85},
    "Space_ship_concept.safetensors": {"trigger": "spaceship concept, sci-fi vehicle", "strength": 0.85},
    "Oily skin style xl v1.safetensors": {"trigger": "oily skin, glossy skin", "strength": 0.85},
    "Sweating my balls of mate.safetensors": {"trigger": "sweaty skin, perspiration", "strength": 0.80},
    "ARobotGirls_Concept-12.safetensors": {"trigger": "robot girl, cyborg, mechanical parts", "strength": 0.85},
    "BFS_head_v1_flux-klein_9b_rank128.safetensors": {"trigger": "detailed face, portrait", "strength": 0.80},
    "flux_face_detail.safetensors": {"trigger": "detailed face, portrait", "strength": 0.70},
    "add_detail.safetensors": {"trigger": "detailed, high quality", "strength": 0.70},
    "flux_realism.safetensors": {"trigger": "realistic, photorealistic", "strength": 0.70},
    "klein_slider_anatomy_9B_v1.5.safetensors": {"trigger": "correct anatomy, proportional", "strength": 0.80},
    "FTextureTransfer_F29B_V2.1.safetensors": {"trigger": "texture transfer, detailed surface", "strength": 0.60},
    "ultra_real_v2.safetensors": {"trigger": "ultra realistic, photorealistic", "strength": 0.70},
    "FK4B_Image_Repair_V1.safetensors": {"trigger": "image repair, restoration", "strength": 0.80},
    "upscale_portrait_9bklein.safetensors": {"trigger": "upscale portrait, sharp details", "strength": 0.80},
    "hipoly_3dcg_v7-epoch-000012.safetensors": {"trigger": "3D CG, high poly render", "strength": 0.85},
    "Flux2Klein_AnythingtoRealCharacters.safetensors": {"trigger": "realistic character, photorealistic portrait", "strength": 0.85},
    "ColorTone_Standard.safetensors": {"trigger": "color tone, color grading", "strength": 0.70},
    "klein_slider_glow.safetensors": {"trigger": "glowing, radiant light", "strength": 0.80},
    "HyperdetailedRealismMJ7Pony.safetensors": {"trigger": "hyperdetailed, photorealistic", "strength": 0.80},
    "StS_PonyXL_Detail_Slider_v1.4_iteration_3.safetensors": {"trigger": "sharp details, high resolution", "strength": 0.70},
    "Ethereal_Gothic_Elegance.safetensors": {"trigger": "ethereal gothic, dark elegance", "strength": 0.85},
    "dark.safetensors": {"trigger": "dark mood, moody atmosphere", "strength": 0.50},
    "Chiaroscuro  film style pony v1.safetensors": {"trigger": "chiaroscuro, dramatic lighting", "strength": 0.85},
    "Dramatic Lighting Slider.safetensors": {"trigger": "dramatic lighting, high contrast", "strength": 0.60},
    "Cinematic Photography Style pony v1.safetensors": {"trigger": "cinematic photo, film still", "strength": 0.80},
    "MetallicGoldSilver_skinbody_paint-000019.safetensors": {"trigger": "metallic skin, gold silver body paint", "strength": 0.90},
    "OiledSkin_Zit_Turbo_V1.safetensors": {"trigger": "oily skin, glossy skin", "strength": 0.85},
    "water_droplet_effect_zit_v1.safetensors": {"trigger": "water droplets, wet skin", "strength": 0.90},
    "93PXB5SENBFN8NEYSRYZA1DVX0-Chrome skin.safetensors": {"trigger": "chrome skin, metallic surface", "strength": 0.90},
    "Z-cyborg.safetensors": {"trigger": "cyborg, mechanical parts, robotic", "strength": 0.90},
    "zy_CinematicShot_zit.safetensors": {"trigger": "cinematic shot, film still", "strength": 0.70},
    "SonyAlpha_ZImage.safetensors": {"trigger": "Sony Alpha photo, camera raw", "strength": 0.80},
    "600mm_Lens-V2_TriggerIs_600mm.safetensors": {"trigger": "600mm, telephoto lens, bokeh", "strength": 0.90},
    "ZiTD3tailed4nime.safetensors": {"trigger": "detailed anime, anime style", "strength": 0.80},
    "z-image-illustria-01.safetensors": {"trigger": "illustration style, digital art", "strength": 0.70},
    "EFFECTSp001_zit.safetensors": {"trigger": "special effects, digital glitch", "strength": 0.70},
    "Z-Image-Professional_Photographer_3500.safetensors": {"trigger": "professional photo, studio lighting", "strength": 0.70},
    "feet v2.1.safetensors": {"trigger": "detailed feet, correct toes", "strength": 0.80},
    "Tentacledv1.safetensors": {"trigger": "tentacles, organic tendrils", "strength": 0.85},
}


def _build_img2img(image_filename, preset, prompt_text, negative_text, seed,
                    loras=None, controlnet=None, controlnet_2=None):
    """Standard img2img: load checkpoint, encode image to latent, denoise, decode.

    Pipeline: CheckpointLoaderSimple → [LoRA chain] → CLIPTextEncode(+/-)
              LoadImage → [WD14Tagger → StringConcatenate] → VAEEncode → KSampler → VAEDecode → SaveImage
    For flux1dev: UNETLoader + CLIPLoader + VAELoader (Flux uses separate loaders).
    Optional WD Tagger auto-tags the input image and prepends tags to the prompt.
    Optional ControlNet injection adds preprocessor + ControlNetApplyAdvanced.
    """
    wf, model_ref, clip_ref, vae_ref = _make_model_loader(preset, "1")

    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], model_ref[0], model_ref=model_ref, clip_ref=clip_ref)

    # Determine the final positive prompt source
    pos_prompt_text = prompt_text

    wf["4"] = {"class_type": "LoadImage",
              "inputs": {"image": image_filename}}
    # Flux ControlNet needs mod-16 dimensions
    img_ref = _ensure_mod16(wf, ["4", 0], preset, "4s")

    wf.update({
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "5": {"class_type": "VAEEncode",
              "inputs": {"pixels": img_ref, "vae": vae_ref}},
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
        if cn_model:
            preprocessor = guide["preprocessor"]

            cn_image_ref = img_ref  # mod-16 scaled for Flux
            if preprocessor:
                wf["20"] = {"class_type": preprocessor,
                            "inputs": {"image": img_ref}}
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

            # Save ControlNet preprocessor output as debug image (if enabled)
            if cn_image_ref != ["4", 0] and _load_config().get("debug_images", False):
                wf["25"] = {"class_type": "SaveImage",
                            "inputs": {"images": cn_image_ref, "filename_prefix": "spellcaster_cn_debug"}}

    # ── ControlNet 2 injection (optional second guide, chained) ─────
    if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        guide2 = CONTROLNET_GUIDE_MODES[controlnet_2["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model_2 = guide2["cn_models"].get(arch, guide2["cn_models"].get("sdxl"))
        if cn_model_2:
            preprocessor_2 = guide2["preprocessor"]

            cn_image_ref_2 = ["4", 0]
            if preprocessor_2:
                wf["30"] = {"class_type": preprocessor_2,
                            "inputs": {"image": ["4", 0]}}
                cn_image_ref_2 = ["30", 0]

            wf["31"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model_2}}

            # Determine what CN2 chains from: CN1 output if active, else raw CLIP
            cn2_pos_ref = ["22", 0] if "22" in wf else ["2", 0]
            cn2_neg_ref = ["22", 1] if "22" in wf else ["3", 0]

            wf["32"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": cn2_pos_ref,
                            "negative": cn2_neg_ref,
                            "control_net": ["31", 0],
                            "image": cn_image_ref_2,
                            "strength": controlnet_2["strength"],
                            "start_percent": controlnet_2.get("start_percent", 0.0),
                            "end_percent": controlnet_2.get("end_percent", 1.0),
                        }}

            # Redirect KSampler to use the chained output
            wf["6"]["inputs"]["positive"] = ["32", 0]
            wf["6"]["inputs"]["negative"] = ["32", 1]

    return wf


def _build_txt2img(preset, prompt_text, negative_text, seed, loras=None):
    """Text-to-image: generate from empty latent (no input image).

    Same as img2img but uses EmptyLatentImage instead of VAEEncode,
    and denoise is always 1.0 (full generation from noise).
    For flux1dev: uses UNETLoader + DualCLIPLoader + VAELoader.
    """
    wf, model_ref, clip_ref, vae_ref = _make_model_loader(preset, "1")

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

def _build_inpaint(image_filename, mask_filename, preset, prompt_text, negative_text, seed, loras=None, controlnet=None, controlnet_2=None):
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
    wf, model_ref, clip_ref, vae_ref = _make_model_loader(preset, "1")
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "1", model_ref=model_ref, clip_ref=clip_ref)

    wf["4"] = {"class_type": "LoadImage", "inputs": {"image": image_filename}}
    img_ref = _ensure_mod16(wf, ["4", 0], preset, "4s")
    wf["5"] = {"class_type": "LoadImage", "inputs": {"image": mask_filename}}

    wf["2"] = {"class_type": "CLIPTextEncode",
                   "inputs": {"text": prompt_text, "clip": clip_ref}}

    wf.update({
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        # Convert the grayscale mask IMAGE to a MASK tensor.
        # LoadImage output [1] is the alpha channel (all-zero if no alpha!).
        # We need output [0] (the actual pixels) → ImageToMask → red channel.
        "51": {"class_type": "ImageToMask",
               "inputs": {"image": ["5", 0], "channel": "red"}},
        # Get original image size for restoring after sampling
        "90": {"class_type": "GetImageSize+",
               "inputs": {"image": img_ref}},
        # Scale image to working resolution
        "91": {"class_type": "ImageScale",
               "inputs": {"image": img_ref, "upscale_method": "lanczos",
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
              "inputs": {"pixels": ["91", 0], "vae": vae_ref}},
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
              "inputs": {"samples": ["8", 0], "vae": vae_ref}},
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
        if cn_model:
            preprocessor = guide["preprocessor"]

            cn_image_ref = img_ref  # LoadImage output (mod-16 scaled if Flux)
            if preprocessor:
                wf["20"] = {"class_type": preprocessor,
                            "inputs": {"image": img_ref}}
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

            # Save ControlNet preprocessor output as debug image (if enabled)
            if cn_image_ref != img_ref and _load_config().get("debug_images", False):
                wf["25"] = {"class_type": "SaveImage",
                            "inputs": {"images": cn_image_ref, "filename_prefix": "spellcaster_cn_debug"}}

    # ── ControlNet 2 injection (optional second guide, chained) ─────
    if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        guide2 = CONTROLNET_GUIDE_MODES[controlnet_2["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model_2 = guide2["cn_models"].get(arch, guide2["cn_models"].get("sdxl"))
        if cn_model_2:
            preprocessor_2 = guide2["preprocessor"]

            cn_image_ref_2 = img_ref
            if preprocessor_2:
                wf["30"] = {"class_type": preprocessor_2,
                            "inputs": {"image": img_ref}}
                cn_image_ref_2 = ["30", 0]

            wf["31"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model_2}}

            # Determine what CN2 chains from: CN1 output if active, else raw CLIP
            cn2_pos_ref = ["22", 0] if "22" in wf else ["2", 0]
            cn2_neg_ref = ["22", 1] if "22" in wf else ["3", 0]

            wf["32"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": cn2_pos_ref,
                            "negative": cn2_neg_ref,
                            "control_net": ["31", 0],
                            "image": cn_image_ref_2,
                            "strength": controlnet_2["strength"],
                            "start_percent": controlnet_2.get("start_percent", 0.0),
                            "end_percent": controlnet_2.get("end_percent", 1.0),
                        }}

            # Redirect KSampler to use the chained output
            wf["8"]["inputs"]["positive"] = ["32", 0]
            wf["8"]["inputs"]["negative"] = ["32", 1]

    # NOTE: When ControlNet is active for inpaint, the preprocessor receives
    # the FULL image (node "4") so it can analyze the complete body pose/structure.
    # The mask (node "52") controls which area gets regenerated by KSampler.
    # This is correct behavior — ControlNet sees full context, inpaint mask
    # limits the region of change.

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
    "(none — no upscale)": None,
    "4x UltraSharp (general)": "4x-UltraSharp.pth",
    "4x RealESRGAN (photo)": "RealESRGAN_x4plus.pth",
    "4x NMKD Superscale (sharp)": "4x_NMKD-Superscale-SP_178000_G.pth",
    "4x Remacri (restoration)": "4x_foolhardy_Remacri.pth",
    "4x RealESRGAN Anime": "RealESRGAN_x4plus_anime_6B.pth",
    "8x NMKD Faces (portraits)": "8x_NMKD-Faces_160000_G.pth",
}

def _build_upscale(image_filename, model_name, upscale_factor=1.0):
    """Upscale image using a super-resolution model with controllable factor.

    Pipeline: LoadImage → UpscaleModelLoader → ImageUpscaleWithModelByFactor → SaveImage

    upscale_factor (default 1.5): Controls output scale. Unlike the native 4x/8x
    model output, this lets you choose any factor (e.g. 1.5x, 2x, 3x).
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": model_name}},
        "3": {"class_type": "ImageUpscaleWithModelByFactor",
              "inputs": {
                  "upscale_model": ["2", 0],
                  "image": ["1", 0],
                  "scale_by": upscale_factor,
              }},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "spellcaster_upscale"}},
    }
    return wf


# ── LaMa Object Removal (selection-based inpainting without diffusion) ─

def _build_lama_remove(image_filename, mask_filename):
    """Remove objects using LaMa inpainting — no checkpoint, no prompt needed.

    Pipeline: LoadImage(image) → LoadImage(mask) → ImageToMask → LamaRemover → SaveImage
    Uses LamaRemover (from ComfyUI-LaMA-Preprocessor) instead of the
    broken LaMaInpaint (from comfyui-art-venture which crashes on recent PyTorch).
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": mask_filename}},
        "5": {"class_type": "ImageToMask",
              "inputs": {"image": ["2", 0], "channel": "red"}},
        "3": {"class_type": "LamaRemover",
              "inputs": {
                  "images": ["1", 0],
                  "masks": ["5", 0],
                  "mask_threshold": 0.5,
                  "gaussblur_radius": 8,
                  "invert_mask": False,
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
                     left, top, right, bottom, feathering, loras=None,
                     controlnet=None):
    """Outpaint: extend the canvas by padding and inpainting the new area.

    Two pipelines depending on architecture:

    Flux 2 Klein (★ RECOMMENDED — best outpaint quality):
      LoadImage → ImagePadForOutpaint → VAEEncode → ReferenceLatent
      → CLIPLoader(flux2) → CLIPTextEncode → ConditioningZeroOut
      → ReferenceLatent(pos) + ReferenceLatent(neg) → CFGGuider
      → Flux2Scheduler → EmptyFlux2LatentImage → SamplerCustomAdvanced
      → VAEDecode → SaveImage
      Uses ReferenceLatent to "show" Flux the existing content so it
      generates seamless continuation. SetLatentNoiseMask ensures only
      the new area is generated.

    Standard (SD1.5/SDXL/etc):
      LoadImage → ImagePadForOutpaint → VAEEncode → SetLatentNoiseMask
      → KSampler(denoise=0.85) → VAEDecode → SaveImage
    """
    arch = preset.get("arch", "sdxl")
    is_klein = arch == "flux2klein"

    loader_wf, model_ref, clip_ref, vae_ref = _make_model_loader(preset, "1")
    wf = dict(loader_wf)
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "1", model_ref, clip_ref)

    # Common: load image and pad
    wf["4"] = {"class_type": "LoadImage", "inputs": {"image": image_filename}}
    wf["5"] = {"class_type": "ImagePadForOutpaint", "inputs": {
        "image": ["4", 0], "left": left, "top": top,
        "right": right, "bottom": bottom, "feathering": feathering,
    }}

    padded_ref = _ensure_mod16(wf, ["5", 0], preset, "5s")

    if is_klein:
        # ── Flux 2 Klein outpaint pipeline ──────────────────────────────
        # Uses SamplerCustomAdvanced (the correct Flux2 pipeline) with
        # ReferenceLatent for context. Then composites the original image
        # back over the non-extension area to prevent any gray/noise.
        wf["6"] = {"class_type": "VAEEncode",
                   "inputs": {"pixels": padded_ref, "vae": vae_ref}}

        wf["2"] = {"class_type": "CLIPTextEncode",
                   "inputs": {"text": prompt_text, "clip": clip_ref}}
        wf["3"] = {"class_type": "ConditioningZeroOut",
                   "inputs": {"conditioning": ["2", 0]}}

        # ReferenceLatent gives Klein context of the existing image
        wf["20"] = {"class_type": "ReferenceLatent",
                    "inputs": {"conditioning": ["2", 0], "latent": ["6", 0]}}
        wf["21"] = {"class_type": "ReferenceLatent",
                    "inputs": {"conditioning": ["3", 0], "latent": ["6", 0]}}

        # Get padded image dimensions
        wf["25"] = {"class_type": "GetImageSize+",
                    "inputs": {"image": padded_ref}}

        # Flux 2 sampling pipeline
        wf["30"] = {"class_type": "CFGGuider",
                    "inputs": {"model": model_ref, "positive": ["20", 0],
                               "negative": ["21", 0], "cfg": 1.0}}
        wf["31"] = {"class_type": "KSamplerSelect",
                    "inputs": {"sampler_name": "euler"}}
        wf["32"] = {"class_type": "Flux2Scheduler",
                    "inputs": {"steps": preset.get("steps", 20), "denoise": 1.0,
                               "width": ["25", 0], "height": ["25", 1]}}
        wf["33"] = {"class_type": "RandomNoise",
                    "inputs": {"noise_seed": seed}}
        wf["34"] = {"class_type": "EmptyFlux2LatentImage",
                    "inputs": {"width": ["25", 0], "height": ["25", 1],
                               "batch_size": 1}}

        # Sample from empty latent — generates the full image
        wf["40"] = {"class_type": "SamplerCustomAdvanced",
                    "inputs": {"noise": ["33", 0], "guider": ["30", 0],
                               "sampler": ["31", 0], "sigmas": ["32", 0],
                               "latent_image": ["34", 0]}}

        # Decode the AI result
        wf["9"] = {"class_type": "VAEDecode",
                   "inputs": {"samples": ["40", 0], "vae": vae_ref}}

        # Composite: paste the original padded image back over the
        # non-extension area using the inverted outpaint mask.
        # mask from ImagePadForOutpaint: white = new area, black = original
        # InvertMask: white = original area (paste source here)
        wf["9m"] = {"class_type": "InvertMask",
                    "inputs": {"mask": ["5", 1]}}
        wf["9c"] = {"class_type": "ImageCompositeMasked",
                    "inputs": {"destination": ["9", 0], "source": padded_ref,
                               "mask": ["9m", 0], "x": 0, "y": 0,
                               "resize_source": False}}
        wf["10"] = {"class_type": "SaveImage",
                    "inputs": {"images": ["9c", 0], "filename_prefix": "spellcaster_outpaint"}}

    else:
        # ── Standard outpaint pipeline (SD1.5/SDXL/etc) ────────────────
        wf.update({
            "2": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": prompt_text, "clip": clip_ref}},
            "3": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": negative_text, "clip": clip_ref}},
            "6": {"class_type": "VAEEncode",
                  "inputs": {"pixels": padded_ref, "vae": vae_ref}},
            "7": {"class_type": "SetLatentNoiseMask",
                  "inputs": {"samples": ["6", 0], "mask": ["5", 1]}},
            "8": {"class_type": "KSampler",
                  "inputs": {
                      "model": model_ref, "positive": ["2", 0], "negative": ["3", 0],
                      "latent_image": ["7", 0], "seed": seed,
                      "steps": preset["steps"], "cfg": preset["cfg"],
                      "sampler_name": preset["sampler"], "scheduler": preset["scheduler"],
                      "denoise": 0.85,
                  }},
            "9": {"class_type": "VAEDecode",
                  "inputs": {"samples": ["8", 0], "vae": vae_ref}},
            "10": {"class_type": "SaveImage",
                   "inputs": {"images": ["9", 0], "filename_prefix": "spellcaster_outpaint"}},
        })

    # ── ControlNet (optional — Canny/Lineart for edge consistency) ──
    if controlnet and controlnet.get("mode", "Off") != "Off":
        guide = CONTROLNET_GUIDE_MODES[controlnet["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model = guide["cn_models"].get(arch, guide["cn_models"].get("sdxl"))
        if cn_model:
            preprocessor = guide["preprocessor"]

            # ControlNet processes the padded image (mod-16 scaled if Flux)
            cn_image_ref = padded_ref
            if preprocessor:
                wf["20"] = {"class_type": preprocessor,
                            "inputs": {"image": padded_ref}}
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
                            "start_percent": controlnet.get("start_percent", 0.0),
                            "end_percent": controlnet.get("end_percent", 1.0),
                        }}
            wf["8"]["inputs"]["positive"] = ["22", 0]
            wf["8"]["inputs"]["negative"] = ["22", 1]

    return wf


# ── Style Transfer / IPAdapter ────────────────────────────────────────

def _build_style_transfer(target_filename, style_ref_filename, preset,
                           prompt_text, negative_text, seed,
                           ipadapter_preset="PLUS (high strength)",
                           weight=0.8, denoise=0.6,
                           controlnet=None, controlnet_2=None):
    """Style transfer using IPAdapter — applies the style of a reference image.

    Pipeline: CheckpointLoaderSimple → IPAdapterUnifiedLoader → LoadImage(style ref)
              → IPAdapterAdvanced(weight_type="style transfer") → LoadImage(target)
              → CLIPTextEncode x2 → [ControlNet 1] → [ControlNet 2]
              → VAEEncode → KSampler → VAEDecode → SaveImage
    """
    loader_wf, model_ref, clip_ref, vae_ref = _make_model_loader(preset, "1")
    wf = dict(loader_wf)
    wf.update({
        "2": {"class_type": "IPAdapterUnifiedLoader",
              "inputs": {
                  "model": model_ref,
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
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text or "blurry, deformed, bad anatomy", "clip": clip_ref}},
        "7": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
    })
    target_ref = _ensure_mod16(wf, ["7", 0], preset, "7s")
    wf.update({
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": target_ref, "vae": vae_ref}},
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
               "inputs": {"samples": ["9", 0], "vae": vae_ref}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": "spellcaster_style"}},
    })

    # ── ControlNet 1 (optional — Depth/Canny preserves structure) ──
    if controlnet and controlnet.get("mode", "Off") != "Off":
        guide = CONTROLNET_GUIDE_MODES[controlnet["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model = guide["cn_models"].get(arch, guide["cn_models"].get("sdxl"))
        if cn_model:
            preprocessor = guide["preprocessor"]

            cn_image_ref = target_ref  # target image (mod-16 scaled if Flux)
            if preprocessor:
                wf["20"] = {"class_type": preprocessor,
                            "inputs": {"image": target_ref}}
                cn_image_ref = ["20", 0]

            wf["21"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model}}
            wf["22"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": ["5", 0],
                            "negative": ["6", 0],
                            "control_net": ["21", 0],
                            "image": cn_image_ref,
                            "strength": controlnet["strength"],
                            "start_percent": controlnet.get("start_percent", 0.0),
                            "end_percent": controlnet.get("end_percent", 1.0),
                        }}
            wf["9"]["inputs"]["positive"] = ["22", 0]
            wf["9"]["inputs"]["negative"] = ["22", 1]

    # ── ControlNet 2 (optional) ──
    if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        guide2 = CONTROLNET_GUIDE_MODES[controlnet_2["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model_2 = guide2["cn_models"].get(arch, guide2["cn_models"].get("sdxl"))
        if cn_model_2:
            preprocessor_2 = guide2["preprocessor"]

            cn_image_ref_2 = target_ref
            if preprocessor_2:
                wf["30"] = {"class_type": preprocessor_2,
                            "inputs": {"image": target_ref}}
                cn_image_ref_2 = ["30", 0]

            wf["31"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model_2}}
            prev_pos = ["22", 0] if "22" in wf else ["5", 0]
            prev_neg = ["22", 1] if "22" in wf else ["6", 0]
            wf["32"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": prev_pos,
                            "negative": prev_neg,
                            "control_net": ["31", 0],
                            "image": cn_image_ref_2,
                            "strength": controlnet_2["strength"],
                            "start_percent": controlnet_2.get("start_percent", 0.0),
                            "end_percent": controlnet_2.get("end_percent", 1.0),
                        }}
            wf["9"]["inputs"]["positive"] = ["32", 0]
            wf["9"]["inputs"]["negative"] = ["32", 1]

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

    Pipeline: LoadImage → UpscaleModelLoader → ImageUpscaleWithModelByFactor(1.5x)
              → ReActorRestoreFace → ImageSharpen → SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": upscale_model}},
        "3": {"class_type": "ImageUpscaleWithModelByFactor",
              "inputs": {
                  "upscale_model": ["2", 0],
                  "image": ["1", 0],
                  "scale_by": 1.0,
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
    # ── Intensity-based (generic) ──
    "Subtle — preserve original": {
        "denoise": 0.20, "cfg": 3.5, "steps": 20,
        "prompt": "ultra detailed, sharp focus, high resolution, same content, faithful reproduction, clean",
        "negative": "different content, changed, altered, blurry, soft, painting, illustration",
    },
    "Moderate — add fine detail": {
        "denoise": 0.35, "cfg": 5.0, "steps": 25,
        "prompt": "ultra detailed, sharp focus, high resolution, intricate details, fine texture, photorealistic",
        "negative": "blurry, low quality, soft, out of focus, painting, cartoon",
    },
    "Strong — reimagine details": {
        "denoise": 0.50, "cfg": 6.5, "steps": 30,
        "prompt": "masterpiece, ultra detailed, sharp focus, high resolution, intricate details, rich texture, professional",
        "negative": "blurry, low quality, worst quality, soft, out of focus, noise, grain",
    },

    # ── Purpose-specific ──
    "Skin Texture — pores & micro-detail": {
        "denoise": 0.30, "cfg": 4.5, "steps": 25,
        "prompt": "ultra detailed skin, visible pores, natural skin texture, subsurface scattering, "
                  "realistic skin detail, peach fuzz, micro-wrinkles, beauty photography, 8k macro",
        "negative": "smooth plastic skin, airbrushed, porcelain, wax, mannequin, painting, soft focus",
    },
    "Eyes & Iris — catchlights & detail": {
        "denoise": 0.28, "cfg": 4.0, "steps": 25,
        "prompt": "ultra detailed eyes, sharp iris pattern, visible iris fibers, crisp catchlights, "
                  "natural eye reflection, detailed eyelashes, realistic eye, macro photography",
        "negative": "blurry eyes, dull eyes, flat eyes, no catchlight, painted eyes, dead eyes",
    },
    "Hair — strands & shine": {
        "denoise": 0.32, "cfg": 5.0, "steps": 25,
        "prompt": "ultra detailed hair, individual hair strands visible, natural hair shine, "
                  "hair highlights, detailed hair texture, flyaway hairs, professional hair photo",
        "negative": "blurry hair, helmet hair, flat hair, painted hair, plastic hair, wig",
    },
    "Fabric & Clothing — weave & texture": {
        "denoise": 0.35, "cfg": 5.5, "steps": 25,
        "prompt": "ultra detailed fabric texture, visible thread weave, cloth fiber detail, "
                  "natural fabric folds, realistic material texture, fashion photography detail",
        "negative": "smooth fabric, flat texture, plastic, blurry clothing, painted",
    },
    "Landscape — foliage & terrain": {
        "denoise": 0.40, "cfg": 5.5, "steps": 30,
        "prompt": "ultra detailed landscape, individual leaves, grass blades, bark texture, "
                  "rock detail, water ripples, natural terrain, nature photography, 8k sharp",
        "negative": "flat landscape, blurry foliage, smooth ground, painting, illustration",
    },
    "Architecture — bricks & surfaces": {
        "denoise": 0.38, "cfg": 5.5, "steps": 28,
        "prompt": "ultra detailed architecture, visible brick texture, mortar joints, "
                  "surface imperfections, concrete grain, wood grain, metal rivets, window reflections",
        "negative": "smooth walls, flat surfaces, blurry building, painting, low resolution",
    },
    "Sharpen & De-blur — rescue soft images": {
        "denoise": 0.22, "cfg": 3.0, "steps": 15,
        "prompt": "razor sharp, tack sharp focus, crisp edges, no motion blur, "
                  "high resolution, crystal clear, DSLR quality, perfectly focused",
        "negative": "blurry, soft, out of focus, motion blur, camera shake, low resolution",
    },
    "Food & Macro — appetizing detail": {
        "denoise": 0.35, "cfg": 5.0, "steps": 25,
        "prompt": "ultra detailed food photography, glistening sauce, visible seasoning, "
                  "steam rising, crisp lettuce, juicy meat texture, macro food detail, appetizing",
        "negative": "blurry food, flat, unappetizing, low quality, plastic food",
    },
    "Metal & Jewelry — reflections & polish": {
        "denoise": 0.30, "cfg": 5.0, "steps": 25,
        "prompt": "ultra detailed metal surface, mirror polish reflections, visible scratches, "
                  "gem facets, gold shimmer, diamond sparkle, jewelry macro photography",
        "negative": "dull metal, flat surface, matte, blurry, painted, low quality",
    },
    "Anti-DoF — sharp focus throughout": {
        "denoise": 0.35, "cfg": 5.5, "steps": 30,
        "prompt": "sharp focus throughout entire image, deep depth of field, f/16 aperture, "
                  "everything in focus from foreground to background, no bokeh, no blur, "
                  "tack sharp edge to edge, large depth of field, landscape focus, "
                  "hyperfocal distance, ultra sharp, every detail crisp",
        "negative": "shallow depth of field, bokeh, blurry background, out of focus areas, "
                    "selective focus, lens blur, tilt shift, soft background, "
                    "foreground blur, defocused, f/1.4, f/1.8, wide aperture",
    },
}

def _build_detail_hallucinate(image_filename, upscale_model, preset, prompt_text, negative_text,
                               seed, denoise, cfg, steps=None,
                               upscale_factor=1.0,
                               controlnet=None, controlnet_2=None):
    """Upscale + img2img at low denoise to hallucinate fine detail.

    Pipeline: LoadImage → UpscaleModelLoader → ImageUpscaleWithModelByFactor(factor)
              → Model Loader → CLIPTextEncode(+/-)
              → [ControlNet 1] → [ControlNet 2]
              → VAEEncode → KSampler → VAEDecode → SaveImage

    upscale_factor (default 1.5): Controls the output scale. Unlike
    ImageUpscaleWithModel which always outputs the model's native factor (4x/8x),
    ImageUpscaleWithModelByFactor lets you specify the exact upscale ratio.
    factor=1.5 on a 1000px image → 1500px output (instead of 4000px).
    This prevents massive images that overwhelm VRAM and cause timeouts.
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
    }
    # Upscale is optional — skip if no upscale model selected
    if upscale_model:
        wf["2"] = {"class_type": "UpscaleModelLoader",
                   "inputs": {"model_name": upscale_model}}
        wf["3"] = {"class_type": "ImageUpscaleWithModelByFactor",
                   "inputs": {"upscale_model": ["2", 0], "image": ["1", 0],
                              "scale_by": upscale_factor}}
        img_ref = ["3", 0]
    else:
        img_ref = ["1", 0]
    img_ref = _ensure_mod16(wf, img_ref, preset, "3s")

    loader_wf, model_ref, clip_ref, vae_ref = _make_model_loader(preset, "4")
    wf.update(loader_wf)
    wf.update({
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "7": {"class_type": "VAEEncode",
              "inputs": {"pixels": img_ref, "vae": vae_ref}},
        "8": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref,
                  "positive": ["5", 0],
                  "negative": ["6", 0],
                  "latent_image": ["7", 0],
                  "seed": seed,
                  "steps": steps or preset["steps"],
                  "cfg": cfg,
                  "sampler_name": preset["sampler"],
                  "scheduler": preset["scheduler"],
                  "denoise": denoise,
              }},
        "9": {"class_type": "VAEDecode",
              "inputs": {"samples": ["8", 0], "vae": vae_ref}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["9", 0], "filename_prefix": "spellcaster_hallucinate"}},
    })

    # ── ControlNet 1 (optional — Tile recommended for hallucination) ──
    if controlnet and controlnet.get("mode", "Off") != "Off":
        guide = CONTROLNET_GUIDE_MODES[controlnet["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model = guide["cn_models"].get(arch, guide["cn_models"].get("sdxl"))
        if cn_model:
            preprocessor = guide["preprocessor"]

            # ControlNet processes the (optionally upscaled) image
            cn_image_ref = img_ref
            if preprocessor:
                wf["20"] = {"class_type": preprocessor,
                            "inputs": {"image": img_ref}}
                cn_image_ref = ["20", 0]

            wf["21"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model}}
            wf["22"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": ["5", 0],
                            "negative": ["6", 0],
                            "control_net": ["21", 0],
                            "image": cn_image_ref,
                            "strength": controlnet["strength"],
                            "start_percent": controlnet.get("start_percent", 0.0),
                            "end_percent": controlnet.get("end_percent", 1.0),
                        }}
            wf["8"]["inputs"]["positive"] = ["22", 0]
            wf["8"]["inputs"]["negative"] = ["22", 1]

            # Debug layer
            if cn_image_ref != ["3", 0] and _load_config().get("debug_images", False):
                wf["25"] = {"class_type": "SaveImage",
                            "inputs": {"images": cn_image_ref, "filename_prefix": "spellcaster_cn_debug"}}

    # ── ControlNet 2 (optional — e.g., combine Tile + Depth) ──
    if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        guide2 = CONTROLNET_GUIDE_MODES[controlnet_2["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model_2 = guide2["cn_models"].get(arch, guide2["cn_models"].get("sdxl"))
        if cn_model_2:
            preprocessor_2 = guide2["preprocessor"]

            cn_image_ref_2 = img_ref
            if preprocessor_2:
                wf["30"] = {"class_type": preprocessor_2,
                            "inputs": {"image": ["3", 0]}}
                cn_image_ref_2 = ["30", 0]

            wf["31"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model_2}}

            # Chain from CN1 output if it exists, else from raw CLIP
            prev_pos = ["22", 0] if "22" in wf else ["5", 0]
            prev_neg = ["22", 1] if "22" in wf else ["6", 0]
            wf["32"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": prev_pos,
                            "negative": prev_neg,
                            "control_net": ["31", 0],
                            "image": cn_image_ref_2,
                            "strength": controlnet_2["strength"],
                            "start_percent": controlnet_2.get("start_percent", 0.0),
                            "end_percent": controlnet_2.get("end_percent", 1.0),
                        }}
            wf["8"]["inputs"]["positive"] = ["32", 0]
            wf["8"]["inputs"]["negative"] = ["32", 1]

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
                    seed, denoise, cfg, steps, scale_factor, orig_width, orig_height,
                    controlnet=None, controlnet_2=None):
    """SeedV2R: upscale + img2img pipeline with user-controlled scale and hallucination.

    For scale > 1x: UpscaleModelLoader → ImageUpscaleWithModel (4x) →
                     ImageScale (to target dims) → [ControlNet 1] → [ControlNet 2]
                     → VAEEncode → KSampler → ...
    For 1x: skip upscale, go straight to VAEEncode → KSampler.
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
    }

    if scale_factor > 1.0 and upscale_model:
        # Upscale with model using ImageUpscaleWithModelByFactor
        # to the exact target factor (instead of always 4x then downscale)
        wf["2"] = {"class_type": "UpscaleModelLoader",
                   "inputs": {"model_name": upscale_model}}
        wf["3"] = {"class_type": "ImageUpscaleWithModelByFactor",
                   "inputs": {
                       "upscale_model": ["2", 0],
                       "image": ["1", 0],
                       "scale_by": scale_factor,
                   }}
        img_ref = ["3", 0]
    else:
        # 1x — no upscale, use original image directly
        img_ref = ["1", 0]
    img_ref = _ensure_mod16(wf, img_ref, preset, "3s")

    loader_wf, m_ref, c_ref, v_ref = _make_model_loader(preset, "4")
    wf.update(loader_wf)
    wf["5"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": prompt_text, "clip": c_ref}}
    wf["6"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": negative_text, "clip": c_ref}}
    wf["7"] = {"class_type": "VAEEncode",
               "inputs": {"pixels": img_ref, "vae": v_ref}}
    wf["8"] = {"class_type": "KSampler",
               "inputs": {
                   "model": m_ref,
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
               "inputs": {"samples": ["8", 0], "vae": v_ref}}
    wf["10"] = {"class_type": "SaveImage",
                "inputs": {"images": ["9", 0], "filename_prefix": "spellcaster_seedv2r"}}

    # ── ControlNet 1 (optional — Tile recommended for upscale) ──
    if controlnet and controlnet.get("mode", "Off") != "Off":
        guide = CONTROLNET_GUIDE_MODES[controlnet["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model = guide["cn_models"].get(arch, guide["cn_models"].get("sdxl"))
        if cn_model:
            preprocessor = guide["preprocessor"]

            # ControlNet processes the upscaled image
            cn_image_ref = img_ref
            if preprocessor:
                wf["20"] = {"class_type": preprocessor,
                            "inputs": {"image": img_ref}}
                cn_image_ref = ["20", 0]

            wf["21"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model}}
            wf["22"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": ["5", 0],
                            "negative": ["6", 0],
                            "control_net": ["21", 0],
                            "image": cn_image_ref,
                            "strength": controlnet["strength"],
                            "start_percent": controlnet.get("start_percent", 0.0),
                            "end_percent": controlnet.get("end_percent", 1.0),
                        }}
            wf["8"]["inputs"]["positive"] = ["22", 0]
            wf["8"]["inputs"]["negative"] = ["22", 1]

    # ── ControlNet 2 (optional — e.g., Tile + Depth) ──
    if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        guide2 = CONTROLNET_GUIDE_MODES[controlnet_2["mode"]]
        arch = preset.get("arch", "sdxl")
        cn_model_2 = guide2["cn_models"].get(arch, guide2["cn_models"].get("sdxl"))
        if cn_model_2:
            preprocessor_2 = guide2["preprocessor"]

            cn_image_ref_2 = img_ref
            if preprocessor_2:
                wf["30"] = {"class_type": preprocessor_2,
                            "inputs": {"image": img_ref}}
                cn_image_ref_2 = ["30", 0]

            wf["31"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model_2}}
            prev_pos = ["22", 0] if "22" in wf else ["5", 0]
            prev_neg = ["22", 1] if "22" in wf else ["6", 0]
            wf["32"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": prev_pos,
                            "negative": prev_neg,
                            "control_net": ["31", 0],
                            "image": cn_image_ref_2,
                            "strength": controlnet_2["strength"],
                            "start_percent": controlnet_2.get("start_percent", 0.0),
                            "end_percent": controlnet_2.get("end_percent", 1.0),
                        }}
            wf["8"]["inputs"]["positive"] = ["32", 0]
            wf["8"]["inputs"]["negative"] = ["32", 1]

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
    "Canny (edges) — SD1.5/SDXL/ZIT": {
        "preprocessor": "CannyEdgePreprocessor",
        "cn_models": {"sd15": "control_v11p_sd15_lineart_fp16.safetensors",
                       "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
                       "illustrious": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
                       "zit": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"},
    },
    "Depth (spatial) — SD1.5/SDXL/ZIT": {
        "preprocessor": "MiDaS-DepthMapPreprocessor",
        "cn_models": {"sd15": "control_v11f1p_sd15_depth_fp16.safetensors",
                       "sdxl": "SDXL\\control-lora-depth-rank128.safetensors",
                       "illustrious": "SDXL\\control-lora-depth-rank128.safetensors",
                       "zit": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"},
    },
    "Lineart (drawing) — SD1.5/SDXL/ZIT": {
        "preprocessor": "LineArtPreprocessor",
        "cn_models": {"sd15": "control_v11p_sd15_lineart_fp16.safetensors",
                       "sdxl": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
                       "illustrious": "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
                       "zit": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"},
    },
    "OpenPose (body) — SD1.5/SDXL/ZIT": {
        "preprocessor": "DWPreprocessor",
        "cn_models": {"sd15": "control_v11p_sd15_openpose_fp16.safetensors",
                       "sdxl": "SDXL\\controlnet-openpose-sdxl-1.0\\diffusion_pytorch_model.safetensors",
                       "illustrious": "noobaiXLControlnet_openposeModel.safetensors",
                       "zit": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"},
    },
    "OpenPose XL (community) — SDXL/Illustrious": {
        "preprocessor": "DWPreprocessor",
        "cn_models": {"sdxl": "OpenPoseXL2.safetensors",
                       "illustrious": "noobaiXLControlnet_openposeModel.safetensors"},
    },
    "Scribble (sketch) — SD1.5 only": {
        "preprocessor": "ScribblePreprocessor",
        "cn_models": {"sd15": "control_v11p_sd15_lineart_fp16.safetensors"},
    },
    "Tile (detail) — SD1.5/SDXL/ZIT": {
        "preprocessor": None,
        "cn_models": {"sd15": "control_v11f1e_sd15_tile.pth",
                       "sdxl": "SDXL\\ttplanetSDXLControlnet_Tile_v20Fp16.safetensors",
                       "illustrious": "SDXL\\ttplanetSDXLControlnet_Tile_v20Fp16.safetensors",
                       "zit": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"},
    },
    "Flux Union Pro (all-in-one) — Flux only": {
        "preprocessor": None,
        "cn_models": {"flux1dev": "FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors",
                       "flux2klein": "FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors",
                       "flux_kontext": "FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors"},
    },
    "ZIT Union (all modes) — ZIT only": {
        "preprocessor": None,
        "cn_models": {"zit": "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"},
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
    # ── Photography Corrections ──
    "Fix White Balance (neutral)": "neutral white balance, correct color temperature, no color cast, daylight balanced, natural colors, accurate whites, grey card calibrated",
    "Fix Warm Cast (too orange/yellow)": "cool color correction, remove warm cast, neutralize orange tint, blue shift, daylight correction, accurate skin tones, remove tungsten warmth",
    "Fix Cold Cast (too blue)": "warm color correction, remove blue cast, neutralize cool tint, warm shift, add warmth, remove fluorescent green-blue, natural warm skin tones",
    "Remove Flash / Harsh Light": "soft natural ambient lighting, remove flash reflection, no harsh shadows, no specular highlights, no red-eye flash, diffused even illumination, matte skin no shine",
    "Fix Overexposure (blown highlights)": "recover blown highlights, restore highlight detail, reduce brightness, proper exposure, no clipping, visible cloud detail, controlled highlights, HDR recovery",
    "Fix Underexposure (too dark)": "brighten dark areas, lift shadows, increase exposure, reveal shadow detail, proper brightness, well-lit, visible detail in dark areas, shadow recovery",
    "HDR Look (dynamic range)": "HDR photography, extreme dynamic range, visible detail in shadows and highlights simultaneously, tone mapped, vivid colors, dramatic contrast, detailed sky and foreground",
    "Remove Motion Blur": "frozen motion, tack sharp, no motion blur, crisp edges, high shutter speed, perfectly still, no camera shake, sharp detail throughout",
    "Remove Red Eye": "natural eye color, no red-eye, clear eyes, proper pupil color, no flash reflection in eyes, natural iris, healthy eye appearance",
    "Studio Portrait Light": "professional three-point studio lighting, key light from 45 degrees, fill light opposite, rim light from behind, soft shadows, portrait photography, beauty dish lighting",
    "Window / Natural Indoor": "soft window light from the side, natural indoor lighting, warm ambient, gentle shadows, cozy atmosphere, diffused daylight through curtains",
    "Sunset / Magic Hour": "sunset golden light, magic hour warm glow, long shadows, orange and pink sky, warm highlights, dramatic silhouette edges, cinematic sunset",
    "Cloudy / Overcast Flat": "overcast even lighting, soft diffused light, no harsh shadows, cloudy day, flat neutral illumination, grey sky ambient, shadowless",
    "Rim Light / Silhouette Edge": "strong backlight rim light, luminous hair edge, silhouette glow, halo effect, backlit portrait, glowing outline, contra jour",
}

COLORIZE_PRESETS = {
    "Natural Photograph (realistic)": {
        "prompt": "vivid natural colors, photorealistic colorization, accurate skin tones, "
                  "natural warm lighting, realistic fabric colors, period-accurate colors, "
                  "color photograph, lifelike, DSLR quality, professional color restoration",
        "negative": "black and white, monochrome, grey, desaturated, oversaturated, "
                    "neon colors, unnatural colors, painting, illustration, cartoon",
        "denoise": 0.72, "cn_strength": 0.85, "cfg": 7.0, "steps": 30,
    },
    "Warm Vintage (old photo)": {
        "prompt": "warm vintage colors, nostalgic color palette, slightly faded film look, "
                  "warm sepia undertones, 1960s color photograph, Kodachrome film colors, "
                  "warm amber highlights, aged photo restoration, retro color grading",
        "negative": "black and white, monochrome, grey, cold blue tones, modern neon, oversaturated",
        "denoise": 0.75, "cn_strength": 0.80, "cfg": 6.5, "steps": 28,
    },
    "Cool/Neutral (documentary)": {
        "prompt": "neutral accurate colors, documentary photograph, cool balanced tones, "
                  "clinical color accuracy, no color cast, grey-balanced, objective colorization, "
                  "reference-accurate, archival quality color restoration",
        "negative": "warm tones, sepia, oversaturated, artistic, painting, stylized, neon",
        "denoise": 0.70, "cn_strength": 0.88, "cfg": 7.5, "steps": 30,
    },
    "Vivid/Saturated (pop art)": {
        "prompt": "highly saturated vivid colors, rich deep colors, intense color palette, "
                  "bold color choices, high contrast colorization, eye-catching, vibrant, "
                  "punchy colors, dramatic color grading, magazine cover quality",
        "negative": "muted, desaturated, grey, dull, pastel, faded, black and white",
        "denoise": 0.78, "cn_strength": 0.75, "cfg": 6.0, "steps": 25,
    },
    "Hand-Tinted (classic)": {
        "prompt": "hand-tinted photograph, delicate pastel colorization, subtle gentle colors, "
                  "slightly transparent color overlay, classic tinted portrait, watercolor tint, "
                  "softly colored cheeks and lips, antique hand-colored photograph",
        "negative": "oversaturated, neon, vivid, modern, digital, sharp colors, harsh",
        "denoise": 0.65, "cn_strength": 0.90, "cfg": 5.5, "steps": 25,
    },
    "Cinematic Film (movie grade)": {
        "prompt": "cinematic color grading, film stock colors, movie-quality colorization, "
                  "teal and orange color scheme, Hollywood color palette, anamorphic film look, "
                  "professional color correction, blockbuster film still, dramatic mood lighting",
        "negative": "flat, boring, grey, monochrome, amateur, oversaturated candy colors",
        "denoise": 0.75, "cn_strength": 0.82, "cfg": 6.5, "steps": 30,
    },
}


def _build_colorize(image_filename, preset, prompt_text, negative_text, seed,
                     controlnet_strength, denoise, steps=None, cfg=None, controlnet_2=None):
    """Colorize B&W photo — dual ControlNet pipeline for maximum structure fidelity.

    Pipeline:
      LoadImage → LineArtPreprocessor (high-res for fine detail)
      LoadImage → DepthPreprocessor (preserves spatial structure)
      Model Loader → CLIPTextEncode(+/-)
      ControlNetApplyAdvanced(lineart) → ControlNetApplyAdvanced(depth)
      VAEEncode(original B&W) → KSampler → VAEDecode → SaveImage

    Uses lineart CN to preserve fine detail (faces, text, edges) and
    depth CN to maintain spatial relationships and 3D structure.
    Resolution auto-scaled to match the working resolution of the model.
    """
    arch = preset.get("arch", "sdxl")
    cn_lineart = CONTROLNET_LINEART_MODELS.get(arch, CONTROLNET_LINEART_MODELS["sdxl"])
    # Use the model's native resolution for the preprocessor
    res = max(preset.get("width", 1024), preset.get("height", 1024))

    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
    }
    img_ref = _ensure_mod16(wf, ["1", 0], preset, "1s")
    wf.update({
        # Lineart preprocessor at full resolution for fine detail
        "2": {"class_type": "LineArtPreprocessor",
              "inputs": {
                  "image": img_ref,
                  "resolution": res,
                  "coarse": "disable",
              }},
    })
    loader_wf, model_ref, clip_ref, vae_ref = _make_model_loader(preset, "3")
    wf.update(loader_wf)
    wf.update({
        "4": {"class_type": "ControlNetLoader",
              "inputs": {"control_net_name": cn_lineart}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
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
              "inputs": {"pixels": img_ref, "vae": vae_ref}},
        "9": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref,
                  "positive": ["7", 0],
                  "negative": ["7", 1],
                  "latent_image": ["8", 0],
                  "seed": seed,
                  "steps": steps or preset["steps"],
                  "cfg": cfg or preset["cfg"],
                  "sampler_name": preset["sampler"],
                  "scheduler": preset["scheduler"],
                  "denoise": denoise,
              }},
        "10": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": vae_ref}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": "spellcaster_colorize"}},
    })

    # Optional second ControlNet (Depth recommended for spatial structure)
    if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        guide2 = CONTROLNET_GUIDE_MODES[controlnet_2["mode"]]
        cn_model_2 = guide2["cn_models"].get(arch, guide2["cn_models"].get("sdxl"))
        if cn_model_2:
            preprocessor_2 = guide2["preprocessor"]

            cn_image_ref_2 = img_ref
            if preprocessor_2:
                wf["30"] = {"class_type": preprocessor_2,
                            "inputs": {"image": img_ref}}
                cn_image_ref_2 = ["30", 0]

            wf["31"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model_2}}
            wf["32"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": ["7", 0],
                            "negative": ["7", 1],
                            "control_net": ["31", 0],
                            "image": cn_image_ref_2,
                            "strength": controlnet_2["strength"],
                            "start_percent": controlnet_2.get("start_percent", 0.0),
                            "end_percent": controlnet_2.get("end_percent", 1.0),
                        }}
            wf["9"]["inputs"]["positive"] = ["32", 0]
            wf["9"]["inputs"]["negative"] = ["32", 1]

            if _load_config().get("debug_images", False):
                if cn_image_ref_2 != img_ref:
                    wf["35"] = {"class_type": "SaveImage",
                                "inputs": {"images": cn_image_ref_2, "filename_prefix": "spellcaster_cn_debug"}}

    # ── Optional ControlNet 2 (Depth/Pose for spatial guidance) ──
    if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
        guide2 = CONTROLNET_GUIDE_MODES[controlnet_2["mode"]]
        cn_model_2 = guide2["cn_models"].get(arch, guide2["cn_models"].get("sdxl"))
        if cn_model_2:
            preprocessor_2 = guide2["preprocessor"]

            cn_image_ref_2 = img_ref
            if preprocessor_2:
                wf["20"] = {"class_type": preprocessor_2,
                            "inputs": {"image": img_ref}}
                cn_image_ref_2 = ["20", 0]

            wf["21"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model_2}}
            wf["22"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": ["7", 0],
                            "negative": ["7", 1],
                            "control_net": ["21", 0],
                            "image": cn_image_ref_2,
                            "strength": controlnet_2["strength"],
                            "start_percent": controlnet_2.get("start_percent", 0.0),
                            "end_percent": controlnet_2.get("end_percent", 1.0),
                        }}
            wf["9"]["inputs"]["positive"] = ["22", 0]
            wf["9"]["inputs"]["negative"] = ["22", 1]

    return wf


# ── Generic ControlNet generation builder ─────────────────────────────

def _build_controlnet_gen(image_filename, preprocessor_type, controlnet_model,
                           preset, prompt, negative, seed, width, height,
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
    }
    loader_wf, model_ref, clip_ref, vae_ref = _make_model_loader(preset, "3")
    wf.update(loader_wf)
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "3", model_ref, clip_ref)
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
               "inputs": {"samples": ["9", 0], "vae": vae_ref}},
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
        preset, prompt, negative, seed,
        preset["width"], preset["height"], preset["steps"], preset["cfg"],
        preset["sampler"], preset["scheduler"], cn_strength, loras)


def _build_canny2img(image_filename, preset, prompt, negative, seed,
                      cn_strength=0.8, loras=None):
    """ControlNet Canny Edge to Image using CannyEdgePreprocessor."""
    arch = preset.get("arch", "sdxl")
    cn_model = CONTROLNET_CANNY_MODELS.get(arch, CONTROLNET_CANNY_MODELS["sdxl"])
    return _build_controlnet_gen(
        image_filename, "CannyEdgePreprocessor", cn_model,
        preset, prompt, negative, seed,
        preset["width"], preset["height"], preset["steps"], preset["cfg"],
        preset["sampler"], preset["scheduler"], cn_strength, loras)


def _build_depth2img(image_filename, preset, prompt, negative, seed,
                      cn_strength=0.8, loras=None):
    """ControlNet Depth to Image using MiDaS-DepthMapPreprocessor."""
    arch = preset.get("arch", "sdxl")
    cn_model = CONTROLNET_DEPTH_MODELS.get(arch, CONTROLNET_DEPTH_MODELS["sdxl"])
    return _build_controlnet_gen(
        image_filename, "MiDaS-DepthMapPreprocessor", cn_model,
        preset, prompt, negative, seed,
        preset["width"], preset["height"], preset["steps"], preset["cfg"],
        preset["sampler"], preset["scheduler"], cn_strength, loras)


def _build_pose2img(image_filename, preset, prompt, negative, seed,
                     cn_strength=0.8, loras=None):
    """ControlNet Pose to Image using DWPreprocessor (DWPose)."""
    arch = preset.get("arch", "sdxl")
    cn_model = CONTROLNET_POSE_MODELS.get(arch, CONTROLNET_POSE_MODELS["sdxl"])
    return _build_controlnet_gen(
        image_filename, "DWPreprocessor", cn_model,
        preset, prompt, negative, seed,
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
    iclight_preset = {"ckpt": ckpt_name, "arch": "sd15"}
    loader_wf, model_ref, clip_ref, vae_ref = _make_model_loader(iclight_preset, "2")
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
    }
    wf.update(loader_wf)
    wf.update({
        # VAEEncode the foreground image to latent (ICLightConditioning expects LATENT)
        "10": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["1", 0], "vae": vae_ref}},
        "3": {"class_type": "LoadAndApplyICLightUnet",
              "inputs": {
                  "model": model_ref,
                  "model_path": "SD-1.5\\iclight_sd15_fc.safetensors",
              }},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": clip_ref}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": clip_ref}},
        "6": {"class_type": "ICLightConditioning",
              "inputs": {
                  "positive": ["4", 0], "negative": ["5", 0],
                  "vae": vae_ref, "foreground": ["10", 0],
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
              "inputs": {"samples": ["7", 0], "vae": vae_ref}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": "spellcaster_iclight"}},
    })
    return wf


# ── SUPIR AI Restoration builder ──────────────────────────────────────

def _build_supir(image_filename, supir_model, sdxl_model, prompt, seed,
                  denoise=0.3, steps=45, scale_by=1.0,
                  controlnet=None, controlnet_2=None):
    """SUPIR AI restoration — full granular pipeline for maximum quality.

    Pipeline (5 stages):
      1. SUPIR_model_loader    — loads SUPIR weights + SDXL backbone
      2. SUPIR_first_stage     — stage-1 denoising (removes compression artifacts,
                                  stabilizes colors before the main restoration pass)
      3. SUPIR_conditioner     — builds rich conditioning from positive + negative prompts
      4. SUPIR_sample          — the main restoration: EDM sampler with start/end control
                                  ramps, restore_cfg for fidelity, tiled for large images
      5. SUPIR_decode          — tiled VAE decode back to pixels

    Compared to the all-in-one SUPIR_Upscale node, this gives:
      - Much better detail recovery (stage-1 pre-denoising)
      - Proper CFG ramping (starts high for structure, drops for detail)
      - Control scale ramping (gentle start, full strength mid-pass)
      - Tiled sampling for large images without VRAM overflow
      - Rich negative prompt engineering
    """
    # Negative prompt engineered for maximum restoration quality
    neg_prompt = (
        "painting, illustration, drawing, art, sketch, anime, cartoon, 3d render, "
        "CG, low quality, blurry, noisy, oversmoothed, plastic skin, washed out, "
        "oversaturated, artifacts, compression, jpeg, watermark, text, logo, "
        "deformed, distorted, disfigured, bad anatomy, extra limbs"
    )

    # Map denoise (0.0-1.0) to control_scale range:
    # Low denoise (0.1-0.3) = faithful restoration, high (0.5-1.0) = creative
    control_start = max(0.0, 1.0 - denoise * 1.5)  # e.g., 0.3 denoise → 0.55 control
    control_end = min(1.0, denoise * 2.0 + 0.4)     # e.g., 0.3 denoise → 1.0 control

    # CFG ramping: start higher for structure, end lower for natural detail
    cfg_start = 4.0 + denoise * 2.0   # e.g., 0.3 → 4.6
    cfg_end = max(1.5, 4.0 - denoise)  # e.g., 0.3 → 3.7

    # Use tiled sampler for images > 1024px
    sampler = "TiledRestoreEDMSampler" if scale_by >= 1.5 else "RestoreEDMSampler"

    wf = {
        # Stage 0: Load input image
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},

        # Stage 1: Load SUPIR model + SDXL backbone
        "10": {"class_type": "SUPIR_model_loader",
               "inputs": {
                   "supir_model": supir_model,
                   "sdxl_model": sdxl_model,
                   "fp8_unet": False,
                   "diffusion_dtype": "auto",
               }},

        # Stage 2: First-stage denoising (pre-cleans the image)
        # This removes compression artifacts and stabilizes before the main pass
        "20": {"class_type": "SUPIR_first_stage",
               "inputs": {
                   "SUPIR_VAE": ["10", 1],
                   "image": ["1", 0],
                   "use_tiled_vae": True,
                   "encoder_tile_size": 512,
                   "decoder_tile_size": 64,
                   "encoder_dtype": "auto",
               }},

        # Stage 3: Build conditioning from prompts
        "30": {"class_type": "SUPIR_conditioner",
               "inputs": {
                   "SUPIR_model": ["10", 0],
                   "latents": ["20", 2],
                   "positive_prompt": prompt if prompt.strip() else "high quality, detailed, sharp focus, professional photograph, natural colors, clean",
                   "negative_prompt": neg_prompt,
               }},

        # Stage 4: Main restoration sampling
        "40": {"class_type": "SUPIR_sample",
               "inputs": {
                   "SUPIR_model": ["10", 0],
                   "latents": ["20", 2],
                   "positive": ["30", 0],
                   "negative": ["30", 1],
                   "seed": seed,
                   "steps": steps,
                   "cfg_scale_start": cfg_start,
                   "cfg_scale_end": cfg_end,
                   "EDM_s_churn": 5,
                   "s_noise": 1.003,
                   "DPMPP_eta": 1.0,
                   "control_scale_start": control_start,
                   "control_scale_end": control_end,
                   "restore_cfg": -1.0,
                   "keep_model_loaded": False,
                   "sampler": sampler,
               }},

        # Stage 5: Tiled VAE decode
        "50": {"class_type": "SUPIR_decode",
               "inputs": {
                   "SUPIR_VAE": ["20", 0],
                   "latents": ["40", 0],
                   "use_tiled_vae": True,
                   "decoder_tile_size": 64,
               }},

        # Output (may be replaced by refinement pass below)
        "60": {"class_type": "SaveImage",
               "inputs": {"images": ["50", 0], "filename_prefix": "spellcaster_supir"}},
    }

    # ── Optional ControlNet Refinement Post-Pass ──────────────────────
    # SUPIR nodes don't support ControlNet directly. So after SUPIR
    # restoration we run a quick img2img refinement at very low denoise
    # (0.12) with ControlNet (Tile/Depth) to lock in structural detail.
    # Uses the same SDXL model as a standard checkpoint loader.
    if controlnet and controlnet.get("mode", "Off") != "Off":
        guide = CONTROLNET_GUIDE_MODES[controlnet["mode"]]
        cn_model = guide["cn_models"].get("sdxl", guide["cn_models"].get("sd15"))
        if cn_model:
            preprocessor = guide["preprocessor"]

            # Load SDXL checkpoint for the refinement pass
            wf["70"] = {"class_type": "CheckpointLoaderSimple",
                        "inputs": {"ckpt_name": sdxl_model}}
            wf["71"] = {"class_type": "CLIPTextEncode",
                        "inputs": {"text": prompt if prompt.strip() else "high quality, detailed, sharp",
                                   "clip": ["70", 1]}}
            wf["72"] = {"class_type": "CLIPTextEncode",
                        "inputs": {"text": "blurry, noisy, artifacts, low quality",
                                   "clip": ["70", 1]}}

            # Preprocess SUPIR output for ControlNet
            cn_image_ref = ["50", 0]  # SUPIR decoded output
            if preprocessor:
                wf["73"] = {"class_type": preprocessor,
                            "inputs": {"image": ["50", 0]}}
                cn_image_ref = ["73", 0]

            wf["74"] = {"class_type": "ControlNetLoader",
                        "inputs": {"control_net_name": cn_model}}
            wf["75"] = {"class_type": "ControlNetApplyAdvanced",
                        "inputs": {
                            "positive": ["71", 0],
                            "negative": ["72", 0],
                            "control_net": ["74", 0],
                            "image": cn_image_ref,
                            "strength": controlnet["strength"],
                            "start_percent": 0.0,
                            "end_percent": 1.0,
                        }}

            # Encode SUPIR output to latent, sample at very low denoise, decode
            wf["76"] = {"class_type": "VAEEncode",
                        "inputs": {"pixels": ["50", 0], "vae": ["70", 2]}}
            wf["77"] = {"class_type": "KSampler",
                        "inputs": {
                            "model": ["70", 0],
                            "positive": ["75", 0],
                            "negative": ["75", 1],
                            "latent_image": ["76", 0],
                            "seed": seed + 1,
                            "steps": 15,
                            "cfg": 4.0,
                            "sampler_name": "dpmpp_2m_sde",
                            "scheduler": "karras",
                            "denoise": 0.12,
                        }}
            wf["78"] = {"class_type": "VAEDecode",
                        "inputs": {"samples": ["77", 0], "vae": ["70", 2]}}

            # Second ControlNet refinement (optional)
            if controlnet_2 and controlnet_2.get("mode", "Off") != "Off":
                guide2 = CONTROLNET_GUIDE_MODES[controlnet_2["mode"]]
                cn_model_2 = guide2["cn_models"].get("sdxl", guide2["cn_models"].get("sd15"))
                if cn_model_2:
                    preprocessor_2 = guide2["preprocessor"]

                    cn_image_ref_2 = ["50", 0]
                    if preprocessor_2:
                        wf["80"] = {"class_type": preprocessor_2,
                                    "inputs": {"image": ["50", 0]}}
                        cn_image_ref_2 = ["80", 0]

                    wf["81"] = {"class_type": "ControlNetLoader",
                                "inputs": {"control_net_name": cn_model_2}}
                    wf["82"] = {"class_type": "ControlNetApplyAdvanced",
                                "inputs": {
                                    "positive": ["75", 0],
                                    "negative": ["75", 1],
                                    "control_net": ["81", 0],
                                    "image": cn_image_ref_2,
                                    "strength": controlnet_2["strength"],
                                    "start_percent": 0.0,
                                    "end_percent": 1.0,
                                }}
                    # Re-wire the KSampler to use chained CN output
                    wf["77"]["inputs"]["positive"] = ["82", 0]
                    wf["77"]["inputs"]["negative"] = ["82", 1]

            # Replace output to use the refined image
            wf["60"]["inputs"]["images"] = ["78", 0]

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

    loader_wf, model_ref, clip_ref, vae_ref = _make_model_loader(p, "1")
    wf = dict(loader_wf)
    wf.update({
        # FaceID unified loader: loads IPAdapter + LoRA, applies to model
        "2": {"class_type": "IPAdapterUnifiedLoaderFaceID",
              "inputs": {
                  "model": model_ref,
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
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text or "blurry, deformed, bad anatomy", "clip": clip_ref}},
        # Load target image and encode to latent
        "7": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["7", 0], "vae": vae_ref}},
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
               "inputs": {"samples": ["9", 0], "vae": vae_ref}},
        "12": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "gimp_faceid"}},
    })
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
        "steps": 20, "second_step": 10, "cfg": 1, "shift": None,
        "lora_prefix": "Wan",
        "high_accel_lora": "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
        "low_accel_lora": "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
        "accel_strength": 1.5,
    },
    "Wan I2V 14B (fp8)": {
        "high_model": "Wan\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "low_model": "Wan\\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        "clip": "umt5-xxl-encoder-Q8_0.gguf",
        "vae": "wan_2.1_vae.safetensors",
        "steps": 20, "second_step": 10, "cfg": 1, "shift": None,
        "lora_prefix": "Wan",
        "high_accel_lora": "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
        "low_accel_lora": "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
        "accel_strength": 1.5,
    },
}

def _filter_wan_loras(all_loras, preset_key=None):
    """Return ALL Wan-related LoRAs from the server list.

    Wan LoRAs live in multiple folders: WAN, Wan/14B, Wan-2.2-I2V, etc.
    We show all of them regardless of preset since they all work with any
    Wan 2.2 model variant.
    """
    # Accept everything under any Wan-related folder
    prefixes = ["wan\\", "wan/", "wan-2.2", "wan2.2"]
    return [l for l in all_loras
            if any(l.lower().startswith(p) for p in prefixes)]


def _find_wan_lora_pair(lora_name, all_loras):
    """Given a LoRA name, find its high/low noise counterpart.

    Wan 2.2 uses paired LoRAs: one for the high-noise model and one for
    the low-noise model. Common naming patterns:
      - _high_noise / _low_noise
      - _HIGH / _LOW
      - HIGH / LOW in the name
      - High / Low in the name

    Returns (high_lora, low_lora) tuple. If the input is the high variant,
    returns (input, low_counterpart) and vice versa.
    """
    name_lower = lora_name.lower()

    # Determine if this is a high or low noise variant
    high_markers = ["_high_noise", "_high.", "high_noise", "-high-", "highnoise",
                    "_high_", "HIGH_", "HIGH.", "-HIGH"]
    low_markers = ["_low_noise", "_low.", "low_noise", "-low-", "lownoise",
                   "_low_", "LOW_", "LOW.", "-LOW"]

    is_high = any(m.lower() in name_lower for m in high_markers)
    is_low = any(m.lower() in name_lower for m in low_markers)

    if not is_high and not is_low:
        # Can't determine — apply to both models as-is
        return lora_name, lora_name

    # Build the counterpart name by swapping high↔low
    def _swap(name):
        pairs = [
            ("_high_noise", "_low_noise"), ("_low_noise", "_high_noise"),
            ("HIGH_", "LOW_"), ("LOW_", "HIGH_"),
            ("_HIGH", "_LOW"), ("_LOW", "_HIGH"),
            ("-HIGH-", "-LOW-"), ("-LOW-", "-HIGH-"),
            ("_high_", "_low_"), ("_low_", "_high_"),
            ("High", "Low"), ("Low", "High"),
            ("highnoise", "lownoise"), ("lownoise", "highnoise"),
            ("HighNoise", "LowNoise"), ("LowNoise", "HighNoise"),
        ]
        for old, new in pairs:
            if old in name:
                return name.replace(old, new, 1)
        return name

    counterpart = _swap(lora_name)

    # Verify the counterpart exists on the server
    if counterpart != lora_name and counterpart in all_loras:
        if is_high:
            return lora_name, counterpart
        else:
            return counterpart, lora_name

    # Counterpart not found — apply the same LoRA to both models
    return lora_name, lora_name


def _build_wan_video(image_filename, preset_key, prompt_text, negative_text, seed,
                      width=832, height=480, length=81,
                      steps=None, cfg=None, second_step=None,
                      turbo=True, loop=False,
                      loras_high=None, loras_low=None,
                      all_server_loras=None,
                      rtx_scale=2.5, interpolate=True,
                      pingpong=False, fps=16,
                      end_image_filename=None):
    """Wan 2.2 video generation — canon dual-model architecture.

    Supports three modes via parameters:
      - I2V:  image_filename set, loop=False, end_image_filename=None
              → WanImageToVideo (single start image)
      - Loop: image_filename set, loop=True
              → WanFirstLastFrameToVideo (same image for start+end = seamless loop)
      - FLF:  image_filename set, end_image_filename set
              → WanFirstLastFrameToVideo (different start+end images)

    Pipeline (from proven canon workflow):
      CLIPLoaderGGUF(umt5 Q8) → CLIPTextEncode (pos/neg)
      UnetLoaderGGUF × 2 (high/low) → [accel LoRAs 1.5str] → [content LoRAs]
      VAELoader + LoadImage → WanImageToVideo or WanFirstLastFrameToVideo
      KSamplerAdvanced pass 1 (high, cfg from preset, euler_ancestral)
      KSamplerAdvanced pass 2 (low, cfg=1, euler_ancestral)
      VAEDecode → RIFE VFI 2× → RTXVideoSuperResolution
      → VHS_VideoCombine (MP4) + VHS_VideoCombine (GIF for GIMP)
    """
    p = WAN_I2V_PRESETS[preset_key]
    steps = steps or p["steps"]
    cfg = cfg if cfg is not None else p["cfg"]
    second_step = second_step if second_step is not None else p.get("second_step", 10)

    is_gguf_high = p["high_model"].endswith(".gguf")
    is_gguf_low = p["low_model"].endswith(".gguf")
    use_flf = loop or (end_image_filename is not None)

    # ── Model loaders ────────────────────────────────────────────────
    wf = {
        "1": {"class_type": "CLIPLoaderGGUF",
              "inputs": {"clip_name": p["clip"], "type": "wan"}},
        "2": {"class_type": "UnetLoaderGGUF" if is_gguf_high else "UNETLoader",
              "inputs": {"unet_name": p["high_model"]}},
        "3": {"class_type": "UnetLoaderGGUF" if is_gguf_low else "UNETLoader",
              "inputs": {"unet_name": p["low_model"]}},
        "4": {"class_type": "VAELoader",
              "inputs": {"vae_name": p["vae"]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["1", 0]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text or "", "clip": ["1", 0]}},
        "7": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
    }
    if not is_gguf_high:
        wf["2"]["inputs"]["weight_dtype"] = "default"
    if not is_gguf_low:
        wf["3"]["inputs"]["weight_dtype"] = "default"

    # End image for FLF mode
    if end_image_filename and not loop:
        wf["7b"] = {"class_type": "LoadImage",
                    "inputs": {"image": end_image_filename}}

    # ── LoRA chains ──────────────────────────────────────────────────
    high_ref = ["2", 0]
    low_ref = ["3", 0]

    # Accelerator LoRAs (turbo) — strength from preset (default 1.5)
    if turbo:
        if p.get("high_accel_lora"):
            wf["100"] = {"class_type": "LoraLoaderModelOnly",
                         "inputs": {"model": high_ref,
                                    "lora_name": p["high_accel_lora"],
                                    "strength_model": p.get("accel_strength", 1.5)}}
            high_ref = ["100", 0]
        if p.get("low_accel_lora"):
            wf["120"] = {"class_type": "LoraLoaderModelOnly",
                         "inputs": {"model": low_ref,
                                    "lora_name": p["low_accel_lora"],
                                    "strength_model": p.get("accel_strength", 1.5)}}
            low_ref = ["120", 0]

    # User content LoRAs
    hi_n = 101 if turbo else 100
    lo_n = 121 if turbo else 120
    if loras_high:
        for i, (ln, ls) in enumerate(loras_high):
            nid = str(hi_n + i)
            wf[nid] = {"class_type": "LoraLoaderModelOnly",
                        "inputs": {"model": high_ref, "lora_name": ln, "strength_model": ls}}
            high_ref = [nid, 0]
    if loras_low:
        for i, (ln, ls) in enumerate(loras_low):
            nid = str(lo_n + i)
            wf[nid] = {"class_type": "LoraLoaderModelOnly",
                        "inputs": {"model": low_ref, "lora_name": ln, "strength_model": ls}}
            low_ref = [nid, 0]

    # ── Conditioning (WanImageToVideo or WanFirstLastFrameToVideo) ───
    if use_flf:
        end_ref = ["7", 0] if loop else ["7b", 0]
        wf["40"] = {"class_type": "WanFirstLastFrameToVideo",
                    "inputs": {
                        "width": width, "height": height, "length": length,
                        "batch_size": 1,
                        "positive": ["5", 0], "negative": ["6", 0],
                        "vae": ["4", 0],
                        "start_image": ["7", 0], "end_image": end_ref,
                    }}
    else:
        wf["40"] = {"class_type": "WanImageToVideo",
                    "inputs": {
                        "width": width, "height": height, "length": length,
                        "batch_size": 1,
                        "positive": ["5", 0], "negative": ["6", 0],
                        "vae": ["4", 0], "start_image": ["7", 0],
                    }}

    # ── Two-pass KSamplerAdvanced (euler_ancestral, no ModelSamplingSD3) ──
    wf["50"] = {"class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": high_ref, "positive": ["40", 0], "negative": ["40", 1],
                    "latent_image": ["40", 2],
                    "add_noise": "enable", "noise_seed": seed,
                    "steps": steps, "cfg": cfg,
                    "sampler_name": "euler_ancestral", "scheduler": "simple",
                    "start_at_step": 0, "end_at_step": second_step,
                    "return_with_leftover_noise": "enable",
                }}
    wf["51"] = {"class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": low_ref, "positive": ["40", 0], "negative": ["40", 1],
                    "latent_image": ["50", 0],
                    "add_noise": "disable", "noise_seed": 0,
                    "steps": steps, "cfg": 1,
                    "sampler_name": "euler_ancestral", "scheduler": "simple",
                    "start_at_step": second_step, "end_at_step": 10000,
                    "return_with_leftover_noise": "disable",
                }}

    # ── VAE Decode ───────────────────────────────────────────────────
    wf["60"] = {"class_type": "VAEDecode",
                "inputs": {"samples": ["51", 0], "vae": ["4", 0]}}

    video_ref = ["60", 0]

    # ── RIFE frame interpolation (2×) ────────────────────────────────
    if interpolate:
        wf["70"] = {"class_type": "RIFE VFI",
                    "inputs": {"frames": video_ref, "ckpt_name": "rife49.pth",
                               "clear_cache_after_n_frames": 32, "multiplier": 2,
                               "fast_mode": False, "ensemble": True, "scale_factor": 1,
                               "dtype": "float32", "torch_compile": False,
                               "batch_size": 1}}
        video_ref = ["70", 0]

    # ── RTX Video Super Resolution ───────────────────────────────────
    if rtx_scale > 1.0:
        wf["75"] = {"class_type": "RTXVideoSuperResolution",
                    "inputs": {"images": video_ref,
                               "resize_type": "scale by multiplier",
                               "resize_type.scale": rtx_scale,
                               "quality": "ULTRA"}}
        video_ref = ["75", 0]

    # ── Output ───────────────────────────────────────────────────────
    output_fps = float(fps * (2 if interpolate else 1))
    prefix = "gimp_wan_loop" if loop else ("gimp_wan_flf" if use_flf else "gimp_wan_i2v")

    # MP4 for the user
    wf["80"] = {"class_type": "VHS_VideoCombine",
                "inputs": {"images": video_ref, "frame_rate": output_fps,
                           "loop_count": 0, "filename_prefix": prefix,
                           "format": "video/h264-mp4", "pingpong": pingpong,
                           "save_output": True}}

    # First frame PNG for GIMP
    wf["82"] = {"class_type": "SaveImage",
                "inputs": {"images": ["60", 0],
                           "filename_prefix": f"{prefix}_frame"}}

    return wf


def _build_wan_flf(start_filename, end_filename, preset_key, prompt_text, negative_text, seed,
                    width=832, height=480, length=81,
                    steps=None, cfg=None, second_step=None,
                    turbo=True, loras_high=None, loras_low=None,
                    all_server_loras=None,
                    rtx_scale=2.5, interpolate=True, pingpong=False, fps=16):
    """Thin wrapper: delegates to _build_wan_video with end_image_filename."""
    return _build_wan_video(
        start_filename, preset_key, prompt_text, negative_text, seed,
        width=width, height=height, length=length,
        steps=steps, cfg=cfg, second_step=second_step,
        turbo=turbo, loop=False,
        loras_high=loras_high, loras_low=loras_low,
        all_server_loras=all_server_loras,
        rtx_scale=rtx_scale, interpolate=interpolate,
        pingpong=pingpong, fps=fps,
        end_image_filename=end_filename,
    )


# ── Video Upscale (V2R) ──────────────────────────────────────────────────

def _build_video_upscale(video_name, upscale_model="4x-UltraSharp.pth",
                          upscale_factor=1.0, rtx_scale=2.0, fps=16):
    """Upscale a video: load frames → model upscale → RTX super-res → save.

    Pipeline: VHS_LoadVideo → TS_Video_Upscale_With_Model(factor)
              → RTXVideoSuperResolution(scale) → CreateVideo → SaveVideo
              + SaveImage (first frame for GIMP)
    """
    wf = {
        "1": {"class_type": "VHS_LoadVideo",
              "inputs": {"video": video_name, "force_rate": 0, "force_size": "Disabled",
                         "custom_width": 0, "custom_height": 0,
                         "frame_load_cap": 0, "skip_first_frames": 0,
                         "select_every_nth": 1}},
    }

    video_ref = ["1", 0]  # IMAGE batch from VHS_LoadVideo

    # Model-based upscale (optional — skip if factor ≤ 1)
    if upscale_factor > 1.0 and upscale_model:
        wf["10"] = {"class_type": "TS_Video_Upscale_With_Model",
                    "inputs": {"model_name": upscale_model, "images": video_ref,
                               "upscale_method": "lanczos", "factor": upscale_factor,
                               "device_strategy": "auto"}}
        video_ref = ["10", 0]

    # RTX Video Super Resolution
    if rtx_scale > 1.0:
        wf["20"] = {"class_type": "RTXVideoSuperResolution",
                    "inputs": {"images": video_ref,
                               "resize_type": "scale by multiplier",
                               "resize_type.scale": rtx_scale,
                               "quality": "ULTRA"}}
        video_ref = ["20", 0]

    # Output video
    wf["30"] = {"class_type": "CreateVideo",
                "inputs": {"fps": float(fps), "images": video_ref}}
    wf["31"] = {"class_type": "SaveVideo",
                "inputs": {"filename_prefix": "gimp_video_upscale",
                           "format": "auto", "codec": "auto",
                           "video": ["30", 0]}}
    # First frame for GIMP
    wf["32"] = {"class_type": "SaveImage",
                "inputs": {"images": video_ref,
                           "filename_prefix": "gimp_video_upscale_frame"}}
    return wf


# ── Video Upscale + ReActor Face Swap ────────────────────────────────────

def _build_video_reactor(video_name, face_models, upscale_model="4x-UltraSharp.pth",
                          upscale_factor=1.0, rtx_scale=2.0, fps=16,
                          face_restore_visibility=0.5, codeformer_weight=0.95):
    """Upscale + face swap a video.

    Pipeline: VHS_LoadVideo → TS_Video_Upscale_With_Model(factor)
              → RTXVideoSuperResolution(scale)
              → ReActorFaceSwap (per face model) → ReActorRestoreFace
              → CreateVideo → SaveVideo + SaveImage (first frame)

    face_models: list of face model filenames (e.g. ["person1.safetensors", "person2.safetensors"])
                 Each gets applied as a separate face swap index.
    """
    wf = {
        "1": {"class_type": "VHS_LoadVideo",
              "inputs": {"video": video_name, "force_rate": 0, "force_size": "Disabled",
                         "custom_width": 0, "custom_height": 0,
                         "frame_load_cap": 0, "skip_first_frames": 0,
                         "select_every_nth": 1}},
    }

    video_ref = ["1", 0]

    # Model-based upscale
    if upscale_factor > 1.0 and upscale_model:
        wf["10"] = {"class_type": "TS_Video_Upscale_With_Model",
                    "inputs": {"model_name": upscale_model, "images": video_ref,
                               "upscale_method": "lanczos", "factor": upscale_factor,
                               "device_strategy": "auto"}}
        video_ref = ["10", 0]

    # RTX upscale
    if rtx_scale > 1.0:
        wf["20"] = {"class_type": "RTXVideoSuperResolution",
                    "inputs": {"images": video_ref,
                               "resize_type": "scale by multiplier",
                               "resize_type.scale": rtx_scale,
                               "quality": "ULTRA"}}
        video_ref = ["20", 0]

    # Load face models + face swap chain
    img_ref = video_ref
    for i, fm_name in enumerate(face_models):
        fm_nid = str(40 + i)
        swap_nid = str(50 + i)
        wf[fm_nid] = {"class_type": "ReActorLoadFaceModel",
                       "inputs": {"face_model": fm_name}}
        wf[swap_nid] = {"class_type": "ReActorFaceSwap",
                         "inputs": {
                             "enabled": True,
                             "input_image": img_ref,
                             "swap_model": "inswapper_128.onnx",
                             "facedetection": "retinaface_resnet50",
                             "face_restore_model": "codeformer-v0.1.0.pth",
                             "face_restore_visibility": face_restore_visibility,
                             "codeformer_weight": codeformer_weight,
                             "detect_gender_input": "no",
                             "detect_gender_source": "no",
                             "input_faces_index": str(i),
                             "source_faces_index": "0",
                             "console_log_level": 1,
                             "face_model": [fm_nid, 0],
                         }}
        img_ref = [swap_nid, 0]

    # Face restore pass on final result
    wf["60"] = {"class_type": "ReActorRestoreFace",
                "inputs": {"image": img_ref,
                           "facedetection": "retinaface_resnet50",
                           "model": "codeformer-v0.1.0.pth",
                           "visibility": face_restore_visibility,
                           "codeformer_weight": codeformer_weight}}
    img_ref = ["60", 0]

    # Output video
    wf["70"] = {"class_type": "CreateVideo",
                "inputs": {"fps": float(fps), "images": img_ref}}
    wf["71"] = {"class_type": "SaveVideo",
                "inputs": {"filename_prefix": "gimp_video_reactor",
                           "format": "auto", "codec": "auto",
                           "video": ["70", 0]}}
    wf["72"] = {"class_type": "SaveImage",
                "inputs": {"images": img_ref,
                           "filename_prefix": "gimp_video_reactor_frame"}}
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
        _update_spinner_status("Reading pixels (fallback export)...")
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

# ── Spinner status text ─────────────────────────────────────────────
# Module-level variable that _run_with_spinner polls to update its label.
# Call _update_spinner_status("...") from _run_* methods instead of
# Gimp.progress_init / Gimp.progress_set_text so the spinner window
# shows the current processing phase in real time.
_spinner_label_text = ""

def _update_spinner_status(text):
    """Set the spinner window's status label from any thread."""
    global _spinner_label_text
    _spinner_label_text = text


# ── Mask cache for inpaint ──────────────────────────────────────────
# Reuses the last-generated selection mask if the selection hasn't changed,
# avoiding redundant pixel scanning and upload.
_mask_cache = {
    "selection_hash": None,  # hash of selection bounds + channel data
    "mask_path": None,       # path to cached mask PNG
    "uploaded_name": None,   # name on ComfyUI server
    "server": None,          # which server it was uploaded to
}


def _cleanup_mask_cache():
    """Remove cached mask file from disk and reset the cache dict."""
    global _mask_cache
    if _mask_cache.get("mask_path") and os.path.exists(_mask_cache["mask_path"]):
        try:
            os.unlink(_mask_cache["mask_path"])
        except Exception:
            pass
    _mask_cache = {"selection_hash": None, "mask_path": None,
                   "uploaded_name": None, "server": None}


def _selection_hash(image):
    """Compute a hash of the current selection to detect changes."""
    import hashlib
    has_sel, x1, y1, x2, y2 = _get_selection_bounds(image)
    if not has_sel:
        return None
    # Hash the bounds + image ID (unique per image)
    key = f"{image.get_id()}:{x1},{y1},{x2},{y2}"
    return hashlib.md5(key.encode()).hexdigest()


# Clean stale mask cache on plugin load
_cleanup_mask_cache()

# Clean stale temp mask files from previous sessions
import glob as _glob_mod
for _f in _glob_mod.glob(os.path.join(tempfile.gettempdir(), "gimp_mask_*.png")):
    try:
        os.unlink(_f)
    except Exception:
        pass
for _f in _glob_mod.glob(os.path.join(tempfile.gettempdir(), "tmp*.png")):
    # Only delete if > 1 day old to avoid deleting active files
    try:
        if os.path.getmtime(_f) < time.time() - 86400:
            os.unlink(_f)
    except Exception:
        pass

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
            result = _api_post_json(server, "/prompt", {
                "prompt": workflow,
                "extra_pnginfo": {"workflow": workflow},
            })
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
    global _spinner_label_text
    _spinner_label_text = ""  # reset live status text
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
            elif not cancel_box[0]:
                # Pick up live status text from _update_spinner_status()
                live = _spinner_label_text
                if live:
                    label.set_text(live)
                elif label.get_text().startswith("Queued"):
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

# ═══════════════════════════════════════════════════════════════════════════
#  AutoSet — one-click optimal configuration for any dialog + model + task
# ═══════════════════════════════════════════════════════════════════════════
# The "A." button in every dialog calls _auto_configure() which sets all
# widgets to known-good values for the current model architecture and task.

_AUTOSET_PROMPTS = {
    "sd15": ("photorealistic, highly detailed, sharp focus, professional, 8k",
             "blurry, low quality, deformed, bad anatomy, watermark"),
    "sdxl": ("photorealistic, ultra detailed, sharp focus, professional photograph, natural lighting, 8k resolution",
             "blurry, low quality, worst quality, deformed, bad anatomy, watermark, text, cartoon"),
    "flux1dev": ("A highly detailed professional photograph with natural lighting and sharp focus throughout",
                 ""),
    "flux2klein": ("Detailed professional photograph, natural light, sharp, realistic",
                   ""),
    "zit": ("photo, detailed, sharp", "blurry, bad"),
    "illustrious": ("masterpiece, best quality, very aesthetic, absurdres, highly detailed",
                    "worst quality, low quality, lowres, bad anatomy"),
    "flux_kontext": ("A highly detailed professional photograph with natural lighting",
                     ""),
}

_AUTOSET_CFG = {
    "sd15": 7.0, "sdxl": 6.5, "zit": 2.0, "illustrious": 5.5,
    "flux1dev": 3.5, "flux2klein": 1.0, "flux_kontext": 3.5,
}

_AUTOSET_STEPS = {
    "sd15": 25, "sdxl": 30, "zit": 6, "illustrious": 28,
    "flux1dev": 25, "flux2klein": 20, "flux_kontext": 25,
}

_AUTOSET_DENOISE = {
    # (arch, mode) -> denoise value
    ("sd15", "img2img"): 0.60, ("sd15", "inpaint"): 0.75,
    ("sd15", "hallucinate"): 0.35, ("sd15", "seedv2r"): 0.40,
    ("sd15", "colorize"): 0.72, ("sd15", "style"): 0.60,
    ("sdxl", "img2img"): 0.60, ("sdxl", "inpaint"): 0.75,
    ("sdxl", "hallucinate"): 0.35, ("sdxl", "seedv2r"): 0.40,
    ("sdxl", "colorize"): 0.72, ("sdxl", "style"): 0.60,
    ("sdxl", "supir"): 0.30,
    ("illustrious", "img2img"): 0.55, ("illustrious", "inpaint"): 0.70,
    ("illustrious", "hallucinate"): 0.35,
    ("zit", "img2img"): 0.55, ("zit", "inpaint"): 0.70,
    ("zit", "hallucinate"): 0.30,
    ("flux1dev", "img2img"): 0.55, ("flux1dev", "inpaint"): 0.70,
    ("flux1dev", "hallucinate"): 0.35, ("flux1dev", "style"): 0.55,
    ("flux2klein", "img2img"): 0.55,
}

# (arch, mode) -> (cn1_key, cn1_strength, cn2_key, cn2_strength)
# cn1_key=None means "leave CN1 alone" (e.g. colorize has built-in lineart)
_AUTOSET_CN = {
    ("sdxl", "img2img"):     ("Off", 0.8, "Off", 0.5),
    ("sdxl", "inpaint"):     ("Off", 0.8, "Off", 0.5),
    ("sdxl", "hallucinate"): ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.4),
    ("sdxl", "seedv2r"):     ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Off", 0.5),
    ("sdxl", "colorize"):    (None, None, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.5),
    ("sdxl", "style"):       ("Depth (spatial) — SD1.5/SDXL/ZIT", 0.6, "Off", 0.5),
    ("sdxl", "supir"):       ("Tile (detail) — SD1.5/SDXL/ZIT", 0.6, "Off", 0.4),
    ("flux1dev", "img2img"): ("Flux Union Pro (all-in-one) — Flux only", 0.7, "Off", 0.5),
    ("flux1dev", "inpaint"): ("Flux Union Pro (all-in-one) — Flux only", 0.6, "Off", 0.5),
    ("flux1dev", "hallucinate"): ("Flux Union Pro (all-in-one) — Flux only", 0.7, "Off", 0.5),
    ("flux1dev", "seedv2r"):  ("Flux Union Pro (all-in-one) — Flux only", 0.7, "Off", 0.5),
    ("flux1dev", "style"):    ("Flux Union Pro (all-in-one) — Flux only", 0.6, "Off", 0.5),
    ("flux2klein", "img2img"): ("Flux Union Pro (all-in-one) — Flux only", 0.7, "Off", 0.5),
    ("sd15", "img2img"):     ("Off", 0.8, "Off", 0.5),
    ("sd15", "inpaint"):     ("Off", 0.8, "Off", 0.5),
    ("sd15", "hallucinate"): ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Off", 0.5),
    ("sd15", "seedv2r"):     ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Off", 0.5),
    ("sd15", "colorize"):    (None, None, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.5),
    ("sd15", "style"):       ("Depth (spatial) — SD1.5/SDXL/ZIT", 0.6, "Off", 0.5),
    ("zit", "img2img"):      ("ZIT Union (all modes) — ZIT only", 0.7, "Off", 0.5),
    ("zit", "inpaint"):      ("ZIT Union (all modes) — ZIT only", 0.7, "Off", 0.5),
    ("zit", "hallucinate"):  ("ZIT Union (all modes) — ZIT only", 0.7, "Off", 0.5),
    ("zit", "seedv2r"):      ("ZIT Union (all modes) — ZIT only", 0.7, "Off", 0.5),
    ("illustrious", "img2img"):     ("Off", 0.8, "Off", 0.5),
    ("illustrious", "inpaint"):     ("Off", 0.8, "Off", 0.5),
    ("illustrious", "hallucinate"): ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.4),
    ("illustrious", "seedv2r"):     ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Off", 0.5),
    ("illustrious", "colorize"):    (None, None, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.5),
    ("illustrious", "style"):       ("Depth (spatial) — SD1.5/SDXL/ZIT", 0.6, "Off", 0.5),
}

# (arch, mode) -> list of (lora_name, model_strength, clip_strength)
_AUTOSET_LORAS = {
    ("sdxl", "img2img"): [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.6, 0.6)],
    ("sdxl", "inpaint"): [],
    ("sdxl", "hallucinate"): [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.5, 0.5)],
    ("sdxl", "seedv2r"): [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.5, 0.5)],
    ("sdxl", "style"): [],
    ("sdxl", "supir"): [],
    ("flux1dev", "img2img"): [],
    ("flux1dev", "inpaint"): [],
    ("flux2klein", "img2img"): [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
    ("sd15", "img2img"): [],
    ("sd15", "hallucinate"): [],
    ("zit", "img2img"): [],
    ("illustrious", "img2img"): [],
}


def _auto_configure(dialog, mode="img2img"):
    """Auto-configure all dialog widgets to optimal values for the current model + task.

    Called by the 'A.' button in every dialog. Reads the current model preset,
    determines architecture, and sets prompts, cfg, steps, ControlNet, LoRAs,
    and denoise to known-good values.
    """
    # Determine architecture from the dialog's model/preset combo
    arch = "sdxl"  # fallback
    if hasattr(dialog, 'preset_combo'):
        idx = dialog.preset_combo.get_active()
        if 0 <= idx < len(MODEL_PRESETS):
            arch = MODEL_PRESETS[idx].get("arch", "sdxl")
    elif hasattr(dialog, '_model_combo_ref'):
        # Non-PresetDialog tools store a reference to their model_combo
        mc = dialog._model_combo_ref
        idx = mc.get_active()
        aid = mc.get_active_id()
        if aid and aid.isdigit():
            idx = int(aid)
        if 0 <= idx < len(MODEL_PRESETS):
            arch = MODEL_PRESETS[idx].get("arch", "sdxl")

    # Set prompts
    pos, neg = _AUTOSET_PROMPTS.get(arch, _AUTOSET_PROMPTS["sdxl"])
    if hasattr(dialog, 'prompt_tv'):
        dialog.prompt_tv.get_buffer().set_text(pos)
    if hasattr(dialog, 'neg_tv'):
        dialog.neg_tv.get_buffer().set_text(neg)

    # Set CFG
    if hasattr(dialog, 'cfg_spin'):
        dialog.cfg_spin.set_value(_AUTOSET_CFG.get(arch, 6.5))

    # Set steps
    if hasattr(dialog, 'steps_spin'):
        dialog.steps_spin.set_value(_AUTOSET_STEPS.get(arch, 30))

    # Set denoise
    dn = _AUTOSET_DENOISE.get((arch, mode))
    if dn is not None and hasattr(dialog, 'denoise_spin') and dialog.denoise_spin:
        dialog.denoise_spin.set_value(dn)

    # Set ControlNet 1
    cn_vals = _AUTOSET_CN.get((arch, mode))
    if cn_vals:
        cn1_key, cn1_str, cn2_key, cn2_str = cn_vals
        # CN1
        if cn1_key is not None:
            cn1_combo = getattr(dialog, '_cn_mode_combo', None) or getattr(dialog, '_autoset_cn1_combo', None)
            if cn1_combo:
                cn1_combo.set_active_id(cn1_key)
            cn1_spin = getattr(dialog, '_cn_strength_spin', None) or getattr(dialog, '_autoset_cn1_spin', None)
            if cn1_spin and cn1_str is not None:
                cn1_spin.set_value(cn1_str)
        # CN2
        cn2_combo = getattr(dialog, '_cn_mode_combo_2', None) or getattr(dialog, '_autoset_cn2_combo', None)
        if cn2_combo:
            cn2_combo.set_active_id(cn2_key)
        cn2_spin = getattr(dialog, '_cn_strength_spin_2', None) or getattr(dialog, '_autoset_cn2_spin', None)
        if cn2_spin and cn2_str is not None:
            cn2_spin.set_value(cn2_str)

    # Set LoRAs (only for dialogs with lora_rows like PresetDialog)
    loras = _AUTOSET_LORAS.get((arch, mode), [])
    if hasattr(dialog, 'lora_rows'):
        # Clear all LoRA slots first
        for combo, ms_spin, cs_spin in dialog.lora_rows:
            combo.set_active(0)  # (none)
            ms_spin.set_value(1.0)
            cs_spin.set_value(1.0)
        # Set new LoRAs
        for i, (lname, ms, cs) in enumerate(loras):
            if i < len(dialog.lora_rows):
                combo, ms_spin, cs_spin = dialog.lora_rows[i]
                # Try to set by ID; if not found, leave as (none)
                combo.set_active_id(lname)
                ms_spin.set_value(ms)
                cs_spin.set_value(cs)


def _shrink_on_collapse(expander, dlg):
    """Shrink dialog when an expander collapses so buttons move up."""
    def _on_toggle(exp, param):
        if not exp.get_expanded():
            # Force GTK to recalculate minimum size
            GLib.idle_add(lambda: dlg.resize(dlg.get_allocated_width(), 1) or False)
    expander.connect("notify::expanded", _on_toggle)


def _make_autoset_button(dialog, mode="img2img"):
    """Create a small 'A.' button that calls _auto_configure on click.

    Returns a Gtk.Box containing the button, suitable for packing at the
    top of any dialog content area.
    """
    auto_btn = Gtk.Button(label="A.")
    auto_btn.set_tooltip_text(
        "AutoSet: auto-configure ALL parameters for optimal results.\n"
        "Sets prompts, CFG, steps, LoRAs, ControlNet, and denoise\n"
        "based on your selected model and task.")
    auto_btn.set_size_request(32, -1)
    auto_btn.connect("clicked", lambda btn: _auto_configure(dialog, mode))
    top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    top_row.pack_end(auto_btn, False, False, 0)
    return top_row


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

        # Branded header (keep compact text, skip large banner image to save space)
        _hdr = _make_branded_header()
        if _hdr:
            box.pack_start(_hdr, False, False, 0)

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
            self.preset_combo.append(str(i), _model_label(p, mode))
        # Default to favourite model from settings, or first model
        fav = _load_config().get("favourite_model", -1)
        if 0 <= fav < len(MODEL_PRESETS):
            self.preset_combo.set_active(fav)
        else:
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

        # ── Style Enhancement Preset dropdown (img2img & txt2img) ─────
        self._style_combo = None
        if mode in ("img2img", "txt2img"):
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
            box.pack_start(Gtk.Label(label="Style Enhancement:", xalign=0), False, False, 0)
            self._style_combo = Gtk.ComboBoxText()
            self._style_combo.set_tooltip_text(
                "Apply a style/effect preset on top of your prompt.\n"
                "Appends style-specific prompt text and loads matching LoRAs.\n"
                "Select '(none)' to use your own prompt only.")
            for i, sp in enumerate(IMG2IMG_STYLE_PRESETS):
                self._style_combo.append(str(i), sp["label"])
            self._style_combo.set_active(0)
            self._style_combo.connect("changed", self._on_style_changed)
            box.pack_start(self._style_combo, False, False, 0)

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

        # ── Advanced Parameters (collapsible) ────────────────────────────
        adv_exp = Gtk.Expander(label="\u25b8 Advanced Parameters")
        _shrink_on_collapse(adv_exp, self)
        adv_exp.set_expanded(False)
        adv_exp.set_tooltip_text("Sampler, scheduler, dimensions, steps, CFG, denoise, and seed.\nDefaults are auto-filled by the model preset.")
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        adv_box.set_margin_start(4); adv_box.set_margin_top(4)

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

        adv_box.pack_start(grid, False, False, 0)
        adv_exp.add(adv_box)
        box.pack_start(adv_exp, False, False, 0)

        # ── LoRAs & Style (collapsible) ──────────────────────────────────
        lora_exp = Gtk.Expander(label="\u25b8 LoRAs (3 slots)")
        _shrink_on_collapse(lora_exp, self)
        lora_exp.set_expanded(False)
        lora_exp.set_tooltip_text("LoRA add-on models that adjust style, subject, or detail.\nEach slot lets you blend a LoRA with adjustable strength.")
        lora_exp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lora_exp_box.set_margin_start(4); lora_exp_box.set_margin_top(4)

        lora_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lora_hdr.pack_start(Gtk.Label(label="LoRA (optional):", xalign=0), False, False, 0)
        self._lora_fetch_btn = Gtk.Button(label="Fetch LoRAs")
        self._lora_fetch_btn.set_tooltip_text("Download the list of available LoRAs from the server.\nLoRAs are small add-on models that adjust style or subject.")
        self._lora_fetch_btn.connect("clicked", self._on_fetch_loras)
        lora_hdr.pack_end(self._lora_fetch_btn, False, False, 0)
        lora_exp_box.pack_start(lora_hdr, False, False, 0)

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

            combo.connect("changed", self._on_lora_combo_changed, ms, cs)
            self.lora_rows.append((combo, ms, cs))
            self._lora_box.pack_start(row, False, False, 0)
        lora_exp_box.pack_start(self._lora_box, False, False, 0)
        lora_exp.add(lora_exp_box)
        box.pack_start(lora_exp, False, False, 0)

        # ── ControlNet (collapsible) ──────────────────────────────────────
        if mode in ("img2img", "inpaint"):
            cn_exp = Gtk.Expander(label="\u25b8 ControlNet (2 guides)")
            _shrink_on_collapse(cn_exp, self)
            cn_exp.set_expanded(False)
            cn_exp.set_tooltip_text("ControlNet preserves structure from your source image.\nCN1 + CN2 can be combined for dual guidance (e.g. Tile + Depth).")
            cn_exp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            cn_exp_box.set_margin_start(4); cn_exp_box.set_margin_top(4)

            cn_exp_box.pack_start(Gtk.Label(label="ControlNet Structure Guide:", xalign=0), False, False, 0)

            self._cn_mode_combo = Gtk.ComboBoxText()
            self._cn_mode_combo.set_tooltip_text(
                "ControlNet preserves structure from your source image.\n\n"
                "Modes:\n"
                "  Tile \u2014 preserves layout + adds detail (BEST for upscale/hallucinate)\n"
                "  Canny \u2014 follows edges (good for architecture, objects)\n"
                "  Depth \u2014 preserves 3D depth (good for portraits, scenes)\n"
                "  OpenPose \u2014 follows body pose (portraits, figure work)\n"
                "  Lineart \u2014 follows line drawing (illustration, sketches)\n"
                "  Scribble \u2014 loose sketch guide (creative, abstract)\n\n"
                "Recommended pairings:\n"
                "  Tile + Depth \u2014 structure-aware detail (hallucination)\n"
                "  OpenPose + Canny \u2014 body pose + edge detail (portraits)\n"
                "  Depth + Lineart \u2014 spatial + line structure (scenes)\n\n"
                "\u26a0 SD1.5 and SDXL use DIFFERENT ControlNet models.\n"
                "The correct model is auto-selected based on your checkpoint.")
            for key in CONTROLNET_GUIDE_MODES:
                self._cn_mode_combo.append(key, key)
            self._cn_mode_combo.set_active(0)  # "Off" by default
            cn_exp_box.pack_start(self._cn_mode_combo, False, False, 0)

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

            cn_exp_box.pack_start(cn_row, False, False, 0)

            # ControlNet 2 (optional second guide)
            cn_exp_box.pack_start(Gtk.Label(label="ControlNet 2 (combine):", xalign=0), False, False, 0)
            self._cn_mode_combo_2 = Gtk.ComboBoxText()
            self._cn_mode_combo_2.set_tooltip_text(
                "Optional second ControlNet to combine with the first.\n"
                "Both guides are applied simultaneously \u2014 the AI follows both.\n\n"
                "Best combos:\n"
                "  CN1: Tile + CN2: Depth \u2014 detail + structure\n"
                "  CN1: OpenPose + CN2: Canny \u2014 pose + edges\n"
                "  CN1: Depth + CN2: Lineart \u2014 spatial + line guide\n\n"
                "Keep CN2 strength lower than CN1 (e.g., 0.4 vs 0.7)\n"
                "to let the primary guide dominate.")
            for key in CONTROLNET_GUIDE_MODES:
                self._cn_mode_combo_2.append(key, key)
            self._cn_mode_combo_2.set_active(0)  # "Off" by default
            cn_exp_box.pack_start(self._cn_mode_combo_2, False, False, 0)

            # CN2 strength
            cn_row_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            cn_row_2.pack_start(Gtk.Label(label="CN2 Strength:"), False, False, 0)
            self._cn_strength_spin_2 = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
            self._cn_strength_spin_2.set_digits(2)
            self._cn_strength_spin_2.set_value(0.6)
            cn_row_2.pack_start(self._cn_strength_spin_2, False, False, 0)
            cn_exp_box.pack_start(cn_row_2, False, False, 0)

            cn_exp.add(cn_exp_box)
            box.pack_start(cn_exp, False, False, 0)
        else:
            self._cn_mode_combo = None
            self._cn_strength_spin = None
            self._cn_start_spin = None
            self._cn_end_spin = None
            self._cn_mode_combo_2 = None
            self._cn_strength_spin_2 = None

        # Mode label
        if mode == "img2img":
            box.pack_start(Gtk.Label(label="Sends current canvas through model preset.", xalign=0), False, False, 0)
        elif mode == "txt2img":
            box.pack_start(Gtk.Label(label="Generate new image from prompt only.", xalign=0), False, False, 0)

        # WD Tagger button — sends image to ComfyUI, gets tags back into prompt
        if mode != "txt2img":
            wd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self._wd_tag_btn = Gtk.Button(label="Tag Image (WD Tagger)")
            self._wd_tag_btn.set_tooltip_text(
                "Sends your image to ComfyUI's WD14 Tagger and pastes the\n"
                "detected tags into your prompt. Review and edit before generating.\n\n"
                "Tags like: '1girl, brown hair, outdoors, smile, sunlight'\n"
                "Requires the WD14Tagger node (pysssss) in ComfyUI.")
            self._wd_tag_btn.connect("clicked", self._on_wd_tag_clicked)
            wd_row.pack_start(self._wd_tag_btn, False, False, 0)
            self._wd_status = Gtk.Label(label="")
            self._wd_status.set_xalign(0)
            wd_row.pack_start(self._wd_status, True, True, 0)
            box.pack_start(wd_row, False, False, 0)

        # Runs spinner
        _add_runs_spinner(self, box)

        # Advanced custom workflow
        exp = Gtk.Expander(label="Advanced: Custom Workflow JSON (overrides everything)")
        _shrink_on_collapse(exp, self)
        exp.set_tooltip_text("Paste a raw ComfyUI workflow JSON here to bypass all presets.\nOnly for advanced users who export workflows from ComfyUI.")
        self.wf_tv = Gtk.TextView()
        self.wf_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.wf_tv.set_monospace(True)
        sw3 = Gtk.ScrolledWindow(); sw3.set_min_content_height(80); sw3.add(self.wf_tv)
        exp.add(sw3)
        box.pack_start(exp, False, False, 0)

        # AutoSet button — tiny "A." in the top area
        box.pack_start(_make_autoset_button(self, mode), False, False, 0)

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
            self._check_style_preset_availability()
        def on_err(e):
            self._all_lora_names = []
            self._conn_label.set_markup(f'<span color="red">⚠ Cannot connect to {server}</span>')
            self._refresh_lora_combos()
            self._check_style_preset_availability()
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
                short = lname.replace("\\", "/").rsplit("/", 1)[-1]
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

    def _on_lora_combo_changed(self, combo, model_spin, clip_spin):
        """When a LoRA is selected, look up metadata for trigger words and optimal strength."""
        lora_id = combo.get_active_id()
        if not lora_id or lora_id == "none":
            return
        # Extract basename from the LoRA path (e.g. "SDXL\\Body\\HandFineTuning_XL.safetensors" -> "HandFineTuning_XL.safetensors")
        basename = lora_id.rsplit("\\", 1)[-1] if "\\" in lora_id else lora_id
        if "/" in basename:
            basename = basename.rsplit("/", 1)[-1]
        meta = LORA_METADATA.get(basename)
        if not meta:
            return
        # Set optimal strength
        model_spin.set_value(meta["strength"])
        clip_spin.set_value(meta["strength"])
        # Append trigger words to prompt (avoid duplicates)
        buf = self.prompt_tv.get_buffer()
        start, end = buf.get_bounds()
        current_text = buf.get_text(start, end, False)
        trigger = meta["trigger"]
        if trigger not in current_text:
            if current_text and not current_text.rstrip().endswith(","):
                buf.insert(end, f", {trigger}")
            else:
                buf.insert(end, f" {trigger}" if current_text else trigger)

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
        # Re-apply style preset if one is active (to update LoRAs for new arch)
        if self._style_combo and self._style_combo.get_active() > 0:
            self._on_style_changed(self._style_combo)
        # Update style preset availability labels for new arch
        if self._all_lora_names:
            self._check_style_preset_availability()

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

    def _on_wd_tag_clicked(self, btn):
        """Send the current GIMP image to WD14Tagger and paste tags into prompt."""
        server = self.server_entry.get_text().strip()
        if not server:
            self._wd_status.set_markup('<span foreground="#FF5252">No server URL</span>')
            return

        self._wd_tag_btn.set_sensitive(False)
        self._wd_status.set_text("Exporting image...")

        def _do_tag():
            try:
                # Get the current image from GIMP
                images = Gimp.get_images()
                if not images:
                    return None, "No image open in GIMP"
                image = images[0]

                # Export to temp file
                tmp = _export_image_to_tmp(image)

                # Upload to ComfyUI
                self._wd_status.set_text("Uploading...")
                uname = f"wd_tag_{uuid.uuid4().hex[:8]}.png"
                _upload_image_sync(server, tmp, uname)
                os.unlink(tmp)

                # Build a minimal WD14Tagger-only workflow
                wf = {
                    "1": {"class_type": "LoadImage",
                          "inputs": {"image": uname}},
                    "2": {"class_type": "WD14Tagger|pysssss",
                          "inputs": {
                              "image": ["1", 0],
                              "model": "wd-eva02-large-tagger-v3",
                              "threshold": 0.35,
                              "character_threshold": 0.85,
                              "replace_underscore": True,
                              "trailing_comma": True,
                              "exclude_tags": "",
                          }},
                    # ShowText is an output_node — its STRING value appears in history
                    "3": {"class_type": "ShowText|pysssss",
                          "inputs": {"text": ["2", 0]}},
                }

                # Submit and wait
                self._wd_status.set_text("Tagging...")
                result = _api_post_json(server, "/prompt", {"prompt": wf, "extra_pnginfo": {"workflow": wf}})
                prompt_id = result.get("prompt_id")
                if not prompt_id:
                    return None, "ComfyUI did not return a prompt_id"

                # Poll for completion
                deadline = time.time() + 60
                while time.time() < deadline:
                    try:
                        history = _api_get(server, f"/history/{prompt_id}")
                        if prompt_id in history:
                            # Extract the STRING output from node 2 (WD14Tagger)
                            outputs = history[prompt_id].get("outputs", {})
                            for nid, nout in outputs.items():
                                if "text" in nout:
                                    # Some versions return text directly
                                    tags = nout["text"]
                                    if isinstance(tags, list):
                                        tags = tags[0]
                                    return tags, None
                                if "string" in nout:
                                    tags = nout["string"]
                                    if isinstance(tags, list):
                                        tags = tags[0]
                                    return tags, None
                            # Fallback: tagger succeeded but we can't read STRING output
                            # (WD14Tagger outputs STRING which doesn't appear in history)
                            return None, "Tagger ran but tags not in history output.\nTry the WD Tagger node directly in ComfyUI."
                    except Exception:
                        pass
                    time.sleep(1)
                return None, "Tagger timed out (60s)"
            except Exception as e:
                return None, str(e)

        def _on_done(result):
            tags, error = result
            self._wd_tag_btn.set_sensitive(True)
            if error:
                self._wd_status.set_markup(f'<span foreground="#FF5252">{error}</span>')
            elif tags:
                # Prepend tags to the prompt
                buf = self.prompt_tv.get_buffer()
                existing = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
                if existing.strip():
                    new_text = f"{tags}, {existing}"
                else:
                    new_text = tags
                buf.set_text(new_text)
                tag_count = len([t for t in tags.split(",") if t.strip()])
                self._wd_status.set_markup(f'<span foreground="#00E676">{tag_count} tags added</span>')

        def _on_err(e):
            self._wd_tag_btn.set_sensitive(True)
            self._wd_status.set_markup(f'<span foreground="#FF5252">{e}</span>')

        _async_fetch(_do_tag, _on_done, _on_err)

    def _on_style_changed(self, combo):
        """Apply a style enhancement preset: load its LoRAs into slots."""
        sidx = combo.get_active()
        if sidx <= 0:
            return  # "(none)" — don't touch anything
        sp = IMG2IMG_STYLE_PRESETS[sidx]

        # Auto-select matching LoRAs for current model architecture
        midx = self.preset_combo.get_active()
        arch = MODEL_PRESETS[midx]["arch"] if midx >= 0 else "sdxl"
        rec_loras = sp["loras"].get(arch, [])

        # Clear all LoRA slots first
        for combo_w, ms, cs in self.lora_rows:
            combo_w.set_active(0)  # "(none)"
            ms.set_value(1.0)
            cs.set_value(1.0)

        # Fill LoRA slots with style's LoRAs (if they exist on the server)
        slot = 0
        for lora_path, model_str, clip_str in rec_loras:
            if slot >= len(self.lora_rows):
                break
            combo_w, ms, cs = self.lora_rows[slot]
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
                continue

    def _check_style_preset_availability(self):
        """Mark style presets whose LoRAs are missing on the server.

        Updates the style dropdown labels with a '(missing LoRA)' suffix
        when a preset's LoRAs for the current architecture are not available
        in self._all_lora_names.
        """
        if not self._style_combo:
            return
        midx = self.preset_combo.get_active()
        arch = MODEL_PRESETS[midx]["arch"] if midx >= 0 else "sdxl"
        active = self._style_combo.get_active()
        self._style_combo.remove_all()
        for i, sp in enumerate(IMG2IMG_STYLE_PRESETS):
            label = sp["label"]
            if i > 0:
                # Check if this preset's LoRAs for the current arch are available
                rec_loras = sp["loras"].get(arch, [])
                if rec_loras:
                    all_found = all(
                        any(lname == lp for lname in self._all_lora_names)
                        for lp, _ms, _cs in rec_loras
                    )
                    if not all_found:
                        label = label + "  (missing LoRA)"
            self._style_combo.append(str(i), label)
        if 0 <= active < len(IMG2IMG_STYLE_PRESETS):
            self._style_combo.set_active(active)
        else:
            self._style_combo.set_active(0)

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
        # ControlNet 2
        if self._cn_mode_combo_2:
            data["cn_mode_2"] = self._cn_mode_combo_2.get_active_id()
            data["cn_strength_2"] = self._cn_strength_spin_2.get_value()
        # Scene preset
        if self._scene_combo:
            data["scene_idx"] = self._scene_combo.get_active()
        # Style preset
        if self._style_combo:
            data["style_idx"] = self._style_combo.get_active()
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
        # ControlNet 2
        if self._cn_mode_combo_2 and "cn_mode_2" in p:
            self._cn_mode_combo_2.set_active_id(p["cn_mode_2"])
        if self._cn_strength_spin_2 and "cn_strength_2" in p:
            self._cn_strength_spin_2.set_value(p["cn_strength_2"])
        # Scene preset
        if self._scene_combo and "scene_idx" in p:
            self._scene_combo.set_active(p["scene_idx"])
        # Style preset
        if self._style_combo and "style_idx" in p:
            sidx = p["style_idx"]
            if 0 <= sidx < len(IMG2IMG_STYLE_PRESETS):
                self._style_combo.set_active(sidx)
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
        # Multi-LoRA strength optimization: reduce each LoRA's strength
        # when multiple are active to prevent over-saturation
        if len(loras) == 2:
            for l in loras:
                l["strength_model"] *= 0.85
                l["strength_clip"] *= 0.85
        elif len(loras) >= 3:
            for l in loras:
                l["strength_model"] *= 0.75
                l["strength_clip"] *= 0.75
        # ControlNet
        cn_mode = self._cn_mode_combo.get_active_id() if self._cn_mode_combo else "Off"
        controlnet = {
            "mode": cn_mode,
            "strength": self._cn_strength_spin.get_value() if self._cn_strength_spin else 0.8,
            "start_percent": self._cn_start_spin.get_value() if self._cn_start_spin else 0.0,
            "end_percent": self._cn_end_spin.get_value() if self._cn_end_spin else 1.0,
        }
        # ControlNet 2
        cn_mode_2 = self._cn_mode_combo_2.get_active_id() if self._cn_mode_combo_2 else "Off"
        controlnet_2 = {
            "mode": cn_mode_2,
            "strength": self._cn_strength_spin_2.get_value() if self._cn_strength_spin_2 else 0.6,
            "start_percent": 0.0,
            "end_percent": 1.0,
        }
        # Style preset — merge style prompt/negative/LoRAs when selected
        style_preset = None
        if self._style_combo and self._style_combo.get_active() > 0:
            style_preset = IMG2IMG_STYLE_PRESETS[self._style_combo.get_active()]

        prompt_text = self._buf_text(self.prompt_tv)
        negative_text = self._buf_text(self.neg_tv)

        if style_preset:
            # Append style prompt/negative to user text
            if style_preset["prompt"]:
                prompt_text = (prompt_text + ", " + style_preset["prompt"]) if prompt_text else style_preset["prompt"]
            if style_preset["negative"]:
                negative_text = (negative_text + ", " + style_preset["negative"]) if negative_text else style_preset["negative"]
            # Merge style LoRAs with manually selected LoRAs
            midx = self.preset_combo.get_active()
            arch = MODEL_PRESETS[midx]["arch"] if midx >= 0 else "sdxl"
            style_loras = style_preset["loras"].get(arch, [])
            existing_names = {l["name"] for l in loras}
            for lora_path, model_str, clip_str in style_loras:
                if lora_path not in existing_names:
                    loras.append({
                        "name": lora_path,
                        "strength_model": model_str,
                        "strength_clip": clip_str,
                    })

        return {
            "server": self.server_entry.get_text().strip(),
            "preset": preset,
            "prompt": prompt_text,
            "negative": negative_text,
            "seed": seed,
            "loras": loras,
            "controlnet": controlnet,
            "controlnet_2": controlnet_2,
            "custom_workflow": custom_wf if custom_wf else None,
            "runs": int(self._runs_spin.get_value()),
            "style_preset": style_preset,
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
        self.shift_spin.set_digits(1); self.shift_spin.set_value(5.0)
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

        # Turbo mode (LightX2V accelerator)
        self.turbo_check = Gtk.CheckButton(label="Turbo (LightX2V 4-step)")
        self.turbo_check.set_active(True)
        self.turbo_check.set_tooltip_text(
            "Enable LightX2V accelerator LoRAs for ~4x faster generation.\n"
            "Uses 4 total steps (2 per model) instead of 30.\n"
            "Quality is slightly lower but generation is near-instant.\n\n"
            "Disable for maximum quality at the cost of much longer generation.")
        def _on_turbo_toggle(cb):
            if cb.get_active():
                self.steps_spin.set_value(4)
                self.second_step_spin.set_value(2)
            else:
                self.steps_spin.set_value(20)
                self.second_step_spin.set_value(10)
        self.turbo_check.connect("toggled", _on_turbo_toggle)
        grid.attach(self.turbo_check, 0, 5, 4, 1)
        # Apply turbo defaults
        _on_turbo_toggle(self.turbo_check)

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
        self.upscale_spin.set_digits(2); self.upscale_spin.set_value(2.5)
        self.upscale_spin.set_tooltip_text("RTX upscale factor. 2.5 = recommended (from canon workflow).")
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
        self.loop_check = Gtk.CheckButton(label="Loop Video")
        self.loop_check.set_active(False)
        self.loop_check.set_tooltip_text("Generate a seamless looping video.\nUses the same image as both first and last frame\nso the video loops perfectly.")
        row2.pack_start(self.loop_check, False, False, 0)
        pp_box.pack_start(row2, False, False, 0)

        pp_frame.add(pp_box)
        box.pack_start(pp_frame, False, False, 0)

        # LoRA section — 3 high-noise slots + 3 low-noise slots
        lora_frame = Gtk.Frame(label="LoRAs (3 high-noise + 3 low-noise)")
        lora_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lora_box.set_margin_start(8); lora_box.set_margin_end(8)
        lora_box.set_margin_top(4); lora_box.set_margin_bottom(8)

        self._lora_fetch_btn = Gtk.Button(label="Fetch Wan LoRAs")
        self._lora_fetch_btn.set_tooltip_text("Download available Wan video LoRAs from the server.\nWan 2.2 uses PAIRED LoRAs: one for the high-noise model, one for the low-noise model.\nPick the high-noise variant in the top 3 slots and the matching low-noise variant in the bottom 3.")
        self._lora_fetch_btn.connect("clicked", self._on_fetch_loras)
        lora_box.pack_start(self._lora_fetch_btn, False, False, 0)

        def _make_lora_slots(parent, label_text, tooltip, count=3):
            parent.pack_start(Gtk.Label(label=label_text, xalign=0), False, False, 2)
            rows = []
            for i in range(count):
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                combo = Gtk.ComboBoxText()
                combo.append("none", "(none)")
                combo.set_active(0)
                combo.set_hexpand(True)
                combo.set_tooltip_text(tooltip)
                row.pack_start(combo, True, True, 0)
                row.pack_start(Gtk.Label(label="Str:"), False, False, 0)
                strength = Gtk.SpinButton.new_with_range(-2.0, 2.0, 0.05)
                strength.set_digits(2); strength.set_value(1.0)
                strength.set_tooltip_text("LoRA strength. 1.0 = full effect.")
                row.pack_start(strength, False, False, 0)
                parent.pack_start(row, False, False, 0)
                rows.append((combo, strength))
            return rows

        self.lora_rows_high = _make_lora_slots(
            lora_box, "High-noise model LoRAs:",
            "LoRA applied to the HIGH-noise model (first sampling pass).\nPick the 'high' or 'HIGH' variant of your LoRA here.")
        self.lora_rows_low = _make_lora_slots(
            lora_box, "Low-noise model LoRAs:",
            "LoRA applied to the LOW-noise model (second sampling pass).\nPick the 'low' or 'LOW' variant of your LoRA here.")
        # Keep combined list for refresh_lora_combos compatibility
        self.lora_rows = self.lora_rows_high + self.lora_rows_low

        lora_frame.add(lora_box)
        box.pack_start(lora_frame, False, False, 0)

        # ── User saved presets ──────────────────────────────────────────
        _add_preset_ui(self, box, "wan_i2v")

        # Runs spinner
        _add_runs_spinner(self, box)

        box.show_all()

        # Auto-fetch LoRAs on dialog open (so user doesn't have to click Fetch)
        try:
            server = self.server_entry.get_text().strip()
            self._all_wan_loras = _fetch_wan_video_loras(server)
            self._refresh_lora_combos()
        except Exception:
            pass

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

        # Auto-select recommended LoRAs — route high/low to correct slots
        if vp["loras"] and self._wan_loras:
            def _set_lora_in_rows(rows, lora_name, lora_str):
                """Find lora_name in the combo items and select it."""
                for row_combo, row_strength in rows:
                    if row_combo.get_active_id() == "none":
                        for j, name in enumerate(self._wan_loras):
                            if name == lora_name or name.endswith(lora_name):
                                row_combo.set_active(j + 1)
                                row_strength.set_value(lora_str)
                                return True
                        return False
                return False

            for lora_name, lora_str in vp["loras"]:
                # Determine if this is a high or low noise LoRA
                name_lower = lora_name.lower()
                is_high = any(m in name_lower for m in ["high", "_h_", "_h."])
                is_low = any(m in name_lower for m in ["low", "_l_", "_l."])
                if is_high:
                    _set_lora_in_rows(self.lora_rows_high, lora_name, lora_str)
                elif is_low:
                    _set_lora_in_rows(self.lora_rows_low, lora_name, lora_str)
                else:
                    # Unknown — try high first, then low
                    if not _set_lora_in_rows(self.lora_rows_high, lora_name, lora_str):
                        _set_lora_in_rows(self.lora_rows_low, lora_name, lora_str)

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
            "turbo": self.turbo_check.get_active(),
            "loop": self.loop_check.get_active(),
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
        self.shift_spin.set_value(p.get("shift", 5.0))
        self.second_step_spin.set_value(p.get("second_step", 20))
        self.seed_spin.set_value(p.get("seed", -1))
        self.turbo_check.set_active(p.get("turbo", True))
        self.loop_check.set_active(p.get("loop", False))
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

        loras_high = []
        for combo, strength in self.lora_rows_high:
            lid = combo.get_active_id()
            if lid and lid != "none":
                loras_high.append((lid, strength.get_value()))
        loras_low = []
        for combo, strength in self.lora_rows_low:
            lid = combo.get_active_id()
            if lid and lid != "none":
                loras_low.append((lid, strength.get_value()))

        return {
            "server": self.server_entry.get_text().strip(),
            "all_server_loras": list(self._all_wan_loras),
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
            "turbo": self.turbo_check.get_active(),
            "loop": self.loop_check.get_active(),
            "loras": None,
            "loras_high": loras_high or None,
            "loras_low": loras_low or None,
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
        row.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry(); self.server_entry.set_text(server_url); self.server_entry.set_hexpand(True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        row.pack_start(self.server_entry, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Source face image file chooser
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Source Face Image:"), False, False, 0)
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
        row.pack_start(self.source_chooser, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Analysis model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Analysis Model:"), False, False, 0)
        self.analysis_combo = Gtk.ComboBoxText()
        self.analysis_combo.set_tooltip_text("Face detection model. buffalo_l is the most accurate.\nSmaller models (buffalo_m, buffalo_sc) are faster but less reliable.")
        for m in ["buffalo_l", "antelopev2", "buffalo_m", "buffalo_sc"]:
            self.analysis_combo.append(m, m)
        self.analysis_combo.set_active_id("buffalo_l")
        self.analysis_combo.set_hexpand(True)
        row.pack_start(self.analysis_combo, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Swap model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Swap Model:"), False, False, 0)
        self.swap_combo = Gtk.ComboBoxText()
        self.swap_combo.set_tooltip_text("Face swap model. inswapper_128 is standard.\nfp16 variant uses less VRAM but may be slightly less accurate.")
        for m in ["inswapper_128.onnx", "inswapper_128_fp16.onnx"]:
            self.swap_combo.append(m, m)
        self.swap_combo.set_active_id("inswapper_128.onnx")
        self.swap_combo.set_hexpand(True)
        row.pack_start(self.swap_combo, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Face index
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Face Index:"), False, False, 0)
        self.face_idx = Gtk.Entry(); self.face_idx.set_text("0")
        self.face_idx.set_tooltip_text("0 = first face, comma-separated for multiple")
        self.face_idx.set_hexpand(True)
        row.pack_start(self.face_idx, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Fetch models from server
        fetch_btn = Gtk.Button(label="Fetch Models from Server")
        fetch_btn.connect("clicked", self._on_fetch)
        box.pack_start(fetch_btn, False, False, 0)

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
        row.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry(); self.server_entry.set_text(server_url); self.server_entry.set_hexpand(True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        row.pack_start(self.server_entry, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Model preset
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Model Preset:"), False, False, 0)
        self.preset_combo = Gtk.ComboBoxText()
        self.preset_combo.set_tooltip_text("Base checkpoint model for generation.\nSD1.5 and SDXL are supported depending on the FaceID type.")
        for key in FACEID_PRESETS:
            self.preset_combo.append(key, key)
        self.preset_combo.set_active(0)
        self.preset_combo.set_hexpand(True)
        row.pack_start(self.preset_combo, False, False, 0)
        box.pack_start(row, False, False, 0)

        # FaceID preset
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="FaceID Type:"), False, False, 0)
        self.faceid_combo = Gtk.ComboBoxText()
        self.faceid_combo.set_tooltip_text("FaceID variant to use. FACEID PLUS V2 is recommended for most cases.\nPORTRAIT modes give stronger face transfer. Some are model-specific.")
        for p in ["FACEID", "FACEID PLUS - SD1.5 only", "FACEID PLUS V2",
                   "FACEID PORTRAIT (style transfer)", "FACEID PORTRAIT UNNORM - SDXL only (strong)"]:
            self.faceid_combo.append(p, p)
        self.faceid_combo.set_active_id("FACEID PLUS V2")
        self.faceid_combo.set_hexpand(True)
        row.pack_start(self.faceid_combo, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Source face image
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Face Reference:"), False, False, 0)
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
        row.pack_start(self.source_chooser, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Prompt
        box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        self.prompt_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_size_request(-1, 60)
        self.prompt_tv.set_tooltip_text("Describe the scene around the face. The face identity comes from the reference image.\nExample: 'elegant portrait, studio lighting, professional photo'")
        sw = Gtk.ScrolledWindow(child=self.prompt_tv, vexpand=False)
        sw.set_min_content_height(60)
        box.pack_start(sw, False, False, 0)

        # Negative
        box.pack_start(Gtk.Label(label="Negative:", xalign=0), False, False, 0)
        self.neg_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.neg_tv.set_size_request(-1, 40)
        self.neg_tv.set_tooltip_text("Describe what you do NOT want (e.g. 'blurry, distorted').")
        sw2 = Gtk.ScrolledWindow(child=self.neg_tv, vexpand=False)
        sw2.set_min_content_height(40)
        box.pack_start(sw2, False, False, 0)
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

        box.pack_start(grid, False, False, 0)

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
        row.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry(); self.server_entry.set_text(server_url); self.server_entry.set_hexpand(True)
        self.server_entry.set_tooltip_text("ComfyUI server address. Default: http://127.0.0.1:8188")
        row.pack_start(self.server_entry, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Flux model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Flux Model:"), False, False, 0)
        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.set_tooltip_text("Flux checkpoint model for generation.\nRequires a Flux-compatible model file on the server.")
        for m in PULID_FLUX_MODELS:
            label = m.split("/")[-1] if "/" in m else m
            self.model_combo.append(m, label)
        self.model_combo.set_active(0)
        self.model_combo.set_hexpand(True)
        row.pack_start(self.model_combo, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Face reference image
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Face Reference:"), False, False, 0)
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
        row.pack_start(self.source_chooser, False, False, 0)
        box.pack_start(row, False, False, 0)

        # Prompt
        box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        self.prompt_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_size_request(-1, 60)
        self.prompt_tv.set_tooltip_text("Describe the scene. The face comes from the reference image.\nExample: 'portrait photo, natural lighting, smiling'")
        sw = Gtk.ScrolledWindow(child=self.prompt_tv, vexpand=False)
        sw.set_min_content_height(60)
        box.pack_start(sw, False, False, 0)

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

        box.pack_start(grid, False, False, 0)

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

        # AutoSet button
        def _klein_auto_set():
            arch = "flux2klein"
            pos, _neg = _AUTOSET_PROMPTS.get(arch, _AUTOSET_PROMPTS["sdxl"])
            self.prompt_tv.get_buffer().set_text(pos)
            self.steps_spin.set_value(_AUTOSET_STEPS.get(arch, 20))
            self.denoise_spin.set_value(0.55)
            self.guidance_spin.set_value(_AUTOSET_CFG.get(arch, 1.0))
        _klein_auto_btn = Gtk.Button(label="A.")
        _klein_auto_btn.set_tooltip_text(
            "AutoSet: auto-configure ALL parameters for optimal Klein results.\n"
            "Sets prompt, steps, denoise, and guidance to recommended values.")
        _klein_auto_btn.set_size_request(32, -1)
        _klein_auto_btn.connect("clicked", lambda b: _klein_auto_set())
        _klein_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _klein_top.pack_end(_klein_auto_btn, False, False, 0)
        box.pack_start(_klein_top, False, False, 0)

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
        """Return procedure names filtered by installed features.

        Reads config.json for 'installed_features' list. If present, only
        registers procedures whose feature dependencies are installed.
        If absent (fresh install), registers everything.
        This prevents empty submenus when the user didn't install Klein, Wan, etc.
        """
        # Map each procedure to its required feature (None = always available)
        _PROC_FEATURES = {
            "spellcaster-img2img": None,       # core — always available
            "spellcaster-txt2img": None,
            "spellcaster-inpaint": None,
            "spellcaster-send-image": None,
            "spellcaster-outpaint": None,
            "spellcaster-batch-variations": None,
            "spellcaster-upscale": "upscale",
            "spellcaster-face-restore": "face_restore",
            "spellcaster-photo-restore": "photo_restore",
            "spellcaster-detail-hallucinate": "detail_hallucinate",
            "spellcaster-supir": "supir",
            "spellcaster-seedv2r": "seedv2r",
            "spellcaster-colorize": "colorize",
            "spellcaster-lama-remove": "lama_remove",
            "spellcaster-faceswap": "face_swap_reactor",
            "spellcaster-faceswap-model": "face_swap_reactor",
            "spellcaster-faceswap-mtb": "face_swap_mtb",
            "spellcaster-faceid-img2img": "faceid_img2img",
            "spellcaster-pulid-flux": "pulid_flux",
            "spellcaster-klein-img2img": "klein_flux2",
            "spellcaster-klein-img2img-ref": "klein_flux2",
            "spellcaster-klein-outpaint": "klein_flux2",
            "spellcaster-klein-blend": "klein_flux2",
            "spellcaster-klein-repose": "klein_flux2",
            "spellcaster-klein-inpaint": "klein_flux2",
            "spellcaster-wan-i2v": "wan_i2v",
            "spellcaster-wan-flf": "wan_i2v",
            "spellcaster-video-upscale": "wan_i2v",
            "spellcaster-video-reactor": "wan_i2v",
            "spellcaster-rembg": "rembg",
            "spellcaster-gif-stitch": None,
            "spellcaster-embed-watermark": None,
            "spellcaster-read-watermark": None,
            "spellcaster-layer-blend-ratio": None,
            "spellcaster-upscale-blend": "upscale",
            "spellcaster-lut": "lut_grading",
            "spellcaster-style-transfer": "style_transfer",
            "spellcaster-iclight": "iclight",
            "spellcaster-settings": None,
            "spellcaster-my-presets": None,
        }

        cfg = _load_config()
        installed = cfg.get("installed_features")  # list of feature keys, or None

        procs = []
        for name, feature in _PROC_FEATURES.items():
            if feature is None:
                procs.append(name)  # always register
            elif installed is None:
                procs.append(name)  # no config = register everything
            elif feature in installed:
                procs.append(name)  # feature was installed
        return procs

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
            "spellcaster-layer-blend-ratio": ("Layer Blend by Ratio...", self._run_layer_blend_ratio,
                                               "Blend two layers by a controllable ratio (e.g. 40%/60%)"),
            "spellcaster-upscale-blend": ("Upscaler Ratio Blender...", self._run_upscale_blend,
                                           "Upscale with two models and blend results (e.g. 40% ESRGAN + 60% Remacri)"),
            "spellcaster-gif-stitch": ("GIF Stitcher (chain GIFs)...", self._run_gif_stitch,
                                       "Chain multiple GIF animations into one seamless video"),
            "spellcaster-embed-watermark": ("Embed Invisible Watermark...", self._run_embed_watermark,
                                             "Hide encrypted metadata inside image pixels (LSB steganography)"),
            "spellcaster-read-watermark": ("Read Invisible Watermark...", self._run_read_watermark,
                                            "Extract hidden metadata from a watermarked image"),
            "spellcaster-klein-outpaint": ("Klein Outpaint (extend canvas)...", self._run_klein_outpaint,
                                          "Extend canvas using Flux 2 Klein — best outpaint quality"),
            "spellcaster-klein-img2img-ref": ("Klein Image Editor + Reference...", self._run_klein_ref,
                                              "Edit image with Flux 2 Klein using a reference image"),
            "spellcaster-klein-blend": ("Klein Layer Blender...", self._run_klein_blend,
                                         "Blend foreground into background using AI-powered harmonization"),
            "spellcaster-klein-repose": ("Klein Re-poser...", self._run_klein_repose,
                                          "Change character pose or position using Flux 2 Klein"),
            "spellcaster-klein-inpaint": ("Klein Inpaint Selection...", self._run_klein_inpaint,
                                           "Regenerate selected area with Klein AI — context-aware, smooth edges"),
            "spellcaster-wan-i2v": ("Wan 2.2 Image to Video...", self._run_wan_i2v,
                                    "Generate video from image using Wan 2.2"),
            "spellcaster-wan-flf": ("Wan 2.2 First + Last Frame to Video...", self._run_wan_flf,
                                     "Generate video transitioning between two keyframes using Wan 2.2"),
            "spellcaster-video-upscale": ("Video Upscale (RTX + Model)...", self._run_video_upscale,
                                           "Upscale a video with model + RTX super-resolution"),
            "spellcaster-video-reactor": ("Video Face Swap + Upscale...", self._run_video_reactor,
                                           "Upscale a video and swap faces using ReActor"),
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
            "spellcaster-my-presets": ("My Spellcaster Presets...", self._run_my_presets,
                                       "Quick access to your saved prompt/settings presets"),
        }
        label, callback, doc = menu_map[name]

        # Menu path mapping — organise tools into logical submenus
        _menu_paths = {
            # My Presets: TOP-LEVEL under Filters (outside Spellcaster submenus)
            "spellcaster-my-presets":       "<Image>/Filters",

            # Expert: the do-it-all generation tools
            "spellcaster-img2img":          "<Image>/Filters/Spellcaster Expert",
            "spellcaster-txt2img":          "<Image>/Filters/Spellcaster Expert",
            "spellcaster-inpaint":          "<Image>/Filters/Spellcaster Expert",
            "spellcaster-outpaint":         "<Image>/Filters/Spellcaster Expert",
            "spellcaster-batch-variations": "<Image>/Filters/Spellcaster Expert",

            # Face & Identity
            "spellcaster-faceswap":         "<Image>/Filters/Spellcaster Face",
            "spellcaster-faceswap-model":   "<Image>/Filters/Spellcaster Face",
            "spellcaster-faceswap-mtb":     "<Image>/Filters/Spellcaster Face",
            "spellcaster-faceid-img2img":    "<Image>/Filters/Spellcaster Face",
            "spellcaster-pulid-flux":        "<Image>/Filters/Spellcaster Face",
            "spellcaster-face-restore":      "<Image>/Filters/Spellcaster Face",

            # Photofixer: restoration, enhancement, repair
            "spellcaster-upscale":           "<Image>/Filters/Spellcaster Photofixer",
            "spellcaster-photo-restore":     "<Image>/Filters/Spellcaster Photofixer",
            "spellcaster-detail-hallucinate":"<Image>/Filters/Spellcaster Photofixer",
            "spellcaster-supir":             "<Image>/Filters/Spellcaster Photofixer",
            "spellcaster-seedv2r":           "<Image>/Filters/Spellcaster Photofixer",
            "spellcaster-colorize":          "<Image>/Filters/Spellcaster Photofixer",
            "spellcaster-lama-remove":       "<Image>/Filters/Spellcaster Photofixer",

            # Style & Lighting
            "spellcaster-style-transfer":    "<Image>/Filters/Spellcaster Style",
            "spellcaster-lut":               "<Image>/Filters/Spellcaster Style",
            "spellcaster-iclight":           "<Image>/Filters/Spellcaster Style",

            # Klein / Flux 2
            "spellcaster-klein-img2img":     "<Image>/Filters/Spellcaster Klein",
            "spellcaster-klein-outpaint": "<Image>/Filters/Spellcaster Klein",
            "spellcaster-klein-img2img-ref": "<Image>/Filters/Spellcaster Klein",
            "spellcaster-klein-blend":    "<Image>/Filters/Spellcaster Klein",
            "spellcaster-klein-repose":   "<Image>/Filters/Spellcaster Klein",
            "spellcaster-klein-inpaint":  "<Image>/Filters/Spellcaster Klein",

            # Video
            "spellcaster-wan-i2v":           "<Image>/Filters/Spellcaster Video",
            "spellcaster-wan-flf":           "<Image>/Filters/Spellcaster Video",
            "spellcaster-video-upscale":     "<Image>/Filters/Spellcaster Video",
            "spellcaster-video-reactor":     "<Image>/Filters/Spellcaster Video",

            # Tools & Utility
            "spellcaster-rembg":             "<Image>/Filters/Spellcaster Tools",
            "spellcaster-layer-blend-ratio": "<Image>/Filters/Spellcaster Tools",
            "spellcaster-upscale-blend":     "<Image>/Filters/Spellcaster Tools",
            "spellcaster-gif-stitch":        "<Image>/Filters/Spellcaster Tools",
            "spellcaster-embed-watermark":   "<Image>/Filters/Spellcaster Tools",
            "spellcaster-read-watermark":    "<Image>/Filters/Spellcaster Tools",
            "spellcaster-send-image":        "<Image>/Filters/Spellcaster Tools",
            "spellcaster-settings":          "<Image>/Filters/Spellcaster Tools",
        }

        proc = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, callback, None)
        proc.set_menu_label(label)
        proc.add_menu_path(_menu_paths.get(name, "<Image>/Filters/Spellcaster"))
        proc.set_documentation(doc, doc, name)
        proc.set_attribution("Spellcaster", "Spellcaster", "2026")
        proc.set_image_types("*")
        return proc

    # ── Procedure callbacks ──────────────────────────────────────────────
    # Each follows the same pattern: guard for INTERACTIVE mode → init GimpUi →
    # show dialog → export canvas → upload → build workflow → execute →
    # import results as layers → flush displays.

    def _run_img2img(self, procedure, run_mode, image, drawables, config, data):
        """Image-to-image: send current canvas through a model preset."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())

        # WITH_LAST_VALS (Ctrl+F "Repeat"): skip dialog, use saved session
        if run_mode == Gimp.RunMode.WITH_LAST_VALS:
            v = _session_to_values("img2img", image)
            if not v:
                return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        else:
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
            _save_session()
            dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            cn_active = v.get("controlnet", {}).get("mode", "Off") != "Off"

            # GIMP export on main thread (PDB not thread-safe)
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)

            def _do_all_runs():
                all_results = []
                base_seed = v["seed"]
                for run_i in range(runs):
                    seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                    wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                         _build_img2img(uname, v["preset"], v["prompt"], v["negative"], seed,
                                        v.get("loras"), controlnet=v.get("controlnet"),
                                        controlnet_2=v.get("controlnet_2"),
                                        )
                    label = f"Run {run_i+1}/{runs}" if runs > 1 else "img2img"
                    _update_spinner_status(f"{label}: processing on ComfyUI...")
                    all_results.extend(list(_run_comfyui_workflow(srv, wf)))
                return all_results
            results = _run_with_spinner("img2img: starting...", _do_all_runs)
            for i, (fn, sf, ft) in enumerate(results):
                # ControlNet debug images have the "spellcaster_cn_debug" prefix
                if cn_active and "spellcaster_cn_debug" in fn:
                    debug_data = _download_image(srv, fn, sf, ft)
                    _import_result_as_layer(image, debug_data, "ControlNet Debug (invisible)")
                    # Set the debug layer to invisible
                    debug_layer = image.get_layers()[0]
                    debug_layer.set_visible(False)
                    continue
                run_i = i // max(1, len([r for r in results if "spellcaster_cn_debug" not in r[0]]) // runs) if runs > 1 else 0
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        if run_mode == Gimp.RunMode.WITH_LAST_VALS:
            v = _session_to_values("txt2img", image)
            if not v:
                return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        else:
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
            _save_session()
            dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            def _do_all_runs():
                all_results = []
                base_seed = v["seed"]
                for run_i in range(runs):
                    seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                    wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                         _build_txt2img(v["preset"], v["prompt"], v["negative"], seed, v.get("loras"))
                    label = f"Run {run_i+1}/{runs}" if runs > 1 else "txt2img"
                    _update_spinner_status(f"{label}: processing on ComfyUI...")
                    all_results.extend(list(_run_comfyui_workflow(srv, wf)))
                return all_results
            results = _run_with_spinner("txt2img: starting...", _do_all_runs)
            for i, (fn, sf, ft) in enumerate(results):
                lbl = f"{v['preset'].get('label','')} run {i+1} #{i+1}" if runs > 1 \
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        if run_mode == Gimp.RunMode.WITH_LAST_VALS:
            v = _session_to_values("inpaint", image)
            if not v:
                return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        else:
            GimpUi.init("spellcaster")
            dlg = PresetDialog("Spellcaster — Inpaint Selection", mode="inpaint")
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
            _save_session()
            dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            cn_active = v.get("controlnet", {}).get("mode", "Off") != "Off"

            # ── GIMP operations on main thread (before spinner) ───────
            global _mask_cache
            sel_hash = _selection_hash(image)
            if (sel_hash
                    and _mask_cache["selection_hash"] == sel_hash
                    and _mask_cache["server"] == srv
                    and _mask_cache["uploaded_name"]):
                mname = _mask_cache["uploaded_name"]
            else:
                mtmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False); mtmp.close()
                _create_selection_mask_png(mtmp.name, image)
                mname = f"gimp_mask_{uuid.uuid4().hex[:8]}.png"
                _upload_image(srv, mtmp.name, mname)
                _mask_cache = {
                    "selection_hash": sel_hash,
                    "mask_path": mtmp.name,
                    "uploaded_name": mname,
                    "server": srv,
                }

            tmp = _export_image_to_tmp(image)
            iname = f"gimp_inp_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, iname); os.unlink(tmp)

            # ── Background thread: network I/O + ComfyUI workflows ────
            def _do_all_runs():
                all_results = []
                base_seed = v["seed"]
                for run_i in range(runs):
                    seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                    wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                         _build_inpaint(iname, mname, v["preset"], v["prompt"], v["negative"], seed,
                                        v.get("loras"), controlnet=v.get("controlnet"),
                                        controlnet_2=v.get("controlnet_2"),
                                        )
                    label = f"Run {run_i+1}/{runs}" if runs > 1 else "Inpaint"
                    _update_spinner_status(f"{label}: processing on ComfyUI...")
                    all_results.extend(list(_run_comfyui_workflow(srv, wf)))
                return all_results
            results = _run_with_spinner("Inpaint: starting...", _do_all_runs)
            for i, (fn, sf, ft) in enumerate(results):
                # ControlNet debug images have the "spellcaster_cn_debug" prefix
                if cn_active and "spellcaster_cn_debug" in fn:
                    debug_data = _download_image(srv, fn, sf, ft)
                    _import_result_as_layer(image, debug_data, "ControlNet Debug (invisible)")
                    # Set the debug layer to invisible
                    debug_layer = image.get_layers()[0]
                    debug_layer.set_visible(False)
                    continue
                lbl = f"Inpaint {v['preset'].get('label','')} #{i+1}"
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Inpaint Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceswap(self, procedure, run_mode, image, drawables, config, data):
        """Face swap via ReActor: paste a face from a source image onto the canvas."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
            _update_spinner_status("Face Swap: exporting images...")
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
                _update_spinner_status(f"Saving face model '{model_name}'...")
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
            _update_spinner_status("Face Swap: processing on ComfyUI...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
            _update_spinner_status("Face Swap (Model): exporting image...")
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
            _update_spinner_status("Face Swap (Model): processing on ComfyUI...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        _save_session()
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            if has_sel:
                _update_spinner_status("Wan I2V: exporting selection region...")
                srv = v["server"]
                tmp, _sw, _sh = _export_selection_to_tmp(image)
            else:
                _update_spinner_status("Wan I2V: exporting image...")
                srv = v["server"]
                tmp = _export_image_to_tmp(image)
            uname = f"gimp_wan_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            base_seed = v["seed"]
            src = "selection" if has_sel else "full image"
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_wan_video(
                    uname, v["preset_key"], v["prompt"], v["negative"], seed,
                    width=v["width"], height=v["height"], length=v["length"],
                    steps=v["steps"], cfg=v["cfg"],
                    second_step=v["second_step"], turbo=v.get("turbo", True),
                    loop=v.get("loop", False),
                    loras_high=v.get("loras_high"),
                    loras_low=v.get("loras_low"),
                    all_server_loras=v.get("all_server_loras"),
                    rtx_scale=v.get("upscale_factor", 2.5),
                    interpolate=v.get("interpolate", True),
                    pingpong=v.get("pingpong", False),
                    fps=v["fps"],
                )
                label = f"Wan I2V run {run_i+1}/{runs}" if runs > 1 else "Wan I2V"
                results = _run_with_spinner(f"{label}: generating video from {src} on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
                for i, (fn, sf, ft) in enumerate(results):
                    # Import PNG frames into GIMP, skip MP4/GIF video files
                    if fn.lower().endswith(".png"):
                        lbl = f"Wan I2V run {run_i+1} #{i+1}" if runs > 1 else f"Wan I2V frame #{i+1}"
                        _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            Gimp.message("Video generation complete!\nFirst frame imported as a layer.\nMP4 saved in ComfyUI output folder.")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Wan I2V Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_wan_flf(self, procedure, run_mode, image, drawables, config, data):
        """Wan 2.2 First+Last Frame to Video: generate video transitioning between two keyframes."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        # Reuse the I2V dialog but add an end-image file chooser
        dlg = WanI2VDialog()
        dlg.set_title("ComfyUI - Wan 2.2 First + Last Frame to Video")

        # Insert end-image file chooser into the dialog
        box = dlg.get_content_area()
        flf_frame = Gtk.Frame(label="  Last Frame (end image)  ")
        flf_frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        flf_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        flf_frame.add(flf_box)

        flf_box.pack_start(Gtk.Label(
            label="The AI will generate a smooth video transition from your current\n"
                  "canvas (first frame) to the image you select below (last frame).",
            xalign=0), False, False, 4)

        hb_flf = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        end_entry = Gtk.Entry()
        end_entry.set_placeholder_text("Select the last frame image file...")
        end_entry.set_hexpand(True)
        end_entry.set_tooltip_text("Path to the end/last frame image.\n"
                                    "The generated video will smoothly transition from your\n"
                                    "current GIMP canvas (first frame) to this image (last frame).")
        hb_flf.pack_start(end_entry, True, True, 0)

        def _browse_end(*_a):
            fc = Gtk.FileChooserDialog(title="Select Last Frame Image",
                                        action=Gtk.FileChooserAction.OPEN)
            fc.add_button("_Cancel", Gtk.ResponseType.CANCEL)
            fc.add_button("_Open", Gtk.ResponseType.OK)
            ff = Gtk.FileFilter()
            ff.set_name("Images")
            for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp", "*.tiff"]:
                ff.add_pattern(ext)
            fc.add_filter(ff)
            if fc.run() == Gtk.ResponseType.OK:
                end_entry.set_text(fc.get_filename())
            fc.destroy()

        browse_btn = Gtk.Button(label="Browse...")
        browse_btn.set_tooltip_text("Open file picker to select the last/end frame image")
        browse_btn.connect("clicked", _browse_end)
        hb_flf.pack_start(browse_btn, False, False, 0)
        flf_box.pack_start(hb_flf, False, False, 4)

        # Also allow picking from GIMP layers
        layers = image.get_layers()
        if len(layers) >= 2:
            hb_layer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            hb_layer.pack_start(Gtk.Label(label="Or use layer:"), False, False, 0)
            layer_combo = Gtk.ComboBoxText()
            layer_combo.append("(none)", "(select from file above)")
            for idx, l in enumerate(layers):
                layer_combo.append(str(idx), l.get_name())
            layer_combo.set_active(0)
            layer_combo.set_tooltip_text("Instead of a file, use one of your GIMP layers as the last frame.\n"
                                          "The current canvas (flattened) is always the first frame.")
            hb_layer.pack_start(layer_combo, True, True, 0)
            flf_box.pack_start(hb_layer, False, False, 4)
        else:
            layer_combo = None

        # Insert the FLF frame near the top of the dialog (after header + server)
        children = box.get_children()
        # Insert after the 3rd child (header, server, model preset label)
        insert_pos = min(3, len(children))
        box.pack_start(flf_frame, False, False, 4)
        box.reorder_child(flf_frame, insert_pos)

        src_w, src_h = image.get_width(), image.get_height()
        vw, vh = _wan_video_dims(src_w, src_h)
        dlg.w_spin.set_value(vw)
        dlg.h_spin.set_value(vh)
        last = _SESSION.get("wan_flf")
        if last:
            dlg._apply_user_preset(last)

        box.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        v = dlg.get_values()
        end_path = end_entry.get_text().strip()
        use_layer = None
        if layer_combo and layer_combo.get_active_id() not in (None, "(none)"):
            use_layer = int(layer_combo.get_active_id())
        _SESSION["wan_flf"] = dlg._collect_user_preset()
        _save_session()
        dlg.destroy()

        if not end_path and use_layer is None:
            Gimp.message("Please select a last frame image or pick a layer.")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        runs = v.get("runs", 1)
        try:
            srv = v["server"]

            # Export first frame (current canvas)
            _update_spinner_status("Wan FLF: exporting first frame...")
            tmp_start = _export_image_to_tmp(image)
            start_name = f"gimp_flf_start_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp_start, start_name); os.unlink(tmp_start)

            # Export last frame (file or layer)
            _update_spinner_status("Wan FLF: exporting last frame...")
            if use_layer is not None:
                end_layer = layers[use_layer]
                end_img = Gimp.Image.new(image.get_width(), image.get_height(), Gimp.ImageBaseType.RGB)
                end_copy = Gimp.Layer.new_from_drawable(end_layer, end_img)
                end_img.insert_layer(end_copy, None, 0)
                end_img.flatten()
                tmp_end = _export_image_to_tmp(end_img)
                end_img.delete()
            else:
                tmp_end = end_path  # Direct file path — upload as-is

            end_name = f"gimp_flf_end_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp_end, end_name)
            if use_layer is not None:
                os.unlink(tmp_end)

            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_wan_flf(
                    start_name, end_name, v["preset_key"],
                    v["prompt"], v["negative"], seed,
                    width=v["width"], height=v["height"], length=v["length"],
                    steps=v["steps"], cfg=v["cfg"],
                    second_step=v["second_step"], turbo=v.get("turbo", True),
                    loras_high=v.get("loras_high"),
                    loras_low=v.get("loras_low"),
                    all_server_loras=v.get("all_server_loras"),
                    rtx_scale=v.get("upscale_factor", 2.5),
                    interpolate=v.get("interpolate", True),
                    pingpong=v.get("pingpong", False),
                    fps=v["fps"],
                )
                label = f"Wan FLF run {run_i+1}/{runs}" if runs > 1 else "Wan FLF"
                results = _run_with_spinner(f"{label}: generating video transition on ComfyUI...",
                                             lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
                for i, (fn, sf, ft) in enumerate(results):
                    if fn.lower().endswith(".png"):
                        lbl = f"Wan FLF run {run_i+1} #{i+1}" if runs > 1 else f"Wan FLF frame #{i+1}"
                        _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            Gimp.message("First+Last Frame video complete!\nFirst frame imported as a layer.\nMP4 saved in ComfyUI output folder.")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Wan FLF Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    # ── Video Upscale (V2R) ────────────────────────────────────────────
    def _run_video_upscale(self, procedure, run_mode, image, drawables, config, data):
        """Upscale a video file using model + RTX super-resolution."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        dlg = Gtk.Dialog(title="Spellcaster — Video Upscale")
        dlg.set_default_size(500, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Upscale Video", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(6); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(10); bx.set_margin_bottom(10)

        _hdr = _make_branded_header()
        if _hdr: bx.pack_start(_hdr, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        srv_e = Gtk.Entry(); srv_e.set_text(COMFYUI_DEFAULT_URL); srv_e.set_hexpand(True)
        hb.pack_start(srv_e, True, True, 0); bx.pack_start(hb, False, False, 0)

        bx.pack_start(Gtk.Label(label="Select a video file from ComfyUI's input folder.\n"
                                      "The video will be upscaled frame-by-frame and re-encoded."),
                       False, False, 4)

        # Video file (from ComfyUI input folder)
        hv = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hv.pack_start(Gtk.Label(label="Video:"), False, False, 0)
        video_combo = Gtk.ComboBoxText()
        video_combo.set_tooltip_text("Video file in ComfyUI's input folder.\nUpload a video there first, or use one from a previous generation.")
        video_combo.set_hexpand(True)
        hv.pack_start(video_combo, True, True, 0); bx.pack_start(hv, False, False, 0)

        # Fetch videos from server
        try:
            srv = srv_e.get_text().strip()
            info = _api_get(srv, "/object_info/VHS_LoadVideo")
            vids = info["VHS_LoadVideo"]["input"]["required"]["video"][0]
            for v in vids:
                video_combo.append(v, v)
            if vids:
                video_combo.set_active(0)
        except Exception:
            pass

        # Upscale model
        hu = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hu.pack_start(Gtk.Label(label="Upscale Model:"), False, False, 0)
        up_combo = Gtk.ComboBoxText()
        up_combo.append("(none)", "(none — RTX only)")
        for label in UPSCALE_PRESETS:
            if UPSCALE_PRESETS[label]:
                up_combo.append(label, label)
        up_combo.set_active(0)
        up_combo.set_tooltip_text("Optional model-based upscale before RTX.\nUse for maximum quality.")
        hu.pack_start(up_combo, True, True, 0); bx.pack_start(hu, False, False, 0)

        # Scale factors
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label="Model factor:"), 0, 0, 1, 1)
        model_factor_sp = Gtk.SpinButton.new_with_range(1.0, 4.0, 0.5)
        model_factor_sp.set_value(1.0); model_factor_sp.set_digits(1)
        model_factor_sp.set_tooltip_text("Upscale factor for the model pass.\n1.0 = skip model upscale.")
        grid.attach(model_factor_sp, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="RTX factor:"), 2, 0, 1, 1)
        rtx_sp = Gtk.SpinButton.new_with_range(1.0, 4.0, 0.5)
        rtx_sp.set_value(2.0); rtx_sp.set_digits(1)
        rtx_sp.set_tooltip_text("RTX Video Super Resolution factor.\n2.0 = double resolution.")
        grid.attach(rtx_sp, 3, 0, 1, 1)

        grid.attach(Gtk.Label(label="FPS:"), 0, 1, 1, 1)
        fps_sp = Gtk.SpinButton.new_with_range(1, 60, 1)
        fps_sp.set_value(16)
        grid.attach(fps_sp, 1, 1, 1, 1)
        bx.pack_start(grid, False, False, 4)

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        srv = srv_e.get_text().strip(); _propagate_server_url(srv)
        video_name = video_combo.get_active_id()
        up_key = up_combo.get_active_id()
        up_model = UPSCALE_PRESETS.get(up_key) if up_key != "(none)" else None
        model_factor = model_factor_sp.get_value()
        rtx_scale = rtx_sp.get_value()
        fps = int(fps_sp.get_value())
        dlg.destroy()

        if not video_name:
            Gimp.message("No video selected.")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        try:
            wf = _build_video_upscale(video_name, upscale_model=up_model,
                                       upscale_factor=model_factor, rtx_scale=rtx_scale, fps=fps)
            results = _run_with_spinner("Video Upscale: processing...",
                                         lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
            for fn, sf, ft in results:
                if fn.lower().endswith(".png"):
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                            "Video Upscale frame")
            Gimp.displays_flush()
            Gimp.message("Video upscale complete! Check ComfyUI output folder.")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Video Upscale Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    # ── Video Upscale + ReActor Face Swap ────────────────────────────
    def _run_video_reactor(self, procedure, run_mode, image, drawables, config, data):
        """Upscale a video + swap faces using ReActor."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        dlg = Gtk.Dialog(title="Spellcaster — Video Upscale + Face Swap")
        dlg.set_default_size(520, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Process Video", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(6); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(10); bx.set_margin_bottom(10)

        _hdr = _make_branded_header()
        if _hdr: bx.pack_start(_hdr, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        srv_e = Gtk.Entry(); srv_e.set_text(COMFYUI_DEFAULT_URL); srv_e.set_hexpand(True)
        hb.pack_start(srv_e, True, True, 0); bx.pack_start(hb, False, False, 0)

        bx.pack_start(Gtk.Label(label="Upscale + face swap a video.\n"
                                      "Faces are swapped using saved ReActor face models."),
                       False, False, 4)

        # Video file
        hv = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hv.pack_start(Gtk.Label(label="Video:"), False, False, 0)
        video_combo = Gtk.ComboBoxText()
        video_combo.set_hexpand(True)
        hv.pack_start(video_combo, True, True, 0); bx.pack_start(hv, False, False, 0)

        # Face models (2 slots)
        bx.pack_start(Gtk.Label(label="Face Models (saved ReActor .safetensors):"), False, False, 2)
        face_combos = []

        # Fetch videos + face models from server
        face_model_list = []
        try:
            srv = srv_e.get_text().strip()
            info = _api_get(srv, "/object_info/VHS_LoadVideo")
            vids = info["VHS_LoadVideo"]["input"]["required"]["video"][0]
            for v in vids:
                video_combo.append(v, v)
            if vids:
                video_combo.set_active(0)

            info2 = _api_get(srv, "/object_info/ReActorLoadFaceModel")
            face_model_list = info2["ReActorLoadFaceModel"]["input"]["required"]["face_model"][0]
        except Exception:
            pass

        for slot in range(2):
            hf = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            hf.pack_start(Gtk.Label(label=f"Face {slot+1}:"), False, False, 0)
            fc = Gtk.ComboBoxText()
            fc.append("(none)", f"(none — skip face {slot+1})")
            for fm in face_model_list:
                fc.append(fm, fm)
            fc.set_active(0)
            fc.set_hexpand(True)
            fc.set_tooltip_text(f"Saved face model for face index {slot}.\nLeave as (none) to skip.")
            hf.pack_start(fc, True, True, 0); bx.pack_start(hf, False, False, 0)
            face_combos.append(fc)

        # Upscale + restore settings
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label="Upscale Model:"), 0, 0, 1, 1)
        up_combo = Gtk.ComboBoxText()
        up_combo.append("(none)", "(none)")
        for label in UPSCALE_PRESETS:
            if UPSCALE_PRESETS[label]:
                up_combo.append(label, label)
        up_combo.set_active(0)
        grid.attach(up_combo, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Model factor:"), 2, 0, 1, 1)
        mf_sp = Gtk.SpinButton.new_with_range(1.0, 4.0, 0.5)
        mf_sp.set_value(1.0); mf_sp.set_digits(1)
        grid.attach(mf_sp, 3, 0, 1, 1)

        grid.attach(Gtk.Label(label="RTX factor:"), 0, 1, 1, 1)
        rtx_sp = Gtk.SpinButton.new_with_range(1.0, 4.0, 0.5)
        rtx_sp.set_value(2.0); rtx_sp.set_digits(1)
        grid.attach(rtx_sp, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="FPS:"), 2, 1, 1, 1)
        fps_sp = Gtk.SpinButton.new_with_range(1, 60, 1)
        fps_sp.set_value(16)
        grid.attach(fps_sp, 3, 1, 1, 1)

        grid.attach(Gtk.Label(label="Restore vis:"), 0, 2, 1, 1)
        vis_sp = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        vis_sp.set_value(0.5); vis_sp.set_digits(2)
        vis_sp.set_tooltip_text("Face restore visibility. Higher = more restore effect.")
        grid.attach(vis_sp, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="CF weight:"), 2, 2, 1, 1)
        cf_sp = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        cf_sp.set_value(0.95); cf_sp.set_digits(2)
        cf_sp.set_tooltip_text("CodeFormer fidelity weight. Higher = more faithful to original.")
        grid.attach(cf_sp, 3, 2, 1, 1)
        bx.pack_start(grid, False, False, 4)

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        srv = srv_e.get_text().strip(); _propagate_server_url(srv)
        video_name = video_combo.get_active_id()
        selected_faces = [fc.get_active_id() for fc in face_combos
                          if fc.get_active_id() and fc.get_active_id() != "(none)"]
        up_key = up_combo.get_active_id()
        up_model = UPSCALE_PRESETS.get(up_key) if up_key != "(none)" else None
        model_factor = mf_sp.get_value()
        rtx_scale = rtx_sp.get_value()
        fps = int(fps_sp.get_value())
        vis = vis_sp.get_value()
        cfw = cf_sp.get_value()
        dlg.destroy()

        if not video_name:
            Gimp.message("No video selected.")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        if not selected_faces:
            Gimp.message("Select at least one face model.")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        try:
            wf = _build_video_reactor(video_name, selected_faces, upscale_model=up_model,
                                       upscale_factor=model_factor, rtx_scale=rtx_scale, fps=fps,
                                       face_restore_visibility=vis, codeformer_weight=cfw)
            results = _run_with_spinner("Video ReActor: processing...",
                                         lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
            for fn, sf, ft in results:
                if fn.lower().endswith(".png"):
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                            "Video ReActor frame")
            Gimp.displays_flush()
            Gimp.message("Video face swap + upscale complete!\nCheck ComfyUI output folder.")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Video ReActor Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceswap_mtb(self, procedure, run_mode, image, drawables, config, data):
        """Face swap via mtb facetools: direct swap from source image."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
            _update_spinner_status("Face Swap (mtb): exporting images...")
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
            _update_spinner_status("Face Swap (mtb): processing...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        _save_session()
        dlg.destroy()
        if not v["source_path"]:
            Gimp.message("No face reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        runs = v.get("runs", 1)
        try:
            _update_spinner_status("FaceID: exporting images...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        _save_session()
        dlg.destroy()
        if not v["source_path"]:
            Gimp.message("No face reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        runs = v.get("runs", 1)
        try:
            _update_spinner_status("PuLID Flux: exporting images...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        _save_session()
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            _update_spinner_status("Klein: exporting image...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        _save_session()
        dlg.destroy()
        if not v.get("ref_file"):
            Gimp.message("No reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        runs = v.get("runs", 1)
        try:
            _update_spinner_status("Klein+Ref: exporting images...")
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

    def _run_klein_outpaint(self, procedure, run_mode, image, drawables, config, data):
        """Klein Outpaint: extend canvas using Flux 2 Klein — best outpaint quality."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — Klein Outpaint")
        dlg.set_default_size(520, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Extend", Gtk.ResponseType.OK)
        _style_dialog_buttons(dlg)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)

        header = _make_branded_header()
        if header:
            bx.pack_start(header, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)

        # Klein model selector
        bx.pack_start(Gtk.Label(label="Klein Model:", xalign=0), False, False, 0)
        klein_combo = Gtk.ComboBoxText()
        klein_combo.set_tooltip_text("Flux 2 Klein model. 9B gives the best outpaint quality.")
        for key in KLEIN_MODELS:
            klein_combo.append(key, key)
        klein_combo.set_active(0)
        bx.pack_start(klein_combo, False, False, 0)

        # Purpose presets (reuse from outpaint)
        KLEIN_OUTPAINT_PRESETS = {
            "(general extension)": "seamless continuation of the existing scene, matching lighting, style, and color palette, natural extension, consistent perspective",
            "Complete person / body": "natural continuation of the human body, correct anatomy, matching skin tone and clothing, same pose direction, realistic proportions",
            "Extend landscape / sky": "seamless landscape continuation, matching horizon, consistent sky, natural terrain, same vegetation, coherent depth of field",
            "Complete cut-off object": "natural completion of the cut-off object, matching material and texture, correct proportions, seamless extension",
            "Extend interior / room": "seamless room extension, matching wall color, consistent floor, same furniture style, correct perspective",
            "Add more background": "smooth background extension, matching colors and blur, consistent depth of field, natural continuation",
            "Widen panorama": "panoramic scene extension, wide angle continuation, matching horizon, consistent sky and ground",
        }
        bx.pack_start(Gtk.Label(label="Purpose:", xalign=0), False, False, 0)
        purpose_combo = Gtk.ComboBoxText()
        purpose_combo.set_tooltip_text("What you're extending — auto-fills an optimized prompt.")
        for label in KLEIN_OUTPAINT_PRESETS:
            purpose_combo.append(label, label)
        purpose_combo.set_active(0)
        bx.pack_start(purpose_combo, False, False, 0)

        # Prompt
        bx.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 60)
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(60)
        bx.pack_start(sw, False, False, 0)

        def _on_purpose(combo):
            key = combo.get_active_id()
            if key and key in KLEIN_OUTPAINT_PRESETS:
                prompt_tv.get_buffer().set_text(KLEIN_OUTPAINT_PRESETS[key])
        purpose_combo.connect("changed", _on_purpose)
        _on_purpose(purpose_combo)

        # Padding
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        grid.attach(Gtk.Label(label="Left:", xalign=1), 0, 0, 1, 1)
        left_sp = Gtk.SpinButton.new_with_range(0, 2048, 16); left_sp.set_value(0)
        grid.attach(left_sp, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Top:", xalign=1), 2, 0, 1, 1)
        top_sp = Gtk.SpinButton.new_with_range(0, 2048, 16); top_sp.set_value(0)
        grid.attach(top_sp, 3, 0, 1, 1)
        grid.attach(Gtk.Label(label="Right:", xalign=1), 0, 1, 1, 1)
        right_sp = Gtk.SpinButton.new_with_range(0, 2048, 16); right_sp.set_value(0)
        grid.attach(right_sp, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="Bottom:", xalign=1), 2, 1, 1, 1)
        bottom_sp = Gtk.SpinButton.new_with_range(0, 2048, 16); bottom_sp.set_value(256)
        grid.attach(bottom_sp, 3, 1, 1, 1)
        grid.attach(Gtk.Label(label="Feathering:", xalign=1), 0, 2, 1, 1)
        feather_sp = Gtk.SpinButton.new_with_range(0, 256, 1); feather_sp.set_value(40)
        grid.attach(feather_sp, 1, 2, 1, 1)
        grid.attach(Gtk.Label(label="Steps:", xalign=1), 2, 2, 1, 1)
        steps_sp = Gtk.SpinButton.new_with_range(4, 50, 1); steps_sp.set_value(20)
        grid.attach(steps_sp, 3, 2, 1, 1)
        bx.pack_start(grid, False, False, 0)

        # Seed + Runs
        hb_seed = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_seed.pack_start(Gtk.Label(label="Seed:"), False, False, 0)
        seed_sp = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1); seed_sp.set_value(-1)
        hb_seed.pack_start(seed_sp, True, True, 0)
        hb_seed.pack_start(Gtk.Label(label="Runs:"), False, False, 6)
        runs_sp = Gtk.SpinButton.new_with_range(1, 99, 1); runs_sp.set_value(1)
        runs_sp.set_tooltip_text("Generate multiple variations — each with a different random seed")
        hb_seed.pack_start(runs_sp, False, False, 0)
        bx.pack_start(hb_seed, False, False, 0)

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        klein_key = klein_combo.get_active_id() or "Klein 9B"
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        pad_l = int(left_sp.get_value()); pad_t = int(top_sp.get_value())
        pad_r = int(right_sp.get_value()); pad_b = int(bottom_sp.get_value())
        feathering = int(feather_sp.get_value())
        steps = int(steps_sp.get_value())
        runs = int(runs_sp.get_value())
        base_seed = int(seed_sp.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        dlg.destroy()
        try:
            _update_spinner_status("Klein Outpaint: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_klein_out_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)

            km = KLEIN_MODELS[klein_key]
            preset = {
                "arch": "flux2klein", "ckpt": km["unet"],
                "steps": steps, "cfg": 1.0, "denoise": 1.0,
                "sampler": "euler", "scheduler": "simple",
            }
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_outpaint(uname, preset, prompt, "", seed,
                                      pad_l, pad_t, pad_r, pad_b, feathering)
                label = f"Klein Outpaint run {run_i+1}/{runs}" if runs > 1 else "Klein Outpaint"
                results = _run_with_spinner(f"{label}: processing...",
                                            lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
                for i, (fn, sf, ft) in enumerate(results):
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                            f"Klein Outpaint run {run_i+1} #{i+1}" if runs > 1 else f"Klein Outpaint #{i+1}")
            Gimp.displays_flush()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Klein Outpaint Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_klein_blend(self, procedure, run_mode, image, drawables, config, data):
        """Klein Layer Blender: AI-powered integration of one layer into another."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        # Need at least 2 layers
        layers = image.get_layers()
        if len(layers) < 2:
            Gimp.message("Need at least 2 layers.\n\nLayer 1 (top) = element to integrate\nLayer 2 = background/scene\n\nAdd a new layer with the element you want to blend in.")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        dlg = Gtk.Dialog(title="Spellcaster — Klein Layer Blender")
        dlg.set_default_size(520, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Blend", Gtk.ResponseType.OK)
        _style_dialog_buttons(dlg)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)

        header = _make_branded_header()
        if header:
            bx.pack_start(header, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)

        # Layer selection
        bx.pack_start(Gtk.Label(label="Foreground (element to integrate):", xalign=0), False, False, 0)
        fg_combo = Gtk.ComboBoxText()
        fg_combo.set_tooltip_text("The layer containing the element you want to place into the scene.\nThis could be a person, object, or any element on a separate layer.")
        for i, layer in enumerate(layers):
            fg_combo.append(str(i), layer.get_name() or f"Layer {i}")
        fg_combo.set_active(0)  # top layer = foreground
        bx.pack_start(fg_combo, False, False, 0)

        bx.pack_start(Gtk.Label(label="Background (scene/destination):", xalign=0), False, False, 0)
        bg_combo = Gtk.ComboBoxText()
        bg_combo.set_tooltip_text("The layer containing the background/scene where the element will be placed.")
        for i, layer in enumerate(layers):
            bg_combo.append(str(i), layer.get_name() or f"Layer {i}")
        bg_combo.set_active(min(1, len(layers)-1))  # second layer = background
        bx.pack_start(bg_combo, False, False, 0)

        # Klein model
        bx.pack_start(Gtk.Label(label="Klein Model:", xalign=0), False, False, 0)
        klein_combo = Gtk.ComboBoxText()
        for key in KLEIN_MODELS:
            klein_combo.append(key, key)
        klein_combo.set_active(0)
        bx.pack_start(klein_combo, False, False, 0)

        # Blend mode presets
        BLEND_PRESETS = {
            "Natural Integration (harmonize lighting)": {
                "prompt": "Seamlessly integrated composition, matching lighting and shadows between all elements, "
                          "consistent color temperature, natural-looking placement, professional compositing, "
                          "unified scene, same artistic style throughout",
                "denoise": 0.25, "steps": 20,
            },
            "Strong Integration (relight + reshade)": {
                "prompt": "Perfectly integrated scene, matching light source direction, consistent shadows, "
                          "matching ambient occlusion, same depth of field, color-matched elements, "
                          "professional photo composite, indistinguishable from single photograph",
                "denoise": 0.35, "steps": 25,
            },
            "Person into Scene": {
                "prompt": "Person naturally placed in the scene, matching background lighting on skin and clothes, "
                          "consistent shadows, correct perspective scale, natural depth of field, "
                          "same color grading applied to person and background",
                "denoise": 0.30, "steps": 25,
            },
            "Object into Photo": {
                "prompt": "Object naturally placed in the photograph, matching surface reflections, "
                          "consistent shadows and ambient light, correct scale, same photographic style, "
                          "physically plausible placement",
                "denoise": 0.28, "steps": 20,
            },
            "Minimal (just compose, barely touch)": {
                "prompt": "Clean composite, minimal changes, preserve both elements as-is, slight edge blending only",
                "denoise": 0.12, "steps": 12,
            },
        }

        bx.pack_start(Gtk.Label(label="Integration Mode:", xalign=0), False, False, 0)
        mode_combo = Gtk.ComboBoxText()
        mode_combo.set_tooltip_text("How aggressively Klein integrates the elements.\nNatural = gentle harmonization. Strong = relight + reshade. Minimal = just overlay.")
        for label in BLEND_PRESETS:
            mode_combo.append(label, label)
        mode_combo.set_active(0)
        bx.pack_start(mode_combo, False, False, 0)

        # Prompt
        bx.pack_start(Gtk.Label(label="Integration Prompt:", xalign=0), False, False, 0)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 50)
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(50)
        bx.pack_start(sw, False, False, 0)

        def _on_mode(combo):
            key = combo.get_active_id()
            if key and key in BLEND_PRESETS:
                prompt_tv.get_buffer().set_text(BLEND_PRESETS[key]["prompt"])
        mode_combo.connect("changed", _on_mode)
        _on_mode(mode_combo)

        # Composite settings (expander)
        comp_exp = Gtk.Expander(label="▸ Composite Settings")
        comp_exp.set_expanded(False)
        _shrink_on_collapse(comp_exp, dlg)
        comp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        comp_box.set_margin_start(4); comp_box.set_margin_top(4)
        comp_grid = Gtk.Grid(column_spacing=8, row_spacing=4)

        comp_grid.attach(Gtk.Label(label="Opacity:", xalign=1), 0, 0, 1, 1)
        opacity_sp = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        opacity_sp.set_value(1.0); opacity_sp.set_digits(2)
        opacity_sp.set_tooltip_text("Foreground element opacity. 1.0 = fully visible.")
        comp_grid.attach(opacity_sp, 1, 0, 1, 1)

        comp_grid.attach(Gtk.Label(label="Scale:", xalign=1), 2, 0, 1, 1)
        scale_sp = Gtk.SpinButton.new_with_range(0.1, 5.0, 0.05)
        scale_sp.set_value(1.0); scale_sp.set_digits(2)
        scale_sp.set_tooltip_text("Scale the foreground element. 1.0 = original size.")
        comp_grid.attach(scale_sp, 3, 0, 1, 1)

        comp_grid.attach(Gtk.Label(label="X Position %:", xalign=1), 0, 1, 1, 1)
        pos_x = Gtk.SpinButton.new_with_range(0, 100, 1); pos_x.set_value(50)
        comp_grid.attach(pos_x, 1, 1, 1, 1)

        comp_grid.attach(Gtk.Label(label="Y Position %:", xalign=1), 2, 1, 1, 1)
        pos_y = Gtk.SpinButton.new_with_range(0, 100, 1); pos_y.set_value(50)
        comp_grid.attach(pos_y, 3, 1, 1, 1)

        comp_grid.attach(Gtk.Label(label="Blend:", xalign=1), 0, 2, 1, 1)
        blend_combo = Gtk.ComboBoxText()
        for m in ["normal", "multiply", "screen", "overlay", "add", "subtract"]:
            blend_combo.append(m, m)
        blend_combo.set_active(0)
        comp_grid.attach(blend_combo, 1, 2, 1, 1)

        comp_box.pack_start(comp_grid, False, False, 0)
        comp_exp.add(comp_box)
        bx.pack_start(comp_exp, False, False, 0)

        # Seed + Runs
        hb_seed = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_seed.pack_start(Gtk.Label(label="Seed:"), False, False, 0)
        seed_sp = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1); seed_sp.set_value(-1)
        hb_seed.pack_start(seed_sp, True, True, 0)
        hb_seed.pack_start(Gtk.Label(label="Runs:"), False, False, 6)
        runs_sp = Gtk.SpinButton.new_with_range(1, 99, 1); runs_sp.set_value(1)
        runs_sp.set_tooltip_text("Generate multiple variations — each with a different random seed")
        hb_seed.pack_start(runs_sp, False, False, 0)
        bx.pack_start(hb_seed, False, False, 0)

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        srv = se.get_text().strip(); _propagate_server_url(srv)
        fg_idx = int(fg_combo.get_active_id() or "0")
        bg_idx = int(bg_combo.get_active_id() or "1")
        klein_key = klein_combo.get_active_id() or "Klein 9B"
        mode_key = mode_combo.get_active_id()
        bp = BLEND_PRESETS.get(mode_key, BLEND_PRESETS["Natural Integration (harmonize lighting)"])
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        opacity = opacity_sp.get_value()
        scale = scale_sp.get_value()
        px = int(pos_x.get_value()); py = int(pos_y.get_value())
        blend_mode = blend_combo.get_active_id() or "normal"
        runs = int(runs_sp.get_value())
        base_seed = int(seed_sp.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        dlg.destroy()

        try:
            _update_spinner_status("Klein Blend: exporting layers...")
            fg_layer = layers[fg_idx]
            bg_layer = layers[bg_idx]

            # Export foreground layer as a temporary image
            fg_img = Gimp.Image.new(image.get_width(), image.get_height(), Gimp.ImageBaseType.RGB)
            fg_copy = Gimp.Layer.new_from_drawable(fg_layer, fg_img)
            fg_img.insert_layer(fg_copy, None, 0)
            fg_img.flatten()
            fg_tmp_path = _export_image_to_tmp(fg_img)
            fg_img.delete()

            # Export background layer as a temporary image
            bg_img = Gimp.Image.new(image.get_width(), image.get_height(), Gimp.ImageBaseType.RGB)
            bg_copy = Gimp.Layer.new_from_drawable(bg_layer, bg_img)
            bg_img.insert_layer(bg_copy, None, 0)
            bg_img.flatten()
            bg_tmp_path = _export_image_to_tmp(bg_img)
            bg_img.delete()

            fg_name = f"blend_fg_{uuid.uuid4().hex[:8]}.png"
            bg_name = f"blend_bg_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, fg_tmp_path, fg_name); os.unlink(fg_tmp_path)
            _upload_image(srv, bg_tmp_path, bg_name); os.unlink(bg_tmp_path)

            km = KLEIN_MODELS[klein_key]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                label = f"Klein Blend run {run_i+1}/{runs}" if runs > 1 else "Klein Blend"
                _update_spinner_status(f"{label}: compositing + AI integration...")

                wf = {
                    "1": {"class_type": "LoadImage", "inputs": {"image": fg_name}},
                    "2": {"class_type": "LoadImage", "inputs": {"image": bg_name}},
                    "3": {"class_type": "AILab_ImageCombiner", "inputs": {
                        "foreground": ["1", 0], "background": ["2", 0],
                        "mode": blend_mode, "foreground_opacity": opacity,
                        "foreground_scale": scale, "position_x": px, "position_y": py,
                    }},
                    "10": {"class_type": "UNETLoader", "inputs": {"unet_name": km["unet"], "weight_dtype": "default"}},
                    "11": {"class_type": "CLIPLoader", "inputs": {
                        "clip_name": km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
                        "type": "flux2", "device": "default"}},
                    "12": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
                    "13": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["11", 0]}},
                    "14": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["13", 0]}},
                    "15": {"class_type": "ImageScaleToTotalPixels", "inputs": {
                        "image": ["3", 0], "upscale_method": "nearest-exact",
                        "megapixels": 1.0, "resolution_steps": 16}},
                    "16": {"class_type": "GetImageSize", "inputs": {"image": ["15", 0]}},
                    "17": {"class_type": "VAEEncode", "inputs": {"pixels": ["15", 0], "vae": ["12", 0]}},
                    "20": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["13", 0], "latent": ["17", 0]}},
                    "21": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["14", 0], "latent": ["17", 0]}},
                    "30": {"class_type": "CFGGuider", "inputs": {
                        "model": ["10", 0], "positive": ["20", 0], "negative": ["21", 0], "cfg": 1.0}},
                    "31": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
                    "32": {"class_type": "Flux2Scheduler", "inputs": {
                        "steps": bp.get("steps", 20), "denoise": bp.get("denoise", 0.25),
                        "width": ["16", 0], "height": ["16", 1]}},
                    "33": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
                    "34": {"class_type": "EmptyFlux2LatentImage", "inputs": {
                        "width": ["16", 0], "height": ["16", 1], "batch_size": 1}},
                    "40": {"class_type": "SamplerCustomAdvanced", "inputs": {
                        "noise": ["33", 0], "guider": ["30", 0], "sampler": ["31", 0],
                        "sigmas": ["32", 0], "latent_image": ["34", 0]}},
                    "50": {"class_type": "VAEDecode", "inputs": {"samples": ["40", 0], "vae": ["12", 0]}},
                    "60": {"class_type": "SaveImage", "inputs": {"images": ["50", 0], "filename_prefix": "spellcaster_blend"}},
                }

                results = _run_with_spinner(f"{label}: AI integration...",
                                            lambda: list(_run_comfyui_workflow(srv, wf, timeout=300)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Klein Blend run {run_i+1} #{i+1}" if runs > 1 else f"Klein Blend #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Klein Layer Blender Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    # ── Klein Re-poser ──────────────────────────────────────────────────
    def _run_klein_repose(self, procedure, run_mode, image, drawables, config, data):
        """Klein Re-poser: change character pose/position using Flux 2 Klein."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        # ── Preset libraries ──────────────────────────────────────────
        CHAR_TEMPLATES = {
            "Single character": "a single person",
            "Two characters": "two people",
            "Three characters": "three people",
            "Group / crowd": "a group of people",
            "Animal": "an animal",
            "Robot / mech": "a humanoid robot",
        }

        POSE_PRESETS = {
            # Standing
            "Standing relaxed":          "standing relaxed with arms at sides, natural weight shift",
            "Standing arms crossed":     "standing with arms crossed over chest, confident posture",
            "Standing hands on hips":    "standing with hands on hips, assertive power pose",
            "Standing contrapposto":     "standing in contrapposto pose, weight on one leg, elegant",
            "Leaning on wall":           "leaning casually against a wall, one foot propped up",
            # Sitting
            "Sitting in chair":          "sitting comfortably in a chair, relaxed posture",
            "Sitting cross-legged":      "sitting cross-legged on the ground, meditative",
            "Sitting on edge":           "sitting on the edge of a surface, legs dangling",
            "Crouching":                 "crouching low to the ground, knees bent",
            "Kneeling":                  "kneeling on one knee, upright torso",
            # Action
            "Walking forward":           "walking forward mid-stride, natural gait",
            "Running":                   "running dynamically, legs mid-stride, arms pumping",
            "Jumping":                   "jumping in the air, legs tucked, arms raised",
            "Dancing":                   "dancing expressively, dynamic body movement, fluid pose",
            "Fighting stance":           "in a martial arts fighting stance, fists raised, weight centered",
            "Throwing":                  "mid-throw motion, arm extended back, body coiled",
            "Reaching up":               "reaching upward with one arm extended high",
            "Pointing":                  "pointing forward with one hand, confident gesture",
            # Expressive
            "Arms raised celebration":   "arms raised overhead in celebration, joyful expression",
            "Waving":                    "waving with one hand raised, friendly greeting",
            "Thinking pose":             "hand on chin in a thinking pose, contemplative",
            "Looking over shoulder":     "turned slightly, looking over one shoulder",
            "Back turned":               "facing away from camera, back to viewer",
            # Lying
            "Lying down relaxed":        "lying down on back, relaxed, arms at sides",
            "Lying on side":             "lying on one side, head propped on hand",
            "Prone / face down":         "lying face down, head turned to one side",
        }

        POSITION_PRESETS = {
            "Keep current position":     "",
            "Move to center":            "positioned in the center of the frame",
            "Move to left":              "positioned on the left side of the frame",
            "Move to right":             "positioned on the right side of the frame",
            "Move to foreground":        "positioned in the foreground, close to camera, larger in frame",
            "Move to background":        "positioned in the background, further away, smaller in frame",
            "Move to upper area":        "positioned in the upper portion of the frame",
            "Move to lower area":        "positioned in the lower portion of the frame",
        }

        CAMERA_PRESETS = {
            "Keep current angle":        "",
            "Low angle (heroic)":        "shot from low angle looking up, heroic perspective",
            "High angle (vulnerable)":   "shot from high angle looking down, diminutive perspective",
            "Eye level":                 "shot at eye level, neutral straight-on perspective",
            "Dutch angle (dramatic)":    "tilted dutch angle shot, dramatic off-kilter framing",
            "Over the shoulder":         "over the shoulder perspective, depth composition",
            "Close-up":                  "close-up framing, head and shoulders, intimate",
            "Wide shot":                 "wide shot showing full body and environment",
        }

        MULTI_CHAR_PRESETS = {
            "Conversation":              "two people facing each other in conversation, natural body language, eye contact",
            "Walking together":          "two people walking side by side, matching pace, casual",
            "Confrontation":             "two people facing each other in tense confrontation, aggressive stances",
            "Back to back":              "two people standing back to back, arms crossed, dramatic",
            "One leading the other":     "one person leading, the other following behind",
            "Group huddle":              "group of people huddled together, leaning inward",
            "Group line-up":             "group standing in a line facing camera, evenly spaced",
            "Dancing together":          "two people dancing together, one leading, graceful movement",
            "Helping / supporting":      "one person helping another up, supportive gesture",
            "Sitting together":          "people sitting together on a bench, casual gathering",
        }

        STYLE_PRESETS = {
            "Photorealistic":            "photorealistic, natural lighting, detailed skin texture",
            "Cinematic":                 "cinematic lighting, dramatic shadows, film grain, movie still",
            "Anime / Manga":            "anime style, cel shading, expressive features",
            "Comic book":                "comic book art style, bold outlines, dynamic composition",
            "Fashion editorial":         "fashion photography style, editorial lighting, model pose",
            "Sports photography":        "sports photography, frozen action, high shutter speed",
            "Fine art":                  "fine art photography, artistic composition, gallery quality",
            "Keep original style":       "",
        }

        # ── Dialog ────────────────────────────────────────────────────
        dlg = Gtk.Dialog(title="Spellcaster — Klein Re-poser")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Re-pose", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(6); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(10); bx.set_margin_bottom(10)

        _hdr = _make_branded_header()
        if _hdr: bx.pack_start(_hdr, False, False, 0)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        srv_e = Gtk.Entry(); srv_e.set_text(COMFYUI_DEFAULT_URL); srv_e.set_hexpand(True)
        srv_e.set_tooltip_text("ComfyUI server address")
        hb.pack_start(srv_e, True, True, 0); bx.pack_start(hb, False, False, 0)

        # Klein model
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="Klein Model:"), False, False, 0)
        klein_combo = Gtk.ComboBoxText()
        for k in KLEIN_MODELS: klein_combo.append(k, k)
        klein_combo.set_active_id("Klein 9B")
        klein_combo.set_tooltip_text("Klein 9B: best quality. Klein 4B: faster, lower VRAM")
        hb2.pack_start(klein_combo, True, True, 0); bx.pack_start(hb2, False, False, 0)

        # Character count
        hb3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb3.pack_start(Gtk.Label(label="Subject:"), False, False, 0)
        char_combo = Gtk.ComboBoxText()
        for k in CHAR_TEMPLATES: char_combo.append(k, k)
        char_combo.set_active_id("Single character")
        char_combo.set_tooltip_text("How many characters / subjects are in the image?")
        hb3.pack_start(char_combo, True, True, 0); bx.pack_start(hb3, False, False, 0)

        # Pose preset
        hb4 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb4.pack_start(Gtk.Label(label="Pose:"), False, False, 0)
        pose_combo = Gtk.ComboBoxText()
        for k in POSE_PRESETS: pose_combo.append(k, k)
        pose_combo.set_active(0)
        pose_combo.set_tooltip_text("Target body pose — the AI will attempt to repose the subject to match")
        hb4.pack_start(pose_combo, True, True, 0); bx.pack_start(hb4, False, False, 0)

        # Position preset
        hb5 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb5.pack_start(Gtk.Label(label="Position:"), False, False, 0)
        pos_combo = Gtk.ComboBoxText()
        for k in POSITION_PRESETS: pos_combo.append(k, k)
        pos_combo.set_active(0)
        pos_combo.set_tooltip_text("Move the subject within the frame")
        hb5.pack_start(pos_combo, True, True, 0); bx.pack_start(hb5, False, False, 0)

        # ── Advanced expander ─────────────────────────────────────────
        exp = Gtk.Expander(label="  Advanced options...")
        exp.set_expanded(False)
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        # Camera angle
        hca = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hca.pack_start(Gtk.Label(label="Camera:"), False, False, 0)
        cam_combo = Gtk.ComboBoxText()
        for k in CAMERA_PRESETS: cam_combo.append(k, k)
        cam_combo.set_active(0)
        cam_combo.set_tooltip_text("Change camera angle / framing")
        hca.pack_start(cam_combo, True, True, 0); adv_box.pack_start(hca, False, False, 0)

        # Multi-character interaction
        hmc = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hmc.pack_start(Gtk.Label(label="Interaction:"), False, False, 0)
        multi_combo = Gtk.ComboBoxText()
        multi_combo.append("(none)", "(none — single subject)")
        for k in MULTI_CHAR_PRESETS: multi_combo.append(k, k)
        multi_combo.set_active(0)
        multi_combo.set_tooltip_text("For multi-character scenes: how subjects interact")
        hmc.pack_start(multi_combo, True, True, 0); adv_box.pack_start(hmc, False, False, 0)

        # Style
        hst = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hst.pack_start(Gtk.Label(label="Style:"), False, False, 0)
        style_combo = Gtk.ComboBoxText()
        for k in STYLE_PRESETS: style_combo.append(k, k)
        style_combo.set_active_id("Keep original style")
        style_combo.set_tooltip_text("Art style or photography style to apply")
        hst.pack_start(style_combo, True, True, 0); adv_box.pack_start(hst, False, False, 0)

        # Denoise
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label="Denoise:"), 0, 0, 1, 1)
        denoise_sp = Gtk.SpinButton.new_with_range(0.50, 1.0, 0.05)
        denoise_sp.set_value(0.82)
        denoise_sp.set_digits(2)
        denoise_sp.set_tooltip_text("How much freedom the AI has to change the image.\n"
                                     "0.70 = subtle reposing, keeps most details\n"
                                     "0.82 = balanced (default)\n"
                                     "0.95 = major reposing, more creative freedom")
        grid.attach(denoise_sp, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Steps:"), 0, 1, 1, 1)
        steps_sp = Gtk.SpinButton.new_with_range(8, 50, 1)
        steps_sp.set_value(25)
        steps_sp.set_tooltip_text("More steps = finer detail but slower. 20-30 recommended")
        grid.attach(steps_sp, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Seed:"), 0, 2, 1, 1)
        seed_sp = Gtk.SpinButton.new_with_range(-1, 2**32, 1)
        seed_sp.set_value(-1)
        seed_sp.set_tooltip_text("-1 = random seed each run. Fix a seed to reproduce results")
        grid.attach(seed_sp, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="Runs:"), 0, 3, 1, 1)
        runs_sp = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_sp.set_value(1)
        runs_sp.set_tooltip_text("Generate multiple variations — each with a different random seed")
        grid.attach(runs_sp, 1, 3, 1, 1)
        adv_box.pack_start(grid, False, False, 4)

        exp.add(adv_box)
        _shrink_on_collapse(exp, dlg)
        bx.pack_start(exp, False, False, 0)

        # ── Prompt (editable, auto-filled from presets) ───────────────
        bx.pack_start(Gtk.Label(label="Prompt (auto-built from presets above, edit freely):"),
                       False, False, 2)
        sw = Gtk.ScrolledWindow(); sw.set_min_content_height(90)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_tooltip_text("Full prompt sent to Klein. Auto-generated from your preset\n"
                                    "selections above — feel free to edit, add details, or rewrite entirely")
        sw.add(prompt_tv); bx.pack_start(sw, True, True, 0)

        # ── Auto-build prompt from combos ─────────────────────────────
        def _rebuild_prompt(*_args):
            char_key = char_combo.get_active_id() or "Single character"
            pose_key = pose_combo.get_active_id() or "Standing relaxed"
            pos_key = pos_combo.get_active_id() or "Keep current position"
            cam_key = cam_combo.get_active_id() or "Keep current angle"
            multi_key = multi_combo.get_active_id() or "(none)"
            style_key = style_combo.get_active_id() or "Keep original style"

            parts = []
            # Subject
            parts.append(CHAR_TEMPLATES.get(char_key, "a person"))
            # Pose
            parts.append(POSE_PRESETS.get(pose_key, "standing relaxed"))
            # Multi-char interaction
            if multi_key != "(none)" and multi_key in MULTI_CHAR_PRESETS:
                parts.append(MULTI_CHAR_PRESETS[multi_key])
            # Position
            pos_txt = POSITION_PRESETS.get(pos_key, "")
            if pos_txt: parts.append(pos_txt)
            # Camera
            cam_txt = CAMERA_PRESETS.get(cam_key, "")
            if cam_txt: parts.append(cam_txt)
            # Style
            style_txt = STYLE_PRESETS.get(style_key, "")
            if style_txt: parts.append(style_txt)
            # Always add quality tail
            parts.append("high quality, detailed, masterful composition")

            prompt_tv.get_buffer().set_text(", ".join(parts))

        for combo in [char_combo, pose_combo, pos_combo, cam_combo, multi_combo, style_combo]:
            combo.connect("changed", _rebuild_prompt)
        _rebuild_prompt()  # initial fill

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        # Collect values
        srv = srv_e.get_text().strip(); _propagate_server_url(srv)
        klein_key = klein_combo.get_active_id() or "Klein 9B"
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        denoise = denoise_sp.get_value()
        steps = int(steps_sp.get_value())
        runs = int(runs_sp.get_value())
        base_seed = int(seed_sp.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        dlg.destroy()

        try:
            _update_spinner_status("Klein Re-poser: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_repose_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)

            km = KLEIN_MODELS[klein_key]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                label = f"Klein Re-poser run {run_i+1}/{runs}" if runs > 1 else "Klein Re-poser"
                wf = {
                    "1": {"class_type": "UNETLoader",
                          "inputs": {"unet_name": km["unet"], "weight_dtype": "default"}},
                    "2": {"class_type": "CLIPLoader",
                          "inputs": {"clip_name": km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
                                     "type": "flux2", "device": "default"}},
                    "3": {"class_type": "VAELoader",
                          "inputs": {"vae_name": "flux2-vae.safetensors"}},
                    "4": {"class_type": "CLIPTextEncode",
                          "inputs": {"text": prompt, "clip": ["2", 0]}},
                    "5": {"class_type": "ConditioningZeroOut",
                          "inputs": {"conditioning": ["4", 0]}},
                    "10": {"class_type": "LoadImage",
                           "inputs": {"image": uname}},
                    "11": {"class_type": "ImageScaleToTotalPixels",
                           "inputs": {"image": ["10", 0], "upscale_method": "nearest-exact",
                                      "megapixels": 1.0, "resolution_steps": 16}},
                    "12": {"class_type": "GetImageSize",
                           "inputs": {"image": ["11", 0]}},
                    "13": {"class_type": "VAEEncode",
                           "inputs": {"pixels": ["11", 0], "vae": ["3", 0]}},
                    "20": {"class_type": "ReferenceLatent",
                           "inputs": {"conditioning": ["4", 0], "latent": ["13", 0]}},
                    "21": {"class_type": "ReferenceLatent",
                           "inputs": {"conditioning": ["5", 0], "latent": ["13", 0]}},
                    "30": {"class_type": "CFGGuider",
                           "inputs": {"model": ["1", 0], "positive": ["20", 0],
                                      "negative": ["21", 0], "cfg": 1.0}},
                    "31": {"class_type": "KSamplerSelect",
                           "inputs": {"sampler_name": "euler"}},
                    "32": {"class_type": "Flux2Scheduler",
                           "inputs": {"steps": steps, "denoise": denoise,
                                      "width": ["12", 0], "height": ["12", 1]}},
                    "33": {"class_type": "RandomNoise",
                           "inputs": {"noise_seed": seed}},
                    "34": {"class_type": "EmptyFlux2LatentImage",
                           "inputs": {"width": ["12", 0], "height": ["12", 1],
                                      "batch_size": 1}},
                    "40": {"class_type": "SamplerCustomAdvanced",
                           "inputs": {"noise": ["33", 0], "guider": ["30", 0],
                                      "sampler": ["31", 0], "sigmas": ["32", 0],
                                      "latent_image": ["34", 0]}},
                    "50": {"class_type": "VAEDecode",
                           "inputs": {"samples": ["40", 0], "vae": ["3", 0]}},
                    "60": {"class_type": "SaveImage",
                           "inputs": {"images": ["50", 0], "filename_prefix": "spellcaster_repose"}},
                }

                results = _run_with_spinner(f"{label}: generating new pose...",
                                             lambda: list(_run_comfyui_workflow(srv, wf, timeout=300)))
                for i, (fn, sf, ft) in enumerate(results):
                    lbl = f"Klein Repose run {run_i+1} #{i+1}" if runs > 1 else f"Klein Repose #{i+1}"
                    _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Klein Re-poser Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    # ── Klein Inpaint Selection ─────────────────────────────────────────
    def _run_klein_inpaint(self, procedure, run_mode, image, drawables, config, data):
        """Klein Inpaint: regenerate selected area using Flux 2 Klein with
        ReferenceLatent context, SetLatentNoiseMask precision, and optional
        DifferentialDiffusion for smooth edges."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        # ── Inpaint task presets ──────────────────────────────────────
        INPAINT_PRESETS = {
            "Replace object (describe the replacement)": {
                "prompt_hint": "Describe what should replace the selected area",
                "denoise": 0.92, "steps": 25,
            },
            "Remove object (fill with background)": {
                "prompt_hint": "clean background, seamless surface, matching surroundings, no artifacts",
                "denoise": 0.95, "steps": 25,
            },
            "Fix face / restore features": {
                "prompt_hint": "detailed human face, sharp eyes, natural skin, correct symmetry, proper anatomy",
                "denoise": 0.45, "steps": 20,
            },
            "Fix hands / fingers": {
                "prompt_hint": "anatomically correct hand, five fingers, natural pose, proper proportions, realistic",
                "denoise": 0.55, "steps": 25,
            },
            "Change clothing / outfit": {
                "prompt_hint": "Describe the new clothing, e.g. 'elegant red dress, silk fabric, flowing'",
                "denoise": 0.85, "steps": 25,
            },
            "Change expression / emotion": {
                "prompt_hint": "Describe the expression, e.g. 'warm genuine smile, happy eyes, natural expression'",
                "denoise": 0.50, "steps": 20,
            },
            "Add object / element": {
                "prompt_hint": "Describe what to add, e.g. 'a small cat sitting, fluffy fur, cute'",
                "denoise": 0.95, "steps": 25,
            },
            "Change material / texture": {
                "prompt_hint": "Describe the new material, e.g. 'polished marble surface, reflective, veined'",
                "denoise": 0.75, "steps": 20,
            },
            "Change hair / hairstyle": {
                "prompt_hint": "Describe the hairstyle, e.g. 'long flowing blonde hair, wavy, golden highlights'",
                "denoise": 0.70, "steps": 25,
            },
            "Fill / extend pattern": {
                "prompt_hint": "seamless continuation of the surrounding pattern, matching texture, color, and rhythm",
                "denoise": 0.80, "steps": 20,
            },
            "Change color / recolor area": {
                "prompt_hint": "Describe the new color, e.g. 'vivid bright red, saturated, uniform color'",
                "denoise": 0.55, "steps": 18,
            },
            "Change background (behind subject)": {
                "prompt_hint": "Describe the new background, e.g. 'sunset beach, golden hour, soft waves'",
                "denoise": 0.90, "steps": 25,
            },
            "Weather / lighting change": {
                "prompt_hint": "Describe the new conditions, e.g. 'snowy winter scene, soft snowfall, cold light'",
                "denoise": 0.70, "steps": 22,
            },
            "Improve detail / sharpen area": {
                "prompt_hint": "highly detailed, sharp focus, fine textures, enhanced clarity, photorealistic",
                "denoise": 0.30, "steps": 15,
            },
            "Remove object from hand": {
                "prompt_hint": "empty hand, open palm, natural hand pose, no object, correct fingers, "
                               "matching skin tone, same lighting, hand in front of body, anatomically correct hand",
                "denoise": 0.72, "steps": 25,
            },
            "Creative reimagine (high freedom)": {
                "prompt_hint": "Describe your creative vision — high denoise gives Klein full artistic freedom",
                "denoise": 0.98, "steps": 30,
            },
            "(custom — manual settings)": {
                "prompt_hint": "",
                "denoise": 0.80, "steps": 20,
            },
        }

        # ── Dialog ────────────────────────────────────────────────────
        dlg = Gtk.Dialog(title="Spellcaster — Klein Inpaint Selection")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Inpaint", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(6); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(10); bx.set_margin_bottom(10)

        _hdr = _make_branded_header()
        if _hdr: bx.pack_start(_hdr, False, False, 0)

        bx.pack_start(Gtk.Label(label="Regenerate the selected area using Klein AI.\n"
                                      "Use any GIMP selection tool to mark what to change."),
                       False, False, 2)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        srv_e = Gtk.Entry(); srv_e.set_text(COMFYUI_DEFAULT_URL); srv_e.set_hexpand(True)
        srv_e.set_tooltip_text("ComfyUI server address")
        hb.pack_start(srv_e, True, True, 0); bx.pack_start(hb, False, False, 0)

        # Klein model
        hm = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hm.pack_start(Gtk.Label(label="Klein Model:"), False, False, 0)
        klein_combo = Gtk.ComboBoxText()
        for k in KLEIN_MODELS: klein_combo.append(k, k)
        klein_combo.set_active_id("Klein 9B")
        klein_combo.set_tooltip_text("Klein 9B: best quality and coherence.\n"
                                      "Klein 4B: faster, lower VRAM, good for quick iterations")
        hm.pack_start(klein_combo, True, True, 0); bx.pack_start(hm, False, False, 0)

        # Task preset
        ht = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        ht.pack_start(Gtk.Label(label="Task:"), False, False, 0)
        task_combo = Gtk.ComboBoxText()
        for k in INPAINT_PRESETS: task_combo.append(k, k)
        task_combo.set_active(0)
        task_combo.set_tooltip_text("What you're doing with the selection.\n"
                                     "Auto-fills the prompt and sets optimal denoise/steps.\n"
                                     "You can always edit the prompt and settings after.")
        ht.pack_start(task_combo, True, True, 0); bx.pack_start(ht, False, False, 0)

        # Prompt
        bx.pack_start(Gtk.Label(label="Prompt (what should appear in the selected area):"),
                       False, False, 2)
        sw = Gtk.ScrolledWindow(); sw.set_min_content_height(80)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_tooltip_text("Describe what Klein should generate in the selected region.\n"
                                    "Be specific about details, materials, lighting.\n"
                                    "Klein understands the surrounding context via the reference image.")
        sw.add(prompt_tv); bx.pack_start(sw, True, True, 0)

        # ── Settings grid ─────────────────────────────────────────────
        grid = Gtk.Grid(column_spacing=10, row_spacing=4)

        grid.attach(Gtk.Label(label="Denoise:", xalign=1), 0, 0, 1, 1)
        denoise_sp = Gtk.SpinButton.new_with_range(0.10, 1.0, 0.05)
        denoise_sp.set_value(0.92); denoise_sp.set_digits(2)
        denoise_sp.set_tooltip_text("How much Klein can change the selected area:\n"
                                     "  0.30 = subtle touch-up, keeps most existing detail\n"
                                     "  0.55 = moderate change, face/expression fixes\n"
                                     "  0.80 = significant change, new objects\n"
                                     "  0.95 = near-total regeneration, object replacement\n"
                                     "  1.00 = full generation (ignores original content)")
        grid.attach(denoise_sp, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Steps:", xalign=1), 2, 0, 1, 1)
        steps_sp = Gtk.SpinButton.new_with_range(8, 50, 1)
        steps_sp.set_value(25)
        steps_sp.set_tooltip_text("Sampling steps. 20-30 recommended for quality")
        grid.attach(steps_sp, 3, 0, 1, 1)

        grid.attach(Gtk.Label(label="Seed:", xalign=1), 0, 1, 1, 1)
        seed_sp = Gtk.SpinButton.new_with_range(-1, 2**32, 1)
        seed_sp.set_value(-1)
        seed_sp.set_tooltip_text("-1 = random seed. Fix a seed to get reproducible results")
        grid.attach(seed_sp, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Runs:", xalign=1), 2, 1, 1, 1)
        runs_sp = Gtk.SpinButton.new_with_range(1, 10, 1)
        runs_sp.set_value(1)
        runs_sp.set_tooltip_text("Generate multiple variations — each uses a different random seed")
        grid.attach(runs_sp, 3, 1, 1, 1)

        bx.pack_start(grid, False, False, 4)

        # ── Advanced expander ─────────────────────────────────────────
        exp = Gtk.Expander(label="  Advanced options...")
        exp.set_expanded(False)
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        # Mask blur
        hbl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbl.pack_start(Gtk.Label(label="Mask blur (edge softness):"), False, False, 0)
        blur_sp = Gtk.SpinButton.new_with_range(0, 64, 1)
        blur_sp.set_value(8)
        blur_sp.set_tooltip_text("Gaussian blur applied to the mask edges.\n"
                                  "Higher = smoother blending with surrounding area.\n"
                                  "0 = hard/sharp edges (for precise cutouts)\n"
                                  "8-16 = natural soft blending (recommended)\n"
                                  "32+ = very gradual transition")
        hbl.pack_start(blur_sp, True, True, 0); adv_box.pack_start(hbl, False, False, 0)

        # Grow/shrink mask
        hgs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hgs.pack_start(Gtk.Label(label="Grow selection (px):"), False, False, 0)
        grow_sp = Gtk.SpinButton.new_with_range(-50, 50, 1)
        grow_sp.set_value(4)
        grow_sp.set_tooltip_text("Expand or shrink the selection mask.\n"
                                  "Positive = grow outward (catches edge artifacts)\n"
                                  "Negative = shrink inward\n"
                                  "4px grow recommended for natural blending")
        hgs.pack_start(grow_sp, True, True, 0); adv_box.pack_start(hgs, False, False, 0)

        # Differential diffusion toggle
        dd_check = Gtk.CheckButton(label="Smooth edges (DifferentialDiffusion)")
        dd_check.set_active(True)
        dd_check.set_tooltip_text("Uses DifferentialDiffusion for gradient-aware edge blending.\n"
                                   "Produces cleaner, more natural transitions at mask boundaries.\n"
                                   "Recommended ON for most tasks. Disable only if you want\n"
                                   "hard/precise mask edges (e.g., pixel art, text).")
        adv_box.pack_start(dd_check, False, False, 0)

        exp.add(adv_box)
        _shrink_on_collapse(exp, dlg)
        bx.pack_start(exp, False, False, 0)

        # ── Preset auto-fill ──────────────────────────────────────────
        def _on_task_changed(*_a):
            key = task_combo.get_active_id()
            if key and key in INPAINT_PRESETS:
                p = INPAINT_PRESETS[key]
                if p["prompt_hint"]:
                    prompt_tv.get_buffer().set_text(p["prompt_hint"])
                denoise_sp.set_value(p["denoise"])
                steps_sp.set_value(p["steps"])
        task_combo.connect("changed", _on_task_changed)
        _on_task_changed()  # initial fill

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        # Collect values
        srv = srv_e.get_text().strip(); _propagate_server_url(srv)
        klein_key = klein_combo.get_active_id() or "Klein 9B"
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        denoise = denoise_sp.get_value()
        steps = int(steps_sp.get_value())
        runs = int(runs_sp.get_value())
        base_seed = int(seed_sp.get_value())
        mask_blur = int(blur_sp.get_value())
        grow_px = int(grow_sp.get_value())
        use_dd = dd_check.get_active()
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        dlg.destroy()

        try:
            km = KLEIN_MODELS[klein_key]

            # ── GIMP operations on main thread (before spinner) ───────
            # GIMP's PDB is not thread-safe. Mask creation and image
            # export use PDB calls that must run on the main thread.
            # Do them HERE, then pass the file paths to the spinner.
            global _mask_cache
            sel_hash = _selection_hash(image)
            if (sel_hash
                    and _mask_cache["selection_hash"] == sel_hash
                    and _mask_cache["server"] == srv
                    and _mask_cache["uploaded_name"]):
                mname = _mask_cache["uploaded_name"]
            else:
                mtmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False); mtmp.close()
                _create_selection_mask_png(mtmp.name, image)
                mname = f"gimp_mask_{uuid.uuid4().hex[:8]}.png"
                _upload_image(srv, mtmp.name, mname)
                _mask_cache = {
                    "selection_hash": sel_hash,
                    "mask_path": mtmp.name,
                    "uploaded_name": mname,
                    "server": srv,
                }

            tmp = _export_image_to_tmp(image)
            uname = f"gimp_kinp_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)

            # ── Background thread: network I/O + ComfyUI workflow ─────
            def _do_klein_inpaint():
                all_results = []
                for run_i in range(runs):
                    seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)

                    wf = {
                        "1": {"class_type": "UNETLoader",
                              "inputs": {"unet_name": km["unet"], "weight_dtype": "default"}},
                        "2": {"class_type": "CLIPLoader",
                              "inputs": {"clip_name": km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
                                         "type": "flux2", "device": "default"}},
                        "3": {"class_type": "VAELoader",
                              "inputs": {"vae_name": "flux2-vae.safetensors"}},
                        "10": {"class_type": "LoadImage",
                               "inputs": {"image": uname}},
                        "11": {"class_type": "LoadImage",
                               "inputs": {"image": mname}},
                        "12": {"class_type": "ImageToMask",
                               "inputs": {"image": ["11", 0], "channel": "red"}},
                    }

                    mask_ref = ["12", 0]
                    if grow_px != 0:
                        wf["13"] = {"class_type": "GrowMask",
                                    "inputs": {"mask": mask_ref, "expand": grow_px,
                                               "tapered_corners": True}}
                        mask_ref = ["13", 0]

                    wf["15"] = {"class_type": "ImageScaleToTotalPixels",
                                "inputs": {"image": ["10", 0], "upscale_method": "nearest-exact",
                                           "megapixels": 1.0, "resolution_steps": 16}}
                    wf["16"] = {"class_type": "GetImageSize",
                                "inputs": {"image": ["15", 0]}}
                    wf["17"] = {"class_type": "VAEEncode",
                                "inputs": {"pixels": ["15", 0], "vae": ["3", 0]}}
                    wf["18"] = {"class_type": "SetLatentNoiseMask",
                                "inputs": {"samples": ["17", 0], "mask": mask_ref}}
                    wf["20"] = {"class_type": "CLIPTextEncode",
                                "inputs": {"text": prompt, "clip": ["2", 0]}}
                    wf["21"] = {"class_type": "ConditioningZeroOut",
                                "inputs": {"conditioning": ["20", 0]}}
                    wf["22"] = {"class_type": "ReferenceLatent",
                                "inputs": {"conditioning": ["20", 0], "latent": ["17", 0]}}
                    wf["23"] = {"class_type": "ReferenceLatent",
                                "inputs": {"conditioning": ["21", 0], "latent": ["17", 0]}}

                    model_ref = ["1", 0]
                    if use_dd:
                        wf["24"] = {"class_type": "DifferentialDiffusion",
                                    "inputs": {"model": ["1", 0]}}
                        model_ref = ["24", 0]

                    wf["30"] = {"class_type": "CFGGuider",
                                "inputs": {"model": model_ref, "positive": ["22", 0],
                                           "negative": ["23", 0], "cfg": 1.0}}
                    wf["31"] = {"class_type": "KSamplerSelect",
                                "inputs": {"sampler_name": "euler"}}
                    wf["32"] = {"class_type": "Flux2Scheduler",
                                "inputs": {"steps": steps, "denoise": denoise,
                                           "width": ["16", 0], "height": ["16", 1]}}
                    wf["33"] = {"class_type": "RandomNoise",
                                "inputs": {"noise_seed": seed}}
                    wf["40"] = {"class_type": "SamplerCustomAdvanced",
                                "inputs": {"noise": ["33", 0], "guider": ["30", 0],
                                           "sampler": ["31", 0], "sigmas": ["32", 0],
                                           "latent_image": ["18", 0]}}
                    wf["50"] = {"class_type": "VAEDecode",
                                "inputs": {"samples": ["40", 0], "vae": ["3", 0]}}
                    wf["60"] = {"class_type": "SaveImage",
                                "inputs": {"images": ["50", 0],
                                           "filename_prefix": "spellcaster_klein_inpaint"}}

                    label = f"Klein Inpaint run {run_i+1}/{runs}" if runs > 1 else "Klein Inpaint"
                    _update_spinner_status(f"{label}: processing on ComfyUI...")
                    all_results.extend(list(_run_comfyui_workflow(srv, wf, timeout=300)))
                return all_results

            results = _run_with_spinner("Klein Inpaint: starting...", _do_klein_inpaint)
            if not results:
                Gimp.message("Klein Inpaint: ComfyUI returned no output images.\n"
                             "Check the ComfyUI console for errors.\n"
                             "Try disabling 'Smooth edges' in Advanced options.")
            for i, (fn, sf, ft) in enumerate(results):
                lbl = f"Klein Inpaint #{i+1}"
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft), lbl)
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Klein Inpaint Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    # ── Layer Blend by Ratio (utility) ────────────────────────────────
    def _run_layer_blend_ratio(self, procedure, run_mode, image, drawables, config, data):
        """Blend two layers by ratio using ComfyUI ImageBlend node."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        layers = image.get_layers()
        if len(layers) < 2:
            Gimp.message("Need at least 2 layers to blend.\n\nLayer 1 = Image A\nLayer 2 = Image B\n"
                         "The blend ratio controls how much of each layer appears in the result.")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        BLEND_MODES = ["normal", "multiply", "screen", "overlay", "soft_light", "difference"]

        dlg = Gtk.Dialog(title="Spellcaster — Layer Blend by Ratio")
        dlg.set_default_size(460, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Blend", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(6); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(10); bx.set_margin_bottom(10)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        srv_e = Gtk.Entry(); srv_e.set_text(COMFYUI_DEFAULT_URL); srv_e.set_hexpand(True)
        hb.pack_start(srv_e, True, True, 0); bx.pack_start(hb, False, False, 0)

        bx.pack_start(Gtk.Label(label="Blend two layers by a controllable ratio.\n"
                                      "0% = 100% Layer A, 100% = 100% Layer B."),
                       False, False, 4)

        # Layer A
        hla = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hla.pack_start(Gtk.Label(label="Layer A:"), False, False, 0)
        la_combo = Gtk.ComboBoxText()
        for idx, l in enumerate(layers):
            la_combo.append(str(idx), l.get_name())
        la_combo.set_active(0)
        la_combo.set_tooltip_text("First image (base). At ratio 0% you see only this layer")
        hla.pack_start(la_combo, True, True, 0); bx.pack_start(hla, False, False, 0)

        # Layer B
        hlb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hlb.pack_start(Gtk.Label(label="Layer B:"), False, False, 0)
        lb_combo = Gtk.ComboBoxText()
        for idx, l in enumerate(layers):
            lb_combo.append(str(idx), l.get_name())
        lb_combo.set_active(1 if len(layers) > 1 else 0)
        lb_combo.set_tooltip_text("Second image (blend target). At ratio 100% you see only this layer")
        hlb.pack_start(lb_combo, True, True, 0); bx.pack_start(hlb, False, False, 0)

        # Blend ratio slider
        hr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hr.pack_start(Gtk.Label(label="Blend ratio:"), False, False, 0)
        ratio_sp = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        ratio_sp.set_value(0.50)
        ratio_sp.set_digits(2)
        ratio_sp.set_tooltip_text("0.0 = 100% Layer A\n0.5 = equal mix\n1.0 = 100% Layer B")
        hr.pack_start(ratio_sp, True, True, 0)
        # Percentage label
        pct_label = Gtk.Label(label="50% A / 50% B")
        def _update_pct(*_a):
            r = ratio_sp.get_value()
            pct_label.set_text(f"{100 - r*100:.0f}% A / {r*100:.0f}% B")
        ratio_sp.connect("value-changed", _update_pct)
        hr.pack_start(pct_label, False, False, 4)
        bx.pack_start(hr, False, False, 0)

        # Blend mode
        hm = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hm.pack_start(Gtk.Label(label="Mode:"), False, False, 0)
        mode_combo = Gtk.ComboBoxText()
        for m in BLEND_MODES: mode_combo.append(m, m)
        mode_combo.set_active_id("normal")
        mode_combo.set_tooltip_text("Blending mode:\n• normal: linear interpolation (most common)\n"
                                     "• multiply: darkens, good for shadows\n• screen: lightens\n"
                                     "• overlay: contrast boost\n• soft_light: subtle toning")
        hm.pack_start(mode_combo, True, True, 0); bx.pack_start(hm, False, False, 0)

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        srv = srv_e.get_text().strip(); _propagate_server_url(srv)
        la_idx = int(la_combo.get_active_id() or "0")
        lb_idx = int(lb_combo.get_active_id() or "1")
        ratio = ratio_sp.get_value()
        mode = mode_combo.get_active_id() or "normal"
        dlg.destroy()

        try:
            _update_spinner_status("Layer Blend: exporting layers...")
            # Export Layer A
            a_img = Gimp.Image.new(image.get_width(), image.get_height(), Gimp.ImageBaseType.RGB)
            a_copy = Gimp.Layer.new_from_drawable(layers[la_idx], a_img)
            a_img.insert_layer(a_copy, None, 0); a_img.flatten()
            a_tmp = _export_image_to_tmp(a_img); a_img.delete()
            # Export Layer B
            b_img = Gimp.Image.new(image.get_width(), image.get_height(), Gimp.ImageBaseType.RGB)
            b_copy = Gimp.Layer.new_from_drawable(layers[lb_idx], b_img)
            b_img.insert_layer(b_copy, None, 0); b_img.flatten()
            b_tmp = _export_image_to_tmp(b_img); b_img.delete()

            a_name = f"blend_a_{uuid.uuid4().hex[:8]}.png"
            b_name = f"blend_b_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, a_tmp, a_name); os.unlink(a_tmp)
            _upload_image(srv, b_tmp, b_name); os.unlink(b_tmp)

            wf = {
                "1": {"class_type": "LoadImage", "inputs": {"image": a_name}},
                "2": {"class_type": "LoadImage", "inputs": {"image": b_name}},
                "3": {"class_type": "ImageBlend", "inputs": {
                    "image1": ["1", 0], "image2": ["2", 0],
                    "blend_factor": ratio, "blend_mode": mode}},
                "4": {"class_type": "SaveImage", "inputs": {
                    "images": ["3", 0], "filename_prefix": "spellcaster_blend_ratio"}},
            }

            results = _run_with_spinner("Layer Blend: processing...",
                                         lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Blend {100 - ratio*100:.0f}A/{ratio*100:.0f}B #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Layer Blend Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    # ── Upscaler Ratio Blender ────────────────────────────────────────
    def _run_upscale_blend(self, procedure, run_mode, image, drawables, config, data):
        """Upscale with two models and blend results by ratio."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        # Filter out (none)
        models = {k: v for k, v in UPSCALE_PRESETS.items() if v is not None}

        dlg = Gtk.Dialog(title="Spellcaster — Upscaler Ratio Blender")
        dlg.set_default_size(500, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Upscale && Blend", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(6); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(10); bx.set_margin_bottom(10)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        srv_e = Gtk.Entry(); srv_e.set_text(COMFYUI_DEFAULT_URL); srv_e.set_hexpand(True)
        hb.pack_start(srv_e, True, True, 0); bx.pack_start(hb, False, False, 0)

        bx.pack_start(Gtk.Label(label="Upscale with two different models and blend the results.\n"
                                      "Example: 40% ESRGAN (sharp) + 60% Remacri (smooth) for balanced output."),
                       False, False, 4)

        # Model A
        ha = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        ha.pack_start(Gtk.Label(label="Model A:"), False, False, 0)
        ma_combo = Gtk.ComboBoxText()
        for k in models: ma_combo.append(k, k)
        ma_combo.set_active(0)
        ma_combo.set_tooltip_text("First upscale model. Its result weight = (1 - ratio)")
        ha.pack_start(ma_combo, True, True, 0); bx.pack_start(ha, False, False, 0)

        # Model B
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="Model B:"), False, False, 0)
        mb_combo = Gtk.ComboBoxText()
        for k in models: mb_combo.append(k, k)
        # Default to Remacri if available
        keys = list(models.keys())
        mb_combo.set_active(3 if len(keys) > 3 else min(1, len(keys)-1))
        mb_combo.set_tooltip_text("Second upscale model. Its result weight = ratio")
        hb2.pack_start(mb_combo, True, True, 0); bx.pack_start(hb2, False, False, 0)

        # Ratio slider
        hr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hr.pack_start(Gtk.Label(label="Blend ratio:"), False, False, 0)
        ratio_sp = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        ratio_sp.set_value(0.60)
        ratio_sp.set_digits(2)
        ratio_sp.set_tooltip_text("0.0 = 100% Model A\n0.5 = equal mix\n1.0 = 100% Model B\n\n"
                                   "Example: 0.60 = 40% Model A + 60% Model B")
        hr.pack_start(ratio_sp, True, True, 0)
        pct_label = Gtk.Label(label="40% A / 60% B")
        def _update_pct(*_a):
            r = ratio_sp.get_value()
            pct_label.set_text(f"{100 - r*100:.0f}% A / {r*100:.0f}% B")
        ratio_sp.connect("value-changed", _update_pct)
        hr.pack_start(pct_label, False, False, 4)
        bx.pack_start(hr, False, False, 0)

        # Quick presets
        bx.pack_start(Gtk.Label(label="Quick recipes:"), False, False, 2)
        RECIPES = {
            "Balanced (50/50 UltraSharp + Remacri)": ("4x UltraSharp (general)", "4x Remacri (restoration)", 0.50),
            "Sharp detail (70% UltraSharp + 30% ESRGAN)": ("4x UltraSharp (general)", "4x RealESRGAN (photo)", 0.30),
            "Smooth restoration (30% ESRGAN + 70% Remacri)": ("4x RealESRGAN (photo)", "4x Remacri (restoration)", 0.70),
            "Anime blend (60% Anime + 40% UltraSharp)": ("4x RealESRGAN Anime", "4x UltraSharp (general)", 0.40),
            "Portrait (40% Faces + 60% Remacri)": ("8x NMKD Faces (portraits)", "4x Remacri (restoration)", 0.60),
        }
        recipe_combo = Gtk.ComboBoxText()
        recipe_combo.append("(custom)", "(custom — use settings above)")
        for k in RECIPES: recipe_combo.append(k, k)
        recipe_combo.set_active(0)
        recipe_combo.set_tooltip_text("Pre-configured upscaler blending recipes.\n"
                                       "Select one to auto-fill Model A, Model B, and ratio")
        def _on_recipe(*_a):
            key = recipe_combo.get_active_id()
            if key and key != "(custom)" and key in RECIPES:
                a_key, b_key, r = RECIPES[key]
                ma_combo.set_active_id(a_key)
                mb_combo.set_active_id(b_key)
                ratio_sp.set_value(r)
        recipe_combo.connect("changed", _on_recipe)
        bx.pack_start(recipe_combo, False, False, 0)

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        srv = srv_e.get_text().strip(); _propagate_server_url(srv)
        ma_key = ma_combo.get_active_id()
        mb_key = mb_combo.get_active_id()
        ma_file = models.get(ma_key)
        mb_file = models.get(mb_key)
        ratio = ratio_sp.get_value()
        dlg.destroy()

        if not ma_file or not mb_file:
            Gimp.message("Please select two valid upscale models.")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        try:
            _update_spinner_status("Upscale Blend: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_upblend_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)

            wf = {
                # Load source image
                "1": {"class_type": "LoadImage", "inputs": {"image": uname}},
                # Model A upscale (1.5x factor to control output size)
                "10": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": ma_file}},
                "11": {"class_type": "ImageUpscaleWithModelByFactor", "inputs": {
                    "upscale_model": ["10", 0], "image": ["1", 0], "scale_by": 1.0}},
                # Model B upscale (same factor)
                "20": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": mb_file}},
                "21": {"class_type": "ImageUpscaleWithModelByFactor", "inputs": {
                    "upscale_model": ["20", 0], "image": ["1", 0], "scale_by": 1.0}},
                # Blend the two upscaled results
                "30": {"class_type": "ImageBlend", "inputs": {
                    "image1": ["11", 0], "image2": ["21", 0],
                    "blend_factor": ratio, "blend_mode": "normal"}},
                "40": {"class_type": "SaveImage", "inputs": {
                    "images": ["30", 0], "filename_prefix": "spellcaster_upblend"}},
            }

            results = _run_with_spinner("Upscale Blend: upscaling with two models and blending...",
                                         lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Upscale {100 - ratio*100:.0f}%{ma_key.split('(')[0].strip()}"
                                        f" + {ratio*100:.0f}%{mb_key.split('(')[0].strip()} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Upscaler Blend Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    # ── GIF Stitcher ──────────────────────────────────────────────────
    def _run_gif_stitch(self, procedure, run_mode, image, drawables, config, data):
        """Stitch multiple GIF files into one seamless animation."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        dlg = Gtk.Dialog(title="Spellcaster — GIF Stitcher")
        dlg.set_default_size(560, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Stitch", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(6); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(10); bx.set_margin_bottom(10)

        _hdr = _make_branded_header()
        if _hdr: bx.pack_start(_hdr, False, False, 0)

        bx.pack_start(Gtk.Label(
            label="Chain multiple GIF files into one seamless animation.\n"
                  "Add GIFs in order — they will play sequentially.\n"
                  "The result is a new image with all frames as layers."),
            False, False, 4)

        # GIF file list
        gif_store = Gtk.ListStore(str)  # filepath
        tree = Gtk.TreeView(model=gif_store)
        tree.set_headers_visible(True)
        tree.set_reorderable(True)  # drag to reorder
        col = Gtk.TreeViewColumn("GIF Files (drag to reorder)", Gtk.CellRendererText(), text=0)
        col.set_expand(True)
        tree.append_column(col)
        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(150)
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(tree)
        bx.pack_start(sw, True, True, 0)

        # Add / Remove buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn = Gtk.Button(label="Add GIF...")
        add_btn.set_tooltip_text("Add a GIF file to the stitch queue")
        def _on_add(*_a):
            fc = Gtk.FileChooserDialog(title="Select GIF File",
                                        action=Gtk.FileChooserAction.OPEN)
            fc.add_button("_Cancel", Gtk.ResponseType.CANCEL)
            fc.add_button("_Open", Gtk.ResponseType.OK)
            fc.set_select_multiple(True)
            ff = Gtk.FileFilter()
            ff.set_name("GIF Images")
            ff.add_pattern("*.gif")
            fc.add_filter(ff)
            if fc.run() == Gtk.ResponseType.OK:
                for path in fc.get_filenames():
                    gif_store.append([path])
            fc.destroy()
        add_btn.connect("clicked", _on_add)
        btn_row.pack_start(add_btn, False, False, 0)

        remove_btn = Gtk.Button(label="Remove Selected")
        remove_btn.set_tooltip_text("Remove the selected GIF from the queue")
        def _on_remove(*_a):
            sel = tree.get_selection()
            model, it = sel.get_selected()
            if it:
                model.remove(it)
        remove_btn.connect("clicked", _on_remove)
        btn_row.pack_start(remove_btn, False, False, 0)

        clear_btn = Gtk.Button(label="Clear All")
        def _on_clear(*_a):
            gif_store.clear()
        clear_btn.connect("clicked", _on_clear)
        btn_row.pack_start(clear_btn, False, False, 0)
        bx.pack_start(btn_row, False, False, 0)

        # Options
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label="Frame delay (ms):"), 0, 0, 1, 1)
        delay_sp = Gtk.SpinButton.new_with_range(10, 1000, 10)
        delay_sp.set_value(100)
        delay_sp.set_tooltip_text("Delay between frames in milliseconds.\n"
                                   "100ms = 10 FPS, 50ms = 20 FPS, 33ms = 30 FPS")
        grid.attach(delay_sp, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Output FPS:"), 2, 0, 1, 1)
        fps_label = Gtk.Label(label="10")
        grid.attach(fps_label, 3, 0, 1, 1)
        def _update_fps(*_a):
            fps_label.set_text(f"{1000 / max(1, delay_sp.get_value()):.0f}")
        delay_sp.connect("value-changed", _update_fps)

        export_check = Gtk.CheckButton(label="Auto-export as GIF")
        export_check.set_active(True)
        export_check.set_tooltip_text("Automatically export the stitched result as a GIF file.\n"
                                       "The file will be saved next to the first input GIF.")
        grid.attach(export_check, 0, 1, 2, 1)

        mp4_check = Gtk.CheckButton(label="Also export MP4")
        mp4_check.set_active(True)
        mp4_check.set_tooltip_text("Send stitched frames to ComfyUI to encode as MP4 video.\n"
                                    "Requires a running ComfyUI server.")
        grid.attach(mp4_check, 2, 1, 2, 1)

        # Server (for MP4 export)
        hb_srv = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_srv.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        srv_e = Gtk.Entry(); srv_e.set_text(COMFYUI_DEFAULT_URL); srv_e.set_hexpand(True)
        srv_e.set_tooltip_text("ComfyUI server (for MP4 export only)")
        hb_srv.pack_start(srv_e, True, True, 0)
        grid.attach(hb_srv, 0, 2, 4, 1)
        bx.pack_start(grid, False, False, 4)

        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        # Collect GIF paths in order
        gif_paths = []
        it = gif_store.get_iter_first()
        while it:
            gif_paths.append(gif_store.get_value(it, 0))
            it = gif_store.iter_next(it)
        delay = int(delay_sp.get_value())
        auto_export = export_check.get_active()
        export_mp4 = mp4_check.get_active()
        srv = srv_e.get_text().strip()
        dlg.destroy()

        if len(gif_paths) < 2:
            Gimp.message("Please add at least 2 GIF files to stitch.")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        try:
            # Load all GIFs and collect their frames
            all_frames = []
            max_w, max_h = 0, 0

            for gif_path in gif_paths:
                gfile = Gio.File.new_for_path(gif_path)
                gif_img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
                layers = gif_img.get_layers()
                # GIMP stores GIF frames as layers (bottom = first frame)
                # Reverse so we iterate first→last
                for layer in reversed(layers):
                    w, h = layer.get_width(), layer.get_height()
                    max_w = max(max_w, w)
                    max_h = max(max_h, h)
                    all_frames.append((gif_img, layer))

            if not all_frames:
                Gimp.message("No frames found in the GIF files.")
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

            # Create new image with all frames
            result = Gimp.Image.new(max_w, max_h, Gimp.ImageBaseType.RGB)

            for i, (src_img, src_layer) in enumerate(all_frames):
                new_layer = Gimp.Layer.new_from_drawable(src_layer, result)
                new_layer.set_name(f"Frame {i+1} ({delay}ms)")
                result.insert_layer(new_layer, None, 0)
                # Scale to canvas if different size
                if new_layer.get_width() != max_w or new_layer.get_height() != max_h:
                    new_layer.scale(max_w, max_h, False)

            # Clean up source images
            src_images = set(img for img, _ in all_frames)
            for src in src_images:
                src.delete()

            # Display the result
            Gimp.Display.new(result)
            Gimp.displays_flush()

            # Auto-export as GIF
            if auto_export:
                out_path = gif_paths[0].rsplit(".", 1)[0] + "_stitched.gif"
                gfile_out = Gio.File.new_for_path(out_path)
                try:
                    # Flatten to indexed for GIF export
                    dup = result.duplicate()
                    _pdb_run('gimp-image-convert-indexed', {
                        'image': dup, 'dither-type': 0, 'palette-type': 0,
                        'num-cols': 255, 'alpha-dither': False,
                        'remove-unused': False, 'palette': "",
                    })
                    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup,
                                   list(dup.get_layers()), gfile_out)
                    dup.delete()
                    Gimp.message(f"GIF stitched! {len(all_frames)} frames.\nExported to: {out_path}")
                except Exception as e:
                    Gimp.message(f"Stitched {len(all_frames)} frames as layers.\n"
                                 f"Auto-export failed: {e}\n"
                                 f"Use File > Export As to save as GIF manually.")
            else:
                Gimp.message(f"GIF stitched! {len(all_frames)} frames as layers.\n"
                             f"Use File > Export As to save as GIF.")

            # MP4 export via ComfyUI
            if export_mp4:
                try:
                    _propagate_server_url(srv)
                    # Export each frame as temp PNG and upload
                    frame_names = []
                    dup_mp4 = result.duplicate()
                    dup_mp4.flatten()
                    # Re-get the original result with all layers as frames
                    result_layers = result.get_layers()
                    for i, layer in enumerate(reversed(result_layers)):
                        tmp_img = Gimp.Image.new(max_w, max_h, Gimp.ImageBaseType.RGB)
                        tmp_layer = Gimp.Layer.new_from_drawable(layer, tmp_img)
                        tmp_img.insert_layer(tmp_layer, None, 0)
                        tmp_img.flatten()
                        tmp_path = _export_image_to_tmp(tmp_img)
                        tmp_img.delete()
                        fname = f"gimp_stitch_frame_{i:04d}.png"
                        _upload_image(srv, tmp_path, fname)
                        os.unlink(tmp_path)
                        frame_names.append(fname)
                    dup_mp4.delete()

                    # Build workflow: LoadImageBatch → VHS_VideoCombine
                    out_fps = 1000.0 / max(1, delay)
                    wf = {}
                    # Load first frame, then use batch
                    for i, fname in enumerate(frame_names):
                        wf[str(200 + i)] = {"class_type": "LoadImage",
                                             "inputs": {"image": fname}}

                    # Use ImageBatch to combine all frames
                    if len(frame_names) >= 2:
                        wf["300"] = {"class_type": "ImageBatch",
                                     "inputs": {"image1": ["200", 0], "image2": ["201", 0]}}
                        batch_ref = ["300", 0]
                        for i in range(2, len(frame_names)):
                            nid = str(300 + i - 1)
                            wf[nid] = {"class_type": "ImageBatch",
                                        "inputs": {"image1": batch_ref,
                                                   "image2": [str(200 + i), 0]}}
                            batch_ref = [nid, 0]
                    else:
                        batch_ref = ["200", 0]

                    wf["400"] = {"class_type": "VHS_VideoCombine",
                                 "inputs": {"images": batch_ref, "frame_rate": out_fps,
                                            "loop_count": 0, "filename_prefix": "gimp_gif_stitch",
                                            "format": "video/h264-mp4", "pingpong": False,
                                            "save_output": True}}
                    _run_with_spinner("Encoding MP4...",
                                       lambda: list(_run_comfyui_workflow(srv, wf, timeout=300)))
                    Gimp.message(f"MP4 exported! Check ComfyUI output folder.\n"
                                 f"{len(frame_names)} frames at {out_fps:.0f} FPS.")
                except Exception as e:
                    Gimp.message(f"MP4 export failed: {e}\nGIF stitch was successful.")

            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"GIF Stitch Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_embed_watermark(self, procedure, run_mode, image, drawables, config, data):
        """Embed invisible encrypted metadata into the current image using LSB steganography."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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

            _update_spinner_status("Embedding invisible watermark...")

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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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

            _update_spinner_status("Reading invisible watermark...")

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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        # Scale factor
        hb3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb3.pack_start(Gtk.Label(label="Scale factor:"), False, False, 0)
        scale_sp = Gtk.SpinButton.new_with_range(1.0, 8.0, 0.5)
        scale_sp.set_value(1.0); scale_sp.set_digits(1)
        scale_sp.set_tooltip_text("Output upscale factor.\n"
                                   "1.5x = 50% larger (fast, good for most uses)\n"
                                   "2.0x = double size\n"
                                   "4.0x = full 4x upscale (slow, large output)")
        hb3.pack_start(scale_sp, False, False, 0); bx.pack_start(hb3, False, False, 0)
        bx.pack_start(Gtk.Label(label="Upscales image using a super-resolution model.\nResult is imported as a new layer."), False, False, 4)
        bx.show_all()
        last = _SESSION.get("upscale")
        if last and "model_id" in last:
            model_combo.set_active_id(last["model_id"])
        if last and "scale" in last:
            scale_sp.set_value(last["scale"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        preset_key = model_combo.get_active_id()
        model_name = UPSCALE_PRESETS[preset_key]
        if not model_name:
            Gimp.message("Please select an upscale model (not 'none').")
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        upscale_factor = scale_sp.get_value()
        _SESSION["upscale"] = {"model_id": preset_key, "scale": upscale_factor}
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("Upscale: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_upscale_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_upscale(uname, model_name, upscale_factor=upscale_factor)
            results = _run_with_spinner("Upscale: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
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
        """Smart object removal: LaMa fast fill OR AI-guided replacement."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Spellcaster — Smart Object Removal")
        dlg.set_default_size(520, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Remove", Gtk.ResponseType.OK)
        _style_dialog_buttons(dlg)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)

        # What to remove
        bx.pack_start(Gtk.Label(label="What object are you removing?", xalign=0), False, False, 0)
        obj_entry = Gtk.Entry()
        obj_entry.set_placeholder_text("e.g., person, car, text, power lines, watermark...")
        obj_entry.set_tooltip_text(
            "Describe the object you want gone. This helps the AI understand\n"
            "what should NOT be in the result and what should REPLACE it.\n\n"
            "Examples: 'person', 'car in background', 'text overlay',\n"
            "'power lines', 'watermark', 'trash can'\n\n"
            "Leave blank for generic removal (LaMa mode).")
        bx.pack_start(obj_entry, False, False, 0)

        # Removal mode
        bx.pack_start(Gtk.Label(label="Removal Method:", xalign=0), False, False, 0)
        mode_combo = Gtk.ComboBoxText()
        mode_combo.append("lama", "LaMa Fast (no AI model — instant, good for simple backgrounds)")
        mode_combo.append("ai", "AI Replace (uses checkpoint — slower but much better results)")
        mode_combo.set_active(0)
        mode_combo.set_tooltip_text(
            "LaMa Fast: fills the selection with surrounding patterns. Best for\n"
            "simple backgrounds (sky, walls, ground). Instant, no prompt needed.\n\n"
            "AI Replace: uses an AI checkpoint to intelligently generate what\n"
            "should replace the removed object. Much better for complex scenes\n"
            "(crowds, detailed backgrounds, textured surfaces). Slower but\n"
            "produces seamless results guided by your object description.")
        bx.pack_start(mode_combo, False, False, 0)

        # AI Replace options (shown/hidden based on mode)
        ai_frame = Gtk.Frame(label="AI Replace Settings")
        ai_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ai_box.set_margin_start(8); ai_box.set_margin_end(8)
        ai_box.set_margin_top(8); ai_box.set_margin_bottom(8)

        ai_box.pack_start(Gtk.Label(label="Checkpoint Model:", xalign=0), False, False, 0)
        ai_model_combo = Gtk.ComboBoxText()
        for i, p in enumerate(MODEL_PRESETS):
            ai_model_combo.append(str(i), _model_label(p, "img2img"))
        _fav = _load_config().get("favourite_model", -1)
        if 0 <= _fav < len(MODEL_PRESETS):
            ai_model_combo.set_active_id(str(_fav))
        if ai_model_combo.get_active() < 0:
            ai_model_combo.set_active(0)
        ai_box.pack_start(ai_model_combo, False, False, 0)

        hb_den = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_den.pack_start(Gtk.Label(label="Denoise:"), False, False, 0)
        ai_denoise = Gtk.SpinButton.new_with_range(0.5, 1.0, 0.05)
        ai_denoise.set_value(0.85); ai_denoise.set_digits(2)
        ai_denoise.set_tooltip_text("How aggressively to replace the content.\n0.85 = strong replacement (recommended). Lower = more blending.")
        hb_den.pack_start(ai_denoise, False, False, 0)
        ai_box.pack_start(hb_den, False, False, 0)

        ai_box.pack_start(Gtk.Label(label="Replacement prompt (auto-generated, editable):", xalign=0), False, False, 0)
        ai_prompt = Gtk.TextView(); ai_prompt.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        ai_prompt.set_size_request(-1, 50)
        sw_p = Gtk.ScrolledWindow(); sw_p.add(ai_prompt); sw_p.set_min_content_height(50)
        ai_box.pack_start(sw_p, False, False, 0)

        ai_frame.add(ai_box)
        bx.pack_start(ai_frame, False, False, 0)

        # Auto-generate replacement prompt when object description changes
        def _update_ai_prompt(*args):
            obj = obj_entry.get_text().strip()
            if not obj:
                ai_prompt.get_buffer().set_text("clean background, seamless continuation, natural fill, matching surroundings")
            else:
                ai_prompt.get_buffer().set_text(
                    f"no {obj}, clean background where the {obj} was, "
                    f"seamless continuation of surrounding area, natural fill, "
                    f"matching lighting and texture, no trace of {obj}")
        obj_entry.connect("changed", _update_ai_prompt)
        _update_ai_prompt()

        # Show/hide AI frame based on mode
        def _on_mode_changed(combo):
            if combo.get_active_id() == "ai":
                ai_frame.show_all()
            else:
                ai_frame.hide()
            GLib.idle_add(lambda: dlg.resize(dlg.get_allocated_width(), 1) or False)
        mode_combo.connect("changed", _on_mode_changed)

        # Edge feather
        hb_feather = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_feather.pack_start(Gtk.Label(label="Edge Feather (px):"), False, False, 0)
        feather_spin = Gtk.SpinButton.new_with_range(0, 64, 1)
        feather_spin.set_value(4)
        feather_spin.set_tooltip_text("Soften mask edges for smoother blending. 4 = default.")
        hb_feather.pack_start(feather_spin, False, False, 0)
        bx.pack_start(hb_feather, False, False, 0)

        # How to use
        info_exp = Gtk.Expander(label="▸ How to use")
        info_exp.set_expanded(False)
        info_lbl = Gtk.Label(label=(
            "1. Select the object with GIMP's tools (Free Select, Fuzzy Select, etc.)\n"
            "2. Make the selection slightly LARGER than the object\n"
            "3. Describe what you're removing in the text field above\n"
            "4. Choose LaMa (fast, simple) or AI Replace (smart, slower)\n"
            "5. Click Remove — result appears as a new layer"))
        info_lbl.set_xalign(0)
        info_exp.add(info_lbl)
        bx.pack_start(info_exp, False, False, 0)

        bx.show_all()
        ai_frame.hide()  # start hidden (LaMa mode)
        _shrink_on_collapse(info_exp, dlg)

        last = _SESSION.get("lama_remove")
        if last:
            if "feather" in last:
                feather_spin.set_value(last["feather"])
            if "mode" in last:
                mode_combo.set_active_id(last["mode"])
                _on_mode_changed(mode_combo)
            if "obj" in last:
                obj_entry.set_text(last["obj"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        feather_px = int(feather_spin.get_value())
        removal_mode = mode_combo.get_active_id()
        obj_desc = obj_entry.get_text().strip()
        # Read AI settings before destroy
        ai_idx = ai_model_combo.get_active()
        ai_den = ai_denoise.get_value()
        pbuf = ai_prompt.get_buffer()
        replacement_prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        _SESSION["lama_remove"] = {"feather": feather_px, "mode": removal_mode, "obj": obj_desc}
        _save_session()
        dlg.destroy()
        try:
            if feather_px > 0:
                try:
                    Gimp.get_pdb().run_procedure("gimp-selection-feather",
                                                  [GObject.Value(Gimp.Image, image),
                                                   GObject.Value(GObject.TYPE_DOUBLE, float(feather_px))])
                except Exception:
                    pass
            _update_spinner_status("Object Removal: building selection mask...")
            mtmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False); mtmp.close()
            _create_selection_mask_png(mtmp.name, image)
            _update_spinner_status("Object Removal: exporting image...")
            tmp = _export_image_to_tmp(image)
            iname = f"gimp_remove_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, iname); os.unlink(tmp)
            mname = f"gimp_remove_mask_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, mtmp.name, mname); os.unlink(mtmp.name)

            if removal_mode == "ai":
                # AI-guided replacement using inpaint pipeline
                preset = dict(MODEL_PRESETS[ai_idx] if 0 <= ai_idx < len(MODEL_PRESETS) else MODEL_PRESETS[0])
                neg = f"{obj_desc}, visible {obj_desc}, trace of {obj_desc}, artifacts, seam" if obj_desc else "artifacts, seam, mismatch"
                wf = _build_inpaint(iname, mname, preset, replacement_prompt, neg,
                                     random.randint(0, 2**32 - 1), denoise=ai_den)
                label_text = "AI Replace"
            else:
                # LaMa fast removal
                wf = _build_lama_remove(iname, mname)
                label_text = "LaMa Remove"

            _update_spinner_status(f"{label_text}: processing on ComfyUI...")
            results = _run_with_spinner(f"{label_text}: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"{label_text}: {obj_desc or 'removed'} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Object Removal Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_lut(self, procedure, run_mode, image, drawables, config, data):
        """Color grading: apply a cinematic LUT to the image."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("LUT: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_lut_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_lut(uname, lut_name, strength)
            _update_spinner_status("LUT: processing on ComfyUI...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        OUTPAINT_PRESETS = {
            "(general extension)": {
                "prompt": "seamless continuation of the existing scene, matching lighting, style, and color palette, natural extension, consistent perspective, same quality and mood",
                "negative": "different style, inconsistent lighting, visible seam, border artifact, blurry, mismatched colors, distorted perspective",
            },
            "Complete person / body": {
                "prompt": "natural continuation of the human body, correct anatomy, matching skin tone and clothing, same pose direction, realistic body proportions, matching lighting on skin",
                "negative": "extra limbs, wrong anatomy, mismatched skin color, different clothing, floating body parts, deformed, cut off",
            },
            "Extend landscape / sky": {
                "prompt": "seamless landscape continuation, matching horizon line, consistent sky, natural terrain, same vegetation style, matching cloud formation, coherent depth of field",
                "negative": "different landscape, sky mismatch, horizon break, inconsistent foliage, visible seam, different season",
            },
            "Complete cut-off object": {
                "prompt": "natural completion of the cut-off object, matching material, same texture and color, correct proportions, physically plausible shape, seamless extension",
                "negative": "wrong shape, different material, inconsistent color, floating parts, impossible geometry, visible seam",
            },
            "Extend interior / room": {
                "prompt": "seamless room extension, matching wall color, consistent floor, same furniture style, correct perspective lines, matching ambient lighting",
                "negative": "different room, wrong perspective, inconsistent decor, floating furniture, visible seam, mismatched lighting",
            },
            "Add more background / bokeh": {
                "prompt": "smooth background extension, matching bokeh and depth of field, consistent blur, same color tones, natural out-of-focus continuation",
                "negative": "sharp background, different blur, focus shift, inconsistent bokeh, visible seam, different color temperature",
            },
            "Widen panorama": {
                "prompt": "panoramic scene extension, wide angle continuation, matching horizon, consistent sky and ground, seamless blend at edges, natural wide-angle perspective",
                "negative": "lens distortion mismatch, different exposure, sky break, visible stitch line, perspective error",
            },
            "Add headroom / space above": {
                "prompt": "natural sky or ceiling continuation above the subject, matching lighting from above, consistent atmosphere, proper vertical perspective",
                "negative": "floating objects, wrong ceiling, sky mismatch, inconsistent overhead lighting, visible seam",
            },
        }
        dlg = PresetDialog("Spellcaster — Outpaint / Extend Canvas", mode="img2img")
        dlg.w_spin.set_value(image.get_width())
        dlg.h_spin.set_value(image.get_height())

        # Outpaint purpose dropdown
        purpose_combo = Gtk.ComboBoxText()
        purpose_combo.set_tooltip_text("What you're extending. Each purpose has an optimized prompt\nfor seamless continuation of that specific content type.")
        for label in OUTPAINT_PRESETS:
            purpose_combo.append(label, label)
        purpose_combo.set_active(0)
        def _on_purpose_changed(combo):
            key = combo.get_active_id()
            if key and key in OUTPAINT_PRESETS:
                p = OUTPAINT_PRESETS[key]
                dlg.prompt_tv.get_buffer().set_text(p["prompt"])
                dlg.neg_tv.get_buffer().set_text(p["negative"])
        purpose_combo.connect("changed", _on_purpose_changed)
        purpose_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        purpose_box.pack_start(Gtk.Label(label="Purpose:"), False, False, 0)
        purpose_box.pack_start(purpose_combo, True, True, 0)
        purpose_box.show_all()
        dlg.get_content_area().pack_start(purpose_box, False, False, 0)
        dlg.get_content_area().reorder_child(purpose_box, 2)  # after model, before prompt

        # Set initial outpaint prompt from purpose preset
        _on_purpose_changed(purpose_combo)
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
        # ControlNet for edge consistency at outpaint borders
        cn_frame = Gtk.Frame(label="ControlNet (edge consistency)")
        cn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        cn_box.set_margin_start(8); cn_box.set_margin_end(8)
        cn_box.set_margin_top(8); cn_box.set_margin_bottom(8)
        cn_box.pack_start(Gtk.Label(label="ControlNet 1 (Canny/Lineart for edge matching):", xalign=0), False, False, 0)
        out_cn_combo = Gtk.ComboBoxText()
        out_cn_combo.set_tooltip_text(
            "ControlNet preserves structure from your source image.\n\n"
            "Modes:\n"
            "  Tile \u2014 preserves layout + adds detail (BEST for upscale/hallucinate)\n"
            "  Canny \u2014 follows edges (good for architecture, objects)\n"
            "  Depth \u2014 preserves 3D depth (good for portraits, scenes)\n"
            "  OpenPose \u2014 follows body pose (portraits, figure work)\n"
            "  Lineart \u2014 follows line drawing (illustration, sketches)\n"
            "  Scribble \u2014 loose sketch guide (creative, abstract)\n\n"
            "Recommended pairings:\n"
            "  Tile + Depth \u2014 structure-aware detail (hallucination)\n"
            "  OpenPose + Canny \u2014 body pose + edge detail (portraits)\n"
            "  Depth + Lineart \u2014 spatial + line structure (scenes)\n\n"
            "\u26a0 SD1.5 and SDXL use DIFFERENT ControlNet models.\n"
            "The correct model is auto-selected based on your checkpoint.")
        for key in CONTROLNET_GUIDE_MODES:
            out_cn_combo.append(key, key)
        out_cn_combo.set_active(0)  # Off by default
        cn_box.pack_start(out_cn_combo, False, False, 0)
        out_cn_str_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        out_cn_str_hb.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        out_cn_strength = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        out_cn_strength.set_digits(2); out_cn_strength.set_value(0.6)
        out_cn_str_hb.pack_start(out_cn_strength, False, False, 0)
        cn_box.pack_start(out_cn_str_hb, False, False, 0)
        cn_frame.add(cn_box)
        cn_frame.show_all()
        dlg.get_content_area().pack_start(cn_frame, False, False, 0)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values()
        _SESSION["outpaint"] = dlg._collect_session()
        _save_session()
        pad_left = int(left_spin.get_value())
        pad_top = int(top_spin.get_value())
        pad_right = int(right_spin.get_value())
        pad_bottom = int(bottom_spin.get_value())
        feathering = int(feather_spin.get_value())
        # ControlNet params
        out_cn1_mode = out_cn_combo.get_active_id() if out_cn_combo else "Off"
        out_cn1 = {"mode": out_cn1_mode, "strength": out_cn_strength.get_value(),
                    "start_percent": 0.0, "end_percent": 1.0} if out_cn1_mode != "Off" else None
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            _update_spinner_status("Outpaint: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_outpaint_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            base_seed = v["seed"]
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                     _build_outpaint(uname, v["preset"], v["prompt"], v["negative"], seed,
                                      pad_left, pad_top, pad_right, pad_bottom, feathering,
                                      v.get("loras"), controlnet=out_cn1)
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
            model_combo.append(str(i), _model_label(p, "style"))
        _fav = _load_config().get("favourite_model", -1)
        if 0 <= _fav < len(MODEL_PRESETS) and model_combo.get_active_id() is None:
            model_combo.set_active_id(str(_fav))
        if model_combo.get_active() < 0:
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
        # ── ControlNet (collapsible) ──────────────────────────────────────
        st_cn_exp = Gtk.Expander(label="\u25b8 ControlNet (2 guides)")
        _shrink_on_collapse(st_cn_exp, dlg)
        st_cn_exp.set_expanded(False)
        st_cn_exp.set_tooltip_text("ControlNet preserves structure during style transfer.\nDepth or Canny recommended to keep spatial layout.")
        st_cn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        st_cn_box.set_margin_start(4); st_cn_box.set_margin_top(4)
        st_cn_box.pack_start(Gtk.Label(label="ControlNet 1 (Depth/Canny preserve structure):", xalign=0), False, False, 0)
        st_cn_combo = Gtk.ComboBoxText()
        st_cn_combo.set_tooltip_text(
            "ControlNet preserves structure from your source image.\n\n"
            "Modes:\n"
            "  Tile \u2014 preserves layout + adds detail (BEST for upscale/hallucinate)\n"
            "  Canny \u2014 follows edges (good for architecture, objects)\n"
            "  Depth \u2014 preserves 3D depth (good for portraits, scenes)\n"
            "  OpenPose \u2014 follows body pose (portraits, figure work)\n"
            "  Lineart \u2014 follows line drawing (illustration, sketches)\n"
            "  Scribble \u2014 loose sketch guide (creative, abstract)\n\n"
            "Recommended pairings:\n"
            "  Tile + Depth \u2014 structure-aware detail (hallucination)\n"
            "  OpenPose + Canny \u2014 body pose + edge detail (portraits)\n"
            "  Depth + Lineart \u2014 spatial + line structure (scenes)\n\n"
            "\u26a0 SD1.5 and SDXL use DIFFERENT ControlNet models.\n"
            "The correct model is auto-selected based on your checkpoint.")
        for key in CONTROLNET_GUIDE_MODES:
            st_cn_combo.append(key, key)
        st_cn_combo.set_active(0)  # Off by default
        st_cn_box.pack_start(st_cn_combo, False, False, 0)
        st_cn_str_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        st_cn_str_hb.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        st_cn_strength = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        st_cn_strength.set_digits(2); st_cn_strength.set_value(0.6)
        st_cn_str_hb.pack_start(st_cn_strength, False, False, 0)
        st_cn_box.pack_start(st_cn_str_hb, False, False, 0)
        # ControlNet 2 (optional)
        st_cn_box.pack_start(Gtk.Label(label="ControlNet 2 (optional):", xalign=0), False, False, 0)
        st_cn_combo_2 = Gtk.ComboBoxText()
        st_cn_combo_2.set_tooltip_text(
            "Optional second ControlNet to combine with the first.\n"
            "Both guides are applied simultaneously \u2014 the AI follows both.\n\n"
            "Best combos:\n"
            "  CN1: Tile + CN2: Depth \u2014 detail + structure\n"
            "  CN1: OpenPose + CN2: Canny \u2014 pose + edges\n"
            "  CN1: Depth + CN2: Lineart \u2014 spatial + line guide\n\n"
            "Keep CN2 strength lower than CN1 (e.g., 0.4 vs 0.7)\n"
            "to let the primary guide dominate.")
        for key in CONTROLNET_GUIDE_MODES:
            st_cn_combo_2.append(key, key)
        st_cn_combo_2.set_active(0)
        st_cn_box.pack_start(st_cn_combo_2, False, False, 0)
        st_cn_str_hb_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        st_cn_str_hb_2.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        st_cn_strength_2 = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        st_cn_strength_2.set_digits(2); st_cn_strength_2.set_value(0.4)
        st_cn_str_hb_2.pack_start(st_cn_strength_2, False, False, 0)
        st_cn_box.pack_start(st_cn_str_hb_2, False, False, 0)
        st_cn_exp.add(st_cn_box)
        bx.pack_start(st_cn_exp, False, False, 0)
        # ── Advanced (collapsible) ───────────────────────────────────────
        st_adv_exp = Gtk.Expander(label="\u25b8 Advanced")
        _shrink_on_collapse(st_adv_exp, dlg)
        st_adv_exp.set_expanded(False)
        st_adv_exp.set_tooltip_text("Style weight, denoise strength, seed, and batch run settings.")
        st_adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        st_adv_box.set_margin_start(4); st_adv_box.set_margin_top(4)
        st_adv_grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        st_adv_grid.attach(Gtk.Label(label="Weight:", xalign=1), 0, 0, 1, 1)
        weight_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        weight_spin.set_value(0.8); weight_spin.set_digits(2)
        weight_spin.set_tooltip_text("How strongly the reference style is applied.\n0.8 = strong style transfer (default). Lower = subtler effect.")
        st_adv_grid.attach(weight_spin, 1, 0, 1, 1)
        st_adv_grid.attach(Gtk.Label(label="Denoise:", xalign=1), 2, 0, 1, 1)
        denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
        denoise_spin.set_value(0.6); denoise_spin.set_digits(2)
        denoise_spin.set_tooltip_text("How much to change the original image.\n0.3 = subtle, 0.6 = balanced (default), 0.9 = heavy restyle.")
        st_adv_grid.attach(denoise_spin, 3, 0, 1, 1)
        st_adv_grid.attach(Gtk.Label(label="Seed:", xalign=1), 0, 1, 1, 1)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        st_adv_grid.attach(seed_spin, 1, 1, 1, 1)
        st_adv_box.pack_start(st_adv_grid, False, False, 0)
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        st_adv_box.pack_start(runs_hb, False, False, 0)
        st_adv_exp.add(st_adv_box)
        bx.pack_start(st_adv_exp, False, False, 0)
        # AutoSet button
        def _style_auto_set():
            idx = model_combo.get_active()
            aid = model_combo.get_active_id()
            if aid and aid.isdigit():
                idx = int(aid)
            arch = MODEL_PRESETS[idx]["arch"] if 0 <= idx < len(MODEL_PRESETS) else "sdxl"
            pos, neg = _AUTOSET_PROMPTS.get(arch, _AUTOSET_PROMPTS["sdxl"])
            prompt_tv.get_buffer().set_text(pos)
            neg_tv.get_buffer().set_text(neg)
            dn = _AUTOSET_DENOISE.get((arch, "style"), 0.60)
            denoise_spin.set_value(dn)
            cn = _AUTOSET_CN.get((arch, "style"))
            if cn:
                cn1k, cn1s, cn2k, cn2s = cn
                if cn1k is not None:
                    st_cn_combo.set_active_id(cn1k)
                if cn1s is not None:
                    st_cn_strength.set_value(cn1s)
                st_cn_combo_2.set_active_id(cn2k)
                st_cn_strength_2.set_value(cn2s)
        _st_auto_btn = Gtk.Button(label="A.")
        _st_auto_btn.set_tooltip_text("AutoSet: optimal config for this model + style transfer")
        _st_auto_btn.set_size_request(32, -1)
        _st_auto_btn.connect("clicked", lambda b: _style_auto_set())
        _st_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _st_top.pack_end(_st_auto_btn, False, False, 0)
        bx.pack_start(_st_top, False, False, 0)
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
            if "cn1_id" in last:
                st_cn_combo.set_active_id(last["cn1_id"])
            if "cn1_str" in last:
                st_cn_strength.set_value(last["cn1_str"])
            if "cn2_id" in last:
                st_cn_combo_2.set_active_id(last["cn2_id"])
            if "cn2_str" in last:
                st_cn_strength_2.set_value(last["cn2_str"])
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
        # ControlNet params
        st_cn1_mode = st_cn_combo.get_active_id() if st_cn_combo else "Off"
        st_cn1 = {"mode": st_cn1_mode, "strength": st_cn_strength.get_value(),
                   "start_percent": 0.0, "end_percent": 1.0} if st_cn1_mode != "Off" else None
        st_cn2_mode = st_cn_combo_2.get_active_id() if st_cn_combo_2 else "Off"
        st_cn2 = {"mode": st_cn2_mode, "strength": st_cn_strength_2.get_value(),
                   "start_percent": 0.0, "end_percent": 1.0} if st_cn2_mode != "Off" else None
        _SESSION["style_transfer"] = {
            "model_idx": idx, "ip_id": ipadapter_preset,
            "prompt": prompt, "negative": negative,
            "weight": weight, "denoise": denoise,
            "cn1_id": st_cn1_mode, "cn1_str": st_cn_strength.get_value(),
            "cn2_id": st_cn2_mode, "cn2_str": st_cn_strength_2.get_value(),
            "runs": runs,
        }
        _save_session()
        dlg.destroy()
        if not style_path:
            Gimp.message("No style reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            _update_spinner_status("Style Transfer: exporting images...")
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
                    controlnet=st_cn1, controlnet_2=st_cn2,
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        cf_spin.set_tooltip_text("Only affects CodeFormer model.\n0.0 = max quality (may alter identity), 1.0 = max fidelity to original. Default: 0.5")
        hb5.pack_start(cf_spin, True, True, 0); bx.pack_start(hb5, False, False, 0)
        # Sharpen composite option
        hb6 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb6.pack_start(Gtk.Label(label="Post-Sharpen:"), False, False, 0)
        sharpen_spin = Gtk.SpinButton.new_with_range(0.0, 2.0, 0.05)
        sharpen_spin.set_value(0.0); sharpen_spin.set_digits(2)
        sharpen_spin.set_tooltip_text("Optional sharpening applied after face restoration.\n0.0 = off (default), 0.3-0.5 = subtle, 1.0+ = aggressive.\nUse 'Restore + Sharpen' for a crisper result.")
        hb6.pack_start(sharpen_spin, True, True, 0); bx.pack_start(hb6, False, False, 0)
        # Before/After comparison mode
        compare_check = Gtk.CheckButton(label="Side-by-side comparison (before | after)")
        compare_check.set_active(False)
        compare_check.set_tooltip_text("When enabled, imports BOTH the original and restored face\nas separate layers so you can compare them in GIMP.")
        bx.pack_start(compare_check, False, False, 0)
        bx.pack_start(Gtk.Label(label="Restores and enhances faces in the image.\nResult is imported as a new layer."), False, False, 4)
        # AutoSet button
        def _fr_auto_set():
            model_combo.set_active(0)  # CodeFormer
            det_combo.set_active(0)    # retinaface_resnet50
            vis_spin.set_value(1.0)
            cf_spin.set_value(0.5)
            sharpen_spin.set_value(0.0)
        _fr_auto_btn = Gtk.Button(label="A.")
        _fr_auto_btn.set_tooltip_text("AutoSet: optimal config for face restoration")
        _fr_auto_btn.set_size_request(32, -1)
        _fr_auto_btn.connect("clicked", lambda b: _fr_auto_set())
        _fr_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _fr_top.pack_end(_fr_auto_btn, False, False, 0)
        bx.pack_start(_fr_top, False, False, 0)
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
            if "sharpen" in last:
                sharpen_spin.set_value(last["sharpen"])
            if "compare" in last:
                compare_check.set_active(last["compare"])
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); _propagate_server_url(srv)
        preset_key = model_combo.get_active_id()
        fr_preset = FACE_RESTORE_PRESETS[preset_key]
        facedetection = det_combo.get_active_id()
        visibility = vis_spin.get_value()
        codeformer_weight = cf_spin.get_value()
        sharpen_amount = sharpen_spin.get_value()
        do_compare = compare_check.get_active()
        _SESSION["face_restore"] = {
            "model_id": preset_key, "det_id": facedetection,
            "visibility": visibility, "codeformer_weight": codeformer_weight,
            "sharpen": sharpen_amount, "compare": do_compare,
        }
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("Face Restore: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_facerestore_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            # If comparison mode, import the original as a "Before" layer first
            if do_compare:
                _import_result_as_layer(image, tmp if os.path.exists(tmp) else _export_image_to_tmp(image),
                                        f"Face Restore BEFORE (original)")
            wf = _build_face_restore(uname, fr_preset["model"], facedetection,
                                      visibility, codeformer_weight)
            # Add sharpening pass if requested
            if sharpen_amount > 0:
                # Find the SaveImage node and insert ImageSharpen before it
                save_key = max(wf.keys(), key=lambda k: int(k))
                sharpen_key = str(int(save_key) + 1)
                new_save_key = str(int(sharpen_key) + 1)
                # Get the input reference from save node
                save_input_ref = wf[save_key]["inputs"]["images"]
                wf[sharpen_key] = {"class_type": "ImageSharpen",
                                   "inputs": {"image": save_input_ref,
                                              "sharpen_radius": 1,
                                              "sigma": 0.5,
                                              "alpha": sharpen_amount}}
                wf[new_save_key] = {"class_type": "SaveImage",
                                    "inputs": {"images": [sharpen_key, 0],
                                               "filename_prefix": "spellcaster_facerestore_sharp"}}
                del wf[save_key]
            _update_spinner_status("Face Restore: processing on ComfyUI...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        # Face detection model dropdown
        hb6 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb6.pack_start(Gtk.Label(label="Face Detection:"), False, False, 0)
        det_combo = Gtk.ComboBoxText()
        det_combo.set_tooltip_text("Face detection model used to locate faces for restoration.\nretinaface_resnet50 is most accurate for varied poses.")
        for det in ["retinaface_resnet50", "retinaface_mobile0.25", "YOLOv5l", "YOLOv5n"]:
            det_combo.append(det, det)
        det_combo.set_active(0)
        det_combo.set_hexpand(True)
        hb6.pack_start(det_combo, True, True, 0); bx.pack_start(hb6, False, False, 0)
        # Sharpen radius control
        hb7 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb7.pack_start(Gtk.Label(label="Sharpen Radius:"), False, False, 0)
        sharpen_radius_spin = Gtk.SpinButton.new_with_range(1, 5, 1)
        sharpen_radius_spin.set_value(1)
        sharpen_radius_spin.set_tooltip_text("Kernel radius for the sharpening pass.\n1 = fine detail (default), 3 = medium, 5 = coarse structure.\nHigher radius sharpens larger features.")
        hb7.pack_start(sharpen_radius_spin, True, True, 0); bx.pack_start(hb7, False, False, 0)
        bx.pack_start(Gtk.Label(label="Full restoration pipeline for old/damaged photos.\nUpscale \u2192 Face Restore \u2192 Sharpen."), False, False, 4)
        # AutoSet button
        def _pr_auto_set():
            up_combo.set_active(0)
            face_combo.set_active(0)    # CodeFormer
            det_combo.set_active(0)     # retinaface_resnet50
            sharpen_spin.set_value(0.5)
            cf_spin.set_value(0.5)
            sharpen_radius_spin.set_value(1)
        _pr_auto_btn = Gtk.Button(label="A.")
        _pr_auto_btn.set_tooltip_text("AutoSet: optimal config for photo restoration")
        _pr_auto_btn.set_size_request(32, -1)
        _pr_auto_btn.connect("clicked", lambda b: _pr_auto_set())
        _pr_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _pr_top.pack_end(_pr_auto_btn, False, False, 0)
        bx.pack_start(_pr_top, False, False, 0)
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
            if "det_id" in last:
                det_combo.set_active_id(last["det_id"])
            if "sharpen_radius" in last:
                sharpen_radius_spin.set_value(last["sharpen_radius"])
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
        facedetection = det_combo.get_active_id()
        sharpen_radius = int(sharpen_radius_spin.get_value())
        _SESSION["photo_restore"] = {
            "up_id": up_key, "face_id": face_key,
            "sharpen": sharpen_amount, "codeformer_weight": codeformer_weight,
            "det_id": facedetection, "sharpen_radius": sharpen_radius,
        }
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("Photo Restore: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_photorestore_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_photo_restore(uname, upscale_model, fr_preset["model"],
                                       facedetection, 1.0, codeformer_weight,
                                       sharpen_radius, 0.5, sharpen_amount)
            results = _run_with_spinner("Photo Restore: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        detail_combo.set_tooltip_text("What kind of detail to hallucinate.\nGeneric: Subtle/Moderate/Strong by intensity.\nSpecific: Skin Texture, Eyes, Hair, Fabric, Landscape, Architecture, Sharpen, Food, Metal.")
        for label in HALLUCINATE_PRESETS:
            detail_combo.append(label, label)
        detail_combo.set_active(1)  # default to "Moderate"
        detail_combo.set_hexpand(True)
        def _on_detail_changed(combo):
            key = combo.get_active_id()
            if key and key in HALLUCINATE_PRESETS:
                hp = HALLUCINATE_PRESETS[key]
                if hp.get("prompt"):
                    prompt_tv.get_buffer().set_text(hp["prompt"])
                if hp.get("negative"):
                    neg_tv.get_buffer().set_text(hp["negative"])
        detail_combo.connect("changed", _on_detail_changed)
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
        # Upscale factor
        hb_sf = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_sf.pack_start(Gtk.Label(label="Scale factor:"), False, False, 0)
        up_factor_sp = Gtk.SpinButton.new_with_range(1.0, 8.0, 0.5)
        up_factor_sp.set_value(1.0); up_factor_sp.set_digits(1)
        up_factor_sp.set_tooltip_text("Output upscale factor.\n"
                                       "1.5x = 50% larger (fast, recommended)\n"
                                       "2.0x = double size\n"
                                       "4.0x = full 4x (slow, may timeout on large images)")
        hb_sf.pack_start(up_factor_sp, False, False, 0); bx.pack_start(hb_sf, False, False, 0)
        # Checkpoint model dropdown
        bx.pack_start(Gtk.Label(label="Checkpoint Model:", xalign=0), False, False, 0)
        model_combo = Gtk.ComboBoxText()
        model_combo.set_tooltip_text("AI model used for the detail hallucination (img2img) pass.\nMatch this to your image style (photo, anime, etc).")
        for i, p in enumerate(MODEL_PRESETS):
            model_combo.append(str(i), _model_label(p, "hallucinate"))
        _fav = _load_config().get("favourite_model", -1)
        if 0 <= _fav < len(MODEL_PRESETS) and model_combo.get_active_id() is None:
            model_combo.set_active_id(str(_fav))
        if model_combo.get_active() < 0:
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
        # ── ControlNet (collapsible) ──────────────────────────────────────
        hall_cn_exp = Gtk.Expander(label="\u25b8 ControlNet (2 guides)")
        _shrink_on_collapse(hall_cn_exp, dlg)
        hall_cn_exp.set_expanded(False)
        hall_cn_exp.set_tooltip_text("ControlNet preserves structure from your source image.\nTile is recommended for detail hallucination.")
        hall_cn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hall_cn_box.set_margin_start(4); hall_cn_box.set_margin_top(4)
        hall_cn_box.pack_start(Gtk.Label(label="ControlNet 1 (Tile recommended):", xalign=0), False, False, 0)
        cn_combo = Gtk.ComboBoxText()
        cn_combo.set_tooltip_text(
            "ControlNet preserves structure from your source image.\n\n"
            "Modes:\n"
            "  Tile \u2014 preserves layout + adds detail (BEST for upscale/hallucinate)\n"
            "  Canny \u2014 follows edges (good for architecture, objects)\n"
            "  Depth \u2014 preserves 3D depth (good for portraits, scenes)\n"
            "  OpenPose \u2014 follows body pose (portraits, figure work)\n"
            "  Lineart \u2014 follows line drawing (illustration, sketches)\n"
            "  Scribble \u2014 loose sketch guide (creative, abstract)\n\n"
            "Recommended pairings:\n"
            "  Tile + Depth \u2014 structure-aware detail (hallucination)\n"
            "  OpenPose + Canny \u2014 body pose + edge detail (portraits)\n"
            "  Depth + Lineart \u2014 spatial + line structure (scenes)\n\n"
            "\u26a0 SD1.5 and SDXL use DIFFERENT ControlNet models.\n"
            "The correct model is auto-selected based on your checkpoint.")
        for key in CONTROLNET_GUIDE_MODES:
            cn_combo.append(key, key)
        cn_combo.set_active_id("Tile (detail upscale) — SD1.5 + SDXL (dedicated models)")
        if cn_combo.get_active() < 0:
            cn_combo.set_active(0)
        hall_cn_box.pack_start(cn_combo, False, False, 0)
        cn_str_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cn_str_hb.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        cn_strength = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        cn_strength.set_digits(2); cn_strength.set_value(0.7)
        cn_str_hb.pack_start(cn_strength, False, False, 0)
        hall_cn_box.pack_start(cn_str_hb, False, False, 0)
        # ControlNet 2 (optional)
        hall_cn_box.pack_start(Gtk.Label(label="ControlNet 2 (optional):", xalign=0), False, False, 0)
        cn_combo_2 = Gtk.ComboBoxText()
        cn_combo_2.set_tooltip_text(
            "Optional second ControlNet to combine with the first.\n"
            "Both guides are applied simultaneously \u2014 the AI follows both.\n\n"
            "Best combos:\n"
            "  CN1: Tile + CN2: Depth \u2014 detail + structure\n"
            "  CN1: OpenPose + CN2: Canny \u2014 pose + edges\n"
            "  CN1: Depth + CN2: Lineart \u2014 spatial + line guide\n\n"
            "Keep CN2 strength lower than CN1 (e.g., 0.4 vs 0.7)\n"
            "to let the primary guide dominate.")
        for key in CONTROLNET_GUIDE_MODES:
            cn_combo_2.append(key, key)
        cn_combo_2.set_active(0)
        hall_cn_box.pack_start(cn_combo_2, False, False, 0)
        cn_str_hb_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cn_str_hb_2.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        cn_strength_2 = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        cn_strength_2.set_digits(2); cn_strength_2.set_value(0.5)
        cn_str_hb_2.pack_start(cn_strength_2, False, False, 0)
        hall_cn_box.pack_start(cn_str_hb_2, False, False, 0)
        hall_cn_exp.add(hall_cn_box)
        bx.pack_start(hall_cn_exp, False, False, 0)
        # ── Advanced (collapsible) ───────────────────────────────────────
        hall_adv_exp = Gtk.Expander(label="\u25b8 Advanced")
        _shrink_on_collapse(hall_adv_exp, dlg)
        hall_adv_exp.set_expanded(False)
        hall_adv_exp.set_tooltip_text("Seed and batch run settings.")
        hall_adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hall_adv_box.set_margin_start(4); hall_adv_box.set_margin_top(4)
        hb_seed = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_seed.pack_start(Gtk.Label(label="Seed:"), False, False, 0)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        hb_seed.pack_start(seed_spin, True, True, 0); hall_adv_box.pack_start(hb_seed, False, False, 0)
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1); runs_spin.set_value(1)
        runs_hb.pack_start(runs_spin, False, False, 0)
        hall_adv_box.pack_start(runs_hb, False, False, 0)
        hall_adv_exp.add(hall_adv_box)
        bx.pack_start(hall_adv_exp, False, False, 0)
        # AutoSet button
        def _hall_auto_set():
            idx = model_combo.get_active()
            aid = model_combo.get_active_id()
            if aid and aid.isdigit():
                idx = int(aid)
            arch = MODEL_PRESETS[idx]["arch"] if 0 <= idx < len(MODEL_PRESETS) else "sdxl"
            pos, neg = _AUTOSET_PROMPTS.get(arch, _AUTOSET_PROMPTS["sdxl"])
            prompt_tv.get_buffer().set_text(pos)
            neg_tv.get_buffer().set_text(neg)
            cn = _AUTOSET_CN.get((arch, "hallucinate"))
            if cn:
                cn1k, cn1s, cn2k, cn2s = cn
                if cn1k is not None:
                    cn_combo.set_active_id(cn1k)
                if cn1s is not None:
                    cn_strength.set_value(cn1s)
                cn_combo_2.set_active_id(cn2k)
                cn_strength_2.set_value(cn2s)
        _hall_auto_btn = Gtk.Button(label="A.")
        _hall_auto_btn.set_tooltip_text("AutoSet: optimal config for this model + detail hallucination")
        _hall_auto_btn.set_size_request(32, -1)
        _hall_auto_btn.connect("clicked", lambda b: _hall_auto_set())
        _hall_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _hall_top.pack_end(_hall_auto_btn, False, False, 0)
        bx.pack_start(_hall_top, False, False, 0)
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
        # ControlNet params (read BEFORE dlg.destroy)
        cn1_mode = cn_combo.get_active_id() if cn_combo else "Off"
        cn1 = {"mode": cn1_mode, "strength": cn_strength.get_value(),
                "start_percent": 0.0, "end_percent": 1.0} if cn1_mode != "Off" else None
        cn2_mode = cn_combo_2.get_active_id() if cn_combo_2 else "Off"
        cn2 = {"mode": cn2_mode, "strength": cn_strength_2.get_value(),
                "start_percent": 0.0, "end_percent": 1.0} if cn2_mode != "Off" else None
        upscale_factor = up_factor_sp.get_value()
        _SESSION["detail_hallucinate"] = {
            "detail_id": detail_key, "up_id": up_key, "model_idx": idx,
            "prompt": prompt, "negative": negative,
            "runs": runs, "scale": upscale_factor,
        }
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("Detail Hallucinate: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_hallucinate_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_detail_hallucinate(uname, upscale_model, preset, prompt, negative,
                                                seed, h_preset["denoise"], h_preset["cfg"],
                                                steps=h_preset.get("steps"),
                                                upscale_factor=upscale_factor,
                                                controlnet=cn1, controlnet_2=cn2)
                label = f"Detail Hallucinate run {run_i+1}/{runs}" if runs > 1 else "Detail Hallucinate"
                _wf = wf
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, _wf, timeout=600)))
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
            model_combo.append(str(i), _model_label(p, "hallucinate"))
        _fav = _load_config().get("favourite_model", -1)
        if 0 <= _fav < len(MODEL_PRESETS) and model_combo.get_active_id() is None:
            model_combo.set_active_id(str(_fav))
        if model_combo.get_active() < 0:
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
        # Prompt and Negative (created here, packed into Advanced expander below)
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 60)
        prompt_tv.set_tooltip_text("Describe the detail style to hallucinate.\nAuto-filled by hallucination level. Customize for specific content.")
        prompt_tv.get_buffer().set_text(SEEDV2R_PRESETS[2]["prompt"])
        neg_tv = Gtk.TextView(); neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        neg_tv.set_size_request(-1, 40)
        neg_tv.set_tooltip_text("Describe what you do NOT want (e.g. 'blurry, soft').")
        neg_tv.get_buffer().set_text(SEEDV2R_PRESETS[2]["negative"])

        # Update prompt/negative when hallucination level changes
        def _on_hall_changed(combo):
            idx = combo.get_active()
            if 0 <= idx < len(SEEDV2R_PRESETS):
                prompt_tv.get_buffer().set_text(SEEDV2R_PRESETS[idx]["prompt"])
                neg_tv.get_buffer().set_text(SEEDV2R_PRESETS[idx]["negative"])
        hall_combo.connect("changed", _on_hall_changed)

        # ── ControlNet (collapsible) ──────────────────────────────────────
        sv2r_cn_exp = Gtk.Expander(label="\u25b8 ControlNet (2 guides)")
        _shrink_on_collapse(sv2r_cn_exp, dlg)
        sv2r_cn_exp.set_expanded(False)
        sv2r_cn_exp.set_tooltip_text("ControlNet preserves structure from your source image.\nTile is recommended for SeedV2R upscaling.")
        sv2r_cn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sv2r_cn_box.set_margin_start(4); sv2r_cn_box.set_margin_top(4)
        sv2r_cn_box.pack_start(Gtk.Label(label="ControlNet 1 (Tile recommended):", xalign=0), False, False, 0)
        sv2r_cn_combo = Gtk.ComboBoxText()
        sv2r_cn_combo.set_tooltip_text(
            "ControlNet preserves structure from your source image.\n\n"
            "Modes:\n"
            "  Tile \u2014 preserves layout + adds detail (BEST for upscale/hallucinate)\n"
            "  Canny \u2014 follows edges (good for architecture, objects)\n"
            "  Depth \u2014 preserves 3D depth (good for portraits, scenes)\n"
            "  OpenPose \u2014 follows body pose (portraits, figure work)\n"
            "  Lineart \u2014 follows line drawing (illustration, sketches)\n"
            "  Scribble \u2014 loose sketch guide (creative, abstract)\n\n"
            "Recommended pairings:\n"
            "  Tile + Depth \u2014 structure-aware detail (hallucination)\n"
            "  OpenPose + Canny \u2014 body pose + edge detail (portraits)\n"
            "  Depth + Lineart \u2014 spatial + line structure (scenes)\n\n"
            "\u26a0 SD1.5 and SDXL use DIFFERENT ControlNet models.\n"
            "The correct model is auto-selected based on your checkpoint.")
        for key in CONTROLNET_GUIDE_MODES:
            sv2r_cn_combo.append(key, key)
        sv2r_cn_combo.set_active(0)  # Off by default
        sv2r_cn_box.pack_start(sv2r_cn_combo, False, False, 0)
        sv2r_cn_str_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sv2r_cn_str_hb.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        sv2r_cn_strength = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        sv2r_cn_strength.set_digits(2); sv2r_cn_strength.set_value(0.7)
        sv2r_cn_str_hb.pack_start(sv2r_cn_strength, False, False, 0)
        sv2r_cn_box.pack_start(sv2r_cn_str_hb, False, False, 0)
        # ControlNet 2 (optional)
        sv2r_cn_box.pack_start(Gtk.Label(label="ControlNet 2 (optional):", xalign=0), False, False, 0)
        sv2r_cn_combo_2 = Gtk.ComboBoxText()
        sv2r_cn_combo_2.set_tooltip_text(
            "Optional second ControlNet to combine with the first.\n"
            "Both guides are applied simultaneously \u2014 the AI follows both.\n\n"
            "Best combos:\n"
            "  CN1: Tile + CN2: Depth \u2014 detail + structure\n"
            "  CN1: OpenPose + CN2: Canny \u2014 pose + edges\n"
            "  CN1: Depth + CN2: Lineart \u2014 spatial + line guide\n\n"
            "Keep CN2 strength lower than CN1 (e.g., 0.4 vs 0.7)\n"
            "to let the primary guide dominate.")
        for key in CONTROLNET_GUIDE_MODES:
            sv2r_cn_combo_2.append(key, key)
        sv2r_cn_combo_2.set_active(0)
        sv2r_cn_box.pack_start(sv2r_cn_combo_2, False, False, 0)
        sv2r_cn_str_hb_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sv2r_cn_str_hb_2.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        sv2r_cn_strength_2 = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        sv2r_cn_strength_2.set_digits(2); sv2r_cn_strength_2.set_value(0.5)
        sv2r_cn_str_hb_2.pack_start(sv2r_cn_strength_2, False, False, 0)
        sv2r_cn_box.pack_start(sv2r_cn_str_hb_2, False, False, 0)
        sv2r_cn_exp.add(sv2r_cn_box)
        bx.pack_start(sv2r_cn_exp, False, False, 0)
        # ── Advanced (collapsible) ───────────────────────────────────────
        sv2r_adv_exp = Gtk.Expander(label="\u25b8 Advanced")
        _shrink_on_collapse(sv2r_adv_exp, dlg)
        sv2r_adv_exp.set_expanded(False)
        sv2r_adv_exp.set_tooltip_text("Prompt, negative prompt, seed, and batch run settings.")
        sv2r_adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sv2r_adv_box.set_margin_start(4); sv2r_adv_box.set_margin_top(4)
        sv2r_adv_box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(60)
        sv2r_adv_box.pack_start(sw, False, False, 0)
        sv2r_adv_box.pack_start(Gtk.Label(label="Negative:", xalign=0), False, False, 0)
        sw2 = Gtk.ScrolledWindow(); sw2.add(neg_tv); sw2.set_min_content_height(40)
        sv2r_adv_box.pack_start(sw2, False, False, 0)
        hb_seed = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_seed.pack_start(Gtk.Label(label="Seed:"), False, False, 0)
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        hb_seed.pack_start(seed_spin, True, True, 0); sv2r_adv_box.pack_start(hb_seed, False, False, 0)
        # Runs spinner
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        sv2r_adv_box.pack_start(runs_hb, False, False, 0)
        sv2r_adv_exp.add(sv2r_adv_box)
        bx.pack_start(sv2r_adv_exp, False, False, 0)
        # AutoSet button
        def _sv2r_auto_set():
            idx = model_combo.get_active()
            aid = model_combo.get_active_id()
            if aid and aid.isdigit():
                idx = int(aid)
            arch = MODEL_PRESETS[idx]["arch"] if 0 <= idx < len(MODEL_PRESETS) else "sdxl"
            pos, neg = _AUTOSET_PROMPTS.get(arch, _AUTOSET_PROMPTS["sdxl"])
            prompt_tv.get_buffer().set_text(pos)
            neg_tv.get_buffer().set_text(neg)
            cn = _AUTOSET_CN.get((arch, "seedv2r"))
            if cn:
                cn1k, cn1s, cn2k, cn2s = cn
                if cn1k is not None:
                    sv2r_cn_combo.set_active_id(cn1k)
                if cn1s is not None:
                    sv2r_cn_strength.set_value(cn1s)
                sv2r_cn_combo_2.set_active_id(cn2k)
                sv2r_cn_strength_2.set_value(cn2s)
        _sv2r_auto_btn = Gtk.Button(label="A.")
        _sv2r_auto_btn.set_tooltip_text("AutoSet: optimal config for this model + SeedV2R upscale")
        _sv2r_auto_btn.set_size_request(32, -1)
        _sv2r_auto_btn.connect("clicked", lambda b: _sv2r_auto_set())
        _sv2r_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _sv2r_top.pack_end(_sv2r_auto_btn, False, False, 0)
        bx.pack_start(_sv2r_top, False, False, 0)
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
            if "cn1_id" in last:
                sv2r_cn_combo.set_active_id(last["cn1_id"])
            if "cn1_str" in last:
                sv2r_cn_strength.set_value(last["cn1_str"])
            if "cn2_id" in last:
                sv2r_cn_combo_2.set_active_id(last["cn2_id"])
            if "cn2_str" in last:
                sv2r_cn_strength_2.set_value(last["cn2_str"])
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
        # ControlNet params
        sv2r_cn1_mode = sv2r_cn_combo.get_active_id() if sv2r_cn_combo else "Off"
        sv2r_cn1 = {"mode": sv2r_cn1_mode, "strength": sv2r_cn_strength.get_value(),
                     "start_percent": 0.0, "end_percent": 1.0} if sv2r_cn1_mode != "Off" else None
        sv2r_cn2_mode = sv2r_cn_combo_2.get_active_id() if sv2r_cn_combo_2 else "Off"
        sv2r_cn2 = {"mode": sv2r_cn2_mode, "strength": sv2r_cn_strength_2.get_value(),
                     "start_percent": 0.0, "end_percent": 1.0} if sv2r_cn2_mode != "Off" else None
        _SESSION["seedv2r"] = {
            "model_idx": idx, "up_id": up_key, "scale_idx": scale_idx,
            "hall_idx": hall_idx, "prompt": prompt, "negative": negative,
            "cn1_id": sv2r_cn1_mode, "cn1_str": sv2r_cn_strength.get_value(),
            "cn2_id": sv2r_cn2_mode, "cn2_str": sv2r_cn_strength_2.get_value(),
            "runs": runs,
        }
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("SeedV2R: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_seedv2r_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            orig_w = image.get_width()
            orig_h = image.get_height()
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_seedv2r(uname, upscale_model, preset, prompt, negative,
                                     seed, hall_preset["denoise"], hall_preset["cfg"],
                                     hall_preset["steps"], scale_factor, orig_w, orig_h,
                                     controlnet=sv2r_cn1, controlnet_2=sv2r_cn2)
                label = f"SeedV2R run {run_i+1}/{runs}" if runs > 1 else "SeedV2R"
                _wf = wf
                results = _run_with_spinner(f"{label}: processing on ComfyUI...",
                                            lambda: list(_run_comfyui_workflow(srv, _wf, timeout=600)))
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
            model_combo.append(str(i), _model_label(p, "seedv2r"))
        _fav = _load_config().get("favourite_model", -1)
        if 0 <= _fav < len(MODEL_PRESETS) and model_combo.get_active_id() is None:
            model_combo.set_active_id(str(_fav))
        if model_combo.get_active() < 0:
            model_combo.set_active(0)
        bx.pack_start(model_combo, False, False, 0)
        # Colorization style preset
        bx.pack_start(Gtk.Label(label="Colorization Style:", xalign=0), False, False, 0)
        color_preset_combo = Gtk.ComboBoxText()
        color_preset_combo.set_tooltip_text("Pre-tuned colorization styles. Each sets optimal prompt, denoise,\nCN strength, and cfg. Select a style, then customize if needed.")
        for label in COLORIZE_PRESETS:
            color_preset_combo.append(label, label)
        color_preset_combo.set_active(0)  # Natural Photograph
        def _on_color_preset_changed(combo):
            key = combo.get_active_id()
            if key and key in COLORIZE_PRESETS:
                cp = COLORIZE_PRESETS[key]
                prompt_tv.get_buffer().set_text(cp["prompt"])
                neg_tv.get_buffer().set_text(cp.get("negative", "black and white, monochrome, grey, desaturated"))
                denoise_spin.set_value(cp["denoise"])
                cn_spin.set_value(cp["cn_strength"])
        bx.pack_start(color_preset_combo, False, False, 0)
        # Parameters (must be created BEFORE connecting preset combo changed signal)
        # CN Strength and Denoise/Seed are created here but packed into expanders below
        cn_spin = Gtk.SpinButton.new_with_range(0.3, 1.0, 0.05)
        cn_spin.set_value(0.85); cn_spin.set_digits(2)
        cn_spin.set_tooltip_text("How strictly to preserve line structure from the original.\n0.85 = default. Higher = more faithful to B&W shapes, lower = more creative.")
        denoise_spin = Gtk.SpinButton.new_with_range(0.4, 0.85, 0.05)
        denoise_spin.set_value(0.72); denoise_spin.set_digits(2)
        denoise_spin.set_tooltip_text("How vivid the colors will be.\n0.50 = subtle tinting, 0.72 = natural (default), 0.85 = very vivid.")
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
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
        # ── ControlNet (collapsible) ──────────────────────────────────────
        col_cn_exp = Gtk.Expander(label="\u25b8 ControlNet")
        _shrink_on_collapse(col_cn_exp, dlg)
        col_cn_exp.set_expanded(False)
        col_cn_exp.set_tooltip_text("Lineart CN strength and optional second ControlNet for spatial guidance.")
        col_cn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        col_cn_box.set_margin_start(4); col_cn_box.set_margin_top(4)
        col_cn_str_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        col_cn_str_hb.pack_start(Gtk.Label(label="Lineart CN Strength:"), False, False, 0)
        col_cn_str_hb.pack_start(cn_spin, False, False, 0)
        col_cn_box.pack_start(col_cn_str_hb, False, False, 0)
        col_cn_box.pack_start(Gtk.Label(label="ControlNet 2 (optional -- Depth/Pose for structure):", xalign=0), False, False, 0)
        col_cn2_combo = Gtk.ComboBoxText()
        col_cn2_combo.set_tooltip_text(
            "Optional second ControlNet to combine with the first.\n"
            "Both guides are applied simultaneously \u2014 the AI follows both.\n\n"
            "Best combos:\n"
            "  CN1: Tile + CN2: Depth \u2014 detail + structure\n"
            "  CN1: OpenPose + CN2: Canny \u2014 pose + edges\n"
            "  CN1: Depth + CN2: Lineart \u2014 spatial + line guide\n\n"
            "Keep CN2 strength lower than CN1 (e.g., 0.4 vs 0.7)\n"
            "to let the primary guide dominate.")
        for key in CONTROLNET_GUIDE_MODES:
            col_cn2_combo.append(key, key)
        col_cn2_combo.set_active(0)  # Off by default
        col_cn_box.pack_start(col_cn2_combo, False, False, 0)
        col_cn2_str_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        col_cn2_str_hb.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        col_cn2_strength = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        col_cn2_strength.set_digits(2); col_cn2_strength.set_value(0.5)
        col_cn2_str_hb.pack_start(col_cn2_strength, False, False, 0)
        col_cn_box.pack_start(col_cn2_str_hb, False, False, 0)
        col_cn_exp.add(col_cn_box)
        bx.pack_start(col_cn_exp, False, False, 0)
        # ── Advanced (collapsible) ───────────────────────────────────────
        col_adv_exp = Gtk.Expander(label="\u25b8 Advanced")
        _shrink_on_collapse(col_adv_exp, dlg)
        col_adv_exp.set_expanded(False)
        col_adv_exp.set_tooltip_text("Color intensity (denoise), seed, and batch run settings.")
        col_adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        col_adv_box.set_margin_start(4); col_adv_box.set_margin_top(4)
        col_dn_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        col_dn_hb.pack_start(Gtk.Label(label="Color Intensity:"), False, False, 0)
        col_dn_hb.pack_start(denoise_spin, False, False, 0)
        col_adv_box.pack_start(col_dn_hb, False, False, 0)
        col_seed_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        col_seed_hb.pack_start(Gtk.Label(label="Seed:"), False, False, 0)
        col_seed_hb.pack_start(seed_spin, False, False, 0)
        col_adv_box.pack_start(col_seed_hb, False, False, 0)
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        col_adv_box.pack_start(runs_hb, False, False, 0)
        col_adv_exp.add(col_adv_box)
        bx.pack_start(col_adv_exp, False, False, 0)
        # AutoSet button
        def _col_auto_set():
            idx = model_combo.get_active()
            aid = model_combo.get_active_id()
            if aid and aid.isdigit():
                idx = int(aid)
            arch = MODEL_PRESETS[idx]["arch"] if 0 <= idx < len(MODEL_PRESETS) else "sdxl"
            pos, neg = _AUTOSET_PROMPTS.get(arch, _AUTOSET_PROMPTS["sdxl"])
            prompt_tv.get_buffer().set_text("vivid natural colors, " + pos)
            neg_tv.get_buffer().set_text("black and white, grayscale, monochrome, desaturated, " + neg)
            dn = _AUTOSET_DENOISE.get((arch, "colorize"), 0.72)
            denoise_spin.set_value(dn)
            cn = _AUTOSET_CN.get((arch, "colorize"))
            if cn:
                _cn1k, _cn1s, cn2k, cn2s = cn
                col_cn2_combo.set_active_id(cn2k)
                col_cn2_strength.set_value(cn2s)
        _col_auto_btn = Gtk.Button(label="A.")
        _col_auto_btn.set_tooltip_text("AutoSet: optimal config for this model + colorization")
        _col_auto_btn.set_size_request(32, -1)
        _col_auto_btn.connect("clicked", lambda b: _col_auto_set())
        _col_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _col_top.pack_end(_col_auto_btn, False, False, 0)
        bx.pack_start(_col_top, False, False, 0)
        # Connect preset combo AFTER all widgets exist
        color_preset_combo.connect("changed", _on_color_preset_changed)
        _on_color_preset_changed(color_preset_combo)  # fill defaults
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
            if "cn2_id" in last:
                col_cn2_combo.set_active_id(last["cn2_id"])
            if "cn2_str" in last:
                col_cn2_strength.set_value(last["cn2_str"])
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
        # ControlNet 2 params
        col_cn2_mode = col_cn2_combo.get_active_id() if col_cn2_combo else "Off"
        col_cn2 = {"mode": col_cn2_mode, "strength": col_cn2_strength.get_value(),
                    "start_percent": 0.0, "end_percent": 1.0} if col_cn2_mode != "Off" else None
        # Color preset params (read BEFORE dlg.destroy)
        _cp_key = color_preset_combo.get_active_id() if color_preset_combo else None
        _cp = COLORIZE_PRESETS.get(_cp_key, {}) if _cp_key else {}
        _SESSION["colorize"] = {
            "model_idx": idx, "cn_strength": cn_strength, "denoise": denoise,
            "prompt": prompt, "negative": negative,
            "cn2_id": col_cn2_mode, "cn2_str": col_cn2_strength.get_value(),
            "runs": runs,
        }
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("Colorize: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_colorize_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_colorize(uname, preset, prompt, negative, seed,
                                      cn_strength, denoise,
                                      steps=_cp.get("steps"),
                                      cfg=_cp.get("cfg"),
                                      controlnet_2=col_cn2)
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
        _save_session()
        batch_count = int(batch_spin.get_value())
        dlg.destroy()
        runs = v.get("runs", 1)
        try:
            srv = v["server"]
            _update_spinner_status("Batch Variations: generating on ComfyUI...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
                model_combo.append(str(i), _model_label(p, "iclight"))
                sd15_indices.append(i)
        if not sd15_indices:
            # Fallback: show all
            for i, p in enumerate(MODEL_PRESETS):
                model_combo.append(str(i), _model_label(p, "iclight"))
        _fav = _load_config().get("favourite_model", -1)
        if 0 <= _fav < len(MODEL_PRESETS) and model_combo.get_active_id() is None:
            model_combo.set_active_id(str(_fav))
        if model_combo.get_active() < 0:
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
        # AutoSet button
        def _icl_auto_set():
            steps_spin.set_value(20)
            mult_spin.set_value(0.18)
        _icl_auto_btn = Gtk.Button(label="A.")
        _icl_auto_btn.set_tooltip_text("AutoSet: optimal config for IC-Light relighting")
        _icl_auto_btn.set_size_request(32, -1)
        _icl_auto_btn.connect("clicked", lambda b: _icl_auto_set())
        _icl_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _icl_top.pack_end(_icl_auto_btn, False, False, 0)
        bx.pack_start(_icl_top, False, False, 0)
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
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("IC-Light: exporting image...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        _apply_spellcaster_theme()
        dlg = Gtk.Dialog(title="Spellcaster — SUPIR AI Restoration")
        dlg.set_default_size(600, -1)
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Restore", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        _style_dialog_buttons(dlg)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        # Branded header
        header = _make_branded_header()
        if header:
            bx.pack_start(header, False, False, 4)
            bx.pack_start(Gtk.Separator(), False, False, 2)
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
                model_combo.append(str(i), _model_label(p, "supir"))
        _fav = _load_config().get("favourite_model", -1)
        if 0 <= _fav < len(MODEL_PRESETS) and model_combo.get_active_id() is None:
            model_combo.set_active_id(str(_fav))
        if model_combo.get_active() < 0:
            model_combo.set_active(0)
        bx.pack_start(model_combo, False, False, 0)
        # Restoration task presets
        SUPIR_TASK_PRESETS = {
            "(general restoration)": {
                "prompt": "high quality, detailed, sharp focus, professional photograph, natural colors, clean, well-lit",
                "denoise": 0.30, "steps": 45,
            },
            "Portrait / Face restore": {
                "prompt": "high quality portrait, detailed facial features, sharp eyes, natural skin texture, "
                          "clear skin pores, realistic skin tone, professional portrait photography, well-lit face",
                "denoise": 0.28, "steps": 45,
            },
            "Landscape / Nature": {
                "prompt": "high resolution landscape, sharp foliage, detailed terrain, crisp horizon, "
                          "natural colors, vivid sky, professional nature photography, 8k detail",
                "denoise": 0.35, "steps": 50,
            },
            "Old / Damaged photo repair": {
                "prompt": "restored vintage photograph, clean image, removed scratches, no damage, no grain, "
                          "sharp focus, natural colors, professional photo restoration, archival quality",
                "denoise": 0.45, "steps": 60,
            },
            "JPEG artifact removal": {
                "prompt": "clean image, no compression artifacts, no blocking, smooth gradients, "
                          "sharp edges, high quality, lossless quality, pristine detail",
                "denoise": 0.25, "steps": 35,
            },
            "Low-light / Noisy photo": {
                "prompt": "clean photo, no noise, no grain, sharp detail, well-exposed, clear image, "
                          "professional low-light photography, noise-free, smooth shadows",
                "denoise": 0.38, "steps": 50,
            },
            "Architecture / Interior": {
                "prompt": "sharp architectural photo, straight lines, detailed surfaces, "
                          "clean brick texture, precise geometry, professional real estate photography",
                "denoise": 0.30, "steps": 45,
            },
            "Product / Commercial": {
                "prompt": "product photography, sharp detail, clean background, studio lighting, "
                          "professional commercial shot, crisp reflections, accurate colors",
                "denoise": 0.28, "steps": 45,
            },
            "Text / Document enhance": {
                "prompt": "sharp text, readable letters, clean document, high contrast, "
                          "crisp font edges, legible text, scanned document enhancement",
                "denoise": 0.20, "steps": 30,
            },
            "Anime / Illustration restore": {
                "prompt": "clean anime illustration, sharp lineart, vivid colors, "
                          "smooth color fills, crisp edges, high quality anime artwork, no artifacts",
                "denoise": 0.30, "steps": 45,
            },
        }

        bx.pack_start(Gtk.Label(label="Restoration Task:", xalign=0), False, False, 0)
        task_combo = Gtk.ComboBoxText()
        task_combo.set_tooltip_text("Select the type of image being restored.\nEach task has an optimized prompt, denoise, and step count.")
        for label in SUPIR_TASK_PRESETS:
            task_combo.append(label, label)
        task_combo.set_active(0)
        bx.pack_start(task_combo, False, False, 0)

        # Quality preset dropdown
        SUPIR_QUALITY_PRESETS = [
            ("Fast Preview (20 steps)", 20, 0.25),
            ("Standard (45 steps)", 45, 0.30),
            ("Maximum Detail (70 steps)", 70, 0.35),
            ("Ultra (100 steps)", 100, 0.40),
        ]
        hb_q = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb_q.pack_start(Gtk.Label(label="Quality Preset:"), False, False, 0)
        quality_combo = Gtk.ComboBoxText()
        quality_combo.set_tooltip_text(
            "Quick quality presets that auto-set steps and denoise.\n"
            "Fast Preview = 20 steps, Standard = 45, Maximum Detail = 70, Ultra = 100.\n"
            "Higher quality takes longer but produces finer restoration.")
        for i, (qlbl, _qs, _qd) in enumerate(SUPIR_QUALITY_PRESETS):
            quality_combo.append(str(i), qlbl)
        quality_combo.set_active(1)  # Standard
        quality_combo.set_hexpand(True)
        hb_q.pack_start(quality_combo, True, True, 0); bx.pack_start(hb_q, False, False, 0)
        # Denoise (always visible)
        supir_dn_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        supir_dn_hb.pack_start(Gtk.Label(label="Denoise:"), False, False, 0)
        denoise_spin = Gtk.SpinButton.new_with_range(0.1, 1.0, 0.05)
        denoise_spin.set_value(0.3); denoise_spin.set_digits(2)
        denoise_spin.set_tooltip_text("Lower = more faithful to original, higher = more restoration.\nDefault: 0.3 (conservative). Try 0.5+ for heavily degraded images.")
        supir_dn_hb.pack_start(denoise_spin, False, False, 0)
        bx.pack_start(supir_dn_hb, False, False, 0)
        # Create steps/scale/seed spinners (packed into expanders below)
        steps_spin = Gtk.SpinButton.new_with_range(10, 100, 5)
        steps_spin.set_value(45)
        steps_spin.set_tooltip_text("Restoration steps. Default: 45 for the full pipeline.\n20 = fast preview, 45 = production quality, 70+ = maximum detail.\nMore steps give finer restoration but take longer.")
        scale_spin = Gtk.SpinButton.new_with_range(1.0, 4.0, 0.25)
        scale_spin.set_value(1.0); scale_spin.set_digits(2)
        scale_spin.set_tooltip_text("Output scale factor. 1.0 = same size as input.\nSUPIR can upscale during restoration. 2.0 = double resolution.\nHigher values use more VRAM and take longer.")
        seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        seed_spin.set_value(-1); seed_spin.set_tooltip_text("-1 = random")
        prompt_tv = Gtk.TextView(); prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_tv.set_size_request(-1, 50)
        prompt_tv.set_tooltip_text("Describe the desired quality of the restored image.\nDefault works well. Add specific terms like 'portrait' or 'landscape' for better results.")
        prompt_tv.get_buffer().set_text("high quality, detailed, sharp focus, professional photograph, natural colors, clean, well-lit")
        # Quality preset auto-sets steps + denoise
        def _on_quality_changed(combo):
            idx = combo.get_active()
            if 0 <= idx < len(SUPIR_QUALITY_PRESETS):
                _qlbl, qsteps, qdenoise = SUPIR_QUALITY_PRESETS[idx]
                steps_spin.set_value(qsteps)
                denoise_spin.set_value(qdenoise)
        quality_combo.connect("changed", _on_quality_changed)
        # WD Tagger button
        supir_wd_btn = None
        supir_wd_status = None
        wd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        supir_wd_btn = Gtk.Button(label="Tag Image (WD Tagger)")
        supir_wd_btn.set_tooltip_text(
            "Sends your image to ComfyUI's WD14 Tagger and pastes the\n"
            "detected tags into your prompt. Review and edit before generating.\n\n"
            "Requires the WD14Tagger node (pysssss) in ComfyUI.")
        supir_wd_status = Gtk.Label(label="")
        supir_wd_status.set_xalign(0)
        def _on_supir_wd_tag(btn):
            server = se.get_text().strip()
            if not server:
                supir_wd_status.set_markup('<span foreground="#FF5252">No server URL</span>')
                return
            btn.set_sensitive(False)
            supir_wd_status.set_text("Exporting image...")
            def _do_tag():
                try:
                    images = Gimp.get_images()
                    if not images:
                        return None, "No image open in GIMP"
                    img = images[0]
                    tmp = _export_image_to_tmp(img)
                    supir_wd_status.set_text("Uploading...")
                    uname = f"wd_tag_{uuid.uuid4().hex[:8]}.png"
                    _upload_image_sync(server, tmp, uname)
                    os.unlink(tmp)
                    wf = {
                        "1": {"class_type": "LoadImage",
                              "inputs": {"image": uname}},
                        "2": {"class_type": "WD14Tagger|pysssss",
                              "inputs": {
                                  "image": ["1", 0],
                                  "model": "wd-eva02-large-tagger-v3",
                                  "threshold": 0.35,
                                  "character_threshold": 0.85,
                                  "replace_underscore": True,
                                  "trailing_comma": True,
                                  "exclude_tags": "",
                              }},
                        "3": {"class_type": "ShowText|pysssss",
                              "inputs": {"text": ["2", 0]}},
                    }
                    supir_wd_status.set_text("Tagging...")
                    result = _api_post_json(server, "/prompt", {"prompt": wf, "extra_pnginfo": {"workflow": wf}})
                    prompt_id = result.get("prompt_id")
                    if not prompt_id:
                        return None, "ComfyUI did not return a prompt_id"
                    deadline = time.time() + 60
                    while time.time() < deadline:
                        try:
                            history = _api_get(server, f"/history/{prompt_id}")
                            if prompt_id in history:
                                outputs = history[prompt_id].get("outputs", {})
                                for nid, nout in outputs.items():
                                    if "text" in nout:
                                        tags = nout["text"]
                                        if isinstance(tags, list):
                                            tags = tags[0]
                                        return tags, None
                                    if "string" in nout:
                                        tags = nout["string"]
                                        if isinstance(tags, list):
                                            tags = tags[0]
                                        return tags, None
                                return None, "Tagger ran but tags not in history output."
                        except Exception:
                            pass
                        time.sleep(1)
                    return None, "Tagger timed out (60s)"
                except Exception as e:
                    return None, str(e)
            def _on_done(result):
                tags, error = result
                btn.set_sensitive(True)
                if error:
                    supir_wd_status.set_markup(f'<span foreground="#FF5252">{error}</span>')
                elif tags:
                    buf = prompt_tv.get_buffer()
                    existing = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
                    new_text = f"{tags}, {existing}" if existing.strip() else tags
                    buf.set_text(new_text)
                    tag_count = len([t for t in tags.split(",") if t.strip()])
                    supir_wd_status.set_markup(f'<span foreground="#00E676">{tag_count} tags added</span>')
            def _on_err(e):
                btn.set_sensitive(True)
                supir_wd_status.set_markup(f'<span foreground="#FF5252">{e}</span>')
            _async_fetch(_do_tag, _on_done, _on_err)
        supir_wd_btn.connect("clicked", _on_supir_wd_tag)
        wd_row.pack_start(supir_wd_btn, False, False, 0)
        wd_row.pack_start(supir_wd_status, True, True, 0)
        # wd_row is packed into the Advanced expander below (near prompt_tv)
        # ── ControlNet & Scale (collapsible) ─────────────────────────────
        supir_cn_exp = Gtk.Expander(label="\u25b8 ControlNet & Scale")
        _shrink_on_collapse(supir_cn_exp, dlg)
        supir_cn_exp.set_expanded(False)
        supir_cn_exp.set_tooltip_text("ControlNet refinement pass (post-SUPIR) and output scale factor.\nSUPIR does not support ControlNet directly; an optional low-denoise pass locks in detail.")
        supir_cn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        supir_cn_box.set_margin_start(4); supir_cn_box.set_margin_top(4)
        supir_cn_box.pack_start(Gtk.Label(label="ControlNet Refinement (post-SUPIR pass):", xalign=0), False, False, 0)
        supir_cn_box.pack_start(Gtk.Label(label="<small>SUPIR does not support ControlNet directly. An optional low-denoise\n"
                                       "refinement pass with ControlNet locks in structural detail.</small>",
                                 xalign=0, use_markup=True), False, False, 0)
        # ControlNet 1
        supir_cn_box.pack_start(Gtk.Label(label="ControlNet 1 (Tile recommended):", xalign=0), False, False, 0)
        supir_cn_combo = Gtk.ComboBoxText()
        supir_cn_combo.set_tooltip_text(
            "ControlNet preserves structure from your source image.\n\n"
            "Modes:\n"
            "  Tile \u2014 preserves layout + adds detail (BEST for upscale/hallucinate)\n"
            "  Canny \u2014 follows edges (good for architecture, objects)\n"
            "  Depth \u2014 preserves 3D depth (good for portraits, scenes)\n"
            "  OpenPose \u2014 follows body pose (portraits, figure work)\n"
            "  Lineart \u2014 follows line drawing (illustration, sketches)\n"
            "  Scribble \u2014 loose sketch guide (creative, abstract)\n\n"
            "Recommended pairings:\n"
            "  Tile + Depth \u2014 structure-aware detail (hallucination)\n"
            "  OpenPose + Canny \u2014 body pose + edge detail (portraits)\n"
            "  Depth + Lineart \u2014 spatial + line structure (scenes)\n\n"
            "\u26a0 SD1.5 and SDXL use DIFFERENT ControlNet models.\n"
            "The correct model is auto-selected based on your checkpoint.")
        for key in CONTROLNET_GUIDE_MODES:
            supir_cn_combo.append(key, key)
        supir_cn_combo.set_active(0)  # Off by default
        supir_cn_box.pack_start(supir_cn_combo, False, False, 0)
        supir_cn_str_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        supir_cn_str_hb.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        supir_cn_strength = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        supir_cn_strength.set_digits(2); supir_cn_strength.set_value(0.6)
        supir_cn_strength.set_tooltip_text("ControlNet 1 strength for the refinement pass.\n0.6 = default. Higher = more structural guidance.")
        supir_cn_str_hb.pack_start(supir_cn_strength, False, False, 0)
        supir_cn_box.pack_start(supir_cn_str_hb, False, False, 0)
        # ControlNet 2
        supir_cn_box.pack_start(Gtk.Label(label="ControlNet 2 (optional -- Tile + Depth):", xalign=0), False, False, 0)
        supir_cn_combo_2 = Gtk.ComboBoxText()
        supir_cn_combo_2.set_tooltip_text(
            "Optional second ControlNet to combine with the first.\n"
            "Both guides are applied simultaneously \u2014 the AI follows both.\n\n"
            "Best combos:\n"
            "  CN1: Tile + CN2: Depth \u2014 detail + structure\n"
            "  CN1: OpenPose + CN2: Canny \u2014 pose + edges\n"
            "  CN1: Depth + CN2: Lineart \u2014 spatial + line guide\n\n"
            "Keep CN2 strength lower than CN1 (e.g., 0.4 vs 0.7)\n"
            "to let the primary guide dominate.")
        for key in CONTROLNET_GUIDE_MODES:
            supir_cn_combo_2.append(key, key)
        supir_cn_combo_2.set_active(0)  # Off by default
        supir_cn_box.pack_start(supir_cn_combo_2, False, False, 0)
        supir_cn_str_hb_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        supir_cn_str_hb_2.pack_start(Gtk.Label(label="Strength:"), False, False, 0)
        supir_cn_strength_2 = Gtk.SpinButton.new_with_range(0.0, 1.5, 0.05)
        supir_cn_strength_2.set_digits(2); supir_cn_strength_2.set_value(0.4)
        supir_cn_strength_2.set_tooltip_text("ControlNet 2 strength. 0.4 = default for secondary guidance.")
        supir_cn_str_hb_2.pack_start(supir_cn_strength_2, False, False, 0)
        supir_cn_box.pack_start(supir_cn_str_hb_2, False, False, 0)
        # Scale spinner inside CN expander
        supir_scale_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        supir_scale_hb.pack_start(Gtk.Label(label="Scale:"), False, False, 0)
        supir_scale_hb.pack_start(scale_spin, False, False, 0)
        supir_cn_box.pack_start(supir_scale_hb, False, False, 0)
        supir_cn_exp.add(supir_cn_box)
        bx.pack_start(supir_cn_exp, False, False, 0)
        # ── Advanced (collapsible) ───────────────────────────────────────
        supir_adv_exp = Gtk.Expander(label="\u25b8 Advanced")
        _shrink_on_collapse(supir_adv_exp, dlg)
        supir_adv_exp.set_expanded(False)
        supir_adv_exp.set_tooltip_text("Steps, seed, positive prompt, and batch run settings.")
        supir_adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        supir_adv_box.set_margin_start(4); supir_adv_box.set_margin_top(4)
        supir_steps_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        supir_steps_hb.pack_start(Gtk.Label(label="Steps:"), False, False, 0)
        supir_steps_hb.pack_start(steps_spin, False, False, 0)
        supir_adv_box.pack_start(supir_steps_hb, False, False, 0)
        supir_seed_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        supir_seed_hb.pack_start(Gtk.Label(label="Seed:"), False, False, 0)
        supir_seed_hb.pack_start(seed_spin, False, False, 0)
        supir_adv_box.pack_start(supir_seed_hb, False, False, 0)
        supir_adv_box.pack_start(Gtk.Label(label="Positive Prompt:", xalign=0), False, False, 0)
        sw = Gtk.ScrolledWindow(); sw.add(prompt_tv); sw.set_min_content_height(50)
        supir_adv_box.pack_start(sw, False, False, 0)
        supir_adv_box.pack_start(wd_row, False, False, 0)
        # Runs spinner
        runs_hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        runs_hb.pack_start(Gtk.Label(label="Runs:"), False, False, 0)
        runs_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        runs_spin.set_value(1)
        runs_spin.set_tooltip_text("Number of times to run this generation. Each run uses a fresh random seed.")
        runs_hb.pack_start(runs_spin, False, False, 0)
        runs_hb.pack_start(Gtk.Label(label="(each run gets a new seed)"), False, False, 0)
        supir_adv_box.pack_start(runs_hb, False, False, 0)
        supir_adv_exp.add(supir_adv_box)
        bx.pack_start(supir_adv_exp, False, False, 0)
        # AutoSet button
        def _supir_auto_set():
            arch = "sdxl"  # SUPIR is always SDXL-based
            pos, _neg = _AUTOSET_PROMPTS.get(arch, _AUTOSET_PROMPTS["sdxl"])
            prompt_tv.get_buffer().set_text(pos)
            denoise_spin.set_value(_AUTOSET_DENOISE.get((arch, "supir"), 0.30))
            steps_spin.set_value(45)
            cn = _AUTOSET_CN.get((arch, "supir"))
            if cn:
                cn1k, cn1s, cn2k, cn2s = cn
                if cn1k is not None:
                    supir_cn_combo.set_active_id(cn1k)
                if cn1s is not None:
                    supir_cn_strength.set_value(cn1s)
                supir_cn_combo_2.set_active_id(cn2k)
                supir_cn_strength_2.set_value(cn2s)
        _supir_auto_btn = Gtk.Button(label="A.")
        _supir_auto_btn.set_tooltip_text("AutoSet: optimal config for SUPIR restoration")
        _supir_auto_btn.set_size_request(32, -1)
        _supir_auto_btn.connect("clicked", lambda b: _supir_auto_set())
        _supir_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        _supir_top.pack_end(_supir_auto_btn, False, False, 0)
        bx.pack_start(_supir_top, False, False, 0)
        # Task preset auto-fills prompt, denoise, steps
        def _on_task_changed(combo):
            key = combo.get_active_id()
            if key and key in SUPIR_TASK_PRESETS:
                tp = SUPIR_TASK_PRESETS[key]
                prompt_tv.get_buffer().set_text(tp["prompt"])
                denoise_spin.set_value(tp["denoise"])
                steps_spin.set_value(tp["steps"])
        task_combo.connect("changed", _on_task_changed)
        _on_task_changed(task_combo)  # fill from initial selection
        bx.show_all()
        last = _SESSION.get("supir")
        if last:
            if "model_id" in last:
                model_combo.set_active_id(last["model_id"])
            if "quality_idx" in last:
                quality_combo.set_active(last["quality_idx"])
            if "denoise" in last:
                denoise_spin.set_value(last["denoise"])
            if "steps" in last:
                steps_spin.set_value(last["steps"])
            if "scale" in last:
                scale_spin.set_value(last["scale"])
            if "prompt" in last:
                prompt_tv.get_buffer().set_text(last["prompt"])
            if "cn1_id" in last:
                supir_cn_combo.set_active_id(last["cn1_id"])
            if "cn1_str" in last:
                supir_cn_strength.set_value(last["cn1_str"])
            if "cn2_id" in last:
                supir_cn_combo_2.set_active_id(last["cn2_id"])
            if "cn2_str" in last:
                supir_cn_strength_2.set_value(last["cn2_str"])
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
        scale = scale_spin.get_value()
        base_seed = int(seed_spin.get_value())
        if base_seed < 0:
            base_seed = random.randint(0, 2**32 - 1)
        runs = int(runs_spin.get_value())
        pbuf = prompt_tv.get_buffer()
        prompt = pbuf.get_text(pbuf.get_start_iter(), pbuf.get_end_iter(), False)
        # ControlNet params
        cn1_mode = supir_cn_combo.get_active_id() if supir_cn_combo else "Off"
        cn1 = {"mode": cn1_mode, "strength": supir_cn_strength.get_value(),
                "start_percent": 0.0, "end_percent": 1.0} if cn1_mode != "Off" else None
        cn2_mode = supir_cn_combo_2.get_active_id() if supir_cn_combo_2 else "Off"
        cn2 = {"mode": cn2_mode, "strength": supir_cn_strength_2.get_value(),
                "start_percent": 0.0, "end_percent": 1.0} if cn2_mode != "Off" else None
        _SESSION["supir"] = {
            "model_id": model_combo.get_active_id(),
            "quality_idx": quality_combo.get_active(),
            "denoise": denoise, "steps": steps, "scale": scale,
            "prompt": prompt, "runs": runs,
            "cn1_id": cn1_mode, "cn1_str": supir_cn_strength.get_value(),
            "cn2_id": cn2_mode, "cn2_str": supir_cn_strength_2.get_value(),
        }
        _save_session()
        dlg.destroy()
        try:
            _update_spinner_status("SUPIR: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_supir_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            for run_i in range(runs):
                seed = base_seed if runs == 1 else random.randint(0, 2**32 - 1)
                wf = _build_supir(uname, "Other\\SUPIR-v0Q_fp16.safetensors", sdxl_model,
                                   prompt, seed, denoise, steps, scale_by=scale,
                                   controlnet=cn1, controlnet_2=cn2)
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
            _update_spinner_status("Remove Background: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_rembg_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_rembg(uname)
            _update_spinner_status("Remove Background: processing on ComfyUI...")
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
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
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
            _update_spinner_status("Uploading...")
            tmp = _export_image_to_tmp(image)
            r = _upload_image_sync(srv, tmp, fn); os.unlink(tmp)
            Gimp.message(f"Uploaded as: {r.get('name', fn)}")
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Upload Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_my_presets(self, procedure, run_mode, image, drawables, config, data):
        """My Spellcaster Presets: quick access to all saved presets across tools."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        _apply_spellcaster_theme()
        dlg = Gtk.Dialog(title="My Spellcaster Presets")
        dlg.set_default_size(600, 400)
        dlg.add_button("_Close", Gtk.ResponseType.CLOSE)
        _style_dialog_buttons(dlg)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(16); bx.set_margin_end(16)
        bx.set_margin_top(16); bx.set_margin_bottom(16)

        _hdr = _make_branded_header()
        if _hdr:
            bx.pack_start(_hdr, False, False, 0)

        # Map dialog keys to human-readable tool names
        # Keys MUST match what _add_preset_ui uses in each dialog
        tool_names = {
            "preset_dialog": "img2img / txt2img / Inpaint",
            "wan_i2v": "Wan I2V Video",
            "faceid": "FaceID",
            "klein": "Klein Editor",
            "pulid_flux": "PuLID Flux",
        }

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroll.add(list_box)

        found_any = False
        for dialog_key, tool_label in tool_names.items():
            saved = _load_user_presets(dialog_key)
            if not saved:
                continue

            # Section header
            header = Gtk.Label()
            header.set_markup(f'<b><span foreground="#D122E3">{tool_label}</span></b>')
            header.set_xalign(0)
            list_box.pack_start(header, False, False, 4)

            for preset in saved:
                found_any = True
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                row.set_margin_start(12)

                # Preset name
                name_lbl = Gtk.Label(label=preset.get("name", "Unnamed"), xalign=0)
                name_lbl.set_hexpand(True)
                row.pack_start(name_lbl, True, True, 0)

                # Info tooltip with preset details
                info_parts = []
                if preset.get("model_preset_idx") is not None:
                    idx = preset["model_preset_idx"]
                    if 0 <= idx < len(MODEL_PRESETS):
                        info_parts.append(f"Model: {MODEL_PRESETS[idx]['label']}")
                if preset.get("prompt"):
                    p = preset["prompt"][:80]
                    info_parts.append(f"Prompt: {p}...")
                if preset.get("steps"):
                    info_parts.append(f"Steps: {preset['steps']}")
                name_lbl.set_tooltip_text("\n".join(info_parts) if info_parts else "Saved preset")

                # Load button — applies preset to session and opens the tool
                load_btn = Gtk.Button(label="Load")
                load_btn.set_tooltip_text(f"Load this preset into {tool_label} and open the tool")
                def _make_load_cb(dk, p):
                    def on_load(btn):
                        # Store preset into session for the correct tool
                        session_key = {
                            "preset_dialog": "img2img",
                            "wan_i2v": "wan_i2v",
                            "faceid": "faceid",
                            "klein": "klein",
                            "pulid_flux": "pulid_flux",
                        }.get(dk, dk)
                        _SESSION[session_key] = p
                        _save_session()
                        dlg.destroy()
                    return on_load
                load_btn.connect("clicked", _make_load_cb(dialog_key, preset))
                row.pack_end(load_btn, False, False, 0)

                # Delete button
                del_btn = Gtk.Button(label="Delete")
                del_btn.set_tooltip_text(f"Delete this preset permanently")
                def _make_del_cb(dk, pname, r):
                    def on_del(btn):
                        presets = _load_user_presets(dk)
                        presets = [pp for pp in presets if pp.get("name") != pname]
                        _save_user_presets(presets, dk)
                        r.destroy()
                    return on_del
                del_btn.connect("clicked", _make_del_cb(dialog_key, preset.get("name"), row))
                row.pack_end(del_btn, False, False, 0)

                list_box.pack_start(row, False, False, 0)

            list_box.pack_start(Gtk.Separator(), False, False, 2)

        if not found_any:
            empty = Gtk.Label()
            empty.set_markup(
                '<span foreground="#888888">No saved presets yet.\n\n'
                'To save a preset, open any Spellcaster tool,\n'
                'configure your settings, then click "Save" in\n'
                'the My Presets section of the dialog.</span>')
            list_box.pack_start(empty, True, True, 20)

        bx.pack_start(scroll, True, True, 0)
        bx.show_all()
        dlg.run()
        dlg.destroy()
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

    def _run_settings(self, procedure, run_mode, image, drawables, config, data):
        """Spellcaster Settings: configure server URL, defaults, and preferences."""
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        try:
            GimpUi.init("spellcaster")
        except Exception:
            pass
        try:
            _apply_spellcaster_theme()
        except Exception:
            pass
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
        _hdr = _make_branded_header()
        if _hdr:
            bx.pack_start(_hdr, False, False, 0)

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

        # ── Favourite Model ──
        bx.pack_start(Gtk.Separator(), False, False, 5)
        bx.pack_start(Gtk.Label(label="Favourite Model (opens first in all dialogs):", xalign=0), False, False, 0)
        fav_combo = Gtk.ComboBoxText()
        fav_combo.append("-1", "(none — use last-used model)")
        for i, p in enumerate(MODEL_PRESETS):
            fav_combo.append(str(i), p["label"])
        saved_fav = cfg.get("favourite_model", -1)
        fav_combo.set_active_id(str(saved_fav))
        fav_combo.set_tooltip_text(
            "Choose your go-to model. When set, every img2img, txt2img,\n"
            "and inpaint dialog opens with this model pre-selected.\n"
            "Set to '(none)' to use the last-used model instead.")
        bx.pack_start(fav_combo, False, False, 0)

        # ── My Presets (quick access to saved presets) ──
        bx.pack_start(Gtk.Separator(), False, False, 5)
        bx.pack_start(Gtk.Label(label="My Saved Presets:", xalign=0), False, False, 0)

        # Load all user presets from all dialog types
        presets_frame = Gtk.Frame()
        presets_frame.set_shadow_type(Gtk.ShadowType.IN)
        presets_scroll = Gtk.ScrolledWindow()
        presets_scroll.set_min_content_height(120)
        presets_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        presets_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        presets_scroll.add(presets_box)
        presets_frame.add(presets_scroll)

        all_presets = {}
        for dialog_key in ["preset_dialog", "wan_dialog", "faceid_dialog",
                           "klein_dialog", "klein_ref_dialog", "pulid_dialog"]:
            saved = _load_user_presets(dialog_key)
            for p in saved:
                pname = p.get("name", "Unnamed") if isinstance(p, dict) else "Unnamed"
                all_presets[f"{dialog_key}: {pname}"] = (dialog_key, p)

        if all_presets:
            for display_name, (dkey, preset) in all_presets.items():
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                lbl = Gtk.Label(label=display_name, xalign=0)
                lbl.set_hexpand(True)
                row.pack_start(lbl, True, True, 4)
                del_btn = Gtk.Button(label="Delete")
                del_btn.set_tooltip_text(f"Delete preset '{preset['name']}' from {dkey}")
                def _make_delete_cb(dk, pname):
                    def on_del(btn):
                        presets = _load_user_presets(dk)
                        presets = [p for p in presets if p.get("name") != pname]
                        _save_user_presets(presets, dk)
                        btn.get_parent().destroy()
                    return on_del
                del_btn.connect("clicked", _make_delete_cb(dkey, preset["name"]))
                row.pack_end(del_btn, False, False, 4)
                presets_box.pack_start(row, False, False, 0)
        else:
            presets_box.pack_start(
                Gtk.Label(label="No saved presets yet. Save presets from any tool dialog."),
                False, False, 8)

        bx.pack_start(presets_frame, True, True, 0)

        # ── Auto-update toggle ──
        bx.pack_start(Gtk.Separator(), False, False, 5)
        auto_update_cb = Gtk.CheckButton(label="Auto-update plugin from GitHub on startup")
        auto_update_cb.set_active(cfg.get("auto_update", True))
        auto_update_cb.set_tooltip_text(
            "When enabled, Spellcaster checks GitHub for updates every time\n"
            "GIMP starts. Disable if you have custom modifications you want\n"
            "to preserve, or if you have no internet connection.")
        bx.pack_start(auto_update_cb, False, False, 0)

        # ── Debug images toggle ──
        debug_cb = Gtk.CheckButton(label="Save ControlNet debug layers (invisible)")
        debug_cb.set_active(cfg.get("debug_images", False))
        debug_cb.set_tooltip_text(
            "When enabled, ControlNet preprocessor output (canny edges, depth map,\n"
            "pose skeleton) is saved as an invisible layer in your image.\n"
            "Toggle the layer visibility to inspect what the AI 'sees'.\n\n"
            "Disable to keep your layer stack clean.")
        bx.pack_start(debug_cb, False, False, 0)

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
        new_debug = debug_cb.get_active()
        fav_id = fav_combo.get_active_id()
        new_fav = int(fav_id) if fav_id and fav_id != "-1" else -1
        dlg.destroy()

        _save_config({
            "server_url": new_url,
            "timeout": new_timeout,
            "auto_update": new_auto_update,
            "debug_images": new_debug,
            "favourite_model": new_fav,
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
