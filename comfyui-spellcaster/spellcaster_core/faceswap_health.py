"""Faceswap runtime probe + auto-recovering guard.

comfy-mtb and ReActor's face-swap nodes load `inswapper_128.onnx`
via ONNX Runtime, which on many Windows ComfyUI installs bridges
to TensorRT. When the TensorRT DLL (`nvinfer_builder_resource_10.dll`
etc.) fails to load, the native path crashes the whole ComfyUI
server with a Windows access violation — Python can't catch it.

This module is a self-healing guard: the user never has to manually
toggle anything. The state machine is:

    AUTO_ON  ──(crash attributed to faceswap)──▶  AUTO_OFF
       ▲                                             │
       │       (ComfyUI stable for 30 min)           │
       └──────────────────────────────────────────────┘

  * `record_dispatch()` is called at build time by every face-swap
    workflow builder. It stamps the wall-clock time.
  * `record_probe(ok)` is called by a background heartbeat thread
    (Guild server / plugin) pinging ComfyUI every ~15 s.
  * When `record_probe(False)` lands AND the most recent dispatch
    was within the last 60 s, we ATTRIBUTE the outage to face-swap
    and flip `AUTO_ON` → `AUTO_OFF`.
  * When ComfyUI has been reachable for a continuous 30 min window
    AND the last disable was automatic (not user-forced), we flip
    `AUTO_OFF` → `AUTO_ON`. Max capability restored. No user action.
  * If the same crash pattern repeats 3 times, we escalate to
    `ESCALATED` — the user must explicitly re-enable. Protects
    against a broken install auto-re-enabling on every restart.

User overrides still beat the state machine:
  * `SPELLCASTER_FACESWAP_DISABLED=1` env var → forced off
  * `faceswap_disabled: true` in guild_config.json → forced off
  * `faceswap_force_enable: true` in guild_config.json → forced on
    (bypasses auto-disable; for when the user is sure the TRT install
    has been fixed and wants to skip the 30-min stability wait)

State is persisted to `<state_dir>/faceswap_state.json` so a Guild
restart doesn't reset the crash counter and reenable a known-broken
install.

Calibration / Shootout / Preflight do NOT use any of these nodes
(verified 2026-04-20), so they never call this guard. Only the
face-swap / head-swap / photobooth builders do.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Optional


# Node classes that the crashing chain registers. Presence in
# `/object_info` means the node pack loaded OK; absence means it
# isn't installed. Neither tells us whether TRT will crash at model
# load — that's inherently unknowable without the risky load itself.
_CRITICAL_NODE_CLASSES = (
    "ReActorFaceSwap",
    "ReActorRestoreFace",
    "ReActorLoadFaceModel",
    "Face Swap",                    # comfy-mtb FaceSwap
    "Load Face Analysis Model",      # comfy-mtb
    "Load Face Swap Model",          # comfy-mtb
)


class FaceswapDisabledError(RuntimeError):
    """Raised by `guard_faceswap` when the user has opted the
    face-swap / head-swap / photobooth paths off. Callers should
    surface the message verbatim to the UI."""


@dataclass
class FaceswapHealth:
    probed_at: float
    comfy_url: str
    reachable: bool
    registered: list[str]
    missing: list[str]
    error: str = ""

    @property
    def nodes_ok(self) -> bool:
        return self.reachable and len(self.registered) >= 1

    def to_dict(self) -> dict:
        return asdict(self)


_HEALTH_CACHE: dict[str, tuple[float, FaceswapHealth]] = {}
_HEALTH_TTL = 120.0   # reprobe every 2 min at most


def probe_faceswap_nodes(
    comfy_url: str,
    *,
    timeout: float = 3.0,
    force: bool = False,
) -> FaceswapHealth:
    """Hit `/object_info` and classify the critical face-swap node
    classes as registered vs missing. Cached per URL for 2 min so a
    burst of workflow dispatches doesn't re-query.
    """
    url = (comfy_url or "").rstrip("/")
    if not url:
        return FaceswapHealth(probed_at=time.time(), comfy_url="",
                               reachable=False, registered=[], missing=[],
                               error="no ComfyUI URL configured")
    if not force:
        cached = _HEALTH_CACHE.get(url)
        if cached and (time.time() - cached[0]) < _HEALTH_TTL:
            return cached[1]

    endpoint = url + "/object_info"
    try:
        req = urllib.request.Request(endpoint)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                h = FaceswapHealth(
                    probed_at=time.time(), comfy_url=url,
                    reachable=False, registered=[], missing=[],
                    error=f"HTTP {resp.status}",
                )
                _HEALTH_CACHE[url] = (time.time(), h)
                return h
            body = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        h = FaceswapHealth(
            probed_at=time.time(), comfy_url=url,
            reachable=False, registered=[], missing=[],
            error=f"unreachable: {e!s}"[:120],
        )
        _HEALTH_CACHE[url] = (time.time(), h)
        return h

    try:
        info = json.loads(body.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as e:
        h = FaceswapHealth(
            probed_at=time.time(), comfy_url=url,
            reachable=False, registered=[], missing=[],
            error=f"bad /object_info JSON: {e!s}"[:120],
        )
        _HEALTH_CACHE[url] = (time.time(), h)
        return h

    registered: list[str] = []
    missing: list[str] = []
    for name in _CRITICAL_NODE_CLASSES:
        (registered if name in info else missing).append(name)
    h = FaceswapHealth(
        probed_at=time.time(), comfy_url=url,
        reachable=True, registered=registered, missing=missing,
    )
    _HEALTH_CACHE[url] = (time.time(), h)
    return h


# ── Opt-out flag ────────────────────────────────────────────────────────

_CONFIG_LOOKUP: Optional[callable] = None


def set_config_lookup(fn) -> None:
    """Inject a `() -> dict` that returns the caller's (Guild /
    plugin) live config. We read the `faceswap_disabled` key from
    it in `guard_faceswap` when set. Keeps this module decoupled
    from the Guild's config file location."""
    global _CONFIG_LOOKUP
    _CONFIG_LOOKUP = fn


