# Spellcaster — Development Guide for Claude

## What This Is

Spellcaster is **middleware** between ComfyUI and user-facing apps (GIMP, Darktable, Wizard Guild chat UI, SillyTavern). It has 69 AI tools. The codebase spans 4 GitHub repos, SFW and NSFW variants, and a crash-safe plugin architecture.

## Zero Duplication Rule

**NEVER duplicate logic.** Spellcaster enforces a single source of truth for ALL shared functionality. If the GIMP plugin and the Guild server both need a function, that function lives in `spellcaster_core/` and both import it. No exceptions.

**Existing shared modules in `spellcaster_core/`:**
- `workflows.py` — ALL workflow builders (build_img2img, build_klein_*, etc.)
- `node_factory.py` — ALL ComfyUI node constructors
- `composites.py` — multi-node building blocks (load_model_stack, inject_lora_chain, etc.)
- `architectures.py` — architecture registry, ArchConfig, `supported_methods` contract (22 archs — see §17)
- `prompt_enhance.py` — LLM prompt enhancement (all backends)
- `comfyui_llm.py` — ComfyUI-based LLM text generation
- `guild_llm.py` — LLM chat abstraction (ComfyUI → KoboldCpp → Ollama)
- `privacy.py` — server file cleanup (privacy mode)
- `preflight.py` — workflow validation and node substitution
- `model_detect.py` — architecture detection + size-aware fallback (§17)
- `video_presets.py` — **canonical WAN + LTX detection + turbo/mode formulas** (see rule 16)
- `asset_gallery.py` — **canonical blob store + metadata index** for every generated image/video (see rule 15)
- `event_bus.py` — cross-interface event fan-out; `<origin>.asset.created` etc.
- `interface_registry.py` — registered consumer interfaces (GIMP, Resolve, Darktable, SillyTavern, Guild)
- `mailbox.py` — per-interface pull queues for directed asset delivery
- `cross_interface.py` — client helper for plugins to publish to inbox/bridge
- `lora_knowledge.py` — per-LoRA metadata aggregator (Civitai + safetensors + shipped defaults) — see §19
- `lora_calibration_store.py` — SFW/NSFW calibration-recipe persistence — see §19
- `lora_scorer.py` — local Ollama multimodal scorer (gemma3:4b default) — see §19
- `faceswap_health.py` — auto-recovering face-swap guard with crash attribution — see §20
- `preflight_status.py` — whole-system traffic-light health aggregator — see §20

**If you find yourself writing the same logic in two places:** STOP. Extract it into `spellcaster_core/` and have both consumers import it. The GIMP plugin at `_spellcaster_main.py` and the Guild server at `tavern/server.py` must NEVER have parallel implementations of the same feature.

## Critical Rules

### 1. SFW / NSFW Separation

**The `nsfw/` directory is gitignored. NEVER `git add -f` anything in it.**

- The PUBLIC repo (`laboratoiresonore/spellcaster`) must NEVER contain NSFW content
- NSFW presets, LoRAs, prompts, splash art live ONLY in `nsfw/` (gitignored)
- NSFW code reaches the PRIVATE repo (`laboratoiresonore/spellcaster_NSFW`) ONLY via `python nsfw/build_nsfw.py --patch --push`
- The NSFW build script copies SFW code into `nsfw/staging/`, patches it (colors, auth tokens, repo URLs, NSFW presets), validates, then pushes to the private repo
- If git says "ignored by .gitignore" for an nsfw/ file — that is CORRECT, do NOT override

### 2. Four Repos — Sync Requirements

| Repo | Visibility | What | Local Path |
|------|-----------|------|------------|
| `spellcaster` | PUBLIC | Main app (GIMP/DT/Guild/installer) | This repo |
| `spellcaster_NSFW` | PRIVATE | NSFW patched variant | Built by `nsfw/build_nsfw.py` |
| `ComfyUI-Spellcaster` | PUBLIC | 4 ComfyUI nodes | `../ComfyUI-Spellcaster` |
| `ComfyUI-Spellcaster-NSFW` | PRIVATE | Same + NSFW LoRA node | `../ComfyUI-Spellcaster-NSFW` |

### 3. ONE SOURCE OF TRUTH: `comfyui-spellcaster/spellcaster_core/`

The canonical source for all shared library code is `comfyui-spellcaster/spellcaster_core/` in THIS repo. **Five copies exist** for the files used by BOTH the ComfyUI node pack AND the GIMP/Guild app:

1. `comfyui-spellcaster/spellcaster_core/` — CANONICAL in main repo (auto-updater downloads from here)
2. `plugins/gimp/comfyui-connector/spellcaster_core/` — dev copy bundled with GIMP plugin source
3. `../ComfyUI-Spellcaster/spellcaster_core/` — public ComfyUI node repo
4. `../ComfyUI-Spellcaster-NSFW/spellcaster_core/` — private NSFW ComfyUI node repo
5. `%APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/spellcaster_core/` — installed plugin on the dev box (overwritten by auto-updater on next GIMP launch)

**Files that MUST be in sync across all 5 copies:**

| File | Why it's shared |
|---|---|
| `workflows.py` | Every workflow builder (build_img2img, build_wan_video, build_klein_*, …) |
| `node_factory.py` | ComfyUI node constructors — signature drift = runtime KeyError |
| `composites.py` | Multi-node building blocks (load_model_stack, inject_lora_chain) |
| `architectures.py` | Arch registry + ArchConfig dataclass |
| `prompt_enhance.py` | LLM-based prompt enhancement dispatcher |
| `video_presets.py` | **WAN + LTX canon** — detect_wan_preset, pick_wan_vae, wan_turbo_kwargs (see §16) |
| `pipeline.py` | Chainable fluent pipeline (Pipeline().txt2img().upscale().run()) |
| `diagnostic.py` | Live server capability probe — runs the canonical builders to validate |
| `preflight.py` | Workflow validation + node substitution |
| `model_detect.py` | Architecture detection from filename |
| `comfyui_llm.py`, `guild_llm.py` | LLM chat abstractions |
| `privacy.py` | Server file cleanup |
| `asset_gallery.py`, `event_bus.py`, `interface_registry.py`, `mailbox.py`, `cross_interface.py` | Cross-interface backbone (see §15) |
| `lora_knowledge.py`, `lora_calibration_store.py`, `lora_scorer.py` | LoRA calibration stack (see §19) |
| `faceswap_health.py`, `preflight_status.py` | Resilience layer (see §20) |
| `lora_calibrations_sfw.json` | Shipped SFW calibration recipes (PUBLIC repo). NSFW companion lives in `nsfw/lora_calibrations_nsfw.json` and is patched in by `build_nsfw.py` |
| `events.py` | Typed event schema — dataclass per canonical bus kind (see §17) |

**Pack-root modules (NOT inside `spellcaster_core/`) that also mirror:**

| File | Where | Why |
|---|---|---|
| `presence.py` | `comfyui-spellcaster/presence.py` | Peer-discovery broker on ComfyUI (see §17) |
| `blob_bus.py` | `comfyui-spellcaster/blob_bus.py` | Guild-less asset transport on ComfyUI (see §17) |

Mirror `presence.py` + `blob_bus.py` to `../ComfyUI-Spellcaster/` and `../ComfyUI-Spellcaster-NSFW/` (pack roots, NOT `spellcaster_core/` subdirs). The GIMP dev copy does NOT carry these — plugins that need the routes hit ComfyUI over HTTP, they don't import them.

**After ANY change to the above files:**

```bash
# 1. Edit the CANONICAL copy:
#    comfyui-spellcaster/spellcaster_core/CHANGED_FILE.py
# 2. Mirror to the other 4 surfaces:
cp comfyui-spellcaster/spellcaster_core/CHANGED_FILE.py \
   plugins/gimp/comfyui-connector/spellcaster_core/
cp comfyui-spellcaster/spellcaster_core/CHANGED_FILE.py \
   ../ComfyUI-Spellcaster/spellcaster_core/
cp comfyui-spellcaster/spellcaster_core/CHANGED_FILE.py \
   ../ComfyUI-Spellcaster-NSFW/spellcaster_core/
cp comfyui-spellcaster/spellcaster_core/CHANGED_FILE.py \
   "%APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/spellcaster_core/"  # deploys for local GIMP test
# 3. Commit + push in all THREE git repos (spellcaster, ComfyUI-Spellcaster, ComfyUI-Spellcaster-NSFW)
# 4. Rebuild NSFW: python nsfw/build_nsfw.py --patch-only --push
# 5. Verify mirrors are identical:
md5sum comfyui-spellcaster/spellcaster_core/CHANGED_FILE.py \
       plugins/gimp/comfyui-connector/spellcaster_core/CHANGED_FILE.py \
       ../ComfyUI-Spellcaster/spellcaster_core/CHANGED_FILE.py \
       ../ComfyUI-Spellcaster-NSFW/spellcaster_core/CHANGED_FILE.py
```

**If you skip the canonical sync, the auto-updater will OVERWRITE your changes on next GIMP launch** — it downloads from `comfyui-spellcaster/spellcaster_core/`, so that copy MUST be the one you edited.

**The `.claude/agents/sync-checker` agent does this audit for you** — run it before any commit touching shared files.

### 4. Crash-Safe Boot Shim Architecture

The GIMP plugin is split into two files:
- `comfyui-connector.py` — **IMMUTABLE** 228-line boot shim. Never auto-updated. Never modified.
- `_spellcaster_main.py` — 22K+ line actual plugin. Auto-updated normally.

The shim provides 3-tier recovery: backup → GitHub download → visible "CRASHED" menu entry. The auto-updater in `_spellcaster_main.py` has `comfyui-connector.py` in its protected set — it will never overwrite or delete the shim.

### 5. Deploying to Local GIMP Installation

