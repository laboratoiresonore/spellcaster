# Ecosystem digest — 2026-09-28

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-wwhau0`.

## Delivery notes

- **PR backlog visibility** — the last operator sync (2026-09-22) noted
  that ten prior ecosystem digest PRs (#164–#173) were all still open and
  unmerged. Since then, three security-hardening PRs on unrelated tracks
  have landed on main (#12 hook auto-enable, #14 fetch allowlist, #181
  LLM manifest + preflight). The ecosystem-digest queue itself has not
  drained. This digest still stacks its Tier-1 fixes on top of latest
  `main` so it stands alone as ready-to-merge, but the cadence caveat
  from 2026-09-22 remains: digests are generating faster than the review
  queue drains. If you want to slow it, pause the routine.
- **`tools/upgrade_research.py` exists and runs clean** (`4 proposals
  from 5 backends`, ISO week `2026-W40`). The gap the brief warns about
  (tool missing) is not present this run — output at
  `_dev_docs/upgrade_research/2026-W40.{json,md}`.
- **Leak-check on main is clean** — simulated the CI `git grep` locally
  against `.githooks/leak-patterns` and got zero hits. The
  self-referential false positives called out in previous digests have
  been eliminated by the pattern-list unification landed as part of #12.
  Any PR opened from this branch should not inherit red leak-check.
- **Gmail / Google-Drive MCP** — not called this run; the digest is
  delivered as the PR itself + this markdown file.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (52 pytest tests +
6 direct test files → all green; mirror-drift + cross-repo-drift +
manifest-drift → all clean; `night_maintenance.py --dry-mode` → exit 0).

### T1-a User-facing tool count still said "69" in four places

`README.md` and `DEEP_DIVE.md` were bumped to **75 tools** by the
2026-09-22 digest (which landed on main). But four other places kept
the stale "69" — three of them user-facing:

- **`installer/installer_gui.py:894`** — the Welcome dialog banner the
  installer shows before any install step (`"75 AI tools — generate
  images, fix photos, swap faces, remove backgrounds..."`).
- **`plugins/gimp/comfyui-connector/_spellcaster_main.py:1174`** — the
  splash subtitle rendered in the GIMP plugin's status panel
  (`"GIMP + ComfyUI + 75 AI tools, pre-configured and ready."`).
- **`installer/install.py:2075`** — the LLM upsell CLI blurb printed
  during install (`"Every one of the 75 tools gets better output
  automatically."`).
- **`scaffold/spellcaster_wizard.py:82,182`** — the wizard's docstring
  example (`total_methods: 75`) AND the LLM system-prompt plugin
  description (`"GIMP 3 — 75 AI tools in Filters > Spellcaster (most
  mature)"`). The latter is the more consequential: it's included in
  the prompt sent to the local LLM every session, so a stale count was
  actively misinforming the model about what surface capacity it has.

Source of truth: `plugins/gimp/comfyui-connector/spellcaster_core/builders_manifest.json`
→ `method_count: 75`, and `grep -c '^def build_'
plugins/gimp/comfyui-connector/spellcaster_core/workflows.py` → 75.

All four spots now say 75. Mirror-drift check is clean because none of
these paths are mirrored surfaces.

### T1-b `DEEP_DIVE.md`: per-arch enhance-profile count was 2 low

`DEEP_DIVE.md:649` claimed `_ARCH_ENHANCE_PROFILES` covers "9
architectures each with their own `max_tokens`, target `length`,
`style`, and guidance notes." AST-parsing the actual dict in
`comfyui-spellcaster/spellcaster_core/prompt_enhance.py` returns 11
distinct top-level keys: `flux1dev, flux2klein, chroma, sdxl, sd15,
illustrious, pony, wan, ltx, sd3, sd3_turbo`. Every entry has its
own body (checked — sd3 and sd3_turbo are not aliased). Bumped
"9 architectures" → "11 architectures". The paragraph's downstream
enumeration (SDXL / Flux 1 Dev / LTX Video / Klein / Illustrious)
already covers ≤ 11 by name so no other edits needed.

### Verification of T1-a through T1-b

- `python -m pytest tests/` — `52 passed`.
- Direct-run tests: `test_lora_auto_calibrate.py PASSED (59/59)`,
  `test_klein_enhancer.py PASSED (27/27)`, `test_quality_boost.py
  PASSED (54/54)`, `test_model_prompt_profiles.py PASSED (22/22)`,
  `test_model_coverage.py PASSED (19/19)`, `test_cn_compat.py PASS —
  all 280 pairs validated`, `test_auto_updater.py PASSED (5/5)`.
