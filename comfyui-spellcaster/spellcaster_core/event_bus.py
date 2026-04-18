"""Unified Event Bus — cross-interface pub/sub for Spellcaster.

Every frontend (GIMP, Darktable, Guild, Resolve, SillyTavern, Signal)
can publish events to the bus and subscribe to events from every other.
This replaces the fragmented model where each interface talks to
ComfyUI in isolation.

Event schema:
    {
      "kind": "gimp.generation.finished",   # dotted namespace
      "origin": "gimp",                      # which interface fired it
      "ts": 1713654321.123,                  # server-side timestamp
      "id": "evt_<random>",                  # unique per event
      "data": { ... }                        # free-form payload
    }

Kinds follow `<interface>.<domain>.<action>` — examples:
    gimp.generation.started / .finished / .failed
    gimp.layer.exported
    darktable.export.finished
    guild.shot.ready / .queued / .failed
    resolve.clip.imported / .playhead.captured
    sillytavern.scene.illustrated / .character.spoke
    signal.message.received / .sent

The bus is in-process (pub/sub inside the Guild server) — it's the
natural hub because it already runs continuously while other
interfaces come and go. Events persist in a short ring buffer (N=1000)
so late subscribers can catch up.

Usage:

    from spellcaster_core.event_bus import EventBus
    bus = EventBus.default()
    bus.publish("guild.shot.ready", origin="guild", data={"shot_id": "abc"})

    # From a subscriber thread:
    for evt in bus.subscribe(since_ts=0):
        print(evt)
"""

from __future__ import annotations

import collections
import json
import queue as _queue
import threading
import time
import uuid
from typing import Iterator, Optional


_DEFAULT_RING_SIZE = 1000
_DEFAULT_SUBSCRIBER_QUEUE_SIZE = 200


class EventBus:
    """Thread-safe pub/sub bus with a replay buffer.

    Publishers call `publish(kind, data, origin)` and never block.
    Subscribers call `subscribe()` to get an iterator yielding events
    as they arrive. Ring-buffer replay lets reconnecting clients catch
    up without missing events that fired during their reconnect window.
    """

    _singleton: Optional["EventBus"] = None
    _lock = threading.Lock()

    def __init__(self, ring_size: int = _DEFAULT_RING_SIZE):
        self._ring = collections.deque(maxlen=ring_size)
        self._subscribers: set[_SubscriberQueue] = set()
        self._lock = threading.Lock()

    @classmethod
    def default(cls) -> "EventBus":
        """Process-wide singleton. Every frontend uses the same bus."""
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = cls()
            return cls._singleton

    # ── Publish ──────────────────────────────────────────────────────

    def publish(self, kind: str, *, origin: str = "unknown",
                data: dict | None = None) -> dict:
        """Publish an event and broadcast to all subscribers.

        Returns the full event dict (useful for callers that want the
        generated event id or ts).
        """
        evt = {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "kind": str(kind or "unknown"),
            "origin": str(origin or "unknown"),
            "ts": time.time(),
            "data": dict(data or {}),
        }
        with self._lock:
            self._ring.append(evt)
            subs = list(self._subscribers)
        # Broadcast outside the lock to avoid blocking on slow subscribers
        for s in subs:
            s.offer(evt)
        return evt

    # ── Subscribe ────────────────────────────────────────────────────

    def subscribe(self, *, since_ts: float = 0.0,
                  kinds: Optional[list[str]] = None,
                  origins: Optional[list[str]] = None,
                  timeout: Optional[float] = None) -> Iterator[dict]:
        """Generator yielding events from now onward.

        Args:
            since_ts: Replay buffered events with ts > this first.
                      0.0 = replay everything in the ring.
            kinds: Optional list of kind prefixes to include (e.g.,
                   ["gimp.", "resolve.clip."]). Prefix match.
            origins: Optional list of origins to include.
            timeout: If set, the iterator ends after `timeout` seconds
                     of no events. If None, runs forever.

        The generator closes cleanly when the caller breaks out or the
        subscriber's queue fills past the drop threshold.
        """
        sub = _SubscriberQueue(kinds=kinds, origins=origins)
        # Replay buffered events first
        with self._lock:
            for evt in list(self._ring):
                if evt["ts"] > since_ts and sub.matches(evt):
                    sub.offer(evt)
            self._subscribers.add(sub)
        try:
            while True:
                try:
                    evt = sub.q.get(timeout=timeout) if timeout else sub.q.get()
                except _queue.Empty:
                    return
                if evt is _STOP:
                    return
                yield evt
        finally:
            with self._lock:
                self._subscribers.discard(sub)

    def recent(self, limit: int = 50, since_ts: float = 0.0,
               kinds: Optional[list[str]] = None,
               origins: Optional[list[str]] = None) -> list[dict]:
        """Snapshot of the replay buffer (no live subscription).

        Useful for "dashboard loads last 50 events" HTTP polling paths
        where SSE isn't available.
        """
        with self._lock:
            all_evts = list(self._ring)
        sub = _SubscriberQueue(kinds=kinds, origins=origins)
        filtered = [e for e in all_evts if e["ts"] > since_ts and sub.matches(e)]
        return filtered[-limit:]

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def ring_size(self) -> int:
        with self._lock:
            return len(self._ring)


# ── Internal subscriber ────────────────────────────────────────────────


class _Stop:
    """Sentinel passed through a subscriber queue to wake the generator."""

_STOP = _Stop()


class _SubscriberQueue:
    """Per-subscriber bounded queue with filter predicates."""

    def __init__(self, kinds: Optional[list[str]] = None,
                 origins: Optional[list[str]] = None,
                 maxsize: int = _DEFAULT_SUBSCRIBER_QUEUE_SIZE):
        self.q: _queue.Queue = _queue.Queue(maxsize=maxsize)
        self.kinds = [k for k in (kinds or []) if k]
        self.origins = [o for o in (origins or []) if o]
        self._dropped = 0

    def matches(self, evt: dict) -> bool:
        if self.kinds:
            k = evt.get("kind", "")
            if not any(k.startswith(pref) for pref in self.kinds):
                return False
        if self.origins:
            if evt.get("origin") not in self.origins:
                return False
        return True

    def offer(self, evt: dict):
        if not self.matches(evt):
            return
        try:
            self.q.put_nowait(evt)
        except _queue.Full:
            # Subscriber is lagging — drop oldest to make room
            try:
                self.q.get_nowait()
            except _queue.Empty:
                pass
            try:
                self.q.put_nowait(evt)
            except _queue.Full:
                self._dropped += 1


# ── Validation helpers ────────────────────────────────────────────────


def validate_kind(kind: str) -> bool:
    """Kinds must be non-empty dotted identifiers. Lenient — any
    non-empty string with at least one dot is fine."""
    if not isinstance(kind, str) or not kind.strip():
        return False
    return "." in kind and all(
        c.isalnum() or c in "._-" for c in kind
    )


def sse_format(evt: dict) -> bytes:
    """Serialize an event dict into an SSE record (`event:\\ndata:\\n\\n`).

    Use this when writing to an SSE response stream. Kind becomes the
    SSE `event:` field so JS `EventSource.addEventListener("kind", ...)`
    works naturally.
    """
    kind = str(evt.get("kind", "message"))
    payload = json.dumps(evt, ensure_ascii=False)
    # Escape any embedded newlines per SSE spec (each line prefixed data:)
    data_lines = payload.split("\n")
    data_block = "\n".join(f"data: {line}" for line in data_lines)
    return (f"event: {kind}\n{data_block}\n\n").encode("utf-8")
