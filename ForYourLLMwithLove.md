# ForYourLLMwithLove.md
# Spellcaster — ultra-dense LLM orientation. Not human-legible by design.
# Companion to CLAUDE.md (which is human-legible). Read this first when scope-constrained.

## §ID — top-level facts
repo=spellcaster;middleware b/w ComfyUI↔{GIMP,DT,Guild,ST,Resolve,Photoshop,Blender,Krita,OBS}
tools=69 AI tools;4 github repos(spellcaster[pub],spellcaster_NSFW[priv],ComfyUI-Spellcaster[pub],ComfyUI-Spellcaster-NSFW[priv])
canon_path=comfyui-spellcaster/spellcaster_core/ in main repo=single-source-of-truth
python=3.12+;ts/react;GTK3(GIMP3);aiohttp(ComfyUI);vanilla-js(Guild)

## §SYNC — 5-copy mirror rule (see CLAUDE.md §3)
spellcaster_core/{file}.py mirrors to:
 1. comfyui-spellcaster/spellcaster_core/              [CANON; auto-updater reads here]
 2. plugins/gimp/comfyui-connector/spellcaster_core/   [dev copy]
 3. ../ComfyUI-Spellcaster/spellcaster_core/           [pub node repo]
 4. ../ComfyUI-Spellcaster-NSFW/spellcaster_core/      [priv node repo]
 5. %APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/spellcaster_core/  [installed]
pack-root mirrors(NOT in spellcaster_core/):presence.py,blob_bus.py,privacy_cleanup.py,model_repair.py → ../ComfyUI-Spellcaster{,-NSFW}/
verify: `md5sum <all-5-copies>` must match
after-sync: commit in {spellcaster,ComfyUI-Spellcaster,ComfyUI-Spellcaster-NSFW}, then `python nsfw/build_nsfw.py --patch-only --push`
skip_sync→auto-updater overwrites on next GIMP launch

## §CORE — spellcaster_core/ module catalog
workflows.py        — all build_* fns(70+);canonical DAG builders
node_factory.py     — ComfyUI node constructors;controlnet_apply_advanced(...,vae_ref=)
composites.py       — multi-node blocks;inject_controlnet(honours cn_model_override),inject_lora_chain,load_model_stack,encode_prompts,apply_sam3_scope,build_sam3_mask,_klein_enhance_model,_apply_quality_boost,_apply_speedup,_apply_flux1_boosters,_emit_sampler
architectures.py    — 22 archs;ArchConfig;supported_methods;IMAGE_METHODS/VIDEO_METHODS/KLEIN_METHODS consts
model_detect.py     — classify_ckpt_model(name,file_size=None);cn_is_compatible;cn_modes_for_arch;CN_FORBIDDEN_ARCHES={flux2klein,flux_kontext,chroma}
dispatch.py         — dispatch_workflow(server,wf,timeout,free_vram,privacy,preflight,optimize)→DispatchResult(prompt_id,outputs,elapsed,warnings)
preflight.py        — preflight_workflow(wf,server)→(ok,wf,report);validate_workflow_files(wf,server)
optimizer.py        — optimize_workflow(wf,comfy_url)→(wf,warnings)
estimate.py         — ETA/runtime estimation for SpeedCoach
video_presets.py    — detect_wan_preset,detect_ltx_preset,wan_turbo_kwargs(turbo),ltx_mode_kwargs(mode),pick_wan_vae
prompt_enhance.py   — LLM rewrite;per-method profiles
comfyui_llm.py      — discover_llm(server);ComfyUI-node-based LLM
guild_llm.py        — LLM chat(ComfyUI→KoboldCpp→Ollama cascade)
privacy.py          — cleanup_server_files(server,workflow,results);uses /spellcaster/privacy/delete route;OWNED_PREFIXES=(gimp_,guild_,spellcaster_,sc_test_);CACHE_PREFIXES
preflight_status.py — traffic-light aggregator
faceswap_health.py  — auto-recovery guard for comfy-mtb+ReActor TRT crashes
asset_gallery.py    — content-hash blob store(tavern/creations/gallery/)
event_bus.py        — cross-interface pub/sub;`{origin}.asset.created` kind
events.py           — typed event dataclasses;parse_event(kind,data)
interface_registry.py — registered consumer interfaces
mailbox.py          — per-interface pull queues
cross_interface.py  — CrossInterfaceClient(heartbeat,publish,blob_put,upload)
lora_knowledge.py   — get_knowledge(name) civitai+safetensors+shipped+fallback merge;classify_nsfw
lora_calibration_store.py — sfw_path/nsfw_path;write_calibration(name,nsfw=bool,...)
lora_scorer.py      — score_image(b64,prompt,ollama_url,model)
pipeline.py         — fluent Pipeline().txt2img().upscale().run()
plugin_base.py      — BasePlugin for thin clients
forge.py            — reverse_engineer_image(png) PNG tEXt parse
diagnostic.py       — live server probe
memory.py           — per-character state
antenna_registry.py — multi-machine service wiring

