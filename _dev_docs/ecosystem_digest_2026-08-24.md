# Ecosystem Research Digest — 2026-08-24

Cloud-side sweep, every-48h routine. Rewritten prompt (2026-08-18)
requires each run to leave the repo in a measurably better state
and hand off anything that structurally can't happen from the cloud
as a precise, executable action item — not another paragraph nobody
parses.

## Header — tool gaps and CI state

- **`tools/upgrade_research.py` was missing on entry.** Every prior
  sweep flagged this and none of them drafted a replacement. This
  run does: `tools/upgrade_research.py` is included in the diff.
  It's a JSON/YAML fact-collector — enumerates the 76-method
  `builders_manifest.json`, the 20 required + 5 optional node
  packs, custom archs, and the model-family list — with no network
  calls (the routine's Claude does its own WebSearch / HF hub /
  WebFetch queries). Callable as `python tools/upgrade_research.py`
  (JSON to stdout) or `--out FILE --format yaml`.

- **`builders_manifest.json` was stale on entry.** The manifest on
  disk claimed 73 methods; `workflows.py` had 76. Three recently
  landed builders were missing from the manifest:
  `build_2d_to_sbs`, `build_2d_to_sbs_extreme`,
  `build_klein_multi_angle`. This is exactly the drift condition
  the `tests/builders_manifest_drift.py` CI guard exists to catch,
  and it would have failed on the next CI run against `main`.
  **Regenerated.** `python tests/builders_manifest_drift.py` is
  green.

- **6-surface mirror had 4-file drift on entry.** `workflows.py`,
  `preflight.py`, `asset_gallery.py`, and `builders_manifest.json`
  had all drifted between surface C (`comfyui-spellcaster/`) and
  surface 1 (`plugins/gimp/comfyui-connector/`). `tests/mirror_drift.py`
  would have failed CI. `--fix` applied (C is canonical, per the
  doc); `26/26 byte-identical` after.

- **README status header was 3 months stale** ("May 2026" — today
  is 2026-08-24). Bumped to "August 2026" in place. Body text
  intentionally left alone because none of the news claims are
  known to be wrong; a follow-up run with more news context should
  refresh the body.

- **CI leak-check** — no diff-side impact. All patterns forbidden
  by `.github/workflows/leak-check.yml` (internal project names,
  PII, token prefixes) remain scrubbed from the changes below.

---

## Tier 1 — fixes applied in this PR

Each of these is a mechanical, in-repo edit. Nothing here needs
human judgment before it ships; each corresponds to a file the
`main` branch could have shipped broken (mirror drift + manifest
staleness would both have red-CI'd on the next PR touching
`spellcaster_core/`).

