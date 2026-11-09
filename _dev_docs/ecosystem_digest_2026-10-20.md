# Ecosystem digest — 2026-10-20

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `ed19fb4`). Branch: `claude/adoring-allen-7g5oiz`.

## Delivery notes

- **Previous digest unmerged on main.** The 2026-10-16 digest
  (`75ef09a`) landed as a chore commit on `main` through the normal
  merge path, so this run starts on a clean tree, not stacked on an
  open PR.
- **Routine health.** `tools/upgrade_research.py --dry-run` is green
  (`4 proposals from 5 backends`, written to `_dev_docs/upgrade_research/
  2026-W43.{md,json}`). No skeleton draft needed this run — the tool
  continues to be present and dry-run-clean.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`, so
  `tools/upgrade_research.py`'s live `backend_huggingface` /
  `backend_civitai` are still unusable from here. Hugging-Face MCP
  (`hf_fs`, `hub_repo_details`) remains the only live path from this
  sandbox. ~7 MCP calls spent of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — pattern list in `.githooks/leak-patterns`
  unchanged since 2026-10-16's run cleared it; the digest + the one
  new `tools/audit_disk_vs_registry.py` added by this run do not
  introduce new secret-adjacent surfaces.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose
fix is in this branch and whose regression suite passes
(`pytest tests/` → **57 passed**, up from 52 at 2026-10-16 as the
intervening v2.4 Spark2 feature-set landed its own tests).

### T1-a `architectures.py` docstring: Image/Video/Other sections stale again

Between 2026-10-16 and now, commit `4b1e1c0` (`feat(v2.4): full Spark2
GB10 NVFP4/FP8/INT8 image & video model support across all plugins`)
+ `0e63dc1` + `ed19fb4` added **8 more fully-registered archs** on
top of the 21 the 2026-10-16 docstring enumerates:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image` (4 new, all
  Flux2/Flux3/Qwen family — `_reg(...)` calls at lines 768, 813, 865,
  911 in the current source).
- Video: `minimax_h3`, `skyreels`, `longcat` (3 new, all video gen).
- Other: `aurasr` (1 new, GAN-based 4x upscaler).

Docstring now enumerates **29 fully-registered** + 6 stubs = **35
built-in** arches. (`audit_disk_vs_registry --dry-run` reports 30
registered + 6 stubs = 36 because the custom-arch registry loader
adds `my_custom_model` — not a built-in and left out of the
docstring list.) Identical edit applied to both mirrored copies —
mirror-drift stays byte-identical: `python tests/mirror_drift.py`
→ `OK: 32/32   DRIFT: 0`.

### T1-b `tools/upgrade_research.py`: HF arch-query map is missing 8 archs (again)

Same bug class the 2026-10-16 run fixed for 12 archs; the v2.4 PR
added 8 more arches to `architectures.py` without touching
`_HF_ARCH_QUERIES`, so a live `huggingface` or `civitai` backend run
would silently skip candidate research for them.

