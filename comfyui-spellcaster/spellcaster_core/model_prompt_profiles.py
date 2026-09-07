"""Per-model prompt profiles — positive/negative additions + SFW/NSFW modifiers.

A lot of community finetunes + merges work best with SPECIFIC trigger words,
quality tags, or negative sets baked into every prompt. Without them the
output is flat or drifts toward the base arch's default aesthetic.

Examples where the difference is dramatic:

    * JuggernautXL Ragnarok / v9 — photoreal SDXL that needs
      `masterpiece, (photorealistic:1.4), raw photo, 8k uhd, hyperdetailed`
      and a heavy negative (`lowres, cartoon, painting, illustration`).
    * gonzalomoZpop_v30AIO — Z-Image-Turbo pop-art variant. Its NSFW-
      capable style only activates with `zpop style` + specific body-
      description phrasing. Without these the model refuses NSFW or
      produces SFW cartoon output.
    * Flux 1 Dev / Flux 2 Klein / Chroma — natural-language models. Any
      comma-separated tags or `masterpiece, best quality` phrases BURN
      the output. The profile must REMOVE such tokens, not add to them.
    * Illustrious / NoobAI / waiIllustrious — booru-tag models. Quality
      tags are `masterpiece, best quality, absurdres, ultra-detailed`
      (SDXL-style) but the body of the prompt should be comma-separated
      danbooru tags.
    * Pony / SloppyMessyMix — SDXL merges tuned for anime/NSFW with the
      canonical Pony rating tags: `score_9, score_8_up, score_7_up,
      source_anime` (positive) + `score_6, score_5, score_4` (negative).

This module is the ONE SOURCE OF TRUTH. Every app surface that builds
a prompt (Guild avatar gen, Guild txt2img dispatch, GIMP plugin,
Darktable plugin, Resolve bridge) calls `profile_for(filename)` and
merges the result into their prompt assembly.

Public API
----------
    profile_for(model_name, arch=None, nsfw=False) -> dict | None
    apply_profile(prompt, negative, profile) -> (prompt, negative)
    merge_nsfw(profile) -> profile  # returns profile with nsfw_* merged

Profile shape
-------------
    {
        "match":            str | re.Pattern,  # substring or regex
        "arch_family":      str,               # sdxl / flux1dev / illustrious / ...
        "prompt_prefix":    str,               # prepended to the user's prompt
        "prompt_suffix":    str,               # appended to the user's prompt
        "negative_prefix":  str,               # prepended to negative
        "negative_suffix":  str,               # appended to negative
        "nsfw_prompt_additions":  str | None,  # only used when nsfw=True
        "nsfw_negative_additions": str | None,
        "strip_tokens":     list[str],         # tokens to REMOVE from prompt
        "strip_quality":    bool,              # drop generic "masterpiece"/"8k" (Flux/Chroma)
        "recommended": {
            "steps":      int | None,
            "cfg":        float | None,
            "sampler":    str | None,
            "scheduler":  str | None,
            "resolution": tuple[int,int] | None,
        },
        "notes": str,
    }
"""
from __future__ import annotations

import re
from typing import Any, Optional


# ─── Shared modifier snippets ────────────────────────────────────────────

SDXL_PHOTOREAL_POS = (
    "masterpiece, (photorealistic:1.3), raw photo, highly detailed, "
    "hyperdetailed, 8k uhd, sharp focus, natural lighting, film grain"
)
SDXL_PHOTOREAL_NEG = (
    "lowres, cartoon, drawing, painting, illustration, anime, render, "
    "3d model, blurry, jpeg artifacts, ugly, deformed, watermark, text, "
    "plastic skin, airbrushed, over-smoothed"
)

SDXL_ANIME_POS = (
    "masterpiece, best quality, absurdres, highly detailed, vibrant colors"
)
SDXL_ANIME_NEG = (
    "lowres, bad anatomy, bad hands, missing fingers, extra digit, "
    "jpeg artifacts, signature, watermark, blurry"
)

PONY_POS = "score_9, score_8_up, score_7_up, source_anime, "
PONY_NEG = "score_6, score_5, score_4, worst quality, low quality, bad anatomy, "

