#!/bin/bash
# ─── Wizard Guild macOS Build Script ──────────────────────────────────
# Builds a standalone macOS application for The Wizard Guild.
#
# Output:
#   dist/Wizard Guild.app              (drag-and-drop .app bundle)
#   dist/wizard-guild                  (single-file Mach-O binary)
#
# Usage:
#   chmod +x build_guild_macos.sh && ./build_guild_macos.sh
#
# Prerequisites:
#   - macOS 12+ with Python 3.10+
#   - Homebrew: brew install python@3.12  (if system Python is too old)
#   - Optional: brew install create-dmg   (for distributable DMG)
# ────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo "  THE WIZARD GUILD — macOS Build"
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
    echo "ERROR: python3 (3.10+) not found."
    echo "  Install via: brew install python@3.12"
    exit 1
fi

echo "Python: $($PYTHON --version)"

$PYTHON -c "import sys; assert sys.version_info >= (3, 10), f'Python 3.10+ required, got {sys.version}'" || {
    echo "ERROR: Python 3.10+ is required."
    exit 1
}

# ── Create isolated venv ─────────────────────────────────────────────
echo ""
echo "Creating build virtual environment..."
VENV_DIR="$SCRIPT_DIR/.build-venv"
$PYTHON -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
echo "  venv: $VENV_DIR"

echo ""
echo "Installing PyInstaller..."
pip install --upgrade pip > /dev/null
pip install pyinstaller > /dev/null

# ── Build 1: .app bundle (for drag-and-drop distribution) ────────────
echo ""
echo "Building macOS .app bundle..."
python build_guild.py --platform macos --onedir

# ── Build 2: Single-file binary (for CLI distribution) ───────────────
echo ""
echo "Building macOS single-file binary..."
python build_guild.py --platform macos

# ── Optional: Create DMG ─────────────────────────────────────────────
if command -v create-dmg &> /dev/null; then
    echo ""
    echo "Creating distributable DMG..."
    create-dmg \
        --volname "Wizard Guild" \
        --volicon "../assets/spellcaster.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --app-drop-link 425 178 \
        "../dist/Wizard-Guild.dmg" \
        "../dist/Wizard Guild.app"
    echo "  DMG created: dist/Wizard-Guild.dmg"
else
    echo ""
    echo "TIP: Install create-dmg for a distributable .dmg:"
    echo "  brew install create-dmg"
    echo '  create-dmg "../dist/Wizard Guild.app" ../dist/'
fi

# ── Clean up ─────────────────────────────────────────────────────────
deactivate 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════════"
echo "  macOS BUILD COMPLETE"
echo ""
echo "  App bundle: dist/Wizard Guild.app"
echo "  Binary:     dist/wizard-guild"
echo ""
echo "  Run: open 'dist/Wizard Guild.app'"
echo "  Run: ./dist/wizard-guild --comfyui http://mypc:8188"
echo ""
echo "  Cleanup: rm -rf $VENV_DIR"
echo "═══════════════════════════════════════════════════"
