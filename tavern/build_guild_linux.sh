#!/bin/bash
# ─── Wizard Guild Linux Build Script ──────────────────────────────────
# Builds a standalone Linux binary for The Wizard Guild.
#
# Output:
#   dist/wizard-guild                   (single-file ELF binary)
#   dist/wizard-guild.desktop           (freedesktop launcher)
#
# Usage:
#   chmod +x build_guild_linux.sh && ./build_guild_linux.sh
#
# Prerequisites (Debian/Ubuntu):
#   sudo apt install python3-pip python3-venv
#
# Prerequisites (Fedora):
#   sudo dnf install python3-pip
#
# Prerequisites (Arch):
#   sudo pacman -S python-pip
# ────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo "  THE WIZARD GUILD — Linux Build"
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

# Install build dependency (only pyinstaller needed — no runtime deps)
echo ""
echo "Installing PyInstaller..."
pip install --upgrade pip > /dev/null
pip install pyinstaller > /dev/null

# ── Build ─────────────────────────────────────────────────────────────
echo ""
echo "Building Wizard Guild..."
python build_guild.py --platform linux

# ── Create .desktop launcher ─────────────────────────────────────────
echo ""
echo "Creating desktop launcher..."
DESKTOP_FILE="../dist/wizard-guild.desktop"
cat > "$DESKTOP_FILE" << 'DESKTOP_EOF'
[Desktop Entry]
Type=Application
Name=Wizard Guild
Comment=Spellcaster's standalone ComfyUI interface
Exec=wizard-guild
Icon=spellcaster
Terminal=false
Categories=Graphics;Photography;
Keywords=AI;ComfyUI;StableDiffusion;Flux;Image;Generation;
DESKTOP_EOF

chmod +x ../dist/wizard-guild 2>/dev/null || true
echo "  Created: $DESKTOP_FILE"

# ── Clean up ─────────────────────────────────────────────────────────
deactivate 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Linux BUILD COMPLETE"
echo ""
echo "  Binary:    dist/wizard-guild"
echo "  Launcher:  dist/wizard-guild.desktop"
echo ""
echo "  Run:       ./dist/wizard-guild"
echo "  Run:       ./dist/wizard-guild --comfyui http://mypc:8188"
echo ""
echo "  Install system-wide:"
echo "    sudo cp dist/wizard-guild /usr/local/bin/"
echo "    sudo cp dist/wizard-guild.desktop /usr/share/applications/"
echo ""
echo "  Cleanup: rm -rf $VENV_DIR"
echo "═══════════════════════════════════════════════════"
