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

The canonical source for all shared library code is `comfyui-spellcaster/spellcaster_core/` in THIS repo. Three copies exist:

1. `comfyui-spellcaster/spellcaster_core/` — CANONICAL (auto-updater downloads from here)
2. `plugins/gimp/comfyui-connector/spellcaster_core/` — bundled with GIMP plugin
3. `../ComfyUI-Spellcaster/spellcaster_core/` — separate ComfyUI node repo

**After ANY change to workflows.py, node_factory.py, composites.py, architectures.py, or prompt_enhance.py:**

```bash
# 1. Edit in plugins/gimp/comfyui-connector/spellcaster_core/ (dev copy)
# 2. Sync to canonical:
cp plugins/gimp/comfyui-connector/spellcaster_core/CHANGED_FILE.py comfyui-spellcaster/spellcaster_core/
# 3. Sync to ComfyUI repos:
cp comfyui-spellcaster/spellcaster_core/CHANGED_FILE.py ../ComfyUI-Spellcaster/spellcaster_core/
cp comfyui-spellcaster/spellcaster_core/CHANGED_FILE.py ../ComfyUI-Spellcaster-NSFW/spellcaster_core/
# 4. Commit and push ALL repos
# 5. Update NSFW: python nsfw/build_nsfw.py --patch --push
```

**If you skip step 2, the auto-updater will OVERWRITE your changes on next GIMP launch** because it downloads from the canonical source.

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
- Usernames or local paths (`C:\Users\lmlgg\...` → use relative paths or `%APPDATA%`)
- Email addresses
- GitHub tokens (`ghp_...`)
- API keys for any service
- The user's actual ComfyUI server address

**Before every commit, verify:**
```bash
# Check staged files for personal data
git diff --cached | grep -iE "192\.168\.86\.|lmlgg|leguillaume|@gmail|ghp_"
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

### 14. Installer Is Self-Updating — Bootstrap Pattern

`spellcaster-installer.exe` is now a two-stage runner ([`installer/bootstrap.py`](installer/bootstrap.py)):

1. Bootstrap fetches the latest `install.py`, `installer_gui.py`, and `manifest.json` from `raw.githubusercontent.com/laboratoiresonore/spellcaster/main` into a temp dir.
2. Execs the fetched code via `importlib`, passing `SPELLCASTER_INSTALLER_ROOT=<temp_dir>` so the fetched install.py finds the fetched manifest.
3. On fetch failure (no network, rate limit, etc.), falls back to the baked-in copy.

**What this means for Claude:**

- **You no longer need to rebuild the .exe for most installer fixes.** Editing `installer/install.py`, `installer/installer_gui.py`, or `installer/manifest.json` and pushing to main is enough — every existing .exe picks it up on next launch.
- **The .exe only needs rebuilding when**: `bootstrap.py` itself changes, `build_installer.py` flags change, a NEW bundled asset is added (e.g. a new `plugins/` dir), or the PyInstaller hidden-imports list needs updating.
- **The assets stay baked**: `plugins/`, `tavern/`, `scaffold/`, `assets/` are bundled. Asset finders (`_find_gimp_plugin_src`, `_find_tavern_src`, `_find_scaffold_src`) consult both `SCRIPT_DIR` (fetched temp dir) and `BUNDLE_DIR` (PyInstaller `_MEIPASS`). So bootstrapped runs can still locate bundled assets.
- **Offline fallback** — users without internet still get the baked-in version, which is guaranteed-working at build time.

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
