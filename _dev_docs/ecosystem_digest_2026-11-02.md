# Ecosystem digest — 2026-11-02

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-q0ywax`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest landed on `main`
  before this run, so this routine starts from a clean slate rather
  than stacking on an open queue.
- **Routine health.** `tools/upgrade_research.py` is still present
  and `--dry-run` executes cleanly (`4 proposals from 5 backends`).
  No skeleton draft needed this run.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy
  continues to deny direct CONNECT to `huggingface.co` /
  `civitai.com`, so the live `backend_huggingface` /
  `backend_civitai` paths of `tools/upgrade_research.py` return
  nothing from the sandbox; Hugging-Face MCP (`hf_fs`,
  `hub_repo_search`, `hub_repo_details`) is the live path from the
  cloud this run uses. ~7 MCP calls spent of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — current `main`'s tracked tree is clean against
  `.githooks/leak-patterns`; no action needed.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
57/57, `mirror_drift.py` → 32/32 OK).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner. Today is 2026-11-02.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left
as-is (all still describes past-tense "landed" items that remain true
today — installer self-healing, LM Studio prompt enhancement, mirror
sync, validator work).

### T1-b `architectures.py` docstring: enumeration + date

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
module-level `SUPPORTED ARCHITECTURES (as of October 2026):` block,
listing **21 fully-registered + 6 stubs = 27 archs** while the
registry on disk is now **35 `_reg()` entries** (29 fully-registered
+ 6 stubs). Since the 2026-10-16 digest, these entries have been
added:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image` (so 15
  image total).
- Video: `minimax_h3`, `skyreels`, `longcat` (so 10 video total).
- Other: `aurasr` (so 4 other total).

The split between fully-wired and stub is unambiguous — `registered=`
is on each `_reg()` call explicitly, no judgement needed. The
enumeration is docstring-only; the registry itself remains
source-of-truth. Mirror-drift stays byte-identical: identical edit
applied to both copies, `python tests/mirror_drift.py` →
`OK: 32/32  DRIFT: 0`.

Bumped the header to `(as of November 2026):` and expanded the list
into three sections — Image (15 fully-registered), Video (10
fully-registered), Other (4 fully-registered), with the explicit stub
list underneath (unchanged: `sd3`, `sd3_turbo`, `hunyuan_dit`,
`pixart`, `auraflow`, `kolors`).

### T1-c `tools/upgrade_research.py`: HF arch-query map is missing 8 archs

`_HF_ARCH_QUERIES` had entries for 27 archs but the registry on disk
is now at 35. That means `_hf_query_for_method(build_<arch>_*)`
returned `None` for 8 fully-registered archs, so a live `huggingface`
or `civitai` backend run would **silently skip** candidate research
for them.

