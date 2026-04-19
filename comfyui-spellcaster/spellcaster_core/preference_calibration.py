"""Preference Calibration — optometrist-style A/B model and settings tuning.

Generates real images from the user's installed models, lets them compare
results side by side, and stores their preferences as default overrides in
config.json. Designed to be UI-agnostic so both GIMP and the Wizard Guild
can use the same engine.

Complements calibration.py (which tests model/LoRA *compatibility*) — this
module tests user *preferences*.

Usage:
    from spellcaster_core.preference_calibration import (
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
    from spellcaster_core.calibration import _get_opts, _submit_and_wait
    from spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model
    from spellcaster_core.architectures import get_arch, ARCHITECTURES


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
)

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

def discover_models(server):
    """Enumerate installed checkpoints + UNETs, classify by architecture.

    Returns list of dicts:
        [{"name": "SDXL/model.safetensors", "arch": "sdxl",
          "loader": "CheckpointLoaderSimple", "short_name": "model"}, ...]
    """
    all_models = []
    seen = set()

    for node, field, classify_fn in [
        ("CheckpointLoaderSimple", "ckpt_name", classify_ckpt_model),
        ("UNETLoader", "unet_name", classify_unet_model),
        ("UnetLoaderGGUF", "unet_name", classify_unet_model),
    ]:
        for name in _get_opts(server, node, field):
            if name in seen:
                continue
            if any(kw in name.lower() for kw in _SKIP_KEYWORDS):
                continue
            arch = classify_fn(name)
            if arch == "unknown":
                continue
            seen.add(name)
            short = name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            short = short.rsplit(".", 1)[0]  # strip extension
            all_models.append({
                "name": name,
                "arch": arch,
                "loader": node,
                "short_name": short,
            })

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
        from spellcaster_core.workflows import build_txt2img

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
        with urllib.request.urlopen(
                f"{server}/view?{params}", timeout=30) as r:
            return r.read()
    except ImportError:
        pass  # dispatch not available — fall through
    except Exception:
        return None

    # Fallback: inline implementation
    try:
        from .preflight import preflight_workflow
    except ImportError:
        from spellcaster_core.preflight import preflight_workflow

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
                for msg in status.get("messages", []):
                    if msg[0] == "execution_error":
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


def generate_model_sample(server, model, seed=42, timeout=180, callback=None):
    """Generate a single sample image for one model.

    Uses architecture-appropriate prompt and parameters.
    Returns PNG bytes or None.
    """
    try:
        from .workflows import build_txt2img
    except ImportError:
        from spellcaster_core.workflows import build_txt2img

    arch_key = model["arch"]
    arch = get_arch(arch_key)
    if not arch:
        return None

    prompt, neg = _get_test_prompt(arch_key)
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

    try:
        wf = build_txt2img(preset, prompt, neg, seed)
    except Exception:
        return None

    if callback:
        callback(f"Generating with {model['short_name']}...")

    return generate_and_download(server, wf, timeout=timeout)


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
