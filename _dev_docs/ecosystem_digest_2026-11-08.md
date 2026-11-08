# Ecosystem digest — 2026-11-08

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-b15rf8`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest (plus the eight new
  arch registrations it enabled — `flux2dev`, `flux3klein`, `krea2`,
  `qwen_image`, `minimax_h3`, `skyreels`, `longcat`, `aurasr`) all
  landed on `main`. The `claude/adoring-allen-b15rf8` branch is
  starting clean from `origin/main` (not stacking).
- **Routine health.** `tools/upgrade_research.py` is still present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`, exit
  `0`). No skeleton draft needed this run.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy
  continues to deny direct CONNECT to `huggingface.co` / `civitai.com`,
  so the live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here. Hugging-Face
  MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`) is the live
  path from the cloud this run uses. ~9 MCP calls spent of the ~25
  soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — scanned current `main`'s tracked tree with the
  canonical pattern list from `.githooks/leak-patterns`; **clean**
  (`exit: 1` = `git grep` found no match, the pass case for this
  check). No carried-over follow-up needed.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
`57 passed`).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner. Today is 2026-11-08.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left
as-is (all still describes past-tense "landed" items that remain true
today — self-healing installer, LM Studio prompt enhancement, mirror
sync, etc.).

### T1-b `README.md` + `DEEP_DIVE.md`: "75 tools" count is 3 short

`builders_manifest.json.method_count` is now `78` and an AST scan of
`workflows.py` confirms 78 `build_*` functions on disk. Both docs
still read `75`:

- `README.md` line 9 (hero tagline), line 139 ("75 tools across 19
  models"), line 212 ("All 75 tools →"), line 330 (plugin-menu caption),
  plus five `#all-75-tools` anchor links at lines 76, 99, 110, 131, 139,
  212 — all updated to `78` + `#all-78-tools`.
- `DEEP_DIVE.md` line 17 (TOC), line 52 (mermaid `GIMP[75 tools]`),
  line 300 (`## All 75 Tools` heading itself). Anchor target renamed
  too so the README → DEEP_DIVE links still resolve.
