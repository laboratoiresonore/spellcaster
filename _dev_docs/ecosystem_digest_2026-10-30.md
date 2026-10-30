# Ecosystem digest — 2026-10-30

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-vrypv3`.

## Delivery notes

- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` runs cleanly (`4 proposals from 5 backends`, 78 methods
  in scope). No skeleton draft needed.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`; this run
  used Hugging-Face MCP (`hf_fs`, `hub_repo_search`) for live Hub
  reads instead. ~10 MCP calls spent of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — not scanned manually this run; the leak-check
  workflow is already wired via `.githooks/leak-patterns` and runs on
  every push. The current diff only touches `README.md`, `DEEP_DIVE.md`,
  `architectures.py` (both copies), `tools/upgrade_research.py`, and
  this digest; no credential-shaped strings introduced.
- **Backlog note.** 15 earlier ecosystem-digest PRs (#185 … #200) are
  still open against `main`. The branch for this run was spun off from
  `main` cleanly, so this digest does NOT stack on them — it's the
  next independent sweep.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
57/57, `python tests/mirror_drift.py` → `OK: 32/32   DRIFT: 0`,
`python tools/build_builders_manifest.py` → `78 methods`,
`python tests/night_maintenance.py --dry-mode --quiet` → exit `0`).

### T1-a `README.md` + `DEEP_DIVE.md`: tool-count drift `75 → 78`

`builders_manifest.json` has `method_count: 78` (and `grep -c '^def
build_' comfyui-spellcaster/spellcaster_core/workflows.py` → `78`),
but 11 user-facing surfaces across `README.md` and `DEEP_DIVE.md`
still claimed `75 tools`:

- `README.md:9` — tagline `75 AI tools, one menu.` → `78`.
- `README.md:76, 99, 110, 131`, plus `139`, `212` — anchor references
  `DEEP_DIVE.md#all-75-tools` all swapped to `#all-78-tools` (the
  anchor target itself renamed in `DEEP_DIVE.md`).
- `README.md:139` — body text `75 tools across 19 models` → `78`. The
  `19 models` surface claim is left as-is: it is intentionally stable
  marketing copy that doesn't track the arch registry 1:1 (same
  treatment the 2026-09-22 digest gave when going 69 → 75 tools).
- `README.md:212` — `All 75 tools →` → `All 78 tools →`.
- `README.md:330` — GIMP menu caption `75 tools across Filters >
  Spellcaster` → `78`.
- `DEEP_DIVE.md:17` — TOC `[All 75 Tools](#all-75-tools)` → `78`.
- `DEEP_DIVE.md:52` — architecture mermaid `GIMP 3<br/>75 tools` →
  `78`.
- `DEEP_DIVE.md:300` — section heading `## All 75 Tools` → `## All 78
  Tools` (this is the anchor target).

Verification: `grep -nE '\b75\b' README.md DEEP_DIVE.md | grep -iE
'tool|all.*75'` returns zero matches post-fix.

### T1-b `architectures.py` docstring: 8 arches missing from enumeration

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried a
`SUPPORTED ARCHITECTURES (as of October 2026)` block listing 11 image
+ 7 video + 3 other = 21 fully-registered arches. The registry on
disk has 35 `_reg(...)` entries, with 29 fully-registered + 6 stubs.

Missing from the docstring (all fully-registered on disk, with
section comments in the source):

- Image: `flux2dev` (Flux 2 Dev, 20-step full-size variant),
  `flux3klein` (Flux 3 Image Klein — SD & Base, Qwen3VL-4B encoder),
  `krea2` (Krea 2 Turbo / Krea Edit, Qwen3VL-4B krea2 encoder + Qwen
  Image VAE), `qwen_image` (Qwen Image Edit 2511, Qwen 2.5 VL 7B +
  Qwen Image VAE).
- Video: `minimax_h3` (MiniMax-H3 joint video+audio generation,
  NVFP4 on Spark2), `skyreels` (SkyReels-V2 1.3B 540p DF/I2V,
  Wan-compatible conditioning), `longcat` (LongCat Video via
  WanVideoWrapper).
