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


# ─── R50b: render-queue driver ────────────────────────────────────────────

def render_timeline(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /resolve/render-timeline

    Add the CURRENT timeline of the CURRENT project to Resolve's render
    queue, start rendering, and return a job handle. Progress can be
    polled via GET /resolve/render-status?job_id=<handle>.

    Body:
        {
          "preset":     "H.264 Master",   # render preset name (must exist in Resolve)
          "target_dir": "<absolute path>", # where Resolve writes the output
          "file_name":  "spellcaster_cut"  # base name (Resolve appends ext)
        }

    The preset MUST exist in Resolve's configured render presets. The
    antenna does not create presets; the user is expected to pick one
    that's already saved. Defaults to "H.264 Master" which ships with
    most Resolve installs.
    """
    cfg = ctx.get("config") or {}
    app, err = _get_resolve(cfg)
    if app is None:
        return 503, {"error": err}

    body = ctx.get("body") or {}
    preset = (body.get("preset") or "H.264 Master").strip()
    target_dir = (body.get("target_dir") or "").strip()
    file_name = (body.get("file_name") or "spellcaster_cut").strip()
    if not target_dir:
        return 400, {"error": "target_dir required (absolute path)"}
    if not os.path.isdir(target_dir):
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as e:
            return 400, {"error": f"target_dir not usable: {e}"}

    try:
        pm = app.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"could not query ProjectManager: {e}"}
    if project is None:
        return 503, {"error": "No active Resolve project"}

    try:
        timeline = project.GetCurrentTimeline()
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"could not query current timeline: {e}"}
    if timeline is None:
        return 400, {"error": "No current timeline in Resolve — "
                              "open the timeline you want to render first"}

    # Resolve API: LoadRenderPreset, SetRenderSettings, AddRenderJob, StartRendering
    try:
        preset_loaded = project.LoadRenderPreset(preset)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"LoadRenderPreset crashed: {e}"}
    if not preset_loaded:
        # Enumerate presets so the user sees what's actually available
        try:
            available = list(project.GetRenderPresetList() or [])
        except Exception:
            available = []
        return 400, {
            "error": f"Render preset {preset!r} not found in this project",
            "available_presets": available[:40],
        }

    try:
        project.SetRenderSettings({
            "TargetDir": target_dir,
            "CustomName": file_name,
        })
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"SetRenderSettings failed: {e}"}

    try:
        job_id = project.AddRenderJob()
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"AddRenderJob failed: {e}"}
    if not job_id:
        return 500, {"error": "AddRenderJob returned empty job id"}

    # StartRendering([job_id]) — isRenderingInAllViewerMode off; just this job
    try:
        started = project.StartRendering([job_id])
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"StartRendering failed: {e}"}
    if not started:
        return 500, {"error": "StartRendering returned false — "
                              "is another render already in progress?"}

    try:
        timeline_name = timeline.GetName()
    except Exception:
        timeline_name = None

    result = {
        "ok": True,
        "job_id": job_id,
        "project": project.GetName(),
        "timeline": timeline_name,
        "preset": preset,
        "target_dir": target_dir,
        "file_name": file_name,
    }
    try:
        from .. import bus_client
        bus_client.emit(ctx, "antenna.resolve.render_started", result)
    except Exception:
        pass
    # R51b: spawn a bg watcher that will emit render_progress + render_complete
    try:
        _start_render_watcher(ctx, job_id, project.GetName())
    except Exception as e:  # noqa: BLE001 — watcher failure never blocks the start
        print(f"[resolve] warn: render watcher failed to start: {e}",
              file=sys.stderr)
    return 200, result


def list_luts(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /resolve/luts

    Enumerate every LUT that Resolve can see on this machine. Walks the
    standard Blackmagic LUT directories (per-OS) plus any user-configured
    extra dirs declared in antenna_config.json:`resolve_lut_dirs`.

    Returns:
        {
          "luts_by_category": {
            "Creative": [{"name": "Kodak 2383", "path": "...", "ext": ".cube"}, ...],
            "Legal": [...]
          },
          "total": 1234,
          "scanned_dirs": ["..."]
        }

    This endpoint does NOT require Resolve to be running — it just reads
    the filesystem. Cached for 60s to make capability-discovery cheap.
    """
    # Cached result per-process (module-level since each endpoint call
    # spawns a fresh handler but the module is long-lived).
    global _LUT_CACHE, _LUT_CACHE_TS
    now = time.time()
    if _LUT_CACHE is not None and (now - _LUT_CACHE_TS) < 60.0:
        return 200, _LUT_CACHE

    cfg = ctx.get("config") or {}
    scanned: list[str] = []
    by_cat: dict[str, list[dict[str, Any]]] = {}
    total = 0

    # Candidate LUT roots — Blackmagic ships LUTs here. Order matters only
    # for the "scanned_dirs" field; duplicates across dirs are de-duped.
    roots: list[Path] = []
    if sys.platform.startswith("win"):
        roots += [
            Path(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT"),
            Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\LUT"),
        ]
    elif sys.platform == "darwin":
        roots += [
            Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT"),
            Path(os.path.expanduser(
                "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT")),
        ]
    else:
        roots += [
            Path("/opt/resolve/LUT"),
            Path(os.path.expanduser("~/.local/share/DaVinciResolve/LUT")),
        ]
    # User overrides from antenna_config.resolve_lut_dirs (list or comma-string)
    extra = cfg.get("resolve_lut_dirs") or []
    if isinstance(extra, str):
        extra = [p.strip() for p in extra.split(",") if p.strip()]
    for e in extra:
        roots.append(Path(os.path.expanduser(str(e))))

    # LUT file extensions Resolve understands (docs: .cube, .3dl, .ilut, .olut)
    exts = {".cube", ".3dl", ".ilut", ".olut", ".csp", ".dat"}
    seen: set[str] = set()

    for root in roots:
        if not root.is_dir():
            continue
        scanned.append(str(root))
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                ext = path.suffix.lower()
                if ext not in exts:
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                # Category = first directory under root (e.g. "Creative",
                # "Legal", "Film"). LUTs directly under root fall into "(root)".
                try:
                    rel = path.relative_to(root)
                    cat = rel.parts[0] if len(rel.parts) > 1 else "(root)"
                except ValueError:
                    cat = "(root)"
                by_cat.setdefault(cat, []).append({
                    "name": path.stem,
                    "path": str(path),
                    "ext": ext,
                })
                total += 1
        except OSError:
            # Permission or network issue on one root — skip, don't fail others
            continue

    # Stable ordering inside each category
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x["name"].lower())

    result = {
        "luts_by_category": by_cat,
        "total": total,
        "scanned_dirs": scanned,
    }
    _LUT_CACHE = result
    _LUT_CACHE_TS = now
    return 200, result


# Module-level LUT cache (60s TTL)
_LUT_CACHE: dict[str, Any] | None = None
_LUT_CACHE_TS: float = 0.0


def render_presets(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /resolve/render-presets

    Return the list of render preset names available to the current
    Resolve project. Populates the dropdown in the Guild's Render dialog
    so users don't have to type a preset name.
    """
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
        return 503, {"error": "No active Resolve project"}
    try:
        presets = list(project.GetRenderPresetList() or [])
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"GetRenderPresetList failed: {e}"}
    return 200, {"presets": presets, "project": project.GetName()}


# ─── R55: project picker ─────────────────────────────────────────────────

def projects(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /resolve/projects

    Enumerate Resolve projects reachable from the currently-open folder.
    Unlike the render dialog which only targets the current project, the
    project picker lets the Guild ask the user which project to target
    BEFORE any send-to-Resolve action. Returns the project list, the
    current folder path, sibling folders for drilling, and the currently
    loaded project (if any) so the UI can mark it as selected.

    Shape:
        {
          "current_project": "My Edit" | null,
          "current_folder":  "Demos/Shortfilm",
          "folders":         ["Archive", "Sound Design"],
          "projects":        ["My Edit", "My Edit — backup"]
        }

    Resolve scripting has no cross-folder enumeration — "projects in
    current folder" is literally what the API exposes. Callers that want
    to browse up/down must POST /resolve/project-folder first; keeping the
    GET side stateless (reads only current folder) means no shared
    session lock in the antenna.
    """
    cfg = ctx.get("config") or {}
    app, err = _get_resolve(cfg)
    if app is None:
        return 503, {"error": err}
    try:
        pm = app.GetProjectManager()
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"could not query ProjectManager: {e}"}
    if pm is None:
        return 503, {"error": "ProjectManager unavailable"}
    out: dict[str, Any] = {}
    try:
        current_proj = pm.GetCurrentProject()
        out["current_project"] = (current_proj.GetName()
                                  if current_proj else None)
    except Exception as e:  # noqa: BLE001
        out["current_project"] = None
        out["current_project_error"] = f"{type(e).__name__}: {e}"
    # Folder context. Some older Resolve versions omit GetCurrentFolder so
    # we guard each call individually and report partial state rather than
    # 500'ing the whole response.
    try:
        out["current_folder"] = pm.GetCurrentFolder() or ""
    except Exception as e:  # noqa: BLE001
        out["current_folder"] = ""
        out["current_folder_error"] = f"{type(e).__name__}: {e}"
    try:
        out["folders"] = list(pm.GetFolderListInCurrentFolder() or [])
    except Exception as e:  # noqa: BLE001
        out["folders"] = []
        out["folders_error"] = f"{type(e).__name__}: {e}"
    try:
        out["projects"] = list(pm.GetProjectListInCurrentFolder() or [])
    except Exception as e:  # noqa: BLE001
        out["projects"] = []
        out["projects_error"] = f"{type(e).__name__}: {e}"
    return 200, out


def load_project(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /resolve/load-project  body: { "name": "<project name>" }

    Open the named project in the current folder. Fails fast if nothing
    matches — a typo should not silently leave the previous project
    loaded. The picker UI resolves the name it got from /projects and
    posts it verbatim; we don't globally search, only the current folder.
    """
    cfg = ctx.get("config") or {}
    body = ctx.get("body") or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return 400, {"error": "missing 'name'"}
    app, err = _get_resolve(cfg)
    if app is None:
        return 503, {"error": err}
    try:
        pm = app.GetProjectManager()
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"could not query ProjectManager: {e}"}
    if pm is None:
        return 503, {"error": "ProjectManager unavailable"}
    try:
        available = list(pm.GetProjectListInCurrentFolder() or [])
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"GetProjectListInCurrentFolder failed: {e}"}
    if name not in available:
        return 404, {
            "error": f"Project {name!r} not found in current folder",
            "available": available,
        }
    try:
        loaded = pm.LoadProject(name)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"LoadProject raised: {type(e).__name__}: {e}"}
    if not loaded:
        return 500, {"error": f"LoadProject({name!r}) returned falsy"}
    try:
        current = pm.GetCurrentProject()
        current_name = current.GetName() if current else None
    except Exception:
        current_name = None
    return 200, {"ok": True, "current_project": current_name}


# ─── R51b: render-complete watcher (bg thread + bus emit) ─────────────────

_RENDER_WATCHERS: dict[str, dict[str, Any]] = {}
_RENDER_WATCHERS_LOCK = None


def _start_render_watcher(ctx: dict[str, Any], job_id: str,
                          project_name: str) -> None:
    """Spawn a daemon thread that polls Resolve's render job until it
    reaches a terminal state, then emits `antenna.resolve.render_complete`.

    One watcher per job_id. Idempotent — if a watcher is already tracking
    this job, this is a no-op.
    """
    global _RENDER_WATCHERS_LOCK
    import threading
    if _RENDER_WATCHERS_LOCK is None:
        _RENDER_WATCHERS_LOCK = threading.Lock()
    with _RENDER_WATCHERS_LOCK:
        if job_id in _RENDER_WATCHERS:
            return
        _RENDER_WATCHERS[job_id] = {"started_at": time.time(),
                                     "project": project_name}

    def _watch():
        import time as _time
        try:
            # Keep polling until terminal status. Resolve uses strings:
            #   "Rendering", "Complete", "Cancelled", "Failed"
            cfg = ctx.get("config") or {}
            last_pct = -1
            terminal = {"Complete", "Cancelled", "Failed"}
            poll_interval = 5.0  # seconds between polls
            max_runs = 7200      # 10 hours ceiling (poll_interval * max_runs)
            for _ in range(max_runs):
                _time.sleep(poll_interval)
                app, err = _get_resolve(cfg)
                if app is None:
                    # Resolve went away mid-render — report and exit
                    try:
                        from .. import bus_client
                        bus_client.emit(ctx, "antenna.resolve.render_complete",
                                        {"job_id": job_id, "status": "Unknown",
                                         "reason": err or "Resolve disconnected"})
                    except Exception:
                        pass
                    return
                try:
                    pm = app.GetProjectManager()
                    project = pm.GetCurrentProject() if pm else None
                    if project is None:
                        continue
                    status = project.GetRenderJobStatus(job_id) or {}
                except Exception:
                    continue
                js = status.get("JobStatus", "Unknown")
                pct = status.get("CompletionPercentage")
                # Emit progress periodically — every 10% change reduces noise
                if isinstance(pct, (int, float)) and (pct - last_pct) >= 10:
                    last_pct = int(pct)
                    try:
                        from .. import bus_client
                        bus_client.emit(ctx, "antenna.resolve.render_progress",
                                        {"job_id": job_id, "completion_percent": last_pct,
                                         "status": js})
                    except Exception:
                        pass
                if js in terminal:
                    try:
                        from .. import bus_client
                        bus_client.emit(ctx, "antenna.resolve.render_complete", {
                            "job_id": job_id,
                            "status": js,
                            "completion_percent": pct,
                            "project": project_name,
                            "time_elapsed_s": (status.get("TimeTakenToRenderInMs", 0) or 0) / 1000.0,
                        })
                    except Exception:
                        pass
                    return
        finally:
            with _RENDER_WATCHERS_LOCK:
                _RENDER_WATCHERS.pop(job_id, None)

    t = threading.Thread(target=_watch, daemon=True,
                         name=f"resolve-render-watch-{job_id[:8]}")
    t.start()


def render_status(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /resolve/render-status?job_id=<id>

    Polls Resolve for the status of a render job. Returns:
        {"job_id": "...", "status": "Rendering|Complete|Cancelled|Failed",
         "completion_percent": 73, "time_elapsed": 42.1}
    """
    cfg = ctx.get("config") or {}
    app, err = _get_resolve(cfg)
    if app is None:
        return 503, {"error": err}

    # job_id comes from query string
    raw_path = ctx.get("raw_path", "") or ctx.get("path", "")
    job_id = ""
    if "?" in raw_path:
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(raw_path).query)
            job_id = (qs.get("job_id") or [""])[0].strip()
        except Exception:
            job_id = ""
    if not job_id:
        return 400, {"error": "job_id query parameter required"}

    try:
        pm = app.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"could not query ProjectManager: {e}"}
    if project is None:
        return 503, {"error": "No active Resolve project"}

    # GetRenderJobStatus returns a dict
    try:
        status = project.GetRenderJobStatus(job_id)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"GetRenderJobStatus failed: {e}"}
    if status is None:
        return 404, {"error": f"job_id {job_id!r} not found in render queue"}

    # Normalize keys — Resolve returns things like JobStatus, CompletionPercentage, etc.
    out: dict[str, Any] = {
        "job_id": job_id,
        "status": status.get("JobStatus"),
        "completion_percent": status.get("CompletionPercentage"),
        "time_elapsed_s": status.get("TimeTakenToRenderInMs", 0) / 1000.0
            if isinstance(status.get("TimeTakenToRenderInMs"), (int, float)) else None,
        "estimated_time_remaining_s": status.get("EstimatedTimeRemainingInMs", 0) / 1000.0
            if isinstance(status.get("EstimatedTimeRemainingInMs"), (int, float)) else None,
    }
    # Pass through raw for debugging
    out["raw"] = {k: v for k, v in status.items()
                  if isinstance(v, (str, int, float, bool))}
    return 200, out
