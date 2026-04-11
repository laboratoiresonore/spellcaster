"""NodeFactory — SHIM importing from canonical spellcaster_core.

The canonical source of the NodeFactory class lives in:
  comfyui-spellcaster/spellcaster_core/node_factory.py

This file re-exports everything for backward compatibility with existing
GIMP plugin code that does `from _nodes import ...`.
"""
import os
import sys

# Add the canonical spellcaster_core to path
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_core_parent = os.path.join(_repo_root, "comfyui-spellcaster")
if _core_parent not in sys.path:
    sys.path.insert(0, _core_parent)

# Re-export everything from the canonical source
from spellcaster_core.node_factory import *
