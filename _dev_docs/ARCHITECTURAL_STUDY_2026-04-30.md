# Spellcaster — Architectural Study

**Date:** 2026-04-30
**Scope:** Full project — `<repo-root>/spellcaster/` (canonical clone)
**Type:** Reference-grade architectural snapshot. No code changes were made.

---

## 0. Executive summary

Spellcaster is **middleware between ComfyUI and a fan of user-facing AI surfaces** (GIMP, Darktable, Krita, OBS, Photoshop, DaVinci Resolve, Blender, SillyTavern, plus a chat UI called *Wizard Guild*). A separate private downstream distribution bundles Spellcaster with a custom GIMP fork; that distribution is out of scope for this public repo. The codebase enforces a **single source of truth** rule — every piece of shared logic lives in `comfyui-spellcaster/spellcaster_core/` and is mirrored to ~6 surfaces by sync rules described in `CLAUDE.md`.

| Surface | Role |
|---|---|
| `comfyui-spellcaster/` | ComfyUI custom-node pack (4 smart nodes + 2 transport routes). **Canonical home of `spellcaster_core/`.** |
| `tavern/` | Wizard Guild — local HTTP chat server + SPA frontend. Cross-app event bus and asset gallery host. |
| `plugins/` | GIMP, Darktable, Krita, OBS, Photoshop, Resolve, Blender, SillyTavern integrations. |
| `nsfw/` | Build script + patches that produce a parallel NSFW variant. Gitignored. |
| `installer/` | PyInstaller-built Windows installer with self-update bootstrap, optional remote/antenna mode. |
| `antenna/` | Lightweight HTTPS agent that runs on the GPU host so clients can install nodes/models remotely. |

Top-level scale: **~38K LOC** in the GIMP plugin, **~17K LOC** in the Guild server, **~31K LOC** in `spellcaster_core/`, **8K+ LOC** in `workflows.py` alone, **2.5K LOC** in `node_factory.py`. Four GitHub repos kept in lockstep (`spellcaster`, `spellcaster_NSFW`, `ComfyUI-Spellcaster`, `ComfyUI-Spellcaster-NSFW`).

---

## 1. Project structure

### 1.1 Top-level tree (depth 2)

```
spellcaster/
├── CLAUDE.md                 1148 lines — operational rules, architecture invariants
├── DEEP_DIVE.md              1027 lines — feature-level reference
├── ForYourLLMwithLove.md      317 lines — ultra-compressed orientation for LLMs
├── README.md                  531 lines — user-facing pitch
├── DEPENDENCIES.md             — auto-generated from installer/manifest.json
├── Wizard_Guild.exe           — compiled chat-UI app (PyInstaller)
├── Wizard_Guild.spec          — PyInstaller build spec for above
├── spellcaster-installer.exe — interactive installer
├── spellcaster-manual-update.exe — standalone updater
├── launcher.py                — top-level app picker
├── *.bat                      — Install / Wizard Guild / Settings / DEVNOUPDATE / rebuild
├── _dev_docs/                 — research, audits, handovers
├── antenna/                   — HTTPS agent for remote ComfyUI host
├── assets/                    — installer + UI imagery (incl. wizard_guild_graphics/)
├── build/                     — PyInstaller intermediate caches
├── comfyui-spellcaster/       — ComfyUI custom-node pack + canonical spellcaster_core
├── dev/                       — dev scratch
├── dist/                      — output executables (gitignored)
├── docs/                      — docs site sources
├── installer/                 — install.py + manual_update.py + GUI
├── nsfw/                      — NSFW build script + patches (gitignored)
├── plugins/                   — host-app integrations (8 hosts)
├── scaffold/                  — wizard scaffolds (LLM-driven state machines)
├── scripts/                   — automation (e.g. generate_dependencies_md.py)
├── tavern/                    — Wizard Guild server + SPA frontend
├── tests/                     — pytest suites (e2e, quality, klein, video, lora)
└── tools/                     — small helpers (incl. llm_offload.py shim)
```

### 1.2 Two parallel git repos visible

The folder is a **multi-repo working tree**:
- `spellcaster/.git` is the public-repo checkout (`origin = laboratoiresonore/spellcaster`).
- The same directory also contains a private NSFW checkout under `nsfw/` as a nested clone.
- Branches in the public repo: `main`, `nsfw_main`, `test/e2e-audit`, plus the secondary `nsfw/main` remote.

---

## 2. Wizard Guild / Wizard Tavern server (`tavern/`)

### 2.1 Entry points

| File | Lines | Role |
|---|---|---|
| `tavern/server.py` | **17,010** | Core HTTP server. Pure-stdlib `ThreadingHTTPServer` + `SimpleHTTPRequestHandler` subclass `GuildHandler`. ~400 endpoints across `do_GET` and `do_POST`. |
| `tavern/guild_launcher.py` | ~2,500 | Lifecycle manager: persistent config, GitHub auto-update, port-collision recovery, optional Kobold/SillyTavern auto-launch, browser auto-open. |
| `tavern/wizard_guild_launcher.py` | 45 | Thin PyInstaller-bundled wrapper that locates and runs `start_guild.bat`. |
| `tavern/guild_tray.py` | 227 | Optional Windows system-tray UI (pystray + Pillow, graceful fallback). |
| `tavern/build_guild.py` | 277 | Build wrapper around `wizard-guild.spec` (PyInstaller). |
| `tavern/start_guild.bat` | tiny | Launches `python guild_launcher.py`. |

### 2.2 Web framework

**Pure stdlib** — `http.server.ThreadingHTTPServer` + custom `GuildHandler(SimpleHTTPRequestHandler)` (server.py:10067). Zero non-stdlib runtime deps for the server itself (pystray is optional). All POST routes parse JSON manually in `do_POST` (server.py:14953+). All GET routes (incl. POST-as-GET dispatches) flow through `do_GET` (server.py:10899+).

### 2.3 Endpoint inventory (representative, ~400 total)

| Category | Sample paths |
|---|---|
| Setup / onboarding | `/api/setup/state`, `/api/setup/comfyui-status` |
| Characters | `/api/characters`, `/api/all_characters` |
| Config / status | `/api/config`, `/api/version`, `/api/comfy_status`, `/api/llm_status` |
| ComfyUI integration | `/api/available_models`, `/api/scaffold_loras`, `/api/workflows`, `/api/run_builder` |
| LoRA stack | `/api/spellcaster/lora/groups`, `/lora/calibrate/*`, `/lora/shootout/*` |
| Models | `/api/spellcaster/models`, `/api/spellcaster/activation` |
| Video | `/api/video/shots`, `/api/video/render-all`, `/api/video/presets`, `/api/video/events` (SSE) |
| Cross-interface backbone | `/api/interfaces`, `/api/interfaces/heartbeat`, `/api/antennas`, `/api/events/emit`, `/api/mailboxes`, `/api/assets` |
| LLM / prompts | `/api/system_prompt`, `/api/llm_status` |
| Per-plugin ingress | `/api/gimp/*`, `/api/sillytavern/*`, `/api/signal/*`, `/api/darktable/*`, `/api/resolve/*` |
| SpeedCoach analytics | `/api/speedcoach/arch_speeds`, `/lora_impact` |

