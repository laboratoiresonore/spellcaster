"""Darktable plugin deployment — antenna-driven install/refresh.

Mirrors the Resolve plugin installer (resolve_plugin.py) for Darktable's
Lua module. The antenna is co-located with Darktable on user boxes that
declare the `darktable` service, so it can write directly into
Darktable's lua/contrib directory and patch luarc — no SCP / manual
copy / release tarball.

Handlers
--------
    GET  /darktable/plugin/status
        Reports where the plugin would land, what SHA is deployed (if
        any), and whether luarc already sources it.

    POST /darktable/plugin/install
        Copies comfyui_connector.lua from the antenna's source tree to
        Darktable's lua/contrib dir and ensures luarc loads it. Safe
        to run while Darktable is open; changes apply on next restart.

Layout decision: we use lua/contrib/<file> (rather than lua/<file>) to
match Darktable's convention of stashing contrib modules there and to
stay aligned with the installer's copy target (install.py:_find_..).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any


# ─── Destination dir discovery ───────────────────────────────────────────

_WIN_CONFIG = r"{APPDATA}\darktable"
_MAC_CONFIG = "{HOME}/Library/Application Support/darktable"
_LINUX_CONFIG_DEFAULT = "{HOME}/.config/darktable"


def _expand(p: str) -> Path:
    env = {"APPDATA": os.environ.get("APPDATA", ""),
           "HOME": os.path.expanduser("~")}
    return Path(p.format(**env)).resolve()


def detect_darktable_dirs(cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    """Return config_dir / lua_contrib_dir / luarc for this host.

    Honours the antenna config override ``darktable_config_dir`` if
    set. Otherwise:
      Windows : %APPDATA%\\darktable
      macOS   : ~/Library/Application Support/darktable
      Linux   : $XDG_CONFIG_HOME/darktable or ~/.config/darktable
    """
    cfg = cfg or {}
    override = (cfg.get("darktable_config_dir") or "").strip()
    if override:
        config = Path(os.path.expanduser(override)).resolve()
    elif os.name == "nt":
        config = _expand(_WIN_CONFIG)
    elif sys.platform == "darwin":
        config = _expand(_MAC_CONFIG)
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if xdg:
            config = Path(xdg).expanduser().resolve() / "darktable"
        else:
            config = _expand(_LINUX_CONFIG_DEFAULT)
    lua_contrib = config / "lua" / "contrib"
    luarc = config / "luarc"
    return {"config": config, "lua_contrib": lua_contrib, "luarc": luarc}


# ─── Source discovery ────────────────────────────────────────────────────


def _src_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / "antenna").is_dir() and (parent / "plugins").is_dir():
            return parent
    return Path(__file__).resolve().parents[2]


def _plugin_src_file() -> Path:
    return _src_root() / "plugins" / "darktable" / "comfyui_connector.lua"


def _git_sha(root: Path) -> str:
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


_VERSION_STAMP = ".spellcaster_version"
_LUARC_LINE = 'require "contrib/comfyui_connector"'


def _version_stamp(dest_dir: Path, sha: str) -> None:
    try:
        (dest_dir / _VERSION_STAMP).write_text(
            json.dumps({"sha": sha, "installed_at": time.time()},
                       indent=2),
            encoding="utf-8")
    except OSError:
        pass


def _read_version(dest_dir: Path) -> str:
    try:
        d = json.loads((dest_dir / _VERSION_STAMP)
                       .read_text(encoding="utf-8"))
        return d.get("sha", "")
    except (OSError, json.JSONDecodeError):
        return ""


def _patch_luarc(luarc: Path) -> bool:
    """Ensure luarc exists and has the require line. Returns True if
    the line is present (either already or newly added), False on
    write failure. Never deletes existing lines."""
    try:
        if luarc.is_file():
            existing = luarc.read_text(encoding="utf-8")
        else:
            existing = ""
        if _LUARC_LINE in existing:
            return True
        # Append. Preserve any trailing newline.
        if existing and not existing.endswith("\n"):
            existing += "\n"
        existing += _LUARC_LINE + "\n"
        luarc.parent.mkdir(parents=True, exist_ok=True)
        luarc.write_text(existing, encoding="utf-8")
        return True
    except OSError:
        return False


def install_plugin_from_src(cfg: dict[str, Any] | None = None,
                              *, force: bool = False) -> dict[str, Any]:
    """Deploy comfyui_connector.lua + assets into Darktable's config.

    Atomic-ish: stages the new Lua to <name>.new, renames on top of
    the existing file. luarc is ensured to source the plugin.
    """
    src = _plugin_src_file()
    if not src.is_file():
        return {"ok": False, "error": f"plugin source missing at {src}"}

    dirs = detect_darktable_dirs(cfg)
    lua_contrib = dirs["lua_contrib"]
    luarc = dirs["luarc"]

    sha = _git_sha(_src_root()) or "unknown"
    installed = _read_version(lua_contrib)
    if installed == sha and sha != "unknown" and not force:
        return {
            "ok": True,
            "status": "already up to date",
            "sha": sha,
            "lua_contrib_dir": str(lua_contrib),
            "luarc": str(luarc),
            "files_copied": 0,
        }

    try:
        lua_contrib.mkdir(parents=True, exist_ok=True)
        dest = lua_contrib / "comfyui_connector.lua"
        tmp = dest.with_suffix(dest.suffix + ".new")
        shutil.copy2(src, tmp)
        if dest.exists():
            dest.unlink()
        tmp.rename(dest)
        files_copied = 1

        # Copy over the visual assets next to the Lua file so the plugin
        # can find splash/header/icon/css via relative paths.
        src_dir = src.parent
        asset_names = (
            "darktable_splash.jpg",
            "installer_background.png",
            "spellcaster-darktable.css",
            "spellcaster_header.png",
            "spellcaster_icon.png",
            "spellcaster_steg.py",
            "splash.py",
        )
        for name in asset_names:
            asrc = src_dir / name
            if asrc.is_file():
                adst = lua_contrib / name
                try:
                    shutil.copy2(asrc, adst)
                    files_copied += 1
                except OSError:
                    pass

        _version_stamp(lua_contrib, sha)

        luarc_ok = _patch_luarc(luarc)

        return {
            "ok": True,
            "status": "installed",
            "sha": sha,
            "lua_contrib_dir": str(lua_contrib),
            "luarc": str(luarc),
            "luarc_patched": luarc_ok,
            "files_copied": files_copied,
            "previous_sha": installed,
            "note": ("Darktable reloads Lua on restart — close and "
                      "reopen to pick up the new plugin version."),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "lua_contrib_dir": str(lua_contrib),
        }


# ─── HTTP handlers ───────────────────────────────────────────────────────


def status(ctx: dict[str, Any]) -> tuple[int, dict]:
    cfg = ctx["config"]
    dirs = detect_darktable_dirs(cfg)
    sha = _git_sha(_src_root())
    installed = _read_version(dirs["lua_contrib"])
    lua_file = dirs["lua_contrib"] / "comfyui_connector.lua"

    luarc_has = False
    try:
        if dirs["luarc"].is_file():
            luarc_has = _LUARC_LINE in dirs["luarc"].read_text(
                encoding="utf-8")
    except OSError:
        pass

    return 200, {
        "installed": lua_file.is_file(),
        "up_to_date": bool(sha) and installed == sha,
        "src_version": sha,
        "installed_sha": installed,
        "lua_contrib_dir": str(dirs["lua_contrib"]),
        "luarc": str(dirs["luarc"]),
        "luarc_patched": luarc_has,
    }


def install(ctx: dict[str, Any]) -> tuple[int, dict]:
    body = ctx.get("body") or {}
    cfg = ctx["config"]
    result = install_plugin_from_src(cfg, force=bool(body.get("force", False)))
    return (200 if result.get("ok") else 500), result
