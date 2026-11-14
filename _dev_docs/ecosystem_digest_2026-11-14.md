# Ecosystem digest — 2026-11-14

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-p0lg50`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest landed on `main`
  (part of the 2026-10-16 "chore: ecosystem digest + Tier-1 fixes"
  series). This run starts from a clean slate on the same branch.
- **Routine health.** `tools/upgrade_research.py` is still present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`). No
  skeleton draft needed this run.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`, so the
  live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return skeleton candidates from here;
  Hugging-Face MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`) is
  the live path from the cloud this run uses. ~9 MCP calls spent of
  the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — scanned current tree with the canonical pattern
  list from `.githooks/leak-patterns` under the same `:!` self-exclusions
  the CI workflow applies; **clean** (`git grep` exit 1 = no match =
  pass case for this check).

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
57/57, `mirror_drift.py` → `32/32 DRIFT: 0`).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner. Today is 2026-11-14.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left
as-is (still accurate — installer self-healing, LM Studio prompt
enhancement, mirror sync, etc.).

### T1-b `architectures.py` docstring: enumeration + date drift

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
module-level `SUPPORTED ARCHITECTURES (as of October 2026):` block
listing 21 fully-registered + 6 stub arches. The registry on disk now
contains **35 `_reg()` entries** (29 fully-registered in-file + 6
stubs), plus 1 runtime-injected custom arch from the `arch_registry`
plugin hook. Eight new `registered=True` entries since the last
digest were not in the docstring:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
- Video: `minimax_h3`, `skyreels`, `longcat`
- Other: `aurasr`

Bumped header to `(as of November 2026):`, expanded the three
sections to cover all 29 fully-registered in-file arches, and added
a one-line note pointing at the `arch_registry` plugin hook so
readers know the on-disk count is a lower bound, not the whole set.
Mirror-drift stays byte-identical: identical edit applied to both
copies, `python tests/mirror_drift.py` → `OK: 32/32  DRIFT: 0`.

### T1-c `tools/upgrade_research.py`: HF arch-query map missed 8 archs

`_HF_ARCH_QUERIES` had entries for 27 arches but the registry now
holds 29 fully-registered in-file (plus 6 stubs). That means
`_hf_query_for_method(build_<arch>_*)` returned `None` for 8 of the
new ones, so a live `huggingface` or `civitai` backend run would
**silently skip** candidate research for them.

