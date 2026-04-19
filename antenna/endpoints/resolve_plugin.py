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


_WIN_WFI_DIR = (
    r"{APPDATA}\Blackmagic Design\DaVinci Resolve"
    r"\Support\Workflow Integration Plugins"
)
_WIN_SCRIPTS_DIR = (
    r"{APPDATA}\Blackmagic Design\DaVinci Resolve"
    r"\Support\Fusion\Scripts\Utility\Spellcaster"
)
_MAC_WFI_DIR = (
    "{HOME}/Library/Application Support/Blackmagic Design/DaVinci Resolve"
    "/Workflow Integration Plugins"
)
_MAC_SCRIPTS_DIR = (
    "{HOME}/Library/Application Support/Blackmagic Design/DaVinci Resolve"
    "/Fusion/Scripts/Utility/Spellcaster"
)
_LINUX_WFI_DIR = "{HOME}/.local/share/DaVinciResolve/Workflow Integration Plugins"
_LINUX_SCRIPTS_DIR = (
    "{HOME}/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Spellcaster"
)


def _expand(p: str) -> Path:
    env = {"APPDATA": os.environ.get("APPDATA", ""),
           "HOME": os.path.expanduser("~")}
    return Path(p.format(**env)).resolve()


def detect_plugin_dirs(cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    """Return absolute paths for this host's Resolve plugin destinations.

    Honors explicit overrides in the antenna config:
      resolve_plugin_workflow_dir, resolve_plugin_scripts_dir.
    Otherwise falls back to OS-standard locations.
    """
    cfg = cfg or {}
    override_wfi = (cfg.get("resolve_plugin_workflow_dir") or "").strip()
    override_scripts = (cfg.get("resolve_plugin_scripts_dir") or "").strip()

    if os.name == "nt":
        wfi = _expand(override_wfi or _WIN_WFI_DIR)
        scripts = _expand(override_scripts or _WIN_SCRIPTS_DIR)
    elif sys.platform == "darwin":
        wfi = _expand(override_wfi or _MAC_WFI_DIR)
        scripts = _expand(override_scripts or _MAC_SCRIPTS_DIR)
    else:
        wfi = _expand(override_wfi or _LINUX_WFI_DIR)
        scripts = _expand(override_scripts or _LINUX_SCRIPTS_DIR)

    return {"workflow_integration": wfi, "scripts": scripts}


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
        r = subprocess.run(
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

        # scripts/ contains .py files directly (not a subfolder named
        # "scripts"), so we copy its CONTENTS into dirs["scripts"].
        # Using a staged temp + rglob copy so we keep the atomic-swap
        # safety at the leaf-dir level.
        dirs["scripts"].mkdir(parents=True, exist_ok=True)
        for f in scripts_src.iterdir():
            if f.is_file() and f.suffix in (".py",):
                target = dirs["scripts"] / f.name
                tmp = target.with_suffix(target.suffix + ".new")
                shutil.copy2(f, tmp)
                if target.exists():
                    target.unlink()
                tmp.rename(target)
                total_files += 1
        total_files += _copy_tree_atomic(shared_src, scripts_shared)
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
        "files_copied": total_files,
        "previous_wfi_sha": installed_wfi,
        "previous_scripts_sha": installed_scripts,
        "note": ("Workflow Integration Plugins require a Resolve restart; "
                  "scripts are picked up on next menu open."),
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
