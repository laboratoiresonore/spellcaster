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
