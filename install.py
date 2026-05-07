#!/usr/bin/env python3
"""LaboratoireSonore Universal Installer -- bootstrap shim.

This file is identical across every LaboratoireSonore repo. It does
ONE thing: fetch the latest universal installer from
laboratoiresonore/main and run it. The full installer lives at
github.com/laboratoiresonore/laboratoiresonore.

Re-running this shim always uses the latest installer code without
needing to re-clone or re-download per repo. New installer features
land in laboratoiresonore and propagate on next launch.

If the network is down: falls back to the cached copy. If there's no
cache: surfaces a clear message and exits 1 (we never silently
half-install something).

Usage:
    python install.py            # GUI (or CLI on headless platforms)
    python install.py --list     # list visible apps
    python install.py --install <app_id>
    python install.py --no-update # skip the version check, run cached
"""

from __future__ import annotations

import argparse
import os
import sys
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

# Single source of truth -- the master copy lives here. Pinned to /main
# so the latest changes are always picked up. The HTTPS endpoint is
# the load-bearing trust anchor; an attacker who can MITM
# raw.githubusercontent.com can already do worse damage.
MASTER_REPO = "laboratoiresonore/laboratoiresonore"
MASTER_BRANCH = "main"
MASTER_BASE = (
    f"https://raw.githubusercontent.com/{MASTER_REPO}/{MASTER_BRANCH}/installer"
)

# Cache lives in user home so updates persist across repos.
CACHE_ROOT = Path.home() / ".lab-installer" / "cache"
CACHE_TTL_SEC = 24 * 60 * 60  # refresh once a day at most


# Files the bootstrap fetches. Keep this list short and stable -- it's
# part of the protocol, and changing it forces every repo's shim to
# be re-synced.
PROTOCOL_FILES = [
    "src/lab_installer.py",
    "src/manifest.py",
    "src/__init__.py",
    "src/actions/__init__.py",
    "src/gui.py",
]

# Optional files -- best-effort, missing-is-fine.
PROTOCOL_OPTIONAL = [
    "src/assets/heroes/beatweaver.png",
    "src/assets/heroes/spellcaster.png",
    "src/assets/heroes/comfyui-spellcaster.png",
]


def _say(msg: str) -> None:
    """Status output -- single line, no fancy formatting (we're a shim,
    the real installer takes over for GUI). Goes to stderr so --list /
    --install output stays grep-able on stdout."""
    print(f"[lab-installer] {msg}", file=sys.stderr)


def _fetch(url: str, dest: Path, *, timeout: float = 10.0,
           quiet: bool = False) -> bool:
    """Download a single file. Atomic via .partial rename so a torn
    download can't half-install. quiet=True silences the failure log
    (used for optional files where 404 is expected)."""
    partial = dest.with_suffix(dest.suffix + ".partial")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "lab-installer-bootstrap"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            partial.parent.mkdir(parents=True, exist_ok=True)
            with open(partial, "wb") as f:
                shutil.copyfileobj(resp, f)
        partial.replace(dest)
        return True
    except (urllib.error.URLError, OSError) as e:
        try: partial.unlink()
        except OSError: pass
        if not quiet:
            _say(f"download failed for {url.split('/')[-1]}: {e}")
        return False


