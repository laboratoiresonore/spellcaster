# Ecosystem digest — 2026-11-22

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-lz3rmr`.

## Delivery notes

- **Previous digest status.** The 2026-10-16 digest (sha `75ef09a`)
  merged to `main` and has been followed by a steady stream of
  architecture additions — `flux2dev`, `flux3klein`, `krea2`,
  `qwen_image`, `minimax_h3`, `skyreels`, `longcat`, `aurasr` — all
  now live in `architectures.py`. The method count has moved from
  **75 → 78**, the `_reg()` entry count from **27 → 35** (29 fully
  registered + 6 stubs). This run starts from a clean baseline on
  top of those landings.
- **Routine health.** `tools/upgrade_research.py` is still present
  and `--dry-run` executes cleanly
  (`4 proposals from 5 backends`, exit 0). No skeleton draft needed
  this run. The tool wrote its weekly artifacts to
  `_dev_docs/upgrade_research/2026-W47.{md,json}` (included in this
  PR).
- **Egress still proxy-walled.** The cloud sandbox's HTTPS proxy
  still denies direct `urllib` CONNECT to `huggingface.co` /
  `civitai.com`, so the live `backend_huggingface` /
  `backend_civitai` paths of `tools/upgrade_research.py` return
  empty from here; the Hugging-Face MCP (`hf_fs`, `hub_repo_search`,
  `hub_repo_details`) is the live path this run uses. ~12 MCP calls
  spent of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — tracked-tree scan with
  `.githooks/leak-patterns` returns clean on the pre-edit tree
  (`git grep` found no match → pass). This run's diffs don't touch
  any pattern surface, so the CI leak-check is expected to pass on
  the PR.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose
fix is in this branch and whose regression suite passes
(`pytest tests/` → 57/57, `python tests/mirror_drift.py` → OK).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner. Today is 2026-11-22.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left
as-is (all still describes past-tense "landed" items that remain
true today).

### T1-b `architectures.py` docstring: date + enumeration both stale

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) carried the
module-level `SUPPORTED ARCHITECTURES (as of October 2026):` block.
Between the 2026-10-16 digest and today, eight new `_reg()` entries
have shipped to `main` — four image (`flux2dev`, `flux3klein`,
`krea2`, `qwen_image`), three video (`minimax_h3`, `skyreels`,
`longcat`), and one Other (`aurasr`) — none of which were listed in
the docstring enumeration. All eight are `registered=True` on disk,
so the gap was purely in the doc block.

Bumped the header to `(as of November 2026):` and added the eight
new entries to their respective sections (Image → 15 entries, Video
→ 10 entries, Other → 4 entries). Stub list unchanged — still
`sd3`, `sd3_turbo`, `hunyuan_dit`, `pixart`, `auraflow`, `kolors`.

Mirror-drift stays byte-identical: identical edit applied to both
copies, `python tests/mirror_drift.py` → `OK`.

### T1-c `tools/upgrade_research.py`: HF arch-query map + stale count

Two fixes in one file:

1. **Module-docstring method-count claim** bumped from
   `70 at the time of that pass, 75 as of 2026-10-16` to
   `70 at the time of that pass, 78 as of 2026-11-22`
   (`build_builders_manifest.py` prints `78 methods` on the current
   tree).
2. **`_HF_ARCH_QUERIES` map** had 27 arch entries after the
   2026-10-16 expansion, but the on-disk registry has since grown
   to 35. That left eight fully-registered arches with no HF
   search terms:
     - **image**: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`
     - **video**: `minimax_h3`, `skyreels`, `longcat`
     - **other**: `aurasr`

   Without those entries, a live `huggingface` or `civitai` backend
   run silently skips candidate research for every `build_*` method
   that routes through them (same bug class as the 2026-10-16
   `"lumina"` → `"lumina2"` fix). Added mappings for all eight,
   using the published HF repo name variants
   (`flux-3-image-klein`, `qwen-image-edit`, etc.).

   Also opportunistically broadened the existing `"wan"` entry to
   pick up the Wan 2.5 generation, and the `"ltx"` entry to pick up
   `ltx-2.5` (prior entry only had `ltx-2`).

