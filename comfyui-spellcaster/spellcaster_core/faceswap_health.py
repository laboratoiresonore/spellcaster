"""Faceswap runtime probe + opt-out guard.

comfy-mtb and ReActor's face-swap nodes load `inswapper_128.onnx`
via ONNX Runtime, which on many Windows ComfyUI installs bridges
to TensorRT. When the TensorRT DLL (`nvinfer_builder_resource_10.dll`
etc.) fails to load, the native path crashes the whole ComfyUI
server with a Windows access violation — Python can't catch it.

This module gives Spellcaster two tools:

  1. `probe_faceswap_nodes(comfy_url)` — check `/object_info` for the
     node CLASSES used by `build_faceswap`, `build_klein_headswap`,
     `build_photobooth`. If they're missing the node pack isn't
     installed; if they're registered the workflow CAN be dispatched
     but that doesn't guarantee the onnx/TensorRT layer is healthy
     (that failure is only observable at model-load time).

  2. `guard_faceswap(feature)` — raises `FaceswapDisabledError` if the
     user has opted out via `SPELLCASTER_FACESWAP_DISABLED=1` env var
     or a `faceswap_disabled: true` flag in the Guild config. Lets
     the user shut off an entire class of builders after a crash,
     until their TensorRT install is fixed.

Calibration / Shootout / Preflight do NOT use any of these nodes
(verified 2026-04-20), so they never call this guard. Only the
face-swap / head-swap / photobooth builders do.
"""
from __future__ import annotations

import json
import os
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


def is_faceswap_disabled() -> tuple[bool, str]:
    """True when the user has shut face-swap off. Checks, in order:
    `SPELLCASTER_FACESWAP_DISABLED` env var (truthy), then the
    injected config lookup's `faceswap_disabled` key.
    Returns (disabled, reason)."""
    raw = os.environ.get("SPELLCASTER_FACESWAP_DISABLED", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return (True, "SPELLCASTER_FACESWAP_DISABLED env var set")
    if _CONFIG_LOOKUP:
        try:
            cfg = _CONFIG_LOOKUP() or {}
            if cfg.get("faceswap_disabled"):
                return (True, "faceswap_disabled=true in config")
        except Exception:
            pass
    return (False, "")


def guard_faceswap(feature: str) -> None:
    """Raise `FaceswapDisabledError` if the user has opted out.
    Callers (workflow builders) should call this before assembling
    any workflow that contains ReActor / comfy-mtb face-swap nodes.
    `feature` is a short label used in the error message so the UI
    can tell the user WHICH feature was blocked."""
    disabled, why = is_faceswap_disabled()
    if disabled:
        raise FaceswapDisabledError(
            f"Face-swap feature '{feature}' is disabled on this install. "
            f"Reason: {why}. The faceswap / ReActor node chain crashed "
            f"ComfyUI on this machine — most often a TensorRT DLL load "
            f"failure (nvinfer_builder_resource_*.dll). Re-enable by "
            f"clearing SPELLCASTER_FACESWAP_DISABLED or setting "
            f"faceswap_disabled: false in guild_config.json."
        )


__all__ = [
    "FaceswapDisabledError",
    "FaceswapHealth",
    "probe_faceswap_nodes",
    "is_faceswap_disabled",
    "guard_faceswap",
    "set_config_lookup",
]
