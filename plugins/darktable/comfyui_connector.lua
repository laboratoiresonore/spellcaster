--[[
  comfyui_connector.lua - Send images to ComfyUI for AI processing

  darktable is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.
]]

--[[
    comfyui_connector.lua

    Per-model img2img workflows for every checkpoint on the ComfyUI server.
    Select a model preset, enter a prompt, and send selected images.
    Results are imported back into your darktable library.

    REQUIREMENTS: curl (built into Windows 10+), a running ComfyUI server.
    Enable via script_manager in lighttable.
]]

local dt = require "darktable"
local du = require "lib/dtutils"

local MODULE_NAME = "comfyui_connector"
du.check_min_api_version("7.0.0", MODULE_NAME)

-- gettext must be defined BEFORE anything uses _()
local gettext = dt.gettext.gettext
dt.gettext.bindtextdomain(MODULE_NAME, dt.configuration.config_dir .. "/lua/locale/")
local function _(msgid) return gettext(msgid) end

-- return data structure for script_manager
local script_data = {}

script_data.metadata = {
  name = _("Spellcaster"),
  purpose = _("send images to a ComfyUI server for AI processing"),
  author = "Spellcaster",
  help = ""
}

script_data.destroy = nil
script_data.destroy_method = nil
script_data.restart = nil
script_data.show = nil

-- ═══════════════════════════════════════════════════════════════════════
-- MODEL PRESETS – mirrors GIMP plugin, tuned per architecture
-- ═══════════════════════════════════════════════════════════════════════

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

  -- Other
  { label = "ZIT - GonzaloMo Zpop v3 AIO", arch = "zit",
    ckpt  = "ZIT\\gonzalomoZpop_v30AIO.safetensors",
    steps = 25, cfg = 7.0, denoise = 0.60,
    sampler = "euler", scheduler = "normal",
    prompt_hint = "high quality, detailed",
    negative_hint = "worst quality, low quality, blurry" },
}

-- ═══════════════════════════════════════════════════════════════════════
-- Architecture → compatible LoRA folder prefixes
-- ═══════════════════════════════════════════════════════════════════════

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
      if starts_with(lora, prefix) or lora == prefix:gsub("\\$", "") then
        table.insert(filtered, lora)
        break
      end
    end
  end
  return filtered
end

-- ═══════════════════════════════════════════════════════════════════════
-- Preferences
-- ═══════════════════════════════════════════════════════════════════════

dt.preferences.register(MODULE_NAME, "server_url", "string",
  _("ComfyUI server URL"),
  _("Full URL including port"),
  "http://127.0.0.1:8188")

dt.preferences.register(MODULE_NAME, "timeout", "integer",
  _("Timeout (seconds)"),
  _("Max wait for ComfyUI processing"),
  300, 10, 3600)

-- ═══════════════════════════════════════════════════════════════════════
-- HTTP via curl
-- ═══════════════════════════════════════════════════════════════════════

local sep = dt.configuration.running_os == "windows" and "\\" or "/"

local function get_server()
  return dt.preferences.read(MODULE_NAME, "server_url", "string")
end

local function tmp_dir()
  return os.getenv("TEMP") or os.getenv("TMP") or os.getenv("TMPDIR") or "/tmp"
end

local function curl_get(url)
  local tmp = tmp_dir() .. sep .. "comfyui_resp_" .. os.time() .. ".json"
  os.execute(string.format('curl -s -o "%s" "%s"', tmp, url))
  local f = io.open(tmp, "r")
  if not f then return nil end
  local c = f:read("*all"); f:close(); os.remove(tmp)
  return c
end

local function curl_post_json(url, json_str)
  local tb = tmp_dir() .. sep .. "comfyui_body_" .. os.time() .. ".json"
  local tr = tmp_dir() .. sep .. "comfyui_presp_" .. os.time() .. ".json"
  local f = io.open(tb, "w"); f:write(json_str); f:close()
  os.execute(string.format('curl -s -X POST -H "Content-Type: application/json" -d @"%s" -o "%s" "%s"', tb, tr, url))
  os.remove(tb)
  local rf = io.open(tr, "r")
  if not rf then return nil end
  local c = rf:read("*all"); rf:close(); os.remove(tr)
  return c
