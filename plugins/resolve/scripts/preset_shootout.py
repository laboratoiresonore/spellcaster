"""Preset Shootout → same prompt, same reference, different presets

Benchmarks multiple i2v presets against a single clip so the editor
can pick the right engine for their look/speed tradeoff. Creates one
shot per available i2v preset (up to 4), all using the same first
frame and prompt. Render kicks off immediately; compare MP4s in the
Media Pool as they land.

Default preset set (takes what's installed):
  • wan22_i2v_lightning   — fast draft, low VRAM
  • wan22_i2v_hq          — quality finals
  • ltx2_image_to_video   — LTX alternative
  • wan_move_i2v          — if installed

Menu: Workspace > Scripts > 💎 Spellcaster > 💎 preset_shootout
"""
from __future__ import annotations

import os
import sys
import traceback

def _boot():
    try:
        d = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        if os.name == "nt":
            d = os.path.join(os.environ.get("APPDATA", ""),
                              "Blackmagic Design", "DaVinci Resolve",
                              "Support", "Fusion", "Scripts",
                              "Utility", "💎 Spellcaster")
        elif sys.platform == "darwin":
            d = os.path.expanduser(
                "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
                "/Fusion/Scripts/Utility/💎 Spellcaster")
        else:
            d = os.path.expanduser(
                "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/💎 Spellcaster")
    if d and d not in sys.path:
        sys.path.insert(0, d)
_boot()

import _spellcaster_common as _sc  # noqa: E402


def _find_clip_under_playhead():
    from resolve_helpers import (
        get_current_project, get_current_timeline, _parse_timecode,
    )
    timeline = get_current_timeline()
    project = get_current_project()
    if not (timeline and project):
        return None
    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
        tc = timeline.GetCurrentTimecode()
    except Exception:
        return None
    if not tc:
        return None
    hh, mm, ss, ff = _parse_timecode(tc)
    playhead = int(round(((hh * 3600 + mm * 60 + ss) * fps) + ff))
    try:
        items = timeline.GetItemListInTrack("video", 1) or []
    except Exception:
        return None
    for it in items:
        try:
            if int(it.GetStart()) <= playhead < int(it.GetEnd()):
                return it
        except Exception:
            continue
    return None


# Order of preference — the shootout picks up to 4 presets from this
# list, in this order, filtered to what the Guild has installed.
_SHOOTOUT_PRESETS = (
    "wan22_i2v_lightning",
    "wan22_i2v_hq",
    "ltx2_image_to_video",
    "wan_move_i2v",
)


def main() -> int:
    guild = _sc.guild_or_die()
    from spellcaster_api import GuildError
    from resolve_helpers import (
        get_current_timeline, capture_frame_at_playhead,
        show_message, prompt_text,
    )

    if not get_current_timeline():
        show_message("Spellcaster", "No timeline is active. Open one first.")
        return 1

    item = _find_clip_under_playhead()
    if not item:
        show_message("Spellcaster",
                     "Position the playhead over a clip on V1 first.")
        return 1

    try:
        clip_name = item.GetName() or "clip"
    except Exception:
        clip_name = "clip"

    prompt = prompt_text(
        "Preset Shootout",
        f"Describe what you want (same prompt runs through 3-4 i2v presets):\n"
        f"(reference = first frame of '{clip_name}')",
        default="",
    )
    if prompt is None:
        return 0
    prompt = (prompt or "").strip()
    if not prompt:
        show_message("Spellcaster", "Need a prompt.")
        return 1

    # Pick the installed subset
    try:
        presets = guild.list_presets()
    except Exception:
        presets = []
    available = {p.get("key"): p for p in presets if p.get("key")}
    entrants = [k for k in _SHOOTOUT_PRESETS if k in available][:4]
    if not entrants:
        show_message("Spellcaster",
                     "None of the target i2v presets are installed:\n"
                     + ", ".join(_SHOOTOUT_PRESETS))
        return 1

    png_path = capture_frame_at_playhead()
    if not png_path or not os.path.exists(png_path):
        show_message("Spellcaster",
                     "Couldn't grab the reference frame.")
        return 1
    try:
        with open(png_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read the still:\n{e}")
        return 1

    base_title = (prompt.split(".")[0].split(",")[0][:35] or clip_name[:35])
    created: list[tuple[str, str]] = []
    failures: list[str] = []

    for preset_key in entrants:
        try:
            shot = guild.create_shot(
                title=f"{base_title} [{preset_key.replace('_', '-')[:16]}]",
                prompt=prompt,
                preset=preset_key,
                reference_png=png_bytes,
                notes=(f"R109: preset shootout for '{clip_name}' — "
                        f"preset {preset_key}"),
            )
            sid = shot.get("id") or shot.get("shot_id") or ""
            if sid:
                created.append((sid, preset_key))
        except GuildError as e:
            failures.append(f"{preset_key}: {e}")

    # Fire all in parallel
    for sid, _ in created:
        try:
            guild.render_shot(sid)
        except Exception:
            pass

    try:
        os.unlink(png_path)
    except Exception:
        pass

    lines = [
        f"Preset shootout queued: {len(created)}/{len(entrants)} variants.",
        f"Prompt: {prompt[:80]}{'…' if len(prompt) > 80 else ''}",
        f"Reference: first frame of '{clip_name}'.",
        "",
    ]
    for sid, key in created:
        label = available[key].get("label", key)
        lines.append(f"  • {sid[:8]}  {label}")
    for f in failures:
        lines.append(f"  ✗ {f}")
    lines.append("")
    lines.append("Compare the MP4s in the Media Pool as they finish. "
                  "The fastest preset usually lands first.")
    show_message("Spellcaster", "\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
