"""Retry Failed — re-queue every shot whose last render errored.

Mirrors the Guild UI's "Reset failed" action. Flips each
``status=failed`` shot back to draft and triggers the render loop.

Menu: Workspace > Scripts > Spellcaster > Retry Failed
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
        shots = guild.list_shots()
    except GuildError as e:
        show_message("Spellcaster", f"Couldn't list shots:\n{e}")
        return 1
    failed = [s for s in shots
               if (s.get("status") or "").lower() == "failed"]
    if not failed:
        show_message("Spellcaster", "No failed shots to retry.")
        return 0

    # /api/video/reset-failed is the Guild's one-shot batch reset —
    # it flips status back to draft for every failed shot and then
    # kicks the render loop.
    try:
        guild._post_json("/api/video/reset-failed", {})
    except GuildError as e:
        show_message("Spellcaster", f"Reset failed:\n{e}")
        return 1

    show_message(
        "Spellcaster",
        f"Re-queued {len(failed)} failed shot(s).\n\n"
        f"Watch the Bridge panel for progress.",
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
