"""
Shotboard — persistent ordered list of video shots.

A Shot is the unit of creative work for video generation in Spellcaster.
Unlike a still image (which is atomic), a video "project" is a sequence
of shots, each of which may:

  - start from a reference image (or be pure text)
  - have a set of motion trajectories drawn on that image
  - carry a prompt, a backend preset choice, and any overrides
  - eventually produce an output video file
  - link forward/backward for continuity (last-frame → next-ref)

The Shotboard is intentionally *dumb*: it knows nothing about WanGP,
ComfyUI, or wizards.  It just stores, loads, and enforces ordering.

Persistence mirrors the existing ``session_state.json`` pattern used by
the Wizard Guild: a single JSON file in the Spellcaster user-data dir,
written atomically on every mutation so a kernel panic can't leave it
half-written.

Zero dependencies beyond stdlib.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger("spellcaster.shotboard")


SHOT_STATUSES = ("draft", "queued", "running", "ready", "failed")


# -----------------------------------------------------------------------------
# Data model
# -----------------------------------------------------------------------------

@dataclass
class Trajectory:
    """A single user-drawn motion path on a reference image.

    Point coords are in image-pixel space (origin top-left).  The
    CinematographerWizard emits these and Wan-Move / Wan-ATI consume
    them.  For backends that don't understand trajectories, they are
    simply ignored.
    """
    label: str = "path"
    # List of (x, y) points along the path
    points: List[List[float]] = field(default_factory=list)
    # Optional per-trajectory speed curve (length matches points - 1)
    speeds: Optional[List[float]] = None
    # Hex colour used for rendering in the UI
    colour: str = "#ff3366"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.speeds is None:
            d.pop("speeds", None)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trajectory":
        return cls(
            label=data.get("label", "path"),
            points=[list(p) for p in data.get("points", [])],
            speeds=data.get("speeds"),
            colour=data.get("colour", "#ff3366"),
        )


@dataclass
class Shot:
    """A single video shot on the storyboard.

    Identity:
      - id:           stable uuid
      - index:        ordered position in the board (0-based)
      - title:        short human label ("EXT. forest — day")

    Creative:
      - prompt:       text description
      - ref_image:    absolute path to the reference PNG/JPG, or None
      - trajectories: list of Trajectory instances

    Routing:
      - backend:      "wangp" | "comfyui" | "hybrid"
      - preset:       preset key (for wangp) or workflow name (for comfyui)
      - overrides:    any per-shot parameter overrides

    Output:
      - video_path:   absolute path to the generated mp4, or None
      - status:       one of SHOT_STATUSES
      - job_id:       backend-specific job handle while running
      - error:        last error message (only set when status="failed")
      - last_updated: unix epoch seconds
      - duration_s:   playback length hint (from the preset's fps/frames)

    Continuity:
      - carry_last_frame: if True, the ShotBoard will wire this shot's
        final frame as the *next* shot's ref_image when
        ``export_for_next()`` is called.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    index: int = 0
    title: str = ""
    prompt: str = ""
    ref_image: Optional[str] = None
    trajectories: List[Trajectory] = field(default_factory=list)
    backend: str = "wangp"
    preset: str = "wan22_i2v_lightning"
    overrides: Dict[str, Any] = field(default_factory=dict)
    video_path: Optional[str] = None
    status: str = "draft"
    job_id: Optional[str] = None
    error: Optional[str] = None
    last_updated: float = field(default_factory=time.time)
    duration_s: Optional[float] = None
    carry_last_frame: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["trajectories"] = [t.to_dict() if isinstance(t, Trajectory)
                             else t for t in self.trajectories]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Shot":
        trajs_raw = data.get("trajectories") or []
        trajs = [Trajectory.from_dict(t) if isinstance(t, dict) else t
                 for t in trajs_raw]
        # Drop unknown keys so old boards still load when schema grows
        known = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in data.items() if k in known}
        clean["trajectories"] = trajs
        return cls(**clean)

    def touch(self) -> None:
        self.last_updated = time.time()


# -----------------------------------------------------------------------------
# Store
# -----------------------------------------------------------------------------

