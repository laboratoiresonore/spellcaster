# Spellcaster E2E Audit

_Ran at_: 2026-04-19 23:35:37
_Totals_: **54** pass · **0** fail · **0** warn · **8** skip

## build_* functions (compile + validate)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | build_color_match | 4 nodes, queued ok | 1777 |
| PASS | build_colorize | 12 nodes, queued ok | 602 |
| PASS | build_controlnet_gen | 12 nodes, queued ok | 160 |
| PASS | build_ddcolor | 3 nodes, queued ok | 43 |
| PASS | build_detail_hallucinate | 11 nodes, queued ok | 203 |
| SKIP | build_face_restore | env lacks model: model= | 105 |
| PASS | build_faceid_img2img | 12 nodes, queued ok | 276 |
| PASS | build_faceswap | 6 nodes, queued ok | 135 |
| SKIP | build_faceswap_model | needs extra args: build_faceswap_model() missing 1 required positional argument: 'face_model_name' | 0 |
| PASS | build_faceswap_mtb | 6 nodes, queued ok | 132 |
| PASS | build_frame_assembly | 2 nodes, queued ok | 85 |
| PASS | build_generate_anything | 9 nodes, queued ok | 23 |
| PASS | build_iclight | 10 nodes, queued ok | 63 |
| PASS | build_img2img | 9 nodes, queued ok | 55 |
| PASS | build_inpaint | 18 nodes, queued ok | 89 |
| PASS | build_klein_auto_inpaint | 24 nodes, queued ok | 42 |
| PASS | build_klein_batch_variations | 24 nodes, queued ok | 66 |
| PASS | build_klein_blend | 23 nodes, queued ok | 74 |
| PASS | build_klein_color_match | 4 nodes, queued ok | 65 |
| PASS | build_klein_detail | 12 nodes, queued ok | 65 |
| PASS | build_klein_face_detail | 9 nodes, queued ok | 52 |
| PASS | build_klein_generate_object | 23 nodes, queued ok | 61 |
| PASS | build_klein_headswap | 25 nodes, queued ok | 91 |
| PASS | build_klein_img2img | 21 nodes, queued ok | 84 |
| PASS | build_klein_img2img_ref | 24 nodes, queued ok | 81 |
| PASS | build_klein_inpaint | 22 nodes, queued ok | 71 |
| PASS | build_klein_refine | 27 nodes, queued ok | 45 |
| PASS | build_klein_repose | 21 nodes, queued ok | 77 |
| PASS | build_klein_sam3_inpaint | 22 nodes, queued ok | 37 |
| PASS | build_klein_scene_img2img | 19 nodes, queued ok | 60 |
| PASS | build_klein_virtual_tryon | 23 nodes, queued ok | 70 |
| PASS | build_lama_remove | 5 nodes, queued ok | 55 |
| PASS | build_layer_blend | 4 nodes, queued ok | 72 |
| PASS | build_ltx_video | 15 nodes, queued ok | 42 |
| SKIP | build_lut | needs extra args: build_lut() missing 1 required positional argument: 'lut_name' | 0 |
| PASS | build_magic_eraser | 5 nodes, queued ok | 43 |
| PASS | build_normal_map | 3 nodes, queued ok | 52 |
| PASS | build_outpaint | 12 nodes, queued ok | 53 |
| SKIP | build_photo_restore | needs extra args: build_photo_restore() missing 1 required positional argument: 'face_model' | 0 |
| PASS | build_photobooth | 25 nodes, queued ok | 46 |
| PASS | build_pulid_flux | 14 nodes, queued ok | 65 |
| SKIP | build_qwen_edit | env lacks model: clip_name=umt5-xxl-encoder-Q3_K_S.gguf | 52 |
| PASS | build_rembg | 3 nodes, queued ok | 64 |
| PASS | build_rembg_birefnet | 3 nodes, queued ok | 45 |
| PASS | build_sam3_extract | 3 nodes, queued ok | 56 |
| SKIP | build_sam3_mask | needs extra args: build_sam3_mask() missing 2 required positional arguments: 'nf' and 'image_ref' | 0 |
| PASS | build_sam3_segment | 5 nodes, queued ok | 63 |
| PASS | build_save_face_model | 4 nodes, queued ok | 56 |
| PASS | build_seedv2r | 11 nodes, queued ok | 70 |
| PASS | build_seedvr2_video_upscale | 6 nodes, queued ok | 67 |
| PASS | build_style_transfer | 12 nodes, queued ok | 56 |
| PASS | build_supir | 7 nodes, queued ok | 57 |
| PASS | build_txt2img | 8 nodes, queued ok | 50 |
| PASS | build_upscale | 4 nodes, queued ok | 45 |
| PASS | build_upscale_blend | 7 nodes, queued ok | 59 |
| SKIP | build_video_reactor | needs extra args: build_video_reactor() missing 1 required positional argument: 'face_models' | 0 |
| PASS | build_video_upscale | 7 nodes, queued ok | 50 |
| PASS | build_wan22_t2v | 15 nodes, queued ok | 42 |
| PASS | build_wan_flf | 31 nodes, queued ok | 76 |
| PASS | build_wan_video | 28 nodes, queued ok | 50 |
| SKIP | build_wan_video_blockswap | needs extra args: build_wan_video_blockswap() missing 3 required positional arguments: 'wan_model', 't5_model', and 'v | 0 |
| PASS | build_wavespeed_upscale | 3 nodes, queued ok | 55 |