def _read_remote_version() -> str | None:
    """Fetch the master's VERSION file. Returns None on any failure
    (network down, file missing). Called once per launch."""
    try:
        req = urllib.request.Request(
            f"{MASTER_BASE}/VERSION",
            headers={"User-Agent": "lab-installer-bootstrap"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.read().decode("utf-8").strip()
    except (urllib.error.URLError, OSError, UnicodeDecodeError):
        return None


def _read_cached_version() -> str | None:
    try:
        return (CACHE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _local_path(rel: str) -> Path:
    """Where a remote file lands locally. Cache mirrors the master
    under `installer/` so the master's `from installer.src import ...`
    absolute imports resolve when CACHE_ROOT is on sys.path."""
    return CACHE_ROOT / "installer" / rel


def _cache_complete() -> bool:
    """True iff every PROTOCOL_FILES entry is present in the cache."""
    return all(_local_path(p).exists() for p in PROTOCOL_FILES)


def _refresh_cache(target_version: str | None = None) -> bool:
    """Download every PROTOCOL_FILES entry into the cache. Returns
    True if every required file landed. The optional list is
    best-effort -- failures don't block install."""
    _say("fetching latest installer...")

    for rel in PROTOCOL_FILES:
        url = f"{MASTER_BASE}/{rel}"
        dest = _local_path(rel)
        if not _fetch(url, dest):
            _say(f"required file missing -- using cached copy if any")
            return False

    for rel in PROTOCOL_OPTIONAL:
        url = f"{MASTER_BASE}/{rel}"
        dest = _local_path(rel)
        # quiet=True: optional assets may legitimately 404; that's
        # fine. Surfacing the line just confuses end-users into
        # thinking something's wrong.
        _fetch(url, dest, quiet=True)

    if target_version:
        (CACHE_ROOT / "VERSION").write_text(target_version, encoding="utf-8")
    _say("cache up to date")
    return True


def _ensure_cache(skip_update: bool = False) -> bool:
    """Refresh the cache if stale + we have network. Falls back to
    existing cache silently on network failure. Returns True iff the
    cache is usable (anything in it is enough -- we don't enforce
    'complete' here because partial caches still let the user run
    last-known-good)."""
    cache_dir = CACHE_ROOT
    cache_dir.mkdir(parents=True, exist_ok=True)

    if skip_update:
        return _cache_complete()

    # Don't touch network if cache is fresh enough -- opportunistic
    # offline-friendly default.
    main_file = _local_path("src/lab_installer.py")
    if main_file.exists():
        age = time.time() - main_file.stat().st_mtime
        if age < CACHE_TTL_SEC:
            return True

    # Stale or missing -- try to refresh. The remote version check is a
    # cheap precursor that can short-circuit a full re-download if
    # nothing's changed.
    remote_v = _read_remote_version()
    cached_v = _read_cached_version()

    if remote_v and remote_v == cached_v and _cache_complete():
        # Same version, full cache -- just bump the mtime so we don't
        # re-check for another TTL window.
        main_file.touch()
        return True

    return _refresh_cache(remote_v) or _cache_complete()


def _run_cached(argv: list[str]) -> int:
    """Hand off to the cached installer via runpy.run_module so the
    master's `from .` and `from installer.src import ...` imports both
    resolve. CACHE_ROOT goes on sys.path; `installer/` is the package
    boundary (namespace-package OK -- no __init__.py required)."""
    main_file = _local_path("src/lab_installer.py")
    if not main_file.exists():
        _say(f"FATAL: no cached installer at {main_file}")
        _say("Run with network access at least once to populate the cache.")
        return 1

    sys.path.insert(0, str(CACHE_ROOT))
    sys.argv = [str(main_file)] + argv
    import runpy
    try:
        runpy.run_module("installer.src.lab_installer", run_name="__main__")
        return 0
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else (1 if e.code else 0)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="LaboratoireSonore universal installer (bootstrap)",
    )
    parser.add_argument("--no-update", action="store_true",
                         help="skip the master-version check; run cached copy")
    parser.add_argument("--clear-cache", action="store_true",
                         help="wipe the local cache and re-download on next run")
    # All other args are passed through to the master installer.
    # parse_known_args() lets unknown flags (--list, --install, --dry-run,
    # subcommands like 'install <id>') reach the master without us needing
    # to keep the shim's parser in sync with the master's CLI surface.
    args, forwarded = parser.parse_known_args()

    if args.clear_cache:
        if CACHE_ROOT.exists():
            shutil.rmtree(CACHE_ROOT, ignore_errors=True)
        _say("cache cleared")
        return 0

    if not _ensure_cache(skip_update=args.no_update):
        _say("cache is empty and refresh failed -- try again with network access")
        return 1

    # Strip the leading '--' separator if the caller explicitly used it
    # to separate shim flags from forwarded ones (`install.py -- --list`).
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]

    return _run_cached(forwarded)


if __name__ == "__main__":
    sys.exit(main())
