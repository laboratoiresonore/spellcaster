@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Spellcaster Build - All Installers
echo ============================================
echo.

REM --- Build main installer + manual update ---
echo [1/3] Building spellcaster-installer.exe ...
cd installer
python build_installer.py --update-tool
if errorlevel 1 (
    echo FAILED: spellcaster-installer
    exit /b 1
)
cd ..

echo.
echo [2/3] Building Wizard_Guild.exe ...
python -m PyInstaller Wizard_Guild.spec --noconfirm --distpath dist --workpath build
if errorlevel 1 (
    echo FAILED: Wizard_Guild
    exit /b 1
)

echo.
echo [3/3] Copying to NSFW staging ...
copy /Y dist\spellcaster-installer.exe nsfw\staging\spellcaster-installer.exe
copy /Y dist\spellcaster-manual-update.exe nsfw\staging\spellcaster-manual-update.exe
copy /Y dist\Wizard_Guild.exe nsfw\staging\Wizard_Guild.exe

echo.
echo ============================================
echo  All builds complete!
echo ============================================
echo.
echo   dist\spellcaster-installer.exe
echo   dist\spellcaster-manual-update.exe
echo   dist\Wizard_Guild.exe
echo.
pause
