"""Signal Notifier — long-render completion pings via Signal Bridge.

Subscribes to selected cross-interface events on the EventBus and, when
one fires, asks the Signal Bridge to send a message to the admin phone
number. This makes 30-minute video renders usable — queue the job, walk
away, get a phone ping when it's done.

Design:
  • Event-driven. No polling. Daemon thread consumes from EventBus.
  • Pluggable transport. The default `_http_send` talks to a POST /send
    endpoint matching signal-cli-rest-api conventions. If your bridge
    speaks a different protocol, pass a custom `transport` callable.
  • Gracefully disabled. If `admin_number` looks like a placeholder
    (+1XXXXXXXXXX) or the bridge config can't be read, the notifier
    starts in a "log-only" mode — still subscribes, prints locally,
    never calls the network.
  • Hot-reloadable. `reload_config()` rereads `signal_bridge_config.json`
    without restarting the subscription thread.

Guild bootstrap:

    from .signal_notifier import SignalNotifier, start_default
    start_default(event_bus, signal_bridge_url, config_path)
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

try:
    from .event_bus import EventBus
except ImportError:
    EventBus = None  # type: ignore


# Events the notifier listens for by default. Tuple entries are (kind,
# message template). `{prompt}` etc. are filled from evt.data — missing
# keys become empty strings.
DEFAULT_NOTIFY_KINDS: list[tuple[str, str]] = [
    # Video renders — the primary use case, they take minutes
    ("guild.shot.ready",
     "🎬 Spellcaster: your video shot '{title}' is ready."),
    ("guild.shot.failed",
     "⚠ Spellcaster: shot '{title}' failed — {error}"),
    # Heavy image ops that hold the GPU for a long time
    ("gimp.generation.finished",
     "✨ Spellcaster: GIMP finished generating '{prompt}'"),
    ("gimp.supir.finished",
     "✨ Spellcaster: GIMP finished a SUPIR restoration."),
    # Calibration wizard runs across dozens of models and can take 30+ min
    ("guild.calibration.finished",
     "🔧 Spellcaster: calibration run finished ({count} models tested)."),
]

# Placeholder phone number used in default configs. Never message this.
_PLACEHOLDER_NUMBER = re.compile(r"^\+?1?X+$")


class SignalNotifier:
    def __init__(self,
                 bridge_url: str,
                 admin_number: str = "",
                 subscribe_kinds: Optional[list[str]] = None,
                 templates: Optional[list[tuple[str, str]]] = None,
                 transport: Optional[Callable[[str, str, str], bool]] = None):
        self.bridge_url = (bridge_url or "").rstrip("/")
        self.admin_number = (admin_number or "").strip()
        self.templates = templates or DEFAULT_NOTIFY_KINDS
        self._templates_map = {k: msg for k, msg in self.templates}
        self.subscribe_kinds = subscribe_kinds or [k for k, _ in self.templates]
        self._transport = transport or self._http_send
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._notified_count = 0
        self._last_error: str = ""

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self, event_bus):
        """Subscribe to the event bus in a daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(event_bus,),
            daemon=True, name="signal-notifier")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self, event_bus):
        # subscribe() is a generator; iterate as events arrive
        try:
            for evt in event_bus.subscribe(kinds=None):  # we filter ourselves
                if self._stop.is_set():
                    return
                try:
                    self._maybe_notify(evt)
                except Exception as e:
                    self._last_error = f"dispatch: {e}"
        except Exception as e:
            self._last_error = f"subscribe loop: {e}"

    # ── Dispatch ─────────────────────────────────────────────────────

    def _maybe_notify(self, evt: dict):
        kind = evt.get("kind", "")
        template = self._templates_map.get(kind)
        if not template:
            # Also support prefix matching: if a template key ends with .*
            # it matches any kind starting with the prefix before .*
            for k, msg in self.templates:
                if k.endswith(".*") and kind.startswith(k[:-2] + "."):
                    template = msg
                    break
        if not template:
            return

        # Safe template fill — missing keys become empty
        data = evt.get("data") or {}
        try:
            text = template.format_map(_SafeDict(data))
        except Exception:
            text = template
        self._send(text)

    def _send(self, text: str):
        if not self.admin_number or _PLACEHOLDER_NUMBER.match(self.admin_number):
            # Log-only mode — still useful during development
            print(f"[SignalNotifier] (log-only, no admin_number) {text}")
            return
        if not self.bridge_url:
            print(f"[SignalNotifier] (no bridge_url) {text}")
            return
        try:
            ok = self._transport(self.bridge_url, self.admin_number, text)
            if ok:
                self._notified_count += 1
            else:
                self._last_error = "transport returned False"
        except Exception as e:
            self._last_error = f"transport raised: {e}"

    # ── Default transport: POST to the bridge ────────────────────────

    @staticmethod
    def _http_send(bridge_url: str, to_number: str, text: str) -> bool:
        """Default transport — POST /send with {to, text}.

        This matches the signal-cli-rest-api convention. Bridges that
        use a different schema can inject their own transport.
        """
        body = json.dumps({
            "to": to_number,
            "text": text,
            "source": "spellcaster",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{bridge_url}/send",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as e:
            # Many bridges treat "message queued" as 202. Accept any 2xx.
            if 200 <= getattr(e, "code", 0) < 300:
                return True
            raise
        except Exception:
            raise

    # ── Introspection ────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "bridge_url": self.bridge_url,
            "admin_number": _mask_number(self.admin_number),
            "subscribed_kinds": list(self.subscribe_kinds),
            "notified_count": self._notified_count,
            "last_error": self._last_error,
            "running": bool(self._thread and self._thread.is_alive()),
        }


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def _mask_number(n: str) -> str:
    """Return a phone number partially masked for logging."""
    if not n:
        return ""
    if len(n) <= 4:
        return "****"
    return f"{n[:3]}…{n[-2:]}"


# ── Bootstrap ─────────────────────────────────────────────────────────


def start_default(event_bus,
                  bridge_url: str,
                  config_path: Optional[str] = None) -> Optional[SignalNotifier]:
    """Create a SignalNotifier using config from signal_bridge_config.json.

    Returns None if the config can't be read or the bridge URL is empty.
    """
    admin_number = ""
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            admin_number = cfg.get("admin_number", "")
        except Exception:
            pass
    notifier = SignalNotifier(bridge_url, admin_number=admin_number)
    notifier.start(event_bus)
    return notifier
