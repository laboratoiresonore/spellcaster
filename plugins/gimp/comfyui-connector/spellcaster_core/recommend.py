"""Model Recommender — suggest the best model for a given task.

Maps user intent ("anime portrait", "photorealistic landscape", "video of
a sunset") to the best architecture and model on the connected ComfyUI server.

Usage:
    from spellcaster_core.recommend import recommend

    rec = recommend("anime girl in a garden", server="http://192.168.x.x:8188")
    print(rec)
    # {"arch": "illustrious", "model": "Illustrious\\ilustreal.safetensors",
    #  "reason": "anime/illustration content", "settings": {...}}
"""

import json
import re
import urllib.request

try:
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .architectures import get_arch, ARCHITECTURES
except ImportError:
    from spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model
    from spellcaster_core.architectures import get_arch, ARCHITECTURES


# ═══════════════════════════════════════════════════════════════════════
#  Intent detection — what does the user want to create?
# ═══════════════════════════════════════════════════════════════════════

INTENT_PATTERNS = [
    # (regex_pattern, intent_key, description)
    # Video intents first — "animate this photo" should be video, not photo
    (r"\b(video|animate|motion|breathing|sway|movement|walking|i2v)\b", "video",
     "video/animation"),
    (r"\b(t2v|text.to.video|timelapse|cinematic motion)\b", "video_t2v",
     "text-to-video generation"),
    (r"\b(anime|manga|waifu|1girl|1boy|chibi|kawaii|danbooru|booru)\b", "anime",
     "anime/illustration content"),
    (r"\b(cartoon|disney|pixar|3d render|toon|claymation)\b", "cartoon",
     "cartoon/3D style"),
    (r"\b(photograph|photorealistic|dslr|portrait photo|headshot|realistic photo)\b", "photorealistic",
     "photorealistic content"),
    (r"\b(t2v|text.to.video|timelapse|cinematic motion)\b", "video_t2v",
     "text-to-video generation"),
    (r"\b(upscale|enhance|sharpen|super.?res|4k|8k|hd)\b", "upscale",
     "image upscaling/enhancement"),
    (r"\b(face.?swap|identity|pulid|faceid)\b", "face",
     "face/identity work"),
    (r"\b(inpaint|remove|erase|fix|repair|restore)\b", "edit",
     "image editing/repair"),
    (r"\b(fast|quick|turbo|instant|preview)\b", "fast",
     "fast generation (turbo mode)"),
    (r"\b(nsfw|nude|naked|explicit|adult|erotic|sexy)\b", "nsfw",
     "NSFW content"),
]

# Intent → preferred architecture priority (first available wins)
INTENT_TO_ARCH = {
    "anime":          ["illustrious", "pony", "sdxl", "sd15"],
    "cartoon":        ["sdxl", "sd15"],
    "photorealistic": ["flux2klein", "flux1dev", "sdxl", "sd15"],
    "video":          ["wan", "ltx"],
    "video_t2v":      ["ltx", "wan"],
    "upscale":        ["sdxl", "sd15"],  # doesn't need a gen model
    "face":           ["flux2klein", "flux1dev", "sdxl"],
    "edit":           ["flux2klein", "sdxl", "sd15"],
    "fast":           ["zit", "flux2klein", "sd15"],
    "nsfw":           ["flux2klein", "flux1dev", "illustrious", "sdxl"],
    "general":        ["flux2klein", "sdxl", "flux1dev", "illustrious", "sd15"],
}


def detect_intent(prompt):
    """Analyze a prompt to determine user intent.

    Returns list of (intent_key, description) sorted by relevance.
    """
    prompt_lower = prompt.lower()
    matches = []
    for pattern, intent, desc in INTENT_PATTERNS:
        if re.search(pattern, prompt_lower):
            matches.append((intent, desc))
    if not matches:
        matches.append(("general", "general image generation"))
    return matches


def _get_server_models(server):
    """Get all models from a ComfyUI server."""
    models = {}  # arch_key -> [model_names]

    for node, field, classify_fn in [
        ("UnetLoaderGGUF", "unet_name", classify_unet_model),
        ("UNETLoader", "unet_name", classify_unet_model),
        ("CheckpointLoaderSimple", "ckpt_name", classify_ckpt_model),
    ]:
        try:
            r = urllib.request.urlopen(f"{server}/object_info/{node}", timeout=5)
            d = json.loads(r.read())
            spec = d[node]["input"]["required"][field]
            opts = spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])
            skip = ("vae", "embeddings", "audio", "clip_", "t5xxl", "umt5",
                    "gemma", "qwen", "mistral", "llava", "connector")
            for m in opts:
                if any(s in m.lower() for s in skip):
                    continue
                arch = classify_fn(m)
                if arch != "unknown":
                    models.setdefault(arch, []).append(m)
        except Exception:
            pass

    return models


def recommend(prompt, server=None, available_archs=None):
    """Recommend the best model and settings for a given prompt.

    Args:
        prompt: User's text description of what they want
        server: ComfyUI server URL (for model inventory)
        available_archs: Pre-fetched {arch: [models]} dict (skips server query)

    Returns dict:
        arch: Best architecture key
        model: Best model filename (or "" if no server)
        reason: Why this was chosen
        intent: Detected user intent
        settings: Recommended generation settings
        alternatives: Other viable options
    """
    intents = detect_intent(prompt)
    primary_intent = intents[0][0]
    reason = intents[0][1]

    # Get available models
    if available_archs is None and server:
        available_archs = _get_server_models(server)
    elif available_archs is None:
        available_archs = {}

    available_keys = set(available_archs.keys()) if available_archs else set(ARCHITECTURES.keys())

    # Find best architecture from intent priority
    arch_priority = INTENT_TO_ARCH.get(primary_intent, INTENT_TO_ARCH["general"])
    best_arch = None
    best_model = ""
    alternatives = []

    for arch_key in arch_priority:
        if arch_key in available_keys:
            if not best_arch:
                best_arch = arch_key
                if available_archs and arch_key in available_archs:
                    best_model = available_archs[arch_key][0]
            else:
                alt_model = ""
                if available_archs and arch_key in available_archs:
                    alt_model = available_archs[arch_key][0]
                alternatives.append({"arch": arch_key, "model": alt_model})

    if not best_arch:
        best_arch = "sd15"
        reason += " (fallback — no preferred models available)"

    # Build recommended settings
    arch = get_arch(best_arch)
    settings = {
        "width": 1024 if best_arch in ("sdxl", "illustrious", "flux1dev", "flux2klein") else 512,
        "height": 1024 if best_arch in ("sdxl", "illustrious", "flux1dev", "flux2klein") else 512,
        "steps": arch.default_steps if arch else 20,
        "cfg": arch.default_cfg if arch else 7.0,
    }

    # Intent-specific adjustments
    if primary_intent == "fast":
        settings["steps"] = min(settings["steps"], 6)
    if primary_intent == "video":
        settings.update({"width": 576, "height": 320, "frames": 33, "fps": 16})
    if primary_intent == "video_t2v":
        settings.update({"width": 384, "height": 256, "frames": 25, "fps": 25})

    return {
        "arch": best_arch,
        "model": best_model,
        "reason": reason,
        "intent": primary_intent,
        "all_intents": intents,
        "settings": settings,
        "alternatives": alternatives[:3],
    }
