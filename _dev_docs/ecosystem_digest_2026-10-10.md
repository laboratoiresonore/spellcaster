# Ecosystem digest — 2026-10-10

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `ecf4249`). Branch: `claude/adoring-allen-q4lsqi`.

## Delivery notes

- **Backlog visibility — this is PR #10 on top of nine still-open
  digests.** PRs #166, #183, #184, #185, #186, #187, #188, #189, #190
  are all open since the 2026-09-24 kanban drain, none merged. All
  three doc-drift fixes shipped here overlap with #190 (2026-10-08);
  this run's **novel** contribution is **T1-c** — a true docstring
  enumeration refresh on `architectures.py` (7 archs → 21 registered
  + 6 stubs) which no prior digest has touched. See **Operator
  decision** below.
- **Leak-check scrub** — confirmed green on today's HEAD using the
  exact `git grep -nIEi "$patterns" -- …` invocation the workflow
  runs (patterns sourced from `.githooks/leak-patterns`, with the
  three self-exclusion paths). Follow-up #1 from the 2026-09-22
  digest is **closed by `2ebdf38`**.
- **`fetch_metadata.py` TLS-verify disable** — follow-up #2 from
  2026-09-22. **Closed by `2ebdf38`.** `grep -n 'CERT_NONE\|check_hostname\|verify_mode'`
  → zero hits on today's HEAD.
- **`tools/upgrade_research.py` transport fallback** — follow-up #3.
  Partially addressed by `cd01ad2` (migrated to `safe_fetch`
  allowlist); still skeleton under `--dry-run` from this cloud
  sandbox because the proxy denies HF/civitai CONNECT and no HF-MCP
  transport is wired into the tool. Remains carried over.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **CI note** — `pytest tests/` 52/52, `tests/mirror_drift.py` 29/29,
  `tests/night_maintenance.py --dry-mode --quiet` exit 0,
  `scripts/check_arch_manifest_drift.py` clean, workflow-shaped
  leak-grep clean.

## Tier 1 — fixes applied in this commit

### T1-a `README.md:46` — status month bump

`📣 Status — September 2026` → `📣 Status — October 2026`. Today is
2026-10-10. **Also carried in #186/#187/#188/#189/#190 against the
same `main`.** If any one of those merges first, this becomes a
no-op; included here so this branch stands alone.

### T1-b `architectures.py` — module docstring date

`(as of September 2026)` → `(as of October 2026)`. Both mirror copies
(`plugins/gimp/comfyui-connector/spellcaster_core/architectures.py`
and `comfyui-spellcaster/spellcaster_core/architectures.py`) kept
byte-identical. **Also carried in #189/#190.**

### T1-c `architectures.py` — module docstring enumeration (NOVEL)

This is the main non-duplicative contribution of this run.

The module docstring's `SUPPORTED ARCHITECTURES` block has enumerated
only the original 7 image-family archs (`sd15 / sdxl / illustrious /
zit / flux1dev / flux2klein / flux_kontext`) since the pre-video
era. The actual registry on today's HEAD has **27 `_reg(...)` calls**
— **21 fully registered (`registered=True`) and 6 stubs
(`registered=False`)**. The 2026-09-22 digest flagged this as a
Tier-2 refresh pending "operator judgment on the split", but the
split is already encoded structurally in the `_reg(...)` calls
themselves (`registered=` kwarg), so refreshing the enumeration is
mechanical and matches the single source of truth.

New enumeration groups by loader shape, which matches how the rest
of the file reads:

- Image — SD/SDXL family (checkpoint loader): `sd15`, `sdxl`,
  `sdxl_turbo`, `illustrious`, `pony`, `playground`, `zit` (7)
- Image — Flux / Chroma family (`unet_clip_vae`): `flux1dev`,
  `chroma`, `flux2klein`, `flux_kontext` (4)
- Image — Other: `lumina2`, `supir` (2)
- Video — stock loaders: `wan`, `ltx`, `seedvr` (3)
- Video — custom wrappers: `cogvideo`, `framepack`, `hunyuan_video`,
  `mochi` (4)
