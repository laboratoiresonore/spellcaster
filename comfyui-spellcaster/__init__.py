"""ComfyUI-Spellcaster — Architecture-aware nodes for AI image generation.

ONE SOURCE OF TRUTH: All architecture definitions, model detection,
prompt enhancement, and workflow construction live in spellcaster_core/.
GIMP plugin, Darktable plugin, and Wizard Guild all import from there.

Nodes:
  - SpellcasterLoader:        Auto-detect arch, load MODEL + CLIP + VAE
  - SpellcasterPromptEnhance: LLM-powered prompt rewriting per architecture
  - SpellcasterSampler:       Auto-select KSampler vs custom_advanced
  - SpellcasterOutput:        VAE decode + privacy-aware save
"""

import os
import sys

# Ensure spellcaster_core is importable (it lives inside this package)
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

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

print("\033[36m[Spellcaster]\033[0m Node pack loaded — 4 nodes registered")
