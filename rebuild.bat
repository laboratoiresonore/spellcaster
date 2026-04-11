@echo off
setlocal enabledelayedexpansion

:: ══════════════════════════════════════════════════════════════════════
::  Spellcaster — Full Rebuild & Push
:: ══════════════════════════════════════════════════════════════════════
::
::  Rebuilds ALL executables (installer, manual-update, wizard-guild),
::  commits them, and pushes to both SFW and NSFW GitHub repos.
::
::  Usage:
::      rebuild.bat                    — rebuild everything + commit + push
::      rebuild.bat --no-push          — rebuild + commit but skip push
::      rebuild.bat --installer-only   — only rebuild installer + updater
::      rebuild.bat --guild-only       — only rebuild wizard guild
::      rebuild.bat --push-only        — skip builds, just commit + push
::
::  Requirements:
::      - Python 3.10+ with pip
::      - PyInstaller (auto-installed if missing)
::      - Git configured with push access to both repos
::
::  This script MUST be run on Windows (PyInstaller cannot cross-compile).
:: ══════════════════════════════════════════════════════════════════════

title Spellcaster Rebuild

:: ── Parse arguments ─────────────────────────────────────────────────
set "NO_PUSH=0"
set "INSTALLER_ONLY=0"
set "GUILD_ONLY=0"
set "PUSH_ONLY=0"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--no-push"          set "NO_PUSH=1"       & shift & goto parse_args
if /i "%~1"=="--installer-only"   set "INSTALLER_ONLY=1" & shift & goto parse_args
if /i "%~1"=="--guild-only"       set "GUILD_ONLY=1"     & shift & goto parse_args
if /i "%~1"=="--push-only"        set "PUSH_ONLY=1"      & shift & goto parse_args
echo Unknown argument: %~1
echo Usage: rebuild.bat [--no-push] [--installer-only] [--guild-only] [--push-only]
exit /b 1
:args_done

:: ── Locate repo roots ───────────────────────────────────────────────
:: This script lives in the SFW repo root. NSFW repo is expected as a
:: sibling directory named spellcaster_NSFW, OR wherever the user has it.
:: We detect via the .git/config remote URL.

set "SFW_ROOT=%~dp0"
:: Strip trailing backslash
if "%SFW_ROOT:~-1%"=="\" set "SFW_ROOT=%SFW_ROOT:~0,-1%"

:: Try to find NSFW repo as sibling
set "NSFW_ROOT="
for %%D in ("%SFW_ROOT%\..\spellcaster_NSFW" "%SFW_ROOT%\..\spellcaster-nsfw" "%SFW_ROOT%\..\Spellcaster_NSFW") do (
    if exist "%%~fD\.git" (
        set "NSFW_ROOT=%%~fD"
        goto found_nsfw
    )
)
:: Not found as sibling — check if there's an NSFW_REPO env var
if defined NSFW_REPO (
    if exist "%NSFW_REPO%\.git" (
        set "NSFW_ROOT=%NSFW_REPO%"
        goto found_nsfw
    )
)
echo.
echo   [WARN] NSFW repo not found as sibling directory.
echo          Set NSFW_REPO=path\to\spellcaster_NSFW or place it next to this repo.
echo          Continuing with SFW only...
echo.
:found_nsfw

:: ── Verify Python ───────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH. Install Python 3.10+ and try again.
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
    echo   NSFW repo:  [not found — SFW only]
)
echo.

:: ── Install build dependencies ──────────────────────────────────────
echo [1/6] Checking build dependencies...
python -m pip install --quiet --upgrade pyinstaller customtkinter pillow requests darkdetect 2>nul
if errorlevel 1 (
    echo   [WARN] pip install had issues — continuing anyway...
)
echo   Done.
echo.

:: ── Clean previous builds ───────────────────────────────────────────
if "%PUSH_ONLY%"=="1" goto skip_builds

echo [2/6] Cleaning previous builds...
if exist "%SFW_ROOT%\dist" (
    del /q "%SFW_ROOT%\dist\*.exe" 2>nul
    del /q "%SFW_ROOT%\dist\*.app" 2>nul
    echo   Cleaned dist/
)
if exist "%SFW_ROOT%\build" (
    rmdir /s /q "%SFW_ROOT%\build" 2>nul
    echo   Cleaned build/
)
echo.

:: ── Build installer + manual update ────────────────────────────────
if "%GUILD_ONLY%"=="1" goto skip_installer

echo [3/6] Building installer + manual update tool...
echo.
pushd "%SFW_ROOT%\installer"
python build_installer.py --platform windows --update-tool
set "INSTALLER_EXIT=%errorlevel%"
popd

if not "%INSTALLER_EXIT%"=="0" (
    echo.
    echo   ERROR: Installer build failed!
    exit /b %INSTALLER_EXIT%
)

:: Rename installer exe for release clarity
if exist "%SFW_ROOT%\dist\spellcaster-installer.exe" (
    echo   spellcaster-installer.exe .... OK
) else (
    echo   [WARN] spellcaster-installer.exe not found in dist/
)
if exist "%SFW_ROOT%\dist\spellcaster-manual-update.exe" (
    echo   spellcaster-manual-update.exe  OK
)
echo.

:skip_installer

:: ── Build Wizard Guild ──────────────────────────────────────────────
if "%INSTALLER_ONLY%"=="1" goto skip_guild

echo [4/6] Building Wizard Guild...
echo.
pushd "%SFW_ROOT%\tavern"
python build_guild.py --platform windows
set "GUILD_EXIT=%errorlevel%"
popd

