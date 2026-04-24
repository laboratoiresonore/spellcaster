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
    from .dispatch import dispatch_workflow

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
#  Error extraction — robust against every ComfyUI status_str=error shape
# ═══════════════════════════════════════════════════════════════════════
#
# ComfyUI does not guarantee that status_str=='error' always comes paired
# with an 'execution_error' message whose 'exception_message' field is
# populated. Different node types, interrupt paths, and ComfyUI versions
# emit differently-shaped messages. The former extractors here only read
# msgs[-1][1]['exception_message'] or scanned for the single type
# 'execution_error' — missing everything else and producing the dreaded
# "unknown error" / "Unknown error" / "(no details available)" fallback
# that the user saw for a failed Inpaint dispatch. Worse, callers raised
# even when entry['outputs'] was non-empty, discarding a perfectly good
# saved result. Single canonical helper now lives here and is imported
# by every surface that inspects a history entry.

def extract_execution_error(status):
    """Extract the best error string from a history-entry 'status' dict.

    Walks every message type looking for known error fields, falls back
    to a structured raw-status dump so the next debugger at least has
    something to work with (instead of 'unknown error').

    Args:
        status: The dict at ``history[prompt_id]['status']``. May be
                None or non-dict — we tolerate both.

    Returns:
        (detail, recognised): ``detail`` is always a non-empty string
        capped at ~600 chars; ``recognised`` is True when at least one
        message had a known error field, False when we fell back to the
        raw-status dump.
    """
    if not isinstance(status, dict):
        return (f"malformed status: {type(status).__name__}", False)
    msgs = status.get("messages") or []
    collected_text = []       # ordered list of (priority, text, ctx)
    error_types = set()
    node_ctx = None
    ERROR_FIELDS = (
        ("exception_message", 0),
        ("message",           1),
        ("error",             2),
        ("details",           3),
        ("reason",            4),
        ("traceback",         5),
    )
    ERROR_MSG_TYPES = {
        "execution_error", "execution_failure",
        "execution_interrupted", "error",
    }
    for m in msgs:
        if not (isinstance(m, (list, tuple)) and len(m) >= 2):
            continue
        msg_type, msg_data = m[0], m[1]
        if not isinstance(msg_data, dict):
            continue
        for field, pri in ERROR_FIELDS:
            val = msg_data.get(field)
            if not val:
                continue
            if isinstance(val, (list, tuple)):
                val = "\n".join(str(x) for x in val)
            text = str(val).strip()
            if not text:
                continue
            # First-match-wins per priority within the message, but
            # keep every message's top pick so multi-node failures
            # surface more than just the first line.
            collected_text.append((pri, msg_type, text))
            break
        exc_type = msg_data.get("exception_type")
        if isinstance(exc_type, str) and exc_type:
            error_types.add(exc_type)
        if msg_type in ERROR_MSG_TYPES and node_ctx is None:
            nt = msg_data.get("node_type")
            nid = msg_data.get("node_id")
            if nt:
                node_ctx = f"[{nt}]"
            elif nid:
                node_ctx = f"[node {nid}]"
    if collected_text:
        collected_text.sort(key=lambda t: t[0])
        parts = []
        if node_ctx:
            parts.append(node_ctx)
        if error_types:
            parts.append(sorted(error_types)[0] + ":")
        # Keep the top text per priority bucket, cap total length.
        seen = set()
        for _, _, txt in collected_text:
            if txt in seen:
                continue
            seen.add(txt)
            parts.append(txt)
            if sum(len(p) for p in parts) > 500:
                break
        detail = " ".join(parts)
        return (detail[:600], True)
    # Fallback: structured dump of what we DID see so next time we know
    # what shape to decode.
    try:
        types_seen = [m[0] for m in msgs
                       if isinstance(m, (list, tuple)) and m][:10]
    except Exception:
        types_seen = []
    raw = json.dumps({
        "status_str": status.get("status_str"),
        "completed":  status.get("completed"),
        "message_count": len(msgs),
        "message_types": types_seen,
    }, default=str)[:400]
    return (f"no recognised error message; status={raw}", False)


