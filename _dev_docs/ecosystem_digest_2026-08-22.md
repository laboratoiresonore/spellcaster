# Ecosystem Digest — 2026-08-22

Cloud sweep run under the every-48h routine. Behavioural rewrite of the
prompt (2026-08-18) took effect this run: fixes that could land safely
inside a PR *did* land inside this PR instead of accreting into another
report nobody reads.

## ⚠ Missing tool — flagged

`tools/upgrade_research.py` is still not in the repo. Every prior digest
falls back to WebSearch-only research, silently. This run does the same
for its Tier-2 sweep but is flagging the gap loudly. I did **not** draft
a replacement in this PR: the routine prompt describes the tool
generically ("what upgrade-research does") but the actual contract
(inputs, output shape, which registries it hits, VRAM/quality
thresholds it flags on) is not recoverable from context alone. A
drive-by stub would be worse than the absence, because a stub that
returns "no findings" would let the next run mark research done. Please
paste the intended `argparse` interface + example output shape into
the routine prompt, or restore the file from `.claude/skills/steward/`
history if it once existed, and the next run will fill it in.

---

## Tier 1 — fixed in this PR

Every fix here was verified against the existing test suite
(`PYTHONPATH=comfyui-spellcaster python3 tests/test_*.py`) — no
regressions, and one previously-red test flipped to green.

### 1. `supir` arch was missing from ARCHITECTURES → **real test failure fixed**

`model_detect.CKPT_ARCH_RULES` line 103 maps any filename containing
`supir` to arch key `supir`, but `architectures.py` had no matching
`_reg("supir", …)` entry. That means `get_arch("supir")` silently fell
back to SDXL — so a wizard summoned on a SUPIR checkpoint would list
`txt2img`, `img2img`, `inpaint`, etc, none of which will build
(`build_supir()` needs `supir_model` + `sdxl_model` paired, not a
single-checkpoint input). The dispatch would explode at sampler time
with an opaque error.

The failure was visible in
`tests/test_model_coverage.py::case_every_detected_arch_is_registered`:

```
[FAIL] registry: every detected arch is registered:
  Detector can emit these archs that aren't in ARCHITECTURES: ['supir'].
```

**Fix:** added `_reg("supir", …)` as a `registered=False` stub with
`supported_methods=()`, mirroring the pattern used for
`hunyuan_dit` / `pixart` / `kolors`. SUPIR is still dispatched via its
dedicated `build_supir()` path — the stub just keeps the wizard UI
honest (`supports_method()` returns False for everything) and makes the
model-coverage guard pass.

Diff: `comfyui-spellcaster/spellcaster_core/architectures.py` (adds one
`_reg` block after `_reg("kolors", …)`).

**Verification:**

```
$ PYTHONPATH=comfyui-spellcaster python3 tests/test_model_coverage.py
============================================================
PASSED (19/19)   # was FAILED (1/19) before this PR
```

### 2. `SUPPORTED ARCHITECTURES (as of April 2026)` docstring was stale + incomplete

The header docstring in `architectures.py` claimed the registry only
covered 7 archs from April 2026. The actual `_reg()` list has grown to
26+ (adding `chroma`, `lumina2`, `sdxl_turbo`, `pony`, `playground`,
five DiT stubs, six video archs, `hunyuan_3d`, and now `supir`).
Updated the docstring to reflect the real Aug-2026 layout, grouped by
kind (image / video / restoration+stubs) so the reader can tell at a
glance which archs have first-class builders vs which are detector-only
stubs.

Diff: `comfyui-spellcaster/spellcaster_core/architectures.py` (docstring
only, no behaviour change).

### 3. README status header was 3 months stale

`README.md:46` still said `📣 Status — May 2026`. Bumped to
`August 2026`. The prose paragraph below is still accurate (installer
hardening, LM Studio prompt enhancement, mirror sync all landed prior
to this window) so left as-is; only the date changed. If the operator
wants the paragraph rewritten to cover post-May items (antenna
retirement in June, nightly.yml CI, HERMES-EDITS-CODE scaffold in
July/Aug), that's a Tier-2 judgement call — kept off this diff.

### 4. `test_full_inline_workflow_shape` was red because `disk_backup=True` became the default

