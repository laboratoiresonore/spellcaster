# Canonical Video Pipelines — WAN 2.2 + LTX 2.3

This document is **the canon** for every WAN / LTX video generation in Spellcaster. The recipe below produced the "perfect" LTX gen and the restored WAN I2V on the user's RTX 5060 Ti. **Do not diverge. Do not re-invent.**

The detection / tuning / dispatch used to live in five separate modules with gradually drifting copies; we consolidated them so anything new goes through `spellcaster_core.video_presets`.

## Single source of truth

| Concern | Canonical API | Lives in |
|---|---|---|
| Detect WAN models on a ComfyUI server | `video_presets.detect_wan_preset(comfy_url)` | `spellcaster_core/video_presets.py` |
| Detect LTX models on a ComfyUI server | `video_presets.detect_ltx_preset(comfy_url)` | same |
| WAN turbo vs full-step params | `video_presets.wan_turbo_kwargs(turbo=bool)` | same |
| LTX mode params (distilled / full / two_stage / i2v) | `video_presets.ltx_mode_kwargs(mode)` | same |
| Build WAN workflow | `workflows.build_wan_video(preset, **kwargs, **wan_turbo_kwargs(turbo))` | `spellcaster_core/workflows.py` |
| Build LTX workflow | `workflows.build_ltx_video(preset, **ltx_mode_kwargs(mode), ...)` | same |

**Every consumer imports these functions.** No `_detect_wan_preset` / `_detect_ltx_preset` copies in `tavern/server.py`, `scaffold/video_workflow_dispatch.py`, `spellcaster_core/pipeline.py`, plugins, or anywhere else. If a consumer needs the result cached, the cache wraps `detect_wan_preset()` — the detection itself stays canonical.

## WAN 2.2 — full formula

### Model family selection (I2V ONLY — the other families crash)

| Family | Filename tags | Channels | Action |
|---|---|---|---|
| WAN 2.2 14B I2V-A14B | `wan…14b…i2v` | patch_embedding 36ch | ✅ Use for Spellcaster |
| WAN 2.2 14B T2V-A14B | `wan…14b…t2v` | patch_embedding 36ch | ❌ Refuse (T2V workflow only) |
| WAN 2.2 5B TI2V       | `wan…5b…ti2v` | patch_embedding 64ch | ✅ Usable (different VAE pair) |
| Generic "wan"         | no i2v/t2v tag | unknown             | ❌ Refuse (may crash 36/64 ch mismatch) |

Feeding a T2V model into an I2V workflow crashes with
`expected input to have 36 channels, but got 64 channels` mid-sampling.
`detect_wan_preset` refuses generic/T2V and logs a warning.

### VAE pairing (must match UNET family)

| UNET family | VAE (prefer) | Avoid |
|---|---|---|
| 14B I2V-A14B | `wan_2.1_vae.safetensors` / `wan2_1_vae.safetensors` / `wan2.2_vae_14b.*` | `wan2.2_vae.safetensors` (the TI2V-5B VAE — crashes on 14B) |
| 5B TI2V     | `wan2.2_vae.safetensors`                                                   | (none) |

`pick_wan_vae(unet_name, vae_list)` encodes this. Any other pairing burns the first conv layer at runtime.

### CLIP (text encoder)

- Prefer GGUF umt5xxl / t5xxl via `CLIPLoaderGGUF`.
- Fall back to fp8/safetensors via `CLIPLoader` only when no GGUF match.
- Both are wan-type CLIPs; never substitute a Flux or SD clip.

### Acceleration LoRAs (HIGH + LOW pair)

- LightX2V I2V or Lightning I2V, split by "high" / "low" in filename.
- T2V accel LoRAs are REJECTED — silently distort I2V output.
- Stored on the preset as `high_accel_lora` + `low_accel_lora` + `accel_strength=1.5`.

### Turbo vs full-step — the formula

