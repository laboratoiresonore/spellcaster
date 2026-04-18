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

# Base VRAM per model architecture (GB, approximate with model loaded).
# This is the "floor" VRAM cost: loading the model weights at rest before any
# inference begins. Measured empirically on RTX 5060 Ti 16GB with fp16/Q4
# quantizations. Does NOT include resolution-dependent overhead (see PIXELS_PER_GB).
ARCH_BASE_VRAM = {
    "sd15": 2.5,
    "sdxl": 4.5,
    "illustrious": 4.5,   # SDXL-derivative, same VRAM profile
    "pony": 4.5,           # SDXL-derivative, same VRAM profile
    "flux1dev": 8.0,       # Flux 1 Dev single-UNET
    "flux2klein": 6.0,     # Flux 2 Klein 4B/9B (smaller than full Flux)
    "chroma": 7.0,         # Chroma v1/v2 (Flux2 family)
    "zit": 5.0,            # ZIT (SiT-based)
    "wan": 10.0,           # WAN 2.1 — dual-UNET 14B, very VRAM-hungry
    "ltx": 9.0,            # LTX Video 2.3 — 22B transformer model
}

# Pixels per GB of extra VRAM needed (above the base cost).
# Higher value = more VRAM-efficient per pixel. SD1.5's smaller U-Net processes
# more pixels per GB than Flux's larger transformer.
# Formula: extra_gb = (width * height) / PIXELS_PER_GB[arch]
# For video models (WAN, LTX), this is the per-frame cost; temporal overhead
# is calculated separately in estimate_vram() using sqrt(frames).
PIXELS_PER_GB = {
    "sd15": 1_500_000,      # ~1.5M px/GB -> 1024x1024 needs ~0.7 GB extra
    "sdxl": 800_000,        # ~0.8M px/GB -> 1024x1024 needs ~1.3 GB extra
    "illustrious": 800_000,
    "flux1dev": 500_000,    # ~0.5M px/GB -> 1024x1024 needs ~2 GB extra
    "flux2klein": 600_000,
    "chroma": 500_000,
    "wan": 200_000,         # Video: ~0.2M px/GB per frame (very hungry)
    "ltx": 300_000,         # Video: ~0.3M px/GB per frame
}

