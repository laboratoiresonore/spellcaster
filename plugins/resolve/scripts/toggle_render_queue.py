"""Toggle Render Queue — pause if running, resume if paused.

Single menu entry that flips the Guild's render queue state. Avoids
cluttering the Spellcaster menu with two near-identical items
(Pause / Resume); editors usually want to toggle anyway.

Menu: Workspace > Scripts > Spellcaster > Toggle Render Queue
"""
from __future__ import annotations

import os
import sys
import traceback

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

    try:
        status = guild.queue_status()
    except GuildError as e:
        show_message("Spellcaster", f"Couldn't read queue status:\n{e}")
        return 1

    paused = bool(status.get("paused", False))
    next_state = "resume" if paused else "pause"

    try:
        guild._post_json(f"/api/video/queue/{next_state}", {})
    except GuildError as e:
        show_message("Spellcaster", f"Queue {next_state} failed:\n{e}")
        return 1

    new_status = "paused" if next_state == "pause" else "running"
    running_count = status.get("running", 0)
    queued_count = status.get("queued", 0)
    show_message(
        "Spellcaster",
        f"Render queue: {new_status}\n\n"
        f"  • running: {running_count}\n"
        f"  • queued: {queued_count}",
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
