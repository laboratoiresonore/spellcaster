"""Resolve plugin install/refresh — antenna-driven deployment.

Zero-touch update path for the DaVinci Resolve bridge. The antenna
lives on the same box as Resolve (licensed Studio installs are
antenna-local per the Spellcaster architecture), so IT can write
directly into Resolve's Workflow Integration Plugins and
Fusion/Scripts/Utility/Spellcaster/ directories — no SCP, no manual
copy, no zipped release.

Handlers
--------

    GET  /resolve/plugin/status
        { installed: bool,
          workflow_integration_dir: "...",
          scripts_dir: "...",
          installed_version: "<sha>" | null,
          src_version: "<sha>",
          src_root: "...",
          files_in_place: int }

    POST /resolve/plugin/install
        Body: { "force": bool = false }
        Copies the plugin tree from the antenna's own source checkout
        (same tree self-update pulls) into Resolve's plugin dirs. Safe
        to run while Resolve is open — Resolve re-discovers scripts on
        next menu open, Workflow Integration Plugins require a restart
        to pick up fresh code. Response lists every file written.

Invariants
----------
- ``resolve`` must be a declared service on this antenna. If it's not,
  the routes are not registered at all (same pattern as /resolve/ping).
- The install is idempotent: same src → same destination paths → same
  content hashes. Running twice does nothing on the second pass unless
  ``force=true`` is set.
- We write into a staging dir then atomically swap, so a partially-copied
  plugin never exists on disk (Resolve would try to import it).
- No file is ever DELETED outside the install target dirs, even on force.
"""
from __future__ import annotations

from .. import _silent
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


# ─── Destination dir discovery ───────────────────────────────────────────


# R84a: Resolve's Scripts menu is page-specific — scripts in
# ``Fusion/Scripts/<PAGE>/`` appear only on that page's Workspace >
# Scripts menu. Install into ALL of them so Spellcaster is one click
# away from anywhere in Resolve. ``Utility`` is the always-available
# catchall, the others are page-specific (Edit, Fusion/Comp, Color,
# Deliver). We also surface under ``Comp`` (the Fusion page folder).
_FUSION_SUBFOLDERS = ("Utility", "Edit", "Comp", "Color", "Deliver")

# R104: the Spellcaster submenu header carries a diamond so it stands
# out in Resolve's menu maze. The leaf folder name becomes the
# submenu label; per-script names are also diamond-prefixed in
# install_plugin_from_src.
_SPELLCASTER_FOLDER_NAME = "\U0001F48E Spellcaster"

_WIN_WFI_DIR = (
    r"{APPDATA}\Blackmagic Design\DaVinci Resolve"
    r"\Support\Workflow Integration Plugins"
)
_WIN_SCRIPTS_BASE = (
    r"{APPDATA}\Blackmagic Design\DaVinci Resolve"
    r"\Support\Fusion\Scripts"
)
_WIN_SCRIPTS_DIR = (_WIN_SCRIPTS_BASE
                     + r"\Utility\\" + _SPELLCASTER_FOLDER_NAME)
_MAC_WFI_DIR = (
    "{HOME}/Library/Application Support/Blackmagic Design/DaVinci Resolve"
    "/Workflow Integration Plugins"
)
_MAC_SCRIPTS_BASE = (
    "{HOME}/Library/Application Support/Blackmagic Design/DaVinci Resolve"
    "/Fusion/Scripts"
)
_MAC_SCRIPTS_DIR = _MAC_SCRIPTS_BASE + "/Utility/" + _SPELLCASTER_FOLDER_NAME
_LINUX_WFI_DIR = "{HOME}/.local/share/DaVinciResolve/Workflow Integration Plugins"
_LINUX_SCRIPTS_BASE = "{HOME}/.local/share/DaVinciResolve/Fusion/Scripts"
_LINUX_SCRIPTS_DIR = (_LINUX_SCRIPTS_BASE + "/Utility/"
                       + _SPELLCASTER_FOLDER_NAME)


def _expand(p: str) -> Path:
    env = {"APPDATA": os.environ.get("APPDATA", ""),
           "HOME": os.path.expanduser("~")}
    return Path(p.format(**env)).resolve()


