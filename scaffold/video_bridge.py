"""
Video Bridge — top-level glue for the shot-centric video pipeline.

This is the video analogue of ``SpellcasterScaffold``.  It wires:

  - a Shotboard (persistent ordered list of shots)
  - a CinematographerWizard (LLM-driven conversational editor)
  - a WanGPRunner (Gradio bridge to deepbeepmeep/Wan2GP)
  - the existing ComfyUIRunner (for the fallback / custom-workflow path)

The Guild server (``tavern/server.py``) imports this in one line and
registers a handful of HTTP endpoints against the methods below.  All
long-running work (queueing, polling, downloading) is non-blocking:
``queue_shot()`` returns immediately and background threads owned by
the bridge poll WanGP and update the Shotboard as jobs finish.

Design rules (matching the rest of Spellcaster):
  - Zero dependencies beyond stdlib.
  - Everything is JSON-serialisable so the HTTP layer is trivial.
  - Failures never raise across the boundary — they come back as
    ``{"status": "error", "message": "..."}`` payloads.
  - State lives on disk in the Shotboard; the bridge itself is
    stateless except for in-flight job threads.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import json
import queue
from typing import Any, Callable, Dict, List, Optional

from .comfyui_runner import ComfyUIRunner
from .frame_extract import extract_last_frame
from .shotboard import Shotboard, Shot
from .video_wizard import CinematographerWizard
from .wangp_runner import WanGPRunner, describe_preset, preset_names

log = logging.getLogger("spellcaster.video_bridge")


class VideoBridge:
    """Top-level entry point for video generation in Spellcaster.

    Attributes:
      - ``board``:       the Shotboard
      - ``wizard``:      the CinematographerWizard
      - ``wangp``:       the WanGPRunner
      - ``comfy``:       an optional ComfyUIRunner (for the ComfyUI branch)

    Typical use from ``tavern/server.py``::

        bridge = VideoBridge(
            shotboard_path="~/pinokio/api/spellcaster/shotboard.json",
            wangp_url="http://localhost:7860",
            comfyui_url="http://localhost:8188",
        )

        # Chat turn:
        reply = bridge.handle_chat(user_id, text)

        # UI drop:
        bridge.attach_reference(shot_id, uploaded_path)

        # User clicks "Render":
        bridge.queue_shot(shot_id)
    """

    def __init__(self,
                 shotboard_path: str,
                 wangp_url: str = "http://localhost:7860",
                 comfyui_url: str = "http://localhost:8188",
                 output_dir: Optional[str] = None,
                 cleanup_outputs: bool = True):
        self.board = Shotboard(os.path.expanduser(shotboard_path))
        self.wizard = CinematographerWizard(self.board)
        self.wangp = WanGPRunner(wangp_url)
        self.comfy = ComfyUIRunner(
            comfyui_url,
            cleanup_inputs=False,  # video refs are usually deliberate
            cleanup_outputs=cleanup_outputs,
        )
        # Where to park downloaded mp4s.  Defaults next to the shotboard.
        if output_dir:
            self.output_dir = os.path.abspath(os.path.expanduser(output_dir))
        else:
            self.output_dir = os.path.join(
                os.path.dirname(self.board.path), "renders"
            )
        os.makedirs(self.output_dir, exist_ok=True)

        # In-flight tracker so we don't re-queue a shot already running.
        self._in_flight: Dict[str, threading.Thread] = {}
        self._in_flight_lock = threading.Lock()

        # SSE event bus
        self._sse_subscribers: list = []
        self._sse_lock = threading.Lock()
        # Render progress tracking
        self._active_progress: float = 0.0
        self._active_stage: str = "idle"
        self._active_started: float = 0.0
        # Queue pause control
        self._paused: bool = False

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Return a status snapshot for the UI's "backends" panel."""
        return {
            "wangp": {
                "url": self.wangp.base_url,
                "available": self.wangp.is_available(),
                "info": self.wangp.server_info()
                        if self.wangp.is_available() else None,
            },
            "comfyui": {
                "url": self.comfy.base_url,
                "available": self.comfy.is_available(),
                "has_api_tools": (self.comfy.has_api_tools()
                                  if self.comfy.is_available() else False),
            },
            "shotboard": {
                "path": self.board.path,
                "count": len(self.board),
            },
            "in_flight": list(self._in_flight.keys()),
            "presets": preset_names(),
            "render_progress": self.render_progress(),
            "total_shots": len(self.board),
            "ready_count": sum(1 for s in self.board if s.status == "ready"),
        }

    # ------------------------------------------------------------------
    # SSE event bus
    # ------------------------------------------------------------------

    def subscribe(self):
        """Return a Queue that will receive SSE events."""
        import queue as _queue
        q = _queue.Queue(maxsize=64)
        with self._sse_lock:
            self._sse_subscribers.append(q)
        return q

    def unsubscribe(self, q):
        """Remove a subscriber queue."""
        with self._sse_lock:
            try:
                self._sse_subscribers.remove(q)
            except ValueError:
                pass

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """Push an event to all SSE subscribers."""
        msg = {"event": event, "data": data, "ts": time.time()}
        with self._sse_lock:
            dead = []
            for q in self._sse_subscribers:
                try:
                    q.put_nowait(msg)
                except Exception:
                    dead.append(q)
            for q in dead:
                try:
                    self._sse_subscribers.remove(q)
                except ValueError:
                    pass

    def _emit_shot_update(self, shot_id: str, **fields) -> None:
        """Emit a shot-update SSE event."""
        self._emit("shot-update", {"shot_id": shot_id, **fields})

    def render_progress(self) -> Dict[str, Any]:
        """Return current render progress for the UI."""
        with self._in_flight_lock:
            active_ids = list(self._in_flight.keys())
        if not active_ids:
            return {"active": None, "stage": "idle", "progress": 0}
        shot_id = active_ids[0]
        if self._active_progress > 0:
            pct = min(self._active_progress * 0.8, 80)
        elif self._active_started > 0:
            elapsed = time.time() - self._active_started
            pct = min(elapsed / 120 * 80, 80)
        else:
            pct = 0
        return {
            "active": shot_id,
            "stage": self._active_stage,
            "progress": round(pct, 1),
        }

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def handle_chat(self, user_id: str, text: str) -> Dict[str, Any]:
        """Drive the wizard for one user turn.

        Returns a dict with:
          - ``reply``: text to display in chat
          - ``pending_render``: shot_id if the user just confirmed,
            else None.  The caller should follow up with queue_shot().
        """
        reply = self.wizard.handle(user_id, text)
        pending = self.wizard.get_pending_render(user_id)
        result = {"reply": reply, "pending_render": pending}
        if pending:
            # Auto-queue the render so the user doesn't need to say it twice.
            result["queued"] = self.queue_shot(pending)
        return result

    # ------------------------------------------------------------------
    # Direct Shotboard editing (from the UI, not the chat)
    # ------------------------------------------------------------------

    def list_shots(self) -> Dict[str, Any]:
        return self.board.as_dict()

    def add_shot(self, **fields: Any) -> Dict[str, Any]:
        shot = self.board.add(**fields)
        return shot.to_dict()

    def update_shot(self, shot_id: str, **fields: Any) -> Dict[str, Any]:
        shot = self.board.update(shot_id, **fields)
        if not shot:
            return {"status": "error", "message": "shot not found"}
        return shot.to_dict()

    def remove_shot(self, shot_id: str) -> Dict[str, Any]:
        ok = self.board.remove(shot_id)
        return {"status": "ok" if ok else "error",
                "shot_id": shot_id}

    def reorder_shots(self, ordered_ids: List[str]) -> Dict[str, Any]:
        self.board.reorder(ordered_ids)
        return self.board.as_dict()

    def attach_reference(self, shot_id: str, path: str) -> Dict[str, Any]:
        """Wire an uploaded file path as the ref image of a shot."""
        try:
            shot = self.wizard.commit_reference(shot_id, path)
        except FileNotFoundError:
            return {"status": "error",
                    "message": f"no file at {path}"}
        if not shot:
            return {"status": "error", "message": "shot not found"}
        return shot.to_dict()

    def set_trajectories(self, shot_id: str,
                         trajectories: List[Dict[str, Any]]
                         ) -> Dict[str, Any]:
        """Store trajectories drawn in the Guild UI."""
        shot = self.wizard.commit_trajectories(shot_id, trajectories)
        if not shot:
            return {"status": "error", "message": "shot not found"}
        return shot.to_dict()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def queue_shot(self, shot_id: str,
                   on_complete: Optional[Callable[[Shot], None]] = None
                   ) -> Dict[str, Any]:
        """Route a shot to the right backend and render it asynchronously.

        Returns immediately with a ``status`` and optional ``job_id``.
        Progress is reflected in the Shot's ``status`` field; the UI
        polls ``list_shots()`` or subscribes via SSE (not wired here).
        """
        shot = self.board.get(shot_id)
        if not shot:
            return {"status": "error", "message": "shot not found"}

        if self._paused:
            return {"status": "paused", "message": "queue is paused"}

        with self._in_flight_lock:
            if shot_id in self._in_flight:
                return {"status": "already_running",
                        "shot_id": shot_id}

        if shot.backend == "wangp":
            return self._queue_wangp(shot, on_complete)
        if shot.backend == "comfyui":
            return self._queue_comfy(shot, on_complete)
        if shot.backend == "hybrid":
            # Hybrid = WanGP generate, then optional ComfyUI upscale.
            # For the first cut we treat this like plain WanGP — the
            # upscale step can chain in ``_on_wangp_done``.
            return self._queue_wangp(shot, on_complete, chain_upscale=True)
        return {"status": "error",
                "message": f"unknown backend {shot.backend!r}"}

    # ---- WanGP path ------------------------------------------------

    def _queue_wangp(self, shot: Shot,
                     on_complete: Optional[Callable[[Shot], None]],
                     chain_upscale: bool = False) -> Dict[str, Any]:
        if not self.wangp.is_available():
            self.board.mark_failed(
                shot.id,
                f"WanGP not reachable at {self.wangp.base_url}",
            )
            return {"status": "error",
                    "message": f"WanGP not reachable at {self.wangp.base_url}"}

        spec = describe_preset(shot.preset)
        if not spec:
            self.board.mark_failed(
                shot.id, f"unknown WanGP preset {shot.preset!r}"
            )
            return {"status": "error",
                    "message": f"unknown preset {shot.preset!r}"}

        if "image" in (spec.get("inputs") or []) and not shot.ref_image:
            self.board.mark_failed(shot.id, "reference image required")
            return {"status": "error",
                    "message": "this preset needs a reference image"}

        trajectories: Optional[List[Dict[str, Any]]] = None
        if shot.trajectories:
            trajectories = [t.to_dict() for t in shot.trajectories]

        overrides = dict(shot.overrides or {})
        if shot.negative:
            overrides.setdefault("negative_prompt", shot.negative)
        if shot.seed is not None:
            overrides.setdefault("seed", shot.seed)

        queue_result = self.wangp.queue_generation(
            preset=shot.preset,
            prompt=shot.prompt,
            image_path=shot.ref_image,
            trajectories=trajectories,
            overrides=overrides,
        )
        if queue_result.get("status") != "queued":
            self.board.mark_failed(
                shot.id, queue_result.get("message", "queue failed")
            )
            return queue_result

        job_id = queue_result["job_id"]
        endpoint = queue_result.get("endpoint", "generate")
        self.board.mark_queued(shot.id, job_id)

        def worker() -> None:
            try:
                self.board.mark_running(shot.id)
                render_start = time.time()
                self._active_started = render_start
                self._active_stage = "rendering"
                def _on_wangp_progress(pct):
                    self._active_progress = pct
                result = self.wangp.wait(job_id, endpoint_hint=endpoint, on_progress=_on_wangp_progress)
                if result.get("status") != "ok":
                    self.board.mark_failed(
                        shot.id, result.get("message", "WanGP error")
                    )
                    return
                videos = result.get("videos") or []
                if not videos:
                    self.board.mark_failed(
                        shot.id, "WanGP returned no video"
                    )
                    return
                remote = videos[0]
                local = os.path.join(
                    self.output_dir,
                    f"{shot.id}_{int(time.time())}.mp4",
                )
                try:
                    self.wangp.download_video(remote, local)
                except Exception as exc:  # noqa: BLE001
                    self.board.mark_failed(
                        shot.id, f"download failed: {exc}"
                    )
                    return
                self.board.mark_ready(shot.id, local)
                elapsed = time.time() - render_start
                self.board.update(shot.id, render_duration_s=elapsed)
                self._emit_shot_update(shot.id, status="ready")
                # Continuity hand-off: extract last frame and wire it
                # as the next shot's reference image.
                last_frame = extract_last_frame(local)
                self.board.export_for_next(shot.id, last_frame)
                if chain_upscale:
                    self._chain_comfy_upscale(shot.id, local)
                if on_complete:
                    try:
                        on_complete(self.board.get(shot.id))
                    except Exception:  # noqa: BLE001
                        log.exception("on_complete raised")
            finally:
                self._active_progress = 0.0
                self._active_stage = "idle"
                self._active_started = 0.0
                with self._in_flight_lock:
                    self._in_flight.pop(shot.id, None)

        t = threading.Thread(target=worker,
                             name=f"wangp-{shot.id[:8]}",
                             daemon=True)
        with self._in_flight_lock:
            self._in_flight[shot.id] = t
        t.start()

        return {"status": "queued", "shot_id": shot.id,
                "backend": "wangp", "job_id": job_id}

    # ---- ComfyUI path ----------------------------------------------

    @staticmethod
    def _patch_comfy_workflow(workflow: Dict[str, Any], shot) -> Dict[str, Any]:
        """Inject shot fields into a ComfyUI API-format workflow."""
        import copy as _copy
        patched = _copy.deepcopy(workflow)
        ov = dict(shot.overrides or {})
        for nid, node in patched.items():
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type", "")
            inp = node.get("inputs", {})
            meta_title = (node.get("_meta") or {}).get("title", "").lower()
            # Prompt injection
            if ct == "CLIPTextEncode" and "text" in inp:
                if "positive" in meta_title and shot.prompt:
                    inp["text"] = shot.prompt
                elif "negative" in meta_title and shot.negative:
                    inp["text"] = shot.negative
            # Seed injection
            if ct == "KSampler" and "seed" in inp:
                if shot.seed is not None:
                    inp["seed"] = shot.seed
                if "steps" in ov:
                    inp["steps"] = ov["steps"]
                if "guidance" in ov or "cfg" in ov:
                    inp["cfg"] = ov.get("guidance", ov.get("cfg", inp.get("cfg")))
            # BasicScheduler
            if ct == "BasicScheduler" and "steps" in inp:
                if "steps" in ov:
                    inp["steps"] = ov["steps"]
            # CFGGuider
            if ct == "CFGGuider" and "cfg" in inp:
                if "guidance" in ov or "cfg" in ov:
                    inp["cfg"] = ov.get("guidance", ov.get("cfg", inp.get("cfg")))
            # EmptyLatentVideo
            if ct == "EmptyLatentVideo":
                if "frames" in ov and "length" in inp:
                    inp["length"] = ov["frames"]
                if "resolution" in ov:
                    try:
                        w, h = ov["resolution"].split("x")
                        inp["width"] = int(w)
                        inp["height"] = int(h)
                    except (ValueError, AttributeError):
                        pass
            # LoadImage ref injection
            if ct == "LoadImage" and "image" in inp:
                if shot.ref_image:
                    inp["image"] = os.path.basename(shot.ref_image)
        return patched

    def _queue_comfy(self, shot: Shot,
                     on_complete: Optional[Callable[[Shot], None]]
                     ) -> Dict[str, Any]:
        if not self.comfy.is_available():
            self.board.mark_failed(
                shot.id,
                f"ComfyUI not reachable at {self.comfy.base_url}",
            )
            return {"status": "error",
                    "message": f"ComfyUI not reachable"}
        # Resolve the workflow JSON.  We defer heavy lifting to the
        # existing WorkflowWizard / workflow_parser machinery; here we
        # only need to know the workflow exists on disk.
        wf_path = os.path.join(
            os.path.dirname(__file__), "workflows", f"{shot.preset}.json"
        )
        if not os.path.isfile(wf_path):
            self.board.mark_failed(
                shot.id, f"workflow {shot.preset} not found"
            )
            return {"status": "error",
                    "message": f"workflow {shot.preset!r} not found"}

        # NOTE: this minimal ComfyUI branch just runs the workflow as-is.
        # A future revision can patch prompt/ref_image into specific
        # nodes using workflow_parser — follows the same pattern as
        # WorkflowWizard.get_final_workflow().  For the first cut we
        # mark it queued, delegate, and let the user wire prompts via
        # the existing workflow wizard if they need parameter control.
        import json
        try:
            with open(wf_path, "r", encoding="utf-8") as fh:
                workflow = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            self.board.mark_failed(shot.id, f"bad workflow json: {exc}")
            return {"status": "error", "message": str(exc)}

        # Patch workflow with shot fields
        workflow = VideoBridge._patch_comfy_workflow(workflow, shot)
        # Upload ref image if present
        if shot.ref_image and os.path.isfile(shot.ref_image):
            self.comfy.upload_image(shot.ref_image, os.path.basename(shot.ref_image))

        self.board.mark_running(shot.id)

        def worker() -> None:
            try:
                comfy_render_start = time.time()
                result = self.comfy.run_raw(workflow)
                if result.get("status") != "ok":
                    self.board.mark_failed(
                        shot.id, result.get("message", "ComfyUI error")
                    )
                    return
                # ComfyUIRunner hands back a list of output dicts; the
                # VHS_VideoCombine node typically emits a 'videos' or
                # 'gifs' list with {"filename": ..., "subfolder": ...}
                outputs = result.get("outputs") or []
                remote = _pick_video_output(outputs)
                if not remote:
                    self.board.mark_failed(
                        shot.id, "ComfyUI produced no video"
                    )
                    return
                local = os.path.join(
                    self.output_dir,
                    f"{shot.id}_{int(time.time())}.mp4",
                )
                data = self.comfy.download_image(
                    filename=remote["filename"],
                    subfolder=remote.get("subfolder", ""),
                    folder_type=remote.get("type", "output"),
                )
                with open(local, "wb") as fh:
                    fh.write(data)
                self.board.mark_ready(shot.id, local)
                elapsed = time.time() - comfy_render_start
                self.board.update(shot.id, render_duration_s=elapsed)
                last_frame = extract_last_frame(local)
                self.board.export_for_next(shot.id, last_frame)
                if on_complete:
                    try:
                        on_complete(self.board.get(shot.id))
                    except Exception:  # noqa: BLE001
                        log.exception("on_complete raised")
            finally:
                self._active_progress = 0.0
                self._active_stage = "idle"
                self._active_started = 0.0
                with self._in_flight_lock:
                    self._in_flight.pop(shot.id, None)

        t = threading.Thread(target=worker,
                             name=f"comfy-{shot.id[:8]}",
                             daemon=True)
        with self._in_flight_lock:
            self._in_flight[shot.id] = t
        t.start()

        return {"status": "queued", "shot_id": shot.id,
                "backend": "comfyui"}

    def _chain_comfy_upscale(self, shot_id: str, video_path: str) -> None:
        """Chain a ComfyUI upscale workflow against a WanGP render.

        Loads the ``seedvr2_video_upscale`` workflow, patches the input
        video path to point at *video_path*, and queues it via the
        ComfyUIRunner.  Runs synchronously inside the WanGP worker
        thread (which is already a background daemon), so there is no
        need for a second thread.

        On success, the shot's ``video_path`` is updated to the upscaled
        file.  On failure, the shot keeps the WanGP output and an
        informational log is emitted — the user still gets usable video.
        """
        import json as _json

        if not self.comfy.is_available():
            log.warning("Hybrid upscale skipped: ComfyUI not reachable "
                        "at %s", self.comfy.base_url)
            return

        wf_path = os.path.join(
            os.path.dirname(__file__), "workflows",
            "seedvr2_video_upscale.json",
        )
        if not os.path.isfile(wf_path):
            log.warning("Hybrid upscale skipped: workflow not found at %s",
                        wf_path)
            return

        try:
            with open(wf_path, "r", encoding="utf-8") as fh:
                workflow = _json.load(fh)
        except Exception as exc:  # noqa: BLE001
            log.warning("Hybrid upscale skipped: bad workflow JSON: %s", exc)
            return

        # Patch the VHS_LoadVideo node's input to our render.
        patched = False
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") == "VHS_LoadVideo":
                node.setdefault("inputs", {})["video"] = video_path
                patched = True
                break
        if not patched:
            log.warning("Hybrid upscale skipped: no VHS_LoadVideo node "
                        "found in workflow")
            return

        log.info("Chaining ComfyUI upscale for shot %s (%s)",
                 shot_id, video_path)

        try:
            result = self.comfy.run_raw(workflow)
        except Exception as exc:  # noqa: BLE001
            log.warning("Hybrid upscale failed for shot %s: %s",
                        shot_id, exc)
            return

        if result.get("status") != "ok":
            log.warning("Hybrid upscale error for shot %s: %s",
                        shot_id, result.get("message", "unknown"))
            return

        outputs = result.get("outputs") or []
        remote = _pick_video_output(outputs)
        if not remote:
            log.warning("Hybrid upscale produced no video for shot %s",
                        shot_id)
            return

        upscaled_local = os.path.join(
            self.output_dir,
            f"{shot_id}_upscaled_{int(time.time())}.mp4",
        )
        try:
            data = self.comfy.download_image(
                filename=remote["filename"],
                subfolder=remote.get("subfolder", ""),
                folder_type=remote.get("type", "output"),
            )
            with open(upscaled_local, "wb") as fh:
                fh.write(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("Hybrid upscale download failed for shot %s: %s",
                        shot_id, exc)
            return

        # Update the shot to point at the upscaled version.
        self.board.update(shot_id, video_path=upscaled_local)
        # Re-extract last frame from the upscaled video for continuity.
        last_frame = extract_last_frame(upscaled_local)
        if last_frame:
            self.board.export_for_next(shot_id, last_frame)
        log.info("Hybrid upscale complete for shot %s -> %s",
                 shot_id, upscaled_local)

    # ------------------------------------------------------------------
    # Render cancellation
    # ------------------------------------------------------------------

    def cancel_shot(self, shot_id: str) -> Dict[str, Any]:
        """Cancel an in-flight render for the given shot.

        Removes the thread from the in-flight tracker and marks the shot
        as draft.  The thread itself is a daemon and will be abandoned
        (we cannot safely kill threads in Python, but daemon threads die
        with the process).
        """
        with self._in_flight_lock:
            thread = self._in_flight.pop(shot_id, None)
        if not thread:
            return {"status": "error", "message": "shot not in flight"}
        self.board.update(shot_id, status="draft", error=None, job_id=None)
        self._active_progress = 0.0
        self._active_stage = "idle"
        self._active_started = 0.0
        self._emit_shot_update(shot_id, status="cancelled")
        log.info("Cancelled render for shot %s", shot_id)
        return {"status": "ok", "shot_id": shot_id}

    # ------------------------------------------------------------------
    # Batch rendering
    # ------------------------------------------------------------------

    def queue_all_drafts(self) -> Dict[str, Any]:
        """Queue all draft shots in order, chaining each to start after
        the previous one finishes.  This prevents VRAM exhaustion from
        running multiple renders in parallel.

        Returns ``{"queued": N, "skipped": M, "shot_ids": [...]}``
        where N is the count of shots successfully queued.
        """
        drafts = [s for s in self.board if s.status == "draft"]
        if not drafts:
            return {"queued": 0, "skipped": 0, "shot_ids": []}

        queued_ids: List[str] = []
        skipped = 0

        first = drafts[0]
        result = self.queue_shot(first.id)
        if result.get("status") in ("queued", "already_running"):
            queued_ids.append(first.id)
        else:
            skipped += 1

        remaining = drafts[1:]
        if remaining:
            chain = list(remaining)

            def _batch_watcher() -> None:
                for nxt in chain:
                    while True:
                        with self._in_flight_lock:
                            busy = bool(self._in_flight)
                        if not busy:
                            break
                        time.sleep(2.0)
                    # Respect pause flag
                    while self._paused:
                        time.sleep(1.0)
                    fresh = self.board.get(nxt.id)
                    if fresh and fresh.status == "draft":
                        self.queue_shot(nxt.id)
                        queued_ids.append(nxt.id)

            watcher = threading.Thread(
                target=_batch_watcher,
                name="batch-render-watcher",
                daemon=True,
            )
            watcher.start()
            queued_ids.extend(s.id for s in remaining)

        return {
            "queued": len(queued_ids),
            "skipped": skipped,
            "shot_ids": queued_ids,
        }

    def reset_failed(self) -> Dict[str, Any]:
        """Reset all failed shots back to draft so they can be re-queued."""
        failed = [s for s in self.board if s.status == "failed"]
        reset_ids: List[str] = []
        for s in failed:
            self.board.update(s.id, status="draft", error=None, job_id=None)
            reset_ids.append(s.id)
        return {"reset": len(reset_ids), "shot_ids": reset_ids}

    # ------------------------------------------------------------------
    # Queue pause / resume
    # ------------------------------------------------------------------

    def pause_queue(self) -> Dict[str, Any]:
        """Pause the render queue. Running shots finish, but no new ones start."""
        self._paused = True
        self._emit("queue_paused", {})
        return {"status": "paused"}

    def resume_queue(self) -> Dict[str, Any]:
        """Resume the render queue."""
        self._paused = False
        self._emit("queue_resumed", {})
        return {"status": "resumed"}

    def queue_status(self) -> Dict[str, Any]:
        """Return current queue status."""
        with self._in_flight_lock:
            in_flight = list(self._in_flight.keys())
        drafts = [s.id for s in self.board if s.status == "draft"]
        queued = [s.id for s in self.board if s.status == "queued"]
        return {
            "paused": self._paused,
            "in_flight": in_flight,
            "drafts_pending": len(drafts),
            "queued": len(queued),
        }

    # ------------------------------------------------------------------
    # Render time estimation
    # ------------------------------------------------------------------

    def estimate_render_time(self, preset: str = None) -> Dict[str, Any]:
        """Estimate render time based on historical data.

        Looks at all completed shots and computes average render_duration_s
        per preset.  If ``preset`` is given, returns estimate for that
        preset only; otherwise returns estimates for all known presets.
        """
        by_preset: Dict[str, List[float]] = {}
        for s in self.board:
            if s.status == "ready" and s.render_duration_s:
                by_preset.setdefault(s.preset, []).append(s.render_duration_s)
        estimates: Dict[str, Dict[str, Any]] = {}
        for p, durations in by_preset.items():
            avg = sum(durations) / len(durations)
            estimates[p] = {
                "avg_seconds": round(avg, 1),
                "sample_count": len(durations),
                "min_seconds": round(min(durations), 1),
                "max_seconds": round(max(durations), 1),
            }
        if preset:
            return estimates.get(preset, {
                "avg_seconds": None,
                "sample_count": 0,
                "min_seconds": None,
                "max_seconds": None,
            })
        return {"estimates": estimates}

    def batch_update_preset(self, shot_ids: List[str],
                            preset: str) -> Dict[str, Any]:
        """Change the preset for multiple shots at once."""
        updated = 0
        for sid in shot_ids:
            shot = self.board.get(sid)
            if shot and shot.status == "draft":
                self.board.update(sid, preset=preset)
                updated += 1
        return {"updated": updated, "preset": preset}

    # ------------------------------------------------------------------
    # Prompt Templates
    # ------------------------------------------------------------------

    def _templates_path(self) -> str:
        return os.path.join(os.path.dirname(self.board.path),
                            "prompt_templates.json")

    def _load_templates(self) -> Dict[str, Dict[str, str]]:
        path = self._templates_path()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_templates(self, templates: Dict[str, Dict[str, str]]) -> None:
        path = self._templates_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(templates, f, indent=2)

    def list_templates(self) -> Dict[str, Any]:
        """Return all saved prompt templates."""
        return {"templates": self._load_templates()}

    def save_template(self, name: str, prompt: str,
                      negative: str = "") -> Dict[str, Any]:
        """Save or overwrite a prompt template."""
        if not name or not name.strip():
            return {"status": "error", "message": "template name required"}
        templates = self._load_templates()
        templates[name.strip()] = {"prompt": prompt, "negative": negative}
        self._save_templates(templates)
        return {"status": "ok", "name": name.strip()}

    def delete_template(self, name: str) -> Dict[str, Any]:
        """Delete a prompt template by name."""
        templates = self._load_templates()
        if name not in templates:
            return {"status": "error", "message": "template not found"}
        del templates[name]
        self._save_templates(templates)
        return {"status": "ok", "name": name}

    # ------------------------------------------------------------------
    # Clone with variation
    # ------------------------------------------------------------------

    def clone_shot(self, shot_id: str,
                   variation: str = "") -> Dict[str, Any]:
        """Duplicate a shot, optionally appending a variation to the prompt."""
        source = self.board.get(shot_id)
        if not source:
            return {"status": "error", "message": "shot not found"}
        prompt = source.prompt
        if variation and variation.strip():
            prompt = f"{prompt} ({variation.strip()})"
        new_shot = self.board.add(
            title=f"{source.title} — var" if source.title else "",
            prompt=prompt,
            negative=source.negative,
            seed=None,
            backend=source.backend,
            preset=source.preset,
            overrides=dict(source.overrides or {}),
            notes=source.notes,
            carry_last_frame=source.carry_last_frame,
        )
        return new_shot.to_dict()

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_shotboard(self) -> Dict[str, Any]:
        """Return the full shotboard state as a JSON-serialisable dict."""
        return self.board.as_dict()

    def import_shotboard(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Replace the current shotboard with imported data."""
        from .shotboard import Shot
        shots_raw = data.get("shots", [])
        if not isinstance(shots_raw, list):
            return {"status": "error", "message": "invalid format: shots must be a list"}
        for s in list(self.board):
            self.board.remove(s.id)
        imported = 0
        for sd in shots_raw:
            if not isinstance(sd, dict):
                continue
            shot = Shot.from_dict(sd)
            shot.status = "draft"
            shot.job_id = None
            shot.error = None
            self.board._shots.append(shot)
            imported += 1
        self.board._reindex()
        self.board._persist()
        return {"status": "ok", "imported": imported}


# -----------------------------------------------------------------------------
# Output helpers
# -----------------------------------------------------------------------------

def _pick_video_output(outputs: List[Any]) -> Optional[Dict[str, Any]]:
    """Find the first video-ish file in a ComfyUI run's outputs list."""
    for o in outputs or []:
        if not isinstance(o, dict):
            continue
        name = (o.get("filename") or "").lower()
        if name.endswith((".mp4", ".webm", ".mov", ".mkv", ".gif")):
            return o
    return None


# ═══════════════════════════════════════════════════════════════════════
# Assembly — concatenate all ready shots into one final video
# ═══════════════════════════════════════════════════════════════════════

def assemble_shots(board, output_dir: str = None) -> Optional[str]:
    """Concatenate all ready shots into a single mp4.

    Uses ffmpeg's concat demuxer which is fast (no re-encode) when all
    clips share the same codec / resolution.  Falls back to re-encode
    via the concat filter if the demuxer fails.

    Returns the path to the assembled file, or None if < 2 ready clips.
    """
    import shutil
    import subprocess
    import tempfile as _tmpmod

    videos = board.ready_videos()
    if len(videos) < 2:
        return videos[0] if videos else None

    if output_dir is None:
        output_dir = _tmpmod.gettempdir()
    os.makedirs(output_dir, exist_ok=True)

    out_path = os.path.join(output_dir,
                            f"assembled_{int(time.time())}.mp4")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("ffmpeg not found — cannot assemble shots")
        return None

    # --- Try concat demuxer first (fast, no re-encode) ----------------
    list_file = os.path.join(output_dir, ".concat_list.txt")
    with open(list_file, "w") as fh:
        for v in videos:
            fh.write(f"file '{v}'\n")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0",
             "-i", list_file, "-c", "copy", out_path],
            check=True, capture_output=True, timeout=300,
        )
        return out_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log.info("concat demuxer failed, trying filter fallback")

    # --- Fallback: concat filter (re-encodes) -------------------------
    inputs = []
    for v in videos:
        inputs += ["-i", v]
    n = len(videos)
    filter_str = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
    filter_str += f"concat=n={n}:v=1:a=1[outv][outa]"
    try:
        subprocess.run(
            [ffmpeg, "-y"] + inputs +
            ["-filter_complex", filter_str,
             "-map", "[outv]", "-map", "[outa]", out_path],
            check=True, capture_output=True, timeout=600,
        )
        return out_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.error("ffmpeg assembly failed: %s", exc)
        return None
