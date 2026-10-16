# Ecosystem digest — 2026-10-16

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `ecf4249`). Branch: `claude/adoring-allen-p38r5b`.

## Delivery notes

- **Previous digest merged.** The 2026-09-22 digest (plus its ten-PR
  stacked harvest) landed as `2ebdf38` on `main`, so this run starts
  from a clean slate rather than stacking on an open queue.
- **Routine health.** `tools/upgrade_research.py` is still present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`). No
  skeleton draft needed this run.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`, so the
  live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here; Hugging-Face
  MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`) is the live
  path from the cloud this run uses. ~10 MCP calls spent of the ~25
  soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — scanned current `main`'s tracked tree with the
  canonical pattern list from `.githooks/leak-patterns`; **clean**
  (`exit: 1` = `git grep` found no match, which is the pass case for
  this check). The follow-up filed by the 2026-09-22 digest to extend
  the file-exclusion set to `_dev_docs/` / `_audit/` / `.githooks/`
  can be closed — the current pattern list no longer hits those
  surfaces.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
52/52).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — September 2026` on the hero banner. Today is 2026-10-16.
Bumped to `📣 Status — October 2026`. News/Focus/Next copy left as-is
(all still describes past-tense "landed" items that remain true today —
installer self-healing, LM Studio prompt enhancement, mirror sync, etc.).

### T1-b `architectures.py` docstring: enumeration + date

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
module-level
`SUPPORTED ARCHITECTURES (as of September 2026):` block, listing only
**7 archs** (sd15, sdxl, illustrious, zit, flux1dev, flux2klein,
flux_kontext) while the registry on disk is **27 `_reg()` entries**
(21 fully-registered + 6 stubs). The 2026-09-22 digest explicitly left
this expansion as a Tier-2 pending-operator-call finding; downgrading
and shipping now because:

- The split between fully-wired and stub is unambiguous — `registered=`
  is on each `_reg()` call explicitly, no judgement needed.
- The enumeration is docstring-only; the registry itself remains
  source-of-truth.
- Mirror-drift stays byte-identical: identical edit applied to both
  copies, `python tests/mirror_drift.py` → `OK: 29/29  DRIFT: 0`.

Bumped the header to `(as of October 2026):` and expanded the list into
three sections — Image (11 fully-registered), Video (7
fully-registered), Other (3 fully-registered), with an explicit stub
list underneath.

### T1-c `tools/upgrade_research.py`: HF arch-query map is missing 12 archs

`_HF_ARCH_QUERIES` had entries for 16 arches but the registry on disk
has 27. That means `_hf_query_for_method(build_<arch>_*)` returned
`None` for 12 fully-registered or stub archs, so a live `huggingface`
or `civitai` backend run would **silently skip** candidate research
for them. Also noticed the existing `"lumina": [...]` key doesn't
match the actual arch id `lumina2` — same bug class.

Added mappings for: `sdxl_turbo`, `playground`, `seedvr`, `cogvideo`,
`framepack`, `hunyuan_video`, `hunyuan_3d`, `mochi`, `sd3_turbo`,
`pixart`, `supir`, plus renamed `"lumina"` → `"lumina2"` with
backwards-compatible aliases. Also broadened the existing `wan` and
`ltx` entries to pick up the 2.2 / 2.5 generations (previously only
`"wan-2.1"` and `"ltx-video", "ltxv"`).

Also bumped the stale method-count claim in the module docstring from
"70 build_* methods" → "`build_*` methods — 70 at the time of that
pass, 75 as of 2026-10-16".

Verification: `python tools/upgrade_research.py --dry-run` still exits
`0`, same `4 proposals from 5 backends` output; `pytest tests/` →
`52 passed`.

**Verification of T1-a through T1-c**