def detect_plugin_dirs(cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    """Return absolute paths for this host's Resolve plugin destinations.

    Honors explicit overrides in the antenna config:
      resolve_plugin_workflow_dir, resolve_plugin_scripts_dir.
    Otherwise falls back to OS-standard locations.

    ``scripts`` is the primary install dir (Utility/Spellcaster — always
    available). ``scripts_base`` is the parent Scripts root, used by
    R84a to additionally install into Edit/Comp/Color/Deliver.
    """
    cfg = cfg or {}
    override_wfi = (cfg.get("resolve_plugin_workflow_dir") or "").strip()
    override_scripts = (cfg.get("resolve_plugin_scripts_dir") or "").strip()

    if os.name == "nt":
        wfi = _expand(override_wfi or _WIN_WFI_DIR)
        scripts = _expand(override_scripts or _WIN_SCRIPTS_DIR)
        scripts_base = _expand(_WIN_SCRIPTS_BASE)
    elif sys.platform == "darwin":
        wfi = _expand(override_wfi or _MAC_WFI_DIR)
        scripts = _expand(override_scripts or _MAC_SCRIPTS_DIR)
        scripts_base = _expand(_MAC_SCRIPTS_BASE)
    else:
        wfi = _expand(override_wfi or _LINUX_WFI_DIR)
        scripts = _expand(override_scripts or _LINUX_SCRIPTS_DIR)
        scripts_base = _expand(_LINUX_SCRIPTS_BASE)

    return {
        "workflow_integration": wfi,
        "scripts": scripts,
        "scripts_base": scripts_base,
    }


# ─── Source discovery (same tree self-update pulls) ──────────────────────


def _src_root() -> Path:
    """Return the spellcaster repo root that this antenna is running from."""
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / "antenna").is_dir() and (parent / "plugins").is_dir():
            return parent
    return Path(__file__).resolve().parents[2]


def _resolve_plugin_src_root() -> Path:
    return _src_root() / "plugins" / "resolve"


def _git_sha(root: Path) -> str:
    """Current HEAD SHA of the source tree, or '' if not a git repo."""
    try:
        import subprocess
        r = _silent.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


# ─── Install logic ───────────────────────────────────────────────────────


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _ignore_pycache(_dir: str, names: list[str]) -> list[str]:
    """shutil.copytree ignore-predicate — skip __pycache__ and .pyc files."""
    return [n for n in names if n == "__pycache__" or n.endswith(".pyc")]


def _copy_tree_atomic(src: Path, dest: Path) -> int:
    """Stage src → temp sibling → atomic swap onto dest. Returns file count.

    `dest` is replaced in full; anything previously there is wiped. The
    staging dir is a sibling of dest so rename is always same-filesystem.
    """
    if not src.is_dir():
        raise FileNotFoundError(f"source missing: {src}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=dest.name + "_staging_",
                                      dir=str(dest.parent)))
    try:
        shutil.copytree(src, staging, dirs_exist_ok=True,
                         ignore=_ignore_pycache)
        count = sum(1 for _ in staging.rglob("*") if _.is_file())
        backup = dest.with_suffix(dest.suffix + ".bak")
        if dest.exists():
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            dest.rename(backup)
        staging.rename(dest)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        return count
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _version_stamp(dest_root: Path, sha: str) -> None:
    """Drop a .spellcaster_version file so status can report what's deployed."""
    try:
        (dest_root / ".spellcaster_version").write_text(
            json.dumps({"sha": sha, "installed_at": time.time()},
                       indent=2),
            encoding="utf-8")
    except OSError:
        pass


def _read_version(dest_root: Path) -> str:
    try:
        d = json.loads((dest_root / ".spellcaster_version")
                       .read_text(encoding="utf-8"))
        return d.get("sha", "")
    except (OSError, json.JSONDecodeError):
        return ""


