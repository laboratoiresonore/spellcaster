#!/usr/bin/env python3
"""Drift-detect between architecture supported_methods and installer manifest features.

The architectures.py registry declares, per arch, which methods it supports
(txt2img, img2img, inpaint, etc.). The installer/manifest.json features
block defines installable features (custom_nodes + models per feature).
These two sources of truth need to agree:

  * Every method name surfaced by any registered arch's supported_methods
    SHOULD have a feature in manifest.json that the user can install.
  * Conversely, every manifest feature that gates on `lora_architectures`
    SHOULD reference an arch key that exists in architectures.py.

This script does NOT auto-patch — it surfaces drift so the maintainer can
decide. Run from repo root:

    python scripts/check_arch_manifest_drift.py

Exit codes:
    0  no drift
    1  drift detected (printed)
    2  internal error (couldn't load source files)

Companion to scripts/generate_dependencies_md.py. This is part of §13.4 of
the upgrade plan (ecosystem-update dispatcher) and §4.5 (SSOT
auto-population).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "installer" / "manifest.json"
ARCH_FILE = REPO_ROOT / "comfyui-spellcaster" / "spellcaster_core" / "architectures.py"


# Methods intentionally without a 1:1 manifest feature, mapped to the
# parent feature they're subsumed by. These are NOT drift — they're
# documented exceptions. Update when a method graduates to its own
# installer feature.
SUBSUMED_BY_PARENT: dict[str, str] = {
    # All Klein-flavored variants ride on the parent Klein feature
    # (img2img/inpaint/controlnet, which depend on Klein checkpoint).
    "klein_edit":       "img2img",
    "klein_headswap":   "img2img",
    "klein_inpaint":    "inpaint",
    "klein_refine":     "img2img",
    "klein_repose":     "img2img",
    # Generic sub-methods of parent features.
    "controlnet_gen":   "controlnet",
    "faceswap":         "face_swap_reactor",  # MTB is alt-installable
    "photobooth":       "img2img",
    "reimagine":        "img2img",
    "relight":          "iclight",
}

# Methods that are real, registered, and shipping — but the installer
# doesn't (yet) have an opt-in feature for them. The wrapper packs +
# weights are installed by the user manually (or via the local update flow for
# NSFW). Update when these graduate to first-class installer features.
ADVANCED_NO_INSTALLER: set[str] = {
    "video_gen",         # FramePack/CogVideoX/HunyuanVideo/Mochi/LTX/WAN T2V
    "video_img2video",   # CogVideoX/FramePack/HunyuanVideo/LTX/WAN I2V
    "video_upscale",     # SeedVR / LTX / WAN upscale paths
    "video_animate",     # WAN Animate (build_wan_animate_video, native node)
    "mesh_gen",          # Hunyuan3D 2.1 image-to-mesh
    "mesh_textured",     # Hunyuan3D 2.1 textured-mesh (multi-view bake)
}


def _load_arch_registry() -> dict:
    """Load the architectures registry by importing the module.

    We don't statically parse architectures.py because the registry is
    expanded at import-time via `_reg(...)` calls — static parsing would
    miss edge cases. Adds the package dir to sys.path temporarily.
    """
    pkg_root = REPO_ROOT / "comfyui-spellcaster"
    sys.path.insert(0, str(pkg_root))
    try:
        from spellcaster_core import architectures as _arch  # type: ignore
        return _arch.ARCHITECTURES
    finally:
        sys.path.pop(0)


def main() -> int:
    if not MANIFEST.is_file():
        print(f"FATAL: manifest not found at {MANIFEST}", file=sys.stderr)
        return 2
    if not ARCH_FILE.is_file():
        print(f"FATAL: architectures.py not found at {ARCH_FILE}", file=sys.stderr)
        return 2

    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FATAL: bad manifest JSON: {exc}", file=sys.stderr)
        return 2

    try:
        registry = _load_arch_registry()
    except Exception as exc:
        print(f"FATAL: couldn't load architectures.py: {exc}", file=sys.stderr)
        return 2

    # Collect every method surfaced by any arch with non-empty supported_methods.
    arch_methods: dict[str, set[str]] = {}
    all_methods: set[str] = set()
    for key, arch in registry.items():
        sm = getattr(arch, "supported_methods", ()) or ()
        if not sm:
            continue
        registered = getattr(arch, "registered", True)
        if not registered:
            # Stub arch — supported_methods=() should be the convention.
            # If a stub still has methods, that's a separate (more urgent)
            # drift case caught by Tier 1.5.
            continue
        for m in sm:
            arch_methods.setdefault(key, set()).add(m)
            all_methods.add(m)

    # Collect manifest features.
    features = manifest.get("features", {})
    feature_keys = set(features.keys())

    # Drift A: methods named by some arch but with no manifest feature.
    # Some arch methods (e.g. "txt2img") have a 1:1 feature; others are
    # documented as either subsumed by a parent feature (SUBSUMED_BY_PARENT)
    # or as advanced features without a first-class installer entry yet
    # (ADVANCED_NO_INSTALLER). Both maps live at module top.
    raw_missing = all_methods - feature_keys
    methods_without_feature = sorted(
        m for m in raw_missing
        if m not in SUBSUMED_BY_PARENT and m not in ADVANCED_NO_INSTALLER
    )
    methods_subsumed = sorted(
        (m, SUBSUMED_BY_PARENT[m]) for m in raw_missing if m in SUBSUMED_BY_PARENT
    )
    methods_advanced = sorted(
        m for m in raw_missing if m in ADVANCED_NO_INSTALLER
    )
    # If a method is in SUBSUMED_BY_PARENT but its declared parent feature
    # doesn't exist, that IS drift (the doc map went stale).
    subsumed_with_missing_parent = sorted(
        (m, p) for m, p in methods_subsumed if p not in feature_keys
    )

    # Drift B: manifest features whose `lora_architectures` references an
    # unknown arch key (e.g. an arch was renamed/removed in the registry).
    arch_keys = set(registry.keys())
    features_with_unknown_arch = []
    for fkey, fval in features.items():
        for arch_ref in (fval.get("lora_architectures") or []):
            if arch_ref not in arch_keys:
                features_with_unknown_arch.append((fkey, arch_ref))

    # Report.
    drift = bool(methods_without_feature or features_with_unknown_arch
                 or subsumed_with_missing_parent)
    print("=" * 64)
    print("Spellcaster arch ↔ manifest drift report")
    print("=" * 64)
    print(f"  registered arches:        {len(arch_keys)}")
    print(f"  arches with methods:      {len(arch_methods)}")
    print(f"  total method names:       {len(all_methods)}")
    print(f"  manifest features:        {len(feature_keys)}")
    print(f"  subsumed exceptions:      {len(methods_subsumed)}")
    print(f"  advanced (no installer):  {len(methods_advanced)}")
    print()
    if methods_without_feature:
        print(f"DRIFT A: {len(methods_without_feature)} method(s) not in manifest features:")
        for m in methods_without_feature:
            owners = sorted(k for k, ms in arch_methods.items() if m in ms)
            print(f"  - method={m!r:24}  archs={owners}")
        print("  → add to installer/manifest.json features, OR add an explicit")
        print("    entry in SUBSUMED_BY_PARENT / ADVANCED_NO_INSTALLER at the")
        print("    top of this script if intentionally not exposed.")
        print()
    if subsumed_with_missing_parent:
        print(f"DRIFT C: {len(subsumed_with_missing_parent)} subsumed-by-parent claim(s) point at non-existent features:")
        for m, p in subsumed_with_missing_parent:
            print(f"  - method={m!r:24}  declared parent={p!r} (not in manifest features)")
        print("  → either fix SUBSUMED_BY_PARENT in this script, or restore the parent feature.")
        print()
    if features_with_unknown_arch:
        print(f"DRIFT B: {len(features_with_unknown_arch)} feature(s) reference unknown arch keys:")
        for fkey, ak in features_with_unknown_arch:
            print(f"  - feature={fkey!r:24}  unknown_arch={ak!r}")
        print("  → either remove the stale arch ref, or restore the arch in architectures.py.")
        print()
    if methods_subsumed and not subsumed_with_missing_parent:
        print(f"INFO: {len(methods_subsumed)} method(s) intentionally subsumed by a parent feature:")
        for m, p in methods_subsumed:
            print(f"  - method={m!r:24}  parent={p!r}")
        print()
    if methods_advanced:
        print(f"INFO: {len(methods_advanced)} advanced method(s) without a first-class installer feature:")
        for m in methods_advanced:
            owners = sorted(k for k, ms in arch_methods.items() if m in ms)
            print(f"  - method={m!r:24}  archs={owners}")
        print("  (wrappers/weights installed manually or via the local update flow; not drift.)")
        print()
    if not drift:
        print("[OK] No drift detected.")

    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
