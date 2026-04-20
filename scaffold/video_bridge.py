"""
Video Bridge — top-level glue for the shot-centric video pipeline.

This is the video-pipeline glue for the Guild server. It wires:

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
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

from .comfyui_runner import ComfyUIRunner
from .frame_extract import extract_last_frame
from .shotboard import Shotboard, Shot
from .video_wizard import CinematographerWizard
from .wangp_runner import WanGPRunner, describe_preset, preset_names

# R126: native ComfyUI routing for Wan presets. Optional import — when
# the dispatch module or spellcaster_core is missing the flag just
# disables the native path and the old WanGP route still runs.
try:
    from .video_workflow_dispatch import (
        build_native_workflow as _build_native_workflow,
        probe_comfyui_models as _probe_comfyui_models,
    )
    _NATIVE_DISPATCH_AVAILABLE = True
except ImportError:
    _NATIVE_DISPATCH_AVAILABLE = False
    _build_native_workflow = None  # type: ignore
    _probe_comfyui_models = None   # type: ignore

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
                 cleanup_outputs: bool = True,
                 resolve_status_fn=None,
                 resolve_action_fn=None):
        """R121: resolve_status_fn / resolve_action_fn are passed
        through to the Cinematographer so its replies and menu tailor
        to a live Resolve Bridge. Both are optional — the bridge
        falls back to the plain flow when they're not provided.
        Injection (rather than import) keeps scaffold/ decoupled from
        tavern/ and spellcaster_core/."""
        self.board = Shotboard(os.path.expanduser(shotboard_path))
        self.wizard = CinematographerWizard(
            self.board,
            resolve_status_fn=resolve_status_fn,
            resolve_action_fn=resolve_action_fn,
        )
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
        # R59a: single-step flag — set by render_next, consumed by the
        # worker loop after it releases ONE shot. Lets the user preview
        # each render before the queue picks up the next.
        self._auto_pause_after_next: bool = False
        # Render concurrency limit — semaphore gates worker threads
        self._max_concurrent: int = 2
        self._render_sem = threading.Semaphore(self._max_concurrent)

        # Export settings for final video assembly
        self._export_settings = ExportSettings()

        # Favorite presets
        self._favorite_presets: List[str] = []

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
    # SSE event bus (video-local — NOT the same thing as EventBus)
    #
    # There are TWO parallel event systems in the Guild and future Claude
    # WILL conflate them without this annotation. They are distinct:
    #
    #   • `VideoBridge.subscribe()` (this one) — a queue-backed fan-out
    #     for `shot-update`, `shot-status` etc. Consumed by Guild's
    #     `/api/video/events` SSE route. Only video-pipeline events.
    #     Per-subscriber Queue(maxsize=64). No replay.
    #
    #   • `spellcaster_core.event_bus.EventBus.default()` — the
    #     cross-interface bus that asset gallery / interface registry /
    #     mailbox fan through. Kinds look like `<origin>.asset.created`,
    #     `resolve.playhead.send_to_peer`, etc. Consumed by Guild's
    #     `/api/events/stream` SSE route. Has a ring buffer for replay.
    #
    # Why two buses? Historical: the video shotboard existed before the
    # cross-interface backbone. Merging them would require teaching one
    # SSE endpoint to fan in from both backends + validating every
    # existing video-events subscriber still gets its shot-update msgs.
    # Not done yet; flagged in _dev_docs/HANDOVER_CROSS_APP_AUDIT.md §6.3.
    #
    # If you're adding a NEW cross-interface event kind, it goes through
    # EventBus (and the typed schema in `spellcaster_core/events.py`).
    # If you're adding a NEW video-shot-lifecycle signal that only the
    # video UI cares about, it goes through `_emit()` below.
    # ------------------------------------------------------------------

    def subscribe(self):
        """Return a Queue that will receive VIDEO-LOCAL SSE events
        (shot-update, shot-status, render-progress, ...). NOT related
        to spellcaster_core.event_bus.EventBus — see the block comment
        above for the split rationale."""
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
        """Push an event to the video-local fan-out only. For cross-
        interface events (assets, peer presence, send-to-X), publish
        through `_EVENT_BUS.publish()` instead."""
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

        # R89: auto-route based on preset.engine if the caller didn't
        # pin a backend explicitly. Shots created with
        # preset=ltx2_v2v_flowedit (engine="comfyui") shouldn't fail
        # just because the UI left backend at the default "wangp".
        # Only applies when the preset exists in WANGP_PRESETS with a
        # declared engine field — otherwise keep the caller's choice.
        try:
            from scaffold.wangp_runner import WANGP_PRESETS as _PR
        except Exception:
            _PR = {}
        preset_spec = _PR.get(shot.preset) or {}
        preset_engine = (preset_spec.get("engine") or "").strip().lower()
        effective_backend = shot.backend
        if preset_engine and preset_engine != shot.backend:
            log.info(f"R89 auto-route: shot {shot.id[:8]} preset "
                     f"{shot.preset!r} declares engine={preset_engine!r}; "
                     f"overriding backend={shot.backend!r}")
            effective_backend = preset_engine
            try:
                self.board.update(shot.id, backend=preset_engine)
            except Exception:
                pass

        if effective_backend == "wangp":
            # R126: native ComfyUI routing for wan22_* presets. If
            # WanGP is unreachable but ComfyUI has the models, build
            # the workflow from spellcaster_core and submit it
            # directly. Falls through to WanGP on any resolver failure.
            if self._should_try_native_wan(shot):
                result = self._queue_comfy_native_wan(shot, on_complete)
                if (result or {}).get("status") == "queued":
                    return result
                # Fall through — log once so the log tail shows what
                # pushed us to WanGP.
                log.info("native wan route skipped for shot %s: %s",
                          shot.id[:8], (result or {}).get("message",
                                                          "unknown"))
            return self._queue_wangp(shot, on_complete)
        if effective_backend == "comfyui":
            return self._queue_comfy(shot, on_complete)
        if effective_backend == "hybrid":
            # Hybrid = WanGP generate, then optional ComfyUI upscale.
            # For the first cut we treat this like plain WanGP — the
            # upscale step can chain in ``_on_wangp_done``.
            return self._queue_wangp(shot, on_complete, chain_upscale=True)
        return {"status": "error",
                "message": f"unknown backend {effective_backend!r}"}

    # ---- R126: native ComfyUI routing for Wan presets --------------

    # R133: native routing also covers the LTX-2 family.
    _NATIVE_WAN_PRESETS = (
        "wan22_i2v_lightning", "wan22_i2v_hq", "wan22_t2v",
    )
    _NATIVE_LTX2_PRESETS = (
        "ltx2_distilled", "ltx2_dev",
        "ltx2_text_to_video", "ltx2_text_to_video_distilled",
        "ltx2_text_to_video_2stage",
        "ltx2_t2v_with_rife_interpolation",
        "ltx2_t2v_with_rtx_upscale",
        "ltx2_image_to_video",
    )
    _NATIVE_UPSCALE_PRESETS = (
        # R134 — video-in presets. The dispatcher takes
        # shot.overrides.input_video (not shot.ref_image) and uploads
        # the source mp4 to ComfyUI's input/ before submitting.
        "seedvr2_video_upscale",
    )
    _NATIVE_I2V_PRESETS = (
        "wan22_i2v_lightning", "wan22_i2v_hq",
        "ltx2_image_to_video",
    )

    def _should_try_native_wan(self, shot: Shot) -> bool:
        """Native ComfyUI routing for wan22_* / ltx2_* / seedvr2_*
        presets. Different presets have different input requirements:
        - i2v presets need a ref image in shot.ref_image
        - Upscale presets need a video in shot.overrides.input_video
        - t2v presets need nothing
        """
        if not _NATIVE_DISPATCH_AVAILABLE:
            return False
        native = (self._NATIVE_WAN_PRESETS
                   + self._NATIVE_LTX2_PRESETS
                   + self._NATIVE_UPSCALE_PRESETS)
        if shot.preset not in native:
            return False
        if not self.comfy.is_available():
            return False
        if shot.preset in self._NATIVE_I2V_PRESETS:
            if not shot.ref_image or not os.path.isfile(shot.ref_image):
                return False
        if shot.preset in self._NATIVE_UPSCALE_PRESETS:
            iv = (shot.overrides or {}).get("input_video")
            if not iv or not os.path.isfile(iv):
                return False
        return True

    def _queue_comfy_native_wan(self, shot: Shot,
                                 on_complete: Optional[Callable[[Shot], None]]
                                 ) -> Dict[str, Any]:
        """Submit a Wan render via ComfyUI directly, bypassing WanGP.
        Routes through scaffold.video_workflow_dispatch, which calls
        the canonical spellcaster_core.workflows builders
        (build_wan22_t2v and build_wan22_i2v — R128)."""
        ref_basename: Optional[str] = None
        input_filenames: List[str] = []
        needs_ref = shot.preset in self._NATIVE_I2V_PRESETS
        needs_video = shot.preset in self._NATIVE_UPSCALE_PRESETS
        if needs_ref:
            ref_basename = os.path.basename(shot.ref_image)
            try:
                with open(shot.ref_image, "rb") as _rf:
                    ref_bytes = _rf.read()
                self.comfy.upload_image(ref_bytes, ref_basename)
                input_filenames.append(ref_basename)
            except Exception as e:  # noqa: BLE001
                return {"status": "error",
                        "message": f"couldn't upload ref image: {e}"}
        elif needs_video:
            iv = (shot.overrides or {}).get("input_video", "")
            ref_basename = os.path.basename(iv)
            try:
                with open(iv, "rb") as _vf:
                    self.comfy.upload_image(_vf.read(), ref_basename)
                input_filenames.append(ref_basename)
            except Exception as e:  # noqa: BLE001
                return {"status": "error",
                        "message": f"couldn't upload input video: {e}"}

        defaults = (describe_preset(shot.preset) or {}).get("defaults") or {}
        width_h = defaults.get("resolution", "832x480").split("x")
        ov = shot.overrides or {}
        try:
            w = int(ov.get("width") or width_h[0])
            h = int(ov.get("height") or width_h[1])
        except Exception:
            w, h = 832, 480
        length = int(ov.get("frames") or defaults.get("frames", 81))
        fps = int(ov.get("fps") or defaults.get("fps", 16))
        seed = shot.seed if shot.seed is not None else int(time.time()) & 0xFFFFFFFF

        # R131: plumb through the full post-processing chain from
        # shot.overrides. Defaults are conservative (off) so the
        # first render is fast; editors opt in per shot via the
        # Cinematographer / Resolve Bridge / Guild UI.
        loras_high = ov.get("loras_high")  # list of (name, strength)
        loras_low = ov.get("loras_low")

        # teacache: None = defer to canonical auto-logic (True on full-step,
        # False on turbo). Only coerce to bool when the caller explicitly
        # set it — this way the canon's auto-TeaCache still fires for
        # Guild/Resolve/SillyTavern shots that don't pass the key.
        _tc = ov.get("teacache")
        if _tc is not None:
            _tc = bool(_tc)

        # Optional quality + speed patches (CLAUDE.md §16.2). None = let
        # the canonical builder / GIMP wrapper's auto-probe decide. Callers
        # that want explicit control set True/False in the overrides dict.
        def _opt_bool(key):
            v = ov.get(key)
            return bool(v) if v is not None else None

        workflow, err = _build_native_workflow(
            shot.preset,
            prompt=shot.prompt or "subtle gentle motion",
            negative=shot.negative or "",
            seed=seed,
            image_filename=ref_basename,  # None for t2v
            comfyui_base_url=self.comfy.base_url,
            width=w, height=h, length=length, fps=fps,
            turbo=bool(ov.get("turbo",
                                shot.preset == "wan22_i2v_lightning")),
            loras_high=loras_high,
            loras_low=loras_low,
            face_swap=bool(ov.get("face_swap", False)),
            interpolate=bool(ov.get("interpolate", False)),
            rtx_scale=float(ov.get("rtx_scale", 1.0)),
            teacache=_tc,
            tiled_vae=bool(ov.get("tiled_vae", False)),
            ip_adapter_image=ov.get("ip_adapter_image"),
            ip_adapter_weight=float(ov.get("ip_adapter_weight", 0.5)),
            motion_mask=ov.get("motion_mask"),
            pingpong=bool(ov.get("pingpong", False)),
            # New optional patches — tri-state (None/True/False). Callers
            # that want to force-enable pass True; force-disable pass False;
            # leave key absent to fall through to the canonical auto-logic.
            enable_slg=_opt_bool("enable_slg"),
            enable_nag=_opt_bool("enable_nag"),
            enable_sage=_opt_bool("enable_sage"),
            enable_cfg_zero=_opt_bool("enable_cfg_zero"),
            sampler_name=ov.get("sampler_name") or None,
            scheduler=ov.get("scheduler") or None,
            # LTX-specific overrides (CLAUDE.md §16.3). None = let the
            # preset default ride. Used by the Guild shot API for any
            # caller (Darktable, SillyTavern, Resolve, future clients)
            # who wants per-shot quality / speed tuning on LTX.
            steps=ov.get("steps") if ov.get("steps") is not None else None,
            cfg=float(ov["cfg"]) if ov.get("cfg") is not None else None,
            stg=float(ov["stg"]) if ov.get("stg") is not None else None,
            rescale=float(ov["rescale"]) if ov.get("rescale") is not None else None,
            i2v_strength=float(ov["i2v_strength"])
                if ov.get("i2v_strength") is not None else None,
            stg_layers=ov.get("stg_layers") or None,
            chunk_size=int(ov["chunk_size"])
                if ov.get("chunk_size") is not None else None,
            vae_spatial_tiles=int(ov["vae_spatial_tiles"])
                if ov.get("vae_spatial_tiles") is not None else None,
            vae_temporal_tile_length=int(ov["vae_temporal_tile_length"])
                if ov.get("vae_temporal_tile_length") is not None else None,
            vae_last_frame_fix=bool(ov.get("vae_last_frame_fix", False)),
            vae_working_dtype=ov.get("vae_working_dtype") or None,
            extra_loras=ov.get("extra_loras") or None,
        )
        if not workflow:
            return {"status": "error", "message": err or "build failed"}

        self.board.mark_running(shot.id)
        self.board.update(shot.id, backend="comfyui")

        def worker() -> None:
            self._render_sem.acquire()
            try:
                start = time.time()
                result = self.comfy.run_raw(
                    workflow, input_filenames=input_filenames or None)
                if result.get("status") != "ok":
                    self.board.mark_failed(
                        shot.id,
                        f"ComfyUI: {result.get('message', 'unknown error')}")
                    return
                outputs = result.get("outputs") or []
                remote = _pick_video_output(outputs)
                if not remote:
                    self.board.mark_failed(
                        shot.id, "ComfyUI produced no video output")
                    return
                local = os.path.join(
                    self.output_dir,
                    f"{shot.id}_{int(time.time())}.mp4")
                data = self.comfy.download_image(
                    filename=remote["filename"],
                    subfolder=remote.get("subfolder", ""),
                    folder_type=remote.get("type", "output"))
                with open(local, "wb") as fh:
                    fh.write(data)
                self.board.mark_ready(shot.id, local)
                self.board.update(
                    shot.id, render_duration_s=time.time() - start)
                try:
                    last_frame = extract_last_frame(local)
                    self.board.export_for_next(shot.id, last_frame)
                except Exception:
                    pass
                if on_complete:
                    try:
                        on_complete(self.board.get(shot.id))
                    except Exception:  # noqa: BLE001
                        log.exception("on_complete raised (native wan)")
            except Exception as e:  # noqa: BLE001
                self.board.mark_failed(shot.id,
                                        f"native wan worker: {e}")
            finally:
                self._render_sem.release()
                self._active_progress = 0.0
                self._active_stage = "idle"
                self._active_started = 0.0
                with self._in_flight_lock:
                    self._in_flight.pop(shot.id, None)

        t = threading.Thread(target=worker,
                              name=f"native-wan-{shot.id[:8]}",
                              daemon=True)
        with self._in_flight_lock:
            self._in_flight[shot.id] = t
        t.start()
        return {"status": "queued", "shot_id": shot.id,
                 "backend": "comfyui_native_wan"}

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
            self._render_sem.acquire()
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
                self._render_sem.release()
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
        """Inject shot fields into a ComfyUI API-format workflow.

        Meta-title rules for CLIPTextEncode nodes:
          - A title containing ``source`` is treated as a fixed
            description of the ORIGINAL material (v2v source side) —
            not touched by shot.prompt / shot.negative.
          - Otherwise, a title containing ``positive`` takes shot.prompt
            and a title containing ``negative`` takes shot.negative.
          - R87-specific: for FlowEdit workflows the ``Target Positive``
            node is the editor's VFX description; ``Source Positive`` is
            a fixed caption of the real footage.
        """
        import copy as _copy
        patched = _copy.deepcopy(workflow)
        ov = dict(shot.overrides or {})
        input_video = (ov.get("input_video") or "").strip()
        for nid, node in patched.items():
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type", "")
            inp = node.get("inputs", {})
            meta_title = (node.get("_meta") or {}).get("title", "").lower()
            # Prompt injection — skip Source-prefixed titles for v2v flows
            if ct == "CLIPTextEncode" and "text" in inp:
                if "source" in meta_title:
                    pass  # fixed source description — don't touch
                elif "positive" in meta_title and shot.prompt:
                    inp["text"] = shot.prompt
                elif "negative" in meta_title and shot.negative:
                    inp["text"] = shot.negative
            # Seed injection — handle KSampler + FlowEdit variants
            if ct == "KSampler" and "seed" in inp:
                if shot.seed is not None:
                    inp["seed"] = shot.seed
                if "steps" in ov:
                    inp["steps"] = ov["steps"]
                if "guidance" in ov or "cfg" in ov:
                    inp["cfg"] = ov.get("guidance", ov.get("cfg", inp.get("cfg")))
            if ct == "RandomNoise" and "noise_seed" in inp:
                if shot.seed is not None:
                    inp["noise_seed"] = shot.seed
            if ct == "LTXFlowEditSampler":
                if shot.seed is not None and "seed" in inp:
                    inp["seed"] = shot.seed
                if "skip_steps" in ov and "skip_steps" in inp:
                    inp["skip_steps"] = int(ov["skip_steps"])
                if "refine_steps" in ov and "refine_steps" in inp:
                    inp["refine_steps"] = int(ov["refine_steps"])
            if ct == "LTXFlowEditCFGGuider":
                if "target_cfg" in ov and "target_cfg" in inp:
                    inp["target_cfg"] = float(ov["target_cfg"])
                if "source_cfg" in ov and "source_cfg" in inp:
                    inp["source_cfg"] = float(ov["source_cfg"])
            # BasicScheduler
            if ct == "BasicScheduler" and "steps" in inp:
                if "steps" in ov:
                    inp["steps"] = ov["steps"]
            # LTXVScheduler
            if ct == "LTXVScheduler" and "steps" in inp:
                if "steps" in ov:
                    inp["steps"] = int(ov["steps"])
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
            # LoadImage ref / mask injection. A meta title containing
            # "mask" routes to shot.overrides.mask_image (R90). Others
            # take shot.ref_image as before.
            if ct == "LoadImage" and "image" in inp:
                mask_image = (ov.get("mask_image") or "").strip()
                if "mask" in meta_title:
                    if mask_image:
                        inp["image"] = os.path.basename(mask_image)
                elif shot.ref_image:
                    inp["image"] = os.path.basename(shot.ref_image)
            # R87: VHS_LoadVideo ingest — input video patched from
            # shot.overrides["input_video"] (a filename already present in
            # ComfyUI's input/ dir). The caller uploads the file before
            # calling run_raw (_queue_comfy handles this).
            if ct == "VHS_LoadVideo" and "video" in inp:
                if input_video:
                    inp["video"] = os.path.basename(input_video)
                if "frames" in ov and "frame_load_cap" in inp:
                    inp["frame_load_cap"] = int(ov["frames"])
                if "fps" in ov and "force_rate" in inp:
                    inp["force_rate"] = float(ov["fps"])
            # R90: WanVaceToVideo strength override
            if ct == "WanVaceToVideo":
                if "strength" in ov and "strength" in inp:
                    inp["strength"] = float(ov["strength"])

        # R90: if the shot has no mask_image, strip any control_masks
        # wire + drop the orphaned mask LoadImage node. WanVaceToVideo
        # treats control_masks as optional; missing mask = full-frame
        # transform. Doing this at the patch layer (rather than
        # branching in the workflow JSON itself) keeps the template
        # readable while matching the "mask is optional" contract.
        if not (shot.overrides or {}).get("mask_image"):
            mask_node_ids = set()
            for nid, node in patched.items():
                if not isinstance(node, dict):
                    continue
                ct = node.get("class_type", "")
                meta_title = (node.get("_meta") or {}).get(
                    "title", "").lower()
                if ct == "LoadImage" and "mask" in meta_title:
                    mask_node_ids.add(nid)
            # Disconnect control_masks edges referencing a mask node
            for nid, node in patched.items():
                if not isinstance(node, dict):
                    continue
                inp = node.get("inputs") or {}
                if (node.get("class_type") == "WanVaceToVideo"
                        and "control_masks" in inp):
                    ref = inp["control_masks"]
                    if (isinstance(ref, list) and len(ref) == 2
                            and ref[0] in mask_node_ids):
                        del inp["control_masks"]
            for mid in mask_node_ids:
                patched.pop(mid, None)
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
            try:
                with open(shot.ref_image, "rb") as _rf:
                    self.comfy.upload_image(_rf.read(),
                                             os.path.basename(shot.ref_image))
            except Exception as _ue:
                log.warning(f"ref_image upload failed: {_ue}")
        # R90: upload mask_image for mask-based workflows. Small PNG,
        # no antenna staging dance — direct upload from Guild is fine.
        mask_image = (shot.overrides or {}).get("mask_image", "")
        if mask_image and os.path.isfile(mask_image):
            try:
                with open(mask_image, "rb") as _mf:
                    self.comfy.upload_image(
                        _mf.read(), os.path.basename(mask_image))
            except Exception as _ue:
                log.warning(f"mask_image upload failed: {_ue}")

        # R87: resolve the input video for v2v workflows.
        #   - A FULL PATH reachable from the Guild host → upload bytes
        #     to ComfyUI's /upload/image endpoint (cross-host transfer).
        #   - A BARE BASENAME → assumed pre-staged on ComfyUI's input
        #     dir (e.g. via antenna /resolve/stage-input-video in R87b),
        #     no upload needed.
        input_video = (shot.overrides or {}).get("input_video", "")
        if input_video:
            is_bare_basename = (
                os.path.basename(input_video) == input_video
                and not os.path.isabs(input_video)
            )
            if is_bare_basename:
                # Pre-staged by the antenna. Nothing to upload.
                pass
            elif os.path.isfile(input_video):
                try:
                    with open(input_video, "rb") as _vf:
                        self.comfy.upload_image(
                            _vf.read(), os.path.basename(input_video))
                except Exception as _ue:
                    self.board.mark_failed(shot.id,
                        f"input_video upload failed: {_ue}")
                    return {"status": "error",
                            "message": f"input_video upload failed: {_ue}"}
            else:
                self.board.mark_failed(shot.id,
                    f"input_video not found: {input_video}")
                return {"status": "error",
                        "message": f"input_video not found: {input_video}"}

        self.board.mark_running(shot.id)

        def worker() -> None:
            self._render_sem.acquire()
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
                self._render_sem.release()
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
        if not self.comfy.is_available():
            log.warning("Hybrid upscale skipped: ComfyUI not reachable "
                        "at %s", self.comfy.base_url)
            return

        # R135: build the upscale workflow from canonical
        # spellcaster_core.workflows.build_seedvr2_video_upscale
        # instead of loading the stale seedvr2_video_upscale.json.
        # The JSON was a 5-node stub with hardcoded (missing) model
        # names and was never a complete workflow.
        try:
            from spellcaster_core.workflows import (  # type: ignore
                build_seedvr2_video_upscale,
            )
        except ImportError as exc:
            log.warning("Hybrid upscale skipped: canonical builder "
                        "unavailable: %s", exc)
            return

        # Upload the render first so ComfyUI can read it by basename
        video_basename = os.path.basename(video_path)
        try:
            with open(video_path, "rb") as _vf:
                self.comfy.upload_image(_vf.read(), video_basename)
        except Exception as exc:  # noqa: BLE001
            log.warning("Hybrid upscale: couldn't upload source video: %s",
                        exc)
            return

        try:
            workflow = build_seedvr2_video_upscale(
                video_name=video_basename,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Hybrid upscale builder raised: %s", exc)
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
        """Queue all draft shots in dependency-respecting order.

        Uses topological sort so dependencies render before the shots
        that need them.  Shots with unmet dependencies are deferred
        until their deps complete.

        Returns ``{"queued": N, "skipped": M, "deferred": D,
        "has_cycle": bool, "shot_ids": [...]}``
        """
        # Use topological order so deps render first
        sorted_shots = self.board.topological_sort()
        drafts = [s for s in sorted_shots if s.status == "draft"]
        has_cycle = self.board.has_cycle()
        if not drafts:
            return {"queued": 0, "skipped": 0, "deferred": 0,
                    "has_cycle": has_cycle, "shot_ids": []}

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
                        # R59a: if single-step is armed, pause again
                        # AFTER this pickup so the watcher stalls until
                        # the user clicks "Render next" again.
                        if self._auto_pause_after_next:
                            self._auto_pause_after_next = False
                            self._paused = True
                            self._emit("queue_paused", {"reason": "step"})

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
            "deferred": 0,
            "has_cycle": has_cycle,
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
        self._auto_pause_after_next = False
        self._emit("queue_resumed", {})
        return {"status": "resumed"}

    def render_next(self) -> Dict[str, Any]:
        """R59a: release ONE queued shot then auto-pause again.

        Lets the user review each render before committing to the next —
        classic "step through the queue one at a time" flow. Idempotent:
        calling it repeatedly while a shot is still rendering just keeps
        the auto-pause flag set; the next dequeue after the current shot
        finishes will fire once and re-pause.

        Returns {"status": "stepping" | "nothing_to_step",
                 "auto_pause_after_next": bool}.
        """
        # Nothing to step through if the queue is empty of dequeueable shots
        has_pending = any(s.status in ("draft", "queued") for s in self.board)
        if not has_pending:
            return {"status": "nothing_to_step",
                    "auto_pause_after_next": self._auto_pause_after_next}
        self._auto_pause_after_next = True
        self._paused = False
        self._emit("queue_step", {})
        return {"status": "stepping",
                "auto_pause_after_next": True}

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
            "max_concurrent": self._max_concurrent,
            # R59a: true when a user clicked "Render next" — the queue
            # will auto-pause after the NEXT shot lands.
            "auto_pause_after_next": self._auto_pause_after_next,
        }

    # ------------------------------------------------------------------
    # Render concurrency settings
    # ------------------------------------------------------------------

    def get_settings(self) -> Dict[str, Any]:
        """Return current bridge settings."""
        return {
            "max_concurrent": self._max_concurrent,
            "paused": self._paused,
            "export": self._export_settings.to_dict(),
            "favorite_presets": list(self._favorite_presets),
        }

    def set_max_concurrent(self, n: int) -> Dict[str, Any]:
        """Update the maximum number of concurrent renders.

        Rebuilds the semaphore.  Active renders are not interrupted;
        the new limit takes effect for future queue_shot() calls.
        """
        n = max(1, min(n, 8))  # clamp 1–8
        old = self._max_concurrent
        self._max_concurrent = n
        self._render_sem = threading.Semaphore(n)
        self._emit("settings_changed", {"max_concurrent": n})
        return {"max_concurrent": n, "previous": old}

    def get_export_settings(self) -> Dict[str, Any]:
        """Return current export settings as a dict."""
        return self._export_settings.to_dict()

    def set_export_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update export settings from a dict.  Returns the new settings."""
        self._export_settings = ExportSettings.from_dict(data)
        self._emit("settings_changed", {"export": self._export_settings.to_dict()})
        return self._export_settings.to_dict()

    def get_favorite_presets(self) -> List[str]:
        """Return the list of favorited preset keys."""
        return list(self._favorite_presets)

    def set_favorite_presets(self, presets: List[str]) -> List[str]:
        """Replace the favorites list.  Returns the new list."""
        self._favorite_presets = list(presets)
        self._emit("settings_changed", {"favorite_presets": self._favorite_presets})
        return self._favorite_presets

    def toggle_favorite_preset(self, preset: str) -> Dict[str, Any]:
        """Toggle a preset's favorite status.  Returns updated list + status."""
        if preset in self._favorite_presets:
            self._favorite_presets.remove(preset)
            added = False
        else:
            self._favorite_presets.append(preset)
            added = True
        self._emit("settings_changed", {"favorite_presets": self._favorite_presets})
        return {"preset": preset, "favorited": added, "favorites": list(self._favorite_presets)}

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
                            preset: str,
                            snapshot_before: bool = True) -> Dict[str, Any]:
        """Change the preset for multiple shots at once.

        R46a: auto-snapshots each shot first so the user can restore if
        the new preset underperforms. Skipped for shots already on the
        target preset (no-op changes don't need a safety net).
        """
        # Only snapshot shots that will actually change
        changing = [sid for sid in shot_ids
                    if (s := self.board.get(sid)) is not None
                    and s.status == "draft"
                    and s.preset != preset]
        auto_snapped = 0
        if snapshot_before and changing:
            auto_snapped = self.board._auto_snapshot_batch(
                changing, f"before preset -> {preset}")
        updated = 0
        for sid in shot_ids:
            shot = self.board.get(sid)
            if shot and shot.status == "draft":
                self.board.update(sid, preset=preset)
                updated += 1
        return {"updated": updated, "preset": preset,
                "auto_snapshots": auto_snapped}

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

