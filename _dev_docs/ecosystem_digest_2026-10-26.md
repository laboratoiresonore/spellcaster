# Ecosystem digest — 2026-10-26

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `ed19fb4`). Branch: `claude/adoring-allen-l0f2bo`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest (`75ef09a`) is on
  `main`, so this run starts from a clean slate rather than stacking
  on an open queue.
- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`,
  methods-in-scope now `78`). No skeleton draft needed this run.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`, so the
  live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here;
  Hugging-Face MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`) is
  the live path from the cloud this run uses. ~8 MCP calls spent of
  the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Tool-count canonicalization.** `tools/build_builders_manifest.py`
  reports `78 methods` on current `main`; the previous digest ran at
  `75`. Front-matter docs still said `75`, so the mismatch is this
  run's T1-a fix below.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
57/57).

### T1-a `README.md` + `DEEP_DIVE.md`: tool count stuck at 75 (now 78)

Canonical builder count is `78` (`python tools/build_builders_manifest.py`
→ `wrote … (78 methods)`), but every front-matter doc still said `75`
(the count the 2026-10-16 digest shipped at). Four `build_*` methods
have landed on `main` since then — the Spark2 GB10 NVFP4/FP8/INT8 push
(`4b1e1c0`) plus the two SPELLCASTER_STEER / E2 model-manifest commits
(`0e63dc1`, `ed19fb4`) are the ones that moved the number.

Updated **8 occurrences in `README.md`**: hero tagline, the five
`DEEP_DIVE.md#all-75-tools` anchor links, the "`→ 75 tools across 19
models`" caption, the GIMP-menu caption at line 330.

Updated **3 occurrences in `DEEP_DIVE.md`**: ToC entry
(`- [All 75 Tools](#all-75-tools)`), mermaid node
(`GIMP[🖌 GIMP 3<br/>75 tools<br/>~34K Python lines]`), the section
header (`## All 75 Tools`) that is the actual link target — all moved
together, so the anchors in README still resolve.

`19 models` left as-is: that is the "powered by" count (image + video
+ 3D model *families* in the hero banner, not the full arch count,
which is 29 fully-registered + 6 stubs = 35 — see Follow-up #1
below).

### T1-b `tools/upgrade_research.py`: `_HF_ARCH_QUERIES` map missing 8 arches

The map now in `main` has 27 entries. The registry on disk has 35
`_reg()` entries (29 fully-registered + 6 stubs); 8 arches land on
`main` with no query-term entry at all:

- `flux2dev` (registered 2025-11-25 era, non-distilled Flux 2)
- `flux3klein` (registered after the 2026-10-16 digest's Tier-2 note
  — Flux 3 Klein is now in the registry; see Follow-up #3 for the
  non-destructive migration shape)
- `krea2` (image arch)
- `qwen_image` (base Qwen-Image / Qwen-Image-2.1 arch)
- `minimax_h3` (video arch)
- `skyreels` (video arch)
- `longcat` (video arch)
- `aurasr` (image upscaler)

Without a `_HF_ARCH_QUERIES` entry, the HF/civitai backends silently
skip candidate research for those `build_*` methods. Added mappings
in the same shape as the previous digest's T1-c expansion. Also
broadened the existing `wan` entry's note is unchanged (`wan-2.1`,
`wan2-i2v`, `wan2.2` still cover the current fleet; `wan2.5` turned
up zero HF hits this sweep, so not pre-wired).

Also bumped the stale method-count claim in the module docstring:
`"75 as of 2026-10-16"` → `"78 as of 2026-10-26"`.

Verification: `python tools/upgrade_research.py --dry-run` still exits
`0`, same shape (`4 proposals from 5 backends`); `pytest tests/` →
`57 passed in 7.80s`.

### Verification of T1-a and T1-b

