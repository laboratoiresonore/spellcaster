# Ecosystem digest — 2026-09-30

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-k8ly7q`.

## Delivery notes

- **Prior digest landed** — the 2026-09-22 digest (`2ebdf38 chore:
  consolidated 2026-09-22 ecosystem digest + 10 stacked-PR harvest`) is
  now on `main`, along with three follow-up security PRs (`#12` hooks
  drift-gate, `#14` safe_fetch allowlist, `#181` LLM ground-truth
  manifest). All six Tier-1 fixes from that digest (`T1-a` through
  `T1-f`) shipped intact; this run builds on that green baseline.
- **Leak-check now GREEN on main** — was red in the 2026-09-22 report;
  the intervening `#12` hooks-drift PR fixed it (the leak-check
  workflow now shares the pattern list with pre-commit + pre-push via
  `.githooks/leak-patterns`, and the self-exclusion list is
  authoritative). Locally verified: `git grep -nIEi $(patterns) --
  :!.github/workflows/leak-check.yml :!.githooks/pre-push
  :!.githooks/leak-patterns` returns empty on this branch.
- **`tools/upgrade_research.py` present** — no need to draft a
  replacement; the tool exists and `--dry-run` completes cleanly (4
  proposals across 5 backends, this ISO week's output at
  `_dev_docs/upgrade_research/2026-W40.{md,json}`). Live-backend calls
  still hit the sandbox egress 403 (Tier-3 follow-up).
- **Gmail / Google-Drive MCP** — not called this run; digest is
  delivered as the PR itself.
- **CI leak-check on this PR** — expected green; the T1 diff below
  changes only `.gitignore`, `DEEP_DIVE.md`, and adds a new
  `_dev_docs/…` file — no strings that would match the leak patterns.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
52/52, `python tests/mirror_drift.py` → 29/29 byte-identical,
`python tests/builders_manifest_drift.py` → manifest fresh at 75
methods).

### T1-a `DEEP_DIVE.md`: developer-section arch-count off-by-one

Line 936 states **"9 model architectures"** and then lists **10**:
`SD 1.5, SDXL, Illustrious/Pony, ZIT, Flux Dev, Flux 2 Klein (4B/9B),
Flux Kontext, Chroma, LTX, Wan`. Internally contradictory. Bumped `9` →
`10` so the number matches the enumeration that follows.

