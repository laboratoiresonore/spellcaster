# Ecosystem digest — 2026-11-16

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/digest-2026-11-16`.

## Delivery notes

- **Previous digest status.** The 2026-10-16 digest closed its own
  follow-up for `fetch_metadata.py` and the tenth-digest backlog
  question, and left two still-open candidates for a future Tier-1:
  (1) draft `tools/audit_disk_vs_registry.py`, and (2) teach
  `upgrade_research.py` an MCP transport for its HF backend. This run
  ships **(1)** as T1-c below. **(2)** remains Tier-3 scope — see the
  Follow-ups section — because it broadens the tool's dependency
  surface and the sandbox-proxy question hasn't changed since last
  run.
- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`). No
  skeleton draft needed this run.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy
  continues to deny direct CONNECT to `huggingface.co` /
  `civitai.com`, so the live `backend_huggingface` /
  `backend_civitai` paths of `tools/upgrade_research.py` still return
  nothing from here. Hugging-Face MCP (`hub_repo_search`,
  `hub_repo_details`) remains the live research path from the cloud;
  10 MCP calls spent of the ~25 soft budget this run.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself. Both servers are connected but the brief
  explicitly allows the PR as sole delivery, which is what this run
  uses.
- **Leak-check** — the canonical pattern list at
  `.githooks/leak-patterns` plus the CI job at
  `.github/workflows/leak-check.yml` cover the tracked-tree sweep.
  Not re-scanned from the sandbox this run (the 2026-10-16 digest
  cleared the file-exclusion follow-up); every edit in this branch
  is to a file that was already on `main` with the same leak-check
  posture, except for the new `tools/audit_disk_vs_registry.py` which
  is a stdlib-only Python file with no credential material.
- **Test suite.** `pytest tests/` → `57 passed in 8.85s` on this
  branch (up from the 52 the 2026-10-16 digest observed —
  `test_cn_compat`, `test_lane6_video_compat`, `test_summon_archetypes`,
  and two others landed on main in the intervening weeks).

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose
fix is in this branch and whose regression suite passes
(`pytest tests/` → 57/57, `python tests/mirror_drift.py` →
`OK: 32/32  DRIFT: 0`, `python tools/build_builders_manifest.py
--check` → `manifest fresh (78 methods)`).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner. Today is 2026-11-16.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left as-is
(all four cells still describe past-tense "landed" items that remain
true today — self-healing installer, LM Studio prompt enhancement,
mirror sync, DaVinci Resolve plugin in test).

### T1-b `architectures.py` docstring: enumeration + date

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
module-level `SUPPORTED ARCHITECTURES (as of October 2026):` block
and the 21-full-registered enumeration the 2026-10-16 digest shipped.
In the intervening month the registry on disk has **grown to 29
fully-registered + 6 stubs = 35 total `_reg()` entries**. The
previous enumeration was missing eight full registrations:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
- Video: `minimax_h3`, `skyreels`, `longcat`
- Other: `aurasr`

Also noted which of those have a `build_*` method wired yet —
`build_krea2_edit`, `build_skyreels_video`, and `build_aurasr_upscale`
exist in `workflows.py`; the other five are registered-but-not-wired
("builder TBD"). That detail goes directly in the enumeration so a
future reader can see at a glance which arches are a full-stack
addition vs. a half-landed one.

Bumped the header to `(as of November 2026):` and expanded the list
in both mirror copies. Mirror parity preserved
(`tests/mirror_drift.py` → `OK: 32/32  DRIFT: 0`).

### T1-c `tools/audit_disk_vs_registry.py`: draft the carried-over tool

The 2026-09-22 and 2026-10-16 digests both filed this as a Tier-1
drafting candidate. Shipped now (~340 lines, no runtime deps beyond
stdlib). What it does:

- AST-walks `architectures.py` to produce the set of
  `registered=True` arch ids (29 at HEAD) + stubs (6).
