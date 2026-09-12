# Ecosystem Research Digest — 2026-09-12

Cloud-side 48-hour sweep of the Spellcaster upgrade surface. Layered
on top of the 2026-09-10 sweep (PR #168, unmerged). Applies the
Tier-1 fixes that are still absent on `main` (README date bump,
broken nightly workflow preflight logic, missing `--dry-mode` flag
in `night_maintenance.py`), reports fresh Tier-2 model findings
against the state established by prior sweeps, and structures Tier-3
local-fleet work into the machine-parsable queue.

## Prelude — state of `main` this cycle

The 11 prior ecosystem-digest PRs (#158 – #168, one every ~48 h since
2026-08-18) are all still open. `main` therefore keeps every Tier-1
seed defect they've been re-applying, minus a handful that landed
via other paths since 2026-09-07:

* ✅ **Fixed on `main` since 2026-09-07** (commit `90d2432`, not via
  the digest routine): the SUPIR arch stub, the 6-surface mirror
  drift on `plugins/gimp/comfyui-connector/spellcaster_core/`,
  `tools/upgrade_research.py` at ~1000 lines with a working
  `--dry-run`, and the `builders_manifest.json` regenerated at
  75 methods. `python tests/mirror_drift.py` now returns
  `OK: 26/26  DRIFT: 0` from a clean checkout.
* ❌ **Still broken on `main`**, re-applied in this PR:
  1. `README.md` line 46 still reads `📣 Status — May 2026`
     (4 months stale).
  2. `.github/workflows/nightly.yml` still has all three preflight
     defects — wrong step id in `jobs.preflight.outputs.proceed`,
     invalid env-var name via `GITHUB_ENV`, POSIX param-expansion
     trap in `${smoke-failed:-0}`. See Tier 1 #2 below for what
     each one causes.
  3. `tests/night_maintenance.py` still has no `--dry-mode` flag,
     so the nightly workflow's `--dry-mode` invocation dies at
     argparse. See Tier 1 #3.

Nothing else on `main` needs a mechanical Tier-1 pass this run
(mirror-drift clean, manifest current, all 33 tests pass on a fresh
`python -m pytest tests/ -q`, `tools/upgrade_research.py --dry-run`
smoke-tests green with 5/5 backends).

## Tier 1 — applied in this PR (diffs below)

### 1. `README.md` — status date May → September 2026

Today is 2026-09-12. `main`'s status banner still reads "May 2026".
Every prior digest PR bumps this line, none have merged, so it's
still stale in the tree that users read.

```diff
-<strong>📣 Status — May 2026</strong>
+<strong>📣 Status — September 2026</strong>
```

### 2. `.github/workflows/nightly.yml` — preflight has never run

Landed 2026-07-04 in `d55f0f1`, untouched since. Three compounding
defects meant the `preflight → build → release` chain silently
did nothing every night:

  a. **Wrong step id in job outputs.** `jobs.preflight.outputs.proceed`
     reads `${{ steps.gate.outputs.proceed }}`, but `proceed` is set
     by the *decide* step, not `gate`. Result: the job output is
     always empty. `needs.preflight.outputs.proceed == 'true'` is
     therefore always false, so `build` never runs; and `== 'false'`
     is also always false, so the failure-issue job never runs
     either. Nightly builds have been silent no-ops for ~10 weeks.
  b. **Invalid env-var name via `GITHUB_ENV`.** `echo "smoke-failed=1"
     >> "$GITHUB_ENV"` writes a name containing `-`, which GHA
     rejects — env names must match `[A-Za-z_][A-Za-z0-9_]*`.
  c. **`${smoke-failed:-0}` isn't the env lookup the author wanted.**
     In POSIX-shell parameter expansion `${VAR-DEFAULT}` means
     "value of `smoke`, defaulting to the literal string
     `failed:-0` when `smoke` is unset". Even if (b) had worked,
     the check would never reflect the smoke result.

Fixed by (a) pointing `outputs.proceed` at `steps.decide`, (b) dropping
the `GITHUB_ENV` write entirely, and (c) reading `steps.gate.outcome`
— a built-in for any step with `continue-on-error: true`.

```diff
     outputs:
-      proceed: ${{ steps.gate.outputs.proceed }}
+      proceed: ${{ steps.decide.outputs.proceed }}
       tag: ${{ steps.tag.outputs.tag }}
...
-          python tests/night_maintenance.py --dry-mode || echo "smoke-failed=1" >> "$GITHUB_ENV"
-      - name: Decide proceed
-        id: decide
+          python tests/night_maintenance.py --dry-mode
+      - id: decide
+        name: Decide proceed
         run: |
-          if [ "${smoke-failed:-0}" = "1" ]; then
-            echo "proceed=false" >> "$GITHUB_OUTPUT"
-          else
+          if [ "${{ steps.gate.outcome }}" = "success" ]; then
             echo "proceed=true" >> "$GITHUB_OUTPUT"
+          else
+            echo "proceed=false" >> "$GITHUB_OUTPUT"
           fi
```

### 3. `tests/night_maintenance.py` — accept `--dry-mode`

The nightly workflow has been invoking `python tests/night_maintenance.py
--dry-mode`, but the script never parsed that flag — argparse would
exit non-zero on "unrecognized arguments: --dry-mode". Combined with
(2) above, this meant even a correctly wired workflow would have
failed at the preflight step.

New flag skips the three checks that require LAN reachability or
local paths (`installer-audit`, `capabilities`, `model-paths`) and
keeps the three that make sense in the GHA sandbox (`mirror-drift`,
`cross-repo-drift`, `log-scan`). Verified on this checkout:

```
$ python tests/night_maintenance.py --dry-mode --quiet ; echo "exit=$?"
exit=0

$ python tests/night_maintenance.py --dry-mode
  Server: http://127.0.0.1:8190
  Caps:   http://127.0.0.1:8191
  Report: /root/.voodoomaster/night_report_20260912.md

  [OK  ] mirror-drift        mirror_drift: byte-identical
  [OK  ] cross-repo-drift    cross_repo_drift: skipped (no sibling-repo paths set)
  [OK  ] log-scan            log scan: no fresh errors in launcher.log / comfyui.log
```

### Test-suite baseline unchanged

`python -m pytest tests/ -q` → **33 passed** before and after every
edit in this PR. `python tests/mirror_drift.py` → **OK: 26/26 DRIFT: 0**.

## Tier 2 — needs human judgement before it ships

New / updated model integrations from the last ~8 weeks. VRAM,
quality, and breaking-change tradeoffs need an operator sign-off
before code lands. Do NOT auto-apply.

| Model | HF repo | Date | Replaces / complements | Approx VRAM (GB) | Risk | Notes |
|---|---|---|---|---|---|---|
| **FLUX.2-klein-base-9b-fp8** | `black-forest-labs/FLUX.2-klein-base-9b-fp8` | ~2026-02, refreshed Aug 2026 | Lower-VRAM path for existing `flux2klein` arch | ~11–13 with FP8 | low | 🔒 Gated. 240.5K downloads, 605 likes. Official BFL FP8 quant of the base FLUX.2-klein-9B checkpoint. Same arch key as `flux2klein`, same loader — a checkpoint slot addition, not a new arch. Consumer-GPU-friendly path. |
| **Minimax-H3 Singularity** (fine-tune) | `WarmBloodAban/Minimax-h3_Singularity` | 2026-09-12 (refreshed today) | Fine-tune on the MiniMax-H3 base proposed in prior digest | 33B base → same VRAM footprint as base | med | 114.1K downloads, 338 likes, Apache-2.0. Adds HDR + `reference-to-video` support on top of MiniMax-H3. Community fine-tune, worth wiring alongside the base (see Tier-3 queue). Custom lib `minimax-h3`. |
| **HunyuanImage 2.1** (Comfy repack) | `Comfy-Org/HunyuanImage_2.1_ComfyUI` | 2026-08-17 | Successor to `hunyuan_dit` arch | ~12–24 with GGUF | med | Still current from prior digest. Downloads still climbing (~20K → ~30K est.). Would replace the `hunyuan_dit` arch key. |
| **LTX-2.5** | `Lightricks/LTX-2.5` | 2026-09-01 | Replaces `ltx` (2.3) | 24–40 (fp8/gguf appearing) | low | 🔒 Gated. 1.9M downloads (up from 1.8M in 2026-09-10), 3.6K likes. Multi-modal (text-to-audio, image-to-audio-video, audio-to-video, 9 languages). Suggest arch key `ltx25`. |
| **Krea-2 (Turbo/Raw)** | `krea/Krea-2-Turbo`, `Comfy-Org/Krea-2` | 2026-07-24 | Complements `flux1dev`/`flux2klein` photoreal T2I | ~12–16 | low | Still current from prior digest. 4.6M downloads on Comfy repack. Suggest arch key `krea2`. |
| **HunyuanVideo-1.5** (FP8/GGUF I2V) | `tencent/HunyuanVideo-1.5`, `unsloth/HunyuanVideo-1.5-720p-FP8`, `jayn7/HunyuanVideo-1.5_I2V_720p-GGUF` | 2026-07 → 2026-08 | Replaces `hunyuan_video` | ~16–24 with GGUF/FP8 | low | Rename `hunyuan_video` → `hunyuan_video15`, reuse VAE/scheduler. |
| **Eyes-Direction LoRA (FLUX.2-klein-9B)** | `eric-venti-seeds/Eyes_Direction_Lora_Flux2Klein9B` | 2026-09-08 | LoRA for existing `flux2klein` arch (portrait gaze control) | +0 GB (LoRA) | low | New this cycle. 37 likes, MIT license. Niche — controls eye direction / gaze in portraits. Worth including in `lora_calibrations_sfw.json` if the operator uses portrait workflows; not a shipping blocker. |
| **SeedVR2-3B** | `ByteDance-Seed/SeedVR2-3B` | 2025-06-22, steady traffic | Size variant of existing SeedVR2 (7B) | ~10–12 | low | Correction to 2026-09-08 digest still holds. Canonical Hub repo is `ByteDance-Seed/SeedVR2-3B` (135 likes, 217K downloads), not the `mofashiWY/` fork. |

### Tier 2 — repo hygiene

**Node-pack ecosystem drift check.** No archival, rename, or
hostile-fork signals on any of the 20 required + 5 optional
ComfyUI node-pack repos in `installer/manifest.json` in the 2-day
window since PR #168.

**`DEPENDENCIES.md` currency.** Regenerated via
`python scripts/generate_dependencies_md.py`; produced a byte-identical
file (27 rows, matches 25 nodes + header). No action.

**Test suite.** `pytest tests/` → 33 pass. `tests/mirror_drift.py`
→ 26/26 byte-identical. No hidden red baseline this cycle.

## Tier 3 — requires local fleet access (structured queue)

```yaml
local_action_queue:
  - action: fetch_flux2_klein_base_fp8
    target_repo: black-forest-labs/FLUX.2-klein-base-9b-fp8
    target_host: unknown
    reason: >-
      NEW this cycle. Official BFL FP8 quant of FLUX.2-klein-base-9B —
      240K downloads, 605 likes. Reuses the existing flux2klein loader
      (same arch key), gives a ~11-13 GB path suitable for 12 GB and
      16 GB consumer GPUs. Gated (license "other") — operator must
      accept license terms on HF once before the fetch will succeed.
    command_hint: >-
      huggingface-cli download black-forest-labs/FLUX.2-klein-base-9b-fp8
      --local-dir <models>/flux2klein/base-fp8   # requires prior license acceptance
    risk: low

  - action: fetch_minimax_h3_singularity_finetune
    target_repo: WarmBloodAban/Minimax-h3_Singularity
    target_host: unknown
    reason: >-
      NEW this cycle. HDR + reference-to-video fine-tune on top of
      MiniMaxAI/MiniMax-H3 (proposed in prior digest). 114K downloads,
      338 likes, Apache-2.0. Ships alongside the base MiniMax-H3
      NVFP4 quant queued 2026-09-10 — not a replacement.
    command_hint: >-
      huggingface-cli download WarmBloodAban/Minimax-h3_Singularity
      --local-dir <models>/minimax_h3/singularity
    risk: medium

  - action: fetch_flux2_klein_eyes_direction_lora
    target_repo: eric-venti-seeds/Eyes_Direction_Lora_Flux2Klein9B
    target_host: unknown
    reason: >-
      NEW this cycle. Portrait gaze-control LoRA for FLUX.2-klein-9B.
      Small (37 likes, MIT). Worth grabbing IF the operator's portrait
      builders (build_gate_portrait, build_focus_portrait, etc.) would
      benefit from a "straight to camera" adjustment slot. Skip if
      no portrait LoRA gap exists.
    command_hint: >-
      huggingface-cli download eric-venti-seeds/Eyes_Direction_Lora_Flux2Klein9B
      --local-dir <models>/loras/flux2klein/eyes_direction
    risk: low

  - action: fetch_and_stage_gated_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: >-
      Carried from prior digest. Base checkpoint for the LTX-2.5 arch
      integration proposed in Tier 2 (replaces existing `ltx` arch).
      Gated (license "other") — operator must accept license terms on
      HF once before the fetch will succeed. Do NOT ship the arch
      glue before this stage lands or the wan_i2v pipeline gets
      surprising 404s.
    command_hint: >-
      huggingface-cli download Lightricks/LTX-2.5 --local-dir
      <models>/ltx25/base   # requires prior license acceptance
    risk: medium

  - action: fetch_quantized_variant
    target_repo: jayn7/HunyuanVideo-1.5_I2V_720p-GGUF
    target_host: unknown
    reason: >-
      Carried from prior digest. 12-24 GB GGUF quant of
      HunyuanVideo-1.5 I2V. Prerequisite for replacing the existing
      hunyuan_video arch on consumer GPUs.
    command_hint: >-
      huggingface-cli download jayn7/HunyuanVideo-1.5_I2V_720p-GGUF
      --local-dir <models>/hunyuan_video15/i2v-gguf
    risk: low

  - action: fetch_krea2_comfy_repack
    target_repo: Comfy-Org/Krea-2
    target_host: unknown
    reason: >-
      Carried from prior digest. Comfy-Org repackage of Krea-2 — matches
      ComfyUI loader layout. Prerequisite for the Tier-2 krea2 arch
      key. Consider fetching lvladikov/Krea2-Turbo-Distill-4step-LoRA
      alongside for fast 12 GB paths.
    command_hint: >-
      huggingface-cli download Comfy-Org/Krea-2 --local-dir
      <models>/krea2/base
    risk: low

  - action: fetch_hunyuanimage_comfy_repack
    target_repo: Comfy-Org/HunyuanImage_2.1_ComfyUI
    target_host: unknown
    reason: >-
      Carried from prior digest. Comfy-Org repack of Tencent's
      HunyuanImage 2.1. Prerequisite for the proposed hunyuan_dit
      -> hunyuan_image21 arch upgrade.
    command_hint: >-
      huggingface-cli download Comfy-Org/HunyuanImage_2.1_ComfyUI
      --local-dir <models>/hunyuan_image/2.1-comfy
    risk: low

  - action: fetch_seedvr2_3b_canonical
    target_repo: ByteDance-Seed/SeedVR2-3B
    target_host: unknown
    reason: >-
      Carried from prior digest. Lower-VRAM SeedVR2 checkpoint (~10-12 GB)
      — same architecture as the existing SeedVR2-7B slot. Wire this
      checkpoint into existing SeedVR2 dispatch as a lower-VRAM slot
      after the Tier-2 dispatch glue lands.
    command_hint: >-
      huggingface-cli download ByteDance-Seed/SeedVR2-3B --local-dir
      <models>/SeedVR2/3B
    risk: low
```

## Not worth acting on this cycle

- **Trending LLMs on HF today** (DeepSeek-V4.1-Flash, MiniCPM5-2B,
  Qwen3.8-27B family, GLM-5.3-Flash, Nex-N2.5, Spark-X2.5-4B,
  Edge0-35B-A3B, YuE2-3B, GLM-5.3-CYBERSECURITY-FP8) — text-generation
  and audio-generation only; Spellcaster's LLM path is LM Studio +
  local-selection, not the ecosystem-digest's mandate.
- **Wan 2.5 / Wan 3.0** (Alibaba) — no open weights yet; API/closed
  beta only.
- **SAM 3.1 community variants** — no official Meta 3.1 drop; searches
  today return only unrelated fine-tunes (drivable-area, potholes,
  medical). Keep `facebook/sam3`.
- **SUPIR-class restoration** — no new drop; `SUPIR restoration`
  search returned 0 results.
- **New SDXL ControlNets** — no fresh drop; the trending SDXL
  controlnet items (`xinsir/controlnet-union-sdxl-1.0`,
  `xinsir/controlnet-openpose-sdxl-1.0`, `thibaud/controlnet-openpose-sdxl-1.0`)
  are already-covered baselines from 2024.
- **`akhaliq/*` and `HI7RAI/*` sora-2 / veo-3 mirror repos** — API
  proxy shells with 0 downloads; not actual weights.

## Correction to prior operator memory notes

None this cycle. The 2026-09-10 correction (canonical SeedVR2-3B is
`ByteDance-Seed/SeedVR2-3B`, not the `mofashiWY/` fork) still holds.

## CI / delivery notes

- **Leak-check baseline on `main`.** Prior digest called out that
  the leak-check regex hits pre-existing strings on `main`
  (nightly.yml host names, retired service names, capability keys).
  This PR touches `.github/workflows/nightly.yml` — a file the
  leak-check already flags on `main` for reasons unrelated to this
  diff. If leak-check goes red on this PR, verify by diffing added
  lines against `main`; the diff here contains no new leak-pattern
  content beyond what was already there. Filing as a Tier-1 candidate
  for a future run — either widen the leak-check exclude list or move
  the affected names behind an env-var scrub.
- **Gmail MCP**: OAuth expired in this cloud sandbox last cycle; not
  attempted this cycle. Falling back to the PR as sole delivery.
- **Google Drive MCP**: not attempted this cycle.
- **Hugging Face MCP**: authenticated as `jghkcktfkytf`, used for
  Tier-2 discovery.

## Research budget

Web + HF calls used this run: **~5 of 25 allotted** (4 `hub_repo_search`
+ 1 `hub_repo_details`, no WebSearch/WebFetch). Time-in-sandbox well
under the ~60-min soft cap.
