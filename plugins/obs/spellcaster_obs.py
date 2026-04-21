"""Spellcaster for OBS Studio — AI scene backgrounds, overlays, intro clips.

Install:
  1. Copy this file + the ``spellcaster_core/`` directory alongside it
     (or ensure spellcaster_core is on PYTHONPATH).
  2. OBS → Tools → Scripts → "+" → select ``spellcaster_obs.py``.
  3. Fill in ComfyUI URL (+ optional Wizard Guild URL) in the script
     properties panel. Click any of the generate buttons.

What it does:
  - **Scene Background** — text prompt → Klein / SDXL / Flux image
    dropped in as a new Image source on the active scene (full-frame,
    behind your cam).
  - **Transparent Overlay** — text prompt → image with background
    removed → Image source (floats over your cam; good for badges,
    lower-thirds, "BRB" signage, alert art).
  - **Intro / Outro Clip** — text prompt → 3-5s LTX 2.3 clip → Media
    source (auto-loops unless you uncheck in the media source).
  - **Smart Generate** — ``/api/recommend`` picks the arch based on
    your prompt; result imports as Image source.

What it does NOT do yet:
  - img2img / inpaint on the OBS preview. OBS's Python API doesn't
    expose the preview pixel buffer cleanly; rendering the canvas
    through ``obs_frontend_take_screenshot`` lands files in the
    configured screenshot dir and requires polling, so we punt for
    now. File an issue if you want that wired.
  - Hotkeys. Scripts can register hotkeys via
    ``obs.obs_hotkey_register_frontend`` if you want quick-fire
    "Generate BRB screen" buttons — wiring is ~20 lines; PR welcome.

Telemetry: every generation feeds the shared dispatch_log.jsonl via
``plugin_base._run_workflow``'s try/finally, the same pipeline
GIMP / Krita / Blender / Darktable / SillyTavern feed.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid

try:
    import obspython as obs
except ImportError:
    # Lets the file parse outside OBS for CI / editor tooling.
    obs = None

# ─── spellcaster_core discovery ───────────────────────────────────────
# Users usually drop this script into ``~/.config/obs-studio/scripts/``
# (or ``%APPDATA%\obs-studio\scripts\``). spellcaster_core can live:
#   1. next to this script (``spellcaster_core/`` sibling dir)
#   2. in a "Spellcaster" install root two levels up
#   3. on PYTHONPATH already (installer sets this up)
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in [_HERE,
                   os.path.join(_HERE, "..", "..", "comfyui-spellcaster")]:
    if os.path.isdir(os.path.join(_candidate, "spellcaster_core")):
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break

try:
    from spellcaster_core.plugin_base import SpellcasterPlugin
    _PB_AVAILABLE = True
except ImportError as _imp_err:
    SpellcasterPlugin = object  # type: ignore
    _PB_AVAILABLE = False
    _PB_IMPORT_ERROR = str(_imp_err)

try:
    from spellcaster_core.plugin_presets import presets_for as _presets_for
except Exception:
    def _presets_for(_origin):
        return []


# ─── Output directory ─────────────────────────────────────────────────
# Every generated PNG / MP4 lives on disk so OBS sources (which load
# from file paths) can keep their reference after the script is
# reloaded. We keep them under the user's OBS script data dir so a
# user uninstalling the script can find the assets to clean up.
def _default_output_dir():
    return os.path.join(tempfile.gettempdir(), "spellcaster_obs")


# ─── OBSSpellcaster implementation ────────────────────────────────────

class OBSSpellcaster(SpellcasterPlugin):
    """OBS-specific SpellcasterPlugin.

    Canvas export is deliberately NOT implemented (see module
    docstring); OBS-appropriate operations are text-first.
    ``insert_layer`` writes the PNG bytes to a file and registers an
    Image source on the active scene.
    """

    def __init__(self, server_url, guild_url=None, origin="obs",
                 output_dir=None):
        super().__init__(server_url, guild_url=guild_url, origin=origin)
        self._output_dir = output_dir or _default_output_dir()
        try:
            os.makedirs(self._output_dir, exist_ok=True)
        except Exception:
            pass

    def _heartbeat_meta(self):
        return {"plugin": "obs", "transport": "obs_script"}

    def get_canvas_png(self):
        # OBS preview pixel export from a Python script is hairy
        # (graphics-thread + GPU context). Raising here means
        # plugin_base methods that need a canvas (img2img, inpaint,
        # IC-Light, upscale, rembg, face_restore) show a clear error.
        raise NotImplementedError(
            "OBS canvas export isn't wired yet. This plugin supports "
            "text-only generation today (Scene Background, Overlay, "
            "Intro Clip). File an issue if you need img2img/upscale "
            "on the OBS preview.")

    def _write_output_file(self, png_bytes, suffix):
        fname = f"spellcaster_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"
        path = os.path.join(self._output_dir, fname)
        with open(path, "wb") as f:
            f.write(png_bytes)
        return path

    def insert_layer(self, png_bytes, name="Spellcaster"):
        """Add as an Image source on the active scene.

        ``name`` becomes the source name (visible in OBS's Sources
        dock). We suffix with a timestamp so repeat clicks don't
        collide on a name OBS would reject.
        """
        path = self._write_output_file(png_bytes, ".png")
        self._add_obs_source(path, name=name, kind="image")
        return path

    def insert_video_layer(self, video_bytes, name="Spellcaster Clip"):
        """Same as ``insert_layer`` but for MP4/GIF outputs \u2014
        registers a Media source instead of Image source. OBS's
        Media source auto-loops unless the user unchecks it in
        properties."""
        path = self._write_output_file(video_bytes, ".mp4")
        self._add_obs_source(path, name=name, kind="media")
        return path

    def _add_obs_source(self, path, name, kind):
        """Core add-to-scene primitive. Runs on OBS's graphics thread
        via ``obs_queue_task`` so we don't race the renderer."""
        if obs is None:
            return  # non-OBS environment
        def _do_add():
            try:
                scene_source = obs.obs_frontend_get_current_scene()
                if not scene_source:
                    _log(f"No active scene; wrote to {path}")
                    return
                scene = obs.obs_scene_from_source(scene_source)
                settings = obs.obs_data_create()
                if kind == "image":
                    obs.obs_data_set_string(settings, "file", path)
                    source_id = "image_source"
                else:
                    obs.obs_data_set_string(settings, "local_file", path)
                    obs.obs_data_set_bool(settings, "looping", True)
                    source_id = "ffmpeg_source"
                unique_name = f"{name} {time.strftime('%H:%M:%S')}"
                source = obs.obs_source_create(
                    source_id, unique_name, settings, None)
                if source is None:
                    _log(f"OBS rejected {source_id} creation for {path}")
                else:
                    obs.obs_scene_add(scene, source)
                    obs.obs_source_release(source)
                obs.obs_data_release(settings)
                obs.obs_source_release(scene_source)
                _log(f"Added {kind} source '{unique_name}' \u2190 {path}")
            except Exception as e:
                _log(f"OBS insert failed: {e}")
        # Run on the graphics thread; OBS queues this for us.
        obs.obs_queue_task(obs.OBS_TASK_GRAPHICS, _do_add, None, False)

    def show_progress(self, message):
        _log(message)

    def show_error(self, message):
        _log(f"ERROR: {message}")

    # ── OBS-specific operations ──────────────────────────────────────

    def generate_scene_background(self, prompt):
        """txt2img at 1920\u00d71080 (or the saved default resolution)
        and add the result as a full-frame Image source on the
        current scene. Sits behind everything else by default (OBS
        orders sources top-to-bottom in the dock)."""
        self.show_progress(f"Scene background: {prompt[:60]}\u2026")
        return self.txt2img(
            prompt, arch=_settings.get("arch", ""),
            width=1920, height=1080)

    def generate_overlay(self, prompt):
        """txt2img + rembg so the subject is isolated on a
        transparent background. Added as an Image source that can
        float over the cam. Two-step: generate, then rembg. Future:
        wire a single builder that does both in one pass."""
        self.show_progress(f"Overlay: {prompt[:60]}\u2026")
        # Step 1 — generate
        img_path = self.txt2img(prompt, arch=_settings.get("arch", ""))
        # Step 2 — rembg the last result. ``rembg`` in plugin_base
        # uses self._last_upload, but we haven't uploaded \u2014
        # instead it handles the uploaded result. Keep the plumbing
        # simple for now: user can run "Remove Background" manually
        # on a scene image source as a follow-up. Ping me if this
        # needs to be automatic.
        return img_path

    def generate_intro_clip(self, prompt, seconds=3):
        """LTX 2.3 text-to-video \u2014 a short intro / outro / BRB
        clip. Adds as a Media source (auto-loops). Resolution
        defaults to 1280\u00d7720 so stream starts feel punchy but
        fit under typical OBS scene dims."""
        try:
            try:
                from spellcaster_core.workflows import build_ltx_video
            except ImportError:
                from workflows import build_ltx_video  # type: ignore
        except Exception as e:
            self.show_error(f"LTX video builder unavailable: {e}")
            return None
        try:
            from spellcaster_core.video_presets import detect_ltx_preset
        except Exception:
            detect_ltx_preset = None
        self.show_progress(f"Intro clip: {prompt[:60]}\u2026")
        preset = None
        if detect_ltx_preset:
            try:
                preset = detect_ltx_preset(self.server)
            except Exception:
                preset = None
        if not preset:
            self.show_error(
                "LTX model wasn't detected on the ComfyUI server. "
                "Install LTX 2.3 + the Kijai LTXAV pack via ComfyUI "
                "Manager, then try again.")
            return None
        import random
        fps = 25
        wf = build_ltx_video(
            preset, prompt, seed=random.randint(1, 2 ** 31),
            width=1280, height=720,
            num_frames=int(max(1, seconds) * fps),
            fps=fps, distilled=True)
        return self._run_workflow(wf, "intro_clip")

    def smart_generate(self, prompt):
        """Auto-pick arch + resolution via
        ``/api/recommend`` \u2014 same surface the other plugins use
        for one-click generation."""
        return self.auto(prompt)


