"""Import Guild Shotboard → Resolve Timeline

Pulls the Guild's current shotboard as an EDL and imports it as a new
timeline in the active Resolve project. Completes the round-trip:
Resolve → Capture Timeline / Markers → Shots → generate → import back
to Resolve. Works against the Guild's current shot order, so whatever
the editor has reorganised in the web UI flows through.

Note: EDL references rendered MP4s by filename. Clips that haven't
auto-imported to the Media Pool yet (Bridge still catching up) will
import as offline — run Refresh Ready Shots first, or let the Bridge
import finish before running this.

Menu: Workspace > Scripts > Spellcaster > Import Guild Timeline
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
import urllib.request
import urllib.error

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
    from resolve_helpers import (
        get_current_project, get_media_pool, show_message,
    )

    project = get_current_project()
    mp = get_media_pool()
    if not (project and mp):
        show_message("Spellcaster",
                     "No project is open. Open a Resolve project first.")
        return 1

    # Pull EDL from Guild. Framerate matches project timeline rate so
    # the imported EDL lines up with existing timelines.
    try:
        fps = int(float(project.GetSetting("timelineFrameRate") or 24.0))
    except Exception:
        fps = 24

    url = f"{guild.base_url}/api/video/export/edl?fps={fps}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "text/plain"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            edl_bytes = resp.read()
    except urllib.error.HTTPError as e:
        show_message("Spellcaster",
                     f"Guild rejected the EDL export (HTTP {e.code}).")
        return 1
    except Exception as e:
        show_message("Spellcaster",
                     f"Couldn't fetch EDL from Guild:\n{e}")
        return 1

    edl_text = edl_bytes.decode("utf-8", errors="replace")
    if not edl_text.strip():
        show_message("Spellcaster",
                     "Guild returned an empty EDL. Check that the "
                     "shotboard has at least one ready shot.")
        return 1

    # Write to a temp file Resolve can read, then import.
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".edl", prefix="spellcaster_",
        mode="w", encoding="utf-8")
    tmp.write(edl_text)
    tmp_path = tmp.name
    tmp.close()

    try:
        timeline = mp.ImportTimelineFromFile(tmp_path)
    except Exception as e:
        show_message("Spellcaster",
                     f"Resolve couldn't import the EDL:\n{e}\n\n"
                     f"File stayed at:\n{tmp_path}")
        return 1
    finally:
        # Keep the EDL around — editor can re-import it if needed.
        pass

    if not timeline:
        show_message("Spellcaster",
                     f"Resolve returned no timeline from the EDL.\n\n"
                     f"Saved EDL at: {tmp_path}\n"
                     f"Try Media Pool > right-click > Import Timeline > "
                     f"manual open if auto-import failed.")
        return 1

    try:
        tl_name = timeline.GetName()
    except Exception:
        tl_name = "new timeline"
    show_message(
        "Spellcaster",
        f"Imported Guild shotboard as '{tl_name}'.\n\n"
        f"Offline-looking clips mean the matching MP4 isn't in the "
        f"Media Pool yet — the Bridge auto-imports rendered shots as "
        f"they finish. If a clip stays offline after the Bridge shows "
        f"it as ready, run Refresh Ready Shots to nudge it in.",
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
