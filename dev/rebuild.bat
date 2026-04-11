@echo off
setlocal enabledelayedexpansion

:: ══════════════════════════════════════════════════════════════════════
::  Spellcaster — Full Rebuild, Push & Release
:: ══════════════════════════════════════════════════════════════════════
::
::  Rebuilds ALL executables (installer, manual-update, wizard-guild),
::  pushes source changes to both SFW and NSFW repos, and uploads
::  binaries to a GitHub Release.
::
::  Usage:
::      rebuild.bat                    — rebuild everything + push + release
::      rebuild.bat --no-push          — rebuild only, no git/github ops
::      rebuild.bat --installer-only   — only rebuild installer + updater
::      rebuild.bat --guild-only       — only rebuild wizard guild
::      rebuild.bat --push-only        — skip builds, just push source + release
::      rebuild.bat --tag v2.2         — set release tag (default: auto)
::
::  Requirements:
::      - Python 3.10+ with pip
::      - PyInstaller (auto-installed if missing)
::      - Git configured with push access to both repos
::
::  This script MUST be run on Windows (PyInstaller cannot cross-compile).
::
::  NOTE: Built .exe files are uploaded to GitHub Releases, NOT committed.
:: ══════════════════════════════════════════════════════════════════════

title Spellcaster Rebuild

:: ── Parse arguments ─────────────────────────────────────────────────
set "NO_PUSH=0"
set "INSTALLER_ONLY=0"
set "GUILD_ONLY=0"
set "PUSH_ONLY=0"
set "RELEASE_TAG="

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--no-push"          set "NO_PUSH=1"         & shift & goto parse_args
if /i "%~1"=="--installer-only"   set "INSTALLER_ONLY=1"   & shift & goto parse_args
if /i "%~1"=="--guild-only"       set "GUILD_ONLY=1"       & shift & goto parse_args
if /i "%~1"=="--push-only"        set "PUSH_ONLY=1"        & shift & goto parse_args
if /i "%~1"=="--tag"              set "RELEASE_TAG=%~2"    & shift & shift & goto parse_args
echo Unknown argument: %~1
echo Usage: rebuild.bat [--no-push] [--installer-only] [--guild-only] [--push-only] [--tag vX.Y]
exit /b 1
:args_done

:: ── Locate repo roots ───────────────────────────────────────────────
:: This script lives in dev/ — repo root is one level up
for %%I in ("%~dp0..") do set "SFW_ROOT=%%~fI"

:: Try to find NSFW repo as sibling
set "NSFW_ROOT="
for %%D in ("%SFW_ROOT%\..\spellcaster_NSFW" "%SFW_ROOT%\..\spellcaster-nsfw" "%SFW_ROOT%\..\Spellcaster_NSFW") do (
    if exist "%%~fD\.git" (
        set "NSFW_ROOT=%%~fD"
        goto found_nsfw
    )
)
if defined NSFW_REPO (
    if exist "%NSFW_REPO%\.git" (
        set "NSFW_ROOT=%NSFW_REPO%"
        goto found_nsfw
    )
)
echo.
echo   [WARN] NSFW repo not found as sibling directory.
echo          Set NSFW_REPO env var or place it next to this repo.
echo          Continuing with SFW only...
echo.
:found_nsfw

:: ── Verify Python ───────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH.
    exit /b 1
)

echo.
echo ══════════════════════════════════════════════════════════════
echo   Spellcaster Rebuild
echo ══════════════════════════════════════════════════════════════
echo.
echo   SFW repo:   %SFW_ROOT%
if defined NSFW_ROOT (
    echo   NSFW repo:  %NSFW_ROOT%
) else (
    echo   NSFW repo:  [not found]
)
if defined RELEASE_TAG echo   Tag:        %RELEASE_TAG%
echo.

:: ══════════════════════════════════════════════════════════════════════
::  STEP 1 — Build dependencies
:: ══════════════════════════════════════════════════════════════════════
echo [1/7] Checking build dependencies...
python -m pip install --quiet --upgrade pyinstaller customtkinter pillow requests darkdetect 2>nul
echo   Done.
echo.

