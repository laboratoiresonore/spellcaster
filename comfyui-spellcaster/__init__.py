"""ComfyUI-Spellcaster-NSFW — Architecture-aware nodes + NSFW LoRA presets.

NSFW edition inherits ALL nodes from the SFW base and adds:
  - SpellcasterNSFWLoRA:          NSFW LoRA presets by arch + category
  - SpellcasterNSFWLoRAModelOnly: Same, model-only (for video pipelines)

ONE SOURCE OF TRUTH: Core logic lives in spellcaster_core/.
NSFW presets are additive — all SFW updates apply automatically.
"""

import os
import sys

# Ensure spellcaster_core is importable (it lives inside this package)
_pack_dir = os.path.dirname(os.path.abspath(__file__))
if _pack_dir not in sys.path:
    sys.path.insert(0, _pack_dir)

# ── SFW base nodes (identical to ComfyUI-Spellcaster) ─────────────────
from .nodes.loader import SpellcasterLoader
from .nodes.prompt import SpellcasterPromptEnhance
from .nodes.sampler import SpellcasterSampler
from .nodes.output import SpellcasterOutput

# ── NSFW additions ─────────────────────────────────────────────────────
from .nodes.nsfw_loras import SpellcasterNSFWLoRA, SpellcasterNSFWLoRAModelOnly


NODE_CLASS_MAPPINGS = {
    # SFW base
    "SpellcasterLoader": SpellcasterLoader,
    "SpellcasterPromptEnhance": SpellcasterPromptEnhance,
    "SpellcasterSampler": SpellcasterSampler,
    "SpellcasterOutput": SpellcasterOutput,
    # NSFW additions
    "SpellcasterNSFWLoRA": SpellcasterNSFWLoRA,
    "SpellcasterNSFWLoRAModelOnly": SpellcasterNSFWLoRAModelOnly,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # SFW base
    "SpellcasterLoader": "Spellcaster Loader (Auto-Arch)",
    "SpellcasterPromptEnhance": "Spellcaster Prompt Enhance (LLM)",
    "SpellcasterSampler": "Spellcaster Sampler (Auto-Config)",
    "SpellcasterOutput": "Spellcaster Output (Privacy)",
    # NSFW additions
    "SpellcasterNSFWLoRA": "Spellcaster NSFW LoRA (Presets)",
    "SpellcasterNSFWLoRAModelOnly": "Spellcaster NSFW LoRA (Model Only)",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

print("\033[36m[Spellcaster NSFW]\033[0m Node pack loaded — 6 nodes registered (4 base + 2 NSFW)")
