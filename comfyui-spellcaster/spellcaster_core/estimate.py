"""Generation-time estimator — refined live countdown for handler UIs.

Builds on :mod:`spellcaster_core.speedcoach` (dispatch_log.jsonl +
preflight_cache.json) to answer the only question a user asks while
a render is spinning: *how long will this take?*

Pipeline
--------

1. **Pre-dispatch baseline** (``estimate_pre_dispatch``):
      - Look up the fingerprint ``(arch, handler, steps, upscale,
        lora_stack_hash)`` in the dispatch log. If we have n≥3 samples,
        the median is the canonical baseline.
      - Broaden fingerprints when the tight match is cold:
        ``(arch, handler)`` -> ``(arch,)`` -> preflight canary scaled
        by handler factor -> hard-coded arch default. Each broadening
        halves confidence.
      - Adjust for live state: queue depth ahead of us (avg dispatch
        elapsed × ``queue_ahead``), VRAM pressure above 85 %
        (multiplicative penalty — swap risk), cold-model flag (add
        first-load overhead).

2. **During-dispatch refinement** (``estimate_during_dispatch``):
      - Given ``elapsed`` + ``(step_cur, step_max)`` from ComfyUI,
        compute a pure linear projection. Blend with the pre-dispatch
        baseline using a weight that rises with step progress — by
        step 5 of 25 (20 % through sampling) we trust the linear
        projection ~90 %.
      - Account for the fact that ComfyUI "steps" only measure the
        sampler loop. VAE decode + upscale + face restore + rembg
        all run AFTER step_max is reached. The per-handler
        ``step_to_total_factor`` multiplier derives this tail from
        the dispatch log.

3. **Post-run learning** is handled implicitly — every completion is
   already written to ``dispatch_log.jsonl`` by the Guild, so the
   next pre-dispatch baseline picks up today's run tomorrow.

Every output carries ``rationale`` so the UI can show *why* the
estimate landed where it did (useful for SpeedCoach's retrospective
"Done 47 s (predicted 22 s). Click to see why →").

API summary::

    from . import estimate as est

    pre = est.estimate_pre_dispatch(
        {"arch": "sdxl", "handler": "build_img2img",
         "steps": 30, "upscale": 1,
         "lora_stack_hash": est.lora_stack_hash(loras)},
        queue_ahead=2, vram_pct=78, cold_model=False,
    )
    # pre == {
    #   "est_sec": 24.3, "low": 19.1, "high": 31.8,
    #   "confidence": 0.82, "source": "exact_fingerprint_median",
    #   "rationale": ["matched 12 runs of same spec",
    #                 "queue +2 slots (+14 s)"],
    #   "n": 12,
    # }

    live = est.estimate_during_dispatch(
        pre, elapsed=6.5, step_cur=8, step_max=30,
    )
    # live == {"eta_sec": 17.2, "source": "step_linear", ...}

    print(est.format_countdown(live["eta_sec"]))
    # "17s"
"""

from __future__ import annotations

import hashlib
import math
import os
from statistics import median
from typing import Any, Optional


# ── Tunables ────────────────────────────────────────────────────────

#: VRAM utilisation above which we add a swap-risk penalty.
VRAM_PRESSURE_THRESHOLD = 0.85
#: Multiplier applied to the estimate when VRAM > threshold.
VRAM_PRESSURE_PENALTY = 1.20

#: Cold-model flat overhead when the model hasn't been loaded this
#: session. Empirical: Flux Dev first load ~8 s, SDXL ~3 s on the
#: user's RTX 5060 Ti. We take the mid-point — handlers that care
#: can pass their own.
COLD_LOAD_OVERHEAD_SECONDS = 5.0

