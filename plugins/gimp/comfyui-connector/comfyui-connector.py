#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ComfyUI Connector for GIMP 3
# Per-model img2img presets for every checkpoint on the server.
# Also supports txt2img, inpainting, and raw workflow paste.
#

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GimpUi, Gtk, GLib, Gio, GObject

import sys
import json
import os
import tempfile
import uuid
import time
import random
import struct
import zlib

import urllib.request
import urllib.parse
import urllib.error
import threading

def _load_config():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

COMFYUI_DEFAULT_URL = _load_config().get("server_url", "http://127.0.0.1:8188")

# ═══════════════════════════════════════════════════════════════════════════
#  MODEL PRESETS – one img2img workflow per checkpoint, tuned per arch
# ═══════════════════════════════════════════════════════════════════════════

MODEL_PRESETS = [
    # ── SD 1.5 ──────────────────────────────────────────────────────────
    {
        "label": "SD1.5 — Juggernaut Reborn (realistic)",
        "arch": "sd15",
        "ckpt": "SD-1.5\\juggernaut_reborn.safetensors",
        "width": 512, "height": 512,
        "steps": 25, "cfg": 7.0, "denoise": 0.62,
        "sampler": "dpmpp_2m", "scheduler": "karras",
        "prompt_hint": "photorealistic, highly detailed, sharp focus",
        "negative_hint": "cartoon, painting, blurry, deformed",
    },
    {
        "label": "SD1.5 — Realistic Vision v5.1 (photo)",
        "arch": "sd15",
        "ckpt": "SD-1.5\\realisticVisionV51_v51VAE.safetensors",
        "width": 512, "height": 512,
        "steps": 25, "cfg": 7.0, "denoise": 0.60,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "RAW photo, photorealistic, ultra detailed skin",
        "negative_hint": "(deformed, distorted, disfigured:1.3), blurry, bad anatomy",
    },
    {
        "label": "SD1.5 — Base v1.5 (general)",
        "arch": "sd15",
        "ckpt": "SD-1.5\\v1-5-pruned-emaonly.safetensors",
        "width": 512, "height": 512,
        "steps": 20, "cfg": 7.5, "denoise": 0.65,
        "sampler": "euler", "scheduler": "normal",
        "prompt_hint": "high quality, detailed",
        "negative_hint": "lowres, bad anatomy, worst quality",
    },
    # ── SDXL Anime ──────────────────────────────────────────────────────
    {
        "label": "SDXL — NoobAI-XL v1.1 (anime)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Anime\\NoobAI-XL-v1.1.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 6.0, "denoise": 0.60,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "masterpiece, best quality, anime style, detailed",
        "negative_hint": "worst quality, low quality, blurry, bad anatomy",
    },
    {
        "label": "SDXL — Nova Anime XL v1.70 (anime)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Anime\\novaAnimeXL_ilV170.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 6.5, "denoise": 0.60,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "anime, masterpiece, vivid colors, detailed illustration",
        "negative_hint": "worst quality, low quality, realistic, 3d",
    },
    {
        "label": "SDXL — Wai Illustrious SDXL (anime)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Anime\\waiIllustriousSDXL_v160-a5f5.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 5.5, "denoise": 0.58,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "masterpiece, best quality, very aesthetic, absurdres",
        "negative_hint": "worst quality, low quality, lowres, bad anatomy",
    },
    # ── SDXL Base ───────────────────────────────────────────────────────
    {
        "label": "SDXL — Albedo Base XL (versatile)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Base\\AlbedoBaseXL.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0, "denoise": 0.62,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "high quality, detailed, professional",
        "negative_hint": "lowres, bad anatomy, worst quality, blurry",
    },
    {
        "label": "SDXL — Base 1.0 (reference)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Base\\sd_xl_base_1.0.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "normal",
        "prompt_hint": "high quality, detailed",
        "negative_hint": "lowres, worst quality, blurry",
    },
    # ── SDXL Cartoon / 3D ──────────────────────────────────────────────
    {
        "label": "SDXL — Modern Disney XL v3 (cartoon/3D)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Cartoon-3D\\modernDisneyXL_v3.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 7.0, "denoise": 0.60,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "disney style, 3d render, cartoon, vibrant colors, cinematic lighting",
        "negative_hint": "photorealistic, blurry, low quality, deformed",
    },
    {
        "label": "SDXL — Nova Cartoon XL v6 (cartoon/3D)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Cartoon-3D\\novaCartoonXL_v60.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 7.0, "denoise": 0.58,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "cartoon style, vibrant, illustration, detailed",
        "negative_hint": "photorealistic, blurry, deformed, low quality",
    },
    # ── SDXL Realistic ─────────────────────────────────────────────────
    {
        "label": "SDXL — CyberRealistic Pony v1.6 (realistic)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\cyberrealisticPony_v160.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 6.5, "denoise": 0.58,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "score_9, score_8_up, photorealistic, ultra detailed, sharp",
        "negative_hint": "score_4, score_3, blurry, cartoon, deformed",
    },
    {
        "label": "SDXL — JibMix Realistic XL v1.8 (photo)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\jibMixRealisticXL_v180SkinSupreme.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 6.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "photorealistic, professional photography, natural skin, sharp focus",
        "negative_hint": "painting, cartoon, deformed, blurry, overexposed",
    },
    {
        "label": "SDXL — Juggernaut XL Ragnarok (realistic)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\juggernautXL_ragnarok.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 6.0, "denoise": 0.58,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "photorealistic, cinematic, highly detailed, professional",
        "negative_hint": "cartoon, anime, blurry, deformed, low quality",
    },
    {
        "label": "SDXL — Juggernaut XL v9 (photo)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 6.5, "denoise": 0.58,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "photorealistic, cinematic lighting, sharp focus, professional",
        "negative_hint": "cartoon, painting, deformed, blurry, worst quality",
    },
    {
        "label": "SDXL — ZavyChroma XL v10 (realistic)",
        "arch": "sdxl",
        "ckpt": "SDXL\\Realistic\\zavychromaxl_v100.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 6.5, "denoise": 0.60,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
        "prompt_hint": "photorealistic, vivid, cinematic, highly detailed",
        "negative_hint": "cartoon, blurry, deformed, worst quality",
    },
    # ── Illustrious ────────────────────────────────────────────────────
    {
        "label": "Illustrious — IlustReal v5 (semi-real)",
        "arch": "sdxl",
        "ckpt": "Illustrious\\ilustreal_v50VAE.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 5.0, "denoise": 0.58,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "masterpiece, best quality, very aesthetic, semi-realistic",
        "negative_hint": "worst quality, low quality, blurry, bad anatomy",
    },
    {
        "label": "Illustrious — Sloppy Messy Mix v1 (artistic)",
        "arch": "sdxl",
        "ckpt": "Illustrious\\sloppyMessyMix_sloppyMessyMixV1.safetensors",
        "width": 1024, "height": 1024,
        "steps": 28, "cfg": 5.5, "denoise": 0.60,
        "sampler": "euler_ancestral", "scheduler": "normal",
        "prompt_hint": "masterpiece, best quality, painterly, expressive",
        "negative_hint": "worst quality, low quality, blurry",
    },
    # ── Other ──────────────────────────────────────────────────────────
    {
        "label": "ZIT — GonzaloMo Zpop v3 AIO",
        "arch": "zit",
        "ckpt": "ZIT\\gonzalomoZpop_v30AIO.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0, "denoise": 0.60,
        "sampler": "euler", "scheduler": "normal",
        "prompt_hint": "high quality, detailed",
        "negative_hint": "worst quality, low quality, blurry",
    },
]

# ═══════════════════════════════════════════════════════════════════════════
#  Architecture → compatible LoRA folder prefixes
# ═══════════════════════════════════════════════════════════════════════════

ARCH_LORA_PREFIXES = {
    # SD 1.5 – no dedicated LoRA folders currently; show none
    "sd15":       [],
    # SDXL family (base, anime, realistic, cartoon, pony, illustrious)
    "sdxl":       ["SDXL\\", "Illustrious\\", "Illustrious-Pony\\", "Pony\\"],
    # Z-Image Turbo ecosystem
    "zit":        ["Z-Image-Turbo\\"],
    # Flux 2 Klein (for Klein dialogs)
    "flux2klein": ["Flux-2-Klein\\"],
    # Flux 1 Dev (not currently a preset, but for completeness)
    "flux1dev":   ["Flux-1-Dev\\"],
}


# ═══════════════════════════════════════════════════════════════════════════
#  Inpaint Refinement Presets — body-part-specific prompts, LoRAs, settings
# ═══════════════════════════════════════════════════════════════════════════
# Each entry:  label, prompt, negative, denoise, cfg_boost (added to model cfg),
#              steps_override (None = use model default),
#              loras: dict of arch → [(lora_path, model_str, clip_str), ...]
# The first LoRA in the list is the primary recommendation; extras are stacked.

