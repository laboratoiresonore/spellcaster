"""Top-level entry for `python -m antenna`.

Picks the best shell automatically:
  - Windows + pystray installed → antenna.tray (system tray + toasts)
  - everything else             → antenna.agent (console)

Users who want to force console mode on Windows can do
    python -m antenna.agent
or set the env var SPELLCASTER_ANTENNA_NO_TRAY=1 before launch.
"""

from __future__ import annotations

import os
import sys


def _prefer_tray() -> bool:
    if os.name != "nt":
        return False
    if os.environ.get("SPELLCASTER_ANTENNA_NO_TRAY", "").strip() in ("1", "true", "yes"):
        return False
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def main() -> int:
    if _prefer_tray():
        from . import tray
        return tray.main()
    # Console mode — run the agent's serve loop
    from . import agent, config
    agent.serve(config.bootstrap(), block=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
