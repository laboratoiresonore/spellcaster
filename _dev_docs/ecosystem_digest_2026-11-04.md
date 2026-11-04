# Ecosystem digest — 2026-11-04

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-ba01zr`.

## Delivery notes

- **Routine health.** `tools/upgrade_research.py` is present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`,
  `Methods in scope: 78`). No skeleton draft needed this run.
- **Backlog decision — reverted.** The 2026-10-16 digest declared the
  stacked-PR backlog resolved after it landed; two weeks later the
  stack is back. There are **~11 open ecosystem-digest PRs** on the
  repo (`#192`, `#193`, `#195`–`#202`), none merged. Current `main`
  tip (`b7d82d1`) is not from this routine; it is a LoRA-provenance
  commit unrelated to the digest work. This PR adds a 12th open
  branch. Flagging as a follow-up — recommend the operator pick one
  recent digest to merge and close the rest (same action taken after
  the 2026-09-22 cycle; harvesting a single merge keeps the
  high-value drift fixes without accumulating ten divergent branches).
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy
  continues to deny direct CONNECT to `huggingface.co` / `civitai.com`,
  so the live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return skeleton rows when run from here;
  Hugging-Face MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`)
  is the live cloud path this run uses. ~9 MCP calls spent of the ~25
  soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — the tracked tree on `main` plus this run's
  touched files scanned clean against `.githooks/leak-patterns`; the
  only `CERT_NONE`/`check_hostname=False` pairs on disk remain inside
  `antenna.RETIRED-*` and `tavern/server.py` (internal tavern server,
  different threat model — matches the 2026-10-16 digest's finding).

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/`
→ 57/57).

### T1-a `README.md`: front-page status one month stale

Hero banner was `📣 Status — October 2026`. Today is 2026-11-04.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left
alone — all describes past-tense "landed" items that remain true
today.

### T1-b `architectures.py` docstring: 8 fully-registered arches + date are stale

Both mirror copies
(`comfyui-spellcaster/spellcaster_core/architectures.py` and
`plugins/gimp/comfyui-connector/spellcaster_core/architectures.py`)
carried the module-level
`SUPPORTED ARCHITECTURES (as of October 2026):` block, enumerating
**21 fully-registered + 6 stubs = 27 arches** while the registry on
disk has **29 fully-registered + 6 stubs = 35 `_reg()` entries**. AST
scan of the file confirms the 8 missing fully-registered arches:

- Image: `flux2dev` (`_reg` at line 768), `flux3klein` (line 813),
  `krea2` (line 865), `qwen_image` (line 911).
- Video: `minimax_h3` (line 1336), `skyreels` (line 1354),
  `longcat` (line 1371).
- Other: `aurasr` (line 1383) — AuraSR v2 GAN-based 4x upscaler.

Expanded the docstring enumeration to cover all 29 fully-registered
arches plus the 6 stubs (unchanged). Bumped the header date to
`(as of November 2026):`. Identical edit applied to both mirror
copies — `python tests/mirror_drift.py` → `OK: 32/32   DRIFT: 0`.

Downgrading from Tier 2 to Tier 1 because the split between
fully-wired and stub is unambiguous (`registered=True`/`False` on
each `_reg()` call) and the enumeration is docstring-only — the
registry itself remains source-of-truth.

### T1-c `tools/upgrade_research.py`: `_HF_ARCH_QUERIES` map is missing 8 arches + stale method count

Same bug class the 2026-10-16 digest already fixed once — the
registry now has 35 arches but `_HF_ARCH_QUERIES` has 29 entries,
so `_hf_query_for_method(build_<arch>_*)` returns `None` for 8 arches,
silently skipping candidate research for them if a live HF/civitai
backend ever runs from a LAN host.

Added mappings for the 8 arches registered between 2026-10-16 and
today:

- `flux2dev`: `["flux.2-dev", "flux2-dev"]`
- `flux3klein`: `["flux.3-klein", "flux3-klein", "flux-3-image-klein"]`
- `krea2`: `["krea-2", "krea2", "krea-turbo", "krea-edit"]`
- `qwen_image`: `["qwen-image", "qwen-image-2", "qwen-image-2.1"]`
- `minimax_h3`: `["minimax-h3", "minimax_h3", "minimax"]`
- `skyreels`: `["skyreels", "skyreels-v2", "skyreels-2"]`
- `longcat`: `["longcat", "longcat-video"]`
- `aurasr`: `["aurasr", "aura-sr"]`

Also broadened the existing `wan` entry to pick up `wan-2.5` (the
upcoming generation) and `ltx` to pick up `ltx-2.5` explicitly
(previously only captured by the `ltx-2` glob, which would miss any
hyphenated `ltx-2.5-*` repo path).

