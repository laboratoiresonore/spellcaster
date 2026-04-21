#!/usr/bin/env python3
"""Build a portable "Spellcaster Studio" bundle.

See _dev_docs/PORTABLE_BUNDLE_PLAN.md for design rationale. This
script produces a self-contained zip / directory tree the user can
extract and run with zero configuration:

    dist/SpellcasterStudio-<VERSION>-win64/
    ├── SpellcasterStudio.bat
    ├── SpellcasterStudio-FirstRun.bat
    ├── README.txt
    ├── LICENSE.txt
    ├── gimp-installer.exe        (used by FirstRun then deleted)
    ├── comfyui/                  (ComfyUI Portable from GH releases)
    │   └── ComfyUI/custom_nodes/ComfyUI-Spellcaster/  (our pack)
    ├── plugin/comfyui-connector/ (pre-installed plugin + config)
    └── data/                     (empty; bundle-local state)

Usage:
    python tools/build_portable_bundle.py --version 2.3 [--lite] [--skip-cns]
                                          [--platform win64] [--zip]

Flags:
    --version X.Y    Spellcaster release tag (required for naming).
    --lite           Skip pre-downloading ControlNet files. Bundle
                     ships a stub that downloads on first run via
                     the pack's /spellcaster/models/repair route.
                     Drops bundle size from ~11 GB to ~3 GB.
    --skip-cns       Same as --lite; explicit.
    --platform       win64 (MVP). macOS / Linux deferred.
    --zip            Package the bundle as a zip at the end.
    --dry-run        Print actions, don't execute.
    --output DIR     Override output dir (default: dist/).

This script is a SCAFFOLD. The download URLs for ComfyUI Portable +
GIMP installer are pinned per release. Update COMFY_PORTABLE_URL and
GIMP_INSTALLER_URL when a newer upstream is tested.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


# ── Pinned upstream artefact URLs ────────────────────────────────
# ComfyUI Portable for Windows — update per release after smoke-test.
COMFY_PORTABLE_URL = (
    "https://github.com/comfyanonymous/ComfyUI/releases/download/"
    "latest/ComfyUI_windows_portable_nvidia.7z"
)
# GIMP 3.x Windows installer — update to latest stable.
GIMP_INSTALLER_URL = (
    "https://download.gimp.org/gimp/v3.0/windows/"
    "gimp-3.0.4-setup.exe"
)
# GIMP installer expected basename (downloaded as-is).
GIMP_INSTALLER_NAME = "gimp-installer.exe"


# ── Repo paths (auto-resolved relative to this script) ───────────
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TEMPLATES = HERE / "portable_bundle_templates"


def _log(msg: str, level: str = "info"):
    prefix = {"info": "[build]", "warn": "[warn]", "err": "[err]"}.get(
        level, "[build]")
    print(f"{prefix} {msg}", flush=True)


def _run(cmd: list[str], cwd: Path | None = None, dry_run: bool = False):
    _log(f"$ {' '.join(str(c) for c in cmd)}")
    if dry_run:
        return 0
    return subprocess.check_call(cmd, cwd=cwd)


def _download(url: str, dest: Path, dry_run: bool = False):
    if dry_run:
        _log(f"would download {url} -> {dest}")
        return
    if dest.exists():
        _log(f"cached {dest.name} ({dest.stat().st_size // (1024*1024)} MB)")
        return
    _log(f"downloading {url} ...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=1800) as resp:
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1 << 20)  # 1 MB
                    if not chunk:
                        break
                    f.write(chunk)
        tmp.replace(dest)
        _log(f"saved {dest.name} ({dest.stat().st_size // (1024*1024)} MB)")
    except Exception as e:
        try:
            tmp.unlink()
        except Exception:
            pass
        raise RuntimeError(f"download failed: {url}: {e}")


def _copy_tree(src: Path, dst: Path, dry_run: bool = False,
                ignore: callable = None):
    if dry_run:
        _log(f"would cp -r {src} -> {dst}")
        return
    _log(f"cp -r {src.name}/ -> {dst}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore or shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".git", ".gitignore", ".DS_Store"))


def _write_json_config(path: Path, data: dict, dry_run: bool = False):
    import json
    if dry_run:
        _log(f"would write {path}: {data}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _log(f"wrote {path}")


def _extract_7z(archive: Path, dest: Path, dry_run: bool = False):
    """ComfyUI Portable ships as .7z. Requires 7z.exe on PATH OR
    py7zr python package. Attempts both."""
    if dry_run:
        _log(f"would extract {archive} -> {dest}")
        return
    _log(f"extracting {archive.name} ...")
    dest.mkdir(parents=True, exist_ok=True)
    # Try 7z CLI first (fastest, most widely installed).
    try:
        subprocess.check_call(["7z", "x", str(archive), f"-o{dest}", "-y"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        return
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # Fallback: py7zr python package.
    try:
        import py7zr
        with py7zr.SevenZipFile(archive, mode="r") as z:
            z.extractall(path=dest)
        return
    except ImportError:
        raise RuntimeError(
            "Need either 7z.exe on PATH or `pip install py7zr` to "
            "extract ComfyUI Portable. 7z: https://7-zip.org/ . "
            "py7zr: pip install py7zr")


def _extract_zip(archive: Path, dest: Path, dry_run: bool = False):
    if dry_run:
        _log(f"would extract {archive} -> {dest}")
        return
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)


# ── Build steps ─────────────────────────────────────────────────

def step_fresh_output(args, bundle: Path):
    """Create a clean bundle directory."""
    if args.dry_run:
        _log(f"would mkdir -p {bundle}")
        return
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    (bundle / "data" / "logs").mkdir(parents=True)
    (bundle / "data" / "gimp_config").mkdir(parents=True)
    (bundle / "data" / "output").mkdir(parents=True)
    _log(f"fresh bundle at {bundle}")


def step_fetch_comfyui(args, bundle: Path, cache: Path):
    """Download + extract ComfyUI Portable."""
    archive = cache / "comfyui_portable.7z"
    _download(COMFY_PORTABLE_URL, archive, args.dry_run)
    comfy_dir = bundle / "comfyui"
    _extract_7z(archive, comfy_dir.parent, args.dry_run)
    # The 7z extracts to ComfyUI_windows_portable/ — rename to comfyui/
    if not args.dry_run:
        extracted = bundle / "ComfyUI_windows_portable"
        if extracted.exists() and not comfy_dir.exists():
            extracted.rename(comfy_dir)


def step_install_pack(args, bundle: Path):
    """Copy the ComfyUI-Spellcaster pack into custom_nodes/."""
    pack_src = REPO.parent / "ComfyUI-Spellcaster"
    if not pack_src.is_dir():
        raise RuntimeError(
            f"ComfyUI-Spellcaster repo not found at {pack_src} — "
            f"this script expects the sibling clone per CLAUDE.md §3")
    pack_dst = bundle / "comfyui" / "ComfyUI" / "custom_nodes" / "ComfyUI-Spellcaster"
    _copy_tree(pack_src, pack_dst, args.dry_run)


def step_install_plugin(args, bundle: Path):
    """Copy the GIMP plugin + pre-populate config.json."""
    plugin_src = REPO / "plugins" / "gimp" / "comfyui-connector"
    plugin_dst = bundle / "plugin" / "comfyui-connector"
    _copy_tree(plugin_src, plugin_dst, args.dry_run,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".git", ".gitignore",
                    "config.json", "session_state.json", "user_presets.json",
                    ".spellcaster_version", "logs", "*.update",
                    ".DS_Store"))
    # Pre-populate bundle-appropriate config.
    _write_json_config(plugin_dst / "config.json", {
        "server_url": "http://127.0.0.1:8188",
        "workflow_timeout": 0,
        "auto_update": True,
        "debug_images": False,
        "favourite_model": -1,
        "output_dir": "",  # launcher sets to %BUNDLE%/data/output at startup
        "output_cleanup": "copy",
        "extra_workflow_dirs": [],
        "prompt_enhance": True,
        "llm_url": "",
        "apply_theme": True,
        "theme_variant": "wizard_guild",
        "_bundle_version": args.version,
    }, args.dry_run)


def step_download_cns(args, bundle: Path, cache: Path):
    """Seed the canonical ControlNet files into models/controlnet/."""
    if args.lite or args.skip_cns:
        _log("--lite / --skip-cns: skipping CN seed (downloaded on first run)")
        return
    # Import CN_URL_MAP from the pack — single source of truth.
    pack_repair = REPO / "comfyui-spellcaster" / "model_repair.py"
    if not pack_repair.exists():
        raise RuntimeError(f"pack model_repair.py not found at {pack_repair}")
    # Eval the constant out of the source without importing the full pack
    # (which needs ComfyUI's `server` module at import time).
    ns: dict = {}
    code = pack_repair.read_text(encoding="utf-8")
    # Trim to just the CN_URL_MAP block to avoid accidentally running
    # registration code.
    import re
    m = re.search(r"^CN_URL_MAP[^=]*=\s*\{", code, re.M)
    if not m:
        raise RuntimeError("Could not locate CN_URL_MAP in model_repair.py")
    # Walk brace balance out.
    start = m.end() - 1
    depth = 0
    i = start
    while i < len(code):
        c = code[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
        i += 1
    literal = code[start:end]
    cn_url_map = eval(literal, {"__builtins__": {}})
    # Dedupe by URL — the map has several path-form aliases pointing
    # at the same file; we only want one download per URL.
    seen_urls: set[str] = set()
    cn_dir = bundle / "comfyui" / "ComfyUI" / "models" / "controlnet"
    cn_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in cn_url_map.items():
        if url in seen_urls:
            continue
        seen_urls.add(url)
        dest = cn_dir / filename
        if dest.exists():
            _log(f"cached {filename}")
            continue
        _download(url, dest, args.dry_run)


def step_fetch_gimp_installer(args, bundle: Path, cache: Path):
    """Download the GIMP Windows installer + stage into bundle root."""
    installer = cache / GIMP_INSTALLER_NAME
    _download(GIMP_INSTALLER_URL, installer, args.dry_run)
    dst = bundle / GIMP_INSTALLER_NAME
    if args.dry_run:
        _log(f"would cp {installer} -> {dst}")
        return
    shutil.copy2(installer, dst)


def step_stage_templates(args, bundle: Path):
    """Drop launcher .bat + README + LICENSE from templates/."""
    if not TEMPLATES.is_dir():
        raise RuntimeError(
            f"Templates missing: {TEMPLATES} — re-clone repo or copy "
            f"tools/portable_bundle_templates/ from main")
    for name in ("SpellcasterStudio.bat", "SpellcasterStudio-FirstRun.bat",
                  "README.txt", "LICENSE.txt"):
        src = TEMPLATES / name
        if not src.exists():
            _log(f"template missing: {name} — skipping", "warn")
            continue
        dst = bundle / name
        if args.dry_run:
            _log(f"would cp {src} -> {dst}")
            continue
        shutil.copy2(src, dst)
        _log(f"staged {name}")


def step_zip(args, bundle: Path):
    """Zip the bundle for distribution."""
    if not args.zip:
        return
    zip_path = bundle.parent / f"{bundle.name}.zip"
    if args.dry_run:
        _log(f"would zip -> {zip_path}")
        return
    _log(f"zipping to {zip_path} (this takes several minutes on 11 GB) ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                           compresslevel=6) as z:
        for p in bundle.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(bundle.parent))
    size_mb = zip_path.stat().st_size // (1024 * 1024)
    _log(f"zip done: {zip_path} ({size_mb} MB)")
    if size_mb > 2000:
        _log("zip exceeds GitHub Releases 2 GB limit — host externally "
              "(Hugging Face Datasets / archive.org / Cloudflare R2)", "warn")


# ── Main ────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True,
                     help="Spellcaster release tag, e.g. 2.3")
    ap.add_argument("--platform", default="win64",
                     choices=["win64"],
                     help="Build platform (MVP: win64 only)")
    ap.add_argument("--lite", action="store_true",
                     help="Skip CN pre-download (downloads on first run)")
    ap.add_argument("--skip-cns", action="store_true",
                     help="Alias for --lite")
    ap.add_argument("--zip", action="store_true",
                     help="Package as zip at the end")
    ap.add_argument("--dry-run", action="store_true",
                     help="Print actions without executing")
    ap.add_argument("--output", type=Path, default=REPO / "dist",
                     help="Output dir (default: dist/)")
    ap.add_argument("--cache", type=Path, default=REPO / ".bundle_cache",
                     help="Download cache (default: .bundle_cache/)")
    args = ap.parse_args()

    suffix = "-lite" if (args.lite or args.skip_cns) else ""
    bundle_name = (f"SpellcasterStudio-v{args.version}{suffix}-"
                    f"{args.platform}")
    bundle = args.output / bundle_name
    cache = args.cache

    _log(f"building {bundle_name}")
    _log(f"  bundle: {bundle}")
    _log(f"  cache:  {cache}")
    _log(f"  dry-run: {args.dry_run}")

    try:
        step_fresh_output(args, bundle)
        step_fetch_comfyui(args, bundle, cache)
        step_install_pack(args, bundle)
        step_install_plugin(args, bundle)
        step_download_cns(args, bundle, cache)
        step_fetch_gimp_installer(args, bundle, cache)
        step_stage_templates(args, bundle)
        step_zip(args, bundle)
    except Exception as e:
        _log(f"build failed: {e}", "err")
        sys.exit(1)

    _log(f"\nDONE. Bundle: {bundle}")
    if args.zip:
        _log(f"      Archive: {bundle.parent / (bundle.name + '.zip')}")


if __name__ == "__main__":
    main()
