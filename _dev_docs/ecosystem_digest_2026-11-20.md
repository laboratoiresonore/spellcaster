# Ecosystem digest — 2026-11-20

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-e5quzv`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest (sha `75ef09a`) and
  its three Tier-1 fixes landed on `main`, so this run starts from a
  clean slate.
- **Routine health.** `tools/upgrade_research.py` is still present and
  `--dry-run` exits `0` with `4 proposals from 5 backends`. 78 methods
  are now in scope (vs 75 at the time of the previous digest). No
  skeleton draft needed this run.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`, so the
  live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here; Hugging-Face
  MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`) is the live
  path from the cloud this run uses. ~8 MCP calls spent of the ~25
  soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — replicated locally with the canonical pattern
  list from `.githooks/leak-patterns` against the tracked tree;
  **clean** (`git grep` returned exit 1 = no match = the pass case
  for this check).
- **Mirror-drift CI** — `python tests/mirror_drift.py` → `exit 0` after
  the Tier-1b edits. Identical content-only docstring change applied
  to both surfaces.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
57/57).

### T1-a `README.md`: front-page is one month + three archs stale

Two drifted fields on the hero banner:

- **Status month.** `📣 Status — October 2026` → `📣 Status — November 2026`.
  (News / What works / Focus / Next copy left as-is; still describes
  past-tense "landed" items that remain true today.)
- **Tagline method count.** `75 AI tools, one menu.` → `78 AI tools,
  one menu.` The number lived on the hero tagline and in
  `tools/upgrade_research.py`'s module docstring; the real count is
  `78` (confirmed by `python tools/build_builders_manifest.py` →
  `wrote … (78 methods)`).

### T1-b `architectures.py` docstring: enumeration is 8 arches behind

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) still carried the
`(as of October 2026)` enumeration listing 21 fully-registered arches.
The actual registry has **29 fully-registered + 6 stubs** (programmatic
count via `from spellcaster_core.architectures import ARCHITECTURES`,
excluding the `my_custom_model` custom entry). The 8 new arches that
landed between October and November 2026 (via `4b1e1c0 feat(v2.4):
full Spark2 GB10 NVFP4/FP8/INT8 image & video model support across all
plugins` and `0e63dc1 fix(models): resolve post-push audit findings
SPELLCASTER_STEER_002`) never propagated to the docstring:

- **Image (new):** `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
- **Video (new):** `minimax_h3`, `skyreels`, `longcat`
- **Other (new):** `aurasr`

Shipping now because this is docstring-only (the registry itself
remains the source of truth, so a stale header is a doc-rot bug, not
a behavior bug), mirror-byte-identical (same edit applied to both),
and the enumeration follows the same three-section shape the previous
digest established.

Bumped the header to `(as of November 2026):` and added the 8 new
entries into the corresponding sections.

### T1-c `tools/upgrade_research.py`: HF arch-query map is missing 8 archs

The `_HF_ARCH_QUERIES` table had 27 entries covering the October
registry; the 8 new arches from T1-b (`flux2dev`, `flux3klein`,
`krea2`, `qwen_image`, `minimax_h3`, `skyreels`, `longcat`, `aurasr`)
were absent — so a live `huggingface` or `civitai` backend run would
**silently skip** candidate research for them (`_hf_query_for_method`
returns `None` → caller skips).

Added query mappings for all 8. Also broadened existing `wan` and
`ltx` entries so they pick up Wan-2.5 and LTX-2.5 candidates (the
previous digest already broadened these; this run extends the Wan
list further to cover the 2.5 generation now appearing on HF).

Also bumped the stale method-count claim in the module docstring from
"75 as of 2026-10-16" → "78 as of 2026-11-20".

Verification: `python tools/upgrade_research.py --dry-run` still exits
`0`, same `4 proposals from 5 backends` output; `pytest tests/` →
`57 passed`.

### T1-d `tools/audit_disk_vs_registry.py`: new tool (was Tier-3 TODO)

