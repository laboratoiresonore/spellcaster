#!/usr/bin/env python3
"""Copy canonical spellcaster_core to all bundle locations.

Run after editing comfyui-spellcaster/spellcaster_core/ to propagate.
"""
import os, shutil

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL = os.path.join(REPO_ROOT, "comfyui-spellcaster", "spellcaster_core")
TARGETS = [
    os.path.join(REPO_ROOT, "plugins", "gimp", "comfyui-connector", "spellcaster_core"),
]

if not os.path.isdir(CANONICAL):
    print(f"ERROR: Canonical source not found: {CANONICAL}")
    exit(1)

for target in TARGETS:
    os.makedirs(target, exist_ok=True)
    copied = 0
    for fname in os.listdir(CANONICAL):
        src = os.path.join(CANONICAL, fname)
        if not os.path.isfile(src) or fname.startswith('.') or fname.endswith('.pyc'):
            continue
        dst = os.path.join(target, fname)
        shutil.copy2(src, dst)
        copied += 1
    print(f"  {target}: {copied} files synced")

print("Done. Run dev/sync_check.py to verify.")
