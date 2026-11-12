# Ecosystem digest — 2026-11-12

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-qv4wza`.

## Delivery notes

- **Previous digest status.** `_dev_docs/ecosystem_digest_2026-10-16.md`
  lives on `main`; this run starts from the clean `main` sha and
  harvests three of its named Tier-1 follow-ups.
- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`, exit `0`).
  No skeleton redraft needed.
- **Egress still proxy-walled** for direct HF/civitai CONNECT, so the
  live backends inside `tools/upgrade_research.py` return skeleton data
  from the cloud. Hugging-Face MCP (`hf_fs`, `hub_repo_search`,
  `hub_repo_details`) remains this routine's live path and was the
  source for the Tier-2 numbers below. ~5 MCP calls spent of the ~25
  soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered via PR.
- **Mirror drift / byte check.** `python tests/mirror_drift.py` →
  `OK: 32/32   DRIFT: 0   MISSING: 0`. Confirms the two
  `architectures.py` copies stay byte-identical after this run's
  edit — both were updated.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes
(`python3 -m pytest tests/` → **60 passed**, up from 57 — three new
tests for the newly-added audit tool).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner was accurate at the
2026-10-16 digest but today is 2026-11-12. Bumped to
`📣 Status — November 2026`. News/Focus/Next copy left as-is (all
still describes past-tense "landed" items that remain true).

### T1-b `architectures.py` docstring: enumeration + date

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
`SUPPORTED ARCHITECTURES (as of October 2026):` block listing only
**21 fully-registered arches**. AST parse of the file returns
**29 registered + 6 stubs = 35** today. The docstring was missing
eight arches that have shipped since the 2026-10-16 digest's
expansion:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
- Video: `minimax_h3`, `skyreels`, `longcat`
- Other: `aurasr`

Docstring brought up to date (date + list). Registry itself remains
source-of-truth; this is docstring-only, no behavior change.
Mirror-drift check confirms both copies stay byte-identical after the
edit.

### T1-c `tools/audit_disk_vs_registry.py`: draft the named Tier-1 tool

The 2026-10-16 digest explicitly filed this as a Tier-1 candidate for
a future run:

> `tools/audit_disk_vs_registry.py` is still a Tier-3 TODO. Writing
> it is a ~100-line Tier-1 candidate for a future digest: read
> `architectures.py` + walk `ComfyUI/models/*`, print paths matching
> `registered=True` arches that have more than one weights candidate
> on disk.

Shipped. Key design choices:

- Reads the arch registry via **AST parse** of
  `comfyui-spellcaster/spellcaster_core/architectures.py` (never
  `exec`s it — the file imports fleet-side wrappers unavailable in
  the sandbox and in CI).
- Walks a user-supplied `--models-root` and classifies every
  `.safetensors/.ckpt/.pt/.pth/.gguf/.bin` file via a conservative
  substring heuristic (`ARCH_SUBSTRINGS` table in the module). All
  29 registered + 6 stub arches are covered.
- Reports four sections: duplicate candidates per arch, registered
  arches with no weights, stub arches with weights ("needs operator
  attention before deletion"), and unclassified files.
- Includes `--self-check` that builds a temp fixture tree and asserts
  the duplicate-detection and stub-flagging paths work — testable
  from the cloud sandbox where the fleet filesystem is unreachable.
- **Never deletes** — report-only, by design.
- Backing tests: `tests/test_audit_disk_vs_registry.py` (3 tests:
  self-check success, missing-root error, registry-parse arch
  membership). All pass.

Operator usage once on the fleet:

```
python tools/audit_disk_vs_registry.py --models-root "D:\LLM\ComfyUI\models"
```

This closes the Tier-3 queue entry `audit_retirable_weights` (the
`command_hint` there named a tool that did not yet exist — now it
does). The fleet-run itself still lives in Tier 3 because only the
operator can see `D:\LLM`.

**Verification of T1-a through T1-c**

- `python3 -m pytest tests/ -q` → **60 passed in 7.04s**.
- `python3 tools/upgrade_research.py --dry-run` → exit `0`,
  `4 proposals from 5 backends`.
- `python3 tests/mirror_drift.py` → `OK: 32/32   DRIFT: 0`.
- `python3 tools/audit_disk_vs_registry.py --self-check` → exit `0`,
  `self-check OK`.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). All numbers are the HF