if not "%GUILD_EXIT%"=="0" (
    echo.
    echo   ERROR: Wizard Guild build failed!
    exit /b %GUILD_EXIT%
)

:: Rename to Wizard_Guild.exe for GitHub release naming convention
if exist "%SFW_ROOT%\dist\wizard-guild.exe" (
    copy /y "%SFW_ROOT%\dist\wizard-guild.exe" "%SFW_ROOT%\dist\Wizard_Guild.exe" >nul
    echo   Wizard_Guild.exe ............. OK
)
echo.

:skip_guild
:skip_builds

:: ══════════════════════════════════════════════════════════════════════
::  Git commit & push — SFW
:: ══════════════════════════════════════════════════════════════════════
echo [5/6] Committing to SFW repo...
pushd "%SFW_ROOT%"

:: Clean git locks if stale
if exist ".git\index.lock" del /f ".git\index.lock" 2>nul

:: Stage all changed files (source + built executables)
git add -A
git status --short

:: Check if there's anything to commit
git diff --cached --quiet
if errorlevel 1 (
    :: There are staged changes — commit
    git commit -m "build: rebuild all executables"
    echo   Committed to SFW.
) else (
    echo   Nothing to commit in SFW.
)

if "%NO_PUSH%"=="1" (
    echo   [--no-push] Skipping push.
) else (
    echo   Pushing SFW to origin...
    git push origin main
    if errorlevel 1 (
        echo   [WARN] SFW push failed — check credentials or network.
    ) else (
        echo   SFW pushed OK.
    )
)
popd
echo.

:: ══════════════════════════════════════════════════════════════════════
::  Mirror to NSFW repo & push
:: ══════════════════════════════════════════════════════════════════════
echo [6/6] Mirroring to NSFW repo...

if not defined NSFW_ROOT (
    echo   Skipped — NSFW repo not found.
    goto done
)

:: Copy all source files that the NSFW repo shares with SFW.
:: The NSFW repo is structurally identical but may have extra NSFW content
:: injected by build_nsfw.py. We mirror ONLY the files we build/modify:
::   - tavern/server.py, guild_launcher.py (prompt enhance, config)
::   - tavern/build_guild.py (build script)
::   - installer/* (installer source + build script)
::   - plugins/gimp/comfyui-connector/* (workflows, nodes, architectures)
::   - scaffold/* (wizard modules)
::   - dist/* (built executables)
::   - .github/workflows/* (CI)
::   - rebuild.bat (this script)

echo   Copying shared source files...
robocopy "%SFW_ROOT%\tavern"    "%NSFW_ROOT%\tavern"    /mir /xd __pycache__ static >nul 2>&1
robocopy "%SFW_ROOT%\tavern\static" "%NSFW_ROOT%\tavern\static" /mir /xd __pycache__ >nul 2>&1
robocopy "%SFW_ROOT%\installer" "%NSFW_ROOT%\installer" /mir /xd __pycache__ .build-venv >nul 2>&1
robocopy "%SFW_ROOT%\plugins"   "%NSFW_ROOT%\plugins"   /mir /xd __pycache__ >nul 2>&1
robocopy "%SFW_ROOT%\scaffold"  "%NSFW_ROOT%\scaffold"  /mir /xd __pycache__ >nul 2>&1
robocopy "%SFW_ROOT%\dist"      "%NSFW_ROOT%\dist"      /mir >nul 2>&1
robocopy "%SFW_ROOT%\.github"   "%NSFW_ROOT%\.github"   /mir >nul 2>&1

:: Copy individual root files
copy /y "%SFW_ROOT%\rebuild.bat"    "%NSFW_ROOT%\rebuild.bat" >nul 2>&1
copy /y "%SFW_ROOT%\install.bat"    "%NSFW_ROOT%\install.bat" >nul 2>&1
copy /y "%SFW_ROOT%\update.bat"     "%NSFW_ROOT%\update.bat"  >nul 2>&1

echo   Committing NSFW repo...
pushd "%NSFW_ROOT%"

if exist ".git\index.lock" del /f ".git\index.lock" 2>nul

git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "build: rebuild all executables (mirrored from SFW)"
    echo   Committed to NSFW.
) else (
    echo   Nothing to commit in NSFW.
)

if "%NO_PUSH%"=="1" (
    echo   [--no-push] Skipping push.
) else (
    echo   Pushing NSFW to origin...
    git push origin main
    if errorlevel 1 (
        echo   [WARN] NSFW push failed — check credentials or network.
    ) else (
        echo   NSFW pushed OK.
    )
)
popd
echo.

:done
echo.
echo ══════════════════════════════════════════════════════════════
echo   Rebuild complete!
echo ══════════════════════════════════════════════════════════════
echo.

:: Show what was built
if not "%PUSH_ONLY%"=="1" (
    echo   Built executables in dist/:
    if exist "%SFW_ROOT%\dist\spellcaster-installer.exe"    echo     spellcaster-installer.exe
    if exist "%SFW_ROOT%\dist\spellcaster-manual-update.exe" echo     spellcaster-manual-update.exe
    if exist "%SFW_ROOT%\dist\Wizard_Guild.exe"             echo     Wizard_Guild.exe
    echo.
)

echo   To create a GitHub release:
echo     1. Tag:  git tag v2.2
echo     2. Push: git push origin v2.2
echo     3. GitHub Actions will build all platforms and create a draft release.
echo.
echo   Or manually upload dist\*.exe to an existing release.
echo.

pause
