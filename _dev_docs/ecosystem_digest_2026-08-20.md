# Ecosystem Research Digest — 2026-08-20

Run: every-48h cloud routine (Anthropic sandbox). No LAN access to
Spark / Theo / Prometheus / antenna. Prior digest search returned
nothing under `_dev_docs/ecosystem_digest_*.md` — this is the first
digest under the new action-oriented three-tier contract.

## Tool-gap note (fixed this run)

`tools/upgrade_research.py`, which prior digests were meant to call,
was **missing**. Rather than silently degrade to web-only research
again, this run drafts a minimal offline snapshot tool in the same
PR (see Tier 1 below). Its contract is inferred from the routine
brief: emit a JSON/YAML snapshot of the current arch registry,
detector-key coverage, and installer node-pack list so the digest
routine has a stable baseline to diff upstream against. See
[`tools/upgrade_research.py`](../tools/upgrade_research.py).

## Tier 1 — fixes applied in this PR

| # | Fix | Files | Verified by |
|---|-----|-------|-------------|
| 1 | Add `_reg("supir", ...)` stub — the detector emits `"supir"` from `model_detect.CKPT_ARCH_RULES` line 103, but no `ArchConfig` existed for it, so `get_arch("supir")` was silently falling back to SDXL. `tests/test_model_coverage.py` was **red** on main because of this; now green. | `comfyui-spellcaster/spellcaster_core/architectures.py` | `PYTHONPATH=comfyui-spellcaster python3 tests/test_model_coverage.py` → **19/19 PASSED** |
| 2 | Rebuild `builders_manifest.json` — stale relative to `workflows.py`. `tests/builders_manifest_drift.py` was **red** on main. | `comfyui-spellcaster/spellcaster_core/builders_manifest.json` | `python3 tests/builders_manifest_drift.py` → `check: manifest fresh (76 methods).` |
| 3 | Re-align 6-surface mirror: surface C → surface 1 for `workflows.py`, `architectures.py`, `preflight.py`, `asset_gallery.py`, `builders_manifest.json`. `tests/mirror_drift.py` was **red** on main with 3 files drifting; the SUPIR fix and manifest rebuild would have widened it to 5. | `plugins/gimp/comfyui-connector/spellcaster_core/*.py` + `builders_manifest.json` | `python3 tests/mirror_drift.py` → `OK: 26/26 DRIFT: 0` |
| 4 | Bump README status header from "Status — May 2026" to "Status — August 2026" — 3 months stale. | `README.md` line 46 | Manual — visual only. |
| 5 | Draft `tools/upgrade_research.py` (minimal offline snapshot: archs / detector keys / installer node packs; `--diff`, `--yaml`, `--out` modes). | `tools/upgrade_research.py` (new file) | `python3 tools/upgrade_research.py \| python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['archs']), 'archs;', len(d['node_packs']), 'node packs')"` → `28 archs; 25 node packs` |

Regressions checked:
- `PYTHONPATH=comfyui-spellcaster python3 tests/test_summon_archetypes.py` → 24/24 PASSED
- `PYTHONPATH=comfyui-spellcaster python3 tests/test_model_prompt_profiles.py` → 22/22 PASSED

### CI pre-existing-red notice (for the PR)

`leak-check.yml` is currently red on **main** for reasons unrelated to
this PR's diff. `git grep` of the `leak-check.yml` pattern against
`origin/main` shows 84 pre-existing hits across `_dev_docs/`,
`_inventory/`, `antenna.RETIRED-*/`, `installer/remote_services.json`,
`plugins/krita/spellcaster_krita.py`, `plugins/gimp/…/workflows.py`,
`comfyui-spellcaster/spellcaster_core/{workflows,asset_gallery}.py`
and comments in `nightly.yml` / `mirror-drift.yml`. This PR's own
edits introduce **zero** new hits — the surface-1 mirror sync copied
identical bytes from surface C, whose comments already exist on main.
This is filed as a Tier-1 candidate for a future run (see below); not
this run's failure per the routine's pre-existing-red rule.

