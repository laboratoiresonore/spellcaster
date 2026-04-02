--[[
  comfyui_connector.lua - Spellcaster: AI superpowers for Darktable

  darktable is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.
]]

--[[
    comfyui_connector.lua  --  Spellcaster Darktable Plugin
    ========================================================

    Bridge between Darktable (photo editor) and ComfyUI (AI image/video server).

    Architecture overview:
      1. User selects images in Darktable lighttable view
      2. Plugin exports them to PNG temp files
      3. Uploads via ComfyUI's REST API (curl-based HTTP)
      4. Submits a JSON workflow (built programmatically per task type)
      5. Polls /history endpoint until results appear
      6. Downloads output images/videos and imports them into Darktable

    Supported workflows:
      - img2img     : SD1.5 / SDXL / Illustrious checkpoint-based image transformation
      - Inpaint     : Mask-guided regeneration of image regions (SetLatentNoiseMask)
      - Face Swap   : ReActor (saved model + direct) and mtb facetools
      - FaceID      : IPAdapter-based face identity transfer
      - PuLID Flux  : Face identity transfer using PuLID on Flux architecture
      - Klein Flux2 : Distilled Flux2 img2img (with optional reference image)
      - Wan I2V     : Wan 2.2 image-to-video generation (dual-UNET high/low noise)

    Why curl instead of a Lua HTTP library?
      Darktable's embedded Lua has no built-in HTTP support and loading
      native C modules (luasocket, lua-curl) is fragile across platforms.
      curl is universally available (built into Windows 10+, macOS, Linux)
      and avoids all dependency issues. The tradeoff is shell escaping
      overhead and temp-file I/O, but this is negligible for the small
      payloads involved (~1-50KB JSON, single image uploads).

    REQUIREMENTS: curl, a running ComfyUI server.
    Enable via script_manager in lighttable.
]]

-- ═══════════════════════════════════════════════════════════════════════
-- Darktable API bootstrap and script_manager registration
-- ═══════════════════════════════════════════════════════════════════════
-- Darktable discovers plugins via script_manager. Each plugin must return
-- a script_data table with metadata, lifecycle callbacks (destroy/restart),
-- and a destroy_method hint. The "hide" method keeps the module registered
-- but invisible, avoiding re-registration overhead on view switches.

local dt = require "darktable"
local du = require "lib/dtutils"

local MODULE_NAME = "comfyui_connector"
du.check_min_api_version("7.0.0", MODULE_NAME)  -- requires dt API 7.0+

-- gettext must be defined BEFORE anything uses _() for i18n string wrapping
local gettext = dt.gettext.gettext
dt.gettext.bindtextdomain(MODULE_NAME, dt.configuration.config_dir .. "/lua/locale/")
local function _(msgid) return gettext(msgid) end

-- script_manager lifecycle table -- populated at end of file with destroy/restart
local script_data = {}

script_data.metadata = {
  name = _("Spellcaster"),
  purpose = _("send images to a ComfyUI server for AI processing"),
  author = "Spellcaster",
  help = ""
}

script_data.destroy = nil       -- set to destroy() at end of file
script_data.destroy_method = nil -- set to "hide" at end of file
script_data.restart = nil       -- set to restart() at end of file
script_data.show = nil          -- set to restart() at end of file

-- ═══════════════════════════════════════════════════════════════════════
-- MODEL PRESETS -- mirrors GIMP plugin, tuned per architecture
-- ═══════════════════════════════════════════════════════════════════════
-- Each preset bundles a checkpoint path with its optimal generation
-- parameters (steps, CFG scale, denoise strength, sampler/scheduler).
-- The prompt_hint/negative_hint are prepended to user input to steer
-- the model toward its strength (e.g. "photorealistic" for photo models).
--
-- The `arch` field ("sd15", "sdxl", "zit") determines which LoRAs
-- are shown as compatible in the UI via ARCH_LORA_PREFIXES filtering.
--
-- Checkpoint paths use backslash separators matching ComfyUI's Windows
-- model directory structure (ComfyUI uses OS-native separators).

local MODEL_PRESETS = {
  -- SD 1.5
  { label = "SD1.5 - Juggernaut Reborn (realistic)", arch = "sd15",
    ckpt  = "SD-1.5\\juggernaut_reborn.safetensors",
    steps = 25, cfg = 7.0, denoise = 0.62,
    sampler = "dpmpp_2m", scheduler = "karras",
    prompt_hint = "photorealistic, highly detailed, sharp focus",
    negative_hint = "cartoon, painting, blurry, deformed" },

  { label = "SD1.5 - Realistic Vision v5.1 (photo)", arch = "sd15",
    ckpt  = "SD-1.5\\realisticVisionV51_v51VAE.safetensors",
    steps = 25, cfg = 7.0, denoise = 0.60,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "RAW photo, photorealistic, ultra detailed skin",
    negative_hint = "(deformed, distorted, disfigured:1.3), blurry, bad anatomy" },

  { label = "SD1.5 - Base v1.5 (general)", arch = "sd15",
    ckpt  = "SD-1.5\\v1-5-pruned-emaonly.safetensors",
    steps = 20, cfg = 7.5, denoise = 0.65,
    sampler = "euler", scheduler = "normal",
    prompt_hint = "high quality, detailed",
    negative_hint = "lowres, bad anatomy, worst quality" },

  -- SDXL Anime
  { label = "SDXL - NoobAI-XL v1.1 (anime)", arch = "sdxl",
    ckpt  = "SDXL\\Anime\\NoobAI-XL-v1.1.safetensors",
    steps = 28, cfg = 6.0, denoise = 0.60,
    sampler = "euler_ancestral", scheduler = "normal",
    prompt_hint = "masterpiece, best quality, anime style, detailed",
    negative_hint = "worst quality, low quality, blurry, bad anatomy" },

  { label = "SDXL - Nova Anime XL v1.70 (anime)", arch = "sdxl",
    ckpt  = "SDXL\\Anime\\novaAnimeXL_ilV170.safetensors",
    steps = 25, cfg = 6.5, denoise = 0.60,
    sampler = "euler_ancestral", scheduler = "normal",
    prompt_hint = "anime, masterpiece, vivid colors, detailed illustration",
    negative_hint = "worst quality, low quality, realistic, 3d" },

  { label = "SDXL - Wai Illustrious SDXL (anime)", arch = "sdxl",
    ckpt  = "SDXL\\Anime\\waiIllustriousSDXL_v160-a5f5.safetensors",
    steps = 28, cfg = 5.5, denoise = 0.58,
    sampler = "euler_ancestral", scheduler = "normal",
    prompt_hint = "masterpiece, best quality, very aesthetic, absurdres",
    negative_hint = "worst quality, low quality, lowres, bad anatomy" },

  -- SDXL Base
  { label = "SDXL - Albedo Base XL (versatile)", arch = "sdxl",
    ckpt  = "SDXL\\Base\\AlbedoBaseXL.safetensors",
    steps = 25, cfg = 7.0, denoise = 0.62,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "high quality, detailed, professional",
    negative_hint = "lowres, bad anatomy, worst quality, blurry" },

  { label = "SDXL - Base 1.0 (reference)", arch = "sdxl",
    ckpt  = "SDXL\\Base\\sd_xl_base_1.0.safetensors",
    steps = 25, cfg = 7.0, denoise = 0.65,
    sampler = "euler", scheduler = "normal",
    prompt_hint = "high quality, detailed",
    negative_hint = "lowres, worst quality, blurry" },

  -- SDXL Cartoon/3D
  { label = "SDXL - Modern Disney XL v3 (cartoon/3D)", arch = "sdxl",
    ckpt  = "SDXL\\Cartoon-3D\\modernDisneyXL_v3.safetensors",
    steps = 30, cfg = 7.0, denoise = 0.60,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "disney style, 3d render, cartoon, vibrant colors, cinematic lighting",
    negative_hint = "photorealistic, blurry, low quality, deformed" },

  { label = "SDXL - Nova Cartoon XL v6 (cartoon/3D)", arch = "sdxl",
    ckpt  = "SDXL\\Cartoon-3D\\novaCartoonXL_v60.safetensors",
    steps = 28, cfg = 7.0, denoise = 0.58,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "cartoon style, vibrant, illustration, detailed",
    negative_hint = "photorealistic, blurry, deformed, low quality" },

  -- SDXL Realistic
  { label = "SDXL - CyberRealistic Pony v1.6 (realistic)", arch = "sdxl",
    ckpt  = "SDXL\\Realistic\\cyberrealisticPony_v160.safetensors",
    steps = 30, cfg = 6.5, denoise = 0.58,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "score_9, score_8_up, photorealistic, ultra detailed, sharp",
    negative_hint = "score_4, score_3, blurry, cartoon, deformed" },

  { label = "SDXL - JibMix Realistic XL v1.8 (photo)", arch = "sdxl",
    ckpt  = "SDXL\\Realistic\\jibMixRealisticXL_v180SkinSupreme.safetensors",
    steps = 30, cfg = 6.0, denoise = 0.55,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "photorealistic, professional photography, natural skin, sharp focus",
    negative_hint = "painting, cartoon, deformed, blurry, overexposed" },

  { label = "SDXL - Juggernaut XL Ragnarok (realistic)", arch = "sdxl",
    ckpt  = "SDXL\\Realistic\\juggernautXL_ragnarok.safetensors",
    steps = 30, cfg = 6.0, denoise = 0.58,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "photorealistic, cinematic, highly detailed, professional",
    negative_hint = "cartoon, anime, blurry, deformed, low quality" },

  { label = "SDXL - Juggernaut XL v9 (photo)", arch = "sdxl",
    ckpt  = "SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
    steps = 30, cfg = 6.5, denoise = 0.58,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "photorealistic, cinematic lighting, sharp focus, professional",
    negative_hint = "cartoon, painting, deformed, blurry, worst quality" },

  { label = "SDXL - ZavyChroma XL v10 (realistic)", arch = "sdxl",
    ckpt  = "SDXL\\Realistic\\zavychromaxl_v100.safetensors",
    steps = 25, cfg = 6.5, denoise = 0.60,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
    prompt_hint = "photorealistic, vivid, cinematic, highly detailed",
    negative_hint = "cartoon, blurry, deformed, worst quality" },

  -- Illustrious
  { label = "Illustrious - IlustReal v5 (semi-real)", arch = "sdxl",
    ckpt  = "Illustrious\\ilustreal_v50VAE.safetensors",
    steps = 28, cfg = 5.0, denoise = 0.58,
    sampler = "euler_ancestral", scheduler = "normal",
    prompt_hint = "masterpiece, best quality, very aesthetic, semi-realistic",
    negative_hint = "worst quality, low quality, blurry, bad anatomy" },

  { label = "Illustrious - Sloppy Messy Mix v1 (artistic)", arch = "sdxl",
    ckpt  = "Illustrious\\sloppyMessyMix_sloppyMessyMixV1.safetensors",
    steps = 28, cfg = 5.5, denoise = 0.60,
    sampler = "euler_ancestral", scheduler = "normal",
    prompt_hint = "masterpiece, best quality, painterly, expressive",
    negative_hint = "worst quality, low quality, blurry" },

  -- Z-Image-Turbo (ZIT) — fast distilled SDXL, 4-12 steps, low CFG
  { label = "ZIT - Photo (fast 6-step)", arch = "zit",
    ckpt  = "ZIT\\gonzalomoZpop_v30AIO.safetensors",
    steps = 6, cfg = 2.0, denoise = 0.60,
    sampler = "euler", scheduler = "simple",
    prompt_hint = "professional photograph, sharp focus, natural lighting, realistic, 8k",
    negative_hint = "blurry, low quality, deformed, cartoon, worst quality" },

  { label = "ZIT - Portrait (fast 8-step)", arch = "zit",
    ckpt  = "ZIT\\gonzalomoZpop_v30AIO.safetensors",
    steps = 8, cfg = 2.5, denoise = 0.55,
    sampler = "euler", scheduler = "simple",
    prompt_hint = "close-up portrait, 85mm lens, soft bokeh, studio lighting, detailed skin",
    negative_hint = "blurry, deformed face, bad anatomy, cartoon, low quality" },

  { label = "ZIT - Cinematic (8-step)", arch = "zit",
    ckpt  = "ZIT\\gonzalomoZpop_v30AIO.safetensors",
    steps = 8, cfg = 2.5, denoise = 0.62,
    sampler = "euler", scheduler = "simple",
    prompt_hint = "cinematic still, anamorphic lens, dramatic lighting, film grain, 35mm",
    negative_hint = "flat lighting, overexposed, blurry, low quality, cartoon" },

  { label = "ZIT - Anime (6-step)", arch = "zit",
    ckpt  = "ZIT\\gonzalomoZpop_v30AIO.safetensors",
    steps = 6, cfg = 2.0, denoise = 0.58,
    sampler = "euler", scheduler = "simple",
    prompt_hint = "masterpiece, best quality, detailed anime, vibrant colors, sharp linework",
    negative_hint = "worst quality, low quality, blurry, realistic, 3d" },

  { label = "ZIT - Quality (12-step)", arch = "zit",
    ckpt  = "ZIT\\gonzalomoZpop_v30AIO.safetensors",
    steps = 12, cfg = 3.0, denoise = 0.60,
    sampler = "dpmpp_2m", scheduler = "karras",
    prompt_hint = "ultra detailed, professional quality, sharp focus, vivid colors, high resolution",
    negative_hint = "blurry, low quality, deformed, worst quality" },
}

-- ═══════════════════════════════════════════════════════════════════════
-- SCENE PRESETS -- subject/scene templates per architecture group
-- ═══════════════════════════════════════════════════════════════════════
-- Each preset defines a label (shown in the dropdown) and prompt text
-- keyed by architecture group: sd15, sdxl, sdxl_anime, sdxl_cartoon,
-- flux, flux_kontext.  The scene_arch() helper maps a MODEL_PRESETS
-- entry to one of these groups so the UI can filter appropriately.

local SCENE_PRESETS = {
  -- ── Photo / Realistic (sd15, sdxl, flux) ──────────────────────────
  { label = "(custom — write your own)",
    prompts = {
      sd15          = { positive = "", negative = "" },
      sdxl          = { positive = "", negative = "" },
      flux          = { positive = "", negative = "" },
      sdxl_anime    = { positive = "", negative = "" },
      sdxl_cartoon  = { positive = "", negative = "" },
      flux_kontext  = { positive = "", negative = "" },
    },
  },

  { label = "Portrait — Headshot",
    prompts = {
      sd15 = {
        positive = "close-up portrait photograph of [subject], 85mm lens, f/1.8, shallow depth of field, soft studio lighting, catchlights in eyes, ultra-detailed skin texture, sharp focus, photorealistic, professional headshot, RAW photo",
        negative = "(deformed, distorted, disfigured:1.3), poorly drawn face, bad anatomy, extra limbs, blurry, out of focus, low quality, cartoon, painting",
      },
      sdxl = {
        positive = "close-up portrait photograph of [subject], shot on Canon EOS R5 with 85mm f/1.4 lens, shallow depth of field, soft directional studio lighting, catchlights in eyes, ultra-detailed skin pores and texture, sharp focus on eyes, professional headshot, natural skin tones, 8k resolution",
        negative = "(deformed, distorted, disfigured:1.3), poorly drawn face, mutation, extra limbs, blurry, bokeh on face, watermark, text, low quality, worst quality, cartoon",
      },
      flux = {
        positive = "Professional headshot portrait of [subject]. Shot on a Canon EOS R5 with an 85mm f/1.4 lens at close range. Soft directional studio lighting creates gentle shadows on one side of the face. Sharp focus on the eyes with beautiful catchlights. Shallow depth of field blurs the background into creamy bokeh. Natural skin tones, visible pores and fine details. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Portrait — Full Body",
    prompts = {
      sd15 = {
        positive = "full body portrait of [subject], standing pose, 50mm lens, f/2.8, natural lighting, clean background, professional fashion photography, sharp focus, highly detailed clothing texture, photorealistic, RAW photo",
        negative = "(deformed, distorted, disfigured:1.3), bad anatomy, extra limbs, missing limbs, floating limbs, blurry, low quality, cartoon, painting",
      },
      sdxl = {
        positive = "full body portrait of [subject], standing pose, shot on Sony A7IV with 50mm f/1.8 lens, natural window lighting, clean studio backdrop, professional fashion photography, sharp focus throughout, detailed clothing fabric texture, natural skin tones, 8k resolution",
        negative = "(deformed, distorted, disfigured:1.3), bad anatomy, extra limbs, missing limbs, floating limbs, blurry, watermark, text, worst quality, low quality",
      },
      flux = {
        positive = "Full body portrait of [subject] standing in a relaxed pose. Photographed with a Sony A7IV and 50mm f/1.8 lens. Soft natural window light illuminates the scene from the left. The background is a clean, slightly blurred studio environment. Every detail of the clothing fabric and accessories is crisp and well-defined. Natural skin tones and proportions. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Product Photo",
    prompts = {
      sd15 = {
        positive = "professional product photography of [subject], white seamless background, soft box lighting, commercial studio setup, sharp focus, clean composition, high-end advertising photo, ultra detailed, RAW photo",
        negative = "(deformed, distorted:1.3), blurry, low quality, noisy, overexposed, text, watermark, bad reflections",
      },
      sdxl = {
        positive = "professional product photography of [subject], pristine white seamless background, three-point soft box lighting, commercial studio setup, shot on Phase One IQ4 with 120mm macro lens, razor sharp focus, clean minimal composition, high-end advertising campaign, ultra detailed textures, 8k resolution",
        negative = "(deformed, distorted:1.3), blurry, noisy, overexposed, underexposed, text, watermark, worst quality, low quality",
      },
      flux = {
        positive = "Professional commercial product photograph of [subject] on a pristine white seamless background. Lit with three-point soft box studio lighting that creates gentle highlights and subtle shadows. Shot on a Phase One IQ4 150MP with a 120mm macro lens for extreme sharpness. Clean minimal composition with generous negative space. Every surface detail, texture, and reflection is captured with precision. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Landscape / Scenic",
    prompts = {
      sd15 = {
        positive = "breathtaking landscape photograph of [subject], golden hour lighting, wide angle lens, f/11, deep depth of field, vivid colors, dramatic sky, National Geographic quality, sharp foreground to background, RAW photo",
        negative = "blurry, overexposed, flat lighting, low quality, cartoon, painting, text, watermark, people",
      },
      sdxl = {
        positive = "breathtaking landscape photograph of [subject], golden hour lighting, shot on Nikon Z9 with 14-24mm f/2.8 wide angle lens at f/11, deep depth of field from foreground to infinity, vivid natural colors, dramatic cloud formations, National Geographic quality, luminous atmosphere, 8k resolution",
        negative = "blurry, overexposed, flat lighting, low quality, worst quality, cartoon, painting, text, watermark, people, artifacts",
      },
      flux = {
        positive = "Breathtaking landscape photograph of [subject] during golden hour. Shot on a Nikon Z9 with a 14-24mm f/2.8 lens at f/11 for infinite depth of field. Warm directional sunlight bathes the scene in golden tones while dramatic cloud formations fill the sky. Vivid natural colors with luminous atmosphere. Sharp detail from the nearest foreground element to the distant horizon. National Geographic quality. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Food Photography",
    prompts = {
      sd15 = {
        positive = "professional food photography of [subject], overhead angle, soft diffused natural lighting, shallow depth of field, rustic wooden surface, garnish details, appetizing colors, editorial food styling, sharp focus, RAW photo",
        negative = "blurry, unappetizing, dark, underexposed, low quality, cartoon, artificial looking, text, watermark",
      },
      sdxl = {
        positive = "professional food photography of [subject], 45-degree overhead angle, soft diffused natural window lighting with bounce fill, shallow depth of field, artisan ceramic plate on rustic wooden surface, fresh garnish details, rich appetizing color palette, editorial food styling, shot on Canon EOS R5 with 100mm macro lens, 8k resolution",
        negative = "blurry, unappetizing, dark, underexposed, overexposed, low quality, worst quality, cartoon, artificial looking, text, watermark",
      },
      flux = {
        positive = "Professional editorial food photograph of [subject] styled on an artisan ceramic plate atop a rustic wooden surface. Shot from a 45-degree overhead angle with a Canon EOS R5 and 100mm macro lens. Soft diffused natural window light from the left with a subtle bounce fill on the right. Shallow depth of field draws the eye to the hero dish while fresh herb garnishes add pops of green. Rich, appetizing color palette with warm undertones. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Architecture / Interior",
    prompts = {
      sd15 = {
        positive = "professional architectural photography of [subject], wide angle lens, f/8, perfectly straight verticals, balanced exposure, natural lighting with warm tones, clean composition, sharp details, interior design magazine quality, RAW photo",
        negative = "distorted perspective, lens distortion, blurry, dark, low quality, cartoon, people, cluttered, text, watermark",
      },
      sdxl = {
        positive = "professional architectural photography of [subject], shot on Canon TS-E 17mm tilt-shift lens at f/8, perfectly corrected verticals and perspective, balanced HDR exposure, warm natural lighting blended with interior ambient light, clean geometric composition, ultra sharp details on textures and materials, Architectural Digest magazine quality, 8k resolution",
        negative = "distorted perspective, lens distortion, blurry, dark, low quality, worst quality, cartoon, people, cluttered, text, watermark",
      },
      flux = {
        positive = "Professional architectural photograph of [subject] shot with a Canon TS-E 17mm tilt-shift lens at f/8. Perfectly corrected vertical lines and perspective. Warm natural light streams through windows and blends with the ambient interior illumination. The composition emphasizes clean geometric lines and spatial depth. Ultra-sharp details reveal every texture in the materials — wood grain, stone, glass reflections. Architectural Digest magazine quality. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Fashion Editorial",
    prompts = {
      sd15 = {
        positive = "high fashion editorial photograph of [subject], dramatic studio lighting, bold composition, fashion magazine cover quality, sharp focus on clothing details, stylized color grading, professional model pose, Vogue quality, RAW photo",
        negative = "(deformed, disfigured:1.3), bad anatomy, blurry, low quality, amateur, casual snapshot, cartoon, painting",
      },
      sdxl = {
        positive = "high fashion editorial photograph of [subject], dramatic Rembrandt studio lighting with colored gels, bold avant-garde composition, shot on Hasselblad H6D with 80mm lens, fashion magazine cover quality, razor sharp focus on clothing textures and details, stylized cinematic color grading, powerful model pose, Vogue editorial quality, 8k resolution",
        negative = "(deformed, disfigured:1.3), bad anatomy, blurry, low quality, worst quality, amateur, casual snapshot, cartoon, painting, watermark",
      },
      flux = {
        positive = "High fashion editorial photograph of [subject] for a Vogue magazine spread. Shot on a Hasselblad H6D with an 80mm lens. Dramatic Rembrandt lighting with subtle colored gels creates depth and mood. Bold avant-garde composition with negative space. Every thread and texture of the clothing is razor sharp. Stylized cinematic color grading with deep shadows and luminous highlights. Powerful, confident model pose. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Fantasy Art / Epic Scene",
    prompts = {
      sd15 = {
        positive = "epic fantasy art scene of [subject], dramatic volumetric lighting, god rays, cinematic composition, highly detailed environment, magical atmosphere, digital painting, concept art, ultra detailed, masterpiece, sharp focus, RAW photo",
        negative = "blurry, low quality, amateur, flat lighting, boring composition, text, watermark, cartoon, chibi",
      },
      sdxl = {
        positive = "epic fantasy art scene of [subject], dramatic volumetric lighting with god rays piercing through clouds, cinematic wide composition, highly detailed environment with intricate architectural elements, magical particle effects, rich color palette, concept art quality, digital painting masterpiece, ultra detailed foreground and background, 8k resolution",
        negative = "blurry, low quality, worst quality, amateur, flat lighting, boring composition, text, watermark, simple background",
      },
      flux = {
        positive = "Epic fantasy art depicting [subject] in a sweeping cinematic composition. Dramatic volumetric lighting with golden god rays pierce through towering cloud formations. The environment is rich with intricate architectural details and magical particle effects floating in the air. Deep color palette ranging from warm ambers to cool teals creates visual depth. Every element — from foreground debris to distant mountains — is rendered with meticulous detail. Concept art masterpiece quality. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Cinematic / Film Still",
    prompts = {
      sd15 = {
        positive = "cinematic film still of [subject], anamorphic lens, shallow depth of field, moody dramatic lighting, film grain, color graded, 35mm film look, movie scene composition, atmospheric, sharp focus, RAW photo",
        negative = "blurry, flat lighting, overexposed, low quality, amateur, snapshot, cartoon, painting, text, watermark",
      },
      sdxl = {
        positive = "cinematic film still of [subject], shot on ARRI Alexa with Cooke anamorphic lens, 2.39:1 aspect ratio, shallow depth of field with oval bokeh, moody dramatic lighting with practical light sources, subtle film grain, professional color grading with teal-orange palette, 35mm film aesthetic, masterful movie scene composition, atmospheric haze, 8k resolution",
        negative = "blurry, flat lighting, overexposed, low quality, worst quality, amateur, snapshot, cartoon, painting, text, watermark, video game",
      },
      flux = {
        positive = "Cinematic film still of [subject] captured on an ARRI Alexa with a Cooke anamorphic lens in 2.39:1 aspect ratio. Shallow depth of field produces beautiful oval bokeh in the background. Moody dramatic lighting from practical sources — a desk lamp, a window, neon signs — creates pools of light and deep shadows. Subtle film grain adds organic texture. Professional color grading with a teal and orange palette. The composition draws the eye along leading lines to the subject. Atmospheric haze softens the background. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Street Photography",
    prompts = {
      sd15 = {
        positive = "candid street photography of [subject], 35mm focal length, natural ambient lighting, urban environment, decisive moment composition, documentary style, gritty authentic atmosphere, sharp focus, black and white option, RAW photo",
        negative = "posed, staged, blurry, low quality, cartoon, painting, studio lighting, text, watermark",
      },
      sdxl = {
        positive = "candid street photography of [subject], shot on Leica M11 with 35mm f/1.4 Summilux lens, natural ambient urban lighting, dynamic decisive moment composition, documentary style with environmental context, gritty authentic metropolitan atmosphere, sharp focus on subject with environmental bokeh, high contrast, 8k resolution",
        negative = "posed, staged, blurry, low quality, worst quality, cartoon, painting, studio lighting, text, watermark, artificial",
      },
      flux = {
        positive = "Candid street photograph of [subject] captured on a Leica M11 with a 35mm f/1.4 Summilux lens. Natural ambient urban lighting — a mix of overcast sky and shop-front illumination. The composition captures a decisive moment with the subject in sharp focus against a gently blurred city environment. Documentary style with rich environmental context — signs, reflections, passing pedestrians. Gritty, authentic metropolitan atmosphere with high contrast and natural grain. 8K resolution.",
        negative = "",
      },
    },
  },

  { label = "Macro / Close-Up Detail",
    prompts = {
      sd15 = {
        positive = "extreme macro close-up photograph of [subject], 1:1 magnification, razor sharp focus on details, soft diffused lighting, beautiful bokeh background, vivid colors, ultra detailed textures, professional macro photography, RAW photo",
        negative = "blurry, out of focus, noisy, low quality, flat lighting, cartoon, painting, text, watermark",
      },
      sdxl = {
        positive = "extreme macro close-up photograph of [subject], shot on Canon EOS R5 with MP-E 65mm at 1:1 magnification, focus stacked for front-to-back sharpness, soft diffused ring light illumination, dreamy creamy bokeh background, vivid saturated colors, ultra detailed surface textures revealing microscopic details, professional macro photography, 8k resolution",
        negative = "blurry, out of focus, noisy, low quality, worst quality, flat lighting, cartoon, painting, text, watermark, motion blur",
      },
      flux = {
        positive = "Extreme macro close-up photograph of [subject] at 1:1 magnification. Shot on a Canon EOS R5 with an MP-E 65mm macro lens. Focus-stacked for razor-sharp detail from front to back. Soft diffused ring light reveals every microscopic surface texture — ridges, pores, iridescent reflections. The background dissolves into a dreamy, creamy bokeh of soft pastel tones. Vivid saturated colors pop against the blurred surroundings. 8K resolution.",
        negative = "",
      },
    },
  },

  -- ── Anime (sdxl_anime) ────────────────────────────────────────────
  { label = "Anime — Character Portrait",
    prompts = {
      sdxl_anime = {
        positive = "masterpiece, best quality, very aesthetic, absurdres, 1girl/1boy, [character description], detailed face, beautiful detailed eyes, looking at viewer, upper body, dynamic lighting, vibrant colors, sharp linework, anime illustration",
        negative = "worst quality, low quality, lowres, bad anatomy, bad hands, extra fingers, fewer fingers, cropped, username, watermark, blurry, jpeg artifacts, realistic, 3d",
      },
    },
  },

  { label = "Anime — Action Scene",
    prompts = {
      sdxl_anime = {
        positive = "masterpiece, best quality, very aesthetic, absurdres, 1girl/1boy, [character description], dynamic action pose, motion blur effects, battle scene, dramatic angle, intense expression, energy effects, speed lines, vibrant colors, detailed background, anime illustration",
        negative = "worst quality, low quality, lowres, bad anatomy, bad hands, extra fingers, fewer fingers, cropped, username, watermark, blurry, jpeg artifacts, realistic, 3d, stiff pose, static",
      },
    },
  },

  { label = "Anime — Slice of Life",
    prompts = {
      sdxl_anime = {
        positive = "masterpiece, best quality, very aesthetic, absurdres, 1girl/1boy, [character description], casual clothes, warm smile, cozy indoor setting, soft afternoon sunlight through window, gentle atmosphere, pastel color palette, everyday scene, detailed background, anime illustration",
        negative = "worst quality, low quality, lowres, bad anatomy, bad hands, extra fingers, fewer fingers, cropped, username, watermark, blurry, jpeg artifacts, realistic, 3d, dark, gloomy",
      },
    },
  },

  { label = "Anime — Fantasy / Isekai",
    prompts = {
      sdxl_anime = {
        positive = "masterpiece, best quality, very aesthetic, absurdres, 1girl/1boy, [character description], fantasy armor/robes, magical aura, epic landscape background, floating crystals, dramatic sky, glowing effects, intricate costume details, vibrant saturated colors, anime illustration",
        negative = "worst quality, low quality, lowres, bad anatomy, bad hands, extra fingers, fewer fingers, cropped, username, watermark, blurry, jpeg artifacts, realistic, 3d, modern clothing, mundane",
      },
    },
  },

  { label = "Anime — Chibi / Cute",
    prompts = {
      sdxl_anime = {
        positive = "masterpiece, best quality, very aesthetic, absurdres, chibi, 1girl/1boy, [character description], super deformed proportions, big head, small body, oversized eyes, cute expression, pastel colors, simple clean background, kawaii, adorable, anime illustration",
        negative = "worst quality, low quality, lowres, bad anatomy, realistic proportions, extra fingers, fewer fingers, cropped, username, watermark, blurry, jpeg artifacts, realistic, 3d, scary, horror",
      },
    },
  },

  { label = "Anime — Wallpaper / Key Visual",
    prompts = {
      sdxl_anime = {
        positive = "masterpiece, best quality, very aesthetic, absurdres, official art, key visual, 1girl/1boy, [character description], dynamic composition, detailed background with depth, cinematic lighting, volumetric light rays, rich color palette, ultra detailed, widescreen aspect ratio, anime illustration",
        negative = "worst quality, low quality, lowres, bad anatomy, bad hands, extra fingers, fewer fingers, cropped, username, watermark, blurry, jpeg artifacts, realistic, 3d, simple background, flat colors",
      },
    },
  },

  -- ── Cartoon / 3D (sdxl_cartoon) ───────────────────────────────────
  { label = "Cartoon — Character Design",
    prompts = {
      sdxl_cartoon = {
        positive = "disney style, 3d render, [character description], expressive face, big eyes, smooth skin, vibrant colors, cinematic lighting, character design sheet, clean background, Pixar quality, cartoon, high detail",
        negative = "photorealistic, blurry, deformed, low quality, dark, scary, bad anatomy, ugly",
      },
    },
  },

  { label = "Cartoon — Scene / Environment",
    prompts = {
      sdxl_cartoon = {
        positive = "disney pixar style, 3d render, [scene description], whimsical environment, vibrant saturated colors, warm cinematic lighting, volumetric god rays, stylized proportions, lush details, magical atmosphere, animated movie quality, high detail",
        negative = "photorealistic, blurry, deformed, low quality, dark, scary, flat lighting, dull colors, ugly",
      },
    },
  },

  { label = "Cartoon — Cute Animal / Mascot",
    prompts = {
      sdxl_cartoon = {
        positive = "disney pixar style, 3d render, cute [animal/mascot description], adorable round proportions, big expressive eyes, fluffy texture, soft pastel and vibrant colors, gentle studio lighting, clean simple background, mascot character design, Pixar quality, high detail",
        negative = "photorealistic, blurry, deformed, low quality, dark, scary, realistic proportions, ugly, menacing",
      },
    },
  },

  -- ── Flux Kontext (edit instructions) ──────────────────────────────
  { label = "Kontext — Change Outfit",
    prompts = {
      flux_kontext = {
        positive = "Change the subject's clothing to [describe new outfit]. Keep the face, hairstyle, pose, and background exactly the same. Only modify the clothing and accessories.",
        negative = "",
      },
    },
  },

  { label = "Kontext — Change Background",
    prompts = {
      flux_kontext = {
        positive = "Replace the background with [describe new background]. Keep the subject exactly the same — same pose, clothing, face, and lighting on the subject. Only change the environment behind them.",
        negative = "",
      },
    },
  },

  { label = "Kontext — Age / Appearance Edit",
    prompts = {
      flux_kontext = {
        positive = "Modify the subject's appearance: [describe change, e.g. 'make them look 20 years older' or 'add a beard']. Keep everything else — clothing, background, pose — exactly the same.",
        negative = "",
      },
    },
  },

  { label = "Kontext — Add Object / Element",
    prompts = {
      flux_kontext = {
        positive = "Add [describe object or element] to the scene. Place it [describe position]. Keep the subject and the rest of the scene completely unchanged.",
        negative = "",
      },
    },
  },
}

-- ═══════════════════════════════════════════════════════════════════════
-- Scene architecture mapping
-- ═══════════════════════════════════════════════════════════════════════
-- Maps a MODEL_PRESETS entry (arch + label) to a scene architecture
-- group key used to look up the correct prompt variant in SCENE_PRESETS.

local function scene_arch(model_arch, model_label)
  if model_arch == "flux1dev" or model_arch == "flux2klein" then
    return "flux"
  end
  if model_arch == "flux_kontext" then
    return "flux_kontext"
  end
  if model_arch == "sd15" then
    return "sd15"
  end
  -- SDXL sub-variants based on model label keywords
  if model_arch == "sdxl" or model_arch == "zit" then
    local lbl = model_label:lower()
    if lbl:find("anime") or lbl:find("noob") or lbl:find("nova anime")
       or lbl:find("wai") or lbl:find("pony") then
      return "sdxl_anime"
    end
    if lbl:find("disney") or lbl:find("cartoon") then
      return "sdxl_cartoon"
    end
    return "sdxl"
  end
  return "sdxl"  -- fallback
end

-- ═══════════════════════════════════════════════════════════════════════
-- Architecture -> compatible LoRA folder prefixes
-- ═══════════════════════════════════════════════════════════════════════
-- LoRAs are only compatible with the architecture they were trained for.
-- This mapping lets the UI filter the full server LoRA list down to only
-- those in folders matching the selected model's architecture.

local ARCH_LORA_PREFIXES = {
  sd15  = {},  -- no dedicated SD 1.5 LoRA folders currently
  sdxl  = {"SDXL\\", "Illustrious\\", "Illustrious-Pony\\", "Pony\\"},
  zit   = {"Z-Image-Turbo\\"},
}

local function starts_with(str, prefix)
  return str:sub(1, #prefix) == prefix
end

local function filter_loras_for_arch(all_loras, arch)
  local prefixes = ARCH_LORA_PREFIXES[arch]
  if not prefixes or #prefixes == 0 then return {} end
  local filtered = {}
  for _, lora in ipairs(all_loras) do
    for _, prefix in ipairs(prefixes) do
      if starts_with(lora, prefix) or lora == prefix:gsub("/$", "") then
        table.insert(filtered, lora)
        break
      end
    end
  end
  return filtered
end

-- ═══════════════════════════════════════════════════════════════════════
-- Preferences (stored in darktablerc)
-- ═══════════════════════════════════════════════════════════════════════
-- These appear in Darktable's preferences dialog under the Lua tab.
-- Users configure the ComfyUI server URL and processing timeout here.

dt.preferences.register(MODULE_NAME, "server_url", "string",
  _("ComfyUI server URL"),
  _("Full URL including port"),
  "http://127.0.0.1:8188")

dt.preferences.register(MODULE_NAME, "timeout", "integer",
  _("Timeout (seconds)"),
  _("Max wait for ComfyUI processing"),
  300, 10, 3600)

-- ═══════════════════════════════════════════════════════════════════════
-- HTTP communication via curl
-- ═══════════════════════════════════════════════════════════════════════
-- All HTTP communication uses os.execute("curl ...") rather than a Lua
-- HTTP library because Darktable's embedded Lua cannot reliably load
-- native C modules (luasocket etc.) across platforms. curl is available
-- on all target OSes (built into Windows 10+, macOS, and Linux).
--
-- Pattern for all requests:
--   1. Write request body to a temp file (avoids shell escaping JSON)
--   2. Invoke curl with -s (silent) and -o (output to temp file)
--   3. Read the response from the temp file
--   4. Clean up temp files
--
-- This avoids embedding large JSON in shell command strings and
-- sidesteps platform-specific quoting issues.

local sep = "/"

local function get_server()
  return dt.preferences.read(MODULE_NAME, "server_url", "string")
end

local function tmp_dir()
  return os.getenv("TEMP") or os.getenv("TMP") or os.getenv("TMPDIR") or "/tmp"
end

-- Security: strip double-quotes from strings before embedding in shell commands.
-- This prevents shell injection via user-controlled values (file paths, URLs).
-- Not a full sanitizer, but sufficient because all values are either:
--   (a) internal temp paths we control, or
--   (b) user-entered paths that get wrapped in double-quotes in the command.
local function shell_esc(s)
  if not s then return "" end
  return tostring(s):gsub('"', '')
end

-- GET request: fetch a URL and return the response body as a string.
-- Returns nil if the request fails or the response cannot be read.
local function curl_get(url)
  local tmp = tmp_dir() .. sep .. "comfyui_resp_" .. os.time() .. ".json"
  os.execute(string.format('curl -s -o "%s" "%s"', shell_esc(tmp), shell_esc(url)))
  local f = io.open(tmp, "r")
  if not f then return nil end
  local c = f:read("*all"); f:close(); os.remove(tmp)
  return c
end

-- POST JSON: write the JSON body to a temp file and use curl's @file syntax.
-- This avoids embedding potentially large JSON strings in the shell command,
-- which would break on special characters and hit command-line length limits.
local function curl_post_json(url, json_str)
  local tb = tmp_dir() .. sep .. "comfyui_body_" .. os.time() .. ".json"
  local tr = tmp_dir() .. sep .. "comfyui_presp_" .. os.time() .. ".json"
  local f = io.open(tb, "w"); f:write(json_str); f:close()
  os.execute(string.format('curl -s -X POST -H "Content-Type: application/json" -d @"%s" -o "%s" "%s"', shell_esc(tb), shell_esc(tr), shell_esc(url)))
  os.remove(tb)
  local rf = io.open(tr, "r")
  if not rf then return nil end
  local c = rf:read("*all"); rf:close(); os.remove(tr)
  return c
end

-- Upload an image file to ComfyUI's /upload/image endpoint via multipart form.
-- The "overwrite=true" flag lets us reuse filenames without conflicts.
local function curl_upload(url, filepath, filename)
  local tr = tmp_dir() .. sep .. "comfyui_up_" .. os.time() .. ".json"
  os.execute(string.format(
    'curl -s -X POST -F "image=@%s;filename=%s" -F "type=input" -F "overwrite=true" -o "%s" "%s"',
    shell_esc(filepath), shell_esc(filename), shell_esc(tr), shell_esc(url)))
  local f = io.open(tr, "r")
  if not f then return nil end
  local c = f:read("*all"); f:close(); os.remove(tr)
  return c
end

-- Download a file (image or video) from ComfyUI's /view endpoint.
local function curl_download(url, out)
  os.execute(string.format('curl -s -o "%s" "%s"', shell_esc(out), shell_esc(url)))
end

-- Minimal JSON value extractor: pull a single string value by key name.
-- Avoids a full JSON parser dependency for the simple responses we handle
-- (prompt_id, filename, subfolder, sha). Not suitable for nested objects.
local function json_val(s, key)
  return s and s:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

-- ── LoRA caching ───────────────────────────────────────────────────────
-- LoRA lists are fetched once from ComfyUI's /object_info endpoint and
-- cached in memory. The UI filters this cached list by architecture
-- whenever the user switches model presets, avoiding repeated HTTP calls.
local cached_all_loras = {}   -- full server list (unfiltered)
local cached_loras = {}       -- currently displayed (filtered by arch)

local function fetch_all_loras()
  local server = get_server()
  local r = curl_get(server .. "/object_info/LoraLoader")
  if not r then return {} end
  local names = {}
  -- Parse the lora_name array from the JSON
  local list_str = r:match('"lora_name"%s*:%s*%[(%[.-%])%s*,')
  if list_str then
    for name in list_str:gmatch('"([^"]*)"') do
      table.insert(names, name)
    end
  end
  cached_all_loras = names
  return names
end

local function get_current_arch()
  local idx = model_selector and model_selector.selected or 1
  local preset = MODEL_PRESETS[idx]
  return preset and preset.arch or "sdxl"
end

-- ═══════════════════════════════════════════════════════════════════════
-- Workflow JSON builders
-- ═══════════════════════════════════════════════════════════════════════
-- ComfyUI workflows are DAGs of processing nodes. Each node has a
-- string ID, a class_type (ComfyUI node name), and an inputs table.
-- Node-to-node connections use ["node_id", output_index] references.
--
-- These builder functions construct workflow JSON as formatted strings
-- rather than Lua tables because:
--   (a) Lua's table-to-JSON would need a serializer library
--   (b) String templates make the node graph visually obvious
--   (c) The JSON structure is static per workflow type (only values change)
--
-- Common pattern across all workflows:
--   LoadImage → ImageScale (down) → process → ImageScale (back up) → SaveImage
-- The scale-down/up preserves original resolution while keeping GPU memory
-- bounded by max_res_slider.

-- Escape a string for safe embedding inside a JSON double-quoted value.
-- Handles backslashes first (\ -> \\), then double-quotes (" -> \").
local function json_escape(s)
  s = s:gsub("\\", "\\\\")   -- backslash must be first
  s = s:gsub('"', '\\"')
  s = s:gsub("\n", "\\n")
  s = s:gsub("\r", "\\r")
  s = s:gsub("\t", "\\t")
  return s
end

-- Compute proportional downscale dimensions fitting within max_res,
-- rounding to multiples of 8 because SD/SDXL operate in latent space
-- where each pixel represents an 8x8 block of actual pixels.
local function compute_scale_dims(orig_w, orig_h, max_res)
  if max_res <= 0 or (orig_w <= max_res and orig_h <= max_res) then
    return orig_w, orig_h
  end
  local scale = max_res / math.max(orig_w, orig_h)
  local new_w = math.floor(orig_w * scale / 8) * 8
  local new_h = math.floor(orig_h * scale / 8) * 8
  if new_w < 8 then new_w = 8 end
  if new_h < 8 then new_h = 8 end
  return new_w, new_h
end

-- Read image dimensions safely (darktable image object)
local function get_image_dims(image)
  local w = (image and image.width) or 4096
  local h = (image and image.height) or 4096
  if w <= 0 then w = 4096 end
  if h <= 0 then h = 4096 end
  return w, h
end

-- Build an img2img workflow: Load checkpoint -> encode prompt -> load image ->
-- scale down -> VAE encode -> KSampler (denoise) -> VAE decode -> scale back up -> save.
-- Optional LoRA node (ID "100") is inserted between checkpoint and sampler.
-- Node ID convention: 1-10 = core pipeline, 90+ = utility (scale/size), 100+ = LoRA chain.
local function build_img2img_json(image_filename, preset, prompt, negative, seed,
                                   lora_name, lora_strength, scale_w, scale_h,
                                   cn_mode, cn_strength, cn_preprocessor, cn_model)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)
  local esc_ckpt = json_escape(preset.ckpt)

  -- Build LoRA node and references if a LoRA is selected
  local lora_node = ""
  local model_ref = '["1",0]'
  local clip_ref = '["1",1]'
  if lora_name and lora_name ~= "" and lora_name ~= "(none)" then
    local esc_lora = json_escape(lora_name)
    lora_node = string.format(
      ',"100":{"class_type":"LoraLoader","inputs":{"model":["1",0],"clip":["1",1],"lora_name":"%s","strength_model":%.2f,"strength_clip":%.2f}}',
      esc_lora, lora_strength or 1.0, lora_strength or 1.0)
    model_ref = '["100",0]'
    clip_ref = '["100",1]'
  end

  -- Determine KSampler conditioning references (may be overridden by ControlNet)
  local pos_ref = '["2",0]'
  local neg_ref = '["3",0]'
  local cn_nodes = ""

  if cn_mode and cn_mode ~= "off" and cn_model then
    local cn_image_ref = '["4",0]'  -- LoadImage output

    if cn_preprocessor then
      cn_nodes = cn_nodes .. string.format(
        ',"20":{"class_type":"%s","inputs":{"image":["4",0]}}', cn_preprocessor)
      cn_image_ref = '["20",0]'
    end

    cn_nodes = cn_nodes .. string.format(
      ',"21":{"class_type":"ControlNetLoader","inputs":{"control_net_name":"%s"}}',
      json_escape(cn_model))

    cn_nodes = cn_nodes .. string.format(
      ',"22":{"class_type":"ControlNetApplyAdvanced","inputs":{"positive":["2",0],"negative":["3",0],"control_net":["21",0],"image":%s,"strength":%.2f,"start_percent":0.0,"end_percent":1.0}}',
      cn_image_ref, cn_strength or 0.8)

    pos_ref = '["22",0]'
    neg_ref = '["22",1]'
  end

  return string.format([[
{"prompt":{
  "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}}%s%s,
  "2":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":%s}},
  "3":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":%s}},
  "4":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"GetImageSize+","inputs":{"image":["4",0]}},
  "91":{"class_type":"ImageScale","inputs":{"image":["4",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "5":{"class_type":"VAEEncode","inputs":{"pixels":["91",0],"vae":["1",2]}},
  "6":{"class_type":"KSampler","inputs":{
    "model":%s,"positive":%s,"negative":%s,
    "latent_image":["5",0],"seed":%d,"steps":%d,"cfg":%.1f,
    "sampler_name":"%s","scheduler":"%s","denoise":%.2f}},
  "7":{"class_type":"VAEDecode","inputs":{"samples":["6",0],"vae":["1",2]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["7",0],"upscale_method":"lanczos","width":["90",0],"height":["90",1],"crop":"disabled"}},
  "8":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_comfy"}}
}}]],
    esc_ckpt, lora_node, cn_nodes,
    esc_prompt, clip_ref,
    esc_neg, clip_ref,
    image_filename,
    scale_w, scale_h,
    model_ref, pos_ref, neg_ref,
    seed, preset.steps, preset.cfg,
    preset.sampler, preset.scheduler, preset.denoise)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Face Swap workflow builder (using saved face model)
-- ═══════════════════════════════════════════════════════════════════════
-- ReActor face swap using a pre-saved face model (.safetensors) on the
-- ComfyUI server. The user saves face models via ComfyUI's ReActor node
-- beforehand, then selects them here for batch face swapping.
-- This avoids uploading a source face image each time.

local cached_face_models = {}   -- face model files from ReActorLoadFaceModel
local cached_swap_models = {}   -- swap engine options from ReActorFaceSwap

local function fetch_face_models()
  local server = get_server()
  local r = curl_get(server .. "/object_info/ReActorLoadFaceModel")
  if not r then return {} end
  local models = {}
  local list_str = r:match('"face_model"%s*:%s*(%[.-%])')
  if list_str then
    for name in list_str:gmatch('"([^"]*)"') do
      if name ~= "none" then
        table.insert(models, name)
      end
    end
  end
  cached_face_models = models
  return models
end

local function fetch_swap_models()
  local server = get_server()
  local r = curl_get(server .. "/object_info/ReActorFaceSwap")
  if not r then return {} end
  local models = {}
  local list_str = r:match('"swap_model"%s*:%s*(%[.-%])')
  if list_str then
    for name in list_str:gmatch('"([^"]*)"') do
      table.insert(models, name)
    end
  end
  cached_swap_models = models
  return models
end

local function build_faceswap_model_json(image_filename, face_model_name, swap_model, scale_w, scale_h)
  local esc_face = json_escape(face_model_name)
  local esc_swap = json_escape(swap_model)

  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"GetImageSize+","inputs":{"image":["1",0]}},
  "91":{"class_type":"ImageScale","inputs":{"image":["1",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "2":{"class_type":"ReActorLoadFaceModel","inputs":{"face_model":"%s"}},
  "3":{"class_type":"ReActorFaceSwapOpt","inputs":{
    "enabled":true,"input_image":["91",0],"face_model":["2",0],
    "swap_model":"%s","facedetection":"retinaface_resnet50",
    "face_restore_model":"codeformer-v0.1.0.pth",
    "face_restore_visibility":1.0,"codeformer_weight":0.5,
    "options":["4",0],"face_boost":["5",0]}},
  "4":{"class_type":"ReActorOptions","inputs":{
    "input_faces_order":"left-right","input_faces_index":"0",
    "detect_gender_input":"no","source_faces_order":"left-right",
    "source_faces_index":"0","detect_gender_source":"no",
    "console_log_level":1,"restore_swapped_only":true}},
  "5":{"class_type":"ReActorFaceBoost","inputs":{
    "enabled":true,"boost_model":"codeformer-v0.1.0.pth",
    "interpolation":"Bicubic","visibility":1.0,
    "codeformer_weight":0.5,"restore_with_main_after":false}},
  "95":{"class_type":"ImageScale","inputs":{"image":["3",0],"upscale_method":"lanczos","width":["90",0],"height":["90",1],"crop":"disabled"}},
  "10":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_faceswap"}}
}}]], image_filename, scale_w, scale_h, esc_face, esc_swap)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Face Swap Direct (ReActor with source image file)
-- ═══════════════════════════════════════════════════════════════════════
-- Alternative to the saved-model approach: uploads a source face image
-- directly. Simpler setup but requires the source image each time.

local function build_faceswap_direct_json(target_filename, source_filename,
                                           swap_model, scale_w, scale_h)
  local esc_swap = json_escape(swap_model)

  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"GetImageSize+","inputs":{"image":["1",0]}},
  "91":{"class_type":"ImageScale","inputs":{"image":["1",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "3":{"class_type":"ReActorFaceSwap","inputs":{
    "enabled":true,"input_image":["91",0],"source_image":["2",0],
    "swap_model":"%s","facedetection":"retinaface_resnet50",
    "face_restore_model":"codeformer-v0.1.0.pth",
    "face_restore_visibility":1.0,"codeformer_weight":0.5,
    "detect_gender_input":"no","detect_gender_source":"no",
    "input_faces_index":"0","source_faces_index":"0","console_log_level":1}},
  "95":{"class_type":"ImageScale","inputs":{"image":["3",0],"upscale_method":"lanczos","width":["90",0],"height":["90",1],"crop":"disabled"}},
  "10":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_faceswap_direct"}}
}}]], target_filename, source_filename, scale_w, scale_h, esc_swap)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Save Face Model (ReActor)
-- ═══════════════════════════════════════════════════════════════════════
-- Builds a face embedding from a source image and saves it as a
-- .safetensors face model on the ComfyUI server. Uses
-- ReActorBuildFaceModel to extract the face embedding, then
-- ReActorSaveFaceModel to persist it. Saved models appear in the
-- "Face Model" dropdown after clicking Fetch.

local function build_save_face_model_json(image_filename, model_name, overwrite)
  local esc_name = json_escape(model_name)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"ReActorBuildFaceModel","inputs":{"compute_method":"CPU","face_model":["1",0]}},
  "3":{"class_type":"ReActorSaveFaceModel","inputs":{"face_model":["2",0],"save_mode":"%s","face_model_name":"%s"}}
}}]], image_filename, overwrite and "overwrite" or "skip-if-exists", esc_name)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Remove Background (rembg) — isnet-general-use, validated settings
-- ═══════════════════════════════════════════════════════════════════════
-- Simplest workflow: LoadImage → Image Rembg → SaveImage.
-- Settings hardcoded from validated Whimweaver REMBG pipeline.
-- DO NOT CHANGE — alpha_matting=true causes color fringing on edges.

local function build_rembg_json(image_filename)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"Image Rembg (Remove Background)","inputs":{
    "images":["1",0],"transparency":true,"model":"isnet-general-use",
    "post_processing":false,"only_mask":false,"alpha_matting":false,
    "alpha_matting_foreground_threshold":240,
    "alpha_matting_background_threshold":10,
    "alpha_matting_erode_size":10,"background_color":"none"}},
  "3":{"class_type":"SaveImage","inputs":{"images":["2",0],"filename_prefix":"darktable_rembg"}}
}}]], shell_esc(image_filename))
end

-- ═══════════════════════════════════════════════════════════════════════
-- Upscale 4x workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Uses UpscaleModelLoader + ImageUpscaleWithModel for model-based 4x
-- upscaling. No checkpoints or samplers needed — pure super-resolution.

local UPSCALE_MODELS = {
  { label = "4x UltraSharp",        file = "4x-UltraSharp.pth" },
  { label = "4x RealESRGAN",        file = "RealESRGAN_x4plus.pth" },
  { label = "4x NMKD Superscale",   file = "4x_NMKD-Superscale-SP_178000_G.pth" },
  { label = "4x Remacri",           file = "4x_foolhardy_Remacri.pth" },
  { label = "4x Anime",             file = "RealESRGAN_x4plus_anime_6B.pth" },
}

local function build_upscale_json(image_filename, model_name)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"UpscaleModelLoader","inputs":{"model_name":"%s"}},
  "3":{"class_type":"ImageUpscaleWithModel","inputs":{"upscale_model":["2",0],"image":["1",0]}},
  "4":{"class_type":"SaveImage","inputs":{"images":["3",0],"filename_prefix":"darktable_upscale"}}
}}]], shell_esc(image_filename), shell_esc(model_name))
end

