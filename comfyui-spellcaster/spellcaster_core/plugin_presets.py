"""Preset bundles for experimental plugins.

Each experimental plugin (Krita, Blender, OBS, Photoshop) exposes a
curated list of starter presets — short name + prompt template +
recommended arch + any extra kwargs the op accepts. UIs pick from
this list rather than making users invent prompts from scratch.

The bundles are specific to each host app because each one has a
different primary workflow:
  - Krita: illustration / concept art / texture
  - Blender: 3D-adjacent — textures, references, HDRI-style backgrounds
  - OBS: streaming overlays, backgrounds, intro stings
  - Photoshop: product + portrait retouch references

Presets are data, not code — a consumer reads the list, shows the
labels in a combobox, then dispatches the right method with the
stored kwargs when the user clicks Go.
"""


# ═══════════════════════════════════════════════════════════════════
#  Krita — illustration, concept art, texturing
# ═══════════════════════════════════════════════════════════════════
KRITA_PRESETS = [
    {
        "label": "Anime character portrait",
        "op": "txt2img",
        "prompt": "anime character portrait, detailed face, expressive eyes, "
                  "studio lighting, clean linework",
        "arch": "illustrious",
    },
    {
        "label": "Cinematic photo",
        "op": "txt2img",
        "prompt": "cinematic photo, shallow depth of field, golden hour, "
                  "35mm film grain, professional composition",
        "arch": "flux1dev",
    },
    {
        "label": "Fantasy concept art",
        "op": "txt2img",
        "prompt": "epic fantasy concept art, dramatic lighting, matte painting "
                  "style, high detail, moody atmosphere",
        "arch": "sdxl",
    },
    {
        "label": "Seamless texture (stone)",
        "op": "txt2img",
        "prompt": "seamless stone texture, tileable, top-down view, high "
                  "detail, PBR-ready, diffuse albedo map",
        "arch": "sdxl",
    },
    {
        "label": "Watercolour illustration",
        "op": "txt2img",
        "prompt": "soft watercolour illustration, loose brushwork, "
                  "granulating pigments, paper texture visible",
        "arch": "sdxl",
    },
    {
        "label": "Style: oil painting (img2img)",
        "op": "img2img",
        "prompt": "oil painting, thick impasto, visible brushstrokes, "
                  "rembrandt lighting",
        "arch": "sdxl",
        "kwargs": {"denoise": 0.5},
    },
    {
        "label": "Colorize photo",
        "op": "colorize",
        "prompt": "vivid natural colors, warm midtones, film photography",
        "arch": "sdxl",
    },
    {
        "label": "Erase object (magic eraser)",
        "op": "magic_eraser",
        "prompt": "",
        "placeholder": "e.g. power line, tourist, watermark",
    },
    {
        "label": "Detail hallucinate 2x",
        "op": "detail_hallucinate",
        "prompt": "crisp detail, fine texture",
        "arch": "sdxl",
        "kwargs": {"upscale_factor": 2.0, "denoise": 0.35},
    },
]


# ═══════════════════════════════════════════════════════════════════
#  Blender — textures, reference plates, concept renders
# ═══════════════════════════════════════════════════════════════════
BLENDER_PRESETS = [
    {
        "label": "PBR texture — stone",
        "op": "txt2img",
        "prompt": "seamless stone wall texture, tileable, diffuse albedo "
                  "map, PBR-ready, top-down view",
        "arch": "sdxl",
    },
    {
        "label": "PBR texture — wood planks",
        "op": "txt2img",
        "prompt": "seamless wood planks texture, tileable, warm tones, "
                  "aged grain, PBR diffuse",
        "arch": "sdxl",
    },
    {
        "label": "PBR texture — metal",
        "op": "txt2img",
        "prompt": "seamless scratched steel metal texture, tileable, "
                  "industrial, PBR albedo",
        "arch": "sdxl",
    },
    {
        "label": "Sci-fi concept environment",
        "op": "txt2img",
        "prompt": "sci-fi concept environment, massive scale, dramatic "
                  "lighting, futuristic architecture, matte painting",
        "arch": "flux1dev",
    },
    {
        "label": "Fantasy landscape reference",
        "op": "txt2img",
        "prompt": "fantasy landscape reference, mountains and rivers, "
                  "golden hour, painterly, environmental detail",
        "arch": "sdxl",
    },
    {
        "label": "HDRI-style skybox",
        "op": "txt2img",
        "prompt": "360 equirectangular skybox, HDRI sky, soft clouds, "
                  "golden hour, seamless horizon",
        "arch": "flux1dev",
    },
    {
        "label": "Character reference sheet",
        "op": "txt2img",
        "prompt": "character reference sheet, front and side view, neutral "
                  "t-pose, clean background, concept art",
        "arch": "sdxl",
    },
    {
        "label": "Normal map from canvas",
        "op": "normal_map",
        "prompt": "",
    },
    {
        "label": "Detail hallucinate 4x (tile)",
        "op": "detail_hallucinate",
        "prompt": "crisp surface detail, fine texture, macro clarity",
        "arch": "sdxl",
        "kwargs": {"upscale_factor": 4.0, "denoise": 0.35},
    },
]


