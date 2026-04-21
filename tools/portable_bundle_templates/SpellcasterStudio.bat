@echo off
rem Spellcaster Studio — portable bundle launcher.
rem
rem Double-click this file. It:
rem   1. Installs GIMP locally to the bundle on first run
rem   2. Starts the bundled ComfyUI backend in the background
rem   3. Waits for ComfyUI to become ready
rem   4. Launches GIMP pointed at the bundle's plugin + config dirs
rem   5. Stops ComfyUI cleanly when GIMP exits
rem
rem No admin rights required. Writes only to this bundle's data/
rem subdir — truly portable, safe on USB sticks, safe to delete.

setlocal EnableDelayedExpansion

rem Resolve bundle root (this script's dir, minus trailing backslash).
set "BUNDLE=%~dp0"
set "BUNDLE=!BUNDLE:~0,-1!"

rem Bundle-local config — the whole point of being portable.
set "GIMP3_DIRECTORY=!BUNDLE!\data\gimp_config"
set "GIMP3_PLUG_IN_PATH=!BUNDLE!\plugin"
set "SPELLCASTER_BUNDLE=1"
set "SPELLCASTER_BUNDLE_ROOT=!BUNDLE!"
set "SPELLCASTER_COMFY=http://127.0.0.1:8188"

rem Ensure data dirs exist (fresh extract may have empty data/).
if not exist "!BUNDLE!\data\logs" mkdir "!BUNDLE!\data\logs"
if not exist "!BUNDLE!\data\gimp_config" mkdir "!BUNDLE!\data\gimp_config"
if not exist "!BUNDLE!\data\output" mkdir "!BUNDLE!\data\output"

rem First-run: install GIMP into bundle\gimp\ if the binary isn't there.
if not exist "!BUNDLE!\gimp\bin\gimp-3.0.exe" (
    call "!BUNDLE!\SpellcasterStudio-FirstRun.bat"
    if errorlevel 1 (
        echo.
        echo [Spellcaster Studio] First-run setup failed.
        echo See data\logs\launcher.log and data\logs\gimp_install.log
        echo for details, or re-download the bundle.
        pause
        exit /b 1
    )
)

echo.
echo [Spellcaster Studio] Starting ComfyUI backend ...
start "Spellcaster - ComfyUI backend" /D "!BUNDLE!\comfyui" /MIN cmd /c ^
  "python_embedded\python.exe -s ComfyUI\main.py --listen 127.0.0.1 --port 8188 > ..\data\logs\comfyui.log 2>&1"

echo [Spellcaster Studio] Waiting for ComfyUI to become ready ...
set /a TRIES=0
:WAIT
set /a TRIES+=1
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8188/system_stats > "%TEMP%\sc_probe.txt" 2>nul
set /p CODE=<"%TEMP%\sc_probe.txt"
if "!CODE!"=="200" goto READY
if !TRIES! GEQ 30 (
    echo.
    echo [Spellcaster Studio] ComfyUI did not become ready in 60 s.
    echo Check data\logs\comfyui.log for the backend error.
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul
goto WAIT
:READY

echo [Spellcaster Studio] Backend ready. Launching GIMP ...
echo.

rem GIMP runs synchronously; the launcher blocks here until user closes GIMP.
"!BUNDLE!\gimp\bin\gimp-3.0.exe"

echo.
echo [Spellcaster Studio] GIMP closed. Stopping ComfyUI ...
rem Stop the backend window by its title. Falls back to python.exe kill
rem if the title match misses (e.g. user minimised + retitled it).
taskkill /F /FI "WINDOWTITLE eq Spellcaster - ComfyUI backend*" >nul 2>&1
if errorlevel 1 (
    rem Last resort — any python.exe we spawned from bundle's embedded Python.
    for /f "tokens=2 delims=," %%P in ('
        wmic process where ^
        "name='python.exe' and commandline like '%%ComfyUI\\main.py%%'" ^
        get processid /format:csv ^| findstr [0-9]
    ') do (
        taskkill /F /PID %%P >nul 2>&1
    )
)

echo [Spellcaster Studio] Goodbye.
endlocal
exit /b 0