Root routes: `/` → `static/index.html`, `/setup` → `static/setup.html` (legacy), `/insights` → SpeedCoach dashboard.

### 2.4 Frontend

`tavern/static/` — vanilla JS + React/JSX:
- `index.html` (44 KB) loads `app.js` (362 KB — main SPA).
- `travelling_wizard.jsx` (218 KB) — live workflow JSON editor.
- `video_panel.jsx` (303 KB) + `video_chat.js` (15 KB) — video editor.
- `lora_calibration.js` (53 KB) + `lora_shootout.js` (61 KB).
- `style.css` (107 KB).
- `avatars/`, `assets/`, `icons/` — wizard portraits, branding.

### 2.5 Characters / Wizards

`tavern/characters/` — 13 SillyTavern v2 character cards (.json + .png pairs). Each card contains a `data.extensions.spellcaster` block linking the wizard to one or more `build_*` workflow builders. Example wizards: **Imaginus, Restorix, Restyler, Sceneshifter, Videomancer, Portraitist, Animancer, Masquerade, Studiocraft, Transmutex, Cinematic, Erasure, Spellcaster.**

### 2.6 Scaffold (sibling, NOT inside tavern/)

`scaffold/` is the **LLM-driven state machine layer** the Guild calls into:
- `spellcaster_wizard.py` (977 LOC) — phases: GREETING → ASSESS → INTENT → RECOMMEND → QUOTE → INSTALL_LOOP → … but the line-18 comment is canonical: *"States form a loose graph — the scaffold is conversational, not rigid."* The LLM picks transitions and emits `<ACTION>{...}</ACTION>` JSON blocks the server executes.
- `studio_scaffold.py` (437 LOC) — Magic Studios 5-act pipeline.
- `video_wizard.py` (774 LOC) — Director's Chair, chained WAN I2V.
- `meta_wizard.py` (162 LOC) — top-level wizard router.
- `introspector.py` — discovers ComfyUI nodes via `/object_info`.
- `workflow_parser.py` — parses .json workflows for parameter extraction.
- `shotboard.py` (122 KB) — video frame/shot management persistence.
- `comfyui_runner.py`, `video_bridge.py`, `video_assembler.py` — video pipeline.

### 2.7 Other tavern artifacts

| File | Role |
|---|---|
| `tavern/shotboard.json` | 35 KB — array of shot objects (id, prompt, ref_image, backend `wangp`/`ltx2`, status, etc.). |
| `tavern/activity.log` | JSON Lines — one event per line; `shot_created`, `shot_removed`, `timeline_imported`. |
| `tavern/signal_bridge_config.json` | 43 keys — Signal CLI integration (phone numbers, allowed contacts, ComfyUI URL, privacy flags). |
| `tavern/guild_config.json` | Extended config (see §8). |
| `tavern/wizard_speech.md` | Setup wizard system prompt overlay. |
| `tavern/creations/gallery/blobs/` | Hash-prefix-bucketed asset blob store. |

### 2.8 Talking to ComfyUI

The Guild **does not import `spellcaster_core` graph builders directly**. It imports `_workflows_v2.build_txt2img` from the installed GIMP-plugin directory (server.py:48, with `BUILTIN_AVAILABLE` fallback). It then submits to ComfyUI over HTTP `POST /prompt`, polls `/history/<id>`, and proxies progress to the browser.

### 2.9 LLM integration

`guild_config.json` keys: `llm_mode` (`"local"` or `"horde"`), `kobold_url` (default `127.0.0.1:5001`), `sillytavern_url`. System prompts built via `scaffold.meta_wizard.build_meta_system_prompt()`. `PROMPT_ENHANCE` flag (default True) wraps user prompts with an LLM rewrite step before ComfyUI.

---

## 3. ComfyUI integration (`comfyui-spellcaster/`)

### 3.1 Pack root

`comfyui-spellcaster/__init__.py` registers four nodes and three HTTP routes:

| Node | Purpose |
|---|---|
| `SpellcasterLoader` | Auto-detect arch from filename, hide checkpoint vs unet+clip+vae split. Returns `(MODEL, CLIP, VAE, arch_key)`. |
| `SpellcasterPromptEnhance` | LLM prompt rewriter; per-arch profiles. |
| `SpellcasterSampler` | Auto-pick KSampler vs SamplerCustomAdvanced. |
| `SpellcasterOutput` | VAE decode + privacy-aware save (integrates `privacy_cleanup.py`). |

Pack-root modules (NOT in `spellcaster_core/`):
- `presence.py` (18 KB) — peer-discovery broker with `/spellcaster/presence/{register,heartbeat,list}`. In-memory `dict` with TTL, cross-LAN. As of 2026-04-20 also broadcasts via `zeroconf` mDNS as `_spellcaster._tcp.local.` (silent fallback).
- `blob_bus.py` (16 KB) — Guild-less asset transport on ComfyUI itself. SHA-256-addressed, TTL-evicted, capped at 256 MB/blob and 2 GB aggregate. Stored under `<comfyui>/output/spellcaster_bus/`. Cuts the Guild's AssetGallery out of the inter-plugin transport path.
- `model_repair.py` — uses `huggingface_hub.hf_hub_download` (adopted 2026-04-20) for resilient model downloads.
- `privacy_cleanup.py` — server-side wipeout after delivery.

### 3.2 `node_factory.py` (2,469 LOC) — central node constructor

`NodeFactory` class is the single point of construction for every ComfyUI node Spellcaster builds.

Pattern of every method (e.g. `lora_loader_model_only(model_ref, lora_name, strength)`):
1. Validate inputs.
2. Build the inputs dict with `[node_id, output_index]` references.
3. Call `_add(class_type, inputs, node_id=…)` — registers node, auto-assigns ID, increments `_next_id`.
4. Return the new node ID for downstream wiring.

Categories of helpers (representative): checkpoint loader, UNET loader (with `.gguf` → `UnetLoaderGGUF` dispatch), single + dual CLIP loaders, VAE loader, LoRA loaders (with/without trigger-word extraction), CLIP encode + ConditioningZeroOut + ConditioningSetArea + ConditioningCombine, ControlNet apply, KSampler / SamplerCustomAdvanced, image upscale, VAE encode/decode, video nodes, faceswap nodes, Klein 2 enhancer chain (`Flux2KleinRefLatentController`, `Flux2KleinTextRefBalance`, `Flux2KleinColorAnchor`, `Flux2KleinRefLatentWeight`, `Flux2KleinMaskRefController`), identity-lock (`IdentityGuidance`, `IdentityFeatureTransfer`), TeaCache + WaveSpeed FBCache.

Returns final dict via `.build()` → `{"<id>": {"class_type": ..., "inputs": {...}}, ...}`.

### 3.3 `workflows.py` (8,276 LOC) — 42 workflow builders

`grep "^def build_"` finds 42 builders. Sample:

