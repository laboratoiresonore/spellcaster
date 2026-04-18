"""Dynamic loader for the Spellcaster service registry.

The registry is a JSON file (remote_services.json) that lists every
app/service the installer and antenna know how to coordinate. The
loader fetches the latest version from GitHub at startup, so adding a
new service means editing the JSON and pushing — no installer rebuild,
no antenna rebuild.

Resolution order on every call to load_services():

    1. HTTPS GET raw.githubusercontent.com/.../installer/remote_services.json
       (5 s timeout — we don't want to block install start-up)
    2. Local bundled copy at the same relative path (ships with the
       installer; guaranteed present offline)
    3. Empty list (catastrophic fallback — the caller will see an empty
       registry and can show a clear "no services configured" error)

The fetched JSON is validated against the baked-in schema before being
used. Missing required keys → reject the fetched copy and fall back to
local. Prevents a corrupted remote file from breaking every installer.

Both the installer (install.py) and the antenna (antenna/agent.py) call
load_services() to get the current list. This guarantees they agree on
what services exist.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


# Canonical URL — used by install.py, antenna, and anything else that
# wants the latest service list. Kept a bare constant, not a function,
# so callers can monkey-patch it for tests.
REMOTE_URL = (
    "https://raw.githubusercontent.com/laboratoiresonore/"
    "spellcaster/main/installer/remote_services.json"
)

# Location of the baked-in fallback, relative to THIS file.
_BAKED_PATH = Path(__file__).parent / "remote_services.json"

# Module-level cache so repeated calls inside one session don't re-hit
# the network. Refreshed when `refresh=True` is passed to load_services().
_CACHE: list[dict[str, Any]] | None = None


# Required keys on each service entry. Used to validate both fetched
# and baked JSON — a malformed entry is dropped (with a stderr warning)
# rather than crashing the caller.
_REQUIRED_KEYS = {"key", "label", "description", "default_port",
                  "detect_paths", "detect_process", "probe_path",
                  "managed_ops"}


def _validate(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop any entries missing required keys; return the clean list."""
    clean = []
    for i, svc in enumerate(services):
        if not isinstance(svc, dict):
            print(f"[remote_services] entry {i} is not an object — skipping",
                  file=sys.stderr)
            continue
        missing = _REQUIRED_KEYS - set(svc.keys())
        if missing:
            print(f"[remote_services] entry {svc.get('key', f'#{i}')} missing "
                  f"keys {missing} — skipping", file=sys.stderr)
            continue
        clean.append(svc)
    return clean


def _fetch_remote(timeout: float = 5.0) -> list[dict[str, Any]] | None:
    """Try to fetch the registry from GitHub. Returns None on any failure."""
    try:
        req = urllib.request.Request(REMOTE_URL, headers={
            "User-Agent": "spellcaster-remote-services-loader",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError) as e:
        print(f"[remote_services] fetch failed ({e}) — using baked copy",
              file=sys.stderr)
        return None
    if not isinstance(data, dict) or "services" not in data:
        print("[remote_services] fetched JSON lacks 'services' key",
              file=sys.stderr)
        return None
    services = data.get("services")
    if not isinstance(services, list):
        return None
    return _validate(services)


def _load_baked() -> list[dict[str, Any]]:
    """Load the registry from the bundled JSON file. Always succeeds
    unless the file is corrupt or missing.
    """
    try:
        with _BAKED_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return _validate(data.get("services", []))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[remote_services] baked JSON unreadable ({e})",
              file=sys.stderr)
        return []


def load_services(*, refresh: bool = False,
                  offline: bool = False) -> list[dict[str, Any]]:
    """Return the current services list.

    Args:
        refresh: If True, force a network fetch even when cached. Use
                 during long-running sessions (antenna) to pick up
                 registry changes pushed since startup.
        offline: If True, skip the network fetch entirely and use the
                 baked copy. Useful for air-gapped installs or when the
                 caller knows the network is unavailable.

    Returns a list of service dicts — see remote_services.json for the
    full schema.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return list(_CACHE)

    services: list[dict[str, Any]] | None = None
    if not offline:
        services = _fetch_remote()
    if not services:
        services = _load_baked()

    _CACHE = services
    return list(services)


# ─── Convenience accessors ───────────────────────────────────────────────
# These exist so callers don't have to re-implement common lookups.
# Each calls load_services() so they benefit from the cache.

def by_key(key: str) -> dict[str, Any] | None:
    """Return the service spec for a given key, or None if unknown."""
    for svc in load_services():
        if svc["key"] == key:
            return svc
    return None


def all_keys() -> list[str]:
    """All service keys in registry order (the order to ask about them)."""
    return [s["key"] for s in load_services()]


def desktop_apps() -> list[dict[str, Any]]:
    """Services that are desktop apps (no network port)."""
    return [s for s in load_services() if s.get("default_port") == 0]


def network_services() -> list[dict[str, Any]]:
    """Services that listen on a network port."""
    return [s for s in load_services() if s.get("default_port", 0) != 0]


if __name__ == "__main__":
    # python -m installer.remote_services → show what's live
    svcs = load_services(refresh=True)
    print(f"Loaded {len(svcs)} services:")
    for s in svcs:
        port = s.get("default_port", 0)
        port_str = f":{port}" if port else " (desktop)"
        print(f"  {s['key']:12s}{port_str:12s}{s['label']}")
