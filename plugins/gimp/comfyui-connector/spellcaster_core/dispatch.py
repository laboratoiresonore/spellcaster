"""Unified Workflow Dispatch — single entry point for all ComfyUI generation.

Every image/video generation in Spellcaster routes through dispatch_workflow(),
regardless of which frontend triggered it (GIMP, Wizard Guild, CLI, calibration).
This guarantees consistent behavior for:

  1. Preflight validation (node substitution, fallback)
  2. Workflow optimization (VRAM capping, auto-tuning)
  3. LLM VRAM management (call /free before heavy generation)
  4. Privacy cleanup (wipe temp files from ComfyUI after delivery)

NOT routed through this: comfyui_llm.py text generation (the LLM IS the model
being evicted by free_vram — routing it here would be circular).

USAGE:
    from spellcaster_core.dispatch import dispatch_workflow

    result = dispatch_workflow(
        "http://192.168.x.x:8188", workflow,
        free_vram=True,   # evict LLM before heavy generation
        privacy=True,     # wipe temp files after
    )
    for fn, sf, ft in result.outputs:
        print(f"Output: {fn}")
"""

import dataclasses
import json
import os
import time
import urllib.request
import urllib.error


@dataclasses.dataclass
class DispatchResult:
    """Standardized result from a ComfyUI workflow execution."""
    prompt_id: str
    outputs: list       # [(filename, subfolder, folder_type), ...]
    elapsed: float      # seconds from submit to completion
    warnings: list      # preflight/optimizer messages


# ═══════════════════════════════════════════════════════════════════════
#  Privacy resolution
# ═══════════════════════════════════════════════════════════════════════

def _should_cleanup(explicit):
    """Determine whether privacy cleanup should run.

    Resolution order:
      1. Explicit True/False passed by caller → use that
      2. SPELLCASTER_PRIVACY_CLEANUP env var → "1"/"true"/"yes"
      3. Default: True (privacy ON by default)
    """
    if explicit is not None:
        return bool(explicit)
    env = os.environ.get("SPELLCASTER_PRIVACY_CLEANUP")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes")
    return True


# ═══════════════════════════════════════════════════════════════════════
#  VRAM management
# ═══════════════════════════════════════════════════════════════════════

