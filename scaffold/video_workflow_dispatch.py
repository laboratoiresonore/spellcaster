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


# ── LTX-2 resolver (R133) ────────────────────────────────────────────
#
# LTX-2.3 uses a completely different stack from Wan 2.2:
#   - Gemma-based text encoder + LTX "embeddings connector" checkpoint
#     loaded through LTXAVTextEncoderLoader (two files → one CLIP).
#   - LTX-specific VAE (LTX23_video_vae / LTX2_video_vae).
#   - Own sampling path: LTXVScheduler + STGGuiderAdvanced +
#     LTXVBaseSampler instead of the Wan KSamplerAdvanced chain.
#   - Optional distilled LoRA for 8-step fast mode.
#
# The canonical spellcaster_core.workflows.build_ltx_video already
# wires all of that. The resolver just has to pick concrete filenames
# from the user's ComfyUI install and hand the builder a preset dict.

_LTX2_PRESET_HINTS: Dict[str, Dict[str, Any]] = {
    "ltx2_distilled": {
        "task": "t2v_audio", "distilled": True,
        "two_stage": False, "num_frames": 121, "fps": 24,
        "resolution": "768x512",
    },
    "ltx2_dev": {
        "task": "t2v", "distilled": False,
        "two_stage": False, "num_frames": 121, "fps": 24,
        "resolution": "1280x720",
    },
    "ltx2_text_to_video": {
        "task": "t2v", "distilled": False,
        "two_stage": False, "num_frames": 121, "fps": 24,
        "resolution": "1024x576",
    },
    "ltx2_text_to_video_distilled": {
        "task": "t2v", "distilled": True,
        "two_stage": False, "num_frames": 121, "fps": 24,
        "resolution": "768x512",
    },
    "ltx2_text_to_video_2stage": {
        "task": "t2v", "distilled": False,
        "two_stage": True, "num_frames": 121, "fps": 24,
        "resolution": "1280x720",
    },
    "ltx2_t2v_with_rife_interpolation": {
        "task": "t2v", "distilled": False, "interpolate": True,
        "two_stage": False, "num_frames": 121, "fps": 60,
        "resolution": "1024x576",
    },
    "ltx2_t2v_with_rtx_upscale": {
        "task": "t2v", "distilled": False, "rtx_scale": 2,
        "two_stage": False, "num_frames": 121, "fps": 24,
        "resolution": "1920x1080",
    },
    "ltx2_image_to_video": {
        "task": "i2v", "distilled": False,
        "two_stage": False, "num_frames": 121, "fps": 24,
        "resolution": "768x512",
    },
}


