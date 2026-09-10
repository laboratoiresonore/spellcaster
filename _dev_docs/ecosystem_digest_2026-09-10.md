# Ecosystem Research Digest — 2026-09-10

Cloud-side 48-hour sweep of the Spellcaster upgrade surface. This
run applies real Tier-1 fixes (broken nightly workflow logic,
--dry-mode missing from `night_maintenance.py`, 6-surface mirror
drift, stale README date, missing `tools/upgrade_research.py`)
and reports fresh Tier-2 model findings against the state
established by the 2026-09-08 sweep (PR #167, unmerged).

## Prelude — prior-run state

The previous 10 ecosystem-digest PRs (#158–#167, one every 48 h
since 2026-08-18) are all still open against `main`. Every one of
them ships the same Tier-1 seed set (add `tools/upgrade_research.py`,
bump the README status date) because nothing has been merged into
`main` yet. This digest therefore treats the same seed set as
"still missing on `main`" and re-applies it, and layers today's
new findings on top:

* **Nightly workflow was silently broken** since it landed
  (2026-07-04, commit `d55f0f1`). This is a real bug that no prior
  sweep caught. Fix applied in this PR (see Tier 1 #3 below).
* **6-surface mirror drift** on `main` (3 files: `workflows.py`,
  `preflight.py`, `asset_gallery.py`). Blessed direction (C → 1)
  applied via `python tests/mirror_drift.py --fix`.
* Fresh HF trending pass surfaces one new arch-adjacent finding
  (Tencent's `HunyuanImage-3.0` line as `hunyuan_dit` successor)
  and one canonical-repo correction to the prior digest's SeedVR2-3B
  entry (`ByteDance-Seed/SeedVR2-3B`, not the `mofashiWY/` mirror
  cited on 2026-09-08).

## Tier 1 — applied in this PR (diffs below)

### 1. `README.md` — status date May → September 2026

Today is 2026-09-10. The status banner still read "May 2026" on
`main` (line 46). Prior digest PRs bumped it to "September 2026"
but none have merged, so `main` still carries the 4-month stale
label.

```diff
-<strong>📣 Status — May 2026</strong>
+<strong>📣 Status — September 2026</strong>
```

### 2. `tools/upgrade_research.py` — new file, stdlib-only

Minimal working version of the tool this routine's brief calls
out by name. Same contract as the version drafted in PR #167:
emits JSON (or `--markdown`) of

  * every arch key registered via `_reg("key", ...)` in
    `comfyui-spellcaster/spellcaster_core/architectures.py`
    (26 today);
  * every ComfyUI custom-node pack in `installer/manifest.json`
    (25 today);
  * every method in `comfyui-spellcaster/spellcaster_core/builders_manifest.json`
    (73 today);
  * a hand-maintained list of non-diffusion helper models
    (SUPIR, SeedVR2, UltraSharp, SAM3, BiRefNet, DDColor,
    DepthAnythingV3, NormalCrafter) so restoration/segmentation
    tools get compared against the Hub too.

Smoke-verified inside the cloud sandbox against this checkout:

```
$ python tools/upgrade_research.py | jq '{archs:(.archs|length),
    nodes:(.nodes|length), builders:(.builders|length),
    helper_models:(.helper_models|length)}'
{"archs": 26, "nodes": 25, "builders": 73, "helper_models": 9}
```

### 3. `.github/workflows/nightly.yml` — preflight gate has never worked

Landed 2026-07-04 in `d55f0f1`, never modified since. Three
compounding defects meant the `preflight → build → release`
chain silently did nothing every night:

  a. **Wrong step id in outputs.** `jobs.preflight.outputs.proceed`
     read `${{ steps.gate.outputs.proceed }}`, but `proceed` was
     set by the *decide* step, not `gate`. Result: the job
     output was always empty. `needs.preflight.outputs.proceed
     == 'true'` was therefore always false, so `build` never
     ran; and `== 'false'` was also always false, so the
     failure-issue job never ran either. Nightly builds have
     been silently no-ops for ~10 weeks.

  b. **Invalid env-var name via `GITHUB_ENV`.** `echo "smoke-failed=1"
     >> "$GITHUB_ENV"` writes a name containing `-`, which GHA
     rejects (env names must match `[A-Za-z_][A-Za-z0-9_]*`).

  c. **`${smoke-failed:-0}` isn't the env lookup the author
     wanted.** In POSIX-shell parameter expansion `${VAR-DEFAULT}`
     means "value of `smoke`, defaulting to the literal string
     `failed:-0` when `smoke` is unset". Even if (b) had worked,
     the check would never have reflected the smoke result.

Fixed by folding the smoke result into a single `steps.gate.outcome`
check (built-in for `continue-on-error` steps), using
`$GITHUB_OUTPUT` throughout, and correcting the job-outputs ref.

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

### 4. `tests/night_maintenance.py` — add `--dry-mode`

The nightly workflow has been invoking
`python tests/night_maintenance.py --dry-mode`, but the script
never accepted that flag — argparse would exit non-zero on
"unrecognized arguments: --dry-mode". Combined with (3) above,
this meant even a working workflow would have failed at the
preflight step.

New flag skips the three checks that require LAN reachability or
local paths (`installer-audit`, `capabilities`, `model-paths`)
and keeps the three that make sense in the GHA sandbox
(`mirror-drift`, `cross-repo-drift`, `log-scan`).

Verified locally on this sandbox:

```
$ python tests/night_maintenance.py --dry-mode
  [FAIL] mirror-drift        # was true on main; fixed in Tier-1 #5
  [OK  ] cross-repo-drift    # sibling paths unset -> skip
  [OK  ] log-scan            # log dir absent -> skip
```

### 5. `tests/mirror_drift.py --fix` — 6-surface drift on `main`

`main` has 3 drifted files in the plugin's copy of `spellcaster_core`
that predate every prior digest run:

  * `plugins/gimp/comfyui-connector/spellcaster_core/workflows.py`
  * `plugins/gimp/comfyui-connector/spellcaster_core/preflight.py`
  * `plugins/gimp/comfyui-connector/spellcaster_core/asset_gallery.py`

Direction is not ambiguous — `mirror_drift.py --fix` copies the
canonical `comfyui-spellcaster/spellcaster_core/` surface (C) into
the plugin mirror (1), and the tool itself blesses that direction.
Applied. Without this fix, the nightly workflow (after Tier-1 #3
and #4 above) would flag drift and file an issue every night
until someone re-ran the sync manually.

Diff scale: +692 / −3 lines in `plugins/gimp/comfyui-connector/`
— all mechanical mirror sync, no logic edits.

## Tier 2 — needs human judgement before it ships

New model integrations from the last ~2 months. VRAM / quality /
breaking-change tradeoffs need an operator sign-off before code
lands. Do NOT auto-apply.

| Model | HF repo | Date | Replaces / complements | Approx VRAM (GB) | Risk | Notes |
|---|---|---|---|---|---|---|
| **HunyuanImage 2.1 / 3.0** | `Comfy-Org/HunyuanImage_2.1_ComfyUI`, `tencent/HunyuanImage-3.0`, `calcuis/hunyuanimage-gguf` | 2026-08-17 (Comfy repack); base 2026-01/02 | Successor to `hunyuan_dit` arch | ~12–24 with GGUF | med | **NEW this cycle.** Tencent's next-gen HunyuanImage line has an official ComfyUI repack (`Comfy-Org/HunyuanImage_2.1_ComfyUI`, 20K downloads Aug-Sep 2026). Would replace the `hunyuan_dit` arch key. `calcuis/hunyuanimage-gguf` (14.8K) is the community GGUF path. Instruct variant (edit-mode) also available. |
| **LTX-2.5** | `Lightricks/LTX-2.5` | 2026-09-01 | Replaces `ltx` (2.3) | 24–40 (fp8/gguf appearing) | low | 🔒 Gated. Confirmed 1.8M downloads, 3.3K likes. Adds text-to-audio, image-to-audio-video, audio-to-video, and 9 languages (en/de/es/fr/ja/ko/zh/it/pt). Same family; suggest arch key `ltx25`, reuse loader path. |
| **Krea-2 (Turbo/Raw)** | `krea/Krea-2-Turbo`, `Comfy-Org/Krea-2`, `lvladikov/Krea2-Turbo-Distill-4step-LoRA` | 2026-07-24; 4-step LoRA refreshed 2026-09-09 | Complements `flux1dev`/`flux2klein` photoreal T2I | ~12–16 | low | Comfy-Org repack has 4.6M downloads. `lvladikov` 4-step distill LoRA at 23K downloads / 121 likes, refreshed yesterday, gives fast T2I on 12 GB. Suggest arch key `krea2`. |
| **HunyuanVideo-1.5** (FP8/GGUF I2V) | `tencent/HunyuanVideo-1.5`, `unsloth/HunyuanVideo-1.5-720p-FP8`, **`jayn7/HunyuanVideo-1.5_I2V_720p-GGUF`** | 2026-07 → 2026-08 (community quants) | Replaces `hunyuan_video` | ~16–24 with GGUF/FP8 | low | Prior digest cited `Bn53/...-720p-GGUF` (367 downloads); `jayn7/...-720p-GGUF` (4K downloads) is now the more established mirror. Rename `hunyuan_video` → `hunyuan_video15`, reuse VAE/scheduler. |
| **MiniMax-H3** + NVFP4 variants | `MiniMaxAI/MiniMax-H3`, `cccian091/MiniMax-H3-T2V-NVFP4`, `WarmBloodAban/Minimax-h3_Singularity`, `jfar-z/MiniMax-H3-FL2VA-Ref2VA-Hybrid-NVFP4` | 2026-08-13 base; NVFP4 variants 2026-09-06 to 2026-09-10 | Complements `wan`/`hunyuan_video` — synced audio+video in one pass | 33B → ~18–24 with NVFP4/Turbo | med | Custom library `minimax-h3`. NVFP4 quants have proliferated in the last 4 days (last one uploaded 2026-09-10 today), suggesting active community interest. First synced-audio-video arch for Spellcaster. |
| **SeedVR2-3B** | **`ByteDance-Seed/SeedVR2-3B`** (canonical) | 2025-06-22 base; steady community traffic | Size variant of existing SeedVR2 (7B) | ~10–12 | low | **Correction.** Prior 2026-09-08 digest cited `mofashiWY/SeedVR2-3B` as target — that is a fork; the canonical Hub repo is `ByteDance-Seed/SeedVR2-3B` (135 likes, 217K downloads). Wire this checkpoint into existing SeedVR2 dispatch as a lower-VRAM slot. |

### Tier 2 — repo hygiene

**`builders_manifest.json` still stale.** Same as prior digest —
regenerating with `python tools/build_builders_manifest.py`
produces ~190 lines of diff adding 3 new methods (73 → 76). Not
shipped in this PR because (a) it changes the C-side capability
surface (behavioral change, not mechanical drift), and (b) two
mirrors must move together. Recommend a dedicated PR.

**Node-pack ecosystem drift check.** No archival, rename, or
hostile-fork signals on any of the 20 required + 5 optional
ComfyUI node-pack repos in `installer/manifest.json` in the
2-day window since the prior digest. `Runware/SeedVR2` (cleaner
FP8 distribution than the `kijai/` mirror) remains worth
tracking — no action today.

## Tier 3 — requires local fleet access (structured queue)

```yaml
local_action_queue:
  - action: download_model_update
    target_repo: ByteDance-Seed/SeedVR2-3B
    target_host: unknown
    reason: >-
      Lower-VRAM SeedVR2 checkpoint (~10-12 GB) — same architecture as
      the existing SeedVR2-7B slot. Prior digest cited mofashiWY/SeedVR2-3B
      which is a fork; the canonical Hub repo is ByteDance-Seed/SeedVR2-3B
      (135 likes, 217K downloads). Ship after the Tier-2 dispatch glue
      lands (adds a 3B checkpoint option to the existing SeedVR2 arch,
      not a new arch).
    command_hint: >-
      huggingface-cli download ByteDance-Seed/SeedVR2-3B --local-dir
      <models>/SeedVR2/3B
    risk: low

  - action: fetch_and_stage_gated_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: >-
      Base checkpoint for the LTX-2.5 arch integration proposed in
      Tier 2. Gated (license "other") — operator must accept license
      terms on HF once before the fetch will succeed. Do NOT ship the
      arch glue before this stage lands or the wan_i2v pipeline gets
      surprising 404s.
    command_hint: >-
      huggingface-cli download Lightricks/LTX-2.5 --local-dir
      <models>/ltx25/base   # requires prior license acceptance
    risk: medium

  - action: fetch_quantized_variant
    target_repo: jayn7/HunyuanVideo-1.5_I2V_720p-GGUF
    target_host: unknown
    reason: >-
      12-24 GB GGUF quant of HunyuanVideo-1.5 I2V. Prior digest cited
      Bn53/... (367 downloads); jayn7 mirror (4K downloads) is now the
      more established community source. Prerequisite for replacing the
      existing hunyuan_video arch on consumer GPUs.
    command_hint: >-
      huggingface-cli download jayn7/HunyuanVideo-1.5_I2V_720p-GGUF
      --local-dir <models>/hunyuan_video15/i2v-gguf
    risk: low

  - action: fetch_krea2_comfy_repack
    target_repo: Comfy-Org/Krea-2
    target_host: unknown
    reason: >-
      Comfy-Org repackage of Krea-2 — 4.6M downloads, matches ComfyUI
      loader layout. Prerequisite for the Tier-2 krea2 arch key.
      Consider fetching the 4-step distill LoRA
      (lvladikov/Krea2-Turbo-Distill-4step-LoRA, refreshed 2026-09-09)
      alongside for fast 12 GB paths.
    command_hint: >-
      huggingface-cli download Comfy-Org/Krea-2 --local-dir
      <models>/krea2/base
    risk: low

  - action: fetch_hunyuanimage_comfy_repack
    target_repo: Comfy-Org/HunyuanImage_2.1_ComfyUI
    target_host: unknown
    reason: >-
      NEW this cycle. Comfy-Org repack of Tencent's HunyuanImage 2.1
      (20K downloads Aug-Sep 2026). Prerequisite for the proposed
      hunyuan_dit -> hunyuan_image21 arch upgrade. Prefer the
      Comfy repack over tencent/HunyuanImage-3.0 base for arch-loader
      compatibility; the base can be fetched later if 3.0 becomes the
      target.
    command_hint: >-
      huggingface-cli download Comfy-Org/HunyuanImage_2.1_ComfyUI
      --local-dir <models>/hunyuan_image/2.1-comfy
    risk: low

  - action: fetch_minimax_h3_nvfp4
    target_repo: cccian091/MiniMax-H3-T2V-NVFP4
    target_host: unknown
    reason: >-
      NVFP4 T2V quant of MiniMax-H3 — makes the 33B synced-audio+video
      model reachable on 24 GB GPUs. Only 39 downloads today (new,
      2026-09-07), but the NVFP4 variant class is proliferating fast
      (5 new uploads in the last 3 days). Stage in a scratch dir first
      to smoke-test before promoting.
    command_hint: >-
      huggingface-cli download cccian091/MiniMax-H3-T2V-NVFP4
      --local-dir <models>/minimax_h3/nvfp4-t2v
    risk: medium
```

## Not worth acting on this cycle

- **Wan 3.0** (Alibaba) — API/closed beta only; no open weights.
- **SAM 3.1 community variants** — no official Meta 3.1; downstream
  fine-tunes only. Keep `facebook/sam3`.
- **New BiRefNet trending items** — ONNX/CoreML/WebGPU repackages
  only, no new architecture.
- **Face-restore SOTA gap** — no drop this cycle that beats the
  current CodeFormer + GPEN-2048 + RestoreFormer++ stack.
- **New SUPIR-class restoration model** — no drop in window; SUPIR
  repos unchanged since 2025.
- **`litert-community/FLUX.2-klein-4B-LiteRT`** (2026-09-05) —
  edge/mobile port, not a fit for Spellcaster's desktop workflow.
- **Trending LLMs** (Qwen3.8-27B family, GLM-5.3, MiniCPM5-2B,
  DeepSeek-V4.1-Flash) — text-generation only, Spellcaster's LLM
  path is LM Studio + local-selection; not the ecosystem-digest's
  mandate.

## Correction to prior operator memory notes

Prior digest (2026-09-08, PR #167) cited `mofashiWY/SeedVR2-3B`
as the SeedVR2-3B target. That repo is a fork/mirror. Canonical
is `ByteDance-Seed/SeedVR2-3B` (135 likes, 217K downloads,
Apache-2.0). Corrected in the Tier-2 table and Tier-3 queue above.

## CI / delivery notes

- **Leak-check will be red on this PR.** Pre-existing on `main`:
  `.github/workflows/nightly.yml`, `comfyui-spellcaster/spellcaster_core/workflows.py`,
  `installer/remote_services.json`, and a few others contain
  strings the leak-check patterns match (dev-host name, retired
  service name, `voodoomaster` capability keys). All present on
  `main` prior to this PR. Verified via
  `git grep -nE "<leak-patterns>" -- ':!.github/workflows/leak-check.yml'`
  against `main`. Not this run's regression. Filing as a Tier-1
  candidate for a future run: either widen the leak-check exclude
  list, or move the affected names into a scrub pass.
- **Gmail MCP**: OAuth expired in this cloud sandbox; no email
  delivery. Falling back to the PR as sole delivery, per the
  routine brief.
- **Google Drive MCP**: not attempted this cycle.
- **Hugging Face MCP**: authenticated as `jghkcktfkytf`, used for
  Tier-2 discovery.

## Research budget

Web + HF calls used: **~8 of 25 allotted** (7 `hf_fs` batches +
1 `hub_repo_details`, no WebSearch/WebFetch this run — the HF
Hub was authoritative for everything queried).
Time-in-sandbox: well under the ~60 min soft cap.
