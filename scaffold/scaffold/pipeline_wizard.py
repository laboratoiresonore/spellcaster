"""
Pipeline Wizard — guided configuration for complex, multi-step ComfyUI
pipelines that are built programmatically (not from JSON templates).

These pipelines correspond to the build_* functions in _workflows_v2.py
that chain multiple operations together:

  - Photo Restore:       upscale → face restore → sharpen
  - Detail Hallucinate:  optional upscale → img2img diffusion
  - SUPIR Restoration:   5-stage AI restoration with optional SDXL refinement
  - LTX Video:           text/image-to-video with optional 2-stage, distilled, RTX, RIFE
  - WAN Video:           dual-model video with optional RTX, RIFE, face swap
  - Video Reactor:       video upscale + face swap chain
  - SeedVR2 Upscale:     AI temporal video upscaler

State machine per user:
    idle -> pipeline_pick -> step_config -> [next step | confirm] -> done

Each pipeline has:
  - Steps (some optional, toggled on/off)
  - Per-step parameters with defaults
  - Pipeline-level presets (curated combos across all steps)

Designed for 7B models — numbered choices, no ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════
#  Pipeline parameter definitions
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineParam:
    """One tunable parameter within a pipeline step."""
    name: str
    label: str
    type: str                          # INT, FLOAT, STRING, BOOLEAN, COMBO
    default: Any
    choices: Optional[List[Any]] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    tooltip: Optional[str] = None


@dataclass
class PipelineStep:
    """One stage in a multi-step pipeline."""
    key: str
    label: str
    description: str
    required: bool = True              # False = user can skip this step
    params: List[PipelineParam] = field(default_factory=list)


@dataclass
class PipelineDef:
    """Full definition of a multi-step pipeline."""
    key: str
    label: str
    description: str
    build_fn: str                      # function name in _workflows_v2.py
    steps: List[PipelineStep] = field(default_factory=list)
    # Common params that apply to the whole pipeline (image, seed, etc.)
    common_params: List[PipelineParam] = field(default_factory=list)
    # Pipeline-level presets: name -> {param_name: value}
    presets: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
#  Pipeline definitions
# ═══════════════════════════════════════════════════════════════════════════

PIPELINES: Dict[str, PipelineDef] = {}


def _register(p: PipelineDef):
    PIPELINES[p.key] = p


# ── Photo Restore ─────────────────────────────────────────────────────────

_register(PipelineDef(
    key="photo_restore",
    label="Photo Restoration",
    description="Upscale + face restore + sharpen for old/damaged photos",
    build_fn="build_photo_restore",
    common_params=[
        PipelineParam("image_filename", "Input image", "STRING", ""),
    ],
    steps=[
        PipelineStep(
            key="upscale",
            label="Step 1 — Upscale",
            description="Super-resolution to recover lost detail",
            required=True,
            params=[
                PipelineParam("upscale_model", "Upscale model", "COMBO",
                              "4x-UltraSharp.pth",
                              choices=["4x-UltraSharp.pth",
                                       "4x_NMKD-Siax_200k.pth",
                                       "RealESRGAN_x4plus.pth",
                                       "4x_foolhardy_Remacri.pth"],
                              tooltip="SR model — UltraSharp is sharp, Remacri is natural"),
            ],
        ),
        PipelineStep(
            key="face_restore",
            label="Step 2 — Face Restoration",
            description="Detect and enhance faces with CodeFormer",
            required=True,
            params=[
                PipelineParam("face_model", "Face model", "COMBO",
                              "codeformer-v0.1.0.pth",
                              choices=["codeformer-v0.1.0.pth",
                                       "GFPGANv1.3.pth",
                                       "GFPGANv1.4.pth"]),
                PipelineParam("facedetection", "Face detector", "COMBO",
                              "retinaface_resnet50",
                              choices=["retinaface_resnet50",
                                       "retinaface_mobile0.25",
                                       "YOLOv5l", "YOLOv5n"]),
                PipelineParam("visibility", "Restoration blend", "FLOAT",
                              1.0, min_val=0.0, max_val=1.0,
                              tooltip="0=original face, 1=full restoration"),
                PipelineParam("codeformer_weight", "CodeFormer weight", "FLOAT",
                              0.7, min_val=0.0, max_val=1.0,
                              tooltip="Higher = more aggressive, may over-smooth"),
            ],
        ),
        PipelineStep(
            key="sharpen",
            label="Step 3 — Sharpen",
            description="Edge sharpening to restore fine details",
            required=True,
            params=[
                PipelineParam("sharpen_radius", "Radius", "FLOAT",
                              1.0, min_val=0.1, max_val=10.0,
                              tooltip="Sharpening kernel radius in pixels"),
                PipelineParam("sigma", "Sigma", "FLOAT",
                              1.0, min_val=0.1, max_val=10.0,
                              tooltip="Gaussian blur sigma"),
                PipelineParam("alpha", "Strength", "FLOAT",
                              1.0, min_val=0.0, max_val=2.0,
                              tooltip="0=none, >1=aggressive (halos at 1.5+)"),
            ],
        ),
    ],
    presets={
        "Quick fix": {
            "upscale_model": "4x-UltraSharp.pth",
            "face_model": "codeformer-v0.1.0.pth",
            "facedetection": "retinaface_resnet50",
            "visibility": 1.0,
            "codeformer_weight": 0.5,
            "sharpen_radius": 1.0,
            "sigma": 1.0,
            "alpha": 0.8,
        },
        "Full restoration": {
            "upscale_model": "4x-UltraSharp.pth",
            "face_model": "codeformer-v0.1.0.pth",
            "facedetection": "retinaface_resnet50",
            "visibility": 1.0,
            "codeformer_weight": 0.7,
            "sharpen_radius": 1.0,
            "sigma": 1.0,
            "alpha": 1.0,
        },
        "Gentle (preserve character)": {
            "upscale_model": "4x_foolhardy_Remacri.pth",
            "face_model": "codeformer-v0.1.0.pth",
            "facedetection": "retinaface_resnet50",
            "visibility": 0.7,
            "codeformer_weight": 0.4,
            "sharpen_radius": 1.0,
            "sigma": 1.0,
            "alpha": 0.5,
        },
    },
))


# ── Detail Hallucinate ────────────────────────────────────────────────────

_register(PipelineDef(
    key="detail_hallucinate",
    label="Detail Hallucination",
    description="Upscale + img2img diffusion to synthesize fine details",
    build_fn="build_detail_hallucinate",
    common_params=[
        PipelineParam("image_filename", "Input image", "STRING", ""),
        PipelineParam("seed", "Seed", "INT", -1, min_val=-1, max_val=2**32,
                      tooltip="-1 for random"),
    ],
    steps=[
        PipelineStep(
            key="upscale",
            label="Step 1 — Upscale (optional)",
            description="Traditional SR before diffusion pass",
            required=False,
            params=[
                PipelineParam("upscale_model", "Upscale model", "COMBO",
                              "4x-UltraSharp.pth",
                              choices=["4x-UltraSharp.pth",
                                       "4x_NMKD-Siax_200k.pth",
                                       "RealESRGAN_x4plus.pth",
                                       "4x_foolhardy_Remacri.pth"]),
                PipelineParam("upscale_factor", "Upscale factor", "FLOAT",
                              1.0, min_val=0.5, max_val=4.0,
                              tooltip="Multiplier — 1.0 uses the model's native scale"),
            ],
        ),
        PipelineStep(
            key="diffusion",
            label="Step 2 — Diffusion Detail Enhancement",
            description="Low-denoise img2img to hallucinate fine details",
            required=True,
            params=[
                PipelineParam("prompt_text", "Prompt", "STRING",
                              "ultra high detail, intricate textures, 8k, photorealistic, sharp focus",
                              tooltip="Guide what details to generate"),
                PipelineParam("negative_text", "Negative prompt", "STRING",
                              "blurry, low quality, artifacts, noise, watermark",
                              tooltip="What to avoid"),
                PipelineParam("denoise", "Denoise strength", "FLOAT",
                              0.35, min_val=0.1, max_val=0.7,
                              tooltip="0.2=subtle, 0.35=balanced, 0.5+=aggressive"),
                PipelineParam("cfg", "CFG scale", "FLOAT",
                              7.0, min_val=1.0, max_val=20.0,
                              tooltip="Prompt adherence — higher follows prompt more"),
                PipelineParam("steps", "Sampling steps", "INT",
                              None, min_val=10, max_val=80,
                              tooltip="Leave empty for preset default"),
            ],
        ),
    ],
    presets={
        "Subtle enhancement": {
            "denoise": 0.25,
            "cfg": 5.0,
            "prompt_text": "high quality, detailed, sharp focus",
            "negative_text": "blurry, artifacts, noise",
        },
        "Balanced hallucination": {
            "upscale_model": "4x-UltraSharp.pth",
            "upscale_factor": 1.0,
            "denoise": 0.35,
            "cfg": 7.0,
            "prompt_text": "ultra high detail, intricate textures, 8k, photorealistic, sharp focus",
            "negative_text": "blurry, low quality, artifacts, noise, watermark",
        },
        "Aggressive detail": {
            "upscale_model": "4x-UltraSharp.pth",
            "upscale_factor": 1.0,
            "denoise": 0.50,
            "cfg": 9.0,
            "prompt_text": "extremely detailed, fine textures, skin pores, fabric weave, 8k masterpiece",
            "negative_text": "blurry, low quality, artifacts, noise, watermark, smooth, plastic",
        },
    },
))


# ── SUPIR AI Restoration ──────────────────────────────────────────────────

_register(PipelineDef(
    key="supir",
    label="SUPIR AI Restoration",
    description="5-stage AI restoration with optional SDXL refinement pass",
    build_fn="build_supir",
    common_params=[
        PipelineParam("image_filename", "Input image", "STRING", ""),
        PipelineParam("seed", "Seed", "INT", -1, min_val=-1, max_val=2**32),
    ],
    steps=[
        PipelineStep(
            key="model",
            label="Step 1 — Model Selection",
            description="Choose SUPIR model + paired SDXL backbone",
            required=True,
            params=[
                PipelineParam("supir_model", "SUPIR model", "COMBO",
                              "SUPIR-v0Q_fp16.safetensors",
                              choices=["SUPIR-v0Q_fp16.safetensors",
                                       "SUPIR-v0F_fp16.safetensors"],
                              tooltip="v0Q = quality focus, v0F = fidelity focus"),
                PipelineParam("sdxl_model", "SDXL backbone", "COMBO",
                              "juggernautXL_v9Rdphoto2Lightning.safetensors",
                              choices=["juggernautXL_v9Rdphoto2Lightning.safetensors",
                                       "sd_xl_base_1.0.safetensors"],
                              tooltip="SDXL checkpoint paired with SUPIR model"),
            ],
        ),
        PipelineStep(
            key="restoration",
            label="Step 2 — Restoration Settings",
            description="Control restoration intensity and sampling",
            required=True,
            params=[
                PipelineParam("prompt", "Guidance prompt", "STRING",
                              "high quality, sharp focus, detailed, clean",
                              tooltip="Guides restoration direction"),
                PipelineParam("denoise", "Denoise / intensity", "FLOAT",
                              0.3, min_val=0.0, max_val=1.0,
                              tooltip="0.3=balanced, 0.5=strong, 1.0=aggressive"),
                PipelineParam("steps", "Sampling steps", "INT",
                              45, min_val=10, max_val=100,
                              tooltip="More steps = higher quality, slower"),
                PipelineParam("scale_by", "Internal upscale factor", "FLOAT",
                              1.0, min_val=1.0, max_val=2.0,
                              tooltip="1.0=pure restoration, >1.5=upscale+restore (uses tiled sampler)"),
            ],
        ),
    ],
    presets={
        "Quick restore": {
            "supir_model": "SUPIR-v0Q_fp16.safetensors",
            "denoise": 0.25,
            "steps": 25,
            "scale_by": 1.0,
            "prompt": "high quality, sharp focus, detailed",
        },
        "Full restoration": {
            "supir_model": "SUPIR-v0Q_fp16.safetensors",
            "denoise": 0.35,
            "steps": 45,
            "scale_by": 1.0,
            "prompt": "high quality, sharp focus, detailed, clean",
        },
        "Upscale + restore": {
            "supir_model": "SUPIR-v0Q_fp16.safetensors",
            "denoise": 0.3,
            "steps": 45,
            "scale_by": 1.5,
            "prompt": "high quality, sharp focus, highly detailed, 4k",
        },
        "Fidelity (preserve original)": {
            "supir_model": "SUPIR-v0F_fp16.safetensors",
            "denoise": 0.2,
            "steps": 35,
            "scale_by": 1.0,
            "prompt": "sharp focus, clean, noise-free",
        },
    },
))


# ── LTX Video 2.3 ─────────────────────────────────────────────────────────

_register(PipelineDef(
    key="ltx_video",
    label="LTX Video 2.3",
    description="Text-to-video or image-to-video generation with optional "
                "two-stage upscale, distilled fast mode, RTX/RIFE post-processing",
    build_fn="build_ltx_video",
    common_params=[
        PipelineParam("prompt_text", "Prompt", "STRING", "",
                      tooltip="Describe the video you want to generate"),
        PipelineParam("seed", "Seed", "INT", -1, min_val=-1, max_val=2**32),
        PipelineParam("image_filename", "Reference image (optional)", "STRING", "",
                      tooltip="Leave empty for text-to-video, provide for image-to-video"),
    ],
    steps=[
        PipelineStep(
            key="generation",
            label="Step 1 — Generation Mode",
            description="Resolution, frame count, and generation strategy",
            required=True,
            params=[
                PipelineParam("width", "Width", "INT", 768,
                              min_val=256, max_val=1920,
                              tooltip="Output width in pixels"),
                PipelineParam("height", "Height", "INT", 512,
                              min_val=256, max_val=1920,
                              tooltip="Output height in pixels"),
                PipelineParam("num_frames", "Frames", "INT", 25,
                              min_val=9, max_val=121,
                              tooltip="25 frames = 1 sec at 25fps"),
                PipelineParam("fps", "FPS", "INT", 25,
                              min_val=8, max_val=60),
                PipelineParam("two_stage", "Two-stage upscale", "BOOLEAN", False,
                              tooltip="Generate at half-res then latent upscale 2x"),
                PipelineParam("distilled", "Distilled (fast mode)", "BOOLEAN", False,
                              tooltip="LoRA-accelerated, 8 steps — 4x faster"),
            ],
        ),
        PipelineStep(
            key="guidance",
            label="Step 2 — Guidance & Sampling",
            description="STG/CFG tuning and i2v strength",
            required=True,
            params=[
                PipelineParam("steps", "Sampling steps", "INT", None,
                              min_val=4, max_val=80,
                              tooltip="Leave empty for preset default (30 normal, 8 distilled)"),
                PipelineParam("cfg", "CFG scale", "FLOAT", None,
                              min_val=1.0, max_val=15.0,
                              tooltip="Leave empty for default (4.0 normal, 1.0 distilled)"),
                PipelineParam("stg", "STG strength", "FLOAT", None,
                              min_val=0.0, max_val=3.0,
                              tooltip="Spatio-Temporal Guidance (1.0 normal, 0.0 distilled)"),
                PipelineParam("rescale", "STG rescale", "FLOAT", None,
                              min_val=0.0, max_val=1.0,
                              tooltip="STG rescale factor (0.7 normal, 0.0 distilled)"),
                PipelineParam("i2v_strength", "I2V strength", "FLOAT", 0.9,
                              min_val=0.0, max_val=1.0,
                              tooltip="Image-to-video adherence (only for i2v mode)"),
            ],
        ),
        PipelineStep(
            key="post_processing",
            label="Step 3 — Post-Processing (optional)",
            description="RTX video upscale and/or RIFE frame interpolation",
            required=False,
            params=[
                PipelineParam("rtx_scale", "RTX upscale factor", "INT", 0,
                              choices=[0, 2, 4],
                              tooltip="0=off, 2=2x, 4=4x (requires RTX 40/50 series)"),
                PipelineParam("interpolate", "RIFE frame interpolation", "BOOLEAN", False,
                              tooltip="Double frame count for smoother motion"),
                PipelineParam("pingpong", "Ping-pong loop", "BOOLEAN", False,
                              tooltip="Play forward then backward for seamless loop"),
            ],
        ),
    ],
    presets={
        "Quick preview": {
            "width": 512, "height": 384, "num_frames": 25,
            "distilled": True, "two_stage": False,
            "rtx_scale": 0, "interpolate": False,
        },
        "Standard quality": {
            "width": 768, "height": 512, "num_frames": 25,
            "distilled": False, "two_stage": False,
            "rtx_scale": 0, "interpolate": False,
        },
        "High quality (2-stage)": {
            "width": 768, "height": 512, "num_frames": 25,
            "distilled": False, "two_stage": True,
            "rtx_scale": 0, "interpolate": False,
        },
        "Cinematic (2-stage + RTX + RIFE)": {
            "width": 768, "height": 512, "num_frames": 49,
            "distilled": False, "two_stage": True,
            "rtx_scale": 2, "interpolate": True, "fps": 25,
        },
        "Fast + smooth (distilled + RIFE)": {
            "width": 768, "height": 512, "num_frames": 25,
            "distilled": True, "two_stage": False,
            "rtx_scale": 0, "interpolate": True,
        },
    },
))


# ── WAN 2.2 Video ─────────────────────────────────────────────────────────

_register(PipelineDef(
    key="wan_video",
    label="WAN 2.2 Video",
    description="Dual-model video generation with optional RTX, RIFE, face swap",
    build_fn="build_wan_video",
    common_params=[
        PipelineParam("image_filename", "Reference image", "STRING", "",
                      tooltip="Starting/anchor image for video generation"),
        PipelineParam("prompt_text", "Prompt", "STRING", "",
                      tooltip="Describe the motion/scene"),
        PipelineParam("negative_text", "Negative prompt", "STRING",
                      "blurry, low quality, distorted",
                      tooltip="What to avoid"),
        PipelineParam("seed", "Seed", "INT", -1, min_val=-1, max_val=2**32),
    ],
    steps=[
        PipelineStep(
            key="generation",
            label="Step 1 — Generation",
            description="Resolution, length, and model settings",
            required=True,
            params=[
                PipelineParam("width", "Width", "INT", 832,
                              min_val=256, max_val=1920),
                PipelineParam("height", "Height", "INT", 480,
                              min_val=256, max_val=1920),
                PipelineParam("length", "Frame count", "INT", 81,
                              min_val=17, max_val=241,
                              tooltip="81 frames ≈ 5 sec at 16fps"),
                PipelineParam("fps", "FPS", "INT", 16,
                              min_val=8, max_val=60),
                PipelineParam("turbo", "Turbo mode", "BOOLEAN", True,
                              tooltip="Faster generation with low-quality model for intermediate frames"),
                PipelineParam("loop", "Seamless loop", "BOOLEAN", False),
            ],
        ),
        PipelineStep(
            key="sampling",
            label="Step 2 — Sampling",
            description="Steps, CFG, and shift parameters",
            required=True,
            params=[
                PipelineParam("steps", "Sampling steps", "INT", None,
                              min_val=4, max_val=80,
                              tooltip="Leave empty for preset default"),
                PipelineParam("cfg", "CFG scale", "FLOAT", None,
                              min_val=1.0, max_val=15.0),
                PipelineParam("shift", "Noise shift", "FLOAT", None,
                              min_val=0.0, max_val=10.0),
                PipelineParam("second_step", "Second model step boundary", "INT", None,
                              min_val=0, max_val=50,
                              tooltip="Frame at which to switch to low-quality model"),
            ],
        ),
        PipelineStep(
            key="post_processing",
            label="Step 3 — Post-Processing (optional)",
            description="Upscaling, interpolation, and face swap",
            required=False,
            params=[
                PipelineParam("rtx_scale", "RTX upscale", "FLOAT", 2.5,
                              min_val=0.0, max_val=4.0,
                              tooltip="0=off, 2-4=RTX Video Super Resolution"),
                PipelineParam("interpolate", "RIFE interpolation", "BOOLEAN", True,
                              tooltip="4x frame interpolation for smooth motion"),
                PipelineParam("face_swap", "Face swap", "BOOLEAN", True,
                              tooltip="Apply face model to each frame"),
                PipelineParam("pingpong", "Ping-pong", "BOOLEAN", False),
                PipelineParam("save_raw", "Save raw (pre-upscale)", "BOOLEAN", False),
            ],
        ),
    ],
    presets={
        "Standard quality": {
            "width": 832, "height": 480, "length": 81,
            "turbo": True, "rtx_scale": 2.5,
            "interpolate": True, "face_swap": True,
        },
        "Fast preview": {
            "width": 576, "height": 320, "length": 33,
            "turbo": True, "rtx_scale": 0,
            "interpolate": False, "face_swap": False,
        },
        "High quality (no turbo)": {
            "width": 832, "height": 480, "length": 81,
            "turbo": False, "rtx_scale": 2.5,
            "interpolate": True, "face_swap": True,
        },
        "Long clip (10 sec)": {
            "width": 832, "height": 480, "length": 161,
            "turbo": True, "rtx_scale": 2.0,
            "interpolate": True, "face_swap": True,
        },
    },
))


# ── Video Reactor (upscale + face swap) ───────────────────────────────────

_register(PipelineDef(
    key="video_reactor",
    label="Video Face Swap + Upscale",
    description="Upscale video + apply face model(s) to every frame",
    build_fn="build_video_reactor",
    common_params=[
        PipelineParam("video_name", "Input video", "STRING", "",
                      tooltip="Video file to process"),
    ],
    steps=[
        PipelineStep(
            key="upscale",
            label="Step 1 — Upscale (optional)",
            description="Traditional upscaling before face swap",
            required=False,
            params=[
                PipelineParam("upscale_model", "Upscale model", "COMBO",
                              "4x-UltraSharp.pth",
                              choices=["4x-UltraSharp.pth",
                                       "4x_NMKD-Siax_200k.pth",
                                       "RealESRGAN_x4plus.pth"]),
                PipelineParam("upscale_factor", "Upscale factor", "FLOAT",
                              1.0, min_val=0.5, max_val=4.0),
                PipelineParam("rtx_scale", "RTX upscale", "FLOAT", 2.0,
                              min_val=0.0, max_val=4.0,
                              tooltip="0=off, applied after traditional upscale"),
            ],
        ),
        PipelineStep(
            key="face_swap",
            label="Step 2 — Face Swap",
            description="Apply ReActor face model(s) to every frame",
            required=True,
            params=[
                PipelineParam("face_models", "Face model file(s)", "STRING", "",
                              tooltip="Comma-separated face model filenames"),
                PipelineParam("face_restore_visibility", "Restore visibility", "FLOAT",
                              1.0, min_val=0.0, max_val=1.0),
                PipelineParam("codeformer_weight", "CodeFormer weight", "FLOAT",
                              0.7, min_val=0.0, max_val=1.0),
                PipelineParam("fps", "Output FPS", "INT", 16,
                              min_val=8, max_val=60),
            ],
        ),
    ],
    presets={
        "Standard": {
            "upscale_model": "4x-UltraSharp.pth",
            "upscale_factor": 1.0,
            "rtx_scale": 2.0,
            "face_restore_visibility": 1.0,
            "codeformer_weight": 0.7,
        },
        "Quality (no traditional upscale)": {
            "upscale_factor": 0.0,
            "rtx_scale": 2.0,
            "face_restore_visibility": 1.0,
            "codeformer_weight": 0.5,
        },
    },
))


# ── SeedVR2 Video Upscale ─────────────────────────────────────────────────

_register(PipelineDef(
    key="seedvr2_upscale",
    label="SeedVR2 AI Video Upscale",
    description="Temporal-aware AI video upscaling with SeedVR2",
    build_fn="build_seedvr2_video_upscale",
    common_params=[
        PipelineParam("video_name", "Input video", "STRING", ""),
        PipelineParam("seed", "Seed", "INT", -1, min_val=-1, max_val=2**32),
    ],
    steps=[
        PipelineStep(
            key="model",
            label="Step 1 — Model",
            description="SeedVR2 DiT + VAE model selection",
            required=True,
            params=[
                PipelineParam("dit_model", "DiT model", "COMBO",
                              "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
                              choices=["seedvr2_ema_3b_fp8_e4m3fn.safetensors"]),
                PipelineParam("vae_model", "VAE model", "COMBO",
                              "ema_vae_fp16.safetensors",
                              choices=["ema_vae_fp16.safetensors",
                                       "seedvr2_vae.safetensors"]),
                PipelineParam("vae_tiled", "Tiled VAE", "BOOLEAN", True,
                              tooltip="Required for large frames to fit in VRAM"),
            ],
        ),
        PipelineStep(
            key="upscale",
            label="Step 2 — Upscale Settings",
            description="Resolution, batch size, and quality settings",
            required=True,
            params=[
                PipelineParam("resolution", "Target resolution", "INT",
                              1024, min_val=512, max_val=4096,
                              tooltip="Shortest-edge pixel count"),
                PipelineParam("max_resolution", "Max resolution", "INT",
                              2048, min_val=1024, max_val=8192,
                              tooltip="Hard cap on output size"),
                PipelineParam("batch_size", "Batch size", "INT",
                              4, min_val=1, max_val=16,
                              tooltip="Frames per batch (lower = less VRAM)"),
                PipelineParam("uniform_batch_size", "Uniform batch", "BOOLEAN", True),
                PipelineParam("color_correction", "Color correction", "COMBO",
                              "lab",
                              choices=["lab", "wavelet", "wavelet_adaptive",
                                       "hsv", "adain", "none"]),
                PipelineParam("temporal_overlap", "Temporal overlap", "INT",
                              2, min_val=0, max_val=8,
                              tooltip="Frame overlap between batches for temporal coherence"),
                PipelineParam("fps", "Output FPS", "INT", 16,
                              min_val=8, max_val=60),
            ],
        ),
    ],
    presets={
        "Standard upscale": {
            "resolution": 1024, "max_resolution": 2048,
            "batch_size": 4, "color_correction": "lab",
            "temporal_overlap": 2,
        },
        "High quality": {
            "resolution": 2048, "max_resolution": 4096,
            "batch_size": 2, "color_correction": "lab",
            "temporal_overlap": 4,
        },
        "Fast preview": {
            "resolution": 720, "max_resolution": 1080,
            "batch_size": 8, "color_correction": "lab",
            "temporal_overlap": 1,
        },
    },
))


# ═══════════════════════════════════════════════════════════════════════════
#  Pipeline session
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineSession:
    """Tracks one user's progress through pipeline configuration."""
    user_id: str
    step: str = "idle"
    pipeline: Optional[PipelineDef] = None
    current_step_idx: int = 0
    # Collected parameter values: {param_name: value}
    values: Dict[str, Any] = field(default_factory=dict)
    # Which optional steps are enabled
    enabled_steps: Dict[str, bool] = field(default_factory=dict)
    # Currently editing a specific param
    editing_param: Optional[str] = None

    def reset(self):
        self.step = "idle"
        self.pipeline = None
        self.current_step_idx = 0
        self.values.clear()
        self.enabled_steps.clear()
        self.editing_param = None

    def current_pipeline_step(self) -> Optional[PipelineStep]:
        if self.pipeline and 0 <= self.current_step_idx < len(self.pipeline.steps):
            return self.pipeline.steps[self.current_step_idx]
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Pipeline Wizard
# ═══════════════════════════════════════════════════════════════════════════

