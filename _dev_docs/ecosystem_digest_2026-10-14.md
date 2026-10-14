# Ecosystem digest — 2026-10-14

Every-48h cloud-side research + maintenance sweep. Baseline: `origin/main`
(sha `ecf4249`). Branch: `claude/adoring-allen-mrqjmw`.

## Delivery notes

- **Backlog unchanged, growing** — thirteen open PRs against `main` and
  none merged since the 2026-09-24 kanban drain (`2ebdf38`): #22, #48,
  #166, #183, #184, #185, #186, #187, #188, #189, #190, #191, #192.
  Eleven of those are ecosystem-digest PRs from this same routine. PR
  #192 (2026-10-12) carries most of the current Tier-1 drift list;
  this PR stacks the single novel finding on top of that same stack so
  the branch stands alone as a strict superset against today's main.
  **This cadence is still generating faster than review drains.**
  Flagged for operator decision (same options as before: merge one
  and close the rest as superseded, or pause the every-48h routine).
- **`tools/upgrade_research.py` ran clean** — `4 proposals from 5
  backends`, ISO week `2026-W42`. Output committed under
  `_dev_docs/upgrade_research/2026-W42.{md,json}`. The HF/civitai live
  backends still fall back to skeleton mode behind the sandbox proxy;
  Tier-2 model intel below comes from HF MCP (`hf_fs`,
  `hub_repo_search`, `hub_repo_details`), which uses a different
  transport.
- **Leak-check is clean on main** — simulated the CI
  `git grep -nIEi "$patterns"` invocation locally against this
  branch, zero hits. 2026-09-22 FU-1 remains closed.
- **Gmail / Google-Drive MCP** — not called this run; PR is the sole
  delivery channel.

## Tier 1 — fixes applied in this commit

Every finding here is a **safe, mechanical, in-repo change** whose fix
is in this branch and whose regression suite passes
(`pytest tests/` → 52/52, `night_maintenance.py --dry-mode --quiet` → 0,
`mirror_drift.py --quiet` → 0).

The **novel** fix this cycle is **T1-a** (`DEEP_DIVE.md:649` says the
`_ARCH_ENHANCE_PROFILES` dict has 9 architectures; AST-parsing the
actual dict in both mirrors returns 11). The other eight entries are
carries from PR #192 so this branch stands alone as a strict superset
of what each individual carry touches — merging *this* PR (or any
later single digest) still lands all of them in one shot.

### T1-a `DEEP_DIVE.md:649` — `_ARCH_ENHANCE_PROFILES` is 2 architectures low (NOVEL)

The prompt-enhancement section says:

> **Per-architecture profile** (`_ARCH_ENHANCE_PROFILES` in
> prompt_enhance.py) — **9 architectures** each with their own
> `max_tokens`, target `length`, `style`, and guidance notes.

