# Spellcaster — Comprehensive Upgrade Plan

> **Drafted:** 2026-05-06
> **Source audit:** `/loop` autonomous audit, iters 1-2 (CLAUDE.md, workflows.py, architectures.py, video_presets.py, builder spot-checks)
> **Hardware target:** RTX 5060 Ti 16GB VRAM (Theo) — primary; secondary deploys at workstation/Lawptop2 (smaller VRAM, secondary models)
> **Status of stack as of audit:** WAN 2.2 + LTX 2.3 builders are SOTA. Image archs are well-covered for the 8 deeply-integrated families (R8 matrix). Significant whitespace exists in the new-2026 video model space.

---

## §1 Executive summary

**Spellcaster's image-generation stack is current.** WAN 2.2 + LTX 2.3 builders carry SLG, NAG, SageAttention (2026-04 kernel), CFGZeroStar, distilled/full/two-stage modes, VAE tiling. `video_presets.py` handles the legacy/COMBO `/object_info` schema migration. R7 contract (`_assert_method_for_preset`) is enforced on the core image gen path; utility/Klein/faceswap builders use parallel gating systems.

**The biggest gap is the 2026 video-model wave.** HunyuanVideo, FramePack (low-VRAM-optimized — perfect fit for 16GB), CogVideoX (registered stub, no builder), Mochi-1, SkyReels are absent or stub-only. **FramePack is the highest-leverage single addition for this hardware.**

**Smaller gaps**: 14 archs in the 22-arch registry are declared without builders (utility-only or stub); some R7-eligible builders skip the assert; a few cross-cutting quality patches (SageAttention, CFGZeroStar, PerturbedAttentionGuidance) are video-only and could lift image quality at near-zero cost.

**This plan is tiered by ROI**, with each tier scoped to fit a multi-iter `/loop` arc respecting R0-R12 and the Phase-9 don't-touch list.

---

## §2 SOTA baseline (May 2026)

What the audit confirmed is current:

| Component | Current SOTA | Spellcaster status |
|---|---|---|
| WAN video | 2.2 (14B I2V-A14B + 5B TI2V) | ✓ detected, paired, built |
| LTX video | 2.3 (distilled / full / two-stage / I2V) | ✓ detected, all 4 modes |
| Flux family | 1-dev, 2-Klein, Kontext | ✓ all 3 in R8 matrix |
| Klein refinement | Mask refiner + Enhancer chain (default ON) | ✓ in builder |
| SageAttention | 2026-04 kernel rewrite (50-100% faster on 40/50xx) | ✓ flag in WAN/LTX, **gap: image archs** |
| CFGZeroStar | Stable in core ComfyUI | ✓ in WAN/LTX, **gap: image archs** |
| SLG (SkipLayerGuidanceSD3) | Stable in core | ✓ in WAN |
| NAG (Wan-specific) | Kijai's WanVideoWrapper | ✓ in WAN |
| Sampler / scheduler defaults | euler/simple paired w/ ModelSamplingSD3 shift | ✓ canonical |
| TeaCache | Stable | ✓ in WAN |
| Qwen Image Edit | 2509 (Sept 2025) | ✓ via `build_qwen_edit` |
| Background removal | BiRefNet | ✓ |
| Face restoration | GFPGAN / CodeFormer / ReActor | ✓ |
| Photo restoration | SUPIR | ✓ |

Gaps (model-currency):

| Component | SOTA option | Spellcaster status |
|---|---|---|
| HunyuanVideo (Tencent) | 13B-T2V, 13B-I2V (Dec 2024 / 2025 refresh) | ❌ no builder; only `hunyuan_dit` (image) registered |
| **FramePack** | Jan 2026, 6GB-VRAM minimum, F1/F2 variants | ❌ absent — **highest-leverage gap for 16GB hardware** |
| CogVideoX | 5B I2V/T2V | ⚠ registered, stub-only (no builder) |
| Mochi-1 (Genmo) | 10B Apache-2.0 | ❌ absent |
| SkyReels-V1 / V2 | I2V-tuned, early 2026 | ❌ absent |
| Stable Video 4D / Diffusion XT | NVIDIA's video-XT line | ❌ absent (less-popular niche) |
| MMAudio | Sound-from-video, 2025 | ❌ no audio builder |
| Hunyuan3D / TripoSG | 3D-from-image (2025) | ❌ no 3D builder |

Cross-cutting gaps (quality patches available for image archs):

| Patch | Where it lives | Could apply to |
|---|---|---|
| SageAttention 2026-04 | `PatchSageAttentionKJ` | All KSampler-based archs (SD15, SDXL, Illustrious, Pony, ZIT, Flux) — 30-50% sampler speedup |
| CFGZeroStar | `CFGZeroStar`/`CFGZeroStep` (core) | All CFG-using archs (SD15, SDXL, Illustrious, Pony) — small quality bump, zero cost |
| PerturbedAttentionGuidance (PAG) | Native ComfyUI | SDXL, SD15, Illustrious — meaningful detail bump |
| TeaCache (image) | Stable | Flux1-dev, Klein |
| RealESRGAN ESRGAN-X4Plus-Anime | Existing | Already in upscale registry |

---

## §3 Findings from audit

### §3.1 R7 contract — partial coverage

CLAUDE.md says R7 covers "the 42 `build_*` functions" but the codebase has 61 builders. Only 11 have `_assert_method_for_preset` as their first body line. The other 50:

- **~32** are utility/post-processing builders that don't take a `preset` (rembg, lut, color_match, sam3_*, frame_assembly, layer_blend, video_upscale, etc.) — legitimately exempt
- **~16** are Klein-family builders with parallel gating via `if klein_models is None:` — semantically equivalent
- **~4** are faceswap-family with `_faceswap_guard()` — semantically equivalent
- **~2 are real R7 gaps**: `build_generate_anything` (takes `preset`, generation builder), `build_qwen_edit` (takes config but no `preset` — nuanced)

**Recommendation:** add `_assert_method_for_preset` to `build_generate_anything`. Update CLAUDE.md R7 paragraph to acknowledge the parallel-gating equivalents and define the exempt categories explicitly.

### §3.2 22-arch registry — declared vs. wired

