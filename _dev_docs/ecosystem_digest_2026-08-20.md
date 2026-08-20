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

| model / capability | released | replaces (in our stack) | vram (est.) | risk | tier | notes |
|---|---|---|---|---|---|---|
| **Wan 2.7** (Apache-2.0 open weights) | March 2026 | Wan 2.2 (our current registered video arch) | ~24 GB for full; quantized variants smaller | med | integration | Open-weights successor. Wan 2.5 (Sep 2025) and Wan 2.6 (Reference-to-Video) are API-only closed weights and NOT deployable locally — don't chase those. Wan 2.7 keeps our local-only stance. Would need new `_reg("wan27", ...)` entry + `build_wan27_video` builder + detector rule. Wan 2.2 stays functional; add 2.7 as parallel arch. |
| **Wan Animate 2** in ComfyUI | 2026 (partner nodes shipped) | our `WanAnimateToVideo` `WAN_EXTRA_METHODS` `video_animate` path | ~ same as Wan 2.2 base | low | integration | Successor to the character-animation path we already advertise. Check whether `ComfyUI-WanVideoWrapper` (already an optional dep) has picked up Animate 2 nodes, or whether it's core-ComfyUI native. |
| **SAM 3.1 Multiplex** natively in ComfyUI (PR #13408, kijai) | 2025-Q4 / 2026-Q1 | our SAM3 selection path (README brags "type 'hair' → SAM3 mask, 1s") | modest | low | check-only | ComfyUI now ships SAM 3.1 native nodes with joint multi-object tracking. If our GIMP `AI Select` currently invokes a wrapper (`ComfyUI-RMBG` bundles SAM3 too) rather than the native path, migrating is a small workflow-builder change. **First step is verifying which loader we actually use today.** |
| **ComfyUI-RMBG v3.1.0** (Lucida BiRefNet variant) | 2026-07-21 | our `ComfyUI-RMBG` optional pack (already listed in `DEPENDENCIES.md`) | ~3 GB | low | version-bump | Lucida target: transparent objects, camouflage, text/logos, glow/VFX, illustrations — real edge-case wins for the AI Eraser + Remove Background tools. Just bump the pinned commit in `installer/manifest.json`; no arch or builder change. |
| **Flux 2 Klein `one-node-flux-2-klein` POSE mode** | 2026-06-26 | our existing Klein optional-quality path via `ComfyUI-Flux2Klein-Enhancer` | 0 additional | low | opportunity | POSE transfer between images without a separate ControlNet setup. If ergonomically better than our current 3-layer ControlNet path for pose, worth a GIMP-tool exposure. |
| **Depth Anything V3 now native in ComfyUI** | 2025-11 (model); native ComfyUI nodes shipped 2026 | our optional `ComfyUI-DepthAnythingV3` third-party wrapper (`PozzettiAndrea/…`) | modest | low | cleanup | The third-party wrapper we ship as an optional pack may now be redundant. If native path is on par, remove the optional pack from `DEPENDENCIES.md` and the installer manifest. |
| **Chroma Radiance** (pixel-space Chroma variant) | 2026 | complements current Chroma image arch (registered=True in our registry) | ~ same as base Chroma | med | evaluate | Generates in pixel space, reducing repeated VAE encode/decode. If quality holds, could become the preferred Chroma dispatch path for high-detail work. |

### Integration-note details (for the two most concrete)

**Wan 2.7 addition — sketch**

- `model_detect.UNET_ARCH_RULES`: add `("wan27", "wan27")` above the
  `("wan22", "wan")` line so the more-specific name wins.
- `architectures.py`: add `_reg("wan27", …, registered=True, supported_methods=VIDEO_METHODS + WAN_EXTRA_METHODS, scene_group="video")` cloning from the `wan` block.
- `workflows.py`: `build_wan27_video` — if Wan 2.7 keeps the WanAnimateToVideo shaper interface, it's a param-tweak on `build_wan_video`; if it introduces new nodes, mirror the pattern in `build_wan_video`.
- Local-fleet action: pull `Wan-AI/Wan2.7-*` weights (verify the exact repo id from the Apache-2.0 announcement) onto whichever Spark hosts the video tail. Filed in Tier 3 below.

**ComfyUI-RMBG v3.1.0 bump — sketch**

- `installer/manifest.json`: bump the pinned commit for `ComfyUI-RMBG` to a
  commit ≥ v3.1.0 tag (2026-07-21).
- Add note in `DEPENDENCIES.md` optional-pack row noting "Lucida added
  2026-07 — better transparent object masks".
- No arch or builder change; the extra model auto-downloads first use.

## Tier 3 — local-action queue (structured — for local Hermes / operator)

```yaml
local_action_queue:
  - action: download_model_update
    target_repo: Wan-AI/Wan2.7
    target_host: unknown  # spark hosting the video tail — please slot correctly
    reason: >-
      Wan 2.7 is the open-weights (Apache-2.0) successor to Wan 2.2 that we
      currently register. Wan 2.5 and 2.6 are API-only. Pulling this on the
      video-tail host lets the next digest run stage a parallel _reg("wan27").
    command_hint: |
      # confirm exact repo id from the Wan-AI HF org (e.g. Wan-AI/Wan2.7-T2V-14B)
      hf download Wan-AI/Wan2.7 --local-dir "D:\LLM\video\wan27"
    risk: medium

  - action: bump_node_pack_pin
    target_repo: 1038lab/ComfyUI-RMBG
    target_host: any-host-with-ComfyUI  # optional pack; installed per-user
    reason: >-
      v3.1.0 (2026-07-21) adds the Lucida BiRefNet variant — real quality
      win for AI Eraser / Remove Background on transparent objects,
      camouflage, text/logos, illustrations.
    command_hint: |
      cd ComfyUI/custom_nodes/ComfyUI-RMBG && git fetch && git checkout v3.1.0
    risk: low

  - action: verify_sam3_path
    target_repo: comfyanonymous/ComfyUI  # PR #13408
    target_host: any-host-with-ComfyUI
    reason: >-
      Native SAM 3.1 Multiplex nodes are now in core ComfyUI. Confirm
      whether Spellcaster's "AI Select" tool is invoking the native
      loader or the RMBG-bundled SAM3. If wrapper, migrate the workflow
      builder to native to drop a dependency edge.
    command_hint: |
      cd ComfyUI && git log --oneline --grep="SAM3\|sam3\|SAM 3" | head -5
      grep -rn "SAM3\|sam3" comfyui-spellcaster/spellcaster_core/workflows.py
    risk: low

  - action: probe_wan_animate2_availability
    target_repo: kijai/ComfyUI-WanVideoWrapper
    target_host: any-host-with-ComfyUI
    reason: >-
      Wan Animate 2 shipped as ComfyUI partner nodes in 2026. Check
      whether the kijai wrapper (already an optional dep) has picked
      up Animate 2, or whether the path is core-ComfyUI native. Result
      drives whether we edit the wrapper pin or the workflow builder.
    command_hint: |
      cd ComfyUI/custom_nodes/ComfyUI-WanVideoWrapper && git log --oneline --grep="animate.*2\|Animate 2" | head -5
    risk: low

  - action: retire_superseded_wan22_weights
    target_repo: Wan-AI/Wan2.2
    target_host: unknown  # video-tail host
    reason: >-
      Only AFTER Wan 2.7 is verified end-to-end AND a wan27 arch is
      registered and dispatching. Not a "do now" — the intent is to
      free VRAM/disk on the fleet once the swap is proven. Filed here
      so the local operator has a paper trail.
    command_hint: |
      # POST-VERIFICATION ONLY: move to cold storage, do not delete
      mv "D:\LLM\video\wan22" "D:\LLM\_retired\wan22-YYYY-MM-DD"
    risk: high

  - action: audit_leak_check_hits_on_main
    target_repo: laboratoiresonore/spellcaster
    target_host: local-workstation
    reason: >-
      `leak-check.yml` is red on main for 84 pre-existing pattern hits
      across _dev_docs/, _inventory/, antenna.RETIRED-*/,
      installer/remote_services.json, plugins/krita/spellcaster_krita.py,
      and comments in workflows.py / asset_gallery.py / mirror-drift.yml.
      Fix strategy is a curation call: widen exclusions, rename codenames,
      or mask real IPs — not safe as a mechanical PR.
    command_hint: |
      git grep -nIE 'Voodoomancer|Whimweaver|Laborantin|voodoo-core|Beatweaver|whimspider|\bTheo\b|192\.168\.86|192\.168\.0\.100|lmlgg|leguillaume|@gmail\.com|MASTER_PLAN' -- ':!.github/workflows/leak-check.yml' | wc -l
    risk: medium
```

## Operator-memory corrections (deltas vs prior notes)

- Wan 2.5 / 2.6 are **not** open weights — closed API models. Any older
  note that suggested we could self-host them is wrong. **Wan 2.7 is the
  correct upgrade target** for the local-only stance.
- Depth Anything **V4** does not exist as of this run's search. V3 (Nov 2025)
  is the latest; ComfyUI now ships it natively so our third-party wrapper
  is a cleanup candidate, not an upgrade candidate.

## Delivery

Gmail MCP requires interactive auth in this sandbox and is unavailable —
so the PR (with this file + Tier 1 diffs) is the sole delivery channel
this run. Google-Drive MCP is available but not used; the digest lives
in-repo per the routine spec.

## Budget

WebSearch calls: 8. WebFetch calls: 0. HF MCP calls: 1. Well under the
~25-call soft ceiling.