INPAINT_REFINEMENTS = [
    {
        "label": "(none — manual prompt)",
        "prompt": "",
        "negative": "",
        "denoise": None,
        "cfg_boost": 0,
        "steps_override": None,
        "loras": {},
    },
    # ── Hands & Fingers ────────────────────────────────────────────────
    {
        "label": "Fix Hands / Fingers",
        "prompt": "perfect hands, five fingers on each hand, correct finger count, natural hand pose, "
                  "realistic hand anatomy, detailed knuckles and nails, well-proportioned fingers",
        "negative": "bad hands, extra fingers, fewer fingers, fused fingers, mutated hands, "
                    "deformed fingers, missing fingers, ugly hands, extra digit, too many fingers",
        "denoise": 0.78,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Body\\HandFineTuning_XL.safetensors", 0.85, 0.85),
                           ("SDXL\\Body\\hand 5.5.safetensors", 0.6, 0.6)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Eyes ───────────────────────────────────────────────────────────
    {
        "label": "Fix Eyes / Iris Detail",
        "prompt": "beautiful detailed eyes, perfect symmetrical eyes, clear sharp iris, "
                  "realistic eye reflections, natural eye color, correct eye anatomy, "
                  "detailed eyelashes, properly aligned pupils",
        "negative": "asymmetric eyes, misaligned eyes, deformed iris, bad eyes, "
                    "cross-eyed, glowing eyes, empty eyes, dead eyes, uneven eyes",
        "denoise": 0.65,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Eyes_High_Definition-000007.safetensors", 0.8, 0.8)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Face / Portrait ───────────────────────────────────────────────
    {
        "label": "Refine Face / Portrait",
        "prompt": "beautiful face, perfect facial features, natural skin texture, "
                  "detailed facial structure, clear complexion, realistic portrait, "
                  "well-defined jawline, natural expression, symmetrical face",
        "negative": "deformed face, ugly face, asymmetric face, blurry face, "
                    "distorted features, bad proportions, uncanny valley, disfigured",
        "denoise": 0.62,
        "cfg_boost": 0.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\BFS_head_v1_flux-klein_9b_rank128.safetensors", 0.8, 0.8)],
        },
    },
    # ── Teeth / Mouth ─────────────────────────────────────────────────
    {
        "label": "Fix Teeth / Mouth",
        "prompt": "perfect teeth, natural white teeth, correct dental anatomy, "
                  "properly aligned teeth, realistic mouth, natural lips, "
                  "healthy gums, natural smile",
        "negative": "bad teeth, missing teeth, extra teeth, deformed mouth, "
                    "broken teeth, ugly teeth, distorted jaw, melted lips",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Teefs-000007.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Skin Texture / Detail ─────────────────────────────────────────
    {
        "label": "Enhance Skin Texture",
        "prompt": "detailed skin texture, realistic skin pores, natural skin surface, "
                  "subsurface scattering, high definition skin, photorealistic skin detail",
        "negative": "plastic skin, smooth plastic, waxy skin, artificial skin, "
                    "airbrushed, oversmoothed, blurry skin, painted skin",
        "denoise": 0.45,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\skin texture style v4.safetensors", 0.75, 0.75),
                           ("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.7, 0.7)],
        },
    },
    # ── Hair ──────────────────────────────────────────────────────────
    {
        "label": "Fix Hair / Hairstyle",
        "prompt": "beautiful detailed hair, natural hair strands, realistic hair texture, "
                  "individual hair strands visible, shiny healthy hair, well-groomed hair, "
                  "natural hair flow, volumetric hair",
        "negative": "bad hair, plastic hair, merged hair clumps, bald patches, "
                    "unnatural hair, wig-like, stiff hair, flat hair, no hair detail",
        "denoise": 0.68,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.65, 0.65)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.6, 0.6)],
        },
    },
    # ── Feet / Toes ───────────────────────────────────────────────────
    {
        "label": "Fix Feet / Toes",
        "prompt": "perfect feet, five toes on each foot, correct toe count, "
                  "natural foot anatomy, detailed toes and toenails, realistic feet, "
                  "well-proportioned feet",
        "negative": "bad feet, extra toes, fused toes, deformed feet, "
                    "missing toes, ugly feet, malformed toes, mutated feet",
        "denoise": 0.75,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\realistic\\feet v3.safetensors", 0.8, 0.8)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Body Anatomy / Proportions ────────────────────────────────────
    {
        "label": "Fix Body Anatomy",
        "prompt": "correct human anatomy, natural body proportions, realistic body structure, "
                  "proper limb length, natural muscle definition, anatomically correct, "
                  "well-proportioned body",
        "negative": "bad anatomy, extra limbs, missing limbs, deformed body, "
                    "disproportionate, mutated, fused limbs, twisted torso, broken anatomy",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Body\\HandFineTuning_XL.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\Sliders\\klein_slider_anatomy_9B_v1.5.safetensors", 0.8, 0.8)],
        },
    },
    # ── Ears ──────────────────────────────────────────────────────────
    {
        "label": "Fix Ears",
        "prompt": "perfect ears, natural ear shape, detailed ear anatomy, "
                  "realistic ear, symmetrical ears, properly attached ears, correct ear placement",
        "negative": "deformed ears, missing ears, extra ears, melted ears, "
                    "oversized ears, badly shaped ears, asymmetric ears",
        "denoise": 0.65,
        "cfg_boost": 0.5,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.6, 0.6)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Nose ──────────────────────────────────────────────────────────
    {
        "label": "Fix Nose",
        "prompt": "perfect nose, natural nose shape, detailed nostril anatomy, "
                  "realistic nose, well-defined nose bridge, natural nose proportions, "
                  "symmetrical nose",
        "negative": "deformed nose, crooked nose, melted nose, flat nose, "
                    "missing nose, blob nose, badly shaped nose",
        "denoise": 0.62,
        "cfg_boost": 0.5,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Neck / Shoulders ──────────────────────────────────────────────
    {
        "label": "Fix Neck / Shoulders",
        "prompt": "natural neck, correct neck proportions, realistic shoulder anatomy, "
                  "proper collarbone detail, natural neck-to-shoulder transition, "
                  "well-defined shoulders",
        "negative": "long neck, broken neck, deformed shoulders, missing neck, "
                    "twisted neck, extra shoulders, giraffe neck, merged neck",
        "denoise": 0.68,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\Sliders\\klein_slider_anatomy_9B_v1.5.safetensors", 0.6, 0.6)],
        },
    },
    # ── Clothing / Fabric ─────────────────────────────────────────────
    {
        "label": "Fix Clothing / Fabric",
        "prompt": "detailed clothing, realistic fabric texture, natural cloth folds, "
                  "proper garment draping, wrinkle detail, high quality textile, "
                  "correct clothing anatomy",
        "negative": "deformed clothing, melted fabric, missing clothing parts, "
                    "bad cloth physics, floating clothing, clipping, merged clothing",
        "denoise": 0.65,
        "cfg_boost": 0.5,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\FTextureTransfer_F29B_V2.1.safetensors", 0.6, 0.6)],
        },
    },
    # ── Background / Scene ────────────────────────────────────────────
    {
        "label": "Fix Background / Scene",
        "prompt": "detailed background, realistic environment, natural scenery, "
                  "high quality background, sharp background detail, "
                  "consistent perspective, proper lighting",
        "negative": "blurry background, distorted background, bad perspective, "
                    "floating objects, impossible architecture, warped scene",
        "denoise": 0.72,
        "cfg_boost": 0.5,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.6, 0.6)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
        },
    },
    # ── General Detail Enhancer ───────────────────────────────────────
    {
        "label": "Sharpen / Add Detail",
        "prompt": "ultra sharp, highly detailed, intricate details, "
                  "enhanced textures, crisp edges, high definition, 8k quality",
        "negative": "blurry, soft, low detail, smooth, flat, low resolution, "
                    "out of focus, motion blur",
        "denoise": 0.40,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.8, 0.8),
                           ("SDXL\\Detail\\rdtdrp.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.8, 0.8)],
        },
    },
    # ── Realism Boost ─────────────────────────────────────────────────
    {
        "label": "Boost Realism / Photo Quality",
        "prompt": "photorealistic, RAW photo, DSLR quality, natural lighting, "
                  "realistic texture, professional photography, film grain, "
                  "natural color grading",
        "negative": "cartoon, anime, painting, illustration, digital art, "
                    "artificial, fake, CGI, unrealistic, oversaturated",
        "denoise": 0.50,
        "cfg_boost": 0.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.65, 0.65),
                           ("SDXL\\Detail\\skin texture style v4.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\ultra_real_v2.safetensors", 0.7, 0.7)],
        },
    },
    # ── Remove Artifacts / Clean Up ───────────────────────────────────
    {
        "label": "Remove Artifacts / Clean Up",
        "prompt": "clean image, artifact free, smooth transition, natural appearance, "
                  "correct details, consistent style, seamless",
        "negative": "artifacts, glitch, noise, compression artifacts, "
                    "banding, jpeg artifacts, posterization, pixelation",
        "denoise": 0.55,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.5, 0.5)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\FK4B_Image_Repair_V1.safetensors", 0.8, 0.8)],
        },
    },

    # ═══════════════════════════════════════════════════════════════════
    #  CREATIVE / EFFECT RENDERS
    # ═══════════════════════════════════════════════════════════════════

    # ── Oily / Wet Skin ───────────────────────────────────────────────
    {
        "label": "✦ Oily / Wet Skin Effect",
        "prompt": "oily skin, wet skin, glistening skin, shiny skin, dewy skin, "
                  "wet body, skin highlights, sweat, glossy complexion, moisture on skin",
        "negative": "dry skin, matte skin, powder, flat lighting, dull skin",
        "denoise": 0.55,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Oily skin style xl v1.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Effect\\OiledSkin_Zit_Turbo_V1.safetensors", 0.85, 0.85)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Sweat / Exertion ──────────────────────────────────────────────
    {
        "label": "✦ Sweat / Exertion Effect",
        "prompt": "sweaty skin, beads of sweat, perspiration, glistening with sweat, "
                  "exertion, post-workout, wet with sweat, sweat dripping, athletic",
        "negative": "dry skin, clean, powder, matte, cold, frozen",
        "denoise": 0.55,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Sweating my balls of mate.safetensors", 0.8, 0.8),
                           ("SDXL\\Oily skin style xl v1.safetensors", 0.4, 0.4)],
            "zit":        [("Z-Image-Turbo\\Effect\\OiledSkin_Zit_Turbo_V1.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Water Droplets ────────────────────────────────────────────────
    {
        "label": "✦ Water Droplets Effect",
        "prompt": "water droplets on skin, water drops, dew drops, rain drops, "
                  "wet surface, water beading, crystal clear droplets, morning dew, "
                  "water splash, droplet reflections",
        "negative": "dry, dusty, matte, powder, no water, arid",
        "denoise": 0.58,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Oily skin style xl v1.safetensors", 0.5, 0.5)],
            "zit":        [("Z-Image-Turbo\\Effect\\water_droplet_effect_zit_v1.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Chrome / Metallic Skin ────────────────────────────────────────
    {
        "label": "✦ Chrome / Metallic Skin",
        "prompt": "chrome skin, metallic skin, liquid metal surface, silver chrome body, "
                  "reflective metallic, mercury skin, shiny metal texture, "
                  "polished chrome, mirror-like skin",
        "negative": "matte, natural skin, realistic skin, dull, flat, organic, flesh tone",
        "denoise": 0.75,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\MetallicGoldSilver_skinbody_paint-000019.safetensors", 0.9, 0.9)],
            "zit":        [("Z-Image-Turbo\\Effect\\93PXB5SENBFN8NEYSRYZA1DVX0-Chrome skin.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Cyborg / Robot Parts ──────────────────────────────────────────
    {
        "label": "✦ Cyborg / Robot Parts",
        "prompt": "cyborg, mechanical parts, robotic body, cybernetic implants, "
                  "exposed machinery, glowing circuits, metal plates, bionic, "
                  "android, tech implants, wires under skin, LED accents",
        "negative": "fully human, natural, organic only, no technology, medieval, rustic",
        "denoise": 0.78,
        "cfg_boost": 1.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Concept\\ARobotGirls_Concept-12.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Effect\\Z-cyborg.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Gothic Dark Fantasy ───────────────────────────────────────────
    {
        "label": "✦ Gothic Dark Fantasy",
        "prompt": "gothic dark fantasy, ethereal gothic elegance, dark atmosphere, "
                  "moody shadows, dramatic dark lighting, mystical, dark beauty, "
                  "occult aesthetic, dark romantic, candlelight, velvet darkness",
        "negative": "bright, cheerful, colorful, sunny, cartoon, daytime, flat lighting",
        "denoise": 0.68,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\Ethereal_Gothic_Elegance.safetensors", 0.85, 0.85),
                           ("SDXL\\Style\\dark.safetensors", 0.5, 0.5)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Chiaroscuro Lighting ──────────────────────────────────────────
    {
        "label": "✦ Chiaroscuro / Dramatic Lighting",
        "prompt": "chiaroscuro lighting, dramatic light and shadow, Rembrandt lighting, "
                  "high contrast, deep shadows, single light source, volumetric light, "
                  "film noir lighting, baroque lighting, tenebrism",
        "negative": "flat lighting, even lighting, overexposed, no shadows, "
                    "bright everywhere, flash photography, washed out",
        "denoise": 0.62,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\Chiaroscuro  film style pony v1.safetensors", 0.85, 0.85),
                           ("SDXL\\Slider\\Dramatic Lighting Slider.safetensors", 0.6, 0.6)],
            "zit":        [("Z-Image-Turbo\\Style\\zy_CinematicShot_zit.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Cinematic Film Look ───────────────────────────────────────────
    {
        "label": "✦ Cinematic Film Look",
        "prompt": "cinematic photography, film grain, anamorphic lens, "
                  "cinematic color grading, movie still, depth of field, "
                  "professional cinematography, 35mm film, warm color palette",
        "negative": "amateur, smartphone, flat, digital noise, harsh flash, "
                    "oversaturated, snapshot, selfie",
        "denoise": 0.55,
        "cfg_boost": 0.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\Cinematic Photography Style pony v1.safetensors", 0.8, 0.8),
                           ("SDXL\\Style\\epiCPhotoXL-Derp2.safetensors", 0.4, 0.4)],
            "zit":        [("Z-Image-Turbo\\Style\\zy_CinematicShot_zit.safetensors", 0.85, 0.85)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Raw Camera / DSLR ─────────────────────────────────────────────
    {
        "label": "✦ Raw Camera / DSLR Photo",
        "prompt": "RAW photo, DSLR, professional camera, natural lighting, "
                  "shallow depth of field, bokeh, lens flare, sharp focus, "
                  "unedited photograph, authentic colors, film emulation",
        "negative": "painting, illustration, digital art, CGI, airbrushed, "
                    "overprocessed, HDR, cartoon, anime",
        "denoise": 0.50,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Style\\RawCam_250_v1.safetensors", 0.8, 0.8),
                           ("SDXL\\Style\\epicNewPhoto.safetensors", 0.4, 0.4)],
            "zit":        [("Z-Image-Turbo\\Style\\SonyAlpha_ZImage.safetensors", 0.8, 0.8)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── 35mm Telephoto Lens ───────────────────────────────────────────
    {
        "label": "✦ Telephoto / 600mm Lens",
        "prompt": "600mm telephoto lens, extreme bokeh, compressed perspective, "
                  "subject isolation, creamy background blur, long focal length, "
                  "professional sports photography, wildlife photography style",
        "negative": "wide angle, fisheye, everything in focus, deep DOF, "
                    "distortion, flat, no blur",
        "denoise": 0.52,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Style\\epiCPhotoXL-Derp2.safetensors", 0.6, 0.6)],
            "zit":        [("Z-Image-Turbo\\Style\\600mm_Lens-V2_TriggerIs_600mm.safetensors", 0.9, 0.9)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Ghibli / Anime Style ─────────────────────────────────────────
    {
        "label": "✦ Ghibli / Anime Painterly",
        "prompt": "studio ghibli style, anime painting, hand-drawn animation, "
                  "soft watercolor, whimsical, miyazaki, painterly anime, "
                  "cel shading, warm natural palette, gentle atmosphere",
        "negative": "photorealistic, 3d render, CGI, harsh shadows, "
                    "sharp edges, dark, horror, gritty",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Style\\ghibli_last.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Style\\ZiTD3tailed4nime.safetensors", 0.8, 0.8)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── FaeTastic Fantasy ─────────────────────────────────────────────
    {
        "label": "✦ Fairy Tale / Fantasy Art",
        "prompt": "fairy tale illustration, fantasy art, magical atmosphere, "
                  "ethereal glow, enchanted, whimsical fantasy, storybook illustration, "
                  "dreamy, luminous, fantasy landscape, magical particles",
        "negative": "realistic, modern, urban, gritty, dark, horror, mundane, "
                    "photographic, plain",
        "denoise": 0.70,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Style\\SDXLFaeTastic2400.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Style\\z-image-illustria-01.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── 80s Fantasy Movie ─────────────────────────────────────────────
    {
        "label": "✦ 80s Fantasy Movie Style",
        "prompt": "80s fantasy movie, retro fantasy, practical effects, "
                  "1980s film aesthetic, sword and sorcery, VHS quality, "
                  "vintage fantasy, Conan the Barbarian style, matte painting background, "
                  "old school special effects, film grain, warm tones",
        "negative": "modern, clean digital, CGI, photorealistic, contemporary, "
                    "minimalist, sleek",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Glitch / Digital Error ────────────────────────────────────────
    {
        "label": "✦ Glitch / Digital Error",
        "prompt": "glitch art, digital corruption, pixel sorting, data moshing, "
                  "RGB split, scan lines, corrupted image, VHS glitch, "
                  "digital artifact aesthetic, broken data, cyberpunk glitch",
        "negative": "clean, perfect, smooth, natural, analog, traditional, "
                    "high quality, no artifacts",
        "denoise": 0.70,
        "cfg_boost": 1.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Concept\\err0rFv1.6.safetensors", 0.85, 0.85)],
            "zit":        [("Z-Image-Turbo\\Effect\\EFFECTSp001_zit.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Slime / Wet & Messy ───────────────────────────────────────────
    {
        "label": "✦ Slime / Wet & Messy (WAM)",
        "prompt": "covered in slime, green slime, gunge, wet and messy, "
                  "dripping slime, splattered, gooey, splosh, viscous liquid, "
                  "slime dripping from body",
        "negative": "clean, dry, pristine, neat, tidy, powder, matte",
        "denoise": 0.72,
        "cfg_boost": 1.0,
        "steps_override": 28,
        "loras": {
            "sdxl":       [("SDXL\\Green_Slime_WAM_Gunge_Wet_and_Messy_Sploshing_Splosh.safetensors", 0.9, 0.9)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Freckles / Skin Detail ────────────────────────────────────────
    {
        "label": "✦ Add Freckles",
        "prompt": "freckles, natural freckles, sun-kissed freckles across cheeks, "
                  "detailed skin with freckles, cute freckle pattern, "
                  "beauty marks, speckled skin, natural imperfections",
        "negative": "airbrushed, smooth porcelain skin, no marks, plastic skin, "
                    "flawless, oversmoothed",
        "denoise": 0.48,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Detail\\skin texture style v4.safetensors", 0.6, 0.6)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Hyperdetailed Realism ─────────────────────────────────────────
    {
        "label": "✦ Hyperdetailed Realism",
        "prompt": "hyperdetailed, hyperrealistic, extreme detail, micro details, "
                  "pore-level detail, ultra sharp focus, photographic perfection, "
                  "8k resolution, extremely detailed textures",
        "negative": "soft, blurry, painterly, illustration, low detail, "
                    "flat, smooth, anime, cartoon",
        "denoise": 0.52,
        "cfg_boost": 1.0,
        "steps_override": 35,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\HyperdetailedRealismMJ7Pony.safetensors", 0.8, 0.8),
                           ("SDXL\\Detail\\RealSkin_xxXL_v1.safetensors", 0.5, 0.5)],
            "zit":        [("Z-Image-Turbo\\Style\\Z-Image-Professional_Photographer_3500.safetensors", 0.7, 0.7)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\K9bSR3al.safetensors", 0.7, 0.7),
                           ("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
        },
    },
    # ── 3D CG / Hi-Poly Render ────────────────────────────────────────
    {
        "label": "✦ 3D CG / Hi-Poly Render",
        "prompt": "3d cg render, hi-poly 3d model, subsurface scattering, "
                  "ray tracing, physically based rendering, unreal engine quality, "
                  "octane render, smooth 3d surface, studio lighting 3d",
        "negative": "2d, flat, painting, sketch, hand-drawn, low poly, "
                    "pixel art, traditional art, photograph",
        "denoise": 0.68,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\polyhedron_all_sdxl-000004.safetensors", 0.7, 0.7)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\hipoly_3dcg_v7-epoch-000012.safetensors", 0.85, 0.85)],
        },
    },
    # ── Amateur / Candid Photo ────────────────────────────────────────
    {
        "label": "✦ Amateur / Candid Photo",
        "prompt": "amateur photo, candid shot, casual snapshot, natural pose, "
                  "real photography, unposed, everyday life, authentic, "
                  "slightly imperfect, natural lighting, no filter",
        "negative": "professional, studio, posed, perfect, airbrushed, "
                    "magazine, retouched, glamour, high fashion",
        "denoise": 0.55,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Style\\zy_AmateurStyle_v2.safetensors", 0.85, 0.85)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Alien / Extraterrestrial ──────────────────────────────────────
    {
        "label": "✦ Alien / Extraterrestrial",
        "prompt": "alien, extraterrestrial being, alien skin texture, otherworldly, "
                  "sci-fi alien, non-human features, bioluminescent, "
                  "exotic alien anatomy, space creature, xenomorph-inspired",
        "negative": "human, normal, mundane, realistic human, everyday, "
                    "natural, earthly",
        "denoise": 0.78,
        "cfg_boost": 1.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Concept\\Aliens_AILF_SDXL.safetensors", 0.85, 0.85)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Shadow Circuit / Tech Pattern ─────────────────────────────────
    {
        "label": "✦ Circuit / Tech Pattern",
        "prompt": "circuit board pattern, tech circuits on skin, glowing circuit lines, "
                  "electronic pathways, neon traces, cybernetic tattoo, "
                  "tech vein pattern, digital circuitry, Tron-like lines",
        "negative": "organic, natural, no technology, plain, simple, "
                    "traditional tattoo, medieval",
        "denoise": 0.68,
        "cfg_boost": 1.0,
        "steps_override": 28,
        "loras": {
            "sdxl":       [],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Glow / Ethereal Light ─────────────────────────────────────────
    {
        "label": "✦ Glow / Ethereal Light",
        "prompt": "ethereal glow, soft radiant light, inner glow, angelic light, "
                  "bioluminescent, aura, glowing skin, divine light, "
                  "warm ethereal illumination, light particles",
        "negative": "dark, shadowy, gloomy, flat lighting, harsh shadows, "
                    "no glow, matte, dull",
        "denoise": 0.58,
        "cfg_boost": 0.5,
        "steps_override": 28,
        "loras": {
            "sdxl":       [],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\Sliders\\klein_slider_glow.safetensors", 0.8, 0.8)],
        },
    },
    # ── Tentacles / Lovecraftian ──────────────────────────────────────
    {
        "label": "✦ Tentacles / Lovecraftian",
        "prompt": "tentacles, eldritch tentacles, lovecraftian horror, "
                  "organic tentacle growth, writhing tentacles, cosmic horror, "
                  "cthulhu inspired, deep sea creature, tentacle embrace",
        "negative": "clean, normal, mundane, no tentacles, ordinary, "
                    "cheerful, bright, simple",
        "denoise": 0.78,
        "cfg_boost": 1.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [],
            "zit":        [("Z-Image-Turbo\\Effect\\Tentacledv1.safetensors", 0.85, 0.85)],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\Tentacle v2_000002000.safetensors", 0.85, 0.85)],
        },
    },
    # ── Spaceship / Sci-Fi Vehicle ────────────────────────────────────
    {
        "label": "✦ Spaceship / Sci-Fi Vehicle",
        "prompt": "spaceship, sci-fi vehicle, futuristic spacecraft, "
                  "space cruiser, starship, detailed hull plating, "
                  "engine glow, space background, concept art spacecraft",
        "negative": "medieval, fantasy, modern car, realistic, natural, "
                    "low quality, blurry",
        "denoise": 0.75,
        "cfg_boost": 1.0,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Concept\\Space_ship_concept.safetensors", 0.85, 0.85)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [],
        },
    },
    # ── Portrait Upscale / Enhancement ────────────────────────────────
    {
        "label": "✦ Portrait Enhancement (Klein)",
        "prompt": "beautiful portrait, enhanced facial features, crisp details, "
                  "professional portrait photography, catchlights in eyes, "
                  "natural skin, high resolution face",
        "negative": "blurry, soft, low resolution, artifacts, distorted, "
                    "plastic, airbrushed, flat",
        "denoise": 0.42,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("Illustrious-Pony\\StS_PonyXL_Detail_Slider_v1.4_iteration_3.safetensors", 0.7, 0.7)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\upscale_portrait_9bklein.safetensors", 0.8, 0.8),
                           ("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.4, 0.4)],
        },
    },
    # ── Color Tone / Grading ──────────────────────────────────────────
    {
        "label": "✦ Color Tone / Grading (Klein)",
        "prompt": "color graded, beautiful color palette, professional color correction, "
                  "cinematic color tone, warm highlights cool shadows, "
                  "complementary colors, mood lighting",
        "negative": "flat colors, oversaturated, undersaturated, grey, "
                    "washed out, neon, ugly colors",
        "denoise": 0.40,
        "cfg_boost": 0.0,
        "steps_override": 25,
        "loras": {
            "sdxl":       [("SDXL\\Style\\sd_xl_offset_example-lora_1.0.safetensors", 0.6, 0.6)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\Sliders\\ColorTone_Standard.safetensors", 0.7, 0.7)],
        },
    },
    # ── Anything to Realistic (Klein) ─────────────────────────────────
    {
        "label": "✦ Anything → Realistic (Klein)",
        "prompt": "photorealistic, real person, natural skin, realistic features, "
                  "real photograph, authentic human, natural imperfections, "
                  "professional portrait, real-life",
        "negative": "anime, cartoon, illustration, painting, 3d render, "
                    "artificial, CGI, plastic, doll-like",
        "denoise": 0.65,
        "cfg_boost": 0.5,
        "steps_override": 30,
        "loras": {
            "sdxl":       [("SDXL\\Style\\epiCRealnessRC1.safetensors", 0.8, 0.8)],
            "zit":        [],
            "sd15":       [],
            "flux2klein": [("Flux-2-Klein\\Character\\Flux2Klein_AnythingtoRealCharacters.safetensors", 0.85, 0.85),
                           ("Flux-2-Klein\\K9bSR3al.safetensors", 0.5, 0.5)],
        },
    },
]


def _filter_loras_for_arch(all_loras, arch):
    """Return only LoRAs whose full path starts with a compatible prefix."""
    prefixes = ARCH_LORA_PREFIXES.get(arch, [])
    if not prefixes:
        return []
    return [l for l in all_loras if any(l.startswith(p) or l == p.rstrip("\\") for p in prefixes)]


# ═══════════════════════════════════════════════════════════════════════════
#  HTTP helpers – pure urllib, no pip installs needed
# ═══════════════════════════════════════════════════════════════════════════

def _fetch_loras(server):
    """Fetch available LoRA names from ComfyUI server."""
    try:
        info = _api_get(server, "/object_info/LoraLoader")
        return info["LoraLoader"]["input"]["required"]["lora_name"][0]
    except Exception:
        return []

def _fetch_reactor_models(server):
    """Fetch available ReActor swap_model and face_restore_model lists from the server."""
    try:
        info = _api_get(server, "/object_info/ReActorFaceSwap")
        inputs = info["ReActorFaceSwap"]["input"]["required"]
        swap = inputs.get("swap_model", [[]])[0]
        restore = inputs.get("face_restore_model", [[]])[0]
        return swap, restore
    except Exception:
        return [], []

def _fetch_face_models(server):
    """Fetch saved face model names from ReActorLoadFaceModel on the server."""
    try:
        info = _api_get(server, "/object_info/ReActorLoadFaceModel")
        models = info["ReActorLoadFaceModel"]["input"]["required"]["face_model"][0]
        return [m for m in models if m != "none"]
    except Exception:
        return []

def _fetch_wan_video_models(server):
    """Fetch available diffusion models from WanVideoModelLoader."""
    try:
        info = _api_get(server, "/object_info/WanVideoModelLoader")
        return info["WanVideoModelLoader"]["input"]["required"]["model"][0]
    except Exception:
        return []

def _fetch_wan_video_loras(server):
    """Fetch Wan LoRAs from the server (via LoraLoaderModelOnly).

    Returns only LoRAs whose path starts with 'Wan\\' — i.e. those
    in the dedicated loras/Wan/ subfolder on the ComfyUI server.
    """
    try:
        info = _api_get(server, "/object_info/LoraLoaderModelOnly")
        all_loras = info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0]
        return [l for l in all_loras if l.startswith("Wan\\") or l.startswith("Wan/")]
    except Exception:
        return []

def _fetch_wan_video_vaes(server):
    """Fetch available VAE models from WanVideoVAELoader."""
    try:
        info = _api_get(server, "/object_info/WanVideoVAELoader")
        return info["WanVideoVAELoader"]["input"]["required"]["model_name"][0]
    except Exception:
        return []

def _fetch_clip_vision_models(server):
    """Fetch available CLIP vision models."""
    try:
        info = _api_get(server, "/object_info/CLIPVisionLoader")
        return info["CLIPVisionLoader"]["input"]["required"]["clip_name"][0]
    except Exception:
        return []

def _fetch_mtb_analysis_models(server):
    """Fetch face analysis models from mtb Face Swap."""
    try:
        info = _api_get(server, "/object_info/Load Face Analysis Model (mtb)")
        return info["Load Face Analysis Model (mtb)"]["input"]["required"]["faceswap_model"][0]
    except Exception:
        return ["antelopev2", "buffalo_l"]

def _fetch_mtb_swap_models(server):
    """Fetch face swap models from mtb."""
    try:
        info = _api_get(server, "/object_info/Load Face Swap Model (mtb)")
        return info["Load Face Swap Model (mtb)"]["input"]["required"]["faceswap_model"][0]
    except Exception:
        return ["inswapper_128.onnx"]

def _fetch_checkpoints(server):
    """Fetch available checkpoints from the server."""
    try:
        info = _api_get(server, "/object_info/CheckpointLoaderSimple")
        return info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except Exception:
        return []

def _fetch_faceid_presets(server):
    """Fetch IPAdapter FaceID preset names."""
    try:
        info = _api_get(server, "/object_info/IPAdapterUnifiedLoaderFaceID")
        return info["IPAdapterUnifiedLoaderFaceID"]["input"]["required"]["preset"][0]
    except Exception:
        return ["FACEID", "FACEID PLUS V2", "FACEID PORTRAIT (style transfer)"]

def _fetch_pulid_models(server):
    """Fetch PuLID Flux model files."""
    try:
        info = _api_get(server, "/object_info/PulidFluxModelLoader")
        return info["PulidFluxModelLoader"]["input"]["required"]["pulid_file"][0]
    except Exception:
        return ["pulid_flux_v0.9.1.safetensors"]

def _api_get(server, path):
    url = f"{server.rstrip('/')}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _api_post_json(server, path, data):
    url = f"{server.rstrip('/')}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code} from {path}: {detail}") from e

def _upload_image(server, filepath, filename=None, image_type="input", overwrite=True):
    url = f"{server.rstrip('/')}/upload/image"
    if filename is None:
        filename = os.path.basename(filepath)
    boundary = uuid.uuid4().hex
    with open(filepath, "rb") as f:
        file_data = f.read()
    body_parts = []
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode())
    body_parts.append(file_data)
    body_parts.append(b"\r\n")
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(f'Content-Disposition: form-data; name="type"\r\n\r\n{image_type}\r\n'.encode())
    body_parts.append(f"--{boundary}\r\n".encode())
    ow = "true" if overwrite else "false"
    body_parts.append(f'Content-Disposition: form-data; name="overwrite"\r\n\r\n{ow}\r\n'.encode())
    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)
    req = urllib.request.Request(url, data=body,
                                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Upload HTTP {e.code}: {detail}") from e

def _create_selection_mask_png(filepath, image):
    """Export GIMP's actual selection channel as a grayscale PNG mask.
    White = selected (inpaint here), Black = unselected (keep).

    Strategy A: save selection → create layer from channel → export directly.
                No fill operations needed — the selection channel IS the mask.

    Strategy B: duplicate → flatten → grayscale → fill dance → export.
                Classic approach with GIMP 3 fill API compat.

    Strategy C: bounds-aware pixel scan using gimp-selection-value.
                Only scans within the selection bounding box.
    """
    width = image.get_width()
    height = image.get_height()
    errors = []

    # ── Pre-check: does a selection exist? ─────────────────────────────
    sel_x1, sel_y1, sel_x2, sel_y2 = 0, 0, width, height
    try:
        bounds = _pdb_run('gimp-selection-bounds', {'image': image})
        has_sel = bool(bounds.index(1))  # non-empty = True
        if not has_sel:
            raise RuntimeError("No selection — use a selection tool to mark the inpaint area first")
        sel_x1 = int(bounds.index(2))
        sel_y1 = int(bounds.index(3))
        sel_x2 = int(bounds.index(4))
        sel_y2 = int(bounds.index(5))
    except RuntimeError:
        raise
    except Exception as e:
        errors.append(f"bounds check: {e}")

    gfile = Gio.File.new_for_path(filepath.replace("\\", "/"))

    def _file_ok():
        try:
            return os.path.getsize(filepath) > 100
        except Exception:
            return False

    # ── Strategy A: export selection channel directly as layer ─────────
    # The selection channel already contains mask data (white=selected).
    # Save it as a channel, create a new grayscale image with a layer
    # from that channel, and export. Zero fill operations.
    new_img = None
    saved_ch = None
    try:
        # Save the selection to a named channel on the original image
        saved_ch = _pdb_run('gimp-selection-save', {'image': image}).index(1)

        # Create a new grayscale image and copy the channel as a layer
        new_img = Gimp.Image.new(width, height, Gimp.ImageBaseType.GRAY)
        new_layer = Gimp.Layer.new_from_drawable(saved_ch, new_img)
        new_layer.set_name("mask")
        new_layer.set_visible(True)
        new_layer.set_opacity(100.0)
        new_img.insert_layer(new_layer, None, 0)

        # Flatten only if there are visible layers, otherwise export directly
        layers = new_img.get_layers()
        visible = [l for l in layers if l.get_visible()]
        if visible:
            new_img.flatten()
            flat = new_img.get_layers()[0]
        else:
            # No visible layers — make the first layer visible and export it
            layers[0].set_visible(True)
            flat = layers[0]
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, new_img, [flat], gfile)

        if _file_ok():
            # Clean up
            new_img.delete()
            image.remove_channel(saved_ch)
            return

        errors.append("Strategy A: exported file too small")
    except Exception as e:
        errors.append(f"Strategy A: {e}")
    finally:
        try:
            if new_img is not None:
                new_img.delete()
        except Exception:
            pass
        try:
            if saved_ch is not None:
                image.remove_channel(saved_ch)
        except Exception:
            pass

    # ── Strategy B: duplicate + fill dance ─────────────────────────────
    dup = None
    try:
        dup = image.duplicate()
        saved_ch2 = _pdb_run('gimp-selection-save', {'image': dup}).index(1)
        dup.flatten()
        _pdb_run('gimp-image-convert-grayscale', {'image': dup})
        layer = dup.get_layers()[0]

        # Set FG = black, BG = white
        _pdb_run('gimp-context-set-default-colors', {})

        # Select all → fill black (try multiple GIMP 3 APIs)
        _pdb_run('gimp-selection-all', {'image': dup})
        fill_ok = False
        for fill_proc, fill_args in [
            ('gimp-drawable-edit-fill', {'drawable': layer, 'fill-type': Gimp.FillType.FOREGROUND}),
            ('gimp-drawable-edit-fill', {'drawable': layer, 'fill-type': 0}),
            ('gimp-edit-fill', {'drawable': layer, 'fill-type': 0}),
        ]:
            try:
                pdb = Gimp.get_pdb()
                if pdb.lookup_procedure(fill_proc) is not None:
                    _pdb_run(fill_proc, fill_args)
                    fill_ok = True
                    break
            except Exception as fe:
                errors.append(f"{fill_proc}: {fe}")
        if not fill_ok:
            raise RuntimeError("No working fill procedure")

        # Reload saved selection
        for op_val in [Gimp.ChannelOps.REPLACE, 2]:
            try:
                _pdb_run('gimp-image-select-item',
                         {'image': dup, 'operation': op_val, 'item': saved_ch2})
                break
            except Exception:
                pass

        # Swap → FG = white → fill selection
        _pdb_run('gimp-context-swap-colors', {})
        for fill_proc, fill_args in [
            ('gimp-drawable-edit-fill', {'drawable': layer, 'fill-type': Gimp.FillType.FOREGROUND}),
            ('gimp-drawable-edit-fill', {'drawable': layer, 'fill-type': 0}),
            ('gimp-edit-fill', {'drawable': layer, 'fill-type': 0}),
        ]:
            try:
                pdb = Gimp.get_pdb()
                if pdb.lookup_procedure(fill_proc) is not None:
                    _pdb_run(fill_proc, fill_args)
                    break
            except Exception as fe:
                errors.append(f"{fill_proc}: {fe}")

        _pdb_run('gimp-selection-none', {'image': dup})
        try:
            dup.remove_channel(saved_ch2)
        except Exception:
            pass

        dup.flatten()
        flat = dup.get_layers()[0]
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, [flat], gfile)

        if _file_ok():
            dup.delete()
            return

        errors.append("Strategy B: exported file too small")
    except Exception as e:
        errors.append(f"Strategy B: {e}")
    finally:
        try:
            if dup is not None:
                dup.delete()
        except Exception:
            pass

    # ── Strategy C: bounds-aware pixel scan ────────────────────────────
    # Only scan pixels inside the selection bounding box.
    sel_w = sel_x2 - sel_x1
    sel_h = sel_y2 - sel_y1
    total_pixels = sel_w * sel_h

    if total_pixels > 6_000_000:
        err_detail = "; ".join(errors) if errors else "unknown"
        raise RuntimeError(
            f"Cannot create selection mask: fast methods failed ({err_detail}) "
            f"and selection area is too large ({sel_w}x{sel_h}) for pixel scan. "
            f"Try a smaller selection or restart GIMP."
        )

    Gimp.progress_set_text("Building selection mask (pixel scan)...")
    rows = []
    mask_total = 0
    for y in range(height):
        row = bytearray(width)
        if sel_y1 <= y < sel_y2:
            for x in range(sel_x1, sel_x2):
                try:
                    res = _pdb_run('gimp-selection-value', {
                        'image': image, 'x': x, 'y': y,
                    })
                    val = int(res.index(1))
                    row[x] = val
                    mask_total += val
                except Exception:
                    row[x] = 0
        rows.append(b'\x00' + bytes(row))
        if y % 32 == 0:
            Gimp.progress_update(y / height)

    if mask_total == 0:
        raise RuntimeError("Selection mask is empty — no area selected")

    _write_grayscale_png(filepath, width, height, rows)


def _write_grayscale_png(filepath, width, height, pixel_rows):
    """Write a grayscale PNG from row data. Pure Python."""
    def _png_chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    with open(filepath, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        ihdr = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
        f.write(_png_chunk(b'IHDR', ihdr))
        # IDAT
        compressed = zlib.compress(b''.join(pixel_rows))
        f.write(_png_chunk(b'IDAT', compressed))
        # IEND
        f.write(_png_chunk(b'IEND', b''))

def _download_image(server, filename, subfolder="", folder_type="output"):
    params = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
    url = f"{server.rstrip('/')}/view?{params}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as resp:
        return resp.read()

def _wait_for_prompt(server, prompt_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            history = _api_get(server, f"/history/{prompt_id}")
            if prompt_id in history:
                return history[prompt_id]
        except Exception:
            pass
        time.sleep(1.5)
    raise TimeoutError(f"ComfyUI prompt {prompt_id} did not finish within {timeout}s")

def _get_output_images(server, prompt_id, timeout=300):
    result = _wait_for_prompt(server, prompt_id, timeout)
    images = []
    for node_id, node_output in result.get("outputs", {}).items():
        for img in node_output.get("images", []):
            images.append((img["filename"], img.get("subfolder", ""), img.get("type", "output")))
    return images

# ═══════════════════════════════════════════════════════════════════════════
#  Workflow builders
# ═══════════════════════════════════════════════════════════════════════════

def _inject_loras(wf, loras, ckpt_node="1"):
    """Insert LoRA loader nodes between checkpoint and the rest of the workflow.
    Chains: ckpt -> lora1 -> lora2 -> ... -> (model_out, clip_out).
    Returns (workflow, final_model_ref, final_clip_ref)."""
    if not loras:
        return wf, [ckpt_node, 0], [ckpt_node, 1]

    prev_model = [ckpt_node, 0]
    prev_clip = [ckpt_node, 1]
    base_id = 100  # high IDs to avoid collision with existing nodes

    for i, lora in enumerate(loras):
        nid = str(base_id + i)
        wf[nid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": prev_model,
                "clip": prev_clip,
                "lora_name": lora["name"],
                "strength_model": lora["strength_model"],
                "strength_clip": lora["strength_clip"],
            }
        }
        prev_model = [nid, 0]
        prev_clip = [nid, 1]

    return wf, prev_model, prev_clip


def _build_img2img(image_filename, preset, prompt_text, negative_text, seed, loras=None):
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": preset["ckpt"]}},
    }
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "1")
    wf.update({
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "4": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "5": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["4", 0], "vae": ["1", 2]}},
        "6": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref, "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["5", 0], "seed": seed,
                  "steps": preset["steps"], "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"], "scheduler": preset["scheduler"],
                  "denoise": preset["denoise"],
              }},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": "gimp_comfy"}},
    })
    return wf


def _build_txt2img(preset, prompt_text, negative_text, seed, loras=None):
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": preset["ckpt"]}},
    }
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "1")
    wf.update({
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": preset["width"], "height": preset["height"], "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref, "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["4", 0], "seed": seed,
                  "steps": preset["steps"], "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"], "scheduler": preset["scheduler"],
                  "denoise": 1.0,
              }},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": "gimp_comfy"}},
    })
    return wf

def _build_inpaint(image_filename, mask_filename, preset, prompt_text, negative_text, seed, loras=None):
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": preset["ckpt"]}},
    }
    wf, model_ref, clip_ref = _inject_loras(wf, loras or [], "1")
    wf.update({
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": clip_ref}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text, "clip": clip_ref}},
        "4": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        "5": {"class_type": "LoadImage",
              "inputs": {"image": mask_filename}},
        # Convert the grayscale mask IMAGE to a MASK tensor.
        # LoadImage output [1] is the alpha channel (all-zero if no alpha!).
        # We need output [0] (the actual pixels) → ImageToMask → red channel.
        "51": {"class_type": "ImageToMask",
               "inputs": {"image": ["5", 0], "channel": "red"}},
        # Get original image size for restoring after sampling
        "90": {"class_type": "GetImageSize+",
               "inputs": {"image": ["4", 0]}},
        # Scale image to working resolution
        "91": {"class_type": "ImageScale",
               "inputs": {"image": ["4", 0], "upscale_method": "lanczos",
                           "width": preset["width"], "height": preset["height"],
                           "crop": "disabled"}},
        # Scale mask to same working resolution
        "92": {"class_type": "ImageScale",
               "inputs": {"image": ["5", 0], "upscale_method": "nearest-exact",
                           "width": preset["width"], "height": preset["height"],
                           "crop": "disabled"}},
        "52": {"class_type": "ImageToMask",
               "inputs": {"image": ["92", 0], "channel": "red"}},
        "6": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["91", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SetLatentNoiseMask",
              "inputs": {"samples": ["6", 0], "mask": ["52", 0]}},
        "8": {"class_type": "KSampler",
              "inputs": {
                  "model": model_ref, "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["7", 0], "seed": seed,
                  "steps": preset["steps"], "cfg": preset["cfg"],
                  "sampler_name": preset["sampler"], "scheduler": preset["scheduler"],
                  "denoise": preset["denoise"],
              }},
        "9": {"class_type": "VAEDecode",
              "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
        # Restore to original image size
        "95": {"class_type": "ImageScale",
               "inputs": {"image": ["9", 0], "upscale_method": "lanczos",
                           "width": ["90", 0], "height": ["90", 1],
                           "crop": "disabled"}},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["95", 0], "filename_prefix": "gimp_inpaint"}},
    })
    return wf


# ── Face Swap (ReActor) ──────────────────────────────────────────────────

FACE_SWAP_MODELS = [
    "inswapper_128.onnx",
    "inswapper_128_fp16.onnx",
    "reswapper_128.onnx",
    "reswapper_256.onnx",
    "hyperswap_1a_256.onnx",
    "hyperswap_1b_256.onnx",
    "hyperswap_1c_256.onnx",
]

FACE_RESTORE_MODELS = [
    "none",
    "codeformer-v0.1.0.pth",
    "GFPGANv1.3.pth",
    "GFPGANv1.4.pth",
    "GPEN-BFR-512.onnx",
    "GPEN-BFR-1024.onnx",
    "RestoreFormer_PP.onnx",
]


def _build_faceswap(target_filename, source_filename, swap_model="inswapper_128.onnx",
                     face_restore_model="codeformer-v0.1.0.pth",
                     face_restore_vis=1.0, codeformer_weight=0.5,
                     detect_gender_input="no", detect_gender_source="no",
                     input_face_idx="0", source_face_idx="0"):
    """ReActorFaceSwap: paste the face from source_image onto target_image."""
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": source_filename}},
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
                  "detect_gender_input": detect_gender_input,
                  "detect_gender_source": detect_gender_source,
                  "input_faces_index": input_face_idx,
                  "source_faces_index": source_face_idx,
                  "console_log_level": 1,
              }},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "gimp_faceswap"}},
    }
    return wf


def _build_faceswap_model(target_filename, face_model_name, swap_model="inswapper_128.onnx",
                           face_restore_model="codeformer-v0.1.0.pth",
                           face_restore_vis=1.0, codeformer_weight=0.5,
                           detect_gender_input="no", detect_gender_source="no",
                           input_face_idx="0", source_face_idx="0"):
    """ReActor face swap using a saved face model instead of a source image."""
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "2": {"class_type": "ReActorLoadFaceModel",
              "inputs": {"face_model": face_model_name}},
        "3": {"class_type": "ReActorFaceSwapOpt",
              "inputs": {
                  "enabled": True,
                  "input_image": ["1", 0],
                  "face_model": ["2", 0],
                  "swap_model": swap_model,
                  "facedetection": "retinaface_resnet50",
                  "face_restore_model": face_restore_model,
                  "face_restore_visibility": face_restore_vis,
                  "codeformer_weight": codeformer_weight,
              }},
        "4": {"class_type": "ReActorOptions",
              "inputs": {
                  "input_faces_order": "left-right",
                  "input_faces_index": input_face_idx,
                  "detect_gender_input": detect_gender_input,
                  "source_faces_order": "left-right",
                  "source_faces_index": source_face_idx,
                  "detect_gender_source": detect_gender_source,
                  "console_log_level": 1,
                  "restore_swapped_only": True,
              }},
        "5": {"class_type": "ReActorFaceBoost",
              "inputs": {
                  "enabled": True,
                  "boost_model": face_restore_model,
                  "interpolation": "Bicubic",
                  "visibility": 1.0,
                  "codeformer_weight": codeformer_weight,
                  "restore_with_main_after": False,
              }},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["3", 0], "filename_prefix": "gimp_faceswap_model"}},
    }
    # Connect options and boost to the swap node
    wf["3"]["inputs"]["options"] = ["4", 0]
    wf["3"]["inputs"]["face_boost"] = ["5", 0]
    return wf


