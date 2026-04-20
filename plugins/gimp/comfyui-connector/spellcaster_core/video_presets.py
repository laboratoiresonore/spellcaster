"""Canonical video-preset detection and tuning for WAN 2.2 + LTX 2.3.

This module is the ONE SOURCE OF TRUTH for:

    1. Auto-detecting WAN / LTX models installed on a ComfyUI server
    2. Pairing the correct VAE to each WAN UNET family (14B I2V vs 5B TI2V)
    3. Picking I2V-safe models (not T2V, not generic — they crash at runtime)
    4. The turbo / full-step parameter formula for WAN
    5. The distilled / full / two-stage / I2V formula for LTX

Every app surface that generates video MUST call these helpers instead of
rolling its own detection or parameter table. Divergent copies caused the
recurring "WAN produces black frames" + "LTX 400 Bad Request" regressions.

See `CLAUDE.md § "Canonical Video Pipelines"` for the full human-readable
recipe and the history of each knob.

Public API
----------
    detect_wan_preset(comfy_url) -> dict | None
    detect_ltx_preset(comfy_url) -> dict | None
    wan_turbo_kwargs(turbo) -> dict
    ltx_mode_kwargs(mode) -> dict

Lower-level helpers (kept public for callers that already own their own
HTTP layer / cache):

    probe_object_info_choices(comfy_url, node, input_name) -> list[str]
    pick_wan_vae(unet_name, vae_list) -> str | None
    pick_wan_accel_loras(lora_list) -> tuple[high, low]
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Optional


# ── ComfyUI /object_info probe ─────────────────────────────────────────────
#
# Every detector in the app used to inline this same urlopen + json.loads
# block. Callers should use this helper instead so we have exactly one place
# to tweak timeout / TLS / error handling.

def probe_object_info_choices(comfy_url: str, node_class: str,
                              input_name: str,
                              *, timeout: float = 10.0) -> list[str]:
    """Return the enum/choice-list for node_class.inputs[input_name].

    ComfyUI's /object_info has used TWO schema shapes over the years:

      Legacy: ["input"]["required"][input_name] = [["a.safetensors", ...], {config}]
              — the enum lives at choices[0], a plain list of strings.

      Modern (2024+): ["input"]["required"][input_name] =
              ["COMBO", {"options": ["a.safetensors", ...], ...}]
              — the enum lives at choices[1]["options"].

    Different nodes return different shapes on the SAME server (ComfyUI's
    node-schema migration is incremental), so we check both.
    """
    try:
        url = f"{comfy_url}/object_info/{node_class}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    choices = (data.get(node_class, {})
                   .get("input", {}).get("required", {})
                   .get(input_name, []))
    if not choices or not isinstance(choices, list):
        return []
    # Legacy shape — first element is the enum list itself.
    if isinstance(choices[0], list):
        return list(choices[0])
    # Modern COMBO shape — second element is a dict with "options".
    if len(choices) >= 2 and isinstance(choices[1], dict):
        opts = choices[1].get("options", [])
        if isinstance(opts, list):
            return list(opts)
    return []


# ══════════════════════════════════════════════════════════════════════════
#  WAN 2.2 — preset detection
# ══════════════════════════════════════════════════════════════════════════
#
# WAN 2.2 ships in three incompatible UNET families. The Spellcaster canon
# is I2V-only because:
#
#   - wan2.2 14B I2V-A14B         patch_embedding = 36 ch input  ← canon
#   - wan2.2 14B T2V-A14B         patch_embedding = 36 ch input  ← rejected
#   - wan2.2 5B TI2V              patch_embedding = 64 ch input  ← usable
#   - Generic "wan" models         unknown channel count         ← rejected
#
# Feeding a T2V model to an I2V workflow crashes with
#   "expected input to have 36 channels, but got 64 channels"
# which is unrecoverable mid-render. We therefore REJECT generic + T2V here
# rather than silently pick them.
#
# The VAE pairing is equally strict:
#   14B I2V-A14B       → wan_2.1_vae.safetensors (16-ch latent)
#   5B TI2V            → wan2.2_vae.safetensors  (48-ch latent)
# Mismatch = channel-count explosion in the first conv layer.

_WAN_VAE_PAIR_14B = ("wan_2.1_vae", "wan2_1_vae", "wan2.1_vae",
                     "wan2_2_vae_14b", "wan2.2_vae_14b")
_WAN_VAE_AVOID_14B = ("wan2.2_vae",)
_WAN_VAE_PAIR_5B   = ("wan2.2_vae", "wan_2.2_vae", "wan2_2_vae")


def _classify_wan_model(name: str) -> dict:
    """Return {is_i2v, is_t2v, is_high, is_low, is_generic} for a filename."""
    ml = name.lower()
    is_i2v = "i2v" in ml
    # RemixT2VI2V ships both markers — we treat it as I2V (canon).
    is_t2v = "t2v" in ml and not is_i2v
    is_low = "low" in ml
    is_high = "high" in ml or (not is_low)
    return {
        "is_i2v": is_i2v, "is_t2v": is_t2v,
        "is_high": is_high and not is_low, "is_low": is_low,
        "is_generic": not (is_i2v or is_t2v),
    }


def pick_wan_vae(unet_name: str, vae_list: list[str]) -> Optional[str]:
    """Return the VAE filename that pairs with `unet_name`, or None.

    The pairing is by UNET family detected from the filename. Callers
    should already have narrowed `vae_list` to the server's installed
    VAEs (from /object_info/VAELoader).
    """
    if not vae_list:
        return None
    unet_l = (unet_name or "").lower()
    is_14b_i2v = ("14b" in unet_l and "i2v" in unet_l)
    is_5b_ti2v = ("5b" in unet_l and "ti2v" in unet_l)
    if is_14b_i2v:
        prefer, avoid = _WAN_VAE_PAIR_14B, _WAN_VAE_AVOID_14B
    elif is_5b_ti2v:
        prefer, avoid = _WAN_VAE_PAIR_5B, ()
    else:
        # Unknown family — fall through to the generic "wan" hunt below.
        prefer, avoid = (), ()
    for pref in prefer:
        for v in vae_list:
            vl = v.lower()
            if pref in vl and not any(a in vl for a in avoid):
                return v
    # Fallback: any "wan" that isn't on the avoid list. Keeps the detector
    # working for exotic WAN VAEs that ship with future model packs.
    for v in vae_list:
        vl = v.lower()
        if "wan" in vl and not any(a in vl for a in avoid):
            return v
    return None


def pick_wan_accel_loras(lora_list: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (high_accel_lora, low_accel_lora) from the server's LoRA list.

    Matches the LightX2V / Lightning / CausVid / *accel* I2V family. T2V
    accel LoRAs are deliberately excluded — they silently distort I2V
    output.

    Accel families we detect (2026-04):
      - LightX2V I2V  : the original 4-step distillation pair
      - Lightning I2V : alternative 4-step distillation
      - CausVid       : temporal-stabilisation LoRA (reduces frame-to-frame
                        flicker, can be stacked with lightx2v/lightning)
      - Generic *accel* : any filename with "accel" token (future-proof)
    """
    high = low = None
    for l in lora_list:
        ll = l.lower()
        if "wan" not in ll:
            continue
        is_wan_accel = (
            ("lightx2v" in ll and "i2v" in ll) or
            ("lightning" in ll and "i2v" in ll) or
            ("causvid" in ll and "i2v" in ll) or
            "causvid" in ll or                  # CausVid filenames don't always include "i2v"
            "accel" in ll
        )
        if not is_wan_accel or "t2v" in ll:
            continue
        if "high" in ll and not high:
            high = l
        elif "low" in ll and not low:
            low = l
    return high, low


