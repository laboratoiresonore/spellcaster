# Ecosystem Digest — 2026-09-02

_Every-48h cloud-side sweep of the Spellcaster upgrade surface. Runbook rewritten 2026-08-18 to demand real Tier-1 fixes on every run, not just a report._

## Run summary

- **Tier 1 applied:** 4 in-repo fixes committed on this branch. Base cherry-picked from PR #164's `chore(digest): 2026-08-30 …` commit (README status bump, `test_full_inline_workflow_shape` fix, and initial `tools/upgrade_research.py` draft) because that PR has been sitting unmerged for the current 48h cycle and today's snapshot still needed those to land somewhere. On top of that base this run bumps the README status one month forward (August → September 2026) and corrects the README's advertised architecture count (27 → 26) to match what `upgrade_research.py` reports.
- **Tier 2 candidates surfaced:** 4 (Z-Image Turbo, LTX-2.5, Qwen-Image-2.0, Wan 2.7 open-weights watch). Details + integration notes below.
- **Tier 3 local-fleet actions queued:** 4 structured entries in `local_action_queue`.
- **Digest tool health:** `tools/upgrade_research.py` runs cleanly, emits the same 68-vs-69 tool-count and 26-vs-README-27 arch-count deltas that prior runs flagged; the arch-count one is fixed by this PR, the DEEP_DIVE per-section count stays Tier-2 (needs a human read to decide which section the missing tool belongs in).
- **Sweep budget used:** 4 WebSearch + 3 HF `hub_repo_search` calls (well under the ~25-call soft cap).

## Tier 1 — fixes in this PR

### 1. README status banner: `May 2026` → `September 2026`

The banner was 4 months stale on `main`. PR #164 already bumped it to August; this PR bumps it one more month to match today (2026-09-02). Copy under the banner (News / What works / Focus / Next) was left untouched — that is human-tone editorial text, not something to auto-rewrite from a cloud sweep.

**Diff:**

```diff
- <strong>📣 Status — May 2026</strong>
+ <strong>📣 Status — September 2026</strong>
```

### 2. README technical-reference blurb: `27-architecture registry` → `26-architecture registry`

`spellcaster_core/architectures.py` currently registers 26 archs (`upgrade_research.py --json` confirms: auraflow, chroma, cogvideo, flux1dev, flux2klein, flux_kontext, framepack, hunyuan_3d, hunyuan_dit, hunyuan_video, illustrious, kolors, ltx, lumina2, mochi, pixart, playground, pony, sd15, sd3, sd3_turbo, sdxl, sdxl_turbo, seedvr, wan, zit). README line 473 was still advertising "27-architecture registry". Corrected. If the plan is instead to _add_ a 27th arch (a strong candidate is Z-Image — see Tier 2), the future PR that adds the `_reg("zimage", …)` call also owns bumping this number back to 27 in the same commit.

### 3. `tests/test_phase9_ws.py::test_full_inline_workflow_shape` — un-break the red test on main