# ── mtb Face Swap (direct swap) ────────────────────────────────────────

def _build_faceswap_mtb(target_filename, source_filename,
                         analysis_model="buffalo_l",
                         swap_model="inswapper_128.onnx",
                         faces_index="0"):
    """Face swap using mtb facetools — direct swap from source image to target.

    Pipeline: LoadImage(target) + LoadImage(source)
              Load Face Analysis Model (mtb) → FACE_ANALYSIS_MODEL
              Load Face Swap Model (mtb) → FACESWAP_MODEL
              Face Swap (mtb) → IMAGE
              SaveImage
    """
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": source_filename}},
        "3": {"class_type": "Load Face Analysis Model (mtb)",
              "inputs": {"faceswap_model": analysis_model}},
        "4": {"class_type": "Load Face Swap Model (mtb)",
              "inputs": {"faceswap_model": swap_model}},
        "5": {"class_type": "Face Swap (mtb)",
              "inputs": {
                  "image": ["1", 0],
                  "reference": ["2", 0],
                  "faces_index": faces_index,
                  "faceanalysis_model": ["3", 0],
                  "faceswap_model": ["4", 0],
              }},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["5", 0], "filename_prefix": "gimp_faceswap_mtb"}},
    }
    return wf


# ── IPAdapter FaceID (face-guided img2img) ─────────────────────────────

FACEID_PRESETS = {
    "SD1.5 — Juggernaut Reborn": {
        "ckpt": "SD-1.5\\juggernaut_reborn.safetensors",
        "width": 512, "height": 512,
        "steps": 25, "cfg": 7.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
    "SD1.5 — Realistic Vision v5.1": {
        "ckpt": "SD-1.5\\realisticVisionV51_v51VAE.safetensors",
        "width": 512, "height": 512,
        "steps": 25, "cfg": 7.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
    "SDXL — Juggernaut XL Ragnarok": {
        "ckpt": "SDXL\\Realistic\\juggernautXL_ragnarok.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 5.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
    "SDXL — ZavyChroma XL v10": {
        "ckpt": "SDXL\\Realistic\\zavychromaxl_v100.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 5.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
    "SDXL — JibMix Realistic v18": {
        "ckpt": "SDXL\\Realistic\\jibMixRealisticXL_v180SkinSupreme.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 5.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    },
}

def _build_faceid_img2img(target_filename, face_ref_filename, preset_key,
                           prompt_text, negative_text, seed,
                           faceid_preset="FACEID PLUS V2",
                           lora_strength=0.6, weight=0.85, weight_v2=1.0,
                           denoise=None, steps=None, cfg=None):
    """IPAdapter FaceID img2img — re-generates target image preserving face identity from reference.

    Pipeline: CheckpointLoaderSimple → MODEL, CLIP, VAE
              IPAdapterUnifiedLoaderFaceID(MODEL, preset) → MODEL (with FaceID LoRA), IPADAPTER
              LoadImage(face_ref) → face reference
              IPAdapterFaceID(MODEL, IPADAPTER, face_image) → MODEL (conditioned on face)
              CLIPTextEncode(positive) → CONDITIONING
              CLIPTextEncode(negative) → CONDITIONING
              LoadImage(target) → IMAGE
              VAEEncode(IMAGE, VAE) → LATENT
              KSampler(MODEL, CONDITIONING+, CONDITIONING-, LATENT) → LATENT
              VAEDecode → IMAGE
              SaveImage
    """
    p = FACEID_PRESETS[preset_key]
    steps = steps or p["steps"]
    cfg = cfg or p["cfg"]
    denoise = denoise or p["denoise"]

    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": p["ckpt"]}},
        # FaceID unified loader: loads IPAdapter + LoRA, applies to model
        "2": {"class_type": "IPAdapterUnifiedLoaderFaceID",
              "inputs": {
                  "model": ["1", 0],
                  "preset": faceid_preset,
                  "lora_strength": lora_strength,
                  "provider": "CUDA",
              }},
        # Load face reference image
        "3": {"class_type": "LoadImage",
              "inputs": {"image": face_ref_filename}},
        # Apply FaceID conditioning
        "4": {"class_type": "IPAdapterFaceID",
              "inputs": {
                  "model": ["2", 0],
                  "ipadapter": ["2", 1],
                  "image": ["3", 0],
                  "weight": weight,
                  "weight_faceidv2": weight_v2,
                  "weight_type": "linear",
                  "combine_embeds": "concat",
                  "start_at": 0.0,
                  "end_at": 1.0,
                  "embeds_scaling": "V only",
              }},
        # Text encoding
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["1", 1]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text or "blurry, deformed, bad anatomy", "clip": ["1", 1]}},
        # Load target image and encode to latent
        "7": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["7", 0], "vae": ["1", 2]}},
        # Sample
        "9": {"class_type": "KSampler",
              "inputs": {
                  "model": ["4", 0],
                  "positive": ["5", 0],
                  "negative": ["6", 0],
                  "latent_image": ["8", 0],
                  "seed": seed,
                  "steps": steps,
                  "cfg": cfg,
                  "sampler_name": p["sampler"],
                  "scheduler": p["scheduler"],
                  "denoise": denoise,
              }},
        # Decode
        "11": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "12": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "gimp_faceid"}},
    }
    return wf


# ── PuLID Flux (face identity-preserving generation) ───────────────────

PULID_FLUX_MODELS = [
    "Flux\\FLUX1 Dev fp8.safetensors",
    "Flux\\flux1-dev-kontext_fp8_scaled.safetensors",
]

def _build_pulid_flux(target_filename, face_ref_filename,
                       prompt_text, negative_text, seed,
                       flux_model="Flux\\FLUX1 Dev fp8.safetensors",
                       pulid_model="pulid_flux_v0.9.1.safetensors",
                       strength=0.9, steps=20, guidance=3.5,
                       denoise=0.65, width=1024, height=1024):
    """PuLID Flux — preserves face identity from reference while generating with Flux.

    Pipeline: UNETLoader(flux) → MODEL
              PulidFluxModelLoader → PULIDFLUX
              PulidFluxEvaClipLoader → EVA_CLIP
              PulidFluxInsightFaceLoader → FACEANALYSIS
              LoadImage(face_ref) → face reference
              ApplyPulidFlux(MODEL, PULIDFLUX, EVA_CLIP, FACEANALYSIS, face_image) → MODEL
              DualCLIPLoader(clip_l, t5xxl, flux) → CLIP
              CLIPTextEncode(prompt) → CONDITIONING
              LoadImage(target) → IMAGE
              VAELoader → VAE
              VAEEncode → LATENT
              KSampler → LATENT
              VAEDecode → IMAGE
              SaveImage
    """
    wf = {
        # Load Flux UNET
        "1": {"class_type": "UNETLoader",
              "inputs": {
                  "unet_name": flux_model,
                  "weight_dtype": "default",
              }},
        # PuLID model components (using Pulid* lowercase node family)
        "2": {"class_type": "PulidFluxModelLoader",
              "inputs": {"pulid_file": pulid_model}},
        "3": {"class_type": "PulidFluxEvaClipLoader",
              "inputs": {}},
        "4": {"class_type": "PulidFluxInsightFaceLoader",
              "inputs": {"provider": "CUDA"}},
        # Load face reference
        "5": {"class_type": "LoadImage",
              "inputs": {"image": face_ref_filename}},
        # Apply PuLID face identity to model
        "6": {"class_type": "ApplyPulidFlux",
              "inputs": {
                  "model": ["1", 0],
                  "pulid_flux": ["2", 0],
                  "eva_clip": ["3", 0],
                  "face_analysis": ["4", 0],
                  "image": ["5", 0],
                  "weight": strength,
                  "start_at": 0.0,
                  "end_at": 1.0,
              }},
        # Text encoding (Flux uses DualCLIPLoader: clip_name1=clip_l, clip_name2=t5)
        "7": {"class_type": "DualCLIPLoader",
              "inputs": {
                  "clip_name1": "clip_l.safetensors",
                  "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                  "type": "flux",
              }},
        "8": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["7", 0]}},
        # Target image for img2img
        "9": {"class_type": "LoadImage",
              "inputs": {"image": target_filename}},
        # VAE
        "10": {"class_type": "VAELoader",
               "inputs": {"vae_name": "ae.safetensors"}},
        "11": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["9", 0], "vae": ["10", 0]}},
        # Sample
        "12": {"class_type": "KSampler",
               "inputs": {
                   "model": ["6", 0],
                   "positive": ["8", 0],
                   "negative": ["8", 0],
                   "latent_image": ["11", 0],
                   "seed": seed,
                   "steps": steps,
                   "cfg": guidance,
                   "sampler_name": "euler",
                   "scheduler": "simple",
                   "denoise": denoise,
               }},
        # Decode and save
        "13": {"class_type": "VAEDecode",
               "inputs": {"samples": ["12", 0], "vae": ["10", 0]}},
        "14": {"class_type": "SaveImage",
               "inputs": {"images": ["13", 0], "filename_prefix": "gimp_pulid_flux"}},
    }
    return wf


