# Spellcaster E2E Audit

_Ran at_: 2026-04-24 03:38:14
_Totals_: **212** pass · **0** fail · **5** warn · **13** skip

## Guild endpoints

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | /api/characters | size=34 | 26 |
| PASS | /api/comfy_status | 2 keys | 44 |
| PASS | /api/llm_status | 8 keys | 1 |
| PASS | /api/antennas | 3 keys | 2 |
| PASS | /api/interfaces | size=1 | 2 |
| PASS | /api/app_control/config | 2 keys | 57 |
| PASS | /api/config | 12 keys | 1 |
| PASS | /api/assets?limit=5 | size=2 | 12 |
| PASS | /api/setup/state | size=9 | 3506 |
| PASS | /api/setup/status | 16 keys | 23 |
| PASS | /api/setup/comfyui-status | 4 keys | 2177 |
| PASS | /api/spellcaster/state | size=6 | 4656 |
| PASS | /api/video/presets | 1 keys | 2 |
| PASS | /api/video/health | 9 keys | 9548 |
| PASS | /api/video/shots | size=2 | 2 |
| PASS | /api/video/queue/status | size=6 | 2 |
| PASS | /api/spellcaster/network/survey | size=3 | 64 |
| PASS | /api/sillytavern_status | 2 keys | 15 |
| PASS | /api/signal_bridge_status | size=2 | 2052 |

## Scaffolds — studio wizards

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | system_prompt[studio_spellcaster] | 26585 chars | 3675 |
| PASS | system_prompt[studio_imaginus] | 1855 chars | 3126 |
| PASS | system_prompt[studio_transmutex] | 2407 chars | 18 |
| PASS | system_prompt[studio_masquerade] | 1818 chars | 15 |
| PASS | system_prompt[studio_restorix] | 1572 chars | 14 |
| PASS | system_prompt[studio_erasure] | 1987 chars | 14 |
| PASS | system_prompt[studio_videomancer] | 1777 chars | 16 |
| PASS | system_prompt[studio_cinematic] | 9078 chars | 2 |
| PASS | system_prompt[studio_studiocraft] | 8757 chars | 2 |
| PASS | system_prompt[comfyui_A-Flux_Flux2_flux-2-klein-9b_safetensors] (per-model spot) | 1807 chars | 3 |

## Wizard naming coverage

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | studio wizards | 9 core wizards present | 0 |
| SKIP | per-model wizards | no summoned per-model wizards  (23 un-summoned skipped) | 0 |

