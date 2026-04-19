"""
Cinematographer Wizard — shot-centric video orchestrator.

This is the video analogue of ``WorkflowWizard``.  It adds a new
creative primitive the other wizards don't model: a **sequence of
shots** driven through heterogeneous backends, with state that
persists across chat sessions.

Flow::

    user says "I want to film 4 shots"
        │
        ▼
    CinematographerWizard.handle()  ───►  creates/loads Shotboard
        │
        ▼
    step 1: "new shot" prompt menu  ──► add Shot(draft)
    step 2: backend picker           ──► pick WanGP preset OR ComfyUI workflow
    step 3: inputs (ref image + traj) ──► may open Wan-Move side-panel
    step 4: confirm                  ──► hand off to runner

The wizard only *configures* shots.  Actual queuing lives in
``VideoBridge`` (see scaffold.video_bridge) so this module stays
synchronous and easy to unit-test.

Like WorkflowWizard, the wizard speaks a numbered-menu protocol so
small-parameter LLMs (7B Qwen on the user's machine) can drive it
reliably — see README §"Three-layer scaffold system".

Zero deps beyond stdlib.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .shotboard import Shotboard, Shot, Trajectory
from .wangp_runner import WANGP_PRESETS, describe_preset, preset_names

log = logging.getLogger("spellcaster.video_wizard")


# R121: when the DaVinci Resolve Bridge is online, the wizard reports
# it in every reply + adds Resolve-specific menu actions. The status
# callable is injected by VideoBridge; signature:
#
#   resolve_status_fn() -> Optional[dict]
#
# Returns a dict with at least {online: bool, bin: str,
# timeline_name: str|None} when the Bridge is heartbeating, or None
# when it's offline / not installed / the caller doesn't have
# access to the interface registry. The wizard keeps working either
# way — the Resolve-aware path is pure bonus on top of the normal
# flow.
ResolveStatusFn = Callable[[], Optional[Dict[str, Any]]]


# -----------------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------------

# Lightweight finite-state machine.  Keeping explicit strings (rather
# than an Enum) mirrors how WorkflowWizard tracks session state.
STEP_IDLE = "idle"
STEP_PICK_ACTION = "pick_action"
STEP_EDIT_TITLE = "edit_title"
STEP_EDIT_PROMPT = "edit_prompt"
STEP_PICK_BACKEND = "pick_backend"
STEP_PICK_PRESET = "pick_preset"
STEP_PICK_REF = "pick_ref"
STEP_TRAJECTORIES = "trajectories"
STEP_REVIEW = "review"


ACTIONS = [
    ("new", "Add a new shot"),
    ("edit", "Edit an existing shot"),
    ("reorder", "Reorder shots"),
    ("remove", "Remove a shot"),
    ("render", "Queue a shot for rendering"),
    ("status", "Show board status"),
    ("done", "Exit the video wizard"),
]

# R121: extra Resolve-native actions injected when the Bridge is live.
RESOLVE_ACTIONS = [
    ("resolve_pull",      "Pull reference from Resolve playhead"),
    ("resolve_import",    "Push shotboard to Resolve timeline (EDL)"),
    ("resolve_status",    "Show Resolve Bridge status"),
]


@dataclass
class VideoSession:
    """Per-user wizard state.  One of these per chat participant."""
    user_id: str
    step: str = STEP_IDLE
    # The shot currently being edited (id)
    current_shot_id: Optional[str] = None
    # Free-form scratchpad — e.g. partial reorder list
    scratch: Dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        self.step = STEP_IDLE
        self.current_shot_id = None
        self.scratch.clear()


# -----------------------------------------------------------------------------
# Wizard
# -----------------------------------------------------------------------------

class CinematographerWizard:
    """LLM-friendly wizard that edits a Shotboard in place.

    Responsibilities:
      - Drive the user through a numbered-menu conversation.
      - Maintain one VideoSession per user.
      - Emit structured "commit" actions the VideoBridge picks up.

    Non-responsibilities (handled elsewhere):
      - Actually running generation → see VideoBridge / WanGPRunner.
      - Drawing trajectories → handed off to the web UI, which calls
        ``commit_trajectories()`` when the user is done drawing.
    """

    def __init__(self, shotboard: Shotboard,
                 resolve_status_fn: Optional[ResolveStatusFn] = None,
                 resolve_action_fn: Optional[Callable[[str, Dict[str, Any]],
                                                       Dict[str, Any]]] = None):
        """shotboard: the shared Shotboard instance.

        resolve_status_fn: optional callable returning a dict with
          {online, bin, timeline_name} when the Resolve Bridge is
          heartbeating. Injected by VideoBridge from the Guild's
          interface_registry. Lets the wizard tailor every reply to
          mention Resolve when appropriate.

        resolve_action_fn: optional callable(action_key, payload) ->
          result dict. Invoked when the user picks a Resolve-native
          menu item. VideoBridge wires this to HTTP calls against
          the paired antenna (e.g. /resolve/playhead-grab for
          pulling a ref frame, /resolve/import-edl for pushing a
          timeline).
        """
        self.board = shotboard
        self._sessions: Dict[str, VideoSession] = {}
        self._resolve_status_fn = resolve_status_fn
        self._resolve_action_fn = resolve_action_fn

    # ------------------------------------------------------------------
    # Resolve-awareness helpers
    # ------------------------------------------------------------------

    def _resolve_info(self) -> Optional[Dict[str, Any]]:
        """Fresh snapshot of the Resolve Bridge status. None when the
        Bridge is offline or the status fn wasn't injected. Safe to
        call every handler tick — the fn is expected to be cheap."""
        if not self._resolve_status_fn:
            return None
        try:
            info = self._resolve_status_fn()
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(info, dict) or not info.get("online"):
            return None
        return info

    def _resolve_banner(self) -> str:
        """One-line banner prepended to every wizard reply when the
        Bridge is live. Empty string when offline — no visual weight."""
        info = self._resolve_info()
        if not info:
            return ""
        bin_path = info.get("bin") or "Spellcaster"
        host = info.get("hostname") or ""
        tl = info.get("timeline_name") or ""
        parts = [f"🎬 **Resolve Bridge live**"]
        if host:
            parts.append(f"@ {host}")
        parts.append(f"— renders auto-import to `{bin_path}/`")
        if tl:
            parts.append(f"(active timeline: {tl})")
        return " ".join(parts) + "\n\n"

    def _actions(self) -> List[tuple]:
        """ACTIONS + RESOLVE_ACTIONS when Bridge is live. Otherwise
        plain ACTIONS. Indices in user replies stay stable within one
        conversation turn (they see the same menu they're replying
        to)."""
        if self._resolve_info():
            # Insert Resolve actions before "done" so "Exit" stays last
            return (ACTIONS[:-1] + RESOLVE_ACTIONS + [ACTIONS[-1]])
        return list(ACTIONS)

    # ------------------------------------------------------------------
    # Session plumbing
    # ------------------------------------------------------------------

    def session(self, user_id: str) -> VideoSession:
        sess = self._sessions.get(user_id)
        if not sess:
            sess = VideoSession(user_id=user_id)
            self._sessions[user_id] = sess
        return sess

    def reset(self, user_id: str) -> None:
        if user_id in self._sessions:
            self._sessions[user_id].reset()

    # ------------------------------------------------------------------
    # Main entry — handle one user turn
    # ------------------------------------------------------------------

    def handle(self, user_id: str, text: str) -> str:
        """Process one user message, return a reply string.

        The reply is plain text with numbered options where applicable —
        the Wizard Guild frontend auto-parses numbered menus into
        clickable buttons.
        """
        sess = self.session(user_id)
        text = (text or "").strip()

        # Global escape hatch
        if text.lower() in ("cancel", "back", "menu"):
            sess.reset()
            return self._render_menu()

        dispatch = {
            STEP_IDLE: self._handle_idle,
            STEP_PICK_ACTION: self._handle_pick_action,
            STEP_EDIT_TITLE: self._handle_edit_title,
            STEP_EDIT_PROMPT: self._handle_edit_prompt,
            STEP_PICK_BACKEND: self._handle_pick_backend,
            STEP_PICK_PRESET: self._handle_pick_preset,
            STEP_PICK_REF: self._handle_pick_ref,
            STEP_TRAJECTORIES: self._handle_trajectories,
            STEP_REVIEW: self._handle_review,
        }
        handler = dispatch.get(sess.step, self._handle_idle)
        try:
            return handler(sess, text)
        except Exception as exc:  # noqa: BLE001
            log.exception("CinematographerWizard handler failed")
            sess.reset()
            return (f"Something went sideways: {exc}\n\n"
                    + self._render_menu())

    # ------------------------------------------------------------------
    # Step handlers
    # ------------------------------------------------------------------

    def _handle_idle(self, sess: VideoSession, text: str) -> str:
        sess.step = STEP_PICK_ACTION
        return self._render_menu()

    def _handle_pick_action(self, sess: VideoSession, text: str) -> str:
        actions = self._actions()
        idx = _parse_index(text, len(actions))
        if idx is None:
            return ("Please pick a number from the list:\n\n"
                    + self._render_menu())
        key, _ = actions[idx]
        if key == "done":
            sess.reset()
            return "Leaving the video wizard. Your shotboard is saved."
        if key == "status":
            return self._render_status()
        if key == "new":
            shot = self.board.add(Shot(title=f"Shot {len(self.board) + 1}"))
            sess.current_shot_id = shot.id
            sess.step = STEP_EDIT_TITLE
            return (f"Created shot #{shot.index + 1}. What should I call "
                    f"this shot? (e.g. 'INT. kitchen - morning')")
        if key == "edit":
            return self._start_edit(sess)
        if key == "remove":
            return self._start_remove(sess)
        if key == "reorder":
            return self._start_reorder(sess)
        if key == "render":
            return self._start_render(sess)
        # R121: Resolve-native actions. Each delegates to
        # self._resolve_action_fn for the actual HTTP call — the
        # wizard just frames the conversation.
        if key == "resolve_pull":
            return self._handle_resolve_pull(sess)
        if key == "resolve_import":
            return self._handle_resolve_import(sess)
        if key == "resolve_status":
            return self._render_resolve_status()
        return self._render_menu()

    # ------------------------------------------------------------------
    # R121: Resolve-native handlers
    # ------------------------------------------------------------------

    def _render_resolve_status(self) -> str:
        info = self._resolve_info()
        if not info:
            return ("🎬 Resolve Bridge is **offline**. Start Resolve on a "
                     "paired antenna and run the bridge plugin, then try "
                     "again.\n\n" + self._render_menu())
        lines = [self._resolve_banner().rstrip() or "🎬 Resolve Bridge live."]
        lines.append("")
        for k in ("hostname", "bin", "timeline_name", "agent_url",
                    "last_heartbeat"):
            if info.get(k):
                lines.append(f"  • {k}: {info[k]}")
        lines.append("")
        lines.append(self._render_menu())
        return "\n".join(lines)

    def _handle_resolve_pull(self, sess: VideoSession) -> str:
        """Create a new shot seeded from the frame currently under
        Resolve's playhead. Uses the paired antenna's grab-and-publish
        flow; the wizard returns immediately and the frame is attached
        as soon as the antenna call resolves. Without a paired antenna
        we fall back to an explanation."""
        if not self._resolve_action_fn:
            return ("🎬 Resolve Bridge is online but this Guild isn't "
                     "paired to the antenna hosting it. Pair via "
                     "Settings > Antenna, then retry.\n\n"
                     + self._render_menu())
        try:
            result = self._resolve_action_fn("pull_playhead", {})
        except Exception as e:  # noqa: BLE001
            return f"🎬 Pull failed: {e}\n\n" + self._render_menu()
        if not result or result.get("error"):
            err = (result or {}).get("error", "no response")
            return f"🎬 Pull failed: {err}\n\n" + self._render_menu()
        shot_id = result.get("shot_id") or ""
        return (
            f"🎬 Pulled playhead frame → shot {shot_id[:8]}.\n"
            f"The reference image is attached. Run **1. Add a new shot**'s "
            f"prompt step next, or **5. Queue a shot for rendering** to "
            f"send it through Wan i2v immediately.\n\n"
            + self._render_menu())

    def _handle_resolve_import(self, sess: VideoSession) -> str:
        """Ask the Bridge to import the current shotboard as an EDL
        timeline in Resolve. Wraps the same /api/video/export/edl
        endpoint R97's 'Import Guild Timeline' Resolve script uses,
        triggered from this side via an event."""
        if not self._resolve_action_fn:
            return ("🎬 Resolve Bridge is online but this Guild isn't "
                     "paired. Pair first.\n\n" + self._render_menu())
        shots = self.board.all()
        ready = [s for s in shots
                   if (s.status or "").lower() == "ready"]
        if not ready:
            return ("🎬 No ready shots yet — render some first. "
                     "Once an EDL is populated we can push it to "
                     "Resolve.\n\n" + self._render_menu())
        try:
            result = self._resolve_action_fn("import_edl", {
                "shot_count": len(ready),
            })
        except Exception as e:  # noqa: BLE001
            return f"🎬 Import failed: {e}\n\n" + self._render_menu()
        if not result or result.get("error"):
            err = (result or {}).get("error", "no response")
            return f"🎬 Import failed: {err}\n\n" + self._render_menu()
        tl = result.get("timeline_name") or "Spellcaster"
        return (
            f"🎬 Sent {len(ready)} shot(s) to Resolve as timeline "
            f"'{tl}'. Check Resolve's timeline list — the new one "
            f"should be active.\n\n" + self._render_menu())

    # ---- title / prompt capture ------------------------------------

    def _handle_edit_title(self, sess: VideoSession, text: str) -> str:
        shot = self._must_current(sess)
        if not shot:
            return self._render_menu()
        if text:
            self.board.update(shot.id, title=text)
        sess.step = STEP_EDIT_PROMPT
        return (f"Got it. Now describe the shot — what should happen "
                f"on screen? (one to three sentences)\n\n"
                f"Example: 'a wolf walks through snowy pines at dusk, "
                f"slow camera tracking from the side, falling snow'")

    def _handle_edit_prompt(self, sess: VideoSession, text: str) -> str:
        shot = self._must_current(sess)
        if not shot:
            return self._render_menu()
        if text:
            self.board.update(shot.id, prompt=text)
        sess.step = STEP_PICK_BACKEND
        return self._render_backend_menu()

    # ---- backend + preset ------------------------------------------

    def _handle_pick_backend(self, sess: VideoSession, text: str) -> str:
        options = ["wangp", "comfyui", "hybrid"]
        idx = _parse_index(text, len(options))
        if idx is None:
            return ("Pick a number:\n\n" + self._render_backend_menu())
        backend = options[idx]
        shot = self._must_current(sess)
        if shot:
            self.board.update(shot.id, backend=backend)
        sess.step = STEP_PICK_PRESET
        return self._render_preset_menu(backend)

    def _handle_pick_preset(self, sess: VideoSession, text: str) -> str:
        shot = self._must_current(sess)
        if not shot:
            return self._render_menu()
        if shot.backend == "wangp":
            keys = preset_names()
        else:
            # For now, ComfyUI branch uses a fixed short list mirroring
            # scaffold/workflows/.  The real WorkflowWizard discovers
            # these dynamically — we borrow that capability when wired.
            keys = ["ltx2_image_to_video",
                    "ltx2_text_to_video",
                    "ltx2_t2v_with_rife_interpolation",
                    "ltx2_t2v_with_rtx_upscale"]
        idx = _parse_index(text, len(keys))
        if idx is None:
            return ("Pick a number:\n\n"
                    + self._render_preset_menu(shot.backend))
        chosen = keys[idx]
        self.board.update(shot.id, preset=chosen)

        # Ref image required?
        if shot.backend == "wangp":
            spec = describe_preset(chosen)
            needs_ref = "image" in (spec.get("inputs") or [])
            needs_traj = "trajectories" in (spec.get("inputs") or [])
        else:
            needs_ref = "image_to_video" in chosen
            needs_traj = False

        if needs_ref:
            sess.step = STEP_PICK_REF
            return ("This preset needs a reference image. "
                    "Upload an image in the chat, or paste an absolute "
                    "path on disk and I'll grab it.")
        if needs_traj:
            sess.step = STEP_TRAJECTORIES
            return ("This preset uses motion trajectories. Open the "
                    "Trajectory panel in the Guild UI — I'll wait.")
        sess.step = STEP_REVIEW
        return self._render_review(shot)

    def _handle_pick_ref(self, sess: VideoSession, text: str) -> str:
        shot = self._must_current(sess)
        if not shot:
            return self._render_menu()
        # The actual upload bytes come through a separate API endpoint
        # (see VideoBridge.attach_reference).  Here we only accept a
        # path-style text fallback.
        if not text:
            return ("I need a reference image. Upload one in the "
                    "Guild UI, or paste its absolute path.")
        if not os.path.isfile(text):
            return (f"I can't find a file at {text!r}. "
                    f"Upload via the UI or paste a valid absolute path.")
        self.board.update(shot.id, ref_image=os.path.abspath(text))
        spec = describe_preset(shot.preset)
        if "trajectories" in (spec.get("inputs") or []):
            sess.step = STEP_TRAJECTORIES
            return ("Got the reference. Now open the Trajectory panel "
                    "to draw the motion paths, then say 'done'.")
        sess.step = STEP_REVIEW
        return self._render_review(shot)

    def _handle_trajectories(self, sess: VideoSession, text: str) -> str:
        shot = self._must_current(sess)
        if not shot:
            return self._render_menu()
        if text.lower() not in ("done", "ok", "ready"):
            return ("When you've finished drawing trajectories in the "
                    "Guild UI, say 'done' here.")
        if not shot.trajectories:
            return ("I don't see any trajectories for this shot yet. "
                    "Draw at least one path in the UI, or say 'skip' "
                    "to render without trajectories.")
        sess.step = STEP_REVIEW
        return self._render_review(shot)

    def _handle_review(self, sess: VideoSession, text: str) -> str:
        shot = self._must_current(sess)
        if not shot:
            return self._render_menu()
        opts = ["Queue it", "Edit title", "Edit prompt",
                "Change preset", "Cancel"]
        idx = _parse_index(text, len(opts))
        if idx is None:
            return self._render_review(shot)
        if idx == 0:
            # Caller (VideoBridge) should pick this up via
            # ``get_pending_render()`` — we just flag the session.
            pending_id = shot.id
            sess.reset()
            sess.scratch["pending_render"] = pending_id
            return (f"Shot '{shot.title}' is ready. "
                    f"Calling the video bridge now…")
        if idx == 1:
            sess.step = STEP_EDIT_TITLE
            return f"Current title: {shot.title!r}. What should it be?"
        if idx == 2:
            sess.step = STEP_EDIT_PROMPT
            return f"Current prompt: {shot.prompt!r}. What should it be?"
        if idx == 3:
            sess.step = STEP_PICK_BACKEND
            return self._render_backend_menu()
        sess.reset()
        return "Cancelled. Back to the main menu.\n\n" + self._render_menu()

    # ------------------------------------------------------------------
    # Commit helpers (called from the web UI, not the chat)
    # ------------------------------------------------------------------

    def commit_reference(self, shot_id: str, path: str) -> Optional[Shot]:
        """Attach an uploaded reference image to a shot.

        The Guild UI uploads the file, saves it somewhere on disk, then
        calls this.  Bypasses the chat flow so drag-and-drop works.
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        return self.board.update(shot_id, ref_image=os.path.abspath(path))

    def commit_trajectories(self, shot_id: str,
                            trajectories: List[Dict[str, Any]]
                            ) -> Optional[Shot]:
        """Store trajectories drawn in the UI against a shot."""
        objs = [Trajectory.from_dict(t) for t in trajectories]
        return self.board.update(shot_id, trajectories=objs)

    def get_pending_render(self, user_id: str) -> Optional[str]:
        """Pop the 'ready to render' flag if the user just confirmed."""
        sess = self._sessions.get(user_id)
        if not sess:
            return None
        return sess.scratch.pop("pending_render", None)

    # ------------------------------------------------------------------
    # Sub-flow starters
    # ------------------------------------------------------------------

    def _start_edit(self, sess: VideoSession) -> str:
        shots = self.board.all()
        if not shots:
            sess.reset()
            return ("No shots yet. Pick 'Add a new shot' to get going.\n\n"
                    + self._render_menu())
        lines = ["Which shot? (pick a number)"]
        for i, s in enumerate(shots, 1):
            lines.append(f"{i}. {s.title or '(untitled)'} "
                         f"[{s.status}]")
        sess.scratch["edit_list"] = [s.id for s in shots]
        sess.step = "pick_edit_target"
        # This step re-uses the idle handler; register an ad-hoc handler:
        # Simpler: we detect "pick_edit_target" inline below.
        return "\n".join(lines)

    def _start_remove(self, sess: VideoSession) -> str:
        shots = self.board.all()
        if not shots:
            sess.reset()
            return "Nothing to remove."
        sess.scratch["remove_list"] = [s.id for s in shots]
        sess.step = "pick_remove_target"
        lines = ["Which shot should I remove? (pick a number)"]
        for i, s in enumerate(shots, 1):
            lines.append(f"{i}. {s.title or '(untitled)'}")
        return "\n".join(lines)

    def _start_reorder(self, sess: VideoSession) -> str:
        shots = self.board.all()
        if len(shots) < 2:
            sess.reset()
            return "Need at least two shots to reorder."
        sess.step = "reorder_input"
        lines = ["Type the new order as a list of numbers, "
                 "e.g. '3,1,2':"]
        for i, s in enumerate(shots, 1):
            lines.append(f"{i}. {s.title or '(untitled)'}")
        sess.scratch["reorder_ids"] = [s.id for s in shots]
        return "\n".join(lines)

    def _start_render(self, sess: VideoSession) -> str:
        shots = [s for s in self.board.all() if s.status != "running"]
        if not shots:
            sess.reset()
            return "No shots ready to render."
        sess.step = "pick_render_target"
        sess.scratch["render_list"] = [s.id for s in shots]
        lines = ["Which shot should I queue? (pick a number)"]
        for i, s in enumerate(shots, 1):
            lines.append(f"{i}. {s.title or '(untitled)'} "
                         f"[{s.status}]")
        return "\n".join(lines)

    # The three pick_* sub-steps share a uniform shape.  Handle them
    # here rather than registering separate handlers so the dispatch
    # table stays readable.
    def _handle_idle(self, sess: VideoSession, text: str) -> str:  # noqa: F811
        # Catch sub-step states that don't fit the main dispatch
        if sess.step == "pick_edit_target":
            return self._resolve_pick(sess, text, "edit_list",
                                      self._jump_into_shot)
        if sess.step == "pick_remove_target":
            return self._resolve_pick(sess, text, "remove_list",
                                      self._do_remove)
        if sess.step == "reorder_input":
            return self._resolve_reorder(sess, text)
        if sess.step == "pick_render_target":
            return self._resolve_pick(sess, text, "render_list",
                                      self._do_render)
        sess.step = STEP_PICK_ACTION
        return self._render_menu()

    def _resolve_pick(self, sess: VideoSession, text: str,
                      list_key: str, action) -> str:
        ids: List[str] = sess.scratch.get(list_key, [])
        idx = _parse_index(text, len(ids))
        if idx is None:
            return "Pick a number from the list."
        shot_id = ids[idx]
        sess.scratch.pop(list_key, None)
        return action(sess, shot_id)

    def _resolve_reorder(self, sess: VideoSession, text: str) -> str:
        ids: List[str] = sess.scratch.get("reorder_ids", [])
        try:
            picks = [int(x) - 1 for x in text.replace(" ", "").split(",")]
        except ValueError:
            return "I need numbers separated by commas, e.g. '3,1,2'."
        if any(p < 0 or p >= len(ids) for p in picks):
            return f"Numbers must be between 1 and {len(ids)}."
        new_order = [ids[p] for p in picks]
        self.board.reorder(new_order)
        sess.reset()
        return "Reordered.\n\n" + self._render_status()

    def _jump_into_shot(self, sess: VideoSession, shot_id: str) -> str:
        sess.current_shot_id = shot_id
        shot = self.board.get(shot_id)
        if not shot:
            sess.reset()
            return "Shot vanished."
        sess.step = STEP_REVIEW
        return self._render_review(shot)

    def _do_remove(self, sess: VideoSession, shot_id: str) -> str:
        shot = self.board.get(shot_id)
        if not shot:
            sess.reset()
            return "Shot not found."
        self.board.remove(shot_id)
        sess.reset()
        return (f"Removed shot '{shot.title}'.\n\n"
                + self._render_status())

    def _do_render(self, sess: VideoSession, shot_id: str) -> str:
        sess.reset()
        sess.scratch["pending_render"] = shot_id
        shot = self.board.get(shot_id)
        title = shot.title if shot else shot_id
        return f"Queuing '{title}' — calling the video bridge now…"

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_menu(self) -> str:
        actions = self._actions()
        lines = [self._resolve_banner() +
                  "**Cinematographer** — what would you like to do?"]
        for i, (_, label) in enumerate(actions, 1):
            lines.append(f"{i}. {label}")
        return "\n".join(lines)

    def _render_backend_menu(self) -> str:
        return ("Which backend should render this shot?\n\n"
                "1. WanGP (Wan 2.2 / LTX 2.3 / Ovi — recommended)\n"
                "2. ComfyUI (custom Spellcaster LTX2 workflow)\n"
                "3. Hybrid (WanGP generate + ComfyUI upscale)")

    def _render_preset_menu(self, backend: str) -> str:
        if backend == "wangp":
            lines = ["Pick a WanGP preset:"]
            for i, key in enumerate(preset_names(), 1):
                spec = describe_preset(key)
                lines.append(
                    f"{i}. {spec.get('label', key)}  "
                    f"(≥{spec.get('vram_min_gb', '?')}GB VRAM)"
                )
            return "\n".join(lines)
        lines = ["Pick a ComfyUI workflow:"]
        for i, name in enumerate(["ltx2_image_to_video",
                                  "ltx2_text_to_video",
                                  "ltx2_t2v_with_rife_interpolation",
                                  "ltx2_t2v_with_rtx_upscale"], 1):
            lines.append(f"{i}. {name}")
        return "\n".join(lines)

    def _render_review(self, shot: Shot) -> str:
        traj_count = len(shot.trajectories)
        lines = [
            f"**Review — {shot.title}**",
            f"  prompt:     {shot.prompt[:100] or '(none)'}",
            f"  backend:    {shot.backend}",
            f"  preset:     {shot.preset}",
            f"  ref image:  {shot.ref_image or '(none)'}",
            f"  trajectories: {traj_count}",
            "",
            "Choose:",
            "1. Queue it",
            "2. Edit title",
            "3. Edit prompt",
            "4. Change preset",
            "5. Cancel",
        ]
        return "\n".join(lines)

    def _render_status(self) -> str:
        shots = self.board.all()
        banner = self._resolve_banner()
        if not shots:
            return banner + "Shotboard is empty."
        lines = [banner + f"**Shotboard** ({len(shots)} shot"
                 f"{'s' if len(shots) != 1 else ''})"]
        for s in shots:
            marker = {
                "draft": "○",
                "queued": "◔",
                "running": "◐",
                "ready": "●",
                "failed": "✗",
            }.get(s.status, "?")
            lines.append(f"  {marker} {s.index + 1}. "
                         f"{s.title or '(untitled)'}  "
                         f"[{s.preset}]")
        return "\n".join(lines)

    def _must_current(self, sess: VideoSession) -> Optional[Shot]:
        if not sess.current_shot_id:
            return None
        shot = self.board.get(sess.current_shot_id)
        if not shot:
            sess.reset()
        return shot


# -----------------------------------------------------------------------------
# Parsing helpers
# -----------------------------------------------------------------------------

def _parse_index(text: str, upper_bound: int) -> Optional[int]:
    """Parse a 1-based menu pick.  Returns 0-based index or None."""
    text = (text or "").strip()
    if not text:
        return None
    # Accept "1", "1.", "1)", "1 - foo"
    token = text.split()[0].rstrip(".),:")
    try:
        idx = int(token) - 1
    except ValueError:
        return None
    if idx < 0 or idx >= upper_bound:
        return None
    return idx

