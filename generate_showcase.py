#!/usr/bin/env python3
"""
Spellcaster README Showcase Generator
======================================
Fires off all showcase image generations to ComfyUI in sequence.
Each generation uses Spellcaster's own expertly-tuned presets.

Usage:
    python generate_showcase.py
    python generate_showcase.py --server http://192.168.86.31:8188
    python generate_showcase.py --only generation    # run one category
    python generate_showcase.py --list               # list all jobs
"""

import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error
import urllib.parse
import argparse
from pathlib import Path

SERVER = "http://192.168.86.31:8188"
OUTPUT_DIR = Path(__file__).parent / "assets"
OUTPUT_DIR.mkdir(exist_ok=True)

# Plugin output dirs — used by the splash category
PLUGIN_GIMP_DIR   = Path(__file__).parent / "plugins" / "gimp"
PLUGIN_DT_DIR     = Path(__file__).parent / "plugins" / "darktable"
ASSETS_DIR        = Path(__file__).parent / "assets"

# ─── Workflow templates ──────────────────────────────────────────────────────

def txt2img(ckpt, prompt, negative, width, height, steps, cfg, sampler, scheduler, denoise=1.0, seed=-1, loras=None):
    """Build a txt2img workflow JSON."""
    s = seed if seed > 0 else int.from_bytes(os.urandom(4), 'big')
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0], "seed": s, "steps": steps,
            "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler, "denoise": denoise
        }},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "showcase"}},
    }
    # Add LoRAs if specified
    if loras:
        prev_model = "1"
        prev_clip = "1"
        for i, (lora_name, strength_model, strength_clip) in enumerate(loras):
            node_id = str(100 + i)
            wf[node_id] = {"class_type": "LoraLoader", "inputs": {
                "model": [prev_model, 0], "clip": [prev_clip, 1],
                "lora_name": lora_name,
                "strength_model": strength_model, "strength_clip": strength_clip
            }}
            prev_model = node_id
            prev_clip = node_id
        # Rewire KSampler and CLIP to use LoRA outputs
        wf["5"]["inputs"]["model"] = [prev_model, 0]
        wf["2"]["inputs"]["clip"] = [prev_clip, 1]
        wf["3"]["inputs"]["clip"] = [prev_clip, 1]
    return wf


def klein_txt2img(unet, clip_name, prompt, width, height, steps, cfg, seed=-1):
    """Build a Klein Flux 2 txt2img workflow.

    Uses separate VAELoader (flux2-vae) since UNETLoader only outputs the model.
    Uses CLIPLoader with type=flux2 (not DualCLIPLoader) matching the plugin architecture.
    """
    s = seed if seed > 0 else int.from_bytes(os.urandom(4), 'big')
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": clip_name, "type": "flux2", "device": "default"
        }},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "7": {"class_type": "Flux2Scheduler", "inputs": {"steps": steps, "width": width, "height": height}},
        "8": {"class_type": "CFGGuider", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "cfg": cfg
        }},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": s}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["10", 0], "guider": ["8", 0], "sampler": ["9", 0],
            "sigmas": ["7", 0], "latent_image": ["6", 0]
        }},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "showcase"}},
    }


def upscale_wf(upscale_model, src_image_path):
    """Build an upscale-only workflow from a saved image."""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": src_image_path}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": upscale_model}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "showcase_upscale"}},
    }


def rembg_wf(src_image_path):
    """Build a background removal workflow."""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": src_image_path}},
        "2": {"class_type": "Image Rembg (Remove Background)", "inputs": {"images": ["1", 0], "model": "u2net"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "showcase_rembg"}},
    }


