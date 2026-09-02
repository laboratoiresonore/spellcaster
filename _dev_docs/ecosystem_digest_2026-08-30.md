# Ecosystem Research Digest — 2026-08-30

Every-48h cloud sweep of the upgrade-opportunity surface for Spellcaster.
Output format: three tiers (fix-it-here, human-judgment, needs-local-fleet).

**Sweep budget used:** ~6 HF searches + 1 WebSearch (well under the ~25-call
cap). Rationale: model-family surface hasn't shifted enough since the last
survey to justify wide sweep; enough signal fell out early to fill Tier 2.

**Missing-tool self-repair:** `tools/upgrade_research.py`, which prior
digests were meant to lean on, did not exist in the repo. Loudly flagged
per the runbook and drafted in this same PR as `tools/upgrade_research.py`
(a best-effort snapshot generator that reads README + DEEP_DIVE +
installer/manifest.json + architectures.py so the next digest run has
structured facts to start from). See Tier 1 below.

---

## Tier 1 — applied in this PR

Real, in-repo, mechanical changes verified against `pytest tests/`
(33/33 green).

### 1. `README.md` — status date bump `May 2026 → August 2026`
The prominent "📣 Status" block on line 46 still read **May 2026** — 3+
months stale. The News/What-works/Focus copy under it is a human-tone
paragraph and was NOT touched (that's rewrite work, not a date bump).
Diff:

```diff
- <strong>📣 Status — May 2026</strong>
+ <strong>📣 Status — August 2026</strong>
```

### 2. `tests/test_phase9_ws.py` — align stale test with documented `disk_backup=True` default
`test_full_inline_workflow_shape` was failing on `main` (2 nodes
expected, 3 built). Root cause: `NodeFactory.save_image_websocket()`
now defaults to `disk_backup=True` and appends a companion `SaveImage`
node — a resilience win added after the 2026-05-09 ws-accept-loop
crash (documented in the method's docstring). The test's docstring
says it validates a fully inline ws-only workflow, so the correct fix
is opting out of disk backup explicitly instead of asserting the
now-wrong count. Behaviour of the production code and every other test
is unchanged.

```diff
- save_id = nf.save_image_websocket([img_id, 0])
+ save_id = nf.save_image_websocket([img_id, 0], disk_backup=False)
```

### 3. `tools/upgrade_research.py` — draft the missing digest harness
The every-48h runbook has been leaning on this file for multiple cycles
and it has never existed in the repo. Drafted a minimal, best-effort
snapshot generator that:

- Reads the README "Status —" date + advertised tool count.
- Diffs DEEP_DIVE's advertised total against the sum of its per-section
  tool-count headers (**currently surfaces 68 vs advertised 69** —
  see Tier 2 below).
- Enumerates the 25 ComfyUI node packs in `installer/manifest.json`.
- Enumerates the 26 architectures in
  `comfyui-spellcaster/spellcaster_core/architectures.py`.
- Marks retired subsystems (antenna) so future digests never propose
  reviving them.
- Emits `digest_hints` explicitly listing the classes of safe Tier-1
  fixes and the leak-check patterns to avoid.

Every collector is best-effort; a missing/broken file degrades to a
placeholder rather than crashing the routine. Smoke:

```
$ python tools/upgrade_research.py
# upgrade_research snapshot @ 2026-08-30T16:12:07+00:00
## readme
{ "advertised_tool_count": 69, "status_line": "August 2026", ... }
## deep_dive
{ "advertised_tool_count": 69, "summed_section_counts": 68, ... }
## manifest
{ "pack_count": 25, "manifest_version": "...", ... }
## arch_registry
{ "count": 26, "arch_names": ["auraflow","chroma", ...], ... }
```

---

## Tier 2 — new-model / new-architecture integration work needing human judgment

Findings from HF + web sweep since ~2026-08-13. Only listing items with
plausible tie-ins to Spellcaster's existing surfaces.

| Model / pack | Date | Replaces / augments | VRAM (approx) | Risk | Notes |
|---|---|---|---|---|---|
| `fal/Flux-Vision-Upscaler-SeedVR2-FP16-FlashPack` | 2026-08-07 | SeedVR2 upscale path | ~12 GB (FP16 3B) | low | FlashPack variant of the existing SeedVR2-3B base. Drop-in candidate for the "SeedV2R Upscale" tool if throughput improves. |
| `CQdesign/LTX-2.5-CQ-Video-and-Image-Enhancer-LoRAs` | 2026-08-20 | LTX 2.3 pipeline (Videomancer) | LoRA only, +0 | low | 67 likes in 10 days. If Spellcaster promotes LTX 2.5 as the T2V engine, this is a quality-uplift LoRA to auto-detect. |
| `happyinhappy/flux2-klein-face-restore-lora` | 2026-08-28 | Klein Face Detail tool | LoRA only | low | Specialised face-restoration LoRA on Klein-9B; worth an A/B against current Impact-Pack face detailer. |
| `houseofboern/more-detail-flux-klein-9b` | 2026-08-27 | Klein Detail Enhancer | LoRA only | low | Detail-boost LoRA on Klein-9B base. |
| `litert-community/FLUX.2-klein-4B-LiteRT` | 2026-07-09 → updated 2026-08-27 | On-device Klein 4B | INT8, mobile | med | 6.9k downloads, 8 likes. Not for the desktop rig but a reference point if a mobile companion ever ships. |
| `abc-l61/FLUX.2-klein-4B-openvino` | 2026-08-29 | CPU/iGPU Klein path | INT8 (OpenVINO) | med | Enables CPU/Intel-iGPU Klein 4B inference. Not a fleet swap — a fallback-path candidate for low-VRAM installs. |
| `dsixteen/flux2-klein-9b` | 2026-08-30 | Klein-9B checkpoint mirror | unchanged | low | Just posted today; treat as a mirror until provenance is clear. |
| Alibaba PAI **MiniMax H3 Acc LoRA** (8-step PDD distill) | 2026-08-26 | Video acceleration | LoRA only | med | Native ComfyUI node pack shipped alongside. If Spellcaster's video path adopts MiniMax H3, this is the acceleration LoRA. |
| **SenseNova-U1.5 ConvRot for ComfyUI** | 2026-08-25 | New heavy image model | ~12 GB (ConvRot squeezes 50 GB → 12 GB) | high | Interesting VRAM story; needs sample-quality bake-off before it earns a slot. |
| **MMH3 Ultimate Upscale** (ComfyUI node) | 2026-08-25 | Video upscale | tiled | med | Tiled H3 video upscaling for limited-VRAM cards. Complements SeedVR2 rather than replacing it. |
| `Qwen/Qwen3-VL-4B-Instruct` (+ 8B) | still current | Prompt-enhance LLM | 8–16 GB | low | The `ComfyUI-QwenVL-Mod` pack (already in Spellcaster's manifest) targets the Qwen2.5-VL family. A Qwen3-VL 4B upgrade is now well-supported (multiple ComfyUI-ready quants, including INT8-ConvRot and NVFP4 variants). Worth benchmarking against current QwenVL-Mod default. |

### Correctness/consistency findings (human-decision only)

These are surfaced by the new `tools/upgrade_research.py` snapshot and
flagged for Tier 2 because we can't pick the right correction without
product context:

- **DEEP_DIVE section counts sum to 68, not 69** (Generate 7 + Klein 9
  + Enhance 9 + Face 7 + Style 4 + Select 3 + Video 7 + Studios 7 +
  Quick 7 + Tools 8 = 68). README slogan and section title still say
  "69 tools". Off-by-one somewhere; **which section is short by one is
  a product decision**, not a mechanical fix, so I did not silently
  bump any count.
- **README.md line 473 claims a "27-architecture registry"**;
  `architectures.py` currently registers 26 via `_reg(...)`. Same story
  — could be README stale, or one arch was intentionally retired. Human
  to decide whether to bump the number down or restore an arch.
- **README.md line 437 and DEEP_DIVE.md §Antenna still promote the
  antenna as a live feature** (`[Antenna service-mesh](antenna/README.md)`
  is a broken link — the file was moved to
  `antenna.RETIRED-2026-06-20-DO-NOT-TOUCH/`). Per `ANTENNA_RETIRED.md`
  the antenna module is superseded by out-of-tree `prometheus-client`
  and the operator has explicitly said not to resurface it. Rewriting
  the marketing copy is a tone/voice decision — flagging, not touching.

---

## Tier 3 — needs local-fleet access this sandbox does not have

```yaml
local_action_queue:
  - action: benchmark_seedvr2_flashpack_variant
    target_repo: fal/Flux-Vision-Upscaler-SeedVR2-FP16-FlashPack
    target_host: unknown
    reason: >
      FlashPack variant of the existing SeedVR2-3B base. If it beats
      current 2K/4K SeedVR2 throughput without quality regression, it
      supersedes the file behind Spellcaster's "SeedV2R Upscale" tool.
    command_hint: >
      hf download fal/Flux-Vision-Upscaler-SeedVR2-FP16-FlashPack --local-dir
      <ComfyUI models dir>/checkpoints/seedvr2_flashpack ; run Spellcaster's
      Upscale tool with hallucination=none on a fixed set of test images
      A/B against the incumbent.
    risk: low

  - action: evaluate_qwen3vl_4b_upgrade_for_prompt_enhance
    target_repo: Qwen/Qwen3-VL-4B-Instruct
    target_host: unknown
    reason: >
      Current ComfyUI-QwenVL-Mod pack (in manifest) targets Qwen2.5-VL.
      Qwen3-VL-4B is mature, has multiple ComfyUI-ready quants, and
      would upgrade the prompt-enhancement chain that all image tools
      share.
    command_hint: >
      Pull one of the Qwen3-VL-4B GGUF/INT8 quants and swap the QwenVL-Mod
      loader path to it in Spellcaster's LLM prompt-enhance node config;
      compare prompt quality on ~20 test prompts.
    risk: medium

  - action: eval_klein_face_restore_lora
    target_repo: happyinhappy/flux2-klein-face-restore-lora
    target_host: unknown
    reason: >
      Fresh (2026-08-28) Klein-9B LoRA targeting face restoration —
      overlaps Spellcaster's "Detail Enhancer (face)" and Restorix
      wizard flows. A/B against the current Impact-Pack detailer.
    command_hint: >
      Place under ComfyUI/models/loras/, auto-detect via Spellcaster's
      LoRA registry, run Detail Enhancer with target=face on the same
      test set used for the previous Klein detailer evaluation.
    risk: low

  - action: eval_ltx25_enhancer_loras
    target_repo: CQdesign/LTX-2.5-CQ-Video-and-Image-Enhancer-LoRAs
    target_host: unknown
    reason: >
      LTX 2.5 quality-uplift LoRA pack; only relevant once the LTX
      path is on 2.5. Do NOT auto-apply — LTX 2.3 is the currently
      documented version (README.md line 135, DEEP_DIVE line 524).
    command_hint: >
      Only proceed after a Spellcaster-side decision to promote LTX 2.5.
      Then: hf download + add to LoRA registry with the Videomancer
      wizard scaffold as trigger.
    risk: medium

  - action: verify_prometheus_client_replaces_all_antenna_docs
    target_repo: null
    target_host: unknown
    reason: >
      README + DEEP_DIVE still describe the retired antenna in the
      present tense. The prometheus-client replacement lives out of
      tree; someone with fleet visibility needs to decide whether to
      (a) rewrite those doc sections to point at prometheus-client, or
      (b) simply delete the sections. Do not touch from the cloud
      sandbox — the operator has explicitly said not to resurface
      antenna-adjacent doc changes without their sign-off.
    command_hint: >
      Human review pass over README.md L437 + DEEP_DIVE.md §Antenna
      section (line 866+) with the operator.
    risk: high
```

---

## Prior-run correction notes

- None: no prior `_dev_docs/ecosystem_digest_*.md` exists in the repo.
  This appears to be the first successful commit of the every-48h
  routine, so there is no prior operator memory to correct. Future
  digests should update this section if they overturn a claim made
  here.

---

## Delivery notes

- Gmail MCP is present but **not authenticated** in this session (the
  connector requires OAuth in an interactive session). No email sent.
  Falling back to this PR as the sole delivery channel, per the runbook.
- Drive MCP is available; not used this cycle (nothing to file there —
  the digest itself lives in-repo).
- The `tools/upgrade_research.py` snapshot is unwritten by default; a
  future run can `--out _dev_docs/upgrade_research_snapshot.json` for a
  persistent baseline.

## Sources (WebSearch citations)

- [ComfyUI News & Open-Source AI Releases | ComfyUI Wiki](https://comfyui-wiki.com/en/news)
- [ComfyUI custom nodes: Manager, Nodes 2.0, prod (2026) | Runflow](https://www.runflow.io/blog/comfyui-custom-nodes)
- [Best ComfyUI Custom Nodes in 2026 | promptzone](https://www.promptzone.com/tara_suzuki/best-comfyui-custom-nodes-in-2026-the-ones-actually-worth-installing-75d)
- [ComfyUI Custom Node Install Guide: 8 Core Packs | Aquanode](https://www.aquanode.io/blog/comfyui-custom-node-install-guide)
- [Custom nodes (new UI) — ComfyUI docs](https://docs.comfy.org/manager/pack-management)
