# Ecosystem digest — 2026-10-18

Every-48h cloud-side research + maintenance sweep. Baseline:
`origin/main` (sha `ed19fb4`). Branch: `claude/adoring-allen-7qdgcv`.

## Delivery notes

- **Previous digest merged.** The 2026-10-16 digest's three Tier-1
  fixes (`75ef09a`) are on `main`. In the two days since, the v2.4
  Spark2 GB10 feature series (`4b1e1c0`, `0e63dc1`, `ed19fb4`) added
  eight new fully-registered architectures and widened the registry
  from 27 to 35 `_reg()` entries — this run's T1-a / T1-b catch up
  the docstring + arch-query map to that change.
- **Routine health.** `tools/upgrade_research.py --dry-run` executes
  cleanly (`4 proposals from 5 backends`). No skeleton draft needed.
- **Egress still proxy-walled.** The cloud sandbox HTTPS proxy still
  denies direct CONNECT to `huggingface.co` / `civitai.com`, so the
  live `backend_huggingface` / `backend_civitai` paths of
  `tools/upgrade_research.py` return nothing from here. Hugging-Face
  MCP (`hf_fs`, `hub_repo_search`) is the live path from the cloud
  this run uses. ~7 MCP calls spent of the ~25 soft budget.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself.
- **Leak-check CI** — not re-scanned manually this run (10-16 digest
  confirmed clean against the canonical pattern list; this run's diff
  is docstring + registry-query map + a new read-only diagnostic
  tool, none of which touch secret-shaped tokens).

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes
(`tests/mirror_drift.py` → OK: 32/32; `tests/test_model_coverage.py` →
PASSED 20/20; `tools/build_builders_manifest.py` → 78 methods;
`tools/upgrade_research.py --dry-run` → exit 0).

### T1-a `architectures.py` docstring: enumeration drift (both mirror copies)

The 10-16 digest brought the `SUPPORTED ARCHITECTURES (as of October
2026):` block to 21 fully-registered + 6 stubs. Since then the v2.4
Spark2 feature series (`4b1e1c0` et seq.) added eight new fully-registered
arches that the docstring did not list:

- Image: `flux2dev`, `flux3klein`, `krea2`, `qwen_image` (4 new)
- Video: `minimax_h3`, `skyreels`, `longcat` (3 new)
- Other / upscale: `aurasr` (1 new)

Expanded the block to show the current state — 15 image + 10 video +
4 other = **29 fully-registered** plus the same 6 stubs. One-line
descriptions per arch, matching the voice of the pre-existing entries.
Date header stays as `(as of October 2026):`. Identical edit applied
to both mirror copies; `tests/mirror_drift.py` → OK 32/32 DRIFT 0.

### T1-b `tools/upgrade_research.py`: HF arch-query map misses 8 arches + stale method count

Two mechanical drifts in `tools/upgrade_research.py`:

1. **`_HF_ARCH_QUERIES` map** — same bug class as T1-c of the 10-16
   digest. The map had entries for 27 arches, but the registry now has
   35 (29 fully-registered + 6 stubs). The eight registered arches
   added in `4b1e1c0` et seq. had **no mapping**, meaning
   `_hf_query_for_method(build_<newarch>_*)` silently returned None
   and a live HF/civitai backend run would skip them. Added entries
   for `flux2dev`, `flux3klein`, `krea2`, `qwen_image`, `minimax_h3`,
   `skyreels`, `longcat`, `aurasr`. Also broadened `wan` to pick up
   `wan-2.5` and `ltx` to pick up `ltx-2.5` (both named in the Tier-3
   queue from prior digests).

