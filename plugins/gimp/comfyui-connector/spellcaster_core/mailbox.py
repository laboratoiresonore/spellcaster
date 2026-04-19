"""Interface Mailbox — per-interface pull queues for short-lived clients.

The SSE event bus is great for long-running subscribers like the
DaVinci Resolve Workflow Integration plugin, which runs as a daemon
inside Resolve. But short-lived clients — GIMP plugins that spawn
for one menu action, SillyTavern polling every N seconds — can't
maintain an SSE subscription long enough to receive push events.

Mailbox gives every interface a lightweight pull-style inbox:

    bus event → matching mailboxes also receive the event
    client polls GET /api/<iface>/inbox
    server returns the queued messages, optionally popping them

Each mailbox is bounded (default 100 messages) and TTL'd (default 5
minutes per message). A completely disconnected client doesn't
accumulate forever.

Usage:
    from spellcaster_core.mailbox import get_mailbox

    mb = get_mailbox("gimp")
    mb.deliver({"kind": "gimp.asset.open", "data": {...}})

    # Client polls:
    pending = mb.peek(consume=True, max_messages=50)
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any, Optional


_DEFAULT_MAX_PER_MAILBOX = 100
_DEFAULT_MSG_TTL_S = 300.0


class Mailbox:
    """Thread-safe bounded deque with per-message TTL."""

    def __init__(self, interface_key: str,
                 max_messages: int = _DEFAULT_MAX_PER_MAILBOX,
                 msg_ttl_s: float = _DEFAULT_MSG_TTL_S):
        self.interface_key = interface_key
        self.max_messages = max_messages
        self.msg_ttl_s = msg_ttl_s
        self._lock = threading.Lock()
        self._deque: deque = deque(maxlen=max_messages)
        self._delivered_count = 0
        self._consumed_count = 0
        self._dropped_count = 0
        self._last_delivery_ts = 0.0
        self._last_consume_ts = 0.0

    # ── Producer side ───────────────────────────────────────────────

    def deliver(self, payload: dict) -> dict:
        """Queue a message for this interface. Returns the wrapped record
        (includes id, enqueued_at). Drops the oldest message if full.
        """
        rec = {
            "id": f"msg_{uuid.uuid4().hex[:10]}",
            "enqueued_at": time.time(),
            "expires_at": time.time() + self.msg_ttl_s,
            "interface": self.interface_key,
            "payload": dict(payload or {}),
        }
        with self._lock:
            was_full = len(self._deque) >= self.max_messages
            self._deque.append(rec)
            if was_full:
                self._dropped_count += 1
            self._delivered_count += 1
            self._last_delivery_ts = rec["enqueued_at"]
        return rec

    # ── Consumer side ───────────────────────────────────────────────

    def peek(self, *, consume: bool = False, max_messages: int = 50,
             since_id: Optional[str] = None) -> list:
        """Read queued messages, oldest first. Evicts expired entries.

        Args:
            consume: If True, pop returned messages from the queue.
                Otherwise leaves them in place (client can later ack
                via ack_ids()).
            max_messages: Cap the result length.
            since_id: Only return messages that arrived AFTER the
                given message id. Useful for clients that remember
                their last-seen id between polls.
        """
        now = time.time()
        with self._lock:
            # Evict expired (compact the deque)
            live = [m for m in self._deque if m["expires_at"] > now]
            dropped = len(self._deque) - len(live)
            if dropped:
                self._dropped_count += dropped
            self._deque = deque(live, maxlen=self.max_messages)

            # Locate since_id anchor, if given
            start_idx = 0
            if since_id:
                for i, m in enumerate(self._deque):
                    if m["id"] == since_id:
                        start_idx = i + 1
                        break
                else:
                    start_idx = 0  # unknown id → return everything

            out = list(self._deque)[start_idx:start_idx + max_messages]
            if consume and out:
                # Remove the returned messages from the head. We keep
                # anything before the `start_idx` slice intact (since
                # a different consumer might have different since_id).
                # Simpler: remove exactly these ids.
                ids = {m["id"] for m in out}
                self._deque = deque(
                    (m for m in self._deque if m["id"] not in ids),
                    maxlen=self.max_messages,
                )
                self._consumed_count += len(out)
                self._last_consume_ts = now
            return out

    def ack_ids(self, ids: list) -> int:
        """Remove messages by id. Returns how many were actually removed."""
        if not ids:
            return 0
        id_set = set(ids)
        with self._lock:
            before = len(self._deque)
            self._deque = deque(
                (m for m in self._deque if m["id"] not in id_set),
                maxlen=self.max_messages,
            )
            removed = before - len(self._deque)
            self._consumed_count += removed
            self._last_consume_ts = time.time()
            return removed

    def clear(self) -> int:
        with self._lock:
            n = len(self._deque)
            self._deque.clear()
            return n

    # ── Introspection ────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            return {
                "interface": self.interface_key,
                "pending": len(self._deque),
                "delivered": self._delivered_count,
                "consumed": self._consumed_count,
                "dropped": self._dropped_count,
                "last_delivery_ts": self._last_delivery_ts,
                "last_consume_ts": self._last_consume_ts,
                "max": self.max_messages,
                "ttl_s": self.msg_ttl_s,
            }


# ── Registry of mailboxes per interface ──────────────────────────────

_MAILBOXES: dict = {}
_MAILBOXES_LOCK = threading.Lock()


def get_mailbox(interface_key: str) -> Mailbox:
    """Get-or-create the singleton mailbox for an interface key."""
    with _MAILBOXES_LOCK:
        mb = _MAILBOXES.get(interface_key)
        if mb is None:
            mb = Mailbox(interface_key)
            _MAILBOXES[interface_key] = mb
    return mb


def all_mailboxes() -> dict:
    """Snapshot of every mailbox's stats."""
    with _MAILBOXES_LOCK:
        return {k: mb.stats() for k, mb in _MAILBOXES.items()}


def fanout_from_event(event: dict):
    """Route a bus event to any interface mailbox that matches.

    The routing rule is simple: an event with kind `<iface>.<rest>`
    gets delivered to the `<iface>` mailbox. Events like
    `gimp.asset.open` → GIMP mailbox; `resolve.clip.import` → Resolve
    mailbox. Events with origin matching the target are NOT delivered
    (don't echo a client's own events back to it).
    """
    if not isinstance(event, dict):
        return
    kind = event.get("kind", "") or ""
    if "." not in kind:
        return
    iface_key = kind.split(".", 1)[0]
    origin = event.get("origin")
    if origin == iface_key:
        return  # don't echo self-events back
    mb = get_mailbox(iface_key)
    mb.deliver({
        "kind": kind,
        "origin": origin,
        "ts": event.get("ts"),
        "event_id": event.get("id"),
        "data": event.get("data", {}),
    })