def detect_wan_preset(comfy_url: str) -> Optional[dict]:
    """Auto-detect WAN I2V models on a ComfyUI server and return a preset.

    Returns a dict compatible with `workflows.build_wan_video(preset=…)`,
    or None if the server is missing anything required (UNET, CLIP, VAE).

    Canon keys (stable — downstream builders rely on these):

        arch              "wan"
        high_model        I2V-A14B HIGH (or TI2V-5B if that's all that's present)
        low_model         Matching LOW. Falls back to high_model when no low exists.
        clip              umt5xxl / t5xxl text encoder (GGUF preferred)
        clip_is_gguf      True when clip ends in .gguf
        vae               PAIRED to the UNET family (see pick_wan_vae)
        steps, cfg,       Tuned for turbo by default (6/1.0/3). Callers that
        shift, second_step    want full-step should override via wan_turbo_kwargs.
        is_i2v            True when the selected high_model is explicitly I2V.
        high_accel_lora   LightX2V / Lightning I2V HIGH, if installed.
        low_accel_lora    same, LOW.
        accel_strength    1.5 — calibrated default for the above LoRAs.
    """
    # ── Enumerate UNETs from both loaders ────────────────────────────
    unet_models = probe_object_info_choices(comfy_url, "UNETLoader", "unet_name")
    gguf_models = probe_object_info_choices(comfy_url, "UnetLoaderGGUF", "unet_name")
    all_models = unet_models + gguf_models
    if not all_models:
        return None

    # ── Partition by family and pick I2V-only ────────────────────────
    i2v_high = i2v_low = None
    t2v_high = generic_high = None
    for m in all_models:
        if "wan" not in m.lower():
            continue
        cls = _classify_wan_model(m)
        if cls["is_i2v"]:
            if cls["is_high"] and not i2v_high:
                i2v_high = m
            elif cls["is_low"] and not i2v_low:
                i2v_low = m
        elif cls["is_t2v"] and not t2v_high and cls["is_high"]:
            t2v_high = m
        elif cls["is_generic"] and not generic_high and cls["is_high"]:
            generic_high = m

    # STRICT: no T2V / generic fallback. Channel mismatch would crash
    # mid-sampling with an opaque error that's very hard to diagnose.
    wan_high = i2v_high
    wan_low = i2v_low
    if wan_high:
        print(f"  [video_presets] WAN model selection: high={wan_high} (i2v)")
    else:
        if generic_high:
            print(f"  [video_presets] WARNING: generic WAN model {generic_high!r} "
                  "refused — unsafe for I2V (may be T2V internally, 36ch/64ch crash). "
                  "Install wan2.2_i2v_720p_*_noise models for video features.")
        if t2v_high:
            print(f"  [video_presets] WARNING: T2V model {t2v_high!r} refused — "
                  "incompatible with I2V pipeline.")
        return None

    # ── CLIP (umt5xxl) — prefer GGUF, fall back to fp8/safetensors ─
    #
    # GGUF quants are NOT equivalent. Live-test on the user's RTX
    # 5060 Ti proved that `umt5-xxl-encoder-Q3_K_S.gguf` (3-bit)
    # produces degenerate text embeddings that cause WAN to silently
    # decode to pure-black frames — same Kijai or stock UNETs, same
    # wan_2.1_vae, only the CLIP precision changes. Q8_0 produces
    # perfect output; Q5/Q6 untested but likely fine; Q3/Q4 are the
    # "too aggressive" floor. Rank GGUFs by quant quality so we never
    # pick a black-frame-causing aggressive quant when a higher-
    # precision variant is installed.
    def _gguf_quant_rank(name: str) -> int:
        """Higher = more precision. Picked to match llama.cpp's
        k-quant ordering; unknowns land below Q4 so they never
        out-rank a real quant."""
        n = name.lower()
        if "fp16" in n or "f16" in n: return 900
        if "q8" in n:   return 800
        if "q6" in n:   return 700
        if "q5_k_m" in n: return 650
        if "q5" in n:   return 600
        if "q4_k_m" in n: return 450
        if "q4" in n:   return 400
        if "q3" in n:   return 300   # known to break WAN
        if "q2" in n:   return 200
        return 100

    wan_clip: Optional[str] = None
    wan_clip_is_gguf = False
    gguf_clips = probe_object_info_choices(comfy_url, "CLIPLoaderGGUF", "clip_name")
    gguf_candidates = [c for c in gguf_clips
                       if c.endswith(".gguf")
                       and ("umt5" in c.lower() or "t5xxl" in c.lower())]
    if gguf_candidates:
        gguf_candidates.sort(key=_gguf_quant_rank, reverse=True)
        wan_clip = gguf_candidates[0]
        wan_clip_is_gguf = True
        print(f"  [video_presets] WAN CLIP picked (GGUF): {wan_clip} "
              f"(rank={_gguf_quant_rank(wan_clip)}; available: "
              f"{[c for c in gguf_candidates]})")
    if not wan_clip:
        std_clips = probe_object_info_choices(comfy_url, "CLIPLoader", "clip_name")
        # fp8/safetensors fallback — prefer umt5 over t5xxl, full-
        # precision over fp8 when both are present.
        std_candidates = [c for c in std_clips
                          if "umt5" in c.lower() or "t5xxl" in c.lower()]
        def _std_rank(name: str) -> int:
            n = name.lower()
            if "umt5" in n and ("fp16" in n or ".safetensors" in n and "fp8" not in n): return 900
            if "umt5" in n: return 800
            if "t5xxl" in n and "fp16" in n: return 700
            if "t5xxl" in n: return 600
            return 100
        if std_candidates:
            std_candidates.sort(key=_std_rank, reverse=True)
            wan_clip = std_candidates[0]
            print(f"  [video_presets] WAN CLIP picked (safetensors): {wan_clip}")

    # ── VAE — paired by UNET family ──────────────────────────────────
    vae_list = probe_object_info_choices(comfy_url, "VAELoader", "vae_name")
    wan_vae = pick_wan_vae(wan_high, vae_list)
    if wan_vae:
        unet_l = wan_high.lower()
        fam = ("14B I2V" if ("14b" in unet_l and "i2v" in unet_l)
               else "5B TI2V" if ("5b" in unet_l and "ti2v" in unet_l)
               else "generic")
        print(f"  [video_presets] WAN VAE pairing: family={fam} "
              f"unet={wan_high} vae={wan_vae}")

    # ── Acceleration LoRAs ───────────────────────────────────────────
    lora_list = probe_object_info_choices(comfy_url,
                                          "LoraLoaderModelOnly", "lora_name")
    accel_high, accel_low = pick_wan_accel_loras(lora_list)

    if not wan_clip or not wan_vae:
        print(f"  [video_presets] WAN incomplete: clip={wan_clip} vae={wan_vae}")
        return None

    preset: dict[str, Any] = {
        "arch": "wan",
        "high_model": wan_high,
        "low_model": wan_low or wan_high,
        "clip": wan_clip,
        "clip_is_gguf": wan_clip_is_gguf,
        "vae": wan_vae,
        # Canonical TURBO defaults. Non-turbo callers override via
        # wan_turbo_kwargs(turbo=False). See CLAUDE.md for derivation.
        "steps": 6,
        "cfg": 1.0,
        "shift": 8.0,
        "second_step": 3,
        "is_i2v": True,
    }
    if accel_high:
        preset["high_accel_lora"] = accel_high
        preset["accel_strength"] = 1.5
    if accel_low:
        preset["low_accel_lora"] = accel_low

    print(f"  [video_presets] WAN preset built: high={wan_high}, "
          f"low={wan_low or wan_high}")
    return preset


