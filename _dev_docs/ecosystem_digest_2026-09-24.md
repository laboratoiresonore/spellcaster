# Ecosystem digest — 2026-09-24

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
at `ecf4249` (Tier-1 security stack from PRs #178/#181 landed 09-24 morning;
the 2026-09-22 digest itself is now merged as PR #174). Branch:
`claude/adoring-allen-zf394v`.

## Delivery notes

- **Prior digest merged.** PR #174 (the 2026-09-22 sweep + 6 Tier-1 fixes)
  merged into `main` this morning. Prior backlog concern about ten stacked
  open digest PRs (#164–#173) is largely resolved — all except #166 are now
  closed, and the routine's "queue vs cadence" pressure has eased.
- **CI leak-check on `main` is clean.** Verified locally by running the
  same `git grep -nIEi` invocation the workflow uses against HEAD's
  tracked tree — no hits. The prior digest's Follow-up #1
  ("`.github/workflows/leak-check.yml` self-hits tracked files, extend
  exclusions") is stale; whatever tripped it earlier is no longer present
  on today's `main`. Dropping that item from the Follow-ups queue.
- **`fetch_metadata.py` TLS re-audit.** Prior digest's Follow-up #2 claimed
  `context.check_hostname = False` / `verify_mode = CERT_NONE`. Re-read
  today: only `ctx = ssl.create_default_context()` — the SECURE default,
  no override anywhere in the file. Prior read was mistaken (probably on
  a stale copy). Dropping from the Follow-ups queue.
- **`tools/upgrade_research.py`** is present and `--dry-run` clean
  (`4 proposals from 5 backends`). The tool's `huggingface` and `civitai`
  backends still can't reach through the sandbox proxy (403 at CONNECT),
  so live rankings this run come from the HF MCP connector directly
  (~4 calls of the 25-call budget) rather than the tool's own backends.
- **Gmail / Google-Drive MCP** — not called this run; delivery via the PR.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix is
in this branch and whose regression suite passes (`pytest tests/` →
52/52 green).

### T1-a `DEEP_DIVE.md` line 649: per-arch prompt-enhance profile count is 2 low

The prose says `_ARCH_ENHANCE_PROFILES` carries "9 architectures each with
their own `max_tokens`…", but the actual dict in
`comfyui-spellcaster/spellcaster_core/prompt_enhance.py:70` has **11**
keys: `flux1dev, flux2klein, chroma, sdxl, sd15, illustrious, pony, wan,
ltx, sd3, sd3_turbo`. Verified by AST-walking the module and reading
the dict literal directly.

Bumped `9 architectures` → `11 architectures`. Rest of the paragraph
still describes the same qualitative examples (SDXL booru tags, Flux
verbose NL, Klein bullets, Illustrious subject-preservation) — those
are all still true on today's HEAD, so the surrounding prose is left
alone.

### T1-b `DEEP_DIVE.md` line 922: `ArchConfig` registry count is 12 low

Prose says "**9-architecture `ArchConfig` registry**", but the actual
registry has **21 fully-registered** archs (13 `_reg(..., registered=True)`
explicit + 8 default-registered) plus **6 stubs** marked
`registered=False`. Prior digest's mermaid at DEEP_DIVE.md:64 already
says `27 arch registry`, and the prose line here should reflect the same
truth. Bumped `9-architecture` → `21-architecture` to match the
fully-wired count (stubs don't drive a builder yet, so "21" is the
count that carries the "**one object drives every builder**" claim in
the same sentence).

Verification (AST walk on `plugins/gimp/comfyui-connector/spellcaster_core/architectures.py`):

- 21 active archs: `chroma, cogvideo, flux1dev, flux2klein, flux_kontext,
  framepack, hunyuan_3d, hunyuan_video, illustrious, ltx, lumina2, mochi,
  playground, pony, sd15, sdxl, sdxl_turbo, seedvr, supir, wan, zit`.
- 6 stubs: `auraflow, hunyuan_dit, kolors, pixart, sd3, sd3_turbo`.

### T1-c `architectures.py` docstring: `SUPPORTED ARCHITECTURES` enumeration is stale

The module docstring in both mirror copies

- `plugins/gimp/comfyui-connector/spellcaster_core/architectures.py:21`
- `comfyui-spellcaster/spellcaster_core/architectures.py:21`

enumerates only **7** archs under `SUPPORTED ARCHITECTURES` (`sd15,
sdxl, illustrious, zit, flux1dev, flux2klein, flux_kontext`) — the
original April-2026 list that the prior digest bumped the *date* on
but not the *content* (that pass explicitly deferred content-refresh
to a future Tier-2).

Regenerated the enumeration from the live `_reg(...)` set, split into
three sections (`Image`, `Video`, `3D / restoration`) plus a compact
one-line "Stubs" callout. Both copies now list all 21 active archs +
name the 6 stubs. Added a closing line reminding future editors that
the `ARCHITECTURES` dict below is the source of truth and this list
is the human-readable index that should be regenerated when new archs
land — reduces the chance the next sweep finds the same drift.

Kept the layout so future counts (e.g. "22 fully-registered") don't
require restructuring the block — one new line per new arch.

**Verification of T1-a through T1-c**

- `pytest tests/` — `52 passed in 8.02s` on the branch (matches
  `origin/main` — no regression).
- `python tools/upgrade_research.py --dry-run` — clean, `4 proposals
  from 5 backends`.
- Leak-check dry-run (same `git grep -nIEi` invocation as
  `.github/workflows/leak-check.yml`) — no hits on the branch.
- Docstring-content changed but no code path reads the docstring; the
  registry itself and every dependent (`get_arch`, `_reg`, the
  ArchConfig class) are untouched.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced this run via HF MCP `hub_repo_search` — 4 calls (`text-to-image`
trending, `image-to-video` trending, `flux kontext` lastModified,
`LTX 2.5` free-text). Signals below are 2026-09-24 values.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Qwen/Qwen-Image-2.1** | 2026-09-14 | New `qwen_image` arch — no current coverage | ~16 GB fp8, ~30 GB fp16 (7.1B) | medium | 2 | **Still the #2 trending model on HF Hub** (2,154 likes ↑ from 1,701 at 09-22; 37.6K base downloads). Comfy-Org repackage `Comfy-Org/Qwen-Image-2.1` now at **2.9M downloads** (↑ from 1.4M at 09-22) — the ComfyUI-native path is clearly the operator's landing target. Same integration shape as prior digest: `build_qwen_image_txt2img` (`build_illustrious_txt2img`-shape) + `_reg("qwen_image", …)`. Still Tier 2 — no code shipped for it yet in-repo. |
| **Lightricks/LTX-2.5** | 2026-07-23 | Direct successor to current `ltx` arch (2.3-shape weights) | ~24 GB video | medium | 2 | **4,968 likes, 1.6M downloads** — the dominant open image-to-video path today. `_reg("ltx", …)` at `architectures.py:974` still points at 2.3-shape config. Straight version-swap keeps the builder set stable; the `LTX 2.5 22b` variant is the one Lightricks is shipping IC-LoRA add-ons for. Gated on HF (`license:other`) — the operator has HF login on the LAN. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler** | 2026-08-11 | NEW LoRA add-on that adds a **video spatial-upscaler pass** on top of the base LTX-2.5 workflow | ~4-6 GB LoRA overhead | low | 2 | 97 likes / 6.3K downloads. `video_upscale` is currently a first-class method in `VIDEO_METHODS` but the LTX arch's implementation is minimal. This IC-LoRA drops in as a second stage after `build_ltx_video`. Same tier as the base 2.5 landing — ships with it. |
| **LiconStudio/LTX-2.5-Multiple-Subject-Reference** | 2026-08-14 | LoRA for LTX-2.5 that adds **multi-subject reference control** (e.g. `person + prop + backdrop` each with a reference image) | ~4 GB LoRA overhead | medium | 2 | 85 likes / 10.6K downloads. `build_wan_animate` currently owns the "person-with-reference" video path; a multi-reference variant for LTX-2.5 would extend `build_ltx_video` towards the same use case without swapping arch. Arxiv 2609.18393 published alongside — reference-guided-video-generation. |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate** | 2026-09-09 | LoRA for LTX-2.5 that does **VFX clean-plate / object-removal** on video | ~4 GB LoRA overhead | low | 2 | 14 likes / 622 downloads — small but semantically distinct: this is essentially `video_inpaint` for the ltx arch (which spellcaster doesn't currently expose). Would land as `build_ltx_clean_plate` gated to the ltx arch. |
| **CQdesign/LTX-2.5-CQ-Video-and-Image-Enhancer-LoRAs** | 2026-08-15 | Quality-enhancement LoRA pack for LTX-2.5 | ~2-4 GB LoRA overhead | low | 2 | 147 likes — third-party quality LoRA bundle. If LTX-2.5 lands as base arch, this becomes an autoset LoRA for the "quality" preset on `build_ltx_video`. |
| **abenzerps/Qwen-Image-2.1-Uncensored-GGUF** | 2026-09-20 | GGUF quantization of Qwen-Image-2.1 base — **NSFW-flagged variant** | ~10 GB Q4_K_M | — | — | 1,581 likes / 575.7K downloads. **Explicitly `Uncensored` in the repo name** → per Spellcaster's H6 SFW canon rule (`_HF_NSFW_NAME_PATTERNS` in `tools/upgrade_research.py`), this belongs in the NSFW-pack backend's queue, NOT this SFW digest. Flagged here only to explain why the trending #4 model is deliberately excluded from the SFW landing pipeline. |
| **Comfy-Org/flux1-kontext-dev_ComfyUI** | 2025-06-25, last touched 2026-09-23 | Comfy-Org repackage of Flux Kontext — the `flux_kontext` arch we already `_reg(...)` | ~24 GB fp16 | low | 2 | 193 likes / 134K downloads. Comfy-Org bumped this repackage yesterday, which suggests a Comfy-side node-shape refresh — worth diffing against whatever the operator has under `D:\LLM\ComfyUI\models\` before the next `build_edit_by_instruction` regression pass. |

### Tier-2 non-model finding

- **`build_qwen_image_txt2img` builder + `qwen_image` arch registration
  are still absent from the repo** despite the model being 10+ days old
  and dominating trending downloads. The wire-up is a 30-line change
  (one `_reg(...)` block + one builder + one `arch_probes` entry) but
  the safe-integration checklist (loader shape, sampler, CFG default,
  VAE filename convention) needs the operator's LAN eyes on the real
  weights first. Still Tier 2, not Tier 1.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Structured entries below. A local Hermes / operator process consumes
this block mechanically. Every `command_hint` is best-effort — the
operator adjusts for the fleet's exact model-directory layout.

```yaml
local_action_queue:
  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Restated from 2026-09-22 digest — still the dominant new-arch signal (Comfy-Org repackage now at 2.9M downloads, ↑ from 1.4M in 48h). Evaluate against existing SDXL/Flux2Klein routes for text-to-image quality before wiring _reg('qwen_image', ...)."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Restated from 2026-09-22 digest — still the direct upgrade path for _reg('ltx', ...). Gated on HF (`license:other` — needs the LAN's HF login the cloud sandbox doesn't have). Before swap, back up the current 2.3-shape weights and diff generation output on the shared eval prompt set."
    command_hint: "huggingface-cli login  # if not already, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_lora
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "NEW this cycle — official Lightricks video-upscaler IC-LoRA for LTX-2.5. Ships in the SAME PR as the LTX-2.5 base landing (both live in the ltx arch's stack). ~1 GB download."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\ltx"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate
    target_host: spark1
    reason: "NEW this cycle — official Lightricks clean-plate / object-removal IC-LoRA for LTX-2.5. If it works well, becomes the video_inpaint path for the ltx arch (currently missing)."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate --local-dir D:\\LLM\\ComfyUI\\models\\loras\\ltx"
    risk: low

  - action: download_and_evaluate_lora
    target_repo: LiconStudio/LTX-2.5-Multiple-Subject-Reference
    target_host: spark1
    reason: "NEW this cycle — third-party multi-subject-reference LoRA for LTX-2.5. Extends the ltx arch towards the animate-with-reference use case currently owned by wan. Read the arxiv (2609.18393) before shipping — architecture may need a small conditioning-injection tweak."
    command_hint: "huggingface-cli download LiconStudio/LTX-2.5-Multiple-Subject-Reference --local-dir D:\\LLM\\ComfyUI\\models\\loras\\ltx"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: CQdesign/LTX-2.5-CQ-Video-and-Image-Enhancer-LoRAs
    target_host: spark2
    reason: "NEW this cycle — third-party quality-enhancement LoRA bundle for LTX-2.5. Optional; ship as autoset LoRA on the quality preset if quality gain is measurable."
    command_hint: "huggingface-cli download CQdesign/LTX-2.5-CQ-Video-and-Image-Enhancer-LoRAs --local-dir D:\\LLM\\ComfyUI\\models\\loras\\ltx"
    risk: low

  - action: refresh_comfy_kontext_repackage
    target_repo: Comfy-Org/flux1-kontext-dev_ComfyUI
    target_host: unknown
    reason: "Comfy-Org repackage was last touched 2026-09-23 (one day ago). Suggests a Comfy-side node-shape refresh. Diff the on-disk file against the newest repackage before the next build_edit_by_instruction regression pass."
    command_hint: "huggingface-cli download Comfy-Org/flux1-kontext-dev_ComfyUI --revision main --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux1-kontext-dev"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "The cloud sandbox's egress proxy still denies direct HF and civitai CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode (--dry-run: 4 stub proposals). Running the same tool from the LAN will exercise the real HF + civitai backends and produce the ranked shopping list this run couldn't."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If Qwen-Image-2.1 lands as a text-to-image default and LTX-2.5 replaces LTXV-2.3, the older weights on D:\\LLM should be flagged for retirement to free space. Prior digest already noted this needs tools/audit_disk_vs_registry.py (does not yet exist). Not in scope for the cloud sandbox to build — needs the disk layout."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items I saw but did not fix in this run — either scope-larger-than-safe,
or ambiguous enough to want the operator's read first.

1. **Auto-regenerate `architectures.py` docstring enumeration.** This run's
   T1-c fixed the enumeration by hand, but the underlying pattern (docstring
   drifts from `_reg(...)` set) will recur next time an arch lands. A
   pre-commit hook that AST-walks `_reg(...)` calls and rewrites the
   `SUPPORTED ARCHITECTURES` block would remove the drift entirely. Small
   diff (< 100 lines), no runtime behaviour change; deferred because it
   changes the pre-commit hook set and the operator should choose the
   trigger.

2. **Wire `Qwen-Image-2.1` as `qwen_image` arch.** Still the strongest
   Tier-2 signal (10+ days trending). The wire-up is small but needs the
   LAN's real weights to pick loader shape / VAE filename / sampler
   defaults. Same status as 09-22 — no code shipped yet.

3. **`_ARCH_ENHANCE_PROFILES` vs `ArchConfig` registry drift.** Enhance
   profiles cover 11 archs; ArchConfig covers 21 active. The 12 active
   archs without an enhance profile (`cogvideo, flux_kontext, framepack,
   hunyuan_3d, hunyuan_video, lumina2, mochi, playground, sdxl_turbo,
   seedvr, supir, zit`) currently fall through to
   `_DEFAULT_ENHANCE_PROFILE`. That's likely correct for the
   restoration + 3D archs (`supir`, `seedvr`, `hunyuan_3d`) but likely
   wrong for the image generators (`lumina2`, `zit`) and the edit-shape
   arch (`flux_kontext`). Small mechanical addition, but each new
   profile is an operator judgement call about tokens/style — deferred.

4. **Digest cadence review.** With PR #174 merged, the "queue vs cadence"
   pressure has eased. If a future run finds itself again stacking
   digests against unmerged predecessors, dial the cadence back rather
   than let the queue grow.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search` (~4 calls);
local `tools/upgrade_research.py --dry-run`; git AST scans of
`architectures.py`, `prompt_enhance.py`, `workflows.py`,
`builders_manifest.json`._
