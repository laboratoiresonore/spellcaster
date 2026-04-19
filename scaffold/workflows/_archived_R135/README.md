# Archived workflow JSONs (R135)

These were static snapshots consumed by the pre-R126 video bridge's disk-JSON
fallback path. They're now dead code — every preset they covered routes through
the canonical builders in `spellcaster_core/workflows.py` via
`scaffold/video_workflow_dispatch.py`.

## Why they're archived, not deleted

- **Reference documentation** — the LTX-2 node graphs here are sometimes
  useful to eyeball when debugging workflow issues, since ComfyUI's UI export
  format is harder to diff than a clean JSON.
- **No functional cost to keeping them** — PyInstaller bundles the
  `scaffold/workflows/` tree wholesale, so these files ride along but are
  never loaded at runtime.

## What replaced each one

| Archived JSON | Canonical builder + dispatch path |
|---|---|
| `ltx2_image_to_video.json` | `build_ltx_video(..., image_filename=...)` via R133 dispatcher |
| `ltx2_text_to_video.json` | `build_ltx_video()` via R133 dispatcher |
| `ltx2_text_to_video_distilled.json` | `build_ltx_video(..., distilled=True)` via R133 |
| `ltx2_text_to_video_2stage.json` | `build_ltx_video(..., two_stage=True)` via R133 |
| `ltx2_t2v_with_rife_interpolation.json` | `build_ltx_video(..., interpolate=True)` via R133 |
| `ltx2_t2v_with_rtx_upscale.json` | `build_ltx_video(..., rtx_scale=2)` via R133 |
| `ltx2_v2v_flowedit.json` | Not yet ported — LTX v2v flow-edit needs a dedicated builder |
| `seedvr2_video_upscale.json` | `build_seedvr2_video_upscale()` via R134 dispatcher + R135 `_chain_comfy_upscale` migration |

## Known bug in the archived snapshots

They hardcoded `ltx-2.3-vae.safetensors` — a filename that doesn't exist on
the tested ComfyUI install. The resolver in `video_workflow_dispatch.py`
probes `/object_info` and picks concrete filenames (`LTX23_video_vae_bf16.
safetensors` in practice), so the native path avoids this class of breakage.

## Still live

`scaffold/workflows/wan22_v2v_vace_mask.json` was **not** archived — it's the
only preset where no canonical builder exists yet, so the `_queue_comfy`
disk-JSON fallback still serves it.
