"""GET /  and  GET /status — liveness and detailed status.

`/` is the unauthenticated liveness probe — minimal JSON, no secrets,
meant for "is there an antenna on this host at all" discovery. Clients
use it during LAN scans before they have a token.

`/status` is authenticated and richer: version, uptime, configured
services, and — for each declared service — its current reachability
and vital stats. This is what the client uses to build its picture of
a multi-machine setup ("Machine A has llm, Machine B has comfyui+resolve").

Security
--------
`/` MUST NOT leak anything identifying about the host. Hostname, LAN
IP, and user path are all withheld. Only: `{"service": "spellcaster-antenna",
"version": "X.Y.Z"}`.

`/status` CAN leak more since the client has already proven it holds the
token. We still keep paths relative (config/log/token file names without
the full home dir) to avoid handing attackers the user's username.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import __version__, heartbeat
from .. import detect as _detect

# Lazy import of the installer's service registry loader — it lives in
# `installer/remote_services.py` but is fetched at runtime from GitHub
# (with baked fallback) so it's always current.
try:
    import sys as _sys
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                               "..", ".."))
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)
    from installer import remote_services as _remote_services  # type: ignore
except ImportError:
    _remote_services = None


# Epoch when the agent started, set lazily on first call. Accurate
# enough — drift between module import and first request is sub-second.
_PROCESS_START = time.time()


def liveness(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET / — unauthenticated liveness probe.

    Clients call this first during LAN discovery before they have a token.
    Deliberately minimal — exposes only what's needed to confirm "yes,
    there's a Spellcaster antenna here, same protocol version as me."
    """
    return 200, {
        "service": "spellcaster-antenna",
        "version": __version__,
        "protocol": 1,
    }


def _probe_comfyui(url: str, timeout: float = 2.0) -> dict[str, Any]:
    """Query ComfyUI's /system_stats. Returns a summary dict (always, may be empty)."""
    out: dict[str, Any] = {"reachable": False, "url": url}
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/system_stats")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        devices = data.get("devices") or []
        if devices:
            dev = devices[0]
            vram_total = dev.get("vram_total") or 0
            vram_free = dev.get("vram_free") or 0
            out.update({
                "reachable": True,
                "gpu_name": dev.get("name", "unknown"),
                "vram_total_gb": round(vram_total / (1024 ** 3), 1),
                "vram_free_gb": round(vram_free / (1024 ** 3), 1),
            })
        else:
            out["reachable"] = True  # Reachable but no GPU reported
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, socket.timeout, OSError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _probe_llm(engine: str, url: str, timeout: float = 2.0) -> dict[str, Any]:
    """Query the LLM backend (Kobold/Ollama) for liveness."""
    out: dict[str, Any] = {"reachable": False, "engine": engine, "url": url}
    if not engine or not url:
        return out
    # Endpoint varies per engine
    probe_path = {
        "koboldcpp": "/api/v1/model",
        "ollama":    "/api/tags",
    }.get(engine, "/")
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}{probe_path}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read(1024)  # just confirm we got bytes back
        out["reachable"] = True
    except (urllib.error.URLError, urllib.error.HTTPError,
            socket.timeout, OSError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def status(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /status — authenticated detailed status.

    Returns a JSON object the client can use to render a full picture of
    this machine: what services it advertises, what's actually reachable
    right now, and how long it's been running.
    """
    cfg = ctx["config"]
    services_declared: list[str] = cfg.get("services", [])
    services_detail: dict[str, dict] = {}

    if "comfyui" in services_declared:
        services_detail["comfyui"] = _probe_comfyui(cfg.get("comfyui_url", ""))
    if "llm" in services_declared:
        services_detail["llm"] = _probe_llm(
            cfg.get("llm_engine", ""), cfg.get("llm_url", ""))
    if "resolve" in services_declared:
        # Placeholder until Phase 4 builds the Resolve bridge
        services_detail["resolve"] = {
            "reachable": False, "note": "resolve service module not yet built"}

    uptime_seconds = int(time.time() - _PROCESS_START)

    # Auto-detect all Spellcaster-compatible services present on this
    # machine, not just the ones this antenna was configured to advertise.
    # Operators can use this to discover "oh, Darktable is installed here,
    # should I add it to my antenna's services list?"
    services_detected: dict[str, dict] = {}
    if _remote_services is not None:
        try:
            registry = _remote_services.load_services()
            services_detected = _detect.detect_installed_services(registry)
        except Exception as e:  # noqa: BLE001 — detection must never fail status
            services_detected = {"_error": {"installed": False,
                                             "evidence": f"detect failed: {e}"}}

    return 200, {
        "service": "spellcaster-antenna",
        "version": __version__,
        "protocol": 1,
        "uptime_seconds": uptime_seconds,
        "hostname": socket.gethostname(),
        "services_declared": services_declared,
        "services_detail": services_detail,
        "services_detected": services_detected,
        "rate_limit_rpm": cfg.get("rate_limit_rpm", 30),
        "heartbeat": heartbeat.current_state(),
        # Paths are returned as basenames only — full paths leak the user's
        # home dir path which attackers could use to guess usernames.
        "token_file": Path(os.path.expanduser(cfg["token_path"])).name,
        "log_file": Path(os.path.expanduser(cfg["log_path"])).name,
    }
