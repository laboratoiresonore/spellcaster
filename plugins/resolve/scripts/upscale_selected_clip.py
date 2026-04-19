"""Upscale Selected Clip → SeedVR2 video upscaler

Sends the V1 clip under the playhead to the Guild for AI video
upscaling. Uses the SeedVR2 preset (temporally-consistent video
upscaler) already registered in WANGP_PRESETS. The upscaled clip
auto-imports into the Media Pool when ready.

Typical use: a Spellcaster-generated clip rendered at 768x512 needs
a delivery-ready 1920x1080 pass; or a degraded archive shot needs
enhancement before intercutting with modern footage.

Menu: Workspace > Scripts > Spellcaster > Upscale Selected Clip
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
        return (None, None)
    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
        tc = timeline.GetCurrentTimecode()
    except Exception:
        return (None, None)
    if not tc:
        return (None, None)
    hh, mm, ss, ff = _parse_timecode(tc)
    playhead = int(round(((hh * 3600 + mm * 60 + ss) * fps) + ff))
    try:
        items = timeline.GetItemListInTrack("video", 1) or []
    except Exception:
        return (None, None)
    for it in items:
        try:
            if int(it.GetStart()) <= playhead < int(it.GetEnd()):
                mp_item = it.GetMediaPoolItem()
                if not mp_item:
                    return (it, None)
                props = mp_item.GetClipProperty() or {}
                return (it, props.get("File Path", "") or "")
        except Exception:
            continue
    return (None, None)


def main() -> int:
    guild = _sc.guild_or_die()
    from spellcaster_api import GuildError
    from resolve_helpers import (
        get_current_timeline, show_message,
    )

    if not get_current_timeline():
        show_message("Spellcaster", "No timeline is active. Open one first.")
        return 1

    item, media_path = _find_clip_under_playhead()
    if not item:
        show_message("Spellcaster",
                     "Position the playhead over a clip on V1 first.")
        return 1
    if not media_path or not os.path.isfile(media_path):
        show_message("Spellcaster",
                     "Couldn't resolve the clip's source file.\n"
                     "Only file-backed clips work for upscaling.")
        return 1

    try:
        clip_name = item.GetName() or os.path.basename(media_path)
    except Exception:
        clip_name = os.path.basename(media_path)

    # Create shot with SeedVR2 preset. No prompt needed — upscaling
    # is content-agnostic. Title documents the source.
    try:
        shot = guild.create_shot(
            title=f"Upscale: {clip_name[:40]}",
            prompt="",
            preset="seedvr2_video_upscale",
            backend="comfyui",
            notes=f"R94: SeedVR2 upscale of '{clip_name}'.",
        )
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected shot creation:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id") or ""
    if not shot_id:
        show_message("Spellcaster", "Shot created but no id returned.")
        return 1

    # Stage input video
    try:
        staged = guild._post_json(
            f"/api/video/shots/{shot_id}/input-video",
            {"path": media_path},
            timeout=180.0,  # upscale inputs can be large
        )
    except GuildError as e:
        show_message("Spellcaster",
                     f"Shot created (id {shot_id[:8]}) but couldn't stage "
                     f"the clip:\n{e}")
        return 1

    staged_name = staged.get("staged_name", "")
    size_mb = (staged.get("size_bytes", 0) or 0) / 1048576.0
    show_message(
        "Spellcaster",
        f"Upscale queued — '{clip_name[:40]}' (id {shot_id[:8]}).\n\n"
        f"  • Source: {os.path.basename(media_path)} ({size_mb:.1f} MB)\n"
        f"  • Staged: {staged_name}\n"
        f"  • Preset: SeedVR2 video upscaler\n"
        f"  • Target: 1920x1080 (configurable in Guild UI)\n\n"
        f"Run 'Render All Drafts' to start. The 2x-4x upscale is "
        f"VRAM-heavy (12+ GB recommended) and slow — expect several "
        f"minutes per second of footage.",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
