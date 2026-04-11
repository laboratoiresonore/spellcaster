#!/usr/bin/env python3
"""Verify spellcaster_core is identical across all locations.

Run before commits to catch divergence early.
Exit code 0 = all in sync, 1 = divergence found.
"""
import os, sys, filecmp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL = os.path.join(REPO_ROOT, "comfyui-spellcaster", "spellcaster_core")
GIMP_BUNDLE = os.path.join(REPO_ROOT, "plugins", "gimp", "comfyui-connector", "spellcaster_core")

LOCATIONS = {
    "canonical": CANONICAL,
    "gimp_bundle": GIMP_BUNDLE,
}

def check():
    if not os.path.isdir(CANONICAL):
        print(f"ERROR: Canonical source not found: {CANONICAL}")
        return False

    ok = True
    for label, loc in LOCATIONS.items():
        if label == "canonical":
            continue
        if not os.path.isdir(loc):
            print(f"  MISSING: {label} ({loc})")
            ok = False
            continue

        for fname in os.listdir(CANONICAL):
            if fname.startswith('.') or fname.endswith('.pyc'):
                continue
            src = os.path.join(CANONICAL, fname)
            dst = os.path.join(loc, fname)
            if not os.path.isfile(src):
                continue
            if not os.path.isfile(dst):
                print(f"  MISSING: {label}/{fname}")
                ok = False
            elif not filecmp.cmp(src, dst, shallow=False):
                sz_src = os.path.getsize(src)
                sz_dst = os.path.getsize(dst)
                print(f"  DIFFER: {label}/{fname} (canonical={sz_src}, bundle={sz_dst})")
                ok = False

    return ok

if __name__ == "__main__":
    print("Spellcaster Core Sync Check")
    print(f"  Canonical: {CANONICAL}")
    for label, loc in LOCATIONS.items():
        if label != "canonical":
            print(f"  {label}: {loc}")
    print()

    if check():
        print("ALL IN SYNC")
        sys.exit(0)
    else:
        print("\nDIVERGENCE FOUND — run: python dev/sync_core.py")
        sys.exit(1)