```
build_txt2img, build_img2img, build_generate_anything, build_rembg,
build_rembg_birefnet, build_ddcolor, build_upscale, build_wavespeed_upscale,
build_normal_map, build_lama_remove, build_lut, build_color_match,
build_klein_img2img, build_faceswap, build_faceswap_model, build_faceswap_mtb,
build_face_restore, build_photo_restore, build_detail_hallucinate, build_colorize,
build_controlnet_gen, build_iclight, build_supir, build_inpaint, build_outpaint,
build_faceid_img2img, build_pulid_flux, build_klein_img2img_ref, build_klein_headswap,
build_video_upscale, build_video_reactor, build_wan_video, build_wan_flf,
build_wan22_t2v, build_seedvr2_video_upscale, build_style_transfer, build_seedv2r,
build_photobooth, build_klein_repose
```

Every builder follows the same composition:

1. `load_model_stack(nf, preset)` — select loader strategy from `arch.loader`.
2. `inject_lora_chain(nf, loras, model_ref, clip_ref)` — chain LoRAs.
3. `encode_prompts(nf, arch_key, clip_ref, pos, neg)` — handle `arch.supports_negative` (Flux uses ConditioningZeroOut).
4. `sample_standard()` or `sample_klein_img2img()`.
5. VAE decode + SaveImage.

### 3.4 `composites.py` (869 LOC)

Reusable multi-node patterns: `load_model_stack` (checkpoint vs unet_clip_vae dispatch), `inject_lora_chain`, `encode_prompts`, `sample_standard`, `sample_klein_img2img`, `inject_controlnet`, `ensure_mod16` (Flux ControlNet sizing).

### 3.5 `architectures.py` (1,026 LOC) + `arch_registry.py` (179 LOC)

`ArchConfig` dataclass captures everything that varies per model family — loader, clip_mode, vae_mode, sampler, default cfg/steps/scheduler/denoise/resolution, supports_negative, lora_prefixes, prompt_style (`booru_tags` / `natural` / `minimal`), prompt_guidance, autoset flags, scene_group, extra dict.

Built-in archs: `sd15`, `sdxl`, `illustrious`, `pony`, `zit`, `flux1dev`, `flux2klein`, `flux_kontext`, `chroma`, `wan`, `ltx`, `hunyuan`. Custom archs can be registered at runtime via JSON in `spellcaster_core/archs/`.

### 3.6 `pipeline.py` (701 LOC)

Fluent pipeline:

```python
Pipeline("http://192.168.x.x:8188") \
    .txt2img("a wizard in a forest", arch="sdxl") \
    .upscale("4x-UltraSharp.pth") \
    .save("output/") \
    .run()
```

Methods: `.load`, `.txt2img`, `.img2img`, `.upscale`, `.rembg`, `.faceswap`, `.face_restore`, `.wan_video`, `.save`, `.run`, `.run_batch`. Internally calls `build_*` then routes through `dispatch_workflow`.

### 3.7 `dispatch.py` (489 LOC)

`dispatch_workflow(comfy_url, workflow, free_vram=True, privacy=True) → DispatchResult` is **the** funnel for all generations (GIMP, Guild, CLI, calibration). Steps:

1. Preflight validation (node availability + fallback substitution).
2. Workflow optimization (VRAM cap, auto-tune).
3. LLM VRAM `/free` if needed.
4. Submit to `/prompt`.
5. Poll `/history/<id>` until done.
6. Privacy cleanup of temp files.

`DispatchResult(prompt_id, outputs, elapsed, warnings)`. Robust `extract_execution_error()` handles every ComfyUI error shape.

### 3.8 Cross-interface backbone (post-2026-04-20 audit)

- `event_bus.py` (310 LOC) — process-wide singleton, publish/subscribe with replay buffer, ring buffer ~1000 events.
- `events.py` (509 LOC) — typed dataclass events: `AssetCreated`, `GenerationFinished`, `AssetSend`, etc.; `KIND` strings like `"*.asset.created"`. Each has `validate(data)`.
- `mailbox.py` (216 LOC) — per-interface pull queues. TTL 5 min, cap 100 messages.
- `interface_registry.py` (426 LOC) — `InterfaceSpec(key, ui_label, icon, detector_paths, config_flag, capabilities)`. `registry.detect_all()` at startup; `registry.heartbeat()`; `registry.is_active()` gates UI.
- `cross_interface.py` (447 LOC) — thin client every plugin imports. Falls silent when Guild unreachable — no try/except needed in callers.
- `asset_gallery.py` (352 LOC) — hash-indexed, interface-aware shared blob store (`creations/gallery/blobs/<aa>/<aabbccdd…>.png`).

### 3.9 LoRA stack

- `lora_knowledge.py` (739 LOC) — six-source knowledge aggregator: user registry → shipped JSON (`lora_calibrations_sfw.json`) → `.civitai.info` sidecar → safetensors `__metadata__` → CivitAI API by SHA-256 → heuristic defaults. Provenance retained on every field.
- `lora_calibration_store.py` (238 LOC) — persistent shootout results indexed by (model, purpose, arch).
- `lora_scorer.py` (253 LOC) — local Ollama multimodal scorer (gemma3:4b default).
- `lora_calibrations_sfw.json` — shipped public-repo defaults. NSFW companion is `nsfw/lora_calibrations_nsfw.json`.

### 3.10 Resilience

- `faceswap_health.py` (436 LOC) — state machine `AUTO_ON ↔ AUTO_OFF ↔ ESCALATED`. Crash within 60 s of dispatch → AUTO_OFF. 30-min stable window → AUTO_ON. Persists `<state_dir>/faceswap_state.json`. Env override `SPELLCASTER_FACESWAP_DISABLED=1`.
- `preflight_status.py` (272 LOC) — whole-system traffic-light health aggregator.
- `preflight.py` (474 LOC) — `/object_info` cache + fallback registry mapping broken nodes to alternatives (e.g. `RTXVideoSuperResolution` → `UpscaleModelLoader`+`ImageUpscaleWithModel`).

### 3.11 LLM modules

- `comfyui_llm.py` (696 LOC) — ComfyUI-native LLM via GGUF nodes. VRAM dance: LOAD → ENHANCE → UNLOAD → GENERATE.
- `guild_llm.py` (626 LOC) — chat backend abstraction (Ollama / KoboldCpp / LM Studio).
- `prompt_enhance.py` (693 LOC) — per-arch profiles (booru-tag style for SDXL/Illustrious, natural prose for Flux/Klein, motion vocab for WAN).

### 3.12 ComfyUI extension web UI

`comfyui-spellcaster/web/`:
- `spellcaster.js` — JS extension hooks for the ComfyUI native web UI.
- `spellcaster_status.json` — marker file written at import time.

### 3.13 Example workflows

`comfyui-spellcaster/example_workflows/`:
- `spellcaster_txt2img.json` (2.2 KB)
- `spellcaster_img2img.json` (2.3 KB)

---

## 5. Plugin layer (`plugins/`)

