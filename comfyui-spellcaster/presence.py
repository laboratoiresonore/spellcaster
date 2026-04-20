"""Spellcaster presence broker — HTTP routes on ComfyUI's own server.

Every Spellcaster-using plugin (GIMP, Darktable, Resolve, SillyTavern,
the Wizard Guild) already talks to ComfyUI as a hard dependency. This
module exposes three routes that let those plugins discover each
other WITHOUT needing the Guild process to be running:

    POST /spellcaster/presence/register
        Body: {key, label?, icon?, capabilities?, version?, url?, meta?}
        Returns: {ok: true, key}

    POST /spellcaster/presence/heartbeat
        Body: {key, meta?}
        Returns: {ok: true, age_s}

    GET  /spellcaster/presence/list
        Returns: {peers: [{key, label, icon, capabilities, version,
                           url, age_s, meta}, ...]}

Presence lives in-memory on the ComfyUI process. Entries older than
PRESENCE_TTL_S drop off the list. A new plugin registering shows up
immediately; an old plugin that crashes disappears after one TTL.

Thread-safe: ComfyUI handles requests on an aiohttp event loop, so
all writes go through a plain threading.Lock. No disk persistence —
presence is transient by design (plugins re-register on each start).

Graceful degradation: if ComfyUI's PromptServer singleton isn't
available (bare-import tests, alternate runners), the module loads
without registering routes and callers get a `is_available() ==
False` signal.
"""

from __future__ import annotations

import threading
import time
from typing import Any


# ── configuration ────────────────────────────────────────────────────
#
# 45 s matches the ~20 s heartbeat cadence recommended in the audit
# doc with 2× safety factor — one dropped heartbeat (network hiccup)
# doesn't evict. Tune here; clients don't need to know.
PRESENCE_TTL_S: float = 45.0

# Max entries to return, max accepted per register. Hard ceilings
# protect against a misbehaving or hostile client filling memory.
MAX_ENTRIES: int = 64
MAX_KEY_LEN: int = 64
MAX_LABEL_LEN: int = 128
MAX_VERSION_LEN: int = 32
MAX_META_BYTES: int = 2048  # JSON-serialised size cap for meta


# ── state ────────────────────────────────────────────────────────────

_lock = threading.Lock()
_peers: dict[str, dict] = {}


# ── helpers ──────────────────────────────────────────────────────────

def _now() -> float:
    return time.time()


def _safe_str(v: Any, max_len: int, default: str = "") -> str:
    if not isinstance(v, str):
        return default
    return v[:max_len]


def _safe_key(v: Any) -> str | None:
    """Keys are the routing identifier; tighter charset than labels."""
    if not isinstance(v, str) or not v:
        return None
    # Match the existing InterfaceRegistry convention (gimp / darktable /
    # resolve / sillytavern / guild / signal / antenna, plus future slugs).
    if not v[:MAX_KEY_LEN].replace("_", "").replace("-", "").isalnum():
        return None
    return v[:MAX_KEY_LEN].lower()


def _safe_capabilities(v: Any) -> list[str]:
    """Capabilities are a short list of stable tokens like `send_image`."""
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for c in v[:16]:
        if isinstance(c, str) and c[:48].replace("_", "").isalnum():
            out.append(c[:48])
    return out


def _safe_meta(v: Any) -> dict:
    """Meta is free-form but size-capped to keep the endpoint cheap."""
    if not isinstance(v, dict):
        return {}
    import json
    try:
        blob = json.dumps(v, default=str)
    except Exception:
        return {}
    if len(blob) > MAX_META_BYTES:
        return {}
    return v


def _prune_expired() -> None:
    """Caller must hold _lock."""
    cutoff = _now() - PRESENCE_TTL_S
    dead = [k for k, p in _peers.items() if p["last_heartbeat"] < cutoff]
    for k in dead:
        _peers.pop(k, None)


# ── public API (also callable from tests without HTTP) ───────────────

