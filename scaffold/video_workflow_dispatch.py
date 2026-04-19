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
    'clip_gguf': [...], 'vae': [...], 'lora': [...]} for the given
    ComfyUI server.

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
        "vae": [], "lora": [],
    }
    queries = [
        ("UnetLoaderGGUF",      "unet_name",  "unet_gguf"),
        ("UNETLoader",          "unet_name",  "unet"),
        ("CLIPLoaderGGUF",      "clip_name",  "clip_gguf"),
        ("CLIPLoader",          "clip_name",  "clip"),
        ("VAELoader",           "vae_name",   "vae"),
        ("LoraLoader",          "lora_name",  "lora"),
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

    # VAE — Wan 2.2 A14B models share the Wan 2.1 VAE (16-channel
    # latents). A file literally named `wan2.2_vae.safetensors` on
    # some ComfyUI installations is actually a 48-channel variant
    # meant for a different Wan 2.2 branch (S2V / audio) and crashes
    # VAEDecode with a channel mismatch when fed A14B latents. Prefer
    # `wan_2.1_vae` or anything explicitly tagged 2.1 first; only fall
    # back to `wan2.2_vae` if no 2.1 VAE is installed.
    vae_pool = models.get("vae", [])
    vae = (_pick(vae_pool, {"wan", "2", "1"}, {"vae"})
           or _pick(vae_pool, {"wan2", "1"}, {"vae", "fp32", "fp16"})
           or _pick(vae_pool, {"wan2", "2"}, {"vae"})
           or _pick(vae_pool, {"wan"}))
    if not vae:
        log.info("resolve_wan_preset(%s): no Wan VAE found", preset_key)
        return None

    # Auto-detect the lightx2v 4-step distillation LoRAs. When both
    # high + low are present, lightning mode runs at 4 steps cfg=1.0
    # with excellent quality. Without them, lightning falls back to
    # HQ-like step counts (the fp8 base models can't hit 4 steps
    # without distillation).
    lora_pool = models.get("lora", [])
    high_accel = None
    low_accel = None
    task = (_WAN_PRESET_HINTS.get(preset_key) or {}).get("task", "i2v")
    if task == "t2v":
        high_accel = _pick(lora_pool,
                            {"wan2", "2", "t2v", "lightx2v", "high"},
                            {"4steps", "lora"})
        low_accel = _pick(lora_pool,
                           {"wan2", "2", "t2v", "lightx2v", "low"},
                           {"4steps", "lora"})
    elif task == "i2v":
        # Prefer the official Wan2.2-Lightning I2V LoRAs; lightx2v
        # variants work too.
        high_accel = (_pick(lora_pool,
                              {"wan2", "2", "lightning", "i2v", "high"},
                              {"4steps", "a14b", "fp16"})
                      or _pick(lora_pool,
                                 {"wan2", "2", "i2v", "lightx2v", "high"},
                                 {"4steps", "lora"}))
        low_accel = (_pick(lora_pool,
                             {"wan2", "2", "lightning", "i2v", "low"},
                             {"4steps", "a14b", "fp16"})
                     or _pick(lora_pool,
                                {"wan2", "2", "i2v", "lightx2v", "low"},
                                {"4steps", "lora"}))

    have_accel = bool(high_accel and low_accel)

    # Per-preset sampler tuning. Wan 2.2's canonical defaults (per the
    # ComfyUI examples repo and xb1n0ry's reference pack):
    #   - shift: 8.0 (HQ), 5.0 with accelerator LoRAs
    #   - steps: 20 split into 10 high / 10 low at HQ, 4 total with
    #     accelerator LoRAs
    #   - cfg: 5.0 on the HQ high pass, 1.0 on low; 1.0 on both with
    #     accelerator
    if preset_key == "wan22_i2v_lightning":
        if have_accel:
            tuning = {"steps": 4, "cfg": 1.0, "shift": 5.0,
                       "second_step": 2, "accel_strength": 1.0}
        else:
            # Graceful fallback — no distillation LoRA available, do a
            # 20-step render instead of a noisy 6-step one. "Lightning"
            # in name only; quality beats garbage every time.
            tuning = {"steps": 20, "cfg": 5.0, "shift": 8.0,
                       "second_step": 10}
    elif preset_key == "wan22_i2v_hq":
        tuning = {"steps": 20, "cfg": 5.0, "shift": 8.0,
                   "second_step": 10}
    elif preset_key == "wan22_t2v":
        if have_accel:
            tuning = {"steps": 4, "cfg": 1.0, "shift": 5.0,
                       "second_step": 2, "accel_strength": 1.0}
        else:
            tuning = {"steps": 20, "cfg": 5.0, "shift": 8.0,
                       "second_step": 10}
    else:
        tuning = {"steps": 20, "cfg": 5.0, "shift": 8.0,
                   "second_step": 10}

    out = {
        "high_model": high,
        "low_model":  low,
        "clip":       clip,
        "vae":        vae,
        "clip_is_gguf": clip.lower().endswith(".gguf"),
        **tuning,
    }
    # Only attach accelerator LoRAs for the lightning presets. HQ
    # deliberately uses the full 20-step + cfg=5 path (no LoRAs) for
    # maximum quality.
    use_accel = have_accel and preset_key in (
        "wan22_i2v_lightning", "wan22_t2v")
    if use_accel:
        out["high_accel_lora"] = high_accel
        out["low_accel_lora"] = low_accel
    return out


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

    # R128: route through the Wan-2.2-correct canonical builders in
    # spellcaster_core/workflows.py. build_wan_video (used in the
    # R126/R127 first cut) is Wan-2.1 shaped — its 16-channel latent
    # path mismatches the Wan 2.2 VAE (48 channels) and fails at
    # VAEDecode. The new builders use Wan22ImageToVideoLatent /
    # WanImageToVideo_F2 which match the Wan 2.2 architecture.
    try:
        from spellcaster_core.workflows import (  # type: ignore
            build_wan22_t2v, build_wan22_i2v,
        )
    except ImportError as e:
        return None, f"spellcaster_core.workflows (R128 builders) missing: {e}"

    try:
        if task == "t2v":
            workflow = build_wan22_t2v(
                preset=preset_dict,
                prompt_text=prompt, negative_text=negative, seed=seed,
                width=width, height=height, length=length, fps=fps,
                turbo=turbo,
            )
        else:
            # i2v / move_i2v / any task that needs a ref image
            workflow = build_wan22_i2v(
                image_filename=image_filename,
                preset=preset_dict,
                prompt_text=prompt, negative_text=negative, seed=seed,
                width=width, height=height, length=length, fps=fps,
                turbo=turbo,
            )
    except Exception as e:  # noqa: BLE001
        return None, f"wan22 builder raised: {e}"
    if not isinstance(workflow, dict) or not workflow:
        return None, "wan22 builder returned empty workflow"
    return workflow, None


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
