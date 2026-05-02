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
    """Standardized result from a ComfyUI workflow execution.

    ``outputs`` lists filename-based outputs (the historical poll-path
    return shape, used by every existing caller). ``binary_outputs`` is
    populated only on the websocket path when ``SaveImageWebsocket`` /
    ``ETN_SendImageWebSocket`` are present in the workflow -- those
    nodes return image bytes via a ws binary frame instead of writing
    to disk. Each entry is ``(format_name, image_bytes, label)`` where
    ``format_name`` is one of ``"png"``, ``"jpg"``, ``"jpeg"``,
    ``"webp"``, and ``label`` is the optional discriminator string
    set on the producing node via
    ``nf.save_image_websocket(..., label=...)``. ``label`` is ``None``
    when the builder did not set one (single-output builders); it is
    populated when a multi-output builder needs to disambiguate frames
    (e.g. ``"sam3_subject"`` vs ``"sam3_mask"``).

    ``transport`` records which path produced the result so callers
    can log + branch (download via /view for ``"poll"``, decode bytes
    in-memory for ``"websocket"``)."""
    prompt_id: str
    outputs: list       # [(filename, subfolder, folder_type), ...]
    elapsed: float      # seconds from submit to completion
    warnings: list      # preflight/optimizer messages
    binary_outputs: list = dataclasses.field(default_factory=list)
    transport: str = "poll"  # "poll" | "websocket"


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
                      on_progress=None, trusted=False,
                      use_websocket=False, ws_fallback_to_poll=True):
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
        use_websocket: **Phase 9 opt-in** (default False). When True,
                   replaces the ``/history/<prompt_id>`` poll loop with
                   a websocket subscription to ``/ws?clientId=<uuid>``.
                   Gains: no 500 ms poll race for short workflows, and
                   binary image frames from ``SaveImageWebsocket`` /
                   ``ETN_SendImageWebSocket`` arrive in-memory without
                   touching the filesystem. The result's
                   ``binary_outputs`` field carries the bytes; the
                   ``outputs`` field still carries any filename-based
                   outputs (mixed-mode workflows are supported).
        ws_fallback_to_poll: When ``use_websocket=True`` and the ws
                   connection fails (``websockets`` not installed,
                   ComfyUI version too old, network blip), fall back
                   to the historical poll path. Default True for
                   safety. Set False to make ws failures hard-error
                   (useful for tests / strict deployments).

    Returns:
        DispatchResult with prompt_id, outputs, elapsed, warnings,
        binary_outputs, transport.

    Raises:
        RuntimeError on critical failures (missing nodes, server offline).
    """
    # Trusted fast-path: every build_* produces a workflow whose
    # class_types and input shapes we own in the canonical factories,
    # so re-validating them per dispatch is pure latency. Skip ONLY
    # preflight (the /object_info-heavy step) — keep optimize ON
    # because it's cheap (one /system_stats call + arithmetic) and
    # it's what VRAM-caps the resolution. Without optimizer, an
    # oversized workflow on an under-provisioned GPU crawls in
    # memory-swap territory at 0.01 it/s, which user-side looks
    # indistinguishable from an indefinite hang (2026-04-24 hotfix
    # after user reported Klein inpaint "runs indefinitely").
    if trusted:
        preflight = False
        # optimize stays enabled — it's cheap and prevents OOM hangs.
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

    # ── 4. Submit + wait ─────────────────────────────────────────
    # Two transports, same shape on the way out:
    #   - ws (Phase 9): subscribe to /ws first, then POST /prompt
    #     with matching client_id, then collect ws messages until
    #     the canonical done signal. Binary frames carry image bytes
    #     when SaveImageWebsocket / ETN_SendImageWebSocket are in
    #     the workflow; filename outputs still fall through the
    #     'executed' message's output.images / output.gifs fields.
    #   - poll (historical default): POST /prompt, then loop
    #     /history/<prompt_id> every 500 ms until status_str==error
    #     or outputs appear.
    # The ws path falls back to poll on any WS error when
    # ws_fallback_to_poll=True (default). Both paths converge on
    # the same DispatchResult shape; only the `transport` field
    # records which one ran.
    if use_websocket:
        try:
            from .comfy_ws import (
                WSError, WSExecutionError, WSTimeout,
                _WS_FORMAT_NAMES,
                submit_and_listen,
            )
        except ImportError as exc:
            if not ws_fallback_to_poll:
                raise RuntimeError(
                    f"websocket transport requested but comfy_ws "
                    f"unavailable: {exc}")
            _progress("ws.fallback", f"comfy_ws import failed: {exc}")
            use_websocket = False  # fall through to poll path

    if use_websocket:
        _progress("ws.dispatch", "subscribing + submitting via /ws")
        t0 = time.time()
        try:
            ws_result = submit_and_listen(
                server, workflow, timeout=timeout,
                on_progress=on_progress,
            )
        except WSError as exc:
            if not ws_fallback_to_poll:
                raise RuntimeError(f"ws dispatch failed: {exc}")
            warnings.append(f"WS path failed, falling back to poll: {exc}")
            _progress("ws.fallback", str(exc))
            use_websocket = False  # fall through to poll path

    if use_websocket:
        # Done via ws path; build the DispatchResult and short-circuit.
        if ws_result.error_detail and not ws_result.file_outputs and not ws_result.binary_frames:
            raise RuntimeError(
                f"ComfyUI execution failed: {ws_result.error_detail}")
        if ws_result.error_detail and (ws_result.file_outputs or ws_result.binary_frames):
            warnings.append(
                f"ComfyUI reported execution_error but produced output -- "
                f"returning it as partial success. Detail: "
                f"{ws_result.error_detail}")
        if ws_result.interrupted:
            raise RuntimeError(
                f"ComfyUI execution interrupted for prompt "
                f"{ws_result.prompt_id}")

        # Map producing-node id -> label for any SaveImageWebsocket /
        # ETN_SendImageWebSocket node that was tagged via
        # nf.save_image_websocket(..., label="..."). The factory stores
        # the label under the node's ``_meta`` key (a ComfyUI-recognised
        # convention -- the server ignores ``_meta`` entries it doesn't
        # know about).
        _ws_save_classes = ("SaveImageWebsocket", "ETN_SendImageWebSocket")
        _node_labels = {}
        for _nid, _ndef in (workflow or {}).items():
            if not isinstance(_ndef, dict):
                continue
            if _ndef.get("class_type") not in _ws_save_classes:
                continue
            _meta = _ndef.get("_meta") or {}
            _lbl = _meta.get("label")
            if _lbl:
                _node_labels[str(_nid)] = str(_lbl)
        binary_outputs = [
            (
                _WS_FORMAT_NAMES.get(f.format, f"fmt{f.format}"),
                f.image_bytes,
                _node_labels.get(f.node_id) if f.node_id is not None else None,
            )
            for f in ws_result.binary_frames
        ]
        elapsed = ws_result.elapsed
        _progress(
            "done",
            f"{len(ws_result.file_outputs)} file + "
            f"{len(binary_outputs)} ws-binary outputs in {elapsed:.1f}s",
        )

        # Privacy cleanup is a no-op for the ws path's binary frames
        # (nothing landed on disk); but file outputs from non-ws nodes
        # in the same workflow do need the cleanup pass.
        if _should_cleanup(privacy) and ws_result.file_outputs:
            _progress("cleanup", "wiping temp files...")
            try:
                from .privacy import cleanup_server_files
                cleanup_server_files(
                    server, workflow=workflow,
                    results=ws_result.file_outputs,
                )
            except ImportError:
                pass

        return DispatchResult(
            prompt_id=ws_result.prompt_id,
            outputs=list(ws_result.file_outputs),
            elapsed=elapsed,
            warnings=warnings,
            binary_outputs=binary_outputs,
            transport="websocket",
        )

    # ── poll path (historical default) ────────────────────────────
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
        binary_outputs=[],
        transport="poll",
    )