# NoobAI / Illustrious prefer their own quality tags
ILLUSTRIOUS_POS = (
    "masterpiece, best quality, newest, absurdres, highres, very aesthetic, "
    "sensitive"
)
ILLUSTRIOUS_NEG = (
    "worst quality, low quality, lowres, bad anatomy, bad hands, watermark, "
    "signature, logo, old, early"
)

# SD 1.5 photo — classic tags for realistic finetunes
SD15_PHOTOREAL_POS = (
    "RAW photo, (masterpiece:1.2), (best quality), (high detailed skin:1.2), "
    "8k uhd, DSLR, soft lighting, Fujifilm XT3"
)
SD15_PHOTOREAL_NEG = (
    "lowres, jpeg artifacts, blurry, bad anatomy, bad hands, ugly, deformed, "
    "cartoon, drawing, painting, 3d"
)

# ZIT / Z-Image-Turbo — stylised + pop art variant
ZIT_POS = (
    "vibrant pop art, dynamic composition, bold outlines, saturated colors, "
    "masterpiece, highly detailed"
)
ZIT_NEG = "lowres, blurry, muddy, dull colors, watermark"

# Flux/Chroma — NATURAL LANGUAGE, no tags. These profiles STRIP quality tags.
_FLUX_STRIP_QUALITY = True


# ─── NSFW trigger-word snippets (SFW repo has placeholders; the real
# strings live in nsfw/build_nsfw.py and get patched in for the NSFW
# build). Keeping the keys empty here means SFW installs never emit
# NSFW tokens even if NSFW_MODE accidentally gets set) ─────────────────

# These placeholders get overridden at runtime by nsfw/build_nsfw.py
# which calls nsfw_inject_model_profiles() below.
NSFW_SDXL_PHOTOREAL_POS = ""
NSFW_SDXL_ANIME_POS = ""
NSFW_PONY_POS = ""
NSFW_ILLUSTRIOUS_POS = ""
NSFW_SD15_PHOTOREAL_POS = ""
NSFW_ZIT_POS = ""
NSFW_GENERIC_NEG = ""


# ═══════════════════════════════════════════════════════════════════════
#  Special per-family detectors + applicators — promoted to first-class
#  functions so each can encode quirky per-model logic that the plain
#  prefix/suffix/strip keys cannot express.
#
#  Two models surfaced as prompt-shaping failures in production:
#
#    1. Stock SD 1.5 base (v1-5-pruned-emaonly and re-uploads). The
#       generic `sd15` family fallback is tuned for photoreal finetunes
#       (Juggernaut Reborn / RealisticVision) and force-injects `RAW
#       photo, DSLR, Fujifilm XT3` plus a style-banning negative. That
#       shoves every base-model output into a flat grainy photo look
#       and makes the model refuse to draw when asked for illustration.
#
#    2. GonzaloMo Zpop v3 AIO (Z-Image-Turbo all-in-one merge). The
#       pre-existing profile forced `vibrant pop art, bold outlines,
#       saturated colors` on every prompt even though the AIO is
#       explicitly multi-style. The catch-all `"zpop"` entry below is
#       still correct for pure pop-art Zpop variants, but the AIO
#       specifically needs only the `zpop style` trigger token and
#       nothing else.
#
#  The two detectors below fire on more filenames than just the literal
#  ones — they pick up common renames and look-alike merges. Negative
#  guards keep them from swallowing known finetunes that have their own
#  profiles already.
# ═══════════════════════════════════════════════════════════════════════

# Filename markers that uniquely identify a stock/base SD 1.5 release.
# These tokens only appear in the HuggingFace reference upload and
# direct re-uploads; every community finetune has its own distinctive
# filename and falls into its own profile instead.
_STOCK_SD15_MARKERS = (
    "v1-5-pruned",              # catches v1-5-pruned-emaonly, v1-5-pruned-fp16, …
    "v1_5_pruned",
    "sd-v1-5",                  # Some re-uploads drop the hyphen/underscore
    "sd_v1-5",
    "stable-diffusion-v1-5",    # HF reference repo name
    "stable_diffusion_v1-5",
    "sd15-base",
    "sd-1.5-base",
)


