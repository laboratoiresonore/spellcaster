# Ecosystem Research Digest — 2026-09-08

Cloud-side 48-hour sweep of the Spellcaster upgrade surface. Prior
routine runs wrote long reports nobody applied; this one leaves the
repo materially better before it hands anything off, per the brief's
three-tier rewrite (Tier 1 fix it now / Tier 2 human decision /
Tier 3 requires local fleet).

## Prelude — the tool this routine depends on was missing

The routine brief instructs: *"Run `python tools/upgrade_research.py`
if it exists. If it does not exist ... draft a minimal working
version and include it in your PR — a missing tool your own prompt
depends on is itself a Tier-1 fixable finding, not a permanent
excuse."*

It did not exist. Prior sweeps degraded silently to web-only
research and did not report the gap. This run supplies it (see
Tier 1 below). Every future run of this routine can now start from
a stable local inventory instead of re-grepping the tree each time.

## Tier 1 — applied in this PR (diffs below)

### 1. `README.md` — "Status — May 2026" → "Status — September 2026"
Today is 2026-09-08. The status banner at line 46 declared "May
2026", a 4-month stale date. The surrounding body ("News / What
works / Current focus / Next") is still substantively accurate, so
this run touches only the label. Anything more would be speculative
copywriting outside this routine's mandate.

```diff
-<strong>📣 Status — May 2026</strong>
+<strong>📣 Status — September 2026</strong>
```

### 2. `tools/upgrade_research.py` — new file, ~180 lines, stdlib-only
Minimal working version of the tool this routine's brief calls out
by name. Emits a JSON (or `--markdown`) snapshot of:

  * every arch key registered via `_reg("key", ...)` in
    `spellcaster_core/architectures.py` (26 today);
  * every ComfyUI custom-node pack from `installer/manifest.json`
    (25 today), with `repo` / `provides` / `required_by`;
  * every workflow builder in
    `spellcaster_core/builders_manifest.json` (73 in the checked-in
    manifest — see Tier 2 note below re: drift);
  * a hand-maintained helper-model list (SUPIR, SeedVR2, UltraSharp,
    SAM3, BiRefNet, DDColor, DepthAnythingV3, NormalCrafter, …) so
    non-diffusion helpers get compared against the Hub too.

No network access, no third-party imports, safe to run inside the
sandbox from a fresh clone. Smoke-tested locally — `python
tools/upgrade_research.py`, `--markdown`, and `--field {archs,nodes,
builders,helper_models}` all return the expected content.

Contract intentionally kept small — future runs can extend it (e.g.
add `--diff-against previous_snapshot.json`) without breaking the
core inventory contract.

## Tier 2 — needs human judgement before it ships

New base models that landed in the last ~8 weeks. Every entry
below is a real upgrade opportunity, but VRAM / quality / breaking-
change tradeoffs need an operator sign-off before code lands. Do
NOT auto-apply.