def _config_get(key: str, default=False):
    if not _CONFIG_LOOKUP:
        return default
    try:
        cfg = _CONFIG_LOOKUP() or {}
        return cfg.get(key, default)
    except Exception:
        return default


def is_faceswap_disabled() -> tuple[bool, str]:
    """True when the user has MANUALLY shut face-swap off. Checks
    env var first, then the config lookup. Returns (disabled,
    reason). Note: this is the user-forced disable only. For the
    full effective state (user + auto-disabled) use
    `get_effective_state` or `guard_faceswap`."""
    raw = os.environ.get("SPELLCASTER_FACESWAP_DISABLED", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return (True, "SPELLCASTER_FACESWAP_DISABLED env var set")
    if _config_get("faceswap_disabled", False):
        return (True, "faceswap_disabled=true in config")
    return (False, "")


# ── Auto-recovering state machine ──────────────────────────────────────
#
# Tracks crash attribution across the whole install lifetime and
# restores max capability without user action when the runtime looks
# stable again.

# Timing constants. `STABLE_REENABLE_SECONDS` is the window of
# continuous reachability required before we auto-re-enable; kept
# long enough to cover a user rebooting ComfyUI during driver
# install without immediately firing the canary again.
ATTRIBUTION_WINDOW_SECONDS = 60        # dispatch → crash grace period
STABLE_REENABLE_SECONDS = 30 * 60      # 30 min stable = auto-reenable
CRASH_ESCALATION_COUNT = 3             # N auto-disables → manual only

_STATE_LOCK = threading.Lock()
_PERSIST_PATH: Optional[str] = None

_STATE: dict = {
    "auto_disabled":        False,
    "auto_disabled_at":     None,     # unix ts
    "auto_disabled_reason": None,
    "last_dispatch_ts":     None,     # last workflow build
    "last_reachable_ts":    None,     # last record_probe(True)
    "last_unreachable_ts":  None,     # last record_probe(False)
    "reachable_since":      None,     # start of current stable streak
    "auto_disable_count":   0,        # cumulative this install
    "escalated":            False,    # True → don't auto-re-enable
    "history":              [],       # ring of recent crashes
    "updated_at":           0,
}


def set_persist_path(path: Optional[str]) -> None:
    """Caller (Guild server) points us at its state dir. On call we
    read back any prior state so a restart doesn't clobber the crash
    counter. Idempotent; last call wins."""
    global _PERSIST_PATH
    with _STATE_LOCK:
        _PERSIST_PATH = path
        if not path:
            return
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    for k in _STATE:
                        if k in loaded:
                            _STATE[k] = loaded[k]
        except Exception:
            pass


def _persist_state_locked() -> None:
    if not _PERSIST_PATH:
        return
    try:
        _STATE["updated_at"] = time.time()
        os.makedirs(os.path.dirname(_PERSIST_PATH), exist_ok=True)
        tmp = _PERSIST_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_STATE, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _PERSIST_PATH)
    except Exception:
        pass