# ═══════════════════════════════════════════════════════════════════
#  OBS — streaming backgrounds, overlays, intro stingers
# ═══════════════════════════════════════════════════════════════════
OBS_PRESETS = [
    {
        "label": "Gaming background — cyberpunk",
        "op": "txt2img",
        "prompt": "cyberpunk street at night, neon signs, rain-soaked "
                  "asphalt, reflections, atmospheric, streaming background",
        "arch": "sdxl",
        "kwargs": {"width": 1920, "height": 1080},
    },
    {
        "label": "Gaming background — fantasy tavern",
        "op": "txt2img",
        "prompt": "cozy fantasy tavern interior, warm firelight, wooden "
                  "beams, ambient, streaming background",
        "arch": "sdxl",
        "kwargs": {"width": 1920, "height": 1080},
    },
    {
        "label": "Lo-fi study overlay",
        "op": "txt2img",
        "prompt": "lo-fi anime aesthetic, desk scene, warm lamp, rain on "
                  "window, chillwave colors",
        "arch": "illustrious",
        "kwargs": {"width": 1920, "height": 1080},
    },
    {
        "label": "BRB screen — fantasy",
        "op": "txt2img",
        "prompt": "fantasy landscape, painterly, peaceful meadow, golden "
                  "hour, nothing distracting",
        "arch": "sdxl",
        "kwargs": {"width": 1920, "height": 1080},
    },
    {
        "label": "Starting soon — abstract neon",
        "op": "txt2img",
        "prompt": "abstract neon gradient, synthwave grid, minimal, "
                  "streamer starting soon background",
        "arch": "sdxl",
        "kwargs": {"width": 1920, "height": 1080},
    },
    {
        "label": "Intro clip — cyberpunk flythrough (3s)",
        "op": "ltx_t2v",
        "prompt": "flying through a neon cyberpunk city at night, fast "
                  "camera motion, rain, reflections, cinematic",
        "kwargs": {"seconds": 3.0, "width": 1280, "height": 720, "fps": 25},
    },
    {
        "label": "Intro clip — fantasy reveal (3s)",
        "op": "ltx_t2v",
        "prompt": "dramatic reveal of a floating castle above clouds, "
                  "slow dolly-in, volumetric light, epic fantasy",
        "kwargs": {"seconds": 3.0, "width": 1280, "height": 720, "fps": 25},
    },
    {
        "label": "Intro clip — abstract particles (2s)",
        "op": "ltx_t2v",
        "prompt": "glowing particles swirling in dark space, ethereal, "
                  "slow motion, volumetric",
        "kwargs": {"seconds": 2.0, "width": 1280, "height": 720, "fps": 25},
    },
]


# ═══════════════════════════════════════════════════════════════════
#  Photoshop — product, portrait, social
# ═══════════════════════════════════════════════════════════════════
PHOTOSHOP_PRESETS = [
    {
        "label": "Product shot — studio",
        "op": "txt2img",
        "prompt": "professional product photography, clean white backdrop, "
                  "studio softbox lighting, high detail, commercial quality",
        "arch": "flux1dev",
    },
    {
        "label": "Portrait retouch reference",
        "op": "txt2img",
        "prompt": "professional portrait photography, natural skin texture, "
                  "soft window light, shallow DoF, 85mm lens",
        "arch": "flux1dev",
    },
    {
        "label": "Social post — square lifestyle",
        "op": "txt2img",
        "prompt": "bright lifestyle photography, warm natural light, shallow "
                  "depth of field, social-media-ready square composition",
        "arch": "sdxl",
        "kwargs": {"width": 1024, "height": 1024},
    },
    {
        "label": "Background plate — studio gradient",
        "op": "txt2img",
        "prompt": "smooth gradient studio backdrop, clean, no subject, "
                  "color-graded neutral tones",
        "arch": "sdxl",
    },
    {
        "label": "AI upscale 4x",
        "op": "upscale",
        "prompt": "",
    },
    {
        "label": "Remove background",
        "op": "rembg",
        "prompt": "",
    },
]


