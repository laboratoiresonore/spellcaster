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

        queue_result = self.wangp.queue_generation(
            preset=shot.preset,
            prompt=shot.prompt,
            image_path=shot.ref_image,
            trajectories=trajectories,
            overrides=shot.overrides,
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
                result = self.wangp.wait(job_id, endpoint_hint=endpoint)
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

        self.board.mark_running(shot.id)

        def worker() -> None:
            try:
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
                last_frame = extract_last_frame(local)
                self.board.export_for_next(shot.id, last_frame)
                if on_complete:
                    try:
                        on_complete(self.board.get(shot.id))
                    except Exception:  # noqa: BLE001
                        log.exception("on_complete raised")
            finally:
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


# -----------------------------------------------------------------------------
# Output helpers
# -----------------------------------------------------------------------------

def _pick_video_output(outputs: List[Any]) -> Optional[Dict[str, Any]]:
    """Find the first video-ish file in a ComfyUI run's outputs list.

    ComfyUIRunner returns a flat list of file descriptor dicts; video
    nodes (VHS_VideoCombine, SaveVideo) emit mp4/gif under the
    ``videos`` or ``gifs`` key per node, but ComfyUIRunner normalises
    these into the outer list already.
    """
    for o in outputs or []:
        if not isinstance(o, dict):
            continue
        name = (o.get("filename") or "").lower()
        if name.endswith((".mp4", ".webm", ".mov", ".mkv", ".gif")):
            return o
    return None