Verification: `python tools/upgrade_research.py --dry-run` still
exits `0`, same `4 proposals from 5 backends` output; `pytest
tests/` → `57 passed`.

**Verification of T1-a through T1-c**

- `pytest tests/` — `57 passed in 7.07s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`.
- `python tests/mirror_drift.py --quiet` — exit `0` (29/29 OK).
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  no manifest regen required (file already current).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **MiniMaxAI/MiniMax-H3-Image** | 2026-11-16 | NEW capability on the existing `minimax_h3` arch — currently registered with `supported_methods=("video_gen", "video_img2video")` only; this is the image-mode companion from the same lab | unknown (no params field on HF, likely ~8 GB fp16) | medium | 2 | **1,717 likes / 952K downloads in the first week** — this is the breakout image release of the month, with 68+ demo spaces on HF. Would require either (a) extending the existing `minimax_h3` registration's `supported_methods` to include `txt2img`/`img2img` (and adding the image CLIP/VAE pair) or (b) a separate `minimax_h3_image` arch. Decision point for the operator: are the shared Spark2 NVFP4 weights the same across image + video modes, or two distinct weights? That gates whether this is a 1-arch or 2-arch landing. |
| **apple/FastFrames-L** | 2026-11-20 | Candidate `build_fastframes_video` builder, or a fine-tune profile under the existing `wan` arch (declared `base_model: Wan-AI/Wan2.1-T2V-14B`) | ~28 GB fp16 (Wan 2.1 14B shape) | medium | 2 | 516 likes, downloads field empty (released 2 days ago). Apple's first open text-to-video — LoRA-style fine-tune on top of Wan 2.1-T2V-14B, so the base weights already match the existing `wan` registration. Could land as a sampler-profile addition rather than a new arch. License is `apple-amlr` (research-only) — needs operator read before fleet download. |
| **meituan-longcat/LongCat-Video-Avatar-1.6** | 2026-11-13 | Audio-driven avatar variant alongside the existing `_reg("longcat", ...)` (text-only video today) | ~6 GB (ONNX-quantized of LongCat-Video base) | low | 2 | 414 likes / 3.5K downloads. New `audio-text-to-video` + `audio-image-text-to-video` capability from the Meituan LongCat team. Would unlock a `build_longcat_avatar` method sitting beside the base `longcat` video builders — same base-model dependency, just a different conditioning adapter. ONNX-quantized so the storage cost is small. |
| **black-forest-labs/flux-3-image-klein-base** | 2026-11-19 (updated) | Non-distilled sister weights to the already-registered `flux3klein` arch (which today defaults to the 8-16 step SD/Distilled shape) | ~11 GB fp16 (5.5B params per HF `safetensors` field) | medium | 2 | 253 likes / 157.8K downloads. Full-quality base variant of the already-landed `flux3klein` — same arch, same encoder stack (Qwen3VL-4B flux3 + Flux2 VAE), but ~20-28 steps instead of the distilled 8-16. The arch's docstring already names this split ("8-16 steps SD / 20-28 Base") — the live registration needs a `base` sampler profile for the longer-step path, or a sibling `_reg("flux3klein_base", ...)` entry. Operator decision: one arch with two profiles or two arches. |
| **black-forest-labs/flux-3-image-klein-pup** | 2026-11-03 | Prompt-upsampling LLM (Qwen3.5-9B finetune) specialized for Flux-3-Klein prompts | ~9 GB fp16 / ~5 GB Q4 | low | 2 | 83 likes / 80K downloads. BFL-official prompt enhancer for `flux3klein`. Would plug into `llm_delegate.py`'s LM Studio hook exactly the way the 2026-10-16 digest's `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4` does for `zit` — but from the model's own lab, not a community adapter. License is apache-2.0 (vs the flux3klein weights' `other`). |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render** | 2026-10-22 | Camera-control + layout-conditioning adapter on top of LTX-2.5 | ~2 GB (adapter) | low | 2 | 160 likes / 32.5K downloads. Not in the 2026-10-16 digest. Would unlock a `build_ltx_layout_to_render_video` builder — the "sketch/box layout → full render" flow that pairs well with the existing `illustrious` img2img reference-sheet pattern. Depends on the base LTX-2.5 download (still Tier-3 queued). |
| **Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate** | 2026-10-22 | VFX object-removal / clean-plate adapter on top of LTX-2.5 | ~2 GB (adapter) | low | 2 | 56 likes / 20.1K downloads. Not in prior digests. Adds `build_ltx_clean_plate_video` — object removal / background completion for video, complements SAM3's image masking and the Alpha-Gen matte adapter. |

