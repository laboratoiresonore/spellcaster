#!/usr/bin/env python3
"""LaboratoireSonore Universal Installer -- bootstrap shim.

This file is identical across every LaboratoireSonore repo. It does
ONE thing: fetch the latest universal installer from
laboratoiresonore/main and run it. The full installer (with the
polished GUI, manifest gate, hero images, etc.) lives at
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
    "src/crypto.py",
    "src/__init__.py",
]

# Optional files -- fetched on best-effort, missing-is-fine.
PROTOCOL_OPTIONAL = [
    "src/private_manifest.bin",
]


def _say(msg: str) -> None:
    """Status output -- single line, no fancy formatting (we're a shim,
    the real installer takes over for GUI). Goes to stderr so --list /
    --install output stays grep-able on stdout."""
    print(f"[lab-installer] {msg}", file=sys.stderr)


def _fetch(url: str, dest: Path, *, timeout: float = 10.0) -> bool:
    """Download a single file. Atomic via .partial rename so a torn
    download can't half-install."""
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


def _cache_complete() -> bool:
    """True iff every PROTOCOL_FILES entry is present in the cache."""
    return all((CACHE_ROOT / p).exists() for p in PROTOCOL_FILES)


def _refresh_cache(target_version: str | None = None) -> bool:
    """Download every PROTOCOL_FILES entry into the cache. Returns
    True if every required file landed. The optional list is
    best-effort -- failures don't block install."""
    _say("fetching latest installer…")

    for rel in PROTOCOL_FILES:
        url = f"{MASTER_BASE}/{rel}"
        dest = CACHE_ROOT / rel
        if not _fetch(url, dest):
            _say(f"required file missing -- using cached copy if any")
            return False

    for rel in PROTOCOL_OPTIONAL:
        url = f"{MASTER_BASE}/{rel}"
        dest = CACHE_ROOT / rel
        _fetch(url, dest)  # best-effort, ignore failures

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
    main_file = cache_dir / "src" / "lab_installer.py"
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
    """Hand off to the cached installer. We use exec() so the running
    process becomes the installer (single argv0, single PID, clean
    process tree on Windows)."""
    main_file = CACHE_ROOT / "src" / "lab_installer.py"
    if not main_file.exists():
        _say(f"FATAL: no cached installer at {main_file}")
        _say("Run with network access at least once to populate the cache.")
        return 1

    # Make `from installer.src import …` resolvable when the master's
    # lab_installer is run as __main__.
    src_root = (CACHE_ROOT / "src").parent
    env_pythonpath = os.environ.get("PYTHONPATH", "")
    new_pythonpath = (
        str(src_root) + os.pathsep + env_pythonpath if env_pythonpath
        else str(src_root)
    )
    os.environ["PYTHONPATH"] = new_pythonpath

    # Switch to runpy to keep the import system sane for relative imports.
    import runpy
    sys.argv = [str(main_file)] + argv
    try:
        runpy.run_path(str(main_file), run_name="__main__")
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
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.clear_cache:
        if CACHE_ROOT.exists():
            shutil.rmtree(CACHE_ROOT, ignore_errors=True)
        _say("cache cleared")
        return 0

    if not _ensure_cache(skip_update=args.no_update):
        _say("cache is empty and refresh failed -- try again with network access")
        return 1

    # Strip the leading '--' separator argparse uses for REMAINDER.
    forwarded = args.rest
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]

    return _run_cached(forwarded)


if __name__ == "__main__":
    sys.exit(main())