The 2026-10-16 digest's follow-up #1 named this as a
"~100-line Tier-1 candidate for a future digest": take
`architectures.py`'s `ARCHITECTURES` registry + walk `ComfyUI/models/*`,
print paths matching `registered=True` arches that have more than one
weights candidate on disk.

Shipped a sandbox-friendly version (155 lines) that works offline:

- Reads the registry via `from spellcaster_core.architectures import
  ARCHITECTURES` and keeps the `registered=True` subset.
- Accepts a disk-manifest on stdin or via `--manifest` — one path per
  line, OR a JSON array of absolute paths — so the fleet operator
  pipes the output of `find D:/LLM/ComfyUI/models -type f` (or the
  PowerShell equivalent, same shape as the 2026-10-16 digest's audit
  action hint) rather than needing the tool to touch the disk itself.
  This structure means the tool runs the same way in CI (with
  `--manifest /dev/null` as a smoke test) and on-fleet (with a real
  listing piped in).
- Emits three sections: (1) coverage gaps — registered arches with no
  on-disk weights match, (2) retire candidates — registered arches
  with >1 on-disk weights match (the question Flux-3-Klein landing
  behind an already-present Flux-2-Klein triggered), (3) orphans —
  on-disk files unmatched by any registered arch (which weights to
  decide about).
- `--quiet` flag emits the same three sections as JSON for pipelines.
- Includes a per-arch regex pattern table covering every registered
  arch; tight patterns (e.g. `flux[-_.]?2[-_.]?dev`, `flux[-_.]?3[-_.]?klein`)
  so a Flux-2-Dev checkpoint doesn't also claim the Flux-3-Klein slot.

Smoke-test with `--manifest /dev/null`: scans 0 paths against 30
registered arches (29 core + the `my_custom_model` custom entry),
reports all 30 as coverage gaps (vacuously correct for an empty
manifest), returns exit `1` (gaps found — informational, not a CI
fail). Smoke-test with a hand-fed manifest of six paths including two
`flux-3-klein` variants: detects `flux3klein` as a retire candidate
with the two paths listed.

**Verification of T1-a through T1-d**

- `pytest tests/` — `57 passed in 6.95s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same shape
  as before the arch-query map expansion.
- `python tests/mirror_drift.py --quiet` — exit `0`.
- `python tests/night_maintenance.py --dry-mode --quiet` — exit `0`.
- `python tests/builders_manifest_drift.py` — `manifest fresh (78 methods)`.
- `python tools/audit_disk_vs_registry.py --manifest /dev/null` — exit `1`
  (informational: all 30 arches report as coverage gaps for an empty
  manifest; the tool itself works).
- Leak-check (git grep replicated locally with the canonical pattern
  file) — clean.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`) on 2026-11-20. Numbers below