def _is_stock_sd15(filename: str) -> bool:
    """True for base SD 1.5 checkpoints.

    Returns False for every community finetune (Juggernaut Reborn,
    RealisticVision, DreamShaper, AbsoluteReality, Deliberate, etc.)
    because those have their own prompt profiles further up the
    PROFILES list and get matched first.
    """
    n = (filename or "").lower()
    return any(m in n for m in _STOCK_SD15_MARKERS)


def _is_zpop_aio(filename: str) -> bool:
    """True for all-in-one Zpop merges (GonzaloMo Zpop v3 AIO and look-alikes).

    The AIO merges differ from pure pop-art Zpop checkpoints in that
    they can render photo / cinematic / anime / realistic styles on
    demand, so the prompt profile must NOT force the pop-art aesthetic.
    Pure pop-art Zpop variants keep hitting the generic `"zpop"`
    string-matcher entry below this function which injects the bold-
    outlines / saturated-colours bias they're tuned for.
    """
    n = (filename or "").lower()
    if "zpop" not in n:
        return False
    # Explicit "aio" marker anywhere in the filename — most reliable signal.
    if "aio" in n:
        return True
    # GonzaloMo Zpop 3.x is published as v30AIO / v3_0_AIO / v3aio.
    # Version 2.x and earlier are pre-AIO pure pop-art.
    if "gonzalomozpop" in n and any(
        v in n for v in ("v30", "v3_0", "v3.0", "v3aio", "-v3")):
        return True
    return False


def _apply_stock_sd15(prompt: str, negative: str) -> tuple[str, str]:
    """Prompt shaping for stock SD 1.5 base checkpoints.

    Base SD 1.5 is a *general-purpose* model, not a photoreal finetune,
    and under-responds to the prompt at default CFG. The right mix is:

      * Soft, style-neutral quality tags (no camera body / film-stock
        branding) so the user can still request illustrations, cartoons,
        anime, paintings, etc.
      * Anatomy-and-artifact negatives only. NO style bans — the model
        needs to be able to draw cartoons / paintings when asked.
      * Tell the caller to use the recommended settings (see the PROFILE
        entry's `recommended` dict — 30 steps, CFG 8.0, 512x512).

    Returns (prompt, negative) tuple.
    """
    POS = "masterpiece, best quality, highly detailed, sharp focus"
    NEG = (
        "lowres, bad anatomy, bad hands, missing fingers, extra digit, "
        "jpeg artifacts, blurry, watermark, signature, worst quality, "
        "low quality, deformed, disfigured, mutated"
    )
    prompt = (POS + ", " + (prompt or "")).strip(", ").strip()
    negative = (NEG + ", " + (negative or "")).strip(", ").strip()
    return prompt, negative


def _apply_zpop_aio(prompt: str, negative: str) -> tuple[str, str]:
    """Prompt shaping for GonzaloMo Zpop v3 AIO and compatible AIO merges.

    The model REQUIRES the `zpop style` trigger token somewhere in the
    positive prompt to activate its style head — but that's the ONLY
    forced token. Pop-art / bold-outline injection is deliberately
    omitted so the AIO can still produce photo / anime / cinematic
    output when the user asks for it.

    If the user already typed `zpop style` (any casing) we don't
    duplicate the trigger.
    """
    user_prompt = prompt or ""
    trigger = "zpop style"
    if trigger not in user_prompt.lower():
        user_prompt = trigger + ", " + user_prompt
    # Light quality suffix that doesn't bias style. Keep it short —
    # at ZIT's CFG 1.0-2.0, every token carries significant weight.
    user_prompt = (user_prompt + ", detailed, sharp focus").strip(", ").strip()
    NEG = "lowres, blurry, watermark, worst quality, low quality"
    negative = (NEG + ", " + (negative or "")).strip(", ").strip()
    return user_prompt, negative


