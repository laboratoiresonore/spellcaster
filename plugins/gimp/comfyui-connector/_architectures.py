"""Architecture Registry — SHIM that imports from canonical spellcaster_core.

The canonical source of all architecture definitions lives in:
  comfyui-spellcaster/spellcaster_core/architectures.py

This file re-exports everything for backward compatibility with existing
GIMP plugin code that does `from _architectures import ...`.

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
from spellcaster_core.architectures import *
from spellcaster_core.architectures import ARCHITECTURES, ArchConfig, get_arch, _reg
