# Ecosystem digest — 2026-11-24

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/ecosystem-digest-2026-11-24`.

## Delivery notes

- **Routine cadence drift.** The previous digest is dated 2026-10-16 —
  39 days ago, not 48 hours. Either the scheduler paused or earlier
  runs died before writing their digest; this run can't tell which
  from inside the sandbox. Not a Tier-1 fixable in-repo; flagged to
  the operator at the bottom of the digest.
- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` executes cleanly — `4 proposals from 5 backends`, exit
  0, new ISO-week artefact at `_dev_docs/upgrade_research/2026-W48.{md,json}`.
  No skeleton draft needed.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy
  still 403s direct CONNECT to `huggingface.co` / `civitai.com`, so
  `tools/upgrade_research.py`'s live `backend_huggingface` /
  `backend_civitai` paths still return skeleton rows from here. The
  Hugging-Face MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`)
  remains the live path from the cloud. ~9 MCP calls spent of the
  ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
57/57).

### T1-a `README.md`: front-page status + method count are stale

Hero banner carried `📣 Status — October 2026` and `75 AI tools, one
menu.`. Today is 2026-11-24 and `python tools/build_builders_manifest.py`
reports **78 methods**. Bumped the status month to November 2026 and
the subhead to `78 AI tools`. News/Focus/Next copy left as-is (all
still describes past-tense "landed" items that remain true today —
installer self-healing, LM Studio prompt enhancement, mirror sync,
etc.).

### T1-b `architectures.py` docstring: enumeration + date + stub-set

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
module-level `SUPPORTED ARCHITECTURES (as of October 2026):` header.
Between then and now the registry has grown — the `_reg()` scan on
disk is:

- **28 fully-registered** (the 24 listed by the previous digest,
  plus `flux2dev`, `flux3klein`, `krea2`, `qwen_image`, `minimax_h3`,
  `skyreels`, `longcat`, `aurasr`).
- **7 stubs** (`registered=False`): `flux_kontext` (**moved from
  fully-registered → stub since the 2026-10-16 digest**), `sd3`,
  `sd3_turbo`, `hunyuan_dit`, `pixart`, `auraflow`, `kolors`.

Bumped the header to `(as of November 2026):`, added one bullet per
new fully-registered arch under the correct Image / Video / Other
heading, and moved `flux_kontext` out of the Image fully-registered
list and into the stub enumeration. Edit applied byte-identically to
both copies; `python tests/mirror_drift.py` → `OK: 32/32  DRIFT: 0`.

### T1-c `tools/upgrade_research.py`: HF arch-query map still trailing registry; stale method count

`_HF_ARCH_QUERIES` had 28 entries, but the registry on disk now has
35 `_reg()` keys (28 fully-registered + 7 stubs). That means
`_hf_query_for_method(build_<arch>_*)` would still return `None` for
the eight archs that have landed since the 2026-10-16 fix:
`flux2dev`, `flux3klein`, `krea2`, `qwen_image`, `minimax_h3`,
`skyreels`, `longcat`, `aurasr`. Broadened `wan` to pick up `wan-2.5`
and `ltx` to pick up `ltx-2.5` while I was there — both now have
real HF listings.

Added mappings for: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`,
`minimax_h3`, `skyreels`, `longcat`, `aurasr`.

Also bumped the stale method-count claim in the module docstring from
`"75 as of 2026-10-16"` → `"78 as of 2026-11-24"`.

Verification: `python tools/upgrade_research.py --dry-run` still
exits `0`, same `4 proposals from 5 backends` shape; `pytest tests/`
→ `57 passed`.

### Verification of T1-a through T1-c

