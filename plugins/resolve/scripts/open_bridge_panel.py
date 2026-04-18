"""Open the Spellcaster Bridge status panel.

Placed under Scripts/Utility/Spellcaster/ so it shows up in
    Workspace → Scripts → Utility → Spellcaster → Open Bridge Panel

The Bridge is already running (loaded by Resolve as a Workflow
Integration). This script just pops its UI window.
"""

from __future__ import annotations

import os
import sys
import traceback


def _locate_bridge_module():
    """Find spellcaster_bridge in Resolve's Workflow Integration folder.

    We prefer the Resolve-installed Workflow Integration copy but fall
    back to an adjacent repo checkout so developers can run this script
    from source.
    """
    candidates: list[str] = []

    # macOS
    candidates.append(os.path.expanduser(
        "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
        "Workflow Integration Plugins"))
    # Windows
    if os.environ.get("APPDATA"):
        candidates.append(os.path.join(
            os.environ["APPDATA"],
            "Blackmagic Design", "DaVinci Resolve", "Support",
            "Workflow Integration Plugins"))
    # Linux
    candidates.append(os.path.expanduser(
        "~/.local/share/DaVinciResolve/Workflow Integration Plugins"))

    # Repo-local fallback (when running from source during dev)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.normpath(os.path.join(here, "..")))

    for root in candidates:
        if os.path.isdir(os.path.join(root, "spellcaster_bridge")):
            if root not in sys.path:
                sys.path.insert(0, root)
            return True
    return False


def main():
    if not _locate_bridge_module():
        print("[Spellcaster] Bridge not installed — run the Spellcaster "
              "installer and pick the 'DaVinci Resolve integration' option.")
        return 1
    try:
        import spellcaster_bridge
        br = spellcaster_bridge.bridge() or spellcaster_bridge.start()
        if br:
            br.show_panel()
            return 0
        print("[Spellcaster] Bridge failed to initialize.")
        return 1
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
