"""Workflow Optimizer — VRAM estimation, resolution capping, and auto-tuning.

Analyzes a workflow before submission and applies safe adjustments:
  1. Estimates VRAM usage from resolution, model size, and frame count
  2. Auto-caps resolution when it would exceed available VRAM
  3. Enables tiled VAE for high-resolution video workflows
  4. Warns about known-problematic parameter combinations

Usage:
    from spellcaster_core.optimizer import optimize_workflow

    workflow, warnings = optimize_workflow(workflow, vram_gb=16.0)
    for w in warnings:
        print(f"[Optimizer] {w}")
"""

import json
import urllib.request


# ═══════════════════════════════════════════════════════════════════════
#  VRAM estimation heuristics
# ═══════════════════════════════════════════════════════════════════════
#
#  These are empirical estimates based on testing with RTX 5060 Ti 16GB.
#  They're intentionally conservative — better to cap resolution than OOM.

# Base VRAM per model architecture (GB, approximate with model loaded)
ARCH_BASE_VRAM = {
    "sd15": 2.5,
    "sdxl": 4.5,
    "illustrious": 4.5,
    "pony": 4.5,
    "flux1dev": 8.0,
    "flux2klein": 6.0,
    "chroma": 7.0,
    "zit": 5.0,
    "wan": 10.0,      # dual-UNET 14B
    "ltx": 9.0,       # 22B model
}

# Pixels per GB of extra VRAM needed (above base)
# Higher = more efficient (SD1.5 is more efficient per pixel than Flux)
PIXELS_PER_GB = {
    "sd15": 1_500_000,      # ~1.5M px/GB → 1024x1024 needs ~0.7 GB extra
    "sdxl": 800_000,        # ~0.8M px/GB → 1024x1024 needs ~1.3 GB extra
    "illustrious": 800_000,
    "flux1dev": 500_000,    # ~0.5M px/GB → 1024x1024 needs ~2 GB extra
    "flux2klein": 600_000,
    "chroma": 500_000,
    "wan": 200_000,         # Video: ~0.2M px/GB per frame (very hungry)
    "ltx": 300_000,         # Video: ~0.3M px/GB per frame
}

# Maximum safe resolution per VRAM tier
MAX_RESOLUTION = {
    # (vram_gb_min, vram_gb_max): {arch: (max_width, max_height)}
    (0, 8): {
        "sd15": (768, 768), "sdxl": (768, 768), "illustrious": (768, 768),
        "flux1dev": (512, 512), "flux2klein": (768, 768), "chroma": (512, 512),
        "wan": (512, 320), "ltx": (384, 256),
    },
    (8, 12): {
        "sd15": (1024, 1024), "sdxl": (1024, 1024), "illustrious": (1024, 1024),
        "flux1dev": (768, 768), "flux2klein": (1024, 1024), "chroma": (768, 768),
        "wan": (576, 320), "ltx": (512, 384),
    },
    (12, 16): {
        "sd15": (1536, 1536), "sdxl": (1024, 1024), "illustrious": (1024, 1024),
        "flux1dev": (1024, 1024), "flux2klein": (1024, 1024), "chroma": (1024, 1024),
        "wan": (832, 480), "ltx": (768, 512),
    },
    (16, 999): {
        "sd15": (2048, 2048), "sdxl": (1536, 1536), "illustrious": (1536, 1536),
        "flux1dev": (1024, 1024), "flux2klein": (1024, 1024), "chroma": (1024, 1024),
        "wan": (832, 480), "ltx": (768, 512),
    },
}


def get_server_vram(comfy_url):
    """Query ComfyUI for total VRAM in GB. Returns None if unreachable."""
    try:
        r = urllib.request.urlopen(f"{comfy_url.rstrip('/')}/system_stats", timeout=5)
        data = json.loads(r.read())
        return data["devices"][0]["vram_total"] / 1e9
    except Exception:
        return None


def estimate_vram(arch_key, width, height, num_frames=1):
    """Estimate peak VRAM usage in GB for a generation.

    Video models (WAN, LTX) process frames in temporal batches, not all at
    once. Peak VRAM is: model_base + resolution_overhead + temporal_overhead.
    The temporal overhead scales with sqrt(frames) not linearly.

    Returns (estimated_gb, breakdown_str).
    """
    base = ARCH_BASE_VRAM.get(arch_key, 5.0)
    ppg = PIXELS_PER_GB.get(arch_key, 500_000)
    pixels = width * height
    resolution_overhead = pixels / ppg

    # Video temporal overhead: scales roughly with sqrt(frames)
    if num_frames > 1 and arch_key in ("wan", "ltx"):
        import math
        temporal = resolution_overhead * math.sqrt(num_frames) * 0.3
        total = base + resolution_overhead + temporal
        breakdown = (f"model={base:.1f}GB + res={resolution_overhead:.1f}GB + "
                     f"temporal={temporal:.1f}GB ({width}x{height}x{num_frames}f)")
    else:
        total = base + resolution_overhead
        breakdown = f"model={base:.1f}GB + res={resolution_overhead:.1f}GB ({width}x{height})"

    return total, breakdown


