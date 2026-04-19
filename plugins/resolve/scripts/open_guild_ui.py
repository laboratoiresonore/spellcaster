"""Open Guild UI — launch the Wizard Guild chat interface in the default browser.

Fastest context switch from Resolve to the full Guild web UI, which
has everything the scripts don't cover: prompt editing, shot reorder,
batch ops, LLM chat, snapshot management, presets, etc.

Menu: Workspace > Scripts > Spellcaster > Open Guild UI
"""
from __future__ import annotations

import os
import sys
import traceback
import webbrowser

def _boot():
    try:
        d = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        if os.name == "nt":
            d = os.path.join(os.environ.get("APPDATA", ""),
                              "Blackmagic Design", "DaVinci Resolve",
                              "Support", "Fusion", "Scripts",
                              "Utility", "Spellcaster")
        elif sys.platform == "darwin":
            d = os.path.expanduser(
                "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
                "/Fusion/Scripts/Utility/Spellcaster")
        else:
            d = os.path.expanduser(
                "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Spellcaster")
    if d and d not in sys.path:
        sys.path.insert(0, d)
_boot()

import _spellcaster_common as _sc  # noqa: E402


def main() -> int:
    # Use guild_or_die to pull the configured URL (respects
    # resolve_bridge.json and env overrides).
    guild = _sc.guild_or_die()
    url = guild.base_url
    try:
        webbrowser.open(url, new=2)
    except Exception:
        from resolve_helpers import show_message
        show_message("Spellcaster",
                     f"Couldn't launch a browser.\n\n"
                     f"Open this URL manually:\n{url}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