| Plugin | Lines | Entry | Comfy access | Maturity |
|---|---|---|---|---|
| **gimp** | comfyui-connector.py 229 + _spellcaster_main.py 37,180 | Boot shim → main | Direct HTTP | **Production** |
| **darktable** | spellcaster_steg.py + comfyui_connector.lua | Lua → subprocess Python | Direct HTTP | **Production** |
| **resolve** | bridge.py + 24 action scripts | Fusion UI + SSE | Guild-mediated | **MVP** |
| **sillytavern** | index.js (~1,000) + server-plugin.js | Extension + worker | Guild-mediated | **Feature-rich MVP** |
| **photoshop** | spellcaster.js (~400) + manifest.json | UXP panel | Guild-mediated | **Production** |
| **krita** | spellcaster_krita.py (~200) | SpellcasterPlugin class | Direct HTTP | **Stable** |
| **obs** | spellcaster_obs.py (~400) | obspython script | Direct HTTP | **MVP** |
| **blender** | spellcaster_blender.py (~100) | SpellcasterPlugin class | Direct HTTP | **Scaffold** |

### 5.1 GIMP plugin deep-dive

**Two-file split (CLAUDE.md §4):**
- `comfyui-connector.py` — **immutable** 229-line boot shim. Never auto-updated.
- `_spellcaster_main.py` — 37,180 lines, auto-updated.

The shim provides 3-tier recovery (`comfyui-connector.py:50-228`):
1. **Apply staged updates** — rename `*.update` files to original names, delete pluginrc.
2. **Download fresh** — pull `_spellcaster_main.py` from GitHub raw, validate ≥5 KB, scrub NTFS null bytes.
3. **Import attempt** with rollback: if import crashes → restore `.bak` → retry; if still fails → fresh download → retry; if still fails → register a `SpellcasterCrashed` plugin that surfaces a single visible "!! Spellcaster CRASHED — click for recovery !!" menu entry.

**Procedure registration (`do_query_procedures`, ~line 19389-19648):** v3 strategy = denylist (user disabled features in `config.json["disabled_features"]`) + allowlist from probe-cache (`config.json["features_probe"]`, TTL 1 h, populated by hitting ComfyUI `/object_info` once per session). Plus a validation gate (post-2026-04-25): `spellcaster_settings.json["validation"]["broken"]` from the installer's tiny test-workflow runs disables broken capabilities so users never see broken menu entries. Drift guard: SHA-1 of sorted procedure names; if changed, purges pluginrc.

**Caps preflight (`_caps_preflight_feature`, ~line 1913-1960):** in-session cached per-feature gate. Looks up `_FEATURE_SENTINELS` (e.g. `"klein_flux2": ("Flux2KleinRefLatentController", "Flux2KleinTextRefBalance")` — any-match). Plus the capabilities-server client (`_caps_client.py`) for vendor-specific gates. Recent commits (Apr 27-28) wired this into 32 handlers: 15 Klein, 7 video, 5 SAM3, 4 ReActor, 2 LaMa.

**Auto-updater (`spellcaster_core/auto_updater.py`):** primitives for `safe_remainder` path validation, `git_blob_sha1`, `acquire_lock` with 10-min staleness, `fetch_latest_sha`, `fetch_tree` from GitHub. Stages downloads as `*.update` files; the boot shim commits them on next launch. `comfyui-connector.py` is in the protected set.

**Image flow GIMP → ComfyUI → GIMP:**
1. User opens dialog.
2. Canvas → temp PNG via `Gimp.Image.get_pixel_rgn()` or copy-to-new + paste.
3. `build_*` builds workflow JSON.
4. `_caps_preflight_feature()` if gated.
5. POST `/api/prompt`.
6. Poll `/api/history/<id>`; download outputs.
7. Import as new layer.
8. Optional steganography metadata embed via `spellcaster_steg.py` (LSB, PBKDF2-HMAC-SHA256, SHAKE-256, scattered).

### 5.2 DaVinci Resolve

`plugins/resolve/spellcaster_bridge/` is an **event-driven SSE bridge**:
- `bridge.py` — orchestrator. Reads `~/.spellcaster/resolve_bridge.json`, connects to Guild's `/api/video/events` SSE.
- `sse_client.py` — uses `sseclient-py` (adopted 2026-04-20) with `Last-Event-ID` replay across reconnects.
- `media_pool_sync.py` — on `shot_rendered`, downloads from `/api/assets/<hash>`, imports into Media Pool under `Spellcaster/<date>/`, optionally appends to a live timeline.
- `ui_panel.py` — Fusion UI status window.

`scripts/` contains 24 action scripts (e.g. Generate from Playhead, Smart Fill Gap, Capture Timeline) that POST `/api/run_builder`. `shared/spellcaster_api.py` wraps the Guild client.

### 5.3 SillyTavern

`plugins/sillytavern/spellcaster-st/`:
- `index.js` (~1,000 LOC) — extension UI + slash commands `/scene`, `/portrait`, `/animate`. Auto-background generation every N messages (default 3). LLM "function tools" let the chat LLM autonomously trigger image gen.
- `server-plugin.js` — async generation worker so the chat UI doesn't block.
- `manifest.json`, `styles.css`, `README.md`, `test/` (unit tests).

Routes through Guild `/api/run_builder` for video; image gen optionally direct to ComfyUI.

### 5.4 Darktable

`plugins/darktable/`:
- `comfyui_connector.lua` — Darktable Lua plugin entry; right-click context menu.
- `spellcaster_steg.py` (~400 LOC) — LSB steganography (PBKDF2-HMAC-SHA256, SHAKE-256, non-sequential scatter for steganalysis resistance). Pure stdlib.
- `splash.py` — Tk splash.
- PNG/CSS assets.

Lua → Python bridge via subprocess. Embeds generation metadata into PNG pixels — survives lossless re-edits.

### 5.5 Photoshop

`plugins/photoshop/`:
- `manifest.json` — UXP v5 manifest (Photoshop 24.0+).
- `spellcaster.js` (~400 LOC) — entire plugin; **no ComfyUI knowledge**. Routes through Guild `/api/run_builder` only. Resilient to ComfyUI changes.

### 5.6 Krita / OBS / Blender

All three import `spellcaster_core.plugin_base.SpellcasterPlugin` (bundled or path-discovered). Krita exports via `doc.exportImage()`, Blender uses `bpy.ops.render.opengl()`, OBS writes generated images to disk for OBS sources to reference.

---

## 6. Distribution & installer

### 6.1 PyInstaller specs

- `Wizard_Guild.spec` (~40 LOC) — entry `tavern/wizard_guild_launcher.py`, console mode, UPX, icon `assets/wizard_guild.ico`.
- `spellcaster-manual-update.spec` (~40 LOC) — entry `installer/manual_update.py`.
- `tavern/wizard-guild.spec` — alternate spec used by `build_guild.py`.

### 6.2 `installer/`