# ══════════════════════════════════════════════════════════════════════════
#  WAN 2.2 — turbo vs full-step formula
# ══════════════════════════════════════════════════════════════════════════
#
# WAN I2V supports two well-tested sampling schedules. The defaults live in
# the preset ABOVE and are TUNED FOR TURBO. Callers that want full-step
# quality must pass the kwargs returned by wan_turbo_kwargs(turbo=False).
#
#   TURBO (fast — calibrated for LightX2V / Lightning 4-step accel LoRAs)
#       steps=6        Matches the 4-step distillation + 2 refinement frames.
#       cfg=1.0        Accel LoRAs are trained CFG-free; any CFG > 1.0 burns.
#       second_step=3  High→low crossover midway through the 6-step chain.
#       LoRA strength=1.5 baked into the preset ("accel_strength").
#       Requires: high_accel_lora + low_accel_lora in the preset.
#
#   FULL-STEP (slow — the reliable path when accel LoRAs are missing or
#              mis-calibrated for a given model/arch combo)
#       steps=30       Classic WAN full-denoise budget.
#       cfg=3.5        Empirical sweet spot for I2V on wan2.2-14B.
#       second_step=15 Crossover at the 50% mark.
#       Accel LoRAs are NOT applied even when present.
#
# The animated-avatar baker defaults to full-step because turbo with the
# shipped LightX2V 4-step LoRAs produced pure-black output on the user's
# RTX 5060 Ti. The SPELLCASTER_WAN_TURBO=1 env var opts back into turbo
# for servers whose model/LoRA combo tolerates it.

