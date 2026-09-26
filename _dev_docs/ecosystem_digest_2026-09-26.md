# Ecosystem digest — 2026-09-26

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-1nbnn4`.

## Delivery notes

- **Backlog visibility** — the merged-in security work (`ecf4249`,
  `cd01ad2`, `0c898f3`, `329761b`) plus the 2026-09-22 consolidation PR
  landing means the open-PR count from the previous digest's warning
  dropped from ten to two ecosystem digests still open (PR #183 from
  2026-09-24 and the much older PR #166 from 2026-09-04). Backlog
  pressure is resolved for now; this PR stacks on top of `main` and can
  be merged independently.
- **Two prior follow-ups already resolved on main** — the 2026-09-22
  digest filed `leak-check.yml` false-positives and `fetch_metadata.py`
  TLS-bypass as future Tier-1 candidates. Verified this run:
  - Simulated `git grep -nIEi "$patterns" -- ':!.github/…leak-check.yml'
    ':!.githooks/pre-push' ':!.githooks/leak-patterns'` on today's HEAD:
    **exit 1, no output**. The security commits that unified the
    pattern list into `.githooks/leak-patterns` and audited its content
    scrubbed the tracked-tree hits — nothing to fix.
  - `fetch_metadata.py:18` uses `ssl.create_default_context()` (secure
    defaults, hostname verification on, `CERT_REQUIRED`). No
    `check_hostname=False` or `verify_mode=CERT_NONE` present anywhere
    in the file — either the prior finding was misidentified or the
    bypass was silently fixed. Nothing to fix.
- **`tools/upgrade_research.py` present** — `--dry-run` exits clean
  (`4 proposals from 5 backends`). Real HF / civitai backends still
  gated on the LAN because the sandbox proxy 403s at CONNECT; see
  Tier-3 `rerun_upgrade_research_from_lan`.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix is
in this branch and whose regression suite passes (`pytest tests/` →
52/52).

### T1-a Six stale "69 AI tools" copy strings outside README/DEEP_DIVE

The 2026-09-22 digest bumped `69` → `75` in README + DEEP_DIVE only, but
`grep -rn "69 AI\|69 tools"` still hits six operator-facing surfaces
that ship the wrong count. Source of truth remains
`builders_manifest.json` (`method_count: 75`) and
`grep -c '^def build_' plugins/gimp/comfyui-connector/spellcaster_core/workflows.py`
(`75`).

Updated (each string was a single occurrence, straight replacement):

| File | Line | Was | Now |
|------|------|-----|-----|
| `installer/installer_gui.py` | 894 | `"69 AI tools — generate images, fix photos, …"` | `"75 AI tools — generate images, …"` |
| `installer/install.py` | 2075 | `"Every one of the 69 tools gets better output automatically."` | `"Every one of the 75 tools …"` |
| `scaffold/spellcaster_wizard.py` | 182 | `"GIMP 3 — 69 AI tools in Filters > Spellcaster …"` | `"GIMP 3 — 75 AI tools …"` |
| `plugins/gimp/comfyui-connector/_spellcaster_main.py` | 1174 | `'GIMP + ComfyUI + 69 AI tools, pre-configured and ready.'` | `'GIMP + ComfyUI + 75 AI tools, …'` |
| `tavern/static/setup.html` | 132 | `"These add 69 AI tools directly into your editor's menu."` | `"These add 75 AI tools …"` |
| `tavern/static/setup.html` | 136 | `"All 69 tools under Filters → Spellcaster."` | `"All 75 tools …"` |

Left the `_spellcaster_main.py:76,92,97` lines alone — those `9269` /
`11569` / `13269` matches are byte-count columns in the
`_run_*` comment table, not tool counts.

Left the historical joke line `ComfyUI-GIMP-Middleware-With-69-Tools-…`
in the README FAQ alone; it's the same inside gag preserved by the
previous digest.

Post-fix sweep: `grep -rn "69 AI\|69 tools" --include='*.py'
--include='*.html' --include='*.md'` outside `_dev_docs/` is empty.

### T1-b `SUPPORTED ARCHITECTURES` docstring in both `architectures.py` copies enumerates 7 of 27

The module docstring in
`comfyui-spellcaster/spellcaster_core/architectures.py` and its
identical copy at
`plugins/gimp/comfyui-connector/spellcaster_core/architectures.py`
lists only 7 archs under `SUPPORTED ARCHITECTURES`, but the actual
`_reg(...)` call set (per AST scan) declares **27**: 8 default-registered
image archs + 13 `registered=True` + 6 `registered=False` stubs. This
was called out as a Tier-2 follow-up in the 2026-09-22 digest; I'm
promoting it to Tier-1 here because the enumeration is fully
determinable from a mechanical AST scan and the "which are shipped vs.
stub" split is legible from the `registered=` kwarg itself.

New docstring (identical in both copies, replaces the 7-item bullet
list) breaks the 27 entries into four categories:

- **Image (fully wired), 12:** sd15, sdxl, illustrious, zit, flux1dev,
  chroma, flux2klein, flux_kontext, sdxl_turbo, pony, playground,
  lumina2
- **Video (fully wired), 6:** wan, ltx, cogvideo, framepack,
  hunyuan_video, mochi
- **3D and restore (fully wired), 3:** hunyuan_3d, supir, seedvr
- **Stubs (`registered=False`, loaders not yet wired), 6:** sd3,
  sd3_turbo, hunyuan_dit, pixart, auraflow, kolors

Total: 12+6+3+6 = 27 ✓ (matches the AST count).

Also added a `NOTE` line pointing at
`tools/build_builders_manifest.py` as the canonical regenerator so the
next drift is caught by tooling rather than by another ecosystem
digest.

### Verification of T1-a and T1-b

- `python -c "import ast; ast.parse(open('.../architectures.py').read())"`
  on both copies: **clean parse**.
- `python -m pytest tests/ -q` → **52 passed in 7.29s** (baseline was
  52/52; no regression).
- `python tools/upgrade_research.py --dry-run` → clean
  (`4 proposals from 5 backends`).
- Post-fix `grep -rn "69 AI\|69 tools"` outside `_dev_docs/` is empty.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via HF MCP `hf_fs ls hf://models/trending`,
`hub_repo_search image-to-video sort=trendingScore`, and
`hub_repo_details MiniMaxAI/MiniMax-H3`. Used ~5 MCP calls of the
25-call soft budget.