end

local function curl_upload(url, filepath, filename)
  local tr = tmp_dir() .. sep .. "comfyui_up_" .. os.time() .. ".json"
  os.execute(string.format(
    'curl -s -X POST -F "image=@%s;filename=%s" -F "type=input" -F "overwrite=true" -o "%s" "%s"',
    filepath, filename, tr, url))
  local f = io.open(tr, "r")
  if not f then return nil end
  local c = f:read("*all"); f:close(); os.remove(tr)
  return c
end

local function curl_download(url, out)
  os.execute(string.format('curl -s -o "%s" "%s"', out, url))
end

local function json_val(s, key)
  return s and s:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

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
-- Workflow builder
-- ═══════════════════════════════════════════════════════════════════════

-- Escape a string for safe embedding inside a JSON double-quoted value.
-- Handles backslashes first (\ → \\), then double-quotes (" → \").
local function json_escape(s)
  s = s:gsub("\\", "\\\\")   -- backslash must be first
  s = s:gsub('"', '\\"')
  s = s:gsub("\n", "\\n")
  s = s:gsub("\r", "\\r")
  s = s:gsub("\t", "\\t")
  return s
end

-- Compute proportional downscale dimensions fitting within max_res,
-- rounding to multiples of 8 for compatibility with latent-space models.
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

local function build_img2img_json(image_filename, preset, prompt, negative, seed, lora_name, lora_strength, scale_w, scale_h)
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
  "4":{"class_type":"LoadImage","inputs":{"image":"%s"}},
  "90":{"class_type":"GetImageSize+","inputs":{"image":["4",0]}},
  "91":{"class_type":"ImageScale","inputs":{"image":["4",0],"upscale_method":"lanczos","width":%d,"height":%d,"crop":"disabled"}},
  "5":{"class_type":"VAEEncode","inputs":{"pixels":["91",0],"vae":["1",2]}},
  "6":{"class_type":"KSampler","inputs":{
    "model":%s,"positive":["2",0],"negative":["3",0],
    "latent_image":["5",0],"seed":%d,"steps":%d,"cfg":%.1f,
    "sampler_name":"%s","scheduler":"%s","denoise":%.2f}},
  "7":{"class_type":"VAEDecode","inputs":{"samples":["6",0],"vae":["1",2]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["7",0],"upscale_method":"lanczos","width":["90",0],"height":["90",1],"crop":"disabled"}},
  "8":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_comfy"}}
}}]],
    esc_ckpt, lora_node,
    esc_prompt, clip_ref,
    esc_neg, clip_ref,
    image_filename,
    scale_w, scale_h,
    model_ref,
    seed, preset.steps, preset.cfg,
    preset.sampler, preset.scheduler, preset.denoise)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Face Swap workflow builder (using saved face model)
-- ═══════════════════════════════════════════════════════════════════════

local cached_face_models = {}
local cached_swap_models = {}

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
-- mtb Face Swap (direct swap from source image)
-- ═══════════════════════════════════════════════════════════════════════

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

local function wan_video_dims(src_w, src_h, target_long, align)
  -- Scale so longest side ≈ target_long, round to align (VAE requirement)
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

