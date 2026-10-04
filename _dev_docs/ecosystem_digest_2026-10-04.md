# Ecosystem digest — 2026-10-04

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-cq66oe`.

## Delivery notes

- **Backlog visibility** — PRs **#166, #183, #184, #185, #186, #187** are
  still open from the previous six runs of this routine. All six stack
  independently on `main` (same baseline `ecf4249`); some overlap on the
  same Tier-1 drift fixes by design, so merging *any one* moves the
  needle for that overlap. This PR (#TBD) will become the seventh in the
  queue. **Operator decision needed**: merge the oldest one and close the
  rest as duplicates, or pause the every-48h cadence until the queue
  drains. The cadence is clearly producing faster than the review queue
  consumes it.
- **No merged consolidation** since 2026-09-22 (PR #174 → `2ebdf38`).
  The three security PRs that landed afterwards (`cd01ad2`, `0c898f3`,
  `329761b`) were separate work and did not touch the stale drift this
  routine tracks.
- **`tools/upgrade_research.py` present** — contract honored; local
  dry-run produced `_dev_docs/upgrade_research/2026-W40.{md,json}`
  (4 proposals from 5 backends; the sandbox proxy 403s the real HF /
  civitai CONNECT so backend data stays skeleton — see 2026-09-22
  follow-up #3). The W40 output is committed in this PR.
- **Gmail / Google-Drive MCP** — not called this run; delivery is this
  PR. Both connectors are reachable but this cycle produced nothing
  requiring their surfaces.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes:

- `pytest tests/` → **52 passed** (same as `origin/main` baseline — no
  regression from the edits).
- `python tests/mirror_drift.py` → **29/29 byte-identical**.
- `python tests/night_maintenance.py --dry-mode --quiet` → **exit 0**.
- AST-parsed each edited `.py` to confirm no syntax breakage.

| ID    | File | Line | Change | Novel? |
|-------|------|------|--------|--------|
| T1-a  | `README.md` | 46 | `Status — September 2026` → `October 2026` (2-day-old banner stale by one month) | overlaps PR #187 |
| T1-b  | `README.md` | 200 | `Text to Image across 9 model families` → `10` (DEEP_DIVE enum lists 10) | **novel** |
| T1-c  | `DEEP_DIVE.md` | 3 | `all 9 model families` → `10` (same source of truth) | **novel** |
| T1-d  | `DEEP_DIVE.md` | 649 | `_ARCH_ENHANCE_PROFILES` cites `9 architectures` → **11** (AST count of dict keys = 11: flux1dev, flux2klein, chroma, sdxl, sd15, illustrious, pony, wan, ltx, sd3, sd3_turbo) | overlaps PR #185 |
| T1-e  | `DEEP_DIVE.md` | 922 | `9-architecture ArchConfig registry` → `21-architecture ... (27 _reg entries, 21 fully active and 6 marked registered=False as stubs)` — adds the explicit stub distinction, so the number no longer disagrees with the mermaid at L64 (`27 arch registry`) OR with the operator's distinction between stubbed and active archs | expanded vs PR #183 |
| T1-f  | `DEEP_DIVE.md` | 934 | `22,000 lines of Python` → `~35,700 lines` (ground truth: `find … -name '*.py' \| xargs wc -l` on `plugins/gimp/comfyui-connector/spellcaster_core/` = 35,723) | sharper vs PR #186 (`~34,000`) |
| T1-g  | `DEEP_DIVE.md` | 936 | `9 model architectures` → `10` | overlaps PR #186/#187 |
| T1-h  | `plugins/gimp/comfyui-connector/spellcaster_core/architectures.py` | 21 | docstring `(as of September 2026)` → `(as of October 2026)` | overlaps PR #187 |
| T1-i  | `comfyui-spellcaster/spellcaster_core/architectures.py` | 21 | same, mirror-identical | overlaps PR #187 |
| T1-j  | `installer/installer_gui.py` | 894 | `"69 AI tools — generate images..."` → `75` (customtkinter banner the user sees before install) | overlaps PR #185 |
| T1-k  | `installer/install.py` | 2075 | `"Every one of the 69 tools gets better output..."` → `75` (CLI text) | overlaps PR #185 |
| T1-l  | `scaffold/spellcaster_wizard.py` | 82 | docstring example `"total_methods": 69` → `75` (shows the shape of the context payload the scaffold builds for the LLM) | **novel** (not in PR #185 which only hit line 182) |
| T1-m  | `scaffold/spellcaster_wizard.py` | 182 | LLM system-prompt `GIMP 3 — 69 AI tools` → `75` (actively misinforming the local LLM) | overlaps PR #185 |
| T1-n  | `plugins/gimp/comfyui-connector/_spellcaster_main.py` | 1174 | GIMP status-panel splash `GIMP + ComfyUI + 69 AI tools` → `75` | overlaps PR #185 |
| T1-o  | `tavern/static/setup.html` | 132 | `69 AI tools directly into your editor's menu` → `75` | overlaps PR #184/#185 |
| T1-p  | `tavern/static/setup.html` | 136 | `All 69 tools under Filters → Spellcaster` → `75` | overlaps PR #184/#185 |

