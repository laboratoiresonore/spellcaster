"""Prometheus link — antenna → Prometheus fleet-frame `/api/heartbeat`.

Purpose
-------
Separate from `heartbeat.py` (which targets the Wizard Guild). This
module advertises the antenna's existence to the Prometheus Fleet Frame
on the fleet's hub server, so the unified top-bar control plane can:

  1. Authorize browsers on this machine to view the frame (registry of
     "machines whose antenna has heartbeated recently").
  2. Render this machine's row of capability tabs — gray for installed
     but not running, colored for live.

The fleet frame is *separate* from the Guild. A spellcaster install
without Prometheus doesn't need this; an install plugged into a
prometheus-fleet topology benefits.

Heartbeat shape
---------------
  POST {prometheus_url}/api/heartbeat
  Body: {
    "hostname":         "theo",
    "tailnet_ip":       "100.101.223.17",
    "antenna_version":  "2.3",
    "antenna_port":     7334,
    "bearer_token":     "...",
    "services_detected": { "comfyui": {"installed": true, "evidence": "..."}, ... }
  }

Design notes
------------
  * Stdlib only. Self-signed Prometheus cert is tolerated (verify=False)
    because tailnet topology is the trust boundary.
  * On-disk config knob: cfg["prometheus_url"]. Empty string = disabled.
    Default left empty so non-fleet installs incur zero outbound traffic.
  * Cycle interval: 5 s (matches fleet-frame's HEARTBEAT_TTL_S = 30 s with
    plenty of safety margin).
  * Token is sent in the body, not the Authorization header — the Frame
    stores per-host antenna tokens for outbound action calls. We treat
    Tailscale source IP as proof of host identity at the network layer;
    the bearer-token in the body is what Prometheus replays back later.
"""
from __future__ import annotations

import json
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from . import _silent


HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TIMEOUT = 4.0


def _guess_prometheus_url(cfg: dict[str, Any]) -> str | None:
    url = cfg.get("prometheus_url", "")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def _tailnet_ip() -> str:
    """Best-effort tailnet IP detection.

    Tries `tailscale ip -4` first; falls back to the outbound-route trick.
    """
    try:
        import subprocess  # for TimeoutExpired etc.
        r = _silent.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=2.0,
        )
        if r.returncode == 0:
            ip = (r.stdout or "").strip().splitlines()
            if ip and ip[0].startswith("100."):
                return ip[0]
    except Exception:
        # Was catching only (FileNotFoundError, OSError). A
        # subprocess.TimeoutExpired (raised when `tailscale ip -4` hangs
        # because the daemon is stuck/restarting) used to escape and kill
        # the entire prometheus-link thread. Catch broadly so the
        # heartbeat keeps running off the fallback IP.
        pass
    # Fallback: outbound-route IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        out = s.getsockname()[0]
        s.close()
        return out
    except OSError:
        return "127.0.0.1"