# ── Wan 2.2 Image-to-Video ──────────────────────────────────────────────

# ── WAN Video Prompt Presets (best-practice templates) ───────────────────
WAN_VIDEO_PRESETS = [
    {
        "label": "(none — manual prompt)",
        "prompt": "",
        "negative": "",
        "cfg_override": None,
        "steps_override": None,
        "length_override": None,
        "pingpong": None,  # None = don't override
        "loras": [],
    },
    # ── Subtle Life / Living Portrait ────────────────────────────────────
    {
        "label": "Living Portrait — subtle breathing & blinks",
        "prompt": "a person subtly breathing, gentle micro-movements, natural blinking, "
                  "soft chest rise and fall, slight head sway, lifelike idle animation, "
                  "photorealistic, cinematic lighting, shallow depth of field",
        "negative": "static, frozen, mannequin, jerky motion, fast movement, "
                    "exaggerated motion, morphing, distorted face, blurry",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Living Portrait — hair & fabric sway",
        "prompt": "person with gently flowing hair, soft fabric movement in breeze, "
                  "subtle clothes ripple, natural hair physics, serene expression, "
                  "photorealistic portrait, gentle wind effect, cinematic",
        "negative": "static, frozen, violent wind, tornado, exaggerated motion, "
                    "morphing, distorted, blurry, unnatural movement",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Living Portrait — smile & expression shift",
        "prompt": "person transitioning from neutral to gentle warm smile, subtle "
                  "expression change, natural facial animation, eyes lighting up, "
                  "slight cheek movement, photorealistic, cinematic close-up",
        "negative": "exaggerated expression, grotesque, morphing, distorted face, "
                    "uncanny valley, rapid change, blurry, jerky",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    # ── Eye & Gaze Movement ──────────────────────────────────────────────
    {
        "label": "Eye Movement — looking around",
        "prompt": "person slowly looking around, natural eye movement, gaze shifting "
                  "left and right, subtle head tracking with eyes, realistic eye motion, "
                  "photorealistic, cinematic portrait, detailed iris",
        "negative": "cross-eyed, spinning eyes, rapid movement, jerky, "
                    "deformed eyes, blurry, morphing face",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Camera Motion ────────────────────────────────────────────────────
    {
        "label": "Camera — slow zoom in",
        "prompt": "slow cinematic zoom in, camera slowly pushing forward, "
                  "gradual close-up, smooth dolly in, professional cinematography, "
                  "steady camera, photorealistic, shallow depth of field",
        "negative": "shaky camera, fast zoom, jerky, jump cut, "
                    "distorted, blurry, fish-eye, warping",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    {
        "label": "Camera — slow orbit / rotate",
        "prompt": "slow cinematic camera orbit around subject, smooth rotating shot, "
                  "gentle lateral dolly, parallax depth, professional steadicam, "
                  "photorealistic, cinematic lighting",
        "negative": "fast rotation, spinning, shaky, jerky, nausea-inducing, "
                    "warping, morphing, distorted perspective",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Camera — slow pan left/right",
        "prompt": "slow cinematic camera pan from left to right, smooth horizontal tracking, "
                  "gentle lateral movement, professional steadicam, photorealistic, "
                  "cinematic widescreen composition",
        "negative": "fast pan, jerky, shaky, vertical movement, zoom, "
                    "warping, morphing, blurry motion",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Nature / Environment ─────────────────────────────────────────────
    {
        "label": "Nature — flowing water & ripples",
        "prompt": "gently flowing water, natural ripples and reflections, "
                  "soft current movement, light dancing on water surface, "
                  "serene river or stream, photorealistic, 4K, cinematic",
        "negative": "static water, frozen, flood, tsunami, rapids, "
                    "distorted reflections, blurry, noisy",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Nature — clouds drifting",
        "prompt": "slowly drifting clouds in sky, gentle cloud movement, "
                  "soft atmospheric motion, time-lapse clouds, golden hour lighting, "
                  "dramatic sky, photorealistic, cinematic landscape",
        "negative": "static sky, storm, tornado, fast clouds, flickering, "
                    "distorted, glitching, blurry",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Nature — trees & foliage swaying",
        "prompt": "trees gently swaying in breeze, leaves rustling, natural foliage "
                  "movement, soft wind through branches, dappled sunlight, "
                  "photorealistic forest or garden, cinematic",
        "negative": "static trees, hurricane, violent wind, falling trees, "
                    "distorted, morphing, blurry",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Nature — fire / candle flicker",
        "prompt": "gently flickering candle flame, warm firelight dancing, "
                  "soft orange glow, natural fire movement, cozy atmosphere, "
                  "photorealistic, cinematic lighting, shallow depth of field",
        "negative": "explosion, inferno, out of control fire, static flame, "
                    "distorted, blurry, flickering artifacts",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Body & Action ────────────────────────────────────────────────────
    {
        "label": "Action — person walking forward",
        "prompt": "person walking forward naturally, smooth gait, realistic body motion, "
                  "natural arm swing, confident stride, photorealistic, "
                  "cinematic tracking shot, urban or nature background",
        "negative": "floating, sliding, moonwalk, jerky movement, "
                    "distorted limbs, extra limbs, blurry, frozen",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    {
        "label": "Action — person turning head",
        "prompt": "person slowly turning head to face camera, natural head rotation, "
                  "smooth neck movement, elegant turn, photorealistic portrait, "
                  "cinematic, shallow depth of field",
        "negative": "snapping head, jerky rotation, exorcist turn, 360 spin, "
                    "morphing, distorted face, blurry, neck distortion",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    {
        "label": "Action — dancing / rhythmic movement",
        "prompt": "person dancing gracefully, smooth rhythmic body movement, "
                  "fluid dance motion, natural choreography, expressive movement, "
                  "photorealistic, cinematic, dynamic lighting",
        "negative": "stiff, robotic, broken limbs, distorted body, "
                    "extra arms, jerky, morphing, blurry",
        "cfg_override": 6.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    # ── Atmospheric / Mood ───────────────────────────────────────────────
    {
        "label": "Atmosphere — rain & droplets",
        "prompt": "gentle rain falling, raindrops on surface, soft rain streaks, "
                  "wet reflections, moody atmosphere, cinematic rain scene, "
                  "photorealistic, shallow depth of field, bokeh raindrops",
        "negative": "flood, hurricane, static, dry, no rain, "
                    "distorted, blurry, noisy",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Atmosphere — snow falling",
        "prompt": "gentle snowfall, soft snowflakes drifting down, peaceful winter scene, "
                  "slow-motion snow, magical winter atmosphere, photorealistic, "
                  "cinematic, cold breath visible",
        "negative": "blizzard, avalanche, static, distorted, "
                    "morphing, blurry, warm, summer",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Atmosphere — particles & dust motes",
        "prompt": "floating dust particles in light beam, atmospheric dust motes, "
                  "volumetric lighting, god rays with floating particles, "
                  "dreamy atmosphere, photorealistic, cinematic",
        "negative": "static, sandstorm, explosion, distorted, "
                    "blurry, noisy, dirty",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Atmosphere — fog / mist rolling",
        "prompt": "gentle fog rolling across scene, soft mist movement, atmospheric haze, "
                  "moody fog tendrils, mysterious atmosphere, volumetric fog, "
                  "photorealistic, cinematic lighting",
        "negative": "static fog, dense smoke, explosion, fire, "
                    "distorted, blurry, noisy",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Cinemagraph Loops ────────────────────────────────────────────────
    {
        "label": "Cinemagraph — ocean waves loop",
        "prompt": "ocean waves gently crashing on shore, rhythmic wave motion, "
                  "sea foam rolling in and out, peaceful beach, golden hour, "
                  "photorealistic, cinematic, seamless loop",
        "negative": "tsunami, storm, static ocean, frozen water, "
                    "distorted, blurry, flickering",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Cinemagraph — city lights & traffic",
        "prompt": "city lights twinkling at night, gentle traffic light trails, "
                  "urban nightscape, bokeh city lights, smooth car headlight streaks, "
                  "photorealistic, cinematic night photography",
        "negative": "static lights, crash, explosion, daytime, "
                    "distorted, blurry, flickering",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Stylized / Creative ──────────────────────────────────────────────
    {
        "label": "Style — painting coming to life",
        "prompt": "painted artwork slowly coming to life, brushstrokes animating, "
                  "oil painting with subtle movement, artistic interpretation, "
                  "painterly animation, museum piece moving, masterwork quality",
        "negative": "photorealistic, modern, digital, jerky, glitching, "
                    "distorted, morphing rapidly, flickering",
        "cfg_override": 6.0,
        "steps_override": 35,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    {
        "label": "Style — anime / illustration loop",
        "prompt": "anime character with subtle idle animation, gentle breathing, "
                  "hair flowing, soft wind, anime art style, beautiful illustration, "
                  "high quality animation, smooth 2D animation",
        "negative": "3D, photorealistic, live action, jerky, static, "
                    "low quality, distorted, blurry",
        "cfg_override": 6.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Product / Object ─────────────────────────────────────────────────
    {
        "label": "Product — 360° turntable spin",
        "prompt": "product slowly rotating on turntable, smooth 360 degree rotation, "
                  "studio lighting, clean white background, professional product shot, "
                  "photorealistic, commercial quality, even lighting",
        "negative": "shaky, jerky rotation, wobble, distorted shape, "
                    "changing product, morphing, blurry, dirty background",
        "cfg_override": 5.5,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": False,
        "loras": [],
    },
    {
        "label": "Product — hero shot with sparkle",
        "prompt": "product hero shot with sparkling light effects, lens flare, "
                  "premium presentation, glamorous lighting sweep, "
                  "commercial advertisement quality, photorealistic, cinematic",
        "negative": "dull, flat lighting, dirty, damaged product, "
                    "distorted, morphing, blurry",
        "cfg_override": 6.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
    # ── Animal / Pet ─────────────────────────────────────────────────────
    {
        "label": "Pet — cat / dog breathing & looking",
        "prompt": "cute pet with subtle breathing, gentle ear twitches, "
                  "natural animal idle motion, soft blinking, whisker movement, "
                  "photorealistic animal portrait, cinematic, warm lighting",
        "negative": "static, frozen, stuffed animal, toy, "
                    "distorted, morphing, extra limbs, blurry",
        "cfg_override": 5.0,
        "steps_override": 30,
        "length_override": 81,
        "pingpong": True,
        "loras": [],
    },
]


def _wan_video_dims(src_w, src_h, target_long=720, align=16):
    """Compute video output dimensions preserving aspect ratio.

    Scales so the longest side is ≈ target_long, then rounds both
    dimensions to the nearest multiple of *align* (VAE requirement).
    Examples:
        1920×1080 → 720×400    (landscape)
        1080×1920 → 400×720    (portrait)
        1024×1024 → 720×720    (square — floored to align)
        832×480   → 832×480    (already ≤720 on long side, kept as-is)
    """
    if src_w <= 0 or src_h <= 0:
        return 832, 480
    long = max(src_w, src_h)
    if long <= target_long:
        # Already small enough — just align
        w = max(align, round(src_w / align) * align)
        h = max(align, round(src_h / align) * align)
        return w, h
    scale = target_long / long
    w = max(align, round(src_w * scale / align) * align)
    h = max(align, round(src_h * scale / align) * align)
    return w, h


WAN_I2V_PRESETS = {
    "Wan I2V 14B (GGUF Q4)": {
        "high_model": "Wan\\wan2.2_i2v_high_noise_14B_Q4_K_S.gguf",
        "low_model": "Wan\\wan2.2_i2v_low_noise_14B_Q4_K_S.gguf",
        "clip": "umt5-xxl-encoder-Q8_0.gguf",
        "vae": "wan_2.1_vae.safetensors",
        "steps": 30, "second_step": 20, "cfg": 5.0, "shift": 8.0,
        "lora_prefix": "Wan\\14B",
        "high_accel_lora": "Wan\\14B\\lightx2v_wan_4steps_lora_high_noise.safetensors",
        "low_accel_lora": "Wan\\14B\\lightx2v_wan_128_lora_low_noise.safetensors",
        "accel_strength": 1.0,
    },
    "Wan I2V 14B (fp8)": {
        "high_model": "Wan\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "low_model": "Wan\\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        "clip": "umt5-xxl-encoder-Q8_0.gguf",
        "vae": "wan_2.1_vae.safetensors",
        "steps": 30, "second_step": 20, "cfg": 5.0, "shift": 8.0,
        "lora_prefix": "Wan\\14B",
    },
    "Wan Enhanced NSFW SVI (fp8)": {
        "high_model": "Wan\\wan22EnhancedNSFWSVICamera_nsfwV2FP8H.safetensors",
        "low_model": "Wan\\wan22EnhancedNSFWSVICamera_nsfwV2FP8L.safetensors",
        "clip": "umt5-xxl-encoder-Q8_0.gguf",
        "vae": "wan_2.1_vae.safetensors",
        "steps": 30, "second_step": 20, "cfg": 5.0, "shift": 8.0,
        "lora_prefix": "Wan\\Enhanced",
    },
}

def _filter_wan_loras(all_loras, preset_key=None):
    """Filter LoRAs to only those in the Wan subfolder matching the selected model variant.

    LoRA folder layout:
        loras/Wan/14B/         — LoRAs compatible with standard Wan 2.2 14B
        loras/Wan/Enhanced/    — LoRAs compatible with Wan Enhanced NSFW SVI
    Each preset declares a lora_prefix (e.g. 'Wan\\14B') and only LoRAs
    whose path starts with that prefix are shown.
    """
    if not preset_key or preset_key not in WAN_I2V_PRESETS:
        # Fallback: show everything under Wan\
        prefix = "Wan\\"
    else:
        prefix = WAN_I2V_PRESETS[preset_key].get("lora_prefix", "Wan\\")
        # Normalise to always end with backslash for matching
        if not prefix.endswith("\\"):
            prefix += "\\"
    return [l for l in all_loras if l.startswith(prefix) or l.startswith(prefix.replace("\\", "/"))]


def _build_wan_i2v(image_filename, preset_key, prompt_text, negative_text, seed,
                    width=832, height=480, length=81,
                    steps=None, cfg=None, shift=None, second_step=None,
                    loras=None, upscale=True, upscale_factor=1.5,
                    interpolate=True, pingpong=False, fps=16):
    """Wan 2.2 Image-to-Video — fatberg_slim dual-model GGUF architecture.

    Two-pass pipeline:
      CLIPLoaderGGUF → CLIPTextEncode (pos/neg)
      UnetLoaderGGUF × 2 (high/low noise) → LoRA chains → ModelSamplingSD3
      VAELoader + LoadImage → WanImageToVideo → conditioning + latent
      KSamplerAdvanced pass 1 (high noise, steps 0→second_step)
      KSamplerAdvanced pass 2 (low noise, steps second_step→end, cfg=1.0)
      VAEDecode → [RTXVideoSuperResolution] → [RIFE VFI] → VHS_VideoCombine
    """
    p = WAN_I2V_PRESETS[preset_key]
    steps = steps or p["steps"]
    cfg = cfg or p["cfg"]
    shift = shift or p["shift"]
    second_step = second_step if second_step is not None else p.get("second_step", 20)

    is_gguf_high = p["high_model"].endswith(".gguf")
    is_gguf_low = p["low_model"].endswith(".gguf")

    wf = {
        # CLIP loader (GGUF T5 encoder for Wan)
        "1": {"class_type": "CLIPLoaderGGUF",
              "inputs": {"clip_name": p["clip"], "type": "wan"}},
        # High noise UNet
        "2": {"class_type": "UnetLoaderGGUF" if is_gguf_high else "UNETLoader",
              "inputs": {"unet_name": p["high_model"]}},
        # Low noise UNet
        "3": {"class_type": "UnetLoaderGGUF" if is_gguf_low else "UNETLoader",
              "inputs": {"unet_name": p["low_model"]}},
        # VAE
        "4": {"class_type": "VAELoader",
              "inputs": {"vae_name": p["vae"]}},
        # Positive prompt
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["1", 0]}},
        # Negative prompt
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_text or "", "clip": ["1", 0]}},
        # Load source image
        "7": {"class_type": "LoadImage",
              "inputs": {"image": image_filename}},
        # Scale image to target resolution
        "8": {"class_type": "ImageScale",
              "inputs": {"image": ["7", 0], "upscale_method": "lanczos",
                         "width": width, "height": height, "crop": "disabled"}},
    }

    # Add weight_dtype for non-GGUF UNet loaders
    if not is_gguf_high:
        wf["2"]["inputs"]["weight_dtype"] = "default"
    if not is_gguf_low:
        wf["3"]["inputs"]["weight_dtype"] = "default"

    # ── LoRA chains ──────────────────────────────────────────────────
    # Accelerator LoRAs (noise-specific) first, then user content LoRAs
    high_model_ref = ["2", 0]
    low_model_ref = ["3", 0]

    high_lora_list = []
    low_lora_list = []

    # Preset accelerator LoRAs (lightx2v etc.)
    if p.get("high_accel_lora"):
        high_lora_list.append((p["high_accel_lora"], p.get("accel_strength", 1.0)))
    if p.get("low_accel_lora"):
        low_lora_list.append((p["low_accel_lora"], p.get("accel_strength", 1.0)))

    # User-selected content LoRAs (applied to both models)
    if loras:
        for lora_name, lora_str in loras:
            high_lora_list.append((lora_name, lora_str))
            low_lora_list.append((lora_name, lora_str))

    # Chain LoRAs for high-noise model (nodes 100+)
    for i, (lname, lstr) in enumerate(high_lora_list):
        nid = str(100 + i)
        wf[nid] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": high_model_ref,
                               "lora_name": lname, "strength_model": lstr}}
        high_model_ref = [nid, 0]

    # Chain LoRAs for low-noise model (nodes 120+)
    for i, (lname, lstr) in enumerate(low_lora_list):
        nid = str(120 + i)
        wf[nid] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": low_model_ref,
                               "lora_name": lname, "strength_model": lstr}}
        low_model_ref = [nid, 0]

    # ── ModelSamplingSD3 (shift) on both models ──────────────────────
    wf["30"] = {"class_type": "ModelSamplingSD3",
                "inputs": {"model": high_model_ref, "shift": shift}}
    wf["31"] = {"class_type": "ModelSamplingSD3",
                "inputs": {"model": low_model_ref, "shift": shift}}

    # ── WanImageToVideo conditioning ─────────────────────────────────
    wf["40"] = {"class_type": "WanImageToVideo",
                "inputs": {
                    "width": width, "height": height, "length": length,
                    "batch_size": 1,
                    "positive": ["5", 0], "negative": ["6", 0],
                    "vae": ["4", 0], "start_image": ["8", 0],
                }}

    # ── Two-pass KSamplerAdvanced ────────────────────────────────────
    # Pass 1: high-noise model (steps 0 → second_step)
    wf["50"] = {"class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["30", 0],
                    "positive": ["40", 0], "negative": ["40", 1],
                    "latent_image": ["40", 2],
                    "add_noise": "enable",
                    "noise_seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "simple",
                    "start_at_step": 0,
                    "end_at_step": second_step,
                    "return_with_leftover_noise": "enable",
                }}
    # Pass 2: low-noise model (steps second_step → end, cfg=1.0)
    wf["51"] = {"class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["31", 0],
                    "positive": ["40", 0], "negative": ["40", 1],
                    "latent_image": ["50", 0],
                    "add_noise": "disable",
                    "noise_seed": seed,
                    "steps": steps,
                    "cfg": 1.0,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "simple",
                    "start_at_step": second_step,
                    "end_at_step": 10000,
                    "return_with_leftover_noise": "disable",
                }}

    # ── VAE Decode ───────────────────────────────────────────────────
    wf["60"] = {"class_type": "VAEDecode",
                "inputs": {"samples": ["51", 0], "vae": ["4", 0]}}

    video_ref = ["60", 0]

    # ── Optional post-processing ─────────────────────────────────────
    if upscale:
        wf["70"] = {"class_type": "RTXVideoSuperResolution",
                    "inputs": {"images": video_ref, "scale": upscale_factor,
                               "backend": "TensorRT"}}
        video_ref = ["70", 0]

    if interpolate:
        wf["71"] = {"class_type": "RIFE VFI",
                    "inputs": {"frames": video_ref, "ckpt_name": "rife49.pth",
                               "clear_cache_after_n_frames": 10, "multiplier": 2,
                               "fast_mode": True, "ensemble": True,
                               "scale_factor": 1.0}}
        video_ref = ["71", 0]

    # Output FPS: double if RIFE 2× interpolation is active
    output_fps = float(fps * (2 if interpolate else 1))

    wf["12"] = {"class_type": "VHS_VideoCombine",
                "inputs": {"images": video_ref, "frame_rate": output_fps,
                           "loop_count": 0, "filename_prefix": "gimp_wan_i2v",
                           "format": "video/h264-mp4", "pingpong": pingpong,
                           "save_output": True}}

    # Save first frame for GIMP to import
    wf["13"] = {"class_type": "SaveImage",
                "inputs": {"images": ["60", 0],
                           "filename_prefix": "gimp_wan_i2v_frames"}}

    return wf


# ── Klein img2img (Flux 2 Klein) ─────────────────────────────────────────

KLEIN_MODELS = {
    "Klein 9B": {
        "unet": "A-Flux\\Flux2\\flux-2-klein-9b.safetensors",
        "clip": "qwen_3_8b_fp8mixed.safetensors",
    },
    "Klein 4B": {
        "unet": "A-Flux\\flux-2-klein-4b-fp8.safetensors",
        "clip": "qwen_3_4b.safetensors",
    },
    "Klein Base 4B": {
        "unet": "A-Flux\\flux-2-klein-base-4b-fp8.safetensors",
        "clip": "qwen_3_4b.safetensors",
    },
}

KLEIN_DEFAULTS = {
    "steps": 4, "cfg": 1.0, "denoise": 0.65,
    "sampler": "euler", "scheduler": "simple",
    "guidance": 1.0,
    "enhancer_magnitude": 1.0, "enhancer_contrast": 0.0,
    "text_ref_balance": 0.5,
}


def _build_klein_img2img(image_filename, klein_model_key, prompt_text, seed,
                          steps=4, denoise=0.65, guidance=1.0,
                          enhancer_mag=1.0, enhancer_contrast=0.0,
                          lora_name=None, lora_strength=1.0):
    """Flux 2 Klein distilled img2img using SamplerCustomAdvanced + ReferenceLatent.

    Architecture (matches working server workflows):
      CLIPLoader(qwen_3_8b, flux2) → CLIPTextEncode → positive cond
      ConditioningZeroOut → negative cond
      LoadImage → ImageScaleToTotalPixels(1MP) → VAEEncode → latent ref
      ReferenceLatent(positive + latent) → CFGGuider
      ReferenceLatent(negative + latent) → CFGGuider
      GetImageSize → EmptyFlux2LatentImage + Flux2Scheduler
      SamplerCustomAdvanced → VAEDecode → SaveImage
    """
    km = KLEIN_MODELS[klein_model_key]

    wf = {
        # Model loaders
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": km["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
                         "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "flux2-vae.safetensors"}},

        # Text conditioning
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["4", 0]}},

        # Input image processing
        "10": {"class_type": "LoadImage",
               "inputs": {"image": image_filename}},
        "11": {"class_type": "ImageScaleToTotalPixels",
               "inputs": {"image": ["10", 0], "upscale_method": "nearest-exact",
                          "megapixels": 1.0, "resolution_steps": 1}},
        "12": {"class_type": "GetImageSize",
               "inputs": {"image": ["11", 0]}},

        # Encode reference image to latent
        "13": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["11", 0], "vae": ["3", 0]}},

        # ReferenceLatent: wrap conditioning with image latent for img2img
        "20": {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["4", 0], "latent": ["13", 0]}},
        "21": {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["5", 0], "latent": ["13", 0]}},

        # Sampler setup
        "30": {"class_type": "CFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["20", 0],
                          "negative": ["21", 0], "cfg": guidance}},
        "31": {"class_type": "KSamplerSelect",
               "inputs": {"sampler_name": "euler"}},
        "32": {"class_type": "Flux2Scheduler",
               "inputs": {"steps": steps,
                          "width": ["12", 0], "height": ["12", 1]}},
        "33": {"class_type": "RandomNoise",
               "inputs": {"noise_seed": seed}},
        "34": {"class_type": "EmptyFlux2LatentImage",
               "inputs": {"width": ["12", 0], "height": ["12", 1],
                          "batch_size": 1}},

        # Sample
        "40": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["33", 0], "guider": ["30", 0],
                          "sampler": ["31", 0], "sigmas": ["32", 0],
                          "latent_image": ["34", 0]}},

        # Decode and save
        "50": {"class_type": "VAEDecode",
               "inputs": {"samples": ["40", 0], "vae": ["3", 0]}},
        "51": {"class_type": "SaveImage",
               "inputs": {"images": ["50", 0], "filename_prefix": "gimp_klein"}},
    }
    return wf