-- ═══════════════════════════════════════════════════════════════════════
-- Object Removal (LaMa Inpaint) workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- LaMa (Large Mask Inpainting) removes objects using a mask image.
-- The mask's alpha channel (LoadImage output[1]) defines the removal area.
-- No checkpoint needed — LaMa is a self-contained inpainting model.

local function build_lama_json(image_filename, mask_filename)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "3":{"class_type":"LaMaInpaint","inputs":{"image":["1",0],"mask":["2",1]}},
  "4":{"class_type":"SaveImage","inputs":{"images":["3",0],"filename_prefix":"darktable_lama"}}
}}]], shell_esc(image_filename), shell_esc(mask_filename))
end

-- ═══════════════════════════════════════════════════════════════════════
-- Color Grading / LUT workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Applies a .cube LUT file via ImageApplyLUT+ node for cinematic color
-- grading. Strength controls blend between original and graded image.

local LUT_PRESETS = {
  { label = "Kodak 2383 Cinema",      file = "Rec709_Kodak_2383_D65.cube" },
  { label = "Fujifilm 3513DI Cinema",  file = "Rec709_Fujifilm_3513DI_D65.cube" },
  { label = "Kodak P3 Wide",          file = "DCI-P3_Kodak_2383_D65.cube" },
  { label = "ACES HDR",               file = "ACES_LMT_v0.1.1.cube" },
}

local function build_lut_json(image_filename, lut_file, strength)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"ImageApplyLUT+","inputs":{"image":["1",0],"lut_file":"%s","gamma_correction":true,"clip_values":true,"strength":%s}},
  "3":{"class_type":"SaveImage","inputs":{"images":["2",0],"filename_prefix":"darktable_lut"}}
}}]], shell_esc(image_filename), shell_esc(lut_file),
     string.format("%.2f", strength))
end

-- ═══════════════════════════════════════════════════════════════════════
-- Outpaint / Extend Canvas workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Uses ImagePadForOutpaint to extend the canvas, then inpaints the new
-- area using the first model preset. Padding values (left/right/top/bottom)
-- specify how many pixels to extend in each direction.

local function build_outpaint_json(image_filename, preset, prompt, negative, seed,
                                    pad_left, pad_right, pad_top, pad_bottom,
                                    scale_w, scale_h)
  local esc_ckpt = json_escape(preset.ckpt)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)

  return string.format([[
{"prompt":{
  "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "2":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["1",1]}},
  "3":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["1",1]}},
  "4":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "5":{"class_type":"ImagePadForOutpaint","inputs":{"image":["4",0],"left":%d,"top":%d,"right":%d,"bottom":%d,"feathering":40}},
  "6":{"class_type":"VAEEncode","inputs":{"pixels":["5",0],"vae":["1",2],"mask":["5",1]}},
  "7":{"class_type":"KSampler","inputs":{
    "model":["1",0],"positive":["2",0],"negative":["3",0],
    "latent_image":["6",0],"seed":%d,"steps":%d,"cfg":%.1f,
    "sampler_name":"%s","scheduler":"%s","denoise":1.0}},
  "8":{"class_type":"VAEDecode","inputs":{"samples":["7",0],"vae":["1",2]}},
  "9":{"class_type":"SaveImage","inputs":{"images":["8",0],"filename_prefix":"darktable_outpaint"}}
}}]],
    esc_ckpt,
    esc_prompt, esc_neg,
    image_filename,
    pad_left, pad_top, pad_right, pad_bottom,
    seed, preset.steps, preset.cfg,
    preset.sampler, preset.scheduler)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Style Transfer (IPAdapter) workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Uses IPAdapterUnifiedLoader with "PLUS (high strength)" preset to
-- transfer artistic style from a reference image. The checkpoint comes
-- from the first model preset for maximum compatibility.

local function build_style_transfer_json(image_filename, style_ref_filename,
                                          ckpt, prompt, negative, seed,
                                          strength, scale_w, scale_h)
  local esc_ckpt = json_escape(ckpt)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative or "blurry, deformed, low quality")

  return string.format([[
{"prompt":{
  "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "2":{"class_type":"IPAdapterUnifiedLoader","inputs":{
    "model":["1",0],"preset":"PLUS (high strength)"}},
  "3":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "4":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"ImageScale","inputs":{"image":["4",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "5":{"class_type":"IPAdapterAdvanced","inputs":{
    "model":["2",0],"ipadapter":["2",1],"image":["3",0],
    "weight":%.2f,"weight_type":"linear","combine_embeds":"concat",
    "start_at":0.0,"end_at":1.0,"embeds_scaling":"V only"}},
  "6":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["1",1]}},
  "7":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["1",1]}},
  "8":{"class_type":"VAEEncode","inputs":{"pixels":["90",0],"vae":["1",2]}},
  "9":{"class_type":"KSampler","inputs":{
    "model":["5",0],"positive":["6",0],"negative":["7",0],
    "latent_image":["8",0],"seed":%d,"steps":25,"cfg":7.0,
    "sampler_name":"dpmpp_2m_sde","scheduler":"karras","denoise":0.65}},
  "90b":{"class_type":"GetImageSize+","inputs":{"image":["4",0]}},
  "10":{"class_type":"VAEDecode","inputs":{"samples":["9",0],"vae":["1",2]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["10",0],"upscale_method":"lanczos","width":["90b",0],"height":["90b",1],"crop":"disabled"}},
  "11":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_style"}}
}}]],
    esc_ckpt,
    style_ref_filename,
    image_filename,
    scale_w, scale_h,
    strength,
    esc_prompt, esc_neg,
    seed)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Face Restore workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Uses ReActorRestoreFace node for standalone face restoration.
-- No checkpoint needed — works with dedicated face restoration models.

local FACE_RESTORE_MODELS = {
  { label = "CodeFormer (best)",     file = "codeformer-v0.1.0.pth" },
  { label = "GFPGAN v1.4 (fast)",   file = "GFPGANv1.4.pth" },
  { label = "GFPGAN v1.3",          file = "GFPGANv1.3.pth" },
  { label = "GPEN 1024 (high-res)", file = "GPEN-BFR-1024.onnx" },
  { label = "GPEN 512 (fast)",      file = "GPEN-BFR-512.onnx" },
  { label = "RestoreFormer++",       file = "RestoreFormer_PP.onnx" },
}

local function build_face_restore_json(image_filename, model, visibility, codeformer_weight)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"ReActorRestoreFace","inputs":{"image":["1",0],"facedetection":"retinaface_resnet50","model":"%s","visibility":%s,"codeformer_weight":%s}},
  "3":{"class_type":"SaveImage","inputs":{"images":["2",0],"filename_prefix":"darktable_facerestore"}}
}}]], shell_esc(image_filename), shell_esc(model),
     string.format("%.2f", visibility),
     string.format("%.2f", codeformer_weight))
end

-- ═══════════════════════════════════════════════════════════════════════
-- Photo Restoration Pipeline workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Full pipeline: Upscale + Face Restore + Sharpen in one pass.
-- Combines UpscaleModelLoader, ReActorRestoreFace, and ImageSharpen.

local PHOTO_RESTORE_UPSCALE_MODELS = {
  { label = "4x Remacri (restoration)", file = "4x_foolhardy_Remacri.pth" },
  { label = "4x RealESRGAN",           file = "RealESRGAN_x4plus.pth" },
  { label = "4x UltraSharp",           file = "4x-UltraSharp.pth" },
  { label = "8x NMKD Faces",           file = "8x_NMKD-Faces_160000_G.pth" },
}

local function build_photo_restore_json(image_filename, upscale_model, face_model, sharpen_alpha)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"UpscaleModelLoader","inputs":{"model_name":"%s"}},
  "3":{"class_type":"ImageUpscaleWithModel","inputs":{"upscale_model":["2",0],"image":["1",0]}},
  "4":{"class_type":"ReActorRestoreFace","inputs":{"image":["3",0],"facedetection":"retinaface_resnet50","model":"%s","visibility":1.0,"codeformer_weight":0.5}},
  "5":{"class_type":"ImageSharpen","inputs":{"image":["4",0],"sharpen_radius":1,"sigma":0.5,"alpha":%s}},
  "6":{"class_type":"SaveImage","inputs":{"images":["5",0],"filename_prefix":"darktable_photorestore"}}
}}]], shell_esc(image_filename), shell_esc(upscale_model),
     shell_esc(face_model),
     string.format("%.2f", sharpen_alpha))
end

-- ═══════════════════════════════════════════════════════════════════════
-- Detail Hallucination / Seed2VR workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Upscale + img2img at low denoise to add AI-hallucinated detail.
-- Requires a checkpoint for the KSampler pass.

local DETAIL_HALLUCINATE_LEVELS = {
  { label = "Subtle (preserve original)", denoise = 0.25, cfg = 4.0 },
  { label = "Moderate (add detail)",      denoise = 0.35, cfg = 5.0 },
  { label = "Strong (reimagine)",         denoise = 0.45, cfg = 6.0 },
  { label = "Extreme (creative)",         denoise = 0.60, cfg = 7.0 },
}

local function build_detail_hallucinate_json(image_filename, ckpt, prompt, negative, seed, cfg, denoise)
  local esc_ckpt = json_escape(ckpt)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)

  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"UpscaleModelLoader","inputs":{"model_name":"4x-UltraSharp.pth"}},
  "3":{"class_type":"ImageUpscaleWithModel","inputs":{"upscale_model":["2",0],"image":["1",0]}},
  "4":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "5":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["4",1]}},
  "6":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["4",1]}},
  "7":{"class_type":"VAEEncode","inputs":{"pixels":["3",0],"vae":["4",2]}},
  "8":{"class_type":"KSampler","inputs":{"model":["4",0],"positive":["5",0],"negative":["6",0],"latent_image":["7",0],"seed":%d,"steps":20,"cfg":%s,"sampler_name":"dpmpp_2m","scheduler":"karras","denoise":%s}},
  "9":{"class_type":"VAEDecode","inputs":{"samples":["8",0],"vae":["4",2]}},
  "10":{"class_type":"SaveImage","inputs":{"images":["9",0],"filename_prefix":"darktable_hallucinate"}}
}}]], shell_esc(image_filename),
     esc_ckpt, esc_prompt, esc_neg,
     seed,
     string.format("%.1f", cfg),
     string.format("%.2f", denoise))
end

-- ═══════════════════════════════════════════════════════════════════════
-- Colorize B&W Photo workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- ControlNet lineart-guided img2img to add color to B&W photos.
-- Auto-selects ControlNet model based on checkpoint architecture.

local function build_colorize_json(image_filename, ckpt, controlnet_name, prompt, negative, seed, strength, denoise)
  local esc_ckpt = json_escape(ckpt)
  local esc_cn = json_escape(controlnet_name)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)

  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"LineArtPreprocessor","inputs":{"image":["1",0]}},
  "3":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "4":{"class_type":"ControlNetLoader","inputs":{"control_net_name":"%s"}},
  "5":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["3",1]}},
  "6":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["3",1]}},
  "7":{"class_type":"ControlNetApplyAdvanced","inputs":{"positive":["5",0],"negative":["6",0],"control_net":["4",0],"image":["2",0],"strength":%s,"start_percent":0.0,"end_percent":1.0}},
  "8":{"class_type":"VAEEncode","inputs":{"pixels":["1",0],"vae":["3",2]}},
  "9":{"class_type":"KSampler","inputs":{"model":["3",0],"positive":["7",0],"negative":["7",1],"latent_image":["8",0],"seed":%d,"steps":25,"cfg":7.0,"sampler_name":"dpmpp_2m","scheduler":"karras","denoise":%s}},
  "10":{"class_type":"VAEDecode","inputs":{"samples":["9",0],"vae":["3",2]}},
  "11":{"class_type":"SaveImage","inputs":{"images":["10",0],"filename_prefix":"darktable_colorize"}}
}}]], shell_esc(image_filename),
     esc_ckpt, esc_cn, esc_prompt, esc_neg,
     string.format("%.2f", strength),
     seed,
     string.format("%.2f", denoise))
end

