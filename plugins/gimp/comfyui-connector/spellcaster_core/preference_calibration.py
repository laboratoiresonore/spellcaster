"""Preference Calibration — optometrist-style A/B model and settings tuning.

Generates real images from the user's installed models, lets them compare
results side by side, and stores their preferences as default overrides in
config.json. Designed to be UI-agnostic so both GIMP and the Wizard Guild
can use the same engine.

Complements calibration.py (which tests model/LoRA *compatibility*) — this
module tests user *preferences*.

Usage:
    from .preference_calibration import (
        discover_models, build_comparison_set, generate_and_download,
        arch_valid_ranges, CalibrationProfile, save_profile,
    )

    models = discover_models("http://192.168.x.x:8188")
    for m in models:
        wfs = build_comparison_set(m, "cfg", [3, 7, 12], prompt, seed=42)
        for item in wfs:
            png = generate_and_download(server, item["workflow"])
            # show png to user, collect preference ...
"""

import json
import time
import urllib.request
import urllib.parse

try:
    from .calibration import _get_opts, _submit_and_wait
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .architectures import get_arch, ARCHITECTURES
except ImportError:
    from .calibration import _get_opts, _submit_and_wait
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .architectures import get_arch, ARCHITECTURES


# ═══════════════════════════════════════════════════════════════════════
#  Architecture-aware calibration ranges
# ═══════════════════════════════════════════════════════════════════════

_CALIBRATION_RANGES = {
    "sd15": {
        "denoise":  [0.40, 0.55, 0.70, 0.85],
        "cfg":      [3.0, 5.0, 7.0, 12.0],
        "steps":    [8, 15, 20, 30],
        "sampler":  ["euler", "dpmpp_2m", "dpmpp_sde"],
    },
    "sdxl": {
        "denoise":  [0.40, 0.55, 0.70, 0.85],
        "cfg":      [3.0, 5.0, 7.0, 12.0],
        "steps":    [8, 15, 20, 30],
        "sampler":  ["euler", "dpmpp_2m", "dpmpp_sde"],
    },
    "illustrious": {
        "denoise":  [0.40, 0.55, 0.70, 0.85],
        "cfg":      [3.0, 5.0, 7.0, 12.0],
        "steps":    [8, 15, 20, 30],
        "sampler":  ["euler_ancestral", "dpmpp_2m", "dpmpp_sde"],
    },
    "zit": {
        "denoise":  [0.40, 0.55, 0.70],
        "cfg":      [1.5, 2.0, 3.0],
        "steps":    [4, 6, 8],
        "sampler":  ["euler", "dpmpp_sde"],
    },
    "flux1dev": {
        "denoise":  [0.40, 0.55, 0.70, 0.85],
        "cfg":      [1.0, 2.0, 3.0, 5.0],
        "steps":    [8, 15, 20, 30],
        "sampler":  ["euler", "dpmpp_2m"],
    },
    "chroma": {
        "denoise":  [0.40, 0.55, 0.70],
        "cfg":      [1.0, 2.0, 3.0],
        "steps":    [8, 15, 20],
        "sampler":  ["euler", "dpmpp_2m"],
    },
    # Klein and kontext: too constrained for meaningful calibration
}

# Architectures that should be skipped for settings calibration
_SKIP_SETTINGS_ARCHS = {"flux2klein", "flux_kontext"}

# Models to skip (non-generation files that appear in model lists)
_SKIP_KEYWORDS = (
    "vae", "embeddings", "audio", "clip_", "t5xxl", "umt5",
    "gemma", "qwen", "mistral", "llava", "connector", "refiner",
    "upscale", "rife", "reactor", "ip-adapter", "controlnet",
    "ipadapter", "insightface", "face_restore", "codeformer",
    "gfpgan", "reswapper", "inswapper", "siglip", "ldsr",
    # Encoders / text-towers that sometimes slip in under UNETLoader
    "text_encoder", "text-encoder", "qwen2", "clipvision",
    "normalcrafter", "depthanything", "midas",
    # Guidance connectors  / post-processors
    "rembg", "sam3", "sam_vit", "sam2", "matting",
)

