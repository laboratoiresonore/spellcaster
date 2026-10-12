# Ecosystem digest — 2026-10-12

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-h8r9lx`.

## Delivery notes

- **Backlog unchanged** — twelve open PRs against `main` and none merged
  since the 2026-09-24 kanban drain (`2ebdf38`): #22, #48, #166, #183,
  #184, #185, #186, #187, #188, #189, #190, #191. Ten of those are
  ecosystem-digest PRs (every one of mine). PR #185 (2026-09-28) carries
  the exact "69 → 75" tool-count edits I had to carry again this cycle;
  PR #191 (2026-10-10) carries the novel architectures.py docstring
  refresh. **This cadence is still generating faster than review
  drains.** Flagged for operator decision (same options as before:
  merge one and close the rest as superseded, or pause the every-48h
  routine).
- **`tools/upgrade_research.py` ran clean** — `4 proposals from 5
  backends`, ISO week `2026-W42`. Output committed under
  `_dev_docs/upgrade_research/2026-W42.{md,json}`. The HF/civitai live
  backends still fall back to skeleton mode behind the sandbox proxy;
  Tier-2 model intel below comes from HF MCP (`hf_fs`,
  `hub_repo_search`), which uses a different transport.
- **Leak-check is clean on main** — simulated the CI
  `git grep -nIEi "$patterns"` locally against this branch, zero hits.
  2026-09-22 FU-1 remains closed.
- **Gmail / Google-Drive MCP** — not called this run; PR is the sole
  delivery channel.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes (`pytest tests/` →
52/52, `night_maintenance.py --dry-mode --quiet` → 0,
`mirror_drift.py --quiet` → 0).

The novel fix this cycle is **T1-g** (`tavern/wizard_speech.md` had an
even older `49 AI tools` claim that no prior digest touched). The other
six are carries from the open-PR stack: the branch stands alone against
today's `main` as a strict superset of what each individual carry
touches, so merging *this* PR (or any later single digest) still lands
all of them in one shot.

### T1-a `README.md:46` — status banner is one month stale

`📣 Status — September 2026` → `📣 Status — October 2026`. Today is
2026-10-12. **Shared with #186–#191.**

### T1-b/c `architectures.py` (both mirrors) — docstring date is one month stale

Both copies — `plugins/gimp/comfyui-connector/spellcaster_core/` and
`comfyui-spellcaster/spellcaster_core/` — carry
`SUPPORTED ARCHITECTURES (as of September 2026):`. Bumped to
`(as of October 2026):`, both files kept byte-identical
(`mirror_drift.py` exit 0). **Shared with #187–#191.**

### T1-d `installer/installer_gui.py:894` — Welcome dialog says "69 AI tools"

Four-month-stale user-facing count in the Windows installer's Welcome
dialog. Bumped to `75 AI tools —`. **Shared with #185.**

### T1-e `installer/install.py:2075` — CLI LLM-upsell blurb says "the 69 tools"

Printed during the LLM-detection step in the CLI installer. Bumped to
`75 tools`. **Shared with #185.**

### T1-f `plugins/gimp/comfyui-connector/_spellcaster_main.py:1174` — GIMP splash subtitle says "69 AI tools"

Rendered as the subtitle of the plugin's bundle-welcome panel the first
time GIMP picks the plugin up. Bumped to `75 AI tools, pre-configured
and ready.`. **Shared with #185.**

### T1-g `tavern/wizard_speech.md:218` — wizard speech says "49 AI tools" (NOVEL)

The Guild wizard-speech markdown advertises `**49 AI tools right inside
GIMP**` — an *even older* count than the "69" that landed everywhere
else, from a time when the GIMP plugin exposed roughly 49 Filters →
Spellcaster entries. No prior digest or open PR touches this file.
Bumped to `**75 AI tools right inside GIMP**` to match the ground truth
(`method_count: 75` in `builders_manifest.json`, `grep -c '^def build_'
plugins/gimp/comfyui-connector/spellcaster_core/workflows.py` → 75).

This file is read-only reference material (not loaded at runtime by any
Python), so the bump cannot regress any code path — but it IS the
canonical wizard-speech corpus that scaffold tooling can draw from for
Guild chat system prompts, so the stale "49" was actively misinforming
whatever downstream flow consumes it.

### T1-h `scaffold/spellcaster_wizard.py:82` — docstring example `total_methods: 69`

The module docstring documents the system-manifest shape with an
example object whose `total_methods` field reads `69`. Bumped to `75`
to match ground truth and the file's own `PLUGIN_DESCRIPTIONS` entry
one page down (which **PR #185** already bumps to 75). **Shared with
#185** on the plugin-description edit at line 182; the docstring
example at line 82 is **novel to this run** — PR #185's diff only
touches line 82 to the same effect but has been open since 2026-09-28
without merge, so I'm carrying it rather than relying on it to land.

### Verification

- `pytest tests/` — `52 passed in 9.50s` on this branch, same as
  baseline `ecf4249`. No regression (every T1 edit is a string
  literal; no code path changes).
- `python tests/mirror_drift.py --quiet` — exit `0`, both
  `architectures.py` copies byte-identical.
- `python tests/night_maintenance.py --dry-mode --quiet` — exit `0`.
- `python tools/upgrade_research.py --dry-run` — clean, `4 proposals
  from 5 backends`; this week's output committed under
  `_dev_docs/upgrade_research/2026-W42.{md,json}`.
- Simulated the leak-check workflow's own `git grep -nIEi "$patterns"`
  invocation against this branch → **zero hits**.
- AST-parsed `installer/installer_gui.py`, `installer/install.py`,
  `plugins/gimp/comfyui-connector/_spellcaster_main.py`,
  `scaffold/spellcaster_wizard.py` and both `architectures.py` after
  edits — all parse clean.
- `grep -rnE "\b(69|49) (AI )?tools\b"` across the tree now returns
  **zero hits** (prior-digest files in `_dev_docs/` excluded).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via HF MCP `hf_fs ls hf://models/trending` + targeted
