"""Prompt enhancement — LLM-based prompt rewriting per architecture.

This module handles expanding short user prompts into full prompts optimized
for a specific model architecture (e.g. SDXL, Flux, Illustrious).

It was originally embedded in server.py but is extracted here to be:
  1. Reusable across different backends (Guild, GIMP plugin, ComfyUI nodes)
  2. Testable in isolation
  3. Centralized for prompt engineering updates

USAGE:
    from .prompt_enhance import enhance_prompt

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
        "max_tokens": 512,
        "notes": (
            "Flux excels with natural-language prompts. Write a vivid, "
            "flowing paragraph. Do NOT use comma-separated tag lists. "
            "Avoid quality tags like 'masterpiece' or '8k' — Flux ignores them. "
            "Focus on subject, scene, lighting, mood, and composition.\n\n"
            "LENGTH IS IMPORTANT: aim squarely for the middle of the 80-150 "
            "word range. Short prompts underfire this model."
        ),
    },
    # Flux 2 Klein 4B/9B — concise natural language
    "flux2klein": {
        "name": "Flux 2 Klein",
        "style": "concise natural language",
        "length": "60-100 words",
        "max_tokens": 384,
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
        "max_tokens": 384,
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
        "max_tokens": 384,
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
        "max_tokens": 256,
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
        "max_tokens": 256,
        "notes": (
            "Illustrious is trained on booru/danbooru-style tags. Use short comma-separated "
            "tags. Include character tags, pose, expression, outfit details. "
            "Quality: 'masterpiece, best quality, absurdres'. "
            "Use underscores in multi-word tags (e.g. long_hair, blue_eyes).\n\n"
            "SUBJECT PRESERVATION (CRITICAL):\n"
            "- The user's subject count is LAW. If the user asks for '1girl', output "
            "ONLY '1girl' — never append '1boy' or 'japanese_boy' or any other "
            "character you weren't asked for.\n"
            "- Never introduce a second gender or a second character unless the user "
            "explicitly mentioned them.\n"
            "- Preserve the exact species / type (girl, boy, woman, man, samurai, "
            "elf, etc.) the user wrote.\n\n"
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
        "max_tokens": 256,
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
        "max_tokens": 512,
        "notes": (
            "WAN excels with cinematic, descriptive natural-language prompts. "
            "Describe the scene as if writing a film shot — subject, action, "
            "camera angle, lighting, atmosphere, motion. For video: include "
            "movement descriptions. Keep it vivid and specific.\n\n"
            "LENGTH: hit the middle of 80-150 words — WAN's motion prior "
            "starves on short prompts."
        ),
    },
    # LTX Video
    "ltx": {
        "name": "LTX Video 2.3",
        "style": "cinematic/filmic natural language",
        "length": "100-200 words",
        "max_tokens": 768,
        "notes": (
            "LTX Video responds to extended cinematic descriptions. "
            "Write as if describing a film scene: establish the setting, "
            "describe the subject in detail, specify camera movement "
            "(pan, dolly, tracking shot), lighting (golden hour, rim light), "
            "mood, and temporal progression. Be specific about motion and timing.\n\n"
            "LENGTH: LTX explicitly REWARDS long prompts. Aim for 150-200 "
            "words — short prompts produce static shots."
        ),
    },
    # SD3 / SD3 Turbo
    "sd3": {
        "name": "Stable Diffusion 3",
        "style": "natural language with light tagging",
        "length": "50-100 words",
        "max_tokens": 384,
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
        "max_tokens": 384,
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
    "max_tokens": 384,
    "notes": (
        "Write a clear, vivid description of the scene. "
        "Include subject, setting, lighting, mood, and composition. "
        "Be specific and descriptive."
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
#  PER-METHOD ENHANCEMENT OVERLAYS
# ═══════════════════════════════════════════════════════════════════════════
# The arch profiles above describe how to format a prompt for a given
# DIFFUSION FAMILY (SDXL = booru tags, Flux = natural language, etc.).
# But different GENERATION METHODS on the same family want completely
# different prompt CONTENT. An inpaint prompt describes only what fills
# the masked region; an outpaint describes what extends beyond the
# canvas; a face-detail refinement describes only facial features; a
# relight describes only the lighting. Without a method overlay, the
# enhancer happily rewrites "a red hat" into a full-scene description
# and inpaint injects a whole sky into the tiny hat area.
#
# Each method profile can:
#   - `skip: True`        — bypass enhancement entirely (edit-instructions,
#                           pure-utility ops, preset-driven tools).
#   - `extra_notes: str`  — appended to the arch profile's notes so the
#                           LLM sees BOTH the arch grammar rules AND the
#                           method-specific scope.
#   - `length_override:`  — replaces the arch profile's length band
#                           (shorter for narrow scopes like "face_detail").
#   - `style_override:`   — replaces the arch profile's style hint.
#
# `method` is a free-form string; unknown values fall through to scene
# behaviour (no overlay). Canonical method keys below; add more as new
# generation pipelines land.
_METHOD_PROFILES = {
    # Pass-through — no LLM call. Used for methods where the prompt is
    # either a literal edit instruction, a preset selector, or absent.
    "edit":            {"skip": True},   # Kontext / Qwen-Edit instructions
    "kontext":         {"skip": True},
    "qwen_edit":       {"skip": True},
    "faceswap":        {"skip": True},
    "face_restore":    {"skip": True},
    "photo_restore":   {"skip": True},
    "rembg":           {"skip": True},
    "lama_remove":     {"skip": True},
    "upscale":         {"skip": True},
    "wavespeed_upscale": {"skip": True},
    "seedvr2":         {"skip": True},
    "sam3_extract":    {"skip": True},
    "sam3_segment":    {"skip": True},
    "magic_eraser":    {"skip": True},
    "lut":             {"skip": True},   # LUT is a preset name, no LLM
    "none":            {"skip": True},

    # Scene description — default behaviour. Empty overlay.
    "scene":           {},
    "txt2img":         {},
    "img2img":         {},
    "controlnet":      {},
    "style_transfer":  {},
    "video":           {},
    "wan_video":       {},
    "ltx_video":       {},
    "scene_img2img":   {},

    # Inpaint — describe ONLY the masked content, not the whole scene.
    "inpaint": {
        "length_override": "20-60 words",
        "max_tokens": 256,
        "extra_notes": (
            "\n\nINPAINT SCOPE (this is the most important rule for this call):\n"
            "The user's prompt describes ONLY what appears INSIDE the masked region. "
            "Enhance for that region ONLY. Do NOT add a global setting, do NOT "
            "describe the backdrop, do NOT invent lighting for the wider scene — "
            "those stay unchanged from the surrounding unmasked pixels. Your output "
            "must read as 'what goes IN the mask', nothing more. Stay tight."
        ),
    },
    "klein_inpaint":       {"inherit": "inpaint"},
    "klein_auto_inpaint":  {"inherit": "inpaint"},
    "klein_sam3_inpaint":  {"inherit": "inpaint"},

    # Outpaint — extend the canvas beyond what the user already has.
    "outpaint": {
        "length_override": "40-80 words",
        "max_tokens": 320,
        "extra_notes": (
            "\n\nOUTPAINT SCOPE:\n"
            "Describe ONLY what extends BEYOND the existing canvas. The user already "
            "has the original image — do NOT repeat its subject or re-describe what's "
            "inside it. Output should cover the new empty area: continuing landscape, "
            "sky, extended floor, adjacent architecture, peripheral props. Match the "
            "original's lighting direction, colour palette, and time-of-day so the "
            "seam is invisible."
        ),
    },

    # Refinement — quality / detail only. Don't invent new subjects.
    "refine": {
        "length_override": "15-40 words",
        "max_tokens": 192,
        "extra_notes": (
            "\n\nREFINE SCOPE:\n"
            "The image already exists; you are adding QUALITY and DETAIL keywords "
            "on top of it. Do NOT introduce new subjects, objects, or scene "
            "elements. Output only descriptors like 'sharper texture', "
            "'photorealistic skin pores', 'crisp fabric weave', 'ambient occlusion', "
            "'fine hair strands'. Preserve the user's content exactly as written; "
            "append enhancement terms."
        ),
    },
    "klein_refine":   {"inherit": "refine"},
    "detail_boost":   {"inherit": "refine"},
    "hallucinate":    {"inherit": "refine"},

    # Face-only detail — ignore body, clothing, background.
    "face_detail": {
        "length_override": "15-35 words",
        "max_tokens": 160,
        "extra_notes": (
            "\n\nFACE DETAIL SCOPE:\n"
            "Focus exclusively on facial features — eyes (catch-lights, iris detail), "
            "skin (pores, subsurface scattering), expression micro-details, individual "
            "hair strands, lip texture. Do NOT describe clothing, body, pose, or "
            "background. The face IS the subject; everything else stays unchanged."
        ),
    },
    "klein_face_detail": {"inherit": "face_detail"},

    # Virtual try-on — outfit / garment focus only.
    "tryon": {
        "length_override": "25-50 words",
        "max_tokens": 256,
        "extra_notes": (
            "\n\nVIRTUAL TRYON SCOPE:\n"
            "Describe ONLY the outfit or garment — its cut, silhouette, fabric, "
            "texture, drape, fit, material (cotton / silk / leather / wool), "
            "construction details (seams, buttons, zippers), and how it sits on "
            "the body. Do NOT describe the model's face, pose, environment, or "
            "lighting. The garment is the subject; everything else is fixed."
        ),
    },
    "klein_virtual_tryon": {"inherit": "tryon"},

    # Relight — lighting direction / color / mood only.
    # Phrasing lists the VOCABULARY families (not specific keywords) to
    # reduce cargo-culting: live testing showed the LLM was echoing
    # "warm amber" and "moody noir" verbatim every call because the old
    # wording listed them as explicit examples.
    "iclight": {
        "length_override": "15-35 words",
        "max_tokens": 160,
        "extra_notes": (
            "\n\nRELIGHT SCOPE:\n"
            "Describe ONLY the new lighting. Cover four vocabulary dimensions:\n"
            "  1. Direction — where the key light comes from "
            "(left / right / above / behind / below / front / three-quarter).\n"
            "  2. Colour temperature — in Kelvin terms or descriptive "
            "(cool tungsten / neutral daylight / warm candlelight / mixed).\n"
            "  3. Hardness — soft diffused / hard specular / bounced fill / "
            "rim-edge only.\n"
            "  4. Mood / quality — e.g. overcast, noir, studio, golden hour, "
            "stage, underwater, firelight, etc.\n"
            "Use whatever vocabulary MATCHES the user's request. Do NOT default "
            "to any one mood or colour temperature if the user didn't ask for "
            "it. Do NOT describe the subject — it stays unchanged from the "
            "source image."
        ),
    },
    "relight":   {"inherit": "iclight"},

    # Colorize — color / tone keywords, no subject re-description.
    # Same anti-cargo-cult rewrite as iclight: describe the DIMENSIONS,
    # don't hand the LLM ready-made phrases it will echo back.
    "colorize": {
        "length_override": "15-30 words",
        "max_tokens": 128,
        "extra_notes": (
            "\n\nCOLORIZE SCOPE:\n"
            "Output ONLY colour-and-tone keywords — NO subject description. The "
            "source image already contains the subject; your output tells the "
            "model what palette to apply. Cover these dimensions as appropriate "
            "to the user's request:\n"
            "  - dominant hue family (blue-green / warm ochre / magenta-pink / "
            "neutral / high-contrast B&W with colour accent / etc.)\n"
            "  - saturation (desaturated / muted / punchy / vivid)\n"
            "  - tonal emphasis (shadows lifted / crushed blacks / bright highlights)\n"
            "  - film-stock / process reference if the user implied one.\n"
            "Invalid (never do this): 'a wizard in a forest at sunset with warm "
            "tones' — that re-describes the subject."
        ),
    },

    # ControlNet + style-transfer still default to scene (the user
    # describes the output image they want); they're listed above as
    # empty overlays for clarity.
}


def _resolve_method_profile(method):
    """Return the method profile, following `inherit` references.

    Unknown or empty `method` returns {} (= no overlay, scene default).
    """
    if not method:
        return {}
    prof = _METHOD_PROFILES.get(method)
    if prof is None:
        return {}
    # Walk inherit chain (depth-limited to prevent cycles).
    for _ in range(5):
        parent = prof.get("inherit")
        if not parent:
            break
        parent_prof = _METHOD_PROFILES.get(parent)
        if parent_prof is None:
            break
        # Child overlays win over parent. Shallow merge.
        merged = dict(parent_prof)
        for k, v in prof.items():
            if k != "inherit":
                merged[k] = v
        prof = merged
    return prof


# ═══════════════════════════════════════════════════════════════════════════
#  ENHANCEMENT FUNCTION
# ═══════════════════════════════════════════════════════════════════════════

def enhance_prompt(prompt_text, arch_key, kobold_url=None, is_negative=False,
                   comfy_url=None, model_name=None, method="scene"):
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

    # Method overlay: some generation methods (edit instructions, pure
    # utility ops, preset-driven tools) skip enhancement entirely; others
    # (inpaint, outpaint, refine, face_detail, tryon, iclight, colorize)
    # narrow the scope so the LLM doesn't over-describe outside the
    # method's region of interest.
    method_prof = _resolve_method_profile(method)
    if method_prof.get("skip"):
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

    # Method overlay: append the method-specific scope instructions to
    # the profile notes, and optionally override length / style / token
    # budget for narrow-scope methods (face_detail, colorize, inpaint,
    # etc.). Narrow scopes get smaller max_tokens so the LLM doesn't
    # run past the scope; wider scopes keep the arch's larger budget.
    if method_prof:
        profile = dict(profile)  # don't mutate the shared table
        if method_prof.get("extra_notes"):
            profile["notes"] = profile.get("notes", "") + method_prof["extra_notes"]
        if method_prof.get("length_override"):
            profile["length"] = method_prof["length_override"]
        if method_prof.get("style_override"):
            profile["style"] = method_prof["style_override"]
        if method_prof.get("max_tokens"):
            profile["max_tokens"] = method_prof["max_tokens"]

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
    #
    # max_tokens priority (highest wins):
    #   1. llm_prompt_db per-model override (user-curated, rare)
    #   2. profile["max_tokens"] from the arch × method overlay — this
    #      is the canonical budget (e.g. LTX 768, colorize 128)
    #   3. 300 fallback (safe for unknown arches / methods)
    sampling_defaults = {
        "temperature": 0.3,
        "max_tokens":  int(profile.get("max_tokens") or 300),
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
            arch_key=arch_key,  # per-family VRAM + timeout config
            method=method,      # per-method AILab preset selection
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
