@echo off
setlocal enabledelayedexpansion
title Wizard Guild — Settings
cd /d "%~dp0"

set "CONFIG=guild_config.json"
set "CONFIG2=tavern\guild_config.json"

REM ══════════════════════════════════════════════════════════
REM  Parse current config
REM ══════════════════════════════════════════════════════════
call :load_config

:menu
cls
echo.
echo   ============================================
echo        WIZARD GUILD — SETTINGS
echo   ============================================
echo.
echo   Current configuration:
echo   ──────────────────────────────────────────
echo     1. Guild Port         :  %CFG_PORT%
echo     2. ComfyUI URL        :  %CFG_COMFYUI%
echo     3. LLM / Kobold URL   :  %CFG_KOBOLD%
echo     4. SillyTavern Dir    :  %CFG_ST_DIR%
echo     5. KoboldCPP Dir      :  %CFG_KCPP_DIR%
echo     6. Kobold Model       :  %CFG_KMODEL%
echo     7. Auto-open browser  :  %CFG_BROWSER%
echo     8. Auto-update        :  %CFG_UPDATE%
echo     9. Auto-launch ST     :  %CFG_LAUNCH_ST%
echo    10. Auto-launch Kobold :  %CFG_LAUNCH_K%
echo    11. Privacy cleanup    :  %CFG_PRIVACY%
echo    12. LLM Mode          :  %CFG_LLM_MODE%
echo    13. Horde API Key      :  %CFG_HORDE_KEY%
echo    14. Horde Model        :  %CFG_HORDE_MODEL%
echo   ──────────────────────────────────────────
echo     S. Save and exit
echo     Q. Quit without saving
echo     R. Re-run full setup wizard
echo.
set /p "CHOICE=  Enter number to change (or S/Q/R): "

if /i "%CHOICE%"=="S" goto save_exit
if /i "%CHOICE%"=="Q" goto quit
if /i "%CHOICE%"=="R" goto run_wizard
if "%CHOICE%"=="1" goto edit_port
if "%CHOICE%"=="2" goto edit_comfyui
if "%CHOICE%"=="3" goto edit_kobold
if "%CHOICE%"=="4" goto edit_stdir
if "%CHOICE%"=="5" goto edit_kcppdir
if "%CHOICE%"=="6" goto edit_kmodel
if "%CHOICE%"=="7" goto toggle_browser
if "%CHOICE%"=="8" goto toggle_update
if "%CHOICE%"=="9" goto toggle_launch_st
if "%CHOICE%"=="10" goto toggle_launch_k
if "%CHOICE%"=="11" goto toggle_privacy
if "%CHOICE%"=="12" goto toggle_llm_mode
if "%CHOICE%"=="13" goto edit_horde_key
if "%CHOICE%"=="14" goto edit_horde_model
goto menu

REM ══════════════════════════════════════════════════════════
REM  Editors
REM ══════════════════════════════════════════════════════════

:edit_port
echo.
set /p "NEW=  Guild port [%CFG_PORT%]: "
if not "%NEW%"=="" set "CFG_PORT=%NEW%"
goto menu

:edit_comfyui
echo.
echo   Enter the full URL including port, e.g. http://192.168.1.50:8188
set /p "NEW=  ComfyUI URL [%CFG_COMFYUI%]: "
if not "%NEW%"=="" set "CFG_COMFYUI=%NEW%"
goto menu

:edit_kobold
echo.
echo   KoboldAI-compatible API URL, e.g. http://127.0.0.1:5001
set /p "NEW=  LLM URL [%CFG_KOBOLD%]: "
if not "%NEW%"=="" set "CFG_KOBOLD=%NEW%"
goto menu

:edit_stdir
echo.
echo   Full path to your SillyTavern installation folder.
echo   Leave blank to clear.
set /p "NEW=  SillyTavern dir [%CFG_ST_DIR%]: "
if not "%NEW%"=="" set "CFG_ST_DIR=%NEW%"
goto menu

