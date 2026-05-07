"""FramePack builder skeleton — PROMOTED 2026-05-06 (Sprint 3 Tier 2.1).

Status: SUPERSEDED. The live builder is `workflows.build_framepack_video`
(also live R4-verified against ComfyUI :8190 — 5/5 nodes present).
The arch entry in `architectures.py:framepack` is now `registered=True,
supported_methods=("video_img2video",)`.

This file is kept as a historical design-doc only — it is intentionally
NOT mirrored or auto-updated. Safe to delete. Refer to the live builder
or the §13 changelog of UPGRADE_PLAN_2026-05-06.md for current state.

ORIGINAL PROMOTION-PROCEDURE (kept for reference):

When ready to promote:
  1. Re-probe ComfyUI /object_info for every node class below
  2. Verify against the example_workflow JSONs in the pack
  3. Move this function (renamed to build_framepack_video) into
     workflows.py
  4. Flip framepack arch's registered=True + supported_methods=("i2v","v2v")
     in architectures.py
  5. Add to R8 matrix (FramePack: cfg=1, no negative-needed-for-cfg=1, no
     CN, sampler=unipc, custom guidance)
  6. Add a detect_framepack_preset() to video_presets.py (sibling to
     detect_wan_preset / detect_ltx_preset)
  7. Mirror per R1 to all 6 surfaces
  8. Run e2e_audit.py --only video,build_fns

Source pack: C:\\Users\\legui\\ComfyUI\\ComfyUI\\custom_nodes\\ComfyUI-FramePackWrapper_Plus
Reference workflow: example_workflows/framepack_F1_example.json

NODES USED (verified from pack source 2026-05-06):
  - LoadFramePackModel             (model loader)
  - DualCLIPLoader                 (llama + clip_l text encoders, core ComfyUI)
  - FramePackTimestampedTextEncode (timestamped prompt encoder)
  - CLIPVisionLoader               (core ComfyUI)
  - CLIPVisionEncode               (image conditioning)
  - VAELoader                      (Hunyuan VAE)
  - VAEEncode                      (start frame to latent)
  - FramePackFindNearestBucket     (image dim alignment)
  - ImageResize+                   (image dim adjust, from rgthree pack)
  - SDXLEmptyLatentSizePicker+     (size picker, from rgthree pack)
  - FramePackLoraSelect            (optional LoRA)
  - FramePackSampler_F1            (the F1 variant; FramePackSampler is the older one)
  - VAEDecodeTiled                 (low-VRAM VAE decode)
  - VHS_VideoCombine               (video output, from VHS pack)

KEY SIGNATURES (from FramePackWrapper_Plus/nodes.py + nodes_F1.py):

FramePackSampler.INPUT_TYPES (verbatim from source line 690-720):
  required:
    model:           FramePackMODEL
    positive:        CONDITIONING
    negative:        CONDITIONING
    start_latent:    LATENT (init for i2v)
    steps:           INT default 30
    use_teacache:    BOOLEAN default True
    teacache_rel_l1_thresh: FLOAT default 0.15
    cfg:             FLOAT default 1.0
    guidance_scale:  FLOAT default 10.0
    shift:           FLOAT default 0.0
    seed:            INT
    latent_window_size: INT default 9 (1..33)
    total_second_length: FLOAT default 5.0 (1..120)
    gpu_memory_preservation: FLOAT default 6.0 GB
    sampler:         enum(unipc_bh1, unipc_bh2)
  optional:
    image_embeds:    CLIP_VISION_OUTPUT
    end_latent:      LATENT
    end_image_embeds: CLIP_VISION_OUTPUT
    embed_interpolation: enum(disabled, weighted_average, linear)
    start_embed_strength: FLOAT
    initial_samples: LATENT (for v2v)
    denoise_strength: FLOAT

PROPOSED PYTHON SIGNATURE:

def build_framepack_video(image_filename, preset, prompt_text, negative_text,
                          seed, *,
                          width=640, height=640,
                          total_second_length=5.0,
                          fps=30,
                          steps=30, cfg=1.0, guidance_scale=10.0,
                          shift=0.0,
                          use_teacache=True, teacache_rel_l1_thresh=0.15,
                          latent_window_size=9,
                          gpu_memory_preservation=6.0,
                          sampler="unipc_bh1",
                          end_image_filename=None,
                          embed_interpolation="disabled",
                          start_embed_strength=1.0,
                          loras=None,
                          filename_prefix="spellcaster_framepack") -> dict:
    \"\"\"FramePack image-to-video via Kijai's ComfyUI-FramePackWrapper_Plus.

    FramePack (Jan 2026) is a Hunyuan-derived video model specifically
    optimized for low VRAM — the 6 GB-minimum design makes it the
    canonical I2V choice on a 16 GB GPU when the user wants to leave
    headroom for ST/Kobold/etc. Compared to WAN 2.2 14B I2V, FramePack
    trades some maximum quality for substantially less VRAM pressure
    + the ability to render arbitrarily long videos via section-by-
    section sampling (latent_window_size + total_second_length determine
    section count; gpu_memory_preservation enforces the headroom).

    Recipe summary (CLAUDE.md §16.4 — to be authored):
      preset      — from `video_presets.detect_framepack_preset(comfy_url)`.
                    Returns ckpt name + dual-CLIP files + VAE name +
                    CLIP-vision name. None when no FramePack model
                    detected on the server.
      total_second_length — wall-clock seconds. FramePack auto-divides
                    into latent_window_size-frame sections.
      cfg=1.0 + guidance_scale=10.0 are the canonical paired values
                    for FramePack (cfg controls the sampler's CFG;
                    guidance_scale is the model's distilled guidance).
                    Diverging from cfg=1 is rarely useful — the
                    distillation collapses CFG.
      use_teacache=True, rel_l1_thresh=0.15 — pack default; gives
                    ~25% wall-clock speedup at neutral quality.
      sampler=unipc_bh1 is the pack default; unipc_bh2 is faster but
                    sometimes loses motion detail.

    Pipeline (from example_workflows/framepack_F1_example.json):
      1. LoadFramePackModel(model_name) -> FramePackMODEL
      2. DualCLIPLoader(clip_name1, clip_name2, type="hunyuan_video")
         -> CLIP
      3. FramePackTimestampedTextEncode(clip, text, ...) -> CONDITIONING
         (positive)
      4. FramePackTimestampedTextEncode(clip, "", ...) -> CONDITIONING
         (negative; FramePack uses cfg=1 so neg is mostly null but
         must be present)
      5. CLIPVisionLoader(clip_vision_name) -> CLIP_VISION
      6. LoadImage(start_filename) -> IMAGE
      7. FramePackFindNearestBucket(image, base_resolution=640) ->
         (resized_image, resolution_info)
      8. CLIPVisionEncode(clip_vision, image=resized) -> CLIP_VISION_OUTPUT
      9. VAELoader(hunyuan_vae) -> VAE
      10. VAEEncode(image, vae) -> LATENT (start_latent)
      11. (optional) FramePackLoraSelect(...) chain on model
      12. FramePackSampler_F1(model, positive, negative, start_latent,
          image_embeds, ...) -> LATENT (samples)
      13. VAEDecodeTiled(vae, samples) -> IMAGE
      14. VHS_VideoCombine(images, fps, format="video/h264-mp4") -> file

    See _dev_docs/UPGRADE_PLAN_2026-05-06.md §6 risks for the R4
    /object_info verification gate before promoting.
    \"\"\"
    raise NotImplementedError(
        "FramePack builder is parked in _dev_docs until ComfyUI-side "
        "verification. See FRAMEPACK_BUILDER_SKELETON.py header.")
"""
"""

# Implementation will go here once verified. The above is the design
# document; the body is a no-op until promoted.

if __name__ == "__main__":
    print(__doc__)
"""