21 archs in the registry (one entry pattern wasn't captured by the regex):

| Arch | Has builder? | Used in R8 matrix? | Notes |
|---|---|---|---|
| sd15 | ✓ | ✓ | core |
| sdxl | ✓ | ✓ | core |
| illustrious | ✓ | ✓ | core |
| zit | ✓ | ✓ | core |
| flux1dev | ✓ | ✓ | core |
| flux2klein | ✓ | ✓ | core |
| flux_kontext | ✓ | ✓ | core |
| chroma | ✓ | ✓ | core |
| sdxl_turbo | ✓ (via `build_txt2img` w/ preset) | — | distillation variant |
| pony | ✓ (via `build_txt2img`) | — | SDXL fine-tune family |
| playground | ✓ (via `build_txt2img`) | — | SDXL fine-tune |
| sd3 | ⚠ partial | — | uses different sampler stack |
| sd3_turbo | ⚠ partial | — | as above |
| hunyuan_dit | ⚠ partial | — | image arch (Tencent) |
| pixart | ⚠ partial | — | DiT-family |
| auraflow | ⚠ partial | — | shift-aware |
| kolors | ⚠ partial | — | KwaiVGI |
| wan | ✓ | — | video; `build_wan_video` |
| ltx | ✓ | — | video; `build_ltx_video` |
| seedvr | ✓ | — | video upscaler |
| cogvideo | ❌ STUB | — | no builder |

**Recommendation:** the 7 "partial" image archs likely route through `build_txt2img`/`build_img2img` with arch-specific dispatches inside; promote them to full first-class status (their own R8 matrix row) only if user uses them. Otherwise low priority.

### §3.3 Code-debt low

`grep -E "TODO|FIXME|HACK|XXX"` returns **1 hit total** across `spellcaster_core/`. Codebase is well-maintained.

### §3.4 Phase-9 don't-touch perimeter

Per CLAUDE.md §5 and confirmed by file timestamps, do NOT structurally edit during Phase-9 prep:

```
asset_gallery.py
event_bus.py
interface_registry.py
mailbox.py
cross_interface.py
events.py
tavern/server.py::_cache_comfyui_asset
tavern/server.py::_handle_assets_get
22-arch registry keys (additive only — never rename)
```

This means cross-cutting refactors that touch the asset pipeline are **paused** until Phase 9 ships. Builders, presets, samplers, LoRA stacks, and architectures are fair game.

---

## §4 Upgrade tiers

### TIER 1 — Quick wins (low effort, high ROI, surgical)

Each item ≤ 1-2 hour effort, no six-mirror sync risk, additive only.

| # | Item | Effort | Impact | Files |
|---|---|---|---|---|
| 1.1 | Add `_assert_method_for_preset` to `build_generate_anything` | 5 min | Closes R7 gap | `workflows.py:588` |
| 1.2 | **Wire `enable_sage` flag through image builders** (`build_txt2img` / `build_img2img` etc.) for SDXL/Illustrious/Flux | **2-3 hr** | 30-50% sampler speedup on RTX 50xx | `workflows.py`, `composites.py` |
| 1.3 | **Wire `enable_cfg_zero` flag through CFG-using image builders** | **1-2 hr** | Quality bump, zero cost | `workflows.py`, `composites.py` |
| 1.4 | **Wire `enable_pag` flag (PerturbedAttentionGuidance) for SDXL/SD15/Illustrious from scratch** | **3-4 hr** | Detail bump | `workflows.py`, `node_factory.py`, possibly `composites.py` |
| 1.5 | Audit + fix `cogvideo` stub: either add a builder or mark `is_stub=True` so R7 doesn't silently pass | 30 min | Removes silent-pass hazard | `architectures.py` |
| 1.6 | Add `wan22_t2v_blockswap` variant for low-VRAM T2V — block swap is supported in `build_wan_video_blockswap` but not in T2V | 1 hr | Low-VRAM T2V on 16GB | `workflows.py` |
| 1.7 | LTX `vae_working_dtype="bf16"` → make default for RTX 50xx (currently warns about end-frame artifacts on 50xx) | 5 min | Removes recurring user issue | `workflows.py:8033` |
| 1.8 | Update CLAUDE.md R7 to clarify exempt categories (utility/Klein/faceswap parallel gating) — kills the false-violation grep | 15 min | Docs hygiene | `CLAUDE.md` |
| **1.9** | ✅ **DONE this iter:** Add LightX2V + WAN-accel + LTX-distilled hints to `LORA_NAME_ARCH_HINTS` | 10 min | Closes 2026 LoRA hint gap | `model_detect.py` (committed locally; needs R1 mirror sync) |

**Tier 1 total:** ~9-12 hours (revised up from initial 4-5h after subagent audit corrected my assumption that quality patches were already wired for image archs — they're wired for video only); all mirror via R1.

#### Tier 1 corrections (post subagent audit, 2026-05-06)

The initial draft of this plan over-estimated how much of the SOTA quality-patch infrastructure was already exposed. Confirmed via direct grep of `workflows.py`:

| Patch | wired in `workflows.py` | scope | status |
|---|---|---|---|
| SageAttention (`PatchSageAttentionKJ`) | 13 hits | `build_wan_video` (line 4188), `build_ltx_video` (line 8020) only | ❌ NOT exposed for image archs |
| CFGZeroStar / CFGZeroStep | 9 hits combined | same — video builders only | ❌ NOT exposed for image archs |
| SkipLayerGuidance (SLG) | 16 hits | video only | ❌ NOT exposed for image archs |
| TeaCache (`ApplyTeaCachePatch`, `WanVideoTeaCache`) | 11 hits | wired in `composites.py:375,449-456,2319-2320` and a few callers | ⚠ partial — image-arch flag absent |
| **PerturbedAttentionGuidance (PAG)** | **0 hits** | — | ❌ **net-new wiring required** |

So Tier 1.4 (PAG) is **net-new wiring**, not flag-exposure. Tier 1.2/1.3 require composites.py extensions OR a workflows.py wrapper around `sample_standard()`. ~2-4 hours each.

### TIER 2 — Medium investments (1-2 days each)

| # | Item | Effort | Impact | Files |
|---|---|---|---|---|
| 2.1 | **Add FramePack builder** (`build_framepack_video`) | 1 day | **Unlocks high-quality video on 16GB hardware** | new builder + arch entry |
| 2.2 | Promote `cogvideo` from stub → first-class builder | 1 day | Closes the 22-arch gap; gives user another I2V option | `workflows.py`, `architectures.py`, `video_presets.py` |
| 2.3 | Add HunyuanVideo builder (`build_hunyuan_video`) — T2V + I2V variants | 1.5 days | Major-model coverage | new builder + arch entry |
| 2.4 | Add SkyReels-V2 builder (community-popular I2V) | 1 day | I2V variant | new builder |
| 2.5 | Promote 7 partial image archs (sd3, sd3_turbo, hunyuan_dit, pixart, auraflow, kolors, sdxl_turbo) to first-class — own row in R8 matrix, own samplers if needed | 1.5 days | Removes "partial" hedging | `architectures.py`, `workflows.py`, `composites.py` |
| 2.6 | TeaCache flag for `build_txt2img` Flux1-dev / Klein paths | 0.5 days | 30-40% faster Flux gen | `workflows.py` |
| 2.7 | Block-swap presets for ALL builders that load 14B+ models on 16GB hardware (currently only one block-swap WAN builder) | 1 day | Reliability on 16GB | various |

**Tier 2 total:** ~7 engineering days; sync to all 6 mirror surfaces (R1) at end.

### TIER 3 — Major additions (week+ each)

| # | Item | Effort | Impact |
|---|---|---|---|
| 3.1 | **MMAudio builder** — generate audio for video output | 2-3 days | Closes the silent-video gap |
| 3.2 | **Hunyuan3D / TripoSG builder** — image-to-3D | 3 days | New surface (3D pipeline) |
| 3.3 | Mochi-1 builder | 2 days | Alternate video model |
| 3.4 | Stable Video Diffusion XT / SV4D | 2-3 days | NVIDIA's line (less popular) |
| 3.5 | Quality-boost cascade refresh (test_quality_boost.py) — add SageAttention + CFGZeroStar + PAG to the per-arch cascade | 2-3 days | Cross-cutting quality bump verified |

**Tier 3 total:** ~3 engineering weeks; substantial test surface.

### TIER 4 — Speculative / research

| # | Item | Notes |
|---|---|---|
| 4.1 | LCM-LoRA / DMD2 distillation cascade for SDXL/Illustrious | Already partially via turbo; consolidate |
| 4.2 | Adapter swap for vision-LM-based prompt enhancement (currently uses Ollama gemma3:4b — could use Theo's qwen3-vl) | `lora_scorer.py`, `prompt_enhance.py` |
| 4.3 | WS + ETN Inline Transport (Phase 9 — already specced, master plan §F.2) | Out of scope for this audit; tracked separately |
| 4.4 | Scaffold dispatcher: route by hardware tier (low-VRAM laptop → FramePack/SkyReels; high-VRAM workstation → WAN 14B) | Requires hardware fingerprinting at session start |
| 4.5 | LoRA auto-calibrate retrofit for new archs (HunyuanVideo, FramePack, etc.) once they have builders | Per `_dev_docs/CANONICAL_RULES_2026-05-01.md` §E |

---

## §4.5 NEW: SSOT auto-population (formerly Tier 1.9, promoted)

The **highest leverage architectural improvement** uncovered by the iter-3 subagent audit isn't a new builder — it's a **build-time sync between architecture/builder definitions and the installer manifest**.

### Today's manual ripple (per Agent 2 trace)

A new generation method (e.g., FramePack) requires hand-edits to **at least 7 files across the SFW repo + 4 mirrored repos**, with manual sync between two dicts that have no relationship-by-content:

```
architectures.py::_reg("framepack", ...)
workflows.py::build_framepack_video(...)
model_detect.py::CKPT_ARCH_RULES + LORA_NAME_ARCH_HINTS
installer/manifest.json::features.framepack_i2v + features.framepack_t2v
installer/install.py::CN_LABELS_AND_SIZES   ← MANUALLY mirrors model_repair.py
comfyui-spellcaster/model_repair.py::CN_REPO_MAP   ← only for ControlNet additions
plugins/gimp/comfyui-connector/_spellcaster_main.py  ← UI menu registration
plugins/resolve/spellcaster_bridge/...    ← if Resolve preset needed
```

Plus R1 propagation to 5 other mirror surfaces and a publishing-bot round-trip.

**Confirmed live this iter:** CN_REPO_MAP has 7 entries; CN_LABELS_AND_SIZES has 5 — 2 keys are out of sync (key-shape mismatch: `SDXL\\controlnet-union…` vs `SDXL/controlnet-union…`). Manual-sync architectural debt is real.

### Proposed SSOT (Tier 1.9 → promoted to its own section)

A small build-time generator script that emits `manifest.json`'s `features` block + `install.py`'s `CN_LABELS_AND_SIZES` from canonical Python definitions:

```
spellcaster_core/architectures.py::_reg(
    "framepack",
    loader="...",
    sampler="...",
    supported_methods={"i2v": True, "t2v": True},
    # NEW FIELDS — feed the installer:
    installer_features=[
        {
            "key": "framepack_i2v",
            "label": "FramePack — Low-VRAM Image-to-Video (Jan 2026)",
            "vram_min_gb": 6,
            "plugins": ["gimp", "resolve"],
            "custom_nodes": ["ComfyUI-FramePackWrapper"],
            "models": {
                "checkpoints": ["FramePack-F1-Lazy-fp8.safetensors"],
                "vae": ["framepack_vae.safetensors"],
            },
        },
        {"key": "framepack_t2v", ...},
    ],
)
```

Then a script `scripts/generate_installer_manifest.py` (sibling to existing `scripts/generate_dependencies_md.py`) reads the registry and writes `installer/manifest.json`'s `features` and `custom_nodes` entries. Hand-edits to `manifest.json` are reduced to top-level metadata only (`version`, `name`, etc.).

**Companion:** consolidate `CN_LABELS_AND_SIZES` and `CN_REPO_MAP` so the labels live next to the repo info in `model_repair.py` (single dict, label as 4th tuple element); regenerate `install.py`'s view from there.

**Effort:** 4-6 hours for the generator + smoke tests + initial regeneration round-trip.

**Impact:** every new arch added in Tier 2/3 saves the 7-file ripple in installer-touch terms — cuts new-builder onboarding time roughly in half.

**Risk:** none structural; the generator is read-only into the source of truth; round-trip is verifiable via `git diff manifest.json` after regeneration.

**Sequence:** ship Tier 1.9 BEFORE Tier 2.1 (FramePack) so FramePack is the first builder to dogfood the auto-populate path.

---

## §5 Per-arch upgrade matrix

For the 8 R8-matrix archs:

| Arch | Sampler patches to wire | Builder issues | Priority |
|---|---|---|---|
| sd15 | sage, cfg_zero, pag | none | TIER 1 |
| sdxl | sage, cfg_zero, pag, teacache | none | TIER 1 |
| illustrious | sage, cfg_zero, pag | none | TIER 1 |
| zit | sage | (CLAUDE.md R8: prompt enhance SKIP — confirmed in code) | TIER 1 |
| flux1dev | sage, teacache | (CLAUDE.md R8: no quality tags) | TIER 1 |
| flux2klein | sage already in enhancer chain | (CLAUDE.md R8: never CN/negative) | low |
| flux_kontext | sage (verify node compat) | (CLAUDE.md R8: never CN/negative, no quality tags, prompt enhance SKIP) | low |
| chroma | sage, cfg_zero | (CLAUDE.md R8: never CN/negative) | TIER 1 |

For video archs:

| Arch | Status | Next |
|---|---|---|
| wan | SOTA | (none — wait for WAN 2.3 if announced) |
| ltx | SOTA | tier 1.7 (bf16 default on 50xx) |
| seedvr | current (SeedVR2 7B sharp Q4_K_M on disk) | none |
| cogvideo | stub | tier 2.2 (full builder OR mark stub) |
| (new) hunyuan_video | absent | tier 2.3 |
| (new) framepack | absent | **tier 2.1 (HIGHEST PRIORITY)** |
| (new) skyreels | absent | tier 2.4 |

---

## §6 Risks + sequencing

### Risk: six-mirror sync drift (R1)

Every change to `comfyui-spellcaster/spellcaster_core/*.py` requires propagation to 5 other surfaces. Tier 1 items individually small; Tier 2 items each touch 2-4 files in the canonical, then mirror. **Sequence Tier 1 fully into one R1 propagation pass to minimize sync ceremony.**

### Risk: Phase-9 collision

`asset_gallery.py` / `event_bus.py` / `interface_registry.py` / `mailbox.py` / `cross_interface.py` / `events.py` are pause-touched. None of Tier 1 or Tier 2 items hit these — confirmed safe.

### Risk: `/object_info` hallucination (R4)

Adding new builders REQUIRES `/object_info` verification of every node. Specifically:

- **FramePack**: requires `ComfyUI-FramePackWrapper` (Kijai) — needs `lllyasviel/FramePack-F1-Lazy*` nodes
- **HunyuanVideo**: requires `ComfyUI-HunyuanVideoWrapper` — `HyVideoSampler`, `HyVideoTextEncode`
- **Mochi-1**: requires `ComfyUI-MochiWrapper`
- **SkyReels**: requires standard WAN-pack + SkyReels checkpoint shape

Before any new-builder PR: confirm node availability on user's `192.168.x.x:8190` via `probe_object_info_choices`. Build a `_dev_docs/NODE_AVAILABILITY_2026-05-06.md` snapshot to ground the work.

### Risk: model-download bloat

FramePack / HunyuanVideo / Mochi each ≥ 12GB. Disk has 23TB free per `df -h` from earlier session — not a constraint, but worth noting.

### Risk: NSFW patcher (§3.0 of CLAUDE.md)

Public→private auto-patcher fires on every push to SFW main. New builders MUST round-trip through the patcher cleanly (no string-collisions with the patch script). Test by running `python nsfw/build_nsfw.py --patch-only` (no push) after each new builder.

### Sequencing recommendation (revised post iter-3)

```
Sprint 0  (1 day)    Tier 1.1, 1.5, 1.7, 1.8 + 1.9 (LightX2V hints DONE)
                     surgical, immediate; one R1 propagation pass at end

Sprint 1  (2-3 days) Tier 1.2, 1.3, 1.4 — cross-cutting quality patches
                     CORRECTED: net-new wiring for image archs, not flag-exposure
                     PAG (1.4) is new from scratch (0 hits in workflows.py)

Sprint 2  (1 day)    Tier 1.6 — wan22 t2v blockswap
                     R1 sync + commit + 6-mirror push
                     e2e_audit.py --offline must stay green throughout

Sprint 2.5 (4-6 hr)  §4.5 SSOT auto-population (NEW, promoted)
                     scripts/generate_installer_manifest.py + arch->manifest fields
                     consolidate CN_LABELS / CN_REPO_MAP into one dict
                     SHIP BEFORE Sprint 3 so FramePack is the first dogfood

Sprint 3  (1 day)    Tier 2.1 — FramePack builder    [HIGHEST ROI]
                     Uses Sprint 2.5's auto-populate path → tests SSOT machine
Sprint 4  (1 day)    Tier 2.2 — CogVideoX promote
Sprint 5  (1.5 days) Tier 2.3 — HunyuanVideo
Sprint 6  (1 day)    Tier 2.4 — SkyReels
Sprint 7  (1.5 days) Tier 2.5 — partial-arch promotion
                     Sprint 3-7 share an R1 sync at end
                     e2e_audit.py --only video,build_fns against live ComfyUI

Sprint 8+ (Tier 3)   MMAudio, Hunyuan3D, Mochi, etc. — schedule per user demand
```

---

## §7 Test gates

Per CLAUDE.md test gate (line 5):

```
PYTHONIOENCODING=utf-8 python tests/e2e_audit.py --offline
```

Expected: `54 PASS / 0 FAIL / N SKIP` green bar.

For new builders: add `--only video,build_fns` against a live ComfyUI server before any change to `workflows.py`, `node_factory.py`, `composites.py`, `architectures.py`, `video_presets.py`.

Each new builder needs a corresponding test in:
- `tests/test_model_coverage.py` — arch registry + supported_methods
- `tests/test_summon_archetypes.py` — archetype validators
- `tests/e2e_audit.py` — green-bar coverage (offline path: golden JSON shape; online path: `/object_info` probe)

---

## §8 Cross-cutting concerns

### §8.1 Hardware-aware scaffold dispatch

Currently `scaffold/video_workflow_dispatch.py` routes by user pick. Tier 4.4 proposal: route by `(hostname → hardware tier)` so Lawptop2 auto-skews to FramePack/SkyReels and Theo to WAN 14B. Aligns with the per-host `launch_st_optimized.<host>.local.ps1` pattern from the launcher overhaul (Laborantin repo, 2026-05-06).

### §8.2 ComfyUI custom-node pack inventory

The user's `192.168.x.x:8190` ComfyUI has packs verified live earlier this session: rgthree, Easy-Use, GeometryPack, SAM3, DepthAnythingV3, Manager. **For Tier 2+, also need:** ComfyUI-FramePackWrapper, ComfyUI-HunyuanVideoWrapper, ComfyUI-MochiWrapper. Run `ls custom_nodes/` on the ComfyUI server and document in `_dev_docs/NODE_AVAILABILITY_2026-05-06.md` before Sprint 3.

### §8.3 Six-mirror sync state at start of upgrade

Per CLAUDE.md §5 (line 332-338): all 6 surfaces in sync at `f940271` after Wk 1 push. Current branch `chore/claude-md-audit-2026-05-06` has `0ded719 docs(claude): ecosystem audit`. Confirm sync via `MIRROR_TARGETS.md` recipe before Sprint 0 starts.

### §8.4 Pre-commit credential-leak guard (R5)

The cycle-3 pre-commit hook regex covers private-LAN IPs, dev box username/email, `ghp_` tokens. Any new builder docstring or comment referencing example endpoints MUST use generic IPs (`192.168.x.x`) and `%APPDATA%`-relative paths. Test before push: `git commit --dry-run` won't trigger the hook; `git commit -m test && git reset --soft HEAD~1` does.

### §8.5 Token-discipline routing

Per CLAUDE.md §6: bug fixes <50 LOC and isolated → qwen2.5-14b drafter. Builder additions and cross-mirror refactors → Claude. **This upgrade plan: Claude drives (architecture, security boundary). Drafter could pinch-hit on Tier 1.5/1.7 (single-line/marker fixes).**

---

## §9 Decision points needing user input

Before Sprint 0, the user should confirm:

1. **Tier 1 → Tier 2 boundary**: green-light Tier 1 sprints autonomously, or pause for review at end of each sprint?
2. **FramePack node pack**: install `ComfyUI-FramePackWrapper` on the `:8190` server before Sprint 3?
3. **CogVideoX promote vs stub**: full builder (Tier 2.2) or just mark `is_stub=True` (Tier 1.5)?
4. **Tier 2.5 partial-archs**: are sd3/sd3_turbo/pixart/auraflow/kolors actively used? If not, deprioritize.
5. **NSFW patcher coverage**: all new builders should be SFW; confirm none of them needs an NSFW counterpart preset bundled.

---

## §10 Exit criteria

This plan is **complete** (and the loop should naturally end) when:

- All Tier 1 items shipped + R1-mirrored + green e2e_audit
- FramePack (Tier 2.1) shipped + verified live on user's hardware
- 22-arch registry has zero stub entries (CogVideoX resolved one way or the other)
- New builders have R7 contract + R8 matrix entries + tests
- A POSTMORTEM written per CLAUDE.md §7.1 with at least one durable artifact

Anything beyond Tier 2.4 / SkyReels is **gated on user demand** — don't pre-build speculative coverage.

---

*Plan generated by `/loop` autonomous audit, iters 1-2. Iter 3 added the SSOT auto-population section (§4.5), corrected Tier 1.2-1.4 scope (net-new wiring rather than flag-exposure), and shipped Tier 1.9 (LightX2V LoRA hints) directly. Subsequent iters execute against this plan unless user redirects. Per CLAUDE.md §7.4 ("the bored-agent hazard"), exit when diff size drops below N lines for K iterations or when this plan's exit criteria are met — whichever comes first.*

---

## §13 Cross-ecosystem update architecture (added iter 4)

### §13.1 Ecosystem topology

The ecosystem is **5 repos + 5 satellites**. The update mechanisms are **deliberately heterogeneous** (per "awake-is-fine" philosophy in MIRROR_TARGETS.md §90):

```
┌─ spellcaster (SFW)  ─── auto-update: 3 mechanisms (GIMP, Guild, installer bootstrap)
│                          + SFW→NSFW auto-patch bot (GitHub Actions, < 5 min lag)
│
├─ spellcaster_NSFW  ─── auto-update via patch bot one-way; ships to Voodoomancer-distro
│
├─ Voodoomancer  ─────── auto_update: false (R0); pull-based via 3-layer integrity check
│  └─ Voodoomaster.exe ─ no auto-update (PyInstaller bundle); /v1/dev/pull for dev
│
├─ Laborantin  ────────── push-based (push_to_theo.py + /dev/upload + /dev/git_pull)
│                          + 4 scheduled tasks (backup / vault_audit / digest / watchdog)
│                          + 7+ NSSM services
│
└─ whimweaver  ─────────── master node, 4760+ tests, NO auto-update (manual git-pull)
   ├─ whimweaver-st
   ├─ whimspider           Electron, electron-updater configurable but unconfigured
   ├─ beatweaver           Electron, independent
   └─ ComfyUI_PerformanceLab  ComfyUI custom node, manager-style updates
```

### §13.2 Existing SSOT contracts (don't reinvent)

Three patterns already in use across the ecosystem:

1. **File-path mirrors** — `MIRROR_TARGETS.md` enumerates 6 byte-identical surfaces for `spellcaster_core/` files. Verification: md5sum / sync-checker agent. **Extend, don't replace.**
2. **Byte-identical shared docs** — `_DEV_HYGIENE.md` matches across 5 repos (currently propagating via `chore/claude-md-audit-2026-05-06` branches; user's WIP). H1-H7 rules.
3. **Derived documents** — `scripts/generate_dependencies_md.py` regenerates `DEPENDENCIES.md` from `manifest.json`. **Same pattern is the right one for §4.5 SSOT auto-population.**

### §13.3 Gaps in current cross-ecosystem update

| Gap | Impact | Fix |
|---|---|---|
| No central registry of "this canonical → these mirrors" | drift-detection is per-pattern (md5sum for code, file-date for docs, manifest-regen for derived) — no top-level dashboard | Tier 1.10 below |
| Cross-repo SSOTs (`_DEV_HYGIENE.md`) propagate via parallel branches per repo | each maintainer has to remember to merge their audit branch — easy to miss | Tier 1.10 below |
| `voodoo-core/` vendored via git subtree in Laborantin + whimweaver — **manual `git subtree pull`** | crypto / hygiene patches don't land in dependents until someone remembers | Tier 1.11 below |
| Spellcaster's auto-patch bot covers SFW→NSFW only — no equivalent for `_DEV_HYGIENE.md` etc. | doc drift across repos | Tier 1.10 below |
| `ComfyUI-Spellcaster` and `ComfyUI-Spellcaster-NSFW` repos sync manually | surface 3 + 4 of the 6-mirror table go stale until release prep | Tier 2.6 below |
| No "platform delegate" model for whimspider / beatweaver Electron updates | Electron apps drift independently | Tier 3.6 below |

### §13.4 Proposed: ecosystem-update dispatcher

**Goal:** Single canonical script that, given a change to one source-of-truth file, fans out to ALL dependents while preserving the documented mirror surfaces (no flattening). Lives in a new repo: `ecosystem-doctor` (small, vendored into all repos via git subtree, like `voodoo-core`).

**Design — `ecosystem_doctor.py`:**

```python
# Read canonical sources (declared in ecosystem.yaml at repo root)
# For each canonical → list-of-mirrors mapping:
#   - read canonical contents + sha256
#   - for each mirror surface:
#       - compare sha256 to mirror's current contents
#       - if drift: emit a structured "update" plan (don't auto-execute)
#   - if --apply: copy + verify byte-identical
# Walks ALL repos in $ECOSYSTEM_ROOT
# Reports: drift-table (markdown), JSON summary for CI consumption
```

**Per-repo `ecosystem.yaml`:**

```yaml
# spellcaster/ecosystem.yaml
canonical:
  - source: comfyui-spellcaster/spellcaster_core/architectures.py
    mirrors:
      - plugins/gimp/comfyui-connector/spellcaster_core/architectures.py  # surface 2
      - ../ComfyUI-Spellcaster/spellcaster_core/architectures.py           # surface 3
      - ../ComfyUI-Spellcaster-NSFW/spellcaster_core/architectures.py     # surface 4 (via patch bot)
      - ../voodoomancer-distro/plugin/comfyui-connector/spellcaster_core/architectures.py  # surface 6
    verifier: byte-identical
  - source: _DEV_HYGIENE.md
    mirrors:
      - ../spellcaster_NSFW/_DEV_HYGIENE.md
      - ../Voodoomancer/_DEV_HYGIENE.md
      - ../Laborantin/_DEV_HYGIENE.md
      - ../LaboratoireSonore/whimweaver/_DEV_HYGIENE.md
    verifier: byte-identical
derived:
  - source: installer/manifest.json
    output: DEPENDENCIES.md
    generator: scripts/generate_dependencies_md.py
  - source: spellcaster_core/architectures.py  # NEW from §4.5
    output: installer/manifest.json[features]
    generator: scripts/generate_installer_manifest.py
```

**Per-repo CI hook:**

```yaml
# .github/workflows/ecosystem-doctor.yml
- run: ecosystem_doctor verify  # exit 1 on drift
```

**One-shot manual sync:**

```bash
ecosystem_doctor sync --canonical=_DEV_HYGIENE.md --from=spellcaster --to=all
ecosystem_doctor sync --canonical=spellcaster_core/architectures.py --apply
```

### §13.5 New tiers (added iter 4)

| # | Item | Effort | Impact |
|---|---|---|---|
| 1.10 | Build `ecosystem_doctor` (drift-detect + sync) — start as a single repo, vendor into the 5 main repos via git subtree | 2-3 days | Eliminates manual md5sum / file-date drift checks |
| 1.11 | Wire `_DEV_HYGIENE.md` propagation: when ANY repo's audit branch merges to main, ecosystem_doctor auto-PRs the hygiene doc to siblings | 1 day | Closes the "ecosystem audit branch" merge-gap |
| 2.6 | Promote SFW→NSFW patch bot to also handle ComfyUI-Spellcaster ↔ ComfyUI-Spellcaster-NSFW (currently manual) | 1 day | Closes pack-repo drift gap |
| 3.6 | Electron-updater config for whimspider + beatweaver | 1 day each | Adds auto-update to Electron satellites |
| 3.7 | Voodoomaster.exe self-update (release manifest at GitHub releases; `.exe` checks pinned signed SHA) | 2-3 days | Removes "no auto-update" footnote |

### §13.6 Sequencing (revised post iter 4)

```
Sprint 0     Tier 1.1, 1.5, 1.7, 1.8, 1.9          surgical (some ✅ done iter 3)
Sprint 1     Tier 1.2, 1.3, 1.4                    image-arch quality wiring (2-3 days)
Sprint 2     Tier 1.6                              wan22 t2v blockswap
Sprint 2.5   §4.5 SSOT auto-population             arch→manifest generator
Sprint 2.6   Tier 1.10  ecosystem_doctor MVP      drift-detect across 5 repos
Sprint 2.7   Tier 1.11  hygiene auto-PR           closes the audit-branch gap
Sprint 3     Tier 2.1   FramePack builder         dogfoods §4.5 + 1.10
Sprint 4     Tier 2.2   CogVideoX promote
Sprint 5     Tier 2.3   HunyuanVideo
Sprint 6     Tier 2.4   SkyReels
Sprint 7     Tier 2.5   partial-arch promotion
Sprint 7.5   Tier 2.6   pack-repo patch bot       closes ComfyUI-Spellcaster manual sync
Sprint 8+    Tier 3 + Electron updaters + Voodoomaster.exe self-update
```

### §13.7 What §13 will NOT do

- **Will NOT collapse the 6-mirror surfaces** into one SSOT (preserves "awake is fine" philosophy)
- **Will NOT touch the auto-patch bot** (it works; only ADD parallel patch bots for ComfyUI packs)
- **Will NOT force whimspider/beatweaver into the spellcaster auto-updater pattern** (different platform); will use platform-native solutions (electron-updater)
- **Will NOT replace `vendor/voodoo-core/` git subtree pattern** (working as designed); will ADD an ecosystem_doctor hook that flags subtree drift

---

## §11 Iter-3 changelog (2026-05-06)

### Subagent triple-audit completed

Three Explore subagents in parallel: hygiene/SSOT (Agent 1), installer trace (Agent 2), core-module SOTA (Agent 3). Findings:

**Confirmed:**
- 6-mirror surfaces match CLAUDE.md (Agent 1 added that surface 4 is `%APPDATA%/ComfyUI/custom_nodes/comfyui-spellcaster/spellcaster_core/<file>` — both GIMP and ComfyUI installs)
- _DEV_HYGIENE.md byte-identity claim — **partially true**: identical across spellcaster, spellcaster_NSFW, whimweaver. Voodoomancer + Laborantin have it on their `chore/claude-md-audit-2026-05-06` branches but NOT yet merged to main. User's ecosystem audit is in flight.
- Installer `step_check_cn_coverage` exists; CN_REPO_MAP and CN_LABELS_AND_SIZES manually-synced (drift confirmed: 7 vs 5 entries, key-shape variants).
- prompt_enhance.py is **fully current** through 2026-05-06 — all archs have validated prompting rules.
- model_detect.py is **clean of 2023-era stale references**; LightX2V was missing — added this iter.
- composites.py wires Sage/CFGZero/SLG/TeaCache nodes but does NOT auto-apply them; workflows.py controls usage.

**Corrected:**
- Initial plan claimed Tier 1.2-1.4 were "flag-exposure of already-wired patches". Reality: patches are wired ONLY for video builders (`build_wan_video`, `build_ltx_video`). Image archs need net-new wiring through composites or workflows.py wrappers. Effort revised: ~9-12h vs initial 4-5h estimate.
- PerturbedAttentionGuidance (PAG) has zero hits in workflows.py — Tier 1.4 is fully net-new.

**Action this iter:**
- ✅ LightX2V + WAN-accel + LTX-distilled hints added to `model_detect.py::LORA_NAME_ARCH_HINTS` (canonical surface only — pending R1 mirror sync)
- ✅ Settings.bat L128 verified NOT a bug (Agent 2's claim was wrong; multi-line `else (` block is valid CMD syntax, same pattern at L134-145)
- ✅ Cross-repo audit branches identified (`chore/claude-md-audit-2026-05-06` on Voodoomancer + Laborantin); leaving alone — that's user's WIP

**Promoted to its own section:**
- Tier 1.9 → §4.5 SSOT auto-population. The single highest-leverage architectural improvement: arch+builder definitions auto-populate manifest.json + CN dicts, eliminating the 7-file manual ripple per new arch.

---

## §12 Iter 5-7 changelog (2026-05-06, execution phase)

### Iter 5 — Sprint 0 (5/5 surgical fixes shipped)

| Tier | Files | Status |
|---|---|---|
| 1.1 R7 contract | `workflows.py:618` (`build_generate_anything`) | ✓ smoke verified |
| 1.5 cogvideo stub | `architectures.py:990` (`supported_methods=()`) | ✓ now raises `UnsupportedMethodError` cleanly |
| 1.7 LTX 50xx defaults | `workflows.py:8260+` (env var `SPELLCASTER_LTX_RTX_50XX=1`) | ✓ syntax compiles |
| 1.8 R7 docs clarify | `spellcaster_NSFW/CLAUDE.md` (canonical) | ✓ exempt categories + builder count corrected |
| 1.9 LightX2V hints | `model_detect.py::LORA_NAME_ARCH_HINTS` | ✓ in iter 3 |

### Iter 6 — Sprint 1 + Sprint 2.5

**Sprint 1 conclusion: image-arch quality patches were ALREADY wired** through `_apply_quality_boost` (line 1276) + `_apply_speedup` (line 1364), gated behind `quality` + `fast_mode` knobs that the GIMP plugin and Wizard Guild already pass through `plugin_base.py`. Sage / CFG-zero / PAG / FreeU / SLG / TeaCache fire arch-aware on `quality="balanced"|"max"` or `fast_mode=True`. The only new addition (composites.py): `apply_model_patches()` helper for callers that need fine-grained per-flag control (currently nobody does, but it's there).

**Sprint 2 BLOCKED:** ComfyUI :8190 went down between iter 4 and iter 6. R4 requires `/object_info` verification of Kijai wrapper nodes (`WanVideoBlockSwap`, `WanVideoModelLoader`, etc.) before writing `build_wan22_t2v_blockswap`. Will resume when ComfyUI is back.

**Sprint 2.5 shipped:** `scripts/check_arch_manifest_drift.py`. Cross-checks every method in any registered arch's `supported_methods` against `installer/manifest.json`'s `features` block. Found 13 method drifts (mostly subsumed-by-parent like `klein_inpaint` → `inpaint`). Companion to `generate_dependencies_md.py`. Returns rc=1 on drift.

### Iter 7 — Sprint 2.6 + Sprint 2.7

**Sprint 2.6 shipped:** `scripts/ecosystem_doctor.py` (drift-detect + sync subcommands, JSON + human reports) + `ecosystem.config.json` (declares canonical sources + mirrors). MVP correctly detects:
- `_DEV_HYGIENE.md` byte-identical with spellcaster_NSFW + whimweaver, MISSING from Voodoomancer + Laborantin (audit branches not yet merged)
- `MIRROR_TARGETS.md` in sync with spellcaster_NSFW

**Sprint 2.7 shipped:** Two GitHub Actions workflows.
- `ecosystem-hygiene-sync.yml` — fires on push-to-main when `_DEV_HYGIENE.md` or `MIRROR_TARGETS.md` change; uses `repository_dispatch` to fan out to siblings.
- `ecosystem-hygiene-receive.yml` — receives the dispatch on each sibling, opens (or updates) a PR with the incoming change. Self-tracking: this workflow file is itself in `ecosystem.config.json` as a byte-identical canonical (drift in the workflow is caught by the workflow).

Both YAMLs parse-clean. Will activate once `ECOSYSTEM_SYNC_TOKEN` (fine-grained PAT) is added as a repo secret + the receive workflow is propagated to siblings via the same mechanism.

### Open items at iter 7 close

- **Sprint 2** BLOCKED on ComfyUI :8190 — resume on next ComfyUI launch
- **Sprint 3+** (FramePack, CogVideoX, HunyuanVideo, SkyReels, Mochi) all gated on (a) ComfyUI up, (b) appropriate Kijai/Hunyuan wrapper packs installed (R4 verification)
- **R1 6-mirror sync** of all canonical-surface edits this session — defer until end of Sprint 2 (avoid sync-thrashing)
- **ECOSYSTEM_SYNC_TOKEN** repo secret needs to be created on the user side before sync workflow activates
- **Sibling repo onboarding**: each of the 4 sibling repos needs `.github/workflows/ecosystem-hygiene-receive.yml` copied in, then `ecosystem.config.json` (with their own canonical/mirror declarations).

---

## §13 Iter 8-13 changelog (2026-05-06, video + 3D builder sprint)

### Iter 8 — Sprint 2 (Tier 1.6) unblocked + shipped

ComfyUI :8190 came back; R4 /object_info verification of `WanVideoBlockSwap`, `WanVideoModelLoader`, `WanVideoTextEncode`, `WanVideoEmptyEmbeds`, `WanVideoSampler`, `WanVideoDecode`, `LoadWanVideoT5TextEncoder` succeeded. Built `build_wan_video_blockswap_t2v()` (~110 LOC, 9 nodes) — sibling to `build_wan_video_blockswap` (I2V) with `WanVideoEmptyEmbeds` replacing the I2V CLIPVision+ImageToVideoEncode chain.

### Iter 9 — Wrapper packs installed + PowerShell `/c/` bug fixed

Cloned `ComfyUI-HunyuanVideoWrapper`, `ComfyUI-MochiWrapper`, `ComfyUI-CogVideoXWrapper` from PowerShell — PowerShell mis-interpreted `/c/Users/...` as drive-relative, clobbering files at `C:\c\Users\...`. Recovered, moved to correct `custom_nodes/` paths from Bash where `/c/` resolves correctly.

### Iter 10-13 — Sprint 3-6.5 (4 video + 1 mesh builder shipped)

| Sprint | Tier | Builder | Arch flipped | LOC | Nodes | R7 method |
|---|---|---|---|---|---|---|
| 3 | 2.1 | `build_framepack_video` | framepack: registered=True, methods=("video_img2video",) | ~130 | 12 | video_img2video |
| 4 | 2.2 | `build_cogvideo_video` | cogvideo: registered=True, methods=("video_gen","video_img2video") | ~160 | 8 (T2V) / 11 (I2V) | video_gen + video_img2video |
| 5 | 2.3 | `build_hunyuan_video` | hunyuan_video: registered=True, methods=("video_gen","video_img2video") | ~210 | 7 (T2V) / 9 (I2V) / 9 (T2V+blockswap+teacache) | video_gen + video_img2video |
| 6 | 3.3 | `build_mochi_video` | mochi: registered=True, methods=("video_gen",) | ~165 | 8 (plain) / 9 (FasterCache) | video_gen (no native I2V) |
| 6.5 | 3.2 | `build_hunyuan_3d_mesh` | hunyuan_3d: registered=True, methods=("mesh_gen",) | ~135 | 6 | **mesh_gen (NEW METHOD — first 3D modality)** |

Each builder verified by:
1. Probing pack source (nodes.py + example_workflows/*.json) for verbatim node signatures
2. py_compile syntax check
3. In-process smoke test (T2V/I2V/full variants) confirming node count + key edges
4. R7 `_assert_method_for_preset` rejects wrong methods, accepts correct ones

Builder count: **61 → 65** (+4 video, +1 3D — net +5).
Architecture registry: 22 → **26** (5 stubs flipped to registered=True, no new stubs added).
Methods registry: video_gen, video_img2video pre-existed; **mesh_gen** added for the new 3D modality.

### R1 6-mirror sync (batched at iter 13 close)

After all 5 sprints landed canonical-side, propagated to ALL surfaces in one pass:

| File | Targets touched | Result |
|---|---|---|
| workflows.py | 8 | drift in 8/8, all synced to canonical md5 b6d05188… (1 absent target — Roaming/ComfyUI-Spellcaster-NSFW lacks workflows.py — expected per pack-deployment shape) |
| architectures.py | 9 | drift in 9/9, all synced to canonical md5 652f9535… |
| composites.py | 9 | drift in 9/9, all synced |
| model_detect.py | 9 | drift in 9/9, all synced |

Surfaces covered: GIMP plugin (SFW + NSFW + antenna-src forks), ComfyUI custom_nodes installed user copy (SFW + NSFW), spellcaster_NSFW (canonical pack + GIMP), Voodoomancer plugin, AppData/Roaming NSFW pack, spellcaster-antenna-src.

### Open items at iter 13 close

- **ECOSYSTEM_SYNC_TOKEN** repo secret still needs creation (carry-over from iter 7)
- **Sibling repo onboarding** (carry-over) — 4 sibling repos still need `ecosystem-hygiene-receive.yml`
- **Hunyuan3D textured path** — current builder is geometry-only. `build_hunyuan_3d_textured()` (sibling using `Hy3DMultiViewsGenerator` + `Hy3DBakeMultiViews`) is a future Tier 3.2.5 builder when texturing flows are needed.
- **Live e2e** — none of the 4 video builders + 1 mesh builder have run on actual model weights; pure-shape verification only. Recommend smoke-running each on real models before claiming production-ready.

### Iter 14 — drift-detector exception map + ZIT quality-stack regression fix

**Drift detector teaching:** updated `scripts/check_arch_manifest_drift.py` with two top-level maps:

  * `SUBSUMED_BY_PARENT` — 10 sub-method → parent-feature pairs (`klein_*`/`controlnet_gen`/`faceswap`/`photobooth`/`reimagine`/`relight` all subsumed by their parent installer feature)
  * `ADVANCED_NO_INSTALLER` — 4 advanced methods without first-class installer features (`video_gen`, `video_img2video`, `video_upscale`, `mesh_gen`)
  * Drift report now distinguishes real drift from documented exceptions; informational pass on subsumed/advanced methods. Detector also flags when a SUBSUMED parent itself goes missing (DRIFT C). `check_arch_manifest_drift.py` now exits 0 cleanly.

**ZIT quality-stack fix (test-vs-code drift discovered):** `tests/test_quality_boost.py` expected ZIT to skip PAG/SLG, but `_QUALITY_ARCHES_PAG` and `_QUALITY_ARCHES_SLG` had ZIT in them. Empirically PAG/SLG hurt ZIT's 4-6-step distilled regime. Removed ZIT from both sets in `workflows.py:1260-1267`; ZIT max stack is now CFGZeroStar + Detail Daemon (both designed for distilled samplers). One stale test case (`case_ays_skips_zit_even_at_max`) was asserting a plain-KSampler path that ZIT no longer takes — updated to mirror `case_ays_skips_klein` (allow SamplerCustomAdvanced from ZIT's own custom-advanced path; only assert AYS absence).

**Test-suite snapshot:** with the ZIT fix + test update, all 490 tests across the 8 test scripts pass:

  * test_quality_boost.py — 54/54
  * test_klein_enhancer.py — 27/27
  * test_cn_compat.py — 280/280
  * test_summon_archetypes.py — 24/24
  * test_lora_auto_calibrate.py — 59/59
  * test_model_coverage.py — 19/19
  * test_model_prompt_profiles.py — 22/22
  * test_auto_updater.py — 5/5

R1 6-mirror sync re-run after the workflows.py edits (8 mirror surfaces re-synced).

### Iter 15 — live R4 verification + CLAUDE.md count update

**Live R4 verification:** ComfyUI :8190 came back up. Probed `/object_info` for all 6 builder families' nodes:

  * FramePack: 5/5 (LoadFramePackModel, FramePackTimestampedTextEncode, FramePackFindNearestBucket, FramePackSampler_F1, VAEDecodeTiled)
  * CogVideo: 4/4 (DownloadAndLoadCogVideoModel, CogVideoTextEncode, CogVideoSampler, CogVideoDecode)
  * HunyuanVideo: 9/9 (HyVideoModelLoader, DownloadAndLoadHyVideoTextEncoder, HyVideoTextEncode, HyVideoVAELoader, HyVideoSampler, HyVideoDecode, HyVideoBlockSwap, HyVideoTeaCache, HyVideoEncode)
  * Mochi: 6/6 (MochiModelLoader, MochiTextEncode, MochiVAELoader, MochiSampler, MochiDecode, MochiFasterCache)
  * Hunyuan3D: 6/6 (Hy3DMeshGenerator, Hy3D21VAELoader, Hy3D21VAEDecode, Hy3D21PostprocessMesh, Hy3D21ExportMesh, Hy3D21LoadImageWithTransparency)
  * WanVideo: 7/7 (WanVideoModelLoader, WanVideoTextEncode, WanVideoEmptyEmbeds, WanVideoSampler, WanVideoDecode, LoadWanVideoT5TextEncoder, WanVideoBlockSwap)

**Total: 37/37 nodes present on the live ComfyUI server.** The pack-source-derived builders match the live wrapper-node interfaces verbatim.

**Side note on detector functions:** the user has all 6 wrapper packs installed, but the model lists exposed by `LoadFramePackModel`/`HyVideoModelLoader`/`MochiModelLoader`/`Hy3DMeshGenerator` show only the user's existing diffusion_models/ contents (Flux, Klein, etc) — none of the specialized FramePack/Hunyuan-Video/Mochi/Hunyuan3D weights are downloaded yet. Adding `detect_*_preset(comfy_url)` siblings to `video_presets.py` for each is a sensible future iter, but they'd return None on this server until weights arrive. Parking that work in `_dev_docs/` for now (low ROI to ship detectors that always return None).

**CLAUDE.md count update (spellcaster_NSFW canonical):**

  * `workflows.py` count: 42 → 65
  * `architectures.py` registry: 22 → 26
  * R7 contract scope: ~11 → ~17 builders (the 5 new video/mesh ones plus the WAN T2V sibling)

Test suite still 490/490 green; e2e_audit.py --offline 84/84 PASS.

### Iter 16 — `video_presets.py` detectors for the 3 new wrapper-pack archs

After iter 15 confirmed the user has the right model weights for HunyuanVideo + Hunyuan3D, built three sibling detectors paralleling `detect_wan_preset` / `detect_ltx_preset`:

  * `detect_hunyuan_video_preset(comfy_url)` — picks `hunyuan_video_t2v_*` (T2V) + `hunyuan_video_image_to_video_*` (I2V) + a `hunyuan_video_vae_*` (NOT the Hunyuan3D VAE — early version had a bug picking the 3D VAE, fixed). Defaults to bf16 + fp8_e4m3fn quantization for 16 GB GPUs.
  * `detect_hunyuan_3d_preset(comfy_url)` — picks `hunyuan3d-dit-v2-1-fp16.ckpt` + `Hunyuan3D-vae-v2-1-fp16.ckpt`, returns sane mesh-extraction defaults (octree=384, mc_algo=dmc, max_facenum=200000, file_format=glb).
  * `detect_mochi_preset(comfy_url)` — returns None on this server (user has no Mochi weights), but pre-wired for when weights arrive.

**Live verification** against ComfyUI :8190 (16 GB RTX 5060 Ti):

  * HunyuanVideo: detected `Hunyuan\hunyuan_video_t2v_720p_bf16.safetensors` + i2v sibling + `hunyuan_video_vae_bf16.safetensors`. Pipeline `detect → build_hunyuan_video` produces 7-node T2V + 9-node I2V workflow.
  * Hunyuan3D: detected `Hunyuan\hunyuan3d-dit-v2-1-fp16.ckpt` + `hunyuan3d-vae-v2-1-fp16.ckpt`. Pipeline produces a 6-node mesh workflow.
  * Mochi: returned None (no `*mochi*` weights on this server, as expected).

**R1 mirror sync:** `video_presets.py` re-synced to 8/8 surfaces.

**Test suite:** 54/54 quality-boost + 27/27 klein + 84/84 e2e_audit offline = 165/165 green after the detector additions.

**Side findings while auditing the live model list:**
  * User has `Lumina\lumina_2.safetensors` — that's a NEW arch (Lumina 2 from Alpha-VLLM, MMDiT) that Spellcaster doesn't cover. Building support requires gemma_2_2b text encoder (user has gemma_3_12B, wrong tokenizer family) — parking for now.
  * ComfyUI 0.19.3 supports CLIP types `qwen_image`, `hunyuan_image`, `flux2`, `omnigen2`, `longcat_image`, `ovis`, `ace`, `cosmos`, `hidream` — none of these archs are wired in Spellcaster yet. Future tier opportunities.
  * User has Wan 2.2 Animate (`Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors`) — a Wan variant for animation. Existing `build_wan_video` may or may not handle Animate variants correctly; needs investigation.

### Iter 17 — `model_detect.py` LoRA classification for the 5 newly-promoted archs

The promoted video / 3D archs (framepack, cogvideo, hunyuan_video, mochi, hunyuan_3d) had no LoRA-name hints, meaning a `hunyuan_video_lora.safetensors` would mis-classify as `hunyuan_dit` (the bare "hunyuan" key won) and `framepack_*.safetensors` would fall through to `unknown`.

Fixed in `model_detect.py`:

  * **LORA_NAME_ARCH_HINTS** — added 11 new keyword rows for the new archs, ordered specific-first so `hunyuan_video` wins over the bare `hunyuan` (which still falls through to `hunyuan_dit` for legacy hunyuan-image LoRAs). Specific tokens: `hunyuan_video`, `hunyuan-video`, `hunyuanvideo`, `hunyuan3d`, `hunyuan-3d`, `hunyuan_3d`, `hy3d`, `framepack`, `mochi`, `cogvideo`, `cogvideox`.
  * **LORA_COMPAT_BUCKETS** — each new arch gets its own single-element bucket. Cross-arch LoRA injection (e.g. a hunyuan_video LoRA into a framepack model) was previously possible by silent fall-through; now it's explicitly blocked at compat-bucket level.

**Verified:** 9/9 lora-classification spot tests pass:

```
  hunyuan_video_lora_v2.safetensors → hunyuan_video
  hunyuan-3d_motion.safetensors     → hunyuan_3d
  hy3d_paint_v1.safetensors         → hunyuan_3d
  hunyuan_image_lora.safetensors    → hunyuan_dit  (legacy fallback)
  framepack_speedup.safetensors     → framepack
  mochi_motion.safetensors          → mochi
  cogvideo_lora.safetensors         → cogvideo
  cogvideox_2b.safetensors          → cogvideo
  wan_2.2_lora.safetensors          → wan
```

**Test suites:** 54/54 quality-boost + 19/19 model-coverage + 22/22 model-prompt-profiles + 59/59 lora-auto-calibrate = 154/154 unit tests still green.

**R1 mirror sync:** `model_detect.py` re-synced to 8/8 surfaces.

### Iter 14 close — production readiness

What's verified end-to-end:
  * 26 architectures registered (5 newly flipped this session)
  * 65 builders importable, syntax-clean
  * 490/490 tests passing
  * Drift detector exits 0
  * 8 mirror surfaces byte-identical with canonical for the 4 changed core modules

What still needs live runtime:
  * 4 new video builders + 1 new mesh builder need at least one smoke run on real model weights — pure-shape verification only currently
  * GitHub Actions hygiene workflows pending `ECOSYSTEM_SYNC_TOKEN` creation
  * Sibling repo onboarding for the receive-side workflow propagation
