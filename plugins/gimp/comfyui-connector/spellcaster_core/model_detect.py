"""Model detection — canonical source for model-name → architecture mapping.

This module contains the SINGLE SOURCE OF TRUTH for mapping model filenames
to architecture keys. It is shared by all parts of Spellcaster:
  - Guild server (model detection in ComfyUI)
  - GIMP plugin (model selection UI)
  - Workflow builders (arch-specific node construction)

Before: these lists were scattered across guild_common.py and duplicated
in the GIMP plugin. Now, they live here.

USAGE:
    from spellcaster_core.model_detect import (
        classify_unet_model, classify_ckpt_model,
        UNET_ARCH_RULES, CKPT_ARCH_RULES,
        FAMILY_MODEL_KEYWORDS, LORA_NAME_ARCH_HINTS,
    )

    arch = classify_unet_model("flux1-dev-q6.gguf")  # "flux1dev"
    arch = classify_ckpt_model("sd_xl_base.safetensors")  # "sdxl"
"""


# ═══════════════════════════════════════════════════════════════════════════
#  ARCHITECTURE / MODEL-NAME → ARCH-KEY MAPPING
# ═══════════════════════════════════════════════════════════════════════════
#
# Single source of truth for "what substring in a model name implies
# which architecture key".  Referenced by:
#   - _fetch_comfyui_models()   (detect all models)
#   - _detect_best_model()      (pick best model for avatar gen)
#   - _build_lora_registry()    (infer LoRA architecture)
#   - FAMILY_MODEL_KEYWORDS    (wizard gating)
#
# Order within each list matters for priority: first match wins.

# UNET model-name keywords → arch key
UNET_ARCH_RULES = [
    # (substring, arch_key)  — order = priority, first match wins
    ("klein",     "flux2klein"),
    ("kontext",   "flux_kontext"),
    ("kaleidoscope", "flux2klein"),  # chroma2_kaleidoscope is a Klein 4B finetune
    ("chroma",    "chroma"),        # Chroma v1/v2 — single CLIPLoader type="chroma"
    ("flux",      "flux1dev"),
    ("wan",       "wan"),
    ("ltx",       "ltx"),
    ("seedvr",    "seedvr"),
    ("pixart",    "pixart"),
    ("auraflow",  "auraflow"),
    ("aura_flow", "auraflow"),
    ("hunyuan_dit", "hunyuan_dit"),
    ("hunyuandit",  "hunyuan_dit"),
    ("sd3.5_large_turbo", "sd3_turbo"),
    ("sd3_turbo",   "sd3_turbo"),
    ("sd3.5",       "sd3"),
    ("sd3_",        "sd3"),
    ("sd3medium",   "sd3"),
]

# Checkpoint model-name keywords → arch key   (order = priority)
CKPT_ARCH_RULES = [
    ("playground",  "playground"),
    ("sdxl_turbo",  "sdxl_turbo"),
    ("sdxl_lightning", "sdxl_turbo"),
    ("lcm",         "sdxl_turbo"),
    ("turbo",       "sdxl_turbo"),     # generic turbo → sdxl_turbo (unless caught above)
    ("kolors",      "kolors"),
    ("sd3.5_large_turbo", "sd3_turbo"),
    ("sd3_turbo",   "sd3_turbo"),
    ("sd3.5",       "sd3"),
    ("sd3_",        "sd3"),
    ("sd3medium",   "sd3"),
    ("hunyuan_dit", "hunyuan_dit"),
    ("hunyuandit",  "hunyuan_dit"),
    ("kaleidoscope", "flux2klein"),     # chroma2_kaleidoscope is a Klein 4B finetune
    ("chroma",      "chroma"),         # Chroma v1/v2 — single CLIPLoader type="chroma"
    ("sdxl",        "sdxl"),
    ("xl",          "sdxl"),
    ("illu",        "illustrious"),
    ("pony",        "pony"),
    ("flux",        "flux1dev"),
    # fallthrough → "sd15"
]

# ── Best-model priority (highest first) ──
# Each entry: (match_pool, substring_test, arch_key)
#   match_pool: "unet" or "ckpt"
BEST_MODEL_PRIORITY = [
    ("unet",  lambda ml: "klein" in ml and "9b" in ml,  "flux2klein"),
    ("unet",  lambda ml: "klein" in ml and "4b" in ml,  "flux2klein"),
    ("unet",  lambda ml: "kaleidoscope" in ml,           "flux2klein"),
    ("unet",  lambda ml: "chroma" in ml and "kaleidoscope" not in ml, "chroma"),
    ("unet",  lambda ml: "flux" in ml and "dev" in ml,  "flux1dev"),
    ("unet",  lambda ml: "flux" in ml,                  "flux1dev"),
    ("unet",  lambda ml: "sd3.5" in ml and "turbo" not in ml, "sd3"),
    ("unet",  lambda ml: "sd3" in ml,                   "sd3"),
    ("unet",  lambda ml: "pixart" in ml,                "pixart"),
    ("unet",  lambda ml: "auraflow" in ml or "aura_flow" in ml, "auraflow"),
    ("ckpt",  lambda ml: "kaleidoscope" in ml,           "flux2klein"),
    ("ckpt",  lambda ml: "chroma" in ml and "kaleidoscope" not in ml, "chroma"),
    ("ckpt",  lambda ml: "sd3.5" in ml and "turbo" not in ml, "sd3"),
    ("ckpt",  lambda ml: "playground" in ml,            "playground"),
    ("ckpt",  lambda ml: "kolors" in ml,                "kolors"),
    ("ckpt",  lambda ml: "illu" in ml,                  "illustrious"),
    ("ckpt",  lambda ml: "xl" in ml and "turbo" not in ml, "sdxl"),
    ("ckpt",  lambda ml: "xl" in ml,                    "sdxl"),
]