-- Each preset can recommend LoRAs via:
--   loras = {{name = "filename_suffix.safetensors", strength = 0.5}, ...}
-- These auto-populate the 3 LoRA content slots when the preset is selected.
-- NOTE: Content LoRAs apply to BOTH high and low noise models equally.
-- For noise-specific pairs, use the accel LoRA system in WAN_I2V_MODELS.
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
      if lower:sub(1, 4) == "wan\\" or lower:sub(1, 4) == "wan/"
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
    local function short(p) return p:match("\\([^\\]+)$") or p end
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

  local is_gguf_high = wan_preset.high_model:match("%.gguf$") ~= nil
  local is_gguf_low  = wan_preset.low_model:match("%.gguf$") ~= nil
  local high_loader = is_gguf_high and "UnetLoaderGGUF" or "UNETLoader"
  local low_loader  = is_gguf_low  and "UnetLoaderGGUF" or "UNETLoader"
  local high_extra = is_gguf_high and "" or ',"weight_dtype":"default"'
  local low_extra  = is_gguf_low  and "" or ',"weight_dtype":"default"'

  -- Build LoRA chain nodes for both models
  local lora_nodes = ""
  local high_model_ref = '["2",0]'
  local low_model_ref  = '["3",0]'

  -- Collect all LoRAs: accelerator first, then user LoRAs
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
-- PuLID Flux workflow (lowercase Pulid* node family)
-- ═══════════════════════════════════════════════════════════════════════

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
    loras = { sdxl = { {"SDXL\\realistic\\feet v3.safetensors", 0.8, 0.8} } } },

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
    loras = { sdxl = { {"SDXL\\Green_Slime_WAM_Gunge_Wet_and_Messy_Sploshing_Splosh.safetensors", 0.9, 0.9} } } },

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
    loras = { zit = { {"Z-Image-Turbo\\Effect\\Tentacledv1.safetensors", 0.85, 0.85} },
              flux2klein = { {"Flux-2-Klein\\Tentacle v2_000002000.safetensors", 0.85, 0.85} } } },

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
-- SDXL Inpaint workflow (CheckpointLoaderSimple + SetLatentNoiseMask)
-- ═══════════════════════════════════════════════════════════════════════

local function build_inpaint_json(image_filename, mask_filename, preset, prompt, negative,
                                   seed, scale_w, scale_h, loras)
  local esc_prompt = json_escape(prompt)
  local esc_neg = json_escape(negative)
  local esc_ckpt = json_escape(preset.ckpt)

  -- Build LoRA chain: ckpt "1" → lora100 → lora101 → ... → final_model/clip
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

  return string.format([[
{"prompt":{
  "1":{"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":"%s"}},
%s  "2":{"class_type":"CLIPTextEncode","inputs":{"text":"%s","clip":%s}},
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
    "model":%s,"positive":["2",0],"negative":["3",0],
    "latent_image":["7",0],"seed":%d,"steps":%d,"cfg":%.1f,
    "sampler_name":"%s","scheduler":"%s","denoise":%.2f}},
  "9":{"class_type":"VAEDecode","inputs":{"samples":["8",0],"vae":["1",2]}},
  "95":{"class_type":"ImageScale","inputs":{"image":["9",0],"upscale_method":"lanczos","width":["90",0],"height":["90",1],"crop":"disabled"}},
  "10":{"class_type":"SaveImage","inputs":{"images":["95",0],"filename_prefix":"darktable_inpaint"}}
}}]],
    esc_ckpt,
    lora_nodes,
    esc_prompt, clip_ref,
    esc_neg, clip_ref,
    image_filename,
    mask_filename,
    scale_w, scale_h,
    scale_w, scale_h,
    model_ref,
    seed, preset.steps, preset.cfg,
    preset.sampler, preset.scheduler, preset.denoise)
end

-- ═══════════════════════════════════════════════════════════════════════
-- Core processing
-- ═══════════════════════════════════════════════════════════════════════

-- Forward declarations for GUI widgets referenced by process functions.
-- In Lua, a local is only in scope from its declaration onward.
-- These are assigned later in the GUI section; without these forward
-- declarations, all process functions would get nil when reading
-- max_res_slider, causing silent crashes in darktable callbacks.
local max_res_slider
local status_label

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

local function launch_splash()
  local lock_file = tmp_dir() .. sep .. "comfyui_splash_" .. os.time() .. "_" .. math.random(1000,9999) .. ".lock"
  local f = io.open(lock_file, "w")
  if f then f:write("1"); f:close() end
  
  local script_dir = debug.getinfo(1, "S").source:match("@?(.*[/\\])") or ""
  local splash_script = script_dir .. "splash.py"
  
  if dt.configuration.running_os == "windows" then
    os.execute(string.format('start /B pythonw "%s" "%s"', splash_script, lock_file))
  else
    os.execute(string.format('python3 "%s" "%s" &', splash_script, lock_file))
  end
  return lock_file
end

local function kill_splash(lock_file)
  if lock_file then
    os.remove(lock_file)
  end
