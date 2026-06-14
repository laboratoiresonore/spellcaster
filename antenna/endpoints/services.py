"""Generic service start/stop/logs endpoints for ComfyUI, Kobold, Ollama.

Thin wrapper around antenna/service_launcher.py — the heavy lifting
(launcher discovery, subprocess spawn, reachability poll) lives there.

    POST /service/start   {"service": "comfyui"}  # starts if not running
    GET  /service/logs?service=comfyui&tail=200   # tail the log
"""
from __future__ import annotations

from typing import Any

from .. import service_launcher as _sl


def start_service(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /service/start — idempotent. If already running, returns
    state="already_running" without spawning. If installed-but-offline,
    spawns and waits up to wait_s seconds for reachability."""
    body = ctx.get("body") or {}
    name = (body.get("service") or "").strip().lower()
    if name not in ("comfyui", "kobold", "ollama"):
        return 400, {"error": f"service must be one of comfyui/kobold/ollama, "
                               f"got {name!r}"}
    try:
        wait_s = float(body.get("wait_s", 30))
    except (TypeError, ValueError):
        wait_s = 30.0
    wait_s = max(1.0, min(120.0, wait_s))  # sane bounds
    cfg = dict(ctx.get("config") or {})
    # R56: accept one-shot path overrides from the request so the user
    # can tell the antenna where their install lives when auto-detection
    # misses. Accepted keys per service: root, launcher, port.
    if name == "comfyui":
        if body.get("root"):
            cfg["comfyui_root"] = body["root"]
        if body.get("launcher"):
            cfg["comfyui_launcher"] = body["launcher"]
        if body.get("port"):
            cfg["comfyui_port"] = body["port"]
    elif name == "kobold":
        if body.get("launcher"):
            cfg["kobold_launcher"] = body["launcher"]
        if body.get("model"):
            cfg["kobold_model"] = body["model"]
        if body.get("port"):
            cfg["kobold_port"] = body["port"]
    elif name == "ollama":
        if body.get("launcher"):
            cfg["ollama_launcher"] = body["launcher"]
    result = _sl.ensure_service_running(name, cfg, wait_s=wait_s)
    # Map state → HTTP status: success/idempotent 200; not installed 503;
    # timeouts/failures return 500 with full detail for the UI to show.
    state = result.get("state")
    if state in ("already_running", "started"):
        status = 200
    elif state == "not_installed":
        status = 503
    elif state == "unknown_service":
        status = 400
    else:
        status = 500
    return status, result


def register_service(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /service/register — persist a service launcher path into the
    antenna's config so future /service/start calls pick it up without
    needing one-shot overrides.

    Body:
      {"service": "comfyui",
       "launcher": "C:/tools/ComfyUI/launch_optimized.bat",
       "root": "C:/tools/ComfyUI",     # optional
       "port": 8188}                    # optional

    The Guild's "Connect an app" popover hits this via the paired
    antenna so the user can tell the antenna exactly where each app
    lives on that machine. Everything writes through config.save_config
    (atomic tempfile + replace) so a crash mid-write can't corrupt
    antenna_config.json.
    """
    body = ctx.get("body") or {}
    name = (body.get("service") or "").strip().lower()
    # Broader allowlist than /service/start — the user may register paths
    # for apps whose launch isn't orchestrated by the antenna yet (GIMP,
    # Darktable, Resolve, SillyTavern, Signal) so the Guild at least
    # knows where they live. Launcher paths for those still persist; the
    # Guild side decides what to do with them.
    #
    # Kobold supports multiple modes on one machine (RP chat, TTS/STT
    # voice). We treat each mode as its own service key (kobold_rp,
    # kobold_tts) so two KoboldCpp processes can coexist with their own
    # launcher + port, and the Guild's chip row renders one chip per
    # mode. See Item 4 of the sidebar rework.
    allowed = {"comfyui", "kobold", "kobold_rp", "kobold_tts", "ollama",
                "gimp", "darktable", "resolve",
                "sillytavern", "signal"}
    if name not in allowed:
        return 400, {"error": f"service must be one of {sorted(allowed)}, "
                               f"got {name!r}"}
    launcher = (body.get("launcher") or "").strip()
    if not launcher:
        return 400, {"error": "launcher path required"}
    try:
        from .. import config as _config
        cfg = _config.load_config()
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"config load failed: {e}"}
    # Legacy schema: services was a list of keys. Convert to dict so we
    # can store per-service overrides without breaking older consumers.
    raw = cfg.get("services") or {}
    if isinstance(raw, dict):
        services = dict(raw)
    elif isinstance(raw, list):
        services = {str(k): {} for k in raw if k}
    else:
        services = {}
    svc_entry = dict(services.get(name) or {})
    svc_entry["launcher"] = launcher
    if body.get("root"):
        svc_entry["root"] = str(body["root"]).strip()
    if body.get("port"):
        try:
            svc_entry["port"] = int(body["port"])
        except (TypeError, ValueError):
            pass
    services[name] = svc_entry
    cfg["services"] = services
    # Also mirror into the flat top-level keys service_launcher reads
    # (comfyui_launcher / kobold_launcher / ollama_launcher / etc.) so
    # start_service's override chain doesn't need to grow another
    # lookup path.
    flat_key = f"{name}_launcher"
    cfg[flat_key] = launcher
    if body.get("root"):
        cfg[f"{name}_root"] = str(body["root"]).strip()
    if body.get("port"):
        try:
            cfg[f"{name}_port"] = int(body["port"])
        except (TypeError, ValueError):
            pass
    try:
        _config.save_config(cfg)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"config save failed: {e}"}
    try:
        from .. import agent as _agent
        _agent.notify(f"{name} registered",
                       f"launcher: {launcher[:80]}", level="success")
    except Exception:  # noqa: BLE001
        pass
    return 200, {"ok": True, "service": name, "launcher": launcher,
                  "root": svc_entry.get("root"),
                  "port": svc_entry.get("port")}