## build_* functions (compile + validate)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | build_color_match | 4 nodes, queued ok | 63 |
| PASS | build_colorize | 12 nodes, queued ok | 62 |
| PASS | build_controlnet_gen | 12 nodes, queued ok | 46 |
| PASS | build_ddcolor | 3 nodes, queued ok | 48 |
| PASS | build_detail_hallucinate | 11 nodes, queued ok | 55 |
| SKIP | build_face_restore | faceswap family skipped (TRT crash risk); set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable | 0 |
| PASS | build_faceid_img2img | 12 nodes, queued ok | 44 |
| SKIP | build_faceswap | faceswap family skipped (TRT crash risk); set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable | 0 |
| SKIP | build_faceswap_model | faceswap family skipped (TRT crash risk); set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable | 0 |
| SKIP | build_faceswap_mtb | faceswap family skipped (TRT crash risk); set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable | 0 |
| PASS | build_frame_assembly | 2 nodes, queued ok | 32 |
| PASS | build_generate_anything | 10 nodes, queued ok | 58 |
| PASS | build_iclight | 10 nodes, queued ok | 55 |
| PASS | build_img2img | 9 nodes, queued ok | 56 |
| PASS | build_inpaint | 19 nodes, queued ok | 67 |
| PASS | build_klein_auto_inpaint | 24 nodes, queued ok | 40 |
| PASS | build_klein_batch_variations | 24 nodes, queued ok | 51 |
| PASS | build_klein_blend | 23 nodes, queued ok | 44 |
| PASS | build_klein_color_match | 4 nodes, queued ok | 47 |
| PASS | build_klein_detail | 12 nodes, queued ok | 62 |
| PASS | build_klein_face_detail | 9 nodes, queued ok | 25 |
| PASS | build_klein_generate_object | 23 nodes, queued ok | 45 |
| SKIP | build_klein_headswap | faceswap family skipped (TRT crash risk); set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable | 0 |
| PASS | build_klein_img2img | 21 nodes, queued ok | 65 |
| PASS | build_klein_img2img_ref | 24 nodes, queued ok | 41 |
| PASS | build_klein_inpaint | 22 nodes, queued ok | 41 |
| PASS | build_klein_refine | 27 nodes, queued ok | 38 |
| PASS | build_klein_repose | 21 nodes, queued ok | 45 |
| PASS | build_klein_sam3_inpaint | 22 nodes, queued ok | 46 |
| PASS | build_klein_scene_img2img | 19 nodes, queued ok | 49 |
| PASS | build_klein_virtual_tryon | 23 nodes, queued ok | 76 |
| PASS | build_lama_remove | 5 nodes, queued ok | 75 |
| PASS | build_layer_blend | 4 nodes, queued ok | 54 |
| PASS | build_ltx_video | 15 nodes, queued ok | 34 |
| SKIP | build_lut | needs extra args: build_lut() missing 1 required positional argument: 'lut_name' | 0 |
| PASS | build_magic_eraser | 5 nodes, queued ok | 48 |
| PASS | build_normal_map | 3 nodes, queued ok | 47 |
| PASS | build_outpaint | 12 nodes, queued ok | 30 |
| SKIP | build_photo_restore | faceswap family skipped (TRT crash risk); set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable | 0 |
| SKIP | build_photobooth | faceswap family skipped (TRT crash risk); set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable | 0 |
| PASS | build_pulid_flux | 14 nodes, queued ok | 49 |
| SKIP | build_qwen_edit | env lacks model: clip_name=umt5-xxl-encoder-Q3_K_S.gguf | 33 |
| PASS | build_rembg | 3 nodes, queued ok | 53 |
| PASS | build_rembg_birefnet | 3 nodes, queued ok | 37 |
| PASS | build_sam3_extract | 3 nodes, queued ok | 35 |
| SKIP | build_sam3_mask | needs extra args: build_sam3_mask() missing 2 required positional arguments: 'nf' and 'image_ref' | 0 |
| PASS | build_sam3_segment | 5 nodes, queued ok | 54 |
| PASS | build_save_face_model | 4 nodes, queued ok | 51 |
| PASS | build_seedv2r | 11 nodes, queued ok | 51 |
| PASS | build_seedvr2_video_upscale | 6 nodes, queued ok | 35 |
| PASS | build_style_transfer | 12 nodes, queued ok | 48 |
| PASS | build_supir | 7 nodes, queued ok | 56 |
| PASS | build_txt2img | 8 nodes, queued ok | 41 |
| PASS | build_upscale | 4 nodes, queued ok | 62 |
| PASS | build_upscale_blend | 7 nodes, queued ok | 67 |
| SKIP | build_video_reactor | faceswap family skipped (TRT crash risk); set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable | 0 |
| PASS | build_video_upscale | 7 nodes, queued ok | 46 |
| PASS | build_wan22_t2v | 15 nodes, queued ok | 36 |
| PASS | build_wan_flf | 31 nodes, queued ok | 55 |
| PASS | build_wan_video | 28 nodes, queued ok | 66 |
| SKIP | build_wan_video_blockswap | needs extra args: build_wan_video_blockswap() missing 3 required positional arguments: 'wan_model', 't5_model', and 'v | 0 |
| PASS | build_wavespeed_upscale | 3 nodes, queued ok | 67 |

## Cross-plugin scaffold manifest

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | totals | total=185, canonical=83, duplicate=0, unknown=11 | 0 |
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
| PASS | detect_wan_preset (live) | high=Wan\2.2\Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_  vae=wan_2.1_vae.safetensors | 201 |
| PASS | detect_ltx_preset (live) | unet=LTX\ltx-2.3-22b-dev-Q4_K_M.gguf  te=gemma_3_12B_it_fp4_mixed.safet | 206 |

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
| PASS | event_bus.emit | published | 14 |
| PASS | /api/antennas registry | 0 registered, 0 online | 0 |

## Presence broker (ComfyUI)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | GET /list (baseline) | 0 peers | 37 |
| PASS | register rejects invalid key | HTTP 400 | 0 |
| PASS | multi-host coexistence | e2e_audit@audit-hostA + e2e_audit@audit-hostB | 0 |
| PASS | heartbeat refresh | age_s=0.09 | 0 |
| PASS | GET /list sees both synthetic peers | +2 peers | 0 |
| PASS | unregister audit-hostA | HTTP 200 | 0 |
| PASS | unregister audit-hostB | HTTP 200 | 0 |

## Blob bus (ComfyUI)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | POST /blob/put | hash=3036fa62479c size=37 | 49 |
| PASS | GET /blob/<hash> roundtrip | 37B exact match | 0 |
| PASS | dedup (same bytes → same hash) | hash stable | 0 |
| PASS | GET /blob/list | 1 live blobs incl. ours | 0 |
| PASS | GET /blob/<unknown> | HTTP 404 | 0 |