Added mappings for: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`,
`minimax_h3`, `skyreels`, `longcat`, `aurasr`. All 8 placed in
registry source order near their siblings so a future diff reads
cleanly.

### T1-c `tools/upgrade_research.py` docstring: method count stale (75 → 78)

Previous digest bumped `70` to `75 as of 2026-10-16`. The v2.4 PR
pushed the live count to **78** per
`python tools/build_builders_manifest.py --check` (`manifest fresh
(78 methods)`). Bumped to `78 as of 2026-10-20`.

### T1-d `tools/audit_disk_vs_registry.py`: ship the retire-weights audit

The 2026-10-16 digest's **follow-up #1** named this tool as a prime
Tier-1 candidate: *"a ~100-line Tier-1 candidate for a future
digest: read architectures.py + walk ComfyUI/models/*, print paths
matching registered=True arches that have more than one weights
candidate on disk."* Written and shipped in this PR, 275 lines
including docstrings and the arch-keyword table.

Shape:

- Loads the registry from `comfyui-spellcaster.spellcaster_core.
  architectures.ARCHITECTURES`.
- Walks the resolved models root (precedence: `--models-root` arg →
  `$COMFYUI_MODELS_DIR` → Windows `D:\LLM\ComfyUI\models` →
  `~/ComfyUI/models` → refuses).
- Attributes each weights file to an arch by (1) exact basename match
  against the arch's `extra["clip_name"] / vae_name / clip_fallbacks`
  (registry is ground truth), (2) keyword probe over
  `_ARCH_FILENAME_KEYWORDS` + the arch_id itself. Fallthrough =
  orphaned.
- Reports three sections: **REDUNDANT** (same arch, >1 weight on
  disk — retirement candidates), **ORPHANED** (weights with no arch
  attribution — move to quarantine before deletion), **MISSING**
  (registry declares a canonical filename that isn't on disk —
  coverage gap or stale `extra` dict).
- `--dry-run` reports only the registry size + resolved root (no
  filesystem walk) so it's smoke-testable from the cloud sandbox
  without fleet disk access. `--json` emits a machine-readable
  format for Hermes consumption.
- Read-only: never deletes or moves anything. The report is the
  deliverable; retirement is a separate manual (or Hermes-driven)
  step.

Smoke-tested in cloud: dry-run exits 0 and prints
`registry: 30 fully-registered + 6 stubs = 36 total  resolved_root:
(none — pass --models-root or set COMFYUI_MODELS_DIR)`. Also
exercised against a synthetic temp directory with duplicates and an
orphan — correctly classified `flux-3-image-klein.safetensors` +
`flux3klein-fp8.safetensors` as redundant under `flux3klein`, and
flagged a nonsense filename as orphaned.

**Verification of T1-a through T1-d**

- `pytest tests/` — **57 passed in 10.72s**.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same `4
  proposals from 5 backends` shape as before the arch-query map
  expansion.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tools/build_builders_manifest.py --check` — `manifest
  fresh (78 methods)`; no manifest regen required (the T1-c change
  is docstring-only, no builder churn).
