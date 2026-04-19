"""Spellcaster Guild HTTP client — shared by every Resolve plugin.

Zero third-party dependencies (stdlib only) so it works inside Resolve's
bundled Python without the user installing anything. If a Resolve script
runs with a Python that has `requests`, great — we fall through to stdlib.

Every plugin imports from here:

    from spellcaster_api import GuildClient
    guild = GuildClient()        # auto-discovers from config + localhost
    shots = guild.list_shots()
    guild.create_shot(title="sunrise shot", prompt="...", reference=png_bytes)

Auth: none. The Guild is localhost-only. If we ever expose it on a LAN,
this is where a token header will live.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


# ─── Config resolution ──────────────────────────────────────────────────

_DEFAULT_PORTS = (7777, 7778, 7779)  # Guild may fall back if 7777 is busy
_CONFIG_FILENAME = "resolve_bridge.json"


def _config_path() -> str:
    """`~/.spellcaster/resolve_bridge.json` on every OS."""
    return os.path.join(os.path.expanduser("~"), ".spellcaster", _CONFIG_FILENAME)


def load_config() -> dict:
    """Load the plugin's config file, returning {} if missing/invalid."""
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict) -> bool:
    """Atomic-ish write of the config file. Returns True on success."""
    path = _config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def discover_guild_url(probe_timeout: float = 0.5) -> str | None:
    """Find a running Guild server by probing common localhost ports.

    Resolution order:
      1. `SPELLCASTER_GUILD_URL` environment variable
      2. `guild_url` key in config file
      3. Probe 127.0.0.1:7777 / 7778 / 7779 for a live /api/config

    Returns the base URL (no trailing slash) or None if nothing responds.
    """
    env = os.environ.get("SPELLCASTER_GUILD_URL")
    if env:
        return env.rstrip("/")

    cfg_url = load_config().get("guild_url")
    if cfg_url:
        return cfg_url.rstrip("/")

    for port in _DEFAULT_PORTS:
        url = f"http://127.0.0.1:{port}"
        if _port_is_open("127.0.0.1", port, probe_timeout):
            return url
    return None


def _port_is_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# ─── HTTP client ────────────────────────────────────────────────────────


class GuildError(Exception):
    """Raised on any HTTP or transport failure."""


