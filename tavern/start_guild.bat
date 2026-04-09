@echo off
title Wizard Guild Server
cd /d "%~dp0"
echo.
echo   ==========================================
echo   The Wizard Guild - Launcher
echo   ==========================================
echo.

REM ── Check for Python ──
where python >nul 2>&1
if errorlevel 1 (
    echo   [!] Python not found. Please install Python 3.10+
    echo       from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ── Launch via guild_launcher.py (handles config, SillyTavern, etc.) ──
REM    First run will trigger the interactive setup wizard.
REM    Use --setup to reconfigure later.
REM    All settings are saved in guild_config.json.
echo   Starting via guild_launcher.py...
echo   (First run will show the setup wizard)
echo.
python guild_launcher.py %*
pause
