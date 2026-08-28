# Ecosystem Research Digest — 2026-08-28

Cloud-side scheduled routine, every-48h. Repo baseline: `laboratoiresonore/spellcaster`, branch `claude/adoring-allen-45kzbe`, HEAD `ccef78a`. Sandbox: Anthropic remote (no LAN reach; no `C:\` or `D:\` FS; `laboratoiresonore/spellcaster` only, public).

Run notes:

- **Missing-tool gap closed this run.** `tools/upgrade_research.py` — a helper this routine's own prompt depends on — did not exist and prior runs had been silently degrading to open-ended web search each time. Drafted a minimal working version this run (see Tier 1 fix below). Future digest runs can now `python tools/upgrade_research.py --json` and get a stable, deterministic list of research targets keyed to the actual `_reg(...)` registry.
- Web budget spent: 0 WebSearch, 4 WebFetch-equivalent MCP calls to `Hugging-Face` (well under the ~25 soft cap).
- Gmail MCP is not authorized in this sandbox — the digest ships as the PR alone; no email fallback attempted (per routine guidance).

---

## Tier 1 — fixes applied in this PR

Every finding here is committed with the digest. Diff summary:

| File | Fix | Reason |
|---|---|---|
| `tools/upgrade_research.py` | **New file** (274 lines). Reads canonical `ARCHITECTURES` registry and emits per-arch HF hints + versioned WebSearch queries, JSON or markdown. | Prior digest runs kept noting this script was referenced by their own prompt but did not exist. Every run degraded to web-only research and lost the arch-registry linkage. First-class contract now checked in. |
| `README.md:46` | `Status — May 2026` → `Status — August 2026` | The "current status" banner had been stale by 3 months. Prior digests flagged this and never fixed it. |
| `comfyui-spellcaster/spellcaster_core/architectures.py` and `plugins/gimp/comfyui-connector/spellcaster_core/architectures.py` | Added `_reg("supir", ...)` stub (registered=True, empty `supported_methods` — dispatch is via `build_supir()` in `workflows.py:3090`, not method gating). | `model_detect.py:103` maps SUPIR checkpoint filenames to arch key `"supir"`, but no `_reg("supir", ...)` existed. Consequence: `get_arch("supir")` silently returned the SDXL fallback — exactly the "don't fall back to SDXL, register a stub" design intent stated in the architectures.py comment block at lines ~790-807. Verified before/after: `28` archs registered post-fix (was 27), `get_arch("supir").key == "supir"` (was `"sdxl"`). |
| `plugins/gimp/comfyui-connector/spellcaster_core/workflows.py`, `preflight.py`, `asset_gallery.py` | Ran `python tests/mirror_drift.py --fix` to sync surface 1 back to canonical surface C. +702 net lines across the three files. | `tests/mirror_drift.py` was red on `main` before this branch: `OK: 23/26  DRIFT: 3`. Confirmed pre-existing by stashing my edits and re-running the check. The `mirror-drift.yml` CI job triggers on any PR touching `spellcaster_core/**`, so the pre-existing drift would have failed this PR's CI regardless. The `--fix` flag is the tool's own auto-sync path (`C → 1`, C being canonical), no logic change — just verbatim mirroring of code that already landed on main via surface C. |

### Verification steps run

```
$ python -c "…; ARCHITECTURES['supir'].registered, ARCHITECTURES['supir'].key"
(True, 'supir')

$ python tests/mirror_drift.py
✓ All surfaces byte-identical    OK: 26/26

$ python tools/upgrade_research.py --group video     # smoke
# emits 7 video archs with HF hints + Aug-2026 web queries

$ python -c "import ast; ast.parse(open('...architectures.py').read())"
OK  (both mirrored files)
```

No test-suite regression suite was runnable in the sandbox (no ComfyUI, no LM Studio, no LAN Theo). The static + import-time checks above are all that this environment can verify. Anything requiring live model dispatch is unverifiable from here — that constraint is unchanged from prior runs.

### Findings noticed but downgraded to Tier 2 (why they weren't auto-applied)

- **`_looks_like_uniform_mask` in `_spellcaster_main.py:8952`** — the routine prompt hinted "uniform classifier mishandles grayscale". Read the function; it handles `LA` (line 8972) and `RGB`/`RGBA`/`P` (line 8974) explicitly, then falls through to `img.getextrema()` for anything else. For mode `L` (already grayscale), the fall-through is correct — the function operates directly on L. For modes `I`, `I;16`, `F` (16/32-bit masks) the histogram bucketing at 8981 assumes an 8-bit range and will silently mis-report uniformity. That's a real edge case but it's unclear whether ComfyUI SAM3/BiRefNet nodes ever emit non-8-bit masks in this codebase's use — needs the human's judgment on whether to widen the check or narrow the input contract. Downgraded to Tier 2 rather than push a speculative fix.

---

## Tier 2 — new-model / new-architecture integration work (needs human judgment)

Ranked by relevance to the currently registered arch surface. All dates are the HF `lastModified` value as of 2026-08-28.

| # | Model | HF repo | Date | Replaces / adds | VRAM (est.) | Risk | Notes |
|---|---|---|---|---|---|---|---|
| T2.1 | **LTX-2.5** | [Lightricks/LTX-2.5](https://hf.co/Lightricks/LTX-2.5) | 2026-08-27 | Bumps `_reg("ltx", …)` baseline from LTX-Video 2.0 → 2.5. Adds native audio-to-video + text-to-audio. | ~12 GB fp16 for 720p (per demo Space) | **Med** — gated repo (auto-approve), so download flow needs a token per Spark. Adds a new modality (audio-video) that Spellcaster's `VIDEO_METHODS` tuple doesn't cover. | 912K downloads in <24h — clear adoption signal. Multi-language prompt support (en/de/es/fr/ja/ko/zh/it/pt). Native `diffusion-single-file` for ComfyUI, so no wrapper-pack blocker. Kijai wrapper compatibility unverified from sandbox. |
| T2.2 | **SeedVR2-3B** | [ByteDance-Seed/SeedVR2-3B](https://hf.co/ByteDance-Seed/SeedVR2-3B) (base) + [mofashiWY/SeedVR2-3B](https://hf.co/mofashiWY/SeedVR2-3B) (mirror, 2026-08-28) | 2026-08-28 | Bump for `_reg("seedvr", …)` — Spellcaster's current entry is version-agnostic, defaults `default_steps=15 default_cfg=1.0`. SeedVR2 is the second-gen model; may want new defaults + a v1 alias. | ~8 GB fp16 (3B params). fp32 VAE also up (Merserk/Seedvr2-vae-fp32, 2026-07-14). | **Low** — Apache-2.0, drop-in-ish for the existing video_upscale method. | Existing `_reg("seedvr", …)` used by `seedv2r` method key in the SDXL autoset_denoise dict. If the arch bump lands, verify the `seedv2r` naming in `autoset_denoise` still resolves the intended pipeline. |
| T2.3 | **MiniMax-H3** | [MiniMaxAI/MiniMax-H3](https://hf.co/MiniMaxAI/MiniMax-H3) · Comfy-Org fork: [Comfy-Org/MiniMax-H3](https://hf.co/Comfy-Org/MiniMax-H3) (19.1M downloads) | 2026-08-13 | **New architecture, unregistered.** Unified image-text-to-video with **synchronized audio-video** output. Would slot alongside `wan` / `hunyuan_video` in scene_group `video`. Comfy-Org has already packaged it as a single-file for ComfyUI. | ~14 GB fp16 (per Abiray GGUFs also up), int4 nvfp4 variant available for lower-VRAM Sparks. | **High** — new modality (audio-video) means new `supported_methods` entries (`video_gen_with_audio` or similar) and a new builder in `workflows.py`. Not a small addition. | 19.1M downloads on the Comfy-Org fork alone in <1 month → this is where mindshare is. Also has a `lightx2v/Minimax-h3-Turbo` distill (681K dl) for faster inference. Also has `alibaba-pai/MiniMax-H3-Fun-Controlnet-Union` (text-to-video ControlNet). If Spellcaster wants to stay on the "which video arch is the default" wave, this is where the puck is. |
| T2.4 | **Illustrious-XL v2.0** | [OnomaAIResearch/Illustrious-XL-v2.0](https://hf.co/OnomaAIResearch/Illustrious-XL-v2.0) (referenced as base of SceneWorks mlx port, 2026-08-23) | 2026-07-10 (upstream) | The existing `_reg("illustrious", …)` doesn't distinguish v1 from v2. If v2 becomes the recommended checkpoint, the classifier is fine but the `prompt_guidance` / `default_cfg=5.5` values may need re-tuning per v2's release notes. | ~12 GB fp16 (same as v1 — SDXL-derived). | **Low** — pure model swap, no arch changes. | Downstream `SceneWorks/illustrious-xl-v2-mlx` (Apple Silicon port) and `Mouserat/Illustrious-XL-v2.0-diffusers-mnn` (Android/on-device) both citing v2.0 as the base — the base_model ecosystem has clearly moved. |
| T2.5 | **Qwen-Image-Edit-2511** | [Qwen/Qwen-Image-Edit-2511](https://hf.co/Qwen/Qwen-Image-Edit-2511) (231K dl) + [lightx2v/Qwen-Image-Edit-2511-Lightning](https://hf.co/lightx2v/Qwen-Image-Edit-2511-Lightning) distill (326K dl) + [Comfy-Org/Qwen-Image-Edit_ComfyUI](https://hf.co/Comfy-Org/Qwen-Image-Edit_ComfyUI) (1.3M dl on earlier vers.) | 2025-12-17 base / 2025-12-22 Lightning | **New architecture, unregistered.** Image editing model in the "type a change, apply it locally" niche. Would go into `IMAGE_METHODS` under a new `image_edit_qwen` method or a new `qwen_image_edit` arch key. Apache-2.0. | ~14 GB fp16 base; GGUF Q4 fits on 8 GB (unsloth quant, 241K dl). | **Med** — new arch + new builder. Overlaps with Klein's edit modes (`klein_edit`, `klein_headswap`) — need to decide if Qwen-Image-Edit is a Klein competitor or a complement (Klein is Flux-2 4B, tuned for portraits; Qwen-Image-Edit is more of a general edit model). | 1.3M-dl Comfy-Org packaging is a strong ComfyUI-ready signal. |
| T2.6 | **FLUX.2-klein face-restore LoRA** | [happyinhappy/flux2-klein-face-restore-lora](https://hf.co/happyinhappy/flux2-klein-face-restore-lora) | 2026-08-28 | LoRA slot for the existing `flux2klein` arch. Directly usable in `autoset_loras` for the `klein_refine` / `klein_inpaint` method rows. | Adds ~200 MB on top of the 4B base. | **Low** — LoRA, no arch changes. Needs eyeballing on quality first. | Zero-download so-far but tagged with an image-to-image face-restoration workflow. Small-scale finding but exactly the kind of drop-in that ships in a nightly. |

Note on Wan: no `Wan-AI/Wan2.5` or `Wan-AI/Wan2.3` upstream repo on HF as of 2026-08-28 — the current `_reg("wan", …)` for Wan2.2 is still current. One hobby "Hiren122/Wan-2.5" upload exists (0 downloads, unofficial). Kijai's WanVideoWrapper repo lookup returned no HF matches from the sandbox (it's a GitHub project, not an HF model repo) — checking that would need a WebFetch on `github.com/kijai/ComfyUI-WanVideoWrapper` which was not spent.

---

## Tier 3 — local_action_queue (structured, for a local operator / Hermes / local Claude session)

Actions that need LAN + local-FS access this sandbox does not have. Emitted as a fenced YAML block so a downstream process can consume it mechanically — the previous free-text prose bullets were consistently not re-derived into commands.

```yaml
local_action_queue:
  - action: download_model_update
    target_repo: Lightricks/LTX-2.5
    target_host: unknown           # pick per LTX use-site (Spark that hosts video_upscale?)
    reason: |
      Bumps the ltx arch baseline from LTX-Video 2.0 → 2.5.
      Gated repo — a valid HF token must already be on the target host
      before this can run. Download the single-file safetensors variant
      (ComfyUI-compatible per the diffusion-single-file library tag).
    command_hint: |
      huggingface-cli login   # if not already tokened
      huggingface-cli download Lightricks/LTX-2.5 --local-dir D:/LLM/ltx/LTX-2.5 --include "*.safetensors" "*.json"
    risk: medium

  - action: download_model_update
    target_repo: ByteDance-Seed/SeedVR2-3B
    target_host: unknown
    reason: |
      Second-generation SeedVR upscaler. Slots into the existing
      seedvr arch entry — the default_steps/default_cfg in _reg("seedvr", …)
      may need re-tuning per SeedVR2 recommendations after weights land.
    command_hint: |
      huggingface-cli download ByteDance-Seed/SeedVR2-3B --local-dir D:/LLM/seedvr/SeedVR2-3B
    risk: low

  - action: fetch_lora
    target_repo: happyinhappy/flux2-klein-face-restore-lora
    target_host: unknown           # wherever klein_refine LoRA store lives
    reason: |
      Face-restoration LoRA sized for the existing flux2klein 4B base.
      Once fetched, wire into autoset_loras for klein_refine / klein_inpaint
      in architectures.py (canonical surface C).
    command_hint: |
      huggingface-cli download happyinhappy/flux2-klein-face-restore-lora \
        --local-dir <ComfyUI>/models/loras/Klein/face_restore/
    risk: low

  - action: evaluate_new_arch
    target_repo: MiniMaxAI/MiniMax-H3
    target_host: theo              # only host with enough VRAM headroom for a first-run smoke
    reason: |
      New unified image-text-to-video arch with synchronized audio-video output.
      Not yet in Spellcaster. Before committing to a _reg() + builder, benchmark
      Comfy-Org/MiniMax-H3 single-file on a 5-second I2V run at 720p and compare
      to Wan2.2 output on the same input. If output quality wins consistently,
      escalate to a Tier 2 integration PR in a future digest run.
    command_hint: |
      huggingface-cli download Comfy-Org/MiniMax-H3 --local-dir <ComfyUI>/models/checkpoints/MiniMax-H3
      # Then submit a video_gen job through the standard ComfyUI /prompt path.
    risk: high

  - action: retirement_pending
    target_repo: Lightricks/LTX-Video (2.0)
    target_host: unknown
    reason: |
      Once LTX-2.5 is downloaded AND a smoke test confirms parity+ on a real
      video_gen job, retire LTX-Video 2.0 to D:\LLM\_retired\ to reclaim disk.
      Blocked on T3.1 landing first.
    command_hint: |
      # After T3.1 verified:
      move D:\LLM\ltx\LTX-Video-2.0 D:\LLM\_retired\LTX-Video-2.0
    risk: medium
```

Nothing in this block was executed from this sandbox — cannot be. Consumer end is a local operator or a future Hermes step reading the digest.

---

## Prior operator memory / notes to correct

None this run. The Wan-2.2 → Wan-2.5 rumor track that prior digests may have carried does not have an upstream Wan-AI repo yet (only one 0-download unofficial hobby upload). Keeping the current `wan` arch baseline as-is is correct.

---

## Delivery

- **Primary:** this file + Tier-1 diffs land on branch `claude/adoring-allen-45kzbe`, PR opened via `mcp__github__create_pull_request`.
- **Fallback (email):** Gmail MCP requires OAuth and is not authorized in this sandbox. Per the routine's guidance, said so plainly here and did not silently drop the notice.
- **Notification:** none pushed — the completion of the PR IS the notification for a routine that runs while the user is away.

---

_Generated by [Claude Code](https://claude.ai/code)_