2. **Build-method count** — module docstring said "75 as of
   2026-10-16"; actual count is now 78 (`grep -c 'def build_'
   plugins/gimp/comfyui-connector/spellcaster_core/workflows.py` →
   78). Bumped to "78 as of 2026-10-18".

Verification: `python tools/upgrade_research.py --dry-run` still exits
`0`, same `4 proposals from 5 backends` output.

### T1-c `tools/audit_disk_vs_registry.py`: draft the Tier-3-named diagnostic

Named in the 2026-09-22 + 2026-10-16 Tier-3 queues and filed by the
10-16 digest as a drafting candidate for a future Tier-1. Shipping
the draft now because:

- The matching logic is pure (expected-filenames from the registry +
  on-disk basenames) — testable without a real fleet filesystem.
- The tool is **read-only** by construction: no deletes, moves, or
  renames. Operator reads the `[ORPHAN]` section and decides whether
  to retire a weight.
- `--self-test` runs a four-case synthetic-tempdir check (matched /
  missing / orphan / subfolder-prefixed basename) that passes in the
  sandbox, so cloud CI can regress-guard it even though the real
  audit needs `D:\LLM\ComfyUI\models` access on a fleet host.

Scope: one new file (`tools/audit_disk_vs_registry.py`, 265 lines)
plus a one-line `.gitignore` carve-out (the top-level `audit_*.py`
ignore rule otherwise swallows the new tool). Reads
`spellcaster_core.architectures.ARCHITECTURES` via the same
`plugins/gimp/comfyui-connector` sys-path shim the other tools use —
no new dependency surface. Local LLM / network calls: zero.

**Running against the real fleet** (what the Tier-3 queue entry
`audit_retirable_weights` turns into once this ships):

    python tools/audit_disk_vs_registry.py \
      --models-dir "D:\LLM\ComfyUI\models"

Exit `0` + a non-empty `[ORPHAN]` section is the state the operator
reads before retiring old weights. The 11 arches currently declaring
weight filenames (`chroma`, `flux1dev`, `flux2dev`, `flux2klein`,
`flux3klein`, `flux_kontext`, `krea2`, `minimax_h3`, `qwen_image`,
`skyreels`, `zit`) seed the "referenced" set — anything on disk whose
basename isn't in that set shows up in `[ORPHAN]` as a retirement
candidate.

**Verification of T1-a through T1-c**

- `tests/mirror_drift.py` — `OK: 32/32   DRIFT: 0`.
- `PYTHONPATH=comfyui-spellcaster python tests/test_model_coverage.py`
  — `PASSED (20/20)`.
- `python tools/upgrade_research.py --dry-run` — exit `0`, `4
  proposals from 5 backends`.
- `python tools/build_builders_manifest.py` — `wrote …
  builders_manifest.json (78 methods)`, no net manifest diff vs
  main.
- `python tools/audit_disk_vs_registry.py --self-test` — `OK: 4/4`.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP (`hf_fs ls hf://models/trending`,
`hub_repo_search`). Numbers below are the HF report at the time of
this digest.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **lightx2v/Qwen-Image-Edit-2511-Lightning** | 2025-12-22 (still rising) | Lightning few-step LoRA on the Qwen-Image Edit 2511 shape that `_reg("qwen_image", …)` already uses | ~0.8 GB (LoRA on top of qwen_image base) | low | 2 | 375.8K downloads / 536 likes. LoRA adapter — drops into `ComfyUI/models/loras/Qwen/` and plugs into `autoset_loras` without a new base download. Directly accelerates the already-registered `qwen_image` arch (which uses the Qwen 2.5 VL 7B encoder path). Would land as a `turbo_config` on the existing `_reg("qwen_image", …)` or as a `build_qwen_image_turbo_*` family. |
| **lightx2v/Qwen-Image-2.1-Lightning** | 2026-10-13 | Alternative to `Qwen/Qwen-Image-2.1-Turbo` filed in the 10-16 digest — same job (few-step distill) as a LoRA, not a full base swap | ~0.8 GB (LoRA on top of Qwen-Image-2.1 base) | low | 2 | 92.2K downloads / 88 likes in five days — the lightx2v house style (same team that shipped `Qwen-Image-Lightning` with 247K downloads). Prefer this to the Turbo full-weight distill IF the base `Qwen-Image-2.1` lane wins the "which Qwen-Image to download" decision in the 10-16 digest's deferred call: a LoRA stacks on the base without doubling the storage footprint of Turbo. |
| **tencent/HunyuanImage-3.0-Instruct** | 2025-09-25 (SOTA re-tested 2026-10) | NEW arch — upgrade path for the `hunyuan_dit` STUB (`registered=False` → `registered=True`) | ~80 GB fp16 full MoE (prohibitive); ~16-24 GB with the ComfyUI-quantized distill below | medium | 2 | 39.7K downloads / 1,054 likes. HunyuanImage 3.0 is a mixture-of-experts text-to-image / image-to-image follow-on to Hunyuan-DiT; the full `tencent/HunyuanImage-3.0` base has 1,149 likes but downloads are a tiny 1.6K because of its 80GB disk cost. The practical fleet integration lane is `PedroMarinhoDev/HunyuanImage-3.0-Instruct-Distil-ComfyUI` (118 downloads, 14 likes — community-quantized, no cost until the fleet decides to try it). Decision: promote the `hunyuan_dit` stub to a full registration keyed `hunyuan_image_3`, or extend the stub rather than orphaning the key? |
| **black-forest-labs/flux-3-image-klein-pup** | 2026-10-14 | NEW model-class — Qwen3.5-9B prompt-upsampling LLM specialized for Flux 3 Klein | ~5 GB (fp16 of a 9B Qwen3.5) | low | 2 | 4.3K downloads / 50 likes. First-party prompt enhancer tuned on the `flux3klein` arch. Would wire into `llm_delegate.py` as a LM-Studio-loadable model-choice option for prompts headed to `build_klein_*` (same pattern the 10-16 digest's `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4` row proposed for `zit`). Interesting because `WaveCut/flux3-klein-pup-50k` (50K prompt-upsample pairs) is an open corpus — the operator can fine-tune a smaller 3B variant on the pack if 9B is too heavy for the LM Studio tier. |
| **Abiray/flux-3-image-klein-sd-GGUF** | 2026-10-15 | GGUF quantizations of the `flux3klein` arch for low-VRAM fleet tiers | ~4-7 GB (Q4-Q6 variants) | low | 2 | 9.2K downloads / 23 likes. Community GGUF quantization matching the `comfyui-gguf` loader. If the fleet's 12-GB tier is excluded from the `flux-3-image-klein-comfy` lane (fp16/BF16 only), this is the drop-in that unlocks it. Pairs with the Flux 2 Klein → Flux 3 Klein retirement pass. |
| **DeepSeek-V4.1-Flash-1017** | 2026-10-17 | New generation of the LM-Studio-local LLM used by `llm_delegate.py` / `tools/upgrade_research.py` / `tools/llm_morning_briefing.py` | varies by quant | low | 2 | 10.2K downloads / 1,241 likes — top of the HF trending list this cycle. Fast, image-text-to-text (so viable for prompt enhancement AND image-grounded briefings). Not image-gen so doesn't register an arch — this is a LM Studio side upgrade (change the default model name in Settings.bat / env). |
| **openbmb/MiniCPM-V-4.7-35B-A3B** | 2026-10-15 | Alternative local VLM for `llm_delegate.py` image-grounded tasks | ~22 GB BF16 (A3B = 3B active with MoE) | medium | 2 | 57.9K downloads / 961 likes. Mixture-of-experts VLM with 35B total / 3B active — well-matched to a 24-GB fleet tier that is otherwise too tight for a 35B dense model. Downside: MoE routing isn't yet first-class in LM Studio; defer until operator confirms LM Studio supports MoE loading on their stack. |
| **openbmb/MiniCPM-V-4.7-1B** | 2026-10-15 | Lightweight VLM option for a laptop / 8-GB tier | ~2.3 GB fp16 | low | 2 | 22.7K downloads / 383 likes. Same family's smallest sibling — practical for the Theo-local tier (per `tools/upgrade_research.py` endpoint resolver, the 1234 port). Would ride into Settings.bat as a lightweight prompt-enhancer option alongside `BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4`. |
| **facebook/sam3.1** | 2026-03-26 (now trending at #54) | Weights-only drop-in for `build_sam3_segment`, carried over from 10-16 | ~2 GB | low | 2 | 97.0K downloads / 1,108 likes (up from 90.9K / 1,091 on 10-16 — still rising). Carries over from the 10-16 Tier-2 row. **Note:** `Comfy-Org/sam3.1` ComfyUI-repackaged variant now shows 273.2K downloads / 102 likes — may be the preferred fleet lane since it's `diffusion-single-file` compatible. The operator audit entry below picks the right lane once run. |

### Tier-2 non-model findings

- **"Which Qwen-Image lane" decision is now a three-way call.** The
  10-16 digest's deferred decision was "base vs Turbo". This digest
  adds Lightning: a LoRA adapter that stacks on either base. The
  operator call to make is now: do we ship (a) base + Lightning LoRA
  (lowest disk cost, two downloads), (b) base + Turbo distill
  (highest quality ceiling, three downloads if Turbo-GGUF is
  included), or (c) Turbo only (fastest to ship, no LoRA plumbing).
  Still Tier-2 because it changes which weights the fleet downloads,
  not which code lands.

- **Prompt-upsampler integration is a shape, not just a model.** Three
  prompt-enhancer models have now been filed as Tier-2 across the
  last three digests (`Qwen3-4b-Z-Image-Engineer-V4` for `zit`,
  `flux-3-image-klein-pup` for `flux3klein`, and the generic DeepSeek
  / MiniCPM options for all). Rather than wiring each one as a
  separate `llm_delegate.py` branch, a future Tier-1 could add a
  per-arch `prompt_enhancer_model` field to `ArchConfig.extra` and
  let `llm_delegate.py` dispatch on the arch key. Deferred to
  Tier-2 because it is architectural (one place to decide the
  convention) rather than mechanical.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Carries over the still-open 2026-10-16 entries that have not been
reported as actioned, plus this run's new ones. A local Hermes /
operator process consumes this block mechanically.

```yaml
local_action_queue:
  # ─── New in 2026-10-18 ────────────────────────────────────────────

  - action: download_and_evaluate_lora_pack
    target_repo: lightx2v/Qwen-Image-Edit-2511-Lightning
    target_host: spark1
    reason: "Lightning LoRA on the Qwen-Image Edit 2511 shape — directly accelerates _reg('qwen_image', ...). ~0.8 GB, LoRA. Drops into ComfyUI/models/loras/Qwen/ with no new base download. Decision gate: whether to wire as turbo_config on the existing arch or as a separate build_qwen_image_turbo_* family (code-side, deferred to Tier-2 above)."
    command_hint: "huggingface-cli download lightx2v/Qwen-Image-Edit-2511-Lightning --local-dir D:\\LLM\\ComfyUI\\models\\loras\\Qwen\\Qwen-Image-Edit-2511-Lightning"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: lightx2v/Qwen-Image-2.1-Lightning
    target_host: spark1
    reason: "Lightning LoRA on the Qwen-Image-2.1 base — alternative to Qwen/Qwen-Image-2.1-Turbo already in the queue (full distill vs LoRA). Only matters if the base-Qwen-Image-2.1 lane wins the 'which Qwen-Image' call (see Tier-2 non-model finding above)."
    command_hint: "huggingface-cli download lightx2v/Qwen-Image-2.1-Lightning --local-dir D:\\LLM\\ComfyUI\\models\\loras\\Qwen\\Qwen-Image-2.1-Lightning"
    risk: low

  - action: download_and_evaluate_prompt_enhancer
    target_repo: black-forest-labs/flux-3-image-klein-pup
    target_host: theo
    reason: "First-party Qwen3.5-9B prompt upsampler for flux3klein. Would wire into llm_delegate.py as a LM-Studio-loadable prompt enhancer. ~5 GB. If the 9B is too heavy for the LM Studio tier (confirm RAM headroom first), WaveCut/flux3-klein-pup-50k is the open corpus and a 3-4B fine-tune is viable."
    command_hint: "huggingface-cli download black-forest-labs/flux-3-image-klein-pup --local-dir D:\\LLM\\LM-Studio\\models\\flux-3-image-klein-pup"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Abiray/flux-3-image-klein-sd-GGUF
    target_host: spark2
    reason: "GGUF quantization of flux3klein for the 12-GB tier that is excluded from the fp16/BF16 flux-3-image-klein-comfy lane. Choose Q5_K_M for the first evaluation (balance). Pairs with the Flux 2 Klein → Flux 3 Klein retirement pass."
    command_hint: "huggingface-cli download Abiray/flux-3-image-klein-sd-GGUF --include '*Q5_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\flux-3-image-klein-GGUF"
    risk: low

  - action: evaluate_llm_studio_default
    target_repo: deepseek-ai/DeepSeek-V4.1-Flash-1017
    target_host: theo
    reason: "Successor LLM for llm_delegate.py / llm_morning_briefing.py / upgrade_research.py local_llm backend. Image-text-to-text so viable for both prompt enhancement and image-grounded briefings. Trending at the top of HF this cycle (1,241 likes / 10.2K downloads in 24h). Deciding factor: does it beat the current LM Studio default on the Laborantin eval prompts (see tools/llm_delegate.py tests). No code change needed if we only swap the Settings.bat default model name."
    command_hint: "huggingface-cli download deepseek-ai/DeepSeek-V4.1-Flash-1017 --local-dir D:\\LLM\\LM-Studio\\models\\DeepSeek-V4.1-Flash-1017"
    risk: medium

  - action: evaluate_llm_studio_default
    target_repo: openbmb/MiniCPM-V-4.7-1B
    target_host: theo
    reason: "Smallest member of the MiniCPM-V 4.7 family — practical VLM for the Theo-local 8GB tier. Would ride into Settings.bat as a lightweight prompt-enhancer option alongside BennyDaBall/Qwen3-4b-Z-Image-Engineer-V4. 1B so fits easily; evaluate against the 4B Qwen3 for pound-for-pound image-grounded reasoning."
    command_hint: "huggingface-cli download openbmb/MiniCPM-V-4.7-1B --local-dir D:\\LLM\\LM-Studio\\models\\MiniCPM-V-4.7-1B"
    risk: low

  - action: run_disk_audit
    target_repo: null
    target_host: unknown
    reason: "The audit_disk_vs_registry.py tool shipped in this PR (T1-c) is now runnable on any fleet host that has D:\\LLM\\ComfyUI\\models/. Running it is what turns the standing 'audit_retirable_weights' Tier-3 entry (carried over below) into actionable orphan paths. Read-only; the operator still decides what to retire from the [ORPHAN] section."
    command_hint: "python tools/audit_disk_vs_registry.py --models-dir \"D:\\LLM\\ComfyUI\\models\""
    risk: low

  # ─── Carried over from 2026-10-16 (still open, re-filing) ─────────

  - action: download_and_evaluate_model
    target_repo: black-forest-labs/flux-3-image-klein-comfy
    target_host: spark1
    reason: "Flux 3 Klein base weights for the already-registered flux3klein arch (_reg at architectures.py:813). Base-flavour; the GGUF above covers the 12-GB tier."
    command_hint: "huggingface-cli login  # once\nhuggingface-cli download black-forest-labs/flux-3-image-klein-comfy --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\flux-3-image-klein"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark2
    reason: "Fast distilled companion to Qwen-Image-2.1. See Tier-2 non-model finding above — this is one of three Qwen-Image lanes; prefer the GGUF or Lightning LoRA path if operator picks either of the other two."
    command_hint: "huggingface-cli download unsloth/Qwen-Image-2.1-Turbo-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-Turbo-GGUF"
    risk: low

  - action: audit_sam3_version_on_fleet
    target_repo: facebook/sam3
    target_host: unknown
    reason: "build_sam3_segment uses the SAM3Segment ComfyUI node — this audit confirms which SAM3 weights that node is actually loading (3.0 vs 3.1 vs still-on-sam2). One-liner on each fleet host; no download yet."
    command_hint: "powershell -c \"Get-ChildItem D:\\LLM\\ComfyUI\\models -Recurse -Filter 'sam3*' | Select-Object FullName,Length\""
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/sam3.1
    target_host: spark1
    reason: "Updated preferred lane — Comfy-Org/sam3.1 (273K downloads, diffusion-single-file compatible with SAM3Segment node) over facebook/sam3.1 (97K downloads, raw checkpoint). The audit above runs first to confirm the node loader lane."
    command_hint: "huggingface-cli download Comfy-Org/sam3.1 --local-dir D:\\LLM\\ComfyUI\\models\\sam3\\sam3.1"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen
    target_host: spark1
    reason: "Alpha-matte / background removal adapter on top of LTX-2.5. Depends on LTX-2.5 base weights (also in queue). ~2 GB, no new base weights, unlocks a build_ltx_remove_bg_video builder."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Alpha-Gen"
    risk: low

  - action: download_and_evaluate_lora_pack
    target_repo: Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler
    target_host: spark1
    reason: "Spatial upscaler adapter on LTX-2.5. Pairs with existing supir image upscaler for a full video+image upscale set."
    command_hint: "huggingface-cli download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler --local-dir D:\\LLM\\ComfyUI\\models\\loras\\LTX-2.5-IC-Upscaler"
    risk: low

  - action: evaluate_sam3d_adjunct
    target_repo: facebook/sam-3d-body-dinov3
    target_host: unknown
    reason: "SAM 3D for human-mesh / body pose from a single image. Different task than Hunyuan3D (object mesh), so NOT a replacement; evaluate as a new builder family. Deciding point: human-mesh output format (SMPL-X vs GLB) vs. what spellcaster downstream tools consume."
    command_hint: "huggingface-cli download facebook/sam-3d-body-dinov3 --local-dir D:\\LLM\\ComfyUI\\models\\sam-3d\\body"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct upgrade path for _reg('ltx', ...). HF now shows 2.01M downloads / 8,318 likes on the base repo — confirmed dominant open-source i2v. Gated=auto; needs HF login the sandbox doesn't have."
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
    reason: "Cloud sandbox egress proxy still denies HF + civitai direct CONNECT (403), so tools/upgrade_research.py's live backends fall back to skeleton mode. This run's T1-b now gives the HF arch-query map eight more arches to probe when the tool DOES run from the LAN."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "Standing entry — now actionable thanks to T1-c. Point the tool at D:\\LLM\\ComfyUI\\models and read the [ORPHAN] section for retirement candidates. Especially relevant once Flux-3-Klein, LTX-2.5, or Hunyuan3D-2.1 lands (each one orphans the predecessor's weights)."
    command_hint: "python tools/audit_disk_vs_registry.py --models-dir \"D:\\LLM\\ComfyUI\\models\""
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items observed but not fixed in this run — scope-larger-than-safe or
needing the operator's read first.

1. **`ArchConfig.prompt_enhancer_model` field.** Three Tier-2
   prompt-enhancer rows now cite the same shape (`llm_delegate.py`
   should know which LLM is tuned for the arch currently in play).
   Would land as one new `extra["prompt_enhancer_model"]` string key
   on `ArchConfig` + a one-call dispatch in `llm_delegate.py`.
   Deferred as architectural (one place to pick the convention)
   rather than mechanical. See Tier-2 non-model finding above.

2. **Transport fallback for `tools/upgrade_research.py`.** Still the
   same gap flagged by every digest since 2026-09-22 — the tool's HF
   and civitai backends use `urllib`, which the cloud proxy 403s.
   Teaching the `huggingface` backend to prefer an MCP transport when
   available would let *this* routine run the ranked backend from the
   cloud instead of the skeleton one. Doable but it broadens the
   tool's dependency surface, so not shipped here.

3. **`hunyuan_dit` stub promotion / rename.** HunyuanImage-3.0 is a
   different arch (MoE, DiT-based but new encoder stack) than
   Hunyuan-DiT. Promoting the `hunyuan_dit` stub to
   `_reg("hunyuan_image_3", …, registered=True)` is a one-reg
   addition, but it is an architectural call (new scene_group? new
   `extra` fields for the MoE routing config?) and the quantized
   ComfyUI-ready variant has only 118 downloads at the moment — a
   premature registration would ship a slot the fleet does not fill.
   Hold until operator picks a lane.

4. **Backward-rename `hunyuan_dit` stub.** Separate from #3: the
   current stub name `hunyuan_dit` is a 2024-era name. If the
   operator decides to drop the stub (Hunyuan-DiT is not under
   active development), it should go rather than mislead
   `_hf_query_for_method` into looking up a dead term. Deferred as
   it is a REMOVAL, not an ADDITION — a cleanup pass, not an
   enabler.

5. **`.gitignore` carve-out pattern.** The one-line
   `!tools/audit_disk_vs_registry.py` added for T1-c is a precedent:
   future Tier-1-drafted audit tools will each need the same escape
   from `audit_*.py`. A future digest could refactor the top-level
   `audit_*.py` ignore to be scoped (e.g., only ignore
   `_audit/**/audit_*.py` rather than every path), but the current
   one-line carve-out is cheaper and better-documented until the
   second entry forces the pattern.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hf_fs`, `hub_repo_search`;
local `tools/upgrade_research.py --dry-run`; AST scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`; the
mirror-drift + model-coverage test suites._