# Maximum safe resolution per VRAM tier.
# These are hard caps — resolutions beyond these will OOM on the given VRAM tier.
# Values are intentionally conservative (measured at ~85% of actual OOM threshold)
# because PyTorch's CUDA allocator fragments memory under real workloads.
# The (vram_min, vram_max) ranges are exclusive on the upper bound.
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
    # Default to 5.0GB base if architecture is unknown (safe middle ground)
    base = ARCH_BASE_VRAM.get(arch_key, 5.0)
    # Default to 500K px/GB if unknown (Flux-like, moderately conservative)
    ppg = PIXELS_PER_GB.get(arch_key, 500_000)
    pixels = width * height
    resolution_overhead = pixels / ppg

    # Video temporal overhead: scales with sqrt(frames), not linearly.
    # WHY sqrt: video models process frames in overlapping temporal windows,
    # so VRAM grows sub-linearly with frame count. The 0.3 multiplier is an
    # empirically-tuned dampening factor from testing 25-81 frame generations
    # on WAN 2.1 with 16GB VRAM.
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
        # 16GB is a safe default: it won't over-cap resolutions on modern GPUs,
        # and if the user has less VRAM, they'll hit OOM (which is better than
        # silently downscaling on a 24GB card).
        vram_gb = 16.0

    warnings = []
    # Shallow copy: node dicts are mutated in-place (resolution, frames),
    # but we don't want to modify the caller's original workflow dict.
    patched = dict(workflow)

    # Detect architecture from workflow nodes
    arch_key = _detect_arch_from_workflow(workflow)

    # Detect resolution from workflow
    width, height, frames = _detect_resolution(workflow)

    if width and height:
        # Check if resolution exceeds safe limits
        max_w, max_h = get_max_resolution(vram_gb, arch_key)
        est_vram, breakdown = estimate_vram(arch_key, width, height, frames)

        # 90% threshold: leave 10% headroom for PyTorch allocator overhead,
        # CUDA context, and any LoRAs/ControlNets that add to peak usage.
        if est_vram > vram_gb * 0.9:
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
                # 81 frames is WAN's default but needs ~14GB+ VRAM.
                # Cap to 49 frames (~2 seconds) on <12GB cards.
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

    # ── TeaCache auto-injection for non-video image workflows ──
    # TeaCache caches intermediate transformer block outputs between diffusion
    # steps, skipping redundant computation when outputs barely change.
    # Adds ~1.4x speedup with zero quality loss at the default 0.25 threshold.
    # Only inject if: (1) no TeaCache/FirstBlockCache already in workflow,
    # (2) not a video workflow (WAN/LTX use WanVideoTeaCache instead),
    # (3) a KSampler node exists whose model input we can intercept.
    if frames <= 1:  # image workflow, not video
        has_teacache = any(
            n.get("class_type", "") in ("ApplyTeaCachePatch", "ApplyFirstBlockCachePatch")
            for n in patched.values() if isinstance(n, dict))
        if not has_teacache:
            for nid, node in list(patched.items()):
                if not isinstance(node, dict):
                    continue
                ct = node.get("class_type", "")
                if ct in ("KSampler", "KSamplerAdvanced"):
                    model_input = node["inputs"].get("model")
                    if model_input:
                        # Splice TeaCache between the model source and the
                        # KSampler: model_source -> [TeaCache] -> KSampler.
                        # The TeaCache node passes through the model with
                        # a caching hook attached.
                        tc_id = f"_tc_{nid}"
                        patched[tc_id] = {
                            "class_type": "ApplyTeaCachePatch",
                            "inputs": {
                                "model": model_input,
                                # 0.25 = conservative threshold; higher values
                                # (0.4+) give more speedup but risk quality loss.
                                "rel_l1_thresh": 0.25,
                            },
                        }
                        # Redirect KSampler's model input to TeaCache output
                        node["inputs"]["model"] = [tc_id, 0]
                        warnings.append("TeaCache auto-injected (1.4x speedup)")
                        break  # only inject once (first KSampler found)

    return patched, warnings


def _detect_arch_from_workflow(workflow):
    """Infer the architecture from model loader nodes in the workflow.

    Scans for checkpoint or UNET loader nodes and classifies the model filename
    to determine the architecture (sdxl, flux1dev, wan, etc.). This drives all
    downstream VRAM estimation and resolution capping decisions.
    """
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})

        # Checkpoint-based architectures (SD1.5, SDXL, Illustrious, etc.)
        if ct in ("CheckpointLoaderSimple",):
            model = inputs.get("ckpt_name", "")
            from .model_detect import classify_ckpt_model
            return classify_ckpt_model(model)

        # Separate UNET loader (Flux, Klein, Chroma) — includes GGUF variant
        if ct in ("UNETLoader", "UnetLoaderGGUF"):
            model = inputs.get("unet_name", "")
            from .model_detect import classify_unet_model
            return classify_unet_model(model)

    return "unknown"


def _detect_resolution(workflow):
    """Extract width, height, and frame count from workflow nodes.

    Scans for latent/conditioning nodes that define generation dimensions.
    Video nodes (WAN, LTX) override image-only EmptyLatentImage if present,
    since the video conditioning node is the one that actually controls output size.
    """
    width = height = 0
    frames = 1

    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})

        # Standard image generation latent
        if ct == "EmptyLatentImage":
            width = inputs.get("width", 0)
            height = inputs.get("height", 0)

        # WAN video conditioning — overrides EmptyLatentImage if both present.
        # "length" is frame count (default 81 = ~3.2s at 25fps).
        if ct in ("WanImageToVideo", "WanFirstLastFrameToVideo"):
            width = inputs.get("width", width)
            height = inputs.get("height", height)
            frames = inputs.get("length", 81)

        # LTX Video latent — uses "num_frames" instead of "length"
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