## §ARCH — 22 arch keys (architectures.py)
fully-built(registered=True):sd15,sdxl,illustrious,zit,flux1dev,flux2klein,flux_kontext,chroma,sdxl_turbo,pony,playground,wan,ltx,seedvr
stubs(registered=False):sd3,sd3_turbo,hunyuan_dit,pixart,auraflow,kolors,cogvideo
CN_FORBIDDEN={flux2klein,flux_kontext,chroma}
no_negative_prompt={flux1dev,flux2klein,flux_kontext,chroma} → use conditioning_zero_out
klein_sampler=SamplerCustomAdvanced+CFGGuider+BasicScheduler(NOT KSampler)
flux_no_quality_tags={flux1dev,flux_kontext}
enhance_skip={flux_kontext,zit}
video_archs={wan,ltx};video_methods=VIDEO_METHODS const
supports_method(arch,method)→bool;_assert_method_for_preset(preset,method) at every builder entry
cn_needs_vae={flux1dev,flux2klein,flux_kontext}→controlnet_apply_advanced(vae_ref=vae)

## §CN — ControlNet resolution 3-layer (CLAUDE.md §26)
layer1=CONTROLNET_GUIDE_MODES(hardcoded,GIMP plugin line 4188)→drives UI combo;per mode×arch flat-form path
layer2=_resolve_normal_map_cn(server,arch_key)+_NORMAL_MAP_FALLBACK_CHAIN→cascade Union→Depth→Canny→lineart;chain includes flat+HF folder paths;stashes cn_model_override
layer3=_resolve_cn_paths_in_workflow(server,wf)→walks every ControlNetLoader,rewrites control_net_name to installed file;runs unconditionally inside _run_comfyui_workflow pre-dispatch;match=exact→basename→stem(strips _fp16;generic HF basenames→parent-folder identity)
composites.inject_controlnet honours controlnet_config["cn_model_override"] BEFORE guide["cn_models"][arch] fallback
session_blacklist=_CN_SESSION_BLACKLIST;_maybe_handle_cn_error scans errs for {incomplete metadata,controlnet file is invalid,does not contain controlnet or t2i adapter data};extracts ControlNetLoader name from wf;adds to blacklist
repair_route=POST /spellcaster/models/repair body={action:delete|redownload,folder:controlnet,filename:...};GET /spellcaster/models/known_urls
GIMP side=_offer_cn_repair() fires on every /3D handler entry when _LAST_BAD_CN set
CN_URL_MAP lockstep=comfyui-spellcaster/model_repair.py + installer/install.py::step_check_cn_coverage (single edit per new CN)

## §DISPATCH — workflow pipeline
GIMP handler→_export_and_upload_cached(srv,image)→uname;build_wf(uname,preset,...);_run_with_spinner(label,lambda:list(_run_comfyui_workflow(srv,wf,timeout=300)))→results=[(fn,sf,ft),...];loop _apply_mask_mode(srv,image,_download_image(srv,fn,sf,ft),label,mask_mode)
_run_comfyui_workflow(server,wf,timeout=300):
 1. _wait_for_comfy_queue_empty(server)
 2. _flush_pending_uploads()  [with _workflow_lock]
 3. _resolve_cn_paths_in_workflow(server,wf)  [§CN layer3]
 4. try spellcaster_core.dispatch.dispatch_workflow(privacy=False) except RuntimeError→_maybe_handle_cn_error→raise
 5. images=result.outputs
 6. _precache_results(server,images) — downloads ALL outputs to _download_cache BEFORE privacy cleanup
 7. _repatriate_outputs(server,images,workflow=wf) — copies to cfg.output_dir;_cleanup_server_temps if cfg.output_cleanup in ("move","delete")
 8. _record_dispatch_telemetry(...) — logs/dispatch_log.jsonl
 9. return images
