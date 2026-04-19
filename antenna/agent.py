"""Spellcaster antenna HTTPS server.

Single process, stdlib-only. Reads config + token + cert via config.py,
wraps a ThreadingHTTPServer in TLS, routes requests to endpoint modules.

Request lifecycle
-----------------
    HTTPS request
       │
       ▼
    _AntennaHandler.do_GET/do_POST
       │
       ▼
    [1] Rate limiter (by remote IP)       — 429 if exceeded
    [2] Route match (exact path → handler)— 404 if unknown
    [3] Auth check (unless endpoint is    — 401 if invalid
        in _UNAUTHENTICATED_PATHS)
    [4] Dispatch to endpoint handler
    [5] Audit log entry written
    [6] JSON response sent

Endpoint handlers are plain functions in antenna/endpoints/*.py. They
receive a dict of {method, path, headers, body, client_ip, config} and
return (status_code, response_body_dict).

Why ThreadingHTTPServer
-----------------------
Even a home-lab antenna gets multiple near-simultaneous requests from
one client (status poll, list models, check install state). Forking
would be overkill on Windows; threading is the sweet spot for stdlib.
Each request runs on its own thread, so a slow git-clone in one thread
doesn't block a status poll in another.

Graceful shutdown
-----------------
SIGINT / Ctrl-C triggers server.shutdown() on the main thread. In-flight
requests finish, then the server exits. Rate-limiter state is lost on
exit (intentional — a restart resets any temporary soft-bans).
"""
from __future__ import annotations

import json
import os
import signal
import socketserver
import ssl
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from . import __version__, auth, config, heartbeat


# ─── Routing table ───────────────────────────────────────────────────────
# Endpoint modules are lazily imported inside _build_routes() so that
# optional services (llm, resolve) don't load if this antenna doesn't
# declare them. Keeps import-time clean and failure modes per-service.

# Endpoints that skip token auth (but still rate-limited).
#
# /pair/claim is unauthenticated BY DESIGN — it's how a Guild that
# doesn't yet have this antenna's bearer token gets one. Rate-limited
# at the normal RateLimiter cap, so brute-forcing the 6-digit code
# requires the attacker to also beat the limiter. Wrong codes count
# against the limit. See antenna/pairing.py for the lifecycle.
_UNAUTHENTICATED_PATHS: set[str] = {"/", "/pair/claim", "/pair/state"}


# R49a diagnostic: last run's result, readable via /status for debugging.
# Populated by _autopopulate_services on every boot.
_LAST_AUTODETECT: dict[str, Any] = {"ran": False}

# R53+ diagnostic: what the pre-bind port reaper killed (if anything).
# Populated by serve() before the ThreadingHTTPServer() call.
_LAST_PORT_CLEANUP: list[dict[str, Any]] = []


# ── Notify hook — let a shell (tray.py on Windows) listen to events ──
# Anything in the antenna that wants the user to SEE something calls
# `notify(title, message, level='info')`. By default it's a no-op that
# prints to stdout; tray.py installs a real handler that surfaces a
# Windows toast. Keep it trivial — the hook is the only cross-module
# handshake between the agent and its optional shell.
_NOTIFY_SINKS: list = []


def register_notify_sink(fn) -> None:
    """Register a callable `fn(title: str, message: str, level: str)` that
    receives every antenna.notify() call. Tray.py registers itself here
    during startup; tests and console mode leave the list empty.
    """
    if callable(fn) and fn not in _NOTIFY_SINKS:
        _NOTIFY_SINKS.append(fn)


def notify(title: str, message: str = "", level: str = "info") -> None:
    """Push a user-visible event to every registered sink.

    level: 'info' | 'success' | 'warn' | 'error' — sinks may style on it.
    Swallows every exception: notification failures must never propagate.
    """
    # Always print so console mode still sees something useful.
    prefix = {"success": "+", "warn": "!", "error": "x"}.get(level, "i")
    try:
        print(f"[antenna/{level}] {prefix} {title}"
              + (f" — {message}" if message else ""))
    except Exception:  # noqa: BLE001
        pass
    for sink in list(_NOTIFY_SINKS):
        try:
            sink(title, message, level)
        except Exception as e:  # noqa: BLE001
            try:
                print(f"[antenna] notify sink {sink!r} raised: {e}",
                      file=sys.stderr)
            except Exception:  # noqa: BLE001
                pass


