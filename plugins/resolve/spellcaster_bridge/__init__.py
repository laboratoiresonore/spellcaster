"""Spellcaster Bridge — DaVinci Resolve Workflow Integration.

This __init__.py is imported automatically by Resolve at launch because
the whole `spellcaster_bridge/` folder lives in the Workflow Integration
Plugins directory. We start the background workers here.

If Resolve launched without a running Guild server, the Bridge goes into
polling-retry mode and tries to connect every few seconds. No errors are
raised to the Resolve host.
"""

from __future__ import annotations

import os
import sys

# Ensure the shared/ folder is importable from our submodules
_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(os.path.dirname(_HERE), "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from spellcaster_api import GuildClient  # type: ignore  # noqa: E402

from .bridge import Bridge  # noqa: E402
from .config import BridgeConfig  # noqa: E402

__all__ = ["Bridge", "BridgeConfig", "GuildClient", "start"]


_BRIDGE: Bridge | None = None


def start():
    """Called by Resolve on plugin load. Idempotent."""
    global _BRIDGE
    if _BRIDGE is not None:
        return _BRIDGE
    _BRIDGE = Bridge()
    _BRIDGE.start()
    return _BRIDGE


def bridge() -> Bridge | None:
    """Accessor for other plugins (Generate from Playhead, etc)."""
    return _BRIDGE


# Resolve auto-starts the plugin on load
try:
    start()
except Exception as e:
    print(f"[Spellcaster Bridge] start failed: {e}", file=sys.stderr)
