# Phase 9 — Builder Adoption Checklist (`save_image_websocket`)

**Date:** 2026-05-01
**Scope:** `comfyui-spellcaster/spellcaster_core/workflows.py` (canonical) — 42 `build_*` functions, 53 `nf.save_image(...)` call sites.
**Predecessor:** `_dev_docs/PHASE_9_SPEC.md` — defines transport, race-free order, failure modes, six-surface sync.
**Status driver:** `PHASE_9_SPEC.md:122` "Builder adoption: no `_workflows_v2` calls `save_image_websocket` yet".

> Clarification on the spec phrasing: `plugins/gimp/comfyui-connector/_workflows_v2.py` is a 35-line shim that `from spellcaster_core.workflows import *`. The real builder set lives in canonical `workflows.py`. "Builder adoption" = "swap `nf.save_image(...)` to `nf.save_image_websocket(...)` (or `nf.etn_send_image_websocket(...)`) inside each `build_*` function".

---

## 1. What "migration" means per builder

```diff
- nf.save_image([dec_id, 0], "spellcaster_xxx", node_id="N")
+ nf.save_image_websocket([dec_id, 0], node_id="N")
```

The dispatcher (`dispatch.dispatch_workflow(..., use_websocket=True)`) collects the binary frame into `result.binary_outputs: list[(format_name, image_bytes)]`. The GIMP plugin already folds these into `_download_cache` with synthesised `(ws_inline_<hex>.png, "", "output")` keys (`_spellcaster_main.py:12750-12760`), so **no GIMP wire-up is needed for single-output builders**.

`use_websocket=True` is already passed defensively at the dispatch site (`_spellcaster_main.py:12697-12724`) with `inspect.signature` feature detection, so a builder swap takes effect the moment the canonical mirror reaches surface #2.

---

## 2. Pre-migration constraints (read before touching anything)

### C1. Filename discriminator filtering downstream

Some builders emit **two distinct outputs** that the GIMP plugin disambiguates by filename substring. Migration silently breaks this because every binary output collapses to the synthesised `ws_inline_<hex>.png`.

| Builder | Discriminator (filename substr) | Downstream consumer |
|---|---|---|
| `build_generate_anything` (706, 719) | `"object"` / `"rmbg"` vs `"raw"` | `_spellcaster_main.py:26129` `if 'object' in fn.lower() or 'rmbg' in fn.lower()` |
| `build_sam3_segment` (6496, 6498) | `"sam3_subject"` vs `"sam3_mask"` | mask-mode UI imports the mask separately |
| `build_klein_generate_object` (7184, 7199) | `"klein_generated"` vs `"klein_object"` | analogous to generate_anything |
| `build_klein_batch_variations` (5673, 5691) | per-variation prefix vs `"_grid"` | grid/individual disambiguation |
| `build_klein_headswap` (3937, 4018) | branch A (identity) and branch B (legacy ReActor) emit at different node_ids; both prefix `"spellcaster_headswap"`. Single output per dispatch — safe. |
| `build_klein_detail` (7387, 7452) | both branches prefix `"klein_detail"`; only one fires per dispatch — safe. |

**Required fix before migrating C1 builders:** extend `binary_outputs` with a third element (label/prefix) — e.g. `(format_name, image_bytes, label)` — and have the builder pass the label via a new `save_image_websocket(..., label="generated_object")` kwarg. The dispatcher would attach the label by collecting frames in node-id order or by reading a paired text message. This is **out of scope for the first pass**; track as `OQ7` in `PHASE_9_SPEC.md:259` follow-ups.

### C2. Video builders — `SaveVideo` / `VHS_VideoCombine` companion

Builders that output a **video** alongside a frame thumbnail. The video must stay on disk (poll path consumes `videos`/`gifs` keys; ws path consumes `gifs` only — `PHASE_9_SPEC.md:262`). The frame thumbnail is the only candidate for ws migration, but two complications:

