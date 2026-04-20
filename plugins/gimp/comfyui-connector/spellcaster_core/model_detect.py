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
    ("chromaxl",  "sdxl"),          # Zavy Chroma XL and similar — SDXL finetunes with "chroma" in name
    ("chroma",    "chroma"),        # Chroma v1/v2 — single CLIPLoader type="chroma"
    ("z_image",   "zit"),           # Z-Image-Turbo (z_image_turbo, z_image_de_turbo)
    ("z-image",   "zit"),
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
    # Z-Image-Turbo AIO checkpoints (gonzalomoZpop, etc.) MUST come before
    # the generic "turbo" → sdxl_turbo rule below or they get misclassified
    # as SDXL Turbo and load with the wrong sampler / steps / native res.
    ("z_image",     "zit"),
    ("z-image",     "zit"),
    ("zit\\",       "zit"),            # ZIT\... folder prefix (Windows separator)
    ("zit/",        "zit"),            # ZIT/... folder prefix (POSIX separator)
    ("gonzalomozpop", "zit"),          # GonzaloMo Zpop AIO merges
    ("zpop",        "zit"),            # other Zpop variants
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
    ("chromaxl",    "sdxl"),           # Zavy Chroma XL and similar — SDXL finetunes with "chroma" in name
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
    ("unet",  lambda ml: "z_image" in ml or "z-image" in ml, "zit"),
    ("unet",  lambda ml: "flux" in ml and "dev" in ml,  "flux1dev"),
    ("unet",  lambda ml: "flux" in ml,                  "flux1dev"),
    ("unet",  lambda ml: "sd3.5" in ml and "turbo" not in ml, "sd3"),
    ("unet",  lambda ml: "sd3" in ml,                   "sd3"),
    ("unet",  lambda ml: "pixart" in ml,                "pixart"),
    ("unet",  lambda ml: "auraflow" in ml or "aura_flow" in ml, "auraflow"),
    ("ckpt",  lambda ml: "kaleidoscope" in ml,           "flux2klein"),
    ("ckpt",  lambda ml: "chromaxl" in ml,               "sdxl"),   # SDXL finetunes with "chroma" in name
    ("ckpt",  lambda ml: "chroma" in ml and "kaleidoscope" not in ml and "xl" not in ml, "chroma"),
    # Z-Image-Turbo AIO checkpoints — must come before any "turbo"/"xl"
    # rules so gonzalomoZpop_v30AIO doesn't get auto-picked as SDXL.
    ("ckpt",  lambda ml: "z_image" in ml or "z-image" in ml or "gonzalomozpop" in ml or "zpop" in ml, "zit"),
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
    "zit":          ["Z-Image-Turbo\\", "ZIT\\", "Z-Image-Turbo/", "ZIT/"],
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
    # --- Z-Image-Turbo first (specific, unambiguous) ---
    ("z_image",    "zit"),
    ("z-image",    "zit"),
    ("zturbo",     "zit"),
    ("z_turbo",    "zit"),
    ("gonzalomozpop", "zit"),
    ("zpop",       "zit"),
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


# LoRAs trained for arch X are shape-compatible with all keys in the same
# bucket. Cross-bucket injection causes the exact shape mismatches seen in
# the ComfyUI log (e.g. Klein 4096-dim LoRA into Flux 1 Dev 3072-dim UNET).
LORA_COMPAT_BUCKETS = {
    "sd15":         ("sd15",),
    "sdxl":         ("sdxl", "illustrious", "pony"),
    "illustrious":  ("sdxl", "illustrious", "pony"),
    "pony":         ("sdxl", "illustrious", "pony"),
    "flux1dev":     ("flux1dev", "flux_kontext"),
    "flux_kontext": ("flux1dev", "flux_kontext"),
    "flux2klein":   ("flux2klein",),
    "chroma":       ("chroma",),
    "zit":          ("zit",),  # Z-Image-Turbo LoRAs are arch-specific
    "wan":          ("wan",),
    "ltx":          ("ltx",),
    "seedvr":       ("seedvr",),
}


def classify_lora_arch(lora_name):
    """Best-effort arch detection for a LoRA filename.

    Checks path prefixes first (most authoritative — the Spellcaster
    convention organises LoRAs by arch folder), then falls back to
    filename keyword hints. Returns None when uncertain so callers
    can pass the LoRA through without blocking a potentially valid use.
    """
    if not isinstance(lora_name, str) or not lora_name:
        return None
    normalized = lora_name.replace("/", "\\")
    for arch_key, prefixes in LORA_ARCH_PREFIXES.items():
        for p in prefixes:
            pn = p.replace("/", "\\")
            if pn and normalized.startswith(pn):
                return arch_key
    ml = lora_name.lower()
    for kw, arch_key in LORA_NAME_ARCH_HINTS:
        if kw in ml:
            return arch_key
    return None


def lora_is_compatible(lora_name, target_arch):
    """Return True if the LoRA is safe to inject into target_arch.

    Unknown LoRAs (no prefix, no name hint) are treated as compatible —
    the alternative silently drops valid custom LoRAs. Known-incompatible
    LoRAs (detected arch is in a different bucket) are rejected.
    """
    if not target_arch:
        return True
    detected = classify_lora_arch(lora_name)
    if detected is None:
        return True
    bucket = LORA_COMPAT_BUCKETS.get(target_arch, (target_arch,))
    return detected in bucket


def classify_ckpt_model(name, file_size=None):
    """Return arch key for a checkpoint model name, or a heuristic default.

    Walks through CKPT_ARCH_RULES in priority order and returns the arch
    key of the first matching rule. When nothing matches AND `file_size`
    (in bytes) is provided, picks a better fallback than the legacy
    hardcoded `sd15`:

      * ≥   9 GB — flux1dev    (Flux full fp16 is ~23 GB, fp8 ~12 GB)
      * ≥ 4.5 GB — sdxl        (SDXL base is ~6.5 GB, fp16 merges ~5 GB)
      * <  4.5 GB — sd15       (classic 2-4 GB territory)

    When `file_size` is None the fallback is still `sd15` (the legacy
    behaviour) — callers that can read the file size on disk should
    pass it in so oddly-named SDXL merges don't get mis-scaffolded.

    Args:
        name: Model filename (str), e.g. "sd_xl_base.safetensors"
        file_size: File size in bytes (int or None). When provided,
                    drives the fallback heuristic for unknown names.

    Returns:
        Architecture key (str), e.g. "sdxl", "sd15", etc.
    """
    ml = name.lower()
    for substring, arch_key in CKPT_ARCH_RULES:
        if substring in ml:
            return arch_key
    # Nothing matched — use file size to guess the family. SDXL is the
    # dominant "weirdly-named custom merge" case today; defaulting to
    # sd15 for a 6-GB file produces bad renders at 512×512 with the
    # wrong samplers.
    if isinstance(file_size, (int, float)) and file_size > 0:
        gb = file_size / (1024.0 ** 3)
        if gb >= 9.0:
            return "flux1dev"
        if gb >= 4.5:
            return "sdxl"
    return "sd15"


def fallback_arch_for_size(file_size):
    """Public helper: given a checkpoint size in bytes, return the best
    guess arch when no filename keyword hints are available. Same
    heuristic as `classify_ckpt_model` but usable in isolation (e.g.
    when an arch arrives via another path but the caller wants to
    sanity-check it)."""
    if not isinstance(file_size, (int, float)) or file_size <= 0:
        return None
    gb = file_size / (1024.0 ** 3)
    if gb >= 9.0:
        return "flux1dev"
    if gb >= 4.5:
        return "sdxl"
    return "sd15"