# ═══════════════════════════════════════════════════════════════════
#  Krita — NSFW preset bundle (mined from spellcaster_NSFW JSON presets)
# ═══════════════════════════════════════════════════════════════════
#
# All entries target Klein 4B (the only Klein variant that fits 8 GB
# VRAM). Each op corresponds to a real method on the KritaSpellcaster
# class — _dispatch_preset calls `getattr(plug, op)(prompt, **kwargs)`.
#
# Ops used:
#   klein_generate_object   — txt-to-image via Klein
#   klein_scene_img2img     — img2img on the active canvas
#   klein_refine            — full-image enhancement / refine
#   klein_inpaint           — uses the active SELECTION as mask
#   klein_repose            — change pose while preserving identity
#   klein_face_detail       — face / eye detail enhancement
#   klein_detail            — texture / micro-detail enhancement
#   photobooth              — multi-pose batch
#
# Prompts intentionally clinical/aesthetic — focused on composition,
# lighting, and anatomical accuracy rather than crude descriptors.
# Edit the prompt in the dialog before each run to add subject
# specifics ("woman in her 30s, ...", "athletic build, ...", etc.).
KRITA_NSFW_PRESETS = [
    # ─── Generate (txt-to-image, Klein) ────────────────────────────
    {
        "label": "NSFW Klein — Portrait closeup",
        "op": "klein_generate_object",
        "prompt": "intimate closeup portrait, soft window light, "
                  "shallow depth of field, sensual mood, detailed skin "
                  "texture, photorealistic, 85mm lens, RAW photo",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Full body shot",
        "op": "klein_generate_object",
        "prompt": "full body photograph, anatomically correct, "
                  "natural pose, soft directional lighting, 35mm lens, "
                  "professional photography, detailed body proportions",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Boudoir / bedroom",
        "op": "klein_generate_object",
        "prompt": "intimate boudoir photograph, soft bedroom lighting, "
                  "silk sheets, warm color palette, sensual mood, "
                  "professional glamour photography, highly detailed",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Lingerie studio",
        "op": "klein_generate_object",
        "prompt": "lingerie photoshoot, clean studio backdrop, soft key "
                  "light with rim lighting, detailed lace and silk "
                  "texture, editorial fashion photography",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Bath / shower scene",
        "op": "klein_generate_object",
        "prompt": "intimate bath scene, water droplets on skin, steam, "
                  "soft natural light through frosted window, detailed "
                  "wet skin texture, glistening highlights",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Beach / poolside",
        "op": "klein_generate_object",
        "prompt": "beach photoshoot, golden hour lighting, sun-kissed "
                  "skin, swimwear, sandy beach background, shallow "
                  "depth of field, professional editorial photography",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Outdoor sensual",
        "op": "klein_generate_object",
        "prompt": "outdoor sensual photograph, natural environment, "
                  "dappled sunlight through trees, soft skin tones, "
                  "natural pose, editorial fashion photography",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Glamour / film noir",
        "op": "klein_generate_object",
        "prompt": "film noir glamour shot, dramatic side lighting, "
                  "deep shadows, monochrome with selective color, "
                  "smoky atmosphere, vintage 35mm film grain",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },

    # ─── img2img on canvas (Klein) ─────────────────────────────────
    {
        "label": "NSFW Klein — Make sensual (img2img)",
        "op": "klein_scene_img2img",
        "prompt": "transform into intimate sensual scene, soft warm "
                  "lighting, detailed skin texture, editorial fashion "
                  "style, photographic realism",
        "arch": "flux2klein",
    },
    {
        "label": "NSFW Klein — Convert to boudoir (img2img)",
        "op": "klein_scene_img2img",
        "prompt": "convert to boudoir setting, silk fabric, warm "
                  "bedroom lighting, intimate composition, professional "
                  "glamour photography",
        "arch": "flux2klein",
    },

    # ─── Refine existing image (Klein) ─────────────────────────────
    {
        "label": "NSFW Klein — Anatomy fix (refine)",
        "op": "klein_refine",
        "prompt": "anatomically correct body, natural proportions, "
                  "smooth skin transitions, realistic anatomy, "
                  "detailed body texture",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Skin / texture enhance",
        "op": "klein_detail",
        "prompt": "highly detailed skin texture, visible pores, natural "
                  "skin tone, sharp focus, photographic realism, "
                  "subsurface scattering",
        "arch": "flux2klein",
    },
    {
        "label": "NSFW Klein — Face / eye detail",
        "op": "klein_face_detail",
        "prompt": "beautiful detailed face, symmetric features, clear "
                  "sharp eyes with catchlights, natural skin, defined "
                  "lashes, photorealistic",
        "arch": "flux2klein",
    },

    # ─── Inpaint (uses active selection as mask) ───────────────────
    {
        "label": "NSFW Klein — Inpaint: remove clothing (mask first)",
        "op": "klein_inpaint",
        "prompt": "anatomically correct bare skin, natural skin tone, "
                  "matching ambient lighting, soft shadow transitions, "
                  "photorealistic body",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B", "denoise": 0.95},
        "placeholder": "mask the clothing area in Krita first, then run",
    },
    {
        "label": "NSFW Klein — Inpaint: add lingerie (mask first)",
        "op": "klein_inpaint",
        "prompt": "elegant lingerie, detailed lace pattern and silk "
                  "fabric, natural fit on body, realistic fabric "
                  "drape, matching ambient light",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B", "denoise": 0.85},
        "placeholder": "mask the area to clothe in Krita first",
    },
    {
        "label": "NSFW Klein — Inpaint: outfit swap (mask first)",
        "op": "klein_inpaint",
        "prompt": "stylish outfit, detailed fabric, natural fit, "
                  "matching scene lighting, photorealistic",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B", "denoise": 0.85},
        "placeholder": "mask current clothing in Krita, then describe new outfit",
    },
    {
        "label": "NSFW Klein — Inpaint: anatomy retouch (mask first)",
        "op": "klein_inpaint",
        "prompt": "anatomically corrected region, natural proportions, "
                  "smooth detailed skin, matching surrounding tone",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B", "denoise": 0.7},
        "placeholder": "mask the area to fix in Krita first",
    },

    # ─── Pose / composition ────────────────────────────────────────
    {
        "label": "NSFW Klein — Repose: reclining",
        "op": "klein_repose",
        "prompt": "reclining pose, relaxed body, soft curves, "
                  "natural body language, anatomically correct",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Repose: sitting",
        "op": "klein_repose",
        "prompt": "seated pose, natural posture, relaxed shoulders, "
                  "anatomically correct proportions",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
    {
        "label": "NSFW Klein — Repose: dynamic",
        "op": "klein_repose",
        "prompt": "dynamic dramatic pose, expressive body language, "
                  "anatomically correct, detailed muscle tone",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
        "placeholder": "describe pose: e.g. arms above head, leaning back, ...",
    },

    # ─── Multi-pose batch ──────────────────────────────────────────
    {
        "label": "NSFW Klein — Photobooth: pose variations",
        "op": "photobooth",
        "prompt": "varied natural poses, consistent identity, "
                  "professional editorial photography",
        "arch": "flux2klein",
        "kwargs": {"klein_model_key": "Klein 4B"},
    },
]


# ═══════════════════════════════════════════════════════════════════
#  Access helper — by origin key
# ═══════════════════════════════════════════════════════════════════
_PRESETS_BY_ORIGIN = {
    # Krita gets SFW + NSFW concatenated. The NSFW block was ported from
    # spellcaster_NSFW/plugins/gimp/comfyui-connector/presets/{scene,lora,
    # inpaint_refinements}.json and adapted to the Krita plugin's op set
    # (Klein 4B-only since the larger Klein 9B / Flux 1 dev BF16 don't
    # fit 8 GB VRAM).
    "krita": KRITA_PRESETS + KRITA_NSFW_PRESETS,
    "blender": BLENDER_PRESETS,
    "obs": OBS_PRESETS,
    "photoshop": PHOTOSHOP_PRESETS,
}


def presets_for(origin):
    """Return the preset list for an origin key (``"krita"``,
    ``"blender"``, ``"obs"``, ``"photoshop"``). Unknown origin → []."""
    return list(_PRESETS_BY_ORIGIN.get((origin or "").lower(), []))