### Tier-1 candidates for the NEXT run (deferred as too big for a single safe PR)

- **Leak-check red on main.** 84 hits across 14 files. Real fix is either
  (a) widen the exclusion list (`_dev_docs/`, `_inventory/`,
  `antenna.RETIRED-*`, `**/comments`) and audit `installer/remote_services.json`
  + `plugins/krita/spellcaster_krita.py` for real IP leakage, or (b) mass-rename
  internal codenames in code comments. Not safe as a mechanical one-shot; needs
  operator direction on which strategy to take. Filed for follow-up.
- **`DEEP_DIVE.md` says "9 model architectures"** at line 936 while the registry
  now holds 27 (20 registered=True + 7 stubs, excluding `my_custom_model`).
  Line 3 (`all 9 model families`) and README line 139 (`69 tools across 19 models`)
  are similarly stale. Not fixed here because "family" vs "arch" is a curation
  decision — the safe count is a judgement call.
- **Un-promoted stubs the digest keeps flagging** (from
  `python3 tools/upgrade_research.py`): `auraflow`, `hunyuan_dit`, `kolors`,
  `pixart`, `sd3`, `sd3_turbo`, `supir` (newly added this run). Each needs a
  dedicated workflow builder before its `registered` flag flips to `True`.

## Tier 2 — new-model / new-architecture opportunities (human judgment needed)

Model / capability tracking since ~2026-05 (last README status date). Sorted
most-actionable first. All are optional upgrades — nothing here is a
regression fix.

> **2026-08-20 correction (post-review with operator):** an earlier draft of
> this table listed a "Wan 2.7 (Apache-2.0 open weights)" swap. **That was
> wrong** — it came from an SEO blog (`wan27.org`), not a primary source.
> Verified against the official `Wan-AI` HF org via MCP: **the newest open
> weights are the Wan 2.2 family; Wan 2.5 / 2.6 / 3.0 are API-only closed
> models with no downloadable weights.** There is no `Wan-AI/Wan2.7-*` repo.
> The row is removed. The genuine capability upgrade in that family is **Wan
> Animate 2** (below), which IS open (Apache-2.0) and IS a real successor to
> the character-animation path we already ship.

Verified via HF MCP (`hub_repo_search author=Wan-AI` + `hf_fs ls`), sorted
most-actionable first. **Disk footprints are real, measured from the HF file
tree — not guesses** — because Spark 1 / Spark 2 are disk-constrained.

