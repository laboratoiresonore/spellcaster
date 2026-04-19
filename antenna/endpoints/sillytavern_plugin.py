"""SillyTavern plugin deployment — antenna-driven install/refresh.

Mirrors resolve_plugin.py and darktable_plugin.py for SillyTavern.
Deploys both halves of the Spellcaster ST integration:

  * Server plugin  → <ST>/plugins/spellcaster/
  * UI extension   → <ST>/data/default-user/extensions/spellcaster-st/

and ensures enableServerPlugins is true in ST's config.yaml so the
server plugin actually loads.

ST has no OS-canonical install path — it lives wherever the user
cloned or extracted it. Detection scans common candidates, or the
operator sets sillytavern_dir in the antenna config for an explicit
pointer.

Handlers
--------
    GET  /sillytavern/plugin/status
    POST /sillytavern/plugin/install
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any


# ─── Install-root discovery ──────────────────────────────────────────────


def _candidate_dirs() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = []

    # Environment override: SILLYTAVERN_DIR
    env = (os.environ.get("SILLYTAVERN_DIR") or "").strip()
    if env:
        candidates.append(Path(env).expanduser().resolve())

    # Common user-level install paths
    candidates.extend([
        home / "SillyTavern",
        home / "sillytavern",
        home / "Documents" / "SillyTavern",
        home / "Desktop" / "SillyTavern",
        home / "Downloads" / "SillyTavern",
    ])

    if os.name == "nt":
        # Windows-specific habits
        for root in (r"C:\\", r"D:\\", r"E:\\"):
            for name in ("SillyTavern", "sillytavern"):
                candidates.append(Path(root + name))

    # Sibling of the antenna source tree — handy on dev boxes
    here = Path(__file__).resolve()
    for parent in list(here.parents)[:4]:
        candidates.append(parent.parent / "SillyTavern")
        candidates.append(parent.parent / "sillytavern")
        candidates.append(parent.parent / "whimweaver-st")

    # Dedupe while preserving order
    seen = set()
    out = []
    for c in candidates:
        s = str(c)
        if s in seen:
            continue
        seen.add(s)
        out.append(c)
    return out


def detect_sillytavern_dir(cfg: dict[str, Any] | None = None) -> Path | None:
    """Return the SillyTavern install root, or None if not found.

    Resolution order:
      1. cfg['sillytavern_dir'] (explicit override)
      2. $SILLYTAVERN_DIR
      3. Common-location scan — the first candidate that contains a
         ``server.js`` at its top level wins.
    """
    cfg = cfg or {}
    override = (cfg.get("sillytavern_dir") or "").strip()
    if override:
        p = Path(os.path.expanduser(override)).resolve()
        if p.is_dir() and (p / "server.js").is_file():
            return p
        if p.is_dir():
            return p  # operator knows best even if server.js is missing
    for c in _candidate_dirs():
        try:
            if c.is_dir() and (c / "server.js").is_file():
                return c
        except OSError:
            continue
    return None


# ─── Source discovery ────────────────────────────────────────────────────


def _src_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / "antenna").is_dir() and (parent / "plugins").is_dir():
            return parent
    return Path(__file__).resolve().parents[2]


def _plugin_src() -> Path:
    return _src_root() / "plugins" / "sillytavern" / "spellcaster-st"


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


def _version_stamp(dest_dir: Path, sha: str) -> None:
    try:
        (dest_dir / _VERSION_STAMP).write_text(
            json.dumps({"sha": sha, "installed_at": time.time()},
                       indent=2), encoding="utf-8")
    except OSError:
        pass


def _read_version(dest_dir: Path) -> str:
    try:
        d = json.loads((dest_dir / _VERSION_STAMP)
                       .read_text(encoding="utf-8"))
        return d.get("sha", "")
    except (OSError, json.JSONDecodeError):
        return ""


def _enable_server_plugins(st_dir: Path) -> bool:
    """Flip enableServerPlugins: false → true in config.yaml. Idempotent."""
    cfg_path = st_dir / "config.yaml"
    if not cfg_path.is_file():
        return False
    try:
        content = cfg_path.read_text(encoding="utf-8")
    except OSError:
        return False
    if "enableServerPlugins: true" in content:
        return True
    if "enableServerPlugins: false" in content:
        content = content.replace(
            "enableServerPlugins: false",
            "enableServerPlugins: true")
        try:
            cfg_path.write_text(content, encoding="utf-8")
        except OSError:
            return False
        return True
    # Not present at all — append it rather than breaking YAML with
    # an in-place mutation we can't locate.
    try:
        sep = "" if content.endswith("\n") else "\n"
        cfg_path.write_text(content + sep + "enableServerPlugins: true\n",
                              encoding="utf-8")
    except OSError:
        return False
    return True


def install_plugin_from_src(cfg: dict[str, Any] | None = None,
                              *, force: bool = False) -> dict[str, Any]:
    """Deploy server-plugin + UI extension into a detected
    SillyTavern install."""
    src = _plugin_src()
    if not src.is_dir():
        return {"ok": False, "error": f"plugin source missing at {src}"}

    st_dir = detect_sillytavern_dir(cfg)
    if not st_dir:
        return {
            "ok": False,
            "error": ("SillyTavern install not found. Set "
                       "`sillytavern_dir` in the antenna config or the "
                       "$SILLYTAVERN_DIR env var."),
        }

    sha = _git_sha(_src_root()) or "unknown"

    server_dest = st_dir / "plugins" / "spellcaster"
    ui_dest = st_dir / "data" / "default-user" / "extensions" / "spellcaster-st"

    installed_server = _read_version(server_dest)
    installed_ui = _read_version(ui_dest)
    up_to_date = (sha != "unknown"
                   and installed_server == sha
                   and installed_ui == sha)
    if up_to_date and not force:
        return {
            "ok": True,
            "status": "already up to date",
            "sha": sha,
            "sillytavern_dir": str(st_dir),
            "server_plugin_dir": str(server_dest),
            "ui_extension_dir": str(ui_dest),
            "files_copied": 0,
        }

    files_copied = 0
    try:
        # 1) Server plugin → <ST>/plugins/spellcaster/
        server_dest.mkdir(parents=True, exist_ok=True)
        server_src_js = src / "server-plugin.js"
        server_src_pkg = src / "server-plugin-package.json"
        if server_src_js.is_file():
            # The server plugin expects to be named index.js in its own
            # directory (Node CommonJS loader convention). Rename on
            # copy to match ST's plugin loader expectations.
            shutil.copy2(server_src_js, server_dest / "index.js")
            files_copied += 1
        if server_src_pkg.is_file():
            shutil.copy2(server_src_pkg, server_dest / "package.json")
            files_copied += 1
        _version_stamp(server_dest, sha)

        # 2) UI extension → <ST>/data/default-user/extensions/spellcaster-st/
        ui_dest.mkdir(parents=True, exist_ok=True)
        for fname in ("index.js", "manifest.json", "styles.css",
                       "README.md"):
            fsrc = src / fname
            if fsrc.is_file():
                shutil.copy2(fsrc, ui_dest / fname)
                files_copied += 1
        _version_stamp(ui_dest, sha)

        # 3) enable server plugins in config.yaml
        enabled_ok = _enable_server_plugins(st_dir)

        return {
            "ok": True,
            "status": "installed",
            "sha": sha,
            "sillytavern_dir": str(st_dir),
            "server_plugin_dir": str(server_dest),
            "ui_extension_dir": str(ui_dest),
            "server_plugins_enabled": enabled_ok,
            "files_copied": files_copied,
            "previous_server_sha": installed_server,
            "previous_ui_sha": installed_ui,
            "note": ("Restart SillyTavern to pick up the new server "
                      "plugin; UI extension reloads on the next browser "
                      "refresh."),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "files_copied": files_copied,
        }


# ─── HTTP handlers ───────────────────────────────────────────────────────


def status(ctx: dict[str, Any]) -> tuple[int, dict]:
    cfg = ctx["config"]
    st_dir = detect_sillytavern_dir(cfg)
    sha = _git_sha(_src_root())
    server_sha = ui_sha = ""
    server_dir = ui_dir = ""
    if st_dir:
        sp = st_dir / "plugins" / "spellcaster"
        ud = st_dir / "data" / "default-user" / "extensions" / "spellcaster-st"
        server_sha = _read_version(sp)
        ui_sha = _read_version(ud)
        server_dir = str(sp)
        ui_dir = str(ud)
    return 200, {
        "installed": bool(st_dir) and (server_sha or ui_sha),
        "up_to_date": bool(sha) and server_sha == sha and ui_sha == sha,
        "src_version": sha,
        "sillytavern_dir": str(st_dir) if st_dir else None,
        "server_plugin_dir": server_dir,
        "server_plugin_sha": server_sha,
        "ui_extension_dir": ui_dir,
        "ui_extension_sha": ui_sha,
    }


def install(ctx: dict[str, Any]) -> tuple[int, dict]:
    body = ctx.get("body") or {}
    cfg = ctx["config"]
    result = install_plugin_from_src(
        cfg, force=bool(body.get("force", False)))
    return (200 if result.get("ok") else 500), result
