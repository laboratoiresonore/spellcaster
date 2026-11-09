# Ecosystem digest — 2026-10-22

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `ed19fb4`). Branch: `claude/adoring-allen-8xu93e`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest (plus its stacked
  harvest) landed on `main`, so this run starts clean and does not
  stack on an open queue.
- **Routine health.** `tools/upgrade_research.py` is still present and
  `--dry-run` exits `0`, same `4 proposals from 5 backends` shape as
  the previous digest confirmed. No skeleton draft needed.
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`, so the
  live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` continue to return nothing from here.
  The Hugging-Face MCP (`hf_fs ls hf://models/trending`,
  `hub_repo_search`) is the live research path this run uses, ~9 MCP
  calls spent of the ~25-call soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **New since 2026-10-16.** The v2.4 Spark2 GB10 NVFP4/FP8/INT8 image
  & video model push (sha `4b1e1c0`) landed 8 new `_reg()` entries in
  `architectures.py` since the last digest — `flux2dev`, `flux3klein`,
  `krea2`, `qwen_image`, `minimax_h3`, `skyreels`, `longcat`,
  `aurasr` — plus three later installer/preset fix commits. That
  bumped the `build_*` method surface from 75 → **78** and the
  registered-arch set from 27 → **35** (29 fully-registered + 6
  stubs). Both docstrings that enumerate it, and the HF upgrade-query
  map, were stale after that drop — see Tier-1 below.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes
(`pytest tests/` → 57/57).

### T1-a `architectures.py` docstring: 8 arches missing from the enumeration

The 2026-10-16 digest's T1-b expanded the `SUPPORTED ARCHITECTURES (as
of October 2026):` block to cover 27 arches (21 fully-registered + 6
stubs). The intervening v2.4 Spark2 push (`4b1e1c0`) added 8 more
`_reg()` entries to the registry on disk without updating the
docstring, so the module header was out of sync by 8 arches again:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
- Video: `minimax_h3`, `skyreels`, `longcat`
- Other / upscaler: `aurasr`

Added the missing entries to the Image / Video / Other sections of the
docstring, keeping the same one-line description shape as prior rows.
This is the same bug class the 2026-10-16 T1-b fix addressed, same
reasoning: `registered=True` is on each `_reg()` call explicitly, no
judgement call needed, docstring-only change, registry stays
source-of-truth.

Mirror-drift stays byte-identical: identical edit applied to both
`comfyui-spellcaster/spellcaster_core/architectures.py` and
`plugins/gimp/comfyui-connector/spellcaster_core/architectures.py`;
`python tests/mirror_drift.py` → `OK: 32/32   DRIFT: 0`.

### T1-b `tools/upgrade_research.py`: HF arch-query map is missing 8 archs

Same bug class as 2026-10-16's T1-c, same cause (new `_reg()` entries
landed after the previous digest). `_HF_ARCH_QUERIES` had 27 entries
but the registry now has 35, so `_hf_query_for_method(build_<arch>_*)`
returned `None` for 8 fully-registered arches, and a live
`huggingface` or `civitai` backend run from a LAN host would silently
skip candidate research for them.

Added mappings for: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`,
`minimax_h3`, `skyreels`, `longcat`, `aurasr`. Also broadened the
existing `ltx` entry to put `"ltx-2.5"` first so the current dominant
LTX release (2.1M downloads on HF trending as of today) ranks ahead of
the generic `"ltx-video"` keyword.

Also bumped the module docstring from "`build_*` methods — 70 at the
time of that pass, 75 as of 2026-10-16" → "70 at the time of that
pass, **78 as of 2026-10-22**" to match the current
`python tools/build_builders_manifest.py` output (which the
newly-rebuilt manifest at HEAD confirms: `78 methods`).

Verification: `python tools/upgrade_research.py --dry-run` still exits
`0`, same `4 proposals from 5 backends` output; `pytest tests/` →
`57 passed`.

### Verification summary of T1-a + T1-b

- `pytest tests/` — `57 passed in 9.47s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same shape
  as before.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  manifest on disk already carried 78 (no diff).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`). Numbers below are the live HF report at the time of