# ══════════════════════════════════════════════════════════════════════
# Export settings
# ══════════════════════════════════════════════════════════════════════

# Supported codecs for final assembly
EXPORT_CODECS = ("h264", "h265", "vp9", "prores")
EXPORT_RESOLUTIONS = ("source", "1920x1080", "1280x720", "3840x2160", "1080x1920", "720x1280")


@dataclass
class ExportSettings:
    """User-configurable settings for final video assembly.

    resolution: "source" keeps original, or "WxH" string
    codec: one of EXPORT_CODECS
    fps: frames per second (0 = keep source)
    crf: constant rate factor (quality; lower = better; 0-51 for h264/h265)
    audio: whether to include audio tracks
    """
    resolution: str = "source"
    codec: str = "h264"
    fps: int = 0
    crf: int = 23
    audio: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExportSettings":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    def ffmpeg_output_args(self) -> List[str]:
        """Build the ffmpeg output arguments for these settings."""
        args = []
        # Codec
        codec_map = {
            "h264": ["-c:v", "libx264"],
            "h265": ["-c:v", "libx265"],
            "vp9": ["-c:v", "libvpx-vp9"],
            "prores": ["-c:v", "prores_ks", "-profile:v", "3"],
        }
        args.extend(codec_map.get(self.codec, ["-c:v", "libx264"]))
        # CRF (not for prores)
        if self.codec != "prores":
            crf = max(0, min(51, self.crf))
            args.extend(["-crf", str(crf)])
        # FPS
        if self.fps > 0:
            args.extend(["-r", str(self.fps)])
        # Resolution
        if self.resolution and self.resolution != "source":
            try:
                w, h = self.resolution.split("x")
                # Use scale filter with padding to handle odd dimensions
                args.extend(["-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"])
            except ValueError:
                pass  # malformed, skip
        # Audio
        if not self.audio:
            args.append("-an")
        else:
            args.extend(["-c:a", "aac", "-b:a", "192k"])
        return args


