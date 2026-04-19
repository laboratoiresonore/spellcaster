#!/usr/bin/env bash
# ==========================================================================
# Spellcaster Antenna — standalone installer for macOS + GNU/Linux
# --------------------------------------------------------------------------
# Download this file, make it executable (`chmod +x install_antenna.sh`) and
# run it. It will:
#
#   1. Verify python3 (>= 3.10) and git are present; print install hints if
#      they're not.
#   2. Clone (or pull) the Spellcaster repo into ~/.spellcaster/repo so the
#      antenna can import scaffold/ and spellcaster_core/ from it.
#   3. Best-effort `pip install` pystray + Pillow so the system-tray icon
#      works when running under a graphical session. Headless servers fall
#      back to console mode.
#   4. Launch `python3 -m antenna`.
#
# On macOS the tray works out of the box through pyobjc (installed here).
# On GNU/Linux the tray needs AppIndicator (`gir1.2-appindicator3-0.1` on
# Debian/Ubuntu, `libappindicator-gtk3` on Fedora); the script skips that
# install and just runs in console mode if the extension is missing.
# ==========================================================================
set -eu

OS="$(uname -s)"
REPO_URL="https://github.com/laboratoiresonore/spellcaster.git"
INSTALL_DIR="${HOME}/.spellcaster/repo"

say() { printf '  %s\n' "$*"; }
fail() { printf '  [error] %s\n' "$*" >&2; exit 1; }

say ""
say "============================================================"
say "Spellcaster Antenna"
say "------------------------------------------------------------"
say "Turns this machine into a remote host your Wizard Guild can"
say "reach. Pair it once from the Guild sidebar (+ Pair new) and"
say "the chips appear — ComfyUI / Kobold / Ollama / Resolve / ..."
say "============================================================"
say ""

# ── 1. Python + git check ─────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || fail "Python 3.10+ required.
    macOS:  brew install python
    Debian: sudo apt install python3 python3-pip python3-venv
    Fedora: sudo dnf install python3 python3-pip"

PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
say "[ok]    Python ${PY_VER}"

command -v git >/dev/null 2>&1 || fail "git required.
    macOS:  brew install git (or install Xcode Command Line Tools)
    Debian: sudo apt install git
    Fedora: sudo dnf install git"

# ── 2. Clone or update the Spellcaster repo ──────────────────────────
mkdir -p "${HOME}/.spellcaster"
if [ -d "${INSTALL_DIR}/antenna" ]; then
    say "[ok]    Spellcaster repo already cloned — pulling latest"
    (cd "${INSTALL_DIR}" && git pull --ff-only 2>/dev/null || true)
else
    say "[...]   Cloning Spellcaster repo into ${INSTALL_DIR}"
    git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}" \
        || fail "git clone failed — check your internet connection."
fi

# ── 3. Dependencies (best-effort; tray is optional) ──────────────────
say "[...]   Installing tray dependencies (pystray + Pillow)"
python3 -m pip install --user --quiet --disable-pip-version-check --upgrade pip 2>/dev/null || true

case "${OS}" in
    Darwin)
        python3 -m pip install --user --quiet --disable-pip-version-check \
            pystray Pillow pyobjc-core pyobjc-framework-Cocoa 2>/dev/null \
            || say "[warn]  tray deps failed — antenna will run in console mode."
        ;;
    Linux)
        python3 -m pip install --user --quiet --disable-pip-version-check \
            pystray Pillow 2>/dev/null \
            || say "[warn]  tray deps failed — antenna will run in console mode."
        if ! python3 -c "import gi; gi.require_version('AppIndicator3', '0.1')" 2>/dev/null; then
            say "[warn]  AppIndicator3 not installed — system-tray icon may not appear."
            say "        Debian/Ubuntu: sudo apt install gir1.2-appindicator3-0.1"
            say "        Fedora:        sudo dnf install libappindicator-gtk3"
        fi
        ;;
    *)
        say "[warn]  Unknown OS: ${OS} — best-effort install only."
        python3 -m pip install --user --quiet --disable-pip-version-check \
            pystray Pillow 2>/dev/null || true
        ;;
esac

# ── 4. Launch ────────────────────────────────────────────────────────
say ""
say "[ok]    Starting the antenna…"
say ""
cd "${INSTALL_DIR}"
exec python3 -m antenna