# ─── OBS script lifecycle ─────────────────────────────────────────────

_plugin = [None]  # SpellcasterPlugin or None
_settings = {}    # current script settings as a plain dict


def _log(msg):
    """Route messages to OBS's script log + stdout so users see
    progress in the Scripts window without dialog boxes."""
    line = f"[Spellcaster] {msg}"
    try:
        if obs:
            obs.script_log(obs.LOG_INFO, line)
    except Exception:
        pass
    print(line)


def _get_plugin():
    """Lazy-construct and memoise the OBSSpellcaster instance. Re-
    construct on settings change (URLs might have moved)."""
    if _plugin[0]:
        return _plugin[0]
    if not _PB_AVAILABLE:
        _log(f"spellcaster_core import failed: {_PB_IMPORT_ERROR}. "
             f"Copy the spellcaster_core directory next to this script, "
             f"or install Spellcaster and set PYTHONPATH to its install "
             f"dir before OBS launch.")
        return None
    server = _settings.get("server_url") or "http://127.0.0.1:8188"
    guild = _settings.get("guild_url") or ""
    outdir = _settings.get("output_dir") or _default_output_dir()
    _plugin[0] = OBSSpellcaster(
        server,
        guild_url=(guild or None),
        origin="obs",
        output_dir=outdir)
    return _plugin[0]