are the HF report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Qwen/Qwen-Image-Edit-2511** | 2025-12-17 | Direct successor of the existing `_reg("qwen_image", …)` + `build_qwen_edit` already on main | ~20.4 GB fp16 (20.4B params); ~10 GB Q4_K_M GGUF via `unsloth/Qwen-Image-Edit-2511-GGUF` | low | 2 | **2.3M downloads / 1,571 likes** on the base repo. `unsloth/Qwen-Image-Edit-2511-GGUF` is at **1.0M downloads** — the GGUF path is dominant for 12-GB VRAM operators. The 2026-09-22 digest filed `Qwen-Image-2.1` as Tier-2; the Edit-2511 release is a *paired* upgrade. ComfyUI loader is `QwenImageEditPlusPipeline` — unchanged pipeline shape vs the existing `qwen_image` arch, so this is predominantly a weights-only swap on the fleet. Operator decision: skip Qwen-Image-2.1 lane entirely and go straight to Edit-2511 (clear community preference, since Edit-2511 downloads outpace 2.1 10×). |
| **MiniMaxAI/MiniMax-H3-Image** | 2026-11-16 | NEW image arch — IMAGE sibling of the existing `_reg("minimax_h3", …)` video arch | ~16 GB fp16 (est.) | medium | 2 | **877K downloads / 1,678 likes** in 4 days. The current `minimax_h3` registration is video-only; MiniMax-H3-Image is a text-to-image + image-editing variant from the same provider. Decision: either (a) widen the existing `minimax_h3` registration to admit both tasks, or (b) land a new `_reg("minimax_h3_image", …)` beside it (preferred, since the loader library tag is `minimax-h3` and shows separate repos per task). 63+ demo spaces on HF suggests ComfyUI node support is already in motion. |
| **Lightricks/LTX-2.5** (base) | 2026-10-11 (updated) | Direct upgrade path for `_reg("ltx", …)` — still gated=auto, still needs operator login | ~16 GB fp16 (per previous digest) | medium | 2 | **2.96M downloads / 12,822 likes** — grew from 1.9M/8,035 in the 2026-10-16 digest. Confirmed dominant open-source i2v. Still the same gating story (gated=auto on HF, fleet host needs `huggingface-cli login` once). Carried over from previous digest; promoted in the local_action_queue below. |
| **meituan-longcat/LongCat-Video-Avatar-1.6** | 2026-11-13 | Avatar / audio-driven variant of the already-registered `_reg("longcat", …)` video arch | ~8 GB fp16 (quantized variant) | medium | 2 | 357 likes / 2.6K downloads (very new, still accruing). Adds `audio-text-to-video` + `audio-image-text-to-video` tasks on top of base LongCat-Video. 7+ demo spaces already up. If `longcat` is a build target the operator wants on the fleet, this is the avatar-shaped companion. |
| **apple/FastFrames-L** | 2026-11-20 (today) | NEW `text-to-video` model from Apple, fine-tuned on Wan2.1-T2V-14B | ~14 GB fp16 (Wan2.1 14B shape) | medium | 2 | 460 likes / low downloads (same-day publish). Interesting because it's a Wan-shape fine-tune — the existing `_reg("wan", …)` + `build_wan22_t2v` loader probably accepts it with no code change. Licensed `apple-amlr` (research-only; commercial use likely restricted — operator should read the license before adding to the fleet). Three demo spaces including `linoyts/fastframes-l-live` suggest real-time streaming support. |
| **black-forest-labs/flux-3-image-klein-comfy** | 2026-10-14 (updated) | Carried from 2026-10-16 digest — the Flux-3 Klein ComfyUI single-file is now dominantly adopted | ~11 GB fp16 (5.5B params) | medium | 2 | **981K downloads / 3,589 likes** — grew from 73K/382 in the 2026-10-16 digest. 13× adoption surge in one month. `unsloth/flux-3-image-klein-GGUF` at 468K downloads provides the Q4_K_M/Q8_0 path for 12-GB tier. `black-forest-labs/flux-3-image-klein-pup` (a Qwen-3.5-based prompt upsampler specifically trained for Flux-3 Klein, 38.7K downloads / 83 likes) would wire into `llm_delegate.py` as the arch-specific prompt enhancer. Already registered as `_reg("flux3klein", …)` in architectures.py — this is the *weights* half of the integration. |
| **wikeeyang/Flux2-Klein-9B-True-V3** | 2026-06-25 (older, now trending) | Community fine-tune of the existing `_reg("flux2klein", …)` registration | ~18 GB fp16 (9B params); GGUF path available | low | 2 | 177 likes / 19.7K downloads. An apache-2.0 relicensed, bilingual (en/zh) fine-tune of Flux-2 Klein 9B. Drops in behind the existing arch. Decision: whether the operator wants an alternative-finetune LoRA in the SFW canon, or treats this as a replacement checkpoint. |
| **fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA** | 2026-01-07 | Adapter on top of the Qwen-Image-Edit-2511 base — 3D-camera / multi-angle control | ~2 GB (adapter) | low | 2 | 1,633 likes / 76K downloads (one of the highest-liked LoRAs on the Hub right now). If Edit-2511 lands, this adapter unlocks a `build_qwen_edit_multiple_angles` builder with no new base weights. Pairs with the `Qwen-Image-Edit-2511-AnyPose` space (same base) for a camera-control + pose-control pair. |