| Param | TURBO (`turbo=True`) | FULL-STEP (`turbo=False`) |
|---|---|---|
| steps | 6 | 30 |
| cfg | 1.0 | 3.5 |
| second_step (high→low crossover) | 3 | 15 |
| Accel LoRAs applied? | Yes (when present) | No (ignored even if present) |
| Default in animated-avatar baker | ❌ (produces black frames on user's box) | ✅ |
| Opt-in via env | `SPELLCASTER_WAN_TURBO=1` | (default) |

Turbo targets the LightX2V / Lightning 4-step distillation. On the user's RTX 5060 Ti, the shipped 4-step LoRAs + `cfg=1.0` produced pure-black output (mean luminance 0.0/255). Full-step is the reliable default; turbo is an opt-in escape hatch for servers whose model/LoRA combo tolerates it. The formula lives in `video_presets.wan_turbo_kwargs(turbo)` — every WAN caller passes its result as `**kwargs` into `build_wan_video`.

### LoRA injection (high/low split)

- `loras_high` → applied to the HIGH noise model (frames 0..second_step-1).
- `loras_low`  → applied to the LOW  noise model (frames second_step..end).
- Both lists live in the preset OR are passed explicitly.
- `inject_lora_chain` is NOT used for WAN — the builder calls `nf.lora_loader_model_only` directly so arch-filter logic doesn't drop WAN-specific LoRAs.

### Pixel dimensions

- Width + height MUST be multiples of 16. `build_wan_video` does NOT re-round; callers pre-round via `round_to_mod(16)`.
- The 512×512 avatar baker + the 832×480 / 1280×720 shot presets are all mod-16 clean.

### Known-good presets

- Animated avatars (Guild): 512×512 · 33 frames · fps=16 · pingpong=True · turbo=False.
- Shotboard I2V default: 832×480 · 81 frames · fps=16 · turbo=True (lightning preset).
- Shotboard I2V HQ: 1280×720 · 81 frames · fps=16 · turbo=False.

## LTX 2.3 — full formula

### Model family

- One UNET family (22B dev or 13B). Prefer filenames tagged `2.3` / `22b` / `13b`. `.gguf` is auto-dispatched to `UnetLoaderGGUF`; `.safetensors` goes to `UNETLoader`.
- Text encoder: Gemma-3. Detection tries `LTXAVTextEncoderLoader` first (Kijai's custom pack) then falls back to standard `CLIPLoader` / `CLIPLoaderGGUF` Gemma checkpoints.
- Embeddings connector: `ltx*connector*` via the same loaders. Last-resort filename `LTX\ltx-2.3-22b-dev_embeddings_connectors.safetensors`.
- VAE: `ltx-video-vae.*`. **NOT** the WAN VAE. Using a WAN VAE produces green/yellow noise.
- Distilled LoRA: `ltx*distill*` — enables the 8-step fast path.

### Mode formula

| Mode | distilled | two_stage | steps | cfg | stg | rescale | Notes |
|---|---|---|---|---|---|---|---|
| `distilled` | True | False | 8 (auto) | 1.0 (auto) | 0.0 (auto) | 0.0 (auto) | Default fast path — 4× faster than full |
| `full` | False | False | 30 | 4.0 | 1.0 | 0.7 | Quality > speed |
| `two_stage` | False | True | 30 | 4.0 | 1.0 | 0.7 | Gen at half-res → 2× latent upscale → refine |
| `i2v` | True | False | 8 (auto) | 1.0 (auto) | 0.0 (auto) | 0.0 (auto) | Caller also passes `image_filename` + `i2v_strength` |

Use `ltx_mode_kwargs("distilled")` / `("full")` / `("two_stage")` / `("i2v")` — returns the right `{distilled, two_stage}` kwargs for `build_ltx_video`.

### Default subtitle-burn-in negative (auto-injected when `negative_text is None`)

```
text, subtitles, captions, watermark, logo, timestamp, UI, interface,
closed captions, overlay, written letters, typography
```

LTX 2.3's distilled corpus includes subtitled video, so without this the model reproduces subtitles. Callers that want a custom negative pass it verbatim.

### VRAM optimisation (canonical defaults, all overridable)

- `LTXVChunkFeedForward` with `chunks=4` on every LTX workflow. Override via `build_ltx_video(chunk_size=...)`.
- `LTXVApplySTG` on layers `"14, 19"` (Spatial-Temporal Guidance). Override via `build_ltx_video(stg_layers="14, 19, 22")`.
- `LTXVSpatioTemporalTiledVAEDecode` with `spatial_tiles=4`, `temporal_tile_length=16`, `last_frame_fix=False`, `working_dtype="auto"`. Override via `build_ltx_video(vae_spatial_tiles=..., vae_temporal_tile_length=..., vae_last_frame_fix=..., vae_working_dtype=...)`.
- Removing the chunk or STG nodes tanks quality; re-tune the parameters instead.

### Optional quality + speed patches (auto-probed by the GIMP LTX dialog)

| Patch | Node class | Gain | Pack |
|---|---|---|---|
| SAGE — Sage Attention | `PatchSageAttentionKJ` | 50–100% sampler speedup on RTX 40/50xx, neutral quality. Injected BEFORE `LTXVChunkFeedForward` so the whole chain uses the kernel. | KJNodes |
| CFG Zero Star | `CFGZeroStar` | Small quality win (no CFG on step 0). Auto-skipped in distilled mode (cfg=1.0). | Core ComfyUI (recent) |

TeaCache / SLG / NAG do **not** apply to LTX — different sampler path (`LTXVBaseSampler` + `STGGuider`, not Wan's `KSamplerAdvanced`).

### Sampler override

`build_ltx_video(sampler_name=...)` accepts per-call overrides (default `"euler"`). Full-step runs can try `dpmpp_2m_sde` or `heun`; distilled mode is tuned for euler and usually regresses on other samplers.

### Extra LoRAs

`build_ltx_video(loras=[(name, strength), ...])` accepts arbitrary LoRAs applied AFTER the distilled LoRA. GIMP dialog exposes 3 slots + strength spinners + a server-LoRA fetch button.

### Canonical builder signature — the full kwargs surface

```python
build_ltx_video(
    preset, prompt_text, seed,                         # required
    width=768, height=512, num_frames=25,              # geometry
    steps=None, cfg=None, stg=None, rescale=None,      # sampling (None → preset default)
    two_stage=False, distilled=False,                  # mode (pair with ltx_mode_kwargs)
    loras=None, interpolate=False, rtx_scale=0,        # post-processing
    fps=25, pingpong=False,                            # output
    image_filename=None, i2v_strength=0.9,             # I2V conditioning
    negative_text=None,                                # None → auto subtitle blocker
    enable_sage=False, enable_cfg_zero=False,          # optional patches
    sampler_name=None, stg_layers=None, chunk_size=None,         # tuning
    vae_spatial_tiles=None, vae_temporal_tile_length=None,       # VAE tiling
    vae_last_frame_fix=False, vae_working_dtype=None,            # VAE dtype/fix
)
```

## Boundary rules

1. **No parallel detection.** If you see `_detect_wan_preset` / `_detect_ltx_preset` anywhere outside `spellcaster_core/video_presets.py`, it must be a thin wrapper that imports the canonical one. Same for WAN VAE pairing and turbo kwargs.
2. **No parallel turbo formula.** Every `build_wan_video(…, turbo=…)` call must pair with `**video_presets.wan_turbo_kwargs(turbo)` OR the caller has a comment explaining why it deviates.
3. **Preset fields are additive only.** `detect_wan_preset` returns a stable dict shape; code downstream reads by key. Don't rename keys — extend.
4. **Plugin path:** GIMP / Resolve / Darktable plugins call `build_wan_video` + `build_ltx_video` via `spellcaster_core.workflows`, using the detection helpers in `video_presets`. They NEVER hand-roll WAN/LTX workflow JSON.
5. **Arch filter does not touch WAN/LTX LoRAs.** The cross-family LoRA filter in `composites.inject_lora_chain` doesn't run on video — video builders call `lora_loader_model_only` directly so WAN-specific LoRAs aren't dropped.
6. **Caller overrides win over preset hints.** In the scaffold dispatcher's LTX branch, caller-supplied `interpolate` / `rtx_scale` / `steps` / `cfg` / `stg` / `rescale` / `i2v_strength` / `sampler_name` / `stg_layers` / `chunk_size` / `enable_sage` / `enable_cfg_zero` / `vae_*` / `extra_loras` override `_LTX2_PRESET_HINTS` defaults. Hints are a floor, not a ceiling — a client asking for RIFE interpolation on `ltx2_distilled` gets it even though the hint defaults `interpolate=False`.
7. **Fluent pipeline DSL accepts the full canon surface.** `Pipeline().ltx_video(...)` exposes every optional kwarg the builder supports. `_run_ltx` forwards them all; unset kwargs stay None so canon defaults ride through.

## Known divergences (tech debt)

| File | Status | Notes |
|---|---|---|
| `plugins/darktable/comfyui_connector.lua` | ⚠ HAND-ROLLED WORKFLOW | Build hand-rolls WAN JSON because Lua can't `import spellcaster_core`. When touching, cross-check every value against this doc. Long-term fix: POST to `/api/video/shots` like the Resolve/SillyTavern plugins. |

Every other consumer goes through `spellcaster_core.video_presets` + `spellcaster_core.workflows`.