| Builder | Frame call | Video node | GIMP-side filter |
|---|---|---|---|
| `build_video_upscale` (4067) | `"gimp_video_upscale_frame"` | `"31"` SaveVideo (4062) | n/a — single thumb consumed by frame display |
| `build_video_reactor` (4137) | `"gimp_video_reactor_frame"` | `"71"` SaveVideo (4132) | n/a |
| `build_wan_video` (4693) | `f"{prefix}_lastframe"` | VHS_VideoCombine (4645, 4680) | **`_spellcaster_main.py:11013, 21874, 22155` — `if fn.lower().endswith(".png") and "lastframe" in fn.lower():`** |
| `build_seedvr2_video_upscale` (4984) | `"seedvr2_upscale_frame"` | VHS_VideoCombine `"10"` (4977) | n/a |

`build_wan_video` migration breaks the lastframe filter (synth name has no `"lastframe"` substring). Resolve C1 first; or pass a `label="lastframe"` once `binary_outputs` carries labels; or leave the lastframe on `save_image` (simplest — the speedup is negligible for a workflow that just spent 60+ s on diffusion).

### C3. Face model artefact preservation

`build_save_face_model` (2032-, save at 2044, prefix `"gimp_face_model_src"`) writes a *source preview alongside* a `.safetensors` face model created by ReactorSaveFaceModel elsewhere in the same workflow. **The on-disk preview is intentional** (it's the user-facing record of which photo built the model). Do not migrate.

### C4. Mirror surfaces (R1)

Every change to canonical `workflows.py` triggers the R1 sync rule (`CLAUDE.md:65-67`). Five mirror surfaces. **Do not migrate one builder per commit** — batch the P1 set into a single canonical commit, mirror once. R1 mirror was already done for Phase 9 core (`PHASE_9_SPEC.md` follow-up R1 marked DONE), but builder edits will require a fresh sync pass.

---

## 3. Priority-ordered migration list

### P1 — single-output image builders (safe, ship first)

One-line edit per builder. No GIMP-side change needed. Ordered by user-facing latency benefit (short-running workflows benefit most from killing the 500 ms poll race).

| # | Builder | Line | save_image prefix | Notes |
|---|---|---|---|---|
| 1 | `build_lut` | 1049 | `spellcaster_lut` | Pure CPU node; sub-second runs — biggest poll-race win. |
| 2 | `build_color_match` | 1090 | `spellcaster_colormatch` | Same. |
| 3 | `build_layer_blend` | 7501 | `spellcaster_blend_ratio` | Same. |
| 4 | `build_rembg` | 760 | `spellcaster_rembg` | Fast model. |
| 5 | `build_rembg_birefnet` | 813 | `spellcaster_rembg` | Fast. |
| 6 | `build_ddcolor` | 841 | `spellcaster_colorize` | Fast. |
| 7 | `build_normal_map` | 938 | `spellcaster_normals` | Fast. |
| 8 | `build_lama_remove` | 998 | `spellcaster_lama` | Fast. |
| 9 | `build_upscale` | 882 | `spellcaster_upscale` | Variable. |
| 10 | `build_wavespeed_upscale` | 901 | `spellcaster_upscale` | Variable. |
| 11 | `build_klein_color_match` | 6415 | `klein_color_match` | Fast. |
| 12 | `build_upscale_blend` | 7571 | `spellcaster_upblend` | Fast. |
| 13 | `build_img2img` | 453 | `gimp_comfy` | |
| 14 | `build_txt2img` | 579 | `gimp_comfy` | |
| 15 | `build_klein_img2img` | 1721 | `gimp_klein` | |
| 16 | `build_klein_img2img_ref` | 3717 | `gimp_klein_ref` | |
| 17 | `build_klein_inpaint` | 5826 | `spellcaster_klein_inpaint` | |
| 18 | `build_klein_repose` | 5466 | `spellcaster_repose` | |
| 19 | `build_klein_blend` | 5556 | `spellcaster_blend` | |
| 20 | `build_klein_virtual_tryon` | 5998 | `klein_tryon` | |
| 21 | `build_klein_scene_img2img` | 6071 | `studio_set` | |
| 22 | `build_klein_refine` | 6220 | `klein_refine` | |
| 23 | `build_klein_auto_inpaint` | 6360 | `klein_auto_inpaint` | |
| 24 | `build_klein_sam3_inpaint` | 6899 | `klein_sam3` | |
| 25 | `build_klein_face_detail` | 7035 | `klein_face_detail` | |
| 26 | `build_klein_headswap` (both branches) | 3937, 4018 | `spellcaster_headswap` | One branch fires per dispatch — single output. |
| 27 | `build_klein_detail` (both branches) | 7387, 7452 | `klein_detail` | Same. |
| 28 | `build_inpaint` | 3235 | `gimp_inpaint` | |
| 29 | `build_outpaint` | 3414 | `spellcaster_outpaint` | |
| 30 | `build_face_restore` | 2099 | `spellcaster_facerestore` | |
| 31 | `build_photo_restore` | 2185 | `spellcaster_photorestore` | |
| 32 | `build_detail_hallucinate` | 2353 | `spellcaster_hallucinate` | |
| 33 | `build_colorize` | 2488 | `spellcaster_colorize` | |
| 34 | `build_controlnet_gen` | 2638 | `spellcaster_controlnet` | |
| 35 | `build_iclight` | 2832 | `spellcaster_iclight` | |
| 36 | `build_supir` | 2971 | `spellcaster_supir` | |
| 37 | `build_faceswap` | 1949 | `gimp_faceswap` | |
| 38 | `build_faceswap_model` | 2028 | `gimp_faceswap_model` | |
| 39 | `build_faceswap_mtb` | 2064 | `gimp_faceswap_mtb` | |
| 40 | `build_faceid_img2img` | 3515 | `gimp_faceid` | |
| 41 | `build_pulid_flux` | 3611 | `gimp_pulid_flux` | |
| 42 | `build_style_transfer` | 5097 | `spellcaster_style` | |
| 43 | `build_seedv2r` | 5203 | `spellcaster_seedv2r` | |
| 44 | `build_photobooth` | 5370 | `photobooth` | |
| 45 | `build_sam3_extract` | 6556 | `sam3_extracted` | Single output (vs `build_sam3_segment` which has two). |
| 46 | `build_magic_eraser` | 6645 | `spellcaster_magic_eraser` | |
| 47 | `build_qwen_edit` | 7990 | `spellcaster_qwen_edit` | |

**P1 commit shape:** one canonical commit `phase 9: migrate single-output builders to save_image_websocket`, then mirror across surfaces #2-#6 per R1, then build NSFW patch (`python nsfw/build_nsfw.py --patch-only --push`).

### P2 — multi-output discriminator builders (requires `binary_outputs` label support)

Blocked on a `binary_outputs` schema bump (third tuple element = label) AND the matching `save_image_websocket(..., label=...)` kwarg AND the GIMP plugin synth-key change to use the label. Track as new follow-up `OQ7` in `PHASE_9_SPEC.md:259`.

| Builder | Lines | Outputs | Discriminator |
|---|---|---|---|
| `build_generate_anything` | 706, 719 | raw + rmbg | `"object"`/`"rmbg"` substring |
| `build_sam3_segment` | 6496, 6498 | subject + mask | `"sam3_mask"` substring |
| `build_klein_generate_object` | 7184, 7199 | full + cutout | `"klein_object"` |
| `build_klein_batch_variations` | 5673, 5691 | individual + grid | `"_grid"` suffix |

### P3 — video builders (deferred, low value)

Save_image is a frame thumbnail; the video file dominates wall-clock time, so the poll-race latency win is sub-1% of dispatch. Skip until a real signal demands it.

| Builder | Lines | Why deferred |
|---|---|---|
| `build_video_upscale` | 4067 | Frame is companion to SaveVideo. |
| `build_video_reactor` | 4137 | Same. |
| `build_wan_video` | 4693 | Lastframe filter requires C1 resolution first. |
| `build_seedvr2_video_upscale` | 4984 | Companion to VHS_VideoCombine. |

### Pure-video builders — nothing to migrate

`build_wan_flf`, `build_wan22_t2v`, `build_frame_assembly`, `build_wan_video_blockswap`, `build_ltx_video` emit only video via `VHS_VideoCombine`. No `save_image` calls. The ws path's `gifs` key consumption (`PHASE_9_SPEC.md:66`) already covers `VHS_VideoCombine` — these builders work over the ws path today without any change. `SaveVideo` (`videos` key) is the gap; not used by these builders.

### Skip — intentional disk artefact

`build_save_face_model` (2044) — see C3.

---

## 4. Verification per builder

Per CLAUDE.md test gate (`CLAUDE.md:5`):

```bash
PYTHONIOENCODING=utf-8 python tests/e2e_audit.py --offline   # green bar pre-commit
PYTHONIOENCODING=utf-8 python tests/e2e_audit.py --only build_fns  # against live ComfyUI
PYTHONIOENCODING=utf-8 python tests/test_phase9_ws.py        # 28/28 ws-specific
```

Smoke test from GIMP after mirror:
1. Run a P1 builder end-to-end (e.g. img2img).
2. Confirm `[Spellcaster]` log shows `transport=websocket` (add a one-line debug emit during P1 if not present).
3. Confirm output layer imports correctly.
4. Confirm `output/` directory on the ComfyUI server does **not** receive a new file from the migrated builder (privacy win — `PHASE_9_SPEC.md:208-210`).

---

## 5. Six-surface mirror reminder (R1)

After canonical edit:
1. Mirror `workflows.py` to surfaces #2 (`plugins/gimp/comfyui-connector/spellcaster_core/`), #3 (`../ComfyUI-Spellcaster/spellcaster_core/`), #4 (`../ComfyUI-Spellcaster-NSFW/spellcaster_core/`), #6 (`<private-distro>/plugin/comfyui-connector/spellcaster_core/`).
2. Surface #5 (`%APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/spellcaster_core/`) refreshes via auto-updater on next GIMP launch — verify by hash after a launch.
3. `md5sum` byte-identity check across surfaces #1-#4 and #6.
4. `python nsfw/build_nsfw.py --patch-only --push`.
5. Use `.claude/agents/sync-checker` for the audit pass before commit.

---

## 6. Rollback plan

If a P1 migration regresses a single builder, the dispatcher's `ws_fallback_to_poll=True` (default) kicks in on any ws-side failure (`PHASE_9_SPEC.md` §4 F1-F12) so the user-facing path stays green. The actual rollback is a one-line revert per builder. No DB / state migration involved.

---

## 7. Refs

- `_dev_docs/PHASE_9_SPEC.md` — protocol, failure modes, surface audit (predecessor; mirror sync R1 marked DONE there)
- `comfyui-spellcaster/spellcaster_core/node_factory.py:1315-1333` — `save_image_websocket` definition
- `comfyui-spellcaster/spellcaster_core/node_factory.py:1287-1313` — `etn_send_image_websocket` (Acly pack alternative)
- `comfyui-spellcaster/spellcaster_core/dispatch.py:285-300` — `use_websocket` kwarg docstring
- `plugins/gimp/comfyui-connector/_spellcaster_main.py:12697-12760` — already-wired GIMP dispatch site (binary_outputs fold-in is defensive; will activate the moment the first builder migrates)
- `CLAUDE.md:65-67` — R1 six-surface mirror rule
- `tests/test_phase9_ws.py` — 28 ws-specific tests; re-run after each migration batch

---

## 8. Open questions / new follow-ups

- **OQ7 (new):** `binary_outputs` label support to unblock P2 builders. Schema change: `list[(format_name, bytes)]` → `list[(format_name, bytes, label: str | None)]`. Dispatcher attaches the label by reading the `node_id`'s configured `filename_prefix` (which `save_image_websocket` would now accept) at frame-decode time. Backward-compatible if defaulted.
- **OQ8 (new):** decide whether to migrate `build_wan_video` lastframe-only (skip the SaveVideo) — gated on OQ7.
- **OQ9 (new):** `SaveVideo`'s `videos` key on the ws path — `_collect_outputs_from_executed` (`comfy_ws.py`) currently reads `images` and `gifs` only (`PHASE_9_SPEC.md:262` was already aware). One-line addition; needed before any pure-video builder switches its `VHS_VideoCombine` to `SaveVideo`.
