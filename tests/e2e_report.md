# Spellcaster E2E Audit

_Ran at_: 2026-04-19 22:23:13
_Totals_: **2** pass · **45** fail · **0** warn · **15** skip

## build_* functions (compile + validate)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| FAIL | build_color_match | ComfyUI -1: URLError: <urlopen error timed out> | 15007 |
| FAIL | build_colorize | ComfyUI -1: URLError: <urlopen error timed out> | 15000 |
| SKIP | build_controlnet_gen | needs extra args: build_controlnet_gen() missing 2 required positional arguments: 'preprocessor_type' and 'controlnet_ | 0 |
| FAIL | build_ddcolor | ComfyUI -1: URLError: <urlopen error timed out> | 15000 |
| SKIP | build_detail_hallucinate | needs extra args: build_detail_hallucinate() missing 1 required positional argument: 'upscale_model' | 0 |
| FAIL | build_face_restore | ComfyUI -1: URLError: <urlopen error timed out> | 15004 |
| FAIL | build_faceid_img2img | ComfyUI -1: URLError: <urlopen error timed out> | 15011 |
| FAIL | build_faceswap | ComfyUI -1: URLError: <urlopen error timed out> | 15002 |
| SKIP | build_faceswap_model | needs extra args: build_faceswap_model() missing 1 required positional argument: 'face_model_name' | 0 |
| FAIL | build_faceswap_mtb | ComfyUI -1: URLError: <urlopen error timed out> | 15013 |
| FAIL | build_frame_assembly | ComfyUI -1: URLError: <urlopen error timed out> | 15001 |
| FAIL | build_generate_anything | ComfyUI -1: URLError: <urlopen error timed out> | 15001 |
| FAIL | build_iclight | ComfyUI -1: URLError: <urlopen error timed out> | 15003 |
| FAIL | build_img2img | ComfyUI -1: URLError: <urlopen error timed out> | 15012 |
| FAIL | build_inpaint | ComfyUI -1: URLError: <urlopen error timed out> | 15014 |
| FAIL | build_klein_auto_inpaint | ComfyUI -1: URLError: <urlopen error timed out> | 15001 |
| FAIL | build_klein_batch_variations | ComfyUI -1: URLError: <urlopen error timed out> | 15003 |
| FAIL | build_klein_blend | ComfyUI -1: URLError: <urlopen error timed out> | 15008 |
| FAIL | build_klein_color_match | ComfyUI -1: URLError: <urlopen error timed out> | 15014 |
| FAIL | build_klein_detail | ComfyUI -1: URLError: <urlopen error timed out> | 15009 |
| FAIL | build_klein_face_detail | ComfyUI -1: URLError: <urlopen error timed out> | 15007 |
| FAIL | build_klein_generate_object | ComfyUI -1: URLError: <urlopen error timed out> | 15016 |
| FAIL | build_klein_headswap | ComfyUI -1: URLError: <urlopen error timed out> | 15006 |
| FAIL | build_klein_img2img | ComfyUI -1: URLError: <urlopen error timed out> | 15001 |
| FAIL | build_klein_img2img_ref | ComfyUI -1: URLError: <urlopen error timed out> | 15008 |
| FAIL | build_klein_inpaint | ComfyUI -1: URLError: <urlopen error timed out> | 15014 |
| FAIL | build_klein_refine | ComfyUI -1: URLError: <urlopen error timed out> | 15013 |
| FAIL | build_klein_repose | ComfyUI -1: URLError: <urlopen error timed out> | 15015 |
| FAIL | build_klein_sam3_inpaint | ComfyUI -1: URLError: <urlopen error timed out> | 15004 |
| FAIL | build_klein_scene_img2img | ComfyUI -1: URLError: <urlopen error timed out> | 15005 |
| FAIL | build_klein_virtual_tryon | ComfyUI -1: URLError: <urlopen error timed out> | 15012 |
| FAIL | build_lama_remove | ComfyUI -1: URLError: <urlopen error timed out> | 15005 |
| FAIL | build_layer_blend | ComfyUI -1: URLError: <urlopen error timed out> | 15005 |
| FAIL | build_ltx_video | KeyError: 'unet' | 0 |
| SKIP | build_lut | needs extra args: build_lut() missing 1 required positional argument: 'lut_name' | 0 |
| FAIL | build_magic_eraser | ComfyUI -1: URLError: <urlopen error timed out> | 15006 |
| FAIL | build_normal_map | ComfyUI -1: URLError: <urlopen error timed out> | 15013 |
| FAIL | build_outpaint | ComfyUI -1: URLError: <urlopen error timed out> | 15013 |
| SKIP | build_photo_restore | needs extra args: build_photo_restore() missing 2 required positional arguments: 'upscale_model' and 'face_model' | 0 |
| FAIL | build_photobooth | ComfyUI -1: URLError: <urlopen error timed out> | 15013 |
| FAIL | build_pulid_flux | ComfyUI -1: URLError: <urlopen error timed out> | 15010 |
| SKIP | build_qwen_edit | needs extra args: build_qwen_edit() missing 3 required positional arguments: 'unet_name', 'clip_name', and 'vae_name' | 0 |
| FAIL | build_rembg | ComfyUI -1: URLError: <urlopen error timed out> | 15015 |
| FAIL | build_rembg_birefnet | ComfyUI -1: URLError: <urlopen error timed out> | 15011 |
| FAIL | build_sam3_extract | ComfyUI -1: URLError: <urlopen error timed out> | 15012 |
| SKIP | build_sam3_mask | needs extra args: build_sam3_mask() missing 2 required positional arguments: 'nf' and 'image_ref' | 0 |
| FAIL | build_sam3_segment | ComfyUI -1: URLError: <urlopen error timed out> | 15004 |
| FAIL | build_save_face_model | ComfyUI -1: URLError: <urlopen error timed out> | 15007 |
| SKIP | build_seedv2r | needs extra args: build_seedv2r() missing 1 required positional argument: 'upscale_model' | 0 |
| FAIL | build_seedvr2_video_upscale | ComfyUI -1: URLError: <urlopen error timed out> | 15015 |
| SKIP | build_style_transfer | env lacks model: ckpt_name= | 62 |
| SKIP | build_supir | needs extra args: build_supir() missing 2 required positional arguments: 'supir_model' and 'sdxl_model' | 0 |
| SKIP | build_txt2img | env lacks model: ckpt_name= | 17 |
| SKIP | build_upscale | env lacks model: model_name= | 37 |
| SKIP | build_upscale_blend | needs extra args: build_upscale_blend() missing 2 required positional arguments: 'model_a_name' and 'model_b_name' | 0 |
| SKIP | build_video_reactor | needs extra args: build_video_reactor() missing 1 required positional argument: 'face_models' | 0 |
| PASS | build_video_upscale | 7 nodes, queued ok | 40 |
| FAIL | build_wan22_t2v | KeyError: 'high_model' | 0 |
| FAIL | build_wan_flf | KeyError: 'high_model' | 0 |
| FAIL | build_wan_video | KeyError: 'high_model' | 0 |
| SKIP | build_wan_video_blockswap | needs extra args: build_wan_video_blockswap() missing 3 required positional arguments: 'wan_model', 't5_model', and 'v | 0 |
| PASS | build_wavespeed_upscale | 3 nodes, queued ok | 42 |