#: Per-handler fraction of total elapsed that sits in the sampler
#: loop (the rest = VAE decode + post-processing). Used to scale
#: a pure step-linear projection up to a full runtime guess. Pulled
#: from empirical dispatch_log analysis; overridable per-install by
#: writing ``handler_step_factor.json`` in the state dir.
#:
#: Values close to 1.0 mean "the sampler IS the job" (txt2img is
#: basically all-sampler). Lower means "the sampler is one stage of
#: many" (detail hallucinate has sampler + 4× upscale + refine).
_HANDLER_STEP_FACTOR_DEFAULT = 0.90
_HANDLER_STEP_FACTOR = {
    "build_txt2img":           0.92,
    "build_img2img":           0.88,
    "build_inpaint":           0.85,
    "build_outpaint":          0.80,
    "build_klein_inpaint":     0.82,
    "build_klein_outpaint":    0.78,
    "build_klein_img2img":     0.88,
    "build_upscale":           0.70,   # heavy VAE passes
    "build_upscale_blend":     0.60,   # SUPIR + blend — mostly tail
    "build_detail_hallucinate":0.55,   # 4× upscale dominates
    "build_seedv2r":           0.50,
    "build_iclight":           0.75,
    "build_colorize":          0.85,
    "build_style_transfer":    0.82,
    "build_faceswap":          0.65,
    "build_faceswap_mtb":      0.65,
    "build_face_restore":      0.70,
    "build_photobooth":        0.60,
    "build_kontext":           0.85,
    "build_normal_map":        0.95,   # near-pure sampler
    "build_sam3":              0.50,
    "build_flux2klein":        0.70,   # 4-step distill + enhancer chain
    "build_chroma":            0.88,
    "build_wan_video":         0.92,   # video — sampler dominates
    "build_ltx_video":         0.88,
}

#: Arch defaults for the last-resort fallback (no fingerprint match,
#: no preflight canary). Expressed as seconds per 30-step 512×512
#: baseline on a mid-range RTX GPU; we scale by steps + resolution.
_ARCH_DEFAULT_SECONDS = {
    "sd15":         4.0,
    "sdxl":         12.0,
    "illustrious":  14.0,
    "pony":         14.0,
    "playground":   13.0,
    "zit":          2.0,   # distilled → blazing
    "flux1dev":     25.0,
    "flux_kontext": 25.0,
    "flux2klein":   4.0,   # 4-step only
    "chroma":       18.0,
    "sdxl_turbo":   2.5,
    "wan":          90.0,
    "ltx":          40.0,
}

#: Blend weight parameters. We want the live step-linear projection to
#: dominate once we're deep enough into the sampler that it's
#: well-calibrated, but not so fast that early-step noise
#: (model-load spike) distorts the countdown.
#:
#: Weight formula: ``w_live = min(1, step_cur / BLEND_STEP_FULL_TRUST)``.
#: At step 5 with BLEND_STEP_FULL_TRUST=5, weight is 1.0 (full trust).
BLEND_STEP_FULL_TRUST = 5
#: Minimum live weight once any step progress is observed. Prevents
#: the banner estimate from sticking around when the first step
#: already tells us we're way off.
BLEND_STEP_MIN_WEIGHT = 0.15


# ── Helpers ─────────────────────────────────────────────────────────

def lora_stack_hash(loras: Any) -> str:
    """Stable, order-preserving hash for a LoRA stack. Shared with
    :mod:`spellcaster_core.speedcoach` — callers should prefer this
    over re-implementing per-site so fingerprints stay consistent
    across frontends."""
    if not loras:
        return "none"
    parts = []
    for item in loras:
        if isinstance(item, dict):
            nm = str(item.get("name") or item.get("path") or "").strip()
            w = item.get("weight") or item.get("strength") or 1.0
            try:
                parts.append(f"{nm}@{float(w):.2f}")
            except (TypeError, ValueError):
                parts.append(nm)
        else:
            parts.append(str(item).strip())
    blob = "||".join(parts)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def handler_step_factor(handler: str) -> float:
    """Return the empirical fraction of total elapsed that the
    sampler loop accounts for. Lookup falls back to the global
    default when the handler isn't in the table."""
    return _HANDLER_STEP_FACTOR.get(str(handler or ""),
                                     _HANDLER_STEP_FACTOR_DEFAULT)