def _build_klein_img2img_ref(image_filename, ref_filename, klein_model_key,
                              prompt_text, seed, steps=4, denoise=0.65,
                              guidance=1.0, enhancer_mag=1.0, enhancer_contrast=0.0,
                              ref_strength=1.0, text_ref_balance=0.5,
                              lora_name=None, lora_strength=1.0):
    """Flux 2 Klein distilled img2img with reference image.

    Same architecture as _build_klein_img2img but uses the reference image
    as the ReferenceLatent source instead of the main input image.
    The main input image is used as the base for editing.
    """
    km = KLEIN_MODELS[klein_model_key]

    wf = {
        # Model loaders
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": km["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": km.get("clip", "qwen_3_8b_fp8mixed.safetensors"),
                         "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "flux2-vae.safetensors"}},

        # Text conditioning
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_text, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["4", 0]}},

        # Main input image processing
        "10": {"class_type": "LoadImage",
               "inputs": {"image": image_filename}},
        "11": {"class_type": "ImageScaleToTotalPixels",
               "inputs": {"image": ["10", 0], "upscale_method": "nearest-exact",
                          "megapixels": 1.0, "resolution_steps": 1}},
        "12": {"class_type": "GetImageSize",
               "inputs": {"image": ["11", 0]}},

        # Encode main image to latent for reference
        "13": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["11", 0], "vae": ["3", 0]}},

        # Reference image (style/structure source)
        "15": {"class_type": "LoadImage",
               "inputs": {"image": ref_filename}},
        "16": {"class_type": "ImageScaleToTotalPixels",
               "inputs": {"image": ["15", 0], "upscale_method": "nearest-exact",
                          "megapixels": 1.0, "resolution_steps": 1}},
        "17": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["16", 0], "vae": ["3", 0]}},

        # ReferenceLatent: use main image latent for conditioning
        "20": {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["4", 0], "latent": ["13", 0]}},
        "21": {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["5", 0], "latent": ["13", 0]}},

        # Sampler setup
        "30": {"class_type": "CFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["20", 0],
                          "negative": ["21", 0], "cfg": guidance}},
        "31": {"class_type": "KSamplerSelect",
               "inputs": {"sampler_name": "euler"}},
        "32": {"class_type": "Flux2Scheduler",
               "inputs": {"steps": steps,
                          "width": ["12", 0], "height": ["12", 1]}},
        "33": {"class_type": "RandomNoise",
               "inputs": {"noise_seed": seed}},
        "34": {"class_type": "EmptyFlux2LatentImage",
               "inputs": {"width": ["12", 0], "height": ["12", 1],
                          "batch_size": 1}},

        # Sample
        "40": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["33", 0], "guider": ["30", 0],
                          "sampler": ["31", 0], "sigmas": ["32", 0],
                          "latent_image": ["34", 0]}},

        # Decode and save
        "50": {"class_type": "VAEDecode",
               "inputs": {"samples": ["40", 0], "vae": ["3", 0]}},
        "51": {"class_type": "SaveImage",
               "inputs": {"images": ["50", 0], "filename_prefix": "gimp_klein_ref"}},
    }
    return wf


# ═══════════════════════════════════════════════════════════════════════════
#  Image export / import helpers
# ═══════════════════════════════════════════════════════════════════════════

def _write_rgb_png(filepath, width, height, pixel_rows):
    """Write an RGB PNG from raw pixel row data. Pure Python, no GIMP calls."""
    def _png_chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    with open(filepath, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
        f.write(_png_chunk(b'IHDR', ihdr))
        compressed = zlib.compress(b''.join(pixel_rows))
        f.write(_png_chunk(b'IDAT', compressed))
        f.write(_png_chunk(b'IEND', b''))


def _pdb_run(proc_name, props=None):
    """Run a GIMP 3 PDB procedure using lookup_procedure / create_config / run.
    Returns the Gimp.ValueArray result."""
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure(proc_name)
    if proc is None:
        raise RuntimeError(f"PDB procedure '{proc_name}' not found")
    cfg = proc.create_config()
    if props:
        for k, v in props.items():
            cfg.set_property(k, v)
    return proc.run(cfg)


def _export_image_to_tmp(image):
    """Export flattened image to a temp PNG.
    Tries multiple strategies from fastest to most reliable.
    Uses GIMP 3 direct methods + lookup/config/run PDB pattern."""
    errors = []

    # --- Duplicate & flatten using direct methods ---------------------------
    try:
        dup = image.duplicate()
    except Exception as e:
        raise RuntimeError(f"image.duplicate() failed: {e}")

    try:
        dup.flatten()
        flat = dup.get_layers()[0]
    except Exception as e:
        dup.delete()
        raise RuntimeError(f"image.flatten() failed: {e}")

    w = dup.get_width()
    h = dup.get_height()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    # CRITICAL: Gio.File only works with forward slashes on Windows
    tmp_path = tmp.name.replace("\\", "/")
    gfile = Gio.File.new_for_path(tmp_path)

    def _cleanup_dup():
        try:
            dup.delete()
        except Exception:
            pass

    def _file_ok():
        try:
            return os.path.getsize(tmp.name) > 100
        except Exception:
            return False

    # --- Strategy 1: Gimp.file_save (Python API) ----------------------------
    try:
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, [flat], gfile)
        if _file_ok():
            _cleanup_dup()
            return tmp.name
        errors.append("Gimp.file_save: wrote 0 or too few bytes")
    except Exception as e:
        errors.append(f"Gimp.file_save: {e}")

    # --- Strategy 2: PDB gimp-file-save via config --------------------------
    try:
        _pdb_run('gimp-file-save', {
            'run-mode': Gimp.RunMode.NONINTERACTIVE,
            'image': dup,
            'file': gfile,
        })
        if _file_ok():
            _cleanup_dup()
            return tmp.name
        errors.append("gimp-file-save: wrote 0 or too few bytes")
    except Exception as e:
        errors.append(f"gimp-file-save: {e}")

    # --- Strategy 3: PDB file-png-export / file-png-save via config ---------
    for proc_name in ['file-png-export', 'file-png-save']:
        try:
            pdb = Gimp.get_pdb()
            if pdb.lookup_procedure(proc_name) is None:
                errors.append(f"{proc_name}: not found")
                continue
            _pdb_run(proc_name, {
                'run-mode': Gimp.RunMode.NONINTERACTIVE,
                'image': dup,
                'file': gfile,
            })
            if _file_ok():
                _cleanup_dup()
                return tmp.name
            errors.append(f"{proc_name}: wrote 0 or too few bytes")
        except Exception as e:
            errors.append(f"{proc_name}: {e}")

    # --- Strategy 4: Read pixels + write PNG in pure Python -----------------
    try:
        Gimp.progress_set_text("Reading pixels (fallback export)...")
        rows = []
        for y in range(h):
            row = bytearray()
            for x in range(w):
                res = _pdb_run('gimp-drawable-get-pixel', {
                    'drawable': flat,
                    'x-coord': x,
                    'y-coord': y,
                })
                num_ch = res.index(1)
                pixel = res.index(2)
                if num_ch >= 3:
                    row.extend([pixel[0], pixel[1], pixel[2]])
                elif num_ch == 1:
                    row.extend([pixel[0], pixel[0], pixel[0]])
                else:
                    row.extend([0, 0, 0])
            rows.append(b'\x00' + bytes(row))
            if y % 64 == 0:
                Gimp.progress_update(y / h)

        _cleanup_dup()
        _write_rgb_png(tmp.name, w, h, rows)
        if _file_ok():
            return tmp.name
        errors.append("pixel-read: wrote invalid PNG")
    except Exception as e:
        errors.append(f"pixel-read: {e}")

    # --- All strategies failed -----------------------------------------------
    _cleanup_dup()
    try:
        os.unlink(tmp.name)
    except Exception:
        pass
    raise RuntimeError(
        "All export strategies failed:\n" + "\n".join(f"  {i+1}. {e}" for i, e in enumerate(errors))
    )

def _get_selection_bounds(image):
    """Return (has_selection, x1, y1, x2, y2) for the image's selection.
    Returns (False, 0, 0, w, h) if no selection or the selection covers everything."""
    w, h = image.get_width(), image.get_height()
    try:
        bounds = _pdb_run('gimp-selection-bounds', {'image': image})
        has_sel = bool(bounds.index(1))
        if not has_sel:
            return False, 0, 0, w, h
        x1 = int(bounds.index(2)); y1 = int(bounds.index(3))
        x2 = int(bounds.index(4)); y2 = int(bounds.index(5))
        # If selection covers the entire canvas, treat as no selection
        if x1 == 0 and y1 == 0 and x2 == w and y2 == h:
            return False, 0, 0, w, h
        return True, x1, y1, x2, y2
    except Exception:
        return False, 0, 0, w, h


def _export_selection_to_tmp(image):
    """Export only the selection region of the image as a cropped PNG.
    Duplicates the image, flattens, crops to selection bounds, and exports.
    Returns (tmp_path, sel_width, sel_height) or falls back to full image."""
    has_sel, x1, y1, x2, y2 = _get_selection_bounds(image)
    if not has_sel:
        path = _export_image_to_tmp(image)
        return path, image.get_width(), image.get_height()

    sel_w = x2 - x1
    sel_h = y2 - y1

    try:
        dup = image.duplicate()
    except Exception as e:
        raise RuntimeError(f"image.duplicate() failed: {e}")

    try:
        # Remove the selection so flatten doesn't create marching ants artifacts
        _pdb_run('gimp-selection-none', {'image': dup})
        dup.flatten()
        # Crop to the selection region
        _pdb_run('gimp-image-crop', {
            'image': dup,
            'new-width': sel_w,
            'new-height': sel_h,
            'offx': x1,
            'offy': y1,
        })
    except Exception as e:
        dup.delete()
        raise RuntimeError(f"Crop to selection failed: {e}")

    flat = dup.get_layers()[0]
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    tmp_path = tmp.name.replace("\\", "/")
    gfile = Gio.File.new_for_path(tmp_path)

    try:
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, [flat], gfile)
        if os.path.getsize(tmp.name) > 100:
            dup.delete()
            return tmp.name, sel_w, sel_h
    except Exception:
        pass

    # Fallback: PDB save
    try:
        _pdb_run('gimp-file-save', {
            'run-mode': Gimp.RunMode.NONINTERACTIVE,
            'image': dup, 'file': gfile,
        })
        if os.path.getsize(tmp.name) > 100:
            dup.delete()
            return tmp.name, sel_w, sel_h
    except Exception:
        pass

    dup.delete()
    raise RuntimeError("Failed to export selection region")