report at the time of this digest (2026-11-12). Rows carrying over
from 2026-10-16 are prefixed `[CARRY]`; genuinely new rows this run
are prefixed `[NEW]`.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **[NEW] MiniMaxAI/MiniMax-H3-Image** + **Comfy-Org/MiniMax-H3-Image** | 2026-11-12 | NEW arch — image sibling of the `minimax_h3` video arch already at `architectures.py:1336` | ~10 GB fp16 est. | medium | 2 | 828 + 282 likes / 307K + 836K downloads in the first week. Comfy-Org variant is `diffusion-single-file` → drops into `ComfyUI/models/checkpoints/`. Spellcaster already has `minimax_h3` registered for VIDEO workflows; question for the operator is whether to **extend** that arch's `supported_methods` to include image generation, or **register a second** arch (e.g. `minimax_h3_image`) with its own method set. Recommend second-arch route — the loader + sampler shape is different (text-to-image ≠ image-text-to-video). |
| **[NEW] VideoRebirthAI/hyperflow-h3-flash** | 2026-11-11 | Fast companion to `minimax_h3` arch — few-step i2v / t2v on MiniMax-H3 base | ~8 GB int8 est. | low | 2 | 230 likes / 326K downloads. Int8-quantized, few-step, ComfyUI tags — this is the few-step distill of the same MiniMax-H3 base used by the current `minimax_h3` registry entry. If `minimax_h3` ships with its default 30-step settings, this fork would land as the few-step default for the 8-GB tier via the same `arch.turbo` config pattern used by `sdxl_turbo` / `zit`. |
| **[CARRY] black-forest-labs/flux-3-image-klein-comfy** | 2026-10-14 | Already `_reg("flux3klein", …)` at `architectures.py:813`. Shipped since last digest — this is now a **weights-on-fleet** question, not a registry one | ~11 GB fp16 | medium | 2 | 3,005 likes / 1.3M downloads — approximately double the numbers at the prior digest, confirms the arch bet. Registry entry is live; the Tier-3 `download_and_evaluate_model` row below is the remaining open action. `unsloth/flux-3-image-klein-GGUF` (349K downloads, 52 likes) is the GGUF path for the lower-VRAM tier. |
| **[NEW] Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 | Camera-control / layout-to-render adapter on LTX-2.5 | ~2 GB (adapter) | low | 2 | 139 likes / 19.2K downloads. Pairs with the Alpha-Gen / Spatial-Upscaler / Refine / Ingredients adapters filed in 2026-10-16. Camera-control is a natural fit for a `build_ltx_camera_motion_video` builder. Same license + distribution contract as the base. |
| **[NEW] Lightricks/LTX-2.5-22b-IC-LoRA-Restore** | 2026-09-27 | Video restoration / colorization adapter on LTX-2.5 (also tagged for LTX-2.3) | ~2 GB (adapter) | low | 2 | 86 likes / 13.5K downloads. Natural fit for a `build_ltx_restore_video` builder that complements the existing `seedvr` + `supir` restorers (which are frame-level). |
| **[NEW] Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR** | 2026-09-28 | SDR→HDR video adapter on LTX-2.5 | ~2 GB (adapter) | low | 2 | 64 likes / 21.3K downloads. Tone-mapping use case. Operator call: is HDR output useful downstream for Resolve? |
| **[CARRY] Lightricks/LTX-2.5** | 2026-10-11 | Direct upgrade path for `_reg("ltx", …)` | ~22 GB fp16 est. | medium | 2 | Now 11,589 likes / 2.78M downloads — up from 8,035 / 1.9M at prior digest. Dominant open-source i2v. Gated=auto, needs HF login on the fleet host. Carry-over from 2026-09-22 Tier-3 queue. |
| **[CARRY] Qwen/Qwen-Image-2.1-Turbo** + **unsloth/Qwen-Image-2.1-Turbo-GGUF** | 2026-10-10 | Fast companion to `_reg("qwen_image", …)` | ~10 GB fp8 est. | medium | 2 | **Turbo lane has won.** unsloth GGUF now at **1.4M downloads** (vs. 294K last digest — nearly 5x growth in 27 days). The paired integration call from the prior digest still stands: wire this as few-step default for the 12 GB tier via `arch.turbo` config. |
| **[CARRY] facebook/sam3** + **facebook/sam3.1** | 2025-11-07 / 2026-03-26 | Weights-only check for `build_sam3_segment` (`workflows.py:7014`) | ~2 GB | low | 2 | sam3 at 2.1M / 6,431 likes; sam3.1 at 167.9K / 1,486 likes. Still worth the audit filed in prior digest's Tier-3 queue. |
| **[CARRY] facebook/sam-3d-body-dinov3** | 2025-11-17 | NEW builder family (3D human-mesh) | ~3 GB | medium | 2 | Now 14.5K / 1,069 likes — up from 8.4K / 541 at prior digest. Trend is up. Decision still open: new `sam3d` arch vs. extend `hunyuan_3d`. |
| **[NEW] speridlabs/idol** | 2026-10-29 | Alternate image-to-3d — **Gaussian Splatting output** (not traditional mesh) | ~5 GB est. | medium | 2 | 2,200 likes / 29.9K downloads in two weeks — fastest-growing image-to-3d on the Hub trending list. Apache-2.0 license (better than Hunyuan3D's). NOT a drop-in for `_reg("hunyuan_3d", …)` because the output is 3DGS, not GLB/OBJ; would land as a separate `build_idol_splat` builder if the fleet's downstream (Resolve, GIMP) has a Gaussian Splatting viewer path. |

### Tier-2 non-model findings

- **MiniMax-H3 lane decision.** Two separate repos from the same lab
  land within 24 hours: an image model (`MiniMax-H3-Image`) and a
  few-step video flash (`hyperflow-h3-flash` via VideoRebirthAI).
  Spellcaster already has `minimax_h3` registered for video. Operator
  decision: (a) extend `minimax_h3` to image generation too, (b)
  register a second `minimax_h3_image` arch, or (c) treat the MiniMax
  stack as one logical arch family with two registry entries like the
  Flux family (`flux1dev` / `flux2klein` / `flux2dev` / `flux3klein`).
  Option (c) matches the house style.

- **LTX-2.5 adapter wave is still growing.** Prior digest filed four
  LTX-2.5 IC-LoRA adapters; this run surfaces three more
  (Layout-To-Render, Restore, SDR-To-HDR) that are from the same
  Sept-Oct 2026 drop but weren't caught by the prior run's searches.
  Total known LTX-2.5 adapters: **7**. If the fleet downloads the
  LTX-2.5 base, all seven are low-risk ~2 GB additions unlocking one
  builder each. Bulk-download candidate.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over still-open 2026-10-16 entries + this run's new ones.
Removes `audit_retirable_weights` from the carry set because its
blocker (tool did not exist) is now resolved by T1-c.

```yaml
local_action_queue:
  # ─── New in 2026-11-12 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/MiniMax-H3-Image
    target_host: spark1
    reason: "New image sibling of the already-registered minimax_h3 video arch. Comfy-Org repack is diffusion-single-file — drops into ComfyUI/models/checkpoints/ with no extra plumbing. 835K downloads in the first week confirms community traction."
    command_hint: "huggingface-cli download Comfy-Org/MiniMax-H3-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MiniMax-H3-Image"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: VideoRebirthAI/hyperflow-h3-flash
    target_host: spark2
    reason: "Few-step int8 fork of MiniMax-H3 for the lower-VRAM tier. ComfyUI-tagged, so should drop into the standard models/ layout. Natural turbo config for the existing minimax_h3 video arch."
    command_hint: "huggingface-cli download VideoRebirthAI/hyperflow-h3-flash --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\hyperflow-h3-flash"
    risk: low

  - action: run_disk_vs_registry_audit
    target_repo: null
    target_host: spark1
    reason: "The tool scaffold filed in prior digest's Tier-1 follow-up list now exists (this run's T1-c). Run it against the fleet's models/ dir and paste the output into the next digest so retirable-weights decisions become data-backed. No downloads, no deletions, read-only."
    command_hint: "python tools/audit_disk_vs_registry.py --models-root \"D:\\LLM\\ComfyUI\\models\" > _audit/disk_vs_registry_2026-11-12.md"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Camera-control / layout-to-render adapter on LTX-2.5. Requires LTX-2.5 base (prior digest's Tier-3 download). ~2 GB. Unlocks a build_ltx_camera_motion_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Restore
    target_host: spark1
    reason: "Video restoration / colorization adapter on LTX-2.5 (also tagged for LTX-2.3 — graceful fallback). ~2 GB. Complements frame-level supir + seedvr."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Restore --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Restore"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR
    target_host: spark1
    reason: "SDR→HDR tone-mapping adapter. Only download if downstream HDR consumption is wanted (Resolve supports HDR timelines; GIMP does not)."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-SDR-HDR"
    risk: low

  - action: download_and_evaluate_model
    target_repo: speridlabs/idol
    target_host: unknown
    reason: "Image-to-3D with Gaussian Splatting output (3DGS, NOT a GLB/OBJ mesh). Fastest-growing image-to-3d on trending (2,200 likes in 2 weeks, apache-2.0 license). Pre-download gate: does the downstream pipeline (Resolve / GIMP / web preview) have a 3DGS viewer? If not, skip — a 3DGS blob is not interchangeable with the Hunyuan3D mesh pipeline."
    command_hint: "# Gate on operator decision re: 3DGS viewer path first.\nhuggingface-cli download speridlabs/idol --local-dir D:\\LLM\\ComfyUI\\models\\idol"
    risk: medium

  # ─── Carried over from 2026-10-16 (still open) ────────────────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Registry entry now live (_reg('flux3klein', ...)). Weights are the remaining open step. Gated=auto on HF — needs huggingface-cli login on the fleet host once. HF trend confirms arch bet: 3,005 likes / 1.3M downloads, ~2× the prior digest's numbers."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: unsloth/Qwen-Image-2.1-Turbo-GGUF
    target_host: spark2
    reason: "Turbo lane has clearly won: 1.4M downloads now, up from 294K at prior digest. GGUF path for the 12-GB tier. Pair with Qwen-Image-2.1 base only if the full-quality lane is also wanted."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading. Carry-over from prior digest; still useful."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Weights-only drop-in for build_sam3_segment, IF the SAM3Segment node loader accepts 3.1-shape weights. Audit above runs first."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on LTX-2.5. Depends on LTX-2.5 base. ~2 GB, unlocks build_ltx_remove_bg_video."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. Depends on LTX-2.5 base. ~2 GB. Pairs with supir (image-only) for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D body / human-mesh. Trending up (14.5K downloads, 1,069 likes; +73% likes since prior digest). Different task than Hunyuan3D object mesh — evaluate as new builder family."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). 11,589 likes / 2.78M downloads — still dominant. Gated=auto, HF login needed."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for existing _reg('hunyuan_3d', ...). Carry-over from 2026-09-22 Tier-3."
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
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT, so tools/upgrade_research.py's live backends fall back to skeleton mode. Running it from the LAN unlocks its downloads-weighted ranking for the arches the registry now knows about."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed this run but not fixed — either scope-larger-than-safe
or needing an operator's read first.

1. **MiniMax-H3 image arch decision.** The `minimax_h3` registry
   entry is video-only today; the lab just shipped an image sibling
   with real volume. A future digest's Tier-1 can add a second
   `minimax_h3_image` (or similar) `_reg()` entry non-destructively,
   following the Flux family pattern. Not shipped here because
   choosing the key name and sampler shape is an architectural call.

2. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap the prior two digests flagged — the tool's HF + civitai
   backends use `urllib`, which the cloud proxy 403s. Teaching the
   `huggingface` backend to prefer an MCP transport when one is
   available would let **this** routine run the ranked backend from
   the cloud. Not shipped: broadens the tool's dep surface.

3. **LTX-2.5 adapter bundle flag.** Seven LTX-2.5 IC-LoRA adapters
   are now known to the digest. If the fleet downloads the base, a
   future Tier-1 could add a small helper
   (`tools/pull_ltx_adapters.py`) that `huggingface-cli downloads`
   the set in one go, or a yaml bundle for Hermes to consume. Named
   here so a future run can pick it up.

4. **`backend_civitai` sanity check.** `tools/upgrade_research.py`
   returned one Civitai candidate in the skeleton run today; prior
   digests have hinted the `backend_civitai` path is skeleton-only.
   A ~30-line audit on the civitai backend (does it return skeleton
   data or real?) is a Tier-1 candidate for a future digest.

5. **Prior digest follow-ups still open.** Items 1–3 from 2026-10-16
   remain open except for #1 (audit tool, closed this run). Items
   #4 and #5 from that digest (backlog decision and `fetch_metadata.py`
   TLS) are also closed.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
AST scans of `architectures.py`; `python3 -m pytest tests/` (60/60);
`tests/mirror_drift.py` (32/32)._