Added mappings for: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`,
`minimax_h3`, `skyreels`, `longcat`, `aurasr`. Also broadened the
existing `wan` and `ltx` entries to pick up the newer generations
(`wan-2.5` on top of `wan2.2`; `ltx-2.5` on top of the existing
`ltx-2`).

Also bumped the stale method-count claim in the module docstring from
"75 as of 2026-10-16" → "78 as of 2026-11-02".

Verification: `python tools/upgrade_research.py --dry-run` still
exits `0`, same `4 proposals from 5 backends` output; `pytest tests/`
→ `57 passed`.

**Verification of T1-a through T1-c**

- `pytest tests/` — `57 passed in 7.46s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same shape
  as before the arch-query map expansion.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  manifest was already at 78, no regen required.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search` by `trendingScore` within `text-to-image`,
`image-to-video`, `text-to-video`, `image-to-3d`, `mask-generation`
tag families, and `hub_repo_details` on specific repos). Numbers
below are the HF report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Comfy-Org/MiniMax-H3** | 2026-10-29 | ComfyUI drop-in for the already-registered `minimax_h3` arch (`architectures.py:1336`) | ~22 GB fp16 (needs GGUF for 12-GB tier) | low | 2 | **79.1M downloads / 2,483 likes** — the ComfyUI community's canonical path to MiniMax-H3. `diffusion-single-file` → drops into `ComfyUI/models/checkpoints/`. `minimax_h3` is already in the registry so this is a weights-only fleet download; no code change needed to light it up beyond pointing `build_minimax_h3_*` at the Comfy-Org path. |
| **unsloth/MiniMax-H3-GGUF** | 2026-08-07 | GGUF variant of the above for the 12-GB tier | ~8-14 GB (GGUF Q4-Q8) | low | 2 | 2.6M downloads / 402 likes. Pair with Comfy-Org/MiniMax-H3 as the Spark2 / smaller-VRAM lane. |
| **larryvrh/MiniMax-H3-Turbo-Lora** | 2026-08-05 | Few-step distill LoRA for `_reg("minimax_h3", …)` | ~2 GB adapter | low | 2 | 207.9K downloads / 1,215 likes. Mirrors the `qwen_image_turbo` / Klein distill pattern — would wire as a Turbo mode on top of the base MiniMax-H3 weights. |
| **Pika-Labs/Pika-H3-Flex** | 2026-10-29 | New Pika-styled i2v adapter on top of MiniMax-H3 | ~2 GB adapter | medium | 2 | 491 downloads / 345 likes — fresh (4 days old) but trending at #2 for i2v on HF. Pika's house style is distinctive; worth watching whether download/like volume stabilises before committing fleet storage. Pairs with `akhaliq/Pika-H3-Flex-Turbo-LoRA` (72 likes, 29K dl) for the few-step shape. |
| **pablodawson/MiniMax-H3-360-Orbit-LoRA** | 2026-09-27 | Camera-control / orbit / first-last-frame adapter for MiniMax-H3 | ~2 GB adapter | low | 2 | 39.5K downloads / 580 likes. Would enable a `build_minimax_h3_orbit` builder (orbit camera around a subject, with FLF2V shape) with no new base weights. |
| **speridlabs/idol** + **Comfy-Org/Idol** | 2026-10-28 / 2026-11-01 | NEW arch `idol` — Gaussian-splatting image-to-3D, parallel/complement to `_reg("hunyuan_3d", …)` | ~6 GB (SPLAT model) | medium | 2 | 384 likes / 7.8K downloads on base; the Comfy-Org ComfyUI repackaging landed yesterday. **apache-2.0** (clean license, unlike Hunyuan3D's `license:other`). Different mesh style (3D Gaussians rather than SDF/mesh) — not a replacement for `hunyuan_3d`, a parallel route. Would land as `_reg("idol", …)` with a different downstream export pipeline (splat → GLB vs. SDF → mesh). |
| **microsoft/TRELLIS.2-4B** | 2025-12-01 | Alternate image-to-3d for the `_reg("hunyuan_3d", …)` slot | ~16 GB fp16 (4B params) | medium | 2 | 2.8M downloads / 1,442 likes, **license:mit** (clean). Different output than Hunyuan3D (full 3D asset w/ texture) and than Idol (gaussian splats). Decision point for the operator: Hunyuan3D-2.1 vs TRELLIS.2-4B vs Idol for the 3D lane. |
| **hi3d-official/Hi3Dv1.0** | 2026-10-16 | Another image-to-3d entrant — geometry-refinement focus | ~4 GB | medium | 2 | 151 likes / 0 downloads (brand new). Monitor; too early to commit. |
| **facebook/sam3.1** | 2026-03-26 | Version-swap for the `SAM3Segment` ComfyUI node already consumed by `build_sam3_segment` (`workflows.py`) | ~2 GB (ViT-L backbone) | low | 2 | **Now 182.5K downloads / 1,345 likes** (up from 90.9K / 1,091 at 2026-10-16 — doubled in 17 days). Still weights-only if the SAM3Segment node loader accepts 3.1-shape weights. The `unsloth/sam3.1` quantized variant (fp8/int8, 28 likes but recent) is the smaller-VRAM lane for Spark2. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 (updated 2026-10-22) | NEW LTX-2.5 adapter — layout-to-render + camera-control for `ltx` arch | ~2 GB adapter | low | 2 | 18.5K downloads / 124 likes. Would enable a `build_ltx_layout_to_video` builder for scene-blocking → final-render video. Depends on LTX-2.5 base. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Restore** | 2026-09-27 (updated 2026-10-22) | LTX-2.5 adapter — archive-footage restoration + colorization | ~2 GB adapter | low | 2 | 13.2K downloads / 82 likes. Pairs with existing `build_ltx_*` set as a `build_ltx_restore_video` builder. Depends on LTX-2.5 base. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Water-Simulation** | 2026-09-09 (updated 2026-10-22) | LTX-2.5 VFX adapter — fluid / water simulation | ~2 GB adapter | low | 2 | 4.3K downloads / 28 likes. Niche but author-published, same license as base LTX-2.5. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Day-To-Night** | 2026-09-08 (updated 2026-10-22) | LTX-2.5 adapter — time-of-day relighting | ~2 GB adapter | low | 2 | 4.6K downloads / 32 likes. Would land as `build_ltx_relight_video`. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Deblur** / **-Decompression** / **-Colorization** | 2026-09-10 (updated 2026-10-22) | LTX-2.5 restoration pack — motion deblur, compression artefact removal, b&w → colour | ~2 GB each | low | 2 | 7.8K / 3.7K / 3.4K downloads, 23 / 20 / 17 likes. Small but author-published; batch install if the restoration lane is wanted. |

### Tier-2 non-model finding

- **MOSS-Image family (OpenMOSS-Team).** `MOSS-Image-SFT` (878 likes),
  `MOSS-Image-Base` (607 likes), `akhaliq/MOSS-Image-IDM-2-Steps` (41
  likes). Fresh (11-30 Oct 2026), Apache-2.0, new `MOSSImagePipeline`
  diffusers class — distinctive from any existing registered arch.
  Download volume still very low (<20K each) so this stays
  **monitor-only** for now rather than a Tier-2 integration row; if a
  ComfyUI community repackage lands and crosses 100K downloads it
  escalates to Tier-2 for the next sweep.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-02 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/MiniMax-H3
    target_host: spark1
    reason: "The ComfyUI community's canonical MiniMax-H3 drop-in — 79.1M downloads, diffusion-single-file. _reg('minimax_h3', ...) is already in the registry so this is a weights-only lightup. Pairs with unsloth/MiniMax-H3-GGUF for the 12-GB (Spark2) tier."
    command_hint: "huggingface-cli download Comfy-Org/MiniMax-H3 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MiniMax-H3"
    risk: low

  - action: download_and_evaluate_model
    target_repo: unsloth/MiniMax-H3-GGUF
    target_host: spark2
    reason: "GGUF (Q4/Q6/Q8) MiniMax-H3 for the 12-GB tier. 2.6M downloads. Target spark2 since spark1 can host the full fp16 version above."
    command_hint: "huggingface-cli download unsloth/MiniMax-H3-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\MiniMax-H3-GGUF"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: larryvrh/MiniMax-H3-Turbo-Lora
    target_host: spark1
    reason: "Few-step distill LoRA for MiniMax-H3. 207.9K downloads / 1,215 likes. Would wire as the default Turbo path for build_minimax_h3_* builders (mirror of the Klein 4-step shape). Depends on MiniMax-H3 base above."
    command_hint: "huggingface-cli download larryvrh/MiniMax-H3-Turbo-Lora --local-dir D:\\LLM\\ComfyUI\\models\\loras\\MiniMax-H3-Turbo"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: pablodawson/MiniMax-H3-360-Orbit-LoRA
    target_host: spark1
    reason: "Camera-control / orbit / first-last-frame adapter on MiniMax-H3. 39.5K downloads / 580 likes. Unlocks a build_minimax_h3_orbit builder with FLF2V shape. Depends on MiniMax-H3 base above."
    command_hint: "huggingface-cli download pablodawson/MiniMax-H3-360-Orbit-LoRA --local-dir D:\\LLM\\ComfyUI\\models\\loras\\MiniMax-H3-360-Orbit"
    risk: low

  - action: evaluate_new_arch
    target_repo: speridlabs/idol
    target_host: unknown
    reason: "NEW image-to-3d candidate via Gaussian splatting (apache-2.0). Not a replacement for _reg('hunyuan_3d', ...) — different output format (splats vs mesh). Decision needed: do we want a parallel 3D lane in architectures.py, or wait for a ComfyUI node pack to standardise splat consumption downstream? Comfy-Org/Idol is the ComfyUI-packaged companion."
    command_hint: "huggingface-cli download Comfy-Org/Idol --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Idol"
    risk: medium

  - action: evaluate_new_arch
    target_repo: microsoft/TRELLIS.2-4B
    target_host: unknown
    reason: "Alternative to Hunyuan3D-2.1 for the image-to-3d slot — 2.8M downloads, MIT license (vs Hunyuan3D's license:other). Needs a bench vs the existing hunyuan_3d builder before committing: output format (textured mesh), VRAM profile (~16 GB), and node-pack availability in ComfyUI."
    command_hint: "huggingface-cli download microsoft/TRELLIS.2-4B --local-dir D:\\LLM\\ComfyUI\\models\\3d\\TRELLIS.2-4B"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Layout-to-render + camera-control adapter on LTX-2.5. 18.5K downloads / 124 likes. Would enable a build_ltx_layout_to_video builder (scene-blocking → final-render video). Depends on LTX-2.5 base."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Restore
    target_host: spark1
    reason: "Archive-footage restoration + colorization adapter on LTX-2.5. 13.2K downloads / 82 likes. Would wire as build_ltx_restore_video. Depends on LTX-2.5 base."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Restore --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Restore"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Day-To-Night
    target_host: spark1
    reason: "Time-of-day relighting adapter on LTX-2.5. 4.6K downloads / 32 likes. Would wire as build_ltx_relight_video. Depends on LTX-2.5 base."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Day-To-Night --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-D2N"
    risk: low

  - action: download_and_evaluate_quantized_sam
    target_repo: unsloth/sam3.1
    target_host: spark2
    reason: "fp8 / int8 quantized SAM 3.1 for the 12-GB tier. 28 likes but only 10 days old. Pair with the already-queued facebook/sam3.1 download; prefer this one on hosts where VRAM is tight."
    command_hint: "huggingface-cli download unsloth/sam3.1 --include '*int8*' --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1-int8"
    risk: low

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein — direct successor to _reg('flux2klein', ...). flux3klein is now in the registry so this is a weights-only lightup. Gated=auto on HF; needs huggingface-cli login on the fleet host once. Up to 1.0M downloads / 2,329 likes."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Fast distilled companion to the Qwen-Image-2.1 base (also carried over from 2026-10-16). Prefer the GGUF path (AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF, 681.4K downloads) for the 12-GB tier. qwen_image is now in the registry — weights-only lightup."
    command_hint: "huggingface-cli download AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "Still-open from 2026-10-16. build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet, just a path check."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Weights-only drop-in for the already-wired build_sam3_segment, IF the SAM3Segment ComfyUI node loader accepts 3.1-shape weights at the same path. Now at 182.5K downloads / 1,345 likes (doubled since 2026-10-16). Audit above runs first."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on top of LTX-2.5. Depends on LTX-2.5 base weights. ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. Also depends on LTX-2.5 base. ~2 GB. Pairs with existing supir image upscaler for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family. Deciding point: human-mesh output format (SMPL-X vs GLB) vs. what spellcaster downstream tools consume."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Base Qwen-Image-2.1 arch — now at 10.6M downloads / 1,249 likes on the Comfy-Org packaging. qwen_image is in the registry — weights-only lightup if the full-quality lane is preferred over the Turbo distill."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). HF now shows 2.47M downloads / 10,321 likes on the base repo (up from 1.9M / 8,035 at 2026-10-16) — confirmed dominant open-source i2v. Gated=auto; needs HF login the sandbox doesn't have."
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
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c now gives the HF arch-query map 8 extra arches to probe when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein, the older weights on D:\\LLM should be flagged for retirement. Mechanical audit still blocked on tools/audit_disk_vs_registry.py which does not exist yet — see follow-up #1 below."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; still a drafting candidate for a future digest."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.**
   Named in prior Tier-3 queues but has never been written. Writing
   it is a ~100-line Tier-1 candidate for a future digest: read
   `architectures.py` + walk `ComfyUI/models/*`, print paths matching
   `registered=True` arches that have more than one weights candidate
   on disk. Not shipped here because this routine's test harness
   can't exercise the fleet-side walk — it needs a tmpdir fake-tree
   fixture at minimum, and the choice of per-arch directory layout
   (`checkpoints/`, `unet/`, `3d/`, …) wants the operator's read
   before we commit to a scheme.

2. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap flagged by prior digests — the tool's HF and civitai
   backends use `urllib`, which the cloud proxy 403s. Teaching the
   `huggingface` backend to prefer an MCP transport when one is
   available would let *this* routine run the ranked backend from
   the cloud instead of the skeleton one. Doable but broadens the
   tool's dependency surface (needs an MCP client in-process or a
   sidecar), so not shipped here.

3. **`flux2klein` → `flux3klein` migration path.** Both archs are
   now in the registry side-by-side (`_reg("flux2klein")` at line
   707 and `_reg("flux3klein")` at line 813). When the operator
   decides to flip the fleet to Flux 3, the question of whether to
   DEPRECATE `flux2klein` (so existing calibrations auto-fall-back)
   or KEEP it indefinitely becomes architectural. Current state is
   "both registered, both wired" — same shape as the pre-existing
   `flux1dev` / `flux2klein` coexistence, so no urgent code churn.

4. **README "75 tools" claim.** `README.md:9`, `README.md:139`,
   `README.md:212`, `README.md:330`, `DEEP_DIVE.md:52` all read "75
   tools" / "all-75-tools" anchor. The `build_*` method count on
   disk is now 78; the DEEP_DIVE table-row sum under `## All 75
   Tools` is **68** (7+9+9+7+4+3+7+7+7+8). This is a 3-way
   inconsistency that pre-dates this digest and cannot be
   mechanically bumped — fixing it requires deciding which number is
   authoritative (the GIMP menu? the DEEP_DIVE tables? the `build_*`
   methods?). Filing as a Tier-2-style follow-up: the next operator
   decision is which number is right, then the four README callouts
   + the anchor + DEEP_DIVE's "All 75 Tools" heading all bump
   together in one safe mechanical fix.

5. **MOSS-Image diffusion family (OpenMOSS-Team).** Not yet
   warranting a Tier-2 integration row (low download volume, no
   ComfyUI repackaging seen yet), but worth tracking: a new
   `MOSSImagePipeline` diffusers class, Apache-2.0, with a
   companion few-step distill (`akhaliq/MOSS-Image-IDM-2-Steps`).
   Will re-check next sweep.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search` (by
trending-score within text-to-image / image-to-video / text-to-video
/ image-to-3d / mask-generation tag families), `hub_repo_details`,
`hf_fs ls hf://models/trending`; local `tools/upgrade_research.py
--dry-run`; AST scans of `architectures.py`, `workflows.py`,
`builders_manifest.json`; `pytest tests/`; `python tests/mirror_drift.py`._