def get_max_resolution(vram_gb, arch_key):
    """Get the maximum safe resolution for a given VRAM and architecture."""
    for (vmin, vmax), arch_limits in MAX_RESOLUTION.items():
        if vmin <= vram_gb < vmax:
            return arch_limits.get(arch_key, (1024, 1024))
    return (1024, 1024)


# ═══════════════════════════════════════════════════════════════════════
#  Workflow optimization
# ═══════════════════════════════════════════════════════════════════════

def optimize_workflow(workflow, vram_gb=None, comfy_url=None):
    """Analyze and optimize a workflow for the available hardware.

    Args:
        workflow: ComfyUI workflow dict
        vram_gb: Available VRAM in GB (auto-detected from comfy_url if None)
        comfy_url: ComfyUI server URL (for VRAM auto-detection)

    Returns:
        (optimized_workflow, warnings) where warnings is a list of strings
        describing what was changed and why.
    """
    if vram_gb is None and comfy_url:
        vram_gb = get_server_vram(comfy_url)
    if vram_gb is None:
        vram_gb = 16.0  # assume 16GB if unknown

    warnings = []
    patched = dict(workflow)

    # Detect architecture from workflow nodes
    arch_key = _detect_arch_from_workflow(workflow)

    # Detect resolution from workflow
    width, height, frames = _detect_resolution(workflow)

    if width and height:
        # Check if resolution exceeds safe limits
        max_w, max_h = get_max_resolution(vram_gb, arch_key)
        est_vram, breakdown = estimate_vram(arch_key, width, height, frames)

        if est_vram > vram_gb * 0.9:  # 90% threshold
            warnings.append(
                f"Estimated VRAM: {est_vram:.1f}GB > available {vram_gb:.1f}GB "
                f"({breakdown})")

            # Auto-cap resolution
            if width > max_w or height > max_h:
                new_w = min(width, max_w)
                new_h = min(height, max_h)
                _set_resolution(patched, new_w, new_h)
                warnings.append(
                    f"Resolution capped: {width}x{height} -> {new_w}x{new_h} "
                    f"(safe limit for {vram_gb:.0f}GB + {arch_key})")

        # Video-specific optimizations
        if frames > 1:
            if frames > 81 and vram_gb < 12:
                # Too many frames for low VRAM
                _set_frames(patched, 49)
                warnings.append(
                    f"Frames reduced: {frames} -> 49 "
                    f"(>81 frames needs 12GB+ VRAM)")

            # Enable tiled VAE for video on <16GB
            if vram_gb < 16 and arch_key == "wan":
                # Check if tiled VAE is already enabled
                has_tiled = any(
                    n.get("class_type") == "VAEDecodeTiled"
                    for n in workflow.values() if isinstance(n, dict))
                if not has_tiled:
                    warnings.append(
                        "Recommend: enable Tiled VAE for WAN video on <16GB")

    return patched, warnings


def _detect_arch_from_workflow(workflow):
    """Infer the architecture from model loader nodes in the workflow."""
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if ct in ("CheckpointLoaderSimple",):
            model = inputs.get("ckpt_name", "")
            from .model_detect import classify_ckpt_model
            return classify_ckpt_model(model)

        if ct in ("UNETLoader", "UnetLoaderGGUF"):
            model = inputs.get("unet_name", "")
            from .model_detect import classify_unet_model
            return classify_unet_model(model)

    return "unknown"


def _detect_resolution(workflow):
    """Extract width, height, and frame count from workflow nodes."""
    width = height = 0
    frames = 1

    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if ct == "EmptyLatentImage":
            width = inputs.get("width", 0)
            height = inputs.get("height", 0)

        # WAN video conditioning
        if ct in ("WanImageToVideo", "WanFirstLastFrameToVideo"):
            width = inputs.get("width", width)
            height = inputs.get("height", height)
            frames = inputs.get("length", 81)

        # LTX video
        if ct == "EmptyLTXVLatentVideo":
            width = inputs.get("width", width)
            height = inputs.get("height", height)
            frames = inputs.get("num_frames", 25)

    return width, height, frames


def _set_resolution(workflow, new_w, new_h):
    """Patch resolution in EmptyLatentImage and video conditioning nodes."""
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        if ct in ("EmptyLatentImage", "WanImageToVideo",
                  "WanFirstLastFrameToVideo", "EmptyLTXVLatentVideo"):
            if "width" in node.get("inputs", {}):
                node["inputs"]["width"] = new_w
            if "height" in node.get("inputs", {}):
                node["inputs"]["height"] = new_h


def _set_frames(workflow, new_frames):
    """Patch frame count in video conditioning nodes."""
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        if ct in ("WanImageToVideo", "WanFirstLastFrameToVideo"):
            if "length" in node.get("inputs", {}):
                node["inputs"]["length"] = new_frames
        if ct == "EmptyLTXVLatentVideo":
            if "num_frames" in node.get("inputs", {}):
                node["inputs"]["num_frames"] = new_frames