- `python tools/audit_disk_vs_registry.py --dry-run` — exit `0`,
  reports 30 fully-registered + 6 stubs; `--dry-run --json` emits
  the same as a JSON payload.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hf_fs search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **OpenMOSS-Team/MOSS-Image-SFT** + **Comfy-Org/MOSS-Image** | 2026-10-19 | NEW `moss_image` arch — a 5B diffusion-transformer specialised for **text-rich / layout-coherent** image synthesis (typography-first) | ~11 GB fp16 (5.08B params per `hub_repo_details`), ~3 GB NVFP4 | medium | 2 | Biggest new entry since last digest. Apache-2.0 (fully open license, unlike Krea-2's "other"). HF paper id `2610.23374` ("MOSS-Image Technical Report") landed 2026-10-16, 73 upvotes. The **Comfy-Org/MOSS-Image** repackage is `diffusion-single-file` with **924.6K downloads in <72 hours** — a very fast adoption curve. Fits the empty niche between flux3klein (general photorealism) and zit (fast prompt-tag anime): typographic / UI-mockup / poster workflows. Would land as `_reg("moss_image", _, loader="unet_clip_vae", clip_mode="single_moss", ...)` plus a `build_moss_image_txt2img` + `_poster` + `_ui_mock` family. Decision point: does the fleet want this as a sibling to flux3klein (adds ~11 GB) or wait until the Spark2 NVFP4 variant (see Tier-3 queue below, `shayudabiaoge/MOSS-Image-SFT-NVFP4`) proves out and lands at ~3 GB? |
| **lodestones/MOSS-Image-SFT-8-steps-dmd** + **akhaliq/MOSS-Image-SFT-4-steps** | 2026-10-17 / 2026-10-20 | Fast-step companions to `moss_image` — DMD + Turbo distillations | ~11 GB fp16 (same params, step-count shift) | low | 2 | Already community-distilled on day 2 of release. 54.8K + 6.7K downloads respectively. If `moss_image` lands at all, the 8-step DMD is the obvious few-step default (same strategy flux2klein uses — distill the slower base). Pairs with the base arch registration in the same PR, no additional ArchConfig needed. |
| **nvidia/Qwen3.8-Flash-Next-FP4-Local** | 2026-10-15 | NEW LM Studio–loadable VLM for `llm_delegate.py` — Qwen3.8-Flash-Next quantised to FP4 by NVIDIA ModelOpt | ~48 GB FP4 (96.5B params per details) | medium | 2 | 7.3K downloads / 254 likes. This is the Spark2-native (NVFP4) quantisation of Qwen3.8-Flash-Next (image-text-to-text / VLM). Delegating prompt enhancement + metadata enrichment to a Spark2-local VLM — rather than LM Studio on an unlanded host — would unlock `llm_preflight.py`'s stricter model-context manifest for the newer archs (krea2, qwen_image, flux3klein) whose prompt styles are poorly covered by the current prompt-style LLM pool. Decision: does the Spark2 48 GB VRAM headroom (post NVFP4 image/video model load) have the capacity for a 48 GB FP4 companion? If not, downgrade to the smaller `Qwen3.8-27B` the 2026-10-19 base model offers (not Spark-tuned). |
| **deepseek-ai/DeepSeek-V4.1-Flash-1017** | 2026-10-17 | NEW top-tier open VLM — DeepSeek V4.1 Flash, image-text-to-text | depends on quant | medium | 2 | 27.7K downloads / 1880 likes in 72 hours — currently the hottest open VLM release. Base weights only, no official Spark NVFP4 variant yet, so landing it on the fleet requires a FP4/INT8 quant to appear first. Watch; file a Tier-3 download action once a Spark-ready quant surfaces. |
| **tencent/Hy-Memory-30B-A3B** | 2026-10-16 | NEW text-generation with persistent memory primitives (A3B = 30B total / 3B active MoE shape) | ~15 GB fp16 (A3B active) | medium | 2 | 2.1K downloads / 239 likes. "Hy-Memory" is Tencent's take on an agent-oriented LLM with built-in memory. Not a drop-in replacement for anything in the current `llm_delegate.py` pool (Mistral / Qwen3 / Hermes3). Interesting mostly for whether spellcaster's own operator-memory flow (prompt-DB + whimweaver replay) could ride a model-native memory substrate rather than the current prompt-DB JSON. Design-level question, not a Tier-1 change. |
| **LiquidAI/LFM2.5-24B-A2B** + GGUF | 2026-10-13 | NEW `llm_delegate.py` candidate — Liquid Foundation 2.5, 24B total / 2B active | ~12 GB fp16 (A2B active), ~6 GB Q4 GGUF | low | 2 | 512 + 226 likes / 15.4K + 132.8K downloads. The **A2B shape (2B active)** fits spellcaster's "fast prompt-enhancer" niche in `llm_delegate.py` better than any current Qwen3 variant, with less VRAM pressure. GGUF variant is LM-Studio-loadable today. Would wire in as a model-choice option behind the existing LM Studio hook, same as the 2026-10-16 digest's Z-Image prompt-engineer entry. |
| **Lightricks/LTX-2.5** (**STATUS UPDATE**) | 2026-10-11 | Direct upgrade for `_reg("ltx", ...)` — still open from 2026-09-22 Tier-3 queue | ~22 GB fp16 (22B params) | medium | 2 (restated) | **Now 8,570 likes / 2.03M downloads** — up from 8,035 / 1.9M at 2026-10-16. Trending #10 on HF today. Gated=auto; needs `huggingface-cli login` on the fleet host. The three LoRA adapters this digest's 2026-10-16 predecessor filed (Alpha-Gen, Pixel-Spatial-Upscaler, Refine-Details, Ingredients) all depend on this base. Still blocked on the fleet-side download. |
| **Comfy-Org/Krea-2** (**STATUS UPDATE**) | 2026-10-16 | Confirms the drop-in weights for `_reg("krea2", ...)` registered at `architectures.py:865` | ~11 GB fp16 (same params as the base `krea/Krea-2-Raw`) | low | 2 (restated) | **Now 721 likes / 15.9M downloads** — a very strong signal that the `krea2` registration ships into a model with real adoption, not vapourware. License is "other" (krea-specific terms, not Apache). Diffusion-single-file. Decision: file as Tier-3 download for the fleet now, so when the first `build_krea2_*` production flow lands the weights are already in place. (Added to Tier-3 queue below.) |

### Tier-2 non-model finding

- **Dedup / tiering of the MOSS-Image track.** Already — within 72
  hours of release — the ecosystem has forked MOSS-Image across
  diffusers / single-file / GGUF / NVFP4 / INT4 / MLX / 4-step
  turbo / 8-step DMD. If `moss_image` lands at all, the operator
  decision to make before any weights go to the fleet is: pick
  **one** quant lane per host (Spark2 → NVFP4, LAN LM-Studio hosts →
  GGUF Q4 or 8-step DMD) and skip the rest, so the fleet doesn't
  carry three 11-GB copies of a model that's one apache-2.0 base. The
  2026-10-16 digest's Qwen-Image-2.1 dedup note is the same shape of
  decision and remains unresolved (base vs Turbo vs GGUF vs Uncensored
  variants).

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 + 2026-09-22 entries, plus
this run's new ones. A local Hermes / operator process consumes this
block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-10-20 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/MOSS-Image
    target_host: spark1
    reason: "MOSS-Image is the biggest new text-to-image release since Flux-3-Klein (2026-10-16) — 924K downloads on the Comfy-Org repackage in 72 hours, Apache-2.0, specialised for text-rich / layout-coherent images (typography, posters, UI mocks). Diffusion-single-file, drops straight into ComfyUI/models/checkpoints/. Would seed a new _reg('moss_image', ...) + build_moss_image_* family (see Tier 2)."
    command_hint: "huggingface-cli download Comfy-Org/MOSS-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MOSS-Image"
    risk: low

  - action: download_and_evaluate_model
    target_repo: lodestones/MOSS-Image-SFT-8-steps-dmd
    target_host: spark1
    reason: "8-step DMD distillation of MOSS-Image-SFT for the 12-GB tier. Same arch as the base; pairs with the Comfy-Org download above. 54.8K downloads already, which is the signal the community has picked this over the 4-step Turbo as the production fast path."
    command_hint: "huggingface-cli download lodestones/MOSS-Image-SFT-8-steps-dmd --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MOSS-Image-SFT-8-steps-dmd"
    risk: low

  - action: download_and_evaluate_model
    target_repo: shayudabiaoge/MOSS-Image-SFT-NVFP4
    target_host: spark2
    reason: "NVFP4 quant of MOSS-Image-SFT for the GB10 / Spark2 (NVFP4) hosts — fits the ~3 GB VRAM footprint tier spellcaster targets on Spark2 for the FP4 image/video stack. License=unknown on the repo tags, verify before fleet download. If declared Apache-2.0 (matching the base), proceed."
    command_hint: "huggingface-cli download shayudabiaoge/MOSS-Image-SFT-NVFP4 --local-dir D:\\LLM\\ComfyUI\\models\\unet\\MOSS-Image-NVFP4"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Krea-2
    target_host: spark1
    reason: "Confirms the weights for the already-registered _reg('krea2', ...) arch at architectures.py:865. 15.9M downloads, 721 likes — hottest active image checkpoint on HF today. Needed before any build_krea2_* production flow can run; filing now so when that flow lands the fleet is primed."
    command_hint: "huggingface-cli download Comfy-Org/Krea-2 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Krea-2"
    risk: low

  - action: download_and_evaluate_llm
    target_repo: LiquidAI/LFM2.5-24B-A2B-GGUF
    target_host: unknown
    reason: "LM Studio–loadable 24B/A2B (2B active) Liquid Foundation 2.5, Q4 GGUF. Fits the 'fast prompt-enhancer' niche in llm_delegate.py better than any current Qwen3 variant. 132K downloads on the GGUF repo — community-vetted."
    command_hint: "huggingface-cli download LiquidAI/LFM2.5-24B-A2B-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\LM-Studio\\models\\LFM2.5-24B-A2B-GGUF"
    risk: low

  - action: evaluate_llm_for_delegate_pool
    target_repo: nvidia/Qwen3.8-Flash-Next-FP4-Local
    target_host: spark2
    reason: "Spark2-native (NVFP4) VLM. Would delegate prompt-enhancement + metadata enrichment to a Spark2-local model, unblocking llm_preflight.py's stricter manifest for krea2 / qwen_image / flux3klein which the current LM-Studio prompt-style LLM pool poorly covers. Decision point: does Spark2 have 48 GB VRAM headroom AFTER the NVFP4 image/video stack loads?"
    command_hint: "# Capacity-plan first; this is 48 GB FP4. If OK:\nhuggingface-cli download nvidia/Qwen3.8-Flash-Next-FP4-Local --local-dir D:\\LLM\\LM-Studio\\models\\Qwen3.8-Flash-Next-FP4"
    risk: medium

  # ─── Carried over from 2026-10-16 (still open) ─────────────────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein lands as the direct successor to _reg('flux2klein', ...) in architectures.py — AND the _reg('flux3klein', ...) at line 813 is already registered in this repo, so this is purely a weights-fetch to light up what the registry promises. Comfy repackage is diffusion-single-file. Gated=auto on HF — needs huggingface-cli login on the fleet host once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Fast distilled companion to the Qwen-Image-2.1 base already queued from 2026-09-22. Prefer the GGUF path (unsloth/Qwen-Image-2.1-Turbo-GGUF, 294K downloads) for the 12-GB tier — base repo is diffusers-only. Still open on fleet."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet, just a path check. Still open."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Weights-only drop-in for the already-wired build_sam3_segment, IF the SAM3Segment ComfyUI node loader accepts 3.1-shape weights at the same path. Audit above runs first."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on top of LTX-2.5. Depends on LTX-2.5 base weights (still-open Tier-3 download). ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. Also depends on the LTX-2.5 base. ~2 GB."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  # ─── Carried over from 2026-09-22 (still open) ─────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Base Qwen-Image-2.1 arch — superseded on the community side by the Turbo distill. If the fleet picks the full-quality lane rather than the few-step one, this is still the right weights to grab."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). Now 2.03M downloads / 8570 likes — confirmed dominant open-source i2v. Gated=auto; needs HF login the sandbox doesn't have."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for existing _reg('hunyuan_3d', ...); current build_hunyuan_3d points at 2.0-shape weights, 2.1 mesh+texture pipeline may need node-list audit before the swap."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Enables build_controlnet_gen on the zit arch (currently an empty cn list)."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. T1-b this run adds 8 more arches (flux2dev/flux3klein/krea2/qwen_image/minimax_h3/skyreels/longcat/aurasr) to the HF arch-query map, so a LAN rerun will now probe 34 arches instead of 26."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: run_disk_vs_registry_audit
    target_repo: null
    target_host: unknown
    reason: "T1-d this run shipped tools/audit_disk_vs_registry.py. Running it from the fleet now surfaces the retire-weights decision the Flux-3-Klein / LTX-2.5 / Qwen-Image / MOSS-Image fleet downloads above all depend on. First run is read-only (REPORT ONLY, no deletions)."
    command_hint: "python tools/audit_disk_vs_registry.py --models-root D:\\LLM\\ComfyUI\\models > D:\\LLM\\audit_2026-10-20.txt"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **Transport fallback for `tools/upgrade_research.py` (still open).**
   Carries over from 2026-10-16's follow-up #2 and 2026-09-22's. The
   tool's HF + civitai backends still use `urllib`, which the cloud
   proxy 403s. Teaching the `huggingface` backend to prefer an MCP
   transport when one is available would let *this* routine run the
   ranked backend from the cloud instead of the dry-run skeleton.
   Doable but it broadens the tool's dependency surface, so still
   not shipped. One concrete design — add a `--mcp` flag that routes
   HF queries through `mcp__Hugging-Face__hub_repo_search` via a
   stdio sidecar — could be prototyped in ~200 lines next run as a
   Tier-1 candidate, but needs an operator call on whether the extra
   surface is wanted.

2. **`moss_image` arch registration path.** When the operator decides
   on the quant lane (Tier-2 non-model finding above), the shape of
   `_reg("moss_image", ...)` is a Tier-1-sized change (one ArchConfig
   entry + extra dict for the single-file loader + a
   `build_moss_image_txt2img` matching the diffusion-single-file node
   contract, visible already in the `Comfy-Org/MOSS-Image` repo
   tags). Not shipped here because the clip_type / clip_name /
   latent-shape fields need an operator read of the model card before
   they're finalised — guessing from the paper abstract and the
   diffusers pipeline name (`MOSSImagePipeline`) is thin ground.

3. **`audit_disk_vs_registry.py` extension — retirement proposal.**
   T1-d shipped the read-only audit. The natural next step is a
   `--propose-retirements` mode that reads the audit output and,
   using arch registration dates + download counts, writes a
   suggested-retirement list to stdout (never deletes). Deferred
   because the "which weight to retire from a REDUNDANT row" question
   needs operator policy input — defaulting to "newest release wins"
   has already bitten calibrations in the past.

4. **`qwen_image` encoder path verification.** The registry has
   `extra["clip_name"]: "nvfp4/qwen_2.5_vl_7b_nvfp4.safetensors"` at
   `architectures.py:954`. The current base model
   (`Qwen/Qwen-Image-2.1-Turbo`) now has a Turbo variant that may
   expect a different encoder path. If the fleet download picks the
   Turbo lane (see Tier-2 dedup note), the `extra` dict here needs a
   corresponding update. Easy Tier-1 fix once that call is made —
   left here as a watch item.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py
--dry-run`; AST scans of `architectures.py`, `workflows.py`,
`builders_manifest.json`; `pytest tests/`;
`tools/audit_disk_vs_registry.py --dry-run`._
