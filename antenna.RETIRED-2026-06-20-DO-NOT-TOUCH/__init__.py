"""Spellcaster Antenna — HTTPS control-plane agent for a remote ComfyUI host.

⚠️ DEPRECATED (2026-06-14): Functionality is being absorbed into the
fleet's `prometheus-client` Windows tray application (private repo).
The fleet-frame at Prometheus:8100 now reads its primary machine state
from `/srv/storage/inventory/*.json` (written by prometheus-client),
so a running Spellcaster antenna is no longer required for a box to
appear on the unified display.

What's left to port out before this package is archived:
  - `endpoints/cam.py` (webcam snapshot + record) → prometheus-client
  - `endpoints/updates.py` (per-service updates) → prometheus-client
  - `prometheus_link.py` (heartbeat) → prometheus-client tray loop

Until the port is complete, an installed Spellcaster antenna still
provides richer real-time telemetry overlay for hosts that have it.

See README.md for the historical architecture, security model, and
endpoints.
"""

__version__ = "2.4"
__deprecated__ = True
__archive_target__ = "prometheus-client"
__all__ = ["__version__", "__deprecated__", "__archive_target__"]