Added mappings for: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`,
`minimax_h3`, `skyreels`, `longcat`, `aurasr`. Also broadened
existing `wan` entry to pick up the 2.5 generation and `ltx` to pick
up the 2.5 generation (both already landed on HF with real traffic).

Also bumped the stale method-count claim in the module docstring
from "75 as of 2026-10-16" → "78 as of 2026-11-14"
(`python tools/build_builders_manifest.py` confirms 78).

Verification: `python tools/upgrade_research.py --dry-run` still
exits `0`, same `4 proposals from 5 backends` output. The
`2026-W46.{md,json}` artefacts emitted by that dry run are committed
too so a future digest has a reference point.

### T1-d `tools/audit_disk_vs_registry.py`: tool filed as TODO in prior two digests is now written

Both the 2026-09-22 and 2026-10-16 digests filed this ~100-line tool
as a Tier-3 (fleet-dependent) item followed by a note "future Tier-1
candidate to actually write." Written here.

What it does:

- Loads `spellcaster_core.architectures` and extracts, per
  `registered=True` arch, the explicit weight filenames declared in
  `extra` (`clip_name`, `clip_name1`, `clip_name2`, `vae_name`,
  `unet_name`) plus `lora_prefixes`.
- Walks a ComfyUI models directory passed via `--models-dir` (or
  the `SPELLCASTER_COMFYUI_MODELS` env var, default
  `D:/LLM/ComfyUI/models`) and classifies every `.safetensors` /
  `.gguf` / `.pt` / `.ckpt` / `.bin` file.
- Prints three sections:
    * **UNKNOWN WEIGHTS** — paths with no claim; retirement candidates
    * **DUPLICATE SLOTS** — >1 file on disk claims the same declared
      name (e.g. two different `ae.safetensors` across subdirs)
    * **MISSING DECLARED** — a declared name the registry asks for
      that isn't on disk at the expected path
- Also supports `--list-declared` (no disk walk, cloud-safe) and
  `--json` (for a future Hermes consumer).
- Read-only. No file is ever moved, renamed, or removed. Exit 0
  always; this is an audit, not a gate.

The `local_action_queue` entries from prior digests that referenced
`audit_disk_vs_registry.py` can now be updated to use it with
real arguments — e.g. the "audit retirable weights" entry below
carries a working `command_hint:`.

Verification: ran on a synthetic fixture under the session
scratchpad — unknown/duplicate/missing partitions matched expected
counts; `--list-declared` prints 30 registered archs and ~20
declared weight filenames; running against a non-existent
`--models-dir` exits 0 with a helpful hint. File is 190 lines, free
of external dependencies beyond stdlib + `spellcaster_core`.

### Verification of T1-a through T1-d

- `pytest tests/` — `57 passed in 7.53s` (prior digest was at 52;
  five new tests have landed on `main` since).
- `python tools/upgrade_research.py --dry-run` — exit `0`, same shape
  as before the arch-query map expansion; artefacts in
  `_dev_docs/upgrade_research/2026-W46.{md,json}`.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  no manifest regen required (count unchanged since last run).
- `python tools/audit_disk_vs_registry.py --list-declared` — exits
  `0` with the expected JSON shape.
- CI-equivalent leak-check (`git grep -nIEi` over the canonical
  patterns, same three `:!` self-excludes the workflow uses) — exit
  `1` = no match = pass.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search` across several model families). Numbers are the HF