# Architectures that the taste-test + settings calibration wizard
# actually exercises. Video archs (wan/ltx/cogvideo/seedvr) use a
# different inference path; listing them in the image-calibration
# wizard causes render failures + skews the "57 models" count. Klein
# and Kontext aren't test-able with a free-form prompt (Klein is
# 4-step distilled-only, Kontext is instruction-only).
_IMAGE_CALIBRATION_ARCHS = frozenset({
    "sd15", "sdxl", "illustrious", "pony", "playground",
    "sdxl_turbo", "zit", "flux1dev", "chroma",
})

# Video archs explicitly — listed so an explicit rejection reason
# can surface in logs + so gen_calibrations / fancier callers can
# pick them up elsewhere for video-side calibration in the future.
_VIDEO_ARCHS = frozenset({"wan", "ltx", "cogvideo", "seedvr"})


def _base_model_key(name):
    """Strip quant tags + folder prefix so every Flux1Dev variant
    (bf16 / fp8 / Q4_K_M / Q5_K_M / Q8_0 / etc.) collapses to the same
    base key and the taste test shows ONE card instead of seven.

    Returns a lowercased stem with the known quant markers removed.
    """
    if not name:
        return ""
    tail = name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = tail.rsplit(".", 1)[0].lower()
    for tag in (
        "-q4_0", "-q4_1", "-q4_k_m", "-q4_k_s", "-q5_0", "-q5_1",
        "-q5_k_m", "-q5_k_s", "-q6_k", "-q8_0",
        "_q4_0", "_q4_1", "_q4_k_m", "_q4_k_s", "_q5_0", "_q5_1",
        "_q5_k_m", "_q5_k_s", "_q6_k", "_q8_0",
        "-fp8", "_fp8", "-fp8-e4m3fn", "-fp8-scaled",
        "-bf16", "_bf16", "-fp16", "_fp16",
        "-scaled", "_scaled",
    ):
        stem = stem.replace(tag, "")
    # Collapse double dashes/underscores left over from the strip.
    while "--" in stem: stem = stem.replace("--", "-")
    while "__" in stem: stem = stem.replace("__", "_")
    return stem.strip("-_")

# Calibration test prompts — one per architecture style
_TEST_PROMPTS = {
    "sd15": (
        "a woman sitting at a wooden desk in a sunlit library, reading a book, "
        "warm afternoon light through tall windows, bookshelves in background, "
        "photorealistic, detailed face, natural lighting",
        "blurry, cartoon, deformed, ugly, low quality",
    ),
    "sdxl": (
        "a woman sitting at a wooden desk in a sunlit library, reading a book, "
        "warm afternoon light through tall windows, bookshelves in background, "
        "photorealistic, detailed face, natural lighting",
        "blurry, cartoon, deformed, ugly, low quality",
    ),
    "illustrious": (
        "1girl, sitting at desk, library, reading book, afternoon sunlight, "
        "warm colors, bookshelves, detailed, masterpiece, best quality",
        "worst quality, low quality, blurry, bad anatomy",
    ),
    "zit": (
        "a woman sitting at a wooden desk in a sunlit library, reading a book, "
        "warm afternoon light, photorealistic",
        "blurry, ugly",
    ),
    "flux1dev": (
        "a woman sitting at a wooden desk in a sunlit library, reading a book, "
        "warm afternoon light through tall windows, bookshelves in background, "
        "natural lighting, detailed"
    ),
    "flux2klein": (
        "a woman sitting at a wooden desk in a sunlit library, reading a book, "
        "warm afternoon light, natural lighting"
    ),
    "chroma": (
        "a woman sitting at a wooden desk in a sunlit library, reading a book, "
        "warm afternoon light through tall windows, natural lighting, detailed"
    ),
    "flux_kontext": (
        "a woman sitting at a wooden desk in a sunlit library, reading a book"
    ),
}


