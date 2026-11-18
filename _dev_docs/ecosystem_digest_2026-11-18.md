# Ecosystem digest — 2026-11-18

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-jckr2k`.

## Delivery notes

- **Open-digest backlog is now deep.** Ten previous digest PRs
  (#200 through #209, 2026-10-28 → 2026-11-16) are still open against
  `main`. This is a stacking pattern, not a fresh-slate run; the
  baseline for this digest is still clean `main` (none of #200-209 is
  merged yet, so this branch does not have to merge-forward from any of
  them). The stacking is itself a Tier-2 follow-up (see below) — the
  routine keeps producing work the operator hasn't harvested.
- **Routine health.** `tools/upgrade_research.py` is still present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`, exit
  `0`). No skeleton draft needed.
- **Egress still proxy-walled.** Cloud sandbox's HTTPS proxy continues
  to deny direct CONNECT to `huggingface.co` / `civitai.com`, so the
  live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here. Hugging-Face
  MCP (`hf_fs`, `hub_repo_search`, `hub_repo_details`) is the live path
  used this run. ~8 MCP calls spent of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — no new leak-sensitive surfaces introduced this
  run; all edits are in `README.md`, `architectures.py` (both mirror
  copies), and `tools/upgrade_research.py` — none touch
  `tavern/`, `installer/`, `_audit/*secret*` or `.githooks/`.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes
(`pytest tests/` → 57/57).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner. Today is 2026-11-18.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left as-is
(all still describes past-tense "landed" items that remain true today
— self-healing installer, LM Studio prompt enhancement, mirror sync,
etc.). This is the same bump the 2026-11-10 and 2026-11-14 digests
applied in their own branches; the fact that none of those has merged
means the live tree on `origin/main` is still stale October, so the
fix is valid again from this branch.

### T1-b `architectures.py` docstring: enumeration + date (both mirror copies)

Both `comfyui-spellcaster/spellcaster_core/architectures.py` and
`plugins/gimp/comfyui-connector/spellcaster_core/architectures.py`
carried a module-level `SUPPORTED ARCHITECTURES (as of October 2026):`
block that enumerated **21 fully-registered** archs (11 image + 7
video + 3 other) + 6 stubs. The registry on disk is now **29
fully-registered** (15 image + 10 video + 4 other) + 6 stubs = 35
total, up from 27 at the 2026-10-16 digest.

Missing from the previous enumeration:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image` (4 new)
- Video: `minimax_h3`, `skyreels`, `longcat` (3 new)
- Other: `aurasr` (1 new)

Bumped the header to `(as of November 2026):` and expanded all three
sections. Also corrected the one-line summary for `minimax_h3` from
"MiniMax Hailuo-3 video" to the canonical "MiniMax-H3 joint video +
audio" (per the live `_reg()` comment at line 1343 — joint audio+video
model, not video-only). Identical edit applied to both mirror copies;
`python tests/mirror_drift.py` → `OK: 32/32  DRIFT: 0`.

### T1-c `tools/upgrade_research.py`: HF arch-query map is missing 8 archs + 1 stale count

The `_HF_ARCH_QUERIES` map maps each spellcaster arch id to a list of
HF-search keywords. It had 27 entries but the registry has 35 archs on
disk, so `_hf_query_for_method(build_<arch>_*)` returned `None` for 8
fully-registered archs, meaning a live `huggingface` or `civitai`
backend run would **silently skip** candidate research for them.

Added mappings for: `flux2dev`, `flux3klein`, `krea2`, `qwen_image`,
`minimax_h3`, `skyreels`, `longcat`, `aurasr`. Also broadened the
existing `wan` entry to pick up `"wan-2.5"` (trending as part of the
Wan-2.5-compatible SkyReels / FastFrames family) and the `ltx` entry
to include `"ltx-2.5"` explicitly (the 2026-10 release that's now
7.3M downloads / 12,508 likes on HF — currently the dominant
open-source i2v model).

Also bumped the stale method-count claim in the module docstring from
"75 as of 2026-10-16" → "78 as of 2026-11-18" (verified via `ast`
walk: `grep -cE "^def build_" workflows.py` = 78).

**Verification of T1-a through T1-c**

- `pytest tests/` — `57 passed in 7.89s`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, same shape
  `4 proposals from 5 backends` as before.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python -c "import ast; print(sum(1 for n in ast.walk(ast.parse(open('comfyui-spellcaster/spellcaster_core/workflows.py').read())) if isinstance(n, ast.FunctionDef) and n.name.startswith('build_')))"`
  → `78` (confirms the new docstring count).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Qwen/Qwen-Image-Edit-2511** + **Comfy-Org/Qwen-Image-Edit** | 2025-12-17 (base) / 2025-08-19 (-comfy, continuously updated) | NEW `qwen_image_edit` capability on top of the existing `qwen_image` arch — instruction-based image editing (prompt + image → edited image) | ~12 GB fp8 / ~20 GB fp16 | medium | 2 | Qwen base: 240K dl / 1,566 likes. `Comfy-Org/Qwen-Image-Edit` repackage: **1.9M downloads / 528 likes** — currently the largest-downloaded ComfyUI image-edit model in the Qwen family. The Comfy repack is `diffusion-single-file` so it drops into `ComfyUI/models/checkpoints/` with no diffusers plumbing. Would land as a new `build_qwen_image_edit` method on the existing `qwen_image` arch's checkpoint, not a new arch registration. Pairs well with the companion LoRA below for a few-step path. |
