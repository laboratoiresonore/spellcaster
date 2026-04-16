"""Spellcaster Keyboard Shortcuts for GIMP 3.0+

Installs default keyboard shortcuts for Spellcaster tools into GIMP's
shortcut system. Shortcuts are registered via Gtk accelerators on
GIMP's application-level action map.

Usage:
    install_shortcuts()   — writes shortcutrc entries for all Spellcaster tools
    get_shortcut_map()    — returns the default shortcut→procedure mapping

Shortcuts follow the pattern:
    Ctrl+Shift+<key>      — primary generation tools
    Ctrl+Alt+<key>        — quick context actions (zero-dialog)
    Ctrl+Alt+Shift+<key>  — specialty tools

These don't conflict with GIMP's built-in shortcuts.
"""

import os
import platform
from pathlib import Path


# ── Default shortcut map ─────────────────────────────────────────────────
# Maps GIMP procedure names to Gtk accelerator strings.
# Format: "<Ctrl><Shift>i" etc.

SPELLCASTER_SHORTCUTS = {
    # ── Primary tools (Ctrl+Shift) ────────────────────────────────────
    "spellcaster-img2img":          "<Ctrl><Shift>i",    # Image to Image
    "spellcaster-txt2img":          "<Ctrl><Shift>t",    # Text to Image
    "spellcaster-inpaint":          "<Ctrl><Shift>p",    # Inpaint
    "spellcaster-kontext":          "<Ctrl><Shift>k",    # Kontext Editor
    "spellcaster-klein-img2img":    "<Ctrl><Shift>j",    # Klein Editor
    "spellcaster-sam3-select":      "<Ctrl><Shift>a",    # AI Selection

    # ── Quick actions (Ctrl+Alt) — zero dialog ────────────────────────
    "spellcaster-quick-enhance":     "<Ctrl><Alt>e",     # Quick Enhance
    "spellcaster-quick-inpaint":     "<Ctrl><Alt>p",     # Quick Inpaint
    "spellcaster-quick-upscale":     "<Ctrl><Alt>u",     # Quick Upscale
    "spellcaster-quick-face-restore":"<Ctrl><Alt>f",     # Quick Face Restore
    "spellcaster-quick-rembg":       "<Ctrl><Alt>b",     # Quick Remove BG
    "spellcaster-rerun-last":        "<Ctrl><Alt>r",     # Re-run Last

    # ── Specialty (Ctrl+Alt+Shift) ────────────────────────────────────
    "spellcaster-color-match":       "<Ctrl><Alt><Shift>c",  # Color Match
    "spellcaster-style-transfer":    "<Ctrl><Alt><Shift>s",  # Style Transfer
    "spellcaster-upscale":           "<Ctrl><Alt><Shift>u",  # Full Upscale dialog
    "spellcaster-face-restore":      "<Ctrl><Alt><Shift>f",  # Full Face Restore
    "spellcaster-rembg":             "<Ctrl><Alt><Shift>b",  # Full Rembg dialog
    "spellcaster-my-presets":        "<Ctrl><Alt><Shift>m",  # My Presets
    "spellcaster-settings":          "<Ctrl><Alt><Shift>comma",  # Settings
}


def _find_gimp_config_dir():
    """Find the current GIMP 3.x config directory."""
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            gimp_base = Path(appdata) / "GIMP"
            if gimp_base.is_dir():
                # Find the newest 3.x version directory
                candidates = sorted(
                    [d for d in gimp_base.iterdir()
                     if d.is_dir() and d.name.startswith("3")],
                    key=lambda d: d.name, reverse=True)
                if candidates:
                    return candidates[0]
    elif platform.system() == "Darwin":
        gimp_base = Path.home() / "Library" / "Application Support" / "GIMP"
        if gimp_base.is_dir():
            candidates = sorted(
                [d for d in gimp_base.iterdir()
                 if d.is_dir() and d.name.startswith("3")],
                key=lambda d: d.name, reverse=True)
            if candidates:
                return candidates[0]
    else:
        gimp_base = Path.home() / ".config" / "GIMP"
        if gimp_base.is_dir():
            candidates = sorted(
                [d for d in gimp_base.iterdir()
                 if d.is_dir() and d.name.startswith("3")],
                key=lambda d: d.name, reverse=True)
            if candidates:
                return candidates[0]
    return None