# ─── Per-model profiles. Matched by substring against the filename
# (case-insensitive). First match wins, so list MORE specific names
# first. Generic arch-family fallbacks live at the tail.
#
# `match` may be a substring, a compiled regex, OR a callable(str)->bool
# — see profile_for() for dispatch order. Profiles can also supply an
# `applicator` callable that fully owns prompt shaping, bypassing the
# prefix/suffix/strip engine. ─────────────────────────────────────────

PROFILES: list[dict[str, Any]] = [
    # ── Stock SD 1.5 base (callable detector — picks up rename variants) ──
    {
        "match": _is_stock_sd15,
        "arch_family": "sd15",
        "applicator": _apply_stock_sd15,
        # Kept for introspection + NSFW-build compatibility; the
        # applicator owns the actual prompt shaping.
        "prompt_prefix": "", "prompt_suffix": "",
        "negative_prefix": "", "negative_suffix": "",
        "nsfw_prompt_additions": "", "nsfw_negative_additions": "",
        "strip_tokens": [], "strip_quality": False,
        "recommended": {"steps": 30, "cfg": 8.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (512, 512)},
        "notes": "Stock SD 1.5 base (v1-5-pruned / v1-5-pruned-emaonly / "
                 "stable-diffusion-v1-5 and HF re-uploads). Style-neutral "
                 "quality tags and anatomy-only negatives; base SD 1.5 is "
                 "not a photoreal finetune and must stay able to draw "
                 "illustrations, cartoons, paintings on request. Higher "
                 "CFG (8.0) because the base model under-responds. 512x512 "
                 "is the training resolution.",
    },

    # ── GonzaloMo Zpop v3 AIO + look-alikes (callable detector) ─────────
    {
        "match": _is_zpop_aio,
        "arch_family": "zit",
        "applicator": _apply_zpop_aio,
        "prompt_prefix": "", "prompt_suffix": "",
        "negative_prefix": "", "negative_suffix": "",
        "nsfw_prompt_additions": "", "nsfw_negative_additions": "",
        "strip_tokens": [], "strip_quality": False,
        "recommended": {"steps": 8, "cfg": 2.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "GonzaloMo Zpop v3 AIO + compatible all-in-one Zpop "
                 "merges. Forces ONLY the `zpop style` trigger (required "
                 "by the model's style head) so the AIO can still render "
                 "photo / cinematic / anime output when the user asks for "
                 "it. Pure pop-art Zpop variants — which DO want the bold-"
                 "outline / saturated-colour forcing — fall through to "
                 "the `\"zpop\"` catch-all entry further down.",
    },

    # ── SDXL photoreal finetunes ────────────────────────────────────
    # ── SDXL photoreal finetunes ────────────────────────────────────
    {
        "match": "juggernautxl",
        "arch_family": "sdxl",
        "prompt_prefix": SDXL_PHOTOREAL_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": SDXL_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 30, "cfg": 5.0, "sampler": "dpmpp_2m_sde",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "JuggernautXL — photoreal SDXL. Needs strong quality tags + heavy negative.",
    },
    {
        "match": "cyberrealistic",
        "arch_family": "sdxl",
        "prompt_prefix": SDXL_PHOTOREAL_POS + ", cinematic, ",
        "prompt_suffix": "",
        "negative_prefix": SDXL_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 30, "cfg": 5.0, "sampler": "dpmpp_2m_sde",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "CyberRealistic Pony — SDXL photoreal merge, accepts Pony scores too.",
    },
    {
        "match": "jibmix",
        "arch_family": "sdxl",
        "prompt_prefix": SDXL_PHOTOREAL_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": SDXL_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 30, "cfg": 5.0, "sampler": "dpmpp_2m_sde",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "JibMixRealisticXL — photoreal SDXL.",
    },
    {
        "match": "zavychroma",
        "arch_family": "sdxl",
        "prompt_prefix": SDXL_PHOTOREAL_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": SDXL_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 30, "cfg": 5.0, "sampler": "dpmpp_2m_sde",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "ZavyChromaXL — colour-rich SDXL.",
    },
    {
        "match": "albedobase",
        "arch_family": "sdxl",
        "prompt_prefix": SDXL_PHOTOREAL_POS.replace("(photorealistic:1.3), ", "") + ", ",
        "prompt_suffix": "",
        "negative_prefix": SDXL_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 30, "cfg": 6.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "AlbedoBaseXL — versatile SDXL base.",
    },
    # ── SDXL stylised ───────────────────────────────────────────────
    {
        "match": "moderndisney",
        "arch_family": "sdxl",
        "prompt_prefix": "disney style, 3d render, pixar style, " + SDXL_ANIME_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": "photorealistic, photo, realistic, " + SDXL_ANIME_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_ANIME_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 28, "cfg": 6.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "ModernDisneyXL — Pixar/Disney stylised SDXL.",
    },
    {
        "match": "novacartoon",
        "arch_family": "sdxl",
        "prompt_prefix": "cartoon style, flat colors, bold outlines, " + SDXL_ANIME_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": "photorealistic, photo, realistic, " + SDXL_ANIME_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_ANIME_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 28, "cfg": 6.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "novaCartoonXL — western cartoon SDXL.",
    },
    {
        "match": "novaanime",
        "arch_family": "sdxl",
        "prompt_prefix": "anime style, manga style, " + SDXL_ANIME_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": "photorealistic, 3d, " + SDXL_ANIME_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_ANIME_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 28, "cfg": 6.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "novaAnimeXL — anime-tuned SDXL.",
    },
    # ── Illustrious / NoobAI / Pony ─────────────────────────────────
    {
        "match": "noobai",
        "arch_family": "illustrious",
        "prompt_prefix": ILLUSTRIOUS_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": ILLUSTRIOUS_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_ILLUSTRIOUS_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 28, "cfg": 5.5, "sampler": "euler_ancestral",
                         "scheduler": "normal", "resolution": (1024, 1024)},
        "notes": "NoobAI-XL — Illustrious-tuned anime. Uses Illustrious quality tags.",
    },
    {
        "match": "waiillustrious",
        "arch_family": "illustrious",
        "prompt_prefix": ILLUSTRIOUS_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": ILLUSTRIOUS_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_ILLUSTRIOUS_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 28, "cfg": 5.5, "sampler": "euler_ancestral",
                         "scheduler": "normal", "resolution": (1024, 1024)},
        "notes": "waiIllustrious — Illustrious-tuned anime.",
    },
    {
        "match": "sloppymessy",
        "arch_family": "illustrious",
        "prompt_prefix": PONY_POS + ILLUSTRIOUS_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": PONY_NEG + ILLUSTRIOUS_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_PONY_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 28, "cfg": 6.0, "sampler": "euler_ancestral",
                         "scheduler": "normal", "resolution": (1024, 1024)},
        "notes": "SloppyMessyMix — Pony + Illustrious merge. Accepts both tag sets.",
    },
    {
        "match": "ponyrealism",
        "arch_family": "pony",
        "prompt_prefix": PONY_POS,
        "prompt_suffix": ", (photorealistic:1.2), highly detailed",
        "negative_prefix": PONY_NEG + "cartoon, anime, drawing, painting, ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_PONY_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 30, "cfg": 7.0, "sampler": "dpmpp_2m_sde",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "Pony realism finetune — needs Pony score tags + photo quality.",
    },
    # ── ZIT / Z-Image-Turbo — the gonzolomo branch ─────────────────
    {
        "match": "gonzalomozpop",
        "arch_family": "zit",
        "prompt_prefix": "zpop style, " + ZIT_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": ZIT_NEG + ", photorealistic, ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_ZIT_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 8, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "gonzalomoZpop — Z-Image-Turbo pop-art. NSFW only fires when "
                 "`zpop style` + explicit body-description phrasing are both present. "
                 "Keep CFG at 1.0 — the model is distilled (turbo).",
    },
    {
        "match": "zpop",  # catch-all for other zpop-family checkpoints
        "arch_family": "zit",
        "prompt_prefix": "zpop style, " + ZIT_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": ZIT_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_ZIT_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 8, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "ZPop family — Z-Image-Turbo pop-art.",
    },
    # ── SD 1.5 photo ────────────────────────────────────────────────
    {
        "match": "juggernaut_reborn",
        "arch_family": "sd15",
        "prompt_prefix": SD15_PHOTOREAL_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": SD15_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SD15_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 25, "cfg": 7.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (768, 768)},
        "notes": "Juggernaut Reborn — SD1.5 photoreal flagship.",
    },
    {
        "match": "realisticvision",
        "arch_family": "sd15",
        "prompt_prefix": SD15_PHOTOREAL_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": SD15_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SD15_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 25, "cfg": 7.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (768, 768)},
        "notes": "RealisticVision — SD1.5 photoreal flagship.",
    },
    # ── Flux 1 Dev / Kontext — NATURAL LANGUAGE, no tags ────────────
    {
        "match": "flux1-dev",
        "arch_family": "flux1dev",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd",
                         "score_9", "score_8", "score_7", "absurdres",
                         "highres"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 28, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Flux 1 Dev — natural language only. Quality tags burn.",
    },
    {
        "match": "flux1_dev",
        "arch_family": "flux1dev",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd",
                         "score_9", "score_8", "score_7", "absurdres",
                         "highres"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 28, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Flux 1 Dev (underscore spelling) — natural language only.",
    },
    {
        # Space variant: ComfyUI filenames like "FLUX1 Dev fp8.safetensors"
        "match": "flux1 dev",
        "arch_family": "flux1dev",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd",
                         "score_9", "score_8", "score_7", "absurdres",
                         "highres"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 28, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Flux 1 Dev (space spelling) — natural language only.",
    },
    {
        # Space variant with "flux dev" (some builds drop the 1)
        "match": "flux dev",
        "arch_family": "flux1dev",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd",
                         "score_9", "score_8", "score_7", "absurdres",
                         "highres"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 28, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Flux Dev (no version number) — natural language only.",
    },
    {
        "match": "flux-2-klein",
        "arch_family": "flux2klein",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd",
                         "score_9", "score_8", "score_7", "absurdres",
                         "highres"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 8, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Flux 2 Klein — natural language. 4-8 steps, CFG 1.0.",
    },
    {
        "match": "flux2klein",
        "arch_family": "flux2klein",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 8, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Flux 2 Klein — natural language.",
    },
    {
        "match": "hyfu",
        "arch_family": "flux1dev",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 8, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "HyFU — 8-step Flux Dev distillation.",
    },
    {
        "match": "chroma",
        "arch_family": "chroma",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 28, "cfg": 4.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Chroma — natural language Flux-family variant.",
    },

    # ── Generic arch fallbacks ──────────────────────────────────────
    # Matched ONLY when no specific model above hits. These rely on the
    # arch argument to profile_for(), not the filename.
]


