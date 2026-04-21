@echo off
rem First-run: silent-install GIMP into this bundle's gimp/ dir.
rem
rem Invoked by SpellcasterStudio.bat when gimp\bin\gimp-3.0.exe is
rem missing. Runs the bundled gimp-installer.exe with /VERYSILENT
rem /NORESTART /DIR="<bundle>\gimp". Logs to data\logs\gimp_install.log.
rem
rem Why orchestrate instead of shipping a "truly portable" GIMP tree:
rem GIMP doesn't publish an officially portable build for Windows, and
rem third-party ones (PortableApps.com) lag the upstream by 1-2 weeks.
rem The silent-installer approach lets us track mainline GIMP within
rem hours of release, and the resulting install is still fully bundle-
rem contained because we pass an explicit /DIR to the installer.
rem
rem Clean uninstall: delete the bundle directory. The installer does
rem NOT register itself in Add/Remove Programs when installed to a
rem user-writable /DIR outside %ProgramFiles%, so there's nothing for
rem the user to manually remove.

setlocal EnableDelayedExpansion

set "BUNDLE=%~dp0"
set "BUNDLE=!BUNDLE:~0,-1!"

if exist "!BUNDLE!\gimp\bin\gimp-3.0.exe" (
    echo [FirstRun] GIMP already installed; skipping.
    exit /b 0
)

if not exist "!BUNDLE!\gimp-installer.exe" (
    echo [FirstRun] gimp-installer.exe missing from bundle root.
    echo           Re-download the bundle or run the bundle builder again.
    exit /b 1
)

if not exist "!BUNDLE!\data\logs" mkdir "!BUNDLE!\data\logs"

echo.
echo =====================================================================
echo   Spellcaster Studio - First-Time Setup
echo =====================================================================
echo.
echo   Installing GIMP 3.x locally to this bundle (~300 MB, 1-3 minutes).
echo.
echo   No admin rights needed. No changes outside this bundle's folder.
echo   Safe to run on a USB stick, flash drive, or any user-writable path.
echo.

"!BUNDLE!\gimp-installer.exe" /VERYSILENT /NORESTART /CURRENTUSER ^
    /DIR="!BUNDLE!\gimp" ^
    /LOG="!BUNDLE!\data\logs\gimp_install.log"

if errorlevel 1 (
    echo.
    echo [FirstRun] GIMP installer returned non-zero exit code.
    echo           See data\logs\gimp_install.log.
    exit /b 1
)

if not exist "!BUNDLE!\gimp\bin\gimp-3.0.exe" (
    echo.
    echo [FirstRun] Installer reported success but gimp-3.0.exe is missing.
    echo           Check data\logs\gimp_install.log.
    exit /b 1
)

echo.
echo [FirstRun] GIMP installed successfully at:
echo              !BUNDLE!\gimp\bin\gimp-3.0.exe
echo.

rem Remove the installer — no longer needed; the install is self-contained.
del /F /Q "!BUNDLE!\gimp-installer.exe" >nul 2>&1

echo [FirstRun] Done. The launcher will now start Spellcaster Studio.
echo.
endlocal
exit /b 0
