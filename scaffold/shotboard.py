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


def _words_share_prefix(a: list[str], b: list[str], length: int) -> bool:
    """R67b helper — True iff the first ``length`` words match case-insensitively."""
    if len(a) < length or len(b) < length:
        return False
    for i in range(length):
        if a[i].lower() != b[i].lower():
            return False
    return True


def _slugify_reel(name: str) -> str:
    """CMX 3600 reel names: ASCII upper, max 8 chars, no spaces/punct."""
    clean = "".join(c for c in (name or "").upper() if c.isalnum())[:8]
    return clean or "CLIP"


def _xml_escape(s: str) -> str:
    """Escape XML text content and attribute values (no HTML5 entities)."""
    return (str(s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


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
    # R47b: ids of snapshots the user has pinned. Pinned snapshots are
    # NEVER auto-pruned when the 20-slot cap is hit — they stay until
    # the user explicitly deletes them.
    pinned_snapshots: List[str] = field(default_factory=list)
    # R61b: priority for render dispatch. "high" shots queue ahead of
    # "normal" which queue ahead of "low". Within a priority, board
    # order wins. Independent of dependencies (depends_on still forces
    # ordering across priority tiers).
    priority: str = "normal"  # "high" | "normal" | "low"
    # R65a: user-toggled bookmark / favorite. Pure UI state — never
    # affects render order or any automated behavior. Filter chip in
    # the video panel shows "⭐ starred" to quickly return to them.
    bookmarked: bool = False
    # R71a: soft-delete flag. Archived shots are excluded from the
    # default view and all batch operations, but kept on disk so the
    # user can restore them. Matches the common "trash" pattern.
    archived: bool = False
    archived_at: Optional[float] = None
    # R72a: variation grouping. Shots that are alternates of the same
    # storyboard beat share a `variation_group` id. Exactly one of them
    # carries `is_primary=True`; the others are shown as siblings you
    # can swap into. The final timeline only renders/exports the
    # primary of each group.
    variation_group: Optional[str] = None
    is_primary: bool = True

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

    # R71b: board-level project metadata (title, author, synopsis, etc).
    # Surfaces in EDL/FCPXML exports and the board-stats panel. All
    # fields are free-form strings; empty ones get default-derived
    # values in downstream exports.
    _PROJECT_META_KEYS = ("title", "author", "synopsis",
                           "copyright", "production")

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._shots: List[Shot] = []
        self._scenes: List[Scene] = []
        self._project_meta: Dict[str, str] = {}
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
        # R71b: project metadata — tolerate missing key on old boards
        pm = raw.get("project_meta") or {}
        if isinstance(pm, dict):
            self._project_meta = {k: str(v) for k, v in pm.items()
                                    if k in self._PROJECT_META_KEYS}
        else:
            self._project_meta = {}
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
            "project_meta": dict(self._project_meta),
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
        self.log_activity("shot_created", shot_id=shot.id, title=shot.title)
        return shot

    @staticmethod
    def _title_from_prompt(prompt: str, max_words: int = 6) -> str:
        """R63b: extract a short title from a prompt. Grabs the first
        N words, strips boilerplate quality tags, title-cases."""
        if not prompt:
            return ""
        # Strip common quality prefixes ComfyUI users pile up
        noise = {"masterpiece", "best", "quality", "highres", "detailed",
                  "8k", "4k", "hd", "ultra", "photorealistic", "cinematic",
                  "professional", "high", "absurdres", "ultradetailed"}
        words = [w.strip(" ,.;:()[]{}\"'").lower()
                 for w in prompt.replace(",", " ").split()]
        # Keep only meaningful words
        kept = [w for w in words if w and w not in noise][:max_words]
        if not kept:
            return ""
        return " ".join(kept).title()

    @staticmethod
    def _is_placeholder_title(title: str) -> bool:
        t = (title or "").strip().lower()
        return (not t
                 or t == "untitled"
                 or t.startswith("shot ")
                 or t.startswith("scene ")
                 or t.startswith("new "))

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
        # R63b: when the user changes the prompt and the current title is
        # still a placeholder, auto-derive a title from the new prompt.
        # User's explicit title always wins — we only fill in blanks.
        if "prompt" in fields and self._is_placeholder_title(shot.title):
            # ...but only if the user didn't also set a title in this call
            if "title" not in fields:
                suggested = self._title_from_prompt(shot.prompt)
                if suggested:
                    shot.title = suggested
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
        self.log_activity("shot_removed", shot_id=shot_id)
        return True

    def get_project_meta(self) -> Dict[str, str]:
        """R71b: return a copy of the project-level metadata dict."""
        return dict(self._project_meta)

    def set_project_meta(self, **fields: str) -> Dict[str, str]:
        """R71b: merge-update project metadata. Unknown keys ignored.
        Empty-string values clear the field."""
        for k, v in fields.items():
            if k not in self._PROJECT_META_KEYS:
                continue
            if v is None or v == "":
                self._project_meta.pop(k, None)
            else:
                self._project_meta[k] = str(v)
        self.save()
        return dict(self._project_meta)

    # ─── R72a: variation groups ────────────────────────────────────

    def _new_group_id(self) -> str:
        return "var-" + uuid.uuid4().hex[:10]

    def make_variation(self, source_id: str,
                         variation_label: str = "") -> Optional[Shot]:
        """R72a: clone `source_id` into a new alternate of the same
        variation group. First call establishes the group (source
        becomes its primary); subsequent calls add siblings.
        The new shot keeps the same prompt/preset/overrides but gets
        a fresh id, status="draft", cleared video/history/snapshots,
        and is_primary=False.
        """
        source = self.get(source_id)
        if source is None:
            return None
        # Ensure source has a group
        if not source.variation_group:
            source.variation_group = self._new_group_id()
            source.is_primary = True
            source.touch()
        copy_shot = copy.deepcopy(source)
        copy_shot.id = uuid.uuid4().hex
        copy_shot.status = "draft"
        copy_shot.video_path = None
        copy_shot.job_id = None
        copy_shot.error = None
        copy_shot.render_history = []
        copy_shot.snapshots = []
        copy_shot.pinned_snapshots = []
        copy_shot.locked = False
        copy_shot.archived = False
        copy_shot.archived_at = None
        copy_shot.render_duration_s = None
        copy_shot.last_updated = time.time()
        copy_shot.bookmarked = False
        copy_shot.is_primary = False
        if variation_label:
            copy_shot.title = f"{source.title or 'Shot'} — {variation_label}"
        elif source.title:
            # Count existing siblings to pick the next letter
            siblings = self.shots_in_group(source.variation_group)
            letter = chr(ord('A') + len(siblings))  # A, B, C...
            copy_shot.title = f"{source.title} — Var {letter}"
        copy_shot.index = len(self._shots)
        self._shots.append(copy_shot)
        self.save()
        return copy_shot

    def shots_in_group(self, group_id: str) -> List[Shot]:
        """All shots sharing a variation group, primary first."""
        if not group_id:
            return []
        members = [s for s in self._shots if s.variation_group == group_id]
        members.sort(key=lambda s: (not s.is_primary, s.index))
        return members

    def promote_variation(self, shot_id: str) -> Optional[Shot]:
        """Make this variation the primary of its group; demote others."""
        shot = self.get(shot_id)
        if shot is None or not shot.variation_group:
            return None
        for s in self._shots:
            if s.variation_group == shot.variation_group:
                s.is_primary = (s.id == shot_id)
                s.touch()
        self.save()
        return shot

    # ─── R72b: activity log ─────────────────────────────────────────

    def _activity_log_path(self) -> str:
        return os.path.join(os.path.dirname(self.path), "activity.log")

    def log_activity(self, action: str, **details: Any) -> None:
        """R72b: append a structured line to the board's activity log.
        Non-fatal — log write failures never interrupt the caller."""
        try:
            entry = {
                "ts": time.time(),
                "action": action,
                **details,
            }
            line = json.dumps(entry) + "\n"
            path = self._activity_log_path()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    def read_activity_log(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Return the most recent `limit` entries (newest last)."""
        path = self._activity_log_path()
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        out: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def archive_shot(self, shot_id: str) -> Optional[Shot]:
        """R71a: soft-delete. Keeps the shot on disk but hides it from
        the default view and batch ops. Returns the archived shot.
        """
        shot = self.get(shot_id)
        if shot is None or shot.archived:
            return None
        shot.archived = True
        shot.archived_at = time.time()
        shot.touch()
        self.save()
        return shot

    def unarchive_shot(self, shot_id: str) -> Optional[Shot]:
        """R71a: restore a shot from the archive."""
        shot = self.get(shot_id)
        if shot is None or not shot.archived:
            return None
        shot.archived = False
        shot.archived_at = None
        shot.touch()
        self.save()
        return shot

    def batch_archive(self, shot_ids: List[str],
                       archive: bool = True) -> Dict[str, Any]:
        """Archive or restore many shots at once."""
        changed = 0
        for sid in shot_ids:
            result = (self.archive_shot(sid) if archive
                       else self.unarchive_shot(sid))
            if result is not None:
                changed += 1
        return {"changed": changed, "archived": archive}

    def archived_shots(self) -> List[Shot]:
        """All shots currently in the archive, newest first."""
        items = [s for s in self._shots if s.archived]
        items.sort(key=lambda s: s.archived_at or 0, reverse=True)
        return items

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

    # R61b: priority → rank. Lower rank = earlier in queue. Unknown
    # priorities fall back to normal.
    _PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}

    def _priority_key(self, sid_to_shot: dict[str, "Shot"],
                       order_map: dict[str, int]):
        """Return a sort-key factory for a dependency-satisfied frontier.

        Sorts by (priority_rank, board_position) so high-priority shots
        queue ahead of normal, without breaking dependency constraints
        (those are enforced by the topological frontier itself — priority
        only reorders the READY-TO-QUEUE set).
        """
        def key(sid: str):
            shot = sid_to_shot.get(sid)
            prio = getattr(shot, "priority", "normal") if shot else "normal"
            rank = self._PRIORITY_RANK.get(prio, 1)
            return (rank, order_map.get(sid, 0))
        return key

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
        # R61b: sort ready frontier by (priority, board-position)
        prio_key = self._priority_key(id_to_shot, order_map)
        queue_list.sort(key=prio_key)

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
                        queue_list.sort(key=prio_key)

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

    def shot_warnings(self, shot_id):
        """R63a: Return a list of continuity / quality warnings for ``shot_id``.

        Each warning is: {"code": "...", "severity": "info|warn|error",
                           "message": "..."}.

        Codes:
          - empty_prompt: prompt is whitespace-only
          - missing_ref_image: ref_image path doesn't exist on disk
          - broken_dependency: depends_on references a non-existent shot
          - failed_dependency: depends_on references a shot whose last
            render failed
          - carry_frame_without_deps: carry_last_frame=True but no
            preceding shot in board order
          - title_looks_placeholder: title is "Untitled" / empty / "shot N"
          - preset_unknown: preset key not recognized (relative to the
            current architectures/presets registry is preset-registry's
            job — here we only flag missing presets)
        """
        shot = self.get(shot_id)
        if shot is None:
            return []
        warnings: List[Dict[str, Any]] = []

        if not (shot.prompt or "").strip():
            warnings.append({"code": "empty_prompt", "severity": "error",
                              "message": "Prompt is empty — render will fail or produce noise."})

        if shot.ref_image:
            try:
                if not os.path.isfile(shot.ref_image):
                    warnings.append({"code": "missing_ref_image",
                                      "severity": "error",
                                      "message": f"Reference image not found: {shot.ref_image}"})
            except (OSError, ValueError):
                warnings.append({"code": "missing_ref_image", "severity": "error",
                                  "message": "Reference image path is invalid."})

        for dep_id in (shot.depends_on or []):
            dep = self.get(dep_id)
            if dep is None:
                warnings.append({"code": "broken_dependency", "severity": "error",
                                  "message": f"Depends on deleted shot {dep_id[:8]}…"})
                continue
            last_hist = [e for e in (dep.render_history or [])
                         if e.get("status") == "ready"]
            if dep.status == "failed" and not last_hist:
                warnings.append({"code": "failed_dependency", "severity": "warn",
                                  "message": f"Depends on {dep.title or dep_id[:8]} which has never rendered successfully."})

        if shot.carry_last_frame:
            idx = next((i for i, s in enumerate(self._shots) if s.id == shot.id), None)
            if idx == 0:
                warnings.append({"code": "carry_frame_without_deps",
                                  "severity": "warn",
                                  "message": "carry_last_frame=True but this is the first shot — nothing to carry from."})

        title = (shot.title or "").strip().lower()
        if not title or title == "untitled" or title.startswith("shot "):
            warnings.append({"code": "title_looks_placeholder", "severity": "info",
                              "message": "Title is a placeholder — consider giving this shot a real name."})

        return warnings

    def board_warnings_summary(self) -> Dict[str, Any]:
        """Aggregate warnings across all shots for a dashboard view."""
        by_code: Dict[str, int] = {}
        by_shot: Dict[str, int] = {}
        total = 0
        for s in self._shots:
            warnings = self.shot_warnings(s.id)
            if warnings:
                by_shot[s.id] = len(warnings)
                for w in warnings:
                    by_code[w["code"]] = by_code.get(w["code"], 0) + 1
                    total += 1
        return {"total": total, "by_code": by_code,
                "shots_with_warnings": by_shot}

    def auto_group_scenes(self, *, min_cluster: int = 2,
                            min_prefix_words: int = 1,
                            assign: bool = True) -> Dict[str, Any]:
        """R67b: Auto-group shots into scenes by shared title prefix.

        Detects clusters of shots whose titles share the first N words
        (case-insensitive, ignoring leading/trailing whitespace). For
        each cluster ≥ ``min_cluster`` shots:

          1. Ensures a Scene with name = shared prefix exists (creates
             one on the fly if needed, using the default color).
          2. If ``assign=True``, sets `scene_id` on every shot in the
             cluster that doesn't already belong to a scene.

        Detection strategy is conservative: a shot title of
        "INT. Kitchen — night" and "INT. Kitchen — day" will cluster
        under "INT. Kitchen" (3 shared words before a divergent token).
        We skip shots with placeholder titles (Untitled / "Shot N").

        Returns:
            {
              "clusters_found": int,
              "scenes_created": int,
              "shots_assigned": int,
              "clusters": [{"prefix": "INT. Kitchen", "shot_ids": [...],
                             "scene_id": "..."}, ...]
            }
        """
        import re

        def _words(title: str) -> list[str]:
            # Split on whitespace + common separators, drop empties
            return [w for w in re.split(r"\s+", (title or "").strip()) if w]

        def _common_prefix(a: list[str], b: list[str]) -> list[str]:
            out = []
            for x, y in zip(a, b):
                if x.lower() == y.lower():
                    out.append(x)
                else:
                    break
            return out

        # Index candidates: only real titles (skip placeholders)
        candidates = [(s, _words(s.title)) for s in self._shots
                       if not self._is_placeholder_title(s.title)
                       and len(_words(s.title)) >= min_prefix_words]

        # Union-find on shots sharing a common prefix of ≥ min_prefix_words
        # Simple O(n²) pairing — shotboards rarely exceed a few hundred
        # shots so perf isn't a concern here.
        groups: Dict[str, List[Shot]] = {}
        # Pick the LONGEST prefix that's shared by at least min_cluster shots
        for i, (shot_i, words_i) in enumerate(candidates):
            best_prefix = None
            best_size = 0
            for length in range(len(words_i), min_prefix_words - 1, -1):
                prefix = " ".join(words_i[:length])
                size = sum(1 for (_, w_j) in candidates
                           if _words_share_prefix(w_j, words_i, length))
                if size >= min_cluster and size > best_size:
                    best_prefix = prefix
                    best_size = size
                    break
            if best_prefix is not None:
                groups.setdefault(best_prefix, []).append(shot_i)

        clusters_found = 0
        scenes_created = 0
        shots_assigned = 0
        cluster_results: List[Dict[str, Any]] = []

        for prefix, shots_in_cluster in groups.items():
            if len(shots_in_cluster) < min_cluster:
                continue
            clusters_found += 1
            # Find or create the scene
            scene = next((sc for sc in self._scenes
                          if (sc.name or "").lower() == prefix.lower()),
                         None)
            if scene is None:
                if assign:
                    scene = self.add_scene(name=prefix, color="#4a9eff")
                    scenes_created += 1
                else:
                    cluster_results.append({
                        "prefix": prefix,
                        "shot_ids": [s.id for s in shots_in_cluster],
                        "scene_id": None,
                    })
                    continue
            if assign:
                for s in shots_in_cluster:
                    # Only reassign shots that aren't already in a scene
                    # (user-curated membership wins)
                    if not s.scene_id:
                        s.scene_id = scene.id
                        s.touch()
                        shots_assigned += 1
            cluster_results.append({
                "prefix": prefix,
                "shot_ids": [s.id for s in shots_in_cluster],
                "scene_id": scene.id if scene else None,
            })
        if shots_assigned or scenes_created:
            self.save()
        return {
            "clusters_found": clusters_found,
            "scenes_created": scenes_created,
            "shots_assigned": shots_assigned,
            "clusters": cluster_results,
        }

    def find_prompt_clusters(self, *, min_cluster: int = 2) -> List[Dict[str, Any]]:
        """R65b: Group shots by exact prompt match. Returns one entry
        per cluster with 2+ shots sharing the same (normalized) prompt.

        Normalization: trim whitespace + collapse runs of whitespace.
        Empty prompts are never clustered.

        Use cases:
          - find accidentally-duplicated work
          - spot shots that share a prompt but diverge in preset/seed
            (intentional variations — might want to group them as a scene)

        Returns:
          [{"prompt": "...", "count": 3, "shot_ids": ["a", "b", "c"]}, ...]
        sorted by cluster size (largest first), then by prompt alpha.
        """
        import re
        ws_re = re.compile(r"\s+")
        by_prompt: Dict[str, List[str]] = {}
        for shot in self._shots:
            p = (shot.prompt or "").strip()
            if not p:
                continue
            norm = ws_re.sub(" ", p).lower()
            by_prompt.setdefault(norm, []).append(shot.id)
        clusters = [
            {"prompt": norm, "count": len(ids), "shot_ids": list(ids)}
            for norm, ids in by_prompt.items()
            if len(ids) >= min_cluster
        ]
        clusters.sort(key=lambda c: (-c["count"], c["prompt"]))
        return clusters

    def batch_randomize_seeds(self, shot_ids,
                               seed_min: int = 0,
                               seed_max: int = 2147483647):
        """R64a: assign each shot a fresh random seed.

        Useful for "render the same prompt 10 times with different
        seeds" variation exploration. Locked shots are skipped.
        Returns count + the new seeds for UI feedback.
        """
        import random
        rng = random.Random()  # process-private, no seed = system entropy
        changed: List[Dict[str, Any]] = []
        for sid in shot_ids:
            shot = self.get(sid)
            if shot is None or shot.locked:
                continue
            new_seed = rng.randint(int(seed_min), int(seed_max))
            shot.seed = new_seed
            shot.touch()
            changed.append({"id": sid, "seed": new_seed})
        if changed:
            self.save()
        return {"changed": len(changed), "shots": changed}

    def import_shots_from_csv(self, csv_text: str) -> Dict[str, Any]:
        """R67a: bulk-create shots from a CSV.

        Accepted columns (case-insensitive, any subset):
          title, prompt, negative, preset, seed, notes, backend,
          color_label, scene_id, priority, target_duration_s,
          depends_on (comma-separated shot titles), carry_last_frame

        Only `prompt` is required. If `title` is missing we auto-derive
        from prompt (R63b). Unknown columns are ignored. Empty cells
        keep the field's default.

        Returns {"created": N, "errors": [...], "new_ids": [...]}.
        """
        import csv
        import io

        reader = csv.DictReader(io.StringIO(csv_text))
        # Normalize headers to lowercase for case-insensitive access
        known_fields = {f.name for f in Shot.__dataclass_fields__.values()}
        created_ids: List[str] = []
        errors: List[Dict[str, Any]] = []
        # Index by title AFTER creation so depends_on can reference
        # same-CSV siblings by title. Only top-level unique titles
        # count — duplicates within one CSV silently overwrite.
        title_to_id: Dict[str, str] = {s.title: s.id for s in self._shots
                                         if s.title}
        for row_i, row in enumerate(reader, start=2):  # row 1 is header
            try:
                # Lowercase keys; strip values
                row_lc = {(k or "").strip().lower(): (v or "").strip()
                           for k, v in row.items()}
                prompt = row_lc.get("prompt", "")
                if not prompt:
                    errors.append({"row": row_i, "error": "empty prompt"})
                    continue
                fields: Dict[str, Any] = {}
                for key, val in row_lc.items():
                    if key not in known_fields:
                        continue
                    if val == "":
                        continue
                    # Type coercion for non-string fields
                    if key == "seed":
                        try:
                            fields[key] = int(val)
                        except ValueError:
                            errors.append({"row": row_i,
                                            "error": f"bad seed: {val}"})
                            continue
                    elif key == "target_duration_s":
                        try:
                            fields[key] = float(val)
                        except ValueError:
                            errors.append({"row": row_i,
                                            "error": f"bad duration: {val}"})
                            continue
                    elif key == "carry_last_frame":
                        fields[key] = val.lower() in ("1", "true", "yes", "y")
                    elif key == "depends_on":
                        # Comma-separated titles → ids, resolved against
                        # the titles we know at this moment (including
                        # siblings created earlier in this same CSV)
                        dep_titles = [t.strip() for t in val.split(",") if t.strip()]
                        dep_ids = [title_to_id[t] for t in dep_titles
                                   if t in title_to_id]
                        if dep_ids:
                            fields[key] = dep_ids
                    else:
                        fields[key] = val
                # Auto-title if missing
                if "title" not in fields:
                    auto = self._title_from_prompt(prompt)
                    if auto:
                        fields["title"] = auto
                fields["prompt"] = prompt
                shot = self.add(**fields)
                created_ids.append(shot.id)
                if shot.title:
                    title_to_id[shot.title] = shot.id
            except Exception as e:  # noqa: BLE001
                errors.append({"row": row_i,
                                "error": f"{type(e).__name__}: {e}"})
        return {
            "created": len(created_ids),
            "errors": errors,
            "new_ids": created_ids,
        }

    def render_history_csv(self) -> str:
        """R64b: emit render history for every shot as a flat CSV.
        Columns: shot_id, shot_title, render_ts, preset, prompt, negative,
                 status, duration_s, error.
        Suitable for piping into a spreadsheet for analysis.
        """
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow([
            "shot_id", "shot_title", "render_ts", "preset",
            "prompt", "negative", "status", "duration_s", "error",
        ])
        for shot in self._shots:
            for entry in (shot.render_history or []):
                writer.writerow([
                    shot.id,
                    shot.title or "",
                    entry.get("timestamp", ""),
                    entry.get("preset", ""),
                    entry.get("prompt", ""),
                    entry.get("negative", ""),
                    entry.get("status", ""),
                    entry.get("duration_s", ""),
                    (entry.get("error", "") or "").replace("\n", " "),
                ])
        return buf.getvalue()

    def batch_priority(self, shot_ids, priority):
        """R61b: set render priority on multiple shots.
        `priority` must be one of 'high', 'normal', 'low'."""
        if priority not in self._PRIORITY_RANK:
            return {"changed": 0, "priority": priority,
                    "error": f"invalid priority {priority!r}"}
        changed = 0
        for sid in shot_ids:
            shot = self.get(sid)
            if shot and shot.priority != priority:
                shot.priority = priority
                shot.touch()
                changed += 1
        if changed:
            self.save()
        return {"changed": changed, "priority": priority}

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

    def render_cost_estimate(self, *, max_concurrent: int = 1):
        """R60b: Estimate total render cost for everything NOT yet ready.

        Draft + queued + running + failed counts as "pending work"; each
        uses its own render history's average when available, falling back
        to the global average otherwise. Returns:

            {
              "pending_count": int,         # total shots that need work
              "by_status": {status: count},
              "total_seconds_serial": float,     # if rendered 1-at-a-time
              "total_seconds_parallel": float,   # given max_concurrent workers
              "avg_seconds_per_shot": float,
              "avg_source": "per-shot" | "board" | "preset-hint" | "default",
              "per_shot": [{"id": "...", "status": "...", "estimate_s": float}],
            }

        Falls back through three estimators per shot:
          1. This shot's own render_history (most accurate — learned)
          2. The board-wide average_render_time() (avg of all shots)
          3. 120s default (placeholder for a brand-new board).
        """
        global_avg = self.average_render_time()
        by_status: Dict[str, int] = {}
        per_shot: List[Dict[str, Any]] = []
        total_serial = 0.0
        sources: set = set()

        for shot in self._shots:
            if shot.status == "ready":
                continue
            by_status[shot.status] = by_status.get(shot.status, 0) + 1
            # Per-shot history
            durations = [e.get("duration_s") for e in (shot.render_history or [])
                         if isinstance(e.get("duration_s"), (int, float))
                         and e.get("status") == "ready"]
            if durations:
                estimate = sum(durations) / len(durations)
                source = "per-shot"
            elif shot.render_duration_s and shot.render_duration_s > 0:
                estimate = float(shot.render_duration_s)
                source = "per-shot"
            elif global_avg > 0:
                estimate = global_avg
                source = "board"
            elif shot.target_duration_s:
                # Weak hint — target playback duration isn't render time,
                # but it's a better guess than 120s when nothing else exists.
                estimate = float(shot.target_duration_s) * 3
                source = "preset-hint"
            else:
                estimate = 120.0
                source = "default"
            sources.add(source)
            total_serial += estimate
            per_shot.append({
                "id": shot.id,
                "status": shot.status,
                "estimate_s": round(estimate, 1),
                "source": source,
            })

        mc = max(1, int(max_concurrent))
        total_parallel = total_serial / mc if per_shot else 0.0

        # Dominant source reporting — the one that fired most often
        if per_shot:
            src_counts: Dict[str, int] = {}
            for row in per_shot:
                src_counts[row["source"]] = src_counts.get(row["source"], 0) + 1
            dominant_source = max(src_counts.items(), key=lambda x: x[1])[0]
            avg = total_serial / len(per_shot)
        else:
            dominant_source = "none"
            avg = 0.0

        return {
            "pending_count": len(per_shot),
            "by_status": by_status,
            "total_seconds_serial": round(total_serial, 1),
            "total_seconds_parallel": round(total_parallel, 1),
            "avg_seconds_per_shot": round(avg, 1),
            "avg_source": dominant_source,
            "per_shot": per_shot,
        }

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

    # ─── R69a: Named board states (whole-board save/restore) ───────────

    def _named_states_dir(self) -> str:
        """Where named-state snapshots live. One JSON file per name."""
        d = os.path.join(os.path.dirname(self.path), "named_states")
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def _sanitize_state_name(name: str) -> str:
        """Filesystem-safe version of a user-provided state name."""
        import re
        s = re.sub(r"[^\w\-\. ]", "_", (name or "").strip())
        return s.replace(" ", "_")[:80] or "state"

    def save_named_state(self, name: str) -> Dict[str, Any]:
        """R69a: Snapshot the entire board (shots + scenes) to a named
        file. User can later restore to this exact state.
        Overwrites if the name exists."""
        safe = self._sanitize_state_name(name)
        if not safe:
            return {"status": "error", "message": "empty name"}
        payload = {
            "version": 1,
            "saved_at": time.time(),
            "name": name.strip(),
            "shots": [s.to_dict() for s in self._shots],
            "scenes": [sc.to_dict() if hasattr(sc, "to_dict") else dict(sc.__dict__)
                        for sc in self._scenes],
        }
        path = os.path.join(self._named_states_dir(), f"{safe}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except OSError as e:
            return {"status": "error", "message": f"write failed: {e}"}
        return {"status": "ok", "name": name.strip(), "file": path,
                "shot_count": len(self._shots),
                "scene_count": len(self._scenes)}

    def list_named_states(self) -> List[Dict[str, Any]]:
        """Return all saved named states with summary info."""
        d = self._named_states_dir()
        results: List[Dict[str, Any]] = []
        try:
            entries = os.listdir(d)
        except OSError:
            return results
        for entry in entries:
            if not entry.endswith(".json"):
                continue
            path = os.path.join(d, entry)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            results.append({
                "name": data.get("name", entry[:-5]),
                "file_name": entry,
                "saved_at": data.get("saved_at"),
                "shot_count": len(data.get("shots") or []),
                "scene_count": len(data.get("scenes") or []),
            })
        results.sort(key=lambda x: x.get("saved_at") or 0, reverse=True)
        return results

    def load_named_state(self, name: str, *,
                          merge: bool = False) -> Dict[str, Any]:
        """Restore a named state. Default (merge=False) replaces the
        current board entirely. merge=True appends the saved shots +
        scenes to what's currently loaded."""
        safe = self._sanitize_state_name(name)
        path = os.path.join(self._named_states_dir(), f"{safe}.json")
        if not os.path.isfile(path):
            return {"status": "error", "message": f"no state named {name!r}"}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return {"status": "error", "message": f"read failed: {e}"}
        shots = [Shot.from_dict(s) for s in (data.get("shots") or [])
                 if isinstance(s, dict)]
        scenes = []
        for sc_d in (data.get("scenes") or []):
            if not isinstance(sc_d, dict):
                continue
            if hasattr(Scene, "from_dict"):
                try:
                    scenes.append(Scene.from_dict(sc_d))
                    continue
                except Exception:
                    pass
            # Fallback: construct with best-effort kwargs
            known = {f.name for f in Scene.__dataclass_fields__.values()} \
                if hasattr(Scene, "__dataclass_fields__") else set()
            scenes.append(Scene(**{k: v for k, v in sc_d.items() if k in known}))
        if merge:
            self._shots.extend(shots)
            self._scenes.extend(scenes)
        else:
            self._shots = shots
            self._scenes = scenes
        self._reindex()
        self.save()
        return {"status": "ok", "name": name.strip(),
                "loaded_shots": len(shots),
                "loaded_scenes": len(scenes),
                "merge": merge}

    def delete_named_state(self, name: str) -> Dict[str, Any]:
        """Delete a saved state file."""
        safe = self._sanitize_state_name(name)
        path = os.path.join(self._named_states_dir(), f"{safe}.json")
        try:
            os.remove(path)
            return {"status": "ok", "name": name.strip()}
        except FileNotFoundError:
            return {"status": "error", "message": "not found"}
        except OSError as e:
            return {"status": "error", "message": str(e)}

    def shotboard_to_csv(self) -> str:
        """R69b: emit the current board as a CSV that round-trips
        through R67a's import_shots_from_csv. Columns match the
        importer's accept list."""
        import csv
        import io
        cols = ["title", "prompt", "negative", "preset", "seed",
                 "notes", "backend", "color_label", "priority",
                 "target_duration_s", "carry_last_frame", "depends_on"]
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(cols)
        # Build id→title map so depends_on refs are human-readable
        id_to_title = {s.id: (s.title or "") for s in self._shots}
        for s in self._shots:
            dep_titles = [id_to_title.get(d, d) for d in (s.depends_on or [])
                           if d in id_to_title]
            writer.writerow([
                s.title or "",
                s.prompt or "",
                s.negative or "",
                s.preset or "",
                s.seed if s.seed is not None else "",
                s.notes or "",
                s.backend or "",
                s.color_label or "",
                s.priority or "normal",
                s.target_duration_s if s.target_duration_s is not None else "",
                "true" if s.carry_last_frame else "false",
                ",".join(dep_titles),
            ])
        return buf.getvalue()

    def ready_videos(self) -> List[str]:
        """Return the ordered list of completed mp4 paths, skipping gaps."""
        return [s.video_path for s in self._shots
                if s.status == "ready" and s.video_path]

    # ─── R47a: EDL / FCPXML export for DaVinci Resolve etc. ───────────

    def _shot_duration_frames(self, shot: "Shot", fps: int) -> int:
        """Estimate how many frames a shot occupies at the target ``fps``.
        Priority order: render_duration_s (actual) → target_duration_s
        (user intent) → duration_s (preset hint) → 2.0 seconds default.
        Always returns at least 1 frame so timelines stay monotonic.
        """
        seconds = (shot.render_duration_s
                   or shot.target_duration_s
                   or shot.duration_s
                   or 2.0)
        return max(1, int(round(seconds * fps)))

    @staticmethod
    def _frames_to_tc(frames: int, fps: int) -> str:
        """Convert frame count to HH:MM:SS:FF timecode (non-drop-frame)."""
        fps = max(1, int(fps))
        total_seconds, ff = divmod(frames, fps)
        hh, rem = divmod(total_seconds, 3600)
        mm, ss = divmod(rem, 60)
        return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

    def export_edl(self, fps: int = 30, title: str = "") -> str:
        """Emit a CMX 3600 EDL referencing each ready shot as one event.

        R71b: `title` defaults to project_meta['title'] when empty;
        falls back to "Spellcaster Timeline" if no project title set.

        Only shots with status=="ready" AND a video_path are exported.
        Non-ready shots are skipped silently — EDLs don't represent gaps
        cleanly, and the user can re-export once more shots land.

        Timecode is non-drop-frame starting at 00:00:00:00. Resolve's
        File > Import > Timeline > EDL will happily build a timeline
        from this. Reel names are derived from the shot title, slugified,
        capped at 8 chars per CMX 3600 tradition.
        """
        if not title:
            title = self._project_meta.get("title") or "Spellcaster Timeline"
        lines = [f"TITLE: {title}", f"FCM: NON-DROP FRAME", ""]
        event = 1
        src_cursor = 0  # each clip starts at 0 in its own source
        rec_cursor = 0
        for shot in self._shots:
            if shot.status != "ready" or not shot.video_path:
                continue
            dur = self._shot_duration_frames(shot, fps)
            reel = _slugify_reel(shot.title or f"shot{shot.index+1}")
            src_in = Shotboard._frames_to_tc(0, fps)
            src_out = Shotboard._frames_to_tc(dur, fps)
            rec_in = Shotboard._frames_to_tc(rec_cursor, fps)
            rec_out = Shotboard._frames_to_tc(rec_cursor + dur, fps)
            lines.append(
                f"{event:03d}  {reel:<8} V     C        "
                f"{src_in} {src_out} {rec_in} {rec_out}"
            )
            # Source-file hint: Resolve reads this as * FROM CLIP NAME
            lines.append(f"* FROM CLIP NAME: {os.path.basename(shot.video_path)}")
            if shot.title:
                lines.append(f"* COMMENT: {shot.title}")
            lines.append("")
            rec_cursor += dur
            event += 1
        return "\n".join(lines) + "\n"

    def export_fcpxml(self, fps: int = 30, title: str = "") -> str:
        """Emit an FCPXML v1.10 document representing the ready shots
        as a single timeline. Preferred over EDL for Resolve because it
        preserves clip names, reference paths, and gaps.

        Missing shots are NOT represented as gaps (FCPXML would need
        explicit gap elements); they're simply omitted so the timeline
        stays contiguous.

        R71b: `title` defaults to project_meta['title'] when empty.
        """
        if not title:
            title = self._project_meta.get("title") or "Spellcaster Timeline"
        fps = max(1, int(fps))
        # FCPXML uses rational time: N/Dsec, with frame duration as 1/fps
        fd = f"1/{fps}s"
        events_xml = []
        cursor = 0
        asset_id = 1
        assets = []
        clips = []
        for shot in self._shots:
            if shot.status != "ready" or not shot.video_path:
                continue
            dur = self._shot_duration_frames(shot, fps)
            src = _xml_escape(shot.video_path)
            name = _xml_escape(shot.title or f"Shot {shot.index+1}")
            assets.append(
                f'    <asset id="r{asset_id}" name="{name}" src="file://{src}" '
                f'start="0s" duration="{dur}/{fps}s" hasVideo="1" format="r1"/>'
            )
            clips.append(
                f'                    <asset-clip name="{name}" ref="r{asset_id}" '
                f'offset="{cursor}/{fps}s" duration="{dur}/{fps}s" start="0s"/>'
            )
            cursor += dur
            asset_id += 1
        assets_block = "\n".join(assets) if assets else ""
        clips_block = "\n".join(clips) if clips else ""
        total = cursor
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE fcpxml>\n'
            '<fcpxml version="1.10">\n'
            '  <resources>\n'
            f'    <format id="r1" name="FFVideoFormat1080p{fps}" '
            f'frameDuration="{fd}" width="1920" height="1080"/>\n'
            f'{assets_block}\n'
            '  </resources>\n'
            '  <library>\n'
            f'    <event name="{_xml_escape(title)}">\n'
            f'      <project name="{_xml_escape(title)}">\n'
            f'        <sequence format="r1" duration="{total}/{fps}s" tcStart="0s">\n'
            '          <spine>\n'
            f'{clips_block}\n'
            '          </spine>\n'
            '        </sequence>\n'
            '      </project>\n'
            '    </event>\n'
            '  </library>\n'
            '</fcpxml>\n'
        )

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

    # ─── R46a: auto-snapshot before destructive batch operations ─────

    def _auto_snapshot_batch(self, shot_ids: List[str], op_label: str) -> int:
        """Save a "Auto: <op>" snapshot on every unlocked shot in ``shot_ids``
        before a destructive batch operation runs.

        Returns the count of snapshots taken. Skips locked shots (they
        can't be restored anyway) and shots that don't exist.

        The snapshot uses the same machinery as user-driven save_snapshot
        — max 20 per shot, oldest pruned. Auto-snapshots compete with
        user snapshots for the 20-slot window, but that's acceptable:
        either way a user can only restore what's currently kept.
        """
        taken = 0
        for sid in shot_ids:
            shot = self.get(sid)
            if shot is None or shot.locked:
                continue
            snap = self.save_snapshot(sid, label=f"Auto: {op_label}")
            if snap is not None:
                taken += 1
        return taken

    def batch_revert(self, shot_ids: List[str],
                     snapshot_before: bool = True) -> Dict[str, Any]:
        """Revert multiple shots to their last rendered settings.

        When ``snapshot_before`` is True (default), each affected shot
        gets an "Auto: before batch-revert" snapshot first so the user
        can undo the revert with a restore.

        Returns a summary dict with 'reverted' count and 'skipped' count.
        Skipped shots are locked, have no history, or don't exist.
        """
        auto_snapped = 0
        if snapshot_before:
            auto_snapped = self._auto_snapshot_batch(shot_ids, "before batch-revert")
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
        return {"reverted": reverted, "skipped": skipped, "auto_snapshots": auto_snapped}

    def batch_prompt_edit(self, shot_ids: List[str], prefix: str = "",
                          suffix: str = "", mode: str = "add",
                          snapshot_before: bool = True) -> Dict[str, Any]:
        """Add or remove a prefix/suffix to/from prompts of multiple shots.

        mode='add': prepend prefix and/or append suffix to each shot's prompt.
        mode='remove': strip prefix from start and/or suffix from end.
        Locked shots are skipped.

        Returns {'modified': int, 'skipped': int}.
        """
        auto_snapped = 0
        if snapshot_before:
            auto_snapped = self._auto_snapshot_batch(shot_ids, "before prompt edit")
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
        return {"modified": modified, "skipped": skipped,
                "auto_snapshots": auto_snapped}

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
        # R47b: prune oldest UNPINNED when cap hit; pinned always survive
        if len(shot.snapshots) > 20:
            pinned_ids = set(shot.pinned_snapshots or [])
            pinned = [s for s in shot.snapshots if s.get("id") in pinned_ids]
            unpinned = [s for s in shot.snapshots if s.get("id") not in pinned_ids]
            keep_unpinned = max(0, 20 - len(pinned))
            unpinned = unpinned[-keep_unpinned:] if keep_unpinned > 0 else []
            # Re-interleave to preserve chronological order (id-based)
            keep = set(s["id"] for s in pinned) | set(s["id"] for s in unpinned)
            shot.snapshots = [s for s in shot.snapshots if s.get("id") in keep]
        shot.touch()
        self.save()
        return snap

    def list_snapshots(self, shot_id: str) -> List[Dict[str, Any]]:
        """Return shallow copies of this shot's snapshots (newest last)."""
        shot = self.get(shot_id)
        if shot is None:
            return []
        return [dict(s) for s in shot.snapshots]

    def preview_snapshot_restore(self, shot_id: str, snap_id: str
                                   ) -> Optional[Dict[str, Any]]:
        """R60a: Report what a `restore_snapshot` would change WITHOUT
        mutating state. Returns per-field diff entries:

            {"shot_id": "...", "snap_id": "...", "snap_label": "...",
             "locked": False, "changes": [
                {"field": "prompt", "from": "old", "to": "new"},
                {"field": "preset", "from": "fast", "to": "quality"},
                ...
             ]}

        Returns None if shot or snapshot don't exist. Locked shots
        return the diff with locked=True so the UI can warn "this
        restore would be refused".
        """
        shot = self.get(shot_id)
        if shot is None:
            return None
        snap = next((s for s in shot.snapshots if s.get("id") == snap_id), None)
        if snap is None:
            return None
        changes: List[Dict[str, Any]] = []
        for key in self._SNAPSHOT_FIELDS:
            if key not in snap:
                continue
            current = getattr(shot, key, None)
            target = snap[key]
            if key == "trajectories":
                # Normalize both sides to dicts for comparison
                current_n = [t.to_dict() if hasattr(t, "to_dict") else dict(t)
                              for t in (current or [])]
                target_n = [dict(t) for t in (target or [])]
                if current_n != target_n:
                    changes.append({
                        "field": key,
                        "from": f"{len(current_n)} trajectorie(s)",
                        "to": f"{len(target_n)} trajectorie(s)",
                    })
                continue
            if current != target:
                changes.append({
                    "field": key,
                    "from": current,
                    "to": target,
                })
        return {
            "shot_id": shot_id,
            "snap_id": snap_id,
            "snap_label": snap.get("label", ""),
            "snap_created_at": snap.get("created_at"),
            "locked": bool(shot.locked),
            "changes": changes,
        }

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
        """Remove a snapshot by id. Returns True if one was removed.
        Also unpins it (R47b) so stale pin ids don't accumulate.
        """
        shot = self.get(shot_id)
        if shot is None:
            return False
        before = len(shot.snapshots)
        shot.snapshots = [s for s in shot.snapshots if s.get("id") != snap_id]
        if len(shot.snapshots) < before:
            if shot.pinned_snapshots and snap_id in shot.pinned_snapshots:
                shot.pinned_snapshots = [p for p in shot.pinned_snapshots if p != snap_id]
            shot.touch()
            self.save()
            return True
        return False

    def pin_snapshot(self, shot_id: str, snap_id: str) -> bool:
        """R47b: Mark a snapshot as pinned so it won't auto-prune."""
        shot = self.get(shot_id)
        if shot is None:
            return False
        if not any(s.get("id") == snap_id for s in shot.snapshots):
            return False
        if snap_id in shot.pinned_snapshots:
            return True  # already pinned = idempotent success
        shot.pinned_snapshots.append(snap_id)
        shot.touch()
        self.save()
        return True

    def unpin_snapshot(self, shot_id: str, snap_id: str) -> bool:
        """R47b: Remove a snapshot from the pinned list."""
        shot = self.get(shot_id)
        if shot is None or snap_id not in (shot.pinned_snapshots or []):
            return False
        shot.pinned_snapshots = [p for p in shot.pinned_snapshots if p != snap_id]
        shot.touch()
        self.save()
        return True

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