AST-parsing both mirrors
(`comfyui-spellcaster/spellcaster_core/prompt_enhance.py` and
`plugins/gimp/comfyui-connector/spellcaster_core/prompt_enhance.py`)
returns **11 top-level dict keys**: `flux1dev`, `flux2klein`, `chroma`,
`sdxl`, `sd15`, `illustrious`, `pony`, `wan`, `ltx`, `sd3`,
`sd3_turbo`. The 9-count has been in the DEEP_DIVE since at least the
2026-05 refactor, before `pony` and `sd3_turbo` were split out. No
prior digest or open PR touches this file at this line (verified with
`gh pr diff` across #183-#192 and the main-branch digest files).

Bumped `9 architectures` → `11 architectures`. The downstream
examples in the same bullet (SDXL / Flux 1 Dev / LTX Video / Klein /
Illustrious) are all still correctly represented in both mirrors, so
no other wording in the bullet needs touching.

Companion AST verification kept in `tests/test_model_prompt_profiles.py`
already asserts the arch keys live in the dict; no code-coverage gap
to patch.

### T1-b `README.md:46` — status banner is one month stale (carry)

`📣 Status — September 2026` → `📣 Status — October 2026`. Today is
2026-10-14. **Shared with #186–#192.** Content (News / Focus / Next)
left as-is: `git log --since="2026-10-01"` returns zero commits on
main, so there is no new news to summarize this month beyond what
the Sept banner already called out.

### T1-c/d `architectures.py` (both mirrors) — docstring date is one month stale (carry)

Both copies — `plugins/gimp/comfyui-connector/spellcaster_core/` and
`comfyui-spellcaster/spellcaster_core/` — carry
`SUPPORTED ARCHITECTURES (as of September 2026):`. Bumped to
`(as of October 2026):`, both files kept byte-identical
(`mirror_drift.py` exit 0). **Shared with #187–#192.**

### T1-e `installer/installer_gui.py:894` — Welcome dialog says "69 AI tools" (carry)

Four-month-stale user-facing count in the Windows installer's Welcome
dialog. Bumped to `75 AI tools —`. **Shared with #185–#192.**

### T1-f `installer/install.py:2075` — CLI LLM-upsell blurb says "the 69 tools" (carry)

Printed during the LLM-detection step in the CLI installer. Bumped to
`75 tools`. **Shared with #185–#192.**

### T1-g `plugins/gimp/comfyui-connector/_spellcaster_main.py:1174` — GIMP splash subtitle says "69 AI tools" (carry)

Rendered as the subtitle of the plugin's bundle-welcome panel the first
time GIMP picks the plugin up. Bumped to `75 AI tools, pre-configured
and ready.`. **Shared with #185–#192.**

### T1-h `tavern/wizard_speech.md:218` — wizard speech says "49 AI tools" (carry)

The Guild wizard-speech markdown advertises `**49 AI tools right
inside GIMP**` — an *even older* count than the "69" that landed
everywhere else. Bumped to `**75 AI tools right inside GIMP**`.
**Shared with #192.**

### T1-i `scaffold/spellcaster_wizard.py` — two "69" counts (carry)

Both `total_methods: 69` in the module-level docstring example (line 82)
and `"gimp": "GIMP 3 — 69 AI tools…"` in `PLUGIN_DESCRIPTIONS`
(line 182) bumped to `75`. **Shared with #185 and #192.**

### Verification

- `pytest tests/` — `52 passed in 9.31s` on this branch; same as
  baseline `ecf4249`. No regression (every T1 edit is a string
  literal; no code path changes).
- `python tests/mirror_drift.py --quiet` — exit `0`, both
  `architectures.py` copies byte-identical.
- `python tests/night_maintenance.py --dry-mode --quiet` — exit `0`.
- `python tools/upgrade_research.py --dry-run` — clean, `4 proposals
  from 5 backends`; this week's output committed under
  `_dev_docs/upgrade_research/2026-W42.{md,json}`.
- Simulated the leak-check workflow's own `git grep -nIEi "$patterns"`
  invocation against this branch → **zero hits** (git-grep exit 1).
- AST-parsed `scaffold/spellcaster_wizard.py`, `installer/install.py`,
  `installer/installer_gui.py`,
  `plugins/gimp/comfyui-connector/_spellcaster_main.py` and both
  `prompt_enhance.py` + `architectures.py` after edits — all parse
  clean.
- `grep -rnE "\b(49|69) (AI )?tools\b"` across the tree now returns
  **zero hits outside `_dev_docs/`** (digest files intentionally
  retain the counts they historically recorded).

## Tier 2 — model-integration candidates (need human VRAM/quality/risk call)

Sourced via HF MCP `hf_fs ls hf://models/trending` +
`hub_repo_details` on `Qwen/Qwen-Image-2.1-Turbo`,
`Comfy-Org/Qwen-Image-2.1`, `Lightricks/LTX-2.5`,
`Qwen/Qwen-Image-Edit-2511`, `google/embeddinggemma-2`,
`Cloudflare/clef-flash`, `openbmb/MiniCPM-V-4.7-35B-A3B`,
`baidu/Unlimited-OCR` (used ~4 MCP calls of the 25-call soft budget).
Deltas vs the 2026-10-12 digest (#192) are called out where the
signal has moved.

| Model | Date | Replaces / adds | VRAM (fp16) | Risk | Tier | Integration notes |
|-------|------|-----------------|-------------|------|------|-------------------|
| **Lightricks/LTX-2.5** | 2026-10-11 | Direct successor to current `ltx` arch (points at LTXV-2.3) | ~24 GB | medium | 2 | **7,738 likes / 3.9M DL** — up from 7,411 / 1.72M at #192 (two days ago). **2.3× download growth in 48h** is the single strongest signal this cycle. Still `gated=auto` on HF → fleet-only. Carry-over from 2026-09-22, now escalating. |
| **Qwen/Qwen-Image-2.1-Turbo** | 2026-10-12 | 4-step distill companion for the Qwen-Image-2.1 arch | ~10 GB fp8 (7.1B base) | low | 2 | **754 likes / 12.7K DL**, up from 604 / 6.8K at #192 (1.9× in 48h). Still climbing. 21+ demo Spaces live on HF. Would land in the SAME PR as the base `_reg("qwen_image", …)` with `turbo_config` wired to 4 steps / cfg=1.0 (Z-Image-Turbo-shape). GGUF companions: `unsloth/Qwen-Image-2.1-Turbo-GGUF`, `AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF` (NSFW-flagged → H6 handoff). |
| **Comfy-Org/Qwen-Image-2.1** | 2026-10-13 | Base arch (ComfyUI-native single-file) | ~16 GB fp8 (7.1B params) | low | 2 | **1,111 likes / 9.8M DL**, up from 1,077 / 9.1M at #192. Monotonic since 2026-09-22 (1.4M → 3.6M → 9.1M → 9.8M). Preferred surface — no diffusers shim. 24+ demo Spaces. |
| **Qwen/Qwen-Image-Edit-2511** | 2025-12-23 (last mod) | Default for `build_edit_by_instruction` + `build_qwen_edit` (opt-in in PR #48) | ~20 GB fp8 (20.4B) | medium | 2 | **2.0M DL / 1,473 likes** (stable from #192's 1,450). Live on `fal-ai` and `wavespeed` as inference providers. 100+ demo Spaces. Entry point remains **operationalize PR #48** — rebase against today's HEAD, promote `qwen_edit_version='2511'` to default. |
| **google/embeddinggemma-2** | 2026-10-06 | Local-prompt-enhancer embedding backend candidate | ~700 MB fp16 (744M params) | low | 2 | **2,213 likes / 135K DL** (up from 1,880 / 115K at #192). ONNX port `onnx-community/embeddinggemma-2-ONNX` is the deployment path for the morning-briefing / Guild chat flows. Multimodal (text+vision+audio+video embeddings). Tiny, A/B-safe. |
| **Cloudflare/clef-flash** | 2026-10-09 | VLM candidate for Wizard Guild / Portraitist chat flow | ~9.4 GB fp16 (9.4B params, Qwen3.5 base) | low | 2 | **817 likes / 26.6K DL** (up from 780 / 23K at #192). Decision-model + typed-output flavor (`structured-output`, `image-text-to-typed-output`). Not a core-image-path change; side-by-side vs `LiquidAI/d1-3B` (390 / 14.8K now) still the right A/B. |
| **baidu/Unlimited-OCR** | 2026-10-14 | New VLM / OCR candidate — currently no coverage | ~3.3 GB fp16 (3.3B params) | low | 2 | **NEW on trending — 4,633 likes / 8.8M DL in <2 weeks**, 77+ demo Spaces, apache-compatible MIT. Multilingual OCR + VLM. Potential slot: Portraitist's "describe this image" step and Spellcaster's layer-caption pass. Side-by-side worth running against `clef-flash` and `LiquidAI/d1-3B` on an existing portrait-describe prompt set. |
| **openbmb/MiniCPM-V-4.7-35B-A3B** | 2026-10-14 | New VLM candidate — MoE | ~24 GB fp8 (35B MoE, A3B active) | medium | 2 | **NEW — 538 likes / 4.2K DL**. Smaller sibling `openbmb/MiniCPM-V-4.7-1B` (323 / 2.5K DL) is the low-VRAM entry. Apache-2.0. Both image-text-to-text (VLM). Early signal; keep on radar one more cycle before fleet download. |
| **MiniMaxAI / MiniMax-H3 family** | ongoing | New video arch not in current `_reg` set | ~24 GB+ fp8 | high | 2 | Carry-over from #184/#186/#189/#190/#192 — no new signal this cycle. Still deserves its own `_reg("minimax_h3", …)` slot pending LAN VRAM/quality eval. |

### Tier-2 non-model finding

- **The LTX-2.5 download curve is now the strongest Tier-2 signal in
  the stack.** 2.3× DL in 48 hours (`1.72M → 3.9M`) with likes also
  moving (`+327`). This passes the threshold where the model has
  clearly won community adoption; the only reason it stays Tier-2 is
  the `gated=auto` constraint and the LAN-only download requirement.
  Flagged for operator priority above all other Tier-2 model work this
  cycle.

- **`abenzerps/Qwen-Image-2.1-Uncensored-Quantized`** reached **4,276
  likes / 2.3M DL** on trending today — that's the dominant NSFW
  Qwen-Image-2.1 branch now. Per H6 SFW-canon it does **not** belong
  in the public spellcaster repo; forwarded to the NSFW pipeline
  queue in Tier 3 below.

- **Illustrious-XL-v2.0 GGUF** stays worth watching, not acting on
  yet. No material movement vs #192. Same conclusion: hold one more
  cycle before promoting to a fleet download.

## Tier 3 — local action queue (fleet-only, sandbox can't reach)

Structured entries. A local Hermes / operator process consumes this
block mechanically rather than a human re-deriving commands from prose.
Every `command_hint` is best-effort — the operator adjusts for the
fleet's exact model directory layout.

```yaml
local_action_queue:
  - action: download_and_evaluate_model
    target_repo: Lightricks/LTX-2.5
    target_host: unknown
    reason: "7,738 likes / 3.9M DL (up from 7,411 / 1.72M at #192 two days ago — 2.3x DL growth in 48h is the strongest Tier-2 signal this cycle). Direct upgrade for _reg('ltx', ...). Gated=auto on HF — needs an HF login the cloud sandbox doesn't have. CARRY-OVER from 2026-09-22 — now escalating. OPERATOR PRIORITY #1 this cycle."
    command_hint: "huggingface-cli login  # once, then:\nhuggingface-cli download Lightricks/LTX-2.5 --local-dir D:\\LLM\\ComfyUI\\models\\ltx\\LTX-2.5"
    risk: medium

  - action: download_and_evaluate_model
    target_repo: Qwen/Qwen-Image-2.1-Turbo
    target_host: spark1
    reason: "4-step distill of Qwen-Image-2.1 (754 likes / 12.7K DL, up 1.9x from #192 two days ago). Land in the SAME PR as the base Qwen-Image-2.1 _reg entry with turbo_config wired to 4 steps / cfg=1.0 (Z-Image-Turbo-shape). Low-VRAM default for 12GB cards once the base arch ships."
    command_hint: "huggingface-cli download Qwen/Qwen-Image-2.1-Turbo --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1-Turbo --local-dir-use-symlinks False"
    risk: low

  - action: download_and_evaluate_model
    target_repo: Comfy-Org/Qwen-Image-2.1
    target_host: spark1
    reason: "Carry-over from 2026-09-22. 9.8M DL / 1,111 likes — monotonically climbing across four cycles (1.4M → 3.6M → 9.1M → 9.8M). ComfyUI single-file single-shot drop into checkpoints/. Evaluate quality against existing SDXL/Flux2Klein routes before wiring _reg('qwen_image', ...). Pair with Qwen-Image-2.1-Turbo above."
    command_hint: "huggingface-cli download Comfy-Org/Qwen-Image-2.1 --local-dir D:\\LLM\\ComfyUI\\models\\checkpoints\\Qwen-Image-2.1 --local-dir-use-symlinks False"
    risk: medium

  - action: download_and_evaluate_vlm
    target_repo: baidu/Unlimited-OCR
    target_host: spark2
    reason: "NEW on HF trending today — 4,633 likes / 8.8M DL in under two weeks, 77+ demo Spaces live. 3.3B params, Apache-compatible MIT, multilingual OCR + VLM. Potential slot: Portraitist's describe-this-image step and the Spellcaster layer-caption pass. Side-by-side vs clef-flash and LiquidAI/d1-3B on an existing portrait-describe prompt set would answer whether we switch the VLM step."
    command_hint: "huggingface-cli download baidu/Unlimited-OCR --local-dir D:\\LLM\\ComfyUI\\models\\vlm\\Unlimited-OCR"
    risk: low

  - action: download_and_evaluate_vlm
    target_repo: Cloudflare/clef-flash
    target_host: spark2
    reason: "VLM candidate for the Wizard Guild / Portraitist chat flow. 817 likes / 26.6K DL (up from 780 / 23K at #192). Qwen3.5-9B base, decision-model / typed-output flavor. Not a core-image-path change; safe to A/B against LiquidAI/d1-3B (390 / 14.8K) and baidu/Unlimited-OCR above."
    command_hint: "huggingface-cli download Cloudflare/clef-flash --local-dir D:\\LLM\\ComfyUI\\models\\vlm\\clef-flash\n# also:\nhuggingface-cli download LiquidAI/d1-3B --local-dir D:\\LLM\\ComfyUI\\models\\vlm\\d1-3B"
    risk: low

  - action: evaluate_embedding_backend
    target_repo: onnx-community/embeddinggemma-2-ONNX
    target_host: spark2
    reason: "ONNX port of embeddinggemma-2 — the deployment path for the morning-briefing / Guild chat embedding step called from tools/llm_morning_briefing.py. Base model climbed from 1,880 / 115K at #192 to 2,213 / 135K now. Multimodal embeddings (text+vision+audio+video) — tiny (~700MB), safe to A/B against existing embedding backend."
    command_hint: "huggingface-cli download onnx-community/embeddinggemma-2-ONNX --local-dir D:\\LLM\\embeddings\\embeddinggemma-2-ONNX"
    risk: low

  - action: hand_off_to_nsfw_pipeline
    target_repo: abenzerps/Qwen-Image-2.1-Uncensored-Quantized
    target_host: unknown
    reason: "NEW on HF trending — 4,276 likes / 2.3M DL, now the dominant NSFW Qwen-Image-2.1 branch. Per H6 SFW-canon this stays out of the public spellcaster repo. If the NSFW pipeline wants a Qwen-Image-2.1 route, this is the dominant community pick. Companion to AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF (442 likes / 258K DL now, up from 363 / 161K at #192)."
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
    reason: "PR #48 (open since 2026-05-19) carries qwen_edit_version='2511' + HunyuanVideo-1.5 + SAM 3.1 opt-ins against a 2026-05 baseline. Qwen-Image-Edit-2511 is now at 2.0M DL / 1,473 likes with live inference providers (fal-ai, wavespeed). Rebase against today's HEAD, promote qwen_edit_version='2511' to default, merge. CARRY-OVER from 2026-10-08."
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
  `329761b`. Verified clean on today's HEAD. Already struck in
  #191/#192; re-confirming here.
- **2026-09-22 FU-2 (`fetch_metadata.py` TLS-verify disable)** —
  closed by `2ebdf38` / `cd01ad2`. Already struck in #191/#192;
  re-confirming here.
- **No new corrections** this run.

## Follow-ups filed as future Tier-1 candidates

1. **Stacked-PR drain decision (unchanged, highest-priority)** —
   eleven open digest PRs (#166, #183, #184, #185, #186, #187, #188,
   #189, #190, #191, #192) now stacked on main. Every single one
   shares at least one Tier-1 fix with every other. Operator picks a
   merge/close policy or the queue keeps growing by one every 48h.
   The individual digests remain honest — nothing is misreported —
   but reviewer load on each one is now dominated by "did I already
   see this edit?" rather than content.

2. **`tools/upgrade_research.py` transport fallback (carry-over)** —
   HF + civitai backends still use stdlib `urllib`; sandbox proxy
   403s at CONNECT. Teaching the tool to prefer an HF MCP transport
   when available would let this routine run the real backend from
   the cloud. Still not shipped.

3. **PR #48 operationalization (carry-over)** — the SOTA-opt-ins PR
   has been open since 2026-05 with Qwen-Image-Edit-2511 as an opt-in.
   The underlying weight is now at 2.0M DL with live inference
   providers. Promoting the opt-in to default is the single
   highest-impact outcome of a near-term cycle. Filed as Tier-3
   action above.

4. **`44 expert presets` claim across four files** (carry-over from
   #185 / #192) — `README.md:311`, `DEPENDENCIES.md:29+33`,
   `scaffold/spellcaster_wizard.py:108`, `tavern/server.py:638` all
   advertise 44 expert presets for Inpaint & Fix, but AST-parsing the
   only `INPAINT_PRESETS` dict in `_spellcaster_main.py` returns 29.
   Could be a down-fix ("44 → 29") OR a restore-missing. Needs the
   operator's read; deferred to Tier-2 (same as #185 and #192).

5. **`DEEP_DIVE.md:52` mermaid `~34K Python lines`** (carry-over from
   #185 / #192) — `_spellcaster_main.py` alone is now ~37K lines, and
   top-level plugin `*.py` sums to ~40K. "~34K" is a soft claim worth
   bumping, but basis is ambiguous (which files does the count
   include?). Deferred to Tier-2.

6. **`DEEP_DIVE.md:922` "9-architecture `ArchConfig` registry"**
   (carry-over from 2026-09-22 Tier-2) — `_reg` AST count returns 27
   total / 21 fully-registered. The "9" probably reflects the
   "fully-wired image archs" subset (sd15, sdxl, illustrious, zit,
   flux1dev, chroma, flux2klein, flux_kontext, sd3) rather than every
   `_reg` entry, but the taxonomy is operator judgment. Deferred.

7. **`13 wizard character cards` claim** (NEW this cycle) —
   `tavern/wizard_speech.md:195` and `scaffold/spellcaster_wizard.py:185`
   both say "13 SillyTavern character cards" but
   `ls tavern/characters/*.json` returns **14**. Spellcaster.json may
   be the meta-wizard that the "13" excludes (it's the installer-
   wizard, not an RP wizard), but the current wording ("13 SillyTavern
   character cards that illustrate RP scenes") doesn't explicitly say
   so. Deferred to Tier-2 as a judgment call on inclusion rather than
   a safe mechanical bump.

---

_This digest was produced automatically by the `Ecosystem Research
Digest` scheduled task. Sources: HF MCP `hf_fs ls hf://models/trending`,
`hub_repo_details`; local `tools/upgrade_research.py --dry-run` (output
at `_dev_docs/upgrade_research/2026-W42.{json,md}`); AST scans of
`prompt_enhance.py`, `architectures.py`, `workflows.py`,
`builders_manifest.json`; `git grep -nIEi` scans of the whole tree
against `.githooks/leak-patterns` for the leak-check gate._
