"""Bridge orchestrator — glues SSE client + media pool sync + UI panel.

Lifecycle:
    start()  — spawn SSE worker + cross-interface heartbeat, register
               event dispatch to MediaPoolSync
    stop()   — tear down workers
    show_panel() — open the Fusion UI status window

Event flow:
    SSEClient.on_event → MediaPoolSync.handle_event → imports mp4 + marks
                        → (if enabled) appends to Spellcaster Live timeline

Cross-interface flow:
    • heartbeat every ~10 s via POST /api/interfaces/heartbeat, which
      registers "resolve" as online in the Guild's InterfaceRegistry
      → "Send to Resolve" chips appear in the Guild UI dynamically
    • subscribes to `resolve.*` events on the bus so Guild-side actions
      (e.g., user clicks "Send to Resolve" on a generated image) trigger
      a Resolve-side reaction (import the asset into the Media Pool)
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.parse
import urllib.request

from spellcaster_api import GuildClient  # type: ignore

from .config import BridgeConfig
from .sse_client import SSEClient
from .media_pool_sync import MediaPoolSync


_HEARTBEAT_INTERVAL_S = 10.0


class Bridge:
    def __init__(self):
        self.config = BridgeConfig()
        self.guild = GuildClient(self.config.get("guild_url"))
        self.sync = MediaPoolSync(self.guild, self.config)
        self.sse = SSEClient(
            self.guild,
            on_event=self.sync.handle_event,
            poll_interval_s=float(self.config.get("poll_interval_s", 2.0)),
        )
        self._panel = None
        self._started = False
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None
        self._bus_stop = threading.Event()
        self._bus_thread: threading.Thread | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self):
        if self._started:
            return
        self.sse.start()
        self._start_heartbeat()
        self._start_bus_subscription()
        self._started = True
        print(f"[Spellcaster Bridge] Started. Guild={self.guild.base_url}  "
              f"Auto-import={self.config.get('auto_import')}  "
              f"Live timeline={self.config.get('live_timeline')}")

    def stop(self):
        if not self._started:
            return
        self.sse.stop()
        self._hb_stop.set()
        self._bus_stop.set()
        self._started = False
        print("[Spellcaster Bridge] Stopped.")

    # ── Cross-interface heartbeat ────────────────────────────────────

    def _start_heartbeat(self):
        """Tell the Guild registry we're alive every 10 s.

        Registers this interface under the `resolve` key. As long as
        the heartbeat keeps arriving, the Guild UI will render
        Resolve-specific chips ("Send to Resolve", etc). If Resolve
        quits, the heartbeats stop, and within 30 s the Guild marks
        us offline and those chips disappear automatically.
        """
        self._hb_stop.clear()

        def _loop():
            # Fire the first heartbeat immediately
            self._send_heartbeat()
            while not self._hb_stop.wait(_HEARTBEAT_INTERVAL_S):
                self._send_heartbeat()

        self._hb_thread = threading.Thread(
            target=_loop, daemon=True, name="resolve-bridge-heartbeat")
        self._hb_thread.start()

    def _send_heartbeat(self):
        try:
            body = json.dumps({
                "interface": "resolve",
                "meta": {
                    "bridge_version": "mvp",
                    "imported": self.sync.imported_count(),
                    "sse_mode": self.sse.mode,
                },
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self.guild.base_url}/api/interfaces/heartbeat",
                data=body, method="POST",
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=3.0).close()
        except Exception:
            # Silent — the bridge remains useful even if heartbeat fails
            pass

    # ── Cross-interface event subscription ───────────────────────────

    def _start_bus_subscription(self):
        """Subscribe to `resolve.*` events on the Guild's bus.

        Guild-side actions (e.g., user clicks "Send to Resolve" on a
        generated image) publish `resolve.asset.send` with the image
        URL. This thread catches them and ingests the image into
        Resolve's Media Pool via the existing sync pipeline.
        """
        self._bus_stop.clear()

        def _loop():
            backoff = 2.0
            while not self._bus_stop.is_set():
                try:
                    self._consume_bus_events()
                    backoff = 2.0  # reset on clean exit
                except Exception:
                    pass
                if self._bus_stop.wait(backoff):
                    return
                backoff = min(backoff * 1.5, 30.0)

        self._bus_thread = threading.Thread(
            target=_loop, daemon=True, name="resolve-bridge-bus")
        self._bus_thread.start()

    def _consume_bus_events(self):
        """Open a single SSE connection + process events until it closes."""
        params = urllib.parse.urlencode({"kinds": "resolve."})
        url = f"{self.guild.base_url}/api/events/stream?{params}"
        req = urllib.request.Request(
            url, headers={"Accept": "text/event-stream"})
        resp = urllib.request.urlopen(req, timeout=60.0)
        try:
            event_name = "message"
            data_buf: list[str] = []
            for raw in resp:
                if self._bus_stop.is_set():
                    return
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                except Exception:
                    continue
                if line == "":
                    if data_buf:
                        joined = "\n".join(data_buf)
                        try:
                            parsed = json.loads(joined)
                        except Exception:
                            parsed = {}
                        self._handle_bus_event(event_name, parsed)
                    event_name = "message"
                    data_buf = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_buf.append(line[5:].lstrip())
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def _handle_bus_event(self, kind: str, evt: dict):
        """Dispatch an event of kind `resolve.*` to the appropriate action."""
        data = evt.get("data") or {}
        if kind in ("resolve.asset.send", "resolve.clip.import"):
            # Guild wants Resolve to import an image/video
            image_url = data.get("image_url") or data.get("url") or data.get("video_url")
            if not image_url:
                return
            try:
                self._ingest_external_image(image_url, evt)
            except Exception as e:
                print(f"[Spellcaster Bridge] ingest failed: {e}", file=sys.stderr)

    def _ingest_external_image(self, image_url: str, evt: dict):
        """Download an asset from the Guild and hand to MediaPoolSync."""
        # Fake a "shot ready" event that the sync module already knows
        # how to handle — it'll download + import + add metadata marker
        shot_stub = {
            "id": f"guild_send_{int(time.time() * 1000)}",
            "title": evt.get("data", {}).get("title", "Guild send"),
            "status": "ready",
            "prompt": evt.get("data", {}).get("prompt", ""),
            "preset": evt.get("data", {}).get("preset", ""),
            "backend": "guild-bus",
            "video_path": image_url,
        }
        # Download the URL to the sync module's cache dir and import
        import os
        import urllib.parse
        import urllib.request as _ur
        from resolve_helpers import import_video  # type: ignore
        dest = os.path.join(self.sync._cache_dir,
                            f"{shot_stub['id']}.png")
        try:
            with _ur.urlopen(image_url, timeout=30.0) as r:
                data = r.read()
            with open(dest, "wb") as f:
                f.write(data)
        except Exception as e:
            print(f"[Spellcaster Bridge] ingest download failed: {e}",
                  file=sys.stderr)
            return
        bin_parts = [self.config.get("target_bin", "Spellcaster"),
                     "From Guild"]
        item = import_video(dest, target_bin_parts=bin_parts)
        if item:
            self.sync._log(f"Imported from Guild: {shot_stub['title']}")

    # ── UI ───────────────────────────────────────────────────────────

    def show_panel(self):
        try:
            from .ui_panel import BridgePanel
            self._panel = BridgePanel(self.guild, self.sse, self.sync, self.config)
            self._panel.show()
        except Exception as e:
            print(f"[Spellcaster Bridge] Panel failed: {e}", file=sys.stderr)

    # ── Introspection (used by peer plugins) ─────────────────────────

    def status(self) -> dict:
        return {
            "guild_url": self.guild.base_url,
            "connected": self.guild.is_reachable(),
            "sse_mode": self.sse.mode,
            "imported": self.sync.imported_count(),
            "auto_import": bool(self.config.get("auto_import")),
            "events_tail": self.sync.events_tail,
        }