- 3D: `hunyuan_3d` (1)
- Stubs (`registered=False`): `sd3`, `sd3_turbo`, `hunyuan_dit`,
  `pixart`, `auraflow`, `kolors` (6)

Total: **21 registered + 6 stubs = 27**, matching the AST walk and
the `grep -c '_reg\\('` count exactly. Both mirror copies received
the identical edit; `tests/mirror_drift.py --quiet` → exit 0.

### Verification

| Check | Baseline on `main` | After this branch |
|-------|-------------------|-------------------|
| `pytest tests/` | 52 passed | 52 passed |
| `tests/mirror_drift.py --quiet` | exit 0 | exit 0 |
| `tests/night_maintenance.py --dry-mode --quiet` | exit 0 | exit 0 |
| `scripts/check_arch_manifest_drift.py` | `[OK] No drift detected.` | `[OK] No drift detected.` |
| Workflow-shaped leak-grep | clean | clean |
| `tools/upgrade_research.py --dry-run` | `4 proposals from 5 backends` | `4 proposals from 5 backends` |

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP `hf_fs ls hf://models/trending` +
`hub_repo_details` on 2026-10-10 (used ~3 MCP calls of the 25-call
soft budget). Scope narrowed to **what moved since the 2026-10-08
digest** — most of this cycle's trending list was already triaged in
#190.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Qwen/Qwen-Image-2.1-Turbo** | 2026-10-09 | New distilled sibling of Qwen-Image-2.1 — pair with the base in a single `_reg("qwen_image", …)` landing | ~10 GB fp8 (7.1B params), low-step | medium | 2 | **New since #190.** Fresh yesterday — 408 likes / 2,138 downloads in <24h, 10+ demo Spaces already up. The turbo distill is the natural low-step companion to the base Qwen-Image-2.1 landing #190's Tier-2 described: ships as a `zit`-shape 4-step entry in whatever `_reg("qwen_image", …)` the operator eventually wires. Would unlock sub-second generation on 12-GB cards for the Qwen-Image path. |
| **Cloudflare/clef** + **Cloudflare/clef-flash** | 2026-10-09 | New VLM option for the Wizard Guild / Portraitist chat flow (not a core image-generation arch) | ~8 GB fp16 (clef) / ~3 GB fp16 (flash) | low | 2 | **New since #190.** 1,976 + 725 likes on day 1. Image-text-to-text (VLM) — potential swap for the current VLM step in the Portraitist auto-route (currently a Qwen-VL variant). Non-core-image-path, safe to A/B against. |
| **Cactus-Compute/whistle** | 2026-10-10 (today) | New ASR candidate for any voice-input Guild flow | ~1 GB fp16 | low | 2 | Just uploaded this morning (297 likes / 12,816 downloads). ASR / `automatic-speech-recognition` task. Only relevant if the Guild grows a voice-input mode — flagged for the roadmap, not for next-cycle integration. |
| **LiquidAI/d1-3B** | 2026-10-07 | Small VLM candidate | ~3 GB fp16 | low | 2 | 253 likes / 9,088 downloads. Image-text-to-text, 3B params — smaller alternative to clef-flash for VRAM-tight Spark configurations. |
| **Lightricks/LTX-2.5** | 2026-10-02 | Direct successor to the current `ltx` arch | ~24 GB video | medium | 2 | **Carried from #189/#190.** 7,133 likes / 1.7M downloads on this run's snapshot (climbed from 6,887 → 7,133 in 2 days). `_reg("ltx", …)` currently registers a 2.3-shape config; this is a straight version-swap. Gated=auto on HF — fleet-only download. |
| **Qwen/Qwen-Image-2.1** (base) | 2026-09-30 | New `qwen_image` arch — no current coverage | ~16 GB fp8, ~30 GB fp16 | medium | 2 | **Carried from #190.** 3,182 likes / 128K downloads. Base for the turbo distill above. Would land as `build_qwen_image_txt2img` + a new `_reg("qwen_image", …)` entry. |
| **google/embeddinggemma-2** | 2026-10-06 | Embedding step swap for `tools/llm_morning_briefing.py` / Guild chat retrieval flows | ~300 MB | low | 2 | **Carried from #190.** 1,452 likes / 45K downloads (climbed from 1,128 / 21K two days ago). Non-core-image-path, safe A/B. GGUF variant (`unsloth/embeddinggemma-2-GGUF`) also trending. |
| **ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF** | 2026-09-29 | GGUF-quantized variant of Qwen3.8-Flash-Next — candidate for the LLM-delegate / morning-briefing path | ~12 GB Q4 | low | 2 | 765 likes / 3.9M downloads. If the fleet currently runs `Qwen3.8-Flash-Next` for the delegate role, the GSQ-RCO GGUF variant is the lower-VRAM swap. See `installer/model_capabilities.json` for whether Flash-Next is in rotation. |
| **abenzerps/Qwen-Image-2.1-Uncensored-GGUF** | 2026-09-28 | NSFW branch of the Qwen-Image-2.1 integration (H6 hand-off) | ~10 GB Q4 | — | — | **Explicitly H6: NSFW-canon only.** 2.1M downloads, 3,837 likes — community-dominant uncensored variant. Does NOT belong on `spellcaster/`'s SFW path; this is a hand-off to the NSFW pipeline covered by the Tier-3 queue below. |

