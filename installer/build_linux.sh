#!/bin/bash
# ─── Spellcaster Linux Build Script ─────────────────────────────────────
# Run this on a Linux machine with Python 3.10+ and tkinter.
#
# Output:
#   dist/spellcaster-installer       (single-file binary)
#   dist/spellcaster-manual-update   (updater tool)
#   dist/spellcaster-installer.desktop (optional desktop launcher)
#
# Usage:
#   chmod +x build_linux.sh && ./build_linux.sh
#
# Prerequisites (Debian/Ubuntu):
#   sudo apt install python3-tk python3-pip python3-venv git
#
# Prerequisites (Fedora):
#   sudo dnf install python3-tkinter python3-pip git
#
# Prerequisites (Arch):
#   sudo pacman -S tk python-pip git
# ────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo "  SPELLCASTER Linux BUILD"
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
    echo "ERROR: python3 (3.10+) not found. Install via your package manager."
    exit 1
fi

echo "Python: $($PYTHON --version)"

# Verify minimum version
$PYTHON -c "import sys; assert sys.version_info >= (3, 10), f'Python 3.10+ required, got {sys.version}'" || {
    echo "ERROR: Python 3.10+ is required."
    exit 1
}

# Check tkinter
$PYTHON -c "import tkinter" 2>/dev/null || {
    echo "ERROR: python3-tkinter not installed."
    echo "  Debian/Ubuntu: sudo apt install python3-tk"
    echo "  Fedora:        sudo dnf install python3-tkinter"
    echo "  Arch:          sudo pacman -S tk"
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

# ── Build 1: Installer binary ────────────────────────────────────────
echo ""
echo "Building Linux installer..."
python build_installer.py --platform linux --update-tool

# ── Create .desktop launcher ─────────────────────────────────────────
echo ""
echo "Creating desktop launcher..."
DESKTOP_FILE="dist/spellcaster-installer.desktop"
cat > "$DESKTOP_FILE" << 'DESKTOP_EOF'
[Desktop Entry]
Type=Application
Name=Spellcaster Installer
Comment=AI superpowers for GIMP 3 & Darktable
Exec=spellcaster-installer
Icon=spellcaster
Terminal=false
Categories=Graphics;Photography;
Keywords=AI;GIMP;Darktable;ComfyUI;StableDiffusion;
DESKTOP_EOF
echo "  Created: $DESKTOP_FILE"

# ── Make binaries executable ──────────────────────────────────────────
chmod +x dist/spellcaster-installer 2>/dev/null || true
chmod +x dist/spellcaster-manual-update 2>/dev/null || true

# ── Clean up venv ─────────────────────────────────────────────────────
deactivate 2>/dev/null || true
echo ""
echo "TIP: Remove .build-venv/ when no longer needed:"
echo "  rm -rf $VENV_DIR"

# ── Optional: Create AppImage ─────────────────────────────────────────
echo ""
echo "TIP: To create an AppImage for wider distribution:"
echo "  1. Install appimagetool: https://appimage.github.io/appimagetool/"
echo "  2. Create AppDir structure with the binary"
echo "  3. Run: appimagetool AppDir/ Spellcaster-Installer.AppImage"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Linux BUILD COMPLETE"
echo ""
echo "  Installer: dist/spellcaster-installer"
echo "  Updater:   dist/spellcaster-manual-update"
echo "  Launcher:  dist/spellcaster-installer.desktop"
echo ""
echo "  Supports: GIMP 3.0, 3.2+ | Darktable 5.x"
echo ""
echo "  Install system-wide:"
echo "    sudo cp dist/spellcaster-installer /usr/local/bin/"
echo "    sudo cp dist/spellcaster-manual-update /usr/local/bin/"
echo "    sudo cp $DESKTOP_FILE /usr/share/applications/"
echo "═══════════════════════════════════════════════════"