if "%PUSH_ONLY%"=="1" goto skip_builds

:: ══════════════════════════════════════════════════════════════════════
::  STEP 2 — Clean previous builds
:: ══════════════════════════════════════════════════════════════════════
echo [2/7] Cleaning previous builds...
if exist "%SFW_ROOT%\dist" (
    del /q "%SFW_ROOT%\dist\*.exe" 2>nul
    echo   Cleaned dist\
)
if exist "%SFW_ROOT%\build" (
    rmdir /s /q "%SFW_ROOT%\build" 2>nul
    echo   Cleaned build\
)
echo.

:: ══════════════════════════════════════════════════════════════════════
::  STEP 3 — Build installer + manual update
:: ══════════════════════════════════════════════════════════════════════
if "%GUILD_ONLY%"=="1" goto skip_installer

echo [3/7] Building installer + manual update tool...
echo.
pushd "%SFW_ROOT%\installer"
python build_installer.py --platform windows --update-tool
set "INSTALLER_EXIT=%errorlevel%"
popd

if not "%INSTALLER_EXIT%"=="0" (
    echo.
    echo   ERROR: Installer build FAILED!
    exit /b %INSTALLER_EXIT%
)

if exist "%SFW_ROOT%\dist\spellcaster-installer.exe" (
    for %%F in ("%SFW_ROOT%\dist\spellcaster-installer.exe") do echo   spellcaster-installer.exe ...... %%~zF bytes  OK
) else (
    echo   [WARN] spellcaster-installer.exe not found in dist\
)
if exist "%SFW_ROOT%\dist\spellcaster-manual-update.exe" (
    for %%F in ("%SFW_ROOT%\dist\spellcaster-manual-update.exe") do echo   spellcaster-manual-update.exe . %%~zF bytes  OK
)
echo.

:skip_installer

:: ══════════════════════════════════════════════════════════════════════
::  STEP 4 — Build Wizard Guild
:: ══════════════════════════════════════════════════════════════════════
if "%INSTALLER_ONLY%"=="1" goto skip_guild

echo [4/7] Building Wizard Guild...
echo.
pushd "%SFW_ROOT%\tavern"
python build_guild.py --platform windows
set "GUILD_EXIT=%errorlevel%"
popd

if not "%GUILD_EXIT%"=="0" (
    echo.
    echo   ERROR: Wizard Guild build FAILED!
    exit /b %GUILD_EXIT%
)

if exist "%SFW_ROOT%\dist\wizard-guild.exe" (
    copy /y "%SFW_ROOT%\dist\wizard-guild.exe" "%SFW_ROOT%\dist\Wizard_Guild.exe" >nul
    for %%F in ("%SFW_ROOT%\dist\Wizard_Guild.exe") do echo   Wizard_Guild.exe ............. %%~zF bytes  OK
)
echo.

:skip_guild
:skip_builds

if "%NO_PUSH%"=="1" (
    echo [--no-push] Skipping all git/github operations.
    goto show_summary
)

:: ══════════════════════════════════════════════════════════════════════
::  STEP 5 — Commit & push SOURCE to SFW repo
:: ══════════════════════════════════════════════════════════════════════
echo [5/7] Pushing source changes to SFW repo...
pushd "%SFW_ROOT%"

if exist ".git\index.lock" del /f ".git\index.lock" 2>nul

:: Stage source changes (dist/ excluded by .gitignore)
git add -A
git status --short

git diff --cached --quiet
if errorlevel 1 (
    git commit -m "build: rebuild all executables"
    echo   Committed.
) else (
    echo   No source changes to commit.
)

echo   Pushing...
git push origin main
if errorlevel 1 (
    echo   [WARN] SFW push failed.
) else (
    echo   SFW pushed OK.
)
popd
echo.

:: ══════════════════════════════════════════════════════════════════════
::  STEP 6 — Mirror source to NSFW repo & push
:: ══════════════════════════════════════════════════════════════════════
echo [6/7] Mirroring source to NSFW repo...

