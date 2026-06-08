# Handover — local agent execution plan (digest 2026-06-08)

**For**: the VS Code Claude session running on your LAN with access to ComfyUI, the bundled spellcaster install, LM Studio peers, and CivitAI/HF model paths.

**From**: cloud routine, branch `digest/2026-06-08`, PR #74.

The cloud routine surfaced the candidates below but cannot install / test / benchmark against your hardware. Each task is scoped so the local agent can execute, verify, and either commit a follow-up branch or report a blocker.

---

## Quick context for the local agent

- VRAM ceiling: **16 GB** (RTX 5060 Ti).
- Local ComfyUI baseline: **0.20.3**.
- Local krita-ai-diffusion baseline: **v1.50**.
- LM Studio: in active use via `antenna/` connector. New 0.4.16 build dropped 2026-06-04.
- `tools/upgrade_research.py` is referenced by the cloud routine but **does not exist in the repo** — either commit it or trim the routine spec (see Task 6).
- Read the full digest at `_dev_docs/ecosystem_digest_2026-06-08.md` before starting.

---

## Tasks, in priority order

### Task 1 — ComfyUI bundle bump (0.20.3 → 0.23.0)

**Why**: 3 minor releases behind. 0.18.0 already shipped WAN/LTX VAE VRAM cuts the 16 GB ceiling benefits from. Logic nodes (And/Or/Not) and Preview3DAdvanced are net-new.

**Steps**:
1. Pull the latest `Comfy-Org/ComfyUI` tag, diff against the pinned version in `installer/` (or wherever the bundle pin lives — search for `0.20.3`).
2. Run the full pytest suite (target 156/156). If anything new fails, isolate to a ComfyUI API breakage vs a spellcaster bug.
3. Smoke-test the regression set: `build_klein_multi_angle`, `build_wan_*`, `build_qwen_edit_*` — each on a single small batch.
4. If green, commit on a `bump/comfyui-0.23.0` branch and open a PR.

**Risk**: ComfyUI minor versions sometimes change node graph schemas. Inspect any `comfyui-spellcaster/` JSON workflow files for `widgets_values` shifts before declaring done.

---

### Task 2 — krita-ai-diffusion bump (v1.50 → v1.51.1)

**Why**: v1.51.1 is the macOS/Linux managed-install fix. Operator runs Windows but the Acly fork is the upstream the krita plugin tracks.

**Steps**:
1. Find the pinned version in `plugins/krita/` or wherever the Acly fork is referenced.
2. Pull the release notes diff from https://github.com/Acly/krita-ai-diffusion/releases between v1.50.0 and v1.51.1.
3. Test the path that just landed in commit `46d903f fix(krita): multi-image outputs + Acly-style layer placement` — verify the v1.51.x release didn't move the layer-placement API.
4. Bump and commit.

---

### Task 3 — FLUX.2-klein-4B trial

**Why**: 4B variant fits ~13 GB — leaves headroom for text encoders + LoRAs without exclusive-load swaps. Current `build_klein_multi_angle` (commit `13c5675`) likely targets the 9B.

**Steps**:
1. Download `black-forest-labs/FLUX.2-klein-4B` (Apache 2.0, 404K downloads — known-good weights).
2. Add a `build_klein_4b_multi_angle` variant in `comfyui-spellcaster/spellcaster_core/workflows.py` that mirrors the 9B variant but targets the 4B checkpoint.
3. Benchmark on the same prompt + seed: 9B (exclusive-load) vs 4B (co-loaded with text encoder + a typical LoRA). Report VRAM peak, wall-clock, perceptual quality.
4. If 4B holds up, ship it as the default for the VRAM-constrained path and keep 9B as a `_high_quality` opt-in.

---

### Task 4 — Evaluate `nomadoor/flux-2-klein-9B-schematic-lora`

**Why**: Just dropped (2026-06-01) — a single LoRA covering depth + normal-map + pose + segmentation conditioning on Klein-9B. If it holds, it collapses what would otherwise be 4 separate ControlNet-style methods.

**Steps**:
1. Pull the LoRA from `hf.co/nomadoor/flux-2-klein-9B-schematic-lora`.
2. Run each of the 4 conditioning modes (depth / normal / pose / seg) through a fixed prompt; compare against your current per-mode pipeline.
3. If quality is competitive, draft a `build_klein_schematic_lora` method that takes a `mode` parameter.
4. **Caveat**: 35 likes, 0 downloads recorded at digest time — this is a leading-edge bet, not a steady-state recommendation. Treat as research.

---

### Task 5 — LM Studio 0.4.16 antenna smoke test

**Why**: 0.4.16 (2026-06-04) adds LM Link / Tailscale-mesh remote-access. The HTTP API surface should be stable, but the Locally mobile-app integration may have shifted the local server's bind defaults.

**Steps**:
1. Upgrade your local LM Studio install to 0.4.16.
2. Run `antenna/` integration tests against the local LM Studio (the cloud routine could not — LAN-only).
3. If `antenna` connects + answers a probe round-trip cleanly, commit the version bump comment in the connector. If it breaks, isolate to a config / port change vs an API change and report.

---

### Task 6 — Commit `tools/upgrade_research.py` (or trim the routine spec)

**Why**: The cloud routine spec says "Run `python tools/upgrade_research.py` (the `huggingface` and `civitai` backends are real impls)" — but that script does not exist in the repo. Today's cloud digest fell back to WebSearch + HF MCP only.

**Pick one**:
- **Option A**: Author the script locally — it should at minimum expose `--backends local_index,huggingface,civitai` flags and write `_dev_docs/upgrade_research/<iso-week>.{json,md}`. Use the existing `lora_calibrations_sfw.json` (currently empty `loras` dict — populate it from a local index walk) as the `local_index` baseline.
- **Option B**: Edit the routine spec to drop `tools/upgrade_research.py` references and accept that cloud digests are WebSearch + HF MCP only.

Option A is the higher-leverage one — the civitai backend in particular gives you a signal the cloud can't easily reproduce.

---

### Task 7 (optional) — Civitai sweep

**Why**: Cloud routine could not reach the civitai backend (no `upgrade_research.py`). Civitai is where Z-Image-Turbo finetunes and Klein-targeted LoRAs land first.

**Steps**:
1. Sweep top trending in the last 7 days under `Checkpoint` + `LoRA` tags, filtered `nsfw=false` per H6.
2. Cross-reference against the current `lora_calibrations_sfw.json` — anything you find that's not already calibrated is a candidate for the next batch.

---

## Handover hygiene

- The PR (#74) is the digest's source of truth. Land bump PRs as separate branches (`bump/comfyui-0.23.0`, `bump/krita-ai-1.51.1`, `feat/klein-4b`) rather than piling onto `digest/2026-06-08`.
- Cross-reference by name, not PR number, in commit messages (H7).
- Don't `git add -A` (H1).
- When you finish a task, mark it done in this file under a `## Status` section appended to the bottom, so the next cloud run can see what's already been picked up.

## Status

_To be filled in by the local agent as tasks land._
