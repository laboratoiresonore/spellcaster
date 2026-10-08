# Ecosystem digest — 2026-10-08

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-a36rq8`.

## Delivery notes

- **Stacked-PR backlog unchanged** — PRs #166, #183, #184, #185, #186,
  #187, #188, #189 are all **still open and unmerged**. This is the
  eighth consecutive 48-hour cycle piling an ecosystem digest on top of
  `main` with no merge in between. Every digest's Tier-1 fixes have
  overlapped with the prior digests (same drift surface, different
  authors re-touching the same lines in `README.md` / `DEEP_DIVE.md` /
  `architectures.py`). Operator decision requested: pick one open PR to
  merge and close the rest as duplicate, **or** pause the every-48h
  cadence until the queue drains. The cadence is generating faster than
  review is draining and this run isn't going to help that until the
  pattern breaks.
- **Gmail / Google-Drive MCP** — not called this run; this PR is the
  sole delivery channel.
- **`tools/upgrade_research.py` ran clean** — 4 proposals from 5
  backends. Fresh `_dev_docs/upgrade_research/2026-W41.{md,json}`
  committed. The HF/civitai live backends still 403 behind the sandbox
  egress proxy, so the ranked proposal list is the stub skeleton;
  Tier-2 model intel below comes from Hugging-Face MCP (`hf_fs ls`,
  `hub_repo_search`, `hub_repo_details`) which routes through a different
  transport that the sandbox proxy allows.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/`
→ 52/52).

### T1-a `README.md:46`: front-page status is one month stale

