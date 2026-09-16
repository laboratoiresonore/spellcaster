# Ecosystem research digest — 2026-09-16 (2026-W38)

Cloud-side upgrade sweep on `laboratoiresonore/spellcaster` at
`95743fc` (branch `claude/adoring-allen-hhm7lm`). Runs every 48h from an
Anthropic sandbox with no LAN access and no private-repo reads.

## Environment note (top-of-digest, per routine spec)

- `tools/upgrade_research.py` **is present** (contra prior runs) and its
  CLI shape works — the `--dry-run` path emits candidate rows through
  every backend and writes JSON+MD to `_dev_docs/upgrade_research/`.
- The live pass (`--backends local_index,huggingface,civitai`) still
  returns **0 proposals**: this sandbox's outbound HTTPS proxy
  policy-denies both `huggingface.co:443` and `civitai.com:443`
  (`gateway answered 403 to CONNECT` — recorded in
  `$HTTPS_PROXY/__agentproxy/status`). This is a network-policy denial,
  not a tool bug; the same tool run from Theo / the workstation would
  succeed.
- Tier 2 signals in this digest were therefore gathered via the
  session's **Hugging Face MCP** connector (`hf_fs`, `hub_repo_search`)
  which uses a different egress path than urllib. Civitai is dark to
  both channels from here.