Carry-overs where the ranking didn't move materially since #190:
`abenzerps/Qwen-Image-2.1-GGUF` (SFW quantization), `MiniMaxAI/MiniMax-H3`
(from #189's top signal), `Comfy-Org/hunyuan3D_2.1_repackaged`,
`alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1`,
`Alissonerdx/BFS-Best-Face-Swap` LoRA. These stay actionable in the
Tier-3 queue of their original digest; not re-listed here to avoid
cycle-over-cycle duplication.

### Tier-2 non-model finding — resolved this run

- **Docstring-content refresh for `architectures.py`** — the finding
  from the 2026-09-22 digest. **Resolved as T1-c above** (promoted
  from Tier-2 to Tier-1 once the stubs-vs-registered split became
  structurally decidable from `_reg(...)`'s `registered=` kwarg).

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

```yaml
local_action_queue:
  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark1
    reason: "New since 2026-10-09; natural low-step companion to Qwen-Image-2.1 base. Pair-land both as _reg('qwen_image', ...) with turbo as the default 4-step tier for 12-GB cards. 10+ demo Spaces up on day 1 — community adoption curve is steep."
    command_hint: "huggingface-cli download Qwen/Qwen-Image-2.1-Turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1-Turbo --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_vlm
    target_repo: Cloudflare/clef-flash
    target_host: spark2
    reason: "New since 2026-10-09; small VLM (~3 GB) candidate for the Wizard Guild / Portraitist auto-route. Non-core-image-path — safe to A/B against the current VLM step. Compare with LiquidAI/d1-3B before promoting either."
    command_hint: "huggingface-cli download Cloudflare/clef-flash --local-dir D:\\LLM\\LM-Studio\\models\\Cloudflare\\clef-flash"
    risk: low

  - action: download_and_evaluate_vlm
    target_repo: LiquidAI/d1-3B
    target_host: spark2
    reason: "New since 2026-10-07; alternative small VLM for the Portraitist chat flow. Compare side-by-side with Cloudflare/clef-flash for latency and the Portraitist's five-tag Guild-routing prompt."
    command_hint: "huggingface-cli download LiquidAI/d1-3B --local-dir D:\\LLM\\LM-Studio\\models\\LiquidAI\\d1-3B"
    risk: low

  - action: download_and_evaluate_llm
    target_repo: ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF
    target_host: theo
    reason: "New GGUF quantization of Qwen3.8-Flash-Next. If the current LLM-delegate / morning-briefing config in installer/model_capabilities.json runs Flash-Next, the GSQ-RCO GGUF is the lower-VRAM swap. Verify the context ceiling matches installer/remote_services.json min_ctx_per_job_class before promoting."
    command_hint: "huggingface-cli download ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\LM-Studio\\models\\Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
    risk: low

  - action: hand_off_to_nsfw_pipeline
    target_repo: abenzerps/Qwen-Image-2.1-Uncensored-GGUF
    target_host: unknown
    reason: "H6 SFW-canon hand-off — does not belong on spellcaster/'s SFW path. 2.1M downloads make it the community-dominant uncensored branch; the NSFW pipeline (tools/upgrade_research_nsfw.py future per upgrade_research.py's H6 note) should pick it up."
    command_hint: "# N/A — hand-off, not a cloud-side download."
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Carried over since 2026-09-22 and partially addressed by cd01ad2 (safe_fetch migration). The cloud sandbox's egress proxy still denies HF/civitai CONNECT, so --dry-run falls back to skeleton (4 stub proposals). Running the same tool from the LAN exercises the real backends and produces the ranked shopping list this run can't."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index --methods build_qwen_image_txt2img,build_wan_video,build_klein_repose,build_illustrious_txt2img"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "Still unaddressed since 2026-09-22. Mechanical audit comparing architectures.py registered=True set against ComfyUI/models/* on disk to flag superseded weights (LTXV-2.3 if LTX-2.5 lands; LTX, Qwen-Image, Wan2.2 if newer variants land). Audit tool does not yet exist; see follow-up #4."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist"
    risk: low
```

## Operator decision — the ten-open-digest problem

The 2026-09-22 digest's follow-up #5 was already **"merge one and
close the rest or pause the routine"**. The operator chose a third
path on 2026-09-24: a kanban drain (consolidated unique diffs from
~50 stale digests into `2ebdf38`, closed the losers). The queue has
since regrown to 10 open digest PRs in 16 days.

Three options from here, in increasing order of operator effort:

1. **Repeat the 2026-09-24 kanban drain** — one commit on `main`
   that cherry-picks the current-truth doc values from this
   digest (status "October 2026", architectures docstring enumeration
   from T1-c), closes PRs #166/#183/#184/#185/#186/#187/#188/#189/#190/this
   as superseded. Lowest effort; preserves the every-48h cadence
   as a safety net.

2. **Merge one, close the rest** — the current PR (this one)
   carries the T1-c refresh plus the shared T1-a/b bumps, so
   merging it is a strict superset of #189's and #190's doc
   values. Then close PRs #166/#183/#184/#185/#186/#187/#188/#189/#190
   as superseded.

3. **Pause the every-48h cadence until the queue drains** — stop the
   schedule, drain the backlog, re-enable only when the review
   queue hits zero. Highest-effort but makes the "measurably better
   repo each run" goal realistic again.

## Follow-ups filed as future Tier-1 candidates

1. **`tools/audit_disk_vs_registry.py`** — the audit tool the
   `audit_retirable_weights` Tier-3 action depends on. Would walk
   `ARCHITECTURES` dict's `registered=True` keys and cross-reference
   `ComfyUI/models/*` layout from `installer/model_paths.json` (if
   present) to flag superseded weights. Mechanical to write but
   needs the model-paths manifest to exist first — flagged for a
   future run when the manifest is in-repo.
2. **`tools/upgrade_research.py` HF-MCP transport fallback** —
   carried from 2026-09-22 follow-up #3. Teaching the HF backend
   to prefer the `mcp__Hugging-Face__hub_repo_search` /
   `hub_repo_details` transport when available would let this
   routine run the *real* HF backend from the cloud instead of
   the skeleton one. Partially unblocked by `cd01ad2`'s
   `safe_fetch` migration (allowlist is already there); the
   remaining work is the MCP-call shim.
3. **`generate_showcase.py` tool-count label** — carried from
   2026-09-22 follow-up #4. Still unverified from the cloud
   sandbox (`generate_showcase.py` reads from
   `builders_manifest.json`'s `method_count: 75` so is probably
   already dynamic; needs a dry-run from a GIMP-capable host to
   confirm).

---
