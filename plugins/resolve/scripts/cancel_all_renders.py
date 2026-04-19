"""Cancel All Renders — stop every running + queued shot on the Guild.

Single-button emergency brake. Flips every non-draft, non-ready shot
back to draft. The Guild's video-bridge honours the status flip on
its next tick and kills any active subprocess (WanGP) or ComfyUI
prompt it's tracking.

Menu: Workspace > Scripts > Spellcaster > Cancel All Renders
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
                              "Utility", "💎 Spellcaster")
        elif sys.platform == "darwin":
            d = os.path.expanduser(
                "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
                "/Fusion/Scripts/Utility/💎 Spellcaster")
        else:
            d = os.path.expanduser(
                "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/💎 Spellcaster")
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

    live = [s for s in shots
             if (s.get("status") or "").lower()
                in ("queued", "running")]
    if not live:
        show_message("Spellcaster",
                     "Nothing to cancel — queue is empty.")
        return 0

    cancelled = 0
    failures = []
    for shot in live:
        sid = shot.get("id") or ""
        try:
            guild.cancel_shot(sid)
            cancelled += 1
        except GuildError as e:
            failures.append(f"{(shot.get('title') or sid)[:30]}: {e}")

    # Also pause the queue so nothing the render loop is holding in
    # its buffer picks up immediately. Editor can resume manually.
    try:
        guild._post_json("/api/video/queue/pause", {})
    except GuildError:
        pass

    msg = f"Cancelled {cancelled}/{len(live)} active render(s); queue paused."
    if failures:
        msg += "\n\nFailures:\n  " + "\n  ".join(failures[:5])
        if len(failures) > 5:
            msg += f"\n  …and {len(failures) - 5} more"
    show_message("Spellcaster", msg)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