`hub_repo_search` on `Qwen-Image-2.1-Turbo`, `Wan 2.3`, `Wan-AI`,
`SeedVR3`, `Flux Krea 2`, `Hunyuan3D 2.2`, `illustrious XL v2 GGUF`,
`Comfy-Org Qwen-Image-2.1`, `embeddinggemma-2 ONNX`
(used ~9 MCP calls of the 25-call soft budget). Deltas vs the
2026-10-08 digest are called out where the signal has moved.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Qwen/Qwen-Image-2.1-Turbo** | 2026-10-09 | 4-step distill companion of the Qwen-Image-2.1 arch flagged in #190 | ~10 GB fp8 (same 7.1B base) | low | 2 | **604 likes / 6.8K DL in 48h, 10+ demo Spaces live.** Already surfaced on today's `hf://models/trending`. **Delta vs 2026-10-08**: #191 called this out at 408 likes / 2.1K DL; it is still climbing but the signal is now ~2× stronger, confirming it is the right default tier for low-VRAM Qwen-Image-2.1 landings. Would land in the SAME PR as the base `_reg("qwen_image", …)` with `turbo_config` wired to 4 steps / cfg=1.0 (Z-Image-Turbo-shape). GGUF companion already exists: `unsloth/Qwen-Image-2.1-Turbo-GGUF` (108K DL / 36 likes), `AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF` (162K DL / 363 likes). The uncensored GGUF is NSFW-flagged → H6 handoff to `spellcaster_NSFW`. |
| **Comfy-Org/Qwen-Image-2.1** | 2026-09-15 | Base arch (ComfyUI-native single-file) | ~16 GB fp8 (7.1B params) | low | 2 | **1,077 likes / 9.1M DL**, up from 1.4M DL at 2026-09-22 and 3.6M at 2026-10-08. Monotonically climbing. Still the preferred integration surface for the base arch (no diffusers-pipeline shim). |
| **Lightricks/LTX-2.5** | 2026-10-11 | Direct successor to current `ltx` arch (points at LTXV-2.3) | ~24 GB | medium | 2 | **7,411 likes / 1.72M DL** — up from 7,133 / 1.6M at #191 (two days ago). Still `gated=auto` on HF → fleet-only download. Carry-over from 2026-09-22 (no completion signal yet). |
| **Qwen/Qwen-Image-Edit-2511** | 2025-12 (last mod 2026-09) | Default for `build_edit_by_instruction` + `build_qwen_edit` (the latter has `qwen_edit_version="2511"` opt-in in PR #48) | ~20 GB fp8 (20.4B) | medium | 2 | Carry-over from 2026-10-08: **2.0M DL / 1,450 likes**, 100+ demo Spaces. Spawned the `Alissonerdx/BFS-Best-Face-Swap` LoRA ecosystem (1,315 likes / 243K DL + 9 community mirrors). Entry point remains **operationalize PR #48** — rebase against today's HEAD, promote the opt-in to default. |
| **google/embeddinggemma-2** | 2026-10-06 | Local-prompt-enhancer embedding backend candidate | ~300 MB | low | 2 | **1,880 likes / 115K DL on the base** (up from 1,128 / 21K at #190, two days ago). ONNX port landed: `onnx-community/embeddinggemma-2-ONNX` (102.6K DL / 18 likes) is the deployment path for the morning-briefing / Guild chat flows. Tiny, A/B-safe. |
| **Cloudflare/clef** + **clef-flash** | 2026-10-09 | New VLM candidate for Wizard Guild / Portraitist chat flow | ~8–14 GB (model-size undisclosed) | low | 2 | **2,073 + 780 likes / 15K + 23K DL in 48h.** Image-text-to-text (VLM) class — same slot as the current VLM step in the Guild. **Delta vs #191**: now live on HF trending at #4 (`clef` base) and #16 (`clef-flash`). Not a core-image-path change. A side-by-side with `LiquidAI/d1-3B` (328 likes / 12K DL, 3B VLM) would answer the "do we switch" question. |
| **MiniMaxAI / MiniMax-H3 family** | ongoing | New video arch not in current `_reg` set | ~24 GB+ fp8 | high | 2 | Carry-over from #184/#186/#189/#190 — still deserves its own `_reg("minimax_h3", …)` slot pending LAN VRAM / quality eval. No new signal this cycle. |

### Tier-2 non-model finding

- **Illustrious-XL-v2.0 GGUF stays worth watching, not acting on yet.**
  `offgrid-ai/illustrious-xl-v2.0-GGUF` is at **4.0K DL / 3 likes** —
  the alternative `btaskel/Illustrious-XL-v2.0-GGUF` is at 733 / 9
  likes. Neither reached the Qwen-tier adoption that would justify a
  `_reg("illustrious", …)` quant swap on its own; keep it on the Tier-2
  radar for one more cycle before promoting to a fleet download.

- **Qwen3.8-27B on HF trending** (17,555 likes / 6.9M DL, #7 on trending) is a plain-text LLM
  for prompt-enhance / Guild chat delegation — not a workflow-architecture change. It belongs in
  `_PER_FAMILY_LLM_CONFIG` consideration for the Guild / LM Studio shortlist, not in
  `architectures.py`. Mentioned here so no later digest proposes it as an image arch.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Structured entries. A local Hermes / operator process consumes this
block mechanically rather than a human re-deriving commands from prose.
Every `command_hint` is best-effort — the operator adjusts for the
fleet's exact model directory layout.

```yaml
local_action_queue:
  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark1
    reason: "Fresh 4-step distill of Qwen-Image-2.1 (604 likes / 6.8K DL in 48h, up 2x from #191's reading two days ago). Land in the SAME PR as the base Qwen-Image-2.1 _reg entry with turbo_config wired to 4 steps / cfg=1.0 (Z-Image-Turbo-shape). Low-VRAM default for 12GB cards once the base arch ships."
    command_hint: "huggingface-cli download Qwen/Qwen-Image-2.1-Turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1-Turbo --local-dir-use-symlinks False"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Carry-over from 2026-09-22 / 2026-10-08 / 2026-10-10. 9.1M DL (monotonically climbing — 1.4M → 3.6M → 9.1M across three cycles). ComfyUI single-file single-shot drop into checkpoints/. Evaluate quality against existing SDXL/Flux2Klein routes before wiring _reg('qwen_image', ...). Pair with Qwen-Image-2.1-Turbo above."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_vlm
    target_repo: Cloudflare/clef-flash
    target_host: spark2
    reason: "New VLM candidate for the Wizard Guild / Portraitist chat flow. 780 likes / 23K DL in 48h on the flash variant (clef base at 2073 likes / 15K DL). Side-by-side with LiquidAI/d1-3B (3B params, 328 likes / 12K DL) on an existing portrait-describe prompt set would answer whether we switch the VLM step. Not a core-image-path change; safe to A/B."
    command_hint: "huggingface-cli download Cloudflare/clef-flash --local-dir D:\\LLM\\ComfyUI\\models\\vlm\\clef-flash\n# also:\nhuggingface-cli download LiquidAI/d1-3B --local-dir D:\\LLM\\ComfyUI\\models\\vlm\\d1-3B"
    risk: low

  - action: evaluate_embedding_backend
    target_repo: onnx-community/embeddinggemma-2-ONNX
    target_host: spark2
    reason: "ONNX port of embeddinggemma-2 (102.6K DL / 18 likes) — the deployment path for the morning-briefing / Guild chat embedding step called from tools/llm_morning_briefing.py. Base model climbed from 1,128 / 21K at #190 to 1,880 / 115K now — the trajectory confirms it's not a flash in the pan. Tiny (~300MB), safe to A/B against existing embedding backend."
    command_hint: "huggingface-cli download onnx-community/embeddinggemma-2-ONNX --local-dir D:\\LLM\\embeddings\\embeddinggemma-2-ONNX"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "7,411 likes / 1.72M DL (up from 7,133 / 1.6M at #191 two days ago). Direct upgrade for _reg('ltx', ...). Gated=auto on HF — needs an HF login the cloud sandbox doesn't have. CARRY-OVER from 2026-09-22 — still no completion signal."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: hand_off_to_nsfw_pipeline
    target_repo: AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF
    target_host: unknown
    reason: "NSFW-tagged GGUF of the Qwen-Image-2.1-Turbo variant (161.7K DL / 363 likes). Per H6 SFW-canon rule this stays out of the public spellcaster repo. If the NSFW pipeline wants a low-VRAM Qwen-Image-2.1-Turbo route, this is the dominant community pick on the uncensored side."
    command_hint: "# forward to spellcaster_NSFW maintenance queue; do NOT add to the public spellcaster repo"
    risk: low

  - action: rerun_upgrade_research_from_lan
    target_repo: null
    target_host: unknown
    reason: "The cloud sandbox's egress proxy denies direct HF and civitai CONNECT (403), so tools/upgrade_research.py's live backends still fall back to skeleton mode (--dry-run: 4 stub proposals). Running the same tool from the LAN (spark1 or the dev host) will exercise the real HF + civitai backends and produce the ranked shopping list this run couldn't. CARRY-OVER from 2026-09-22 and every digest since — still unresolved."
    command_hint: "python tools/upgrade_research.py --backends huggingface,civitai,comfy_manager,local_index --methods build_illustrious_txt2img,build_wan_video,build_klein_repose"
    risk: low

  - action: revisit_pr_48
    target_repo: null
    target_host: dev-host
    reason: "PR #48 (open since 2026-05-19) carries qwen_edit_version='2511' + HunyuanVideo-1.5 + SAM 3.1 opt-ins against a 2026-05 baseline. Qwen-Image-Edit-2511 is now the dominant edit model on HF (2M DL / 1,450 likes). Rebase against today's HEAD, promote qwen_edit_version='2511' to default, merge. CARRY-OVER from 2026-10-08."
    command_hint: "gh pr checkout 48 && git rebase origin/main && python tests/mirror_drift.py && gh pr ready 48"
    risk: medium

  - action: audit_retirable_weights
    target_repo: null
    target_host: unknown
    reason: "If Qwen-Image-2.1(+Turbo) lands and LTX-2.5 replaces LTXV-2.3, older weights on D:\\LLM should be flagged for retirement to free space. CARRY-OVER from 2026-09-22 — still unresolved. Mechanical: compare architectures.py registered=True set against ComfyUI/models/* on disk."
    command_hint: "python tools/audit_disk_vs_registry.py  # tool does not yet exist; see Follow-ups below."
    risk: low
```

## Corrections to prior operator memory notes

- **2026-09-22 FU-1 (`leak-check.yml` scrub)** — closed by `2ebdf38` /
  `329761b`. Verified clean on today's HEAD. Already struck in #191;
  re-confirming here.
- **2026-09-22 FU-2 (`fetch_metadata.py` TLS-verify disable)** —
  closed by `2ebdf38` / `cd01ad2`. `grep -n 'CERT_NONE|check_hostname|
  verify_mode' fetch_metadata.py` → zero hits on main. Already struck
  in #191; re-confirming here.
- **No new corrections** this run.

## Follow-ups filed as future Tier-1 candidates

1. **Stacked-PR drain decision (unchanged, highest-priority)** — ten
   open digest PRs (#166, #183, #184, #185, #186, #187, #188, #189,
   #190, #191) now stacked on main. Every single one shares at least
   one Tier-1 fix with every other. Operator picks a merge/close
   policy or the queue keeps growing by one every 48h. The individual
   digests remain honest — nothing is misreported — but reviewer load
   on each one is now dominated by "did I already see this edit?"
   rather than content.

2. **`tools/upgrade_research.py` transport fallback (carry-over)** —
   HF + civitai backends still use stdlib `urllib`; sandbox proxy
   403s at CONNECT. Teaching the tool to prefer an HF MCP transport
   when available would let this routine run the real backend from
   the cloud. Still not shipped.

3. **PR #48 operationalization (carry-over from #190)** — the
   SOTA-opt-ins PR has been open since 2026-05 with Qwen-Image-Edit-2511
   as an opt-in. The underlying weight is now the dominant edit model
   on HF (2M DL). Promoting the opt-in to default is the single
   highest-impact outcome of a near-term cycle. Filed as Tier-3 action
   above.

4. **`44 expert presets` claim across four files** (carry-over from
   #185) — `README.md`, `DEEP_DIVE.md`, `DEPENDENCIES.md`,
   `tavern/server.py` all advertise 44 expert presets for Inpaint &
   Fix, but AST-parsing the only `INPAINT_PRESETS` dict returns 29.
   Could be a down-fix ("44 → 29") OR restore-missing. Needs the
   operator's read; deferred to Tier-2 (same as #185).

5. **`DEEP_DIVE.md:52` mermaid `~34K Python lines`** (carry-over from
   #185) — `_spellcaster_main.py` alone is now ~37K lines, and
   top-level plugin `*.py` sums to ~40K. "~34K" is a soft claim worth
   bumping, but basis is ambiguous (which files does the count
   include?). Deferred to Tier-2 for the operator.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hf_fs ls hf://models/trending`,
`hub_repo_search`; local `tools/upgrade_research.py --dry-run` (output
at `_dev_docs/upgrade_research/2026-W42.{json,md}`); AST scans of
`architectures.py`, `workflows.py`, `builders_manifest.json`;
`git grep -nIEi` scans of the whole tree against `.githooks/leak-patterns`
for the leak-check gate._
