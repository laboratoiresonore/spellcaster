#!/usr/bin/env python3
"""
Spellcaster Magic Studios Walkthrough Asset Generator
=====================================================
Generates ALL 21 assets referenced in MAGIC_STUDIOS_WALKTHROUGH.md
following Gerald McFluffington III's star-making journey.

Uses the SAME ComfyUI pipelines as the actual Magic Studios tools:
  Act I   — ReActor self-swap + three restore variants + face model save
  Act II  — txt2img body + ReActor face swap + rembg background removal
  Act III — Klein Flux 2 inpaint for wardrobe changes
  Act IV  — txt2img backgrounds + Klein Flux 2 composite blend
  Act V   — Wan 2.2 I2V for walk + pause + look + final composite

Requirements:
  - ComfyUI server running with ReActor, Klein Flux 2, Wan 2.2 nodes
  - A source "Gerald" photo (selfie.png in assets/) — or generates one
  - All referenced checkpoints, LoRAs, and models installed

Usage:
    python generate_walkthrough.py
    python generate_walkthrough.py --server http://127.0.0.1:8188
    python generate_walkthrough.py --act 1         # Run only Act I
    python generate_walkthrough.py --act 1,2,3     # Run Acts I-III
    python generate_walkthrough.py --list           # List all steps
    python generate_walkthrough.py --dry-run        # Validate only
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
import copy
from pathlib import Path

SERVER = "http://127.0.0.1:8188"
ASSETS_DIR = Path(__file__).parent / "assets"
OUTPUT_DIR = ASSETS_DIR / "walkthrough"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Shared config ───────────────────────────────────────────────────────────

# Gerald's source photo — we generate one if it doesn't exist
GERALD_SOURCE = ASSETS_DIR / "walkthrough_gerald_source.png"

# Negative prompts
NEG_REAL = (
    "cartoon, painting, blurry, deformed, disfigured, bad anatomy, extra fingers, "
    "mutated hands, poorly drawn, ugly, jpeg artifacts, low quality, worst quality"
)
NEG_BODY = (
    "bad anatomy, extra limbs, deformed, disfigured, blurry, low quality, "
    "mutated, missing fingers, extra fingers, bad hands, worst quality"
)

# Checkpoints
CKPT_SDXL = "SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors"
CKPT_SD15 = "SD-1.5\\juggernaut_reborn.safetensors"
KLEIN_9B = "A-Flux\\Flux2\\flux-2-klein-9b.safetensors"
KLEIN_CLIP = "qwen_3_8b_fp8mixed.safetensors"


# ─── Utility functions ───────────────────────────────────────────────────────

def random_seed():
    return int.from_bytes(os.urandom(4), 'big')


def upload_image(server, local_path, upload_name=None):
    """Upload a local image to ComfyUI's input directory."""
    if upload_name is None:
        upload_name = f"wt_{uuid.uuid4().hex[:8]}.png"
    boundary = uuid.uuid4().hex
    import mimetypes
    content_type = mimetypes.guess_type(str(local_path))[0] or "image/png"

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


def queue_prompt(server, workflow):
    """Submit a workflow to ComfyUI and return the prompt_id."""
    payload = json.dumps({"prompt": workflow, "client_id": str(uuid.uuid4())}).encode()
    req = urllib.request.Request(
        f"{server}/prompt", data=payload,
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
    """Poll ComfyUI history until the prompt completes. Returns outputs dict."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{server}/history/{prompt_id}", timeout=10) as resp:
                history = json.loads(resp.read())
            if prompt_id in history:
                return history[prompt_id].get("outputs", {})
        except Exception:
            pass
        time.sleep(2)
    return None


def download_output(server, outputs, dest_path, prefer_node=None):
    """Download the first output image/gif from a completed prompt."""
    for node_id, node_out in outputs.items():
        if prefer_node and node_id != prefer_node:
            continue
        items = node_out.get("images") or node_out.get("gifs") or []
        if items:
            item = items[0]
            fname = item.get("filename", "")
            subfolder = item.get("subfolder", "")
            ftype = item.get("type", "output")
            url = f"{server}/view?filename={urllib.parse.quote(fname)}&type={ftype}"
            if subfolder:
                url += f"&subfolder={urllib.parse.quote(subfolder)}"
            urllib.request.urlretrieve(url, dest_path)
            return True
    # If prefer_node was set but not found, try any node
    if prefer_node:
        return download_output(server, outputs, dest_path, prefer_node=None)
    return False


def run_step(server, name, workflow, dest_path, timeout=1800):
    """Queue a workflow, wait, download result. Returns True on success."""
    print(f"  [{name}] Queuing...", end="", flush=True)
    pid = queue_prompt(server, workflow)
    if not pid:
        print(" FAILED (queue error)")
        return False
    print(f" {pid[:8]}...", end="", flush=True)
    outputs = wait_for_prompt(server, pid, timeout=timeout)
    if not outputs:
        print(" TIMEOUT")
        return False
    if download_output(server, outputs, dest_path):
        print(f" -> {dest_path.name}")
        return True
    print(" FAILED (no output)")
    return False


# ─── Workflow builders ───────────────────────────────────────────────────────

def wf_generate_gerald():
    """Generate Gerald's source photo — a middle-aged accountant headshot."""
    s = random_seed()
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CKPT_SDXL}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": (
                  "professional headshot photograph of a regular everyday man in his late 40s, "
                  "balding on top with thin hair on sides, round friendly face, "
                  "slight double chin, warm brown eyes, dad bod, soft jawline, "
                  "genuine awkward smile showing teeth, wearing ill-fitting business casual polo shirt, "
                  "Walgreens photo kiosk quality, slightly overexposed, "
                  "reading glasses perched on forehead, "
                  "fluorescent lighting, realistic, 8k, DSLR"
              ), "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": NEG_REAL, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {
                  "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["4", 0], "seed": s,
                  "steps": 30, "cfg": 6.5,
                  "sampler_name": "dpmpp_2m_sde", "scheduler": "karras",
                  "denoise": 1.0,
              }},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": "wt_gerald_source"}},
    }


