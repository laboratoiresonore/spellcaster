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

    COMPREHENSIVE MODULE OVERVIEW
    ===============================
    Bridge between Darktable (photo editor) and ComfyUI (AI image/video server).
    Provides access to 20+ AI image/video workflows via an intuitive Lua plugin UI.

    ARCHITECTURE
    ============
    Data Flow:
      1. User selects image(s) in Darktable lighttable view
      2. Plugin exports selected image(s) to temporary PNG files
      3. Constructs workflow-specific JSON (see section: Workflow JSON builders)
      4. Uploads JSON + images via ComfyUI REST API (curl-based HTTP)
      5. Polls /history endpoint until ComfyUI finishes processing
      6. Downloads output image(s) or video(s)
      7. Imports results back into Darktable collection

    HTTP Communication: curl via shell escaping (see section: HTTP communication)
      - No native Lua HTTP library (Lua sandbox in Darktable)
      - curl avoids platform-specific C module loading fragility
      - Temp files hold JSON/images to avoid shell quoting hell
      - All requests: write file → curl → read response → cleanup

    Supported Workflows (20+ operations):
      IMAGE TRANSFORMATION:
        - img2img     : SD1.5 / SDXL / Illustrious checkpoint-based image-to-image
        - Inpaint     : Mask-guided regeneration of image regions (SetLatentNoiseMask)
        - LUT         : Lookup-table color grading application
        - Style Transfer : Style reference image → style on target (perceptual loss)

      FACE OPERATIONS:
        - Face Swap   : ReActor (saved model + direct) and mtb facetools
        - FaceID      : IPAdapter-based face identity transfer
        - PuLID Flux  : Face identity transfer using PuLID on Flux architecture
        - Face Restore : CodeFormer + upscale for damaged faces

      ADVANCED GENERATION:
        - Klein Flux2 : Distilled Flux2 img2img (with optional reference image)
        - Wan I2V     : Wan 2.2 image-to-video (dual-UNET high/low noise schedules)
        - Outpaint    : Expand image canvas (AddDiffusion boundary expansion)
        - Detail Hallucinate : ControlNet-based detail enhancement
        - Colorize    : Grayscale → color (T2I ControlNet)

      QUALITY/RESTORATION:
        - Photo Restore : Upscale + face restore + optional sharpening
        - Upscale     : 2x-4x with RealESRGAN/other models
        - RemBG       : Transparent background removal
        - LAMA Inpaint : AI-powered object removal via mask
        - SUPIR       : Super-resolution with SDXL refinement
        - SeedV2R      : Seed-based variation with upscale

      BATCH:
        - Batch Txt2Img : Generate variations from prompt (no input image)
        - Batch Variations : Multiple seeds/variations on single input
        - ICLight      : Relighting with intensity control

    FILE MAP (approximate line numbers)
    ===================================
      ~2-8      : GPL license header
      ~10-43    : Module overview and README
      ~45-78    : Darktable API bootstrap + gettext i18n setup
      ~79-583   : MODEL_PRESETS (18+ checkpoint configs + metadata)
      ~585-615  : scene_arch() — map model arch to scene prompt library
      ~616-628  : ARCH_LORA_PREFIXES — architecture → LoRA folder filters
      ~629-682  : Helper functions (starts_with, filter_loras_for_arch, get_turbo_config)
      ~687-702  : Preferences (server_url, timeout_override from darktablerc)
      ~703-818  : HTTP via curl (get_server, tmp_dir, shell_esc, curl_*, json_val, fetch_all_loras)
      ~820-975  : img2img + ControlNet workflow builders
      ~976-1115 : Face Swap builders (ReActor model-based, direct, save, fetch models)
      ~1116-1180: Background removal, upscale, LUT, LAMA inpaint builders
      ~1181-1265: Outpaint, style transfer, face restore builders
      ~1266-1420: Photo restore, detail hallucinate, colorize, mtb faceswap builders
      ~1420-1652: Wan I2V builder and video-dimension computation
      ~1652-1750: Wan LoRA helpers (fetch, filter, noise detection, concept keys)
      ~1750-1920: Klein Flux2 builder (with optional reference image support)
      ~1920-2055: PuLID Flux + FaceID builders
      ~2055-2460: Klein reference + inpaint builders
      ~2460-2650: Batch txt2img, ICLight, SUPIR builders
      ~2650-2810: SeedV2R, processing locks (prevent concurrent runs)
      ~2810-2900: Image export, splash screen, result polling
      ~2900-3900: Process* wrappers (img2img → process_image, etc.)
      ~3900-3960: Preset save/load (serialize to darktablerc)
      ~3960-4850: UI widget builders (sliders, combos, buttons, text boxes)
      ~4850-4950: Wan I2V specific UI (lora combos for 3 steps)
      ~4950-7200: Main UI construction + control callbacks
      ~7200-7300: Install/destroy/restart (script_manager lifecycle)

    KEY DATA STRUCTURES
    ===================
    MODEL_PRESETS (table, ~80 entries)
      - Checkpoint config bundles (ckpt path, steps, CFG, sampler, scheduler, hints)
      - Each has: label, arch ("sd15"/"sdxl"/"flux2klein"/etc.), ckpt, steps, cfg,
                  denoise, sampler, scheduler, prompt_hint, negative_hint
      - Architecture determines compatible LoRAs and scene prompts

    SCENE_PRESETS (referenced but not shown; used for prompt templates)
      - Maps (scene_name, architecture) → prompt template
      - Architecture keys: "sd15", "sdxl", "sdxl_anime", "sdxl_cartoon", "flux"
      - Allows one scene prompt to work across multiple architectures

    Workflow JSON (string-based, not Lua tables)
      - ComfyUI workflows are JSON DAGs with node_id → {class_type, inputs}
      - Built as formatted strings (no JSON library in Darktable Lua)
      - Nodes reference outputs via ["node_id", index] arrays
      - Common structure: LoadImage → Scale down → Process → Scale up → SaveImage

    REQUIREMENTS
    ============
      - curl (built into Windows 10+, macOS, Linux)
      - Running ComfyUI server (127.0.0.1:8188 or configured via preferences)
      - Supported checkpoint files (.safetensors) on ComfyUI's models/checkpoints/
      - LoRA files (if using model-specific LoRAs)

    Enable via script_manager in Darktable lighttable view.

    USAGE WALKTHROUGH (TYPICAL WORKFLOW)
    ====================================
    1. START DARKTABLE + ENABLE SPELLCASTER
       - Open Darktable → Preferences → Lua → check "Spellcaster" → restart
       - "Spellcaster" panel appears in lighttable view (right side)

    2. VERIFY COMFYUI IS RUNNING
       - Start ComfyUI server (address shown in preferences, default: 127.0.0.1:8188)
       - Test: click "Send Test Message" button

    3. SELECT IMAGES IN LIGHTTABLE
       - Collection mode: click on one or more images (highlighted border)
       - Selection shows: "1 image" / "3 images" in dt status bar

    4. CHOOSE WORKFLOW (example: img2img)
       - Model: pick "SDXL - Juggernaut" (or any preset)
       - Prompt: "a portrait, professional lighting, detailed face"
       - Negative: "blurry, low quality" (optional)
       - Scene Preset: "(custom)" or pick a template
       - LoRA: "Fetch LoRAs" button → pick one or leave as "(none)"
       - Send → workflow uploads image, processes on ComfyUI, downloads result

    5. IMPORT RESULTS
       - Result appears in Darktable automatically after processing finishes
       - New image in collection (labeled with workflow name)
       - Check history view to see all generated versions

    6. ADVANCED: CONFIGURE SETTINGS
       - Preferences → Lua → comfyui_connector:
         * Server URL: http://127.0.0.1:8188 (adjust to your setup)
         * Timeout: 300 (seconds, for images) / 600 (for video)
       - Max Resolution: slider to limit GPU memory usage (0 = no scaling)

    ARCHITECTURE DECISIONS EXPLAINED
    ================================
    Q: Why build workflows as JSON strings instead of Lua tables?
    A: - No JSON library in Darktable's embedded Lua
       - String templates show the ComfyUI node DAG visually (easier debug)
       - Static structure per workflow type; only values change

    Q: Why use curl instead of a Lua HTTP library?
    A: - Darktable Lua sandbox can't reliably load native C modules (luasocket, lua-curl)
       - curl is universally available (Windows 10+, macOS, Linux)
       - Temp files avoid shell command-line length limits and escaping hell

    Q: How are prompts "prepped" by model hints?
    A: - USER enters: "a girl"
       - MODEL PRESET has prompt_hint: "photorealistic, detailed, sharp focus"
       - FINAL prompt: "photorealistic, detailed, sharp focus, a girl"
       - This steers the model toward its trained strength (photo vs. anime vs. cartoon)

    Q: Why downscale/upscale around processing?
    A: - Keeps GPU memory bounded (configurable max_res slider)
       - SD/SDXL operate at 8x8 latent granularity → scale to multiples of 8
       - Aspect ratio preserved mathematically (scale one dimension, then math.floor)
       - Output is upscaled back to original resolution (preserves quality)

    DEBUGGING TIPS
    ==============
    • Check Darktable → Preferences → Lua → comfyui_connector
      Server URL and timeout should match your ComfyUI setup
    • Ensure ComfyUI is running: http://127.0.0.1:8188 (or your IP:port)
    • Test connection: "Send Test Message" button
    • Check Darktable message log (bottom bar): shows export/upload/processing steps
    • Look at ComfyUI web terminal for detailed node execution logs
    • For video (Wan I2V), timeout may need to increase to 10+ minutes

    CODE STRUCTURE NOTES FOR DEVELOPERS
    ===================================
    • Adding a new workflow? Copy an existing build_*_json() function
    • Add corresponding process_*() wrapper (orchestrates export/upload/poll/import)
    • Add UI controls in the widget section (~line 4970)
    • Add button clicked_callback that calls process_*()
    • Test with small images first (compute is slow, ~minutes per image)
    • Workflow builders are at lines ~1085 (img2img), ~1300 (faceswap), etc.
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
function _(msgid) return gettext(msgid) end

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

function scene_arch(model_arch, model_label)
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
  sd15         = {},  -- no dedicated SD 1.5 LoRA folders currently
  sdxl         = {"SDXL\\", "Illustrious\\", "Illustrious-Pony\\", "Pony\\"},
  zit          = {"Z-Image-Turbo\\"},
  illustrious  = {"Illustrious\\", "Illustrious-Pony\\"},
  pony         = {"Pony\\", "Illustrious-Pony\\"},
  flux2klein   = {"Flux-2-Klein\\"},
  flux1dev     = {"Flux-1-Dev\\", "Flux\\"},
  flux_kontext = {"Flux-1-Dev\\"},
  ltx          = {"ltxv\\", "LTX\\"},
  wan          = {"Wan\\", "WAN\\", "Wan-2.2-I2V\\"},
  seedvr       = {"SeedVR\\", "seedvr\\"},
}

-- Image arches: root-folder LoRAs + empty-prefix fallback are safe to
-- admit only here. Video arches (wan/ltx/seedvr) must keep a strict
-- folder match so stray image LoRAs don't slip in.
local IMAGE_ARCHES_SET = {
  sd15 = true, sdxl = true, zit = true, illustrious = true, pony = true,
  flux2klein = true, flux1dev = true, flux_kontext = true, chroma = true,
}

-- Video-LoRA markers (lowercase pattern → Lua pattern). Any LoRA
-- whose lowered path contains one of these is a video LoRA and must
-- NEVER appear in an image-arch picker. Mirrors the _VIDEO_LORA_RE
-- regex in the GIMP plugin (patterns kept simple enough for Lua's
-- lowered plain-string matching).
local VIDEO_LORA_MARKERS = {
  "wan2.1", "wan2.2", "wan-2.1", "wan-2.2",
  "wan_2_1", "wan_2_2", "wan21", "wan22",
  "/i2v", "_i2v_", "-i2v-", "_i2v.", "-i2v.",
  "high_noise", "low_noise", "highnoise", "lownoise",
  "high-noise", "low-noise",
  "lightx2v", "wan-lightning", "wan_lightning",
  "ltx2", "ltx-2", "ltx_2", "ltxv", "ltx-distill", "ltx_distill",
  "seed-vr", "seedvr",
}

function starts_with(str, prefix)
  return str:sub(1, #prefix) == prefix
end

function _looks_like_video_lora(lora_lower)
  for _, marker in ipairs(VIDEO_LORA_MARKERS) do
    if lora_lower:find(marker, 1, true) then
      return true
    end
  end
  return false
end

function filter_loras_for_arch(all_loras, arch)
  -- Three gates, progressively more permissive, matching the canonical
  -- _filter_loras_for_arch in the GIMP plugin:
  --   1. case-insensitive folder prefix match (Linux/macOS servers
  --      return lowercase paths; our prefixes are mixed case);
  --   2. root-folder LoRAs for image arches (no subfolder separator
  --      so no strict arch inference is possible — admit them);
  --   3. empty-prefix image arches (sd15) get every non-video LoRA
  --      rather than an unconditional empty list.
  -- Video markers in the lowered path reject WAN/LTX/SeedVR LoRAs
  -- from ever surfacing in an image arch.
  local prefixes = ARCH_LORA_PREFIXES[arch]
  local is_image_arch = IMAGE_ARCHES_SET[arch] == true
  local prefix_variants = {}
  if prefixes then
    for _, p in ipairs(prefixes) do
      local pl = p:lower()
      table.insert(prefix_variants, pl)
      local alt = pl:gsub("\\", "/")
      if alt ~= pl then table.insert(prefix_variants, alt) end
    end
  end
  local filtered = {}
  for _, lora in ipairs(all_loras) do
    local lora_lower = lora:lower()
    -- Image arches always reject video-marker LoRAs first.
    if is_image_arch and _looks_like_video_lora(lora_lower) then
      -- skip
    else
      local admitted = false
      -- Gate 1
      for _, pv in ipairs(prefix_variants) do
        if starts_with(lora_lower, pv) then
          admitted = true
          break
        end
      end
      -- Gate 2 — root-folder LoRA (no separator), image arches only.
      if (not admitted) and is_image_arch
          and not lora:find("[\\/]") then
        admitted = true
      end
      -- Gate 3 — empty-prefix image arch: admit any non-video LoRA.
      if (not admitted) and is_image_arch
          and (not prefixes or #prefixes == 0) then
        admitted = true
      end
      if admitted then
        table.insert(filtered, lora)
      end
    end
  end
  return filtered
end

-- ── Turbo acceleration configs per architecture ──────────────────────
-- Hyper-SD LoRAs (ByteDance) — 8-step CFG-preserving variants.
-- These support negative prompts (cfg 5-8). ZIT and flux2klein
-- are already fast (4 steps) so no turbo config is needed.
local TURBO_CONFIGS = {
  sd15 = {
    label = "Hyper-SD15 8-step",
    lora  = "Hyper-SD15-8steps-CFG-lora.safetensors",
    strength_model = 1.0, strength_clip = 1.0,
    sampler = "ddim", scheduler = "sgm_uniform",
    steps = 8, cfg = 5.0,
  },
  sdxl = {
    label = "Hyper-SDXL 8-step",
    lora  = "Hyper-SDXL-8steps-CFG-lora.safetensors",
    strength_model = 1.0, strength_clip = 1.0,
    sampler = "ddim", scheduler = "sgm_uniform",
    steps = 8, cfg = 5.0,
  },
  flux1dev = {
    label = "Hyper-FLUX 8-step",
    lora  = "Hyper-FLUX.1-dev-8steps-lora.safetensors",
    strength_model = 0.125, strength_clip = 0.125,
    sampler = "euler", scheduler = "simple",
    steps = 8, cfg = 3.5,
  },
  flux_kontext = {
    label = "Hyper-FLUX 8-step",
    lora  = "Hyper-FLUX.1-dev-8steps-lora.safetensors",
    strength_model = 0.125, strength_clip = 0.125,
    sampler = "euler", scheduler = "simple",
    steps = 8, cfg = 3.5,
  },
}

function get_turbo_config(arch)
  return TURBO_CONFIGS[arch]
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

-- Wizard Guild URL — used by the cross-interface backbone (heartbeat
-- registration + event emit). Leave blank to disable the integration;
-- Darktable will still work against ComfyUI as a stand-alone tool.
dt.preferences.register(MODULE_NAME, "guild_url", "string",
  _("Wizard Guild URL (optional)"),
  _("Leave blank to run stand-alone; set to e.g. http://127.0.0.1:7777 to show Darktable in the Guild UI"),
  "http://127.0.0.1:7777")

-- Auto-poll cadence for the cross-interface inbox. 0 disables the
-- background drain (user falls back to the manual "Check Inbox"
-- button). 30 seconds is a reasonable default: low enough for peers
-- to feel instant, high enough not to hammer the Guild or wake the
-- disk every few seconds.
dt.preferences.register(MODULE_NAME, "inbox_auto_interval_s", "integer",
  _("Auto inbox poll interval (seconds, 0 = off)"),
  _("How often Darktable silently checks the Spellcaster inbox for assets other plugins sent it. 0 disables the background drain; use the 💎 Check Inbox button to pull on demand instead."),
  30, 0, 3600)

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

-- ═══════════════════════════════════════════════════════════════════════
-- SERVER CONFIGURATION
-- ═══════════════════════════════════════════════════════════════════════

local sep = "/"

-- @return string : ComfyUI server URL from preferences (e.g. "http://127.0.0.1:8188")
-- Stores in Darktable's darktablerc file (editable via Preferences → Lua → comfyui_connector)
function get_server()
  return dt.preferences.read(MODULE_NAME, "server_url", "string")
end

-- @return string : Platform-specific temp directory
-- Tries: TEMP (Windows) → TMP (Windows/POSIX) → TMPDIR (POSIX) → /tmp (fallback)
function tmp_dir()
  return os.getenv("TEMP") or os.getenv("TMP") or os.getenv("TMPDIR") or "/tmp"
end

-- SHELL ESCAPING FOR CURL COMMANDS
-- ==================================
-- Security: strip double-quotes from strings before embedding in shell commands.
-- This prevents shell injection via user-controlled values (file paths, URLs).
-- Not a full sanitizer, but sufficient because all values are either:
--   (a) internal temp paths we control, or
--   (b) user-entered paths that get wrapped in double-quotes in the command.
-- Usage: curl -s -o "outfile" "URL" where URL=shell_esc(user_url)
-- @param s : string to escape (or nil)
-- @return string : escaped version (empty if nil)
function shell_esc(s)
  if not s then return "" end
  return tostring(s):gsub('"', '')
end

-- Unique temp-file path. os.time() alone is second-granular; when two
-- curl helpers fire inside the same second (easy with a loop) the
-- response files collide and whichever command writes last wins. Mix
-- in math.random() so the probability of collision in a Darktable
-- session is effectively zero.
-- @param tag : short identifier embedded in the filename for log traces
-- @param ext : file extension including the dot (".json", ".txt", ".png")
local _tmp_seq = 0
function _unique_tmp(tag, ext)
  _tmp_seq = _tmp_seq + 1
  return string.format(
    "%s%s%s_%d_%d_%d%s",
    tmp_dir(), sep, tag,
    os.time(), math.random(100000, 999999), _tmp_seq,
    ext or "")
end

-- CURL HTTP OPERATIONS
-- ═════════════════════════════════════════════════════════════════════════
-- All HTTP uses curl (not a Lua library) invoked via os.execute().
-- Temp files hold request/response bodies to avoid shell escaping JSON.

-- GET request: fetch a URL and return the response body as a string.
-- @param url : ComfyUI API endpoint (e.g. "http://server:8188/api/object_info")
-- @return string or nil : response JSON (nil if curl fails or file can't be read)
-- Pattern:
--   1. Create temp file name with timestamp to avoid collisions
--   2. Execute: curl -s -o "tmpfile" "url"
--   3. Read tmpfile into string variable
--   4. Delete tmpfile
-- Used by: fetch_all_loras(), fetch_face_models(), fetch_swap_models(), etc.
function curl_get(url)
  local tmp = _unique_tmp("comfyui_resp", ".json")
  os.execute(string.format('curl -s -o "%s" "%s"', shell_esc(tmp), shell_esc(url)))
  local f = io.open(tmp, "r")
  if not f then return nil end
  local c = f:read("*all"); f:close(); os.remove(tmp)
  return c
end

-- POST JSON workflow to ComfyUI and return response.
-- Writes JSON body to temp file, then uses curl's @file syntax to read it.
-- This avoids embedding large JSON in shell commands (which breaks on special chars
-- and hits command-line length limits on some platforms).
-- @param url : ComfyUI API endpoint (e.g. "http://server:8188/prompt")
-- @param json_str : complete workflow JSON as a string (already formatted, no escaping needed)
-- @return string or nil : response JSON from ComfyUI (contains prompt_id on success)
-- Pattern:
--   1. Create two temp files: tb (body input) and tr (response output)
--   2. Write json_str to tb
--   3. Execute: curl -X POST -d @"tb" -o "tr" "url"
--   4. Read tr into return value, delete both temp files
-- Response format: {"prompt_id":"<uuid>","number":"<int>","..."}
-- Used by: process_image, process_wan_i2v, all AI workflows
function curl_post_json(url, json_str)
  -- Telemetry wrapper: stamps elapsed + outcome for every POST.
  -- When the target URL is ComfyUI's ``/prompt`` endpoint, fires a
  -- fire-and-forget dispatch_ok row to the Guild so SpeedCoach sees
  -- Darktable workflows alongside GIMP/Guild ones. The handler name
  -- comes from the nearest Lua function in the call stack (via
  -- ``debug.getinfo``), so submissions like ``process_faceswap_mtb``
  -- label their rows without per-site plumbing.
  local _tel_start = os.clock()
  local _tel_handler = ""
  if debug and debug.getinfo then
    for level = 3, 8 do
      local info = debug.getinfo(level, "n")
      if not info then break end
      if info.name and info.name:match("^process_") then
        _tel_handler = info.name; break
      end
    end
  end
  local tb = _unique_tmp("comfyui_body",  ".json")
  local tr = _unique_tmp("comfyui_presp", ".json")
  local f = io.open(tb, "w"); f:write(json_str); f:close()
  os.execute(string.format('curl -s -X POST -H "Content-Type: application/json" -d @"%s" -o "%s" "%s"', shell_esc(tb), shell_esc(tr), shell_esc(url)))
  os.remove(tb)
  local rf = io.open(tr, "r")
  local c = nil
  if rf then
    c = rf:read("*all"); rf:close(); os.remove(tr)
  end
  -- Fire telemetry only for workflow submissions; upload / status /
  -- presence endpoints are out of scope for SpeedCoach.
  if url:find("/prompt", 1, true) then
    local elapsed = os.clock() - _tel_start
    local failed = (c == nil or c == "" or c:find('"error"') ~= nil)
    local err_str = ""
    if failed and c then err_str = c:sub(1, 200) end
    -- ``_log_dispatch_telemetry`` is safe to call when the Guild is
    -- down (silent no-op) \u2014 see its implementation above.
    if _log_dispatch_telemetry then
      _log_dispatch_telemetry(
        _tel_handler ~= "" and _tel_handler or "darktable_prompt",
        "", "unknown", elapsed, failed, err_str)
    end
  end
  return c
end

-- Upload an image file to ComfyUI's /upload/image endpoint via multipart form.
-- ComfyUI expects the form field name "image" and reads the filename from the upload.
-- The "overwrite=true" flag lets us reuse filenames without generating unique names.
-- @param url : ComfyUI /upload/image endpoint (e.g. "http://server:8188/upload/image")
-- @param filepath : path to local PNG file exported from Darktable (e.g. "/tmp/dt_export_xyz.png")
-- @param filename : how to name the file on ComfyUI (e.g. "dt_export_xyz.png")
-- @return string or nil : response JSON (contains "name"/"subfolder" on success)
-- Pattern:
--   1. Create temp file tr for response
--   2. Execute: curl -F "image=@filepath" -F "overwrite=true" -o "tr" "url"
--   3. Read tr, delete it, return response
-- Response format: {"name":"filename","subfolder":"input","type":"input"}
-- Used by: export_to_temp + process_image (upload step)
function curl_upload(url, filepath, filename)
  local tr = _unique_tmp("comfyui_up", ".json")
  os.execute(string.format(
    'curl -s -X POST -F "image=@%s;filename=%s" -F "type=input" -F "overwrite=true" -o "%s" "%s"',
    shell_esc(filepath), shell_esc(filename), shell_esc(tr), shell_esc(url)))
  local f = io.open(tr, "r")
  if not f then return nil end
  local c = f:read("*all"); f:close(); os.remove(tr)
  return c
end

-- Download a file (image or video) from ComfyUI's /view endpoint.
-- ComfyUI stores all outputs in a folder tree; this fetches them to local disk.
-- @param url : ComfyUI /view endpoint (e.g. "http://server:8188/view?filename=output_xyz.png")
-- @param out : local path where file should be saved (e.g. "/tmp/output_xyz.png")
-- Pattern:
--   1. Execute: curl -s -o "out" "url"
--   2. Return (no response body to read; curl handles file writing)
-- Used by: result polling + importing into Darktable (see wait_result, process_image)
function curl_download(url, out)
  os.execute(string.format('curl -s -o "%s" "%s"', shell_esc(out), shell_esc(url)))
end

-- Forward declarations for helpers defined further below. Lua scopes
-- ``local`` names from declaration point forward, so we can't call a
-- local that doesn't exist yet. Declaring the names up front lets
-- other helpers (e.g. ``_download_comfyui_view``) reference them
-- before the body is filled in down at the base64 + POST site.
local _gallery_stash_after_download
local _download_comfyui_view

-- ═══════════════════════════════════════════════════════════════════════
-- Canonical-builder dispatch — talk to spellcaster_core via the Guild.
-- ═══════════════════════════════════════════════════════════════════════
--
-- CLAUDE.md §3 ("ONE SOURCE OF TRUTH"): every workflow builder lives in
-- comfyui-spellcaster/spellcaster_core/workflows.py. Inlining a Klein /
-- WAN / LTX workflow as JSON in Lua duplicates ~100-300 lines per
-- function and guarantees we'll diverge on the next bug fix. The
-- Guild's POST /api/run_builder takes a builder name + params dict and
-- runs the Python builder on our behalf.
--
-- Use ``_run_builder`` to call any build_* function and ``_download_guild_assets``
-- to pull the resulting /api/assets/<hash> URLs into Darktable's library.
-- For new image-editing features, prefer this path over inlining.

function _run_builder(builder_name, params_json)
  -- ``params_json`` MUST already be a valid JSON object literal (e.g.
  -- '{"image_filename":"foo.png","prompt_text":"a cat"}'). Caller is
  -- responsible for json_escape on string values — we pass through as-is.
  local guild = get_guild_url()
  if not guild or guild == "" then
    return nil, "Guild URL not configured (Settings > Spellcaster > guild_url)"
  end
  local server = get_server() or ""
  local body = string.format(
    '{"builder":"%s","comfy_url":"%s","params":%s}',
    json_escape(builder_name),
    json_escape(server),
    params_json or "{}")
  local resp = curl_post_json(guild .. "/api/run_builder", body)
  if not resp or resp == "" then
    return nil, "No response from Guild — is " .. guild .. " reachable?"
  end
  -- Cheap JSON-shape inspection (no full parser needed for our envelope).
  if resp:find('"ok"%s*:%s*false') then
    local err = resp:match('"error"%s*:%s*"(.-)"') or "unknown error"
    return nil, err
  end
  local urls_block = resp:match('"urls"%s*:%s*%[(.-)%]') or ""
  local urls = {}
  for u in urls_block:gmatch('"([^"]+)"') do
    table.insert(urls, u)
  end
  return urls
end

function _download_guild_assets(urls, prefix)
  -- Guild returns canonical /api/assets/<hash> URLs (AssetGallery
  -- backed). Resolve to absolute, fetch, and import each into the
  -- Darktable library so the user sees the result alongside the
  -- original. Files are stored under tmp_dir() so the OS reaps them
  -- on next reboot.
  local guild = get_guild_url()
  if not guild or guild == "" then return 0 end
  prefix = prefix or "spellcaster_result"
  local imported = 0
  for j, u in ipairs(urls or {}) do
    local full = u
    if u:sub(1, 1) == "/" then full = guild .. u end
    -- All current image builders emit PNG. If we add video builders
    -- here later, switch on the content-type or pass an explicit ext.
    local out = tmp_dir() .. sep .. prefix .. "_" .. os.time() .. "_" .. j .. ".png"
    curl_download(full, out)
    -- import returns the new dt_image_t on success; nil on failure.
    if dt.database.import(out) then imported = imported + 1 end
  end
  return imported
end

-- ═══════════════════════════════════════════════════════════════════════
-- CROSS-INTERFACE BACKBONE — heartbeat + event emit to the Wizard Guild
-- ═══════════════════════════════════════════════════════════════════════
-- The Guild's /api/interfaces registry expects each frontend (GIMP,
-- Darktable, Resolve, etc.) to ping /api/interfaces/heartbeat
-- periodically. When Darktable heartbeats, the Guild UI starts showing
-- Darktable-specific chips like "Edit in Darktable" on generated
-- images. When Darktable quits, the TTL expires and those chips
-- disappear automatically.
--
-- Darktable's Lua sandbox gives us no threading primitives, so we
-- don't run a polling loop. Instead we heartbeat on plugin load and
-- again every time the user triggers any Spellcaster action. That
-- keeps us "online" during active sessions without any background
-- work. The Guild's 30s TTL handles graceful disappearance.

function get_guild_url()
  return dt.preferences.read(MODULE_NAME, "guild_url", "string")
end

-- ── ComfyUI-side presence (phase-9) ────────────────────────────────
--
-- Zero-config cross-app discovery. Each plugin registers itself with
-- the ComfyUI-Spellcaster custom-nodes pack's /spellcaster/presence/*
-- routes so sibling plugins (GIMP, SillyTavern, Resolve) discover
-- Darktable WITHOUT needing the Wizard Guild. Presence is
-- best-effort; a Guild heartbeat still runs below for the richer
-- record when the Guild IS up.
-- Short, LAN-safe hostname so the broker can disambiguate the same
-- plugin kind running on multiple machines. Lua has no portable
-- os.hostname, so we shell out once at script load and cache.
-- NOTE: locals in Lua's main chunk count against a hard 200-slot
-- limit. Darktable plugins are loaded as a single main chunk so every
-- top-level `local X = ...` line consumes a slot file-wide. This
-- plugin had already accumulated ~200 top-level locals from widget
-- declarations; adding the presence + blob-bus + 3D helpers below
-- tipped us past the limit and Lua refused to compile with "too many
-- local variables in main function". Dropping `local` from each of
-- these decls promotes them to the file-scope globals DT plugins
-- traditionally use for cross-section access (comfy_presence_*,
-- process_normal_map, _blob_upload all have domain-unique names so
-- namespace collision is a non-issue). When more than a small number
-- of new helpers need adding, wrap them in `do ... end` to free the
-- slots instead.
function _dt_hostname()
  local f = io.popen(package.config:sub(1,1) == "\\" and "hostname" or "uname -n")
  if not f then return "dt-host" end
  local h = f:read("*l") or ""
  f:close()
  h = (h or ""):gsub("%s+$", ""):gsub("%..*$", "")  -- trim + short form
  -- Keep the broker's _safe_host charset happy.
  h = h:gsub("[^%w%-_]", "")
  if h == "" then return "dt-host" end
  return h:sub(1, 64)
end

DARKTABLE_HOST = _dt_hostname()
DARKTABLE_PRESENCE_META = {
  key = "darktable",
  label = "Darktable",
  icon = "📷",
  version = "2.0.0",
  capabilities = { "send_image", "receive_image", "raw_edit" },
  host = DARKTABLE_HOST,
  instance_id = "darktable@" .. DARKTABLE_HOST,
}

-- Fire-and-forget POST via curl. Guards: 2s timeout; stdout+stderr
-- swallowed so a missing route / ComfyUI-down doesn't flood the log.
function _comfy_presence_post(endpoint, body_str)
  local comfy = get_server()
  if not comfy or comfy == "" then return end
  local tmp = _unique_tmp("dt_presence", ".json")
  local f = io.open(tmp, "w"); if not f then return end
  f:write(body_str); f:close()
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 2 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s%s" -o NUL 2>NUL',
      shell_esc(tmp), shell_esc(comfy), shell_esc(endpoint))
  else
    cmd = string.format(
      'curl -s --max-time 2 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s%s" -o /dev/null 2>/dev/null',
      shell_esc(tmp), shell_esc(comfy), shell_esc(endpoint))
  end
  os.execute(cmd)
  os.remove(tmp)
end

-- Fire-and-forget telemetry POST to the Guild's dispatch_ok endpoint.
-- Mirrors the GIMP plugin's ``_speedcoach_post`` so SpeedCoach's
-- per-tool aggregator sees Darktable dispatches alongside GIMP ones.
-- Safe to call without a Guild running (swallows errors silently).
function _log_dispatch_telemetry(handler, builder, arch, elapsed_s, failed, err_str)
  local guild = get_guild_url()
  if not guild or guild == "" then return end
  local body = string.format(
    '{"origin":"darktable","handler":"%s","build_fn":"%s","arch":"%s","elapsed":%s,"failed":%s,"error":"%s","ts":%d}',
    json_escape(handler or ""),
    json_escape(builder or ""),
    json_escape(arch or "unknown"),
    tostring(elapsed_s or 0),
    tostring(failed and "true" or "false"),
    json_escape((err_str or ""):sub(1, 200)),
    os.time())
  local tmp = _unique_tmp("dt_tel", ".json")
  local f = io.open(tmp, "w"); if not f then return end
  f:write(body); f:close()
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 2 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/telemetry/dispatch_ok" -o NUL 2>NUL',
      shell_esc(tmp), shell_esc(guild))
  else
    cmd = string.format(
      'curl -s --max-time 2 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/telemetry/dispatch_ok" -o /dev/null 2>/dev/null',
      shell_esc(tmp), shell_esc(guild))
  end
  os.execute(cmd)
  os.remove(tmp)
