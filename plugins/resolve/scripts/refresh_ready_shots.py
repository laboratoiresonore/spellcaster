"""Refresh Ready Shots — append every ready Guild clip to the timeline.

The Bridge already auto-imports rendered clips into the Media Pool.
This script is the "now put them on the timeline" step: walks every
shot with ``status=ready`` and a valid ``video_path``, finds the
matching MediaPoolItem (by filename), and appends it to the current
timeline in shotboard order.

Menu: Workspace > Scripts > Spellcaster > Refresh Ready Shots
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
    from resolve_helpers import (
        get_media_pool, get_current_timeline, show_message,
        append_to_current_timeline,
    )

    timeline = get_current_timeline()
    mp = get_media_pool()
    if not (timeline and mp):
        show_message("Spellcaster",
                     "No timeline is active. Open one first.")
        return 1

    try:
        shots = guild.list_shots()
    except GuildError as e:
        show_message("Spellcaster", f"Couldn't list shots:\n{e}")
        return 1
    ready = [s for s in shots
              if (s.get("status") or "").lower() == "ready"
              and s.get("video_path")]
    ready.sort(key=lambda s: s.get("index", 0))
    if not ready:
        show_message("Spellcaster",
                     "No ready shots to append.\n\n"
                     "Render some shots first (Render All Drafts).")
        return 0

    # Walk the media pool (all folders) collecting clips by basename.
    clips_by_name: dict[str, object] = {}

    def _walk(folder):
        try:
            for c in folder.GetClipList() or []:
                try:
                    props = c.GetClipProperty()
                    name = (props or {}).get("File Name") or c.GetName()
                except Exception:
                    name = c.GetName() if hasattr(c, "GetName") else ""
                if name:
                    clips_by_name.setdefault(os.path.basename(name), c)
            for sub in folder.GetSubFolderList() or []:
                _walk(sub)
        except Exception:
            pass

    try:
        _walk(mp.GetRootFolder())
    except Exception:
        pass

    # Append in shotboard order. Items without a matching pool clip are
    # reported (Bridge's auto-import might not have caught up yet).
    appended = 0
    missing: list[str] = []
    for shot in ready:
        basename = os.path.basename(shot.get("video_path") or "")
        item = clips_by_name.get(basename)
        if item is None:
            missing.append(shot.get("title") or basename)
            continue
        try:
            if append_to_current_timeline(item):
                appended += 1
        except Exception:
            missing.append(shot.get("title") or basename)

    msg = f"Appended {appended} clip(s) to the timeline."
    if missing:
        msg += (f"\n\n{len(missing)} missing from Media Pool "
                 f"(Bridge may still be importing):\n  "
                 + "\n  ".join(missing[:6]))
        if len(missing) > 6:
            msg += f"\n  …and {len(missing) - 6} more"
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
