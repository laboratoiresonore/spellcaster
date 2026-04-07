#!/bin/bash
# ─── Spellcaster macOS Build Script ─────────────────────────────────────
# Run this on a macOS machine with Python 3.10+ and Homebrew.
#
# Output:
#   dist/Spellcaster Installer.app   (drag-and-drop installer)
#   dist/spellcaster-installer       (single-file binary)
#   dist/spellcaster-manual-update   (updater tool)
#
# Usage:
#   chmod +x build_macos.sh && ./build_macos.sh
# ────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo "  SPELLCASTER macOS BUILD"
echo "═══════════════════════════════════════════════════"

# Check Python (3.10+)
PYTHON=""
for py in python3.12 python3.11 python3.10 python3; do
    if command -v "$py" &> /dev/null; then
        PYTHON="$py"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "ERROR: python3 (3.10+) not found. Install via: brew install python@3.12"
    exit 1
fi

echo "Python: $($PYTHON --version)"

# Verify minimum version
$PYTHON -c "import sys; assert sys.version_info >= (3, 10), f'Python 3.10+ required, got {sys.version}'" || {
    echo "ERROR: Python 3.10+ is required."
    exit 1
}

# ── Create isolated venv for build ───────────────────────────────────
echo ""
echo "Creating build virtual environment..."
VENV_DIR="$SCRIPT_DIR/.build-venv"
$PYTHON -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
echo "  venv: $VENV_DIR"

# Install dependencies into venv
echo ""
echo "Installing build dependencies..."
pip install --upgrade pip
pip install pyinstaller customtkinter pillow requests darkdetect

# ── Build 1: .app bundle (onedir + windowed) ───────────────────────────
echo ""
echo "Building macOS .app bundle..."
python build_installer.py --platform macos --onedir

# ── Build 2: Single-file binary (for curl distribution) ───────────────
echo ""
echo "Building macOS single-file binary..."
python build_installer.py --platform macos --update-tool

# ── Optional: Create DMG ──────────────────────────────────────────────
if command -v create-dmg &> /dev/null; then
    echo ""
    echo "Creating distributable DMG..."
    create-dmg \
        --volname "Spellcaster Installer" \
        --volicon "assets/spellcaster.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --app-drop-link 425 178 \
        "dist/Spellcaster-Installer.dmg" \
        "dist/Spellcaster Installer.app"
    echo "DMG created: dist/Spellcaster-Installer.dmg"
else
    echo ""
    echo "TIP: Install create-dmg for a drag-and-drop .dmg:"
    echo "  brew install create-dmg"
    echo "  create-dmg 'dist/Spellcaster Installer.app' dist/"
fi

# ── Clean up venv ─────────────────────────────────────────────────────
deactivate 2>/dev/null || true
echo ""
echo "TIP: Remove .build-venv/ when no longer needed:"
echo "  rm -rf $VENV_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  macOS BUILD COMPLETE"
echo ""
echo "  App bundle:  dist/Spellcaster Installer.app"
echo "  Binary:      dist/spellcaster-installer"
echo "  Updater:     dist/spellcaster-manual-update"
echo ""
echo "  Supports: GIMP 3.0, 3.2+ | Darktable 5.x"
echo "═══════════════════════════════════════════════════"