if not defined NSFW_ROOT (
    echo   Skipped.
    goto upload_release
)

echo   Copying shared source files...

:: Tavern — copy individual files, preserve NSFW-injected content
for %%F in (server.py guild_launcher.py guild_common.py build_guild.py) do (
    if exist "%SFW_ROOT%\tavern\%%F" (
        copy /y "%SFW_ROOT%\tavern\%%F" "%NSFW_ROOT%\tavern\%%F" >nul 2>&1
    )
)
:: Tavern static
robocopy "%SFW_ROOT%\tavern\static" "%NSFW_ROOT%\tavern\static" /s /xd __pycache__ >nul 2>&1

:: Installer
robocopy "%SFW_ROOT%\installer" "%NSFW_ROOT%\installer" /s /xd __pycache__ .build-venv dist build >nul 2>&1

:: Plugins
robocopy "%SFW_ROOT%\plugins" "%NSFW_ROOT%\plugins" /s /xd __pycache__ >nul 2>&1

:: ComfyUI-Spellcaster — sync base files from SFW, preserve NSFW-only additions
:: (nsfw_loras.py, __init__.py, web/spellcaster.js, README, pyproject.toml are NSFW-specific)
robocopy "%SFW_ROOT%\comfyui-spellcaster\spellcaster_core" "%NSFW_ROOT%\comfyui-spellcaster\spellcaster_core" /s /xd __pycache__ >nul 2>&1
for %%F in (loader.py sampler.py output.py prompt.py) do (
    if exist "%SFW_ROOT%\comfyui-spellcaster\nodes\%%F" (
        copy /y "%SFW_ROOT%\comfyui-spellcaster\nodes\%%F" "%NSFW_ROOT%\comfyui-spellcaster\nodes\%%F" >nul 2>&1
    )
)
robocopy "%SFW_ROOT%\comfyui-spellcaster\example_workflows" "%NSFW_ROOT%\comfyui-spellcaster\example_workflows" spellcaster_txt2img.json spellcaster_img2img.json >nul 2>&1

:: Scaffold — individual files to preserve NSFW-only modules
for %%F in (meta_wizard.py introspector.py workflow_wizard.py workflow_parser.py comfyui_runner.py presets.py prompt_builder.py wizard.py bridge_launcher.py pipeline_wizard.py __init__.py) do (
    if exist "%SFW_ROOT%\scaffold\%%F" (
        copy /y "%SFW_ROOT%\scaffold\%%F" "%NSFW_ROOT%\scaffold\%%F" >nul 2>&1
    )
)
if exist "%SFW_ROOT%\scaffold\workflows" (
    robocopy "%SFW_ROOT%\scaffold\workflows" "%NSFW_ROOT%\scaffold\workflows" /s >nul 2>&1
)

:: GitHub workflows
robocopy "%SFW_ROOT%\.github" "%NSFW_ROOT%\.github" /s >nul 2>&1

:: Root scripts (user-facing)
for %%F in (Install.bat Settings.bat "Wizard Guild.bat") do (
    if exist "%SFW_ROOT%\%%~F" (
        copy /y "%SFW_ROOT%\%%~F" "%NSFW_ROOT%\%%~F" >nul 2>&1
    )
)
:: Dev scripts
if not exist "%NSFW_ROOT%\dev" mkdir "%NSFW_ROOT%\dev"
for %%F in (rebuild.bat release_upload.py update.bat) do (
    if exist "%SFW_ROOT%\dev\%%F" (
        copy /y "%SFW_ROOT%\dev\%%F" "%NSFW_ROOT%\dev\%%F" >nul 2>&1
    )
)

echo   Committing NSFW repo...
pushd "%NSFW_ROOT%"

if exist ".git\index.lock" del /f ".git\index.lock" 2>nul

git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "build: rebuild all executables (mirrored from SFW)"
    echo   Committed.
) else (
    echo   No changes in NSFW.
)

echo   Pushing...
git push origin main
if errorlevel 1 (
    echo   [WARN] NSFW push failed.
) else (
    echo   NSFW pushed OK.
)
popd
echo.