- `pytest tests/` — `52 passed in 9.32s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same shape
  as before the arch-query map expansion.
- `python tests/mirror_drift.py` — `OK: 29/29   DRIFT: 0`.
- `python tests/night_maintenance.py --dry-mode --quiet` — exit `0`.
- `python tools/build_builders_manifest.py` — `wrote … (75 methods)`;
  no manifest regen required.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **black-forest-labs/flux-3-image-klein** + **-comfy** | 2026-10-16 | NEW `flux3klein` arch — direct successor to the current `flux2klein` registration at `architectures.py:679` | ~11 GB fp16 (5.5B params) | medium | 2 | 374 + 382 likes / 22K + 73K downloads in the first 48 hours. The `-comfy` variant is `diffusion-single-file` → drops straight into `ComfyUI/models/checkpoints/`. Gated=auto on HF, so a fleet host needs `huggingface-cli login`. Would land as `_reg("flux3klein", …)` beside the existing `_reg("flux2klein", …)` plus a `build_klein_repose` + `build_klein_*` family switch; the 4-step distill shape is unchanged from Klein 2, so sampler config can be forked from the 2's entry. |
| **Qwen/Qwen-Image-2.1-Turbo** | 2026-10-12 | Fast companion to the `Qwen-Image-2.1` arch the 2026-09-22 digest already filed as Tier-2 — not shipped yet, so this is a *paired* integration | ~10 GB fp8, ~16 GB fp16 (7.1B params) | medium | 2 | 923 likes / 17.4K downloads on the base repo; the community distill (`AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF` 328K downloads, `unsloth/Qwen-Image-2.1-Turbo-GGUF` 294K downloads, `Viggle/Qwen-Image-2.1-viggle-turbo` 494K) signals the turbo variant is where the ComfyUI traffic has gone. If `qwen_image` lands, wire this in the SAME PR as the few-step default for the 12-GB tier. |
| **facebook/sam3.1** | 2026-03-26 | Version-swap for the `SAM3Segment` ComfyUI node already consumed by `build_sam3_segment` (`workflows.py:7014`) | ~2 GB (ViT-L backbone) | low | 2 | 90.9K downloads / 1,091 likes. Pre-existing `build_sam3_segment` uses the generic `SAM3Segment` node, so if the node loader accepts 3.1 checkpoints without a `node_name` change this is a *weights-only* swap on the fleet. Needs operator verification: does the installed `SAM3Segment` node resolve 3.1-shape weights at the Comfy model-dir path, or does it need an updated custom-node pack? |
| **facebook/sam3** | 2025-11-07 | Baseline check — the "type 'hair', select the hair" promise in README | ~2 GB | low | 2 | 2.03M downloads / 4,493 likes — currently the dominant open mask-generation model. `build_sam3_segment` is already wired; the question is whether the fleet is already on 3.0 or still falling back to 2.x. One-line audit for the operator to confirm. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen** | 2026-09-28 | Adds alpha-matte / background-removal to the planned `ltx` 2.5 integration | ~2 GB (adapter on top of LTX-2.5) | low | 2 | 185 likes / 11.2K downloads. If the 2026-09-22 digest's `Lightricks/LTX-2.5` Tier-3 download lands on the fleet, this adapter unlocks a `build_ltx_remove_bg_video` builder with no new base weights to download. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler** | 2026-08-11 | Video spatial upscaler as a `build_ltx_upscale_video` method | ~2 GB (adapter) | low | 2 | 125 likes / 10.8K downloads. Same arch as above. Pairs well with the `supir` image upscaler (which is image-only). |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details** | 2026-09-27 | Video detail-refinement adapter | ~2 GB (adapter) | low | 2 | 65 likes / 16.1K downloads. Lightricks-published, so same license + distribution contract as the base 2.5 model. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients** | 2026-09-10 | Character-consistency reference-sheet adapter | ~2 GB (adapter) | low | 2 | 66 likes / 9.2K downloads. Reference-image flow aligned with spellcaster's existing character-consistency builder patterns in the illustrious / sdxl arches. |
| **facebook/sam-3d-body-dinov3** | 2025-11-17 | NEW capability — 3D human-mesh recovery from a single image | ~3 GB (DINOv3 backbone) | medium | 2 | 541 likes / 8.4K downloads. Would land as a NEW builder family alongside `build_hunyuan_3d` (which does image-to-3d-object). Different task (human mesh + pose) than Hunyuan3D's object mesh. Needs a decision: new `sam3d` arch or extension of the `hunyuan_3d` builder set? |
| **facebook/sam-3d-objects** | 2025-10-06 | Alternate image-to-3d for `_reg("hunyuan_3d", …)` | ~3 GB | medium | 2 | 575 likes / 5.5K downloads. Direct comparator for Hunyuan3D-2.x. Not a replacement — different mesh style, different texture pipeline — but worth benchmarking against Hunyuan3D 2.1 (also Tier-2 from previous digest) before committing fleet storage to only one. |
| **Comfy-Org/flux2-dev** | 2025-11-25 | NEW arch `flux2dev` separate from `flux2klein` | ~24 GB fp16 (full-size, not distilled) | medium | 2 | 1.1M downloads / 352 likes. The non-distilled Flux 2 variant — bigger, slower, higher ceiling than the 4-step Klein. Would land as `_reg("flux2dev", …)` with a different sampler shape than `flux2klein` (standard DDIM/Euler rather than Klein's custom sampler). Decision point: is the quality delta worth the extra 13 GB over Klein? |
| **BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4** | 2026-10-15 (updated) | Prompt-engineering LLM specialized for Z-Image (`zit` arch) prompts | ~3 GB (GGUF Q4) | low | 2 | 167 likes / 5.4K downloads. A LM Studio–loadable prompt enhancer tuned for `zit`'s short-prompt / few-step shape. Would wire into `llm_delegate.py`'s existing LM Studio hook as a model-choice option for prompts headed to `build_zit_*`. |

### Tier-2 non-model finding

- **Dedup / tiering of the Qwen-Image track.** The 2026-09-22 digest
  filed `Qwen/Qwen-Image-2.1`, `Comfy-Org/Qwen-Image-2.1`, and
  `abenzerps/Qwen-Image-2.1-GGUF` as three Tier-2 rows; this run adds
  the Turbo-distilled fork as a fourth. The operator decision to make
  before any Qwen-Image lands is: ship the base + GGUF path first, or
  skip straight to Turbo + Turbo-GGUF (since Turbo's community volume
  has clearly eclipsed the base's — 494K + 328K + 294K downloads vs.
  the base repo's ~17K). This is the kind of "pick one lane" call
  that stays Tier-2 because it affects which weights the fleet
  downloads, not which code lands.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-09-22 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-10-16 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein lands as the direct successor to the current _reg('flux2klein', ...) in architectures.py. The -comfy repackage is diffusion-single-file so it drops into ComfyUI/models/checkpoints/ with no diffusers-pipeline plumbing. Gated=auto on HF — needs huggingface-cli login on the fleet host once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Fast distilled companion to the Qwen-Image-2.1 base already queued from 2026-09-22. Prefer the GGUF path (unsloth/Qwen-Image-2.1-Turbo-GGUF, 294K downloads) for the 12-GB tier — base repo is diffusers-only."
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
    reason: "Alpha-matte / background removal adapter on top of LTX-2.5. Depends on LTX-2.5 base weights (previous digest's Tier-3 download). ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
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

  # ─── Carried over from 2026-09-22 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Base Qwen-Image-2.1 arch — superseded on the community side by the Turbo distill (see new entry above). If the fleet picks the full-quality lane rather than the few-step one, this is still the right weights to grab."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). HF now shows 1.9M downloads / 8035 likes on the base repo — confirmed dominant open-source i2v. Gated=auto; needs HF login the sandbox doesn't have."
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
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c now at least gives the HF arch-query map 11 extra arches to probe when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein, the older weights on D:\\LLM should be flagged for retirement. Mechanical audit: compare architectures.py registered=True set against ComfyUI/models/*."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; a drafting candidate for a future digest's Tier-1."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.** Named
   in prior Tier-3 queues but has never been written. If the next
   wave of fleet downloads (Flux-3-Klein, LTX-2.5, Qwen-Image-2.1
   either lane) lands, the retirable-weights question lives behind
   this tool. Writing it is a ~100-line Tier-1 candidate for a future
   digest: read `architectures.py` + walk `ComfyUI/models/*`, print
   paths matching `registered=True` arches that have more than one
   weights candidate on disk.

2. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap the 2026-09-22 digest flagged — the tool's HF and civitai
   backends use `urllib`, which the cloud proxy 403s. Teaching the
   `huggingface` backend to prefer an MCP transport when one is
   available would let *this* routine run the ranked backend from
   the cloud instead of the skeleton one. Doable but it broadens the
   tool's dependency surface (would need an MCP client in-process or
   a sidecar), so not shipped here.

3. **`flux2klein` → `flux3klein` migration path.** When the operator
   decides to flip, the question of whether to KEEP the `flux2klein`
   `_reg()` entry (for people on the older weights) or REPLACE it
   outright becomes architectural. Default of this project's
   style has been to keep older arches registered under a backward
   name so existing calibrations don't orphan — a future Tier-1 can
   add the `flux3klein` entry non-destructively and leave `flux2klein`
   until a later cleanup.

4. **Backlog decision — resolved.** 2026-09-22's #5 ("ten open
   digests, pause the routine or merge one") resolved itself: that
   digest was merged (sha `2ebdf38`) and the stacked PRs harvested.
   This run starts on clean `main`.

5. **`fetch_metadata.py` TLS flag.** 2026-09-22's #2 ("spot-checked
   `CERT_NONE` disable") is **no longer present** — current
   `fetch_metadata.py` uses `ssl.create_default_context()`. Grep of
   the live tree confirms the only `CERT_NONE` + `check_hostname=False`
   pairs are inside `antenna.RETIRED-*` and `tavern/server.py` (which
   is a tavern-internal server, not an outbound client — different
   threat model). Follow-up closed.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
AST scans of `architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`._