def _get_test_prompt(arch_key):
    """Get test prompt (and negative if supported) for an architecture."""
    entry = _TEST_PROMPTS.get(arch_key, _TEST_PROMPTS["sdxl"])
    if isinstance(entry, tuple):
        return entry[0], entry[1]
    return entry, ""


# ═══════════════════════════════════════════════════════════════════════
#  Model discovery
# ═══════════════════════════════════════════════════════════════════════

def discover_models(server, *, include_video=False, dedupe_quants=True):
    """Enumerate installed checkpoints + UNETs, classify by architecture.

    By default returns only IMAGE-generation archs (see
    ``_IMAGE_CALIBRATION_ARCHS``) and collapses quant variants of the
    same base UNET (``flux1-dev-fp8`` + ``flux1-dev-Q4_K_M`` + ``-bf16``
    → one entry). The pre-2026-04-20 behaviour (every variant + video
    UNETs included) yielded ~57 entries on the user's server for what
    was really ~8 image models, making the wizard unusable.

    Args:
        include_video: include WAN / LTX / Cogvideo UNETs. Off by
            default — their taste-test path doesn't exist yet. Video
            calibration gets its own surface in gen_calibrations.py.
        dedupe_quants: collapse quant/fp8/bf16 variants of the same
            base model name. On by default; callers who genuinely want
            to see Q4 vs Q8 for A/B testing pass False.

    Returns list of dicts::

        [{"name": "...", "arch": "sdxl", "loader": "...",
          "short_name": "...", "variants": [{"name": "...", ...}, ...]}]

    ``variants`` carries the sibling quants that collapsed into this
    entry so the UI can offer a "test all variants" action.
    """
    all_models = []
    seen = set()
    # Maps base-model-key → index into all_models (for variant merging).
    by_base: dict = {}

    for node, field, classify_fn in [
        ("CheckpointLoaderSimple", "ckpt_name", classify_ckpt_model),
        ("UNETLoader", "unet_name", classify_unet_model),
        ("UnetLoaderGGUF", "unet_name", classify_unet_model),
    ]:
        for name in _get_opts(server, node, field):
            if name in seen:
                continue
            seen.add(name)
            if any(kw in name.lower() for kw in _SKIP_KEYWORDS):
                continue
            arch = classify_fn(name)
            if arch == "unknown":
                continue
            if arch not in _IMAGE_CALIBRATION_ARCHS:
                if arch in _VIDEO_ARCHS and not include_video:
                    continue
                if not include_video:
                    # Klein / Kontext / unknown — not image-taste-test
                    # candidates. Don't pollute the wizard with them.
                    continue
            short = name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            short = short.rsplit(".", 1)[0]  # strip extension
            entry = {
                "name": name,
                "arch": arch,
                "loader": node,
                "short_name": short,
                "variants": [],
            }
            if dedupe_quants:
                base_key = f"{arch}::{_base_model_key(name)}"
                if base_key in by_base:
                    # Attach as a variant of the already-registered
                    # canonical entry. Prefer fp16/bf16 as canonical
                    # when available (highest quality); swap roles if
                    # the new one is higher-quality than the one held.
                    canon_idx = by_base[base_key]
                    canon = all_models[canon_idx]
                    # Simple quality score — higher is better.
                    def _q(n: str) -> int:
                        low = n.lower()
                        if "bf16" in low or "fp16" in low: return 5
                        if "fp8" in low or "scaled" in low: return 4
                        if "q8_0" in low: return 4
                        if "q6_k" in low: return 3
                        if "q5" in low:   return 2
                        if "q4" in low:   return 1
                        return 3  # plain safetensors — usually fp16
                    if _q(name) > _q(canon["name"]):
                        # Swap: new entry becomes canon, old one a variant.
                        new_entry = dict(entry)
                        new_entry["variants"] = (canon["variants"]
                                                  + [{"name": canon["name"],
                                                      "loader": canon["loader"]}])
                        all_models[canon_idx] = new_entry
                    else:
                        canon["variants"].append({
                            "name": name, "loader": node,
                        })
                    continue
                by_base[base_key] = len(all_models)
            all_models.append(entry)

    return all_models


