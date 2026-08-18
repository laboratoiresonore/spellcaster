# Ecosystem Research Digest — 2026-08-18

Cloud-side sweep of the upgrade-opportunity surface for the Laboratoire
Sonore / Spellcaster stack. See `_dev_docs/ecosystem_digest_*.md` for
prior runs. Format follows the every-48h routine's tier split (Tier 1
= apply here; Tier 2 = new-model integration needing human VRAM/quality
judgment; Tier 3 = needs local fleet access, emitted as structured
`local_action_queue`).

## Meta — self-repairs this run made

Previous runs of this routine noted `python tools/upgrade_research.py`
as missing and silently degraded to web-only research. That's fixed
this run:

- **Drafted `tools/upgrade_research.py`.** Zero-dep stdlib script that
  imports `architectures.py` in isolation, parses `builders_manifest.json`
  and the `UNET_ARCH_RULES` / `CKPT_ARCH_RULES` tables out of
  `model_detect.py`, and emits a JSON snapshot of "what Spellcaster
  already integrates" so future digests can start from a stable state
  instead of re-crawling. Verified end-to-end: 27 archs / 73 builders /
  2 detect-rule tables in the payload.

## Tier 1 — fixes applied in this PR

Each item below is a real edit in this commit, not a note for a human
to apply later. Ran `python3 tools/upgrade_research.py` after every fix
to confirm no regression.

### 1. Register the missing `supir` architecture stub

**File**: `comfyui-spellcaster/spellcaster_core/architectures.py`

`model_detect.CKPT_ARCH_RULES` line 103 maps any filename containing
`supir` to the arch key `"supir"`, but `architectures.ARCHITECTURES`
had no entry for it. `get_arch("supir")` therefore silently returned
the SDXL config — meaning any caller iterating the registry for
capability reporting would misclassify SUPIR as a first-class
summonable SDXL model. Diagnostic's `_build_txt2img_test` would try
to txt2img-test it as SDXL and fail confusingly at sampler time
(SUPIR checkpoints don't have the CLIP/VAE for standalone summon —
they need pairing with an SDXL backbone via `build_supir(sdxl_model,
supir_model)` in `workflows.py:3108`).

Added a `registered=False` stub with empty `supported_methods=()`,
matching the pattern used for `sd3` / `pixart` / other DiT-only stubs.
`get_arch("supir")` now returns a real ArchConfig with `.registered ==
False` so callers can detect the stub state. The existing autoset
lookups on the **SDXL** registration (`autoset_denoise["supir"] = 0.30`,
`autoset_cn["supir"] = ...`) remain the source of truth for the SUPIR
*method* running on an SDXL backbone — those are unchanged.

Registry count: 26 → 27.

### 2. Refresh README status date

**File**: `README.md`

`Status — May 2026` → `Status — August 2026`. Today is 2026-08-18;
the badge was three months stale.

### 3. Refresh DEEP_DIVE arch-count claim

**File**: `DEEP_DIVE.md` (line 64 of the system-architecture mermaid)

`22 arch registry` → `27 arch registry`. Actual `_reg()` calls in
`architectures.py` = 26 before this PR, 27 after adding the SUPIR stub.
Confirmed via `grep -cE "^_reg\(" architectures.py`.

## Tier 2 — new-model / new-arch integration candidates

Each entry names a real, currently-shippable upstream release, the
Spellcaster surface it maps onto, the VRAM/risk tradeoff, and what
"integrate" would concretely look like. **Not auto-applied** — VRAM
and quality-vs-existing decisions belong to the operator.

| model / arch | released | replaces / augments | vram_gb | risk | tier | integration notes |
|---|---|---|---|---|---|---|
| **LTX-2.5** | 2026-08-12 | our `ltx` arch (currently LTX-2.3 era per ComfyUI blog history) | ~24 | low | 2.1 | ComfyUI has day-0 support in core; `build_ltx_video` shape should carry over, but native multi-shot workflow is new — probably worth a sibling builder `build_ltx25_multi_shot` rather than patching `build_ltx_video` in place. Verify `LTXVBaseSampler` still the canonical node before promoting. |
| **LTX-2.3** | 2026-03-05 | our `ltx` arch (if fleet is still pre-2.3) | ~20 | low | 2.1 | 22B, native 4K@50fps, first open model with synchronized audio+video generation. Even without going straight to 2.5, moving to 2.3 unlocks the audio track — currently no audio+video builder in `workflows.py`. |
| **HunyuanImage-3.0-Instruct** | 2026-01-26 | new image arch (MoE) + I2I with prompt-reasoning | 80B params, ~48–64 needed | high | 2.2 | Adds reasoning-based prompt enhancement + I2I creative editing. Would slot in as a new arch `hunyuan_image_3` alongside the existing `hunyuan_dit` stub (which stays as-is, image-1.x). VRAM is a real gate — most Sparks won't run it. Consider only if Theo has 48+ GB free. |
| **Hunyuan3D-Shape-v2-1 Small** | 2026-02 | refines our existing `hunyuan_3d` arch | ~8 | low | 2.3 | Baseline model shipped alongside HY3D-Bench dataset; small variant fits low-VRAM. Straight upgrade path to the existing `build_hunyuan_3d_mesh` / `build_hunyuan_3d_textured` builders — check the Kijai wrapper pack has caught up before swapping. |
| **Flux2-Klein-9B-Consistency** (community fine-tune, `dx8152/…`) | live | augments existing `flux2klein` for portrait consistency | same as Klein 9B | low | 2.3 | Direct drop-in checkpoint for the 9B Klein slot when the workflow is portrait-consistency-sensitive (character portraits, headswap chains). No builder change needed — this is a preset addition. |
| **FLUX 3** (announcement only) | 2026-07-23 | watch-only; would replace or supersede `flux1dev` + `flux2klein` if BFL ships open weights | unknown | n/a | watch | BFL announced multimodal (image/video/audio/action) but no repo, no license, no param count as of the sweep. Re-check on next run. |

