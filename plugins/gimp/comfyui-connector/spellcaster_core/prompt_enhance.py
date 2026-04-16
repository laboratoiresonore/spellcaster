"""Prompt enhancement — LLM-based prompt rewriting per architecture.

This module handles expanding short user prompts into full prompts optimized
for a specific model architecture (e.g. SDXL, Flux, Illustrious).

It was originally embedded in server.py but is extracted here to be:
  1. Reusable across different backends (Guild, GIMP plugin, ComfyUI nodes)
  2. Testable in isolation
  3. Centralized for prompt engineering updates

USAGE:
    from spellcaster_core.prompt_enhance import enhance_prompt

    enhanced = enhance_prompt(
        "cat sleeping in sunlight",
        arch_key="sdxl",
        kobold_url="http://127.0.0.1:5001",
        is_negative=False
    )
    # Returns: "A beautiful cat sleeping peacefully in warm sunlight..."

If the LLM is unavailable or times out, returns the original prompt unchanged.
"""

import json
import urllib.request
import urllib.error

from .architectures import get_arch


# ═══════════════════════════════════════════════════════════════════════════
#  PROMPT ENHANCEMENT PROFILES (by architecture)
# ═══════════════════════════════════════════════════════════════════════════
# Each architecture has unique prompting preferences. These profiles guide
# the LLM in how to rewrite prompts for optimal results with that model.

_ARCH_ENHANCE_PROFILES = {
    # Flux 1 Dev — natural-language, moderate length, no quality tags
    "flux1dev": {
        "name": "Flux 1 Dev",
        "style": "natural language, flowing description",
        "length": "80-150 words",
        "notes": (
            "Flux excels with natural-language prompts. Write a vivid, "
            "flowing paragraph. Do NOT use comma-separated tag lists. "
            "Avoid quality tags like 'masterpiece' or '8k' — Flux ignores them. "
            "Focus on subject, scene, lighting, mood, and composition."
        ),
    },
    # Flux 2 Klein 4B/9B — concise natural language
    "flux2klein": {
        "name": "Flux 2 Klein",
        "style": "concise natural language",
        "length": "60-100 words",
        "notes": (
            "Klein responds best to short, focused natural-language prompts. "
            "Keep it tight — one clear paragraph. No quality tags. "
            "Describe the subject and scene directly."
        ),
    },
    # Chroma — same as Klein (Flux2 family)
    "chroma": {
        "name": "Chroma",
        "style": "concise natural language",
        "length": "60-100 words",
        "notes": (
            "Chroma uses the same Flux 2 engine. Short, focused natural-language prompts. "
            "Describe the subject and scene directly. No quality tags."
        ),
    },
    # SDXL — hybrid tags + natural language
    "sdxl": {
        "name": "SDXL",
        "style": "tag-based with natural language phrases",
        "length": "40-80 words",
        "notes": (
            "SDXL responds to both tags and short phrases. Start with the subject, "
            "then add style, lighting, and quality. Quality tags like 'masterpiece, "
            "best quality, highly detailed' ARE effective. Use commas to separate concepts."
        ),
    },
    # SD 1.5 — classic tag style
    "sd15": {
        "name": "Stable Diffusion 1.5",
        "style": "comma-separated tags",
        "length": "30-60 words",
        "notes": (
            "SD 1.5 works best with comma-separated tags/keywords. "
            "Quality tags are essential: 'masterpiece, best quality, highly detailed'. "
            "Order matters — put the most important concepts first. "
            "Include style, medium, lighting, and composition tags."
        ),
    },
    # Illustrious / Pony — anime-focused SDXL derivatives
    "illustrious": {
        "name": "Illustrious",
        "style": "booru-style tags",
        "length": "30-70 words",
        "notes": (
            "Illustrious is trained on booru/danbooru-style tags. Use short comma-separated "
            "tags. Include character tags, pose, expression, outfit details. "
            "Quality: 'masterpiece, best quality, absurdres'. "
            "Use underscores in multi-word tags (e.g. long_hair, blue_eyes)."
        ),
    },
    "pony": {
        "name": "Pony Diffusion",
        "style": "score-prefixed booru tags",
        "length": "30-70 words",
        "notes": (
            "Pony Diffusion uses booru tags with score prefixes. "
            "Start with 'score_9, score_8_up, score_7_up' for quality. "
            "Then character/scene tags. Use underscores for multi-word tags."
        ),
    },
    # WAN — video/image, natural language
    "wan": {
        "name": "WAN 2.1",
        "style": "cinematic natural language",
        "length": "80-150 words",
        "notes": (
            "WAN excels with cinematic, descriptive natural-language prompts. "
            "Describe the scene as if writing a film shot — subject, action, "
            "camera angle, lighting, atmosphere, motion. For video: include "
            "movement descriptions. Keep it vivid and specific."
        ),
    },
    # LTX Video
    "ltx": {
        "name": "LTX Video 2.3",
        "style": "cinematic/filmic natural language",
        "length": "100-200 words",
        "notes": (
            "LTX Video responds to extended cinematic descriptions. "
            "Write as if describing a film scene: establish the setting, "
            "describe the subject in detail, specify camera movement "
            "(pan, dolly, tracking shot), lighting (golden hour, rim light), "
            "mood, and temporal progression. Be specific about motion and timing."
        ),
    },
    # SD3 / SD3 Turbo
    "sd3": {
        "name": "Stable Diffusion 3",
        "style": "natural language with light tagging",
        "length": "50-100 words",
        "notes": (
            "SD3 understands natural language well but also responds to tags. "
            "Write a clear description with some quality markers. "
            "Focus on subject, composition, and style."
        ),
    },
    "sd3_turbo": {
        "name": "SD3 Turbo",
        "style": "natural language with light tagging",
        "length": "50-100 words",
        "notes": (
            "SD3 Turbo — same prompting as SD3 but keep it concise. "
            "Clear subject, style, and lighting. Moderate detail."
        ),
    },
}

