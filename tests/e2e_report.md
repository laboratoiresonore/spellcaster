# Spellcaster E2E Audit

_Ran at_: 2026-04-19 17:24:20
_Totals_: **71** pass · **4** fail · **0** warn · **39** skip

## Guild endpoints

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | /api/characters | size=34 | 5 |
| PASS | /api/comfy_status | 2 keys | 23 |
| PASS | /api/llm_status | 8 keys | 0 |
| PASS | /api/antennas | 3 keys | 2 |
| PASS | /api/interfaces | size=1 | 18 |
| PASS | /api/app_control/config | 2 keys | 5 |
| PASS | /api/config | 12 keys | 1 |
| PASS | /api/assets?limit=5 | size=2 | 2 |
| PASS | /api/setup/state | size=9 | 4053 |
| PASS | /api/setup/status | 16 keys | 3 |
| PASS | /api/setup/comfyui-status | 4 keys | 5089 |
| PASS | /api/spellcaster/state | size=6 | 5594 |
| PASS | /api/video/presets | 1 keys | 3 |
| PASS | /api/video/health | 9 keys | 8197 |
| PASS | /api/video/shots | size=2 | 3 |
| PASS | /api/video/queue/status | size=6 | 1 |
| PASS | /api/spellcaster/network/survey | size=3 | 2 |
| PASS | /api/sillytavern_status | 2 keys | 2027 |
| PASS | /api/signal_bridge_status | size=2 | 5 |

## Scaffolds — studio wizards

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | system_prompt[studio_spellcaster] | 26438 chars | 4588 |
| PASS | system_prompt[studio_imaginus] | 1850 chars | 4059 |
| PASS | system_prompt[studio_transmutex] | 2402 chars | 4 |
| PASS | system_prompt[studio_masquerade] | 1813 chars | 1 |
| PASS | system_prompt[studio_restorix] | 1567 chars | 2 |
| PASS | system_prompt[studio_erasure] | 1982 chars | 3 |
| PASS | system_prompt[studio_videomancer] | 1772 chars | 2 |
| PASS | system_prompt[studio_cinematic] | 9063 chars | 3 |
| PASS | system_prompt[studio_studiocraft] | 8742 chars | 1 |
| PASS | system_prompt[comfyui_A-Flux_Flux2_flux-2-klein-9b_safetensors] (per-model spot) | 1802 chars | 2 |

## Wizard naming coverage

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | studio wizards | 9 core wizards present | 0 |
| PASS | per-model wizards | all 23 wizards have human names | 0 |

