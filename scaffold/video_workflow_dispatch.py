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
import urllib.parse
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
        "unet_gguf": [], "unet": [], "ckpt": [],
        "clip_gguf": [], "clip": [],
        "vae": [], "lora": [], "latent_upscaler": [],
        "seedvr2_dit": [], "seedvr2_vae": [],
    }
    queries = [
        ("UnetLoaderGGUF",      "unet_name",  "unet_gguf"),
        ("UNETLoader",          "unet_name",  "unet"),
        ("CheckpointLoaderSimple", "ckpt_name", "ckpt"),
        ("CLIPLoaderGGUF",      "clip_name",  "clip_gguf"),
        ("CLIPLoader",          "clip_name",  "clip"),
        ("VAELoader",           "vae_name",   "vae"),
        ("LoraLoader",          "lora_name",  "lora"),
        ("LatentUpscaleModelLoader", "model_name", "latent_upscaler"),
        ("SeedVR2LoadDiTModel", "model",      "seedvr2_dit"),
        ("SeedVR2LoadVAEModel", "model",      "seedvr2_vae"),
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
            elif (field and isinstance(field, list) and field[0] == "COMBO"
                  and len(field) > 1 and isinstance(field[1], dict)):
                # newer V3-style combo: ["COMBO", {"options": [...]}]
                out[out_key] = list(field[1].get("options", []))
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

    # UNET — ltx-2.3-22b GGUF or full safetensors checkpoint.
    # Lane6 2026-10-05: the unet pools on some servers (spark2) alias EVERY
    # model folder, so they also list LoRAs, spatial/temporal upscalers and
    # connector files whose names contain "ltx"/"22b". Those are not
    # diffusion models; picking one (it was the shortest name) produced
    # "UnetLoaderGGUF.unet_name not in list" validation failures.
    _not_unet = {"lora", "upscaler", "embeddings", "connectors", "connector"}
    raw_unets = models.get("unet_gguf", []) + models.get("unet", [])
    raw_ckpts = [c for c in models.get("ckpt", []) if c not in raw_unets]
    unet_pool = [u for u in (raw_unets + raw_ckpts)
                 if not (_tokens(u) & _not_unet)
                 and not u.replace("\\", "/").endswith("ltx-video-2.3-nvfp4/model.safetensors")]
    try:
        from spellcaster_core.model_detect import is_usable_model
        unet_pool = [u for u in unet_pool if is_usable_model(u, "unet")]
    except ImportError:
        pass
    unet = (_pick(unet_pool, {"ltx", "2", "3", "22b", "distilled"},
                   {"fp4", "nvfp4", "1"})
            or _pick(unet_pool, {"ltx", "2", "3", "22b", "dev"},
                   {"q4", "gguf", "k", "nvfp4", "fp4"})
            or _pick(unet_pool, {"ltx", "22b"}, {"q4", "q8", "gguf", "nvfp4", "fp4"})
            or _pick(unet_pool, {"ltx", "2", "3"})
            or _pick(unet_pool, {"ltx"}))
    if not unet:
        log.info("resolve_ltx2_preset(%s): no LTX-2 UNET found", preset_key)
        return None
    unet_in_checkpoints = (unet in raw_ckpts and unet not in raw_unets)
    # A non-GGUF "distilled" file is the full distilled checkpoint (the
    # distilled LoRA is already baked in; it also carries the embeddings
    # connector). Builder loads it with UNETLoader.
    baked_distilled = ("distilled" in _tokens(unet)
                       and not unet.lower().endswith(".gguf"))

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
    if not connector and not unet.lower().endswith(".gguf"):
        # Full safetensors checkpoint carries its own connectors.
        connector = unet
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
    if hint.get("distilled") or baked_distilled:
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
    if baked_distilled:
        out["distilled_baked"] = True
    if unet_in_checkpoints:
        out["unet_in_checkpoints"] = True
    ups_pool = models.get("latent_upscaler", [])
    ups = (_pick(ups_pool, {"ltx", "spatial", "upscaler", "x2"}, {"2", "3", "1"})
           or _pick(ups_pool, {"spatial", "upscaler"}))
    if ups:
        out["latent_upscaler"] = ups
    return out


# ── Preset resolver ─────────────────────────────────────────────────

# Map WANGP_PRESETS keys to a (must, nice, bad) token spec for the
# HIGH-noise (or single) model. The LOW-noise model mirrors the HIGH
# with the "high" / "low" token swapped inside _resolve_wan().
_WAN_PRESET_HINTS: Dict[str, Dict[str, Any]] = {
    "wan22_i2v_lightning": {
        "task": "i2v", "family": "wan22",
        "high_must": {"wan2", "2", "i2v", "high"},
        "high_nice": {"a14b", "14b", "lightning", "nvfp4", "fp4", "q4"},
        "high_bad":  {"t2v"},
        "low_must":  {"wan2", "2", "i2v", "low"},
        "low_nice":  {"a14b", "14b", "lightning", "nvfp4", "fp4", "q4"},
        "low_bad":   {"t2v"},
    },
    "wan22_i2v_hq": {
        "task": "i2v", "family": "wan22",
        "high_must": {"wan2", "2", "i2v", "high"},
        "high_nice": {"a14b", "14b", "nvfp4", "fp4", "q6", "q8", "fp16", "hq"},
        "high_bad":  {"t2v", "lightning"},
        "low_must":  {"wan2", "2", "i2v", "low"},
        "low_nice":  {"a14b", "14b", "nvfp4", "fp4", "q6", "q8", "fp16", "hq"},
        "low_bad":   {"t2v", "lightning"},
    },
    "wan22_t2v": {
        "task": "t2v", "family": "wan22",
        "high_must": {"wan2", "2", "t2v", "high"},
        "high_nice": {"a14b", "14b", "nvfp4", "fp4", "q4", "q6"},
        "high_bad":  {"i2v"},
        "low_must":  {"wan2", "2", "t2v", "low"},
        "low_nice":  {"a14b", "14b", "nvfp4", "fp4", "q6", "q8"},
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
    try:
        from spellcaster_core.model_detect import is_usable_model
        unet_pool = [u for u in unet_pool if is_usable_model(u, "unet")]
    except ImportError:
        pass
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
    # then fp4_mixed / full-precision safetensors, then the Q8 GGUF, and only if
    # nothing else exists fall back to Q6. Q3 and Q4 GGUF are
    # explicitly rejected — live-test on the user's RTX 5060 Ti
    # proved Q3_K_S produces pure-black WAN output (degenerate text
    # embeddings). Same bug band spans Q2-Q4 for UMT5. Leave the
    # legacy "blue-with-text artifacts" note for context; the black
    # frame is the more common failure.
    clip_pool = models.get("clip", []) + models.get("clip_gguf", [])
    _clip_skip = {"gguf", "nsfw"}
    clip = (_pick(clip_pool, {"umt5"}, {"fp8", "xxl", "scaled", "safetensors"},
                  _clip_skip)
            or _pick(clip_pool, {"umt5"}, {"fp4", "mixed", "xxl", "safetensors"},
                     _clip_skip)
            or _pick(clip_pool, {"umt5"}, {"xxl", "fp16", "safetensors"},
                     _clip_skip)
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

def _build_native_workflow_impl(preset_key: str, *, prompt: str,
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
                           teacache: Optional[bool] = None,
                           tiled_vae: bool = False,
                           ip_adapter_image: Optional[str] = None,
                           ip_adapter_weight: float = 0.5,
                           motion_mask: Optional[str] = None,
                           pingpong: bool = False,
                           # Optional quality + speed patches (auto-probed
                           # by the GIMP wrapper; plumbed here so Guild /
                           # Resolve / SillyTavern / Darktable can opt in
                           # too). None = let the canonical builder decide
                           # (usually disabled unless the caller explicitly
                           # wants the patch). See CLAUDE.md §16.2.
                           enable_slg: Optional[bool] = None,
                           enable_nag: Optional[bool] = None,
                           enable_sage: Optional[bool] = None,
                           enable_cfg_zero: Optional[bool] = None,
                           # Sampler override (default euler/simple in the
                           # canonical builder — Kijai reference schedule).
                           sampler_name: Optional[str] = None,
                           scheduler: Optional[str] = None,
                           # LTX-specific overrides (CLAUDE.md §16.3).
                           # None = let the preset's default ride. Used by
                           # the GIMP dialog's Advanced section, Darktable
                           # LTX section, and any future Guild clients.
                           steps: Optional[int] = None,
                           cfg: Optional[float] = None,
                           stg: Optional[float] = None,
                           rescale: Optional[float] = None,
                           i2v_strength: Optional[float] = None,
                           stg_layers: Optional[str] = None,
                           chunk_size: Optional[int] = None,
                           # VAE decode tiling — for VRAM tuning +
                           # last-frame artifact fixes on RTX 50xx.
                           vae_spatial_tiles: Optional[int] = None,
                           vae_temporal_tile_length: Optional[int] = None,
                           vae_last_frame_fix: bool = False,
                           vae_working_dtype: Optional[str] = None,
                           # Extra LoRAs beyond the preset's distilled LoRA.
                           # List of (name, strength) tuples.
                           extra_loras: Optional[List[Tuple[str, float]]] = None,
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
            from spellcaster_core import video_presets as _vp  # type: ignore
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
            svr_preset = _vp.detect_seedvr2_preset(comfyui_base_url) or {}
            dit_kwargs = {}
            if svr_preset.get("dit_model"):
                dit_kwargs["dit_model"] = svr_preset["dit_model"]
            if svr_preset.get("vae_model"):
                dit_kwargs["vae_model"] = svr_preset["vae_model"]
            workflow = build_seedvr2_video_upscale(
                video_name=image_filename,
                seed=seed,
                resolution=w_target,
                fps=fps,
                **dit_kwargs,
            )
        except Exception as e:  # noqa: BLE001
            return None, f"build_seedvr2_video_upscale raised: {e}"
        return workflow, None

    # ── HunyuanVideo 1.5 / SkyReels V2 ──────────────────────────────
    if family in ("hunyuan_video", "skyreels"):
        _ensure_spellcaster_core_on_path()
        try:
            from spellcaster_core import workflows as _wf  # type: ignore
            from spellcaster_core import video_presets as _vp  # type: ignore
        except ImportError as e:
            return None, f"spellcaster_core video modules missing: {e}"
        task = (spec.get("task") or "").lower()
        if task in ("i2v",) and not image_filename:
            return None, "this preset needs a reference image (i2v)"
        try:
            if family == "hunyuan_video":
                preset_dict = _vp.detect_hunyuan_video_preset(comfyui_base_url)
                if not preset_dict:
                    return None, "couldn't locate HunyuanVideo models on ComfyUI"
                workflow = _wf.build_hunyuan_video(
                    prompt_text=prompt, seed=seed,
                    hy_model=preset_dict["hy_model"],
                    vae_name=preset_dict["vae_name"],
                    width=width, height=height, num_frames=length, fps=fps,
                    steps=steps or defaults.get("steps", 20),
                )
            else:
                preset_dict = _vp.detect_skyreels_preset(comfyui_base_url)
                if not preset_dict:
                    return None, "couldn't locate SkyReels V2 models on ComfyUI"
                workflow = _wf.build_skyreels_video(
                    preset=preset_dict,
                    prompt_text=prompt, negative_text=negative, seed=seed,
                    width=width, height=height, length=length, fps=fps,
                    steps=steps or defaults.get("steps", 20),
                    cfg=cfg if cfg is not None else defaults.get("guidance", 5.0),
                    image_filename=image_filename,
                )
        except Exception as e:  # noqa: BLE001
            return None, f"{family} builder raised: {e}"
        if not isinstance(workflow, dict) or not workflow:
            return None, f"{family} builder returned empty workflow"
        return workflow, None

    # ── LTX-2 family ────────────────────────────────────────────────
    # Uses a completely different stack (Gemma encoder, LTX VAE,
    # STGGuider, LTXVBaseSampler). Canonical builder is
    # spellcaster_core.workflows.build_ltx_video.
    if family == "ltx":
        _ensure_spellcaster_core_on_path()
        try:
            from spellcaster_core.workflows import build_ltx_video  # type: ignore
            from spellcaster_core import video_presets as _vp  # type: ignore
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

        # Resolve (distilled, two_stage) via the canonical helper — this
        # mirrors the GIMP / Guild path and keeps every LTX caller
        # agreeing on the mode → kwargs translation (CLAUDE.md §16.4
        # rule #2). The mode name is implicit in the hint dict.
        if hint.get("distilled") and not hint.get("two_stage"):
            _mode = "i2v" if image_filename else "distilled"
        elif hint.get("two_stage"):
            _mode = "two_stage"
        else:
            _mode = "full"
        try:
            mode_kwargs = _vp.ltx_mode_kwargs(_mode)
        except Exception:
            mode_kwargs = {
                "distilled": bool(hint.get("distilled", False)),
                "two_stage": bool(hint.get("two_stage", False)),
            }

        # Conditional passthrough — only include caller overrides when
        # they are set so the canonical builder's defaults stay intact.
        extra = {}
        if steps        is not None: extra["steps"]        = steps
        if cfg          is not None: extra["cfg"]          = cfg
        if stg          is not None: extra["stg"]          = stg
        if rescale      is not None: extra["rescale"]      = rescale
        if i2v_strength is not None: extra["i2v_strength"] = i2v_strength
        if sampler_name:             extra["sampler_name"] = sampler_name
        if stg_layers:               extra["stg_layers"]   = stg_layers
        if chunk_size   is not None: extra["chunk_size"]   = chunk_size
        if enable_sage     is not None: extra["enable_sage"]     = bool(enable_sage)
        if enable_cfg_zero is not None: extra["enable_cfg_zero"] = bool(enable_cfg_zero)
        if vae_spatial_tiles        is not None: extra["vae_spatial_tiles"]        = vae_spatial_tiles
        if vae_temporal_tile_length is not None: extra["vae_temporal_tile_length"] = vae_temporal_tile_length
        if vae_last_frame_fix:                   extra["vae_last_frame_fix"]       = True
        if vae_working_dtype:                    extra["vae_working_dtype"]        = vae_working_dtype
        if extra_loras:                          extra["loras"]                    = list(extra_loras)

        # Caller-supplied interpolate / rtx_scale override the preset's
        # hint default. `interpolate=True` from the caller wins even if
        # the hint is False; `rtx_scale>1.0` from the caller wins over
        # hint's default. This matches the Wan family's behaviour and
        # lets SillyTavern / Resolve / Darktable turn RIFE + RTX upscale
        # on per-shot without picking a different preset_key.
        _ltx_interp = bool(interpolate) or bool(hint.get("interpolate", False))
        if rtx_scale and rtx_scale > 1.0:
            _ltx_rtx = int(rtx_scale)
        else:
            _ltx_rtx = int(hint.get("rtx_scale", 0))

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
                **mode_kwargs,
                interpolate=_ltx_interp,
                rtx_scale=_ltx_rtx,
                fps=fps,
                pingpong=bool(pingpong),
                image_filename=image_filename,
                negative_text=(negative or None),
                **extra,
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
                # Optional quality + speed patches. Only forward when
                # the caller explicitly set them (None means "let the
                # canonical builder's default decide"). This keeps the
                # canonical builder's auto-logic intact for
                # teacache/sage/etc.
                **({"enable_slg": enable_slg} if enable_slg is not None else {}),
                **({"enable_nag": enable_nag} if enable_nag is not None else {}),
                **({"enable_sage": enable_sage} if enable_sage is not None else {}),
                **({"enable_cfg_zero": enable_cfg_zero} if enable_cfg_zero is not None else {}),
                **({"sampler_name": sampler_name} if sampler_name else {}),
                **({"scheduler": scheduler} if scheduler else {}),
            )
    except Exception as e:  # noqa: BLE001
        return None, f"wan22 builder raised: {e}"
    if not isinstance(workflow, dict) or not workflow:
        return None, "wan22 builder returned empty workflow"
    return workflow, None


# ── Disk-JSON model-name healing (Lane6 2026-10-05) ─────────────────
#
# Static workflow templates (scaffold/workflows/*.json) hard-code model
# filenames from whichever machine they were authored on. On another
# ComfyUI the names are not in the loader's combo list and /prompt fails
# validation (value_not_in_list). heal_loader_names() rewrites each
# loader input that is NOT in the server's list to the best fuzzy match
# (same token machinery as the builders' resolvers). Values already valid
# are never touched; with no acceptable match the value is left alone so
# the server's own error surfaces.

_LOADER_FIELDS = {
    "UNETLoader": "unet_name", "UnetLoaderGGUF": "unet_name",
    "CLIPLoader": "clip_name", "CLIPLoaderGGUF": "clip_name",
    "VAELoader": "vae_name", "LoraLoaderModelOnly": "lora_name",
    "LoraLoader": "lora_name", "CheckpointLoaderSimple": "ckpt_name",
    "ReActorFaceSwap": "swap_model", "ReActorFaceSwapOpt": "swap_model",
}
# Loader classes safe to fuzzy-heal on ANY video workflow. LoRAs are
# deliberately excluded: a silently-wrong LoRA is worse than a loud error.
_VIDEO_HEAL_CLASSES = {"UNETLoader", "UnetLoaderGGUF", "CLIPLoader",
                       "CLIPLoaderGGUF", "VAELoader",
                       "ReActorFaceSwap", "ReActorFaceSwapOpt"}
_SWAP_FALLBACKS = ["inswapper_128.onnx", "inswapper_128_fp16.onnx"]
_VIDEO_NODE_CLASSES = {"VHS_VideoCombine", "VHS_LoadVideo", "CreateVideo",
                       "SaveVideo", "SaveWEBM", "SaveAnimatedWEBP"}
_QUANT_TOKENS = {"q2", "q3", "q4", "q5", "q6", "q8", "k", "m", "s", "l", "0",
                 "1", "fp8", "fp16", "fp32", "bf16", "e4m3fn", "scaled",
                 "gguf", "safetensors", "wan", "ltx"}


def heal_loader_names(workflow: dict, base_url: str,
                      only_classes: Optional[set] = None) -> List[str]:
    """In-place heal of loader model names. Returns a list of change notes."""
    notes: List[str] = []
    cache: Dict[str, List[str]] = {}

    def _opts(cls: str, field: str) -> List[str]:
        if cls in cache:
            return cache[cls]
        out: List[str] = []
        try:
            with urllib.request.urlopen(
                    f"{base_url.rstrip('/')}/object_info/{cls}", timeout=15) as r:
                d = json.loads(r.read()).get(cls) or {}
            req = (d.get("input") or {}).get("required") or {}
            f = req.get(field)
            if f:
                out = list(f[0]) if isinstance(f[0], list) else list(
                    (f[1] or {}).get("options", []))
        except Exception as e:  # noqa: BLE001 — healing must never raise
            log.debug("heal probe %s failed: %s", cls, e)
        cache[cls] = out
        return out

    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        field = _LOADER_FIELDS.get(cls)
        if only_classes is not None and cls not in only_classes:
            continue
        inp = node.get("inputs") or {}
        want = inp.get(field) if field else None
        if not isinstance(want, str):
            continue
        opts = _opts(cls, field)
        if not opts or want in opts:
            continue
        pool = list(opts)
        # GGUF loader missing the file: try the stock loader's list too.
        alt_cls = {"UnetLoaderGGUF": "UNETLoader",
                   "CLIPLoaderGGUF": "CLIPLoader"}.get(cls)
        alt_pool = _opts(alt_cls, field) if alt_cls else []
        base = os.path.basename(want.replace("\\", "/"))
        toks = _tokens(base) - _QUANT_TOKENS
        pick = None
        pick_cls = cls
        if field == "swap_model":
            pick = next((m for m in _SWAP_FALLBACKS if m in pool), None)
            toks = set()
        for must_n in range(len(toks), 0, -1):
            must = set(sorted(toks, key=len, reverse=True)[:must_n])
            pick = _pick(pool, must)
            if pick:
                break
            if alt_pool:
                pick = _pick(alt_pool, must)
                if pick:
                    pick_cls = alt_cls
                    break
        if pick:
            inp[field] = pick
            node["class_type"] = pick_cls
            if pick_cls != cls and pick_cls == "UNETLoader":
                inp.setdefault("weight_dtype", "default")
            notes.append(f"{nid}:{cls}.{field}: {want!r} -> {pick!r}")
    return notes


def drop_unsafe_audio_links(workflow: dict, base_url: str) -> List[str]:
    """Remove VHS_LoadVideo(audio) -> VHS_VideoCombine(audio) wires when the
    source clip has NO audio stream.

    Lane6 2026-10-05 root cause of "VHS failed to extract audio from
    .../ComfyUI_00008_.mp4 ... Output file does not contain any stream":
    VHS_LoadVideo's AUDIO output is lazy; the moment VHS_VideoCombine pulls
    it, VHS runs ffmpeg to extract an audio stream that does not exist and
    raises, failing the whole prompt. Generated (Wan/LTX/ComfyUI) clips are
    usually silent, so the passthrough wiring is a latent landmine. We probe
    the clip with ffprobe (via /view) and drop the wire only when it is
    provably silent; probe failures leave the workflow untouched.
    """
    import shutil
    import subprocess
    import tempfile
    notes: List[str] = []
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not (ffprobe or ffmpeg):
        return notes
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    for nid, node in workflow.items():
        if not (isinstance(node, dict)
                and node.get("class_type") == "VHS_VideoCombine"):
            continue
        a = (node.get("inputs") or {}).get("audio")
        if not (isinstance(a, list) and len(a) == 2 and a[1] == 2):
            continue
        src = workflow.get(a[0]) or {}
        if src.get("class_type") != "VHS_LoadVideo":
            continue
        fname = (src.get("inputs") or {}).get("video")
        if not isinstance(fname, str) or not fname:
            continue
        sub, _, base = fname.replace("\\", "/").rpartition("/")
        q = urllib.parse.urlencode({"filename": base, "subfolder": sub,
                                    "type": "input"})
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(base)[1] or ".mp4",
                                             delete=False) as tf:
                tmp = tf.name
                with urllib.request.urlopen(
                        f"{base_url.rstrip('/')}/view?{q}", timeout=60) as r:
                    total = 0
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 512 * (1 << 20):
                            raise RuntimeError("clip too large to probe")
                        tf.write(chunk)
            if ffprobe:
                out = subprocess.run(
                    [ffprobe, "-v", "error", "-select_streams", "a",
                     "-show_entries", "stream=index", "-of", "csv=p=0", tmp],
                    capture_output=True, text=True, timeout=60,
                    creationflags=flags)
                has_audio = bool(out.stdout.strip())
                ok = out.returncode == 0
            else:
                out = subprocess.run([ffmpeg, "-hide_banner", "-i", tmp],
                                     capture_output=True, text=True,
                                     timeout=60, creationflags=flags)
                has_audio = "Audio:" in out.stderr
                ok = "Video:" in out.stderr
            if ok and not has_audio:
                del node["inputs"]["audio"]
                notes.append(f"{nid}: dropped audio wire from silent clip {fname!r}")
        except Exception as e:  # noqa: BLE001 — probing must never block submit
            log.debug("audio probe for %s failed: %s", fname, e)
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    return notes


def heal_video_workflow(workflow: dict, base_url: str) -> List[str]:
    """Universal pre-submit compat pass for VIDEO workflows only (image
    workflows are left untouched). Used by ComfyUIRunner._queue_prompt."""
    if not any(isinstance(n, dict) and n.get("class_type") in _VIDEO_NODE_CLASSES
               for n in workflow.values()):
        return []
    notes = adapt_missing_nodes(workflow, base_url)
    notes += drop_unsafe_audio_links(workflow, base_url)
    notes += heal_loader_names(workflow, base_url, _VIDEO_HEAL_CLASSES)
    return notes


def adapt_missing_nodes(workflow: dict, base_url: str) -> List[str]:
    """Swap node classes the target ComfyUI lacks for installed equivalents.

    Lane6 2026-10-05: builders emit ``RIFE VFI`` (ComfyUI-Frame-Interpolation).
    spark2 does not ship that pack but does ship ComfyUI-GIMM-VFI, so the
    interpolation presets failed /prompt validation ("missing class").
    Rewrites RIFE VFI -> DownloadAndLoadGIMMVFIModel + GIMMVFI_interpolate.
    No-op when RIFE VFI exists or GIMM-VFI is absent. Returns change notes.
    """
    notes: List[str] = []
    if not any(isinstance(n, dict) and n.get("class_type") == "RIFE VFI"
               for n in workflow.values()):
        return notes

    def _has(cls: str) -> Optional[dict]:
        try:
            with urllib.request.urlopen(
                    f"{base_url.rstrip('/')}/object_info/{urllib.parse.quote(cls)}",
                    timeout=15) as r:
                return json.loads(r.read()).get(cls)
        except Exception:  # noqa: BLE001
            return None

    if _has("RIFE VFI"):
        return notes
    loader = _has("DownloadAndLoadGIMMVFIModel")
    interp = _has("GIMMVFI_interpolate")
    if not (loader and interp):
        return notes
    mopts = ((loader.get("input") or {}).get("required") or {}).get("model", [[]])[0]
    model = next((m for m in mopts if "_r_" in m), mopts[0] if mopts else None)
    if not model:
        return notes
    for nid in [k for k, n in workflow.items()
                if isinstance(n, dict) and n.get("class_type") == "RIFE VFI"]:
        node = workflow[nid]
        mult = int(node["inputs"].get("multiplier", 2))
        lid = f"{nid}_gimm_model"
        workflow[lid] = {"class_type": "DownloadAndLoadGIMMVFIModel",
                         "inputs": {"model": model, "precision": "fp16"}}
        # GIMMVFI_interpolate outputs [interpolated IMAGE, flow IMAGE]; slot 0
        # is a drop-in for RIFE VFI's single IMAGE output.
        workflow[nid] = {"class_type": "GIMMVFI_interpolate",
                         "inputs": {"gimmvfi_model": [lid, 0],
                                    "images": node["inputs"]["frames"],
                                    "ds_factor": 1.0,
                                    "interpolation_factor": mult,
                                    "seed": 0}}
        notes.append(f"{nid}: RIFE VFI -> GIMMVFI_interpolate x{mult} ({model})")
    return notes


def build_native_workflow(*args, **kwargs):
    """See _build_native_workflow_impl; adds server-compat node adaptation
    and loader-name healing to every native-built workflow."""
    workflow, err = _build_native_workflow_impl(*args, **kwargs)
    if workflow:
        base = kwargs.get("comfyui_base_url")
        if base:
            try:
                for n in adapt_missing_nodes(workflow, base):
                    log.info("native workflow adapted: %s", n)
            except Exception as e:  # noqa: BLE001
                log.warning("adapt_missing_nodes skipped: %s", e)
    return workflow, err


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