this digest. The 2026-10-16 digest's Tier-2 rows for Flux-3-Klein,
Qwen-Image-2.1-Turbo, SAM 3.1, SAM 3D variants, LTX-2.5 IC-LoRA pack,
Flux-2-Dev, and the Z-Image prompt-engineer are still open and are
NOT re-reported here — assume they carry forward until the operator
acts on them. New this run:

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **OpenMOSS-Team/MOSS-Image-SFT** + **Comfy-Org/MOSS-Image** | 2026-10-11 (base) / 2026-10-16 (comfy repack) | NEW `moss_image` arch — no current `_reg()` entry; distinct architecture family (not SDXL / Flux-shape) | TBD (base is diffusers-only; Comfy repack is single-file but size not listed) | medium | 2 | Trending Score 516 on SFT base, Comfy-Org repack 1.46M downloads / 353 likes / Trending Score 332. Apache-2.0 license (first-class open license — unlike Flux's "other"). SFT variant currently sits ~5× more downloads than Flux-3-Klein SFT on the trending board. Would land as a new `_reg("moss_image", loader="unet_clip_vae", clip_mode="single_moss_image", vae_mode="separate", ...)`. Also has an 8-step distill at `lodestones/MOSS-Image-SFT-8-steps-dmd` (75.4K downloads) that pairs with it the way Qwen-Image-Turbo pairs with Qwen-Image. Decision point: is this the right new "open-license fast image lane" to add alongside `qwen_image`, or does the operator prefer to keep the open-license lane on Qwen? |
| **lodestones/Kromoss** | 2026-10-19 (updated) | MOSS-Image fine-tune — reference checkpoint for a `moss_image` builder family if MOSS lands | n/a (fine-tune of the SFT base) | low | 2 | 222 likes / 14.4K downloads in the first 72 hours, Trending Score 217. If MOSS-Image gets a `_reg()` entry, this is the drop-in fine-tune for the "character / stylised" lane of that arch, analogous to how `pony` and `illustrious` sit on top of SDXL. |
| **deepseek-ai/DeepSeek-V4.1-Flash-1017** | 2026-10-17 | New VLM candidate for `llm_delegate.py` — would replace or complement the current Qwen3-VL and Gemma3 picks in LM Studio preflight | ~4.5 GB fp8 (`eval-results, 8-bit, fp8` on the card); full ~1.5 M-download base at `DeepSeek-V4.1-Flash` is larger | medium | 2 | Trending Score **2013** (top of the live HF trending board as of this digest; 51.9K downloads in 5 days). Image-text-to-text (vision + reasoning + tool-calling, 1M context on the uncensored fork). MIT-licensed. Would land as a new entry in `llm_delegate.py`'s model list for prompt enhancement / preflight routing; probably displaces the DeepSeek-V3.x row the fleet runs today. Needs operator read: does the Spark2's VRAM budget want a 4.5 GB fp8 VLM pinned permanently, or is the fp4-local nvidia variant (`nvidia/Qwen3.8-Flash-Next-FP4-Local`) a better fit? |
| **meta-models/Muse-Spark-Open-816B-A42B** (+ `-NVFP4` + `-GGUF`) | 2026-09-15 | Large sparse MoE VLM (A42B active / 816B total) for `llm_delegate.py` top-of-stack reasoning | ~130 GB fp16 full, ~45 GB NVFP4, ~55 GB Q4_K_M GGUF | high | 2 | Trending Scores 585 / 180 / 63 on the three variants. Named "Muse-Spark" by Meta — unrelated to the operator's local "Spark1/2" boxes. 816B total parameters, gated=manual on HF (unlike flux-3-image-klein's gated=auto, this needs a reviewed access request). Realistically only the NVFP4 or GGUF variants fit on Spark1/2 at all, and even then would saturate the box. Operator decision: is this the kind of "think-slow" router the stack wants, or is a Qwen3.8-27B / DeepSeek-V4.1-Flash blend a better fit for the latency budget? |
| **lodestones/MOSS-Image-SFT-8-steps-dmd** | 2026-10-16 | Few-step distill of MOSS-Image-SFT (paired candidate — only matters if MOSS lands) | n/a (adapter / distilled, size follows SFT base) | low | 2 | 196 Trending Score / 75.4K downloads. DMD distill (same technique family as the Qwen-Image-Turbo and chriswritescode/Turbo8-LoRA-Qwen-Image-2.1 forks). If the operator picks MOSS as a new arch, this is the "fast lane" entry inside it. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-09-22 | NEW LTX-2.5 IC-LoRA — storyboard-to-video / camera control | ~2 GB (adapter on LTX-2.5 base) | low | 2 | 105 likes / 10.8K downloads. Fourth IC-LoRA entry in the LTX-2.5 series (alongside Alpha-Gen, Pixel-Spatial-Upscaler, Refine-Details, Ingredients, Clean-Plate the 2026-10-16 digest already filed). Camera-control + layout-to-render is a distinctly different task than the four prior IC-LoRAs — would land as `build_ltx_storyboard_video` or `build_ltx_camera_control_video`. Same license / distribution contract as the LTX-2.5 base. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate** | 2026-09-09 | NEW LTX-2.5 IC-LoRA — object removal from video | ~2 GB (adapter on LTX-2.5 base) | low | 2 | 31 likes / 6K downloads. Object-removal video builder (`build_ltx_remove_object_video`); the natural pair for the already-filed Alpha-Gen (which does background/matte removal) — Alpha-Gen removes BG, Clean-Plate removes individual objects. |