-- ═══════════════════════════════════════════════════════════════════════
-- mtb Face Swap (direct swap from source image)
-- ═══════════════════════════════════════════════════════════════════════
-- Uses the mtb (Mel's Toolkit Basics) ComfyUI node pack instead of
-- ReActor. Offers different analysis models (buffalo_l, antelopev2)
-- and supports face index selection for multi-face images.

local MTB_ANALYSIS_MODELS = {"buffalo_l", "antelopev2", "buffalo_m", "buffalo_sc"}
local MTB_SWAP_MODELS = {"inswapper_128.onnx", "inswapper_128_fp16.onnx"}

local function build_faceswap_mtb_json(target_filename, source_filename,
                                        analysis_model, swap_model, faces_index,
                                        scale_w, scale_h)
  local esc_analysis = json_escape(analysis_model)
  local esc_swap = json_escape(swap_model)
  local esc_idx = json_escape(faces_index or "0")

  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"GetImageSize+","inputs":{"image":["1",0]}},
  "91":{"class_type":"ImageScale","inputs":{"image":["1",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "92":{"class_type":"ImageScale","inputs":{"image":["2",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "3":{"class_type":"Load Face Analysis Model (mtb)","inputs":{"faceswap_model":"%s"}},
  "4":{"class_type":"Load Face Swap Model (mtb)","inputs":{"faceswap_model":"%s"}},
  "5":{"class_type":"Face Swap (mtb)","inputs":{"image":["91",0],"reference":["92",0],"faces_index":"%s","faceanalysis_model":["3",0],"faceswap_model":["4",0]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["5",0],"upscale_method":"lanczos","width":["90",0],"height":["90",1],"crop":"disabled"}},
  "10":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_faceswap_mtb"}}
}}]], target_filename, source_filename,
     scale_w, scale_h, scale_w, scale_h,
     esc_analysis, esc_swap, esc_idx)
end

local function process_faceswap_mtb(image, source_path, analysis_model, swap_model, faces_index)
  local server = get_server()

  dt.print(_("Exporting for mtb face swap..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading target to ComfyUI..."))
  local tgt_name = "dt_mtb_tgt_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, tgt_name)
  os.remove(path)

  dt.print(_("Uploading source face..."))
  local src_name = "dt_mtb_src_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", source_path, src_name)

  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_faceswap_mtb_json(tgt_name, src_name, analysis_model, swap_model, faces_index, scale_w, scale_h)

  dt.print(_("Queuing mtb face swap..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue mtb face swap")); return end

  dt.print(_("Processing mtb face swap..."))
  local results = wait_result(pid)
  if not results then dt.print(_("mtb face swap timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_mtb_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end
  dt.print(_("mtb face swap complete!"))
end

-- ═══════════════════════════════════════════════════════════════════════
-- Wan 2.2 Image-to-Video workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Wan 2.2 uses a dual-UNET architecture: a "high noise" model handles
-- early denoising steps (coarse structure), then hands off to a "low
-- noise" model for refinement. The switch point is controlled by
-- second_step (KSamplerAdvanced end_at_step / start_at_step).
--
-- Acceleration LoRAs (e.g. LightX2V) reduce inference from ~30 steps
-- to ~4 steps with minimal quality loss. Each noise model gets its own
-- acceleration LoRA.
--
-- Post-processing pipeline (optional):
--   RTXVideoSuperResolution -> RIFE VFI 2x interpolation
-- Output is saved as both H.264 MP4 and GIF.

local function wan_video_dims(src_w, src_h, target_long, align)
  -- Scale so longest side = target_long, round to align (Wan VAE needs multiples of 16)
  target_long = target_long or 720
  align = align or 16
  if src_w <= 0 or src_h <= 0 then return 832, 480 end
  local long = math.max(src_w, src_h)
  local scale = (long <= target_long) and 1.0 or (target_long / long)
  local w = math.max(align, math.floor(src_w * scale / align + 0.5) * align)
  local h = math.max(align, math.floor(src_h * scale / align + 0.5) * align)
  return w, h
end

local WAN_I2V_MODELS = {
  {
    label = "Wan I2V 14B (GGUF Q4)",
    high_model = "Wan\\wan2.2_i2v_high_noise_14B_Q4_K_S.gguf",
    low_model  = "Wan\\wan2.2_i2v_low_noise_14B_Q4_K_S.gguf",
    clip       = "umt5-xxl-encoder-Q8_0.gguf",
    vae        = "wan_2.1_vae.safetensors",
    steps = 30, second_step = 20, cfg = 5.0, shift = 8.0,
    lora_prefixes   = {"WAN\\", "Wan-2.2-I2V\\"},
    high_accel_lora = "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    low_accel_lora  = "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    accel_strength  = 1.0,
  },
  {
    label = "Wan I2V 14B (fp8)",
    high_model = "Wan\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    low_model  = "Wan\\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    clip       = "umt5-xxl-encoder-Q8_0.gguf",
    vae        = "wan_2.1_vae.safetensors",
    steps = 30, second_step = 20, cfg = 5.0, shift = 8.0,
    lora_prefixes   = {"WAN\\", "Wan-2.2-I2V\\"},
    high_accel_lora = "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    low_accel_lora  = "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    accel_strength  = 1.0,
  },
  {
    label = "Wan Enhanced NSFW SVI (fp8)",
    high_model = "Wan\\wan22EnhancedNSFWSVICamera_nsfwV2FP8H.safetensors",
    low_model  = "Wan\\wan22EnhancedNSFWSVICamera_nsfwV2FP8L.safetensors",
    clip       = "umt5-xxl-encoder-Q8_0.gguf",
    vae        = "wan_2.1_vae.safetensors",
    steps = 30, second_step = 20, cfg = 5.0, shift = 8.0,
    lora_prefixes   = {"WAN\\", "Wan-2.2-I2V\\"},
    high_accel_lora = "WAN\\SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors",
    low_accel_lora  = "WAN\\SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors",
    accel_strength  = 1.0,
  },
}

-- ── Wan Video Prompt Presets ────────────────────────────────────────────
-- Curated prompt templates for common video generation scenarios.
-- Each preset can recommend LoRAs via:
--   loras = {{name = "filename_suffix.safetensors", strength = 0.5}, ...}
-- These auto-populate the 3 LoRA content slots when the preset is selected.
-- NOTE: Content LoRAs apply to BOTH high and low noise models equally.
-- For noise-specific pairs, use the accel LoRA system in WAN_I2V_MODELS.
--
-- pingpong=true creates seamless loops by playing forward then backward.
-- cfg_override/steps_override let presets tune generation parameters
-- beyond the model defaults.
local WAN_VIDEO_PRESETS = {
  { label = "(none — manual prompt)",
    prompt = "", negative = "",
    cfg_override = nil, steps_override = nil, length_override = nil,
    pingpong = nil, loras = {} },
  -- Subtle Life / Living Portrait
  { label = "Living Portrait — subtle breathing & blinks",
    prompt = "a person subtly breathing, gentle micro-movements, natural blinking, soft chest rise and fall, slight head sway, lifelike idle animation, photorealistic, cinematic lighting, shallow depth of field",
    negative = "static, frozen, mannequin, jerky motion, fast movement, exaggerated motion, morphing, distorted face, blurry",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  { label = "Living Portrait — hair & fabric sway",
    prompt = "person with gently flowing hair, soft fabric movement in breeze, subtle clothes ripple, natural hair physics, serene expression, photorealistic portrait, gentle wind effect, cinematic",
    negative = "static, frozen, violent wind, tornado, exaggerated motion, morphing, distorted, blurry, unnatural movement",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  { label = "Living Portrait — smile & expression shift",
    prompt = "person transitioning from neutral to gentle warm smile, subtle expression change, natural facial animation, eyes lighting up, slight cheek movement, photorealistic, cinematic close-up",
    negative = "exaggerated expression, grotesque, morphing, distorted face, uncanny valley, rapid change, blurry, jerky",
    cfg_override = 5.5, steps_override = 30, length_override = 81, pingpong = false, loras = {} },
  -- Eye & Gaze Movement
  { label = "Eye Movement — looking around",
    prompt = "person slowly looking around, natural eye movement, gaze shifting left and right, subtle head tracking with eyes, realistic eye motion, photorealistic, cinematic portrait, detailed iris",
    negative = "cross-eyed, spinning eyes, rapid movement, jerky, deformed eyes, blurry, morphing face",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  -- Camera Motion
  { label = "Camera — slow zoom in",
    prompt = "slow cinematic zoom in, camera slowly pushing forward, gradual close-up, smooth dolly in, professional cinematography, steady camera, photorealistic, shallow depth of field",
    negative = "shaky camera, fast zoom, jerky, jump cut, distorted, blurry, fish-eye, warping",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = false, loras = {} },
  { label = "Camera — slow orbit / rotate",
    prompt = "slow cinematic camera orbit around subject, smooth rotating shot, gentle lateral dolly, parallax depth, professional steadicam, photorealistic, cinematic lighting",
    negative = "fast rotation, spinning, shaky, jerky, nausea-inducing, warping, morphing, distorted perspective",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  { label = "Camera — slow pan left/right",
    prompt = "slow cinematic camera pan from left to right, smooth horizontal tracking, gentle lateral movement, professional steadicam, photorealistic, cinematic widescreen composition",
    negative = "fast pan, jerky, shaky, vertical movement, zoom, warping, morphing, blurry motion",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  -- Nature / Environment
  { label = "Nature — flowing water & ripples",
    prompt = "gently flowing water, natural ripples and reflections, soft current movement, light dancing on water surface, serene river or stream, photorealistic, 4K, cinematic",
    negative = "static water, frozen, flood, tsunami, rapids, distorted reflections, blurry, noisy",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  { label = "Nature — clouds drifting",
    prompt = "slowly drifting clouds in sky, gentle cloud movement, soft atmospheric motion, time-lapse clouds, golden hour lighting, dramatic sky, photorealistic, cinematic landscape",
    negative = "static sky, storm, tornado, fast clouds, flickering, distorted, glitching, blurry",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  { label = "Nature — trees & foliage swaying",
    prompt = "trees gently swaying in breeze, leaves rustling, natural foliage movement, soft wind through branches, dappled sunlight, photorealistic forest or garden, cinematic",
    negative = "static trees, hurricane, violent wind, falling trees, distorted, morphing, blurry",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  { label = "Nature — fire / candle flicker",
    prompt = "gently flickering candle flame, warm firelight dancing, soft orange glow, natural fire movement, cozy atmosphere, photorealistic, cinematic lighting, shallow depth of field",
    negative = "explosion, inferno, out of control fire, static flame, distorted, blurry, flickering artifacts",
    cfg_override = 5.5, steps_override = 30, length_override = 81, pingpong = true,
    loras = {{name = "WanAnimate_relight_lora_fp16.safetensors", strength = 0.5}} },
  -- Body & Action
  { label = "Action — person walking forward",
    prompt = "person walking forward naturally, smooth gait, realistic body motion, natural arm swing, confident stride, photorealistic, cinematic tracking shot, urban or nature background",
    negative = "floating, sliding, moonwalk, jerky movement, distorted limbs, extra limbs, blurry, frozen",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = false, loras = {} },
  { label = "Action — person turning head",
    prompt = "person slowly turning head to face camera, natural head rotation, smooth neck movement, elegant turn, photorealistic portrait, cinematic, shallow depth of field",
    negative = "snapping head, jerky rotation, exorcist turn, 360 spin, morphing, distorted face, blurry, neck distortion",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = false, loras = {} },
  { label = "Action — dancing / rhythmic movement",
    prompt = "person dancing gracefully, smooth rhythmic body movement, fluid dance motion, natural choreography, expressive movement, photorealistic, cinematic, dynamic lighting",
    negative = "stiff, robotic, broken limbs, distorted body, extra arms, jerky, morphing, blurry",
    cfg_override = 6.0, steps_override = 30, length_override = 81, pingpong = false, loras = {} },
  -- Atmospheric / Mood
  { label = "Atmosphere — rain & droplets",
    prompt = "gentle rain falling, raindrops on surface, soft rain streaks, wet reflections, moody atmosphere, cinematic rain scene, photorealistic, shallow depth of field, bokeh raindrops",
    negative = "flood, hurricane, static, dry, no rain, distorted, blurry, noisy",
    cfg_override = 5.5, steps_override = 30, length_override = 81, pingpong = true,
    loras = {{name = "WanAnimate_relight_lora_fp16.safetensors", strength = 0.4}} },
  { label = "Atmosphere — snow falling",
    prompt = "gentle snowfall, soft snowflakes drifting down, peaceful winter scene, slow-motion snow, magical winter atmosphere, photorealistic, cinematic, cold breath visible",
    negative = "blizzard, avalanche, static, distorted, morphing, blurry, warm, summer",
    cfg_override = 5.5, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  { label = "Atmosphere — particles & dust motes",
    prompt = "floating dust particles in light beam, atmospheric dust motes, volumetric lighting, god rays with floating particles, dreamy atmosphere, photorealistic, cinematic",
    negative = "static, sandstorm, explosion, distorted, blurry, noisy, dirty",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true,
    loras = {{name = "WanAnimate_relight_lora_fp16.safetensors", strength = 0.5}} },
  { label = "Atmosphere — fog / mist rolling",
    prompt = "gentle fog rolling across scene, soft mist movement, atmospheric haze, moody fog tendrils, mysterious atmosphere, volumetric fog, photorealistic, cinematic lighting",
    negative = "static fog, dense smoke, explosion, fire, distorted, blurry, noisy",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true,
    loras = {{name = "WanAnimate_relight_lora_fp16.safetensors", strength = 0.4}} },
  -- Cinemagraph Loops
  { label = "Cinemagraph — ocean waves loop",
    prompt = "ocean waves gently crashing on shore, rhythmic wave motion, sea foam rolling in and out, peaceful beach, golden hour, photorealistic, cinematic, seamless loop",
    negative = "tsunami, storm, static ocean, frozen water, distorted, blurry, flickering",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  { label = "Cinemagraph — city lights & traffic",
    prompt = "city lights twinkling at night, gentle traffic light trails, urban nightscape, bokeh city lights, smooth car headlight streaks, photorealistic, cinematic night photography",
    negative = "static lights, crash, explosion, daytime, distorted, blurry, flickering",
    cfg_override = 5.5, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  -- Stylized / Creative
  { label = "Style — painting coming to life",
    prompt = "painted artwork slowly coming to life, brushstrokes animating, oil painting with subtle movement, artistic interpretation, painterly animation, museum piece moving, masterwork quality",
    negative = "photorealistic, modern, digital, jerky, glitching, distorted, morphing rapidly, flickering",
    cfg_override = 6.0, steps_override = 35, length_override = 81, pingpong = true, loras = {} },
  { label = "Style — anime / illustration loop",
    prompt = "anime character with subtle idle animation, gentle breathing, hair flowing, soft wind, anime art style, beautiful illustration, high quality animation, smooth 2D animation",
    negative = "3D, photorealistic, live action, jerky, static, low quality, distorted, blurry",
    cfg_override = 6.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  -- Product / Object
  { label = "Product — 360 turntable spin",
    prompt = "product slowly rotating on turntable, smooth 360 degree rotation, studio lighting, clean white background, professional product shot, photorealistic, commercial quality, even lighting",
    negative = "shaky, jerky rotation, wobble, distorted shape, changing product, morphing, blurry, dirty background",
    cfg_override = 5.5, steps_override = 30, length_override = 81, pingpong = false, loras = {} },
  { label = "Product — hero shot with sparkle",
    prompt = "product hero shot with sparkling light effects, lens flare, premium presentation, glamorous lighting sweep, commercial advertisement quality, photorealistic, cinematic",
    negative = "dull, flat lighting, dirty, damaged product, distorted, morphing, blurry",
    cfg_override = 6.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
  -- Animal / Pet
  { label = "Pet — cat / dog breathing & looking",
    prompt = "cute pet with subtle breathing, gentle ear twitches, natural animal idle motion, soft blinking, whisker movement, photorealistic animal portrait, cinematic, warm lighting",
    negative = "static, frozen, stuffed animal, toy, distorted, morphing, extra limbs, blurry",
    cfg_override = 5.0, steps_override = 30, length_override = 81, pingpong = true, loras = {} },
}

local cached_wan_loras = {}     -- all Wan\ loras from server
local cached_wan_loras_filtered = {}  -- subset shown in combos (per-preset filtered)

local function fetch_wan_loras()
  -- Fetch all LoRAs, then keep only those inside any wan-related subfolder.
  -- Adaptive: matches any folder starting with 'wan' (case-insensitive).
  local server = get_server()
  local r = curl_get(server .. "/object_info/LoraLoaderModelOnly")
  if not r then return {} end
  local loras = {}
  local list_str = r:match('"lora_name"%s*:%s*%[(%[.-%])%s*,')
  if list_str then
    for name in list_str:gmatch('"([^"]*)"') do
      local lower = name:lower()
      if lower:sub(1, 4) == "wan/" or lower:sub(1, 4) == "wan\\"
         or lower:sub(1, 4) == "wan-" then
        table.insert(loras, name)
      end
    end
  end
  cached_wan_loras = loras
  return loras
end

local function filter_wan_loras(all_loras, wan_preset)
  -- Filter cached Wan loras by the preset's lora_prefixes list.
  -- Falls back to matching all wan-related folders if no prefixes defined.
  local prefixes = (wan_preset and wan_preset.lora_prefixes)
                   or {"WAN\\", "Wan\\", "wan\\", "Wan-2.2-I2V\\"}
  local out = {}
  for _, name in ipairs(all_loras) do
    for _, prefix in ipairs(prefixes) do
      local alt_prefix = prefix:gsub("\\", "/")
      if name:sub(1, #prefix) == prefix or name:sub(1, #alt_prefix) == alt_prefix then
        table.insert(out, name)
        break
      end
    end
  end
  return out
end

-- ── Noise-specific LoRA detection and pairing ───────────────────────────
-- Wan LoRAs come in high/low noise pairs that must be applied to the
-- correct UNET model. These functions detect noise affinity from the
-- filename and auto-pair high/low counterparts so the user only needs
-- to select one and the other is found automatically.

local function detect_wan_lora_noise(lora_name)
  -- Detect whether a Wan LoRA targets the high or low noise model.
  -- Returns "high", "low", or "both" (universal).
  local basename = lora_name:match("\\([^\\]+)$") or lora_name:match("/([^/]+)$") or lora_name
  local low = basename:lower()

  local has_high = (low:find("high_noise") or low:find("highnoise")
                    or low:find("_high_") or low:find("_high%.")
                    or low:sub(1, 4) == "high" or basename:find("HIGH"))
  local has_low = (low:find("low_noise") or low:find("lownoise")
                   or low:find("_low_") or low:find("_low%.")
                   or low:sub(1, 3) == "low" or basename:find("LOW"))

  if has_high and not has_low then return "high" end
  if has_low and not has_high then return "low" end
  return "both"
end

local function find_wan_lora_pair(lora_name, target_noise)
  -- Given a LoRA name and target noise level ("high" or "low"),
  -- find the matching paired LoRA from cached_wan_loras.
  local basename = lora_name:match("\\([^\\]+)$") or lora_name:match("/([^/]+)$") or lora_name

  -- Build swap pairs
  local swaps
  if target_noise == "low" then
    swaps = {{"high_noise", "low_noise"}, {"highnoise", "lownoise"},
             {"_high_", "_low_"}, {"_high.", "_low."},
             {"HIGH", "LOW"}, {"High", "Low"}, {"high", "low"}}
  else
    swaps = {{"low_noise", "high_noise"}, {"lownoise", "highnoise"},
             {"_low_", "_high_"}, {"_low.", "_high."},
             {"LOW", "HIGH"}, {"Low", "High"}, {"low", "high"}}
  end

  local candidates = {}
  for _, pair in ipairs(swaps) do
    local old, new = pair[1], pair[2]
    if basename:lower():find(old:lower(), 1, true) then
      local swapped = basename:gsub(old:gsub("%%", "%%%%"), new)
      candidates[swapped:lower()] = true
      -- Also try case-insensitive sub
      local i, j = basename:lower():find(old:lower(), 1, true)
      if i then
        local swapped2 = basename:sub(1, i - 1) .. new .. basename:sub(j + 1)
        candidates[swapped2:lower()] = true
      end
    end
  end

  -- Search cached LoRAs for a match
  for _, server_lora in ipairs(cached_wan_loras) do
    local s_base = server_lora:match("\\([^\\]+)$") or server_lora:match("/([^/]+)$") or server_lora
    if candidates[s_base:lower()] then
      return server_lora
    end
  end
  return nil
end

local function wan_lora_concept_key(lora_name)
  -- Strip noise tokens from LoRA filename to get a concept key for pair grouping.
  local base = lora_name:match("\\([^\\]+)$") or lora_name:match("/([^/]+)$") or lora_name
  local low = base:lower()
  for _, token in ipairs({"_high_noise", "_low_noise", "high_noise", "low_noise",
                          "_highnoise", "_lownoise", "highnoise", "lownoise",
                          "_high_", "_low_", "_high.", "_low.",
                          "_high", "_low"}) do
    low = low:gsub(token:lower():gsub("%%", "%%%%"):gsub("%.", "%%."), "_")
  end
  low = low:gsub("_+", "_"):gsub("^_", ""):gsub("_$", "")
  return low
end

local function group_wan_lora_pairs(lora_names)
  -- Group LoRAs into high/low noise pairs by concept key.
  -- Returns list of {display=str, high=path|nil, low=path|nil}
  local groups = {}   -- concept_key → {high, low, both}
  local order = {}    -- preserve first-seen order
  for _, lname in ipairs(lora_names) do
    local noise = detect_wan_lora_noise(lname)
    local key = wan_lora_concept_key(lname)
    if not groups[key] then
      groups[key] = {high = nil, low = nil, both = nil}
      table.insert(order, key)
    end
    if noise == "high" then
      groups[key].high = lname
    elseif noise == "low" then
      groups[key].low = lname
    else
      groups[key].both = lname
    end
  end

  local pairs_list = {}
  for _, key in ipairs(order) do
    local g = groups[key]
    local function short(p) return p:match("\\([^\\]+)$") or p:match("/([^/]+)$") or p end
    if g.high and g.low then
      table.insert(pairs_list, {display = short(g.high) .. "  +  " .. short(g.low),
                                 high = g.high, low = g.low})
    elseif g.both then
      table.insert(pairs_list, {display = short(g.both),
                                 high = g.both, low = g.both})
    elseif g.high then
      table.insert(pairs_list, {display = short(g.high) .. " (high only)",
                                 high = g.high, low = nil})
    elseif g.low then
      table.insert(pairs_list, {display = short(g.low) .. " (low only)",
                                 high = nil, low = g.low})
    end
  end
  return pairs_list
end

-- Cached pair list for the current preset (used by send buttons)
local cached_wan_lora_pairs = {}

-- Build the Wan I2V workflow JSON. This is the most complex workflow in the plugin.
-- Node graph (simplified):
--   CLIPLoaderGGUF(1) -> text encoding(5,6)
--   UNETLoader(2) -> [LoRA chain 100+] -> ModelSamplingSD3(30) = high-noise model
--   UNETLoader(3) -> [LoRA chain 120+] -> ModelSamplingSD3(31) = low-noise model
--   LoadImage(7) -> [optional crop(15)] -> ImageScale(8) -> conditioning(40)
--   KSamplerAdvanced(50) high-noise -> KSamplerAdvanced(51) low-noise -> VAEDecode(60)
--   [optional RTX upscale(70)] -> [optional RIFE interpolation(71)]
--   VHS_VideoCombine(12) MP4 + VHS_VideoCombine(14) GIF
--
-- If end_image_filename is set, VACE start-to-end conditioning replaces
-- the standard WanImageToVideo node, enabling interpolation between frames.
local function build_wan_i2v_json(image_filename, wan_preset, prompt, negative, seed,
                                   width, height, length, steps, cfg, shift, second_step,
                                   loras, accel_enabled, accel_strength,
                                   upscale, upscale_factor, interpolate, pingpong, fps,
                                   crop_region, end_image_filename, vace_strength)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative or "")
  local esc_clip = json_escape(wan_preset.clip)
  local esc_high = json_escape(wan_preset.high_model)
  local esc_low = json_escape(wan_preset.low_model)
  local esc_vae = json_escape(wan_preset.vae)

  -- Auto-detect GGUF vs safetensors format to use the correct loader node.
  -- GGUF models use UnetLoaderGGUF (no weight_dtype param),
  -- safetensors models use UNETLoader (needs weight_dtype:"default").
  local is_gguf_high = wan_preset.high_model:match("%.gguf$") ~= nil
  local is_gguf_low  = wan_preset.low_model:match("%.gguf$") ~= nil
  local high_loader = is_gguf_high and "UnetLoaderGGUF" or "UNETLoader"
  local low_loader  = is_gguf_low  and "UnetLoaderGGUF" or "UNETLoader"
  local high_extra = is_gguf_high and "" or ',"weight_dtype":"default"'
  local low_extra  = is_gguf_low  and "" or ',"weight_dtype":"default"'

  -- Build LoRA chain nodes for both UNET models independently.
  -- LoRAs are chained: model -> lora100 -> lora101 -> ... -> final_ref
  -- High-noise model LoRAs use node IDs 100+, low-noise uses 120+.
  local lora_nodes = ""
  local high_model_ref = '["2",0]'
  local low_model_ref  = '["3",0]'

  -- Collect all LoRAs: accelerator first (speed priority), then user LoRAs
  local high_lora_list = {}
  local low_lora_list  = {}

  if accel_enabled then
    local astr = accel_strength or wan_preset.accel_strength or 1.0
    if wan_preset.high_accel_lora and wan_preset.high_accel_lora ~= "" then
      table.insert(high_lora_list, {name = wan_preset.high_accel_lora, str = astr})
    end
    if wan_preset.low_accel_lora and wan_preset.low_accel_lora ~= "" then
      table.insert(low_lora_list, {name = wan_preset.low_accel_lora, str = astr})
    end
  end

  -- User-selected content LoRAs — pre-computed pairs.
  -- Each entry has {high=path|nil, low=path|nil, strength=num}.
  -- Both paths are applied to their respective noise model.
  if loras then
    for _, lr in ipairs(loras) do
      if lr.high then
        table.insert(high_lora_list, {name = lr.high, str = lr.strength})
      end
      if lr.low then
        table.insert(low_lora_list, {name = lr.low, str = lr.strength})
      end
    end
  end

  -- High-noise model LoRA chain (nodes 100+)
  for i, lr in ipairs(high_lora_list) do
    local nid = tostring(99 + i)
    lora_nodes = lora_nodes .. string.format(
      ',"%s":{"class_type":"LoraLoaderModelOnly","inputs":{"model":%s,"lora_name":"%s","strength_model":%.2f}}',
      nid, high_model_ref, json_escape(lr.name), lr.str)
    high_model_ref = '["' .. nid .. '",0]'
  end

  -- Low-noise model LoRA chain (nodes 120+)
  for i, lr in ipairs(low_lora_list) do
    local nid = tostring(119 + i)
    lora_nodes = lora_nodes .. string.format(
      ',"%s":{"class_type":"LoraLoaderModelOnly","inputs":{"model":%s,"lora_name":"%s","strength_model":%.2f}}',
      nid, low_model_ref, json_escape(lr.name), lr.str)
    low_model_ref = '["' .. nid .. '",0]'
  end

  -- Post-processing nodes
  local pp_nodes = ""
  local video_ref = '["60",0]'

  if upscale then
    pp_nodes = pp_nodes .. string.format(
      ',"70":{"class_type":"RTXVideoSuperResolution","inputs":{"images":%s,"resize_type":"scale by multiplier","resize_type.scale":%.2f,"quality":"ULTRA"}}',
      video_ref, upscale_factor or 1.5)
    video_ref = '["70",0]'
  end

  if interpolate then
    pp_nodes = pp_nodes .. string.format(
      ',"71":{"class_type":"RIFE VFI","inputs":{"frames":%s,"ckpt_name":"rife49.pth","clear_cache_after_n_frames":10,"multiplier":2,"fast_mode":true,"ensemble":true,"scale_factor":1.0,"dtype":"float16","torch_compile":false,"batch_size":1}}',
      video_ref)
    video_ref = '["71",0]'
  end

  local output_fps = fps * (interpolate and 2 or 1)

  -- Optional crop node: if crop_region is provided, insert a crop between load and scale
  local crop_node = ""
  local scale_image_ref = '["7",0]'
  if crop_region then
    crop_node = string.format(
      ',"15":{"class_type":"ImageCrop","inputs":{"image":["7",0],"x":%d,"y":%d,"width":%d,"height":%d}}',
      crop_region.x, crop_region.y, crop_region.width, crop_region.height)
    scale_image_ref = '["15",0]'
  end

  -- Conditioning node 40: either WanImageToVideo or VACE start→end
  local conditioning_nodes
  if end_image_filename and end_image_filename ~= "" then
    local vs = vace_strength or 1.0
    conditioning_nodes = string.format(
      '"9":{"class_type":"LoadImage","inputs":{"image":"%s"}},' ..
      '"10":{"class_type":"ImageScale","inputs":{"image":["9",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},' ..
      '"41":{"class_type":"WanVideoVACEStartToEndFrame","inputs":{"num_frames":%d,"empty_frame_level":0.5,"start_image":["8",0],"end_image":["10",0]}},' ..
      '"40":{"class_type":"WanVaceToVideo","inputs":{"width":%d,"height":%d,"length":%d,"batch_size":1,"strength":%.2f,"positive":["5",0],"negative":["6",0],"vae":["4",0],"control_video":["41",0],"control_masks":["41",1]}}',
      json_escape(end_image_filename), width, height,
      length,
      width, height, length, vs)
  else
    conditioning_nodes = string.format(
      '"40":{"class_type":"WanImageToVideo","inputs":{"width":%d,"height":%d,"length":%d,"batch_size":1,"positive":["5",0],"negative":["6",0],"vae":["4",0],"start_image":["8",0]}}',
      width, height, length)
  end

  return string.format([[
{"prompt":{
  "1":{"class_type":"CLIPLoaderGGUF","inputs":{"clip_name":"%s","type":"wan"}},
  "2":{"class_type":"%s","inputs":{"unet_name":"%s"%s}},
  "3":{"class_type":"%s","inputs":{"unet_name":"%s"%s}},
  "4":{"class_type":"VAELoader","inputs":{"vae_name":"%s"}},
  "5":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["1",0]}},
  "6":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["1",0]}},
  "7":{"class_type":"LoadImage","inputs":{"image":"%s"}}%s,
  "8":{"class_type":"ImageScale","inputs":{"image":%s,"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}}%s,
  "30":{"class_type":"ModelSamplingSD3","inputs":{"model":%s,"shift":%.1f}},
  "31":{"class_type":"ModelSamplingSD3","inputs":{"model":%s,"shift":%.1f}},
  %s,
  "50":{"class_type":"KSamplerAdvanced","inputs":{"model":["30",0],"positive":["40",0],"negative":["40",1],"latent_image":["40",2],"add_noise":"enable","noise_seed":%d,"steps":%d,"cfg":%.1f,"sampler_name":"euler_ancestral","scheduler":"simple","start_at_step":0,"end_at_step":%d,"return_with_leftover_noise":"enable"}},
  "51":{"class_type":"KSamplerAdvanced","inputs":{"model":["31",0],"positive":["40",0],"negative":["40",1],"latent_image":["50",0],"add_noise":"disable","noise_seed":%d,"steps":%d,"cfg":1.0,"sampler_name":"euler_ancestral","scheduler":"simple","start_at_step":%d,"end_at_step":10000,"return_with_leftover_noise":"disable"}},
  "60":{"class_type":"VAEDecode","inputs":{"samples":["51",0],"vae":["4",0]}}%s,
  "12":{"class_type":"VHS_VideoCombine","inputs":{"images":%s,"frame_rate":%.1f,"loop_count":0,"filename_prefix":"darktable_wan_i2v","format":"video/h264-mp4","pingpong":%s,"save_output":true}},
  "14":{"class_type":"VHS_VideoCombine","inputs":{"images":%s,"frame_rate":%.1f,"loop_count":0,"filename_prefix":"darktable_wan_i2v_gif","format":"image/gif","pingpong":%s,"save_output":true}}
}}]],
    esc_clip,
    high_loader, esc_high, high_extra,
    low_loader, esc_low, low_extra,
    esc_vae,
    esc_prompt, esc_neg,
    image_filename, crop_node,
    scale_image_ref, width, height,
    lora_nodes,
    high_model_ref, shift,
    low_model_ref, shift,
    conditioning_nodes,
    seed, steps, cfg, second_step,
    seed, steps, second_step,
    pp_nodes,
    video_ref, output_fps, pingpong and "true" or "false",
    video_ref, output_fps, pingpong and "true" or "false")
end

-- ═══════════════════════════════════════════════════════════════════════
-- Klein Flux2 Distilled workflow
-- ═══════════════════════════════════════════════════════════════════════
-- Klein is a distilled variant of Flux2 that achieves good quality in
-- very few steps (typically 4). Uses a reference latent system where
-- the input image is VAE-encoded and used as conditioning alongside
-- the text prompt. The Flux2Scheduler computes appropriate sigma values.

local KLEIN_MODELS = {
  { label = "Klein 9B",        unet = "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",      clip = "qwen_3_8b_fp8mixed.safetensors" },
  { label = "Klein 4B (fp8)",  unet = "A-Flux\\flux-2-klein-4b-fp8.safetensors",         clip = "qwen_3_4b.safetensors" },
  { label = "Klein Base 4B",   unet = "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",    clip = "qwen_3_4b.safetensors" },
}

local function build_klein_img2img_json(image_filename, klein_model, prompt, seed,
                                         steps, guidance, scale_w, scale_h)
  local esc_prompt = json_escape(prompt)
  local esc_unet = json_escape(klein_model.unet)
  local esc_clip = json_escape(klein_model.clip or "qwen_3_8b_fp8mixed.safetensors")

  return string.format([[
{"prompt":{
  "1":{"class_type":"UNETLoader","inputs":{"unet_name":"%s","weight_dtype":"default"}},
  "2":{"class_type":"CLIPLoader","inputs":{"clip_name":"%s","type":"flux2","device":"default"}},
  "3":{"class_type":"VAELoader","inputs":{"vae_name":"flux2-vae.safetensors"}},
  "4":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["2",0]}},
  "5":{"class_type":"ConditioningZeroOut","inputs":{"conditioning":["4",0]}},
  "10":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"ImageScale","inputs":{"image":["10",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "11":{"class_type":"ImageScaleToTotalPixels","inputs":{"image":["90",0],"upscale_method":"nearest-exact","megapixels":1.0,"resolution_steps":1}},
  "12":{"class_type":"GetImageSize","inputs":{"image":["11",0]}},
  "13":{"class_type":"VAEEncode","inputs":{"pixels":["11",0],"vae":["3",0]}},
  "20":{"class_type":"ReferenceLatent","inputs":{"conditioning":["4",0],"latent":["13",0]}},
  "21":{"class_type":"ReferenceLatent","inputs":{"conditioning":["5",0],"latent":["13",0]}},
  "30":{"class_type":"CFGGuider","inputs":{"model":["1",0],"positive":["20",0],"negative":["21",0],"cfg":%.1f}},
  "31":{"class_type":"KSamplerSelect","inputs":{"sampler_name":"euler"}},
  "32":{"class_type":"Flux2Scheduler","inputs":{"steps":%d,"width":["12",0],"height":["12",1]}},
  "33":{"class_type":"RandomNoise","inputs":{"noise_seed":%d}},
  "34":{"class_type":"EmptyFlux2LatentImage","inputs":{"width":["12",0],"height":["12",1],"batch_size":1}},
  "40":{"class_type":"SamplerCustomAdvanced","inputs":{"noise":["33",0],"guider":["30",0],"sampler":["31",0],"sigmas":["32",0],"latent_image":["34",0]}},
  "50":{"class_type":"VAEDecode","inputs":{"samples":["40",0],"vae":["3",0]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["50",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "51":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_klein"}}
}}]],
    esc_unet,
    esc_clip,
    esc_prompt,
    image_filename,
    scale_w, scale_h,
    guidance,
    steps,
    seed,
    scale_w, scale_h)
end

-- ═══════════════════════════════════════════════════════════════════════
-- PuLID Flux workflow (PulidFlux* node family)
-- ═══════════════════════════════════════════════════════════════════════
-- PuLID (Pure and Lightning ID customization) transfers face identity
-- from a reference image onto a generated image. Unlike face swap, it
-- works at the model attention level (similar to IP-Adapter) rather
-- than post-processing face replacement. Runs on Flux architecture
-- with Klein 9B as the base UNET for fast generation.

local function build_pulid_flux_json(image_filename, face_filename, prompt, seed,
                                      strength, steps, guidance, scale_w, scale_h)
  local esc_prompt = json_escape(prompt)

  return string.format([[
{"prompt":{
  "1":{"class_type":"UNETLoader","inputs":{"unet_name":"A-Flux\\Flux2\\flux-2-klein-9b.safetensors","weight_dtype":"default"}},
  "2":{"class_type":"PulidFluxModelLoader","inputs":{"pulid_file":"pulid_flux_v0.9.1.safetensors"}},
  "3":{"class_type":"PulidFluxEvaClipLoader","inputs":{"provider":"cpu"}},
  "4":{"class_type":"PulidFluxInsightFaceLoader","inputs":{"provider":"CPU"}},
  "5":{"class_type":"CLIPLoader","inputs":{"clip_name":"qwen_3_8b_fp8mixed.safetensors","type":"flux2","device":"default"}},
  "6":{"class_type":"VAELoader","inputs":{"vae_name":"flux2-vae.safetensors"}},
  "7":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["5",0]}},
  "8":{"class_type":"ConditioningZeroOut","inputs":{"conditioning":["7",0]}},
  "9":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "15":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "16":{"class_type":"ApplyPulidFlux","inputs":{"model":["1",0],"pulid_flux":["2",0],"eva_clip":["3",0],"face_analysis":["4",0],"image":["15",0],"weight":%.2f,"start_at":0.0,"end_at":1.0}},
  "90":{"class_type":"ImageScale","inputs":{"image":["9",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "11":{"class_type":"ImageScaleToTotalPixels","inputs":{"image":["90",0],"upscale_method":"nearest-exact","megapixels":1.0,"resolution_steps":1}},
  "12":{"class_type":"GetImageSize","inputs":{"image":["11",0]}},
  "13":{"class_type":"VAEEncode","inputs":{"pixels":["11",0],"vae":["6",0]}},
  "20":{"class_type":"ReferenceLatent","inputs":{"conditioning":["7",0],"latent":["13",0]}},
  "21":{"class_type":"ReferenceLatent","inputs":{"conditioning":["8",0],"latent":["13",0]}},
  "30":{"class_type":"CFGGuider","inputs":{"model":["16",0],"positive":["20",0],"negative":["21",0],"cfg":%.1f}},
  "31":{"class_type":"KSamplerSelect","inputs":{"sampler_name":"euler"}},
  "32":{"class_type":"Flux2Scheduler","inputs":{"steps":%d,"width":["12",0],"height":["12",1]}},
  "33":{"class_type":"RandomNoise","inputs":{"noise_seed":%d}},
  "34":{"class_type":"EmptyFlux2LatentImage","inputs":{"width":["12",0],"height":["12",1],"batch_size":1}},
  "40":{"class_type":"SamplerCustomAdvanced","inputs":{"noise":["33",0],"guider":["30",0],"sampler":["31",0],"sigmas":["32",0],"latent_image":["34",0]}},
  "50":{"class_type":"VAEDecode","inputs":{"samples":["40",0],"vae":["6",0]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["50",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "51":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_pulid"}}
}}]],
    esc_prompt,
    image_filename,
    face_filename,
    strength,
    scale_w, scale_h,
    guidance,
    steps,
    seed,
    scale_w, scale_h)
end

-- ═══════════════════════════════════════════════════════════════════════
-- FaceID (IPAdapter) workflow
-- ═══════════════════════════════════════════════════════════════════════
-- IPAdapter FaceID uses InsightFace embeddings to inject face identity
-- into the generation process. Works with both SD1.5 and SDXL checkpoints.
-- The "FACEID PLUS V2" preset auto-loads the appropriate IPAdapter and
-- LoRA for the selected checkpoint architecture.

local FACEID_PRESETS = {
  {
    label = "SD1.5 — Juggernaut Reborn",
    ckpt = "SD-1.5\\juggernaut_reborn.safetensors",
    steps = 25, cfg = 7.0, denoise = 0.55,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
  },
  {
    label = "SD1.5 — Realistic Vision v5.1",
    ckpt = "SD-1.5\\realisticVisionV51_v51VAE.safetensors",
    steps = 25, cfg = 7.0, denoise = 0.55,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
  },
  {
    label = "SDXL — Juggernaut XL Ragnarok",
    ckpt = "SDXL\\Realistic\\juggernautXL_ragnarok.safetensors",
    steps = 30, cfg = 5.0, denoise = 0.55,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
  },
  {
    label = "SDXL — ZavyChroma XL v10",
    ckpt = "SDXL\\Realistic\\zavychromaxl_v100.safetensors",
    steps = 30, cfg = 5.0, denoise = 0.55,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
  },
  {
    label = "SDXL — JibMix Realistic v18",
    ckpt = "SDXL\\Realistic\\jibMixRealisticXL_v180SkinSupreme.safetensors",
    steps = 30, cfg = 5.0, denoise = 0.55,
    sampler = "dpmpp_2m_sde", scheduler = "karras",
  },
}

local function build_faceid_json(target_filename, face_ref_filename, preset,
                                  prompt, negative, seed, scale_w, scale_h,
                                  weight, weight_v2, denoise_override)
  local esc_ckpt = json_escape(preset.ckpt)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative or "blurry, deformed, bad anatomy")
  local steps = preset.steps
  local cfg = preset.cfg
  local denoise = denoise_override or preset.denoise
  local sampler = preset.sampler
  local scheduler = preset.scheduler
  local w = weight or 0.85
  local wv2 = weight_v2 or 1.0

  return string.format([[
{"prompt":{
  "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "2":{"class_type":"IPAdapterUnifiedLoaderFaceID","inputs":{
    "model":["1",0],"preset":"FACEID PLUS V2","lora_strength":0.6,"provider":"CUDA"}},
  "3":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "4":{"class_type":"IPAdapterFaceID","inputs":{
    "model":["2",0],"ipadapter":["2",1],"image":["3",0],
    "weight":%.2f,"weight_faceidv2":%.2f,"weight_type":"linear",
    "combine_embeds":"concat","start_at":0.0,"end_at":1.0,"embeds_scaling":"V only"}},
  "5":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["1",1]}},
  "6":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["1",1]}},
  "7":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"ImageScale","inputs":{"image":["7",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "8":{"class_type":"VAEEncode","inputs":{"pixels":["90",0],"vae":["1",2]}},
  "9":{"class_type":"KSampler","inputs":{
    "model":["4",0],"positive":["5",0],"negative":["6",0],
    "latent_image":["8",0],"seed":%d,"steps":%d,"cfg":%.1f,
    "sampler_name":"%s","scheduler":"%s","denoise":%.2f}},
  "90b":{"class_type":"GetImageSize+","inputs":{"image":["7",0]}},
  "11":{"class_type":"VAEDecode","inputs":{"samples":["9",0],"vae":["1",2]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["11",0],"upscale_method":"lanczos","width":["90b",0],"height":["90b",1],"crop":"disabled"}},
  "12":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_faceid"}}
}}]],
    esc_ckpt,
    face_ref_filename,
    w, wv2,
    esc_prompt,
    esc_neg,
    target_filename,
    scale_w, scale_h,
    seed, steps, cfg,
    sampler, scheduler, denoise)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Klein Flux2 + Reference Image workflow
-- ═══════════════════════════════════════════════════════════════════════
-- Extends the basic Klein workflow by adding a second reference image.
-- Both the target and reference images are VAE-encoded as ReferenceLatent
-- conditioning, allowing style/structure transfer from the reference.

local function build_klein_ref_json(image_filename, ref_filename, klein_model,
                                     prompt, seed, steps, guidance, scale_w, scale_h)
  local esc_prompt = json_escape(prompt)
  local esc_unet = json_escape(klein_model.unet)
  local esc_clip = json_escape(klein_model.clip or "qwen_3_8b_fp8mixed.safetensors")

  return string.format([[
{"prompt":{
  "1":{"class_type":"UNETLoader","inputs":{"unet_name":"%s","weight_dtype":"default"}},
  "2":{"class_type":"CLIPLoader","inputs":{"clip_name":"%s","type":"flux2","device":"default"}},
  "3":{"class_type":"VAELoader","inputs":{"vae_name":"flux2-vae.safetensors"}},
  "4":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["2",0]}},
  "5":{"class_type":"ConditioningZeroOut","inputs":{"conditioning":["4",0]}},
  "10":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"ImageScale","inputs":{"image":["10",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "11":{"class_type":"ImageScaleToTotalPixels","inputs":{"image":["90",0],"upscale_method":"nearest-exact","megapixels":1.0,"resolution_steps":1}},
  "12":{"class_type":"GetImageSize","inputs":{"image":["11",0]}},
  "13":{"class_type":"VAEEncode","inputs":{"pixels":["11",0],"vae":["3",0]}},
  "15":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "16":{"class_type":"ImageScaleToTotalPixels","inputs":{"image":["15",0],"upscale_method":"nearest-exact","megapixels":1.0,"resolution_steps":1}},
  "17":{"class_type":"VAEEncode","inputs":{"pixels":["16",0],"vae":["3",0]}},
  "20":{"class_type":"ReferenceLatent","inputs":{"conditioning":["4",0],"latent":["13",0]}},
  "21":{"class_type":"ReferenceLatent","inputs":{"conditioning":["5",0],"latent":["13",0]}},
  "30":{"class_type":"CFGGuider","inputs":{"model":["1",0],"positive":["20",0],"negative":["21",0],"cfg":%.1f}},
  "31":{"class_type":"KSamplerSelect","inputs":{"sampler_name":"euler"}},
  "32":{"class_type":"Flux2Scheduler","inputs":{"steps":%d,"width":["12",0],"height":["12",1]}},
  "33":{"class_type":"RandomNoise","inputs":{"noise_seed":%d}},
  "34":{"class_type":"EmptyFlux2LatentImage","inputs":{"width":["12",0],"height":["12",1],"batch_size":1}},
  "40":{"class_type":"SamplerCustomAdvanced","inputs":{"noise":["33",0],"guider":["30",0],"sampler":["31",0],"sigmas":["32",0],"latent_image":["34",0]}},
  "50":{"class_type":"VAEDecode","inputs":{"samples":["40",0],"vae":["3",0]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["50",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "51":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_klein_ref"}}
}}]],
    esc_unet,
    esc_clip,
    esc_prompt,
    image_filename,
    scale_w, scale_h,
    ref_filename,
    guidance,
    steps,
    seed,
    scale_w, scale_h)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Inpaint Refinement Presets (body part fixes with LoRA recommendations)
-- ═══════════════════════════════════════════════════════════════════════
-- Curated prompt/negative/parameter presets for common inpainting tasks.
-- Each preset specifies architecture-specific LoRAs (sdxl, zit, flux2klein)
-- that are automatically applied when the preset is selected.
--
-- Entries prefixed with "*" are creative/effect presets (style changes)
-- vs. the unprefixed entries which are corrective (fixing anatomy).
--
-- The `loras` table maps architecture keys to arrays of
-- {filename, model_strength, clip_strength} tuples.

local INPAINT_REFINEMENTS = {
  { label = "(none - manual prompt)", prompt = "", negative = "",
    denoise = nil, cfg_boost = 0, steps_override = nil, loras = {} },

  { label = "Fix Hands / Fingers",
    prompt = "perfect hands, five fingers on each hand, correct finger count, natural hand pose, realistic hand anatomy, detailed knuckles and nails",
    negative = "bad hands, extra fingers, fewer fingers, fused fingers, mutated hands, deformed fingers, missing fingers, ugly hands",
    denoise = 0.78, cfg_boost = 1.0, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Body\\HandFineTuning_XL.safetensors", 0.85, 0.85} } } },

  { label = "Fix Eyes / Iris Detail",
    prompt = "beautiful detailed eyes, perfect symmetrical eyes, clear sharp iris, realistic eye reflections, natural eye color, detailed eyelashes",
    negative = "asymmetric eyes, misaligned eyes, deformed iris, bad eyes, cross-eyed, glowing eyes, empty eyes, dead eyes",
    denoise = 0.65, cfg_boost = 0.5, steps_override = 28,
    loras = { sdxl = { {"SDXL\\Detail\\Eyes_High_Definition-000007.safetensors", 0.8, 0.8} } } },

  { label = "Refine Face / Portrait",
    prompt = "beautiful face, perfect facial features, natural skin texture, detailed facial structure, clear complexion, realistic portrait, symmetrical face",
    negative = "deformed face, ugly face, asymmetric face, blurry face, distorted features, bad proportions, uncanny valley, disfigured",
    denoise = 0.62, cfg_boost = 0.5, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.7, 0.7} },
              flux2klein = { {"Flux-2-Klein\\BFS_head_v1_flux-klein_9b_rank128.safetensors", 0.8, 0.8} } } },

  { label = "Fix Teeth / Mouth",
    prompt = "perfect teeth, natural white teeth, correct dental anatomy, properly aligned teeth, realistic mouth, natural lips, natural smile",
    negative = "bad teeth, missing teeth, extra teeth, deformed mouth, broken teeth, ugly teeth, distorted jaw, melted lips",
    denoise = 0.72, cfg_boost = 1.0, steps_override = 28,
    loras = { sdxl = { {"SDXL\\Detail\\Teefs-000007.safetensors", 0.9, 0.9} } } },

  { label = "Enhance Skin Texture",
    prompt = "detailed skin texture, realistic skin pores, natural skin surface, subsurface scattering, high definition skin, photorealistic skin detail",
    negative = "plastic skin, smooth plastic, waxy skin, artificial skin, airbrushed, oversmoothed, blurry skin",
    denoise = 0.45, cfg_boost = 0, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Detail\\skin texture style v4.safetensors", 0.75, 0.75} },
              flux2klein = { {"Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.7, 0.7} } } },

  { label = "Fix Hair / Hairstyle",
    prompt = "beautiful detailed hair, natural hair strands, realistic hair texture, individual hair strands visible, shiny healthy hair, volumetric hair",
    negative = "bad hair, plastic hair, merged hair clumps, bald patches, unnatural hair, wig-like, stiff hair, flat hair",
    denoise = 0.68, cfg_boost = 0.5, steps_override = 28,
    loras = { sdxl = { {"SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.65, 0.65} },
              flux2klein = { {"Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.6, 0.6} } } },

  { label = "Fix Feet / Toes",
    prompt = "perfect feet, five toes on each foot, correct toe count, natural foot anatomy, detailed toes and toenails, realistic feet",
    negative = "bad feet, extra toes, fused toes, deformed feet, missing toes, ugly feet, malformed toes, mutated feet",
    denoise = 0.75, cfg_boost = 1.0, steps_override = 30,
    loras = {} },

  { label = "Fix Body Anatomy",
    prompt = "correct human anatomy, natural body proportions, realistic body structure, proper limb length, natural muscle definition, anatomically correct",
    negative = "bad anatomy, extra limbs, missing limbs, deformed body, disproportionate, mutated, fused limbs, twisted torso",
    denoise = 0.72, cfg_boost = 1.0, steps_override = 30,
    loras = { flux2klein = { {"Flux-2-Klein\\Sliders\\klein_slider_anatomy_9B_v1.5.safetensors", 0.8, 0.8} } } },

  { label = "Fix Ears",
    prompt = "perfect ears, natural ear shape, detailed ear anatomy, realistic ear, symmetrical ears, correct ear placement",
    negative = "deformed ears, missing ears, extra ears, melted ears, oversized ears, badly shaped ears",
    denoise = 0.65, cfg_boost = 0.5, steps_override = 25,
    loras = {} },

  { label = "Fix Nose",
    prompt = "perfect nose, natural nose shape, detailed nostril anatomy, realistic nose, well-defined nose bridge, symmetrical nose",
    negative = "deformed nose, crooked nose, melted nose, flat nose, missing nose, blob nose",
    denoise = 0.62, cfg_boost = 0.5, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.5, 0.5} } } },

  { label = "Fix Neck / Shoulders",
    prompt = "natural neck, correct neck proportions, realistic shoulder anatomy, proper collarbone detail, well-defined shoulders",
    negative = "long neck, broken neck, deformed shoulders, missing neck, twisted neck, giraffe neck",
    denoise = 0.68, cfg_boost = 0.5, steps_override = 28,
    loras = { flux2klein = { {"Flux-2-Klein\\Sliders\\klein_slider_anatomy_9B_v1.5.safetensors", 0.6, 0.6} } } },

  { label = "Fix Clothing / Fabric",
    prompt = "detailed clothing, realistic fabric texture, natural cloth folds, proper garment draping, wrinkle detail, high quality textile",
    negative = "deformed clothing, melted fabric, missing clothing parts, bad cloth physics, floating clothing, clipping",
    denoise = 0.65, cfg_boost = 0.5, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.7, 0.7} },
              flux2klein = { {"Flux-2-Klein\\FTextureTransfer_F29B_V2.1.safetensors", 0.6, 0.6} } } },

  { label = "Fix Background / Scene",
    prompt = "detailed background, realistic environment, natural scenery, high quality background, sharp background detail, consistent perspective",
    negative = "blurry background, distorted background, bad perspective, floating objects, impossible architecture",
    denoise = 0.72, cfg_boost = 0.5, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.6, 0.6} },
              flux2klein = { {"Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5} } } },

  { label = "Sharpen / Add Detail",
    prompt = "ultra sharp, highly detailed, intricate details, enhanced textures, crisp edges, high definition, 8k quality",
    negative = "blurry, soft, low detail, smooth, flat, low resolution, out of focus, motion blur",
    denoise = 0.40, cfg_boost = 0, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.8, 0.8} },
              flux2klein = { {"Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.8, 0.8} } } },

  { label = "Boost Realism / Photo Quality",
    prompt = "photorealistic, RAW photo, DSLR quality, natural lighting, realistic texture, professional photography, film grain",
    negative = "cartoon, anime, painting, illustration, digital art, artificial, fake, CGI, unrealistic",
    denoise = 0.50, cfg_boost = 0.5, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.65, 0.65} },
              flux2klein = { {"Flux-2-Klein\\ultra_real_v2.safetensors", 0.7, 0.7} } } },

  { label = "Remove Artifacts / Clean Up",
    prompt = "clean image, artifact free, smooth transition, natural appearance, correct details, consistent style, seamless",
    negative = "artifacts, glitch, noise, compression artifacts, banding, jpeg artifacts, posterization, pixelation",
    denoise = 0.55, cfg_boost = 0, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.5, 0.5} },
              flux2klein = { {"Flux-2-Klein\\FK4B_Image_Repair_V1.safetensors", 0.8, 0.8} } } },

  -- CREATIVE / EFFECT RENDERS

  { label = "* Oily / Wet Skin Effect",
    prompt = "oily skin, wet skin, glistening skin, shiny skin, dewy skin, wet body, skin highlights, sweat, glossy complexion",
    negative = "dry skin, matte skin, powder, flat lighting, dull skin",
    denoise = 0.55, cfg_boost = 0.5, steps_override = 28,
    loras = { sdxl = { {"SDXL\\Oily skin style xl v1.safetensors", 0.85, 0.85} },
              zit = { {"Z-Image-Turbo\\Effect\\OiledSkin_Zit_Turbo_V1.safetensors", 0.85, 0.85} } } },

  { label = "* Sweat / Exertion Effect",
    prompt = "sweaty skin, beads of sweat, perspiration, glistening with sweat, exertion, post-workout, wet with sweat",
    negative = "dry skin, clean, powder, matte, cold, frozen",
    denoise = 0.55, cfg_boost = 0.5, steps_override = 28,
    loras = { sdxl = { {"SDXL\\Sweating my balls of mate.safetensors", 0.8, 0.8}, {"SDXL\\Oily skin style xl v1.safetensors", 0.4, 0.4} },
              zit = { {"Z-Image-Turbo\\Effect\\OiledSkin_Zit_Turbo_V1.safetensors", 0.7, 0.7} } } },

  { label = "* Water Droplets Effect",
    prompt = "water droplets on skin, water drops, dew drops, rain drops, wet surface, water beading, crystal clear droplets",
    negative = "dry, dusty, matte, powder, no water, arid",
    denoise = 0.58, cfg_boost = 0.5, steps_override = 28,
    loras = { zit = { {"Z-Image-Turbo\\Effect\\water_droplet_effect_zit_v1.safetensors", 0.9, 0.9} },
              sdxl = { {"SDXL\\Oily skin style xl v1.safetensors", 0.5, 0.5} } } },

  { label = "* Chrome / Metallic Skin",
    prompt = "chrome skin, metallic skin, liquid metal surface, silver chrome body, reflective metallic, mercury skin, polished chrome",
    negative = "matte, natural skin, realistic skin, dull, flat, organic, flesh tone",
    denoise = 0.75, cfg_boost = 1.0, steps_override = 30,
    loras = { sdxl = { {"Illustrious-Pony\\MetallicGoldSilver_skinbody_paint-000019.safetensors", 0.9, 0.9} },
              zit = { {"Z-Image-Turbo\\Effect\\93PXB5SENBFN8NEYSRYZA1DVX0-Chrome skin.safetensors", 0.9, 0.9} } } },

  { label = "* Cyborg / Robot Parts",
    prompt = "cyborg, mechanical parts, robotic body, cybernetic implants, exposed machinery, glowing circuits, metal plates, bionic",
    negative = "fully human, natural, organic only, no technology, medieval, rustic",
    denoise = 0.78, cfg_boost = 1.5, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Concept\\ARobotGirls_Concept-12.safetensors", 0.85, 0.85} },
              zit = { {"Z-Image-Turbo\\Effect\\Z-cyborg.safetensors", 0.9, 0.9} } } },

  { label = "* Gothic Dark Fantasy",
    prompt = "gothic dark fantasy, ethereal gothic elegance, dark atmosphere, moody shadows, dramatic dark lighting, mystical, dark beauty",
    negative = "bright, cheerful, colorful, sunny, cartoon, daytime, flat lighting",
    denoise = 0.68, cfg_boost = 1.0, steps_override = 30,
    loras = { sdxl = { {"Illustrious-Pony\\Ethereal_Gothic_Elegance.safetensors", 0.85, 0.85}, {"SDXL\\Style\\dark.safetensors", 0.5, 0.5} } } },

  { label = "* Chiaroscuro / Dramatic Lighting",
    prompt = "chiaroscuro lighting, dramatic light and shadow, Rembrandt lighting, high contrast, deep shadows, volumetric light, tenebrism",
    negative = "flat lighting, even lighting, overexposed, no shadows, bright everywhere, flash photography",
    denoise = 0.62, cfg_boost = 1.0, steps_override = 30,
    loras = { sdxl = { {"Illustrious-Pony\\Chiaroscuro  film style pony v1.safetensors", 0.85, 0.85}, {"SDXL\\Slider\\Dramatic Lighting Slider.safetensors", 0.6, 0.6} },
              zit = { {"Z-Image-Turbo\\Style\\zy_CinematicShot_zit.safetensors", 0.7, 0.7} } } },

  { label = "* Cinematic Film Look",
    prompt = "cinematic photography, film grain, anamorphic lens, cinematic color grading, movie still, depth of field, 35mm film",
    negative = "amateur, smartphone, flat, digital noise, harsh flash, oversaturated, snapshot",
    denoise = 0.55, cfg_boost = 0.5, steps_override = 30,
    loras = { sdxl = { {"Illustrious-Pony\\Cinematic Photography Style pony v1.safetensors", 0.8, 0.8} },
              zit = { {"Z-Image-Turbo\\Style\\zy_CinematicShot_zit.safetensors", 0.85, 0.85} } } },

  { label = "* Raw Camera / DSLR Photo",
    prompt = "RAW photo, DSLR, professional camera, natural lighting, shallow depth of field, bokeh, sharp focus, authentic colors",
    negative = "painting, illustration, digital art, CGI, airbrushed, overprocessed, HDR, cartoon",
    denoise = 0.50, cfg_boost = 0.5, steps_override = 28,
    loras = { sdxl = { {"SDXL\\Style\\RawCam_250_v1.safetensors", 0.8, 0.8} },
              zit = { {"Z-Image-Turbo\\Style\\SonyAlpha_ZImage.safetensors", 0.8, 0.8} } } },

  { label = "* Telephoto / 600mm Lens",
    prompt = "600mm telephoto lens, extreme bokeh, compressed perspective, subject isolation, creamy background blur, professional sports photography",
    negative = "wide angle, fisheye, everything in focus, deep DOF, distortion, flat",
    denoise = 0.52, cfg_boost = 0.5, steps_override = 28,
    loras = { zit = { {"Z-Image-Turbo\\Style\\600mm_Lens-V2_TriggerIs_600mm.safetensors", 0.9, 0.9} },
              sdxl = { {"SDXL\\Style\\epiCPhotoXL-Derp2.safetensors", 0.6, 0.6} } } },

  { label = "* Ghibli / Anime Painterly",
    prompt = "studio ghibli style, anime painting, hand-drawn animation, soft watercolor, whimsical, painterly anime, warm natural palette",
    negative = "photorealistic, 3d render, CGI, harsh shadows, sharp edges, dark, horror",
    denoise = 0.72, cfg_boost = 1.0, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Style\\ghibli_last.safetensors", 0.85, 0.85} },
              zit = { {"Z-Image-Turbo\\Style\\ZiTD3tailed4nime.safetensors", 0.8, 0.8} } } },

  { label = "* Fairy Tale / Fantasy Art",
    prompt = "fairy tale illustration, fantasy art, magical atmosphere, ethereal glow, enchanted, storybook illustration, dreamy, luminous",
    negative = "realistic, modern, urban, gritty, dark, horror, mundane, photographic",
    denoise = 0.70, cfg_boost = 1.0, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Style\\SDXLFaeTastic2400.safetensors", 0.85, 0.85} },
              zit = { {"Z-Image-Turbo\\Style\\z-image-illustria-01.safetensors", 0.7, 0.7} } } },

  { label = "* Glitch / Digital Error",
    prompt = "glitch art, digital corruption, pixel sorting, data moshing, RGB split, scan lines, corrupted image, VHS glitch",
    negative = "clean, perfect, smooth, natural, analog, traditional, high quality",
    denoise = 0.70, cfg_boost = 1.0, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Concept\\err0rFv1.6.safetensors", 0.85, 0.85} },
              zit = { {"Z-Image-Turbo\\Effect\\EFFECTSp001_zit.safetensors", 0.7, 0.7} } } },

  { label = "* Slime / Wet & Messy (WAM)",
    prompt = "covered in slime, green slime, gunge, wet and messy, dripping slime, splattered, gooey, viscous liquid",
    negative = "clean, dry, pristine, neat, tidy, powder, matte",
    denoise = 0.72, cfg_boost = 1.0, steps_override = 28,
    loras = {} },

  { label = "* Add Freckles",
    prompt = "freckles, natural freckles, sun-kissed freckles across cheeks, detailed skin with freckles, beauty marks, speckled skin",
    negative = "airbrushed, smooth porcelain skin, no marks, plastic skin, flawless, oversmoothed",
    denoise = 0.48, cfg_boost = 0, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Detail\\skin texture style v4.safetensors", 0.6, 0.6} } } },

  { label = "* Hyperdetailed Realism",
    prompt = "hyperdetailed, hyperrealistic, extreme detail, micro details, pore-level detail, ultra sharp focus, 8k resolution",
    negative = "soft, blurry, painterly, illustration, low detail, flat, smooth, anime",
    denoise = 0.52, cfg_boost = 1.0, steps_override = 35,
    loras = { sdxl = { {"Illustrious-Pony\\HyperdetailedRealismMJ7Pony.safetensors", 0.8, 0.8}, {"SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.5, 0.5} },
              zit = { {"Z-Image-Turbo\\Style\\Z-Image-Professional_Photographer_3500.safetensors", 0.7, 0.7} },
              flux2klein = { {"Flux-2-Klein\\K9bSR3al.safetensors", 0.7, 0.7}, {"Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5} } } },

  { label = "* 3D CG / Hi-Poly Render",
    prompt = "3d cg render, hi-poly 3d model, subsurface scattering, ray tracing, physically based rendering, octane render, studio lighting 3d",
    negative = "2d, flat, painting, sketch, hand-drawn, low poly, pixel art, photograph",
    denoise = 0.68, cfg_boost = 1.0, steps_override = 30,
    loras = { sdxl = { {"SDXL\\polyhedron_all_sdxl-000004.safetensors", 0.7, 0.7} },
              flux2klein = { {"Flux-2-Klein\\hipoly_3dcg_v7-epoch-000012.safetensors", 0.85, 0.85} } } },

  { label = "* Amateur / Candid Photo",
    prompt = "amateur photo, candid shot, casual snapshot, natural pose, real photography, unposed, everyday life, authentic",
    negative = "professional, studio, posed, perfect, airbrushed, magazine, retouched, glamour",
    denoise = 0.55, cfg_boost = 0, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Style\\zy_AmateurStyle_v2.safetensors", 0.85, 0.85} } } },

  { label = "* Alien / Extraterrestrial",
    prompt = "alien, extraterrestrial being, alien skin texture, otherworldly, sci-fi alien, bioluminescent, exotic alien anatomy",
    negative = "human, normal, mundane, realistic human, everyday, natural, earthly",
    denoise = 0.78, cfg_boost = 1.5, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Concept\\Aliens_AILF_SDXL.safetensors", 0.85, 0.85} } } },

  { label = "* Glow / Ethereal Light",
    prompt = "ethereal glow, soft radiant light, inner glow, angelic light, bioluminescent, aura, glowing skin, light particles",
    negative = "dark, shadowy, gloomy, flat lighting, harsh shadows, no glow, matte, dull",
    denoise = 0.58, cfg_boost = 0.5, steps_override = 28,
    loras = { flux2klein = { {"Flux-2-Klein\\Sliders\\klein_slider_glow.safetensors", 0.8, 0.8} } } },

  { label = "* Tentacles / Lovecraftian",
    prompt = "tentacles, eldritch tentacles, lovecraftian horror, organic tentacle growth, cosmic horror, deep sea creature",
    negative = "clean, normal, mundane, no tentacles, ordinary, cheerful, bright",
    denoise = 0.78, cfg_boost = 1.5, steps_override = 30,
    loras = { zit = { {"Z-Image-Turbo\\Effect\\Tentacledv1.safetensors", 0.85, 0.85} } } },

  { label = "* Spaceship / Sci-Fi Vehicle",
    prompt = "spaceship, sci-fi vehicle, futuristic spacecraft, space cruiser, starship, detailed hull plating, engine glow",
    negative = "medieval, fantasy, modern car, realistic, natural, low quality, blurry",
    denoise = 0.75, cfg_boost = 1.0, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Concept\\Space_ship_concept.safetensors", 0.85, 0.85} } } },

  { label = "* Portrait Enhancement (Klein)",
    prompt = "beautiful portrait, enhanced facial features, crisp details, professional portrait photography, catchlights in eyes, natural skin",
    negative = "blurry, soft, low resolution, artifacts, distorted, plastic, airbrushed, flat",
    denoise = 0.42, cfg_boost = 0, steps_override = 25,
    loras = { sdxl = { {"Illustrious-Pony\\StS_PonyXL_Detail_Slider_v1.4_iteration_3.safetensors", 0.7, 0.7} },
              flux2klein = { {"Flux-2-Klein\\upscale_portrait_9bklein.safetensors", 0.8, 0.8}, {"Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.4, 0.4} } } },

  { label = "* Color Tone / Grading (Klein)",
    prompt = "color graded, beautiful color palette, professional color correction, cinematic color tone, warm highlights cool shadows",
    negative = "flat colors, oversaturated, undersaturated, grey, washed out, neon, ugly colors",
    denoise = 0.40, cfg_boost = 0, steps_override = 25,
    loras = { sdxl = { {"SDXL\\Style\\sd_xl_offset_example-lora_1.0.safetensors", 0.6, 0.6} },
              flux2klein = { {"Flux-2-Klein\\Sliders\\ColorTone_Standard.safetensors", 0.7, 0.7} } } },

  { label = "* Anything to Realistic (Klein)",
    prompt = "photorealistic, real person, natural skin, realistic features, real photograph, authentic human, professional portrait",
    negative = "anime, cartoon, illustration, painting, 3d render, artificial, CGI, plastic, doll-like",
    denoise = 0.65, cfg_boost = 0.5, steps_override = 30,
    loras = { sdxl = { {"SDXL\\Style\\epiCRealnessRC1.safetensors", 0.8, 0.8} },
              flux2klein = { {"Flux-2-Klein\\Character\\Flux2Klein_AnythingtoRealCharacters.safetensors", 0.85, 0.85}, {"Flux-2-Klein\\K9bSR3al.safetensors", 0.5, 0.5} } } },
}

-- ═══════════════════════════════════════════════════════════════════════
-- Inpaint workflow (CheckpointLoaderSimple + SetLatentNoiseMask)
-- ═══════════════════════════════════════════════════════════════════════
-- Inpainting uses a standard checkpoint (not a dedicated inpaint model)
-- with SetLatentNoiseMask to constrain generation to masked regions.
-- The mask is loaded as a separate image, converted to a single-channel
-- mask via ImageToMask (red channel), and applied to the VAE-encoded latent.
-- White mask regions are regenerated; black regions are preserved.

local function build_inpaint_json(image_filename, mask_filename, preset, prompt, negative,
                                   seed, scale_w, scale_h, loras,
                                   cn_mode, cn_strength, cn_preprocessor, cn_model)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)
  local esc_ckpt = json_escape(preset.ckpt)

  -- Build LoRA chain: ckpt "1" -> lora100 -> lora101 -> ... -> final_model/clip
  -- Each LoRA node takes model+clip from the previous and outputs new refs.
  local lora_nodes = ""
  local model_ref = '["1",0]'
  local clip_ref  = '["1",1]'
  if loras and #loras > 0 then
    for i, lr in ipairs(loras) do
      local nid = tostring(99 + i)  -- "100", "101", ...
      lora_nodes = lora_nodes .. string.format(
        '  "%s":{"class_type":"LoraLoader","inputs":{"model":%s,"clip":%s,"lora_name":"%s","strength_model":%.2f,"strength_clip":%.2f}},\n',
        nid, model_ref, clip_ref,
        json_escape(lr[1]), lr[2], lr[3])
      model_ref = string.format('["%s",0]', nid)
      clip_ref  = string.format('["%s",1]', nid)
    end
  end

  -- Determine KSampler conditioning references (may be overridden by ControlNet)
  local pos_ref = '["2",0]'
  local neg_ref = '["3",0]'
  local cn_nodes = ""

  if cn_mode and cn_mode ~= "off" and cn_model then
    local cn_image_ref = '["4",0]'  -- LoadImage output (source image)

    if cn_preprocessor then
      cn_nodes = cn_nodes .. string.format(
        '  "20":{"class_type":"%s","inputs":{"image":["4",0]}},\n', cn_preprocessor)
      cn_image_ref = '["20",0]'
    end

    cn_nodes = cn_nodes .. string.format(
      '  "21":{"class_type":"ControlNetLoader","inputs":{"control_net_name":"%s"}},\n',
      json_escape(cn_model))

    cn_nodes = cn_nodes .. string.format(
      '  "22":{"class_type":"ControlNetApplyAdvanced","inputs":{"positive":["2",0],"negative":["3",0],"control_net":["21",0],"image":%s,"strength":%.2f,"start_percent":0.0,"end_percent":1.0}},\n',
      cn_image_ref, cn_strength or 0.8)

    pos_ref = '["22",0]'
    neg_ref = '["22",1]'
  end

  return string.format([[
{"prompt":{
  "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
%s%s  "2":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":%s}},
  "3":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":%s}},
  "4":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "5":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"GetImageSize+","inputs":{"image":["4",0]}},
  "91":{"class_type":"ImageScale","inputs":{"image":["4",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "92":{"class_type":"ImageScale","inputs":{"image":["5",0],"upscale_method":"nearest-exact","width":%d,"height":%d,"crop":"disabled"}},
  "52":{"class_type":"ImageToMask","inputs":{"image":["92",0],"channel":"red"}},
  "6":{"class_type":"VAEEncode","inputs":{"pixels":["91",0],"vae":["1",2]}},
  "7":{"class_type":"SetLatentNoiseMask","inputs":{"samples":["6",0],"mask":["52",0]}},
  "8":{"class_type":"KSampler","inputs":{
    "model":%s,"positive":%s,"negative":%s,
    "latent_image":["7",0],"seed":%d,"steps":%d,"cfg":%.1f,
    "sampler_name":"%s","scheduler":"%s","denoise":%.2f}},
  "9":{"class_type":"VAEDecode","inputs":{"samples":["8",0],"vae":["1",2]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["9",0],"upscale_method":"lanczos","width":["90",0],"height":["90",1],"crop":"disabled"}},
  "10":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_inpaint"}}
}}]],
    esc_ckpt,
    lora_nodes, cn_nodes,
    esc_prompt, clip_ref,
    esc_neg, clip_ref,
    image_filename,
    mask_filename,
    scale_w, scale_h,
    scale_w, scale_h,
    model_ref, pos_ref, neg_ref,
    seed, preset.steps, preset.cfg,
    preset.sampler, preset.scheduler, preset.denoise)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Batch Variations workflow builder (txt2img with batch_size > 1)
-- ═══════════════════════════════════════════════════════════════════════
-- Builds a txt2img workflow using EmptyLatentImage with batch_size > 1
-- to generate multiple variations in one pass. Reuses the img2img
-- checkpoint/prompt pipeline but generates from noise instead of encoding.

local function build_batch_txt2img_json(preset, prompt, negative, seed, lora_name, lora_strength, width, height, batch_count)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)
  local esc_ckpt = json_escape(preset.ckpt)

  -- Build LoRA node and references if a LoRA is selected
  local lora_node = ""
  local model_ref = '["1",0]'
  local clip_ref = '["1",1]'
  if lora_name and lora_name ~= "" and lora_name ~= "(none)" then
    local esc_lora = json_escape(lora_name)
    lora_node = string.format(
      ',"100":{"class_type":"LoraLoader","inputs":{"model":["1",0],"clip":["1",1],"lora_name":"%s","strength_model":%.2f,"strength_clip":%.2f}}',
      esc_lora, lora_strength or 1.0, lora_strength or 1.0)
    model_ref = '["100",0]'
    clip_ref = '["100",1]'
  end

  return string.format([[
{"prompt":{
  "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}}%s,
  "2":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":%s}},
  "3":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":%s}},
  "4":{"class_type":"EmptyLatentImage","inputs":{"width":%d,"height":%d,"batch_size":%d}},
  "5":{"class_type":"KSampler","inputs":{
    "model":%s,"positive":["2",0],"negative":["3",0],
    "latent_image":["4",0],"seed":%d,"steps":%d,"cfg":%.1f,
    "sampler_name":"%s","scheduler":"%s","denoise":1.0}},
  "6":{"class_type":"VAEDecode","inputs":{"samples":["5",0],"vae":["1",2]}},
  "7":{"class_type":"SaveImage","inputs":{"images":["6",0],"filename_prefix":"darktable_batch"}}
}}]],
    esc_ckpt, lora_node,
    esc_prompt, clip_ref,
    esc_neg, clip_ref,
    width, height, batch_count,
    model_ref,
    seed, preset.steps, preset.cfg,
    preset.sampler, preset.scheduler)
end

-- ═══════════════════════════════════════════════════════════════════════
-- ControlNet Suite workflow builder (shared by Sketch, Canny, Depth, Pose)
-- ═══════════════════════════════════════════════════════════════════════
-- Builds a ControlNet-guided generation workflow. The preprocessor class_type
-- and controlnet_model are swapped per mode (sketch, canny, depth, pose).

local CONTROLNET_MODELS = {
  sketch = {sd15 = "control_v11p_sd15_lineart_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
  canny  = {sd15 = "control_v11p_sd15_lineart_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
  depth  = {sd15 = "control_v11f1p_sd15_depth_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
  pose   = {sd15 = "control_v11p_sd15_openpose_fp16.safetensors", sdxl = "OpenPoseXL2.safetensors"},
}

-- ── ControlNet guide mode definitions (integrated into img2img/inpaint) ──
-- Each entry maps a UI label to its ComfyUI preprocessor class and a key
-- used to look up the correct ControlNet model per architecture.
local cn_guide_modes = {
  {label = "Off",                preprocessor = nil,                       key = "off"},
  {label = "Canny (edges)",      preprocessor = "CannyEdgePreprocessor",   key = "canny"},
  {label = "Depth (spatial)",    preprocessor = "MiDaS-DepthMapPreprocessor", key = "depth"},
  {label = "Lineart (drawing)",  preprocessor = "LineArtPreprocessor",     key = "lineart"},
  {label = "OpenPose (body)",    preprocessor = "DWPreprocessor",          key = "pose"},
  {label = "Scribble (sketch)",  preprocessor = "ScribblePreprocessor",    key = "scribble"},
  {label = "Tile (detail)",      preprocessor = nil,                       key = "tile"},
}

-- ControlNet model auto-selection by mode and architecture
local CN_MODEL_MAP = {
  canny    = {sd15 = "control_v11p_sd15_lineart_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors", zit = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
  depth    = {sd15 = "control_v11f1p_sd15_depth_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors", zit = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
  lineart  = {sd15 = "control_v11p_sd15_lineart_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors", zit = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
  pose     = {sd15 = "control_v11p_sd15_openpose_fp16.safetensors", sdxl = "OpenPoseXL2.safetensors", zit = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
  scribble = {sd15 = "control_v11p_sd15_lineart_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors", zit = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
  tile     = {sd15 = "control_v11f1e_sd15_tile.pth", sdxl = "SDXL\\ttplanetSDXLControlnet_Tile_v20Fp16.safetensors", zit = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"},
}

local function build_controlnet_json(uploaded_name, preprocessor, controlnet_model, ckpt, prompt, negative, seed, width, height, steps, cfg, sampler, scheduler, cn_strength)
  local esc_ckpt = json_escape(ckpt)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)
  local esc_cn = json_escape(controlnet_model)

  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"%s","inputs":{"image":["1",0]}},
  "3":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "4":{"class_type":"ControlNetLoader","inputs":{"control_net_name":"%s"}},
  "5":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["3",1]}},
  "6":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["3",1]}},
  "7":{"class_type":"ControlNetApplyAdvanced","inputs":{"positive":["5",0],"negative":["6",0],"control_net":["4",0],"image":["2",0],"strength":%s,"start_percent":0.0,"end_percent":1.0}},
  "8":{"class_type":"EmptyLatentImage","inputs":{"width":%d,"height":%d,"batch_size":1}},
  "9":{"class_type":"KSampler","inputs":{"model":["3",0],"positive":["7",0],"negative":["7",1],"latent_image":["8",0],"seed":%d,"steps":%d,"cfg":%s,"sampler_name":"%s","scheduler":"%s","denoise":1.0}},
  "10":{"class_type":"VAEDecode","inputs":{"samples":["9",0],"vae":["3",2]}},
  "11":{"class_type":"SaveImage","inputs":{"images":["10",0],"filename_prefix":"darktable_controlnet"}}
}}]], shell_esc(uploaded_name),
     preprocessor,
     esc_ckpt, esc_cn,
     esc_prompt, esc_neg,
     string.format("%.2f", cn_strength),
     width, height,
     seed, steps,
     string.format("%.1f", cfg),
     sampler, scheduler)
end

-- ═══════════════════════════════════════════════════════════════════════
-- IC-Light Relighting workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- Uses IC-Light (Intrinsic Compositing Light) to relight foreground objects.
-- Only works with SD1.5 models. The ICLightConditioning node produces
-- positive, negative and latent outputs for the KSampler.

local ICLIGHT_PRESETS = {
  {label = "Left Side Light", prompt = "soft light from the left side, dramatic side lighting, cinematic"},
  {label = "Right Side Light", prompt = "soft light from the right side, dramatic side lighting, cinematic"},
  {label = "Top Light", prompt = "overhead lighting, dramatic top light, cinematic shadows below"},
  {label = "Bottom Light", prompt = "light from below, dramatic uplighting, rim light on chin"},
  {label = "Back Light", prompt = "strong back lighting, rim light, silhouette edges, halo effect"},
  {label = "Front Soft", prompt = "soft frontal fill light, even illumination, studio portrait"},
  {label = "Golden Hour", prompt = "warm golden hour sunlight from the side, orange warm tones"},
  {label = "Blue Hour", prompt = "cool blue hour lighting, twilight, moody blue tones"},
  {label = "Neon", prompt = "colorful neon light, pink and blue, cyberpunk lighting"},
  {label = "Dramatic", prompt = "dramatic chiaroscuro lighting, strong contrast, film noir"},
}

local function build_iclight_json(uploaded_name, ckpt, prompt, negative, seed, multiplier)
  local esc_ckpt = json_escape(ckpt)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)

  -- ICLightConditioning.foreground expects LATENT, not IMAGE.
  -- VAEEncode the image first (node 10). model_path uses full subfolder path.
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "10":{"class_type":"VAEEncode","inputs":{"pixels":["1",0],"vae":["2",2]}},
  "3":{"class_type":"LoadAndApplyICLightUnet","inputs":{"model":["2",0],"model_path":"SD-1.5\\iclight_sd15_fc.safetensors"}},
  "4":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["2",1]}},
  "5":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["2",1]}},
  "6":{"class_type":"ICLightConditioning","inputs":{"positive":["4",0],"negative":["5",0],"vae":["2",2],"foreground":["10",0],"multiplier":%s}},
  "7":{"class_type":"KSampler","inputs":{"model":["3",0],"positive":["6",0],"negative":["6",1],"latent_image":["6",2],"seed":%d,"steps":20,"cfg":2.0,"sampler_name":"euler","scheduler":"normal","denoise":1.0}},
  "8":{"class_type":"VAEDecode","inputs":{"samples":["7",0],"vae":["2",2]}},
  "9":{"class_type":"SaveImage","inputs":{"images":["8",0],"filename_prefix":"darktable_iclight"}}
}}]], shell_esc(uploaded_name),
     esc_ckpt,
     esc_prompt, esc_neg,
     string.format("%.2f", multiplier),
     seed)
end

-- ═══════════════════════════════════════════════════════════════════════
-- SUPIR AI Restoration workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- SUPIR (Scale-Up Photo Restoration) uses the all-in-one SUPIR_Upscale
-- node which takes supir_model and sdxl_model path strings directly,
-- along with prompt, denoise (control_scale), and sampling parameters.

local function build_supir_json(uploaded_name, supir_model, sdxl_model, prompt, seed, denoise, steps)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"SUPIR_Upscale","inputs":{
    "supir_model":"%s","sdxl_model":"%s","image":["1",0],
    "seed":%d,"resize_method":"lanczos","scale_by":1.0,
    "steps":%d,"restoration_scale":-1.0,"cfg_scale":4.0,
    "a_prompt":"%s","n_prompt":"bad quality, blurry, messy",
    "s_churn":5,"s_noise":1.003,"control_scale":%.2f,
    "cfg_scale_start":4.0,"control_scale_start":0.0,
    "color_fix_type":"Wavelet","keep_model_loaded":false,
    "use_tiled_vae":true,"encoder_tile_size_pixels":512,
    "decoder_tile_size_latent":64,"sampler":"RestoreEDMSampler"}},
  "3":{"class_type":"SaveImage","inputs":{"images":["2",0],"filename_prefix":"darktable_supir"}}
}}]], shell_esc(uploaded_name), json_escape(supir_model), json_escape(sdxl_model),
     seed, steps, json_escape(prompt), denoise)
end

-- ═══════════════════════════════════════════════════════════════════════
-- SeedV2R Upscaler - presets, scales, and workflow builder
-- ═══════════════════════════════════════════════════════════════════════
-- SeedV2R uses a standard upscale-model + KSampler refinement pipeline.
-- At scale=1x the upscale model nodes are skipped entirely, feeding
-- the source image directly into VAEEncode for detail enhancement only.

local SEEDV2R_PRESETS = {
  {label = "Faithful (no hallucination)", denoise = 0.15, cfg = 3.0, steps = 15,
   prompt = "ultra detailed, sharp focus, high resolution, faithful reproduction",
   negative = "different content, changed, altered, blurry, soft"},
  {label = "Subtle (minimal)", denoise = 0.25, cfg = 4.0, steps = 20,
   prompt = "ultra detailed, sharp focus, high resolution, intricate details",
   negative = "blurry, low quality, soft, out of focus"},
  {label = "Moderate (add detail)", denoise = 0.35, cfg = 5.0, steps = 25,
   prompt = "ultra detailed, sharp focus, high resolution, rich texture, fine detail",
   negative = "blurry, low quality, soft, out of focus, low detail"},
  {label = "Strong (reimagine)", denoise = 0.45, cfg = 6.0, steps = 25,
   prompt = "masterpiece, ultra detailed, sharp focus, intricate details",
   negative = "blurry, low quality, worst quality, soft, out of focus"},
  {label = "Extreme (creative)", denoise = 0.60, cfg = 7.0, steps = 30,
   prompt = "masterpiece, best quality, ultra detailed, vivid colors, intricate",
   negative = "blurry, low quality, worst quality, deformed, bad anatomy"},
}

local SEEDV2R_SCALES = {
  {label = "1x (enhance only)", factor = 1.0},
  {label = "1.5x", factor = 1.5},
  {label = "2x (default)", factor = 2.0},
  {label = "3x", factor = 3.0},
  {label = "4x", factor = 4.0},
}

local function build_seedv2r_json(uploaded_name, upscale_model, ckpt, prompt, negative,
                                   seed, denoise, steps, cfg, sampler, scheduler,
                                   scale_factor, orig_w, orig_h)
  local esc_img = shell_esc(uploaded_name)
  local esc_ckpt = json_escape(ckpt)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)

  if scale_factor > 1.0 then
    -- Full pipeline: upscale model -> ImageScale to target -> KSampler refine
    local target_w = math.floor(orig_w * scale_factor + 0.5)
    local target_h = math.floor(orig_h * scale_factor + 0.5)
    local esc_upmodel = json_escape(upscale_model)
    return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"UpscaleModelLoader","inputs":{"model_name":"%s"}},
  "3":{"class_type":"ImageUpscaleWithModel","inputs":{"upscale_model":["2",0],"image":["1",0]}},
  "4":{"class_type":"ImageScale","inputs":{"image":["3",0],"width":%d,"height":%d,"upscale_method":"lanczos","crop":"disabled"}},
  "5":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "6":{"class_type":"CLIPTextEncode","inputs":{"clip":["5",1],"text":"%s"}},
  "7":{"class_type":"CLIPTextEncode","inputs":{"clip":["5",1],"text":"%s"}},
  "8":{"class_type":"VAEEncode","inputs":{"pixels":["4",0],"vae":["5",2]}},
  "9":{"class_type":"KSampler","inputs":{"model":["5",0],"positive":["6",0],"negative":["7",0],"latent_image":["8",0],"seed":%d,"steps":%d,"cfg":%.1f,"sampler_name":"%s","scheduler":"%s","denoise":%.2f}},
  "10":{"class_type":"VAEDecode","inputs":{"samples":["9",0],"vae":["5",2]}},
  "11":{"class_type":"SaveImage","inputs":{"images":["10",0],"filename_prefix":"darktable_seedv2r"}}
}}]], esc_img, esc_upmodel,
     target_w, target_h,
     esc_ckpt, esc_prompt, esc_neg,
     seed, steps, cfg, json_escape(sampler), json_escape(scheduler), denoise)
  else
    -- 1x: enhance only, no upscale model nodes
    return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "5":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
  "6":{"class_type":"CLIPTextEncode","inputs":{"clip":["5",1],"text":"%s"}},
  "7":{"class_type":"CLIPTextEncode","inputs":{"clip":["5",1],"text":"%s"}},
  "8":{"class_type":"VAEEncode","inputs":{"pixels":["1",0],"vae":["5",2]}},
  "9":{"class_type":"KSampler","inputs":{"model":["5",0],"positive":["6",0],"negative":["7",0],"latent_image":["8",0],"seed":%d,"steps":%d,"cfg":%.1f,"sampler_name":"%s","scheduler":"%s","denoise":%.2f}},
  "10":{"class_type":"VAEDecode","inputs":{"samples":["9",0],"vae":["5",2]}},
  "11":{"class_type":"SaveImage","inputs":{"images":["10",0],"filename_prefix":"darktable_seedv2r"}}
}}]], esc_img, esc_ckpt, esc_prompt, esc_neg,
     seed, steps, cfg, json_escape(sampler), json_escape(scheduler), denoise)
  end
