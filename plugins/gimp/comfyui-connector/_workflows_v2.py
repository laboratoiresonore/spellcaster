"""Workflow Builders — SHIM importing from canonical spellcaster_core.

The canonical source of all workflow builders lives in:
  comfyui-spellcaster/spellcaster_core/workflows.py

This file re-exports everything for backward compatibility with existing
code that does `from _workflows_v2 import build_txt2img` etc.

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
    from spellcaster_core.workflows import *
except ImportError:
    print("[Spellcaster] WARNING: spellcaster_core.workflows not found. "
          "Use Repair/Update in Settings or reinstall.", file=sys.stderr)