end


function comfy_presence_register()
  -- Caps list as JSON array
  local caps_json = '["' .. table.concat(DARKTABLE_PRESENCE_META.capabilities, '","') .. '"]'
  local body = string.format(
    '{"key":"%s","label":"%s","icon":"%s","version":"%s","capabilities":%s,"host":"%s","instance_id":"%s"}',
    DARKTABLE_PRESENCE_META.key,
    DARKTABLE_PRESENCE_META.label,
    DARKTABLE_PRESENCE_META.icon,
    DARKTABLE_PRESENCE_META.version,
    caps_json,
    DARKTABLE_PRESENCE_META.host,
    DARKTABLE_PRESENCE_META.instance_id)
  _comfy_presence_post("/spellcaster/presence/register", body)
end

function comfy_presence_heartbeat()
  _comfy_presence_post("/spellcaster/presence/heartbeat",
    string.format('{"key":"%s","host":"%s","instance_id":"%s"}',
      DARKTABLE_PRESENCE_META.key,
      DARKTABLE_PRESENCE_META.host,
      DARKTABLE_PRESENCE_META.instance_id))
end

-- Query siblings. Returns a list of peer tables; empty on failure
-- (ComfyUI down, pack too old, etc.). Does NOT merge Guild data here —
-- the existing guild_active_peers() helper handles the Guild side so
-- callers decide which union they want.
function comfy_presence_list()
  local comfy = get_server()
  if not comfy or comfy == "" then return {} end
  local tmp = _unique_tmp("dt_peers", ".json")
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 2 "%s/spellcaster/presence/list" -o "%s" 2>NUL',
      shell_esc(comfy), shell_esc(tmp))
  else
    cmd = string.format(
      'curl -s --max-time 2 "%s/spellcaster/presence/list" -o "%s" 2>/dev/null',
      shell_esc(comfy), shell_esc(tmp))
  end
  os.execute(cmd)
  local f = io.open(tmp, "r")
  if not f then return {} end
  local body = f:read("*all"); f:close(); os.remove(tmp)
  if not body or body == "" then return {} end
  -- Minimal JSON-object extraction — Lua has no stdlib JSON. We pull
  -- each peer's key + label with a targeted pattern. Good enough for
  -- a menu render; callers should treat the returned list as advisory.
  local peers = {}
  for obj in body:gmatch('%b{}') do
    local key = obj:match('"key"%s*:%s*"([^"]+)"')
    local label = obj:match('"label"%s*:%s*"([^"]+)"') or key
    local icon = obj:match('"icon"%s*:%s*"([^"]*)"') or ""
    local host = obj:match('"host"%s*:%s*"([^"]*)"') or ""
    local instance_id = obj:match('"instance_id"%s*:%s*"([^"]+)"') or key
    -- Filter out only OUR own instance_id, not every Darktable entry —
    -- another Darktable on the LAN is a real peer worth listing.
    if instance_id and instance_id ~= DARKTABLE_PRESENCE_META.instance_id then
      table.insert(peers, {
        key = key, label = label, icon = icon,
        host = host, instance_id = instance_id,
      })
    end
  end
  return peers
end


function guild_heartbeat(meta_pairs)
  -- meta_pairs: optional flat k=v list, e.g. { active_image = "photo.raw" }
  local guild = get_guild_url()
  if not guild or guild == "" then return end
  -- Build a tiny JSON payload without pulling in a JSON library
  local meta = ""
  if meta_pairs then
    local first = true
    for k, v in pairs(meta_pairs) do
      if not first then meta = meta .. "," end
      meta = meta .. string.format('"%s":"%s"',
        tostring(k):gsub('"', "'"),
        tostring(v):gsub('"', "'"))
      first = false
    end
  end
  local body = string.format(
    '{"interface":"darktable","meta":{%s}}', meta)
  local tmp = _unique_tmp("spellcaster_hb", ".json")
  local f = io.open(tmp, "w")
  if not f then return end
  f:write(body); f:close()
  -- Fire-and-forget; 2s timeout keeps us from blocking the UI if the
  -- Guild is down. `--max-time 2` ensures curl doesn't hang on a stuck
  -- route. Output goes to null.
  local cmd
  if package.config:sub(1,1) == "\\" then
    -- Windows: hide the console window with conhost spawning via start /b
    cmd = string.format(
      'curl -s --max-time 2 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/interfaces/heartbeat" -o NUL 2>NUL',
      shell_esc(tmp), shell_esc(guild))
  else
    cmd = string.format(
      'curl -s --max-time 2 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/interfaces/heartbeat" -o /dev/null 2>/dev/null',
      shell_esc(tmp), shell_esc(guild))
  end
  os.execute(cmd)
  os.remove(tmp)
end

function guild_emit_event(kind, data_json)
  -- data_json: raw JSON string for the 'data' field, e.g.
  --   '{"prompt":"sunset","model":"sdxl"}'
  -- Keeping it as a raw string means callers format it however they
  -- want without this helper reinventing JSON encoding.
  local guild = get_guild_url()
  if not guild or guild == "" then return end
  data_json = data_json or "{}"
  local body = string.format(
    '{"kind":"%s","origin":"darktable","data":%s}',
    tostring(kind):gsub('"', "'"), data_json)
  local tmp = _unique_tmp("spellcaster_evt", ".json")
  local f = io.open(tmp, "w")
  if not f then return end
  f:write(body); f:close()
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 2 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/events/emit" -o NUL 2>NUL',
      shell_esc(tmp), shell_esc(guild))
  else
    cmd = string.format(
      'curl -s --max-time 2 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/events/emit" -o /dev/null 2>/dev/null',
      shell_esc(tmp), shell_esc(guild))
  end
  os.execute(cmd)
  os.remove(tmp)
end

-- R110: cross-plugin asset send — upload an image file to the Guild's
-- content-hashed /api/assets endpoint, then publish a
-- <target>.asset.send event. Both steps are fire-and-best-effort;
-- returns true on successful publish, false otherwise.
-- We use a Python helper to base64-encode the file since Lua's
-- stdlib has no b64. Python ships with the Spellcaster runtime and is
-- reliably on PATH for every install tier.
-- Try ComfyUI's blob bus first (audit tier-3). Saves a LAN hop when
-- the Guild is on a different machine from ComfyUI + the target peer.
-- Returns hash string on success, nil on any failure (no error spam;
-- caller falls back to Guild upload). curl's -F flag builds the
-- multipart body natively so we skip the Python-b64 shuffle needed
-- for the JSON endpoint.
function _blob_upload(png_path)
  local comfy = get_server()
  if not comfy or comfy == "" then return nil end
  local resp_path = tmp_dir() .. sep
                    .. "spellcaster_blob_resp_" .. os.time() .. ".json"
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 30 -X POST -F "origin=darktable" -F "kind=generation" -F "file=@%s" "%s/spellcaster/blob/put" -o "%s" 2>NUL',
      shell_esc(png_path), shell_esc(comfy), shell_esc(resp_path))
  else
    cmd = string.format(
      'curl -s --max-time 30 -X POST -F "origin=darktable" -F "kind=generation" -F "file=@%s" "%s/spellcaster/blob/put" -o "%s" 2>/dev/null',
      shell_esc(png_path), shell_esc(comfy), shell_esc(resp_path))
  end
  os.execute(cmd)
  local rf = io.open(resp_path, "r")
  if not rf then return nil end
  local body = rf:read("*all"); rf:close(); os.remove(resp_path)
  if not body or body == "" then return nil end
  local hash = body:match('"hash"%s*:%s*"([^"]+)"')
  local url = body:match('"url"%s*:%s*"([^"]+)"')
  if not hash or not url then return nil end
  return hash, url
end

function _asset_upload_and_emit(target, png_path, friendly)
  local guild = get_guild_url()
  if not guild or guild == "" then return false, "no guild url" end
  -- Blob-bus-first path — byte transport skips the Guild when possible.
  -- Guild still handles the event signal, so subscribers (GIMP, ST,
  -- Resolve Bridge) don't care which URL shape they see.
  local bhash, burl = _blob_upload(png_path)
  if bhash and burl then
    local data_json = string.format(
      '{"image_url":"%s","hash":"%s","source":"darktable","kind":"generation","transport":"blob"}',
      burl, bhash)
    guild_emit_event(target .. ".asset.send", data_json)
    return true, bhash
  end
  -- 1) base64-encode the file to a temp .txt via python helper
  local b64_out = tmp_dir() .. sep
                  .. "spellcaster_b64_" .. os.time() .. ".txt"
  local b64_cmd
  if package.config:sub(1,1) == "\\" then
    b64_cmd = string.format(
      'python -c "import base64,sys; sys.stdout.buffer.write(base64.b64encode(open(r\'%s\',\'rb\').read()))" > "%s" 2>NUL',
      shell_esc(png_path), shell_esc(b64_out))
  else
    b64_cmd = string.format(
      'python -c "import base64,sys; sys.stdout.buffer.write(base64.b64encode(open(\'%s\',\'rb\').read()))" > "%s" 2>/dev/null',
      shell_esc(png_path), shell_esc(b64_out))
  end
  os.execute(b64_cmd)
  local bf = io.open(b64_out, "r")
  if not bf then return false, "b64 helper failed" end
  local b64 = bf:read("*all"); bf:close(); os.remove(b64_out)
  if not b64 or b64 == "" then return false, "empty b64" end
  -- 2) build asset-upload JSON + post
  local asset_body = tmp_dir() .. sep
                     .. "spellcaster_asset_" .. os.time() .. ".json"
  local asset_resp = tmp_dir() .. sep
                     .. "spellcaster_asset_resp_" .. os.time() .. ".json"
  local payload = string.format(
    '{"origin":"darktable","kind":"asset","title":"From Darktable → %s","tags":["to_%s","darktable_export"],"body_b64":"%s"}',
    tostring(friendly):gsub('"', "'"),
    tostring(target):gsub('"', "'"),
    b64)
  local f = io.open(asset_body, "w")
  if not f then return false, "tmp write failed" end
  f:write(payload); f:close()
  local upload_cmd
  if package.config:sub(1,1) == "\\" then
    upload_cmd = string.format(
      'curl -s --max-time 60 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/assets" -o "%s" 2>NUL',
      shell_esc(asset_body), shell_esc(guild), shell_esc(asset_resp))
  else
    upload_cmd = string.format(
      'curl -s --max-time 60 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/assets" -o "%s" 2>/dev/null',
      shell_esc(asset_body), shell_esc(guild), shell_esc(asset_resp))
  end
  os.execute(upload_cmd)
  os.remove(asset_body)
  local rf = io.open(asset_resp, "r")
  if not rf then return false, "no response" end
  local resp = rf:read("*all"); rf:close(); os.remove(asset_resp)
  -- json_val defined further down — use inline regex since we might be
  -- earlier in the file than json_val's definition. Hash is `"hash":"..."`.
  local hash = resp and resp:match('"hash"%s*:%s*"([^"]+)"') or nil
  if not hash or hash == "" then return false, "no hash in response" end
  -- 3) publish event for the target's subscriber (Bridge / GIMP / ST)
  local data_json = string.format(
    '{"image_url":"/api/assets/%s","hash":"%s","source":"darktable","kind":"asset","transport":"guild"}',
    hash, hash)
  guild_emit_event(target .. ".asset.send", data_json)
  return true, hash
end

-- ═══════════════════════════════════════════════════════════════════════
-- GUILD SHOT API — canonical WAN I2V path (CLAUDE.md §16.4)
-- ═══════════════════════════════════════════════════════════════════════
-- Every WAN generation in Darktable routes through these helpers so the
-- hand-rolled workflow JSON is gone. The Guild's /api/video/shots endpoints
-- wrap the canonical spellcaster_core.workflows.build_wan_video + the
-- canonical video_presets.wan_turbo_kwargs. When the canon moves, this
-- plugin tracks it automatically — no more drift.
--
-- Flow:
--   1. guild_create_shot()           → draft shot in the Guild's shotboard
--   2. guild_attach_reference()      → base64-upload the ref frame
--   3. guild_render_shot()           → queues the canonical build_wan_video
--   4. guild_wait_for_shot_ready()   → polls until status="ready"
--   5. guild_download_shot_video()   → fetches the MP4 output

-- File → base64 string using the same python helper pattern as
-- _asset_upload_and_emit. Returns nil on failure.
--
-- Bounds the source read at MAX_REF_BYTES so a 4 GB Darktable export
-- can't OOM the Python interpreter we spawn. The Guild's own reference
-- upload cap is 200 MB; we match that on the client side.
local MAX_REF_BYTES = 200 * 1024 * 1024
function _file_to_base64(path)
  -- Cheap pre-check: ask the OS for the file size via Lua io.open +
  -- seek, without reading the body. If we can't size it, play safe
  -- and refuse rather than pushing unbounded data through Python.
  local probe = io.open(path, "rb")
  if not probe then return nil end
  local ok_size, size = pcall(function()
    probe:seek("end"); return probe:seek()
  end)
  probe:close()
  if not ok_size or not size or size > MAX_REF_BYTES then
    return nil
  end
  local b64_out = _unique_tmp("dt_b64", ".txt")
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'python -c "import base64,sys; sys.stdout.buffer.write(base64.b64encode(open(r\'%s\',\'rb\').read()))" > "%s" 2>NUL',
      shell_esc(path), shell_esc(b64_out))
  else
    cmd = string.format(
      'python -c "import base64,sys; sys.stdout.buffer.write(base64.b64encode(open(\'%s\',\'rb\').read()))" > "%s" 2>/dev/null',
      shell_esc(path), shell_esc(b64_out))
  end
  os.execute(cmd)
  local f = io.open(b64_out, "r")
  if not f then return nil end
  local b64 = f:read("*all"); f:close(); os.remove(b64_out)
  if not b64 or b64 == "" then return nil end
  return b64
end

-- Body for ``_gallery_stash_after_download`` (forward-declared near
-- curl_download). Pushes a locally-downloaded ComfyUI output into the
-- Guild's AssetGallery so every cross-interface subscriber sees the
-- generation via ``darktable.asset.created``. Fire-and-forget —
-- errors are swallowed so Darktable's own import never blocks on a
-- slow or offline Guild. Darktable keeps the bytes locally as its
-- source of truth; the gallery stash is additive visibility.
_gallery_stash_after_download = function(out, filename, extra_tags)
  local guild = get_guild_url()
  if not guild or guild == "" then return end
  local probe = io.open(out, "rb")
  if not probe then return end
  local head = probe:read(16); probe:close()
  if not head or #head == 0 then return end
  local b64 = _file_to_base64(out)
  if not b64 or b64 == "" then return end
  local title = tostring(filename or "darktable generation"):gsub('"', "'")
  local tags_json = '["darktable_generation"'
  for _, t in ipairs(extra_tags or {}) do
    tags_json = tags_json .. ',"' .. tostring(t):gsub('"', "'") .. '"'
  end
  tags_json = tags_json .. "]"
  local payload = string.format(
    '{"origin":"darktable","kind":"generation","title":"%s","tags":%s,"body_b64":"%s"}',
    title, tags_json, b64)
  local body_file = _unique_tmp("spellcaster_stash", ".json")
  local resp_file = _unique_tmp("spellcaster_stash_resp", ".json")
  local f = io.open(body_file, "w")
  if not f then return end
  f:write(payload); f:close()
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 30 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/assets" -o "%s" 2>NUL',
      shell_esc(body_file), shell_esc(guild), shell_esc(resp_file))
  else
    cmd = string.format(
      'curl -s --max-time 30 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/assets" -o "%s" 2>/dev/null',
      shell_esc(body_file), shell_esc(guild), shell_esc(resp_file))
  end
  os.execute(cmd)
  os.remove(body_file)
  os.remove(resp_file)
end

-- Body for ``_download_comfyui_view`` (forward-declared near
-- curl_download). Canonical ComfyUI-result download for Darktable —
-- fetches the /view endpoint into ``out`` AND stashes the bytes into
-- the Guild's AssetGallery so every other plugin sees the generation
-- via the ``darktable.asset.created`` event. Replaces the ad-hoc
-- ``curl_download(format("%s/view?..."))`` sites that previously left
-- cross-interface subscribers blind to Darktable generations.
_download_comfyui_view = function(server, filename, out)
  local url = string.format("%s/view?filename=%s&type=output",
                             server, shell_esc(filename))
  curl_download(url, out)
  pcall(_gallery_stash_after_download, out, filename, nil)
end

-- Create a draft shot on the Guild. Returns shot_id or nil.
-- `overrides` is an optional table of per-shot parameter overrides the
-- Guild will pass through to build_wan_video (width, height, length, fps,
-- ip_adapter_*, loras_high, loras_low, motion_mask, etc.). The Guild
-- applies wan_turbo_kwargs internally based on the `preset` name.
function guild_create_shot(title, prompt, negative, preset, overrides)
  local guild = get_guild_url()
  if not guild or guild == "" then
    return nil, "Guild URL not configured (preferences → Wizard Guild URL)"
  end

  -- Build JSON payload. Escape strings via json_escape where available.
  local function esc(s) return (s or ""):gsub('\\', '\\\\'):gsub('"', '\\"') end
  local overrides_json = "{}"
  if overrides and next(overrides) ~= nil then
    local parts = {}
    for k, v in pairs(overrides) do
      local kesc = esc(tostring(k))
      if type(v) == "string" then
        table.insert(parts, string.format('"%s":"%s"', kesc, esc(v)))
      elseif type(v) == "boolean" then
        table.insert(parts, string.format('"%s":%s', kesc, v and "true" or "false"))
      elseif type(v) == "number" then
        table.insert(parts, string.format('"%s":%s', kesc, tostring(v)))
      end
    end
    overrides_json = "{" .. table.concat(parts, ",") .. "}"
  end

  local body = string.format(
    '{"title":"%s","prompt":"%s","negative":"%s","preset":"%s","overrides":%s}',
    esc(title or ""), esc(prompt or ""), esc(negative or ""),
    esc(preset or "wan22_i2v_lightning"), overrides_json)

  local tmp = _unique_tmp("dt_shot_create", ".json")
  local f = io.open(tmp, "w"); if not f then return nil, "tmp write failed" end
  f:write(body); f:close()
  local resp_path = _unique_tmp("dt_shot_resp", ".json")
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 30 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/video/shots" -o "%s" 2>NUL',
      shell_esc(tmp), shell_esc(guild), shell_esc(resp_path))
  else
    cmd = string.format(
      'curl -s --max-time 30 -X POST -H "Content-Type: application/json" --data-binary "@%s" "%s/api/video/shots" -o "%s" 2>/dev/null',
      shell_esc(tmp), shell_esc(guild), shell_esc(resp_path))
  end
  os.execute(cmd)
  os.remove(tmp)
  local rf = io.open(resp_path, "r")
  if not rf then return nil, "no response" end
  local resp = rf:read("*all"); rf:close(); os.remove(resp_path)
  local shot_id = resp and (resp:match('"id"%s*:%s*"([^"]+)"')
                            or resp:match('"shot_id"%s*:%s*"([^"]+)"'))
  if not shot_id then
    return nil, string.format("shot create failed: %s",
                              (resp or ""):sub(1, 200))
  end
  return shot_id
end

-- Attach a reference image to an existing shot (base64 upload).
--
-- Previously returned `true` blindly after `os.execute(curl)` — that
-- masked a Guild-side dispatcher bug where POST /reference was
-- shadowed by a GET handler and silently 404'd every upload. Now we
-- ask curl to capture the HTTP status into a separate file via
-- `-w "%{http_code}"` and only report success on 2xx. The Guild's
-- response body goes into its own tmp file so we can surface the
-- error text to the caller on failure.
function guild_attach_reference(shot_id, image_path)
  local guild = get_guild_url()
  if not guild or guild == "" then return false, "no guild url" end
  local b64 = _file_to_base64(image_path)
  if not b64 then return false, "base64 encode failed (file too large or unreadable)" end
  local body = string.format('{"image_data":"data:image/png;base64,%s"}', b64)
  local tmp       = _unique_tmp("dt_shot_ref",      ".json")
  local resp_body = _unique_tmp("dt_shot_ref_resp", ".txt")
  local status_f  = _unique_tmp("dt_shot_ref_code", ".txt")
  local f = io.open(tmp, "w"); if not f then return false, "tmp write failed" end
  f:write(body); f:close()
  local url = string.format("%s/api/video/shots/%s/reference", guild, shot_id)
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 60 -X POST -H "Content-Type: application/json" --data-binary "@%s" -o "%s" -w "%%{http_code}" "%s" > "%s" 2>NUL',
      shell_esc(tmp), shell_esc(resp_body), shell_esc(url), shell_esc(status_f))
  else
    cmd = string.format(
      'curl -s --max-time 60 -X POST -H "Content-Type: application/json" --data-binary "@%s" -o "%s" -w "%%{http_code}" "%s" > "%s" 2>/dev/null',
      shell_esc(tmp), shell_esc(resp_body), shell_esc(url), shell_esc(status_f))
  end
  os.execute(cmd)
  os.remove(tmp)
  -- Read back the curl-written HTTP status code (`-w "%{http_code}"`).
  local sf = io.open(status_f, "r")
  local code_str = sf and sf:read("*all") or ""
  if sf then sf:close() end
  os.remove(status_f)
  local code = tonumber((code_str or ""):match("%d+")) or 0
  if code < 200 or code >= 300 then
    -- Surface the first 200 chars of the error body for diagnosis.
    local body_snippet = ""
    local bf = io.open(resp_body, "r")
    if bf then
      body_snippet = (bf:read("*all") or ""):sub(1, 200)
      bf:close()
    end
    os.remove(resp_body)
    return false, string.format("guild attach_reference HTTP %d: %s",
                                code, body_snippet)
  end
  os.remove(resp_body)
  return true
end

-- Trigger render for a shot. Returns true on queued, false on error.
function guild_render_shot(shot_id)
  local guild = get_guild_url()
  if not guild or guild == "" then return false, "no guild url" end
  local url = string.format("%s/api/video/shots/%s/render", guild, shot_id)
  local resp_path = _unique_tmp("dt_shot_render", ".json")
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 15 -X POST -H "Content-Type: application/json" -d "{}" "%s" -o "%s" 2>NUL',
      shell_esc(url), shell_esc(resp_path))
  else
    cmd = string.format(
      'curl -s --max-time 15 -X POST -H "Content-Type: application/json" -d "{}" "%s" -o "%s" 2>/dev/null',
      shell_esc(url), shell_esc(resp_path))
  end
  os.execute(cmd)
  local rf = io.open(resp_path, "r")
  if not rf then return false, "no response" end
  local resp = rf:read("*all"); rf:close(); os.remove(resp_path)
  local status = resp and resp:match('"status"%s*:%s*"([^"]+)"') or ""
  -- queued / running / ready → success; error / paused → failure
  if status == "error" or status == "paused" then
    return false, status .. ": " .. (resp or ""):sub(1, 200)
  end
  return true, status
end

-- Poll the Guild's shot list until the target shot reaches status="ready"
-- (or "failed"). Returns (ready, status_or_error).
function guild_wait_for_shot_ready(shot_id, timeout_s)
  local guild = get_guild_url()
  if not guild or guild == "" then return false, "no guild url" end
  timeout_s = timeout_s or 600
  local deadline = os.time() + timeout_s
  local last_status = "unknown"
  while os.time() < deadline do
    local list_url = guild .. "/api/video/shots"
    local resp = curl_get(list_url)
    if resp then
      -- Find our shot by id within the list. The list is a JSON array of
      -- shot dicts; each has "id" and "status". We do not parse the full
      -- JSON (that would require a library) — we carve out the slice
      -- between our id and the next id boundary.
      local slice_start = resp:find('"id"%s*:%s*"' .. shot_id .. '"', 1, false)
      if slice_start then
        -- Look for the next "id": field OR end of array — whichever is
        -- earlier bounds the slice containing our shot's keys.
        local next_id = resp:find('"id"%s*:%s*"', slice_start + 1, false)
        local slice_end = next_id or #resp
        local slice = resp:sub(slice_start, slice_end)
        local status = slice:match('"status"%s*:%s*"([^"]+)"') or "unknown"
        last_status = status
        if status == "ready" then return true, "ready" end
        if status == "failed" then
          local err = slice:match('"error"%s*:%s*"([^"]+)"') or ""
          return false, "failed: " .. err
        end
      end
    end
    -- ~3s between polls is fine — WAN renders take minutes.
    os.execute(
      package.config:sub(1,1) == "\\" and "timeout /t 3 /nobreak > NUL"
                                       or "sleep 3")
  end
  return false, "timeout (last status: " .. last_status .. ")"
end

-- Download the rendered video for a shot. Returns true on success.
function guild_download_shot_video(shot_id, out_path)
  local guild = get_guild_url()
  if not guild or guild == "" then return false, "no guild url" end
  local url = string.format("%s/api/video/shots/%s/video", guild, shot_id)
  curl_download(url, out_path)
  local f = io.open(out_path, "rb")
  if not f then return false, "no output file" end
  local head = f:read(4); f:close()
  -- Sanity check — ensure we didn't just download the 404 JSON body.
  -- MP4 files start with an 'ftyp' box around offset 4; we just check
  -- size > 1KB to rule out the error body.
  local size = 0
  local s = io.open(out_path, "rb")
  if s then
    s:seek("end")
    size = s:seek()
    s:close()
  end
  if size < 1024 then
    return false, "download too small (likely error response)"
  end
  return true
end

-- SIMPLE JSON VALUE EXTRACTION
-- ═════════════════════════════════════════════════════════════════════════
-- Minimal parser to avoid adding a JSON library dependency.
-- Uses regex pattern matching for simple "key": "value" pairs (string values only).
-- Not suitable for nested objects, arrays, or numeric values.

-- Extract a single string value from JSON response by key name.
-- @param s : JSON response string (or nil)
-- @param key : the key to extract (e.g. "prompt_id", "name", "filename")
-- @return string or nil : the value (without quotes) or nil if key not found
-- Example: json_val('{"prompt_id":"abc123","number":5}', "prompt_id") → "abc123"
-- Pattern: matches "key" : "value" with optional whitespace, captures the value part
function json_val(s, key)
  return s and s:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

-- ───────────────────────────────────────────────────────────────────────
-- LoRA CACHING
-- ───────────────────────────────────────────────────────────────────────
-- LoRA lists are fetched once from ComfyUI's /object_info endpoint and
-- cached in memory. The UI filters this cached list by architecture
-- whenever the user switches model presets, avoiding repeated HTTP calls.
local cached_all_loras = {}   -- full server list (unfiltered, fetched by fetch_all_loras)
local cached_loras = {}       -- currently displayed (filtered by architecture via filter_loras_for_arch)

