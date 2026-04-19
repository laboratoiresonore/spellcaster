"""Markers → Shots

Walks every timeline marker and turns each into a draft shot on the
Guild. The marker's note becomes the shot's prompt; the marker's
color maps to shot.color_label; the marker's duration (if present)
becomes target_duration_s. For each marker we grab the frame at that
timecode as the shot's reference image.

Editorial workflow this enables:
  1. Scrub the timeline, hit M to drop a marker wherever you want a
     VFX shot.
  2. Type the VFX description as the marker note — that becomes the
     prompt.
  3. Optionally set a marker duration — the shot inherits that length.
  4. Colour-code markers: red = v2v VFX, green = i2v extension, etc.
     Colours come through as shot labels in the Guild UI.
  5. Run this script. Every marker becomes a shot, all grouped under
     one scene. Open the Guild, pick presets, render.

Menu: Workspace > Scripts > Spellcaster > Markers → Shots
"""
from __future__ import annotations

import os
import sys
import base64
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


# Map Resolve marker colours to Spellcaster colour labels. Resolve's
# palette is richer than the 6-colour Shotboard set, so several
# Resolve hues collapse to the same label. Chosen so editors using
# the common Red/Blue/Green triad land on the matching Shotboard
# colours without thinking about it.
_COLOR_MAP = {
    "Red":        "red",
    "Rose":       "red",
    "Pink":       "red",
    "Yellow":     "yellow",
    "Sand":       "yellow",
    "Cream":      "yellow",
    "Green":      "green",
    "Mint":       "green",
    "Lemon":      "green",
    "Blue":       "blue",
    "Sky":        "blue",
    "Navy":       "blue",
    "Cyan":       "blue",
    "Purple":     "purple",
    "Lavender":   "purple",
    "Fuchsia":    "purple",
    "Orange":     "orange",
    "Chocolate":  "orange",
    "Cocoa":      "orange",
}


def main() -> int:
    guild = _sc.guild_or_die()
    from spellcaster_api import GuildError
    from resolve_helpers import (
        get_current_project, get_current_timeline,
        capture_frame_at_playhead, show_message,
    )

    timeline = get_current_timeline()
    project = get_current_project()
    if not (timeline and project):
        show_message("Spellcaster",
                     "No timeline is active. Open one first.")
        return 1

    try:
        markers = timeline.GetMarkers() or {}
    except Exception:
        markers = {}
    if not markers:
        show_message("Spellcaster",
                     "No timeline markers found.\n\n"
                     "Scrub to a frame, hit M to drop a marker, then type "
                     "a VFX description as the marker note. Markers are "
                     "how this script knows WHERE and WHAT to render.")
        return 0

    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
    except Exception:
        fps = 24.0
    try:
        timeline_name = timeline.GetName() or "Untitled"
    except Exception:
        timeline_name = "Untitled"

    # Resolve returns GetMarkers() as {frameId: {"color", "note", "name",
    # "duration", "customData"}}. Preserve timeline order.
    marker_items = sorted(markers.items(), key=lambda kv: int(kv[0]))

    # Cap reference-still captures so a 100-marker timeline doesn't
    # freeze Resolve for minutes. Rest ship without a ref image.
    _REF_CAP = 30
    created = 0
    ref_count = 0
    failures: list[str] = []

    for frame_id, m in marker_items:
        try:
            frame_id = int(frame_id)
        except (TypeError, ValueError):
            continue
        note = (m.get("note") or m.get("name") or "").strip()
        if not note:
            # Markers without notes become generic "Marker @ TC" shots.
            # Editors who don't write notes still get a place-holder to
            # fill in later via the Guild UI.
            note = ""
        color = _COLOR_MAP.get(m.get("color", ""), "")
        duration_frames = int(m.get("duration", 0) or 0)
        target_duration_s = (duration_frames / fps) if duration_frames > 0 else None

        # Format timecode for title + notes
        hh = int(frame_id / fps // 3600)
        mm = int((frame_id / fps) % 3600 // 60)
        ss = int((frame_id / fps) % 60)
        ff = int(frame_id % int(round(fps)))
        tc = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

        title = (note.split(".")[0].split(",")[0][:50]
                  or f"Marker @ {tc}")

        # Optional ref-frame capture (cap to _REF_CAP)
        ref_b64 = None
        if ref_count < _REF_CAP:
            try:
                timeline.SetCurrentTimecode(tc)
                png_path = capture_frame_at_playhead()
                if png_path and os.path.isfile(png_path):
                    with open(png_path, "rb") as f:
                        ref_b64 = base64.b64encode(f.read()).decode("ascii")
                    ref_count += 1
                    try:
                        os.unlink(png_path)
                    except Exception:
                        pass
            except Exception:
                pass

        # Build and POST the shot. We reuse the same
        # /api/video/import-timeline endpoint from R83 — it accepts a
        # cohort of clip records, creates shots in a new scene, and
        # returns the whole batch. One script → one scene.
        # But import-timeline expects clip shape; easier to just create
        # one shot at a time via /api/video/shots.
        try:
            extras: dict = {}
            if color:
                extras["color_label"] = color
            if target_duration_s:
                extras["target_duration_s"] = target_duration_s
            payload_notes = (f"R93: from marker @ {tc} on '{timeline_name}'"
                              + (f" (duration {duration_frames} frames)"
                                 if duration_frames else ""))
            shot = guild.create_shot(
                title=title,
                prompt=note,
                preset="wan22_i2v_lightning",
                reference_png=(base64.b64decode(ref_b64)
                                if ref_b64 else None),
                notes=payload_notes,
                extras=extras,
            )
            if shot.get("id") or shot.get("shot_id"):
                created += 1
        except GuildError as e:
            failures.append(f"{tc}: {e}")

    lines = [
        f"Markers → Shots complete.",
        "",
        f"Timeline: {timeline_name}",
        f"  • {len(marker_items)} markers scanned",
        f"  • {created} shots created",
        f"  • {ref_count} ref frames grabbed (cap {_REF_CAP})",
    ]
    if failures:
        lines.append(f"  • {len(failures)} failed")
        for f in failures[:5]:
            lines.append(f"     ✗ {f}")
    lines.append("")
    lines.append("Open the Guild to edit prompts / pick presets. "
                  "Colours carried over from marker colours.")
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