## Error extraction

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | import dispatch.py | module has 9 public names | 0 |
| PASS | extract[classic execution_error.exception_message] | detail="[VAEEncode] RuntimeError: Kernel size can't be greater" | 0 |
| PASS | extract[execution_error with only 'message' field (non-canonical)] | detail='[node 42] node failed' | 0 |
| PASS | extract[error type msg without exception_message] | detail='preflight rejected' | 0 |
| PASS | extract[execution_interrupted (no exception)] | detail='no recognised error message; status={"status_str": "error", ' | 0 |
| PASS | extract[empty messages list] | detail='no recognised error message; status={"status_str": "error", ' | 0 |
| PASS | extract[malformed status] | detail='malformed status: NoneType' | 0 |
| PASS | extract[status is a string] | detail='malformed status: str' | 0 |
| PASS | extract[node_type prefix injection] | detail='[KSampler] OOM' | 0 |
| PASS | has_usable_outputs[None entry] | False | 0 |
| PASS | has_usable_outputs[empty dict] | False | 0 |
| PASS | has_usable_outputs[no outputs key] | False | 0 |
| PASS | has_usable_outputs[empty outputs] | False | 0 |
| PASS | has_usable_outputs[outputs with no filenames] | False | 0 |
| PASS | has_usable_outputs[outputs with images] | True | 0 |
| PASS | has_usable_outputs[outputs with gifs] | True | 0 |
| PASS | has_usable_outputs[outputs with videos] | True | 0 |
| PASS | has_usable_outputs[outputs malformed] | False | 0 |

## Event schema

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | import events.py | registry has 10 explicit kinds | 0 |
| PASS | _EventBase round-trip | kind= | 0 |
| PASS | AssetCreated round-trip | kind=*.asset.created | 0 |
| PASS | AssetUploaded round-trip | kind=*.asset.uploaded | 0 |
| PASS | GenerationFinished round-trip | kind=*.generation.finished | 0 |
| PASS | AssetSend round-trip | kind=*.asset.send | 0 |
| PASS | ClipImport round-trip | kind=resolve.clip.import | 0 |
| PASS | PresenceHeartbeat round-trip | kind=*.presence.heartbeat | 0 |
| PASS | GuildSelfUpdateResult round-trip | kind=guild.self_update.result | 0 |
| PASS | GuildSelfUpdateError round-trip | kind=guild.self_update.error | 0 |
| PASS | PlayheadGrab round-trip | kind=resolve.playhead.grab | 0 |
| PASS | PlayheadSendToPeer round-trip | kind=resolve.playhead.send_to_peer | 0 |
| PASS | TimelineImport round-trip | kind=resolve.timeline.import | 0 |
| PASS | PlayheadReady round-trip | kind=resolve.playhead.ready | 0 |
| PASS | TimelineImported round-trip | kind=resolve.timeline.imported | 0 |
| PASS | SendToPeerDone round-trip | kind=resolve.send_to_peer.done | 0 |
| PASS | DispatchPredicted round-trip | kind=*.dispatch.predicted | 0 |
| PASS | DispatchCompleted round-trip | kind=*.dispatch.completed | 0 |
| PASS | SpeedCoachSuggestion round-trip | kind=*.speedcoach.suggestion | 0 |
| PASS | DriftDetected round-trip | kind=spellcaster.drift.detected | 0 |
| PASS | RatingSubmitted round-trip | kind=*.rating.submitted | 0 |
| PASS | publish_event() wildcard expansion | e2e_audit.asset.send | 0 |

## SillyTavern routes

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | ST preflight | reachable at http://127.0.0.1:8000 | 0 |
| WARN | GET /peers | route not registered (older ST plugin build?) | 0 |
| WARN | GET /models | route not registered (older ST plugin build?) | 0 |
| WARN | GET /capabilities | route not registered (older ST plugin build?) | 0 |
| WARN | GET /cross/inbox | route not registered (older ST plugin build?) | 0 |
| WARN | POST /settings | HTTP 403 | 0 |

## GuildClient (Resolve shared/)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | import + construct | base_url=http://127.0.0.1:7777 | 0 |
| PASS | config() | no exception | 14 |
| PASS | create_shot() | no exception | 321 |
| PASS | is_reachable() | no exception | 2 |
| PASS | list_presets() | no exception | 1 |
| PASS | list_shots() | no exception | 1 |
| PASS | open_event_stream() | no exception | 219 |
| PASS | queue_status() | no exception | 2 |
| PASS | render_all_drafts() | no exception | 4262 |
| PASS | video_health() | no exception | 8235 |