| File | Role |
|---|---|
| `install.py` | 245 KB — main interactive installer. CLI/GUI/dry-run/auto-accept. Reads `manifest.json`, downloads/installs ComfyUI nodes + models, patches GIMP/Darktable. |
| `installer_gui.py` | 164 KB — Tk GUI front-end. |
| `bootstrap.py` | Self-update for the installer itself: fetches fresh `install.py` from GitHub, runs it via `SPELLCASTER_INSTALLER_ROOT` env var. |
| `manifest.json` | 62 KB — canonical list of 25 ComfyUI custom-node packs (20 required, 5 optional). |
| `manual_update.py` | 63 KB — standalone updater. |
| `install_remote.py` | 44 KB — remote installation flow against an antenna-managed ComfyUI. |
| `antenna_setup.py` | Installs the antenna service on the GPU host. |
| `antenna_entry.py` | Thin wrapper to launch antenna. |
| `antenna_build/` + `antenna_spec/` | PyInstaller artifacts for the antenna agent. |

### 6.3 `launcher.py`

Repo-root unified entry. Detects:
- **GIMP**: probes `%APPDATA%/GIMP/3.{0,2}/plug-ins/comfyui-connector/comfyui-connector.py`.
- **Darktable**: `comfyui_connector.lua` in `%LOCALAPPDATA%/darktable/lua/contrib/`.
- **SillyTavern**: configured dir or `~/SillyTavern`, `~/Documents/SillyTavern`.
- **Resolve**: implicit.

First-run shows the installer wizard (`tavern/guild_launcher.py --setup`). Subsequent runs show the app picker.

### 6.4 `.bat` launchers

| Bat | Role |
|---|---|
| `Install.bat` | Calls `python installer/install.py %*`. |
| `Wizard Guild.bat` | Tries `dist/Wizard_Guild.exe`, falls back to `python tavern/guild_launcher.py %*`. |
| `Settings.bat` | 284-line interactive CMD-batch settings menu. Reads/writes `guild_config.json` via findstr. Privacy warning for Horde mode. |
| `DEVNOUPDATE_NSFW Wizard Guild.bat` | NSFW dev launcher that passes `--no-update` so local edits to `tavern/`/`scaffold/` are not clobbered. |
| `rebuild.bat` | 191-line CI pipeline: clean → build SFW → build NSFW → test → push. |

### 6.5 Antenna (`antenna/`)

Lightweight HTTPS agent (zero non-stdlib deps) that runs on the GPU host. Lets remote clients install nodes/models without SSH.

| Endpoint | Status |
|---|---|
| `GET /` | liveness |
| `GET /status` | per-service probes |
| `POST /install-node` | Phase 2 — accepts manifest entries only |
| `POST /install-model` | Phase 2 stub |
| `POST /self-update` | fetch + restart |
| `POST /telemetry` | usage tracking |
| `POST /resolve/*`, `/darktable_plugin/*`, `/sillytavern_plugin/*` | cross-app bridges |

Security: TLS self-signed cert (`~/.spellcaster/antenna.{key,crt}`), 32-byte bearer token in `~/.spellcaster/antenna_token`, `hmac.compare_digest`, 30 req/min per IP, audit log to `~/.spellcaster/antenna.log`, regex allowlist on node/model names. **No arbitrary code execution** — `/install-node` only accepts entries from the canonical `manifest.json`.

---

## 7. Configuration

### 7.1 `guild_config.json` (root)

```json
{
  "guild_port": 7777,
  "comfyui_url": "http://192.168.x.x:8188",
  "kobold_url": "http://192.168.x.x:5001",
  "sillytavern_dir": "...",
  "auto_open_browser": true,
  "auto_update": true,
  "auto_launch_st": true,
  "auto_launch_kobold": false,
  "privacy_cleanup": true,
  "llm_mode": "local",         // "local" or "horde"
  "horde_api_key": "",
  "horde_model": ""
}
```

### 7.2 `tavern/guild_config.json`

Superset adding `sillytavern_url`, `signal_bridge_url`, `prompt_enhance`, `antenna_url` (`https://<LAN-host>:7334`), `antenna_token`, `app_control` (cross-app launcher map), `user_settings.guild_preset`.

### 7.3 `tavern/signal_bridge_config.json`

43 keys for Signal CLI / Signal-cli-webui integration. Includes `signal_cli_path` (e.g. `signal-cli-0.13.24`), `webui_url`/`webui_api_key`, `comfyui_output_dir`, allowed-numbers list, `poll_interval` 2 s, `rate_limit` 20 req / 60 s, `privacy.{clean_comfyui_input, clean_comfyui_output, strip_metadata_on_send, auto_delete_generated}`.

### 7.4 `comfyui-spellcaster/pyproject.toml`

```toml
[project]
name = "comfyui-spellcaster"
version = "1.0.0"
license = { file = "LICENSE" }
requires-python = ">=3.10"

[tool.comfy]
PublisherId = "laboratoiresonore"
DisplayName = "Spellcaster Nodes"
```

`requirements.txt` is minimal — runtime deps come from ComfyUI itself.

### 7.5 `.gitignore` highlights

`nsfw/` directory **completely ignored** (git refuses `git add -f`). Build artifacts (`dist/`, `build/`, `*.spec.bak`), virtual envs, user state (`tavern/.guild_state/`, `guild_config.json`, `.guild_version`), executables, and defensive credential patterns (`**/aws*key*`, `**/github_pat*`, `**/anthropic*key*`, `**/openai*key*`).

### 7.6 `.mcp.json`

Registers MCP servers (Gemini image tools, local Ollama).

### 7.7 `shootout-list.yml`

LoRA shootout matrix (~26 KB) — list of LoRAs × architectures × prompts for the calibration pipeline.

---

## 8. Active development state

### 8.1 Branches

```
* main                                ← currently checked out
  nsfw_main
+ test/e2e-audit                      ← worktree pinned
  remotes/origin/main
  remotes/nsfw/main
  remotes/nsfw/dependabot/...
```

### 8.2 Recent commit history (last 30, public repo)

| SHA | Subject |
|---|---|
| baab417 | gitignore: defensive credential patterns |
| d2d60ab | plugin: dedup redundant klein_enhancer caps preflight |
| 8ee5fe2 | plugin: caps preflight on 2 LaMa-using handlers |
| 0dda01d | plugin: caps preflight on 4 ReActor handlers |
| a284b64 | plugin: caps preflight on 7 video handlers |
| 6a5916e | plugin: caps-based preflight on 15 Klein handlers |
| 4cdcab2 | plugin: caps-based preflight on 5 SAM3 handlers |
| 35f3458 | plugin: add capabilities-server client + helper to SFW canonical |
| 8a0e4c2 | docs(readme): add self-updating callout |
| aea5945 | feat(installer): every .exe self-updates from GitHub on every launch |
| 0fadd44 | fix(installer): six more edge cases |
| f6378c7 | fix(installer+plugin): edge cases for remote ComfyUI, fully-loaded servers |
| b7a9e3b | feat(installer+plugin): close all deferred audit items |
| 07c6edf | feat(installer+plugin): asset auto-update + Refresh-from-Server menu |
| 9ef8cdf | feat(installer): jewel-polish UI + 49 locally-generated assets |
| 02e3b03 | feat(installer): end-to-end validation step + 6 bug-fix sweep |
| 19c0202 | gimp/pdb: pass real exception text into GLib.Error |
| e7dc8e6 | fix(gimp/3d-outpaint): pad normal map with neutral (128,128,255) |
| 7c1da6f | perf(gimp): kill the 50-100ms thumbnail fingerprint |
| d913789 | perf(gimp): cut GIMP→ComfyUI send overhead from ~15s to ~100ms |
| 43bb38b | klein: identity-lock extended to repose / virtual_tryon / inpaint / img2img_ref |
| e1f2fe8 | klein: identity-lock face-swap + controlnet_gen Flux vae_ref |
| 99dc973 | dispatch: robust error extractor + partial-success pass-through |
| c1ab0e5 | audit: eliminate spurious FAIL/WARN + faceswap safety skip |