end

-- ═══════════════════════════════════════════════════════════════════════
-- Core processing pipeline
-- ═══════════════════════════════════════════════════════════════════════
-- All process_* functions follow the same pattern:
--   1. export_to_temp()  -- darktable image -> PNG temp file
--   2. curl_upload()     -- upload to ComfyUI's /upload/image
--   3. build_*_json()    -- construct the workflow JSON
--   4. curl_post_json()  -- submit to ComfyUI's /prompt endpoint
--   5. wait_result()     -- poll /history until outputs appear
--   6. curl_download()   -- fetch result images/videos
--   7. dt.database.import() -- import results into darktable library
--
-- Each step uses dt.print() for user feedback in darktable's status bar.

-- Forward declarations for GUI widgets referenced by process functions.
-- In Lua, a local is only in scope from its declaration onward.
-- These are assigned later in the GUI section; without these forward
-- declarations, all process functions would get nil when reading
-- max_res_slider, causing silent crashes in darktable callbacks.
local max_res_slider
local status_label

-- ── Workflow queue guard ─────────────────────────────────────────────
-- Prevents double-clicks from queuing multiple workflows simultaneously.
-- Darktable Lua runs callbacks on the main thread, but rapid clicks can
-- still stack multiple process_* calls before the first one returns.
local _processing = false

