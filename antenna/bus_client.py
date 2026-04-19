"""Hub event-bus client — fire-and-forget events from antenna to Guild.

The antenna runs on a remote machine and mutates state (installs a node,
downloads a model, completes a self-update). The Guild on the hub needs
to know about these so its UI can reflect them in real time — a chip
animation, a toast, a progress indicator.

This module provides a thin client that POSTs to `{hub}/api/events/emit`
with `kind="antenna.<verb>"` and arbitrary data. Silent on every error
path: if the hub is unreachable, offline, or returns 500, antenna's
primary operation MUST NOT fail because a side-channel notification
couldn't land.

Usage
-----
    from .. import bus_client
    bus_client.emit(ctx, "antenna.node.installed", {
        "node_key": "ComfyUI-Spellcaster",
        "took_seconds": 4.7,
    })

Design
------
- Fire-and-forget: we don't wait for a successful ack beyond the POST.
- No queue / retry: if the hub is down, the event is dropped. The
  antenna's primary HTTP response carries the authoritative result
  (return status_code from the endpoint handler); the bus event is
  just for live UI updates.
- Runs on a background thread so the endpoint can return immediately
  without waiting on a hub network round-trip.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from typing import Any


_POST_TIMEOUT = 3.0


def _hub_url_from_ctx(ctx: dict[str, Any]) -> str | None:
    """Extract the hub URL from the request context's config. None if unset."""
    cfg = ctx.get("config") or {}
    hub = cfg.get("hub_url", "") if isinstance(cfg, dict) else ""
    hub = (hub or "").strip()
    return hub or None


def _send(hub_url: str, kind: str, data: dict[str, Any]) -> None:
    """Blocking POST — called only from the background thread started by emit()."""
    body = json.dumps({
        "kind": kind,
        "origin": "antenna",
        "data": data,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{hub_url.rstrip('/')}/api/events/emit",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "spellcaster-antenna-bus-client",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_POST_TIMEOUT) as resp:
            _ = resp.read(1024)  # drain + close cleanly
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        # Hub down, route missing, connection refused, etc. — fine.
        # Caller already has the authoritative result via HTTP response.
        pass
    except Exception as e:  # noqa: BLE001 — never let the bg thread crash loud
        print(f"[bus_client] send {kind!r} failed: {type(e).__name__}: {e}",
              file=sys.stderr)


def emit(ctx: dict[str, Any], kind: str, data: dict[str, Any] | None = None) -> None:
    """Fire-and-forget event notification to the hub's /api/events/emit.

    Args:
        ctx: request context dict (has 'config' with 'hub_url')
        kind: event kind — MUST start with "antenna." to stay in the
              antenna's event namespace. The Guild's fan-out routes
              "<iface>.*" events into the matching mailbox.
        data: arbitrary JSON-serializable dict. Caller is responsible
              for keeping it small — hub mailboxes cap at ~100 messages.

    Returns immediately; actual POST happens on a daemon thread. Errors
    are silent (logged to stderr only on unexpected exception types).

    No-op when hub_url isn't configured.
    """
    if not kind.startswith("antenna."):
        print(f"[bus_client] refusing to emit kind {kind!r} "
              f"— antenna events must be namespaced as 'antenna.*'",
              file=sys.stderr)
        return
    hub_url = _hub_url_from_ctx(ctx)
    if not hub_url:
        return  # no hub configured → no-op
    payload = dict(data or {})
    t = threading.Thread(
        target=_send,
        args=(hub_url, kind, payload),
        daemon=True,
        name=f"bus-emit-{kind}",
    )
    t.start()