**Themes:** caps-preflight rollout (most recent batch), installer self-update, Klein identity-lock, GIMP perf wins, dispatch hardening.

### 8.3 Staged changes — the "88-file refactor"

`git diff --cached --shortstat`: **88 files changed, 251 insertions(+), 202 deletions(-)**. Touches:

```
assets/
assets/wizard_guild_graphics/    ← 17 new graphics
comfyui-spellcaster/             ← 1 file
comfyui-spellcaster/nodes/       ← loader, prompt, sampler
comfyui-spellcaster/spellcaster_core/  ← ~40 files
comfyui-spellcaster/web/         ← spellcaster_status.json
plugins/gimp/comfyui-connector/spellcaster_core/  ← ~40 files (mirror)
```

The Python diff is a single mechanical refactor: **`from spellcaster_core.X` → `from .X`** (absolute → relative imports), with the matching dual-import fallback in modules like `pipeline.py` and `cli.py`. The new `comfyui-spellcaster/install.py` and `requirements.txt` add proper packaging metadata. The 17 new images under `assets/wizard_guild_graphics/` are UI artwork (hero, sidebar, icons, etc.).

The single untracked file is `_dev_docs/EVAL_LANGGRAPH_COMFYSCRIPT.md` (created today, 2026-04-30).

`EVAL_LANGGRAPH_COMFYSCRIPT.md:110`: *"Don't introduce anything until the 88-file `from .X` refactor lands."*

---

## 9. Dependencies

### 9.1 Python runtime