# ── Model-family → keyword map for wizard-gating ──
# If at least one installed model name contains any of these substrings,
# the corresponding model_wizard family is shown.
FAMILY_MODEL_KEYWORDS = {
    "ltx2":        ["ltx"],
    "seedvr2":     ["seedvr"],
    "wan":         ["wan"],
    "video_tools": ["wan", "ltx", "seedvr", "svd", "animate", "rife",
                    "video_upscale", "reactor"],
}

# ── LoRA prefix → arch mapping ──
# Maps architecture keys to the subfolder prefixes used in ComfyUI's
# LoRA directory layout.  Cross-platform: callers check both / and \.
LORA_ARCH_PREFIXES = {
    "sd15":         ["SD15\\", "v1.5\\", "sd1.5\\", "StableDiffusion15\\", "SD15/"],
    "sdxl":         ["SDXL\\", "Illustrious\\", "Illustrious-Pony\\", "Pony\\", "SDXL/", "Pony/"],
    "illustrious":  ["Illustrious\\", "Illustrious-Pony\\", "Illustrious/"],
    "pony":         ["Pony\\", "Illustrious-Pony\\", "Pony/"],
    "flux2klein":   ["Flux-2-Klein\\", "Flux2/"],
    "flux1dev":     ["Flux-1-Dev\\", "Flux\\", "Flux/"],
    "flux_kontext": ["Flux-1-Dev\\", "Flux/"],
    "ltx":          ["ltxv\\", "LTX\\", "ltxv/", "LTX/"],
    "wan":          ["Wan\\", "WAN\\", "Wan-2.2-I2V\\", "Wan/", "WAN/"],
    "seedvr":       ["SeedVR\\", "seedvr\\", "SeedVR/", "seedvr/"],
}

# LoRA name keyword → arch (fallback when prefix matching fails).
# Order matters: first match wins. More-specific / less-ambiguous keywords
# come FIRST so short generic suffixes like "xl" don't swallow names that
# contain them incidentally (e.g. "wan_mixl" would match "xl" before "wan"
# if "xl" came first). Video-model hints are also up front so we don't
# mis-classify video LoRAs as image ones.
#
# DO NOT add "realism"/"detail"/"aesthetic" → sdxl defaults. They fire on
# video LoRAs too (e.g. "Wan_realism_enhance") and pollute SDXL wizards
# with Wan LoRAs, which is the exact bug we're guarding against.
LORA_NAME_ARCH_HINTS = [
    # --- Video models first (unambiguous keywords) ---
    ("ltxv",       "ltx"),
    ("ltx-video",  "ltx"),
    ("ltx_video",  "ltx"),
    ("ltx",        "ltx"),
    ("wan2.2",     "wan"),
    ("wan-2.2",    "wan"),
    ("wan_2.2",    "wan"),
    ("wan2",       "wan"),
    ("wan_i2v",    "wan"),
    ("wani2v",     "wan"),
    ("wan_t2v",    "wan"),
    ("wan-",       "wan"),
    ("wan_",       "wan"),
    ("seedvr",     "seedvr"),
    ("cogvideo",   "cogvideo"),
    ("hunyuan",    "hunyuan_dit"),
    # --- Image models ---
    ("flux2klein", "flux2klein"),
    ("flux-2-klein", "flux2klein"),
    ("flux_2_klein", "flux2klein"),
    ("klein",      "flux2klein"),
    ("flux",       "flux1dev"),
    ("flx",        "flux1dev"),
    ("illustrious", "illustrious"),
    ("illu",       "illustrious"),
    ("ponv6",      "pony"),
    ("pony",       "pony"),
    ("sdxl",       "sdxl"),
    ("sd15",       "sd15"),
    ("sd1.5",      "sd15"),
    ("v1.5",       "sd15"),
    ("v15",        "sd15"),
    ("sd35",       "sd3"),
    ("sd3",        "sd3"),
    ("pixart",     "pixart"),
    ("auraflow",   "auraflow"),
    ("kolors",     "kolors"),
    ("playground", "playground"),
    # --- 2-char suffix hint (last, weakest) — only matches if nothing above did ---
    ("xl",         "sdxl"),
]


# ═══════════════════════════════════════════════════════════════════════════
#  CLASSIFICATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def classify_unet_model(name):
    """Return arch key for a UNET model name, or 'unknown'.

    Walks through UNET_ARCH_RULES in priority order and returns the arch key
    of the first matching rule. Falls back to 'unknown' if no match.

    Args:
        name: Model filename (str), e.g. "flux1-dev-q6.gguf"

    Returns:
        Architecture key (str), e.g. "flux1dev" or "unknown"
    """
    ml = name.lower()
    for substring, arch_key in UNET_ARCH_RULES:
        if substring in ml:
            return arch_key
    return "unknown"


def classify_ckpt_model(name):
    """Return arch key for a checkpoint model name, or 'sd15' (default).

    Walks through CKPT_ARCH_RULES in priority order and returns the arch key
    of the first matching rule. Falls back to 'sd15' (the most common and
    safest default) if no match.

    Args:
        name: Model filename (str), e.g. "sd_xl_base.safetensors"

    Returns:
        Architecture key (str), e.g. "sdxl", "sd15", etc.
    """
    ml = name.lower()
    for substring, arch_key in CKPT_ARCH_RULES:
        if substring in ml:
            return arch_key
    return "sd15"
