"""Service launcher — start ComfyUI / Kobold / Ollama when installed but offline.

The user's pain point: I've got ComfyUI installed on the render box, but
it's not running right now. Launching it manually is a nuisance — I
just want Spellcaster to notice and start it.

This module is the antenna's answer. Each launcher helper returns a
(argv, cwd) tuple so the caller can spawn it as a detached subprocess.
Heuristics prefer user-tuned launchers (launch_optimized.bat,
launch.bat, etc.) over a generic `python main.py --listen` fallback,
because many users have custom .bat files with the exact flags their
GPU/OS needs.

Launcher discovery order for ComfyUI:
  1. cfg["comfyui_launcher"] — explicit absolute path override.
  2. <comfyui_root>/launch_optimized.bat (matches the user's setup)
  3. <comfyui_root>/launch.bat / start.bat / run_nvidia_gpu.bat
  4. <comfyui_root>/run_nvidia_gpu.bat (the stock portable's launcher)
  5. `python <comfyui_root>/main.py --listen 127.0.0.1 --port 8188`

Design constraints:
  - **Never block the request thread.** ensure_service_running() spawns
    the child as detached then polls reachability with a timeout.
  - **Stdlib only** — same constraint as detect.py/port_cleanup.py.
  - **Logs** — stdout/stderr captured to
    ~/.spellcaster/antenna-logs/<service>.log so the user can see why
    a launch failed without opening a terminal on the antenna box.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


# Where we stash stdout/stderr from launched services. One rolling file per
# service so logs don't mix.
_LOG_DIR = Path(os.path.expanduser("~/.spellcaster/antenna-logs"))


def _log_path(service: str) -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR / f"{service}.log"


def _probe(url: str, timeout: float = 1.0) -> bool:
    """Best-effort GET → True if any response (including 4xx), False on network error."""
    try:
        req = urllib.request.Request(url,
                                      headers={"User-Agent": "spellcaster-antenna-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read(256)
            return True
    except urllib.error.HTTPError:
        return True  # any HTTP response proves the port is live
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


# ─── ComfyUI ──────────────────────────────────────────────────────────────

def _import_installer():
    """Reuse the installer's ComfyUI-root finder — same as comfyui.py does."""
    try:
        _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        from installer import install as _install
        return _install
    except ImportError:
        return None


def _find_comfyui_root(cfg: dict[str, Any]) -> Path | None:
    """Locate the ComfyUI install root on this machine.

    Fallback chain:
      1. cfg['comfyui_root'] explicit override.
      2. installer.find_default_comfyui() — the canonical finder.
      3. antenna.detect's filesystem-evidence path — catches non-standard
         installs that find_default_comfyui misses (e.g. ComfyUI not in
         one of its default search dirs).
    """
    explicit = (cfg.get("comfyui_root") or "").strip()
    if explicit and explicit != "auto":
        p = Path(os.path.expanduser(explicit))
        if p.is_dir():
            return p

    # Installer-native finder
    inst = _import_installer()
    if inst is not None:
        try:
            found = inst.find_default_comfyui()
            if found:
                return Path(found)
        except Exception:
            pass

    # Antenna-detector fallback — services_detected.comfyui.evidence
    # carries the filesystem path when the probe found it on disk.
    try:
        from . import detect as _d
        try:
            from installer import remote_services as _rs
            services_list = _rs.load_services()
        except Exception:
            services_list = []
        comfy_svc = next((s for s in services_list if s.get("key") == "comfyui"),
                          None)
        if comfy_svc is not None:
            evidence = _d.detect_service(comfy_svc)
            ev_str = evidence.get("evidence") or ""
            if ev_str.startswith("filesystem:"):
                path_str = ev_str[len("filesystem:"):].strip()
                p = Path(path_str)
                if p.is_file():
                    return p.parent
                if p.is_dir():
                    return p
    except Exception:
        pass

    # Deep glob fallback — walk 2 levels deep under each drive/home
    # looking for any dir named comfy* (case-insensitive) that holds a
    # main.py. Catches installs like D:\AI\ComfyUI\ or C:\Dev\MyComfyUI\
    # that no shallower detector will find.
    try:
        search_roots: list[Path] = [Path.home()]
        if os.name == "nt":
            try:
                import ctypes
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                for i in range(26):
                    if bitmask & (1 << i):
                        search_roots.append(Path(chr(ord("A") + i) + ":\\"))
            except Exception:
                pass
        else:
            search_roots += [Path("/opt"), Path("/usr/local")]

        candidates: list[Path] = []
        for root in search_roots:
            try:
                if not root.exists():
                    continue
                # Level 1: root/comfy*/main.py
                for sub in list(root.iterdir())[:500]:
                    try:
                        if not sub.is_dir():
                            continue
                        if "comfy" in sub.name.lower() and (sub / "main.py").is_file():
                            candidates.append(sub)
                        # Level 2: root/*/comfy*/main.py
                        try:
                            for ssub in list(sub.iterdir())[:200]:
                                if (ssub.is_dir()
                                    and "comfy" in ssub.name.lower()
                                    and (ssub / "main.py").is_file()):
                                    candidates.append(ssub)
                        except (OSError, PermissionError):
                            continue
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError):
                continue
        if candidates:
            # Prefer shorter paths (closer to drive root) — typically the
            # "real" install vs a backup/clone buried deep.
            candidates.sort(key=lambda p: (len(str(p)), str(p).lower()))
            return candidates[0]
    except Exception:
        pass

    return None


