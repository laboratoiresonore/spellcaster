# Portable Bundle — "Spellcaster Studio" Plan

Ship Spellcaster as a **portable zip** that contains everything needed to generate images: a pre-configured GIMP, a portable ComfyUI with our custom node pack, canonical ControlNet files pre-downloaded, the plugin pre-installed, and a one-click launcher.

Goal: replace "install GIMP → install ComfyUI → run Spellcaster installer → configure → download models" with "extract zip → double-click .bat."

**Status:** spec + build scaffolding landed 2026-04-20. Actual bundle production is a per-release CI step using `tools/build_portable_bundle.py`.

---

## Scope

### In-scope for MVP (Windows)

- GIMP 3.x portable install (user-level, silent-installed on first run — GIMP doesn't ship a truly portable tree officially, so we orchestrate the official installer in `%BUNDLE%\gimp\` with `--install-dir` flag).
- ComfyUI Portable (Windows standalone build from `github.com/comfyanonymous/ComfyUI/releases`) as-is, extracted into `%BUNDLE%\comfyui\`.
- Pre-installed Spellcaster plugin under `%BUNDLE%\plugin\comfyui-connector\`.
- Pre-installed `ComfyUI-Spellcaster` node pack in `%BUNDLE%\comfyui\ComfyUI\custom_nodes\`.
- Pre-seeded ControlNet files in `%BUNDLE%\comfyui\ComfyUI\models\controlnet\` — same curated URLs as `step_check_cn_coverage`.
- Launcher `SpellcasterStudio.bat` that starts ComfyUI headless → waits for it → launches GIMP with env vars pointing at the bundle's plugin dir + config dir.
- Pre-configured `config.json` with `server_url=http://127.0.0.1:8188` and `apply_theme=true`.
- `README.txt` for end users.

### Out-of-scope for MVP

- macOS / Linux bundles (documented path; not built yet).
- Pre-bundled checkpoint models (too big — 7B+ GB per file). Users download via Guild's setup wizard or ComfyUI Manager.
- LLM (KoboldCpp / Ollama) bundling. Guild falls back to ComfyUI-side LLM detection.
- Wizard Guild bundled and auto-started. Phase 2.

### Naming

"Spellcaster Studio" — per GIMP trademark policy, a redistributed GIMP with modifications or bundling should use a different name. "Studio" tags on the additional DAW-like integration (GIMP + ComfyUI + plugin, positioned as one studio). Logo + splash use our existing branding (`plugins/gimp/comfyui-connector/spellcaster-theme.css` palette).

---

## Bundle Layout

```
SpellcasterStudio-v2.3-win64/
├── SpellcasterStudio.bat          ← double-click to launch
├── SpellcasterStudio-FirstRun.bat ← silent-installs GIMP to bundle dir on first run
├── README.txt                      ← user-facing docs
├── LICENSE.txt                     ← GPL + credits
│
├── gimp/                           ← populated by first-run installer
│   ├── bin/gimp-3.0.exe
│   └── ...
│
├── comfyui/                        ← ComfyUI Portable, as-shipped
│   ├── python_embedded/
│   ├── ComfyUI/
│   │   ├── main.py
│   │   ├── custom_nodes/
│   │   │   └── ComfyUI-Spellcaster/  ← our pack, pre-cloned
│   │   ├── models/
│   │   │   ├── checkpoints/        ← empty, user drops models here
│   │   │   ├── loras/
│   │   │   ├── controlnet/         ← pre-populated with canonical CNs
│   │   │   │   ├── SDXL/controlnet-union-sdxl-1.0/diffusion_pytorch_model.safetensors
│   │   │   │   ├── control_v11p_sd15_normalbae.pth
│   │   │   │   ├── control_v11f1p_sd15_depth_fp16.safetensors
│   │   │   │   ├── control_v11p_sd15_lineart_fp16.safetensors
│   │   │   │   └── FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors
│   │   │   ├── vae/
│   │   │   └── ...
│   │   └── output/
│   └── run_nvidia_gpu.bat          ← ComfyUI's stock launcher (bundle uses its own)
│
├── plugin/
│   └── comfyui-connector/          ← pre-installed plugin
│       ├── _spellcaster_main.py
│       ├── comfyui-connector.py
│       ├── spellcaster_core/
│       ├── spellcaster-theme.css
│       ├── config.json             ← pre-configured: server_url=127.0.0.1:8188, apply_theme=true
│       └── ...
│
└── data/                           ← persistent bundle state (NOT user's %APPDATA%)
    ├── gimp_config/                ← GIMP3_DIRECTORY target
    ├── output/                     ← user-facing output dir (config.json points here)
    └── logs/
        ├── comfyui.log
        └── launcher.log
```

**Key principle:** the bundle writes to `%BUNDLE%\data\` not `%APPDATA%\GIMP\`. This makes the bundle truly portable — user can put it on a USB stick, move it between machines, delete to fully remove. Achieved via `GIMP3_DIRECTORY` env var and the plugin reading its own config from `_PLUGIN_DIR / "config.json"` (already the case).

---

## Launcher `SpellcasterStudio.bat`

```batch
@echo off
setlocal EnableDelayedExpansion

set "BUNDLE=%~dp0"
set "BUNDLE=!BUNDLE:~0,-1!"

REM Bundle-local config dirs so we don't touch the user's %APPDATA%.
set "GIMP3_DIRECTORY=!BUNDLE!\data\gimp_config"
set "SPELLCASTER_BUNDLE=1"
set "SPELLCASTER_COMFY=http://127.0.0.1:8188"

REM First-run: install GIMP into bundle if missing.
if not exist "!BUNDLE!\gimp\bin\gimp-3.0.exe" (
    call "!BUNDLE!\SpellcasterStudio-FirstRun.bat"
    if errorlevel 1 (
        echo First-run setup failed. See data\logs\launcher.log.
        pause
        exit /b 1
    )
)

REM Point GIMP at the bundled plugin dir.
set "GIMP3_PLUG_IN_PATH=!BUNDLE!\plugin"

REM Start ComfyUI headless in a detached window.
start "Spellcaster — ComfyUI backend" /D "!BUNDLE!\comfyui" /MIN cmd /c ^
  "python_embedded\python.exe -s ComfyUI\main.py --listen 127.0.0.1 --port 8188 > ..\data\logs\comfyui.log 2>&1"

REM Wait for ComfyUI ready (polls /system_stats up to 60 s).
set /a TRIES=0
:WAIT
set /a TRIES+=1
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8188/system_stats > "%TEMP%\sc_probe.txt" 2>nul
set /p CODE=<"%TEMP%\sc_probe.txt"
if "!CODE!"=="200" goto READY
if !TRIES! GEQ 30 (
    echo ComfyUI did not become ready in 60 s. Check data\logs\comfyui.log.
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul
goto WAIT
:READY

REM Launch GIMP.
"!BUNDLE!\gimp\bin\gimp-3.0.exe"

REM Stop ComfyUI when GIMP exits.
taskkill /IM python.exe /F /FI "WINDOWTITLE eq Spellcaster - ComfyUI backend*" >nul 2>&1

endlocal
exit /b 0
```

---

## First-Run Installer `SpellcasterStudio-FirstRun.bat`

Silently installs GIMP into `%BUNDLE%\gimp\`. Shipping the official installer .exe and running with `/S /D=%BUNDLE%\gimp` flags.

```batch
@echo off
set "BUNDLE=%~dp0"
set "BUNDLE=!BUNDLE:~0,-1!"

if exist "!BUNDLE!\gimp\bin\gimp-3.0.exe" exit /b 0

echo Spellcaster Studio — first-time setup (installing GIMP locally to bundle)...

REM Ship gimp-installer.exe in the bundle root; remove after install.
if not exist "!BUNDLE!\gimp-installer.exe" (
    echo GIMP installer missing. Re-download the bundle.
    exit /b 1
)

REM Silent install to bundle/gimp/.
"!BUNDLE!\gimp-installer.exe" /VERYSILENT /NORESTART /DIR="!BUNDLE!\gimp" /LOG="!BUNDLE!\data\logs\gimp_install.log"
if errorlevel 1 exit /b 1

REM Drop the installer — it's now in the install dir as a backup.
del "!BUNDLE!\gimp-installer.exe"

exit /b 0
```

Alternative considered: bundle GIMP Portable from PortableApps.com. Rejected because PA build lags official GIMP by 1-2 weeks, and their wrapper adds complexity.

---

## Build Script `tools/build_portable_bundle.py`

Orchestrates the full bundle creation:

1. Create fresh `dist/SpellcasterStudio-vX.Y-win64/` tree.
2. Download + extract ComfyUI Portable from GitHub releases (pin version).
3. `git clone` `ComfyUI-Spellcaster` pack into `custom_nodes/`.
4. Stage the plugin tree (copy from `plugins/gimp/comfyui-connector/` + spellcaster_core).
5. Pre-populate `config.json` with bundle-appropriate defaults.
6. Download canonical ControlNet files via `urllib` using the same `CN_URL_MAP` as `model_repair.py` + `installer/install.py` (single source of truth — we import from the pack).
7. Download latest GIMP Windows installer from gimp.org releases into bundle root.
8. Drop in `SpellcasterStudio.bat` + `SpellcasterStudio-FirstRun.bat` + `README.txt` + `LICENSE.txt` from `tools/portable_bundle_templates/`.
9. Zip everything.

Output: `dist/SpellcasterStudio-v2.3-win64.zip` (~12 GB with all CNs + ComfyUI + GIMP installer).

---

## Size Estimate

| Component | Size |
|-----------|------|
| ComfyUI Portable (python_embedded + deps) | ~3.0 GB |
| GIMP installer (.exe) | ~300 MB |
| ComfyUI-Spellcaster pack (git clone) | ~30 MB |
| Spellcaster plugin files | ~15 MB |
| SDXL Union Pro CN (promax) | 2.5 GB |
| Flux Union Pro 2.0 CN | 2.5 GB |
| SD 1.5 normalbae + depth + lineart | ~3 GB |
| Tavern + scaffold + misc | ~100 MB |
| **Total uncompressed** | **~11.4 GB** |
| **Zip (estimated)** | **~8.5 GB** |

Distribution: GitHub Releases has a 2 GB per-file limit → split-zip OR host on archive.org / Hugging Face datasets / Cloudflare R2. Phase-2: a "lite" variant (no CNs; installer downloads on first run) targets 3 GB and fits GitHub Releases.

---

## Phased Rollout

### Phase 1 — Windows MVP (1-2 weeks)

- `tools/build_portable_bundle.py` script functional.
- One reference bundle published (manually uploaded to HF).
- README + first-run UX tested on a clean Windows VM.

### Phase 2 — "Lite" variant (+1 week)

- Same bundle but without pre-downloaded CN files.
- First-run launcher invokes `step_check_cn_coverage` to auto-download on first ComfyUI boot.
- Target 3 GB zip (fits GitHub Releases).

### Phase 3 — macOS + Linux (+2 weeks)

- macOS: `.dmg` with GIMP app bundle + a `SpellcasterStudio.command` launcher. ComfyUI runs from inside the `.app`.
- Linux: `.AppImage` wrapping GIMP flatpak + ComfyUI in a portable venv.

### Phase 4 — Wizard Guild bundled (+1 week)

- Bundle ships with `tavern/` pre-configured.
- Launcher starts Guild as a tray app alongside GIMP.
- All `/api/*` endpoints live on first launch — cross-interface backbone works out of the box.

---

## Risks + Mitigations

| Risk | Mitigation |
|------|------------|
| GIMP trademark — redistributing "GIMP" with modifications | Rename bundle "Spellcaster Studio"; credit GIMP in README + LICENSE |
| Bundle size exceeds GitHub Releases 2 GB limit | Lite variant OR split-zip OR external hosting (Hugging Face Datasets / archive.org) |
| ComfyUI Portable upstream breaks compat | Pin to a known-good release tag; update bundle per-release w/ smoke-test |
| GIMP silent-install fails on locked-down Windows | Fall back to user-level install in `%LOCALAPPDATA%` (documented in launcher) |
| Python embedded can't install spellcaster_core deps | Pre-bake all deps into `python_embedded/site-packages/` at build time |
| NVIDIA driver mismatch (user's GPU < our PyTorch/xformers build) | Ship CUDA 12.x build as default; add `run_cpu.bat` fallback for no-GPU case |
| Maintenance cost per release | Automate via GitHub Actions: tag push → builder runs → artifacts uploaded |

---

## Legal + Licensing

- **GIMP**: GPLv3. Redistribution allowed; trademark requires different name.
- **ComfyUI**: GPLv3. Same.
- **Spellcaster plugin + spellcaster_core**: MIT (per existing LICENSE). Compatible with GPL.
- **ControlNet files**: each has its own license on Hugging Face — Xinsir Union (Apache 2.0), Shakker Labs Flux Union Pro (CreativeML OpenRAIL-M), lllyasviel v1.1 set (OpenRAIL). All permit redistribution with credit. Document in bundle's `LICENSE.txt`.
- **NSFW content**: NEVER in the public bundle. Private NSFW variant built separately via `nsfw/build_nsfw.py` (bundle builder has a `--nsfw` flag that's gated on `nsfw/` dir existing + reads from the private repo's bundle).

---

## Success Criteria

- **One-step onboarding**: user downloads zip → extracts → double-clicks .bat → GIMP opens with Spellcaster menu populated + ComfyUI running + connected status green.
- **Time-to-first-generation**: < 3 minutes from zip download on 100 Mbps.
- **Truly portable**: bundle works from any path (including USB stick), writes nothing outside its own dir.
- **Zero config**: no need for user to edit any file. Pre-populated `config.json` is correct for the bundle layout.
- **Update story**: bundle's plugin auto-updates from GitHub on GIMP launch (per `auto_update: true` default) — no re-bundling needed for plugin-only patches.
