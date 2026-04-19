"""GET /telemetry — R60b: structured antenna health snapshot.

Thin wrapper around antenna.telemetry.collect_snapshot(cfg). See that
module's docstring for schema + design notes.

The schema is compatible with WhimWeaver's FleetTelemetry consumer
(antenna_id, timestamp, cpu/ram/gpu/vram, per-service extras) so the
same dashboard code can ingest both.
"""
from __future__ import annotations

from typing import Any

from .. import telemetry as _telemetry


def snapshot(ctx: dict[str, Any]) -> tuple[int, dict]:
    cfg = ctx.get("config") or {}
    try:
        return 200, _telemetry.collect_snapshot(cfg)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"telemetry collection failed: "
                              f"{type(e).__name__}: {e}"}