- `pytest tests/` — `57 passed in 7.80s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same shape
  as before the map expansion.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  manifest already current, no regen needed.
- `grep -nE "75[- ]?(AI )?tool|all[- ]?75|75 build|75 method"` across
  `README.md`, `DEEP_DIVE.md`, `VIBECODER.md`, `DEPENDENCIES.md`,
  `tools/upgrade_research.py` — no hits remain.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest (2026-10-26, late UTC).

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **OpenMOSS-Team/MOSS-Image-SFT** + **MOSS-Image-Base** + **Comfy-Org/MOSS-Image** | 2026-10-21 | NEW `moss_image` arch — a 5.08B-param text-to-image model from OpenMOSS, Apache-2.0, text-encoder is Qwen3.5 (see `Ouinche/moss-image-qwen3.5-te-mlx-q8g64`). Not a replacement for any existing arch — this is a fresh family alongside Flux / Qwen-Image / Z-Image. | ~10 GB fp16 (5.08B params) | medium | 2 | 747 + 565 likes on the Base + SFT repos; **2.4M downloads** on `Comfy-Org/MOSS-Image` repackage in <1 week, which is the dominant integration path (`diffusion-single-file` → drops into `ComfyUI/models/checkpoints/`). Variants already surfaced: 4-step turbo (`akhaliq/moss-image-4-step-turbo` Space), 8-step DMD distill, image-edit LoRA (`PedroMarinhoDev/Moss-Image-Edit-ComfyUI`), INT4 ConvRot quant (`toxicdog/MOSS-Image-SFT-INT4-ConvRot-ComfyUI`). English + Chinese prompt support. Would land as `_reg("moss_image", ...)` with a Flux-shape sampler config (checkpoint-loader-based, since the comfy repackage is single-file). Decision point: which SFT or Base weights to pin as the default on the fleet, and whether the 4-step turbo distill shape warrants a sibling `build_moss_image_turbo_*` family. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR** | 2026-09-28 | NEW adapter on top of LTX-2.5 — SDR→HDR video grading, pairs with the Alpha-Gen + Upscaler + Refine-Details adapters already filed in 2026-10-16's Tier-2 | ~2 GB (adapter) | low | 2 | 46 likes / 13.7K downloads. Published by Lightricks, same license + distribution contract as the base 2.5 model. Would land as `build_ltx_sdr_to_hdr_video` on the existing `_reg("ltx", …)` entry. Only ships value once LTX-2.5 base weights are on the fleet (still a pending Tier-3 download from 2026-10-16). |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 | NEW adapter — camera-control / layout-aware rendering on LTX-2.5 | ~2 GB (adapter) | low | 2 | 116 likes / 13.2K downloads. Camera-control is a distinct capability from the existing wan/ltx builders. Would land as `build_ltx_layout_to_render_video`. Pairs with Alpha-Gen for a complete "VFX plate" set on LTX-2.5. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Restore** | 2026-09-27 | NEW adapter — video restoration + colorization + archive-footage grading on LTX-2.5 (tagged `ltx-2.3`, `ltx-2.5`, both base weights supported) | ~2 GB (adapter) | low | 2 | 78 likes / 9.2K downloads. Overlaps conceptually with the existing `supir` image upscaler (which is image-only) and `seedvr` (which is a video restorer with different style). The three-way comparison before shipping is: `seedvr` vs. LTX-2.5-Restore vs. SUPIR-pass-per-frame — ask operator which is default for `build_ltx_restore_video`. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate** | 2026-09-09 | NEW adapter — object removal / clean-plate generation on LTX-2.5 | ~2 GB (adapter) | low | 2 | 38 likes / 7.2K downloads. VFX workflow — the clean-plate adapter removes an object across a shot. Would land as `build_ltx_clean_plate_video`. Pairs with Alpha-Gen (matte extraction) → Clean-Plate (background fill) as a two-step VFX pipeline on the DaVinci Resolve plugin side. |
| **Comfy-Org/SeedVR2** | 2026-06-06 | Comfy repackage of ByteDance's SeedVR2 — the current `_reg("seedvr", …)` builder may still be loading an older 1.x build; this is the dominant 2.x drop-in | ~6 GB (3B variant) / ~14 GB (7B variant) | low | 2 | **663.3K downloads** / 141 likes on the Comfy-Org repackage; 674.9K / 327 likes on `numz/SeedVR2_comfyUI`. The question for the operator is whether `build_seedvr_*` currently points at the 1.x or 2.x shape — if 1.x, this is a weights-only swap on the fleet with no code change on the connector side (same ComfyUI node, newer weights). One-line fleet audit required. |
| **BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4** | 2026-02-04 (updated 2026-10-15) | Carried over from 2026-10-16; downloads now at 4.7K / 168 likes (was 5.4K / 167 likes — likes grew). Still a Z-Image (`zit`) prompt-engineering LLM. | ~3 GB (GGUF Q4) | low | 2 | GGUF variant now visible on the base repo (`gguf` tag), so this is loadable directly into LM Studio alongside the current `llm_delegate.py` LM Studio hook. Still a `zit`-only prompt enhancer. |
| **cmeka/SeedVR2-GGUF** | 2025-07-24 | GGUF quant for the SeedVR2 Comfy repackage above — fits the <= 12 GB tier if the full fp16 weights are too heavy | ~3-4 GB (GGUF Q4-ish) | low | 2 | 42.1K downloads / 166 likes. Should be paired with the Comfy-Org/SeedVR2 download decision — if the fleet is already on 2.x fp16, this is unnecessary; if the 12 GB tier is memory-pressured, this is the right drop-in. |

### Tier-2 non-model findings

- **`moss_image` + `qwen_image` dedup.** The `qwen_image` arch is now
  on `main` (one of the 8 just added to `_HF_ARCH_QUERIES` in T1-b).
  The Qwen-Image-2.1 track (base + Turbo + GGUFs) is still an open
  Tier-3 download from 2026-09-22 / 2026-10-16. Now that MOSS-Image
  lands as a *separate* 5B-param family rather than a Qwen-Image
  variant (text encoder is Qwen3.5 but the diffusion backbone is
  independent), the operator decision is now **three-way** rather
  than two-way: ship Qwen-Image-2.1-Turbo-GGUF, MOSS-Image Comfy
  repackage, or both? MOSS has clearly higher community volume on
  the Comfy side (2.4M vs. 294K downloads on the dominant repackages),
  but Qwen-Image-2.1 benefits from the already-registered `qwen_image`
  arch entry. This is a Tier-2 call because it affects fleet
  storage, not code.

- **Illustrious XL v2.0 is still visible on HF.** OnomaAIResearch's
  v2.0 trending at 237 likes (Apr-2025, so not new, but surfaces in
  the trending-adjacent search). The current `_reg("illustrious", …)`
  entry is sampler-shape identical to SDXL (which v2.0 preserves),
  so this is a weights-only swap on the fleet. Verified by the HF
  tag `base_model:...stable-diffusion-xl` on the GGUF quant. No code
  change needed; Tier-3 download decision for operator.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-10-26 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/MOSS-Image
    target_host: spark1
    reason: "MOSS-Image is a brand-new 5.08B-param text-to-image family from OpenMOSS (Apache-2.0, 2.4M downloads on the Comfy-Org repackage in <1 week, dominant). Diffusion-single-file so it drops into ComfyUI/models/checkpoints/ with no diffusers-pipeline plumbing. Pin this before the SFT/Base diffusers path — the comfy repackage is the community default."
    command_hint: "huggingface-cli download Comfy-Org/MOSS-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\moss-image"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: PedroMarinhoDev/Moss-Image-Edit-ComfyUI
    target_host: spark1
    reason: "Image-edit LoRA on MOSS-Image-SFT. Unlocks a `build_moss_image_edit` method (edit-via-instruction, in the shape of `build_klein_edit` / `flux_kontext`). ~1-2 GB adapter, depends on the MOSS-Image Comfy repackage above."
    command_hint: "huggingface-cli download PedroMarinhoDev/Moss-Image-Edit-ComfyUI --local-dir D:\\LLM\\ComfyUI\\models\\loras\\moss-image-edit"
    risk: low

  - action: audit_seedvr_version_on_fleet
    target_repo: Comfy-Org/SeedVR2
    target_host: unknown
    reason: "build_seedvr_* currently loads whatever weights are at ComfyUI/models/seedvr/* — this audit confirms whether the fleet is on SeedVR 1.x or 2.x. One-liner per host; no download yet, just a path check. If still on 1.x, Comfy-Org/SeedVR2 is a weights-only drop-in (same node, newer weights, 663K+ downloads)."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models\\seedvr -Recurse | Select-Object FullName,Length,LastWriteTime\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/SeedVR2
    target_host: spark1
    reason: "SeedVR 2 drop-in for the already-wired build_seedvr_* if the audit above confirms the fleet is still on 1.x. Weights-only, same node, 3B variant is ~6 GB fp16. Apache-2.0."
    command_hint: "huggingface-cli download Comfy-Org/SeedVR2 --local-dir D:\\LLM\\ComfyUI\\models\\seedvr\\seedvr2"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR
    target_host: spark1
    reason: "SDR→HDR video grading adapter on LTX-2.5. Depends on LTX-2.5 base weights (previous digest's Tier-3 download, still open). ~2 GB."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-SDR-To-HDR"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Camera-control / layout-aware rendering adapter on LTX-2.5. ~2 GB. Depends on LTX-2.5 base."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Restore
    target_host: spark1
    reason: "Video restoration + colorization + archive-footage adapter. Supports both LTX-2.3 and LTX-2.5 bases, so this is actionable even without the LTX-2.5 download. Comparison needed against seedvr + per-frame SUPIR."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Restore --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Restore"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate
    target_host: spark1
    reason: "VFX clean-plate / object-removal adapter on LTX-2.5. Pairs with Alpha-Gen (filed 2026-10-16) to form the two-step matte+fill VFX pipeline. ~2 GB."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Clean-Plate"
    risk: low

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein — now at 1669 likes / 700.7K downloads (up from 374 / 22K at previous filing). The flux3klein _reg() entry is now in architectures.py on main, so once weights land the fleet can route to it. Gated=auto on HF — needs huggingface-cli login on fleet host once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Still open from 2026-10-16. Fast distilled companion to the Qwen-Image-2.1 base — qwen_image _reg() entry now on main. Prefer the GGUF path (unsloth/Qwen-Image-2.1-Turbo-GGUF)."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "Still open from 2026-10-16. build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is loading (3.0 vs 3.1 vs still-on-sam2)."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Still open from 2026-10-16. Weights-only drop-in for build_sam3_segment IF the SAM3Segment node accepts 3.1 weights. Audit above runs first."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Still open from 2026-10-16. Alpha-matte / background removal adapter on LTX-2.5. 221 likes / 17.4K downloads now (up from 185 / 11.2K). Pairs with Clean-Plate (new above) for VFX matte+fill pipeline."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Still open from 2026-10-16. Spatial upscaler adapter on LTX-2.5. 138 likes / 11.9K downloads now (up from 125 / 10.8K)."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "Still open from 2026-10-16. SAM 3D for human-mesh / body pose. New builder family alongside hunyuan_3d; decision needed on output format (SMPL-X vs GLB)."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Still open from 2026-10-16. Base LTX-2.5 — now at 9410 likes / 2.1M downloads on HF (confirmed dominant open-source i2v). Blocks all 7 LTX-2.5 IC-LoRA adapters above (4 new in this run + 3 carried from 2026-10-16). Gated=auto; needs HF login the sandbox doesn't have."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Still open from 2026-10-16. Drop-in for existing _reg('hunyuan_3d', …); 2.1 mesh+texture pipeline may need node-list audit before swap."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Still open from 2026-10-16. Enables build_controlnet_gen on the zit arch (currently an empty cn list)."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-b now gives the HF arch-query map 8 more arches to probe when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "Still open from 2026-10-16. If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein, older weights on D:\\LLM should be flagged for retirement. Needs the tools/audit_disk_vs_registry.py drafting candidate below."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; still a Tier-1 drafting candidate (see Follow-up #1 below)."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.**
   Named in prior Tier-3 queues since 2026-10-16 but has never been
   written. Would be a ~100-line Tier-1 candidate for a future
   digest: read `architectures.py` + walk `ComfyUI/models/*`, print
   paths matching `registered=True` arches that have more than one
   weights candidate on disk. Not shipped this run because its only
   caller is the fleet-side `audit_retirable_weights` queue entry,
   and the fleet action is itself still open — the tool would land
   dead until a human runs the retirement pass.

2. **`architectures.py` docstring `SUPPORTED ARCHITECTURES` enum.**
   Current header enumerates 11 image + 7 video + 3 other
   fully-registered arches (= 21). On-disk registry has 29
   fully-registered + 6 stubs (= 35). Eight arches have landed on
   `main` since the 2026-10-16 digest's expansion:
   `flux2dev`, `flux3klein`, `krea2`, `qwen_image`, `minimax_h3`,
   `skyreels`, `longcat`, `aurasr`. The previous digest shipped a
   similar enumeration expansion as its T1-b — but this time the
   docstring also claims each entry's loader/sampler shape, which
   this run cannot verify from the registry alone without reading
   each new `_reg()` body. Downgraded to Tier-2 because:
   (a) the registry is source-of-truth and the docstring is a
   convenience list, so staleness is cosmetic not functional;
   (b) ensuring the `aurasr` upscaler ends up in the correct
   "Other" bucket (upscaler) rather than "Image" needs an operator
   read of its `_reg()` entry. Would be a safe Tier-1 for a future
   digest once an operator confirms the per-arch bucket.

3. **`flux2klein` → `flux3klein` default-pointer.** The `flux3klein`
   `_reg()` entry is now **on `main`** (one of the 8 added since
   2026-10-16), so the architectural question is no longer "where
   does it land" but "when does the operator switch the fleet
   default from `flux2klein` to `flux3klein`". That is a Tier-3
   fleet decision (weights download — see queue above). Follow-up
   closed on the code side.

4. **CI leak-check status.** Scanned current `main`'s tracked tree
   with the canonical pattern list from `.githooks/leak-patterns`;
   **clean** (`git grep` → `exit: 1`, which is the pass case for
   this check). No pre-existing failures on `main` to pre-emptively
   excuse this PR's CI. If a leak-check red surfaces on the PR,
   diff against `origin/main` first — any match in files this PR
   touches is this PR's.

5. **Previous digest's Follow-up #2 (MCP transport for
   `upgrade_research.py`).** Still open — the tool's HF and civitai
   backends still use `urllib`, which the cloud proxy 403s. Would
   let *this* routine run the ranked backend from the cloud instead
   of the skeleton. Still not shipped: broadens the tool's
   dependency surface (would need an MCP client in-process or a
   sidecar). Noted for a future digest that is willing to invest
   that scope.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
AST scans of `architectures.py`, `builders_manifest.json`;
`pytest tests/`._
