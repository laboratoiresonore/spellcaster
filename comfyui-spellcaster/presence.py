"""Spellcaster presence broker — HTTP routes on ComfyUI's own server.

Every Spellcaster-using plugin (GIMP, Darktable, Resolve, SillyTavern,
the Wizard Guild) already talks to ComfyUI as a hard dependency. This
module exposes three routes that let those plugins discover each
other WITHOUT needing the Guild process to be running:

    POST /spellcaster/presence/register
        Body: {key, label?, icon?, capabilities?, version?, url?,
               host?, instance_id?, meta?}
        Returns: {ok: true, key, instance_id, host}

    POST /spellcaster/presence/heartbeat
        Body: {key, instance_id?, host?, meta?}
        Returns: {ok: true, age_s, instance_id}

    GET  /spellcaster/presence/list
        Returns: {peers: [{key, instance_id, label, icon, capabilities,
                           version, url, host, address, age_s, meta},
                          ...]}

Presence lives in-memory on the ComfyUI process. Entries older than
PRESENCE_TTL_S drop off the list. A new plugin registering shows up
immediately; an old plugin that crashes disappears after one TTL.

LAN-wide discovery: multiple machines can heartbeat to a shared
ComfyUI. Because the broker keys records by `instance_id` (derived
from the logical key + the client's remote address when not supplied
explicitly), the same plugin running on two hosts coexists in the
peer list. Clients on any machine see the full fleet with `host` and
`address` populated so they can distinguish instances.

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
# Raised vs. pre-LAN design because the broker now keys by
# instance_id (one per host × plugin-kind), not just logical key.
MAX_ENTRIES: int = 256
MAX_KEY_LEN: int = 64
MAX_LABEL_LEN: int = 128
MAX_VERSION_LEN: int = 32
MAX_HOST_LEN: int = 96
MAX_INSTANCE_LEN: int = 160
MAX_META_BYTES: int = 2048  # JSON-serialised size cap for meta


# ── state ────────────────────────────────────────────────────────────

_lock = threading.Lock()
# Keyed by instance_id, not logical key — same kind of plugin on two
# different hosts coexists so we can return both in /list.
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


def _safe_host(v: Any) -> str:
    """Host is a display hint — letters/digits/dot/dash/underscore."""
    if not isinstance(v, str):
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "0123456789.-_")
    cleaned = "".join(c for c in v[:MAX_HOST_LEN] if c in allowed)
    return cleaned


def _safe_instance(v: Any) -> str:
    """Instance id — same charset as key + '@' + '.' for 'gimp@host'."""
    if not isinstance(v, str):
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "0123456789.-_@")
    cleaned = "".join(c for c in v[:MAX_INSTANCE_LEN] if c in allowed)
    return cleaned


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


def _derive_instance_id(key: str, body: dict, remote_addr: str) -> str:
    """Resolve the broker's storage key.

    Priority: explicit instance_id (client-provided, stable across
    restarts) > key@host (client-supplied host) > key@remote (server-
    observed peer address). The remote fallback is what makes LAN-wide
    coexistence work with zero client changes.
    """
    explicit = _safe_instance(body.get("instance_id"))
    if explicit:
        return explicit
    host = _safe_host(body.get("host"))
    if host:
        return f"{key}@{host}"
    addr = _safe_host(remote_addr) or "unknown"
    return f"{key}@{addr}"


def _prune_expired() -> None:
    """Caller must hold _lock."""
    cutoff = _now() - PRESENCE_TTL_S
    dead = [k for k, p in _peers.items() if p["last_heartbeat"] < cutoff]
    for k in dead:
        _peers.pop(k, None)


# ── public API (also callable from tests without HTTP) ───────────────

def register(body: dict, remote_addr: str = "") -> dict:
    """Register a plugin. Upsert: calling twice with the same
    instance_id refreshes the record."""
    key = _safe_key(body.get("key"))
    if not key:
        return {"error": "key required (alphanumeric/-/_, <=64 chars)"}
    instance_id = _derive_instance_id(key, body, remote_addr)
    now = _now()
    entry = {
        "key": key,
        "instance_id": instance_id,
        "label": _safe_str(body.get("label"), MAX_LABEL_LEN, default=key),
        "icon": _safe_str(body.get("icon"), 16),
        "capabilities": _safe_capabilities(body.get("capabilities")),
        "version": _safe_str(body.get("version"), MAX_VERSION_LEN),
        "url": _safe_str(body.get("url"), 256),
        "host": _safe_host(body.get("host")),
        "address": _safe_host(remote_addr),
        "meta": _safe_meta(body.get("meta")),
        "registered_at": now,
        "last_heartbeat": now,
    }
    with _lock:
        _prune_expired()
        # Evict oldest if we're about to overflow the ceiling.
        if instance_id not in _peers and len(_peers) >= MAX_ENTRIES:
            oldest = min(_peers.items(), key=lambda kv: kv[1]["last_heartbeat"])[0]
            _peers.pop(oldest, None)
        _peers[instance_id] = entry
    return {"ok": True, "key": key, "instance_id": instance_id,
            "host": entry["host"], "ttl_s": PRESENCE_TTL_S}


def heartbeat(body: dict, remote_addr: str = "") -> dict:
    """Refresh the last_heartbeat timestamp. Auto-registers a minimal
    record if the plugin wasn't registered yet — this keeps clients
    that crash-recover simple."""
    key = _safe_key(body.get("key"))
    if not key:
        return {"error": "key required"}
    instance_id = _derive_instance_id(key, body, remote_addr)
    now = _now()
    with _lock:
        _prune_expired()
        if instance_id in _peers:
            peer = _peers[instance_id]
            peer["last_heartbeat"] = now
            # Refresh address in case the client moved (DHCP, NAT).
            if remote_addr:
                peer["address"] = _safe_host(remote_addr)
            # Meta can be refreshed opportunistically.
            new_meta = body.get("meta")
            if isinstance(new_meta, dict):
                peer["meta"] = _safe_meta(new_meta)
            age = now - peer["registered_at"]
            return {"ok": True, "age_s": round(age, 2),
                    "instance_id": instance_id}
    # Not registered — fall through to register with whatever we got.
    return register(body, remote_addr)


def list_peers() -> dict:
    """Return active peers (dropping expired ones)."""
    now = _now()
    with _lock:
        _prune_expired()
        peers = []
        for p in _peers.values():
            peers.append({
                "key": p["key"],
                "instance_id": p["instance_id"],
                "label": p["label"],
                "icon": p["icon"],
                "capabilities": list(p["capabilities"]),
                "version": p["version"],
                "url": p["url"],
                "host": p["host"],
                "address": p["address"],
                "age_s": round(now - p["last_heartbeat"], 2),
                "meta": dict(p["meta"]),
            })
    # Newest heartbeats first — keeps the UI stable in the common case.
    peers.sort(key=lambda p: p["age_s"])
    return {"peers": peers, "ttl_s": PRESENCE_TTL_S}


def unregister(body: dict | str, remote_addr: str = "") -> dict:
    """Explicit deregister (plugin shutdown). Idempotent.

    Accepts either a body dict (new shape, mirrors register/heartbeat)
    or a bare key string (legacy shape from early callers). With a
    body, resolves instance_id the same way heartbeat does — so a
    client that always sends the same derivation inputs gets exact-
    match cleanup regardless of whether it tracks its own id.
    """
    if isinstance(body, str):
        body = {"key": body}
    key = _safe_key((body or {}).get("key"))
    if not key:
        return {"error": "key required"}
    instance_id = _derive_instance_id(key, body or {}, remote_addr)
    with _lock:
        _peers.pop(instance_id, None)
    return {"ok": True, "key": key, "instance_id": instance_id}


# ── HTTP route registration ──────────────────────────────────────────

def _client_addr(request) -> str:
    """Extract the peer IP aiohttp sees. Strips port; tolerates proxies."""
    remote = getattr(request, "remote", "") or ""
    # Some deployments expose an X-Forwarded-For chain — trust the leftmost
    # entry as the real client. ComfyUI default setup doesn't proxy, but
    # users do stick it behind Tailscale / Cloudflare / Caddy occasionally.
    try:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                remote = first
    except Exception:
        pass
    # Drop port if present (aiohttp gives "ip:port" sometimes).
    if ":" in remote and not remote.startswith("["):
        remote = remote.rsplit(":", 1)[0]
    return remote


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
        result = register(body, _client_addr(request))
        status = 200 if result.get("ok") else 400
        return web.json_response(result, status=status)

    @routes.post("/spellcaster/presence/heartbeat")
    async def _heartbeat(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = heartbeat(body, _client_addr(request))
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
        # Tolerate legacy callers that POSTed {"key": "..."} OR a bare
        # string in older snapshots.
        result = unregister(body, _client_addr(request))
        status = 200 if result.get("ok") else 400
        return web.json_response(result, status=status)

    return True


_available: bool = False

# ── mDNS / zeroconf ADDITIONAL broadcast ────────────────────────────
#
# The HTTP broker above stays authoritative (cross-subnet discovery,
# multi-host coexistence, rich TXT metadata over the 2 KB cap). On
# top of it, we ALSO advertise an mDNS service record on the LAN so
# peers using zeroconf (Bonjour / Avahi clients on macOS / Linux /
# Windows 10+) can find this ComfyUI without knowing its address.
#
# Failure is silent: a ComfyUI on a network without multicast, a
# firewall that blocks port 5353, a missing python-zeroconf install —
# none of those are fatal. The HTTP broker carries the primary
# discovery load; zeroconf is cream on top.
#
# Adopted from RESEARCH_EXISTING_TOOLS.md (sprint 3 evaluation path).

_ZEROCONF_SERVICE_TYPE = "_spellcaster._tcp.local."
_zeroconf_instance: Any = None
_zeroconf_service: Any = None


def _install_zeroconf_broadcast() -> bool:
    """Advertise this ComfyUI's presence-broker via mDNS. Returns
    True on success, False when zeroconf isn't installed / multicast
    isn't available / the port isn't discoverable. All failures are
    silent — the HTTP broker is the authoritative path."""
    global _zeroconf_instance, _zeroconf_service
    try:
        import socket
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        return False
    # Resolve this host's LAN IP. `socket.gethostbyname(socket.
    # gethostname())` returns 127.0.0.1 on some Linux configs — pick
    # the actual outbound IP by opening a UDP socket toward a public
    # target (no packets sent; just lets the kernel pick a route).
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            addr = s.getsockname()[0]
        ip_bytes = socket.inet_aton(addr)
    except Exception:
        return False
    # Discover the ComfyUI port the PromptServer is actually bound on.
    port = 8188  # ComfyUI default
    try:
        from server import PromptServer
        inst = getattr(PromptServer, "instance", None)
        if inst is not None:
            app = getattr(inst, "app", None)
            if app is not None:
                # aiohttp app doesn't always expose its bound port
                # directly; fall back to the default if introspection
                # fails.
                pass
    except Exception:
        pass
    # Short TXT record: keys that fit the 1300-byte mDNS TXT cap.
    # Capability list lives in HTTP broker's richer records; mDNS
    # just points clients at the broker URL.
    try:
        hostname = socket.gethostname()[:63] or "comfyui"
    except Exception:
        hostname = "comfyui"
    service_name = f"Spellcaster on {hostname}.{_ZEROCONF_SERVICE_TYPE}"
    props = {
        "key":       "comfyui",
        "label":     "Spellcaster / ComfyUI",
        "broker":    f"http://{addr}:{port}/spellcaster/presence/list",
        "version":   "1",
    }
    try:
        info = ServiceInfo(
            type_=_ZEROCONF_SERVICE_TYPE,
            name=service_name,
            addresses=[ip_bytes],
            port=port,
            properties=props,
            server=f"{hostname}.local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        _zeroconf_instance = zc
        _zeroconf_service = info
        print(f"[Spellcaster] mDNS advertised as "
              f"'{service_name}' ({addr}:{port})")
        return True
    except Exception as e:
        # Common failures: port already taken, multicast blocked,
        # hostname resolution issues. Silent — HTTP broker handles
        # the primary path.
        print(f"[Spellcaster] mDNS broadcast skipped: {e}")
        return False


def _teardown_zeroconf_broadcast() -> None:
    """Clean up mDNS registration on process exit. Best-effort."""
    global _zeroconf_instance, _zeroconf_service
    try:
        if _zeroconf_instance is not None and _zeroconf_service is not None:
            _zeroconf_instance.unregister_service(_zeroconf_service)
            _zeroconf_instance.close()
    except Exception:
        pass
    _zeroconf_instance = None
    _zeroconf_service = None


def install() -> bool:
    """Called from __init__.py at ComfyUI startup. Registers HTTP
    routes + optionally broadcasts via mDNS. Safe to call multiple
    times."""
    global _available
    if _available:
        return True
    _available = _register_routes()
    # Additional mDNS broadcast (silent on failure).
    try:
        _install_zeroconf_broadcast()
    except Exception:
        pass
    return _available


def is_available() -> bool:
    return _available