- `python tests/mirror_drift.py` — `OK: 29/29    DRIFT: 0    MISSING: 0`.
- `python tests/builders_manifest_drift.py` — `manifest fresh (75 methods)`.
- `python tests/cross_repo_drift.py` — `drift=0 missing=0`.
- `python tests/night_maintenance.py --dry-mode --quiet` — exit `0`.
- `python tools/upgrade_research.py --dry-run` — `4 proposals from
  5 backends`.
- `python scripts/generate_dependencies_md.py` then `git diff
  DEPENDENCIES.md` — no drift (script output matches committed file).
- AST-parsed each edited `.py` to confirm no syntax breakage from the
  string edits.

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP `hf_fs` on trending / lastModified,
budget-capped (used ~11 MCP calls of the 25-call soft budget).

| Model | Date | Replaces_method | VRAM (GB) | Risk | Tier | Notes |
|-------|------|-----------------|-----------|------|------|-------|
| `Qwen/Qwen-Image-2.1` (base fp16) | 2026-09-21 | new arch — no direct spellcaster replacement | ~18 fp16, ~10 fp8 | high | integration | Currently the #1 non-Klein text-to-image model on HF trending (2563 likes, 59K DL). Would be a genuinely new architecture for spellcaster (`_HF_ARCH_QUERIES` has no `qwen_image` entry, `architectures.py` has no `_reg("qwen_image", …)`). Community bundles: `Comfy-Org/Qwen-Image-2.1` (4.35M DL, official ComfyUI packaging), `unsloth/Qwen-Image-2.1-GGUF` (220K DL) for lower-VRAM. Not shovel-ready — needs a new `ArchConfig`, model_detect rules, a `build_qwen_txt2img` (and probably `_img2img`/`_inpaint`), and a prompt profile. Recommend a spike after the current Klein/Flux2 stabilisation lands. |
| `Viggle/Qwen-Image-2.1-viggle-turbo` | 2026-09-25 | turbo variant of the above | ~10 fp8 | medium | integration | Turbo distillation for Qwen-Image-2.1, 175K DL. Only makes sense once base Qwen-Image-2.1 is integrated (see row above). Follow-up, not prerequisite. |
| `Comfy-Org/SeedVR2` (repackage) | 2026-09-23 | `build_seedvr2_video_upscale` | ~12 (unchanged) | low | swap-in | Comfy-Org re-packaged the existing SeedVR2 weights spellcaster already uses (`build_seedvr2_video_upscale` in `workflows.py:5510`). 487K DL. Same architecture, official Comfy loading. Likely a drop-in URL swap in `installer/manifest.json` if it exposes cleaner loader nodes. Verify locally that the node names match `SeedVR2_comfyUI` before switching. |
| `feeday/Z-Image-Turbo-GGUF` | 2026-09-28 | zit arch (`build_zit_*`) memory footprint | ~4-6 (was ~10 fp16) | low | quantization | Fresh GGUF packaging for Z-Image Turbo (already registered in spellcaster as `zit`, arch key `zit` in `_HF_ARCH_QUERIES`). Would let zit run on ~6-8GB VRAM cards instead of ~10GB. New enough (today) that it's worth waiting a week for community validation before recommending. |
| `black-forest-labs/FLUX.2-klein-4b-fp8` | 2026-02-24 | `build_klein_*` VRAM path | ~5 (was ~10 fp16) | low | quantization | Official BFL fp8 build of Klein 4B (250K DL). Spellcaster's Klein pipeline currently uses fp16 4B/9B. fp8 4B would open Klein to ~8GB cards without needing GGUF. Low risk — same weights, native format, official. Merit a smoke test locally. |
| `prism-ml/Ternary-Bonsai-2-27B-gguf` | 2026-09-25 | LM Studio recommended shortlist | ~9-14 GGUF | medium | LLM-side | 3.4M DL, 2225 likes. Ternary-quant 27B is competitive with 7-13B models on chat and much cheaper to run. Would be a legitimate addition to `comfyui-spellcaster/spellcaster_core/comfyui_llm.py::_PER_FAMILY_LLM_CONFIG` or the LM Studio "recommended local LLM" list surfaced by the installer. Not a workflow architecture change; local LLM preference. |

**Skipped as noise (checked, not proposed):**

- Every `Muapi/*` LoRA hit — those are LoRA aggregator pages that spam
  every arch name into their model card; they don't map to a single
  spellcaster method.
- `black-forest-labs/FLUX.1-Klein-2.1` (previously proposed 2026-W39):
  no new activity, still not released as of today.
- `Wan 2.5` / `Wan 3` — searched, no upstream release yet, Wan 2.2
  remains current.

## Tier 3 — requires local fleet access (structured queue)

