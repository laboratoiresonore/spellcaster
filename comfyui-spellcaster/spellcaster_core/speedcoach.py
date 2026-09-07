"""SpeedCoach — read-side telemetry aggregator.

Pure read-aggregation over files Spellcaster already writes:

  * ``<state_dir>/dispatch_log.jsonl``  — every dispatch completion
  * ``<state_dir>/preflight_cache.json`` — per-arch canary elapsed_ms
  * ``<state_dir>/faceswap_state.json``  — faceswap crash history
  * ``<state_dir>/ratings.jsonl``        — thumbs up/down per fingerprint
  * ``<state_dir>/videoshot_log.jsonl``  — per-frame render timings
  * ``<state_dir>/object_info_last.json`` — last-seen node catalogue hash

No writes, no network. Every frontend (GIMP, Darktable, Guild) calls
the same functions so the numbers are consistent across surfaces.

Design rules:

1.  **Graceful on missing data.** Every aggregator returns an empty
    result when the source file is absent. Callers render "no data
    yet" in the UI instead of erroring.
2.  **Sample-size gated.** ``suggest_alternatives`` never returns a
    suggestion backed by fewer than ``MIN_SAMPLE_SIZE`` samples
    (default 3). Tunable via ``configure(min_sample_size=...)``.
3.  **Speedup-threshold gated.** Suggestions require predicted
    speedup ≥ ``MIN_SPEEDUP_PCT`` (default 30%) — sub-threshold
    alternatives are noise.
4.  **Hot paths are cheap.** Aggregators read whole JSONL files; each
    file caps at 5000 lines (older rows skipped). Callers that need
    sub-50ms response wrap the aggregator with their own LRU.
5.  **No stateful side effects.** Calling an aggregator twice with
    the same underlying files returns identical results. Safe to call
    from any thread.

Configuration:

    from . import speedcoach
    speedcoach.set_state_dir("/path/to/.guild_state")
    speedcoach.configure(min_sample_size=3, min_speedup_pct=30)

Every aggregator is independent; you can call one without initializing
the others. Ship-time seed values are correct for the user's box.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from statistics import median
from typing import Any, Callable, Optional


DEFAULT_MIN_SAMPLE_SIZE = 3
DEFAULT_MIN_SPEEDUP_PCT = 30
MAX_JSONL_LINES = 5000
STALE_CANARY_SECONDS = 7 * 24 * 3600

_CFG_LOCK = threading.Lock()
_STATE_DIR: Optional[str] = None
_MIN_SAMPLE_SIZE: int = DEFAULT_MIN_SAMPLE_SIZE
_MIN_SPEEDUP_PCT: int = DEFAULT_MIN_SPEEDUP_PCT
_MAILBOX_CALLBACK: Optional[Callable[[], dict]] = None


def set_state_dir(path: Optional[str]) -> None:
    """Point the aggregator at a directory containing dispatch_log.jsonl,
    preflight_cache.json, ... Idempotent; the last call wins."""
    global _STATE_DIR
    with _CFG_LOCK:
        _STATE_DIR = (str(path).rstrip("\\/") if path else None)


def configure(*, min_sample_size: Optional[int] = None,
              min_speedup_pct: Optional[int] = None) -> None:
    """Tune sample-size + speedup thresholds. Callable at any time."""
    global _MIN_SAMPLE_SIZE, _MIN_SPEEDUP_PCT
    with _CFG_LOCK:
        if min_sample_size is not None:
            _MIN_SAMPLE_SIZE = max(1, int(min_sample_size))
        if min_speedup_pct is not None:
            _MIN_SPEEDUP_PCT = max(0, int(min_speedup_pct))


def set_mailbox_callback(fn: Optional[Callable[[], dict]]) -> None:
    """The Guild server injects a ``() -> {pending, oldest_s, p50_ms,
    p95_ms, p99_ms, dropped, retried, delivered_5m}`` callback so
    ``mailbox_stats()`` can surface live in-memory counters the bus
    keeps. Frontends that can't reach the Guild get ``{}``."""
    global _MAILBOX_CALLBACK
    with _CFG_LOCK:
        _MAILBOX_CALLBACK = fn


def _state_path(filename: str) -> Optional[str]:
    with _CFG_LOCK:
        root = _STATE_DIR
    if not root:
        return None
    return os.path.join(root, filename)


# ── data classes ─────────────────────────────────────────────────────

