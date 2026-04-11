@echo off
title Wizard Guild
cd /d "%~dp0"

REM ── Try compiled exe first, then fall back to Python ──
if exist "dist\wizard-guild.exe" (
    "dist\wizard-guild.exe" %*
    goto :done
)
if exist "dist\Wizard_Guild.exe" (
    "dist\Wizard_Guild.exe" %*
    goto :done
)

REM ── No exe — run from source ──
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   Wizard Guild could not start.
    echo   No compiled exe found in dist\ and Python is not installed.
    echo   Run Install.bat first, or install Python 3.10+ from https://python.org
    echo.
    pause
    exit /b 1
)

python tavern\guild_launcher.py %*

:done
if %errorlevel% neq 0 (
    echo.
    echo   Wizard Guild exited with an error. See above for details.
    echo.
    pause
)