def find_comfyui_launcher(cfg: dict[str, Any]) -> tuple[list[str], Path, str] | None:
    """Delegate to the R57 robust detector — handles all the edge cases
    (deep installs, registry lookups, running-process introspection,
    cache hits). The legacy shallow finder is gone: users with
    non-standard layouts were falling through to `python main.py` which
    often fails due to wrong CUDA/torch env.
    """
    try:
        from . import service_detector as _sd
        return _sd.find_comfyui_launcher_robust(cfg)
    except ImportError as e:
        print(f"[service_launcher] service_detector missing: {e}",
              file=sys.stderr)
        return None


# ─── Kobold ───────────────────────────────────────────────────────────────

def _find_executable_on_fs(names: list[str],
                            hint_dirs: list[Path] | None = None) -> Path | None:
    """Best-effort filesystem scan for any of the named executables.
    First looks in hint_dirs, then in common per-OS install roots.
    """
    search_roots: list[Path] = list(hint_dirs or [])
    search_roots.append(Path.home())
    if os.name == "nt":
        for drive in ("C:", "D:", "E:"):
            search_roots.append(Path(drive + "\\"))
    else:
        search_roots += [Path("/opt"), Path("/usr/local"), Path("/usr")]
    # Shallow search to keep startup fast — we won't walk 100k files
    # looking for a binary.
    for root in search_roots:
        if not root.is_dir():
            continue
        for name in names:
            # Direct match in the root
            p = root / name
            if p.is_file():
                return p
        # One level deep (catches KoboldCpp/koboldcpp.exe, ollama/ollama etc.)
        try:
            for sub in list(root.iterdir())[:200]:
                if not sub.is_dir():
                    continue
                for name in names:
                    p = sub / name
                    if p.is_file():
                        return p
        except OSError:
            continue
    return None


def find_kobold_launcher(cfg: dict[str, Any]) -> tuple[list[str], Path, str] | None:
    # R57: robust binary finder with cache + registry + PATH fallbacks
    try:
        from . import service_detector as _sd
        found, strategy = _sd.find_binary_robust(
            cfg, "kobold",
            ["koboldcpp.exe", "koboldcpp_cuda.exe", "koboldcpp"])
    except ImportError:
        found, strategy = None, "none"
    if found is None:
        return None
    argv: list[str] = [str(found)]
    model = (cfg.get("kobold_model") or "").strip()
    if model and Path(os.path.expanduser(model)).is_file():
        argv += ["--model", os.path.expanduser(model)]
    argv += ["--port", str(cfg.get("kobold_port", 5001))]
    return (argv, found.parent, f"{strategy}:{found.name}")


# ─── Ollama ───────────────────────────────────────────────────────────────

def find_ollama_launcher(cfg: dict[str, Any]) -> tuple[list[str], Path, str] | None:
    try:
        from . import service_detector as _sd
        found, strategy = _sd.find_binary_robust(
            cfg, "ollama", ["ollama.exe", "ollama"])
    except ImportError:
        found, strategy = None, "none"
    if found is None:
        return None
    return ([str(found), "serve"], found.parent, f"{strategy}:{found.name}")


# ─── Generic ensure-running ───────────────────────────────────────────────

_PROBE_URLS = {
    "comfyui": "http://127.0.0.1:{port}/system_stats",
    "kobold":  "http://127.0.0.1:{port}/api/v1/model",
    "ollama":  "http://127.0.0.1:{port}/api/tags",
}

_DEFAULT_PORTS = {"comfyui": 8188, "kobold": 5001, "ollama": 11434}

_LAUNCHERS = {
    "comfyui": find_comfyui_launcher,
    "kobold":  find_kobold_launcher,
    "ollama":  find_ollama_launcher,
}

# Per-service last-known PID tracking for diagnostic purposes. Not used
# for process management (we don't parent these; OS owns them) but helpful
# when a user asks "did you start it?".
_LAST_SPAWN: dict[str, dict[str, Any]] = {}


def _already_running(service: str, cfg: dict[str, Any]) -> bool:
    port = int(cfg.get(f"{service}_port", _DEFAULT_PORTS.get(service, 0))) or 0
    if port == 0:
        return False
    tmpl = _PROBE_URLS.get(service)
    if tmpl is None:
        return False
    return _probe(tmpl.format(port=port), timeout=1.0)


def ensure_service_running(service: str, cfg: dict[str, Any],
                            *, wait_s: float = 30.0) -> dict[str, Any]:
    """Start ``service`` if it isn't already running. Returns:
        {
          "service": "...",
          "state": "already_running" | "started" | "failed" | "not_installed",
          "argv": [...]            // what we ran
          "cwd": "...",
          "strategy": "...",       // launcher identifier
          "pid": 12345,            // spawned child's pid (None on failure)
          "log_path": "...",
          "waited_seconds": 4.2
        }
    """
    result: dict[str, Any] = {"service": service, "state": "unknown",
                                "argv": [], "cwd": None, "strategy": None,
                                "pid": None, "log_path": str(_log_path(service)),
                                "waited_seconds": 0.0}
    if _already_running(service, cfg):
        result["state"] = "already_running"
        return result

    launcher = _LAUNCHERS.get(service)
    if launcher is None:
        result["state"] = "unknown_service"
        return result
    found = launcher(cfg)
    if found is None:
        result["state"] = "not_installed"
        return result
    argv, cwd, strategy = found
    result.update({"argv": argv, "cwd": str(cwd), "strategy": strategy})

    # Open the per-service log file for append and redirect child IO into it.
    try:
        log_f = open(_log_path(service), "a", encoding="utf-8", buffering=1)
        log_f.write(f"\n\n=== launching {service} at {time.strftime('%Y-%m-%dT%H:%M:%S')} "
                    f"via {strategy} ===\n")
        log_f.flush()
    except OSError as e:
        result["state"] = "failed"
        result["error"] = f"log-open failed: {e}"
        return result

    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "stdout": log_f, "stderr": log_f, "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008)  # DETACHED_PROCESS
        # shell=True when the target is a .bat so Windows picks cmd.exe
        if argv[0].lower().endswith(".bat"):
            kwargs["shell"] = True
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(argv, **kwargs)
    except Exception as e:  # noqa: BLE001
        log_f.close()
        result["state"] = "failed"
        result["error"] = f"spawn failed: {type(e).__name__}: {e}"
        return result

    result["pid"] = proc.pid
    _LAST_SPAWN[service] = {"pid": proc.pid, "at": time.time(),
                              "strategy": strategy, "argv": argv}

    # Poll reachability until the service is up or we hit wait_s
    t_start = time.time()
    deadline = t_start + wait_s
    poll_interval = 0.5
    ok = False
    while time.time() < deadline:
        if _already_running(service, cfg):
            ok = True
            break
        # Child died before becoming reachable?
        if proc.poll() is not None:
            result["state"] = "failed"
            result["error"] = f"process exited early with code {proc.returncode}"
            result["waited_seconds"] = round(time.time() - t_start, 1)
            return result
        time.sleep(poll_interval)

    result["waited_seconds"] = round(time.time() - t_start, 1)
    result["state"] = "started" if ok else "timeout"
    return result


def tail_log(service: str, lines: int = 200) -> str:
    """Return the last N lines of the service's log file (UTF-8)."""
    path = _log_path(service)
    if not path.is_file():
        return f"(no log yet for {service})"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail = all_lines[-max(1, int(lines)):]
        return "".join(tail)
    except OSError as e:
        return f"(log read failed: {e})"


def last_spawn_info() -> dict[str, Any]:
    """Return a copy of the last-spawn table for /status visibility."""
    return {k: dict(v) for k, v in _LAST_SPAWN.items()}