| Model | HF repo | Date | Replaces / complements | Approx VRAM (GB) | Risk | Notes |
|---|---|---|---|---|---|---|
| **LTX-2.5** | `Lightricks/LTX-2.5` | 2026-09-01 | Replaces `ltx` (2.3) | 24–40 (fp8/gguf appearing) | low | Same family as existing LTX; adds audio-to-video / video-to-audio / T2AV. Suggest new arch key `ltx25`, reuse loader path; spatial upscaler variant already ported to community repos. Gated repo, license "other". |
| **Krea-2** (Turbo / Raw) | `krea/Krea-2-Turbo`, `Comfy-Org/Krea-2` | 2026-07-24 (Comfy port 2026-08-17) | Complements `flux1dev` / `flux2klein` — photoreal T2I | ~12–16 | low | Comfy-Org repackage has 4.6M downloads. 4-step distill LoRA (`lvladikov/Krea2-Turbo-Distill-4step-LoRA`) makes it fast on 12 GB. Pose ControlNet already exists. Add `krea2` arch. |
| **HunyuanVideo-1.5** (FP8/GGUF I2V wave) | `tencent/HunyuanVideo-1.5`, `unsloth/HunyuanVideo-1.5-720p-FP8`, `Bn53/HunyuanVideo-1.5_I2V_720p-GGUF` | 2026-07 → 2026-08 (community quants) | Replaces `hunyuan_video` | ~16–24 with GGUF/FP8 | low | Base was Dec 2025 but only usable locally now via July–Aug FP8/GGUF drops. Rename `hunyuan_video` → `hunyuan_video15`, reuse VAE / scheduler mostly. |
| **MiniMax-H3** | `MiniMaxAI/MiniMax-H3` | 2026-08-13 | Complements `wan` / `hunyuan_video` — synced audio+video in one pass | 33B params → ~48 fp16, ~18–24 with NVFP4/Turbo | med | Custom library `minimax-h3`; Turbo-LoRA + NVFP4 distilled variants active (multimodalart/h3-acceleration-arena, mrfakename/minimax-h3-ultra-fast). New audio+video family — first time Spellcaster would ship synced-audio video. |
| **SeedVR2-3B** | `mofashiWY/SeedVR2-3B` | 2026-08-28 | Size variant of existing SeedVR2 (7B) | ~10–12 | low | Same architecture, lower-VRAM slot. Wire new checkpoint into existing SeedVR2 dispatch. Also see Tier 3 fetch. |

### Tier 2 — non-model repo hygiene

**`builders_manifest.json` is stale on `main`.** Regenerating with
`python tools/build_builders_manifest.py` produces a 190-line diff
adding **3 new methods** (73 → 76). Not shipped in this PR because:

  1. The generated manifest is the C-side / capabilities-gate
     surface — 3 new advertised methods is a behavioral change,
     not a mechanical drift-fix.
  2. Two mirror copies exist
     (`comfyui-spellcaster/spellcaster_core/builders_manifest.json`
     and `plugins/gimp/comfyui-connector/spellcaster_core/builders_manifest.json`);
     the PR-template checklist requires all mirrors to move in
     lockstep with the accompanying `spellcaster_core/` changes.

Recommend a dedicated PR that (a) regenerates both mirrors, (b) runs
`tests/test_model_coverage.py`, and (c) explicitly lists the 3
newly-advertised methods in the PR body so the human reviewer can
confirm each is ready to be exposed to the C-side dispatcher.

### Tier 2 — ecosystem drift check (no action required)

Cross-referenced the 20 required + 5 optional ComfyUI node-pack
repo IDs in `installer/manifest.json` against the Hub. **No archival
/ rename / hostile-fork signals in the 8-week window** for any of:
`kijai/ComfyUI-SUPIR`, `cubiq/ComfyUI_essentials`, `city96/ComfyUI-GGUF`
(active PRs Aug/Sep 2026), `Fannovel16/comfyui_controlnet_aux`,
`Kosinkadink/ComfyUI-VideoHelperSuite`, `ltdrdata/ComfyUI-Impact-Pack`,
`PozzettiAndrea/ComfyUI-DepthAnythingV3`, `1038lab/ComfyUI-RMBG`,
`AIWarper/ComfyUI-NormalCrafterWrapper`. All repo IDs remain valid.

One adjacent repo worth tracking (not a rename): **`Runware/SeedVR2`**
(2026-08-03) provides a cleaner FP8 checkpoint distribution than
kijai's mirror. Could become the canonical download source if kijai
stops mirroring — no action today, just note.

## Tier 3 — requires local fleet access (structured queue)

Forward-compatible queue for a local operator / Hermes process to
consume. Not a live pipeline — a human still triggers this — but
now written as data instead of prose so a script can dispatch it
without re-reading the digest.

