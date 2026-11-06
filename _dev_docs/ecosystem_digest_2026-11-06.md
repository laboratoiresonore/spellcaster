# Ecosystem digest — 2026-11-06

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `b7d82d1`). Branch: `claude/adoring-allen-ocsc3f`.

## Delivery notes

- **Previous digest status.** The 2026-10-16 digest's PR
  (`claude/adoring-allen-p38r5b`) landed on `main` — this run starts
  from a clean slate rather than stacking on an open queue.
- **Routine health.** `tools/upgrade_research.py` is still present and
  `--dry-run` executes cleanly (`4 proposals from 5 backends`). No
  skeleton draft needed this run.
- **Egress still proxy-walled from the sandbox.** The cloud HTTPS proxy
  still denies direct CONNECT to `huggingface.co` / `civitai.com`, so
  the live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here; the
  **Hugging-Face MCP** (`hf_fs`, `hub_repo_search`, `hub_repo_details`)
  is the live path from the cloud this run uses. ~11 MCP calls spent
  of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — the current branch only touches `README.md`,
  `DEEP_DIVE.md`, `tools/upgrade_research.py`, and both
  `architectures.py` mirrors — none intersect `.githooks/leak-patterns`
  entries. Nothing in this diff should trip the scan.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
57/57, `python tests/mirror_drift.py` → `OK: 32/32 DRIFT: 0`,
`python tools/upgrade_research.py --dry-run` → clean exit).

### T1-a `README.md`: front-page status is one month stale

`📣 Status — October 2026` on the hero banner. Today is 2026-11-06.
Bumped to `📣 Status — November 2026`. News/Focus/Next copy left as-is
— the "landed" items (self-healing installer, LM Studio prompt
enhancement, mirror sync, DaVinci bridge-in-test, etc.) still describe
things that remain true today.

### T1-b `architectures.py` docstring: enumeration + date

Both copies of `architectures.py`
(`comfyui-spellcaster/spellcaster_core/` and
`plugins/gimp/comfyui-connector/spellcaster_core/`) still carried the
`SUPPORTED ARCHITECTURES (as of October 2026):` enumeration listing
**21 fully-registered + 6 stubs = 27** archs, but the registry on disk
is now **29 fully-registered + 6 stubs = 35** built-in entries (plus
the `my_custom_model` test scaffold loaded from `_arch_registry`).

The eight new archs that had been registered since the 2026-10-16
sweep but never surfaced in the module docstring:

| Key | Loader | Category | Comment |
|-----|--------|----------|---------|
| `flux2dev` | `unet_clip_vae` | Image | Full-size Flux 2 counterpart to `flux2klein`'s 4-step distill |
| `flux3klein` | `unet_clip_vae` | Image | Flux 3 Klein (the Oct-2026 release prior digest filed at Tier-2) |
| `krea2` | `unet_clip_vae` | Image | Krea 2 Turbo — Qwen3VL-4B text encoder + Qwen Image VAE at 8 steps |
| `qwen_image` | `unet_clip_vae` | Image | Qwen Image Edit 2511 (Qwen 2.5 VL 7B + Qwen Image VAE) |
| `skyreels` | `unet_clip_vae` | Video | SkyReels-V2 540p DF / I2V — Wan-compatible conditioning + VAE |
| `longcat` | `unet_clip_vae` | Video | LongCat long-video / avatar extension (WanVideoWrapper-based) |
| `minimax_h3` | `unet_clip_vae` | Video (audio-video) | MiniMax-H3 — Qwen3-VL-32B text encoder + separate video + audio VAEs |
| `aurasr` | `custom_wrapper` | Other (upscaler) | AuraSR v2 GAN-based 4× image super-resolution |

Bumped the header to `(as of November 2026):` and expanded the list
accordingly. Mirror-drift stays byte-identical: identical edit applied
to both copies, `python tests/mirror_drift.py` → `OK: 32/32 DRIFT: 0`.

### T1-c `tools/upgrade_research.py`: HF arch-query map is missing 8 archs

Same bug class as the 2026-10-16 digest's T1-c — `_HF_ARCH_QUERIES`
drifted behind the registry again. Eight arches (the same eight added
to the docstring above) had no entry, so `_hf_query_for_method()`
would return `None` for every `build_<arch>_*` call, and a live HF /
Civitai backend run would **silently skip** candidate research for
them. Verified with:

```python
arch_keys - set(_HF_ARCH_QUERIES.keys())
# → {'aurasr', 'flux2dev', 'flux3klein', 'krea2', 'longcat',
#    'minimax_h3', 'qwen_image', 'skyreels'}
```

Added mappings for all eight:

```python
"flux2dev":    ["flux-2-dev", "flux.2-dev", "flux2dev"],
"flux3klein":  ["flux-3-image-klein", "flux.3-klein", "flux3klein"],
"krea2":       ["krea-2", "krea2"],
"qwen_image":  ["qwen-image-2.1", "qwen-image", "qwen-image-edit"],
"skyreels":    ["skyreels", "skyreels-v2"],
"longcat":     ["longcat-video", "longcat"],
"minimax_h3":  ["minimax-h3", "MiniMax-H3"],
"aurasr":      ["aura-sr", "aurasr"],
```

While there, broadened the existing `wan` and `ltx` entries to also
pick up the new generations the HF trending list surfaced: `wan-2.5`
and `ltx-2.5` (Lightricks published `Lightricks/LTX-2.5` on 2026-10-11,
now at 2.6M downloads / 10.8K likes — would otherwise be matched by
`"ltx-2"` substring but keeping the explicit entry makes it a
first-class query term).

Also bumped the stale method-count claim in the module docstring from
`75 as of 2026-10-16` → `75 as of 2026-10-16; 78 as of 2026-11-06`
(matches `python tools/build_builders_manifest.py` output: "78
methods").

### T1-d `DEEP_DIVE.md`: two concrete counts drifted

- Line 64 (Mermaid backbone diagram): `architectures.py<br/>27 arch
  registry` → `35 arch registry`. The number is a direct count of
  `_reg(` entries in `architectures.py` (29 fully-registered + 6
  stubs = 35 built-in; test-scaffold `my_custom_model` lives in
  `_arch_registry` and is loaded dynamically, excluded here).
- Line 649 (Enhancement Operators section): "`_ARCH_ENHANCE_PROFILES`
  in prompt_enhance.py — **9 architectures** each with their own
  `max_tokens`, target `length`, `style`, and guidance notes" →
  "**11 architectures**". Verified count by grepping the dict
  literal in `comfyui-spellcaster/spellcaster_core/prompt_enhance.py`
  (currently `flux1dev`, `flux2klein`, `chroma`, `sdxl`, `sd15`,
  `illustrious`, `pony`, `wan`, `ltx`, `sd3`, `sd3_turbo` — 11
  entries).

Left the other DEEP_DIVE "9 model architectures"-style claims
(lines 443, 922, 936) at Tier-2 — those read as representative feature
copy ("SD 1.5, SDXL, Illustrious/Pony, …") rather than concrete
counts, so bumping them requires editorial judgement about how to
re-list, not a mechanical count bump.

### Verification of T1-a through T1-d

- `pytest tests/` — `57 passed in 6.97s`.
- `python tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `python tools/upgrade_research.py --dry-run` — exit `0`,
  same `4 proposals from 5 backends` output as before.
- `python tools/build_builders_manifest.py` — `wrote … (78 methods)`;
  no manifest regen required (already up-to-date on disk).
- Post-fix `arch_keys - set(_HF_ARCH_QUERIES.keys())` → `set()`
  (empty — every registered arch has a query term).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`, `hub_repo_details`). Numbers below are the HF