The dominant signal of the 96-hour window since the last digest is
**MiniMax-H3**: a new video generation architecture from MiniMaxAI
that landed hard (5,691 likes / 8.7M downloads on the base repo, 100+
demo Spaces including MiniMaxAI's own, and both official Turbo and
GGUF variants trending in the top-10 image-to-video slot). It is NOT
in the current `architectures.py` registry — `_reg("minimax_h3", …)`
does not exist. This is a genuine new-arch integration.

The Qwen-Image-2.1 recommendation from the 2026-09-22 digest is also
STRONGER now: Comfy-Org/Qwen-Image-2.1 is at 3.6M downloads (was 1.4M
four days ago) and abenzerps/Qwen-Image-2.1-Uncensored-GGUF is at
876K (was 182K). The community is clearly consolidating on the
Comfy-Org repackage as the ComfyUI-native single-file entry point.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **MiniMaxAI/MiniMax-H3** | 2026-08-13 (updated 2026-09) | NEW `minimax_h3` arch — no current coverage; unified text/image/audio-to-video | ~66 GB fp16 (33B params), ~10 GB Q4 via unsloth GGUF | high | 2 | 5,691 likes / 8.7M downloads on base. 100+ Spaces. Two live inference providers (fal-ai, wavespeed). Would land as `build_minimax_h3_video` (video-arch shape) + `_reg("minimax_h3", …)`. VRAM at base is out of range for consumer cards; a GGUF-first integration (`unsloth/MiniMax-H3-GGUF`, 1.2M downloads) is the realistic default. |
| **WarmBloodAban/Minimax-h3_Singularity** | 2026-09-05 | Community fine-tune of MiniMax-H3 (higher-quality, HDR-tuned) | same as base | medium | 2 | 422K downloads / 668 likes. If `minimax_h3` lands as an arch, this and its GGUF (Abiray/MiniMax-H3-Singularity-GGUF, 8K downloads) are the "quality" preset above the base weights. |
| **lightx2v/Minimax-h3-Turbo** | 2026-08-07 | Distill of MiniMax-H3 for few-step inference | same as base | medium | 2 | 1.6M downloads / 999 likes. Diffusers-library. Would live as the low-latency preset on the `minimax_h3` arch (analogous to `zit` on the SDXL side, or the 4-step Klein preset on `flux2klein`). |
| **Comfy-Org/Qwen-Image-2.1** | 2026-09-22 | STRONGER re-recommend from prior digest — new `qwen_image` arch | ~16 GB fp8 | low | 2 | 3.6M downloads now (was 1.4M in 4 days). Single-file `.safetensors` at `diffusion-single-file`, drops straight into `ComfyUI/models/checkpoints/`. `build_qwen_image_txt2img` (`build_illustrious_txt2img`-shape) + `_reg("qwen_image", …)`. |
| **abenzerps/Qwen-Image-2.1-Uncensored-GGUF** | 2026-09-26 | STRONGER re-recommend — GGUF variant | ~10 GB Q4_K_M | low | 2 | 876K downloads / 1,891 likes (was 182K in 4 days — 4.8× growth). If the base arch lands, wire this GGUF in the same PR as the low-VRAM default via `UnetLoaderGGUF`. |
| **pinecoresystems/Krea-2-Raw / Krea-2-Turbo** | 2026-09-26 | Krea 2 open weights + turbo distill | ~14 GB fp16 base, ~14 GB turbo | medium | 2 | 0 downloads / 0 likes yet (published today). Krea 2 has commercial mindshare via its hosted Space; the open weights just landing means it's a landing-zone candidate to watch, but too fresh to integrate. Deferred to next digest. |
| **Jinstudio/LLaDA-Image / LLaDA-Image-Turbo** | 2026-09-26 | Diffusion language model (`LLaDAImagePipeline`) | unknown | high | 2 | 0 downloads yet. Research-shape architecture (`arxiv:2609.03796`). Too experimental to integrate this quarter, but flagging for the next 30-day watch window. |