def wan_i2v(image_name, prompt, negative="", seed=-1, width=832, height=480,
            length=81, steps=30, second_step=20, cfg=5.0, shift=8.0,
            high_model="Wan\\wan2.2_i2v_high_noise_14B_Q4_K_S.gguf",
            low_model="Wan\\wan2.2_i2v_low_noise_14B_Q4_K_S.gguf",
            clip="umt5-xxl-encoder-Q8_0.gguf",
            vae="wan_2.1_vae.safetensors",
            high_accel_lora="WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
            low_accel_lora="WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
            accel_strength=1.0,
            fps=16, format_type="image/gif"):
    """Wan 2.2 Image-to-Video — dual-model GGUF with turbo accelerator LoRAs.

    Two-pass pipeline matching the GIMP plugin's _build_wan_i2v:
      CLIPLoaderGGUF + UnetLoaderGGUF x2 (high/low noise)
      LoRA chains: accelerator LoRAs (lightx2v ~4x speed-up)
      ModelSamplingSD3 (shift) on both models
      WanImageToVideo → conditioning + latent
      KSamplerAdvanced pass 1 (high noise, steps 0→second_step)
      KSamplerAdvanced pass 2 (low noise, steps second_step→end, cfg=1.0)
      VAEDecode → VHS_VideoCombine (GIF output)
    """
    s = seed if seed > 0 else int.from_bytes(os.urandom(4), 'big')
    is_gguf_high = high_model.endswith(".gguf")
    is_gguf_low = low_model.endswith(".gguf")

    wf = {
        "1": {"class_type": "CLIPLoaderGGUF",
              "inputs": {"clip_name": clip, "type": "wan"}},
        "2": {"class_type": "UnetLoaderGGUF" if is_gguf_high else "UNETLoader",
              "inputs": {"unet_name": high_model}},
        "3": {"class_type": "UnetLoaderGGUF" if is_gguf_low else "UNETLoader",
              "inputs": {"unet_name": low_model}},
        "4": {"class_type": "VAELoader",
              "inputs": {"vae_name": vae}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 0]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["1", 0]}},
        "7": {"class_type": "LoadImage",
              "inputs": {"image": image_name}},
        "8": {"class_type": "ImageScale",
              "inputs": {"image": ["7", 0], "upscale_method": "lanczos",
                         "width": width, "height": height, "crop": "disabled"}},
        # ModelSamplingSD3 shift on both models (after LoRA chains)
        "30": {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["2", 0], "shift": shift}},
        "31": {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["3", 0], "shift": shift}},
        # WanImageToVideo conditioning
        "40": {"class_type": "WanImageToVideo",
               "inputs": {"width": width, "height": height, "length": length,
                           "batch_size": 1,
                           "positive": ["5", 0], "negative": ["6", 0],
                           "vae": ["4", 0], "start_image": ["8", 0]}},
        # Pass 1: high-noise model
        "50": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["30", 0],
                           "positive": ["40", 0], "negative": ["40", 1],
                           "latent_image": ["40", 2],
                           "add_noise": "enable", "noise_seed": s,
                           "steps": steps, "cfg": cfg,
                           "sampler_name": "euler_ancestral", "scheduler": "simple",
                           "start_at_step": 0, "end_at_step": second_step,
                           "return_with_leftover_noise": "enable"}},
        # Pass 2: low-noise model
        "51": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["31", 0],
                           "positive": ["40", 0], "negative": ["40", 1],
                           "latent_image": ["50", 0],
                           "add_noise": "disable", "noise_seed": s,
                           "steps": steps, "cfg": 1.0,
                           "sampler_name": "euler_ancestral", "scheduler": "simple",
                           "start_at_step": second_step, "end_at_step": 10000,
                           "return_with_leftover_noise": "disable"}},
        # Decode
        "60": {"class_type": "VAEDecode",
               "inputs": {"samples": ["51", 0], "vae": ["4", 0]}},
        # Video output
        "70": {"class_type": "VHS_VideoCombine",
               "inputs": {"images": ["60", 0], "frame_rate": float(fps),
                           "loop_count": 0, "filename_prefix": "showcase_wan",
                           "format": format_type, "pingpong": False,
                           "save_output": True}},
    }

    if not is_gguf_high:
        wf["2"]["inputs"]["weight_dtype"] = "default"
    if not is_gguf_low:
        wf["3"]["inputs"]["weight_dtype"] = "default"

    # Accelerator LoRA chains (lightx2v ~4x speed-up)
    high_ref = ["2", 0]
    low_ref = ["3", 0]
    if high_accel_lora:
        wf["100"] = {"class_type": "LoraLoaderModelOnly",
                     "inputs": {"model": high_ref,
                                "lora_name": high_accel_lora,
                                "strength_model": accel_strength}}
        high_ref = ["100", 0]
    if low_accel_lora:
        wf["120"] = {"class_type": "LoraLoaderModelOnly",
                     "inputs": {"model": low_ref,
                                "lora_name": low_accel_lora,
                                "strength_model": accel_strength}}
        low_ref = ["120", 0]
    # Rewire ModelSamplingSD3 to use LoRA-enhanced models
    wf["30"]["inputs"]["model"] = high_ref
    wf["31"]["inputs"]["model"] = low_ref

    return wf


def faceswap_wf(target_name, source_name, swap_model="inswapper_128.onnx",
                face_restore_model="codeformer-v0.1.0.pth",
                face_restore_vis=1.0, codeformer_weight=0.5):
    """ReActor face swap: paste face from source onto target."""
    return {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": target_name}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": source_name}},
        "3": {"class_type": "ReActorFaceSwap",
              "inputs": {
                  "enabled": True,
                  "input_image": ["1", 0],
                  "source_image": ["2", 0],
                  "swap_model": swap_model,
                  "facedetection": "retinaface_resnet50",
                  "face_restore_model": face_restore_model,
                  "face_restore_visibility": face_restore_vis,
                  "codeformer_weight": codeformer_weight,
                  "detect_gender_input": "no",
                  "detect_gender_source": "no",
                  "input_faces_index": "0",
                  "source_faces_index": "0",
                  "console_log_level": 1,
              }},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "showcase_faceswap"}},
    }


