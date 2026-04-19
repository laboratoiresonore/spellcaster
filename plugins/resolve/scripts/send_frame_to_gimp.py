"""Send Frame → GIMP (cross-plugin reverse of R105)

Grabs the frame at the playhead, uploads to the shared asset gallery,
and publishes a ``gimp.asset.send`` event. Any GIMP running the
Spellcaster plugin can then call Spellcaster > Check Inbox to open
the frame as a new image.

Editor example: needs to retouch a frame (paint out a wire, restore
a missing element, generate a matte) and wants to drop into GIMP
without a manual export. Grab the frame here, pop over to GIMP, run
Check Inbox — the frame's already waiting.

Menu: Workspace > Scripts > 💎 Spellcaster > 💎 send_frame_to_gimp
"""
from __future__ import annotations

import os
import sys
import traceback
import urllib.parse

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
        get_current_timeline, capture_frame_at_playhead, show_message,
    )

    if not get_current_timeline():
        show_message("Spellcaster",
                     "No timeline is active. Open one first.")
        return 1

    png_path = capture_frame_at_playhead()
    if not png_path or not os.path.exists(png_path):
        show_message("Spellcaster",
                     "Couldn't grab the playhead frame.\n"
                     "Switch to the Color page first and retry.")
        return 1

    try:
        with open(png_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read the still:\n{e}")
        return 1

    # Upload via /api/assets (public URL, cross-host reachable).
    # We use a direct HTTP call rather than CrossInterfaceClient here
    # to stay dependency-free inside Resolve's bundled Python.
    import base64
    import urllib.request
    import urllib.error
    import json as _json

    b64 = base64.b64encode(png_bytes).decode("ascii")
    payload = {
        "origin": "resolve",
        "kind": "frame_grab",
        "title": "Frame from Resolve",
        "tags": ["to_gimp", "resolve_export"],
        "body_b64": b64,
    }
    try:
        req = urllib.request.Request(
            f"{guild.base_url}/api/assets",
            data=_json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            rec = _json.loads(resp.read())
    except Exception as e:
        show_message("Spellcaster",
                     f"Couldn't upload frame to Guild:\n{e}")
        return 1
    finally:
        try:
            os.unlink(png_path)
        except Exception:
            pass

    asset_hash = rec.get("hash", "")
    if not asset_hash:
        show_message("Spellcaster",
                     "Upload succeeded but Guild returned no asset hash.")
        return 1

    # Publish gimp.asset.send — the mailbox fanout routes it to GIMP's
    # inbox, ready for Check Inbox to pull.
    event_payload = {
        "kind": "gimp.asset.send",
        "origin": "resolve",
        "data": {
            "image_url": f"/api/assets/{asset_hash}",
            "hash": asset_hash,
            "source": "resolve_playhead",
            "title": "Frame from Resolve",
        },
    }
    try:
        req = urllib.request.Request(
            f"{guild.base_url}/api/events/emit",
            data=_json.dumps(event_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception as e:
        show_message("Spellcaster",
                     f"Upload succeeded (hash {asset_hash[:10]}…) but "
                     f"couldn't publish the Gimp event:\n{e}\n\n"
                     f"You can still open the image manually at:\n"
                     f"{guild.base_url}/api/assets/{asset_hash}")
        return 1

    show_message(
        "Spellcaster",
        f"Frame sent to GIMP.\n\n"
        f"Asset: {asset_hash[:10]}…\n"
        f"Size: {len(png_bytes) / 1024:.1f} KB\n\n"
        f"Open GIMP and run Spellcaster > 💎 Check Inbox to load "
        f"the frame as a new image.",
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
