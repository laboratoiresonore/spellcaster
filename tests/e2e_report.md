# Spellcaster E2E Audit

_Ran at_: 2026-04-19 17:46:26
_Totals_: **116** pass · **0** fail · **0** warn · **8** skip

## Guild endpoints

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | /api/characters | size=34 | 3 |
| PASS | /api/comfy_status | 2 keys | 25 |
| PASS | /api/llm_status | 8 keys | 2 |
| PASS | /api/antennas | 3 keys | 0 |
| PASS | /api/interfaces | size=1 | 1 |
| PASS | /api/app_control/config | 2 keys | 4 |
| PASS | /api/config | 12 keys | 2 |
| PASS | /api/assets?limit=5 | size=2 | 1 |
| PASS | /api/setup/state | size=9 | 4193 |
| PASS | /api/setup/status | 16 keys | 5 |
| PASS | /api/setup/comfyui-status | 4 keys | 3618 |
| PASS | /api/spellcaster/state | size=6 | 5675 |
| PASS | /api/video/presets | 1 keys | 2 |
| PASS | /api/video/health | 9 keys | 8206 |
| PASS | /api/video/shots | size=2 | 9 |
| PASS | /api/video/queue/status | size=6 | 5 |
| PASS | /api/spellcaster/network/survey | size=3 | 8 |
| PASS | /api/sillytavern_status | 2 keys | 2033 |
| PASS | /api/signal_bridge_status | size=2 | 17 |

## Scaffolds — studio wizards

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | system_prompt[studio_spellcaster] | 26438 chars | 4878 |
| PASS | llm_turn[studio_spellcaster] | "*   img2img…" | 5852 |
| PASS | system_prompt[studio_imaginus] | 1850 chars | 4531 |
| PASS | llm_turn[studio_imaginus] | "```json…" | 1243 |
| PASS | system_prompt[studio_transmutex] | 2604 chars | 4 |
| PASS | llm_turn[studio_transmutex] | "```json…" | 3011 |
| PASS | system_prompt[studio_masquerade] | 2016 chars | 4 |
| PASS | llm_turn[studio_masquerade] | "```json…" | 4307 |
| PASS | system_prompt[studio_restorix] | 1768 chars | 4 |
| PASS | llm_turn[studio_restorix] | "```json…" | 2896 |
| PASS | system_prompt[studio_erasure] | 2184 chars | 6 |
| PASS | llm_turn[studio_erasure] | "```json…" | 4665 |
| PASS | system_prompt[studio_videomancer] | 1772 chars | 4 |
| PASS | llm_turn[studio_videomancer] | "```json…" | 4512 |
| PASS | system_prompt[studio_cinematic] | 9063 chars | 4 |
| PASS | llm_turn[studio_cinematic] | "1.  Dramatic Reveal (3 steps)…" | 6196 |
| PASS | system_prompt[studio_studiocraft] | 8742 chars | 4 |
| PASS | llm_turn[studio_studiocraft] | "Darling, let's see what delights await!…" | 4767 |
| PASS | system_prompt[comfyui_A-Flux_Flux2_flux-2-klein-9b_safetensors] (per-model spot) | 1802 chars | 4 |

## Wizard naming coverage

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | studio wizards | 9 core wizards present | 0 |
| PASS | per-model wizards | all 23 wizards have human names | 0 |