@dataclass
class Suggestion:
    kind: str                        # "arch_swap" | "param_trim" | "deferred_compute"
    message: str                     # user-facing one-liner
    current_elapsed: float           # predicted seconds at current config
    alt_elapsed: float               # predicted seconds at alternative
    speedup_pct: int                 # 0..99
    sample_size: int                 # n that backs the suggestion
    alt_job_spec: dict = field(default_factory=dict)  # machine-applicable alt

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DriftReport:
    has_drift: bool
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    changed: list = field(default_factory=list)
    previous_hash: str = ""
    current_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WarningsSummary:
    elapsed: float = 0.0
    predicted: float = 0.0
    outcome: str = "unknown"         # "ok" | "warnings" | "failed" | "unknown"
    warnings: list = field(default_factory=list)  # list[str]

    def to_dict(self) -> dict:
        return asdict(self)


# ── file IO helpers ─────────────────────────────────────────────────

def _read_jsonl(name: str, max_lines: int = MAX_JSONL_LINES) -> list[dict]:
    path = _state_path(name)
    if not path or not os.path.exists(path):
        return []
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    tail = lines[-max_lines:] if len(lines) > max_lines else lines
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                out.append(rec)
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def _read_json(name: str) -> dict:
    path = _state_path(name)
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _fingerprint(spec: dict) -> str:
    """Stable hash of the job-spec keys SpeedCoach groups by."""
    keys = ("arch", "handler", "upscale", "steps", "lora_stack_hash")
    parts = []
    for k in keys:
        v = spec.get(k)
        parts.append(f"{k}={v}")
    return "|".join(parts)


