"""Composite workflow helpers — SHIM importing from canonical spellcaster_core.

The canonical source of all composite patterns lives in:
  comfyui-spellcaster/spellcaster_core/composites.py

This file re-exports everything for backward compatibility with existing
GIMP plugin code that does `from _composites import ...`.

Lookup order:
  1. spellcaster_core/ bundled alongside this file (installed plugin)
  2. comfyui-spellcaster/spellcaster_core/ in the repo tree (dev checkout)
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))

# 1) Bundled copy — lives in the same directory as the plugin
if os.path.isdir(os.path.join(_here, "spellcaster_core")):
    if _here not in sys.path:
        sys.path.insert(0, _here)
else:
    # 2) Dev checkout — navigate up to repo root
    _core_parent = os.path.join(_here, "..", "..", "..", "comfyui-spellcaster")
    _core_parent = os.path.abspath(_core_parent)
    if os.path.isdir(os.path.join(_core_parent, "spellcaster_core")):
        if _core_parent not in sys.path:
            sys.path.insert(0, _core_parent)

# Re-export everything from the canonical source
try:
    from spellcaster_core.composites import *
except ImportError:
    print("[Spellcaster] WARNING: spellcaster_core/composites not found.", file=sys.stderr)

    # Stubs so the plugin can load. Functions raise at call time.
    def _missing(*a, **kw):
        raise RuntimeError(
            "spellcaster_core is missing. Open Spellcaster Settings "
            "and click Repair/Update, or reinstall the plugin.")
    load_model_stack = _missing
    inject_lora_chain = _missing
    encode_prompts = _missing
    sample_standard = _missing
    sample_klein_img2img = _missing
    inject_controlnet = _missing
    inject_controlnet_pair = _missing
