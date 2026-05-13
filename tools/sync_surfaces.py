#!/usr/bin/env python3
"""Auto-patch tool: sync canon spellcaster_core → siblings 5 + 6.

The "auto-patch bot" referenced in MIRROR_TARGETS.md and CLAUDE.md was
historically aspirational — every canon-side fix required a human to
open + merge a sync PR on Voodoomancer (surface 5) and another on the
NSFW pack (surface 6). This session alone did that dance 4 times.

This tool collapses the dance into one command. Each invocation:

  1. Reads ``tests/cross_repo_drift.py`` to discover MIRROR_FILES +
     KNOWN_DIVERGENT (single source of truth for "what to sync").
  2. md5-compares each canon file against its sibling-repo counterpart.
  3. For any drift NOT listed in KNOWN_DIVERGENT, copies canon →
     sibling, creates a sync branch, commits, pushes, and opens a PR
     via the ``gh`` CLI.
  4. Reports what it did and what's pending review.

Per the H6 hygiene boundary: NSFW-only files
(``workflows_nsfw.py``, ``prompt_enhance_nsfw.py``, etc.) are
NOT in MIRROR_FILES and therefore NOT touched. The KNOWN_DIVERGENT
table (per surface) keeps the legitimate per-surface customizations
(host-label comments, NSFW catalogue extras) untouched.

Default operation is DRY-RUN — prints the planned moves and exits 0
without writing anything. Pass ``--apply`` to actually copy +
commit + push + PR. Pass ``--no-pr`` to skip the gh PR step (useful
when you want to inspect the local commit before deciding).

Usage
-----

    # Inspect what would change:
    python tools/sync_surfaces.py \\
        --surface-5 ~/path/to/distro-runtime \\
        --surface-6 ~/path/to/nsfw-pack

    # Actually do it:
    python tools/sync_surfaces.py \\
        --surface-5 ~/path/to/distro-runtime \\
        --surface-6 ~/path/to/nsfw-pack \\
        --apply

Sibling-repo paths come from env vars if not passed:
``DISTRO_REPO_PATH`` (surface 5) and ``NSFW_REPO_PATH`` (surface 6).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
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
SURFACE_C = REPO / "comfyui-spellcaster" / "spellcaster_core"
SURFACE_5_REL = Path("plugin") / "comfyui-connector" / "spellcaster_core"
SURFACE_6_REL = Path("comfyui-spellcaster") / "spellcaster_core"

# Import MIRROR_FILES + KNOWN_DIVERGENT from the audit tool so the two
# files have a single source of truth.
sys.path.insert(0, str(REPO / "tests"))
try:
    from cross_repo_drift import MIRROR_FILES, KNOWN_DIVERGENT  # type: ignore
except ImportError:
    print(f"{RED}✗ failed to import tests/cross_repo_drift.py — "
          f"is the spellcaster repo intact?{RESET}", file=sys.stderr)
    sys.exit(2)


def _md5(p: Path) -> str:
    h = hashlib.md5()
    h.update(p.read_bytes())
    return h.hexdigest()


def _run(cmd: list[str], cwd: Path, dry_run: bool = False) -> tuple[int, str, str]:
    if dry_run:
        return 0, f"(dry-run) {' '.join(cmd)}", ""
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True,
                           text=True, timeout=120)
        return p.returncode, p.stdout, p.stderr
    except subprocess.CalledProcessError as e:
        return e.returncode, e.stdout or "", e.stderr or str(e)
    except FileNotFoundError as e:
        return 127, "", str(e)


def _plan_sync(label: str, sibling_root: Path, surface_rel: Path) -> list[tuple[str, str, str]]:
    """Return list of (filename, canon_md5, sibling_md5) for files to sync."""
    out: list[tuple[str, str, str]] = []
    sibling_dir = sibling_root / surface_rel
    if not sibling_dir.is_dir():
        print(f"{RED}✗ surface {label} dir missing: {sibling_dir}{RESET}")
        return out
    known = KNOWN_DIVERGENT.get(label, set())
    for rel in MIRROR_FILES:
        c = SURFACE_C / rel
        s = sibling_dir / rel
        if not c.is_file() or not s.is_file():
            continue
        hc, hs = _md5(c), _md5(s)
        if hc == hs:
            continue
        if rel in known:
            continue  # legitimate divergence, leave alone
        out.append((rel, hc, hs))
    return out


def _sync_surface(label: str, sibling_root: Path, surface_rel: Path,
                   plan: list[tuple[str, str, str]],
                   apply: bool, push: bool, open_pr: bool,
                   org: str) -> int:
    """Apply the plan to one sibling repo. Returns 0 on success."""
    if not plan:
        print(f"  {GREEN}✓ surface {label}: no sync needed{RESET}")
        return 0

    print(f"\n  {BOLD}── syncing surface {label} ──{RESET}")
    print(f"     repo: {sibling_root}")
    for rel, hc, hs in plan:
        print(f"     • {rel}  canon={hc[:8]} → sibling (was {hs[:8]})")

    if not apply:
        print(f"  {YEL}(dry-run — pass --apply to execute){RESET}")
        return 0

    # 1. Copy files
    for rel, _, _ in plan:
        shutil.copy2(SURFACE_C / rel, sibling_root / surface_rel / rel)
    print(f"  {GREEN}✓ copied {len(plan)} file(s) canon → surface {label}{RESET}")

    # 2. Create branch + commit
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    branch = f"sync/auto-canon-{stamp}"
    # If branch exists locally, reuse it; otherwise create from origin/main
    rc, _, _ = _run(["git", "fetch", "origin", "--quiet"], sibling_root)
    rc, out, err = _run(["git", "checkout", "-B", branch, "origin/main"], sibling_root)
    if rc != 0:
        print(f"  {RED}✗ branch checkout failed: {err.strip()[:200]}{RESET}")
        return 1
    files_arg = [str(surface_rel / rel) for rel, _, _ in plan]
    rc, _, err = _run(["git", "add"] + files_arg, sibling_root)
    if rc != 0:
        print(f"  {RED}✗ git add failed: {err.strip()[:200]}{RESET}")
        return 1
    summary_lines = ", ".join(rel for rel, _, _ in plan[:4])
    if len(plan) > 4:
        summary_lines += f" (+{len(plan) - 4} more)"
    msg = (f"sync(surface {label}): pull canon updates ({summary_lines})\n\n"
           f"Auto-generated by spellcaster/tools/sync_surfaces.py — "
           f"propagates the latest canon spellcaster_core to surface {label}.\n"
           f"Files synced: {len(plan)}\n\n"
           f"Co-Authored-By: Claude Opus 4.7 (1M context) "
           f"<noreply@anthropic.com>")
    rc, _, err = _run(["git", "commit", "-m", msg], sibling_root)
    if rc != 0:
        print(f"  {RED}✗ git commit failed: {err.strip()[:200]}{RESET}")
        return 1
    print(f"  {GREEN}✓ committed on branch {branch}{RESET}")

    if not push:
        print(f"  {DIM}(--no-push: local commit only){RESET}")
        return 0

    # 3. Push
    rc, _, err = _run(["git", "push", "-u", "origin", branch, "--force-with-lease"],
                      sibling_root)
    if rc != 0:
        print(f"  {RED}✗ push failed: {err.strip()[:200]}{RESET}")
        return 1
    print(f"  {GREEN}✓ pushed origin/{branch}{RESET}")

    if not open_pr:
        return 0

    # 4. Open PR (idempotent: if already open, gh prints existing URL)
    rc, out, err = _run(
        ["gh", "pr", "create",
         "--title", f"sync(surface {label}): auto canon update {stamp}",
         "--body", (f"Auto-generated sync from spellcaster canon — "
                    f"`tools/sync_surfaces.py` mirrors changed "
                    f"`spellcaster_core/` files into surface {label}. "
                    f"Files: {', '.join(rel for rel, _, _ in plan)}.\n\n"
                    f"🤖 Generated with [Claude Code]"
                    f"(https://claude.com/claude-code)")],
        sibling_root)
    last = (out + err).strip().splitlines()
    if rc == 0:
        url_line = next((ln for ln in last if "https://" in ln), "")
        print(f"  {GREEN}✓ PR opened: {url_line.strip()}{RESET}")
    else:
        # gh prints "a pull request for branch X already exists" non-fatally
        already = "already exists" in (err.lower() + out.lower())
        if already:
            print(f"  {DIM}(PR already exists for {branch}){RESET}")
        else:
            print(f"  {RED}✗ gh pr create failed: {err.strip()[:200]}{RESET}")
            return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--surface-5", default=os.environ.get("DISTRO_REPO_PATH", ""),
                    help="distro-runtime repo path (default: $DISTRO_REPO_PATH)")
    ap.add_argument("--surface-6", default=os.environ.get("NSFW_REPO_PATH", ""),
                    help="NSFW pack repo path (default: $NSFW_REPO_PATH)")
    ap.add_argument("--apply", action="store_true",
                    help="actually copy + commit + push (default: dry-run)")
    ap.add_argument("--no-push", action="store_true",
                    help="copy + commit locally but don't push or open PR")
    ap.add_argument("--no-pr", action="store_true",
                    help="push branch but don't open PR (useful for review)")
    ap.add_argument("--org", default=os.environ.get("GITHUB_ORG",
                                                      "laboratoiresonore"))
    args = ap.parse_args()

    if not SURFACE_C.is_dir():
        print(f"{RED}✗ canon dir missing: {SURFACE_C}{RESET}", file=sys.stderr)
        return 2

    plans = []
    if args.surface_5:
        plans.append(("5", Path(args.surface_5), SURFACE_5_REL,
                       _plan_sync("5", Path(args.surface_5), SURFACE_5_REL)))
    else:
        print(f"{YEL}~ surface 5 skipped (no --surface-5 / DISTRO_REPO_PATH){RESET}")
    if args.surface_6:
        plans.append(("6", Path(args.surface_6), SURFACE_6_REL,
                       _plan_sync("6", Path(args.surface_6), SURFACE_6_REL)))
    else:
        print(f"{YEL}~ surface 6 skipped (no --surface-6 / NSFW_REPO_PATH){RESET}")

    total = sum(len(p) for *_, p in plans)
    print(f"\n{BOLD}plan: {total} file(s) to sync across {len(plans)} surface(s){RESET}")

    push = not args.no_push
    open_pr = push and not args.no_pr

    exit_code = 0
    for label, sibling_root, surface_rel, plan in plans:
        rc = _sync_surface(label, sibling_root, surface_rel,
                            plan, args.apply, push, open_pr, args.org)
        exit_code = max(exit_code, rc)

    if not args.apply:
        print(f"\n{DIM}Run with --apply to execute.{RESET}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