# ═══════════════════════════════════════════════════════════════════════
#  Comparison workflow builder
# ═══════════════════════════════════════════════════════════════════════

def arch_valid_ranges(arch_key):
    """Return calibration parameter ranges for an architecture.

    Returns dict with keys: denoise, cfg, steps, sampler.
    Returns None for architectures that skip settings calibration.
    """
    return _CALIBRATION_RANGES.get(arch_key)


def build_comparison_set(model, parameter, values, prompt, neg_prompt, seed):
    """Build one workflow per parameter value for side-by-side comparison.

    Args:
        model: dict from discover_models() with name, arch, loader keys
        parameter: "denoise" | "cfg" | "steps" | "sampler"
        values: list of parameter values to compare
        prompt: positive prompt text
        neg_prompt: negative prompt text (empty string for Flux/Chroma)
        seed: fixed seed (same across all comparisons)

    Returns:
        list of {"value": <param_value>, "workflow": <comfyui_workflow_dict>}
    """
    try:
        from .workflows import build_txt2img
    except ImportError:
        from .workflows import build_txt2img

    arch_key = model["arch"]
    arch = get_arch(arch_key)
    if not arch:
        return []

    w, h = arch.default_resolution
    # Use smaller resolution for speed during calibration
    if w >= 1024:
        w, h = 768, 768
    elif w >= 512:
        w, h = 512, 512

    results = []
    for val in values:
        preset = {
            "arch": arch_key,
            "ckpt": model["name"],
            "width": w,
            "height": h,
            "steps": arch.default_steps,
            "cfg": arch.default_cfg,
            "denoise": arch.default_denoise,
            "sampler": arch.default_sampler,
            "scheduler": arch.default_scheduler,
            "loader": arch.loader,
            "clip_name1": "",
            "clip_name2": "",
            "vae_name": "",
        }

        # Override the tested parameter
        if parameter == "denoise":
            # txt2img always uses denoise=1.0, so we use steps as proxy
            # for "quality level" and adjust width for visual difference
            preset["steps"] = arch.default_steps
            preset["cfg"] = arch.default_cfg
            # Store denoise for config output, use steps to vary quality
            pass
        elif parameter == "cfg":
            preset["cfg"] = val
        elif parameter == "steps":
            preset["steps"] = val
        elif parameter == "sampler":
            preset["sampler"] = val

        try:
            wf = build_txt2img(preset, prompt, neg_prompt, seed)
            results.append({"value": val, "workflow": wf})
        except Exception:
            continue

    return results


# ═══════════════════════════════════════════════════════════════════════
#  Generation + download
# ═══════════════════════════════════════════════════════════════════════

