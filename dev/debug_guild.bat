@echo off
echo ============================================
echo  Wizard Guild Debug Launcher
echo ============================================
echo.
echo Running from: %~dp0
echo.
cd /d "%~dp0"

REM Try running from dist first, then root
if exist "dist\wizard-guild.exe" (
    echo Using: dist\wizard-guild.exe
    echo.
    "dist\wizard-guild.exe" --no-update --no-browser 2>&1
) else if exist "Wizard_Guild.exe" (
    echo Using: Wizard_Guild.exe
    echo.
    "Wizard_Guild.exe" --no-update --no-browser 2>&1
) else (
    echo ERROR: No wizard-guild exe found!
)

echo.
echo ============================================
echo  EXIT CODE: %errorlevel%
echo ============================================
echo.
echo Press any key to close this window...
pause > nul
