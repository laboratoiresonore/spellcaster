"""LoRA bulk calibration engine — cross-arch verification + trigger extraction.

The legacy classifier (`tavern/server.py::_llm_worker`) decides a LoRA's
architecture from filename heuristics and an LLM guess — it never actually
runs the LoRA against a model, so Wan video LoRAs get shelved under SDXL
wizards and the user sees an `auto:txt2img` tag on a clip that will never
produce a still.

This module fixes that. For each LoRA:

  1. Pull trigger words from the safetensors header (`ss_tag_frequency`,
     `ss_output_name`, `modelspec.trigger_phrase`) — these land in the
     file's metadata at training time.
  2. Iterate across every architecture the user has at least one installed
     model for. Run `_build_test_workflow` + dispatch. The first arch that
     returns a valid image wins; any that errors with an obvious shape /
     dim / dtype mismatch is discarded.
  3. If no arch works, mark the LoRA `no_dice` — the Spellcaster will
     ask the user whether to keep it hidden or force-assign it anyway.

Results are a list of `LoraCalibrationResult` dataclasses, which the Guild
hands to the scaffold for "the user reviews" — the user validates /
invalidates / completes the trigger words, and their approvals merge into
the shared `_LORA_REGISTRY` so every surface picks up the truth.

Designed to be called either synchronously (for small sets, one wizard's
worth of LoRAs) or via a background thread (the whole library of 63+ LoRAs
× 7 archs takes minutes).
"""
from __future__ import annotations

import io
import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


# ── Safetensors metadata reader ──────────────────────────────────────────

def read_safetensors_metadata(path: str) -> dict:
    """Extract the `__metadata__` JSON from a safetensors file.

    Safetensors stores an 8-byte little-endian header length, then that many
    bytes of JSON containing both tensor offsets and a `__metadata__` key
    with free-form string:string pairs. We only read the first few KB.

    Returns {} if the file is missing, unreadable, or not safetensors.
    """
    try:
        with open(path, "rb") as f:
            raw_len = f.read(8)
            if len(raw_len) != 8:
                return {}
            header_len = struct.unpack("<Q", raw_len)[0]
            if header_len <= 0 or header_len > 64 * 1024 * 1024:
                # 64 MB sanity cap — headers are normally a few KB.
                return {}
            header_bytes = f.read(header_len)
        header = json.loads(header_bytes.decode("utf-8", errors="replace"))
        meta = header.get("__metadata__") or {}
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


_METADATA_TRIGGER_FIELDS = (
    # Field names set by different trainers / civitai conventions.
    "ss_output_name",
    "ss_network_trigger",
    "ss_trigger_word",
    "modelspec.trigger_phrase",
    "trigger_phrase",
    "activation",
    "activation_text",
    "invocation",
)


def extract_trigger_words(lora_path: str, filename_fallback: bool = True) -> tuple[list[str], str]:
    """Best-effort trigger-word extraction for a LoRA.

    Strategy:
      1. Read safetensors `__metadata__`. Scan for the known trigger fields;
         if present, parse (comma / pipe / space-separated).
      2. `ss_tag_frequency` is a training-time JSON map of tag → count.
         Take the top-N by count as likely triggers.
      3. If nothing useful and `filename_fallback=True`, derive candidate
         triggers from the filename (split on `_`, `-`, drop version tokens).

    Returns (trigger_words, source) where source is "metadata" | "tag_freq" |
    "filename" | "none". The caller is expected to ask the user to confirm
    — these are guesses.
    """
    meta = read_safetensors_metadata(lora_path) if lora_path else {}
    triggers: list[str] = []

    # 1. Named trigger fields
    for field_name in _METADATA_TRIGGER_FIELDS:
        val = meta.get(field_name)
        if not val or not isinstance(val, str):
            continue
        parts = re.split(r"[,|;]+", val)
        for p in parts:
            p = p.strip()
            if p and p not in triggers and len(p) <= 64:
                triggers.append(p)
    if triggers:
        return triggers, "metadata"

    # 2. ss_tag_frequency — {dataset_name: {tag: count}}
    raw_freq = meta.get("ss_tag_frequency")
    if raw_freq:
        try:
            freq = json.loads(raw_freq) if isinstance(raw_freq, str) else raw_freq
            # Flatten across datasets, then sort by count desc.
            flat: dict[str, int] = {}
            if isinstance(freq, dict):
                for dataset_tags in freq.values():
                    if isinstance(dataset_tags, dict):
                        for tag, count in dataset_tags.items():
                            try:
                                flat[tag] = flat.get(tag, 0) + int(count)
                            except (TypeError, ValueError):
                                pass
            top = sorted(flat.items(), key=lambda kv: kv[1], reverse=True)[:5]
            triggers = [t for t, _c in top if t and len(t) <= 64]
            if triggers:
                return triggers, "tag_freq"
        except Exception:
            pass

    # 3. Filename-based candidates (last resort)
    if filename_fallback and lora_path:
        stem = os.path.splitext(os.path.basename(lora_path))[0]
        # Drop common version / arch tokens so the LLM later sees a clean hint
        junk = {"v1", "v2", "v3", "v1a", "v1b", "v10", "v20", "xl", "sdxl",
                "sd15", "sd1", "pony", "flux", "klein", "illu", "illustrious",
                "final", "beta", "alpha", "rank4", "rank8", "rank16",
                "epoch", "lora", "loha", "lokr"}
        parts = [p for p in re.split(r"[-_\s.]+", stem)
                 if p and p.lower() not in junk and not p.isdigit()]
        if parts:
            return [" ".join(parts[:3])], "filename"

    return [], "none"