:edit_kcppdir
echo.
echo   Full path to your KoboldCPP directory.
echo   Leave blank to clear.
set /p "NEW=  KoboldCPP dir [%CFG_KCPP_DIR%]: "
if not "%NEW%"=="" set "CFG_KCPP_DIR=%NEW%"
goto menu

:edit_kmodel
echo.
echo   Full path to the GGUF model file for KoboldCPP.
echo   Leave blank to clear.
set /p "NEW=  Model path [%CFG_KMODEL%]: "
if not "%NEW%"=="" set "CFG_KMODEL=%NEW%"
goto menu

:toggle_browser
if /i "%CFG_BROWSER%"=="true" (set "CFG_BROWSER=false") else (set "CFG_BROWSER=true")
goto menu

:toggle_update
if /i "%CFG_UPDATE%"=="true" (set "CFG_UPDATE=false") else (set "CFG_UPDATE=true")
goto menu

:toggle_launch_st
if /i "%CFG_LAUNCH_ST%"=="true" (set "CFG_LAUNCH_ST=false") else (set "CFG_LAUNCH_ST=true")
goto menu

:toggle_launch_k
if /i "%CFG_LAUNCH_K%"=="true" (set "CFG_LAUNCH_K=false") else (set "CFG_LAUNCH_K=true")
goto menu

:toggle_privacy
if /i "%CFG_PRIVACY%"=="true" (set "CFG_PRIVACY=false") else (set "CFG_PRIVACY=true"
set "CFG_LLM_MODE=local"
set "CFG_HORDE_KEY="
set "CFG_HORDE_MODEL=")
goto menu

:toggle_llm_mode
if /i "%CFG_LLM_MODE%"=="horde" (
    set "CFG_LLM_MODE=local"
    echo.
    echo   Switched to LOCAL mode (KoboldAI).
) else (
    echo.
    echo   ╔══════════════════════════════════════════════════════╗
    echo   ║         ⚠ ZERO PRIVACY WARNING ⚠                  ║
    echo   ║                                                      ║
    echo   ║  AI Horde is a CROWDSOURCED volunteer network.       ║
    echo   ║  Every prompt you send is processed by RANDOM        ║
    echo   ║  STRANGERS' MACHINES.  Your conversations, character ║
    echo   ║  names, and all text are FULLY VISIBLE to workers.   ║
    echo   ║                                                      ║
    echo   ║  NEVER send sensitive or private info through Horde. ║
    echo   ╚══════════════════════════════════════════════════════╝
    echo.
    set /p "CONFIRM=  Type YES to enable Horde mode: "
    if /i "!CONFIRM!"=="YES" (
        set "CFG_LLM_MODE=horde"
        echo   Horde mode ENABLED.
    ) else (
        echo   Cancelled — staying in local mode.
    )
)
goto menu

:edit_horde_key
echo.
echo   Your AI Horde API key. Leave blank for anonymous (slower, lower priority).
echo   Get a key at https://aihorde.net/register
set /p "NEW=  Horde API Key [%CFG_HORDE_KEY%]: "
if not "%NEW%"=="" set "CFG_HORDE_KEY=%NEW%"
goto menu

:edit_horde_model
echo.
echo   Preferred Horde model name. Leave blank for any available model.
set /p "NEW=  Horde Model [%CFG_HORDE_MODEL%]: "
if not "%NEW%"=="" set "CFG_HORDE_MODEL=%NEW%"
goto menu

REM ══════════════════════════════════════════════════════════
REM  Save
REM ══════════════════════════════════════════════════════════

:save_exit
echo.
echo   Saving settings...