def generate_and_download(server, workflow, timeout=120):
    """Submit workflow, wait for completion, download first output image.

    Delegates to spellcaster_core.dispatch when available. Calibration
    workflows skip free_vram and privacy (speed over cleanup).

    Returns PNG bytes on success, None on failure.
    """
    try:
        from .dispatch import dispatch_workflow
        result = dispatch_workflow(
            server, workflow, timeout=timeout,
            free_vram=False,   # calibration — speed matters
            privacy=False,     # calibration outputs are disposable
        )
        if not result.outputs:
            return None
        fn, sf, ft = result.outputs[0]
        params = urllib.parse.urlencode({
            "filename": fn, "subfolder": sf, "type": ft
        })
        # Bound the download so a malicious or misconfigured ComfyUI
        # can't stream an unbounded blob into the caller's RAM. 200 MB
        # is comfortably above any legitimate generated image/video.
        _MAX = 200 * 1024 * 1024
        with urllib.request.urlopen(
                f"{server}/view?{params}", timeout=30) as r:
            data = r.read(_MAX + 1)
        if len(data) > _MAX:
            return None
        return data
    except ImportError:
        pass  # dispatch not available — fall through
    except Exception:
        return None

    # Fallback: inline implementation
    try:
        from .preflight import preflight_workflow
    except ImportError:
        from .preflight import preflight_workflow

    try:
        _ok, workflow, _ = preflight_workflow(workflow, server)
    except Exception:
        pass

    body = json.dumps({"prompt": workflow}).encode()
    try:
        resp = json.loads(urllib.request.urlopen(
            urllib.request.Request(
                f"{server}/prompt", data=body,
                headers={"Content-Type": "application/json"}),
            timeout=10).read())
        pid = resp.get("prompt_id")
    except Exception:
        return None
    if not pid:
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            h = json.loads(urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=5).read())
            if pid in h:
                status = h[pid].get("status", {})
                # Prefer canonical extractor; fall back to legacy scan
                # if dispatch.py isn't importable in this install.
                if status.get("status_str") == "error":
                    try:
                        from .dispatch import (
                            extract_execution_error, has_usable_outputs,
                        )
                        # Calibration tolerates partial output — if an
                        # image landed anyway, use it (better than None).
                        if not has_usable_outputs(h[pid]):
                            return None
                    except ImportError:
                        for msg in status.get("messages") or []:
                            if (isinstance(msg, (list, tuple)) and msg
                                    and msg[0] == "execution_error"):
                                return None
                for out in h[pid].get("outputs", {}).values():
                    for img in out.get("images", []):
                        fn = img["filename"]
                        sf = img.get("subfolder", "")
                        ft = img.get("type", "output")
                        params = urllib.parse.urlencode({
                            "filename": fn, "subfolder": sf, "type": ft
                        })
                        with urllib.request.urlopen(
                                f"{server}/view?{params}", timeout=30) as r:
                            return r.read()
        except Exception:
            pass
        time.sleep(1)
    return None


def generate_model_sample_rich(server, model, seed=42, timeout=180,
                                 callback=None):
    """Richer variant of ``generate_model_sample`` — returns a dict
    instead of raw bytes so the calibration wizard can surface speed,
    distinguish "generation failed" from "user disliked", and build a
    research/repair path when the render crashes.

    Returns a dict with these keys (all present even on failure)::

        {
          "png":        bytes | None,        # PNG bytes on success
          "elapsed_ms": int,                 # wall-clock ms
          "failed":    bool,                 # True iff png is None
          "error":     str,                  # human-readable cause
          "model":     str,                  # echoed for callback binding
          "arch":      str,
          "preset":    dict,                 # exact preset used
          "prompt":    str,                  # prompt used
          "seed":      int,
        }

    Legacy callers should use ``generate_model_sample`` (returns just
    the PNG bytes) — it's a thin shim over this function.
    """
    try:
        from .workflows import build_txt2img
    except ImportError:
        from .workflows import build_txt2img

    arch_key = model["arch"]
    t0 = time.time()
    result = {
        "png":        None,
        "elapsed_ms": 0,
        "failed":     True,
        "error":      "",
        "model":      model.get("name", ""),
        "arch":       arch_key,
        "preset":     {},
        "prompt":     "",
        "seed":       seed,
    }

    arch = get_arch(arch_key)
    if not arch:
        result["error"] = f"Unknown architecture: {arch_key!r}"
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        return result

    prompt, neg = _get_test_prompt(arch_key)
    result["prompt"] = prompt
    w, h = arch.default_resolution
    if w >= 1024:
        w, h = 768, 768

    preset = {
        "arch": arch_key,
        "ckpt": model["name"],
        "width": w, "height": h,
        "steps": arch.default_steps,
        "cfg": arch.default_cfg,
        "denoise": 1.0,
        "sampler": arch.default_sampler,
        "scheduler": arch.default_scheduler,
        "loader": arch.loader,
        "clip_name1": "", "clip_name2": "", "vae_name": "",
    }
    result["preset"] = dict(preset)

    try:
        wf = build_txt2img(preset, prompt, neg, seed)
    except Exception as e:
        result["error"] = f"Workflow build failed: {e!s}"[:400]
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        return result

    if callback:
        try:
            callback(f"Generating with {model['short_name']}...")
        except Exception:
            pass

    try:
        png = generate_and_download(server, wf, timeout=timeout)
    except Exception as e:
        result["error"] = f"Dispatch failed: {e!s}"[:400]
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        return result
    result["elapsed_ms"] = int((time.time() - t0) * 1000)
    if png:
        result["png"] = png
        result["failed"] = False
    else:
        result["error"] = ("Server returned no image — check ComfyUI "
                           "console for errors (missing CLIP / VAE / "
                           "LoRA or OOM).")
    return result