def install_plugin_from_src(cfg: dict[str, Any] | None = None,
                              *, force: bool = False) -> dict[str, Any]:
    """Copy the plugins/resolve/ tree into Resolve's plugin dirs.

    Layout (both destinations end up with a local `shared/` copy so the
    scripts and the workflow integration both import successfully
    without having to walk up to a parent dir):

        Workflow Integration Plugins/
            spellcaster_bridge/   <- from plugins/resolve/spellcaster_bridge/
            shared/               <- from plugins/resolve/shared/
            .spellcaster_version  <- stamp

        Fusion/Scripts/Utility/Spellcaster/
            *.py                  <- from plugins/resolve/scripts/
            shared/               <- from plugins/resolve/shared/
            .spellcaster_version  <- stamp

    Idempotent: if both destinations already match the current SHA and
    force=false, this no-ops and reports what was found.
    """
    src_root = _resolve_plugin_src_root()
    if not src_root.is_dir():
        return {"ok": False, "error": f"plugin source missing at {src_root}"}

    dirs = detect_plugin_dirs(cfg)
    wfi = dirs["workflow_integration"] / "spellcaster_bridge"
    wfi_shared = dirs["workflow_integration"] / "shared"
    scripts = dirs["scripts"]
    scripts_shared = dirs["scripts"] / "shared"

    sha = _git_sha(_src_root()) or "unknown"
    installed_wfi = _read_version(dirs["workflow_integration"])
    installed_scripts = _read_version(dirs["scripts"])

    up_to_date = (sha != "unknown"
                   and installed_wfi == sha
                   and installed_scripts == sha)
    if up_to_date and not force:
        return {
            "ok": True,
            "status": "already up to date",
            "sha": sha,
            "workflow_integration_dir": str(dirs["workflow_integration"]),
            "scripts_dir": str(scripts),
            "files_copied": 0,
        }

    bridge_src = src_root / "spellcaster_bridge"
    scripts_src = src_root / "scripts"
    shared_src = src_root / "shared"

    total_files = 0
    try:
        total_files += _copy_tree_atomic(bridge_src, wfi)
        total_files += _copy_tree_atomic(shared_src, wfi_shared)
        _version_stamp(dirs["workflow_integration"], sha)

        # R84a: deploy into EVERY page-specific Scripts folder
        # (Utility/Edit/Comp/Color/Deliver) so Spellcaster appears in
        # the Workspace > Scripts menu on every page. ``Utility`` is
        # primary (pointed to by dirs["scripts"]) and stamped with
        # .spellcaster_version; the others are copies kept in sync.
        scripts_base = dirs.get("scripts_base")
        page_targets: list[Path] = []
        if scripts_base:
            for sub in _FUSION_SUBFOLDERS:
                page_targets.append(
                    scripts_base / sub / _SPELLCASTER_FOLDER_NAME)
        else:
            page_targets.append(dirs["scripts"])

        # R104: remove any legacy "Spellcaster" folder (no diamond
        # prefix) left over from pre-R104 installs so the menu
        # doesn't show BOTH "Spellcaster" and "💎 Spellcaster".
        if scripts_base:
            for sub in _FUSION_SUBFOLDERS:
                legacy = scripts_base / sub / "Spellcaster"
                if legacy.is_dir() and legacy.name != _SPELLCASTER_FOLDER_NAME:
                    try:
                        shutil.rmtree(legacy, ignore_errors=True)
                    except Exception:  # noqa: BLE001
                        pass

        # Ensure the primary ("scripts" dir, Utility) is always the
        # first target and gets the version stamp.
        primary = dirs["scripts"]
        if primary in page_targets:
            page_targets.remove(primary)
        page_targets.insert(0, primary)

        installed_pages: list[str] = []
        for target_root in page_targets:
            target_root.mkdir(parents=True, exist_ok=True)
            # R104: wipe any stale non-helper .py files left over from a
            # prior install under the old naming (pre-diamond or with a
            # different prefix). Helpers (underscore-prefixed, dotfiles,
            # __pycache__) are preserved.
            try:
                for existing in target_root.iterdir():
                    if not existing.is_file():
                        continue
                    nm = existing.name
                    if nm.startswith("_") or nm.startswith("."):
                        continue
                    if existing.suffix == ".py":
                        try:
                            existing.unlink()
                        except OSError:
                            pass
            except OSError:
                pass
            for f in scripts_src.iterdir():
                if f.is_file() and f.suffix in (".py",):
                    # R104: prefix menu-facing scripts with 💎 so they
                    # stand out in Resolve's Workspace > Scripts menu.
                    # Helpers (_spellcaster_common, __init__) keep their
                    # raw names because they're imported by other
                    # scripts via their import name — renaming them
                    # would break `import _spellcaster_common`.
                    display_name = f.name
                    if (not f.name.startswith("_")
                            and not f.name.startswith(".")):
                        display_name = "\U0001F48E " + f.name
                    target = target_root / display_name
                    tmp = target.with_suffix(target.suffix + ".new")
                    shutil.copy2(f, tmp)
                    if target.exists():
                        target.unlink()
                    tmp.rename(target)
                    total_files += 1
            # shared/ sibling of the scripts, same dir layout in each
            # page copy — matches what _script_dir() expects.
            page_shared = target_root / "shared"
            total_files += _copy_tree_atomic(shared_src, page_shared)
            installed_pages.append(target_root.parent.name
                                    if target_root.name == "Spellcaster"
                                    else target_root.name)
        _version_stamp(dirs["scripts"], sha)
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "workflow_integration_dir": str(dirs["workflow_integration"]),
            "scripts_dir": str(scripts),
            "files_copied": total_files,
        }

    return {
        "ok": True,
        "status": "installed",
        "sha": sha,
        "workflow_integration_dir": str(dirs["workflow_integration"]),
        "scripts_dir": str(scripts),
        "pages_installed": installed_pages,
        "files_copied": total_files,
        "previous_wfi_sha": installed_wfi,
        "previous_scripts_sha": installed_scripts,
        "note": ("Workflow Integration Plugins require a Resolve restart; "
                  "scripts are picked up on next menu open. Scripts are "
                  "deployed under every page's Workspace > Scripts menu."),
    }