-- Fetch all available LoRAs from ComfyUI and cache them in memory.
-- ComfyUI exposes LoRA metadata via /object_info/LoraLoader endpoint.
-- The response is JSON with "lora_name": ["name1", "name2", ...] structure.
-- @return table : array of LoRA filenames (e.g. {"Hyper-SD15-8steps-CFG-lora.safetensors", ...})
-- Side effects: populates cached_all_loras (used by refresh_lora_selector when filtering by arch)
-- HTTP: GET /object_info/LoraLoader → parse "lora_name" field → extract quoted names
-- Called by: fetch_lora_btn.clicked_callback (in UI section)
function fetch_all_loras()
  local server = get_server()
  local r = curl_get(server .. "/object_info/LoraLoader")
  if not r then return {} end
  local names = {}
  -- Parse the lora_name array from the JSON
  -- ComfyUI returns: {"lora_name": ["file1.safetensors", "file2.safetensors", ...], "inputs": {...}}
  -- We extract the JSON array portion (quoted names separated by commas)
  local list_str = r:match('"lora_name"%s*:%s*%[(%[.-%])%s*,')
  if list_str then
    -- Extract each quoted string from the JSON array
    for name in list_str:gmatch('"([^"]*)"') do
      table.insert(names, name)
    end
  end
  cached_all_loras = names
  return names
end

-- Get the architecture string of the currently selected model preset.
-- Used by UI to filter compatible LoRAs, scenes, and ControlNets.
-- @return string : architecture ID ("sd15", "sdxl", "flux1dev", "flux2klein", etc.)
-- Fallback: "sdxl" if no model preset is selected (should not happen in normal use)
-- Called by: refresh_lora_selector, refresh_scene_selector, get_turbo_config
function get_current_arch()
  local idx = model_selector and model_selector.selected or 1
  local preset = MODEL_PRESETS[idx]
  return preset and preset.arch or "sdxl"
end

-- ═══════════════════════════════════════════════════════════════════════
-- WORKFLOW JSON BUILDERS
-- ═══════════════════════════════════════════════════════════════════════
-- ComfyUI workflows are JSON objects describing DAGs of processing nodes.
-- Each node has:
--   - A unique string ID (e.g., "1", "42", "99")
--   - A class_type (ComfyUI node name, e.g., "LoadImage", "KSampler", "SaveImage")
--   - An inputs dict with parameter values and inter-node connections
--
-- Node-to-node connections use ["node_id", output_index] arrays to reference
-- outputs from earlier nodes (e.g., ["1", 0] means "output 0 of node 1").
--
-- WHY STRING-BASED BUILDERS (NOT LUA TABLES)?
-- ============================================
-- (a) Lua's embedded Lua in Darktable has no JSON library
-- (b) String templates make the node DAG structure visually obvious (easier debug)
-- (c) The JSON structure is static per workflow type; only specific values change
-- (d) We can use string.format() to inject values without Lua table serialization
--
-- COMMON PATTERN ACROSS WORKFLOWS
-- ================================
--   1. LoadImage (node 4) → read original image dimensions
--   2. ImageScale (node 90) → downscale to max_res to save GPU memory
--   3. Process (nodes 1-3, KSampler/etc.) → AI processing at reduced res
--   4. ImageScale (node 91) → upscale back to original dimensions
--   5. SaveImage (node 8) → write output PNG file
--
-- The downscale is computed to preserve aspect ratio and round to multiples of 8
-- (because SD/SDXL VAE latent space has 8x8 pixel granularity).
-- Without this, a 1024x768 image would become 1016x760, changing aspect ratio.

-- JSON VALUE ESCAPING
-- ═══════════════════════════════════════════════════════════════════════
-- JSON requires escaping special characters inside double-quoted strings.
-- Order matters: escape backslashes first, then everything else.

-- Escape a string for safe embedding inside a JSON double-quoted value.
-- Converts Lua string → JSON string (handles backslashes, quotes, newlines, tabs).
-- @param s : Lua string (may contain unescaped JSON special chars)
-- @return string : escaped version safe for JSON embedding
-- Examples:
--   "hello\nworld" → "hello\\nworld" (preserves literal newline as \n in JSON)
--   'path\\to\\file' → 'path\\\\to\\\\file' (Windows paths get doubled backslashes)
--   'say "hi"' → 'say \\"hi\\"' (quotes escaped for JSON)
-- IMPORTANT: backslash must be escaped first, or we'd double-escape everything
function json_escape(s)
  s = s:gsub("\\", "\\\\")   -- backslash must be first (catches existing escapes too)
  s = s:gsub('"', '\\"')      -- double-quote → \"
  s = s:gsub("\n", "\\n")     -- literal newline → \n escape sequence
  s = s:gsub("\r", "\\r")     -- literal carriage return → \r escape sequence
  s = s:gsub("\t", "\\t")     -- literal tab → \t escape sequence
  return s
end

-- IMAGE DIMENSION UTILITIES
-- ═══════════════════════════════════════════════════════════════════════
-- Compute proportional downscale dimensions fitting within max_res.
-- Rounds to multiples of 8 because SD/SDXL operate in latent space
-- where each "pixel" in latent space represents an 8x8 block in image space.
-- This ensures the latent representation respects the original aspect ratio.
--
-- @param orig_w, orig_h : original image dimensions (pixels)
-- @param max_res : maximum dimension (e.g., 768, 1024); 0 = no scaling
-- @return new_w, new_h : downscaled dimensions (multiples of 8)
-- Examples:
--   compute_scale_dims(1024, 768, 512) → (512, 384) [max dimension fits in 512]
--   compute_scale_dims(1920, 1080, 1024) → (1024, 576)
--   compute_scale_dims(640, 480, 0) → (640, 480) [no scaling]
function compute_scale_dims(orig_w, orig_h, max_res)
  if max_res <= 0 or (orig_w <= max_res and orig_h <= max_res) then
    return orig_w, orig_h
  end
  -- Scale the larger dimension down to max_res, keeping aspect ratio
  local scale = max_res / math.max(orig_w, orig_h)
  -- Round to multiples of 8 (SD/SDXL latent space granularity)
  local new_w = math.floor(orig_w * scale / 8) * 8
  local new_h = math.floor(orig_h * scale / 8) * 8
  -- Clamp to minimum 8x8 (would be nonsensical but prevents zero dimensions)
  if new_w < 8 then new_w = 8 end
  if new_h < 8 then new_h = 8 end
  return new_w, new_h
end

-- Read image dimensions from a Darktable image object.
-- Darktable images are loaded in the lighttable view; each has width/height properties.
-- @param image : Darktable image object (or nil)
-- @return w, h : width and height in pixels
-- Fallback: 4096x4096 if image is nil or dimensions are invalid (<=0)
-- Used by: build_*_json functions to determine if scaling is needed
function get_image_dims(image)
  local w = (image and image.width) or 4096
  local h = (image and image.height) or 4096
  if w <= 0 then w = 4096 end
  if h <= 0 then h = 4096 end
  return w, h
end

-- BUILD IMG2IMG WORKFLOW JSON
-- ═══════════════════════════════════════════════════════════════════════
-- Construct the JSON DAG for an image-to-image diffusion workflow.
-- This is the most common and versatile workflow: transform an existing image
-- using a prompt and a model checkpoint.
--
-- WORKFLOW DAG (node IDs):
--   Node 1: CheckpointLoaderSimple (loads .safetensors model)
--   Nodes 2-3: CLIPTextEncode (positive & negative prompts)
--   Node 4: LoadImage (read the input image file)
--   Node 90: GetImageSize (get original dimensions)
--   Node 91: ImageScale (downscale to max_res to save GPU memory)
--   Node 5: VAEEncode (compress image to latent space)
--   Node 6: KSampler (the main diffusion loop)
--   Node 7: VAEDecode (decompress latent back to image)
--   Node 92: ImageScale (upscale back to original dimensions)
--   Node 8: SaveImage (save result PNG)
--   Nodes 99-100: LoRA chain (optional model fine-tuning)
--   Nodes 20-22: ControlNet chain (optional guidance via reference image)
--
-- PARAMETERS:
--   @param image_filename : name of uploaded image on ComfyUI (e.g. "dt_export_xyz.png")
--   @param preset : MODEL_PRESETS entry with ckpt path, steps, cfg, sampler, scheduler
--   @param prompt, negative : user text prompts (will be json_escape'd)
--   @param seed : RNG seed (negative = random each run)
--   @param lora_name, lora_strength : optional LoRA fine-tuning (or "" for none)
--   @param scale_w, scale_h : downscaled dimensions (computed by compute_scale_dims)
--   @param cn_mode, cn_strength : ControlNet mode ("off"/"reference"/etc.) and blend strength
--   @param cn_preprocessor, cn_model : optional ControlNet processor and model names
--   @param turbo_config : optional turbo LoRA for 8-step acceleration (or nil)
--
-- RETURN: JSON string (entire workflow object, ready to POST to /prompt endpoint)
--
-- NODE CHAINING STRATEGY:
--   - Outputs referenced via ["node_id", output_index] arrays
--   - Turbo LoRA (node 99) chains before user LoRA (node 100)
--   - LoRA outputs update model/clip references for KSampler
--   - ControlNet (nodes 20-22) optionally preprocesses image and applies guidance
--   - Image scaling happens before/after VAE to preserve aspect ratio
--
-- TURBO MODE:
--   Hyper-SD15 / Hyper-SDXL LoRAs enable 8-step generation instead of 20-30 steps.
--   This prepends an automatic LoRA before user-selected ones.
--
-- CONTROLNET (optional):
--   Adds nodes for:
--     - Optional preprocessor (e.g., LineArt, DepthAnything) → node 20
--     - ControlNetLoader → node 21
--     - ControlNetApplyAdvanced (applies guidance) → node 22
--   If enabled, nodes 2-3 outputs are replaced with nodes 22's outputs in KSampler.
--
function build_img2img_json(image_filename, preset, prompt, negative, seed,
                                   lora_name, lora_strength, scale_w, scale_h,
                                   cn_mode, cn_strength, cn_preprocessor, cn_model,
                                   turbo_config)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)
  local esc_ckpt = json_escape(preset.ckpt)

  -- Build LoRA chain: turbo LoRA first (node 99), then user LoRA (node 100)
  local lora_nodes = ""
  local model_ref = '["1",0]'
  local clip_ref = '["1",1]'

  -- Turbo acceleration LoRA (prepended before user LoRA)
  if turbo_config then
    local esc_turbo = json_escape(turbo_config.lora)
    lora_nodes = string.format(
      ',"99":{"class_type":"LoraLoader","inputs":{"model":%s,"clip":%s,"lora_name":"%s","strength_model":%.3f,"strength_clip":%.3f}}',
      model_ref, clip_ref, esc_turbo, turbo_config.strength_model, turbo_config.strength_clip)
    model_ref = '["99",0]'
    clip_ref = '["99",1]'
  end

  -- User-selected LoRA
  if lora_name and lora_name ~= "" and lora_name ~= "(none)" then
    local esc_lora = json_escape(lora_name)
    lora_nodes = lora_nodes .. string.format(
      ',"100":{"class_type":"LoraLoader","inputs":{"model":%s,"clip":%s,"lora_name":"%s","strength_model":%.2f,"strength_clip":%.2f}}',
      model_ref, clip_ref, esc_lora, lora_strength or 1.0, lora_strength or 1.0)
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

  -- Apply turbo overrides if active
  local steps = preset.steps
  local cfg = preset.cfg
  local sampler = preset.sampler
  local scheduler = preset.scheduler
  if turbo_config then
    steps = turbo_config.steps
    cfg = turbo_config.cfg
    sampler = turbo_config.sampler
    scheduler = turbo_config.scheduler
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
    esc_ckpt, lora_nodes, cn_nodes,
    esc_prompt, clip_ref,
    esc_neg, clip_ref,
    image_filename,
    scale_w, scale_h,
    model_ref, pos_ref, neg_ref,
    seed, steps, cfg,
    sampler, scheduler, preset.denoise)
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

function fetch_face_models()
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

-- Fetch swap models (detection/replacement backends) from ComfyUI.
-- @return table : array of swap model names (e.g. ["inswapper_128.onnx", ...])
function fetch_swap_models()
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

-- BUILD FACESWAP WORKFLOW (saved face model)
-- ═══════════════════════════════════════════════════════════════════════
-- ReActor approach: uses a pre-saved face embedding file (learned from prior photo).
-- Swaps all detected faces in target image with the reference face identity.
--
-- WORKFLOW NODES:
--   Node 1: LoadImage (target image)
--   Node 90: GetImageSize (original dimensions)
--   Node 91: ImageScale (downscale)
--   Node 2: ReActorLoadFaceModel (loads saved face embedding from disk)
--   Node 3: ReActorFaceSwapOpt (main swap + CodeFormer restoration)
--   Node 4: ReActorOptions (face detection / ordering config)
--   Node 5: ReActorFaceBoost (post-swap face enhancement)
--   Node 95: ImageScale (upscale back to original size)
--   Node 10: SaveImage (output)
--
-- @param image_filename : target image name on ComfyUI
-- @param face_model_name : saved face embedding file (e.g. "john_doe.pt")
-- @param swap_model : detection backend (e.g. "inswapper_128.onnx")
-- @param scale_w, scale_h : downscaled dimensions
-- @return string : complete workflow JSON
--
function build_faceswap_model_json(image_filename, face_model_name, swap_model, scale_w, scale_h)
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

function build_faceswap_direct_json(target_filename, source_filename,
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

-- BUILD SAVE FACE MODEL WORKFLOW (ReActor)
-- ═══════════════════════════════════════════════════════════════════════
-- Extract and save a face embedding from a source image (learn a face).
-- This workflow encodes the face identity into a .pt/.safetensors file
-- on the ComfyUI server, which can then be used with build_faceswap_model_json.
--
-- WORKFLOW:
--   Node 1: LoadImage (source image with the face to encode)
--   Node 2: ReActorBuildFaceModel (extract face embedding via neural net)
--   Node 3: ReActorSaveFaceModel (persist to disk)
--
-- @param image_filename : source image name on ComfyUI
-- @param model_name : filename for saved model (user-provided, e.g. "john_doe.pt")
-- @param overwrite : boolean (true = overwrite existing, false = skip if exists)
-- @return string : complete workflow JSON
--
function build_save_face_model_json(image_filename, model_name, overwrite)
  local esc_name = json_escape(model_name)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"ReActorBuildFaceModel","inputs":{"compute_method":"CPU","face_model":["1",0]}},
  "3":{"class_type":"ReActorSaveFaceModel","inputs":{"face_model":["2",0],"save_mode":"%s","face_model_name":"%s"}}
}}]], image_filename, overwrite and "overwrite" or "skip-if-exists", esc_name)
end

-- BUILD REMOVE BACKGROUND WORKFLOW (rembg isnet-general-use)
-- ═══════════════════════════════════════════════════════════════════════
-- Remove background via semantic segmentation. Produces PNG with transparency.
--
-- WORKFLOW:
--   Node 1: LoadImage (input image)
--   Node 2: Image Rembg (background removal)
--   Node 3: SaveImage (output with alpha channel)
--
-- Settings are hardcoded from validated Spellcaster pipeline (DO NOT CHANGE):
--   - transparency: true (output has alpha channel)
--   - model: "isnet-general-use" (general-purpose, not anime/portrait-specific)
--   - post_processing: false (no edge smoothing; can cause artifacts)
--   - alpha_matting: false (IMPORTANT: true causes color fringing on edges)
--   - alpha_matting_threshold settings: unused but present for completeness
--
-- @param image_filename : input image name on ComfyUI
-- @return string : complete workflow JSON
--
function build_rembg_json(image_filename)
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

-- BUILD UPSCALE WORKFLOW (4x super-resolution)
-- ═══════════════════════════════════════════════════════════════════════
-- Model-based 4x upscaling via RealESRGAN or other upscale models.
-- NO checkpoints, NO samplers — purely deterministic upsampling.
--
-- WORKFLOW:
--   Node 1: LoadImage (input image)
--   Node 2: UpscaleModelLoader (load .pth upscale model from disk)
--   Node 3: ImageUpscaleWithModel (apply upscale)
--   Node 4: SaveImage (output)
--
-- Available models: RealESRGAN (photo), UltraSharp (detail), Anime (anime)
--
-- @param image_filename : input image name on ComfyUI
-- @param model_name : upscale model filename (e.g. "RealESRGAN_x4plus.pth")
-- @return string : complete workflow JSON
--
local UPSCALE_MODELS = {
  { label = "4x UltraSharp",        file = "4x-UltraSharp.pth" },
  { label = "4x RealESRGAN",        file = "RealESRGAN_x4plus.pth" },
  { label = "4x NMKD Superscale",   file = "4x_NMKD-Superscale-SP_178000_G.pth" },
  { label = "4x Remacri",           file = "4x_foolhardy_Remacri.pth" },
  { label = "4x Anime",             file = "RealESRGAN_x4plus_anime_6B.pth" },
}

function build_upscale_json(image_filename, model_name)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"UpscaleModelLoader","inputs":{"model_name":"%s"}},
  "3":{"class_type":"ImageUpscaleWithModel","inputs":{"upscale_model":["2",0],"image":["1",0]}},
  "4":{"class_type":"SaveImage","inputs":{"images":["3",0],"filename_prefix":"darktable_upscale"}}
}}]], shell_esc(image_filename), shell_esc(model_name))
end

-- BUILD OBJECT REMOVAL WORKFLOW (LaMa Inpaint)
-- ═══════════════════════════════════════════════════════════════════════
-- AI-powered object removal using LaMa (Large Mask Inpainting).
-- Restores masked areas using context from surrounding pixels.
--
-- WORKFLOW:
--   Node 1: LoadImage (target image with unwanted objects)
--   Node 2: LoadImage (mask image: white = remove, black = keep)
--   Node 3: LamaRemover (inpainting model removes masked regions)
--   Node 4: SaveImage (output)
--
-- The mask image should have transparency or separate alpha channel.
-- LoadImage output[1] extracts the alpha channel for the mask.
--
-- @param image_filename : input image name on ComfyUI
-- @param mask_filename : mask image name on ComfyUI (alpha channel = removal area)
-- @return string : complete workflow JSON
--
-- NOTE on class name: ComfyUI-LaMA-Preprocessor registers the remover
-- as ``LamaRemover`` (single-word, lowercase 'a'). The earlier
-- ``LaMaInpaint`` reference here was a copy-paste miss — no ComfyUI
-- install ever registered that class, so this button silently failed
-- every time it was clicked. The canonical spellcaster_core node
-- factory uses ``LamaRemover`` too; keep the two in sync.
--
-- LamaRemover takes separate IMAGE + MASK inputs (not a LoadImage
-- alpha channel). An ImageToMask step extracts the mask bitmap from
-- the mask PNG's red channel — matches the canonical
-- build_lama_remove workflow.
function build_lama_json(image_filename, mask_filename)
  return string.format([[
{"prompt":{
  "1":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "2":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "5":{"class_type":"ImageToMask","inputs":{"image":["2",0],"channel":"red"}},
  "3":{"class_type":"LamaRemover","inputs":{"images":["1",0],"masks":["5",0],"mask_threshold":250,"gaussblur_radius":8,"invert_mask":false}},
  "4":{"class_type":"SaveImage","inputs":{"images":["3",0],"filename_prefix":"darktable_lama"}}
}}]], shell_esc(image_filename), shell_esc(mask_filename))
end

-- BUILD COLOR GRADING WORKFLOW (LUT-based)
-- ═══════════════════════════════════════════════════════════════════════
-- Apply cinematic color grading via .cube lookup tables.
-- LUTs are industry-standard for color grading (Kodak, Fujifilm, DCI-P3, ACES).
--
-- WORKFLOW:
--   Node 1: LoadImage (input image)
--   Node 2: ImageApplyLUT (apply .cube LUT for color transformation)
--   Node 3: SaveImage (output with graded colors)
--
-- Strength (0.0-1.0) blends between original and graded:
--   strength=0.0 → original image (no effect)
--   strength=1.0 → fully graded image
--   strength=0.5 → 50% blend
--
-- Presets include: Kodak 2383 (warm cinema), Fujifilm 3513DI (cool cinema), ACES (HDR)
--
-- @param image_filename : input image name on ComfyUI
-- @param lut_file : .cube LUT filename (e.g. "Kodak_2383_Cinema.cube")
-- @param strength : blend strength (0.0 to 1.0)
-- @return string : complete workflow JSON
--
local LUT_PRESETS = {
  { label = "Kodak 2383 Cinema",      file = "Rec709_Kodak_2383_D65.cube" },
  { label = "Fujifilm 3513DI Cinema",  file = "Rec709_Fujifilm_3513DI_D65.cube" },
  { label = "Kodak P3 Wide",          file = "DCI-P3_Kodak_2383_D65.cube" },
  { label = "ACES HDR",               file = "ACES_LMT_v0.1.1.cube" },
}

function build_lut_json(image_filename, lut_file, strength)
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

