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

# Files fetched into the temp dir on every launch. Keep this list to Python
# source + JSON only — asset PNGs go through the persistent cache (see
# _ensure_assets() below). The list is the UNION across every variant so
# the same FETCH set works for all five .exes; per-variant filtering would
# add maintenance overhead with negligible bandwidth savings (these are
# all small files, total ~700 KB).
FETCH_FILES = [
    "installer/install.py",          # used by ALL variants
    "installer/installer_gui.py",    # main GUI installer + LLM variant
    "installer/theme.py",            # palette + asset resolver (all GUI surfaces)
    "installer/manifest.json",       # all variants

    # Per-variant entry scripts — bootstrap.py picks one to invoke based
    # on the .exe name (spellcaster-validate-install → validate_install,
    # spellcaster-remote-installer → install_remote, etc.)
    "installer/install_with_llm.py",
    "installer/install_remote.py",
    "installer/validate_install.py",
    "installer/manual_update.py",
]
FETCH_TIMEOUT = 15  # per file

# ── Variant routing ─────────────────────────────────────────────────────────
# Every .exe runs THIS bootstrap.py. The .exe name (sys.argv[0]) tells us
# which entry script to invoke after the fetch. Substring match — order
# matters because some keys are prefixes of others (e.g. "installer-llm"
# must be checked before "installer").
_VARIANTS = [
    ("validate-install", {"main_module": "validate_install",  "fetch_assets": False}),
    ("remote-installer", {"main_module": "install_remote",    "fetch_assets": False}),
    ("installer-llm",    {"main_module": "install_with_llm",  "fetch_assets": True}),
    ("manual-update",    {"main_module": "manual_update",     "fetch_assets": False}),
    # Default catches the unmodified "spellcaster-installer.exe" / "spellcaster-installer".
    ("installer",        {"main_module": "install",           "fetch_assets": True}),
]


def _detect_variant() -> dict:
    """Pick the right entry-script + asset policy from the .exe name."""
    name = ""
    try:
        name = Path(sys.argv[0]).stem.lower()
    except Exception:  # noqa: BLE001
        pass
    for substr, cfg in _VARIANTS:
        if substr in name:
            return cfg
    # Fall back to the main installer behavior so an unrecognised name
    # still does *something* useful (better than a hard crash).
    return _VARIANTS[-1][1]


# Asset auto-update — pulls the locally-generated installer artwork into a
# persistent cache so existing .exes get visual polish without rebuild.
ASSET_MANIFEST_PATH = "assets/installer/MANIFEST.json"
ASSET_FETCH_TIMEOUT = 30          # per asset (PNGs can be 1-2 MB each)
ASSET_MAX_BYTES = 8 * 1024 * 1024  # per asset, hard cap (largest legitimate
                                    # asset is the welcome hero at ~2 MB)

# Small network banner so users understand the delay.
# NOTE: use explicit `+` between each piece — implicit adjacent-literal
# concatenation combined with `* 60` would repeat the middle string 60 times.
_BANNER = (
    "=" * 60 + "\n"
    + "  Spellcaster Installer — checking for latest version...\n"
    + "=" * 60
)


