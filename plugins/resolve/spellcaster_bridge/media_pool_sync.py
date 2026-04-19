"""Shot → Resolve media pool synchronization.

When the SSEClient reports a shot is `ready`, this module:
  1. Downloads the mp4 to a local cache folder.
  2. Imports it into the Media Pool under `<target_bin>/<date>/`.
  3. Attaches a Spellcaster metadata marker to the imported clip.
  4. Optionally appends the clip to the "Spellcaster Live" timeline.

Idempotent: if the same shot_id comes through twice (e.g. SSE reconnect),
we don't import twice — we keep a local cache of shot_id -> MediaPoolItem.
"""

from __future__ import annotations

import datetime
import os
import sys
import threading

from spellcaster_api import GuildClient  # type: ignore
from resolve_helpers import (  # type: ignore
    ensure_bin, import_video, append_to_current_timeline,
    get_current_project, get_media_pool, add_spellcaster_marker,
)


class MediaPoolSync:
    """Thread-safe shot importer."""

    def __init__(self, guild: GuildClient, config):
        self.guild = guild
        self.config = config
        self._imported: dict[str, object] = {}  # shot_id -> MediaPoolItem
        self._lock = threading.Lock()
        self._cache_dir = self._init_cache_dir()
        self._events: list[str] = []   # human-readable log tail
        self._max_events = int(config.get("max_events_log", 20))

    def _init_cache_dir(self) -> str:
        base = os.path.expanduser("~/.spellcaster/resolve_cache/videos")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            base = os.path.join(os.getcwd(), ".spellcaster_cache")
            os.makedirs(base, exist_ok=True)
        return base

    # ── Public API ──────────────────────────────────────────────────

    def handle_event(self, event: dict):
        """Called by SSEClient for every event. We filter for ready shots.

        Two event shapes are accepted:

        1. Video-bridge SSE stream (`/api/video/events`) — emits a single
           `shot-update` event whenever a Shot mutates. The `data` dict
           carries the full shot record; we only act when status=='ready'.

        2. Cross-interface bus (`/api/events/stream`) — older shot.*
           style events that some integrations might still emit. Kept as
           a fallback so a mixed-old/new server doesn't skip imports.
        """
        data = event.get("data") or {}
        # SSE responses use `event:` field from the stream; internally
        # iterators store it under both "event" and "kind". Accept both.
        event_name = event.get("event") or event.get("kind") or ""
        status = (data.get("status") or "").lower()
        shot_id = data.get("id") or data.get("shot_id")
        if not shot_id:
            return

        # Canonical: the video bridge emits `shot-update`. When status
        # flips to ready AND we have a video_path, import it.
        if event_name == "shot-update":
            if status == "ready" and data.get("video_path"):
                self._import_shot(data)
            elif status == "failed":
                self._log(f"Shot failed: {data.get('title','?')} — "
                          f"{data.get('error','?')[:80]}")
            return

        # Fallback kinds (legacy / cross-interface bus shape)
        if event_name in ("shot.ready", "shot.status", "shot.updated",
                          "shot.added"):
            if status == "ready":
                self._import_shot(data)
        elif event_name == "shot.removed":
            self._forget_shot(shot_id)

    @property
    def events_tail(self) -> list[str]:
        return list(self._events)

    def imported_count(self) -> int:
        return len(self._imported)

    # ── Internals ────────────────────────────────────────────────────

    def _import_shot(self, shot: dict):
        shot_id = shot.get("id") or shot.get("shot_id")
        if not shot_id:
            return
        with self._lock:
            if shot_id in self._imported:
                return
        if not self.config.get("auto_import", True):
            self._log(f"Shot ready but auto_import=false: {shot.get('title','?')}")
            return

        # The SSE `shot-update` event ships only the mutated fields, so
        # when the handoff is sparse we pull the canonical record. That
        # gives us the full title/prompt/preset/scene_id/etc. to stamp
        # into the Resolve clip metadata.
        needs_full_record = not all(
            k in shot for k in ("title", "prompt", "preset"))
        if needs_full_record:
            try:
                canonical = self.guild.get_shot(shot_id)
                if canonical:
                    # Merge: canonical data fills gaps; SSE fields win
                    # (they're the freshest status/video_path)
                    merged = dict(canonical)
                    merged.update(shot)
                    shot = merged
            except Exception:
                pass  # fall through with whatever the SSE gave us

        dest = os.path.join(self._cache_dir, f"{shot_id}.mp4")
        if not os.path.exists(dest):
            ok = self.guild.download_shot_video(shot_id, dest)
            if not ok:
                self._log(f"Download failed for {shot.get('title','?')} ({shot_id})")
                return

        # Build the bin path: <target_bin>/<YYYY-MM-DD>
        bin_parts = [self.config.get("target_bin", "Spellcaster")]
        if self.config.get("bin_date_subfolder", True):
            bin_parts.append(datetime.date.today().isoformat())

        item = import_video(dest, target_bin_parts=bin_parts)
        if item is None:
            self._log(f"Import rejected for {shot.get('title','?')}")
            return

        with self._lock:
            self._imported[shot_id] = item

        # Attach metadata as a marker on the clip itself (frame 0 of the clip)
        # For MediaPoolItems, markers attach via SetClipProperty fallback; for
        # TimelineItems we add markers. We try both.
        self._attach_metadata_marker(item, shot)

        # Optionally append to Spellcaster Live timeline
        if self.config.get("live_timeline", False):
            self._append_to_live_timeline(item, shot)

        self._log(f"Imported {shot.get('title','?')}")

    def _attach_metadata_marker(self, media_item, shot: dict):
        """Attach shot metadata to the MediaPoolItem.

        Writes every non-empty Shot field from the canonical model:
        id, title, prompt, negative, preset, backend, seed, scene_id,
        transition, duration_s, render_duration_s, notes, color_label.
        Resolve's SetMetadata silently refuses unknown keys so it's
        safe to attempt them all.
        """
        def _str_or_empty(v):
            return "" if v is None else str(v)

        payload = {
            "Spellcaster ShotID":      _str_or_empty(shot.get("id")),
            "Spellcaster Title":       _str_or_empty(shot.get("title"))[:120],
            "Spellcaster Prompt":      _str_or_empty(shot.get("prompt"))[:500],
            "Spellcaster Negative":    _str_or_empty(shot.get("negative"))[:300],
            "Spellcaster Preset":      _str_or_empty(shot.get("preset")),
            "Spellcaster Backend":     _str_or_empty(shot.get("backend")),
            "Spellcaster Seed":        _str_or_empty(shot.get("seed")),
            "Spellcaster SceneID":     _str_or_empty(shot.get("scene_id")),
            "Spellcaster Transition":  _str_or_empty(shot.get("transition", "cut")),
            "Spellcaster Duration":    _str_or_empty(shot.get("duration_s")),
            "Spellcaster RenderTime":  _str_or_empty(shot.get("render_duration_s")),
            "Spellcaster Notes":       _str_or_empty(shot.get("notes"))[:200],
            "Spellcaster Label":       _str_or_empty(shot.get("color_label")),
        }
        for k, v in payload.items():
            if not v:
                continue
            try:
                media_item.SetMetadata(k, v)
            except Exception:
                # Resolve builds vary on accepted key set — silent skip
                pass

    def _append_to_live_timeline(self, media_item, shot: dict):
        """Append the imported clip to the 'Spellcaster Live' timeline,
        creating it if it doesn't exist."""
        project = get_current_project()
        mp = get_media_pool()
        if not (project and mp):
            return
        target_name = self.config.get("live_timeline_name", "Spellcaster Live")

        # Find existing timeline by name
        live_tl = None
        try:
            count = project.GetTimelineCount()
            for i in range(1, count + 1):
                tl = project.GetTimelineByIndex(i)
                if tl and tl.GetName() == target_name:
                    live_tl = tl
                    break
        except Exception:
            pass

        if live_tl is None:
            try:
                live_tl = mp.CreateEmptyTimeline(target_name)
            except Exception:
                return

        try:
            project.SetCurrentTimeline(live_tl)
            timeline_items = mp.AppendToTimeline([media_item]) or []
        except Exception:
            return

        # Add marker to the freshly appended timeline item
        if timeline_items:
            add_spellcaster_marker(
                timeline_items[0],
                shot_id=shot.get("id", ""),
                prompt=shot.get("prompt", ""),
                preset=shot.get("preset", ""),
                seed=shot.get("seed"),
                backend=shot.get("backend", ""),
            )

    def _forget_shot(self, shot_id: str):
        with self._lock:
            self._imported.pop(shot_id, None)

    def _log(self, msg: str):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        self._events.append(line)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        print(f"[Spellcaster Bridge] {line}")
