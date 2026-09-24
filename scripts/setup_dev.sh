#!/usr/bin/env bash
# scripts/setup_dev.sh -- one-shot contributor setup for the spellcaster repo.
#
# Currently does one thing: point `core.hookspath` at the repo's `.githooks/`
# directory so pre-commit + pre-push run for every commit made in this
# checkout. Safe to re-run; the config write is idempotent.
#
# Not for end-users -- those install via `install.py` / `Install.bat`.

set -eu

# Resolve to repo root so this works whether the contributor runs it from
# the repo root or from anywhere else.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Sanity: is this a git checkout at all?
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "[setup_dev] warning: not inside a git checkout -- skipping hook wiring." >&2
  exit 0
fi

# Sanity: does .githooks/ exist? (It should, but if a contributor cloned a
# shallow slice that omitted it, silently skip rather than error.)
if [ ! -d "${REPO_ROOT}/.githooks" ]; then
  echo "[setup_dev] warning: .githooks/ not present -- skipping hook wiring." >&2
  exit 0
fi

# Wire the hook path. Don't fail the whole script if git config errors
# (unusual, but keeps the installer from breaking on odd worktrees).
if git config --local core.hookspath .githooks 2>/dev/null; then
  echo "[setup_dev] git hooks enabled (core.hookspath=.githooks)"
  echo "[setup_dev]   pre-commit: credential-leak + mirror-drift + builders-manifest scans"
  echo "[setup_dev]   pre-push:   credential-leak scan over the pushed range"
else
  echo "[setup_dev] warning: 'git config --local core.hookspath .githooks' failed" >&2
  echo "[setup_dev] you can wire the hooks by hand later:" >&2
  echo "[setup_dev]   git config --local core.hookspath .githooks" >&2
fi