# ─── HTTP handlers ───────────────────────────────────────────────────────


def status(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /resolve/plugin/status — report what's deployed vs. available."""
    cfg = ctx["config"]
    dirs = detect_plugin_dirs(cfg)
    src_root = _resolve_plugin_src_root()
    src_sha = _git_sha(_src_root())

    wfi_sha = _read_version(dirs["workflow_integration"])
    scripts_sha = _read_version(dirs["scripts"])

    # Count files actually on disk so status differentiates "never
    # installed" from "installed but stamp missing".
    def _count(p: Path) -> int:
        try:
            return sum(1 for _ in p.rglob("*") if _.is_file())
        except OSError:
            return 0

    wfi_files = _count(dirs["workflow_integration"])
    scripts_files = _count(dirs["scripts"])

    installed = (wfi_sha or scripts_sha
                  or wfi_files > 0 or scripts_files > 0)
    up_to_date = bool(src_sha) and wfi_sha == src_sha and scripts_sha == src_sha

    return 200, {
        "installed": installed,
        "up_to_date": up_to_date,
        "src_version": src_sha,
        "src_root": str(src_root),
        "workflow_integration_dir": str(dirs["workflow_integration"]),
        "workflow_integration_sha": wfi_sha,
        "workflow_integration_files": wfi_files,
        "scripts_dir": str(dirs["scripts"]),
        "scripts_sha": scripts_sha,
        "scripts_files": scripts_files,
    }


def install(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /resolve/plugin/install — deploy the plugin from src.

    Optional body: {"guild_url": "http://<host>:<port>", "force": bool}.
    If ``guild_url`` is provided, the bridge's resolve_bridge.json config
    file is also (re-)written so scripts and the Bridge daemon find the
    Guild on first run. Otherwise only the tree is deployed.
    """
    body = ctx.get("body") or {}
    cfg = ctx["config"]
    force = bool(body.get("force", False))
    result = install_plugin_from_src(cfg, force=force)
    guild_url = (body.get("guild_url") or "").strip()
    if guild_url:
        cfg_result = _write_bridge_config(guild_url)
        result["bridge_config"] = cfg_result
    return (200 if result.get("ok") else 500), result


# ─── Bridge config (resolve_bridge.json) ─────────────────────────────────


def _bridge_config_path() -> Path:
    """Mirror spellcaster_api.py's _config_path — the place the scripts
    and the Bridge read from. ``~/.spellcaster/resolve_bridge.json``."""
    return Path(os.path.expanduser("~")) / ".spellcaster" / "resolve_bridge.json"


def _write_bridge_config(guild_url: str) -> dict[str, Any]:
    """Atomically merge-update the bridge config with a guild_url.

    Preserves every other key the operator may have already set
    (auto_import, target_bin, live_timeline, poll_interval_s, …). Only
    guild_url is guaranteed to be overwritten.
    """
    url = guild_url.rstrip("/")
    path = _bridge_config_path()
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing["guild_url"] = url
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        return {"ok": False, "error": f"could not write {path}: {e}"}
    return {"ok": True, "path": str(path), "guild_url": url}


def stage_input_video(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /resolve/stage-input-video — copy a local video file into
    ComfyUI's input/ directory so VHS_LoadVideo can reference it by
    basename alone.

    Body: {"path": "<absolute path on the antenna host>"}.

    The antenna's co-located with both Resolve and ComfyUI, so this is
    a plain filesystem copy (no LAN transfer). Returns the staged
    basename on success; the caller then sets that basename as the
    shot's overrides.input_video and the Guild renders without a
    separate upload.
    """
    body = ctx.get("body") or {}
    cfg = ctx["config"]
    src = (body.get("path") or "").strip()
    if not src:
        return 400, {"error": "path is required"}
    src_path = Path(os.path.expanduser(src))
    if not src_path.is_file():
        return 404, {"error": f"no file at {src}"}

    # Locate ComfyUI's input directory. The antenna config already
    # carries comfyui_root for service launching; input/ is a
    # well-known child.
    comfy_root = (cfg.get("comfyui_root") or "").strip()
    if not comfy_root:
        return 500, {"error": "antenna config has no comfyui_root"}
    input_dir = Path(os.path.expanduser(comfy_root)) / "input"
    if not input_dir.is_dir():
        # Some ComfyUI layouts have input/ one level deeper (inside the
        # main/, venv-adjacent repo clone). Walk up one shallow.
        alt = Path(os.path.expanduser(comfy_root)) / "ComfyUI" / "input"
        if alt.is_dir():
            input_dir = alt
        else:
            return 500, {"error": f"ComfyUI input dir not found at "
                                     f"{input_dir}"}

    # Keep filename collision-free by prefixing with content hash —
    # avoids clobbering "bedroom.mp4" in the test fixtures. Use first 8
    # hex chars to keep the name readable.
    h = hashlib.sha1()
    with src_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    digest = h.hexdigest()[:8]
    dest_name = f"sc_{digest}_{src_path.name}"
    dest = input_dir / dest_name
    if not dest.exists():
        try:
            shutil.copy2(src_path, dest)
        except OSError as e:
            return 500, {"error": f"copy failed: {e}"}
    return 200, {
        "ok": True,
        "staged_name": dest_name,
        "comfyui_input_dir": str(input_dir),
        "size_bytes": dest.stat().st_size,
    }


def debug(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /resolve/plugin/debug — dump bridge config + reachability test.

    Used to diagnose "my capture_timeline.py script ran but no shots
    appeared on the Guild". Reports:
      * contents of ~/.spellcaster/resolve_bridge.json verbatim
      * whether guild_url is reachable from this host (antenna-side
        network view, which is what the scripts see)
      * env vars that override discover_guild_url
    """
    import urllib.request as _ur
    import urllib.error as _ue

    path = _bridge_config_path()
    bridge_cfg: dict[str, Any] = {}
    bridge_cfg_error: str | None = None
    if path.is_file():
        try:
            bridge_cfg = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError) as e:
            bridge_cfg_error = str(e)
    else:
        bridge_cfg_error = "file does not exist"

    env_override = os.environ.get("SPELLCASTER_GUILD_URL", "")

    # Resolve the URL the scripts will actually use (mirrors
    # discover_guild_url's precedence).
    effective_url = (env_override
                      or bridge_cfg.get("guild_url")
                      or "(none — will probe 127.0.0.1)")

    reach_target = effective_url
    reach_result: dict[str, Any] = {"target": reach_target}
    if reach_target.startswith("http"):
        try:
            req = _ur.Request(reach_target.rstrip("/") + "/api/config",
                               method="GET")
            with _ur.urlopen(req, timeout=5) as resp:
                reach_result["status_code"] = resp.status
                body = resp.read(512).decode("utf-8", "replace")
                reach_result["body_sample"] = body[:200]
                reach_result["ok"] = True
        except _ue.HTTPError as e:
            reach_result["status_code"] = e.code
            reach_result["ok"] = False
        except Exception as e:  # noqa: BLE001
            reach_result["ok"] = False
            reach_result["error"] = f"{type(e).__name__}: {e}"
    else:
        reach_result["ok"] = False
        reach_result["error"] = "no http(s) url to probe"

    return 200, {
        "bridge_config_path": str(path),
        "bridge_config_error": bridge_cfg_error,
        "bridge_config": bridge_cfg,
        "env_SPELLCASTER_GUILD_URL": env_override,
        "effective_guild_url": effective_url,
        "reach_test": reach_result,
    }


def configure(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /resolve/plugin/configure — write the bridge's resolve_bridge.json.

    Body: {"guild_url": "http://<host>:<port>"}

    The Resolve Bridge daemon and every Resolve-side script read this
    file via spellcaster_api.discover_guild_url() to find the Guild. On
    a fresh install, without a file here, those calls fall back to
    probing 127.0.0.1 — which doesn't find the Guild when it lives on a
    different box on the LAN. Pairing from the Guild side calls this
    endpoint so the config is populated automatically.
    """
    body = ctx.get("body") or {}
    guild_url = (body.get("guild_url") or "").strip()
    if not guild_url:
        return 400, {"error": "guild_url is required"}
    return 200, _write_bridge_config(guild_url)
