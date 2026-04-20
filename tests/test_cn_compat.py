"""Systematic ControlNet × architecture compatibility tests.

The user reported: picking a 3D Normal Map ControlNet on a Klein
preset (or any arch the CN doesn't list) silently fails at sampling
because the UI populated every CN mode regardless of the active
model. The fix is `cn_is_compatible` / `cn_modes_for_arch` in
spellcaster_core/model_detect.py — every UI picker (GIMP, Darktable,
Guild) MUST consult it before populating.

This test enumerates the canonical CONTROLNET_GUIDE_MODES dict
(loaded from the GIMP plugin where it lives) cross every
architecture key in the registry and asserts:

    * Klein / Kontext / Chroma never get a non-Off CN — those
      arches don't accept ControlNet at all (CLAUDE.md §9).
    * Off is ALWAYS available so the user can disable CN.
    * Every other (mode, arch) pair where cn_models has a key for
      the arch IS reported compatible — no false negatives that
      would hide working CN combos.
    * Every (mode, arch) where cn_models lacks the key OR cn_models
      is None+arch-forbidden is reported INcompatible — no false
      positives that would let the user pick a doomed CN.
    * cn_modes_for_arch preserves dict order (so "Off" stays first).
    * Spot checks for the user's exact failure mode (Normal Map on
      Klein) and the working path (Normal Map on SDXL).

Run from the repo root::

    PYTHONPATH=comfyui-spellcaster python tests/test_cn_compat.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO_ROOT, "comfyui-spellcaster")
if CORE_PATH not in sys.path:
    sys.path.insert(0, CORE_PATH)

from spellcaster_core.model_detect import (
    cn_is_compatible,
    cn_modes_for_arch,
    CN_FORBIDDEN_ARCHES,
)


# ── Load CONTROLNET_GUIDE_MODES from the GIMP plugin ─────────────────
# The dict lives in plugins/gimp/comfyui-connector/_spellcaster_main.py.
# We don't want to import the whole 22K-line module (pulls Gtk and
# triggers GIMP init), so parse out just the dict literal we need.

def _load_controlnet_guide_modes():
    src = os.path.join(REPO_ROOT, "plugins", "gimp", "comfyui-connector",
                        "_spellcaster_main.py")
    with open(src, "r", encoding="utf-8") as f:
        text = f.read()
    # Snip from "CONTROLNET_GUIDE_MODES = {" to its matching closing brace.
    start = text.index("CONTROLNET_GUIDE_MODES = {")
    # Brace-balance walk. The dict value is the trailing portion of the
    # source up to the brace that returns the depth to zero.
    i = text.index("{", start)
    depth = 0
    end = None
    for j in range(i, len(text)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    if end is None:
        raise RuntimeError("could not isolate CONTROLNET_GUIDE_MODES dict")
    snippet = text[start:end]
    ns = {}
    exec(compile(snippet, src, "exec"), ns)
    return ns["CONTROLNET_GUIDE_MODES"]


GUIDE_MODES = _load_controlnet_guide_modes()


# ── Architecture roster ──────────────────────────────────────────────
# All arches Spellcaster knows about; covers every model the user
# could realistically have loaded. Forbidden arches MUST get only the
# Off entry; others MUST get exactly the modes that map to their key.

ALL_ARCHES = (
    "sd15", "sdxl", "illustrious", "pony", "playground",
    "flux1dev", "flux2klein", "flux_kontext", "chroma",
    "zit", "wan", "ltx", "seedvr",
    "sd3", "sd3_turbo", "hunyuan_dit", "pixart", "auraflow", "kolors",
    "sdxl_turbo",
)


def _failures():
    """Yield (test_name, detail) for every assertion that fails."""

    # 1. "Off" is in the dict and IS available on every arch.
    assert "Off" in GUIDE_MODES, "GUIDE_MODES dict missing the canonical 'Off' entry"
    for arch in ALL_ARCHES:
        if not cn_is_compatible(GUIDE_MODES["Off"]["cn_models"], arch):
            yield ("off_always_compat",
                   f"'Off' should be compatible with arch={arch}")

    # 2. Forbidden arches get NOTHING but Off.
    for arch in CN_FORBIDDEN_ARCHES:
        modes = cn_modes_for_arch(GUIDE_MODES, arch)
        if modes != ["Off"]:
            yield ("forbidden_arch_only_off",
                   f"arch={arch} should yield ['Off'] only, got {modes}")

    # 3. For every non-Off mode and every supported arch:
    #    cn_is_compatible MUST return True iff cn_models has the arch key
    #    AND arch is not forbidden. No false positives, no false negatives.
    for mode_name, cfg in GUIDE_MODES.items():
        if mode_name == "Off":
            continue
        cn_models = cfg.get("cn_models")
        if not isinstance(cn_models, dict):
            continue
        for arch in ALL_ARCHES:
            expected = (arch not in CN_FORBIDDEN_ARCHES) and (arch in cn_models)
            actual = cn_is_compatible(cn_models, arch)
            if expected != actual:
                yield ("compat_mismatch",
                       f"mode={mode_name!r} arch={arch}: "
                       f"expected {expected}, got {actual} "
                       f"(cn_models keys={sorted(cn_models)})")

    # 4. cn_modes_for_arch preserves the original dict order so 'Off'
    #    stays at position 0 (every Spellcaster CN combo expects it).
    for arch in ALL_ARCHES:
        modes = cn_modes_for_arch(GUIDE_MODES, arch)
        if modes and modes[0] != "Off":
            yield ("off_must_be_first",
                   f"arch={arch}: first entry should be 'Off', got {modes[0]!r}")
        # Order should match the dict's iteration order over compatible keys
        in_dict_order = [
            k for k in GUIDE_MODES
            if cn_is_compatible(
                GUIDE_MODES[k].get("cn_models")
                if isinstance(GUIDE_MODES[k], dict) else None,
                arch)
        ]
        if modes != in_dict_order:
            yield ("order_drift",
                   f"arch={arch}: cn_modes_for_arch reordered keys")

    # 5. The user's exact failure mode — Normal Map on Klein. Find any
    #    "Normal Map" mode in the dict and assert it's INcompatible
    #    with flux2klein.
    nm_modes = [k for k in GUIDE_MODES if "normal map" in k.lower()]
    if not nm_modes:
        yield ("nm_modes_missing",
               "Expected at least one 'Normal Map' mode in GUIDE_MODES")
    for nm in nm_modes:
        for forbid in CN_FORBIDDEN_ARCHES:
            if cn_is_compatible(GUIDE_MODES[nm].get("cn_models"), forbid):
                yield ("nm_klein_regression",
                       f"{nm!r} must NOT be compatible with arch={forbid}")
        # Sanity: it MUST be compatible with at least one of the
        # arches it advertises in cn_models.
        models = GUIDE_MODES[nm].get("cn_models", {}) or {}
        usable = [a for a in models if a not in CN_FORBIDDEN_ARCHES]
        if usable and not any(
                cn_is_compatible(models, a) for a in usable):
            yield ("nm_no_compat",
                   f"{nm!r} should be compatible with at least one of {usable}")

    # 6. Defensive: empty/None inputs don't blow up.
    if cn_is_compatible(None, "sdxl") is not True:
        yield ("none_models_off_semantic",
               "cn_is_compatible(None, 'sdxl') should be True (Off semantics)")
    if cn_is_compatible({"sdxl": "x"}, "") is not False:
        yield ("empty_arch", "cn_is_compatible(..., '') should be False")
    if cn_is_compatible({"sdxl": "x"}, None) is not False:
        yield ("none_arch", "cn_is_compatible(..., None) should be False")
    if cn_modes_for_arch(None, "sdxl") != []:
        yield ("none_dict", "cn_modes_for_arch(None, ...) should be []")


def main():
    fails = list(_failures())
    print(f"=== ControlNet × arch compatibility — {len(GUIDE_MODES)} modes "
          f"× {len(ALL_ARCHES)} arches ===")
    if not fails:
        print(f"PASS — all {len(GUIDE_MODES) * len(ALL_ARCHES)} pairs validated.")
        return 0
    print(f"FAIL — {len(fails)} assertion(s):")
    for name, detail in fails:
        print(f"  [{name}] {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
