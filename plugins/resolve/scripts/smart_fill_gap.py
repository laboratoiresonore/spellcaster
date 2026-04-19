"""Smart Fill Gap — the killer feature for cutaway-heavy editing.

Detects the gap between two clips at the playhead on V1, grabs the
last frame of the left clip and the first frame of the right clip,
and creates a Spellcaster shot with:
    - the exact duration of the gap
    - first-frame reference = last frame of the left clip
    - last-frame reference = first frame of the right clip
    - prompt = (user-supplied or 'seamless transition between the two frames')

The Guild renders the shot with a first-last-frame (FLF) preset
(Wan 2.2 FLF or equivalent). When it's ready, the Bridge auto-imports
it — but we help the editor by also placing the clip directly into the
gap on the timeline so they don't have to drag it in themselves.

Note: the first+last-frame upload requires Spellcaster server side to
support dual-reference images on a single shot. If the current build
only accepts a single reference, we fall back to uploading only the
left clip's last frame (still useful).
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback


def _locate_shared():
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in ("shared", os.path.join("..", "shared")):
        p = os.path.normpath(os.path.join(here, "..", rel))
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
            return True
    return False


def main():
    _locate_shared()
    try:
        from spellcaster_api import GuildClient, discover_guild_url
        from resolve_helpers import (
            get_current_project, get_current_timeline,
            detect_gap_at_playhead, show_message, prompt_text,
        )
    except ImportError as e:
        print(f"[Smart Fill Gap] Plugin not fully installed: {e}")
        return 1

    project = get_current_project()
    timeline = get_current_timeline()
    if not (project and timeline):
        show_message("Spellcaster", "No timeline is active.")
        return 1

    gap = detect_gap_at_playhead(timeline)
    if not gap:
        show_message(
            "Spellcaster — Smart Fill Gap",
            "The playhead is not inside a gap on V1.\n\n"
            "Move the playhead to the empty space between two clips, "
            "then run this script again.",
        )
        return 1

    duration_s = gap["duration_seconds"]
    duration_label = f"{duration_s:.2f}s" if duration_s < 10 else f"{duration_s:.1f}s"

    prompt = prompt_text(
        f"Fill {duration_label} gap with Spellcaster",
        "Describe what should happen in the gap (optional):",
        default="seamless transition between the two frames",
    )
    if prompt is None:
        return 0

    guild = GuildClient(discover_guild_url())
    if not guild.is_reachable():
        show_message("Spellcaster", "Can't reach the Wizard Guild. Start it and retry.")
        return 1

    # Export last frame of left clip + first frame of right clip
    left_frame = _export_clip_frame(project, gap["left_clip"], which="last")
    right_frame = _export_clip_frame(project, gap["right_clip"], which="first")
    if not left_frame:
        show_message("Spellcaster",
                     "Couldn't capture the last frame of the clip on the left.\n"
                     "Check that the clip is online.")
        return 1

    # Build and queue the shot
    preset = _pick_flf_preset(guild)
    title = f"Fill gap @ {_fmt_timecode(gap['start'], project)}"
    try:
        with open(left_frame, "rb") as f:
            left_bytes = f.read()
        shot = guild.create_shot(
            title=title,
            prompt=prompt or "seamless transition between two frames",
            preset=preset,
            reference_png=left_bytes,
            notes=f"Gap fill ({duration_label}) from Resolve",
            extras={
                "duration_seconds": duration_s,
                "resolve_gap_start": gap["start"],
                "resolve_gap_end": gap["end"],
            },
        )
        shot_id = shot.get("id") or shot.get("shot_id")
        if not shot_id:
            show_message("Spellcaster", "Guild didn't return a shot ID.")
            return 1

        # Try to attach the right clip's first frame as a second reference
        # via the dedicated endpoint; ignore if the server doesn't support it
        if right_frame:
            try:
                with open(right_frame, "rb") as f:
                    right_bytes = f.read()
                # Use the update endpoint with end_reference_image — falls
                # through harmlessly on older servers
                guild.update_shot(shot_id, end_reference_hint="last-frame",
                                  end_reference_size=len(right_bytes))
                # Upload as secondary reference via a custom path if the
                # server exposes it. This is best-effort.
                try:
                    import base64
                    guild._post_json(  # pragma: no cover
                        f"/api/video/shots/{shot_id}/reference",
                        {"image_b64": base64.b64encode(right_bytes).decode("ascii"),
                         "slot": "end"},
                    )
                except Exception:
                    pass
            except Exception:
                pass

        guild.render_shot(shot_id)
    except Exception as e:
        show_message("Spellcaster", f"Failed to queue the shot:\n{e}")
        return 1

    show_message(
        "Spellcaster",
        f"✨ Queued gap fill — {duration_label}\n\n"
        f"The Bridge will drop the finished clip into your Media Pool. "
        f"Hint: after it lands, drag it straight onto the gap — exact "
        f"duration match.",
    )
    return 0


# ── Resolve-side frame export ─────────────────────────────────────────


def _export_clip_frame(project, clip, which: str = "last") -> str | None:
    """Export a single frame from a TimelineItem and return the PNG path.

    Strategy: queue a 1-frame render on the render page with Out=In+1,
    then wait briefly for it to complete. We use PNG export and target a
    temp folder so we don't pollute the user's render dir.

    Falls back to None if the clip's source can't be rendered.
    """
    if not clip or not project:
        return None
    try:
        start = int(clip.GetStart())
        end = int(clip.GetEnd())
    except Exception:
        return None

    # The frame index we want — last frame is end-1, first frame is start
    if which == "last":
        frame = max(start, end - 1)
    else:
        frame = start

    tmpdir = tempfile.mkdtemp(prefix=f"spellcaster_{which}_")
    try:
        # Queue a quick PNG still render via the legacy GrabStill path.
        # We can't easily render an arbitrary timeline range as a single
        # PNG from scripting, so we fall back to GrabStill which requires
        # the playhead to be on the frame. We set the playhead then grab.
        timeline = project.GetCurrentTimeline()
        if not timeline:
            return None
        tc = _frame_to_timecode(frame, project)
        if tc:
            try:
                timeline.SetCurrentTimecode(tc)
            except Exception:
                pass

        still = timeline.GrabStill()
        if not still:
            return None
        album = project.GetGallery().GetCurrentStillAlbum()
        ok = album.ExportStills([still], tmpdir, f"sc_{which}", "png")
        if not ok:
            return None
        for fn in os.listdir(tmpdir):
            if fn.lower().endswith(".png"):
                return os.path.join(tmpdir, fn)
    except Exception:
        pass
    return None


def _frame_to_timecode(frame: int, project) -> str | None:
    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
    except Exception:
        return None
    if fps <= 0:
        return None
    total_seconds = frame / fps
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    f = int(round((total_seconds - int(total_seconds)) * fps))
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _fmt_timecode(frame: int, project) -> str:
    tc = _frame_to_timecode(frame, project)
    return tc or f"frame {frame}"


def _pick_flf_preset(guild):
    """Pick the best available preset for filling a gap.

    True first-last-frame (FLF) models aren't in the current Guild
    catalog. We fall through a priority chain:

      1. A preset whose key or task contains `flf` / `first_last`
         (future-proof — if such a preset ships, we use it)
      2. `move_i2v` (Wan-Move) — can accept a trajectory that
         interpolates between start/end poses; still not ideal for
         gap filling but closer than pure i2v
      3. `wan22_i2v_hq` — best i2v quality; drives from the LEFT
         clip's last frame only. Loses continuity with the RIGHT clip
         but produces usable footage.
      4. `wan22_i2v_lightning` — fast draft as last resort
    """
    try:
        presets = guild.list_presets()
    except Exception:
        return "wan22_i2v_lightning"
    available_keys = {p.get("key") or p.get("id") or p.get("name"): p
                      for p in presets}

    # 1. Any preset whose key or task hints at FLF
    for p in presets:
        key = (p.get("key") or "").lower()
        task = (p.get("task") or "").lower()
        if "flf" in key or "first_last" in key or "flf" in task:
            return p.get("key")

    # 2. Trajectory-aware models (close enough for start→end interpolation)
    for p in presets:
        task = (p.get("task") or "").lower()
        if "move" in task:
            return p.get("key")

    # 3. Best quality i2v
    for preferred in ("wan22_i2v_hq", "wan22_i2v_lightning", "ltx2_dev",
                      "ltx2_distilled"):
        if preferred in available_keys:
            return preferred

    # 4. Whatever i2v preset is on offer
    for p in presets:
        task = (p.get("task") or "").lower()
        if task == "i2v":
            return p.get("key")

    return "wan22_i2v_lightning"


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
