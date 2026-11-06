# Ecosystem digest — 2026-10-28

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `ed19fb4`). Branch: `claude/adoring-allen-qec2c7`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest (sha `75ef09a`)
  landed on `main` as part of the v2.4 Spark2-support stack, so this
  run starts on clean `main` (`ed19fb4`), not stacked on an open PR.
- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`,
  `Methods in scope: 78`). No skeleton draft needed.
- **Registry has grown.** Since the 2026-10-16 docstring was written,
  the architecture registry picked up eight fully-registered arches
  (`flux2dev`, `flux3klein`, `krea2`, `qwen_image`, `minimax_h3`,
  `skyreels`, `longcat`, `aurasr`) via the v2.4 GB10 landing commit
  `4b1e1c0` and the follow-ups. The in-tree docstring and the HF
  arch-query map in `tools/upgrade_research.py` both still described
  the pre-v2.4 shape → Tier-1 fixes shipped here (see T1-a, T1-c).
- **Egress still proxy-walled.** Cloud sandbox HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`, so
  live-backend `urllib` calls inside `tools/upgrade_research.py`
  still fall back to the skeleton. Hugging-Face MCP (`hf_fs`,
  `hub_repo_search`, `hub_repo_details`) remains this routine's live
  path from the cloud. ~13 MCP calls spent of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; delivery is
  this PR itself.
- **Leak-check CI** — scanned current tracked tree with the canonical
  pattern list from `.githooks/leak-patterns`, with the three
  self-excluded files (`.github/workflows/leak-check.yml`,
  `.githooks/pre-push`, `.githooks/leak-patterns`) left out exactly
  as the workflow does. **Clean** (`git grep` returned no hits).

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
57/57).

### T1-a `architectures.py` docstring: enumeration lags the registry

Both mirrors of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
module-level
`SUPPORTED ARCHITECTURES (as of October 2026):` block from the
2026-10-16 edit, which listed **21 fully-registered + 6 stubs = 27
arches**. The registry on disk now has **29 fully-registered + 6 stubs
= 35 arches** — the v2.4 Spark2 GB10 landing (`4b1e1c0`) and the
post-push audit fix (`0e63dc1`) added:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image` (4 new).
- Video: `minimax_h3`, `skyreels`, `longcat` (3 new).
- Other: `aurasr` (1 new).

The stub set (`sd3`, `sd3_turbo`, `hunyuan_dit`, `pixart`, `auraflow`,
`kolors`) is unchanged — spot-checked by `grep -nE "registered=False"`,
exactly six hits. Edit is docstring-only; the registry itself remains
source-of-truth. Mirror-drift stays byte-identical: identical edit
applied to both copies, `python tests/mirror_drift.py` → `OK: 32/32
DRIFT: 0`.

### T1-b `tools/upgrade_research.py` module docstring: stale method count

Line 7-8 said `"70 at the time of that pass, 75 as of 2026-10-16"`.
`python tools/build_builders_manifest.py` reports **78 methods** on
disk today. Bumped to `"78 as of 2026-10-28"`.

### T1-c `tools/upgrade_research.py`: `_HF_ARCH_QUERIES` is missing 8 arches

`_HF_ARCH_QUERIES` had 27 entries. Registry has 35. The 8 missing
mappings would have caused `backend_huggingface` to silently skip
candidate research for 8 fully-registered arches when the tool runs
from the LAN (where the HF proxy block doesn't apply). Added:

| Arch | Added search terms |
|------|--------------------|
| `flux2dev` | `flux.2-dev`, `flux2-dev` |
| `flux3klein` | `flux.3-klein`, `flux3-klein`, `flux-3-image-klein` |
| `krea2` | `krea-2`, `krea2` |
| `qwen_image` | `qwen-image-2.1`, `qwen-image`, `qwen-image-2.1-turbo` |
| `minimax_h3` | `minimax-h3`, `minimax_h3`, `minimax-h` |
| `skyreels` | `skyreels-v2`, `skyreels` |
| `longcat` | `longcat-video`, `longcat` |
| `aurasr` | `aurasr`, `aura-sr` |

Also broadened `wan` (added `wan-2.5`) and `ltx` (added `ltx-2.5`) to
pick up the 2.5 generation now that LTX-2.5 is the dominant repo
(2.2M downloads, 9668 likes this run).

### Verification of T1-a through T1-c

- `pytest tests/` — **57 passed in 8.84s**. (New tests since the
  2026-10-16 run's 52 — the suite grew; both runs pass.)
- `python tools/upgrade_research.py --dry-run` — exit `0`,
  `4 proposals from 5 backends`, same shape as before this run.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0  MISSING: 0`.