## build_* functions (compile + validate)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| SKIP | build_color_match | needs extra args: build_color_match() missing 2 required positional arguments: 'source_filename' and 'reference_filena | 0 |
| SKIP | build_colorize | needs extra args: build_colorize() missing 2 required positional arguments: 'controlnet_strength' and 'denoise' | 0 |
| SKIP | build_controlnet_gen | needs extra args: build_controlnet_gen() missing 6 required positional arguments: 'preprocessor_type', 'controlnet_mod | 0 |
| PASS | build_ddcolor | 3 nodes, queued ok | 50 |
| SKIP | build_detail_hallucinate | needs extra args: build_detail_hallucinate() missing 3 required positional arguments: 'upscale_model', 'denoise', and  | 0 |
| SKIP | build_face_restore | needs extra args: build_face_restore() missing 4 required positional arguments: 'model_name', 'facedetection', 'visibi | 0 |
| SKIP | build_faceid_img2img | needs extra args: build_faceid_img2img() missing 2 required positional arguments: 'target_filename' and 'face_ref_file | 0 |
| SKIP | build_faceswap | needs extra args: build_faceswap() missing 2 required positional arguments: 'target_filename' and 'source_filename' | 0 |
| SKIP | build_faceswap_model | needs extra args: build_faceswap_model() missing 2 required positional arguments: 'target_filename' and 'face_model_na | 0 |
| SKIP | build_faceswap_mtb | needs extra args: build_faceswap_mtb() missing 2 required positional arguments: 'target_filename' and 'source_filename | 0 |
| SKIP | build_frame_assembly | needs extra args: build_frame_assembly() missing 1 required positional argument: 'frame_filenames' | 0 |
| PASS | build_generate_anything | 9 nodes, queued ok | 20 |
| FAIL | build_iclight | ComfyUI 400: {"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation", "details": "", "extra_info": {}}, "node_errors": {"2": {"e | 42 |
| PASS | build_img2img | 8 nodes, queued ok | 34 |
| FAIL | build_inpaint | ComfyUI 400: {"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation", "details": "", "extra_info": {}}, "node_errors": {"5": {"e | 80 |
| PASS | build_klein_auto_inpaint | 24 nodes, queued ok | 34 |
| SKIP | build_klein_batch_variations | needs extra args: build_klein_batch_variations() missing 1 required positional argument: 'klein_model_key' | 0 |
| SKIP | build_klein_blend | needs extra args: build_klein_blend() missing 2 required positional arguments: 'fg_filename' and 'bg_filename' | 0 |
| SKIP | build_klein_color_match | needs extra args: build_klein_color_match() missing 2 required positional arguments: 'target_filename' and 'reference_ | 0 |
| SKIP | build_klein_detail | needs extra args: build_klein_detail() missing 1 required positional argument: 'preset_key' | 0 |
| PASS | build_klein_face_detail | 9 nodes, queued ok | 55 |
| SKIP | build_klein_generate_object | needs extra args: build_klein_generate_object() missing 1 required positional argument: 'scene_filename' | 0 |
| SKIP | build_klein_headswap | needs extra args: build_klein_headswap() missing 3 required positional arguments: 'target_filename', 'source_filename' | 0 |
| SKIP | build_klein_img2img | needs extra args: build_klein_img2img() missing 1 required positional argument: 'klein_model_key' | 0 |
| SKIP | build_klein_img2img_ref | needs extra args: build_klein_img2img_ref() missing 2 required positional arguments: 'ref_filename' and 'klein_model_k | 0 |
| FAIL | build_klein_inpaint | ValueError: build_klein_inpaint requires mask_filename, sam3_prompt, or use_solid_mask | 0 |
| SKIP | build_klein_refine | needs extra args: build_klein_refine() missing 1 required positional argument: 'klein_model_key' | 0 |
| SKIP | build_klein_repose | needs extra args: build_klein_repose() missing 1 required positional argument: 'klein_model_key' | 0 |
| PASS | build_klein_sam3_inpaint | 22 nodes, queued ok | 64 |
| PASS | build_klein_scene_img2img | 19 nodes, queued ok | 46 |
| SKIP | build_klein_virtual_tryon | needs extra args: build_klein_virtual_tryon() missing 2 required positional arguments: 'face_filename' and 'outfit_fil | 0 |
| FAIL | build_lama_remove | ValueError: build_lama_remove requires either mask_filename or sam3_prompt | 0 |
| SKIP | build_layer_blend | needs extra args: build_layer_blend() missing 2 required positional arguments: 'image_a_filename' and 'image_b_filenam | 0 |
| PASS | build_ltx_video | 15 nodes, queued ok | 27 |
| SKIP | build_lut | needs extra args: build_lut() missing 2 required positional arguments: 'lut_name' and 'strength' | 0 |
| PASS | build_magic_eraser | 5 nodes, queued ok | 38 |
| PASS | build_normal_map | 3 nodes, queued ok | 43 |
| SKIP | build_outpaint | needs extra args: build_outpaint() missing 5 required positional arguments: 'left', 'top', 'right', 'bottom', and 'fea | 0 |
| SKIP | build_photo_restore | needs extra args: build_photo_restore() missing 8 required positional arguments: 'upscale_model', 'face_model', 'faced | 0 |
| SKIP | build_photobooth | needs extra args: build_photobooth() missing 1 required positional argument: 'ref_filename' | 0 |
| SKIP | build_pulid_flux | needs extra args: build_pulid_flux() missing 2 required positional arguments: 'target_filename' and 'face_ref_filename | 0 |
| SKIP | build_qwen_edit | needs extra args: build_qwen_edit() missing 3 required positional arguments: 'unet_name', 'clip_name', and 'vae_name' | 0 |
| PASS | build_rembg | 3 nodes, queued ok | 55 |
| PASS | build_rembg_birefnet | 3 nodes, queued ok | 39 |
| PASS | build_sam3_extract | 3 nodes, queued ok | 62 |
| SKIP | build_sam3_mask | needs extra args: build_sam3_mask() missing 2 required positional arguments: 'nf' and 'image_ref' | 0 |
| PASS | build_sam3_segment | 5 nodes, queued ok | 53 |
| SKIP | build_save_face_model | needs extra args: build_save_face_model() missing 2 required positional arguments: 'source_filename' and 'model_name' | 0 |
| SKIP | build_seedv2r | needs extra args: build_seedv2r() missing 7 required positional arguments: 'upscale_model', 'denoise', 'cfg', 'steps', | 0 |
| SKIP | build_seedvr2_video_upscale | needs extra args: build_seedvr2_video_upscale() missing 1 required positional argument: 'video_name' | 0 |
| SKIP | build_style_transfer | needs extra args: build_style_transfer() missing 2 required positional arguments: 'target_filename' and 'style_ref_fil | 0 |
| SKIP | build_supir | needs extra args: build_supir() missing 2 required positional arguments: 'supir_model' and 'sdxl_model' | 0 |
| PASS | build_txt2img | 7 nodes, queued ok | 25 |
| SKIP | build_upscale | needs extra args: build_upscale() missing 1 required positional argument: 'model_name' | 0 |
| SKIP | build_upscale_blend | needs extra args: build_upscale_blend() missing 2 required positional arguments: 'model_a_name' and 'model_b_name' | 0 |
| SKIP | build_video_reactor | needs extra args: build_video_reactor() missing 2 required positional arguments: 'video_name' and 'face_models' | 0 |
| SKIP | build_video_upscale | needs extra args: build_video_upscale() missing 1 required positional argument: 'video_name' | 0 |
| PASS | build_wan22_t2v | 15 nodes, queued ok | 21 |
| PASS | build_wan_flf | 31 nodes, queued ok | 65 |
| PASS | build_wan_video | 28 nodes, queued ok | 53 |
| SKIP | (cap reached at 60) | 2 untested | 0 |

## Cross-plugin scaffold manifest

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | totals | total=204, canonical=75, duplicate=6, unknown=10 | 0 |
| PASS | plugin[Wizard Guild] | methods=0 | 0 |
| PASS | plugin[GIMP Plugin] | methods=0 | 0 |
| PASS | plugin[Darktable Plugin] | methods=0 | 0 |
| PASS | plugin[DaVinci Resolve Plugin] | methods=0 | 0 |
| PASS | plugin[SillyTavern Plugin] | methods=0 | 0 |

## Video canon (spellcaster_core.video_presets)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | wan_turbo_kwargs | turbo={}  full={'steps': 30, 'cfg': 3.5, 'second_step': 15} | 0 |
| PASS | ltx_mode_kwargs | {'distilled': {'distilled': True, 'two_stage': False}, 'full': {'distilled': False, 'two_stage': False}, 'two_stage': {'distilled': False, 'two_stage': True}, 'i2v': {'distilled': True, 'two_stage': False}} | 0 |
| PASS | pick_wan_vae | 14B→wan_2.1_vae.safetensors  5B→wan2.2_vae.safetensors | 0 |
| PASS | detect_wan_preset (live) | high=Wan\2.2\Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_  vae=wan_2.1_vae.safetensors | 140 |
| PASS | detect_ltx_preset (live) | unet=LTX\ltx-2.3-22b-dev-Q4_K_M.gguf  te=gemma_3_12B_it_fp4_mixed.safet | 171 |

## Model prompt profiles (spellcaster_core.model_prompt_profiles)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | profile[juggernautXL_v9Rundiffusionphoto2.safetensors] | arch=sdxl (expected sdxl) | 0 |
| PASS | profile[gonzalomoZpop_v30AIO.safetensors] | arch=zit (expected zit) | 0 |
| PASS | profile[sloppyMessyMix_sloppyMessyMixV1.safetensors] | arch=illustrious (expected illustrious) | 0 |
| PASS | profile[FLUX1 Dev fp8.safetensors] | arch=flux1dev (expected flux1dev) | 0 |
| PASS | profile[Flux\FLUX1 Dev fp8.safetensors] | arch=flux1dev (expected flux1dev) | 0 |
| PASS | profile[flux-2-klein-9b.safetensors] | arch=flux2klein (expected flux2klein) | 0 |
| PASS | profile[modernDisneyXL_v3.safetensors] | arch=sdxl (expected sdxl) | 0 |
| PASS | apply_profile(juggernautXL) | pos[:60]='masterpiece, (photorealistic:1.3), raw photo, highly detaile' | 0 |

## Cross-interface backbone

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | /api/interfaces snapshot | 1 entries, 0 online | 0 |
| PASS | event_bus.emit | published | 12 |
| PASS | /api/antennas registry | 0 registered, 0 online | 0 |
