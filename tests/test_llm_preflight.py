"""Tests for tools/llm_preflight.py — the ground-truth context gate.

Covers the failure mode from issue #181 (server under-reports the
loaded model's context and no override manifest is consulted) and
the fallback paths when the manifest or the server is missing.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent

# Mirror the sys.path shape safe_fetch tests use — the connector-side
# spellcaster_core is authoritative.
_CORE_PARENT = _REPO / "plugins" / "gimp" / "comfyui-connector"
if _CORE_PARENT.is_dir() and str(_CORE_PARENT) not in sys.path:
    sys.path.insert(0, str(_CORE_PARENT))

_TOOLS = _REPO / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))


import llm_preflight  # noqa: E402
from llm_preflight import (  # noqa: E402
    InsufficientContextError,
    assert_context,
    get_declared_context,
    load_manifest,
)


class _FakeResp:
    """Minimal duck-type of a urllib response for mocking — matches
    the shape spellcaster_core.safe_fetch expects."""

    def __init__(self, body: bytes, status: int = 200):
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = _FakeHeaders({"Content-Length": str(len(body))})
        self.closed = False

    def read(self, amt=None):
        if amt is None or amt < 0:
            return self._buf.read()
        return self._buf.read(amt)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class _FakeHeaders(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


class LlmPreflightTest(unittest.TestCase):
    """Isolated tests: each test writes a manifest of its own into a
    per-test tempdir and points ``llm_preflight`` at it via the
    ``manifest_path`` kwarg. The real installer/model_capabilities.json
    is not touched."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="preflight_test_"))
        self._manifest = self._tmp / "model_capabilities.json"
        # Redirect the safe_fetch audit log so tests don't clutter
        # ~/.voodoomaster/.
        self._audit = self._tmp / "fetch_audit.jsonl"
        self._prev_audit = os.environ.get("SPELLCASTER_FETCH_AUDIT_PATH")
        os.environ["SPELLCASTER_FETCH_AUDIT_PATH"] = str(self._audit)

    def tearDown(self):
        if self._prev_audit is None:
            os.environ.pop("SPELLCASTER_FETCH_AUDIT_PATH", None)
        else:
            os.environ["SPELLCASTER_FETCH_AUDIT_PATH"] = self._prev_audit
        for p in (self._manifest, self._audit):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        try:
            self._tmp.rmdir()
        except OSError:
            pass

    def _write_manifest(self, models: dict) -> None:
        payload = {
            "_schema": {"version": 1, "purpose": "test fixture"},
            "models": models,
        }
        self._manifest.write_text(json.dumps(payload), encoding="utf-8")

    # -----------------------------------------------------------------
    # Test 1 — manifest-only path (server unreachable, manifest hit)
    # -----------------------------------------------------------------

    def test_manifest_only_path_succeeds_when_server_unreachable(self):
        self._write_manifest({
            "qwen3-8b": {"context_length": 131072,
                         "notes": "test"},
        })
        # Force _fetch_server_context to look reachable-but-empty by
        # raising URLError from urlopen.
        with mock.patch("urllib.request.urlopen",
                         side_effect=OSError("connection refused")):
            declared = get_declared_context(
                "qwen3-8b", host="http://127.0.0.1:1234",
                manifest_path=self._manifest)
            self.assertEqual(declared, 131072)
            # And the assert helper: required 64000 must succeed
            # against a manifest-only 131072.
            assert_context("qwen3-8b", required_ctx=64000,
                           host="http://127.0.0.1:1234",
                           manifest_path=self._manifest)

    # -----------------------------------------------------------------
    # Test 2 — server under-reports; manifest overrides upward
    # -----------------------------------------------------------------

    def test_manifest_overrides_server_under_report(self):
        self._write_manifest({
            "qwen3-8b": {"context_length": 131072, "notes": ""},
        })
        server_payload = json.dumps({
            "object": "list",
            "data": [
                {"id": "qwen3-8b",
                 # LM Studio's under-reported window from the incident.
                 "context_length": 4096},
            ],
        }).encode("utf-8")
        fake = _FakeResp(server_payload)
        with mock.patch("urllib.request.urlopen", return_value=fake):
            declared = get_declared_context(
                "qwen3-8b", host="http://127.0.0.1:1234",
                manifest_path=self._manifest)
        self.assertEqual(declared, 131072,
                          "effective must be max(server, manifest); "
                          "server under-report must not win")
        # And required 64000 clears cleanly.
        with mock.patch("urllib.request.urlopen", return_value=fake):
            assert_context("qwen3-8b", required_ctx=64000,
                            host="http://127.0.0.1:1234",
                            manifest_path=self._manifest)

    # -----------------------------------------------------------------
    # Test 3 — unknown model raises with a clear message
    # -----------------------------------------------------------------

    def test_unknown_model_raises_clear_message(self):
        self._write_manifest({
            "some-other-model": {"context_length": 8192, "notes": ""},
        })
        # Server reachable but doesn't list the model.
        server_payload = json.dumps({
            "object": "list",
            "data": [{"id": "some-other-model", "context_length": 8192}],
        }).encode("utf-8")
        fake = _FakeResp(server_payload)
        with mock.patch("urllib.request.urlopen", return_value=fake):
            with self.assertRaises(InsufficientContextError) as ctx:
                get_declared_context("nonexistent-model",
                                       host="http://127.0.0.1:1234",
                                       manifest_path=self._manifest)
        self.assertIn("unknown model", str(ctx.exception))
        self.assertIn("nonexistent-model", str(ctx.exception))
        self.assertIn("installer/model_capabilities.json",
                      str(ctx.exception))

    # -----------------------------------------------------------------
    # Test 4 — required exceeds both → InsufficientContextError
    # -----------------------------------------------------------------

    def test_required_exceeds_both_raises_naming_values(self):
        self._write_manifest({
            "qwen3-8b": {"context_length": 40960, "notes": "native"},
        })
        server_payload = json.dumps({
            "object": "list",
            "data": [{"id": "qwen3-8b", "context_length": 4096}],
        }).encode("utf-8")
        fake = _FakeResp(server_payload)
        with mock.patch("urllib.request.urlopen", return_value=fake):
            with self.assertRaises(InsufficientContextError) as ctx:
                assert_context("qwen3-8b", required_ctx=200000,
                                 host="http://127.0.0.1:1234",
                                 manifest_path=self._manifest)
        msg = str(ctx.exception)
        # Message must name BOTH values so a shell error is legible.
        self.assertIn("200000", msg,
                       "required_ctx must appear in the diagnostic")
        self.assertIn("40960", msg,
                       "declared_ctx (max of server, manifest) must "
                       "appear in the diagnostic")

    # -----------------------------------------------------------------
    # Test 5 — CLI: exit 0 when the check passes
    # -----------------------------------------------------------------

    def test_cli_exits_zero_when_sufficient(self):
        # Uses the REAL manifest under installer/. The green-path CLI
        # run is one of the definition-of-done items in issue #181.
        result = subprocess.run(
            [sys.executable, str(_REPO / "tools" / "llm_preflight.py"),
             "--model", "qwen3-8b",
             "--required-ctx", "64000"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ,
                 # Force server to be unreachable so we hit the
                 # manifest-only fallback deterministically.
                 "LM_STUDIO_HOST": "http://127.0.0.1:1",
                 "SPELLCASTER_FETCH_AUDIT_PATH": str(self._audit)},
        )
        self.assertEqual(result.returncode, 0,
                          f"expected exit 0, got {result.returncode}. "
                          f"stdout={result.stdout!r} "
                          f"stderr={result.stderr!r}")
        self.assertIn("OK:", result.stdout)

    # -----------------------------------------------------------------
    # Test 6 — CLI: exit 1 with a diagnostic when the check fails
    # -----------------------------------------------------------------

    def test_cli_exits_one_with_diagnostic_when_insufficient(self):
        result = subprocess.run(
            [sys.executable, str(_REPO / "tools" / "llm_preflight.py"),
             "--model", "qwen3-8b",
             "--required-ctx", "200000"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ,
                 "LM_STUDIO_HOST": "http://127.0.0.1:1",
                 "SPELLCASTER_FETCH_AUDIT_PATH": str(self._audit)},
        )
        self.assertEqual(result.returncode, 1,
                          f"expected exit 1, got {result.returncode}. "
                          f"stdout={result.stdout!r} "
                          f"stderr={result.stderr!r}")
        # Diagnostic names both values.
        self.assertIn("200000", result.stderr)
        self.assertIn("131072", result.stderr,
                       "expected the manifest's context value in the "
                       "diagnostic (qwen3-8b is 131072 in the real "
                       "installer/model_capabilities.json)")


class LlmPreflightManifestLoadTest(unittest.TestCase):
    """Cover load_manifest's error path — the FileNotFoundError needs
    to point maintainers at the fix."""

    def test_missing_manifest_error_points_at_fix(self):
        tmp = Path(tempfile.mkdtemp(prefix="preflight_load_"))
        missing = tmp / "does_not_exist.json"
        try:
            with self.assertRaises(FileNotFoundError) as ctx:
                load_manifest(missing)
            msg = str(ctx.exception)
            self.assertIn(str(missing), msg)
            self.assertIn("_schema", msg,
                           "hint should mention the file's schema block "
                           "so the fixer knows where to look")
        finally:
            try:
                tmp.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
