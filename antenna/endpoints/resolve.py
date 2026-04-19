"""DaVinci Resolve scripting endpoints — antenna-driven timeline import.

This endpoint is co-located with Resolve on the antenna host because the
Resolve scripting API is IPC-local — it talks to the running Resolve
process via a Fusion script bridge that doesn't traverse the network.
A remote Guild cannot script Resolve directly; it has to ask the antenna.

Handlers:

    GET  /resolve/ping
        Unauthenticated-ish liveness for Resolve. Returns:
          { "running": true,  "version": "19.0.3", "project": "My Project" }
          { "running": false, "reason": "Resolve not running" }
          { "running": false, "reason": "scripting module not found" }

    POST /resolve/import-edl
        Body: { "edl": "<EDL text>", "bin": "Spellcaster", "fps": 30 }
        Writes the EDL to a temp file and calls
        ``MediaPool.ImportTimelineFromFile(path)``. Returns the new
        timeline name on success, or a descriptive error.

    POST /resolve/import-fcpxml
        Same contract as /import-edl but for FCPXML text.

Security
--------
Driving Resolve is a privileged action — an attacker with the antenna
bearer token could fill a user's project with junk timelines. All
handlers require the standard antenna auth (rate-limited + bearer).

Idempotency
-----------
We do NOT dedupe on EDL content. Two identical POSTs create two
timelines. The caller is expected to be a human-driven "Send to Resolve"
button, not an automated poller.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


# ─── Resolve Python module discovery ──────────────────────────────────────
#
# The DaVinciResolveScript module ships with Resolve. Its location depends
# on OS. We probe all known install locations and add the first that
# exists to sys.path, then import. Failure is non-fatal — the endpoint
# returns a structured error.

_RESOLVE_SCRIPT_PATHS_WINDOWS = [
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer"
    r"\Scripting\Modules",
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Support\Developer"
    r"\Scripting\Modules",
]
_RESOLVE_SCRIPT_PATHS_MACOS = [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve"
    "/Developer/Scripting/Modules",
]
_RESOLVE_SCRIPT_PATHS_LINUX = [
    "/opt/resolve/Developer/Scripting/Modules",
    "/home/resolve/Developer/Scripting/Modules",
]


def _find_resolve_script_dir(cfg: dict[str, Any] | None = None) -> Path | None:
    """Return the first existing Modules/ dir that likely hosts
    DaVinciResolveScript.py, honoring an explicit config override first.
    """
    explicit = ((cfg or {}).get("resolve_script_dir") or "").strip()
    if explicit and explicit != "auto":
        p = Path(os.path.expanduser(explicit))
        if p.is_dir():
            return p
    # RESOLVE_SCRIPT_API is the official Blackmagic env var
    env_dir = os.environ.get("RESOLVE_SCRIPT_API", "").strip()
    if env_dir:
        candidate = Path(env_dir) / "Scripting" / "Modules"
        if candidate.is_dir():
            return candidate
        # Some installs use RESOLVE_SCRIPT_API=<Scripting> directly
        candidate2 = Path(env_dir) / "Modules"
        if candidate2.is_dir():
            return candidate2
    if sys.platform.startswith("win"):
        candidates = _RESOLVE_SCRIPT_PATHS_WINDOWS
    elif sys.platform == "darwin":
        candidates = _RESOLVE_SCRIPT_PATHS_MACOS
    else:
        candidates = _RESOLVE_SCRIPT_PATHS_LINUX
    for c in candidates:
        p = Path(c)
        if p.is_dir():
            return p
    return None


def _import_resolve_script(cfg: dict[str, Any] | None = None):
    """Return (module, error_str). module is None on failure."""
    modules_dir = _find_resolve_script_dir(cfg)
    if modules_dir is None:
        return None, ("DaVinciResolveScript module dir not found — "
                      "Resolve may not be installed. Set resolve_script_dir "
                      "in antenna_config.json to override.")
    mod_path = str(modules_dir)
    if mod_path not in sys.path:
        sys.path.insert(0, mod_path)
    try:
        import DaVinciResolveScript as dvr_script  # type: ignore
        return dvr_script, None
    except ImportError as e:
        return None, f"failed to import DaVinciResolveScript: {e}"
    except Exception as e:  # noqa: BLE001 — Fusion script raises strange things
        return None, f"DaVinciResolveScript import error: {type(e).__name__}: {e}"


def _get_resolve(cfg: dict[str, Any] | None = None):
    """Return (resolve_app, error). resolve_app is None if Resolve isn't
    running — scriptapp('Resolve') returns None in that case.
    """
    dvr, err = _import_resolve_script(cfg)
    if dvr is None:
        return None, err
    try:
        app = dvr.scriptapp("Resolve")
    except Exception as e:  # noqa: BLE001
        return None, f"scriptapp call failed: {type(e).__name__}: {e}"
    if app is None:
        return None, ("Resolve is not running or scripting is disabled. "
                      "Start Resolve and enable External scripting under "
                      "Preferences > System > General.")
    return app, None


# ─── GET /resolve/ping ────────────────────────────────────────────────────

def ping(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /resolve/ping — is Resolve running and scriptable?"""
    cfg = ctx.get("config") or {}
    app, err = _get_resolve(cfg)
    if app is None:
        return 200, {"running": False, "reason": err}
    info: dict[str, Any] = {"running": True}
    try:
        pm = app.GetProjectManager()
        proj = pm.GetCurrentProject() if pm else None
        info["project"] = proj.GetName() if proj else None
    except Exception as e:  # noqa: BLE001
        info["project"] = None
        info["project_error"] = f"{type(e).__name__}: {e}"
    try:
        info["version"] = getattr(app, "GetVersionString", lambda: None)()
    except Exception:
        pass
    return 200, info