`save_image_websocket()` grew a `disk_backup=True` default in a prior
commit (adds a parallel `SaveImage` node so the poll-fallback path can
recover the result from `/history` when the ws connection dies —
observed 2026-05-09 per the docstring). The test was written before
that landed and still expected a 2-node workflow; it was asserting the
pure ws-only shape but the default is now ws + disk pair.

Two-part fix:

- `tests/test_phase9_ws.py::test_full_inline_workflow_shape` — pass
  `disk_backup=False` so the test still asserts the ws-only shape it was
  written for. This preserves the test's original intent instead of
  silently accepting the new 3-node reality.
- Added `test_save_image_websocket_disk_backup_pair` — new test that
  covers the disk-backup default (verifies both nodes are added, share
  the same source images ref, and use `filename_prefix="spellcaster"`).
  Registered in the test runner. This is real coverage that was missing
  entirely for a resilience feature.

**Verification:**

```
$ PYTHONPATH=comfyui-spellcaster python3 tests/test_phase9_ws.py
All 34 tests passed.   # was FAILED (1 of 33) before this PR
```

### Full test-suite verification (baseline: 2 red before → all green after)

```
tests/test_auto_updater.py            PASSED (5/5)
tests/test_cn_compat.py               PASS — all 280 pairs validated.
tests/test_klein_enhancer.py          PASSED (27/27)
tests/test_lora_auto_calibrate.py     PASSED (59/59)
tests/test_model_coverage.py          PASSED (19/19)   ← was 18/19
tests/test_model_prompt_profiles.py   PASSED (22/22)
tests/test_phase9_ws.py               All 34 tests passed.  ← was 32/33 + 1 new
tests/test_quality_boost.py           PASSED (54/54)
tests/test_summon_archetypes.py       PASSED (24/24)
```

---

## Tier 2 — new-model / architecture integration work (needs human judgement)

The three landings below are all things Spellcaster already has an
adjacent builder for; none of them will get scaffolded correctly by
existing code as-is, so they are integration work, not "just download".

| Model                             | Released    | Replaces / augments                    | VRAM est. | Risk   | Notes                                                                                                                                                                                                       |
| --------------------------------- | ----------- | -------------------------------------- | --------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Wan-AI/Wan2.2-Animate-2-14B**   | 2026-07-14  | `build_wan_animate_video` path         | 24GB+     | low    | Native ComfyUI support landed 2026-08-08. Two new nodes: `WanAnimate2ToVideo` (conditioning shaper — supersedes `WanAnimateToVideo`) and `WanAnimate2Cache` (~2× speedup by caching the pose branch). Distilled diffusers variant also published. Spellcaster's WAN_EXTRA_METHODS = `("video_animate",)` still points at the v1 builder; adding a v2 branch is a one-file change in `workflows.py` once the model is on-Spark. |
| **Lightricks/LTX-2.5 (Dev + Distilled)** | 2026-08-11 | `_reg("ltx", …)` + `build_ltx_video`  | 24GB (Dev), 12GB (Distilled) | medium | 22B open-weights audio+video foundation. Native ComfyUI day-0. Notable: multi-shot scenes, auto duration, 4K HDR, synchronized audio in the same pass. Distilled generates a 10s clip in ~6.8s on NVIDIA superchips. Spellcaster's LTX arch stub still targets the 2.3 flow; a `ltx25` arch key + separate builder is the cleanest path (audio-out doesn't fit the existing image-only handler contract). |
| **lodestones/Chroma1-Radiance**   | 2025-08-22 (rev 2025-11-27) | Complements `_reg("chroma", …)`     | 16GB      | low    | Chroma variant that generates in *pixel space* rather than latent space; ComfyUI has native BlockInfo support as of v0.3.60. Trades some speed for detail retention on high-res outputs. Would be a `chroma_radiance` sibling arch, not a chroma replacement — worth wiring for the photo-restoration surface where latent decode softness matters. |

I did **not** push these to Tier 1 because they all touch dispatch
paths + require an on-Spark checkpoint before any sensible smoke test
can run in-repo. VRAM + speed tradeoffs also need operator judgement.

Notably NOT flagged:
- No credible **SUPIR successor** landed in the window. SUPIR is still
  the SOTA restoration baseline referenced by NTIRE 2024 and by 2026
  survey papers. DiffBIR and ResShift are viable alternatives on the
  low-VRAM end but neither displaces SUPIR for the "damaged / heavily
  compressed photo" use case Restorix wraps. No action.