def has_usable_outputs(entry):
    """Return True if a history entry has any downloadable outputs.

    Used to distinguish "partial success" (a side node raised but the
    main Save*Image node still emitted a file) from a total failure.
    """
    outputs = (entry or {}).get("outputs") or {}
    if not isinstance(outputs, dict):
        return False
    for _, node_out in outputs.items():
        if not isinstance(node_out, dict):
            continue
        for key in ("images", "gifs", "videos"):
            for item in node_out.get(key, []) or []:
                if isinstance(item, dict) and item.get("filename"):
                    return True
    return False


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
                      on_progress=None, trusted=False):
    """Submit a workflow to ComfyUI with full lifecycle management.

    Args:
        server: ComfyUI server URL (e.g. "http://192.168.x.x:8188")
        workflow: ComfyUI workflow dict (node graph)
        timeout: Max seconds to wait for completion
        free_vram: If True, call /free to evict cached models before submit.
                   Use for heavy generation (img2img, txt2img, video).
                   Skip for lightweight jobs (64x64 calibration tests).
        preflight: Run node validation and automatic fallbacks. **NOTE**:
                   on a fresh plugin/process this triggers a /object_info
                   fetch which on servers with many custom-node packs
                   can be 25+ MB / 4–9 s. The cache is per-process, so
                   subsequent dispatches within the same session are free
                   — but the first one pays the full cost. Skip entirely
                   by passing ``trusted=True`` when the workflow was
                   produced by our own ``build_*`` functions (known-valid
                   JSON by construction).
        optimize: Run VRAM capping and auto-tuning. Same caveat: relies
                   on the same /object_info cache. Skip with
                   ``trusted=True``.
        privacy: True/False to override, None to read from env/config.
                 When enabled, wipes all temp files from ComfyUI after
                 results are downloaded.
        on_progress: Optional callback(stage: str, detail: str) for progress.
                     Stages: "preflight", "optimize", "free", "submit",
                     "poll", "cleanup", "done".
        trusted: **Fast-path opt-in** (default False for back-compat).
                   Set True when the workflow is produced by one of our
                   ``spellcaster_core.workflows.build_*`` functions —
                   those generate known-valid JSON so preflight +
                   validator + optimize are redundant, and skipping
                   them saves the 4–9 s ``/object_info`` fetch on a
                   cold cache. Overrides ``preflight`` and ``optimize``
                   when True (both become no-ops). External workflows
                   (user-pasted JSON, third-party saved files) should
                   stay ``trusted=False`` so the validator catches
                   version-skew and missing-node issues up front.

    Returns:
        DispatchResult with prompt_id, outputs, elapsed, warnings.

    Raises:
        RuntimeError on critical failures (missing nodes, server offline).
    """
    # Trusted fast-path: every build_* produces a workflow whose
    # class_types and input shapes we own in the canonical factories,
    # so re-validating them per dispatch is pure latency. Flip BOTH
    # flags off in one go rather than making every caller remember to
    # set preflight=False AND optimize=False.
    if trusted:
        preflight = False
        optimize = False
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
        # Step 1b: validate the model-file references (ckpt / LoRA /
        # ControlNet / upscaler / VAE / CLIP / UNET). Turns the cryptic
        # "Value not in list for CheckpointLoaderSimple.ckpt_name" that
        # ComfyUI raises mid-submit into an actionable list of missing
        # files. See preflight.validate_workflow_files.
        #
        # CRITICAL SAFETY (2026-04-20 hotfix): any NON-ImportError raised
        # by the validator (stale cache, server timeout during the extra
        # /object_info fetch, weird workflow shape, etc.) was previously
        # uncaught → propagated to the handler's outer except → silently
        # surfaced as "Spellcaster <tool> Error: …" dialog with no
        # workflow submission. Triple-layer catch now: ImportError →
        # preflight module missing (ok, skip); RuntimeError from the
        # missing-files branch → propagate with the install hint;
        # ANYTHING ELSE → log the traceback and proceed with submit.
        # This mirrors the first preflight_workflow's fail-open shape.
        try:
            from .preflight import (
                validate_workflow_files, format_missing_files_hint)
            try:
                files_ok, files_report = validate_workflow_files(
                    workflow, server)
                if not files_ok:
                    hint = format_missing_files_hint(
                        files_report["missing_files"])
                    raise RuntimeError(
                        "Some model files referenced by this workflow "
                        "are not installed on your ComfyUI server.\n\n"
                        f"{hint}\n\n"
                        "Install the missing files (or point the "
                        "preset at files you already have) and try "
                        "again.")
            except RuntimeError:
                raise  # deliberate — propagate the actionable message
            except Exception as _validator_err:
                import traceback as _tb
                print(f"[Preflight] file validator crashed; submitting "
                      f"anyway: {_validator_err}")
                _tb.print_exc()
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

            # Check for execution error. Use the robust extractor +
            # preserve usable outputs when ComfyUI set status_str=error
            # BUT the main SaveImage still emitted a file (common when
            # a side node raised). Raising + discarding the output is
            # the bug that showed up as "comfyui made it but it never
            # returned to gimp".
            if status.get("status_str") == "error":
                err_detail, recognised = extract_execution_error(status)
                if has_usable_outputs(entry):
                    warnings.append(
                        f"ComfyUI reported status=error but produced "
                        f"output — returning it as partial success. "
                        f"Detail: {err_detail}")
                    # Fall through to output collection below.
                else:
                    raise RuntimeError(
                        f"ComfyUI execution failed: {err_detail}")

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