_PORT_REAP_FALLBACK = {
    # Map service name -> default port we should port-reap if the
    # canonical service_launcher.stop_service has no handler. This lets
    # us kill services we never spawned (sillytavern, lmstudio, etc.)
    # by closing whatever process owns that port.
    "sillytavern": 8000,
    "lmstudio":    1234,
    "kobold_rp":   5001,
    "kobold_tts":  5002,
    "resolve":     0,
    "darktable":   0,
    "gimp":        0,
    "signal":      0,
}


def _port_reap(port: int) -> dict[str, Any]:
    """Best-effort: terminate any process owning the given TCP port."""
    if not port:
        return {"state": "no_port", "detail": "service has no canonical port"}
    import os
    if os.name == "nt":
        # Windows: netstat for the PID, then taskkill /F /PID
        import subprocess
        try:
            r = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=5,
            )
            pids: set[int] = set()
            for ln in r.stdout.splitlines():
                parts = ln.split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    local = parts[1]
                    if local.endswith(f":{port}"):
                        pids.add(int(parts[-1]))
            if not pids:
                return {"state": "not_running", "detail": f"nothing on :{port}"}
            killed = []
            failed = []
            for pid in pids:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   capture_output=True, timeout=5)
                    killed.append(pid)
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                    failed.append(pid)
            return {"state": "stopped" if killed else "failed",
                    "killed_pids": killed, "failed_pids": failed,
                    "detail": f"reaped :{port}"}
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            return {"state": "failed", "detail": f"{type(e).__name__}: {e}"}
    # POSIX fallback
    import subprocess
    try:
        r = subprocess.run(["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
                           capture_output=True, text=True, timeout=5)
        pids = [int(x) for x in r.stdout.split() if x.isdigit()]
        if not pids:
            return {"state": "not_running", "detail": f"nothing on :{port}"}
        for pid in pids:
            try:
                os.kill(pid, 15)  # SIGTERM
            except (ProcessLookupError, PermissionError):
                pass
        return {"state": "stopped", "killed_pids": pids,
                "detail": f"SIGTERM to {pids}"}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return {"state": "failed", "detail": f"{type(e).__name__}: {e}"}


def stop_service(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /service/stop — kill the child we launched (or port-reap).

    Supported service names:
      - comfyui / kobold / ollama — full launcher-managed stop via
        service_launcher.stop_service (graceful + tracked).
      - sillytavern / lmstudio / kobold_rp / kobold_tts — best-effort
        port reap (we never spawned them, but if they're sitting on
        their canonical port we'll kill the owner).
      - resolve / darktable / gimp / signal — no canonical TCP port;
        returns 400 with a clear "no stop path" message.
    """
    body = ctx.get("body") or {}
    name = (body.get("service") or "").strip().lower()
    cfg = ctx.get("config") or {}
    if name in ("comfyui", "kobold", "ollama"):
        try:
            result = _sl.stop_service(name, cfg)
        except Exception as e:  # noqa: BLE001
            return 500, {"error": f"stop failed: {type(e).__name__}: {e}"}
    elif name in _PORT_REAP_FALLBACK:
        port = cfg.get(f"{name}_port") or _PORT_REAP_FALLBACK[name]
        if not port:
            return 400, {"error": f"{name} has no stoppable TCP port; close "
                                   f"the app window manually"}
        result = _port_reap(int(port))
        if result.get("state") == "failed":
            return 500, result
    else:
        return 400, {"error": f"unknown service {name!r}"}
    # Notify the tray so the user sees the transition.
    try:
        from .. import agent as _agent
        _agent.notify(f"{name} stopped", f"state={result.get('state')}")
    except Exception:  # noqa: BLE001
        pass
    return 200, result


def detector_diag(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /diag/detector — R57 diagnostic: what did the service detector
    find on this machine, with which strategy, and what's in its cache?

    Surfaces the result of service_detector.detect_all(cfg) so users can
    troubleshoot "why doesn't auto-detect find my install?" without
    hunting through log files.
    """
    from .. import service_detector as _sd
    cfg = ctx.get("config") or {}
    try:
        return 200, _sd.detect_all(cfg)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"detect_all failed: {type(e).__name__}: {e}"}


def service_logs(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /service/logs?service=X&tail=N — returns the last N lines
    of the service's launch log. Useful when `start_service` returned
    state="failed" or "timeout" — the log has the actual error."""
    raw_path = ctx.get("raw_path", "") or ctx.get("path", "")
    service = ""
    tail = 200
    if "?" in raw_path:
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(raw_path).query)
            service = (qs.get("service") or [""])[0].strip().lower()
            try:
                tail = int((qs.get("tail") or ["200"])[0])
            except ValueError:
                tail = 200
        except Exception:
            pass
    if service not in ("comfyui", "kobold", "ollama"):
        return 400, {"error": "service query param must be comfyui/kobold/ollama"}
    tail = max(1, min(2000, tail))
    text = _sl.tail_log(service, lines=tail)
    return 200, {"service": service, "tail_lines": tail, "log": text,
                  "last_spawn": _sl.last_spawn_info().get(service)}