# Arch-family fallbacks. These fire only when profile_for() finds no
# filename match; arch is supplied explicitly by the caller.
ARCH_FALLBACKS: dict[str, dict[str, Any]] = {
    "sdxl": {
        "arch_family": "sdxl",
        "prompt_prefix": SDXL_PHOTOREAL_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": SDXL_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SDXL_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 30, "cfg": 5.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (1024, 1024)},
        "notes": "Generic SDXL fallback (photoreal-leaning).",
    },
    "illustrious": {
        "arch_family": "illustrious",
        "prompt_prefix": ILLUSTRIOUS_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": ILLUSTRIOUS_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_ILLUSTRIOUS_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 28, "cfg": 5.5, "sampler": "euler_ancestral",
                         "scheduler": "normal", "resolution": (1024, 1024)},
        "notes": "Generic Illustrious fallback.",
    },
    "pony": {
        "arch_family": "pony",
        "prompt_prefix": PONY_POS,
        "prompt_suffix": "",
        "negative_prefix": PONY_NEG,
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_PONY_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 28, "cfg": 6.0, "sampler": "euler_ancestral",
                         "scheduler": "normal", "resolution": (1024, 1024)},
        "notes": "Generic Pony fallback.",
    },
    "sd15": {
        "arch_family": "sd15",
        "prompt_prefix": SD15_PHOTOREAL_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": SD15_PHOTOREAL_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_SD15_PHOTOREAL_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 25, "cfg": 7.0, "sampler": "dpmpp_2m",
                         "scheduler": "karras", "resolution": (768, 768)},
        "notes": "Generic SD 1.5 fallback.",
    },
    "zit": {
        "arch_family": "zit",
        "prompt_prefix": ZIT_POS + ", ",
        "prompt_suffix": "",
        "negative_prefix": ZIT_NEG + ", ",
        "negative_suffix": "",
        "nsfw_prompt_additions": NSFW_ZIT_POS,
        "nsfw_negative_additions": NSFW_GENERIC_NEG,
        "strip_tokens": [],
        "strip_quality": False,
        "recommended": {"steps": 8, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Generic Z-Image-Turbo fallback.",
    },
    "flux1dev": {
        "arch_family": "flux1dev",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 28, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Generic Flux 1 Dev fallback — natural language only.",
    },
    "flux2klein": {
        "arch_family": "flux2klein",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 8, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Generic Flux 2 Klein fallback.",
    },
    "chroma": {
        "arch_family": "chroma",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k", "uhd"],
        "strip_quality": _FLUX_STRIP_QUALITY,
        "recommended": {"steps": 28, "cfg": 4.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Generic Chroma fallback.",
    },
    "flux_kontext": {
        "arch_family": "flux_kontext",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prefix": "",
        "negative_suffix": "",
        "nsfw_prompt_additions": "",
        "nsfw_negative_additions": "",
        "strip_tokens": ["masterpiece", "best quality", "8k"],
        "strip_quality": True,
        "recommended": {"steps": 28, "cfg": 1.0, "sampler": "euler",
                         "scheduler": "simple", "resolution": (1024, 1024)},
        "notes": "Flux Kontext — edit-instruction model. Use imperatives ('change X to Y').",
    },
}


def profile_for(model_name: str,
                arch: Optional[str] = None,
                nsfw: bool = False) -> Optional[dict]:
    """Return the profile for a model filename, or None if no rule matches.

    Flow:
        1. Scan PROFILES for a filename-substring match (case-insensitive).
        2. If none matches, use ARCH_FALLBACKS[arch] if arch is provided.
        3. Return None if neither applies.

    When `nsfw=True`, the `nsfw_prompt_additions` + `nsfw_negative_additions`
    are folded into the main prompt_prefix / negative_prefix so callers get
    a single merged string. SFW callers pass nsfw=False and never see NSFW
    tokens even if the profile defines them.
    """
    if not model_name:
        name_l = ""
    else:
        name_l = model_name.lower().replace("\\", "/").rsplit("/", 1)[-1]

    found: Optional[dict] = None
    for prof in PROFILES:
        m = prof["match"]
        # Callable detector wins first — tested before the regex/string
        # branches so a function can subsume/extend substring matching.
        if callable(m) and not isinstance(m, (str, re.Pattern)):
            try:
                if m(name_l):
                    found = prof
                    break
            except Exception:
                # A buggy detector must not crash prompt resolution;
                # skip and fall through to the next candidate.
                continue
        elif isinstance(m, re.Pattern):
            if m.search(name_l):
                found = prof
                break
        elif isinstance(m, str) and m.lower() in name_l:
            found = prof
            break

    if not found and arch and arch in ARCH_FALLBACKS:
        found = ARCH_FALLBACKS[arch]

    if not found:
        return None

    # Clone and merge NSFW additions when requested.
    p = dict(found)
    if nsfw:
        extra_pos = (p.get("nsfw_prompt_additions") or "").strip()
        extra_neg = (p.get("nsfw_negative_additions") or "").strip()
        if extra_pos:
            p["prompt_prefix"] = (p.get("prompt_prefix", "") + extra_pos + ", ")
        if extra_neg:
            p["negative_prefix"] = (p.get("negative_prefix", "") + extra_neg + ", ")
    return p


def apply_profile(prompt: str, negative: str,
                  profile: Optional[dict]) -> tuple[str, str]:
    """Apply a profile's prefix/suffix/strip rules to a (prompt, negative) pair.

    Returns the modified (prompt, negative) tuple. If profile is None, the
    inputs are returned unchanged so callers can unconditionally call this.

    Precedence:
      1. If `profile["applicator"]` is a callable, delegate entirely —
         the applicator fully owns prompt shaping for that model. Used
         for models whose quirks can't be expressed as plain prefix/
         suffix/strip rules (see _apply_stock_sd15 + _apply_zpop_aio).
      2. Otherwise fall back to the prefix/suffix/strip engine.
    """
    prompt = prompt or ""
    negative = negative or ""
    if not profile:
        return prompt, negative

    # Callable applicator path — profile is entirely in charge.
    applicator = profile.get("applicator")
    if callable(applicator):
        try:
            return applicator(prompt, negative)
        except Exception:
            # A broken applicator must not crash the workflow. Fall
            # through to the default engine so at least the prefix/
            # suffix keys still apply.
            pass

    # Strip rules come first so we don't double-add a token that was
    # already cleaned out by the user.
    strip_tokens = profile.get("strip_tokens") or []
    if profile.get("strip_quality"):
        # Common quality-tag spam that kills Flux / Chroma natural-language
        # generation. We also strip common comma-separated residues like
        # "(masterpiece:1.2)" and booru score tags.
        strip_tokens = list(strip_tokens) + [
            "masterpiece", "best quality", "8k", "uhd", "hdr",
            "absurdres", "highres", "score_9", "score_8_up", "score_7_up",
            "(masterpiece", "(best quality",
        ]
    for tok in strip_tokens:
        # Case-insensitive remove, boundaried roughly on comma/space.
        prompt = re.sub(r"(?i)\b" + re.escape(tok) + r"\b[,\s]*", "", prompt)

    prefix = profile.get("prompt_prefix", "") or ""
    suffix = profile.get("prompt_suffix", "") or ""
    prompt = (prefix + prompt + suffix).strip(", ").strip()

    neg_prefix = profile.get("negative_prefix", "") or ""
    neg_suffix = profile.get("negative_suffix", "") or ""
    negative = (neg_prefix + negative + neg_suffix).strip(", ").strip()

    return prompt, negative


def nsfw_inject_model_profiles(overrides: dict) -> None:
    """Called by nsfw/build_nsfw.py to swap the NSFW string constants in.

    Shape:
        {
            "NSFW_SDXL_PHOTOREAL_POS": "...",
            "NSFW_PONY_POS": "...",
            ...
        }
    """
    g = globals()
    for k, v in overrides.items():
        if k.startswith("NSFW_"):
            g[k] = v
    # Re-walk PROFILES + ARCH_FALLBACKS to pick up the new constants since
    # they were captured by value in the dict literal.
    for prof in PROFILES:
        _refresh_nsfw_keys(prof)
    for prof in ARCH_FALLBACKS.values():
        _refresh_nsfw_keys(prof)


def _refresh_nsfw_keys(prof: dict) -> None:
    """Re-read the NSFW_* constants into this profile. Called after
    nsfw_inject_model_profiles updates the module globals."""
    arch = prof.get("arch_family", "")
    # Map arch -> the NSFW constant name pair
    table = {
        "sdxl":        ("NSFW_SDXL_PHOTOREAL_POS", "NSFW_GENERIC_NEG"),
        "illustrious": ("NSFW_ILLUSTRIOUS_POS", "NSFW_GENERIC_NEG"),
        "pony":        ("NSFW_PONY_POS", "NSFW_GENERIC_NEG"),
        "sd15":        ("NSFW_SD15_PHOTOREAL_POS", "NSFW_GENERIC_NEG"),
        "zit":         ("NSFW_ZIT_POS", "NSFW_GENERIC_NEG"),
    }
    pair = table.get(arch)
    if not pair:
        return
    g = globals()
    prof["nsfw_prompt_additions"] = g.get(pair[0], "")
    prof["nsfw_negative_additions"] = g.get(pair[1], "")
