# Ecosystem Research Digest — 2026-08-26

_Every-48h cloud-side sweep of the Spellcaster upgrade surface. Prior digest: `_dev_docs/ecosystem_digest_2026-08-24.md` (PR #161, still open)._

## TL;DR

Repo state on `main` is measurably unchanged since 2026-08-24: mirror drift, stale builders manifest, "May 2026" README header, and the missing `tools/upgrade_research.py` — the same four items PR #161 fixes — are still all present because that PR (and #160, #159, #158, #157) haven't been merged. This run re-applies those four Tier-1 fixes on a fresh branch so they can be picked up independently, and adds one genuinely new finding to Tier 2: **MiniMax H3** (native ComfyUI, 18.8M downloads on the Comfy-Org mirror, Kijai wrapper landed 2026-08-24) as a serious contender in the image-to-video slot currently held by Wan 2.2.

If the operator prefers to merge PR #161 instead, this PR is safe to close — its Tier-1 fixes are the same.

---

## Tier 1 — applied in this PR

Each item is a safe, mechanical, in-repo change. All were verified locally against the same test commands the CI mirror-drift and manifest-drift checks run.

| # | Finding | Fix | Verify |
|---|---|---|---|
| 1 | 6-surface mirror drift: `workflows.py`, `preflight.py`, `asset_gallery.py` diverged between surface C and surface 1. | `python tests/mirror_drift.py --fix` (C → 1; C canonical per `MIRROR_TARGETS.md`). | `python tests/mirror_drift.py` → `26/26 byte-identical`. |
| 2 | `builders_manifest.json` stale (73 methods on disk, 76 in `workflows.py`; missing `build_2d_to_sbs`, `build_2d_to_sbs_extreme`, `build_klein_multi_angle`). | `python tools/build_builders_manifest.py` regenerated it; then re-synced the manifest across the 6 surfaces. | `python tests/builders_manifest_drift.py` → `check: manifest fresh (76 methods).` |
| 3 | README status header dated "May 2026" (3 months stale). | Bumped to "August 2026" in place. News body intentionally untouched. | `README.md` line 46. |
| 4 | `tools/upgrade_research.py` missing — the routine's own prompt names this tool; prior runs silently degraded to web-only research. | Drafted a minimal offline fact-collector: reads `builders_manifest.json`, `architectures.py`, `installer/manifest.json`, and `DEPENDENCIES.md`; emits JSON or YAML; no network calls. | `python tools/upgrade_research.py` prints valid payload; `--out FILE --format yaml` works; snapshot reports 76 methods, 26 archs, 20 required + 5 optional packs. |

### Why the same four items, again

PR #161 (2026-08-24) and PR #160 (2026-08-22) both landed exactly this Tier-1 slate, and both are still open. Rather than pile new ecosystem-digest PRs on top of unmerged ones or skip Tier 1 entirely, this run re-does the fixes on an independent branch so any one of the three can be merged in isolation. If PR #161 lands first, this PR should merge cleanly (same result) or close (superseded).

---

## Tier 2 — needs human judgment on VRAM/quality/risk tradeoffs before shipping

| Model / change | Date | Replaces | VRAM | Risk | Notes |
|---|---|---|---|---|---|
| **MiniMax H3** (image-to-video) — [Comfy-Org mirror](https://huggingface.co/Comfy-Org/MiniMax-H3) `diffusion-single-file`, 1546 likes, 18.8M downloads | 2026-08-25 update | Wan 2.2 slot (`wan_i2v`) as a stronger alternative, not a replacement | GGUFs, INT4/INT8 ConvRot, and NVFP4 quants all published — 8-24 GB feasible | Medium | Native ComfyUI via Comfy-Org format; Kijai `MiniMax-H3_comfy` (397 likes) and `MiniMax-H3-experimental` (274 likes, 2026-08-24) mean the ComfyUI wiring is upstream. Turbo LoRA (`lightx2v/Minimax-h3-Turbo`, 711 likes) enables 4-step generation. Would slot alongside existing `wan_i2v` builder as a new arch, not swap for it. |
| **LTX-Video 2.5** — `Lightricks/LTX-2.5`, updated 2026-08-17, 1833 likes | 2026-08-17 | Current LTX-2.3 slot | int8 fits 24 GB | Medium | Carried over from #161. |
| **SAM 3.1** native ComfyUI — `dummy9996/SAM3.1-comfyui-fp8`, `Lutianming/SAM3.1-comfyui-fp8` | 2026-08-04 / 2026-08-16 | Existing SAM3 wiring | ~8 GB | Low-med | Drop-in for the SAM3 preprocessor path. |
| **PuLID-Flux2 v0.9.1** | pre-#161 | PuLID-Flux2 v0.9 | same | Low | +5 pp facial similarity; Klein 4B/9B aware. Carried over. |
| **SeedVR2 GGUF quants** | pre-#161 | SeedVR2 fp8 in 4K upscale | 8-12 GB | Low | Lowers 4K upscale floor. Carried over. |
| **Depth-Anything V3** — promote Optional → Required in `DEPENDENCIES.md` | ongoing | V2 | +200 MB | Low | Already listed as Optional; promotion is a docs + preflight change, not a code change. Carried over. |
| **DEEP_DIVE.md "69 tools" counter refresh** | — | — | — | — | Deliberately kept at 69 for the innuendo joke ("Yes, we counted. Yes, we noticed. No, we will not be adding a 70th (officially).") with 9 anchor references. Documented here as a Tier-2 human call, not a Tier-1 auto-fix. Actual method count is 76. |

---

## Tier 3 — needs local fleet access (LAN-only, not doable from cloud)

Emitted as a structured YAML block so a local Hermes/operator process can iterate over it mechanically, not as prose bullets a human has to re-parse.

```yaml
local_action_queue:
  - action: download_model_update
    target_repo: Comfy-Org/MiniMax-H3
    target_host: spark1
    reason: >-
      MiniMax H3 is trending #12 on HF (18.8M dl on the Comfy-Org mirror);
      pull the diffusion-single-file into ComfyUI/models/ so a Tier-2
      integration can be tested next cycle.
    command_hint: >-
      huggingface-cli download Comfy-Org/MiniMax-H3
      --local-dir /d/LLM/ComfyUI/models/diffusion_models/minimax_h3
    risk: low
  - action: download_model_update
    target_repo: Kijai/MiniMax-H3_comfy
    target_host: spark1
    reason: Kijai's ComfyUI-native wrapper for H3 (397 likes, 2026-08-13).
    command_hint: >-
      huggingface-cli download Kijai/MiniMax-H3_comfy
      --local-dir /d/LLM/ComfyUI/models/diffusion_models/minimax_h3_comfy
    risk: low
  - action: download_model_update
    target_repo: lightx2v/Minimax-h3-Turbo
    target_host: spark1
    reason: 4-step turbo LoRA for H3 — matches the Klein "fast at low steps" story.
    command_hint: >-
      huggingface-cli download lightx2v/Minimax-h3-Turbo
      --local-dir /d/LLM/ComfyUI/models/loras/minimax_h3_turbo
    risk: low
  - action: download_model_update
    target_repo: Lightricks/LTX-2.5
    target_host: spark1
    reason: LTX-Video 2.5 int8 → replaces current LTX-2.3 for higher fidelity.
    command_hint: >-
      huggingface-cli download Lightricks/LTX-2.5 --local-dir /d/LLM/ComfyUI/models/checkpoints/ltx_2.5
    risk: medium
  - action: install_comfyui_pack
    target_repo: https://github.com/kijai/ComfyUI-MiniMaxH3Wrapper
    target_host: spark1
    reason: >-
      If Kijai publishes a MiniMax-H3 wrapper node pack, ComfyUI needs it
      before the arch can be registered in spellcaster_core/architectures.py.
      Verify the exact repo URL before running — the wrapper may still be
      staged under his existing WanVideoWrapper.
    command_hint: >-
      git clone <verified_url> ComfyUI/custom_nodes/ComfyUI-MiniMaxH3Wrapper
    risk: medium
  - action: retire_superseded_model
    target_repo: Wan2.2-fp8
    target_host: unknown
    reason: >-
      DO NOT retire yet. This is a placeholder to reconsider once an H3
      integration is verified working; Wan 2.2 remains canonical until then.
    command_hint: null
    risk: high
```

---

## Prior-memory corrections

None this cycle. Prior digests (2026-08-18 through 2026-08-24) are consistent with what's on `main` — the drift-fix, manifest-regen, README-bump, and `upgrade_research.py`-draft observations they made are all still accurate because none of those PRs merged.

## Notes on delivery

- Gmail MCP: **auth expired / not authorized in this session** — cannot email a summary. Falling back to the PR + PushNotification as the sole delivery channels for this cycle. The operator can re-authorize the Gmail connector at claude.ai settings if the mail digest is desired going forward.
- Google-Drive MCP is available but there is no established Drive destination for these digests, so nothing was written there.

## Notes on CI leak-check

The `.github/workflows/leak-check.yml` may already be red against `main` from pre-existing `Whimweaver` / `Theo` / `192.168.86.*` matches in files this PR does not author (e.g. `_dev_docs/WHIMWEAVER_REPLAY_BRIDGE_PROPOSAL.md`, `plugins/krita/spellcaster_krita.py`, `installer/remote_services.json`). A diff-only scan restricted to files this PR authors is clean. If the leak-check fires on this PR purely because of pre-existing matches on `main`, that is not a regression introduced here — but it remains a valid Tier-1 candidate for a future run to actually scrub.
