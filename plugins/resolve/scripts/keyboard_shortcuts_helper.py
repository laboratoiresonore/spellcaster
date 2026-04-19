"""💎 Spellcaster — Keyboard Shortcuts Helper (R125)

Resolve's public scripting API has no hook for programmatic keyboard
binding — shortcut assignments live in a proprietary binary prefs
file that BMD doesn't document, so we can't ship a preset file. The
honest path: show the editor a recommended binding table and walk
them to DaVinci Resolve > Keyboard Customization where they can wire
the same Fusion scripts to hotkeys manually.

All scripts the panel exposes are also visible under:
    DaVinci Resolve > Keyboard Customization… > Search "Spellcaster"
Each binds to any free key combo the user prefers.

Menu: Workspace > Scripts > 💎 Spellcaster > Keyboard Shortcuts Helper
"""
from __future__ import annotations

import os
import sys
import traceback


def _script_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        pass
    if os.name == "nt":
        return os.path.join(
            os.environ.get("APPDATA", ""),
            "Blackmagic Design", "DaVinci Resolve",
            "Support", "Fusion", "Scripts",
            "Utility", "💎 Spellcaster")
    if sys.platform == "darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Blackmagic Design/"
            "DaVinci Resolve/Fusion/Scripts/Utility/💎 Spellcaster")
    return os.path.expanduser(
        "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/💎 Spellcaster")


def _locate_shared():
    here = _script_dir()
    for cand in (
        os.path.join(here, "shared"),
        os.path.normpath(os.path.join(here, "..", "shared")),
        os.path.normpath(os.path.join(here, "..", "..", "shared")),
    ):
        if os.path.isdir(cand) and cand not in sys.path:
            sys.path.insert(0, cand)
            return True
    return False


# The recommended map. Keys chosen to avoid collisions with stock
# Resolve bindings (Ctrl+Alt+<letter> is mostly free in the Edit page).
# A plain 2-column table that pastes well into a dialog.
_SHORTCUT_MAP = [
    # (script name as Resolve lists it, recommended chord, category)
    ("Generate from Playhead",           "Ctrl+Alt+G",  "Capture"),
    ("Capture Timeline",                 "Ctrl+Alt+T",  "Capture"),
    ("Markers → Shots",                  "Ctrl+Alt+M",  "Capture"),
    ("Generate from Prompt",             "Ctrl+Alt+P",  "Generate"),
    ("Generate 3 Variations",            "Ctrl+Alt+V",  "Generate"),
    ("Preset Shootout",                  "Ctrl+Alt+S",  "Generate"),
    ("Reprompt Selected Shot",           "Ctrl+Alt+R",  "Selected clip"),
    ("Upscale Selected Clip",            "Ctrl+Alt+U",  "Selected clip"),
    ("Send Clip to v2v",                 "Ctrl+Alt+2",  "Selected clip"),
    ("Send Clip to VACE",                "Ctrl+Alt+C",  "Selected clip"),
    ("Send Frame to GIMP",               "Ctrl+Alt+I",  "Send to"),
    ("Send Frame to Darktable",          "Ctrl+Alt+D",  "Send to"),
    ("Send Frame to SillyTavern",        "Ctrl+Alt+X",  "Send to"),
    ("Render All Drafts",                "Ctrl+Alt+A",  "Queue"),
    ("Toggle Render Queue",              "Ctrl+Alt+Q",  "Queue"),
    ("Refresh Ready Shots",              "Ctrl+Alt+F",  "Queue"),
    ("Open Bridge Panel",                "Ctrl+Alt+B",  "Meta"),
    ("Open Guild UI",                    "Ctrl+Alt+W",  "Meta"),
]


def _format_table() -> str:
    lines = [
        "DAVINCI RESOLVE DOESN'T SUPPORT IMPORTING SCRIPT SHORTCUTS",
        "FROM A FILE — they live in a proprietary binary prefs blob.",
        "Set these by hand (takes ~3 min), then enjoy one-chord ops.",
        "",
        "HOW TO BIND:",
        "  1. DaVinci Resolve menu → Keyboard Customization…",
        "  2. In the search box, type:  Spellcaster",
        "  3. Click the right-hand shortcut slot → press the chord",
        "  4. Save As → pick a name (e.g. 'Spellcaster Editor')",
        "",
        "RECOMMENDED BINDINGS (free chords on default Resolve layout):",
        "",
    ]
    # Group by category, keeping input order within each
    buckets: dict[str, list[tuple[str, str]]] = {}
    order: list[str] = []
    for name, chord, cat in _SHORTCUT_MAP:
        if cat not in buckets:
            buckets[cat] = []
            order.append(cat)
        buckets[cat].append((name, chord))
    for cat in order:
        lines.append(f"── {cat} ─────────────────────────")
        for name, chord in buckets[cat]:
            lines.append(f"  {chord:<14}{name}")
        lines.append("")
    lines.append(
        "TIP: the same bindings also trigger the 💎 Spellcaster")
    lines.append(
        "     Command Center panel buttons — use whichever is faster.")
    return "\n".join(lines)


def main() -> int:
    _locate_shared()
    try:
        from resolve_helpers import show_message  # type: ignore
    except ImportError:
        print(_format_table())
        return 0
    show_message("💎 Spellcaster — Keyboard Shortcuts", _format_table())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
