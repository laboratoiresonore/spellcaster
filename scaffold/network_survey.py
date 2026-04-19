"""Multi-host service survey — lead question of the Spellcaster's install flow.

Before any download or model test, the Spellcaster asks the user where each
Spellcaster-compatible service is hosted:

    - Local machine                   (most common; no antenna needed)
    - Another machine on the LAN      (needs a Spellcaster Antenna there)
    - Not installed                   (we'll offer to install it)
    - Managed elsewhere, skip         (user knows what they're doing)

Then for every "remote" answer, the Spellcaster walks the user through
launching the Antenna on that machine and verifies end-to-end reachability
before moving on. Surfacing this as a first-class step rather than a
follow-up keeps the install flow safe — once we know the network topology,
every subsequent probe / install / test routes to the right host.

This module is the canonical backend. The catalog of services lives in
`installer/remote_services.json` (also used by the Antenna itself for
auto-detect). The survey state lives under `tavern/.guild_state/` so the
Spellcaster can resume partial surveys on reconnect.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Catalog loader ───────────────────────────────────────────────────────

_CATALOG_CACHE = {"data": None, "ts": 0.0}
_CATALOG_TTL = 300.0  # 5 min, then re-read — catalog is tiny


def load_service_catalog(path: Optional[str] = None) -> list[dict]:
    """Load `installer/remote_services.json` and return its `services` list.

    Cached for 5 minutes. The catalog is the source of truth for which
    applications the Spellcaster knows about (ComfyUI, SillyTavern,
    Kobold, Ollama, GIMP, Darktable, Resolve, Blender, Krita, Photoshop,
    ... whatever lands there). New services require no code change here
    — just an entry in the JSON.
    """
    now = time.time()
    if (_CATALOG_CACHE["data"] is not None
            and now - _CATALOG_CACHE["ts"] < _CATALOG_TTL):
        return list(_CATALOG_CACHE["data"])
    candidates = []
    if path:
        candidates.append(path)
    # Resolve relative to the repo root (two levels up from this file).
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.abspath(
        os.path.join(here, "..", "installer", "remote_services.json")))
    for p in candidates:
        if not p or not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            services = data.get("services") or []
            if isinstance(services, list):
                _CATALOG_CACHE["data"] = services
                _CATALOG_CACHE["ts"] = now
                return list(services)
        except Exception:
            continue
    return []


# ── Survey record model ──────────────────────────────────────────────────

@dataclass
class ServiceLocation:
    """One user-declared placement for a service."""
    key: str                          # "comfyui" / "sillytavern" / ...
    placement: str = "unknown"        # local | remote | not_installed | skip
    host: str = ""                    # hostname or IP when placement=remote
    port: int = 0                     # optional override of default_port
    antenna_port: int = 7334          # where the Antenna daemon listens
    verified: bool = False            # True after a successful probe
    last_probe_ts: Optional[float] = None
    last_probe_error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def default_placement_for(service: dict, localhost_reachable: bool) -> str:
    """Seed the survey with a sensible default — 'local' if the service
    answers on localhost, 'unknown' otherwise.

    Keeps the user from having to re-declare obvious stuff. The scaffold
    still confirms each placement verbally before committing.
    """
    if localhost_reachable:
        return "local"
    return "unknown"


# ── Persistence ──────────────────────────────────────────────────────────

_SURVEY_LOCK = threading.Lock()


def _survey_path() -> str:
    # Mirror the LoRA / activation registries: under tavern/.guild_state/ when
    # the Guild is running, else next to this file (test runs).
    try:
        import tavern.server as _gs  # type: ignore
        sd = getattr(_gs, "_STATE_DIR", None)
        if sd:
            return os.path.join(sd, "network_survey.json")
    except Exception:
        pass
    return os.path.join(os.path.dirname(__file__), "network_survey.json")


def load_survey() -> dict[str, ServiceLocation]:
    p = _survey_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    out: dict[str, ServiceLocation] = {}
    for k, v in (raw.get("services") or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            out[k] = ServiceLocation(**{**v, "key": k})
        except TypeError:
            # Tolerate unknown fields from future schema versions.
            pass
    return out


def save_survey(locations: dict[str, ServiceLocation]) -> None:
    p = _survey_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    payload = {
        "version":  1,
        "updated":  time.time(),
        "services": {k: v.to_dict() for k, v in locations.items()},
    }
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


# ── Probe helpers ────────────────────────────────────────────────────────

def probe_localhost(service: dict, timeout: float = 1.5) -> tuple[bool, str]:
    """Is the service answering on localhost?"""
    port = service.get("default_port") or 0
    if not port:
        return (False, "no default port")
    url = f"http://127.0.0.1:{port}{service.get('probe_path', '/')}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return (resp.status < 500, f"http {resp.status}")
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}"[:120])


def probe_remote(host: str, service: dict,
                 port: Optional[int] = None,
                 timeout: float = 3.0) -> tuple[bool, str]:
    """Is the service answering on `host`?"""
    if not host:
        return (False, "no host")
    p = int(port or service.get("default_port") or 0)
    if not p:
        return (False, "no port for this service")
    url = f"http://{host}:{p}{service.get('probe_path', '/')}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return (resp.status < 500, f"http {resp.status}")
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}"[:120])


def probe_antenna(host: str, antenna_port: int = 7334,
                  timeout: float = 3.0) -> tuple[bool, str, dict]:
    """Probe a Spellcaster Antenna daemon's /status endpoint.

    Returns (ok, message, inventory) where `inventory` is the antenna's
    own service detection list, which we cross-reference against the
    user's survey to catch "user said GIMP is on this host but the antenna
    doesn't see GIMP installed."
    """
    if not host:
        return (False, "no host", {})
    url = f"http://{host}:{int(antenna_port)}/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        return (True, "reachable", body)
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}"[:120], {})


def probe_all(survey: dict[str, ServiceLocation],
              catalog: list[dict]) -> dict[str, ServiceLocation]:
    """Run the appropriate probe for every entry in `survey`.

    - placement=local         → probe_localhost
    - placement=remote        → probe_remote + probe_antenna
    - placement=not_installed → skip
    - placement=skip          → skip
    - placement=unknown       → auto-check localhost; if present, mark local.

    Survey records are mutated in place with verified / last_probe_* fields
    updated. Returns the same dict for caller convenience.
    """
    by_key = {s.get("key"): s for s in catalog}
    now = time.time()
    for key, loc in survey.items():
        svc = by_key.get(key)
        if not svc:
            loc.last_probe_error = f"unknown service key {key!r}"
            loc.verified = False
            loc.last_probe_ts = now
            continue
        if loc.placement in ("not_installed", "skip"):
            loc.verified = False
            loc.last_probe_ts = now
            loc.last_probe_error = ""
            continue
        if loc.placement == "unknown":
            ok, msg = probe_localhost(svc)
            if ok:
                loc.placement = "local"
                loc.verified = True
                loc.last_probe_error = ""
            else:
                loc.verified = False
                loc.last_probe_error = msg
        elif loc.placement == "local":
            ok, msg = probe_localhost(svc)
            loc.verified = ok
            loc.last_probe_error = "" if ok else msg
        elif loc.placement == "remote":
            ok_a, msg_a, _inv = probe_antenna(loc.host, loc.antenna_port)
            ok_s, msg_s = probe_remote(loc.host, svc, loc.port or None)
            loc.verified = bool(ok_a and ok_s)
            if not ok_a:
                loc.last_probe_error = f"antenna: {msg_a}"
            elif not ok_s:
                loc.last_probe_error = f"service: {msg_s}"
            else:
                loc.last_probe_error = ""
        loc.last_probe_ts = now
    return survey


# ── Public survey API (used by Guild endpoints) ──────────────────────────

def get_survey_state() -> dict:
    """Return a UI-friendly snapshot: catalog + current placements.

    Shape:
      {
        "catalog":  [ {key, label, default_port, probe_path, description} ],
        "survey":   { key: {placement, host, port, verified, ...} },
        "ready":    bool — True iff every service is either placed+verified
                           or explicitly skipped.
      }
    """
    catalog = load_service_catalog()
    with _SURVEY_LOCK:
        survey = load_survey()
    # Seed missing entries so the UI shows every known service up-front.
    for svc in catalog:
        k = svc.get("key")
        if k and k not in survey:
            survey[k] = ServiceLocation(key=k, placement="unknown")
    ready = all(
        (s.placement in ("not_installed", "skip")) or s.verified
        for s in survey.values()
    )
    return {
        "catalog": [{
            "key":          s.get("key"),
            "label":        s.get("label"),
            "description":  s.get("description", ""),
            "default_port": s.get("default_port"),
            "probe_path":   s.get("probe_path", "/"),
        } for s in catalog],
        "survey": {k: v.to_dict() for k, v in survey.items()},
        "ready":  ready,
    }


def declare_placement(key: str, placement: str,
                      host: str = "", port: int = 0,
                      antenna_port: int = 7334) -> dict:
    """User says "ComfyUI is on this host" / "GIMP is local" / "skip Kobold".

    Persists + probes the newly-declared entry, returns the verified record.
    """
    if placement not in ("local", "remote", "not_installed", "skip", "unknown"):
        raise ValueError(f"invalid placement {placement!r}")
    with _SURVEY_LOCK:
        survey = load_survey()
        loc = survey.get(key) or ServiceLocation(key=key)
        loc.placement = placement
        loc.host = host
        loc.port = int(port or 0)
        loc.antenna_port = int(antenna_port or 7334)
        loc.verified = False
        loc.last_probe_error = ""
        loc.last_probe_ts = None
        survey[key] = loc
        # Probe immediately so the user sees pass/fail right away.
        probe_all({key: loc}, load_service_catalog())
        save_survey(survey)
    return loc.to_dict()


def refresh_all_probes() -> dict:
    """Re-probe every entry — user clicked 'verify everything again'."""
    with _SURVEY_LOCK:
        survey = load_survey()
        probe_all(survey, load_service_catalog())
        save_survey(survey)
    return get_survey_state()


__all__ = [
    "ServiceLocation",
    "load_service_catalog",
    "load_survey",
    "save_survey",
    "probe_localhost",
    "probe_remote",
    "probe_antenna",
    "probe_all",
    "get_survey_state",
    "declare_placement",
    "refresh_all_probes",
]
