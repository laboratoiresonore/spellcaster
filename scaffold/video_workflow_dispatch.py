"""R126: Native ComfyUI routing for Wan / LTX video presets.

WanGP is a Gradio app we can no longer rely on reaching — users run
ComfyUI with all the Wan 2.2 / LTX-2 nodes already installed, and
spellcaster_core/workflows.py ships a full `build_wan_video()` builder
that outputs a ready-to-submit ComfyUI workflow dict. This module
wires the two together: given a WANGP_PRESETS key it probes ComfyUI
for the concrete model filenames, turns the preset into the `preset`
dict that build_wan_video expects, and hands back a workflow ready
for ComfyUIRunner.run_raw.

Design constraints:
- This lives in scaffold/, not spellcaster_core/, because it's pure
  Guild-side plumbing (never imported by the GIMP plugin).
- Model lists are probed once per ComfyUI URL and cached for 5 min —
  /object_info on a loaded ComfyUI is ~500KB so repeat probes hurt.
- Fuzzy match against model filenames: WANGP_PRESETS only declares a
  `model_hint` string; the user's actual filenames vary (NSFW variants,
  quantization choices, custom names). Match tokens, not substrings.
- Never raise from the resolver path. Return None + log — the caller
  falls back to WanGP or surfaces "unsupported preset".
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("spellcaster.video_dispatch")

# ── Model probe ──────────────────────────────────────────────────────

_MODEL_CACHE: Dict[str, Tuple[float, dict]] = {}
_CACHE_TTL_S = 300.0


def probe_comfyui_models(base_url: str, *, force: bool = False) -> dict:
    """Return {'unet_gguf': [...], 'unet': [...], 'clip': [...],
    'clip_gguf': [...], 'vae': [...]} for the given ComfyUI server.

    Cached 5 min. Empty lists on probe failure — caller handles the
    emptiness, not this function.
    """
    now = time.time()
    cached = _MODEL_CACHE.get(base_url)
    if cached and not force and (now - cached[0]) < _CACHE_TTL_S:
        return cached[1]
    out: Dict[str, List[str]] = {
        "unet_gguf": [], "unet": [],
        "clip_gguf": [], "clip": [],
        "vae": [],
    }
    queries = [
        ("UnetLoaderGGUF",      "unet_name",  "unet_gguf"),
        ("UNETLoader",          "unet_name",  "unet"),
        ("CLIPLoaderGGUF",      "clip_name",  "clip_gguf"),
        ("CLIPLoader",          "clip_name",  "clip"),
        ("VAELoader",           "vae_name",   "vae"),
    ]
    for node_class, input_key, out_key in queries:
        try:
            url = f"{base_url.rstrip('/')}/object_info/{node_class}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                d = json.loads(resp.read())
            info = d.get(node_class) or {}
            inputs = ((info.get("input") or {}).get("required") or {})
            field = inputs.get(input_key)
            if field and isinstance(field, list) and isinstance(field[0], list):
                out[out_key] = list(field[0])
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            log.debug("probe %s failed: %s", node_class, e)
        except Exception as e:  # noqa: BLE001 — never raise out of probe
            log.debug("probe %s unexpected: %s", node_class, e)
    _MODEL_CACHE[base_url] = (now, out)
    return out


# ── Fuzzy match ──────────────────────────────────────────────────────

def _tokens(s: str) -> set[str]:
    """Lowercase + split on non-alphanumeric. Used for loose matching —
    'wan2.2-i2v-14b-lightning' → {'wan','2','2','i','v','14','b','lightning'}."""
    import re
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t}


def _score(candidate: str, must_have: set[str],
            nice_to_have: set[str] | None = None,
            penalize: set[str] | None = None) -> int:
    """Score a candidate filename against required / bonus / penalty
    token sets. Returns a score ≥ 0; must_have tokens missing → score 0
    (disqualified). Higher is better."""
    ctok = _tokens(candidate)
    # All required tokens must be present
    if not must_have.issubset(ctok):
        return 0
    score = 100 + len(must_have) * 10
    if nice_to_have:
        score += sum(5 for t in nice_to_have if t in ctok)
    if penalize:
        score -= sum(20 for t in penalize if t in ctok)
    # Prefer shorter filenames (less random cruft)
    score -= len(candidate) // 20
    return max(0, score)


def _pick(candidates: List[str], must: set[str],
           nice: set[str] | None = None,
           bad: set[str] | None = None) -> Optional[str]:
    if not candidates:
        return None
    scored = [(c, _score(c, must, nice, bad)) for c in candidates]
    scored = [s for s in scored if s[1] > 0]
    if not scored:
        return None
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


# ── Preset resolver ─────────────────────────────────────────────────

# Map WANGP_PRESETS keys to a (must, nice, bad) token spec for the
# HIGH-noise (or single) model. The LOW-noise model mirrors the HIGH
# with the "high" / "low" token swapped inside _resolve_wan().
_WAN_PRESET_HINTS: Dict[str, Dict[str, Any]] = {
    "wan22_i2v_lightning": {
        "task": "i2v", "family": "wan22",
        "high_must": {"wan2", "2", "i2v", "high"},
        "high_nice": {"14b", "lightning", "q4"},
        "high_bad":  {"t2v"},
        "low_must":  {"wan2", "2", "i2v", "low"},
        "low_nice":  {"14b", "lightning", "q4"},
        "low_bad":   {"t2v"},
    },
    "wan22_i2v_hq": {
        "task": "i2v", "family": "wan22",
        "high_must": {"wan2", "2", "i2v", "high"},
        "high_nice": {"14b", "q6", "q8", "fp16", "hq"},
        "high_bad":  {"t2v", "lightning"},
        "low_must":  {"wan2", "2", "i2v", "low"},
        "low_nice":  {"14b", "q6", "q8", "fp16", "hq"},
        "low_bad":   {"t2v", "lightning"},
    },
    "wan22_t2v": {
        "task": "t2v", "family": "wan22",
        "high_must": {"wan2", "2", "t2v", "high"},
        "high_nice": {"a14b", "14b", "q4", "q6"},
        "high_bad":  {"i2v"},
        "low_must":  {"wan2", "2", "t2v", "low"},
        "low_nice":  {"a14b", "14b", "q6", "q8"},
        "low_bad":   {"i2v"},
    },
}


def resolve_wan_preset(preset_key: str, models: dict) -> Optional[dict]:
    """Build a build_wan_video-compatible preset dict from probed model
    lists. Returns None if we can't find all required models.

    models: as returned by probe_comfyui_models().
    """
    hint = _WAN_PRESET_HINTS.get(preset_key)
    if not hint:
        return None

    unet_pool = models.get("unet_gguf", []) + models.get("unet", [])
    high = _pick(unet_pool, hint["high_must"], hint.get("high_nice"),
                  hint.get("high_bad"))
    low  = _pick(unet_pool, hint["low_must"],  hint.get("low_nice"),
                  hint.get("low_bad"))
    if not (high and low):
        log.info("resolve_wan_preset(%s): no matching high/low models "
                 "(high=%s low=%s in pool of %d)",
                 preset_key, high, low, len(unet_pool))
        return None

    # CLIP — Wan uses UMT5 family. Prefer GGUF Q8 for quality,
    # safetensors fp8 for speed. Guild defaults to quality.
    clip_pool = models.get("clip_gguf", []) + models.get("clip", [])
    clip = (_pick(clip_pool, {"umt5"}, {"q8", "xxl", "encoder"})
            or _pick(clip_pool, {"umt5"}, {"fp8", "xxl", "scaled"})
            or _pick(clip_pool, {"umt5"}))
    if not clip:
        log.info("resolve_wan_preset(%s): no UMT5 clip found", preset_key)
        return None

    # VAE — wan2.2 or wan2.1 VAE both work for Wan 2.2 models.
    vae_pool = models.get("vae", [])
    vae = (_pick(vae_pool, {"wan2", "2"}, {"vae"})
           or _pick(vae_pool, {"wan"}, {"vae", "2", "1"})
           or _pick(vae_pool, {"wan"}))
    if not vae:
        log.info("resolve_wan_preset(%s): no Wan VAE found", preset_key)
        return None

    # Default sampler tuning per preset. `shift` is the Wan timestep
    # remap; lightning keeps it short (fewer steps), HQ goes longer.
    if preset_key == "wan22_i2v_lightning":
        tuning = {"steps": 6, "cfg": 1.0, "shift": 5.0, "second_step": 2}
    elif preset_key == "wan22_i2v_hq":
        tuning = {"steps": 25, "cfg": 5.0, "shift": 5.0, "second_step": 12}
    elif preset_key == "wan22_t2v":
        tuning = {"steps": 20, "cfg": 5.0, "shift": 5.0, "second_step": 10}
    else:
        tuning = {"steps": 20, "cfg": 5.0, "shift": 5.0, "second_step": 10}

    return {
        "high_model": high,
        "low_model":  low,
        "clip":       clip,
        "vae":        vae,
        "clip_is_gguf": clip.lower().endswith(".gguf"),
        **tuning,
    }


# ── Workflow builder ─────────────────────────────────────────────────

def build_native_workflow(preset_key: str, *, prompt: str,
                           negative: str = "", seed: int = 0,
                           image_filename: Optional[str] = None,
                           comfyui_base_url: str,
                           width: Optional[int] = None,
                           height: Optional[int] = None,
                           length: Optional[int] = None,
                           fps: Optional[int] = None,
                           turbo: bool = True) -> Tuple[Optional[dict], Optional[str]]:
    """Build a ComfyUI workflow dict for `preset_key`.

    Returns (workflow, error). On success workflow is a dict suitable
    for ComfyUIRunner.run_raw; error is None. On failure workflow is
    None and error is a short user-facing message.

    `image_filename` must be the basename of a file already uploaded
    to ComfyUI's input/ dir (uploaded by the caller before submitting).
    T2V presets pass None.
    """
    # WANGP_PRESETS lives in the scaffold package — import locally to
    # avoid a circular import at module load.
    try:
        from scaffold.wangp_runner import WANGP_PRESETS  # type: ignore
    except ImportError:
        return None, "WANGP_PRESETS unavailable"
    spec = WANGP_PRESETS.get(preset_key)
    if not spec:
        return None, f"unknown preset {preset_key!r}"

    # Default geometry from the preset.
    defaults = spec.get("defaults") or {}
    res = defaults.get("resolution", "832x480")
    try:
        w_default, h_default = (int(x) for x in res.split("x"))
    except Exception:
        w_default, h_default = 832, 480
    width = width or w_default
    height = height or h_default
    length = length or defaults.get("frames", 81)
    fps = fps or defaults.get("fps", 16)

    # Only the wan22_* family routes through build_wan_video today.
    family = (spec.get("family") or "").lower()
    if family != "wan":
        return None, (f"native routing for family={family!r} not yet "
                      "implemented — ComfyUI support for this preset "
                      "needs a dedicated workflow builder.")

    # Probe models fresh (cached internally).
    models = probe_comfyui_models(comfyui_base_url)
    preset_dict = resolve_wan_preset(preset_key, models)
    if not preset_dict:
        return None, (f"couldn't locate Wan models on ComfyUI for "
                      f"{preset_key!r}. Install Wan 2.2 14B GGUFs + "
                      "a UMT5 CLIP + wan2.2_vae under ComfyUI/models/.")

    # i2v needs a reference image; t2v uses the first generated frame.
    task = (spec.get("task") or "").lower()
    if task in ("i2v", "move_i2v") and not image_filename:
        return None, "this preset needs a reference image (i2v)"

    # Add spellcaster_core to sys.path for the workflow builder import.
    # The Guild ships `comfyui-spellcaster/spellcaster_core/` as the
    # canonical source — same path the auto-updater downloads to.
    _ensure_spellcaster_core_on_path()
    try:
        from spellcaster_core.workflows import build_wan_video  # type: ignore
    except ImportError as e:
        return None, f"spellcaster_core.workflows not importable: {e}"

    # t2v uses a custom workflow (no WanImageToVideo, no CLIPVision —
    # just text conditioning + EmptyHunyuanLatentVideo). Build inline
    # since spellcaster_core's build_wan_video is i2v-only.
    if task == "t2v":
        try:
            workflow = _build_wan_t2v_workflow(
                preset=preset_dict, prompt=prompt, negative=negative,
                seed=seed, width=width, height=height, length=length,
                fps=fps, turbo=turbo,
            )
        except Exception as e:  # noqa: BLE001
            return None, f"_build_wan_t2v_workflow raised: {e}"
        return workflow, None

    try:
        workflow = build_wan_video(
            image_filename=image_filename,
            preset=preset_dict,
            prompt_text=prompt,
            negative_text=negative,
            seed=seed,
            width=width, height=height, length=length,
            turbo=turbo, fps=fps,
            face_swap=False,          # editor-controlled, default off
            interpolate=False,        # skip RIFE for the first cut
            rtx_scale=1.0,            # no upscale by default
        )
    except Exception as e:  # noqa: BLE001
        return None, f"build_wan_video raised: {e}"
    if not isinstance(workflow, dict) or not workflow:
        return None, "build_wan_video returned empty workflow"
    return workflow, None


# ── Native t2v workflow (no WanImageToVideo) ────────────────────────

def _build_wan_t2v_workflow(*, preset: dict, prompt: str, negative: str,
                              seed: int, width: int, height: int,
                              length: int, fps: int, turbo: bool) -> dict:
    """Wan 2.2 text-to-video workflow.

    Differs from build_wan_video in that it:
      - Drops LoadImage / ImageScale / CLIPVision — no ref frame.
      - Uses EmptyHunyuanLatentVideo as the starting latent (Wan 2.2
        shares Hunyuan's 16-channel video latent shape, so that node's
        output slots into the Wan KSamplerAdvanced chain unchanged).
      - Skips the WanImageToVideo conditioning wrap — positive /
        negative CONDITIONING feed the samplers directly.

    Returned workflow is the same two-pass high/low KSampler structure
    as the i2v path, so the render-downloader in video_bridge doesn't
    need to know which kind it got back.
    """
    high_model = preset["high_model"]
    low_model = preset["low_model"]
    clip_name = preset["clip"]
    vae_name = preset["vae"]
    steps = preset.get("steps", 20)
    cfg = preset.get("cfg", 5.0)
    shift = preset.get("shift", 5.0)
    second_step = preset.get("second_step", 10)

    if turbo:
        if not (2 <= steps <= 10):
            steps = 6
        if not (1 <= second_step < steps):
            second_step = min(3, steps - 1)

    is_gguf_clip = preset.get("clip_is_gguf", clip_name.lower().endswith(".gguf"))
    is_gguf_high = high_model.lower().endswith(".gguf")
    is_gguf_low = low_model.lower().endswith(".gguf")

    wf: Dict[str, Any] = {}

    # 1. CLIP loader
    if is_gguf_clip:
        wf["1"] = {"class_type": "CLIPLoaderGGUF",
                   "inputs": {"clip_name": clip_name, "type": "wan"}}
    else:
        wf["1"] = {"class_type": "CLIPLoader",
                   "inputs": {"clip_name": clip_name, "type": "wan"}}

    # 2-3. Unet loaders (high + low)
    wf["2"] = {"class_type": "UnetLoaderGGUF" if is_gguf_high else "UNETLoader",
               "inputs": ({"unet_name": high_model}
                            if is_gguf_high else
                            {"unet_name": high_model, "weight_dtype": "default"})}
    wf["3"] = {"class_type": "UnetLoaderGGUF" if is_gguf_low else "UNETLoader",
               "inputs": ({"unet_name": low_model}
                            if is_gguf_low else
                            {"unet_name": low_model, "weight_dtype": "default"})}

    # 4. VAE loader
    wf["4"] = {"class_type": "VAELoader",
               "inputs": {"vae_name": vae_name}}

    # 5-6. Prompt encoding
    wf["5"] = {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["1", 0], "text": prompt}}
    wf["6"] = {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["1", 0], "text": negative or ""}}

    # 7. Empty latent video. Hunyuan's empty-latent node works for
    # Wan 2.2 because both families share the 16-channel (B,16,T,H,W)
    # latent layout. Frame count must be (length-1)/4*4+1 aligned.
    wf["7"] = {"class_type": "EmptyHunyuanLatentVideo",
               "inputs": {"width": width, "height": height,
                            "length": length, "batch_size": 1}}

    # 8-9. ModelSamplingSD3 (timestep shift)
    wf["8"] = {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["2", 0], "shift": shift}}
    wf["9"] = {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["3", 0], "shift": shift}}

    # 10. KSamplerAdvanced pass 1 (high)
    wf["10"] = {"class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["8", 0],
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "latent_image": ["7", 0],
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

    # 11. KSamplerAdvanced pass 2 (low)
    wf["11"] = {"class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["9", 0],
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "latent_image": ["10", 0],
                    "add_noise": "disable",
                    "noise_seed": 0,
                    "steps": steps,
                    "cfg": 1.0,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "simple",
                    "start_at_step": second_step,
                    "end_at_step": 10000,
                    "return_with_leftover_noise": "disable",
                }}

    # 12. VAE decode
    wf["12"] = {"class_type": "VAEDecode",
                "inputs": {"samples": ["11", 0], "vae": ["4", 0]}}

    # 13. Video combine (mp4 out). Filename prefix keeps the Guild's
    # downloader happy — it greps outputs for *.mp4.
    wf["13"] = {"class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["12", 0],
                    "frame_rate": fps,
                    "loop_count": 0,
                    "filename_prefix": "spellcaster_t2v",
                    "format": "video/h264-mp4",
                    "pingpong": False,
                    "save_output": True,
                }}

    return wf


def _ensure_spellcaster_core_on_path():
    """Add the canonical comfyui-spellcaster/ dir to sys.path so the
    workflows.py import works even when the Guild is launched from a
    subdirectory. Idempotent."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    candidates = [
        os.path.join(repo_root, "comfyui-spellcaster"),
        os.path.join(os.path.dirname(repo_root), "ComfyUI-Spellcaster"),
    ]
    for c in candidates:
        if os.path.isdir(os.path.join(c, "spellcaster_core")):
            if c not in sys.path:
                sys.path.insert(0, c)
            return