## build_* functions (compile + validate)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | build_color_match | 4 nodes, queued ok | 184 |
| PASS | build_colorize | 11 nodes, queued ok | 182 |
| PASS | build_controlnet_gen | 11 nodes, queued ok | 232 |
| PASS | build_ddcolor | 3 nodes, queued ok | 74 |
| PASS | build_detail_hallucinate | 10 nodes, queued ok | 118 |
| SKIP | build_face_restore | env lacks model: model= | 208 |
| PASS | build_faceid_img2img | 11 nodes, queued ok | 274 |
| PASS | build_faceswap | 6 nodes, queued ok | 107 |
| SKIP | build_faceswap_model | needs extra args: build_faceswap_model() missing 1 required positional argument: 'face_model_name' | 0 |
| PASS | build_faceswap_mtb | 6 nodes, queued ok | 318 |
| PASS | build_frame_assembly | 2 nodes, queued ok | 196 |
| PASS | build_generate_anything | 9 nodes, queued ok | 126 |
| PASS | build_iclight | 10 nodes, queued ok | 194 |
| PASS | build_img2img | 8 nodes, queued ok | 98 |
| PASS | build_inpaint | 16 nodes, queued ok | 311 |
| PASS | build_klein_auto_inpaint | 24 nodes, queued ok | 163 |
| PASS | build_klein_batch_variations | 24 nodes, queued ok | 244 |
| PASS | build_klein_blend | 23 nodes, queued ok | 144 |
| PASS | build_klein_color_match | 4 nodes, queued ok | 207 |
| PASS | build_klein_detail | 12 nodes, queued ok | 221 |
| PASS | build_klein_face_detail | 9 nodes, queued ok | 195 |
| PASS | build_klein_generate_object | 23 nodes, queued ok | 192 |
| PASS | build_klein_headswap | 25 nodes, queued ok | 162 |
| PASS | build_klein_img2img | 21 nodes, queued ok | 226 |
| PASS | build_klein_img2img_ref | 24 nodes, queued ok | 198 |
| PASS | build_klein_inpaint | 22 nodes, queued ok | 201 |
| PASS | build_klein_refine | 27 nodes, queued ok | 94 |
| PASS | build_klein_repose | 21 nodes, queued ok | 99 |
| PASS | build_klein_sam3_inpaint | 22 nodes, queued ok | 118 |
| PASS | build_klein_scene_img2img | 19 nodes, queued ok | 138 |
| PASS | build_klein_virtual_tryon | 23 nodes, queued ok | 99 |
| PASS | build_lama_remove | 5 nodes, queued ok | 56 |
| PASS | build_layer_blend | 4 nodes, queued ok | 203 |
| PASS | build_ltx_video | 15 nodes, queued ok | 211 |
| SKIP | build_lut | needs extra args: build_lut() missing 1 required positional argument: 'lut_name' | 0 |
| PASS | build_magic_eraser | 5 nodes, queued ok | 85 |
| PASS | build_normal_map | 3 nodes, queued ok | 195 |
| PASS | build_outpaint | 10 nodes, queued ok | 269 |
| SKIP | build_photo_restore | needs extra args: build_photo_restore() missing 1 required positional argument: 'face_model' | 0 |
| PASS | build_photobooth | 25 nodes, queued ok | 167 |
| PASS | build_pulid_flux | 14 nodes, queued ok | 134 |
| SKIP | build_qwen_edit | env lacks model: clip_name=umt5-xxl-encoder-Q3_K_S.gguf | 238 |
| PASS | build_rembg | 3 nodes, queued ok | 72 |
| PASS | build_rembg_birefnet | 3 nodes, queued ok | 197 |
| PASS | build_sam3_extract | 3 nodes, queued ok | 203 |
| SKIP | build_sam3_mask | needs extra args: build_sam3_mask() missing 2 required positional arguments: 'nf' and 'image_ref' | 0 |
| PASS | build_sam3_segment | 5 nodes, queued ok | 99 |
| PASS | build_save_face_model | 4 nodes, queued ok | 125 |
| PASS | build_seedv2r | 10 nodes, queued ok | 220 |
| PASS | build_seedvr2_video_upscale | 6 nodes, queued ok | 181 |
| PASS | build_style_transfer | 11 nodes, queued ok | 124 |
| PASS | build_supir | 7 nodes, queued ok | 247 |
| PASS | build_txt2img | 7 nodes, queued ok | 215 |
| PASS | build_upscale | 4 nodes, queued ok | 167 |
| PASS | build_upscale_blend | 7 nodes, queued ok | 210 |
| SKIP | build_video_reactor | needs extra args: build_video_reactor() missing 1 required positional argument: 'face_models' | 0 |
| PASS | build_video_upscale | 7 nodes, queued ok | 137 |
| PASS | build_wan22_t2v | 15 nodes, queued ok | 225 |
| PASS | build_wan_flf | 31 nodes, queued ok | 293 |
| PASS | build_wan_video | 28 nodes, queued ok | 280 |
| SKIP | build_wan_video_blockswap | needs extra args: build_wan_video_blockswap() missing 3 required positional arguments: 'wan_model', 't5_model', and 'v | 0 |
| PASS | build_wavespeed_upscale | 3 nodes, queued ok | 293 |

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
| PASS | detect_wan_preset (live) | high=Wan\2.2\Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_  vae=wan_2.1_vae.safetensors | 674 |
| PASS | detect_ltx_preset (live) | unet=LTX\ltx-2.3-22b-dev-Q4_K_M.gguf  te=gemma_3_12B_it_fp4_mixed.safet | 269 |

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
| PASS | event_bus.emit | published | 4 |
| PASS | /api/antennas registry | 0 registered, 0 online | 0 |