def reset_state(*, preserve_escalation: bool = False) -> None:
    """Wipe crash history. Used when the user manually says "I fixed
    it, try again" (e.g. re-enable button in the UI) AND by the
    test harness between cases. When `preserve_escalation=True`
    the escalation flag AND the counter survive the reset — useful
    if the user wants to clear state without also resetting the
    "you've crashed 3 times" tally."""
    with _STATE_LOCK:
        kept_escalated = _STATE.get("escalated", False) if preserve_escalation else False
        kept_count = _STATE.get("auto_disable_count", 0) if preserve_escalation else 0
        _STATE.update({
            "auto_disabled":        False,
            "auto_disabled_at":     None,
            "auto_disabled_reason": None,
            "last_dispatch_ts":     None,
            "last_reachable_ts":    None,
            "last_unreachable_ts":  None,
            "reachable_since":      time.time(),
            "auto_disable_count":   kept_count,
            "escalated":            kept_escalated,
            "history":              [],
        })
        _persist_state_locked()


def record_dispatch() -> None:
    """Called at build time by every face-swap workflow builder.
    Stamps `last_dispatch_ts` for attribution."""
    with _STATE_LOCK:
        _STATE["last_dispatch_ts"] = time.time()
        _persist_state_locked()


def record_probe(ok: bool) -> None:
    """Called by a heartbeat thread with the result of pinging
    ComfyUI. Drives auto-disable (on failure within the attribution
    window) and auto-re-enable (after a stable streak)."""
    now = time.time()
    with _STATE_LOCK:
        if ok:
            _STATE["last_reachable_ts"] = now
            if _STATE.get("reachable_since") is None:
                _STATE["reachable_since"] = now
            # Auto-re-enable: stable long enough + was auto-disabled +
            # user hasn't escalated to manual-only.
            if (_STATE["auto_disabled"]
                    and not _STATE.get("escalated")
                    and (now - _STATE["reachable_since"]) >= STABLE_REENABLE_SECONDS):
                _STATE["auto_disabled"] = False
                _STATE["auto_disabled_at"] = None
                _STATE["auto_disabled_reason"] = (
                    f"auto-re-enabled after {int(STABLE_REENABLE_SECONDS/60)} "
                    f"min of stability"
                )
        else:
            _STATE["last_unreachable_ts"] = now
            _STATE["reachable_since"] = None
            last_disp = _STATE.get("last_dispatch_ts")
            if (last_disp is not None
                    and (now - last_disp) <= ATTRIBUTION_WINDOW_SECONDS
                    and not _STATE["auto_disabled"]):
                # Attribute this outage to a face-swap dispatch.
                _STATE["auto_disabled"] = True
                _STATE["auto_disabled_at"] = now
                _STATE["auto_disabled_reason"] = (
                    f"ComfyUI went unreachable within "
                    f"{int(now - last_disp)}s of a face-swap dispatch"
                )
                _STATE["auto_disable_count"] = int(_STATE.get("auto_disable_count", 0)) + 1
                hist = list(_STATE.get("history") or [])
                hist.append({
                    "ts": now,
                    "dispatch_ts": last_disp,
                    "gap_seconds": int(now - last_disp),
                })
                _STATE["history"] = hist[-10:]     # keep last 10
                if _STATE["auto_disable_count"] >= CRASH_ESCALATION_COUNT:
                    _STATE["escalated"] = True
        _persist_state_locked()