### Tier-2 non-model finding

- **Flux 3 Klein distribution has split into three canonical repos.**
  As of today the Flux 3 Klein family on HF trending is: `-comfy`
  (single-file, 512K downloads, 1261 likes), base `flux-3-image-klein`
  (diffusers, 102K / 625 likes), `-base` (undistilled, 105K / 164
  likes), plus `-pup` (Qwen3.5-9B-based prompt upsampler). When the
  operator takes the `flux3klein` `_reg()` already on disk from stub
  to validated, the question is whether to also wire the `-pup`
  prompt-upsampler as an optional pre-step in `llm_delegate.py`
  (analogous to the Z-Image prompt enhancer the 2026-10-16 digest
  queued) or leave the `_reg("flux3klein", …)` as weights-only. The
  `-pup` repo is Apache-2.0 licensed, so the licensing is cleaner than
  the base Klein's "other" license.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 and 2026-09-22 entries that
have not been reported as actioned, plus this run's new ones. A local
Hermes / operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-10-22 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/MOSS-Image
    target_host: spark1
    reason: "MOSS-Image is the strongest NEW open-license (Apache-2.0) image arch on the HF trending board as of this digest (1.46M downloads on the Comfy-Org repack, Trending Score 332). Needs a fleet-side benchmark against Flux-3-Klein and Qwen-Image-2.1 before an operator call on whether to add a _reg('moss_image', ...) entry. The Comfy-Org repack is diffusion-single-file → drops straight into ComfyUI/models/checkpoints/."
    command_hint: "huggingface-cli download Comfy-Org/MOSS-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MOSS-Image"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: lodestones/MOSS-Image-SFT-8-steps-dmd
    target_host: spark1
    reason: "Paired 8-step distill for MOSS-Image. Only download after the base MOSS-Image evaluation above decides the arch is worth adding to the fleet."
    command_hint: "huggingface-cli download lodestones/MOSS-Image-SFT-8-steps-dmd --local-dir D:\\LLM\\ComfyUI\\models\\loras\\MOSS-Image-8step-dmd"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Fourth LTX-2.5 IC-LoRA to queue. Camera-control / storyboard-to-video is a distinct task from the three IC-LoRAs the 2026-10-16 digest already queued (Alpha-Gen, Pixel-Spatial-Upscaler, Refine-Details, Ingredients). Depends on LTX-2.5 base weights (previous digest's Tier-3 download)."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout-Render"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate
    target_host: spark1
    reason: "Object-removal video adapter on LTX-2.5. Pairs with the already-queued Alpha-Gen (BG/matte removal) to cover the full 'remove unwanted stuff from video' lane. ~2 GB, same license contract as the base LTX-2.5."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Clean-Plate"
    risk: low

  - action: evaluate_vlm_swap
    target_repo: deepseek-ai/DeepSeek-V4.1-Flash-1017
    target_host: theo
    reason: "Top of the HF trending board this cycle (Trending Score 2013). MIT-licensed vision + reasoning VLM, fp8 single-file. Candidate to replace or complement the current DeepSeek row the fleet runs in LM Studio for llm_delegate.py preflight. Would need a bench vs. the fleet's current preflight LLM on prompt-enhancement quality + latency before a swap. Theo-local is where LM Studio runs — this evaluation happens there, not on a Spark."
    command_hint: "huggingface-cli download deepseek-ai/DeepSeek-V4.1-Flash-1017 --local-dir D:\\LLM\\LMStudio\\models\\deepseek-ai\\DeepSeek-V4.1-Flash-1017"
    risk: medium

  - action: evaluate_prompt_upsampler
    target_repo: black-forest-labs/flux-3-image-klein-pup
    target_host: unknown
    reason: "Apache-2.0 licensed prompt-upsampler for Flux-3-Klein — paired with the 2026-10-16 digest's Flux-3-Klein download. Builds on Qwen3.5-9B, so if the fleet already has that base loaded, this is a LoRA-style finetune on top. Only matters if the operator picks Flux-3-Klein as the Klein successor; defer until that call."
    command_hint: "huggingface-cli download black-forest-labs/flux-3-image-klein-pup --local-dir D:\\LLM\\LMStudio\\models\\black-forest-labs\\flux-3-image-klein-pup"
    risk: low

  # ─── Carried over, still open ─────────────────────────────────────

  # The 2026-10-16 digest's Tier-3 queue (Flux-3-Klein-comfy,
  # Qwen-Image-2.1-Turbo, SAM 3.1 + audit, SAM 3D body/objects, LTX-2.5
  # IC-LoRA Alpha-Gen / Pixel-Spatial-Upscaler / Refine-Details /
  # Ingredients, Z-Image controlnet, Qwen-Image-2.1 base,
  # Lightricks/LTX-2.5 base, hunyuan3D_2.1_repackaged,
  # rerun_upgrade_research_from_lan, audit_retirable_weights) is
  # unchanged by this run. Rather than restate 11 verbatim YAML blobs
  # here, consider the 2026-10-16 digest's local_action_queue the
  # authoritative live list and this one its 2026-10-22 delta.

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "The HF arch-query map now covers 35 arches (up from 27 at the 2026-10-16 run) so a live LAN run of tools/upgrade_research.py now has 8 extra arches to probe. If this routine is going to migrate from skeleton-mode to full-mode, now is a cheaper time than later."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is STILL a Tier-3 TODO.** Named
   in the 2026-09-22 and 2026-10-16 digests' Tier-3 queues but never
   written. With the fleet now holding 29 fully-registered arches +
   growing LoRA/IC-LoRA/controlnet weight sets, the "which weights can
   be retired" question is getting harder every digest. The 2026-10-16
   digest already scoped it as ~100-line Tier-1 candidate (read
   `architectures.py` + walk `ComfyUI/models/*`, print paths matching
   `registered=True` arches that have more than one weights candidate
   on disk). Not shipped this run because the tool's hot path walks
   `D:\LLM\ComfyUI\models\*` which the cloud sandbox cannot reach, so
   drafting it here without a target directory to validate against
   risks shipping an untested tool. If a future digest can be run from
   a LAN host, this becomes the first Tier-1.

2. **Transport fallback for `tools/upgrade_research.py`.** Same gap
   the 2026-09-22 and 2026-10-16 digests flagged — the tool's HF and
   civitai backends use `urllib` → `safe_fetch`, which the cloud
   proxy 403s. Teaching the `huggingface` backend to prefer an MCP
   transport when one is available would let *this* routine run the
   ranked backend from the cloud instead of the skeleton one. Still
   broadens the tool's dependency surface (would need an MCP client
   in-process or a sidecar), so not shipped. Promoting to a formal
   Tier-1 for a future digest.

3. **`flux3klein` + `flux2dev` + `krea2` + `qwen_image` are
   `registered=True` already.** The v2.4 Spark2 push landed them as
   full `_reg()` entries, not stubs. Means the architecture-level
   plumbing is ready; the question that stays Tier-2 is "when do the
   WEIGHTS land on D:\LLM, and does the fleet want to retire the
   predecessors (flux2klein, flux1dev base) at the same time?" That's
   covered by the pending `audit_disk_vs_registry.py` work above.

4. **Prior-run follow-ups still open.**
   - `tools/audit_disk_vs_registry.py` (above, 2nd time filed).
   - MCP transport fallback for `upgrade_research.py` (above).
   - `fetch_metadata.py` TLS flag — confirmed resolved by the
     2026-10-16 digest, carried as closed.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`, `hf_fs`;
local `tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`._