def _xfade_name(transition: str) -> str:
    """Map our transition names to ffmpeg xfade transition names."""
    mapping = {
        "fade": "fade",
        "crossfade": "fade",
        "wipeleft": "wipeleft",
        "wiperight": "wiperight",
        "wipeup": "wipeup",
        "wipedown": "wipedown",
    }
    return mapping.get(transition, "fade")



def _build_xfade_filter(ready_shots, videos):
    """Build an ffmpeg filter_complex string with xfade transitions.

    ready_shots: list of Shot objects (only those with status=ready, ordered)
    videos: list of video paths (same order/length as ready_shots)

    Returns (filter_str, output_label) or (None, None) if all cuts.
    """
    n = len(videos)
    if n < 2:
        return None, None

    # Collect transitions: shot[i].transition defines how shot[i] blends
    # into shot[i+1].  We need n-1 transitions.
    transitions = []
    for i in range(n - 1):
        t_type = getattr(ready_shots[i], "transition", "cut")
        t_ms = getattr(ready_shots[i], "transition_ms", 500)
        transitions.append((t_type, t_ms))

    # If every transition is a hard cut, skip xfade entirely
    if all(t == "cut" for t, _ in transitions):
        return None, None

    # Build chained xfade filters.
    # Each xfade takes two inputs and produces one output.
    # First pair: [0:v][1:v] xfade=... [v01]
    # Then:       [v01][2:v] xfade=... [v012]  etc.
    parts = []
    prev_label = "[0:v]"
    for i, (t_type, t_ms) in enumerate(transitions):
        next_input = f"[{i+1}:v]"
        out_label = f"[v{i}]"
        if t_type == "cut":
            # For a cut in the middle of xfade chain, use 0-duration fade
            duration_s = 0.001
            xfade = "fade"
        else:
            duration_s = max(0.1, t_ms / 1000.0)
            xfade = _xfade_name(t_type)
        # offset = time at which the transition starts (seconds from stream start)
        # For simplicity, we use the shot's duration minus the transition duration.
        # Since we don't know exact durations here, we use a fixed offset of 0
        # and let ffmpeg figure it out — actually, xfade needs an explicit offset.
        # We'll compute cumulative offsets from shot durations.
        parts.append((prev_label, next_input, xfade, duration_s, out_label))
        prev_label = out_label

    # To compute offsets, we need shot durations.  Probe each video.
    durations = []
    for v in videos:
        dur = _probe_duration(v)
        durations.append(dur if dur else 3.0)  # fallback 3s

    filter_parts = []
    cumulative = 0.0
    for i, (inp_a, inp_b, xfade, dur_s, out_lbl) in enumerate(parts):
        # offset = cumulative duration of all previous segments minus
        # the sum of all previous transition durations, minus this transition
        offset = cumulative - dur_s
        if offset < 0:
            offset = 0
        filter_parts.append(
            f"{inp_a}{inp_b}xfade=transition={xfade}:duration={dur_s:.3f}"
            f":offset={offset:.3f}{out_lbl}"
        )
        cumulative += durations[i] - dur_s

    final_label = parts[-1][4]  # last output label
    filter_str = ";".join(filter_parts)
    return filter_str, final_label


