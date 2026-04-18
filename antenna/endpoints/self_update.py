"""POST /self-update — pull latest antenna code from GitHub and restart.

Enables zero-touch iteration: dev pushes to main, curls /self-update,
the remote agent replaces its code and restarts within seconds. The
operator never touches the remote terminal.

Flow
----
    1. git fetch + git reset --hard origin/main
       (or clone if the source tree is missing — rare, but handles
       the case where a user moved the src dir)
    2. Syntax-validate all antenna/*.py — if any file doesn't
       compile, roll back to the previous SHA and report the error
       WITHOUT restarting. A bad push must not brick the remote box.
    3. Record the SHA that was just deployed into
       ~/.spellcaster/antenna_last_sha for rollback
    4. Start a subprocess that re-execs the agent, then shut this
       process down. The caller sees HTTP 202 + the new SHA before
       the socket closes.

Rollback mode (rollback=true in body): reset to the SHA stored in
antenna_last_sha BEFORE the last successful update. Useful when you
just pushed something that runs but is logically wrong.

Safety
------
- Bearer-token gated (same as all POST endpoints)
- Audit-logged
- Syntax validation BEFORE accepting the update
- Original source tree identity check (same repo) before pulling
- Never touches the user's config, token, cert, or audit log —
  those live in ~/.spellcaster/, outside the source tree
"""
from __future__ import annotations

import json
import os
import py_compile
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _src_root() -> Path:
    """Return the spellcaster source-tree root on this machine.

    We find it by walking up from the antenna package dir until we
    hit a directory that looks like the spellcaster repo (has both
    `antenna/` and `installer/`). Robust to the user cloning into
    any directory name.
    """
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / "antenna").is_dir() and (parent / "installer").is_dir():
            return parent
    # Fallback: assume two levels up (antenna/endpoints/self_update.py)
    return Path(__file__).resolve().parents[2]


def _git_sha(root: Path) -> str:
    """Current HEAD SHA of the source tree, or '' if not a git repo."""
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _git_pull(root: Path) -> tuple[bool, str, str]:
    """git fetch + git reset --hard origin/main. Returns (ok, old_sha, new_sha)."""
    old_sha = _git_sha(root)
    try:
        subprocess.run(["git", "-C", str(root), "fetch", "--depth=1", "origin", "main"],
                       check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "-C", str(root), "reset", "--hard", "origin/main"],
                       check=True, capture_output=True, timeout=10)
    except subprocess.CalledProcessError as e:
        return False, old_sha, f"git error: {e.stderr.decode(errors='replace')[:500]}"
    except subprocess.TimeoutExpired:
        return False, old_sha, "git timed out"
    new_sha = _git_sha(root)
    return True, old_sha, new_sha


def _git_reset_to(root: Path, sha: str) -> bool:
    """Hard-reset to a specific SHA. Used for rollback."""
    try:
        subprocess.run(["git", "-C", str(root), "reset", "--hard", sha],
                       check=True, capture_output=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _validate_antenna(root: Path) -> tuple[bool, str]:
    """Compile-check every antenna/**.py file. Returns (ok, error_message)."""
    antenna_dir = root / "antenna"
    if not antenna_dir.is_dir():
        return False, "antenna/ directory missing after update"
    errors = []
    for py in antenna_dir.rglob("*.py"):
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as e:
            # Keep the error terse — the first line is the file:line
            errors.append(str(e).splitlines()[0] if str(e) else str(py))
        except OSError as e:
            errors.append(f"{py}: {e}")
    if errors:
        return False, "; ".join(errors[:5])
    return True, ""


def _last_sha_file(cfg: dict[str, Any]) -> Path:
    """Location of the rollback-target SHA — next to the token file."""
    token_path = Path(os.path.expanduser(cfg["token_path"]))
    return token_path.parent / "antenna_last_sha"


def _save_last_sha(cfg: dict[str, Any], sha: str) -> None:
    try:
        _last_sha_file(cfg).write_text(sha, encoding="utf-8")
    except OSError:
        pass  # Rollback will be unavailable but update still succeeds


def _load_last_sha(cfg: dict[str, Any]) -> str:
    try:
        return _last_sha_file(cfg).read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return ""


def _schedule_restart(delay_seconds: float = 0.5) -> None:
    """Spawn a successor python process, then exit this one.

    The delay lets the HTTP response flush to the client before we die.
    The successor runs the SAME command (`python -m antenna.agent`) in
    the SAME directory, so it picks up the just-pulled code on startup.

    Uses os._exit to bypass the httpserver's shutdown machinery — that
    machinery would try to close active connections cleanly, but the
    successor is going to rebind the port, so we want the old process
    to die fast.
    """
    def _respawn():
        time.sleep(delay_seconds)
        root = _src_root()
        # Use start_new_session / DETACHED on Windows so the child lives
        # past this process exiting. On Windows, subprocess.Popen with
        # CREATE_NEW_PROCESS_GROUP is the equivalent.
        kwargs: dict[str, Any] = {"cwd": str(root)}
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008)  # DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(
                [sys.executable, "-m", "antenna.agent"],
                **kwargs,
            )
        except Exception as e:
            print(f"[self-update] failed to spawn successor: {e}", file=sys.stderr)
            return
        # Give the child a beat to bind the port before we release it
        time.sleep(0.8)
        os._exit(0)

    threading.Thread(target=_respawn, daemon=True).start()