local function acquire_processing_lock()
  if _processing then
    dt.print(_("A workflow is already running — please wait"))
    return false
  end
  _processing = true
  return true
end

local function release_processing_lock()
  _processing = false
end

-- Export a darktable image to a temporary PNG file for upload.
-- Returns (file_path, file_name) or (nil, nil) on failure.
local function export_to_temp(image)
  local dir = tmp_dir()
  local fname = "dt_comfy_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  local path = dir .. sep .. fname
  local exp = dt.new_format("png")
  exp.bpp = 8
  exp:write_image(image, path)
  -- verify file was written
  local f = io.open(path, "r")
  if not f then return nil, nil end
  f:close()
  return path, fname
end

-- ── Splash screen (visual progress indicator) ──────────────────────────
-- While ComfyUI processes a workflow (which can take minutes for video),
-- a Tkinter splash window is shown via an external Python process.
-- Communication uses a lock file: the splash stays open while the file
-- exists and closes when it's deleted. This avoids any IPC complexity.

local function launch_splash()
  local lock_file = tmp_dir() .. sep .. "comfyui_splash_" .. os.time() .. "_" .. math.random(1000,9999) .. ".lock"
  local f = io.open(lock_file, "w")
  if f then f:write("1"); f:close() end

  -- Locate splash.py relative to this Lua file's directory
  local script_dir = debug.getinfo(1, "S").source:match("@?(.*[/\\])") or ""
  local splash_script = script_dir .. "splash.py"

  -- Launch as a background process (start /B on Windows, & on Unix)
  if dt.configuration.running_os == "windows" then
    os.execute(string.format('start /B pythonw "%s" "%s"', shell_esc(splash_script), shell_esc(lock_file)))
  else
    os.execute(string.format('python3 "%s" "%s" &', shell_esc(splash_script), shell_esc(lock_file)))
  end
  return lock_file
end

local function kill_splash(lock_file)
  -- Deleting the lock file signals the splash Python process to exit
  if lock_file then
    os.remove(lock_file)
  end
end

-- Poll ComfyUI's /history endpoint until the workflow completes or times out.
-- Returns a list of output filenames (PNG/JPG only) or nil on timeout.
-- Shows a splash screen during the wait and polls every 2 seconds.
local function wait_result(prompt_id, timeout_override)
  local server = get_server()
  local timeout = timeout_override or dt.preferences.read(MODULE_NAME, "timeout", "integer")
  local deadline = os.time() + timeout
  local lock_file = launch_splash()

  while os.time() < deadline do
    -- ComfyUI adds the prompt_id to /history once all nodes complete
    local r = curl_get(server .. "/history/" .. prompt_id)
    if r and r:find(prompt_id) then
      local fnames = {}
      for fn in r:gmatch('"filename"%s*:%s*"([^"]*)"') do
        if fn:match("%.png$") or fn:match("%.jpg$") then
          table.insert(fnames, fn)
        end
      end
      if #fnames > 0 then 
        kill_splash(lock_file)
        return fnames 
      end
    end
    dt.control.sleep(2000)
  end
  kill_splash(lock_file)
  return nil
end

-- Extended result poller for Wan I2V: returns ALL output files including
-- videos (MP4, WebM) and GIFs, not just images. Each entry includes
-- the subfolder path needed to construct the correct /view download URL.
local function wait_result_all(prompt_id, timeout_override)
  local server = get_server()
  local timeout = timeout_override or 600
  local deadline = os.time() + timeout
  while os.time() < deadline do
    local r = curl_get(server .. "/history/" .. prompt_id)
    if r and r:find(prompt_id) then
      local results = {}
      -- Extract all files from "images" and "gifs" arrays
      -- Parse subfolder context for each filename
      for fn in r:gmatch('"filename"%s*:%s*"([^"]*)"') do
        if fn:match("%.png$") or fn:match("%.jpg$") or
           fn:match("%.gif$") or fn:match("%.mp4$") or fn:match("%.webm$") then
          -- Try to find the subfolder for this file
          local sf = ""
          local pattern = '"filename"%s*:%s*"' .. fn:gsub("([%.%-%+])", "%%%1") .. '"%s*,%s*"subfolder"%s*:%s*"([^"]*)"'
          local found_sf = r:match(pattern)
          if not found_sf then
            -- Try reversed order
            pattern = '"subfolder"%s*:%s*"([^"]*)"%s*,%s*"filename"%s*:%s*"' .. fn:gsub("([%.%-%+])", "%%%1") .. '"'
            found_sf = r:match(pattern)
          end
          if found_sf then sf = found_sf end
          table.insert(results, {filename = fn, subfolder = sf})
        end
      end
      if #results > 0 then return results end
    end
    dt.control.sleep(2000)
  end
  return nil
end