def _detected_services(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Reuse the same detection pipeline as `endpoints/status.status()`.

    Defensive: detection must never crash the heartbeat thread.
    """
    try:
        import os
        import sys as _sys
        from . import detect as _detect
        _repo_root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..",
        ))
        if _repo_root not in _sys.path:
            _sys.path.insert(0, _repo_root)
        from installer import remote_services as _rs  # type: ignore
        registry = _rs.load_services()
        return _detect.detect_installed_services(registry) or {}
    except Exception:
        return {}


def _collect_telemetry(cfg: dict[str, Any]) -> dict[str, Any]:
    """Reuse antenna.telemetry.collect_snapshot — gracefully degrades when
    psutil/nvidia-smi aren't available. Wrapped in a broad try so the
    heartbeat thread never crashes on a sensor hiccup.
    """
    try:
        from . import telemetry as _tel
        snap = _tel.collect_snapshot(cfg) or {}
        # Add Windows-side uptime since collect_snapshot doesn't include it.
        snap.setdefault("uptime_s", _uptime_s())
        return snap
    except Exception:
        return {"uptime_s": _uptime_s()}


def _uptime_s() -> float:
    """Cross-platform best-effort uptime in seconds."""
    try:
        import time as _t
        # Linux/macOS: /proc/uptime first
        try:
            with open("/proc/uptime", "r") as f:
                return float(f.read().split()[0])
        except OSError:
            pass
        # Windows: GetTickCount64 via ctypes
        if sys.platform == "win32":
            import ctypes
            return ctypes.windll.kernel32.GetTickCount64() / 1000.0
        # Fallback: time since boot via psutil if present
        try:
            import psutil  # type: ignore
            return _t.time() - psutil.boot_time()
        except Exception:
            return 0.0
    except Exception:
        return 0.0


def _build_payload(cfg: dict[str, Any], token: str) -> dict[str, Any]:
    return {
        "hostname": socket.gethostname().lower(),
        "tailnet_ip": _tailnet_ip(),
        "antenna_version": _antenna_version(),
        "antenna_port": int(cfg.get("port", 7334)),
        "bearer_token": token,
        "services_detected": _detected_services(cfg),
        "telemetry": _collect_telemetry(cfg),
    }


def _antenna_version() -> str:
    try:
        from . import __version__
        return str(__version__)
    except Exception:
        return "?"


def _read_token(cfg: dict[str, Any]) -> str:
    import os
    p = cfg.get("token_path") or ""
    if not p:
        return ""
    try:
        with open(os.path.expanduser(p), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _post(url: str, payload: dict[str, Any]) -> bool:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/heartbeat",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"spellcaster-antenna/{_antenna_version()} prometheus-link",
        },
        method="POST",
    )
    # Prometheus fleet frame may use a self-signed cert at the tailnet
    # boundary; trust the tailnet, accept the cert.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=HEARTBEAT_TIMEOUT, context=ctx) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError,
            socket.timeout, OSError, ssl.SSLError):
        return False


class _LinkThread(threading.Thread):
    def __init__(self, cfg: dict[str, Any], url: str):
        super().__init__(daemon=True, name="antenna-prometheus-link")
        self.cfg = cfg
        self.url = url
        self._stop_event = threading.Event()
        self._consecutive_failures = 0
        self._logged_first_success = False

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._cycle()
            except Exception as e:
                # Defensive: any unhandled exception inside _cycle() (sensor
                # hiccup, sudden DNS failure, transient OSError on Windows,
                # etc.) must NOT kill the heartbeat loop. Log once per
                # consecutive run of the same exception class.
                cls = type(e).__name__
                if getattr(self, "_last_exc_cls", None) != cls:
                    print(f"[prometheus-link] cycle error ({cls}): {e}",
                          file=sys.stderr, flush=True)
                    self._last_exc_cls = cls
            self._stop_event.wait(HEARTBEAT_INTERVAL)

    def _cycle(self) -> None:
        token = _read_token(self.cfg)
        payload = _build_payload(self.cfg, token)
        ok = _post(self.url, payload)
        if ok:
            if self._consecutive_failures > 0 or not self._logged_first_success:
                print(f"[prometheus-link] → {self.url} OK",
                      file=sys.stderr, flush=True)
                self._logged_first_success = True
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1 or self._consecutive_failures % 60 == 0:
                # 1st failure, then every 5 min (60 × 5 s)
                print(f"[prometheus-link] unreachable "
                      f"({self._consecutive_failures}x): {self.url}",
                      file=sys.stderr, flush=True)


_THREAD: _LinkThread | None = None


def current_state() -> dict[str, Any]:
    """For inclusion in /status — lets operators verify the link from a curl."""
    if _THREAD is None:
        return {"enabled": False, "url": None}
    return {
        "enabled": True,
        "url": _THREAD.url,
        "consecutive_failures": _THREAD._consecutive_failures,
        "last_cycle_ok": _THREAD._consecutive_failures == 0,
        "interval_seconds": HEARTBEAT_INTERVAL,
    }


def start(cfg: dict[str, Any]) -> None:
    """Spawn the daemon if cfg['prometheus_url'] is set. Idempotent."""
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():
        return
    url = _guess_prometheus_url(cfg)
    if not url:
        # Non-fleet install — silent disable. No noise.
        return
    _THREAD = _LinkThread(cfg, url)
    _THREAD.start()
    print(f"[prometheus-link] started → {url} every {HEARTBEAT_INTERVAL:.0f}s",
          file=sys.stderr, flush=True)


def stop() -> None:
    if _THREAD is not None:
        _THREAD.stop()
