"""
WanGP Runner — thin client for deepbeepmeep/Wan2GP (WanGP) as a video
generation backend for Spellcaster.

WanGP is a Gradio app wrapping Wan 2.1/2.2, LTX-2.x, Hunyuan, Ovi,
Wan-Move, SCAIL etc. with a persistent task queue and aggressive VRAM
optimisation.  It exposes the standard Gradio HTTP API, which means we
can queue jobs from Spellcaster with no extra dependencies — just
stdlib urllib, matching the rest of the scaffold.

Why a separate runner and not ComfyUIRunner?
  - WanGP is not a ComfyUI.  It does not speak /prompt or /history.
    Its API surface is /gradio_api/call/<fn_index> (predict) plus
    event-stream polling of /gradio_api/call/<fn_index>/<event_id>.
  - WanGP owns the model-selection and low-VRAM orchestration, so
    Spellcaster should treat it as a higher-level primitive: pick a
    preset ("wan_i2v_14b_lightning", "ltx2_distilled", "wan_move_i2v"),
    pass inputs, wait for video.
  - WanGP's queue survives crashes (queue.zip) so we can fire-and-poll
    without holding state on our side.

Privacy:
  WanGP runs locally by default; outputs live in its output/ folder.
  There is no built-in remote cleanup API (unlike ComfyUI-api-tools).
  For Signal Bridge / remote users, the WanGPRunner downloads the
  generated video bytes then the caller is expected to delete the
  local WanGP copy via `delete_output(path)` if privacy matters.

This module has zero dependencies beyond stdlib.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("spellcaster.wangp")


# -----------------------------------------------------------------------------
# Preset catalogue
# -----------------------------------------------------------------------------
# Each preset maps a Spellcaster-facing name to the WanGP generation tab and
# the minimum input shape expected.  This layer is what lets the
# CinematographerWizard talk in user-terms ("fast draft", "cinematic i2v",
# "draw-the-path") without leaking WanGP internals.
#
# The `tab` / `fn_index` values are filled in at runtime by probing WanGP's
# Gradio config (see WanGPRunner._load_endpoints), because Gradio numbers
# change between WanGP versions.  The preset only declares intent.

WANGP_PRESETS: Dict[str, Dict[str, Any]] = {
    "wan22_i2v_lightning": {
        "label": "Wan 2.2 Image-to-Video (Lightning)",
        "family": "wan",
        "task": "i2v",
        "model_hint": "wan2.2-i2v-14b-lightning",
        "inputs": ["image", "prompt"],
        "defaults": {"steps": 6, "guidance": 1.0, "frames": 81, "fps": 16,
                     "resolution": "832x480"},
        "vram_min_gb": 8,
        "notes": "Fastest cinematic I2V. Good default for shot previews.",
    },
    "wan22_i2v_hq": {
        "label": "Wan 2.2 Image-to-Video (Quality)",
        "family": "wan",
        "task": "i2v",
        "model_hint": "wan2.2-i2v-14b",
        "inputs": ["image", "prompt"],
        "defaults": {"steps": 25, "guidance": 5.0, "frames": 81, "fps": 16,
                     "resolution": "1280x720"},
        "vram_min_gb": 12,
        "notes": "Heavier motion realism. Use for finals.",
    },
    "wan22_t2v": {
        "label": "Wan 2.2 Text-to-Video",
        "family": "wan",
        "task": "t2v",
        "model_hint": "wan2.2-t2v-14b",
        "inputs": ["prompt"],
        "defaults": {"steps": 20, "guidance": 5.0, "frames": 81, "fps": 16,
                     "resolution": "832x480"},
        "vram_min_gb": 10,
        "notes": "No reference image required.",
    },
    "ltx2_distilled": {
        "label": "LTX-2.3 Distilled (fast + audio)",
        "family": "ltx",
        "task": "t2v_audio",
        "model_hint": "ltx-2.3-distilled",
        "inputs": ["prompt"],
        "defaults": {"steps": 8, "guidance": 3.0, "frames": 121, "fps": 24,
                     "resolution": "768x512"},
        "vram_min_gb": 8,
        "notes": "Single-pass video + ambient audio. Great for iterating.",
    },
    "ltx2_dev": {
        "label": "LTX-2.3 Dev (HQ two-stage)",
        "family": "ltx",
        "task": "t2v",
        "model_hint": "ltx-2.3-dev",
        "inputs": ["prompt"],
        "defaults": {"steps": 30, "guidance": 4.5, "frames": 121, "fps": 24,
                     "resolution": "1280x720"},
        "vram_min_gb": 16,
        "notes": "High-quality LTX. Slower, better detail.",
    },
    "wan_move_i2v": {
        "label": "Wan-Move I2V (trajectory control)",
        "family": "wan",
        "task": "move_i2v",
        "model_hint": "wan-move-14b-480p",
        "inputs": ["image", "prompt", "trajectories"],
        "defaults": {"steps": 20, "guidance": 5.0, "frames": 81, "fps": 16,
                     "resolution": "832x480"},
        "vram_min_gb": 10,
        "notes": "Drive motion by drawing arrows on the ref image.",
    },
    "scail_preview": {
        "label": "SCAIL (multi-char 3D pose)",
        "family": "wan",
        "task": "scail",
        "model_hint": "scail-preview",
        "inputs": ["image", "prompt", "pose_video"],
        "defaults": {"steps": 20, "guidance": 5.0, "frames": 81, "fps": 16},
        "vram_min_gb": 12,
        "notes": "Character performance transfer with occlusion awareness.",
    },
    "ovi_720p_audio": {
        "label": "Ovi (720p with speech)",
        "family": "ovi",
        "task": "t2av",
        "model_hint": "ovi",
        "inputs": ["prompt", "audio_sample?"],
        "defaults": {"frames": 121, "fps": 24, "resolution": "1280x720"},
        "vram_min_gb": 6,
        "notes": "Ultra-low VRAM talking-head video + audio.",
    },

    # ─── R86: ComfyUI-backed presets ──────────────────────────────────
    # These map to workflow JSONs at scaffold/workflows/<preset-key>.json.
    # Shots using them must set backend="comfyui" — the video bridge's
    # _queue_comfy path reads the JSON, patches in prompt / seed /
    # ref_image via _patch_comfy_workflow, and sends to ComfyUI.
    # `engine` is a new hint field: "comfyui" → Guild UI nudges the
    # backend selector to ComfyUI.
    "ltx2_image_to_video": {
        "label": "LTX-2.3 Image-to-Video (ComfyUI)",
        "family": "ltx",
        "task": "i2v",
        "engine": "comfyui",
        "inputs": ["image", "prompt"],
        "defaults": {"steps": 8, "guidance": 3.0, "frames": 121, "fps": 24,
                     "resolution": "768x512"},
        "vram_min_gb": 12,
        "notes": "Footage-friendly: drop a frame in, get an animated "
                  "clip back. Alternative to Wan i2v via ComfyUI. Use "
                  "for restyling / extending individual shots.",
    },
    "ltx2_text_to_video_distilled": {
        "label": "LTX-2.3 T2V Distilled (ComfyUI)",
        "family": "ltx",
        "task": "t2v",
        "engine": "comfyui",
        "inputs": ["prompt"],
        "defaults": {"steps": 8, "guidance": 3.0, "frames": 121, "fps": 24,
                     "resolution": "768x512"},
        "vram_min_gb": 10,
        "notes": "Fast LTX-2.3 t2v via ComfyUI. No audio (use "
                  "ltx2_distilled if you want speech).",
    },
    "ltx2_text_to_video_2stage": {
        "label": "LTX-2.3 T2V Two-Stage HQ (ComfyUI)",
        "family": "ltx",
        "task": "t2v",
        "engine": "comfyui",
        "inputs": ["prompt"],
        "defaults": {"steps": 30, "guidance": 4.5, "frames": 121, "fps": 24,
                     "resolution": "1280x720"},
        "vram_min_gb": 16,
        "notes": "Two-stage LTX-2.3 for maximum detail. Slower; use "
                  "for finals and beauty passes.",
    },
    "ltx2_text_to_video": {
        "label": "LTX-2.3 T2V Standard (ComfyUI)",
        "family": "ltx",
        "task": "t2v",
        "engine": "comfyui",
        "inputs": ["prompt"],
        "defaults": {"steps": 20, "guidance": 4.0, "frames": 121, "fps": 24,
                     "resolution": "1024x576"},
        "vram_min_gb": 12,
        "notes": "Baseline LTX-2.3 t2v at middling quality/speed tradeoff.",
    },
    "ltx2_t2v_with_rife_interpolation": {
        "label": "LTX-2.3 T2V + RIFE (smooth 60fps)",
        "family": "ltx",
        "task": "t2v",
        "engine": "comfyui",
        "inputs": ["prompt"],
        "defaults": {"steps": 20, "guidance": 4.0, "frames": 121, "fps": 60,
                     "resolution": "1024x576"},
        "vram_min_gb": 14,
        "notes": "LTX t2v piped through RIFE for 60fps buttery output. "
                  "Great for slow-mo sim.",
    },
    "ltx2_t2v_with_rtx_upscale": {
        "label": "LTX-2.3 T2V + RTX Upscale",
        "family": "ltx",
        "task": "t2v",
        "engine": "comfyui",
        "inputs": ["prompt"],
        "defaults": {"steps": 20, "guidance": 4.0, "frames": 121, "fps": 24,
                     "resolution": "1920x1080"},
        "vram_min_gb": 16,
        "notes": "LTX t2v followed by NVIDIA RTX Video Super-Resolution "
                  "to 1080p. Single-pass 'good-looking' preset.",
    },
    "seedvr2_video_upscale": {
        "label": "SeedVR2 Video Upscaler (ComfyUI)",
        "family": "seedvr2",
        "task": "upscale",
        "engine": "comfyui",
        "inputs": ["video"],
        "defaults": {"resolution": "1920x1080", "fps": 24},
        "vram_min_gb": 12,
        "notes": "AI video upscaler (2x-4x) — takes an existing clip and "
                  "reprojects it at higher resolution with temporal "
                  "consistency. Use on rendered Spellcaster clips before "
                  "final delivery.",
    },
}


def preset_names() -> List[str]:
    """Return the list of Spellcaster-visible WanGP preset keys."""
    return list(WANGP_PRESETS.keys())


def describe_preset(key: str) -> Dict[str, Any]:
    """Return a shallow copy of a preset spec, or {} if unknown."""
    spec = WANGP_PRESETS.get(key)
    return dict(spec) if spec else {}


# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

class WanGPRunner:
    """Thin client for a running WanGP Gradio server.

    Usage::

        runner = WanGPRunner("http://localhost:7860")
        if not runner.is_available():
            raise RuntimeError("WanGP not running")
        job = runner.queue_generation(
            preset="wan22_i2v_lightning",
            prompt="a cat yawning, cinematic",
            image_path="/tmp/cat.png",
        )
        result = runner.wait(job["job_id"])
        # result["videos"] -> list of absolute paths to generated mp4s
    """

    def __init__(self, base_url: str = "http://localhost:7860",
                 timeout: int = 1800,
                 poll_interval: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._gradio_config: Optional[Dict[str, Any]] = None
        self._endpoint_map: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if a Gradio app answers at base_url."""
        try:
            req = urllib.request.Request(f"{self.base_url}/config")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    return False
                # Cache config for endpoint discovery
                body = resp.read().decode("utf-8", errors="replace")
                self._gradio_config = json.loads(body)
                return True
        except Exception as exc:  # noqa: BLE001
            log.debug("WanGP not reachable at %s: %s", self.base_url, exc)
            return False

    def server_info(self) -> Dict[str, Any]:
        """Return a short summary of the connected WanGP instance."""
        if self._gradio_config is None and not self.is_available():
            return {"available": False, "url": self.base_url}
        cfg = self._gradio_config or {}
        return {
            "available": True,
            "url": self.base_url,
            "version": cfg.get("version"),
            "app_id": cfg.get("app_id"),
            "title": cfg.get("title"),
            "theme": cfg.get("theme"),
            "components": len(cfg.get("components", [])),
        }

    # ------------------------------------------------------------------
    # Endpoint discovery
    # ------------------------------------------------------------------

    def _load_endpoints(self) -> Dict[str, int]:
        """Build a best-effort map of logical names -> Gradio fn_index.

        WanGP's Gradio config exposes `dependencies`, each with a `js` hint,
        an `api_name`, and an `inputs`/`outputs` wiring.  We look for any
        dep with a named api_name (WanGP 9.x+ labels its main generate
        function as `generate`) and fall back to heuristic matching on
        component labels.

        Gradio fn_index numbers are *not stable* across WanGP versions —
        the preset.family/task lookup is what keeps Spellcaster portable.
        """
        if self._endpoint_map:
            return self._endpoint_map
        if self._gradio_config is None and not self.is_available():
            return {}
        cfg = self._gradio_config or {}
        deps = cfg.get("dependencies", []) or []
        endpoint_map: Dict[str, int] = {}
        for idx, dep in enumerate(deps):
            api_name = dep.get("api_name") or ""
            if not api_name:
                continue
            # Normalise: gradio prefixes with '/' sometimes
            key = api_name.lstrip("/")
            endpoint_map.setdefault(key, idx)
        self._endpoint_map = endpoint_map
        if not endpoint_map:
            log.warning("WanGP exposed no named Gradio endpoints; "
                        "falling back to positional fn_index=0")
        return endpoint_map

    def _resolve_fn_index(self, endpoint_hint: str) -> int:
        """Map a Spellcaster endpoint hint to a Gradio fn_index.

        WanGP's generate endpoint is commonly ``generate`` or ``run``.
        We try several names before falling back to 0.
        """
        endpoints = self._load_endpoints()
        for candidate in (endpoint_hint, "generate", "run", "predict"):
            if candidate in endpoints:
                return endpoints[candidate]
        return 0

    # ------------------------------------------------------------------
    # Input marshalling
    # ------------------------------------------------------------------

    def _upload_file(self, local_path: str) -> str:
        """Upload a file to Gradio's /upload endpoint, return server path.

        Gradio's upload is a POST multipart/form-data returning a JSON
        list of uploaded-file paths.  These paths are what Gradio inputs
        expect (Gradio 4.x: ``{"path": ..., "url": ..., "meta": ...}``).

        We keep the uploaded-path string form because that's what
        /gradio_api/call expects for file inputs.
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)

        boundary = f"----spellcaster{uuid.uuid4().hex}"
        filename = os.path.basename(local_path)
        with open(local_path, "rb") as fh:
            body = fh.read()

        prelude = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; '
            f'filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        epilogue = f"\r\n--{boundary}--\r\n".encode("utf-8")
        payload = prelude + body + epilogue

        req = urllib.request.Request(
            f"{self.base_url}/upload",
            data=payload,
            method="POST",
        )
        req.add_header("Content-Type",
                       f"multipart/form-data; boundary={boundary}")
        req.add_header("Content-Length", str(len(payload)))

        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Gradio returns a JSON list of paths
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unexpected /upload response: {raw[:200]}") from exc
        if not isinstance(data, list) or not data:
            raise RuntimeError(f"Empty upload response: {raw[:200]}")
        return data[0]

    def _build_inputs(self, preset: Dict[str, Any],
                      prompt: str,
                      image_path: Optional[str],
                      overrides: Dict[str, Any],
                      trajectories: Optional[Any] = None) -> List[Any]:
        """Build the Gradio `data` array for a generation call.

        NOTE: WanGP's component order varies by version, so this method
        returns the *logical* payload.  The caller is responsible for
        reshuffling into positional order via its saved schema — see
        CinematographerWizard.describe_inputs().

        For now we return a dict (easier to debug) and the HTTP layer
        wraps it.  If/when WanGP publishes a stable JSON schema, we swap
        this for real positional args.
        """
        merged = dict(preset.get("defaults") or {})
        merged.update(overrides or {})
        payload: Dict[str, Any] = {
            "preset": preset.get("model_hint"),
            "family": preset.get("family"),
            "task": preset.get("task"),
            "prompt": prompt,
            **merged,
        }
        if image_path:
            payload["image_path"] = self._upload_file(image_path)
        if trajectories is not None:
            payload["trajectories"] = trajectories
        return [payload]  # Gradio expects a list of positional args

    # ------------------------------------------------------------------
    # Generation lifecycle
    # ------------------------------------------------------------------

    def queue_generation(self,
                         preset: str,
                         prompt: str,
                         image_path: Optional[str] = None,
                         trajectories: Optional[Any] = None,
                         overrides: Optional[Dict[str, Any]] = None,
                         endpoint_hint: str = "generate",
                         ) -> Dict[str, Any]:
        """Submit a generation job to WanGP and return a job handle.

        Returns::
            {"status": "queued", "job_id": "<event_id>",
             "preset": "...", "fn_index": N}

        On error, status is "error" with a ``message`` field.
        """
        spec = WANGP_PRESETS.get(preset)
        if not spec:
            return {"status": "error",
                    "message": f"Unknown preset: {preset}"}

        if "image" in spec["inputs"] and not image_path:
            return {"status": "error",
                    "message": f"Preset {preset!r} requires image_path"}
        if "trajectories" in spec["inputs"] and not trajectories:
            return {"status": "error",
                    "message": f"Preset {preset!r} requires trajectories"}

        if not self.is_available():
            return {"status": "error",
                    "message": f"WanGP not reachable at {self.base_url}"}

        try:
            data = self._build_inputs(spec, prompt, image_path,
                                      overrides or {}, trajectories)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error",
                    "message": f"Failed to build inputs: {exc}"}

        fn_index = self._resolve_fn_index(endpoint_hint)
        url = f"{self.base_url}/gradio_api/call/{urllib.parse.quote(endpoint_hint)}"
        body = json.dumps({"data": data, "fn_index": fn_index}).encode("utf-8")

        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return {"status": "error",
                    "message": f"WanGP rejected job: HTTP {exc.code}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error",
                    "message": f"WanGP queue failed: {exc}"}

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "error",
                    "message": f"Non-JSON queue response: {raw[:200]}"}

        event_id = (parsed.get("event_id")
                    or parsed.get("hash")
                    or parsed.get("eventId"))
        if not event_id:
            return {"status": "error",
                    "message": f"No event_id in response: {raw[:200]}"}

        return {"status": "queued", "job_id": event_id,
                "preset": preset, "fn_index": fn_index,
                "endpoint": endpoint_hint}

    def poll(self, job_id: str, endpoint_hint: str = "generate") -> Dict[str, Any]:
        """Poll a running WanGP job once. Returns a status dict.

        The Gradio event-stream reports progress messages; we only
        return the latest snapshot, so the caller can show progress
        without managing the stream themselves.
        """
        url = (f"{self.base_url}/gradio_api/call/"
               f"{urllib.parse.quote(endpoint_hint)}/"
               f"{urllib.parse.quote(job_id)}")
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": f"poll failed: {exc}"}

        # Gradio SSE: lines alternate "event: <name>" / "data: <json>"
        latest_event = None
        latest_data: Any = None
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("event:"):
                latest_event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    latest_data = json.loads(payload)
                except json.JSONDecodeError:
                    latest_data = payload

        if latest_event == "complete":
            return {"status": "ok", "outputs": latest_data or []}
        if latest_event == "error":
            return {"status": "error",
                    "message": str(latest_data or "unknown WanGP error")}
        # "generating" / "estimation" / "heartbeat" all roll up as running
        return {"status": "running", "event": latest_event,
                "progress": latest_data}

    def wait(self, job_id: str, endpoint_hint: str = "generate",
             on_progress=None) -> Dict[str, Any]:
        """Block until a WanGP job completes, errors, or times out.

        Args:
            job_id:         event id returned by queue_generation()
            endpoint_hint:  same value passed to queue_generation()
            on_progress:    optional callable(progress_dict) for UI hooks

        Returns the final poll result dict, adding "videos" when the
        run succeeded.
        """
        start = time.time()
        while True:
            snap = self.poll(job_id, endpoint_hint=endpoint_hint)
            if snap.get("status") in ("ok", "error"):
                if snap.get("status") == "ok":
                    snap["videos"] = _extract_video_paths(snap.get("outputs"))
                return snap
            if on_progress:
                try:
                    on_progress(snap)
                except Exception:  # noqa: BLE001
                    log.debug("on_progress raised; ignoring", exc_info=True)
            if time.time() - start > self.timeout:
                return {"status": "error",
                        "message": f"WanGP job {job_id} timed out "
                                   f"after {self.timeout}s"}
            time.sleep(self.poll_interval)

    # ------------------------------------------------------------------
    # Download / cleanup
    # ------------------------------------------------------------------

    def download_video(self, remote_path: str, dest_path: str) -> str:
        """Download a generated video from WanGP to `dest_path`.

        Gradio serves files via ``/file=<path>``.  This is how we get
        WanGP outputs off the server for the Shotboard cache.
        """
        url = f"{self.base_url}/file={urllib.parse.quote(remote_path)}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)) or ".",
                    exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(data)
        return dest_path

    def delete_output(self, remote_path: str) -> bool:
        """Best-effort deletion of a WanGP output file (local-FS only).

        WanGP and Spellcaster typically share the same host for local
        installs, so if the path is reachable on our side we delete it.
        For remote WanGP (different machine) this is a no-op and returns
        False; the user must clean up on the WanGP host.
        """
        try:
            if os.path.isfile(remote_path):
                os.remove(remote_path)
                return True
        except Exception:  # noqa: BLE001
            log.warning("Could not delete WanGP output %s",
                        remote_path, exc_info=True)
        return False


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _extract_video_paths(outputs: Any) -> List[str]:
    """Pull plausible video paths out of a Gradio outputs blob.

    WanGP returns a list whose items can be:
      - dicts with a 'path' or 'name' key (Gradio 4.x File component)
      - strings (paths)
      - nested lists (galleries)
    """
    if not outputs:
        return []
    paths: List[str] = []

    def walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, str):
            if obj.lower().endswith((".mp4", ".webm", ".mov", ".mkv")):
                paths.append(obj)
            return
        if isinstance(obj, dict):
            for key in ("path", "name", "url"):
                val = obj.get(key)
                if isinstance(val, str):
                    walk(val)
            return
        if isinstance(obj, (list, tuple)):
            for item in obj:
                walk(item)

    walk(outputs)
    # dedupe, preserve order
    seen = set()
    unique: List[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique
