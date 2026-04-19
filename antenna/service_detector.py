"""Robust multi-strategy service detector for the antenna.

Finds the install root + preferred launcher for ComfyUI, GIMP,
Darktable, Resolve, Kobold, Ollama, SillyTavern — regardless of how
the user installed them. Unlike the simpler `antenna/detect.py` (which
only flags installed/online for `/status`), this module's job is
**finding the exact absolute path** the launcher needs to cd into.

## Path-separator policy (central rule — see also CLAUDE.md §Paths)

All paths in THIS codebase pass through `pathlib.Path`, which internally
stores platform-native separators. We never manually concatenate with
`/` or `\\`. When emitting paths for external consumers:

  - **API response bodies**: emit `.as_posix()` (forward slashes)
    everywhere. JSON escaping hell is the reason — a Windows path with
    backslashes forces callers to escape-or-die. Forward slashes work
    on Windows file operations just fine.
  - **Subprocess argv**: emit `str(path)` (platform-native). Some
    Windows .bat launchers are picky about backslashes.
  - **Config file values**: forward slashes (users can write either,
    we normalize on read via `Path(os.path.expanduser(s))`).

This is detector-side policy only. The ComfyUI WORKFLOW BUILDERS in
spellcaster_core/workflows.py have their own path rules (pass filenames,
not full paths, because ComfyUI resolves against its input/output dirs).
Don't touch those.

## Detection strategies (ordered, short-circuit on first match)

1. **Explicit override** — `cfg["<svc>_root"]` or `cfg["<svc>_launcher"]`.
2. **Cache hit** — previously-discovered path persisted in
   `~/.spellcaster/antenna_state.json`. Verified with a quick `.is_dir()`
   before trusting.
3. **Running-process introspection** — if the service is live, read
   its cmdline (Windows: wmic process get CommandLine; POSIX: /proc/PID/cmdline)
   and extract the install path from argv.
4. **Platform-native installed-app probes**:
     Windows: winreg uninstall keys + LOCALAPPDATA/Programs/* +
              USERPROFILE/* 2 levels + Program Files scan
     macOS:   /Applications/*.app/Contents/MacOS/<binary>
     Linux:   /opt/<svc>*, /usr/local/<svc>*, /snap/<svc>/*
5. **Cross-drive deep glob** — every drive root, walk 3 levels deep
   with smart pruning (skip system dirs, bail after ~5000 file checks).
6. **Content signature verification** — every candidate `main.py` is
   grepped for "ComfyUI" in its first 4KB to prevent false positives
   from unrelated `main.py` files.

Every successful detection is cached to `antenna_state.json`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

# ─── Persistent detector cache ───────────────────────────────────────

_STATE_PATH = Path(os.path.expanduser("~/.spellcaster/antenna_state.json"))
# Cache hit TTL — re-verify paths older than this (handles user moving/
# deleting an install without leaving a stale cache forever).
_CACHE_MAX_AGE_S = 7 * 24 * 60 * 60  # 7 days


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {"detected_paths": {}}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"detected_paths": {}}


def _save_state(state: dict[str, Any]) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[service_detector] cache write failed: {e}", file=sys.stderr)


def _remember(service: str, root: Path, strategy: str) -> None:
    state = _load_state()
    state.setdefault("detected_paths", {})
    state["detected_paths"][service] = {
        "root": root.as_posix(),
        "discovered_at": time.time(),
        "strategy": strategy,
    }
    _save_state(state)


def _cached(service: str) -> Path | None:
    state = _load_state()
    entry = (state.get("detected_paths") or {}).get(service)
    if not entry:
        return None
    if (time.time() - entry.get("discovered_at", 0)) > _CACHE_MAX_AGE_S:
        return None
    p = Path(entry.get("root", ""))
    return p if p.is_dir() else None


# ─── Helper: process cmdline lookup ──────────────────────────────────

def _running_cmdlines_containing(needle: str) -> list[str]:
    """Return the full cmdline strings of running processes whose image
    or arguments contain ``needle`` (case-insensitive). Used to recover
    an install path when the service is already live but cache is empty.
    """
    needle_lc = needle.lower()
    lines: list[str] = []
    try:
        if os.name == "nt":
            # wmic deprecated but still shipping on most installs. Use
            # CIM-cmdlets as the better path but fall back to wmic.
            try:
                proc = subprocess.run(
                    ["wmic", "process", "get", "ProcessId,CommandLine", "/FORMAT:CSV"],
                    capture_output=True, text=True, timeout=5,
                )
                text = proc.stdout or ""
            except (OSError, subprocess.TimeoutExpired):
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Process | Select-Object "
                     "-ExpandProperty CommandLine"],
                    capture_output=True, text=True, timeout=5,
                )
                text = proc.stdout or ""
            for line in text.splitlines():
                if needle_lc in line.lower():
                    lines.append(line.strip())
        else:
            proc = subprocess.run(
                ["ps", "-eo", "args"],
                capture_output=True, text=True, timeout=3,
            )
            for line in (proc.stdout or "").splitlines():
                if needle_lc in line.lower():
                    lines.append(line.strip())
    except (OSError, subprocess.TimeoutExpired):
        return []
    return lines


# ─── Content signature helpers ───────────────────────────────────────

def _file_contains(path: Path, needle: bytes, head_bytes: int = 4096) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(head_bytes)
        return needle in head
    except OSError:
        return False


# ─── Drive + root enumeration ────────────────────────────────────────

def _candidate_roots() -> list[Path]:
    roots: list[Path] = [Path.home()]
    if os.name == "nt":
        # Every logical drive
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    roots.append(Path(chr(ord("A") + i) + ":\\"))
        except Exception:
            pass
        # LOCALAPPDATA / Program Files — common for portable installs
        for env in ("LOCALAPPDATA", "APPDATA",
                     "ProgramFiles", "ProgramFiles(x86)"):
            v = os.environ.get(env, "").strip()
            if v:
                roots.append(Path(v))
    else:
        roots.extend([Path("/opt"), Path("/usr/local"),
                       Path("/Applications"), Path("/snap")])
    # Dedup while preserving order; tolerate WinError 5 on mapped drives
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        s = str(r)
        if s in seen:
            continue
        seen.add(s)
        try:
            if r.exists():
                out.append(r)
        except (OSError, PermissionError):
            continue
    return out


# Directories we should NEVER recurse into when scanning (big time sinks
# with zero chance of hosting an AI app install).
_SKIP_DIR_PATTERNS = {
    "$recycle.bin", "system volume information", "windows",
    "winsxs", "node_modules", ".git", "__pycache__",
    "program files\\windowsapps",  # system-protected
    "programdata\\package cache",
}


def _should_skip(path: Path) -> bool:
    name_lc = path.name.lower()
    if name_lc.startswith("."):
        return True
    if name_lc in {"windows", "winsxs", "temp", "tmp",
                    "$recycle.bin", "node_modules", "__pycache__"}:
        return True
    return False


def _walk_for_needle(roots: list[Path], needle: str, max_depth: int = 3,
                      max_visits: int = 8000) -> list[Path]:
    """Walk ``roots`` up to ``max_depth`` levels deep collecting every
    directory whose basename contains ``needle`` (case-insensitive).
    Bounded by ``max_visits`` dir probes to keep scan time predictable.
    """
    needle_lc = needle.lower()
    hits: list[Path] = []
    visited = 0

    def _walk(p: Path, depth: int):
        nonlocal visited
        if visited >= max_visits or depth > max_depth:
            return
        try:
            entries = list(p.iterdir())
        except (OSError, PermissionError):
            return
        for entry in entries:
            if visited >= max_visits:
                return
            visited += 1
            try:
                if not entry.is_dir():
                    continue
            except (OSError, PermissionError):
                continue
            if _should_skip(entry):
                continue
            if needle_lc in entry.name.lower():
                hits.append(entry)
            # Recurse regardless of whether THIS dir matched — a hit
            # might be one more level down.
            _walk(entry, depth + 1)

    for r in roots:
        _walk(r, 0)
    return hits


# ─── ComfyUI-specific detection ──────────────────────────────────────

# Accept both dash and underscore variants. Order = preference.
COMFYUI_PREFERRED_LAUNCHERS = (
    "launch-optimized.bat", "launch_optimized.bat",
    "launch.bat", "start.bat",
    "run_nvidia_gpu.bat", "run_cpu.bat",
    "launch-portable.bat", "launch_portable.bat",
)


def _verify_comfyui_root(p: Path) -> bool:
    """True iff ``p`` looks like a real ComfyUI install. Uses structural
    cues instead of a single string match, because main.py's first 4 KB
    might not mention "ComfyUI" by name (depends on the ComfyUI version).

    Signature: main.py + execution.py + server.py + comfy/ dir all exist.
    That combination is diagnostic — no other common project has exactly
    this layout.
    """
    main_py = p / "main.py"
    if not main_py.is_file():
        return False
    # Strong structural signature
    if ((p / "execution.py").is_file()
        and (p / "server.py").is_file()
        and (p / "comfy").is_dir()):
        return True
    # Fallback — string match on main.py for older layouts
    return _file_contains(main_py, b"ComfyUI", head_bytes=16384)


def find_comfyui_root_robust(cfg: dict[str, Any]) -> tuple[Path | None, str]:
    """Find ComfyUI root + report which strategy hit. Strategies tried
    in order; short-circuits on first valid result.
    """
    # 1. explicit override
    explicit = (cfg.get("comfyui_root") or "").strip()
    if explicit and explicit != "auto":
        p = Path(os.path.expanduser(explicit))
        if p.is_dir() and _verify_comfyui_root(p):
            return p, "config-override"

    # 2. cache hit
    cached = _cached("comfyui")
    if cached is not None and _verify_comfyui_root(cached):
        return cached, "cache-hit"

    # 3. running-process introspection
    for line in _running_cmdlines_containing("main.py"):
        # Extract the first path-like token containing "main.py"
        # Handles: python.exe "C:\X\Y\ComfyUI\main.py" --listen ...
        for token in line.replace('"', ' ').split():
            if token.lower().endswith("main.py"):
                p = Path(token).parent
                if p.is_dir() and _verify_comfyui_root(p):
                    _remember("comfyui", p, "running-process")
                    return p, "running-process"

    # 4. installer-native finder
    try:
        _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        from installer import install as _install  # type: ignore
        found = _install.find_default_comfyui()
        if found:
            p = Path(found)
            if p.is_dir() and _verify_comfyui_root(p):
                _remember("comfyui", p, "installer-finder")
                return p, "installer-finder"
    except Exception:
        pass

    # 5. Windows registry (uninstall entries mentioning ComfyUI)
    if os.name == "nt":
        try:
            import winreg  # type: ignore
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for subkey_path in (
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                ):
                    try:
                        with winreg.OpenKey(hive, subkey_path) as root_key:
                            i = 0
                            while True:
                                try:
                                    subname = winreg.EnumKey(root_key, i)
                                except OSError:
                                    break
                                i += 1
                                if "comfy" not in subname.lower():
                                    continue
                                try:
                                    with winreg.OpenKey(root_key, subname) as sub:
                                        loc, _ = winreg.QueryValueEx(
                                            sub, "InstallLocation")
                                        p = Path(str(loc))
                                        if p.is_dir() and _verify_comfyui_root(p):
                                            _remember("comfyui", p, "registry")
                                            return p, "registry"
                                except (OSError, FileNotFoundError):
                                    continue
                    except OSError:
                        continue
        except ImportError:
            pass

    # 6. deep glob — find any dir named comfy* with main.py containing
    # the ComfyUI signature. Covers `C:\Users\<u>\ComfyUI\ComfyUI\`
    # (3 levels deep from drive root), `D:\AI\ComfyUI\`, etc.
    roots = _candidate_roots()
    candidates = _walk_for_needle(roots, "comfy", max_depth=4, max_visits=8000)
    # Filter to real ComfyUI installs
    valid = [p for p in candidates if _verify_comfyui_root(p)]
    if valid:
        # Prefer shortest path (more likely the "real" install vs a
        # nested backup/clone)
        valid.sort(key=lambda p: (len(str(p)), str(p).lower()))
        best = valid[0]
        _remember("comfyui", best, "deep-glob")
        return best, "deep-glob"

    return None, "none"


def find_comfyui_launcher_robust(cfg: dict[str, Any]
                                   ) -> tuple[list[str], Path, str] | None:
    """R57 version of find_comfyui_launcher. Returns (argv, cwd, strategy)
    or None. Strategy format: "<root-strategy>:<launcher-name>".
    """
    # Explicit launcher override always wins
    override = (cfg.get("comfyui_launcher") or "").strip()
    if override:
        p = Path(os.path.expanduser(override))
        if p.is_file():
            return ([str(p)], p.parent, f"override:{p.name}")

    root, root_strategy = find_comfyui_root_robust(cfg)
    if root is None:
        return None

    # Walk preferred .bat names in both the root and one level up
    # (portable distros put the .bat in the parent of ComfyUI/).
    for search_dir in (root, root.parent):
        for name in COMFYUI_PREFERRED_LAUNCHERS:
            p = search_dir / name
            if p.is_file():
                return ([str(p)], p.parent, f"{root_strategy}:{name}")

    # Fallback — `python main.py --listen --port`
    main_py = root / "main.py"
    if main_py.is_file():
        port = int(cfg.get("comfyui_port", 8188))
        argv = [sys.executable, str(main_py),
                "--listen", "127.0.0.1", "--port", str(port)]
        return (argv, root, f"{root_strategy}:python-main.py")
    return None


# ─── Generic executable finder (kobold/ollama/etc.) ──────────────────

def find_binary_robust(cfg: dict[str, Any], service: str,
                         names: list[str],
                         depth: int = 3, max_visits: int = 5000
                         ) -> tuple[Path | None, str]:
    """Generic robust finder for a service whose install is an
    executable (not a source dir). Tries override → cache → PATH →
    Program Files → deep scan. Returns (path, strategy)."""
    override = (cfg.get(f"{service}_launcher") or "").strip()
    if override:
        p = Path(os.path.expanduser(override))
        if p.is_file():
            return p, "config-override"

    cached = _cached(service)
    if cached is not None:
        # For binary services, cache may be dir (installed location).
        # Verify a named executable still exists inside.
        for name in names:
            p = cached / name
            if p.is_file():
                return p, "cache-hit"

    # PATH scan
    for name in names:
        from shutil import which
        found = which(name)
        if found:
            p = Path(found)
            if p.is_file():
                _remember(service, p.parent, "PATH")
                return p, "PATH"

    # Filesystem walk — checks root, 1 level deep, AND common
    # binary-subdir layouts (bin/, Bin/, Binaries/). Many Windows apps
    # (GIMP, Darktable, Blender) install as <root>/<AppDir>/bin/<exe>.
    BIN_SUBDIRS = ("", "bin", "Bin", "binaries", "Binaries")
    roots = _candidate_roots()
    for r in roots:
        candidates: list[Path] = []
        try:
            # Check root itself and root/bin/*
            for binsub in BIN_SUBDIRS:
                search = r / binsub if binsub else r
                if not search.is_dir():
                    continue
                for name in names:
                    p = search / name
                    if p.is_file():
                        candidates.append(p)
        except (OSError, PermissionError):
            pass
        # One level deep (+ bin/ inside each level-1 dir)
        try:
            for sub in list(r.iterdir())[:500]:
                if not sub.is_dir() or _should_skip(sub):
                    continue
                for binsub in BIN_SUBDIRS:
                    search = sub / binsub if binsub else sub
                    if not search.is_dir():
                        continue
                    for name in names:
                        p = search / name
                        if p.is_file():
                            candidates.append(p)
        except (OSError, PermissionError):
            continue
        if candidates:
            candidates.sort(key=lambda p: (len(str(p)), str(p).lower()))
            best = candidates[0]
            _remember(service, best.parent, "filesystem-walk")
            return best, "filesystem-walk"

    # Deep walk — expensive but thorough. Only runs if shallow missed.
    dir_hits = _walk_for_needle(roots, service, max_depth=depth,
                                  max_visits=max_visits)
    for d in dir_hits:
        for name in names:
            p = d / name
            if p.is_file():
                _remember(service, p.parent, "deep-glob")
                return p, "deep-glob"
    return None, "none"


# ─── DaVinci Resolve detection ───────────────────────────────────────

# Resolve isn't launchable from the antenna (it's a GUI app the user
# starts manually), but we DO want to detect its install + verify the
# scripting module path. The scripting API path is what resolve.py's
# import relies on.
_RESOLVE_SEARCH_PATTERNS = {
    "win":   ["Blackmagic Design/DaVinci Resolve/Resolve.exe"],
    "mac":   ["Applications/DaVinci Resolve/DaVinci Resolve.app"],
    "linux": ["opt/resolve/bin/resolve"],
}


def find_resolve_install(cfg: dict[str, Any]) -> tuple[Path | None, str]:
    """Locate the DaVinci Resolve install root (the dir containing
    Resolve.exe on Windows, the .app bundle on macOS, or the bin dir
    on Linux). Returns (path, strategy)."""
    explicit = (cfg.get("resolve_root") or "").strip()
    if explicit:
        p = Path(os.path.expanduser(explicit))
        if p.exists():
            return p, "config-override"

    cached = _cached("resolve")
    if cached is not None:
        return cached, "cache-hit"

    # Process introspection — if Resolve is running, wmic tells us where
    for line in _running_cmdlines_containing("Resolve"):
        # Look for a path-like token ending in Resolve.exe / Resolve
        for token in line.replace('"', ' ').split():
            lc = token.lower()
            if lc.endswith("resolve.exe") or lc.endswith("resolve"):
                p = Path(token).parent
                if p.is_dir():
                    _remember("resolve", p, "running-process")
                    return p, "running-process"

    # Windows: check the canonical Program Files location
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env, "").strip()
            if not base:
                continue
            candidate = (Path(base) / "Blackmagic Design"
                         / "DaVinci Resolve" / "Resolve.exe")
            if candidate.is_file():
                _remember("resolve", candidate.parent, "program-files")
                return candidate.parent, "program-files"
        # Also check winreg for Blackmagic Design keys
        try:
            import winreg  # type: ignore
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for subkey_path in (
                    r"SOFTWARE\Blackmagic Design\DaVinci Resolve",
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                ):
                    try:
                        with winreg.OpenKey(hive, subkey_path) as key:
                            i = 0
                            while True:
                                try:
                                    subname = winreg.EnumKey(key, i)
                                except OSError:
                                    break
                                i += 1
                                if "resolve" not in subname.lower():
                                    continue
                                try:
                                    with winreg.OpenKey(key, subname) as sub:
                                        loc, _ = winreg.QueryValueEx(
                                            sub, "InstallLocation")
                                        p = Path(str(loc))
                                        if p.is_dir():
                                            _remember("resolve", p, "registry")
                                            return p, "registry"
                                except (OSError, FileNotFoundError):
                                    continue
                    except OSError:
                        continue
        except ImportError:
            pass
    elif sys.platform == "darwin":
        candidate = Path("/Applications/DaVinci Resolve/DaVinci Resolve.app")
        if candidate.exists():
            _remember("resolve", candidate, "applications")
            return candidate, "applications"
    else:
        for prefix in ("/opt/resolve", "/usr/local/resolve"):
            p = Path(prefix)
            if p.is_dir():
                _remember("resolve", p, "posix-prefix")
                return p, "posix-prefix"

    return None, "none"


# ─── Windows registry helper (shared across services) ───────────────

def _win_registry_find_install_location(key_name_needle: str
                                          ) -> Path | None:
    """Walk Windows Uninstall registry keys for any entry whose name
    contains ``key_name_needle`` (case-insensitive). Returns the first
    InstallLocation found as an existing directory. Covers MSI, winget,
    Chocolatey, and most third-party installers that register properly."""
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore
    except ImportError:
        return None
    needle_lc = key_name_needle.lower()
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey_path in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                with winreg.OpenKey(hive, subkey_path) as root_key:
                    i = 0
                    while True:
                        try:
                            subname = winreg.EnumKey(root_key, i)
                        except OSError:
                            break
                        i += 1
                        if needle_lc not in subname.lower():
                            continue
                        try:
                            with winreg.OpenKey(root_key, subname) as sub:
                                loc, _ = winreg.QueryValueEx(sub, "InstallLocation")
                                p = Path(str(loc))
                                if p.is_dir():
                                    return p
                        except (OSError, FileNotFoundError):
                            continue
            except OSError:
                continue
    return None


# ─── GIMP / Darktable / SillyTavern ──────────────────────────────────

def find_gimp_install(cfg: dict[str, Any]) -> tuple[Path | None, str]:
    """Find GIMP install root. Tries in order: config-override,
    cache, explicit exe discovery (shutil.which), Windows registry,
    Program Files versioned-dir walk, cross-drive PortableApps scan."""
    import shutil

    explicit = (cfg.get("gimp_root") or "").strip()
    if explicit:
        p = Path(os.path.expanduser(explicit))
        if p.is_dir():
            return p, "config-override"
    cached = _cached("gimp")
    if cached is not None:
        return cached, "cache-hit"

    # shutil.which for any GIMP binary name
    for name in ("gimp-3.2", "gimp-3.0", "gimp3", "gimp-2.99", "gimp"):
        exe = shutil.which(name)
        if exe:
            p = Path(exe).resolve()
            # gimp.exe is typically in <install>/bin/ — go up to root
            install_root = p.parent
            if install_root.name.lower() in ("bin", "binaries"):
                install_root = install_root.parent
            _remember("gimp", install_root, "which")
            return install_root, "which"

    if os.name == "nt":
        # Registry Uninstall entries
        loc = _win_registry_find_install_location("gimp")
        if loc is not None:
            _remember("gimp", loc, "registry")
            return loc, "registry"

        # Program Files scan — GIMP always installs as GIMP 3/ or GIMP N/
        # with bin/ holding gimp-X.Y.exe.
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            pf = os.environ.get(env, "").strip()
            if not pf:
                continue
            pf_path = Path(pf)
            for gdir_pattern in ("GIMP 3", "GIMP 2", "GIMP", "GIMP3", "GIMP2"):
                gdir = pf_path / gdir_pattern
                if not gdir.is_dir():
                    continue
                for exe_name in ("gimp-3.2.exe", "gimp-3.0.exe",
                                   "gimp-2.10.exe", "gimp.exe"):
                    if (gdir / "bin" / exe_name).is_file():
                        _remember("gimp", gdir, "program-files")
                        return gdir, "program-files"

        # PortableApps (USB / portable)
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if not (bitmask & (1 << i)):
                    continue
                drive_root = Path(chr(ord("A") + i) + ":\\")
                try:
                    for d in drive_root.glob("PortableApps/GIMPPortable*"):
                        # Portable apps usually have App/gimp/bin/
                        for p in d.glob("App/gimp*/bin/gimp*.exe"):
                            _remember("gimp", p.parent.parent, "portable-apps")
                            return p.parent.parent, "portable-apps"
                except (OSError, PermissionError):
                    continue
        except Exception:
            pass
    elif sys.platform == "darwin":
        for p in (Path("/Applications/GIMP.app"),
                   Path("/Applications/GIMP-3.0.app"),
                   Path("/Applications/GIMP-2.10.app")):
            if p.exists():
                _remember("gimp", p, "applications")
                return p, "applications"
    else:  # Linux
        for prefix in ("/usr/bin", "/usr/local/bin", "/snap/bin"):
            for exe in ("gimp", "gimp-3.0", "gimp-3.2"):
                p = Path(prefix) / exe
                if p.is_file():
                    _remember("gimp", p.parent, "posix-prefix")
                    return p.parent, "posix-prefix"

    # Final fallback — generic binary search with bin/ subdir support
    names = ["gimp-3.0.exe", "gimp-3.2.exe", "gimp-2.10.exe", "gimp.exe",
              "gimp"]
    p, strat = find_binary_robust(cfg, "gimp", names, depth=3, max_visits=4000)
    if p is not None:
        # Exe is at <install>/bin/<exe> — return install root
        install_root = p.parent
        if install_root.name.lower() in ("bin", "binaries"):
            install_root = install_root.parent
        return install_root, strat
    return None, "none"


def find_darktable_install(cfg: dict[str, Any]) -> tuple[Path | None, str]:
    """Find Darktable install root — parallel logic to GIMP."""
    import shutil
    explicit = (cfg.get("darktable_root") or "").strip()
    if explicit:
        p = Path(os.path.expanduser(explicit))
        if p.is_dir():
            return p, "config-override"
    cached = _cached("darktable")
    if cached is not None:
        return cached, "cache-hit"

    for name in ("darktable", "darktable-cli"):
        exe = shutil.which(name)
        if exe:
            p = Path(exe).resolve()
            install_root = p.parent
            if install_root.name.lower() in ("bin", "binaries"):
                install_root = install_root.parent
            _remember("darktable", install_root, "which")
            return install_root, "which"

    if os.name == "nt":
        loc = _win_registry_find_install_location("darktable")
        if loc is not None:
            _remember("darktable", loc, "registry")
            return loc, "registry"
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            pf = os.environ.get(env, "").strip()
            if not pf:
                continue
            for sub in ("darktable",):
                p = Path(pf) / sub / "bin" / "darktable.exe"
                if p.is_file():
                    _remember("darktable", p.parent.parent, "program-files")
                    return p.parent.parent, "program-files"
    elif sys.platform == "darwin":
        for p in (Path("/Applications/darktable.app"),):
            if p.exists():
                _remember("darktable", p, "applications")
                return p, "applications"

    names = ["darktable.exe", "darktable"]
    p, strat = find_binary_robust(cfg, "darktable", names)
    if p is not None:
        install_root = p.parent
        if install_root.name.lower() in ("bin", "binaries"):
            install_root = install_root.parent
        return install_root, strat
    return None, "none"


def find_sillytavern_install(cfg: dict[str, Any]) -> tuple[Path | None, str]:
    explicit = (cfg.get("sillytavern_root") or "").strip()
    if explicit:
        p = Path(os.path.expanduser(explicit))
        if p.is_dir():
            return p, "config-override"
    cached = _cached("sillytavern")
    if cached is not None:
        return cached, "cache-hit"
    # SillyTavern ships as Node — look for server.js under SillyTavern/
    roots = _candidate_roots()
    hits = _walk_for_needle(roots, "sillytavern", max_depth=3,
                              max_visits=4000)
    for h in hits:
        if (h / "server.js").is_file() or (h / "start.bat").is_file():
            _remember("sillytavern", h, "deep-glob")
            return h, "deep-glob"
    return None, "none"


# ─── Public: /diagnostic endpoint backing ────────────────────────────

def detect_all(cfg: dict[str, Any]) -> dict[str, Any]:
    """One-shot report of what we detected, what strategies fired, and
    the cache state. Backs the /diag/detector endpoint.
    Covers ComfyUI, Kobold, Ollama, Resolve, GIMP, Darktable, SillyTavern —
    so the user sees a comprehensive picture of what's installed on
    this antenna's host."""
    out: dict[str, Any] = {"cache_path": str(_STATE_PATH),
                             "cache": _load_state(),
                             "results": {}}

    # ComfyUI (launch target — includes launcher strategy)
    root, strat = find_comfyui_root_robust(cfg)
    out["results"]["comfyui"] = {
        "root": root.as_posix() if root else None,
        "strategy": strat,
    }
    if root is not None:
        launcher = find_comfyui_launcher_robust(cfg)
        if launcher:
            argv, cwd, lstrat = launcher
            out["results"]["comfyui"]["launcher"] = argv[0]
            out["results"]["comfyui"]["launcher_strategy"] = lstrat

    # Kobold (launch target)
    p, strat = find_binary_robust(
        cfg, "kobold",
        ["koboldcpp.exe", "koboldcpp_cuda.exe", "koboldcpp"],
    )
    out["results"]["kobold"] = {
        "path": p.as_posix() if p else None,
        "strategy": strat,
    }

    # Ollama (launch target)
    p, strat = find_binary_robust(cfg, "ollama", ["ollama.exe", "ollama"])
    out["results"]["ollama"] = {
        "path": p.as_posix() if p else None,
        "strategy": strat,
    }

    # DaVinci Resolve (detection-only — user launches manually)
    root, strat = find_resolve_install(cfg)
    out["results"]["resolve"] = {
        "root": root.as_posix() if root else None,
        "strategy": strat,
    }

    # GIMP (detection-only)
    root, strat = find_gimp_install(cfg)
    out["results"]["gimp"] = {
        "root": root.as_posix() if root else None,
        "strategy": strat,
    }

    # Darktable (detection-only)
    root, strat = find_darktable_install(cfg)
    out["results"]["darktable"] = {
        "root": root.as_posix() if root else None,
        "strategy": strat,
    }

    # SillyTavern (detection-only)
    root, strat = find_sillytavern_install(cfg)
    out["results"]["sillytavern"] = {
        "root": root.as_posix() if root else None,
        "strategy": strat,
    }

    return out
