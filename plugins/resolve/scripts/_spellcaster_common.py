"""R84: tiny helper shared by all standalone scripts.

Every script needs the same two things: a way to find ``shared/``
when Resolve strips ``__file__``, and a reachable GuildClient. This
module centralises both so individual scripts can be tiny.

Keep this file dependency-free beyond the stdlib so it works inside
Resolve's bundled Python without ``requests`` or ``urllib3``.
"""
from __future__ import annotations

import os
import sys


def script_dir() -> str:
    """Best-effort lookup of the script's directory. Mirrors
    _script_dir in each main script — duplicated here so
    _spellcaster_common stays self-contained even if imported before
    shared/ is on sys.path."""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        pass
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return os.path.join(
                appdata, "Blackmagic Design", "DaVinci Resolve",
                "Support", "Fusion", "Scripts", "Utility", "Spellcaster")
    elif sys.platform == "darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
            "/Fusion/Scripts/Utility/Spellcaster")
    else:
        return os.path.expanduser(
            "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Spellcaster")
    return ""


def add_shared_to_path() -> bool:
    here = script_dir()
    if not here:
        return False
    for cand in (
        os.path.join(here, "shared"),
        os.path.normpath(os.path.join(here, "..", "shared")),
        os.path.normpath(os.path.join(here, "..", "..", "shared")),
    ):
        if os.path.isdir(cand) and cand not in sys.path:
            sys.path.insert(0, cand)
            return True
    return False


def guild_or_die():
    """Return a reachable GuildClient, or show a modal + raise SystemExit(1).

    Factors out the "find Guild, show error if not reachable" pattern
    that every script needs.
    """
    add_shared_to_path()
    try:
        from spellcaster_api import GuildClient, discover_guild_url
        from resolve_helpers import show_message
    except ImportError as e:
        print(f"[Spellcaster] Plugin not fully installed: {e}")
        raise SystemExit(1)
    guild = GuildClient(discover_guild_url())
    if not guild.is_reachable():
        show_message("Spellcaster",
                     "Can't reach the Wizard Guild.\n\n"
                     "Start the Guild (Wizard Guild.bat / .sh) and try again.")
        raise SystemExit(1)
    return guild
