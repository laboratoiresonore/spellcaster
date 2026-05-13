#!/usr/bin/env python3
"""Mirror-drift check — fails the build when 6-surface mirror has drifted.

Per ``MIRROR_TARGETS.md``, the spellcaster_core/ package must be
byte-identical across SIX surfaces. This check enforces it inside the
spellcaster repo for the two in-repo surfaces (C and 1); cross-repo
surfaces (2, 3, 5, 6) are caught by the same script run in a
post-merge GitHub Action that fetches the sibling repos.

Why this exists: PR #20 caught a 4-week-old drift between surfaces C
and 1 where the ``disk_backup`` SaveImageWebsocket fix landed on
surface 1 (the GIMP-side dev copy) but never propagated to surface C.
The auto-patch bot then nearly overwrote 5 + 6 from C and would have
silently regressed the inpaint resilience fix. A pre-merge drift
check would have flagged the original PR.

Behavior:
- Exit 0 when every file in the mirror list is byte-identical between C and 1.
- Exit 1 with a per-file diff summary when any file drifts.
- ``--fix`` copies C → 1 (single direction; C is canonical per the doc).

Usage:
    python tests/mirror_drift.py
    python tests/mirror_drift.py --fix       # SFW-canonical → GIMP-side
    python tests/mirror_drift.py --quiet     # only print on failure
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Force UTF-8 console on Windows (cp1252 chokes on ✓ / ✗)
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

SURFACE_C = REPO / "comfyui-spellcaster" / "spellcaster_core"
SURFACE_1 = REPO / "plugins" / "gimp" / "comfyui-connector" / "spellcaster_core"

# Files that MUST be byte-identical across all 6 surfaces. Sourced
# from MIRROR_TARGETS.md §"Files in scope". Keep this list in sync
# with that document.
MIRROR_FILES = [
    "workflows.py",
    "node_factory.py",
    "composites.py",
    "architectures.py",
    "prompt_enhance.py",
    "video_presets.py",
    "pipeline.py",
    "diagnostic.py",
    "preflight.py",
    "model_detect.py",
    "comfyui_llm.py",
    "guild_llm.py",
    "privacy.py",
    "asset_gallery.py",
    "event_bus.py",
    "interface_registry.py",
    "mailbox.py",
    "cross_interface.py",
    "lora_knowledge.py",
    "lora_calibration_store.py",
    "lora_scorer.py",
    "faceswap_health.py",
    "preflight_status.py",
    "events.py",
    "lora_calibrations_sfw.json",
]


def _md5(p: Path) -> str:
    h = hashlib.md5()
    h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fix", action="store_true",
                        help="Copy surface C → surface 1 to resolve drift "
                             "(C is canonical per MIRROR_TARGETS.md)")
    parser.add_argument("--quiet", action="store_true",
                        help="Only print on failure")
    args = parser.parse_args()

    if not SURFACE_C.is_dir():
        print(f"{RED}✗{RESET} surface C missing: {SURFACE_C}")
        return 2
    if not SURFACE_1.is_dir():
        print(f"{RED}✗{RESET} surface 1 missing: {SURFACE_1}")
        return 2

    drift: list[tuple[str, str, str]] = []  # (file, md5_c, md5_1)
    missing: list[tuple[str, str]] = []     # (file, which_surface)
    ok = 0

    for rel in MIRROR_FILES:
        c = SURFACE_C / rel
        s1 = SURFACE_1 / rel
        if not c.is_file() and not s1.is_file():
            missing.append((rel, "both"))
            continue
        if not c.is_file():
            missing.append((rel, "C"))
            continue
        if not s1.is_file():
            missing.append((rel, "1"))
            continue
        hc = _md5(c)
        h1 = _md5(s1)
        if hc == h1:
            ok += 1
        else:
            drift.append((rel, hc, h1))

    total = len(MIRROR_FILES)
    if not args.quiet or drift or missing:
        print(f"{BOLD}6-surface mirror drift check{RESET}")
        print(f"  C: {SURFACE_C}")
        print(f"  1: {SURFACE_1}")
        print(f"  OK: {ok}/{total}    "
              f"DRIFT: {len(drift)}    "
              f"MISSING: {len(missing)}")

    if drift:
        print(f"\n  {RED}{BOLD}DRIFT DETECTED{RESET}")
        for rel, hc, h1 in drift:
            print(f"    {RED}✗{RESET} {rel}")
            print(f"      C={hc[:8]}  1={h1[:8]}")
        if args.fix:
            print(f"\n  {YEL}--fix: copying C → 1 (C is canonical){RESET}")
            for rel, *_ in drift:
                shutil.copy2(SURFACE_C / rel, SURFACE_1 / rel)
                print(f"    {GREEN}→{RESET} {rel}")
            print(f"\n  {GREEN}✓ surface 1 re-aligned with C{RESET}")
            print(f"    Run again to confirm:  python tests/mirror_drift.py")
            return 0  # we resolved the drift, the next run will be clean
        else:
            print(f"\n  Fix locally:")
            print(f"    python tests/mirror_drift.py --fix")
            print(f"  Or copy C surface manually to surface 1.")
            print(f"  Cross-repo surfaces (2/3/5/6) are checked in CI "
                  f"after merge; sync those via their respective repos.")

    if missing:
        print(f"\n  {YEL}{BOLD}MISSING FILES{RESET}")
        for rel, which in missing:
            print(f"    {YEL}~{RESET} {rel} (missing in {which})")

    if drift or missing:
        return 1
    if not args.quiet:
        print(f"\n  {GREEN}{BOLD}✓ All surfaces byte-identical{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