The full Tier-2 shortlist from the 2026-09-22 digest (Qwen-Image-Edit-2509,
LTX-2.5, Wan2.2-I2V-A14B-GGUF, Wan2.2-Animate-2, Hunyuan3D-2.1,
illustrious-xl-v2.0-GGUF, Z-Image-Turbo-Fun-Controlnet-Union-2.1)
remains valid — none of those trended down or were superseded — but is
not re-tabled here to keep this row set focused on what's new in the
96-hour window. Refer to the prior digest for those integration notes.

### Tier-2 non-model finding

- **Manifest regeneration hook** — the T1-b docstring refresh made the
  drift obvious; the underlying "docs enumerate what the code declares"
  invariant is a natural fit for the existing
  `tools/build_builders_manifest.py` (which already regenerates
  `builders_manifest.json` from the workflow builder set). A future
  Tier-2 could extend that tool to also emit an
  `architectures_manifest.json` (name, family, default_size,
  registered) and have the two `architectures.py` module docstrings
  auto-regen from it in the same pass. Left as Tier-2 because the
  "should the docstring auto-regen or should the manifest be the
  human-readable enumeration" question is the operator's call.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Structured entries below. A local Hermes / operator process consumes
this block mechanically instead of a human re-deriving the command from
prose. Every `command_hint` is best-effort — the operator adjusts for
the fleet's exact model directory layout. Deltas from the 2026-09-22
digest: **added** the MiniMax-H3 evaluation entries (new arch, high
priority); **carried forward** the LTX-2.5, Qwen-Image-2.1,
Wan2.2-I2V-A14B-GGUF, Hunyuan3D-2.1, Z-Image-CN-2.1, rerun-from-LAN,
and audit-retirable entries unchanged. Entries the operator has
already actioned should be dropped from the queue at their end.

