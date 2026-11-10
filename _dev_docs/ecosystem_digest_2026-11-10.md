# Ecosystem digest — 2026-11-10

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-t1riwo`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest was merged and
  this run starts from clean `main` rather than a stacked queue.
- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` exits `0` (`4 proposals from 5 backends`, same shape
  as last run). No skeleton rewrite needed.
- **Egress is still proxy-walled.** The cloud sandbox's HTTPS proxy
  still denies direct CONNECT to `huggingface.co` / `civitai.com`,
  so the live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here; Hugging-Face
  MCP (`hub_repo_search`) is the live path from the cloud this run
  uses. ~13 MCP calls spent of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — no pre-existing-red state observed on `main`;
  the diff this run ships is docstring text + a dict literal + a
  one-char date, all below the leak-pattern threshold (checked
  against `.githooks/leak-patterns`).
- **Test suite.** Count rose from the 52 the 2026-10-16 digest saw
  to **57 passed** this run — regression surface grew by 5 tests
  since. All 57 pass on this branch; mirror-drift still clean
  (`OK: 32/32   DRIFT: 0`).

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose
fix is in this branch and whose regression suite passes
(`pytest tests/` → 57/57, mirror-drift 32/32).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner. Today is 2026-11-10.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left
as-is (all still describes past-tense "landed" items that remain
true today — installer self-healing, LM Studio prompt enhancement,
mirror sync, etc.). Same one-line bump the 2026-10-16 run made for
October; this is the routine upkeep that would otherwise just
quietly age.

### T1-b `architectures.py` docstring: enumeration + date

Both mirrored copies
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
module-level `SUPPORTED ARCHITECTURES (as of October 2026):` block,
which the 2026-10-16 digest refreshed to **11 image + 7 video +
3 other fully-registered + 6 stubs = 27**. The registry on disk
now holds **35 `_reg()` entries** (29 fully-registered + 6 stubs):

Added since the October refresh:
- **Image (+4):** `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
- **Video (+2):** `minimax_h3`, `skyreels`
- **Other (+2):** `longcat`, `aurasr`

Rebuilt the block section-by-section with explicit per-section
counts (15 / 9 / 5) and bumped the header to `(as of November 2026):`.
Identical edit applied to both mirrored copies; `python tests/mirror_drift.py`
→ `OK: 32/32  DRIFT: 0`.

Downgrade rationale (same as the T1-b in 2026-10-16): the arch
registry is the authoritative list; the docstring is header-only
text, and `registered=` is explicit on each `_reg()` call, so no
judgement is needed to classify.

### T1-c `tools/upgrade_research.py`: HF arch-query map is missing 8 archs

Same bug class as 2026-10-16's T1-c. The 2026-10-16 fix brought
`_HF_ARCH_QUERIES` from 16 → 27 entries to match the registry at
the time. The registry has since gained 8 more, so the map is
8-off again:

- `aurasr`, `flux2dev`, `flux3klein`, `krea2`, `longcat`,
  `minimax_h3`, `qwen_image`, `skyreels`

Without these, `_hf_query_for_method(build_<arch>_*)` returns
`None` for those arches, so the live `huggingface` and `civitai`
backends would silently skip candidate research for them.

Added mappings with arch-plausible search aliases:
`"flux2dev": ["flux.2-dev", "flux2-dev"]`,
`"flux3klein": ["flux.3-klein", "flux3-klein", "flux-3-image-klein"]`,
`"krea2": ["krea-2", "krea2"]`,
`"qwen_image": ["qwen-image-2", "qwen-image", "qwen-image-2.1"]`,
`"minimax_h3": ["minimax-hailuo-3", "hailuo-3", "minimax-video"]`,
`"skyreels": ["skyreels-v2", "skyreels"]`,
`"longcat": ["longcat-video", "longcat"]`,
`"aurasr": ["aura-sr", "aurasr"]`.

Also bumped the stale method-count claim in the module docstring
from `"70 build_* methods — 70 at the time of that pass, 75 as of
2026-10-16"` → `"70 at the time of that pass, 78 as of 2026-11-10"`
(both mirror copies of `workflows.py` show 78 `build_*` methods
each).

Verification: `python tools/upgrade_research.py --dry-run` exits
`0`, same `4 proposals from 5 backends` output. Post-edit
`_HF_ARCH_QUERIES` now has 35 keys — 1:1 with the arch registry.

**Verification of T1-a through T1-c**

- `pytest tests/` — `57 passed in 6.46s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same
  shape as before the arch-query map expansion.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hub_repo_search`). Download counts