def _autopopulate_services(cfg: dict[str, Any]) -> None:
    """R49a: Merge auto-detected services into cfg['services'].

    The antenna's config file declares services the user explicitly wants
    to expose — but fresh users shouldn't have to edit JSON to enable
    every locally-installed app. Instead, we probe the machine at
    startup and UNION detected services with config-declared ones.

    Precedence: declared services always stay. Detected services are
    added if not already present. Nothing is ever removed here (user
    can still disable a service by editing config).

    Quiet on failure — if detection itself blows up, we log and keep
    the config-declared list untouched. The agent must boot regardless.
    """
    declared = list(cfg.get("services") or [])
    _LAST_AUTODETECT.clear()
    _LAST_AUTODETECT.update({
        "ran": True,
        "declared_before": list(declared),
        "auto_added": [],
        "error": None,
    })
    try:
        from . import detect as _detect
        # Load the service registry (same path status.py uses)
        try:
            import sys as _sys
            _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            if _repo_root not in _sys.path:
                _sys.path.insert(0, _repo_root)
            from installer import remote_services as _remote_services  # type: ignore
            # load_services returns list[dict] directly (not a wrapper dict)
            services_list = _remote_services.load_services()
        except Exception as e:
            msg = f"could not load service registry: {type(e).__name__}: {e}"
            print(f"[antenna] auto-detect: {msg}", file=sys.stderr)
            _LAST_AUTODETECT["error"] = msg
            return
        _LAST_AUTODETECT["registry_keys"] = [s.get("key") for s in services_list]
        if not services_list:
            _LAST_AUTODETECT["error"] = "empty service registry"
            return
        evidence = _detect.detect_installed_services(services_list, use_cache=False)
        _LAST_AUTODETECT["evidence_keys"] = list(evidence.keys())
        _LAST_AUTODETECT["installed_keys"] = [
            k for k, v in evidence.items() if isinstance(v, dict) and v.get("installed")
        ]
        auto_added: list[str] = []
        for svc in services_list:
            key = svc.get("key", "")
            if not key or key in declared:
                continue
            ev = evidence.get(key, {})
            # A service is auto-activated if ANY signal fired. The evidence
            # dict's top-level flag 'installed' is set by detect_service when
            # any of filesystem/process/network probes succeeded.
            if ev.get("installed"):
                declared.append(key)
                auto_added.append(key)
        _LAST_AUTODETECT["auto_added"] = auto_added
        _LAST_AUTODETECT["declared_after"] = list(declared)
        if auto_added:
            cfg["services"] = declared
            print(f"[antenna] auto-detected services added: {auto_added}")
            print(f"[antenna] effective services: {declared}")
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        print(f"[antenna] auto-detect failed ({msg}) — using declared only",
              file=sys.stderr)
        _LAST_AUTODETECT["error"] = msg