def _free_vram(server):
    """Ask ComfyUI to unload all cached models and free VRAM.

    This evicts the LLM (and any other cached model) before heavy
    image generation, ensuring maximum VRAM is available. Models
    reload automatically on next use.
    """
    try:
        url = f"{server.rstrip('/')}/free"
        body = json.dumps({
            "unload_models": True,
            "free_memory": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # /free may not exist on older ComfyUI versions


# ═══════════════════════════════════════════════════════════════════════
#  Core dispatch
# ═══════════════════════════════════════════════════════════════════════

def dispatch_workflow(server, workflow, *, timeout=300, free_vram=False,
                      preflight=True, optimize=True, privacy=None,
                      on_progress=None):
    """Submit a workflow to ComfyUI with full lifecycle management.

    Args:
        server: ComfyUI server URL (e.g. "http://192.168.x.x:8188")
        workflow: ComfyUI workflow dict (node graph)
        timeout: Max seconds to wait for completion
        free_vram: If True, call /free to evict cached models before submit.
                   Use for heavy generation (img2img, txt2img, video).
                   Skip for lightweight jobs (64x64 calibration tests).
        preflight: Run node validation and automatic fallbacks
        optimize: Run VRAM capping and auto-tuning
        privacy: True/False to override, None to read from env/config.
                 When enabled, wipes all temp files from ComfyUI after
                 results are downloaded.
        on_progress: Optional callback(stage: str, detail: str) for progress.
                     Stages: "preflight", "optimize", "free", "submit",
                     "poll", "cleanup", "done".

    Returns:
        DispatchResult with prompt_id, outputs, elapsed, warnings.

    Raises:
        RuntimeError on critical failures (missing nodes, server offline).
    """
    server = server.rstrip("/")
    warnings = []

    def _progress(stage, detail=""):
        if on_progress:
            try:
                on_progress(stage, detail)
            except Exception:
                pass

    # ── 1. Preflight ──────────────────────────────────────────────
    if preflight:
        _progress("preflight", "checking nodes...")
        try:
            from .preflight import preflight_workflow
            ok, workflow, report = preflight_workflow(workflow, server)
            for orig, desc in report.get("substituted", []):
                warnings.append(f"Preflight: {orig} -> {desc}")
            if not ok:
                missing = report.get("missing", [])
                raise RuntimeError(
                    f"Missing ComfyUI nodes: {', '.join(missing)}. "
                    f"Install the required custom nodes on your server.")
        except ImportError:
            pass

    # ── 2. Optimize ───────────────────────────────────────────────
    if optimize:
        _progress("optimize", "tuning workflow...")
        try:
            from .optimizer import optimize_workflow
            workflow, opt_warnings = optimize_workflow(
                workflow, comfy_url=server)
            for w in opt_warnings:
                warnings.append(f"Optimizer: {w}")
        except ImportError:
            pass

    # ── 3. Free VRAM ──────────────────────────────────────────────
    if free_vram:
        _progress("free", "unloading cached models...")
        _free_vram(server)

    # ── 4. Submit ─────────────────────────────────────────────────
    _progress("submit", "posting workflow...")
    t0 = time.time()
    try:
        body = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(
            f"{server}/prompt", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            prompt_id = data.get("prompt_id")
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_detail = json.loads(err_body) if err_body else {}
            node_errors = err_detail.get("node_errors", {})
            if node_errors:
                msgs = []
                for nid, info in node_errors.items():
                    cls = info.get("class_type", nid)
                    for er in info.get("errors", []):
                        msgs.append(f"{cls}: {er.get('message', str(er))}")
                detail = "; ".join(msgs) if msgs else err_body[:500]
            else:
                detail = err_body[:500]
        except Exception:
            detail = str(e)
        raise RuntimeError(f"ComfyUI rejected workflow: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"ComfyUI is offline at {server}: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to submit to ComfyUI: {e}")

    if not prompt_id:
        raise RuntimeError("ComfyUI did not return a prompt_id")

    # ── 5. Poll for results ───────────────────────────────────────
    _progress("poll", "waiting for completion...")
    history_url = f"{server}/history/{prompt_id}"
    deadline = time.time() + timeout

    outputs = []
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(history_url, timeout=5) as resp:
                h = json.loads(resp.read().decode("utf-8"))

            if prompt_id not in h:
                time.sleep(0.5)
                continue

            entry = h[prompt_id]
            status = entry.get("status", {})

            # Check for execution error
            if status.get("status_str") == "error":
                err_msg = ""
                for msg in status.get("messages", []):
                    if msg[0] == "execution_error":
                        err_msg = msg[1].get("exception_message", "")
                raise RuntimeError(
                    f"ComfyUI execution failed: {err_msg or 'unknown error'}")

            # Collect all output images/videos
            for nid, node_out in entry.get("outputs", {}).items():
                for img in node_out.get("images", []):
                    outputs.append((
                        img.get("filename", ""),
                        img.get("subfolder", ""),
                        img.get("type", "output"),
                    ))
                # Video outputs (VHS_VideoCombine → "gifs")
                for vid in node_out.get("gifs", []):
                    outputs.append((
                        vid.get("filename", ""),
                        vid.get("subfolder", ""),
                        vid.get("type", "output"),
                    ))

            if outputs or entry.get("outputs"):
                break  # got results (or empty output = successful no-output job)

        except RuntimeError:
            raise
        except Exception:
            pass
        time.sleep(0.5)

    elapsed = time.time() - t0

    if not outputs and time.time() >= deadline:
        raise RuntimeError(f"Timeout after {timeout}s waiting for ComfyUI")

    # ── 6. Privacy cleanup ────────────────────────────────────────
    if _should_cleanup(privacy) and outputs:
        _progress("cleanup", "wiping temp files...")
        try:
            from .privacy import cleanup_server_files
            cleanup_server_files(server, workflow=workflow, results=outputs)
        except ImportError:
            pass

    _progress("done", f"{len(outputs)} outputs in {elapsed:.1f}s")
    return DispatchResult(
        prompt_id=prompt_id,
        outputs=outputs,
        elapsed=elapsed,
        warnings=warnings,
    )