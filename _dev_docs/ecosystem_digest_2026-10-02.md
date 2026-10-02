# Ecosystem digest — 2026-10-02

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-rkm7z1`.

## Delivery notes

- **Stacked-digest backlog is reopening.** The 2026-09-22 consolidation
  (`2ebdf38`) merged ten prior digests at once — great drain. Since
  then, four new ecosystem-digest PRs (`#183` 2026-09-24, `#184`
  2026-09-26, `#185` 2026-09-28, `#186` 2026-09-30) have stacked
  without merging, plus `#166` (2026-09-04) and the two older feature
  branches `#48` / `#22`. Not a code problem; the operator decides
  whether to merge one (preferred — any of them stands alone) or
  consolidate again. This digest's Tier-1 batch overlaps with #186
  (same safe, mechanical fixes against the same `ecf4249` baseline) by
  design: so merging *either* this PR or #186 moves the needle,
  without the operator having to pick the "right" one.
- **`tools/upgrade_research.py` present and green on dry-run.** 4
  demo proposals across 5 backends; output under
  `_dev_docs/upgrade_research/2026-W40.{md,json}` (ISO week W40). A
  live-backend attempt still hits the sandbox egress 403 (expected —
  Tier-3 follow-up to re-run from LAN still open).
- **Gmail / Google-Drive MCP** — not called this run; delivery is the
  PR itself.
- **CI leak-check** — green on `main` since the `#12` hooks-drift PR
  landed; this diff touches only `.gitignore`, `README.md`,
  `DEEP_DIVE.md`, two mirror-locked copies of `architectures.py`, and
  adds files under `_dev_docs/…` — no strings that match the leak
  patterns, so this PR should inherit green.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes:

- `pytest tests/` → 52/52
- `python tests/mirror_drift.py` → 29/29 byte-identical
- `python tests/night_maintenance.py --dry-mode --quiet` → exit 0
- `python tools/upgrade_research.py --dry-run` → 4 proposals / 5 backends

### T1-a `README.md`: front-page status is 2 days into the next month

The `📣 Status — September 2026` banner is the first thing a fresh
visitor sees. Today is 2026-10-02 — month-change stale. Bumped to
`📣 Status — October 2026`. The News / Focus / Next copy left as-is
(all still accurate past-tense "landed" items).

### T1-b `architectures.py` module docstring (both copies): "as of September 2026"