- Other: `aurasr` (AuraSR v2 GAN-based 4x image upscaler, custom
  wrapper).

Added all 8 entries in-place preserving the existing order within
each section. The 6-stub list below (`sd3`, `sd3_turbo`,
`hunyuan_dit`, `pixart`, `auraflow`, `kolors`) is unchanged.

Mirror parity: identical edit applied to both copies; `python
tests/mirror_drift.py` → `OK: 32/32   DRIFT: 0`.

### T1-c `tools/upgrade_research.py`: HF arch-query map is missing 8 arches

`_HF_ARCH_QUERIES` had entries for 27 arches but the registry on disk
has 35, so a live `backend_huggingface` or `backend_civitai` pass
would silently skip candidate research for 8 fully-registered image /
video / upscaler arches.

Added mappings for: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`,
`minimax_h3`, `skyreels`, `longcat`, `aurasr`. All include the
canonical HF slug plus common variant spellings — e.g. `qwen_image`:
`["qwen-image-2.1", "qwen-image-edit", "qwen-image"]`.

Also bumped the stale method-count claim in the module docstring from
`75 as of 2026-10-16` → `78 as of 2026-10-30`.

Post-fix invariant: a repeated AST diff of `_HF_ARCH_QUERIES` keys
vs. `_reg(...)` arg-0 strings now reports `MISSING: []` (previously
`['aurasr', 'flux2dev', 'flux3klein', 'krea2', 'longcat',
'minimax_h3', 'qwen_image', 'skyreels']`).

### Verification of T1-a through T1-c

- `pytest tests/` — `57 passed in 8.12s` (test count is up from 52
  in the 2026-10-16 digest — new tests have landed since).
- `python tools/upgrade_research.py --dry-run` — exit `0`, same
  `4 proposals from 5 backends` shape.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tests/night_maintenance.py --dry-mode --quiet` — exit `0`.
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  no manifest regen required.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`). Numbers below are the HF report at the time of
this digest. Verified against the Oct-16 digest's Tier-2 roster;
rows below are **net new** since that run.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 | Camera-control / layout adapter on top of LTX-2.5 — would land as `build_ltx_layout_to_render` on the `ltx` arch | ~2 GB (adapter) | low | 2 | 15.9K downloads / 120 likes. New since the Oct-16 digest filed Alpha-Gen/Upscaler/Refine/Ingredients. Pairs with existing `klein_repose` camera/pose UX — this is the LTX equivalent on video. Same license + distribution contract as the base LTX-2.5 (Lightricks-published, non-commercial). |
| **Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR** | 2026-09-28 | HDR tone-map conversion adapter — would land as `build_ltx_sdr_to_hdr` on `ltx` | ~2 GB (adapter) | low | 2 | 16.6K downloads / 51 likes. Also new since Oct-16. The spellcaster `lut` / `color_match` builders currently cover SDR colour grading only; this would be the first HDR-aware builder in the registry. Operator decision: does the Resolve plugin's output pipeline expect SDR or HDR today? |
| **Wan-AI/Wan2.2-Animate-14B** + **QuantStack/Wan2.2-Animate-14B-GGUF** | 2025-09-11 / 2025-09-19 | Base + GGUF quantization backing `build_wan_animate_video` on the `wan` arch | ~24 GB fp16 / ~8-14 GB GGUF Q4-Q8 | medium | 2 | 207.6K + 381.3K downloads / 1,303 + 234 likes. The base Wan 2.2 I2V (`QuantStack/Wan2.2-I2V-A14B-GGUF`, 891.7K / 456) is the one `build_wan_video` targets; the Animate variant is used by `build_wan_animate_video` and may already be the fleet's running weights — an audit (same shape as the Oct-16 SAM3 audit) confirms this before any download. |
| **Wan-AI/Wan2.2-Animate-2-14B-Distilled-Diffusers** | 2026-08-06 | Distilled few-step companion to the Animate 14B — fast lane for 12-GB tier `build_wan_animate_video` | ~14 GB fp16 (distilled) | medium | 2 | 5.2K downloads / 16 likes. Fresh (Aug-2026), low adoption yet but Lightricks' own distill lane for Wan Animate 2. Would land in the same PR as the Animate-2 base-weight pick, as a 4-6 step default. |
| **ByteDance/Sa2VA-Qwen3-VL-4B-SAM3** | 2026-06-10 | Alternate "AI Select by Description" engine for the SAM3Segment node (text-grounded referring-segmentation) | ~4 GB fp16 (Qwen3-VL backbone) | medium | 2 | 632 downloads / 3 likes. Low adoption so this is a watch, not a swap. Named here because it's the first referring-segmentation model that explicitly chains Qwen3-VL + SAM3 — same shape as the "type the hair, select the hair" README promise, but with VL-conditioned matching for ambiguous prompts ("the leftmost person's jacket"). Keep tracking before committing fleet storage. |
| **MiniMaxAI/MiniMax-M3.1-Flash** | 2026-10-30 | Fresh LLM for LM Studio prompt-enhancement delegate (`tools/llm_delegate.py`) | ~3-7 GB GGUF Q4 depending on quant | low | 2 | 499 likes / 18.8K downloads at <24h on HF. Trending top-20. image-text-to-text — hints at multimodal prompt-enhancement for the `qwen_image` / `krea2` arches where VL rewriting is useful. Alternative to the `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4` already filed in the Oct-16 digest. |

### Tier-2 non-model finding

- **The 15-PR backlog.** PRs #185 through #200 (plus #192, #193) are
  all open ecosystem-digest PRs stacked on `main`, each independent.
  Nothing in them conflicts with this digest's T1-a/b/c diff (they
  touch different docs and different docstring sections most of the
  time). Operator decision outside this run's scope: either batch-
  merge them, cherry-pick, or close as superseded.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries forward unresolved 2026-10-16 and 2026-09-22 entries that
have not been reported as actioned, plus this run's new ones. A local
Hermes / operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-10-30 ───────────────────────────────────────────

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Camera-control / layout-to-render adapter on LTX-2.5. Depends on LTX-2.5 base weights (still-open Tier-3 download from 2026-10-16). ~2 GB, unlocks build_ltx_layout_to_render as a camera-aware video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR
    target_host: spark1
    reason: "HDR tone-map conversion adapter on LTX-2.5. ~2 GB. First HDR-aware video builder for spellcaster. Operator check first: does the Resolve plugin pipeline currently emit SDR or HDR output?"
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-SDR-HDR"
    risk: low

  - action: audit_wan_animate_version_on_fleet
    target_repo: Wan-AI/Wan2.2-Animate-14B
    target_host: unknown
    reason: "build_wan_animate_video uses the WanAnimateToVideo native node. Confirm which Animate weights that node is actually loading — Wan2.2-Animate (1,303 likes) or the newer Wan2.2-Animate-2 (18 likes). One-liner on each fleet host; informs whether the next Tier-3 is an upgrade or a status report."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'Wan2.2*Animate*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: Wan-AI/Wan2.2-Animate-2-14B-Distilled-Diffusers
    target_host: spark1
    reason: "Distilled few-step Wan Animate 2. ~14 GB. 4-6 step default for 12-GB tier. Audit above runs first to confirm current weights aren't already the right lane."
    command_hint: "huggingface-cli download Wan-AI/Wan2.2-Animate-2-14B-Distilled-Diffusers --local-dir D:\\LLM\\ComfyUI\\models\\wan\\Wan2.2-Animate-2-Distilled"
    risk: medium

  - action: download_and_evaluate_llm
    target_repo: MiniMaxAI/MiniMax-M3.1-Flash
    target_host: theo
    reason: "Fresh multimodal LLM for LM Studio prompt-enhancement delegate on krea2 / qwen_image arches. Trending top-20 at the time of this digest (<24h, 499 likes). Try side-by-side vs the Qwen3-4b-Z-Image-Engineer already queued."
    command_hint: "# Via LM Studio: Settings > Models > Download > search 'MiniMaxAI/MiniMax-M3.1-Flash' > pick Q4_K_M GGUF"
    risk: low

  - action: watch_model_do_not_download
    target_repo: ByteDance/Sa2VA-Qwen3-VL-4B-SAM3
    target_host: unknown
    reason: "Referring-segmentation (Qwen3VL + SAM3) with text grounding. 632 downloads only — low adoption. Flag as a watch, not a download: revisit in a future digest once >5K downloads, then compare against SAM3's existing text-grounded masking."
    command_hint: "# no action yet — track in future digest; not a current download"
    risk: low

  # ─── Carried over, still open — 2026-10-16 ──────────────────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein lands as the direct successor to _reg('flux2klein', ...). The -comfy repackage is diffusion-single-file so it drops into ComfyUI/models/checkpoints/ with no diffusers-pipeline plumbing. Gated=auto on HF."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Fast distilled companion to Qwen-Image-2.1 base. Prefer the GGUF path (unsloth/Qwen-Image-2.1-Turbo-GGUF, 294K downloads) for the 12-GB tier — base repo is diffusers-only."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet, just a path check."
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
    reason: "Alpha-matte / background removal adapter on top of LTX-2.5. ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. ~2 GB. Pairs with supir image upscaler for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  # ─── Carried over, still open — 2026-09-22 ──────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Base Qwen-Image-2.1 arch — superseded on the community side by the Turbo distill (see above). If the fleet picks the full-quality lane rather than the few-step one, this is still the right weights."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). HF now shows 2.3M downloads / 9,924 likes on the base repo — confirmed dominant open-source i2v. Gated=auto; needs HF login the sandbox doesn't have."
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
    reason: "Enables build_controlnet_gen on the zit arch (currently an empty cn list). 99.0K downloads / 466 likes."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c now gives the HF arch-query map 8 extra arches to probe when the tool runs from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein, the older weights on D:\\LLM should be flagged for retirement. Mechanical audit: compare architectures.py registered=True set against ComfyUI/models/*."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; still a drafting candidate for a future digest's Tier-1."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.** Named
   in prior queues but has never been written. If the next wave of
   fleet downloads lands (Flux-3-Klein, LTX-2.5, Qwen-Image-2.1,
   Wan 2.2 Animate variants), the retirable-weights question lives
   behind this tool. ~100-line Tier-1 candidate for a future digest:
   read `architectures.py` + walk `ComfyUI/models/*`, print paths
   matching `registered=True` arches that have more than one weights
   candidate on disk.

2. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap the 2026-09-22 digest flagged — the tool's HF and civitai
   backends use `urllib`, which the cloud proxy 403s. Teaching the
   `huggingface` backend to prefer an MCP transport when one is
   available would let *this* routine run the ranked backend from the
   cloud instead of the skeleton one. Doable but it broadens the
   tool's dependency surface, so not shipped here.

3. **`19 models` surface claim.** The POWERED BY badge strip in
   `README.md:134-136` lists 19 named model/helper lines total (11
   image + 3 video + 5 helpers). The real `_reg(...)` set is now 29
   fully-registered. The gap is intentional (marketing-level) and
   stayed stable across every digest since 2026-09-22, but if the
   operator wants it refreshed, two options exist: (a) refresh the
   badge strip to include `Flux 2 Dev / Flux 3 Klein / Krea 2 / Qwen
   Image / MiniMax-H3 / SkyReels / LongCat / AuraSR`, bumping to
   something like `27 models`; or (b) rephrase to `75+ tools, dozens
   of models`. Needs the operator's call on tone, so filed here.

4. **PR backlog.** 15 ecosystem-digest PRs (#185 … #200) are still
   open. Nothing in this digest conflicts with them, but they're
   accumulating. Possible next-run T1: a one-shot script that walks
   the PR list, computes which fixes have already been applied via
   subsequent runs' re-fix, and closes superseded ones.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`, `hf_fs`;
local `tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`._