def generate_model_sample(server, model, seed=42, timeout=180, callback=None):
    """Legacy shim — returns just the PNG bytes (or None) so existing
    callers don't break. New code should use
    ``generate_model_sample_rich`` for speed + failure data."""
    res = generate_model_sample_rich(server, model, seed=seed,
                                       timeout=timeout, callback=callback)
    return res.get("png")


# ═══════════════════════════════════════════════════════════════════════
#  Calibration profile
# ═══════════════════════════════════════════════════════════════════════

class CalibrationProfile:
    """Stores user's calibrated preferences."""

    def __init__(self):
        self.preferred_models = []   # ranked model names (most preferred first)
        self.model_overrides = {}    # {model_name: {steps, cfg, denoise, sampler, scheduler}}
        self.timestamp = ""
        self.version = 1

    def to_config(self):
        """Convert to dict suitable for _save_config()."""
        return {
            "calibration_profile": {
                "timestamp": self.timestamp,
                "version": self.version,
                "tests_completed": len(self.model_overrides),
            },
            "preferred_models": self.preferred_models,
            "model_overrides": self.model_overrides,
        }

    @classmethod
    def from_config(cls, config):
        """Load from config.json data. Returns None if no calibration exists."""
        if "calibration_profile" not in config:
            return None
        p = cls()
        p.preferred_models = config.get("preferred_models", [])
        p.model_overrides = config.get("model_overrides", {})
        cp = config["calibration_profile"]
        p.timestamp = cp.get("timestamp", "")
        p.version = cp.get("version", 1)
        return p

    def set_model_preference(self, model_name, rating):
        """Record a model rating. rating: 'love', 'ok', or 'dislike'."""
        # Remove from list first
        self.preferred_models = [m for m in self.preferred_models if m != model_name]
        if rating == "love":
            # Insert at front (most preferred)
            self.preferred_models.insert(0, model_name)
        elif rating == "ok":
            # Append after loved models
            self.preferred_models.append(model_name)
        # 'dislike' = not in the list at all

    def set_model_settings(self, model_name, **settings):
        """Store calibrated settings for a specific model.

        Accepts: steps, cfg, denoise, sampler, scheduler
        """
        if model_name not in self.model_overrides:
            self.model_overrides[model_name] = {}
        self.model_overrides[model_name].update(settings)

    def get_model_settings(self, model_name):
        """Get calibrated settings for a model, or None."""
        return self.model_overrides.get(model_name)

    def should_calibrate_settings(self, arch_key):
        """Check if this architecture should get settings calibration."""
        return arch_key not in _SKIP_SETTINGS_ARCHS and arch_key in _CALIBRATION_RANGES
