"""Render All Drafts — queue every draft shot on the Guild.

Complements Capture Timeline: after an import run that drops N fresh
draft shots onto the board, this script flips them all to ``queued``
and nudges the render loop. The resulting clips land in the Media Pool
via the Bridge's asset-subscribe auto-import path.

Menu: Workspace > Scripts > Spellcaster > Render All Drafts
"""
from __future__ import annotations

import os
import sys
import traceback

# Bootstrap: add this script's dir to sys.path so _spellcaster_common
# resolves. Resolve's Scripts exec() doesn't populate __file__ or add
# the script dir to sys.path, so we hardcode the OS-standard install
# location as a fallback. Must run BEFORE the _spellcaster_common import.
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
    guild = _sc.guild_or_die()
    from spellcaster_api import GuildError
    from resolve_helpers import show_message

    # Count drafts first so the confirmation tells the editor what
    # they're about to commit to.
    try:
        shots = guild.list_shots()
    except GuildError as e:
        show_message("Spellcaster", f"Couldn't list shots:\n{e}")
        return 1
    drafts = [s for s in shots
               if (s.get("status") or "").lower() in ("draft", "queued")]
    if not drafts:
        show_message("Spellcaster",
                     "No drafts to render.\n\n"
                     "Capture a timeline first, or add shots in the Guild UI.")
        return 0

    try:
        result = guild.render_all_drafts()
    except GuildError as e:
        show_message("Spellcaster", f"Guild rejected render-all:\n{e}")
        return 1

    queued = int(result.get("queued") or result.get("count") or len(drafts))
    show_message(
        "Spellcaster",
        f"Queued {queued} shot(s) for render.\n\n"
        f"Clips will auto-import into the Spellcaster bin as they "
        f"finish. Open the Bridge panel for live progress.",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