end

local function wait_result(prompt_id, timeout_override)
  local server = get_server()
  local timeout = timeout_override or dt.preferences.read(MODULE_NAME, "timeout", "integer")
  local deadline = os.time() + timeout
  local lock_file = launch_splash()
  
  while os.time() < deadline do
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

local function wait_result_all(prompt_id, timeout_override)
  -- Like wait_result but returns ALL output files (images + gifs/videos).
  -- Returns table of {filename, subfolder, type} entries.
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

local function process_image(image, preset, prompt, negative, lora_name, lora_strength)
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
  local wf_json = build_img2img_json(upload_name, preset, prompt, negative, seed, lora_name, lora_strength, scale_w, scale_h)

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
      os.execute((dt.configuration.running_os == "windows" and "mkdir " or "mkdir -p ") .. '"' .. vid_dir .. '"')
      local safe_fn = fn:gsub("\\", "_"):gsub("/", "_")
      local vid_path = vid_dir .. sep .. safe_fn
      curl_download(url, vid_path)
      mp4_opened = true
      -- Open with system player
      if dt.configuration.running_os == "windows" then
        os.execute('start "" "' .. vid_path .. '"')
      elseif dt.configuration.running_os == "macos" then
        os.execute('open "' .. vid_path .. '"')
      else
        os.execute('xdg-open "' .. vid_path .. '" &')
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

local function process_inpaint(image, preset, mask_path, prompt, negative, loras)
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
                                      seed, scale_w, scale_h, loras)

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

-- ═══════════════════════════════════════════════════════════════════════
-- GUI
-- ═══════════════════════════════════════════════════════════════════════

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
  changed_callback = function(self)
    -- Re-filter LoRAs when model selection changes
    if #cached_all_loras > 0 then
      refresh_lora_selector()
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

-- Refresh the LoRA combobox with only architecture-compatible LoRAs
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
    local short = name:match("\\([^\\]+)$") or name
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