Bumped the module docstring's stale method-count claim: `75 as of
2026-10-16` → `78 as of 2026-11-04`. Verified against
`python -c "import ast; p='comfyui-spellcaster/spellcaster_core/workflows.py'; print(sum(1 for n in ast.walk(ast.parse(open(p).read())) if isinstance(n, ast.FunctionDef) and n.name.startswith('build_')))"`.

**Verification of T1-a through T1-c**

- `pytest tests/` — `57 passed in 7.00s`.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0   MISSING: 0`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same shape
  as before the arch-query map expansion (4 proposals from 5 backends).
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  the manifest on disk was already in sync with the registry, no diff
  to commit.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **unsloth/flux-3-image-klein-GGUF** | 2026-10-16 | GGUF path for the already-registered `flux3klein` arch (12-GB tier) | ~5–7 GB (Q4_K_M), ~8 GB (Q6_K) | low | 2 | 209K downloads / 46 likes. The quantized companion to the `black-forest-labs/flux-3-image-klein-comfy` repo. Since `_reg("flux3klein", ...)` is already in the registry (architectures.py:813), the GGUF file drops straight into the existing arch — no new `_reg()` call, just a choice of weights file for the 12-GB tier. Pairs with `unsloth/flux-3-image-klein-FP8` (200K dl, 6 likes) for the 16-GB tier. |
| **Comfy-Org/sam3.1** | 2026-04-14 | Drop-in for `build_sam3_segment` (`workflows.py`) that the 2026-10-16 digest left as a weights-audit question | ~2 GB | low | 2 | **862K downloads** / 120 likes — the ComfyUI-single-file repackage of `facebook/sam3.1`. This resolves the Tier-2 uncertainty from the 2026-10-16 digest: with a ready-made `diffusion-single-file` repackage, the SAM3 node no longer needs a custom node-pack update; the operator just drops this into `ComfyUI/models/sams/`. Still a weights-only swap if the SAM3Segment node accepts the 3.1 shape at the same path — the audit entry in Tier 3 below still holds, but the path forward is now unblocked. |
| **abenzerps/Qwen-Image-2.1-Turbo-Quantized** | 2026-09-20 | GGUF/FP8/NVFP4 pack for `qwen_image` arch (which is now fully-registered, line 911) | ~6–10 GB (FP8), ~5 GB (Q4_K_M GGUF) | low | 2 | **305.9K downloads / 5,645 likes** — this is the dominant open-weight Qwen-Image-2.1-Turbo distribution (vs. the 17K-download base repo). Multi-format pack (GGUF, FP8, NVFP4) — covers 12-GB, 16-GB, and NVFP4 (Spark) tiers in one. Since `_reg("qwen_image", ...)` landed since the last digest, this is the natural follow-up download. |
| **Pika-Labs/Pika-H3-Flex-Turbo-LoRA** | 2026-10-29 | 2-/4-/8-step Turbo LoRA on the already-registered `minimax_h3` arch | ~0.5 GB (adapter) | low | 2 | 43.1K downloads / 137 likes. Turbo-step LoRA for `_reg("minimax_h3", ...)` — the base arch's `default_steps=8`, this LoRA unlocks 2/4-step fast paths. Published by Pika Labs; base model is `Iwannapose/minimax_h3_pdmd_2nfe_comfyui`. Would land as a calibration entry in `lora_calibrations_sfw.json` + a `build_minimax_h3_fast_i2v` variant. |
| **Pika-Labs/Pika-H3-Flex** | 2026-10-29 | LoRA-level extension on `minimax_h3` arch | ~0.5 GB (adapter) | medium | 2 | 749 downloads / 419 likes (very high like-to-download ratio = brand-new, pre-mainstream). Base is `MiniMaxAI/MiniMax-H3`. Different from the Turbo LoRA — this is the quality/style adapter rather than the step-count distill. Pair-evaluate alongside the Turbo variant. |
| **speridlabs/idol** | 2026-10-29 | NEW image-to-3d arch (gaussian-splatting) — different output format from Hunyuan3D's mesh pipeline | ~3–4 GB (est.) | medium | 2 | 14.6K downloads / 577 likes. Apache-2.0 license. Gaussian-splatting output is NOT a mesh — it produces `.splat` / `.ply` files consumed by WebGL/three.js viewers rather than a traditional 3D mesh. Would land as a NEW `_reg("idol", ...)` beside `hunyuan_3d`, not as a replacement. Decision point for the operator: does the downstream fleet pipeline consume gaussian-splat output, or does it need mesh-only? |
| **LiquidAI/LFM3-1.7B-GGUF** | 2026-10-24 | LM Studio prompt-enhancer candidate for `llm_delegate.py` | ~1–2 GB (Q4_K_M GGUF) | low | 2 | 213.2K downloads / 228 likes. Multilingual 1.7B that fits in <2 GB — would slot into `llm_delegate.py`'s LM Studio hook as a lightweight prompt-enhancement option (comparable role to `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4` from the 2026-10-16 digest, but ~half the memory). Also check `LiquidAI/LFM3-Omni-2B-GGUF` (198K dl, 126 likes) if any-to-any multimodal is in scope. |
| **Lightricks/LTX-2.5** (likes update) | 2026-10-11 | Direct upgrade path for `_reg("ltx", ...)` — same filing as 2026-10-16 but likes/downloads have continued climbing | ~22 GB fp16 (22B params) | medium | 2 | **2.5M downloads / 10,576 likes** — was 1.9M / 8,035 at the 2026-10-16 digest. Confirmed dominant open-weight i2v model. If the fleet download has still not happened, this is the single highest-leverage Tier-3 action in the queue. Note `unsloth/LTX-2.5-GGUF` (229K dl, Oct 13) and `unsloth/LTX-2.5-FP8` (28.8K dl, Oct 13) are both now available for the 12-GB and 16-GB tiers respectively. |