class PipelineWizard:
    """
    Guided wizard for complex multi-step ComfyUI pipelines.

    Call handle(user_id, text) for each message.
    Returns the next message to send back.
    """

    def __init__(self):
        self._sessions: Dict[str, PipelineSession] = {}

    def get_session(self, user_id: str) -> Optional[PipelineSession]:
        return self._sessions.get(user_id)

    def handle(self, user_id: str, text: str) -> str:
        text = text.strip()
        low = text.lower()

        s = self._sessions.get(user_id)

        # Global commands
        if low in ("cancel", "quit", "exit", "stop"):
            if s:
                s.reset()
            return "Cancelled. Type 'menu' to browse pipelines."

        if low in ("menu", "pipelines", "start", "home"):
            if s:
                s.reset()
            return self._pipeline_menu(user_id)

        if low == "help":
            return self._help_text()

        # No session or idle
        if s is None or s.step == "idle":
            s = PipelineSession(user_id=user_id, step="pick")
            self._sessions[user_id] = s
            if low in ("", "hi", "hello"):
                return self._pipeline_menu(user_id)
            return self._handle_pick(s, text)

        handler = getattr(self, f"_handle_{s.step}", None)
        if handler:
            return handler(s, text)

        s.reset()
        return self._pipeline_menu(user_id)

    # ------------------------------------------------------------------
    # Pipeline menu
    # ------------------------------------------------------------------

    def _pipeline_menu(self, user_id: str) -> str:
        s = PipelineSession(user_id=user_id, step="pick")
        self._sessions[user_id] = s

        lines = [
            "Multi-Step Pipelines",
            "=" * 35,
            "",
        ]

        pipe_list = list(PIPELINES.values())
        for i, p in enumerate(pipe_list, 1):
            step_labels = ", ".join(st.label.split(" — ", 1)[-1] for st in p.steps)
            lines.append(f"  {i}. {p.label}")
            lines.append(f"     {p.description}")
            lines.append(f"     Steps: {step_labels}")
            lines.append("")

        lines.append("Pick a number, or describe what you want.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Pipeline pick
    # ------------------------------------------------------------------

    def _handle_pick(self, s: PipelineSession, text: str) -> str:
        low = text.lower()
        pipe_list = list(PIPELINES.values())

        # Numeric pick
        try:
            idx = int(text) - 1
            if 0 <= idx < len(pipe_list):
                return self._select_pipeline(s, pipe_list[idx])
        except ValueError:
            pass

        # Keyword match
        best, best_score = None, 0
        for p in pipe_list:
            score = 0
            if p.key in low:
                score = 50
            else:
                words = set(low.split())
                target = set(p.label.lower().split()) | set(p.description.lower().split())
                score = len(words & target) * 10
            if score > best_score:
                best_score = score
                best = p

        if best and best_score >= 10:
            return self._select_pipeline(s, best)

        return f"Pick a number (1-{len(pipe_list)}) or describe what you want."

    def _select_pipeline(self, s: PipelineSession, pipeline: PipelineDef) -> str:
        s.pipeline = pipeline
        s.values.clear()
        s.enabled_steps.clear()

        # Enable all required steps, mark optional as disabled by default
        for step in pipeline.steps:
            s.enabled_steps[step.key] = step.required

        # If presets exist, offer them first
        if pipeline.presets:
            s.step = "preset"
            return self._preset_menu(s)

        # Otherwise go straight to step config
        s.step = "step_overview"
        s.current_step_idx = 0
        return self._step_overview(s)

    # ------------------------------------------------------------------
    # Preset selection
    # ------------------------------------------------------------------

    def _preset_menu(self, s: PipelineSession) -> str:
        p = s.pipeline
        preset_list = list(p.presets.keys())

        lines = [
            f"{p.label}",
            "=" * 35,
            "",
            "Choose a starting configuration:",
            "",
        ]

        for i, name in enumerate(preset_list, 1):
            lines.append(f"  {i}. {name}")

        lines.append("")
        lines.append(f"  {len(preset_list) + 1}. Manual (step by step)")
        lines.append(f"  {len(preset_list) + 2}. All defaults")
        lines.append("")
        lines.append("Pick a number.")
        return "\n".join(lines)

    def _handle_preset(self, s: PipelineSession, text: str) -> str:
        preset_list = list(s.pipeline.presets.keys())
        n = len(preset_list)

        try:
            idx = int(text)
        except ValueError:
            return f"Pick a number (1-{n + 2})."

        if 1 <= idx <= n:
            # Apply preset
            preset_name = preset_list[idx - 1]
            preset_vals = s.pipeline.presets[preset_name]
            s.values.update(preset_vals)
            # Enable optional steps if preset sets their params
            for step in s.pipeline.steps:
                if not step.required:
                    step_param_names = {p.name for p in step.params}
                    if step_param_names & set(preset_vals.keys()):
                        s.enabled_steps[step.key] = True
            s.step = "confirm"
            return self._confirm(s, f"Preset: {preset_name}")
        elif idx == n + 1:
            # Manual
            s.step = "step_overview"
            s.current_step_idx = 0
            return self._step_overview(s)
        elif idx == n + 2:
            # All defaults
            s.step = "confirm"
            return self._confirm(s, "All defaults")
        else:
            return f"Pick a number (1-{n + 2})."

    # ------------------------------------------------------------------
    # Step overview (shows all steps, lets user navigate)
    # ------------------------------------------------------------------

    def _step_overview(self, s: PipelineSession) -> str:
        p = s.pipeline
        step_def = s.current_pipeline_step()
        if step_def is None:
            s.step = "confirm"
            return self._confirm(s)

        lines = [
            f"{p.label} — {step_def.label}",
            f"{step_def.description}",
            "=" * 40,
            "",
        ]

        # If optional, ask whether to enable
        if not step_def.required:
            enabled = s.enabled_steps.get(step_def.key, False)
            status = "ENABLED" if enabled else "DISABLED"
            lines.append(f"  This step is optional [{status}]")
            lines.append("")
            if not enabled:
                lines.append("  1. Enable this step")
                lines.append("  2. Skip to next step")
                lines.append("")
                lines.append("Pick a number.")
                s.step = "toggle_optional"
                return "\n".join(lines)

        # Show params for this step
        for i, param in enumerate(step_def.params, 1):
            val = s.values.get(param.name, param.default)
            val_str = _fmt(val)
            lines.append(f"  {i}. {param.label} = {val_str}")
            if param.tooltip:
                lines.append(f"     {param.tooltip}")

        n = len(step_def.params)
        lines.append("")
        lines.append(f"  {n + 1}. Accept & continue to next step")
        lines.append(f"  {n + 2}. Accept all defaults & skip to confirmation")
        lines.append("")
        lines.append("Pick a parameter number to change, or an action.")
        s.step = "step_config"
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Toggle optional step
    # ------------------------------------------------------------------

    def _handle_toggle_optional(self, s: PipelineSession, text: str) -> str:
        try:
            idx = int(text)
        except ValueError:
            return "Pick 1 (enable) or 2 (skip)."

        step_def = s.current_pipeline_step()

        if idx == 1:
            s.enabled_steps[step_def.key] = True
            s.step = "step_overview"
            return self._step_overview(s)
        elif idx == 2:
            s.current_step_idx += 1
            s.step = "step_overview"
            return self._step_overview(s)
        else:
            return "Pick 1 (enable) or 2 (skip)."

    # ------------------------------------------------------------------
    # Step param config
    # ------------------------------------------------------------------

    def _handle_step_config(self, s: PipelineSession, text: str) -> str:
        step_def = s.current_pipeline_step()
        n = len(step_def.params)

        try:
            idx = int(text)
        except ValueError:
            low = text.lower()
            if low in ("next", "continue", "accept"):
                return self._advance_step(s)
            if low in ("done", "skip", "defaults"):
                s.step = "confirm"
                return self._confirm(s)
            return f"Pick a number (1-{n + 2})."

        if 1 <= idx <= n:
            s.editing_param = step_def.params[idx - 1].name
            s.step = "edit_param"
            return self._ask_param(s, step_def.params[idx - 1])
        elif idx == n + 1:
            return self._advance_step(s)
        elif idx == n + 2:
            s.step = "confirm"
            return self._confirm(s)
        else:
            return f"Pick a number (1-{n + 2})."

    def _advance_step(self, s: PipelineSession) -> str:
        s.current_step_idx += 1
        s.step = "step_overview"
        return self._step_overview(s)

    # ------------------------------------------------------------------
    # Edit single param
    # ------------------------------------------------------------------

    def _ask_param(self, s: PipelineSession, param: PipelineParam) -> str:
        lines = [f"Editing: {param.label}"]

        current = s.values.get(param.name, param.default)
        lines.append(f"  Current: {_fmt(current)}")

        if param.choices:
            lines.append("")
            for i, c in enumerate(param.choices, 1):
                marker = " ←" if c == current else ""
                lines.append(f"  {i}. {c}{marker}")
        elif param.type == "BOOLEAN":
            lines.append("  Reply: yes / no")
        elif param.type == "INT":
            rng = ""
            if param.min_val is not None:
                rng += f" min={int(param.min_val)}"
            if param.max_val is not None:
                rng += f" max={int(param.max_val)}"
            lines.append(f"  Enter a whole number{rng}")
        elif param.type == "FLOAT":
            rng = ""
            if param.min_val is not None:
                rng += f" min={param.min_val}"
            if param.max_val is not None:
                rng += f" max={param.max_val}"
            lines.append(f"  Enter a decimal number{rng}")
        else:
            lines.append("  Enter new value")

        lines.append("")
        lines.append("  Type 'keep' to keep current value.")
        return "\n".join(lines)

    def _handle_edit_param(self, s: PipelineSession, text: str) -> str:
        low = text.lower().strip()

        if low in ("keep", "cancel", "back"):
            s.step = "step_overview"
            return self._step_overview(s)

        # Find the param definition
        param = self._find_param(s, s.editing_param)
        if not param:
            s.step = "step_overview"
            return self._step_overview(s)

        value = _parse_value(param, text)
        if value is None:
            return "Invalid input. Try again, or type 'keep'."

        s.values[param.name] = value
        s.step = "step_overview"
        return self._step_overview(s)

    def _find_param(self, s: PipelineSession, name: str) -> Optional[PipelineParam]:
        for step in s.pipeline.steps:
            for p in step.params:
                if p.name == name:
                    return p
        for p in s.pipeline.common_params:
            if p.name == name:
                return p
        return None

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    def _confirm(self, s: PipelineSession, label: str = "") -> str:
        p = s.pipeline

        lines = [
            f"Ready to run: {p.label}",
        ]
        if label:
            lines.append(f"Configuration: {label}")
        lines.append("=" * 40)
        lines.append("")

        # Show enabled steps and their param values
        for step in p.steps:
            enabled = s.enabled_steps.get(step.key, step.required)
            if not enabled:
                lines.append(f"  {step.label}: SKIPPED")
                continue

            lines.append(f"  {step.label}:")
            for param in step.params:
                val = s.values.get(param.name, param.default)
                lines.append(f"    {param.label} = {_fmt(val)}")
            lines.append("")

        # Show common params that have been set
        set_common = [p for p in s.pipeline.common_params
                      if p.name in s.values and s.values[p.name]]
        if set_common:
            lines.append("  Common:")
            for param in set_common:
                lines.append(f"    {param.label} = {_fmt(s.values[param.name])}")
            lines.append("")

        lines.append("1. Confirm and run")
        lines.append("2. Edit parameters")
        lines.append("3. Choose different pipeline")
        lines.append("")
        lines.append("Reply with the number.")
        s.step = "confirm_choice"
        return "\n".join(lines)

    def _handle_confirm_choice(self, s: PipelineSession, text: str) -> str:
        low = text.lower().strip()

        if low in ("1", "confirm", "yes", "y", "run", "go"):
            s.step = "done"
            return self._finalize(s)
        if low in ("2", "edit", "change"):
            s.current_step_idx = 0
            s.step = "step_overview"
            return self._step_overview(s)
        if low in ("3", "back", "different"):
            s.reset()
            return self._pipeline_menu(s.user_id)

        return "Reply 1 (run), 2 (edit), or 3 (different pipeline)."

    # ------------------------------------------------------------------
    # Finalize — produce the build function call spec
    # ------------------------------------------------------------------

    def _finalize(self, s: PipelineSession) -> str:
        p = s.pipeline

        # Gather all params with defaults filled in
        final: Dict[str, Any] = {}
        for param in p.common_params:
            final[param.name] = s.values.get(param.name, param.default)

        for step in p.steps:
            enabled = s.enabled_steps.get(step.key, step.required)
            if not enabled:
                continue
            for param in step.params:
                val = s.values.get(param.name, param.default)
                if val is not None:
                    final[param.name] = val

        # Store for external retrieval
        s._final_params = final
        s._build_fn = p.build_fn

        import json
        params_json = json.dumps(final, indent=2, default=str)

        return (
            f"Pipeline '{p.label}' configured.\n\n"
            f"Build function: {p.build_fn}\n"
            f"```json\n{params_json}\n```\n\n"
            f"Ready to execute via ComfyUI."
        )

    def get_final_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the completed pipeline config for a user."""
        s = self._sessions.get(user_id)
        if s and hasattr(s, "_final_params"):
            return {
                "build_fn": s._build_fn,
                "params": s._final_params,
            }
        return None

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _help_text(self) -> str:
        return (
            "Pipeline Wizard Help\n"
            "====================\n\n"
            "Multi-step pipelines chain multiple operations:\n"
            "  e.g., Photo Restore = Upscale → Face Restore → Sharpen\n\n"
            "Commands:\n"
            "  menu       — Browse available pipelines\n"
            "  cancel     — Cancel and reset\n"
            "  help       — Show this message\n\n"
            "Navigation:\n"
            "  - Type a number to pick from any menu\n"
            "  - Type 'keep' to keep a parameter's current value\n"
            "  - Type 'back' to go up one level\n"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  System prompt builder
# ═══════════════════════════════════════════════════════════════════════════

def build_pipeline_system_prompt() -> str:
    """Build a system prompt section describing available pipelines and presets."""
    lines = [
        "MULTI-STEP PIPELINES:",
        "These are complex, multi-stage workflows that chain multiple operations.",
        "Each pipeline has presets for common configurations.",
        "",
    ]

    for key, p in PIPELINES.items():
        step_desc = " → ".join(
            st.label.split(" — ", 1)[-1] for st in p.steps
        )
        lines.append(f"  {p.label} ({p.key}):")
        lines.append(f"    {p.description}")
        lines.append(f"    Pipeline: {step_desc}")

        if p.presets:
            preset_names = ", ".join(p.presets.keys())
            lines.append(f"    Presets: {preset_names}")

        lines.append(f"    Build function: {p.build_fn}()")
        lines.append("")

    lines.append(
        "When the user wants a multi-step operation (restore, hallucinate, "
        "video generation, video upscale), route them to the appropriate pipeline."
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _fmt(val: Any) -> str:
    if val is None:
        return "(auto)"
    if isinstance(val, bool):
        return "yes" if val else "no"
    if isinstance(val, str):
        if not val:
            return "(empty)"
        if len(val) > 50:
            return f'"{val[:50]}..."'
        return f'"{val}"'
    return str(val)


def _parse_value(param: PipelineParam, text: str) -> Any:
    low = text.lower().strip()

    # Choices
    if param.choices:
        try:
            idx = int(text) - 1
            if 0 <= idx < len(param.choices):
                return param.choices[idx]
        except ValueError:
            pass
        for c in param.choices:
            if low == str(c).lower():
                return c
        return None

    # Boolean
    if param.type == "BOOLEAN":
        if low in ("yes", "y", "true", "1", "on"):
            return True
        if low in ("no", "n", "false", "0", "off"):
            return False
        return None

    # Int
    if param.type == "INT":
        try:
            val = int(float(text))
            if param.min_val is not None and val < param.min_val:
                val = int(param.min_val)
            if param.max_val is not None and val > param.max_val:
                val = int(param.max_val)
            return val
        except ValueError:
            return None

    # Float
    if param.type == "FLOAT":
        try:
            val = float(text)
            if param.min_val is not None and val < param.min_val:
                val = param.min_val
            if param.max_val is not None and val > param.max_val:
                val = param.max_val
            return val
        except ValueError:
            return None

    # String
    return text
