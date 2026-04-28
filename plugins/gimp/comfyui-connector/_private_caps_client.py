"""the private downstream distribution-side client for the capabilities-server capabilities endpoint.

Companion to ``private-distro/caps-server/capabilities/`` — the
server side that composes + serves the document. This module is what
the private downstream distribution (the GIMP fork) imports to consume it.

Usage from the GIMP plug-in:

    from _private_caps_client import (
        fetch_capabilities, has_arch, has_feature, current,
        invalidate_cache,
    )

    caps = fetch_capabilities("http://<INTERNAL_HOST>:8191")
    if has_feature("sam3"):
        # Show the SAM3 button on the inline AI Actions expander
        ...
    if not has_arch("flux2klein"):
        # Hide every Klein button — the server doesn't have Klein nodes
        ...

The fetch result is cached for the session (per server URL) so the
inline expander can call ``has_feature(...)`` cheaply on every render
without re-hitting the server. Call ``invalidate_cache()`` after a
config change (server URL change, manual reconnect) to force a refetch.

Failure modes
-------------
* Server unreachable / 404 / timeout → `fetch_capabilities` returns
  None. Callers should fall back to "show everything" (legacy
  behaviour) so a misconfigured server doesn't render the plug-in
  useless.
* Non-JSON response → same fallback.
* Schema mismatch (`schema_version` not 1) → same fallback + a one-time
  stderr warning. Forward-compatibility: clients should ignore unknown
  fields silently.

This module has ZERO third-party deps — stdlib only — so it loads
cleanly inside GIMP's stripped-down embedded Python.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

# Schema we know how to read. Server may emit higher; we still try to
# use the known fields. Lower means we refuse (server is older than
# the client, very unlikely in practice).
_KNOWN_SCHEMA = 1

# Default port — must match caps-server.capabilities.DEFAULT_CAPS_PORT
DEFAULT_CAPS_PORT = 8191

# In-process cache — keyed by base URL ("http://host:port"), value is
# (timestamp, document). Module-level + thread-safe for the GIMP
# plug-in's mixed thread access (UI thread + dispatch worker thread).
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SEC = 60.0    # re-fetch after a minute — the private downstream distribution's
                          # connection is mostly steady-state

_WARNED_SCHEMA: set[int] = set()


# ── Public API ──────────────────────────────────────────────────────

def fetch_capabilities(base_url: str,
                       *,
                       force: bool = False,
                       timeout: float = 5.0) -> Optional[dict]:
    """Fetch the capabilities document from a capabilities-server server.

    `base_url` is the caps-server origin — "http://<INTERNAL_HOST>:8191"
    (NOT the ComfyUI URL on 8190; the caps server is a separate port).
    If the caller has only the ComfyUI URL, use `derive_caps_url(...)`.

    Returns the document dict on success, None on any failure. Caches
    successful fetches for ~60 s per base URL; pass `force=True` to
    bypass the cache.
    """
    base_url = base_url.rstrip("/")
    if not force:
        with _CACHE_LOCK:
            entry = _CACHE.get(base_url)
            if entry is not None:
                ts, doc = entry
                if time.time() - ts < _CACHE_TTL_SEC:
                    return doc

    url = f"{base_url}/v1/capabilities"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "private-pipeline-caps-client/1.0",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        doc = json.loads(body.decode("utf-8"))
    except urllib.error.URLError as exc:
        # Server unreachable / DNS / refused — silent fail. The
        # plug-in's status dashboard already reports backend health;
        # don't spam stderr on every poll.
        return None
    except (OSError, ValueError) as exc:
        print(f"[private caps] non-JSON or read error from {url}: {exc}",
              file=sys.stderr)
        return None

    if not isinstance(doc, dict):
        return None
    schema = doc.get("schema_version")
    if schema != _KNOWN_SCHEMA:
        # Tolerate forward-version drift — log once, still use what we can.
        if isinstance(schema, int) and schema not in _WARNED_SCHEMA:
            _WARNED_SCHEMA.add(schema)
            print(f"[private caps] schema mismatch (server={schema}, "
                  f"client={_KNOWN_SCHEMA}); reading best-effort",
                  file=sys.stderr)

    with _CACHE_LOCK:
        _CACHE[base_url] = (time.time(), doc)
    return doc


def derive_caps_url(comfy_url: str,
                    caps_port: int = DEFAULT_CAPS_PORT) -> str:
    """Given a ComfyUI URL ("http://host:8190"), return the matching
    caps URL ("http://host:8191"). Lets the plug-in derive the caps
    server from the existing comfy config without an extra setting."""
    # Cheap parse — http(s)://host[:port][/...]
    try:
        scheme, rest = comfy_url.split("://", 1)
    except ValueError:
        return f"http://127.0.0.1:{caps_port}"
    host_part = rest.split("/", 1)[0]
    host = host_part.rsplit(":", 1)[0] if ":" in host_part else host_part
    return f"{scheme}://{host}:{caps_port}"


def invalidate_cache(base_url: Optional[str] = None) -> None:
    """Force the next fetch to re-hit the server. Pass a specific
    base_url to drop just one entry; pass None to clear everything
    (useful on server-URL change in the plug-in's settings)."""
    with _CACHE_LOCK:
        if base_url is None:
            _CACHE.clear()
        else:
            _CACHE.pop(base_url.rstrip("/"), None)


# ── Convenience accessors ───────────────────────────────────────────
#
# These functions all take a `caps` dict (returned by
# fetch_capabilities) so callers can pass a known-good doc OR re-fetch
# per-call. None-tolerant: when caps is None or missing the relevant
# field, the accessor returns the "permissive" answer (True / empty
# list) so the plug-in stays functional during caps-server outages.

def has_arch(caps: Optional[dict], arch: str) -> bool:
    """True iff the server reports `arch` as supported.
    Permissive default (True) when caps is None."""
    if caps is None:
        return True
    archs = caps.get("archs")
    if not isinstance(archs, dict):
        return True
    entry = archs.get(arch)
    if not isinstance(entry, dict):
        return True
    return bool(entry.get("supported", True))


def has_feature(caps: Optional[dict], feature: str) -> bool:
    """True iff the server reports `feature` (e.g. "sam3", "klein_enhancer").
    Permissive default (True) when caps is None."""
    if caps is None:
        return True
    flags = caps.get("feature_flags")
    if not isinstance(flags, dict):
        return True
    return bool(flags.get(feature, True))


def channel(caps: Optional[dict]) -> str:
    """Return "sfw" or "nsfw". Defaults to "sfw" when unknown."""
    if caps is None:
        return "sfw"
    lic = caps.get("license")
    if not isinstance(lic, dict):
        return "sfw"
    return str(lic.get("channel") or "sfw")


def models(caps: Optional[dict], family: str) -> list[str]:
    """Return the list of installed model basenames for a family
    ("checkpoints", "loras", "vae", etc.). Empty list when unknown."""
    if caps is None:
        return []
    m = caps.get("models")
    if not isinstance(m, dict):
        return []
    raw = m.get(family) or []
    return [s for s in raw if isinstance(s, str)]


def missing_for_arch(caps: Optional[dict], arch: str) -> list[str]:
    """Return the ComfyUI node class_types missing for an arch — useful
    for telling the user WHY an arch is greyed out."""
    if caps is None:
        return []
    archs = caps.get("archs")
    if not isinstance(archs, dict):
        return []
    entry = archs.get(arch)
    if not isinstance(entry, dict):
        return []
    raw = entry.get("missing_nodes") or []
    return [s for s in raw if isinstance(s, str)]


def server_summary(caps: Optional[dict]) -> str:
    """One-line human summary for the plug-in's status bar /
    Server Info dialog."""
    if caps is None:
        return "capabilities-server server unreachable (caps endpoint down)."
    srv = caps.get("server") or {}
    cv = srv.get("comfyui_version", "?")
    inst = caps.get("instance_id", "?")
    nodes = caps.get("node_count", "?")
    chan = channel(caps)
    return (f"capabilities-server {inst} · ComfyUI {cv} · {nodes} nodes · "
            f"channel: {chan}")


# ── Self-test / smoke ──────────────────────────────────────────────

def _selftest() -> tuple[bool, str]:
    """Verify the cache + accessors against a synthetic document."""
    fake = {
        "schema_version": 1,
        "instance_id": "vm-test123",
        "license": {"channel": "nsfw", "tier": "lifetime"},
        "node_count": 42,
        "archs": {
            "sdxl": {"supported": True, "missing_nodes": []},
            "flux1dev": {"supported": False,
                          "missing_nodes": ["UNETLoader"]},
        },
        "feature_flags": {"sam3": True, "klein_enhancer": False},
        "models": {"checkpoints": ["foo.safetensors"]},
        "server": {"comfyui_version": "0.19.3"},
    }
    try:
        assert has_arch(fake, "sdxl") is True
        assert has_arch(fake, "flux1dev") is False
        assert has_arch(None, "anything") is True   # permissive default
        assert has_feature(fake, "sam3") is True
        assert has_feature(fake, "klein_enhancer") is False
        assert has_feature(None, "anything") is True
        assert channel(fake) == "nsfw"
        assert channel(None) == "sfw"
        assert models(fake, "checkpoints") == ["foo.safetensors"]
        assert models(fake, "loras") == []
        assert missing_for_arch(fake, "flux1dev") == ["UNETLoader"]
        assert "vm-test123" in server_summary(fake)
        # derive_caps_url
        assert derive_caps_url("http://1.2.3.4:8190") \
               == "http://1.2.3.4:8191"
        assert derive_caps_url("https://host/path") \
               == "https://host:8191"
    except AssertionError as exc:
        return False, f"selftest assertion failed: {exc}"
    return True, "ok"


if __name__ == "__main__":
    ok, detail = _selftest()
    print(("PASS" if ok else "FAIL"), detail)
    sys.exit(0 if ok else 1)
