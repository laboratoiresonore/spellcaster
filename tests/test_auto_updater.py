"""Tests for the hardening added after the 2026-04 auto-updater audit.

Covers the two fixes the audit called out:

  * `fetch_tree` raises `TruncatedTreeError` when GitHub signals the
    response is truncated — otherwise a maintainer would silently
    miss half the asset files on update pass.
  * `download_blob_with_retry` smooths transient network failures
    with exponential backoff, and propagates deterministic failures
    (SHA / size mismatch) without retrying.

The fake-HTTP harness is the same pattern used in
`test_lora_auto_calibrate.py` — a stdlib HTTPServer in a daemon
thread so the tests stay deterministic without touching GitHub.

Run:
    PYTHONPATH=comfyui-spellcaster python tests/test_auto_updater.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for p in (os.path.join(_REPO, "comfyui-spellcaster"), _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


from spellcaster_core.auto_updater import (  # noqa: E402
    fetch_tree, download_blob, download_blob_with_retry,
    TruncatedTreeError,
)


def _serve(handler_cls) -> tuple[HTTPServer, str]:
    """Spin up a daemon HTTP server; return (srv, base_url)."""
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ── fetch_tree + TruncatedTreeError ──────────────────────────────────

def case_fetch_tree_returns_blobs():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw): pass
        def do_GET(self):
            body = json.dumps({
                "tree": [
                    {"path": "plugins/gimp/foo.py", "type": "blob",
                     "size": 123, "sha": "abc"},
                    {"path": "plugins/gimp/theme.css", "type": "blob",
                     "size": 456, "sha": "def"},
                ],
                "truncated": False,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv, base = _serve(H)
    try:
        tree = fetch_tree(base + "/tree", {}, timeout=2.0)
        assert len(tree) == 2
        assert any(item["path"].endswith(".css") for item in tree)
    finally:
        srv.shutdown()


def case_fetch_tree_raises_on_truncation():
    """If the GitHub Tree API returns truncated=true we refuse to
    proceed — otherwise the caller's stale-file cleanup would delete
    every asset that DIDN'T make it into the partial tree."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw): pass
        def do_GET(self):
            body = json.dumps({"tree": [], "truncated": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv, base = _serve(H)
    try:
        raised = False
        try:
            fetch_tree(base + "/tree", {}, timeout=2.0)
        except TruncatedTreeError as e:
            raised = True
            assert "truncated" in str(e).lower()
        assert raised
    finally:
        srv.shutdown()


# ── download_blob_with_retry ─────────────────────────────────────────

def case_retry_succeeds_after_transient_failures():
    """Two flaky responses followed by a good one — the retry
    wrapper should land on the third try and return the blob."""
    hit_count = {"n": 0}
    good_body = b"the-bytes"

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw): pass
        def do_GET(self):
            hit_count["n"] += 1
            if hit_count["n"] < 3:
                # Close mid-response → client sees an OSError/URLError
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(good_body)))
            self.end_headers()
            self.wfile.write(good_body)

    srv, base = _serve(H)
    try:
        blob = download_blob_with_retry(
            base + "/f", len(good_body), {},
            timeout=2.0, retries=3, backoff_seconds=0.01,
        )
        assert blob == good_body
        assert hit_count["n"] == 3
    finally:
        srv.shutdown()


def case_retry_gives_up_after_exhausting_attempts():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw): pass
        def do_GET(self):
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv, base = _serve(H)
    try:
        raised = False
        try:
            download_blob_with_retry(
                base + "/f", 100, {},
                timeout=1.0, retries=2, backoff_seconds=0.01,
            )
        except Exception:
            raised = True
        assert raised
    finally:
        srv.shutdown()


def case_retry_does_not_retry_on_size_mismatch():
    """If the server hands back a different-size blob than the tree
    advertised, retrying won't help — it's a deterministic failure.
    Give up on the first attempt."""
    hit_count = {"n": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw): pass
        def do_GET(self):
            hit_count["n"] += 1
            body = b"wrong-size"   # 10 bytes but expected_size says 5
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv, base = _serve(H)
    try:
        raised = False
        try:
            download_blob_with_retry(
                base + "/f", expected_size=5, headers={},
                timeout=2.0, retries=5, backoff_seconds=0.01,
            )
        except IOError as e:
            raised = True
            assert "incomplete" in str(e).lower() or "mismatch" in str(e).lower()
        assert raised
        # Exactly ONE hit — size mismatch is deterministic, retry skipped.
        assert hit_count["n"] == 1, f"expected 1 hit, got {hit_count['n']}"
    finally:
        srv.shutdown()


CASES = [
    ("fetch_tree: returns blobs on normal response",    case_fetch_tree_returns_blobs),
    ("fetch_tree: raises on truncated=true",            case_fetch_tree_raises_on_truncation),
    ("retry: succeeds after transient failures",        case_retry_succeeds_after_transient_failures),
    ("retry: gives up after exhausting attempts",       case_retry_gives_up_after_exhausting_attempts),
    ("retry: skips retry on size mismatch",             case_retry_does_not_retry_on_size_mismatch),
]


def main():
    print("auto_updater hardening tests")
    print("=" * 60)
    failures = []
    for label, fn in CASES:
        try:
            fn()
            print(f"  [OK]   {label}")
        except AssertionError as e:
            print(f"  [FAIL] {label}: {e}")
            failures.append(label)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR]  {label}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append(label)
    print("=" * 60)
    if failures:
        print(f"FAILED ({len(failures)}/{len(CASES)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASSED ({len(CASES)}/{len(CASES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