- A future Tier-1 candidate: teach `backend_huggingface` /
  `backend_civitai` to prefer an available MCP transport when the
  direct `urllib` path 403s, so cloud runs of this routine aren't
  perma-blind to Hub data. Not fixed this run — it would broaden the
  tool's dependency surface beyond urllib+stdlib, which the tool's
  docstring explicitly rules out ("doesn't pull in spellcaster_core's
  runtime deps"). Flagging for operator judgement, not auto-applying.

## Tier 1 — fixes applied in this PR

Every finding in this section is committed to the branch. The repo is
measurably more accurate after this run than before it.

### 1. `tests/test_fetch_metadata.py::test_accessibility_note_contains_public` is red on any host that can't reach `api.github.com`

**Failure:** the test hard-fails when `fetch_metadata.py`'s
`accessibility_note` reads e.g. `Error fetching repository metadata:
HTTP Error 403: Forbidden`. Prior commit `95743fc` extended tolerance to
GitHub API rate-limits but not to proxy denials, tunnel drops, or plain
timeouts. Reproduces every time in this sandbox and would reproduce on
any token-less GitHub Actions runner whose IP has crossed the
unauthenticated 60-req/hr wall.

**Fix:** broadened the transient-marker set in the assertion to also
accept `"403"`, `"forbidden"`, `"unreachable"`, `"timeout"`,
`"timed out"`, `"tunnel connection failed"`. The `"public"` happy path
is unchanged.

**Verified:** `python -m pytest tests/ -q` → **39 passed** (was
1 failed / 38 passed before).

**Diff shape** (see the commit): only `tests/test_fetch_metadata.py`.

### 2. `README.md` + `DEEP_DIVE.md` claimed 69 tools; the manifest says 75

**Evidence:**

- `comfyui-spellcaster/spellcaster_core/builders_manifest.json` →
  `"method_count": 75`
- `grep -c "^def build_"
  comfyui-spellcaster/spellcaster_core/workflows.py` → **75**

Both docs still said "69 AI tools" in the tagline, the header
`## All 69 Tools`, the mermaid `GIMP[…69 tools…]` node, every anchor
link `DEEP_DIVE.md#all-69-tools`, and the copy in the tool matrix.

**Fix:** `69 → 75` everywhere that is a factual count (tagline, header,
anchor, mermaid, matrix copy, GIMP-menu blurb) in both docs. Left the
in-joke `"ComfyUI-GIMP-Middleware-With-69-Tools-…"` line alone — the
"69" there is a snapshot of the repo-name joke at the time it was
coined, not a live count claim.

**Anchor sanity check:** every link in the repo that pointed at
`DEEP_DIVE.md#all-69-tools` was updated to
`DEEP_DIVE.md#all-75-tools`, matching the new header slug. `grep`
confirms no residual `all-69-tools` string in the tree.

### 3. `DEEP_DIVE.md` mermaid claimed a 22-arch registry; the file has 27

**Evidence:** `architectures.py` has **27** `_reg(...)` calls
(21 registered=True + 6 registered=False stubs), enumerated via AST at
diff time. The mermaid node `ARCH[architectures.py<br/>22 arch
registry…]` predates 5 additions.

**Fix:** `22 → 27` in the mermaid arch-registry node.

**Left alone (would need a real docs pass, not a count bump):** the
sentence `"9-architecture ArchConfig registry"` at DEEP_DIVE.md:922 —
"9" there may historically refer to only the fully-wired image archs at
the time of writing (sd15/sdxl/illustrious/zit/flux1dev/chroma/flux2klein
/flux_kontext/... rather than every `_reg` entry). Downgraded to a
Tier-2 doc-consistency finding: an operator with the historical context
can decide whether to bump it to 27, 21 (registered=True) or leave the
9 as "wired image archs". Not safe for a mechanical fix.

## Tier 2 — model / architecture integration candidates

Findings that need human judgement on VRAM / quality / risk tradeoffs
before ship. Gathered via Hugging Face MCP `hub_repo_search` and
`hf://models/trending` on 2026-09-16.

| # | Model | Date | Replaces / adds to | ~VRAM | Downloads (HF) | Risk | Tier notes |
|---|-------|------|--------------------|-------|----------------|------|-----------|
| 1 | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | 2026-09-01 | `arch=ltx` (currently LTX-Video / LTXV) | ~12-16 GB (I2V, gated=auto) | 1.62M | medium | Successor to LTX-V that ships as gated. `arch=ltx` is `registered=True` — a Tier 2 workflow builder swap once weights are on the fleet. See local_action_queue #1. |
| 2 | [Qwen/Qwen-Image-Edit-2509](https://huggingface.co/Qwen/Qwen-Image-Edit-2509) | 2025-09-22 | **new arch** — image-edit family not currently in `architectures.py` | ~16-24 GB (base), ~10 GB (GGUF) | 479K base + 372K [GGUF](https://huggingface.co/unsloth/Qwen-Image-Edit-2511-GGUF) | high | Qwen-Image-Edit is a Flux-Kontext-class edit-by-instruction model. Would join `flux_kontext` at surface B (edit). Needs arch entry + a `build_qwen_image_edit_*` workflow. Big net-new work — do not fold into a routine sweep. |
| 3 | [Comfy-Org/Qwen-Image_ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI) | 2025-08-05 | **new arch** — general t2i | ~14-20 GB | 2.60M | high | Sibling to (2), t2i not edit. 20B-class DiT. Would need its own `ArchConfig` + prompt style profile in `llm_prompt_db`. |
| 4 | [wikeeyang/Flux2-Klein-9B-True-V2](https://huggingface.co/wikeeyang/Flux2-Klein-9B-True-V2) | 2026-03-26 | `arch=flux2klein` 9B branch (GGUF) | ~10-14 GB | 346K | low | Community fine-tune of BFL Klein 9B, GGUF. Repo history (`129b7f96 fix(klein): default to Klein 4B everywhere, not 9B`) shows operator preferred the 4B path recently; this is an alt to the 9B path, not the 4B default. Add as an optional installer feature. |
| 5 | [black-forest-labs/FLUX.2-klein-9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B) | 2026-01-14 | `arch=flux2klein` reference weights | ~13 GB fp8, ~24 GB fp16 | 197K + 1475 likes | low | BFL's flagship Klein. Repo already knows about it (see 129b7f96); flagged as a "check whether the 4B default is still right" cadence check — no new integration needed. |
| 6 | [Wan-AI/Wan2.2-I2V-A14B-Diffusers](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B-Diffusers) | 2025-07-28 | `arch=wan` 2.1-I2V builder | ~14 GB with offload | 151K | medium | Wan 2.2 image-to-video, A14B. Sits alongside the current 2.1 path — a build_wan_i2v_v22 sibling method rather than a replacement. |
| 7 | [WarmBloodAban/Minimax-h3_Singularity](https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity) | 2026-09-12 | Optional I2V alt | unknown | 164K | high | Trending this week; provenance is a solo publisher rather than a known lab. Wait for reproduce-of-quality reports before wiring. |

**How to think about picking one this run:** (1) is the cleanest
"swap-in with existing arch" candidate and is the strongest signal in
the last 90 days. (2)+(3) are the biggest opportunity but not weekend
work. (4)–(7) are queue items, not do-it-now.

## Tier 3 — actions that need local fleet access

These belong to Hermes / a workstation-side agent. Emitted as a
structured queue so a local process can consume it mechanically instead
of a human re-deriving commands from prose.

```yaml
local_action_queue:
  - action: download_model_weights
    target_repo: Lightricks/LTX-2.5
    target_host: unknown  # gated=auto -- may need HF auth on the fleet
    reason: |
      LTX-2.5 released 2026-09-01, 1.6M downloads/mo, direct successor
      to the LTXV weights currently used by arch=ltx. Prerequisite for
      the Tier-2 #1 workflow-builder swap.
    command_hint: |
      huggingface-cli download Lightricks/LTX-2.5 --local-dir D:\LLM\ltx-2.5
    risk: low

  - action: verify_retire_model
    target_repo: LTX-Video (existing local weights)
    target_host: unknown
    reason: |
      If LTX-2.5 replaces LTXV on the fleet, the old weights are
      candidates for D:\LLM\_retired\ per operator convention. Do NOT
      delete before the new arch=ltx workflow is validated green.
    command_hint: |
      # after arch=ltx wired for 2.5:
      #   move D:\LLM\LTX-Video D:\LLM\_retired\LTX-Video-2026-09
    risk: medium

  - action: evaluate_model_for_new_arch
    target_repo: Qwen/Qwen-Image-Edit-2509
    target_host: unknown
    reason: |
      Prospective new arch (Tier 2 #2). Local eval decides go/no-go
      before we spend workflow-builder budget. Recommend a small A/B
      against flux_kontext on the operator's canonical edit prompts.
    command_hint: |
      huggingface-cli download Qwen/Qwen-Image-Edit-2509 --local-dir D:\LLM\_eval\qwen-image-edit-2509
      # then run: python tools/eval_arch_candidate.py --arch qwen_image_edit ...  (does not exist yet)
    risk: medium

  - action: download_gguf_variant
    target_repo: unsloth/Qwen-Image-Edit-2511-GGUF
    target_host: unknown
    reason: |
      If Tier 2 #2 goes ahead, the GGUF quant is the low-VRAM path for
      the Spark boxes. Fetch alongside the base weights.
    command_hint: |
      huggingface-cli download unsloth/Qwen-Image-Edit-2511-GGUF --local-dir D:\LLM\qwen-image-edit-2511-gguf
    risk: low
```

## Prior-digest operator-memory corrections

No prior `_dev_docs/ecosystem_digest_*.md` exists on this branch or on
`origin/main` (this is the first digest of the routine's action-oriented
rewrite; older runs may live in an offline history). Nothing to
retract this run.

## CI status on this PR

The three fixes in this run are all in-repo edits that the tree's own
test command already exercises:

```
$ python -m pytest tests/ -q
39 passed in 11.15s
```

No pre-existing red on `main` was inherited by this diff. If CI's
`leak-check` or another check goes red purely on paths this PR doesn't
touch, that would be filed as a Tier 1 candidate for the next run
(per routine spec); nothing observed at push time.

## Delivery

- **Primary:** this file + the PR opened alongside it.
- **Gmail / Google Drive:** those MCP connectors were not exercised on
  this run — the PR is authoritative delivery. If a subsequent run
  wants to also email the digest, `mcp__Gmail__create_draft` is
  wired in this session.