- `python tools/build_builders_manifest.py` — regenerates to 78
  methods; the on-disk manifest already matches, so no re-write
  needed in this commit.
- Leak-scan — self-exclusions as per
  `.github/workflows/leak-check.yml`, clean (no hits).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers are the HF report at
the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **tencent/Hy-Nomas** + **-Diffusers** | 2026-10-21 / 2026-10-24 | NEW arch — interactive video world model (text + camera control, autoregressive DiT) | ~15 GB fp16 (est, repo tag `pytorch` + `diffusion-transformer`) | medium | 2 | 105 + 14 likes / 38.1K + 97 downloads in ~1 week; trending score 102. Apache-2.0, no gating. Different task class from existing Wan/LTX video — this one keeps interaction history (multi-turn text + camera path) rather than a one-shot i2v prompt. Would land as a NEW `hy_nomas` arch with its own builder family (`build_hy_nomas_world`, `build_hy_nomas_extend`), not an extension of any existing video arch. Paper: arXiv:2610.36729. |
| **OpenMOSS-Team/MOSS-Image-SFT** + **Comfy-Org/MOSS-Image** | 2026-10-11 / 2026-10-16 | NEW image arch — open DiT with built-in intent-aware prompt enhancement | ~8 GB fp16 (est from `diffusers` pipeline shape) | medium | 2 | 798 + 519 likes / 14.3K + 3.1M downloads in <3 weeks (Comfy-Org variant has already crossed 3M). Apache-2.0, no gating. Specifically targets long-form text and layout-coherent generation (paper arXiv:2610.23374). Pipeline name `MOSSImagePipeline`. Would land as `_reg("moss_image", ...)` with its own `build_moss_image_txt2img` + the prompt-enhancement path integrated into `llm_delegate.py`'s per-arch enhancer hook. Decision point: does it earn a slot alongside `zit` / `qwen_image` at the 8-10 GB tier, or is overlap too high? |
| **black-forest-labs/flux-3-image-klein-pup** | 2026-10-14 | Prompt-rewriter LLM for `flux3klein` (Qwen3.5-9B-based) | ~5 GB (GGUF Q4 est) / ~18 GB bf16 | low | 2 | 69 likes / 56.0K downloads. Published alongside the main `flux-3-image-klein` repo as a dedicated prompt-upsampling model. Apache-2.0. Would wire into `llm_delegate.py`'s per-architecture enhancer map (same slot as the `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4` 2026-10-16 entry does for `zit`) as the default prompt enhancer for `build_flux3klein_*`. Base model is `Qwen/Qwen3.5-9B` so it loads cleanly in LM Studio alongside existing LLMs. |
| **unsloth/flux-3-image-klein-GGUF** | 2026-10-16 | Quantized Flux-3-Klein weights for the 12-GB tier | 6-10 GB (depending on quant) | low | 2 | 38 likes / 109.7K downloads. The GGUF path for Flux 3 Klein that was anticipated by the 2026-10-16 Tier-3 download of the `-comfy` repo (now at 798K / 1927 likes, confirming the arch has broken through). This repo is the Q4/Q8 lane for anyone on sub-24 GB VRAM. Would pair with the pending fleet download of the full `-comfy` version from 2026-10-16's Tier 3. |
| **black-forest-labs/flux-3-image-klein-base** | 2026-10-13 | Alternate (non-finetuned) Flux-3 Klein checkpoint | ~11 GB fp16 | low | 2 | 196 likes / 113.1K downloads. The "base" variant alongside the main `flux-3-image-klein` repo. Mostly a benchmarking question — does spellcaster's `flux3klein` arch want the base or the finetuned variant as the fleet default? Fleet question, not a code question. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Water-Simulation** | 2026-09-09 (last mod 2026-10-22) | NEW VFX adapter on LTX-2.5 | ~2 GB (adapter) | low | 2 | 28 likes / 3.2K downloads. Would unlock a `build_ltx_water_vfx` builder once the LTX-2.5 base is on fleet (still a pending Tier-3 from 2026-10-16). Lightricks-published, same license + distribution contract as the base LTX-2.5. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Restore** | 2026-09-27 (last mod 2026-10-22) | NEW video restoration + colorization adapter on LTX-2.5 (and LTX-2.3) | ~2 GB (adapter) | low | 2 | 80 likes / 10.1K downloads. Interesting because it's tagged both `ltx-2.3` AND `ltx-2.5` — can be evaluated against the existing `ltx` arch WITHOUT waiting for the LTX-2.5 base download. Would unlock a `build_ltx_restore_video` + `build_ltx_colorize_video` pair. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 (last mod 2026-10-22) | Camera-controlled layout-to-video adapter | ~2 GB (adapter) | low | 2 | 118 likes / 14.3K downloads. The camera-control angle is close to Hy-Nomas (Tier-2 above) but as an adapter on an arch spellcaster already has, so cheaper to ship than a full new arch. Would land as `build_ltx_layout_render`. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Decompression** | 2026-09-10 (last mod 2026-10-22) | Compression-artifact removal video adapter | ~2 GB (adapter) | low | 2 | 20 likes / 2.9K downloads. Niche but neatly orthogonal to the Restore / Deblur pack above. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Deblur** | 2026-09-09 (last mod 2026-10-22) | Video deblur adapter | ~2 GB (adapter) | low | 2 | 23 likes / 7.0K downloads. Pairs with Restore above. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Day-To-Night** | 2026-09-08 (last mod 2026-10-22) | Video relighting (day→night) adapter | ~2 GB (adapter) | low | 2 | 32 likes / 3.9K downloads. Mirror of the per-method relight builder spellcaster already has for images. |
| **krea/Krea-2-Turbo** | 2026-06-18 | Few-step companion to the already-registered `krea2` arch | ~6 GB fp16 (est) | low | 2 | 1798 likes / 82.8K downloads. The `krea2` arch is already registered; `Krea-2-Turbo` is the few-step distill that would go into the same arch config with reduced default steps + a different sampler path, in parallel with the full `Krea-2-Raw`. Operator decision: wire it as a new `extra["turbo_variant"]` config on `_reg("krea2", ...)`, or as a separate `_reg("krea2_turbo", ...)` arch keyed off the ckpt detector? Same question Flux-2 Klein vs Flux-2 Dev settled last cycle. |
| **conradlocke/krea2-identity-edit** | 2026-07-07 | Identity-preserving edit LoRA for the `krea2` arch | ~1 GB (LoRA) | low | 2 | 911 likes / 202.9K downloads. First community-published identity-edit LoRA for the fresh krea2 arch. Would go into `lora_calibrations_sfw.json` under the `krea2` arch key, same shape as existing SDXL identity-edit calibrations. |
| **facebook/sam3.1** | 2026-03-26 | Version-swap for `build_sam3_segment` | ~2 GB (ViT-L backbone) | low | 2 | 173.3K downloads / 1255 likes — **growing** (from 90.9K / 1091 at the 2026-10-16 digest). Still gated on operator verification: does the installed `SAM3Segment` ComfyUI node resolve 3.1-shape weights at the same path? Carried forward from 2026-10-16 as `audit_sam3_version_on_fleet` is still open. |
| **facebook/sam-3d-body-dinov3** | 2025-11-17 | NEW capability — 3D human-mesh recovery | ~3 GB (DINOv3 backbone) | medium | 2 | 669 likes / 10.7K downloads — **growing** (from 541 / 8.4K last cycle). Still a NEW builder family alongside `build_hunyuan_3d`. Decision point unchanged from last cycle: new `sam3d` arch or extension of `hunyuan_3d`? |
| **facebook/sam-3d-objects** | 2025-10-06 | Alternate image-to-3d for `_reg("hunyuan_3d", …)` | ~3 GB | medium | 2 | 608 likes / 7.8K downloads — **growing** (from 575 / 5.5K last cycle). Still a direct comparator for Hunyuan3D 2.1 (now at 1326 likes / 84.1K dl, Comfy-Org repackage at 102K). Decision pending: which 3D arch wins the fleet storage slot? |
| **tencent/Hunyuan3D-2.1** + **Comfy-Org/Hunyuan-3D-2.1** | 2025-06-13 / 2025-09-05 | Drop-in for existing `_reg("hunyuan_3d", …)` | ~6 GB fp16 | medium | 2 | 1326 + 31 likes / 84.1K + 102.6K downloads. Still the dominant Hunyuan3D line; carried from 2026-09-22 and 2026-10-16's Tier-3 download request. |