def get_effective_state() -> dict:
    """Compute the full guard verdict from every input. Read-only."""
    user_off, user_off_reason = is_faceswap_disabled()
    with _STATE_LOCK:
        snap = dict(_STATE)
    force_on = bool(_config_get("faceswap_force_enable", False))
    if user_off:
        state = "forced_off"
        reason = user_off_reason
    elif snap["escalated"] and snap["auto_disabled"]:
        state = "escalated"
        reason = (f"{snap['auto_disable_count']} auto-disables — "
                  f"manual re-enable required")
    elif snap["auto_disabled"] and not force_on:
        state = "auto_off"
        reason = snap.get("auto_disabled_reason") or "auto-disabled"
    elif force_on:
        state = "forced_on"
        reason = "faceswap_force_enable=true in config"
    else:
        state = "auto_on"
        # Surface the most recent auto-recovery reason so the UI can
        # show "auto-re-enabled after 30 min of stability" instead of
        # a plain "no crash attribution" after recovery.
        recovery = snap.get("auto_disabled_reason") or ""
        if "re-enabled" in recovery:
            reason = recovery
        else:
            reason = "no crash attribution"
    snap["state"] = state
    snap["state_reason"] = reason
    return snap


def guard_faceswap(feature: str) -> None:
    """Raise `FaceswapDisabledError` when the effective state blocks
    face-swap — whether the user opted out manually, we detected a
    crash within the attribution window, or we've escalated to
    manual-only after repeated crashes. Otherwise stamp the dispatch
    timestamp for future attribution and return."""
    snap = get_effective_state()
    st = snap["state"]
    if st in ("auto_on", "forced_on"):
        record_dispatch()
        return
    msg_head = f"Face-swap feature '{feature}' is disabled on this install."
    msg_tail = {
        "forced_off":
            (f"Reason: {snap['state_reason']}. Re-enable by clearing "
             f"SPELLCASTER_FACESWAP_DISABLED or setting "
             f"faceswap_disabled: false in guild_config.json."),
        "auto_off":
            (f"Reason: {snap['state_reason']}. Spellcaster auto-disabled "
             f"face-swap after ComfyUI became unreachable shortly after "
             f"a face-swap dispatch — most often a TensorRT DLL load "
             f"failure (nvinfer_builder_resource_*.dll). It will "
             f"auto-re-enable when ComfyUI stays reachable for "
             f"{int(STABLE_REENABLE_SECONDS/60)} minutes straight. "
             f"Override now by setting faceswap_force_enable: true "
             f"in guild_config.json."),
        "escalated":
            (f"Reason: {snap['state_reason']}. After "
             f"{CRASH_ESCALATION_COUNT} auto-disables Spellcaster no "
             f"longer re-enables face-swap automatically — your "
             f"runtime keeps crashing. Fix the TensorRT / onnxruntime "
             f"install, then set faceswap_force_enable: true OR call "
             f"the reset endpoint to clear the counter."),
    }.get(st, snap.get("state_reason") or "unknown")
    raise FaceswapDisabledError(f"{msg_head} {msg_tail}")


__all__ = [
    "FaceswapDisabledError",
    "FaceswapHealth",
    "probe_faceswap_nodes",
    "is_faceswap_disabled",
    "guard_faceswap",
    "set_config_lookup",
    "set_persist_path",
    "record_dispatch",
    "record_probe",
    "get_effective_state",
    "reset_state",
    "ATTRIBUTION_WINDOW_SECONDS",
    "STABLE_REENABLE_SECONDS",
    "CRASH_ESCALATION_COUNT",
]