def wf_casting_polaroid(gerald_upload_name, restore_model, variant_label, seed=None):
    """Act I: ReActor self-swap with a specific face restore model.

    Pipeline: Load Gerald → ReActorFaceSwapOpt(self-swap) + FaceBoost → SaveImage
    Three variants use different restore models for variety.
    """
    s = seed or random_seed()
    return {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": gerald_upload_name}},
        "3": {"class_type": "ReActorFaceSwapOpt",
              "inputs": {
                  "enabled": True,
                  "input_image": ["1", 0],
                  "source_image": ["1", 0],  # self-swap
                  "swap_model": "reswapper_256.onnx",
                  "facedetection": "retinaface_resnet50",
                  "face_restore_model": restore_model,
                  "face_restore_visibility": 0.8,
                  "codeformer_weight": 0.5,
              }},
        "4": {"class_type": "ReActorOptions",
              "inputs": {
                  "input_faces_order": "left-right",
                  "input_faces_index": "0",
                  "detect_gender_input": "no",
                  "source_faces_order": "left-right",
                  "source_faces_index": "0",
                  "detect_gender_source": "no",
                  "console_log_level": 1,
                  "restore_swapped_only": True,
              }},
        "5": {"class_type": "ReActorFaceBoost",
              "inputs": {
                  "enabled": True,
                  "boost_model": restore_model,
                  "interpolation": "Bicubic",
                  "visibility": 1.0,
                  "codeformer_weight": 0.5,
                  "restore_with_main_after": False,
              }},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["3", 0],
                           "filename_prefix": f"wt_casting_{variant_label}"}},
    }


def _link_reactor_opts(wf):
    """Wire ReActorOptions + FaceBoost into the swap node."""
    wf["3"]["inputs"]["options"] = ["4", 0]
    wf["3"]["inputs"]["face_boost"] = ["5", 0]
    return wf


def wf_casting_complete(gerald_upload_name):
    """Act I final: Best variant (GPEN-2048) as the 'selected' casting photo."""
    wf = wf_casting_polaroid(gerald_upload_name, "GPEN-BFR-2048.onnx", "complete")
    return _link_reactor_opts(wf)


def wf_body_generate(variant_num):
    """Act II step 1: Generate a male body with SDXL.

    Full-body standing pose, neutral background for easy rembg.
    """
    prompts = [
        "full body photograph of an average dad bod man, late 40s, standing straight, "
        "slightly soft midsection, love handles, not muscular, "
        "wearing plain white t-shirt that is a little tight around the belly, grey sweatpants, "
        "clean white studio background, even lighting, full body visible head to feet, "
        "regular guy physique, photorealistic, 8k, sharp",

        "full body photograph of a stocky heavyset man, late 40s, relaxed standing pose, "
        "hands at sides, round beer belly, thick arms, barrel chest, broad shoulders, "
        "wearing basic white undershirt and khaki shorts, "
        "clean white studio background, even lighting, full body visible, "
        "big teddy bear build, photorealistic, 8k, sharp",

        "full body photograph of a skinny lanky man, late 40s, standing awkwardly, "
        "very thin build, narrow shoulders, long arms, bony, no muscle definition, "
        "wearing oversized board shorts hanging low, no shirt showing ribs, "
        "clean bright background, even lighting, full body visible head to feet, "
        "beanpole physique, photorealistic, 8k, sharp",
    ]
    s = random_seed()
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CKPT_SDXL}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompts[variant_num - 1], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": NEG_BODY, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 768, "height": 1216, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {
                  "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["4", 0], "seed": s,
                  "steps": 30, "cfg": 6.5,
                  "sampler_name": "dpmpp_2m_sde", "scheduler": "karras",
                  "denoise": 1.0,
              }},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0],
                          "filename_prefix": f"wt_body_raw_{variant_num}"}},
    }


def wf_faceswap_onto_body(body_upload_name, face_upload_name):
    """Act II step 2: Swap Gerald's face onto the generated body."""
    return {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": body_upload_name}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": face_upload_name}},
        "3": {"class_type": "ReActorFaceSwapOpt",
              "inputs": {
                  "enabled": True,
                  "input_image": ["1", 0],
                  "source_image": ["2", 0],
                  "swap_model": "reswapper_256.onnx",
                  "facedetection": "retinaface_resnet50",
                  "face_restore_model": "GPEN-BFR-2048.onnx",
                  "face_restore_visibility": 0.8,
                  "codeformer_weight": 0.5,
              }},
        "4": {"class_type": "ReActorOptions",
              "inputs": {
                  "input_faces_order": "left-right",
                  "input_faces_index": "0",
                  "detect_gender_input": "no",
                  "source_faces_order": "left-right",
                  "source_faces_index": "0",
                  "detect_gender_source": "no",
                  "console_log_level": 1,
                  "restore_swapped_only": True,
              }},
        "5": {"class_type": "ReActorFaceBoost",
              "inputs": {
                  "enabled": True,
                  "boost_model": "GPEN-BFR-2048.onnx",
                  "interpolation": "Bicubic",
                  "visibility": 1.0,
                  "codeformer_weight": 0.5,
                  "restore_with_main_after": False,
              }},
        "10": {"class_type": "SaveImage",
               "inputs": {"images": ["3", 0],
                           "filename_prefix": "wt_body_swapped"}},
    }