## ControlNet model coverage

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | server CN inventory | 20 CN files visible | 0 |
| PASS | parse CONTROLNET_GUIDE_MODES | 14 modes defined | 0 |
| PASS | every mode × arch resolves to an installed file | 14 modes verified via resolver | 0 |

## Coverage inventory

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | spellcaster_core | 44/509 referenced (9%) | 0 |
| PASS | comfyui_pack | 44/519 referenced (8%) | 0 |
| PASS | gimp_plugin | 45/595 referenced (8%) | 0 |
| PASS | resolve_shared | 2/42 referenced (5%) | 0 |
| PASS | resolve_bridge | 1/16 referenced (6%) | 0 |
| PASS | guild_tavern | 1/28 referenced (4%) | 0 |
| PASS | TOTAL across all surfaces | 137/1709 public fns referenced (8%) | 0 |

## Upload cache & privacy

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | CACHE_PREFIXES ∩ OWNED_PREFIXES is empty |  | 0 |
| PASS | cleanup_inputs SKIPS sc_cache_* from workflow | wiped=[] | 0 |
| PASS | cleanup_inputs WIPES gimp_* from workflow | wiped=['gimp_abc.png', 'gimp_123.png'] | 0 |
| PASS | cleanup_inputs server-scan exempts sc_cache_* | missing=set(), extra=set() | 0 |
| PASS | purge_cache targets ONLY CACHE_PREFIXES | wiped=['sc_cache_abc.png'] | 0 |
| PASS | cleanup_outputs wipes all result files | wiped=['result_1.png', 'sc_cache_should_still_go_if_passed_here.png'] | 0 |
| PASS | section complete |  | 608 |

## Blank/uniform classifiers

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | blank: empty bytes |  | 0 |
| PASS | blank: garbage bytes |  | 0 |
| PASS | blank: RGBA alpha=0 (blank) |  | 0 |
| PASS | blank: RGBA alpha=255 (opaque) |  | 0 |
| PASS | blank: RGB (no alpha channel) |  | 0 |
| PASS | blank: LA alpha=0 |  | 0 |
| PASS | blank: LA alpha=255 |  | 0 |
| PASS | uniform: all-black L |  | 0 |
| PASS | uniform: all-white L |  | 0 |
| PASS | uniform: mixed L |  | 0 |
| PASS | uniform: empty |  | 0 |
| PASS | section complete |  | 3747 |

## IC-Light normal-map routing

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | normal-map path does NOT load iclight_sd15_fbc |  | 0 |
| PASS | normal-map path loads ControlNetLoader | classes=['CLIPTextEncode', 'CheckpointLoaderSimple', 'ControlNetApplyAdvanced', 'ControlNetLoader', 'ICLightConditioning', 'KSampler', 'LoadAndApplyICLightUnet', 'LoadImage', 'SaveImage', 'VAEDecode', 'VAEEncode'] | 0 |
| PASS | normal-map path applies ControlNetApplyAdvanced |  | 0 |
| PASS | CN model is normalbae (surface-aware) | cn_names=['control_v11p_sd15_normalbae.pth'] | 0 |
| PASS | normal map loaded as image (not latent) |  | 0 |
| PASS | no-normal path does NOT include ControlNet | classes=['CLIPTextEncode', 'CheckpointLoaderSimple', 'ICLightConditioning', 'KSampler', 'LoadAndApplyICLightUnet', 'LoadImage', 'SaveImage', 'VAEDecode', 'VAEEncode'] | 0 |
| PASS | section complete |  | 0 |

## Plugin surface (AST)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | plugin parses |  | 0 |
| PASS | every _PROC_FEATURES key has menu_map entry (97 procs) |  | 0 |
| PASS | every _PROC_FEATURES key has _menu_paths entry |  | 0 |
| PASS | no orphan menu_map keys (every menu has a feature) |  | 0 |
| PASS | no orphan _menu_paths keys |  | 0 |
| PASS | _apply_mask_mode arity (5 or 6) across 58 call sites |  | 0 |
| PASS | every _run_* Gimp.message-ing except prints traceback |  | 0 |
| PASS | _download_image results aren't stored as '*_path' |  | 0 |
| PASS | upload-cache migration (cached=64, legacy=9) | 9 legacy idioms remain (budget 12; helper leaves are expected) | 0 |
| PASS | sc_cache_* literals use content-hash suffix |  | 0 |
| PASS | section complete |  | 9110 |
