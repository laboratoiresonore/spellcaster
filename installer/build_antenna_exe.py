r"""Build a standalone Spellcaster Antenna binary via PyInstaller.

Outputs
-------
    dist/spellcaster-antenna-windows.exe  (on Windows)
    dist/spellcaster-antenna-linux        (on Linux)
    dist/spellcaster-antenna-macos        (on macOS)

The binary is a one-file bundle — double-click to launch the tray
(Windows) or the console mode (Linux/macOS without AppIndicator). It
embeds every antenna dependency (pystray, Pillow, stdlib) plus the
scaffold / spellcaster_core modules the antenna imports lazily.

First launch still runs the install_shortcuts prompt on Windows,
writes its token + config to %USERPROFILE%\.spellcaster\, and shows
the 6-digit pair code in the tray.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _out_name() -> str:
    tag = {"Windows": "windows", "Linux": "linux",
            "Darwin": "macos"}.get(platform.system(), "unknown")
    ext = ".exe" if platform.system() == "Windows" else ""
    return f"spellcaster-antenna-{tag}{ext}"


def _require_build_deps() -> None:
    """Fail-fast if the build environment is missing anything
    PyInstaller would silently omit. We got burned once: pystray
    wasn't installed, --collect-all pystray was a no-op, and the
    exe shipped with no tray. Every dep the onefile bundle needs
    must actually import here — otherwise the exe is broken.
    """
    missing: list[str] = []
    for mod, reason in (
        ("pystray", "system-tray icon + menu — core UX"),
        ("PIL",     "Pillow; pystray renders icons through it"),
    ):
        try:
            __import__(mod)
        except Exception as e:
            missing.append(f"  - {mod}: {type(e).__name__}: {e}  ({reason})")
    if missing:
        print("\n[antenna-build] FAIL — build environment is missing deps:")
        for line in missing:
            print(line)
        print("\n  Install them in this Python environment before rebuilding:")
        print(f"    {sys.executable} -m pip install pystray Pillow")
        sys.exit(2)

    # Sanity: both --paths directories must exist. If the user cloned
    # `spellcaster` but not `comfyui-spellcaster/` (which ships in the
    # same repo as a subdir), PyInstaller will fail to find
    # spellcaster_core and the exe won't start.
    needed_dirs = [
        REPO_ROOT / "antenna",
        REPO_ROOT / "scaffold",
        REPO_ROOT / "comfyui-spellcaster" / "spellcaster_core",
    ]
    missing_dirs = [p for p in needed_dirs if not p.is_dir()]
    if missing_dirs:
        print("\n[antenna-build] FAIL — required source trees missing:")
        for p in missing_dirs:
            print(f"  - {p}")
        sys.exit(3)


def _find_tcl_tk_dirs() -> list[tuple[Path, str]]:
    """Locate the interpreter's Tcl + Tk data directories so we can
    bundle them explicitly. PyInstaller's tkinter hook usually handles
    this, but on non-standard interpreters (embedded Python, vendored
    installs where TCL_LIBRARY isn't set) the theme .tcl scripts get
    missed and ttk widgets fall back to a Motif-looking default.

    Returns a list of (source_dir, dest_rel_dir) tuples suitable for
    --add-data. Empty list on failure (PyInstaller's hook is the
    fallback in that case; we're belt-and-suspenders)."""
    result: list[tuple[Path, str]] = []
    # Common layouts:
    #   Windows python.org: C:/Python312/tcl/tcl8.6, .../tcl/tk8.6
    #   macOS framework:    /Library/Frameworks/Python.framework/.../tcl-tk/...
    #   Linux system:       /usr/lib/tcl8.6, /usr/lib/tk8.6
    prefix = Path(sys.prefix)
    candidate_roots = [
        prefix / "tcl",             # standard Windows layout
        prefix / "lib" / "tcl",     # some Unix layouts
    ]
    for root in candidate_roots:
        if not root.is_dir():
            continue
        # Each interesting subdir inside `tcl/` or `lib/tcl/` becomes
        # a bundled folder at the same relative path so Tk resolves
        # them the same way it does in dev.
        for child in root.iterdir():
            if not child.is_dir():
                continue
            # tcl8.6, tk8.6, tcl8, tk8, tkdnd2.8, ... — all welcome.
            lowered = child.name.lower()
            if (lowered.startswith("tcl") or lowered.startswith("tk")
                    or "themes" in lowered):
                dest = f"tcl/{child.name}"
                result.append((child, dest))
    return result


def main() -> int:
    _require_build_deps()
    out_name = _out_name()
    print(f"[antenna-build] Target: {out_name}")
    print(f"[antenna-build] Repo:   {REPO_ROOT}")

    # Clean prior build artefacts so PyInstaller doesn't trip on stale state.
    build_dir = REPO_ROOT / "installer" / "antenna_build"
    spec_dir = REPO_ROOT / "installer" / "antenna_spec"
    dist_dir = REPO_ROOT / "dist"
    for d in (build_dir, spec_dir):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    dist_dir.mkdir(parents=True, exist_ok=True)

    # Entry point: a tiny shim that imports antenna and runs main().
    entry = REPO_ROOT / "installer" / "antenna_entry.py"
    entry.write_text(
        "# auto-generated by build_antenna_exe.py\n"
        "import sys\n"
        "from antenna.__main__ import main\n"
        "sys.exit(main() or 0)\n",
        encoding="utf-8",
    )

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", out_name.rsplit(".", 1)[0] if "." in out_name else out_name,
        "--workpath", str(build_dir),
        "--specpath", str(spec_dir),
        "--distpath", str(dist_dir),
        "--clean",
        "--noconfirm",
        # Paths PyInstaller searches when resolving imports. Adding the
        # repo root + comfyui-spellcaster/ makes antenna/, scaffold/,
        # and spellcaster_core/ all directly importable without data
        # copies — the freezer collects the whole package graph.
        "--paths", str(REPO_ROOT),
        "--paths", str(REPO_ROOT / "comfyui-spellcaster"),
        # Antenna submodules are lazily imported inside _build_routes /
        # autopopulate_services / tray worker threads; PyInstaller's
        # static analyser misses them, so list them explicitly.
        "--collect-submodules", "antenna",
        "--collect-submodules", "scaffold",
        "--collect-submodules", "spellcaster_core",
        # Tkinter — PyInstaller does NOT auto-bundle Tcl/Tk; the
        # first-run shortcut dialog + splash need it. --collect-all
        # ensures the _tkinter C extension + the tcl/tk runtime DLLs
        # land in the onefile bundle. --collect-data grabs the
        # theme .tcl scripts (vistaTheme.tcl, xpTheme.tcl) PyInstaller's
        # static analyser otherwise misses — without those Tk falls
        # back to a Motif-looking default that made the antenna look
        # "ugly as fuck" on fresh Windows machines.
        "--collect-all", "tkinter",
        "--collect-data", "tkinter",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.font",
        # Pystray + PIL — the tray icon. --hidden-import of the
        # per-platform backend wasn't enough because pystray's top-
        # level __init__ pulls Win32 COM stubs at import time that
        # PyInstaller's static analysis misses. --collect-all gathers
        # every submodule + any .pyd binaries they pull.
        "--collect-all", "pystray",
        "--collect-all", "PIL",
        "--hidden-import", "pystray._win32",
        "--hidden-import", "pystray._darwin",
        "--hidden-import", "pystray._appindicator",
        # remote_services.json is read by installer/remote_services.py
        # at boot; it's a pure data file so --add-data is still the
        # right tool here.
        "--add-data", (f"{REPO_ROOT / 'installer' / 'remote_services.json'}"
                        f"{os.pathsep}installer"),
        # Antenna splash asset — PyInstaller's import analyser doesn't
        # see it (it's read via pathlib at runtime). Bundled under
        # antenna/assets/ so the splash resolver in antenna/splash.py
        # finds it relative to _MEIPASS without further tweaking.
        "--add-data", (f"{REPO_ROOT / 'antenna' / 'assets' / 'antenna_logo.png'}"
                        f"{os.pathsep}antenna/assets"),
    ]

    # Explicit Tcl/Tk directory bundling — belt-and-suspenders against
    # PyInstaller's tkinter hook missing the theme .tcl scripts on
    # non-standard interpreters. See _find_tcl_tk_dirs() for rationale.
    for src, dest in _find_tcl_tk_dirs():
        cmd += ["--add-data", f"{src}{os.pathsep}{dest}"]
        print(f"[antenna-build] Tcl/Tk bundle: {src} -> {dest}")
    # Windows: tray-only (--noconsole). Use build_antenna_exe_debug.py
    # if you need a console build for troubleshooting; the shipped
    # binary should always be windowless so the user sees the tray
    # icon and nothing else. Tracebacks land in the log file the
    # antenna writes into %USERPROFILE%\.spellcaster\antenna.log via
    # antenna.agent — they're not silently dropped.
    if platform.system() == "Windows":
        cmd.append("--noconsole")
    cmd.append(str(entry))

    print(f"[antenna-build] PyInstaller cmd:\n  {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if r.returncode != 0:
        print(f"[antenna-build] PyInstaller failed with exit {r.returncode}")
        return r.returncode

    produced = dist_dir / out_name
    if not produced.is_file():
        # PyInstaller strips the extension on non-Windows
        alt = dist_dir / out_name.rsplit(".", 1)[0]
        if alt.is_file():
            produced = alt
    if produced.is_file():
        size_mb = produced.stat().st_size / (1024 * 1024)
        print(f"[antenna-build] OK: {produced} ({size_mb:.1f} MB)")
        return 0
    print(f"[antenna-build] FAIL: {produced} not found")
    return 2


if __name__ == "__main__":
    sys.exit(main())