_download_image = cache-first(via _download_cache) then raw HTTP GET /view

## §RETRIEVER — result import homogeneity (CLAUDE.md §28)
choke_point=_apply_mask_mode(server,image,img_data,layer_name,mask_enabled,keep_size=False)
guard: if img_data is None or len<100 → Gimp.message + return False
delegates to _import_result_as_layer(image,data,name,keep_size)
import routing: larger-than-canvas→Gimp.Display.new(new image);else layer path scaled to canvas;keep_size=True→natural size centered(SAM3/normal-map auto-gen)
video handlers:_import_video_results routes last-frame PNG through _apply_mask_mode(...,mask_enabled=False) + calls _repatriate_outputs at end (privacy parity)
mask_enabled=True→upload+build_rembg→download transparent PNG
NEVER call _import_result_as_layer directly unless documented reason

## §WORKFLOWS — build_* catalog (workflows.py; use these — never hand-roll DAG)
# image
build_img2img, build_txt2img, build_generate_anything
build_inpaint (composite-in-mask via ImageCompositeMasked "96" — outside-mask pixels pristine)
build_outpaint
build_detail_hallucinate, build_seedv2r, build_style_transfer
build_colorize, build_controlnet_gen, build_iclight, build_supir
build_upscale, build_wavespeed_upscale, build_upscale_blend, build_layer_blend
build_rembg, build_rembg_birefnet, build_ddcolor, build_lut, build_color_match
build_normal_map, build_lama_remove
# klein family (flux2klein)
build_klein_img2img, build_klein_img2img_ref, build_klein_inpaint, build_klein_headswap
build_klein_repose, build_klein_blend, build_klein_batch_variations, build_klein_refine
build_klein_virtual_tryon, build_klein_scene_img2img, build_klein_auto_inpaint
build_klein_color_match, build_klein_sam3_inpaint, build_klein_face_detail
build_klein_generate_object, build_klein_detail
# face
build_faceswap, build_faceswap_model, build_faceswap_mtb, build_save_face_model
build_face_restore, build_photo_restore, build_faceid_img2img, build_pulid_flux
build_photobooth
# sam3
build_sam3_segment, build_sam3_extract, build_magic_eraser
# video
build_wan_video, build_wan_flf, build_wan22_t2v, build_wan_video_blockswap
build_ltx_video (see CLAUDE.md §16 for full canon; 29-kwarg surface)
build_video_upscale, build_video_reactor, build_seedvr2_video_upscale
build_frame_assembly
# edit
build_qwen_edit

## §WF-RULES — invariants
every builder first line: _assert_method_for_preset(preset, "<method>")
model stack: model_ref, clip_ref, vae_ref = load_model_stack(nf, preset, base_id)
loras: inject_lora_chain(nf, loras, model_ref, clip_ref, arch_key=preset['arch']) — skip for WAN (uses direct lora_loader_model_only)
encode: pos_id, neg_id = encode_prompts(nf, arch_key, clip_ref, pos, neg, pos_id, neg_id) — honours arch no-negative
CN inject: inject_controlnet(nf, cn, guide_modes, arch_key, img_ref, pos, neg, cn_base_id, vae_ref=vae_ref)
video LoRA filter: arch filter DOES NOT run on video — use lora_loader_model_only direct
dims: MUST be mod-16 for Flux; callers pre-round via round_to_mod(16)
quality cascade: _apply_quality_boost(nf, model_ref, arch_key, quality, cfg, node_base_id)→CFGZeroStar→PAG→SLG→FreeU→DetailDaemon (per-arch gates §22)
speedup: _apply_speedup(nf, model_ref, arch_key, fast_mode, node_id)→Sage Attn+torch.compile+TeaCache (per-arch §22)
flux boosters: _apply_flux1_boosters(nf, model_ref, pos, preset, node_base_id)→Flux1 specific
klein enhance: _klein_enhance_model(nf, model_ref, pos, node_base_id) only when enhance=True