- Joke at `DEEP_DIVE.md:302` ("No, we will not be adding a 70th
  (officially)") left intact — it was already quasi-stale against 75,
  so ignoring that gag is consistent with how it was written.

Three new builders landed since the Oct 16 digest's fix: counting from
the `build_qwen_edit` / `build_skyreels_video` / `build_aurasr_upscale`
additions visible at the tail of `workflows.py`.

### T1-c `architectures.py` (both mirrors): docstring enumeration is 8 archs short

The Oct 16 digest's T1-b expanded the module-level `SUPPORTED
ARCHITECTURES` block to list 21 fully-registered + 6 stubs (27 archs).
Since then, **8 new `_reg()` entries** have landed on `main` (the
arches the Oct 16 digest flagged Tier-2 → all green-lit and merged):

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
- Video: `minimax_h3`, `skyreels`, `longcat`
- Other: `aurasr`

That makes the on-disk registry **35 `_reg()` entries** (29
fully-registered + 6 stubs), but the docstring still said "(as of
October 2026)" with the old 21 + 6 list. Downgrading to Tier 1
for the same reasons the Oct 16 pass did:

- The split between fully-wired and stub is unambiguous
  (`registered=True`/`False` is on each `_reg()` call).
- The enumeration is docstring-only; the registry itself remains the
  source of truth.
- Mirror-drift stays byte-identical: the identical edit was applied
  to both copies, `python tests/mirror_drift.py` →
  `OK: 32/32  DRIFT: 0`.

Bumped header to `(as of November 2026):` and expanded the list into
the same three sections: Image (15 fully-registered), Video (10
fully-registered), Other (4 fully-registered), stub list underneath
unchanged.

### T1-d `tools/upgrade_research.py`: HF arch-query map is 8 archs short

Same shape of bug as Oct 16's T1-c: `_HF_ARCH_QUERIES` was 27 entries
but the registry is now 35, so `_hf_query_for_method(build_<arch>_*)`
returned `None` for 8 fully-registered archs — a live `huggingface`
or `civitai` backend run would **silently skip** candidate research
for them.

Added mappings for: `flux2dev` (flux.2-dev / flux2-dev), `flux3klein`
(flux.3-klein / flux-3-image-klein — matches the actual HF repo id
of the already-landed weights), `krea2`, `qwen_image` (qwen-image-2.1
primary), `minimax_h3` (`hailuo` + `minimax-hailuo`), `skyreels`,
`longcat`, `aurasr`.

Also bumped the stale method-count claim in the module docstring from
`"75 as of 2026-10-16"` → `"78 as of 2026-11-08"`.

**Verification of T1-a through T1-d**

- `pytest tests/` — `57 passed in 6.07s` (baseline was 57 too — Oct 16
  reported 52, so 5 new tests landed between digests, all green).
- `python tools/upgrade_research.py --dry-run` — exit `0`, same
  `4 proposals from 5 backends` shape as before.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- No new untracked artifacts beyond the digest file itself.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers are the HF report at
the time of this digest, not 30-day rolling.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Lightricks/LTX-2.5** (+ existing Tier-3 queue) | 2026-10-11 | Direct upgrade for `_reg("ltx", …)` at `architectures.py:1189` | ~22 GB fp16 / ~9 GB int4 GGUF | medium | 2 | 6.2M downloads / 11,090 likes — up from 1.9M / 8,035 at Oct 16. Growth confirms this as the dominant open i2v. Gated=auto (needs `huggingface-cli login` once per fleet host). Base sampler shape unchanged from LTX-2.3 so `build_ltx_video` family would wire through with a weights swap + the new `ltx-2.5` substring added to `_HF_ARCH_QUERIES["ltx"]`. Pair with the IC-LoRAs below. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 | NEW builder `build_ltx_layout_to_render_video` (camera-control) | ~2 GB (adapter) | low | 2 | 17.9K downloads / 131 likes. Camera-control IC-LoRA on top of LTX-2.5. If the base lands, this is a one-builder unlock. Same license + distribution as the Oct-16 Alpha-Gen / Upscaler / Refine-Details adapters already queued. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR** | 2026-09-28 | NEW builder `build_ltx_sdr_to_hdr_video` | ~2 GB (adapter) | low | 2 | 19.4K downloads / 61 likes. SDR→HDR on LTX-2.5. Relevant for the DaVinci Resolve bridge — the Resolve bin pipeline already handles HDR media. |
| **facebook/sam3.1** | 2026-03-27 | Weights-only swap for existing `build_sam3_segment` / `build_sam3_extract` at `workflows.py:7216` and `:7296` | ~2 GB (ViT-L) | low | 2 | 954.6K downloads / 1,431 likes — up from 90.9K / 1,091 at Oct 16, 10× growth confirms community adoption. Gated on HF (same `huggingface-cli login` step as LTX-2.5). Still contingent on the Oct-16 Tier-3 `audit_sam3_version_on_fleet` entry resolving first. |
| **PrunaAI/P-H3-Image-Comfy** | 2026-11-03 | Weights for the already-landed `_reg("minimax_h3", …)` at `architectures.py:1336` | ~6 GB int8 / ~3 GB 4-bit | low | 2 | 625.1K downloads / 239 likes. Comfy-ready quantized MiniMax-Hailuo-3 repackage that includes the prompt-upsampling LoRA. `minimax_h3` is already in the registry so this is a weights-only acquisition, not a code change. Pairs naturally with `llm_delegate.py`'s LM Studio hook (the LoRA is a prompt-upsampler). |
| **unsloth/Qwen-Image-2.1-Turbo-GGUF** | 2026-10-10 | Weights for the already-landed `_reg("qwen_image", …)` at `architectures.py:911` | ~4 GB Q4_K_M / ~6 GB Q5 | low | 2 | 1.3M downloads / 80 likes — up from 294K at Oct 16. GGUF turbo variant — dominates the Turbo lane. 12-GB-tier fleet host deploys this directly. Oct 16 digest queued the base `Comfy-Org/Qwen-Image-2.1` in Tier-3; this is the few-step distilled companion for the lower-VRAM tier. |
| **abenzerps/Qwen-Image-2.1-Turbo-Quantized** | 2026-11-03 | Alt weights for `qwen_image` (int8/fp8, diffusers) | ~8 GB fp8 | low | 2 | 76.8K downloads but **5,722 likes** — the most-liked Qwen-Image repackage. Diffusers pipeline rather than GGUF — relevant on hosts that prefer the native diffusers path over `stable-diffusion.cpp`. |
| **Comfy-Org/Flux-2-Dev** | 2025-11-25 | Already-landed `_reg("flux2dev", …)` at `architectures.py:768` | ~24 GB fp16 / ~9 GB GGUF-Q4 | medium | 2 | 1.0M downloads / 372 likes (also `unsloth/FLUX.2-dev-GGUF` 99.5K + `city96/FLUX.2-dev-gguf` 80.4K for the quantized lane). Arch is registered — pending fleet download. No new code work; weight-acquisition decision. |
| **speridlabs/idol** | 2026-10-29 | NEW arch candidate — image-to-3D via Gaussian splatting | ~3 GB | medium | 2 | 22.9K downloads / 1,307 likes in 10 days. Apache-2.0 (notable — most of the 3D-gen field is "other" or custom licenses). Different output format from `hunyuan_3d` (Gaussian splats vs mesh+texture). Would land as `_reg("idol", …)` + `build_idol_3d` builder, NOT a Hunyuan3D replacement. Needs an operator decision on splat vs mesh pipeline for downstream consumption. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details** | 2026-09-27 | NEW builder `build_ltx_refine_details_video` | ~2 GB (adapter) | low | 2 | 20.7K / 89 likes. Carrying forward the Oct 16 Tier-2 entry at updated numbers (was 16.1K / 65). Still contingent on the base LTX-2.5 landing. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients** | 2026-09-10 | NEW builder `build_ltx_character_consistency_video` | ~2 GB (adapter) | low | 2 | 15.0K / 108 likes. Carrying forward at updated numbers (was 9.2K / 66). Reference-sheet-driven character consistency for video — aligns with the character-consistency builder patterns in illustrious/sdxl. |

### Tier-2 non-model finding

- **Qwen-Image lane choice is now forced.** The Oct 16 digest left
  "base vs Turbo-GGUF" as an open operator call. The two most recent
  numbers resolve it empirically — `unsloth/Qwen-Image-2.1-Turbo-GGUF`
  at 1.3M downloads and `abenzerps/Qwen-Image-2.1-Turbo-Quantized`
  at 5,722 likes have both decisively outpaced the base repo, and
  spellcaster has `qwen_image` already registered in the Turbo-friendly
  `clip_mode="single_qwen_image"` shape with `default_steps=20`.
  Recommendation: ship the GGUF Turbo path first (12-GB tier) +
  the fp8 Quantized variant as the 24-GB fallback. The base repo
  queued in Oct 16's Tier-3 can be deprioritised.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-08 ────────────────────────────────────────────

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Camera-control IC-LoRA on LTX-2.5. Depends on LTX-2.5 base weights (Oct 16 Tier-3). Unlocks a build_ltx_layout_to_render_video builder with no new base weights needed."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout-To-Render"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR
    target_host: spark1
    reason: "SDR→HDR IC-LoRA on LTX-2.5. Depends on LTX-2.5 base weights. Pairs with the DaVinci Resolve bridge (Resolve bin already handles HDR media)."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-SDR-To-HDR"
    risk: low

  - action: download_and_evaluate_model
    target_repo: PrunaAI/P-H3-Image-Comfy
    target_host: spark2
    reason: "Comfy-ready quantized weights for the already-landed _reg('minimax_h3', ...) arch. Includes prompt-upsampling LoRA. Int8 + 4-bit variants in-pack — pick int8 for spark2's 24-GB tier."
    command_hint: "huggingface-cli download PrunaAI/P-H3-Image-Comfy --include '*int8*' --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\P-H3-Image-Comfy"
    risk: low

  - action: download_and_evaluate_model
    target_repo: unsloth/Qwen-Image-2.1-Turbo-GGUF
    target_host: spark2
    reason: "Primary weights lane for the already-landed _reg('qwen_image', ...) arch. GGUF Q4_K_M fits the 12-GB tier. Dominated the Turbo variants at 1.3M downloads vs. base's few-hundred-K."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: abenzerps/Qwen-Image-2.1-Turbo-Quantized
    target_host: spark1
    reason: "Fp8 diffusers-pipeline Qwen-Image Turbo for the 24-GB tier. 5,722 likes signals strongest community preference even if raw downloads are smaller than the GGUF pack."
    command_hint: "huggingface-cli download abenzerps/Qwen-Image-2.1-Turbo-Quantized --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1-Turbo-Quantized"
    risk: low

  - action: evaluate_new_arch
    target_repo: speridlabs/idol
    target_host: unknown
    reason: "Gaussian-splatting image-to-3D. Apache-2.0 license (notable in the 3D-gen field). Different output format than hunyuan_3d (splats vs mesh). Decision before weight acquisition: does the downstream consumer (DaVinci Resolve bridge? Blender bridge?) prefer splats or meshes?"
    command_hint: "huggingface-cli download speridlabs/idol --local-dir D:\\LLM\\ComfyUI\\models\\idol"
    risk: medium

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein weights for the already-landed _reg('flux3klein', ...) arch. Growth confirmed at 1.2M downloads / 2,731 likes. Gated=auto — needs huggingface-cli login on the fleet host once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment and build_sam3_extract use the SAM3 node family — this audit confirms which SAM3 weights are actually loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet, just a path check. Precondition for the sam3.1 upgrade."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Weights-only drop-in for the already-wired build_sam3_segment / build_sam3_extract. 954.6K downloads / 1,431 likes now — 10× growth since Oct 16. Gated on HF. Still contingent on the audit above."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on LTX-2.5. 18.9K / 251 likes. Depends on LTX-2.5 base weights. ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. 13.6K / 152 likes. Depends on LTX-2.5 base. Pairs with existing supir/aurasr image upscalers for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details
    target_host: spark1
    reason: "Detail-refinement IC-LoRA on LTX-2.5. 20.7K / 89 likes. Lightricks-published, same license as base."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Refine"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients
    target_host: spark1
    reason: "Reference-sheet character-consistency IC-LoRA on LTX-2.5. 15.0K / 108 likes."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Ingredients"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Base LTX-2.5 weights for the direct upgrade of _reg('ltx', ...). 6.2M downloads / 11,090 likes — dominant open i2v. Gated=auto; needs HF login the sandbox doesn't have."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for existing _reg('hunyuan_3d', ...). Current build_hunyuan_3d points at 2.0-shape weights; 2.1 mesh+texture pipeline may need node-list audit before the swap. Compare against speridlabs/idol (new Tier-3 entry above) before committing fleet storage to both."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Enables build_controlnet_gen on the zit arch (currently an empty cn list). 122.0K downloads / 472 likes — confirmed stable."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-d adds 8 more arches to the probe set once the tool runs from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein, the older weights on D:\\LLM should be flagged for retirement. Mechanical audit: compare architectures.py registered=True set against ComfyUI/models/*. Tool draft is a candidate for a future digest's Tier-1 (see follow-up #1)."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.**
   Named in prior Tier-3 queues (2026-09-22 and -10-16) but has never
   been written. A ~100-line script: read `architectures.py` + walk
   `ComfyUI/models/*`, print paths matching `registered=True` arches
   that have more than one weights candidate on disk. Future Tier-1
   candidate — the script runs fine from the LAN (it only reads the
   fleet host's own disk) so it's shippable before the next fleet
   download wave. Not drafted this run because it needs a decision
   on canonical path layout under `D:\LLM\ComfyUI\models\` that the
   operator should make.

2. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap flagged on 2026-09-22 and 2026-10-16 — the tool's HF and
   civitai backends use `urllib`, which the cloud proxy 403s.
   Teaching `backend_huggingface` to prefer an MCP transport when one
   is available would let *this* routine run the ranked backend from
   the cloud instead of the skeleton one. Still not shipped — it
   broadens the tool's dependency surface (needs an MCP client
   in-process or a sidecar). Probably worth doing before the LAN
   backend hygiene (follow-up #1) because this routine runs from the
   cloud and #1 doesn't.

3. **`flux2klein` → `flux3klein` migration path.** `flux3klein` is now
   registered alongside `flux2klein` (non-destructively, as the Oct 16
   digest recommended), but no builder function routes to `flux3klein`
   yet — the `build_klein_*` family still dispatches through the
   `flux2klein` arch key. When the operator decides to flip, the code
   change is mechanical (`arch_key = "flux3klein"` in the klein
   builders) but needs an operator-level "which arch is canonical for
   new work" call. Not touched this run.

4. **Qwen-Image Turbo lane is decided (see Tier-2 non-model
   finding).** Promote `unsloth/Qwen-Image-2.1-Turbo-GGUF` to the
   canonical weights lane and deprioritise the Oct 16 Tier-3
   `Comfy-Org/Qwen-Image-2.1` (base, non-Turbo) entry — leaving it in
   the queue for the moment in case the operator wants the full-quality
   lane as a non-default option.

5. **No CI red to investigate.** Pre-flight on `main` is green and the
   branch under this PR adds only docstring/markdown changes +
   `_HF_ARCH_QUERIES` entries. Mirror drift + pytest both pass.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
AST scans of `architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`._
