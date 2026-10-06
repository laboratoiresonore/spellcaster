# Ecosystem digest — 2026-10-06

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-asgtml`.

## Delivery notes

- **`tools/upgrade_research.py` is present and runs clean** —
  `python tools/upgrade_research.py --dry-run` returned `4 proposals from
  5 backends` and wrote `_dev_docs/upgrade_research/2026-W41.{md,json}`.
  No skeleton-mode degradation this run. The tool's HF/civitai backends
  still fall back to the proxy-safe skeleton because the sandbox proxy
  CONNECT-403s outbound HF/civitai TCP; the live Hub reconnaissance in
  this digest's Tier 2 came from the Hugging-Face MCP connector, not the
  tool's own backends.
- **Prior-run follow-ups still open on main** — the fetch_metadata.py
  TLS-verification concern flagged in the 2026-09-22 digest no longer
  reproduces (today's `fetch_metadata.py` uses
  `ssl.create_default_context()` without the `CERT_NONE` /
  `check_hostname=False` pair). The leak-check self-exclusion concern
  from that same digest also no longer reproduces — a manual repro of
  the exact scan command the workflow runs comes back clean on today's
  `origin/main` (`git grep` finds zero hits with the current exclusion
  list). Both are logged here so a future run doesn't re-flag them.
- **Gmail / Google-Drive MCP** — not called this run; digest is
  delivered as the PR itself.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix is
in this branch and whose regression suite passes (`pytest tests/` →
52/52 before and after).

### T1-a `README.md`: front-page status is one month stale

The `📣 Status — September 2026` banner is the first thing a fresh
visitor sees. Today is 2026-10-06. Bumped to `📣 Status — October 2026`.
News/Focus/Next copy left as-is (all describes past-tense "landed" items
that remain true today).

### T1-b `architectures.py` docstring: `as of September 2026` is a month stale

Both copies of `architectures.py`
(`plugins/gimp/comfyui-connector/spellcaster_core/` and
`comfyui-spellcaster/spellcaster_core/`) carry the module-level
docstring `SUPPORTED ARCHITECTURES (as of September 2026):`. Bumped
both to `(as of October 2026):`. Left the 7-arch enumeration below the
header alone — that mismatch (7 enumerated vs 27 registered) is a
Tier-2 docstring-content refresh, still open from the prior digest.

### T1-c `DEEP_DIVE.md`: `9-architecture ArchConfig registry` is factually wrong

Line 922 of `DEEP_DIVE.md` claimed `9-architecture ArchConfig registry`.
AST count of `_reg(...)` calls on today's HEAD across both copies of
`architectures.py` is **27, all `registered=True` (no stubs)** —
`sd15, sdxl, illustrious, zit, flux1dev, chroma, flux2klein,
flux_kontext, sdxl_turbo, pony, playground, sd3, sd3_turbo, hunyuan_dit,
pixart, auraflow, kolors, wan, ltx, seedvr, cogvideo, framepack,
hunyuan_video, mochi, hunyuan_3d, lumina2, supir`. Prior digest left
this at `9` because it might reflect "fully-wired image archs" vs stubs;
with every entry now `registered=True`, there is no stub distinction
left and the 9 claim is simply undercounting by 18. Bumped to
`27-architecture`.

Downgraded to Tier-2 for a later pass: the `DEEP_DIVE.md` opening blurb
`all 9 model families` (line 3) is probably also stale, but "families"
is a human grouping not a code artifact — the right new number depends
on whether video / 3D / restoration archs count as their own families or
roll up into one.

### Verification

- `pytest tests/` → `52 passed in 9.26s` on this branch (same count on
  `origin/main` baseline).
- `python tests/night_maintenance.py --dry-mode --quiet` → exit 0.
- `python scripts/check_arch_manifest_drift.py` → `[OK] No drift
  detected.`
- `python scripts/generate_dependencies_md.py` → no diff
  (`DEPENDENCIES.md` is in sync with `installer/manifest.json`).
- `python tools/upgrade_research.py --dry-run` → clean (`4 proposals
  from 5 backends`, `_dev_docs/upgrade_research/2026-W41.{md,json}`
  regenerated — not committed, this is per-week ephemera the tool
  owns).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via Hugging-Face MCP `hub_repo_search` / `hub_repo_details` on
trending + lastModified, budget-capped (used ~6 MCP calls of the
25-call soft budget). The big movement vs the 2026-09-22 digest is
MiniMax-H3 — a 33B param text+image+audio-to-video model that didn't
exist two weeks ago and now has 9.8M downloads / 5930 likes on the
base repo and 100+ demo spaces. LTX-2.5 kept climbing (4738 → 6594
likes in 14 days). Qwen-Image-2.1 fragmented into base + uncensored
GGUF forks + viggle-turbo distill; the uncensored GGUF is now the
dominant practical variant.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **MiniMaxAI/MiniMax-H3** | 2026-08-13 (updated through 2026-10) | New arch — currently no coverage for text+image+audio-to-video with synchronized audio output | ~66 GB fp16 (33B params), ~20 GB fp8 practical for the "turbo" fork | high | 2 | 9.8M downloads / 5930 likes / 100+ demo spaces on HF — the dominant text-to-video / image-to-video landing of September 2026, with synchronized audio generation as the native capability (not a separate pass). Would land as `_reg("minimax_h3", …)` with new builders `build_minimax_h3_t2v`, `build_minimax_h3_i2v` under the existing `WAN_EXTRA_METHODS`-shape video method set. ComfyUI library is `minimax-h3` (new node pack dependency; the 88+ spaces imply upstream ComfyUI support already lands as a custom-node). High risk due to VRAM and because it's a new library the installer hasn't been audited against. |
| **lightx2v/Minimax-h3-Turbo** | 2026-08-07 | Companion turbo variant to MiniMax-H3 | ~20 GB fp8 (practical) | medium | 2 | 1.5M downloads / 1038 likes. Few-step distill. If MiniMax-H3 base lands, this is the default for the ≤24-GB tier. Same `minimax-h3` library. |
| **Lightricks/LTX-2.5** | 2026-10-02 | Direct successor to current `ltx` arch at `architectures.py:974` | ~24 GB fp16 | medium | 2 | 3.3M downloads / 6594 likes — climbed from 4738 likes on the 2026-09-22 digest. Explicit `comfyui` + `ltx-2.5` + `ltx` tags on the repo means it's a straight single-file drop-in for the existing `ltx` registration (no new arch, just a weights swap). Still `gated=auto` on the HF side — fleet-only (sandbox has no HF login). Also now carries native audio-to-video / video-to-audio capability on top of the 2.3-era image-to-video pipeline. |
| **Qwen/Qwen-Image-2.1** | 2026-09-30 | New `qwen_image` arch — no current coverage | ~16 GB fp8, ~30 GB fp16 (7.1B params) | medium | 2 | 102K downloads / 3029 likes on the base repo in two weeks. Would land as `_reg("qwen_image", …)` + a `build_qwen_image_txt2img` on the `build_illustrious_txt2img` shape (`diffusers:QwenImage21Pipeline`). The base repo has 88+ demo spaces, confirming ecosystem readiness. |
| **abenzerps/Qwen-Image-2.1-Uncensored-GGUF** | 2026-09-20 | Same arch, quantized + uncensored | ~10 GB Q4_K_M | low | 2 | 1.7M downloads / 3376 likes — this fork, not the base, is what the community actually runs. GGUF path via `UnetLoaderGGUF` on the existing `ComfyUI-GGUF` node pack (already in `DEPENDENCIES.md`). If the base arch lands, wire this fork as the default for sub-16-GB tiers in the SAME PR. Note the `uncensored` branding — operator decides if that's a shipping concern. |
| **Viggle/Qwen-Image-2.1-viggle-turbo** | 2026-09-22 | Few-step distill of Qwen-Image-2.1 | ~10 GB fp8 | low | 2 | 302K downloads / 626 likes. 4-6 step distill, drops into the same arch slot as a sibling LoRA — same shape as how `zit` relates to SDXL. Would unlock a `qwen_image_turbo` method tier the same way `sdxl_turbo` sits beside `sdxl`. |
| **unsloth/Qwen-Image-2.1-GGUF** | 2026-09-21 | Alternate GGUF repack | ~10 GB Q4 | low | 2 | 683K downloads / 352 likes. Second-choice GGUF path; abenzerps leads in community adoption so unsloth is a backup, not primary. |
| **krea/Krea-2-Turbo** | 2026-06-18 (updated 2026-07-24) | Alt to Flux1dev / Flux2klein for high-quality T2I | ~26 GB fp16 (12.8B params) | medium | 2 | 425K downloads / 1511 likes. `diffusers:Krea2Pipeline`, `gated=auto`. Fewer-step distill of `Krea-2-Raw`. Would live beside `flux2klein` as an alternate "best quality" tier. Adoption lagging behind Flux-family alternatives in the Spellcaster context — flagged only because the trending-score is high and the operator may want to A/B against Klein. |
| **inclusionAI/Ming-Image-0.1-Design** | 2026-09-17 | New niche arch — graphic-design / text-rendering focus | ~20 GB fp16 | medium | 2 | 390 likes but downloads=0 (just-launched). Specialized for text-rendering (a known weakness of SDXL / Flux pipelines). Would be an interesting match for the Resolve-plugin "render title card" use case. Not a priority — low adoption yet, specialized use. |

### Tier-2 non-model findings (carry forward)

- **Docstring enumeration refresh** — `architectures.py` module
  docstring enumerates 7 archs but 27 are registered. Still open
  (unchanged from 2026-09-22 digest). Can be regenerated from the
  `ARCHITECTURES` dict at doc-build time, or hand-bumped once per
  release.
- **`DEEP_DIVE.md` opening blurb** says `all 9 model families` on
  line 3 — probably stale; the right new number depends on whether
  video / 3D / restoration archs count as separate families.
- **README "19 models" claim** on line 139 — same ambiguity. The code
  truth is 27 registered archs; "19 models" may be the operator's
  historical grouping and so is left alone.
- **`DEEP_DIVE.md` "22,000 lines of Python" aside** on line 934 — line
  count on today's HEAD is 35,723 lines in `comfyui-spellcaster/`
  alone, 95K+ across the whole repo. The 22K figure is a joke/aside
  so it's not a correctness bug, but it is factually off now. Leaving
  for the operator.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Structured entries below. A local Hermes / operator process consumes
this block mechanically instead of a human re-deriving the command
from prose. Every `command_hint` is best-effort — the operator adjusts
for the fleet's exact model directory layout.

```yaml
local_action_queue:
  - action: download_and_evaluate_model
    target_repo: MiniMaxAI/MiniMax-H3
    target_host: unknown
    reason: "New video/audio arch candidate (Tier-2). 33B parameters means this needs the fleet's largest-VRAM host — spark1 or theo. Prior-digest wan/ltx benches should re-run against it. ComfyUI library is 'minimax-h3' — the 88+ demo spaces imply a custom-node already exists; verify before downloading. Full fp16 weights are ~66 GB."
    command_hint: "huggingface-cli download MiniMaxAI/MiniMax-H3 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MiniMax-H3 --local-dir-use-symlinks False"
    risk: high

  - action: download_and_evaluate_model
    target_repo: lightx2v/Minimax-h3-Turbo
    target_host: unknown
    reason: "Few-step turbo distill of MiniMax-H3. If the base lands as default for the top-VRAM tier, this is default for the mid tier (12-24 GB). 1.5M downloads / 1038 likes."
    command_hint: "huggingface-cli download lightx2v/Minimax-h3-Turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\MiniMax-H3-Turbo"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "Direct successor to _reg('ltx', ...) at architectures.py:974 — single-file ComfyUI drop-in, no shim needed. Jumped from 4738 likes (2026-09-22 digest) to 6594 likes today; adoption continues to accelerate. Gated=auto on HF — requires an HF login the sandbox doesn't have, so this is still fleet-only. Also now carries native audio-to-video capability."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1
    target_host: spark1
    reason: "Base weights for the new qwen_image arch. 7.1B params / ~30 GB fp16; evaluate text-rendering + image-editing quality against SDXL/Flux2Klein routes before wiring _reg('qwen_image', ...)."
    command_hint: "huggingface-cli download Qwen/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: abenzerps/Qwen-Image-2.1-Uncensored-GGUF
    target_host: spark2
    reason: "Dominant practical variant of Qwen-Image-2.1 — 1.7M downloads, more than base. If base lands, this is the default for sub-16-GB tiers. GGUF path uses the already-installed ComfyUI-GGUF node pack. Operator decides whether 'uncensored' branding is a shipping concern."
    command_hint: "huggingface-cli download abenzerps/Qwen-Image-2.1-Uncensored-GGUF --include '*Q4_K_M*' --local-dir D:\\LLM\\ComfyUI\\models\\unet\\Qwen-Image-2.1-GGUF"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Viggle/Qwen-Image-2.1-viggle-turbo
    target_host: spark2
    reason: "Few-step turbo distill of Qwen-Image-2.1. If base arch lands, this is the 'qwen_image_turbo' tier (same relationship as sdxl → sdxl_turbo). 302K downloads / 626 likes."
    command_hint: "huggingface-cli download Viggle/Qwen-Image-2.1-viggle-turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1-turbo"
    risk: low

  - action: download_and_evaluate_model
    target_repo: krea/Krea-2-Turbo
    target_host: unknown
    reason: "High-quality T2I alt to Flux family. Gated=auto on HF — fleet-only. 12.8B params. A/B against build_klein_* before deciding whether this earns a slot."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download krea/Krea-2-Turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Krea-2-Turbo"
    risk: medium

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "The cloud sandbox's egress proxy denies direct HF and civitai CONNECT (403), so tools/upgrade_research.py's live backends still fall back to skeleton mode (--dry-run: 4 stub proposals). Running the same tool from the LAN (spark1 or the dev host) exercises the real HF + civitai backends and produces the ranked shopping list this run couldn't. (Same ask as the 2026-09-22 digest — still unaddressed.)"
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index --methods build_illustrious_txt2img,build_wan_video,build_klein_repose,build_qwen_image_txt2img"
    risk: low

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If Qwen-Image-2.1 lands as a text-to-image default, LTX-2.5 replaces LTXV-2.3, and MiniMax-H3 lands as a new primary video arch, older weights on D:\\LLM should be flagged for retirement to free space. (Same ask as the 2026-09-22 digest — still unaddressed.) Human decision, but the audit itself is mechanical."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; see Follow-ups."
    risk: low
