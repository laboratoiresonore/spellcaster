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
#  PROMPT ENHANCEMENT PROFILES (by architecture) — CANONICAL
# ═══════════════════════════════════════════════════════════════════════════
# Each architecture has unique prompting preferences. These profiles are the
# single source of truth for prompt grammar across every surface: the Guild,
# the GIMP plugin, the Darktable plugin, the ComfyUI-Spellcaster node pack,
# and anything else that calls `enhance_prompt()`. Do not maintain parallel
# copies anywhere.
#
# ── Validation record ─────────────────────────────────────────────────────
# Last end-to-end audit: 2026-04-19
#   LLMs:      Ollama gemma3:4b (chat backend), ComfyUI AILab_QwenVL_GGUF
#              (enhance backend)
#   Parameters: temperature=0.3, max_tokens=300
#   Test corpus: 1-person / 2-person / 3-person scene prompts across all 9
#                architectures below
#   Pass criteria:
#     - Tag-style archs (sd15, illustrious, pony, sdxl): output is pure
#       comma-separated tags, zero sentences/paragraphs, required quality
#       prefix present. BREAK blocks with per-character attributes on 2+
#       person scenes.
#     - Natural-language archs (flux1dev, flux2klein, chroma, wan, ltx):
#       flowing prose with no quality tags, correct length band, camera
#       / lighting / motion language where the profile specifies.
#   Results: 9/9 tag format, 9/9 quality conventions, 8/9 BREAK on 2p.
#            3-person BREAK adherence is 5/9 (LLM occasionally merges
#            characters when the GOOD example shows 2); users can steer
#            with explicit per-character prompts when N >= 3 matters.
#
# ── Upkeep rules ──────────────────────────────────────────────────────────
# - When adding a new architecture: add its profile here, then re-run the
#   1p/2p/3p audit to confirm the LLM can follow it. If it can't, tighten
#   the `notes` field with HARD FORMAT RULES and concrete GOOD/BAD examples
#   before shipping.
# - Do NOT change `style` or `length` without a corresponding re-audit.
# - Changes here must be synced to all three spellcaster_core copies per
#   CLAUDE.md Rule 3 (plugin / ComfyUI-Spellcaster / -NSFW).

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
        "length": "40-100 words",
        "notes": (
            "SDXL responds to both tags and short phrases. Start with the subject, "
            "then add style, lighting, and quality. Quality tags like 'masterpiece, "
            "best quality, highly detailed' ARE effective. Use commas to separate concepts.\n\n"
            "MULTI-CHARACTER RULES (CRITICAL — follow these when the prompt has 2+ people):\n"
            "- Start with the character count: '2girls', '1boy 1girl', '3people', etc.\n"
            "- Use the BREAK keyword (uppercase) to separate each character's description into its own block.\n"
            "- First block: scene/setting + character count + shared context.\n"
            "- Each subsequent BREAK block: one character only with ALL their attributes "
            "(hair, eyes, clothing, pose, position).\n"
            "- Always specify position: 'on the left', 'on the right', 'in the center'.\n"
            "- Make each character's attributes maximally DIFFERENT to prevent bleed.\n"
            "- Boost unique features with attention weights: (red hair:1.3)\n"
            "- Example: 'masterpiece, 2girls, fantasy tavern, warm lighting BREAK "
            "1girl, (long red hair:1.3), green eyes, leather armor, on the left BREAK "
            "1girl, (blonde bob:1.3), blue eyes, wizard robe, on the right'\n"
            "- NEVER list two characters' attributes in the same BREAK block."
        ),
    },
    # SD 1.5 — classic tag style
    "sd15": {
        "name": "Stable Diffusion 1.5",
        "style": "comma-separated tags",
        "length": "30-80 words",
        "notes": (
            "SD 1.5 works best with comma-separated tags/keywords.\n\n"
            "HARD FORMAT RULES — violating these destroys quality:\n"
            "- Output ONLY a flat comma-separated list of short tags and 2-4 word phrases.\n"
            "- NEVER write sentences or paragraphs. No 'The', 'A', 'With', 'Her', 'His' as sentence starters.\n"
            "- NO punctuation except commas and optional (attention:1.3) weights.\n"
            "- NO conjunctions (and, or, but, while, as).\n"
            "- Start with quality tags: 'masterpiece, best quality, highly detailed'.\n"
            "- Then subject, style, lighting, composition tags. Most important first.\n\n"
            "SINGLE CHARACTER GOOD: 'masterpiece, best quality, highly detailed, 1wizard, "
            "long silver hair, green eyes, blue cloak, casting fire spell, mystical forest, "
            "golden light, cinematic'\n"
            "BAD (never do this): 'masterpiece, best quality: the wizard stands in the forest "
            "with his hands raised as flames dance around him'\n\n"
            "MULTI-CHARACTER (2+ people) — BREAK IS MANDATORY:\n"
            "- First block: scene/setting + count tag ('2girls', '3friends'). No individual traits.\n"
            "- Each BREAK block after = ONE character with unique hair, eyes, clothing, pose, position.\n"
            "- Every character gets a position tag: 'on the left', 'on the right', 'in the center'.\n"
            "- Use (attention:1.3) on distinguishing features to prevent attribute bleed.\n"
            "GOOD 2-person: 'masterpiece, best quality, highly detailed, 2wizards, mystical forest, "
            "golden light BREAK 1wizard, (long silver hair:1.3), sharp blue eyes, green robe, "
            "on the left, holding staff BREAK 1wizard, (wavy brown hair:1.4), amber eyes, "
            "purple cloak, on the right, casting fire spell'\n"
            "BAD (never do this): '2wizards, long hair, dueling with staffs, dramatic lighting' "
            "— this merges both characters and causes attribute bleed."
        ),
    },
    # Illustrious / Pony — anime-focused SDXL derivatives
    "illustrious": {
        "name": "Illustrious",
        "style": "booru-style tags",
        "length": "30-80 words",
        "notes": (
            "Illustrious is trained on booru/danbooru-style tags. Use short comma-separated "
            "tags. Include character tags, pose, expression, outfit details. "
            "Quality: 'masterpiece, best quality, absurdres'. "
            "Use underscores in multi-word tags (e.g. long_hair, blue_eyes).\n\n"
            "MULTI-CHARACTER: Start with count tag (2girls, 1boy_1girl). Use BREAK "
            "between character blocks. Each block: one character with all tags "
            "(hair_color, eye_color, outfit, pose, position). "
            "Example: 'masterpiece, 2girls, indoors BREAK "
            "girl, red_hair, long_hair, green_eyes, armor, standing, on_the_left BREAK "
            "girl, blonde_hair, bob_cut, blue_eyes, robe, standing, on_the_right'"
        ),
    },
    "pony": {
        "name": "Pony Diffusion",
        "style": "score-prefixed booru tags",
        "length": "30-80 words",
        "notes": (
            "Pony Diffusion uses booru tags with score prefixes.\n\n"
            "HARD FORMAT RULES — violating these destroys quality:\n"
            "- Output ONLY comma-separated booru tags. NO sentences. NO paragraphs.\n"
            "- NO conjunctions (and, or, but, while, as). NO articles (the, a, with).\n"
            "- Every multi-word concept MUST use underscores: long_hair, blue_eyes, "
            "holding_staff, magical_battle, forest_clearing.\n"
            "- NEVER write 'two wizards dueling' — write '2boys, dueling, holding_staff'.\n"
            "- ALWAYS start with: 'score_9, score_8_up, score_7_up'\n"
            "- Then add scene tags, character tags, action tags. Most important first.\n\n"
            "SINGLE CHARACTER GOOD: 'score_9, score_8_up, score_7_up, 1wizard, "
            "long_silver_hair, blue_cloak, casting_fire_spell, mystical_forest, "
            "golden_light, (glowing_runes:1.3), cinematic'\n"
            "BAD (never do this): 'score_9, score_8_up, score_7_up wizard duel, two wizards "
            "in magical battle attire, staffs glowing with arcane energy'\n\n"
            "MULTI-CHARACTER (2+ people) — BREAK IS MANDATORY:\n"
            "- First block: scene/setting + count tag (2girls, 1boy_1girl, 3friends). No individual traits.\n"
            "- Each BREAK block after = ONE character with unique underscored tags for "
            "hair, eyes, clothing, pose, position.\n"
            "- Every character gets a position tag (on_the_left, on_the_right, in_the_center).\n"
            "- Use (attention:1.3) on distinguishing features to prevent attribute bleed.\n"
            "GOOD 2-person: 'score_9, score_8_up, score_7_up, 2boys, mystical_forest, "
            "golden_light BREAK boy, (long_silver_hair:1.3), blue_eyes, green_robe, "
            "on_the_left, holding_staff BREAK boy, (wavy_brown_hair:1.4), amber_eyes, "
            "purple_cloak, on_the_right, casting_fire_spell'\n"
            "BAD (never do this): 'score_9, score_8_up, score_7_up, 2boys, dueling, "
            "holding_staff, magical_battle' — this merges both characters and "
            "causes attribute bleed."
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
                   comfy_url=None, model_name=None):
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
    # Negative prompts list things to AVOID (e.g. "blurry, low quality").
    # Expanding them with an LLM would add unwanted positive descriptions.
    if is_negative:
        return prompt_text

    if not prompt_text or not prompt_text.strip():
        return prompt_text

    # 60-word threshold: prompts above this length are already well-formed
    # (probably copy-pasted from CivitAI or manually crafted). Enhancing them
    # risks over-inflating the prompt and diluting the user's intent.
    # Below 60 words, the user likely typed a short description ("cat sleeping")
    # that benefits from expansion.
    word_count = len(prompt_text.split())
    if word_count > 60:
        return prompt_text

    # Each architecture has a unique prompting style. Using the wrong style
    # (e.g. booru tags for Flux, or natural language for SD1.5) produces
    # noticeably worse results. The profile tells the LLM how to format output.
    profile = _ARCH_ENHANCE_PROFILES.get(arch_key, _DEFAULT_ENHANCE_PROFILE)

    # Per-model overlay: if the caller named a specific checkpoint and
    # the user has curated per-model hints / profile overrides in the
    # llm_prompt_db, merge them on top of the arch baseline. This lets
    # "this klein finetune likes 40-word prompts" travel with the model
    # without hard-coding it into the arch profile.
    if model_name:
        try:
            from . import llm_prompt_db
            profile = llm_prompt_db.merge_with_profile(model_name, profile)
        except Exception:
            pass  # DB unavailable — fall back to arch baseline

    # Build system prompt that guides the LLM.
    # The `Target style` line is load-bearing: if it says "tags" then the
    # output MUST be tags (not prose). Small LLMs (4B Qwen/Gemma) tend to
    # default to paragraph prose unless we insist otherwise. The per-arch
    # notes reinforce this with concrete GOOD/BAD examples for tag-style
    # archs; see sd15 and pony profiles above.
    system_msg = (
        f"You are a prompt engineer for {profile['name']} image generation. "
        f"Your ONLY job is to expand the user's short description into an optimised "
        f"prompt for {profile['name']}.\n\n"
        f"Target style: {profile['style']}\n"
        f"Target length: {profile['length']}\n\n"
        f"{profile['notes']}\n\n"
        "RULES:\n"
        "- Output ONLY the enhanced prompt text — no explanations, no labels, no markdown.\n"
        "- The Target style is MANDATORY. If it says 'tags', output tags, never sentences. "
        "If it says 'natural language', output a paragraph, never a tag list.\n"
        "- Preserve the user's core intent exactly — do NOT change what they asked for.\n"
        "- Add detail, atmosphere, lighting, and style where missing.\n"
        "- Do NOT add NSFW content unless the input already contains it.\n"
        "- Do NOT wrap the output in quotes."
    )

    user_msg = f"Enhance this prompt for {profile['name']}:\n{prompt_text}"

    # ── One backend, many surfaces ─────────────────────────────────────
    # Route through spellcaster_core.guild_llm.chat — THE single LLM
    # entry point shared by the Guild, the GIMP plugin, Darktable, and
    # any other surface. Do NOT add a parallel LLM path here.
    #
    # For prompt enhancement we set purpose="enhance" which tries
    # ComfyUI's purpose-built PromptEnhancer node first (it lives on
    # the ComfyUI box alongside the diffusion model, and ComfyUI
    # auto-unloads the LLM before image generation — the full cycle
    # is load-LLM / enhance / unload-LLM / generate / reload-LLM).
    # Ollama and KoboldCpp are the fallbacks.
    try:
        from . import guild_llm
    except Exception:
        return prompt_text
    # Sampling defaults for the structured-enhancement task. Per-model
    # overrides from llm_prompt_db can override any of these; the base
    # stays conservative because high temperature makes the LLM drift
    # into prose when the profile demands tags, or skip BREAK blocks
    # in multi-character scenes.
    sampling_defaults = {
        "temperature": 0.3,
        "max_tokens":  300,
        "top_p":       0.9,
    }
    if model_name:
        try:
            from . import llm_prompt_db
            sampling = llm_prompt_db.get_effective_params(
                model_name, sampling_defaults)
        except Exception:
            sampling = sampling_defaults
    else:
        sampling = sampling_defaults
    try:
        enhanced = guild_llm.chat(
            message=user_msg, system_prompt=system_msg,
            server=comfy_url, kobold_url=kobold_url,
            max_tokens=int(sampling.get("max_tokens", 300)),
            temperature=float(sampling.get("temperature", 0.3)),
            purpose="enhance",
        )
    except Exception:
        enhanced = None
    # 10-char minimum filters junk responses like "OK" or whitespace.
    if enhanced and len(enhanced.strip()) > 10:
        return _clean_enhanced(enhanced)
    return prompt_text


def _clean_enhanced(text):
    """Strip wrappers the LLM sometimes adds (quotes, 'Enhanced:' label,
    leading/trailing whitespace). Keep only the prompt itself.
    """
    s = (text or "").strip()
    # Strip label prefixes like "Enhanced prompt:", "Prompt:", "Here:"
    for prefix in ("Enhanced prompt:", "Enhanced:", "Prompt:", "Here:",
                   "Here is:", "Output:"):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):].strip()
    # Strip outer quotes (single or double)
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
        s = s[1:-1].strip()
    return s