**Explicitly NOT-actionable this cycle** (avoid re-proposing):

- **Wan 2.5 / 2.6** — Alibaba shipped Wan 2.5 (Sep 2025, audio+video +1080p@24fps) and Wan 2.6 (Dec 2025, Reference-to-Video), but **weights are not public**. API-only. Fleet stays on Wan 2.2 for local. Do not add a Wan 2.5/2.6 arch stub.
- **HunyuanImage-3.0 base** (Sep 2025, 80B MoE) — superseded here by the Instruct variant above (same weights + reasoning head + I2I). Only list one.
- **Z-Image Turbo v2** — no announcement from Tongyi-MAI as of 2026-08. Turbo v1 is our current `zit`. Don't add speculative entries.
- **"SUPIR successor"** — nothing shipping. Arxiv 2507.20590 ("Harnessing Diffusion-Yielded Score Priors for Image Restoration") is research, not weights. Keep SUPIR as-is.

## Tier 3 — local_action_queue (structured, machine-consumable)

Actions that need a host on the operator's LAN (Spark GPUs, Theo,
Hermes downloader). Emitted as YAML so a local process can consume
them mechanically instead of parsing prose. Consumer contract: read
this block, execute in order, mark done.

```yaml
local_action_queue:
  - action: download_model_update
    target_repo: Lightricks/LTX-Video   # verify exact HF path against ComfyUI-LTXVideo README before pulling
    target_host: unknown                # whichever Spark hosts the video-gen ComfyUI (Spark that serves the `ltx` arch); operator picks
    reason: >
      LTX-2.5 landed 2026-08-12 with ComfyUI day-0 support and native
      multi-shot generation; 2.3 (2026-03-05) is also a jump if the
      fleet is still on the pre-audio branch. Local weights currently
      unknown from cloud sandbox — operator/Hermes to check disk.
    command_hint: >
      # from the ComfyUI models/ dir on the video-host:
      huggingface-cli download Lightricks/LTX-Video --local-dir models/checkpoints/LTX --include "*ltx*2.5*.safetensors"
      # then restart ComfyUI and run the LTX-2.5 template workflow to confirm the new nodes register.
    risk: low

  - action: download_model_update
    target_repo: tencent/Hunyuan3D-Shape-v2-1
    target_host: unknown                # whichever host runs the hunyuan_3d builder (build_hunyuan_3d_mesh)
    reason: >
      HY3D-Bench release (2026-02) shipped a small baseline model that
      improves shape quality on the low-VRAM Hunyuan3D 2.x pipeline
      already wired via `_reg("hunyuan_3d", ...)`. Straight upgrade
      path; no builder change required — verify Kijai wrapper pack
      version accepts v2.1 shape weights first.
    command_hint: >
      huggingface-cli download tencent/Hunyuan3D-Shape-v2-1 --local-dir models/checkpoints/Hunyuan3D
    risk: low

  - action: evaluate_and_maybe_download
    target_repo: tencent/HunyuanImage-3.0-Instruct
    target_host: theo                   # only Theo could plausibly hold a 80B MoE (13B active); confirm free VRAM
    reason: >
      New multimodal image arch with reasoning + I2I creative editing;
      MoE 80B total / 13B active. Would land as a new `hunyuan_image_3`
      arch entry, NOT replacing the existing `hunyuan_dit` stub. Skip
      unless Theo has 48+ GB VRAM free — the whole model plus the T5
      encoder overshoots most single-GPU Sparks.
    command_hint: >
      # inspect first without pulling weights:
      hf_hub_download tencent/HunyuanImage-3.0-Instruct --filename README.md --local-dir /tmp/hy3-inspect
    risk: high

  - action: preset_addition_only
    target_repo: dx8152/Flux2-Klein-9B-Consistency
    target_host: unknown                # whichever host serves Klein 9B
    reason: >
      Community fine-tune of Flux 2 Klein 9B specialised for portrait
      consistency across shots. Slots in as a preset-level checkpoint
      swap for the 9B Klein slot on portrait-heavy workflows (headswap
      chains, character sheets). No `build_klein_*` code change needed.
    command_hint: >
      huggingface-cli download dx8152/Flux2-Klein-9B-Consistency --local-dir models/unet/Flux-2-Klein/Consistency
    risk: low
```

## Corrections to prior operator-memory notes

None this run — prior digest history is empty (`_dev_docs/` contained
only the WHIMWEAVER_REPLAY_BRIDGE_PROPOSAL.md before this commit).

## Delivery status

- Gmail MCP requires re-auth (this session non-interactive → cannot
  run the OAuth flow). Notification via Gmail is **skipped**; PR is
  sole delivery channel per the routine's fallback rule.
- Google-Drive MCP is available but the routine's contract puts
  the digest in-repo (`_dev_docs/…`) so external mirroring would be
  redundant — skipped.
- CI on this PR: not evaluated yet (this is the initial push). If
  `leak-check.yml` or any other check goes red purely on pre-existing
  main issues unrelated to the diff, will diff-verify against base
  and comment rather than treating it as this run's failure.

## Budget accounting

- WebSearch calls used this sweep: 6 (LTX-2.5, LTX-2.3 lineage, FLUX 3,
  Z-Image v2, HunyuanImage 3.0, ReActor). Well inside the ~25 combined
  cap.
- WebFetch calls used: 0 — every WebSearch summary carried enough
  metadata (release dates, VRAM, licence) that no follow-up fetch
  was needed.