def _probe_duration(video_path: str) -> Optional[float]:
    """Use ffprobe to get the duration of a video file in seconds."""
    import shutil
    import subprocess
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            ValueError, AttributeError):
        return None


def assemble_shots(board, output_dir: str = None, export_settings: ExportSettings = None) -> Optional[str]:
    """Concatenate all ready shots into a single mp4.

    If shots have xfade transitions defined, uses ffmpeg's xfade filter
    for blending.  Otherwise uses the concat demuxer (fast, no re-encode)
    with a fallback to the concat filter (re-encodes).

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

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("ffmpeg not found — cannot assemble shots")
        return None

    if export_settings is None:
        export_settings = ExportSettings()
    output_args = export_settings.ffmpeg_output_args()

    # Choose file extension based on codec
    ext = ".webm" if export_settings.codec == "vp9" else ".mov" if export_settings.codec == "prores" else ".mp4"
    out_path = os.path.join(output_dir,
                            f"assembled_{int(time.time())}{ext}")

    # Gather the ready shots in order (matching board.ready_videos() order)
    ready_shots = [s for s in board if s.status == "ready" and s.video_path]

    # --- Try xfade transitions first ----------------------------------
    xfade_filter, out_label = _build_xfade_filter(ready_shots, videos)
    if xfade_filter:
        inputs = []
        for v in videos:
            inputs += ["-i", v]
        try:
            subprocess.run(
                [ffmpeg, "-y"] + inputs +
                ["-filter_complex", xfade_filter,
                 "-map", out_label] + output_args + [out_path],
                check=True, capture_output=True, timeout=600,
            )
            return out_path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("xfade assembly failed (%s), falling back to concat", exc)

    # --- Try concat demuxer (fast, no re-encode) ----------------------
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
             "-map", "[outv]", "-map", "[outa]"] + output_args + [out_path],
            check=True, capture_output=True, timeout=600,
        )
        return out_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.error("ffmpeg assembly failed: %s", exc)
        return None