Left the fully-registered arch count (21 in `architectures.py`) as-is
here — the "developer overview" line reflects the *high-touch shipped*
family list, not every registered arch. Downgrading the fuller docstring
refresh (see the 2026-09-22 digest's Tier-2 non-model finding) to
another Tier-2 pass again.

### T1-b `DEEP_DIVE.md`: "22,000 lines of Python" is stale (~13,700 short)

Line 934 says `22,000 lines of Python that somehow work`. Line 52
(mermaid diagram) says `~34K Python lines`. The two DEEP_DIVE.md
statements contradicted each other, and line 52 matched ground truth:
`find plugins/gimp/comfyui-connector/spellcaster_core -name '*.py' |
xargs wc -l` today reports **35,723 lines** in the canonical surface.
Bumped `22,000 lines` → `~34,000 lines` so both DEEP_DIVE mentions
agree and neither is misleading.

### T1-c `.gitignore`: whitelist `tests/test_fetch_metadata.py` for consistency

`tests/*` is gitignored with a manual whitelist ("carve-outs: canonical
shared harnesses"). `tests/test_fetch_metadata.py` was force-added by
the 2026-09-14 outside-agent commit `74b0a92 Add GitHub repo metadata
fetcher for flux2-dev-quantized-rtx-4090` but never added to the
whitelist, so the tracked file drifts from the whitelist contract. Added
`!tests/test_fetch_metadata.py` next to the other `test_*.py`
carve-outs. Zero behavior change (the file was already tracked) — this
just restores the whitelist as the authoritative "what's tracked in
`tests/`" declaration.

### T1-d `.gitignore`: ignore `metadata.json` root-level artifact

`fetch_metadata.py` writes `metadata.json` at repo root on every run,
and `tests/test_fetch_metadata.py` invokes the script four times per
run (before tear-down). If a developer runs the tests and does `git add
-A` before the tear-down finishes (or the process aborts mid-test),
`metadata.json` lands in the index — nothing in the existing gitignore
patterns catches it (`/*.png`, `/*.gif`, `/_*.json` all miss it because
the name doesn't start with `_`). Added `/metadata.json` next to the
existing root-scoped scratch patterns. Locally verified: `touch
metadata.json && git status --short` now hides the file.

**Verification of T1-a through T1-d**

- `pytest tests/` — 52 passed on this branch (was 52/52 on baseline,
  no regression).
- `python tests/mirror_drift.py` — 29/29 byte-identical.
- `python tests/builders_manifest_drift.py` — manifest fresh (75
  methods).
- `python tools/upgrade_research.py --dry-run` — 4 proposals from 5
  backends, output at `_dev_docs/upgrade_research/2026-W40.{md,json}`.
- Leak-check pattern scan — clean on this branch.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP `hf_fs ls hf://models/trending` and
targeted `hub_repo_search`, budget-capped (used ~7 MCP calls of the
25-call soft budget). New / repositioned since the 2026-09-22 sweep:

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **black-forest-labs/FLUX.2-klein-4B** | 2026-02-24 (base repo); ecosystem-repackage wave 2026-09-28..30 | Straight VRAM-saver for existing `flux2klein` arch (currently 9B-only) | ~8 GB fp16 (3.87 B params, ~half the 9B path) | low | 2 | **3.1M downloads, 990 likes** on the base BFL repo and an ecosystem repackage explosion in the last 48h — `JoyFusionAI/gguf-flux2-klein-4b`, `HelloSun/FLUX.2-klein-4B-OpenVINO-INT4`, `Fractalyze/flux2-klein-base-4b-rtx5090` (SGLang FP8 for RTX 5090), `Cyronius/FLUX.2-klein-4B-NPU2`, plus multiple `RunningHubAI/rh-flux2-klein*` LoRA adapters. DEEP_DIVE.md line 936 already anticipates it (`Flux 2 Klein (4B/9B)`). Would land as a second checkpoint slot under `_reg("flux2klein", …)` with a VRAM-triage rule ("< 12 GB → 4B, else 9B"). |
| **abenzerps/Qwen-Image-2.1-Uncensored-GGUF** | 2026-09-28 | Same slot as the 2026-09-22 digest's `Qwen-Image-2.1` line, but SFW-canon-relevant only via the NSFW pipeline | ~10 GB Q4_K_M | medium | 2 | 2,506 likes, **1.23M downloads** in ~48h. **NSFW-tagged**, so does NOT land in `spellcaster_core` (which reads `lora_calibrations_sfw.json` only). Flag for the NSFW pipeline's own upgrade tool (`tools/upgrade_research_nsfw.py` per `tools/upgrade_research.py`'s docstring — noted as future work). |
| **Qwen/Qwen-Image-2.1** | 2026-09-30 (last commit today) | Same as 2026-09-22 digest's entry, updated numbers | ~16 GB fp8 | medium | 2 | Now **2,700 likes / 70K downloads on base repo** (was 1,701/16K last digest), and **`Comfy-Org/Qwen-Image-2.1` at 864 likes / 5.03M downloads** (was 1.4M). Trending upward; the community has clearly settled on this as the Qwen-native text-to-image path. Same integration plan as before — new `_reg("qwen_image", …)` + `build_qwen_image_txt2img`. |
| **Viggle/Qwen-Image-2.1-viggle-turbo** | 2026-09-25 | Distilled speed variant of the same arch | ~16 GB fp8 | medium | 2 | 444 likes / 205K downloads. If `qwen_image` lands, this is a candidate for a `qwen_image_turbo` step-reduction path (parallels the existing `sdxl` / `sdxl_turbo` split). Defer until base lands. |
| **trmz/flux2-klein-alpha** | 2026-09-29 | RGBA / background-removal LoRA for `flux2klein` | ~9 GB (loads onto base 9B) | low | 2 | 8 likes but LoRA-shape — small download (~200 MB). Would slot into `WAN_EXTRA_METHODS`-style extra-methods list under the `flux2klein` arch. Interesting because it does transparent-output generation on Klein without a separate rembg step. |
| **Lightricks/LTX-2.5** | 2026-09-01 (unchanged from prior digest) | Direct successor to current `ltx` arch weights | ~24 GB video | medium | 2 | Still on trending (5,648 likes / 1.6M downloads — up from 4,738/1.6M). Gated=auto — needs LAN HF login. Prior digest's Tier-3 download-and-evaluate action still open in the local queue. |

### Tier-2 non-model finding (carried from 2026-09-22)

- **Docstring-content refresh** (still Tier-2) — `architectures.py`
  module docstring lists only 7 archs but the registry now has 21
  fully-registered + 6 stubs. The 2026-09-22 digest's Tier-2 note
  identified `kolors` as fully-registered — verified by AST this run,
  `kolors` is actually a **stub** (`registered=False`). Prior 21/6 count
  stands, but the specific fully-registered list should be sourced from
  the AST, not the digest — noting the earlier error here for the
  record. Full audited list:
  - **Fully registered (21):** `sd15`, `sdxl`, `illustrious`, `zit`,
    `flux1dev`, `chroma`, `flux2klein`, `flux_kontext`, `sdxl_turbo`,
    `pony`, `playground`, `wan`, `ltx`, `seedvr`, `cogvideo`,
    `framepack`, `hunyuan_video`, `mochi`, `hunyuan_3d`, `lumina2`,
    `supir`.
  - **Stub (6):** `sd3`, `sd3_turbo`, `hunyuan_dit`, `pixart`,
    `auraflow`, `kolors`.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Structured entries below. A local Hermes / operator process consumes
this block mechanically instead of a human re-deriving the command from
prose. Every `command_hint` is best-effort — the operator adjusts for
the fleet's exact model directory layout. Entries mostly *carry
forward* from the 2026-09-22 digest since none of those actions have a
"done" signal reaching this cloud sandbox yet; new entries below the
carry-forward header.

```yaml
local_action_queue:
  # ---- NEW THIS RUN ----

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/FLUX.2-klein-4B
    target_host: spark2
    reason: "New Tier-2: half-VRAM Klein path (3.87B params vs current 9B). Would let 8-GB cards run build_klein_* families that currently need >= 12 GB. Base BFL repo is 3.1M downloads / 990 likes; multiple community repackages (GGUF for stable-diffusion.cpp / draw-things, OpenVINO INT4, NPU2, SGLang FP8, RunningHubAI LoRAs) all landed in the last 48h -- ecosystem is settling on this immediately."
    command_hint: "huggingface-cli download black-forest-labs/FLUX.2-klein-4B --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\FLUX.2-klein-4B --local-dir-use-symlinks False"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: trmz/flux2-klein-alpha
    target_host: spark2
    reason: "RGBA / transparency LoRA for the existing flux2klein arch -- generates transparent-background images without a separate rembg pass. Small (~200 MB). Would slot into a new build_klein_rgba tool if quality is good, or as an option flag on build_klein_generate."
    command_hint: "huggingface-cli download trmz/flux2-klein-alpha --include '*.safetensors' --local-dir D:\\LLM\\ComfyUI\\models\\loras\\flux2-klein-alpha"
    risk: low

  - action: nsfw_pipeline_handoff
    target_repo: abenzerps/Qwen-Image-2.1-Uncensored-GGUF
    target_host: unknown
    reason: "NSFW-tagged variant of the Qwen-Image-2.1 trending model (2,506 likes, 1.23M downloads in 48h). Does NOT belong in the SFW canon -- lora_calibrations_sfw.json wouldn't pick it up. Route to the spellcaster_NSFW pipeline's own upgrade tool (tools/upgrade_research_nsfw.py per the docstring in tools/upgrade_research.py) when that tool is built."
    command_hint: "# no download from SFW fleet; forward this candidate to the NSFW pipeline"
    risk: medium

  # ---- CARRIED FORWARD from 2026-09-22 (still no completion signal) ----

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "New arch candidate (Tier-2); Comfy-Org single-file repackage lands directly in ComfyUI/models/checkpoints/. Trend growing (5.03M downloads on the repackage today, up from 1.4M eight days ago). Evaluate against SDXL/Flux2Klein routes for text-to-image quality before wiring _reg('qwen_image', ...)."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...); 5,648 likes / 1.6M downloads on HF (still trending). Gated=auto -- needs an HF login the cloud sandbox doesn't have, so this is fleet-only."
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
    reason: "The cloud sandbox's egress proxy denies direct HF and civitai CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode (--dry-run: 4 stub proposals). Running the same tool from the LAN (spark1 or the dev host) will exercise the real HF + civitai backends and produce the ranked shopping list this run couldn't."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index --methods build_illustrious_txt2img,build_wan_video,build_klein_repose"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items I saw but did not fix in this run — either scope-larger-than-safe,
or ambiguous enough to want the operator's read first.

1. **`fetch_metadata.py` is a hardcoded outside-agent leftover.** It
   targets `REPO_OWNER = "golang"` / `REPO_NAME = "go"` with a
   commented-in explanation that says the true target
   `mikaziebelman/flux2-dev-quantized-rtx-4090` doesn't exist. The
   file also bypasses the new `spellcaster_core.safe_fetch` allowlist
   (Issue #14 / commit `cd01ad2`) — it uses raw `urllib.request` to
   hit `api.github.com`. The 2026-09-22 digest already flagged that
   the TLS-verification concern was a misreport (the script uses
   `ssl.create_default_context()`, so verification is on). Real
   candidates for a future pass:
   - Remove the script + its test (it produces no artifact used by
     anything else in the repo — verified with `grep -rn "metadata\.json"`
     and `grep -rn "fetch_metadata"` — no consumers), OR
   - Migrate it to `safe_fetch.safe_get` so it stays inside the new
     allowlist choke point.
   Flagged rather than shipped because the removal-vs-migrate call is
   the operator's.

2. **`tools/upgrade_research.py` transport fallback** (carried from
   2026-09-22, still open). HF and civitai backends use stdlib
   `urllib`, which the sandbox proxy 403s at CONNECT time. Teaching
   the tool to prefer an HF MCP transport when one is available would
   let this routine run the *real* backend from the cloud instead of
   the skeleton one. Not shipped this run because it broadens the
   tool's dependency surface beyond stdlib and adds an
   MCP-availability probe path.

3. **Tool-count consistency in `assets/showcase.gif` render** (carried
   from 2026-09-22, still open) — the README/DEEP_DIVE now say `75`,
   but the `generate_showcase.py` render may still emit labels from a
   hardcoded count. Not verified — would need to run the generator
   locally to see what surface it exposes.

4. **README status-date auto-bump** — line 46 says `📣 Status —
   September 2026`. Today is 2026-09-30, still in September. The next
   scheduled run (2026-10-02) will be the first one where this is
   stale; landing an auto-bump on that run rather than pre-emptively
   here to avoid a stale-check false positive if the operator merges
   this later.

5. **DEEP_DIVE.md fully-registered arch enumeration** — the "9
   supported" / "10 model architectures" claims (T1-a fixed the
   internal inconsistency) still undercount the real registry (21
   fully-registered). Refreshing the enumeration to reflect the
   `supir`, `mochi`, `hunyuan_video`, `hunyuan_3d`, `seedvr`,
   `cogvideo`, `framepack`, `lumina2`, `sdxl_turbo`, `playground`
   families is Tier-2 because the split between "shipped enough to
   name in the developer overview" and "wired but not user-facing"
   needs the operator's read.

6. **Backlog decision** (carried from 2026-09-22) — the 2026-09-22
   consolidated PR merged in the ten stacked PRs (`#164–#173`). Good
   drain! This is now a solved problem. If PR volume stays flat, the
   every-48h cadence is sustainable; if it climbs again, the "merge
   one, close rest as duplicate" pattern from `2ebdf38` is the escape
   valve.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hf_fs ls hf://models/trending`
and `hub_repo_search` (Qwen-Image, flux2 klein, wan 2.2, SUPIR,
illustrious); local `tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`; local
mirror-drift + builders-manifest-drift + full pytest sweep._