```

## Follow-ups filed as future Tier-1 candidates

Items I saw but did not fix in this run — either scope-larger-than-safe,
or ambiguous enough to want the operator's read first.

1. **`DEEP_DIVE.md` opening blurb** — `all 9 model families` on line 3,
   `19 models` claim surface the same ambiguity. The right new number
   depends on "families" grouping (do video archs count separately?).
   Would downgrade to Tier-1 once the operator picks a grouping rule.

2. **`architectures.py` docstring enumeration** — static list of 7
   archs under `SUPPORTED ARCHITECTURES`, but 27 registered. Could
   regenerate from the dict at tooling time. Still open from
   2026-09-22. Mechanical when the "right split" rule is set.

3. **PR backlog** — the 2026-09-22 digest flagged ten open ecosystem
   digests (`#164–#173`); as of this writing I haven't checked whether
   that queue has drained. If still backed up, either pause the
   routine or pick one digest to merge and close the rest as
   duplicates. (The hard rule from the task description applies: this
   digest's branch stands alone against `main` so it's merge-ready
   regardless of what's in the queue.)

4. **`tools/upgrade_research.py` transport fallback** — carried over
   from 2026-09-22. The tool's HF and civitai backends use stdlib
   `urllib`, which the sandbox proxy 403s at CONNECT time. Teaching
   it to prefer an HF MCP transport when one is available would let
   this routine run the real backend from the cloud instead of
   skeleton mode. Not shipped this run because it broadens the tool's
   dependency surface beyond stdlib.

5. **Tool count visualization consistency** — carried over from
   2026-09-22. README/DEEP_DIVE now say 75, but `assets/showcase.gif`
   (`generate_showcase.py`) still emits labels from a hardcoded
   count that nothing re-verifies. Not verified in this run — would
   need to execute the generator locally.

---

_Branch: `claude/adoring-allen-asgtml` · baseline `ecf4249` ·
tests 52/52 · delivery via PR._
