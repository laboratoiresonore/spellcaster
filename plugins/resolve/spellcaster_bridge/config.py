"""Bridge config — thin wrapper around the shared config file.

All Bridge settings live in `~/.spellcaster/resolve_bridge.json`:

    {
      "guild_url": "http://127.0.0.1:7777",
      "auto_import": true,
      "target_bin": "Spellcaster",
      "bin_date_subfolder": true,
      "live_timeline": false,
      "live_timeline_name": "Spellcaster Live",
      "poll_interval_s": 2.0,
      "max_events_log": 20
    }

None of the keys are required — sensible defaults are provided.
"""

from __future__ import annotations

import os
import sys

# Bridge lives two levels under plugins/resolve — add shared/ to path
_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(os.path.dirname(_HERE), "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from spellcaster_api import load_config, save_config  # noqa: E402


DEFAULTS = {
    "guild_url": "http://127.0.0.1:7777",
    "auto_import": True,
    "target_bin": "Spellcaster",
    "bin_date_subfolder": True,          # Spellcaster/2026-04-18/clip.mp4
    "live_timeline": False,
    "live_timeline_name": "Spellcaster Live",
    "poll_interval_s": 2.0,
    "max_events_log": 20,
}


class BridgeConfig:
    """In-memory config with dict-style read/write and persist helper."""

    def __init__(self):
        self._data = dict(DEFAULTS)
        self._data.update(load_config())

    def __getitem__(self, key):
        return self._data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self._data[key] = value

    def get(self, key, default=None):
        return self._data.get(key, default if default is not None else DEFAULTS.get(key))

    def update(self, **kwargs):
        self._data.update(kwargs)

    def save(self) -> bool:
        return save_config(self._data)

    def as_dict(self) -> dict:
        return dict(self._data)