### Tier-2 non-model finding

- **`black-forest-labs/flux-3-image-klein-comfy` now dominant.** The
  2026-10-16 digest filed Flux-3-Klein when it was at 73K downloads /
  374 likes; it is now at **1.1M downloads / 2,467 likes** — the base
  distilled repo moved from "candidate" to "de facto open-source
  Flux". Since `_reg("flux3klein", ...)` landed in the registry since
  the previous digest, the pending operator decision is now purely
  "which weights file to pull onto which host" (full `-comfy`
  single-file / GGUF / FP8 / NVFP4 — see Tier 3 below).

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-04 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: unsloth/flux-3-image-klein-GGUF
    target_host: spark2
    reason: "Flux-3-Klein GGUF path for the 12-GB tier. _reg('flux3klein', ...) is already in architectures.py (line 813) — this is just a weights-file choice. Pair with the FP8 variant below on the 16-GB host for a two-tier deploy of the same arch."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: unsloth/flux-3-image-klein-FP8
    target_host: spark1
    reason: "Flux-3-Klein FP8 path for the 16-GB tier. Same arch as the GGUF entry; this is the higher-fidelity variant. 200K downloads community confidence."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-FP8 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein-FP8"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/sam3.1
    target_host: spark1
    reason: "ComfyUI-single-file repackage of facebook/sam3.1 — 862K downloads on the Comfy-Org variant resolves the custom-node-vs-weights uncertainty from the 2026-10-16 digest. Weights-only swap for the already-wired build_sam3_segment, drop into D:\\LLM\\ComfyUI\\models\\sams\\."
    command_hint: "huggingface-cli download Comfy-Org/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sams\\sam3.1-comfy"
    risk: low

  - action: download_and_evaluate_model
    target_repo: abenzerps/Qwen-Image-2.1-Turbo-Quantized
    target_host: spark2
    reason: "Multi-format pack (GGUF, FP8, NVFP4) for the now-registered qwen_image arch. 305K downloads / 5,645 likes is the dominant distribution for Qwen-Image-2.1-Turbo. Covers 12-GB, 16-GB, and NVFP4 tiers from a single repo."
    command_hint: "huggingface-cli download abenzerps/Qwen-Image-2.1-Turbo-Quantized --include '*nvfp4*' --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1-Turbo-NVFP4"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: Pika-Labs/Pika-H3-Flex-Turbo-LoRA
    target_host: spark2
    reason: "2-/4-/8-step Turbo LoRA for the already-registered minimax_h3 arch. Adapter-size (~0.5 GB), no new base weights. Would unlock a fast-path builder on top of _reg('minimax_h3', ...)."
    command_hint: "huggingface-cli download Pika-Labs/Pika-H3-Flex-Turbo-LoRA --local-dir D:\\LLM\\ComfyUI\\models\\loras\\Pika-H3-Flex-Turbo"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: Pika-Labs/Pika-H3-Flex
    target_host: spark2
    reason: "Quality/style LoRA on minimax_h3 — different role than the Turbo LoRA above. Pre-mainstream (high like-to-download ratio) so a sampled eval first is appropriate."
    command_hint: "huggingface-cli download Pika-Labs/Pika-H3-Flex --local-dir D:\\LLM\\ComfyUI\\models\\loras\\Pika-H3-Flex"
    risk: medium

  - action: evaluate_new_arch
    target_repo: speridlabs/idol
    target_host: unknown
    reason: "NEW image-to-3d candidate (gaussian-splatting rather than mesh). Not a replacement for _reg('hunyuan_3d', ...) — different output format. Evaluate whether the downstream fleet pipeline (Theo? Prometheus?) can consume .splat / .ply gaussian-splat files, then decide whether to open a _reg('idol', ...) alongside hunyuan_3d."
    command_hint: "huggingface-cli download speridlabs/idol --local-dir D:\\LLM\\ComfyUI\\models\\idol"
    risk: medium

  - action: download_and_evaluate_llm
    target_repo: LiquidAI/LFM3-1.7B-GGUF
    target_host: spark2
    reason: "Lightweight (~1.5 GB Q4_K_M) multilingual LLM for the LM Studio prompt-enhancement slot in llm_delegate.py. Fits on 12-GB tier beside an image model. Comparable role to the 2026-10-16 digest's Qwen3-4b-Z-Image-Engineer, but ~half the memory."
    command_hint: "huggingface-cli download LiquidAI/LFM3-1.7B-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\LMStudio\\models\\LiquidAI\\LFM3-1.7B-GGUF"
    risk: low

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Full-precision Flux-3-Klein single-file for the 24-GB+ tier. _reg('flux3klein', ...) is already wired; 1.1M downloads confirms dominance. Gated=auto — needs huggingface-cli login on the fleet host once."
    command_hint: "huggingface-cli login  # once, if not already\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: spark1
    reason: "Direct upgrade path for _reg('ltx', ...). HF now shows 2.5M downloads / 10,576 likes — up from 1.9M / 8,035 three weeks ago. Confirmed dominant open-source i2v. Gated=auto; needs HF login the sandbox doesn't have. If storage-tight, pair with unsloth/LTX-2.5-GGUF (229K dl) on the 12-GB host and unsloth/LTX-2.5-FP8 (28.8K dl) on the 16-GB host instead of the full base."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background-removal adapter on top of LTX-2.5. Depends on the LTX-2.5 base weights above. ~2 GB adapter, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Video spatial upscaler adapter on LTX-2.5. Also depends on the LTX-2.5 base. ~2 GB. Pairs with the existing supir image upscaler for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet, just a path check. Precedes the Comfy-Org/sam3.1 drop-in above."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Hunyuan-3D-2.1
    target_host: spark1
    reason: "ComfyUI-repackaged drop-in for existing _reg('hunyuan_3d', ...); 118K downloads on the Comfy-Org repackage. Current build_hunyuan_3d points at 2.0-shape weights; 2.1 mesh+texture pipeline may need a node-list audit before the swap."
    command_hint: "huggingface-cli download Comfy-Org/Hunyuan-3D-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
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
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c now gives the HF arch-query map 8 extra arches to probe when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTX 2.3 and Flux-3-Klein supersedes Flux-2-Klein on disk, the older weights should be flagged for retirement. Mechanical audit: compare architectures.py registered=True set against ComfyUI/models/*. tools/audit_disk_vs_registry.py is the drafting candidate for a future Tier-1 digest."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; ~100 LOC drafting candidate for a future Tier-1 run."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **Stacked-PR backlog is back, 12 open.** The 2026-10-16 digest
   declared this resolved (the 2026-09-22 branch merged + harvested);
   the stack has since re-accumulated to 11 open ecosystem-digest
   PRs on the repo (`#192`, `#193`, `#195`–`#202`), and this PR adds
   a 12th. Recommend the operator pick one (either this one or
   `#202` from 2026-11-02 — both carry the same T1-a/T1-b/T1-c class
   of fixes against their respective baselines) to merge and close
   the rest. The routine's whole value proposition rests on the fixes
   actually reaching `main`; a 12-deep stack defeats that.

2. **`tools/audit_disk_vs_registry.py` still a Tier-3 TODO.** Named
   in prior Tier-3 queues (2026-10-16 #1) but has never been
   written. With the new Flux-3-Klein / LTX-2.5 / Qwen-Image-Turbo
   downloads queued, the retirable-weights question is only going to
   get larger. Writing it is a ~100-line Tier-1 candidate for a
   future digest; could not be shipped in this run because the fleet
   path layout (`D:\LLM\ComfyUI\models\*`) is only inferable, not
   observable, from the cloud sandbox.

3. **Transport fallback for `tools/upgrade_research.py`.** Same gap
   as prior digests — the tool's HF and civitai backends use
   `urllib`, which the cloud proxy 403s. Teaching the `huggingface`
   backend to prefer an MCP transport when one is available would
   let this routine run the ranked backend from the cloud instead of
   the skeleton one. Doable but it broadens the tool's dependency
   surface (would need an MCP client in-process or a sidecar), so
   not shipped here.

4. **`flux2klein` → `flux3klein` migration path.** The `flux3klein`
   `_reg()` entry is in since the 2026-10-16 digest. The question of
   whether to keep `flux2klein` registered (for people on the older
   weights) or retire it stays operator-decided; default style has
   been to keep older arches registered until a cleanup pass.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py
--dry-run`; AST scans of `architectures.py`, `workflows.py`,
`builders_manifest.json`; `pytest tests/`._