def _lora_stack_hash(loras: Any) -> str:
    """Deterministic hash for a LoRA stack (list of names or list of
    {name, weight} dicts). Order-sensitive so ``[a,b]`` != ``[b,a]``."""
    if not loras:
        return "none"
    parts: list[str] = []
    for item in loras:
        if isinstance(item, dict):
            nm = str(item.get("name") or item.get("path") or "").strip()
            w = item.get("weight") or item.get("strength") or 1.0
            parts.append(f"{nm}@{float(w):.2f}")
        else:
            parts.append(str(item).strip())
    blob = "||".join(parts)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _group_records_by_fingerprint(records: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        spec = {
            "arch": rec.get("arch"),
            "handler": rec.get("build_fn") or rec.get("handler"),
            "upscale": rec.get("upscale"),
            "steps": rec.get("steps"),
            "lora_stack_hash": rec.get("lora_stack_hash"),
        }
        groups[_fingerprint(spec)].append(rec)
    return groups


# ── public aggregators ─────────────────────────────────────────────

def predicted_elapsed(job_spec: dict) -> tuple[float, float, int]:
    """Return ``(median_elapsed, p95_elapsed, sample_size)`` for the
    fingerprint matching ``job_spec``. All three are 0 when n==0."""
    records = _read_jsonl("dispatch_log.jsonl")
    fp = _fingerprint(_normalize_spec(job_spec))
    match_elapsed = [
        float(rec.get("elapsed") or 0.0)
        for rec in records
        if _fingerprint(_normalize_spec(rec)) == fp
        and float(rec.get("elapsed") or 0.0) > 0.0
    ]
    if not match_elapsed:
        return (0.0, 0.0, 0)
    match_elapsed.sort()
    n = len(match_elapsed)
    med = median(match_elapsed)
    p95_idx = max(0, int(round(0.95 * (n - 1))))
    p95 = match_elapsed[p95_idx]
    return (float(med), float(p95), n)


def _normalize_spec(spec: dict) -> dict:
    """Accept a raw dispatch record OR a handler-dialog job_spec dict
    and coerce into the canonical fingerprint-input shape."""
    loras = spec.get("loras") or spec.get("lora_stack") or []
    lora_stack_hash = spec.get("lora_stack_hash")
    if not lora_stack_hash and loras:
        lora_stack_hash = _lora_stack_hash(loras)
    return {
        "arch": spec.get("arch") or spec.get("model_arch"),
        "handler": spec.get("build_fn") or spec.get("handler"),
        "upscale": spec.get("upscale"),
        "steps": spec.get("steps"),
        "lora_stack_hash": lora_stack_hash,
    }


def arch_speed_chart() -> list[dict]:
    """One entry per arch from the preflight canary cache, sorted by
    elapsed ms. Stale entries (>7 days) still appear with
    ``stale=True`` so the UI can render them faded."""
    cache = _read_json("preflight_cache.json")
    canaries = cache.get("canaries") or []
    now = time.time()
    out: list[dict] = []
    for c in canaries:
        ran_at = float(c.get("ran_at") or 0.0)
        age = max(0.0, now - ran_at) if ran_at else 0.0
        out.append({
            "arch": c.get("arch"),
            "ok": bool(c.get("ok")),
            "elapsed_ms": int(c.get("elapsed_ms") or 0),
            "ran_at": ran_at,
            "age_s": int(age),
            "stale": age > STALE_CANARY_SECONDS,
            "error": c.get("error") or "",
        })
    out.sort(key=lambda r: (not r["ok"], r["elapsed_ms"] or 10**9))
    return out


def suggest_alternatives(job_spec: dict) -> list[Suggestion]:
    """Generate (at most 3) alternative-configuration suggestions for
    ``job_spec``. Returns empty list when n<min_sample_size,
    speedup<threshold, or no signal in dispatch_log.

    Three suggestion classes:
      * ``arch_swap`` — same handler + different arch is faster
      * ``param_trim`` — same arch + fewer steps / smaller upscale
      * ``deferred_compute`` — queue is busy now, off-peak is faster
    """
    norm = _normalize_spec(job_spec)
    cur_median, cur_p95, cur_n = predicted_elapsed(norm)
    if cur_n < _MIN_SAMPLE_SIZE or cur_median <= 0:
        return []

    records = _read_jsonl("dispatch_log.jsonl")
    suggestions: list[Suggestion] = []

    # arch_swap
    arch_chart = arch_speed_chart()
    arch_speeds = {c["arch"]: c["elapsed_ms"]
                   for c in arch_chart if c["ok"] and c["elapsed_ms"]}
    cur_arch = norm.get("arch")
    cur_arch_ms = arch_speeds.get(cur_arch)
    if cur_arch_ms:
        faster = sorted(
            ((a, ms) for a, ms in arch_speeds.items()
             if a != cur_arch and ms < cur_arch_ms),
            key=lambda t: t[1],
        )
        if faster:
            alt_arch, alt_ms = faster[0]
            speedup = int(round(100 * (cur_arch_ms - alt_ms) / cur_arch_ms))
            if speedup >= _MIN_SPEEDUP_PCT:
                alt_elapsed = cur_median * (alt_ms / cur_arch_ms)
                suggestions.append(Suggestion(
                    kind="arch_swap",
                    message=(f"{cur_arch} averages {cur_median:.0f}s on your "
                             f"box (n={cur_n}). {alt_arch} averages "
                             f"{alt_elapsed:.0f}s for similar prompts."),
                    current_elapsed=cur_median,
                    alt_elapsed=alt_elapsed,
                    speedup_pct=speedup,
                    sample_size=cur_n,
                    alt_job_spec={**norm, "arch": alt_arch},
                ))

    # param_trim: same arch/handler, lower upscale or lower steps
    cur_up = _safe_int(norm.get("upscale"), 1)
    cur_steps = _safe_int(norm.get("steps"), 0)
    groups = _group_records_by_fingerprint(records)
    best_trim: Optional[tuple[int, dict]] = None
    for fp, recs in groups.items():
        if not recs:
            continue
        sample = _normalize_spec(recs[0])
        if (sample.get("arch") != norm.get("arch")
                or sample.get("handler") != norm.get("handler")):
            continue
        o_up = _safe_int(sample.get("upscale"), 1)
        o_steps = _safe_int(sample.get("steps"), 0)
        trims = False
        if cur_up and o_up and o_up < cur_up:
            trims = True
        elif cur_steps and o_steps and 0 < o_steps < cur_steps:
            trims = True
        if not trims:
            continue
        elapsed = [float(r.get("elapsed") or 0.0) for r in recs
                   if float(r.get("elapsed") or 0.0) > 0.0]
        if len(elapsed) < _MIN_SAMPLE_SIZE:
            continue
        med = median(elapsed)
        if med >= cur_median:
            continue
        speedup = int(round(100 * (cur_median - med) / cur_median))
        if speedup < _MIN_SPEEDUP_PCT:
            continue
        if best_trim is None or speedup > best_trim[0]:
            trim_params = {}
            if o_up != cur_up:
                trim_params["upscale"] = o_up
            if o_steps != cur_steps and o_steps > 0:
                trim_params["steps"] = o_steps
            best_trim = (speedup, {
                "speedup": speedup,
                "alt_elapsed": med,
                "sample_size": len(elapsed),
                "trim_params": trim_params,
            })
    if best_trim:
        _, t = best_trim
        trim_desc = ", ".join(f"{k} {cur_val_for(norm, k)}→{v}"
                              for k, v in t["trim_params"].items())
        suggestions.append(Suggestion(
            kind="param_trim",
            message=(f"Avg {cur_median:.0f}s on your box (n={cur_n}). "
                     f"Drop {trim_desc}: ~{t['alt_elapsed']:.0f}s "
                     f"(predicted, n={t['sample_size']})."),
            current_elapsed=cur_median,
            alt_elapsed=t["alt_elapsed"],
            speedup_pct=t["speedup"],
            sample_size=t["sample_size"],
            alt_job_spec={**norm, **t["trim_params"]},
        ))

    # deferred_compute: queue is busy now vs off-peak
    heatmap = queue_heatmap()
    if heatmap:
        hr = time.localtime().tm_hour
        wd = time.localtime().tm_wday
        now_load = heatmap[wd][hr] if heatmap and 0 <= wd < 7 else 0
        flat = [heatmap[d][h] for d in range(7) for h in range(24)]
        flat_nonzero = [v for v in flat if v > 0]
        if flat_nonzero and now_load > 0:
            avg_load = sum(flat_nonzero) / len(flat_nonzero)
            if now_load >= avg_load * 1.5:
                overhead_pct = int(round(100 * (now_load - avg_load) / now_load))
                if overhead_pct >= _MIN_SPEEDUP_PCT:
                    suggestions.append(Suggestion(
                        kind="deferred_compute",
                        message=(f"Queue is busy now (load {now_load:.0f} vs "
                                 f"avg {avg_load:.0f}). Waiting for an "
                                 f"off-peak window would cut ~{overhead_pct}% "
                                 f"of the wait time."),
                        current_elapsed=cur_median,
                        alt_elapsed=cur_median * (avg_load / max(now_load, 1)),
                        speedup_pct=overhead_pct,
                        sample_size=cur_n,
                        alt_job_spec=dict(norm),
                    ))

    return suggestions[:3]


def cur_val_for(spec: dict, key: str) -> Any:
    """Pretty-printer for suggestion messages."""
    v = spec.get(key)
    return v if v is not None else "?"


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def lora_impact() -> list[dict]:
    """Per-LoRA delta-t and thumbs delta (percentage points). Returns
    rows sorted by absolute Δt descending so the UI can lead with
    the most expensive LoRAs. Skips LoRAs with fewer than
    min_sample_size samples."""
    records = _read_jsonl("dispatch_log.jsonl")
    ratings = _read_jsonl("ratings.jsonl")
    if not records:
        return []

    # Baseline: elapsed times WITHOUT any LoRA (or with that specific
    # LoRA absent) grouped per handler.
    by_handler: dict[str, list[float]] = defaultdict(list)
    per_lora: dict[str, list[float]] = defaultdict(list)
    for rec in records:
        handler = rec.get("build_fn") or rec.get("handler") or "unknown"
        elapsed = float(rec.get("elapsed") or 0.0)
        if elapsed <= 0:
            continue
        loras = rec.get("loras") or []
        names = [_lora_name(l) for l in loras if _lora_name(l)]
        if not names:
            by_handler[handler].append(elapsed)
        else:
            for nm in names:
                per_lora[f"{handler}::{nm}"].append(elapsed)

    # Thumbs rate per fingerprint (approx — by LoRA).
    thumbs_per_lora: dict[str, list[int]] = defaultdict(list)
    for rec in ratings:
        loras = rec.get("loras") or []
        vote = 1 if str(rec.get("verdict") or "").lower() in ("up", "yes", "1", "true") else 0
        for nm in [_lora_name(l) for l in loras if _lora_name(l)]:
            thumbs_per_lora[nm].append(vote)

    # Baseline thumbs rate across all runs.
    all_votes = [
        1 if str(rec.get("verdict") or "").lower() in ("up", "yes", "1", "true") else 0
        for rec in ratings
    ]
    base_thumbs_pct = (sum(all_votes) / max(len(all_votes), 1)) * 100 if all_votes else 0

    rows: list[dict] = []
    for key, samples in per_lora.items():
        if len(samples) < _MIN_SAMPLE_SIZE:
            continue
        handler, lora_name = key.split("::", 1)
        base = by_handler.get(handler) or []
        if len(base) < _MIN_SAMPLE_SIZE:
            continue
        delta_t = median(samples) - median(base)
        lora_votes = thumbs_per_lora.get(lora_name) or []
        if lora_votes and all_votes:
            lora_pct = (sum(lora_votes) / len(lora_votes)) * 100
            delta_pp = int(round(lora_pct - base_thumbs_pct))
        else:
            delta_pp = 0
        rows.append({
            "lora": lora_name,
            "delta_t": round(delta_t, 1),
            "delta_thumbs_pp": delta_pp,
            "sample_size": len(samples),
        })
    rows.sort(key=lambda r: abs(r["delta_t"]), reverse=True)
    return rows


def _lora_name(l: Any) -> str:
    if isinstance(l, dict):
        return str(l.get("name") or l.get("path") or "")
    return str(l)


def queue_heatmap() -> list[list[int]]:
    """7×24 integer matrix — [weekday][hour_of_day] = dispatch count
    over all rows in dispatch_log.jsonl. weekday 0 = Monday."""
    records = _read_jsonl("dispatch_log.jsonl")
    if not records:
        return []
    out = [[0] * 24 for _ in range(7)]
    for rec in records:
        ts = float(rec.get("ts") or 0.0)
        if ts <= 0:
            continue
        try:
            lt = time.localtime(ts)
            out[lt.tm_wday][lt.tm_hour] += 1
        except (ValueError, OSError):
            continue
    return out


def warnings_last_run() -> WarningsSummary:
    records = _read_jsonl("dispatch_log.jsonl", max_lines=50)
    if not records:
        return WarningsSummary()
    last = records[-1]
    warnings = list(last.get("warnings") or [])
    outcome = "ok"
    if warnings:
        outcome = "warnings"
    if last.get("failed") or last.get("error"):
        outcome = "failed"
        if last.get("error") and last["error"] not in warnings:
            warnings.append(str(last["error"])[:200])
    return WarningsSummary(
        elapsed=float(last.get("elapsed") or 0.0),
        predicted=float(last.get("predicted_elapsed") or 0.0),
        outcome=outcome,
        warnings=warnings,
    )


def drift_since_last_session() -> DriftReport:
    """Compare the current object_info_last.json (written at session
    start) against the stored ``previous`` snapshot in the same file
    and classify the diff as added / removed / signature-changed."""
    data = _read_json("object_info_last.json")
    cur = data.get("current") or {}
    prev = data.get("previous") or {}
    if not cur or not prev:
        return DriftReport(
            has_drift=False,
            previous_hash=str(prev.get("hash") or ""),
            current_hash=str(cur.get("hash") or ""),
        )
    cur_nodes = set((cur.get("nodes") or {}).keys())
    prev_nodes = set((prev.get("nodes") or {}).keys())
    added = sorted(cur_nodes - prev_nodes)
    removed = sorted(prev_nodes - cur_nodes)
    changed: list[dict] = []
    for n in cur_nodes & prev_nodes:
        c_sig = (cur.get("nodes") or {}).get(n, "")
        p_sig = (prev.get("nodes") or {}).get(n, "")
        if c_sig != p_sig:
            changed.append({"node": n, "from": p_sig, "to": c_sig})
    has_drift = bool(added or removed or changed)
    return DriftReport(
        has_drift=has_drift,
        added=added[:50],
        removed=removed[:50],
        changed=changed[:50],
        previous_hash=str(prev.get("hash") or ""),
        current_hash=str(cur.get("hash") or ""),
    )


def faceswap_reliability() -> dict:
    """Return ``{history: [...], crash_pct: int, total: int,
    spark: str, state: str}`` for the faceswap sparkline."""
    state = _read_json("faceswap_state.json")
    history = list(state.get("history") or [])
    # Build a fake sparkline over the last 20 dispatch-or-crash events.
    # Crashes produce a higher bar; successes produce a low bar.
    # Without per-run success records we approximate: each crash = 1
    # crash bar; interpolate 19 "clean" bars between crashes so the
    # sparkline has meaningful shape even with a short history.
    bars: list[int] = []
    last_crash_ts = 0.0
    for c in history[-20:]:
        bars.append(3 if int(c.get("gap_seconds") or 0) < 10 else 2)
        last_crash_ts = float(c.get("ts") or 0.0)
    # Pad with low bars (no crash).
    while len(bars) < 20:
        bars.insert(0, 1)
    bars = bars[-20:]
    spark_chars = "▁▂▃▄▅▆▇█"
    spark = "".join(spark_chars[min(b, 7)] for b in bars)
    total = max(len(history), 0)
    auto_disable = int(state.get("auto_disable_count") or 0)
    # Crash pct: crashes over last 20 runs (approx; real runs history
    # would need dispatch_log cross-ref, skipped to keep this light).
    crash_pct = int(round(100 * len([b for b in bars if b >= 3]) / 20))
    return {
        "history": history[-20:],
        "crash_pct": crash_pct,
        "total": total,
        "spark": spark,
        "auto_disable_count": auto_disable,
        "escalated": bool(state.get("escalated")),
        "auto_disabled": bool(state.get("auto_disabled")),
        "state_reason": state.get("auto_disabled_reason") or "",
        "last_crash_ts": last_crash_ts,
    }


def videoshot_frame_times(shot_id: Optional[str] = None) -> dict:
    """Return ``{frames: [float_seconds,...], median, slowest,
    slowest_index}``. When shot_id is given only frames for that
    shot are included."""
    records = _read_jsonl("videoshot_log.jsonl")
    if shot_id:
        records = [r for r in records if r.get("shot_id") == shot_id]
    frames = [float(r.get("elapsed") or 0.0) for r in records
              if float(r.get("elapsed") or 0.0) > 0.0]
    if not frames:
        return {"frames": [], "median": 0.0, "slowest": 0.0,
                "slowest_index": -1, "count": 0}
    slowest = max(frames)
    slowest_index = frames.index(slowest)
    return {
        "frames": frames,
        "median": round(median(frames), 2),
        "slowest": round(slowest, 2),
        "slowest_index": slowest_index,
        "count": len(frames),
    }


def mailbox_stats() -> dict:
    """Return live mailbox SLA counters. Empty dict when the callback
    isn't wired (e.g. called from a plugin that can't reach the Guild)."""
    with _CFG_LOCK:
        cb = _MAILBOX_CALLBACK
    if cb is None:
        return {}
    try:
        stats = cb() or {}
    except Exception:
        return {}
    return dict(stats) if isinstance(stats, dict) else {}


def wizard_profile_stats(wizard_id: str) -> dict:
    """``{avg, q3, thumbs_pct, sample_size}`` for one wizard."""
    records = _read_jsonl("dispatch_log.jsonl")
    ratings = _read_jsonl("ratings.jsonl")
    elapsed = [float(r.get("elapsed") or 0.0) for r in records
               if r.get("char_id") == wizard_id
               and float(r.get("elapsed") or 0.0) > 0.0]
    votes = [
        1 if str(r.get("verdict") or "").lower() in ("up", "yes", "1", "true") else 0
        for r in ratings if r.get("char_id") == wizard_id
    ]
    if not elapsed:
        return {"avg": 0.0, "q3": 0.0, "thumbs_pct": 0,
                "sample_size": 0, "votes": len(votes)}
    elapsed.sort()
    n = len(elapsed)
    avg = round(sum(elapsed) / n, 1)
    q3_idx = max(0, int(round(0.75 * (n - 1))))
    q3 = round(elapsed[q3_idx], 1)
    thumbs_pct = (int(round(100 * sum(votes) / len(votes)))
                  if votes else 0)
    return {
        "avg": avg,
        "q3": q3,
        "thumbs_pct": thumbs_pct,
        "sample_size": n,
        "votes": len(votes),
    }


def speed_leaderboard(limit: int = 10) -> list[dict]:
    """Per-handler median elapsed, slowest to fastest."""
    records = _read_jsonl("dispatch_log.jsonl")
    per_handler: dict[str, list[float]] = defaultdict(list)
    for rec in records:
        handler = rec.get("build_fn") or rec.get("handler") or "unknown"
        elapsed = float(rec.get("elapsed") or 0.0)
        if elapsed > 0:
            per_handler[handler].append(elapsed)
    rows = []
    for h, samples in per_handler.items():
        if len(samples) < _MIN_SAMPLE_SIZE:
            continue
        rows.append({
            "handler": h,
            "median": round(median(samples), 1),
            "sample_size": len(samples),
        })
    rows.sort(key=lambda r: r["median"])
    return rows[:limit]


def cost_vs_quality() -> list[dict]:
    """Scatter data: [{handler, elapsed, thumbs_pct, n}]. Elapsed is
    the per-handler median. Thumbs pct is per-handler rate."""
    records = _read_jsonl("dispatch_log.jsonl")
    ratings = _read_jsonl("ratings.jsonl")
    if not records:
        return []
    per_handler: dict[str, list[float]] = defaultdict(list)
    thumbs_handler: dict[str, list[int]] = defaultdict(list)
    for rec in records:
        h = rec.get("build_fn") or rec.get("handler") or "unknown"
        e = float(rec.get("elapsed") or 0.0)
        if e > 0:
            per_handler[h].append(e)
    for rec in ratings:
        h = rec.get("build_fn") or rec.get("handler") or "unknown"
        vote = 1 if str(rec.get("verdict") or "").lower() in ("up", "yes", "1", "true") else 0
        thumbs_handler[h].append(vote)
    out: list[dict] = []
    for h, samples in per_handler.items():
        if len(samples) < _MIN_SAMPLE_SIZE:
            continue
        votes = thumbs_handler.get(h) or []
        pct = (int(round(100 * sum(votes) / len(votes)))
               if votes else None)
        out.append({
            "handler": h,
            "elapsed": round(median(samples), 1),
            "thumbs_pct": pct,
            "sample_size": len(samples),
        })
    out.sort(key=lambda r: r["elapsed"])
    return out


# ── writer helpers (used by server + plugins) ─────────────────────

def append_dispatch_record(record: dict) -> None:
    """Append one enriched dispatch record to dispatch_log.jsonl.
    The server's /api/telemetry/dispatch_ok endpoint calls this; it's
    the single writer so the schema stays consistent.

    Record shape (all optional except ts):
      ts, elapsed, predicted_elapsed, build_fn, handler, char_id,
      arch, model, loras (list), lora_stack_hash, steps, cfg,
      upscale, warnings (list[str]), failed (bool), error (str)
    """
    path = _state_path("dispatch_log.jsonl")
    if not path:
        return
    rec = dict(record or {})
    rec.setdefault("ts", time.time())
    if "loras" in rec and "lora_stack_hash" not in rec:
        rec["lora_stack_hash"] = _lora_stack_hash(rec["loras"])
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def append_rating_record(record: dict) -> None:
    """Append one rating (thumbs up/down / score) to ratings.jsonl."""
    path = _state_path("ratings.jsonl")
    if not path:
        return
    rec = dict(record or {})
    rec.setdefault("ts", time.time())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def append_videoshot_frame(record: dict) -> None:
    """Append one per-frame render timing to videoshot_log.jsonl."""
    path = _state_path("videoshot_log.jsonl")
    if not path:
        return
    rec = dict(record or {})
    rec.setdefault("ts", time.time())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def record_object_info_snapshot(nodes: dict[str, str]) -> DriftReport:
    """Rotate the stored ``current`` snapshot into ``previous`` and
    write the new one. ``nodes`` maps node_class_name → signature
    string (e.g. concatenated required-input names). Returns the
    DriftReport comparing the two."""
    path = _state_path("object_info_last.json")
    if not path:
        return DriftReport(has_drift=False)
    prev_current = _read_json("object_info_last.json").get("current") or {}
    cur_hash = hashlib.sha1(
        json.dumps(nodes, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    new_doc = {
        "previous": prev_current,
        "current": {"nodes": nodes, "hash": cur_hash, "ts": time.time()},
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_doc, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
    return drift_since_last_session()


__all__ = [
    # config
    "set_state_dir", "configure", "set_mailbox_callback",
    # types
    "Suggestion", "DriftReport", "WarningsSummary",
    # aggregators
    "suggest_alternatives", "predicted_elapsed", "arch_speed_chart",
    "lora_impact", "queue_heatmap", "warnings_last_run",
    "drift_since_last_session", "faceswap_reliability",
    "videoshot_frame_times", "mailbox_stats", "wizard_profile_stats",
    "speed_leaderboard", "cost_vs_quality",
    # writers
    "append_dispatch_record", "append_rating_record",
    "append_videoshot_frame", "record_object_info_snapshot",
    # helpers
    "DEFAULT_MIN_SAMPLE_SIZE", "DEFAULT_MIN_SPEEDUP_PCT",
]