**Source-of-truth references used**

- `plugins/gimp/comfyui-connector/spellcaster_core/builders_manifest.json` →
  `method_count: 75`.
- `grep -c '^def build_' plugins/gimp/comfyui-connector/spellcaster_core/workflows.py`
  = 75.
- AST walk of `_reg(...)` calls in `architectures.py` → 27 entries,
  of which 6 carry `registered=False`.
- AST walk of `_ARCH_ENHANCE_PROFILES` keys in `prompt_enhance.py` → 11.
- `wc -l` of `plugins/gimp/comfyui-connector/spellcaster_core/*.py` →
  35,723 total.

**Why most T1 fixes overlap earlier open PRs**: per the routine's design
(see 2026-10-02 digest), each PR stacks on `main` independently so the
branch stands alone and merging any single one moves the needle. T1-b,
T1-c, T1-l are **novel** this cycle; T1-e is sharpened (adds explicit
stub distinction so it doesn't contradict the mermaid at L64); T1-f is
sharpened (35,700 vs the previously-quoted 34,000, closer to the
real 35,723).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP `hf_fs ls hf://models/trending` +
`hub_repo_search`. Budget used: **5 MCP calls** of the ~25-call soft
budget.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Lightricks/LTX-2.5** | 2026-10-02 (modified) | Direct successor to `_reg("ltx", …)` currently 2.3-shape | ~24 GB fp16 (BF16/NVFP4/INT8/GGUF variants exist via `stablediffusiontutorials/Ltx-2.5`) | medium | 2 | 6,232 likes / 1.63M downloads, now **#4 trending** overall. Picks up `image-to-video`, `text-to-video`, `video-to-video`, `audio-to-video`, `text-to-audio-video` tags — the single-pipeline multimodal model. Gated=auto on HF (needs login). **Three official IC-LoRAs** in-arch: `Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render` (995 DL, camera-control), `Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen` (1.7K DL, alpha-matte VFX/background-removal). Plus community `CQdesign/LTX-2.5-CQ-Video-and-Image-Enhancer-LoRAs` (166 likes). This is the strongest single Tier-2 signal of the cycle. |
| **Qwen/Qwen-Image-2.1** | 2026-09-30 | New `qwen_image` arch — no current coverage | ~16 GB fp8, ~30 GB fp16 (7.1B params) | medium | 2 | 2,927 likes / 90K downloads on the base repo (up from 2,700/70K @ 09-30). Would land as `build_qwen_image_txt2img` + a new `_reg("qwen_image", …)`. See 2026-09-22, 09-26, 09-28 digests for the running integration-notes thread. |
| **alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union** | 2026-09-24 | ControlNet-Union for a *new* `qwen_image` arch (requires base to land first) | ~2 GB extra | low (contingent) | 2 | 52 likes / 22.5K downloads. `videox_fun` library repo. If/when `qwen_image` lands as a Spellcaster arch, this unlocks `build_controlnet_gen` on it in the same PR. The `t8star` ComfyUI mirror (`t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy`) is one week old and ready-to-use. |
| **Viggle/Qwen-Image-2.1-viggle-turbo** | 2026-10-01 | Turbo (fast-sampling) distill for a new `qwen_image` arch | same as base | low | 2 | 581 likes / 272K downloads in <72h. Companion to the base model — if `qwen_image` lands, this is the sub-second preview path. |
| **vnbot-ai/FLUX.2-klein-4B-GGUF** | 2026-10-03 | GGUF path for existing `flux2klein` arch (4B variant) | ~7 GB Q4 | low | 2 | Fresh GGUF repackage of `black-forest-labs/FLUX.2-klein-4B`. Would wire as a `klein_backend="gguf"` setting on the existing arch, co-landing with the `klein_backend="base"` path. Companion to the trmz/flux2-klein-alpha RGBA/transparency LoRA already flagged in the 2026-09-30 digest. |
| **AcademiaSD/FLUX.2-Klein-9B-NF4-for-LoRA-Training** | 2026-10-03 | NF4 (bitsandbytes) quantization for the 9B `flux2klein` arch, LoRA-training-oriented | ~11 GB NF4 | low | 2 | Not for the main generation path, but relevant to users building their own 9B-Klein LoRAs on 16-GB cards. Operator decides whether this is in scope. |
| **Comfy-Org/HunyuanVideo_1.5_repackaged** | 2026-09-23 (modified) | Direct drop-in for a `hunyuan_version="1.5"` opt-in on `build_hunyuan_video` (per prior PR #48's design) | ~16 GB (8.3B GGUF path exists) | medium | 2 | 101 likes / 681K downloads. The Comfy-Org single-file repackage is the ready-to-use path. PR #48 (open since May 2026) scaffolded the opt-in machinery — this would operationalize it. The step-distilled i2v variant (`hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v_step_distilled`) is the low-VRAM path. |
| **Comfy-Org/Wan_2.2_ComfyUI_Repackaged** | 2025-07 (ongoing) | Already in use as `wan` arch — flagged here only to confirm 6.5M downloads / 910 likes, i.e. this remains the dominant open-source I2V path, so no deprecation pressure | — | — | — | Status-quo check: `wan` arch's current pointer is still the right one. |

### Tier-2 non-model finding

- **Six-way PR backlog on open ecosystem digests** (#166, #183, #184, #185, #186, #187) → **operator decision**: either (a) merge the oldest and close the rest marking the overlap as duplicate, or (b) pause the every-48h cadence until the queue drains. See Delivery notes above.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Structured entries below. A local Hermes / operator process consumes
this block mechanically instead of a human re-deriving the command from
prose. Every `command_hint` is best-effort — the operator adjusts for
the fleet's exact model directory layout.

```yaml
local_action_queue:
  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: spark1
    reason: "Direct upgrade path for _reg('ltx', ...); 2026-10-02 modification lifted it to #4 trending overall with 6,232 likes. Multimodal (video+audio in one pipeline) worth evaluating against existing LTXV-2.3 route. Gated=auto on HF — cloud sandbox cannot authenticate, so this is fleet-only. If 2.5 produces better temporal coherence at same VRAM, retire LTXV-2.3 weights per audit_retirable_weights below."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Official LTX-2.5 IC-LoRA for camera-control / layout-to-render — pairs with the LTX-2.5 base. Ships alongside the base in the same integration PR."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\ltx-2.5-ic\\layout-to-render"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Official LTX-2.5 IC-LoRA for alpha-matte / background-removal (VFX). Enables build_video_bgremove on the ltx arch once LTX-2.5 is in place."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\ltx-2.5-ic\\alpha-gen"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "New arch candidate (Tier-2). Comfy-Org single-file repackage drops into ComfyUI/models/checkpoints/ with no diffusers plumbing. Evaluate against existing Flux2Klein/SDXL routes before wiring _reg('qwen_image', ...). Running tracker since 2026-09-22; 2026-10-04 trending numbers still growing."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union
    target_host: spark1
    reason: "ControlNet-Union for qwen_image arch (contingent on base landing). Co-land with Comfy-Org/Qwen-Image-2.1 in the same integration PR to unlock build_controlnet_gen on qwen_image. The t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy mirror is the ready-to-use variant for the ComfyUI node graph."
    command_hint: "huggingface-cli download t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Qwen-Image-2.1-Fun-Union"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Viggle/Qwen-Image-2.1-viggle-turbo
    target_host: spark2
    reason: "Turbo distill (fast-sampling) of Qwen-Image-2.1 — 272K downloads in <72h. If qwen_image lands, this is the <1s preview path for the UI. Download only after the base evaluation is done."
    command_hint: "huggingface-cli download Viggle/Qwen-Image-2.1-viggle-turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1-viggle-turbo"
    risk: low

  - action: download_and_evaluate_model
    target_repo: vnbot-ai/FLUX.2-klein-4B-GGUF
    target_host: spark2
    reason: "GGUF path for flux2klein arch's 4B variant — unlocks the 4B Klein path on cards that can't run safetensors fp8. Wire as klein_backend='gguf' setting alongside the existing fp8 path. Low-risk because the arch is already wired; only the loader shape changes."
    command_hint: "huggingface-cli download vnbot-ai/FLUX.2-klein-4B-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\FLUX.2-klein-4B-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/HunyuanVideo_1.5_repackaged
    target_host: spark1
    reason: "Operationalizes the hunyuan_version='1.5' opt-in that PR #48 scaffolded in May 2026 but never got weights for. Comfy-Org single-file repackage is the ready-to-use path. 681K downloads validates the ComfyUI community has moved. Also pull hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v_step_distilled as the low-VRAM path."
    command_hint: "huggingface-cli download Comfy-Org/HunyuanVideo_1.5_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan_video\\1.5"
    risk: medium

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Still a standing entry — the cloud sandbox's egress proxy denies HF/civitai CONNECT (403), so tools/upgrade_research.py falls back to skeleton mode (--dry-run: 4 stub proposals). Running from the LAN exercises real HF + civitai backends and produces the ranked shopping list this run couldn't."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index --methods build_illustrious_txt2img,build_wan_video,build_klein_repose,build_hunyuan_video,build_qwen_image_txt2img"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 lands as default I2V and Qwen-Image-2.1 joins the arch set, the older LTXV-2.3 weights and any legacy SDXL variants that newer archs supersede should be flagged for retirement to free D:\\ space. Human decision but audit itself is mechanical. Tool does not yet exist; see Follow-ups below."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; see Follow-ups below."
    risk: low

  - action: hand_off_to_nsfw_pipeline
    target_repo: abenzerps/Qwen-Image-2.1-Uncensored-GGUF
    target_host: unknown
    reason: "3,038 likes / 1.55M downloads on the trending list. SFW-canon rule (H6) keeps this out of the public spellcaster repo. Hand-off to spellcaster_NSFW if that pipeline is active and wants it."
    command_hint: "# forward to spellcaster_NSFW routine, not to the public repo"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items I saw but did not fix in this run — either scope-larger-than-safe,
or ambiguous enough to want the operator's read first.

1. **`generate_showcase.py` label count** — follow-up #4 from the
   2026-09-22 digest; still untouched. The showcase generator may still
   emit `69` label text in rendered assets if its hardcoded count was
   never bumped. Would need to run the generator locally against a
   ComfyUI to verify what the surface actually shows today — out of
   sandbox scope.

2. **`tools/audit_disk_vs_registry.py` does not exist** — referenced
   from the Tier-3 queue for months. Would compare `D:\LLM\…` directory
   layout against the active `_reg(registered=True)` arch set and flag
   dead weights. Mechanical to write; needs the operator's canonical
   `D:\LLM\…` tree to validate paths against. Candidate for next-run
   Tier-1 if the tree layout is confirmed stable.

3. **`tools/upgrade_research.py` transport fallback** — still true: the
   tool's HF and civitai backends use stdlib `urllib`, which the sandbox
   proxy 403s at CONNECT time. Teaching it to prefer the HF MCP transport
   when one is available would let this routine run the *real* backend
   from the cloud instead of the skeleton one. Not shipped because it
   broadens the tool's dependency surface beyond stdlib.

4. **Backlog decision** (repeated from Delivery notes above) — six
   stacked ecosystem-digest PRs without merges. The routine will keep
   generating one every 48h unless paused. Operator picks:
   consolidate-and-close, or pause.

5. **PR #48 (ComfyUI workflow export + nightly routine)** — open since
   2026-05-19, blocked on operator install of ComfyUI v0.21+ for the
   SAM 3.1 native path. The HunyuanVideo-1.5 opt-in piece of that PR is
   now co-ready with the Comfy-Org repackage (see Tier-2 above). Worth
   a fresh look.

6. **Leak-check pattern coverage** — not re-verified this run. Prior
   2026-09-24 digest confirmed it was clean on main after the security
   PR run; monitoring but not acting.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hf_fs`, `hub_repo_search`;
local `tools/upgrade_research.py --dry-run` (output committed to
`_dev_docs/upgrade_research/2026-W40.{md,json}`); git AST scans of
`architectures.py`, `prompt_enhance.py`, `workflows.py`,
`builders_manifest.json`; `wc -l` on
`plugins/gimp/comfyui-connector/spellcaster_core/`._