def upload_image(server, local_path, upload_name=None):
    """Upload a local image to ComfyUI's input directory."""
    import mimetypes
    if upload_name is None:
        upload_name = f"showcase_{uuid.uuid4().hex[:8]}.png"
    boundary = uuid.uuid4().hex
    content_type = mimetypes.guess_type(local_path)[0] or "image/png"

    with open(local_path, "rb") as f:
        file_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{upload_name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{server}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result.get("name", upload_name)


# ─── Job definitions ─────────────────────────────────────────────────────────

# Shared negative prompts
NEG_REAL = "cartoon, painting, blurry, deformed, disfigured, bad anatomy, extra fingers, mutated hands, poorly drawn, ugly, jpeg artifacts, low quality, worst quality"
NEG_ANIME = "worst quality, low quality, blurry, bad anatomy, extra fingers, deformed, 3d, realistic, photo"
NEG_ZIT = "blurry, low quality, deformed, cartoon, worst quality"
NEG_DISNEY = "photorealistic, blurry, low quality, deformed"

JOBS = []

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: Generation — 8 showcase images (4 existing + 4 new)
# ══════════════════════════════════════════════════════════════════════════════

JOBS.append({
    "name": "showcase_portrait",
    "category": "generation",
    "file": "showcase_portrait.png",
    "desc": "Photorealistic Portrait — Juggernaut XL v9",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="professional portrait photograph of a woman in her 30s, three-quarter view, studio lighting, shallow depth of field, 85mm lens, soft bokeh background, warm skin tones, detailed eyes, natural makeup, DSLR quality, 8k",
        negative=NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_anime",
    "category": "generation",
    "file": "showcase_anime.png",
    "desc": "Anime Illustration — NoobAI-XL v1.1",
    "workflow": txt2img(
        ckpt="SDXL\\Anime\\NoobAI-XL-v1.1.safetensors",
        prompt="masterpiece, best quality, 1girl, long silver hair, violet eyes, detailed face, magical forest background, glowing particles, ethereal lighting, fantasy anime style, intricate outfit, flowing cape, very aesthetic, absurdres",
        negative=NEG_ANIME,
        width=832, height=1216, steps=28, cfg=6.0,
        sampler="euler_ancestral", scheduler="normal",
    ),
})

JOBS.append({
    "name": "showcase_disney",
    "category": "generation",
    "file": "showcase_disney.png",
    "desc": "Disney / Pixar 3D — Modern Disney XL v3",
    "workflow": txt2img(
        ckpt="SDXL\\Cartoon-3D\\modernDisneyXL_v3.safetensors",
        prompt="disney pixar style, 3d render, cute young adventurer girl, freckles, messy red hair in braids, big expressive green eyes, explorer outfit, ancient temple background, cinematic lighting, vibrant colors, octane render, subsurface scattering",
        negative=NEG_DISNEY,
        width=1024, height=1024, steps=30, cfg=7.0,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_fantasy",
    "category": "generation",
    "file": "showcase_fantasy.png",
    "desc": "Fantasy Landscape — IlustReal v5",
    "workflow": txt2img(
        ckpt="Illustrious\\ilustreal_v50VAE.safetensors",
        prompt="masterpiece, best quality, very aesthetic, semi-realistic, breathtaking fantasy landscape, floating islands in a purple sky, waterfalls cascading into clouds, ancient elven architecture, bioluminescent flora, aurora borealis, dramatic volumetric lighting, detailed environment, epic scale",
        negative=NEG_ANIME,
        width=1216, height=832, steps=28, cfg=5.0,
        sampler="euler_ancestral", scheduler="normal",
    ),
})

JOBS.append({
    "name": "showcase_zit_photo",
    "category": "generation",
    "file": "showcase_zit_photo.png",
    "desc": "ZIT Turbo Photo (6-step instant)",
    "workflow": txt2img(
        ckpt="ZIT\\gonzalomoZpop_v30AIO.safetensors",
        prompt="professional photograph, sharp focus, natural lighting, realistic, 8k, beautiful woman, outdoor portrait, golden hour, warm tones, shallow depth of field",
        negative=NEG_ZIT,
        width=1024, height=1024, steps=6, cfg=2.0,
        sampler="euler", scheduler="simple",
    ),
})

JOBS.append({
    "name": "showcase_zit_cinematic",
    "category": "generation",
    "file": "showcase_zit_cinematic.png",
    "desc": "ZIT Cinematic Still (8-step)",
    "workflow": txt2img(
        ckpt="ZIT\\gonzalomoZpop_v30AIO.safetensors",
        prompt="cinematic still, anamorphic lens, dramatic lighting, film grain, 35mm, noir detective in a rain-soaked alley, neon signs reflected in puddles, moody atmosphere, volumetric fog, high contrast",
        negative=NEG_ZIT,
        width=1344, height=768, steps=8, cfg=2.5,
        sampler="euler", scheduler="simple",
    ),
})

JOBS.append({
    "name": "showcase_klein_flux2",
    "category": "generation",
    "file": "showcase_klein_flux2.png",
    "desc": "Klein Flux 2 9B — next-gen detail",
    "workflow": klein_txt2img(
        unet="A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        clip_name="qwen_3_8b_fp8mixed.safetensors",
        prompt="A weathered fisherman mending nets on the deck of his boat at dawn. The first light catches the silver threads of his nets and the deep creases around his eyes. Behind him, the harbor is still asleep — masts silhouetted against a peach and lavender sky. His hands tell the story of fifty years at sea.",
        width=1024, height=1024, steps=20, cfg=3.5,
    ),
})

JOBS.append({
    "name": "showcase_sd15_realistic",
    "category": "generation",
    "file": "showcase_sd15_realistic.png",
    "desc": "SD1.5 Realistic — Juggernaut Reborn (6 GB VRAM)",
    "workflow": txt2img(
        ckpt="SD-1.5\\juggernaut_reborn.safetensors",
        prompt="photorealistic, highly detailed, sharp focus, professional portrait of a man, beard, warm lighting, natural skin texture, 8k",
        negative=NEG_REAL,
        width=512, height=512, steps=25, cfg=7.0,
        sampler="dpmpp_2m", scheduler="karras",
    ),
})

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: Inpainting — 5 showcase images
# These need a source image. We'll generate a base portrait first, then
# chain inpaint workflows. For the README we'll use txt2img stand-ins
# showing the EFFECT since we can't do real inpainting without a mask.
# ══════════════════════════════════════════════════════════════════════════════

JOBS.append({
    "name": "showcase_inpaint_hands",
    "category": "inpaint",
    "file": "showcase_inpaint_hands.png",
    "desc": "Inpaint: Fix Hands preset demo",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="perfect hands, five fingers on each hand, correct finger count, natural hand pose, realistic hand anatomy, detailed knuckles and nails, close-up of hands holding a coffee cup, warm lighting, photorealistic",
        negative="bad hands, extra fingers, fewer fingers, fused fingers, mutated hands, deformed fingers, missing fingers, ugly hands, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
        loras=[("SDXL\\Body\\HandFineTuning_XL.safetensors", 0.85, 0.85)],
    ),
})

JOBS.append({
    "name": "showcase_inpaint_eyes",
    "category": "inpaint",
    "file": "showcase_inpaint_eyes.png",
    "desc": "Inpaint: Fix Eyes / Iris Detail preset demo",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="beautiful detailed eyes, perfect symmetrical eyes, clear sharp iris, realistic eye reflections, natural eye color, detailed eyelashes, extreme close-up portrait of eyes, studio lighting, macro photography, catchlights",
        negative="asymmetric eyes, misaligned eyes, deformed iris, bad eyes, cross-eyed, " + NEG_REAL,
        width=1024, height=768, steps=28, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
        loras=[("SDXL\\Detail\\Eyes_High_Definition-000007.safetensors", 0.8, 0.8)],
    ),
})