(
echo {
echo   "guild_port": %CFG_PORT%,
echo   "comfyui_url": "%CFG_COMFYUI%",
echo   "kobold_url": "%CFG_KOBOLD%",
echo   "sillytavern_dir": "%CFG_ST_DIR%",
echo   "koboldcpp_dir": "%CFG_KCPP_DIR%",
echo   "kobold_model": "%CFG_KMODEL%",
echo   "auto_open_browser": %CFG_BROWSER%,
echo   "auto_update": %CFG_UPDATE%,
echo   "auto_launch_st": %CFG_LAUNCH_ST%,
echo   "auto_launch_kobold": %CFG_LAUNCH_K%,
echo   "privacy_cleanup": %CFG_PRIVACY%,
echo   "llm_mode": "%CFG_LLM_MODE%",
echo   "horde_api_key": "%CFG_HORDE_KEY%",
echo   "horde_model": "%CFG_HORDE_MODEL%"
echo }
) > "%CONFIG%"

REM Keep tavern copy in sync (source-mode fallback)
if exist "%CONFIG2%" copy /y "%CONFIG%" "%CONFIG2%" >nul 2>&1

echo   Done! Restart the Guild for changes to take effect.
echo.
pause
exit /b 0

:quit
echo.
echo   No changes saved.
pause
exit /b 0

:run_wizard
echo.
echo   Launching the full setup wizard...
echo.
cd tavern
python guild_launcher.py --setup
cd ..
REM Reload config after wizard finishes
call :load_config
goto menu

REM ══════════════════════════════════════════════════════════
REM  Config loader — parse JSON with findstr
REM ══════════════════════════════════════════════════════════

:load_config
REM Defaults
set "CFG_PORT=7777"
set "CFG_COMFYUI=http://127.0.0.1:8188"
set "CFG_KOBOLD=http://127.0.0.1:5001"
set "CFG_ST_DIR="
set "CFG_KCPP_DIR="
set "CFG_KMODEL="
set "CFG_BROWSER=true"
set "CFG_UPDATE=true"
set "CFG_LAUNCH_ST=true"
set "CFG_LAUNCH_K=false"
set "CFG_PRIVACY=true"

if not exist "%CONFIG%" (
    echo   [!] No config file found at %CONFIG%
    echo       Using defaults. Run the setup wizard ^(R^) to create one.
    goto :eof
)

REM Parse each key from the JSON
for /f "usebackq tokens=1,* delims=:" %%A in ("%CONFIG%") do (
    set "KEY=%%A"
    set "VAL=%%B"
    REM Strip quotes and whitespace from key
    set "KEY=!KEY:"=!"
    set "KEY=!KEY: =!"
    REM Strip leading space, trailing comma, and quotes from value
    if defined VAL (
        set "VAL=!VAL:~1!"
        set "VAL=!VAL:,=!"
        set "VAL=!VAL:"=!"
        REM Trim trailing spaces
        for /f "tokens=*" %%V in ("!VAL!") do set "VAL=%%V"
    )
    if "!KEY!"=="guild_port"        set "CFG_PORT=!VAL!"
    if "!KEY!"=="comfyui_url"       set "CFG_COMFYUI=!VAL!"
    if "!KEY!"=="kobold_url"        set "CFG_KOBOLD=!VAL!"
    if "!KEY!"=="sillytavern_dir"   set "CFG_ST_DIR=!VAL!"
    if "!KEY!"=="koboldcpp_dir"     set "CFG_KCPP_DIR=!VAL!"
    if "!KEY!"=="kobold_model"      set "CFG_KMODEL=!VAL!"
    if "!KEY!"=="auto_open_browser" set "CFG_BROWSER=!VAL!"
    if "!KEY!"=="auto_update"       set "CFG_UPDATE=!VAL!"
    if "!KEY!"=="auto_launch_st"    set "CFG_LAUNCH_ST=!VAL!"
    if "!KEY!"=="auto_launch_kobold" set "CFG_LAUNCH_K=!VAL!"
    if "!KEY!"=="privacy_cleanup"   set "CFG_PRIVACY=!VAL!"
    if "!KEY!"=="llm_mode"          set "CFG_LLM_MODE=!VAL!"
    if "!KEY!"=="horde_api_key"     set "CFG_HORDE_KEY=!VAL!"
    if "!KEY!"=="horde_model"       set "CFG_HORDE_MODEL=!VAL!"
)
goto :eof