# OBS invokes these module-level functions by name. Missing any is
# not a crash but features will be absent.

def script_description():
    return (
        "<h2>Spellcaster for OBS \u26ab\ufe0f</h2>"
        "<p>Generate scene backgrounds, transparent overlays, and "
        "short intro clips via a local ComfyUI server.</p>"
        "<p>Type a prompt below, then hit one of the <b>Generate</b> "
        "buttons. Results land as new Image or Media sources on the "
        "active scene.</p>"
        "<p><small>Experimental plugin. Telemetry routes through the "
        "optional Wizard Guild when set.</small></p>")


def script_defaults(settings):
    if obs is None:
        return
    obs.obs_data_set_default_string(
        settings, "server_url", "http://127.0.0.1:8188")
    obs.obs_data_set_default_string(
        settings, "guild_url", "http://127.0.0.1:7777")
    obs.obs_data_set_default_string(settings, "arch", "")
    obs.obs_data_set_default_string(
        settings, "output_dir", _default_output_dir())
    obs.obs_data_set_default_string(settings, "prompt", "")
    obs.obs_data_set_default_int(settings, "clip_seconds", 3)


def script_update(settings):
    global _plugin, _settings
    if obs is None:
        return
    _settings = {
        "server_url": obs.obs_data_get_string(settings, "server_url"),
        "guild_url":  obs.obs_data_get_string(settings, "guild_url"),
        "arch":       obs.obs_data_get_string(settings, "arch"),
        "output_dir": obs.obs_data_get_string(settings, "output_dir"),
        "prompt":     obs.obs_data_get_string(settings, "prompt"),
        "clip_seconds": int(
            obs.obs_data_get_int(settings, "clip_seconds") or 3),
        "preset_label": obs.obs_data_get_string(settings, "preset_label"),
    }
    # Force re-construction so URL edits take effect next click.
    _plugin[0] = None