| **lightx2v/Qwen-Image-Edit-2511-Lightning** | 2025-12-22 | 4- to 8-step distill LoRA for the above | ~0 extra (LoRA on top of Qwen-Image-Edit) | low | 2 | 884.6K dl / 549 likes. Published by lightx2v, same maintainer as the LTX Lightning distills we already use. If `qwen_image_edit` lands, this LoRA makes it a few-step editor at ~4× faster — the exact pattern the fleet uses today for `flux2klein`'s 4-step Klein sampler. |
| **MiniMaxAI/MiniMax-H3-Image** | 2026-11-16 | NEW image variant of the already-registered `minimax_h3` video arch | ~8 GB fp8 (shares MiniMax-H3 clip backbone) | medium | 2 | **1,571 likes / 759.7K downloads** in ~2 days — strongest-trending text-to-image launch of November. Already shipping on Spark2 as part of the `minimax_h3` registration BUT the current `_reg("minimax_h3", ...)` restricts `supported_methods=("video_gen", "video_img2video")` and the extras point only at the video VAE. Shipping the image path would either (a) widen `supported_methods` to include `txt2img`/`img2img` and add an `image_vae_name` to `extra`, or (b) register a second arch `minimax_h3_image`. The extras share the clip backbone so weights reuse is high. 40+ demo Spaces on HF, including a 2-step variant — very low-friction integration. |
| **apple/FastFrames-L** | 2026-11-18 | NEW `fastframes` arch — Apple's text-to-video (14B, built on Wan2.1-T2V-14B) | ~28 GB fp16 (14B params); fp8 TBD | medium | 2 | 175 likes on launch day; `0` downloads yet (weights just posted). Base model is a fine-tune of `Wan-AI/Wan2.1-T2V-14B` so the sampler/VAE shape is Wan-compatible — likely a Wan-family drop-in similar to how SkyReels was registered. License is `apple-amlr` (Apple's internal research license — **not commercial-friendly**; operator must verify spellcaster's SFW canon can accept it). If yes, lands as `_reg("fastframes", ...)` beside the existing `_reg("wan", ...)`. |
| **meituan-longcat/LongCat-Video-Avatar-1.6** | 2026-11-13 | NEW `build_longcat_avatar` method on the existing `longcat` arch | ~0 extra (quantized onto the existing LongCat weights) | low | 2 | 249 likes / 1.2K downloads. Audio-driven avatar video — takes `(audio, image text)` and generates a talking-head video. `base_model:quantized:meituan-longcat/LongCat-Video`, so no new base weights, just the avatar head + the ONNX wrapper. Would unlock a new `video_avatar` method shape on the `longcat` arch (currently exposes only `VIDEO_METHODS`). MIT license — clean. |
| **speridlabs/idol** | 2026-10-29 | Potential sibling arch to `hunyuan_3d` — image-to-3D via Gaussian Splatting (not mesh) | ~4 GB (apache-2.0, splat-based) | medium | 2 | **2,476 likes / 37.2K downloads** — the highest-liked non-Qwen trending model this week. Different output format than `hunyuan_3d` (gaussian-splat .ply, not .glb mesh), so NOT a replacement — adds a parallel 3D path. Needs a product decision: do downstream spellcaster consumers (GIMP export, Blender hand-off) want splats or do they only consume meshes? If the latter, defer; if the former, land as `_reg("idol", ...)` and a `build_idol_3d_image` method. 20+ demo spaces including a "turbo" variant. |
| **Lightricks/LTX-2.5** (status refresh) | 2026-10-11 | Direct upgrade path for `_reg("ltx", ...)` | ~22 GB fp16 (22b params) | medium | 2 | Updated numbers: **7.3M downloads / 12,508 likes** on HF (up from 1.9M dl / 8,035 likes at the 2026-10-16 digest — ~4× growth in 5 weeks). Confirmed dominant open-source i2v now. Gated=auto so a fleet host needs `huggingface-cli login` once. Still Tier-3-download — carried forward below. |
| **unsloth/Qwen-Image-Edit-2511-GGUF** | 2025-12-20 | GGUF quant of the Tier-2 Qwen-Image-Edit-2511 above | ~6 GB (Q4_K_M) / ~8 GB (Q8_0) | low | 2 | 1.0M downloads / 658 likes. If Qwen-Image-Edit lands at all, the Q4_K_M lane is the obvious 12-GB-tier option on Spark2 (matches how the fleet consumes other Qwen weights today). Lands in the same PR as the base, not a separate integration. |

