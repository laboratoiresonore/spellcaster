# Spellcaster — Canonical Rules Reference

**Last reviewed:** 2026-05-01
**Lifted from:** previous monolithic `CLAUDE.md` (sections 8, 16, 19–31) during the cycle-3 7-section migration.
**Status:** reference for callers / extenders. The HARD RULES that still gate every session live in `CLAUDE.md` §2; this file is the technical canon they depend on.

When editing canon: keep the rule in `CLAUDE.md`, update the reference here, mirror across the six `spellcaster_core/` surfaces (`CLAUDE.md` §2 R1).

---

## A. Klein / Flux 2 enhancer node names (was §8)

ComfyUI class_type names verified against `/object_info`. Pack:
[capitan01R/ComfyUI-Flux2Klein-Enhancer](https://github.com/capitan01R/ComfyUI-Flux2Klein-Enhancer) v3.2.0+. **Always re-verify against the live server before committing a new builder.**

**Classic enhancer chain** (every Klein builder with `enhance=True` wires these):
- `Flux2KleinRefLatentController` — per-reference strength; MODEL + CONDITIONING → (MODEL, CONDITIONING). strength 0.0–1000.0, default 1.0
- `Flux2KleinTextRefBalance` — balance slider; MODEL + CONDITIONING → (MODEL, CONDITIONING). 0.0=ref-only, 0.5=balanced, 1.0=text-only
- `Flux2KleinColorAnchor` — fixes Klein's warm/red drift; MODEL + CONDITIONING → MODEL
- `Flux2KleinRefLatentWeight` — per-reference k/v scaler; MODEL → MODEL
- `Flux2KleinMaskRefController` — **CONDITIONING + MASK (NOT model)** → CONDITIONING. Spatial mask control over the reference latent — NOT inpainting

**Text enhancement** (wraps positive conditioning before sampler):
- `Flux2KleinEnhancer`, `Flux2KleinTextEnhancer`, `Flux2KleinDetailController`, `Flux2KleinSectionedEncoder`

**Identity control (pack v3.2.0 — "better face-swap")** — bypass conditioning, lock identity:
- `IdentityGuidance` — MODEL + LATENT(identity) → MODEL. `strength=0.3`, `mode=adaptive|direct|channel_match`, `start_percent=0.0`, `end_percent=0.8`
- `IdentityFeatureTransfer` — MODEL → MODEL. `strength=0.15`, `mode=cosine_pull|topk_replace|mean_transfer`. Requires a ReferenceLatent on the conditioning path.
- `IdentityFeatureTransferAdvanced` — per-band strength, `sim_floor=0.20`, `block_schedule`. Preflight before use.

**Integration points (2026-04-24):**
- `spellcaster_core.workflows._klein_enhance_model(..., identity_latent_ref=...)` appends IdentityGuidance + IdentityFeatureTransfer after the classic chain when an `identity_latent_ref` is supplied. Knobs: `identity_strength=0.3`, `identity_mode="adaptive"`, `identity_feature_strength=0.15`, `identity_feature_mode="cosine_pull"`.
- `build_klein_headswap(..., use_identity_lock=True)` is the **new default** — Klein + ReferenceLatent(source) + IdentityGuidance(source_latent) + IdentityFeatureTransfer. Skips ReActor, no TensorRT, no §B.1 native-crash risk. `use_identity_lock=False` OR a `face_model` kwarg falls back to the legacy ReActor path.
- `build_klein_img2img_ref(..., identity_lock=True)` opt-in lock against the reference image. Default False preserves style-transfer semantics.
- `_faceswap_guard` (§B.1) still fires on Klein face/head-swap entries — effectively a safety net on the legacy ReActor branch.

---

## B. Resilience — faceswap auto-recovery & preflight status (was §20)

Two independent layers landed in 2026-04.

### B.1 Faceswap auto-recovering guard (`faceswap_health.py`)

ReActor + comfy-mtb load `inswapper_128.onnx` via ONNX Runtime + TensorRT. When `nvinfer_builder_resource_*.dll` fails to load, the native path crashes ComfyUI with a Windows access violation (Python can't catch it).

The guard wraps every face-swap builder in `workflows.py` (`build_faceswap`, `build_faceswap_model`, `build_faceswap_mtb`, `build_face_restore`, `build_klein_headswap`, `build_photobooth`) via `_faceswap_guard(feature)`. State machine:

- **AUTO_ON** (default) — guard passes; `record_dispatch()` stamps `last_dispatch_ts`.
- **Heartbeat** (`tavern/server.py` boot) — daemon thread pings ComfyUI `/system_stats` every 15 s, calls `record_probe(ok)`.
- **Attribution** — `record_probe(False)` within 60 s of a dispatch flips `auto_disabled=True`. Next face-swap build raises `FaceswapDisabledError`.
- **Recovery** — 30 min continuous reachability + automatic disable + no escalation → flips back automatically.
- **Escalation** — `CRASH_ESCALATION_COUNT` (3) attributed crashes stops auto-recovery. User must `POST /api/spellcaster/faceswap/reset` or set `faceswap_force_enable: true`.
- **Persistence** — `set_persist_path(<state_dir>/faceswap_state.json)` survives Guild auto-updates.

**User overrides** (highest precedence first):
- `SPELLCASTER_FACESWAP_DISABLED=1` env var → forced off.
- `faceswap_disabled: true` in `guild_config.json` → forced off.
- `faceswap_force_enable: true` in `guild_config.json` → bypasses auto-disable.

**Endpoints:** `GET /api/spellcaster/faceswap/health`, `POST /api/spellcaster/faceswap/reset`.

Calibration / Shootouts / Preflight do NOT use face-swap nodes (verified 2026-04-20). Guard is strictly for face/head-swap / photobooth.

### B.2 Preflight status dot (`preflight_status.py`)

Traffic light left of ✧ Calibration in `chat-shootout-slot`. Aggregates:
- ComfyUI `/system_stats` reachability
- Faceswap `get_effective_state()` (red on escalated, yellow on auto_off)
- Scorer `probe_available()` (yellow when offline)
- Per-arch render canaries cached in `<state_dir>/preflight_cache.json` (red on failure, yellow when stale > 24 h, green when fresh + passing)

Colour rules in `_classify_overall()`; first matching rule wins.

**Install-flow trigger** — end of `_setup_flow` spawns a daemon that runs `run_full_preflight(COMFYUI_URL, _preflight_arch_probe, models)` (one minimal render per unique installed arch, skip video). Cached to disk; dot picks it up on next 60 s poll.

**Endpoints:** `GET /api/spellcaster/preflight/status`, `POST /api/spellcaster/preflight/run`.

---

## C. Canonical video pipelines — WAN 2.2 + LTX 2.3 (was §16)

This is the **canon** for every WAN / LTX generation. The recipe below produced the "perfect" LTX gen and the restored WAN I2V on the dev RTX 5060 Ti. **Do not diverge. Do not re-invent.**

### C.1 Single source of truth

| Concern | Canonical API | Lives in |
|---|---|---|
| Detect WAN models | `video_presets.detect_wan_preset(comfy_url)` | `spellcaster_core/video_presets.py` |
| Detect LTX models | `video_presets.detect_ltx_preset(comfy_url)` | same |
| WAN turbo vs full-step params | `video_presets.wan_turbo_kwargs(turbo=bool)` | same |
| LTX mode params (distilled / full / two_stage / i2v) | `video_presets.ltx_mode_kwargs(mode)` | same |
| Build WAN workflow | `workflows.build_wan_video(preset, **kwargs, **wan_turbo_kwargs(turbo))` | `spellcaster_core/workflows.py` |
| Build LTX workflow | `workflows.build_ltx_video(preset, **ltx_mode_kwargs(mode), ...)` | same |

Every consumer imports these. No `_detect_wan_preset` / `_detect_ltx_preset` copies anywhere. Cache wraps `detect_wan_preset()` — detection itself stays canonical.

### C.2 WAN 2.2 — full formula

**Model family selection (I2V ONLY — others crash):**

| Family | Filename tags | Channels | Action |
|---|---|---|---|
| WAN 2.2 14B I2V-A14B | `wan…14b…i2v` | 36 ch | ✅ Use |
| WAN 2.2 14B T2V-A14B | `wan…14b…t2v` | 36 ch | ❌ Refuse (T2V workflow only) |
| WAN 2.2 5B TI2V       | `wan…5b…ti2v` | 64 ch | ✅ Usable (different VAE pair) |
| Generic "wan"         | no tag | unknown | ❌ Refuse (36/64 ch mismatch crash) |

T2V into I2V workflow → `expected input to have 36 channels, but got 64`. `detect_wan_preset` refuses generic/T2V.

**VAE pairing** — `pick_wan_vae(unet_name, vae_list)`:
- 14B I2V → `wan_2.1_vae.safetensors` / `wan2_1_vae.safetensors` / `wan2.2_vae_14b.*`. Avoid `wan2.2_vae.safetensors` (TI2V-5B VAE crashes 14B).
- 5B TI2V → `wan2.2_vae.safetensors`.

Other pairings burn the first conv layer at runtime.

**CLIP** — prefer GGUF umt5xxl/t5xxl via `CLIPLoaderGGUF`; fp8/safetensors via `CLIPLoader` only as fallback. Both are wan-type CLIPs; never substitute Flux/SD CLIP.

**Acceleration LoRAs (HIGH + LOW pair):**
- LightX2V I2V or Lightning I2V, split by "high"/"low" in filename.
- T2V accel LoRAs are REJECTED — silently distort I2V output.
- Stored on preset as `high_accel_lora` + `low_accel_lora` + `accel_strength=1.5`.

**Turbo vs full-step:**

| Param | TURBO (`turbo=True`) | FULL-STEP (`turbo=False`) |
|---|---|---|
| steps | 6 | 30 |
| cfg | 1.0 | 3.5 |
| second_step (high→low crossover) | 3 | 15 |
| Accel LoRAs applied? | Yes (when present) | No (ignored even if present) |
| Default in animated-avatar baker | ❌ (black frames on dev box) | ✅ |
| Opt-in env | `SPELLCASTER_WAN_TURBO=1` | (default) |

Turbo targets LightX2V/Lightning 4-step distillation. On RTX 5060 Ti, shipped 4-step LoRAs + cfg=1.0 produced pure-black output. Full-step is the reliable default. Formula lives in `wan_turbo_kwargs(turbo)`.

**LoRA injection (high/low split):**
- `loras_high` → HIGH noise model (frames 0..second_step-1).
- `loras_low`  → LOW  noise model (frames second_step..end).
- `inject_lora_chain` is NOT used for WAN — builder calls `nf.lora_loader_model_only` directly so arch-filter doesn't drop WAN LoRAs.

**Pixel dimensions** — width + height MUST be multiples of 16. `build_wan_video` does NOT re-round; callers pre-round via `round_to_mod(16)`.

**Known-good presets:**
- Animated avatars (Guild): 512×512 · 33 frames · fps=16 · pingpong=True · turbo=False.
- Shotboard I2V default: 832×480 · 81 frames · fps=16 · turbo=True (lightning preset).
- Shotboard I2V HQ: 1280×720 · 81 frames · fps=16 · turbo=False.

**Optional quality + speed patches** (auto-probed by GIMP wrapper via `/object_info`):

| Patch | Node class | Gain | Pack |
|---|---|---|---|
| SLG — Skip Layer Guidance | `SkipLayerGuidanceSD3` | Cleaner motion | Core |
| NAG — Normalized Attention Guidance | `WanVideoNAG` | Sharper motion, less drift | Kijai WanVideoWrapper |
| SAGE — Sage Attention | `PatchSageAttentionKJ` | **50–100 % sampler speedup** RTX 40/50xx | KJNodes |
| CFG Zero Star | `CFGZeroStar` | Small quality win | Core (recent) |

**Auto-TeaCache** — `teacache=None` resolves to `True` for full-step (saves 30–40 % on 30-step), `False` for turbo. Explicit overrides ride through.

**CausVid** — `pick_wan_accel_loras` matches CausVid family (frame-to-frame flicker reduction). Stacks cleanly with lightx2v/lightning.

**Sampler override** — `build_wan_video(sampler_name=..., scheduler=...)` accepts per-call overrides (default `euler`/`simple`).

### C.3 LTX 2.3 — full formula

**Model family** — one UNET family (22B dev or 13B). `.gguf` → `UnetLoaderGGUF`; `.safetensors` → `UNETLoader`. Text encoder: Gemma-3 via `LTXAVTextEncoderLoader` (Kijai pack). Embeddings connector: `ltx*connector*` via same loader. VAE: `ltx-video-vae.*` (NOT WAN VAE — green/yellow noise). Distilled LoRA: `ltx*distill*` enables 8-step fast path.

**Mode formula:**

| Mode | distilled | two_stage | steps | cfg | stg | rescale | Notes |
|---|---|---|---|---|---|---|---|
| `distilled` | True | False | 8 (auto) | 1.0 (auto) | 0.0 (auto) | 0.0 (auto) | Default fast path — 4× faster |
| `full` | False | False | 30 | 4.0 | 1.0 | 0.7 | Quality > speed |
| `two_stage` | False | True | 30 | 4.0 | 1.0 | 0.7 | half-res → 2× latent upscale → refine |
| `i2v` | True | False | 8 (auto) | 1.0 (auto) | 0.0 (auto) | 0.0 (auto) | Caller passes `image_filename` + `i2v_strength` |

Use `ltx_mode_kwargs("distilled" | "full" | "two_stage" | "i2v")`.

**Default subtitle-burn-in negative** (auto-injected when negative_text is None):
```
text, subtitles, captions, watermark, logo, timestamp, UI, interface,
closed captions, overlay, written letters, typography
```
LTX 2.3's distilled corpus includes subtitled video — without this, the model reproduces subtitles.

**VRAM optimisation:**
- `LTXVChunkFeedForward` with `chunks=4` on every LTX workflow (override via `chunk_size=...`).
- `LTXVApplySTG` on layers `14, 19` (override via `stg_layers="14, 19, 22"`).
- Both core to canon; removing either tanks quality.

**Optional patches** (auto-probed by GIMP LTX dialog):

| Patch | Node class | Gain |
|---|---|---|
| SAGE — Sage Attention | `PatchSageAttentionKJ` | 50–100 % speedup, applied BEFORE `LTXVChunkFeedForward` |
| CFG Zero Star | `CFGZeroStar` | Small win; auto-skipped in distilled (cfg=1.0) |

TeaCache / SLG / NAG do **not** apply to LTX (uses `LTXVBaseSampler` + `STGGuider`, different sampler path).

**VAE decode tiling** — `LTXVSpatioTemporalTiledVAEDecode` parameterised via `build_ltx_video(vae_spatial_tiles=..., vae_temporal_tile_length=..., vae_last_frame_fix=..., vae_working_dtype=...)`. Canon defaults: `spatial_tiles=4`, `temporal_tile_length=16`, `last_frame_fix=False`, `working_dtype="auto"`. Low-VRAM raise spatial tiles to 6–8; RTX 50xx hitting garbled last frames set `last_frame_fix=True` or `working_dtype="bf16"`.

**Extra LoRAs** — `build_ltx_video(loras=[("style/cinematic_v2.safetensors", 0.8), ...])` — list of (name, strength) tuples applied AFTER the distilled LoRA.

**Builder signature — full kwargs (29 args):**
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
    sampler_name=None, stg_layers=None, chunk_size=None,
    vae_spatial_tiles=None, vae_temporal_tile_length=None,
    vae_last_frame_fix=False, vae_working_dtype=None,
)
```

Every live caller is audited against this surface — see §C.6.

### C.4 Boundary rules

1. **No parallel detection.** `_detect_wan_preset` / `_detect_ltx_preset` outside `spellcaster_core/video_presets.py` → delete + import canonical.
2. **No parallel turbo formula.** Every `build_wan_video(…, turbo=…)` call pairs with `**video_presets.wan_turbo_kwargs(turbo)` OR has a comment explaining the deviation.
3. **Preset fields are additive only.** `detect_wan_preset` returns a stable dict shape; downstream reads by key. Don't rename — extend.
4. **Plugin path:** Python plugins (GIMP, Resolve scripts) call `build_wan_video` + `build_ltx_video` directly. Lua/JS/remote (Darktable, SillyTavern) POST to Guild's `/api/video/shots`. No plugin hand-rolls workflow JSON.
5. **Arch filter does not touch WAN/LTX LoRAs.** Video builders call `lora_loader_model_only` directly.
6. **Caller overrides win over preset hints.** Scaffold dispatcher's LTX branch lets caller `interpolate` / `rtx_scale` / `steps` / `cfg` / etc. override `_LTX2_PRESET_HINTS`. Hints are a floor, not a ceiling.
7. **Fluent pipeline DSL accepts the full canon surface.** `Pipeline().ltx_video(...)` exposes every optional kwarg.

### C.5 Canon verification — `tests/e2e_audit.py`

```bash
PYTHONIOENCODING=utf-8 python tests/e2e_audit.py --only video --verbose
PYTHONIOENCODING=utf-8 python tests/e2e_audit.py --only build_fns --verbose
```

Video canon section asserts:
- `wan_turbo_kwargs(True)` returns `{}`; `(False)` returns `{steps:30, cfg:3.5, second_step:15}`.
- `ltx_mode_kwargs(mode)` returns the right `{distilled, two_stage}` for every mode.
- `pick_wan_vae` pairs 14B I2V → `wan_2.1_vae.safetensors`, 5B TI2V → `wan2.2_vae.safetensors`.
- `detect_wan_preset(live_server)` returns I2V-safe preset (< ~200 ms).
- `detect_ltx_preset(live_server)` returns 22B/13B preset with Gemma encoder.

Build-fns section compiles every `build_*` and POSTs to ComfyUI's `/prompt`. Expected green: `54 PASS / 0 FAIL / N SKIP`.

### C.6 Where every WAN / LTX call lands

**WAN 2.2 call paths:** GIMP UI → `_build_wan_video` wrapper → canonical `build_wan_video`. Wizard Guild API → `_VIDEO_BRIDGE.add_shot` → scaffold dispatcher (applies `wan_turbo_kwargs`). SillyTavern, Resolve, Darktable Lua → `POST /api/video/shots`. `Pipeline().wan_video()` → `_run_wan` → `detect_wan_preset()` + `wan_turbo_kwargs()` + canonical builder. Live diagnostic (`diagnostic._build_wan_test`) probes server with canon. `tools/generate_*.py` use detection + canonical builder.

**LTX 2.3 call paths — all audited against the 29-kwarg canon (2026-04-20):**

| # | Caller | Coverage |
|---|---|---|
| 1 | GIMP LTX button (T2V / I2V) | All 26 optional kwargs via dialog widgets |
| 2 | Guild avatar baker (`_queue_animated_avatar`) | Fixed 512×512×25 I2V; auto-probes SAGE + CFG Zero. Canon defaults by design |
| 3 | Guild I2V retry path (`_retry_anim_as_ltx`) | Same as #2 |
| 4 | Wizard Guild API consumers (`POST /api/video/shots`) | Bridge reads 16 LTX keys from `overrides`; dispatcher spreads via `**extra` |
| 5 | SillyTavern plugin | Same chain as #4 |
| 6 | DaVinci Resolve plugin | Same chain as #4 |
| 7 | Darktable Lua plugin | Same chain as #4; UI exposes mode + scene template + advanced patches |
| 8 | `Pipeline().ltx_video(...)` | All 20+ optional kwargs forwarded via `_run_ltx` |
| 9 | Live diagnostic (`_build_ltx_test`) | Minimal (5 kwargs) — intentional probe test |

**Receivers verified (2026-04-20):** `scaffold/video_bridge.py::queue_shot()` reads 16 LTX override keys; `scaffold/video_workflow_dispatch.py::build_native_workflow()` LTX branch spreads all 16 via `**extra`; `tavern/server.py::_ltx_server_opts(comfy_url)` auto-probes SAGE + CFG Zero; GIMP `_build_ltx_video` wrapper auto-probes via `_ltx_quality_patches_available(server)`.

If you see a new caller that doesn't fit one of these, it's a canon violation in the making — route through one of the above.

### C.7 Global quality mode — the ⚡ / ⚖️ / 💎 toggle

Wizard Guild's global preset button cycles through three session-scoped quality modes that every WAN + LTX workflow respects:

| Mode | Icon | WAN effect | LTX effect |
|---|---|---|---|
| `turbo` | ⚡ | `turbo=True` (6 steps + lightning LoRAs, cfg 1.0) | `distilled=True` (8-step fast path) |
| `standard` | ⚖️ | `turbo=False` (30/3.5/15 full-step, no accel) | `distilled=False, two_stage=False` (30-step full) |
| `quality` | 💎 | `turbo=False` + auto-swap `wan22_i2v_lightning` → `wan22_i2v_hq` | auto-swap to `ltx2_text_to_video_2stage` |

State in `tavern/server.py::_GUILD_VIDEO_MODE` — module-level string, NOT persisted. Resets to `"turbo"` on Guild restart. Client localStorage caches choice + POSTs on page load.

**Endpoints:** `GET /api/video/quality-mode`, `POST /api/video/quality-mode {mode: ...}`.

**Remap helper** (`_apply_quality_mode`) called in `POST /api/video/shots` to rewrite `(preset_key, overrides)` before `_VIDEO_BRIDGE.add_shot`. Caller's explicit overrides still win — mode only fills via `setdefault()`. Preset rewrites only fire when no explicit quality variant exists.

**Intentional non-coverage:** GIMP `_build_ltx_video` and `_run_ltx_t2v` use the dialog's explicit checkboxes, not Guild mode. Scaffold dispatcher's LTX branch respects caller overrides over hint defaults (§C.4 #6).

---

## D. Model coverage & supported_methods (was §17)

22 architectures registered in `spellcaster_core/architectures.py` — up from the original 8.

**Fully-built archs** (registered=True + populated `supported_methods`):

| Arch | Default (steps / CFG / res) | Notes |
|---|---|---|
| `sd15` | 25 / 7.0 / 512² | Classic, dpmpp_2m karras |
| `sdxl` | 30 / 6.5 / 1024² | dpmpp_2m_sde karras |
| `illustrious` | 28 / 5.5 / 1024² | Booru tags, euler_ancestral |
| `zit` | 6 / 2.0 / 1024² | Z-Image-Turbo distill, 4–6 steps |
| `flux1dev` | 25 / 3.5 / 1024² | dual CLIP (clip_l + t5xxl) |
| `flux2klein` | 4 / 1.0 / 1024² | SamplerCustomAdvanced + CFGGuider |
| `flux_kontext` | 25 / 3.5 / 1024² | edit instructions, no negative |
| `chroma` | 25 / 3.0 / 1024² | single CLIPLoader type="chroma" |
| `sdxl_turbo` | 6 / 1.5 / 1024² | euler_ancestral sgm_uniform |
| `pony` | 30 / 7.0 / 1024² | booru score cascade |
| `playground` | 30 / 3.0 / 1024² | SDXL backbone |
| `wan` | 30 / 3.5 / 832×480 | `supported_methods=VIDEO_METHODS` |
| `ltx` | 30 / 4.0 / 768×512 | Gemma encoder, VIDEO_METHODS |
| `seedvr` | 15 / 1.0 / 1280×720 | `supported_methods=("video_upscale",)` |

**Stubs** (`registered=False`, `supported_methods=()`): `sd3`, `sd3_turbo`, `hunyuan_dit`, `pixart`, `auraflow`, `kolors`, `cogvideo`. Detector knows them, defaults are correct, no builder dispatches yet — `_assert_method` raises an explicit "detected but not yet scaffolded" error. Promote a stub by (a) implementing the builder chain, (b) flipping `registered=True`, (c) populating `supported_methods`.

**The `supported_methods` contract** — canonical lists in `architectures.py`: `IMAGE_METHODS`, `VIDEO_METHODS`, `KLEIN_METHODS`, `ALL_IMAGE_METHODS`. Each ArchConfig's `supported_methods: tuple[str, ...]`. Enforcement at builder entry: `_assert_method_for_preset(preset, method_name)` is the FIRST line of every core builder. Raises `UnsupportedMethodError` when the preset's arch is registered but doesn't support the method, or arch is a stub. Unknown / 3rd-party arch keys pass silently (backward compat).

**UI gating rides on the same data** — Summon flow, Calibration UI, Chimera router read `supported_methods`.

**Size-aware unknown-checkpoint fallback** (`model_detect.py::classify_ckpt_model(name, file_size=None)`):
- No keyword + no size → `sd15`.
- No keyword + ≥ 9 GB → `flux1dev`.
- No keyword + ≥ 4.5 GB → `sdxl`.
- Keyword rules always win. Size is fallback only.
- `fallback_arch_for_size(bytes)` exposes the heuristic standalone.

**Adding a new arch** — register in `architectures.py` with correct defaults; `registered=True` only when a builder exists; populate `supported_methods` honestly; new `build_*` drops `_assert_method_for_preset(preset, "<method_name>")` as first body line; add a test in `tests/test_model_coverage.py`.

---

## E. LoRA calibration stack — ✧ Calibration (was §19)

UI button `tavern/static/lora_calibration.js`. Tabbed modal: **Confirm** (auto-rendered cards by (arch, purpose_group)) / **Compare duplicates** (pending shootouts; delegates to `window.SpellcasterShootout.open()`) / **Stats** (coverage + scorer health + preflight breakdown).

**Four-layer knowledge stack:**

1. `lora_knowledge.py::get_knowledge(name, path=..., user_override=..., use_network=True)` — merges in precedence order: User registry → `.civitai.info` sidecar → Safetensors `__metadata__` → Shipped community defaults (`lora_calibrations_sfw.json` + `lora_calibrations_nsfw.json`) → Civitai public API by SHA-256 (cached in `<state_dir>/lora_knowledge_cache.json`) → Heuristic fallbacks. Every populated field records its source in `provenance`.

2. `lora_calibration_store.py` — SFW/NSFW split JSON stores. `sfw_path()` → `comfyui-spellcaster/spellcaster_core/lora_calibrations_sfw.json` (PUBLIC). `nsfw_path()` → same dir + `lora_calibrations_nsfw.json` (gitignored in source; copied by `nsfw/build_nsfw.py::patch_nsfw_lora_calibrations` to staged `spellcaster_core/`). `write_calibration(name, *, nsfw=bool, ...)` routes via `lora_knowledge.classify_nsfw(knowledge, filename)` (Civitai flag OR keyword match; conservative — false-positive leaks NSFW-store-private, false-negative leaks NSFW into PUBLIC SFW which is unacceptable).

3. `lora_scorer.py::score_image(image_b64, prompt, *, ollama_url, model="gemma3:4b")` — POSTs to local Ollama multimodal `/api/chat` with `format: "json"`. Returns `ScoreResult(ok, score, reason, model, elapsed_ms, error)`. `probe_available()` hits `/api/tags`. Gracefully `ok=False` on any failure.

4. `scaffold/lora_grouping.py` — calibration engine. `resolve_shootout_recipe_for_lora(name, group, arch, ...)` consults `lora_knowledge`. `render_calibration_sample(server, name, group, arch, models, **opts)` renders ONE sample. `start_calibration_job(server, targets, models, *, preflight=True, ...)` kicks off background batch. **Preflight** (default on) renders ONE minimal base sample per unique arch — broken pipelines fail fast instead of streaming 50 red error cards. Job state serializes to `<state_dir>/calibration_jobs/<job_id>.json` (metadata only — image_b64 stripped). On Guild restart, still-running jobs marked `interrupted`.

**Shipped calibration JSON schema** (SFW + NSFW share):
```json
{
  "schema_version": 1,
  "loras": {
    "SomeLora.safetensors": {
      "updated_at": 1700000000,
      "source": "user_confirm | auto_confirm_llm | auto",
      "recommended_weight": 0.85,
      "recommended_sampler": "dpmpp_2m",
      "recommended_cfg": 7.5,
      "subject_key": "portrait_f",
      "trigger_words": ["sinozick style"],
      "base_model": "sdxl",
      "sha256": "abc123...",
      "confirmed_by_user": true,
      "confirmed_at": 1700000000,
      "nsfw": false
    }
  }
}
```

**Server endpoints (all in `tavern/server.py`):**
- `GET /api/spellcaster/lora/knowledge?name=X` → merged record
- `GET /api/spellcaster/lora/calibrate/summary` → confirmed/pending counts + store paths
- `POST /api/spellcaster/lora/calibrate/auto/start` (body: `{subset: "unconfirmed", use_network, score_with_llm, preflight, stability_seeds, sweep_strengths}`) → spawns job
- `GET /api/spellcaster/lora/calibrate/auto/status?job=X` → polls samples + skipped + preflight
- `POST /api/spellcaster/lora/calibrate/auto/cancel?job=X` → sets `cancel_requested` + ComfyUI `/interrupt` + `/queue {clear:true}`
- `POST /api/spellcaster/lora/calibrate/confirm` → writes recipe to right store + flips registry flag
- `GET /api/spellcaster/lora/calibrate/resumable` / `POST /.../resumable/clear` → interrupted-job metadata + dismiss
- `GET /api/spellcaster/lora/scorer/probe` → Ollama multimodal availability

---

## F. Summon archetypes — 5 specialised wizard kinds (was §21)

Classic Summon flow (pick model → auto-studio → LLM-name) is **path A**. Five archetype kinds sit alongside as **path B** — summon a wizard whose mechanic isn't tied to a single model.

**Character record** (persisted in `.guild_state/custom_wizards.json`):
```json
{
  "id": "archetype_<kind>_<slug>",
  "type": "archetype",
  "archetype_kind": "forensic|chimera|oracle|lore_keeper|scalpel",
  "archetype_config": { ... kind-specific ... },
  "system_prompt": "...",
  "name", "subtext", "color1", "color2", "personality"
}
```

**Per-kind config + runtime endpoint:**

| Kind | Config | Runtime endpoint | Back-end |
|---|---|---|---|
| **forensic** | `{}` | `POST /api/archetype/forensic/extract` (body: `image_b64`) | `forge.reverse_engineer_image` parses PNG tEXt for workflow / prompt / seed / LoRAs |
| **chimera** | `{models: [{name, arch, type, domain}, 2-5]}` | `POST /api/archetype/chimera/route` (body: `prompt, char_id`) | Keyword classifier picks best-domain head |
| **oracle** | `{llm_model: "gemma3:4b", ...}` | `POST /api/archetype/oracle/review` (body: `image_b64, prompt, llm_model`) | Delegates to `lora_scorer.score_image` |
| **lore_keeper** | `{}` | `POST /api/archetype/lore_keeper/query` (body: `query, limit`) | Substring search over `_LORA_REGISTRY` + `lora_calibration_store.load_merged()`; confirmed sort first |
| **scalpel** | `{base_model: {name, arch, type}}` | `POST /api/archetype/scalpel/plan` (body: `char_id, instruction`) | Verb detect (erase / replace / add) → SAM3 chain plan |

**Validation** (`_validate_archetype_config`): Chimera 2–5 models; Oracle non-empty `llm_model`; Scalpel `base_model` with `name`; Forensic / Lore-keeper accept empty. Unknown kind → 400.

**Adding a new archetype** — update `_ARCHETYPE_CATALOGUE` (`server.py`) with `icon` + `default_subtext` + `hue` + `system_prompt`; add validator branch; wire runtime endpoint; add entry to `SUMMON_ARCHETYPES` in `app.js`. Tests in `tests/test_summon_archetypes.py`.

---

## G. Quality + speedup cascade (was §22)

`spellcaster_core.workflows._apply_quality_boost` + `_apply_speedup` layer per-arch boosters. Surface params:
- `quality`: `"fast" | "balanced" (default) | "max"`
- `fast_mode`: bool (default False)
- `compile_mode`: bool (default False; opt-in torch.compile, persistent-server only — 20–40 s warm-up)

**Per-arch cascade (module-level sets in `workflows.py`):**

| Booster | Set variable | Scope | Applies when |
|---|---|---|---|
| CFGZeroStar         | `_QUALITY_ARCHES_CFG_ZERO_STAR` | `{zit, flux1dev, flux_kontext}` | quality ≠ fast AND cfg < 4.5 |
| PerturbedAttention  | `_QUALITY_ARCHES_PAG`           | `{sdxl, illustrious, flux1dev, chroma, flux_kontext, zit}` | quality ≠ fast |
| RescaleCFG          | `_QUALITY_ARCHES_RESCALE`       | `{sd15, sdxl, illustrious}` | cfg ≥ 7.5 |
| FreeU_V2            | `_QUALITY_ARCHES_FREEU`         | `{sdxl}` | quality == max |
| SkipLayerGuidanceDiT| `_QUALITY_ARCHES_SLG`           | `{flux1dev, flux_kontext, zit}` | quality == max |
| SageAttention       | `_SAGE_ATTENTION_ARCHES`        | `{flux1dev, flux_kontext, flux2klein, zit, wan, ltx, chroma}` | fast_mode |
| torch.compile       | (all arches)                    | any | compile_mode |
| TeaCache            | explicit list                   | `{flux1dev, flux_kontext, zit}` | fast_mode |
| DetailDaemon sampler| `_DETAIL_DAEMON_ARCHES`         | `{zit}` | quality == max (replaces KSampler) |

**Klein excluded from every model-patch booster** — its `Flux2KleinEnhancer` chain (§A) handles guidance shaping, and PAG/SLG conflict with `ReferenceLatent + CFGGuider`. Klein still gets Sage Attention when `fast_mode=True` (pure attention swap, no guidance interaction).

**Per-arch tunings:**
- PAG scale: `1.5` ZIT (distilled cfg=2 hates PAG 3.0), `3.0` elsewhere.
- SLG scale: `2.0` ZIT, `3.0` Flux; layers 7–9 in both streams.
- TeaCache threshold: `0.3` ZIT, `0.4` Flux.
- Detail Daemon: `detail_amount=0.1`, `start=0.2`, `end=0.8`, `smooth=True`.

**Ordering invariant:** CFGZeroStar fires BEFORE PAG/SLG so subsequent patches stack on corrected guidance. `_apply_speedup` node-id tranche is `base / base+1 / base+2` = Sage / torch.compile / TeaCache. Callers passing only legacy `node_id` still get a valid 3-slot tranche from it; do NOT remove that fallback.

**Smoke check:** `cd comfyui-spellcaster && python -c "from spellcaster_core import workflows as wf; print('zit' in wf._DETAIL_DAEMON_ARCHES)"`. Full coverage in `tests/test_quality_boost.py`.

---

## H. ControlNet routing (was §23, §26, §29, §30)

### H.1 Compatibility gating (`cn_is_compatible`)

Every UI picker that exposes a CN combobox MUST filter through `spellcaster_core.model_detect.cn_is_compatible` (or its list wrapper `cn_modes_for_arch`).

Canonical filter (`spellcaster_core/model_detect.py`):
- `CN_FORBIDDEN_ARCHES = frozenset({"flux2klein", "flux_kontext", "chroma"})` — these arches see ONLY the "Off" entry.
- `cn_is_compatible(cn_models, target_arch)` — True iff `cn_models is None` (synthetic "Off") OR target arch is non-forbidden AND a key of `cn_models`.
- `cn_modes_for_arch(modes_dict, target_arch)` — iteration-order-preserving list helper; "Off" stays at index 0.

**UI integration:**
- **GIMP** — local `cn_modes_for_arch` wrapper delegates to canonical with inline fallback. `_cn_mode_combo` + `_cn_mode_combo_2` populate through it. `_refresh_cn_combos()` re-filters on preset change, preserving user pick across arch switches when survivable, else falling back to Off. Hooked into `_on_preset_changed`.
- **Darktable** — `CN_MODEL_MAP`; every ZIT mode routes to `ZIT_UNION_CN = "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"`.
- **Guild** — delegates; no standalone CN picker.

**Builder-layer enforcement:** every `build_*` calls `_assert_method_for_preset` at entry (§D). UI filter is usability; builder assertion is the safety net.

**Coverage** — `tests/test_cn_compat.py` validates every (mode, arch) pair across 14 modes × 20 architectures = 280 pairs. Loads `CONTROLNET_GUIDE_MODES` out of GIMP plugin without importing Gtk (brace-balance walks the dict literal).

### H.2 File resolution — three-layer system

Real ComfyUI installs put CN files in non-canonical paths: HF folder layout, fp16 versioned subdirs, partial downloads with `safetensors_rust.SafetensorError: incomplete metadata`. Three defensive layers:

**Layer 1 — Hardcoded guide table (`CONTROLNET_GUIDE_MODES`):** per-mode × per-arch canonical flat-form filename. Drives UI combo. DEFAULT when no override supplied.

**Layer 2 — Normal-Map cascade (`_resolve_normal_map_cn` + `_NORMAL_MAP_FALLBACK_CHAIN`):** walks arch-specific fallback chain (Union → Depth → Canny / lineart) when preferred file isn't installed. Chain entries include both flat-form AND HF folder-form. Stashes resolved name as `controlnet["cn_model_override"]`. Fired by `_maybe_override_cn_with_normal_map` in every 3D handler.

**Layer 3 — Universal workflow resolver (`_resolve_cn_paths_in_workflow`):** walks every `ControlNetLoader` node in the built workflow and rewrites `control_net_name` to whatever's installed. Called unconditionally in `_run_comfyui_workflow` right before dispatch. Matching: exact → basename → stem (strips `_fp16`; HF generic `diffusion_pytorch_model.safetensors` uses parent-folder name as identity).

`composites.inject_controlnet` honours `cn_model_override` BEFORE falling back to the guide's hardcoded table. Without this, layer 2 work was discarded pre-2026-04-20.

**Session blacklist** (`_CN_SESSION_BLACKLIST`) — `_maybe_handle_cn_error` scans dispatch errors for known-bad tokens (`incomplete metadata`, `controlnet file is invalid`, `does not contain controlnet or t2i adapter data`), extracts the offending filename, adds to in-memory blacklist. Layers 2 + 3 skip blacklisted on retry. Clears on GIMP restart.

**Server-side repair** (`comfyui-spellcaster/model_repair.py`): `POST /spellcaster/models/repair` with `{action: "delete"|"redownload", folder: "controlnet", filename: ...}`. Deletes + streams from curated HF URLs (`CN_URL_MAP` — single source, mirrored in `installer/install.py::step_check_cn_coverage`). GIMP `_offer_cn_repair` fires Gtk dialog on every 3D handler entry when bad-CN marker set; user clicks "Repair on server"; pack does delete+download; blacklist clears + cache invalidates.

**Adding a new CN** — extend `CN_URL_MAP` in BOTH `model_repair.py` AND `installer/install.py`; add fallback-chain entry in `_NORMAL_MAP_FALLBACK_CHAIN` if normal-map-capable.

### H.3 Flux CNs require VAE on `ControlNetApplyAdvanced`

Flux-family CN models raise `ValueError: This Controlnet needs a VAE but none was provided` without `vae` input. `NodeFactory.controlnet_apply_advanced` accepts optional `vae_ref` wired when arch is Flux-family (`flux1dev`, `flux2klein`, `flux_kontext`). `composites.inject_controlnet` makes the per-arch decision; every `workflows.build_*` threads `vae_ref=vae_ref` through its `inject_controlnet` call.

### H.4 Inpaint composite preserves outside-mask pixels

`build_inpaint` composites the decoded output with the ORIGINAL input via the full-res mask so unmasked pixels are byte-identical. Prior code saved VAE-decoded output directly — VAE round-trip artefacts + ControlNet global pressure leaked the "3D map look". `ImageCompositeMasked` node at ID `"96"` is the critical addition. Only fires on the `mask_filename` path (SAM3 branch operates at working resolution).

---

## I. Cross-interface backbone — presence + blob bus + typed events (was §25)

Two HTTP surfaces alongside each other:

| Surface | Process | Ownership |
|---|---|---|
| ComfyUI pack | ComfyUI PromptServer | Peer discovery (`presence.py`), LAN-resilient blob transport (`blob_bus.py`) |
| Wizard Guild | Guild Python process | Persistent asset gallery, event bus, mailboxes, video shotboard, all `/api/*` |

ComfyUI is ambient — every plugin already reaches it. Presence + blob routes give plugins a way to discover each other AND hand bytes around without the Guild process being up.

### I.1 Presence broker — `comfyui-spellcaster/presence.py`

```
POST /spellcaster/presence/register      body: {key, host?, instance_id?, label, icon, capabilities, version, url, meta}
POST /spellcaster/presence/heartbeat     body: {key, host?, instance_id?, meta}    # auto-registers
GET  /spellcaster/presence/list          → {peers: [...], ttl_s}
POST /spellcaster/presence/unregister    body: {key, host?, instance_id?}          # idempotent
```

TTL 45 s (2× recommended 20 s heartbeat). Broker keys records by `instance_id` — `key@host` when client provides host, else `key@<observed remote_addr>`. Same plugin on two machines gets different `instance_id`s. X-Forwarded-For honoured.

Plugins heartbeat at module load: GIMP (`_start_comfy_presence_heartbeat`), Darktable (`comfy_presence_heartbeat`), SillyTavern (`_startPresenceHeartbeat`), Resolve (`_send_comfyui_presence`).

Why it matters: Guild restart used to blind every plugin. Now presence survives Guild outages.

### I.2 Blob bus — `comfyui-spellcaster/blob_bus.py`

```
POST /spellcaster/blob/put       multipart: file + origin + kind + ttl_s?    → {hash, url (absolute), size, kind, mime, expires_at}
GET  /spellcaster/blob/<hash>    → raw bytes + sniffed Content-Type
GET  /spellcaster/blob/list      → {blobs: [...], total_bytes, max_store_bytes, max_blob_bytes}
```

Storage: `<comfyui>/output/spellcaster_bus/`, content-hash (SHA-256) addressed. TTL 1 h default, 24 h max per blob. Hard ceilings: 256 MB per blob, 2 GB aggregate. Reaper every 60 s. Dedup by content hash — re-upload bumps TTL.

`url` is absolute (built from `Host:` header) so peers on other LAN machines fetch without knowing ComfyUI's IP.

**Three senders use it as preferred Send-to-X transport** (Guild AssetGallery fallback): GIMP (`_cross_interface_send` → `CrossInterfaceClient.blob_put`), Darktable (`_asset_upload_and_emit` → curl `-F` multipart), Resolve (`_handle_playhead_send_to_peer` — hand-built multipart). Event has `transport: "blob"|"guild"` so subscribers can tell which path landed.

**When NOT to use blob bus:** assets that need persist > 1 h (avatars, backgrounds, gallery). Those belong in `AssetGallery` (`CLAUDE.md` §2 R9).

### I.3 Typed event schema — `spellcaster_core/events.py`

Every canonical wire kind has a dataclass. Publishers construct the typed event; subscribers get a typed view via `parse_event(kind, data)`. Wildcard suffixes (`*.asset.created`, `*.generation.finished`, `*.asset.send`) match any origin prefix.

```python
from spellcaster_core.events import AssetSend, publish_event, parse_event

# publisher
publish_event(bus, AssetSend(image_url="/api/assets/abc", hash="abc",
                              source="gimp", kind="generation"),
              origin="gimp")   # emits gimp.asset.send

# subscriber
evt = parse_event(kind, data)
if isinstance(evt, AssetSend):
    use(evt.image_url, evt.hash)
```

Guild's `_cache_comfyui_asset` already uses it (`AssetCreated` on every generation). Existing dict-reading subscribers see no wire-format change — extra fields ride through.

**Add new kinds:** dataclass in `events.py`, register in `EVENT_SCHEMAS` (or rely on wildcard-suffix match), then mirror to all surfaces (`CLAUDE.md` §2 R1).

### I.4 When Guild is down

- Presence still works (ComfyUI is the discovery hub).
- Blob bus still works (bytes move Guild-lessly).
- **Event signalling does NOT** — no bus without Guild. Receivers need Guild's SSE stream to know a blob is waiting. Three candidate designs in `_dev_docs/HANDOVER_CROSS_APP_AUDIT.md` §6.4, none shipped. Pragmatic answer: Guild is still the coordinator; blob bus is a transport optimisation, not a full replacement.

### I.5 Verification — `tests/e2e_audit.py`

```bash
python tests/e2e_audit.py --only presence_broker,blob_bus,events_schema
python tests/e2e_audit.py --only guild_client,cn_model_coverage
python tests/e2e_audit.py --only coverage_inventory
python tests/e2e_audit.py --offline                    # no Guild required
```

`presence_broker` exercises multi-host coexistence, `blob_bus` exercises put/get/dedup/404, `events_schema` round-trips every dataclass, `cn_model_coverage` verifies every CN mode × arch references a real CN file on the live server, `coverage_inventory` ast-walks plugin surfaces and counts public functions.

---

## J. Single source of truth for assets (was §15)

Cross-interface backbone provides ONE canonical blob store (`tavern/creations/gallery/`) + ONE event bus. Every generated asset MUST flow:

1. **`spellcaster_core.asset_gallery.AssetGallery.put(data, origin=..., kind=..., prompt=..., model=..., seed=..., tags=..., meta=...)`** — content-hash addressed, sharded by first two hex chars; upserts metadata; returns `AssetRecord` with stable `.hash`.
2. **`spellcaster_core.event_bus.EventBus.default().publish(f"{origin}.asset.created", origin=..., data={...})`** — notifies subscribers (Resolve Bridge, GIMP gallery publisher, Signal notifier). Event includes `asset_hash` so subscribers `GET /api/assets/<hash>`.
3. **Return canonical `/api/assets/<hash>`** — served by `GuildHandler._handle_assets_get`. Never return raw ComfyUI `/view?filename=...` to browser; they break the moment privacy cleanup runs.

**Guild-side entry point:** `_cache_comfyui_asset` in `tavern/server.py`. Downloads ComfyUI `/view`, calls `AssetGallery.put`, publishes event, returns `/api/assets/<hash>`:

```python
cached_url = _cache_comfyui_asset(
    view_url, "image",
    kind="generation",                    # or "avatar", "background", "shot", "upscale", "inpaint", ...
    prompt=positive_prompt,
    model=ckpt or unet_filename,
    seed=seed,
    title="optional short label",
    tags=[arch_key, wizard_name],
    meta={"char_id": char_id, "arch": arch_key},
)
```

**GIMP / Resolve / other plugins** posting bytes to Guild from outside: `POST /api/<iface>/inbox` with `body_b64` — endpoint already routes through `AssetGallery.put` and emits the event. Do NOT add a second storage path on the plugin side.

**Banned:**
- Writing bytes to flat dir keyed by URL/filename hash (the old behaviour).
- Returning raw ComfyUI `/view?filename=...` URLs to the browser.
- Bypassing EventBus on generation completion.
- Rolling a bespoke blob store in a plugin or scaffold.

**Compat shims (legacy, do not extend):** `/api/cached_asset/<name>` still serves files from the pre-refactor flat cache so old `generated_assets.json` entries work. `_cache_comfyui_asset` falls back to flat cache only when `_ASSET_GALLERY is None` at import. New code tolerates both URL shapes when parsing (`'/api/assets/' in url or '/api/cached_asset/' in url`) but produces only canonical. `_seed_bundled_assets` (2026-04-20) routes through `AssetGallery.put` too — fresh installs no longer write `/api/cached_asset/` URLs.

**Alternative transport — blob bus** (§I.2): every plugin with a ComfyUI URL can push bytes via `POST /spellcaster/blob/put` and broadcast the absolute URL through the event bus. Use via `CrossInterfaceClient.blob_put()` (Python) or curl `-F` (Lua/other). Senders prefer blob bus, fall back to AssetGallery; receivers are URL-shape-agnostic.

**PR check:**
- New ComfyUI download → through `_cache_comfyui_asset` (Guild) or `_upload_bytes_to_comfyui` → `AssetGallery.put` (plugin ingest).
- New generation path emits `<origin>.asset.created` (via `_cache_comfyui_asset(..., emit_event=True)` or explicitly).
- No `os.path.join(_ASSET_CACHE_DIR, ...)` writes outside the fallback branch.
- No new `/api/cached_asset/*` writers (readers are fine).

---

## K. /api/run_builder bridge (was §24)

Thin client plugins (Darktable Lua, future Lua/JS surfaces, remote scripts) call `POST /api/run_builder` instead of inlining workflow JSON.

Body: `{"builder": "build_klein_inpaint", "params": {...}, "comfy_url": "..."}`.

Guild routes through `_build_and_dispatch` → `spellcaster_core.workflows.<builder>`, dispatches, caches via `AssetGallery` (§J), returns canonical `/api/assets/<hash>` URLs.

**Use this for any new image-edit feature in a non-Python plugin.** Inlining a 200-line workflow JSON DAG in Lua/JS duplicates the canonical builder and guarantees divergence on the next bug fix.

The Python GIMP plugin imports `spellcaster_core` directly and doesn't need this bridge.

**Canonical example:** Darktable "Klein Surgical Edits" + "Z-Image-Turbo (Advanced)" use `_run_builder(builder_name, params_json)` + `_download_guild_assets(urls, prefix)`. ~50 Lua lines per feature, zero workflow JSON, bug fixes in `spellcaster_core/workflows.py` reach every client automatically.

**Param conventions for Lua/JS callers:** flat keyword shape (`image_filename`, `prompt_text`, `negative_text`, `seed`, `denoise`, `quality`, `fast_mode`, `arch`, `ckpt`, `loras`, `sam3_prompt`). Guild's `_translate_params` (`tavern/server.py`) handles renames (e.g. `prompt` → `prompt_text`), builds `preset` from flat params + auto-detection, re-uploads any `/api/assets/<hash>` or `/api/cached_asset/<name>` filenames to ComfyUI before dispatch.

---

## L. Result routing in GIMP (was §18, §28)

Every ComfyUI result downloaded by the GIMP plugin flows through `_import_result_as_layer` (via the shared `_apply_mask_mode` wrapper). That helper decides whether the result becomes a new layer or a new GIMP image — **handlers must NOT open their own display.**

**The rule — dimensional, not flag-based:**

| Result dims vs. canvas | Outcome |
|---|---|
| Larger than canvas on either axis | `Gimp.Display.new(result_image)` — opens as a new GIMP image |
| Same size or smaller | Insert as a new top layer on existing image (scale up to canvas if smaller) |
| `keep_size=True` caller flag | Always a layer, centered, never auto-routed (SAM3, normal-map auto-gen) |

**Why dimensional:** one check catches every upscaler automatically (`_run_upscale`, `_run_quick_upscale`, `_run_upscale_blend`, `_run_detail_hallucinate`, `_run_seedv2r` with scale > 1×, `_run_outpaint`, `_run_klein_outpaint`). No per-handler flag needed. Scale-to-fit would have discarded the upscale pass. The "z1 / enhance only" case (scale = 1.0) naturally produces output dims == input dims → stays a layer.

**Empty-bytes guard** — `_apply_mask_mode` refuses to import `img_data` shorter than 100 bytes. Surfaces `Gimp.message` with likely-cause hints (privacy cleanup race, SaveImage error, concurrent workflow wipe) and returns False. Previously, "outputs produced but not imported" reports came from silently inserting a broken layer.

**Video handlers** — `_import_video_results` routes last-frame PNG imports through `_apply_mask_mode(..., mask_enabled=False)` so video calls inherit the guard. Function ALSO calls `_repatriate_outputs(server, results)` so video outputs (`.mp4`/`.gif`/lastframe `.png`) go through the same privacy-cleanup path as image outputs. Pre-audit they leaked indefinitely.

**For new handlers:**
1. Download bytes via `_download_image(srv, fn, sf, ft)`, hand to `_apply_mask_mode(srv, image, data, layer_name, mask_enabled)`.
2. If genuinely same-size-only (face restore, recolour, img2img at canvas dims), the layer path is taken automatically.
3. If your workflow may return a cropped subject overlaid at natural position, call `_import_result_as_layer(..., keep_size=True)` directly — bypasses auto-route.
4. Never add a handler-side dimension check — the helper owns this decision; divergent copies will drift.

---

## M. GIMP plugin subprocess facts (was §27)

GIMP 3 Python plug-ins run in a SEPARATE child process (typically `gimp-script-fu-interpreter-3.0.exe` or a Python interpreter GIMP spawned).

- **`Gimp.quit(False)` doesn't reliably quit GIMP from a plug-in** — quit request is sent from the child while inside `dlg.run()` of its own Gtk dialog; request gets lost or deferred. The Restart GIMP button in Settings spawns a detached `taskkill /IM gimp-3.0.exe /F /T` (Windows) or `pkill -f gimp-3.0` (Unix) wrapper that force-kills GIMP + every child plug-in process after 1 s, waits 2 s for locks to release, then launches fresh. Does NOT depend on `Gimp.quit()` firing.

- **CSS theme provider needs `PRIORITY_USER`, not `PRIORITY_APPLICATION`** — GIMP's own theme sits at `PRIORITY_APPLICATION` (600) and wins specificity ties. `Gtk.STYLE_PROVIDER_PRIORITY_USER` (800) lets Spellcaster CSS override.

- **Apply-Theme needs a UI toggle**, not a hidden config key. First-class checkbox in Settings + persist on OK + re-apply live via `_apply_spellcaster_theme()`.

- **15 Guild-matching theme variants** in `_THEME_VARIANTS` — one per architecture in Guild's `ARCH_META` (`tavern/static/app.js`) + a Cinema Night dim variant. Each is a ~200-byte CSS overlay (`@define-color` overrides) prepending to the canonical 48 KB `spellcaster-theme.css`. `c1 / c2 / glow` lifted verbatim from `ARCH_META` — adding a new Guild arch becomes a one-line entry in `_THEME_VARIANTS`. Picker is the "└ Variant:" ComboBoxText under the Apply-Theme checkbox.

- **Plug-in dialog indices are NOT MODEL_PRESETS indices** after 2026-04-20 (3D tools filter out incompatible archs). Inside `PresetDialog`, always use `self._preset_idx()` — reads `get_active_id()` (we append `str(MODEL_PRESETS_index)` as the stable combo ID). `get_active()` returns the VISUAL position which no longer aligns with `MODEL_PRESETS` when exclusions are active. External `set_active(i)` callers must become `set_active_id(str(i))`.

---

## N. Path separators — central policy (was §14)

| Context | Separator | Rationale |
|---|---|---|
| Internal Python | `pathlib.Path` objects | OS-native, no manual concat |
| Config file values (JSON) | Forward slash `/` | Escaping-free, Windows accepts |
| API response bodies (JSON) | Forward slash via `.as_posix()` | Clients don't escape |
| Subprocess argv on Windows | Platform-native via `str(path)` | Some `.bat` launchers are picky |
| Error messages / logs | Whatever repr gives | Human-readable, OS-appropriate |
| ComfyUI workflow JSON (builders) | **Filenames only — no full paths** | ComfyUI resolves against input/output dirs |

**Rules of thumb:**
- Inside Python, always `pathlib.Path`. Never build paths with `+` or f-strings.
- Accepting paths from JSON: `Path(os.path.expanduser(s))` handles both separators transparently.
- Emitting paths TO JSON: prefer `.as_posix()`.
- Workflow builders in `spellcaster_core/workflows.py` DELIBERATELY use only filenames (not full paths) because ComfyUI resolves them server-side. Touching this is a minefield — don't.

---

## O. Auto-update clobber matrix (was §13)

Three different auto-updaters DOWNLOAD from GitHub on startup, OVERWRITE local files, DELETE anything not in remote:

| Component | Updater | Runs when | Protected files | What gets clobbered |
|---|---|---|---|---|
| **Wizard Guild** | `tavern/guild_launcher.py:check_for_updates` | every launch | `guild_launcher.py`, `guild_config.json`, `guild_common.py` | everything under `tavern/` and `scaffold/` |
| **GIMP plugin** | `plugins/gimp/comfyui-connector/_spellcaster_main.py:_auto_update` | GIMP start | `comfyui-connector.py` (boot shim), `config.json`, `.spellcaster_version`, `user_presets.json`, `session_state.json` | everything else in plugin dir + `spellcaster_core/` copy |
| **Installer** | `installer/bootstrap.py` | every .exe launch | n/a (runs in temp dir) | nothing — bootstrap uses ephemeral dir |

**Before recommending a Guild restart:** run `git status -s | grep -E "tavern/\|scaffold/"`. If anything modified or untracked, warn — changes will be overwritten unless committed first OR `--no-update` used.

**Before recommending a GIMP restart after editing `_spellcaster_main.py` or `spellcaster_core/`:** same check on `plugins/gimp/comfyui-connector/`. If uncommitted, offer (a) sync to local GIMP via deploy first, (b) commit + push so auto-update is no-op, or (c) disable auto-update temporarily.

**Safe-restart options (preference order):**
a. **Commit + push** (cleanest) — auto-update downloads exactly what's there.
b. **No-update launcher** — `DEVNOUPDATE_NSFW Wizard Guild.bat` skips Guild updater. No direct GIMP equivalent; delete `.update` files if needed.
c. **`auto_update: false`** in `guild_config.json` (Guild only) for longer debug.
d. **Stash** (last resort).

**Never tell a user a restart is "safe" without checking first.** The Guild updater also PRUNES — files in local `tavern/`/`scaffold/` not in remote get DELETED.

When Claude makes changes that need a running server to test: commit first, then restart. Don't ask the user to restart while edits are uncommitted.

---

## P. Installer self-update + step 5b CN coverage (was §15a, §31)

`spellcaster-installer.exe` is a two-stage runner (`installer/bootstrap.py`):

1. Bootstrap fetches latest `install.py`, `installer_gui.py`, `manifest.json` from `raw.githubusercontent.com/laboratoiresonore/spellcaster/main` to a temp dir.
2. Execs fetched code via `importlib`, passing `SPELLCASTER_INSTALLER_ROOT=<temp_dir>`.
3. On fetch failure, falls back to baked-in copy.

**No need to rebuild the .exe for most installer fixes.** Editing `installer/install.py`, `installer_gui.py`, or `manifest.json` and pushing to main is enough — every existing .exe picks up on next launch.

**.exe needs rebuilding only when:** `bootstrap.py` itself changes, `build_installer.py` flags change, NEW bundled asset added (e.g. new `plugins/` dir), PyInstaller hidden-imports list needs updating.

Assets stay baked: `plugins/`, `tavern/`, `scaffold/`, `assets/` are bundled. Asset finders consult both `SCRIPT_DIR` (fetched temp) and `BUNDLE_DIR` (PyInstaller `_MEIPASS`).

**Installer step 5b — CN coverage audit** runs after `step_install_models` and before `_write_shared_settings`. For every canonical CN in the URL map (mirrors `model_repair.py::CN_URL_MAP`):
1. Probes server's CN inventory.
2. Matches both flat and HF folder-form paths.
3. Prints `✓ installed` / `✗ missing` with sizes + HF URLs + total estimate.
4. Offers auto-download via `POST /spellcaster/models/repair`. Falls back to manual ComfyUI Manager instructions when repair route isn't live (first-run chicken-and-egg).
5. Respects `--dry-run` and `--yes`.

First-time users no longer hit cryptic "incomplete metadata" / "controlnet file is invalid" errors — gaps surface at install time.

---

## End

Cross-references back to `CLAUDE.md`:
- Hard rules → `CLAUDE.md` §2
- Architecture overview → `CLAUDE.md` §3 (which points at `_dev_docs/ARCHITECTURAL_STUDY_2026-04-30.md`)
- Privacy & ethics → `CLAUDE.md` §4
- Active phase → `CLAUDE.md` §5
- Token discipline routing → `CLAUDE.md` §6
- Self-improvement loop → `CLAUDE.md` §7