# Fallback for unknown architectures
_DEFAULT_ENHANCE_PROFILE = {
    "name": "Generic",
    "style": "descriptive natural language",
    "length": "60-120 words",
    "notes": (
        "Write a clear, vivid description of the scene. "
        "Include subject, setting, lighting, mood, and composition. "
        "Be specific and descriptive."
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
#  ENHANCEMENT FUNCTION
# ═══════════════════════════════════════════════════════════════════════════

def enhance_prompt(prompt_text, arch_key, kobold_url=None, is_negative=False,
                   comfy_url=None):
    """Expand a terse user prompt into an architecture-optimised description.

    Tries ComfyUI LLM nodes first (if comfy_url provided), then falls back
    to the external LLM at kobold_url via OpenAI-compatible API.
    Returns the original prompt unchanged on any error (never blocks generation).

    Args:
        prompt_text: The raw prompt string from the user
        arch_key: Architecture identifier (e.g. 'flux1dev', 'sdxl', 'wan')
        kobold_url: Base URL of external LLM (e.g. 'http://127.0.0.1:5001')
        is_negative: If True, skip enhancement (negatives don't need expansion)
        comfy_url: ComfyUI server URL — if set, tries native LLM nodes first

    Returns:
        Enhanced prompt string, or the original if enhancement fails
    """
    # Skip enhancement for negative prompts — they don't benefit from expansion
    if is_negative:
        return prompt_text

    # Skip if prompt is empty or already long/well-formed
    if not prompt_text or not prompt_text.strip():
        return prompt_text

    word_count = len(prompt_text.split())
    if word_count > 60:
        # Already detailed enough — don't over-enhance
        return prompt_text

    # Look up architecture profile (with fallback to generic)
    profile = _ARCH_ENHANCE_PROFILES.get(arch_key, _DEFAULT_ENHANCE_PROFILE)

    # Build system prompt that guides the LLM
    system_msg = (
        f"You are a prompt engineer for {profile['name']} image generation. "
        f"Your ONLY job is to expand the user's short description into an optimised "
        f"prompt for {profile['name']}.\n\n"
        f"Target style: {profile['style']}\n"
        f"Target length: {profile['length']}\n\n"
        f"{profile['notes']}\n\n"
        "RULES:\n"
        "- Output ONLY the enhanced prompt text — no explanations, no labels, no markdown.\n"
        "- Preserve the user's core intent exactly — do NOT change what they asked for.\n"
        "- Add detail, atmosphere, lighting, and style where missing.\n"
        "- Do NOT add NSFW content unless the input already contains it.\n"
        "- Do NOT wrap the output in quotes."
    )

    user_msg = f"Enhance this prompt for {profile['name']}:\n{prompt_text}"

    # ── Try ComfyUI LLM nodes first (if server URL provided) ──
    if comfy_url:
        try:
            from .comfyui_llm import generate_text
            enhanced = generate_text(
                comfy_url, prompt=user_msg, system_prompt=system_msg,
                max_tokens=300, temperature=0.7)
            if enhanced and len(enhanced) > 10:
                return enhanced
        except Exception:
            pass  # Fall through to KoboldCpp

    # ── Fall back to external LLM (KoboldCpp / OpenAI-compatible) ──
    if not kobold_url:
        return prompt_text

    # Prepare the API payload (OpenAI-compatible format)
    payload = {
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "model": "koboldcpp",
        "max_tokens": 300,
        "temperature": 0.7,
    }

    try:
        # Call the LLM API
        url = f"{kobold_url.rstrip('/')}/v1/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        # Extract the enhanced prompt from the response
        enhanced = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        # Only use enhancement if it's meaningful (>10 chars)
        if enhanced and len(enhanced) > 10:
            return enhanced

        # LLM returned empty or junk — fall back
        return prompt_text

    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            TimeoutError, Exception) as e:
        # Any error (timeout, connection refused, JSON parse error, etc) — just
        # return the original prompt unchanged. Never block generation.
        return prompt_text