| # | Finding | Fix | Verify |
|---|---|---|---|
| 1 | `builders_manifest.json` stale (73 methods on disk, 76 in `workflows.py`; drift check would fail CI) | `python tools/build_builders_manifest.py` regenerated the manifest; new `method_count: 76` includes `build_2d_to_sbs`, `build_2d_to_sbs_extreme`, `build_klein_multi_angle` | `python tests/builders_manifest_drift.py` → `check: manifest fresh (76 methods).` |
| 2 | 6-surface mirror drift on 4 files (workflows.py, preflight.py, asset_gallery.py, builders_manifest.json) between surface C and surface 1 | `python tests/mirror_drift.py --fix` (C → 1; C is canonical per MIRROR_TARGETS.md) | `python tests/mirror_drift.py` → `26/26 byte-identical` |
| 3 | README status header dated "May 2026" | Bumped to "August 2026" (mechanical date-only change; news body untouched) | Visual: `README.md` line 47 |
| 4 | `tools/upgrade_research.py` missing (the routine's own prompt names it, prior runs degraded silently to web-only research) | Drafted minimal fact-collector: reads `builders_manifest.json`, `spellcaster_core/archs/`, and `DEPENDENCIES.md`; emits JSON or YAML; no network calls | `python tools/upgrade_research.py --now 2026-08-24T00:00:00Z` prints a well-formed payload; `--out snap.json` writes it. Method count / families / packs match the source of truth. |

Nothing in this diff touches user-facing behavior — surface 1 gains
the missing `build_2d_to_sbs*` + `build_klein_multi_angle`
definitions and the `_fallback_sam3_optional` helper, which are
already live on surface C. This is drift closure, not new behavior.

### Explicitly downgraded to Tier 2 — safety guard

- **"69 tools" counter in README + DEEP_DIVE.** The actual method
  count is 76. Changing "69" → "76" would ordinarily be a Tier-1
  bump, but three things push it out of the Tier-1 safe zone:
  (a) the "69" is a deliberate innuendo joke ("Yes, we counted.
  Yes, we noticed. No, we will not be adding a 70th (officially).");
  (b) there are hard-coded anchor links `DEEP_DIVE.md#all-69-tools`
  in nine places that would silently break; (c) the DEEP_DIVE
  sub-tables sum to something between 68 and 70 depending on how
  Director's Chair Solo/Duo/Trio is counted, so no single "76"
  replacement is obviously right. Kicked to Tier 2 for a human
  call. See Tier 2 §6.

---

## Tier 2 — new-model / new-architecture opportunities

Each of these is a fresh upgrade candidate landed within the past
~six months. Model / date / replaces / VRAM / risk / tier /
integration notes format is preserved from prior digests.

| # | Model / pack | Date | Replaces (Spellcaster method) | VRAM | Risk | Tier | Integration notes |
|---|---|---|---|---|---|---|---|
| 1 | **LTX-Video 2.5** (`Lightricks/LTX-2.5` on HF, gated) | 2026-08-11 (13 days ago) | `build_ltx_video` (currently LTX 2.3) | int8: 22.7 GiB on RTX 4090; bf16: ~66 GB; 16 GB minimum | medium — gated HF repo requires license accept; single-file diffusion loader; VRAM budgeting per resolution row | **HIGH-priority swap** | 22B open-weights DiT; day-zero native ComfyUI support; adds text-to-audio-video, audio-to-video in one model; 10s at 720p in 6.8 s on GB200. Replaces our LTX 2.3 slot without changing the builder API — `build_ltx_video`'s preset table adapts to the new resolution/duration grid. |
| 2 | **SAM 3.1 Multiplex** (native in ComfyUI PR #13408, kijai) | 2026-04 native, ongoing multiplex updates | `build_sam3_segment`, `build_sam3_extract`, `build_magic_eraser`, `build_klein_sam3_inpaint` | Same as SAM 3 (single-GPU friendly, no extra deps) | low — additive; native ComfyUI, no wrapper pack to install | recommended | Shared-memory joint multi-object tracking; text-conditioned detection of new/occluded objects; bit-packed masks + object ID overlays. Same input shape as our SAM 3 wiring → drop-in if we upgrade the native ComfyUI pin. |
| 3 | **Depth-Anything V3** (already listed as *optional* in DEPENDENCIES.md) | 2025-11-14 released; ComfyUI native | `build_depth_map_v3` uses it; controlnet_gen depth arm falls back to V2 | small delta over V2 | low | promotion candidate | Consider promoting `ComfyUI-DepthAnythingV3` from **Optional** → **Required**, because it's also feeding `build_2d_to_sbs` (Y7-SBS-2Dto3D pipeline) and `build_2d_to_sbs_extreme`. V3 improves multi-view consistency across video frames — SBS-Extreme's disocclusion pass is a direct beneficiary. |
| 4 | **PuLID-Flux2 (v0.9.1)** — Klein 4B/9B-aware fork | 2026 v0.9.1 | `build_pulid_flux` (currently `PuLID_ComfyUI` for Flux Dev) | ~30 GB for full PuLID stack; Klein 4B path lighter | medium — new pack means new preflight entry; auto-detect logic in `preflight.py` needs the extra class_type | recommended | +5 pp facial similarity; Klein 4B is the best speed/quality tradeoff, Klein 9B is the identity-preserving ceiling. Aligns with the Klein-first house style; can be additive (keep PuLID-Flux for Flux Dev callers). |
| 5 | **SeedVR2 GGUF quants** | 2026 nightly ComfyUI-SeedVR2 | `build_seedvr2_video_upscale`, `build_wavespeed_upscale` | 4K workflow now runs on 8-12 GB consumer GPUs | low | recommended | Lowers the VRAM floor for `SeedVR2 Video Upscale` from studio → mid-range GPU. Purely additive — the wrapper picks the GGUF variant when it detects one on disk. Aligns with the "no cliff at 12 GB" install-story goal. |
| 6 | **DEEP_DIVE.md tool-counter refresh** ("69" → actual count) | n/a (docs) | Doc-only | n/a | low but **has an innuendo joke + 9 anchor links to update** | needs human call | See "Explicitly downgraded" above. Options: (a) recount every table to a new legible round number, update anchor to `#all-N-tools`, rewrite the "we will not be adding a 70th" joke; (b) leave the header at "69" as a stable marketing-joke number and add a footnote pointing to `builders_manifest.json` as SSoT. Recommend (b): the joke lives, the number stops being a lie, and the anchor stays stable. |
| 7 | **Wan 2.6 Reference-to-Video** | recent, ComfyUI-native | Would extend `build_wan_video` family | n/a — **API-only, no local weights** | HIGH — violates "100% local" philosophy | **do NOT integrate** | Called out here explicitly so future digests don't re-surface it. Wan 2.6 is API-only per Alibaba; only Wan 2.2 (current) and Wan 2.7 (open-weight, on ModelScope + GitHub — not HF) are candidates for local integration. |
| 8 | **Wan 2.7 open weights** | 2026-03 return-to-OW; ModelScope + GitHub distribution | Would be a new peer to `build_wan22_t2v` / `build_wan_video` | TBD | medium — distribution outside HF hub means the installer's HF-based pull needs a ModelScope path | prospective | Track for the next digest — need to confirm license (Apache 2.0 like 2.2 or restricted) and get a `Wan-AI/Wan2.7` HF mirror to appear before committing to install-side work. |

---

## Tier 3 — local_action_queue (structured hand-off)

Prior digests wrote these as prose bullets that a human had to
re-parse into commands. The rewritten routine says: emit them as a
structured yaml block so a local Hermes/operator process can consume
them mechanically. `target_host: unknown` when we can't say from the
cloud — better than guessing.

```yaml
local_action_queue:
  - action: download_model_update
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: >-
      Spellcaster's build_ltx_video currently ships LTX-2.3 presets.
      LTX-2.5 released 2026-08-11 with native ComfyUI support and
      an int8 build that fits a 24 GB card. Fleet operator picks
      the right Spark and accepts the HF license.
    command_hint: >-
      huggingface-cli download Lightricks/LTX-2.5 --local-dir
      D:\LLM\LTX-2.5 --exclude "*.safetensors.index.json"
      (requires: `huggingface-cli login` first; repo is gated,
      accept license at https://hf.co/Lightricks/LTX-2.5)
    risk: medium

  - action: pin_comfyui_sam3_native
    target_repo: Comfy-Org/ComfyUI
    target_host: unknown
    reason: >-
      SAM 3.1 with multiplex tracking is native in ComfyUI via
      PR #13408 (kijai). Spellcaster's SAM3 methods
      (sam3_segment / sam3_extract / magic_eraser /
      klein_sam3_inpaint) can drop the third-party
      ComfyUI-SAM3 / ComfyUI-Easy-Sam3 wrappers once the
      ComfyUI pin includes that PR.
    command_hint: >-
      Verify current ComfyUI commit >= PR #13408 merge sha; if
      older, `cd ComfyUI && git pull origin master && python
      -c "import comfy_extras.sam3 as s; print(s.__file__)"` to
      confirm native module.
    risk: low

  - action: retire_stale_ltx23_weights
    target_repo: Lightricks/LTX-Video
    target_host: unknown
    reason: >-
      Once LTX-2.5 is in place and calibration wizard confirms it
      passes the LTX slot's smoke test, retire the LTX-2.3
      checkpoint to free ~13 GB per Spark. Do NOT bulk-delete —
      keep one seed for regression comparison, per the "keep one
      seed" retirement convention.
    command_hint: >-
      Move D:\LLM\LTX-Video-2.3 → D:\LLM\.retired\LTX-Video-2.3
      (do not delete; the retirement folder is the safety net).
    risk: low

  - action: gguf_seedvr2_probe
    target_repo: numz/ComfyUI-SeedVR2_VideoUpscaler
    target_host: unknown
    reason: >-
      GGUF variants of SeedVR2 let 4K upscale run on 8-12 GB
      consumer GPUs — matters for community reproducibility of
      Spellcaster's video-upscale claims. Confirm nightly wrapper
      is on ComfyUI and pick a GGUF quant matching the fleet's
      smallest GPU.
    command_hint: >-
      `cd ComfyUI/custom_nodes/ComfyUI-SeedVR2_VideoUpscaler && git
      pull` then check the pack's README for the recommended GGUF
      variant matrix and pull the quant that fits the smallest
      GPU on the fleet.
    risk: low

  - action: watch_wan27_open_weights
    target_repo: Wan-AI (on ModelScope)
    target_host: unknown
    reason: >-
      Wan 2.7 returned to open-weight distribution in 2026-03 but
      is on ModelScope + GitHub, not HF. The Spellcaster
      installer today pulls from HF only. Nothing to download
      yet — this is a watch action so the next 48h sweep confirms
      a HF mirror or not.
    command_hint: >-
      No command yet. Cloud-side follow-up: search HF for
      Wan-AI/Wan2.7 mirror in the next digest; if present, add
      to installer/manifest.json as an optional model. If still
      only on ModelScope, decide whether to add a ModelScope
      fetcher to the installer.
    risk: low
```

Structured on purpose. A local process reading this can iterate over
`local_action_queue`, take the fields, and execute the
`command_hint` — no NLP re-parsing needed.

---

## Correction to prior operator memory notes

None this run. The three known-and-repeatedly-flagged in-repo
issues (supir arch _reg stub, uniform classifier grayscale
handling, "README says May 2026") were either already fixed on
main by earlier commits or fixed in this diff (README date). No
prior "false-positive" claims from earlier digests carried
forward that needed retraction here.

---

## Delivery notes

- **PR:** opened via `gh` from branch
  `claude/adoring-allen-a7h58b` against `main`. Digest is
  committed at `_dev_docs/ecosystem_digest_2026-08-24.md`.
- **Gmail notification:** Gmail MCP requires auth in this
  sandbox (per session start-up); falling back to the PR as sole
  delivery, as the rewritten routine instructs.
- **Google-Drive notification:** available; not used this run —
  the digest belongs in-repo, not in a personal drive folder
  where it can drift out of git.
- **Search budget used:** 8 WebSearch calls + 2 HF hub_repo_details
  calls, ~10 of the ~25 combined-call cap.

## Sources

- LTX-2.5 — [LTX-2.5 open-weights announcement (CryptoBriefing)](https://cryptobriefing.com/ltx-2-5-ai-video-model-release/) · [LTX-2.5 VentureBeat coverage](https://venturebeat.com/technology/ltx-2-5-can-generate-a-10-second-ai-video-from-an-image-in-just-6-8-seconds-on-nvidia-superchips-and-its-open-weights) · [Lightricks/LTX-2.5 on HF](https://huggingface.co/Lightricks/LTX-2.5)
- SAM 3.1 — [SAM 3.1 support PR #13408](https://github.com/Comfy-Org/ComfyUI/pull/13408) · [ComfyUI SAM 3.1 tutorial](https://docs.comfy.org/tutorials/utility/video-segment-sam3)
- Depth-Anything V3 — [Depth Anything 3 examples in ComfyUI](https://docs.comfy.org/tutorials/utility/depth-anything-3) · [Comfy-Org/Depth-Anything-3 on HF](https://huggingface.co/Comfy-Org/Depth-Anything-3)
- PuLID — [ComfyUI-PuLID-Flux2 (runcomfy)](https://www.runcomfy.com/comfyui-nodes/ComfyUI-PuLID-Flux2)
- SeedVR2 GGUF — [SeedVR2 GGUF 4K on mid-range GPUs](https://seedvr2.net/blog/tutorials/seedvr2-gguf-4k-upscaling-guide-2026)
- Wan 2.6 API-only — [Wan 2.6 R2V in ComfyUI](https://blog.comfy.org/p/wan26-reference-to-video)
- Wan 2.7 open weights — [Wan 2.7 open-weight status](https://wan27.org/blog/wan-2-7-open-source-guide)
- Flux 2 Klein context — [Flux2 official inference repo](https://github.com/black-forest-labs/flux2)