# ── Result model ─────────────────────────────────────────────────────────

@dataclass
class LoraCalibrationResult:
    """One LoRA's full calibration outcome.

    The Spellcaster wizard presents this to the user in the "review" step.
    Fields the user may edit: trigger_words, verified_archs (via
    validate/invalidate), notes. Everything else is derived and shouldn't
    need manual correction.
    """
    lora_name: str
    trigger_words: list[str] = field(default_factory=list)
    trigger_source: str = "none"           # metadata | tag_freq | filename | none
    # Per-arch verification outcome. Only archs the server has a model for
    # are included.
    arch_outcomes: dict[str, str] = field(default_factory=dict)
    verified_archs: list[str] = field(default_factory=list)
    suggested_strength: Optional[float] = None
    status: str = "pending"                # pending | ok | no_dice | error
    notes: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Cross-arch verification ──────────────────────────────────────────────

def _pick_representative_model(models: list[dict], arch: str) -> Optional[dict]:
    """Given `discover_models()` output, return one model for the given arch.

    Preference: the smallest model (fastest test). Fallback: any.
    """
    candidates = [m for m in models if m.get("arch") == arch]
    if not candidates:
        return None
    # Fastest-first: sorted alphabetically as a rough proxy (no size
    # information in the discover_models dict). Good enough — test is small.
    return sorted(candidates, key=lambda m: str(m.get("name", "")))[0]


def verify_lora_against_model(
    server: str,
    model: dict,
    lora_name: str,
    strength: float = 0.5,
    timeout: int = 45,
) -> tuple[bool, str, int]:
    """Run the smallest possible test workflow with `lora_name` loaded.

    Returns (ok, error_message, elapsed_ms).

    Builds the 64x64 2-step workflow from spellcaster_core.calibration and
    dispatches it via the same `_submit_and_wait` helper; any ComfyUI error
    bubbles back as the error_message. A successful generation — even if
    the output is ugly — means the LoRA is structurally compatible with
    the model's architecture.
    """
    t0 = time.time()
    try:
        try:
            from spellcaster_core.calibration import (
                _build_test_workflow, _submit_and_wait,
            )
        except ImportError:
            from calibration import _build_test_workflow, _submit_and_wait  # type: ignore

        wf = _build_test_workflow(
            model.get("name", ""), model.get("arch", ""),
            lora=lora_name, lora_strength=strength,
        )
        if wf is None:
            return (False, "could not build test workflow", 0)

        ok, _elapsed, msg = _submit_and_wait(server, wf, timeout=timeout)
        return (ok, msg if not ok else "",
                int((time.time() - t0) * 1000))
    except Exception as e:
        return (False, f"dispatch error: {e!s}"[:200],
                int((time.time() - t0) * 1000))


def calibrate_one_lora(
    server: str,
    lora_name: str,
    models: list[dict],
    comfy_models_root: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
) -> LoraCalibrationResult:
    """Run one LoRA through every installed architecture until one passes.

    Args:
        server:            ComfyUI URL (e.g. http://localhost:8188).
        lora_name:         filename as it appears in ComfyUI's lora dropdown
                           (including any subfolder prefix).
        models:            `discover_models(server)` output. Must include an
                           `arch` key per model.
        comfy_models_root: optional filesystem path to ComfyUI's models/ dir.
                           If set, trigger-word extraction opens the LoRA
                           from disk. If None, we fall back to
                           filename-based triggers only (no safetensors peek).
        log:               optional progress callback, called with short
                           status strings.

    Returns a `LoraCalibrationResult`.
    """
    t0 = time.time()
    result = LoraCalibrationResult(lora_name=lora_name)

    # 1. Trigger extraction
    lora_path = ""
    if comfy_models_root:
        lora_path = os.path.join(comfy_models_root, "loras", lora_name)
    triggers, source = extract_trigger_words(lora_path)
    result.trigger_words = triggers
    result.trigger_source = source

    # 2. Cross-arch trial
    archs_with_models = []
    seen_archs: set[str] = set()
    for m in models:
        a = m.get("arch", "")
        if not a or a == "unknown" or a in seen_archs:
            continue
        seen_archs.add(a)
        archs_with_models.append(a)

    if not archs_with_models:
        result.status = "error"
        result.notes = "no installed models to test against"
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    if log:
        log(f"  [{lora_name}] trying {len(archs_with_models)} arch(s): "
            f"{', '.join(archs_with_models)}")

    verified: list[str] = []
    for arch in archs_with_models:
        model = _pick_representative_model(models, arch)
        if not model:
            result.arch_outcomes[arch] = "skip: no model"
            continue
        if log:
            log(f"    [{lora_name}] testing on {arch} ({model.get('name')})…")
        ok, err, _ms = verify_lora_against_model(server, model, lora_name)
        if ok:
            result.arch_outcomes[arch] = "pass"
            verified.append(arch)
            # Keep testing — a LoRA can legitimately be cross-arch (rare but
            # happens with pony/sdxl variants). Comment out `break` to
            # always try every arch; uncomment to short-circuit on first
            # success for speed.
            # break
        else:
            # Truncate error to keep the registry readable.
            short = (err or "").strip()[:140]
            result.arch_outcomes[arch] = f"error: {short}"

    result.verified_archs = verified
    if verified:
        result.status = "ok"
        result.suggested_strength = 0.5
    else:
        result.status = "no_dice"
        result.notes = ("No installed model accepted this LoRA. Either it "
                        "is for an architecture you haven't installed, or "
                        "the file is corrupt.")

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result