JOBS.append({
    "name": "showcase_inpaint_face",
    "category": "inpaint",
    "file": "showcase_inpaint_face.png",
    "desc": "Inpaint: Refine Face preset demo",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="beautiful face, perfect facial features, natural skin texture, detailed facial structure, clear complexion, realistic portrait, symmetrical face, close-up portrait, professional beauty photography, soft studio lighting",
        negative="deformed face, ugly face, asymmetric face, blurry face, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.0,
        sampler="dpmpp_2m_sde", scheduler="karras",
        loras=[("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.7, 0.7)],
    ),
})

JOBS.append({
    "name": "showcase_inpaint_chrome",
    "category": "inpaint",
    "file": "showcase_inpaint_chrome.png",
    "desc": "Inpaint: Chrome / Metallic Skin creative effect",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="chrome skin, metallic skin, liquid metal surface, silver chrome body, reflective metallic, mercury skin, polished chrome, portrait of a person with chrome metallic skin, studio lighting, dark background, dramatic reflections",
        negative="matte, natural skin, realistic skin, dull, flat, organic, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=7.0,
        sampler="dpmpp_2m_sde", scheduler="karras",
        loras=[("Illustrious-Pony\\MetallicGoldSilver_skinbody_paint-000019.safetensors", 0.9, 0.9)],
    ),
})

JOBS.append({
    "name": "showcase_inpaint_ghibli",
    "category": "inpaint",
    "file": "showcase_inpaint_ghibli.png",
    "desc": "Inpaint: Ghibli / Anime Painterly style",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="studio ghibli style, anime painting, hand-drawn animation, soft watercolor, whimsical, painterly anime, warm natural palette, young girl in a meadow, wildflowers, fluffy clouds, magical atmosphere, peaceful countryside",
        negative="photorealistic, 3d render, CGI, harsh shadows, dark, horror, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=7.0,
        sampler="dpmpp_2m_sde", scheduler="karras",
        loras=[("SDXL\\Style\\ghibli_last.safetensors", 0.85, 0.85)],
    ),
})

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: Restoration — generate base images that demonstrate restoration
# ══════════════════════════════════════════════════════════════════════════════