def wf_rembg(image_upload_name, prefix="wt_body_transparent"):
    """Remove background from an image using rembg."""
    return {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": image_upload_name}},
        "2": {"class_type": "Image Rembg (Remove Background)",
              "inputs": {
                  "images": ["1", 0],
                  "model": "u2net",
                  "transparency": True,
                  "post_processing": False,
                  "only_mask": False,
                  "alpha_matting": False,
                  "alpha_matting_foreground_threshold": 240,
                  "alpha_matting_background_threshold": 10,
                  "alpha_matting_erode_size": 10,
                  "background_color": "none",
              }},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0],
                          "filename_prefix": prefix}},
    }


def wf_klein_inpaint(image_upload_name, mask_upload_name, prompt, denoise=0.85):
    """Act III: Klein Flux 2 inpaint for wardrobe changes.

    Uses InpaintModelConditioning + DifferentialDiffusion for smooth edges.
    """
    s = random_seed()
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": KLEIN_9B, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": KLEIN_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "DifferentialDiffusion",
              "inputs": {"model": ["1", 0]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "LoadImage",
              "inputs": {"image": image_upload_name}},
        "8": {"class_type": "LoadImage",
              "inputs": {"image": mask_upload_name}},
        "9": {"class_type": "InpaintModelConditioning",
              "inputs": {
                  "positive": ["5", 0], "negative": ["6", 0],
                  "vae": ["3", 0], "pixels": ["7", 0], "mask": ["8", 0],
                  "noise_mask": True,
              }},
        "20": {"class_type": "Flux2Scheduler",
               "inputs": {"steps": 20, "width": 768, "height": 1216}},
        "21": {"class_type": "CFGGuider",
               "inputs": {"model": ["4", 0], "positive": ["9", 0],
                           "negative": ["9", 1], "cfg": 3.5}},
        "22": {"class_type": "KSamplerSelect",
               "inputs": {"sampler_name": "euler"}},
        "23": {"class_type": "RandomNoise",
               "inputs": {"noise_seed": s}},
        "24": {"class_type": "SamplerCustomAdvanced",
               "inputs": {
                   "noise": ["23", 0], "guider": ["21", 0],
                   "sampler": ["22", 0], "sigmas": ["20", 0],
                   "latent_image": ["9", 2],
               }},
        "30": {"class_type": "VAEDecode",
               "inputs": {"samples": ["24", 0], "vae": ["3", 0]}},
        "31": {"class_type": "SaveImage",
               "inputs": {"images": ["30", 0],
                           "filename_prefix": "wt_wardrobe"}},
    }


def wf_txt2img_background(prompt, width=1216, height=832):
    """Act IV step 1: Generate a background scene with SDXL."""
    s = random_seed()
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CKPT_SDXL}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": NEG_REAL, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {
                  "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                  "latent_image": ["4", 0], "seed": s,
                  "steps": 30, "cfg": 6.5,
                  "sampler_name": "dpmpp_2m_sde", "scheduler": "karras",
                  "denoise": 1.0,
              }},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0],
                          "filename_prefix": "wt_set_bg"}},
    }


