"""Heartbeat client — antenna → Mega Bridge `/api/interfaces/heartbeat`.

Purpose
-------
The Wizard Guild maintains a live registry of interfaces (GIMP, Resolve,
Darktable, ...) that renders as green-dot chips in the sidebar. An
interface stays visible while heartbeats arrive; after a short TTL
without one, it disappears (no dead click targets).

This module lets a remote antenna advertise each service it hosts as
its own interface chip in the Guild, so a user running Spellcaster at
home sees:

  - local: GIMP ●       (heartbeat from their own GIMP plugin)
  - local: Darktable ●
  - remote (<hostname>): ComfyUI ●   (heartbeat from antenna on the LAN)
  - remote (Theo): Ollama ●

Namespacing
-----------
We heartbeat with BARE interface keys (`comfyui`, `ollama`, `resolve`)
that match the Guild's KNOWN_INTERFACES registry. The namespaced form
(`antenna.<svc>`) was considered, but:

1. The registry is a fixed allowlist — adding `antenna.<svc>` would
   require coordinated edits in spellcaster_core/interface_registry.py,
   owned by the Mega Bridge lane.
2. Using bare keys keeps the sidebar chip rendering uniform regardless
   of local vs remote.
3. Origin-machine info is preserved in `meta.source_antenna` and
   `meta.machine`, so a consumer that cares about routing ("send this
   to the remote ComfyUI, not a hypothetical local one") can still
   filter by meta.

The tradeoff: if two machines on the same LAN both run the same
service, the registry shows one chip whose last_meta reflects
whichever heartbeated most recently. Fine for single-remote setups.
Sharding by machine is roadmap item "per-remote separation" (deferred).

Lifecycle
---------
`start(cfg)` spawns a daemon thread that posts every HEARTBEAT_INTERVAL
seconds. Thread exits when the agent exits (daemon=True). Errors are
swallowed and retried — a flaky Guild shouldn't crash the antenna.

Bridge protocol contract
------------------------
The Mega Bridge team may evolve the `/api/interfaces/heartbeat`
request/response shape. This module sends what the Round 1 spec
documented:

  POST {hub_url}/api/interfaces/heartbeat
  Body: {
    "interface": "antenna.comfyui",
    "meta": { ... service-specific ... }
  }

If the shape changes, update _build_payload() only — everything else
(polling interval, error handling, thread management) stays the same.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any


# Seconds between heartbeats. Mega Bridge TTL is ~30s (per Round 1
# summary) — we ping at 10s for responsive disappearance on agent-quit
# without being chatty.
HEARTBEAT_INTERVAL = 10.0
HEARTBEAT_TIMEOUT = 5.0


def _guess_hub_url(cfg: dict[str, Any]) -> str | None:
    """Determine where to heartbeat. Priority:
       1. cfg["hub_url"]  (set by installer-generated antenna.bat)
       2. None — heartbeat disabled (logs once, keeps serving locally)
    """
    hub = cfg.get("hub_url", "").strip() if isinstance(cfg.get("hub_url"), str) else ""
    return hub or None


def _probe_comfyui(url: str) -> dict[str, Any]:
    """Quick ComfyUI probe — same shape as endpoints/status._probe_comfyui
    but defensive for use from the heartbeat thread (no stack traces on
    errors, all failures → reachable:false).
    """
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/system_stats")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        devices = data.get("devices") or []
        if not devices:
            return {"reachable": True}
        dev = devices[0]
        vram_total = dev.get("vram_total") or 0
        vram_free = dev.get("vram_free") or 0
        return {
            "reachable": True,
            "gpu_name": dev.get("name", ""),
            "vram_total_gb": round(vram_total / (1024 ** 3), 1),
            "vram_free_gb": round(vram_free / (1024 ** 3), 1),
        }
    except Exception:
        return {"reachable": False}


_FRONTEND_INTERFACES = {"gimp", "darktable", "resolve", "sillytavern"}


def _build_payloads(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the heartbeat payload(s) for this cycle.

    Strategy:
      1. One `antenna` heartbeat per cycle — represents the remote box as
         a single first-class interface chip in the Guild. Meta carries
         the full per-service state (machine, services, agent_url, vitals).
      2. For any declared service that ALSO happens to be a user-facing
         frontend (gimp, darktable, resolve, sillytavern), send a second
         heartbeat under that key with `remote=true` + `source_antenna`
         so the native chip also lights up with remote-origin attribution.

    Why NOT heartbeat per-backend-service (comfyui/kobold/ollama) as
    their own interface keys: the Guild's KNOWN_INTERFACES registry
    only accepts frontends. Backend services live inside the antenna's
    meta and are surfaced via /api/interfaces.antenna.last_meta.services.
    """
    hostname = socket.gethostname()
    # Detect LAN IP the same way config.py does
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        ip = "127.0.0.1"

    agent_port = cfg.get("port", 7334)
    agent_url = f"https://{ip}:{agent_port}"
    services = cfg.get("services", [])

    # Build per-service vital snapshots (embedded in the antenna meta)
    services_detail: dict[str, dict[str, Any]] = {}
    for svc in services:
        if svc == "comfyui":
            services_detail[svc] = _probe_comfyui(cfg.get("comfyui_url", ""))
        elif svc in ("llm", "kobold", "ollama"):
            services_detail[svc] = {"reachable": True}  # optimistic
        else:
            services_detail[svc] = {"declared": True}

    antenna_meta: dict[str, Any] = {
        "machine": hostname,
        "ip": ip,
        "agent_url": agent_url,
        "services": services,
        "services_detail": services_detail,
        "remote": True,
    }

    payloads: list[dict[str, Any]] = [
        {"interface": "antenna", "meta": antenna_meta},
    ]

    # For any service that's a native frontend interface, also heartbeat
    # under its bare key so the sidebar chip for that frontend lights up
    # with remote-origin attribution.
    for svc in services:
        if svc in _FRONTEND_INTERFACES:
            frontend_meta = {
                "machine": hostname,
                "ip": ip,
                "agent_url": agent_url,
                "source_antenna": agent_url,
                "remote": True,
            }
            payloads.append({"interface": svc, "meta": frontend_meta})

    return payloads