The installed plugin is at: `%APPDATA%\GIMP\3.2\plug-ins\comfyui-connector\`

After modifying `_spellcaster_main.py`:
```bash
# Delete any .update files (from auto-updater)
rm -f "%APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/"*.update
rm -f "%APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/spellcaster_core/"*.update
# Copy the file
cp plugins/gimp/comfyui-connector/_spellcaster_main.py "%APPDATA%/GIMP/3.2/plug-ins/comfyui-connector/"
# Clear procedure cache
rm -f "%APPDATA%/GIMP/3.2/pluginrc"
```

**The NSFW auto-updater pulls from `spellcaster_NSFW` repo.** If you only push to the main repo, the NSFW installation will revert your changes. Always run `nsfw/build_nsfw.py --patch --push` after pushing to main.

**See Rule 13 for the full auto-update risk matrix.** Short version: a GIMP restart or Guild restart will re-download from GitHub and overwrite anything uncommitted in the plugin dir / `tavern/` / `scaffold/`. Commit before restarting, or use `DEVNOUPDATE_NSFW Wizard Guild.bat` for the Guild.

### 6. NSFW Build Script (`nsfw/build_nsfw.py`)

The build script patches the SFW code for NSFW distribution:
- `--patch` — Apply all NSFW patches to staging
- `--push` — Push staged files to private GitHub repo
- `--build` — Compile Windows .exe installers
- `--patch --push` — Most common: patch and push

After the shim split, the NSFW build patches `_spellcaster_main.py` (NOT `comfyui-connector.py`). It targets the file by checking both filenames with fallback.

### 7. Registration Integrity

Every GIMP procedure must appear in ALL THREE dicts in `_spellcaster_main.py`:
1. `_PROC_FEATURES` — feature gate (None = always show)
2. `menu_map` — label, callback, docstring
3. `_menu_paths` — GIMP menu location

If a procedure is in `menu_map` but NOT in `_PROC_FEATURES`, it will never register and silently not appear in GIMP menus.

### 8. Klein/Flux 2 Enhancer Node Names

The correct ComfyUI class_type names (from `/object_info`, NOT hallucinated):
- `Flux2KleinRefLatentController` (NOT "FLUX.2 Klein Ref Latent Controller")
- `Flux2KleinTextRefBalance` (NOT "FLUX.2 Klein Text/Ref Balance")
- `Flux2KleinColorAnchor` (NOT "Color Anchor")
- `Flux2KleinMaskRefController`

Always verify node names against the actual ComfyUI server at `/object_info`.

### 9. Architecture-Specific Rules

**The authoritative list is `spellcaster_core/architectures.py`**, which registers 22 arch keys (8 fully-built + 14 covering video + SDXL-variants + DiT stubs). See §17 for the full coverage matrix. The table below lists the CORE 8 whose workflow builders are deeply integrated; for any other arch, `get_arch(key)` returns an ArchConfig with correct defaults but callers must check `arch.supports_method(m)` before dispatching.

| Architecture | Supports Negative | Sampler | ControlNet | Enhancer |
|-------------|-------------------|---------|------------|----------|
| sd15 | Yes | KSampler | Yes | No |
| sdxl | Yes | KSampler | Yes | No |
| illustrious | Yes | KSampler | Yes | No |
| zit | Yes | KSampler | Yes (Union) | No |
| flux1dev | No | KSampler | Yes (Union Pro) | No |
| flux2klein | No | SamplerCustomAdvanced | No (skip) | Yes (default ON) |
| flux_kontext | No | KSampler | No (skip) | No |
| chroma | No | KSampler | No (skip) | No |

- Klein/Kontext/Chroma: NEVER inject ControlNet, NEVER encode negative prompts (use conditioning_zero_out)
- Klein: ALWAYS use CFGGuider + BasicScheduler (not KSampler)
- Flux/Kontext: NEVER use quality tags ("masterpiece", "8k" etc.)
- Prompt enhancement: SKIP for flux_kontext (edit instructions) and zit (too fast)
- **Every workflow builder calls `_assert_method_for_preset(preset, method)` at entry** — raises `UnsupportedMethodError` if the preset's arch doesn't declare `method` in its `supported_methods` tuple. This catches e.g. `build_wan_video` called with an SDXL preset, or `build_txt2img` called with an SD3 stub. See §17.

### 10. Theme System

The premium theme is OPT-IN only. Default is UNBRANDED.
- `_apply_spellcaster_theme()` checks `config.json {"apply_theme": true}` and returns immediately if false
- The installer checkbox defaults to OFF
- Darktable theme install is gated by `spellcaster_config.json {"apply_theme": true}`

### 11. Personal Data & Leak Prevention

**NEVER commit any of these to ANY public repo:**
- Real IP addresses (use `192.168.x.x` in examples/tooltips)
- Usernames or local paths (`C:\Users\redacted\...` → use relative paths or `%APPDATA%`)
- Email addresses
- GitHub tokens (`ghp_...`)
- API keys for any service
- The user's actual ComfyUI server address

**Before every commit, verify:**
```bash
# Check staged files for personal data
git diff --cached | grep -iE "192\.168\.86\.|redacted|redacted|@gmail|ghp_"
```

**Files that must NEVER be tracked (gitignored):**
- `config.json` — GIMP plugin config (has server URLs)
- `guild_config.json` / `tavern/guild_config.json` — has local paths
- `session_state.json` / `user_presets.json` — user session data
- `.guild_state/` — generated avatar state
- `.claude/` — Claude Code internal files
- `nsfw/` — NSFW content (critical — PUBLIC repo)
- `tavern/creations/` — generated images (could be NSFW)

**If a file is already tracked that shouldn't be:**
```bash
git rm --cached path/to/file   # removes from tracking, keeps file locally
```

### 12. Git Commit Rules

- NEVER use `git add -A` or `git add .` — always add specific files by name
- NEVER use `git add -f` on gitignored files (especially nsfw/)
- Before pushing, check for accidentally staged personal data
- Use descriptive commit messages that explain WHY, not just WHAT
- Always include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (bump the version label when the active model changes)

### 13. Server Restarts During Testing — AUTO-UPDATE WILL CLOBBER UNCOMMITTED WORK

**Before restarting the Wizard Guild, the GIMP plugin, or the installer, check
for uncommitted local changes and warn the user if any exist.**

Three different auto-updaters run on startup and DOWNLOAD from GitHub, then
OVERWRITE local files and DELETE anything not in remote:

| Component | Updater | Runs when | Protected files | What gets clobbered |
|-----------|---------|-----------|-----------------|----------------------|
| **Wizard Guild** | `tavern/guild_launcher.py:check_for_updates` | every launch | `guild_launcher.py`, `guild_config.json`, `guild_common.py` | everything under `tavern/` and `scaffold/` |
| **GIMP plugin** | `plugins/gimp/comfyui-connector/_spellcaster_main.py:_auto_update` | GIMP start | `comfyui-connector.py` (boot shim), `config.json`, `.spellcaster_version`, `user_presets.json`, `session_state.json` | everything else in the plugin dir + `spellcaster_core/` copy |
| **Installer** | `installer/bootstrap.py` | every .exe launch | n/a (runs in temp dir) | nothing — bootstrap uses an ephemeral dir |

**What this means for Claude during a session:**

1. **Before recommending a Guild restart**: run `git status -s | grep -E "tavern/\|scaffold/"`. If anything is modified or untracked, warn the user — their changes will be overwritten unless they commit first OR use `--no-update`.

2. **Before recommending a GIMP restart after editing `_spellcaster_main.py` or `spellcaster_core/`**: same check on `plugins/gimp/comfyui-connector/`. If there are uncommitted changes, offer to either (a) sync to local GIMP via the deploy procedure first, (b) commit and push so the auto-updater is a no-op, or (c) disable auto-update temporarily.

3. **Safe-restart options in order of preference**:
   a. **Commit and push** (cleanest) — auto-update downloads exactly what's already there.
   b. **Use the no-update launcher** — `DEVNOUPDATE_NSFW Wizard Guild.bat` at repo root skips the Guild updater. For the GIMP plugin, no direct equivalent exists; delete `.update` files if needed.
   c. **Set `auto_update: false`** in `guild_config.json` (Guild only) for longer debug sessions.
   d. **Stash** (last resort) — `git stash push -m "WIP: before restart"` isolates local edits.

4. **Never tell a user a restart is "safe" without checking first.** The Guild's auto-updater also PRUNES — files in your local tavern/ or scaffold/ that aren't in remote get DELETED.

5. **When Claude makes changes that need a running server to test**: commit first, then restart. Do not ask the user to restart to see your changes while your edits are uncommitted — the restart will erase them.

### 14. Path Separators — Central Policy

**Paths are platform-specific but we standardize HOW we handle them.**

| Context | Separator | Rationale |
|---------|-----------|-----------|
| Internal Python code (always) | `pathlib.Path` objects | OS-native, no manual concat |
| Config file values (JSON) | Forward slash `/` | Escaping-free, Windows accepts them |
| API response bodies (JSON) | Forward slash via `.as_posix()` | Clients don't have to escape |
| Subprocess argv on Windows | Platform-native via `str(path)` | Some `.bat` launchers are picky |
| Error messages / logs | Whatever repr gives | Human-readable, OS-appropriate |
| ComfyUI workflow JSON (builders) | **Filenames only — no full paths** | ComfyUI resolves against input/output dirs; DON'T change this |

**Rules of thumb:**
- Inside Python, always use `pathlib.Path`. Never build paths with `+` or f-strings.
- When accepting paths from JSON, `Path(os.path.expanduser(s))` handles both separators transparently.
- When emitting paths TO JSON, prefer `.as_posix()`.
- The **workflow builders in `spellcaster_core/workflows.py`** DELIBERATELY use only filenames (not full paths) because ComfyUI resolves them server-side. Touching this is a minefield — don't.

### 15. Installer Is Self-Updating — Bootstrap Pattern

`spellcaster-installer.exe` is now a two-stage runner ([`installer/bootstrap.py`](installer/bootstrap.py)):

1. Bootstrap fetches the latest `install.py`, `installer_gui.py`, and `manifest.json` from `raw.githubusercontent.com/laboratoiresonore/spellcaster/main` into a temp dir.
2. Execs the fetched code via `importlib`, passing `SPELLCASTER_INSTALLER_ROOT=<temp_dir>` so the fetched install.py finds the fetched manifest.
3. On fetch failure (no network, rate limit, etc.), falls back to the baked-in copy.

**What this means for Claude:**

- **You no longer need to rebuild the .exe for most installer fixes.** Editing `installer/install.py`, `installer/installer_gui.py`, or `installer/manifest.json` and pushing to main is enough — every existing .exe picks it up on next launch.
- **The .exe only needs rebuilding when**: `bootstrap.py` itself changes, `build_installer.py` flags change, a NEW bundled asset is added (e.g. a new `plugins/` dir), or the PyInstaller hidden-imports list needs updating.
- **The assets stay baked**: `plugins/`, `tavern/`, `scaffold/`, `assets/` are bundled. Asset finders (`_find_gimp_plugin_src`, `_find_tavern_src`, `_find_scaffold_src`) consult both `SCRIPT_DIR` (fetched temp dir) and `BUNDLE_DIR` (PyInstaller `_MEIPASS`). So bootstrapped runs can still locate bundled assets.
- **Offline fallback** — users without internet still get the baked-in version, which is guaranteed-working at build time.

### 15. Single Source of Truth — Every Asset Goes Through `AssetGallery` + `EventBus`

The cross-interface backbone provides ONE canonical blob store (`tavern/creations/gallery/`) and ONE event bus. Every generated asset — image or video, produced by the Guild, GIMP plugin, Darktable plugin, DaVinci Resolve bridge, SillyTavern, or any future surface — MUST flow through:

1. **`spellcaster_core.asset_gallery.AssetGallery.put(data, origin=..., kind=..., prompt=..., model=..., seed=..., tags=..., meta=...)`** — stores the blob (content-hash addressed, sharded by first two hex chars), upserts the metadata record, and returns an `AssetRecord` with a stable `.hash`.
2. **`spellcaster_core.event_bus.EventBus.default().publish(f"{origin}.asset.created", origin=..., data={...})`** — notifies subscribers (Resolve Bridge, GIMP gallery publisher, Signal notifier, future interfaces). The event includes `asset_hash` so subscribers can `GET /api/assets/<hash>` for the bytes.
3. **Return the canonical URL `/api/assets/<hash>`** — served by `GuildHandler._handle_assets_get`. Never return raw ComfyUI `/view?filename=...` URLs to the browser; they break the moment privacy cleanup runs.

**The Guild-side entry point is `_cache_comfyui_asset` in `tavern/server.py`.** It downloads a ComfyUI `/view` URL, calls `AssetGallery.put`, publishes the event, and returns `/api/assets/<hash>`. New callers:

```python
cached_url = _cache_comfyui_asset(
    view_url, "image",
    kind="generation",                    # or "avatar", "background", "shot", "upscale", "inpaint", ...
    prompt=positive_prompt,
    model=ckpt or unet_filename,
    seed=seed,
    title="optional short label",
    tags=[arch_key, wizard_name],
    meta={"char_id": char_id, "arch": arch_key},
)
```

**GIMP / Resolve / other plugins** that post generated bytes to the Guild from outside use `POST /api/<iface>/inbox` with `body_b64` — the endpoint handler already routes the bytes through `AssetGallery.put` and emits the event. Do NOT add a second storage path on the plugin side.

**What's banned:**
- Writing generated bytes to any flat directory keyed by URL or filename hash (the old `_cache_comfyui_asset` behavior).
- Returning raw ComfyUI `/view?filename=...` URLs to the browser.
- Bypassing the EventBus when a generation completes — no `asset.created` event means cross-interface subscribers are blind.
- Rolling a bespoke blob store in a plugin or a scaffold.

**Compat shims (legacy, do not extend):** `/api/cached_asset/<name>` still serves files from the pre-refactor flat cache so old `generated_assets.json` entries keep working. `_cache_comfyui_asset` falls back to that flat cache only when `_ASSET_GALLERY is None` at import (cross-interface backbone failed to initialize). New code paths must tolerate both URL shapes when parsing (`'/api/assets/' in url or '/api/cached_asset/' in url`), but must produce only the canonical shape.

**What to check on every PR:**
- Any new call that downloads from ComfyUI goes through `_cache_comfyui_asset` (Guild) or `_upload_bytes_to_comfyui` → `AssetGallery.put` path (plugin ingest).
- Any new generation path emits an `<origin>.asset.created` event (either via `_cache_comfyui_asset(..., emit_event=True)` or explicitly).
- No `os.path.join(_ASSET_CACHE_DIR, ...)` writes outside the `_cache_comfyui_asset` fallback branch.
- No new `/api/cached_asset/*` writer endpoints. Readers are fine (legacy compat).

### 16. Canonical Video Pipelines — WAN 2.2 + LTX 2.3

This section is **the canon** for every WAN / LTX generation in the app. The recipe below produced the "perfect" LTX gen and the restored WAN I2V on the user's RTX 5060 Ti. **Do not diverge. Do not re-invent.** The files that detected / tuned / dispatched WAN + LTX used to live in five separate modules with gradually drifting copies; we consolidated them so anything new goes through `spellcaster_core.video_presets`.

#### 16.1 The single source of truth

| Concern | Canonical API | Lives in |
|---|---|---|
| Detect WAN models on a ComfyUI server | `video_presets.detect_wan_preset(comfy_url)` | `spellcaster_core/video_presets.py` |
| Detect LTX models on a ComfyUI server | `video_presets.detect_ltx_preset(comfy_url)` | same |
| WAN turbo vs full-step params | `video_presets.wan_turbo_kwargs(turbo=bool)` | same |
| LTX mode params (distilled / full / two_stage / i2v) | `video_presets.ltx_mode_kwargs(mode)` | same |
| Build WAN workflow | `workflows.build_wan_video(preset, **kwargs, **wan_turbo_kwargs(turbo))` | `spellcaster_core/workflows.py` |
| Build LTX workflow | `workflows.build_ltx_video(preset, **ltx_mode_kwargs(mode), ...)` | same |

**Every consumer imports these functions.** No `_detect_wan_preset` / `_detect_ltx_preset` copies in `tavern/server.py`, `scaffold/video_workflow_dispatch.py`, `spellcaster_core/pipeline.py`, plugins, or anywhere else. If a consumer needs the result cached, the cache wraps `detect_wan_preset()` — the detection itself stays canonical.

#### 16.2 WAN 2.2 — full formula

**Model family selection (I2V ONLY — the other families crash):**

| Family | Filename tags | Channels | Action |
|---|---|---|---|
| WAN 2.2 14B I2V-A14B | `wan…14b…i2v` | patch_embedding 36ch | ✅ Use for Spellcaster |
| WAN 2.2 14B T2V-A14B | `wan…14b…t2v` | patch_embedding 36ch | ❌ Refuse (T2V workflow only) |
| WAN 2.2 5B TI2V       | `wan…5b…ti2v` | patch_embedding 64ch | ✅ Usable (different VAE pair) |
| Generic "wan"         | no i2v/t2v tag | unknown             | ❌ Refuse (may crash 36/64 ch mismatch) |

Feeding a T2V model into an I2V workflow crashes with
`expected input to have 36 channels, but got 64 channels` mid-sampling.
`detect_wan_preset` refuses generic/T2V and logs a warning.

**VAE pairing (must match UNET family):**

| UNET family | VAE (prefer) | Avoid |
|---|---|---|
| 14B I2V-A14B | `wan_2.1_vae.safetensors` / `wan2_1_vae.safetensors` / `wan2.2_vae_14b.*` | `wan2.2_vae.safetensors` (the TI2V-5B VAE — crashes on 14B) |
| 5B TI2V     | `wan2.2_vae.safetensors`                                                   | (none) |

`pick_wan_vae(unet_name, vae_list)` encodes this. Any other pairing burns the first conv layer at runtime.

**CLIP (text encoder):**
- Prefer GGUF umt5xxl / t5xxl via `CLIPLoaderGGUF`.
- Fall back to fp8/safetensors via `CLIPLoader` only when no GGUF match.
- Both are wan-type CLIPs; never substitute a Flux or SD clip.

**Acceleration LoRAs (HIGH + LOW pair):**
- LightX2V I2V or Lightning I2V, split by "high" / "low" in filename.
- T2V accel LoRAs are REJECTED — silently distort I2V output.
- Stored on the preset as `high_accel_lora` + `low_accel_lora` + `accel_strength=1.5`.

**Turbo vs full-step — the formula:**

| Param | TURBO (`turbo=True`) | FULL-STEP (`turbo=False`) |
|---|---|---|
| steps | 6 | 30 |
| cfg | 1.0 | 3.5 |
| second_step (high→low crossover) | 3 | 15 |
| Accel LoRAs applied? | Yes (when present) | No (ignored even if present) |
| Default in animated-avatar baker | ❌ (produces black frames on user's box) | ✅ |
| Opt-in via env | `SPELLCASTER_WAN_TURBO=1` | (default) |

Turbo targets the LightX2V / Lightning 4-step distillation. On the user's RTX 5060 Ti, the shipped 4-step LoRAs + `cfg=1.0` produced pure-black output (mean luminance 0.0/255). Full-step is the reliable default; turbo is an opt-in escape hatch for servers whose model/LoRA combo tolerates it. The formula lives in `video_presets.wan_turbo_kwargs(turbo)` — every WAN caller passes its result as `**kwargs` into `build_wan_video`.

**LoRA injection (high/low split):**
- `loras_high` → applied to the HIGH noise model (frames 0..second_step-1).
- `loras_low`  → applied to the LOW  noise model (frames second_step..end).
- Both lists live in the preset OR are passed explicitly.
- `inject_lora_chain` is NOT used for WAN — the builder calls `nf.lora_loader_model_only` directly so arch-filter logic doesn't drop WAN-specific LoRAs.

**Pixel dimensions:**
- Width + height MUST be multiples of 16. `build_wan_video` does NOT re-round; callers pre-round via `round_to_mod(16)`.
- The 512×512 avatar baker + the 832×480 / 1280×720 shot presets are all mod-16 clean.

**Known-good presets:**
- Animated avatars (Guild): 512×512 · 33 frames · fps=16 · pingpong=True · turbo=False.
- Shotboard I2V default: 832×480 · 81 frames · fps=16 · turbo=True (lightning preset).
- Shotboard I2V HQ: 1280×720 · 81 frames · fps=16 · turbo=False.

**Optional quality + speed patches (auto-probed by the GIMP wrapper):**

| Patch | Node class | Gain | Pack |
|---|---|---|---|
| SLG — Skip Layer Guidance | `SkipLayerGuidanceSD3` | Cleaner motion (layers 7,8,9 skipped during CFG) | Core ComfyUI |
| NAG — Normalized Attention Guidance | `WanVideoNAG` | Sharper motion, less drift | Kijai WanVideoWrapper |
| SAGE — Sage Attention | `PatchSageAttentionKJ` | **50–100% sampler speedup** on RTX 40/50xx | KJNodes |
| CFG Zero Star | `CFGZeroStar` | Small quality win (no CFG on step 0) | Core ComfyUI (recent) |

All four are probed at runtime via `/object_info` in `_wan_quality_patches_available` (GIMP wrapper). If the node is present they auto-enable; missing nodes silently skip. No server-specific hardcoding.

**Auto-TeaCache:** `teacache=None` (the default for `build_wan_video`) resolves to `True` for full-step mode (non-turbo) — saves 30–40% time on 30-step runs. Turbo already fast enough, so `teacache=False` when `turbo=True`. Explicit `teacache=True/False` overrides the auto-choice.

**CausVid support:** `video_presets.pick_wan_accel_loras` now matches the CausVid temporal-stabilisation LoRA family (reduces frame-to-frame flicker). Stacks cleanly with lightx2v/lightning; preset's `high_accel_lora`/`low_accel_lora` fields pick whichever family the server has.

**Sampler override:** `build_wan_video(sampler_name=..., scheduler=...)` accepts per-call overrides (default `euler`/`simple` unchanged). Advanced users can try `dpmpp_2m_sde`/`karras` for full-step runs.

#### 16.3 LTX 2.3 — full formula

**Model family:**
- One UNET family (22B dev or 13B). Prefer filenames tagged `2.3` / `22b` / `13b`. `.gguf` is auto-dispatched to `UnetLoaderGGUF`; `.safetensors` goes to `UNETLoader`.
- Text encoder: Gemma-3 via `LTXAVTextEncoderLoader` (Kijai's custom pack).
- Embeddings connector: `ltx*connector*` via the same loader.
- VAE: `ltx-video-vae.*`. **NOT** the WAN VAE. Using a WAN VAE produces green/yellow noise.
- Distilled LoRA: `ltx*distill*` — enables the 8-step fast path.

**Mode formula:**

| Mode | distilled | two_stage | steps | cfg | stg | rescale | Notes |
|---|---|---|---|---|---|---|---|
| `distilled` | True | False | 8 (auto) | 1.0 (auto) | 0.0 (auto) | 0.0 (auto) | Default fast path — 4× faster than full |
| `full` | False | False | 30 | 4.0 | 1.0 | 0.7 | Quality > speed |
| `two_stage` | False | True | 30 | 4.0 | 1.0 | 0.7 | Gen at half-res → 2× latent upscale → refine |
| `i2v` | True | False | 8 (auto) | 1.0 (auto) | 0.0 (auto) | 0.0 (auto) | Caller also passes `image_filename` + `i2v_strength` |

Use `ltx_mode_kwargs("distilled")` / `("full")` / `("two_stage")` / `("i2v")` — returns the right `{distilled, two_stage}` kwargs for `build_ltx_video`.

**Default subtitle-burn-in negative (auto-injected when negative_text is None):**
```
text, subtitles, captions, watermark, logo, timestamp, UI, interface,
closed captions, overlay, written letters, typography
```
LTX 2.3's distilled corpus includes subtitled video, so without this the model reproduces subtitles. Callers that want a custom negative pass it verbatim.

**VRAM optimisation:**
- `LTXVChunkFeedForward` with `chunks=4` on every LTX workflow (canon default; override via `build_ltx_video(chunk_size=...)`).
- `LTXVApplySTG` on layers `14, 19` (Spatial-Temporal Guidance; override via `build_ltx_video(stg_layers="14, 19, 22")`).
- Both are core to the canon; removing either tanks quality.

**Optional quality + speed patches (auto-probed by the GIMP LTX dialog):**

| Patch | Node class | Gain | Pack |
|---|---|---|---|
| SAGE — Sage Attention | `PatchSageAttentionKJ` | **50–100% sampler speedup** on RTX 40/50xx, neutral quality. Applied BEFORE `LTXVChunkFeedForward` so the whole chain uses the kernel. | KJNodes |
| CFG Zero Star | `CFGZeroStar` | Small quality win (no CFG on step 0). Auto-skipped in distilled mode (cfg=1.0). | Core ComfyUI (recent) |

TeaCache / SLG / NAG do **not** apply to LTX — LTX uses `LTXVBaseSampler` + `STGGuider` (different sampler path from Wan's `KSamplerAdvanced`).

**Sampler override:** `build_ltx_video(sampler_name=...)` accepts per-call overrides (default `"euler"`). Full-step runs can try `dpmpp_2m_sde` or `heun`; distilled mode is tuned for euler and usually regresses on other samplers.

**VAE decode tiling knobs** — `LTXVSpatioTemporalTiledVAEDecode` is parameterised via `build_ltx_video(vae_spatial_tiles=..., vae_temporal_tile_length=..., vae_last_frame_fix=..., vae_working_dtype=...)`. Canon defaults: `spatial_tiles=4`, `temporal_tile_length=16`, `last_frame_fix=False`, `working_dtype="auto"`. Low-VRAM users raise `spatial_tiles` to 6–8; RTX 50xx users hitting garbled last frames set `last_frame_fix=True` or `working_dtype="bf16"`. The GIMP dialog's Advanced section exposes all four.

**Extra LoRAs** — `build_ltx_video(loras=[("style/cinematic_v2.safetensors", 0.8), ...])` accepts a list of `(name, strength)` tuples applied AFTER the distilled LoRA. The GIMP dialog exposes 3 slots with strength spinners and a "Fetch LoRAs from server" button.

**Canonical builder signature — the full kwargs surface (29 args):**

```python
build_ltx_video(
    preset, prompt_text, seed,                         # required
    width=768, height=512, num_frames=25,              # geometry
    steps=None, cfg=None, stg=None, rescale=None,      # sampling (None → preset default)
    two_stage=False, distilled=False,                  # mode (pair with ltx_mode_kwargs)
    loras=None, interpolate=False, rtx_scale=0,        # post-processing
    fps=25, pingpong=False,                            # output
    image_filename=None, i2v_strength=0.9,             # I2V conditioning
    negative_text=None,                                # None → auto subtitle blocker
    enable_sage=False, enable_cfg_zero=False,          # optional patches
    sampler_name=None, stg_layers=None, chunk_size=None,         # tuning
    vae_spatial_tiles=None, vae_temporal_tile_length=None,       # VAE tiling
    vae_last_frame_fix=False, vae_working_dtype=None,            # VAE dtype/fix
)
```

Every live caller in the app is audited against this surface — see §16.6 for the full call-landing table.

**LTX model presets in the GIMP dialog** — `LTX_PRESETS` dict in `_spellcaster_main.py` carries 7 variants: 22B GGUF Q4_K_M / Q5_K_M / Q6_K / Q8_0 / fp8 scaled / bf16, plus 13B GGUF Q4_K_M. Shared fields (text encoder, VAE, embeddings connector, distilled LoRA, upscaler) are factored into `_LTX_COMMON` so adding a new variant is a one-liner. Users with non-standard filenames can use the Guild shot API (`detect_ltx_preset` handles detection automatically server-side).

**Scene template library** — `LTX_VIDEO_PRESETS` in `_spellcaster_main.py` has ~35 SFW entries tuned to LTX's strengths: VFX (fireball explosions, dancing flames, lightning, sparks, magic spells, volumetric smoke), weather (rain/snow/fog/dust), liquid physics (water splash, wave crash, pour), cinematic camera moves (golden-hour pan, dolly-in, orbital tracking, crane reveal), lighting (neon cyberpunk, moonlit forest, candlelit), sci-fi (hologram, laser, energy aura), portrait micro-motion, cinemagraph loops, particle abstract. Each prompt is 80–150 words so LTX's cinematic prior engages. NSFW build injects 15 additional entries at the `# ── NSFW_LTX_INJECTION_POINT ──` sentinel during `nsfw/build_nsfw.py --patch`.

**GIMP LtxVideoDialog exposes:**
- preflight node check (warning banner if `LTXVBaseSampler` / `LTXAVTextEncoderLoader` / `LTXVApplySTG` / `LTXVSpatioTemporalTiledVAEDecode` missing)
- prompt enhance checkbox (async via `_run_with_spinner`; uses LTX profile in `prompt_enhance.py`)
- negative prompt field (empty = canon default subtitle blocker)
- aspect ratio preset buttons (9:16 / 1:1 / 16:9 / 21:9 snapped to mod-32)
- scene template combobox (~35 SFW + 15 NSFW)
- mode checkboxes (distilled / two_stage — mutually exclusive)
- steps / cfg / stg / rescale / seed / width / height / frames / fps / i2v strength / rtx_scale / runs
- Advanced: SAGE / CFG Zero (tri-state auto/on/off), sampler combo (euler / euler_ancestral / dpmpp_2m / dpmpp_2m_sde / heun / uni_pc), STG layers entry, chunk size spin, VAE spatial/temporal tiles, last-frame-fix check, VAE dtype combo
- 3 LoRA slots + fetch button
- preset save/load bar

#### 16.4 Boundary rules

1. **No parallel detection.** If you see `_detect_wan_preset` / `_detect_ltx_preset` anywhere outside `spellcaster_core/video_presets.py`, delete it and import the canonical one. Same for WAN VAE pairing and turbo kwargs.
2. **No parallel turbo formula.** Every `build_wan_video(…, turbo=…)` call must pair with `**video_presets.wan_turbo_kwargs(turbo)` OR the caller has a comment explaining why it deviates.
3. **Preset fields are additive only.** `detect_wan_preset` returns a stable dict shape; code downstream reads by key. Don't rename keys — extend.
4. **Plugin path:**
   - Python plugins (GIMP `_spellcaster_main.py`, Resolve scripts) call `build_wan_video` + `build_ltx_video` directly via `spellcaster_core.workflows`, paired with `wan_turbo_kwargs`.
   - Lua / JS / remote plugins (Darktable, SillyTavern) POST to the Guild's `/api/video/shots` endpoints instead — that surface wraps the canon server-side. The GIMP plugin uses `_build_wan_video` (its local wrapper) that applies `wan_turbo_kwargs` itself.
   - No plugin hand-rolls WAN/LTX workflow JSON. The Darktable plugin's `build_wan_i2v_json` is an emergency escape hatch ONLY — live code goes through `guild_create_shot` → Guild → canon.
5. **Arch filter does not touch WAN/LTX LoRAs.** The cross-family LoRA filter in `composites.inject_lora_chain` doesn't run on video — video builders call `lora_loader_model_only` directly so WAN-specific LoRAs aren't dropped.
6. **Caller overrides win over preset hints.** In the scaffold dispatcher's LTX branch, caller-supplied `interpolate` / `rtx_scale` / `steps` / `cfg` / `stg` / `rescale` / `i2v_strength` / `sampler_name` / `stg_layers` / `chunk_size` / `enable_sage` / `enable_cfg_zero` / `vae_*` / `extra_loras` override the `_LTX2_PRESET_HINTS` default. Hints are a floor, not a ceiling — a client asking for RIFE interpolation on `ltx2_distilled` gets it even though the hint defaults `interpolate=False`.
7. **Fluent pipeline DSL accepts the full canon surface.** `Pipeline().ltx_video(...)` exposes every optional kwarg the builder supports (`distilled`, `two_stage`, `steps`, `cfg`, `stg`, `rescale`, `i2v_strength`, `pingpong`, `interpolate`, `rtx_scale`, `enable_sage`, `enable_cfg_zero`, `sampler_name`, `stg_layers`, `chunk_size`, `vae_*`, `loras`, `negative`). `_run_ltx` forwards them all; unset kwargs stay None so canon defaults ride through.

#### 16.5 Canon verification — `tests/e2e_audit.py`

The audit script at `tests/e2e_audit.py` is the **live test harness** for the canon. Run it against a ComfyUI server that has WAN and LTX models installed to confirm the canon works end-to-end:

```bash
# Windows PowerShell / Git Bash — utf-8 env var avoids cp1252 Unicode crash
PYTHONIOENCODING=utf-8 python tests/e2e_audit.py --only video --verbose
PYTHONIOENCODING=utf-8 python tests/e2e_audit.py --only build_fns --verbose
```

Video canon section asserts:
- `wan_turbo_kwargs(True)` returns `{}`; `wan_turbo_kwargs(False)` returns `{steps:30, cfg:3.5, second_step:15}`.
- `ltx_mode_kwargs(mode)` returns the right `{distilled, two_stage}` for every mode.
- `pick_wan_vae` pairs 14B I2V → `wan_2.1_vae.safetensors` and 5B TI2V → `wan2.2_vae.safetensors`.
- `detect_wan_preset(live_server)` returns an I2V-safe preset (< ~200ms).
- `detect_ltx_preset(live_server)` returns a 22B/13B preset with Gemma text encoder.

Build-fns section compiles every `build_*` function (including `build_wan_video`, `build_wan_flf`, `build_wan22_t2v`) and POSTs the result to ComfyUI's `/prompt` endpoint. ComfyUI validates the shape and either queues or rejects — the rejection error is what the audit report shows.

**Expected green bar:** `54 PASS / 0 FAIL / N SKIP` (skips are for builders that need extra positional args not supplied by auto-test, e.g. `build_wan_video_blockswap`).

If any WAN/LTX test fails after changes, the diagnostic output tells you exactly which canon rule regressed.

#### 16.6 Where every WAN/LTX call lands

Every runtime call path for video goes through exactly one of the entries below. The **LTX section** has been end-to-end audited (2026-04-20) — every live call site either uses the canonical `build_ltx_video` kwarg surface in full, or has a documented reason for being minimal.

**WAN 2.2 call paths:**

| Caller | Entry point | Mechanism |
|---|---|---|
| Python plugin code (GIMP, Resolve scripts) | `workflows.build_wan_video()` + `wan_turbo_kwargs()` | Direct import |
| GIMP plugin UI buttons | `_build_wan_video` wrapper in `_spellcaster_main.py` → canonical `build_wan_video` | Thin wrapper applies `wan_turbo_kwargs` + probes IP-Adapter/SLG/NAG availability |
| Wizard Guild API consumers | `POST /api/video/shots` → `_VIDEO_BRIDGE.add_shot` → scaffold dispatcher | Dispatcher applies `wan_turbo_kwargs` |
| SillyTavern plugin | `POST /api/video/shots` with `preset="wan22_i2v_lightning"` or `"wan22_i2v_hq"` | Goes through the Guild |
| DaVinci Resolve plugin | `spellcaster_api.create_shot()` → `POST /api/video/shots` | Goes through the Guild |
| Darktable Lua plugin (WAN) | `guild_create_shot()` helper → `POST /api/video/shots` | Goes through the Guild (pre-R200 hand-rolled JSON removed) |
| `spellcaster_core.pipeline.Pipeline().wan_video()` | `_run_wan` → `detect_wan_preset()` + `wan_turbo_kwargs()` + `build_wan_video()` | Fluent-chain client |
| Live diagnostic (`diagnostic._build_wan_test`) | `detect_wan_preset()` + `wan_turbo_kwargs(True)` + `build_wan_video()` | Probes server with canon |
| `tools/generate_showcase.py`, `tools/generate_walkthrough.py`, `tools/generate_readme_gifs.py` | Detect preset live + `build_wan_video()` + `wan_turbo_kwargs()` | Ad-hoc dev tools |

**LTX 2.3 call paths — all audited against the 29-kwarg canon:**

| # | Caller | Entry point | Kwarg coverage |
|---|---|---|---|
| 1 | GIMP LTX button (T2V / I2V) | `LtxVideoDialog.get_values()` → `_build_ltx_video` wrapper → canon | **All 26 optional kwargs** exposed via dialog widgets (§16.3); wrapper tri-state-resolves SAGE/CFG Zero vs server probe and forwards everything |
| 2 | Guild avatar baker | `tavern/server.py::_queue_animated_avatar` → `build_ltx_video(..., **ltx_mode_kwargs("i2v"), **_ltx_server_opts(url))` | Fixed 512×512×25 I2V; auto-probes SAGE + CFG Zero via `_ltx_server_opts`. Other kwargs stay canon default by design |
| 3 | Guild I2V retry path | `tavern/server.py::_retry_anim_as_ltx` → same as #2 | Same as #2 |
| 4 | Wizard Guild API consumers | `POST /api/video/shots` (body has `overrides` dict) → `_VIDEO_BRIDGE.add_shot` → `queue_shot` → `_build_native_workflow` → dispatcher LTX branch → canon | Bridge reads 16 LTX keys from `overrides`; dispatcher spreads them via `**extra`. **Caller overrides win** over `_LTX2_PRESET_HINTS` defaults (§16.4 rule #6) |
| 5 | SillyTavern plugin | `POST /api/video/shots` with `preset="ltx2_distilled"` etc. + `overrides` | Same chain as #4 |
| 6 | DaVinci Resolve plugin | `spellcaster_api.create_shot()` → `POST /api/video/shots` + `overrides` | Same chain as #4 |
| 7 | Darktable Lua plugin | `process_ltx_video()` → `guild_create_shot()` → `POST /api/video/shots` | Same chain as #4; Darktable UI exposes mode + scene-template selector + advanced patches |
| 8 | `spellcaster_core.pipeline.Pipeline().ltx_video(...)` | Fluent DSL: `_run_ltx` → `detect_ltx_preset()` + `build_ltx_video()` | **All 20+ optional kwargs** accepted in the fluent API (§16.4 rule #7); `_run_ltx` forwards them all |
| 9 | Live diagnostic (`diagnostic._build_ltx_test`) | `detect_ltx_preset()` + `build_ltx_video()` | Minimal (5 kwargs) — intentional, just a live probe test |

**Receivers verified (2026-04-20 audit):**
- [scaffold/video_bridge.py](scaffold/video_bridge.py) `queue_shot()` reads 16 LTX override keys (`steps`, `cfg`, `stg`, `rescale`, `i2v_strength`, `sampler_name`, `stg_layers`, `chunk_size`, `enable_sage`, `enable_cfg_zero`, `vae_spatial_tiles`, `vae_temporal_tile_length`, `vae_last_frame_fix`, `vae_working_dtype`, `extra_loras`, `pingpong`) from `shot.overrides` and passes them to `_build_native_workflow`.
- [scaffold/video_workflow_dispatch.py](scaffold/video_workflow_dispatch.py) `build_native_workflow()` LTX branch spreads all 16 into the build call via `**extra`. Caller's `interpolate` / `rtx_scale` override the hint's defaults.
- [tavern/server.py](tavern/server.py) `_ltx_server_opts(comfy_url)` auto-probes `/object_info/{PatchSageAttentionKJ, CFGZeroStar}` and returns ready-to-spread kwargs; used by every Guild-side LTX caller (avatar baker + retry path).
- GIMP `_build_ltx_video` wrapper auto-probes SAGE + CFG Zero via `_ltx_quality_patches_available(server)` and resolves tri-state user overrides against the probe.

If you see a new caller that doesn't fit one of these, it's a canon violation in the making — route it through one of the above.

#### 16.7 Global quality mode — the ⚡/⚖️/💎 toggle

The Wizard Guild's global preset button cycles through **three** session-scoped quality modes that every WAN + LTX workflow respects:

| Mode | Icon | WAN effect | LTX effect |
|---|---|---|---|
| `turbo` | ⚡ | `turbo=True` (6 steps + lightning LoRAs, cfg 1.0) | `distilled=True` (8-step fast path) |
| `standard` | ⚖️ | `turbo=False` (30/3.5/15 full-step, no accel LoRAs) | `distilled=False, two_stage=False` (30-step full) |
| `quality` | 💎 | `turbo=False` + preset auto-swaps `wan22_i2v_lightning` → `wan22_i2v_hq` | preset auto-swaps to `ltx2_text_to_video_2stage` (half-res → 2× latent upscale → re-denoise) |

**State lives in `tavern/server.py::_GUILD_VIDEO_MODE`** — a module-level string, intentionally NOT persisted. Resets to `"turbo"` on every Guild restart. Users who want their choice to survive restart should rely on the button's localStorage caching (client-side) — the server state is the per-session runtime override.

**Endpoints:**
- `GET /api/video/quality-mode` → `{"mode": "turbo"|"standard"|"quality"}`
- `POST /api/video/quality-mode` body `{"mode": "..."}` → updates + echoes back

**Client sync** ([tavern/static/app.js::_wireGlobalPresetBtn](tavern/static/app.js)): the button's click handler POSTs the new mode to the server; on page load it also POSTs the localStorage-cached mode so a freshly-restarted Guild (which boots at "turbo") picks up the user's prior choice.

**Remapping helper** ([tavern/server.py::_apply_quality_mode](tavern/server.py)): called in `POST /api/video/shots` to rewrite `(preset_key, overrides)` before they reach `_VIDEO_BRIDGE.add_shot`. Caller's explicit `overrides` still win — the mode only fills defaults via `setdefault()`, and preset rewrites only happen when the current preset has no explicit quality-aware variant (e.g., lightning → hq for WAN quality).

**Consumers:**
- `POST /api/video/shots` — applies mode to incoming shot (caller's body `quality_mode` field wins over `_GUILD_VIDEO_MODE` if present)
- `_queue_animated_avatar` — reads `_GUILD_VIDEO_MODE` directly, overrides `ltx_mode_kwargs("i2v")` default
- `_retry_anim_as_ltx` — same pattern

**Intentional non-coverage:**
- The GIMP plugin's `_build_ltx_video` wrapper and `_run_ltx_t2v` use the dialog's explicit mode checkboxes (distilled / two_stage), NOT the Guild mode. GIMP users pick per-run; Guild users pick globally.
- The scaffold dispatcher's LTX branch respects caller overrides over hint defaults (§16.4 rule #6), so the remapped preset + overrides flow through without further interference.

### 17. Model Coverage & the `supported_methods` contract

**22 architectures are registered** in `spellcaster_core/architectures.py` — up from the original 8. Every arch key the detector (`model_detect.py`) can emit now has a first-class ArchConfig entry, so `get_arch(key)` returns correct defaults instead of silently falling back to SDXL and crashing at dispatch time.

**Fully-built archs** (registered=True + populated `supported_methods`):

| Arch | Default (steps / CFG / res) | Notes |
|---|---|---|
| `sd15` | 25 / 7.0 / 512² | Classic, dpmpp_2m karras |
| `sdxl` | 30 / 6.5 / 1024² | dpmpp_2m_sde karras |
| `illustrious` | 28 / 5.5 / 1024² | Booru tags, euler_ancestral |
| `zit` | 6 / 2.0 / 1024² | Z-Image-Turbo distill, 4-6 steps |
| `flux1dev` | 25 / 3.5 / 1024² | dual CLIP (clip_l + t5xxl) |
| `flux2klein` | 4 / 1.0 / 1024² | SamplerCustomAdvanced + CFGGuider |
| `flux_kontext` | 25 / 3.5 / 1024² | edit instructions, no negative |
| `chroma` | 25 / 3.0 / 1024² | single CLIPLoader type="chroma" |
| `sdxl_turbo` | 6 / 1.5 / 1024² | euler_ancestral sgm_uniform |
| `pony` | 30 / 7.0 / 1024² | booru score cascade autoset prompts |
| `playground` | 30 / 3.0 / 1024² | SDXL backbone, aesthetic tuning |
| `wan` | 30 / 3.5 / 832×480 | `supported_methods=VIDEO_METHODS` |
| `ltx` | 30 / 4.0 / 768×512 | Gemma text encoder, VIDEO_METHODS |
| `seedvr` | 15 / 1.0 / 1280×720 | `supported_methods=("video_upscale",)` |

**Stubs** (`registered=False`, `supported_methods=()`): `sd3`, `sd3_turbo`, `hunyuan_dit`, `pixart`, `auraflow`, `kolors`, `cogvideo`. Detector knows them, defaults are correct, but no builder dispatches them yet — `_assert_method` raises an explicit "detected but not yet scaffolded" error instead of a cryptic runtime crash. Promote a stub by (a) implementing its builder chain, (b) flipping `registered=True`, (c) populating `supported_methods`.

**The `supported_methods` contract:**
- Canonical method lists: `IMAGE_METHODS`, `VIDEO_METHODS`, `KLEIN_METHODS`, `ALL_IMAGE_METHODS` (import from `architectures.py`).
- Each ArchConfig's `supported_methods: tuple[str, ...]` lists the methods it can dispatch.
- **Enforcement is at builder entry** (`workflows.py`): `_assert_method_for_preset(preset, method_name)` is the FIRST line of every core image + video builder. Raises `UnsupportedMethodError` when the preset's arch is registered AND explicitly doesn't support the method, OR when the arch is a stub. Unknown / custom arch keys pass through silently (backward compat for 3rd-party arch_registry entries).
- **UI gating rides on the same data.** Summon flow, calibration UI, and Chimera's router read `supported_methods` to decide which actions to advertise — no more video wizards listing txt2img buttons that explode at sampler time.

**Size-aware unknown-checkpoint fallback** (`model_detect.py::classify_ckpt_model(name, file_size=None)`):
  - No keyword match + no size → `sd15` (legacy default).
  - No keyword match + ≥ 9 GB → `flux1dev`.
  - No keyword match + ≥ 4.5 GB → `sdxl`.
  - Keyword rules always win. Size is a fallback only.
  - `fallback_arch_for_size(bytes)` exposes the heuristic standalone.

**Rule of thumb when adding a new arch:**
1. Register it in `architectures.py` with correct defaults. Use `registered=True` only when a builder chain actually exists.
2. Populate `supported_methods` honestly (IMAGE_METHODS / VIDEO_METHODS / ALL_IMAGE_METHODS / custom subset).
3. New `build_*` function → drop `_assert_method_for_preset(preset, "<method_name>")` as its first body line.
4. Add a test case in `tests/test_model_coverage.py`.

### 18. GIMP Result Routing — Upscalers Open As a New Image

**Every ComfyUI result downloaded by the GIMP plugin flows through `_import_result_as_layer` in [plugins/gimp/comfyui-connector/_spellcaster_main.py](plugins/gimp/comfyui-connector/_spellcaster_main.py) (via the shared `_apply_mask_mode` wrapper).** That helper decides whether the result becomes a new layer or a new GIMP image — handlers must NOT open their own display.

**The rule — dimensional, not flag-based:**

| Result dims vs. canvas | Outcome |
|---|---|
| Larger than canvas on either axis | `Gimp.Display.new(result_image)` — opens as a new GIMP image |
| Same size or smaller              | Insert as a new top layer on the existing image (scale up to canvas if smaller) |
| `keep_size=True` caller flag      | Always a layer, centered, never auto-routed (SAM3, normal-map auto-gen) |

**Why dimensional:** one check catches every upscaler automatically — `_run_upscale`, `_run_quick_upscale`, `_run_upscale_blend`, `_run_detail_hallucinate`, `_run_seedv2r` with scale > 1x, `_run_outpaint`, `_run_klein_outpaint`. No per-handler flag needed. Scale-to-fit would have discarded the upscale pass. The "z1 / enhance only" case (scale = 1.0) naturally produces output dims == input dims → stays a layer, which is what the user expects.

**Rules for new handlers:**
1. Download the result bytes and hand them to `_apply_mask_mode(server, image, data, layer_name, mask_enabled)` — do not call `Gimp.Display.new` yourself.
2. If your workflow is genuinely same-size-only (face restore, recolour, img2img at canvas dims), the layer path is taken automatically.
3. If your workflow may return a cropped subject that should overlay at its natural position, call `_import_result_as_layer(..., keep_size=True)` directly — that bypasses the auto-route.
4. Never add a handler-side dimension check. The helper owns this decision; divergent copies will drift.

**UI text:** if a dialog label claims "Result is imported as a new layer" for a handler whose output may exceed canvas dims, the label is stale — fix it. The upscale-4x dialog label already reflects the dual behavior; mirror that wording when adding similar handlers.

### 19. LoRA Calibration Stack — ✧ Calibration unified studio

The UI button is **✧ Calibration** (`tavern/static/lora_calibration.js`). It merged the old ⚔ Shootouts + ✨ Auto-calibrate entry points into one tabbed modal: **Confirm** (auto-rendered cards grouped by (arch, purpose_group)) / **Compare duplicates** (pending shootout groups; delegates to the legacy shootouts modal via `window.SpellcasterShootout.open()`) / **Stats** (coverage + scorer health + preflight breakdown). The ⚔ Shootouts button injection is disabled in `lora_shootout.js::ensureEntryButton`; the UI stays reachable only from the Compare tab.

**The four-layer knowledge stack:**

1. **`lora_knowledge.py::get_knowledge(name, path=..., user_override=..., use_network=True)`**
   Merges every source we can cheaply read, in precedence order:
   - User registry (highest priority — user-confirmed recipes)
   - `.civitai.info` sidecar next to the LoRA file (A1111 convention)
   - Safetensors `__metadata__` header (trainer-embedded triggers)
   - Shipped community defaults (`lora_calibrations_sfw.json` + `lora_calibrations_nsfw.json`)
   - Civitai public API by SHA-256 hash (one shot, cached forever per hash in `<state_dir>/lora_knowledge_cache.json`)
   - Heuristic fallbacks keyed on base_model
   Every populated field records its source in `provenance` so the UI can badge it (civitai / community / user / heuristic).

2. **`lora_calibration_store.py`** — SFW/NSFW split JSON stores.
   - `sfw_path()` → `comfyui-spellcaster/spellcaster_core/lora_calibrations_sfw.json` (shipped in public repo).
   - `nsfw_path()` → same dir + `lora_calibrations_nsfw.json`. The NSFW file lives in `nsfw/` in the source tree (gitignored); `nsfw/build_nsfw.py::patch_nsfw_lora_calibrations` copies it into the staged `spellcaster_core/` so the NSFW build ships it.
   - `write_calibration(name, *, nsfw=bool, ...)` routes to the right store. Classification is `lora_knowledge.classify_nsfw(knowledge, filename)` — Civitai flag OR keyword match on filename/triggers. Conservative by design (false-positive leaks to NSFW store which is private; false-negative would leak NSFW into the public SFW store which is NOT acceptable).

3. **`lora_scorer.py::score_image(image_b64, prompt, *, ollama_url, model="gemma3:4b")`**
   Posts the rendered sample to a local Ollama multimodal model via `/api/chat` with `format: "json"`. Returns `ScoreResult(ok, score, reason, model, elapsed_ms, error)`. `probe_available()` hits `/api/tags` so the UI can gray out auto-confirm when the model isn't installed. Gracefully returns `ok=False` on any failure — the calibration pipeline proceeds without scoring.

4. **`scaffold/lora_grouping.py`** — the calibration engine.
   - `resolve_shootout_recipe_for_lora(name, group, arch, ...)` consults `lora_knowledge` and returns `{prompt, negative, strength, sampler, cfg, trigger_words, nsfw, provenance}`.
   - `render_calibration_sample(server, name, group, arch, models, **opts)` renders ONE sample with that recipe. Opts include `score_with_llm`, `stability_seeds` (1 = default; 3 = opt-in stability check — render at N seeds, median-score picks winner, `unstable=True` flag when score range > 3.0), `sweep_strengths` (opt-in list like `[0.4, 0.7, 1.0]` — runs only when weight provenance is heuristic-only; scorer picks winner; losing images are dropped to keep payload small).
   - `start_calibration_job(server, targets, models, *, preflight=True, ...)` kicks off a background batch. **Preflight** (default on) renders ONE minimal base sample per unique arch to catch broken pipelines before 50 red error cards stream in. Archs that fail preflight get all their LoRAs moved to `skipped` with the arch-level reason.
   - **Job persistence**: state serializes to `<state_dir>/calibration_jobs/<job_id>.json` on every update (metadata only — image_b64 is stripped). On Guild restart, `set_calibration_persist_dir()` marks any still-running jobs as `interrupted`. The UI's Confirm tab shows a resume banner when interrupted jobs exist.

**Shipped calibration JSON schema (both SFW and NSFW files share):**
```json
{
  "schema_version": 1,
  "loras": {
    "SomeLora.safetensors": {
      "updated_at": 1700000000,
      "source": "user_confirm | auto_confirm_llm | auto",
      "recommended_weight": 0.85,
      "recommended_sampler": "dpmpp_2m",
      "recommended_cfg": 7.5,
      "subject_key": "portrait_f",
      "trigger_words": ["sinozick style"],
      "base_model": "sdxl",
      "sha256": "abc123...",
      "confirmed_by_user": true,
      "confirmed_at": 1700000000,
      "nsfw": false
    }
  }
}
```

**Server endpoints (all in `tavern/server.py`):**
- `GET /api/spellcaster/lora/knowledge?name=X` → merged knowledge record
- `GET /api/spellcaster/lora/calibrate/summary` → confirmed/pending counts + store paths
- `POST /api/spellcaster/lora/calibrate/auto/start` (body: `{subset: "unconfirmed", use_network, score_with_llm, preflight, stability_seeds, sweep_strengths}`) → spawns job
- `GET /api/spellcaster/lora/calibrate/auto/status?job=X` → polls samples + skipped + preflight
- `POST /api/spellcaster/lora/calibrate/auto/cancel?job=X` → sets `cancel_requested` + POSTs ComfyUI `/interrupt` + `/queue {clear:true}`
- `POST /api/spellcaster/lora/calibrate/confirm` → writes recipe to SFW or NSFW store + flips registry flag
- `GET /api/spellcaster/lora/calibrate/resumable` / `POST /.../resumable/clear` → interrupted-job metadata + dismiss
- `GET /api/spellcaster/lora/scorer/probe` → Ollama multimodal availability

### 20. Resilience — Faceswap Auto-Recovery & Preflight Status Dot

Two independent resilience layers landed in the 2026-04 cycle.

#### 20.1 Faceswap auto-recovering guard (`faceswap_health.py`)

comfy-mtb + ReActor face-swap nodes load `inswapper_128.onnx` via ONNX Runtime + TensorRT. When `nvinfer_builder_resource_*.dll` fails to load, the native path crashes ComfyUI with a Windows access violation — Python can't catch it.

The guard wraps every face-swap workflow builder in `workflows.py` (`build_faceswap`, `build_faceswap_model`, `build_faceswap_mtb`, `build_face_restore`, `build_klein_headswap`, `build_photobooth`) via `_faceswap_guard(feature)`. The state machine:

- **`AUTO_ON`** (default) — guard passes; `record_dispatch()` stamps `last_dispatch_ts` for attribution.
- **Heartbeat** (`tavern/server.py` boot) — background thread pings ComfyUI `/system_stats` every 15s and calls `record_probe(ok)`.
- **Attribution**: if `record_probe(False)` lands within 60s of a dispatch AND not already auto-disabled → flip `auto_disabled=True`. Next face-swap build raises `FaceswapDisabledError` with a clear message.
- **Recovery**: after ComfyUI stays reachable continuously for 30 min AND the disable was automatic (not user-forced) AND we haven't escalated → flip `auto_disabled=False` automatically. `state_reason` surfaces the recovery.
- **Escalation**: after `CRASH_ESCALATION_COUNT` (3) attributed crashes we stop auto-re-enabling. User must call `POST /api/spellcaster/faceswap/reset` or set `faceswap_force_enable: true` in `guild_config.json`.
- **Persistence**: `set_persist_path(<state_dir>/faceswap_state.json)` at boot; state survives Guild auto-updates (see §13).

**User overrides** (highest precedence, in order):
- `SPELLCASTER_FACESWAP_DISABLED=1` env var → forced off
- `faceswap_disabled: true` in `guild_config.json` → forced off
- `faceswap_force_enable: true` in `guild_config.json` → forced on (bypasses auto-disable for users who fixed TRT and don't want to wait the 30-min stability window)

**Endpoints:** `GET /api/spellcaster/faceswap/health` (full state + run history) + `POST /api/spellcaster/faceswap/reset` (wipe crash history, clear escalation).

**Calibration / Shootouts / Preflight do NOT use face-swap nodes** (verified 2026-04-20 audit) — they route through `build_txt2img` only. The guard is strictly for face-swap / head-swap / photobooth workflows.

#### 20.2 Preflight status dot (`preflight_status.py`)

Small colored dot sits left of the ✧ Calibration button in `chat-shootout-slot`. Traffic light aggregates:

- ComfyUI `/system_stats` reachability
- Faceswap `get_effective_state()` (red when escalated, yellow when auto_off)
- Scorer `probe_available()` (yellow when offline)
- Per-arch render canaries cached in `<state_dir>/preflight_cache.json` (red on failure, yellow when stale > 24h, green when fresh + all passing)

Colour rules live in `_classify_overall()`; first matching rule wins.

**Install-flow trigger**: end of `_setup_flow` in `tavern/server.py` (right after `_setup_marker_done()`) spawns a daemon thread that runs `run_full_preflight(COMFYUI_URL, _preflight_arch_probe, models)` — one minimal render per unique installed arch (skip video archs). Results cache to disk; the dot picks up the verdict on its next 60s poll. User sees green/yellow/red the moment setup ends.

**Endpoints:**
- `GET /api/spellcaster/preflight/status` → aggregate traffic light + headline + canary list + active run_job (if any)
- `POST /api/spellcaster/preflight/run` → kick off fresh canaries in a background thread (idempotent while running)

UI-side: tooltip on the dot shows the one-line headline; click opens Calibration → Stats tab which surfaces the full breakdown + "Re-run preflight" button. During a run, the dot shows a spinning ring.

### 21. Summon Archetypes — 5 specialised wizard kinds

The classic Summon flow (pick model → auto-studio → LLM-name) is **path A**. Five archetype kinds sit alongside as **path B**: summon a wizard whose mechanic isn't tied to a single model. UI lives in `tavern/static/app.js` + `tavern/static/index.html` (new step 0 archetype picker + step-arc per-archetype config screen).

**Character-record shape** (persisted in `.guild_state/custom_wizards.json`):
```json
{
  "id": "archetype_<kind>_<slug>",
  "type": "archetype",
  "archetype_kind": "forensic|chimera|oracle|lore_keeper|scalpel",
  "archetype_config": { ... kind-specific ... },
  "system_prompt": "...",    // pulled from _ARCHETYPE_CATALOGUE in server.py
  "name", "subtext", "color1", "color2", "personality"
}
```

**Per-kind config + runtime endpoint:**

| Kind | Config | Runtime endpoint | Back-end |
|---|---|---|---|
| **forensic** | `{}` | `POST /api/archetype/forensic/extract` (body: `image_b64`) | `forge.reverse_engineer_image` parses PNG tEXt chunks for workflow / prompt / seed / LoRAs |
| **chimera** | `{models: [{name, arch, type, domain}, 2-5 items]}` | `POST /api/archetype/chimera/route` (body: `prompt, char_id`) | Keyword classifier picks the best-domain head per prompt |
| **oracle** | `{llm_model: "gemma3:4b", ...}` | `POST /api/archetype/oracle/review` (body: `image_b64, prompt, llm_model`) | Delegates to `lora_scorer.score_image` |
| **lore_keeper** | `{}` | `POST /api/archetype/lore_keeper/query` (body: `query, limit`) | Substring search over `_LORA_REGISTRY` + `lora_calibration_store.load_merged()`; confirmed recipes sort first |
| **scalpel** | `{base_model: {name, arch, type}}` | `POST /api/archetype/scalpel/plan` (body: `char_id, instruction`) | Verb detection (erase / replace / add) → returns SAM3 chain plan (full dispatch TBD) |

**Summon-side validation** (`_validate_archetype_config` in `tavern/server.py`): Chimera needs 2-5 models; Oracle needs a non-empty `llm_model`; Scalpel needs a `base_model` with `name`; Forensic / Lore-keeper accept empty config. Unknown `archetype_kind` → 400.

**Rule:** when adding a new archetype, update `_ARCHETYPE_CATALOGUE` (server.py) with `icon` + `default_subtext` + `hue` + `system_prompt`, add a per-kind validator branch in `_validate_archetype_config`, wire a runtime endpoint, and add an entry to `SUMMON_ARCHETYPES` in `app.js`. Tests live in `tests/test_summon_archetypes.py`.

### 22. Quality + Speedup Cascade — `quality` and `fast_mode` parameters

**Every image builder that goes through `spellcaster_core.workflows._apply_quality_boost` + `_apply_speedup`** layers boosters on the model ref, gated per-arch. These are the canonical knobs every surface (GIMP preset picker, Darktable Advanced panels, Guild `/api/run_builder`) exposes via two scalars the caller passes to `build_*`:

- `quality`: `"fast"` | `"balanced"` (default) | `"max"`
- `fast_mode`: `bool` (default `False`)
- `compile_mode`: `bool` (default `False`; opt-in torch.compile, persistent-server only — 20–40 s warm-up)

**Per-arch cascade (module-level sets in [workflows.py](comfyui-spellcaster/spellcaster_core/workflows.py)):**

| Booster | Set variable | Scope | Applies when |
|---|---|---|---|
| CFGZeroStar         | `_QUALITY_ARCHES_CFG_ZERO_STAR` | `{zit, flux1dev, flux_kontext}`                                   | quality ≠ fast AND cfg < 4.5 |
| PerturbedAttention  | `_QUALITY_ARCHES_PAG`           | `{sdxl, illustrious, flux1dev, chroma, flux_kontext, zit}`         | quality ≠ fast |
| RescaleCFG          | `_QUALITY_ARCHES_RESCALE`       | `{sd15, sdxl, illustrious}`                                        | cfg ≥ 7.5 |
| FreeU_V2            | `_QUALITY_ARCHES_FREEU`         | `{sdxl}`                                                           | quality == max |
| SkipLayerGuidanceDiT| `_QUALITY_ARCHES_SLG`           | `{flux1dev, flux_kontext, zit}`                                    | quality == max |
| SageAttention       | `_SAGE_ATTENTION_ARCHES`        | `{flux1dev, flux_kontext, flux2klein, zit, wan, ltx, chroma}`      | fast_mode |
| torch.compile       | (all arches)                    | any                                                                | compile_mode |
| TeaCache            | explicit list                   | `{flux1dev, flux_kontext, zit}`                                    | fast_mode |
| DetailDaemon sampler| `_DETAIL_DAEMON_ARCHES`         | `{zit}`                                                            | quality == max (replaces KSampler with SamplerCustomAdvanced) |

**Klein is intentionally excluded from every model-patch booster** — its own `Flux2KleinEnhancer` chain (§8) already handles guidance shaping, and PAG / SLG would conflict with the `ReferenceLatent + CFGGuider` stack. Klein does still receive Sage Attention when `fast_mode=True` (pure attention-backend swap, no guidance interaction).

**Per-arch tunings** (inside `_apply_quality_boost` / `_apply_speedup`):
- PAG scale: `1.5` on ZIT (distilled cfg=2 hates PAG 3.0), `3.0` elsewhere.
- SLG scale: `2.0` on ZIT, `3.0` on Flux; layers 7–9 in both streams.
- TeaCache threshold: `0.3` on ZIT (distilled per-step deltas are larger), `0.4` on Flux.
- Detail Daemon: `detail_amount=0.1`, `start=0.2`, `end=0.8`, `smooth=True` (muerrilla defaults, community-tested at 6 steps).

**Ordering invariant:** CFGZeroStar fires BEFORE PAG/SLG so subsequent patches stack on the corrected guidance. `_apply_speedup` node-id tranche is `base / base+1 / base+2` = Sage / torch.compile / TeaCache. Callers passing only the legacy `node_id` still get a valid 3-slot tranche computed from it; do NOT remove that fallback.

**Smoke check** for a new arch opt-in: `cd comfyui-spellcaster && python -c "from spellcaster_core import workflows as wf; print('zit' in wf._DETAIL_DAEMON_ARCHES)"`. Full stack coverage lives in [tests/test_quality_boost.py](tests/test_quality_boost.py).

### 23. ControlNet Compatibility Gating — `cn_is_compatible`

**Every UI picker that exposes a ControlNet combobox MUST filter through `spellcaster_core.model_detect.cn_is_compatible`** (or its list wrapper `cn_modes_for_arch`). User report that kicked this off: picking a 3D Normal Map ControlNet on a Klein preset silently failed at sampling because the picker showed every mode regardless of loaded arch.

**The canonical filter (`spellcaster_core/model_detect.py`):**
- `CN_FORBIDDEN_ARCHES = frozenset({"flux2klein", "flux_kontext", "chroma"})` — these arches see ONLY the "Off" entry, never a real CN mode. §9 architecture matrix is the source of truth.
- `cn_is_compatible(cn_models, target_arch)` — True iff `cn_models is None` (the synthetic "Off" entry, always available) OR `target_arch` is non-forbidden AND is a key of the `cn_models` dict.
- `cn_modes_for_arch(modes_dict, target_arch)` — iteration-order-preserving list helper; use this in comboboxes so "Off" stays at index 0.

**UI integration points:**
- **GIMP** ([`_spellcaster_main.py`](plugins/gimp/comfyui-connector/_spellcaster_main.py)): local `cn_modes_for_arch` wrapper delegates to the canonical helper with an inline fallback (same pattern as `_filter_loras_for_arch`). Both `_cn_mode_combo` and `_cn_mode_combo_2` populate through it. `_refresh_cn_combos()` re-filters on preset change, preserving the user's pick across arch switches when it survives, falling back to Off otherwise. Hooked into `_on_preset_changed` next to the existing LoRA / scene refresh calls.
- **Darktable** ([`comfyui_connector.lua`](plugins/darktable/comfyui_connector.lua)): `CN_MODEL_MAP` — every ZIT mode routes to the `ZIT_UNION_CN = "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"` constant. Commit `dcfc2aa` fixed a copy-paste bug that pointed every ZIT mode at SDXL canny.
- **Guild**: delegates to the GIMP/Darktable flows — no standalone CN picker.

**Enforcement at the builder layer:** separate from the UI gate, every `build_*` calls `_assert_method_for_preset` at entry (§17). The UI filter is a usability win; the builder assertion is the safety net for API callers, scaffolds, and anything that bypasses the picker.

**Systematic coverage** ([`tests/test_cn_compat.py`](tests/test_cn_compat.py)): loads `CONTROLNET_GUIDE_MODES` out of the GIMP plugin without importing Gtk (brace-balance walks the dict literal out of the source) and validates every (mode, arch) pair across 14 modes × 20 architectures = 280 pairs. Must pass on every commit that touches CN routing.

### 24. The `/api/run_builder` Bridge — Thin Plugins Into Canonical Builders

**Thin client plugins (Darktable Lua, future Lua/JS surfaces, remote scripts) call `POST /api/run_builder` instead of inlining workflow JSON.** Body: `{"builder": "build_klein_inpaint", "params": {...}, "comfy_url": "..."}`. The Guild routes through `_build_and_dispatch` → `spellcaster_core.workflows.<builder>`, dispatches to ComfyUI, caches the result via `AssetGallery` (§15), and returns canonical `/api/assets/<hash>` URLs.

**Use this path for any new image-edit feature in a non-Python plugin.** Inlining a 200-line workflow JSON DAG in Lua/JS duplicates the canonical builder and guarantees divergence on the next bug fix — precisely the scenario §3 forbids. The Python GIMP plugin imports `spellcaster_core` directly and doesn't need this bridge.

**Canonical example:** the Darktable "Klein Surgical Edits" + "Z-Image-Turbo (Advanced)" panels use `_run_builder(builder_name, params_json)` + `_download_guild_assets(urls, prefix)` helpers in [comfyui_connector.lua](plugins/darktable/comfyui_connector.lua). ~50 Lua lines per feature, zero workflow JSON, bug fixes in `spellcaster_core/workflows.py` reach every client automatically.

**Parameter conventions for Lua/JS callers:** flat keyword shape (`image_filename`, `prompt_text`, `negative_text`, `seed`, `denoise`, `quality`, `fast_mode`, `arch`, `ckpt`, `loras`, `sam3_prompt`). The Guild's `_translate_params` (`tavern/server.py`) handles renames (e.g. `prompt` → `prompt_text`), builds the `preset` dict from flat params + auto-detection, and re-uploads any `/api/assets/<hash>` or `/api/cached_asset/<name>` filenames to ComfyUI before dispatch.

## File Structure Quick Reference

```
spellcaster/
├── plugins/gimp/comfyui-connector/
│   ├── comfyui-connector.py          ← IMMUTABLE boot shim
│   ├── _spellcaster_main.py          ← main plugin (22K+ lines)
│   └── spellcaster_core/             ← shared library (dev copy)
├── comfyui-spellcaster/
│   └── spellcaster_core/             ← CANONICAL source (auto-updater reads this)
├── tavern/                           ← Wizard Guild server + web UI
├── installer/                        ← Windows/macOS/Linux installers
├── nsfw/                             ← GITIGNORED — NSFW build system
│   ├── build_nsfw.py                 ← NSFW build/patch/push script
│   ├── staging/                      ← Patched SFW copy
│   ├── nsfw_klein_presets.json       ← NSFW presets (NEVER commit to main)
│   └── lora_calibrations_nsfw.json   ← NSFW calibration recipes (§19; patched into NSFW build)
├── tests/
│   ├── test_model_coverage.py        ← arch registry + supported_methods enforcement (§17)
│   ├── test_lora_auto_calibrate.py   ← calibration stack (§19)
│   ├── test_summon_archetypes.py     ← archetype validators + runtime endpoints (§21)
│   └── ...                           ← other canonical test harnesses
└── CLAUDE.md                         ← This file
```