report at the time of this digest. The 2026-10-16 digest's Tier-2
block remains the master list; the entries below are **new since
that digest** or **material status changes** to already-filed entries.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Pika-Labs/Pika-H3-Flex** | 2026-10-29 | LoRA adapter on top of `minimax_h3` — audio-conditioned video LoRA | ~2 GB (adapter) | medium | 2 | 487 likes / 986 downloads (very new; on the HF trending front page). `base_model:adapter:MiniMaxAI/MiniMax-H3` — plugs straight into the existing `_reg("minimax_h3", …)` registration. Would wire as a LoRA variant of `build_minimax_h3_video_gen` with the audio-video pathway surfaced. |
| **abenzerps/Qwen-Image-2.1-Turbo-Quantized** | 2026-11-03 | Consolidated multi-quant (GGUF + FP8 + NVFP4 + MLX) for the Qwen-Image-2.1-Turbo lane the 2026-10-16 digest already filed as Tier-2 | 4–10 GB depending on quant | medium | 2 | 2.1M downloads / 5,680 likes — the Qwen-Image-Turbo distribution has clearly consolidated here. If/when `qwen_image` lands and the operator picks the Turbo lane (per prior digest's "pick one lane" decision), this is the canonical quant repo to pull. Supersedes the previous digest's three separate `unsloth` / `AtomicChat` / `Viggle` entries as the ComfyUI landing spot. |
| **unsloth/flux-3-image-klein-GGUF** + **-FP8** | 2026-10-16 (first published), currently 246.9K + 227.2K downloads | GGUF + FP8 companion to the Flux 3 Klein integration filed at Tier-2 in the 2026-10-16 digest | GGUF Q4 ≈ 6 GB, FP8 ≈ 11 GB | medium | 2 | Unlocks the 12-GB-tier lane for the `flux3klein` arch (which currently assumes BF16 weights). Lands as a quant-list extension in the Flux 3 Klein integration PR when it ships — not its own PR. |
| **speridlabs/idol** | 2026-10-29 | NEW capability — image-to-3d via **Gaussian splatting** (different output format than Hunyuan3D's mesh pipeline) | ~5 GB (ViT backbone + GS head) | medium | 2 | 886 likes / 19.1K downloads; Apache-2.0; 12+ demo spaces active on the Hub. Output is a Gaussian-splat scene (`.ply` / `.splat`) rather than a textured mesh, so it's **not** a replacement for `hunyuan_3d` — it's an adjunct for the "I want a 3D scene I can drop into Blender/WebGL" use case, versus Hunyuan3D's "I want a printable/textured object mesh" use case. Decision for the operator: separate `_reg("idol", …)` arch with its own `build_idol_image_to_3d_scene`, or extend `build_hunyuan_3d` with a `format=mesh|splat` flag? |
| **tencent/Hunyuan3D-Omni** | 2026-11-04 (diffusers port by community) | Multi-modal 3D generation (image, text, and view-conditioned) — direct successor family to `hunyuan_3d` | ~6–8 GB (fp16) | medium | 2 | Not yet on the HF trending page; surfaced via `hub_repo_search hunyuan 3d`. Two new mini-variants (`OzzyGT/hunyuan3d_2mini_{base,fast,turbo}`, 2026-10-29) suggest Tencent is actively iterating the 3D family. If the operator plans a Hunyuan3D 2.1 → Omni path, bench these variants together. |
| **tokenfrugal LTX-video GGUFs** (`maxh8086/tokenfrugal-ltx-video-0.9-gguf`, `-0.9.8-gguf`) | 2026-11-05 | GGUF quants for the LTX-video base — same 12-GB-tier bridge as the Qwen-Turbo quants above, but for `ltx` | ~3–5 GB | low | 2 | 21 + 33 downloads, 0 likes (brand-new) — early signal, keep an eye on adoption for a future digest before acting. Not yet worth pulling. |

### Tier-2 non-model finding

- **New research papers for Z-Image Turbo.** Recent HF `z-image-turbo`
  repos (`Esackr/Z-Image-Turbo` 2026-11-04, `abc1015abc/Z-Image-Turbo`
  2026-11-06) carry **three new arxiv tags** on their model cards:
  `2511.22699`, `2511.22677`, `2511.13649` (November 2026 papers).
  These are academic improvements on the Z-Image Turbo recipe
  (potentially informing future `zit` recalibration). Nothing to
  commit yet — the research is upstream; the moment it lands as
  weights under `black-forest-labs/z-image-turbo` or similar canonical
  publisher, it becomes a weights-swap for `_reg("zit", …)`. Filing
  as a "watch" item for the 2026-11-08 digest.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Entries from the 2026-10-16 digest are carried forward below only if
they haven't been reported as actioned locally. Local operator /
Hermes process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-11-06 ────────────────────────────────────────────

  - action: download_and_evaluate_lora
    target_repo: Pika-Labs/Pika-H3-Flex
    target_host: spark1
    reason: "Pika Labs' audio-conditioned video LoRA on top of MiniMax-H3 (the minimax_h3 arch already registered in architectures.py). ~2 GB adapter, apache-compatible license per 'other' tag — check license file before shipping. Unlocks an audio-video generation path on top of the existing minimax_h3 registration without a new base download."
    command_hint: "huggingface-cli download Pika-Labs/Pika-H3-Flex --local-dir D:\\LLM\\ComfyUI\\models\\loras\\MiniMax-H3\\Pika-H3-Flex"
    risk: medium

  - action: download_and_evaluate_quant_variant
    target_repo: abenzerps/Qwen-Image-2.1-Turbo-Quantized
    target_host: spark2
    reason: "Consolidated multi-quant (GGUF + FP8 + NVFP4 + MLX) replacing the 2026-10-16 digest's three-repo recommendation (unsloth/AtomicChat/Viggle). 2.1M downloads on a single repo is a strong consolidation signal — pull the Q4_K_M or FP8 variant depending on spark2's active VRAM headroom."
    command_hint: "huggingface-cli download abenzerps/Qwen-Image-2.1-Turbo-Quantized --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-Quantized"
    risk: low

  - action: download_and_evaluate_quant_variant
    target_repo: unsloth/flux-3-image-klein-GGUF
    target_host: spark1
    reason: "GGUF quant of Flux 3 Klein for the 12-GB tier; paired download with the already-queued flux-3-image-klein-comfy. The -comfy repo is bf16 (24 GB); this GGUF repo gives spark1 a fallback if the full bf16 doesn't fit active workload."
    command_hint: "huggingface-cli download unsloth/flux-3-image-klein-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\flux-3-image-klein-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: speridlabs/idol
    target_host: unknown
    reason: "NEW image-to-3d Gaussian-splatting arch (different output format than hunyuan_3d — scene, not mesh). 886 likes / 19.1K downloads in first 8 days; Apache-2.0. Decide: does spellcaster surface GS output alongside mesh output, or is this out of scope? Needs a fleet host that can hold ~5 GB ViT backbone."
    command_hint: "huggingface-cli download speridlabs/idol --local-dir D:\\LLM\\ComfyUI\\models\\image-to-3d\\idol"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: tencent/Hunyuan3D-Omni
    target_host: spark1
    reason: "Multi-modal 3D generation successor to Hunyuan3D-2.1 — image/text/view-conditioned. Still gated license (tencent weights), may need HF login on the fleet. Only download after the Hunyuan3D-2.1 drop-in evaluation from the 2026-10-16 digest closes, so we don't thrash spark1 disk on two parallel 3D candidates."
    command_hint: "huggingface-cli download tencent/Hunyuan3D-Omni --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\Omni"
    risk: medium

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────
  # (These were filed on the 2026-10-16 digest; re-listing here for
  # local-queue consumers that only read the latest digest. Local
  # operator should treat them as deduplicated — act on them once.)

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein — direct successor to the current _reg('flux3klein', ...) scaffold in architectures.py. 1.1M downloads / 2,609 likes as of 2026-11-06 (prior digest: 374 likes / 22K downloads — the adoption curve has flattened the reservation that previous runs noted). Gated=auto on HF — needs huggingface-cli login on the fleet host once."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet, just a path check. (Carried from 2026-10-16; no action report seen yet.)"
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "LTX-2.5 is now at 2.6M downloads / 10.8K likes (vs. 1.9M / 8035 at prior digest). Direct upgrade path for _reg('ltx', ...). Gated=auto; needs HF login. The ltx-2.5 IC-LoRA family (Alpha-Gen, Pixel-Spatial-Upscaler, Refine-Details, Ingredients) still waits on this base."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Drop-in for existing _reg('hunyuan_3d', ...); current build_hunyuan_3d points at 2.0-shape weights, 2.1 mesh+texture pipeline may need node-list audit before the swap. If the Hunyuan3D-Omni (new T2 above) proves out, this 2.1 drop-in becomes a one-off bridge step."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium
```

## Operator memory corrections

None this run. The brief's note that `tools/upgrade_research.py` has
"gone missing before" doesn't apply this sweep — the tool is present,
functional, and the `_HF_ARCH_QUERIES` surface drift was the only
upgrade-research-side gap, already fixed above in T1-c.