```yaml
local_action_queue:
  - action: download_and_evaluate_model
    target_repo: unsloth/MiniMax-H3-GGUF
    target_host: spark1
    reason: "NEW ARCH candidate — MiniMax-H3 is the top-trending video model of the past week (5,691 likes / 8.7M downloads on base). Base weights are 33B params (~66 GB fp16, out of reach for consumer cards); the unsloth Q4 GGUF is the realistic entry point at ~10 GB. Evaluate quality against Wan 2.2 I2V before proposing _reg('minimax_h3', ...) integration."
    command_hint: "huggingface-cli download unsloth/MiniMax-H3-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\MiniMax-H3-GGUF"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: WarmBloodAban/Minimax-h3_Singularity
    target_host: spark2
    reason: "Higher-quality community fine-tune of MiniMax-H3 (422K downloads, HDR-tuned). Pair with Abiray/MiniMax-H3-Singularity-GGUF if the base MiniMax-H3 arch lands. Runs only after unsloth GGUF eval decides base quality is worth the arch slot."
    command_hint: "huggingface-cli download WarmBloodAban/Minimax-h3_Singularity --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Minimax-h3_Singularity"
    risk: medium

  - action: download_and_evaluate_lora
    target_repo: lightx2v/Minimax-h3-Turbo
    target_host: spark1
    reason: "Few-step distill LoRA for MiniMax-H3 (1.6M downloads). If MiniMax-H3 lands, this is the low-latency preset (analog of the 4-step Klein preset on flux2klein). Small download."
    command_hint: "huggingface-cli download lightx2v/Minimax-h3-Turbo --local-dir D:\\LLM\\ComfyUI\\models\\loras\\Minimax-h3-Turbo"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Carried forward from 2026-09-22 digest. Signal strengthened: Comfy-Org repackage now at 3.6M downloads (was 1.4M in 4 days). Land this before the base HF repo — it drops into ComfyUI/models/checkpoints/ with no diffusers-pipeline shim."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: abenzerps/Qwen-Image-2.1-Uncensored-GGUF
    target_host: spark2
    reason: "Carried forward from 2026-09-22 digest. Signal strengthened: 876K downloads (was 182K in 4 days, 4.8× growth). Low-VRAM companion to Comfy-Org/Qwen-Image-2.1; if base lands, default for the 12-GB tier."
    command_hint: "huggingface-cli download abenzerps/Qwen-Image-2.1-Uncensored-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Uncensored-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Unchanged from 2026-09-22. Direct upgrade path for _reg('ltx', ...). Gated=auto on HF — needs HF login the cloud sandbox doesn't have, so this stays fleet-only."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: QuantStack/Wan2.2-I2V-A14B-GGUF
    target_host: spark1
    reason: "Unchanged from 2026-09-22. VRAM-saver GGUF swap for existing wan arch's build_wan_video I2V path."
    command_hint: "huggingface-cli download QuantStack/Wan2.2-I2V-A14B-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Wan2.2-I2V-A14B-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/hunyuan3D_2.1_repackaged
    target_host: spark1
    reason: "Unchanged from 2026-09-22. Drop-in for existing _reg('hunyuan_3d', ...); node-list audit needed."
    command_hint: "huggingface-cli download Comfy-Org/hunyuan3D_2.1_repackaged --local-dir D:\\LLM\\ComfyUI\\models\\hunyuan3d\\2.1"
    risk: medium

  - action: download_and_evaluate_controlnet
    target_repo: alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1
    target_host: spark2
    reason: "Unchanged from 2026-09-22. Enables build_controlnet_gen on zit arch."
    command_hint: "huggingface-cli download alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\controlnet\\Z-Image-Turbo-Fun-Union-2.1"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "Unchanged from 2026-09-22. Cloud sandbox proxy still 403s HF + civitai CONNECT; tools/upgrade_research.py's live backends still fall back to skeleton mode. Running it from the LAN exercises real backends."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index --methods build_illustrious_txt2img,build_wan_video,build_klein_repose,build_minimax_h3_video"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "Unchanged from 2026-09-22. Extended: if MiniMax-H3 lands and displaces some of the Wan I2V paths on the video side, both LTXV-2.3 and older Wan variants become candidates for retirement to free D:\\LLM space."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; carried follow-up."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items I saw but did not fix in this run — either scope-larger-than-safe,
or ambiguous enough to want the operator's read first.

1. **`tools/build_builders_manifest.py` extension for arch enumeration**
   — the T1-b docstring refresh made the drift visible; the underlying
   invariant should be enforced by tooling. Extending the manifest
   builder to emit an `architectures_manifest.json` (name, family,
   default_size, registered) and having both `architectures.py` module
   docstrings regen from it would prevent this drift class permanently.
   Not shipped this run because the "docstring auto-regen vs. manifest
   as SoT" architecture call is the operator's.

2. **`tools/upgrade_research.py` transport fallback** — carried from
   prior digest. The tool's HF and civitai backends use stdlib
   `urllib`, which the sandbox proxy 403s at CONNECT time. Teaching it
   to prefer an HF MCP transport when one is available would let this
   routine run the *real* backend from the cloud instead of the
   skeleton one. Not shipped because it broadens the tool's dependency
   surface beyond stdlib.

3. **Tool count consistency in `assets/showcase.gif`** — carried from
   prior digest. README/DEEP_DIVE + the six sources fixed today all say
   75, but the `generate_showcase.py`-produced GIF may still emit
   labels from a hardcoded count. Not verified this run.

4. **`comfyui-spellcaster/` and `plugins/gimp/comfyui-connector/spellcaster_core/`
   sync check** — both copies of `architectures.py` were identical
   before this run's T1-b edit and remain identical after. There's no
   automated check enforcing that invariant; a `pytest`-side assert or
   a pre-commit hook comparing the two files' hashes would prevent
   drift. Small mechanical fix, but the "which is canonical" question
   (or "should both be a symlink to a shared module?") is the
   operator's.

5. **MiniMax-H3 arch slot** — Tier-2 dispatch to the local fleet. If
   the operator green-lights integrating it after eval, the code-side
   work is: define `MINIMAX_H3_EXTRA_METHODS` if needed, add
   `_reg("minimax_h3", …)` in `architectures.py` (both copies), add
   `build_minimax_h3_video` in `workflows.py`, and regenerate the
   manifest. A dedicated Tier-1 PR for a *future* digest run once the
   local-eval verdict is in.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hub_repo_search`,
`hub_repo_details`, `hf_fs`; local `tools/upgrade_research.py --dry-run`;
git AST scans of `architectures.py`, `workflows.py`,
`builders_manifest.json`; git grep of the tracked tree._