def _build_shortcutrc_content(shortcuts=None):
    """Build the content for a GIMP shortcutrc file.

    GIMP 3.0 uses a simple text format:
      (gtk_accel_path "<Actions>/plug-in/procedure-name" "<Ctrl><Shift>i")
    """
    if shortcuts is None:
        shortcuts = SPELLCASTER_SHORTCUTS

    lines = [
        "; Spellcaster keyboard shortcuts",
        "; Auto-generated — edit manually or re-run install_shortcuts() to reset",
        ";",
    ]
    for proc_name, accel in sorted(shortcuts.items()):
        lines.append(
            f'(gtk_accel_path "<Actions>/plug-in/{proc_name}" "{accel}")')
    lines.append("")
    return "\n".join(lines)


def install_shortcuts(shortcuts=None):
    """Install Spellcaster keyboard shortcuts into GIMP's shortcutrc.

    Reads the existing shortcutrc (if any), removes old Spellcaster entries,
    and appends the new ones. This is safe to call multiple times.

    Returns:
        str: Path to the modified shortcutrc, or None if GIMP config not found.
    """
    config_dir = _find_gimp_config_dir()
    if not config_dir:
        return None

    rc_path = config_dir / "shortcutrc"
    if shortcuts is None:
        shortcuts = SPELLCASTER_SHORTCUTS

    # Read existing content, filtering out old Spellcaster entries
    existing_lines = []
    if rc_path.exists():
        try:
            existing_lines = rc_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            pass

    # Filter out old spellcaster shortcuts and the header comment
    filtered = []
    skip_header = False
    for line in existing_lines:
        if "; Spellcaster keyboard shortcuts" in line:
            skip_header = True
            continue
        if skip_header and line.startswith(";"):
            continue
        skip_header = False
        if "spellcaster-" in line:
            continue
        filtered.append(line)

    # Build new content
    new_block = _build_shortcutrc_content(shortcuts)

    # Combine: existing (filtered) + new spellcaster block
    final = "\n".join(filtered).rstrip() + "\n\n" + new_block

    try:
        rc_path.write_text(final, encoding="utf-8")
        return str(rc_path)
    except Exception:
        return None


def get_shortcut_map():
    """Return the default shortcut mapping for documentation/UI display."""
    return dict(SPELLCASTER_SHORTCUTS)


def get_shortcut_help():
    """Return a human-readable shortcut reference string."""
    categories = {
        "Primary Tools (Ctrl+Shift)": [],
        "Quick Actions (Ctrl+Alt)": [],
        "Specialty (Ctrl+Alt+Shift)": [],
    }

    for proc, accel in sorted(SPELLCASTER_SHORTCUTS.items()):
        # Parse the accelerator into a readable form
        readable = accel.replace("<Ctrl>", "Ctrl+").replace("<Shift>", "Shift+") \
                        .replace("<Alt>", "Alt+").replace("++", "+")
        # Clean up procedure name
        label = proc.replace("spellcaster-", "").replace("-", " ").title()

        if "<Alt><Shift>" in accel or "<Shift>" in accel and "<Alt>" in accel:
            categories["Specialty (Ctrl+Alt+Shift)"].append(f"  {readable:30s} {label}")
        elif "<Alt>" in accel:
            categories["Quick Actions (Ctrl+Alt)"].append(f"  {readable:30s} {label}")
        else:
            categories["Primary Tools (Ctrl+Shift)"].append(f"  {readable:30s} {label}")

    lines = ["Spellcaster Keyboard Shortcuts", "=" * 40, ""]
    for cat, entries in categories.items():
        if entries:
            lines.append(cat)
            lines.append("-" * len(cat))
            lines.extend(sorted(entries))
            lines.append("")

    return "\n".join(lines)
