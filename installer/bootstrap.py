"""Spellcaster installer bootstrap — self-updating entry point.

The compiled spellcaster-installer.exe runs this file. It fetches the
LATEST installer code (install.py, installer_gui.py, manifest.json) from
GitHub and hands off execution to that. The baked-in bundle serves two
purposes only:

  1. Asset repository — plugins/, tavern/, scaffold/, assets/ stay bundled
     since they're large and don't change per installer release.
  2. Offline fallback — if the GitHub fetch fails (no network, repo down,
     rate limit), we run the baked install.py as if no bootstrap happened.

Why this design
---------------
The installer has bug-fix releases far more often than asset changes.
Users who ran an older installer.exe (e.g. v2.2 from yesterday) should
not need to re-download the 312 MB exe just to pick up today's detection
fix. This bootstrap makes every .exe self-update on launch, so pushing
to main IS the installer release. No rebuild-per-fix needed.

Flow
----
  1. Parse argv for --no-update / --bootstrapped / --local flags.
  2. If --no-update or --bootstrapped: run baked install.py, return.
  3. Create a temp dir; fetch install.py + installer_gui.py + manifest.json
     into it via GitHub raw URLs.
  4. On any fetch error → run baked install.py (fallback).
  5. On success → set SPELLCASTER_INSTALLER_ROOT env var to the temp dir,
     importlib-exec the fetched install.py's main(), then clean up.

Recursion guard
---------------
When we re-enter (e.g. from a subprocess the fetched code spawned),
sys.argv will contain --bootstrapped. We honour that flag and skip
fetching, preventing an infinite self-update loop.

CLI flags
---------
  --no-update      Skip fetch. Run the baked installer exactly as if
                   this bootstrap didn't exist. Useful for offline
                   installs or when debugging the bundled version.
  --bootstrapped   Internal marker; set automatically after fetch.
"""
from __future__ import annotations

import json
import os
import shutil
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────────────────
REPO = "laboratoiresonore/spellcaster"
BRANCH = "main"
# Files fetched into the temp dir. Keep this list small — only Python
# source and manifest. Asset dirs stay in the bundle.
FETCH_FILES = [
    "installer/install.py",
    "installer/installer_gui.py",
    "installer/manifest.json",
]
FETCH_TIMEOUT = 15  # per file

# Small network banner so users understand the delay
_BANNER = (
    "=" * 60 + "\n"
    "  Spellcaster Installer — checking for latest version...\n"
    "=" * 60
)


def _raw_url(rel_path: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{rel_path}"


def _fetch_one(rel_path: str, dest: Path) -> None:
    """Download one file to dest. Raises on any failure."""
    url = _raw_url(rel_path)
    req = urllib.request.Request(url, headers={
        "User-Agent": "spellcaster-installer-bootstrap",
    })
    # HTTPS with default CA bundle. If the system has a broken cert store,
    # the urlopen call raises ssl.SSLError — we let it propagate so the
    # caller falls back to the baked installer instead of silently running
    # untrusted content.
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        blob = resp.read()
    if not blob:
        raise IOError(f"empty response from {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)


def _fetch_latest(dest_dir: Path) -> bool:
    """Download FETCH_FILES into dest_dir. Returns True on total success."""
    for rel in FETCH_FILES:
        name = Path(rel).name
        target = dest_dir / name
        try:
            _fetch_one(rel, target)
        except (urllib.error.URLError, ssl.SSLError, IOError, OSError) as e:
            print(f"[bootstrap] Fetch failed for {rel}: {e}")
            return False
    # Validate: install.py and manifest.json must parse
    try:
        (dest_dir / "install.py").read_text(encoding="utf-8")
        json.loads((dest_dir / "manifest.json").read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[bootstrap] Fetched files are corrupt: {e}")
        return False
    return True


def _run_baked(argv: list[str]) -> int:
    """Run install.py from the PyInstaller bundle. Returns exit code."""
    here = Path(getattr(sys, "_MEIPASS",
                        os.path.dirname(os.path.abspath(__file__))))
    install_py = here / "install.py"
    if not install_py.exists():
        print(f"[bootstrap] FATAL: baked install.py missing at {install_py}")
        return 2
    # Ensure the bundle dir is on sys.path so installer_gui imports work
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    sys.argv = [sys.argv[0]] + argv
    import importlib.util
    spec = importlib.util.spec_from_file_location("install", install_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.main()
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0


def _run_fetched(temp_dir: Path, argv: list[str]) -> int:
    """Run the fetched install.py from temp_dir. Returns exit code."""
    # Set env var so fetched install.py uses temp_dir for manifest lookups
    os.environ["SPELLCASTER_INSTALLER_ROOT"] = str(temp_dir)
    # Put temp_dir on sys.path AHEAD of the bundle so the fresh code wins
    # (import resolution for `import installer_gui` etc.).
    sys.path.insert(0, str(temp_dir))
    sys.argv = [sys.argv[0], "--bootstrapped"] + argv

    import importlib.util
    spec = importlib.util.spec_from_file_location("install", temp_dir / "install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.main()
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0


def main() -> int:
    argv = list(sys.argv[1:])

    # Already bootstrapped? Run baked (prevents recursion).
    if "--bootstrapped" in argv:
        argv = [a for a in argv if a != "--bootstrapped"]
        return _run_baked(argv)

    # User asked for offline/baked mode explicitly.
    if "--no-update" in argv:
        argv = [a for a in argv if a != "--no-update"]
        print("[bootstrap] --no-update: using baked-in installer")
        return _run_baked(argv)

    print(_BANNER)
    temp = Path(tempfile.mkdtemp(prefix="spellcaster-installer-"))
    try:
        if _fetch_latest(temp):
            print(f"[bootstrap] Fetched latest installer ({len(FETCH_FILES)} files)")
            print("[bootstrap] Running updated code...\n")
            return _run_fetched(temp, argv)
        else:
            print("[bootstrap] Using baked-in installer (network unavailable)\n")
            return _run_baked(argv)
    finally:
        try:
            shutil.rmtree(temp, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
