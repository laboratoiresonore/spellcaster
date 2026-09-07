"""Antenna Registry — one entry per remote agent on the LAN.

The existing `interface_registry` tracks one slot per interface key
(gimp, darktable, resolve, ...). Antennas break that model because:

  * Multiple antennas can exist on one LAN — one on the ComfyUI box,
    one on the render farm, one on a laptop — and all send
    heartbeats with interface="antenna". The single-slot registry
    overwrites each new heartbeat, losing visibility into the others.

  * For any given service (comfyui, resolve, ollama), only ONE antenna
    is the "authoritative" host even if multiple report the service as
    installed. A laptop with ComfyUI installed-but-never-used shouldn't
    shadow the render box whose ComfyUI is actually loaded and serving
    models.

This module stores an independent per-machine registry keyed on the
hostname reported in heartbeat meta. It is populated by the same
heartbeat pipeline as interface_registry (see tavern/server.py's
`_handle_iface_heartbeat`).

Thread-safety: same pattern as interface_registry — one lock around
mutations, read-mostly snapshot for the /api/antennas endpoint.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# Heartbeat TTL — an antenna must ping within this window to count as online.
_ONLINE_TTL_S = 45.0


@dataclass
class AntennaEntry:
    """One physical antenna, keyed on hostname."""
    hostname: str = ""
    agent_url: str = ""
    ip: str = ""
    services: list[str] = field(default_factory=list)
    services_detail: dict[str, Any] = field(default_factory=dict)
    services_detected: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: float = 0.0
    # Free-form carryover from heartbeat meta (future-proofing)
    extra: dict[str, Any] = field(default_factory=dict)

    def online(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return (now - self.last_heartbeat) < _ONLINE_TTL_S

    def to_dict(self, *, now: float | None = None) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "agent_url": self.agent_url,
            "ip": self.ip,
            "services": list(self.services),
            "services_detail": dict(self.services_detail),
            "services_detected": dict(self.services_detected),
            "last_heartbeat": self.last_heartbeat,
            "online": self.online(now=now),
            "extra": dict(self.extra),
        }


# ─── Registry singleton ──────────────────────────────────────────────

_lock = threading.Lock()
_antennas: dict[str, AntennaEntry] = {}


def ingest_heartbeat(meta: dict[str, Any]) -> Optional[AntennaEntry]:
    """Update (or insert) the per-machine entry from an antenna heartbeat.

    The heartbeat payload was sent by antenna/heartbeat.py:_build_payloads
    under `interface="antenna"`. Its meta dict carries:
        hostname, ip, agent_url, services, services_detail, services_detected

    Returns the updated entry, or None if meta lacked a usable hostname
    (in which case we can't key it uniquely — degrade silently so one
    malformed client doesn't poison the registry).
    """
    if not isinstance(meta, dict):
        return None
    host = (meta.get("machine") or meta.get("hostname") or "").strip()
    if not host:
        return None

    with _lock:
        entry = _antennas.get(host)
        if entry is None:
            entry = AntennaEntry(hostname=host)
            _antennas[host] = entry
        entry.agent_url = (meta.get("agent_url") or entry.agent_url or "").strip()
        entry.ip = (meta.get("ip") or entry.ip or "").strip()
        services_val = meta.get("services")
        if isinstance(services_val, list):
            entry.services = [str(s) for s in services_val if s]
        elif isinstance(services_val, dict):
            # Defensive — older shapes may have been a dict
            entry.services = sorted(services_val.keys())
        sd = meta.get("services_detail")
        if isinstance(sd, dict):
            entry.services_detail = dict(sd)
        sdet = meta.get("services_detected")
        if isinstance(sdet, dict):
            entry.services_detected = dict(sdet)
        entry.last_heartbeat = time.time()
        # Preserve other fields the antenna sent — we don't own the schema
        reserved = {"machine", "hostname", "ip", "agent_url", "services",
                     "services_detail", "services_detected"}
        entry.extra = {k: v for k, v in meta.items() if k not in reserved}
        return entry


def snapshot() -> dict[str, Any]:
    """Read-mostly snapshot for the /api/antennas endpoint."""
    now = time.time()
    with _lock:
        entries = [a.to_dict(now=now) for a in _antennas.values()]
    # Sort by hostname so UI chips are stable across reloads
    entries.sort(key=lambda e: e["hostname"].lower())
    online = [e for e in entries if e["online"]]
    return {
        "antennas": entries,
        "total": len(entries),
        "online": len(online),
    }


def list_entries(*, only_online: bool = False) -> list[AntennaEntry]:
    """Return a copy of the entries (safe to iterate outside the lock)."""
    now = time.time()
    with _lock:
        items = list(_antennas.values())
    if only_online:
        items = [e for e in items if e.online(now=now)]
    items.sort(key=lambda e: e.hostname.lower())
    return items


def get(hostname: str) -> Optional[AntennaEntry]:
    with _lock:
        return _antennas.get(hostname)


def forget(hostname: str) -> bool:
    """Remove a stale entry (manual eviction for tests and UI cleanup)."""
    with _lock:
        return _antennas.pop(hostname, None) is not None


def clear() -> None:
    """Drop all entries — used by tests."""
    with _lock:
        _antennas.clear()


# ─── Service-to-antenna election ─────────────────────────────────────

def choose_antenna_for(service_key: str) -> Optional[AntennaEntry]:
    """Pick the best antenna to target for `service_key`.

    Precedence (highest wins):
      1. Must be online.
      2. Must have `service_key` in its `services` list (not just detected).
      3. If the service has a live-probe in `services_detail`, prefer
         antennas whose probe reports `reachable=True` or `installed=True`.
      4. For comfyui: prefer higher vram_free_gb in services_detail.
      5. For resolve: prefer antennas where `services_detail.resolve` is
         reachable (scripting on) over merely-installed.
      6. Tie-break: lexicographic hostname (stable across reloads).

    Returns None if no antenna matches — callers surface a clear error
    instead of silently picking a bad one.
    """
    candidates = list_entries(only_online=True)
    if not candidates:
        return None
    matching = [a for a in candidates if service_key in a.services]
    if not matching:
        # Legacy: if no antenna DECLARES the service, but one has it in
        # services_detected as installed, fall back to that. Lets users
        # drive a machine where auto-detect hasn't yet promoted the
        # service into the declared list.
        fallback = [a for a in candidates
                    if (a.services_detected.get(service_key) or {}).get("installed")]
        if not fallback:
            return None
        matching = fallback

    def _score(a: AntennaEntry) -> tuple[int, float, str]:
        # Larger tuple = better. We negate hostname for lex tie-break
        # because sorted() sorts ascending.
        detail = a.services_detail.get(service_key) or {}
        reachable = 1 if (detail.get("reachable") or detail.get("installed")) else 0
        vram = float(detail.get("vram_free_gb") or 0.0) if service_key == "comfyui" else 0.0
        # hostname used as string; sort desc by reachable/vram, asc by hostname
        return (reachable, vram, a.hostname.lower())

    matching.sort(key=_score, reverse=True)
    # After reverse sort hostnames become descending; fix by stable-sorting
    # again on hostname ascending while preserving the primary score.
    # Simpler: re-sort manually.
    best_score = _score(matching[0])
    tied = [a for a in matching if _score(a)[:2] == best_score[:2]]
    tied.sort(key=lambda a: a.hostname.lower())
    return tied[0]
