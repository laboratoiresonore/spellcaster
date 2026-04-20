# Spellcaster E2E Audit

_Ran at_: 2026-04-20 16:21:08
_Totals_: **66** pass · **0** fail · **0** warn · **0** skip

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

## Coverage inventory

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | spellcaster_core | 40/485 referenced (8%) | 0 |
| PASS | comfyui_pack | 40/495 referenced (8%) | 0 |
| PASS | gimp_plugin | 41/572 referenced (7%) | 0 |
| PASS | resolve_shared | 1/42 referenced (2%) | 0 |
| PASS | resolve_bridge | 1/16 referenced (6%) | 0 |
| PASS | guild_tavern | 1/28 referenced (4%) | 0 |
| PASS | TOTAL across all surfaces | 124/1638 public fns referenced (8%) | 0 |

## Upload cache & privacy

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | CACHE_PREFIXES ∩ OWNED_PREFIXES is empty |  | 0 |
| PASS | cleanup_inputs SKIPS sc_cache_* from workflow | wiped=[] | 0 |
| PASS | cleanup_inputs WIPES gimp_* from workflow | wiped=['gimp_abc.png', 'gimp_123.png'] | 0 |
| PASS | cleanup_inputs server-scan exempts sc_cache_* | missing=set(), extra=set() | 0 |
| PASS | purge_cache targets ONLY CACHE_PREFIXES | wiped=['sc_cache_abc.png'] | 0 |
| PASS | cleanup_outputs wipes all result files | wiped=['result_1.png', 'sc_cache_should_still_go_if_passed_here.png'] | 0 |
| PASS | section complete |  | 3 |

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
| PASS | section complete |  | 2506 |

## IC-Light normal-map routing

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | normal-map path does NOT load iclight_sd15_fbc |  | 0 |
| PASS | normal-map path loads ControlNetLoader | classes=['CLIPTextEncode', 'CheckpointLoaderSimple', 'ControlNetApplyAdvanced', 'ControlNetLoader', 'ICLightConditioning', 'KSampler', 'LoadAndApplyICLightUnet', 'LoadImage', 'SaveImage', 'VAEDecode', 'VAEEncode'] | 0 |
| PASS | normal-map path applies ControlNetApplyAdvanced |  | 0 |
| PASS | CN model is normalbae (surface-aware) | cn_names=['control_v11p_sd15_normalbae.pth'] | 0 |
| PASS | normal map loaded as image (not latent) |  | 0 |
| PASS | no-normal path does NOT include ControlNet | classes=['CLIPTextEncode', 'CheckpointLoaderSimple', 'ICLightConditioning', 'KSampler', 'LoadAndApplyICLightUnet', 'LoadImage', 'SaveImage', 'VAEDecode', 'VAEEncode'] | 0 |
| PASS | section complete |  | 4 |

## Plugin surface (AST)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | plugin parses |  | 0 |
| PASS | every _PROC_FEATURES key has menu_map entry (90 procs) |  | 0 |
| PASS | every _PROC_FEATURES key has _menu_paths entry |  | 0 |
| PASS | no orphan menu_map keys (every menu has a feature) |  | 0 |
| PASS | no orphan _menu_paths keys |  | 0 |
| PASS | _apply_mask_mode arity (5 or 6) across 58 call sites |  | 0 |
| PASS | every _run_* Gimp.message-ing except prints traceback |  | 0 |
| PASS | _download_image results aren't stored as '*_path' |  | 0 |
| PASS | upload-cache migration (cached=63, legacy=9) | 9 legacy idioms remain (budget 12; helper leaves are expected) | 0 |
| PASS | sc_cache_* literals use content-hash suffix |  | 0 |
| PASS | section complete |  | 8803 |