def wan_turbo_kwargs(turbo: bool) -> dict:
    """Return the kwargs to pass into build_wan_video for the chosen mode.

    Usage:

        from spellcaster_core import video_presets, workflows
        extra = video_presets.wan_turbo_kwargs(turbo=False)
        wf = workflows.build_wan_video(..., turbo=False, **extra)

    When `turbo=True` we return an empty dict so the preset's turbo-tuned
    defaults (steps=6, cfg=1.0, second_step=3) are used unchanged.
    """
    if turbo:
        return {}
    return {"steps": 30, "cfg": 3.5, "second_step": 15}


# ══════════════════════════════════════════════════════════════════════════
#  LTX 2.3 — preset detection
# ══════════════════════════════════════════════════════════════════════════
#
# LTX 2.3 has a single UNET family (22B dev or 13B). The text encoder is
# Gemma-3, loaded via LTXAVTextEncoderLoader (Kijai's custom pack). VAE
# is a dedicated ltx-video-vae file — DIFFERENT from the WAN VAE family.

def detect_ltx_preset(comfy_url: str) -> Optional[dict]:
    """Auto-detect LTX 2.3 models on ComfyUI and return a preset.

    Returns a dict compatible with `workflows.build_ltx_video(preset=…)`,
    or None if the server is missing anything required.

    Canon keys:

        unet                    LTX 2.3 UNET (GGUF preferred, 22B/13B/2.3 tagged)
        unet_is_gguf            True for .gguf files (dispatched to UnetLoaderGGUF)
        text_encoder            Gemma-3 model name
        embeddings_connector    LTX embeddings connector (Kijai's pack)
        vae                     ltx-video-vae.* (NOT the WAN VAE)
        steps, cfg, stg, rescale    Tuned for full-step (30 / 4.0 / 1.0 / 0.7)
        distilled_lora          Optional LTX distilled LoRA (enables 8-step mode)
    """
    # ── UNET (prefer GGUF, then safetensors, prefer versioned) ────────
    gguf_models = probe_object_info_choices(comfy_url, "UnetLoaderGGUF", "unet_name")
    unet_models = probe_object_info_choices(comfy_url, "UNETLoader", "unet_name")
    all_models = gguf_models + unet_models

    ltx_unet = None
    ltx_unet_fallback = None
    ltx_is_gguf = False
    for m in all_models:
        ml = m.lower()
        if "ltx" not in ml:
            continue
        is_gguf = m.endswith(".gguf")
        # Prefer VERSIONED builds so the user's extra LTX1 checkpoints
        # don't steal the slot.
        if "2.3" in ml or "22b" in ml or "13b" in ml:
            ltx_unet = m
            ltx_is_gguf = is_gguf
            break
        if ltx_unet_fallback is None:
            ltx_unet_fallback = m
            ltx_is_gguf = is_gguf
    if not ltx_unet:
        ltx_unet = ltx_unet_fallback
        if ltx_unet:
            print(f"  [video_presets] LTX: no versioned model, fallback={ltx_unet}")
    if not ltx_unet:
        print("  [video_presets] LTX: no LTX UNET found")
        return None

    # ── Text encoder (Gemma) + embeddings connector ──────────────────
    # LTXAVTextEncoderLoader's real input names are `text_encoder`
    # (which lists Gemma/T5/etc. text-encoder safetensors) and
    # `ckpt_name` (which lists the LTX-specific embeddings connector
    # file from the checkpoints folder). Not `text_encoder_name` /
    # `embeddings_connector_name` — those don't exist on the node and
    # would cause ComfyUI to reject the workflow with "Value not in list"
    # at validation time.
    text_encoder = None
    embeddings_connector = None
    te_choices = probe_object_info_choices(comfy_url,
                                           "LTXAVTextEncoderLoader",
                                           "text_encoder")
    for c in te_choices:
        if "gemma" in c.lower():
            text_encoder = c
            break
    # Connector lives under `ckpt_name` (Checkpoints folder). Pick the
    # LTX-tagged *connector*.safetensors file; avoid picking the LTX
    # video VAE or the audio VAE by matching on "connector" explicitly.
    ec_choices = probe_object_info_choices(comfy_url,
                                           "LTXAVTextEncoderLoader",
                                           "ckpt_name")
    for c in ec_choices:
        cl = c.lower()
        if "ltx" in cl and "connector" in cl:
            embeddings_connector = c
            break

    # Fallback: probe standard CLIP loaders for Gemma when the Kijai
    # LTXAV node isn't installed. The connector path still needs the
    # checkpoints-folder file — without LTXAV we can't build a workflow
    # at all, so returning None is the right failure mode.
    if not text_encoder:
        clip_pool = (probe_object_info_choices(comfy_url, "CLIPLoader", "clip_name")
                     + probe_object_info_choices(comfy_url, "CLIPLoaderGGUF", "clip_name"))
        for c in clip_pool:
            if "gemma" in c.lower():
                text_encoder = c
                break

    # ── LTX VAE (must be the ltx-video family, NOT a WAN VAE) ────────
    ltx_vae = None
    vae_list = probe_object_info_choices(comfy_url, "VAELoader", "vae_name")
    for v in vae_list:
        vl = v.lower()
        if "ltx" in vl and "video" in vl and "vae" in vl:
            ltx_vae = v
            break

    if not text_encoder or not ltx_vae:
        print(f"  [video_presets] LTX found {ltx_unet!r} but missing "
              f"text_encoder={text_encoder!r} or vae={ltx_vae!r}")
        return None

    # ── Distilled LoRA (enables the 8-step fast path) ────────────────
    distilled_lora = None
    for l in probe_object_info_choices(comfy_url,
                                       "LoraLoaderModelOnly", "lora_name"):
        ll = l.lower()
        if "ltx" in ll and "distill" in ll:
            distilled_lora = l
            break

    preset: dict[str, Any] = {
        "unet": ltx_unet,
        "unet_is_gguf": ltx_is_gguf,
        "text_encoder": text_encoder,
        "embeddings_connector": embeddings_connector or "",
        "vae": ltx_vae,
        # Canonical FULL-STEP defaults. Distilled mode overrides inside
        # build_ltx_video when distilled=True.
        "steps": 30,
        "cfg": 4.0,
        "stg": 1.0,
        "rescale": 0.7,
    }
    if distilled_lora:
        preset["distilled_lora"] = distilled_lora

    print(f"  [video_presets] LTX preset built: unet={ltx_unet}")
    return preset


# ══════════════════════════════════════════════════════════════════════════
#  LTX 2.3 — mode formula
# ══════════════════════════════════════════════════════════════════════════
#
# LTX ships four well-tested modes. build_ltx_video takes the kwargs
# (distilled, two_stage, image_filename) and derives the rest. This helper
# returns the canonical kwargs for a human-readable mode string so the
# Guild / GIMP plugin / Resolve bridge can all pass the same thing.

_LTX_MODES = {
    # 8-step LoRA-accelerated (preferred default for iteration)
    "distilled": {"distilled": True, "two_stage": False},
    # Full 30-step single-pass (quality > speed)
    "full":      {"distilled": False, "two_stage": False},
    # Half-res → 2x latent upscale → refine (beauty pass)
    "two_stage": {"distilled": False, "two_stage": True},
    # 8-step I2V (caller supplies image_filename separately)
    "i2v":       {"distilled": True, "two_stage": False},
}


def ltx_mode_kwargs(mode: str) -> dict:
    """Return the build_ltx_video kwargs for a named LTX mode.

    Known modes: "distilled", "full", "two_stage", "i2v". Unknown modes
    default to "distilled" (the safe fast path).
    """
    return dict(_LTX_MODES.get(mode, _LTX_MODES["distilled"]))