def wf_composite_actor(bg_upload, actor_upload, denoise=0.15):
    """Act IV step 2: Composite actor onto background using Klein Flux 2 blend.

    Pipeline:
      1. Load background + actor (transparent PNG with alpha)
      2. SplitImageWithAlpha extracts RGB + mask from the actor
      3. ImageScale resizes actor to fit the scene
      4. ImageCompositeMasked overlays actor onto background using the alpha mask
      5. Klein Flux 2 gentle harmonization (CFG 1.0 — guidance-distilled model)
    """
    s = random_seed()
    return {
        # Load images
        "10": {"class_type": "LoadImage",
               "inputs": {"image": bg_upload}},
        # LoadImage on RGBA PNGs gives output[0]=RGB, output[1]=MASK (alpha)
        "11": {"class_type": "LoadImage",
               "inputs": {"image": actor_upload}},
        # Scale the RGB actor to fit background (bg is 1216x832)
        # Actor is 768x1216 portrait -> scale to ~340x540 to look natural
        "12": {"class_type": "ImageScale",
               "inputs": {"image": ["11", 0], "upscale_method": "lanczos",
                           "width": 340, "height": 540, "crop": "disabled"}},
        # LoadImage alpha mask has white=BACKGROUND, black=CHARACTER (inverted)
        # ImageCompositeMasked needs white=source visible (character)
        # So invert, then scale to match actor size
        "18": {"class_type": "InvertMask",
               "inputs": {"mask": ["11", 1]}},
        "15": {"class_type": "MaskToImage",
               "inputs": {"mask": ["18", 0]}},
        "16": {"class_type": "ImageScale",
               "inputs": {"image": ["15", 0], "upscale_method": "lanczos",
                           "width": 340, "height": 540, "crop": "disabled"}},
        "17": {"class_type": "ImageToMask",
               "inputs": {"image": ["16", 0], "channel": "red"}},
        # Composite: place actor on background using alpha mask
        # x=438 centers 340px actor on 1216px bg, y=292 places feet near bottom
        "13": {"class_type": "ImageCompositeMasked",
               "inputs": {"destination": ["10", 0], "source": ["12", 0],
                           "mask": ["17", 0],
                           "x": 438, "y": 292, "resize_source": False}},
        # Also save the raw composite (before Klein) for comparison
        "32": {"class_type": "SaveImage",
               "inputs": {"images": ["13", 0],
                           "filename_prefix": "wt_set_raw_composite"}},
        # Klein Flux 2 harmonization — CFG 1.0 (guidance-distilled)
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": KLEIN_9B, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": KLEIN_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": (
                  "photorealistic scene, person standing on beach, Hawaiian shirt, "
                  "golden sunset, warm lighting matching skin tones, natural shadows, "
                  "foggy atmosphere, cinematic, coherent lighting"
              ), "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["4", 0]}},
        "7": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["13", 0], "vae": ["3", 0]}},
        "21": {"class_type": "CFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["4", 0],
                           "negative": ["5", 0], "cfg": 1.0}},
        "22": {"class_type": "KSamplerSelect",
               "inputs": {"sampler_name": "euler"}},
        "23": {"class_type": "RandomNoise",
               "inputs": {"noise_seed": s}},
        "24": {"class_type": "BasicScheduler",
               "inputs": {"model": ["1", 0], "scheduler": "simple",
                           "steps": 10, "denoise": denoise}},
        "25": {"class_type": "SamplerCustomAdvanced",
               "inputs": {
                   "noise": ["23", 0], "guider": ["21", 0],
                   "sampler": ["22", 0], "sigmas": ["24", 0],
                   "latent_image": ["7", 0],
               }},
        "30": {"class_type": "VAEDecode",
               "inputs": {"samples": ["25", 0], "vae": ["3", 0]}},
        "31": {"class_type": "SaveImage",
               "inputs": {"images": ["30", 0],
                           "filename_prefix": "wt_set_composite"}},
    }


