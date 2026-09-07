"""System-wide preflight status aggregator.

Combines every health signal Spellcaster can cheaply probe into a
single verdict the Calibration status dot consults:

  * ComfyUI reachability (one /system_stats hit)
  * Faceswap auto-recovering state (from faceswap_health)
  * LLM vision scorer availability (from lora_scorer)
  * Per-arch render canary, run once at install and on manual trigger
    (cached on disk so the status dot doesn't re-render every minute)

Two-tier design:

  * `get_status(...)` — fast poll, no real renders. Used by the
    Calibration status dot every 60 s. Returns the aggregate traffic
    light + last-known per-arch canary results from disk.
  * `run_full_preflight(...)` — heavy, real renders per installed
    arch. Called once at end-of-install (see `_setup_flow`) and on
    manual re-run (button in the Calibration Stats tab). Caches
    results to the state dir so future `get_status` calls surface
    them without re-running.

Overall verdict rules (first matching wins):
  * red    — ComfyUI unreachable OR faceswap escalated
             OR a per-arch canary failed recently
  * yellow — faceswap auto_off (recovering)
             OR scorer unavailable
             OR no preflight has been run yet
  * green  — everything above passes, recent successful preflight
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


CACHE_FILENAME = "preflight_cache.json"
CANARY_FRESH_SECONDS = 24 * 3600   # canaries older than 24h go yellow


@dataclass
class PreflightCanary:
    """One per (arch) result from run_full_preflight."""
    arch: str
    ok: bool
    error: str = ""
    elapsed_ms: int = 0
    ran_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PreflightSnapshot:
    """Aggregate status returned by `get_status`."""
    overall: str = "unknown"          # green | yellow | red | unknown
    headline: str = ""                # one-line summary for the tooltip
    comfy_reachable: bool = False
    comfy_error: str = ""
    faceswap: dict = field(default_factory=dict)   # from get_effective_state
    scorer: dict = field(default_factory=dict)     # from scorer.probe_available
    canaries: list = field(default_factory=list)
    canary_ran_at: Optional[float] = None
    probed_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


_CACHE_LOCK = threading.Lock()
_CACHE_PATH: Optional[str] = None
_RUN_JOB: dict = {"running": False, "progress": "", "started_at": None}


def set_cache_dir(path: Optional[str]) -> None:
    """Caller (Guild server) points us at its state dir."""
    global _CACHE_PATH
    with _CACHE_LOCK:
        _CACHE_PATH = (os.path.join(path, CACHE_FILENAME) if path else None)


def _load_cache() -> dict:
    if not _CACHE_PATH or not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(d: dict) -> None:
    if not _CACHE_PATH:
        return
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        tmp = _CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _CACHE_PATH)
    except Exception:
        pass


def _probe_comfy(comfy_url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """Fast reachability ping. No real render."""
    base = (comfy_url or "").rstrip("/")
    if not base:
        return (False, "no ComfyUI URL configured")
    try:
        req = urllib.request.Request(base + "/system_stats")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return (False, f"HTTP {resp.status}")
            return (True, "")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return (False, f"unreachable: {e!s}"[:120])


def _classify_overall(
    comfy_ok: bool,
    comfy_error: str,
    fs_state: str,
    scorer_ok: bool,
    canaries: list,
    canary_ran_at: Optional[float],
) -> tuple[str, str]:
    """Apply the overall verdict rules. Returns (colour, one-line headline)."""
    if not comfy_ok:
        return ("red", f"ComfyUI unreachable — {comfy_error or 'no response'}")
    if fs_state == "escalated":
        return ("red", "Face-swap escalated after 3 crashes — manual reset needed")
    failed_canaries = [c for c in canaries if not c.get("ok")]
    if failed_canaries and canary_ran_at:
        names = ", ".join(c["arch"] for c in failed_canaries[:3])
        return ("red", f"Preflight failed for {len(failed_canaries)} arch"
                        f"{'' if len(failed_canaries) == 1 else 'es'}: {names}")
    if fs_state == "auto_off":
        return ("yellow", "Face-swap auto-disabled — recovering when ComfyUI stabilises")
    if not scorer_ok:
        return ("yellow", "LLM scorer unavailable — auto-confirm disabled")
    if canary_ran_at is None:
        return ("yellow", "No preflight run yet — click to run one")
    age = time.time() - canary_ran_at
    if age > CANARY_FRESH_SECONDS:
        return ("yellow", f"Preflight is {int(age/3600)}h old — consider re-running")
    ok_count = sum(1 for c in canaries if c.get("ok"))
    return ("green",
             f"All systems go — {ok_count} arch{'' if ok_count == 1 else 'es'} verified")


def get_status(
    comfy_url: str,
    *,
    ollama_url: Optional[str] = None,
    scorer_model: Optional[str] = None,
) -> PreflightSnapshot:
    """Assemble the full status snapshot from fast probes + disk cache."""
    comfy_ok, comfy_err = _probe_comfy(comfy_url)

    fs_state: dict = {}
    try:
        from .faceswap_health import get_effective_state
        fs_state = get_effective_state()
    except Exception:
        pass
    scorer_probe: dict = {"ok": False, "reason": "module missing"}
    try:
        from .lora_scorer import (
            probe_available, DEFAULT_OLLAMA_URL, DEFAULT_MODEL,
        )
        scorer_probe = probe_available(
            ollama_url=ollama_url or DEFAULT_OLLAMA_URL,
            model=scorer_model or DEFAULT_MODEL,
        )
    except Exception as e:
        scorer_probe = {"ok": False, "reason": f"probe error: {e!s}"[:120]}

    cache = _load_cache()
    canaries = cache.get("canaries") or []
    canary_ran_at = cache.get("ran_at")
    overall, headline = _classify_overall(
        comfy_ok, comfy_err,
        fs_state.get("state", "unknown"),
        bool(scorer_probe.get("ok")),
        canaries, canary_ran_at,
    )
    return PreflightSnapshot(
        overall=overall,
        headline=headline,
        comfy_reachable=comfy_ok,
        comfy_error=comfy_err,
        faceswap=fs_state,
        scorer=scorer_probe,
        canaries=canaries,
        canary_ran_at=canary_ran_at,
        probed_at=time.time(),
    )


def run_full_preflight(
    comfy_url: str,
    arch_probe: Callable[[str, str, list, int], tuple[bool, str]],
    models: list[dict],
    *,
    on_progress: Optional[Callable[[str], None]] = None,
    per_probe_timeout: int = 60,
) -> list[PreflightCanary]:
    """Run one real render per unique installed arch. Delegates to
    `arch_probe(server, arch, models, timeout) -> (ok, error)`; the
    Guild wires this to `scaffold.lora_grouping._preflight_arch_probe`.

    Results are cached to disk so subsequent `get_status` calls pick
    them up without re-rendering. Skips video archs (they use a
    different inference path and probing them isn't meaningful).
    """
    skip_archs = {"wan", "ltx"}
    archs = sorted({
        (m.get("arch") or "").lower()
        for m in (models or [])
        if m.get("arch") and (m.get("arch") or "").lower() not in skip_archs
    })
    _RUN_JOB.update({"running": True, "started_at": time.time(),
                      "progress": f"0/{len(archs)}"})
    results: list[PreflightCanary] = []
    try:
        for i, arch in enumerate(archs, start=1):
            if on_progress:
                try: on_progress(f"probe {i}/{len(archs)}: {arch}")
                except Exception: pass
            _RUN_JOB["progress"] = f"{i}/{len(archs)}: {arch}"
            t0 = time.time()
            try:
                ok, err = arch_probe(comfy_url, arch, models, per_probe_timeout)
            except Exception as e:
                ok, err = (False, f"exception: {e!s}"[:200])
            results.append(PreflightCanary(
                arch=arch, ok=bool(ok), error=err,
                elapsed_ms=int((time.time() - t0) * 1000),
                ran_at=time.time(),
            ))
        with _CACHE_LOCK:
            _save_cache({
                "canaries": [c.to_dict() for c in results],
                "ran_at":   time.time(),
            })
    finally:
        _RUN_JOB.update({"running": False, "progress": ""})
    return results


def get_run_job_state() -> dict:
    return dict(_RUN_JOB)


__all__ = [
    "PreflightSnapshot",
    "PreflightCanary",
    "get_status",
    "run_full_preflight",
    "get_run_job_state",
    "set_cache_dir",
    "CANARY_FRESH_SECONDS",
]