### Tier-2 non-model finding

- **Digest-PR backlog policy.** Ten digest PRs (#200–#209) are open
  with no merge activity in ~3 weeks. That's a fleet-management
  problem, not a code problem: each new digest keeps assuming "clean
  main" when 10 prior digests are waiting to land. Operator decisions
  needed:
  1. **Merge one, stop stacking** — pick the strongest recent digest
     (probably the most recent one that actually applied a real T1
     fix the fleet needs: a quick spot-check suggests #209
     "digest-2026-11-16" is the newest with real T1 content), merge
     it, and treat later digests as rebase-and-trim.
  2. **Pause the routine** — if the operator doesn't have time to
     review digests at a 48h cadence, the routine should be slowed
     (weekly? bi-weekly?) rather than continuing to bank up unreviewed
     branches. The current rate produces ~3.5 PRs/week against a
     repository with no other open PRs — the ratio is wrong.
  3. **Auto-merge the T1-only ones** — if the operator's actual
     decision rule is "T1 fixes are always fine, T2/T3 need me," wire
     an auto-merge policy on the CI-green digest PRs (or at minimum a
     "merge-when-green" label) so the T1 stream clears without
     operator attention. This is a repo-config decision, not a code
     fix, so it stays Tier-2.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over still-open 2026-10-16 entries that have not been reported
as actioned, plus this run's new ones. A local Hermes / operator
process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-18 ────────────────────────────────────────────

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-Edit
    target_host: spark1
    reason: "ComfyUI-ready repackage of Qwen-Image-Edit-2511 (1.9M downloads, 528 likes). diffusion-single-file, drops straight into ComfyUI/models/checkpoints/. Prereq for the build_qwen_image_edit path on the existing qwen_image arch. Apache-2.0 license — clean."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-Edit --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-Edit"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: lightx2v/Qwen-Image-Edit-2511-Lightning
    target_host: spark1
    reason: "Few-step (4-8) distill LoRA for Qwen-Image-Edit-2511. Depends on the Comfy-Org/Qwen-Image-Edit base. ~0 extra weights, unlocks a fast-edit path similar to how flux2klein's 4-step Klein sampler runs today."
    command_hint: "huggingface-cli download lightx2v/Qwen-Image-Edit-2511-Lightning --local-dir D:\\LLM\\ComfyUI\\models\\loras\\Qwen-Image-Edit-Lightning"
    risk: low

  - action: download_and_evaluate_quant
    target_repo: unsloth/Qwen-Image-Edit-2511-GGUF
    target_host: spark2
    reason: "Q4_K_M lane for 12-GB-tier hosts. Pair with the Comfy-Org base on a 24-GB-tier host for full-precision reference while the 12-GB tier runs the Q4. 1.0M downloads / 658 likes."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-Edit-2511-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-Edit-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: MiniMaxAI/MiniMax-H3-Image
    target_host: spark2
    reason: "Image variant of the MiniMax-H3 joint-video+audio model already registered as _reg('minimax_h3', ...). Shares clip backbone; the image VAE is new (~2 GB). 1,571 likes / 759.7K downloads in the first week — strongest text-to-image launch of November. Operator call: add the image VAE to the existing arch's `extra` dict and widen supported_methods, OR register a sibling `minimax_h3_image` arch."
    command_hint: "huggingface-cli download MiniMaxAI/MiniMax-H3-Image --local-dir D:\\LLM\\ComfyUI\\models\\minimax-h3\\image"
    risk: medium

  - action: download_and_evaluate_lora_pack
    target_repo: meituan-longcat/LongCat-Video-Avatar-1.6
    target_host: spark1
    reason: "Audio-driven avatar head on top of the existing LongCat base. ~0 new base weights (quantized onto LongCat-Video). Unlocks a new `build_longcat_avatar` method shape (audio+image → talking-head video). MIT license."
    command_hint: "huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.6 --local-dir D:\\LLM\\ComfyUI\\models\\longcat\\avatar-1.6"
    risk: low

  - action: evaluate_text_to_video_adjunct
    target_repo: apple/FastFrames-L
    target_host: unknown
    reason: "Apple-amlr license is NOT standard-commercial-friendly — operator must confirm the spellcaster SFW canon accepts it before any fleet download. If yes, land as a Wan-family sibling (fine-tune of Wan-AI/Wan2.1-T2V-14B, so Wan-compatible VAE/sampler shape)."
    command_hint: "# DO NOT DOWNLOAD until operator confirms apple-amlr license compatibility\n# huggingface-cli download apple/FastFrames-L --local-dir D:\\LLM\\ComfyUI\\models\\fastframes"
    risk: medium

  - action: evaluate_3d_sibling_arch
    target_repo: speridlabs/idol
    target_host: unknown
    reason: "Image-to-3D via Gaussian Splatting (not mesh). Output format is .ply splats, not .glb meshes — different from existing hunyuan_3d. Operator call: do downstream consumers (GIMP export, Blender) want splats? apache-2.0 license — clean if yes."
    command_hint: "huggingface-cli download speridlabs/idol --local-dir D:\\LLM\\ComfyUI\\models\\idol-3d"
    risk: medium

  # ─── Carried over from 2026-10-16 (still open) ────────────────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "flux3klein is now registered as _reg('flux3klein', ...) in architectures.py — the code side of this is landed. Still missing on the fleet: the actual weights. Gated=auto on HF; needs huggingface-cli login on the fleet host."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Updated numbers: 7.3M downloads / 12,508 likes on HF (~4× growth since last digest). Direct upgrade path for _reg('ltx', ...). Gated=auto; needs HF login the sandbox doesn't have."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for existing _reg('hunyuan_3d', ...); current build_hunyuan_3d points at 2.0-shape weights, 2.1 mesh+texture pipeline may need node-list audit before the swap."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Enables build_controlnet_gen on the zit arch (currently an empty cn list)."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Cloud sandbox egress proxy denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-c adds 8 more arches and refreshes wan/ltx keyword lists, so a LAN rerun now has 35 archs to probe instead of 27."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein replaces Flux-2-Klein, the older weights on D:\\LLM should be flagged for retirement. tools/audit_disk_vs_registry.py (named in prior digests) still does not exist — a future Tier-1 drafting candidate."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist"
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.** Named
   in prior Tier-3 queues (2026-09-22, 2026-10-16) but has never been
   written. If the Qwen-Image-Edit + LTX-2.5 + Flux-3-Klein + MiniMax-
   H3-Image downloads all land, the retirable-weights question stays
   unanswered without this tool. A ~100-line Tier-1 candidate for a
   future digest.

2. **Transport fallback for `tools/upgrade_research.py`.** Same gap
   the 2026-09-22 and 2026-10-16 digests flagged — the tool's HF and
   civitai backends use `urllib`, which the cloud proxy 403s. Teaching
   the `huggingface` backend to prefer an MCP transport when one is
   available would let *this* routine run the ranked backend from the
   cloud instead of skeleton mode. Still not shipped (broadens
   dependency surface).

3. **`minimax_h3` arch widening vs sibling registration.** The
   MiniMax-H3-Image launch surfaces a design question: do we widen
   `supported_methods` on the existing `_reg("minimax_h3", ...)` to
   include image methods and add an `image_vae_name` to `extra`, OR
   register a sibling `_reg("minimax_h3_image", ...)` that shares the
   clip backbone? Previous project style has been sibling registration
   (see `flux2klein` / `flux2dev` / `flux3klein`), so leaning there,
   but the clip reuse makes a strong case for the widening path.
   Operator call.

4. **Digest-PR backlog.** See Tier-2 non-model finding above — the
   routine's actual bottleneck is that 10 PRs in the queue have
   nobody to merge them. This is the single highest-leverage
   follow-up: fix the review cadence or the T1 fixes never land.

5. **`fastframes` arch and Apple-AMLR.** If the operator does want
   Apple's FastFrames in the fleet, the license audit needs to happen
   before any download — apple-amlr is more restrictive than the
   Lightricks / Black-Forest-Labs licenses the fleet is used to. One
   line of research, zero code — but blocks the T3 download above.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
AST scans of `architectures.py`, `workflows.py`, `builders_manifest.json`;
`pytest tests/`; `python tests/mirror_drift.py`._
