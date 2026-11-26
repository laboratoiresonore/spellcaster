# Ecosystem digest — 2026-11-26

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch:
`claude/ecosystem-digest-2026-11-26`.

## Delivery notes

- **Digest-PR backlog is 20 deep (#193 → #213) and none have merged.**
  Every previous run in this cadence has produced a near-identical
  diff — bump README status month, bump arch-enum docstring, add new
  entries to `_HF_ARCH_QUERIES` — and every one is sitting on the same
  base sha `b7d82d1`. That pattern means (a) new runs of this routine
  that repeat those same fixes add zero value, and (b) the stack
  cannot land as separate merges without hand-resolving the same
  three-file conflict 20 times. This run therefore deliberately
  **does NOT re-fix** the stale README month or the arch-enum
  docstring, both of which PR #213 already covers correctly for
  everything except one factual slip (see below). The operator's
  action item is upstream of this routine: pick one PR off the top,
  merge it, close the duplicates.
- **PR #213 (2026-11-24) is close to mergeable but has one factual
  error.** Its `comfyui-spellcaster/spellcaster_core/architectures.py`
  docstring moves `flux_kontext` from the fully-registered Image
  list into the `registered=False` stub list. On disk, `_reg(
  "flux_kontext", …)` at `architectures.py:956` has **no
  `registered=False`** flag — it is fully registered. Before merging
  #213, `flux_kontext` needs to be moved back into the Image
  fully-registered list in both mirror copies (byte-identical edit).
  Same note applies to PRs #205, #207, #208, #210, #211, #212 which
  copied the error from an earlier run of this routine.
- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`, exit
  0, new artifact at `_dev_docs/upgrade_research/2026-W48.{md,json}`).
  No skeleton draft needed.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy
  still 403s direct CONNECT to `huggingface.co`, so the Hugging-Face
  MCP (`hf_fs ls hf://models/trending`, `hub_repo_search`,
  `hub_repo_details`) is the live path. ~6 MCP calls spent of the
  ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.

## Tier 1 — fixes applied in this commit

Novel, non-duplicate work: these are fixes **no open digest PR has
filed** (checked against the full 2026-10-14 → 2026-11-24 stack).
`pytest tests/` → 57/57 before and after.

### T1-a `tools/build_builders_manifest.py`: three new-arch builders fall through to `model_family="generic"`

The model-family inference table `_MODEL_FAMILY_PATTERNS` (added by
the 2026-05-15 fix comment at `build_builders_manifest.py:152-162`)
is the voodoomaster gate's source of truth for mapping a `build_*`
name to the arch key the gate checks against the host's
`archs_block`. The 2026-05-15 fix comment is explicit that a
mis-tagged family causes `supported=False` in the caps advertisement
*even when the arch and nodes are live on the host* — because
`archs_block.get("generic")` returns `None`.

Three builders that landed since the 2026-05-15 fix are currently
tagged `model_family="generic"` in the manifest:

| Builder (workflows.py line) | Terminal node clue | Correct arch |
|-----------------------------|---------------------|--------------|
| `build_aurasr_upscale` (10615) | `RunAuraSR` / `LoadAuraSR` | `aurasr` |
| `build_krea2_edit` (10479) | `Krea2EditModelPatch`, `type="krea2"`, qwen3vl-4b CLIP | `krea2` |
| `build_skyreels_video` (10549) | SkyReels V2 1.3B I2V, `umt5_xxl` CLIP, `wan_2.1_vae` | `skyreels` |