def _import_result_as_layer(image, image_data, layer_name="ComfyUI Result"):
    """Import raw PNG bytes as a new layer on top of *image*.

    Handles mode mismatches (e.g. ComfyUI returns a grayscale PNG but the
    canvas is RGB) by converting the loaded result to match the destination
    image's colour mode before inserting the layer.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(image_data)
    tmp.close()
    file = Gio.File.new_for_path(tmp.name.replace("\\", "/"))
    result_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, file)
    layers = result_image.get_layers()
    if not layers:
        result_image.delete()
        os.unlink(tmp.name)
        return

    # ── Ensure the result image matches the destination colour mode ─────
    dest_type = image.get_base_type()      # e.g. Gimp.ImageBaseType.RGB
    src_type = result_image.get_base_type()
    if src_type != dest_type:
        try:
            if dest_type == Gimp.ImageBaseType.RGB:
                _pdb_run('gimp-image-convert-rgb', {'image': result_image})
            elif dest_type == Gimp.ImageBaseType.GRAY:
                _pdb_run('gimp-image-convert-grayscale', {'image': result_image})
            elif dest_type == Gimp.ImageBaseType.INDEXED:
                _pdb_run('gimp-image-convert-indexed', {
                    'image': result_image,
                    'dither-type': 0, 'palette-type': 0,
                    'num-cols': 256, 'alpha-dither': False,
                    'remove-unused': False, 'palette': "",
                })
        except Exception:
            pass  # best-effort; insert_layer will fail with a clear error

    layers = result_image.get_layers()  # re-fetch after conversion
    new_layer = Gimp.Layer.new_from_drawable(layers[0], image)
    new_layer.set_name(layer_name)
    image.insert_layer(new_layer, None, 0)
    if (new_layer.get_width() != image.get_width() or
            new_layer.get_height() != image.get_height()):
        new_layer.scale(image.get_width(), image.get_height(), False)
    result_image.delete()
    os.unlink(tmp.name)
    Gimp.displays_flush()

def _run_comfyui_workflow(server, workflow, timeout=300):
    result = _api_post_json(server, "/prompt", {"prompt": workflow})
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return a prompt_id: {result}")
    return _get_output_images(server, prompt_id, timeout)



def _async_fetch(fetch_fn, on_done, on_error):
    def worker():
        try:
            res = fetch_fn()
            GLib.idle_add(on_done, res)
        except Exception as e:
            GLib.idle_add(on_error, e)
    threading.Thread(target=worker, daemon=True).start()

def _run_with_spinner(label_text, func, *args):
    """Run func(*args) in a background thread, show a spinner window, return result."""
    result_box = [None]
    error_box = [None]
    done_box = [False]
    loop = GLib.MainLoop()

    win = Gtk.Window(title="Spellcaster")
    win.set_default_size(320, 100)
    win.set_deletable(False)
    win.set_position(Gtk.WindowPosition.CENTER)
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    vbox.set_margin_start(16); vbox.set_margin_end(16)
    vbox.set_margin_top(12); vbox.set_margin_bottom(12)
    spinner = Gtk.Spinner(); spinner.start()
    label = Gtk.Label(label=label_text)
    pb = Gtk.ProgressBar(); pb.set_pulse_step(0.1)
    vbox.pack_start(spinner, False, False, 0)
    vbox.pack_start(label, False, False, 0)
    vbox.pack_start(pb, False, False, 0)
    win.add(vbox); win.show_all()

    def _pulse():
        if not done_box[0]:
            pb.pulse()
            return True
        return False
    GLib.timeout_add(300, _pulse)

    def _worker():
        try:
            result_box[0] = func(*args)
        except Exception as e:
            error_box[0] = e
        finally:
            done_box[0] = True
            GLib.idle_add(loop.quit)

    threading.Thread(target=_worker, daemon=True).start()
    loop.run()
    win.destroy()
    if error_box[0]:
        raise error_box[0]
    return result_box[0]


# ═══════════════════════════════════════════════════════════════════════════
#  GTK Dialog with model-preset selector
# ═══════════════════════════════════════════════════════════════════════════

class PresetDialog(Gtk.Dialog):
    """Pick a model preset, tweak params, enter prompt, go."""

    def __init__(self, title, mode="img2img", server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title=title)
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.mode = mode

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        self._conn_label = Gtk.Label()
        self._conn_label.set_xalign(0)
        box.pack_start(self._conn_label, False, False, 0)

        # Model preset
        box.pack_start(Gtk.Label(label="Model Preset:", xalign=0), False, False, 0)
        self.preset_combo = Gtk.ComboBoxText()
        for i, p in enumerate(MODEL_PRESETS):
            self.preset_combo.append(str(i), p["label"])
        self.preset_combo.set_active(0)
        self.preset_combo.connect("changed", self._on_preset_changed)
        box.pack_start(self.preset_combo, False, False, 0)

        # Inpaint refinement dropdown (only in inpaint mode)
        self._refinement_combo = None
        if mode == "inpaint":
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
            box.pack_start(Gtk.Label(label="Body Part / Refinement Preset:", xalign=0), False, False, 0)
            self._refinement_combo = Gtk.ComboBoxText()
            for i, ref in enumerate(INPAINT_REFINEMENTS):
                self._refinement_combo.append(str(i), ref["label"])
            self._refinement_combo.set_active(0)
            self._refinement_combo.connect("changed", self._on_refinement_changed)
            box.pack_start(self._refinement_combo, False, False, 0)
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # Prompt
        box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        self.prompt_tv = Gtk.TextView()
        self.prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw = Gtk.ScrolledWindow(); sw.set_min_content_height(60); sw.add(self.prompt_tv)
        box.pack_start(sw, False, False, 0)

        # Negative
        box.pack_start(Gtk.Label(label="Negative:", xalign=0), False, False, 0)
        self.neg_tv = Gtk.TextView()
        self.neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw2 = Gtk.ScrolledWindow(); sw2.set_min_content_height(40); sw2.add(self.neg_tv)
        box.pack_start(sw2, False, False, 0)

        # Params
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        r = 0
        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, r, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 150, 1)
        grid.attach(self.steps_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="CFG:", xalign=1), 2, r, 1, 1)
        self.cfg_spin = Gtk.SpinButton.new_with_range(1.0, 30.0, 0.5)
        self.cfg_spin.set_digits(1)
        grid.attach(self.cfg_spin, 3, r, 1, 1)
        r += 1

        if mode in ("img2img", "inpaint"):
            grid.attach(Gtk.Label(label="Denoise:", xalign=1), 0, r, 1, 1)
            self.denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
            self.denoise_spin.set_digits(2)
            grid.attach(self.denoise_spin, 1, r, 1, 1)
            r += 1
        else:
            self.denoise_spin = None

        grid.attach(Gtk.Label(label="Width:", xalign=1), 0, r, 1, 1)
        self.w_spin = Gtk.SpinButton.new_with_range(64, 4096, 64)
        grid.attach(self.w_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Height:", xalign=1), 2, r, 1, 1)
        self.h_spin = Gtk.SpinButton.new_with_range(64, 4096, 64)
        grid.attach(self.h_spin, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Seed (-1=rand):", xalign=1), 0, r, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**31, 1)
        self.seed_spin.set_value(-1)
        grid.attach(self.seed_spin, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Sampler:", xalign=1), 0, r, 1, 1)
        self.sampler_entry = Gtk.Entry()
        grid.attach(self.sampler_entry, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Scheduler:", xalign=1), 2, r, 1, 1)
        self.scheduler_entry = Gtk.Entry()
        grid.attach(self.scheduler_entry, 3, r, 1, 1)

        box.pack_start(grid, False, False, 0)

        # LoRA section
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        lora_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lora_hdr.pack_start(Gtk.Label(label="LoRA (optional):", xalign=0), False, False, 0)
        self._lora_fetch_btn = Gtk.Button(label="Fetch LoRAs")
        self._lora_fetch_btn.connect("clicked", self._on_fetch_loras)
        lora_hdr.pack_end(self._lora_fetch_btn, False, False, 0)
        box.pack_start(lora_hdr, False, False, 0)

        self._all_lora_names = []   # full server list (unfiltered)
        self._lora_names = []       # currently displayed (filtered by arch)
        self.lora_rows = []         # list of (combo, model_spin, clip_spin)
        self._lora_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for slot in range(3):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            combo = Gtk.ComboBoxText()
            combo.append("none", "(none)")
            combo.set_active(0)
            combo.set_hexpand(True)
            row.pack_start(combo, True, True, 0)

            row.pack_start(Gtk.Label(label="Str:"), False, False, 0)
            ms = Gtk.SpinButton.new_with_range(-5.0, 5.0, 0.05)
            ms.set_digits(2); ms.set_value(1.0)
            ms.set_tooltip_text("Model strength")
            row.pack_start(ms, False, False, 0)

            row.pack_start(Gtk.Label(label="CLIP:"), False, False, 0)
            cs = Gtk.SpinButton.new_with_range(-5.0, 5.0, 0.05)
            cs.set_digits(2); cs.set_value(1.0)
            cs.set_tooltip_text("CLIP strength")
            row.pack_start(cs, False, False, 0)

            self.lora_rows.append((combo, ms, cs))
            self._lora_box.pack_start(row, False, False, 0)
        box.pack_start(self._lora_box, False, False, 0)

        # Mode label
        if mode == "img2img":
            box.pack_start(Gtk.Label(label="Sends current canvas through model preset.", xalign=0), False, False, 0)
        elif mode == "txt2img":
            box.pack_start(Gtk.Label(label="Generate new image from prompt only.", xalign=0), False, False, 0)

        # Advanced custom workflow
        exp = Gtk.Expander(label="Advanced: Custom Workflow JSON (overrides everything)")
        self.wf_tv = Gtk.TextView()
        self.wf_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.wf_tv.set_monospace(True)
        sw3 = Gtk.ScrolledWindow(); sw3.set_min_content_height(80); sw3.add(self.wf_tv)
        exp.add(sw3)
        box.pack_start(exp, False, False, 0)

        box.show_all()
        self._apply_preset(0)

        # Auto-fetch LoRAs on dialog open
        GLib.idle_add(self._on_fetch_loras, None)

    def _on_fetch_loras(self, _btn):
        server = self.server_entry.get_text().strip()
        self._lora_fetch_btn.set_label("Fetching...")
        def on_done(res):
            self._all_lora_names = res
            self._conn_label.set_markup('<span color="green">● Connected</span>')
            self._refresh_lora_combos()
        def on_err(e):
            self._all_lora_names = []
            self._conn_label.set_markup(f'<span color="red">⚠ Cannot connect to {server}</span>')
            self._refresh_lora_combos()
        _async_fetch(lambda: _fetch_loras(server), on_done, on_err)

    def _refresh_lora_combos(self):
        """Filter cached LoRAs for the currently selected model's architecture."""
        idx = self.preset_combo.get_active()
        arch = MODEL_PRESETS[idx]["arch"] if idx >= 0 else "sdxl"
        self._lora_names = _filter_loras_for_arch(self._all_lora_names, arch)
        for combo, _ms, _cs in self.lora_rows:
            combo.remove_all()
            combo.append("none", "(none)")
            for lname in self._lora_names:
                short = lname.rsplit("\\", 1)[-1] if "\\" in lname else lname
                combo.append(lname, short)
            combo.set_active(0)
        total = len(self._all_lora_names)
        shown = len(self._lora_names)
        self._lora_fetch_btn.set_label(f"{shown}/{total} LoRAs ({arch})")

    def _on_preset_changed(self, combo):
        idx = combo.get_active()
        if idx >= 0:
            self._apply_preset(idx)
            # Re-filter LoRAs for the new architecture
            if self._all_lora_names:
                self._refresh_lora_combos()

    def _apply_preset(self, idx):
        p = MODEL_PRESETS[idx]
        self.steps_spin.set_value(p["steps"])
        self.cfg_spin.set_value(p["cfg"])
        if self.denoise_spin:
            self.denoise_spin.set_value(p["denoise"])
        self.w_spin.set_value(p["width"])
        self.h_spin.set_value(p["height"])
        self.sampler_entry.set_text(p["sampler"])
        self.scheduler_entry.set_text(p["scheduler"])
        # Pre-fill prompt hints (only if empty)
        buf = self.prompt_tv.get_buffer()
        if buf.get_char_count() == 0:
            buf.set_text(p["prompt_hint"])
        buf2 = self.neg_tv.get_buffer()
        if buf2.get_char_count() == 0:
            buf2.set_text(p["negative_hint"])
        # Re-apply refinement if one is active (to update LoRAs for new arch)
        if self._refinement_combo and self._refinement_combo.get_active() > 0:
            self._on_refinement_changed(self._refinement_combo)

    def _on_refinement_changed(self, combo):
        """Apply an inpaint refinement preset: fill prompt, negative, denoise, settings, LoRAs."""
        ridx = combo.get_active()
        if ridx < 0:
            return
        ref = INPAINT_REFINEMENTS[ridx]
        if ridx == 0:
            return  # "(none)" — don't touch anything

        # Fill prompt and negative (always overwrite for refinements)
        self.prompt_tv.get_buffer().set_text(ref["prompt"])
        self.neg_tv.get_buffer().set_text(ref["negative"])

        # Apply denoise override
        if ref["denoise"] is not None and self.denoise_spin:
            self.denoise_spin.set_value(ref["denoise"])

        # Apply steps override
        if ref["steps_override"] is not None:
            self.steps_spin.set_value(ref["steps_override"])

        # Apply CFG boost (add to model's base CFG)
        if ref["cfg_boost"]:
            midx = self.preset_combo.get_active()
            base_cfg = MODEL_PRESETS[midx]["cfg"] if midx >= 0 else 7.0
            self.cfg_spin.set_value(base_cfg + ref["cfg_boost"])

        # Auto-select matching LoRAs for current model architecture
        midx = self.preset_combo.get_active()
        arch = MODEL_PRESETS[midx]["arch"] if midx >= 0 else "sdxl"
        rec_loras = ref["loras"].get(arch, [])

        # Clear all LoRA slots first
        for combo_w, ms, cs in self.lora_rows:
            combo_w.set_active(0)  # "(none)"
            ms.set_value(1.0)
            cs.set_value(1.0)

        # Fill LoRA slots with recommended LoRAs (if they exist on the server)
        slot = 0
        for lora_path, model_str, clip_str in rec_loras:
            if slot >= len(self.lora_rows):
                break
            combo_w, ms, cs = self.lora_rows[slot]
            # Find this LoRA in the combo items
            found = False
            for j, lname in enumerate(self._lora_names):
                if lname == lora_path:
                    combo_w.set_active(j + 1)  # +1 because index 0 is "(none)"
                    ms.set_value(model_str)
                    cs.set_value(clip_str)
                    found = True
                    slot += 1
                    break
            if not found:
                # LoRA not available — skip this slot, try next recommended LoRA
                continue

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def get_values(self):
        idx = self.preset_combo.get_active()
        preset = dict(MODEL_PRESETS[idx] if idx >= 0 else MODEL_PRESETS[0])
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        custom_wf = self._buf_text(self.wf_tv).strip()
        preset["steps"] = int(self.steps_spin.get_value())
        preset["cfg"] = self.cfg_spin.get_value()
        preset["denoise"] = self.denoise_spin.get_value() if self.denoise_spin else 1.0
        preset["width"] = int(self.w_spin.get_value())
        preset["height"] = int(self.h_spin.get_value())
        preset["sampler"] = self.sampler_entry.get_text().strip()
        preset["scheduler"] = self.scheduler_entry.get_text().strip()
        # Collect active LoRAs
        loras = []
        for combo, ms, cs in self.lora_rows:
            lora_id = combo.get_active_id()
            if lora_id and lora_id != "none":
                loras.append({
                    "name": lora_id,
                    "strength_model": ms.get_value(),
                    "strength_clip": cs.get_value(),
                })
        return {
            "server": self.server_entry.get_text().strip(),
            "preset": preset,
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "seed": seed,
            "loras": loras,
            "custom_workflow": custom_wf if custom_wf else None,
        }

# ═══════════════════════════════════════════════════════════════════════════
#  Face Swap Dialog
# ═══════════════════════════════════════════════════════════════════════════

