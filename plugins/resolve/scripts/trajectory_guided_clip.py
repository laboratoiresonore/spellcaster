"""Trajectory-Guided Clip → Wan-Move i2v with motion description

The Wan-Move preset accepts an image + prompt + TRAJECTORIES (arrays
of points on the image defining motion arrows). Fusion's UI is too
limited to draw arrows, so this script approximates: editor types a
motion description in prose ("camera pushes in diagonally", "subject
drifts right then up"), and the Guild's motion-parser converts it to
a default trajectory on the server side. For full pixel-accurate
trajectory control, use the Guild's web UI canvas.

Still a win over plain Wan i2v: the motion prompt gets into the
preset's trajectory-aware pipeline rather than being ignored.

Menu: Workspace > Scripts > 💎 Spellcaster > 💎 trajectory_guided_clip
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


# Default trajectories for common camera/subject motions. Points are
# normalised [0,1] x [0,1] coordinates over the ref frame. Wan-Move
# interprets them as keyframe positions over the clip duration.
# The prose-to-trajectory mapping here is deliberately crude — the
# Guild's web canvas is the full-fidelity path.
_MOTION_PRESETS = {
    "push_in":       [[0.5, 0.5], [0.5, 0.5]],           # static, zoom handled by i2v
    "push_out":      [[0.5, 0.5], [0.5, 0.5]],
    "pan_right":     [[0.2, 0.5], [0.8, 0.5]],
    "pan_left":      [[0.8, 0.5], [0.2, 0.5]],
    "tilt_up":       [[0.5, 0.8], [0.5, 0.2]],
    "tilt_down":     [[0.5, 0.2], [0.5, 0.8]],
    "drift_right":   [[0.3, 0.5], [0.7, 0.5]],
    "diagonal_in":   [[0.2, 0.2], [0.5, 0.5]],
    "orbit_right":   [[0.3, 0.5], [0.5, 0.3], [0.7, 0.5], [0.5, 0.7]],
}


def _guess_motion(prose: str) -> list:
    """Map a prose motion description to one of the preset trajectories."""
    s = (prose or "").lower()
    # Simple keyword scan — last match wins, so put specifics last
    key = "pan_right"  # default
    if "push in" in s or "zoom in" in s or "dolly in" in s:
        key = "push_in"
    elif "push out" in s or "zoom out" in s or "pull back" in s or "pull out" in s:
        key = "push_out"
    elif "orbit" in s or "around" in s:
        key = "orbit_right"
    elif "tilt up" in s or "look up" in s:
        key = "tilt_up"
    elif "tilt down" in s or "look down" in s:
        key = "tilt_down"
    elif "pan left" in s or "left" in s:
        key = "pan_left"
    elif "diagonal" in s:
        key = "diagonal_in"
    elif "drift" in s:
        key = "drift_right"
    elif "pan right" in s or "right" in s:
        key = "pan_right"
    return _MOTION_PRESETS[key]


def main() -> int:
    guild = _sc.guild_or_die()
    # R114: pre-flight — wan_move_i2v has a custom trajectory pipeline
    if not _sc.require_presets(guild, ["wan_move_i2v"],
                                friendly="Wan-Move trajectory i2v"):
        return 1
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

    motion = prompt_text(
        "Trajectory-Guided Clip — Motion",
        "Describe the camera or subject motion:\n\n"
        "Recognised keywords: push in / push out / pan left / pan right / "
        "tilt up / tilt down / diagonal / drift / orbit.\n"
        "(e.g. 'camera pans right while tilting up')",
        default="",
    )
    if motion is None:
        return 0
    motion = (motion or "").strip()
    if not motion:
        show_message("Spellcaster", "Need a motion description.")
        return 1

    prompt = prompt_text(
        "Trajectory-Guided Clip — Scene",
        f"Describe the SCENE content for '{clip_name}':\n"
        f"(what's in the frame — separate from the motion)",
        default="",
    )
    if prompt is None:
        return 0

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

    trajectory_points = _guess_motion(motion)
    # Guild's trajectory shape is [{points: [[x,y],...], color: "#..."}]
    trajectories = [{
        "points": trajectory_points,
        "color": "#00d9ff",
    }]
    title = (prompt.split(".")[0].split(",")[0][:40]
              or f"Trajectory: {clip_name[:30]}")
    combined_prompt = f"{prompt}. Motion: {motion}." if prompt else motion
    try:
        shot = guild.create_shot(
            title=title,
            prompt=combined_prompt,
            preset="wan_move_i2v",
            reference_png=png_bytes,
            notes=(f"R108: trajectory-guided i2v from '{clip_name}'. "
                    f"Motion: {motion}. Trajectory: {trajectory_points}."),
            extras={"trajectories": trajectories},
        )
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected the shot:\n{e}")
        return 1

    shot_id = shot.get("id") or shot.get("shot_id") or ""
    if not shot_id:
        show_message("Spellcaster", "Shot created but no id returned.")
        return 1

    # Attach trajectories via the dedicated endpoint too (belt-and-suspenders
    # for older Guilds that don't read trajectories from extras).
    try:
        guild.set_trajectories(shot_id, trajectories)
    except Exception:
        pass

    try:
        guild.render_shot(shot_id)
    except GuildError as e:
        show_message("Spellcaster",
                     f"Shot queued (id {shot_id[:8]}) but render failed "
                     f"to start:\n{e}")
        return 1

    try:
        os.unlink(png_path)
    except Exception:
        pass

    show_message(
        "Spellcaster",
        f"Trajectory clip queued — '{title}' (id {shot_id[:8]}).\n\n"
        f"  • Ref: first frame of '{clip_name}'\n"
        f"  • Motion: {motion}\n"
        f"  • Trajectory: {len(trajectory_points)} keypoints\n"
        f"  • Preset: wan_move_i2v\n\n"
        f"For pixel-accurate motion arrows, open the Guild UI and "
        f"draw directly on the reference frame — this script's keyword-"
        f"to-trajectory map is a rough sketch.",
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