# ── Bulk flow (with threaded job runner) ─────────────────────────────────

@dataclass
class BulkJobState:
    """In-memory state for a running bulk calibration job."""
    job_id: str
    total: int
    done: int = 0
    current: str = ""
    results: list[LoraCalibrationResult] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    status: str = "running"          # running | complete | error | cancelled
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: str = ""

    def to_public_dict(self) -> dict:
        """Public snapshot — excludes internal threading bits."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "current": self.current,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": int((self.finished_at or time.time()) - self.started_at),
            "log_tail": self.log[-20:],
            "error": self.error,
        }


# Global job registry. Guild holds a reference so the HTTP handler can
# poll status / fetch results by job_id.
_BULK_JOBS: dict[str, BulkJobState] = {}
_BULK_JOBS_LOCK = threading.Lock()


def start_bulk_job(
    server: str,
    lora_names: list[str],
    models: list[dict],
    comfy_models_root: Optional[str] = None,
) -> BulkJobState:
    """Launch a background thread that calibrates `lora_names` and exposes
    progress via the module-global `_BULK_JOBS` dict.

    Returns the BulkJobState immediately. Caller polls via `get_job_state`.
    """
    job_id = f"lcal_{uuid.uuid4().hex[:12]}"
    state = BulkJobState(job_id=job_id, total=len(lora_names))
    with _BULK_JOBS_LOCK:
        _BULK_JOBS[job_id] = state

    def _worker():
        try:
            for name in lora_names:
                state.current = name
                state.log.append(f"▶ {name}")

                def _log(msg: str):
                    state.log.append(msg)
                    if len(state.log) > 500:
                        # Keep memory bounded; older entries drop off.
                        del state.log[:100]

                try:
                    res = calibrate_one_lora(
                        server, name, models,
                        comfy_models_root=comfy_models_root,
                        log=_log,
                    )
                except Exception as e:
                    res = LoraCalibrationResult(
                        lora_name=name,
                        status="error",
                        notes=f"worker crashed: {e!s}"[:200],
                    )
                state.results.append(res)
                state.done += 1
                state.log.append(
                    f"  → {res.status}"
                    + (f" (archs: {', '.join(res.verified_archs)})"
                       if res.verified_archs else "")
                )
            state.status = "complete"
        except Exception as e:
            state.status = "error"
            state.error = f"{e!s}"[:400]
        finally:
            state.finished_at = time.time()

    t = threading.Thread(target=_worker, daemon=True,
                         name=f"lora-calibrate-{job_id}")
    t.start()
    return state


def get_job_state(job_id: str) -> Optional[BulkJobState]:
    with _BULK_JOBS_LOCK:
        return _BULK_JOBS.get(job_id)


def list_jobs() -> list[BulkJobState]:
    with _BULK_JOBS_LOCK:
        return list(_BULK_JOBS.values())


def clear_finished_jobs(older_than_s: int = 3600) -> int:
    """Drop job records that finished more than `older_than_s` ago."""
    cutoff = time.time() - older_than_s
    removed = 0
    with _BULK_JOBS_LOCK:
        for jid in list(_BULK_JOBS):
            js = _BULK_JOBS[jid]
            if js.status != "running" and (js.finished_at or 0) < cutoff:
                del _BULK_JOBS[jid]
                removed += 1
    return removed


__all__ = [
    "read_safetensors_metadata",
    "extract_trigger_words",
    "LoraCalibrationResult",
    "verify_lora_against_model",
    "calibrate_one_lora",
    "BulkJobState",
    "start_bulk_job",
    "get_job_state",
    "list_jobs",
    "clear_finished_jobs",
]