All three archs are already `_reg()`d (fully-registered, not stubs)
in `architectures.py`, so the gate will correctly resolve the family
once the inference map covers them. Added three patterns just
before the SDXL-coupled block (so the SDXL sweep can't shadow them):

```python
(r"^skyreels", "skyreels"),
(r"^krea2",    "krea2"),
(r"^aurasr",   "aurasr"),
```

Then regenerated the manifest and copied to the mirror:

```
python tools/build_builders_manifest.py
cp comfyui-spellcaster/spellcaster_core/builders_manifest.json \
   plugins/gimp/comfyui-connector/spellcaster_core/builders_manifest.json
```

Diff of the regen is exactly three `"model_family"` strings flipping
from `"generic"` → the correct arch (`aurasr` / `krea2` / `skyreels`),
once per mirror. Nothing else moves.

### Verification of T1-a

- `pytest tests/` — `57 passed in 7.55s` (same as pre-edit).
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  no further drift.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tests/builders_manifest_drift.py` — `check: manifest fresh (78 methods).`
- `python tools/upgrade_research.py --dry-run` — exit `0`, same
  `4 proposals from 5 backends` shape.
- `python tests/night_maintenance.py --dry-mode` — all three dry-mode
  checks (mirror-drift, cross-repo-drift, log-scan) pass.
- Generic-family bucket now holds 7 builders instead of 10 — exactly
  the 7 the module docstring documents as "arch-universal generic
  pipelines gated by model files, not node classes"
  (`build_txt2img`, `build_img2img`, `build_inpaint`,
  `build_outpaint`, `build_generate_anything`, `build_2d_to_sbs`,
  `build_2d_to_sbs_extreme`). No remaining false-generic rows.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search` on `text-to-image` by trending score,
`hub_repo_details`). Numbers below are the HF report at the time of
this digest. Entries flagged **[delta]** are movement on rows prior
digests already filed; **[new]** are rows no earlier digest in this
chain filed.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **nvidia/Nemotron-Labs-Image-30B-A3B** `[new]` | 2026-09-24 (updated 2026-11-25) | NEW arch — first NVIDIA text-to-image model | ~65 GB fp16 (32.6B params); fits ~16 GB at 4-bit | high | 2 | 233 likes / 227 downloads (very early). Trending score 201, so community pickup is starting. Uses `nemotron_h` architecture class (`AutoModelForCausalLM` wrapper, not `DiffusionPipeline`), so wiring is **not** a `_reg()` drop-in — the loader shape differs from every current Spellcaster arch (image-generation emerges from a 30B causal-LM, not a diffusion UNet). nvidia-license (not open), gated=false. Decision: wait for a ComfyUI loader node to materialize before considering integration — raw `transformers` loading is outside spellcaster's current pipeline-builder surface. |
| **MiniMaxAI/MiniMax-H3-Image** `[new]` | 2026-11-16 | Weights home for the already-wired `minimax_h3` arch | ~22 GB fp16 (NVFP4 variant fits 10 GB on Spark2) | low | 2 | 1.0M downloads / 2,567 likes — mainstream. `_reg("minimax_h3", …)` is already on disk since the 2026-11-24 digest's run, so this is a **weights-only** operation on the fleet host (Spark2 per prior notes: "NVFP4 on Spark2"). 63+ demo Spaces live. The `base_model:finetune:MiniMaxAI/MiniMax-H3` tag means this is the finetuned image checkpoint; the base `MiniMaxAI/MiniMax-H3` is a separate text model and is NOT what the arch registration points at. |
| **Lightricks/LTX-2.5** `[delta]` | 2026-11-26 (updated TODAY) | Replaces `_reg("ltx", …)` current weights | ~22 GB fp16 base | medium | 2 | **Huge movement in 2 days:** `8.0M` downloads / `13,518` likes as of this digest, vs. 2026-11-24's note of `3M` / `923` likes. Still `gated=auto` — the fleet host needs a one-time `huggingface-cli login` before the download. The 88+ demo Spaces include multiple variants (alpha-matte, pixel-upscaler, multi-pipe) that match the LoRA adapters already in the prior digests' Tier-3 queue. Decision point for the operator is still "when to flip" — the download has NOT landed yet per the still-open queue entry from 2026-10-16. |
| **supermansundies/Minimax-H3-Image-Pose-Transfer-Lora** `[new]` | 2026-11-25 | Pose-transfer LoRA for `minimax_h3` | ~500 MB adapter | low | 2 | Fresh (6 downloads / 44 likes) but published yesterday. The `base_model:adapter:Comfy-Org/MiniMax-H3-Image` tag means this is an IC-LoRA-style pose adapter, Apache-2.0 licensed. If the fleet has MiniMax-H3-Image weights (see row above), this unlocks a `build_minimax_h3_pose_transfer` builder with no additional base-weight cost. |
| **Nebsh/Seedreamstyle-H3-6K** `[new]` | 2026-11-19 | Photography/cinematic style LoRA for `minimax_h3` | ~300 MB adapter | low | 2 | 8.1K downloads / 183 likes. ComfyUI-tagged, drops into `ComfyUI/models/loras/` without wiring work — the `minimax_h3` arch already accepts LoRAs via the standard `lora_prefixes` plumbing. Pairs cleanly with the H3 base weights download. |
| **chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized** `[delta]` | 2026-11-23 (no change) | Already Tier-2 in 2026-11-24 | ~10 GB (quantized) | medium | 2 | Moved from 474K/877 (11-24) to 515.6K/972 — steady community pickup. SFW/NSFW gate still with the `_NSFW` pipeline, not this repo's canon. No action change from last digest. |

