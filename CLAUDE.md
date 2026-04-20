# Spellcaster — Development Guide for Claude

## What This Is

Spellcaster is **middleware** between ComfyUI and user-facing apps (GIMP, Darktable, Wizard Guild chat UI, SillyTavern). It has 69 AI tools. The codebase spans 4 GitHub repos, SFW and NSFW variants, and a crash-safe plugin architecture.

## Zero Duplication Rule

**NEVER duplicate logic.** Spellcaster enforces a single source of truth for ALL shared functionality. If the GIMP plugin and the Guild server both need a function, that function lives in `spellcaster_core/` and both import it. No exceptions.

**Existing shared modules in `spellcaster_core/`:**
- `workflows.py` — ALL workflow builders (build_img2img, build_klein_*, etc.)
- `node_factory.py` — ALL ComfyUI node constructors
- `composites.py` — multi-node building blocks (load_model_stack, inject_lora_chain, etc.)
- `architectures.py` — architecture registry and ArchConfig
- `prompt_enhance.py` — LLM prompt enhancement (all backends)
- `comfyui_llm.py` — ComfyUI-based LLM text generation
- `guild_llm.py` — LLM chat abstraction (ComfyUI → KoboldCpp → Ollama)
- `privacy.py` — server file cleanup (privacy mode)
- `preflight.py` — workflow validation and node substitution
- `model_detect.py` — architecture detection from model filename
- `video_presets.py` — **canonical WAN + LTX detection + turbo/mode formulas** (see rule 16)
- `asset_gallery.py` — **canonical blob store + metadata index** for every generated image/video (see rule 15)
- `event_bus.py` — cross-interface event fan-out; `<origin>.asset.created` etc.
- `interface_registry.py` — registered consumer interfaces (GIMP, Resolve, Darktable, SillyTavern, Guild)
- `mailbox.py` — per-interface pull queues for directed asset delivery
- `cross_interface.py` — client helper for plugins to publish to inbox/bridge

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
- Always include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

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
│   └── nsfw_klein_presets.json       ← NSFW presets (NEVER commit to main)
└── CLAUDE.md                         ← This file
```