def resolve_ltx2_preset(preset_key: str, models: dict) -> Optional[dict]:
    """Build a build_ltx_video-compatible preset dict.

    models: as returned by probe_comfyui_models().
    """
    hint = _LTX2_PRESET_HINTS.get(preset_key)
    if not hint:
        return None

    # UNET — ltx-2.3-22b GGUF or fp8 safetensors.
    unet_pool = models.get("unet_gguf", []) + models.get("unet", [])
    unet = (_pick(unet_pool, {"ltx", "2", "3", "22b", "dev"},
                   {"q4", "gguf", "k"})
            or _pick(unet_pool, {"ltx", "22b"}, {"q4", "q8", "gguf"})
            or _pick(unet_pool, {"ltx", "2", "3"})
            or _pick(unet_pool, {"ltx"}))
    if not unet:
        log.info("resolve_ltx2_preset(%s): no LTX-2 UNET found", preset_key)
        return None

    # Text encoder — LTX-2 uses Gemma 3 12B (fp4 or fp8 scaled).
    te_pool = models.get("clip", []) + models.get("clip_gguf", [])
    text_encoder = (_pick(te_pool, {"gemma", "3", "12b"},
                           {"fp4", "fp8", "mixed", "scaled"})
                    or _pick(te_pool, {"gemma"}, {"it", "12b"})
                    or _pick(te_pool, {"gemma"}))
    if not text_encoder:
        log.info("resolve_ltx2_preset(%s): no Gemma text encoder found",
                  preset_key)
        return None

    # Embeddings connector — LTXAVTextEncoderLoader's ckpt_name field
    # expects the LTX connector safetensors. CheckpointLoaderSimple's
    # ckpt list is the same namespace so we reuse the unet_gguf +
    # vae pools + anything else; the connector is in the Wan/LTX dir.
    # We also probe CheckpointLoaderSimple separately since the
    # connector lives there rather than in unet_name.
    connector = None
    # Use the raw object_info response if available; for now look in
    # the unet pool (the connector is sometimes listed as a UNET
    # because it's a .safetensors file in the models dir).
    for pool_key in ("unet", "unet_gguf", "vae"):
        cand = _pick(models.get(pool_key, []),
                      {"ltx", "dev", "embeddings"},
                      {"connector"})
        if cand:
            connector = cand
            break
    if not connector:
        # Known LTX-2.3 embedding connector filename — fall back to the
        # literal name if the probe didn't surface it. LTX-2 users
        # universally have this file at `LTX\ltx-2.3-22b-dev_embeddings_connectors.safetensors`.
        connector = "LTX\\ltx-2.3-22b-dev_embeddings_connectors.safetensors"

    # VAE — LTX-2.3 video VAE.
    vae_pool = models.get("vae", [])
    vae = (_pick(vae_pool, {"ltx23", "video"}, {"bf16", "fp16"})
           or _pick(vae_pool, {"ltx", "2", "3"}, {"video", "vae"})
           or _pick(vae_pool, {"ltx", "video"})
           or _pick(vae_pool, {"ltx"}, {"video", "vae"}))
    if not vae:
        log.info("resolve_ltx2_preset(%s): no LTX VAE found", preset_key)
        return None

    # Distilled LoRA — accelerator for fast mode (8 steps).
    lora_pool = models.get("lora", [])
    distilled_lora = None
    if hint.get("distilled"):
        distilled_lora = (_pick(lora_pool,
                                  {"ltx", "distilled", "lora"},
                                  {"22b", "2", "3", "384"})
                          or _pick(lora_pool, {"ltxv", "distilled"}, {})
                          or _pick(lora_pool, {"ltx", "distilled"}))

    # Per-preset sampler tuning. Canonical LTX-2 defaults:
    #   - Standard: steps=30, cfg=4.0, stg=1.0, rescale=0.7
    #   - Distilled: steps=8, cfg=1.0, stg=0.0, rescale=0.0
    if hint.get("distilled"):
        tuning = {"steps": 8, "cfg": 1.0, "stg": 0.0, "rescale": 0.0}
    else:
        tuning = {"steps": 30, "cfg": 4.0, "stg": 1.0, "rescale": 0.7}

    out = {
        "unet": unet,
        "text_encoder": text_encoder,
        "embeddings_connector": connector,
        "vae": vae,
        **tuning,
    }
    if distilled_lora:
        out["distilled_lora"] = distilled_lora
    return out


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
    """Build a build_wan_video-compatible preset dict from probed model lists.

    **Canon boundary (CLAUDE.md §16.4):**
      - This is the SCAFFOLD resolver — NOT the canonical
        `video_presets.detect_wan_preset`. It exists because the
        scaffold dispatcher must also support T2V (e.g.
        `preset_key == "wan22_t2v"`), whereas the canonical helper
        is I2V-only by design.
      - For the I2V branch we DELEGATE to canon where possible:
          * VAE pairing → `video_presets.pick_wan_vae`
          * Accel LoRA pairing → `video_presets.pick_wan_accel_loras`
      - Only the UNET family picking (token-based `_pick` with
        hints from `_WAN_PRESET_HINTS`) is local, because the
        canon refuses T2V outright and the scaffold can't.

    Returns None if we can't find all required models.

    models: as returned by `probe_comfyui_models()`.
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

    # CLIP — Wan uses UMT5-XXL. Prefer the fp8 safetensors (canonical
    # ComfyUI reference workflows ship `umt5_xxl_fp8_e4m3fn_scaled`),
    # then full-precision safetensors, then the Q8 GGUF, and only if
    # nothing else exists fall back to Q6. Q3 and Q4 GGUF are
    # explicitly rejected — live-test on the user's RTX 5060 Ti
    # proved Q3_K_S produces pure-black WAN output (degenerate text
    # embeddings). Same bug band spans Q2-Q4 for UMT5. Leave the
    # legacy "blue-with-text artifacts" note for context; the black
    # frame is the more common failure.
    clip_pool = models.get("clip", []) + models.get("clip_gguf", [])
    clip = (_pick(clip_pool, {"umt5"}, {"fp8", "xxl", "scaled", "safetensors"},
                  {"gguf", "nsfw"})
            or _pick(clip_pool, {"umt5"}, {"xxl", "fp16", "safetensors"},
                     {"gguf", "nsfw"})
            or _pick(clip_pool, {"umt5"}, {"q8", "xxl"})
            or _pick(clip_pool, {"umt5"}, {"q6", "xxl"})
            or _pick(clip_pool, {"umt5"}, {"q5", "xxl"}))
    if not clip:
        log.info("resolve_wan_preset(%s): no safe UMT5 clip found "
                 "(Q3/Q4 GGUFs ignored — they produce black WAN output)",
                 preset_key)
        return None

    # VAE — Wan 2.2 A14B models share the Wan 2.1 VAE (16-channel
    # latents). A file literally named `wan2.2_vae.safetensors` on
    # some ComfyUI installations is actually a 48-channel variant
    # meant for a different Wan 2.2 branch (S2V / audio) and crashes
    # VAE — delegate to canonical pairing helper (pairs by UNET family:
    # 14B I2V-A14B ↔ wan_2.1_vae, 5B TI2V ↔ wan2.2_vae). The local
    # fallback below runs only when the canon import is unavailable or
    # pairing returns None; it's kept because token-hint resolution
    # still needs SOMETHING when running against an exotic VAE layout.
    # See CLAUDE.md §16.2 "WAN 2.2 — full formula" for the pairing table.
    vae_pool = models.get("vae", [])
    vae = None
    try:
        from spellcaster_core import video_presets as _vp
        vae = _vp.pick_wan_vae(high, vae_pool)
    except ImportError:
        pass
    if not vae:
        vae = (_pick(vae_pool, {"wan", "2", "1"}, {"vae"})
               or _pick(vae_pool, {"wan2", "1"}, {"vae", "fp32", "fp16"})
               or _pick(vae_pool, {"wan2", "2"}, {"vae"})
               or _pick(vae_pool, {"wan"}))
    if not vae:
        log.info("resolve_wan_preset(%s): no Wan VAE found", preset_key)
        return None

    # Accel LoRAs — delegate to canonical picker when the task is I2V.
    # T2V still uses the explicit token search here because the canon
    # rejects T2V accel LoRAs (Spellcaster's canon is I2V-only). See
    # `video_presets.pick_wan_accel_loras` + CLAUDE.md §16.2.
    lora_pool = models.get("lora", [])
    high_accel = None
    low_accel = None
    task = (_WAN_PRESET_HINTS.get(preset_key) or {}).get("task", "i2v")
    if task == "i2v":
        try:
            from spellcaster_core import video_presets as _vp
            high_accel, low_accel = _vp.pick_wan_accel_loras(lora_pool)
        except ImportError:
            pass
        # Fall back to the local token search if the canon returned nothing
        # (e.g. LoRAs with non-standard filenames).
        if not (high_accel and low_accel):
            high_accel = (high_accel or _pick(lora_pool,
                              {"wan2", "2", "lightning", "i2v", "high"},
                              {"4steps", "a14b", "fp16"})
                          or _pick(lora_pool,
                                 {"wan2", "2", "i2v", "lightx2v", "high"},
                                 {"4steps", "lora"}))
            low_accel = (low_accel or _pick(lora_pool,
                             {"wan2", "2", "lightning", "i2v", "low"},
                             {"4steps", "a14b", "fp16"})
                         or _pick(lora_pool,
                                {"wan2", "2", "i2v", "lightx2v", "low"},
                                {"4steps", "lora"}))
    elif task == "t2v":
        # T2V is out-of-canon for Spellcaster but the preset key exists;
        # we still wire accel LoRAs so that workflow runs at all.
        high_accel = _pick(lora_pool,
                            {"wan2", "2", "t2v", "lightx2v", "high"},
                            {"4steps", "lora"})
        low_accel = _pick(lora_pool,
                           {"wan2", "2", "t2v", "lightx2v", "low"},
                           {"4steps", "lora"})

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
                           turbo: bool = True,
                           # R131: quality-feature passthroughs for the
                           # Wan 2.1-era build_wan_video path. These mirror
                           # the GIMP plugin's UI knobs so the Guild /
                           # Resolve / Cinematographer can request the same
                           # post-processing chain.
                           loras_high: Optional[List[Tuple[str, float]]] = None,
                           loras_low: Optional[List[Tuple[str, float]]] = None,
                           face_swap: bool = False,
                           interpolate: bool = False,
                           rtx_scale: float = 1.0,
                           teacache: bool = False,
                           tiled_vae: bool = False,
                           ip_adapter_image: Optional[str] = None,
                           ip_adapter_weight: float = 0.5,
                           motion_mask: Optional[str] = None,
                           pingpong: bool = False,
                           ) -> Tuple[Optional[dict], Optional[str]]:
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

    family = (spec.get("family") or "").lower()

    # ── SeedVR2 upscaler ────────────────────────────────────────────
    # Video-in → higher-resolution video-out. Takes a source video
    # file that must already live in ComfyUI's input/ dir (uploaded
    # by the dispatcher). No prompt, no ref image, no latent — it's
    # a post-processing path.
    if family == "seedvr2":
        _ensure_spellcaster_core_on_path()
        try:
            from spellcaster_core.workflows import build_seedvr2_video_upscale  # type: ignore
        except ImportError as e:
            return None, f"spellcaster_core.workflows.build_seedvr2_video_upscale missing: {e}"
        if not image_filename:
            # For seedvr2 `image_filename` is reused as the input
            # video basename — the caller uploads the mp4 to
            # ComfyUI's input/ and passes the basename here.
            return None, ("seedvr2_video_upscale requires an input "
                          "video (set shot.overrides.input_video)")
        try:
            target_res = defaults.get("resolution", "1920x1080")
            try:
                w_target = int(target_res.split("x")[0])
            except Exception:
                w_target = 1920
            workflow = build_seedvr2_video_upscale(
                video_name=image_filename,
                seed=seed,
                resolution=w_target,
                fps=fps,
            )
        except Exception as e:  # noqa: BLE001
            return None, f"build_seedvr2_video_upscale raised: {e}"
        return workflow, None

    # ── LTX-2 family ────────────────────────────────────────────────
    # Uses a completely different stack (Gemma encoder, LTX VAE,
    # STGGuider, LTXVBaseSampler). Canonical builder is
    # spellcaster_core.workflows.build_ltx_video.
    if family == "ltx":
        _ensure_spellcaster_core_on_path()
        try:
            from spellcaster_core.workflows import build_ltx_video  # type: ignore
        except ImportError as e:
            return None, f"spellcaster_core.workflows.build_ltx_video missing: {e}"
        models = probe_comfyui_models(comfyui_base_url)
        preset_dict = resolve_ltx2_preset(preset_key, models)
        if not preset_dict:
            return None, (f"couldn't locate LTX-2 models on ComfyUI for "
                          f"{preset_key!r}. Install ltx-2.3-22b-dev GGUF "
                          "+ Gemma 3 12B + the LTX connector + LTX "
                          "video VAE under ComfyUI/models/.")
        hint = _LTX2_PRESET_HINTS.get(preset_key) or {}
        task = (spec.get("task") or "").lower()
        if task in ("i2v",) and not image_filename:
            return None, "this preset needs a reference image (i2v)"
        try:
            # Pass the caller's negative verbatim so shot.negative
            # reaches the sampler. Defaulting to None lets
            # build_ltx_video inject its subtitle-burn-in blocker.
            workflow = build_ltx_video(
                preset=preset_dict,
                prompt_text=prompt,
                seed=seed,
                width=width, height=height,
                num_frames=length,
                two_stage=bool(hint.get("two_stage", False)),
                distilled=bool(hint.get("distilled", False)),
                interpolate=bool(hint.get("interpolate", False)),
                rtx_scale=int(hint.get("rtx_scale", 0)),
                fps=fps,
                image_filename=image_filename,
                negative_text=(negative or None),
            )
        except Exception as e:  # noqa: BLE001
            return None, f"build_ltx_video raised: {e}"
        if not isinstance(workflow, dict) or not workflow:
            return None, "build_ltx_video returned empty workflow"
        return workflow, None

    # ── Wan 2.2 family — existing path ─────────────────────────────
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

    # R128: route through the canonical builders.
    #
    # t2v → build_wan22_t2v (uses Wan22ImageToVideoLatent, which matches
    # the Wan 2.2 A14B t2v models cleanly).
    #
    # i2v → build_wan_video (the Wan 2.1-era builder). It uses
    # WanImageToVideo (base) + CLIPVisionEncode which works correctly
    # on Wan 2.2 A14B i2v models. The Wan 2.2-native alternative
    # WanImageToVideo_F2 has a local reshape bug on some ComfyUI
    # installs (adds 3 phantom channels worth of data that the downstream
    # tensor reshape rejects — "shape [1, 21, 4, 60, 104] invalid for
    # input of size 542880"). Staying on the base node avoids it and
    # inherits build_wan_video's full quality chain (face_swap,
    # interpolate, NAG, SLG, IP-Adapter) when callers want them.
    try:
        from spellcaster_core.workflows import (  # type: ignore
            build_wan22_t2v, build_wan_video,
        )
        # Canon: every build_wan_video call pairs with wan_turbo_kwargs so
        # the turbo/full-step schedule (steps/cfg/second_step) is the same
        # across every WAN consumer. See CLAUDE.md §16.4 rule #2.
        from spellcaster_core import video_presets as _vp  # type: ignore
    except ImportError as e:
        return None, f"spellcaster_core.workflows (R128 builders) missing: {e}"

    _canon = _vp.wan_turbo_kwargs(bool(turbo))

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
            workflow = build_wan_video(
                image_filename=image_filename,
                preset=preset_dict,
                prompt_text=prompt, negative_text=negative, seed=seed,
                width=width, height=height, length=length,
                fps=fps, turbo=turbo,
                # Canon turbo/full-step schedule. When turbo=False this
                # injects steps=30, cfg=3.5, second_step=15 — without these
                # the preset's turbo defaults leak through and the LoRA-less
                # full-step path produces black frames (CLAUDE.md §16.2).
                **_canon,
                # Pass through user-chosen / caller-chosen quality
                # knobs. The canonical build_wan_video knows how to
                # wire each one (face swap via ReActor, RIFE 4× for
                # interpolate, Wan video upscale for rtx_scale,
                # IP-Adapter-WAN for ip_adapter_image, etc). Turning
                # them on/off is the caller's decision, not the
                # dispatcher's.
                loras_high=loras_high, loras_low=loras_low,
                face_swap=face_swap, interpolate=interpolate,
                rtx_scale=rtx_scale,
                teacache=teacache, tiled_vae=tiled_vae,
                ip_adapter_image=ip_adapter_image,
                ip_adapter_weight=ip_adapter_weight,
                motion_mask=motion_mask, pingpong=pingpong,
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