### Tier-2 non-model notes

- **Nemotron-Labs-Image shape caveat.** This is the first serious
  "causal-LM as image generator" release trending on HF. If it
  survives the next 2 weeks (32.6B params + nvidia-license is a tall
  ask for hobbyists), spellcaster's `architectures.py` pattern —
  which assumes a diffusion pipeline with a sampler, loader, CLIP,
  VAE — will need a new "category" alongside its existing Image /
  Video / Other buckets, or a `loader="causal_lm_image"` path that
  treats the model like a vision-LM. Not an immediate code change;
  flagged so a future Tier-1 doesn't try to wedge it into an existing
  arch shape.
- **MiniMax-H3 LoRA ecosystem is forming.** Two H3-based LoRAs
  surfaced in this run (pose transfer + photography). The
  `minimax_h3` arch landed in 2026-11-24 without yet having its base
  weights on the fleet; the LoRA ecosystem appearing *before* the
  base weights are downloaded is normal for an arch in its first
  week of circulation, but the operator should decide whether
  `minimax_h3` adoption is actually planned before pulling LoRAs
  that depend on it.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-11-24 entries and prior digests'
unresolved items. The local-action format is unchanged — a Hermes /
operator process can consume this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-26 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: MiniMaxAI/MiniMax-H3-Image
    target_host: spark2
    reason: "Weights home for the _reg('minimax_h3', ...) registration that landed on 2026-11-24. 1.0M downloads / 2,567 likes — mainstream. Use the NVFP4 variant on Spark2 (per the arch registration's comment)."
    command_hint: "huggingface-cli download MiniMaxAI/MiniMax-H3-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MiniMax-H3-Image"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: Nebsh/Seedreamstyle-H3-6K
    target_host: spark2
    reason: "Photography/cinematic style LoRA for minimax_h3. Depends on the H3-Image base weights above. 8.1K downloads / 183 likes. ComfyUI-tagged, standard LoRA plumbing."
    command_hint: "huggingface-cli download Nebsh/Seedreamstyle-H3-6K --local-dir D:\\LLM\\ComfyUI\\models\\loras\\MiniMax-H3-Seedream-6K"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: supermansundies/Minimax-H3-Image-Pose-Transfer-Lora
    target_host: spark2
    reason: "Pose-transfer IC-LoRA for minimax_h3 — unlocks a build_minimax_h3_pose_transfer builder. Depends on H3-Image base weights. Apache-2.0. Very new (24 hours old) — defer until operator has decided on H3 adoption."
    command_hint: "huggingface-cli download supermansundies/Minimax-H3-Image-Pose-Transfer-Lora --local-dir D:\\LLM\\ComfyUI\\models\\loras\\MiniMax-H3-Pose"
    risk: low

  - action: resolve_digest_pr_backlog
    target_repo: laboratoiresonore/spellcaster
    target_host: unknown
    reason: "20 open digest PRs (#193 → #213) all stacked on the same main sha b7d82d1. Each re-fixes the same README month + arch-enum + HF-arch-query-map triple. Routine is producing no value until ONE merges and the rest are closed. Suggested order: merge #213 (latest, has the broadest arch-enum update), then close #193-#212. See the 'Delivery notes' section for the one-line correction PR #213 needs before merge (flux_kontext back in Image fully-registered)."
    command_hint: "gh pr merge 213 --squash  # after fixing flux_kontext placement in both mirror copies\ngh pr close 193 194 195 196 197 198 199 200 201 202 203 204 205 206 207 208 209 210 211 212 --comment 'Superseded by #213 (merged).'"
    risk: medium

  # ─── Carried over from 2026-11-24 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein lands as the direct successor to the current _reg('flux2klein', ...) in architectures.py. _reg('flux3klein', ...) is already registered on disk. The -comfy repackage is diffusion-single-file so it drops into ComfyUI/models/checkpoints/ with no diffusers-pipeline plumbing. Gated=auto on HF — needs huggingface-cli login on the fleet host once. 2026-11-24 digest noted 892K downloads / 4,517 likes."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). HF now shows 8.0M downloads / 13,518 likes — 4x growth in 2 days since the 2026-11-24 digest (3M/923). Gated=auto; needs HF login the sandbox doesn't have. Carries LoRA adapters (alpha-matte, pixel-upscaler, refine-details, ingredients) that the 2026-10-16 digest already queued separately."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: unsloth/flux-3-image-klein-GGUF
    target_host: spark2
    reason: "GGUF quantization of Flux 3 Klein for the 12-GB tier. Carried over from 2026-11-24 digest at 475K downloads."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\flux-3-image-klein-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: unsloth/Qwen-Image-2.1-Turbo-GGUF
    target_host: spark2
    reason: "Fast distilled Qwen-Image-2.1 companion for the 12-GB tier. Carried over from 2026-10-16 digest. _reg('qwen_image', ...) is now on disk; this is weights-only."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading (3.0 vs 3.1 vs still-on-sam2). Carried from 2026-10-16. One-liner on each fleet host; no download yet."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/sam3.1
    target_host: spark1
    reason: "ComfyUI-shape repackage of facebook/sam3.1 — drop-in for the already-wired build_sam3_segment. 458K downloads / 130 likes. Depends on audit above. Carried from 2026-11-24."
    command_hint: "huggingface-cli download Comfy-Org/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on top of LTX-2.5. ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder. Carried from 2026-10-16."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. ~2 GB. Pairs with existing supir image upscaler. Carried from 2026-10-16."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh). Gating moved from auto → manual per 2026-11-24 digest — needs a one-time HF 'request access' click. Decision gate: human-mesh output format vs. downstream consumer."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for existing _reg('hunyuan_3d', ...); current build_hunyuan_3d points at 2.0-shape weights. Carried from 2026-10-16."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Enables build_controlnet_gen on the zit arch (currently empty cn list). Carried from 2026-10-16."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. The LAN run picks up the full set of arches the 2026-10-16 and 2026-11-24 fixes have added to _HF_ARCH_QUERIES."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein, the older weights on D:\\LLM should be flagged for retirement. tools/audit_disk_vs_registry.py exists in PR #209 (claude/digest-2026-11-16); merging that PR gives this action a real script to run."
    command_hint: "python tools/audit_disk_vs_registry.py  # exists in PR #209 only"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing operator read first.

