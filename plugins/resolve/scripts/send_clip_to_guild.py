"""Send Selected Clip to Spellcaster — create a Guild shot from a
timeline clip's first frame.

Typical VFX workflow:
  1. Place the playhead on (or select) a clip you want to restyle
     ("burn this hero's cape with fire", "turn this dusk into dawn",
     "make this alley match the wizard's tower scene").
  2. Run this script.
  3. Type a prompt.
  4. A new draft shot lands on the Guild with that clip's first frame
     as reference image. Pick a preset in the Guild UI — today that
     means Wan i2v or LTX2 — and render. The generated clip
     auto-imports into the Media Pool when it's done.

R86 will add specific "VFX over footage" presets (Wan/LTX2 v2v-with-
mask, first-last-frame continuation, etc.) so this script can queue
renders directly.

Menu: Workspace > Scripts > Spellcaster > Send Clip to Spellcaster
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
    """Return the TimelineItem on V1 currently under the playhead, or None."""
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
        get_current_timeline, capture_frame_at_playhead,
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
        clip_name = item.GetName() or ""
    except Exception:
        clip_name = ""

    prompt = prompt_text(
        "Send to Spellcaster",
        f"Describe the VFX / restyle for '{clip_name}':",
        default="",
    )
    if prompt is None:
        return 0

    png_path = capture_frame_at_playhead()
    if not png_path or not os.path.exists(png_path):
        show_message("Spellcaster",
                     "Couldn't grab a still at the playhead.\n\n"
                     "Tip: switch to the Color page first — its Grab Still is "
                     "the most reliable path.")
        return 1

    try:
        with open(png_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read the still:\n{e}")
        return 1

    title = (prompt.strip().split(".")[0].split(",")[0][:50]
              or clip_name[:50]
              or "clip VFX")
    try:
        shot = guild.create_shot(
            title=title,
            prompt=prompt or "subtle gentle motion",
            preset="wan22_i2v_lightning",
            reference_png=png_bytes,
            notes=(f"From Resolve clip '{clip_name}' — VFX request. "
                    f"Change preset in Guild UI if Wan i2v isn't the "
                    f"right fit for this clip."),
        )
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected the shot:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id", "")
    show_message(
        "Spellcaster",
        f"Draft shot created — '{title}' (id {shot_id[:8]}).\n\n"
        f"Open the Guild UI (Workspace > Scripts > Spellcaster > "
        f"Open Guild UI) to pick the right preset and hit Render. "
        f"Or run 'Render All Drafts' to queue with the default "
        f"Wan i2v preset.",
    )

    try:
        os.unlink(png_path)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
