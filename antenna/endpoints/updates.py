"""POST /update/* — antenna-side auto-update execution.

For each service in installer/remote_services.json that declares an
`update_command`, this endpoint can run that command and stream the
result. A daily Task Scheduler entry on each Windows fleet host calls
`POST /update/all` against its own antenna to keep everything fresh.

Update-command discipline
-------------------------
  * Commands are read from the registry, not from the request body —
    the request only names which service to update. This means the
    fleet operator decides what update means for each service (via a
    PR to remote_services.json); the antenna just executes.
  * Commands run via the user's shell (cmd.exe / sh) for portability.
    Each registry entry can override with `update_shell` if needed.
  * 10-minute per-service timeout (longer than typical winget/pip).
  * Output captured and stored for the /update/status endpoint so the
    fleet-frame can surface "last result" + log per service.

  POST /update/<service>            → run one service's update
  POST /update/all                  → run every service that has a command
  GET  /update/status               → returns the recorded result of the
                                       most-recent run per service

Results are persisted to ~/.spellcaster/update_history.json (atomic
write). The file is bounded to the most recent 50 runs.
"""
from __future__ import annotations

import json
import os
import subprocess
from .. import _silent
import sys
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_S = 600  # 10 minutes per service
HISTORY_MAX = 50
_history_lock = threading.RLock()
_in_flight: set[str] = set()


def _history_path() -> Path:
    return Path(os.path.expanduser("~/.spellcaster/update_history.json"))


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def _load_history() -> list[dict[str, Any]]:
    try:
        with _history_path().open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _append_history(entry: dict[str, Any]) -> None:
    with _history_lock:
        h = _load_history()
        h.append(entry)
        if len(h) > HISTORY_MAX:
            h = h[-HISTORY_MAX:]
        try:
            _atomic_write(_history_path(), h)
        except OSError:
            pass


def _service_registry() -> list[dict[str, Any]]:
    """Reads remote_services.json — same source the rest of the antenna
    uses for service detection. Lazy import to avoid circular deps."""
    try:
        repo_root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..",
        ))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from installer import remote_services as _rs  # type: ignore
        reg = _rs.load_services()
        return reg.get("services") or []
    except Exception:  # noqa: BLE001
        return []


def _service_by_key(key: str) -> dict[str, Any] | None:
    for s in _service_registry():
        if s.get("key") == key:
            return s
    return None


def _run_one(service: dict[str, Any]) -> dict[str, Any]:
    """Execute a single service's update_command. Returns a result dict."""
    key = service.get("key", "?")
    cmd = service.get("update_command")
    if not cmd:
        return {
            "service": key, "skipped": True,
            "reason": "no update_command in registry",
            "ts_start": int(time.time()),
            "ts_end": int(time.time()),
        }
    if key in _in_flight:
        return {"service": key, "skipped": True,
                "reason": "already in flight",
                "ts_start": int(time.time())}
    _in_flight.add(key)
    started = time.time()
    log_lines: list[str] = []
    return_code = -1
    state = "failed"
    try:
        shell_choice = service.get("update_shell")
        if shell_choice == "powershell":
            full = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
            use_shell = False
        else:
            # cmd.exe on Windows, /bin/sh elsewhere — let subprocess pick
            full = cmd
            use_shell = True
        proc = _silent.Popen(
            full,
            shell=use_shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            stdout, _ = proc.communicate(
                timeout=int(service.get("update_timeout_s", DEFAULT_TIMEOUT_S)))
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                stdout, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout = ""
            log_lines.append("[antenna] update timed out")
            state = "timeout"
            return_code = -2
        else:
            return_code = proc.returncode
            state = "success" if return_code == 0 else "failed"
        if stdout:
            # Keep the last ~4000 chars to bound the JSON payload.
            log_lines.append(stdout[-4000:])
    except Exception as e:  # noqa: BLE001 — must never crash the route
        log_lines.append(f"[antenna] exec error: {type(e).__name__}: {e}")
    finally:
        _in_flight.discard(key)

    return {
        "service": key,
        "label": service.get("label", key),
        "cmd": cmd,
        "ts_start": int(started),
        "ts_end": int(time.time()),
        "duration_s": round(time.time() - started, 2),
        "return_code": return_code,
        "state": state,
        "log": "\n".join(log_lines),
    }


# ─── Endpoint handlers ────────────────────────────────────────────────


def update_one(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /update/<service>"""
    raw_path = ctx.get("raw_path", "") or ctx.get("path", "")
    key = raw_path.split("?", 1)[0].rstrip("/").split("/")[-1].lower()
    if not key:
        return 400, {"error": "service key required in URL"}
    svc = _service_by_key(key)
    if not svc:
        return 404, {"error": f"service {key!r} not in registry"}
    result = _run_one(svc)
    _append_history(result)
    code = 200 if result.get("state") == "success" else (
        202 if result.get("skipped") else 500)
    return code, result


def update_all(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /update/all — runs every service that has an update_command."""
    results: list[dict[str, Any]] = []
    for svc in _service_registry():
        if not svc.get("update_command"):
            continue
        r = _run_one(svc)
        _append_history(r)
        results.append(r)
    summary = {
        "ts": int(time.time()),
        "total": len(results),
        "success": sum(1 for r in results if r.get("state") == "success"),
        "failed":  sum(1 for r in results if r.get("state") == "failed"),
        "timeout": sum(1 for r in results if r.get("state") == "timeout"),
        "results": results,
    }
    return 200, summary


def update_status(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /update/status — most-recent recorded result per service."""
    history = _load_history()
    latest: dict[str, dict[str, Any]] = {}
    for e in history:
        k = e.get("service")
        if k and (k not in latest or e.get("ts_end", 0) > latest[k].get("ts_end", 0)):
            latest[k] = e
    # Strip giant log bodies in this listing — clients fetch individual
    # service detail via the history endpoint if they want logs.
    light = {}
    for k, v in latest.items():
        light[k] = {kk: v[kk] for kk in v if kk != "log"}
    return 200, {"latest": light, "history_size": len(history)}
