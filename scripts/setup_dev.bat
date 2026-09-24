@echo off
REM scripts\setup_dev.bat -- Windows twin of scripts/setup_dev.sh.
REM
REM Wires .githooks/ into this checkout so pre-commit + pre-push run for
REM every commit made from this clone. Safe to re-run.
REM
REM Not for end-users -- those install via install.py / Install.bat.

setlocal

REM Resolve repo root relative to this script so it works from any cwd.
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.." >nul
set "REPO_ROOT=%CD%"

REM Sanity: are we in a git checkout?
git rev-parse --show-toplevel >nul 2>&1
if errorlevel 1 (
    echo [setup_dev] warning: not inside a git checkout -- skipping hook wiring. 1>&2
    popd >nul
    exit /b 0
)

REM Sanity: does .githooks\ exist?
if not exist "%REPO_ROOT%\.githooks" (
    echo [setup_dev] warning: .githooks\ not present -- skipping hook wiring. 1>&2
    popd >nul
    exit /b 0
)

git config --local core.hookspath .githooks
if errorlevel 1 (
    echo [setup_dev] warning: 'git config --local core.hookspath .githooks' failed 1>&2
    echo [setup_dev] you can wire the hooks by hand later: 1>&2
    echo [setup_dev]   git config --local core.hookspath .githooks 1>&2
) else (
    echo [setup_dev] git hooks enabled ^(core.hookspath=.githooks^)
    echo [setup_dev]   pre-commit: credential-leak + mirror-drift + builders-manifest scans
    echo [setup_dev]   pre-push:   credential-leak scan over the pushed range
)

popd >nul
endlocal