- `pytest tests/` — `57 passed in 7.94s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same
  shape as before the arch-query map expansion.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  no manifest regen required (count already correct).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **black-forest-labs/flux-3-image-klein-comfy** | 2026-10-14 | Already has `_reg("flux3klein", …)` on disk; what's missing is a weight on the fleet | ~11 GB fp16 | medium | 2 | **Delta since the 2026-10-16 digest:** the `-comfy` repackage is now 892K downloads / 4,517 likes (was 73K/382). The `unsloth/flux-3-image-klein-GGUF` (475K/56 likes) and `unsloth/flux-3-image-klein-FP8` (318K/8 likes) quantized variants are also live — pick the GGUF path for the 12-GB tier. The `_reg("flux3klein", …)` wiring is already in `architectures.py` (sampler="custom_advanced", steps=16, `type="flux3"` CLIP); this is a weights-download operation only, not code work. |
| **Wan-AI/Wan2.2-Animate-2-14B-Diffusers** | 2026-08-06 | Successor to the `Wan2.2-Animate-14B` already consumed by the `wan` arch's animate branch | ~17 GB fp16 (14B params) | medium | 2 | 28.4K downloads on the base Diffusers repo; the Wan 2.2-Animate original is 237K/1,325. This is a drop-in weights swap at the Comfy `models/unet/` path — but the Diffusers pipeline name changed (`WanAnimate2Pipeline` vs `WanAnimatePipeline`), so a ComfyUI custom-node audit is needed before the swap lands on the fleet. |
| **Abiray/LTX-2.5-Distilled-GGUF** | 2026-08-12 | GGUF-quantized companion to the already-queued `Lightricks/LTX-2.5` download | ~6 GB (Q4_K_M) | low | 2 | 28.3K downloads / 98 likes. If the operator's fleet has 12-16 GB per host (Spark2 does), the GGUF path is preferable to the 22B fp16 base — same quality ceiling, half the VRAM. Pair this with the LTX-2.5 base download already in the queue. |
| **apple/FastFrames-L** + **apple/FastFrames-S** | 2026-11-16 | Fine-tunes of `Wan2.1-T2V-14B` / `Wan2.1-T2V-1.3B` — targets the existing `wan` arch | 14B: ~17 GB fp16; 1.3B: ~2 GB | low | 2 | 582 + 210 likes within a week of launch; downloads not yet recorded by the Hub (likely gated / staged). Apple's amlr licence (research-friendly, not pure open), paper `arxiv:2611.23226`. The `_reg("wan", …)` entry already accepts `wan` LoRAs; FastFrames would land as another checkpoint variant under the same arch, not a new `_reg()`. Decision: is the quality delta vs. base Wan 2.1-T2V worth the fleet storage? |
| **apple/DepthPro2** | 2026-11-03 | NEW monocular + video depth-estimation capability — not currently covered by any `_reg()` | ~1-2 GB (Depth-Pro successor) | medium | 2 | 1,168 likes, zero downloads (base) / 1.8K downloads for the `-H` (half-precision) variant / 780 for the `-focal` camera-calibration variant. Different task than anything currently in Spellcaster's arch registry — would land as a new builder family under `other` (comparable to `supir` and `aurasr` which are single-task registrations). Paper `arxiv:2611.26603`. Uncertain whether Spellcaster's current image pipeline has a downstream consumer for depth maps; needs an operator decision on whether to add depth as a first-class output channel. |
| **facebook/sam-3d-body-dinov3** | 2025-12-10 (updated) | SAM 3D for human-mesh + body pose from a single image — a NEW builder family, not a replacement | ~3 GB (DINOv3 backbone) | medium | 2 | **Movement since 2026-10-16:** now 1,890 likes / 20.3K downloads (was 541/8.4K). HF gating moved from `auto` → `manual`, so a fleet host needs a one-time "request access" click on huggingface.co rather than just a logged-in CLI. The prior digest's Tier-3 download command_hint still stands but is now gated by that manual approval step. |
| **Comfy-Org/sam3.1** | 2026-04-14 | ComfyUI-shape repackage of `facebook/sam3.1` — direct drop-in for the already-wired `build_sam3_segment` | ~2 GB | low | 2 | 458K downloads / 130 likes on the Comfy repackage (base `facebook/sam3.1` is 123K/1,660, `unsloth/sam3.1` 6.9K/38). The Comfy-Org path is the cleanest for the fleet — `diffusion-single-file`, drops into `ComfyUI/models/sam3/` without any Diffusers pipeline wiring. The 2026-10-16 digest's `audit_sam3_version_on_fleet` Tier-3 action still gates this: confirm first what version the `SAM3Segment` ComfyUI node currently resolves. |
| **chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized** | 2026-11-23 | Quantized Qwen-Image-2.1 companion for the already-wired `qwen_image` arch | ~10 GB (quantized) | medium | 2 | 474K downloads / 877 likes in 24 h of trending. The `_reg("qwen_image", …)` is already on disk (steps=20, `clip_type="qwen_image"`); this is a weights-only operation on the 12-GB tier. SFW lane: this is the "Omni" cross-lane repack — SFW/NSFW gate stays with the spellcaster_NSFW pipeline, not this repo's canon. |

### Tier-2 non-model finding

- **Flux 3 Dev does not yet exist.** The 2026-10-16 digest's Tier-2
  row `Comfy-Org/flux2-dev` (the non-distilled Flux 2) has shipped as
  `_reg("flux2dev", …)` on disk since then. But the equivalent Flux 3
  Dev (non-distilled Flux 3) is NOT on HF yet — search for
  `flux-3-dev` returns only Flux 1 Dev quantizations and Flux 3 Klein
  variants. Which means the `flux3klein` registration landed without
  a dev companion to follow; worth noting so the operator doesn't
  queue a Flux-3-Dev download that doesn't exist to download.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-24 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: unsloth/flux-3-image-klein-GGUF
    target_host: spark2
    reason: "The _reg('flux3klein', ...) registration is already on disk in architectures.py (sampler=custom_advanced, 16 steps, type='flux3' CLIP), so the only remaining work to put Flux 3 Klein on the fleet is to get its weights there. GGUF is the right path for the 12-GB tier; Spark1 can take the full comfy repackage if preferred."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\flux-3-image-klein-GGUF"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Abiray/LTX-2.5-Distilled-GGUF
    target_host: spark2
    reason: "Quantized companion to the already-queued Lightricks/LTX-2.5 base. Preferred on the 12-16 GB tier — same quality ceiling, half the VRAM. Pair with the base LTX-2.5 download already in the queue; same target directory, different file."
    command_hint: "huggingface-cli download Abiray/LTX-2.5-Distilled-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\LTX-2.5-Distilled-GGUF"
    risk: low

  - action: evaluate_wan22_animate2_swap
    target_repo: Wan-AI/Wan2.2-Animate-2-14B-Diffusers
    target_host: spark1
    reason: "Successor to Wan 2.2-Animate already on the fleet's wan arch. Diffusers pipeline name changed (WanAnimate2Pipeline vs WanAnimatePipeline), so a ComfyUI custom-node audit is needed before swap lands. Weights-only on the Comfy side if the node supports the new name."
    command_hint: "powershell -c \"Get-ChildItem 'D:\\LLM\\ComfyUI\\custom_nodes' -Recurse -Filter '*wan*anim*' | Select-Object FullName\" # audit first; then: huggingface-cli download Wan-AI/Wan2.2-Animate-2-14B-Diffusers --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Wan2.2-Animate-2"
    risk: medium

  - action: evaluate_depthpro2_adjunct
    target_repo: apple/DepthPro2
    target_host: unknown
    reason: "NEW monocular + video depth-estimation model from Apple. Not currently in Spellcaster's arch registry — would land as a new 'other' builder family (comparable to supir and aurasr). Needs an operator decision first: is there a downstream Spellcaster consumer for depth maps (ControlNet-depth is one; is there anything else)?"
    command_hint: "huggingface-cli download apple/DepthPro2-H --local-dir D:\\LLM\\ComfyUI\\models\\depth-pro\\DepthPro2-H"
    risk: medium

  - action: evaluate_apple_fastframes_wan_finetune
    target_repo: apple/FastFrames-L
    target_host: spark1
    reason: "Apple-published fine-tune of Wan2.1-T2V-14B. Would land as another checkpoint variant under the existing _reg('wan', ...) arch, not a new _reg(). Apple-amlr license; verify research-use vs. redistribution terms before shipping."
    command_hint: "huggingface-cli download apple/FastFrames-L --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\FastFrames-L"
    risk: medium

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Full-size Flux 3 Klein weights for the Spark1 tier. The _reg('flux3klein', ...) wiring is already on disk, so this is a weights-only download. Deltas from the 2026-10-16 digest: 892K downloads / 4,517 likes now (was 73K/382). Gated=auto on HF — needs huggingface-cli login on the fleet host once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Carried from 2026-10-16: fast distilled companion to the Qwen-Image-2.1 base. Note: _reg('qwen_image', ...) IS now on disk (default_steps=20) — it's wired for the full-quality base. For the Turbo variant, prefer the GGUF path (unsloth/Qwen-Image-2.1-Turbo-GGUF); may need a separate _reg entry with fewer steps."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "Carried from 2026-10-16: still a prerequisite for the SAM 3.1 swap. One-liner on each fleet host; no download yet, just a path check. Confirm which SAM3 weights the SAM3Segment ComfyUI node is actually loading."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/sam3.1
    target_host: spark1
    reason: "Swap the audit target to Comfy-Org/sam3.1 (458K downloads vs. the base facebook/sam3.1 at 123K) — Comfy-Org's is the diffusion-single-file repackage that drops straight into ComfyUI's model dir. Weights-only drop-in for the already-wired build_sam3_segment, IF the SAM3Segment ComfyUI node loader accepts 3.1-shape weights. Audit above runs first."
    command_hint: "huggingface-cli download Comfy-Org/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Carried from 2026-10-16: alpha-matte / background removal adapter on top of LTX-2.5. Depends on LTX-2.5 base weights. ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Carried from 2026-10-16: spatial upscaler adapter on LTX-2.5. ~2 GB. Pairs with existing supir (image-only) + aurasr (image-only) upscalers for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "Carried from 2026-10-16: SAM 3D for human-mesh / body pose. Deltas since: now 1,890 likes / 20.3K downloads (was 541/8.4K). HF gating moved from auto → manual, so a fleet host needs a one-time 'request access' click on huggingface.co rather than just a logged-in CLI. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family."
    command_hint: "# After manual access request approved on huggingface.co:\nhuggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Carried from 2026-10-16: direct upgrade path for _reg('ltx', ...). HF now shows 3.0M downloads / 13,268 likes (was 1.9M/8,035) — accelerating. Gated=auto; needs HF login the sandbox doesn't have. Pair with the new Abiray GGUF (above) for the 12-GB tier."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Carried from 2026-10-16: drop-in for existing _reg('hunyuan_3d', ...); current build_hunyuan_3d points at 2.0-shape weights, 2.1 mesh+texture pipeline may need node-list audit before the swap."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Carried from 2026-10-16: enables build_controlnet_gen on the zit arch (currently an empty cn list)."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c now gives the HF arch-query map 8 additional arches (flux2dev, flux3klein, krea2, qwen_image, minimax_h3, skyreels, longcat, aurasr) to probe when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "Still open from 2026-10-16: if LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein augments or replaces Flux-2-Klein, the older weights on D:\\LLM should be flagged for retirement. Mechanical audit, no new tool required yet — can be a one-liner find+compare."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; a drafting candidate for a future digest's Tier-1."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **Scheduler cadence drift.** The last digest is dated 2026-10-16;
   this one is 2026-11-24. The routine is nominally every 48 h; 39
   days between runs means the scheduler paused, or earlier runs
   died before producing their digest. Not actionable from inside
   the sandbox — the operator should check the "Ecosystem Research
   Digest (every 48h)" trigger's status in the Claude routines
   dashboard.

2. **`tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.** Still
   named in the local-action queue but never written. If the next
   wave of fleet downloads (Flux-3-Klein, LTX-2.5, Wan 2.2-Animate 2)
   lands, the retirable-weights question lives behind this tool.
   Writing it is a ~100-line Tier-1 candidate for a future digest:
   read `architectures.py` + walk `ComfyUI/models/*`, print paths
   matching `registered=True` arches that have more than one weights
   candidate on disk. Skipped here because I didn't want to commit a
   tool that depends on fleet-only paths without being able to smoke
   it end-to-end.

3. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap the 2026-09-22 and 2026-10-16 digests flagged — the
   tool's HF and civitai backends use `urllib`, which the cloud
   proxy 403s. Teaching the `huggingface` backend to prefer an MCP
   transport when one is available would let *this* routine run the
   ranked backend from the cloud instead of the skeleton one. Doable
   but it broadens the tool's dependency surface (would need an MCP
   client in-process or a sidecar), so not shipped here.

4. **`flux2klein` → `flux3klein` migration path.** When the operator
   decides to flip, the question of whether to KEEP the `flux2klein`
   `_reg()` entry (for people on the older weights) or REPLACE it
   outright becomes architectural. Default of this project's style
   has been to keep older arches registered under a backward name so
   existing calibrations don't orphan; both are on disk right now,
   so this is a documentation call, not code.

5. **`flux_kontext` stub lifecycle.** Moved from fully-registered to
   stub since the previous digest's inventory — the docstring is now
   consistent with that, but the Tier-2 queue never mentioned a
   Flux Kontext successor. If `flux_kontext` is on its way out (not
   just paused), a future digest should either revive it with a
   real upstream reference or drop the `_reg()` entirely.

6. **CI leak-check.** Not run this cycle because the branch has no
   `_dev_docs/` content changes beyond the usual digest. Will keep
   watching on the PR.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
AST scans of `architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`._
