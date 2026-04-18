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

from . import __version__, auth, config


# ─── Routing table ───────────────────────────────────────────────────────
# Endpoint modules are lazily imported inside _build_routes() so that
# optional services (llm, resolve) don't load if this antenna doesn't
# declare them. Keeps import-time clean and failure modes per-service.

# Endpoints that skip token auth (but still rate-limited).
_UNAUTHENTICATED_PATHS: set[str] = {"/"}


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

    # Service-specific routes
    services = cfg.get("services", [])
    if "comfyui" in services:
        # Lazy import so an llm-only antenna doesn't need comfyui deps
        try:
            from .endpoints import comfyui as comfyui_ep
            routes[("POST", "/install-node")]  = comfyui_ep.install_node
            routes[("POST", "/install-model")] = comfyui_ep.install_model
        except ImportError as e:
            print(f"[antenna] comfyui service declared but endpoints not yet built: {e}",
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

    # Install handler class attributes BEFORE the server starts accepting
    _AntennaHandler._config = cfg
    _AntennaHandler._routes = _build_routes(cfg)
    _AntennaHandler._rate_limiter = auth.RateLimiter(
        limit_per_minute=cfg.get("rate_limit_rpm", 30))

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
    print(f"[antenna] Ready. Ctrl-C to stop.", flush=True)

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


if __name__ == "__main__":
    # python -m antenna.agent → start the server with default config
    serve()
