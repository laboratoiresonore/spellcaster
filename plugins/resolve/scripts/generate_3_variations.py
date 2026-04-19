"""Generate 3 Variations → fan out from one prompt + reference

Creates three draft shots from the V1 clip under the playhead, all
using the same first-frame reference and the same user-typed prompt,
but with three different seeds. Editor compares in the Media Pool
and keeps the best. This is the fastest "one idea, many executions"
loop for VFX exploration.

Every script that creates a shot picks a fresh seed automatically
if none is specified, so this is just three calls to create_shot in
a row — no special Guild support needed.

Menu: Workspace > Scripts > Spellcaster > Generate 3 Variations
"""
from __future__ import annotations

import os
import sys
import random
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
        "Generate 3 Variations",
        f"Describe what you want (1 prompt → 3 seeds):\n"
        f"(reference = first frame of '{clip_name}')",
        default="",
    )
    if prompt is None:
        return 0
    prompt = (prompt or "").strip()
    if not prompt:
        show_message("Spellcaster", "Need a prompt.")
        return 1

    png_path = capture_frame_at_playhead()
    if not png_path or not os.path.exists(png_path):
        show_message("Spellcaster",
                     "Couldn't grab the reference frame. "
                     "Switch to the Color page first and retry.")
        return 1

    try:
        with open(png_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read the still:\n{e}")
        return 1

    # Pick a solid i2v preset
    try:
        presets = guild.list_presets()
    except Exception:
        presets = []
    available = {p.get("key"): p for p in presets if p.get("key")}
    preset_key = "wan22_i2v_lightning"
    for preferred in ("wan22_i2v_lightning", "wan22_i2v_hq",
                      "ltx2_image_to_video"):
        if preferred in available:
            preset_key = preferred
            break

    base_title = (prompt.split(".")[0].split(",")[0][:40] or clip_name[:40])
    seeds = [random.randint(0, 2**31 - 1) for _ in range(3)]
    created: list[tuple[str, int]] = []
    failures: list[str] = []

    for i, seed in enumerate(seeds, start=1):
        try:
            shot = guild.create_shot(
                title=f"{base_title} (v{i})",
                prompt=prompt,
                preset=preset_key,
                seed=seed,
                reference_png=png_bytes,
                notes=f"R98: variation {i}/3 of '{clip_name}', seed={seed}",
            )
            shot_id = shot.get("id") or shot.get("shot_id", "")
            if shot_id:
                created.append((shot_id, seed))
        except GuildError as e:
            failures.append(f"v{i}: {e}")

    # Kick off renders immediately so all three run in parallel where
    # the backend supports it.
    for shot_id, _ in created:
        try:
            guild.render_shot(shot_id)
        except Exception:
            pass

    try:
        os.unlink(png_path)
    except Exception:
        pass

    lines = [f"Queued {len(created)}/3 variations of '{base_title}'.", ""]
    for i, (sid, seed) in enumerate(created, start=1):
        lines.append(f"  v{i}: {sid[:8]}  seed={seed}")
    for f in failures:
        lines.append(f"  ✗ {f}")
    lines.append("")
    lines.append(f"Preset: {preset_key}. Compare the three MP4s in the "
                  f"Media Pool as they land via the Bridge.")
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
