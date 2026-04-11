@echo off
setlocal enabledelayedexpansion

:: ══════════════════════════════════════════════════════════════════════
::  Spellcaster — Full Rebuild, Push & Release
:: ══════════════════════════════════════════════════════════════════════
::
::  Rebuilds ALL executables (installer, manual-update, wizard-guild),
::  pushes source changes to both SFW and NSFW repos, and uploads
::  binaries to a GitHub Release (never committed to git — too large).
::
::  Usage:
::      rebuild.bat                    — rebuild everything + push + release
::      rebuild.bat --no-push          — rebuild only, no git/github ops
::      rebuild.bat --installer-only   — only rebuild installer + updater
::      rebuild.bat --guild-only       — only rebuild wizard guild
::      rebuild.bat --push-only        — skip builds, just push source + release
::      rebuild.bat --tag v2.2         — set release tag (default: auto from VERSION)
::
::  Requirements:
::      - Python 3.10+ with pip
::      - PyInstaller (auto-installed if missing)
::      - Git configured with push access to both repos
::
::  This script MUST be run on Windows (PyInstaller cannot cross-compile).
::
::  NOTE: Built .exe files go into dist/ which is gitignored. They are
::  uploaded to GitHub Releases, NOT committed to the repo.
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
set "SFW_ROOT=%~dp0"
if "%SFW_ROOT:~-1%"=="\" set "SFW_ROOT=%SFW_ROOT:~0,-1%"

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
    echo   NSFW repo:  [not found]
)
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
    echo   Cleaned dist\*.exe
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
    echo   ERROR: Installer build FAILED ^^!
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
    echo   ERROR: Wizard Guild build FAILED ^^!
    exit /b %GUILD_EXIT%
)

:: Copy with release naming convention
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
::           (dist/ is NOT committed — binaries go to GitHub Releases)
:: ══════════════════════════════════════════════════════════════════════
echo [5/7] Pushing source changes to SFW repo...
pushd "%SFW_ROOT%"

if exist ".git\index.lock" del /f ".git\index.lock" 2>nul

