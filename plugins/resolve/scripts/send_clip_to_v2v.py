"""Send Clip → VFX (LTX-2.3 FlowEdit v2v)

The headline VFX-on-real-footage flow. Takes the V1 clip under the
playhead, sends its SOURCE MEDIA FILE to the Guild, creates a draft
shot with the LTX FlowEdit v2v preset, and tags the shot with your
VFX description so it's ready to render. Editor picks up the rendered
output in the Media Pool via the Bridge's auto-import.

Compared to Send Clip to Spellcaster (which sends just a single
still, triggering a fresh i2v generation), this script preserves the
temporal structure of the real footage — ideal for style transfer,
object re-texture, or localized effects that need to follow the real
motion.

Menu: Workspace > Scripts > Spellcaster > Send Clip → VFX
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
    """Return (TimelineItem, media_file_path) for V1's clip at playhead."""
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
                path = props.get("File Path", "") or ""
                return (it, path)
        except Exception:
            continue
    return (None, None)


def main() -> int:
    guild = _sc.guild_or_die()
    # R114: pre-flight — LTX FlowEdit v2v preset must be on the Guild
    if not _sc.require_presets(guild, ["ltx2_v2v_flowedit"],
                                friendly="LTX-2.3 FlowEdit v2v"):
        return 1
    from spellcaster_api import GuildError
    from resolve_helpers import (
        get_current_timeline, show_message, prompt_text,
    )

    timeline = get_current_timeline()
    if not timeline:
        show_message("Spellcaster",
                     "No timeline is active. Open one first.")
        return 1

    item, media_path = _find_clip_under_playhead()
    if not item:
        show_message("Spellcaster",
                     "Position the playhead over a clip on V1 first.")
        return 1
    if not media_path or not os.path.isfile(media_path):
        show_message("Spellcaster",
                     "Couldn't resolve the clip's source media file.\n\n"
                     f"Reported path: {media_path!r}\n"
                     "Only file-backed clips work for v2v — compound clips, "
                     "Fusion comps, and generators don't have a source file.")
        return 1

    try:
        clip_name = item.GetName() or os.path.basename(media_path)
    except Exception:
        clip_name = os.path.basename(media_path)

    prompt = prompt_text(
        "Send Clip → VFX",
        f"Describe the VFX transformation for '{clip_name}':\n\n"
        f"(e.g. 'turn this into a van Gogh painting' or "
        f"'restyle as a moody noir night scene' — "
        f"the source stays the same, the look changes)",
        default="",
    )
    if prompt is None:
        return 0
    if not prompt.strip():
        show_message("Spellcaster",
                     "v2v needs a target description to transform toward. "
                     "Try again with a prompt.")
        return 1

    # Create the shot first (draft, backend=comfyui, preset=ltx2_v2v_flowedit)
    title = (prompt.strip().split(".")[0].split(",")[0][:50]
              or clip_name[:50]
              or "v2v VFX")
    try:
        shot = guild.create_shot(
            title=title,
            prompt=prompt,
            preset="ltx2_v2v_flowedit",
            backend="comfyui",
            notes=(f"R87: v2v VFX on '{clip_name}'. "
                    f"Source media: {os.path.basename(media_path)}."),
        )
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected shot creation:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id", "")
    if not shot_id:
        show_message("Spellcaster", "Shot created but no id returned.")
        return 1

    # Stage the video via the Guild → antenna → ComfyUI input dir path
    try:
        staged = guild._post_json(
            f"/api/video/shots/{shot_id}/input-video",
            {"path": media_path},
            timeout=120.0,
        )
    except GuildError as e:
        show_message("Spellcaster",
                     f"Shot created (id {shot_id[:8]}) but couldn't stage the "
                     f"video:\n{e}\n\n"
                     f"You can still render: open the Guild, set the shot's "
                     f"input_video override manually.")
        return 1

    staged_name = staged.get("staged_name", "") or ""
    size_mb = (staged.get("size_bytes", 0) or 0) / 1048576.0
    show_message(
        "Spellcaster",
        f"v2v shot queued — '{title}' (id {shot_id[:8]}).\n\n"
        f"  • Source: {os.path.basename(media_path)}  ({size_mb:.1f} MB)\n"
        f"  • Staged on ComfyUI as: {staged_name}\n"
        f"  • Preset: LTX-2.3 FlowEdit (skip_steps=4)\n\n"
        f"Run 'Render All Drafts' or 'Open Guild UI' to kick off the render. "
        f"Tweak skip_steps in the Guild UI if you want a subtler (2) or "
        f"heavier (8) transformation.",
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