```yaml
local_action_queue:
  - action: download_and_smoketest_new_arch
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: Qwen-Image-2.1 is the top trending non-Klein text-to-image model on HF; spellcaster has no arch entry for it. A local smoke test on Spark 1 (loader + one 1024x1024 render) would establish whether it's worth an integration spike.
    command_hint: hfetch Comfy-Org/Qwen-Image-2.1 --dest D:/AI/ComfyUI/models/checkpoints/ && python -m comfyui_spellcaster.smoketest --arch qwen_image --ckpt qwen-image-2.1.safetensors
    risk: medium

  - action: try_quantized_klein
    target_repo: black-forest-labs/FLUX.2-klein-4b-fp8
    target_host: spark2
    reason: Official fp8 Klein 4B is ~5GB VRAM vs ~10GB fp16. If it passes visual parity against the current fp16 build_klein_txt2img on a 10-prompt set, spellcaster's Klein pipeline could add fp8 as the low-VRAM auto-pick.
    command_hint: hfetch black-forest-labs/FLUX.2-klein-4b-fp8 --dest D:/AI/ComfyUI/models/checkpoints/ && python -m comfyui_spellcaster.smoketest --arch flux2klein --ckpt flux2-klein-4b-fp8.safetensors --prompts tests/klein_parity_set.txt
    risk: low

  - action: evaluate_llm_addition
    target_repo: prism-ml/Ternary-Bonsai-2-27B-gguf
    target_host: theo
    reason: 27B ternary model trending at 3.4M downloads. If it beats current LM Studio recommended (Qwen2.5-14B / Nemotron) on the prompt-enhance eval set, add it to the LM Studio shortlist surfaced by the installer.
    command_hint: lms load prism-ml/Ternary-Bonsai-2-27B-gguf && python tools/llm_eval.py --model Ternary-Bonsai-2-27B --suite prompt_enhance
    risk: low

  - action: swap_seedvr2_bundle_if_compatible
    target_repo: Comfy-Org/SeedVR2
    target_host: unknown
    reason: Comfy-Org released an official SeedVR2 repackage (487K DL). If its node names match what spellcaster's build_seedvr2_video_upscale calls, swap installer/manifest.json to point at the official bundle. Verify node-name compatibility first.
    command_hint: hfetch Comfy-Org/SeedVR2 --dry-run --list-nodes | diff - <(grep -oP 'SeedVR2\w+' comfyui-spellcaster/spellcaster_core/workflows.py | sort -u)
    risk: low
```

## Corrections to prior operator memory notes

None this run. The 2026-09-22 digest's operator-memory notes (installer
splash claim, tool-count truthing) held up on re-audit.

## Tier 1 candidates deliberately downgraded

Reported here per the brief's rule ("if you are not confident a fix is
safe, downgrade it to Tier 2 and say why"):

1. **`DEEP_DIVE.md:52` mermaid says `~34K Python lines` for the GIMP
   plugin** — actual `_spellcaster_main.py` alone is now 37,366 lines,
   and top-level plugin `*.py` sums to ~40K. Bumping "~34K" → "~40K"
   is defensible but I'm not certain what the "~34K" was measuring
   (all of `plugins/gimp/comfyui-connector/`? just the main file at
   some past time?). Leaving it a soft claim rather than encoding a
   guess. Tier 2 for a human to decide the true count-basis.

2. **`README.md` / `DEEP_DIVE.md` / `DEPENDENCIES.md` / `tavern/server.py`
   all say "44 expert presets" for Inpaint & Fix** — AST-parsing the
   only `INPAINT_PRESETS` dict in the tree (in `_spellcaster_main.py`)
   returns 29 entries. Could be that some presets were merged / removed
   intentionally, or that "44" was a compound of a base list × body-part
   variants that no longer exists as separate structures. Because I
   can't confidently tell whether the correct fix is "44 → 29" or
   "restore missing presets", I'm leaving all four docs untouched and
   filing this as Tier 2 for a human to decide the direction.

3. **`DEEP_DIVE.md:61` mermaid box `workflows.py<br/>70+ build_* fns`**
   — actual is 75, but "70+" is a valid soft lower-bound that stays
   correct as new builders land. Style choice, not a stale fact. Skip.

## Follow-ups (candidates for future runs)

- The "44 expert presets" question above — worth a dedicated pass with
  operator input on whether to fix the docs down or restore the
  presets up.
- If ecosystem-digest PRs continue not merging, this routine should be
  paused explicitly rather than continuing to file new ones.
- Consider adding `qwen_image` to `_HF_ARCH_QUERIES` in
  `tools/upgrade_research.py` once the arch is integrated, so future
  sweeps can discover Qwen-Image variants automatically.