- No new **Flux 2 family** beyond Klein 4B (Jan 2026) — Pro is
  proprietary. Nothing to integrate.

---

## Tier 3 — local action queue (structured, machine-consumable)

Cloud sandbox cannot reach Spark / Theo / Prometheus. The block below
is intentionally structured (not prose) so a local Hermes/Claude
process — or the operator by hand — can pick each entry up and act on
it without having to re-derive the command from a paragraph.

```yaml
local_action_queue:
  - action: download_model_update
    target_repo: Wan-AI/Wan2.2-Animate-2-14B
    target_host: unknown          # was: Spark that already hosts Wan2.2-Animate-14B (~18GB)
    reason: >
      Wan Animate 2 supersedes v1's WanAnimateToVideo path; 237K downloads
      on the Comfy-Org mirror in 5 weeks says it's the actual v2. Integration
      is a builder-side change in Spellcaster (see Tier 2, row 1).
    command_hint: |
      huggingface-cli download Wan-AI/Wan2.2-Animate-2-14B \
        --local-dir D:\LLM\video\wan-animate-2 --exclude "*.bin"
    risk: low

  - action: download_model_update
    target_repo: Comfy-Org/Wan-Animate-2
    target_host: unknown          # ComfyUI-packaged single-file — likely same Spark as above
    reason: >
      ComfyUI-Org packaged single-file mirror — usually the drop-in that plugs
      into workflow templates without re-plumbing loaders. Grab it as well as
      the raw diffusers repo; keeps both dispatch options open.
    command_hint: |
      huggingface-cli download Comfy-Org/Wan-Animate-2 \
        --local-dir <ComfyUI>\models\diffusion_models\wan-animate-2
    risk: low

  - action: download_model_evaluate
    target_repo: Lightricks/LTX-2.5           # Dev (22B)
    target_host: unknown          # only Spark with 24GB+ headroom
    reason: >
      Successor to LTX-2.3 (which Spellcaster already dispatches). Multi-shot
      + audio changes the handler contract, so this is a Tier-2 integration
      *not* a straight arch swap — DO NOT retire LTX-2.3 until the ltx25 path
      is wired and calibrated.
    command_hint: |
      huggingface-cli download Lightricks/LTX-2.5 \
        --local-dir D:\LLM\video\ltx-2.5
    risk: medium

  - action: download_model_evaluate
    target_repo: Lightricks/LTX-2.5-Distilled
    target_host: unknown          # low-VRAM Spark
    reason: >
      Distilled sibling — 6.8s for a 10s 720p clip on RTX-class hardware.
      Better fit for low-VRAM peers where Dev won't fit.
    command_hint: |
      huggingface-cli download Lightricks/LTX-2.5-Distilled \
        --local-dir D:\LLM\video\ltx-2.5-distilled
    risk: low

  - action: download_model_evaluate
    target_repo: lodestones/Chroma1-Radiance
    target_host: unknown          # any Spark with 16GB
    reason: >
      Pixel-space Chroma variant — sharper high-res output at some speed cost.
      Complements existing chroma arch, doesn't replace it. Worth wiring on
      the restoration surface.
    command_hint: |
      huggingface-cli download lodestones/Chroma1-Radiance \
        --local-dir D:\LLM\image\chroma1-radiance
    risk: low

  - action: fill_tool_gap
    target_repo: laboratoiresonore/spellcaster
    target_host: any              # operator's local workstation is fine
    reason: >
      tools/upgrade_research.py has been missing for multiple digests.
      Every run silently degrades to WebSearch-only. Paste the argparse
      contract + expected output shape into the routine prompt (or restore
      from Hermes/Steward history) and the next cloud run will draft the
      script.
    command_hint: (no command — needs operator to publish the intended contract)
    risk: low
```

---

## Corrections to operator memory

None this run — this is the first digest under the rewritten routine, so
there is no prior operator memory to correct. Future runs should list
anything they know they got wrong last time here.

---

## Delivery notes

- Digest committed on branch `claude/adoring-allen-hk0cxu` and pushed.
- PR opened via `mcp__github__create_pull_request` (see PR body for the
  same summary in short form).
- Gmail MCP is un-authorized in this session (see the session's MCP
  banner). Falling back to the PR as the sole delivery channel, as the
  routine says to do when Gmail auth is expired. No silent skip.
