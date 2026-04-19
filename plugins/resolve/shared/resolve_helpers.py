"""DaVinci Resolve scripting helpers — shared by every plugin.

Wraps the raw Blackmagic API with ergonomic functions and None-guards.
The Resolve API is forgiving about missing objects (it returns None),
so we consolidate the boilerplate of chaining `Resolve() → Project →
Timeline → CurrentClip` into single calls that either return a useful
thing or None, never raise.

Usage from any Resolve Python script:

    from resolve_helpers import (
        get_resolve, get_current_project, get_current_timeline,
        import_video, add_marker, frame_at_playhead,
    )
    project = get_current_project()
    if project:
        ...
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any


# ─── Resolve bootstrap ──────────────────────────────────────────────────


def get_resolve():
    """Return the live Resolve API object, or None if we're not inside Resolve.

    The Resolve Python host pre-injects `resolve` as a module-level
    global. Workflow Integration plugins load in a context where
    `GetResolve()` is available via DaVinciResolveScript.
    """
    # 1. Preferred: the global injected by Resolve's script runner
    try:
        import DaVinciResolveScript as bmd  # type: ignore
        r = bmd.scriptapp("Resolve")
        if r:
            return r
    except Exception:
        pass
    # 2. Fusion context (Workflow Integration panels have `fu` / `fusion`)
    try:
        return fusion.GetResolve()  # type: ignore  # noqa: F821
    except Exception:
        pass
    # 3. Last resort — some launcher setups expose it as a plain global
    try:
        return resolve  # type: ignore  # noqa: F821
    except Exception:
        return None


def get_fusion():
    """Get the Fusion API object (for UI Manager etc)."""
    try:
        return fusion  # type: ignore  # noqa: F821
    except Exception:
        pass
    r = get_resolve()
    if r:
        try:
            return r.Fusion()
        except Exception:
            pass
    return None


def get_project_manager():
    r = get_resolve()
    return r.GetProjectManager() if r else None


def get_current_project():
    pm = get_project_manager()
    return pm.GetCurrentProject() if pm else None


def get_current_timeline():
    p = get_current_project()
    return p.GetCurrentTimeline() if p else None


def get_media_pool():
    p = get_current_project()
    return p.GetMediaPool() if p else None


# ─── Media pool helpers ─────────────────────────────────────────────────


def ensure_bin(path_parts: list[str]):
    """Walk/create a nested bin path in the Media Pool.

    path_parts = ["Spellcaster", "2026-04-18"] creates (or finds) that
    nested folder structure and returns the leaf folder object.
    """
    mp = get_media_pool()
    if not mp:
        return None
    try:
        root = mp.GetRootFolder()
    except Exception:
        return None
    current = root
    for name in path_parts:
        sub = _find_subfolder(current, name)
        if sub is None:
            mp.SetCurrentFolder(current)
            try:
                sub = mp.AddSubFolder(current, name)
            except Exception:
                return None
        current = sub
    return current


def _find_subfolder(folder, name: str):
    try:
        subs = folder.GetSubFolderList() or []
    except Exception:
        return None
    for s in subs:
        try:
            if s.GetName() == name:
                return s
        except Exception:
            pass
    return None


def import_video(file_path: str, target_bin_parts: list[str] | None = None):
    """Import a video file into the media pool. Optionally into a nested bin.

    Returns the first MediaPoolItem on success, None on failure.
    """
    mp = get_media_pool()
    if not mp:
        return None
    if target_bin_parts:
        target = ensure_bin(target_bin_parts)
        if target:
            mp.SetCurrentFolder(target)
    try:
        items = mp.ImportMedia([file_path])
    except Exception:
        items = None
    if items and len(items) > 0:
        return items[0]
    return None


def append_to_current_timeline(media_item):
    """Append a media pool item as a new clip at the end of the current timeline."""
    mp = get_media_pool()
    if not (mp and media_item):
        return None
    try:
        return mp.AppendToTimeline([media_item])
    except Exception:
        return None


# ─── Marker helpers (metadata round-trip) ───────────────────────────────


_SPELLCASTER_MARKER_COLOR = "Purple"
_SPELLCASTER_MARKER_PREFIX = "[SC]"


def add_spellcaster_marker(timeline_item, *, shot_id: str, prompt: str = "",
                           preset: str = "", seed: int | None = None,
                           backend: str = "", notes: str = "",
                           frame: int = 0, duration: int = 1) -> bool:
    """Attach a Spellcaster metadata marker to a TimelineItem.

    The marker note encodes all shot metadata as JSON so other plugins
    (Marker Round-Trip, Shotboard Sync) can round-trip it cleanly.
    """
    if not timeline_item:
        return False
    meta = {
        "shot_id": shot_id,
        "prompt": prompt,
        "preset": preset,
        "seed": seed,
        "backend": backend,
    }
    name = f"{_SPELLCASTER_MARKER_PREFIX} {prompt[:60] or shot_id}"
    # Resolve markers expect: frameId, color, name, note, duration, customData
    try:
        return bool(timeline_item.AddMarker(
            frame, _SPELLCASTER_MARKER_COLOR, name,
            json.dumps(meta), duration, shot_id,  # customData = shot_id for lookup
        ))
    except Exception:
        return False


def read_spellcaster_marker(timeline_item) -> dict | None:
    """Return the first Spellcaster marker payload on a timeline item, or None."""
    if not timeline_item:
        return None
    try:
        markers = timeline_item.GetMarkers() or {}
    except Exception:
        return None
    for frame, m in markers.items():
        if m.get("color") == _SPELLCASTER_MARKER_COLOR and m.get("note"):
            try:
                payload = json.loads(m["note"])
                if "shot_id" in payload:
                    payload["_frame"] = frame
                    return payload
            except Exception:
                continue
    return None


# ─── Playhead + frame capture ───────────────────────────────────────────


def frame_at_playhead(project=None, timeline=None) -> tuple[int, int] | None:
    """Return (timeline_frame, clip_frame) at the playhead, or None.

    The API gives us Timecode strings; we convert to frames. If the
    project framerate can't be read, returns None.
    """
    project = project or get_current_project()
    timeline = timeline or (project.GetCurrentTimeline() if project else None)
    if not timeline:
        return None
    try:
        tc = timeline.GetCurrentTimecode()
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
    except Exception:
        return None
    if not tc:
        return None
    hh, mm, ss, ff = _parse_timecode(tc)
    total = int(round(((hh * 3600 + mm * 60 + ss) * fps) + ff))
    return (total, total)  # clip frame == timeline frame at playhead


def _parse_timecode(tc: str) -> tuple[int, int, int, int]:
    # "HH:MM:SS:FF" or "HH:MM:SS;FF" (drop-frame separator)
    parts = tc.replace(";", ":").split(":")
    try:
        h, m, s, f = [int(p) for p in parts]
        return h, m, s, f
    except Exception:
        return 0, 0, 0, 0


def capture_frame_at_playhead() -> str | None:
    """Grab a PNG of the current Color-page still at the playhead.

    Uses Resolve's Gallery > Grab Still mechanism, which respects the
    current grade. Returns a local PNG path, or None on failure.

    Strategy:
      1. Grab a Gallery still at the playhead.
      2. Export that still as a PNG (`.dpx` fallback if PNG unsupported).
      3. Return the path.

    This is imperfect — Resolve's still export path is clunky — but it
    works without launching a full render. For the "Color-Graded Reference"
    plugin (Tier 2) we'll use AddRenderJob instead for full fidelity.
    """
    timeline = get_current_timeline()
    project = get_current_project()
    if not (timeline and project):
        return None

    gallery = None
    try:
        gallery = project.GetGallery()
    except Exception:
        pass
    if not gallery:
        return None

    try:
        album = gallery.GetCurrentStillAlbum()
        still = timeline.GrabStill()
        if not still:
            return None
        # Export as PNG to a temp dir. The API returns a filename prefix.
        tmpdir = tempfile.mkdtemp(prefix="spellcaster_still_")
        ok = album.ExportStills([still], tmpdir, "sc_still", "png")
        if not ok:
            return None
        # Find the emitted file — ExportStills names it sc_still*.png
        for fn in os.listdir(tmpdir):
            if fn.lower().endswith(".png"):
                return os.path.join(tmpdir, fn)
        return None
    except Exception:
        return None


# ─── Timeline gap detection ─────────────────────────────────────────────


def detect_gap_at_playhead(timeline=None) -> dict | None:
    """If the playhead is inside a gap between two clips on V1, return
    {"start": frame, "end": frame, "left_clip": item, "right_clip": item}.

    Returns None if we're on a clip or if the project is unavailable.
    """
    timeline = timeline or get_current_timeline()
    if not timeline:
        return None
    project = get_current_project()
    if not project:
        return None
    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
        tc = timeline.GetCurrentTimecode()
    except Exception:
        return None
    hh, mm, ss, ff = _parse_timecode(tc)
    playhead_frame = int(round(((hh * 3600 + mm * 60 + ss) * fps) + ff))

    try:
        items = timeline.GetItemListInTrack("video", 1) or []
    except Exception:
        return None

    left = None
    right = None
    for it in items:
        try:
            start = int(it.GetStart())
            end = int(it.GetEnd())
        except Exception:
            continue
        if end <= playhead_frame:
            if left is None or end > int(left.GetEnd()):
                left = it
        if start >= playhead_frame:
            if right is None or start < int(right.GetStart()):
                right = it

    if left and right:
        lstart = int(left.GetEnd())
        rstart = int(right.GetStart())
        if rstart > lstart:
            return {"start": lstart, "end": rstart,
                    "left_clip": left, "right_clip": right,
                    "duration_frames": rstart - lstart,
                    "duration_seconds": (rstart - lstart) / fps}
    return None


# ─── Timeline walker (capture for Shotboard import) ─────────────────────


def walk_timeline_clips(timeline=None, *, tracks: str = "V1") -> list[dict]:
    """R83: walk clips on the current timeline and return a list of dicts
    suitable for POST /api/video/import-timeline.

    `tracks` supports:
       "V1"  — only the first video track (default; matches editor intent)
       "all" — every video track (useful for multi-cam / VFX stacks)

    Each returned dict has:
       clip_name, track, start_frame, end_frame, duration_frames,
       spellcaster_shot_id (if the clip carries a [SC] marker),
       marker_meta (full JSON from the [SC] marker if present)
    """
    timeline = timeline or get_current_timeline()
    if not timeline:
        return []
    try:
        track_count = int(timeline.GetTrackCount("video") or 0)
    except Exception:
        track_count = 0
    if track_count <= 0:
        return []

    if tracks.lower() == "all":
        track_indices = range(1, track_count + 1)
    else:
        track_indices = [1] if track_count >= 1 else []

    out: list[dict] = []
    for tidx in track_indices:
        try:
            items = timeline.GetItemListInTrack("video", tidx) or []
        except Exception:
            continue
        for it in items:
            try:
                start = int(it.GetStart())
                end = int(it.GetEnd())
            except Exception:
                continue
            try:
                name = it.GetName() or ""
            except Exception:
                name = ""
            clip = {
                "clip_name": name,
                "track": tidx,
                "start_frame": start,
                "end_frame": end,
                "duration_frames": max(0, end - start),
            }
            # Look for a Spellcaster marker; round-trip its metadata
            meta = read_spellcaster_marker(it)
            if meta:
                clip["spellcaster_shot_id"] = meta.get("shot_id", "")
                clip["marker_meta"] = {
                    k: v for k, v in meta.items()
                    if k not in ("_frame",)
                }
            out.append(clip)
    return out


def grab_first_frame_of_clip(timeline_item) -> str | None:
    """Render a single PNG at the first frame of a TimelineItem.

    Uses the same Gallery still pipeline as capture_frame_at_playhead;
    quick and dirty, sufficient for "here's what this clip looks like"
    references. Returns a local PNG path, or None on failure.

    We don't bump the playhead before grabbing, because GrabStill grabs
    at the playhead position — the caller should JumpToTimecode first
    if they want a specific frame.
    """
    project = get_current_project()
    if not (project and timeline_item):
        return None
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return None
    # Move playhead to the clip's start
    try:
        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
        start_f = int(timeline_item.GetStart())
        hh = int(start_f / fps // 3600)
        mm = int((start_f / fps) % 3600 // 60)
        ss = int((start_f / fps) % 60)
        ff = int(start_f % int(round(fps)))
        tc = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
        timeline.SetCurrentTimecode(tc)
    except Exception:
        pass
    return capture_frame_at_playhead()


# ─── UI utilities (Fusion) ──────────────────────────────────────────────


def show_message(title: str, message: str):
    """Best-effort modal message box inside Resolve. Falls back to print."""
    fu = get_fusion()
    if fu:
        try:
            ui = fu.UIManager
            disp = fu.UIDispatcher(ui)
            win = disp.AddWindow({"WindowTitle": title, "Geometry": [800, 500, 420, 160]}, [
                ui.VGroup([
                    ui.Label({"Text": message, "WordWrap": True, "Alignment": {"AlignHCenter": True}}),
                    ui.HGap(0, 1.0),
                    ui.Button({"ID": "ok", "Text": "OK", "Geometry": [0, 0, 80, 28]}),
                ]),
            ])

            def _close(ev):
                disp.ExitLoop()

            win.On.ok.Clicked = _close
            win.On.Window.Close = _close
            win.Show()
            disp.RunLoop()
            win.Hide()
            return
        except Exception:
            pass
    print(f"[{title}] {message}")


def prompt_text(title: str, label: str, default: str = "") -> str | None:
    """Single-line text-input dialog. Returns the text or None if cancelled."""
    fu = get_fusion()
    if not fu:
        return None
    try:
        ui = fu.UIManager
        disp = fu.UIDispatcher(ui)
        result = {"value": None}
        win = disp.AddWindow({"WindowTitle": title, "Geometry": [800, 500, 460, 180]}, [
            ui.VGroup([
                ui.Label({"Text": label}),
                ui.LineEdit({"ID": "input", "Text": default}),
                ui.HGroup([
                    ui.Button({"ID": "cancel", "Text": "Cancel"}),
                    ui.Button({"ID": "ok", "Text": "OK"}),
                ]),
            ]),
        ])

        def _ok(ev):
            result["value"] = win.Find("input").Text
            disp.ExitLoop()

        def _cancel(ev):
            disp.ExitLoop()

        win.On.ok.Clicked = _ok
        win.On.cancel.Clicked = _cancel
        win.On.Window.Close = _cancel
        win.Show()
        disp.RunLoop()
        win.Hide()
        return result["value"]
    except Exception:
        return None