def _raw_url(rel_path: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{rel_path}"


_MAX_FETCH_BYTES = 10 * 1024 * 1024  # 10 MB — any legit install.py /
                                      # installer_gui.py / manifest.json
                                      # is well under this. The largest
                                      # current file is ~300 KB.


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
    # Bounded read: a hostile mirror (or compromised CDN) could
    # otherwise stream forever, filling /tmp. 10 MB is an order of
    # magnitude above any legitimate file we fetch.
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        blob = resp.read(_MAX_FETCH_BYTES + 1)
    if not blob:
        raise IOError(f"empty response from {url}")
    if len(blob) > _MAX_FETCH_BYTES:
        raise IOError(
            f"fetched {rel_path} exceeds {_MAX_FETCH_BYTES} bytes; "
            "refusing to write (possible hostile mirror)")
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


def _asset_cache_dir() -> Path:
    """Persistent location for downloaded installer artwork.

    Survives between launches so we don't re-download the 20 MB asset set
    every time. theme.py reads this via the SPELLCASTER_INSTALLER_ASSET_DIR
    env var (set in main() after _ensure_assets succeeds).
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        root = Path(base) / "Spellcaster"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Spellcaster"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME",
                                    os.path.expanduser("~/.local/share"))
                    ) / "spellcaster"
    return root / "installer_cache" / "assets" / "installer"


def _ensure_assets(say) -> Path | None:
    """Download any missing installer assets into the persistent cache.

    Returns the cache dir on success, or None if anything went wrong (in
    which case the GUI falls back to whatever's baked in the bundle and
    degrades to emoji/text where assets are missing).

    `say(msg)` is the splash-status callback (passed in from main()) so the
    user sees "Fetching artwork (12/49)…" instead of staring at nothing.
    """
    cache_dir = _asset_cache_dir()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[bootstrap] cannot create asset cache {cache_dir}: {e}")
        return None

    # Step 1: fetch the asset MANIFEST.json (small, fast)
    try:
        say("Checking artwork manifest…")
        url = _raw_url(ASSET_MANIFEST_PATH)
        req = urllib.request.Request(url, headers={
            "User-Agent": "spellcaster-installer-bootstrap"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            mf_blob = r.read(_MAX_FETCH_BYTES + 1)
        if len(mf_blob) > _MAX_FETCH_BYTES:
            raise IOError("manifest too large")
        manifest = json.loads(mf_blob.decode("utf-8"))
    except (urllib.error.URLError, ssl.SSLError,
            IOError, OSError, ValueError) as e:
        print(f"[bootstrap] asset manifest fetch failed: {e}")
        return None

    files = manifest.get("files", [])
    if not files:
        return None

    # Step 2: write the manifest into the cache so later runs can compare
    try:
        (cache_dir / "MANIFEST.json").write_bytes(mf_blob)
    except OSError:
        pass

    # Step 3: download each asset that's missing OR has wrong size
    missing = []
    for entry in files:
        name = entry.get("name", "")
        size = int(entry.get("size", 0))
        local = cache_dir / name
        try:
            if local.exists() and local.stat().st_size == size:
                continue
        except OSError:
            pass
        missing.append((name, size))

    if not missing:
        say("Artwork up to date.")
        return cache_dir

    total = len(missing)
    for i, (name, size) in enumerate(missing, 1):
        say(f"Fetching artwork ({i}/{total})…")
        try:
            url = _raw_url(f"assets/installer/{name}")
            req = urllib.request.Request(url, headers={
                "User-Agent": "spellcaster-installer-bootstrap"})
            with urllib.request.urlopen(
                    req, timeout=ASSET_FETCH_TIMEOUT) as r:
                blob = r.read(ASSET_MAX_BYTES + 1)
            if len(blob) > ASSET_MAX_BYTES:
                # Skip this asset — never write a hostile-mirror payload
                continue
            if size and len(blob) != size:
                # Size mismatch — likely a stale manifest. Take the file we
                # got but warn so a re-run can catch up.
                print(f"[bootstrap] {name} size {len(blob)} != manifest {size}")
            (cache_dir / name).write_bytes(blob)
        except (urllib.error.URLError, ssl.SSLError,
                IOError, OSError) as e:
            print(f"[bootstrap] asset {name} failed: {e}")
            # Continue with other assets — partial cache is better than
            # zero cache, since theme.py degrades per-asset to None.
            continue

    return cache_dir


def _run_baked(argv: list[str], main_module: str = "install") -> int:
    """Run the baked entry script for the active variant. Returns exit code.

    `main_module` names the .py file to load (e.g. "install",
    "validate_install", "install_remote"). Falls back to "install" if the
    requested module isn't bundled (defence against build-time omissions).
    """
    here = Path(getattr(sys, "_MEIPASS",
                        os.path.dirname(os.path.abspath(__file__))))
    entry_py = here / f"{main_module}.py"
    if not entry_py.exists():
        # Fallback to install.py — every bundle ships it as the floor
        print(f"[bootstrap] baked {main_module}.py missing — falling back to install.py")
        entry_py = here / "install.py"
    if not entry_py.exists():
        print(f"[bootstrap] FATAL: baked install.py missing at {here}")
        return 2
    # Ensure the bundle dir is on sys.path so cross-variant imports work
    # (validate_install + install_remote + install_with_llm all do `import install`)
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    sys.argv = [sys.argv[0]] + argv
    import importlib.util
    spec = importlib.util.spec_from_file_location(main_module, entry_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.main()
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0


def _run_fetched(temp_dir: Path, argv: list[str],
                 main_module: str = "install") -> int:
    """Run the fetched entry script from temp_dir. Returns exit code."""
    # Set env var so fetched install.py uses temp_dir for manifest lookups
    os.environ["SPELLCASTER_INSTALLER_ROOT"] = str(temp_dir)
    # Put temp_dir on sys.path AHEAD of the bundle so the fresh code wins
    # (import resolution for `import installer_gui`, `import install`, etc.)
    sys.path.insert(0, str(temp_dir))
    sys.argv = [sys.argv[0], "--bootstrapped"] + argv

    entry_py = temp_dir / f"{main_module}.py"
    if not entry_py.exists():
        # Fetched set didn't include this entry — fall back to baked
        print(f"[bootstrap] fetched {main_module}.py missing — using baked")
        return _run_baked(argv, main_module=main_module)

    import importlib.util
    spec = importlib.util.spec_from_file_location(main_module, entry_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.main()
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0


def main() -> int:
    argv = list(sys.argv[1:])

    # Pick the variant first so even baked / no-update / bootstrapped
    # paths invoke the right entry script.
    variant = _detect_variant()
    main_module = variant["main_module"]

    # Already bootstrapped? Run baked (prevents recursion).
    if "--bootstrapped" in argv:
        argv = [a for a in argv if a != "--bootstrapped"]
        return _run_baked(argv, main_module=main_module)

    # User asked for offline/baked mode explicitly.
    if "--no-update" in argv:
        argv = [a for a in argv if a != "--no-update"]
        print(f"[bootstrap] --no-update: using baked-in {main_module}")
        return _run_baked(argv, main_module=main_module)

    print(_BANNER)

    # Splash: give the user immediate feedback while the fetch runs.
    # Under `--windowed` the console print above is invisible; the
    # splash is the only thing users see before install.py paints its
    # real window. Silent fallback if Tk isn't available.
    # Console-only variants (validate / remote / manual-update) skip the
    # splash entirely — it would just look weird on a CLI tool.
    sp = None
    if variant.get("fetch_assets", True):
        try:
            from . import splash as _splash  # type: ignore
        except Exception:  # noqa: BLE001
            try:
                import splash as _splash  # type: ignore
            except Exception:  # noqa: BLE001
                _splash = None
        if _splash is not None:
            sp = _splash.show_splash()

    def _say(msg: str) -> None:
        if sp is not None:
            try: sp.status(msg)
            except Exception: pass  # noqa: BLE001
        else:
            # Console variants — print to stdout so the user sees progress
            print(f"[bootstrap] {msg}")

    temp = Path(tempfile.mkdtemp(prefix=f"spellcaster-{main_module}-"))
    try:
        _say(f"Checking for the latest {main_module}…")
        fetched = _fetch_latest(temp)

        # Asset auto-update — only for variants that show the GUI. Skipping
        # the 20 MB asset fetch on console-only variants keeps their startup
        # tight (CLI users care about responsiveness more than artwork).
        if variant.get("fetch_assets", True):
            cache = _ensure_assets(_say)
            if cache is not None:
                os.environ["SPELLCASTER_INSTALLER_ASSET_DIR"] = str(cache)

        if fetched:
            print(f"[bootstrap] Fetched latest source ({len(FETCH_FILES)} files); "
                  f"running {main_module}\n")
            _say(f"Launching the updated {main_module}…")
            if sp is not None:
                try: sp.close()
                except Exception: pass  # noqa: BLE001
            return _run_fetched(temp, argv, main_module=main_module)
        else:
            print(f"[bootstrap] Using baked-in {main_module} (network unavailable)\n")
            _say(f"Offline — launching bundled {main_module}…")
            if sp is not None:
                try: sp.close()
                except Exception: pass  # noqa: BLE001
            return _run_baked(argv, main_module=main_module)
    finally:
        try:
            if sp is not None: sp.close()
        except Exception:
            pass
        try:
            shutil.rmtree(temp, ignore_errors=True)
        except Exception:
            pass


# ── Crash reporter (R136) ───────────────────────────────────────────────────
# The Windows build uses `--windowed`, which swallows stderr. When the exe
# crashes during import or very early in main(), the user sees absolutely
# nothing — that's the literal "doesn't even start" report in issue #7.
# Wrap main() so any unhandled exception lands both in a log file AND in a
# dialog the user can actually screenshot.

def _crashlog_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / "Spellcaster"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Spellcaster"
    return Path(os.environ.get("XDG_STATE_HOME",
                                os.path.expanduser("~/.local/state"))) / "spellcaster"


def _write_crashlog(exc: BaseException) -> Path | None:
    import traceback as _tb
    from datetime import datetime as _dt, timezone as _tz
    try:
        d = _crashlog_dir()
        d.mkdir(parents=True, exist_ok=True)
        # Use UTC (H3 hygiene): naive datetimes are ambiguous when crash
        # logs are sent for triage across timezones.
        _now = _dt.now(_tz.utc)
        stamp = _now.strftime("%Y%m%d_%H%M%S")
        path = d / f"installer_crash_{stamp}.log"
        body = [
            "Spellcaster installer crash report",
            "=" * 60,
            f"Time:       {_now.isoformat(timespec='seconds')}",
            f"Python:     {sys.version.splitlines()[0]}",
            f"Platform:   {sys.platform}  {os.name}",
            f"Frozen:     {getattr(sys, 'frozen', False)}",
            f"MEIPASS:    {getattr(sys, '_MEIPASS', '(not frozen)')}",
            f"Executable: {sys.executable}",
            f"Argv:       {sys.argv}",
            "",
            "Traceback",
            "-" * 60,
            "".join(_tb.format_exception(type(exc), exc, exc.__traceback__)),
        ]
        path.write_text("\n".join(body), encoding="utf-8")
        return path
    except Exception:
        return None


def _show_crash_dialog(exc: BaseException, logpath: Path | None) -> None:
    """Best-effort Tk dialog explaining the crash. Silent on failure —
    if Tk itself is the thing that failed to import, showing a Tk
    dialog isn't an option. The log file is the fallback."""
    try:
        import tkinter as _tk
        from tkinter import scrolledtext
        import traceback as _tb
    except Exception:
        return
    try:
        from . import theme  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            import theme  # type: ignore
        except Exception:  # noqa: BLE001
            theme = None  # crash dialog must survive a broken bundle

    BG = getattr(theme, "BG", "#0B0715")
    TEXT = getattr(theme, "TEXT", "#FFFFFF")
    ACCENT = getattr(theme, "ACCENT", "#D122E3")
    ACCENT_HOVER = getattr(theme, "ACCENT_HOVER", "#E84DF7")
    BG_CARD = getattr(theme, "BG_CARD", "#110A1F")
    TEXT_MUTED = getattr(theme, "TEXT_MUTED", "#8E889D")
    BORDER = getattr(theme, "BORDER", "#3A2863")

    try:
        root = _tk.Tk()
        root.title("Spellcaster Installer — startup error")
        root.geometry("760x480")
        root.configure(bg=BG)
        if theme is not None:
            theme.apply_tk_theme(root)
            theme.try_set_window_icon(root)

        # Header strip with an accent bar for brand recognition
        accent_bar = _tk.Frame(root, bg=ACCENT, height=3)
        accent_bar.pack(fill="x")

        header = _tk.Label(
            root, anchor="w", justify="left",
            font=("Segoe UI", 12, "bold"),
            bg=BG, fg=TEXT,
            text="💎 Spellcaster Installer — startup error")
        header.pack(fill="x", padx=16, pady=(14, 2))

        subtitle = _tk.Label(
            root, anchor="w", justify="left",
            font=("Segoe UI", 10),
            bg=BG, fg=TEXT_MUTED,
            text=("The installer crashed before it could draw its main "
                   "window.  Paste the log below into\n"
                   "github.com/laboratoiresonore/spellcaster/issues/7 "
                   "so we can fix it."))
        subtitle.pack(fill="x", padx=16, pady=(0, 8))

        if logpath:
            pathlbl = _tk.Label(
                root, anchor="w", justify="left",
                font=("Consolas", 9),
                bg=BG, fg=TEXT_MUTED,
                text=f"Log file: {logpath}")
            pathlbl.pack(fill="x", padx=16)

        body = scrolledtext.ScrolledText(
            root, font=("Consolas", 9), wrap="word",
            bg=BG_CARD, fg=TEXT, insertbackground=ACCENT,
            relief="flat", bd=0, padx=10, pady=8,
            highlightbackground=BORDER, highlightthickness=1,
        )
        body.pack(fill="both", expand=True, padx=16, pady=10)
        tb_text = "".join(_tb.format_exception(
            type(exc), exc, exc.__traceback__))
        body.insert("1.0", tb_text)
        body.configure(state="disabled")

        btn = _tk.Button(
            root, text="Close", command=root.destroy, width=14,
            bg=ACCENT, fg=TEXT,
            activebackground=ACCENT_HOVER, activeforeground=TEXT,
            relief="flat", bd=0, padx=16, pady=8,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            highlightthickness=0,
        )
        btn.pack(pady=(0, 16))
        root.mainloop()
    except Exception:
        # If Tk is broken too, at least we have the log file.
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as _exc:
        logpath = _write_crashlog(_exc)
        _show_crash_dialog(_exc, logpath)
        sys.exit(3)