The `📣 Status — September 2026` banner is first thing a fresh visitor
sees. Today is 2026-10-08 — one month late. Bumped to `📣 Status —
October 2026`. (Overlaps with the identical edit in PRs #186, #187,
#188, #189; this branch stands alone against `main`.)

### T1-b `architectures.py` (both mirrors): docstring date is one month stale

Both mirror copies — `plugins/gimp/comfyui-connector/spellcaster_core/`
and `comfyui-spellcaster/spellcaster_core/` — carry the module-level
docstring `SUPPORTED ARCHITECTURES (as of September 2026):`. Bumped
both to `(as of October 2026):` and kept the two files byte-identical
(`python tests/mirror_drift.py --quiet` → exit 0). (Overlaps with
PRs #187, #188, #189.)

### T1-c `DEEP_DIVE.md:922`: ArchConfig registry count is 12 low

The description currently reads `**9-architecture ArchConfig
registry**`. AST walk over `_reg(...)` calls in
`plugins/gimp/comfyui-connector/spellcaster_core/architectures.py`
counts **27 total = 21 fully-active (`registered=True`) + 6 stubs
(`registered=False`)**. Bumped to `**21-architecture ArchConfig
registry** ... 21 fully-active archs plus 6 stub registrations marked
`registered=False` (27 `_reg(...)` entries total)` to resolve the
apparent conflict with the mermaid at `DEEP_DIVE.md:64` (`27 arch
registry`) by making the stub distinction explicit, instead of just
echoing the raw count.

Correction to prior digest state: PR #189's claim that today's HEAD
has "zero `registered=False`" is wrong. AST walk returns 6 stubs
(`sdxl_turbo`, `pony`, `playground`, `sd3`, `sd3_turbo`,
`hunyuan_dit`). The `21-architecture (+ 6 stubs)` phrasing from PRs
#183 / #188 is the current-truth version.

### T1-d `DEEP_DIVE.md:934`: Python line-count is 13K+ low

Reads `Only 22,000 lines of Python that somehow work`. Ground truth
(`wc -l` on `plugins/gimp/comfyui-connector/spellcaster_core/*.py`)
is **35,723** today. Bumped to `~35,700 lines`. The mermaid at
`DEEP_DIVE.md:52` already reads `~34K` — this fix closes the inline
discrepancy between the two mentions.

### T1-e `DEEP_DIVE.md:936`: model-architecture enumeration count is off-by-one

Reads `**9 model architectures**: SD 1.5, SDXL, Illustrious/Pony, ZIT,
Flux Dev, Flux 2 Klein (4B/9B), Flux Kontext, Chroma, LTX, Wan`. The
list that follows the colon enumerates **ten** items; the leading
count was off-by-one. Bumped to `**10 model architectures**`.
(Overlaps with the same edit in PRs #185, #186, #188.)

### Verification

- `pytest tests/` — `52 passed in 9.04s` on this branch, same as
  baseline `ecf4249`. No regression.
- `python tests/mirror_drift.py --quiet` — exit `0`, both
  `architectures.py` copies byte-identical.
- `python tests/night_maintenance.py --dry-mode --quiet` — exit `0`.
- `python tools/upgrade_research.py --dry-run` — clean, `4 proposals
  from 5 backends`.
- AST-parsed both edited `.py` files to confirm no syntax breakage.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP `hf_fs ls hf://models/trending` +
targeted `hub_repo_search` + `hub_repo_details` (used ~5 MCP calls of
the 25-call soft budget). Deltas vs the 2026-09-22 digest are called
out where the signal has moved.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Qwen/Qwen-Image-Edit-2511** | 2025-12-23 (last modified) | **Supersedes** the 2509 variant flagged in the 2026-09-22 digest; alt to `flux_kontext` for `build_edit_by_instruction` | ~20.4B params (fp8 ~20 GB) | medium | 2 | **2.0M downloads / 1450 likes / 100+ demo Spaces** — now the dominant edit-by-instruction route. Spawned the BFS-Best-Face-Swap LoRA ecosystem (see next row). Live on `fal-ai` + `wavespeed` inference providers, meaning Spellcaster could expose a `qwen_edit_backend=remote` opt-in alongside the local path. |
| **Alissonerdx/BFS-Best-Face-Swap** | 2025-11-07 (created), 2026-09-27 (last mod) | New faceswap route for `build_faceswap_*` family on top of Qwen-Image-Edit-2511 | ~20 GB (base) + small LoRA | medium | 2 | **1,315 likes / 243K downloads** on the main repo, with ~9 community forks (`Bhavu02`, `ItBitter`, `sisniha`, `thornmaze`, `nancy12345melon`, `chfm`, `justusgeorge10`, …) all mirroring the same recipe. Would land as a new `qwen_edit`-backed path on `build_faceswap_mtb` / `build_save_face_model`, controlled by a `faceswap_backend` setting. The community uniformly uses the Qwen-Image-Edit-2511 base — operator-decision whether to retire the current reactor-based path. |
| **Lightricks/LTX-2.5** | 2026-10-02 (last modified) | **Still** the direct successor to the current `ltx` arch (which points at LTXV-2.3) | ~24 GB video | medium | 2 | **6,887 likes / 3.4M downloads / 54+ demo Spaces** — up from 4,738 likes / 1.6M downloads at the 2026-09-22 digest and 6,232 / 1.63M at the 2026-10-04 digest. Multimodal signatures now explicit on the tag list (`image-to-video`, `text-to-video`, `video-to-video`, `audio-to-video`, `text-to-audio`, `video-to-audio`, `audio-to-audio`). Still `gated=auto` on HF — fleet-only download. |
| **Qwen/Qwen-Image-2.1** (base) | 2026-09-30 (last modified) | New `qwen_image` arch — no current coverage | ~16 GB fp8 (7.1B params) | medium | 2 | **3,118 likes / 117K downloads on the base**; the `Comfy-Org/Qwen-Image-2.1` repackage (1.4M → 3.6M → still climbing) remains the preferred integration surface. 100+ demo Spaces including Viggle turbo distill, outpaint, "multiple-angles-3d-camera" research prototypes — momentum has broadened not narrowed since the first flagging on 2026-09-22. |
| **abenzerps/Qwen-Image-2.1-Uncensored-GGUF** | 2026-09-28 (last modified) | Low-VRAM NSFW companion for the Qwen-Image-2.1 arch | ~10 GB Q4_K_M | low (NSFW-flagged) | 2 | **3,652 likes / 1.9M downloads** — up from 968 / 182K at the 2026-09-22 digest. Dominant practical variant on the GGUF path. **Explicitly flagged for hand-off to `spellcaster_NSFW` per the H6 SFW-canon rule — this entry is a hand-off reminder, not a public-repo integration recommendation.** |
| **MiniMaxAI / MiniMax-H3 family** | 2026-09 onward | New video arch not in the current `_reg` set | ~24 GB+ fp8 | high | 2 | Flagged in digests #184, #186 and #189 (5,691 → 9.8M downloads trajectory). Still deserves its own `_reg("minimax_h3", …)` slot pending LAN VRAM / quality eval. Carried forward because no completion signal has reached the sandbox. |
| **google/embeddinggemma-2** | 2026-10-06 | Potential swap for the local prompt-enhancer embedding step | ~300 MB | low | 2 | **1,128 likes / 21K downloads** in the last 48h. Tiny model, used downstream by the morning-briefing / Guild chat flows that call into `tools/llm_morning_briefing.py`. Would land as a configurable embedding backend; not a core-image-path change. |

### Tier-2 non-model finding

- **Qwen-Image-Edit-2511 is already an opt-in in PR #48 (`qwen_edit_version="2511"`
  on `build_qwen_edit`).** The 2.0M-download / 1450-like trajectory on
  HF today is the signal to actually operationalize that opt-in: wire
  it as the default and promote the BFS-Best-Face-Swap LoRA into the
  `build_faceswap_*` route. Entry point: PR #48 is open since 2026-05;
  revisiting it against today's HEAD would convert that one PR into a
  real shipped integration instead of a 5-month-stale opt-in scaffold.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Structured entries below. A local Hermes / operator process consumes
this block mechanically instead of a human re-deriving the command
from prose. Every `command_hint` is best-effort — the operator adjusts
for the fleet's exact model directory layout.

```yaml
local_action_queue:
  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-Edit-2511
    target_host: spark1
    reason: "Supersedes the Qwen-Image-Edit-2509 variant flagged in the 2026-09-22 digest. 2.0M downloads / 1450 likes with ~100 demo Spaces; now dominant edit-by-instruction. Evaluate as default for build_edit_by_instruction and build_qwen_edit (the latter already has qwen_edit_version='2511' opt-in in PR #48)."
    command_hint: "huggingface-cli download Qwen/Qwen-Image-Edit-2511 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-Edit-2511 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_lora
    target_repo: Alissonerdx/BFS-Best-Face-Swap
    target_host: spark1
    reason: "243K downloads / 1315 likes on the main repo, ~9 community mirrors all using the same Qwen-Image-Edit-2511 recipe. Would add a 'qwen_edit' backend to build_faceswap_mtb / build_save_face_model; may let us retire the reactor path if quality is at least on par."
    command_hint: "huggingface-cli download Alissonerdx/BFS-Best-Face-Swap --local-dir D:\\LLM\\ComfyUI\\models\\loras\\BFS-Best-Face-Swap"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "6887 likes / 3.4M downloads (up from 1.6M at 2026-09-22) — direct upgrade path for _reg('ltx', ...); the current LTXV-2.3-shape weights on disk should be retired if 2.5 produces better temporal coherence at same VRAM. Gated=auto on HF — needs an HF login the cloud sandbox doesn't have, so this is fleet-only. CARRY-OVER from 2026-09-22 — still no completion signal."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Carry-over from 2026-09-22. Comfy-Org single-file repackage lands directly in ComfyUI/models/checkpoints/ with no diffusers-pipeline plumbing. Evaluate against existing SDXL/Flux2Klein routes for text-to-image quality before wiring _reg('qwen_image', ...)."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: hand_off_to_nsfw_pipeline
    target_repo: abenzerps/Qwen-Image-2.1-Uncensored-GGUF
    target_host: unknown
    reason: "3652 likes / 1.9M downloads. NSFW-tagged — per H6 SFW-canon rule this stays out of the public spellcaster repo. If the NSFW pipeline wants a low-VRAM Qwen-Image-2.1 route, this is the dominant community pick."
    command_hint: "# forward to spellcaster_NSFW maintenance queue; do NOT add to the public spellcaster repo"
    risk: low

  - action: evaluate_embedding_backend
    target_repo: google/embeddinggemma-2
    target_host: spark2
    reason: "1128 likes / 21K downloads in last 48h. Tiny (~300MB) replacement candidate for the embedding step in tools/llm_morning_briefing.py / Guild chat. Not a core-image-path change; safe to A/B against the existing embedding backend."
    command_hint: "huggingface-cli download google/embeddinggemma-2 --local-dir D:\\LLM\\embeddings\\embeddinggemma-2"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "The cloud sandbox's egress proxy denies direct HF and civitai CONNECT (403), so tools/upgrade_research.py's live backends still fall back to skeleton mode (--dry-run: 4 stub proposals). Running the same tool from the LAN (spark1 or the dev host) will exercise the real HF + civitai backends and produce the ranked shopping list this run couldn't. CARRY-OVER from 2026-09-22 — still unresolved."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index --methods build_illustrious_txt2img,build_wan_video,build_klein_repose"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If Qwen-Image-Edit-2511 lands as the default and LTX-2.5 replaces LTXV-2.3, the older weights on D:\\LLM should be flagged for retirement to free space. CARRY-OVER from 2026-09-22 — still unresolved."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; see Follow-ups below."
    risk: low

  - action: revisit_pr_48
    target_repo: null
    target_host: dev-host
    reason: "PR #48 (open since 2026-05-19) carries the qwen_edit_version='2511' + HunyuanVideo-1.5 + SAM 3.1 opt-ins against a 2026-05 baseline. HF now shows Qwen-Image-Edit-2511 at 2.0M downloads — the opt-in's underlying weight is the dominant edit model today. Rebase against today's HEAD, promote qwen_edit_version='2511' to default, and merge."
    command_hint: "gh pr checkout 48 && git rebase origin/main && python tests/mirror_drift.py && gh pr ready 48"
    risk: medium
```

## Follow-ups filed as future Tier-1 candidates

1. **Stacked-PR drain decision** (highest priority) — eight open
   digest PRs (#166, #183, #184, #185, #186, #187, #188, #189) all
   touching overlapping subsets of the same `README.md` + `DEEP_DIVE.md`
   + `architectures.py` surface. Operator picks a merge/close policy
   or the queue keeps growing.

2. **`tools/upgrade_research.py` transport fallback** (carry-over from
   2026-09-22) — the HF and civitai backends use stdlib `urllib`,
   which the sandbox proxy 403s at CONNECT time. Teaching the tool to
   prefer an HF MCP transport when one is available would let this
   routine run the real backend from the cloud. Still not shipped.

3. **PR #48 operationalization** — the SOTA-opt-ins PR has been open
   since 2026-05 with Qwen-Image-Edit-2511, HunyuanVideo-1.5 and
   SAM 3.1 as opt-ins. The underlying Qwen-Image-Edit-2511 weight is
   now the dominant edit model on HF (2M downloads). Promoting the
   opt-in to default would be the single highest-impact outcome of
   the next cycle. Filed as Tier-3 action above.

4. **BFS-Best-Face-Swap integration spike** — enables Qwen-Image-Edit-2511-
   backed faceswap, potentially retiring the current reactor path.
   Would land as a `faceswap_backend` setting on `build_faceswap_mtb`
   / `build_save_face_model`. Fleet-side download gates the eval; see
   Tier-3 queue.

5. **DEPENDENCIES.md regeneration** — not touched this run; worth a
   future audit pass after Qwen-Image-Edit-2511 lands as default
   (new node dependencies likely).

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`; local `tools/upgrade_research.py
--dry-run`; git AST scans of `architectures.py`, `workflows.py`,
`builders_manifest.json`; `wc -l` on `plugins/gimp/comfyui-connector/
spellcaster_core/*.py`._
