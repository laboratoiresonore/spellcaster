"""Pre-bind port cleanup — reap processes still holding our listening port.

Why
---
On Windows, the self-update flow used to leave orphaned `python.exe`
processes holding port 7334 after a botched restart. The new antenna
process then couldn't bind and died silently. This module closes that
gap: when serve() starts up, it scans for any process currently holding
its target port and — if the process looks like a stale antenna —
terminates it before attempting to bind.

Design constraints
------------------
- **Stdlib only.** No psutil. We shell out to OS-native tools
  (netstat/taskkill on Windows, lsof/kill on POSIX).
- **Safety heuristic.** We only kill processes whose image name contains
  "python" (case-insensitive). If something unrelated is on port 7334
  (a web server, a game lobby, whatever), we leave it alone and let the
  bind fail loudly — the operator then has to intervene.
- **Best effort.** Failures in discovery/kill are logged but never raise.
  A serve() call that can't reap is STILL better than no reap at all
  because the subsequent bind will tell us if the port is clear.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any


def _find_pids_holding_port_windows(port: int) -> list[int]:
    """Return PIDs of Windows processes listening on `port`.

    Uses `netstat -ano` (universal, ships with every Windows install).
    Filters to LISTENING state only — we don't want to kill transient
    clients that happen to have an ephemeral port briefly bound.
    """
    pids: set[int] = set()
    try:
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=5,
            # No shell — the binary is always on PATH on Windows.
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[port-cleanup] netstat failed: {e}", file=sys.stderr)
        return []
    for line in proc.stdout.splitlines():
        # Sample line:
        #   TCP    0.0.0.0:7334          0.0.0.0:0              LISTENING       12345
        parts = line.split()
        if len(parts) < 5:
            continue
        # parts[1] is local address like "0.0.0.0:7334" or "[::]:7334"
        local = parts[1]
        if not local.endswith(f":{port}"):
            continue
        state = parts[3]
        if state != "LISTENING":
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return sorted(pids)


def _pid_image_name_windows(pid: int) -> str:
    """Best-effort image name for a Windows PID. Empty string if unknown."""
    try:
        # `tasklist /FI "PID eq <pid>" /FO CSV /NH` — quoting-safe CSV output.
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    out = (proc.stdout or "").strip()
    if not out or "No tasks" in out:
        return ""
    # "python.exe","12345","Console","1","42,000 K"
    first_field = out.split('","', 1)[0].strip().strip('"')
    return first_field


def _kill_pid_windows(pid: int) -> bool:
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[port-cleanup] taskkill {pid} failed: {e}", file=sys.stderr)
        return False


def _find_pids_holding_port_posix(port: int) -> list[int]:
    """Return PIDs of POSIX processes listening on `port` via lsof."""
    pids: set[int] = set()
    try:
        proc = subprocess.run(
            ["lsof", "-nP", "-i", f"TCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[port-cleanup] lsof failed: {e}", file=sys.stderr)
        return []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.add(int(line))
        except ValueError:
            continue
    return sorted(pids)


def _pid_image_name_posix(pid: int) -> str:
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip()


def _kill_pid_posix(pid: int) -> bool:
    try:
        os.kill(pid, 15)  # SIGTERM
        time.sleep(0.5)
        # Still alive? Escalate.
        try:
            os.kill(pid, 0)  # probe — raises if dead
            os.kill(pid, 9)  # SIGKILL
        except ProcessLookupError:
            pass
        return True
    except (ProcessLookupError, PermissionError) as e:
        print(f"[port-cleanup] kill {pid} failed: {e}", file=sys.stderr)
        return False


def reap_port_holders(port: int, *, only_python: bool = True,
                      self_pid: int | None = None) -> list[dict[str, Any]]:
    """Kill any process currently listening on ``port``.

    Args:
        port: TCP port we want to bind.
        only_python: if True (default), only kill processes whose image
            name contains "python" (case-insensitive). Guards against
            accidentally killing unrelated services that happened to
            claim the port — a user who's moved the antenna to port 80
            should not have their webserver reaped.
        self_pid: PID to NEVER kill (use os.getpid() when called from
            the same process). Prevents suicide if lsof/netstat returns
            the caller's own listen socket during a reload.

    Returns a list of dicts: [{"pid": int, "image": str, "killed": bool,
    "skipped_reason": str|None}, ...]. Empty list means nothing to reap.
    """
    self_pid = self_pid if self_pid is not None else os.getpid()
    if os.name == "nt":
        pids = _find_pids_holding_port_windows(port)
        image_of = _pid_image_name_windows
        kill = _kill_pid_windows
    else:
        pids = _find_pids_holding_port_posix(port)
        image_of = _pid_image_name_posix
        kill = _kill_pid_posix

    results: list[dict[str, Any]] = []
    for pid in pids:
        if pid == self_pid:
            results.append({"pid": pid, "image": "(self)", "killed": False,
                             "skipped_reason": "self-pid"})
            continue
        image = image_of(pid)
        if only_python and "python" not in image.lower():
            results.append({"pid": pid, "image": image or "(unknown)",
                             "killed": False,
                             "skipped_reason": "not a python process"})
            continue
        ok = kill(pid)
        results.append({"pid": pid, "image": image or "(unknown)",
                         "killed": bool(ok),
                         "skipped_reason": None if ok else "kill failed"})
    return results