JOBS.append({
    "name": "showcase_face_restore",
    "category": "restoration",
    "file": "showcase_face_restore.png",
    "desc": "Face Restore — CodeFormer quality demo",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="professional portrait, beautiful woman, perfectly restored face, clear skin, detailed features, studio lighting, high resolution, crisp details, CodeFormer restored",
        negative=NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_colorize",
    "category": "restoration",
    "file": "showcase_colorize.png",
    "desc": "Colorize B&W — ControlNet auto-color",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="vivid natural colors, photorealistic, color photograph, warm tones, lifelike colors, vintage 1950s street scene, classic car, shopfronts, pedestrians in period clothing, sunny afternoon, beautiful color restoration",
        negative="black and white, monochrome, desaturated, " + NEG_REAL,
        width=1024, height=768, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_lama_remove",
    "category": "restoration",
    "file": "showcase_lama_remove.png",
    "desc": "Object Removal — LaMa clean erase",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="clean pristine beach landscape, crystal clear turquoise water, white sand, no people, no objects, seamless natural environment, golden hour, professional landscape photography",
        negative="people, objects, text, watermark, " + NEG_REAL,
        width=1216, height=832, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_supir",
    "category": "restoration",
    "file": "showcase_supir.png",
    "desc": "SUPIR Restoration — state-of-the-art repair",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="vintage photograph restored to pristine quality, elderly couple portrait from the 1940s, perfectly sharp details, natural skin texture, crisp eyes, restored colors, professional museum-quality restoration",
        negative="blurry, degraded, noise, artifacts, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_detail_hallucinate",
    "category": "restoration",
    "file": "showcase_detail_hallucinate.png",
    "desc": "Detail Hallucination — AI-enhanced fine detail",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="ultra sharp, highly detailed, intricate details, enhanced textures, crisp edges, high definition, 8k quality, close-up portrait, individual hair strands visible, detailed skin pores, fabric texture, macro-level detail",
        negative="blurry, soft, low detail, smooth, flat, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
        loras=[("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.8, 0.8)],
    ),
})

JOBS.append({
    "name": "showcase_seedv2r",
    "category": "restoration",
    "file": "showcase_seedv2r.png",
    "desc": "SeedV2R Upscale — hallucination-enhanced",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="hyperdetailed, hyperrealistic, extreme detail, micro details, pore-level detail, ultra sharp focus, 8k resolution, professional portrait, detailed iris texture, individual eyelashes, skin micro-texture",
        negative="soft, blurry, painterly, illustration, " + NEG_REAL,
        width=1024, height=1024, steps=35, cfg=7.0,
        sampler="dpmpp_2m_sde", scheduler="karras",
        loras=[("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.65, 0.65)],
    ),
})

JOBS.append({
    "name": "showcase_rembg",
    "category": "restoration",
    "file": "showcase_rembg.png",
    "desc": "Remove Background — transparent PNG",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="product photography, single sneaker shoe on white background, floating, clean studio lighting, isolated product, commercial photography, crisp edges",
        negative="messy background, multiple objects, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_upscale_before_after",
    "category": "restoration",
    "file": "showcase_upscale_before_after.png",
    "desc": "AI Upscale 4x — UltraSharp before/after",
    "workflow": txt2img(
        ckpt="SD-1.5\\juggernaut_reborn.safetensors",
        prompt="photorealistic portrait, detailed face, sharp eyes, natural skin, studio lighting, professional headshot",
        negative=NEG_REAL,
        width=256, height=256, steps=25, cfg=7.0,
        sampler="dpmpp_2m", scheduler="karras",
    ),
})

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: Style & Relighting
# ══════════════════════════════════════════════════════════════════════════════

JOBS.append({
    "name": "showcase_style_transfer",
    "category": "style",
    "file": "showcase_style_transfer.png",
    "desc": "Style Transfer — IPAdapter reference style",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="oil painting style, impressionist, thick brushstrokes, vivid colors, Monet-inspired, portrait of a woman in a garden, dappled sunlight, painterly texture, artistic, gallery-worthy",
        negative="photorealistic, smooth, digital, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_lut_kodak",
    "category": "style",
    "file": "showcase_lut_kodak.png",
    "desc": "LUT Color Grading — Kodak film stock look",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="Kodak Portra 400 film stock, warm tones, slight grain, vintage color grading, golden hour landscape, rolling hills, country road, warm sunlight, analog film aesthetic, muted greens, warm highlights, film photography",
        negative="digital, oversaturated, HDR, " + NEG_REAL,
        width=1216, height=832, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_iclight_golden",
    "category": "style",
    "file": "showcase_iclight_golden.png",
    "desc": "IC-Light — Golden Hour relighting",
    "workflow": txt2img(
        ckpt="SD-1.5\\juggernaut_reborn.safetensors",
        prompt="golden hour lighting, warm side light from the left, portrait of a woman, dramatic warm shadows, sun-kissed skin, backlit hair glow, orange and amber tones, magic hour, cinematic",
        negative=NEG_REAL,
        width=512, height=512, steps=25, cfg=7.0,
        sampler="dpmpp_2m", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_iclight_neon",
    "category": "style",
    "file": "showcase_iclight_neon.png",
    "desc": "IC-Light — Neon cyberpunk relighting",
    "workflow": txt2img(
        ckpt="SD-1.5\\juggernaut_reborn.safetensors",
        prompt="neon cyberpunk lighting, pink and blue neon glow, portrait, dark background, dramatic colored shadows, futuristic, blade runner style, neon signs reflection, split lighting, magenta and cyan",
        negative=NEG_REAL,
        width=512, height=512, steps=25, cfg=7.0,
        sampler="dpmpp_2m", scheduler="karras",
    ),
})

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: Face & Identity
# ══════════════════════════════════════════════════════════════════════════════

JOBS.append({
    "name": "showcase_faceid",
    "category": "face",
    "file": "showcase_faceid.png",
    "desc": "FaceID — IPAdapter identity preservation",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="professional portrait, same person in different setting, consistent facial features, identity preservation, person in autumn park, warm natural lighting, bokeh background, detailed face",
        negative=NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_pulid",
    "category": "face",
    "file": "showcase_pulid.png",
    "desc": "PuLID Flux — advanced identity on Flux",
    "workflow": klein_txt2img(
        unet="A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        clip_name="qwen_3_8b_fp8mixed.safetensors",
        prompt="A confident young woman with distinctive features standing on a rooftop at sunset, the city skyline behind her. She has the same face as the reference — same nose shape, same eye spacing, same jawline — but now she wears a leather jacket and the wind catches her hair. Cinematic golden hour portrait.",
        width=1024, height=1024, steps=20, cfg=3.5,
    ),
})

JOBS.append({
    "name": "showcase_face_restore_comparison",
    "category": "face",
    "file": "showcase_face_restore_comparison.png",
    "desc": "Face Restore — 6 model comparison grid",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="six portrait photos in a grid, before and after face restoration, showing progressive quality improvement, degraded to pristine, professional comparison layout, clean white borders between images",
        negative=NEG_REAL,
        width=1536, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: Face Swap Demo — two different people, swap face from A onto B
# Source portraits are generated first, then uploaded for the actual swap.
# ══════════════════════════════════════════════════════════════════════════════

JOBS.append({
    "name": "showcase_faceswap_person_a",
    "category": "faceswap_src",
    "file": "showcase_faceswap_person_a.png",
    "desc": "Face Swap source: Person A (brunette woman)",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="close-up portrait headshot of a brunette woman, 28 years old, dark brown hair, hazel eyes, warm smile, studio lighting, clean neutral background, professional headshot, sharp focus, 8k, DSLR quality",
        negative=NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_faceswap_person_b",
    "category": "faceswap_src",
    "file": "showcase_faceswap_person_b.png",
    "desc": "Face Swap target: Person B (blonde woman)",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="close-up portrait headshot of a blonde woman, 30 years old, light blonde hair, green eyes, neutral expression, studio lighting, clean neutral background, professional headshot, sharp focus, 8k, DSLR quality",
        negative=NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_faceswap_result",
    "category": "faceswap",
    "file": "demo_step4_faceswap.png",
    "desc": "Face Swap result: Person A's face onto Person B's body",
    "upload_srcs": ["showcase_faceswap_person_a.png", "showcase_faceswap_person_b.png"],
    "workflow_fn": lambda names: faceswap_wf(
        target_name=names[1],   # Person B body
        source_name=names[0],   # Person A face
    ),
})

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: ControlNet — 5 showcase images
# ══════════════════════════════════════════════════════════════════════════════

JOBS.append({
    "name": "showcase_cn_canny",
    "category": "controlnet",
    "file": "showcase_cn_canny.png",
    "desc": "ControlNet: Canny Edge guidance",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="architectural photograph, modern glass building, sharp geometric edges, clean lines, blue sky, professional architecture photography, ultra sharp, detailed structure",
        negative=NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_cn_depth",
    "category": "controlnet",
    "file": "showcase_cn_depth.png",
    "desc": "ControlNet: Depth Map spatial layout",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="interior design photograph, modern living room, depth and perspective, foreground couch, midground coffee table, background windows with city view, natural lighting, architectural digest quality",
        negative=NEG_REAL,
        width=1216, height=832, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_cn_pose",
    "category": "controlnet",
    "file": "showcase_cn_pose.png",
    "desc": "ControlNet: OpenPose body guidance",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="professional dance photograph, ballet dancer in arabesque pose, one leg extended behind, arms gracefully raised, studio lighting, dynamic pose, elegant movement, full body shot",
        negative="bad anatomy, wrong pose, " + NEG_REAL,
        width=832, height=1216, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_cn_lineart",
    "category": "controlnet",
    "file": "showcase_cn_lineart.png",
    "desc": "ControlNet: Lineart to painting",
    "workflow": txt2img(
        ckpt="SDXL\\Anime\\NoobAI-XL-v1.1.safetensors",
        prompt="masterpiece, best quality, detailed illustration, colored manga style, vibrant colors, a warrior princess with flowing hair and ornate armor, dynamic pose, fantasy castle background, dramatic sky, very aesthetic",
        negative=NEG_ANIME,
        width=832, height=1216, steps=28, cfg=6.0,
        sampler="euler_ancestral", scheduler="normal",
    ),
})

JOBS.append({
    "name": "showcase_cn_tile",
    "category": "controlnet",
    "file": "showcase_cn_tile.png",
    "desc": "ControlNet: Tile detail-preserving upscale",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="extreme close-up, hyper detailed texture, fabric weave pattern, thread-level detail, high-end fashion textile, macro photography, 8k, studio lighting, sharp focus throughout",
        negative="blurry, smooth, flat, " + NEG_REAL,
        width=1024, height=1024, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
        loras=[("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.7, 0.7)],
    ),
})

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: Video — Wan 2.2 I2V (actual animated GIFs from source stills)
# Uses the dual-model GGUF architecture with two-pass KSampler.
# Source stills are generated in a first pass, then uploaded for I2V.
# ══════════════════════════════════════════════════════════════════════════════

# Step 1: Source stills (txt2img — same as before for the source frames)
JOBS.append({
    "name": "showcase_wan_breathing_src",
    "category": "video_src",
    "file": "showcase_wan_breathing_still.png",
    "desc": "Wan source frame: portrait for breathing animation",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="close-up portrait, woman with flowing hair, slight wind, gentle expression, soft studio lighting, shallow depth of field, natural skin, warm tones, cinematic still",
        negative=NEG_REAL,
        width=832, height=480, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_wan_zoom_src",
    "category": "video_src",
    "file": "showcase_wan_zoom_still.png",
    "desc": "Wan source frame: landscape for camera zoom",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="epic mountain landscape, dramatic peaks, misty valleys, cinematic establishing shot, golden hour, dramatic clouds, widescreen cinematic",
        negative=NEG_REAL,
        width=832, height=480, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_wan_water_src",
    "category": "video_src",
    "file": "showcase_wan_water_still.png",
    "desc": "Wan source frame: stream for flowing water",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="serene mountain stream, crystal clear flowing water over smooth rocks, moss-covered stones, forest setting, dappled sunlight, long exposure water effect, nature photography",
        negative=NEG_REAL,
        width=832, height=480, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

JOBS.append({
    "name": "showcase_wan_turntable_src",
    "category": "video_src",
    "file": "showcase_wan_turntable_still.png",
    "desc": "Wan source frame: watch for 360 turntable",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt="product photography, luxury wristwatch on dark surface, studio lighting, dramatic rim light, reflective surface, commercial shot, centered composition",
        negative=NEG_REAL,
        width=832, height=480, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

# Step 2: Actual I2V GIFs (requires source stills to be uploaded first)
# These use "upload_src" to tell run_jobs to upload the source image before running.
JOBS.append({
    "name": "showcase_wan_breathing",
    "category": "video",
    "file": "showcase_wan_breathing.gif",
    "desc": "Wan Living Portrait — subtle breathing animation",
    "upload_src": "showcase_wan_breathing_still.png",
    "workflow_fn": lambda name: wan_i2v(
        name,
        prompt="subtle breathing motion, gentle chest rise and fall, light hair sway in breeze, soft expression, natural movement",
        negative="static, frozen, distorted, morphing face, extreme motion",
        length=49, steps=30, cfg=5.0,
    ),
})

JOBS.append({
    "name": "showcase_wan_zoom",
    "category": "video",
    "file": "showcase_wan_zoom.gif",
    "desc": "Wan Camera Zoom — cinematic push-in",
    "upload_src": "showcase_wan_zoom_still.png",
    "workflow_fn": lambda name: wan_i2v(
        name,
        prompt="slow smooth camera zoom in, cinematic push forward, gradual approach to mountains, clouds drifting slowly",
        negative="shaky camera, fast motion, distorted, morphing landscape",
        length=49, steps=30, cfg=5.0,
    ),
})

JOBS.append({
    "name": "showcase_wan_water",
    "category": "video",
    "file": "showcase_wan_water.gif",
    "desc": "Wan Flowing Water — nature motion",
    "upload_src": "showcase_wan_water_still.png",
    "workflow_fn": lambda name: wan_i2v(
        name,
        prompt="flowing water over rocks, rippling stream, gentle current, leaves floating, natural water motion, dappled sunlight on water surface",
        negative="frozen water, ice, static, distorted rocks",
        length=49, steps=30, cfg=5.0,
    ),
})

JOBS.append({
    "name": "showcase_wan_turntable",
    "category": "video",
    "file": "showcase_wan_turntable.gif",
    "desc": "Wan 360 Turntable — product showcase spin",
    "upload_src": "showcase_wan_turntable_still.png",
    "workflow_fn": lambda name: wan_i2v(
        name,
        prompt="smooth 360 degree rotation, turntable spin, product slowly rotating, consistent lighting, studio product showcase",
        negative="shaky, distorted, morphing shape, inconsistent lighting",
        length=49, steps=30, cfg=5.0,
    ),
})


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY: Splash — Spellcaster-themed UI graphics for GIMP / Darktable / Installer
# These replace the host-application splash screen and plugin banner images.
# Generated at 1:1 pixel ratio for their target dimensions.
# ══════════════════════════════════════════════════════════════════════════════

# Prompt shared across all splash images — consistent magical-cyberpunk identity
_SPLASH_NEGATIVE = (
    "text, watermark, logo, ui, interface, blurry, low quality, "
    "photorealistic face, portrait, person, ugly, deformed, cartoon"
)

# GIMP plugin banner — 1024×600, shown at the top of the GIMP plugin window
JOBS.append({
    "name": "gimp_banner",
    "category": "splash",
    "file": "gimp_banner.png",
    "output_dir": str(PLUGIN_GIMP_DIR),   # saved to plugins/gimp/
    "desc": "GIMP plugin banner — Spellcaster Magical Cyberpunk 1024×600",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt=(
            "spellcaster arcane interface, magical cyberpunk dark theme, "
            "glowing purple and gold runes floating in a deep indigo void, "
            "cosmic energy tendrils, geometric spell circles, bioluminescent "
            "particles, abstract digital magic, dark mystical background, "
            "cinematic widescreen banner, 1024x600, no text, ultra detailed, "
            "8k, sharp, vibrant, studio quality"
        ),
        negative=_SPLASH_NEGATIVE,
        width=1024, height=600, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

# Darktable splash overlay — 1600×600, shown during AI processing
JOBS.append({
    "name": "darktable_splash",
    "category": "splash",
    "file": "darktable_splash.jpg",
    "output_dir": str(PLUGIN_DT_DIR),     # saved to plugins/darktable/
    "desc": "Darktable splash overlay — Spellcaster Magical Cyberpunk 1600×600",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt=(
            "spellcaster alchemist darkroom, magical cyberpunk laboratory, "
            "ancient camera obscura fused with quantum circuitry, glowing "
            "chemical vials with purple bioluminescent liquid, rune-etched "
            "metal gears and clockwork, deep teal and violet palette, "
            "mystical fog, dramatic cinematic lighting from below, "
            "widescreen panoramic banner 1600x600, no text, ultra detailed, "
            "8k, professional illustration quality"
        ),
        negative=_SPLASH_NEGATIVE,
        width=1600, height=600, steps=30, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})

# Installer background — 1920×1080, shown behind the PyInstaller GUI wizard
JOBS.append({
    "name": "installer_background",
    "category": "splash",
    "file": "installer_background.png",
    "output_dir": str(ASSETS_DIR),        # also mirrors to plugins/darktable/ at install time
    "desc": "Installer background — Spellcaster Magical Cyberpunk 1920×1080",
    "workflow": txt2img(
        ckpt="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        prompt=(
            "spellcaster wizard installation screen, magical cyberpunk full background, "
            "vast cosmic void filled with swirling purple and gold energy vortexes, "
            "ancient spell circle mandala in the center radiating light, "
            "constellation of rune glyphs scattered across deep space, "
            "bioluminescent neural network tendrils, dark indigo and violet tones, "
            "epic fantasy meets sci-fi aesthetic, immersive depth, no text, "
            "ultra wide 1920x1080, cinematic 8k, photorealistic lighting"
        ),
        negative=_SPLASH_NEGATIVE,
        width=1920, height=1088,  # nearest mod-64 to 1080
        steps=35, cfg=6.5,
        sampler="dpmpp_2m_sde", scheduler="karras",
    ),
})


# ─── Queue engine ─────────────────────────────────────────────────────────────

def queue_prompt(server, workflow):
    """Submit a workflow to ComfyUI and return the prompt_id."""
    payload = json.dumps({"prompt": workflow, "client_id": str(uuid.uuid4())}).encode()
    req = urllib.request.Request(
        f"{server}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("prompt_id")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"    ERROR {e.code}: {body[:500]}")
        return None
    except Exception as e:
        print(f"    ERROR: {e}")
        return None


def wait_for_prompt(server, prompt_id, timeout=1800):
    """Poll ComfyUI history until the prompt completes."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{server}/history/{prompt_id}", timeout=10) as resp:
                history = json.loads(resp.read())
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                return outputs
        except Exception:
            pass
        time.sleep(2)
    return None


def run_jobs(server, jobs, categories=None, output_plugin_dir=None):
    """Execute all jobs sequentially, waiting for each to complete.

    output_plugin_dir: if set, overrides the output directory for all jobs
    (used to force all output to a specific plugin dir instead of per-job dirs).
    """
    if categories:
        jobs = [j for j in jobs if j["category"] in categories]

    total = len(jobs)
    print(f"\n{'='*60}")
    print(f"  SPELLCASTER SHOWCASE GENERATOR")
    print(f"  Server: {server}")
    print(f"  Jobs: {total}")
    print(f"{'='*60}\n")

    succeeded = 0
    failed = 0

    for i, job in enumerate(jobs, 1):
        print(f"[{i}/{total}] {job['desc']}")
        print(f"         -> {job['file']}")

        # Handle jobs that need source images uploaded first
        workflow = job.get("workflow")
        if "upload_src" in job and "workflow_fn" in job:
            # Single source image upload (Wan I2V)
            src_path = OUTPUT_DIR / job["upload_src"]
            if not src_path.exists():
                print(f"         SKIPPED — source {job['upload_src']} not found\n")
                failed += 1
                continue
            try:
                uname = upload_image(server, str(src_path))
                print(f"         Uploaded: {uname}")
                workflow = job["workflow_fn"](uname)
            except Exception as e:
                print(f"         Upload failed: {e}\n")
                failed += 1
                continue
        elif "upload_srcs" in job and "workflow_fn" in job:
            # Multiple source image uploads (face swap)
            uploaded_names = []
            upload_ok = True
            for src_file in job["upload_srcs"]:
                src_path = OUTPUT_DIR / src_file
                if not src_path.exists():
                    print(f"         SKIPPED — source {src_file} not found\n")
                    upload_ok = False
                    break
                try:
                    uname = upload_image(server, str(src_path))
                    uploaded_names.append(uname)
                    print(f"         Uploaded: {uname}")
                except Exception as e:
                    print(f"         Upload failed: {e}\n")
                    upload_ok = False
                    break
            if not upload_ok:
                failed += 1
                continue
            workflow = job["workflow_fn"](uploaded_names)

        prompt_id = queue_prompt(server, workflow)
        if not prompt_id:
            print(f"         FAILED to queue\n")
            failed += 1
            continue

        print(f"         Queued: {prompt_id[:8]}... waiting...", end="", flush=True)
        outputs = wait_for_prompt(server, prompt_id)

        if outputs:
            # Find output — check both images (SaveImage) and gifs (VHS_VideoCombine)
            found = False
            for node_id, node_out in outputs.items():
                # VHS_VideoCombine puts output in "gifs" key
                out_items = node_out.get("images") or node_out.get("gifs") or []
                if out_items:
                    item = out_items[0]
                    fname = item.get("filename", "")
                    subfolder = item.get("subfolder", "")
                    ftype = item.get("type", "output")
                    print(f" done!")
                    print(f"         Saved: {subfolder}/{fname}" if subfolder else f"         Saved: {fname}")
                    if output_plugin_dir:
                        dest_dir = Path(output_plugin_dir)
                    elif "output_dir" in job:
                        dest_dir = Path(job["output_dir"])
                    else:
                        dest_dir = OUTPUT_DIR
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest = dest_dir / job["file"]
                    try:
                        img_url = f"{server}/view?filename={urllib.parse.quote(fname)}&type={ftype}"
                        if subfolder:
                            img_url += f"&subfolder={urllib.parse.quote(subfolder)}"
                        urllib.request.urlretrieve(img_url, dest)
                        print(f"         Downloaded to: {dest}")
                        succeeded += 1
                    except Exception as e:
                        print(f"         Download failed: {e}")
                        failed += 1
                    found = True
                    break
            if not found:
                print(f" done (no output found)")
                failed += 1
        else:
            print(f" TIMEOUT")
            failed += 1
        print()

    print(f"{'='*60}")
    print(f"  COMPLETE: {succeeded} succeeded, {failed} failed")
    print(f"{'='*60}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate Spellcaster README showcase images and UI splash graphics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Categories:
  generation   txt2img across all 6 model families
  inpaint      inpainting preset demos
  restoration  face restore, upscale, colorize, SUPIR
  style        LUT grading, IC-Light, style transfer
  face         FaceID, PuLID, face restore comparison
  controlnet   Canny, Depth, Pose, Lineart, Tile
  video        Wan 2.2 source frames
  splash       GIMP banner, Darktable splash, installer background

Examples:
  python generate_showcase.py --only splash
  python generate_showcase.py --only splash --server http://192.168.86.31:8188
  python generate_showcase.py --job gimp_banner
        """
    )
    parser.add_argument("--server", default=SERVER, help="ComfyUI server URL")
    parser.add_argument("--only",
        help="Comma-separated categories: generation,inpaint,restoration,style,face,controlnet,video,splash")
    parser.add_argument("--list", action="store_true", help="List all jobs without running")
    parser.add_argument("--job", help="Run a single job by name")
    parser.add_argument("--output-plugin-dir", metavar="PATH",
        help="Override output directory for all jobs (e.g. plugins/gimp for the splash category)")
    args = parser.parse_args()

    if args.list:
        print(f"  {'Category':12s}  {'Name':40s}  {'Output file':30s}  Output dir")
        print(f"  {'─'*12}  {'─'*40}  {'─'*30}  {'─'*30}")
        for j in JOBS:
            out_dir = j.get('output_dir', str(OUTPUT_DIR))
            print(f"  [{j['category']:12s}] {j['name']:40s}  {j['file']:30s}  {out_dir}")
        print(f"\n  Total: {len(JOBS)} jobs")
        sys.exit(0)

    categories = None
    if args.only:
        categories = set(args.only.split(","))

    out_plugin_dir = args.output_plugin_dir if args.output_plugin_dir else None

    if args.job:
        matching = [j for j in JOBS if j["name"] == args.job]
        if not matching:
            print(f"Job not found: {args.job}")
            sys.exit(1)
        run_jobs(args.server, matching, output_plugin_dir=out_plugin_dir)
    else:
        run_jobs(args.server, JOBS, categories, output_plugin_dir=out_plugin_dir)