are the HF report at the time of this digest. Movement callouts
compare to the 2026-10-16 snapshot (where applicable).

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **black-forest-labs/flux-3-image-klein-comfy** | 2026-10-14 | `flux3klein` arch (now `_reg()`-landed) — direct successor to `_reg("flux2klein", …)` | ~11 GB fp16 (5.5B params) | medium | 2 | **📈 73K → 1.3M downloads / 382 → 2858 likes in 25 days** (trending score 238 at the time of this digest). The `-comfy` variant is `diffusion-single-file` → drops straight into `ComfyUI/models/checkpoints/`. Registry entry is already in place (see T1-b), so the fleet-side blocker is just downloading the weights (see Tier-3 queue). |
| **black-forest-labs/flux-3-image-klein-base** | 2026-10-13 | NON-distilled companion to `flux3klein` (ships without the 4-step distill) | ~11 GB fp16 | medium | 2 | 132K downloads / 230 likes. The "base" variant trades the 4-step distill for arbitrary-step quality — mirrors the Klein-vs-Dev split that the `flux2klein`/`flux2dev` pair already codifies. Decision point: KEEP `flux3klein` pointing at the distilled 4-step weights and add a future `flux3dev` row for the base? Or let `flux3klein`'s registration accept both? The existing Klein-2 registration treats the 4-step shape as canonical, so the cleanest path is to leave `flux3klein` alone and file a hypothetical `flux3dev` as a separate Tier-2 when the base gets community traction. |
| **unsloth/flux-3-image-klein-GGUF** | 2026-10-16 | 12-GB-tier path for `flux3klein` | 4–8 GB (Q4/Q5 GGUF) | low | 2 | 314K downloads / 51 likes. Same-arch quantized; routes through the existing GGUF loader shape used by `qwen_image`'s GGUF variants. Preferred for the Spark2 / 12-GB tier. |
| **black-forest-labs/flux-3-image-klein-pup** | 2026-10-14 | Prompt-upsampler LLM specific to Flux 3 Klein (Qwen3.5-9B base, fine-tuned for Flux 3 prompt rewriting) | ~5 GB (GGUF Q4/Q5 available via `AtomicChat/*GGUF`) | low | 2 | 70.5K downloads / 79 likes on the base; 40K / 25 on the GGUF repackage (`AtomicChat/FLUX-3-Image-Klein-pup-Uncensored-GGUF`). Would wire into `tools/llm_delegate.py`'s LM Studio hook as a dedicated prompt-enhancer option for anything routed to `build_klein_*` on the Flux 3 lane — exact analog of the `BennyDaBall/Qwen3-4b-Z-Image-Engineer` entry filed last run for `zit`. |
| **NoiseToNova/Flux-3-Klein-turbo-pdd-4_8-steps** | 2026-10-26 | Few-step distill LoRA on top of `flux-3-image-klein-base` (makes the base behave like the 4-step distill when loaded) | <1 GB (LoRA) | low | 2 | 3.5K downloads / 8 likes — low signal, but the shape (community-published PDD distill) is the kind of adapter the fleet typically consumes once a base weight is in place. Flagging for the next sweep: if downloads rise after the Flux-3-Klein base download lands, this becomes an auto-pickup. |
| **Comfy-Org/sam3.1** | 2026-04-14 | ComfyUI-repackaged SAM 3.1, drop-in for the already-wired `build_sam3_segment` builder | ~2 GB (ViT-L backbone) | low | 2 | **396.9K downloads / 124 likes** — the ComfyUI-shaped SAM 3.1 the 2026-10-16 "audit_sam3_version_on_fleet" action was preparing to swap in. The upstream `facebook/sam3.1` also doubled (90.9K → 184.5K / 1091 → 1459 likes). This is now the preferred swap target instead of the raw Facebook repo: `diffusion-single-file` → drops into `ComfyUI/models/sam3/`. |
| **unsloth/sam3.1** | 2026-10-20 | Quantized SAM 3.1 (bf16 / fp8 / int8) for VRAM-constrained hosts | <2 GB | low | 2 | 5.7K downloads / 32 likes. Secondary option if the ComfyUI repackage above is too large for a given fleet host. |
| **Efficient-Large-Model/SoL-Refiner-LTX-2.5-for-MiniMax-H3** | 2026-09-28 | Cross-arch refiner: takes LTX-2.5 output and refines it through MiniMax-H3 | ~5 GB (adapter stack) | medium | 2 | 336 base-repo downloads + 3.5K on `szwagros/SoL-Refiner-LTX-2.5-H3-int8-convrot` (int8 quant). **Interesting because spellcaster has stub-level `minimax_h3` AND fully-registered `ltx` arches, so this refiner sits exactly at an arch-pair we've already named.** No builder exists for either yet though — this is a future-wave integration (needs both LTX-2.5 and MiniMax-H3 base weights on the fleet first). |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details** (growth) | 2026-09-27 | (Same adapter already filed in 2026-10-16 digest as Tier-2) | ~2 GB (adapter) | low | 2 | 📈 16.1K → 20.2K downloads / 65 → 89 likes. Still Tier-2, still depends on the LTX-2.5 base download being Tier-3 queued. |
| **AtomicChat/FLUX-3-Image-Klein-TE-Uncensored-GGUF** | 2026-10-20 | Alternate text-encoder path for `flux3klein` (abliterated Qwen3-VL-4B) | ~3 GB (GGUF) | high | 2 | 32.8K downloads / 25 likes. Named here because it fits the "text-encoder swap" category that spellcaster's `qwen_image` and `zit` arches both support (`extra={"clip_name1": …, "clip_name2": …}`), but it's abliterated — the H6 SFW invariant in `tools/upgrade_research.py` would (correctly) filter this on the SFW lane. Keeping it in the digest as a documented NSFW-pack candidate; it would NOT flow into the SFW canon via the research tool. |

