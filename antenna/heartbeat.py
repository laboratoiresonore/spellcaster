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
  - remote (Theo): ComfyUI ●     (heartbeat from antenna on <INTERNAL_HOST>)
  - remote (Theo): Ollama ●

Namespacing
-----------
Interface keys use `antenna.<service>` to stay distinct from local
services of the same name. Meta includes `machine`, `ip`, `service`,
and any service-specific vitals (VRAM, model count, etc.). The bridge
can then route cross-app events to the right machine:

  {kind: "comfyui.install-node.requested",
   data: {node_name: "...", target: "antenna.comfyui@<INTERNAL_HOST>"}}

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


def _build_payloads(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Build one heartbeat payload per declared service.

    A beefy box that hosts comfyui + ollama sends TWO heartbeats each
    cycle so both appear in the Guild sidebar independently. Lets users
    filter / click each one separately (e.g. "install node on this
    ComfyUI" without affecting Ollama state).
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

    payloads = []
    services = cfg.get("services", [])

    for svc in services:
        base_meta: dict[str, Any] = {
            "machine": hostname,
            "ip": ip,
            "service": svc,
            "agent_url": agent_url,   # how the bridge can reach us
        }

        # Service-specific vitals
        if svc == "comfyui":
            base_meta.update(_probe_comfyui(cfg.get("comfyui_url", "")))
        elif svc == "llm" or svc == "kobold" or svc == "ollama":
            # LLM liveness is cheap — skip for now to avoid adding another
            # probe every 10s. Can add later if the bridge needs it.
            base_meta["reachable"] = True  # optimistic; /status is authoritative

        payloads.append({
            "interface": f"antenna.{svc}",
            "meta": base_meta,
        })

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