- Walks a configurable `ComfyUI/models/*` tree (default
  `D:\LLM\ComfyUI\models` to match the operator's Windows fleet
  layout), buckets every `*.safetensors` / `*.gguf` / `*.ckpt` /
  `*.pt` / `*.pth` / `*.sft` file by its immediate parent directory,
  and classifies each bucket into one of:
  - **matched** — bucket name is a substring of a registered arch id,
    longest-match wins so `sdxl-turbo-v2/` picks `sdxl_turbo` not
    `sdxl`.
  - **unmatched_on_disk** — retirement candidates (or clip/vae/cn
    weights that legitimately live outside the arch set — operator
    decides).
  - **missing_from_disk** — arches registered as `True` with no
    matching directory (as of this run the whole 29-arch set is
    "missing" from the cloud sandbox's view because there is no fleet
    disk here; this is expected, see Tier 3 for the real audit).
  - **duplicate_weights** — a single arch dir with more than one
    weight file; benign for quant variants, worth a glance for
    orphaned pre-upgrade checkpoints.

Three exit codes (0 clean, 1 findings, 2 parse failure), plus an
optional `--json` machine-readable report so a future Hermes process
can consume the retirement proposals mechanically. Read-only: never
deletes or moves anything.

Smoke-tested from the sandbox:

- `python tools/audit_disk_vs_registry.py --dry-run` → exit 0,
  prints registry-only report shape (29 full / 6 stub / 0 disk
  entries).
- `python tools/audit_disk_vs_registry.py --models-dir
  /tmp/fake-tree` on a hand-built layout with `checkpoints/sdxl/`
  (two fp16/fp8 files) + `checkpoints/flux-2-klein/` + `orphan-arch/`
  reproduces the expected buckets (matched: 2, unmatched: 1,
  dupes: 1, missing: 27), and the longest-arch-first scan correctly
  prefers `sdxl` over `sdxl_turbo` for a bare `sdxl/` directory.
- Did NOT run against a real fleet host (sandbox can't reach the LAN
  per H6). That's a Tier-3 entry below.

### T1-d `tools/upgrade_research.py`: method count + arch-query map

Two separate drifts fixed in one edit:

1. **Module docstring claimed "75 as of 2026-10-16"**; actual
   `build_*` count is now 78 in `workflows.py` (confirmed on both
   mirror copies). Bumped to `78 as of 2026-11-16`.
2. **`_HF_ARCH_QUERIES` only mapped 27 of the 35 current arches**,
   so a live run of `backend_huggingface` / `backend_civitai` would
   have silently skipped candidate research for the eight new
   fully-registered arches (`flux2dev`, `flux3klein`, `krea2`,
   `qwen_image`, `minimax_h3`, `skyreels`, `longcat`, `aurasr`).
   Added mappings for all eight; the HF/civitai search keywords
   follow the patterns the 2026-10-16 digest's T1-c established
   (Hugging-Face publishes e.g. `black-forest-labs/flux-3-image-klein`
   rather than `flux3klein`). Also broadened the `wan` entry to pick
   up the `wan-2.5` / `wan-3-0` generations and the `ltx` entry to
   lead with `ltx-2.5` (the dominant community variant in the HF
   downloads this run; see Tier 2).