report as of this digest (2026-11-14).

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **black-forest-labs/flux-3-image-klein-comfy** | 2026-10-14 | Weights for existing `_reg("flux3klein", …)` at `architectures.py:813` | ~11 GB fp16 (5.5B) | low→medium | 2 | **1.3M downloads / 3,156 likes** — up from 374+382 likes / 95K dl a month ago. The arch registration landed since the 2026-10-16 digest, so this is now a *weights-only* fleet download, not an integration task. `diffusion-single-file` → drops into `ComfyUI/models/checkpoints/`. Gated=auto — needs `huggingface-cli login` on fleet host once. Companion quantised variants also hot: `unsloth/flux-3-image-klein-GGUF` (392K dl / 53 likes), `unsloth/flux-3-image-klein-FP8` (320K dl / 7 likes), `ml-resources/flux-3-image-klein-comfy` (524K dl / 13 likes — unofficial mirror; prefer the BFL repo). |
| **black-forest-labs/flux-3-image-klein-pup** | 2026-10-14 | Prompt-upsampling LLM paired with Flux-3-Klein — Qwen3.5-9B finetune for prompt rewriting | ~5 GB fp16 (9B, likely GGUF for LM Studio) | low | 2 | 73K downloads / 81 likes. Apache-2.0. Would wire into `llm_delegate.py` as a per-arch prompt enhancer selected when the pending workflow's `arch == "flux3klein"`. Similar in spirit to `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4` (prior digest's Tier-2 for `zit`). |
| **facebook/sam3.1** | 2026-03-26 | Version-swap for the `SAM3Segment` node already consumed by `build_sam3_segment` (`workflows.py:7014`) | ~2 GB (ViT-L backbone) | low | 2 | **156.4K downloads / 1,508 likes** — up from 90K / 1,091 last digest, so adoption has grown. Node-vs-weights question unchanged: does the installed `SAM3Segment` node resolve 3.1-shape weights at the Comfy model-dir path, or need a custom-node pack bump? One-line audit on the fleet host before download. |
| **facebook/sam-3d-body-dinov3** | 2025-11-17 | NEW capability — 3D human-mesh recovery from a single image | ~3 GB (DINOv3 backbone) | medium | 2 | **1,167 likes / 15.7K downloads** — up from 541/8.4K last digest. Would land as NEW builder family alongside `build_hunyuan_3d` (which does image-to-object-mesh). Different task (human mesh + SMPL-X pose) vs. Hunyuan3D's object mesh. Decision point: new `sam3d_body` arch, or extend the `hunyuan_3d` builder set? |
| **facebook/sam-3d-objects** | 2025-10-06 | Alternate image-to-3d comparator for `_reg("hunyuan_3d", …)` | ~3 GB | medium | 2 | 664 likes / 8.9K downloads. Direct comparator for Hunyuan3D-2.x — different mesh style, different texture pipeline. Worth benchmarking against Hunyuan3D 2.1 before committing fleet storage to only one. Steady adoption. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR** | 2026-09-28 | NEW adapter — SDR→HDR tone-mapping for `ltx` | ~2 GB (adapter on LTX-2.5) | low | 2 | 20.1K downloads / 65 likes. Lightricks-published, same license + distribution contract as the base 2.5 model. Would land as a `build_ltx_sdr_to_hdr_video` builder. Depends on `Lightricks/LTX-2.5` base weights (prior digest's Tier-3 download). |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 | NEW adapter — layout/storyboard → rendered video (camera-control shaping) | ~2 GB (adapter) | low | 2 | **19.1K downloads / 140 likes** — strong early traction. Would wire into a new `build_ltx_layout_to_render_video` builder; layout-to-video is a capability the current `ltx` registration doesn't expose. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Restore** | 2026-09-27 | NEW adapter — video restoration + colorization for archival footage | ~2 GB (adapter) | low | 2 | 13K downloads / 88 likes. Base model is tagged for both `ltx-2.3` and `ltx-2.5`, so compatible with either base-weight download. Pairs with `supir` (image-only) as a video-side restoration option. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate** | 2026-09-09 | NEW adapter — object removal / clean-plate generation for VFX | ~2 GB (adapter) | low | 2 | 12K downloads / 50 likes. `diffusion-single-file`, drops straight into `loras/`. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen** | 2026-09-28 | Alpha-matte / background removal — carried over from last digest | ~2 GB (adapter) | low | 2 | 18.6K downloads / 267 likes (up from 11K / 185). Worth bundling with the five other Lightricks IC-LoRAs as one fleet-side pack. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler** | 2026-08-11 | Video spatial upscaler — carried over | ~2 GB (adapter) | low | 2 | 13.4K downloads / 158 likes (up from 10.8K / 125). Same download-pack logic. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details** | 2026-09-27 | Video detail refinement — carried over | ~2 GB (adapter) | low | 2 | 18.8K downloads / 92 likes. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients** | 2026-09-10 | Character consistency — carried over | ~2 GB (adapter) | low | 2 | 16.5K downloads / 121 likes. |
| **meituan-longcat/LongCat-Video-Avatar-1.5** | 2026-05-21 (updated) | Audio-driven avatar video — different task than `_reg("longcat", …)`'s current text/image-to-video | ~12 GB (fp16) | medium | 2 | **4K downloads / 907 likes**; the ComfyUI GGUF repack (`vantagewithai/LongCat-Video-Avatar-1.5-GGUF-ComfyUI`) adds another 19.2K / 27 likes. Audio-driven (`audio-text-to-video`, `audio-image-text-to-video`) is a capability no current arch covers. Would land as a sibling `_reg("longcat_avatar", …)` or an extra method on `longcat` — operator call on whether avatar-video deserves a separate arch key. |

### Tier-2 non-model finding — paired decision

- **LTX-2.5 "all-in-one" IC-LoRA pack vs. individual adapters.**
  There are now **nine** published Lightricks IC-LoRAs for LTX-2.5
  (Alpha-Gen, Pixel-Spatial-Upscaler, Refine-Details, Ingredients
  from prior digest, plus SDR-To-HDR, Layout-To-Render, Restore,
  Clean-Plate added here). Operator decision: do all nine land as
  one `D:\LLM\ComfyUI\models\loras\LTX-2.5-IC-*` download sweep, or
  gate by use-case (download Alpha-Gen + Restore + Clean-Plate first
  for VFX, defer the camera-control ones until there's a project
  that needs them)? Mechanical answer is "download them all, they're
  ~2 GB each"; aesthetic answer depends on spark storage budget.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-14 ────────────────────────────────────────────

  - action: download_model_for_registered_arch
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "flux3klein arch is already _reg'd (architectures.py:813) — this is now a weights-only download, not an integration task. Gated=auto on HF — needs `huggingface-cli login` on the fleet host once. The comfy-packaged diffusion-single-file drops straight into ComfyUI/models/checkpoints/. 1.3M downloads / 3156 likes — clear community adoption."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein-comfy"
    risk: low

  - action: download_prompt_enhancer_for_flux3klein
    target_repo: black-forest-labs/flux-3-image-klein-pup
    target_host: theo
    reason: "Qwen3.5-9B prompt-upsampling finetune paired with Flux-3-Klein. Would wire into llm_delegate.py as a per-arch enhancer when workflow.arch == 'flux3klein'. Apache-2.0 so no license plumbing needed. Prefer a GGUF quant on LM Studio if available."
    command_hint: "huggingface-cli download black-forest-labs/flux-3-image-klein-pup --local-dir D:\\LLM\\LMStudio\\models\\flux-3-image-klein-pup"
    risk: low

  - action: download_lightricks_ltx25_ic_lora_pack
    target_repo: multiple — Lightricks/LTX-2.5-22b-IC-LoRA-{Alpha-Gen,Pixel-Spatial-Upscaler,Refine-Details,Ingredients,SDR-To-HDR,Layout-To-Render,Restore,Clean-Plate}
    target_host: spark1
    reason: "Nine Lightricks IC-LoRAs now published for LTX-2.5. All ~2 GB, adapter-only (no new base weights beyond the LTX-2.5 base already queued). Depends on Lightricks/LTX-2.5 base weights (Tier-3 carried over below). Would unlock: build_ltx_remove_bg_video, build_ltx_upscale_video, build_ltx_refine_video, build_ltx_consistent_character_video, build_ltx_sdr_to_hdr_video, build_ltx_layout_to_render_video, build_ltx_restore_video, build_ltx_clean_plate_video."
    command_hint: "for repo in Alpha-Gen Pixel-Spatial-Upscaler Refine-Details Ingredients SDR-To-HDR Layout-To-Render Restore Clean-Plate ; do huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-$repo --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-$repo ; done"
    risk: low

  - action: evaluate_longcat_avatar_as_new_arch
    target_repo: vantagewithai/LongCat-Video-Avatar-1.5-GGUF-ComfyUI
    target_host: spark2
    reason: "Audio-driven avatar video is a capability no current arch covers. meituan-longcat/LongCat-Video-Avatar-1.5 has 907 likes; the ComfyUI GGUF repack from vantagewithai has 19K downloads. Download + run against a short reference to decide: register as _reg('longcat_avatar', ...) or extend the existing longcat registration with a method bit?"
    command_hint: "huggingface-cli download vantagewithai/LongCat-Video-Avatar-1.5-GGUF-ComfyUI --include '*Q5_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\LongCat-Video-Avatar-1.5-GGUF"
    risk: medium

  - action: run_audit_disk_vs_registry
    target_repo: null
    target_host: any_spark
    reason: "The tool shipped in this PR (tools/audit_disk_vs_registry.py). First real run on a fleet host will surface any orphaned weights from the series of Flux-2 → Flux-3 and Qwen-Image / Krea-2 / MiniMax-H3 registrations that have landed in architectures.py over the last two months. Output drives the retirement decisions in the audit_retirable_weights entry below."
    command_hint: "python tools/audit_disk_vs_registry.py --models-dir D:/LLM/ComfyUI/models --json > D:/Laborantin/audits/disk_vs_registry_2026-11-14.json"
    risk: low

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet, just a path check."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Weights-only drop-in for the already-wired build_sam3_segment, IF the SAM3Segment ComfyUI node loader accepts 3.1-shape weights at the same path. Audit above runs first. Now at 156K dl / 1508 likes, up from 90K / 1091 last digest."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family. Deciding point: human-mesh output format (SMPL-X vs GLB) vs. what spellcaster downstream tools consume. Now at 1167 likes / 15.7K dl, strong growth signal."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Base LTX-2.5 weights — unblocks the nine IC-LoRAs listed above. HF now reports 2.78M downloads / 11.9K likes. Gated=auto; needs HF login the sandbox doesn't have."
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
    reason: "Enables build_controlnet_gen on the zit arch (currently an empty cn list). Still open from 2026-09-22."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c gives the HF arch-query map 8 extra arches to probe when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: any_spark
    reason: "The audit_disk_vs_registry.py tool now exists (T1-d this digest). If Flux-3-Klein replaces Flux-2-Klein on disk, or LTX-2.5 replaces LTXV-2.3, the older weights should be flagged in the UNKNOWN WEIGHTS and DUPLICATE SLOTS sections of the tool's output — the operator then decides retention by hand."
    command_hint: "python tools/audit_disk_vs_registry.py --models-dir D:/LLM/ComfyUI/models"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **Transport fallback for `tools/upgrade_research.py`.** Same gap
   the 2026-09-22 / 2026-10-16 digests already flagged — the tool's
   HF and civitai backends use `urllib`, which the cloud proxy 403s.
   Teaching the `huggingface` backend to prefer an MCP transport
   when one is available would let *this* routine run the ranked
   backend from the cloud instead of the skeleton one. Doable but
   broadens the tool's dependency surface (would need an MCP client
   in-process or a sidecar). Still not shipped here; could be a
   Tier-1 "add a `backend_hf_mcp` module that shells out to the HF
   MCP when present" drop for a future digest.