class Shotboard:
    """Ordered, persistent list of Shot objects.

    The store is cheap enough that every mutation rewrites the whole
    file atomically — the expected size is tens of shots, not
    thousands.  This matches how ``session_state.json`` is handled
    elsewhere in Spellcaster.
    """

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._shots: List[Shot] = []
        self._load()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load the board from disk, tolerating missing / corrupt files."""
        if not os.path.isfile(self.path):
            self._shots = []
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Shotboard at %s is unreadable (%s); "
                        "starting empty", self.path, exc)
            self._shots = []
            return
        if not isinstance(raw, dict):
            log.warning("Shotboard %s: expected object at top level, "
                        "starting empty", self.path)
            self._shots = []
            return
        shots = raw.get("shots") or []
        self._shots = [Shot.from_dict(s) for s in shots if isinstance(s, dict)]
        self._reindex()

    def save(self) -> None:
        """Atomically persist the board."""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        payload = {
            "version": 1,
            "saved_at": time.time(),
            "shots": [s.to_dict() for s in self._shots],
        }
        # Write to a temp file in the same directory, then rename — so
        # if we crash mid-write, the original file is still intact.
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".shotboard.", suffix=".tmp",
            dir=os.path.dirname(self.path) or ".",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp_path, self.path)
        except Exception:
            # Make sure we don't leave litter
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._shots)

    def __iter__(self):
        return iter(self._shots)

    def all(self) -> List[Shot]:
        return list(self._shots)

    def get(self, shot_id: str) -> Optional[Shot]:
        for s in self._shots:
            if s.id == shot_id:
                return s
        return None

    def next_of(self, shot_id: str) -> Optional[Shot]:
        """Return the shot immediately after shot_id, or None."""
        for i, s in enumerate(self._shots):
            if s.id == shot_id and i + 1 < len(self._shots):
                return self._shots[i + 1]
        return None

    def previous_of(self, shot_id: str) -> Optional[Shot]:
        """Return the shot immediately before shot_id, or None."""
        for i, s in enumerate(self._shots):
            if s.id == shot_id and i > 0:
                return self._shots[i - 1]
        return None

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, shot: Optional[Shot] = None, **kwargs: Any) -> Shot:
        """Append a new shot. Pass either a Shot or keyword fields."""
        if shot is None:
            shot = Shot(**kwargs)
        shot.index = len(self._shots)
        shot.touch()
        self._shots.append(shot)
        self.save()
        return shot

    def update(self, shot_id: str, **fields: Any) -> Optional[Shot]:
        """Mutate an existing shot by id; ignores unknown fields."""
        shot = self.get(shot_id)
        if not shot:
            return None
        known = {f.name for f in Shot.__dataclass_fields__.values()}
        for key, val in fields.items():
            if key in known:
                setattr(shot, key, val)
        shot.touch()
        self.save()
        return shot

    def remove(self, shot_id: str) -> bool:
        """Drop a shot from the board. Returns True on success."""
        before = len(self._shots)
        self._shots = [s for s in self._shots if s.id != shot_id]
        if len(self._shots) == before:
            return False
        self._reindex()
        self.save()
        return True

    def reorder(self, ordered_ids: List[str]) -> None:
        """Reorder shots to match the given id sequence.

        Any shot ids missing from ``ordered_ids`` keep their relative
        order and are appended at the end — this prevents client-side
        bugs from silently dropping a shot.
        """
        by_id = {s.id: s for s in self._shots}
        new_list: List[Shot] = []
        seen: set = set()
        for sid in ordered_ids:
            s = by_id.get(sid)
            if s and sid not in seen:
                new_list.append(s)
                seen.add(sid)
        for s in self._shots:
            if s.id not in seen:
                new_list.append(s)
        self._shots = new_list
        self._reindex()
        self.save()

    def _reindex(self) -> None:
        for i, s in enumerate(self._shots):
            s.index = i

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def mark_queued(self, shot_id: str, job_id: str) -> Optional[Shot]:
        return self.update(shot_id, status="queued",
                           job_id=job_id, error=None)

    def mark_running(self, shot_id: str) -> Optional[Shot]:
        return self.update(shot_id, status="running", error=None)

    def mark_ready(self, shot_id: str, video_path: str) -> Optional[Shot]:
        return self.update(shot_id, status="ready",
                           video_path=video_path, error=None, job_id=None)

    def mark_failed(self, shot_id: str, error: str) -> Optional[Shot]:
        return self.update(shot_id, status="failed",
                           error=str(error)[:500], job_id=None)

    # ------------------------------------------------------------------
    # Continuity
    # ------------------------------------------------------------------

    def export_for_next(self, shot_id: str,
                        last_frame_path: Optional[str]) -> Optional[Shot]:
        """Wire the end of `shot_id` into the start of the next shot.

        If `last_frame_path` is provided and the next shot has no ref
        image yet (or its carry_last_frame flag is True), set its
        ref_image to that path.  This is what makes multi-shot continuity
        work without manual copying.
        """
        shot = self.get(shot_id)
        if not shot:
            return None
        nxt = self.next_of(shot_id)
        if not nxt:
            return None
        if last_frame_path and (nxt.ref_image is None or nxt.carry_last_frame):
            nxt.ref_image = last_frame_path
            nxt.touch()
            self.save()
        return nxt

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def as_dict(self) -> Dict[str, Any]:
        """Serialise the whole board (for API responses)."""
        return {
            "version": 1,
            "shot_count": len(self._shots),
            "shots": [s.to_dict() for s in self._shots],
        }

    def ready_videos(self) -> List[str]:
        """Return the ordered list of completed mp4 paths, skipping gaps."""
        return [s.video_path for s in self._shots
                if s.status == "ready" and s.video_path]