```yaml
local_action_queue:
  - action: download_model_update
    target_repo: mofashiWY/SeedVR2-3B
    target_host: unknown
    reason: >-
      Lower-VRAM SeedVR2 checkpoint (~10-12 GB) — same architecture as
      the existing SeedVR2-7B slot, useful for 12 GB / 16 GB GPUs. Ship
      after the Tier-2 arch-registry glue lands (adds a 3B checkpoint
      option to the existing SeedVR2 arch, not a new arch).
    command_hint: >-
      huggingface-cli download mofashiWY/SeedVR2-3B --local-dir
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
    target_repo: Bn53/HunyuanVideo-1.5_I2V_720p-GGUF
    target_host: unknown
    reason: >-
      12-24 GB GGUF quant of HunyuanVideo-1.5 I2V — the community-
      quantized path that makes replacing the existing hunyuan_video
      arch actually reachable on consumer GPUs.
    command_hint: >-
      huggingface-cli download Bn53/HunyuanVideo-1.5_I2V_720p-GGUF
      --local-dir <models>/hunyuan_video15/i2v-gguf
    risk: low

  - action: fetch_krea2_comfy_repack
    target_repo: Comfy-Org/Krea-2
    target_host: unknown
    reason: >-
      Comfy-Org repackage of Krea-2 — matches ComfyUI loader layout,
      already downloaded 4.6M times so it is the de-facto standard
      distribution. Prerequisite for the Tier-2 `krea2` arch key.
    command_hint: >-
      huggingface-cli download Comfy-Org/Krea-2 --local-dir
      <models>/krea2/base
    risk: low
```

## Not worth acting on this cycle

- **Wan 3.0** (Alibaba, public beta 2026-08-06, 30 s 1080p + audio) —
  API/closed beta only; no open weights on HF. Revisit if Alibaba
  open-sources. No Wan 2.5/2.6/2.7 on HF either.
- **SAM 3.1 community variants** (`adopd/SAM3.1-segmentation-ADOPD`,
  `tea98/sam3-for-insects-segmentation`) — no official Meta 3.1
  release; all downstream fine-tunes. Keep `facebook/sam3`.
- **New BiRefNet trending items** — all ONNX/CoreML/WebGPU repackages
  of existing weights, no new architecture. Existing BiRefNet stays.
- **Face-restore SOTA gap** — `ohayonguy/PMRF_blind_face_image_restoration`
  reposted 2026-07-27 and `GOBUNU/NTIRE2025_RealWorld_Face_Restoration`
  (2026-08-25) exist, but nothing here beats the current
  CodeFormer + GPEN-2048 + RestoreFormer++ stack decisively.
- **New SUPIR-class restoration model** — no drop in window; SUPIR
  repos unchanged since 2025.
- **Small SwinIR / SRResNet / RCAN uploads (Sep 2026)** — student
  coursework, no benchmark data, none replace
  UltraSharp / Remacri / NMKD.
- **SDXL successor** — no credible open drop in the window;
  Krea-2 is the closest and it's already in Tier 2.

## Correction to prior operator memory notes

None this cycle. No prior digests exist in `_dev_docs/` to correct;
this is (per `git log --all -- _dev_docs/ecosystem_digest_*`) the
first ecosystem digest committed to the repo. Prior routine outputs
lived outside git or in the notification channel only.

## Delivery notes

- **Gmail MCP**: OAuth expired in this sandbox. Not fatal — the
  system reminder flags it, this session cannot run an OAuth flow.
  Falling back to the PR as sole delivery, per the routine brief's
  "say so plainly" clause.
- **Google Drive MCP**: not attempted this cycle (nothing to file
  outside the repo).
- **Hugging Face MCP**: authenticated as `jghkcktfkytf`, used for
  Tier 2 discovery. 8 of the budgeted 15 web/HF calls consumed.

## Research budget

Web + HF calls used: **~8 of 25 allotted**
(4 `hf_fs` batches + 1 `hub_repo_details` + 3 WebSearch).
Time-in-sandbox: well under the ~60 min soft cap.