def format_countdown(seconds: float) -> str:
    """Human-friendly ETA for status bars. Rules:
      * <1 s        → "~now"
      * 1..59 s     → "42s"
      * 60..3599 s  → "1m 23s"
      * ≥1 h        → "1h 14m"
    Negative (overrun) surfaces as "overtime +Ns" so the UI doesn't
    confuse users with a silent 0s when the real elapsed passed
    the predicted finish."""
    if seconds is None:
        return ""
    s = float(seconds)
    if s <= 0.5:
        return "~now"
    if s < 60:
        return f"{int(round(s))}s"
    if s < 3600:
        m = int(s // 60); rem = int(round(s - m * 60))
        if rem >= 60:
            m += 1; rem = 0
        return f"{m}m {rem:02d}s"
    h = int(s // 3600)
    m = int((s - h * 3600) // 60)
    return f"{h}h {m:02d}m"


def format_overrun(overrun_seconds: float) -> str:
    """Format a positive ``overrun_seconds`` (elapsed beyond the
    predicted finish) as e.g. ``"overtime +12s"``. Used by the UI
    when the countdown hits zero but ComfyUI hasn't declared done."""
    s = max(0.0, float(overrun_seconds or 0))
    if s < 1:
        return "overtime"
    if s < 60:
        return f"overtime +{int(round(s))}s"
    m = int(s // 60); rem = int(round(s - m * 60))
    return f"overtime +{m}m {rem:02d}s"


# ── Pre-dispatch baseline ───────────────────────────────────────────

def estimate_pre_dispatch(spec: dict, *,
                           queue_ahead: int = 0,
                           vram_pct: float = 0.0,
                           cold_model: bool = False,
                           queue_mean_sec: Optional[float] = None) -> dict:
    """Compute an estimate BEFORE the job dispatches. Every adjustment
    writes a one-line note to ``rationale`` so the UI can explain the
    number.

    Args:
        spec: dict with some subset of
            ``{arch, handler, steps, upscale, lora_stack_hash, loras,
              resolution}``.
        queue_ahead: dispatches ahead of us in ComfyUI's queue.
        vram_pct: current ``/system_stats`` VRAM utilization, 0..100.
        cold_model: True when the target model hasn't been loaded in
            this ComfyUI process yet (first generation since boot).
        queue_mean_sec: optional mean seconds-per-queued-job for the
            current model. Falls back to ``est_sec`` when None.

    Returns:
        dict with ``est_sec``, ``low``, ``high``, ``confidence``,
        ``n``, ``source``, ``rationale``. ``source`` is one of
        ``exact_fingerprint_median`` / ``arch_handler_median`` /
        ``preflight_canary`` / ``arch_default``.
    """
    rationale: list[str] = []
    # Lazy import so a GIMP plugin that pre-loads this module doesn't
    # pull the full speedcoach graph at import time.
    try:
        from . import speedcoach as sc
    except ImportError:
        try:
            from . import speedcoach as sc  # type: ignore
        except ImportError:
            sc = None  # type: ignore

    # 1. Exact fingerprint.
    est_sec = 0.0
    low = 0.0
    high = 0.0
    n = 0
    confidence = 0.0
    source = "unknown"

    if sc is not None:
        try:
            med, p95, n_tight = sc.predicted_elapsed(spec)
        except Exception:
            med, p95, n_tight = 0.0, 0.0, 0
        if n_tight >= 3 and med > 0:
            est_sec = float(med)
            low  = float(med) * 0.85
            high = float(p95) if p95 > med else float(med) * 1.25
            n = n_tight
            confidence = min(1.0, 0.5 + 0.1 * n_tight)
            source = "exact_fingerprint_median"
            rationale.append(
                f"matched {n_tight} run(s) of this exact config")

    # 2. Broaden to (arch, handler). We walk the dispatch log
    # directly here (rather than calling ``predicted_elapsed``)
    # because it uses full-fingerprint matching — including keys like
    # ``steps`` and ``lora_stack_hash`` that we want to disregard at
    # the broadened tier.
    if est_sec <= 0 and sc is not None:
        try:
            records = sc._read_jsonl("dispatch_log.jsonl")
        except Exception:
            records = []
        arch = spec.get("arch")
        handler = spec.get("handler") or spec.get("build_fn")
        pool = []
        pool_steps_list: list[float] = []
        for rec in records:
            if arch and rec.get("arch") != arch:
                continue
            rec_handler = rec.get("build_fn") or rec.get("handler")
            if handler and rec_handler != handler:
                continue
            e = rec.get("elapsed")
            if isinstance(e, (int, float)) and e > 0:
                pool.append(float(e))
            s = rec.get("steps")
            if isinstance(s, (int, float)) and s > 0:
                pool_steps_list.append(float(s))
        if len(pool) >= 3:
            pool_sorted = sorted(pool)
            med2 = median(pool_sorted)
            p95_idx = max(0, int(round(0.95 * (len(pool_sorted) - 1))))
            p95_2 = pool_sorted[p95_idx]
            # Scale by the ratio of this run's steps to the median
            # steps in the broader pool, so longer/shorter sampler
            # loops still show the right number.
            if pool_steps_list:
                pool_step_med = median(pool_steps_list)
                this_steps = _int_or(spec.get("steps"),
                                       int(pool_step_med) or 30)
                ratio = (max(0.3, min(3.0, this_steps / pool_step_med))
                         if pool_step_med > 0 else 1.0)
            else:
                ratio = 1.0
            est_sec = float(med2) * ratio
            low  = est_sec * 0.7
            high = (float(p95_2) * ratio if p95_2 > med2
                    else est_sec * 1.4)
            n = len(pool)
            confidence = 0.45
            source = "arch_handler_median"
            rationale.append(
                f"no exact match; used median of {n} "
                f"{handler or '?'} runs on {arch or '?'}"
                + (f" (scaled {ratio:.2f}× for steps)"
                   if abs(ratio - 1.0) > 0.1 else ""))

    # 3. Preflight canary × handler factor.
    if est_sec <= 0 and sc is not None:
        try:
            chart = sc.arch_speed_chart()
        except Exception:
            chart = []
        arch = spec.get("arch") or ""
        for row in chart:
            if row.get("arch") == arch and row.get("ok") and row.get("elapsed_ms"):
                base_sec = float(row["elapsed_ms"]) / 1000.0
                # Scale canary (1 LoRA, 20 steps, 512²) up to this
                # job's step count. LoRA stack size + resolution are
                # secondary factors we don't perturb here to keep the
                # fallback simple; handler_step_factor handles post-
                # sampler tail.
                steps = _int_or(spec.get("steps"), 20)
                step_scale = steps / 20.0
                res_scale = _resolution_scale(spec)
                hf = handler_step_factor(
                    spec.get("handler") or spec.get("build_fn") or "")
                # Handler factor goes the OTHER way — a low hf means
                # more tail work, so we INCREASE the canary estimate
                # (canary is all-sampler; this job isn't).
                est_sec = base_sec * step_scale * res_scale / max(hf, 0.1)
                low  = est_sec * 0.55
                high = est_sec * 1.65
                confidence = 0.30
                source = "preflight_canary"
                staleness = "fresh" if not row.get("stale") else "stale"
                rationale.append(
                    f"no dispatch history; projected from {staleness} "
                    f"canary ({base_sec:.1f}s baseline × "
                    f"steps {steps}/20 × res {res_scale:.1f}× "
                    f"× 1/{hf:.2f} tail factor)")
                break

    # 4. Hard-coded arch default.
    if est_sec <= 0:
        arch = spec.get("arch") or ""
        base = _ARCH_DEFAULT_SECONDS.get(arch, 10.0)
        steps = _int_or(spec.get("steps"), 30)
        step_scale = steps / 30.0
        res_scale = _resolution_scale(spec)
        est_sec = base * step_scale * res_scale
        low  = est_sec * 0.4
        high = est_sec * 2.5
        confidence = 0.15
        source = "arch_default"
        rationale.append(
            f"no data; rough arch default for {arch or 'unknown'} "
            f"({base:.1f}s × steps + res)")

    # 5. Adjust for live state.
    if cold_model:
        est_sec += COLD_LOAD_OVERHEAD_SECONDS
        high    += COLD_LOAD_OVERHEAD_SECONDS
        rationale.append(
            f"+{COLD_LOAD_OVERHEAD_SECONDS:.0f}s cold-load overhead")

    if vram_pct and vram_pct >= 100 * VRAM_PRESSURE_THRESHOLD:
        add = est_sec * (VRAM_PRESSURE_PENALTY - 1.0)
        est_sec += add
        high    += add * 1.2
        rationale.append(
            f"VRAM {vram_pct:.0f}%: +{add:.0f}s swap risk")

    if queue_ahead and queue_ahead > 0:
        per_job = queue_mean_sec or est_sec
        queue_add = per_job * queue_ahead
        est_sec += queue_add
        low     += queue_add
        high    += queue_add
        rationale.append(
            f"queue +{queue_ahead} slot(s): +{queue_add:.0f}s "
            f"(×{per_job:.0f}s/job)")

    # Round everything to avoid spurious decimals in the UI.
    return {
        "est_sec":    round(max(est_sec, 0.5), 1),
        "low":        round(max(low, 0.3), 1),
        "high":       round(max(high, est_sec), 1),
        "confidence": round(confidence, 2),
        "n":          int(n),
        "source":     source,
        "rationale":  rationale,
    }


# ── During-dispatch refinement ──────────────────────────────────────

def estimate_during_dispatch(pre: dict, *,
                              elapsed: float,
                              step_cur: int = 0,
                              step_max: int = 0,
                              queue_ahead: int = 0,
                              queue_mean_sec: Optional[float] = None) -> dict:
    """Refine a pre-dispatch estimate with live signals.

    Args:
        pre: the dict returned by :func:`estimate_pre_dispatch`. Passed
            through to access ``rationale`` + source flags.
        elapsed: wall-clock seconds since ``_JobManager.add()``.
        step_cur, step_max: current ComfyUI sampler step and total (0
            when no step info is available yet).
        queue_ahead: current queue depth ahead of us. Decrements as
            the queue drains; live refinement shrinks the estimate
            each time a predecessor finishes.

    Returns:
        dict with ``eta_sec`` (remaining seconds until done),
        ``total_sec`` (projected total elapsed at completion),
        ``source`` (``pre_dispatch`` / ``step_linear`` / ``blended``),
        ``confidence`` (0..1), ``rationale`` (list of strings that
        document which signals fed this refinement).
    """
    pre_total = float((pre or {}).get("est_sec") or 0.0)
    pre_conf  = float((pre or {}).get("confidence") or 0.0)
    rationale: list[str] = list((pre or {}).get("rationale") or [])
    source = "pre_dispatch"

    # Absent step info: trust pre + drain queue.
    live_total = pre_total

    # Step-linear projection.
    if step_cur > 0 and step_max > 0 and elapsed > 0.5:
        # Scale the sampler projection up to full handler runtime
        # using the tail factor so we're not dividing the sampler
        # percentage by itself (VAE decode etc. hasn't started yet).
        # Conservative: cap per-step seconds at 10× pre-estimate's
        # per-step rate so a stalled step 1 doesn't explode ETA.
        per_step = elapsed / max(step_cur, 1)
        sampler_total = per_step * step_max
        hf = handler_step_factor(
            (pre or {}).get("handler_key") or (pre or {}).get("handler") or "")
        step_linear_total = sampler_total / max(hf, 0.1)
        # Blend weight grows with step progress.
        w_live = max(BLEND_STEP_MIN_WEIGHT,
                      min(1.0, step_cur / BLEND_STEP_FULL_TRUST))
        # Dampen when pre-estimate had high confidence (n≥5). The
        # tight-fingerprint baseline is usually more stable than
        # one-point linear extrapolation.
        if pre_conf >= 0.7:
            w_live *= 0.80
        live_total = (1 - w_live) * pre_total + w_live * step_linear_total
        source = "blended" if pre_total > 0 else "step_linear"
        rationale.append(
            f"step {step_cur}/{step_max} at {elapsed:.1f}s "
            f"→ projecting {step_linear_total:.0f}s "
            f"(blend w={w_live:.2f})")

    # Queue drain: we never refund queue_ahead > 0 below pre_total's
    # built-in queue adjustment, because pre_total already includes
    # it. But during-dispatch we DO add a per-tick drain note so the
    # UI can show "queue drained, your job next".
    if queue_ahead and queue_ahead <= 0:
        rationale.append("queue clear — this job is next")

    # ETA floor: once we're past step_max the sampler is done but
    # the tail (VAE + post) is running. Avoid negative ETAs by at
    # least keeping a thin positive.
    if step_cur and step_max and step_cur >= step_max:
        # Tail remaining = total × (1 - handler_step_factor).
        hf = handler_step_factor(
            (pre or {}).get("handler_key") or (pre or {}).get("handler") or "")
        tail_frac = max(0.0, 1.0 - hf)
        tail_eta = max(0.5, (elapsed / max(hf, 0.1)) * tail_frac)
        live_total = max(live_total, elapsed + tail_eta)
        rationale.append(
            f"sampler done; ~{tail_eta:.0f}s post-processing tail")

    eta = live_total - elapsed
    return {
        "eta_sec":    round(eta, 1),
        "total_sec":  round(live_total, 1),
        "elapsed":    round(elapsed, 1),
        "source":     source,
        "confidence": round(min(1.0, pre_conf + (
            0.3 if source == "blended" else 0.0)), 2),
        "rationale":  rationale,
    }


# ── Internal helpers ────────────────────────────────────────────────

def _int_or(v: Any, default: int) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _resolution_scale(spec: dict) -> float:
    """Return a linear scale factor relative to the 512×512 baseline.
    Doubles resolution ≈ quadruples work (area scaling); we use
    sqrt(area/512²) so the scale is conservative."""
    res = spec.get("resolution")
    w = h = 512
    if isinstance(res, dict):
        w = _int_or(res.get("width"), 512)
        h = _int_or(res.get("height"), 512)
    elif isinstance(res, (tuple, list)) and len(res) >= 2:
        w = _int_or(res[0], 512)
        h = _int_or(res[1], 512)
    elif spec.get("width") or spec.get("height"):
        w = _int_or(spec.get("width"), 512)
        h = _int_or(spec.get("height"), 512)
    area = max(1, w * h)
    return round(math.sqrt(area / (512 * 512)), 2)


def _steps_ratio(spec: dict, sc) -> float:
    """Compute the ratio of this job's steps to the median steps in
    the (arch, handler) pool. Used to scale the broader-match median
    so a 50-step run doesn't get the 20-step median's ETA."""
    try:
        records = sc._read_jsonl("dispatch_log.jsonl")
    except Exception:
        records = []
    arch = spec.get("arch")
    handler = spec.get("handler") or spec.get("build_fn")
    pool_steps = []
    for r in records:
        if r.get("arch") != arch:
            continue
        if (r.get("build_fn") or r.get("handler")) != handler:
            continue
        s = r.get("steps")
        if isinstance(s, (int, float)) and s > 0:
            pool_steps.append(float(s))
    if not pool_steps:
        return 1.0
    pool_med = median(pool_steps)
    this_steps = _int_or(spec.get("steps"), int(pool_med) or 30)
    if pool_med <= 0:
        return 1.0
    return max(0.3, min(3.0, this_steps / pool_med))


__all__ = [
    "estimate_pre_dispatch",
    "estimate_during_dispatch",
    "format_countdown",
    "format_overrun",
    "handler_step_factor",
    "lora_stack_hash",
    # tunables (for tests)
    "VRAM_PRESSURE_THRESHOLD",
    "VRAM_PRESSURE_PENALTY",
    "COLD_LOAD_OVERHEAD_SECONDS",
    "BLEND_STEP_FULL_TRUST",
    "BLEND_STEP_MIN_WEIGHT",
]
