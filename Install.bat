@echo off
title Spellcaster Installer
cd /d "%~dp0"

echo.
echo   ========================================
echo     Spellcaster Installer
echo   ========================================
echo.

REM Check for Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Python not found in PATH.
    echo   Please install Python 3.10+ from https://python.org
    echo   Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

python installer\install.py %*
if %errorlevel% neq 0 (
    echo.
    echo   Installation encountered an error. See above for details.
    echo.
    pause
)