class GuildClient:
    """Stateless HTTP wrapper around the Guild's /api/video/* endpoints.

    Example:
        guild = GuildClient()               # auto-discover
        guild = GuildClient("http://host:7777")  # explicit
        if not guild.is_reachable():
            raise RuntimeError("Guild not running")
    """

    def __init__(self, base_url: str | None = None, timeout: float = 10.0):
        self.base_url = (base_url or discover_guild_url() or "http://127.0.0.1:7777").rstrip("/")
        self.timeout = timeout

    # ── Low-level ────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: bytes | None = None,
                 headers: dict | None = None, timeout: float | None = None) -> bytes:
        url = f"{self.base_url}{path}"
        hdrs = {"Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = str(e)
            raise GuildError(f"{method} {path} -> HTTP {e.code}: {err_body[:400]}")
        except urllib.error.URLError as e:
            raise GuildError(f"{method} {path} -> {e}")
        except Exception as e:
            raise GuildError(f"{method} {path} -> {e}")

    def _get_json(self, path: str, params: dict | None = None, timeout: float | None = None):
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        data = self._request("GET", path, timeout=timeout)
        return json.loads(data.decode("utf-8"))

    def _post_json(self, path: str, payload: dict, timeout: float | None = None):
        body = json.dumps(payload).encode("utf-8")
        data = self._request("POST", path, body=body,
                             headers={"Content-Type": "application/json"},
                             timeout=timeout)
        if not data:
            return {}
        return json.loads(data.decode("utf-8"))

    # ── Health & introspection ───────────────────────────────────────

    def is_reachable(self) -> bool:
        """Quick liveness check. Doesn't raise — returns bool."""
        try:
            self._get_json("/api/config", timeout=2.0)
            return True
        except Exception:
            return False

    def video_health(self) -> dict:
        """Backend status: WanGP reachable, ComfyUI reachable, queue counts."""
        return self._get_json("/api/video/health")

    def config(self) -> dict:
        return self._get_json("/api/config")

    # ── Shotboard CRUD ───────────────────────────────────────────────

    def list_shots(self) -> list:
        """All shots in order. Each shot is a dict with id, title, status, etc."""
        d = self._get_json("/api/video/shots")
        # The Guild returns either a list or {shots: [...]} — handle both
        if isinstance(d, list):
            return d
        return d.get("shots", [])

    def get_shot(self, shot_id: str) -> dict | None:
        for s in self.list_shots():
            if s.get("id") == shot_id:
                return s
        return None

    def create_shot(self, *, title: str = "", prompt: str = "",
                    preset: str | None = None, backend: str | None = None,
                    reference_png: bytes | None = None,
                    negative: str = "", seed: int | None = None,
                    notes: str = "", extras: dict | None = None) -> dict:
        """Create a draft shot. Optionally attach a reference image in one call.

        The reference is uploaded via /api/video/shots/{id}/reference after
        the shot exists — same order as the Guild's own UI flow.
        """
        payload: dict = {
            "title": title,
            "prompt": prompt,
            "negative": negative,
            "notes": notes,
        }
        if preset is not None:
            payload["preset"] = preset
        if backend is not None:
            payload["backend"] = backend
        if seed is not None:
            payload["seed"] = seed
        if extras:
            payload.update(extras)

        shot = self._post_json("/api/video/shots", payload)
        shot_id = shot.get("id") or shot.get("shot_id")
        if reference_png and shot_id:
            self.attach_reference(shot_id, reference_png)
        return shot

    def update_shot(self, shot_id: str, **fields) -> dict:
        return self._post_json(f"/api/video/shots/{shot_id}/update", fields)

    def delete_shot(self, shot_id: str) -> bool:
        try:
            self._post_json(f"/api/video/shots/{shot_id}/delete", {})
            return True
        except GuildError:
            return False

    def clone_shot(self, shot_id: str, prompt_variation: str = "") -> dict:
        return self._post_json(f"/api/video/shots/{shot_id}/clone",
                               {"prompt_variation": prompt_variation})

    # ── Attachments ──────────────────────────────────────────────────

    def attach_reference(self, shot_id: str, png_bytes: bytes) -> dict:
        """Upload a reference image as base64 — matches the Guild UI contract."""
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return self._post_json(f"/api/video/shots/{shot_id}/reference",
                               {"image_b64": b64})

    def set_trajectories(self, shot_id: str, trajectories: list) -> dict:
        """Each trajectory: {points: [[x,y], ...], color: '#rrggbb'}."""
        return self._post_json(f"/api/video/shots/{shot_id}/trajectories",
                               {"trajectories": trajectories})

    # ── Rendering ────────────────────────────────────────────────────
    #
    # The Guild does NOT expose a per-shot `/render` endpoint today.
    # Rendering is triggered by `/api/video/render-all` (queues every
    # draft shot) or implicitly through the chat-driven
    # CinematographerWizard. For single-shot queueing from a plugin we
    # mark the shot as ready-to-render by bumping its status to
    # "queued" via /update and then calling render-all, which picks up
    # any draft/queued shots that have carry_last_frame=False satisfied.

    def queue_shot(self, shot_id: str) -> dict:
        """Queue a single shot for rendering.

        Flips status to queued via /update, then calls render-all so
        the video bridge picks it up on its next tick. Safe to call
        multiple times — the video bridge de-dupes.
        """
        try:
            self.update_shot(shot_id, status="queued")
        except GuildError:
            # If the server rejects the status bump, fall through — the
            # render-all sweep still picks up drafts
            pass
        return self._post_json("/api/video/render-all", {})

    # Back-compat alias — older callers used `render_shot`
    render_shot = queue_shot

    def render_all_drafts(self) -> dict:
        return self._post_json("/api/video/render-all", {})

    def cancel_shot(self, shot_id: str) -> dict:
        return self._post_json(f"/api/video/shots/{shot_id}/cancel", {})

    def queue_status(self) -> dict:
        return self._get_json("/api/video/queue/status")

    # ── Presets ──────────────────────────────────────────────────────

    def list_presets(self) -> list:
        """All WanGP/ComfyUI presets available for shot creation.

        Normalizes every shape the Guild has exposed over time:
          1. [{key, label, task, ...}, ...]       — list of records
          2. {"presets": [...]}                    — wrapped list
          3. {"presets": {key: record, ...}}       — dict-of-records (current)
          4. {key: record, ...}                    — bare dict

        Always returns a list of records, each with a `key` field
        populated so callers can match presets by name.
        """
        d = self._get_json("/api/video/presets")
        # Unwrap {"presets": ...} if present
        if isinstance(d, dict) and "presets" in d:
            d = d["presets"]
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            out = []
            for k, rec in d.items():
                if isinstance(rec, dict):
                    # Inject the dict key as `key` so matching works
                    r = dict(rec)
                    r.setdefault("key", k)
                    out.append(r)
                else:
                    out.append({"key": k, "label": str(rec)})
            return out
        return []

    # ── Media download ───────────────────────────────────────────────

    def download_shot_video(self, shot_id: str, dest_path: str) -> bool:
        """Stream a rendered video to a local file. Returns True on success."""
        try:
            data = self._request("GET", f"/api/video/shots/{shot_id}/video",
                                 timeout=60.0)
            with open(dest_path, "wb") as f:
                f.write(data)
            return True
        except GuildError:
            return False

    def download_shot_reference(self, shot_id: str, dest_path: str) -> bool:
        try:
            data = self._request("GET", f"/api/video/shots/{shot_id}/reference",
                                 timeout=15.0)
            with open(dest_path, "wb") as f:
                f.write(data)
            return True
        except GuildError:
            return False

    # ── SSE subscription (connection only; callers iterate) ──────────

    def open_event_stream(self):
        """Open a streaming connection to /api/video/events.

        Returns an iterator yielding parsed event dicts, or None on failure.
        The caller is responsible for closing the underlying response.

        This is a generator-style helper — safe to use in a background
        thread. Each yielded value is {"event": str, "data": dict}.
        """
        url = f"{self.base_url}/api/video/events"
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        resp = urllib.request.urlopen(req, timeout=30.0)
        return _iter_sse(resp)


def _iter_sse(resp):
    """Parse an SSE response into {event, data} dicts as they arrive."""
    event_name = "message"
    data_buf: list[str] = []
    try:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                # Flush current event
                if data_buf:
                    raw_data = "\n".join(data_buf)
                    try:
                        parsed = json.loads(raw_data)
                    except Exception:
                        parsed = {"raw": raw_data}
                    yield {"event": event_name, "data": parsed, "ts": time.time()}
                event_name = "message"
                data_buf = []
                continue
            if line.startswith(":"):
                # SSE comment / keepalive
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_buf.append(line[5:].lstrip())
            # other fields (id:, retry:) ignored
    finally:
        try:
            resp.close()
        except Exception:
            pass