`NodeFactory.save_image_websocket()` now defaults `disk_backup=True` (a resilience win added 2026-05-09 after a ws-accept-loop crash; documented in that method's docstring). The test's docstring says it validates a **fully inline ws-only** workflow (expects 2 nodes), so passing `disk_backup=False` explicitly is the correct fix — production behavior and every other test are unchanged. `pytest tests/ ` → 33/33 green after the fix.

### 4. `tools/upgrade_research.py` — the tool this runbook depends on

Missing on `main` for many cycles despite the runbook leaning on it. Adds a best-effort snapshot generator that reads README + DEEP_DIVE + `installer/manifest.json` + `spellcaster_core/architectures.py` and emits a structured baseline (README status line, tool counts, 25 packs, 26 archs, retired-subsystem list). `--json` mode parses cleanly.

Living output already earns its keep — this run's Tier-1 arch-count fix (27 → 26) came from its `README.advertised_arch_count` vs `arch_registry.count` delta. The still-unresolved delta it emits (`DEEP_DIVE section headers advertise 69 tools, per-section sum is 68`) stays Tier-2 below.

## Tier 2 — new-model / new-architecture candidates (needs a human on VRAM/quality/risk)

| Model / pack | Released | Replaces / adds to | Approx VRAM | Risk | Integration notes |
|---|---|---|---|---|---|
| **Z-Image Turbo** (`Tongyi-MAI/Z-Image-Turbo`, `Comfy-Org/z_image_turbo`) — 6B, Apache 2.0, 8 steps, ~2–3s @ 1024² on 4090. GGUF variants exist (`jayn7/Z-Image-Turbo-GGUF`, `unsloth/Z-Image-Turbo-GGUF`). ControlNet-Union already available (`alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union`). 7.1M downloads on the Comfy-Org release. | 2025-11 base, 2026 turbo family maturing | Fast realistic path — could replace or sit next to current SDXL/Turbo route for the "generate a photo fast" tools. Does NOT replace Klein/Flux for high-fidelity work. | ~10–16 GB (GGUF: less) | **low** | Would add a 27th arch (`zimage`) in `spellcaster_core/architectures.py`; add a `_reg("zimage", …)` with an 8-step scheduler default; ControlNet-Union path already exists so preprocessor short-name alias map (commit `b20638c`) needs one new entry. Prompt-enhance profile: photorealistic, short prompt, English-heavy. |
| **LTX-2.5** (`Lightricks/LTX-2.5`, distilled GGUF `Abiray/LTX-2.5-Distilled-GGUF`, official spatial upscaler `Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler`, community BBox control `yuvraj108c/LTX-2.5-22b-IC-LoRA-BBox-Control`) — 22B family, Aug 2026, production-fidelity, multi-shot consistency, deep fine-tune support. | 2026-07 base repo, 2026-08 IC-LoRA ecosystem live | Direct successor to the `ltx` arch (currently registers LTX 2.x); LTX 2.5 is the current line. | ~24 GB fp16 for 22B, distilled GGUFs down to consumer GPUs | **medium** | Keep the `ltx` arch name (no registry rename); bump the checkpoint the arch resolves to, and add an `LTX-2.5` sub-profile in the video wizard. IC-LoRA-Pixel-Spatial-Upscaler is a strong Tier-3 candidate to add to the Upscale menu. |
| **Qwen-Image-2.0** (`QwenLM/Qwen-Image`, natively supported in ComfyUI since Aug 2025; 2.0 launched 2026-02-10) — 20B MMDiT, Apache 2.0, 2K native, standout text-in-image rendering, professional typography, 1k-token instruction budget. | 2025-08 v1, 2026-02 v2.0 | Adds a text-rendering-focused arch Spellcaster currently has no equivalent for (Klein/Flux/SDXL all mishandle in-image text). | ~24 GB fp16; GGUFs available for 16 GB tier | **medium** | New arch `qwen_image` in `architectures.py`; wire ComfyUI-Wiki's native workflow as the scaffold. Prompt-enhance profile: preserve exact text strings verbatim, disable rewriting inside quoted segments. |
| **Wan 2.6 / 2.7 (open-weights watch)** — Wan 2.6 reference-to-video is API-only (no local weights), so **not actionable for Spellcaster** until Wan 2.7 open weights land. Wan 2.5 is also API-only. | Wan 2.6 = Dec 2025, API-only; Wan 2.7 open release still pending as of this sweep | Placeholder — DO NOT integrate yet. Prior digest already flagged this pattern. | n/a | **n/a** | Keep `wan` arch pinned to Wan 2.2 open weights (the current one). Re-check at each 48h sweep; only integrate when a Wan 2.7 weights release exists on HF. |

Extra Tier-2 candidate carried forward from the prior digest (unresolved): `SeedVR2-7B FlashPack` (`fal/SeedVR2-7B-FlashPack`) — a FlashPack variant of the base SeedVR2 that would improve throughput on the existing `seedvr` arch's 2K/4K upscale flows. Same "needs local A/B" story as before; queued in Tier 3 below.

Also carried forward (unresolved from prior digests): `DEEP_DIVE.md` per-section headers sum to 68 tools while the "69 AI tools" advertised count remains 69. Fixing this well requires reading each section and finding the missing tool description; it is not a mechanical Tier-1.

## Tier 3 — local-fleet actions (structured queue for the local operator / Hermes)

```yaml
local_action_queue:
  - action: download_and_ab_test_z_image_turbo
    target_repo: Comfy-Org/z_image_turbo
    target_host: unknown
    reason: >
      6B Apache-2.0 realistic-photo generator, 8 steps, ~2-3s on RTX 4090.
      Very strong candidate to add as a 27th arch (zimage) for the
      "generate a photo fast" path — currently that lands on SDXL/Turbo.
      A/B against SDXL-Turbo on a fixed set of photorealistic prompts
      before wiring the arch registry entry.
    command_hint: >
      hf download Comfy-Org/z_image_turbo --local-dir
      <ComfyUI models dir>/checkpoints/z_image_turbo ; also grab
      Comfy-Org's shipped native workflow from
      https://blog.comfy.org/p/z-image-turbo-in-comfyui-realism and run
      side-by-side with SDXL-Turbo. If it wins, next 48h digest opens
      the arch-registry PR.
    risk: low

  - action: download_ltx25_and_bump_ltx_arch
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: >
      LTX-2.5 is the current line (Aug 2026). The `ltx` arch currently
      resolves to older LTX weights; pointing it at 2.5 is a
      quality-and-consistency uplift. Distilled GGUF
      (Abiray/LTX-2.5-Distilled-GGUF) is the consumer-GPU path.
    command_hint: >
      hf download Lightricks/LTX-2.5 --local-dir <ComfyUI models dir>/checkpoints/ltx25
      ; retire prior LTX checkpoint from live serving path once confirmed;
      Spellcaster PR follows to point ltx arch at the new file.
    risk: medium

  - action: eval_ltx25_pixel_spatial_upscaler
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: unknown
    reason: >
      Official spatial upscaler IC-LoRA for LTX-2.5. If it beats current
      video-upscale path (video_upscale tool added in commit 765c664)
      on a fixed clip set, add to the Upscale menu as an LTX-2.5-only
      option once the ltx arch is on 2.5.
    command_hint: >
      Only run after the ltx25 checkpoint download above. Then hf
      download the IC-LoRA under models/loras/ and run video_upscale
      on the fixed test clip set A/B against the incumbent.
    risk: low

  - action: benchmark_seedvr2_7b_flashpack
    target_repo: fal/SeedVR2-7B-FlashPack
    target_host: unknown
    reason: >
      Carried over from prior digest. FlashPack variant of SeedVR2 —
      throughput uplift for the existing seedvr arch's 2K/4K upscale
      flows without a quality regression, in principle. Needs a local
      A/B this sandbox can't run.
    command_hint: >
      hf download fal/SeedVR2-7B-FlashPack --local-dir
      <ComfyUI models dir>/checkpoints/seedvr2_flashpack ; run
      Spellcaster's Upscale tool with hallucination=none on the same
      test set used previously.
    risk: low
```

## Corrections to prior operator memory notes

- Prior digest (2026-08-30, in this PR's cherry-picked commit) said README status was already August 2026; that PR never merged, so `main` at start of this run still said May 2026. That's the merge-backlog cost of these digest PRs stacking without landing — not something this run can fix, but worth naming.
- Prior digest flagged `plugins/krita/spellcaster_krita.py` hardcodes a LAN IP in 5 places (should adopt the `COMFYUI_HOST` env-var pattern used elsewhere) as a Tier-1 candidate for a future run. Reviewed today — still true on `main`, but the change touches user-visible defaults and one operator-supervised fallback path, so leaving it as a **Tier-2 candidate** rather than pulling it into this PR. A follow-up PR scoped just to that plugin is the cleaner delivery.
- Wan 2.6 and Wan 2.5 remain API-only as of this sweep — do not spend cycles trying to integrate. Watch for Wan 2.7 open-weights.

## CI / delivery

- Ran the `leak-check.yml` pattern set locally against every changed file in this PR (README.md, tests/test_phase9_ws.py, tools/upgrade_research.py, _dev_docs/ecosystem_digest_2026-09-02.md, _dev_docs/ecosystem_digest_2026-08-30.md). Clean.
- `pytest tests/ ` — 33/33 green (only `test_phase9_ws.py` is currently pytest-discoverable; other test files aren't collected).
- Gmail MCP is present but not authenticated in this session, so the digest is delivered as the PR itself + this markdown; no email is sent this run.