| Component | Deps |
|---|---|
| Guild server | **stdlib only** (optional `pystray` + `Pillow` for tray) |
| GIMP plugin | **stdlib only** (must run inside GIMP's bundled Python) |
| ComfyUI extension (`comfyui-spellcaster/requirements.txt`) | adds `huggingface_hub>=1.10`, `pyrage`, `websockets`, `sseclient-py`, optionally `zeroconf` (per Sprint 1/2 adoption) |
| ComfyUI itself | torch, transformers, diffusers, insightface, etc. — out of Spellcaster's scope |

### 9.2 ComfyUI custom-node packs (from `installer/manifest.json`)

25 packs — 20 required, 5 optional. Notable:
- **Klein/Flux 2:** `capitan01R/ComfyUI-Flux2Klein-Enhancer` (v3.2.0+). Provides the `Flux2Klein*` enhancer chain and identity-lock nodes.
- **comfyui-tooling-nodes** (Acly, GPL-3.0) — installed as sibling pack for ETN_LoadImageBase64 / ETN_SendImageWebSocket. Already cloned by `nsfw/bundle/tools/build_portable_bundle.py::_install_tooling_nodes`.
- **ReActor / SAM3 / LaMa / SUPIR / IC-Light / DDColor / BiRefNet / Wan / LTX / SeedVR / Klein** — all the model packs referenced in workflows.py.

### 9.3 LLM endpoints

- **GPU host** (LAN address per dev environment): ComfyUI :8188, KoboldCpp :5001, LM Studio :1234. Models include `qwen2.5-14b-instruct`, `qwen3-30b-a3b`, `qwen3.5-35b-a3b`, `mistral-nemo`, `deepseek-r1-qwen3-8b`, `gpt-oss-20b`.
- **This box**: Ollama (gemma3:4b) for low-VRAM scoring.

---

## 10. `_dev_docs/` — research & planning

| File | Lines | Summary |
|---|---|---|
| `RESEARCH_EXISTING_TOOLS.md` | 167 | Dump of "stop reinventing" candidates with adoption matrix. `huggingface_hub`, `pyrage`, `python-websockets`, `sseclient-py`, `comfyui-tooling-nodes`, `ComfyScript`, `ComfyUI-Manager`, `zeroconf`. Each tagged ✅ NOW / ⚖️ SOON / 🔎 EVAL / ❌ SKIP. |
| `EVAL_LANGGRAPH_COMFYSCRIPT.md` | 161 | Today's (2026-04-30) decision document. "ComfyInject" doesn't exist — likely confusion with ComfyScript. Recommendation: finish the 88-file relative-import refactor → ship websockets + ETN inline transport → ComfyScript pilot if/when next ComfyUI node-family ships. **Skip LangGraph** (architectural mismatch with the LLM-as-orchestrator design + LangChain dependency weight). |
| `AUDIT_CROSS_APP_ARCHITECTURE.md` | 209 | Reviews how 5 surfaces talk to ComfyUI/each other. GIMP is the "gold standard"; ST/DT/Resolve are less autonomous because JS/Lua/embedded-Python can't import the Python canon. Recommends Option C: add `SpellcasterWanI2V` / `SpellcasterLtxI2V` custom nodes that embed the Python canon. |
| `AUDIT_CROSS_APP_DEEP.md` | 237 | Deep-dive on Option C variants. Settles on **C.2**: register `POST /spellcaster/animate/wan` + `/spellcaster/animate/ltx` HTTP routes on ComfyUI's own server. Calls `spellcaster_core.workflows.build_wan_video()` directly, queues to ComfyUI. Keeps `wangp` backend in Guild as failsafe. |
| `AUDIT_CROSS_APP_DISCOVERY.md` | 377 | Inventory of cross-app discovery primitives. Found gaps: SillyTavern doesn't heartbeat; assets arrive without "intent" metadata; no per-plugin shot-ready subscription; AssetRecord lacks intent field. |
| `AUDIT_PLUGINS_RECIPROCAL.md` | 381 | Audits 19+ cross-app menu actions, mailbox flows, asset-metadata propagation. |
| `HANDOVER_CROSS_APP_AUDIT.md` | 536 | Consolidates phases M0–M10. Mailbox M10 known issue: consume-on-fetch loses messages on crash. |
| `HANDOVER_VIDEO_LAYER.md` | 990 | Detailed handover on WAN 2.2 / LTX 2.3 / SeedVR / shotboard state. |
| `HANDOVER_VIDEO_LAYER_PART2.md` | 157 | Continuation notes on video layer. |

---

## 11. Websockets + ETN inline transport — current status

This is the **single most important in-flight design item** mentioned in the brief. Here's the consolidated state:

### 11.1 Goal (per RESEARCH_EXISTING_TOOLS.md §3, §5)

Replace ComfyUI's `/history/<prompt_id>` poll loop with a `python-websockets` client that listens to `/ws?clientId=<cid>`, looks for the canonical completion signal (`type=executing` with `data.node==None and data.prompt_id==pid`), and consumes binary image frames sent by `ETN_SendImageWebSocket` (8-byte header `struct.pack(">II", 1, 2) + png_bytes`).

Pair with `ETN_LoadImageBase64` to embed input images as base64 inside the prompt JSON instead of using `POST /upload/image` + `GET /view?filename=`. Net effect: **no plaintext files ever touch ComfyUI's `input/`+`output/` for Spellcaster-authored workflows**, and the completion-vs-history race goes away.

### 11.2 What's already done

- ✅ `huggingface_hub` (Sprint 1 #1, 2026-04-20). `model_repair.py` uses `hf_hub_download`. `CN_REPO_MAP` is canonical.
- ✅ `sseclient-py` (Sprint 1 #2, 2026-04-20). Resolve bridge `_iter_sseclient` with `Last-Event-ID` replay; hand-rolled `_iter_sse` kept as fallback.
- ✅ `pyrage` for `.age` encryption (Sprint 2 #4, 2026-04-20). NSFW vault uses `.age`.
- ✅ `comfyui-tooling-nodes` cloned into bundle's `custom_nodes/` by `nsfw/bundle/tools/build_portable_bundle.py::_install_tooling_nodes`. Bundle's `python_embedded/` has `huggingface_hub` + `pyrage` + `websockets` + `sseclient-py` pre-installed via `step_install_pyrequirements`.
- ✅ `zeroconf` mDNS broadcast in `presence.py::_install_zeroconf_broadcast` (Sprint 3 #7, 2026-04-20). Additive — HTTP broker stays authoritative.

### 11.3 What's NOT done — explicit text from RESEARCH_EXISTING_TOOLS.md:150

> **PARTIAL** — `Acly/comfyui-tooling-nodes` git-cloned into bundle's `custom_nodes/`. Bundle's `python_embedded/` has the deps pre-installed. **STILL TODO: add `use_inline_transport=True` flag on `build_*` and wire ETN_LoadImageBase64 / ETN_SendImageWebSocket in the GIMP dispatcher** — lands when the websockets client swap (sprint 1 #3) lands, since ETN's result path is ws-binary-frame-based.

> **DEFERRED** — `python-websockets` for ComfyUI `/history` poll replacement. Full value only comes paired with ETN_SendImageWebSocket binary frames (disk-free image return). Landing both together is a future dedicated session — needs live ComfyUI testing + config flag + gradual rollout.

### 11.4 Codebase verification

`grep` for `use_inline_transport`, `ETN_LoadImageBase64`, `ETN_SendImageWebSocket`, `websockets.sync.client`, `/ws` — **zero matches in the active source tree** (only matches are inside `_dev_docs/` markdown). The bundle build script has the dep installed, but no caller code yet imports `websockets` or builds an ETN node.

`AUDIT_CROSS_APP_DEEP.md:180` notes: *"ComfyUI's built-in queue already handles concurrency, progress (`/ws` progress events), and cancellation (`/interrupt`). The C.2 route inherits all of this for free. The cancel endpoint I added in phase-8 (`POST /animate/cancel`) can be replaced with a ComfyUI-native `/interrupt` call when the prompt is current."* — implying that future websocket adoption will also obsolete some custom Guild routes.

### 11.5 Implementation plan (from EVAL_LANGGRAPH_COMFYSCRIPT.md §7)

```
Now (blocked on refactor)
└── Land 88-file relative-import refactor    ← STAGED, READY TO COMMIT
    └── Sprint A (1–2 days)
        ├── python-websockets client in dispatch.py + GIMP _spellcaster_main.py
        └── Wire ETN_LoadImageBase64 / ETN_SendImageWebSocket via use_inline_transport flag
    └── Sprint B (gated on need)
        └── ComfyScript pilot on ONE build_* (suggest: build_txt2img — smallest, well-tested)
```

**Bottom line:** the websockets + ETN inline transport is **specced but unwired**. The deps are bundled and the design document is concrete. The blocker is the staged 88-file refactor, after which it's a 1–2 day Sprint A.

---

## 12. CLAUDE.md table of contents

`CLAUDE.md` (1148 lines) is the operational source-of-truth. Its 31 numbered sections are:

```
 1. SFW / NSFW Separation
 2. Four Repos — Sync Requirements
 3. ONE SOURCE OF TRUTH: comfyui-spellcaster/spellcaster_core/
 4. Crash-Safe Boot Shim Architecture
 5. Deploying to Local GIMP Installation
 6. NSFW Build Script (nsfw/build_nsfw.py)
 7. Registration Integrity (3 dicts in _spellcaster_main.py must align)
 8. Klein/Flux 2 Enhancer Node Names
 9. Architecture-Specific Rules
10. Theme System
11. Personal Data & Leak Prevention
12. Git Commit Rules
13. Server Restarts During Testing — AUTO-UPDATE WILL CLOBBER UNCOMMITTED WORK
14. Path Separators — Central Policy
15. Installer Is Self-Updating — Bootstrap Pattern
15. Single Source of Truth — Every Asset Goes Through AssetGallery + EventBus  ← duplicate "15"
16. Canonical Video Pipelines — WAN 2.2 + LTX 2.3
17. Model Coverage & the supported_methods contract
18. GIMP Result Routing — Upscalers Open As a New Image
19. LoRA Calibration Stack — ✧ Calibration unified studio
20. Resilience — Faceswap Auto-Recovery & Preflight Status Dot
21. Summon Archetypes — 5 specialised wizard kinds
22. Quality + Speedup Cascade — quality and fast_mode parameters
23. ControlNet Compatibility Gating — cn_is_compatible
24. The /api/run_builder Bridge — Thin Plugins Into Canonical Builders
25. Cross-Interface Backbone — presence broker + blob bus + typed events
26. ControlNet File Resolution — Three-Layer System
27. GIMP Plugin Subprocess Facts
28. Retriever Homogeneity — Every Result Funnels Through _apply_mask_mode
29. Inpaint: ImageCompositeMasked Preserves Outside-Mask Pixels
30. Flux ControlNets Require VAE on ControlNetApplyAdvanced
31. Installer Step 5b — CN Coverage Audit
```

Note: there are two sections numbered "15" (Installer Bootstrap and AssetGallery+EventBus). This appears to be an accidental duplicate.

---

## 13. Tests (`tests/`)

| File | Size | Coverage |
|---|---|---|
| `e2e_audit.py` | 112 KB | End-to-end cross-app audit. |
| `e2e_report.md` | 18 KB | Human-readable audit summary. |
| `test_quality_boost.py` | 31 KB | CFG/PAG/SLG/FreeU/DetailDaemon per arch. |
| `test_klein_enhancer.py` | 20 KB | Klein sampler + enhancer chain. |
| `test_model_prompt_profiles.py` | 12 KB | Prompt rewriting per model/method. |
| `test_lora_auto_calibrate.py` | 54 KB | LoRA scoring, NSFW detection, civitai metadata. |
| `test_model_coverage.py` | 14 KB | Required-models discovery + load. |
| `test_cn_compat.py` | 8 KB | ControlNet path resolution + fallback chains. |
| `test_auto_updater.py` | 8 KB | Auto-update pull + SHA verify + rollback. |
| `test_summon_archetypes.py` | 17 KB | Prompt generator + model recommendation. |
| `test_video_layer.py` | 353 KB | WAN/LTX/frame assembly/upscale. |
| `gimp_batch.py` | 9 KB | Batch GIMP plugin processing. |
| `test_quality.py` (root) | 8.6 KB | Top-level harness. |

---

## 14. Known issues / TODOs / FIXMEs

### 14.1 In code
A grep across `comfyui-spellcaster/spellcaster_core/` for `TODO|FIXME|XXX|HACK` returns **a single match** (in `signal_notifier.py`). The codebase clearly relies on `_dev_docs/` and `CLAUDE.md` for issue tracking rather than inline TODOs.

### 14.2 In docs
- **Mailbox M10**: consume-on-fetch loses messages on crash (`HANDOVER_CROSS_APP_AUDIT.md`).
- **SillyTavern doesn't heartbeat** (`AUDIT_CROSS_APP_DISCOVERY.md`): everyone sees ST as offline in `/api/interfaces` even when running.
- **No "intent" metadata on AssetRecord**: receivers can't tell whether to use an asset as a layer, reference, or I2V seed.
- **Websockets + ETN inline transport unwired** (this doc §11).

### 14.3 Architectural debts called out by audits
- ST/DT/Resolve still depend on Guild for video — Option C.2 routes specced but not implemented.
- `ComfyScript` migration deferred until next ComfyUI node-family addition triggers it.
- `LangGraph` skipped — architectural mismatch.

---

## 15. Image generation pipeline — full data flow

End-to-end trace of a single GIMP txt2img request:

```
User clicks "Filters → Spellcaster → Text to Image"

  └─→ _spellcaster_main.py opens dialog (Tab UI)
        └─→ collects {prompt, negative, model, arch, steps, cfg, seed, loras, quality, fast_mode}

  └─→ _caps_preflight_feature(server_url, "txt2img_<arch>", "Spellcaster")
        └─→ Hits ComfyUI /object_info (cached, 1 h TTL)
            └─→ Maps required nodes via _FEATURE_SENTINELS
            └─→ Optionally calls the caps-server sidecar :8191 /v1/capabilities (graceful fallback)
        └─→ Returns (allowed, reason). Permissive default if caps server unreachable.

  └─→ build_txt2img(NodeFactory(), preset) [from spellcaster_core.workflows]
        ├─→ load_model_stack: dispatches on arch.loader (CheckpointLoaderSimple OR UNETLoader+CLIPLoader+VAELoader)
        ├─→ inject_lora_chain: chained LoraLoader nodes per LoRA spec
        ├─→ encode_prompts: CLIPTextEncode for pos; ConditioningZeroOut for neg if !arch.supports_negative
        ├─→ sample_standard or sample_klein_*: KSampler / SamplerCustomAdvanced based on arch.sampler
        ├─→ Optional cn_is_compatible() + inject_controlnet
        ├─→ Optional Klein enhancer chain (if enhance=True)
        ├─→ Optional IdentityGuidance + IdentityFeatureTransfer (if identity_latent_ref supplied)
        ├─→ VAEDecode
        └─→ SaveImage
        Returns NodeFactory().build() = {"<id>": {"class_type": ..., "inputs": {...}}, ...}

  └─→ dispatch_workflow(comfy_url, workflow, free_vram=True, privacy=True)
        ├─→ preflight_workflow: validates every node against /object_info; substitutes via fallback registry
        ├─→ optimize_workflow: VRAM cap, autotune
        ├─→ LLM /free if needed
        ├─→ POST /prompt → {"prompt_id": "..."}
        ├─→ Poll /history/<id> until done   ← (target of websockets migration)
        │     └─→ extract_execution_error on errors; retain partial outputs if any
        └─→ Privacy cleanup of temp files

  └─→ DispatchResult(prompt_id, outputs=[(filename, subfolder, "output"), ...], elapsed, warnings)

  └─→ GET /view?filename=...   ← (target of ETN_SendImageWebSocket migration)
        └─→ Receives PNG bytes

  └─→ GIMP creates new layer in original image, pastes PNG data
        └─→ Optional spellcaster_steg.embed_metadata() into RGB LSBs

  └─→ EventBus.publish("gimp.asset.created", AssetCreated(asset_hash, ...))
        └─→ Subscribers (Resolve bridge, ST extension, Guild UI) react
        └─→ AssetGallery.put() under creations/gallery/blobs/<aa>/<aabb...>.png
        └─→ Mailbox.deliver() to interfaces with capability "receive_image"

  └─→ GIMP shows toast / focuses canvas
```

The same path runs on the Guild (substituting "user typed in chat" for "user opened dialog") and on the CLI (`spellcaster_core.cli`). Every surface ends up at the same `dispatch_workflow()` funnel.

---

## 16. Quick-reference cheatsheet

| Question | Answer |
|---|---|
| Where does shared logic live? | `comfyui-spellcaster/spellcaster_core/` (canonical) |
| How many copies must stay in sync? | Six — see CLAUDE.md §3 |
| What's the workflow factory? | `node_factory.py` (2,469 LOC), `NodeFactory` class |
| How many workflow builders? | 42 `build_*` in `workflows.py` (8,276 LOC) |
| How many architectures? | 22 keys in `architectures.py` registry |
| What's the dispatch funnel? | `dispatch_workflow()` in `dispatch.py` |
| What's the cross-interface bus? | event_bus + events + mailbox + interface_registry + cross_interface + asset_gallery |
| What enables Guild-less plugin↔plugin? | `presence.py` + `blob_bus.py` on ComfyUI itself |
| How does the GIMP plugin self-recover? | 3-tier: backup → GitHub fresh → "CRASHED" menu shim |
| What's the in-flight refactor? | 88 staged files: `from spellcaster_core.X` → `from .X` |
| What's the next sprint? | Sprint A: python-websockets + ETN inline transport |
| What's in `nsfw/`? | Build script + patches for the NSFW variant (gitignored) |

---

## 17. Sources consulted

- `CLAUDE.md` (1,148 lines)
- `README.md` (531), `DEEP_DIVE.md` (1,027), `ForYourLLMwithLove.md` (317), `DEPENDENCIES.md`
- `_dev_docs/` — all 9 markdown files
- `tavern/server.py`, `guild_launcher.py`, `guild_tray.py`, `wizard-guild.spec`, `guild_config.json`, `signal_bridge_config.json`, `shotboard.json`, `activity.log`, all character cards
- `comfyui-spellcaster/__init__.py`, `presence.py`, `blob_bus.py`, `pyproject.toml`, `requirements.txt`, every file in `spellcaster_core/`
- All eight `plugins/*/` subdirectories
- `installer/` (install.py, bootstrap.py, manifest.json, manual_update.py, antenna_*)
- `antenna/` and `launcher.py`
- All `.bat` files at repo root
- `tests/` listing
- `.gitignore`, `.mcp.json`, `shootout-list.yml`
- `git log --oneline -30`, `git status`, `git diff --cached`, `git branch -a`