-- ── img2img processing ─────────────────────────────────────────────────
local function process_image(image, preset, prompt, negative, lora_name, lora_strength,
                              cn_mode, cn_strength, cn_preprocessor, cn_model)
  local server = get_server()

  dt.print(string.format(_("Exporting for %s..."), preset.label))
  local path, fname = export_to_temp(image)
  if not path then
    dt.print(_("Export failed")); return
  end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_img2img_json(upload_name, preset, prompt, negative, seed,
                                      lora_name, lora_strength, scale_w, scale_h,
                                      cn_mode, cn_strength, cn_preprocessor, cn_model)

  dt.print(_("Queuing prompt..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then
    dt.print(_("Failed to queue prompt")); return
  end

  dt.print(string.format(_("Processing with %s..."), preset.label))
  local results = wait_result(pid)
  if not results then
    dt.print(_("Timed out or failed")); return
  end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_result_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end

  dt.print(string.format(_("Done: %s"), preset.label))
end

-- ── Face swap (saved model) processing ──────────────────────────────────
local function process_faceswap_model(image, face_model_name, swap_model)
  local server = get_server()

  dt.print(_("Exporting for face swap..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_fs_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_faceswap_model_json(upload_name, face_model_name, swap_model, scale_w, scale_h)

  dt.print(_("Queuing face swap..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue face swap")); return end

  dt.print(_("Processing face swap..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Face swap timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_fs_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end
  dt.print(_("Face swap complete!"))
end

-- ── Save face model processing ──────────────────────────────────────────
-- Exports the selected image, uploads it, builds a face model from it,
-- and saves the model on the ComfyUI server as a .safetensors file.

local function process_save_face_model(image, model_name, overwrite)
  local server = get_server()

  dt.print(_("Exporting face for model building..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_facemodel_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local wf_json = build_save_face_model_json(upload_name, model_name, overwrite)

  dt.print(string.format(_("Building face model '%s'..."), model_name))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue face model build")); return end

  dt.print(_("Processing face model..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Face model build timed out or failed")); return end

  dt.print(string.format(_("Face model '%s' saved!"), model_name))
end

-- ── Remove Background processing ────────────────────────────────────────
-- One-click background removal. No scaling, no presets — operates at
-- original resolution for best edge accuracy.

local function process_rembg(image)
  local server = get_server()

  dt.print(_("Exporting for background removal..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_rembg_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local wf_json = build_rembg_json(upload_name)

  dt.print(_("Queuing background removal..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue background removal")); return end

  dt.print(_("Removing background..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Background removal timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_rembg_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Background removed!"))
end

-- ── Upscale 4x processing ──────────────────────────────────────────────
local function process_upscale(image, upscale_model_file)
  local server = get_server()

  dt.print(_("Exporting for upscale..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_upscale_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local wf_json = build_upscale_json(upload_name, upscale_model_file)

  dt.print(_("Queuing upscale..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue upscale")); return end

  dt.print(_("Upscaling 4x..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Upscale timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_upscale_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Upscale complete!"))
end

-- ── Object Removal (LaMa) processing ──────────────────────────────────
local function process_lama(image, mask_path)
  local server = get_server()

  dt.print(_("Exporting for LaMa inpaint..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading image to ComfyUI..."))
  local img_name = "dt_lama_img_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, img_name)
  os.remove(path)

  dt.print(_("Uploading mask to ComfyUI..."))
  local mask_name = "dt_lama_mask_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", mask_path, mask_name)

  local wf_json = build_lama_json(img_name, mask_name)

  dt.print(_("Queuing LaMa inpaint..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue LaMa inpaint")); return end

  dt.print(_("Removing objects with LaMa..."))
  local results = wait_result(pid)
  if not results then dt.print(_("LaMa inpaint timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_lama_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Object removal complete!"))
end

-- ── Color Grading / LUT processing ────────────────────────────────────
local function process_lut(image, lut_file, strength)
  local server = get_server()

  dt.print(_("Exporting for LUT grading..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_lut_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local wf_json = build_lut_json(upload_name, lut_file, strength)

  dt.print(_("Queuing LUT grading..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue LUT grading")); return end

  dt.print(_("Applying LUT color grading..."))
  local results = wait_result(pid)
  if not results then dt.print(_("LUT grading timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_lut_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("LUT color grading complete!"))
end

-- ── Outpaint / Extend Canvas processing ───────────────────────────────
local function process_outpaint(image, preset, prompt, negative,
                                 pad_left, pad_right, pad_top, pad_bottom)
  local server = get_server()

  dt.print(_("Exporting for outpaint..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_outpaint_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_outpaint_json(upload_name, preset, prompt, negative, seed,
                                       pad_left, pad_right, pad_top, pad_bottom,
                                       scale_w, scale_h)

  dt.print(_("Queuing outpaint..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue outpaint")); return end

  dt.print(_("Extending canvas with outpaint..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Outpaint timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_outpaint_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Outpaint complete!"))
end

-- ── Style Transfer (IPAdapter) processing ─────────────────────────────
local function process_style_transfer(image, style_ref_path, ckpt, prompt, negative, strength)
  local server = get_server()

  dt.print(_("Exporting for style transfer..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading target image..."))
  local tgt_name = "dt_style_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, tgt_name)
  os.remove(path)

  dt.print(_("Uploading style reference..."))
  local ref_name = "dt_style_ref_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", style_ref_path, ref_name)

  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_style_transfer_json(tgt_name, ref_name, ckpt,
                                              prompt, negative, seed,
                                              strength, scale_w, scale_h)

  dt.print(_("Queuing style transfer..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue style transfer")); return end

  dt.print(_("Applying style transfer..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Style transfer timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_style_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Style transfer complete!"))
end

-- ── Face Restore processing ──────────────────────────────────────────────
local function process_face_restore(image, model, visibility, codeformer_weight)
  local server = get_server()

  dt.print(_("Exporting for face restore..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_facerestore_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local wf_json = build_face_restore_json(upload_name, model, visibility, codeformer_weight)

  dt.print(_("Queuing face restore..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue face restore")); return end

  dt.print(_("Restoring faces..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Face restore timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_facerestore_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Face restore complete!"))
end

-- ── Photo Restoration Pipeline processing ────────────────────────────────
local function process_photo_restore(image, upscale_model, face_model, sharpen_alpha)
  local server = get_server()

  dt.print(_("Exporting for photo restoration..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_photorestore_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local wf_json = build_photo_restore_json(upload_name, upscale_model, face_model, sharpen_alpha)

  dt.print(_("Queuing photo restoration pipeline..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue photo restoration")); return end

  dt.print(_("Restoring photo (upscale + face + sharpen)..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Photo restoration timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_photorestore_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Photo restoration complete!"))
end

-- ── Detail Hallucination processing ──────────────────────────────────────
local function process_detail_hallucinate(image, ckpt, prompt, negative, cfg, denoise)
  local server = get_server()

  dt.print(_("Exporting for detail hallucination..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_hallucinate_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local seed = math.random(0, 2^31 - 1)
  local wf_json = build_detail_hallucinate_json(upload_name, ckpt, prompt, negative, seed, cfg, denoise)

  dt.print(_("Queuing detail hallucination..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue detail hallucination")); return end

  dt.print(_("Hallucinating detail (upscale + img2img)..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Detail hallucination timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_hallucinate_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Detail hallucination complete!"))
end

-- ── Colorize B&W processing ──────────────────────────────────────────────
local function process_colorize(image, ckpt, controlnet_name, prompt, negative, strength, denoise)
  local server = get_server()

  dt.print(_("Exporting for colorization..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_colorize_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local seed = math.random(0, 2^31 - 1)
  local wf_json = build_colorize_json(upload_name, ckpt, controlnet_name, prompt, negative, seed, strength, denoise)

  dt.print(_("Queuing colorization..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue colorization")); return end

  dt.print(_("Colorizing B&W photo..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Colorization timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_colorize_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("Colorization complete!"))
end

-- ── Wan I2V processing ──────────────────────────────────────────────────
local function process_wan_i2v(image, wan_preset_idx, prompt, negative,
                                width, height, length, steps, cfg, shift, second_step,
                                loras, accel_enabled, accel_strength,
                                upscale, upscale_factor, interpolate, pingpong, fps,
                                crop_region, end_image_path, vace_strength)
  local server = get_server()
  local wan_preset = WAN_I2V_MODELS[wan_preset_idx]

  dt.print(_("Exporting for Wan I2V..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_wan_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  -- Upload end image if provided
  local end_upload_name = nil
  if end_image_path and end_image_path ~= "" then
    dt.print(_("Uploading end image..."))
    end_upload_name = "dt_wan_end_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
    curl_upload(server .. "/upload/image", end_image_path, end_upload_name)
  end

  local seed = math.random(0, 2^31 - 1)
  local wf_json = build_wan_i2v_json(upload_name, wan_preset, prompt, negative, seed,
                                      width, height, length, steps, cfg, shift, second_step,
                                      loras, accel_enabled, accel_strength,
                                      upscale, upscale_factor, interpolate, pingpong, fps,
                                      crop_region, end_upload_name, vace_strength)

  dt.print(_("Queuing Wan I2V (this may take a while)..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue Wan I2V")); return end

  dt.print(string.format(_("Generating video with %s..."), wan_preset.label))
  local results = wait_result_all(pid, 600)
  if not results then dt.print(_("Wan I2V timed out or failed")); return end

  local gif_imported = false
  local mp4_opened = false
  local imgs_imported = 0

  for j, entry in ipairs(results) do
    local fn = entry.filename
    local sf = entry.subfolder
    local lower_fn = fn:lower()

    -- Build download URL with subfolder if present
    local url
    if sf and sf ~= "" then
      url = string.format("%s/view?filename=%s&subfolder=%s&type=output", server, fn, sf)
    else
      url = string.format("%s/view?filename=%s&type=output", server, fn)
    end

    if lower_fn:match("%.gif$") then
      local out = tmp_dir() .. sep .. "comfy_wan_" .. os.time() .. "_" .. j .. ".gif"
      curl_download(url, out)
      dt.database.import(out)
      gif_imported = true

    elseif lower_fn:match("%.mp4$") or lower_fn:match("%.webm$") then
      local vid_dir = tmp_dir() .. sep .. "comfyui_videos"
      os.execute((dt.configuration.running_os == "windows" and "mkdir " or "mkdir -p ") .. '"' .. shell_esc(vid_dir) .. '"')
      local safe_fn = fn:gsub("\\", "_"):gsub("/", "_")
      local vid_path = vid_dir .. sep .. safe_fn
      curl_download(url, vid_path)
      mp4_opened = true
      -- Open with system player
      if dt.configuration.running_os == "windows" then
        os.execute('start "" "' .. shell_esc(vid_path) .. '"')
      elseif dt.configuration.running_os == "macos" then
        os.execute('open "' .. shell_esc(vid_path) .. '"')
      else
        os.execute('xdg-open "' .. shell_esc(vid_path) .. '" &')
      end

    end
  end

  -- Status message
  local parts = {}
  if gif_imported then table.insert(parts, "GIF imported") end
  if mp4_opened then table.insert(parts, "video opened in player") end
  if #parts > 0 then
    dt.print(string.format(_("Wan I2V complete! %s"), table.concat(parts, ", ")))
  else
    dt.print(_("Wan I2V complete!"))
  end
end

-- ── Klein Flux2 processing ──────────────────────────────────────────────
local function process_klein(image, klein_model, prompt, steps, guidance)
  local server = get_server()

  dt.print(string.format(_("Exporting for Klein %s..."), klein_model.label))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_klein_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_klein_img2img_json(upload_name, klein_model, prompt, seed,
                                            steps, guidance, scale_w, scale_h)

  dt.print(_("Queuing Klein Flux2..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue Klein prompt")); return end

  dt.print(string.format(_("Processing with %s..."), klein_model.label))
  local results = wait_result(pid)
  if not results then dt.print(_("Klein timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_klein_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end
  dt.print(string.format(_("Klein %s complete!"), klein_model.label))
end

-- ── PuLID Flux processing ───────────────────────────────────────────────
local function process_pulid_flux(image, face_source_path, prompt, strength, steps, guidance)
  local server = get_server()

  dt.print(_("Exporting for PuLID Flux..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading target image..."))
  local upload_name = "dt_pulid_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  -- Upload face reference image
  dt.print(_("Uploading face reference..."))
  local face_upload = "dt_pulid_face_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", face_source_path, face_upload)

  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_pulid_flux_json(upload_name, face_upload, prompt, seed,
                                         strength, steps, guidance, scale_w, scale_h)

  dt.print(_("Queuing PuLID Flux..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue PuLID prompt")); return end

  dt.print(_("Processing PuLID Flux (face identity transfer)..."))
  local results = wait_result(pid)
  if not results then dt.print(_("PuLID Flux timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_pulid_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end
  dt.print(_("PuLID Flux complete!"))
end

-- ── Face swap (direct/ReActor) processing ───────────────────────────────
local function process_faceswap_direct(image, source_path, swap_model)
  local server = get_server()

  dt.print(_("Exporting for direct face swap..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading target to ComfyUI..."))
  local tgt_name = "dt_fsd_tgt_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, tgt_name)
  os.remove(path)

  dt.print(_("Uploading source face..."))
  local src_name = "dt_fsd_src_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", source_path, src_name)

  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_faceswap_direct_json(tgt_name, src_name, swap_model, scale_w, scale_h)

  dt.print(_("Queuing direct face swap..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue direct face swap")); return end

  dt.print(_("Processing direct face swap..."))
  local results = wait_result(pid)
  if not results then dt.print(_("Direct face swap timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_fsd_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end
  dt.print(_("Direct face swap complete!"))
end

-- ── FaceID (IPAdapter) processing ────────────────────────────────────────
local function process_faceid(image, preset, face_ref_path, prompt, negative,
                               weight, weight_v2, denoise_override)
  local server = get_server()

  dt.print(string.format(_("Exporting for FaceID %s..."), preset.label))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading target image..."))
  local tgt_name = "dt_faceid_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, tgt_name)
  os.remove(path)

  dt.print(_("Uploading face reference..."))
  local face_name = "dt_faceid_ref_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", face_ref_path, face_name)

  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_faceid_json(tgt_name, face_name, preset,
                                     prompt, negative, seed, scale_w, scale_h,
                                     weight, weight_v2, denoise_override)

  dt.print(_("Queuing FaceID..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue FaceID prompt")); return end

  dt.print(string.format(_("Processing FaceID with %s..."), preset.label))
  local results = wait_result(pid)
  if not results then dt.print(_("FaceID timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_faceid_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end
  dt.print(string.format(_("FaceID %s complete!"), preset.label))
end

-- ── Klein + Reference processing ────────────────────────────────────────
local function process_klein_ref(image, ref_path, klein_model, prompt, steps, guidance)
  local server = get_server()

  dt.print(string.format(_("Exporting for Klein+Ref %s..."), klein_model.label))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading target image..."))
  local tgt_name = "dt_kleinref_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, tgt_name)
  os.remove(path)

  dt.print(_("Uploading reference image..."))
  local ref_name = "dt_kleinref_ref_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", ref_path, ref_name)

  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_klein_ref_json(tgt_name, ref_name, klein_model,
                                        prompt, seed, steps, guidance, scale_w, scale_h)

  dt.print(_("Queuing Klein+Reference..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue Klein+Ref prompt")); return end

  dt.print(string.format(_("Processing Klein+Ref with %s..."), klein_model.label))
  local results = wait_result(pid)
  if not results then dt.print(_("Klein+Ref timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_kleinref_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end
  dt.print(string.format(_("Klein+Ref %s complete!"), klein_model.label))
end

-- ── Inpaint processing ──────────────────────────────────────────────────
local function process_inpaint(image, preset, mask_path, prompt, negative, loras,
                                cn_mode, cn_strength, cn_preprocessor, cn_model)
  local server = get_server()

  -- Verify mask file exists
  local mf = io.open(mask_path, "r")
  if not mf then
    dt.print(_("Mask file not found: ") .. mask_path); return
  end
  mf:close()

  dt.print(string.format(_("Exporting for inpaint (%s)..."), preset.label))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading image and mask..."))
  local upload_name = "dt_inp_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local mask_name = "dt_mask_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", mask_path, mask_name)

  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)
  local wf_json = build_inpaint_json(upload_name, mask_name, preset, prompt, negative,
                                      seed, scale_w, scale_h, loras,
                                      cn_mode, cn_strength, cn_preprocessor, cn_model)

  dt.print(_("Queuing inpaint..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue inpaint prompt")); return end

  dt.print(string.format(_("Inpainting with %s..."), preset.label))
  local results = wait_result(pid)
  if not results then dt.print(_("Inpaint timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_inpaint_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, rfn), out)
    dt.database.import(out)
  end
  dt.print(string.format(_("Inpaint %s complete!"), preset.label))
end

-- ── Batch Variations processing ──────────────────────────────────────────
local function process_batch_variations(preset, prompt, negative, lora_name, lora_strength, width, height, batch_count)
  local server = get_server()

  local seed = math.random(0, 2^31 - 1)
  local wf_json = build_batch_txt2img_json(preset, prompt, negative, seed, lora_name, lora_strength, width, height, batch_count)

  dt.print(string.format(_("Queuing batch of %d variations..."), batch_count))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue batch variations")); return end

  dt.print(string.format(_("Generating %d variations with %s..."), batch_count, preset.label))
  local results = wait_result(pid)
  if not results then dt.print(_("Batch variations timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_batch_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(string.format(_("Batch complete! %d variations generated."), #results))
end

-- (Standalone ControlNet process functions removed -- ControlNet is now
--  integrated into img2img and inpaint via cn_guide_selector widget)

-- ── IC-Light Relighting processing ───────────────────────────────────────
local function process_iclight(image, prompt, negative, multiplier)
  local server = get_server()

  -- IC-Light only works with SD1.5 models
  local preset = MODEL_PRESETS[1]  -- SD1.5 - Juggernaut Reborn

  dt.print(_("Exporting for IC-Light relighting..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_iclight_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local seed = math.random(0, 2^31 - 1)
  local wf_json = build_iclight_json(upload_name, preset.ckpt, prompt, negative, seed, multiplier)

  dt.print(_("Queuing IC-Light relighting..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue IC-Light relighting")); return end

  dt.print(_("Relighting with IC-Light (SD1.5)..."))
  local results = wait_result(pid)
  if not results then dt.print(_("IC-Light relighting timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_iclight_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("IC-Light relighting complete!"))
end

-- ── SUPIR AI Restoration processing ──────────────────────────────────────
local function process_supir(image, supir_model, sdxl_model, prompt, steps, denoise)
  local server = get_server()

  dt.print(_("Exporting for SUPIR restoration..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_supir_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local seed = math.random(0, 2^31 - 1)
  local wf_json = build_supir_json(upload_name, supir_model, sdxl_model, prompt, seed, denoise, steps)

  dt.print(_("Queuing SUPIR restoration..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue SUPIR restoration")); return end

  dt.print(_("Restoring with SUPIR AI (this may take a while)..."))
  local results = wait_result(pid, 300)
  if not results then dt.print(_("SUPIR restoration timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_supir_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("SUPIR restoration complete!"))
end

-- ── SeedV2R Upscaler processing ────────────────────────────────────────
local function process_seedv2r(image, upscale_model, ckpt, prompt, negative,
                                denoise, steps, cfg, sampler, scheduler,
                                scale_factor)
  local server = get_server()

  dt.print(_("Exporting for SeedV2R upscale..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  local orig_w, orig_h = get_image_dims(image)

  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_seedv2r_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  local seed = math.random(0, 2^31 - 1)
  local wf_json = build_seedv2r_json(upload_name, upscale_model, ckpt, prompt, negative,
                                      seed, denoise, steps, cfg, sampler, scheduler,
                                      scale_factor, orig_w, orig_h)

  dt.print(_("Queuing SeedV2R upscale..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then dt.print(_("Failed to queue SeedV2R upscale")); return end

  dt.print(_("Upscaling with SeedV2R (this may take a while)..."))
  local results = wait_result(pid, 300)
  if not results then dt.print(_("SeedV2R upscale timed out or failed")); return end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_seedv2r_" .. os.time() .. "_" .. j .. ".png"
    curl_download(string.format("%s/view?filename=%s&type=output", server, shell_esc(rfn)), out)
    dt.database.import(out)
  end
  dt.print(_("SeedV2R upscale complete!"))
end

-- ═══════════════════════════════════════════════════════════════════════
-- USER PRESET SAVE / LOAD / DELETE
-- ═══════════════════════════════════════════════════════════════════════
-- Stores user-defined presets as a serialized Lua table file.  Each
-- section (img2img, wan_i2v, etc.) gets its own key in the
-- file.  The factory function make_preset_widgets() returns a combobox
-- plus Save / Load / Delete buttons that any section can embed.

local USER_PRESETS_PATH = dt.configuration.config_dir .. "/lua/contrib/spellcaster_presets.lua"

-- Read the entire preset file and return the top-level table, or {}.
local function load_presets_from_file(section)
  local f = io.open(USER_PRESETS_PATH, "r")
  if not f then return {} end
  local content = f:read("*a")
  f:close()
  if not content or content == "" then return {} end
  local fn, err = load("return " .. content)
  if not fn then
    dt.print_error("Spellcaster: failed to parse presets file: " .. tostring(err))
    return {}
  end
  local ok, all = pcall(fn)
  if not ok or type(all) ~= "table" then return {} end
  return all[section] or {}
end

-- Serialize a single Lua value (string, number, boolean) for writing.
local function serialize_value(v)
  if type(v) == "string" then
    return string.format("%q", v)
  elseif type(v) == "number" then
    return tostring(v)
  elseif type(v) == "boolean" then
    return v and "true" or "false"
  else
    return string.format("%q", tostring(v))
  end
end

-- Write presets for one section back to the shared file, preserving
-- other sections that may already be stored there.
local function save_presets_to_file(section, presets)
  -- Load the existing file so we keep other sections intact
  local all = {}
  local f = io.open(USER_PRESETS_PATH, "r")
  if f then
    local content = f:read("*a")
    f:close()
    if content and content ~= "" then
      local fn = load("return " .. content)
      if fn then
        local ok, tbl = pcall(fn)
        if ok and type(tbl) == "table" then all = tbl end
      end
    end
  end
  all[section] = presets

  -- Write the whole table back
  f = io.open(USER_PRESETS_PATH, "w")
  if not f then
    dt.print(_("Error: cannot write presets file"))
    return
  end
  f:write("{\n")
  for sec, list in pairs(all) do
    f:write("[" .. string.format("%q", sec) .. "] = {\n")
    for _, p in ipairs(list) do
      f:write("  {\n")
      for k, v in pairs(p) do
        f:write("    [" .. string.format("%q", k) .. "] = " .. serialize_value(v) .. ",\n")
      end
      f:write("  },\n")
    end
    f:write("},\n")
  end
  f:write("}\n")
  f:close()
end

-- Factory: create preset UI widgets for a given section.
--
--   section_key  -- string key in the presets file (e.g. "img2img")
--   collect_fn   -- function() -> table : gathers current widget values
--   apply_fn     -- function(table)      : restores widget values
--
-- Returns: preset_combo, load_btn, save_btn, delete_btn
-- (caller places them in the module_widget layout)
local function make_preset_widgets(section_key, collect_fn, apply_fn)
  local presets = load_presets_from_file(section_key)

  local combo_init = {
    label = _("My Presets"),
    tooltip = _("Saved preset configurations for this section"),
    selected = 0,
    changed_callback = function() end,
  }
  for _, p in ipairs(presets) do
    combo_init[#combo_init + 1] = p.name or "?"
  end
  local combo = dt.new_widget("combobox")(combo_init)
  if #presets > 0 then combo.selected = 1 end

  -- helper: rebuild the combobox contents from the presets list
  local function rebuild_combo()
    -- Remove existing items (set each trailing slot to nil)
    while #combo > 0 do combo[#combo] = nil end
    for _, p in ipairs(presets) do
      combo[#combo + 1] = p.name or "?"
    end
    if #presets > 0 then combo.selected = 1 else combo.selected = 0 end
  end

  local load_btn = dt.new_widget("button") {
    label = _("Load Preset"),
    tooltip = _("Load the selected preset into this section's controls"),
    clicked_callback = function()
      local idx = combo.selected
      if idx < 1 or idx > #presets then
        dt.print(_("No preset selected"))
        return
      end
      apply_fn(presets[idx])
      dt.print(_("Preset loaded: ") .. (presets[idx].name or "?"))
    end,
  }

  local save_btn = dt.new_widget("button") {
    label = _("Save Preset"),
    tooltip = _("Save the current settings as a preset (name auto-generated from prompt)"),
    clicked_callback = function()
      local data = collect_fn()
      -- Auto-generate a name from the prompt field or a timestamp
      local name = data.prompt or data.positive or ""
      if #name > 30 then name = name:sub(1, 30) .. "..." end
      if #name == 0 then name = os.date("Preset %Y-%m-%d %H:%M:%S") end
      data.name = name
      -- If a preset with this name already exists, overwrite it
      local found = false
      for i, p in ipairs(presets) do
        if p.name == name then
          presets[i] = data
          found = true
          break
        end
      end
      if not found then
        presets[#presets + 1] = data
      end
      save_presets_to_file(section_key, presets)
      rebuild_combo()
      -- Select the one we just saved
      for i, p in ipairs(presets) do
        if p.name == name then combo.selected = i; break end
      end
      dt.print(_("Preset saved: ") .. name)
    end,
  }

  local delete_btn = dt.new_widget("button") {
    label = _("Delete Preset"),
    tooltip = _("Delete the selected preset"),
    clicked_callback = function()
      local idx = combo.selected
      if idx < 1 or idx > #presets then
        dt.print(_("No preset selected"))
        return
      end
      local name = presets[idx].name or "?"
      table.remove(presets, idx)
      save_presets_to_file(section_key, presets)
      rebuild_combo()
      dt.print(_("Preset deleted: ") .. name)
    end,
  }

  return combo, load_btn, save_btn, delete_btn
end

-- ═══════════════════════════════════════════════════════════════════════
-- GUI widget construction
-- ═══════════════════════════════════════════════════════════════════════
-- Darktable's Lua API provides a widget toolkit for building plugin UIs.
-- Widgets are created via dt.new_widget() and assembled into a vertical
-- box layout (module_widget) that gets registered as a lighttable module.
--
-- Widget types used:
--   combobox   -- dropdown selector (model presets, LoRAs, etc.)
--   entry      -- single-line text input (prompts, file paths)
--   slider     -- numeric value with range (denoise, steps, CFG)
--   button     -- action trigger (send, fetch, test connection)
--   label      -- static text (section headers, status)
--   separator  -- visual divider between sections
--   check_button -- boolean toggle (upscale, interpolation, etc.)
--   box        -- container layout (the top-level module widget)
--
-- The GUI is divided into sections by workflow type, each with its own
-- set of controls. All sections share the max_res_slider for resolution.

-- Build combobox with all model presets
local model_selector = dt.new_widget("combobox") {
  label = _("Model"),
  tooltip = _("Select a model preset with tuned settings"),
  selected = 1,
  MODEL_PRESETS[1].label,
  MODEL_PRESETS[2].label,
  MODEL_PRESETS[3].label,
  MODEL_PRESETS[4].label,
  MODEL_PRESETS[5].label,
  MODEL_PRESETS[6].label,
  MODEL_PRESETS[7].label,
  MODEL_PRESETS[8].label,
  MODEL_PRESETS[9].label,
  MODEL_PRESETS[10].label,
  MODEL_PRESETS[11].label,
  MODEL_PRESETS[12].label,
  MODEL_PRESETS[13].label,
  MODEL_PRESETS[14].label,
  MODEL_PRESETS[15].label,
  MODEL_PRESETS[16].label,
  MODEL_PRESETS[17].label,
  MODEL_PRESETS[18].label,
  MODEL_PRESETS[19].label,
  MODEL_PRESETS[20].label,
  MODEL_PRESETS[21].label,
  MODEL_PRESETS[22].label,
  changed_callback = function(self)
    -- Re-filter LoRAs when model selection changes
    if #cached_all_loras > 0 then
      refresh_lora_selector()
    end
    -- Re-filter scene presets for the new architecture
    if refresh_scene_selector then
      refresh_scene_selector()
    end
  end,
}

local prompt_entry = dt.new_widget("entry"){
  tooltip = _("Positive prompt (model hint is prepended automatically)"),
  text = "",
  editable = true,
}

local negative_entry = dt.new_widget("entry"){
  tooltip = _("Negative prompt (model hint is prepended automatically)"),
  text = "",
  editable = true,
}

-- Scene preset selector — populated dynamically by refresh_scene_selector()
local scene_selector = dt.new_widget("combobox") {
  label = _("Scene Preset"),
  tooltip = _("Pick a scene template to auto-fill the prompt fields"),
  selected = 1,
  _("(custom — write your own)"),
  changed_callback = function(self)
    local scene_idx = self.selected
    if scene_idx <= 1 then return end  -- "(custom)" selected, do nothing

    -- Determine current scene architecture
    local midx = model_selector.selected
    local mp = MODEL_PRESETS[midx]
    local sa = mp and scene_arch(mp.arch, mp.label) or "sdxl"

    -- scene_selector stores a mapping from combo index -> SCENE_PRESETS index
    -- in its ._scene_map table (set by refresh_scene_selector)
    local sp_idx = scene_selector._scene_map and scene_selector._scene_map[scene_idx]
    if not sp_idx then return end
    local sp = SCENE_PRESETS[sp_idx]
    if not sp then return end

    -- Look up prompts: exact arch -> fallback to "sdxl" for anime/cartoon/sd15 -> empty
    local p = sp.prompts[sa]
    if not p then
      if sa == "sdxl_anime" or sa == "sdxl_cartoon" or sa == "sd15" then
        p = sp.prompts["sdxl"]
      end
    end
    if not p then p = { positive = "", negative = "" } end

    prompt_entry.text = p.positive or ""
    negative_entry.text = p.negative or ""
  end,
}

-- Store internal mapping (combo index -> SCENE_PRESETS index)
scene_selector._scene_map = {}

-- Refresh scene_selector options to show only scenes available for current arch.
-- Called when model_selector changes.
function refresh_scene_selector()
  local midx = model_selector.selected
  local mp = MODEL_PRESETS[midx]
  local sa = mp and scene_arch(mp.arch, mp.label) or "sdxl"

  -- Clear existing entries
  while #scene_selector > 0 do
    scene_selector[#scene_selector] = nil
  end
  scene_selector._scene_map = {}

  -- Always add "(custom)" as first entry (maps to SCENE_PRESETS[1])
  scene_selector[1] = _("(custom — write your own)")
  scene_selector._scene_map[1] = 1

  -- Add scenes that have prompts for current arch (or fallback)
  local combo_idx = 2
  for i = 2, #SCENE_PRESETS do
    local sp = SCENE_PRESETS[i]
    local has_prompt = sp.prompts[sa]
    if not has_prompt then
      -- Fallback: anime/cartoon/sd15 can use sdxl prompts
      if sa == "sdxl_anime" or sa == "sdxl_cartoon" or sa == "sd15" then
        has_prompt = sp.prompts["sdxl"]
      end
    end
    if has_prompt then
      scene_selector[combo_idx] = sp.label
      scene_selector._scene_map[combo_idx] = i
      combo_idx = combo_idx + 1
    end
  end
  scene_selector.selected = 1
end

local denoise_slider = dt.new_widget("slider"){
  label = _("Denoise override"),
  tooltip = _("Override preset denoise (0 = use preset default)"),
  soft_min = 0,
  soft_max = 1,
  hard_min = 0,
  hard_max = 1,
  step = 0.05,
  digits = 2,
  value = 0,
}

local lora_selector = dt.new_widget("combobox") {
  label = _("LoRA"),
  tooltip = _("Select a compatible LoRA (click Fetch first)"),
  selected = 1,
  "(none)",
}

local lora_strength_slider = dt.new_widget("slider"){
  label = _("LoRA strength"),
  tooltip = _("Strength for both model and CLIP"),
  soft_min = -2,
  soft_max = 2,
  hard_min = -2,
  hard_max = 2,
  step = 0.05,
  digits = 2,
  value = 1,
}

-- Refresh the LoRA combobox with only architecture-compatible LoRAs.
-- Called on model preset change and after fetching LoRAs from server.
-- Darktable combobox items are replaced by clearing all entries and
-- re-adding them (no bulk-set API available).
function refresh_lora_selector()
  local arch = get_current_arch()
  cached_loras = filter_loras_for_arch(cached_all_loras, arch)
  -- Clear existing entries
  while #lora_selector > 0 do
    lora_selector[#lora_selector] = nil
  end
  -- Re-add "(none)" first, then filtered LoRA names
  lora_selector[1] = "(none)"
  for _, name in ipairs(cached_loras) do
    local short = name:match("\\([^\\]+)$") or name:match("/([^/]+)$") or name
    lora_selector[#lora_selector + 1] = short
  end
  lora_selector.selected = 1
end

local fetch_lora_btn = dt.new_widget("button") {
  label = _("Fetch LoRAs"),
  tooltip = _("Fetch LoRAs from ComfyUI (filtered by model architecture)"),
  clicked_callback = function()
    local all = fetch_all_loras()
    refresh_lora_selector()
    local shown = #cached_loras
    local total = #all
    local arch = get_current_arch()
    dt.print(string.format(_("Found %d/%d LoRAs for %s"), shown, total, arch))
  end
}

max_res_slider = dt.new_widget("slider") {
  label = _("Max Processing Res"),
  tooltip = _("Max longest-side resolution for ComfyUI processing. Images larger than this are downscaled before processing and restored to original size afterward."),
  soft_min = 512, soft_max = 4096,
  hard_min = 256, hard_max = 8192,
  step = 64, digits = 0, value = 2048,
}

status_label = dt.new_widget("label") { label = _("Ready") }

local test_btn = dt.new_widget("button") {
  label = _("Test Connection"),
  clicked_callback = function()
    local r = curl_get(get_server() .. "/system_stats")
    if r and #r > 5 then
      status_label.label = _("Connected to ") .. get_server()
      dt.print(_("Connection OK"))
    else
      status_label.label = _("Connection failed")
      dt.print(_("Cannot reach ComfyUI"))
    end
  end
}

-- Forward-declare resolve_cn_params; actual definition is after the
-- ControlNet widgets further down. Closures in clicked_callback only
-- run at button-click time, so the upvalue will be populated by then.
local resolve_cn_params

local img2img_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local send_btn = dt.new_widget("button") {
  label = _("Process with Spellcaster"),
  tooltip = _("Process selected images with the chosen model preset"),
  clicked_callback = function()
    if not acquire_processing_lock() then return end
    local images = dt.gui.selection()
    if #images == 0 then
      dt.print(_("No images selected")); release_processing_lock(); return
    end

    local idx = model_selector.selected
    local preset = MODEL_PRESETS[idx]
    if not preset then
      dt.print(_("Invalid model selection")); release_processing_lock(); return
    end

    -- Build final prompt: preset hint is prepended to user input so the
    -- model gets architecture-appropriate quality tokens automatically
    local user_prompt = prompt_entry.text or ""
    local user_neg = negative_entry.text or ""
    local prompt = preset.prompt_hint
    if #user_prompt > 0 then
      prompt = prompt .. ", " .. user_prompt
    end
    local negative = preset.negative_hint
    if #user_neg > 0 then
      negative = negative .. ", " .. user_neg
    end

    -- Shallow-copy preset so we can override denoise without mutating the original
    local p = {}
    for k, v in pairs(preset) do p[k] = v end
    if denoise_slider.value > 0.001 then
      p.denoise = denoise_slider.value
    end

    status_label.label = string.format(_("Processing %d image(s)..."), #images)

    -- Resolve LoRA selection
    local lora_name = nil
    local lora_str = lora_strength_slider.value
    local lora_idx = lora_selector.selected
    if lora_idx > 1 and cached_loras[lora_idx - 1] then
      lora_name = cached_loras[lora_idx - 1]
    end

    -- Resolve ControlNet guide parameters
    local cn_mode, cn_str, cn_preprocessor, cn_model_name = resolve_cn_params(p)

    local runs = math.floor(img2img_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Image %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Image %d/%d"), i, #images))
        end
        local ok, err = pcall(process_image, img, p, prompt, negative, lora_name, lora_str,
                               cn_mode, cn_str, cn_preprocessor, cn_model_name)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster img2img error: " .. tostring(err))
        end
      end
    end

    release_processing_lock()
    status_label.label = _("Complete!")
    dt.print(_("All images processed"))
  end
}

local upload_btn = dt.new_widget("button") {
  label = _("Upload Only (no processing)"),
  tooltip = _("Upload selected images to ComfyUI input folder for custom workflows"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local server = get_server()
    for i, img in ipairs(images) do
      local path, fname = export_to_temp(img)
      if path then
        curl_upload(server .. "/upload/image", path, fname)
        dt.print(string.format(_("Uploaded: %s"), fname))
        os.remove(path)
      end
    end
  end
}

-- Preset info label (updates on selection change)
local info_label = dt.new_widget("label") {
  label = _("Select a model to see its settings")
}

-- ═══════════════════════════════════════════════════════════════════════
-- Face Swap GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local face_model_selector = dt.new_widget("combobox") {
  label = _("Face Model"),
  tooltip = _("Saved face model from ComfyUI ReActor"),
  selected = 1,
  "(none — click Fetch)",
}

local swap_model_selector = dt.new_widget("combobox") {
  label = _("Swap Engine"),
  tooltip = _("Face swap model engine"),
  selected = 1,
  "inswapper_128.onnx",
}

local fetch_face_btn = dt.new_widget("button") {
  label = _("Fetch Face Models"),
  tooltip = _("Fetch saved face models and swap engines from the server"),
  clicked_callback = function()
    local faces = fetch_face_models()
    local swaps = fetch_swap_models()

    -- Update face model combobox
    while #face_model_selector > 0 do
      face_model_selector[#face_model_selector] = nil
    end
    if #faces > 0 then
      for _, m in ipairs(faces) do
        face_model_selector[#face_model_selector + 1] = m
      end
      face_model_selector.selected = 1
    else
      face_model_selector[1] = "(none found)"
      face_model_selector.selected = 1
    end

    -- Update swap model combobox
    while #swap_model_selector > 0 do
      swap_model_selector[#swap_model_selector] = nil
    end
    if #swaps > 0 then
      for _, m in ipairs(swaps) do
        swap_model_selector[#swap_model_selector + 1] = m
      end
      swap_model_selector.selected = 1
    else
      swap_model_selector[1] = "inswapper_128.onnx"
      swap_model_selector.selected = 1
    end

    dt.print(string.format(_("Found %d face models, %d swap engines"), #faces, #swaps))
  end
}

local faceswap_btn = dt.new_widget("button") {
  label = _("Face Swap (Model)"),
  tooltip = _("Swap face using a saved face model from the server"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local face_idx = face_model_selector.selected
    if face_idx < 1 or #cached_face_models == 0 then
      dt.print(_("No face model selected — click Fetch first")); return
    end
    local face_model = cached_face_models[face_idx]
    local swap_idx = swap_model_selector.selected
    local swap_model = cached_swap_models[swap_idx] or "inswapper_128.onnx"

    for i, img in ipairs(images) do
      dt.print(string.format(_("Face swap %d/%d"), i, #images))
      local ok, err = pcall(process_faceswap_model, img, face_model, swap_model)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster faceswap error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Save Face Model GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local save_face_model_name_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("my_face_model"),
  tooltip = _("Name for the saved face model (without .safetensors extension)"),
  editable = true,
}

local save_face_model_overwrite_check = dt.new_widget("check_button") {
  label = _("Overwrite existing"),
  tooltip = _("If checked, overwrite an existing face model with the same name"),
  value = false,
}

local save_face_model_btn = dt.new_widget("button") {
  label = _("Save Face Model"),
  tooltip = _("Build and save a face model from the selected image to the ComfyUI server"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local model_name = save_face_model_name_entry.text
    if not model_name or model_name == "" then
      dt.print(_("Enter a name for the face model first")); return
    end

    local overwrite = save_face_model_overwrite_check.value

    for i, img in ipairs(images) do
      dt.print(string.format(_("Saving face model %d/%d"), i, #images))
      local name = (#images > 1)
        and string.format("%s_%d", model_name, i)
        or model_name
      local ok, err = pcall(process_save_face_model, img, name, overwrite)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster save face model error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- mtb Face Swap GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local mtb_source_path = ""

local mtb_source_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to source face image..."),
  tooltip = _("Full path to the face image to swap onto the target"),
  editable = true,
}

local mtb_source_btn = dt.new_widget("button") {
  label = _("Browse Source Face..."),
  tooltip = _("Select a source face image file"),
  clicked_callback = function()
    -- Use file_chooser_button alternative via entry
    dt.print(_("Enter the full path to the source face image in the text field above"))
  end
}

local mtb_analysis_selector = dt.new_widget("combobox") {
  label = _("Analysis Model"),
  tooltip = _("Face analysis model for detection"),
  selected = 1,
  "buffalo_l", "antelopev2", "buffalo_m", "buffalo_sc",
}

local mtb_swap_selector = dt.new_widget("combobox") {
  label = _("Swap Model"),
  tooltip = _("Face swap model (inswapper)"),
  selected = 1,
  "inswapper_128.onnx", "inswapper_128_fp16.onnx",
}

local mtb_face_idx_entry = dt.new_widget("entry") {
  text = "0",
  placeholder = "0",
  tooltip = _("Face index (0 = first detected face)"),
  editable = true,
}

local mtb_swap_btn = dt.new_widget("button") {
  label = _("Face Swap (mtb)"),
  tooltip = _("Swap face using mtb facetools with a source image"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local source = mtb_source_entry.text
    if not source or source == "" then
      dt.print(_("Enter source face image path first")); return
    end
    -- Verify file exists
    local f = io.open(source, "r")
    if not f then
      dt.print(_("Source face image not found: ") .. source); return
    end
    f:close()

    local analysis_idx = mtb_analysis_selector.selected
    local analysis = MTB_ANALYSIS_MODELS[analysis_idx] or "buffalo_l"
    local swap_idx = mtb_swap_selector.selected
    local swap = MTB_SWAP_MODELS[swap_idx] or "inswapper_128.onnx"
    local face_idx = mtb_face_idx_entry.text or "0"

    for i, img in ipairs(images) do
      dt.print(string.format(_("mtb face swap %d/%d"), i, #images))
      local ok, err = pcall(process_faceswap_mtb, img, source, analysis, swap, face_idx)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster mtb faceswap error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Wan I2V GUI widgets
-- ═══════════════════════════════════════════════════════════════════════
-- The Wan I2V section has the most complex UI because video generation
-- has many tunable parameters: model pair selection, prompt templates,
-- frame count, dual-step scheduling, acceleration LoRAs, post-processing
-- (upscale + interpolation), VACE end-image mode, and crop region.

local wan_model_selector = dt.new_widget("combobox") {
  label = _("Wan Model"),
  tooltip = _("Select a Wan 2.2 video model pair (high + low noise)"),
  selected = 1,
  WAN_I2V_MODELS[1].label,
  WAN_I2V_MODELS[2].label,
  WAN_I2V_MODELS[3].label,
}

-- Video prompt template selector
local wan_video_preset_labels = {}
for _, vp in ipairs(WAN_VIDEO_PRESETS) do
  wan_video_preset_labels[#wan_video_preset_labels + 1] = vp.label
end

local wan_video_preset_selector  -- forward declaration

local wan_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt for video generation"),
  text = "",
  editable = true,
}

local wan_neg_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for video generation"),
  text = "blurry, distorted, low quality",
  editable = true,
}

-- Create the video preset combobox (callback wired after all widgets are defined)
do
  local init = { label = _("Prompt Template"),
    tooltip = _("Select a best-practice prompt template for common video scenarios"),
    selected = 1 }
  for _, lbl in ipairs(wan_video_preset_labels) do
    init[#init + 1] = lbl
  end
  wan_video_preset_selector = dt.new_widget("combobox")(init)
end

local wan_frames_slider = dt.new_widget("slider") {
  label = _("Frames"),
  tooltip = _("Number of frames (81 = ~5s at 16fps)"),
  soft_min = 17, soft_max = 257,
  hard_min = 1, hard_max = 257,
  step = 4, digits = 0, value = 81,
}

local wan_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Sampling steps"),
  soft_min = 10, soft_max = 50,
  hard_min = 1, hard_max = 100,
  step = 1, digits = 0, value = 30,
}

local wan_cfg_slider = dt.new_widget("slider") {
  label = _("CFG"),
  tooltip = _("Classifier free guidance scale (5.0 recommended for fatberg_slim)"),
  soft_min = 1, soft_max = 15,
  hard_min = 0, hard_max = 30,
  step = 0.5, digits = 1, value = 5.0,
}

local wan_shift_slider = dt.new_widget("slider") {
  label = _("Shift"),
  tooltip = _("Noise shift (8.0 recommended for fatberg_slim)"),
  soft_min = 1, soft_max = 20,
  hard_min = 0, hard_max = 100,
  step = 0.5, digits = 1, value = 8.0,
}

local wan_second_step_slider = dt.new_widget("slider") {
  label = _("Switch Step"),
  tooltip = _("Step at which sampling switches from high-noise to low-noise model"),
  soft_min = 5, soft_max = 40,
  hard_min = 1, hard_max = 100,
  step = 1, digits = 0, value = 20,
}

local wan_upscale_check = dt.new_widget("check_button") {
  label = _("RTX Upscale"),
  tooltip = _("Apply RTXVideoSuperResolution upscale after generation"),
  value = true,
}

local wan_upscale_factor_slider = dt.new_widget("slider") {
  label = _("RTX Scale"),
  tooltip = _("RTX upscale factor (e.g. 1.5 = 50% larger)"),
  soft_min = 1.0, soft_max = 4.0,
  hard_min = 1.0, hard_max = 4.0,
  step = 0.25, digits = 2, value = 1.5,
}

local wan_interpolate_check = dt.new_widget("check_button") {
  label = _("RIFE 2x Interpolation"),
  tooltip = _("Apply RIFE VFI 2x frame interpolation (doubles FPS)"),
  value = true,
}

local wan_pingpong_check = dt.new_widget("check_button") {
  label = _("Ping Pong"),
  tooltip = _("Play video forward then backward for seamless looping"),
  value = false,
}

local wan_accel_check = dt.new_widget("check_button") {
  label = _("Acceleration LoRA"),
  tooltip = _("Apply preset-specific speed LoRAs (e.g. LightX2V) for ~4x faster inference.\nDisable for full-quality slow generation."),
  value = true,
}

local wan_accel_strength_slider = dt.new_widget("slider") {
  label = _("Accel Strength"),
  tooltip = _("Accelerator LoRA strength (1.0 = default, lower = slower but potentially higher quality)"),
  soft_min = 0, soft_max = 2,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

-- Wire up the video preset changed callback now that all widgets exist
wan_video_preset_selector.changed_callback = function(self)
  local idx = self.selected
  if idx < 1 or idx > #WAN_VIDEO_PRESETS then return end
  local vp = WAN_VIDEO_PRESETS[idx]
  if idx == 1 then return end  -- "(none)" — don't touch anything

  wan_prompt_entry.text = vp.prompt
  wan_neg_entry.text = vp.negative
  if vp.cfg_override then wan_cfg_slider.value = vp.cfg_override end
  if vp.steps_override then wan_steps_slider.value = vp.steps_override end
  if vp.length_override then wan_frames_slider.value = vp.length_override end
  if vp.pingpong ~= nil then wan_pingpong_check.value = vp.pingpong end

  -- Auto-select recommended LoRAs if any & filtered list is populated
  if vp.loras and #vp.loras > 0 and #cached_wan_loras_filtered > 0 then
    for slot, lr in ipairs(vp.loras) do
      if slot > 3 then break end
      local row = wan_lora_pair_rows[slot]
      local high_combo, low_combo, str_slider = row[1], row[2], row[3]
      -- Reset both combos
      high_combo.selected = 1
      low_combo.selected = 1
      str_slider.value = lr.strength or 1.0
      -- Try to match lr.name against filtered LoRA list for both high and low
      for j, lname in ipairs(cached_wan_loras_filtered) do
        if lname == lr.name or lname:sub(-#lr.name) == lr.name then
          -- Put matching LoRA in high noise slot by default from preset
          high_combo.selected = j + 1  -- +1 for "(none)" entry
          break
        end
      end
    end
  end
end

-- Explicit High Noise / Low Noise LoRA pair selectors (3 slots).
-- Each slot has independent high/low combos because many Wan LoRAs
-- come as noise-specific pairs that must go to the correct UNET.
local wan_lora_high_1 = dt.new_widget("combobox") {
  label = _("Pair 1 — High Noise"),
  tooltip = _("LoRA for the high-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
local wan_lora_low_1 = dt.new_widget("combobox") {
  label = _("Pair 1 — Low Noise"),
  tooltip = _("LoRA for the low-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
local wan_lora_str_slider_1 = dt.new_widget("slider") {
  label = _("Pair 1 Strength"),
  tooltip = _("LoRA pair 1 strength"),
  soft_min = -2, soft_max = 2,
  hard_min = -2, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

local wan_lora_high_2 = dt.new_widget("combobox") {
  label = _("Pair 2 — High Noise"),
  tooltip = _("LoRA for the high-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
local wan_lora_low_2 = dt.new_widget("combobox") {
  label = _("Pair 2 — Low Noise"),
  tooltip = _("LoRA for the low-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
local wan_lora_str_slider_2 = dt.new_widget("slider") {
  label = _("Pair 2 Strength"),
  tooltip = _("LoRA pair 2 strength"),
  soft_min = -2, soft_max = 2,
  hard_min = -2, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

local wan_lora_high_3 = dt.new_widget("combobox") {
  label = _("Pair 3 — High Noise"),
  tooltip = _("LoRA for the high-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
local wan_lora_low_3 = dt.new_widget("combobox") {
  label = _("Pair 3 — Low Noise"),
  tooltip = _("LoRA for the low-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
local wan_lora_str_slider_3 = dt.new_widget("slider") {
  label = _("Pair 3 Strength"),
  tooltip = _("LoRA pair 3 strength"),
  soft_min = -2, soft_max = 2,
  hard_min = -2, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

-- Each entry: {high_combo, low_combo, strength_slider}
local wan_lora_pair_rows = {
  {wan_lora_high_1, wan_lora_low_1, wan_lora_str_slider_1},
  {wan_lora_high_2, wan_lora_low_2, wan_lora_str_slider_2},
  {wan_lora_high_3, wan_lora_low_3, wan_lora_str_slider_3},
}

local function refresh_wan_lora_combos()
  -- Filter cached loras by the currently selected model preset
  local wan_idx = wan_model_selector.selected
  local wan_preset = WAN_I2V_MODELS[wan_idx]
  local filtered = filter_wan_loras(cached_wan_loras, wan_preset)
  cached_wan_loras_filtered = filtered

  -- Populate every high and low combo with the full filtered list
  for _, row in ipairs(wan_lora_pair_rows) do
    local high_combo, low_combo = row[1], row[2]
    for _, combo in ipairs({high_combo, low_combo}) do
      while #combo > 0 do
        combo[#combo] = nil
      end
      combo[1] = "(none)"
      for _, lname in ipairs(filtered) do
        -- Show just the filename portion for readability
        local short = lname:match("\\([^\\]+)$") or lname:match("/([^/]+)$") or lname
        combo[#combo + 1] = short
      end
      combo.selected = 1
    end
  end
  dt.print(string.format(_("Showing %d/%d Wan LoRAs"), #filtered, #cached_wan_loras))
end

-- Re-filter LoRA combos when user switches model preset
wan_model_selector.changed_callback = function()
  if #cached_wan_loras > 0 then
    refresh_wan_lora_combos()
  end
end

local fetch_wan_lora_btn = dt.new_widget("button") {
  label = _("Fetch LoRAs"),
  tooltip = _("Fetch Wan LoRAs from the server (filtered by selected model variant)"),
  clicked_callback = function()
    fetch_wan_loras()
    refresh_wan_lora_combos()
  end
}

-- End image file picker for VACE start→end mode
local wan_end_image_entry = dt.new_widget("entry") {
  tooltip = _("Path to end image file (leave empty for start-image-only mode)"),
  text = "",
  placeholder = _("(none — start image only)"),
}
local wan_end_image_browse_btn = dt.new_widget("button") {
  label = _("Browse End Image..."),
  tooltip = _("Select an end image to interpolate between start and end frames (VACE)"),
  clicked_callback = function()
    local sel = dt.gui.libs.import.create_dialog()
    -- Darktable doesn't have a simple file chooser widget,
    -- so we use the entry for manual path input.
    -- The user can type or paste a file path.
    dt.print(_("Type or paste the end image file path into the entry above"))
  end
}
local wan_vace_strength_slider = dt.new_widget("slider") {
  label = _("VACE Strength"),
  tooltip = _("VACE conditioning strength (1.0 = full guidance, lower = more creative freedom)"),
  soft_min = 0, soft_max = 2,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

-- Crop region sliders for selection mode (pixel coordinates in source image)
local wan_crop_x_slider = dt.new_widget("slider") {
  label = _("Crop X"),
  tooltip = _("Left edge of crop region in pixels from the source image"),
  soft_min = 0, soft_max = 4096,
  hard_min = 0, hard_max = 8192,
  step = 8, digits = 0, value = 0,
}
local wan_crop_y_slider = dt.new_widget("slider") {
  label = _("Crop Y"),
  tooltip = _("Top edge of crop region in pixels from the source image"),
  soft_min = 0, soft_max = 4096,
  hard_min = 0, hard_max = 8192,
  step = 8, digits = 0, value = 0,
}
local wan_crop_w_slider = dt.new_widget("slider") {
  label = _("Crop Width"),
  tooltip = _("Width of crop region in pixels (0 = full width from X)"),
  soft_min = 0, soft_max = 4096,
  hard_min = 0, hard_max = 8192,
  step = 8, digits = 0, value = 0,
}
local wan_crop_h_slider = dt.new_widget("slider") {
  label = _("Crop Height"),
  tooltip = _("Height of crop region in pixels (0 = full height from Y)"),
  soft_min = 0, soft_max = 4096,
  hard_min = 0, hard_max = 8192,
  step = 8, digits = 0, value = 0,
}

-- Shared helper: collect all Wan I2V parameters from UI widgets into a table.
-- Used by both the "Whole Image" and "Selection" send buttons to avoid
-- duplicating the parameter-gathering logic.
local function collect_wan_i2v_params()
  local params = {}
  params.wan_idx = wan_model_selector.selected
  params.prompt = wan_prompt_entry.text or ""
  params.negative = wan_neg_entry.text or ""
  params.length = math.floor(wan_frames_slider.value)
  params.steps = math.floor(wan_steps_slider.value)
  params.cfg = wan_cfg_slider.value
  params.shift = wan_shift_slider.value
  params.second_step = math.floor(wan_second_step_slider.value)
  params.accel_enabled = wan_accel_check.value
  params.accel_strength = wan_accel_strength_slider.value
  params.upscale = wan_upscale_check.value
  params.upscale_factor = wan_upscale_factor_slider.value
  params.interpolate = wan_interpolate_check.value
  params.pingpong = wan_pingpong_check.value
  params.fps = 16

  -- Collect up to 3 explicit LoRA pairs (high noise + low noise per slot)
  local loras = {}
  for _, row in ipairs(wan_lora_pair_rows) do
    local high_combo, low_combo, str_slider = row[1], row[2], row[3]
    local hi_idx = high_combo.selected
    local lo_idx = low_combo.selected
    local high_path = nil
    local low_path = nil
    -- Index 1 = "(none)", so actual LoRAs start at index 2
    if hi_idx > 1 and cached_wan_loras_filtered[hi_idx - 1] then
      high_path = cached_wan_loras_filtered[hi_idx - 1]
    end
    if lo_idx > 1 and cached_wan_loras_filtered[lo_idx - 1] then
      low_path = cached_wan_loras_filtered[lo_idx - 1]
    end
    if high_path or low_path then
      table.insert(loras, {high = high_path, low = low_path, strength = str_slider.value})
    end
  end
  params.loras = #loras > 0 and loras or nil

  -- End image for VACE start→end mode
  local end_path = wan_end_image_entry.text or ""
  if end_path ~= "" then
    params.end_image_path = end_path
    params.vace_strength = wan_vace_strength_slider.value
  end

  return params
end

local wan_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local wan_send_full_btn = dt.new_widget("button") {
  label = _("Wan I2V (Whole Image)"),
  tooltip = _("Generate video from the entire image using Wan 2.2"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local p = collect_wan_i2v_params()

    local runs = math.floor(wan_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Wan I2V (whole) %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Wan I2V (whole) %d/%d"), i, #images))
        end
        local orig_w, orig_h = get_image_dims(img)
        local vid_w, vid_h = wan_video_dims(orig_w, orig_h)
        local ok, err = pcall(process_wan_i2v, img, p.wan_idx, p.prompt, p.negative,
                        vid_w, vid_h, p.length, p.steps, p.cfg, p.shift, p.second_step,
                        p.loras, p.accel_enabled, p.accel_strength,
                        p.upscale, p.upscale_factor, p.interpolate, p.pingpong, p.fps,
                        nil, p.end_image_path, p.vace_strength)  -- no crop
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster Wan I2V error: " .. tostring(err))
        end
      end
    end
  end
}

local wan_send_sel_btn = dt.new_widget("button") {
  label = _("Wan I2V (Selection)"),
  tooltip = _("Generate video from a cropped region of the image.\nSet Crop X/Y/Width/Height above to define the region."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local cx = math.floor(wan_crop_x_slider.value)
    local cy = math.floor(wan_crop_y_slider.value)
    local cw = math.floor(wan_crop_w_slider.value)
    local ch = math.floor(wan_crop_h_slider.value)

    if cw < 16 or ch < 16 then
      dt.print(_("Set Crop Width and Crop Height (min 16px) before using Selection mode."))
      return
    end

    local crop = {x = cx, y = cy, width = cw, height = ch}
    local p = collect_wan_i2v_params()

    local runs = math.floor(wan_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Wan I2V (selection) %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Wan I2V (selection) %d/%d"), i, #images))
        end
        local vid_w, vid_h = wan_video_dims(cw, ch)
        local ok, err = pcall(process_wan_i2v, img, p.wan_idx, p.prompt, p.negative,
                        vid_w, vid_h, p.length, p.steps, p.cfg, p.shift, p.second_step,
                        p.loras, p.accel_enabled, p.accel_strength,
                        p.upscale, p.upscale_factor, p.interpolate, p.pingpong, p.fps,
                        crop, p.end_image_path, p.vace_strength)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster Wan I2V error: " .. tostring(err))
        end
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Klein Flux2 GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local klein_model_selector = dt.new_widget("combobox") {
  label = _("Klein Model"),
  tooltip = _("Select a Klein Flux2 distilled model"),
  selected = 1,
  KLEIN_MODELS[1].label,
  KLEIN_MODELS[2].label,
  KLEIN_MODELS[3].label,
}

local klein_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt for Klein Flux2 generation"),
  text = "",
  editable = true,
}

local klein_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Sampling steps (distilled model works well with 4)"),
  soft_min = 1, soft_max = 20,
  hard_min = 1, hard_max = 50,
  step = 1, digits = 0, value = 4,
}

local klein_guidance_slider = dt.new_widget("slider") {
  label = _("Guidance"),
  tooltip = _("CFG guidance scale (1.0 for Flux 2)"),
  soft_min = 1, soft_max = 10,
  hard_min = 0, hard_max = 30,
  step = 0.5, digits = 1, value = 1.0,
}

local klein_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local klein_send_btn = dt.new_widget("button") {
  label = _("Send to Klein Flux2"),
  tooltip = _("Process selected images with Klein Flux2 distilled architecture"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local idx = klein_model_selector.selected
    local klein_model = KLEIN_MODELS[idx]
    if not klein_model then dt.print(_("Invalid Klein model")); return end

    local prompt = klein_prompt_entry.text or ""
    local steps = math.floor(klein_steps_slider.value)
    local guidance = klein_guidance_slider.value

    local runs = math.floor(klein_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Klein %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Klein %d/%d"), i, #images))
        end
        local ok, err = pcall(process_klein, img, klein_model, prompt, steps, guidance)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster Klein error: " .. tostring(err))
        end
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- PuLID Flux GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local pulid_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt for PuLID Flux generation"),
  text = "",
  editable = true,
}

local pulid_face_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to face reference image..."),
  tooltip = _("Full path to the face image whose identity will be transferred"),
  editable = true,
}

local pulid_strength_slider = dt.new_widget("slider") {
  label = _("Face Strength"),
  tooltip = _("How strongly to apply the face identity (0.0–1.0)"),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 0.9,
}

local pulid_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Sampling steps"),
  soft_min = 1, soft_max = 20,
  hard_min = 1, hard_max = 50,
  step = 1, digits = 0, value = 4,
}

local pulid_guidance_slider = dt.new_widget("slider") {
  label = _("Guidance"),
  tooltip = _("CFG guidance scale"),
  soft_min = 1, soft_max = 10,
  hard_min = 0, hard_max = 30,
  step = 0.5, digits = 1, value = 3.5,
}

local pulid_send_btn = dt.new_widget("button") {
  label = _("Send to PuLID Flux"),
  tooltip = _("Transfer face identity onto selected images using PuLID Flux"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local face_path = pulid_face_entry.text
    if not face_path or face_path == "" then
      dt.print(_("Enter face reference image path first")); return
    end
    local f = io.open(face_path, "r")
    if not f then
      dt.print(_("Face image not found: ") .. face_path); return
    end
    f:close()

    local prompt = pulid_prompt_entry.text or ""
    local strength = pulid_strength_slider.value
    local steps = math.floor(pulid_steps_slider.value)
    local guidance = pulid_guidance_slider.value

    for i, img in ipairs(images) do
      dt.print(string.format(_("PuLID Flux %d/%d"), i, #images))
      local ok, err = pcall(process_pulid_flux, img, face_path, prompt, strength, steps, guidance)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster PuLID Flux error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Face Swap Direct (ReActor with source image) GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local fsd_source_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to source face image..."),
  tooltip = _("Full path to the face image to swap onto the target"),
  editable = true,
}

local fsd_swap_selector = dt.new_widget("combobox") {
  label = _("Swap Engine"),
  tooltip = _("Face swap model engine"),
  selected = 1,
  "inswapper_128.onnx",
}

local fsd_send_btn = dt.new_widget("button") {
  label = _("Face Swap (Direct/ReActor)"),
  tooltip = _("Swap face from source image onto selected targets using ReActor"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local source = fsd_source_entry.text
    if not source or source == "" then
      dt.print(_("Enter source face image path first")); return
    end
    local f = io.open(source, "r")
    if not f then
      dt.print(_("Source face image not found: ") .. source); return
    end
    f:close()

    local swap_idx = fsd_swap_selector.selected
    local swap_model = fsd_swap_selector[swap_idx] or "inswapper_128.onnx"

    for i, img in ipairs(images) do
      dt.print(string.format(_("Direct face swap %d/%d"), i, #images))
      local ok, err = pcall(process_faceswap_direct, img, source, swap_model)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster direct faceswap error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- FaceID (IPAdapter) GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local faceid_preset_selector = dt.new_widget("combobox") {
  label = _("FaceID Preset"),
  tooltip = _("Select a checkpoint preset for FaceID processing"),
  selected = 1,
  FACEID_PRESETS[1].label,
  FACEID_PRESETS[2].label,
  FACEID_PRESETS[3].label,
  FACEID_PRESETS[4].label,
  FACEID_PRESETS[5].label,
}

local faceid_face_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to face reference image..."),
  tooltip = _("Full path to the face image whose identity will be applied"),
  editable = true,
}

local faceid_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Positive prompt for FaceID generation"),
  text = "",
  editable = true,
}

local faceid_neg_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for FaceID generation"),
  text = "blurry, deformed, bad anatomy",
  editable = true,
}

local faceid_weight_slider = dt.new_widget("slider") {
  label = _("FaceID Weight"),
  tooltip = _("Weight for face identity preservation"),
  soft_min = 0, soft_max = 1.5,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 0.85,
}

local faceid_weight_v2_slider = dt.new_widget("slider") {
  label = _("FaceID V2 Weight"),
  tooltip = _("Weight for FaceID v2 features"),
  soft_min = 0, soft_max = 1.5,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

local faceid_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("Denoise strength (0 = use preset default)"),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 1,
  step = 0.05, digits = 2, value = 0,
}

local faceid_send_btn = dt.new_widget("button") {
  label = _("Send to FaceID"),
  tooltip = _("Apply face identity from reference onto selected images"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local face_path = faceid_face_entry.text
    if not face_path or face_path == "" then
      dt.print(_("Enter face reference image path first")); return
    end
    local f = io.open(face_path, "r")
    if not f then
      dt.print(_("Face image not found: ") .. face_path); return
    end
    f:close()

    local idx = faceid_preset_selector.selected
    local preset = FACEID_PRESETS[idx]
    if not preset then dt.print(_("Invalid FaceID preset")); return end

    local prompt = faceid_prompt_entry.text or ""
    local negative = faceid_neg_entry.text or "blurry, deformed, bad anatomy"
    local weight = faceid_weight_slider.value
    local weight_v2 = faceid_weight_v2_slider.value
    local denoise = nil
    if faceid_denoise_slider.value > 0.001 then
      denoise = faceid_denoise_slider.value
    end

    for i, img in ipairs(images) do
      dt.print(string.format(_("FaceID %d/%d"), i, #images))
      local ok, err = pcall(process_faceid, img, preset, face_path, prompt, negative,
                             weight, weight_v2, denoise)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster FaceID error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Klein Flux2 + Reference GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local kleinref_model_selector = dt.new_widget("combobox") {
  label = _("Klein Model"),
  tooltip = _("Select a Klein Flux2 model for reference-guided editing"),
  selected = 1,
  KLEIN_MODELS[1].label,
  KLEIN_MODELS[2].label,
  KLEIN_MODELS[3].label,
}

local kleinref_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt for Klein+Reference generation"),
  text = "",
  editable = true,
}

local kleinref_ref_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to reference/style image..."),
  tooltip = _("Full path to the reference image (style/structure source)"),
  editable = true,
}

local kleinref_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Sampling steps"),
  soft_min = 1, soft_max = 20,
  hard_min = 1, hard_max = 50,
  step = 1, digits = 0, value = 4,
}

local kleinref_guidance_slider = dt.new_widget("slider") {
  label = _("Guidance"),
  tooltip = _("CFG guidance scale (1.0 for Flux 2)"),
  soft_min = 1, soft_max = 10,
  hard_min = 0, hard_max = 30,
  step = 0.5, digits = 1, value = 1.0,
}

local kleinref_send_btn = dt.new_widget("button") {
  label = _("Send to Klein+Reference"),
  tooltip = _("Edit selected images using Klein Flux2 with a reference image for style guidance"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local ref_path = kleinref_ref_entry.text
    if not ref_path or ref_path == "" then
      dt.print(_("Enter reference image path first")); return
    end
    local f = io.open(ref_path, "r")
    if not f then
      dt.print(_("Reference image not found: ") .. ref_path); return
    end
    f:close()

    local idx = kleinref_model_selector.selected
    local klein_model = KLEIN_MODELS[idx]
    if not klein_model then dt.print(_("Invalid Klein model")); return end

    local prompt = kleinref_prompt_entry.text or ""
    local steps = math.floor(kleinref_steps_slider.value)
    local guidance = kleinref_guidance_slider.value

    for i, img in ipairs(images) do
      dt.print(string.format(_("Klein+Ref %d/%d"), i, #images))
      local ok, err = pcall(process_klein_ref, img, ref_path, klein_model, prompt, steps, guidance)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster Klein+Ref error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Inpaint GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local inpaint_model_selector = dt.new_widget("combobox") {
  label = _("Inpaint Model"),
  tooltip = _("Select a model preset for inpainting"),
  changed_callback = function() end,
  MODEL_PRESETS[1].label,
  MODEL_PRESETS[2].label,
  MODEL_PRESETS[3].label,
  MODEL_PRESETS[4].label,
  MODEL_PRESETS[5].label,
  MODEL_PRESETS[6].label,
  MODEL_PRESETS[7].label,
  MODEL_PRESETS[8].label,
  MODEL_PRESETS[9].label,
  MODEL_PRESETS[10].label,
  MODEL_PRESETS[11].label,
  MODEL_PRESETS[12].label,
  MODEL_PRESETS[13].label,
  MODEL_PRESETS[14].label,
  MODEL_PRESETS[15].label,
  MODEL_PRESETS[16].label,
  MODEL_PRESETS[17].label,
  MODEL_PRESETS[18].label,
  MODEL_PRESETS[19].label,
  MODEL_PRESETS[20].label,
  MODEL_PRESETS[21].label,
  MODEL_PRESETS[22].label,
}

-- Build refinement combobox items dynamically
local inpaint_refinement_labels = {}
for i, ref in ipairs(INPAINT_REFINEMENTS) do
  inpaint_refinement_labels[i] = ref.label
end

local inpaint_refinement_selector = dt.new_widget("combobox") {
  label = _("Body Part / Refinement"),
  tooltip = _("Select a body part preset to auto-fill prompt, negative, denoise, and LoRA settings"),
  changed_callback = function(self)
    local ridx = self.selected
    if ridx <= 1 then return end  -- "(none)" or invalid
    local ref = INPAINT_REFINEMENTS[ridx]
    if not ref then return end
    inpaint_prompt_entry.text = ref.prompt
    inpaint_negative_entry.text = ref.negative
    if ref.denoise then inpaint_denoise_slider.value = ref.denoise end
    if ref.steps_override then
      -- Update the model preset steps via override stored in a variable
      _G._inpaint_steps_override = ref.steps_override
    else
      _G._inpaint_steps_override = nil
    end
    if ref.cfg_boost and ref.cfg_boost > 0 then
      local midx = inpaint_model_selector.selected
      local mp = MODEL_PRESETS[midx]
      if mp then _G._inpaint_cfg_override = mp.cfg + ref.cfg_boost end
    else
      _G._inpaint_cfg_override = nil
    end
  end,
  table.unpack(inpaint_refinement_labels),
}

local inpaint_mask_entry = dt.new_widget("entry") {
  tooltip = _("Full path to a grayscale mask PNG (white = inpaint area, black = keep)"),
  placeholder = _("/path/to/mask.png"),
}

local inpaint_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt describing what to generate in the masked area"),
}

local inpaint_negative_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for inpainting"),
  text = "lowres, bad anatomy, worst quality, blurry",
}

local inpaint_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("Denoising strength (higher = more change in masked area)"),
  soft_min = 0.1, soft_max = 1.0,
  hard_min = 0.01, hard_max = 1.0,
  step = 0.05, digits = 2,
  value = 0.75,
}

local inpaint_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local inpaint_send_btn = dt.new_widget("button") {
  label = _("Send to Inpaint"),
  tooltip = _("Inpaint the masked area of selected images using the chosen model"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local mask_path = inpaint_mask_entry.text
    if not mask_path or mask_path == "" then
      dt.print(_("Enter mask image path first")); return
    end
    local mf = io.open(mask_path, "r")
    if not mf then
      dt.print(_("Mask file not found: ") .. mask_path); return
    end
    mf:close()

    local idx = inpaint_model_selector.selected
    local preset = MODEL_PRESETS[idx]
    if not preset then dt.print(_("Invalid model selection")); return end

    -- Override denoise from slider, apply refinement overrides
    local p = {}
    for k, v in pairs(preset) do p[k] = v end
    p.denoise = inpaint_denoise_slider.value
    if _G._inpaint_steps_override then p.steps = _G._inpaint_steps_override end
    if _G._inpaint_cfg_override then p.cfg = _G._inpaint_cfg_override end

    local prompt = inpaint_prompt_entry.text or ""
    local negative = inpaint_negative_entry.text or ""

    -- Collect LoRAs from refinement preset for current model arch
    local loras = nil
    local ridx = inpaint_refinement_selector.selected
    if ridx and ridx > 1 then
      local ref = INPAINT_REFINEMENTS[ridx]
      if ref and ref.loras then
        local arch = preset.arch or "sdxl"
        loras = ref.loras[arch]
      end
    end

    -- Resolve ControlNet guide parameters
    local cn_mode, cn_str, cn_preprocessor, cn_model_name = resolve_cn_params(p)

    local runs = math.floor(inpaint_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Inpaint %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Inpaint %d/%d"), i, #images))
        end
        local ok, err = pcall(process_inpaint, img, p, mask_path, prompt, negative, loras,
                               cn_mode, cn_str, cn_preprocessor, cn_model_name)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster Inpaint error: " .. tostring(err))
        end
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Module widget assembly and registration
-- ═══════════════════════════════════════════════════════════════════════
-- ═══════════════════════════════════════════════════════════════════════
-- Upscale 4x GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local upscale_model_selector = dt.new_widget("combobox") {
  label = _("Upscale Model"),
  tooltip = _("Select a 4x upscale model"),
  selected = 1,
  UPSCALE_MODELS[1].label,
  UPSCALE_MODELS[2].label,
  UPSCALE_MODELS[3].label,
  UPSCALE_MODELS[4].label,
  UPSCALE_MODELS[5].label,
}

local upscale_send_btn = dt.new_widget("button") {
  label = _("Upscale 4x"),
  tooltip = _("Upscale selected images 4x using the chosen model"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local idx = upscale_model_selector.selected
    local model = UPSCALE_MODELS[idx]
    if not model then dt.print(_("Invalid upscale model")); return end

    for i, img in ipairs(images) do
      dt.print(string.format(_("Upscaling %d/%d"), i, #images))
      local ok, err = pcall(process_upscale, img, model.file)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster upscale error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Object Removal (LaMa) GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local lama_mask_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to mask image (white=remove)..."),
  tooltip = _("Full path to a mask image where white areas mark objects to remove (alpha channel used)"),
  editable = true,
}

local lama_send_btn = dt.new_widget("button") {
  label = _("Remove Objects (LaMa)"),
  tooltip = _("Remove masked objects from the selected image using LaMa inpainting"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    if #images > 1 then dt.print(_("LaMa processes one image at a time — using first selected")); end

    local mask_path = lama_mask_entry.text
    if not mask_path or mask_path == "" then
      dt.print(_("Enter mask image path first")); return
    end
    local f = io.open(mask_path, "r")
    if not f then
      dt.print(_("Mask image not found: ") .. mask_path); return
    end
    f:close()

    local img = images[1]
    local ok, err = pcall(process_lama, img, mask_path)
    if not ok then
      dt.print(_("Error: ") .. tostring(err))
      dt.print_error("Spellcaster LaMa error: " .. tostring(err))
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Color Grading / LUT GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local lut_selector = dt.new_widget("combobox") {
  label = _("LUT Preset"),
  tooltip = _("Select a cinematic LUT for color grading"),
  selected = 1,
  LUT_PRESETS[1].label,
  LUT_PRESETS[2].label,
  LUT_PRESETS[3].label,
  LUT_PRESETS[4].label,
}

local lut_strength_slider = dt.new_widget("slider") {
  label = _("LUT Strength"),
  tooltip = _("Blend strength between original and graded image"),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 1,
  step = 0.05, digits = 2, value = 0.7,
}

local lut_send_btn = dt.new_widget("button") {
  label = _("Apply LUT"),
  tooltip = _("Apply the selected LUT color grade to selected images"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local idx = lut_selector.selected
    local lut = LUT_PRESETS[idx]
    if not lut then dt.print(_("Invalid LUT selection")); return end

    local strength = lut_strength_slider.value

    for i, img in ipairs(images) do
      dt.print(string.format(_("Applying LUT %d/%d"), i, #images))
      local ok, err = pcall(process_lut, img, lut.file, strength)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster LUT error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Outpaint / Extend Canvas GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local outpaint_pad_left_slider = dt.new_widget("slider") {
  label = _("Pad Left"),
  tooltip = _("Pixels to extend on the left side"),
  soft_min = 0, soft_max = 512,
  hard_min = 0, hard_max = 2048,
  step = 8, digits = 0, value = 0,
}

local outpaint_pad_right_slider = dt.new_widget("slider") {
  label = _("Pad Right"),
  tooltip = _("Pixels to extend on the right side"),
  soft_min = 0, soft_max = 512,
  hard_min = 0, hard_max = 2048,
  step = 8, digits = 0, value = 0,
}

local outpaint_pad_top_slider = dt.new_widget("slider") {
  label = _("Pad Top"),
  tooltip = _("Pixels to extend on the top side"),
  soft_min = 0, soft_max = 512,
  hard_min = 0, hard_max = 2048,
  step = 8, digits = 0, value = 0,
}

local outpaint_pad_bottom_slider = dt.new_widget("slider") {
  label = _("Pad Bottom"),
  tooltip = _("Pixels to extend on the bottom side"),
  soft_min = 0, soft_max = 512,
  hard_min = 0, hard_max = 2048,
  step = 8, digits = 0, value = 0,
}

local outpaint_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Describe what to generate in the extended area"),
  text = "",
  editable = true,
}

local outpaint_negative_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for outpaint generation"),
  text = "blurry, deformed, low quality",
  editable = true,
}

local outpaint_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local outpaint_send_btn = dt.new_widget("button") {
  label = _("Outpaint / Extend"),
  tooltip = _("Extend the canvas of the selected image and inpaint the new area"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local preset = MODEL_PRESETS[1]
    local prompt = outpaint_prompt_entry.text or ""
    local negative = outpaint_negative_entry.text or "blurry, deformed, low quality"
    local pad_left = math.floor(outpaint_pad_left_slider.value)
    local pad_right = math.floor(outpaint_pad_right_slider.value)
    local pad_top = math.floor(outpaint_pad_top_slider.value)
    local pad_bottom = math.floor(outpaint_pad_bottom_slider.value)

    if pad_left + pad_right + pad_top + pad_bottom == 0 then
      dt.print(_("Set at least one padding value")); return
    end

    local runs = math.floor(outpaint_runs_slider.value)
    for run_i = 1, runs do
      if runs > 1 then
        dt.print(string.format(_("Outpaint run %d/%d"), run_i, runs))
      end
      local img = images[1]
      local ok, err = pcall(process_outpaint, img, preset, prompt, negative,
                             pad_left, pad_right, pad_top, pad_bottom)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster outpaint error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Style Transfer (IPAdapter) GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local style_ref_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to style reference image..."),
  tooltip = _("Full path to an image whose artistic style will be transferred"),
  editable = true,
}

local style_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Optional prompt to guide the style transfer"),
  text = "",
  editable = true,
}

local style_strength_slider = dt.new_widget("slider") {
  label = _("Style Strength"),
  tooltip = _("How strongly to apply the reference style"),
  soft_min = 0, soft_max = 1.5,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 0.8,
}

local style_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local style_send_btn = dt.new_widget("button") {
  label = _("Apply Style Transfer"),
  tooltip = _("Transfer artistic style from a reference image onto selected images"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local style_path = style_ref_entry.text
    if not style_path or style_path == "" then
      dt.print(_("Enter style reference image path first")); return
    end
    local f = io.open(style_path, "r")
    if not f then
      dt.print(_("Style image not found: ") .. style_path); return
    end
    f:close()

    local ckpt = MODEL_PRESETS[1].ckpt
    local prompt = style_prompt_entry.text or ""
    local strength = style_strength_slider.value

    local runs = math.floor(style_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Style transfer %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Style transfer %d/%d"), i, #images))
        end
        local ok, err = pcall(process_style_transfer, img, style_path, ckpt,
                               prompt, "blurry, deformed, low quality", strength)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster style transfer error: " .. tostring(err))
        end
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Face Restore GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local face_restore_model_selector = dt.new_widget("combobox") {
  label = _("Face Restore Model"),
  tooltip = _("Select a face restoration model"),
  selected = 1,
  FACE_RESTORE_MODELS[1].label,
  FACE_RESTORE_MODELS[2].label,
  FACE_RESTORE_MODELS[3].label,
  FACE_RESTORE_MODELS[4].label,
  FACE_RESTORE_MODELS[5].label,
  FACE_RESTORE_MODELS[6].label,
}

local face_restore_visibility_slider = dt.new_widget("slider") {
  label = _("Visibility"),
  tooltip = _("Blend between original and restored face (0=original, 1=fully restored)"),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 1,
  step = 0.05, digits = 2, value = 1.0,
}

local face_restore_codeformer_slider = dt.new_widget("slider") {
  label = _("CodeFormer Weight"),
  tooltip = _("CodeFormer fidelity weight (lower=quality, higher=fidelity). Only affects CodeFormer model."),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 1,
  step = 0.05, digits = 2, value = 0.5,
}

local face_restore_send_btn = dt.new_widget("button") {
  label = _("Restore Faces"),
  tooltip = _("Restore faces in selected images using the chosen model"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local idx = face_restore_model_selector.selected
    local model = FACE_RESTORE_MODELS[idx]
    if not model then dt.print(_("Invalid face restore model")); return end

    local visibility = face_restore_visibility_slider.value
    local codeformer_weight = face_restore_codeformer_slider.value

    for i, img in ipairs(images) do
      dt.print(string.format(_("Restoring faces %d/%d"), i, #images))
      local ok, err = pcall(process_face_restore, img, model.file, visibility, codeformer_weight)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster face restore error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Photo Restoration Pipeline GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local photo_restore_upscale_selector = dt.new_widget("combobox") {
  label = _("Upscale Model"),
  tooltip = _("Select an upscale model for the restoration pipeline"),
  selected = 1,
  PHOTO_RESTORE_UPSCALE_MODELS[1].label,
  PHOTO_RESTORE_UPSCALE_MODELS[2].label,
  PHOTO_RESTORE_UPSCALE_MODELS[3].label,
  PHOTO_RESTORE_UPSCALE_MODELS[4].label,
}

local photo_restore_sharpen_slider = dt.new_widget("slider") {
  label = _("Sharpen Strength"),
  tooltip = _("Sharpening alpha (0=none, 2=maximum)"),
  soft_min = 0, soft_max = 2,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 0.5,
}

local photo_restore_send_btn = dt.new_widget("button") {
  label = _("Full Photo Restore"),
  tooltip = _("Upscale + Face Restore + Sharpen selected images in one pass"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local up_idx = photo_restore_upscale_selector.selected
    local up_model = PHOTO_RESTORE_UPSCALE_MODELS[up_idx]
    if not up_model then dt.print(_("Invalid upscale model")); return end

    local fr_idx = face_restore_model_selector.selected
    local fr_model = FACE_RESTORE_MODELS[fr_idx]
    if not fr_model then dt.print(_("Invalid face restore model")); return end

    local sharpen = photo_restore_sharpen_slider.value

    for i, img in ipairs(images) do
      dt.print(string.format(_("Photo restore %d/%d"), i, #images))
      local ok, err = pcall(process_photo_restore, img, up_model.file, fr_model.file, sharpen)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster photo restore error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Detail Hallucination / Seed2VR GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local detail_level_selector = dt.new_widget("combobox") {
  label = _("Detail Level"),
  tooltip = _("How much AI detail to hallucinate (higher = more creative, less faithful)"),
  selected = 1,
  DETAIL_HALLUCINATE_LEVELS[1].label,
  DETAIL_HALLUCINATE_LEVELS[2].label,
  DETAIL_HALLUCINATE_LEVELS[3].label,
  DETAIL_HALLUCINATE_LEVELS[4].label,
}

local detail_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt to guide detail hallucination"),
  text = "ultra detailed, sharp focus, high resolution, intricate details",
  editable = true,
}

local detail_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local detail_send_btn = dt.new_widget("button") {
  label = _("Hallucinate Detail"),
  tooltip = _("Upscale and add AI-hallucinated detail to selected images"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local level_idx = detail_level_selector.selected
    local level = DETAIL_HALLUCINATE_LEVELS[level_idx]
    if not level then dt.print(_("Invalid detail level")); return end

    local midx = model_selector.selected
    local mp = MODEL_PRESETS[midx]
    if not mp then dt.print(_("Invalid model preset")); return end

    local prompt = detail_prompt_entry.text or "ultra detailed, sharp focus, high resolution, intricate details"
    local negative = "blurry, low quality, soft, out of focus"

    local runs = math.floor(detail_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Hallucinating detail %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Hallucinating detail %d/%d"), i, #images))
        end
        local ok, err = pcall(process_detail_hallucinate, img, mp.ckpt, prompt, negative, level.cfg, level.denoise)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster detail hallucinate error: " .. tostring(err))
        end
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Colorize B&W Photo GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

local colorize_strength_slider = dt.new_widget("slider") {
  label = _("ControlNet Strength"),
  tooltip = _("How strongly the lineart structure guides colorization"),
  soft_min = 0.5, soft_max = 1.0,
  hard_min = 0.5, hard_max = 1.0,
  step = 0.05, digits = 2, value = 0.85,
}

local colorize_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("Generation strength (higher = more creative color, less faithful to structure)"),
  soft_min = 0.4, soft_max = 0.7,
  hard_min = 0.4, hard_max = 0.7,
  step = 0.05, digits = 2, value = 0.55,
}

local colorize_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt to guide colorization"),
  text = "vivid natural colors, photorealistic, color photograph, warm tones, lifelike colors",
  editable = true,
}

local colorize_negative_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for colorization"),
  text = "black and white, grayscale, monochrome, desaturated, sepia, low quality",
  editable = true,
}

local colorize_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local colorize_send_btn = dt.new_widget("button") {
  label = _("Colorize B&W"),
  tooltip = _("Add color to black & white photos using ControlNet-guided img2img"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local midx = model_selector.selected
    local mp = MODEL_PRESETS[midx]
    if not mp then dt.print(_("Invalid model preset")); return end

    -- Auto-select ControlNet based on model architecture
    local controlnet_name
    if mp.arch == "sd15" then
      controlnet_name = "control_v11p_sd15_lineart_fp16.safetensors"
    elseif mp.arch == "zit" then
      controlnet_name = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"
    else
      controlnet_name = "SDXL\\controlnet-canny-sdxl-1.0.safetensors"
    end

    local prompt = colorize_prompt_entry.text or "vivid natural colors, photorealistic, color photograph, warm tones, lifelike colors"
    local negative = colorize_negative_entry.text or "black and white, grayscale, monochrome, desaturated, sepia, low quality"
    local strength = colorize_strength_slider.value
    local denoise = colorize_denoise_slider.value

    local runs = math.floor(colorize_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Colorizing %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Colorizing %d/%d"), i, #images))
        end
        local ok, err = pcall(process_colorize, img, mp.ckpt, controlnet_name, prompt, negative, strength, denoise)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster colorize error: " .. tostring(err))
        end
      end
    end
  end
}

-- ── Batch Variations widgets ─────────────────────────────────────────────
local batch_count_slider = dt.new_widget("slider") {
  label = _("Batch Count"),
  tooltip = _("Number of variations to generate in one pass (txt2img)"),
  soft_min = 2, soft_max = 8,
  hard_min = 2, hard_max = 8,
  step = 1, digits = 0, value = 4,
}

local batch_width_slider = dt.new_widget("slider") {
  label = _("Width"),
  tooltip = _("Output image width (multiple of 8)"),
  soft_min = 512, soft_max = 2048,
  hard_min = 256, hard_max = 4096,
  step = 64, digits = 0, value = 1024,
}

local batch_height_slider = dt.new_widget("slider") {
  label = _("Height"),
  tooltip = _("Output image height (multiple of 8)"),
  soft_min = 512, soft_max = 2048,
  hard_min = 256, hard_max = 4096,
  step = 64, digits = 0, value = 1024,
}

local batch_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate the full batch. Each run uses fresh seeds."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local batch_send_btn = dt.new_widget("button") {
  label = _("Generate Batch"),
  tooltip = _("Generate multiple txt2img variations using the selected model preset"),
  clicked_callback = function()
    local idx = model_selector.selected
    local preset = MODEL_PRESETS[idx]
    if not preset then
      dt.print(_("Invalid model selection")); return
    end

    -- Build final prompt: preset hint + user input
    local user_prompt = prompt_entry.text or ""
    local user_neg = negative_entry.text or ""
    local prompt = preset.prompt_hint
    if #user_prompt > 0 then
      prompt = prompt .. ", " .. user_prompt
    end
    local negative = preset.negative_hint
    if #user_neg > 0 then
      negative = negative .. ", " .. user_neg
    end

    -- Shallow-copy preset so we can override denoise without mutating the original
    local p = {}
    for k, v in pairs(preset) do p[k] = v end
    if denoise_slider.value > 0.001 then
      p.denoise = denoise_slider.value
    end

    -- Resolve LoRA selection
    local lora_name = nil
    local lora_str = lora_strength_slider.value
    local lora_idx = lora_selector.selected
    if lora_idx > 1 and cached_loras[lora_idx - 1] then
      lora_name = cached_loras[lora_idx - 1]
    end

    local width = math.floor(batch_width_slider.value / 8) * 8
    local height = math.floor(batch_height_slider.value / 8) * 8
    local batch_count = math.floor(batch_count_slider.value)

    local runs = math.floor(batch_runs_slider.value)
    for run_i = 1, runs do
      if runs > 1 then
        status_label.label = string.format(_("Batch run %d/%d (%d variations)..."), run_i, runs, batch_count)
        dt.print(string.format(_("Batch run %d/%d"), run_i, runs))
      else
        status_label.label = string.format(_("Generating %d batch variations..."), batch_count)
      end
      local ok, err = pcall(process_batch_variations, p, prompt, negative, lora_name, lora_str, width, height, batch_count)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster batch error: " .. tostring(err))
      end
    end
    status_label.label = _("Complete!")
  end
}

-- ── Integrated ControlNet Guide widgets (used by img2img and inpaint) ────
-- These replace the former standalone ControlNet Suite buttons. The guide
-- mode selector and strength slider are placed in the img2img section and
-- their values are read by both the img2img and inpaint button handlers.

local cn_guide_selector = dt.new_widget("combobox") {
  label = _("ControlNet Guide"),
  tooltip = _("Structure-guided generation: extract edges/depth/pose from source image"),
  selected = 1,
  "Off", "Canny (edges)", "Depth (spatial)", "Lineart (drawing)",
  "OpenPose (body)", "Scribble (sketch)", "Tile (detail)",
}

local cn_strength_slider = dt.new_widget("slider") {
  label = _("CN Strength"),
  tooltip = _("How strongly the structure guide influences generation"),
  soft_min = 0.0, soft_max = 1.5, hard_min = 0.0, hard_max = 2.0,
  step = 0.05, digits = 2, value = 0.8,
}

-- Helper: resolve ControlNet parameters from the shared widgets and a preset
-- (forward-declared above send_btn so closures can capture the upvalue)
resolve_cn_params = function(preset)
  local cn_idx = cn_guide_selector.selected
  local cn_mode_info = cn_guide_modes[cn_idx]
  if not cn_mode_info or cn_mode_info.key == "off" then
    return "off", 0, nil, nil
  end
  local cn_mode = cn_mode_info.key
  local cn_preprocessor = cn_mode_info.preprocessor
  local arch = preset.arch or "sdxl"
  local map = CN_MODEL_MAP[cn_mode]
  local cn_model_name = map and (map[arch] or map["sdxl"]) or nil
  local cn_str = cn_strength_slider.value
  return cn_mode, cn_str, cn_preprocessor, cn_model_name
end

-- ── IC-Light Relighting widgets ──────────────────────────────────────────
local iclight_preset_selector = dt.new_widget("combobox") {
  label = _("Lighting Preset"),
  tooltip = _("Select a lighting direction/mood preset"),
  selected = 1,
  ICLIGHT_PRESETS[1].label,
  ICLIGHT_PRESETS[2].label,
  ICLIGHT_PRESETS[3].label,
  ICLIGHT_PRESETS[4].label,
  ICLIGHT_PRESETS[5].label,
  ICLIGHT_PRESETS[6].label,
  ICLIGHT_PRESETS[7].label,
  ICLIGHT_PRESETS[8].label,
  ICLIGHT_PRESETS[9].label,
  ICLIGHT_PRESETS[10].label,
}

local iclight_multiplier_slider = dt.new_widget("slider") {
  label = _("Multiplier"),
  tooltip = _("IC-Light conditioning multiplier (lower=subtle, higher=stronger)"),
  soft_min = 0.0, soft_max = 1.0,
  hard_min = 0.0, hard_max = 2.0,
  step = 0.02, digits = 2, value = 0.18,
}

local iclight_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local iclight_send_btn = dt.new_widget("button") {
  label = _("Relight with IC-Light"),
  tooltip = _("Relight selected images using IC-Light (SD1.5 only)"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end

    local preset_idx = iclight_preset_selector.selected
    local iclight_preset = ICLIGHT_PRESETS[preset_idx]
    if not iclight_preset then dt.print(_("Invalid lighting preset")); return end

    local prompt = iclight_preset.prompt
    local negative = "dark, shadows, underexposed, low quality"
    local multiplier = iclight_multiplier_slider.value

    local runs = math.floor(iclight_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("IC-Light relighting %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("IC-Light relighting %d/%d"), i, #images))
        end
        local ok, err = pcall(process_iclight, img, prompt, negative, multiplier)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster IC-Light error: " .. tostring(err))
        end
      end
    end
  end
}

-- ── SUPIR AI Restoration widgets ─────────────────────────────────────────
local supir_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("SUPIR denoising strength (lower=preserve detail, higher=more restoration)"),
  soft_min = 0.1, soft_max = 1.0,
  hard_min = 0.1, hard_max = 1.0,
  step = 0.05, digits = 2, value = 0.3,
}

local supir_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Number of sampling steps for SUPIR restoration"),
  soft_min = 10, soft_max = 50,
  hard_min = 5, hard_max = 100,
  step = 1, digits = 0, value = 20,
}

local supir_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Positive prompt for SUPIR restoration (describes desired output quality)"),
  text = "high quality, detailed, sharp",
  editable = true,
}

-- SUPIR SDXL model selector (uses SDXL checkpoints from MODEL_PRESETS)
local supir_sdxl_models = {}
local supir_sdxl_ckpts = {}
for _, mp in ipairs(MODEL_PRESETS) do
  if mp.arch == "sdxl" then
    table.insert(supir_sdxl_models, mp.label)
    table.insert(supir_sdxl_ckpts, mp.ckpt)
  end
end

local supir_model_selector = dt.new_widget("combobox") {
  label = _("SDXL Model"),
  tooltip = _("SDXL checkpoint for SUPIR restoration backbone"),
  selected = 1,
}
-- Populate the SDXL model combobox
for i, label in ipairs(supir_sdxl_models) do
  supir_model_selector[i] = label
end

local supir_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local supir_send_btn = dt.new_widget("button") {
  label = _("Restore with SUPIR"),
  tooltip = _("AI restoration using SUPIR (requires SUPIR model + SDXL checkpoint)"),
  clicked_callback = function()
    if not acquire_processing_lock() then return end
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); release_processing_lock(); return end

    local supir_model = "Other\\SUPIR-v0Q_fp16.safetensors"
    local sdxl_idx = supir_model_selector.selected
    local sdxl_model = supir_sdxl_ckpts[sdxl_idx]
    if not sdxl_model then
      -- Fallback to Juggernaut XL v9
      sdxl_model = "SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors"
    end

    local prompt = supir_prompt_entry.text or "high quality, detailed, sharp"
    local steps = math.floor(supir_steps_slider.value)
    local denoise = supir_denoise_slider.value

    local runs = math.floor(supir_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("SUPIR restoring %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("SUPIR restoring %d/%d"), i, #images))
        end
        local ok, err = pcall(process_supir, img, supir_model, sdxl_model, prompt, steps, denoise)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster SUPIR error: " .. tostring(err))
        end
      end
    end
    release_processing_lock()
  end
}

-- ── SeedV2R Upscaler widgets ───────────────────────────────────────────
-- Forward-declare entry widgets so changed_callback can reference them
local seedv2r_prompt_entry, seedv2r_negative_entry

local seedv2r_preset_labels = {}
for _, p in ipairs(SEEDV2R_PRESETS) do
  table.insert(seedv2r_preset_labels, p.label)
end

local seedv2r_hallucination_combo = dt.new_widget("combobox") {
  label = _("Hallucination Level"),
  tooltip = _("Controls how much detail the AI invents vs preserves from the original"),
  selected = 2,
  changed_callback = function(self)
    local idx = self.selected
    local preset = SEEDV2R_PRESETS[idx]
    if preset then
      seedv2r_prompt_entry.text = preset.prompt
      seedv2r_negative_entry.text = preset.negative
    end
  end,
}
for i, label in ipairs(seedv2r_preset_labels) do
  seedv2r_hallucination_combo[i] = label
end

local seedv2r_scale_labels = {}
for _, s in ipairs(SEEDV2R_SCALES) do
  table.insert(seedv2r_scale_labels, s.label)
end

local seedv2r_scale_combo = dt.new_widget("combobox") {
  label = _("Scale"),
  tooltip = _("Upscale factor (1x = enhance only, no size change)"),
  selected = 3,  -- default 2x
}
for i, label in ipairs(seedv2r_scale_labels) do
  seedv2r_scale_combo[i] = label
end

local SEEDV2R_UPSCALE_MODELS = {
  {label = "4x-UltraSharp", file = "4x-UltraSharp.pth"},
  {label = "RealESRGAN x4plus", file = "RealESRGAN_x4plus.pth"},
  {label = "4x-Remacri", file = "4x_Remacri.pth"},
  {label = "4x-NMKD-Superscale", file = "4x_NMKD-Superscale-SP_178000_G.pth"},
  {label = "4x-foolhardy-Remacri", file = "4x_foolhardy_Remacri.pth"},
}

local seedv2r_upscale_model_labels = {}
local seedv2r_upscale_model_files = {}
for _, m in ipairs(SEEDV2R_UPSCALE_MODELS) do
  table.insert(seedv2r_upscale_model_labels, m.label)
  table.insert(seedv2r_upscale_model_files, m.file)
end

local seedv2r_upscale_model_combo = dt.new_widget("combobox") {
  label = _("Upscale Model"),
  tooltip = _("Neural upscale model (all are 4x; output is rescaled to target)"),
  selected = 1,
}
for i, label in ipairs(seedv2r_upscale_model_labels) do
  seedv2r_upscale_model_combo[i] = label
end

-- Use first SDXL realistic checkpoint as default for KSampler refinement
local seedv2r_ckpt_labels = {}
local seedv2r_ckpt_paths = {}
for _, mp in ipairs(MODEL_PRESETS) do
  if mp.arch == "sdxl" then
    table.insert(seedv2r_ckpt_labels, mp.label)
    table.insert(seedv2r_ckpt_paths, mp.ckpt)
  end
end

local seedv2r_ckpt_combo = dt.new_widget("combobox") {
  label = _("Refinement Checkpoint"),
  tooltip = _("SDXL checkpoint used for KSampler detail refinement pass"),
  selected = 1,
}
for i, label in ipairs(seedv2r_ckpt_labels) do
  seedv2r_ckpt_combo[i] = label
end

seedv2r_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Positive prompt (auto-filled from hallucination preset)"),
  text = SEEDV2R_PRESETS[2].prompt,
  editable = true,
}

seedv2r_negative_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt (auto-filled from hallucination preset)"),
  text = SEEDV2R_PRESETS[2].negative,
  editable = true,
}

local seedv2r_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

local seedv2r_send_btn = dt.new_widget("button") {
  label = _("Upscale with SeedV2R"),
  tooltip = _("AI upscale using upscale model + KSampler detail refinement"),
  clicked_callback = function()
    if not acquire_processing_lock() then return end
    local images = dt.gui.selection()
    if #images == 0 then
      dt.print(_("No images selected")); release_processing_lock(); return
    end

    local hall_idx = seedv2r_hallucination_combo.selected
    local preset = SEEDV2R_PRESETS[hall_idx] or SEEDV2R_PRESETS[2]

    local scale_idx = seedv2r_scale_combo.selected
    local scale_factor = SEEDV2R_SCALES[scale_idx] and SEEDV2R_SCALES[scale_idx].factor or 2.0

    local upmodel_idx = seedv2r_upscale_model_combo.selected
    local upscale_model = seedv2r_upscale_model_files[upmodel_idx] or seedv2r_upscale_model_files[1]

    local ckpt_idx = seedv2r_ckpt_combo.selected
    local ckpt = seedv2r_ckpt_paths[ckpt_idx] or seedv2r_ckpt_paths[1]

    local prompt = seedv2r_prompt_entry.text or preset.prompt
    local negative = seedv2r_negative_entry.text or preset.negative
    local denoise = preset.denoise
    local steps = preset.steps
    local cfg = preset.cfg

    local runs = math.floor(seedv2r_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("SeedV2R upscaling %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("SeedV2R upscaling %d/%d"), i, #images))
        end
        local ok, err = pcall(process_seedv2r, img, upscale_model, ckpt, prompt, negative,
                               denoise, steps, cfg, "dpmpp_2m_sde", "karras", scale_factor)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster SeedV2R error: " .. tostring(err))
        end
      end
    end
    release_processing_lock()
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Per-section user preset widgets (combo + Save / Load / Delete)
-- ═══════════════════════════════════════════════════════════════════════

-- ── img2img presets ─────────────────────────────────────────────────
local img2img_preset_combo, img2img_preset_load, img2img_preset_save, img2img_preset_delete =
  make_preset_widgets("img2img",
    function()  -- collect
      return {
        model_idx    = model_selector.selected,
        scene_idx    = scene_selector.selected,
        prompt       = prompt_entry.text or "",
        negative     = negative_entry.text or "",
        denoise      = denoise_slider.value,
        cn_mode      = cn_guide_selector.selected,
        cn_strength  = cn_strength_slider.value,
      }
    end,
    function(p)  -- apply
      if p.model_idx    then model_selector.selected    = p.model_idx    end
      if p.scene_idx    then scene_selector.selected    = p.scene_idx    end
      if p.prompt       then prompt_entry.text          = p.prompt       end
      if p.negative     then negative_entry.text        = p.negative     end
      if p.denoise      then denoise_slider.value       = p.denoise      end
      if p.cn_mode      then cn_guide_selector.selected = p.cn_mode      end
      if p.cn_strength  then cn_strength_slider.value   = p.cn_strength  end
    end)

-- ── Wan I2V presets ─────────────────────────────────────────────────
local wan_preset_combo, wan_preset_load, wan_preset_save, wan_preset_delete =
  make_preset_widgets("wan_i2v",
    function()
      return {
        model_idx   = wan_model_selector.selected,
        prompt      = wan_prompt_entry.text or "",
        negative    = wan_neg_entry.text or "",
        frames      = wan_frames_slider.value,
        steps       = wan_steps_slider.value,
        cfg         = wan_cfg_slider.value,
        shift       = wan_shift_slider.value,
        second_step = wan_second_step_slider.value,
        upscale     = wan_upscale_check.value,
        upscale_f   = wan_upscale_factor_slider.value,
        interpolate = wan_interpolate_check.value,
        pingpong    = wan_pingpong_check.value,
        accel       = wan_accel_check.value,
        accel_str   = wan_accel_strength_slider.value,
      }
    end,
    function(p)
      if p.model_idx   then wan_model_selector.selected      = p.model_idx   end
      if p.prompt      then wan_prompt_entry.text             = p.prompt      end
      if p.negative    then wan_neg_entry.text                = p.negative    end
      if p.frames      then wan_frames_slider.value           = p.frames      end
      if p.steps       then wan_steps_slider.value            = p.steps       end
      if p.cfg         then wan_cfg_slider.value              = p.cfg         end
      if p.shift       then wan_shift_slider.value            = p.shift       end
      if p.second_step then wan_second_step_slider.value      = p.second_step end
      if p.upscale ~= nil     then wan_upscale_check.value     = p.upscale     end
      if p.upscale_f   then wan_upscale_factor_slider.value   = p.upscale_f   end
      if p.interpolate ~= nil then wan_interpolate_check.value = p.interpolate end
      if p.pingpong ~= nil    then wan_pingpong_check.value    = p.pingpong    end
      if p.accel ~= nil       then wan_accel_check.value       = p.accel       end
      if p.accel_str   then wan_accel_strength_slider.value   = p.accel_str   end
    end)

-- ── Klein Flux2 presets ─────────────────────────────────────────────
local klein_preset_combo, klein_preset_load, klein_preset_save, klein_preset_delete =
  make_preset_widgets("klein",
    function()
      return {
        model_idx = klein_model_selector.selected,
        prompt    = klein_prompt_entry.text or "",
        steps     = klein_steps_slider.value,
        guidance  = klein_guidance_slider.value,
      }
    end,
    function(p)
      if p.model_idx then klein_model_selector.selected = p.model_idx end
      if p.prompt    then klein_prompt_entry.text        = p.prompt    end
      if p.steps     then klein_steps_slider.value       = p.steps     end
      if p.guidance  then klein_guidance_slider.value     = p.guidance  end
    end)

-- ── Inpaint presets ─────────────────────────────────────────────────
local inpaint_preset_combo, inpaint_preset_load, inpaint_preset_save, inpaint_preset_delete =
  make_preset_widgets("inpaint",
    function()
      return {
        model_idx   = inpaint_model_selector.selected,
        refinement  = inpaint_refinement_selector.selected,
        prompt      = inpaint_prompt_entry.text or "",
        negative    = inpaint_negative_entry.text or "",
        denoise     = inpaint_denoise_slider.value,
      }
    end,
    function(p)
      if p.model_idx  then inpaint_model_selector.selected      = p.model_idx  end
      if p.refinement then inpaint_refinement_selector.selected  = p.refinement end
      if p.prompt     then inpaint_prompt_entry.text             = p.prompt     end
      if p.negative   then inpaint_negative_entry.text           = p.negative   end
      if p.denoise    then inpaint_denoise_slider.value          = p.denoise    end
    end)

-- ── IC-Light presets ────────────────────────────────────────────────
local iclight_preset_combo, iclight_preset_load, iclight_preset_save, iclight_preset_delete =
  make_preset_widgets("iclight",
    function()
      return {
        prompt     = ICLIGHT_PRESETS[iclight_preset_selector.selected]
                       and ICLIGHT_PRESETS[iclight_preset_selector.selected].label or "",
        preset_idx = iclight_preset_selector.selected,
        multiplier = iclight_multiplier_slider.value,
      }
    end,
    function(p)
      if p.preset_idx then iclight_preset_selector.selected = p.preset_idx end
      if p.multiplier then iclight_multiplier_slider.value   = p.multiplier end
    end)

-- ── Outpaint presets ────────────────────────────────────────────────
local outpaint_preset_combo, outpaint_preset_load, outpaint_preset_save, outpaint_preset_delete =
  make_preset_widgets("outpaint",
    function()
      return {
        prompt   = outpaint_prompt_entry.text or "",
        negative = outpaint_negative_entry.text or "",
        pad_l    = outpaint_pad_left_slider.value,
        pad_r    = outpaint_pad_right_slider.value,
        pad_t    = outpaint_pad_top_slider.value,
        pad_b    = outpaint_pad_bottom_slider.value,
      }
    end,
    function(p)
      if p.prompt   then outpaint_prompt_entry.text        = p.prompt   end
      if p.negative then outpaint_negative_entry.text      = p.negative end
      if p.pad_l    then outpaint_pad_left_slider.value    = p.pad_l    end
      if p.pad_r    then outpaint_pad_right_slider.value   = p.pad_r    end
      if p.pad_t    then outpaint_pad_top_slider.value     = p.pad_t    end
      if p.pad_b    then outpaint_pad_bottom_slider.value  = p.pad_b    end
    end)

-- ── Style Transfer presets ──────────────────────────────────────────
local style_preset_combo, style_preset_load, style_preset_save, style_preset_delete =
  make_preset_widgets("style_transfer",
    function()
      return {
        prompt   = style_prompt_entry.text or "",
        ref_path = style_ref_entry.text or "",
        strength = style_strength_slider.value,
      }
    end,
    function(p)
      if p.prompt   then style_prompt_entry.text    = p.prompt   end
      if p.ref_path then style_ref_entry.text       = p.ref_path end
      if p.strength then style_strength_slider.value = p.strength end
    end)

-- ── Colorize presets ────────────────────────────────────────────────
local colorize_preset_combo, colorize_preset_load, colorize_preset_save, colorize_preset_delete =
  make_preset_widgets("colorize",
    function()
      return {
        prompt    = colorize_prompt_entry.text or "",
        negative  = colorize_negative_entry.text or "",
        strength  = colorize_strength_slider.value,
        denoise   = colorize_denoise_slider.value,
      }
    end,
    function(p)
      if p.prompt   then colorize_prompt_entry.text       = p.prompt   end
      if p.negative then colorize_negative_entry.text     = p.negative end
      if p.strength then colorize_strength_slider.value   = p.strength end
      if p.denoise  then colorize_denoise_slider.value    = p.denoise  end
    end)

-- All widgets are assembled into a single vertical box. Darktable
-- renders this as a scrollable panel in the right sidebar of lighttable.
-- Registration is guarded: if we're already in lighttable, register
-- immediately. Otherwise, wait for a view-changed event from darkroom
-- to lighttable. The "hide" destroy method keeps the module registered
-- but invisible, so re-showing is instant without re-registration.

local module_widget = dt.new_widget("box") {
  orientation = "vertical",
  dt.new_widget("label") { label = _("\xe2\x9c\xa8 Spellcaster \xe2\x80\x94 AI Superpowers") },
  status_label,
  test_btn,
  dt.new_widget("separator") {},

  -- Global scaling control
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 RESOLUTION SCALING") },
  max_res_slider,
  dt.new_widget("separator") {},

  -- img2img section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 IMAGE TO IMAGE") },
  dt.new_widget("label") { label = _("Model Preset:") },
  model_selector,
  info_label,
  dt.new_widget("label") { label = _("Scene / Subject:") },
  scene_selector,
  dt.new_widget("label") { label = _("Additional Prompt:") },
  prompt_entry,
  dt.new_widget("label") { label = _("Additional Negative:") },
  negative_entry,
  denoise_slider,
  dt.new_widget("label") { label = _("LoRA:") },
  fetch_lora_btn,
  lora_selector,
  lora_strength_slider,
  dt.new_widget("label") { label = _("ControlNet Guide (optional):") },
  cn_guide_selector,
  cn_strength_slider,
  img2img_runs_slider,
  send_btn,
  upload_btn,
  img2img_preset_combo,
  img2img_preset_load,
  img2img_preset_save,
  img2img_preset_delete,
  dt.new_widget("separator") {},

  -- Inpaint section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 INPAINT (MASK-BASED)") },
  dt.new_widget("label") { label = _("Model Preset:") },
  inpaint_model_selector,
  inpaint_refinement_selector,
  dt.new_widget("label") { label = _("Mask Image Path (white=inpaint):") },
  inpaint_mask_entry,
  dt.new_widget("label") { label = _("Prompt:") },
  inpaint_prompt_entry,
  dt.new_widget("label") { label = _("Negative:") },
  inpaint_negative_entry,
  inpaint_denoise_slider,
  inpaint_runs_slider,
  inpaint_send_btn,
  inpaint_preset_combo,
  inpaint_preset_load,
  inpaint_preset_save,
  inpaint_preset_delete,
  dt.new_widget("separator") {},

  -- Face swap section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 FACE SWAP (SAVED MODEL)") },
  fetch_face_btn,
  face_model_selector,
  swap_model_selector,
  faceswap_btn,
  dt.new_widget("separator") {},

  -- Save Face Model section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 SAVE FACE MODEL (REACTOR)") },
  dt.new_widget("label") { label = _("Model Name:") },
  save_face_model_name_entry,
  save_face_model_overwrite_check,
  save_face_model_btn,
  dt.new_widget("separator") {},

  -- mtb Face Swap section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 FACE SWAP (MTB DIRECT)") },
  dt.new_widget("label") { label = _("Source Face Image Path:") },
  mtb_source_entry,
  mtb_analysis_selector,
  mtb_swap_selector,
  dt.new_widget("label") { label = _("Face Index:") },
  mtb_face_idx_entry,
  mtb_swap_btn,
  dt.new_widget("separator") {},

  -- Wan I2V section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 WAN 2.2 IMAGE TO VIDEO") },
  wan_model_selector,
  wan_video_preset_selector,
  dt.new_widget("label") { label = _("Prompt:") },
  wan_prompt_entry,
  dt.new_widget("label") { label = _("Negative:") },
  wan_neg_entry,
  wan_frames_slider,
  wan_steps_slider,
  wan_cfg_slider,
  wan_shift_slider,
  wan_second_step_slider,
  wan_upscale_check,
  wan_upscale_factor_slider,
  wan_interpolate_check,
  wan_pingpong_check,
  wan_accel_check,
  wan_accel_strength_slider,
  fetch_wan_lora_btn,
  wan_lora_high_1,
  wan_lora_low_1,
  wan_lora_str_slider_1,
  wan_lora_high_2,
  wan_lora_low_2,
  wan_lora_str_slider_2,
  wan_lora_high_3,
  wan_lora_low_3,
  wan_lora_str_slider_3,
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 END IMAGE (VACE START\xe2\x86\x92END)") },
  wan_end_image_entry,
  wan_vace_strength_slider,
  wan_runs_slider,
  wan_send_full_btn,
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 SELECTION REGION") },
  wan_crop_x_slider,
  wan_crop_y_slider,
  wan_crop_w_slider,
  wan_crop_h_slider,
  wan_send_sel_btn,
  wan_preset_combo,
  wan_preset_load,
  wan_preset_save,
  wan_preset_delete,
  dt.new_widget("separator") {},

  -- Klein Flux2 section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 KLEIN FLUX2 DISTILLED") },
  klein_model_selector,
  dt.new_widget("label") { label = _("Prompt:") },
  klein_prompt_entry,
  klein_steps_slider,
  klein_guidance_slider,
  klein_runs_slider,
  klein_send_btn,
  klein_preset_combo,
  klein_preset_load,
  klein_preset_save,
  klein_preset_delete,
  dt.new_widget("separator") {},

  -- PuLID Flux section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 PULID FLUX (FACE IDENTITY)") },
  dt.new_widget("label") { label = _("Prompt:") },
  pulid_prompt_entry,
  dt.new_widget("label") { label = _("Face Reference Image Path:") },
  pulid_face_entry,
  pulid_strength_slider,
  pulid_steps_slider,
  pulid_guidance_slider,
  pulid_send_btn,
  dt.new_widget("separator") {},

  -- Face Swap Direct (ReActor) section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 FACE SWAP (DIRECT/REACTOR)") },
  dt.new_widget("label") { label = _("Source Face Image Path:") },
  fsd_source_entry,
  fsd_swap_selector,
  fsd_send_btn,
  dt.new_widget("separator") {},

  -- FaceID (IPAdapter) section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 FACEID (IPADAPTER)") },
  faceid_preset_selector,
  dt.new_widget("label") { label = _("Face Reference Image Path:") },
  faceid_face_entry,
  dt.new_widget("label") { label = _("Prompt:") },
  faceid_prompt_entry,
  dt.new_widget("label") { label = _("Negative:") },
  faceid_neg_entry,
  faceid_weight_slider,
  faceid_weight_v2_slider,
  faceid_denoise_slider,
  faceid_send_btn,
  dt.new_widget("separator") {},

  -- Klein + Reference section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 KLEIN FLUX2 + REFERENCE") },
  kleinref_model_selector,
  dt.new_widget("label") { label = _("Prompt:") },
  kleinref_prompt_entry,
  dt.new_widget("label") { label = _("Reference Image Path:") },
  kleinref_ref_entry,
  kleinref_steps_slider,
  kleinref_guidance_slider,
  kleinref_send_btn,
  dt.new_widget("separator") {},

  -- Invisible Watermark section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 INVISIBLE WATERMARK") },
  dt.new_widget("button") {
    label = _("Embed Watermark"),
    tooltip = _("Hide encrypted metadata in selected images (LSB steganography, save as PNG)"),
    clicked_callback = function()
      local images = dt.gui.selection()
      if #images == 0 then dt.print(_("No images selected")); return end
      local steg_script = dt.configuration.config_dir .. "/lua/contrib/spellcaster_steg.py"
      if not io.open(steg_script, "r") then
        dt.print(_("Error: spellcaster_steg.py not found alongside the plugin"))
        return
      end
      for i, img in ipairs(images) do
        dt.print(string.format(_("Embedding watermark %d/%d"), i, #images))
        local ok, err = pcall(function()
          local path, fname = export_to_temp(img)
          if not path then error("Export failed") end
          local out = path .. ".steg.png"
          local meta = string.format(
            '{"tool":"Spellcaster","timestamp":"%s","source":"darktable"}',
            os.date("!%Y-%m-%dT%H:%M:%SZ"))
          local cmd = string.format(
            'python "%s" embed "%s" "%s" --json \'%s\'',
            shell_esc(steg_script), shell_esc(path), shell_esc(out), meta)
          os.execute(cmd)
          os.remove(path)
          if io.open(out, "r") then
            dt.database.import(out)
            dt.print(_("Watermark embedded: ") .. out)
          else
            dt.print(_("Watermark embedding failed"))
          end
        end)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
        end
      end
    end
  },
  dt.new_widget("button") {
    label = _("Read Watermark"),
    tooltip = _("Extract hidden metadata from selected images"),
    clicked_callback = function()
      local images = dt.gui.selection()
      if #images == 0 then dt.print(_("No images selected")); return end
      local steg_script = dt.configuration.config_dir .. "/lua/contrib/spellcaster_steg.py"
      local img = images[1]
      local path, fname = export_to_temp(img)
      if not path then dt.print(_("Export failed")); return end
      local tmp_out = tmp_dir() .. sep .. "steg_read_" .. os.time() .. ".txt"
      local cmd = string.format(
        'python "%s" read "%s" > "%s" 2>&1',
        shell_esc(steg_script), shell_esc(path), shell_esc(tmp_out))
      os.execute(cmd)
      os.remove(path)
      local f = io.open(tmp_out, "r")
      if f then
        local result = f:read("*all"); f:close(); os.remove(tmp_out)
        dt.print(result)
      else
        dt.print(_("No watermark data found"))
      end
    end
  },
  dt.new_widget("separator") {},

  -- Remove Background section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 REMOVE BACKGROUND") },
  dt.new_widget("button") {
    label = _("Remove Background"),
    tooltip = _("Remove background from selected images (transparent PNG)"),
    clicked_callback = function()
      local images = dt.gui.selection()
      if #images == 0 then dt.print(_("No images selected")); return end
      for i, img in ipairs(images) do
        dt.print(string.format(_("Removing background %d/%d"), i, #images))
        local ok, err = pcall(process_rembg, img)
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster rembg error: " .. tostring(err))
        end
      end
    end
  },
  dt.new_widget("separator") {},

  -- Upscale 4x section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 UPSCALE 4X") },
  dt.new_widget("label") { label = _("Upscale Model:") },
  upscale_model_selector,
  upscale_send_btn,
  dt.new_widget("separator") {},

  -- Object Removal (LaMa) section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 OBJECT REMOVAL (LAMA)") },
  dt.new_widget("label") { label = _("Mask Image Path (white=remove):") },
  lama_mask_entry,
  lama_send_btn,
  dt.new_widget("separator") {},

  -- Color Grading / LUT section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 COLOR GRADING / LUT") },
  dt.new_widget("label") { label = _("LUT Preset:") },
  lut_selector,
  lut_strength_slider,
  lut_send_btn,
  dt.new_widget("separator") {},

  -- Outpaint / Extend Canvas section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 OUTPAINT / EXTEND CANVAS") },
  dt.new_widget("label") { label = _("Prompt:") },
  outpaint_prompt_entry,
  dt.new_widget("label") { label = _("Negative:") },
  outpaint_negative_entry,
  outpaint_pad_left_slider,
  outpaint_pad_right_slider,
  outpaint_pad_top_slider,
  outpaint_pad_bottom_slider,
  outpaint_runs_slider,
  outpaint_send_btn,
  outpaint_preset_combo,
  outpaint_preset_load,
  outpaint_preset_save,
  outpaint_preset_delete,
  dt.new_widget("separator") {},

  -- Style Transfer (IPAdapter) section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 STYLE TRANSFER (IPADAPTER)") },
  dt.new_widget("label") { label = _("Style Reference Image Path:") },
  style_ref_entry,
  dt.new_widget("label") { label = _("Prompt:") },
  style_prompt_entry,
  style_strength_slider,
  style_runs_slider,
  style_send_btn,
  style_preset_combo,
  style_preset_load,
  style_preset_save,
  style_preset_delete,
  dt.new_widget("separator") {},

  -- Face Restore section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 FACE RESTORE") },
  dt.new_widget("label") { label = _("Face Restore Model:") },
  face_restore_model_selector,
  face_restore_visibility_slider,
  face_restore_codeformer_slider,
  face_restore_send_btn,
  dt.new_widget("separator") {},

  -- Photo Restoration Pipeline section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 PHOTO RESTORATION PIPELINE") },
  dt.new_widget("label") { label = _("Upscale Model:") },
  photo_restore_upscale_selector,
  dt.new_widget("label") { label = _("Face Model: (uses Face Restore selector above)") },
  photo_restore_sharpen_slider,
  photo_restore_send_btn,
  dt.new_widget("separator") {},

  -- Detail Hallucination section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 DETAIL HALLUCINATION") },
  dt.new_widget("label") { label = _("Model: (uses img2img Model Preset above)") },
  detail_level_selector,
  dt.new_widget("label") { label = _("Prompt:") },
  detail_prompt_entry,
  detail_runs_slider,
  detail_send_btn,
  dt.new_widget("separator") {},

  -- Colorize B&W section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 COLORIZE B&W PHOTO") },
  dt.new_widget("label") { label = _("Model: (uses img2img Model Preset above)") },
  colorize_strength_slider,
  colorize_denoise_slider,
  dt.new_widget("label") { label = _("Prompt:") },
  colorize_prompt_entry,
  dt.new_widget("label") { label = _("Negative:") },
  colorize_negative_entry,
  colorize_runs_slider,
  colorize_send_btn,
  colorize_preset_combo,
  colorize_preset_load,
  colorize_preset_save,
  colorize_preset_delete,
  dt.new_widget("separator") {},

  -- Batch Variations section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 BATCH VARIATIONS (TXT2IMG)") },
  dt.new_widget("label") { label = _("Model/Prompt: (uses img2img settings above)") },
  batch_width_slider,
  batch_height_slider,
  batch_count_slider,
  batch_runs_slider,
  batch_send_btn,
  dt.new_widget("separator") {},

  -- (ControlNet Suite integrated into img2img section above)

  -- IC-Light Relighting section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 IC-LIGHT RELIGHTING (SD1.5)") },
  iclight_preset_selector,
  iclight_multiplier_slider,
  iclight_runs_slider,
  iclight_send_btn,
  iclight_preset_combo,
  iclight_preset_load,
  iclight_preset_save,
  iclight_preset_delete,
  dt.new_widget("separator") {},

  -- SUPIR AI Restoration section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 SUPIR AI RESTORATION") },
  supir_model_selector,
  supir_denoise_slider,
  supir_steps_slider,
  dt.new_widget("label") { label = _("Prompt:") },
  supir_prompt_entry,
  supir_runs_slider,
  supir_send_btn,
  dt.new_widget("separator") {},

  -- SeedV2R Upscaler section
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 SEEDV2R UPSCALER") },
  seedv2r_hallucination_combo,
  seedv2r_scale_combo,
  seedv2r_upscale_model_combo,
  seedv2r_ckpt_combo,
  dt.new_widget("label") { label = _("Prompt:") },
  seedv2r_prompt_entry,
  dt.new_widget("label") { label = _("Negative:") },
  seedv2r_negative_entry,
  seedv2r_runs_slider,
  seedv2r_send_btn,
}

local module_installed = false

local function install_module()
  if not module_installed then
    dt.register_lib(
      MODULE_NAME,
      _("Spellcaster"),
      true,   -- expandable
      true,   -- resetable
      {[dt.gui.views.lighttable] = {"DT_UI_CONTAINER_PANEL_RIGHT_CENTER", 99}},
      module_widget,
      nil,    -- view_enter
      nil     -- view_leave
    )
    module_installed = true
  end
end

local function destroy()
  dt.gui.libs[MODULE_NAME].visible = false
end

local function restart()
  dt.gui.libs[MODULE_NAME].visible = true
end

-- Darktable plugins can only register UI modules when the target view is active.
-- If we're already in lighttable, register immediately. Otherwise, defer until
-- the user switches from darkroom to lighttable (view-changed event).
if dt.gui.current_view().id == "lighttable" then
  install_module()
else
  dt.register_event(
    MODULE_NAME, "view-changed",
    function(event, old_view, new_view)
      if new_view.name == "lighttable" and old_view.name == "darkroom" then
        install_module()
      end
    end
  )
end

-- Wire up lifecycle callbacks for script_manager.
-- "hide" destroy_method means the module stays registered but becomes invisible,
-- making show/restart instant without re-creating all widgets.
script_data.destroy = destroy
script_data.restart = restart
script_data.destroy_method = "hide"
script_data.show = restart

dt.print(_("Spellcaster loaded - img2img, inpaint, face swap, Wan I2V, Klein Flux2, PuLID Flux, FaceID, Klein+Ref, batch, ControlNet, IC-Light, SUPIR"))

-- ═══════════════════════════════════════════════════════════════════════
-- Auto-updater (GitHub-based self-update mechanism)
-- ═══════════════════════════════════════════════════════════════════════
-- On every plugin load, checks the GitHub API for the latest commit SHA
-- on the main branch. If it differs from the locally stored SHA (in
-- .spellcaster_version), downloads updated files and overwrites them.
--
-- Update flow:
--   1. Read local SHA from .spellcaster_version (empty = first run)
--   2. Fetch latest commit SHA from GitHub API (8s timeout)
--   3. If different: download each file to .tmp, then atomic rename
--   4. Write new SHA to .spellcaster_version
--   5. Prompt user to restart Darktable
--
-- The entire check runs inside pcall() so network failures never
-- prevent the plugin from loading. The --max-time flags on curl
-- ensure the check doesn't block plugin startup for more than ~10s.
local function spellcaster_auto_update()
  local sep = package.config:sub(1,1)           -- '\' on Windows, '/' on Unix
  local mv  = (sep == "\\") and "move /y" or "mv -f"  -- platform-appropriate rename
  local plugin_dir = debug.getinfo(1, "S").source:sub(2):match("(.*[/\\])") or ("." .. sep)
  local version_file = plugin_dir .. ".spellcaster_version"
  local api_url  = "https://api.github.com/repos/laboratoiresonore/spellcaster/commits?sha=main&per_page=1"
  local tree_url = "https://api.github.com/repos/laboratoiresonore/spellcaster/git/trees/main?recursive=1"
  local raw_base = "https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main"
  local dt_prefix = "plugins/darktable/"

  -- Read local SHA (fast path: if matches remote, no downloads needed)
  local local_sha = ""
  local fv = io.open(version_file, "r")
  if fv then local_sha = fv:read("*l") or ""; fv:close() end

  -- Fetch latest commit SHA from GitHub API (short timeout to avoid blocking startup)
  local api_tmp = os.tmpname()
  local ok = os.execute(string.format(
    'curl -s -A "spellcaster-dt/2.0" --max-time 8 -o "%s" "%s"', shell_esc(api_tmp), shell_esc(api_url)))
  if not (ok == 0 or ok == true) then os.remove(api_tmp); return end

  local fa = io.open(api_tmp, "r")
  if not fa then return end
  local api_body = fa:read("*a"); fa:close(); os.remove(api_tmp)
  local latest_sha = api_body:match('"sha"%s*:%s*"([a-f0-9]+)"')
  if not latest_sha or latest_sha == local_sha then return end  -- already up to date

  -- Dynamic file discovery: fetch the repo tree to find ALL darktable plugin files
  -- This replaces the old hardcoded list so new files are automatically picked up.
  local update_files = {}
  local tree_tmp = os.tmpname()
  local tree_ok = os.execute(string.format(
    'curl -s -A "spellcaster-dt/2.0" --max-time 15 -o "%s" "%s"', shell_esc(tree_tmp), shell_esc(tree_url)))
  if tree_ok == 0 or tree_ok == true then
    local ft = io.open(tree_tmp, "r")
    if ft then
      local tree_body = ft:read("*a"); ft:close()
      -- Extract file paths under plugins/darktable/ from the JSON tree
      -- Pattern matches: "path":"plugins/darktable/filename.ext","type":"blob"
      for path in tree_body:gmatch('"path"%s*:%s*"(' .. dt_prefix:gsub("/", "/") .. '[^"]-)"') do
        -- Only top-level files (no subdirectories)
        local filename = path:sub(#dt_prefix + 1)
        if not filename:find("/") and filename ~= "" then
          table.insert(update_files, { src = path, dst = filename })
        end
      end
    end
  end
  os.remove(tree_tmp)

  -- Fallback to static list if tree API returned nothing
  if #update_files == 0 then
    update_files = {
      { src = "plugins/darktable/comfyui_connector.lua",     dst = "comfyui_connector.lua" },
      { src = "plugins/darktable/installer_background.png",  dst = "installer_background.png" },
      { src = "plugins/darktable/splash.py",                 dst = "splash.py" },
      { src = "plugins/darktable/spellcaster_steg.py",       dst = "spellcaster_steg.py" },
      { src = "plugins/darktable/darktable_splash.jpg",      dst = "darktable_splash.jpg" },
    }
  end

  -- Download updated files: write to .tmp first, then rename for atomic replacement
  local updated = 0
  for _, f in ipairs(update_files) do
    local url = raw_base .. "/" .. f.src
    local dest = plugin_dir .. f.dst
    local tmp  = dest .. ".tmp"
    local dl = os.execute(string.format(
      'curl -s -A "spellcaster-dt/2.0" --max-time 30 -o "%s" "%s"', shell_esc(tmp), shell_esc(url)))
    if dl == 0 or dl == true then
      os.execute(string.format('%s "%s" "%s"', mv, shell_esc(tmp), shell_esc(dest)))
      updated = updated + 1
    else
      os.remove(tmp)  -- clean up failed download
    end
  end

  -- Record the new SHA so the next startup skips the download
  if updated > 0 then
    local fv2 = io.open(version_file, "w")
    if fv2 then fv2:write(latest_sha); fv2:close() end
    dt.print(string.format(_("Spellcaster updated to %s (%d files). Please restart Darktable."),
             latest_sha:sub(1, 7), updated))
  end
end

-- Run update check wrapped in pcall: network/file errors must never
-- prevent the plugin from loading and functioning normally.
pcall(spellcaster_auto_update)

return script_data