Verification: `python tools/upgrade_research.py --dry-run` still
exits 0 with the same `4 proposals from 5 backends` shape;
`pytest tests/` → `57 passed`; `tests/mirror_drift.py` →
`OK: 32/32  DRIFT: 0`.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hub_repo_search` with sort by
`trendingScore` and `downloads`). Numbers are the HF report at the
time of this digest. All findings are new since the 2026-10-16
digest, OR updates to that digest's open Tier-2 items.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **VideoRebirthAI/hyperflow-h3-flash** | 2026-11-04 | NEW — few-step distill companion for the already-registered `minimax_h3` arch | ~10 GB bf16, ~5 GB int8 | medium | 2 | **572.3K downloads / 317 likes / trending 134** in the first ~12 days. Based on `MiniMaxAI/MiniMax-H3`, which already has `_reg("minimax_h3", …)` at `architectures.py:1336` — but `minimax_h3` has NO `build_minimax_h3_*` method yet (see Follow-ups). A ComfyUI-ready int8 quant lives at `BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI` (75.5K downloads, 35 likes) and an NVFP4 variant at `BennyDaBall/HyperFlow-H3-Flash-NVFP4-ComfyUI` (178 downloads but published only 2026-11-15 — matches the Spark2 NVFP4 convention the `minimax_h3` `_reg(…, extra={"clip_type": "minimax", …})` already hints at). Landing this would be the first `build_minimax_h3_*` method AND a few-step default in the same PR. |
| **meituan-longcat/LongCat-Video-Avatar-1.6** | 2026-11-13 | Audio-driven avatar extension for the already-registered `longcat` arch | ~14 GB | medium | 2 | 125 downloads / 48 likes / trending 48 (only 3 days old). Distilled from `meituan-longcat/LongCat-Video` (3.2K downloads / 596 likes on the base, already queued for `longcat` in the 2026-10-16 Tier-3). `longcat` is registered but has NO builder yet; the 1.6 avatar variant is audio-text-to-video + audio-driven continuation, which doesn't fit the existing `VIDEO_METHODS` signature — it would need either a new method id (`avatar_gen` with an audio input slot) OR a wrapper node that exposes it through the plain `video_gen` shape. Operator call. |
| **black-forest-labs/flux-3-image-klein-comfy** | 2026-10-14 (seen 10-16, now mature) | Weights for the already-registered `flux3klein` arch at `architectures.py:813` | ~11 GB fp16 | medium | 2 | **1.1M downloads / 3,295 likes** — up from 73K / 382 at the 2026-10-16 digest. Clear community consensus. `_reg("flux3klein", …)` is in place but `build_flux3klein_*` is not — see Follow-ups. Companion GGUF path at `unsloth/flux-3-image-klein-GGUF` (422.9K downloads, 55 likes) + FP8 at `unsloth/flux-3-image-klein-FP8` (332.5K / 7 likes) means the 12-GB-tier path is ready. |
| **black-forest-labs/flux-3-image-klein-pup** | 2026-10-14 | Prompt-upsampling LLM paired with Flux-3-Klein | ~5 GB (Qwen3.5-9B fp16) | low | 2 | 70.4K downloads / 81 likes. Qwen-3.5-9B specialised for prompt-rewriting to Flux-3-Klein's preferred shape. Would plug into `llm_delegate.py` the same way the 2026-10-16 digest's `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4` plugs in for `zit` — model-choice option in LM Studio, selected when the downstream builder targets `flux3klein`. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 | Camera-controllable render adapter on LTX-2.5 | ~2 GB (adapter) | low | 2 | 144 likes / 19.3K downloads. Second-highest-liked member of the LTX-2.5 IC-LoRA family. Unlocks a new builder `build_ltx_layout_to_render_video` with structured-camera-control input. Pairs with the existing LTX-2.5 Tier-3 download (base weights still pending on fleet). |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Restore** | 2026-09-27 | Archive-footage restoration + colorization on LTX-2.5 | ~2 GB (adapter) | low | 2 | 91 likes / 13.3K downloads. Base is `LTX-2.3` here (not 2.5) per the repo metadata — a minor compat note for the operator. Would land as `build_ltx_restore_video`. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR** | 2026-09-28 | SDR → HDR conversion on LTX-2.5 | ~2 GB (adapter) | low | 2 | 67 likes / 19.8K downloads. Second most-downloaded of the new batch. Narrow use case but mechanical to wire — reuses the same sampler config as the other LTX-2.5 IC-LoRAs. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate** | 2026-09-09 | Object removal / plate cleanup on LTX-2.5 | ~2 GB (adapter) | low | 2 | 53 likes / 12.1K downloads. VFX "object removal" workflow. `build_ltx_clean_plate_video`. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Day-To-Night** | 2026-09-08 | Relighting day→night on LTX-2.5 | ~2 GB (adapter) | low | 2 | 45 likes / 6.7K downloads. Creative relighting, pairs with the existing image-side `relight` method surface. |
| **Lightricks/LTX-2.5-22b-LoRA-Cinemagraph** | 2026-09-10 | Selective-motion cinemagraph builder (I2V-shape, not V2V) | ~2 GB (adapter) | low | 2 | 49 likes / 6.6K downloads. Only LTX-2.5 adapter in this batch that's I2V-shape (base task tag is `image-to-video`); the others are V2V. Would land under `build_ltx_cinemagraph_video`. |
| **sandpies/ComfyUI-H3-Video-Upsampler** | 2026-10-06 | Video-upscale LoRA on MiniMax-H3 | ~1 GB (adapter) | low | 2 | 14 likes / 0 downloads but trending 3 — fresh. If `build_minimax_h3_upscale_video` lands with the HyperFlow-H3-Flash plumbing above, this adapter plugs straight in. |

### Tier-2 non-model finding

- **Five arches are registered without builders.** The registry at
  HEAD has `_reg(…)` entries for `flux3klein` (line 813),
  `qwen_image` (911), `flux2dev` (768), `minimax_h3` (1336), and
  `longcat` (1371), but `workflows.py` has no matching
  `build_flux3klein_*` / `build_qwen_image_*` / `build_flux2dev_*` /
  `build_minimax_h3_*` / `build_longcat_*`. These are **not stubs** —
  they claim `registered=True` so `get_arch(name)` returns a real
  config, and the builders manifest therefore advertises them to
  Voodoomaster — but calling any derived method would fail at the
  `build_*` lookup. Wiring the missing builders is Tier-2 work (per-
  arch sampler + loader decisions, not mechanical), but the
  registered-but-unwired state itself is worth surfacing for the
  operator's next planning pass. The HyperFlow-H3-Flash and
  Flux-3-Klein entries above are the two with the strongest
  community signal to ship the builder for first.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-16 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: BennyDaBall/HyperFlow-H3-Flash-NVFP4-ComfyUI
    target_host: spark2
    reason: "HyperFlow-H3-Flash is the few-step distill of MiniMax-H3 (already registered as _reg('minimax_h3', ...) at architectures.py:1336). The NVFP4 ComfyUI variant matches the Spark2 NVFP4 convention the registry's extra={'clip_type': 'minimax', ...} already hints at. 75K+ community downloads on the matching INT8 variant signal strong adoption. Pairs with the Tier-2 ask to wire build_minimax_h3_*."
    command_hint: "huggingface-cli download BennyDaBall/HyperFlow-H3-Flash-NVFP4-ComfyUI --local-dir D:\\LLM\\ComfyUI\\models\\unet\\MiniMax-H3-HyperFlow-NVFP4"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI
    target_host: spark1
    reason: "The int8 variant as fallback for a 12-GB-tier host that can't run NVFP4. 75.5K downloads / 35 likes, published 2026-11-07 — the community's default MiniMax-H3 distribution path."
    command_hint: "huggingface-cli download BennyDaBall/HyperFlow-H3-Flash-INT8-ComfyUI --local-dir D:\\LLM\\ComfyUI\\models\\unet\\MiniMax-H3-HyperFlow-INT8"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Highest-liked of the new LTX-2.5 IC-LoRA batch (144 likes). Depends on the LTX-2.5 base weights (still-open Tier-3 from the 2026-10-16 digest; this adapter is useless without them)."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout-To-Render"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Restore
    target_host: spark1
    reason: "Archive-footage restoration + colorization LoRA on LTX-2.5. 91 likes / 13.3K downloads. Compat note: base_model lists 2.3, not 2.5."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Restore --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Restore"
    risk: low

  - action: download_and_evaluate_lora_pack_batch
    target_repo: "Lightricks/LTX-2.5-22b-IC-LoRA-{SDR-To-HDR,Clean-Plate,Day-To-Night,Cinemagraph}"
    target_host: spark1
    reason: "Three more LTX-2.5 LoRAs from the 2026-09 batch. Grouped as one action since they share base/deps and can be evaluated together. Combined storage ~8 GB. Each unlocks one builder."
    command_hint: "for repo in Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate Lightricks/LTX-2.5-22b-IC-LoRA-Day-To-Night Lightricks/LTX-2.5-22b-LoRA-Cinemagraph; do huggingface-cli download $repo --local-dir D:\\LLM\\ComfyUI\\models\\loras\\$(basename $repo); done"
    risk: low

  - action: download_and_evaluate_model
    target_repo: meituan-longcat/LongCat-Video-Avatar-1.6
    target_host: spark1
    reason: "Audio-driven avatar extension of LongCat-Video. Fresh (3 days old), only 48 likes but trending 48. Would depend on the base LongCat-Video weights (already queued from 2026-10-16). Novel audio-video modality — may warrant a new `avatar_gen` method id rather than overloading `video_gen`."
    command_hint: "huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.6 --local-dir D:\\LLM\\ComfyUI\\models\\longcat\\Avatar-1.6"
    risk: medium

  - action: run_audit_disk_vs_registry_from_lan
    target_repo: null
    target_host: spark1
    reason: "The new T1-c tool at tools/audit_disk_vs_registry.py reads architectures.py and walks ComfyUI/models/* to list: (a) what weights on disk don't correspond to a registered arch (retirement candidates), (b) which registered arches have no weights yet (download candidates), (c) dirs with multiple weight files (quant variants or orphans). First real run of this tool is the operator's first look at the retirable-weights question."
    command_hint: "python tools/audit_disk_vs_registry.py --models-dir D:\\LLM\\ComfyUI\\models --json _dev_docs/audit-$(Get-Date -Format yyyy-MM-dd).json"
    risk: low

  # ─── Carried over from 2026-10-16 (still open) ────────────────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein — community adoption now clear (1.1M downloads / 3,295 likes). The arch _reg('flux3klein', ...) is already in architectures.py:813; this download is what the registered entry was waiting on. Gated=auto on HF — needs huggingface-cli login on the fleet host once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: unsloth/flux-3-image-klein-GGUF
    target_host: spark2
    reason: "GGUF path for the 12-GB-tier host. 422.9K downloads / 55 likes. Pairs with the main flux3klein _reg() entry."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\flux-3-image-klein-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-pup
    target_host: theo
    reason: "Prompt-upsampling LLM paired with Flux-3-Klein. 5 GB Qwen3.5-9B. Lands in LM Studio on the theo host rather than ComfyUI/models/; plugs into llm_delegate.py as a model-choice option when the downstream builder targets flux3klein."
    command_hint: "huggingface-cli download black-forest-labs/flux-3-image-klein-pup --local-dir D:\\LLM\\LMStudio\\models\\flux-3-image-klein-pup"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Fast distilled companion to Qwen-Image-2.1. Prefer the GGUF path (unsloth/Qwen-Image-2.1-Turbo-GGUF, 294K downloads) for the 12-GB tier — base repo is diffusers-only. _reg('qwen_image', ...) is in place at architectures.py:911; this download is what the registered entry was waiting on."
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
    reason: "Alpha-matte / background removal adapter on top of LTX-2.5. Depends on LTX-2.5 base weights (still-open Tier-3 from the 2026-10-16 digest). ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. Also depends on the LTX-2.5 base. ~2 GB. Pairs with existing supir image upscaler (which does image-only) for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family. Deciding point: human-mesh output format (SMPL-X vs GLB) vs. what spellcaster downstream tools consume."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). The 2026-11-16 LTX-2.5 LoRA batch above all requires this base to be useful. Gated=auto; needs HF login the sandbox doesn't have."
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
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-d now gives the HF arch-query map 8 more arches to probe when the tool DOES run from the LAN, for a total of 35 matched arches."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **Five arches registered without builders** (`flux3klein`,
   `qwen_image`, `flux2dev`, `minimax_h3`, `longcat`). The expanded
   docstring in T1-b calls this out explicitly ("builder TBD") but
   the actual wiring is domain work — per-arch sampler, loader,
   method-list decisions that a mechanical fix can't make. The
   HyperFlow-H3-Flash community momentum (572K downloads in 12 days)
   and the Flux-3-Klein maturity (1.1M downloads) mean these two are
   the strongest candidates for the operator's next builder-wiring
   pass. The other three can wait until their weights land on the
   fleet (Qwen-Image Turbo GGUF is pending in Tier 3 above;
   LongCat-Video + flux2dev base weights still unqueued).

2. **MCP transport for `upgrade_research.py`.** Still the same gap
   the 2026-09-22 and 2026-10-16 digests flagged — the tool's HF and
   civitai backends use `urllib`, which the cloud proxy 403s.
   Teaching the `huggingface` backend to prefer an MCP transport when
   one is available would let *this* routine run the ranked backend
   from the cloud instead of the skeleton one. Doable but it
   broadens the tool's dependency surface. Keeping this Tier-3
   scope until a concrete need to drop MCP calls appears.

3. **`flux2klein` → `flux3klein` migration path.** The 2026-10-16
   digest left this as a forward-looking question; the arch is now
   registered (`architectures.py:813`) so the migration is one
   unwired builder away (see Follow-up #1). The question for the
   operator: keep both `_reg()` entries so existing `flux2klein`
   calibrations don't orphan, OR replace the 2 entry outright. Repo
   style has leaned keep-both historically; a cleanup pass can come
   after both are in use for a cycle.

4. **`comfyui-spellcaster/spellcaster_core/_arch_registry` custom
   arch note.** `tools/upgrade_research.py --dry-run` prints
   `[arch_registry] Loaded 1 custom architecture(s): my_custom_model`
   — not an error, just a sign that a user-registered custom arch is
   living alongside the canon. Worth a line in CLAUDE.md or the
   architectures.py docstring documenting that the one-arch custom
   registry is intentional and not a drift signal for future
   digests.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`;
local `tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`; `tests/mirror_drift.py`;
`tools/build_builders_manifest.py --check`._