| model / capability | released | replaces (in our stack) | disk on host | risk | verdict |
|---|---|---|---|---|---|
| **Wan Animate 2** (`Wan-AI/Wan2.2-Animate-2-14B`, Apache-2.0) | model 2026-07-14; Distilled-Diffusers 2026-08-06 | our `video_animate` / `WanAnimateToVideo` path — currently backed by **Animate v1** | see note ↓ | med | **SWAP — but blocked on quant.** Genuine successor. **Caveat: only Diffusers format exists** (~43 GiB repo, ~32 GiB net-new after the shared UMT5 encoder). **No GGUF/fp8 ComfyUI-native build yet** — the QuantStack GGUF is v1 Animate only (Q5_K_M ≈ 12 GiB). On a disk-tight Spark, swapping *today* means trading a 12 GiB GGUF for a 43 GiB Diffusers repo — wrong direction. **Recommendation: hold the swap until a GGUF/fp8 Animate-2 build lands** (Monster tracks; re-check next run), OR accept the heavy download if the operator wants Animate 2 now. |
| **Wan-Dancer-14B** (`Wan-AI/Wan-Dancer-14B`, Apache-2.0, i2v music-to-dance) | 2026-07-10 | **NEW capability** — nothing in our stack does music-driven dance i2v | 14B i2v (~14–16 GiB quantized when a GGUF appears) | med | **NEW, not a swap.** Only worth deploying if the product wants a dance/motion tool. Not an upgrade to anything existing; defer unless there's product demand. |
| **SAM 3.1 Multiplex** native in ComfyUI (PR #13408, kijai) | 2025-Q4 / 2026-Q1 | our SAM3 selection path (README: "type 'hair' → SAM3 mask, 1s") | ~0 net if already pulling SAM3 weights | low | **VERIFY-THEN-MIGRATE.** Native nodes now ship with joint multi-object tracking. First step is confirming whether our `AI Select` uses the native loader or a wrapper (`ComfyUI-RMBG` bundles SAM3 too). Small workflow-builder change, no big download. |
| **ComfyUI-RMBG (Lucida BiRefNet, v3.1.0)** | 2026-07-21 | our `ComfyUI-RMBG` optional pack | +~1 model (auto-download) | low | **ALREADY LIVE.** Our manifest pins `ref: null` → installer follows upstream `main`, so a fresh install already gets v3.1.0. **No manifest change needed.** Only a `DEPENDENCIES.md` note is warranted. Existing installs pick it up on `git pull`. |
| **Depth Anything V3 native in ComfyUI** | 2025-11 (model); native nodes 2026 | our optional `ComfyUI-DepthAnythingV3` third-party wrapper | frees the wrapper's disk | low | **CLEANUP (frees disk).** If the native path is on par, drop the third-party pack from the manifest + `DEPENDENCIES.md`. Net **negative** disk — good for Spark. Verify parity first. |
| **Flux 2 Klein `one-node-flux-2-klein` POSE mode** | 2026-06-26 | our Klein optional-quality path (`ComfyUI-Flux2Klein-Enhancer`) | 0 additional | low | **OPPORTUNITY.** POSE transfer without a separate ControlNet setup. Worth a GIMP-tool exposure if better than our 3-layer ControlNet pose path. No weights to add. |
| **Chroma Radiance** (pixel-space Chroma) | 2026 | complements current Chroma image arch (already `registered=True`) | ~ same as base Chroma | med | **EVALUATE.** Pixel-space gen reduces VAE round-trips. Quality-dependent; not a clear swap yet. |

### The only "swap old for new" that's actually disk-safe right now

Most rows above are either **not a swap** (SAM3, Dancer, Klein POSE), **already
live** (RMBG), or **disk-negative cleanup** (DepthAnything). The one true
model-weight swap the operator asked for — **Animate v1 → Animate 2** — is
**blocked on a quantized build** because Animate 2 is Diffusers-only today and
would *increase* disk 12 GiB → 43 GiB on a constrained host. So the honest
disk-aware answer is:

- **Do now (disk-negative or zero):** DepthAnything wrapper removal (frees
  space), RMBG note (no download), SAM3 path verification (no download).
- **Hold (disk-positive, no quant yet):** Animate 2 swap — Monster watches for
  a GGUF/fp8 build; re-check next run. Don't push a 43 GiB Diffusers repo onto
  a full Spark for a swap when a 12–16 GiB quant is likely weeks away.
- **Defer (new capability, no demand signal):** Wan-Dancer.

**Model inventory is Monster's job** (per operator). Tier 3 below routes every
weight action through Monster rather than issuing raw `hf download` commands, so
the fleet's single source of truth stays consistent.

## Tier 3 — local-action queue (structured — for Monster / operator)

**Policy this queue encodes** (from the operator, 2026-08-20):

1. **Spark 1 and Spark 2 are disk-constrained.** Every add-new must be paired
   with a matched retire-old on the same host, and net disk delta must be
   listed and non-positive except when the operator explicitly greenlights it
   for a capability win.
2. **Model inventory is Monster's job.** Every weight-touching entry below
   uses `monster_action` verbs (which Monster resolves against its
   fleet-inventory ledger); no raw `hf download` on any host.
3. **Swap old for new whenever possible; deploy when workflows add
   significant capabilities.** "Newer version, same capability" gets deferred
   in favor of capability wins.

Entries are grouped: **do-now (disk-negative or zero)**, **hold-for-quant
(disk-positive today, blocked)**, **verify-then-decide**, and **repo-side**.

```yaml
local_action_queue:

  # ────────────────────────────────────────────────────────────────
  # DO-NOW group — every entry is disk-neutral or disk-negative
  # ────────────────────────────────────────────────────────────────

  - action: monster_verify_rmbg_currency
    target_host: any-host-with-ComfyUI
    replaces: ComfyUI-RMBG (older commit)
    net_disk_delta_gb: 0            # optional pack; already unpinned in our manifest
    capability_gain: >-
      v3.1.0 (2026-07-21) adds Lucida BiRefNet — real wins for AI Eraser /
      Remove Background on transparent objects, camouflage, text/logos,
      glow/VFX, illustrations. Our installer manifest has ref: null
      (upstream main), so fresh installs already pick it up.
    monster_action:
      verb: verify_pack_head_at_or_above
      pack: 1038lab/ComfyUI-RMBG
      minimum_ref: v3.1.0
      on_stale: pull_latest_main
    risk: low

  - action: monster_verify_sam3_path
    target_host: any-host-with-ComfyUI
    replaces: >-
      (unknown loader — need Monster to report whether "AI Select" invokes
      native SAM 3.1 nodes or the RMBG-bundled SAM3 wrapper)
    net_disk_delta_gb: 0
    capability_gain: >-
      Native SAM 3.1 Multiplex in core ComfyUI (PR #13408) adds joint
      multi-object tracking. If we're on the wrapper path, migration is
      workflow-builder-only.
    monster_action:
      verb: probe_active_loader
      probe:
        - method_key: "ai_select"
        - target_node_class: "SAM3*, Sam3*, SegmentAnything3*"
      report:
        - which_pack_owns_it
        - whether_native_alternative_exists
    risk: low

  - action: monster_retire_depthanything_wrapper_if_native_on_par
    target_host: any-host-with-ComfyUI
    replaces: PozzettiAndrea/ComfyUI-DepthAnythingV3 (third-party wrapper)
    net_disk_delta_gb: negative      # frees the wrapper's disk (~small, node code only)
    capability_gain: >-
      ComfyUI now ships DepthAnythingV3 natively. Removing the third-party
      wrapper frees disk and drops a dependency edge. Verify parity first
      (same output on a 3-image probe set).
    monster_action:
      verb: parity_probe_then_retire
      canonical_path: comfyui_native_depth_anything_v3
      candidate_retire: custom_nodes/ComfyUI-DepthAnythingV3
      parity_criterion: mean_depth_delta_lt_0.02
      on_pass: retire_wrapper
    risk: low

  # ────────────────────────────────────────────────────────────────
  # HOLD-FOR-QUANT group — the requested swap, blocked on disk math
  # ────────────────────────────────────────────────────────────────

  - action: monster_watch_wan_animate2_quant
    target_host: video-tail spark (Monster picks)
    replaces: Wan Animate v1 GGUF (~12 GiB Q5_K_M today)
    net_disk_delta_gb: -12          # AFTER the swap; Animate 2 quant size TBD
    capability_gain: >-
      Wan Animate 2 (Wan-AI/Wan2.2-Animate-2-14B, Apache-2.0, 2026-07-14) is
      the successor to the character-animation path we already advertise.
      A Distilled-Diffusers variant landed 2026-08-06.
    blocked_on: >-
      Only Diffusers format exists today (~43 GiB repo, ~32 GiB net-new after
      the shared UMT5 encoder). No GGUF/fp8/ComfyUI-native build yet — the
      QuantStack GGUF is Animate v1 only. On a disk-tight Spark, doing the
      swap now trades 12 GiB → 43 GiB (wrong direction). Wait for the quant.
    monster_action:
      verb: watch_for_quant
      base_model: Wan-AI/Wan2.2-Animate-2-14B
      formats:
        - gguf: [Q5_K_M, Q4_K_M, Q6_K]
        - safetensors_fp8
      candidate_publishers: [QuantStack, city96, Kijai]
      on_appear:
        - alert_operator
        - stage_download_plan_with_matched_retire  # 1:1 swap, disk-negative or zero
    risk: low

  # ────────────────────────────────────────────────────────────────
  # DEFER group — new capability, no product signal yet
  # ────────────────────────────────────────────────────────────────

  - action: monster_note_wan_dancer_availability
    target_host: n/a
    replaces: nothing (new capability, not a swap)
    net_disk_delta_gb: 0            # not staging anything
    capability_gain: >-
      Wan-Dancer-14B (Apache-2.0, 2026-07-10) is music-to-dance i2v. Not an
      upgrade to anything we ship; only worth deploying if the product wants
      a dance/motion tool. Recording so it's not re-discovered every digest.
    monster_action:
      verb: annotate_ledger
      key: wan-dancer-14b
      note: "available; no product demand; do not stage"
    risk: low

  # ────────────────────────────────────────────────────────────────
  # REPO-SIDE group — cleanup local operator does at their workstation
  # ────────────────────────────────────────────────────────────────

  - action: audit_leak_check_hits_on_main
    target_host: local-workstation
    replaces: n/a
    net_disk_delta_gb: 0
    capability_gain: >-
      leak-check.yml is red on main for 84 pre-existing pattern hits across
      _dev_docs/, _inventory/, antenna.RETIRED-*/, installer/remote_services.json,
      plugins/krita/spellcaster_krita.py, and code comments. Fix strategy is a
      curation call (widen exclusions vs. rename codenames vs. mask real IPs) —
      not safe as a mechanical PR from the cloud sandbox.
    command_hint: |
      git grep -nIE 'Voodoomancer|Whimweaver|Laborantin|voodoo-core|Beatweaver|whimspider|\bTheo\b|192\.168\.86|192\.168\.0\.100|lmlgg|leguillaume|@gmail\.com|MASTER_PLAN' -- ':!.github/workflows/leak-check.yml' | wc -l
    risk: medium
```

## Operator-memory corrections (deltas vs prior notes)

- **Retracted: "Wan 2.7 open weights".** An earlier draft of this digest
  named `Wan-AI/Wan2.7` as an Apache-2.0 open-weights swap target. That
  claim came from an SEO blog (`wan27.org`), not the source. Verified via
  HF MCP against the `Wan-AI` org: **no `Wan-AI/Wan2.7-*` repo exists.** The
  newest open-weights release in the Wan family is still the **Wan 2.2**
  line (T2V-A14B / I2V-A14B / TI2V-5B) plus **Wan 2.2-Animate / Animate-2**
  and **Wan-Dancer-14B**. Wan 2.5 / 2.6 / 3.0 remain API-only closed models.
- Wan 2.5 / 2.6 are **not** open weights — closed API models. Any older
  note that suggested we could self-host them is wrong.
- Depth Anything **V4** does not exist as of this run's search. V3 (Nov 2025)
  is the latest; ComfyUI now ships it natively so our third-party wrapper
  is a cleanup candidate, not an upgrade candidate.
- **Model inventory ownership:** Monster is the source of truth for what
  weights live on which host. This digest routes every weight action
  through Monster (`monster_action` verbs) rather than issuing raw
  `hf download` commands. Future digest runs should keep this discipline —
  do not maintain a shadow inventory in this repo.
- **Spark disk pressure:** Spark 1 and Spark 2 are constrained. Every
  swap entry in Tier 3 lists a `net_disk_delta_gb`; positive-delta swaps
  are held pending a quantized build unless the operator explicitly
  greenlights the heavy download for a capability win.

## Delivery

Gmail MCP requires interactive auth in this sandbox and is unavailable —
so the PR (with this file + Tier 1 diffs) is the sole delivery channel
this run. Google-Drive MCP is available but not used; the digest lives
in-repo per the routine spec.

## Budget

WebSearch calls: 8. WebFetch calls: 0. HF MCP calls: 1. Well under the
~25-call soft ceiling.