def _build_routes(cfg: dict[str, Any]) -> dict[tuple[str, str], Callable]:
    """Return the (method, path) → handler routing table.

    Handlers are callables: (request_ctx) → (status, body_dict)
    where request_ctx has keys: method, path, headers, body_json, client_ip, config.

    Called once at startup. Service-specific routes are added based on
    cfg["services"] so an antenna with services=["llm"] doesn't expose
    comfyui endpoints.
    """
    from .endpoints import status as status_ep

    routes: dict[tuple[str, str], Callable] = {
        ("GET", "/"):         status_ep.liveness,
        ("GET", "/status"):   status_ep.status,
    }

    # Pair-code handshake: unauthenticated claim + public state probe.
    # See _UNAUTHENTICATED_PATHS above and antenna/pairing.py for the
    # full flow. The claim handler returns the bearer token on the one
    # correct code, invalidates the code afterward, and 403s everything
    # else (which counts against the rate limit).
    try:
        from . import pairing as _pairing

        def _pair_claim(ctx: dict) -> tuple[int, dict]:
            body = ctx.get("body") or {}
            code = body.get("code", "") if isinstance(body, dict) else ""
            status_code, resp = _pairing.claim(code, ctx.get("config"))
            if status_code == 200:
                notify("Antenna paired",
                       "A Guild just completed the handshake — token shared.",
                       level="success")
            return status_code, resp

        def _pair_state(_ctx: dict) -> tuple[int, dict]:
            return 200, _pairing.get_pairing_state()

        def _pair_start(_ctx: dict) -> tuple[int, dict]:
            return 200, _pairing.start_pairing()

        def _pair_cancel(_ctx: dict) -> tuple[int, dict]:
            cancelled = _pairing.cancel_pairing()
            return 200, {"cancelled": cancelled}

        routes[("POST", "/pair/claim")]  = _pair_claim
        routes[("GET",  "/pair/state")]  = _pair_state
        routes[("POST", "/pair/start")]  = _pair_start   # auth required
        routes[("POST", "/pair/cancel")] = _pair_cancel  # auth required
    except ImportError as _e:
        print(f"[antenna] pairing endpoints unavailable: {_e}",
              file=sys.stderr)

    # R60b: telemetry snapshot (GPU/RAM/queue-depth) for fleet dashboards.
    # Schema is compatible with WhimWeaver's FleetTelemetry consumer.
    try:
        from .endpoints import telemetry_ep
        routes[("GET", "/telemetry")] = telemetry_ep.snapshot
    except ImportError as e:
        print(f"[antenna] WARN: telemetry endpoint missing: {e}",
              file=sys.stderr)

    # Service-specific routes
    services = cfg.get("services", [])
    if "comfyui" in services:
        # Lazy import so an llm-only antenna doesn't need comfyui deps
        try:
            from .endpoints import comfyui as comfyui_ep
            routes[("POST", "/install-node")]      = comfyui_ep.install_node
            routes[("POST", "/install-model")]     = comfyui_ep.install_model
            routes[("GET",  "/comfyui/node-catalog")] = comfyui_ep.node_catalog
        except ImportError as e:
            print(f"[antenna] comfyui service declared but endpoints not yet built: {e}",
                  file=sys.stderr)

    if "resolve" in services:
        # DaVinci Resolve scripting bridge — only import if the host
        # actually has Resolve. Discovery + scriptapp() are safe to
        # attempt; the endpoints return a descriptive 503 when Resolve
        # isn't running.
        try:
            from .endpoints import resolve as resolve_ep
            routes[("GET",  "/resolve/ping")]            = resolve_ep.ping
            routes[("POST", "/resolve/import-edl")]      = resolve_ep.import_edl
            routes[("POST", "/resolve/import-fcpxml")]   = resolve_ep.import_fcpxml
            routes[("POST", "/resolve/render-timeline")] = resolve_ep.render_timeline
            routes[("GET",  "/resolve/render-status")]   = resolve_ep.render_status
            routes[("GET",  "/resolve/render-presets")]  = resolve_ep.render_presets
            routes[("GET",  "/resolve/luts")]            = resolve_ep.list_luts
        except ImportError as e:
            print(f"[antenna] resolve service declared but endpoints missing: {e}",
                  file=sys.stderr)
        # R83b: resolve plugin deployment — antenna-driven refresh of
        # Resolve's Workflow Integration Plugins + Fusion/Scripts dirs.
        # Independent import so a stale resolve.py doesn't block plugin
        # install (the install logic has no Resolve-API dependency).
        try:
            from .endpoints import resolve_plugin as resolve_plugin_ep
            routes[("GET",  "/resolve/plugin/status")]    = resolve_plugin_ep.status
            routes[("GET",  "/resolve/plugin/debug")]     = resolve_plugin_ep.debug
            routes[("POST", "/resolve/plugin/install")]   = resolve_plugin_ep.install
            routes[("POST", "/resolve/plugin/configure")] = resolve_plugin_ep.configure
            # R87b: stage a local video file into ComfyUI's input dir so
            # VHS_LoadVideo can pick it up by basename without a
            # cross-LAN byte transfer.
            routes[("POST", "/resolve/stage-input-video")] = \
                resolve_plugin_ep.stage_input_video
        except ImportError as e:
            print(f"[antenna] resolve_plugin endpoint failed to import: {e}",
                  file=sys.stderr)

    # R115: Darktable plugin deployment — same antenna-installer pattern
    # as Resolve. Gated on the darktable service so hosts without
    # Darktable installed don't show the routes.
    if "darktable" in services:
        try:
            from .endpoints import darktable_plugin as darktable_plugin_ep
            routes[("GET",  "/darktable/plugin/status")]  = darktable_plugin_ep.status
            routes[("POST", "/darktable/plugin/install")] = darktable_plugin_ep.install
        except ImportError as e:
            print(f"[antenna] darktable_plugin endpoint failed to import: {e}",
                  file=sys.stderr)

    # R116: SillyTavern deploy. Gated on the sillytavern service so
    # hosts without ST don't expose the routes. Detection scans common
    # install paths; operator can pin via cfg['sillytavern_dir'].
    if "sillytavern" in services:
        try:
            from .endpoints import sillytavern_plugin as st_plugin_ep
            routes[("GET",  "/sillytavern/plugin/status")]  = st_plugin_ep.status
            routes[("POST", "/sillytavern/plugin/install")] = st_plugin_ep.install
        except ImportError as e:
            print(f"[antenna] sillytavern_plugin endpoint failed to import: {e}",
                  file=sys.stderr)

    # R56: generic service start/logs — covers ComfyUI, Kobold, Ollama.
    # Always registered (not gated by a specific service) because
    # start_service chooses based on the request body, not route key.
    try:
        from .endpoints import services as services_ep
        routes[("POST", "/service/start")] = services_ep.start_service
        routes[("POST", "/service/stop")]  = services_ep.stop_service
        routes[("GET",  "/service/logs")]  = services_ep.service_logs
        routes[("GET",  "/diag/detector")] = services_ep.detector_diag
    except ImportError as e:
        print(f"[antenna] WARN: services endpoint failed to import: {e}",
              file=sys.stderr)

    # LLM install + status — always registered. /llm/install is the gating
    # piece that lets the Guild's setup wizard bootstrap a local LLM on a
    # remote ComfyUI host the user can't SSH into. /llm/status is a cheap
    # probe the wizard calls before deciding whether install is even needed.
    try:
        from .endpoints import llm as llm_ep
        routes[("GET",  "/llm/status")]  = llm_ep.status
        routes[("POST", "/llm/install")] = llm_ep.install_llm
    except ImportError as e:
        print(f"[antenna] WARN: llm endpoint failed to import: {e}",
              file=sys.stderr)

    # self-update is always available — it's how the agent updates itself.
    # Any import failure here is critical to surface so operators can
    # debug it — otherwise they see mysterious "no such endpoint" 404s.
    try:
        from .endpoints import self_update as su_ep
        routes[("POST", "/self-update")] = su_ep.self_update
        print("[antenna] registered: POST /self-update")
    except ImportError as e:
        print(f"[antenna] WARN: self_update endpoint failed to import: {e}",
              file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — catch ALL, including SyntaxError
        print(f"[antenna] WARN: self_update endpoint error: "
              f"{type(e).__name__}: {e}", file=sys.stderr)

    # Log every registered route at startup so the operator can confirm
    # visually what's live
    print(f"[antenna] Registered routes: {len(routes)}")
    for (method, path) in sorted(routes.keys()):
        print(f"[antenna]   {method} {path}")

    return routes


# ─── Audit log ───────────────────────────────────────────────────────────

_log_lock = threading.Lock()


def _audit_log(log_path: str, ip: str, method: str, path: str,
               status: int, note: str = "") -> None:
    """Append one line to the audit log. Thread-safe.

    Format: `<ISO timestamp> <ip> <method> <path> <status> <note>`
    Written append-only. The user can tail it with `tail -f antenna.log`.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    line = f"{ts} {ip} {method} {path} {status} {note}\n"
    try:
        log_file = Path(os.path.expanduser(log_path))
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with _log_lock:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(line)
    except OSError as e:
        # Don't crash the server if the log disk fills up — log to stderr
        print(f"[antenna] audit log write failed: {e} (line was: {line.strip()})",
              file=sys.stderr)


# ─── Request handler ─────────────────────────────────────────────────────

class _AntennaHandler(BaseHTTPRequestHandler):
    """One request = one instance (BaseHTTPRequestHandler convention).

    We attach the shared config + routes + rate limiter to the class
    (set at startup by serve()) so each instance can access them without
    reloading.
    """

    # Populated by serve() before the server starts
    _config: dict[str, Any] = {}
    _routes: dict[tuple[str, str], Callable] = {}
    _rate_limiter: auth.RateLimiter | None = None

    # Override to silence the default access-log to stderr — we have our
    # own structured audit log
    def log_message(self, format, *args):  # noqa: A002  (parent API)
        pass

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        """Serialize body as JSON, set headers, write."""
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        # Allow browser-based clients (Wizard Guild served from another
        # host) to call us. Strict CORS wouldn't buy us much beyond the
        # bearer token requirement.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Client disconnected — nothing to do

    def _handle(self, method: str) -> None:
        """Shared GET/POST pipeline. Runs rate-limit → route → auth → dispatch."""
        client_ip = self.client_address[0]

        # Strip query string for routing (endpoints can still read it
        # from self.path if needed — we pass the raw path through below)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        route_key = (method, path)
        rl = self._AntennaHandler__class__._rate_limiter if False else self._rate_limiter

        # 1. Rate limit (applies to every request, even unknown paths —
        #    otherwise attackers could probe endlessly for valid paths)
        if rl is not None:
            allowed, retry_after = rl.check_and_record(client_ip)
            if not allowed:
                self.send_response(429)
                self.send_header("Retry-After", str(int(retry_after)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": "rate limited",
                                "retry_after_seconds": int(retry_after)}).encode())
                _audit_log(self._config["log_path"], client_ip, method, path,
                           429, "rate-limited")
                return

        # 2. Route match
        handler = self._routes.get(route_key)
        if handler is None:
            self._send_json(404, {"error": f"no such endpoint: {method} {path}"})
            _audit_log(self._config["log_path"], client_ip, method, path, 404)
            return

        # 3. Auth check (unless endpoint is explicitly unauthenticated)
        if path not in _UNAUTHENTICATED_PATHS:
            ok, err = auth.authenticate_request(
                dict(self.headers), self._config["token_path"])
            if not ok:
                self._send_json(401, {"error": err or "unauthorized"})
                _audit_log(self._config["log_path"], client_ip, method, path,
                           401, err or "")
                return

        # 4. Parse request body for POSTs (JSON only)
        body: dict[str, Any] = {}
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_048_576:  # 1 MB cap — endpoints don't need more
                    self._send_json(413, {"error": "request body too large"})
                    _audit_log(self._config["log_path"], client_ip, method, path,
                               413, f"len={length}")
                    return
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
            except (ValueError, json.JSONDecodeError) as e:
                self._send_json(400, {"error": f"invalid JSON body: {e}"})
                _audit_log(self._config["log_path"], client_ip, method, path,
                           400, str(e))
                return

        # 5. Dispatch to handler
        try:
            request_ctx = {
                "method": method,
                "path": path,
                "raw_path": self.path,
                "headers": dict(self.headers),
                "body": body,
                "client_ip": client_ip,
                "config": self._config,
            }
            status, response = handler(request_ctx)
        except Exception as e:  # noqa: BLE001  (handler contract says it may raise)
            # Log full traceback to audit log for debugging but only send
            # a generic error to the client (no internal leakage)
            tb = traceback.format_exc()
            print(f"[antenna] handler {path} crashed:\n{tb}", file=sys.stderr)
            _audit_log(self._config["log_path"], client_ip, method, path,
                       500, f"exception: {type(e).__name__}")
            self._send_json(500, {"error": "internal agent error"})
            return

        self._send_json(status, response)
        _audit_log(self._config["log_path"], client_ip, method, path, status)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_OPTIONS(self):
        # CORS preflight — reply 204 with the allow headers we set in _send_json
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()


# ─── Server bootstrap ────────────────────────────────────────────────────

def _make_ssl_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    """Build a TLS context from the self-signed cert. TLS 1.2+ only."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    # We're serving clients that pin the cert fingerprint, so no need
    # to advertise a CA chain or accept client certs.
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def serve(cfg: dict[str, Any] | None = None,
          block: bool = True) -> ThreadingHTTPServer:
    """Start the HTTPS antenna. Call config.bootstrap() first.

    Args:
        cfg: config dict from config.load_config(). None → auto-load.
        block: True → serve_forever (runs until Ctrl-C). False → returns
               the server object immediately for the caller to drive
               (used by tests).

    Returns the ThreadingHTTPServer instance (already bound + listening).
    """
    if cfg is None:
        cfg = config.bootstrap()

    # R49a: auto-populate services so users don't edit JSON. Runs BEFORE
    # _build_routes so auto-detected services get their routes registered.
    _autopopulate_services(cfg)

    # Install handler class attributes BEFORE the server starts accepting
    _AntennaHandler._config = cfg
    _AntennaHandler._routes = _build_routes(cfg)
    _AntennaHandler._rate_limiter = auth.RateLimiter(
        limit_per_minute=cfg.get("rate_limit_rpm", 30))

    # Reap any prior process still holding our port — protects us from
    # orphaned `python.exe` processes left over by a botched self-update
    # restart. Only kills python-named processes by default, so an
    # unrelated service on the same port fails-open (bind raises, operator
    # sees it).
    try:
        global _LAST_PORT_CLEANUP
        from . import port_cleanup as _pc
        _LAST_PORT_CLEANUP = _pc.reap_port_holders(int(cfg["port"]),
                                                    only_python=True)
        if _LAST_PORT_CLEANUP:
            killed = [r for r in _LAST_PORT_CLEANUP if r.get("killed")]
            skipped = [r for r in _LAST_PORT_CLEANUP if not r.get("killed")]
            if killed:
                print(f"[antenna] reaped {len(killed)} stale process(es) "
                      f"on port {cfg['port']}: "
                      f"{[(r['pid'], r['image']) for r in killed]}")
                # Give the OS a moment to release the socket
                import time as _t
                _t.sleep(1.0)
            if skipped:
                print(f"[antenna] left {len(skipped)} process(es) "
                      f"untouched on port {cfg['port']}: "
                      f"{[(r['pid'], r['image'], r['skipped_reason']) for r in skipped]}",
                      file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[antenna] port-cleanup failed: {type(e).__name__}: {e} — "
              f"proceeding anyway", file=sys.stderr)

    use_tls = config.tls_enabled(cfg)
    server = ThreadingHTTPServer((cfg["bind"], int(cfg["port"])), _AntennaHandler)

    if use_tls:
        cert_path = Path(os.path.expanduser(cfg["tls_cert_path"]))
        key_path = Path(os.path.expanduser(cfg["tls_key_path"]))
        ssl_ctx = _make_ssl_context(cert_path, key_path)
        server.socket = ssl_ctx.wrap_socket(server.socket, server_side=True)
        scheme = "https"
        fingerprint = config.cert_fingerprint(cert_path)
    else:
        scheme = "http"
        fingerprint = ""

    print(f"[antenna] Spellcaster antenna v{__version__} listening on "
          f"{scheme}://{cfg['bind']}:{cfg['port']}")
    print(f"[antenna] Services: {', '.join(cfg.get('services', []))}")
    if use_tls:
        print(f"[antenna] Cert fingerprint (SHA-256): {fingerprint}")
    else:
        print(f"[antenna] TLS disabled (ANTENNA_NO_TLS=1) — plain HTTP + bearer token")
        print(f"[antenna]   Install openssl or Git-for-Windows to enable TLS.")
    print(f"[antenna] Token file: {cfg['token_path']}")
    print(f"[antenna] Audit log:  {cfg['log_path']}")

    # Start heartbeat to Mega Bridge so declared services appear in the
    # Guild sidebar. No-op when hub_url isn't configured (local agent).
    heartbeat.start(cfg)

    print(f"[antenna] Ready. Ctrl-C to stop.", flush=True)
    notify("Antenna ready",
           f"Listening on {scheme}://{cfg['bind']}:{cfg['port']}",
           level="success")

    # Graceful shutdown on Ctrl-C — close the listening socket, let
    # in-flight requests finish on their own threads, then exit.
    def _shutdown(signum, frame):
        print("\n[antenna] shutting down...")
        # shutdown() from a signal handler requires a thread since it
        # blocks until serve_forever returns.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    if block:
        try:
            server.serve_forever()
        finally:
            server.server_close()
            print("[antenna] stopped.")
    return server


# Under `python -m antenna.agent`, Python creates TWO module objects:
# one keyed on "__main__" (this file) and one on "antenna.agent" (via the
# package import). Module-level state (_LAST_AUTODETECT, _AntennaHandler
# class) only lives on whichever Python first touched — usually __main__.
# Force them to be the same object so status.py etc. see current state
# regardless of which name they import through.
if __name__ == "__main__":
    # Unconditional: if `antenna.agent` already points at a DIFFERENT
    # module object (runpy under certain CPython builds re-imports),
    # force it to point at the running __main__ so `from .. import agent`
    # from status.py lands on the module whose state was actually mutated.
    import sys as _sys
    _sys.modules["antenna.agent"] = _sys.modules["__main__"]
    # python -m antenna.agent → start the server with default config
    serve()
