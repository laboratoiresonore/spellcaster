"""SpellcasterPromptEnhance — LLM-powered prompt enhancement, architecture-aware.

Sends prompts to a local LLM (KoboldCpp / Ollama / any OpenAI-compatible
server) for rewriting, tuned per architecture.  Uses prompt_style and
prompt_guidance from ArchConfig to generate architecture-specific system prompts.
"""

import os
import sys
import json
import urllib.request
import urllib.error

# ── spellcaster_core import ────────────────────────────────────────────
_pack_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pack_dir not in sys.path:
    sys.path.insert(0, _pack_dir)

from spellcaster_core.architectures import get_arch


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

        arch = get_arch(arch_key)
        system = self._build_system(arch, is_negative)

        print(f"\033[36m[Spellcaster]\033[0m Enhancing prompt for {arch_key} "
              f"(style={arch.prompt_style}, negative={is_negative})")

        # Try OpenAI-compatible API first (KoboldCpp /v1/chat/completions),
        # then fall back to KoboldCpp /api/v1/generate,
        # then Ollama /api/generate.
        for fn in (self._call_openai, self._call_kobold, self._call_ollama):
            try:
                result = fn(prompt, system, llm_url)
                if result and result.strip():
                    print(f"\033[36m[Spellcaster]\033[0m Enhanced: "
                          f"{len(prompt)} → {len(result)} chars")
                    return (result.strip(),)
            except Exception as e:
                print(f"\033[36m[Spellcaster]\033[0m {fn.__name__} failed: {e}")

        print(f"\033[36m[Spellcaster]\033[0m All LLM endpoints failed, "
              f"returning original prompt")
        return (prompt,)

    # ── system prompt builder ──────────────────────────────────────────
    @staticmethod
    def _build_system(arch, is_negative):
        if is_negative:
            return (
                f"You are an expert at writing negative prompts for the "
                f"{arch.key} diffusion model. Optimize the following negative "
                f"prompt. Output ONLY the optimized negative prompt, "
                f"no commentary."
            )

        style = arch.prompt_style
        guidance = arch.prompt_guidance or ""

        if style == "booru_tags":
            task = (
                "Rewrite the following image prompt as optimized "
                "comma-separated booru/danbooru tags. Keep the core concept. "
                "Add quality tags. Output ONLY the tags, no commentary."
            )
        elif style == "natural":
            task = (
                "Rewrite the following image prompt as a detailed "
                "natural-language description. Be verbose and descriptive. "
                "Output ONLY the enhanced prompt, no commentary."
            )
        else:
            task = (
                "Improve the following image prompt for the "
                f"{arch.key} model. Output ONLY the enhanced prompt."
            )

        return f"{task}\n\nExpert guidance for {arch.key}:\n{guidance}"

    # ── API callers ────────────────────────────────────────────────────
    @staticmethod
    def _call_openai(prompt, system, llm_url):
        """OpenAI-compatible /v1/chat/completions (KoboldCpp, vLLM, etc)."""
        url = f"{llm_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": "koboldcpp",
            "max_tokens": 300,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]

    @staticmethod
    def _call_kobold(prompt, system, llm_url):
        """KoboldCpp /api/v1/generate (legacy)."""
        url = f"{llm_url.rstrip('/')}/api/v1/generate"
        payload = {
            "prompt": f"{system}\n\nUser: {prompt}\n\nAssistant:",
            "max_length": 300,
            "temperature": 0.7,
            "top_p": 0.95,
            "rep_pen": 1.1,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["results"][0]["text"]

    @staticmethod
    def _call_ollama(prompt, system, llm_url):
        """Ollama /api/generate."""
        url = f"{llm_url.rstrip('/')}/api/generate"
        payload = {
            "model": "llama3",
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["response"]
