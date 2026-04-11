"""SpellcasterPromptEnhance — LLM-powered prompt enhancement, architecture-aware.

This node sends prompts to a local LLM (KoboldCpp/Ollama/etc) for rewriting,
tuned per architecture. Uses the architecture's prompt_style to decide format
(booru tags vs natural language).
"""

import os
import sys
import json
import urllib.request
import urllib.error

# Add parent to path for spellcaster_core imports
_pack_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pack_dir not in sys.path:
    sys.path.insert(0, _pack_dir)

try:
    from spellcaster_core.architectures import get_arch
except ImportError as e:
    print(f"[SpellcasterPromptEnhance] WARNING: Failed to import spellcaster_core: {e}")
    get_arch = None


class SpellcasterPromptEnhance:
    """LLM-powered prompt enhancement, tuned per architecture.

    Sends the prompt to a local LLM (KoboldCpp/Ollama/etc) for rewriting.
    Uses the architecture's prompt_style to decide format (booru tags vs natural
    language). Useful for expanding vague prompts or enforcing style consistency.

    Returns:
      - enhanced_prompt: The rewritten prompt (or original if enhance=False)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "arch_key": ("STRING", {"default": "sdxl"}),
            },
            "optional": {
                "enhance": ("BOOLEAN", {"default": True}),
                "llm_url": ("STRING", {"default": "http://127.0.0.1:5001"}),
                "is_negative": ("BOOLEAN", {"default": False}),
                "model_override": ("STRING", {"default": "", "tooltip": "Optional LLM model name"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("enhanced_prompt",)
    FUNCTION = "enhance"
    CATEGORY = "Spellcaster"
    DESCRIPTION = "LLM-powered prompt enhancement, tuned per architecture."

    def enhance(self, prompt, arch_key, enhance=True, llm_url="http://127.0.0.1:5001",
                is_negative=False, model_override=""):
        """Enhance prompt via LLM or return unchanged.

        Args:
            prompt: Input prompt text (str)
            arch_key: Architecture key (e.g., "sdxl", "flux2klein")
            enhance: If False, return prompt unchanged
            llm_url: LLM server URL (e.g., KoboldCpp or Ollama)
            is_negative: If True, optimize for negative prompts
            model_override: Optional model override (passed to LLM)

        Returns:
            Tuple (enhanced_prompt,)
        """
        if not enhance:
            print(f"[SpellcasterPromptEnhance] Enhancement disabled, returning original prompt")
            return (prompt,)

        if not prompt or not prompt.strip():
            print(f"[SpellcasterPromptEnhance] Empty prompt, returning as-is")
            return (prompt,)

        if not get_arch:
            print(f"[SpellcasterPromptEnhance] spellcaster_core not available, returning unchanged")
            return (prompt,)

        arch = get_arch(arch_key)
        if not arch:
            print(f"[SpellcasterPromptEnhance] Unknown arch {arch_key}, returning unchanged")
            return (prompt,)

        # Build enhancement prompt based on architecture
        system_prompt = self._build_system_prompt(arch, is_negative)

        print(f"[SpellcasterPromptEnhance] Enhancing for {arch_key} (style={arch.prompt_style})")
        print(f"  LLM URL: {llm_url}")
        print(f"  Prompt length: {len(prompt)} chars")

        # Call LLM
        try:
            result = self._call_llm(prompt, system_prompt, llm_url, model_override)
            print(f"[SpellcasterPromptEnhance] Enhancement successful, result length: {len(result)} chars")
            return (result,)
        except Exception as e:
            print(f"[SpellcasterPromptEnhance] LLM call failed: {e}, returning original")
            return (prompt,)

    def _build_system_prompt(self, arch, is_negative):
        """Build system prompt based on architecture guidance."""
        prompt_type = "negative" if is_negative else "positive"
        style = arch.prompt_style

        base_prompt = f"""You are an expert prompt writer for the {arch.key} diffusion model.
Prompt style: {style}
{arch.prompt_guidance}

Your task: {prompt_type.upper()} PROMPT ENHANCEMENT
- Expand the user's {prompt_type} prompt to be more specific and effective
- Match the style: {style}
- Keep the core meaning while adding detail
- Return ONLY the enhanced prompt, no explanations or commentary
"""
        return base_prompt.strip()

    def _call_llm(self, prompt, system_prompt, llm_url, model_override):
        """Call LLM API (KoboldCpp/Ollama-compatible).

        Supports both KoboldCpp and Ollama API formats.
        """
        # Try KoboldCpp format first
        try:
            print(f"[SpellcasterPromptEnhance] Trying KoboldCpp API...")
            return self._call_kobold(prompt, system_prompt, llm_url, model_override)
        except Exception as e:
            print(f"[SpellcasterPromptEnhance] KoboldCpp failed: {e}")

        # Fallback to Ollama
        try:
            print(f"[SpellcasterPromptEnhance] Trying Ollama API...")
            return self._call_ollama(prompt, system_prompt, llm_url, model_override)
        except Exception as e:
            print(f"[SpellcasterPromptEnhance] Ollama failed: {e}")
            raise RuntimeError("Could not reach LLM server (KoboldCpp/Ollama)")

    def _call_kobold(self, prompt, system_prompt, llm_url, model_override):
        """Call KoboldCpp /api/v1/generate endpoint."""
        url = f"{llm_url}/api/v1/generate"

        payload = {
            "prompt": f"{system_prompt}\n\nUser: {prompt}\n\nAssistant:",
            "max_length": 500,
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 0,
            "rep_pen": 1.1,
            "rep_pen_range": 2048,
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST',
                                     headers={'Content-Type': 'application/json'})

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            if 'results' in result and len(result['results']) > 0:
                text = result['results'][0].get('text', '').strip()
                if text:
                    return text

        raise RuntimeError("No results from KoboldCpp")

    def _call_ollama(self, prompt, system_prompt, llm_url, model_override):
        """Call Ollama /api/generate endpoint."""
        url = f"{llm_url}/api/generate"

        model_name = model_override or "neural-chat"  # Default Ollama model

        payload = {
            "model": model_name,
            "prompt": f"{system_prompt}\n\nUser: {prompt}\n\nAssistant:",
            "temperature": 0.7,
            "top_p": 0.95,
            "stream": False,
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST',
                                     headers={'Content-Type': 'application/json'})

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            if 'response' in result:
                text = result['response'].strip()
                if text:
                    return text

        raise RuntimeError("No results from Ollama")


# Node registry (for ComfyUI)
NODE_CLASS_MAPPINGS = {
    "SpellcasterPromptEnhance": SpellcasterPromptEnhance,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SpellcasterPromptEnhance": "Spellcaster Prompt Enhance (LLM)",
}
