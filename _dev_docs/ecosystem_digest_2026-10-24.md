# Ecosystem digest — 2026-10-24

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `ed19fb4`). Branch: `claude/adoring-allen-4o2g87`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest landed on `main`
  as `75ef09a`; the current head carries three additional commits
  (`ecf4249`, `0e63dc1`, `ed19fb4`) covering model-manifest / preset
  alignment work. This run starts from a clean slate rather than
  stacking on an open queue.
- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`). No
  skeleton draft needed this run. However, two correctness bugs in
  the tool's arch-query map were found by this run's T1-c audit —
  one new (missing arch coverage), one latent (greedy `flux` substring
  matched the wrong arch for every Flux variant). Both fixed in this
  commit (see T1-b, T1-d).
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy
  still denies direct CONNECT to `huggingface.co` / `civitai.com`,
  so the live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here; Hugging-Face
  MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`) is the live
  path from the cloud this run uses. ~6 MCP calls spent of the ~25
  soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — current `main`'s tracked tree stays within
  the canonical pattern list.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
`57 passed`).

### T1-a `architectures.py` docstring: enumeration is 8 arches short

Both mirrors
(`comfyui-spellcaster/spellcaster_core/architectures.py` and
`plugins/gimp/comfyui-connector/spellcaster_core/architectures.py`)
still carried the `SUPPORTED ARCHITECTURES (as of October 2026)`
block the 2026-10-16 digest wrote, listing **11 image + 7 video + 3
other = 21 fully-registered + 6 stubs**. The current `_reg()` set
on disk is now **15 image + 10 video + 4 other = 29 fully-registered
+ 6 stubs** — eight new entries landed in commits `4b1e1c0` (full
Spark2 GB10 NVFP4/FP8/INT8 image & video model support) and
`0e63dc1` / `ed19fb4` (manifest alignment):