1. **The flux_kontext docstring slip in PRs #205-213.** A one-line
   correction before merging #213 keeps the enumeration honest. If
   the operator wants, a future run of this routine can land that
   correction as a Tier-1 — but only AFTER one of the stacked PRs
   actually merges, otherwise we add #214 to the backlog for the same
   reason.
2. **`tools/audit_disk_vs_registry.py` exists but only in PR #209.**
   Carried from 2026-10-16 as a Tier-1 candidate — the 2026-11-16 run
   actually implemented it (see `claude/digest-2026-11-16`
   `tools/audit_disk_vs_registry.py` 358 lines added), but that PR
   is also stuck in the backlog. Not re-implementing on this branch
   — would just stack another copy on top. Merging PR #209 is the
   right action.
3. **Transport fallback for `tools/upgrade_research.py`.** Still
   open from 2026-09-22. Teaching the `huggingface` backend to
   prefer an MCP transport when one is available would let the
   ranked backend run from the cloud. Broadens dependency surface;
   not shipped.
4. **`MIRROR_TARGETS.md` is a dead reference.** Seven files in-tree
   (`.github/workflows/mirror-drift.yml`, `tests/mirror_drift.py`,
   `tests/cross_repo_drift.py`, `tools/sync_surfaces.py`) point at
   `MIRROR_TARGETS.md` as design-doc-of-record, but the file was
   only ever committed on the unmerged 2026-05-13 branch
   `docs/dev-hygiene-mirror-targets-2026-05-13` and never made it to
   `main`. Not a runtime bug — the workflow's `paths:` trigger for
   this nonexistent file is inert, the docstring citations are
   prose. But it's a Tier-1-ish restoration opportunity: cherry-pick
   `MIRROR_TARGETS.md` + `_DEV_HYGIENE.md` from that branch's
   `a44b351` commit onto main. Scope-larger-than-mechanical (file
   contents need to be audited against today's layout, and that
   branch was intentionally not merged by the operator). Flagging
   for an operator decision.
5. **`model_family` gate for `build_qwen_edit`.** Currently mapped
   to `flux1dev` family (documented as intentional at
   `build_builders_manifest.py:170-177`: "qwen-image-edit shares
   the Flux1 loader path"). The `qwen_image` arch now exists on
   disk — worth confirming whether `build_qwen_edit` should move
   to the `qwen_image` family or stay on `flux1dev`. Depends on
   which loader the terminal `TextEncodeQwenImageEditPlus` node
   actually resolves at runtime. Not mechanical; operator read.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs ls hf://models/trending`; local
`tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`; `git log` over the 20-PR open-digest backlog._