def wf_wan_i2v(image_name, prompt, negative="", length=49, steps=20,
               second_step=10, cfg=1.0, shift=8.0, accel_strength=1.5):
    """Act V: Wan 2.2 I2V — dual-model GGUF with lightx2v turbo LoRAs.

    Uses the GIMP plugin's proven settings:
      steps=20, second_step=10, cfg=1, accel_strength=1.5
    The lightx2v 4-step LoRAs at 1.5 strength need fewer total steps.
    """
    s = random_seed()
    return {
        "1": {"class_type": "CLIPLoaderGGUF",
              "inputs": {"clip_name": "umt5-xxl-encoder-Q8_0.gguf", "type": "wan"}},
        "2": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "Wan\\wan2.2_i2v_high_noise_14B_Q4_K_S.gguf"}},
        "3": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "Wan\\wan2.2_i2v_low_noise_14B_Q4_K_S.gguf"}},
        "4": {"class_type": "VAELoader",
              "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 0]}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["1", 0]}},
        "7": {"class_type": "LoadImage",
              "inputs": {"image": image_name}},
        "8": {"class_type": "ImageScale",
              "inputs": {"image": ["7", 0], "upscale_method": "lanczos",
                         "width": 832, "height": 480, "crop": "disabled"}},
        # Accelerator LoRAs (lightx2v 4-step — strength 1.5 for aggressive accel)
        "100": {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["2", 0],
                            "lora_name": "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
                            "strength_model": accel_strength}},
        "120": {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["3", 0],
                            "lora_name": "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
                            "strength_model": accel_strength}},
        # ModelSamplingSD3 shift
        "30": {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["100", 0], "shift": shift}},
        "31": {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["120", 0], "shift": shift}},
        # WanImageToVideo conditioning
        "40": {"class_type": "WanImageToVideo",
               "inputs": {"width": 832, "height": 480, "length": length,
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
        "60": {"class_type": "VAEDecode",
               "inputs": {"samples": ["51", 0], "vae": ["4", 0]}},
        "70": {"class_type": "VHS_VideoCombine",
               "inputs": {"images": ["60", 0], "frame_rate": 16.0,
                           "loop_count": 0, "filename_prefix": "wt_director",
                           "format": "image/gif", "pingpong": False,
                           "save_output": True}},
    }


# ─── Pipeline orchestration ─────────────────────────────────────────────────

class Pipeline:
    """Orchestrates the 5-act walkthrough generation with dependency chaining."""

    def __init__(self, server, dry_run=False):
        self.server = server
        self.dry_run = dry_run
        self.gerald_upload = None  # Set after Act I uploads Gerald
        self.body_upload = None    # Set after Act II body generation
        self.results = {}          # Track intermediate results

    def _run(self, name, wf, dest, timeout=1800):
        if self.dry_run:
            print(f"  [DRY RUN] {name} -> {dest.name}")
            return True
        return run_step(self.server, name, wf, dest, timeout)

    def _upload(self, local_path, prefix="wt"):
        if self.dry_run:
            return f"{prefix}_dry_run.png"
        return upload_image(self.server, str(local_path),
                           f"{prefix}_{uuid.uuid4().hex[:6]}.png")

    def act_0_generate_gerald(self):
        """Generate Gerald's source photo if it doesn't exist."""
        print("\n" + "=" * 60)
        print("  PROLOGUE: Generating Gerald McFluffington III")
        print("=" * 60)

        if GERALD_SOURCE.exists():
            print(f"  Gerald already exists: {GERALD_SOURCE.name}")
            self.gerald_upload = self._upload(GERALD_SOURCE, "gerald")
            return True

        wf = wf_generate_gerald()
        if self._run("Generate Gerald", wf, GERALD_SOURCE):
            self.gerald_upload = self._upload(GERALD_SOURCE, "gerald")
            return True
        return False

    def act_1_casting_polaroids(self):
        """Act I: Generate 3 casting variants + complete shot."""
        print("\n" + "=" * 60)
        print("  ACT I: CASTING POLAROIDS")
        print("  'I'd like three shots. One serious, one mysterious,")
        print("   and one where I look like young Clooney.'")
        print("=" * 60)

        if not self.gerald_upload:
            self.gerald_upload = self._upload(GERALD_SOURCE, "gerald")

        variants = [
            ("casting_01", "codeformer-v0.1.0.pth",  "CodeFormer Sharp"),
            ("casting_02", "GPEN-BFR-2048.onnx",     "GPEN-2048 Balanced"),
            ("casting_03", "codeformer-v0.1.0.pth",  "CodeFormer Faithful"),
        ]

        ok = True
        for label, restore, desc in variants:
            wf = wf_casting_polaroid(self.gerald_upload, restore, label)
            wf = _link_reactor_opts(wf)
            dest = OUTPUT_DIR / f"{label}.png"
            if not self._run(f"Casting {desc}", wf, dest):
                ok = False

        # Casting complete — the "selected" variant (#2)
        wf = wf_casting_complete(self.gerald_upload)
        dest = OUTPUT_DIR / "casting_complete.png"
        if not self._run("Casting Complete (selected)", wf, dest):
            ok = False

        return ok

    def act_2_body_double(self):
        """Act II: Generate 3 body variants + face swap + rembg."""
        print("\n" + "=" * 60)
        print("  ACT II: BODY DOUBLE")
        print("  'I want action hero, but approachable.'")
        print("=" * 60)

        if not self.gerald_upload:
            self.gerald_upload = self._upload(GERALD_SOURCE, "gerald")

        ok = True

        # Generate 3 body variants
        for i in range(1, 4):
            wf = wf_body_generate(i)
            body_raw = OUTPUT_DIR / f"_body_raw_{i}.png"
            if not self._run(f"Body variant {i}", wf, body_raw):
                ok = False
                continue

            # Face swap Gerald onto body
            body_up = self._upload(body_raw, f"body_raw_{i}")
            wf_swap = wf_faceswap_onto_body(body_up, self.gerald_upload)
            wf_swap = _link_reactor_opts(wf_swap)
            body_swapped = OUTPUT_DIR / f"_body_swapped_{i}.png"
            if not self._run(f"Face swap body {i}", wf_swap, body_swapped):
                ok = False
                continue

            # Remove background
            swapped_up = self._upload(body_swapped, f"body_swapped_{i}")
            wf_bg = wf_rembg(swapped_up, f"wt_body_transparent_{i}")
            body_final = OUTPUT_DIR / f"body_{i:02d}.png"
            if not self._run(f"Rembg body {i}", wf_bg, body_final):
                ok = False
            elif i == 2:
                # Save body #2 as the "complete" selection
                self.results["body_selected"] = body_final

        # Body complete — copy selected variant
        selected = self.results.get("body_selected", OUTPUT_DIR / "body_02.png")
        dest = OUTPUT_DIR / "body_complete.png"
        if selected.exists() and not self.dry_run:
            import shutil
            shutil.copy2(selected, dest)
            print(f"  [Body Complete] -> {dest.name}")
        elif self.dry_run:
            print(f"  [DRY RUN] Body Complete -> {dest.name}")

        return ok

    def act_3_wardrobe(self):
        """Act III: Wardrobe Department — Klein Flux 2 inpaint clothing."""
        print("\n" + "=" * 60)
        print("  ACT III: WARDROBE DEPARTMENT")
        print("  'The costume lady had OPINIONS.'")
        print("=" * 60)

        body_src = OUTPUT_DIR / "body_02.png"
        if not body_src.exists() and not self.dry_run:
            print("  SKIP — body_02.png not found (run Act II first)")
            return False

        ok = True
        outfits = [
            ("wardrobe_shark", (
                "wearing a ridiculous full-body great white shark costume, "
                "grey felt shark body suit, dorsal fin hat on head, "
                "felt shark teeth framing face like a hood, tail dragging behind, "
                "standing stiffly with arms out, absurd but totally committed"
            )),
            ("wardrobe_reaction", (
                "wearing comically oversized elaborate medieval knight armor, "
                "huge ornate breastplate too big for him, chain mail hanging loose, "
                "massive gauntlets swallowing his hands, helmet visor half-down, "
                "standing awkwardly, visibly uncomfortable, armor doesn't fit"
            )),
            ("wardrobe_final", (
                "wearing casual relaxed outfit, bright Hawaiian shirt with bold "
                "palm tree and hibiscus print, unbuttoned over white t-shirt, "
                "blue jeans, comfortable flip flops, "
                "standing casually with one hand in pocket, relaxed confident smile"
            )),
        ]

        for label, prompt in outfits:
            # For walkthrough screenshots, generate the outfitted body as txt2img
            # (real pipeline uses Klein inpaint on canvas selection, but we need
            # standalone images for the markdown)
            wf = {
                "1": {"class_type": "CheckpointLoaderSimple",
                      "inputs": {"ckpt_name": CKPT_SDXL}},
                "2": {"class_type": "CLIPTextEncode",
                      "inputs": {"text": (
                          f"full body photograph of a regular dad bod man, late 40s, "
                          f"balding, round friendly face, slight belly, soft midsection, "
                          f"{prompt}, "
                          f"clean studio background, professional photography, 8k, sharp"
                      ), "clip": ["1", 1]}},
                "3": {"class_type": "CLIPTextEncode",
                      "inputs": {"text": NEG_BODY, "clip": ["1", 1]}},
                "4": {"class_type": "EmptyLatentImage",
                      "inputs": {"width": 768, "height": 1216, "batch_size": 1}},
                "5": {"class_type": "KSampler",
                      "inputs": {
                          "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                          "latent_image": ["4", 0], "seed": random_seed(),
                          "steps": 30, "cfg": 6.5,
                          "sampler_name": "dpmpp_2m_sde", "scheduler": "karras",
                          "denoise": 1.0,
                      }},
                "6": {"class_type": "VAEDecode",
                      "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
                "7": {"class_type": "SaveImage",
                      "inputs": {"images": ["6", 0],
                                  "filename_prefix": f"wt_{label}"}},
            }
            # Face swap Gerald's face onto the wardrobe shot
            wardrobe_raw = OUTPUT_DIR / f"_{label}_raw.png"
            if not self._run(f"Wardrobe: {label}", wf, wardrobe_raw):
                ok = False
                continue

            raw_up = self._upload(wardrobe_raw, label)
            wf_swap = wf_faceswap_onto_body(raw_up, self.gerald_upload)
            wf_swap = _link_reactor_opts(wf_swap)
            dest = OUTPUT_DIR / f"{label}.png"
            if not self._run(f"Face swap {label}", wf_swap, dest):
                ok = False

        # Wardrobe complete — copy the Hawaiian shirt final
        dest = OUTPUT_DIR / "wardrobe_complete.png"
        src = OUTPUT_DIR / "wardrobe_final.png"
        if src.exists() and not self.dry_run:
            import shutil
            shutil.copy2(src, dest)
            print(f"  [Wardrobe Complete] -> {dest.name}")
        elif self.dry_run:
            print(f"  [DRY RUN] Wardrobe Complete -> {dest.name}")

        # Create transparent version of wardrobe_final for Set Design compositing
        if src.exists() or self.dry_run:
            src_up = self._upload(src, "wardrobe_final_for_rembg")
            wf_bg = wf_rembg(src_up, "wt_wardrobe_transparent")
            transparent_dest = OUTPUT_DIR / "_wardrobe_final_transparent.png"
            self._run("Rembg wardrobe for compositing", wf_bg, transparent_dest)
            self.results["actor_transparent"] = transparent_dest

        return ok

    def act_4_set_design(self):
        """Act IV: Set Design — backgrounds + composite Gerald into scenes."""
        print("\n" + "=" * 60)
        print("  ACT IV: SET DESIGN")
        print("  'Every great actor needs fog.'")
        print("=" * 60)

        ok = True
        bg_prompts = [
            ("set_bg_01", (
                "tropical beach scene, palm trees, turquoise ocean, golden sand, "
                "bright sunny day, clear blue sky, photorealistic, no fog, "
                "cheerful atmosphere, paradise island, 8k"
            )),
            ("set_bg_02", (
                "tropical beach scene, palm trees, turquoise ocean, golden sand, "
                "sunset lighting, photorealistic, rolling fog, mysterious atmosphere, "
                "moody cinematic, dramatic clouds, golden hour, 8k"
            )),
            ("set_bg_03", (
                "tropical beach scene completely engulfed in thick fog, "
                "barely visible palm trees, extremely heavy mist, "
                "mysterious, eerie, atmospheric, low visibility, "
                "sunset glow through dense fog, cinematic, 8k"
            )),
        ]

        for label, prompt in bg_prompts:
            wf = wf_txt2img_background(prompt)
            dest = OUTPUT_DIR / f"{label}.png"
            if not self._run(f"Background: {label}", wf, dest):
                ok = False

        # Composite Gerald onto BG #2 (the fog-approved background)
        bg_path = OUTPUT_DIR / "set_bg_02.png"
        # Use transparent version of wardrobe_final (rembg'd in Act III)
        actor_path = self.results.get("actor_transparent",
                                       OUTPUT_DIR / "_wardrobe_final_transparent.png")

        if (bg_path.exists() and actor_path.exists()) or self.dry_run:
            # Upload both images
            bg_up = self._upload(bg_path, "set_bg")
            actor_up = self._upload(actor_path, "set_actor")
            # Composite actor onto background + Klein harmonization
            wf = wf_composite_actor(bg_up, actor_up)
            dest = OUTPUT_DIR / "set_complete.png"
            if not self._run("Composite: Gerald on beach", wf, dest):
                ok = False

            # set_final is a higher quality version (same scene, slightly different seed)
            dest_final = OUTPUT_DIR / "set_final.png"
            wf2 = wf_composite_actor(bg_up, actor_up)
            if not self._run("Set Final: polished", wf2, dest_final):
                ok = False
        else:
            print("  SKIP composite — missing bg or actor (run Acts II-III first)")

        return ok

    def _run_video(self, name, wf, dest_gif, timeout=1800):
        """Queue a Wan I2V workflow, wait, download the GIF result."""
        if self.dry_run:
            print(f"  [DRY RUN] {name} -> {dest_gif.name}")
            return True
        print(f"  [{name}] Queuing...", end="", flush=True)
        pid = queue_prompt(self.server, wf)
        if not pid:
            print(" FAILED (queue error)")
            return False
        print(f" {pid[:8]}...", end="", flush=True)
        outputs = wait_for_prompt(self.server, pid, timeout=timeout)
        if not outputs:
            print(" TIMEOUT")
            return False
        # VHS_VideoCombine puts GIFs in the "gifs" key
        for node_id, node_out in outputs.items():
            gifs = node_out.get("gifs", [])
            if gifs:
                item = gifs[0]
                fname = item.get("filename", "")
                subfolder = item.get("subfolder", "")
                ftype = item.get("type", "output")
                url = (f"{self.server}/view?filename={urllib.parse.quote(fname)}"
                       f"&type={ftype}")
                if subfolder:
                    url += f"&subfolder={urllib.parse.quote(subfolder)}"
                urllib.request.urlretrieve(url, dest_gif)
                print(f" -> {dest_gif.name}")
                return True
        print(" FAILED (no GIF output)")
        return False

    def act_5_director(self):
        """Act V: The Director's Chair — Wan 2.2 I2V video generation."""
        print("\n" + "=" * 60)
        print("  ACT V: THE DIRECTOR'S CHAIR")
        print("  'I've been preparing for this role my entire life.'")
        print("=" * 60)

        scene_src = OUTPUT_DIR / "set_complete.png"
        if not scene_src.exists() and not self.dry_run:
            print("  SKIP — set_complete.png not found (run Act IV first)")
            return False

        scene_up = self._upload(scene_src, "director_scene")
        ok = True

        # ── Video 1: Walk — approaching through fog ──
        wf = wf_wan_i2v(
            scene_up,
            prompt=(
                "man in Hawaiian shirt walking slowly forward on foggy beach, "
                "cinematic approach toward camera, sunset golden hour, "
                "shirt billowing gently in sea breeze, palm trees sway in background, "
                "waves rolling on shore, fog drifting, smooth steady camera"
            ),
            negative="static, frozen, distorted face, morphing, ugly, jitter",
            length=33,
        )
        dest_walk = OUTPUT_DIR / "director_walk.gif"
        if not self._run_video("Director: Walk", wf, dest_walk):
            ok = False

        # ── Video 2: Pause — dramatic stop ──
        wf2 = wf_wan_i2v(
            scene_up,
            prompt=(
                "man in Hawaiian shirt standing still on foggy beach, "
                "dramatic pause, slight head turn toward camera, wind in hair, "
                "sunset silhouette, fog rolling past, moody golden hour atmosphere, "
                "subtle shirt flutter, contemplative moment"
            ),
            negative="walking, running, fast motion, distorted, morphing, ugly",
            length=33,
        )
        dest_pause = OUTPUT_DIR / "director_pause.gif"
        if not self._run_video("Director: Pause", wf2, dest_pause):
            ok = False

        # ── Video 3: The Look — slow turn close-up ──
        wf3 = wf_wan_i2v(
            scene_up,
            prompt=(
                "close-up cinematic shot, man in Hawaiian shirt slowly turns head "
                "toward camera with confident knowing smile, "
                "foggy beach sunset behind, dramatic rim lighting on face, "
                "golden hour glow, shallow depth of field, film grain, "
                "the look of a man who knows this is his moment"
            ),
            negative="fast motion, distorted face, morphing, ugly, zoom, jitter",
            length=33,
        )
        dest_look = OUTPUT_DIR / "director_look.gif"
        if not self._run_video("Director: The Look", wf3, dest_look):
            ok = False

        # ── Video 4: Complete — walking away from explosion ──
        wf4 = wf_wan_i2v(
            scene_up,
            prompt=(
                "epic cinematic shot, man in Hawaiian shirt walking confidently away "
                "from massive fiery explosion on beach behind him, "
                "not looking back, debris and sparks flying, "
                "action movie moment, sunset, palm trees silhouetted against fireball, "
                "dramatic backlighting, cool guys dont look at explosions"
            ),
            negative="looking back, turning around, distorted, ugly, static, frozen",
            length=33,
        )
        dest_complete = OUTPUT_DIR / "director_complete.gif"
        if not self._run_video("Director: Complete", wf4, dest_complete):
            ok = False

        # ── Extract still frames as PNGs for the walkthrough markdown ──
        print("  Extracting PNG stills from GIFs...")
        for gif_name, png_name in [
            ("director_walk.gif", "director_walk.png"),
            ("director_pause.gif", "director_pause.png"),
            ("director_look.gif", "director_look.png"),
            ("director_complete.gif", "director_complete.png"),
        ]:
            gif_path = OUTPUT_DIR / gif_name
            png_path = OUTPUT_DIR / png_name
            if gif_path.exists() and not self.dry_run:
                try:
                    from PIL import Image
                    with Image.open(gif_path) as im:
                        # Grab middle frame for a good representative still
                        n_frames = getattr(im, 'n_frames', 1)
                        target = n_frames // 2
                        im.seek(target)
                        im.convert("RGB").save(png_path)
                    print(f"    {png_name} (frame {target}/{n_frames})")
                except Exception as e:
                    print(f"    {png_name} FAILED: {e}")
            elif self.dry_run:
                print(f"    [DRY RUN] {png_name}")

        return ok


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate Magic Studios Walkthrough assets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Acts:
  0  Prologue — Generate Gerald's source photo (if missing)
  1  Casting Polaroids — 3 variants + complete
  2  Body Double — 3 body variants + face swap + rembg
  3  Wardrobe Department — shark, knight, Hawaiian shirt
  4  Set Design — 3 backgrounds + composite
  5  Director's Chair — walk, pause, look, explosion

Examples:
  python generate_walkthrough.py                    # Run all acts
  python generate_walkthrough.py --act 1            # Only Act I
  python generate_walkthrough.py --act 1,2,3        # Acts I through III
  python generate_walkthrough.py --dry-run           # Validate without running
  python generate_walkthrough.py --list              # List all output files
        """
    )
    parser.add_argument("--server", default=SERVER, help="ComfyUI server URL")
    parser.add_argument("--act", help="Comma-separated act numbers (0-5)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    parser.add_argument("--list", action="store_true", help="List all output files")
    args = parser.parse_args()

    if args.list:
        files = [
            "Prologue:",
            "  walkthrough_gerald_source.png    Gerald's Walgreens headshot",
            "",
            "Act I — Casting Polaroids:",
            "  casting_01.png                   CodeFormer Sharp variant",
            "  casting_02.png                   GPEN-2048 Balanced variant",
            "  casting_03.png                   CodeFormer Faithful variant",
            "  casting_complete.png             Selected casting photo",
            "",
            "Act II — Body Double:",
            "  body_01.png                      Fitness model build (transparent)",
            "  body_02.png                      Athletic casual (transparent)",
            "  body_03.png                      Beach-ready (transparent)",
            "  body_complete.png                Selected body (= body_02)",
            "",
            "Act III — Wardrobe Department:",
            "  wardrobe_shark.png               Marguerite's magnum opus",
            "  wardrobe_reaction.png            Gerald's face says it all",
            "  wardrobe_final.png               The Hawaiian shirt, finally",
            "  wardrobe_complete.png            Final wardrobe selection",
            "",
            "Act IV — Set Design:",
            "  set_bg_01.png                    Too sunny (Gerald disapproves)",
            "  set_bg_02.png                    Fog: approved",
            "  set_bg_03.png                    Too much fog, even for me",
            "  set_complete.png                 Gerald composited on foggy beach",
            "  set_final.png                    Polished final composite",
            "",
            "Act V — Director's Chair (Wan 2.2 I2V video + PNG stills):",
            "  director_walk.gif                Walking through the fog (video)",
            "  director_pause.gif               The dramatic stop (video)",
            "  director_look.gif                The confident turn (video)",
            "  director_complete.gif            Explosion walk-away (video)",
            "  director_walk.png                Still frame from walk",
            "  director_pause.png               Still frame from pause",
            "  director_look.png                Still frame from look",
            "  director_complete.png            Still frame from explosion",
        ]
        print("\nMagic Studios Walkthrough — All Assets")
        print("=" * 55)
        for line in files:
            print(f"  {line}")
        print(f"\n  Output: {OUTPUT_DIR}/")
        print(f"  Total: 21 walkthrough assets + 1 source photo")
        return

    # Determine which acts to run
    acts = {0, 1, 2, 3, 4, 5}
    if args.act:
        acts = set(int(a.strip()) for a in args.act.split(","))

    pipeline = Pipeline(args.server, dry_run=args.dry_run)

    print("\n" + "=" * 60)
    print("  SPELLCASTER MAGIC STUDIOS — WALKTHROUGH GENERATOR")
    print(f"  Server: {args.server}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Acts:   {sorted(acts)}")
    if args.dry_run:
        print("  MODE:   DRY RUN (no workflows will be queued)")
    print("=" * 60)

    # Always ensure Gerald exists and is uploaded
    if 0 in acts or not GERALD_SOURCE.exists():
        pipeline.act_0_generate_gerald()
    elif GERALD_SOURCE.exists() and not pipeline.gerald_upload:
        # Gerald exists on disk but hasn't been uploaded yet
        print(f"\n  Gerald source exists — uploading to server...")
        pipeline.gerald_upload = pipeline._upload(GERALD_SOURCE, "gerald")

    if 1 in acts:
        pipeline.act_1_casting_polaroids()
    if 2 in acts:
        pipeline.act_2_body_double()
    if 3 in acts:
        pipeline.act_3_wardrobe()
    if 4 in acts:
        pipeline.act_4_set_design()
    if 5 in acts:
        pipeline.act_5_director()

    print("\n" + "=" * 60)
    print("  GENERATION COMPLETE")
    # Count generated files
    generated = list(OUTPUT_DIR.glob("*.png"))
    print(f"  Files in {OUTPUT_DIR.name}/: {len(generated)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