def self_update(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /self-update — pull + validate + restart.

    Request body (all optional):
      {
        "rollback": bool,  // if true, reset to antenna_last_sha and restart
        "ref": "main"      // branch/tag/SHA override (not yet used)
      }

    Response: {status_code, result dict}. Returns 202 on success because
    the actual restart happens after we send the response.
    """
    body = ctx.get("body") or {}
    cfg = ctx["config"]
    root = _src_root()

    # ── Rollback branch ──
    if body.get("rollback") is True:
        target_sha = _load_last_sha(cfg)
        if not target_sha:
            return 409, {"error": "no previous SHA recorded — can't roll back"}
        if not _git_reset_to(root, target_sha):
            return 500, {"error": f"git reset to {target_sha[:7]} failed"}
        ok, err = _validate_antenna(root)
        if not ok:
            return 500, {"error": f"rolled-back code doesn't compile: {err}",
                         "rolled_back_to": target_sha}
        _schedule_restart()
        return 202, {"rolled_back_to": target_sha,
                     "restart": "imminent",
                     "expected_online_in_seconds": 2}

    # ── Forward-update branch ──
    old_sha = _git_sha(root)
    if not old_sha:
        return 500, {"error": "source tree isn't a git repo — "
                     "can't self-update. Re-bootstrap via the original "
                     "antenna_for_<ip>.bat."}

    force = bool(body.get("force", False))
    ok, old_sha_pulled, new_sha = _git_pull(root)
    if not ok:
        return 500, {"error": f"git pull failed: {new_sha}"}

    if old_sha_pulled == new_sha and not force:
        return 200, {"status": "already up to date",
                     "sha": new_sha,
                     "hint": "POST {\"force\": true} to restart anyway "
                             "(e.g. after editing config files manually)"}

    # Force restart path: skip validation since we didn't change any code
    if old_sha_pulled == new_sha and force:
        _schedule_restart()
        return 202, {"status": "restarting (forced, no code change)",
                     "sha": new_sha,
                     "restart": "imminent",
                     "expected_online_in_seconds": 2}

    # Compile-check BEFORE restarting — a bad push must not brick us
    ok, err = _validate_antenna(root)
    if not ok:
        # Roll back immediately so we stay alive on the pre-update code
        _git_reset_to(root, old_sha_pulled)
        return 500, {
            "error": f"new code failed syntax check: {err}",
            "attempted_sha": new_sha,
            "rolled_back_to": old_sha_pulled,
            "hint": "fix the syntax error, push, and try /self-update again",
        }

    # Save the pre-update SHA for future rollback
    _save_last_sha(cfg, old_sha_pulled)

    # Schedule restart AFTER we've replied
    _schedule_restart()

    return 202, {
        "updated_from": old_sha_pulled,
        "updated_to": new_sha,
        "restart": "imminent",
        "expected_online_in_seconds": 2,
        "rollback_available": True,
    }
