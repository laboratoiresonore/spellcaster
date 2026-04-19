"""GET /telemetry — structured antenna snapshot for Guild/fleet dashboards.

Pattern borrowed from Spellcaster's `/api/antenna/telemetry` endpoint
(launch/spellcaster_antenna.py) so Spellcaster's antenna emits snapshots
compatible with any FleetTelemetry-shaped consumer.

Schema:

    {
      "antenna_id": "hostname_ip",
      "timestamp": 1776593..,
      "cpu_percent": 21.4,
      "ram_percent": 48.2,
      "ram_used_mb": 7840,
      "disk_free_gb": 112.3,
      "gpu_util_percent": 68,
      "gpu_temp_c": 64,
      "vram_used_mb": 9100,
      "vram_total_mb": 16000,
      "services": {
        "comfyui": {"active": true, "port": 8188,
                     "extra": {"queue_pending": 2, "queue_running": 1,
                               "vram_used_mb": 9100}},
        ...
      }
    }

Design notes:
  - psutil and nvidia-smi are both optional — the snapshot degrades
    gracefully when they're unavailable (returns zeros in those fields).
  - ComfyUI queue depth is read from its /prompt endpoint; Kobold's
    token-per-second from /api/extra/perf.
  - The endpoint is stateless — no history is kept here. History is
    the consumer's job (the Guild's capabilities cache can poll
    /telemetry at whatever interval it wants).
  - Cheap: capped at ~3s worst-case (nvidia-smi timeout) so fleet
    dashboards can poll every 5-10s without drowning the antenna.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _cpu_ram_snapshot() -> dict[str, Any]:
    """Fill cpu/ram/disk via psutil when available."""
    out = {"cpu_percent": 0.0, "ram_percent": 0.0, "ram_used_mb": 0,
            "disk_free_gb": 0.0}
    try:
        import psutil  # type: ignore
    except ImportError:
        return out
    try:
        out["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        out["ram_percent"] = mem.percent
        out["ram_used_mb"] = int(mem.used / 1048576)
        # Use system drive on Windows, root on POSIX
        drive = "C:\\" if sys.platform.startswith("win") else "/"
        disk = psutil.disk_usage(drive)
        out["disk_free_gb"] = round(disk.free / 1073741824, 1)
    except Exception:
        pass
    return out


def _gpu_snapshot() -> dict[str, Any]:
    """Fill gpu_util/temp/vram via nvidia-smi when available. Reports
    primary (first) GPU only — multi-GPU hosts would need a richer schema.
    """
    out = {"gpu_util_percent": 0.0, "gpu_temp_c": 0.0,
            "vram_used_mb": 0, "vram_total_mb": 0,
            "gpu_name": ""}
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,temperature.gpu,"
             "memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return out
    if result.returncode != 0 or not result.stdout.strip():
        return out
    # First line = primary GPU
    parts = [p.strip() for p in result.stdout.splitlines()[0].split(",")]
    if len(parts) < 5:
        return out
    try:
        out["gpu_name"] = parts[0]
        out["gpu_util_percent"] = float(parts[1])
        out["gpu_temp_c"] = float(parts[2])
        out["vram_used_mb"] = int(parts[3])
        out["vram_total_mb"] = int(parts[4])
    except (ValueError, IndexError):
        pass
    return out


def _comfyui_queue_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    """Pull /prompt from the resolved ComfyUI URL.

    ComfyUI's /prompt endpoint returns queue counters:
        {"exec_info": {"queue_remaining": N}}
    Older builds return {"queue_running": [...], "queue_pending": [...]}
    under /queue — we try both.
    """
    out = {"queue_pending": 0, "queue_running": 0, "reachable": False}
    try:
        from .endpoints.comfyui import _resolve_comfyui_url
        url = _resolve_comfyui_url(cfg)
    except Exception:
        url = cfg.get("comfyui_url")
    if not url:
        return out

    def _fetch_json(path: str, timeout: float = 1.5):
        try:
            req = urllib.request.Request(
                url.rstrip("/") + path,
                headers={"User-Agent": "spellcaster-antenna-telemetry"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, urllib.error.HTTPError,
                OSError, json.JSONDecodeError, TimeoutError):
            return None

    # /prompt returns queue_remaining
    prompt_info = _fetch_json("/prompt")
    if isinstance(prompt_info, dict):
        out["reachable"] = True
        exec_info = prompt_info.get("exec_info") or {}
        out["queue_pending"] = int(exec_info.get("queue_remaining", 0))

    # /queue returns running + pending lists
    queue_info = _fetch_json("/queue")
    if isinstance(queue_info, dict):
        out["reachable"] = True
        if "queue_running" in queue_info:
            out["queue_running"] = len(queue_info.get("queue_running") or [])
        if "queue_pending" in queue_info:
            out["queue_pending"] = max(
                out["queue_pending"],
                len(queue_info.get("queue_pending") or []))
    return out


def _kobold_perf_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    """Pull /api/extra/perf for tokens-per-second and context usage."""
    out = {"tok_per_sec": 0.0, "context_used": 0, "context_max": 0,
            "reachable": False}
    port = int(cfg.get("kobold_port", 5001) or 5001)
    url = f"http://127.0.0.1:{port}/api/extra/perf"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "spellcaster-antenna-telemetry"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            perf = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            OSError, json.JSONDecodeError, TimeoutError):
        return out
    if isinstance(perf, dict):
        out["reachable"] = True
        out["tok_per_sec"] = float(perf.get("idle_speed",
                                              perf.get("last_token_per_second", 0.0)))
        out["context_used"] = int(perf.get("last_process_tokens", 0))
        out["context_max"] = int(perf.get("max_context_length", 0))
    return out


def collect_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    """Build a full telemetry snapshot. Safe for concurrent calls — all
    data sources are independent subprocess/HTTP calls with timeouts."""
    hostname = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        ip = "127.0.0.1"
    antenna_id = (f"{hostname}_{ip}".replace(".", "_")
                  .replace(" ", "_").lower())

    snap: dict[str, Any] = {
        "antenna_id": antenna_id,
        "hostname": hostname,
        "ip": ip,
        "timestamp": time.time(),
    }
    snap.update(_cpu_ram_snapshot())
    snap.update(_gpu_snapshot())

    # Per-service blocks — only include services that are declared
    declared = list(cfg.get("services") or [])
    services: dict[str, Any] = {}
    if "comfyui" in declared:
        cu = _comfyui_queue_snapshot(cfg)
        services["comfyui"] = {
            "active": cu["reachable"],
            "port": int(cfg.get("comfyui_port", 8188)),
            "extra": {
                "queue_pending": cu["queue_pending"],
                "queue_running": cu["queue_running"],
            },
        }
    if "kobold" in declared:
        kb = _kobold_perf_snapshot(cfg)
        services["kobold"] = {
            "active": kb["reachable"],
            "port": int(cfg.get("kobold_port", 5001)),
            "extra": {
                "tok_per_sec": kb["tok_per_sec"],
                "context_used": kb["context_used"],
                "context_max": kb["context_max"],
            },
        }
    if "ollama" in declared:
        services["ollama"] = {
            "active": True,  # no cheap probe; assume declared = live
            "port": int(cfg.get("ollama_port", 11434)),
            "extra": {},
        }
    if "resolve" in declared:
        services["resolve"] = {
            "active": True,
            "extra": {"note": "scripting-API-driven; no passive metrics"},
        }
    snap["services"] = services
    return snap