class FaceSwapDialog(Gtk.Dialog):
    """Pick a source face image from disk, choose swap model, run ReActor."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - Face Swap (ReActor)")
        self.set_default_size(500, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Swap", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Source face file chooser
        box.pack_start(Gtk.Label(label="Source Face Image:", xalign=0), False, False, 0)
        self.face_chooser = Gtk.FileChooserButton(title="Select face source image")
        self.face_chooser.set_action(Gtk.FileChooserAction.OPEN)
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_pattern("*.png"); ff.add_pattern("*.jpg"); ff.add_pattern("*.jpeg")
        ff.add_pattern("*.webp"); ff.add_pattern("*.bmp")
        self.face_chooser.add_filter(ff)
        box.pack_start(self.face_chooser, False, False, 0)

        # Fetch models button
        self._fetch_btn = Gtk.Button(label="Fetch Models from Server")
        self._fetch_btn.connect("clicked", self._on_fetch_models)
        box.pack_start(self._fetch_btn, False, False, 0)

        # Swap model
        box.pack_start(Gtk.Label(label="Swap Model:", xalign=0), False, False, 0)
        self.swap_combo = Gtk.ComboBoxText()
        for m in FACE_SWAP_MODELS:
            self.swap_combo.append(m, m)
        self.swap_combo.set_active(0)
        box.pack_start(self.swap_combo, False, False, 0)

        # Face restore
        box.pack_start(Gtk.Label(label="Face Restore Model:", xalign=0), False, False, 0)
        self.restore_combo = Gtk.ComboBoxText()
        for m in FACE_RESTORE_MODELS:
            self.restore_combo.append(m, m)
        self.restore_combo.set_active(1)  # codeformer default
        box.pack_start(self.restore_combo, False, False, 0)

        # Restore visibility + codeformer weight
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label="Restore Visibility:", xalign=1), 0, 0, 1, 1)
        self.restore_vis = Gtk.SpinButton.new_with_range(0.1, 1.0, 0.05)
        self.restore_vis.set_digits(2); self.restore_vis.set_value(1.0)
        grid.attach(self.restore_vis, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="CodeFormer Weight:", xalign=1), 0, 1, 1, 1)
        self.cf_weight = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.cf_weight.set_digits(2); self.cf_weight.set_value(0.5)
        grid.attach(self.cf_weight, 1, 1, 1, 1)
        box.pack_start(grid, False, False, 0)

        # Face indices
        grid2 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid2.attach(Gtk.Label(label="Input Face Index:", xalign=1), 0, 0, 1, 1)
        self.input_idx = Gtk.Entry(); self.input_idx.set_text("0")
        grid2.attach(self.input_idx, 1, 0, 1, 1)
        grid2.attach(Gtk.Label(label="Source Face Index:", xalign=1), 0, 1, 1, 1)
        self.source_idx = Gtk.Entry(); self.source_idx.set_text("0")
        grid2.attach(self.source_idx, 1, 1, 1, 1)
        box.pack_start(grid2, False, False, 0)

        # Gender filter
        grid3 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid3.attach(Gtk.Label(label="Filter Input Gender:", xalign=1), 0, 0, 1, 1)
        self.gender_input = Gtk.ComboBoxText()
        for g in ["no", "female", "male"]:
            self.gender_input.append(g, g)
        self.gender_input.set_active(0)
        grid3.attach(self.gender_input, 1, 0, 1, 1)
        grid3.attach(Gtk.Label(label="Filter Source Gender:", xalign=1), 0, 1, 1, 1)
        self.gender_source = Gtk.ComboBoxText()
        for g in ["no", "female", "male"]:
            self.gender_source.append(g, g)
        self.gender_source.set_active(0)
        grid3.attach(self.gender_source, 1, 1, 1, 1)
        box.pack_start(grid3, False, False, 0)

        box.show_all()

        # Auto-fetch models on dialog open
        self._on_fetch_models(None)

    def _on_fetch_models(self, _btn):
        """Fetch swap and restore model lists from the ComfyUI server."""
        server = self.server_entry.get_text().strip()
        try:
            swap_list, restore_list = _fetch_reactor_models(server)
        except Exception:
            swap_list, restore_list = [], []

        if swap_list:
            self.swap_combo.remove_all()
            for m in swap_list:
                self.swap_combo.append(m, m)
            self.swap_combo.set_active(0)

        if restore_list:
            self.restore_combo.remove_all()
            for m in restore_list:
                self.restore_combo.append(m, m)
            # Try to default to codeformer
            for i, m in enumerate(restore_list):
                if "codeformer" in m.lower():
                    self.restore_combo.set_active(i)
                    break
            else:
                self.restore_combo.set_active(0)

        n_swap = len(swap_list) if swap_list else len(FACE_SWAP_MODELS)
        n_rest = len(restore_list) if restore_list else len(FACE_RESTORE_MODELS)
        src = "server" if swap_list else "local"
        self._fetch_btn.set_label(f"Models: {n_swap} swap, {n_rest} restore ({src})")

    def get_values(self):
        face_file = self.face_chooser.get_filename()
        return {
            "server": self.server_entry.get_text().strip(),
            "face_file": face_file,
            "swap_model": self.swap_combo.get_active_id() or FACE_SWAP_MODELS[0],
            "face_restore_model": self.restore_combo.get_active_id() or "codeformer-v0.1.0.pth",
            "face_restore_vis": self.restore_vis.get_value(),
            "codeformer_weight": self.cf_weight.get_value(),
            "input_face_idx": self.input_idx.get_text().strip() or "0",
            "source_face_idx": self.source_idx.get_text().strip() or "0",
            "detect_gender_input": self.gender_input.get_active_id() or "no",
            "detect_gender_source": self.gender_source.get_active_id() or "no",
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Face Swap with Saved Face Model Dialog
# ═══════════════════════════════════════════════════════════════════════════

class FaceSwapModelDialog(Gtk.Dialog):
    """Face swap using a saved face model from the server (no source image needed)."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - Face Swap (Saved Face Model)")
        self.set_default_size(500, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Swap", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Fetch button
        self._fetch_btn = Gtk.Button(label="Fetch Models from Server")
        self._fetch_btn.connect("clicked", self._on_fetch_models)
        box.pack_start(self._fetch_btn, False, False, 0)

        # Face model selector
        box.pack_start(Gtk.Label(label="Face Model:", xalign=0), False, False, 0)
        self.face_model_combo = Gtk.ComboBoxText()
        self.face_model_combo.append("none", "(none — select a model)")
        self.face_model_combo.set_active(0)
        box.pack_start(self.face_model_combo, False, False, 0)

        # Swap model
        box.pack_start(Gtk.Label(label="Swap Model:", xalign=0), False, False, 0)
        self.swap_combo = Gtk.ComboBoxText()
        for m in FACE_SWAP_MODELS:
            self.swap_combo.append(m, m)
        self.swap_combo.set_active(0)
        box.pack_start(self.swap_combo, False, False, 0)

        # Face restore
        box.pack_start(Gtk.Label(label="Face Restore Model:", xalign=0), False, False, 0)
        self.restore_combo = Gtk.ComboBoxText()
        for m in FACE_RESTORE_MODELS:
            self.restore_combo.append(m, m)
        self.restore_combo.set_active(1)
        box.pack_start(self.restore_combo, False, False, 0)

        # Restore visibility + codeformer weight
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid.attach(Gtk.Label(label="Restore Visibility:", xalign=1), 0, 0, 1, 1)
        self.restore_vis = Gtk.SpinButton.new_with_range(0.1, 1.0, 0.05)
        self.restore_vis.set_digits(2); self.restore_vis.set_value(1.0)
        grid.attach(self.restore_vis, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="CodeFormer Weight:", xalign=1), 0, 1, 1, 1)
        self.cf_weight = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.cf_weight.set_digits(2); self.cf_weight.set_value(0.5)
        grid.attach(self.cf_weight, 1, 1, 1, 1)
        box.pack_start(grid, False, False, 0)

        # Face indices
        grid2 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid2.attach(Gtk.Label(label="Input Face Index:", xalign=1), 0, 0, 1, 1)
        self.input_idx = Gtk.Entry(); self.input_idx.set_text("0")
        grid2.attach(self.input_idx, 1, 0, 1, 1)
        grid2.attach(Gtk.Label(label="Source Face Index:", xalign=1), 0, 1, 1, 1)
        self.source_idx = Gtk.Entry(); self.source_idx.set_text("0")
        grid2.attach(self.source_idx, 1, 1, 1, 1)
        box.pack_start(grid2, False, False, 0)

        # Gender filter
        grid3 = Gtk.Grid(column_spacing=8, row_spacing=4)
        grid3.attach(Gtk.Label(label="Filter Input Gender:", xalign=1), 0, 0, 1, 1)
        self.gender_input = Gtk.ComboBoxText()
        for g in ["no", "female", "male"]:
            self.gender_input.append(g, g)
        self.gender_input.set_active(0)
        grid3.attach(self.gender_input, 1, 0, 1, 1)
        grid3.attach(Gtk.Label(label="Filter Source Gender:", xalign=1), 0, 1, 1, 1)
        self.gender_source = Gtk.ComboBoxText()
        for g in ["no", "female", "male"]:
            self.gender_source.append(g, g)
        self.gender_source.set_active(0)
        grid3.attach(self.gender_source, 1, 1, 1, 1)
        box.pack_start(grid3, False, False, 0)

        box.show_all()
        self._on_fetch_models(None)

    def _on_fetch_models(self, _btn):
        server = self.server_entry.get_text().strip()
        # Fetch face models
        face_models = _fetch_face_models(server)
        if face_models:
            self.face_model_combo.remove_all()
            for m in face_models:
                self.face_model_combo.append(m, m)
            self.face_model_combo.set_active(0)
        # Fetch swap/restore models
        try:
            swap_list, restore_list = _fetch_reactor_models(server)
        except Exception:
            swap_list, restore_list = [], []
        if swap_list:
            self.swap_combo.remove_all()
            for m in swap_list:
                self.swap_combo.append(m, m)
            self.swap_combo.set_active(0)
        if restore_list:
            self.restore_combo.remove_all()
            for m in restore_list:
                self.restore_combo.append(m, m)
            for i, m in enumerate(restore_list):
                if "codeformer" in m.lower():
                    self.restore_combo.set_active(i); break
            else:
                self.restore_combo.set_active(0)

        n_face = len(face_models) if face_models else 0
        self._fetch_btn.set_label(f"{n_face} face models loaded")

    def get_values(self):
        return {
            "server": self.server_entry.get_text().strip(),
            "face_model": self.face_model_combo.get_active_id(),
            "swap_model": self.swap_combo.get_active_id() or FACE_SWAP_MODELS[0],
            "face_restore_model": self.restore_combo.get_active_id() or "codeformer-v0.1.0.pth",
            "face_restore_vis": self.restore_vis.get_value(),
            "codeformer_weight": self.cf_weight.get_value(),
            "input_face_idx": self.input_idx.get_text().strip() or "0",
            "source_face_idx": self.source_idx.get_text().strip() or "0",
            "detect_gender_input": self.gender_input.get_active_id() or "no",
            "detect_gender_source": self.gender_source.get_active_id() or "no",
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Wan 2.2 Image-to-Video Dialog
# ═══════════════════════════════════════════════════════════════════════════

class WanI2VDialog(Gtk.Dialog):
    """Wan 2.2 Image-to-Video with LoRA management."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - Wan 2.2 Image to Video")
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Generate", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        self._all_wan_loras = []
        self._wan_loras = []

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Model preset
        box.pack_start(Gtk.Label(label="Model Preset:", xalign=0), False, False, 0)
        self.preset_combo = Gtk.ComboBoxText()
        for key in WAN_I2V_PRESETS:
            self.preset_combo.append(key, key)
        self.preset_combo.set_active(0)
        self.preset_combo.connect("changed", self._on_preset_changed)
        box.pack_start(self.preset_combo, False, False, 0)

        # Video prompt preset (template)
        box.pack_start(Gtk.Label(label="Prompt Template:", xalign=0), False, False, 0)
        self._video_preset_combo = Gtk.ComboBoxText()
        for i, vp in enumerate(WAN_VIDEO_PRESETS):
            self._video_preset_combo.append(str(i), vp["label"])
        self._video_preset_combo.set_active(0)
        self._video_preset_combo.connect("changed", self._on_video_preset_changed)
        box.pack_start(self._video_preset_combo, False, False, 0)

        # Prompt
        box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(60)
        self.prompt_tv = Gtk.TextView()
        self.prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw.add(self.prompt_tv)
        box.pack_start(sw, False, False, 0)

        # Negative prompt
        box.pack_start(Gtk.Label(label="Negative Prompt:", xalign=0), False, False, 0)
        sw2 = Gtk.ScrolledWindow()
        sw2.set_min_content_height(40)
        self.neg_tv = Gtk.TextView()
        self.neg_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.neg_tv.get_buffer().set_text("blurry, distorted, low quality")
        sw2.add(self.neg_tv)
        box.pack_start(sw2, False, False, 0)

        # Parameters grid
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)

        grid.attach(Gtk.Label(label="Width:", xalign=1), 0, 0, 1, 1)
        self.w_spin = Gtk.SpinButton.new_with_range(16, 2048, 16)
        self.w_spin.set_value(832)
        grid.attach(self.w_spin, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Height:", xalign=1), 2, 0, 1, 1)
        self.h_spin = Gtk.SpinButton.new_with_range(16, 2048, 16)
        self.h_spin.set_value(480)
        grid.attach(self.h_spin, 3, 0, 1, 1)

        grid.attach(Gtk.Label(label="Frames:", xalign=1), 0, 1, 1, 1)
        self.length_spin = Gtk.SpinButton.new_with_range(1, 257, 4)
        self.length_spin.set_value(81)
        grid.attach(self.length_spin, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="FPS:", xalign=1), 2, 1, 1, 1)
        self.fps_spin = Gtk.SpinButton.new_with_range(1, 60, 1)
        self.fps_spin.set_value(16)
        grid.attach(self.fps_spin, 3, 1, 1, 1)

        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, 2, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.steps_spin.set_value(30)
        grid.attach(self.steps_spin, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="CFG:", xalign=1), 2, 2, 1, 1)
        self.cfg_spin = Gtk.SpinButton.new_with_range(0.0, 30.0, 0.5)
        self.cfg_spin.set_digits(1); self.cfg_spin.set_value(5.0)
        grid.attach(self.cfg_spin, 3, 2, 1, 1)

        grid.attach(Gtk.Label(label="Shift:", xalign=1), 0, 3, 1, 1)
        self.shift_spin = Gtk.SpinButton.new_with_range(0.0, 100.0, 0.5)
        self.shift_spin.set_digits(1); self.shift_spin.set_value(8.0)
        grid.attach(self.shift_spin, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="Switch Step:", xalign=1), 2, 3, 1, 1)
        self.second_step_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.second_step_spin.set_value(20)
        self.second_step_spin.set_tooltip_text(
            "Step at which sampling switches from high-noise to low-noise model")
        grid.attach(self.second_step_spin, 3, 3, 1, 1)

        grid.attach(Gtk.Label(label="Seed:", xalign=1), 0, 4, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32 - 1, 1)
        self.seed_spin.set_value(-1)
        grid.attach(self.seed_spin, 1, 4, 2, 1)

        box.pack_start(grid, False, False, 0)

        # Post-processing & output options
        pp_frame = Gtk.Frame(label="Post-processing & Output")
        pp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pp_box.set_margin_start(8); pp_box.set_margin_end(8)
        pp_box.set_margin_top(4); pp_box.set_margin_bottom(8)

        # Row 1: RTX upscale toggle + scale value
        rtx_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.upscale_check = Gtk.CheckButton(label="RTX Upscale")
        self.upscale_check.set_active(True)
        self.upscale_check.set_tooltip_text("Apply RTXVideoSuperResolution upscale")
        rtx_row.pack_start(self.upscale_check, False, False, 0)
        rtx_row.pack_start(Gtk.Label(label="Scale:"), False, False, 0)
        self.upscale_spin = Gtk.SpinButton.new_with_range(1.0, 4.0, 0.25)
        self.upscale_spin.set_digits(2); self.upscale_spin.set_value(1.5)
        self.upscale_spin.set_tooltip_text("RTX upscale factor (e.g. 1.5 = 50% larger)")
        rtx_row.pack_start(self.upscale_spin, False, False, 0)
        pp_box.pack_start(rtx_row, False, False, 0)

        # Row 2: RIFE interpolation + ping pong
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.interpolate_check = Gtk.CheckButton(label="RIFE 2× Interpolation")
        self.interpolate_check.set_active(True)
        self.interpolate_check.set_tooltip_text("Apply RIFE VFI 2× frame interpolation (doubles FPS)")
        row2.pack_start(self.interpolate_check, False, False, 0)
        self.pingpong_check = Gtk.CheckButton(label="Ping Pong")
        self.pingpong_check.set_active(False)
        self.pingpong_check.set_tooltip_text("Play video forward then backward for seamless looping")
        row2.pack_start(self.pingpong_check, False, False, 0)
        pp_box.pack_start(row2, False, False, 0)

        pp_frame.add(pp_box)
        box.pack_start(pp_frame, False, False, 0)

        # LoRA section
        lora_frame = Gtk.Frame(label="LoRAs")
        lora_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lora_box.set_margin_start(8); lora_box.set_margin_end(8)
        lora_box.set_margin_top(4); lora_box.set_margin_bottom(8)

        self._lora_fetch_btn = Gtk.Button(label="Fetch Wan LoRAs")
        self._lora_fetch_btn.connect("clicked", self._on_fetch_loras)
        lora_box.pack_start(self._lora_fetch_btn, False, False, 0)

        self.lora_rows = []
        for i in range(3):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            combo = Gtk.ComboBoxText()
            combo.append("none", "(none)")
            combo.set_active(0)
            combo.set_hexpand(True)
            row.pack_start(combo, True, True, 0)

            row.pack_start(Gtk.Label(label="Str:"), False, False, 0)
            strength = Gtk.SpinButton.new_with_range(-2.0, 2.0, 0.05)
            strength.set_digits(2); strength.set_value(1.0)
            row.pack_start(strength, False, False, 0)

            lora_box.pack_start(row, False, False, 0)
            self.lora_rows.append((combo, strength))

        lora_frame.add(lora_box)
        box.pack_start(lora_frame, False, False, 0)

        box.show_all()

    def _on_fetch_loras(self, _btn):
        server = self.server_entry.get_text().strip()
        try:
            self._all_wan_loras = _fetch_wan_video_loras(server)
        except Exception:
            self._all_wan_loras = []
        self._refresh_lora_combos()

    def _refresh_lora_combos(self):
        preset_key = self.preset_combo.get_active_id() or ""
        self._wan_loras = _filter_wan_loras(self._all_wan_loras, preset_key)
        for combo, _str in self.lora_rows:
            combo.remove_all()
            combo.append("none", "(none)")
            for lname in self._wan_loras:
                short = lname.rsplit("\\", 1)[-1] if "\\" in lname else lname
                combo.append(lname, short)
            combo.set_active(0)
        total = len(self._all_wan_loras)
        shown = len(self._wan_loras)
        self._lora_fetch_btn.set_label(f"{shown}/{total} Wan LoRAs")

    def _on_preset_changed(self, combo):
        if self._all_wan_loras:
            self._refresh_lora_combos()

    def _on_video_preset_changed(self, combo):
        """Apply a video prompt template: fill prompt, negative, and override settings."""
        vidx = combo.get_active()
        if vidx < 0:
            return
        vp = WAN_VIDEO_PRESETS[vidx]
        if vidx == 0:
            return  # "(none — manual prompt)" — don't touch anything

        # Fill prompt & negative
        self.prompt_tv.get_buffer().set_text(vp["prompt"])
        self.neg_tv.get_buffer().set_text(vp["negative"])

        # Apply optional overrides
        if vp["cfg_override"] is not None:
            self.cfg_spin.set_value(vp["cfg_override"])
        if vp["steps_override"] is not None:
            self.steps_spin.set_value(vp["steps_override"])
        if vp["length_override"] is not None:
            self.length_spin.set_value(vp["length_override"])
        if vp["pingpong"] is not None:
            self.pingpong_check.set_active(vp["pingpong"])

        # Auto-select recommended LoRAs if any & lora list is populated
        if vp["loras"] and self._wan_loras:
            for slot_idx, (lora_name, lora_str) in enumerate(vp["loras"]):
                if slot_idx >= len(self.lora_rows):
                    break
                row_combo, row_strength = self.lora_rows[slot_idx]
                # Find matching lora in combo
                found = False
                for j, name in enumerate(self._wan_loras):
                    if name == lora_name or name.endswith(lora_name):
                        row_combo.set_active(j + 1)  # +1 for "(none)" entry
                        row_strength.set_value(lora_str)
                        found = True
                        break
                if not found:
                    row_combo.set_active(0)

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def get_values(self):
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)

        loras = []
        for combo, strength in self.lora_rows:
            lid = combo.get_active_id()
            if lid and lid != "none":
                loras.append((lid, strength.get_value()))

        return {
            "server": self.server_entry.get_text().strip(),
            "preset_key": self.preset_combo.get_active_id(),
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "width": int(self.w_spin.get_value()),
            "height": int(self.h_spin.get_value()),
            "length": int(self.length_spin.get_value()),
            "fps": int(self.fps_spin.get_value()),
            "steps": int(self.steps_spin.get_value()),
            "cfg": self.cfg_spin.get_value(),
            "shift": self.shift_spin.get_value(),
            "second_step": int(self.second_step_spin.get_value()),
            "seed": seed,
            "loras": loras if loras else None,
            "upscale": self.upscale_check.get_active(),
            "upscale_factor": self.upscale_spin.get_value(),
            "interpolate": self.interpolate_check.get_active(),
            "pingpong": self.pingpong_check.get_active(),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  mtb Face Swap Dialog
# ═══════════════════════════════════════════════════════════════════════════

class MtbFaceSwapDialog(Gtk.Dialog):
    """mtb facetools direct face swap — requires source image file."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - Face Swap (mtb)")
        self.set_default_size(480, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Server
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Server:"))
        self.server_entry = Gtk.Entry(text=server_url, hexpand=True)
        row.append(self.server_entry)
        box.append(row)

        # Source face image file chooser
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Source Face Image:"))
        self.source_chooser = Gtk.FileChooserButton(title="Select source face image")
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_mime_type("image/png")
        ff.add_mime_type("image/jpeg")
        ff.add_pattern("*.png")
        ff.add_pattern("*.jpg")
        ff.add_pattern("*.jpeg")
        self.source_chooser.add_filter(ff)
        self.source_chooser.set_hexpand(True)
        row.append(self.source_chooser)
        box.append(row)

        # Analysis model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Analysis Model:"))
        self.analysis_combo = Gtk.ComboBoxText()
        for m in ["buffalo_l", "antelopev2", "buffalo_m", "buffalo_sc"]:
            self.analysis_combo.append(m, m)
        self.analysis_combo.set_active_id("buffalo_l")
        self.analysis_combo.set_hexpand(True)
        row.append(self.analysis_combo)
        box.append(row)

        # Swap model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Swap Model:"))
        self.swap_combo = Gtk.ComboBoxText()
        for m in ["inswapper_128.onnx", "inswapper_128_fp16.onnx"]:
            self.swap_combo.append(m, m)
        self.swap_combo.set_active_id("inswapper_128.onnx")
        self.swap_combo.set_hexpand(True)
        row.append(self.swap_combo)
        box.append(row)

        # Face index
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Face Index:"))
        self.face_idx = Gtk.Entry(text="0")
        self.face_idx.set_tooltip_text("0 = first face, comma-separated for multiple")
        self.face_idx.set_hexpand(True)
        row.append(self.face_idx)
        box.append(row)

        # Fetch models from server
        fetch_btn = Gtk.Button(label="Fetch Models from Server")
        fetch_btn.connect("clicked", self._on_fetch)
        box.append(fetch_btn)

        self.show()

    def _on_fetch(self, _btn):
        srv = self.server_entry.get_text().strip()
        try:
            analysis = _fetch_mtb_analysis_models(srv)
            swaps = _fetch_mtb_swap_models(srv)
            self.analysis_combo.remove_all()
            for m in analysis:
                self.analysis_combo.append(m, m)
            if analysis:
                self.analysis_combo.set_active(0)
            self.swap_combo.remove_all()
            for m in swaps:
                self.swap_combo.append(m, m)
            if swaps:
                self.swap_combo.set_active(0)
        except Exception as e:
            Gimp.message(f"Fetch error: {e}")

    def get_values(self):
        source_path = None
        f = self.source_chooser.get_file()
        if f:
            source_path = f.get_path()
        return {
            "server": self.server_entry.get_text().strip(),
            "source_path": source_path,
            "analysis_model": self.analysis_combo.get_active_id() or "buffalo_l",
            "swap_model": self.swap_combo.get_active_id() or "inswapper_128.onnx",
            "faces_index": self.face_idx.get_text().strip() or "0",
        }


# ═══════════════════════════════════════════════════════════════════════════
#  IPAdapter FaceID img2img Dialog
# ═══════════════════════════════════════════════════════════════════════════

class FaceIDDialog(Gtk.Dialog):
    """IPAdapter FaceID — regenerate image preserving face identity from a reference."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - IPAdapter FaceID img2img")
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Server
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Server:"))
        self.server_entry = Gtk.Entry(text=server_url, hexpand=True)
        row.append(self.server_entry)
        box.append(row)

        # Model preset
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Model Preset:"))
        self.preset_combo = Gtk.ComboBoxText()
        for key in FACEID_PRESETS:
            self.preset_combo.append(key, key)
        self.preset_combo.set_active(0)
        self.preset_combo.set_hexpand(True)
        row.append(self.preset_combo)
        box.append(row)

        # FaceID preset
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="FaceID Type:"))
        self.faceid_combo = Gtk.ComboBoxText()
        for p in ["FACEID", "FACEID PLUS - SD1.5 only", "FACEID PLUS V2",
                   "FACEID PORTRAIT (style transfer)", "FACEID PORTRAIT UNNORM - SDXL only (strong)"]:
            self.faceid_combo.append(p, p)
        self.faceid_combo.set_active_id("FACEID PLUS V2")
        self.faceid_combo.set_hexpand(True)
        row.append(self.faceid_combo)
        box.append(row)

        # Source face image
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Face Reference:"))
        self.source_chooser = Gtk.FileChooserButton(title="Select face reference image")
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_mime_type("image/png")
        ff.add_mime_type("image/jpeg")
        ff.add_pattern("*.png")
        ff.add_pattern("*.jpg")
        ff.add_pattern("*.jpeg")
        self.source_chooser.add_filter(ff)
        self.source_chooser.set_hexpand(True)
        row.append(self.source_chooser)
        box.append(row)

        # Prompt
        box.append(Gtk.Label(label="Prompt:", xalign=0))
        self.prompt_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_size_request(-1, 60)
        sw = Gtk.ScrolledWindow(child=self.prompt_tv, vexpand=False)
        sw.set_min_content_height(60)
        box.append(sw)

        # Negative
        box.append(Gtk.Label(label="Negative:", xalign=0))
        self.neg_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.neg_tv.set_size_request(-1, 40)
        sw2 = Gtk.ScrolledWindow(child=self.neg_tv, vexpand=False)
        sw2.set_min_content_height(40)
        box.append(sw2)
        self.neg_tv.get_buffer().set_text("blurry, deformed, bad anatomy, disfigured")

        # Spinners grid
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        r = 0
        grid.attach(Gtk.Label(label="Weight:", xalign=1), 0, r, 1, 1)
        self.weight_spin = Gtk.SpinButton.new_with_range(0.0, 3.0, 0.05)
        self.weight_spin.set_value(0.85)
        self.weight_spin.set_digits(2)
        grid.attach(self.weight_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Weight V2:", xalign=1), 2, r, 1, 1)
        self.weight_v2_spin = Gtk.SpinButton.new_with_range(0.0, 5.0, 0.05)
        self.weight_v2_spin.set_value(1.0)
        self.weight_v2_spin.set_digits(2)
        grid.attach(self.weight_v2_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="LoRA Str:", xalign=1), 0, r, 1, 1)
        self.lora_str_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.lora_str_spin.set_value(0.6)
        self.lora_str_spin.set_digits(2)
        grid.attach(self.lora_str_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Denoise:", xalign=1), 2, r, 1, 1)
        self.denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
        self.denoise_spin.set_value(0.55)
        self.denoise_spin.set_digits(2)
        grid.attach(self.denoise_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, r, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.steps_spin.set_value(25)
        grid.attach(self.steps_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="CFG:", xalign=1), 2, r, 1, 1)
        self.cfg_spin = Gtk.SpinButton.new_with_range(1.0, 30.0, 0.5)
        self.cfg_spin.set_value(7.0)
        self.cfg_spin.set_digits(1)
        grid.attach(self.cfg_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="Seed:", xalign=1), 0, r, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        self.seed_spin.set_value(-1)
        self.seed_spin.set_tooltip_text("-1 = random")
        grid.attach(self.seed_spin, 1, r, 1, 1)

        box.append(grid)
        self.show()

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def get_values(self):
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        source_path = None
        f = self.source_chooser.get_file()
        if f:
            source_path = f.get_path()
        return {
            "server": self.server_entry.get_text().strip(),
            "preset_key": self.preset_combo.get_active_id(),
            "faceid_preset": self.faceid_combo.get_active_id() or "FACEID PLUS V2",
            "source_path": source_path,
            "prompt": self._buf_text(self.prompt_tv),
            "negative": self._buf_text(self.neg_tv),
            "weight": self.weight_spin.get_value(),
            "weight_v2": self.weight_v2_spin.get_value(),
            "lora_strength": self.lora_str_spin.get_value(),
            "denoise": self.denoise_spin.get_value(),
            "steps": int(self.steps_spin.get_value()),
            "cfg": self.cfg_spin.get_value(),
            "seed": seed,
        }


# ═══════════════════════════════════════════════════════════════════════════
#  PuLID Flux Face Identity Dialog
# ═══════════════════════════════════════════════════════════════════════════

class PulidFluxDialog(Gtk.Dialog):
    """PuLID Flux — generate image preserving face identity with Flux model."""

    def __init__(self, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title="ComfyUI - PuLID Flux Face Identity")
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Server
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Server:"))
        self.server_entry = Gtk.Entry(text=server_url, hexpand=True)
        row.append(self.server_entry)
        box.append(row)

        # Flux model
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Flux Model:"))
        self.model_combo = Gtk.ComboBoxText()
        for m in PULID_FLUX_MODELS:
            label = m.split("\\")[-1] if "\\" in m else m
            self.model_combo.append(m, label)
        self.model_combo.set_active(0)
        self.model_combo.set_hexpand(True)
        row.append(self.model_combo)
        box.append(row)

        # Face reference image
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Face Reference:"))
        self.source_chooser = Gtk.FileChooserButton(title="Select face reference image")
        ff = Gtk.FileFilter()
        ff.set_name("Images")
        ff.add_mime_type("image/png")
        ff.add_mime_type("image/jpeg")
        ff.add_pattern("*.png")
        ff.add_pattern("*.jpg")
        ff.add_pattern("*.jpeg")
        self.source_chooser.add_filter(ff)
        self.source_chooser.set_hexpand(True)
        row.append(self.source_chooser)
        box.append(row)

        # Prompt
        box.append(Gtk.Label(label="Prompt:", xalign=0))
        self.prompt_tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt_tv.set_size_request(-1, 60)
        sw = Gtk.ScrolledWindow(child=self.prompt_tv, vexpand=False)
        sw.set_min_content_height(60)
        box.append(sw)

        # Spinners
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        r = 0
        grid.attach(Gtk.Label(label="Strength:", xalign=1), 0, r, 1, 1)
        self.strength_spin = Gtk.SpinButton.new_with_range(0.0, 2.0, 0.05)
        self.strength_spin.set_value(0.9)
        self.strength_spin.set_digits(2)
        grid.attach(self.strength_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Denoise:", xalign=1), 2, r, 1, 1)
        self.denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
        self.denoise_spin.set_value(0.65)
        self.denoise_spin.set_digits(2)
        grid.attach(self.denoise_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, r, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.steps_spin.set_value(20)
        grid.attach(self.steps_spin, 1, r, 1, 1)
        grid.attach(Gtk.Label(label="Guidance:", xalign=1), 2, r, 1, 1)
        self.guidance_spin = Gtk.SpinButton.new_with_range(1.0, 30.0, 0.5)
        self.guidance_spin.set_value(1.0)
        self.guidance_spin.set_digits(1)
        grid.attach(self.guidance_spin, 3, r, 1, 1)

        r += 1
        grid.attach(Gtk.Label(label="Seed:", xalign=1), 0, r, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**32-1, 1)
        self.seed_spin.set_value(-1)
        self.seed_spin.set_tooltip_text("-1 = random")
        grid.attach(self.seed_spin, 1, r, 1, 1)

        box.append(grid)
        self.show()

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def get_values(self):
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        source_path = None
        f = self.source_chooser.get_file()
        if f:
            source_path = f.get_path()
        return {
            "server": self.server_entry.get_text().strip(),
            "flux_model": self.model_combo.get_active_id(),
            "source_path": source_path,
            "prompt": self._buf_text(self.prompt_tv),
            "strength": self.strength_spin.get_value(),
            "denoise": self.denoise_spin.get_value(),
            "steps": int(self.steps_spin.get_value()),
            "guidance": self.guidance_spin.get_value(),
            "seed": seed,
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Klein img2img Dialog
# ═══════════════════════════════════════════════════════════════════════════

class KleinDialog(Gtk.Dialog):
    """Klein img2img editor dialog. Optionally with reference image."""

    def __init__(self, title, with_reference=False, server_url=COMFYUI_DEFAULT_URL):
        super().__init__(title=title)
        self.set_default_size(560, -1)
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Run", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.with_reference = with_reference

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)

        # Server
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        self.server_entry = Gtk.Entry()
        self.server_entry.set_text(server_url)
        self.server_entry.set_hexpand(True)
        hb.pack_start(self.server_entry, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Klein model selector
        box.pack_start(Gtk.Label(label="Klein Model:", xalign=0), False, False, 0)
        self.klein_combo = Gtk.ComboBoxText()
        for key in KLEIN_MODELS:
            self.klein_combo.append(key, key)
        self.klein_combo.set_active(0)
        box.pack_start(self.klein_combo, False, False, 0)

        # Prompt
        box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
        self.prompt_tv = Gtk.TextView()
        self.prompt_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw = Gtk.ScrolledWindow(); sw.set_min_content_height(60); sw.add(self.prompt_tv)
        box.pack_start(sw, False, False, 0)

        # Reference image (only for ref mode)
        if with_reference:
            box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
            box.pack_start(Gtk.Label(label="Reference Image (for structure):", xalign=0), False, False, 0)
            self.ref_chooser = Gtk.FileChooserButton(title="Select reference image")
            self.ref_chooser.set_action(Gtk.FileChooserAction.OPEN)
            ff = Gtk.FileFilter(); ff.set_name("Images")
            ff.add_pattern("*.png"); ff.add_pattern("*.jpg"); ff.add_pattern("*.jpeg")
            ff.add_pattern("*.webp"); ff.add_pattern("*.bmp")
            self.ref_chooser.add_filter(ff)
            box.pack_start(self.ref_chooser, False, False, 0)
        else:
            self.ref_chooser = None

        # Parameters
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        r = 0

        grid.attach(Gtk.Label(label="Steps:", xalign=1), 0, r, 1, 1)
        self.steps_spin = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.steps_spin.set_value(KLEIN_DEFAULTS["steps"])
        grid.attach(self.steps_spin, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Denoise:", xalign=1), 2, r, 1, 1)
        self.denoise_spin = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.05)
        self.denoise_spin.set_digits(2)
        self.denoise_spin.set_value(KLEIN_DEFAULTS["denoise"])
        grid.attach(self.denoise_spin, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Guidance:", xalign=1), 0, r, 1, 1)
        self.guidance_spin = Gtk.SpinButton.new_with_range(0.0, 30.0, 0.5)
        self.guidance_spin.set_digits(1)
        self.guidance_spin.set_value(KLEIN_DEFAULTS["guidance"])
        grid.attach(self.guidance_spin, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Seed (-1=rand):", xalign=1), 2, r, 1, 1)
        self.seed_spin = Gtk.SpinButton.new_with_range(-1, 2**31, 1)
        self.seed_spin.set_value(-1)
        grid.attach(self.seed_spin, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Enhancer Mag:", xalign=1), 0, r, 1, 1)
        self.enh_mag = Gtk.SpinButton.new_with_range(0.0, 10.0, 0.1)
        self.enh_mag.set_digits(1)
        self.enh_mag.set_value(KLEIN_DEFAULTS["enhancer_magnitude"])
        grid.attach(self.enh_mag, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Enh. Contrast:", xalign=1), 2, r, 1, 1)
        self.enh_contrast = Gtk.SpinButton.new_with_range(-1.0, 10.0, 0.1)
        self.enh_contrast.set_digits(1)
        self.enh_contrast.set_value(KLEIN_DEFAULTS["enhancer_contrast"])
        grid.attach(self.enh_contrast, 3, r, 1, 1)
        r += 1

        if with_reference:
            grid.attach(Gtk.Label(label="Ref Strength:", xalign=1), 0, r, 1, 1)
            self.ref_strength = Gtk.SpinButton.new_with_range(0.0, 5.0, 0.05)
            self.ref_strength.set_digits(2)
            self.ref_strength.set_value(1.0)
            grid.attach(self.ref_strength, 1, r, 1, 1)

            grid.attach(Gtk.Label(label="Text/Ref Balance:", xalign=1), 2, r, 1, 1)
            self.text_ref_bal = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
            self.text_ref_bal.set_digits(2)
            self.text_ref_bal.set_value(KLEIN_DEFAULTS["text_ref_balance"])
            grid.attach(self.text_ref_bal, 3, r, 1, 1)
            r += 1
        else:
            self.ref_strength = None
            self.text_ref_bal = None

        box.pack_start(grid, False, False, 0)

        # LoRA section
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        lora_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lora_hdr.pack_start(Gtk.Label(label="LoRA (fed to Klein Analyzer):", xalign=0), False, False, 0)
        self._lora_fetch_btn = Gtk.Button(label="Fetch LoRAs")
        self._lora_fetch_btn.connect("clicked", self._on_fetch_loras)
        lora_hdr.pack_end(self._lora_fetch_btn, False, False, 0)
        box.pack_start(lora_hdr, False, False, 0)

        self._all_lora_names = []
        self._lora_names = []
        self.lora_combo = Gtk.ComboBoxText()
        self.lora_combo.append("none", "(none)")
        self.lora_combo.set_active(0)
        box.pack_start(self.lora_combo, False, False, 0)

        lora_str_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lora_str_box.pack_start(Gtk.Label(label="LoRA Strength:"), False, False, 0)
        self.lora_str_spin = Gtk.SpinButton.new_with_range(-5.0, 5.0, 0.05)
        self.lora_str_spin.set_digits(2); self.lora_str_spin.set_value(1.0)
        lora_str_box.pack_start(self.lora_str_spin, False, False, 0)
        box.pack_start(lora_str_box, False, False, 0)

        box.show_all()
        GLib.idle_add(self._on_fetch_loras, None)

    def _on_fetch_loras(self, _btn):
        server = self.server_entry.get_text().strip()
        try:
            self._all_lora_names = _fetch_loras(server)
        except Exception:
            self._all_lora_names = []
        # Klein only shows Flux-2-Klein compatible LoRAs
        self._lora_names = _filter_loras_for_arch(self._all_lora_names, "flux2klein")
        self.lora_combo.remove_all()
        self.lora_combo.append("none", "(none)")
        for lname in self._lora_names:
            short = lname.rsplit("\\", 1)[-1] if "\\" in lname else lname
            self.lora_combo.append(lname, short)
        self.lora_combo.set_active(0)
        total = len(self._all_lora_names)
        shown = len(self._lora_names)
        self._lora_fetch_btn.set_label(f"{shown}/{total} Klein LoRAs")

    def _buf_text(self, tv):
        buf = tv.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def get_values(self):
        seed = int(self.seed_spin.get_value())
        if seed < 0:
            seed = random.randint(0, 2**32 - 1)
        lora_id = self.lora_combo.get_active_id()
        lora_name = lora_id if lora_id and lora_id != "none" else None
        vals = {
            "server": self.server_entry.get_text().strip(),
            "klein_model": self.klein_combo.get_active_id() or list(KLEIN_MODELS.keys())[0],
            "prompt": self._buf_text(self.prompt_tv),
            "seed": seed,
            "steps": int(self.steps_spin.get_value()),
            "denoise": self.denoise_spin.get_value(),
            "guidance": self.guidance_spin.get_value(),
            "enhancer_mag": self.enh_mag.get_value(),
            "enhancer_contrast": self.enh_contrast.get_value(),
            "lora_name": lora_name,
            "lora_strength": self.lora_str_spin.get_value(),
        }
        if self.with_reference:
            vals["ref_file"] = self.ref_chooser.get_filename() if self.ref_chooser else None
            vals["ref_strength"] = self.ref_strength.get_value() if self.ref_strength else 1.0
            vals["text_ref_balance"] = self.text_ref_bal.get_value() if self.text_ref_bal else 0.5
        return vals


# ═══════════════════════════════════════════════════════════════════════════
#  GIMP 3 Plug-in
# ═══════════════════════════════════════════════════════════════════════════

class Spellcaster(Gimp.PlugIn):

    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [
            "spellcaster-img2img", "spellcaster-txt2img", "spellcaster-inpaint", "spellcaster-send-image",
            "spellcaster-faceswap", "spellcaster-faceswap-model",
            "spellcaster-faceswap-mtb", "spellcaster-faceid-img2img", "spellcaster-pulid-flux",
            "spellcaster-klein-img2img", "spellcaster-klein-img2img-ref",
            "spellcaster-wan-i2v",
        ]

    def do_create_procedure(self, name):
        menu_map = {
            "spellcaster-img2img": ("Image to Image (presets)...", self._run_img2img,
                                    "Send canvas to ComfyUI with per-model presets"),
            "spellcaster-txt2img": ("Text to Image (presets)...", self._run_txt2img,
                                    "Generate from text with per-model presets"),
            "spellcaster-inpaint": ("Inpaint Selection (presets)...", self._run_inpaint,
                                    "Inpaint selection area with per-model presets"),
            "spellcaster-send-image": ("Upload Image to Server", self._run_send,
                                       "Upload canvas to ComfyUI input folder"),
            "spellcaster-faceswap": ("Face Swap (ReActor)...", self._run_faceswap,
                                     "Swap face on canvas using a source face image"),
            "spellcaster-faceswap-model": ("Face Swap (Saved Face Model)...", self._run_faceswap_model,
                                           "Swap face using a saved face model from the server"),
            "spellcaster-faceswap-mtb": ("Face Swap (mtb)...", self._run_faceswap_mtb,
                                         "Direct face swap using mtb facetools"),
            "spellcaster-faceid-img2img": ("FaceID img2img (IPAdapter)...", self._run_faceid,
                                           "Regenerate image preserving face identity with IPAdapter FaceID"),
            "spellcaster-pulid-flux": ("PuLID Flux Face Identity...", self._run_pulid_flux,
                                       "Generate with Flux preserving face identity via PuLID"),
            "spellcaster-klein-img2img": ("Klein Image Editor...", self._run_klein,
                                          "Edit image with Flux 2 Klein model"),
            "spellcaster-klein-img2img-ref": ("Klein Image Editor + Reference...", self._run_klein_ref,
                                              "Edit image with Flux 2 Klein using a reference image"),
            "spellcaster-wan-i2v": ("Wan 2.2 Image to Video...", self._run_wan_i2v,
                                    "Generate video from image using Wan 2.2"),
        }
        label, callback, doc = menu_map[name]
        proc = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, callback, None)
        proc.set_menu_label(label)
        proc.add_menu_path("<Image>/Filters/Spellcaster")
        proc.set_documentation(doc, doc, name)
        proc.set_attribution("Spellcaster", "Spellcaster", "2026")
        proc.set_image_types("*")   # accept all image types (RGB, GRAY, INDEXED, with/without alpha)
        return proc

    def _run_img2img(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = PresetDialog("Spellcaster — Image to Image", mode="img2img")
        dlg.w_spin.set_value(image.get_width())
        dlg.h_spin.set_value(image.get_height())
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        try:
            srv = v["server"]
            Gimp.progress_init("img2img: exporting image...")
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                 _build_img2img(uname, v["preset"], v["prompt"], v["negative"], v["seed"], v.get("loras"))
            Gimp.progress_set_text("img2img: processing on ComfyUI...")
            results = _run_with_spinner("img2img: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"{v['preset'].get('label','')} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster img2img Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_txt2img(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = PresetDialog("Spellcaster — Text to Image", mode="txt2img")
        dlg.w_spin.set_value(image.get_width())
        dlg.h_spin.set_value(image.get_height())
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        try:
            srv = v["server"]
            Gimp.progress_init("txt2img: generating on ComfyUI...")
            wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                 _build_txt2img(v["preset"], v["prompt"], v["negative"], v["seed"], v.get("loras"))
            Gimp.progress_set_text("txt2img: processing on ComfyUI...")
            results = _run_with_spinner("txt2img: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"{v['preset'].get('label','')} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster txt2img Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_inpaint(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        dlg = PresetDialog("Spellcaster — Inpaint Selection", mode="inpaint")
        # Working resolution for the sampler — full image dims, NOT selection dims.
        # The mask controls which area gets inpainted; ImageScale handles resolution.
        dlg.w_spin.set_value(image.get_width()); dlg.h_spin.set_value(image.get_height())
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        try:
            Gimp.progress_init("Building selection mask...")
            srv = v["server"]

            # Build mask from GIMP's actual selection channel (not just bounds)
            mtmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False); mtmp.close()
            _create_selection_mask_png(mtmp.name, image)

            Gimp.progress_set_text("Exporting image...")
            # Export current image
            tmp = _export_image_to_tmp(image)
            iname = f"gimp_inp_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, iname); os.unlink(tmp)

            mname = f"gimp_mask_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, mtmp.name, mname); os.unlink(mtmp.name)

            wf = json.loads(v["custom_workflow"]) if v["custom_workflow"] else \
                 _build_inpaint(iname, mname, v["preset"], v["prompt"], v["negative"], v["seed"], v.get("loras"))
            Gimp.progress_set_text("Inpaint: processing on ComfyUI...")
            results = _run_with_spinner("Inpaint: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Inpaint {v['preset'].get('label','')} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Inpaint Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceswap(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = FaceSwapDialog()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v["face_file"]:
            Gimp.message("No source face image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("Face Swap: exporting images...")
            srv = v["server"]
            # Upload target (current canvas)
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_fstgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            # Upload source face
            src_name = f"gimp_fssrc_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["face_file"], src_name)
            # Build and run workflow
            wf = _build_faceswap(
                tgt_name, src_name,
                swap_model=v["swap_model"],
                face_restore_model=v["face_restore_model"],
                face_restore_vis=v["face_restore_vis"],
                codeformer_weight=v["codeformer_weight"],
                detect_gender_input=v["detect_gender_input"],
                detect_gender_source=v["detect_gender_source"],
                input_face_idx=v["input_face_idx"],
                source_face_idx=v["source_face_idx"],
            )
            Gimp.progress_set_text("Face Swap: processing on ComfyUI...")
            results = _run_with_spinner("Face Swap: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"FaceSwap #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Face Swap Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceswap_model(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = FaceSwapModelDialog()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v["face_model"] or v["face_model"] == "none":
            Gimp.message("No face model selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("Face Swap (Model): exporting image...")
            srv = v["server"]
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_fsm_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            wf = _build_faceswap_model(
                tgt_name, v["face_model"],
                swap_model=v["swap_model"],
                face_restore_model=v["face_restore_model"],
                face_restore_vis=v["face_restore_vis"],
                codeformer_weight=v["codeformer_weight"],
                detect_gender_input=v["detect_gender_input"],
                detect_gender_source=v["detect_gender_source"],
                input_face_idx=v["input_face_idx"],
                source_face_idx=v["source_face_idx"],
            )
            Gimp.progress_set_text("Face Swap (Model): processing on ComfyUI...")
            results = _run_with_spinner("Face Swap (Model): processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"FaceSwap Model #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Face Swap (Model) Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_wan_i2v(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")

        # Check for selection — if present, use selection region as start image
        has_sel, sx1, sy1, sx2, sy2 = _get_selection_bounds(image)

        dlg = WanI2VDialog()
        if has_sel:
            src_w, src_h = sx2 - sx1, sy2 - sy1
        else:
            src_w, src_h = image.get_width(), image.get_height()
        vw, vh = _wan_video_dims(src_w, src_h)
        dlg.w_spin.set_value(vw)
        dlg.h_spin.set_value(vh)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        try:
            if has_sel:
                Gimp.progress_init("Wan I2V: exporting selection region...")
                srv = v["server"]
                tmp, _sw, _sh = _export_selection_to_tmp(image)
            else:
                Gimp.progress_init("Wan I2V: exporting image...")
                srv = v["server"]
                tmp = _export_image_to_tmp(image)
            uname = f"gimp_wan_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_wan_i2v(
                uname, v["preset_key"], v["prompt"], v["negative"], v["seed"],
                width=v["width"], height=v["height"], length=v["length"],
                steps=v["steps"], cfg=v["cfg"], shift=v["shift"],
                second_step=v["second_step"], loras=v["loras"],
                upscale=v["upscale"], upscale_factor=v["upscale_factor"],
                interpolate=v["interpolate"], pingpong=v["pingpong"],
                fps=v["fps"],
            )
            src = "selection" if has_sel else "full image"
            Gimp.progress_set_text(f"Wan I2V: generating video from {src} on ComfyUI...")
            results = _run_with_spinner(f"Wan I2V: generating video from {src} on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf, timeout=600)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Wan I2V frame #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            Gimp.message("Video generation complete! Check ComfyUI output folder for the MP4 file.")
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Wan I2V Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceswap_mtb(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = MtbFaceSwapDialog()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v["source_path"]:
            Gimp.message("No source face image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("Face Swap (mtb): exporting images...")
            srv = v["server"]
            # Export target (current canvas)
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_mtb_tgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            # Upload source face image
            src_name = f"gimp_mtb_src_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["source_path"], src_name)
            wf = _build_faceswap_mtb(tgt_name, src_name,
                                      analysis_model=v["analysis_model"],
                                      swap_model=v["swap_model"],
                                      faces_index=v["faces_index"])
            Gimp.progress_set_text("Face Swap (mtb): processing...")
            results = _run_with_spinner("Face Swap (mtb): processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"FaceSwap mtb #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Face Swap (mtb) Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_faceid(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = FaceIDDialog()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v["source_path"]:
            Gimp.message("No face reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("FaceID: exporting images...")
            srv = v["server"]
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_fid_tgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            src_name = f"gimp_fid_ref_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["source_path"], src_name)
            wf = _build_faceid_img2img(
                tgt_name, src_name, v["preset_key"],
                v["prompt"], v["negative"], v["seed"],
                faceid_preset=v["faceid_preset"],
                lora_strength=v["lora_strength"],
                weight=v["weight"], weight_v2=v["weight_v2"],
                denoise=v["denoise"], steps=v["steps"], cfg=v["cfg"],
            )
            Gimp.progress_set_text("FaceID: processing on ComfyUI...")
            results = _run_with_spinner("FaceID: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"FaceID {v['preset_key']} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster FaceID Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_pulid_flux(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = PulidFluxDialog()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v["source_path"]:
            Gimp.message("No face reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("PuLID Flux: exporting images...")
            srv = v["server"]
            tmp = _export_image_to_tmp(image)
            tgt_name = f"gimp_pulid_tgt_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, tgt_name); os.unlink(tmp)
            src_name = f"gimp_pulid_ref_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["source_path"], src_name)
            wf = _build_pulid_flux(
                tgt_name, src_name,
                v["prompt"], "",
                v["seed"],
                flux_model=v["flux_model"],
                strength=v["strength"],
                steps=v["steps"],
                guidance=v["guidance"],
                denoise=v["denoise"],
            )
            Gimp.progress_set_text("PuLID Flux: processing on ComfyUI...")
            results = _run_with_spinner("PuLID Flux: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"PuLID Flux #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster PuLID Flux Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_klein(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = KleinDialog("Spellcaster — Klein Image Editor", with_reference=False)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        try:
            Gimp.progress_init("Klein: exporting image...")
            srv = v["server"]
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_klein_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            wf = _build_klein_img2img(
                uname, v["klein_model"], v["prompt"], v["seed"],
                steps=v["steps"], denoise=v["denoise"], guidance=v["guidance"],
                enhancer_mag=v["enhancer_mag"], enhancer_contrast=v["enhancer_contrast"],
                lora_name=v["lora_name"], lora_strength=v["lora_strength"],
            )
            Gimp.progress_set_text("Klein: processing on ComfyUI...")
            results = _run_with_spinner("Klein: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Klein {v['klein_model']} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Klein Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_klein_ref(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = KleinDialog("Spellcaster — Klein Editor + Reference", with_reference=True)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        v = dlg.get_values(); dlg.destroy()
        if not v.get("ref_file"):
            Gimp.message("No reference image selected")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())
        try:
            Gimp.progress_init("Klein+Ref: exporting images...")
            srv = v["server"]
            # Upload main image
            tmp = _export_image_to_tmp(image)
            uname = f"gimp_kleinm_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, tmp, uname); os.unlink(tmp)
            # Upload reference image
            ref_name = f"gimp_kleinr_{uuid.uuid4().hex[:8]}.png"
            _upload_image(srv, v["ref_file"], ref_name)
            wf = _build_klein_img2img_ref(
                uname, ref_name, v["klein_model"], v["prompt"], v["seed"],
                steps=v["steps"], denoise=v["denoise"], guidance=v["guidance"],
                enhancer_mag=v["enhancer_mag"], enhancer_contrast=v["enhancer_contrast"],
                ref_strength=v["ref_strength"], text_ref_balance=v["text_ref_balance"],
                lora_name=v["lora_name"], lora_strength=v["lora_strength"],
            )
            Gimp.progress_set_text("Klein+Ref: processing on ComfyUI...")
            results = _run_with_spinner("Klein+Ref: processing on ComfyUI...",
                                        lambda: list(_run_comfyui_workflow(srv, wf)))
            for i, (fn, sf, ft) in enumerate(results):
                _import_result_as_layer(image, _download_image(srv, fn, sf, ft),
                                        f"Klein+Ref {v['klein_model']} #{i+1}")
            Gimp.displays_flush()
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Spellcaster Klein+Ref Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    def _run_send(self, procedure, run_mode, image, drawables, config, data):
        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error())
        GimpUi.init("spellcaster")
        dlg = Gtk.Dialog(title="Upload to Spellcaster")
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Upload", Gtk.ResponseType.OK)
        bx = dlg.get_content_area()
        bx.set_spacing(8); bx.set_margin_start(12); bx.set_margin_end(12)
        bx.set_margin_top(12); bx.set_margin_bottom(12)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.pack_start(Gtk.Label(label="Server:"), False, False, 0)
        se = Gtk.Entry(); se.set_text(COMFYUI_DEFAULT_URL); se.set_hexpand(True)
        hb.pack_start(se, True, True, 0); bx.pack_start(hb, False, False, 0)
        uname = f"gimp_upload_{uuid.uuid4().hex[:8]}.png"
        hb2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb2.pack_start(Gtk.Label(label="Filename:"), False, False, 0)
        ne = Gtk.Entry(); ne.set_text(uname); ne.set_hexpand(True)
        hb2.pack_start(ne, True, True, 0); bx.pack_start(hb2, False, False, 0)
        bx.show_all()
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        srv = se.get_text().strip(); fn = ne.get_text().strip(); dlg.destroy()
        try:
            Gimp.progress_init("Uploading...")
            tmp = _export_image_to_tmp(image)
            r = _upload_image(srv, tmp, fn); os.unlink(tmp)
            Gimp.message(f"Uploaded as: {r.get('name', fn)}")
            Gimp.progress_end()
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            Gimp.message(f"Upload Error: {e}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())


Gimp.main(Spellcaster.__gtype__, sys.argv)