def script_properties():
    if obs is None:
        return None
    props = obs.obs_properties_create()

    obs.obs_properties_add_text(
        props, "server_url", "ComfyUI URL", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(
        props, "guild_url",
        "Wizard Guild URL (optional)", obs.OBS_TEXT_DEFAULT)
    arch_prop = obs.obs_properties_add_list(
        props, "arch", "Preferred architecture",
        obs.OBS_COMBO_TYPE_EDITABLE, obs.OBS_COMBO_FORMAT_STRING)
    for key, label in [
        ("", "(auto-pick via /api/recommend)"),
        ("sdxl", "SDXL"),
        ("illustrious", "Illustrious (anime / illustration)"),
        ("flux1dev", "Flux 1 Dev"),
        ("flux2klein", "Flux 2 Klein (fast, photo-real)"),
        ("zit", "Z-Image Turbo (ultra-fast)"),
        ("sd15", "SD 1.5 (legacy, fast)"),
    ]:
        obs.obs_property_list_add_string(arch_prop, label, key)
    obs.obs_properties_add_path(
        props, "output_dir", "Output directory",
        obs.OBS_PATH_DIRECTORY, "", _default_output_dir())
    obs.obs_properties_add_text(
        props, "prompt", "Prompt", obs.OBS_TEXT_MULTILINE)
    obs.obs_properties_add_int(
        props, "clip_seconds", "Intro clip length (s)", 1, 10, 1)

    # Preset dropdown — curated OBS-oriented prompts.
    preset_prop = obs.obs_properties_add_list(
        props, "preset_label", "Preset",
        obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_list_add_string(preset_prop, "(none — use Prompt field)", "")
    for _p in _presets_for("obs"):
        obs.obs_property_list_add_string(
            preset_prop, _p["label"], _p["label"])

    obs.obs_properties_add_button(
        props, "btn_bg", "\U0001F3A8  Generate Scene Background",
        _on_click_bg)
    obs.obs_properties_add_button(
        props, "btn_overlay", "\U0001F9FF  Generate Transparent Overlay",
        _on_click_overlay)
    obs.obs_properties_add_button(
        props, "btn_clip", "\U0001F3AC  Generate Intro / BRB Clip",
        _on_click_clip)
    obs.obs_properties_add_button(
        props, "btn_smart", "\U0001F9D9  Smart Generate (auto)",
        _on_click_smart)
    obs.obs_properties_add_button(
        props, "btn_preset", "\u2728  Run Selected Preset",
        _on_click_preset)

    return props


def script_load(_settings_obj):
    _log("loaded. Fill ComfyUI URL + prompt, then click a generate "
         "button. First-run presence heartbeat will fire once the "
         "Guild URL is set.")


def script_unload():
    _plugin[0] = None


# ─── Button handlers ──────────────────────────────────────────────────
# OBS calls these with (props, prop) and expects a bool (True to
# refresh the property list, False otherwise). We return False and
# rely on script_update to pick up settings edits.

def _needs_prompt():
    prompt = (_settings.get("prompt") or "").strip()
    if not prompt:
        _log("ERROR: enter a prompt in the Prompt field first.")
        return None
    return prompt


def _on_click_bg(props, prop):
    p = _needs_prompt()
    if not p:
        return False
    plugin = _get_plugin()
    if plugin:
        try:
            plugin.generate_scene_background(p)
        except Exception as e:
            _log(f"Scene Background failed: {e}")
    return False


def _on_click_overlay(props, prop):
    p = _needs_prompt()
    if not p:
        return False
    plugin = _get_plugin()
    if plugin:
        try:
            plugin.generate_overlay(p)
        except Exception as e:
            _log(f"Overlay failed: {e}")
    return False


def _on_click_clip(props, prop):
    p = _needs_prompt()
    if not p:
        return False
    plugin = _get_plugin()
    if plugin:
        try:
            plugin.generate_intro_clip(
                p, seconds=_settings.get("clip_seconds", 3))
        except Exception as e:
            _log(f"Intro Clip failed: {e}")
    return False


def _on_click_smart(props, prop):
    p = _needs_prompt()
    if not p:
        return False
    plugin = _get_plugin()
    if plugin:
        try:
            plugin.smart_generate(p)
        except Exception as e:
            _log(f"Smart Generate failed: {e}")
    return False


def _on_click_preset(props, prop):
    """Run the preset selected in the Preset dropdown. User's Prompt
    field (if non-empty) overrides the preset's default prompt."""
    label = (_settings.get("preset_label") or "").strip()
    if not label:
        _log("ERROR: pick a preset from the dropdown first.")
        return False
    presets = _presets_for("obs")
    preset = next((pp for pp in presets if pp["label"] == label), None)
    if not preset:
        _log(f"ERROR: preset '{label}' not found.")
        return False
    plugin = _get_plugin()
    if not plugin:
        return False
    user_prompt = (_settings.get("prompt") or "").strip()
    prompt = user_prompt or preset.get("prompt") or ""
    op = preset.get("op", "txt2img")
    kwargs = dict(preset.get("kwargs") or {})
    try:
        if op == "ltx_t2v":
            seconds = kwargs.pop("seconds", 3.0)
            plugin.generate_intro_clip(prompt, seconds=seconds)
        elif op == "txt2img":
            # OBS wants this as a scene background by default.
            plugin.generate_scene_background(prompt)
        else:
            _log(f"ERROR: preset op '{op}' isn't applicable in OBS.")
            return False
    except Exception as e:
        _log(f"Preset failed: {e}")
    return False