local send_btn = dt.new_widget("button") {
  label = _("Process with Spellcaster"),
  tooltip = _("Process selected images with the chosen model preset"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then
      dt.print(_("No images selected")); return
    end

    local idx = model_selector.selected
    local preset = MODEL_PRESETS[idx]
    if not preset then
      dt.print(_("Invalid model selection")); return
    end

    -- Build final prompt: preset hint + user prompt
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

    -- Apply denoise override if set
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

    for i, img in ipairs(images) do
      dt.print(string.format(_("Image %d/%d"), i, #images))
      local ok, err = pcall(process_image, img, p, prompt, negative, lora_name, lora_str)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster img2img error: " .. tostring(err))
      end
    end

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

-- Explicit High Noise / Low Noise LoRA pair selectors (3 slots)
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

-- Shared helper: collect all Wan I2V parameters from UI widgets
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

local wan_send_full_btn = dt.new_widget("button") {
  label = _("Wan I2V (Whole Image)"),
  tooltip = _("Generate video from the entire image using Wan 2.2"),
  clicked_callback = function()
    local images = dt.gui.selection()
    if #images == 0 then dt.print(_("No images selected")); return end
    local p = collect_wan_i2v_params()

    for i, img in ipairs(images) do
      dt.print(string.format(_("Wan I2V (whole) %d/%d"), i, #images))
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

    for i, img in ipairs(images) do
      dt.print(string.format(_("Wan I2V (selection) %d/%d"), i, #images))
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

    for i, img in ipairs(images) do
      dt.print(string.format(_("Klein %d/%d"), i, #images))
      local ok, err = pcall(process_klein, img, klein_model, prompt, steps, guidance)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster Klein error: " .. tostring(err))
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

    for i, img in ipairs(images) do
      dt.print(string.format(_("Inpaint %d/%d"), i, #images))
      local ok, err = pcall(process_inpaint, img, p, mask_path, prompt, negative, loras)
      if not ok then
        dt.print(_("Error: ") .. tostring(err))
        dt.print_error("Spellcaster Inpaint error: " .. tostring(err))
      end
    end
  end
}

-- ═══════════════════════════════════════════════════════════════════════
-- Module registration (guarded for lighttable view)
-- ═══════════════════════════════════════════════════════════════════════

local module_widget = dt.new_widget("box") {
  orientation = "vertical",
  status_label,
  test_btn,
  dt.new_widget("separator") {},

  -- Global scaling control
  dt.new_widget("label") { label = _("── Resolution Scaling ──") },
  max_res_slider,
  dt.new_widget("separator") {},

  -- img2img section
  dt.new_widget("label") { label = _("── Image to Image ──") },
  dt.new_widget("label") { label = _("Model Preset:") },
  model_selector,
  info_label,
  dt.new_widget("label") { label = _("Additional Prompt:") },
  prompt_entry,
  dt.new_widget("label") { label = _("Additional Negative:") },
  negative_entry,
  denoise_slider,
  dt.new_widget("label") { label = _("LoRA:") },
  fetch_lora_btn,
  lora_selector,
  lora_strength_slider,
  send_btn,
  upload_btn,
  dt.new_widget("separator") {},

  -- Inpaint section
  dt.new_widget("label") { label = _("── Inpaint (Mask-Based) ──") },
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
  inpaint_send_btn,
  dt.new_widget("separator") {},

  -- Face swap section
  dt.new_widget("label") { label = _("── Face Swap (Saved Model) ──") },
  fetch_face_btn,
  face_model_selector,
  swap_model_selector,
  faceswap_btn,
  dt.new_widget("separator") {},

  -- mtb Face Swap section
  dt.new_widget("label") { label = _("── Face Swap (mtb Direct) ──") },
  dt.new_widget("label") { label = _("Source Face Image Path:") },
  mtb_source_entry,
  mtb_analysis_selector,
  mtb_swap_selector,
  dt.new_widget("label") { label = _("Face Index:") },
  mtb_face_idx_entry,
  mtb_swap_btn,
  dt.new_widget("separator") {},

  -- Wan I2V section
  dt.new_widget("label") { label = _("── Wan 2.2 Image to Video ──") },
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
  dt.new_widget("label") { label = _("── End Image (VACE Start→End) ──") },
  wan_end_image_entry,
  wan_vace_strength_slider,
  wan_send_full_btn,
  dt.new_widget("label") { label = _("── Selection Region ──") },
  wan_crop_x_slider,
  wan_crop_y_slider,
  wan_crop_w_slider,
  wan_crop_h_slider,
  wan_send_sel_btn,
  dt.new_widget("separator") {},

  -- Klein Flux2 section
  dt.new_widget("label") { label = _("── Klein Flux2 Distilled ──") },
  klein_model_selector,
  dt.new_widget("label") { label = _("Prompt:") },
  klein_prompt_entry,
  klein_steps_slider,
  klein_guidance_slider,
  klein_send_btn,
  dt.new_widget("separator") {},

  -- PuLID Flux section
  dt.new_widget("label") { label = _("── PuLID Flux (Face Identity) ──") },
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
  dt.new_widget("label") { label = _("── Face Swap (Direct/ReActor) ──") },
  dt.new_widget("label") { label = _("Source Face Image Path:") },
  fsd_source_entry,
  fsd_swap_selector,
  fsd_send_btn,
  dt.new_widget("separator") {},

  -- FaceID (IPAdapter) section
  dt.new_widget("label") { label = _("── FaceID (IPAdapter) ──") },
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
  dt.new_widget("label") { label = _("── Klein Flux2 + Reference ──") },
  kleinref_model_selector,
  dt.new_widget("label") { label = _("Prompt:") },
  kleinref_prompt_entry,
  dt.new_widget("label") { label = _("Reference Image Path:") },
  kleinref_ref_entry,
  kleinref_steps_slider,
  kleinref_guidance_slider,
  kleinref_send_btn,
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

-- Only register if we're already in lighttable; otherwise wait for view switch
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

script_data.destroy = destroy
script_data.restart = restart
script_data.destroy_method = "hide"
script_data.show = restart

dt.print(_("Spellcaster loaded - img2img, inpaint, face swap, Wan I2V, Klein Flux2, PuLID Flux, FaceID, Klein+Ref"))

return script_data
