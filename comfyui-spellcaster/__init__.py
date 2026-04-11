"""ComfyUI-Spellcaster — Architecture-aware nodes for image generation.

ONE SOURCE OF TRUTH: All architecture definitions, model detection,
prompt enhancement, and workflow construction live in spellcaster_core/.
GIMP plugin, Darktable plugin, and Wizard Guild all import from there.
"""

import os
import sys

# Ensure spellcaster_core is importable
_pack_dir = os.path.dirname(os.path.abspath(__file__))
if _pack_dir not in sys.path:
    sys.path.insert(0, _pack_dir)

from .nodes.loader import SpellcasterLoader
from .nodes.prompt import SpellcasterPromptEnhance
from .nodes.sampler import SpellcasterSampler
from .nodes.output import SpellcasterOutput


NODE_CLASS_MAPPINGS = {
    "SpellcasterLoader": SpellcasterLoader,
    "SpellcasterPromptEnhance": SpellcasterPromptEnhance,
    "SpellcasterSampler": SpellcasterSampler,
    "SpellcasterOutput": SpellcasterOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SpellcasterLoader": "Spellcaster Loader (Auto-Arch)",
    "SpellcasterPromptEnhance": "Spellcaster Prompt Enhance (LLM)",
    "SpellcasterSampler": "Spellcaster Sampler (Auto-Config)",
    "SpellcasterOutput": "Spellcaster Output (Privacy)",
}

WEB_DIRECTORY = None

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

print("[Spellcaster] Node pack loaded — 4 nodes registered")
