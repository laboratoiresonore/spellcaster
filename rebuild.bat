@echo off

REM ============================================================================
REM  Spellcaster - Full Rebuild, Test and Push
REM  Builds all SFW + NSFW executables, copies to root/nsfw, pushes both repos
REM ============================================================================

echo.
echo  ===================================================
echo     Spellcaster Full Rebuild
echo  ===================================================
echo.

REM -- 0. Clean git locks --

echo [0/8] Cleaning stale git locks...
if exist ".git\index.lock"              del /f ".git\index.lock"
if exist ".git\HEAD.lock"               del /f ".git\HEAD.lock"
if exist ".git\objects\maintenance.lock" del /f ".git\objects\maintenance.lock"
echo       Done.

REM -- 1. Clean old dist/ executables --

echo [1/8] Cleaning dist/, nsfw/dist/, and build cache...
if exist "dist\spellcaster-installer.exe"           del /f "dist\spellcaster-installer.exe"
if exist "dist\spellcaster-manual-update.exe"        del /f "dist\spellcaster-manual-update.exe"
if exist "dist\wizard-guild.exe"                     del /f "dist\wizard-guild.exe"
if exist "dist\Wizard_Guild.exe"                     del /f "dist\Wizard_Guild.exe"
if exist "nsfw\dist\spellcaster-nsfw-installer.exe"  del /f "nsfw\dist\spellcaster-nsfw-installer.exe"
if exist "nsfw\dist\spellcaster-nsfw-updater.exe"    del /f "nsfw\dist\spellcaster-nsfw-updater.exe"
if exist "nsfw\dist\Wizard_Guild_NSFW.exe"           del /f "nsfw\dist\Wizard_Guild_NSFW.exe"
if exist "build\wizard-guild" rmdir /s /q "build\wizard-guild"
if exist "nsfw\staging" (
    attrib -r -h -s "nsfw\staging\*.*" /s /d >nul 2>&1
    rmdir /s /q "nsfw\staging" >nul 2>&1
)
if exist "nsfw\staging" (
    echo       WARNING: staging locked, retrying in 2s...
    timeout /t 2 /nobreak >nul
    rmdir /s /q "nsfw\staging" >nul 2>&1
)
echo       Done.

REM -- 2. Build SFW Installer + Updater --

echo.
echo [2/8] Building SFW installer + updater...
cd installer
python build_installer.py --platform windows --update-tool
if %errorlevel% neq 0 (
    echo       SFW installer BUILD FAILED.
    cd ..
    pause
    exit /b 1
)
cd ..
echo       SFW installer + updater built.

REM -- 3. Build SFW Wizard Guild --

echo.
echo [3/8] Building SFW Wizard Guild...
cd tavern
python build_guild.py --platform windows
if %errorlevel% neq 0 (
    echo       SFW Wizard Guild BUILD FAILED.
    cd ..
    pause
    exit /b 1
)
cd ..
echo       SFW Wizard Guild built.

REM -- 4. Copy SFW exes to root --

echo.
echo [4/8] Copying SFW executables to root...
if exist "dist\spellcaster-installer.exe"     copy /y "dist\spellcaster-installer.exe"     "spellcaster-installer.exe"     >nul
if exist "dist\spellcaster-manual-update.exe"  copy /y "dist\spellcaster-manual-update.exe"  "spellcaster-manual-update.exe"  >nul
if exist "dist\wizard-guild.exe"              copy /y "dist\wizard-guild.exe"              "Wizard_Guild.exe"              >nul
echo       spellcaster-installer.exe
echo       spellcaster-manual-update.exe
echo       Wizard_Guild.exe

REM -- 5. Build NSFW (stage + patch + exe, but NOT push yet) --

echo.
echo [5/8] Building NSFW edition (stage, patch, compile)...
python nsfw/build_nsfw.py --patch-only
if %errorlevel% neq 0 (
    echo       NSFW patch FAILED.
    pause
    exit /b 1
)
python nsfw/build_nsfw.py --build-exe
if %errorlevel% neq 0 (
    echo       NSFW exe build FAILED.
    pause
    exit /b 1
)
echo       NSFW installer + updater + Wizard Guild built.

REM -- 6. Test --

echo.
echo [6/8] Launching SFW installer for testing...
echo       Close the window when done, then press any key.
start "" "spellcaster-installer.exe"
pause

echo       Launching NSFW installer for testing...
echo       Close the window when done, then press any key.
if exist "nsfw\dist\spellcaster-nsfw-installer.exe" (
    start "" "nsfw\dist\spellcaster-nsfw-installer.exe"
    pause
)

REM -- 7. Push SFW repo --
REM  Root .exe files are gitignored (local release copies only).
REM  Only push source changes.

echo.
echo [7/8] Pushing SFW repo to origin...
if exist ".git\index.lock" del /f ".git\index.lock"
if exist ".git\index.lock" (
    echo       ERROR: Cannot remove .git\index.lock - close any git GUIs and retry.
    pause
    exit /b 1
)
git rm --cached tavern\.guild_state\generated_assets.json tavern\.guild_state\wizard_identities.json tavern\.guild_state\lora_registry.json tavern\.guild_version 2>nul
git add -A
if %errorlevel% neq 0 (
    echo       git add FAILED - check for lock files or disk errors.
    pause
    exit /b 1
)
git diff --cached --stat
git status --short
git diff --cached --quiet
if %errorlevel% equ 0 goto sfw_skip
git commit -m "build: rebuild all executables"
if %errorlevel% neq 0 (
    echo       SFW commit FAILED.
    pause
    exit /b 1
)
git push origin main
if %errorlevel% neq 0 (
    echo       SFW push FAILED - check above for errors.
    pause
    exit /b 1
)
echo       SFW pushed.
goto sfw_done
:sfw_skip
echo       Nothing to commit - working tree matches HEAD.
echo       Skipping SFW push.
:sfw_done

REM -- 8. Push NSFW repo --
REM  build_nsfw.py --push clones the private repo, copies staging, and pushes.

echo.
echo [8/8] Pushing NSFW repo...
python nsfw/build_nsfw.py --push
if %errorlevel% neq 0 (
    echo       NSFW push FAILED.
    pause
    exit /b 1
)
echo       NSFW pushed.

REM -- Done --

echo.
echo  ===================================================
echo     All builds complete, all repos pushed.
echo  ===================================================
echo.
echo   SFW:
echo     spellcaster-installer.exe
echo     spellcaster-manual-update.exe
echo     Wizard_Guild.exe
echo.
echo   NSFW:
echo     nsfw/dist/spellcaster-nsfw-installer.exe
echo     nsfw/dist/spellcaster-nsfw-updater.exe
echo     nsfw/dist/Wizard_Guild_NSFW.exe
echo.
pause