:: Make sure dist/ and build/ are gitignored (don't commit 300MB binaries)
if not exist ".gitignore" (
    echo Creating .gitignore...
    (
        echo # Build artifacts — uploaded to GitHub Releases, not committed
        echo dist/
        echo build/
        echo *.spec
        echo *.spec.bak
        echo.
        echo # Virtual environments
        echo .build-venv/
        echo .venv/
        echo venv/
        echo.
        echo # Python
        echo __pycache__/
        echo *.py[cod]
        echo *.pyo
        echo *.pyd
        echo *.egg-info/
        echo .eggs/
        echo.
        echo # OS
        echo .DS_Store
        echo Thumbs.db
        echo Desktop.ini
    ) > .gitignore
    git add .gitignore
)

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
::           Uses selective copy (NOT /mir) to preserve NSFW-only content
:: ══════════════════════════════════════════════════════════════════════
echo [6/7] Mirroring source to NSFW repo...

if not defined NSFW_ROOT (
    echo   Skipped — NSFW repo not found.
    goto upload_release
)

echo   Copying shared source files...

:: Tavern — copy individual files, preserve NSFW-injected content
for %%F in (server.py guild_launcher.py guild_common.py build_guild.py) do (
    if exist "%SFW_ROOT%\tavern\%%F" (
        copy /y "%SFW_ROOT%\tavern\%%F" "%NSFW_ROOT%\tavern\%%F" >nul 2>&1
    )
)
:: Tavern static — full sync is safe (no NSFW-specific frontend files)
robocopy "%SFW_ROOT%\tavern\static" "%NSFW_ROOT%\tavern\static" /s /xd __pycache__ >nul 2>&1

:: Installer — full sync (no NSFW-specific installer files)
robocopy "%SFW_ROOT%\installer" "%NSFW_ROOT%\installer" /s /xd __pycache__ .build-venv dist build >nul 2>&1

:: Plugins — full sync
robocopy "%SFW_ROOT%\plugins" "%NSFW_ROOT%\plugins" /s /xd __pycache__ >nul 2>&1

:: Scaffold — copy individual files, preserve any NSFW-only modules
for %%F in (meta_wizard.py introspector.py workflow_wizard.py workflow_parser.py comfyui_runner.py presets.py prompt_builder.py wizard.py bridge_launcher.py pipeline_wizard.py __init__.py) do (
    if exist "%SFW_ROOT%\scaffold\%%F" (
        copy /y "%SFW_ROOT%\scaffold\%%F" "%NSFW_ROOT%\scaffold\%%F" >nul 2>&1
    )
)
:: Scaffold workflows — full sync
if exist "%SFW_ROOT%\scaffold\workflows" (
    robocopy "%SFW_ROOT%\scaffold\workflows" "%NSFW_ROOT%\scaffold\workflows" /s >nul 2>&1
)

:: GitHub workflows
robocopy "%SFW_ROOT%\.github" "%NSFW_ROOT%\.github" /s >nul 2>&1

:: Root scripts
for %%F in (rebuild.bat install.bat update.bat settings.bat) do (
    if exist "%SFW_ROOT%\%%F" (
        copy /y "%SFW_ROOT%\%%F" "%NSFW_ROOT%\%%F" >nul 2>&1
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
    echo   No changes to commit in NSFW.
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

:: Check if gh CLI is available
where gh >nul 2>&1
if errorlevel 1 (
    echo.
    echo   GitHub CLI (gh) not found. Falling back to Python uploader...
    echo.
    goto python_upload
)

:: Use gh CLI
pushd "%SFW_ROOT%"

:: Determine tag
if not defined RELEASE_TAG (
    :: Try to read version from guild_launcher or use date-based tag
    for /f "tokens=*" %%V in ('python -c "import re,sys; m=re.search(r'VERSION\s*=\s*\"([^\"]+)\"', open('tavern/guild_launcher.py').read()); print('v'+m.group(1) if m else '')" 2^>nul') do set "RELEASE_TAG=%%V"
)
if not defined RELEASE_TAG (
    :: Fallback: date-based tag
    for /f "tokens=*" %%D in ('python -c "import datetime; print('v'+datetime.date.today().strftime('%%Y.%%m.%%d'))"') do set "RELEASE_TAG=%%D"
)

echo   Release tag: %RELEASE_TAG%

:: Check if release already exists
gh release view %RELEASE_TAG% >nul 2>&1
if errorlevel 1 (
    echo   Creating new release %RELEASE_TAG%...
    gh release create %RELEASE_TAG% --title "%RELEASE_TAG%" --notes "Rebuilt Windows executables." --latest
) else (
    echo   Release %RELEASE_TAG% exists — uploading assets...
)

:: Upload each binary (--clobber overwrites existing assets with same name)
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

echo   Release upload complete.
popd
goto show_summary

:: ── Python fallback uploader (no gh CLI) ────────────────────────────
:python_upload
pushd "%SFW_ROOT%"

python -c "
import json, os, sys, urllib.request, urllib.error, glob

TOKEN = None
# Try reading token from git remote URL
try:
    import subprocess
    remote = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip()
    if '@' in remote and 'github.com' in remote:
        TOKEN = remote.split('//')[1].split('@')[0]
except: pass

if not TOKEN:
    print('  No GitHub token found in git remote. Cannot upload.')
    print('  Install gh CLI (https://cli.github.com) or add token to remote URL.')
    sys.exit(1)

REPO = 'laboratoiresonore/spellcaster'
API = 'https://api.github.com'
UPLOAD = 'https://uploads.github.com'
tag = os.environ.get('RELEASE_TAG', '')
if not tag:
    print('  No release tag set.')
    sys.exit(1)

headers = {
    'Authorization': f'token {TOKEN}',
    'Accept': 'application/vnd.github+json',
}

# Get or create release
try:
    req = urllib.request.Request(f'{API}/repos/{REPO}/releases/tags/{tag}', headers=headers)
    with urllib.request.urlopen(req) as r:
        release = json.loads(r.read())
    release_id = release['id']
    upload_url = release['upload_url'].split('{')[0]
    print(f'  Found existing release: {tag} (id={release_id})')
except urllib.error.HTTPError as e:
    if e.code == 404:
        # Create release
        body = json.dumps({'tag_name': tag, 'name': tag, 'body': 'Rebuilt Windows executables.', 'draft': False}).encode()
        req = urllib.request.Request(f'{API}/repos/{REPO}/releases', data=body, headers={**headers, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as r:
            release = json.loads(r.read())
        release_id = release['id']
        upload_url = release['upload_url'].split('{')[0]
        print(f'  Created release: {tag} (id={release_id})')
    else:
        raise

# Delete existing assets with same names, then upload new ones
existing = {}
try:
    req = urllib.request.Request(f'{API}/repos/{REPO}/releases/{release_id}/assets', headers=headers)
    with urllib.request.urlopen(req) as r:
        for a in json.loads(r.read()):
            existing[a['name']] = a['id']
except: pass

dist = os.path.join(os.environ.get('SFW_ROOT', '.'), 'dist')
for exe in ['spellcaster-installer.exe', 'spellcaster-manual-update.exe', 'Wizard_Guild.exe']:
    fpath = os.path.join(dist, exe)
    if not os.path.exists(fpath):
        continue
    # Delete old asset if exists
    if exe in existing:
        try:
            req = urllib.request.Request(f'{API}/repos/{REPO}/releases/assets/{existing[exe]}', headers=headers, method='DELETE')
            urllib.request.urlopen(req)
            print(f'  Deleted old {exe}')
        except: pass
    # Upload
    fsize = os.path.getsize(fpath)
    print(f'  Uploading {exe} ({fsize:,} bytes)...')
    with open(fpath, 'rb') as f:
        data = f.read()
    upload_headers = {**headers, 'Content-Type': 'application/octet-stream'}
    req = urllib.request.Request(f'{upload_url}?name={exe}', data=data, headers=upload_headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            result = json.loads(r.read())
        print(f'  Uploaded {exe} -> {result.get(\"browser_download_url\", \"ok\")}')
    except Exception as ex:
        print(f'  FAILED to upload {exe}: {ex}')

print('  Release upload complete.')
"
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
