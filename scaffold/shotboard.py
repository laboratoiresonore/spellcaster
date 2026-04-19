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

import copy
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
TRANSITION_TYPES = ("cut", "fade", "crossfade", "wipeleft", "wiperight", "wipeup", "wipedown")


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
class Scene:
    """A named group of shots (e.g. "Act 1", "EXT. Forest — Day").

    Scenes are purely organisational — they don't affect rendering or
    assembly.  Each shot may optionally belong to one scene via its
    ``scene_id`` field.  Scenes have a display order but that order is
    derived from the first shot in the scene, not stored separately.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    color: str = "#4a9eff"   # UI accent colour
    collapsed: bool = False  # whether the scene group is collapsed in UI

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Scene":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

@dataclass
class Shot:
    """A single video shot on the storyboard.

    Identity:
      - id:           stable uuid
      - index:        ordered position in the board (0-based)
      - title:        short human label ("EXT. forest — day")

    Creative:
      - prompt:       text description
      - negative:     negative prompt (text to avoid)
      - seed:         optional random seed for reproducibility
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

    Transition:
      - transition:    how this shot blends INTO the next ("cut", "fade",
        "crossfade", "wipeleft", "wiperight", "wipeup", "wipedown")
      - transition_ms: duration of the transition in milliseconds (0 = hard cut)

    Continuity:
      - carry_last_frame: if True, the ShotBoard will wire this shot's
        final frame as the *next* shot's ref_image when
        ``export_for_next()`` is called.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    index: int = 0
    title: str = ""
    prompt: str = ""
    negative: str = ""
    seed: Optional[int] = None
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
    render_duration_s: Optional[float] = None
    target_duration_s: Optional[float] = None
    carry_last_frame: bool = True
    notes: str = ""
    color_label: str = ""
    scene_id: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    transition: str = "cut"
    transition_ms: int = 500
    locked: bool = False
    render_history: List[Dict[str, Any]] = field(default_factory=list)
    # R45: user-labelled save/restore points. Distinct from render_history:
    # snapshots capture ANY creative state at ANY time (not just at render),
    # and they're user-driven (manually named, manually restored).
    snapshots: List[Dict[str, Any]] = field(default_factory=list)

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
        self._scenes: List[Scene] = []
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
        scenes_raw = raw.get("scenes") or []
        self._scenes = [Scene.from_dict(sc) for sc in scenes_raw if isinstance(sc, dict)]
        self._reindex()

    def _persist(self) -> None:
        """Internal alias for save() for consistency with other methods."""
        self.save()

    def save(self) -> None:
        """Atomically persist the board."""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        payload = {
            "version": 1,
            "saved_at": time.time(),
            "shots": [s.to_dict() for s in self._shots],
            "scenes": [sc.to_dict() for sc in self._scenes],
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
        """Mutate an existing shot by id; ignores unknown fields.
        
        Locked shots reject edits except for status, locked, error,
        video_path, job_id, render_duration_s (system fields).
        """
        shot = self.get(shot_id)
        if not shot:
            return None
        SYSTEM_FIELDS = {"status", "locked", "error", "video_path",
                         "job_id", "render_duration_s", "last_updated"}
        known = {f.name for f in Shot.__dataclass_fields__.values()}
        for key, val in fields.items():
            if key not in known:
                continue
            if shot.locked and key not in SYSTEM_FIELDS:
                continue  # silently skip locked field edits
            setattr(shot, key, val)
        # Auto-lock on render start or completion
        if "status" in fields:
            if fields["status"] in ("rendering", "ready"):
                shot.locked = True
            elif fields["status"] == "draft":
                shot.locked = False
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

    def duplicate(self, shot_id: str) -> Optional[Shot]:
        """Create a copy of a shot and insert it right after the original."""
        source = self.get(shot_id)
        if not source:
            return None
        new_shot = copy.deepcopy(source)
        new_shot.id = uuid.uuid4().hex
        new_shot.title = f"{source.title} (copy)" if source.title else ""
        new_shot.status = "draft"
        new_shot.video_path = None
        new_shot.job_id = None
        new_shot.error = None
        new_shot.seed = None
        new_shot.last_updated = time.time()
        # Insert after original
        idx = next((i for i, s in enumerate(self._shots) if s.id == shot_id), len(self._shots))
        self._shots.insert(idx + 1, new_shot)
        self._reindex()
        self.save()
        return new_shot

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
    # Scene management
    # ------------------------------------------------------------------

    def scenes(self) -> List[Scene]:
        """Return the list of scenes."""
        return list(self._scenes)

    def get_scene(self, scene_id: str) -> Optional[Scene]:
        """Look up a scene by id."""
        for sc in self._scenes:
            if sc.id == scene_id:
                return sc
        return None

    def add_scene(self, name: str = "", color: str = "#4a9eff") -> Scene:
        """Create a new scene and persist."""
        sc = Scene(name=name, color=color)
        self._scenes.append(sc)
        self.save()
        return sc

    def update_scene(self, scene_id: str, **fields: Any) -> Optional[Scene]:
        """Update a scene's fields by id."""
        sc = self.get_scene(scene_id)
        if not sc:
            return None
        known = {f.name for f in Scene.__dataclass_fields__.values()}
        for key, val in fields.items():
            if key in known:
                setattr(sc, key, val)
        self.save()
        return sc

    def remove_scene(self, scene_id: str) -> bool:
        """Remove a scene. Shots in it get scene_id cleared."""
        before = len(self._scenes)
        self._scenes = [sc for sc in self._scenes if sc.id != scene_id]
        if len(self._scenes) == before:
            return False
        # Clear scene_id from orphaned shots
        for s in self._shots:
            if s.scene_id == scene_id:
                s.scene_id = None
        self.save()
        return True

    def assign_shot_to_scene(self, shot_id: str, scene_id: Optional[str]) -> Optional[Shot]:
        """Set a shot's scene_id. Pass None to unassign."""
        shot = self.get(shot_id)
        if not shot:
            return None
        if scene_id is not None and not self.get_scene(scene_id):
            return None  # scene doesn't exist
        shot.scene_id = scene_id
        shot.touch()
        self.save()
        return shot

    def shots_in_scene(self, scene_id: str) -> List[Shot]:
        """Return all shots belonging to a scene, in board order."""
        return [s for s in self._shots if s.scene_id == scene_id]

    # ------------------------------------------------------------------
    # Dependencies
    # ------------------------------------------------------------------

    def add_dependency(self, shot_id: str, depends_on_id: str) -> Optional[Shot]:
        """Make shot_id depend on depends_on_id finishing first."""
        shot = self.get(shot_id)
        dep = self.get(depends_on_id)
        if not shot or not dep:
            return None
        if shot_id == depends_on_id:
            return None  # no self-dependency
        if depends_on_id not in shot.depends_on:
            shot.depends_on.append(depends_on_id)
            shot.touch()
            self.save()
        return shot

    def remove_dependency(self, shot_id: str, depends_on_id: str) -> Optional[Shot]:
        """Remove a dependency from a shot."""
        shot = self.get(shot_id)
        if not shot:
            return None
        if depends_on_id in shot.depends_on:
            shot.depends_on.remove(depends_on_id)
            shot.touch()
            self.save()
        return shot

    def dependencies_met(self, shot_id: str) -> bool:
        """Check if all dependencies of a shot are in 'ready' status."""
        shot = self.get(shot_id)
        if not shot or not shot.depends_on:
            return True
        for dep_id in shot.depends_on:
            dep = self.get(dep_id)
            if not dep or dep.status != "ready":
                return False
        return True

    def ready_to_render(self, shot_id: str) -> bool:
        """Check if a shot can be rendered (draft + dependencies met)."""
        shot = self.get(shot_id)
        if not shot:
            return False
        if shot.status != "draft":
            return False
        return self.dependencies_met(shot_id)

    # ------------------------------------------------------------------
    # Topological sort (dependency-aware ordering)
    # ------------------------------------------------------------------

    def has_cycle(self) -> bool:
        visited = set()
        rec_stack = set()
        ids = {s.id for s in self._shots}

        def _dfs(sid):
            visited.add(sid)
            rec_stack.add(sid)
            shot = self.get(sid)
            if shot:
                for dep_id in shot.depends_on:
                    if dep_id not in ids:
                        continue
                    if dep_id not in visited:
                        if _dfs(dep_id):
                            return True
                    elif dep_id in rec_stack:
                        return True
            rec_stack.discard(sid)
            return False

        for s in self._shots:
            if s.id not in visited:
                if _dfs(s.id):
                    return True
        return False

    def topological_sort(self):
        id_to_shot = {s.id: s for s in self._shots}
        in_degree = {s.id: 0 for s in self._shots}

        for s in self._shots:
            for dep_id in s.depends_on:
                if dep_id in id_to_shot:
                    in_degree[s.id] += 1

        queue_list = []
        for sid, deg in in_degree.items():
            if deg == 0:
                queue_list.append(sid)

        order_map = {s.id: i for i, s in enumerate(self._shots)}
        queue_list.sort(key=lambda sid: order_map.get(sid, 0))

        result = []
        visited_set = set()

        while queue_list:
            sid = queue_list.pop(0)
            visited_set.add(sid)
            result.append(id_to_shot[sid])
            for s in self._shots:
                if sid in s.depends_on and s.id not in visited_set:
                    in_degree[s.id] -= 1
                    if in_degree[s.id] == 0:
                        queue_list.append(s.id)
                        queue_list.sort(key=lambda x: order_map.get(x, 0))

        for s in self._shots:
            if s.id not in visited_set:
                result.append(s)

        return result

    def lock_shot(self, shot_id):
        """Lock a shot to prevent edits."""
        shot = self.get(shot_id)
        if not shot:
            return None
        shot.locked = True
        shot.touch()
        self.save()
        return shot

    def unlock_shot(self, shot_id):
        """Unlock a shot to allow edits."""
        shot = self.get(shot_id)
        if not shot:
            return None
        shot.locked = False
        shot.touch()
        self.save()
        return shot

    def is_locked(self, shot_id):
        """Check if a shot is locked."""
        shot = self.get(shot_id)
        return shot is not None and shot.locked

    def batch_lock(self, shot_ids, lock=True):
        """Lock or unlock multiple shots at once. Returns count of changed shots."""
        changed = 0
        for sid in shot_ids:
            shot = self.get(sid)
            if shot and shot.locked != lock:
                shot.locked = lock
                shot.touch()
                changed += 1
        if changed:
            self.save()
        return {"changed": changed, "lock": lock}

    def batch_reset_status(self, shot_ids):
        """Reset multiple shots to draft status. Skips locked shots. Returns count."""
        changed = 0
        for sid in shot_ids:
            shot = self.get(sid)
            if shot and shot.status != "draft" and not shot.locked:
                shot.status = "draft"
                shot.locked = False
                shot.touch()
                changed += 1
        if changed:
            self.save()
        return {"reset": changed}

    def batch_color_label(self, shot_ids, color_label):
        """Set color label on multiple shots. Returns count."""
        changed = 0
        for sid in shot_ids:
            shot = self.get(sid)
            if shot:
                shot.color_label = color_label
                shot.touch()
                changed += 1
        if changed:
            self.save()
        return {"changed": changed, "color_label": color_label}

    def effective_duration(self, shot_id):
        """Return the effective duration for a shot: target override or preset default."""
        shot = self.get(shot_id)
        if not shot:
            return 0.0
        if shot.target_duration_s is not None and shot.target_duration_s > 0:
            return shot.target_duration_s
        if shot.duration_s is not None and shot.duration_s > 0:
            return shot.duration_s
        return 0.0

    def total_duration(self):
        """Return sum of effective durations for all shots."""
        total = 0.0
        for s in self._shots:
            total += self.effective_duration(s.id)
        return round(total, 2)

    def average_render_time(self):
        """Return the average render duration across all shots with render_duration_s."""
        durations = [s.render_duration_s for s in self._shots
                     if s.render_duration_s is not None and s.render_duration_s > 0]
        if not durations:
            return 0.0
        return round(sum(durations) / len(durations), 2)

    def queue_eta(self):
        """Estimate time remaining for queued + running shots."""
        avg = self.average_render_time()
        pending = sum(1 for s in self._shots if s.status in ("queued", "running"))
        if avg <= 0 or pending == 0:
            return {"eta_seconds": 0, "pending_count": pending, "avg_render_s": avg}
        eta = round(avg * pending, 1)
        return {"eta_seconds": eta, "pending_count": pending, "avg_render_s": avg}

    def record_render(self, shot_id, preset=None, status="ready",
                      duration_s=None, error=None):
        """Append a render attempt to the shot's history log."""
        shot = self.get(shot_id)
        if not shot:
            return None
        entry = {
            "timestamp": time.time(),
            "preset": preset or shot.preset,
            "prompt": shot.prompt,
            "negative": shot.negative,
            "overrides": dict(shot.overrides) if shot.overrides else {},
            "status": status,
            "duration_s": duration_s,
            "error": error,
        }
        shot.render_history.append(entry)
        # Keep last 20 entries to bound storage
        if len(shot.render_history) > 20:
            shot.render_history = shot.render_history[-20:]
        shot.touch()
        self.save()
        return entry

    def get_render_history(self, shot_id):
        """Return the render history for a shot."""
        shot = self.get(shot_id)
        if not shot:
            return []
        return list(shot.render_history)

    def render_order(self):
        """Return render order preview with dependency graph data."""
        sorted_shots = self.topological_sort()
        has_cycle = self.has_cycle()
        nodes = []
        for i, s in enumerate(sorted_shots):
            deps_met = self.dependencies_met(s.id)
            ready = self.ready_to_render(s.id)
            nodes.append({
                "id": s.id,
                "title": s.title or s.id[:8],
                "status": s.status,
                "order": i,
                "depends_on": list(s.depends_on),
                "dependencies_met": deps_met,
                "ready_to_render": ready,
            })
        edges = []
        for s in sorted_shots:
            for dep_id in s.depends_on:
                dep_shot = self.get(dep_id)
                met = dep_shot is not None and dep_shot.status == "ready"
                edges.append({"from": dep_id, "to": s.id, "met": met})
        ready_count = sum(1 for n in nodes if n["ready_to_render"])
        return {
            "nodes": nodes,
            "edges": edges,
            "has_cycle": has_cycle,
            "total": len(nodes),
            "ready_count": ready_count,
        }

    def carry_frame_to_next(self, shot_id, last_frame_path=None):
        """Set the reference image for the next shot in sequence."""
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

    # ------------------------------------------------------------------
    # Diff indicator
    # ------------------------------------------------------------------

    def shot_diff(self, shot_id: str) -> Dict[str, Any]:
        """Compare current shot fields against the last successful render.

        Returns a dict with:
          - "has_changes": bool
          - "fields": dict mapping field name → {"old": ..., "new": ...}
          - "last_render_ts": float or None
        If the shot has no successful render history, returns has_changes=False.
        """
        shot = self.get(shot_id)
        if not shot:
            return {"has_changes": False, "fields": {}, "last_render_ts": None}

        # Find most recent successful render
        last_ok = None
        for entry in reversed(shot.render_history):
            if entry.get("status") == "ready":
                last_ok = entry
                break

        if last_ok is None:
            return {"has_changes": False, "fields": {}, "last_render_ts": None}

        changes: Dict[str, Any] = {}

        # Compare prompt
        rendered_prompt = last_ok.get("prompt", "")
        if shot.prompt != rendered_prompt:
            changes["prompt"] = {"old": rendered_prompt, "new": shot.prompt}

        # Compare negative prompt
        rendered_negative = last_ok.get("negative", "")
        if shot.negative != rendered_negative:
            changes["negative"] = {"old": rendered_negative, "new": shot.negative}

        # Compare preset
        rendered_preset = last_ok.get("preset", "")
        if shot.preset != rendered_preset:
            changes["preset"] = {"old": rendered_preset, "new": shot.preset}

        # Compare overrides (stored as dict)
        rendered_overrides = last_ok.get("overrides") or {}
        if shot.overrides != rendered_overrides:
            changes["overrides"] = {"old": rendered_overrides,
                                    "new": shot.overrides}


        return {
            "has_changes": len(changes) > 0,
            "fields": changes,
            "last_render_ts": last_ok.get("timestamp"),
        }

    def revert_to_last_render(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """Revert a shot's prompt/preset/overrides to the last successful render.

        Returns a dict of the reverted fields, or None if the shot doesn't
        exist, is locked, or has no successful render history.
        """
        shot = self.get(shot_id)
        if not shot:
            return None
        if shot.locked:
            return None

        # Find most recent successful render
        last_ok = None
        for entry in reversed(shot.render_history):
            if entry.get("status") == "ready":
                last_ok = entry
                break

        if last_ok is None:
            return None

        reverted = {}
        old_prompt = last_ok.get("prompt", "")
        if shot.prompt != old_prompt:
            reverted["prompt"] = {"from": shot.prompt, "to": old_prompt}
            shot.prompt = old_prompt

        old_negative = last_ok.get("negative", "")
        if shot.negative != old_negative:
            reverted["negative"] = {"from": shot.negative, "to": old_negative}
            shot.negative = old_negative


        old_preset = last_ok.get("preset", "")
        if shot.preset != old_preset:
            reverted["preset"] = {"from": shot.preset, "to": old_preset}
            shot.preset = old_preset

        old_overrides = last_ok.get("overrides") or {}
        if shot.overrides != old_overrides:
            reverted["overrides"] = {"from": dict(shot.overrides),
                                     "to": old_overrides}
            shot.overrides = dict(old_overrides)

        if reverted:
            shot.touch()
            self.save()

        return reverted

    def batch_revert(self, shot_ids: List[str]) -> Dict[str, Any]:
        """Revert multiple shots to their last rendered settings.

        Returns a summary dict with 'reverted' count and 'skipped' count.
        Skipped shots are locked, have no history, or don't exist.
        """
        reverted = 0
        skipped = 0
        for sid in shot_ids:
            result = self.revert_to_last_render(sid)
            if result is None:
                skipped += 1
            elif isinstance(result, dict):
                if result:
                    reverted += 1
                else:
                    skipped += 1  # no changes to revert
        return {"reverted": reverted, "skipped": skipped}

    def batch_prompt_edit(self, shot_ids: List[str], prefix: str = "",
                          suffix: str = "", mode: str = "add") -> Dict[str, Any]:
        """Add or remove a prefix/suffix to/from prompts of multiple shots.

        mode='add': prepend prefix and/or append suffix to each shot's prompt.
        mode='remove': strip prefix from start and/or suffix from end.
        Locked shots are skipped.

        Returns {'modified': int, 'skipped': int}.
        """
        modified = 0
        skipped = 0
        for sid in shot_ids:
            shot = self.get(sid)
            if not shot:
                skipped += 1
                continue
            if shot.locked:
                skipped += 1
                continue
            old_prompt = shot.prompt
            new_prompt = old_prompt
            if mode == "add":
                if prefix and not new_prompt.startswith(prefix):
                    new_prompt = prefix + new_prompt
                if suffix and not new_prompt.endswith(suffix):
                    new_prompt = new_prompt + suffix
            elif mode == "remove":
                if prefix and new_prompt.startswith(prefix):
                    new_prompt = new_prompt[len(prefix):]
                if suffix and new_prompt.endswith(suffix):
                    new_prompt = new_prompt[:-len(suffix)]
            if new_prompt != old_prompt:
                shot.prompt = new_prompt
                shot.touch()
                modified += 1
            else:
                skipped += 1
        if modified > 0:
            self.save()
        return {"modified": modified, "skipped": skipped}

    # ─── R45a: shot version snapshots ────────────────────────────────

    _SNAPSHOT_FIELDS = (
        "title", "prompt", "negative", "seed", "ref_image", "backend",
        "preset", "overrides", "notes", "transition", "transition_ms",
        "target_duration_s", "trajectories",
    )

    def save_snapshot(self, shot_id: str, label: str = "") -> Optional[Dict[str, Any]]:
        """Append a labelled snapshot of the shot's creative state.

        Unlike render_history (auto-captured at render time), snapshots are
        user-driven save points — taken before a risky prompt change,
        before experimenting with a new preset, etc. Max 20 per shot
        (oldest pruned on overflow).
        """
        shot = self.get(shot_id)
        if shot is None:
            return None
        snap_id = uuid.uuid4().hex[:12]
        snap: Dict[str, Any] = {
            "id": snap_id,
            "label": (label or f"Snapshot {len(shot.snapshots) + 1}").strip(),
            "created_at": time.time(),
        }
        for key in self._SNAPSHOT_FIELDS:
            val = getattr(shot, key, None)
            if key == "trajectories":
                # Trajectories are list[Trajectory]; serialize to dicts for
                # stable restore regardless of in-memory object identity
                snap[key] = [t.to_dict() if hasattr(t, "to_dict") else dict(t)
                             for t in (val or [])]
            else:
                snap[key] = copy.deepcopy(val)
        shot.snapshots.append(snap)
        if len(shot.snapshots) > 20:
            shot.snapshots = shot.snapshots[-20:]
        shot.touch()
        self.save()
        return snap

    def list_snapshots(self, shot_id: str) -> List[Dict[str, Any]]:
        """Return shallow copies of this shot's snapshots (newest last)."""
        shot = self.get(shot_id)
        if shot is None:
            return []
        return [dict(s) for s in shot.snapshots]

    def restore_snapshot(self, shot_id: str, snap_id: str) -> Optional[Dict[str, Any]]:
        """Reset the shot's creative state to the named snapshot. Runtime
        fields (status, video_path, job_id, error) are NOT touched — the
        shot may still be locked/running; creative edits are independent.

        Returns the snapshot dict that was applied, or None if not found.
        Locked shots are skipped.
        """
        shot = self.get(shot_id)
        if shot is None or shot.locked:
            return None
        snap = next((s for s in shot.snapshots if s.get("id") == snap_id), None)
        if snap is None:
            return None
        for key in self._SNAPSHOT_FIELDS:
            if key not in snap:
                continue
            if key == "trajectories":
                shot.trajectories = [Trajectory.from_dict(t) for t in (snap[key] or [])]
            else:
                setattr(shot, key, copy.deepcopy(snap[key]))
        shot.touch()
        self.save()
        return snap

    def delete_snapshot(self, shot_id: str, snap_id: str) -> bool:
        """Remove a snapshot by id. Returns True if one was removed."""
        shot = self.get(shot_id)
        if shot is None:
            return False
        before = len(shot.snapshots)
        shot.snapshots = [s for s in shot.snapshots if s.get("id") != snap_id]
        if len(shot.snapshots) < before:
            shot.touch()
            self.save()
            return True
        return False

    # ─── R45b: batch duplicate with counter ──────────────────────────

    def batch_duplicate(self, shot_ids: List[str], count: int = 1,
                        title_suffix_mode: str = "counter") -> Dict[str, Any]:
        """Create `count` copies of each shot in shot_ids.

        For each source shot, copies share the source's creative state
        (prompt, preset, overrides, notes, trajectories) but get fresh
        ids, a fresh status ("draft"), and NO render_history / snapshots.

        title_suffix_mode:
          - "counter": source "Scene A" → "Scene A v2", "Scene A v3", ...
                       (v1 assumed = original; new copies start at v2)
          - "plain":   source "Scene A" → "Scene A (2)", "Scene A (3)", ...

        Locked shots are copied but their copies are NOT locked — the
        user just wanted a starting point.

        Returns {"created": int, "skipped": int, "new_ids": [...]}
        """
        if count < 1:
            return {"created": 0, "skipped": 0, "new_ids": []}
        created: List[str] = []
        skipped = 0
        for sid in shot_ids:
            source = self.get(sid)
            if source is None:
                skipped += 1
                continue
            for i in range(count):
                new_shot = copy.deepcopy(source)
                new_shot.id = uuid.uuid4().hex
                new_shot.status = "draft"
                new_shot.video_path = None
                new_shot.job_id = None
                new_shot.error = None
                new_shot.render_history = []
                new_shot.snapshots = []
                new_shot.locked = False
                new_shot.render_duration_s = None
                new_shot.last_updated = time.time()
                # Compose the new title
                base = (source.title or "Untitled").rstrip()
                if title_suffix_mode == "plain":
                    new_shot.title = f"{base} ({i + 2})"
                else:  # "counter"
                    new_shot.title = f"{base} v{i + 2}"
                new_shot.index = len(self._shots)
                self._shots.append(new_shot)
                created.append(new_shot.id)
        if created:
            self.save()
        return {"created": len(created), "skipped": skipped, "new_ids": created}