# ─── Shared timeline-import core ──────────────────────────────────────────

def _ensure_bin(project: Any, bin_name: str) -> Any:
    """Find or create a media-pool bin with the given name. Returns the bin
    object, or the root folder if creation fails (safer than exploding)."""
    try:
        media_pool = project.GetMediaPool()
        if not media_pool:
            return None
        root = media_pool.GetRootFolder()
        if not bin_name or bin_name == "/":
            return root
        # Search existing children
        for folder in (root.GetSubFolderList() or []):
            try:
                if folder.GetName() == bin_name:
                    media_pool.SetCurrentFolder(folder)
                    return folder
            except Exception:
                continue
        # Not found — create it
        created = media_pool.AddSubFolder(root, bin_name)
        if created:
            media_pool.SetCurrentFolder(created)
            return created
        return root
    except Exception:
        return None


def _import_timeline(ctx: dict[str, Any], raw: str, suffix: str,
                     default_bin: str = "Spellcaster") -> tuple[int, dict]:
    """Shared timeline-import implementation for both EDL and FCPXML."""
    if not raw or not raw.strip():
        return 400, {"error": "empty timeline body"}

    cfg = ctx.get("config") or {}
    app, err = _get_resolve(cfg)
    if app is None:
        return 503, {"error": err}

    try:
        pm = app.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"could not query ProjectManager: {e}"}
    if project is None:
        return 503, {
            "error": "No active Resolve project. Open or create a project "
                     "in Resolve first."
        }

    # Stage the timeline file on disk — ImportTimelineFromFile takes a path,
    # not in-memory text. Use a named temp file, prefixed for debuggability.
    body = ctx.get("body") or {}
    bin_name = (body.get("bin") or default_bin).strip() or default_bin
    _ensure_bin(project, bin_name)

    try:
        fd, temp_path = tempfile.mkstemp(prefix="spellcaster_timeline_",
                                          suffix=suffix)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
    except OSError as e:
        return 500, {"error": f"could not stage temp file: {e}"}

    t_start = time.time()
    try:
        media_pool = project.GetMediaPool()
        if not media_pool:
            return 500, {"error": "could not get media pool"}
        timeline = media_pool.ImportTimelineFromFile(temp_path)
    except Exception as e:  # noqa: BLE001 — Fusion script raises anything
        return 500, {"error": f"ImportTimelineFromFile failed: "
                              f"{type(e).__name__}: {e}"}
    finally:
        # Resolve may hold the file while importing — best-effort cleanup
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    if timeline is None:
        return 500, {"error": "ImportTimelineFromFile returned None — "
                              "Resolve rejected the timeline (malformed or "
                              "incompatible fps/format)."}

    try:
        name = timeline.GetName()
    except Exception:
        name = None
    took = round(time.time() - t_start, 2)
    result = {
        "ok": True,
        "timeline_name": name,
        "project": project.GetName(),
        "bin": bin_name,
        "took_seconds": took,
    }
    # Tell the hub so its UI can react
    try:
        from .. import bus_client
        bus_client.emit(ctx, "antenna.resolve.timeline_imported", result)
    except Exception:
        pass
    return 200, result


# ─── POST /resolve/import-edl ─────────────────────────────────────────────

def import_edl(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /resolve/import-edl

    Request body: {"edl": "<EDL text>", "bin": "Spellcaster"}
    """
    body = ctx.get("body") or {}
    edl = body.get("edl") or ""
    return _import_timeline(ctx, edl, suffix=".edl")


# ─── POST /resolve/import-fcpxml ──────────────────────────────────────────

def import_fcpxml(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /resolve/import-fcpxml

    Request body: {"fcpxml": "<FCPXML text>", "bin": "Spellcaster"}
    """
    body = ctx.get("body") or {}
    xml = body.get("fcpxml") or ""
    return _import_timeline(ctx, xml, suffix=".fcpxml")