- Image: added `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
- Video: added `minimax_h3`, `skyreels`, `longcat`
- Other: added `aurasr`

Expanded the docstring enumeration to match, with one-line
descriptions sourced from each entry's own section comment in the
registry file. Mirror-drift stays byte-identical: identical edit
applied to both copies, `python tests/mirror_drift.py` →
`OK: 32/32   DRIFT: 0`.

### T1-b `tools/upgrade_research.py`: HF arch-query map is still 8 arches short

`_HF_ARCH_QUERIES` had entries for 27 arches but the registry on disk
now has 35 `_reg()` entries (29 fully-registered + 6 stubs). The 8
missing arches are the same 8 the T1-a docstring was missing. That
means `_hf_query_for_method(build_<arch>_*)` returned `None` for
them, so a live `huggingface` or `civitai` backend run would
**silently skip** candidate research for the entire new wave of
2026-10 arches.

Added mappings:

| Arch | Search terms |
|------|-------------|
| `flux2dev`  | `flux.2-dev`, `flux2-dev` |
| `flux3klein`| `flux.3-klein`, `flux3-klein`, `flux-3-image-klein` |
| `krea2`     | `krea-2`, `krea2`, `krea-edit` |
| `qwen_image`| `qwen-image`, `qwen-image-edit` |
| `minimax_h3`| `minimax-h3`, `minimax`, `minimax-video` |
| `skyreels`  | `skyreels-v2`, `skyreels` |
| `longcat`   | `longcat-video`, `longcat` |
| `aurasr`    | `aura-sr`, `aurasr` |

### T1-c `tools/upgrade_research.py`: method-count claim is stale

Module docstring said "70 at the time of that pass, **75 as of
2026-10-16**". Current `build_*` count (via AST walk of
`workflows.py`) is **78**, so the eight-day drift adds 3 more
methods. Bumped to "78 as of 2026-10-24".

### T1-d `tools/upgrade_research.py`: `flux` greedy-match bug

Latent bug found while verifying T1-b: `_hf_query_for_method` iterates
`_HF_ARCH_QUERIES` in insertion order and returns the FIRST arch
whose id or term substring-matches `method_name`. The pre-T1-b
`flux1dev` entry's term list contained a bare `"flux"`, which is a
substring of every method name starting with `build_flux…`. The
resolver therefore mis-routed:

| Method | Pre-fix mapping | Correct mapping |
|--------|-----------------|-----------------|
| `build_flux2klein_repose` | `flux1dev` ❌ | `flux2klein` |
| `build_flux_kontext_edit` | `flux1dev` ❌ | `flux_kontext` |
| `build_flux2dev_*`        | `flux1dev` ❌ | `flux2dev`    |
| `build_flux3klein_*`      | `flux1dev` ❌ | `flux3klein`  |

The live HF backend was consequently returning Flux-1 search results
for Flux 2 / Flux 3 / Flux Kontext methods. Confirmed via a
pre-change AST snapshot (git stash + replay). Fix: drop the overly
generic `"flux"` term from `flux1dev`'s list; keep the two specific
`flux.1-dev` / `flux-1-dev` terms. HF primary-term queries now resolve
each arch correctly (verified post-fix in-process):

```
build_flux1dev_txt2img              -> flux1dev
build_flux2klein_repose             -> flux2klein
build_flux2dev_txt2img              -> flux2dev
build_flux3klein_edit               -> flux3klein
build_flux_kontext_edit             -> flux_kontext
```

This was a pre-existing bug — not introduced by the T1-b additions —
but surfaced by them, so it ships alongside.

**Verification of T1-a through T1-d**

- `pytest tests/` — `57 passed in 7.33s` (post-fix).
- `python tools/upgrade_research.py --dry-run` — exit `0`,
  `4 proposals from 5 backends` (same shape as before edits).
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `_hf_query_for_method` resolver on every new arch verified
  in-process (above).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Comfy-Org/MOSS-Image** + **OpenMOSS-Team/MOSS-Image-Base** / **-SFT** | 2026-10-16 → 2026-10-22 | NEW `moss_image` arch — a new 5.08B-param open diffusion transformer specialising in long-form text + layout-coherent images (arXiv 2610.23374, Apache-2.0). | ~10 GB fp16 (5.08B params) | medium | 2 | **1.94M downloads** / 418 likes on the `Comfy-Org/MOSS-Image` repackage (diffusion-single-file, drops into `ComfyUI/models/checkpoints/`), 97 upvotes on the companion paper. Base + SFT variants published by `OpenMOSS-Team`. 15+ demo Spaces already up. Would land as `_reg("moss_image", loader="unet_clip_vae", clip_mode="single_moss_image", vae_mode="separate", …)` beside the `qwen_image` entry — the paper's "intent-aware prompt enhancement" shape slots into the existing LM-Studio prompt-enhancer hook. SOTA on long-form text + layout per the paper's claims; direct comparator for Qwen-Image-2.1 and Flux-3-Klein on the "typography + many-object scene" axis. |
| **lodestones/Kromoss** | 2026-10-24 | Fine-tune of MOSS-Image-Base, same 5.08B shape; new fine-tuner on this arch | ~10 GB fp16 (5.08B params) | low | 2 | 244 likes / 21.1K downloads. Pairs with the MOSS-Image arch above — if `moss_image` lands as a registered arch, this is a LoRA/fine-tune candidate for the character-consistency builder set. Apache-2.0. |
| **unsloth/flux-3-image-klein-GGUF** | 2026-10-16 | Low-VRAM path for the already-queued `flux3klein` fleet download | ~5 GB fp8 / 6 GB Q6_K | low | 2 | 49.5K downloads / 32 likes in 8 days. Pairs with the `black-forest-labs/flux-3-image-klein-comfy` download the 2026-10-16 digest filed as Tier-3. If the operator plans the 12-GB tier (Theo-style peers), prefer this over the full `-comfy` repack. |
| **unsloth/flux-3-image-klein-FP8** | 2026-10-16 | FP8 variant of the same, for Spark2 NVFP4/FP8 tier | ~5 GB FP8 | low | 2 | 54.6K downloads / 4 likes. Spark2's commit `4b1e1c0` already added NVFP4/FP8/INT8 wiring for the current arches; dropping FP8 Flux-3-Klein weights would exercise that path on the newest Flux generation. |
| **unsloth/LTX-2.5-GGUF** | 2026-10-13 | Low-VRAM / consumer-grade path for the `ltx` arch LTX-2.5 upgrade | ~8 GB Q4_K_M / ~12 GB Q6_K | low | 2 | 85.2K downloads / 16 likes. The 2026-10-16 digest filed `Lightricks/LTX-2.5` (full fp16, 2.1M downloads) as Tier-3; this GGUF repackage is unsloth's canonical low-VRAM path — matches how the fleet already runs Wan 2.5 and Qwen-Image GGUF variants. Would land as the default LTX-2.5 download target for 12-GB tier peers (Theo). |
| **comfyicu/LTX-2.5** | 2026-08-13 | Non-gated mirror of `Lightricks/LTX-2.5` | same as base | low | 2 | 1.8M downloads / 10 likes. Byte-identical repack of the gated upstream, which means fleet hosts can skip `huggingface-cli login`. Not an upgrade of the base weights — a *packaging-only* fallback for operators without an HF account on a given Spark. |
| **JoaoZaokk/LTX-2.5-22B-distilled-W4A8-ConvRot** | 2026-09-13 | Experimental INT4 / W4A8 LTX-2.5 distill | ~5-6 GB (W4A8) | medium | 2 | 142.8K downloads / 2 likes. Aggressive quantization; low likes signal community hasn't validated the quality delta vs. the Q6_K GGUF path above. Interesting ceiling for the 8-GB tier but mark as "evaluate against GGUF Q4 before shipping". |
| **DeepSeek-AI/DeepSeek-V4.1-Flash-1017** | 2026-10-17 | **Not a Spellcaster arch** — image-text-to-text VLM; relevant to `llm_delegate.py` as a vision-capable prompt enhancer | ~24 GB fp16 (big — likely needs quantized GGUF path) | medium | 2 | 2.7K likes / 73K downloads in 7 days; trending #1 on the Hub this week. Candidate to wire into `llm_delegate.py` alongside the existing `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4` prompt enhancer the 2026-10-16 digest filed. The `unsloth/flint-GGUF` (78K downloads) is a related GGUF path. |
| **MiniMaxAI/MiniMax-M3.1-Flash** | 2026-10-23 | Multimodal companion for the existing `minimax_h3` video arch | ~16 GB fp16 | medium | 2 | 289 likes / 5.8K downloads. Same lineage as `minimax_h3` which landed in `architectures.py` this month. Could feed into the `minimax_h3` prompt-conditioning path or stand up as a sibling "chat about this video" tool. Low downloads so far (released yesterday), low priority. |

### Tier-2 non-model findings

- **MOSS-Image is this fortnight's T2 headline.** It's the only
  genuinely new text-to-image *architecture family* to land since
  the 2026-10-16 digest. The paper's "long-form text + layout
  coherence" claim is the kind of capability that would differentiate
  it from Flux-3-Klein and Qwen-Image-2.1 on the "poster, slide,
  brochure" axes — i.e. where the user's photography / editorial
  work does intersect. Priority call for the operator:
  *does the fleet have slack for a fourth text-to-image arch
  this quarter alongside Flux-3-Klein, Qwen-Image-2.1, and the
  existing Flux-2 / Z-Image set*, or is MOSS-Image a 2026-Q1
  track? One lane; name it before downloads start.

- **LTX-2.5 download format decision carries forward.** The 2026-10-16
  digest filed the gated `Lightricks/LTX-2.5` as Tier-3; this week
  the ecosystem produced three parallel paths (the official
  non-gated `comfyicu/LTX-2.5`, `unsloth/LTX-2.5-GGUF`, and
  `JoaoZaokk/.../distilled-W4A8-ConvRot`). The operator picks ONE —
  going by the Qwen-Image-2.1 precedent (where the Turbo-GGUF path
  dominated), unsloth's GGUF is the probable winner for the fleet,
  but confirm.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-10-24 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/MOSS-Image
    target_host: spark2
    reason: "MOSS-Image is a new 5.08B diffusion-transformer arch (OpenMOSS-Team) specialising in long-form text + layout-coherent image generation (arXiv 2610.23374). 1.94M downloads on the ComfyUI-ready repack in 8 days — fastest trajectory of any new T2I arch since Flux-3-Klein. Apache-2.0. Needs operator call on whether to make room for a fourth T2I arch alongside Flux-3-Klein / Qwen-Image-2.1 / Z-Image; this entry only grabs the weights for a benchmark, no architectures.py changes yet."
    command_hint: "huggingface-cli download Comfy-Org/MOSS-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MOSS-Image"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: unsloth/LTX-2.5-GGUF
    target_host: unknown
    reason: "GGUF path for LTX-2.5 (the gated full-precision Lightricks/LTX-2.5 remains in the Tier-3 queue). unsloth GGUFs are the fleet's standard low-VRAM path (same provider as the Qwen-Image-2.1 GGUF the previous digest also recommended). 85K downloads in 11 days. Prefer the Q4_K_M quant for 12-GB peers, Q6_K for 16-GB."
    command_hint: "huggingface-cli download unsloth/LTX-2.5-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\LTX-2.5-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: unsloth/flux-3-image-klein-GGUF
    target_host: theo
    reason: "Low-VRAM GGUF path for Flux-3-Klein that pairs with the already-queued black-forest-labs/flux-3-image-klein-comfy download. For the 12-GB tier (Theo-style peers) prefer this over the full -comfy repack. Same provider pattern as the LTX-2.5-GGUF above."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-GGUF --include '*Q6_K*' --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: unsloth/flux-3-image-klein-FP8
    target_host: spark2
    reason: "Spark2 commit 4b1e1c0 added NVFP4/FP8/INT8 wiring across all plugins. The FP8 Flux-3-Klein variant lands straight into that path. 54.6K downloads in 8 days. Exercises the newest piece of the fleet's quantization matrix on the newest Flux generation."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-FP8 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein-FP8"
    risk: low

  - action: evaluate_llm_candidate
    target_repo: deepseek-ai/DeepSeek-V4.1-Flash-1017
    target_host: unknown
    reason: "Trending #1 on HF this week (2.7K likes / 73K downloads in 7 days). Image-text-to-text VLM; relevant to llm_delegate.py's prompt-enhancer path. Likely needs the unsloth/flint-GGUF (78K downloads, same arch family) for a 12-GB-tier peer. NOT an image-generation arch — this is a tool-change for llm_delegate.py, not architectures.py."
    command_hint: "# evaluate in LM Studio first; if viable, GGUF path:\nhuggingface-cli download unsloth/flint-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\LMStudio\\models\\flint-GGUF"
    risk: medium

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein — direct successor to _reg('flux2klein', ...). Gated=auto on HF; needs huggingface-cli login on the fleet host once. Note: flux3klein IS now registered in architectures.py (post-2026-10-16), so once weights are on disk the arch is live. Pair with the FP8 or GGUF entries above for the lower tiers."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Fast distilled companion to Qwen-Image-2.1. Prefer the GGUF path (unsloth/Qwen-Image-2.1-Turbo-GGUF, 294K downloads) for the 12-GB tier. The qwen_image arch IS now registered in architectures.py (post-2026-10-16), so weights-on-disk enables the builder set."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "Still unactioned from 2026-10-16. Confirm which SAM3 weights build_sam3_segment is actually loading (3.0 vs 3.1 vs sam2). One-liner on each fleet host; no download yet, just a path check."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Weights-only drop-in for the already-wired build_sam3_segment, IF the SAM3Segment node loader accepts 3.1-shape weights at the same path. Audit above runs first."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on top of LTX-2.5. Depends on LTX-2.5 base. ~2 GB. Unlocks a build_ltx_remove_bg_video builder. Downloads=16.4K / likes=218 as of today — likes nearly doubled since 2026-10-16."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. Also depends on the LTX-2.5 base. ~2 GB. Pairs with the existing supir image upscaler for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement. Deciding point: human-mesh output format (SMPL-X vs GLB) vs. what spellcaster downstream tools consume."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Base Qwen-Image-2.1 weights for the already-registered qwen_image arch — community has clearly chosen the Turbo lane, but if the fleet picks full-quality this is the right starting point."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). Base repo at 2.1M downloads / 9124 likes as of today — up ~200K and +1089 likes in 8 days. Gated=auto; needs HF login. Note the non-gated comfyicu/LTX-2.5 mirror as a login-free alternative."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for existing _reg('hunyuan_3d', ...); 2.1 mesh+texture pipeline may need node-list audit before the swap."
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
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-b now gives the HF arch-query map 8 additional arches to probe (and T1-d fixes a greedy-match bug that was silently misrouting every Flux-family query) when the tool DOES run from the LAN. Re-run should show MORE than 20/78 methods mapping to an HF query — specifically, every post-2026-10 arch should now resolve correctly."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein, the older weights on D:\\LLM should be flagged for retirement. Still awaiting the tools/audit_disk_vs_registry.py tool (follow-up #1 below)."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; drafting candidate below."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.** Carried
   over from 2026-10-16. Now that Flux-3-Klein, Qwen-Image-2.1 (Turbo
   GGUF path), and LTX-2.5 all have T3 download entries queued, the
   retirable-weights question grows every digest. Writing this tool
   is still a ~100-line Tier-1 candidate for a future digest. The
   tool's spec: parse `architectures.py` → set of `registered=True`
   arches, walk `ComfyUI/models/*` on each fleet host, print paths
   whose filename stem does not match any registered arch's known
   filenames, grouped by directory. A --json flag writes a structured
   report into `_dev_docs/retirable_weights_<date>.json` that
   `local_action_queue` entries can reference.

2. **Transport fallback for `tools/upgrade_research.py`.** Still open
   — the tool's HF and civitai backends use `urllib`, which the cloud
   proxy 403s. Teaching the `huggingface` backend to prefer an MCP
   transport (via `mcp__Hugging-Face__hub_repo_search`) when one is
   available would let *this* routine run the ranked backend from the
   cloud instead of the skeleton one. Doable but it broadens the
   tool's dependency surface. Candidate for the next time MOSS-Image
   or similar lands and the digest wants to query HF directly.

3. **`flux3klein` is now registered — operator Go/No-Go for the
   weights download.** `_reg("flux3klein", …)` is live in both
   mirrors. The weights still need to land on a fleet host before
   `build_flux3klein_*` works. T3 queue has entries for the full
   `-comfy` repack, GGUF, and FP8 variants — pick ONE.

4. **MOSS-Image Go/No-Go.** This fortnight's genuinely new T2I
   architecture. Operator call: is MOSS-Image a 2026-Q4 ship or a
   2027-Q1 track? One lane; name it.

5. **LTX-2.5 download-format call still open.** Three parallel paths
   this fortnight (gated, non-gated mirror, unsloth GGUF). The
   previous digest's precedent (Qwen-Image-2.1 → Turbo-GGUF won) says
   this probably ends in `unsloth/LTX-2.5-GGUF`, but the operator
   decides.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
AST scans of `architectures.py`, `workflows.py`; `pytest tests/`;
`python tests/mirror_drift.py`._
