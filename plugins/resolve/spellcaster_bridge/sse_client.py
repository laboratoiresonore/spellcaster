"""SSE subscription with automatic polling fallback.

Runs on a background thread. Delivers shot-state changes to a callback
regardless of whether the Guild's SSE endpoint is reachable.

Two modes:
  1. **SSE mode** — connect to `/api/video/events`, parse event stream,
     pass through every event verbatim.
  2. **Polling fallback** — if SSE fails to connect, or disconnects,
     poll `/api/video/shots` at `poll_interval_s` and emit synthetic
     "shot.updated" / "shot.ready" events when we detect changes.

Never raises to the caller. All errors go to stderr + an internal
status string that the UI panel can read.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from typing import Callable

# shared/ is added to sys.path by the Bridge's entry module
from spellcaster_api import GuildClient  # type: ignore


EventCallback = Callable[[dict], None]


class SSEClient:
    """Long-lived background worker that emits Guild events to a callback."""

    def __init__(self, guild: GuildClient, on_event: EventCallback,
                 poll_interval_s: float = 2.0):
        self.guild = guild
        self.on_event = on_event
        self.poll_interval_s = poll_interval_s
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._mode = "idle"     # idle | sse | polling | disconnected
        self._last_error: str = ""
        self._last_tick: float = 0.0
        self._known_shots: dict[str, dict] = {}  # id -> last-seen status

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                         name="spellcaster-sse")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._mode = "idle"

    # ── Status (read by UI panel) ────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def last_tick(self) -> float:
        return self._last_tick

    # ── Worker loop ──────────────────────────────────────────────────

    def _run(self):
        # Seed the known-shots map with a first snapshot so we don't flood
        # the UI with "new shot!" on startup
        try:
            for s in self.guild.list_shots():
                sid = s.get("id")
                if sid:
                    self._known_shots[sid] = s
        except Exception:
            pass

        while not self._stop.is_set():
            if not self.guild.is_reachable():
                self._mode = "disconnected"
                self._last_error = "Guild unreachable"
                if self._stop.wait(self.poll_interval_s * 2):
                    return
                continue

            try:
                self._run_sse()
            except Exception as e:
                self._last_error = f"SSE: {e}"
                self._mode = "polling"
                # Fall through to polling for a bit then retry SSE
                self._run_polling(duration_s=15.0)

    def _run_sse(self):
        """Try to maintain an SSE connection. Any failure bubbles up."""
        self._mode = "sse"
        stream = self.guild.open_event_stream()
        if stream is None:
            raise RuntimeError("open_event_stream returned None")
        for event in stream:
            if self._stop.is_set():
                return
            self._last_tick = time.time()
            self._dispatch(event)
            # Piggy-back: also update the known-shots map from shot events
            self._update_known(event.get("data") or {})

    def _run_polling(self, duration_s: float):
        """Fallback polling loop. Runs for at most `duration_s` before we
        try SSE again (in case the server came back online)."""
        deadline = time.time() + duration_s
        while not self._stop.is_set() and time.time() < deadline:
            try:
                shots = self.guild.list_shots()
                self._last_tick = time.time()
                self._diff_and_emit(shots)
            except Exception as e:
                self._last_error = f"poll: {e}"
            if self._stop.wait(self.poll_interval_s):
                return

    def _diff_and_emit(self, shots: list):
        """Synthetic event emission: compare to last-seen snapshot."""
        current: dict[str, dict] = {}
        for s in shots:
            sid = s.get("id")
            if not sid:
                continue
            current[sid] = s
            prev = self._known_shots.get(sid)
            if prev is None:
                self._dispatch({"event": "shot.added", "data": s})
                continue
            if prev.get("status") != s.get("status"):
                self._dispatch({"event": "shot.status", "data": s})
            elif any(prev.get(k) != s.get(k) for k in
                     ("prompt", "preset", "backend", "seed", "title", "video_path")):
                self._dispatch({"event": "shot.updated", "data": s})
        # Removed?
        for sid in self._known_shots.keys() - current.keys():
            self._dispatch({"event": "shot.removed",
                            "data": {"id": sid, "title": self._known_shots[sid].get("title", "")}})
        self._known_shots = current

    def _update_known(self, data: dict):
        sid = data.get("id") if isinstance(data, dict) else None
        if sid:
            self._known_shots[sid] = data

    def _dispatch(self, event: dict):
        try:
            self.on_event(event)
        except Exception as e:
            print(f"[SSEClient] callback raised: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
