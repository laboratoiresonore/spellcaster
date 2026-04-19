"""Auto-detect Spellcaster-compatible services on the local machine.

Consumed by `antenna/agent.py` at startup and by `GET /status` to surface
a live inventory of what this box actually hosts. The service registry
(`installer/remote_services.json`, fetched dynamically at runtime) is the
authoritative catalog; this module answers "is X present here and right
now?" for each catalog entry.

Three detection signals, combined:

1. **Filesystem presence** — a `detect_paths` hit means the app is
   installed on disk. We walk a small set of common roots (all drive
   letters on Windows, `/Applications`, `/opt`, `/usr`, `$HOME` on Unix)
   checking whether any declared relative path resolves to an existing
   file or directory.

2. **Process presence** — if a process whose image/command name
   contains `detect_process` is running, the app is actually booted.
   Implementation: `tasklist /FO CSV` on Windows, `ps -eo comm,args`
   on POSIX. Best-effort; we don't elevate privileges.

3. **Network reachability** — for services with `default_port != 0`
   (ComfyUI, Kobold, Ollama, SillyTavern), a 1.5s HTTP GET on
   `http://127.0.0.1:<port><probe_path>` confirms the service is
   accepting connections. Cheaper than process inspection and also
   catches services running inside containers or under alt images.

A service is reported as `installed=True` if ANY signal fires. The
`evidence` string captures which one, so operators can tell from
`/status` why the agent thinks something is or isn't available.

Design constraints
------------------
- **Pure function** — returns a dict, no side effects. Callers decide
  whether to auto-mutate config or just surface the inventory.
- **Stdlib only** — no psutil, no requests. The antenna must run on a
  stock ComfyUI Python interpreter without extra pip installs.
- **Fast** — `detect_installed_services()` is called from `/status`, so
  every request can be sub-200ms. We parallelize network probes with
  threads and cap total time.
- **Defensive** — a rogue detect_paths regex, missing command, or
  unreachable localhost MUST NOT raise. Each detector swallows its own
  errors and reports the service as "undetected" with evidence.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


# Cache: service_key -> (evidence_dict, expires_ts). Keeps per-status-call
# cost near-zero after the first call.
_CACHE: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 30.0  # seconds — refreshes every ~30s of /status calls


# ─── Filesystem-presence detector ─────────────────────────────────────────

def _candidate_roots() -> list[Path]:
    """Return the set of root directories to search for detect_paths.

    Windows: every drive letter that exists ($C, $D, $E, ...).
    Unix:    $HOME, /, /Applications, /opt, /usr.
    Home dir is ALWAYS included (portable installs, user-scoped apps).
    """
    roots: list[Path] = [Path.home()]
    if os.name == "nt":
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    roots.append(Path(f"{chr(65 + i)}:/"))
        except Exception:
            # Fallback to common drives if GetLogicalDrives fails
            for letter in "CDEFGH":
                p = Path(f"{letter}:/")
                if p.is_dir():
                    roots.append(p)
        # Program Files is the canonical install root on Windows
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            val = os.environ.get(env)
            if val:
                roots.append(Path(val))
    else:
        roots.extend([
            Path("/"),
            Path("/opt"),
            Path("/usr"),
            Path("/Applications"),         # macOS
            Path.home() / ".local",
        ])
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        s = str(r)
        if s not in seen and r.exists():
            out.append(r)
            seen.add(s)
    return out


def _find_detect_path(detect_path: str, roots: list[Path]) -> Path | None:
    """Resolve a declared relative path against each root. Returns the first hit.

    `detect_path` is relative (e.g. "ComfyUI/main.py" or "GIMP 3/bin/gimp.exe").
    We join against each root and check existence.
    """
    for root in roots:
        try:
            candidate = root / detect_path
            if candidate.exists():
                return candidate
        except (OSError, ValueError):
            # Permission denied / invalid chars in path — keep searching
            continue
    return None


def _detect_by_filesystem(service: dict, roots: list[Path]) -> tuple[bool, str]:
    """Returns (found, evidence). Evidence is the full path on hit."""
    for p in service.get("detect_paths", []) or []:
        hit = _find_detect_path(p, roots)
        if hit is not None:
            return True, f"filesystem: {hit}"
    return False, ""


# ─── Process-presence detector ────────────────────────────────────────────

def _list_processes() -> list[str]:
    """Return a list of lowercase process-identifier strings (image name or
    command line). Empty list on failure — caller treats as "no process".
    """
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode != 0:
                return []
            # CSV lines like: "image.exe","1234","Console","1","4,200 K"
            out: list[str] = []
            for line in r.stdout.splitlines():
                if line.startswith('"') and '",' in line:
                    img = line.split('","', 1)[0].lstrip('"').lower()
                    out.append(img)
            return out
        except (OSError, subprocess.TimeoutExpired):
            return []
    else:
        try:
            r = subprocess.run(
                ["ps", "-eo", "comm,args"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode != 0:
                return []
            return [line.strip().lower() for line in r.stdout.splitlines()[1:]]
        except (OSError, subprocess.TimeoutExpired):
            return []


def _detect_by_process(service: dict, proc_list: list[str]) -> tuple[bool, str]:
    """Returns (found, evidence). Substring match on process name."""
    needle = (service.get("detect_process") or "").lower().strip()
    if not needle:
        return False, ""
    for p in proc_list:
        if needle in p:
            return True, f"process: {p[:80]}"
    return False, ""


# ─── Network-reachability detector ────────────────────────────────────────

def _detect_by_network(service: dict, timeout: float = 1.5) -> tuple[bool, str]:
    """Returns (found, evidence). Only runs if default_port != 0."""
    port = service.get("default_port", 0) or 0
    if port <= 0:
        return False, ""
    probe = service.get("probe_path", "") or "/"
    url = f"http://127.0.0.1:{port}{probe}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            # Any 2xx/3xx means something is listening — even a 404 from a
            # service that doesn't have that path proves the port is live.
            if 200 <= status < 500:
                return True, f"network: http://127.0.0.1:{port} ({status})"
    except (urllib.error.HTTPError,):
        # HTTP errors (401/403/404/500) still prove the port is listening
        return True, f"network: http://127.0.0.1:{port} (http error reply)"
    except (urllib.error.URLError, socket.timeout, OSError):
        return False, ""
    return False, ""


# ─── Main entry points ────────────────────────────────────────────────────

def detect_service(service: dict, *, roots: list[Path] | None = None,
                   proc_list: list[str] | None = None) -> dict[str, Any]:
    """Inspect one service entry. Returns an evidence dict.

    Args:
        service: one entry from installer/remote_services.json
        roots:   pre-computed filesystem roots (optional, for perf on bulk calls)
        proc_list: pre-computed process list (optional, same reason)

    Returns:
        {
          "installed": bool,
          "evidence": "filesystem: ..." | "process: ..." | "network: ..." | "",
          "port_listening": bool,     # only present if default_port > 0
          "signals": {                  # which detectors fired
            "fs": bool, "process": bool, "network": bool
          }
        }
    """
    if roots is None:
        roots = _candidate_roots()
    if proc_list is None:
        proc_list = _list_processes()

    fs_found, fs_ev = _detect_by_filesystem(service, roots)
    proc_found, proc_ev = _detect_by_process(service, proc_list)
    net_found, net_ev = _detect_by_network(service)

    # Pick the strongest signal for the evidence string: network > process > fs
    # (network proves it's running; process proves it's booted; fs only proves
    # it's installed.)
    if net_found:
        evidence = net_ev
    elif proc_found:
        evidence = proc_ev
    elif fs_found:
        evidence = fs_ev
    else:
        evidence = ""

    result: dict[str, Any] = {
        "installed": bool(fs_found or proc_found or net_found),
        "evidence": evidence,
        "signals": {"fs": fs_found, "process": proc_found, "network": net_found},
    }
    port = service.get("default_port", 0) or 0
    if port > 0:
        result["port_listening"] = net_found
    return result


def detect_installed_services(services: list[dict],
                               *, use_cache: bool = True) -> dict[str, dict]:
    """Inspect every service in the registry. Returns {service_key: evidence}.

    Cached for _CACHE_TTL seconds to keep /status responses snappy. Pass
    use_cache=False on explicit refresh (e.g. a `POST /rescan` later).

    Internals: pre-computes the filesystem roots + process list ONCE, then
    reuses them across all services. Dominant cost is the network probes
    which are run in parallel via threads (cap ~2s for all).
    """
    now = time.time()

    # Return stale entries immediately if still fresh
    if use_cache:
        fresh: dict[str, dict] = {}
        all_fresh = True
        for svc in services:
            key = svc.get("key", "")
            cached = _CACHE.get(key)
            if cached and cached[1] > now:
                fresh[key] = cached[0]
            else:
                all_fresh = False
                break
        if all_fresh:
            return fresh

    roots = _candidate_roots()
    proc_list = _list_processes()

    # Parallelize network probes — biggest latency contributor.
    results: dict[str, dict] = {}
    threads: list[threading.Thread] = []
    lock = threading.Lock()

    def _work(svc: dict):
        evidence = detect_service(svc, roots=roots, proc_list=proc_list)
        with lock:
            results[svc.get("key", "")] = evidence

    for svc in services:
        t = threading.Thread(target=_work, args=(svc,), daemon=True)
        t.start()
        threads.append(t)

    # Cap the whole batch at 3 seconds AFTER the threads actually start —
    # using `now` (function entry) would eat into the budget during the
    # roots/proc_list prep work, causing slow probes to get cut off.
    deadline = time.time() + 3.0
    for t in threads:
        remaining = max(0.0, deadline - time.time())
        t.join(timeout=remaining)

    # Persist to cache
    expires = time.time() + _CACHE_TTL
    for key, ev in results.items():
        _CACHE[key] = (ev, expires)

    return results


def invalidate_cache() -> None:
    """Force the next detect_installed_services() call to re-probe everything.
    Called from `POST /self-update` after a code update so the new agent
    starts with a fresh inventory.
    """
    _CACHE.clear()
