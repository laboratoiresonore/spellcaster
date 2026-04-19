@echo off
REM ==========================================================================
REM Spellcaster Antenna — standalone Windows installer
REM --------------------------------------------------------------------------
REM Download this file from the Spellcaster repo and double-click it to:
REM
REM   1. Make sure Python 3.10+ is available (prompts you to install if not).
REM   2. Clone (or update) the Spellcaster repo into %USERPROFILE%\.spellcaster\
REM      so the antenna can import scaffold/ and spellcaster_core/ from it.
REM   3. Best-effort `pip install` pystray + Pillow so the tray icon works.
REM   4. Launch `python -m antenna`, which on first run asks you whether to
REM      create a desktop icon, a Start Menu entry, and / or run at Windows
REM      login. After that, it runs as a system-tray icon and bridges this
REM      machine's ComfyUI / Kobold / Ollama / Resolve / Darktable / GIMP /
REM      SillyTavern to your Wizard Guild on another box.
REM
REM Everything is re-runnable — if this closes or reboots, double-click again.
REM ==========================================================================

setlocal EnableExtensions EnableDelayedExpansion

title Spellcaster Antenna — installer

echo.
echo   ============================================================
echo   Spellcaster Antenna
echo   ------------------------------------------------------------
echo   Turns this machine into a remote host your Wizard Guild can
echo   reach. Pair it once from the Guild sidebar (+ Pair new) and
echo   the chips appear — ComfyUI / Kobold / Ollama / Resolve / ...
echo   ============================================================
echo.

REM ── 1. Python check ────────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [error] Python 3.10 or newer is required but wasn't found on PATH.
    echo           Install Python from https://www.python.org/downloads/
    echo           and tick "Add python.exe to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [ok]    Python %PYVER%

REM ── 2. Clone / update the Spellcaster repo ─────────────────────────
set REPO_DIR=%USERPROFILE%\.spellcaster\repo
if not exist "%USERPROFILE%\.spellcaster" mkdir "%USERPROFILE%\.spellcaster"

if exist "%REPO_DIR%\antenna" (
    echo   [ok]    Spellcaster repo already cloned — pulling latest
    pushd "%REPO_DIR%"
    git pull --ff-only 2>nul
    popd
) else (
    echo   [...]   Cloning Spellcaster repo into %REPO_DIR%
    where git >nul 2>&1
    if !errorlevel! equ 0 (
        git clone --depth 1 https://github.com/laboratoiresonore/spellcaster.git "%REPO_DIR%"
        if !errorlevel! neq 0 (
            echo   [error] git clone failed. Check your internet connection.
            pause
            exit /b 2
        )
    ) else (
        echo   [error] git is required but wasn't found on PATH.
        echo           Install Git from https://git-scm.com/download/win
        pause
        exit /b 1
    )
)

REM ── 3. Tray dependencies (best-effort) ─────────────────────────────
echo   [...]   Installing tray dependencies (pystray + Pillow)
python -m pip install --quiet --disable-pip-version-check --upgrade pip 2>nul
python -m pip install --quiet --disable-pip-version-check pystray Pillow
if %errorlevel% neq 0 (
    echo   [warn]  pystray install failed — antenna will run in console mode.
    echo           You can still pair it with the Guild; the system-tray icon
    echo           just won't appear.
)

REM ── 4. Launch ─────────────────────────────────────────────────────
echo.
echo   [ok]    Starting the antenna…
echo           (first launch will ask about desktop / Start Menu / startup)
echo.
pushd "%REPO_DIR%"
python -m antenna
popd

endlocal