function build_outpaint_json(image_filename, preset, prompt, negative, seed,
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

function build_style_transfer_json(image_filename, style_ref_filename,
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

function build_face_restore_json(image_filename, model, visibility, codeformer_weight)
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

function build_photo_restore_json(image_filename, upscale_model, face_model, sharpen_alpha)
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

function build_detail_hallucinate_json(image_filename, ckpt, prompt, negative, seed, cfg, denoise)
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

function build_colorize_json(image_filename, ckpt, controlnet_name, prompt, negative, seed, strength, denoise)
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

function build_faceswap_mtb_json(target_filename, source_filename,
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

function process_faceswap_mtb(image, source_path, analysis_model, swap_model, faces_index)
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
    _download_comfyui_view(server, rfn, out)
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

function wan_video_dims(src_w, src_h, target_long, align)
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

-- ══════════════════════════════════════════════════════════════════
--  LEGACY UI-LABEL TABLE — no longer drives generation
--  ──────────────────────────────────────────────────────────────────
--  As of the CLAUDE.md §16.4 refactor, WAN I2V is produced by the
--  Guild's /api/video/shots pipeline (see `process_wan_i2v` below,
--  which calls `guild_create_shot` → canonical
--  `spellcaster_core.workflows.build_wan_video` +
--  `video_presets.wan_turbo_kwargs` server-side).
--
--  This table now exists ONLY so the Darktable dropdown keeps the
--  familiar labels ("Wan I2V 14B (GGUF Q4)", "fp8", etc.). The
--  `high_model` / `low_model` / `vae` fields below are NOT consulted
--  by `process_wan_i2v` anymore — the Guild re-detects the right
--  files via `detect_wan_preset(comfy_url)` for the user's server.
--
--  We keep the fields populated for two reasons:
--    1. The emergency escape hatch `build_wan_i2v_json` below still
--       reads them — leave it callable if the Guild is unreachable.
--    2. The label-to-preset heuristic in `process_wan_i2v` peeks at
--       the label text (e.g. "hq", "lightning") to pick the Guild
--       preset name. The model filenames are incidental now.
--
--  If you ADD a new UI label: just add an entry with a distinctive
--  `label` string. You do NOT need to keep the other fields in sync
--  with reality — the Guild owns the canon.
-- ══════════════════════════════════════════════════════════════════
local WAN_I2V_MODELS = {
  {
    label = "Wan I2V 14B (GGUF Q4)",
    high_model = "Wan\\wan2.2_i2v_high_noise_14B_Q4_K_S.gguf",
    low_model  = "Wan\\wan2.2_i2v_low_noise_14B_Q4_K_S.gguf",
    clip       = "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    vae        = "wan_2.1_vae.safetensors",
    steps = 4, second_step = 2, cfg = 1.0, shift = 5.0,
    lora_prefixes   = {"WAN\\", "Wan-2.2-I2V\\"},
    high_accel_lora = "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    low_accel_lora  = "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    accel_strength  = 1.0,
  },
  {
    label = "Wan I2V 14B (fp8)",
    high_model = "Wan\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    low_model  = "Wan\\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    clip       = "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    vae        = "wan_2.1_vae.safetensors",
    steps = 4, second_step = 2, cfg = 1.0, shift = 5.0,
    lora_prefixes   = {"WAN\\", "Wan-2.2-I2V\\"},
    high_accel_lora = "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    low_accel_lora  = "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    accel_strength  = 1.0,
  },
  {
    label = "Wan I2V 14B HQ (no LoRA)",
    high_model = "Wan\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    low_model  = "Wan\\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    clip       = "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    vae        = "wan_2.1_vae.safetensors",
    steps = 20, second_step = 10, cfg = 5.0, shift = 8.0,
    lora_prefixes   = {"WAN\\", "Wan-2.2-I2V\\"},
  },
  -- NSFW_WAN_MODEL_INJECTION_POINT --
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

  -- NSFW_WAN_INJECTION_POINT --

}

local cached_wan_loras = {}     -- all Wan\ loras from server
local cached_wan_loras_filtered = {}  -- subset shown in combos (per-preset filtered)

function fetch_wan_loras()
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

function filter_wan_loras(all_loras, wan_preset)
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

function detect_wan_lora_noise(lora_name)
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

function wan_lora_concept_key(lora_name)
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
-- ══════════════════════════════════════════════════════════════════
--  LEGACY: NO LONGER THE CANONICAL WAN I2V PATH
--  ──────────────────────────────────────────────────────────────────
--  `process_wan_i2v` now routes through `guild_create_shot` →
--  Guild `/api/video/shots` → canonical
--  `spellcaster_core.workflows.build_wan_video` +
--  `video_presets.wan_turbo_kwargs`.
--
--  This hand-rolled JSON is kept as an emergency escape hatch for
--  when the Guild is unreachable. It's intentionally NOT called by
--  any live code path — see CLAUDE.md §16.4 rule #4. If you add a
--  direct caller, you're reintroducing the drift this file fought
--  for months. Go through the Guild.
-- ══════════════════════════════════════════════════════════════════
function build_wan_i2v_json(image_filename, wan_preset, prompt, negative, seed,
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
  "50":{"class_type":"KSamplerAdvanced","inputs":{"model":["30",0],"positive":["40",0],"negative":["40",1],"latent_image":["40",2],"add_noise":"enable","noise_seed":%d,"steps":%d,"cfg":%.1f,"sampler_name":"euler","scheduler":"simple","start_at_step":0,"end_at_step":%d,"return_with_leftover_noise":"enable"}},
  "51":{"class_type":"KSamplerAdvanced","inputs":{"model":["31",0],"positive":["40",0],"negative":["40",1],"latent_image":["50",0],"add_noise":"disable","noise_seed":%d,"steps":%d,"cfg":1.0,"sampler_name":"euler","scheduler":"simple","start_at_step":%d,"end_at_step":10000,"return_with_leftover_noise":"disable"}},
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

function build_klein_img2img_json(image_filename, klein_model, prompt, seed,
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
-- PuLID Flux2 workflow (ComfyUI-PuLID-Flux2 node family)
-- ═══════════════════════════════════════════════════════════════════════
-- PuLID (Pure and Lightning ID customization) transfers face identity
-- from a reference image onto a generated image. Unlike face swap, it
-- works at the model attention level (similar to IP-Adapter) rather
-- than post-processing face replacement. Uses PuLID-Flux2 nodes
-- (PuLIDModelLoader, PuLIDEVACLIPLoader, PuLIDInsightFaceLoader,
-- ApplyPuLIDFlux2) designed for Flux.2 architecture (Klein 4B/9B).

function build_pulid_flux_json(image_filename, face_filename, prompt, seed,
                                      strength, steps, guidance, scale_w, scale_h)
  local esc_prompt = json_escape(prompt)

  return string.format([[
{"prompt":{
  "1":{"class_type":"UNETLoader","inputs":{"unet_name":"A-Flux\\Flux2\\flux-2-klein-9b.safetensors","weight_dtype":"default"}},
  "2":{"class_type":"PuLIDModelLoader","inputs":{"pulid_file":"pulid_flux_v0.9.1.safetensors"}},
  "3":{"class_type":"PuLIDEVACLIPLoader","inputs":{}},
  "4":{"class_type":"PuLIDInsightFaceLoader","inputs":{"provider":"CUDA"}},
  "5":{"class_type":"CLIPLoader","inputs":{"clip_name":"qwen_3_8b_fp8mixed.safetensors","type":"flux2","device":"default"}},
  "6":{"class_type":"VAELoader","inputs":{"vae_name":"flux2-vae.safetensors"}},
  "7":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":["5",0]}},
  "8":{"class_type":"ConditioningZeroOut","inputs":{"conditioning":["7",0]}},
  "9":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "15":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "16":{"class_type":"ApplyPuLIDFlux2","inputs":{"model":["1",0],"pulid_model":["2",0],"strength":%.2f,"eva_clip":["3",0],"face_analysis":["4",0],"image":["15",0]}},
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

function build_faceid_json(target_filename, face_ref_filename, preset,
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

function build_klein_ref_json(image_filename, ref_filename, klein_model,
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

  -- NSFW_INPAINT_INJECTION_POINT --

}

-- ═══════════════════════════════════════════════════════════════════════
-- Inpaint workflow (CheckpointLoaderSimple + SetLatentNoiseMask)
-- ═══════════════════════════════════════════════════════════════════════
-- Inpainting uses a standard checkpoint (not a dedicated inpaint model)
-- with SetLatentNoiseMask to constrain generation to masked regions.
-- The mask is loaded as a separate image, converted to a single-channel
-- mask via ImageToMask (red channel), and applied to the VAE-encoded latent.
-- White mask regions are regenerated; black regions are preserved.

function build_inpaint_json(image_filename, mask_filename, preset, prompt, negative,
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

function build_batch_txt2img_json(preset, prompt, negative, seed, lora_name, lora_strength, width, height, batch_count)
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

-- ControlNet model auto-selection by mode and architecture.
--
-- Z-Image-Turbo uses a SINGLE "Union" ControlNet
-- (Z-Image-Turbo-Fun-Controlnet-Union.safetensors) that handles every
-- mode — canny / depth / lineart / pose / scribble / tile are all
-- routed through the same file on the ComfyUI side and the loader
-- disambiguates by the preprocessor feeding it. The earlier per-mode
-- zit entries all pointed at SDXL\\controlnet-canny-sdxl-1.0
-- (copy-paste bug) which silently loaded an SDXL CN into a ZIT
-- workflow and either failed at sampling or produced garbage. Canon:
-- mirror what spellcaster_core.architectures._reg("zit", ...)
-- autoset_cn declares and what CONTROLNET_GUIDE_MODES["ZIT Union"]
-- uses in the GIMP plugin.
local ZIT_UNION_CN = "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"
local CN_MODEL_MAP = {
  canny    = {sd15 = "control_v11p_sd15_lineart_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors", zit = ZIT_UNION_CN},
  depth    = {sd15 = "control_v11f1p_sd15_depth_fp16.safetensors", sdxl = "SDXL\\control-lora-depth-rank128.safetensors", zit = ZIT_UNION_CN},
  lineart  = {sd15 = "control_v11p_sd15_lineart_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors", zit = ZIT_UNION_CN},
  pose     = {sd15 = "control_v11p_sd15_openpose_fp16.safetensors", sdxl = "OpenPoseXL2.safetensors", zit = ZIT_UNION_CN},
  scribble = {sd15 = "control_v11p_sd15_lineart_fp16.safetensors", sdxl = "SDXL\\controlnet-canny-sdxl-1.0.safetensors", zit = ZIT_UNION_CN},
  tile     = {sd15 = "control_v11f1e_sd15_tile.pth", sdxl = "SDXL\\ttplanetSDXLControlnet_Tile_v20Fp16.safetensors", zit = ZIT_UNION_CN},
}

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

function build_iclight_json(uploaded_name, ckpt, prompt, negative, seed, multiplier)
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

function build_supir_json(uploaded_name, supir_model, sdxl_model, prompt, seed, denoise, steps)
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

function build_seedv2r_json(uploaded_name, upscale_model, ckpt, prompt, negative,
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

function acquire_processing_lock()
  if _processing then
    dt.print(_("A workflow is already running — please wait"))
    return false
  end
  _processing = true
  return true
end

function release_processing_lock()
  _processing = false
end

-- IMAGE EXPORT & RESULT POLLING
-- ═══════════════════════════════════════════════════════════════════════
-- Darktable → ComfyUI requires exporting to temp files (PNG format with 8-bit color).
-- ComfyUI processing is async; we poll /history until results appear.

-- Export a Darktable image to a temporary PNG file for ComfyUI upload.
-- Uses 8-bit PNG (standard format for AI models).
-- @param image : Darktable image object from lighttable view
-- @return path, fname : tuple of (local file path, filename for upload) or (nil, nil) on failure
-- Usage:
--   local path, fname = export_to_temp(dt.database[1])
--   local resp = curl_upload(..., path, fname)  -- upload to ComfyUI
-- Filenames are unique: "dt_comfy_<timestamp>_<random>.png" to avoid collisions
function export_to_temp(image)
  local dir = tmp_dir()
  local fname = "dt_comfy_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  local path = dir .. sep .. fname
  local exp = dt.new_format("png")
  exp.bpp = 8
  exp:write_image(image, path)
  -- verify file was written (prevents returning invalid path)
  local f = io.open(path, "r")
  if not f then return nil, nil end
  f:close()
  return path, fname
end

-- SPLASH SCREEN (visual progress indicator during processing)
-- ═══════════════════════════════════════════════════════════════════════
-- While ComfyUI processes workflows (which can take 10+ minutes for video),
-- a Python Tkinter splash window shows progress and prevents UI freezing.
-- Communication: the splash stays open while a lock file exists, closes when deleted.
-- This avoids IPC complexity (no pipes, sockets, or shared memory needed).

-- Launch a splash screen process that displays until the lock file is deleted.
-- @return string : path to lock file (used to signal splash process to exit)
-- Locates splash.py relative to this Lua plugin directory.
-- On Windows: uses pythonw (no console window) + start /B (background process)
-- On Unix: uses python3 + & (background shell process)
function launch_splash()
  local lock_file = tmp_dir() .. sep .. "comfyui_splash_" .. os.time() .. "_" .. math.random(1000,9999) .. ".lock"
  local f = io.open(lock_file, "w")
  if f then f:write("1"); f:close() end

  -- Locate splash.py relative to this Lua file's directory
  -- debug.getinfo(1, "S").source gives the current file path with @ prefix
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

-- Signal the splash screen process to exit by deleting the lock file.
-- The splash Python process checks for file existence in a loop.
-- @param lock_file : path to lock file created by launch_splash()
function kill_splash(lock_file)
  if lock_file then
    os.remove(lock_file)
  end
end

-- RESULT POLLING FROM COMFYUI
-- ═══════════════════════════════════════════════════════════════════════
-- ComfyUI is async: /prompt returns immediately with a prompt_id (UUID).
-- Workflow execution happens in background; we poll /history/<prompt_id>
-- until the entry appears (indicating all nodes finished).
--
-- Polling strategy:
--   - Check /history every 2 seconds (dt.control.sleep(2000))
--   - Timeout is user-configurable (default 300s = 5 min, typical for images)
--   - For videos (Wan I2V), use longer timeout (600s = 10 min)
--   - Splash screen stays open during polling

-- Poll ComfyUI's /history endpoint until workflow completes or times out.
-- Filters results to return only PNG/JPG image files (ignores videos, metadata).
-- @param prompt_id : UUID returned from /prompt endpoint
-- @param timeout_override : max seconds to wait (nil = use preferences setting)
-- @return table or nil : array of output filenames (e.g. ["output_xyz.png"]) or nil on timeout
-- Usage:
--   local prompt_id = json_val(curl_post_json(...), "prompt_id")  -- submit workflow
--   local filenames = wait_result(prompt_id)  -- poll until done
--   if filenames then curl_download(...filename...) end
-- Polling loop:
--   1. GET /history/<prompt_id> → parse JSON
--   2. Look for "filename" fields in response
--   3. Filter to .png / .jpg extensions only
--   4. If any found, return list
--   5. Otherwise sleep 2s and retry
function wait_result(prompt_id, timeout_override)
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
-- @param prompt_id : UUID from /prompt endpoint
-- @param timeout_override : max seconds to wait (default 600s = 10min for video)
-- @return table or nil : array of {filename, subfolder} dicts or nil on timeout
function wait_result_all(prompt_id, timeout_override)
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

-- ═══════════════════════════════════════════════════════════════════════
-- IMG2IMG PROCESSING WRAPPER
-- ═══════════════════════════════════════════════════════════════════════
-- High-level orchestration for image-to-image workflows.
-- Coordinates: export → upload → build workflow → submit → poll → import result
--
-- This is a wrapper over build_img2img_json that handles the full pipeline:
-- 1. Export selected Darktable image to temp PNG
-- 2. Upload PNG to ComfyUI (multipart form)
-- 3. Build workflow JSON (img2img + optional LoRA/ControlNet)
-- 4. POST workflow to ComfyUI /prompt endpoint
-- 5. Poll /history until result appears
-- 6. Download output image and import back to Darktable
--
-- @param image : Darktable image object
-- @param preset : MODEL_PRESETS entry (ckpt, steps, cfg, etc.)
-- @param prompt, negative : text prompts from UI
-- @param lora_name, lora_strength : optional LoRA and its blend strength
-- @param cn_mode, cn_strength, cn_preprocessor, cn_model : optional ControlNet config
-- @param turbo_config : optional Hyper-SD/SDXL turbo LoRA config (or nil)
--
-- Progress updates: dt.print() at each major step (export, upload, processing, import)
--
-- On any error: dt.print() error message and early return (no crash)
--
function process_image(image, preset, prompt, negative, lora_name, lora_strength,
                              cn_mode, cn_strength, cn_preprocessor, cn_model,
                              turbo_config)
  local server = get_server()

  -- STEP 1: Export the selected Darktable image to a temp PNG file
  dt.print(string.format(_("Exporting for %s..."), preset.label))
  local path, fname = export_to_temp(image)
  if not path then
    dt.print(_("Export failed")); return
  end

  -- STEP 2: Upload temp PNG to ComfyUI's /upload/image endpoint
  -- ComfyUI stores it in ComfyUI/input/ directory with our provided filename
  dt.print(_("Uploading to ComfyUI..."))
  local upload_name = "dt_" .. os.time() .. "_" .. math.random(10000,99999) .. ".png"
  curl_upload(server .. "/upload/image", path, upload_name)
  os.remove(path)

  -- STEP 3: Determine scaling and random seed
  local seed = math.random(0, 2^31 - 1)
  local orig_w, orig_h = get_image_dims(image)
  local max_res = max_res_slider.value
  local scale_w, scale_h = compute_scale_dims(orig_w, orig_h, max_res)

  -- STEP 4: Build the workflow JSON DAG (img2img pattern)
  local wf_json = build_img2img_json(upload_name, preset, prompt, negative, seed,
                                      lora_name, lora_strength, scale_w, scale_h,
                                      cn_mode, cn_strength, cn_preprocessor, cn_model,
                                      turbo_config)

  -- STEP 5: Submit workflow to ComfyUI
  -- Response contains {"prompt_id": "<uuid>", "number": <int>, ...}
  -- We extract prompt_id to poll for results
  dt.print(_("Queuing prompt..."))
  local resp = curl_post_json(server .. "/prompt", wf_json)
  local pid = json_val(resp, "prompt_id")
  if not pid then
    dt.print(_("Failed to queue prompt")); return
  end

  -- STEP 6: Poll until workflow finishes (shows splash screen during wait)
  dt.print(string.format(_("Processing with %s..."), preset.label))
  local results = wait_result(pid)
  if not results then
    dt.print(_("Timed out or failed")); return
  end

  for j, rfn in ipairs(results) do
    local out = tmp_dir() .. sep .. "comfy_result_" .. os.time() .. "_" .. j .. ".png"
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end

  dt.print(string.format(_("Done: %s"), preset.label))
end

-- ── Face swap (saved model) processing ──────────────────────────────────
function process_faceswap_model(image, face_model_name, swap_model)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Face swap complete!"))
end

-- ── Save face model processing ──────────────────────────────────────────
-- Exports the selected image, uploads it, builds a face model from it,
-- and saves the model on the ComfyUI server as a .safetensors file.

function process_save_face_model(image, model_name, overwrite)
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

function process_rembg(image)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Background removed!"))
end

-- ── Upscale 4x processing ──────────────────────────────────────────────
function process_upscale(image, upscale_model_file)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Upscale complete!"))
end

-- ── Object Removal (LaMa) processing ──────────────────────────────────
function process_lama(image, mask_path)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Object removal complete!"))
end

-- ── Klein Inpaint (canonical) ──────────────────────────────────────────
-- Routes through POST /api/run_builder → spellcaster_core.workflows.build_klein_inpaint.
-- The Lua plugin used to do all inpainting via SDXL/KSampler; this path
-- gets the architecturally correct Klein workflow (UNETLoader +
-- Flux2Scheduler + SamplerCustomAdvanced + the Klein enhancer chain)
-- without duplicating the 200-line builder JSON.
--
-- Mask source — pass either ``mask_path`` (file on disk) OR
-- ``sam3_prompt`` (text describing what to mask, segmentation built
-- server-side via SAM3). When both are set, SAM3 wins because typing
-- a prompt is the explicit "I don't want to deal with mask files"
-- gesture. Either-or is enforced in the canonical builder.
function process_klein_inpaint(image, mask_path, klein_model_label,
                                      prompt, denoise, sam3_prompt)
  local server = get_server()

  dt.print(_("Exporting for Klein inpaint..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading image to ComfyUI..."))
  local img_name = "dt_kinp_img_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, img_name)
  os.remove(path)

  -- Mask param — SAM3 prompt takes precedence over file path
  local mask_param
  if sam3_prompt and sam3_prompt ~= "" then
    mask_param = string.format(
      ',"sam3_prompt":"%s","sam3_expand":6,"sam3_blur":4',
      json_escape(sam3_prompt))
    dt.print(_("Building SAM3 mask: ") .. sam3_prompt)
  elseif mask_path and mask_path ~= "" then
    dt.print(_("Uploading mask to ComfyUI..."))
    local mask_name = "dt_kinp_mask_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
    curl_upload(server .. "/upload/image", mask_path, mask_name)
    mask_param = string.format(',"mask_filename":"%s"', json_escape(mask_name))
  else
    dt.print(_("Klein inpaint: provide either a mask path or a SAM3 mask prompt"))
    return
  end

  local seed = math.random(1, 2^31 - 1)
  local params = string.format(
    '{"image_filename":"%s","prompt_text":"%s",'
    .. '"seed":%d,"klein_model_key":"%s","denoise":%.2f,"enhance":true%s}',
    json_escape(img_name),
    json_escape(prompt or ""),
    seed,
    json_escape(klein_model_label or "Klein 9B"),
    denoise or 0.92,
    mask_param)

  dt.print(_("Klein inpaint running (this may take a minute)..."))
  local urls, err = _run_builder("build_klein_inpaint", params)
  if not urls then
    dt.print(_("Klein inpaint failed: ") .. tostring(err))
    return
  end
  if #urls == 0 then
    dt.print(_("Klein inpaint returned no images"))
    return
  end
  local imported = _download_guild_assets(urls, "klein_inpaint")
  dt.print(string.format(_("Klein inpaint done — %d image(s) imported"), imported))
end

-- ── LaMa Object Removal (canonical, with SAM3 support) ─────────────────
-- The legacy build_lama_json + process_lama path requires a mask file.
-- This canonical path accepts a SAM3 prompt instead, so the user can
-- type "the trash can" and never leave Darktable.
function process_lama_canon(image, mask_path, sam3_prompt)
  local server = get_server()

  dt.print(_("Exporting for LaMa removal..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading image to ComfyUI..."))
  local img_name = "dt_lama2_img_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, img_name)
  os.remove(path)

  local mask_param
  if sam3_prompt and sam3_prompt ~= "" then
    mask_param = string.format(
      ',"sam3_prompt":"%s","sam3_expand":8,"sam3_blur":6',
      json_escape(sam3_prompt))
    dt.print(_("SAM3 mask: ") .. sam3_prompt)
  elseif mask_path and mask_path ~= "" then
    dt.print(_("Uploading mask to ComfyUI..."))
    local mask_name = "dt_lama2_mask_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
    curl_upload(server .. "/upload/image", mask_path, mask_name)
    mask_param = string.format(',"mask_filename":"%s"', json_escape(mask_name))
  else
    dt.print(_("LaMa Remove: provide either a mask path or a SAM3 mask prompt"))
    return
  end

  local params = string.format('{"image_filename":"%s"%s}',
                               json_escape(img_name), mask_param)
  dt.print(_("LaMa Remove running..."))
  local urls, err = _run_builder("build_lama_remove", params)
  if not urls then dt.print(_("LaMa Remove failed: ") .. tostring(err)); return end
  if #urls == 0 then dt.print(_("LaMa Remove returned no images")); return end
  local imported = _download_guild_assets(urls, "lama_remove")
  dt.print(string.format(_("LaMa Remove done — %d image(s) imported"), imported))
end

-- ── Klein Re-pose (canonical) ──────────────────────────────────────────
-- Routes through POST /api/run_builder → build_klein_repose. Uses
-- Klein's ReferenceLatent + BasicScheduler so the input photo's
-- structure is preserved as a soft guide while the prompt drives the
-- new pose / framing. Lower denoise = closer to the original;
-- higher denoise = freer reinterpretation.
function process_klein_repose(image, klein_model_label, prompt, denoise)
  local server = get_server()

  dt.print(_("Exporting for Klein re-pose..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local img_name = "dt_krep_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, img_name)
  os.remove(path)

  local seed = math.random(1, 2^31 - 1)
  local params = string.format(
    '{"image_filename":"%s","prompt_text":"%s","seed":%d,'
    .. '"klein_model_key":"%s","denoise":%.2f,"enhance":true}',
    json_escape(img_name),
    json_escape(prompt or ""),
    seed,
    json_escape(klein_model_label or "Klein 9B"),
    denoise or 0.65)

  dt.print(_("Klein re-pose running (this may take a minute)..."))
  local urls, err = _run_builder("build_klein_repose", params)
  if not urls then
    dt.print(_("Klein re-pose failed: ") .. tostring(err))
    return
  end
  if #urls == 0 then
    dt.print(_("Klein re-pose returned no images"))
    return
  end
  local imported = _download_guild_assets(urls, "klein_repose")
  dt.print(string.format(_("Klein re-pose done — %d image(s) imported"), imported))
end

-- ── Klein Head Swap (canonical) ────────────────────────────────────────
-- ReActor face swap → Klein img2img refinement. The two stages are
-- chained inside spellcaster_core.workflows.build_klein_headswap so we
-- just hand it both filenames + the model key. ``source`` is the face
-- to insert; ``target`` is the photo whose head gets replaced.
function process_klein_headswap(image, source_path, klein_model_label,
                                       prompt, denoise)
  local server = get_server()

  dt.print(_("Exporting target for Klein head swap..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading target to ComfyUI..."))
  local tgt_name = "dt_khs_tgt_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, tgt_name)
  os.remove(path)

  dt.print(_("Uploading source face..."))
  local src_name = "dt_khs_src_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", source_path, src_name)

  local seed = math.random(1, 2^31 - 1)
  local params = string.format(
    '{"target_filename":"%s","source_filename":"%s","prompt":"%s",'
    .. '"seed":%d,"klein_model_key":"%s","denoise":%.2f,"enhance":true}',
    json_escape(tgt_name),
    json_escape(src_name),
    json_escape(prompt or ""),
    seed,
    json_escape(klein_model_label or "Klein 9B"),
    denoise or 0.35)

  dt.print(_("Klein head swap running (ReActor + Klein refine)..."))
  local urls, err = _run_builder("build_klein_headswap", params)
  if not urls then dt.print(_("Klein head swap failed: ") .. tostring(err)); return end
  if #urls == 0 then dt.print(_("Klein head swap returned no images")); return end
  local imported = _download_guild_assets(urls, "klein_headswap")
  dt.print(string.format(_("Klein head swap done — %d image(s) imported"), imported))
end

-- ── Klein img2img with reference (canonical) ───────────────────────────
-- Uses the reference image as the ReferenceLatent source rather than
-- the input itself — soft style/lighting/structure guidance from a
-- separate photo while editing the main image. ref_strength 1.0 =
-- strong influence, 0.4 = subtle nudge.
function process_klein_img2img_ref(image, ref_path, klein_model_label,
                                          prompt, denoise, ref_strength)
  local server = get_server()

  dt.print(_("Exporting for Klein img2img+ref..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading image to ComfyUI..."))
  local img_name = "dt_kref_img_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, img_name)
  os.remove(path)

  dt.print(_("Uploading reference..."))
  local ref_name = "dt_kref_ref_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", ref_path, ref_name)

  local seed = math.random(1, 2^31 - 1)
  local params = string.format(
    '{"image_filename":"%s","ref_filename":"%s","prompt_text":"%s",'
    .. '"seed":%d,"klein_model_key":"%s","denoise":%.2f,'
    .. '"ref_strength":%.2f,"enhance":true}',
    json_escape(img_name),
    json_escape(ref_name),
    json_escape(prompt or ""),
    seed,
    json_escape(klein_model_label or "Klein 9B"),
    denoise or 0.65,
    ref_strength or 1.0)

  dt.print(_("Klein img2img+ref running..."))
  local urls, err = _run_builder("build_klein_img2img_ref", params)
  if not urls then dt.print(_("Klein img2img+ref failed: ") .. tostring(err)); return end
  if #urls == 0 then dt.print(_("Klein img2img+ref returned no images")); return end
  local imported = _download_guild_assets(urls, "klein_img2img_ref")
  dt.print(string.format(_("Klein img2img+ref done — %d image(s) imported"), imported))
end

-- ── Generate 3D Normal Map (NormalCrafter, canonical) ─────────────────
-- Routes through POST /api/run_builder → build_normal_map. Produces a
-- 3D surface normal map useful for relighting, ControlNet normal
-- guidance in GIMP, or 3D reconstruction workflows. The GIMP plugin
-- has a native menu entry for the same builder; this DT button mirrors
-- it so a RAW processor user can generate the normal map without
-- leaving Darktable first.
function process_normal_map(image, max_res)
  local server = get_server()
  -- Fix 4b (3D audit 2026-04-20): preflight the NormalCrafter custom
  -- node so the user sees an actionable message before we spend time
  -- exporting and uploading. Without this, a missing node crashes the
  -- workflow submit ~2 s after upload with a raw ComfyUI error.
  local probe = curl_get(server .. "/object_info/NormalCrafterNode")
  if not probe or probe == "" or probe:find('"error"', 1, true) then
    dt.print(_("💎 3D Normal Map needs the NormalCrafter custom node on ComfyUI. "
               .. "Install it via ComfyUI Manager → Install Custom Nodes → "
               .. "search 'NormalCrafter', restart ComfyUI, try again."))
    return
  end
  dt.print(_("Exporting for normal map..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end
  dt.print(_("Uploading to ComfyUI..."))
  local img_name = "dt_normal_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, img_name)
  os.remove(path)
  local params = string.format(
    '{"image_filename":"%s","max_res":%d}',
    json_escape(img_name), max_res or 1024)
  dt.print(_("Generating 3D normal map via NormalCrafter..."))
  local urls, err = _run_builder("build_normal_map", params)
  if not urls then
    dt.print(_("Normal map failed: ") .. tostring(err))
    return
  end
  if #urls == 0 then
    dt.print(_("Normal map returned no images"))
    return
  end
  local imported = _download_guild_assets(urls, "normal_map")
  dt.print(string.format(_("Normal map done — %d image(s) imported"), imported))
end

-- ── Upscale Blend (canonical) ──────────────────────────────────────────
-- Run two upscaler models in parallel and blend the outputs. Useful
-- when one model is sharp-but-crunchy (e.g. RealESRGAN) and the other
-- is smooth-but-soft (e.g. Remacri) — the blend gives a tunable
-- middle ground.
function process_upscale_blend(image, model_a_file, model_b_file,
                                      blend_factor, scale_by)
  local server = get_server()

  dt.print(_("Exporting for upscale blend..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local img_name = "dt_ublend_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, img_name)
  os.remove(path)

  local params = string.format(
    '{"image_filename":"%s","model_a_name":"%s","model_b_name":"%s",'
    .. '"blend_factor":%.2f,"scale_by":%.2f}',
    json_escape(img_name),
    json_escape(model_a_file or ""),
    json_escape(model_b_file or ""),
    blend_factor or 0.5,
    scale_by or 1.0)

  dt.print(_("Upscale blend running..."))
  local urls, err = _run_builder("build_upscale_blend", params)
  if not urls then dt.print(_("Upscale blend failed: ") .. tostring(err)); return end
  if #urls == 0 then dt.print(_("Upscale blend returned no images")); return end
  local imported = _download_guild_assets(urls, "upscale_blend")
  dt.print(string.format(_("Upscale blend done — %d image(s) imported"), imported))
end

-- ── Z-Image-Turbo img2img (canonical, full quality stack) ─────────────
-- Routes through POST /api/run_builder → build_img2img with arch="zit",
-- so the canonical Python builder applies the full ZIT optimization
-- chain (PAG @ scale 1.5 + SkipLayerGuidanceDiT @ scale 2.0 + optional
-- TeaCache @ rel_l1_thresh=0.3 when fast_mode=True). Single source of
-- truth — Darktable doesn't reimplement the workflow.
--
-- Optional sam3_prompt scopes the change to a SAM3-segmented region
-- (the same plumbing the Klein flows use). Optional ckpt override lets
-- the user point at a different ZIT checkpoint than the AIO default.
function process_zit_img2img(image, prompt, negative, denoise,
                                    quality, fast_mode, sam3_prompt,
                                    ckpt_override, lora_name, lora_strength)
  local server = get_server()

  dt.print(_("Exporting for Z-Image-Turbo img2img..."))
  local path, fname = export_to_temp(image)
  if not path then dt.print(_("Export failed")); return end

  dt.print(_("Uploading to ComfyUI..."))
  local img_name = "dt_zit_img_" .. os.time() .. "_" .. math.random(10000, 99999) .. ".png"
  curl_upload(server .. "/upload/image", path, img_name)
  os.remove(path)

  -- Build extras: sam3 + ckpt + loras as comma-prefixed JSON tail. The
  -- canonical build_img2img accepts loras=[{name, strength_model,
  -- strength_clip}] and runs them through inject_lora_chain — which
  -- (per CLAUDE.md model_detect.LORA_COMPAT_BUCKETS) silently drops
  -- cross-arch LoRAs. ZIT-folder LoRAs get the zit bucket and are
  -- safe to inject; passing through any other folder is a no-op.
  local extras = ""
  if sam3_prompt and sam3_prompt ~= "" then
    extras = extras .. string.format(
      ',"sam3_prompt":"%s","sam3_expand":6,"sam3_blur":4',
      json_escape(sam3_prompt))
  end
  if ckpt_override and ckpt_override ~= "" then
    extras = extras .. string.format(',"ckpt":"%s"', json_escape(ckpt_override))
  end
  if lora_name and lora_name ~= "" then
    local s = lora_strength or 1.0
    extras = extras .. string.format(
      ',"loras":[{"name":"%s","strength_model":%.3f,"strength_clip":%.3f}]',
      json_escape(lora_name), s, s)
  end

  local seed = math.random(1, 2^31 - 1)
  local fast_str = (fast_mode and "true" or "false")
  local params = string.format(
    '{"image_filename":"%s","arch":"zit","prompt_text":"%s","negative_text":"%s",'
    .. '"seed":%d,"denoise":%.2f,"quality":"%s","fast_mode":%s%s}',
    json_escape(img_name),
    json_escape(prompt or ""),
    json_escape(negative or ""),
    seed,
    denoise or 0.55,
    quality or "balanced",
    fast_str,
    extras)

  dt.print(string.format(
    _("Z-Image-Turbo img2img running (quality=%s, fast=%s)..."),
    quality or "balanced", fast_str))
  local urls, err = _run_builder("build_img2img", params)
  if not urls then
    dt.print(_("Z-Image-Turbo img2img failed: ") .. tostring(err))
    return
  end
  if #urls == 0 then
    dt.print(_("Z-Image-Turbo img2img returned no images"))
    return
  end
  local imported = _download_guild_assets(urls, "zit_img2img")
  dt.print(string.format(_("Z-Image-Turbo done — %d image(s) imported"), imported))
end

-- ── Color Grading / LUT processing ────────────────────────────────────
function process_lut(image, lut_file, strength)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("LUT color grading complete!"))
end

-- ── Outpaint / Extend Canvas processing ───────────────────────────────
function process_outpaint(image, preset, prompt, negative,
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Outpaint complete!"))
end

-- ── Style Transfer (IPAdapter) processing ─────────────────────────────
function process_style_transfer(image, style_ref_path, ckpt, prompt, negative, strength)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Style transfer complete!"))
end

-- ── Face Restore processing ──────────────────────────────────────────────
function process_face_restore(image, model, visibility, codeformer_weight)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Face restore complete!"))
end

-- ── Photo Restoration Pipeline processing ────────────────────────────────
function process_photo_restore(image, upscale_model, face_model, sharpen_alpha)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Photo restoration complete!"))
end

-- ── Detail Hallucination processing ──────────────────────────────────────
function process_detail_hallucinate(image, ckpt, prompt, negative, cfg, denoise)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Detail hallucination complete!"))
end

-- ── Colorize B&W processing ──────────────────────────────────────────────
function process_colorize(image, ckpt, controlnet_name, prompt, negative, strength, denoise)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Colorization complete!"))
end

-- ── Wan I2V processing ──────────────────────────────────────────────────
-- CANONICAL path (CLAUDE.md §16.4 rule #4): route through Guild's shot API.
-- The Guild wraps spellcaster_core.workflows.build_wan_video +
-- video_presets.wan_turbo_kwargs so this plugin tracks the canon
-- automatically. The old hand-rolled JSON (build_wan_i2v_json) is left in
-- the file as an emergency escape hatch but is no longer called.
function process_wan_i2v(image, wan_preset_idx, prompt, negative,
                                width, height, length, steps, cfg, shift, second_step,
                                loras, accel_enabled, accel_strength,
                                upscale, upscale_factor, interpolate, pingpong, fps,
                                crop_region, end_image_path, vace_strength,
                                advanced)
  local guild = get_guild_url()
  if not guild or guild == "" then
    dt.print(_("Wizard Guild URL not configured — preferences → Wizard Guild URL"))
    return
  end

  -- Map the Darktable UI "WAN preset" label to a Guild preset name.
  -- The Guild knows how to pick the right UNET / VAE / accel LoRAs via
  -- video_presets.detect_wan_preset + wan_turbo_kwargs. We only need to
  -- tell it which schedule the user wants (turbo vs HQ).
  local dt_preset = WAN_I2V_MODELS[wan_preset_idx] or {}
  local label = (dt_preset.label or ""):lower()
  -- Heuristic: explicit HQ / full-step labels go to wan22_i2v_hq,
  -- everything else (lightning / Q4 / fp8 / default) goes to lightning.
  local guild_preset =
    (label:find("hq") or label:find("full") or label:find("quality"))
      and "wan22_i2v_hq"
       or "wan22_i2v_lightning"

  dt.print(_("Exporting for Wan I2V..."))
  local ref_path, fname = export_to_temp(image)
  if not ref_path then dt.print(_("Export failed")); return end

  -- Build the `overrides` dict — per-shot parameters the Guild passes
  -- straight through to build_wan_video. Only non-nil / non-default
  -- values are sent so the canonical preset is free to fill its defaults.
  local overrides = {}
  if width           then overrides.width           = width end
  if height          then overrides.height          = height end
  if length          then overrides.length          = length end
  if fps             then overrides.fps             = fps end
  if pingpong ~= nil then overrides.pingpong        = pingpong and true or false end
  if upscale ~= nil  then
    overrides.rtx_scale = (upscale and (upscale_factor or 2.5)) or 0
  end
  if interpolate ~= nil then overrides.interpolate  = interpolate and true or false end
  -- Pass LoRA lists when the user picked any — the Guild's canonical
  -- build_wan_video wires these via lora_loader_model_only (CLAUDE.md
  -- §16.2 "LoRA injection"); the cross-family filter is bypassed so WAN
  -- LoRAs aren't dropped.
  if loras and loras.high and #loras.high > 0 then
    overrides.loras_high = table.concat(loras.high, ",")
  end
  if loras and loras.low and #loras.low > 0 then
    overrides.loras_low = table.concat(loras.low, ",")
  end
  if accel_enabled ~= nil then overrides.accel_enabled   = accel_enabled and true or false end
  if accel_strength        then overrides.accel_strength  = accel_strength end
  if end_image_path and end_image_path ~= "" then
    -- The Guild's shot API doesn't currently surface end_image, but the
    -- override is passed through so future endpoints can read it.
    overrides.end_image_path = end_image_path
  end
  if vace_strength then overrides.vace_strength = vace_strength end

  -- Advanced WAN 2.2 quality / speed patches (CLAUDE.md §16.2). Each value
  -- is a tri-state string: "auto" (defer to server probe), "on" (force),
  -- or "off" (force). The scaffold dispatcher only forwards non-"auto"
  -- values so the canonical builder's server-probe default stays intact.
  if advanced then
    local function _fwd(key)
      local v = advanced[key]
      if v and v ~= "auto" then overrides[key] = v end
    end
    _fwd("teacache"); _fwd("sage"); _fwd("cfg_zero"); _fwd("slg"); _fwd("nag")
    if advanced.sampler_name then overrides.sampler_name = advanced.sampler_name end
    if advanced.scheduler    then overrides.scheduler    = advanced.scheduler end
  end

  local title = string.format("Darktable: %s", (image and image.filename) or "frame")
  dt.print(_("Creating shot in the Wizard Guild..."))
  local shot_id, err = guild_create_shot(title, prompt, negative or "",
                                         guild_preset, overrides)
  if not shot_id then
    dt.print(string.format(_("Could not create shot: %s"), tostring(err)))
    os.remove(ref_path)
    return
  end

  dt.print(_("Uploading reference frame..."))
  local ok_ref, ref_err = guild_attach_reference(shot_id, ref_path)
  os.remove(ref_path)
  if not ok_ref then
    dt.print(string.format(_("Reference upload failed: %s"), tostring(ref_err)))
    return
  end

  dt.print(string.format(_("Rendering via canonical pipeline (%s)..."),
                         guild_preset))
  local ok_render, status_or_err = guild_render_shot(shot_id)
  if not ok_render then
    dt.print(string.format(_("Render request refused: %s"),
                           tostring(status_or_err)))
    return
  end

  local ok_ready, status = guild_wait_for_shot_ready(shot_id, 900)
  if not ok_ready then
    dt.print(string.format(_("Render did not complete: %s"), tostring(status)))
    return
  end

  local vid_dir = tmp_dir() .. sep .. "comfyui_videos"
  os.execute((dt.configuration.running_os == "windows" and "mkdir " or "mkdir -p ")
             .. '"' .. shell_esc(vid_dir) .. '"')
  local vid_path = vid_dir .. sep .. string.format(
    "guild_wan_%s_%d.mp4", shot_id:sub(1, 8), os.time())
  local ok_dl, dl_err = guild_download_shot_video(shot_id, vid_path)
  if not ok_dl then
    dt.print(string.format(_("Video download failed: %s"), tostring(dl_err)))
    return
  end

  -- Open with system player
  if dt.configuration.running_os == "windows" then
    os.execute('start "" "' .. shell_esc(vid_path) .. '"')
  elseif dt.configuration.running_os == "macos" then
    os.execute('open "' .. shell_esc(vid_path) .. '"')
  else
    os.execute('xdg-open "' .. shell_esc(vid_path) .. '" &')
  end

  dt.print(_("Wan I2V complete (canonical pipeline) — video opened in player"))
end

-- ── Klein Flux2 processing ──────────────────────────────────────────────
function process_klein(image, klein_model, prompt, steps, guidance)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(string.format(_("Klein %s complete!"), klein_model.label))
end

-- ── PuLID Flux processing ───────────────────────────────────────────────
function process_pulid_flux(image, face_source_path, prompt, strength, steps, guidance)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("PuLID Flux complete!"))
end

-- ── Face swap (direct/ReActor) processing ───────────────────────────────
function process_faceswap_direct(image, source_path, swap_model)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("Direct face swap complete!"))
end

-- ── FaceID (IPAdapter) processing ────────────────────────────────────────
function process_faceid(image, preset, face_ref_path, prompt, negative,
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(string.format(_("FaceID %s complete!"), preset.label))
end

-- ── Klein + Reference processing ────────────────────────────────────────
function process_klein_ref(image, ref_path, klein_model, prompt, steps, guidance)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(string.format(_("Klein+Ref %s complete!"), klein_model.label))
end

-- ── Inpaint processing ──────────────────────────────────────────────────
function process_inpaint(image, preset, mask_path, prompt, negative, loras,
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(string.format(_("Inpaint %s complete!"), preset.label))
end

-- ── Batch Variations processing ──────────────────────────────────────────
function process_batch_variations(preset, prompt, negative, lora_name, lora_strength, width, height, batch_count)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(string.format(_("Batch complete! %d variations generated."), #results))
end

-- (Standalone ControlNet process functions removed -- ControlNet is now
--  integrated into img2img and inpaint via cn_guide_selector widget)

-- ── IC-Light Relighting processing ───────────────────────────────────────
function process_iclight(image, prompt, negative, multiplier)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("IC-Light relighting complete!"))
end

-- ── SUPIR AI Restoration processing ──────────────────────────────────────
function process_supir(image, supir_model, sdxl_model, prompt, steps, denoise)
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
    _download_comfyui_view(server, rfn, out)
    dt.database.import(out)
  end
  dt.print(_("SUPIR restoration complete!"))
end

-- ── SeedV2R Upscaler processing ────────────────────────────────────────
function process_seedv2r(image, upscale_model, ckpt, prompt, negative,
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
    _download_comfyui_view(server, rfn, out)
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
function load_presets_from_file(section)
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
function serialize_value(v)
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
function save_presets_to_file(section, presets)
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
function make_preset_widgets(section_key, collect_fn, apply_fn)
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
model_selector = dt.new_widget("combobox") {
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

prompt_entry = dt.new_widget("entry"){
  tooltip = _("Positive prompt (model hint is prepended automatically)"),
  text = "",
  editable = true,
}

negative_entry = dt.new_widget("entry"){
  tooltip = _("Negative prompt (model hint is prepended automatically)"),
  text = "",
  editable = true,
}

-- Scene preset selector — populated dynamically by refresh_scene_selector()
scene_selector = dt.new_widget("combobox") {
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

denoise_slider = dt.new_widget("slider"){
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

lora_selector = dt.new_widget("combobox") {
  label = _("LoRA"),
  tooltip = _("Select a compatible LoRA (click Fetch first)"),
  selected = 1,
  "(none)",
}

lora_strength_slider = dt.new_widget("slider"){
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

fetch_lora_btn = dt.new_widget("button") {
  label = _("Fetch LoRAs"),
  tooltip = _("Fetch LoRAs from ComfyUI (filtered by model architecture). Also refreshes the dedicated Z-Image-Turbo LoRA picker further down."),
  clicked_callback = function()
    local all = fetch_all_loras()
    refresh_lora_selector()
    -- Pop the dedicated ZIT-arch LoRA picker too. Defined later in the
    -- file (near the Z-Image-Turbo Advanced section); guard with a type
    -- check so this fires only after the function has been declared.
    if type(refresh_zit_lora_selector) == "function" then
      refresh_zit_lora_selector()
    end
    local shown = #cached_loras
    local total = #all
    local arch = get_current_arch()
    -- Distinguish between "server unreachable / wrong URL" (total=0)
    -- and "server up, no compatible LoRAs for this arch" (shown=0,
    -- total>0). The old message collapsed both into a confusing
    -- "Found 0/0 LoRAs" without indicating which. dt.print now
    -- prepends a ⚠ marker when the server returned nothing so users
    -- immediately check their Server setting instead of assuming
    -- they have no LoRAs installed.
    if total == 0 then
      dt.print(string.format(
        _("⚠ LoRA fetch returned 0 \u{2014} is ComfyUI at %s running? "
          .. "Check Server in Spellcaster preferences."),
        get_server()))
    else
      dt.print(string.format(
        _("Found %d/%d LoRAs for %s"), shown, total, arch))
    end
  end
}

turbo_check = dt.new_widget("check_button") {
  label = _("⚡ Turbo (Hyper-SD 8-step)"),
  tooltip = _("Turbo Mode — Hyper-SD accelerator LoRA for ~3x faster generation.\n\n"
    .. "ON:  8 steps with specialized CFG-preserving turbo LoRA.\n"
    .. "     Quality is 85-95% of full — excellent for iteration.\n"
    .. "     Negative prompts still work (8-step CFG variant).\n\n"
    .. "OFF: Normal steps from preset (20-50). Maximum quality.\n\n"
    .. "Supports: SD1.5, SDXL, Illustrious, Flux Dev, Flux Kontext.\n"
    .. "Not needed for: ZIT (already 4 steps), Klein Flux2 (already 4 steps)."),
  value = false,
}

max_res_slider = dt.new_widget("slider") {
  label = _("Max Processing Res"),
  tooltip = _("Max longest-side resolution for ComfyUI processing. Images larger than this are downscaled before processing and restored to original size afterward."),
  soft_min = 512, soft_max = 4096,
  hard_min = 256, hard_max = 8192,
  step = 64, digits = 0, value = 2048,
}

status_label = dt.new_widget("label") { label = _("Ready") }

-- ── SpeedCoach strip + last-run footer ────────────────────────────
-- Minimal surface that matches the design spec: one italic grey line
-- with predicted elapsed + fastest alternative above the dispatch
-- button, and a coloured last-run footer below. Both poll the Guild's
-- /api/speedcoach/* endpoints every 10 s and update in place.
speedcoach_strip   = dt.new_widget("label") { label = _("") }
speedcoach_footer  = dt.new_widget("label") { label = _("") }

function speedcoach_raw_get(path)
  local guild = get_guild_url()
  if not guild or guild == "" then return nil end
  local resp = curl_get(guild .. path)
  if not resp or #resp < 2 then return nil end
  return resp
end

function speedcoach_refresh()
  -- Strip above dispatch: fastest arch on this box from arch_speeds.
  -- Regex-parse a JSON response shaped like:
  --   {"archs": [{"arch": "...", "ok": true, "elapsed_ms": 1234, ...}, ...]}
  -- The DT plugin parses JSON with string.match everywhere, so keep
  -- the same pattern (no dkjson dep).
  local resp = speedcoach_raw_get("/api/speedcoach/arch_speeds") or ""
  local fastest_arch, fastest_ms = nil, nil
  for arch_name, ms_str in string.gmatch(
        resp,
        '"arch"%s*:%s*"([^"]+)"%s*,%s*"ok"%s*:%s*true[^%}]-"elapsed_ms"%s*:%s*(%d+)'
      ) do
    local ms = tonumber(ms_str) or 0
    if ms > 0 and (not fastest_ms or ms < fastest_ms) then
      fastest_arch, fastest_ms = arch_name, ms
    end
  end
  if fastest_arch and fastest_ms then
    speedcoach_strip.label = string.format(
      _("~%.1fs fastest arch on your box (%s)   Speed chart in Guild"),
      fastest_ms / 1000.0, fastest_arch)
  else
    speedcoach_strip.label = _("First run for this config - no estimate yet")
  end
  -- Last-run footer: outcome + elapsed from warnings_last endpoint.
  local wresp = speedcoach_raw_get("/api/speedcoach/warnings_last") or ""
  local outcome = wresp:match('"outcome"%s*:%s*"([^"]+)"') or "unknown"
  local elapsed_str = wresp:match('"elapsed"%s*:%s*([%d%.]+)') or "0"
  local elapsed = tonumber(elapsed_str) or 0
  local wcount = 0
  for _w in string.gmatch(wresp:match('"warnings"%s*:%s*%[(.-)%]') or "", '"')
  do wcount = wcount + 1 end
  wcount = math.floor(wcount / 2)  -- each string has open+close quote
  if outcome == "ok" and elapsed > 0 then
    speedcoach_footer.label = string.format(
      _("Last run: OK (%ds)"), math.floor(elapsed))
  elseif outcome == "warnings" then
    speedcoach_footer.label = string.format(
      _("Last run: %d warnings (%ds)"), wcount, math.floor(elapsed))
  elseif outcome == "failed" then
    speedcoach_footer.label = _("Last run: FAILED")
  else
    speedcoach_footer.label = _("")
  end
end

-- Refresh once on plugin load. Subsequent refreshes happen when the
-- user presses the refresh button (explicit) or right after any send.
pcall(speedcoach_refresh)

speedcoach_refresh_btn = dt.new_widget("button") {
  label = _("\xE2\x9A\xA1 Refresh speed stats"),
  tooltip = _("Re-poll the Guild for predicted elapsed + last run outcome."),
  clicked_callback = function() pcall(speedcoach_refresh) end,
}

test_btn = dt.new_widget("button") {
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

img2img_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

send_btn = dt.new_widget("button") {
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

    -- Resolve turbo acceleration
    local tc = nil
    if turbo_check.value then
      tc = get_turbo_config(get_current_arch())
    end

    local runs = math.floor(img2img_runs_slider.value)
    for i, img in ipairs(images) do
      for run_i = 1, runs do
        if runs > 1 then
          dt.print(string.format(_("Image %d/%d, run %d/%d"), i, #images, run_i, runs))
        else
          dt.print(string.format(_("Image %d/%d"), i, #images))
        end
        local ok, err = pcall(process_image, img, p, prompt, negative, lora_name, lora_str,
                               cn_mode, cn_str, cn_preprocessor, cn_model_name, tc)
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

upload_btn = dt.new_widget("button") {
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
info_label = dt.new_widget("label") {
  label = _("Select a model to see its settings")
}

-- ═══════════════════════════════════════════════════════════════════════
-- Face Swap GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

face_model_selector = dt.new_widget("combobox") {
  label = _("Face Model"),
  tooltip = _("Saved face model from ComfyUI ReActor"),
  selected = 1,
  "(none — click Fetch)",
}

swap_model_selector = dt.new_widget("combobox") {
  label = _("Swap Engine"),
  tooltip = _("Face swap model engine"),
  selected = 1,
  "inswapper_128.onnx",
}

fetch_face_btn = dt.new_widget("button") {
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

faceswap_btn = dt.new_widget("button") {
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

save_face_model_name_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("my_face_model"),
  tooltip = _("Name for the saved face model (without .safetensors extension)"),
  editable = true,
}

save_face_model_overwrite_check = dt.new_widget("check_button") {
  label = _("Overwrite existing"),
  tooltip = _("If checked, overwrite an existing face model with the same name"),
  value = false,
}

save_face_model_btn = dt.new_widget("button") {
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

mtb_source_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to source face image..."),
  tooltip = _("Full path to the face image to swap onto the target"),
  editable = true,
}

mtb_source_btn = dt.new_widget("button") {
  label = _("Browse Source Face..."),
  tooltip = _("Select a source face image file"),
  clicked_callback = function()
    -- Use file_chooser_button alternative via entry
    dt.print(_("Enter the full path to the source face image in the text field above"))
  end
}

mtb_analysis_selector = dt.new_widget("combobox") {
  label = _("Analysis Model"),
  tooltip = _("Face analysis model for detection"),
  selected = 1,
  "buffalo_l", "antelopev2", "buffalo_m", "buffalo_sc",
}

mtb_swap_selector = dt.new_widget("combobox") {
  label = _("Swap Model"),
  tooltip = _("Face swap model (inswapper)"),
  selected = 1,
  "inswapper_128.onnx", "inswapper_128_fp16.onnx",
}

mtb_face_idx_entry = dt.new_widget("entry") {
  text = "0",
  placeholder = "0",
  tooltip = _("Face index (0 = first detected face)"),
  editable = true,
}

mtb_swap_btn = dt.new_widget("button") {
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

wan_model_selector = dt.new_widget("combobox") {
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

wan_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt for video generation"),
  text = "",
  editable = true,
}

wan_neg_entry = dt.new_widget("entry") {
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

wan_frames_slider = dt.new_widget("slider") {
  label = _("Frames"),
  tooltip = _("Number of frames (81 = ~5s at 16fps)"),
  soft_min = 17, soft_max = 257,
  hard_min = 1, hard_max = 257,
  step = 4, digits = 0, value = 81,
}

wan_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Sampling steps"),
  soft_min = 10, soft_max = 50,
  hard_min = 1, hard_max = 100,
  step = 1, digits = 0, value = 30,
}

wan_cfg_slider = dt.new_widget("slider") {
  label = _("CFG"),
  tooltip = _("Classifier free guidance scale (5.0 recommended for fatberg_slim)"),
  soft_min = 1, soft_max = 15,
  hard_min = 0, hard_max = 30,
  step = 0.5, digits = 1, value = 5.0,
}

wan_shift_slider = dt.new_widget("slider") {
  label = _("Shift"),
  tooltip = _("Noise shift (8.0 recommended for fatberg_slim)"),
  soft_min = 1, soft_max = 20,
  hard_min = 0, hard_max = 100,
  step = 0.5, digits = 1, value = 8.0,
}

wan_second_step_slider = dt.new_widget("slider") {
  label = _("Switch Step"),
  tooltip = _("Step at which sampling switches from high-noise to low-noise model"),
  soft_min = 5, soft_max = 40,
  hard_min = 1, hard_max = 100,
  step = 1, digits = 0, value = 20,
}

wan_upscale_check = dt.new_widget("check_button") {
  label = _("RTX Upscale"),
  tooltip = _("Apply RTXVideoSuperResolution upscale after generation"),
  value = true,
}

wan_upscale_factor_slider = dt.new_widget("slider") {
  label = _("RTX Scale"),
  tooltip = _("RTX upscale factor (e.g. 1.5 = 50% larger)"),
  soft_min = 1.0, soft_max = 4.0,
  hard_min = 1.0, hard_max = 4.0,
  step = 0.25, digits = 2, value = 1.5,
}

wan_interpolate_check = dt.new_widget("check_button") {
  label = _("RIFE 2x Interpolation"),
  tooltip = _("Apply RIFE VFI 2x frame interpolation (doubles FPS)"),
  value = true,
}

wan_pingpong_check = dt.new_widget("check_button") {
  label = _("Ping Pong"),
  tooltip = _("Play video forward then backward for seamless looping"),
  value = false,
}

wan_accel_check = dt.new_widget("check_button") {
  label = _("Acceleration LoRA"),
  tooltip = _("Apply preset-specific speed LoRAs (e.g. LightX2V) for ~4x faster inference.\nDisable for full-quality slow generation."),
  value = true,
}

wan_accel_strength_slider = dt.new_widget("slider") {
  label = _("Accel Strength"),
  tooltip = _("Accelerator LoRA strength (1.0 = default, lower = slower but potentially higher quality)"),
  soft_min = 0, soft_max = 2,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

-- Advanced WAN 2.2 quality / speed patches (CLAUDE.md §16.2). Each combobox
-- is tri-state:
--   index 1 "Auto"  → defer to the Guild server probe (enable if node exists)
--   index 2 "On"    → force-enable (fails validation if server lacks node)
--   index 3 "Off"   → force-disable
-- The Guild's scaffold/video_workflow_dispatch.py forwards these overrides
-- to the canonical build_wan_video.
function _wan_tri_combo(label, tooltip)
  return dt.new_widget("combobox") {
    label = _(label),
    tooltip = _(tooltip),
    selected = 1,
    _("Auto"), _("On"), _("Off"),
  }
end
local wan_teacache_combo = _wan_tri_combo("TeaCache",
  "TeaCache cross-step cache — 30-40% speedup on full-step (30-step) runs.\n"
  .. "Auto: on for full-step, off for turbo.\nOn/Off: force the choice.")
local wan_sage_combo = _wan_tri_combo("SAGE Attention",
  "SageAttention kernel — 50-100% sampler speedup on RTX 40/50xx, neutral quality.\n"
  .. "Requires ComfyUI-KJNodes (PatchSageAttentionKJ).")
local wan_cfg_zero_combo = _wan_tri_combo("CFG Zero★",
  "CFG Zero Star — CFG=0 on the first sampling step to reduce burn-in.\nSmall quality win at zero cost. Requires recent ComfyUI.")
local wan_slg_combo = _wan_tri_combo("SLG (Skip Layer Guidance)",
  "SkipLayerGuidanceSD3 — skips layers 7/8/9 during CFG for cleaner motion.\nCore ComfyUI node.")
local wan_nag_combo = _wan_tri_combo("NAG (Negative Attention)",
  "WanVideoNAG — Normalized Attention Guidance for sharper motion, less drift.\nRequires Kijai's WanVideoWrapper pack.")

function _tri_combo_to_str(combo)
  local idx = combo.selected or 1
  if idx == 2 then return "on" end
  if idx == 3 then return "off" end
  return "auto"
end

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
wan_lora_high_1 = dt.new_widget("combobox") {
  label = _("Pair 1 — High Noise"),
  tooltip = _("LoRA for the high-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
wan_lora_low_1 = dt.new_widget("combobox") {
  label = _("Pair 1 — Low Noise"),
  tooltip = _("LoRA for the low-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
wan_lora_str_slider_1 = dt.new_widget("slider") {
  label = _("Pair 1 Strength"),
  tooltip = _("LoRA pair 1 strength"),
  soft_min = -2, soft_max = 2,
  hard_min = -2, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

wan_lora_high_2 = dt.new_widget("combobox") {
  label = _("Pair 2 — High Noise"),
  tooltip = _("LoRA for the high-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
wan_lora_low_2 = dt.new_widget("combobox") {
  label = _("Pair 2 — Low Noise"),
  tooltip = _("LoRA for the low-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
wan_lora_str_slider_2 = dt.new_widget("slider") {
  label = _("Pair 2 Strength"),
  tooltip = _("LoRA pair 2 strength"),
  soft_min = -2, soft_max = 2,
  hard_min = -2, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

wan_lora_high_3 = dt.new_widget("combobox") {
  label = _("Pair 3 — High Noise"),
  tooltip = _("LoRA for the high-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
wan_lora_low_3 = dt.new_widget("combobox") {
  label = _("Pair 3 — Low Noise"),
  tooltip = _("LoRA for the low-noise UNET model (click Fetch first)"),
  selected = 1,
  "(none)",
}
wan_lora_str_slider_3 = dt.new_widget("slider") {
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

function refresh_wan_lora_combos()
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

fetch_wan_lora_btn = dt.new_widget("button") {
  label = _("Fetch LoRAs"),
  tooltip = _("Fetch Wan LoRAs from the server (filtered by selected model variant)"),
  clicked_callback = function()
    fetch_wan_loras()
    refresh_wan_lora_combos()
  end
}

-- End image file picker for VACE start→end mode
wan_end_image_entry = dt.new_widget("entry") {
  tooltip = _("Path to end image file (leave empty for start-image-only mode)"),
  text = "",
  placeholder = _("(none — start image only)"),
}
wan_end_image_browse_btn = dt.new_widget("button") {
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
wan_vace_strength_slider = dt.new_widget("slider") {
  label = _("VACE Strength"),
  tooltip = _("VACE conditioning strength (1.0 = full guidance, lower = more creative freedom)"),
  soft_min = 0, soft_max = 2,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

-- Crop region sliders for selection mode (pixel coordinates in source image)
wan_crop_x_slider = dt.new_widget("slider") {
  label = _("Crop X"),
  tooltip = _("Left edge of crop region in pixels from the source image"),
  soft_min = 0, soft_max = 4096,
  hard_min = 0, hard_max = 8192,
  step = 8, digits = 0, value = 0,
}
wan_crop_y_slider = dt.new_widget("slider") {
  label = _("Crop Y"),
  tooltip = _("Top edge of crop region in pixels from the source image"),
  soft_min = 0, soft_max = 4096,
  hard_min = 0, hard_max = 8192,
  step = 8, digits = 0, value = 0,
}
wan_crop_w_slider = dt.new_widget("slider") {
  label = _("Crop Width"),
  tooltip = _("Width of crop region in pixels (0 = full width from X)"),
  soft_min = 0, soft_max = 4096,
  hard_min = 0, hard_max = 8192,
  step = 8, digits = 0, value = 0,
}
wan_crop_h_slider = dt.new_widget("slider") {
  label = _("Crop Height"),
  tooltip = _("Height of crop region in pixels (0 = full height from Y)"),
  soft_min = 0, soft_max = 4096,
  hard_min = 0, hard_max = 8192,
  step = 8, digits = 0, value = 0,
}

-- Shared helper: collect all Wan I2V parameters from UI widgets into a table.
-- Used by both the "Whole Image" and "Selection" send buttons to avoid
-- duplicating the parameter-gathering logic.
function collect_wan_i2v_params()
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

  -- Advanced quality / speed patches (tri-state): "auto"/"on"/"off". "auto"
  -- defers to the Guild's server probe — forwarded as overrides so the
  -- canonical build_wan_video sees the exact user intent.
  params.teacache = _tri_combo_to_str(wan_teacache_combo)
  params.sage     = _tri_combo_to_str(wan_sage_combo)
  params.cfg_zero = _tri_combo_to_str(wan_cfg_zero_combo)
  params.slg      = _tri_combo_to_str(wan_slg_combo)
  params.nag      = _tri_combo_to_str(wan_nag_combo)

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

wan_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

wan_send_full_btn = dt.new_widget("button") {
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
                        nil, p.end_image_path, p.vace_strength,
                        {teacache = p.teacache, sage = p.sage, cfg_zero = p.cfg_zero,
                         slg = p.slg, nag = p.nag})  -- no crop
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster Wan I2V error: " .. tostring(err))
        end
      end
    end
  end
}

wan_send_sel_btn = dt.new_widget("button") {
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
                        crop, p.end_image_path, p.vace_strength,
                        {teacache = p.teacache, sage = p.sage, cfg_zero = p.cfg_zero,
                         slg = p.slg, nag = p.nag})
        if not ok then
          dt.print(_("Error: ") .. tostring(err))
          dt.print_error("Spellcaster Wan I2V error: " .. tostring(err))
        end
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- LTX 2.3 I2V GUI widgets (CLAUDE.md §16.3)
-- Routes through the Guild's shot API; the server re-detects the correct
-- preset and applies video_presets.ltx_mode_kwargs canonically.
-- ═══════════════════════════════════════════════════════════════════════

local LTX_MODES = {
  { label = "Distilled (8-step fast)",  preset = "ltx2_distilled" },
  { label = "Full 30-step (quality)",   preset = "ltx2_dev" },
  { label = "Two-stage (upscale)",      preset = "ltx2_text_to_video_2stage" },
  { label = "I2V (image-to-video)",     preset = "ltx2_image_to_video" },
}

-- LTX scene template library (CLAUDE.md §16.3). LTX 2.3 rewards long
-- cinematic prompts — these are pre-tuned 80-150 word descriptions that
-- play to LTX's strengths: camera moves, VFX, weather, lighting,
-- portraits, sci-fi. Pick one to auto-fill the prompt; user can still
-- edit after selection.
-- NSFW_LTX_SCENES_INJECTION_POINT --
local LTX_SCENE_TEMPLATES = {
  { label = "(custom — manual prompt)", prompt = "" },
  { label = "Cinematic Pan — Golden Hour",
    prompt = "A slow cinematic camera pan across a vast rolling landscape at golden hour. Warm amber sunlight rakes across distant hills, volumetric fog drifts through the valley, wildflowers sway in foreground breeze. Shallow depth of field, anamorphic lens flare, 35mm film grain, cinematic colour grading. Steady dolly movement." },
  { label = "Dolly-In — Establishing Shot",
    prompt = "Slow cinematic dolly push-in toward a lone figure at the edge of a cliff. The camera glides forward at a steady pace revealing the vastness of the mountain range behind. Dramatic cloud cover, soft backlighting, atmospheric haze. The figure remains perfectly still as the world moves around them. Cinematic 2.39:1 framing." },
  { label = "Orbital Tracking — Subject",
    prompt = "Smooth orbital camera movement around a central subject, lens holding focus as the background blurs into painterly swirl. Cinematic 360-degree tracking shot, stable gimbal movement, shallow depth of field. The subject remains in sharp detail throughout the rotation, lit by soft key light." },
  { label = "Explosion — Slow-mo Fireball",
    prompt = "A massive fireball explosion erupts in slow motion. Orange and yellow flames billow outward in a mushroom shape, dense black smoke curls at the edges, debris and embers scatter through the air, shockwave visible in surrounding dust. Photorealistic particle physics, high-dynamic-range lighting, 240fps-feel slow motion, cinematic 2.39:1 framing." },
  { label = "Fire Close-up — Dancing Flames",
    prompt = "Extreme macro close-up of dancing flames. Every individual flame tongue writhes and curls against black background, glowing orange and yellow at the core with blue-white highlights at the base. Embers rise and flicker, smoke wisps drift upward. Hyperreal fire physics, deep HDR contrast, cinematic crawl speed." },
  { label = "Lightning Strike — Storm",
    prompt = "Dramatic lightning bolt cracks across a turbulent stormy sky. Multiple branching forks illuminate dark clouds from within, casting brief harsh shadows. Rain streaks diagonally across the frame. The lightning flashes last a fraction of a second each, leaving vivid after-images. Cinematic wide shot, electric white bursts." },
  { label = "Sparks Shower — Metal",
    prompt = "Extreme close-up of sparks flying from a grinding wheel striking metal. Thousands of glowing orange and yellow particles arc through dark space, each leaving a brief bright trail before cooling to ember red. The camera holds still as the shower builds and fades. Hyperreal particle physics, deep black background." },
  { label = "Magic Spell — Energy Burst",
    prompt = "A wizard's hands glow with swirling magical energy, arcane symbols rotating around the palms. Crackling blue-white electric tendrils reach outward, casting shifting highlights across the sorcerer's face. A sudden burst of energy releases forward, lighting up surrounding darkness. Fantasy VFX, high-contrast rim lighting, smoke and ember particles." },
  { label = "Smoke Drift — Volumetric",
    prompt = "Slow cinematic shot of thick volumetric smoke curling through a beam of golden light. The smoke swirls in organic vortices, revealing and concealing shapes within it. Dust motes catch the light and shimmer briefly before drifting into shadow. Deep atmospheric depth, high contrast between illuminated smoke and black background." },
  { label = "Heavy Rain — Window View",
    prompt = "Rain pours against a window pane in cinematic close-up. Each droplet traces a glistening path downward, refracting the warm interior light. Beyond the window, a blurred city at night glows in soft amber and electric blue. The rhythm of the rain is hypnotic, rivulets merging and splitting. Film-noir lighting." },
  { label = "Snow Fall — Quiet Forest",
    prompt = "Gentle snowfall in a silent pine forest. Thousands of fat snowflakes drift lazily downward, catching pale blue winter light. The boughs of evergreens are already laden with powder, deadening all sound. A slight breeze ripples the surface of the snow. Serene, meditative atmosphere, cold colour palette." },
  { label = "Fog Rolling — Valley",
    prompt = "Thick fog rolls slowly through a mountain valley at dawn. The mist curls around jagged rock formations, revealing and swallowing trees in turn. First light of day cuts golden shafts through gaps in the fog. Atmospheric, cinematic, vast scale." },
  { label = "Water Splash — Macro Slow-mo",
    prompt = "Extreme macro slow-motion shot of a single water droplet striking a still surface. The impact sends a perfect crown of splash droplets upward, each catching light like liquid diamonds. Concentric ripples expand outward. Hyperreal fluid physics, cinematic high-speed photography look, dramatic side lighting." },
  { label = "Wave Crash — Coastal",
    prompt = "A massive ocean wave rises, curls, and crashes against jagged coastal rocks in cinematic slow motion. The crest turns translucent turquoise where the sun shines through, spray explodes upward in a white sheet, foam cascades over rocks. Moody overcast sky, cinematic widescreen framing." },
  { label = "Pour Shot — Coffee/Liquid",
    prompt = "Hyperreal close-up of hot coffee being poured into a white ceramic cup. The dark liquid streams in a steady ribbon, catching warm overhead light, steam curling upward in delicate ribbons. Bubbles form and pop on the surface, crema swirls into a fractal pattern. Shallow depth of field, sensory commercial aesthetic." },
  { label = "Golden Hour Portrait",
    prompt = "A close-up portrait during golden hour. Soft amber sunlight rakes across the subject's face from the side, creating warm highlights and deep amber-tinted shadows. The subject's hair catches the light like spun copper. Micro-expressions flicker naturally, subtle blink, slight breath. Cinematic shallow depth of field, creamy bokeh." },
  { label = "Neon Cyberpunk — Rainy Street",
    prompt = "A rain-slicked city street at night, reflecting neon signs in hot pink, electric blue, and acid green. Steam rises from grates in the road, a lone figure in a long coat walks through puddles. Cyberpunk aesthetic, Blade Runner colour palette, volumetric lighting, anamorphic lens flares from every neon source." },
  { label = "Moonlit Forest — Atmospheric",
    prompt = "A deep forest at night under a full moon. Silver-blue moonlight filters through the canopy in ethereal shafts, pooling on the forest floor. A light mist drifts between the trunks. Fireflies blink occasionally in the middle distance. Fantasy atmosphere, muted cool palette with tiny warm highlights, cinematic long take." },
  { label = "Hologram Interface — Sci-fi",
    prompt = "A translucent blue holographic interface materialises in mid air, rotating 3D data visualisations spinning slowly in volumetric light. Grid lines and glowing text scroll across the projected surface, occasional glitch artifacts flicker. A hand enters and interacts with the projection, triggering rippling light cascades. Clean sci-fi aesthetic, electric-blue palette." },
  { label = "Laser Beam — Sci-fi Combat",
    prompt = "A brilliant red laser beam streaks through a dark environment, cutting a line of incandescent light across the frame. Dust and smoke swirl in its wake, the beam leaves a brief afterglow, heat distortion shimmers along its path. Deep black background, saturated red palette, cinematic sci-fi atmosphere." },
  { label = "Energy Aura — Power-up",
    prompt = "A character stands with arms outstretched as a swirling aura of golden and violet energy builds around them. Particles rise from the ground, electric arcs crackle between palms, cloth and hair billow in an aura-induced wind. The power peaks in a brilliant flash. Anime-style VFX, cinematic low-angle shot, rim lighting from the aura itself." },
  { label = "Particle Swarm — Abstract",
    prompt = "Thousands of luminous particles swirl through dark space in fluid organic patterns, forming and dissolving into shapes — spirals, waves, constellations — driven by invisible forces. Each particle trails a short tail of light, the whole swarm behaves like a living fluid. Motion-graphics aesthetic, saturated cyan and magenta." },
  { label = "Cinemagraph — Coffee Steam",
    prompt = "Seamless cinemagraph loop: a steaming cup of coffee sits perfectly still on a wooden table. Only the steam moves, curling upward in endless hypnotic patterns. Warm morning light from the side, shallow depth of field, everything else frozen in time. Cinematic still-life meets subtle motion." },
  { label = "Product Turntable — 360°",
    prompt = "A premium product rotates 360 degrees on a pristine turntable. Clean gradient background, three-point studio lighting with strong key, soft fill, and back light accentuating the product's silhouette. Smooth constant rotation speed, razor-sharp detail throughout. Premium commercial photography aesthetic." },
}

ltx_scene_selector = dt.new_widget("combobox") {
  label = _("LTX Scene Template"),
  tooltip = _("Pick a pre-tuned cinematic prompt template.\n"
           .. "LTX 2.3 rewards long cinematic descriptions — these fill\n"
           .. "the prompt field with 80-150 word scenes tuned to LTX's\n"
           .. "strengths. Edit after selecting for your own twist."),
  selected = 1,
  LTX_SCENE_TEMPLATES[1].label,  -- at least one required at construction
  changed_callback = function(self)
    local idx = self.selected
    if idx < 1 or idx > #LTX_SCENE_TEMPLATES then return end
    local tpl = LTX_SCENE_TEMPLATES[idx]
    if tpl.prompt and tpl.prompt ~= "" then
      ltx_prompt_entry.text = tpl.prompt
    end
  end,
}
-- Populate remaining template labels (same pattern as refresh_scene_selector).
for i = 2, #LTX_SCENE_TEMPLATES do
  ltx_scene_selector[i] = LTX_SCENE_TEMPLATES[i].label
end

ltx_mode_selector = dt.new_widget("combobox") {
  label = _("LTX Mode"),
  tooltip = _("Distilled: 8 steps, fastest (~60s on RTX 5060 Ti).\n"
           .. "Full 30-step: higher quality, slower.\n"
           .. "Two-stage: half-res → latent upscale → refine.\n"
           .. "I2V: start from the selected Darktable image."),
  selected = 1,
  LTX_MODES[1].label, LTX_MODES[2].label,
  LTX_MODES[3].label, LTX_MODES[4].label,
}

ltx_prompt_entry = dt.new_widget("entry") {
  tooltip = _("LTX 2.3 generation prompt. Descriptive, cinematic language works best."),
  text = "",
  placeholder = _("e.g. a cat sitting on a windowsill, soft afternoon light, slight breeze"),
}

ltx_neg_entry = dt.new_widget("entry") {
  tooltip = _("Optional negative prompt. Leave empty to auto-inject the\n"
           .. "subtitle-burn-in blocker (LTX's training corpus includes\n"
           .. "subtitled video — canon negative blocks it)."),
  text = "",
  placeholder = _("(auto: blocks subtitles/watermarks)"),
}

ltx_width_slider = dt.new_widget("slider") {
  label = _("LTX Width"),
  tooltip = _("Output width (multiple of 32). 768 is the canon sweet-spot."),
  soft_min = 256, soft_max = 1280, hard_min = 128, hard_max = 1920,
  step = 32, digits = 0, value = 768,
}

ltx_height_slider = dt.new_widget("slider") {
  label = _("LTX Height"),
  tooltip = _("Output height (multiple of 32). 512 is the canon sweet-spot."),
  soft_min = 256, soft_max = 1280, hard_min = 128, hard_max = 1920,
  step = 32, digits = 0, value = 512,
}

ltx_frames_slider = dt.new_widget("slider") {
  label = _("LTX Frames"),
  tooltip = _("Number of frames. 25 = 1 sec at 25fps. 121 = ~5 sec."),
  soft_min = 9, soft_max = 121, hard_min = 1, hard_max = 257,
  step = 8, digits = 0, value = 25,
}

ltx_fps_slider = dt.new_widget("slider") {
  label = _("LTX FPS"),
  tooltip = _("Output frame rate. LTX 2.3 native is 25fps; 24fps also common."),
  soft_min = 12, soft_max = 30, hard_min = 1, hard_max = 60,
  step = 1, digits = 0, value = 25,
}

ltx_i2v_strength_slider = dt.new_widget("slider") {
  label = _("LTX I2V Strength"),
  tooltip = _("Only used in I2V mode. How strongly the ref image drives the video.\n"
           .. "0.85-0.90 is the sweet spot."),
  soft_min = 0.0, soft_max = 1.0, hard_min = 0.0, hard_max = 1.0,
  step = 0.05, digits = 2, value = 0.90,
}

-- Advanced patches — reuses the _wan_tri_combo helper (tri-state auto/on/off).
local ltx_sage_combo = _wan_tri_combo("LTX SAGE",
  "SageAttention kernel — 50-100% sampler speedup on RTX 40/50xx, neutral\n"
  .. "quality. Requires ComfyUI-KJNodes (PatchSageAttentionKJ).\n"
  .. "Auto: enable if the node is installed.")
local ltx_cfg_zero_combo = _wan_tri_combo("LTX CFG Zero★",
  "CFG Zero Star — CFG=0 on first step, reduces burn-in. Only takes effect\n"
  .. "when cfg > 1 (distilled mode at cfg=1 is auto-skipped).")

ltx_sampler_combo = dt.new_widget("combobox") {
  label = _("LTX Sampler"),
  tooltip = _("Sampler name. Canon 'euler' matches the LTX team reference.\n"
           .. "Distilled mode is tuned for euler; other samplers usually\n"
           .. "regress on distilled runs."),
  selected = 1,
  "euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "heun", "uni_pc",
}

function collect_ltx_params()
  local idx = ltx_mode_selector.selected or 1
  local mode = LTX_MODES[idx] or LTX_MODES[1]
  local sampler_idx = ltx_sampler_combo.selected or 1
  local sampler_names = {"euler", "euler_ancestral", "dpmpp_2m",
                         "dpmpp_2m_sde", "heun", "uni_pc"}
  return {
    preset       = mode.preset,
    prompt       = ltx_prompt_entry.text or "",
    negative     = ltx_neg_entry.text or "",
    width        = math.floor(ltx_width_slider.value),
    height       = math.floor(ltx_height_slider.value),
    length       = math.floor(ltx_frames_slider.value),
    fps          = math.floor(ltx_fps_slider.value),
    i2v_strength = ltx_i2v_strength_slider.value,
    sage         = _tri_combo_to_str(ltx_sage_combo),
    cfg_zero     = _tri_combo_to_str(ltx_cfg_zero_combo),
    sampler_name = sampler_names[sampler_idx] or "euler",
    is_i2v       = (mode.preset == "ltx2_image_to_video"),
  }
end

-- Route an LTX generation through the Guild shot API. Uses the same
-- guild_create_shot / guild_attach_reference helpers as the WAN path
-- (CLAUDE.md §16.4 rule #4: no plugin hand-rolls LTX workflow JSON).
function process_ltx_video(image)
  local guild = get_guild_url()
  if not guild or guild == "" then
    dt.print(_("Wizard Guild URL not configured — preferences → Wizard Guild URL"))
    return
  end
  local p = collect_ltx_params()
  if (p.prompt or "") == "" then
    dt.print(_("LTX: prompt is empty")); return
  end

  local overrides = {}
  overrides.width        = p.width
  overrides.height       = p.height
  overrides.length       = p.length
  overrides.fps          = p.fps
  if p.is_i2v then overrides.i2v_strength = p.i2v_strength end
  if p.sage     and p.sage     ~= "auto" then overrides.enable_sage     = (p.sage == "on") end
  if p.cfg_zero and p.cfg_zero ~= "auto" then overrides.enable_cfg_zero = (p.cfg_zero == "on") end
  if p.sampler_name and p.sampler_name ~= "euler" then
    overrides.sampler_name = p.sampler_name
  end

  local ref_path = nil
  if p.is_i2v and image then
    dt.print(_("LTX I2V: exporting reference..."))
    local tmp, _fn = export_to_temp(image)
    if not tmp then dt.print(_("Export failed")); return end
    ref_path = tmp
  end

  local title = string.format("Darktable LTX: %s",
    (image and image.filename) or "t2v")
  dt.print(_("Creating LTX shot in the Wizard Guild..."))
  local shot_id, err = guild_create_shot(title, p.prompt, p.negative or "",
                                         p.preset, overrides)
  if not shot_id then
    if ref_path then os.remove(ref_path) end
    dt.print(string.format(_("Could not create shot: %s"), tostring(err)))
    return
  end

  if ref_path then
    local ok_ref, ref_err = guild_attach_reference(shot_id, ref_path)
    os.remove(ref_path)
    if not ok_ref then
      dt.print(string.format(_("Reference upload failed: %s"), tostring(ref_err)))
      return
    end
  end

  dt.print(string.format(_("Rendering LTX via canonical pipeline (%s)..."), p.preset))
  local ok_render, render_err = guild_render_shot(shot_id)
  if not ok_render then
    dt.print(string.format(_("Render failed: %s"), tostring(render_err)))
    return
  end

  local ok_wait, wait_err = guild_wait_for_shot_ready(shot_id, 900)
  if not ok_wait then
    dt.print(string.format(_("Wait failed: %s"), tostring(wait_err)))
    return
  end

  local saved_path, dl_err = guild_download_shot_video(shot_id)
  if not saved_path then
    dt.print(string.format(_("Download failed: %s"), tostring(dl_err)))
    return
  end
  dt.print(string.format(_("LTX video saved: %s"), saved_path))
end

ltx_send_t2v_btn = dt.new_widget("button") {
  label = _("LTX: Text-to-Video"),
  tooltip = _("Generate video from the prompt alone (no image ref)."),
  clicked_callback = function()
    local ok, e = pcall(process_ltx_video, nil)
    if not ok then dt.print(_("LTX error: ") .. tostring(e)) end
  end
}

ltx_send_i2v_btn = dt.new_widget("button") {
  label = _("LTX: Image-to-Video"),
  tooltip = _("Generate video starting from the first selected Darktable image.\n"
           .. "Make sure the LTX Mode is set to 'I2V'."),
  clicked_callback = function()
    local imgs = dt.gui.selection()
    if #imgs == 0 then dt.print(_("No images selected")); return end
    local ok, e = pcall(process_ltx_video, imgs[1])
    if not ok then dt.print(_("LTX error: ") .. tostring(e)) end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Klein Flux2 GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

klein_model_selector = dt.new_widget("combobox") {
  label = _("Klein Model"),
  tooltip = _("Select a Klein Flux2 distilled model"),
  selected = 1,
  KLEIN_MODELS[1].label,
  KLEIN_MODELS[2].label,
  KLEIN_MODELS[3].label,
}

klein_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt for Klein Flux2 generation"),
  text = "",
  editable = true,
}

klein_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Sampling steps (distilled model works well with 4)"),
  soft_min = 1, soft_max = 20,
  hard_min = 1, hard_max = 50,
  step = 1, digits = 0, value = 4,
}

klein_guidance_slider = dt.new_widget("slider") {
  label = _("Guidance"),
  tooltip = _("CFG guidance scale (1.0 for Flux 2)"),
  soft_min = 1, soft_max = 10,
  hard_min = 0, hard_max = 30,
  step = 0.5, digits = 1, value = 1.0,
}

klein_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

klein_send_btn = dt.new_widget("button") {
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

pulid_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt for PuLID Flux generation"),
  text = "",
  editable = true,
}

pulid_face_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to face reference image..."),
  tooltip = _("Full path to the face image whose identity will be transferred"),
  editable = true,
}

pulid_strength_slider = dt.new_widget("slider") {
  label = _("Face Strength"),
  tooltip = _("How strongly to apply the face identity (0.0–1.0)"),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 0.9,
}

pulid_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Sampling steps"),
  soft_min = 1, soft_max = 20,
  hard_min = 1, hard_max = 50,
  step = 1, digits = 0, value = 4,
}

pulid_guidance_slider = dt.new_widget("slider") {
  label = _("Guidance"),
  tooltip = _("CFG guidance scale"),
  soft_min = 1, soft_max = 10,
  hard_min = 0, hard_max = 30,
  step = 0.5, digits = 1, value = 3.5,
}

pulid_send_btn = dt.new_widget("button") {
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

fsd_source_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to source face image..."),
  tooltip = _("Full path to the face image to swap onto the target"),
  editable = true,
}

fsd_swap_selector = dt.new_widget("combobox") {
  label = _("Swap Engine"),
  tooltip = _("Face swap model engine"),
  selected = 1,
  "inswapper_128.onnx",
}

fsd_send_btn = dt.new_widget("button") {
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

faceid_preset_selector = dt.new_widget("combobox") {
  label = _("FaceID Preset"),
  tooltip = _("Select a checkpoint preset for FaceID processing"),
  selected = 1,
  FACEID_PRESETS[1].label,
  FACEID_PRESETS[2].label,
  FACEID_PRESETS[3].label,
  FACEID_PRESETS[4].label,
  FACEID_PRESETS[5].label,
}

faceid_face_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to face reference image..."),
  tooltip = _("Full path to the face image whose identity will be applied"),
  editable = true,
}

faceid_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Positive prompt for FaceID generation"),
  text = "",
  editable = true,
}

faceid_neg_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for FaceID generation"),
  text = "blurry, deformed, bad anatomy",
  editable = true,
}

faceid_weight_slider = dt.new_widget("slider") {
  label = _("FaceID Weight"),
  tooltip = _("Weight for face identity preservation"),
  soft_min = 0, soft_max = 1.5,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 0.85,
}

faceid_weight_v2_slider = dt.new_widget("slider") {
  label = _("FaceID V2 Weight"),
  tooltip = _("Weight for FaceID v2 features"),
  soft_min = 0, soft_max = 1.5,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 1.0,
}

faceid_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("Denoise strength (0 = use preset default)"),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 1,
  step = 0.05, digits = 2, value = 0,
}

faceid_send_btn = dt.new_widget("button") {
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

kleinref_model_selector = dt.new_widget("combobox") {
  label = _("Klein Model"),
  tooltip = _("Select a Klein Flux2 model for reference-guided editing"),
  selected = 1,
  KLEIN_MODELS[1].label,
  KLEIN_MODELS[2].label,
  KLEIN_MODELS[3].label,
}

kleinref_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt for Klein+Reference generation"),
  text = "",
  editable = true,
}

kleinref_ref_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to reference/style image..."),
  tooltip = _("Full path to the reference image (style/structure source)"),
  editable = true,
}

kleinref_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Sampling steps"),
  soft_min = 1, soft_max = 20,
  hard_min = 1, hard_max = 50,
  step = 1, digits = 0, value = 4,
}

kleinref_guidance_slider = dt.new_widget("slider") {
  label = _("Guidance"),
  tooltip = _("CFG guidance scale (1.0 for Flux 2)"),
  soft_min = 1, soft_max = 10,
  hard_min = 0, hard_max = 30,
  step = 0.5, digits = 1, value = 1.0,
}

kleinref_send_btn = dt.new_widget("button") {
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

inpaint_model_selector = dt.new_widget("combobox") {
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

inpaint_refinement_selector = dt.new_widget("combobox") {
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

inpaint_mask_entry = dt.new_widget("entry") {
  tooltip = _("Full path to a grayscale mask PNG (white = inpaint area, black = keep)"),
  placeholder = _("/path/to/mask.png"),
}

inpaint_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt describing what to generate in the masked area"),
}

inpaint_negative_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for inpainting"),
  text = "lowres, bad anatomy, worst quality, blurry",
}

inpaint_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("Denoising strength (higher = more change in masked area)"),
  soft_min = 0.1, soft_max = 1.0,
  hard_min = 0.01, hard_max = 1.0,
  step = 0.05, digits = 2,
  value = 0.75,
}

inpaint_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

inpaint_send_btn = dt.new_widget("button") {
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

upscale_model_selector = dt.new_widget("combobox") {
  label = _("Upscale Model"),
  tooltip = _("Select a 4x upscale model"),
  selected = 1,
  UPSCALE_MODELS[1].label,
  UPSCALE_MODELS[2].label,
  UPSCALE_MODELS[3].label,
  UPSCALE_MODELS[4].label,
  UPSCALE_MODELS[5].label,
}

upscale_send_btn = dt.new_widget("button") {
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

lama_mask_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to mask image (white=remove)..."),
  tooltip = _("Full path to a mask image where white areas mark objects to remove (alpha channel used)"),
  editable = true,
}

lama_send_btn = dt.new_widget("button") {
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
-- Klein Inpaint + Klein Re-pose GUI widgets (canonical builder dispatch)
-- ═══════════════════════════════════════════════════════════════════════
-- Both flows talk to the Guild's /api/run_builder so the actual workflow
-- JSON stays in spellcaster_core/workflows.py — bug fixes there reach
-- Darktable for free. KLEIN_MODELS is the local model table (line ~2830)
-- that already drives the existing Klein img2img controls.

klein_model_selector = dt.new_widget("combobox") {
  label = _("Klein Model"),
  tooltip = _("9B = best quality, more VRAM. 4B fp8 = faster, fits 12GB."),
  selected = 1,
  KLEIN_MODELS[1].label,
  KLEIN_MODELS[2].label,
}

-- Klein Inpaint controls
klein_inpaint_mask_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to mask image (white=inpaint area)..."),
  tooltip = _("Full path to a mask PNG — white pixels mark the area Klein will regenerate"),
  editable = true,
}

klein_inpaint_prompt_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("What should appear in the masked area..."),
  tooltip = _("Klein uses natural language — 'a vintage brass lamp' beats 'lamp, vintage, brass'"),
  editable = true,
}

klein_inpaint_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("How strongly the masked area is regenerated. 0.6 = subtle fix, 0.92 = full replace."),
  soft_min = 0.30, soft_max = 1.00,
  hard_min = 0.10, hard_max = 1.00,
  step = 0.02, digits = 2, value = 0.92,
}

-- Shared SAM3 mask prompt entry — feeds Klein Inpaint, LaMa (canonical),
-- and the smart-action buttons. When this is non-empty, the mask file
-- path is ignored: SAM3 builds the mask server-side from the text. UX
-- win: photographers describe what to mask in plain English instead of
-- bouncing to GIMP to draw a PNG.
klein_sam3_prompt_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("...or SAM3 mask prompt: 'the sky', 'her face', 'the trash can'..."),
  tooltip = _("Type what you want masked. SAM3 segments the image server-side. Leave empty to fall back to the mask path above."),
  editable = true,
}

klein_inpaint_send_btn = dt.new_widget("button") {
  label = _("Klein Inpaint"),
  tooltip = _("Regenerate the masked region with Flux 2 Klein. Use SAM3 prompt for hands-free masking, or supply a mask file."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    if #images > 1 then dt.print(_("Klein inpaint processes one image at a time — using first selected")); end
    local sam3 = klein_sam3_prompt_entry.text or ""
    local mask_path = klein_inpaint_mask_entry.text or ""
    if (sam3 == "") and (mask_path == "") then
      dt.print(_("Enter a SAM3 mask prompt OR a mask image path")); return
    end
    if mask_path ~= "" and sam3 == "" then
      local mf = io.open(mask_path, "r")
      if not mf then dt.print(_("Mask image not found: ") .. mask_path); return end
      mf:close()
    end
    local prompt = klein_inpaint_prompt_entry.text or ""
    if prompt == "" then
      dt.print(_("Enter a prompt describing what should appear in the masked area")); return
    end
    local model_idx = klein_model_selector.selected or 1
    local model_label = KLEIN_MODELS[model_idx] and KLEIN_MODELS[model_idx].label or "Klein 9B"
    local denoise = klein_inpaint_denoise_slider.value
    local ok, err = pcall(process_klein_inpaint, images[1], mask_path,
                          model_label, prompt, denoise, sam3)
    if not ok then
      dt.print(_("Error: ") .. tostring(err))
      dt.print_error("Spellcaster Klein inpaint error: " .. tostring(err))
    end
  end
}

-- LaMa Remove with SAM3 — sibling button to the legacy mask-path lama
-- button up above. Reuses the shared klein_sam3_prompt_entry so the
-- user types the target object once and can run either Klein Inpaint
-- (regenerate) or LaMa Remove (deterministic erase) against the same
-- mask description.
lama_sam3_send_btn = dt.new_widget("button") {
  label = _("LaMa Remove (SAM3)"),
  tooltip = _("Erase the SAM3-described region with LaMa. Deterministic, no diffusion — best for small objects."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    if #images > 1 then dt.print(_("LaMa Remove processes one image at a time — using first selected")); end
    local sam3 = klein_sam3_prompt_entry.text or ""
    local mask_path = klein_inpaint_mask_entry.text or ""
    if (sam3 == "") and (mask_path == "") then
      dt.print(_("Enter a SAM3 mask prompt (or a mask image path) first")); return
    end
    local ok, err = pcall(process_lama_canon, images[1], mask_path, sam3)
    if not ok then
      dt.print(_("Error: ") .. tostring(err))
      dt.print_error("Spellcaster LaMa SAM3 error: " .. tostring(err))
    end
  end
}

-- ── Smart Actions ──────────────────────────────────────────────────────
-- One-click, no-mask, no-prompt photo edits. Each chains a fixed SAM3
-- mask prompt + a fixed Klein Inpaint refinement to give photographers
-- workflow buttons rather than tool buttons. Internally identical to a
-- normal Klein Inpaint with the values pre-filled.
function _smart_klein_inpaint(image, sam3_target, refinement_prompt, denoise)
  local model_idx = klein_model_selector.selected or 1
  local model_label = KLEIN_MODELS[model_idx] and KLEIN_MODELS[model_idx].label or "Klein 9B"
  return process_klein_inpaint(image, "", model_label, refinement_prompt,
                                denoise, sam3_target)
end

smart_skin_btn = dt.new_widget("button") {
  label = _("✨ Smooth Skin"),
  tooltip = _("Auto-mask all visible skin via SAM3, then run Klein with the skin-texture refinement."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    for i, img in ipairs(images) do
      dt.print(string.format(_("Smooth Skin %d/%d"), i, #images))
      local ok, err = pcall(_smart_klein_inpaint, img, "skin",
        "detailed skin texture, realistic skin pores, natural skin surface, subsurface scattering, photorealistic skin detail",
        0.45)
      if not ok then dt.print(_("Smooth Skin error: ") .. tostring(err)) end
    end
  end
}

smart_eyes_btn = dt.new_widget("button") {
  label = _("✨ Brighten Eyes"),
  tooltip = _("Auto-mask the eyes via SAM3, then run Klein with the iris-detail refinement."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    for i, img in ipairs(images) do
      dt.print(string.format(_("Brighten Eyes %d/%d"), i, #images))
      local ok, err = pcall(_smart_klein_inpaint, img, "eyes",
        "beautiful detailed eyes, perfect symmetrical eyes, clear sharp iris, realistic eye reflections, natural eye color, detailed eyelashes",
        0.65)
      if not ok then dt.print(_("Brighten Eyes error: ") .. tostring(err)) end
    end
  end
}

-- The sky button takes the prompt entry's contents to drive the new sky
-- (defaulting to a dramatic stormy sky). It's the one smart action that
-- benefits from a knob; the others have a single canonical refinement.
smart_sky_btn = dt.new_widget("button") {
  label = _("✨ Replace Sky"),
  tooltip = _("Auto-mask the sky via SAM3, then run Klein Inpaint with the prompt above (defaults to a dramatic sky)."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local prompt = klein_inpaint_prompt_entry.text or ""
    if prompt == "" then
      prompt = "dramatic stormy sky with golden hour clouds, cinematic lighting, high dynamic range, photorealistic"
      dt.print(_("Replace Sky: using default dramatic-sky prompt (set Inpaint prompt to override)"))
    end
    for i, img in ipairs(images) do
      dt.print(string.format(_("Replace Sky %d/%d"), i, #images))
      local ok, err = pcall(_smart_klein_inpaint, img, "sky", prompt, 0.92)
      if not ok then dt.print(_("Replace Sky error: ") .. tostring(err)) end
    end
  end
}

smart_bg_remove_btn = dt.new_widget("button") {
  label = _("✨ Remove Background"),
  tooltip = _("Auto-mask the main subject via SAM3 (inverted), then erase the background with LaMa."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    -- LaMa with SAM3 prompt "background" — sam3_invert is set in the
    -- builder defaults to false; here we want literal background. SAM3
    -- knows that label well enough to produce a usable mask.
    for i, img in ipairs(images) do
      dt.print(string.format(_("Remove Background %d/%d"), i, #images))
      local ok, err = pcall(process_lama_canon, img, "", "background")
      if not ok then dt.print(_("Remove Background error: ") .. tostring(err)) end
    end
  end
}

-- Klein Re-pose controls
klein_repose_prompt_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Describe the new pose / camera angle / framing..."),
  tooltip = _("Natural language prompt — 'three-quarter portrait turned to the right, looking at camera'"),
  editable = true,
}

klein_repose_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("How far the result drifts from the source. 0.4 = subtle nudge, 0.85 = bold reinterpretation."),
  soft_min = 0.30, soft_max = 0.95,
  hard_min = 0.10, hard_max = 1.00,
  step = 0.02, digits = 2, value = 0.65,
}

klein_repose_send_btn = dt.new_widget("button") {
  label = _("Klein Re-pose"),
  tooltip = _("Change pose / angle / framing while keeping the subject's identity (canonical workflow via the Guild)"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    if #images > 1 then dt.print(_("Klein re-pose processes one image at a time — using first selected")); end
    local prompt = klein_repose_prompt_entry.text or ""
    if prompt == "" then
      dt.print(_("Enter a prompt describing the new pose")); return
    end
    local model_idx = klein_model_selector.selected or 1
    local model_label = KLEIN_MODELS[model_idx] and KLEIN_MODELS[model_idx].label or "Klein 9B"
    local denoise = klein_repose_denoise_slider.value
    local ok, err = pcall(process_klein_repose, images[1], model_label, prompt, denoise)
    if not ok then
      dt.print(_("Error: ") .. tostring(err))
      dt.print_error("Spellcaster Klein re-pose error: " .. tostring(err))
    end
  end
}

-- Klein Head Swap controls
klein_headswap_source_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to source face image..."),
  tooltip = _("PNG/JPG of the face you want to swap INTO the selected target image"),
  editable = true,
}

klein_headswap_prompt_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Optional refinement prompt (e.g. 'natural skin, studio lighting')..."),
  tooltip = _("Klein refinement prompt — leave empty for a neutral blend"),
  editable = true,
}

klein_headswap_denoise_slider = dt.new_widget("slider") {
  label = _("Refine denoise"),
  tooltip = _("Klein refinement strength after ReActor swap. 0.20 = subtle blend, 0.45 = stronger smoothing."),
  soft_min = 0.10, soft_max = 0.60,
  hard_min = 0.05, hard_max = 0.95,
  step = 0.02, digits = 2, value = 0.35,
}

klein_headswap_send_btn = dt.new_widget("button") {
  label = _("Klein Head Swap"),
  tooltip = _("ReActor face swap + Klein refinement (canonical workflow via the Guild)"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    if #images > 1 then dt.print(_("Klein head swap processes one image at a time — using first selected")); end
    local src = klein_headswap_source_entry.text
    if not src or src == "" then dt.print(_("Enter source face image path first")); return end
    local sf = io.open(src, "r")
    if not sf then dt.print(_("Source face image not found: ") .. src); return end
    sf:close()
    local model_idx = klein_model_selector.selected or 1
    local model_label = KLEIN_MODELS[model_idx] and KLEIN_MODELS[model_idx].label or "Klein 9B"
    local prompt = klein_headswap_prompt_entry.text or ""
    local denoise = klein_headswap_denoise_slider.value
    local ok, err = pcall(process_klein_headswap, images[1], src, model_label, prompt, denoise)
    if not ok then
      dt.print(_("Error: ") .. tostring(err))
      dt.print_error("Spellcaster Klein head swap error: " .. tostring(err))
    end
  end
}

-- Klein img2img with reference controls
klein_img2img_ref_path_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to reference image (lighting / mood / style guide)..."),
  tooltip = _("PNG/JPG used as soft style + structure guidance via Klein's ReferenceLatent"),
  editable = true,
}

klein_img2img_ref_prompt_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Edit prompt (what should change in the main image)..."),
  tooltip = _("Klein img2img with reference — natural language prompt"),
  editable = true,
}

klein_img2img_ref_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("How far the result drifts from the input. 0.4 = subtle, 0.8 = bold."),
  soft_min = 0.30, soft_max = 0.95,
  hard_min = 0.10, hard_max = 1.00,
  step = 0.02, digits = 2, value = 0.65,
}

klein_img2img_ref_strength_slider = dt.new_widget("slider") {
  label = _("Reference strength"),
  tooltip = _("How strongly the reference influences the output. 1.0 = strong guide, 0.4 = soft hint."),
  soft_min = 0.20, soft_max = 1.50,
  hard_min = 0.10, hard_max = 2.00,
  step = 0.05, digits = 2, value = 1.0,
}

klein_img2img_ref_send_btn = dt.new_widget("button") {
  label = _("Klein img2img + Ref"),
  tooltip = _("Edit while matching a reference image's lighting/structure (canonical workflow via the Guild)"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    if #images > 1 then dt.print(_("Klein img2img+ref processes one image at a time — using first selected")); end
    local refp = klein_img2img_ref_path_entry.text
    if not refp or refp == "" then dt.print(_("Enter reference image path first")); return end
    local rf = io.open(refp, "r")
    if not rf then dt.print(_("Reference image not found: ") .. refp); return end
    rf:close()
    local prompt = klein_img2img_ref_prompt_entry.text or ""
    if prompt == "" then dt.print(_("Enter a prompt describing the edit")); return end
    local model_idx = klein_model_selector.selected or 1
    local model_label = KLEIN_MODELS[model_idx] and KLEIN_MODELS[model_idx].label or "Klein 9B"
    local denoise = klein_img2img_ref_denoise_slider.value
    local refs = klein_img2img_ref_strength_slider.value
    local ok, err = pcall(process_klein_img2img_ref, images[1], refp, model_label,
                          prompt, denoise, refs)
    if not ok then
      dt.print(_("Error: ") .. tostring(err))
      dt.print_error("Spellcaster Klein img2img+ref error: " .. tostring(err))
    end
  end
}

-- Hybrid Upscale Blend controls
-- Reuses the existing UPSCALE_MODELS table (line ~2033). Two combos
-- for the two models, one slider for the mix.
upscale_blend_model_a_selector = dt.new_widget("combobox") {
  label = _("Upscale model A"),
  tooltip = _("First upscaler — typically the sharper one"),
  selected = 1,
  UPSCALE_MODELS[1].label,
  UPSCALE_MODELS[2].label,
  UPSCALE_MODELS[3].label,
  UPSCALE_MODELS[4].label,
  UPSCALE_MODELS[5].label,
}

upscale_blend_model_b_selector = dt.new_widget("combobox") {
  label = _("Upscale model B"),
  tooltip = _("Second upscaler — typically the smoother one"),
  selected = 4,
  UPSCALE_MODELS[1].label,
  UPSCALE_MODELS[2].label,
  UPSCALE_MODELS[3].label,
  UPSCALE_MODELS[4].label,
  UPSCALE_MODELS[5].label,
}

upscale_blend_factor_slider = dt.new_widget("slider") {
  label = _("Blend (A→B)"),
  tooltip = _("0.0 = pure A, 1.0 = pure B, 0.5 = even mix"),
  soft_min = 0.0, soft_max = 1.0,
  hard_min = 0.0, hard_max = 1.0,
  step = 0.05, digits = 2, value = 0.5,
}

upscale_blend_scale_slider = dt.new_widget("slider") {
  label = _("Scale by"),
  tooltip = _("Final downscale relative to the upscaler's native output. 1.0 keeps the full 4x; 0.5 halves it."),
  soft_min = 0.25, soft_max = 1.0,
  hard_min = 0.10, hard_max = 1.0,
  step = 0.05, digits = 2, value = 1.0,
}

-- 3D Normal Map generation — canonical NormalCrafter path. Mirrors the
-- GIMP plugin's "Enhance > 3D Normal Map" menu entry. Handy inside
-- Darktable for RAW-based relighting workflows where the user wants a
-- normal map to feed into a downstream GIMP IC-Light pass or Klein
-- surgical-edit that uses normal-map ControlNet (CLAUDE.md §25 / the
-- "Normal Map (use existing layer)" CN mode). No dialog — just runs
-- at a sensible default max_res tied to the exported image size.
normal_map_btn = dt.new_widget("button") {
  label = _("💎 3D Normal Map (NormalCrafter)"),
  tooltip = _("Generate a 3D surface normal map for the selected image via the canonical build_normal_map builder. "
              .. "Useful for relighting + ControlNet normal guidance. "
              .. "The 'Max Processing Res' slider above controls NormalCrafter's internal inference resolution."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    -- Reuse the existing 'Max Processing Res' slider so the user has
    -- a single knob for all AI processing in the panel. NormalCrafter
    -- clamps internally; any value works, though 1024 is the sweet
    -- spot (defined as soft_max in the slider, enforced here).
    local nm_res = math.floor(math.min(
      (max_res_slider and max_res_slider.value) or 1024, 1024))
    for i, img in ipairs(images) do
      dt.print(string.format(_("Normal map %d/%d (max_res=%d)"),
                              i, #images, nm_res))
      local ok, err = pcall(process_normal_map, img, nm_res)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster normal map error: " .. tostring(err))
      end
    end
  end
}

upscale_blend_send_btn = dt.new_widget("button") {
  label = _("Hybrid Upscale (Blend)"),
  tooltip = _("Run two upscalers in parallel and blend the outputs (canonical workflow via the Guild)"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local a_idx = upscale_blend_model_a_selector.selected or 1
    local b_idx = upscale_blend_model_b_selector.selected or 4
    local a_file = UPSCALE_MODELS[a_idx] and UPSCALE_MODELS[a_idx].file
    local b_file = UPSCALE_MODELS[b_idx] and UPSCALE_MODELS[b_idx].file
    if not a_file or not b_file then dt.print(_("Invalid upscale model selection")); return end
    local blend = upscale_blend_factor_slider.value
    local scale = upscale_blend_scale_slider.value
    for i, img in ipairs(images) do
      dt.print(string.format(_("Upscale blend %d/%d"), i, #images))
      local ok, err = pcall(process_upscale_blend, img, a_file, b_file, blend, scale)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster upscale blend error: " .. tostring(err))
      end
    end
  end
}

-- ── Z-Image-Turbo (Advanced) controls ──────────────────────────────────
-- All parameters flow through the canonical build_img2img builder via
-- /api/run_builder. The Lua side intentionally stays thin: file upload
-- + parameter packaging. PAG / SkipLayerGuidanceDiT / TeaCache
-- selection happens in spellcaster_core.workflows so any future tuning
-- reaches Darktable for free.
zit_ckpt_entry = dt.new_widget("entry") {
  text = "ZIT\\gonzalomoZpop_v30AIO.safetensors",
  placeholder = _("ZIT checkpoint path on the ComfyUI server..."),
  tooltip = _("Full path of the Z-Image-Turbo checkpoint as ComfyUI sees it. Defaults to the GonzaloMo Zpop AIO."),
  editable = true,
}

zit_prompt_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Edit prompt (Z-Image-Turbo prefers short, plain language)..."),
  tooltip = _("ZIT is distilled — short, focused prompts beat long tag spam. cfg is fixed low (~2.0) by the canonical builder."),
  editable = true,
}

zit_negative_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Negative prompt (optional)..."),
  tooltip = _("Optional negative. Keep it minimal on distilled models."),
  editable = true,
}

zit_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("How far the result drifts from the source. 0.4 = subtle, 0.85 = bold."),
  soft_min = 0.20, soft_max = 0.95,
  hard_min = 0.05, hard_max = 1.00,
  step = 0.02, digits = 2, value = 0.55,
}

zit_quality_selector = dt.new_widget("combobox") {
  label = _("Quality"),
  tooltip = _("balanced = PAG + SLG (recommended). max = also enables FreeU/SLG cap. fast = no boosters (raw 6-step)."),
  selected = 2,
  "fast",
  "balanced",
  "max",
}

zit_fast_check = dt.new_widget("check_button") {
  label = _("⚡ TeaCache (fast_mode)"),
  tooltip = _("Wraps the model in ApplyTeaCachePatch (rel_l1_thresh=0.3 for ZIT). Bigger win on batches than single shots; needs the ComfyUI-TeaCache custom pack."),
  value = false,
}

-- Dedicated ZIT LoRA selector — independent of the global lora_selector
-- so the user can pick a Z-Image-Turbo style/effect LoRA without
-- changing the active img2img preset's arch. cached_zit_loras is
-- populated by refresh_zit_lora_selector(), which runs after the
-- existing Fetch LoRAs button (no separate fetch needed).
local cached_zit_loras = {}

zit_lora_selector = dt.new_widget("combobox") {
  label = _("ZIT LoRA"),
  tooltip = _("Pick a Z-Image-Turbo LoRA from your ComfyUI server. Click 'Fetch LoRAs' above first to populate."),
  selected = 1,
  "(none)",
}

zit_lora_strength_slider = dt.new_widget("slider") {
  label = _("ZIT LoRA strength"),
  tooltip = _("Strength applied to both model and CLIP. 1.0 = full effect, 0.5 = subtle."),
  soft_min = -2, soft_max = 2,
  hard_min = -2, hard_max = 2,
  step = 0.05, digits = 2, value = 0.8,
}

-- Mirror of refresh_lora_selector, but always filters to the zit
-- bucket regardless of the currently-selected img2img model. Hooked
-- into fetch_lora_btn below so pressing "Fetch LoRAs" once populates
-- BOTH the global selector AND this ZIT-specific one.
function refresh_zit_lora_selector()
  cached_zit_loras = filter_loras_for_arch(cached_all_loras, "zit")
  while #zit_lora_selector > 0 do
    zit_lora_selector[#zit_lora_selector] = nil
  end
  zit_lora_selector[1] = "(none)"
  for _, name in ipairs(cached_zit_loras) do
    -- Show short label (last path segment) so the dropdown stays
    -- readable; the full path is recovered from cached_zit_loras
    -- via the same idx-1 trick the global selector uses.
    local short = name:match("\\([^\\]+)$") or name:match("/([^/]+)$") or name
    zit_lora_selector[#zit_lora_selector + 1] = short
  end
  zit_lora_selector.selected = 1
end

zit_send_btn = dt.new_widget("button") {
  label = _("✨ Z-Image-Turbo Generate"),
  tooltip = _("img2img with the full Z-Image-Turbo quality stack (canonical build_img2img via the Guild). Reuses the SAM3 prompt entry above when you want to scope the edit."),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local prompt = zit_prompt_entry.text or ""
    if prompt == "" then
      dt.print(_("Enter a prompt for Z-Image-Turbo")); return
    end
    local negative = zit_negative_entry.text or ""
    local denoise = zit_denoise_slider.value
    local quality_idx = zit_quality_selector.selected or 2
    local quality = ({"fast", "balanced", "max"})[quality_idx] or "balanced"
    local fast_mode = zit_fast_check.value
    local ckpt = zit_ckpt_entry.text or ""
    -- Reuse the shared SAM3 mask prompt entry from the Klein section so
    -- the user types the target once and can switch arches without
    -- re-entering it. Empty string = no scoping (full image).
    local sam3 = klein_sam3_prompt_entry.text or ""
    -- ZIT LoRA pick (item 1 = "(none)")
    local lora_idx = zit_lora_selector.selected or 1
    local lora_name = ""
    if lora_idx > 1 and cached_zit_loras[lora_idx - 1] then
      lora_name = cached_zit_loras[lora_idx - 1]
    end
    local lora_strength = zit_lora_strength_slider.value
    for i, img in ipairs(images) do
      dt.print(string.format(_("Z-Image-Turbo %d/%d"), i, #images))
      local ok, err = pcall(process_zit_img2img, img, prompt, negative,
                             denoise, quality, fast_mode, sam3, ckpt,
                             lora_name, lora_strength)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster Z-Image-Turbo error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Color Grading / LUT GUI widgets
-- ═══════════════════════════════════════════════════════════════════════

lut_selector = dt.new_widget("combobox") {
  label = _("LUT Preset"),
  tooltip = _("Select a cinematic LUT for color grading"),
  selected = 1,
  LUT_PRESETS[1].label,
  LUT_PRESETS[2].label,
  LUT_PRESETS[3].label,
  LUT_PRESETS[4].label,
}

lut_strength_slider = dt.new_widget("slider") {
  label = _("LUT Strength"),
  tooltip = _("Blend strength between original and graded image"),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 1,
  step = 0.05, digits = 2, value = 0.7,
}

lut_send_btn = dt.new_widget("button") {
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

outpaint_pad_left_slider = dt.new_widget("slider") {
  label = _("Pad Left"),
  tooltip = _("Pixels to extend on the left side"),
  soft_min = 0, soft_max = 512,
  hard_min = 0, hard_max = 2048,
  step = 8, digits = 0, value = 0,
}

outpaint_pad_right_slider = dt.new_widget("slider") {
  label = _("Pad Right"),
  tooltip = _("Pixels to extend on the right side"),
  soft_min = 0, soft_max = 512,
  hard_min = 0, hard_max = 2048,
  step = 8, digits = 0, value = 0,
}

outpaint_pad_top_slider = dt.new_widget("slider") {
  label = _("Pad Top"),
  tooltip = _("Pixels to extend on the top side"),
  soft_min = 0, soft_max = 512,
  hard_min = 0, hard_max = 2048,
  step = 8, digits = 0, value = 0,
}

outpaint_pad_bottom_slider = dt.new_widget("slider") {
  label = _("Pad Bottom"),
  tooltip = _("Pixels to extend on the bottom side"),
  soft_min = 0, soft_max = 512,
  hard_min = 0, hard_max = 2048,
  step = 8, digits = 0, value = 0,
}

outpaint_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Describe what to generate in the extended area"),
  text = "",
  editable = true,
}

outpaint_negative_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for outpaint generation"),
  text = "blurry, deformed, low quality",
  editable = true,
}

outpaint_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

outpaint_send_btn = dt.new_widget("button") {
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

style_ref_entry = dt.new_widget("entry") {
  text = "",
  placeholder = _("Path to style reference image..."),
  tooltip = _("Full path to an image whose artistic style will be transferred"),
  editable = true,
}

style_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Optional prompt to guide the style transfer"),
  text = "",
  editable = true,
}

style_strength_slider = dt.new_widget("slider") {
  label = _("Style Strength"),
  tooltip = _("How strongly to apply the reference style"),
  soft_min = 0, soft_max = 1.5,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 0.8,
}

style_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

style_send_btn = dt.new_widget("button") {
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

face_restore_model_selector = dt.new_widget("combobox") {
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

face_restore_visibility_slider = dt.new_widget("slider") {
  label = _("Visibility"),
  tooltip = _("Blend between original and restored face (0=original, 1=fully restored)"),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 1,
  step = 0.05, digits = 2, value = 1.0,
}

face_restore_codeformer_slider = dt.new_widget("slider") {
  label = _("CodeFormer Weight"),
  tooltip = _("CodeFormer fidelity weight (lower=quality, higher=fidelity). Only affects CodeFormer model."),
  soft_min = 0, soft_max = 1,
  hard_min = 0, hard_max = 1,
  step = 0.05, digits = 2, value = 0.5,
}

face_restore_send_btn = dt.new_widget("button") {
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

photo_restore_upscale_selector = dt.new_widget("combobox") {
  label = _("Upscale Model"),
  tooltip = _("Select an upscale model for the restoration pipeline"),
  selected = 1,
  PHOTO_RESTORE_UPSCALE_MODELS[1].label,
  PHOTO_RESTORE_UPSCALE_MODELS[2].label,
  PHOTO_RESTORE_UPSCALE_MODELS[3].label,
  PHOTO_RESTORE_UPSCALE_MODELS[4].label,
}

photo_restore_sharpen_slider = dt.new_widget("slider") {
  label = _("Sharpen Strength"),
  tooltip = _("Sharpening alpha (0=none, 2=maximum)"),
  soft_min = 0, soft_max = 2,
  hard_min = 0, hard_max = 2,
  step = 0.05, digits = 2, value = 0.5,
}

photo_restore_send_btn = dt.new_widget("button") {
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

detail_level_selector = dt.new_widget("combobox") {
  label = _("Detail Level"),
  tooltip = _("How much AI detail to hallucinate (higher = more creative, less faithful)"),
  selected = 1,
  DETAIL_HALLUCINATE_LEVELS[1].label,
  DETAIL_HALLUCINATE_LEVELS[2].label,
  DETAIL_HALLUCINATE_LEVELS[3].label,
  DETAIL_HALLUCINATE_LEVELS[4].label,
}

detail_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt to guide detail hallucination"),
  text = "ultra detailed, sharp focus, high resolution, intricate details",
  editable = true,
}

detail_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

detail_send_btn = dt.new_widget("button") {
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

colorize_strength_slider = dt.new_widget("slider") {
  label = _("ControlNet Strength"),
  tooltip = _("How strongly the lineart structure guides colorization"),
  soft_min = 0.5, soft_max = 1.0,
  hard_min = 0.5, hard_max = 1.0,
  step = 0.05, digits = 2, value = 0.85,
}

colorize_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("Generation strength (higher = more creative color, less faithful to structure)"),
  soft_min = 0.4, soft_max = 0.7,
  hard_min = 0.4, hard_max = 0.7,
  step = 0.05, digits = 2, value = 0.55,
}

colorize_prompt_entry = dt.new_widget("entry") {
  tooltip = _("Prompt to guide colorization"),
  text = "vivid natural colors, photorealistic, color photograph, warm tones, lifelike colors",
  editable = true,
}

colorize_negative_entry = dt.new_widget("entry") {
  tooltip = _("Negative prompt for colorization"),
  text = "black and white, grayscale, monochrome, desaturated, sepia, low quality",
  editable = true,
}

colorize_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

colorize_send_btn = dt.new_widget("button") {
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
batch_count_slider = dt.new_widget("slider") {
  label = _("Batch Count"),
  tooltip = _("Number of variations to generate in one pass (txt2img)"),
  soft_min = 2, soft_max = 8,
  hard_min = 2, hard_max = 8,
  step = 1, digits = 0, value = 4,
}

batch_width_slider = dt.new_widget("slider") {
  label = _("Width"),
  tooltip = _("Output image width (multiple of 8)"),
  soft_min = 512, soft_max = 2048,
  hard_min = 256, hard_max = 4096,
  step = 64, digits = 0, value = 1024,
}

batch_height_slider = dt.new_widget("slider") {
  label = _("Height"),
  tooltip = _("Output image height (multiple of 8)"),
  soft_min = 512, soft_max = 2048,
  hard_min = 256, hard_max = 4096,
  step = 64, digits = 0, value = 1024,
}

batch_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate the full batch. Each run uses fresh seeds."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

batch_send_btn = dt.new_widget("button") {
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

cn_guide_selector = dt.new_widget("combobox") {
  label = _("ControlNet Guide"),
  tooltip = _("Structure-guided generation: extract edges/depth/pose from source image"),
  selected = 1,
  "Off", "Canny (edges)", "Depth (spatial)", "Lineart (drawing)",
  "OpenPose (body)", "Scribble (sketch)", "Tile (detail)",
}

cn_strength_slider = dt.new_widget("slider") {
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
iclight_preset_selector = dt.new_widget("combobox") {
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

iclight_multiplier_slider = dt.new_widget("slider") {
  label = _("Multiplier"),
  tooltip = _("IC-Light conditioning multiplier (lower=subtle, higher=stronger)"),
  soft_min = 0.0, soft_max = 1.0,
  hard_min = 0.0, hard_max = 2.0,
  step = 0.02, digits = 2, value = 0.18,
}

iclight_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

iclight_send_btn = dt.new_widget("button") {
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
supir_denoise_slider = dt.new_widget("slider") {
  label = _("Denoise"),
  tooltip = _("SUPIR denoising strength (lower=preserve detail, higher=more restoration)"),
  soft_min = 0.1, soft_max = 1.0,
  hard_min = 0.1, hard_max = 1.0,
  step = 0.05, digits = 2, value = 0.3,
}

supir_steps_slider = dt.new_widget("slider") {
  label = _("Steps"),
  tooltip = _("Number of sampling steps for SUPIR restoration"),
  soft_min = 10, soft_max = 50,
  hard_min = 5, hard_max = 100,
  step = 1, digits = 0, value = 20,
}

supir_prompt_entry = dt.new_widget("entry") {
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

supir_model_selector = dt.new_widget("combobox") {
  label = _("SDXL Model"),
  tooltip = _("SDXL checkpoint for SUPIR restoration backbone"),
  selected = 1,
}
-- Populate the SDXL model combobox
for i, label in ipairs(supir_sdxl_models) do
  supir_model_selector[i] = label
end

supir_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

supir_send_btn = dt.new_widget("button") {
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

seedv2r_hallucination_combo = dt.new_widget("combobox") {
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

seedv2r_scale_combo = dt.new_widget("combobox") {
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

seedv2r_upscale_model_combo = dt.new_widget("combobox") {
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

seedv2r_ckpt_combo = dt.new_widget("combobox") {
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

seedv2r_runs_slider = dt.new_widget("slider") {
  label = _("Runs"),
  tooltip = _("Number of times to generate. Each run uses a fresh seed."),
  soft_min = 1, soft_max = 20, hard_min = 1, hard_max = 99,
  step = 1, digits = 0, value = 1,
}

seedv2r_send_btn = dt.new_widget("button") {
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
img2img_preset_combo, img2img_preset_load, img2img_preset_save, img2img_preset_delete =
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
        turbo        = turbo_check.value,
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
      if p.turbo ~= nil then turbo_check.value          = p.turbo        end
    end)

-- ── Wan I2V presets ─────────────────────────────────────────────────
wan_preset_combo, wan_preset_load, wan_preset_save, wan_preset_delete =
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
klein_preset_combo, klein_preset_load, klein_preset_save, klein_preset_delete =
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
inpaint_preset_combo, inpaint_preset_load, inpaint_preset_save, inpaint_preset_delete =
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
iclight_preset_combo, iclight_preset_load, iclight_preset_save, iclight_preset_delete =
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
outpaint_preset_combo, outpaint_preset_load, outpaint_preset_save, outpaint_preset_delete =
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
style_preset_combo, style_preset_load, style_preset_save, style_preset_delete =
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
colorize_preset_combo, colorize_preset_load, colorize_preset_save, colorize_preset_delete =
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

-- Server URL entry (editable directly in the panel, syncs with preferences)
server_url_entry = dt.new_widget("entry") {
  tooltip = _("ComfyUI server URL. Change this and press Enter to save.\nAlso configurable in Darktable Preferences > Lua tab."),
  text = dt.preferences.read(MODULE_NAME, "server_url", "string"),
  editable = true,
}

server_save_btn = dt.new_widget("button") {
  label = _("Save Server URL"),
  tooltip = _("Save the server URL to Darktable preferences so it persists across sessions."),
  clicked_callback = function()
    local new_url = server_url_entry.text
    if new_url and new_url ~= "" then
      dt.preferences.write(MODULE_NAME, "server_url", "string", new_url)
      dt.print(string.format(_("Server URL saved: %s"), new_url))
    end
  end,
}

-- R118: Check Capabilities — probe the connected ComfyUI's node
-- catalog and report which architectures are installed. Mirrors the
-- GIMP plugin's _FEATURE_SENTINELS approach: an architecture counts
-- as "available" when ANY of its sentinel nodes is registered.
--
-- Diagnostic-only for now — doesn't filter the MODEL_PRESETS
-- combobox. Editors can see which presets will fail and avoid them,
-- without us doing a heavy dynamic-widget-rebuild pass.
local _ARCH_SENTINELS = {
  ["Flux 2 Klein"]     = {"Flux2KleinRefLatentController",
                           "Flux2KleinTextRefBalance"},
  ["Flux Kontext"]     = {"FluxKontextImageScale",
                           "FluxKontextModelLoader"},
  ["Flux 1 Dev"]       = {"FluxGuidance",
                           "DualCLIPLoader"},
  ["SDXL"]             = {"KSamplerAdvanced"},   -- universal, sanity
  ["SD 1.5"]           = {"KSampler"},           -- universal, sanity
  ["Wan 2.2 Video"]    = {"WanImageToVideo",
                           "LoadWanVideoModel",
                           "WanVaceToVideo"},
  ["LTX-2 Video"]      = {"LTXVImgToVideo",
                           "LTXVScheduler",
                           "LTXAVTextEncoderLoader"},
  ["SUPIR Upscale"]    = {"SUPIR_sample",
                           "SUPIR_first_stage"},
  ["SeedVR2 Video"]    = {"SeedVR2VideoUpscaler"},
  ["IPAdapter / Style"] = {"IPAdapterAdvanced",
                            "IPAdapterUnifiedLoader"},
  ["Face: ReActor"]    = {"ReActorFaceSwap"},
  ["Face: PuLID Flux"] = {"PulidFluxModelLoader",
                           "ApplyPulidFlux"},
  ["Inpaint (LaMa)"]   = {"LamaRemover"},
  ["BG Remove"]        = {"BiRefNetRMBG", "RMBG"},
  ["Chroma"]           = {"ChromaSampler"},
}

-- Module-level cache: fills after first probe or on Refresh click.
local _capabilities_cache = nil   -- { arch_label -> true/false }

function _probe_comfyui_capabilities()
  local server = get_server()
  if not server or server == "" then
    dt.print(_("💎 Capabilities: no server URL configured."))
    return nil
  end
  dt.print(_("💎 Probing ComfyUI capabilities… (24MB download, ~2s)"))
  local resp = curl_get(server .. "/object_info")
  if not resp or resp == "" then
    dt.print(_("💎 Capabilities: ComfyUI unreachable."))
    return nil
  end
  -- Extract top-level class_type names. Top-level keys in /object_info
  -- are the node names (CamelCase identifiers followed by :).
  -- Use a pattern that tolerates the trailing {"input":{… structure.
  local nodes = {}
  for name in resp:gmatch('"([A-Z][%w_%./ +]*)"%s*:%s*{%s*"input"') do
    nodes[name] = true
  end
  -- Compute which archs have at least one sentinel present.
  local caps = {}
  for arch, sentinels in pairs(_ARCH_SENTINELS) do
    caps[arch] = false
    for _, n in ipairs(sentinels) do
      if nodes[n] then
        caps[arch] = true
        break
      end
    end
  end
  _capabilities_cache = caps
  return caps
end

function _check_capabilities()
  local caps = _probe_comfyui_capabilities()
  if not caps then return end
  -- Build a sorted report: available first, missing second.
  local avail, missing = {}, {}
  for arch, ok in pairs(caps) do
    if ok then
      table.insert(avail, arch)
    else
      table.insert(missing, arch)
    end
  end
  table.sort(avail)
  table.sort(missing)
  local lines = {}
  table.insert(lines, _("💎 Spellcaster Capabilities on this ComfyUI:"))
  table.insert(lines, "")
  if #avail > 0 then
    table.insert(lines, _("✓ Installed:"))
    for _, a in ipairs(avail) do
      table.insert(lines, "  • " .. a)
    end
  end
  if #missing > 0 then
    if #avail > 0 then table.insert(lines, "") end
    table.insert(lines, _("✗ Missing (presets using these will fail):"))
    for _, a in ipairs(missing) do
      table.insert(lines, "  • " .. a)
    end
  end
  dt.print(table.concat(lines, "\n"))
end

capabilities_btn = dt.new_widget("button") {
  label = _("💎 Check Capabilities"),
  tooltip = _("Probe the connected ComfyUI's node catalog and report which Spellcaster architectures are installed. Use before picking a preset to avoid silent render failures."),
  clicked_callback = _check_capabilities,
}

-- R113: Check Inbox — pull pending assets other apps have sent to
-- Darktable and drop them into an inbox folder the user can then
-- import via Darktable's native Import panel. Uses GET /api/darktable
-- /inbox?consume=1 (mailbox fanout from event bus routes
-- darktable.asset.* events to darktable's mailbox automatically).
function _inbox_dir()
  -- Prefer OS-standard Pictures dir + Spellcaster-Inbox subfolder.
  -- Fall back to tmp_dir() if HOME isn't set.
  local home = os.getenv("USERPROFILE") or os.getenv("HOME")
  if not home or home == "" then return tmp_dir() end
  local pics = home .. sep .. "Pictures" .. sep .. "Spellcaster-Inbox"
  -- Ensure directory exists. mkdir is fine to run repeatedly.
  if package.config:sub(1,1) == "\\" then
    os.execute(string.format('if not exist "%s" mkdir "%s" 2>NUL',
                              pics, pics))
  else
    os.execute(string.format('mkdir -p "%s" 2>/dev/null', pics))
  end
  return pics
end

-- Worker: drains the Darktable inbox and writes any received assets
-- to the Pictures/Spellcaster-Inbox folder. Returns a table:
--   { status = "ok" | "no_guild" | "unreachable" | "empty",
--     downloaded = int, failed = int,
--     imported = int,       -- files added to dt.database (silent path)
--     dir = <inbox path> }
-- The ``silent`` flag skips dt.print and (crucially) auto-imports the
-- new files into the Darktable library via dt.database.import so the
-- user sees them in lighttable without touching the Import panel.
-- The manual "Check Inbox" button passes silent=false — it prints a
-- one-line summary and leaves auto-import off so users can still
-- review files before adding them.
function _drain_spellcaster_inbox(silent)
  local res = { status = "ok", downloaded = 0, failed = 0, imported = 0, dir = nil }
  local guild = get_guild_url()
  if not guild or guild == "" then
    res.status = "no_guild"
    return res
  end
  local resp_file = _unique_tmp("spellcaster_inbox", ".json")
  local cmd
  if package.config:sub(1,1) == "\\" then
    cmd = string.format(
      'curl -s --max-time 10 "%s/api/darktable/inbox?consume=1&max=20" -o "%s" 2>NUL',
      shell_esc(guild), shell_esc(resp_file))
  else
    cmd = string.format(
      'curl -s --max-time 10 "%s/api/darktable/inbox?consume=1&max=20" -o "%s" 2>/dev/null',
      shell_esc(guild), shell_esc(resp_file))
  end
  os.execute(cmd)
  local f = io.open(resp_file, "r")
  if not f then
    res.status = "unreachable"
    return res
  end
  local body = f:read("*all"); f:close(); os.remove(resp_file)
  if not body or body == "" then
    res.status = "unreachable"
    return res
  end
  local urls = {}
  for url in body:gmatch('"image_url"%s*:%s*"([^"]+)"') do
    table.insert(urls, url)
  end
  if #urls == 0 then
    res.status = "empty"
    return res
  end
  local dir = _inbox_dir()
  res.dir = dir
  for i, url in ipairs(urls) do
    if url:sub(1, 1) == "/" then
      url = guild:gsub("/+$", "") .. url
    end
    local hash = url:match("/api/assets/([^/?#]+)") or tostring(i)
    local out = dir .. sep .. "sc_" .. os.time() .. "_" .. hash:sub(1, 8) .. ".png"
    local dcmd
    if package.config:sub(1,1) == "\\" then
      dcmd = string.format('curl -s --max-time 30 -o "%s" "%s" 2>NUL',
                            shell_esc(out), shell_esc(url))
    else
      dcmd = string.format('curl -s --max-time 30 -o "%s" "%s" 2>/dev/null',
                            shell_esc(out), shell_esc(url))
    end
    os.execute(dcmd)
    local check = io.open(out, "rb")
    if check then
      local chunk = check:read(16); check:close()
      if chunk and #chunk > 0 then
        res.downloaded = res.downloaded + 1
        -- Silent path auto-imports so users discover the asset in
        -- lighttable without an extra click. Manual path leaves the
        -- file unimported so users can review first.
        if silent then
          local ok = pcall(function()
            local img = dt.database.import(out)
            if img then res.imported = res.imported + 1 end
          end)
          if not ok then
            -- Import failed — leave the file on disk; user can
            -- still pick it up via the Import panel.
          end
        end
      else
        os.remove(out)
        res.failed = res.failed + 1
      end
    else
      res.failed = res.failed + 1
    end
  end
  return res
end

function _check_spellcaster_inbox()
  local res = _drain_spellcaster_inbox(false)
  if res.status == "no_guild" then
    dt.print(_("💎 Inbox: no Guild URL configured — set Server in Spellcaster panel."))
    return
  end
  if res.status == "unreachable" then
    dt.print(_("💎 Inbox: couldn't reach the Guild."))
    return
  end
  if res.status == "empty" then
    dt.print(_("💎 Inbox: nothing waiting."))
    return
  end
  dt.print(string.format(
    _("💎 Inbox: %d image(s) saved to %s. Open Darktable's Import panel to add them to the library."),
    res.downloaded, res.dir or _inbox_dir()))
end

inbox_btn = dt.new_widget("button") {
  label = _("💎 Check Spellcaster Inbox"),
  tooltip = _("Pull any assets other Spellcaster apps have sent to Darktable. Downloads go to Pictures/Spellcaster-Inbox; import via Darktable's native Import panel."),
  clicked_callback = _check_spellcaster_inbox,
}

-- R110: cross-plugin send buttons. Use the ACTIVE lighttable image
-- (dt.gui.selection()[1] or act_image) as the source, export via
-- the existing export_to_temp() helper, then upload + publish via
-- _asset_upload_and_emit. Diamond (\xf0\x9f\x92\x8e = 💎) prefix
-- matches the Resolve-plugin convention from R104 so the "AI-related
-- branch" jumps out of Darktable's lighttable module list.
-- Tri-state presence check. Returns "yes" if we confirmed the peer
-- is live, "no" if a presence query succeeded but didn't list the
-- target, "unknown" if we couldn't reach any presence surface. UI
-- code treats "unknown" the same as "yes" — don't pre-emptively block
-- when we can't tell.
function _peer_online_tristate(target_key)
  local queried = false
  local peers = comfy_presence_list()
  if type(peers) == "table" then
    if #peers > 0 then queried = true end
    for _, p in ipairs(peers) do
      if p and p.key == target_key then return "yes" end
    end
  end
  -- No Guild-side fallback yet in the Lua plugin (guild_active_peers
  -- doesn't exist here — only the ComfyUI broker is queried). If that
  -- query failed we can't be sure, so we return "unknown" and let the
  -- send proceed; errors from _asset_upload_and_emit still surface to
  -- the user.
  if queried then return "no" end
  return "unknown"
end

function _cross_send_active_image(target, friendly)
  local sel = dt.gui.selection() or {}
  local image = sel[1] or dt.gui.act_image
  if not image then
    dt.print(_("💎 Select an image first, then click Send to ") ..
             friendly)
    return
  end
  local presence = _peer_online_tristate(target)
  if presence == "no" then
    dt.print(string.format(
      _("💎 %s isn't running right now. Start it and click Send again."),
      friendly))
    return
  end
  dt.print(_("💎 Exporting image for ") .. friendly .. _(" …"))
  local path, fname = export_to_temp(image)
  if not path then
    dt.print(_("💎 Couldn't export the selected image."))
    return
  end
  local ok, info = _asset_upload_and_emit(target, path, friendly)
  os.remove(path)
  if ok then
    dt.print(string.format(
      _("💎 Sent to %s (asset %s…) — open %s and pick it up."),
      friendly, tostring(info):sub(1, 10), friendly))
  else
    dt.print(string.format(
      _("💎 Send to %s failed: %s"), friendly, tostring(info or "?")))
  end
end

send_to_resolve_btn = dt.new_widget("button") {
  label = _("💎 Send to DaVinci Resolve"),
  tooltip = _("Publish the selected image to Resolve's Media Pool via the Spellcaster Bridge"),
  clicked_callback = function()
    _cross_send_active_image("resolve", "DaVinci Resolve")
  end,
}
send_to_gimp_btn = dt.new_widget("button") {
  label = _("💎 Send to GIMP"),
  tooltip = _("Publish the selected image to GIMP's inbox (GIMP: Spellcaster > Cross-App > Check Inbox)"),
  clicked_callback = function()
    _cross_send_active_image("gimp", "GIMP")
  end,
}
send_to_sillytavern_btn = dt.new_widget("button") {
  label = _("💎 Send to SillyTavern"),
  tooltip = _("Publish the selected image to SillyTavern as a character / scene asset"),
  clicked_callback = function()
    _cross_send_active_image("sillytavern", "SillyTavern")
  end,
}

module_widget = dt.new_widget("box") {
  orientation = "vertical",
  dt.new_widget("label") { label = _("\xe2\x9c\xa8 Spellcaster \xe2\x80\x94 AI Superpowers") },
  dt.new_widget("label") { label = _("Server:") },
  server_url_entry,
  server_save_btn,
  status_label,
  test_btn,
  -- SpeedCoach read-side strip: fastest arch on this box + last-run
  -- outcome + explicit refresh button. Polls the Guild's
  -- /api/speedcoach/* endpoints; degrades silently when Guild is down.
  speedcoach_strip,
  speedcoach_footer,
  speedcoach_refresh_btn,
  dt.new_widget("separator") {},

  -- R110 + R113 + R118: cross-plugin transfer + capability probe.
  dt.new_widget("label") { label = _("💎 CROSS-APP TRANSFER") },
  send_to_resolve_btn,
  send_to_gimp_btn,
  send_to_sillytavern_btn,
  inbox_btn,
  capabilities_btn,
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
  turbo_check,
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
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 ADVANCED QUALITY / SPEED PATCHES") },
  wan_teacache_combo,
  wan_sage_combo,
  wan_cfg_zero_combo,
  wan_slg_combo,
  wan_nag_combo,
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

  -- LTX 2.3 Video section (CLAUDE.md §16.3)
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 LTX 2.3 VIDEO") },
  ltx_scene_selector,
  ltx_mode_selector,
  dt.new_widget("label") { label = _("Prompt:") },
  ltx_prompt_entry,
  dt.new_widget("label") { label = _("Negative (empty = auto):") },
  ltx_neg_entry,
  ltx_width_slider,
  ltx_height_slider,
  ltx_frames_slider,
  ltx_fps_slider,
  ltx_i2v_strength_slider,
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 LTX ADVANCED") },
  ltx_sampler_combo,
  ltx_sage_combo,
  ltx_cfg_zero_combo,
  ltx_send_t2v_btn,
  ltx_send_i2v_btn,
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
      local tmp_out = _unique_tmp("steg_read", ".txt")
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

  -- Klein Inpaint + Re-pose (canonical builders, dispatched via the Guild)
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 KLEIN SURGICAL EDITS") },
  klein_model_selector,
  dt.new_widget("label") { label = _("Inpaint mask path (white=replace):") },
  klein_inpaint_mask_entry,
  klein_sam3_prompt_entry,
  dt.new_widget("label") { label = _("Inpaint prompt:") },
  klein_inpaint_prompt_entry,
  klein_inpaint_denoise_slider,
  klein_inpaint_send_btn,
  lama_sam3_send_btn,
  dt.new_widget("label") { label = _("\xe2\x9c\xa8 SMART ACTIONS (SAM3-driven, no mask file needed):") },
  smart_skin_btn,
  smart_eyes_btn,
  smart_sky_btn,
  smart_bg_remove_btn,
  dt.new_widget("label") { label = _("Re-pose prompt:") },
  klein_repose_prompt_entry,
  klein_repose_denoise_slider,
  klein_repose_send_btn,
  dt.new_widget("label") { label = _("Head swap source face path:") },
  klein_headswap_source_entry,
  dt.new_widget("label") { label = _("Head swap refine prompt:") },
  klein_headswap_prompt_entry,
  klein_headswap_denoise_slider,
  klein_headswap_send_btn,
  dt.new_widget("label") { label = _("img2img reference image path:") },
  klein_img2img_ref_path_entry,
  dt.new_widget("label") { label = _("img2img+ref prompt:") },
  klein_img2img_ref_prompt_entry,
  klein_img2img_ref_denoise_slider,
  klein_img2img_ref_strength_slider,
  klein_img2img_ref_send_btn,
  dt.new_widget("separator") {},

  -- Hybrid Upscale Blend (canonical builder via the Guild)
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 HYBRID UPSCALE BLEND") },
  upscale_blend_model_a_selector,
  upscale_blend_model_b_selector,
  upscale_blend_factor_slider,
  upscale_blend_scale_slider,
  upscale_blend_send_btn,
  dt.new_widget("separator") {},

  -- 3D Normal Map (NormalCrafter) — standalone generation via the
  -- canonical builder. Pairs with GIMP's IC-Light + Normal-Map CN
  -- modes for cross-app relighting workflows.
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 3D / RELIGHTING") },
  normal_map_btn,
  dt.new_widget("separator") {},

  -- Z-Image-Turbo (advanced) — full PAG + SLG + optional TeaCache stack
  -- via the canonical build_img2img builder.
  dt.new_widget("label") { label = _("\xe2\x9c\xa6 Z-IMAGE-TURBO (ADVANCED)") },
  dt.new_widget("label") { label = _("Checkpoint:") },
  zit_ckpt_entry,
  dt.new_widget("label") { label = _("Prompt:") },
  zit_prompt_entry,
  dt.new_widget("label") { label = _("Negative:") },
  zit_negative_entry,
  zit_denoise_slider,
  zit_quality_selector,
  zit_fast_check,
  zit_lora_selector,
  zit_lora_strength_slider,
  zit_send_btn,
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

-- ═══════════════════════════════════════════════════════════════════════
-- DARKTABLE MODULE REGISTRATION & LIFECYCLE
-- ═══════════════════════════════════════════════════════════════════════
-- Darktable's plugin lifecycle: scripts are loaded on startup and must
-- register UI modules. The plugin must respond to script_manager events
-- (destroy/restart) to appear/disappear when toggled in the preferences.
--
-- KEY CONCEPTS:
-- 1. module_widget is a vertical box (dt.new_widget("box")) containing all UI controls
-- 2. dt.register_lib() attaches the module to a lighttable panel (right-center, pos 99)
-- 3. Widgets are created at file load time, but only attached to the UI when needed
-- 4. The module starts invisible if the plugin isn't enabled in preferences
--
-- REGISTRATION LOGIC:
--   - If already in lighttable view: register immediately
--   - Otherwise: wait for view-changed event before registering
--   This prevents errors from registering modules in non-target views.
--
-- LIFECYCLE CALLBACKS:
--   - destroy() : called when user disables plugin in preferences
--     Sets visible = false (keeps module in memory, avoids re-creating widgets)
--   - restart() : called when user re-enables plugin
--     Sets visible = true (restores visibility instantly)
--   - destroy_method = "hide" : tells script_manager to use hide/show, not delete/recreate
--
-- THREAD-SAFETY:
--   module_installed flag prevents double-registration if somehow called twice

local module_installed = false

-- Register the Spellcaster module with Darktable.
-- Adds a new panel in the lighttable view (right side, position 99) containing
-- all workflow controls. The panel is expandable and resetable (collapse/restore).
--
-- @see module_widget for the UI container (created above)
function install_module()
  if not module_installed then
    dt.register_lib(
      MODULE_NAME,                                          -- internal key ("comfyui_connector")
      _("Spellcaster"),                                     -- display name (translated)
      true,                                                 -- expandable (user can collapse)
      true,                                                 -- resetable (user can restore defaults)
      {[dt.gui.views.lighttable] = {"DT_UI_CONTAINER_PANEL_RIGHT_CENTER", 99}},  -- position: right panel, priority 99
      module_widget,                                        -- the actual UI widget (box of controls)
      nil,                                                  -- view_enter callback (unused)
      nil                                                   -- view_leave callback (unused)
    )
    module_installed = true
  end
end

-- Hide the module (called when user disables via preferences).
-- Uses "hide" strategy (keep in memory) rather than delete, so re-enabling is instant.
function destroy()
  dt.gui.libs[MODULE_NAME].visible = false
end

-- Show the module (called when user re-enables via preferences).
-- Instant because widgets are still in memory.
function restart()
  dt.gui.libs[MODULE_NAME].visible = true
end

-- ───────────────────────────────────────────────────────────────────────
-- DEFERRED REGISTRATION: Darktable only allows UI registration in the
-- target view. If we're not in lighttable yet, wait for the user to
-- switch to lighttable before registering the module.
-- ───────────────────────────────────────────────────────────────────────
if dt.gui.current_view().id == "lighttable" then
  -- Already in lighttable: register immediately
  install_module()
else
  -- Not in lighttable yet: register when view changes to lighttable
  dt.register_event(
    MODULE_NAME, "view-changed",
    function(event, old_view, new_view)
      -- Only install when transitioning FROM darkroom TO lighttable
      -- (avoids re-registering if lighttable → darkroom → lighttable)
      if new_view.name == "lighttable" and old_view.name == "darkroom" then
        install_module()
      end
    end
  )
end

-- ───────────────────────────────────────────────────────────────────────
-- SCRIPT_MANAGER LIFECYCLE CALLBACKS
-- ───────────────────────────────────────────────────────────────────────
-- These callbacks allow script_manager (Darktable's plugin manager) to
-- control the Spellcaster module visibility without destroying/recreating widgets.
--
-- When user enables/disables the plugin in Preferences → Lua → Spellcaster:
--   - script_manager calls destroy() → module becomes invisible
--   - script_manager calls restart() → module becomes visible again
--
-- The "hide" destroy_method is efficient: all widgets remain in memory,
-- so toggling is instant (no widget reconstruction overhead).
script_data.destroy = destroy
script_data.restart = restart
script_data.destroy_method = "hide"    -- Use hide/show strategy, not delete/recreate
script_data.show = restart              -- Alias for restart() when re-enabling

dt.print(_("Spellcaster loaded - img2img, inpaint, face swap, Wan I2V, Klein Flux2, PuLID Flux, FaceID, Klein+Ref, batch, ControlNet, IC-Light, SUPIR"))

-- ═══════════════════════════════════════════════════════════════════════
-- Background inbox auto-drain
-- ═══════════════════════════════════════════════════════════════════════
-- Darktable runs a persistent Lua main loop, so we can keep a
-- long-lived dispatched coroutine that silently drains the
-- cross-interface inbox on an interval. Every tick calls
-- _drain_spellcaster_inbox(true) — the silent path that also
-- dt.database.import()s any newly downloaded assets so users discover
-- peer-sent files in lighttable without clicking anything.
--
-- Guarded by a global module flag so script_manager reloads don't
-- stack multiple pollers, and gated on the user pref
-- ``inbox_auto_interval_s`` (0 = disabled).
if not _G._SPELLCASTER_INBOX_POLL_STARTED then
  _G._SPELLCASTER_INBOX_POLL_STARTED = true
  dt.control.dispatch(function()
    while true do
      local ok_iv, iv = pcall(dt.preferences.read,
                               MODULE_NAME, "inbox_auto_interval_s", "integer")
      if not ok_iv or type(iv) ~= "number" then iv = 30 end
      if iv <= 0 then
        -- Disabled — sleep a minute and re-check the pref so users
        -- enabling it in the preferences dialog see it take effect
        -- without a full Darktable restart.
        dt.control.sleep(60 * 1000)
      else
        -- Fire-and-forget drain. pcall insulates the loop from any
        -- networking/filesystem error so the poller never dies.
        pcall(_drain_spellcaster_inbox, true)
        dt.control.sleep(iv * 1000)
      end
    end
  end)
end

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
function spellcaster_auto_update()
  local sep = package.config:sub(1,1)           -- '\' on Windows, '/' on Unix
  local mv  = (sep == "\\") and "move /y" or "mv -f"  -- platform-appropriate rename
  local plugin_dir = debug.getinfo(1, "S").source:sub(2):match("(.*[/\\])") or ("." .. sep)
  local version_file = plugin_dir .. ".spellcaster_version"
  local api_url  = "https://api.github.com/repos/laboratoiresonore/spellcaster/commits?sha=main&per_page=1"
  local tree_url = "https://api.github.com/repos/laboratoiresonore/spellcaster/git/trees/main?recursive=1"
  local raw_base = "https://raw.githubusercontent.com/laboratoiresonore/spellcaster/main"
  local dt_prefix = "plugins/darktable/"

  -- Protected files: user config and version tracker -- never overwrite
  local protected_files = {
    [".spellcaster_version"] = true,
    ["config.json"] = true,
    ["user_presets.json"] = true,
    ["session_state.json"] = true,
  }
  local protected_suffixes = { ".pyc", ".update", ".tmp", ".onnx", ".safetensors" }

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
  local update_files = {}
  local remote_filenames = {}  -- track for stale-file cleanup
  local tree_tmp = os.tmpname()
  local tree_ok = os.execute(string.format(
    'curl -s -A "spellcaster-dt/2.0" --max-time 15 -o "%s" "%s"', shell_esc(tree_tmp), shell_esc(tree_url)))
  if tree_ok == 0 or tree_ok == true then
    local ft = io.open(tree_tmp, "r")
    if ft then
      local tree_body = ft:read("*a"); ft:close()
      -- Extract file paths and sizes from the JSON tree
      -- Each blob entry: {"path":"...","type":"blob","size":NNN,...}
      for blob_entry in tree_body:gmatch('{[^{}]-"type"%s*:%s*"blob"[^{}]-}') do
        local path = blob_entry:match('"path"%s*:%s*"([^"]-)"')
        local size = tonumber(blob_entry:match('"size"%s*:%s*(%d+)')) or 0
        if path and path:sub(1, #dt_prefix) == dt_prefix then
          local filename = path:sub(#dt_prefix + 1)
          -- Only top-level files (no subdirectories)
          if not filename:find("/") and filename ~= "" and not protected_files[filename] then
            table.insert(update_files, { src = path, dst = filename, expected_size = size })
            remote_filenames[filename] = true
          end
        end
      end
    end
  end
  os.remove(tree_tmp)

  -- Fallback to static list if tree API returned nothing.
  -- THIS LIST MUST INCLUDE EVERY TOP-LEVEL FILE in plugins/darktable/
  -- (check via `ls plugins/darktable/`). When an asset file exists
  -- in the repo but is missing here, it won't refresh on the rare
  -- days the GitHub Tree API is unreachable — which is exactly the
  -- silent-asset-update bug flagged in the 2026-04 updater audit.
  if #update_files == 0 then
    update_files = {
      -- Core code
      { src = "plugins/darktable/comfyui_connector.lua",     dst = "comfyui_connector.lua", expected_size = 0 },
      { src = "plugins/darktable/splash.py",                 dst = "splash.py", expected_size = 0 },
      { src = "plugins/darktable/spellcaster_steg.py",       dst = "spellcaster_steg.py", expected_size = 0 },
      -- Theme + branding assets (MUST be included — the pre-fix
      -- fallback skipped these, which meant users with stale icons
      -- never saw an update whenever the GitHub Tree API hiccuped).
      { src = "plugins/darktable/spellcaster-darktable.css", dst = "spellcaster-darktable.css", expected_size = 0 },
      { src = "plugins/darktable/spellcaster_icon.png",      dst = "spellcaster_icon.png", expected_size = 0 },
      { src = "plugins/darktable/spellcaster_header.png",    dst = "spellcaster_header.png", expected_size = 0 },
      { src = "plugins/darktable/installer_background.png",  dst = "installer_background.png", expected_size = 0 },
      { src = "plugins/darktable/darktable_splash.jpg",      dst = "darktable_splash.jpg", expected_size = 0 },
    }
    for _, f in ipairs(update_files) do remote_filenames[f.dst] = true end
  end

  -- Text file extensions for null-byte scrubbing
  local text_exts = { lua=true, py=true, js=true, jsx=true, css=true, json=true, md=true, txt=true, html=true }

  -- Download updated files: write to .tmp first, then rename for atomic replacement
  local updated = 0
  local failed = 0
  for _, f in ipairs(update_files) do
    local url = raw_base .. "/" .. f.src
    local dest = plugin_dir .. f.dst
    local tmp  = dest .. ".tmp"
    local dl = os.execute(string.format(
      'curl -s -A "spellcaster-dt/2.0" --max-time 30 -o "%s" "%s"', shell_esc(tmp), shell_esc(url)))
    if dl == 0 or dl == true then
      -- Integrity check: verify download size matches expected
      local fh = io.open(tmp, "rb")
      local ok_size = true
      if fh then
        local content = fh:read("*a"); fh:close()
        if f.expected_size > 0 and #content ~= f.expected_size then
          ok_size = false
          os.remove(tmp)
          failed = failed + 1
        else
          -- Scrub null bytes from text files (NTFS corruption guard)
          local ext = f.dst:match("%.(%w+)$")
          if ext and text_exts[ext] and content:find("%z") then
            content = content:gsub("%z", "")
            local fw = io.open(tmp, "wb")
            if fw then fw:write(content); fw:close() end
          end
        end
      end
      if ok_size then
        os.execute(string.format('%s "%s" "%s"', mv, shell_esc(tmp), shell_esc(dest)))
        updated = updated + 1
      end
    else
      os.remove(tmp)  -- clean up failed download
      failed = failed + 1
    end
  end

  -- Remove local files that no longer exist in the repo
  local ls_tmp = os.tmpname()
  local ls_cmd = (sep == "\\")
    and string.format('dir /b "%s" > "%s" 2>nul', shell_esc(plugin_dir), shell_esc(ls_tmp))
    or  string.format('ls -1 "%s" > "%s" 2>/dev/null', shell_esc(plugin_dir), shell_esc(ls_tmp))
  os.execute(ls_cmd)
  local ls_fh = io.open(ls_tmp, "r")
  if ls_fh then
    for line in ls_fh:lines() do
      local fn = line:match("^%s*(.-)%s*$")  -- trim whitespace
      if fn and fn ~= "" and not protected_files[fn] then
        local dominated = false
        for _, suf in ipairs(protected_suffixes) do
          if fn:sub(-#suf) == suf then dominated = true; break end
        end
        if not dominated and not remote_filenames[fn] then
          os.remove(plugin_dir .. fn)
        end
      end
    end
    ls_fh:close()
  end
  os.remove(ls_tmp)

  -- Record the new SHA so the next startup skips the download
  if updated > 0 then
    local fv2 = io.open(version_file, "w")
    if fv2 then fv2:write(latest_sha); fv2:close() end
    local msg = string.format(_("Spellcaster updated to %s (%d files)."),
                latest_sha:sub(1, 7), updated)
    if failed > 0 then
      msg = msg .. string.format(" %d file(s) failed.", failed)
    end
    msg = msg .. " " .. _("Please restart Darktable.")
    dt.print(msg)
  end
end

-- Run update check wrapped in pcall: network/file errors must never
-- prevent the plugin from loading and functioning normally.
pcall(spellcaster_auto_update)

-- ═══════════════════════════════════════════════════════════════════════
--  Spellcaster Theme Auto-Install
-- ═══════════════════════════════════════════════════════════════════════
-- Copies spellcaster-darktable.css to the Darktable themes directory
-- so the user can select it from Preferences > General > Theme.
-- Non-destructive: only copies if the file is newer or missing.
function install_spellcaster_theme()
  local plugin_dir = dt.configuration.config_dir .. "/lua/"
  -- Find the CSS file next to this Lua script
  local css_candidates = {
    plugin_dir .. "spellcaster-darktable.css",
    plugin_dir .. "contrib/spellcaster-darktable.css",
  }
  -- Also check the script's own directory
  local script_dir = debug.getinfo(1, "S").source:match("@?(.*[/\\])")
  if script_dir then
    table.insert(css_candidates, 1, script_dir .. "spellcaster-darktable.css")
  end

  local css_source = nil
  for _, path in ipairs(css_candidates) do
    local f = io.open(path, "r")
    if f then
      f:close()
      css_source = path
      break
    end
  end
  if not css_source then return end

  -- Determine themes directory
  local themes_dir = dt.configuration.config_dir .. "/themes"
  local dest = themes_dir .. "/spellcaster-darktable.css"

  -- Create themes directory if needed
  local mkdir_cmd
  if dt.configuration.running_os == "windows" then
    mkdir_cmd = 'mkdir "' .. themes_dir:gsub("/", "\\") .. '" 2>NUL'
  else
    mkdir_cmd = 'mkdir -p "' .. themes_dir .. '" 2>/dev/null'
  end
  os.execute(mkdir_cmd)

  -- Check if update needed (compare sizes as a simple freshness check)
  local src_f = io.open(css_source, "rb")
  if not src_f then return end
  local src_data = src_f:read("*a")
  src_f:close()

  local dst_f = io.open(dest, "rb")
  if dst_f then
    local dst_data = dst_f:read("*a")
    dst_f:close()
    if dst_data == src_data then
      return  -- already up to date
    end
  end

  -- Copy the theme CSS
  local out = io.open(dest, "wb")
  if out then
    out:write(src_data)
    out:close()
    dt.print(_("Spellcaster theme installed. Select it in Preferences > General > Theme."))
  end
end

-- Only install theme if user opted in via config. Default is UNBRANDED.
local _cfg_path = dt.configuration.config_dir .. "/lua/spellcaster_config.json"
local _apply_theme = false
do
  local f = io.open(_cfg_path, "r")
  if f then
    local txt = f:read("*a"); f:close()
    if txt:find('"apply_theme"%s*:%s*true') then _apply_theme = true end
  end
end
if _apply_theme then pcall(install_spellcaster_theme) end

-- Tell the Wizard Guild we're alive. Non-blocking (fires a curl and
-- moves on). If the Guild isn't running, the heartbeat silently fails
-- and Darktable stays out of the Guild's active-interface list — no
-- "dead function" chips appear in the Guild UI.
pcall(guild_heartbeat, { active_view = "lighttable" })

-- Also register with ComfyUI-Spellcaster's presence broker. Zero-
-- config cross-app discovery: GIMP / SillyTavern / Resolve see
-- Darktable listed WITHOUT needing the Guild running. Register once
-- + heartbeat on the same cadence Darktable uses for Guild
-- (opportunistic — Lua has no timer; each user action that
-- heartbeats refreshes presence TTL).
pcall(comfy_presence_register)
pcall(comfy_presence_heartbeat)

return script_data