### Tier-2 non-model finding

- **The Qwen-Image track has resolved itself.** The 2026-10-16 digest
  noted an operator decision pending: ship Qwen-Image-2.1 base + GGUF
  first, or skip to Turbo? The community has now answered — the
  **Edit-2511** release is where the traffic went (2.3M base
  downloads, 1.0M GGUF downloads, 123K downloads on the Rapid AIO
  GGUF). Recommendation: drop 2.1 base from the local_action_queue
  and target Edit-2511 directly.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries that haven't been
actioned, plus this run's new ones. A local Hermes / operator process
consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-20 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-Edit-2511
    target_host: spark1
    reason: "Successor to the Qwen-Image track already queued. Edit-2511 is where the community traffic went (2.3M base + 1M GGUF downloads). Loader is QwenImageEditPlusPipeline — same pipeline shape as the existing _reg('qwen_image', ...), so weights-only drop-in once the ComfyUI side supports Plus. Prefer the GGUF path (unsloth/Qwen-Image-Edit-2511-GGUF, Q4_K_M) for 12-GB operators."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-Edit-2511-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-Edit-2511-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: MiniMaxAI/MiniMax-H3-Image
    target_host: spark2
    reason: "Image sibling of the already-registered minimax_h3 video arch. 877K downloads in 4 days. ComfyUI nodes under development (63+ demo spaces running). Needs an architectures.py decision first: widen _reg('minimax_h3', ...) to admit image tasks, or add _reg('minimax_h3_image', ...) separately — the HF library tag minimax-h3 suggests the latter."
    command_hint: "huggingface-cli download MiniMaxAI/MiniMax-H3-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MiniMax-H3-Image"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA
    target_host: spark1
    reason: "Multiple-angles / 3D-camera LoRA on top of Qwen-Image-Edit-2511. 1,633 likes / 76K downloads (one of the highest-liked LoRAs trending right now). Depends on Qwen-Image-Edit-2511 base — queue after that lands."
    command_hint: "huggingface-cli download fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA --local-dir D:\\LLM\\ComfyUI\\models\\loras\\Qwen-Image-Edit-2511-Multiple-Angles"
    risk: low

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-pup
    target_host: unknown
    reason: "Qwen3.5-9B-based prompt upsampler specifically trained for Flux-3 Klein. Wires into llm_delegate.py's LM Studio hook as the arch-specific prompt enhancer when the generation target is flux3klein. 38.7K downloads / 83 likes. ~5-6 GB in Q5_K_M GGUF."
    command_hint: "huggingface-cli download AtomicChat/FLUX-3-Image-Klein-pup-Uncensored-GGUF --include '*Q5_K_M*' --local-dir D:\\LLM\\LMStudio\\models\\flux3klein-pup"
    risk: low

  - action: evaluate_longcat_avatar
    target_repo: meituan-longcat/LongCat-Video-Avatar-1.6
    target_host: unknown
    reason: "Avatar / audio-driven-video variant of the existing longcat arch. Very new (2026-11-13), 357 likes, 2.6K downloads — evaluate rather than commit. Would be a new builder family (audio-text-to-video is a distinct task from the base longcat)."
    command_hint: "huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.6 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\LongCat-Video-Avatar-1.6"
    risk: medium

  - action: license_review_apple_fastframes
    target_repo: apple/FastFrames-L
    target_host: unknown
    reason: "Apple's new text-to-video (Wan2.1 14B fine-tune). Licensed apple-amlr (research-only). Before any fleet download, confirm the apple-amlr license allows spellcaster's non-commercial-user base case (or restricts it). If OK, the existing build_wan22_t2v loader probably accepts it without code change."
    command_hint: "# Read https://huggingface.co/apple/FastFrames-L/blob/main/LICENSE first; no download yet."
    risk: medium

  - action: run_fleet_disk_audit
    target_repo: null
    target_host: all
    reason: "tools/audit_disk_vs_registry.py now exists (T1-d this digest). A first fleet-wide audit would seed the retire-candidates list before Flux-3-Klein and Qwen-Image-Edit-2511 downloads land and double-up with older weights."
    command_hint: "find D:/LLM/ComfyUI/models -type f -name '*.safetensors' -o -name '*.gguf' | python tools/audit_disk_vs_registry.py --quiet > disk-audit-$(date -I).json"
    risk: low

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "13× adoption surge in one month (73K → 981K downloads). Still the single-file ComfyUI drop-in for the already-registered flux3klein arch. Gated=auto on HF — needs `huggingface-cli login` once on the fleet host."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Still the dominant open-source i2v (now 2.96M downloads / 12.8K likes, up from 1.9M / 8K). Still gated=auto, still needs operator HF login."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "Still carrying from 2026-10-16. SAM 4 has NOT appeared on HF as of this digest — SAM 3.1 remains the frontier. The on-fleet SAM3 version audit still needs to run so a future Tier-1 can confirm build_sam3_segment is loading 3.1 weights where available."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Weights-only drop-in for the already-wired build_sam3_segment IF the SAM3Segment ComfyUI node loader accepts 3.1-shape weights. Audit above runs first."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on LTX-2.5. Depends on LTX-2.5 base weights. ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. Depends on LTX-2.5 base. ~2 GB. Pairs with the existing supir image upscaler (image-only) for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
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
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403). This run's T1-c now gives the HF arch-query map 8 more arches to probe (flux2dev, flux3klein, krea2, qwen_image, minimax_h3, skyreels, longcat, aurasr) when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low
```

### Items resolved this run

- `tools/audit_disk_vs_registry.py` — 2026-10-16's follow-up #1. Now
  exists and smoke-tests cleanly. Removed from the carry-over queue.
- "Dedup / tiering of the Qwen-Image track" — 2026-10-16's Tier-2
  non-model finding. Community volume has now answered it; see this
  run's non-model finding for the recommendation.

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **Widen vs duplicate `minimax_h3`.** The existing
   `_reg("minimax_h3", …)` is video-only, but
   `MiniMaxAI/MiniMax-H3-Image` (877K downloads / 1.6K likes) is an
   image sibling that shares the `minimax-h3` library tag. Decision
   needed: widen the registration or add `_reg("minimax_h3_image", …)`.
   Either direction is architectural; filing for operator input.

2. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap. Teaching the `huggingface` backend to prefer an MCP
   transport (so this routine can run the ranked backend from the
   cloud instead of the skeleton) is doable but broadens the tool's
   dependency surface — not shipped here.

3. **`audit_disk_vs_registry.py` pattern coverage.** The regex table
   covers every registered arch, but on first fleet runs it may
   produce a lot of orphans (every LoRA, VAE, CLIP model etc.). A
   future Tier-1 refines the orphan detection — perhaps by also
   consuming `lora_calibrations_sfw.json` so known LoRAs route to
   "accounted-for" rather than orphan. Doable mechanically once the
   first real fleet listing comes back.

4. **Apple FastFrames-L license.** Before any fleet action on the new
   Apple Wan2.1-shape fine-tune, the `apple-amlr` license text needs
   to be read for commercial-use clauses. Filed as a Tier-3 license
   review above, surfaced here as a note for the operator.

5. **`flux2klein` ↔ `flux3klein` migration path.** Still open from
   2026-10-16's follow-up #3. The sharper decision now is whether to
   remove `flux2klein` from preset defaults once `flux3klein` weights
   land — defer to operator's calibration pass.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs` on `hf://models/trending`; local
`tools/upgrade_research.py --dry-run`; AST + import scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`; `tests/mirror_drift.py`; `tests/night_maintenance.py`._