### Tier-2 non-model finding

- **Prompt-enhancer slot per arch.** Three arches now have a
  dedicated community-published prompt enhancer (`zit` →
  `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4`, `flux3klein` →
  `black-forest-labs/flux-3-image-klein-pup`, `moss_image` ships one
  built-in via `MOSSImagePipeline`). `llm_delegate.py` has an LM
  Studio hook but no first-class per-arch enhancer registry. Adding
  one would turn these from one-off integrations into a repeatable
  pattern (same shape as `lora_calibrations_sfw.json` is for LoRAs).
  Non-trivial scope (~150 lines, touches `llm_delegate.py`,
  `scaffold/`, and the per-arch workflow builders) — Tier-2 because
  it's a feature decision, not a mechanical fix.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over still-open 2026-10-16 entries that have not been reported
as actioned, plus this run's new ones. A local Hermes / operator
process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-10-28 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: tencent/Hy-Nomas
    target_host: spark1
    reason: "NEW interactive video world model (Apache-2.0, no gating). Multi-turn text + camera-path conditioning — different task class from existing i2v arches. Would land as a NEW `hy_nomas` arch. Trending score 102, 105 likes in ~1 week; worth a fleet eval slot before deciding whether to register."
    command_hint: "huggingface-cli download tencent/Hy-Nomas --local-dir D:\\LLM\\ComfyUI\\models\\hy-nomas"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/MOSS-Image
    target_host: spark2
    reason: "NEW open-weights DiT (Apache-2.0) with built-in intent-aware prompt enhancement. 3.1M downloads already on the Comfy-Org repackage — community confirmation. Fits spellcaster's quality-boost-prompt + per-arch enhancer story natively."
    command_hint: "huggingface-cli download Comfy-Org/MOSS-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MOSS-Image"
    risk: low

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-pup
    target_host: spark1
    reason: "Flux-3 Klein's dedicated prompt-rewriter LLM (Qwen3.5-9B-based, Apache-2.0). Pairs with the pending flux-3-image-klein-comfy fleet download (from 2026-10-16). Would wire into llm_delegate.py as the default enhancer for build_flux3klein_* once both are on disk."
    command_hint: "huggingface-cli download black-forest-labs/flux-3-image-klein-pup --local-dir D:\\LLM\\LMStudio\\models\\flux-3-klein-pup"
    risk: low

  - action: download_and_evaluate_model
    target_repo: unsloth/flux-3-image-klein-GGUF
    target_host: unknown
    reason: "Quantized Flux-3 Klein for the 12-GB VRAM tier. Lets fleet hosts without 24 GB VRAM access the flux3klein arch. Decide fleet-wide default (full -comfy vs this GGUF) alongside the pending -comfy download."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\flux-3-image-klein-GGUF"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Restore
    target_host: spark1
    reason: "Dual-tagged ltx-2.3 AND ltx-2.5, so it can be evaluated against the EXISTING ltx arch without waiting for the LTX-2.5 base download. Unlocks a build_ltx_restore_video / build_ltx_colorize_video pair. Fastest ROI of this cycle's LTX IC-LoRA batch."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Restore --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Restore"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Camera-controlled layout-to-video adapter. Depends on LTX-2.5 base. Overlaps with the Hy-Nomas camera-control angle above — pick ONE camera-control path per fleet (adapter vs. new arch) before downloading both."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Water-Simulation
    target_host: unknown
    reason: "Niche VFX adapter; low priority. Grab in the same batch as the other LTX-2.5 adapters IF LTX-2.5 base already landed."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Water-Simulation --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Water"
    risk: low

  - action: download_and_evaluate_model
    target_repo: krea/Krea-2-Turbo
    target_host: spark2
    reason: "Few-step distill of the already-registered krea2 arch. If krea2 base lands on fleet, the Turbo variant is the few-step default for the 12-GB tier. Operator call: new _reg key or extra['turbo_variant']? (Same shape as the Flux-2 Klein vs Flux-2 Dev decision.)"
    command_hint: "huggingface-cli download krea/Krea-2-Turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Krea-2-Turbo"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: conradlocke/krea2-identity-edit
    target_host: spark2
    reason: "Community identity-edit LoRA for the fresh krea2 arch. Would go into lora_calibrations_sfw.json under the krea2 arch key, same shape as existing SDXL identity-edit entries."
    command_hint: "huggingface-cli download conradlocke/krea2-identity-edit --local-dir D:\\LLM\\ComfyUI\\models\\loras\\krea2-identity-edit"
    risk: low

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Still open from 2026-10-16. Numbers have EXPLODED since then: 1927 likes / 798.9K downloads (vs 374 / 22K last cycle). Flux-3 Klein is the clear winner this cycle — unblock the fleet download so the already-registered flux3klein arch can be exercised with real weights. Gated=auto on HF; needs huggingface-cli login once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Still open from 2026-10-16. The uncensored-quantized community fork (abenzerps/Qwen-Image-2.1-Uncensored-Quantized) is now at 5237 likes / 2.2M downloads — the dominant Qwen-Image-2.1 variant. Operator decision pending: ship the base + GGUF path (Comfy-Org/Qwen-Image-2.1 + unsloth/Qwen-Image-2.1-GGUF), the Turbo + Turbo-GGUF path, or the uncensored path?"
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "Still open from 2026-10-16. SAM3 base is now 5315 likes / 1.9M downloads (vs 4493 / 2.03M last cycle — essentially flat on downloads, +18% likes). Audit confirms which SAM3 weights the installed SAM3Segment ComfyUI node actually loads before any 3.1 swap."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Still open from 2026-10-16. 1255 likes / 173.3K downloads (up from 1091 / 90.9K). Weights-only drop-in for the already-wired build_sam3_segment IF SAM3Segment node loader accepts 3.1 shape. Audit above runs first."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Still open from 2026-10-16. Alpha-matte / background removal adapter on top of LTX-2.5. Depends on LTX-2.5 base weights (still-pending Tier-3 download below). ~2 GB, unlocks build_ltx_remove_bg_video."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Still open from 2026-10-16. 141 likes / 12.2K downloads (up from 125 / 10.8K). Pairs with existing supir image upscaler for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "Still open from 2026-10-16. 669 likes / 10.7K downloads (up from 541 / 8.4K). SMPL-X vs GLB output decision for spellcaster downstream still pending."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Still open from 2026-10-16 and 2026-09-22. Now at 9668 likes / 2.23M downloads (vs 8035 / 1.9M last cycle). Direct upgrade for _reg('ltx', ...). Gated=auto, needs HF login the sandbox doesn't have. BLOCKS five Tier-3 LTX IC-LoRA items until it lands."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Still open from 2026-10-16. The hunyuan3d-2.1 repackage. Current build_hunyuan_3d points at 2.0-shape weights; 2.1 may need node-list audit before swap."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Still open from 2026-10-16. 466 likes / 94.4K downloads. Enables build_controlnet_gen on the zit arch (currently an empty cn list)."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Still open from 2026-10-16. Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends still fall back to skeleton mode. This run's T1-c now gives the HF arch-query map 8 more arches + 2 broadened entries to probe when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "Still open from 2026-10-16 and 2026-09-22. Named in prior Tier-3 queues but tools/audit_disk_vs_registry.py has never been written. If the next wave of fleet downloads (Flux-3-Klein, LTX-2.5, Qwen-Image-2.1, krea2, Hy-Nomas, MOSS-Image) lands, the retirable-weights question lives behind this tool. Writing it is a ~100-line Tier-1 candidate for a future digest."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is STILL a Tier-3 TODO.**
   Carried over from both 2026-10-16 and 2026-09-22; the inbound
   wave this cycle (Flux-3 Klein, Krea-2, MOSS-Image, Hy-Nomas, five
   LTX-2.5 IC-LoRAs) will stress the retirable-weights question
   harder than ever. Writing this is still a safe ~100-line Tier-1
   candidate: read `architectures.py` + walk `ComfyUI/models/*`, print
   paths matching `registered=True` arches that have more than one
   weights candidate on disk. Deliberately deferred this run to keep
   the diff tight and the Tier-1 fixes verifiable.

2. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap the 2026-09-22 and 2026-10-16 digests flagged — the
   tool's HF and civitai backends use `urllib`, which the cloud
   proxy 403s. Teaching the `huggingface` backend to prefer an MCP
   transport when one is available would let *this* routine run the
   ranked backend from the cloud. Still non-trivial dependency
   surface change; not shipped here.

3. **Per-arch prompt-enhancer registry.** This cycle's three
   prompt-enhancer finds (`zit` → Qwen3-4b-Z-Image-Engineer-V4,
   `flux3klein` → flux-3-image-klein-pup, `moss_image` → built-in)
   turn an ad-hoc mapping into a pattern worth centralising, same
   shape as `lora_calibrations_sfw.json` is for LoRAs. Non-trivial
   scope, filed as Tier-2 above.

4. **`flux2klein` → `flux3klein` migration path.** Carried from
   2026-10-16. `flux3klein` is now REGISTERED (one of the new arches
   from `4b1e1c0`); the open question flips from "add it
   non-destructively" to "do we deprecate `flux2klein` once Flux-3
   weights are on fleet, and if so, when?". This is a fleet-timing
   question, not a code question — stays in the operator's lane.

5. **`SPELLCASTER_STEER_002` follow-ups** (post-push audit from
   `0e63dc1`). The 2026-10-16 digest's T1-c anticipated 11 new
   arches; the actual landing (`4b1e1c0` + `0e63dc1` + `ed19fb4`)
   went with 8 (`flux2dev`, `flux3klein`, `krea2`, `qwen_image`,
   `minimax_h3`, `skyreels`, `longcat`, `aurasr`). The three not
   added — `wan 2.5`, `sam3d`, `moss_image` — remain Tier-2
   candidates this cycle (Hy-Nomas / MOSS-Image above; SAM-3D in the
   carryover block). Note that T1-c's broadened `wan` entry already
   covers the Wan-2.5 query term even though no `wan25` key exists
   yet — the arch stays `wan` and the search broadens.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
`python tools/build_builders_manifest.py`; AST scans of
`architectures.py`; `pytest tests/`; local leak-pattern scan._