## §GIMP — plug-in anatomy
path=plugins/gimp/comfyui-connector/{comfyui-connector.py[IMMUTABLE shim],_spellcaster_main.py[~34K lines]}
subprocess_fact: each proc call = NEW child process;Gimp.quit() unreliable→use taskkill /IM gimp-3.0.exe /F /T on restart (CLAUDE.md §27)
theme: CSS provider at PRIORITY_USER(800 > PRIORITY_APPLICATION 600 which GIMP default uses);_apply_spellcaster_theme gated on config.json apply_theme;_THEME_VARIANTS dict(15 guild-matching palettes);theme_variant config key
dialog_pattern: GimpUi.init→Gtk.Dialog→add_button(Cancel,CANCEL)+add_button(Run,OK)+set_default_response(OK);_style_dialog_buttons(dlg);_make_branded_header();content;dlg.run();dlg.get_values();dlg.destroy()
PresetDialog: class at line 11622;use self._preset_idx() NOT preset_combo.get_active() (filtered archs break visual-index==MODEL_PRESETS_index invariant);external set_active(i)→set_active_id(str(i))
handler_signature: def _run_<name>(self, procedure, run_mode, image, drawables, config, data)→procedure.new_return_values(PDBStatusType.SUCCESS|CANCEL|EXECUTION_ERROR|CALLING_ERROR, GLib.Error())
RunMode: INTERACTIVE(user),WITH_LAST_VALS(F2 re-run),NONINTERACTIVE(API)
every handler wraps work in try/except→traceback.print_exc()+Gimp.message(f"Error: {e}")
_add_normal_map_selector(dialog,box,image) — adds 3D normal map picker;sets _normal_enabled/_normal_combo/_normal_auto_gen on dlg;_FORCE_3D_MODE global locks it on
_collect_normal_map_from_dialog(dlg,image,srv,current_cn_mode,arch_key)→uploaded filename or None;short-circuits on CN=Off unless _FORCE_3D_MODE
_maybe_override_cn_with_normal_map(cn,nm_filename,arch_key)→merged cn dict with cn_model_override
_CN_INCOMPATIBLE_ARCHS=frozenset({flux2klein,flux_kontext,chroma})→passed as exclude_archs to PresetDialog
procedure_registration: every proc must be in _PROC_FEATURES + menu_map + _menu_paths dicts (CLAUDE.md §7)
klein/kontext class_types: Flux2KleinRefLatentController, Flux2KleinTextRefBalance, Flux2KleinColorAnchor, Flux2KleinMaskRefController — verify via /object_info, never hallucinate

## §SETTINGS — keys in config.json (plugin dir)
server_url, workflow_timeout, auto_update(bool), debug_images(bool), favourite_model(int), output_dir, output_cleanup("copy"|"delete"|"move"), extra_workflow_dirs(list), prompt_enhance(bool), llm_url, apply_theme(bool), theme_variant(str)
_save_config(partial_dict) merges with existing config
config.json is gitignored (contains server URL which is personal data)