def _send_one(hub_url: str, payload: dict[str, Any]) -> bool:
    """POST one heartbeat. Returns True on 2xx, False otherwise."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{hub_url.rstrip('/')}/api/interfaces/heartbeat",
        data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "spellcaster-antenna-heartbeat"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HEARTBEAT_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError,
            socket.timeout, OSError):
        return False


class _HeartbeatThread(threading.Thread):
    """Daemon thread that posts heartbeats every HEARTBEAT_INTERVAL seconds.

    One thread per agent process, regardless of how many services are
    declared — we batch all service heartbeats inside one cycle so
    they arrive at the Guild within milliseconds of each other.
    """

    def __init__(self, cfg: dict[str, Any], hub_url: str):
        super().__init__(daemon=True, name="antenna-heartbeat")
        self.cfg = cfg
        self.hub_url = hub_url
        self._stop_event = threading.Event()
        # Track consecutive failures so we back off + log less often
        self._consecutive_failures = 0
        self._logged_first_success = False

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._cycle()
            # Sleep with wake-on-stop support so shutdown is snappy
            self._stop_event.wait(HEARTBEAT_INTERVAL)

    def _cycle(self) -> None:
        payloads = _build_payloads(self.cfg)
        if not payloads:
            return
        all_ok = True
        for p in payloads:
            if not _send_one(self.hub_url, p):
                all_ok = False

        if all_ok:
            if self._consecutive_failures > 0 or not self._logged_first_success:
                print(f"[heartbeat] → {self.hub_url} "
                      f"({len(payloads)} service(s)) OK",
                      file=sys.stderr, flush=True)
                self._logged_first_success = True
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            # Log on 1st failure, then every 30th (5 minutes at 10s interval)
            if self._consecutive_failures == 1 or self._consecutive_failures % 30 == 0:
                print(f"[heartbeat] hub unreachable "
                      f"({self._consecutive_failures}x consecutive failures): "
                      f"{self.hub_url}",
                      file=sys.stderr, flush=True)


# Module-level singleton so agent.py doesn't need to track it
_THREAD: _HeartbeatThread | None = None


def current_state() -> dict[str, Any]:
    """Return a snapshot of heartbeat state for /status.

    Lets operators verify from the antenna's /status whether heartbeats
    are flowing — useful when debugging "remote service doesn't appear
    in the Guild sidebar" (is the antenna trying? is the hub reachable?).
    """
    if _THREAD is None:
        return {"enabled": False, "hub_url": None}
    return {
        "enabled": True,
        "hub_url": _THREAD.hub_url,
        "consecutive_failures": _THREAD._consecutive_failures,
        "last_cycle_ok": _THREAD._consecutive_failures == 0,
        "interval_seconds": HEARTBEAT_INTERVAL,
    }


def start(cfg: dict[str, Any]) -> None:
    """Start the heartbeat thread if cfg['hub_url'] is set. Idempotent."""
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():
        return
    hub_url = _guess_hub_url(cfg)
    if not hub_url:
        # Antenna without a hub is fine — it still serves /status to
        # whoever curls it. Just don't heartbeat.
        print("[heartbeat] no hub_url configured — heartbeats disabled",
              file=sys.stderr, flush=True)
        return
    _THREAD = _HeartbeatThread(cfg, hub_url)
    _THREAD.start()
    print(f"[heartbeat] started → {hub_url} every {HEARTBEAT_INTERVAL:.0f}s",
          file=sys.stderr, flush=True)


def stop() -> None:
    """Signal the heartbeat thread to exit at the next cycle boundary."""
    if _THREAD is not None:
        _THREAD.stop()
