"""Extend Clip → Wan i2v (continuation from the last frame)

Tail-extend a real clip with AI-generated continuation. Grabs the
LAST frame of the V1 clip under the playhead, uses it as the seed
for a Wan 2.2 i2v render, and asks for a continuation prompt.

The difference vs. Capture Timeline (walks whole timeline) and Send
Clip to Spellcaster (grabs FIRST frame): this one is purpose-built
for the "I need a few more seconds of this shot" case — the new clip
picks up exactly where the real footage ended.

Menu: Workspace > Scripts > Spellcaster > Extend Clip from Last Frame
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
                              "Utility", "Spellcaster")
        elif sys.platform == "darwin":
            d = os.path.expanduser(
                "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
                "/Fusion/Scripts/Utility/Spellcaster")
        else:
            d = os.path.expanduser(
                "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Spellcaster")
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


def main() -> int:
    guild = _sc.guild_or_die()
    from spellcaster_api import GuildError
    from resolve_helpers import (
        get_current_timeline, grab_last_frame_of_clip,
        show_message, prompt_text,
    )

    timeline = get_current_timeline()
    if not timeline:
        show_message("Spellcaster",
                     "No timeline is active. Open one first.")
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
        "Extend Clip — Continuation",
        f"What should happen AFTER '{clip_name}'?\n"
        f"(e.g. 'camera continues panning right, revealing a castle' "
        f"or 'subject turns and walks into frame')",
        default="",
    )
    if prompt is None:
        return 0

    # Grab the last frame. This jumps the playhead to the clip's
    # last frame before calling capture_frame_at_playhead — the
    # editor sees the playhead move briefly.
    png_path = grab_last_frame_of_clip(item)
    if not png_path or not os.path.exists(png_path):
        show_message("Spellcaster",
                     "Couldn't grab the last frame.\n\n"
                     "Tip: switch to the Color page first — its Grab Still "
                     "is the most reliable path.")
        return 1

    try:
        with open(png_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read the still:\n{e}")
        return 1

    # Pick best i2v preset available (same selection logic as
    # generate_from_playhead — keeps the choice consistent).
    preset = _pick_preset(guild)

    title = (prompt.strip().split(".")[0].split(",")[0][:50]
              or f"Extend {clip_name[:40]}")
    try:
        shot = guild.create_shot(
            title=title,
            prompt=prompt or "subtle continuation, maintaining motion",
            preset=preset,
            reference_png=png_bytes,
            notes=f"R92: tail-extension from last frame of '{clip_name}'.",
        )
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected the shot:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id", "")

    # Trigger render
    try:
        guild.render_shot(shot_id)
    except GuildError as e:
        show_message("Spellcaster",
                     f"Shot queued (id {shot_id[:8]}) but render failed to "
                     f"start:\n{e}")
        return 1

    show_message(
        "Spellcaster",
        f"Extension queued — '{title}' (id {shot_id[:8]}).\n\n"
        f"Seed: last frame of '{clip_name}'.\n"
        f"Preset: {preset}.\n\n"
        f"The generated continuation auto-imports into the Media Pool "
        f"when ready. Drop it onto the timeline right after the source "
        f"clip for a seamless tail.",
    )

    try:
        os.unlink(png_path)
    except Exception:
        pass
    return 0


def _pick_preset(guild) -> str:
    """Pick the fastest i2v preset available."""
    try:
        presets = guild.list_presets()
    except Exception:
        return "wan22_i2v_lightning"
    available = {p.get("key"): p for p in presets if p.get("key")}
    for preferred in ("wan22_i2v_lightning", "wan22_i2v_hq",
                      "ltx2_image_to_video", "ltx2_distilled"):
        if preferred in available:
            return preferred
    for p in presets:
        if (p.get("task") or "").lower() == "i2v":
            return p.get("key")
    return "wan22_i2v_lightning"


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
