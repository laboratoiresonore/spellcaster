#!/usr/bin/env python3
"""Loop-start coordination check — what is every other Claude doing right now?

Built 2026-05-13 per the user directive: "you must automatically and
systematically find out what other claude sessions do so as not to
interfere with their work."

Designed to be the first thing a Claude session calls at the start
of every ``/loop`` iteration. Cheap (~1 s) and prints a compact
human-readable + machine-parsable report:

    1. Active sessions registered via tools/claude_session.py
    2. Active file locks (so this session knows what NOT to edit)
    3. Untracked / modified files in spellcaster + siblings — strong
       signal that a parallel session has WIP there
    4. Recent commits on origin/main across the 3 repos — what
       landed since the last iteration

If another session has claimed a file this iteration plans to edit,
print a COLLISION line so the caller can pick a different concern.

Usage:

    python tools/loop_start_check.py
    python tools/loop_start_check.py --json
    python tools/loop_start_check.py --intent comfyui-spellcaster/spellcaster_core/workflows.py

The ``--intent`` flag declares the file(s) this session is about
to touch; the script exits 1 (collision) if any are locked by
another active session.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GREEN = "\033[92m"
RED   = "\033[91m"
YEL   = "\033[93m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
RESET = "\033[0m"

REPO = Path(__file__).resolve().parent.parent
COORD = REPO / "tools" / "claude_session.py"

# Sibling repos: env-driven so the leak-check regex doesn't flag this
# file. Set DISTRO_REPO_PATH and NSFW_REPO_PATH in the dev environment.
_DISTRO = os.environ.get("DISTRO_REPO_PATH", "")
_NSFW   = os.environ.get("NSFW_REPO_PATH", "")
SIBLINGS = [("spellcaster", REPO)]
if _DISTRO and Path(_DISTRO).is_dir():
    SIBLINGS.append(("distro-runtime", Path(_DISTRO)))
if _NSFW and Path(_NSFW).is_dir():
    SIBLINGS.append(("nsfw-pack", Path(_NSFW)))


def _coord_json(subcmd: str) -> dict:
    if not COORD.is_file():
        return {}
    try:
        p = subprocess.run([sys.executable, str(COORD), subcmd],
                           capture_output=True, text=True, timeout=10)
        return json.loads(p.stdout or "{}")
    except (subprocess.CalledProcessError,
            json.JSONDecodeError, FileNotFoundError):
        return {}


def _git_status(path: Path) -> list[str]:
    try:
        p = subprocess.run(["git", "-C", str(path), "status", "-sb"],
                           capture_output=True, text=True, timeout=10,
                           check=True)
        return p.stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def _git_log(path: Path, n: int = 3) -> list[str]:
    try:
        # Best-effort fetch (don't fail loud if offline)
        subprocess.run(["git", "-C", str(path), "fetch", "origin", "--quiet"],
                       capture_output=True, text=True, timeout=15)
        p = subprocess.run(["git", "-C", str(path), "log", "--oneline",
                            f"-{n}", "origin/main"],
                           capture_output=True, text=True, timeout=10,
                           check=True)
        return p.stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="emit a machine-readable JSON blob instead of "
                         "the human-readable summary")
    ap.add_argument("--intent", nargs="*", default=[],
                    help="file path(s) this session plans to edit. "
                         "Exit 1 on collision with another session's lock.")
    args = ap.parse_args()

    sessions = _coord_json("list").get("sessions", [])
    locks    = _coord_json("locks").get("locks", [])

    # Build a path → owning-session map from lock dicts. The coord
    # module's lock entries look like
    # {"file": "...", "sid": "...", "task": "...", ...}
    locked_by: dict[str, dict] = {}
    for entry in locks:
        if not isinstance(entry, dict):
            continue
        f = entry.get("file") or entry.get("path") or ""
        if f:
            locked_by[str(Path(f).resolve())] = entry

    # Collision check on caller's intent
    collisions: list[dict] = []
    for path_str in args.intent:
        resolved = str(Path(path_str).resolve())
        if resolved in locked_by:
            collisions.append({"intent": path_str,
                                "locked_by": locked_by[resolved]})

    # Per-repo git status / log
    repo_status: dict[str, dict] = {}
    for label, path in SIBLINGS:
        repo_status[label] = {
            "path": str(path),
            "status": _git_status(path),
            "recent_commits": _git_log(path, 3),
        }

    summary = {
        "active_sessions": sessions,
        "locks": locks,
        "collisions": collisions,
        "repos": repo_status,
    }

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return 1 if collisions else 0

    # Human-readable
    print(f"{BOLD}── loop start: parallel-session check ──{RESET}")
    print(f"  active sessions: {len(sessions)}")
    for s in sessions[:10]:
        if not isinstance(s, dict):
            continue
        sid = s.get("sid", "?")
        task = s.get("task", "")[:80]
        age = s.get("age_s", "?")
        files = s.get("files", [])
        print(f"    [{sid}] age={age}s")
        if task:
            print(f"      task: {task}")
        for f in files[:6]:
            print(f"      file: {f}")
    print(f"  active locks: {len(locks)}")
    for entry in locks[:10]:
        if isinstance(entry, dict):
            print(f"    {entry.get('file','?')}  (sid={entry.get('sid','?')})")
    if collisions:
        print(f"\n  {RED}{BOLD}COLLISION{RESET}")
        for c in collisions:
            lb = c["locked_by"]
            print(f"    {RED}✗{RESET} intent={c['intent']}")
            print(f"      held by [{lb.get('sid','?')}] task={lb.get('task','?')}")
    print(f"\n{BOLD}── repos ──{RESET}")
    for label, info in repo_status.items():
        print(f"  {label}: {info['path']}")
        wip = [ln for ln in info['status']
               if ln.startswith(('?? ', ' M ', 'M ', 'A '))]
        if wip:
            print(f"    WIP (untracked/modified):")
            for ln in wip[:10]:
                print(f"      {ln}")
        if info['recent_commits']:
            print(f"    recent commits on origin/main:")
            for ln in info['recent_commits']:
                print(f"      {ln}")

    return 1 if collisions else 0


if __name__ == "__main__":
    sys.exit(main())