### Tier-2 non-model finding

- **README "75 tools across 19 models" copy is a Tier-2 call, not a Tier-1 fix.**
  The README hero sub-text claims "75 tools across 19 models" and
  the DEEP_DIVE.md anchor is `#all-75-tools`. `workflows.py` now
  has 78 `build_*` methods (both mirror copies), so the number
  looks stale; but `75` here is a curated UI-tool count, not the
  `build_*` function count (the sub-section counts in DEEP_DIVE's
  "All 75 Tools" section sum to 68, not 75 or 78). Treating this
  as a Tier-2 pending-operator-call because the mechanical fix is
  ambiguous: do we bump every "75" to "78" (matches
  `build_*` count, breaks the DEEP_DIVE anchor's history), to
  "68" (matches section sums), or do we leave it and bump
  curated UI-tool copy separately? This is exactly the class of
  "mechanical but wrong without a read" that T1 fixes should not
  attempt.

- **`19 models` copy is also a Tier-2 call.** The sub-tag lists
  11 image + 3 video + 5 helpers = 19 model names user-facing in
  that banner, but the arch registry on disk now holds 29
  fully-registered + 6 stubs = 35 entries. Same kind of curated-
  vs-registry mismatch as above; same reason for keeping it out
  of T1.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries forward the 2026-10-16 entries that have not been reported
as actioned, PLUS this run's new ones and one promoted item. A
local Hermes / operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-10 ────────────────────────────────────────────

  - action: download_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "PROMOTED from 2026-10-16's 'download_and_evaluate_model'. Downloads jumped 73K → 1.3M in 25 days and the flux3klein _reg() entry is already landed in architectures.py, so the fleet-side blocker is just the weights. The -comfy variant is diffusion-single-file; gated=auto on HF, needs huggingface-cli login on the fleet host once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_model
    target_repo: unsloth/flux-3-image-klein-GGUF
    target_host: spark2
    reason: "12-GB-tier path for flux3klein. 314K downloads / 51 likes. Use the Q4_K_M quant for the 12-GB tier; routes through the existing GGUF loader shape (same path qwen_image's GGUF variants use)."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\flux-3-image-klein-GGUF"
    risk: low

  - action: download_model
    target_repo: black-forest-labs/flux-3-image-klein-pup
    target_host: theo
    reason: "Prompt-upsampler LLM (Qwen3.5-9B base) tuned for Flux 3 prompts. Install on theo-local (LM Studio or Ollama) so tools/llm_delegate.py can route build_klein_* prompts through it. GGUF repackage is at AtomicChat/FLUX-3-Image-Klein-pup-Uncensored-GGUF for the same model shape on the 12-GB tier — pick the base for theo (large VRAM) or the GGUF for a Spark."
    command_hint: "huggingface-cli download black-forest-labs/flux-3-image-klein-pup --local-dir D:\\LLM\\lmstudio\\flux-3-image-klein-pup"
    risk: low

  - action: download_model
    target_repo: Comfy-Org/sam3.1
    target_host: spark1
    reason: "ComfyUI-repackaged SAM 3.1 — supersedes the raw facebook/sam3.1 as the drop-in weights for build_sam3_segment (the Comfy repackage has 396.9K dl / 124 likes vs facebook/sam3.1's 184.5K / 1459). diffusion-single-file → ComfyUI/models/sam3/. Supersedes the 2026-10-16 'audit_sam3_version_on_fleet' + 'download facebook/sam3.1' pair — this is now the single correct target."
    command_hint: "huggingface-cli download Comfy-Org/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: audit_disk_vs_registry_tool
    target_repo: null
    target_host: unknown
    reason: "tools/audit_disk_vs_registry.py is STILL not drafted — named in the 2026-10-16 digest's follow-up list as a '~100-line Tier-1 candidate'. Blocks the retire-older-weights action below. With 8 new arches landed since Oct 16 (incl. flux2dev + flux3klein which may both want to live on disk alongside flux2klein), the retirement-vs-coexistence question is now live."
    command_hint: "# Draft candidate: read architectures.py registry, walk ComfyUI/models/*, print arches with >1 weights file for operator review"
    risk: low

  # ─── Carried over from 2026-10-16 (still open) ────────────────────

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Carried over; the qwen_image _reg() entry is now in architectures.py so this is weights-only. Prefer the GGUF path (unsloth/Qwen-Image-2.1-Turbo-GGUF) for the 12-GB tier."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Carried over. Base qwen_image weights; qwen_image _reg() entry now landed, so this is weights-only. Decision between base lane and Turbo lane (above) stays with the operator."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Carried over; prerequisite for the LTX-2.5 LoRA pack below. Gated=auto; needs HF login the sandbox doesn't have."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Carried over. Alpha-matte / background removal adapter on LTX-2.5. ~2 GB, unlocks build_ltx_remove_bg_video."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Carried over. Spatial upscaler adapter on LTX-2.5."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Carried over. 2.1 drop-in for existing _reg('hunyuan_3d', ...); 122.5K downloads on the Comfy-Org repackage. Mesh+texture pipeline may need a node-list audit before the swap."
    command_hint: "huggingface-cli download Comfy-Org/Hunyuan-3D-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Carried over. Enables build_controlnet_gen on the zit arch (currently an empty cn list)."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "Carried over. SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT, so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c now gives the HF arch-query map 8 more arches to probe when the tool DOES run from the LAN (35 total arch keys)."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "Carried over. If LTX-2.5 replaces LTXV-2.3, Flux-3-Klein replaces (or coexists with) Flux-2-Klein, and sam3.1 replaces sam3.0 on the fleet, the older weights should be flagged for retirement. BLOCKED on 'audit_disk_vs_registry_tool' above being drafted."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist"
    risk: low

  # ─── Retirements since 2026-10-16 ─────────────────────────────────

  - action: supersede_entry
    target_repo: facebook/sam3.1
    target_host: unknown
    reason: "The 2026-10-16 digest filed 'audit_sam3_version_on_fleet' + 'download facebook/sam3.1' as a pair. Comfy-Org/sam3.1 (above) is now the preferred drop-in for ComfyUI — supersede this raw-upstream pair with the Comfy-Org variant. Keep facebook/sam3.1 only as a diffusers-pipeline reference."
    command_hint: "# No download; just mark the 2026-10-16 audit+raw-facebook entries as superseded by Comfy-Org/sam3.1"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe
or needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is STILL a Tier-3 TODO.**
   Named in prior Tier-3 queues (2026-09-22, 2026-10-16) but has
   never been written. With 8 new arches landed since Oct 16 —
   notably `flux2dev` and `flux3klein` both likely to coexist on
   disk alongside `flux2klein` — the retirable-weights question is
   now live and the tool is on the critical path for operator
   fleet-cleanup. A future digest should draft the ~100-line
   stub rather than defer again.

2. **Transport fallback for `tools/upgrade_research.py`.** Still
   the same gap the 2026-09-22 and 2026-10-16 digests both
   flagged — the tool's HF and civitai backends use `urllib`,
   which the cloud proxy 403s. This routine has now had three
   runs calling this out; worth a decision this cycle on whether
   the tool should grow an MCP-transport adapter or whether the
   cloud routine should just route through `hub_repo_search` and
   render its own digest-equivalent markdown (effectively what
   this digest already does).

3. **`75 tools` / `19 models` README copy.** See the Tier-2 non-
   model finding. The right fix needs a one-shot operator read of
   what "75 tools" and "19 models" are actually counting
   (user-facing menu items? builder methods? model families?);
   once answered the whole README + DEEP_DIVE anchor set becomes
   mechanical. Candidate for a future Tier-1 with
   operator-confirmed scope.

4. **README "Status" copy beyond the date.** News/Focus/Next
   fields have been unchanged across three monthly bumps now.
   The dates are sliding but the content isn't — at some point
   the copy stops being "current status" and becomes "status as
   of several months ago, with today's date stamped on it".
   Flagging for operator attention, not auto-touching: this is
   content, not mechanical date drift.

5. **`flux2klein` → `flux3klein` coexistence vs migration.**
   Both `_reg()` entries now sit side-by-side in `architectures.py`.
   With the 2026-11-10 jump in `flux3klein` downloads (1.3M),
   the operator decision is now an active one, not hypothetical:
   is the fleet keeping both LoRA calibrations alive, or
   migrating calibrations forward and leaving `flux2klein` only
   as a shim? The research tool can't decide; needs a lab call.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`;
local `tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`; `pytest tests/`; `tests/mirror_drift.py`._
