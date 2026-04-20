"""Cross-Interface Client — thin helpers every frontend imports.

Usage from any plugin (GIMP, Darktable, Resolve, etc):

    from spellcaster_core.cross_interface import CrossInterfaceClient
    client = CrossInterfaceClient(interface_key="gimp")

    # Announce liveness (call every 10s)
    client.heartbeat()

    # Publish an event
    client.publish("gimp.generation.finished",
                   data={"prompt": "a cat", "model": "sdxl"})

    # Upload an asset
    rec = client.upload_asset(png_bytes, kind="generation",
                              prompt="a cat", model="sdxl")

    # Subscribe to events from other interfaces
    for evt in client.subscribe(kinds=["resolve.", "guild."]):
        print(evt)

The client falls silent (returns None / no-ops) when the Guild server
is unreachable — never raises to the caller. Plugins can wrap-and-
forget without any try/except gymnastics.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterator, Optional


_DEFAULT_GUILD_URL = "http://127.0.0.1:7777"
_HEARTBEAT_INTERVAL_S = 10.0


def resolve_guild_url() -> str:
    """Find a running Guild. Same logic as the Resolve plugin's
    spellcaster_api.discover_guild_url — duplicated here so this
    module has zero imports from outside spellcaster_core."""
    env = os.environ.get("SPELLCASTER_GUILD_URL")
    if env:
        return env.rstrip("/")
    cfg_path = os.path.join(os.path.expanduser("~"), ".spellcaster",
                            "cross_interface.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        u = data.get("guild_url")
        if u:
            return str(u).rstrip("/")
    except Exception:
        pass
    return _DEFAULT_GUILD_URL


# ── Low-level HTTP primitives (no external deps) ──────────────────────


def _http_json(method: str, url: str, payload: Optional[dict] = None,
               timeout: float = 5.0) -> Optional[dict]:
    try:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


# ── Client ───────────────────────────────────────────────────────────


class CrossInterfaceClient:
    """Thin wrapper around the Guild's cross-interface endpoints.

    Args:
        interface_key: `gimp` / `darktable` / `resolve` / `sillytavern` /
            `signal` / `guild`. Used as the `origin` on every event + asset.
        guild_url: Override the auto-discovered Guild URL.
        auto_heartbeat: If True (default), spawn a daemon thread that
            pings /api/interfaces/heartbeat every 10 s until the client
            is garbage-collected.
    """

    def __init__(self, interface_key: str,
                 guild_url: Optional[str] = None,
                 auto_heartbeat: bool = True):
        self.key = interface_key
        self.base_url = (guild_url or resolve_guild_url()).rstrip("/")
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_stop = threading.Event()
        self._last_meta: dict = {}
        if auto_heartbeat:
            self.start_auto_heartbeat()

    # ── Liveness ────────────────────────────────────────────────────

    def is_reachable(self) -> bool:
        return _http_json("GET", f"{self.base_url}/api/config", timeout=2.0) is not None

    def heartbeat(self, meta: Optional[dict] = None) -> bool:
        """Tell the Guild "I am alive". Plugins should call this every
        ~10s while their host app is open. `meta` is free-form — e.g.
        GIMP can pass `{active_doc: "portrait.xcf"}`."""
        if meta is None:
            meta = self._last_meta
        else:
            self._last_meta = dict(meta)
        r = _http_json("POST", f"{self.base_url}/api/interfaces/heartbeat",
                       {"interface": self.key, "meta": meta}, timeout=3.0)
        return r is not None

    def start_auto_heartbeat(self):
        """Background thread that heartbeats every _HEARTBEAT_INTERVAL_S."""
        if self._hb_thread and self._hb_thread.is_alive():
            return
        self._hb_stop.clear()

        def _loop():
            # First heartbeat immediate, so the Guild registers us now
            self.heartbeat()
            while not self._hb_stop.wait(_HEARTBEAT_INTERVAL_S):
                try:
                    self.heartbeat()
                except Exception:
                    pass

        self._hb_thread = threading.Thread(
            target=_loop, daemon=True,
            name=f"spellcaster-heartbeat-{self.key}")
        self._hb_thread.start()

    def stop_auto_heartbeat(self):
        self._hb_stop.set()

    # ── Events ───────────────────────────────────────────────────────

    def publish(self, kind: str, data: Optional[dict] = None) -> Optional[dict]:
        """Publish an event to the cross-interface bus. Returns the
        server-assigned event dict, or None on failure."""
        r = _http_json("POST", f"{self.base_url}/api/events/emit",
                       {"kind": kind, "origin": self.key, "data": dict(data or {})},
                       timeout=3.0)
        return r

    def recent_events(self, *, limit: int = 50,
                      kinds: Optional[list[str]] = None,
                      origins: Optional[list[str]] = None,
                      since_ts: float = 0.0) -> list[dict]:
        params = {"limit": str(limit), "since": str(since_ts)}
        if kinds:
            params["kinds"] = ",".join(kinds)
        if origins:
            params["origins"] = ",".join(origins)
        url = f"{self.base_url}/api/events?{urllib.parse.urlencode(params)}"
        r = _http_json("GET", url, timeout=5.0)
        if isinstance(r, dict):
            return list(r.get("events", []))
        if isinstance(r, list):
            return r
        return []

    def subscribe(self, *, kinds: Optional[list[str]] = None,
                  origins: Optional[list[str]] = None,
                  on_event: Optional[Callable[[dict], None]] = None,
                  timeout: float = 0.0) -> Iterator[dict]:
        """SSE subscription. Yields events as they arrive. Returns when
        the connection closes or `timeout` seconds pass with no events.

        If `on_event` is given, run the loop inline (no yield); return
        when done.
        """
        params = {}
        if kinds:
            params["kinds"] = ",".join(kinds)
        if origins:
            params["origins"] = ",".join(origins)
        qs = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{self.base_url}/api/events/stream{qs}"
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "text/event-stream"})
            resp = urllib.request.urlopen(req, timeout=timeout or 30.0)
        except Exception:
            return

        try:
            event_name = "message"
            data_buf: list[str] = []
            for raw in resp:
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
                            parsed = {"raw": joined}
                        evt = {"kind": event_name, **parsed}
                        if on_event:
                            try:
                                on_event(evt)
                            except Exception:
                                pass
                        else:
                            yield evt
                    event_name = "message"
                    data_buf = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_buf.append(line[5:].lstrip())
        except Exception:
            return
        finally:
            try:
                resp.close()
            except Exception:
                pass

    # ── Asset gallery ────────────────────────────────────────────────

    def upload_asset(self, data: bytes, *, kind: str = "generation",
                     title: str = "", prompt: str = "", model: str = "",
                     seed: Optional[int] = None,
                     ext: Optional[str] = None,
                     tags: Optional[list[str]] = None,
                     meta: Optional[dict] = None) -> Optional[dict]:
        """Upload a blob to the shared gallery. Returns the AssetRecord
        dict (with hash, ext, size, ts) or None on failure."""
        if not data:
            return None
        b64 = base64.b64encode(data).decode("ascii")
        payload = {
            "origin": self.key,
            "kind": kind,
            "title": title,
            "prompt": prompt,
            "model": model,
            "ext": ext,
            "tags": list(tags or []),
            "meta": dict(meta or {}),
            "body_b64": b64,
        }
        if seed is not None:
            payload["seed"] = int(seed)
        return _http_json("POST", f"{self.base_url}/api/assets",
                          payload, timeout=30.0)

    def list_assets(self, *, limit: int = 20,
                    origins: Optional[list[str]] = None,
                    kinds: Optional[list[str]] = None,
                    active_only: bool = True) -> list[dict]:
        """List recent assets. By default filters to origins the Guild
        reports as active (so uninstalled tools don't clutter the
        gallery)."""
        params = {"limit": str(limit)}
        if origins:
            params["origins"] = ",".join(origins)
        if kinds:
            params["kinds"] = ",".join(kinds)
        if active_only:
            params["active_only"] = "1"
        url = f"{self.base_url}/api/assets?{urllib.parse.urlencode(params)}"
        r = _http_json("GET", url, timeout=5.0)
        if isinstance(r, dict):
            return list(r.get("assets", []))
        if isinstance(r, list):
            return r
        return []

    def download_asset(self, h: str) -> Optional[bytes]:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/assets/{h}")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return resp.read()
        except Exception:
            return None

    # ── ComfyUI blob bus (Guild-less asset transport) ────────────────
    #
    # The Guild's AssetGallery is the canonical persistent store, but
    # every plugin also talks to ComfyUI directly. When the Guild is
    # down OR when the transport shouldn't go through the Guild at all
    # (LAN handoff between plugins on different machines), use these
    # helpers — they put bytes on ComfyUI's /spellcaster/blob/* routes
    # instead. TTL-based eviction keeps the store bounded (1 h default,
    # 24 h max per blob). Returns {hash, url, …} on success.

    def blob_put(self, comfy_url: str, data: bytes, *,
                 kind: str = "generation", ttl_s: Optional[float] = None,
                 timeout: float = 30.0) -> Optional[dict]:
        """POST bytes to a ComfyUI's blob bus. Returns the record dict
        (hash, url, size, kind, origin, mime, expires_at) or None on
        failure. Use the returned `url` — it's absolute and LAN-
        reachable so peers on other machines can GET it directly."""
        if not data or not comfy_url:
            return None
        url = f"{comfy_url.rstrip('/')}/spellcaster/blob/put"
        # We build a minimal multipart body by hand to avoid pulling
        # in requests/aiohttp. The boundary is random-ish per call.
        import os as _os
        boundary = "----spellcasterBlob" + _os.urandom(8).hex()
        parts: list[bytes] = []

        def _field(name: str, value: str):
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            parts.append(value.encode("utf-8"))
            parts.append(b"\r\n")

        _field("kind", kind)
        _field("origin", self.key)
        if ttl_s is not None:
            _field("ttl_s", str(float(ttl_s)))
        # File part
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            b'Content-Disposition: form-data; name="file"; filename="blob.bin"\r\n'
            b'Content-Type: application/octet-stream\r\n\r\n')
        parts.append(bytes(data))
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def blob_get(self, url: str,
                 timeout: float = 30.0) -> Optional[bytes]:
        """GET raw bytes from a blob bus URL. The URL is typically
        returned by blob_put and points at a ComfyUI instance (not the
        Guild). Returns None on failure."""
        if not url:
            return None
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            return None

    def blob_list(self, comfy_url: str,
                  timeout: float = 3.0) -> list[dict]:
        """List every live blob on a ComfyUI's bus. Useful for UIs
        that want to show 'recent cross-app assets in flight'."""
        if not comfy_url:
            return []
        url = f"{comfy_url.rstrip('/')}/spellcaster/blob/list"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict):
                return list(data.get("blobs", []))
        except Exception:
            pass
        return []

    # ── Introspection ────────────────────────────────────────────────

    def active_interfaces(self) -> list[str]:
        """Keys of interfaces the Guild reports as active RIGHT NOW.
        Use this before rendering any 'send to X' chip so dead
        interfaces don't pollute the UI."""
        r = _http_json("GET", f"{self.base_url}/api/interfaces", timeout=3.0)
        if not r:
            return []
        ifaces = r.get("interfaces", {})
        return [k for k, v in ifaces.items()
                if v.get("installed") and v.get("enabled") and v.get("online")]

    def interface_state(self) -> dict:
        r = _http_json("GET", f"{self.base_url}/api/interfaces", timeout=3.0)
        return r or {}