## §GUILD — tavern/server.py
port=15001 default; python server w/ web UI at tavern/static/
_cache_comfyui_asset(url,kind=str,origin=,prompt=,model=,seed=,tags=,meta=)→AssetGallery.put+publish AssetCreated event+return /api/assets/<hash>
asset canonical URL = /api/assets/<hash>;legacy /api/cached_asset/<name> shim stays
_GUILD_VIDEO_MODE module-level ("turbo"|"standard"|"quality");GET/POST /api/video/quality-mode
_apply_quality_mode(preset_key,overrides)→rewrites based on mode
/api/video/shots entry for WAN+LTX (§16)
/api/spellcaster/lora/* calibration+scorer endpoints (§19)
/api/spellcaster/faceswap/{health,reset} (§20)
/api/spellcaster/preflight/{status,run} (§20)
/api/archetype/{forensic,chimera,oracle,lore_keeper,scalpel}/* (§21)
/api/run_builder — thin plugin bridge (§24) body={builder,params,comfy_url}→{assets:[/api/assets/<hash>,...]}
_ARCHETYPE_CATALOGUE,_validate_archetype_config for Summon path B
_queue_animated_avatar uses build_ltx_video + ltx_mode_kwargs("i2v") + _ltx_server_opts(srv)
_retry_anim_as_ltx same pattern
_GENERATION_FINISHED_KINDS triggers gimp.asset.created event fan-out

## §PACK — comfyui-spellcaster HTTP routes
presence.py → POST /spellcaster/presence/{register,heartbeat,unregister}; GET /spellcaster/presence/list;TTL=45s
blob_bus.py → POST /spellcaster/blob/put (multipart);GET /spellcaster/blob/<hash>;/list;TTL 1h default 24h max;256MB/blob 2GB aggregate;storage=comfyui/output/spellcaster_bus/
privacy_cleanup.py → POST /spellcaster/privacy/delete body={filenames:[],folder_type:input|output|temp|all,prefixes:[]};returns {deleted:[],failed:[]};safety=prefix whitelist + path traversal + realpath under folder root
model_repair.py → POST /spellcaster/models/repair {action,folder:controlnet,filename}; GET /spellcaster/models/known_urls;CN_URL_MAP curated HF URLs;min-size refusal on download;atomic rename via .download tmp
nodes/ = SpellcasterLoader, SpellcasterPromptEnhance, SpellcasterSampler, SpellcasterOutput (4 nodes + NSFW LoRA node in NSFW variant)

## §NSFW — insertion points (build_nsfw.py patch markers)
nsfw_dir=nsfw/ (GITIGNORED — never git add -f)
build: python nsfw/build_nsfw.py [--patch] [--push] [--build] [--patch-only --push](most common)
patches copy SFW→nsfw/staging/, apply NSFW overlays, push to private repo
## marker locations (grep: "NSFW_.*_INJECTION_POINT" or "NSFW_.*_INJECT_ANCHOR")
plugins/gimp/comfyui-connector/_spellcaster_main.py:
 L4465  NSFW_OUTPAINT_INJECTION_POINT       — OUTPAINT_PURPOSE_PRESETS extras
 L4935  NSFW_HALLUCINATE_INJECTION_POINT    — HALLUCINATE_PRESETS extras
 L4967  NSFW_ICLIGHT_INJECTION_POINT        — ICLIGHT_PRESETS extras
 L5021  NSFW_KONTEXT_INJECTION_POINT        — KONTEXT_TASKS extras
 L6688  NSFW_PHOTOBOOTH_STYLES_INJECTION_POINT
 L9393  NSFW_LTX_INJECTION_POINT            — LTX_VIDEO_PRESETS extras
 L29896 NSFW_BODY_FACTORY_INJECTION_POINT   — BODY_PRESETS extras
 L30199 NSFW_CLOTHING_STORE_INJECTION_POINT — OUTFIT_PRESETS extras
 L30437 NSFW_STUDIO_SET_SCENES_INJECTION_POINT
 L30466 NSFW_STUDIO_SET_PLACEMENTS_INJECTION_POINT
tavern/server.py:
 L200   NSFW_PERSONALITY_INJECT_ANCHOR
 L7798  NSFW_APPEARANCE_INJECT_ANCHOR
 L15575 NSFW_BG_STYLES_INJECT_ANCHOR
wan (unknown exact loc) NSFW_WAN_INJECTION_POINT, NSFW_WAN_SCENES_INJECTION_POINT
ltx NSFW_LTX_SCENES_INJECTION_POINT, NSFW_DIRECTOR_INJECTION_POINT
data files(nsfw/):nsfw_klein_presets.json,nsfw_loras.json,nsfw_presets_extras.json,nsfw_presets_inpaint.json,nsfw_presets_video.json,lora_calibrations_nsfw.json
## when patching SFW for NSFW
1. add marker line comment "# -- NSFW_<CATEGORY>_INJECTION_POINT --" near target data struct
2. build_nsfw.py::patch_nsfw_* finds marker → injects entries from nsfw_*.json above it
3. NSFW build ships to laboratoiresonore/spellcaster_NSFW private repo
## personalization rules (non-NSFW custom extensions)
- add to SFW code at same injection-point pattern — just use "# -- CUSTOM_<CATEGORY>_INJECTION_POINT --" and wire your own patcher
- OR fork + maintain your own overlay similar to nsfw/build_nsfw.py
- calibration_recipes: add to comfyui-spellcaster/spellcaster_core/lora_calibrations_sfw.json (public) or nsfw/lora_calibrations_nsfw.json (private patch)
- style presets: IMG2IMG_STYLE_PRESETS in _spellcaster_main.py (inline dict; no marker yet — add one if you want clean patch-ability)

## §TESTS — tests/ harnesses
tests/e2e_audit.py — live end-to-end sweep;sections include {presence_broker,blob_bus,events_schema,video,build_fns,guild_client,cn_model_coverage,coverage_inventory};run: `PYTHONIOENCODING=utf-8 python tests/e2e_audit.py --only video --verbose`; `--offline` runs without Guild
tests/test_model_coverage.py — arch registry + supported_methods enforcement (§17)
tests/test_cn_compat.py — every (mode,arch) × 14 modes × 20 archs = 280 pairs
tests/test_quality_boost.py — §22 cascade
tests/test_lora_auto_calibrate.py — §19 calibration
tests/test_summon_archetypes.py — §21 archetype validators
tests/test_klein_enhancer.py — Klein enhancer chain
tests/test_auto_updater.py
tests/test_model_prompt_profiles.py
tests/test_video_layer.py
expected green bar on live server ≥ 54 PASS / 0 FAIL / N SKIP (audit §16.5)

## §INSTALLER — installer/install.py
bootstrap=installer/bootstrap.py (fetches latest install.py/installer_gui.py/manifest.json from raw.githubusercontent.com on every exe launch;offline fallback to baked-in)
steps: step_system_detection → step_api_keys → step_detect_server → step_detect_paths → step_probe_server → step_detect_llm_server → step_install_mode_choice(guided|expert) → step_select_features → step_install_nodes → step_install_models → step_check_cn_coverage → _write_shared_settings → step_install_plugins → step_install_tavern → step_import_luts → step_apply_theme → step_ask_remote_services → generate_antenna_files
step_check_cn_coverage matches {flat,HF-folder} against server inventory;offers auto-download via pack repair route;falls back to ComfyUI Manager instructions if pack route not live
manifest.json drives features+nodes+models selection
fresh_install: rebuild exe ONLY when bootstrap.py/build flags/bundled assets change;install.py edits → push to main, existing exe picks up on next launch

## §AUTO-UPDATER — 3 flavours (CLAUDE.md §13)
1. Wizard Guild → tavern/guild_launcher.py:check_for_updates — every launch;protected={guild_launcher.py,guild_config.json,guild_common.py};clobbers ALL tavern/ + scaffold/ NOT in remote (including prunes)
2. GIMP plugin → _spellcaster_main.py:_auto_update — GIMP start;protected={comfyui-connector.py,config.json,.spellcaster_version,user_presets.json,session_state.json};clobbers plugin dir + spellcaster_core/
3. Installer bootstrap → ephemeral temp dir, never clobbers user data
BEFORE recommending a restart: check `git status -s | grep <affected-dir>` and warn user if uncommitted

## §COMMON-PITFALLS
- never `git add -A` or `git add .` — always specific files (CLAUDE.md §11,§12)
- never `git add -f` on gitignored (especially nsfw/)
- never commit IPs/paths/emails/tokens → scan via `git diff --cached | grep -iE "192\.168|lmlgg|leguillaume|@gmail|ghp_"`
- gitignored: config.json, guild_config.json, session_state.json, user_presets.json, .guild_state/, .claude/, nsfw/, tavern/creations/, CLAUDE.md, ForYourLLMwithLove.md
- pluginrc: clear via `rm -f %APPDATA%/GIMP/3.2/pluginrc` when menu reg changes
- .update files: `rm -f %APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/*.update` before copying new plugin
- Gimp.quit() unreliable from plug-in → taskkill pattern (§27)
- CSS PRIORITY_APPLICATION loses to GIMP default → use PRIORITY_USER
- preset_combo.get_active() breaks when exclude_archs filters entries → use _preset_idx()
- Flux CN ControlNetApplyAdvanced REQUIRES vae_ref (raises `This Controlnet needs a VAE` else)
- outpaint inpaint VAE round-trip tints preserved regions UNLESS ImageCompositeMasked composites output with original via full-res mask
- ZIT-Fun CN (Z-Image-Turbo-Fun-Controlnet-Union.safetensors) needs dedicated loader, built-in ControlNetLoader raises "controlnet file is invalid"
- NormalCrafter on RTX 50xx crashes ComfyUI (xformers capability 12.0 incompat) — detect + fail fast
- mask_mode (rembg transparency) ≠ mask_enabled (inpaint mask); don't confuse
- Guild backfill seeded assets route through AssetGallery.put as of 2026-04-20 — no new /api/cached_asset/ writers

## §PATHS — central policy (CLAUDE.md §14)
python: pathlib.Path always;never + concat;never f-string
config json: forward slash `/` (Windows accepts);emit via .as_posix()
subprocess argv on Win: str(path) native
workflow JSON: filenames only, NO full paths (ComfyUI resolves server-side)
API response bodies: forward slash via .as_posix()

## §QUICK-REF — file:line bookmarks
plugins/gimp/comfyui-connector/_spellcaster_main.py:
 L2319   _FORCE_3D_MODE global
 L2322   _add_normal_map_selector
 L2750   _collect_normal_map_from_dialog
 L3007   _NORMAL_MAP_FALLBACK_CHAIN
 L3045   _resolve_normal_map_cn
 L3308   _maybe_override_cn_with_normal_map
 L3437   _apply_mask_mode(with <100B guard)
 L3633   _fetch_available_cn_files
 L3660   _cn_model_available (3-valued)
 L3700   _resolve_cn_paths_in_workflow (layer 3)
 L4188   CONTROLNET_GUIDE_MODES
 L9330   _import_result_as_layer (upscaler auto-route)
 L9742   _import_video_results
 L11622  class PresetDialog
 L11677  _run_comfyui_workflow
comfyui-spellcaster/spellcaster_core/
 workflows.py:L306 build_img2img, L2913 build_inpaint(composite "96"), L3130 build_outpaint, L3880 build_wan_video, various
 node_factory.py:L1251 controlnet_apply_advanced(vae_ref=)
 composites.py:L533 inject_controlnet(reads cn_model_override), L637 inject_controlnet_pair, L798 apply_sam3_scope
 architectures.py: ArchConfig, get_arch, supported_methods, IMAGE/VIDEO/KLEIN_METHODS
 model_detect.py: classify_ckpt_model, cn_is_compatible, cn_modes_for_arch, fallback_arch_for_size
comfyui-spellcaster/:
 __init__.py wires presence, blob_bus, privacy_cleanup, model_repair
 model_repair.py L30 CN_URL_MAP (mirror in installer/install.py)

## §COMMIT — message style
Template: "<scope>: <headline verb-object>\n\n<what changed + why>\n\n<how verified>\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
scopes: gimp, core, server+gimp, gimp/3d, gimp/theme, gimp/restart, server+installer, docs, pack
never skip hooks (no --no-verify unless user asks)
verify: `git diff --cached | grep -iE "192\.168|lmlgg|leguillaume|@gmail|ghp_"` must be empty

## §PROMISE — invariants future-LLM should not break
1. spellcaster_core is single source of truth;never have parallel impl in plugin
2. every build_* asserts method support at line 1
3. every CN-loading workflow passes through _resolve_cn_paths_in_workflow before dispatch
4. every generated asset flows through AssetGallery.put + events (CLAUDE.md §15)
5. NSFW never reaches public repo (nsfw/ gitignored; build_nsfw.py patches then pushes to private)
6. thin-plugin DAGs go through /api/run_builder;Python plugins import spellcaster_core directly
7. GIMP Settings dialog is the ONE place the user changes config — UI + persist + live re-apply
8. Klein never uses ControlNet;use CFGGuider+BasicScheduler+SamplerCustomAdvanced;never KSampler
9. Flux arches never use quality tags;never use negative prompts (zero_out)
10. Preset index in PresetDialog is a stable ID via _preset_idx(),not get_active()

<!-- END ForYourLLMwithLove.md -->
