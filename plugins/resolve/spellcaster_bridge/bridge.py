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


def _resolve_host() -> str:
    """Short, LAN-safe hostname for instance_id disambiguation."""
    try:
        import socket
        raw = (socket.gethostname() or "").strip().split(".")[0][:64]
    except Exception:
        raw = ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "0123456789-_")
    cleaned = "".join(c for c in raw if c in allowed)
    return cleaned or "resolve-host"


_RESOLVE_HOST = _resolve_host()

# Presence broker metadata — matches the shape the other plugins use so
# the ComfyUI pack can enumerate this interface as a peer even when the
# Guild is restarting (see AUDIT_CROSS_APP_DISCOVERY.md §6.5).
_RESOLVE_PRESENCE_META = {
    "key": "resolve",
    "label": "DaVinci Resolve",
    "icon": "🎬",
    "version": "mvp",
    "capabilities": ["receive_image", "receive_video", "timeline_import"],
    "host": _RESOLVE_HOST,
    "instance_id": f"resolve@{_RESOLVE_HOST}",
}


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
        # Resolved on first heartbeat via GET {guild}/api/config; Resolve
        # doesn't configure this directly (it's Guild-centric by design).
        self._comfyui_url: str | None = None
        self._comfyui_url_checked = False

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
        meta = {
            "bridge_version": "mvp",
            "imported": self.sync.imported_count(),
            "sse_mode": self.sse.mode,
        }
        try:
            body = json.dumps({
                "interface": "resolve",
                "meta": meta,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self.guild.base_url}/api/interfaces/heartbeat",
                data=body, method="POST",
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=3.0).close()
        except Exception:
            # Silent — the bridge remains useful even if heartbeat fails
            pass
        # Mirror to ComfyUI's presence broker so peer plugins see us even
        # when the Guild is momentarily down.
        self._send_comfyui_presence(meta)

    # ── ComfyUI presence broker mirror ───────────────────────────────

    def _resolve_comfyui_url(self) -> str | None:
        """One-shot lookup of the ComfyUI URL via {guild}/api/config.

        Resolve's BridgeConfig doesn't carry comfyui_url — the Guild owns
        that setting. We fetch once, cache, and tolerate the Guild being
        down (returns None; presence silently skipped).
        """
        if self._comfyui_url_checked:
            return self._comfyui_url
        self._comfyui_url_checked = True
        try:
            req = urllib.request.Request(
                f"{self.guild.base_url}/api/config",
                headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3.0) as r:
                cfg = json.loads(r.read().decode("utf-8", errors="replace"))
            url = (cfg.get("comfyui_url") or "").strip()
            if url:
                self._comfyui_url = url.rstrip("/")
        except Exception:
            self._comfyui_url = None
        return self._comfyui_url

    def _send_comfyui_presence(self, meta: dict):
        url = self._resolve_comfyui_url()
        if not url:
            return
        body = dict(_RESOLVE_PRESENCE_META)
        body["url"] = self.guild.base_url
        body["meta"] = meta
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                f"{url}/spellcaster/presence/heartbeat",
                data=data, method="POST",
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2.0).close()
        except Exception:
            # ComfyUI might be off or not running the Spellcaster pack;
            # Guild heartbeat already succeeded so this is a bonus.
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
        elif kind == "resolve.playhead.grab":
            # R122: Cinematographer asked us for the current playhead
            # frame. Capture it + upload to the Guild's asset gallery,
            # then publish resolve.playhead.ready so the wizard can
            # attach it as a shot reference.
            try:
                self._handle_playhead_grab(evt)
            except Exception as e:
                print(f"[Spellcaster Bridge] playhead grab failed: {e}",
                      file=sys.stderr)
        elif kind == "resolve.timeline.import":
            # R122: Cinematographer asked us to import the current
            # shotboard as a new Resolve timeline. Fetch EDL from
            # Guild + MediaPool.ImportTimelineFromFile.
            try:
                self._handle_timeline_import(evt)
            except Exception as e:
                print(f"[Spellcaster Bridge] timeline import failed: {e}",
                      file=sys.stderr)
        elif kind == "resolve.playhead.send_to_peer":
            # Audit tier-1: Resolve-to-peer outbound. Grabs the current
            # playhead frame, uploads it to the Guild's asset gallery,
            # then publishes <target>.asset.send so the target plugin's
            # existing subscriber (GIMP inbox puller, DT inbox button,
            # ST /cross/inbox, etc.) ingests it. Payload: {target:
            # "gimp"|"darktable"|"sillytavern"}. This closes the
            # Resolve→GIMP / Resolve→ST / Resolve→DT gaps identified in
            # AUDIT_CROSS_APP_DEEP.md §4.
            try:
                self._handle_playhead_send_to_peer(evt)
            except Exception as e:
                print(f"[Spellcaster Bridge] send_to_peer failed: {e}",
                      file=sys.stderr)

    # ── Audit tier-1: Resolve → peer outbound transport ──────────────

    _SEND_TARGETS = frozenset({"gimp", "darktable", "sillytavern"})

    def _handle_playhead_send_to_peer(self, evt: dict):
        """Capture the current Resolve playhead frame, upload it to the
        Guild as a canonical asset, then publish <target>.asset.send so
        the target plugin ingests the image from its own inbox.

        This is the Send-to-X equivalent for Resolve — the other
        direction from R122's grab-into-shot. Used by the
        Cinematographer wizard's "Send frame to GIMP / ST / DT" chips.

        Event payload:
            {target: "gimp"|"darktable"|"sillytavern", title?: str}
        """
        import os
        data = evt.get("data") or {}
        target = (data.get("target") or "").strip().lower()
        if target not in self._SEND_TARGETS:
            self._publish_send_done({
                "error": f"unsupported target: {target!r} "
                         f"(expected one of {sorted(self._SEND_TARGETS)})"})
            return
        try:
            from resolve_helpers import capture_frame_at_playhead  # type: ignore
        except ImportError:
            self._publish_send_done({
                "error": "resolve_helpers not available in this environment"})
            return
        png_path = capture_frame_at_playhead()
        if not png_path or not os.path.isfile(png_path):
            self._publish_send_done({
                "target": target,
                "error": ("Couldn't grab a still at the playhead. "
                          "Switch to the Color page and retry.")})
            return
        try:
            with open(png_path, "rb") as f:
                png_bytes = f.read()
        except OSError as e:
            self._publish_send_done({
                "target": target, "error": f"read failed: {e}"})
            return
        finally:
            try:
                os.unlink(png_path)
            except Exception:
                pass
        # Upload via the Guild so it lands in the canonical asset
        # gallery — the receiving plugin fetches by hash. This also
        # keeps the event/mailbox path identical to GIMP/DT sends so
        # subscriber code on the other side doesn't branch on origin.
        try:
            asset_url, asset_hash = self._upload_via_guild(
                png_bytes, title=data.get("title") or "From Resolve")
        except Exception as e:
            self._publish_send_done({
                "target": target, "error": f"upload failed: {e}"})
            return
        try:
            self.guild._post_json("/api/events/emit", {
                "kind": f"{target}.asset.send",
                "origin": "resolve",
                "data": {
                    "image_url": asset_url,
                    "hash": asset_hash,
                    "source": "resolve",
                    "kind": "generation",
                },
            }, timeout=5.0)
        except Exception as e:
            self._publish_send_done({
                "target": target, "error": f"publish failed: {e}"})
            return
        self.sync._log(f"Resolve → {target}: {asset_hash[:8]}")
        self._publish_send_done({
            "ok": True, "target": target,
            "hash": asset_hash, "size_bytes": len(png_bytes)})

    def _upload_via_guild(self, png_bytes, title=""):
        """POST bytes to the Guild's /api/assets endpoint. Returns
        (asset_url, hash). Raises on any non-success."""
        import base64 as _b64
        body = json.dumps({
            "body_b64": _b64.b64encode(png_bytes).decode("ascii"),
            "kind": "generation",
            "origin": "resolve",
            "title": title,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.guild.base_url}/api/assets",
            data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        h = payload.get("hash")
        if not h:
            raise RuntimeError(f"Guild rejected asset: {payload}")
        return f"/api/assets/{h}", h

    def _publish_send_done(self, data: dict):
        """Result echo for UI feedback — Cinematographer or other
        callers can subscribe to resolve.send_to_peer.done."""
        try:
            self.guild._post_json("/api/events/emit", {
                "kind": "resolve.send_to_peer.done",
                "origin": "resolve",
                "data": data,
            }, timeout=5.0)
        except Exception:
            pass

    # ── R122: bus-triggered Resolve actions ──────────────────────────

    def _handle_playhead_grab(self, evt: dict):
        """Capture the current Resolve playhead frame and create a
        draft Shot on the Guild with the frame as reference_png.

        Chain:
          1. resolve_helpers.capture_frame_at_playhead → PNG bytes
          2. GuildClient.create_shot(reference_png=...) → shot dict
          3. publish resolve.playhead.ready with shot_id so the
             Cinematographer can acknowledge the new entry on its
             next turn.

        Creating the shot directly (rather than a bare asset upload)
        means the user sees the new entry immediately in the
        Shotboard — no second round-trip needed to attach the
        reference.
        """
        import os
        try:
            from resolve_helpers import capture_frame_at_playhead  # type: ignore
            from spellcaster_api import GuildError  # type: ignore
        except ImportError:
            return
        png_path = capture_frame_at_playhead()
        if not png_path or not os.path.isfile(png_path):
            self._publish_resolve_ready({
                "error": ("Couldn't grab a still at the playhead. "
                           "Switch to the Color page and retry.")})
            return
        try:
            with open(png_path, "rb") as f:
                png_bytes = f.read()
        except OSError as e:
            self._publish_resolve_ready({"error": f"read failed: {e}"})
            return
        finally:
            try:
                os.unlink(png_path)
            except Exception:
                pass
        try:
            shot = self.guild.create_shot(
                title="Playhead grab (Cinematographer)",
                prompt="",
                preset="wan22_i2v_lightning",
                reference_png=png_bytes,
                notes=("Cinematographer wizard requested a playhead "
                        "grab from Resolve. Edit the prompt + queue "
                        "the shot to render."),
            )
        except GuildError as e:
            self._publish_resolve_ready({"error": f"create_shot failed: {e}"})
            return
        shot_id = (shot or {}).get("id") or (shot or {}).get("shot_id") or ""
        if not shot_id:
            self._publish_resolve_ready(
                {"error": "Guild didn't return a shot id"})
            return
        self.sync._log(
            f"Cinema playhead grab → new shot {shot_id[:8]}")
        self._publish_resolve_ready({
            "ok": True,
            "shot_id": shot_id,
            "size_bytes": len(png_bytes),
        })

    def _handle_timeline_import(self, evt: dict):
        """Fetch the Guild's shotboard as an EDL and import it as a
        new Resolve timeline."""
        import os
        import tempfile
        import urllib.request as _ur
        # Use the project's framerate if we can; default 24.
        fps = 24
        try:
            from resolve_helpers import (  # type: ignore
                get_current_project, get_media_pool,
            )
            proj = get_current_project()
            if proj:
                try:
                    fps = int(float(proj.GetSetting("timelineFrameRate") or 24))
                except Exception:
                    fps = 24
            mp = get_media_pool()
        except ImportError:
            proj, mp = None, None
        if not mp:
            self._publish_timeline_imported({
                "error": "no active Resolve project"})
            return
        url = f"{self.guild.base_url}/api/video/export/edl?fps={fps}"
        try:
            req = _ur.Request(url, headers={"Accept": "text/plain"})
            with _ur.urlopen(req, timeout=30) as resp:
                edl_bytes = resp.read()
        except Exception as e:
            self._publish_timeline_imported({
                "error": f"EDL fetch failed: {e}"})
            return
        edl_text = edl_bytes.decode("utf-8", errors="replace")
        if not edl_text.strip():
            self._publish_timeline_imported({
                "error": "Guild returned an empty EDL — render some shots first."})
            return
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".edl",
            prefix="spellcaster_cinema_",
            mode="w", encoding="utf-8")
        tmp.write(edl_text)
        tmp_path = tmp.name
        tmp.close()
        try:
            timeline = mp.ImportTimelineFromFile(tmp_path)
        except Exception as e:
            self._publish_timeline_imported({
                "error": f"ImportTimelineFromFile raised: {e}",
                "edl_path": tmp_path})
            return
        if not timeline:
            self._publish_timeline_imported({
                "error": "Resolve returned no timeline",
                "edl_path": tmp_path})
            return
        try:
            tl_name = timeline.GetName()
        except Exception:
            tl_name = "Spellcaster"
        self.sync._log(f"Cinema imported timeline: {tl_name}")
        self._publish_timeline_imported({
            "ok": True,
            "timeline_name": tl_name,
        })

    def _publish_resolve_ready(self, data: dict):
        """Best-effort publish of resolve.playhead.ready. Wraps the
        Guild's /api/events/emit. Silent on failure — the Bridge log
        has enough detail already."""
        try:
            self.guild._post_json("/api/events/emit", {
                "kind": "resolve.playhead.ready",
                "origin": "resolve",
                "data": data,
            }, timeout=5.0)
        except Exception:
            pass

    def _publish_timeline_imported(self, data: dict):
        try:
            self.guild._post_json("/api/events/emit", {
                "kind": "resolve.timeline.imported",
                "origin": "resolve",
                "data": data,
            }, timeout=5.0)
        except Exception:
            pass

    def _ingest_external_image(self, image_url: str, evt: dict):
        """Download an asset from the Guild and hand to MediaPoolSync.

        R105: absolute URLs are used as-is. Relative paths are
        prepended with the Bridge's own Guild base_url — this is
        essential when the publisher (e.g. GIMP on a different host)
        doesn't know the LAN URL the Bridge uses to reach the Guild.
        """
        if image_url.startswith("/"):
            image_url = self.guild.base_url.rstrip("/") + image_url
        # Scheme clamp — the Guild's event bus is unauthenticated on
        # localhost. Without this, any interface with publish access
        # could smuggle file:/// or gopher:// URLs that urllib dutifully
        # follows, reading arbitrary local files into the Resolve cache.
        import urllib.parse
        try:
            scheme = urllib.parse.urlparse(image_url).scheme.lower()
        except Exception:
            scheme = ""
        if scheme not in ("http", "https"):
            print(f"[Spellcaster Bridge] rejected non-http ingest url: "
                  f"{image_url[:80]}", file=sys.stderr)
            return
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
        import urllib.request as _ur
        from resolve_helpers import import_video  # type: ignore
        dest = os.path.join(self.sync._cache_dir,
                            f"{shot_stub['id']}.png")
        # 200 MB ceiling on asset downloads — matches the Guild's own
        # outgoing video cap and keeps a hostile/truncated response from
        # pinning Resolve's RAM.
        MAX_INGEST_BYTES = 200 * 1024 * 1024
        try:
            with _ur.urlopen(image_url, timeout=30.0) as r:
                data = r.read(MAX_INGEST_BYTES + 1)
            if len(data) > MAX_INGEST_BYTES:
                print(f"[Spellcaster Bridge] ingest exceeded "
                      f"{MAX_INGEST_BYTES} bytes; rejected.",
                      file=sys.stderr)
                return
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