### Tier-2 non-model finding

- **`minimax_h3` registration is under-declared.** The current
  `_reg("minimax_h3", ...)` (at `architectures.py:1336`) only
  claims `supported_methods=("video_gen", "video_img2video")`,
  but the lab's own `MiniMaxAI/MiniMax-H3-Image` release this week
  (952K downloads) and the base `MiniMaxAI/MiniMax-H3` (shared
  across image + video) imply the arch is image-capable too. This
  is adjacent to the Qwen-Image track's dedup question from the
  2026-10-16 digest: the operator decision before any
  MiniMax-H3-Image download is whether to extend the existing arch
  entry or add a sibling. Stays Tier 2 because it affects both
  what weights the fleet downloads AND the arch-registry shape.

- **Hunyuan 4 Flash is NOT an image/video upgrade.**
  `tencent/Hy4-flash` is trending (589 likes) but on inspection
  is a 220B multimodal MoE **LLM** (image-text-to-text), not a
  generation model. Not a candidate for `hunyuan_video` /
  `hunyuan_3d`. Could be relevant as an LM Studio candidate for
  `llm_delegate.py` — but at 220B it's well outside the Spark2
  tier. Filed here so a future digest doesn't re-surface it as a
  Hunyuan arch upgrade.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries, plus this run's new
ones. A local Hermes / operator process consumes this block
mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-22 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: MiniMaxAI/MiniMax-H3-Image
    target_host: spark2
    reason: "Breakout image release of the month (952K downloads, 1717 likes in 1 week) and the image-mode companion to the already-registered minimax_h3 (currently video-only). Download first, then the architectures.py decision (extend existing _reg vs new sibling) can be made against real on-disk weights rather than a spec guess."
    command_hint: "huggingface-cli download MiniMaxAI/MiniMax-H3-Image --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MiniMax-H3-Image"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-base
    target_host: spark1
    reason: "Non-distilled base weights for the already-registered flux3klein arch. Pairs with the current -comfy distilled download — the arch's docstring already names the 8-16 step SD / 20-28 step Base split, this is the Base half."
    command_hint: "huggingface-cli download black-forest-labs/flux-3-image-klein-base --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein-base"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-pup
    target_host: spark2
    reason: "BFL-official prompt upsampler for flux3klein. Plugs into llm_delegate.py / LM Studio exactly like the Z-Image-Engineer prompt enhancer does for zit. Apache-2.0 so no gating."
    command_hint: "huggingface-cli download black-forest-labs/flux-3-image-klein-pup --local-dir D:\\LLM\\LMStudio\\models\\bfl\\flux-3-image-klein-pup"
    risk: low

  - action: download_and_evaluate_model
    target_repo: apple/FastFrames-L
    target_host: spark1
    reason: "Apple's first open text-to-video, a Wan-2.1-T2V-14B fine-tune. If the fleet already has Wan-2.1-T2V-14B on disk, FastFrames-L is a weights swap at the Wan arch's loader path. License is apple-amlr (research-only) — operator must confirm it fits spellcaster's distribution contract before downloading."
    command_hint: "huggingface-cli download apple/FastFrames-L --local-dir D:\\LLM\\ComfyUI\\models\\wan\\FastFrames-L"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: meituan-longcat/LongCat-Video-Avatar-1.6
    target_host: spark1
    reason: "Audio-driven avatar extension for the already-registered longcat arch. ONNX-quantized so storage cost is small (~6 GB). Depends on the base LongCat-Video weights already assumed by _reg('longcat', ...)."
    command_hint: "huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.6 --local-dir D:\\LLM\\ComfyUI\\models\\longcat\\LongCat-Video-Avatar-1.6"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render
    target_host: spark1
    reason: "Camera-control + layout-conditioning adapter on LTX-2.5. Unlocks build_ltx_layout_to_render_video. Depends on the base LTX-2.5 weights (still queued in prior digest's Tier-3, see below)."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Layout"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate
    target_host: spark1
    reason: "VFX object-removal / clean-plate adapter on LTX-2.5. Complements the Alpha-Gen matte adapter (prior digest) and SAM3's image-mask output. Same base-model dependency."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Clean-Plate"
    risk: low

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). HF now shows 7.7M downloads / 13K likes (up from 1.9M / 8035 at prior digest) — the dominant open i2v model by a wide margin. Still gated=auto; needs huggingface-cli login on the fleet host. Gating every LTX-2.5 IC-LoRA download sitting in this queue."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Base weights for the already-registered qwen_image arch. The arch is live in code; the fleet still needs the weights. Prior digest flagged the lane choice (Turbo vs base) — qwen_image's registration defaults to CFG 1.0 / 20 steps, the base-model shape."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: unsloth/Qwen-Image-2.1-Turbo-GGUF
    target_host: spark2
    reason: "Turbo distill GGUF for the 12 GB tier — 1.9M downloads (up from 294K at prior digest), now the dominant SFW community lane for Qwen-Image. Operator picks this OR the base-quality Comfy-Org variant, not both."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for the registered _reg('hunyuan_3d', ...). Current build_hunyuan_3d points at 2.0-shape weights; 2.1 mesh+texture pipeline may need a node-list audit before the swap."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet, just a path check."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: facebook/sam3.1
    target_host: spark1
    reason: "Weights-only drop-in for the already-wired build_sam3_segment, IF the SAM3Segment ComfyUI node loader accepts 3.1-shape weights at the same path. Audit above runs first."
    command_hint: "huggingface-cli download facebook/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on LTX-2.5. Numbers up since prior digest (279 likes / 33K DL, from 185 / 11.2K). Depends on LTX-2.5 base weights above."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. Still open from prior digest (168 likes / 13.9K DL)."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Enables build_controlnet_gen on the zit arch (currently an empty cn list). Open since 2026-09-22 digest."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c adds 8 more arches to the HF arch-query map (now 35 of 35 fully-registered + stub arches have terms) so a LAN rerun has a strictly larger search surface than the 2026-10-16 version did."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein on the fleet, the older weights on D:\\LLM should be flagged for retirement. tools/audit_disk_vs_registry.py still does not exist — drafting candidate for a future Tier-1."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe
or needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` still a Tier-3 TODO.** Open
   since the 2026-09-22 digest. With this run's eight new HF
   arch-query entries, the tool would have a larger useful
   footprint than before (it would catch retirable weights for all
   29 fully-registered arches instead of the 21 at the 2026-09-22
   baseline). Still a ~100-line Tier-1 candidate for a future
   digest: read `architectures.py` + walk `ComfyUI/models/*`,
   print paths matching `registered=True` arches that have more
   than one weights candidate on disk.

2. **Transport fallback for `tools/upgrade_research.py`.** Still
   open — the tool's HF and civitai backends use `urllib`, which
   the cloud proxy 403s. Teaching the `huggingface` backend to
   prefer an MCP transport when one is available would let *this*
   routine run the ranked backend from the cloud instead of the
   skeleton one. Doable but it broadens the tool's dependency
   surface (would need an MCP client in-process or a sidecar), so
   not shipped here.

3. **`minimax_h3` → image-mode decision.** Live `_reg()` only
   claims video methods; the 2026-11-22 HF release adds an
   image-mode companion that's trending at 952K downloads.
   Non-destructive future Tier-1 options: (a) extend
   `supported_methods` to include `txt2img`/`img2img` with a
   gated branch, (b) add a sibling `_reg("minimax_h3_image", ...)`.
   Operator read first.

4. **`flux3klein` Base vs SD profile.** Current registration
   defaults to the 8-16 step SD/Distilled shape. The docstring
   already names the Base branch (20-28 steps) but the entry has
   one `default_steps=16`. A future Tier-1 can add a
   non-destructive Base profile — either a sibling
   `_reg("flux3klein_base", ...)` with `default_steps=24` or a
   `base_mode` extra field — once the operator confirms the Base
   weights are on the fleet.

5. **Carry-forward: `fetch_metadata.py` TLS flag.** Still clean —
   `ssl.create_default_context()`. Follow-up remains closed.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local
`tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`._
