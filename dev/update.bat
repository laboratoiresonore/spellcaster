@echo off
title Spellcaster Updater
cd /d "%~dp0"

echo.
echo   ========================================
echo     Spellcaster Manual Update
echo   ========================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Python not found in PATH.
    echo   Please install Python 3.10+ from https://python.org
    echo.
    pause
    exit /b 1
)

python installer\manual_update.py %*
if %errorlevel% neq 0 (
    echo.
    echo   Update encountered an error. See above for details.
    echo.
    pause
)
