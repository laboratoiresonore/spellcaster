"""SpellcasterPromptEnhance — LLM-powered prompt enhancement, architecture-aware.

Delegates to spellcaster_core.prompt_enhance (single source of truth) for
all LLM interaction.  Uses external LLM servers only (KoboldCpp, Ollama,
or any OpenAI-compatible API) — NOT ComfyUI LLM nodes, because this node
runs INSIDE a ComfyUI workflow and submitting a nested workflow would
deadlock the queue.
"""

import os
import sys



class SpellcasterPromptEnhance:
    """LLM-powered prompt enhancement, tuned per architecture."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Input prompt to enhance.",
                }),
                "arch_key": ("STRING", {
                    "default": "sdxl",
                    "tooltip": "Architecture key (from Spellcaster Loader).",
                }),
            },
            "optional": {
                "enhance": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Enable/disable LLM enhancement.",
                }),
                "llm_url": ("STRING", {
                    "default": "http://127.0.0.1:5001",
                    "tooltip": "LLM server URL (KoboldCpp, Ollama, or OpenAI-compatible).",
                }),
                "is_negative": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Optimize as a negative prompt instead.",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("enhanced_prompt",)
    FUNCTION = "enhance"
    CATEGORY = "Spellcaster"
    DESCRIPTION = (
        "LLM-powered prompt enhancement. Sends your prompt to a local LLM "
        "for rewriting — booru tags for SD/SDXL, natural language for Flux/Klein."
    )
    SEARCH_ALIASES = ["spellcaster prompt", "llm prompt", "enhance prompt",
                      "prompt rewrite"]

    def enhance(self, prompt, arch_key, enhance=True,
                llm_url="http://127.0.0.1:5001", is_negative=False):

        if not enhance or not prompt or not prompt.strip():
            return (prompt,)

        print(f"\033[36m[Spellcaster]\033[0m Enhancing prompt for {arch_key} "
              f"(negative={is_negative})")

        # Delegate to the single source of truth.
        # comfy_url is intentionally NOT passed — this node runs inside a
        # ComfyUI workflow, and submitting a nested LLM workflow would
        # deadlock the queue.  External LLM servers only.
        from ..spellcaster_core.prompt_enhance import enhance_prompt
        result = enhance_prompt(
            prompt, arch_key,
            kobold_url=llm_url,
            is_negative=is_negative,
            comfy_url=None,
        )

        if result and result != prompt:
            print(f"\033[36m[Spellcaster]\033[0m Enhanced: "
                  f"{len(prompt)} → {len(result)} chars")
        else:
            print(f"\033[36m[Spellcaster]\033[0m Enhancement skipped or "
                  f"returned original prompt")

        return (result,)
