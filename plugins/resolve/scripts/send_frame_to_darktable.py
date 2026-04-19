"""Send Frame → Darktable

Grabs the frame at the playhead, uploads to the shared asset gallery,
and publishes a ``darktable.asset.send`` event. Any Darktable running
the Spellcaster plugin can then pull the asset from its mailbox.

Useful when the editor wants to grade a grabbed frame in Darktable
before using it as a reference for AI generation (color palette, LUT
matching, etc.).

Menu: Workspace > Scripts > 💎 Spellcaster > 💎 send_frame_to_darktable
"""
from __future__ import annotations

import os
import sys
import base64
import json as _json
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


def _send(target: str, friendly: str, hint: str) -> int:
    guild = _sc.guild_or_die()
    from resolve_helpers import (
        get_current_timeline, capture_frame_at_playhead, show_message,
    )

    if not get_current_timeline():
        show_message("Spellcaster", "No timeline is active. Open one first.")
        return 1

    png_path = capture_frame_at_playhead()
    if not png_path or not os.path.exists(png_path):
        show_message("Spellcaster", "Couldn't grab the playhead frame.")
        return 1

    try:
        with open(png_path, "rb") as f:
            png_bytes = f.read()
    except Exception as e:
        show_message("Spellcaster", f"Couldn't read the still:\n{e}")
        return 1

    b64 = base64.b64encode(png_bytes).decode("ascii")
    payload = {
        "origin": "resolve",
        "kind": "frame_grab",
        "title": f"Frame from Resolve → {friendly}",
        "tags": [f"to_{target}", "resolve_export"],
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
        show_message("Spellcaster", "Upload returned no asset hash.")
        return 1

    event_payload = {
        "kind": f"{target}.asset.send",
        "origin": "resolve",
        "data": {
            "image_url": f"/api/assets/{asset_hash}",
            "hash": asset_hash,
            "source": "resolve_playhead",
            "title": f"Frame from Resolve → {friendly}",
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
                     f"Upload ok (hash {asset_hash[:10]}…) but event "
                     f"publish failed:\n{e}\n\n"
                     f"Pick up manually at:\n"
                     f"{guild.base_url}/api/assets/{asset_hash}")
        return 1

    show_message(
        "Spellcaster",
        f"Frame sent to {friendly}.\n\n"
        f"Asset: {asset_hash[:10]}…\n"
        f"Size: {len(png_bytes) / 1024:.1f} KB\n\n"
        f"{hint}",
    )
    return 0


def main() -> int:
    return _send(
        "darktable",
        "Darktable",
        "In Darktable the inbox subscriber (when present) pulls incoming "
        "assets automatically. If nothing appears, use the asset URL "
        "above to download manually."
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