Both mirror-locked copies of `architectures.py` carry the module-level
docstring `SUPPORTED ARCHITECTURES (as of September 2026):`. Bumped
both to `(as of October 2026):`. Mirror-drift stays 29/29 byte-identical
because the same bump went into both files. (Downstream enumeration
list of 7 archs vs. 21 fully-registered + 6 stubs remains Tier-2 —
needs the operator's call on "shipped-enough-to-name".)

### T1-c `DEEP_DIVE.md`: "22,000 lines of Python" is ~13K stale

Line 934 (`For developers` section) says `22,000 lines of Python that
somehow work`. Line 52 (mermaid) says `~34K Python lines`. These two
numbers in the same file contradicted each other, and line 52 matches
ground truth: `find plugins/gimp/comfyui-connector/spellcaster_core
-name '*.py' | xargs wc -l` reports **35,723 lines** today. Bumped
`22,000 lines` → `~34,000 lines` so both DEEP_DIVE mentions agree. (This
fix is also in open PR #186; applying it here on top of `main` means
whichever PR merges first lands it.)

### T1-d `DEEP_DIVE.md`: `9 model architectures` lists ten

Line 936 states **"9 model architectures"** and then enumerates **10**:
`SD 1.5, SDXL, Illustrious/Pony, ZIT, Flux Dev, Flux 2 Klein (4B/9B),
Flux Kontext, Chroma, LTX, Wan`. Internally contradictory. Bumped `9`
→ `10` so the number matches the enumeration that follows. (Also in
#186.) The fully-registered-registry count (21) stays a Tier-2
docstring refresh — "developer overview families" and
"every registered arch" are two different lists and the operator
chooses which to surface in the overview.

### T1-e `.gitignore`: whitelist `tests/test_fetch_metadata.py` for consistency

`tests/*` is gitignored with an explicit whitelist (the "canonical
shared harnesses" carve-outs). `tests/test_fetch_metadata.py` was
force-added by outside-agent commit `74b0a92` but never added to the
whitelist, so the tracked file drifts from the whitelist contract.
Added `!tests/test_fetch_metadata.py` next to the other `test_*.py`
carve-outs. Zero behavior change (the file is already tracked) — this
restores the whitelist as the authoritative "what's tracked in
`tests/`" declaration. (Also in #186.)

### T1-f `.gitignore`: ignore root-level `metadata.json` artifact

`fetch_metadata.py` writes `metadata.json` at repo root on every run,
and `tests/test_fetch_metadata.py` invokes the script four times per
run. If a developer runs the tests and does `git add -A` before
tear-down finishes (or the process aborts mid-test), `metadata.json`
lands in the index — nothing in the existing root scratch patterns
catches it (`/*.png`, `/*.gif`, `/_*.json` all miss it because the
name doesn't start with `_`). Added `/metadata.json` next to the
existing root-scoped scratch patterns. Verified: `touch metadata.json
&& git status --short | grep metadata` returns empty on this branch.
(Also in #186.)

**Verification**

- `pytest tests/` → **52 passed** (baseline + this branch).
- `python tests/mirror_drift.py` → **29/29 byte-identical** (both
  architectures.py docstrings got the same bump).
- `python tests/night_maintenance.py --dry-mode --quiet` → exit **0**.
- `python tools/upgrade_research.py --dry-run` → 4 proposals / 5
  backends, output committed under
  `_dev_docs/upgrade_research/2026-W40.{md,json}`.
- `touch metadata.json && git status --short | grep metadata` →
  empty.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via HF MCP `hf_fs ls hf://models/trending` with a 25-call soft
budget (used ~2 MCP calls this run; carry-forward entries use last
digest's data).

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Qwen/Qwen-Image-2.1** | 2026-09-30 (last commit) | New `qwen_image` arch (`build_qwen_image_txt2img` + `_reg("qwen_image", …)`) | ~16 GB fp8, ~30 GB fp16 (7.1B params) | medium | 2 | **2,817 likes / 81K downloads** on base, up from 2,700 / 70K at the 2026-09-30 digest. **Comfy-Org/Qwen-Image-2.1 repack** at 5M+ downloads continues to be the deployable path. Three digests have landed this candidate at the top of their Tier-2 lists without integration — ready for the operator to green-light. |
| **Viggle/Qwen-Image-2.1-viggle-turbo** | 2026-10-01 (just-updated) | Distilled speed variant of `qwen_image` arch, parallels `sdxl`/`sdxl_turbo` split | ~16 GB fp8 | medium | 2 | **522 likes / 240K downloads** (up from 444/205K two days ago). Depends on base `qwen_image` landing first. |
| **Lightricks/LTX-2.5** | 2026-09-01 (unchanged, still trending) | Direct successor to current `ltx` arch weights (`_reg("ltx", …)` at `architectures.py:974`) | ~24 GB video | medium | 2 | **5,922 likes / 1.58M downloads** (up from 5,648 / 1.58M). Gated=auto on HF — needs LAN HF login the sandbox doesn't have. Tier-3 download action still open from 2026-09-22 digest. |
| **akatz-ai/MiniMax-H3-Character-Swap-LoRA** | 2026-09-27 | New video-to-video LoRA; could extend `wan` arch's animate path or stand up a separate `build_character_swap_video` | ~20 GB (video + LoRA on top of wan) | medium | 2 | **233 likes / 11.5K downloads** — small but trending on video-to-video (new task-type for the fleet). Would need a MiniMax-H3 base — if that lands, this is the obvious companion. Flag for the operator to decide whether to pursue a MiniMax-H3 base arch at all. |
| **abenzerps/Qwen-Image-2.1-Uncensored-GGUF** | 2026-09-28 | NSFW companion of `qwen_image`; **routes to the NSFW pipeline, NOT SFW canon** | ~10 GB Q4_K_M | medium | 2 | **2,786 likes / 1.37M downloads** (up from 2,506/1.23M). Explicitly NSFW-tagged → does NOT belong in `lora_calibrations_sfw.json`. Forwarded to the (still-notional) `tools/upgrade_research_nsfw.py` pipeline. |
| **black-forest-labs/FLUX.2-klein-4B** | ecosystem-repackage wave 2026-09-28..2026-10-01 | Half-VRAM Klein path alongside existing 9B (`_reg("flux2klein", …)`) | ~8 GB fp16 (3.87B params) | low | 2 | 3.1M+ downloads on BFL repo and multiple community repackages (GGUF, OpenVINO INT4, SGLang FP8, NPU2, RunningHubAI LoRAs). `DEEP_DIVE.md` already anticipates it (`Flux 2 Klein (4B/9B)`). Would land as a second checkpoint slot with `< 12 GB → 4B, else 9B` VRAM triage. |

### Tier-2 non-model finding (carried from 2026-09-22)

- **`architectures.py` module docstring refresh** — static enumeration
  lists 7 archs; registry has 21 fully-registered + 6 stubs
  (AST-confirmed this run). Static list should either be regenerated
  from `ARCHITECTURES` at doc-build time or hand-updated to mention the
  21 fully-registered. The split between "shipped user-facing" vs.
  "wired-but-not-exposed" is the operator's call, so this stays Tier-2.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carrying forward every unfulfilled entry from the 2026-09-22 and
2026-09-30 digests — none of these have landed a "done" signal
reaching this cloud sandbox. New entry: a Viggle-turbo evaluate hook,
contingent on the base Qwen landing.

```yaml
local_action_queue:
  # ---- NEW THIS RUN ----

  - action: download_and_evaluate_model
    target_repo: Viggle/Qwen-Image-2.1-viggle-turbo
    target_host: unknown
    reason: "Distilled speed variant of Qwen-Image-2.1; parallels sdxl/sdxl_turbo. Only useful AFTER the base qwen_image lands via one of the earlier Tier-3 downloads (Comfy-Org/Qwen-Image-2.1). 522 likes / 240K downloads and climbing."
    command_hint: "huggingface-cli download Viggle/Qwen-Image-2.1-viggle-turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1-viggle-turbo"
    risk: medium

  # ---- CARRIED FORWARD (no completion signal reaching cloud) ----

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "New arch candidate (Tier-2); Comfy-Org single-file repack lands directly in ComfyUI/models/checkpoints/. Still trending (5M+ downloads on the repack vs 1.4M on 2026-09-22). Evaluate against SDXL/Flux2Klein routes for text-to-image quality before wiring _reg('qwen_image', ...)."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/FLUX.2-klein-4B
    target_host: spark2
    reason: "Half-VRAM Klein path. Lets 8-GB cards run build_klein_* families that currently need >= 12 GB. Ecosystem repackage wave (OpenVINO INT4, SGLang FP8, NPU2, GGUF) landed in the 2026-09-28..10-01 window."
    command_hint: "huggingface-cli download black-forest-labs/FLUX.2-klein-4B --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\FLUX.2-klein-4B --local-dir-use-symlinks False"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: trmz/flux2-klein-alpha
    target_host: spark2
    reason: "RGBA / transparency LoRA for flux2klein -- generates transparent-background images without a separate rembg pass. Small (~200 MB). Would slot into a new build_klein_rgba tool or as an option flag on build_klein_generate."
    command_hint: "huggingface-cli download trmz/flux2-klein-alpha --include '*.safetensors' --local-dir D:\\LLM\\ComfyUI\\models\\loras\\flux2-klein-alpha"
    risk: low

  - action: nsfw_pipeline_handoff
    target_repo: abenzerps/Qwen-Image-2.1-Uncensored-GGUF
    target_host: unknown
    reason: "NSFW variant of Qwen-Image-2.1 (2,786 likes / 1.37M downloads). Does NOT belong in SFW canon. Forward to the spellcaster_NSFW pipeline's own upgrade tool (tools/upgrade_research_nsfw.py per the docstring in tools/upgrade_research.py) when that tool exists."
    command_hint: "# no download from SFW fleet; forward this candidate to the NSFW pipeline"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...); now 5,922 likes / 1.58M downloads. Gated=auto -- needs an HF login the cloud sandbox doesn't have, so this is fleet-only."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: QuantStack/Wan2.2-I2V-A14B-GGUF
    target_host: spark1
    reason: "VRAM-saver GGUF swap for existing wan arch's build_wan_video I2V path. Unlocks 12-GB cards that currently fall back to slower routes."
    command_hint: "huggingface-cli download QuantStack/Wan2.2-I2V-A14B-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Wan2.2-I2V-A14B-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for existing _reg('hunyuan_3d', ...); the current build_hunyuan_3d workflow points at 2.0-shape weights, and the 2.1 mesh+texture pipeline may need node-list audit before the swap ships."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Enables build_controlnet_gen on the zit arch (currently an empty cn list). 4-step distill means CN'd gens stay under 1s. Small download (~500 MB)."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Sandbox proxy denies HF and civitai CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode (--dry-run demo candidates). Running from LAN (spark1 or dev host) exercises the real HF + civitai backends."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index --methods build_illustrious_txt2img,build_wan_video,build_klein_repose"
    risk: low
```

## Follow-ups filed as future Tier-1 / Tier-2 candidates

Items I saw but did not fix in this run — either scope-larger-than-safe,
or ambiguous enough to want the operator's read first.

1. **`fetch_metadata.py` is a hardcoded outside-agent leftover.** It
   targets `REPO_OWNER = "golang"` / `REPO_NAME = "go"` with a
   commented-in note that the true intended target doesn't exist. The
   file also bypasses the new `safe_fetch` allowlist (Issue #14 /
   commit `cd01ad2`) — uses raw `urllib.request` directly to
   `api.github.com`. Two paths: remove the script + its test (verified
   no in-repo consumer of its `metadata.json` output), OR migrate it to
   `safe_fetch.safe_get`. Operator's call — flagged every digest since
   2026-09-22 and still open.

2. **`tools/upgrade_research.py` transport fallback** (carried from
   2026-09-22). HF and civitai backends use stdlib `urllib`, which the
   sandbox proxy 403s. Teaching the tool to prefer the HF MCP
   transport when available would let this routine run the *real*
   backend from the cloud instead of the skeleton one. Not shipped
   because it broadens the tool's dependency surface beyond stdlib.

3. **Tool-count consistency in `assets/showcase.gif` render** (carried
   from 2026-09-22) — the README/DEEP_DIVE say `75`, but the
   `generate_showcase.py` render may still emit labels from a
   hardcoded count. Not verified — would need to run the generator
   locally to see what surface it exposes.

4. **DEEP_DIVE.md fully-registered arch enumeration** (carried from
   2026-09-30 digest / #186). Developer-section line now reads "10
   model architectures" after T1-d, but the registry has 21
   fully-registered. Whether to expand that list is the operator's
   call because the split between "shipped user-facing" and "wired
   but experimental" needs the operator's read.

5. **Stacked-PR backlog decision.** Six open ecosystem-digest PRs
   (`#166`, `#183`, `#184`, `#185`, `#186`, this one if it opens).
   Options:
   - Merge any ONE (they all stand alone against the same baseline).
   - Consolidate again, mirroring the `2ebdf38` pattern.
   - Explicitly pause the every-48h schedule until the review queue
     drains.
   Not a code decision — flagged for the operator.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hf_fs ls hf://models/trending`;
local `tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`; local mirror-drift + full pytest
sweep (52/52) + night_maintenance dry-mode smoke (exit 0)._