2. **`flux2klein` → `flux3klein` migration path.** The `flux3klein`
   `_reg()` entry is already in `architectures.py` (landed 2026-11-ish
   before this digest's baseline). The open question — whether to
   retire the `flux2klein` arch outright or keep it non-destructively
   under its own key for backwards compat — is unchanged, and now
   gets its mechanical answer from `audit_disk_vs_registry.py` once
   it runs on a fleet host. Default of this project's style has been
   to keep older arches registered so existing calibrations don't
   orphan; that's still the recommendation.

3. **LongCat Avatar: new arch key or extend existing?** Flagged
   in the Tier-2 table above. Defers to the operator because
   `audio-driven-video-continuation` is a capability class
   spellcaster doesn't currently have anywhere, and the decision
   affects both `architectures.py` and the `supported_methods` /
   `WAN_EXTRA_METHODS`-style helper tuples. Not a Tier-1 candidate
   until the fleet has evaluated the model.

4. **Prompt-enhancer registry.** With Flux-3-Klein-pup added to the
   per-arch enhancer set (alongside `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4`
   for `zit` from the prior digest), `llm_delegate.py` is accumulating
   per-arch enhancer rules. A `arch → preferred_enhancer_model` map
   — paralleling `_HF_ARCH_QUERIES` — would make this registration
   mechanical rather than scattered `if arch == "zit"` checks. Small
   Tier-1 candidate for a future digest.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
`tools/audit_disk_vs_registry.py --list-declared`;
AST scans of `architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/` (57 passed); `python tests/mirror_drift.py` (32/32)._