def register(body: dict) -> dict:
    """Register a plugin. Upsert: calling twice with the same key
    refreshes the record."""
    key = _safe_key(body.get("key"))
    if not key:
        return {"error": "key required (alphanumeric/-/_, <=64 chars)"}
    now = _now()
    entry = {
        "key": key,
        "label": _safe_str(body.get("label"), MAX_LABEL_LEN, default=key),
        "icon": _safe_str(body.get("icon"), 16),
        "capabilities": _safe_capabilities(body.get("capabilities")),
        "version": _safe_str(body.get("version"), MAX_VERSION_LEN),
        "url": _safe_str(body.get("url"), 256),
        "meta": _safe_meta(body.get("meta")),
        "registered_at": now,
        "last_heartbeat": now,
    }
    with _lock:
        _prune_expired()
        # Evict oldest if we're about to overflow the ceiling.
        if key not in _peers and len(_peers) >= MAX_ENTRIES:
            oldest = min(_peers.items(), key=lambda kv: kv[1]["last_heartbeat"])[0]
            _peers.pop(oldest, None)
        _peers[key] = entry
    return {"ok": True, "key": key, "ttl_s": PRESENCE_TTL_S}


def heartbeat(body: dict) -> dict:
    """Refresh the last_heartbeat timestamp. Auto-registers a minimal
    record if the plugin wasn't registered yet — this keeps clients
    that crash-recover simple."""
    key = _safe_key(body.get("key"))
    if not key:
        return {"error": "key required"}
    now = _now()
    with _lock:
        _prune_expired()
        if key in _peers:
            _peers[key]["last_heartbeat"] = now
            # Meta can be refreshed opportunistically.
            new_meta = body.get("meta")
            if isinstance(new_meta, dict):
                _peers[key]["meta"] = _safe_meta(new_meta)
            age = now - _peers[key]["registered_at"]
            return {"ok": True, "age_s": round(age, 2)}
    # Not registered — fall through to register with just the key.
    return register({"key": key, "label": key,
                     "meta": body.get("meta") or {}})


def list_peers() -> dict:
    """Return active peers (dropping expired ones)."""
    now = _now()
    with _lock:
        _prune_expired()
        peers = []
        for p in _peers.values():
            peers.append({
                "key": p["key"],
                "label": p["label"],
                "icon": p["icon"],
                "capabilities": list(p["capabilities"]),
                "version": p["version"],
                "url": p["url"],
                "age_s": round(now - p["last_heartbeat"], 2),
                "meta": dict(p["meta"]),
            })
    # Newest heartbeats first — keeps the UI stable in the common case.
    peers.sort(key=lambda p: p["age_s"])
    return {"peers": peers, "ttl_s": PRESENCE_TTL_S}


def unregister(key: str) -> dict:
    """Explicit deregister (plugin shutdown). Idempotent."""
    k = _safe_key(key)
    if not k:
        return {"error": "key required"}
    with _lock:
        _peers.pop(k, None)
    return {"ok": True, "key": k}


# ── HTTP route registration ──────────────────────────────────────────

def _register_routes() -> bool:
    """Wire register/heartbeat/list/unregister onto ComfyUI's
    PromptServer. Returns True if the routes were attached."""
    try:
        from server import PromptServer  # ComfyUI's singleton
    except Exception:  # pragma: no cover — not in ComfyUI runtime
        return False
    try:
        from aiohttp import web
    except Exception:  # pragma: no cover
        return False

    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return False
    routes = getattr(instance, "routes", None)
    if routes is None:
        return False

    @routes.post("/spellcaster/presence/register")
    async def _register(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = register(body)
        status = 200 if result.get("ok") else 400
        return web.json_response(result, status=status)

    @routes.post("/spellcaster/presence/heartbeat")
    async def _heartbeat(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = heartbeat(body)
        status = 200 if result.get("ok") else 400
        return web.json_response(result, status=status)

    @routes.get("/spellcaster/presence/list")
    async def _list(_request):
        return web.json_response(list_peers())

    @routes.post("/spellcaster/presence/unregister")
    async def _unregister(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = unregister(body.get("key", ""))
        status = 200 if result.get("ok") else 400
        return web.json_response(result, status=status)

    return True


_available: bool = False


def install() -> bool:
    """Called from __init__.py at ComfyUI startup. Registers routes if
    possible, no-ops otherwise. Safe to call multiple times."""
    global _available
    if _available:
        return True
    _available = _register_routes()
    return _available


def is_available() -> bool:
    return _available