:: ══════════════════════════════════════════════════════════════════════
::  STEP 7 — Upload binaries to GitHub Release
:: ══════════════════════════════════════════════════════════════════════
:upload_release
echo [7/7] Uploading binaries to GitHub Release...

:: Auto-detect tag if not set
if not defined RELEASE_TAG (
    for /f "tokens=*" %%V in ('python -c "import re; m=re.search(r'VERSION\s*=\s*[\"'']([^\"'']+)[\"'']', open('tavern/guild_launcher.py').read()); print('v'+m.group(1) if m else '')" 2^>nul') do set "RELEASE_TAG=%%V"
)
if not defined RELEASE_TAG (
    echo   [WARN] No --tag provided and could not auto-detect version.
    echo          Use: rebuild.bat --tag v2.2
    goto show_summary
)

:: Check if gh CLI is available
where gh >nul 2>&1
if errorlevel 1 goto use_python_upload

:: ── Upload via gh CLI ───────────────────────────────────────────────
pushd "%SFW_ROOT%"
echo   Using gh CLI...
echo   Release tag: %RELEASE_TAG%

gh release view %RELEASE_TAG% >nul 2>&1
if errorlevel 1 (
    echo   Creating release %RELEASE_TAG%...
    gh release create %RELEASE_TAG% --title "%RELEASE_TAG%" --notes "Rebuilt Windows executables." --latest
)

if exist "%SFW_ROOT%\dist\spellcaster-installer.exe" (
    echo   Uploading spellcaster-installer.exe...
    gh release upload %RELEASE_TAG% "%SFW_ROOT%\dist\spellcaster-installer.exe" --clobber
)
if exist "%SFW_ROOT%\dist\spellcaster-manual-update.exe" (
    echo   Uploading spellcaster-manual-update.exe...
    gh release upload %RELEASE_TAG% "%SFW_ROOT%\dist\spellcaster-manual-update.exe" --clobber
)
if exist "%SFW_ROOT%\dist\Wizard_Guild.exe" (
    echo   Uploading Wizard_Guild.exe...
    gh release upload %RELEASE_TAG% "%SFW_ROOT%\dist\Wizard_Guild.exe" --clobber
)
echo   Done.
popd
goto show_summary

:: ── Upload via Python (no gh CLI) ───────────────────────────────────
:use_python_upload
echo   gh CLI not found, using Python uploader...
pushd "%SFW_ROOT%"

if exist "%SFW_ROOT%\dev\release_upload.py" (
    python "%SFW_ROOT%\dev\release_upload.py" --tag %RELEASE_TAG% --dist "%SFW_ROOT%\dist"
) else (
    echo   ERROR: dev\release_upload.py not found. Install gh CLI or restore it.
)
popd

:: ══════════════════════════════════════════════════════════════════════
::  Summary
:: ══════════════════════════════════════════════════════════════════════
:show_summary
echo.
echo ══════════════════════════════════════════════════════════════
echo   Rebuild complete!
echo ══════════════════════════════════════════════════════════════
echo.

if not "%PUSH_ONLY%"=="1" (
    echo   Built executables in dist\:
    if exist "%SFW_ROOT%\dist\spellcaster-installer.exe" (
        for %%F in ("%SFW_ROOT%\dist\spellcaster-installer.exe") do echo     spellcaster-installer.exe ...... %%~zF bytes
    )
    if exist "%SFW_ROOT%\dist\spellcaster-manual-update.exe" (
        for %%F in ("%SFW_ROOT%\dist\spellcaster-manual-update.exe") do echo     spellcaster-manual-update.exe . %%~zF bytes
    )
    if exist "%SFW_ROOT%\dist\Wizard_Guild.exe" (
        for %%F in ("%SFW_ROOT%\dist\Wizard_Guild.exe") do echo     Wizard_Guild.exe ............. %%~zF bytes
    )
    echo.
)

if defined RELEASE_TAG (
    echo   Release: https://github.com/laboratoiresonore/spellcaster/releases/tag/%RELEASE_TAG%
    echo.
)

pause
