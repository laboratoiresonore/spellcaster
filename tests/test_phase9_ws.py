"""Phase 9: websocket dispatch + ETN inline-transport tests.

Mocks ``websockets.sync.client.connect`` so no real ComfyUI server is
needed. Covers:

  * comfy_ws._build_ws_url (http -> ws, https -> wss)
  * comfy_ws._decode_binary_frame (header parsing, short-frame guard)
  * comfy_ws._collect_outputs_from_executed (images + gifs)
  * comfy_ws.submit_and_listen happy path -- text + binary mixed
  * comfy_ws.submit_and_listen execution_error
  * comfy_ws.submit_and_listen execution_interrupted
  * comfy_ws.submit_and_listen prompt_id filter (ignore other clients)
  * comfy_ws.submit_and_listen wire-format detail (client_id passed
    in /prompt body)
  * dispatch.dispatch_workflow(use_websocket=True) happy path
  * dispatch.dispatch_workflow(use_websocket=True) ws-failure fallback
    to poll
  * dispatch.dispatch_workflow(use_websocket=True, ws_fallback_to_poll=False)
    ws-failure raises
  * node_factory.etn_load_image_base64 / save_image_websocket /
    etn_send_image_websocket emit the right class_types

Run:
    PYTHONPATH=comfyui-spellcaster python tests/test_phase9_ws.py
"""
from __future__ import annotations

import io
import json
import os
import struct
import sys
import traceback
import urllib.error
from typing import Any, List
from unittest import mock


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_CORE_ROOT = os.path.join(_REPO, "comfyui-spellcaster")
if _CORE_ROOT not in sys.path:
    sys.path.insert(0, _CORE_ROOT)


from spellcaster_core import comfy_ws, dispatch, node_factory  # noqa: E402


# ────────────────────────────────────────────────────────────────────
# Mock helpers
# ────────────────────────────────────────────────────────────────────


class _FakeWS:
    """Stand-in for the ``websockets.sync.client`` connection.

    Constructed with a script of messages -- each call to ``recv()``
    pops the next one. Strings are returned as text frames (str);
    bytes are returned as binary frames. Use ``_TIMEOUT_SENTINEL`` to
    simulate a single recv() timeout (the loop should retry on the
    outer deadline).
    """

    _TIMEOUT_SENTINEL = object()

    def __init__(self, script):
        self._script = list(script)
        self.closed = False
        self.recv_calls = 0

    def recv(self, timeout=None):
        self.recv_calls += 1
        if not self._script:
            # Hang until parent loop times out
            raise TimeoutError("script exhausted")
        item = self._script.pop(0)
        if item is _FakeWS._TIMEOUT_SENTINEL:
            raise TimeoutError("scripted timeout")
        return item

    def close(self):
        self.closed = True


def _make_post_response(prompt_id: str = "test-prompt-id"):
    """Stand-in for urllib's HTTPResponse-as-context-manager."""
    body = json.dumps({"prompt_id": prompt_id}).encode("utf-8")
    resp = mock.MagicMock()
    resp.read.return_value = body
    cm = mock.MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


def _bin_frame(image_bytes: bytes,
               *, event=comfy_ws.WS_EVENT_PREVIEW_IMAGE,
               fmt=comfy_ws.WS_FORMAT_PNG) -> bytes:
    """Build an 8-byte-header + payload binary frame."""
    return struct.pack(comfy_ws._WS_HEADER_FMT, event, fmt) + image_bytes


def _patch_ws_and_post(monkey_targets, fake_ws, post_resp_or_exc):
    """Context-manager bundle: patch ws connect + urlopen.

    monkey_targets: list to which we append .stop functions.
    """
    # Patch the ws connect (lazy-imported inside _ws_connect)
    fake_connect = mock.MagicMock(return_value=fake_ws)
    p1 = mock.patch.object(comfy_ws, "_ws_connect", fake_connect)
    p1.start()
    monkey_targets.append(p1.stop)

    # Patch urlopen used by _submit_prompt
    if isinstance(post_resp_or_exc, Exception):
        p2 = mock.patch.object(
            comfy_ws.urlrequest, "urlopen",
            side_effect=post_resp_or_exc,
        )
    else:
        p2 = mock.patch.object(
            comfy_ws.urlrequest, "urlopen",
            return_value=post_resp_or_exc,
        )
    p2.start()
    monkey_targets.append(p2.stop)


def _stop_all(monkey_targets):
    for stop in reversed(monkey_targets):
        try:
            stop()
        except Exception:
            pass


# ────────────────────────────────────────────────────────────────────
# Test runner machinery (matches sibling tests' plain-Python style)
# ────────────────────────────────────────────────────────────────────


_failures: List[str] = []


def _run(name, fn):
    print(f"  [test] {name} ... ", end="")
    try:
        fn()
        print("OK")
    except AssertionError as e:
        _failures.append(f"{name}: {e}")
        print(f"FAIL: {e}")
    except Exception as e:
        _failures.append(f"{name}: {type(e).__name__}: {e}")
        print(f"FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()


# ────────────────────────────────────────────────────────────────────
# Unit tests: comfy_ws helpers
# ────────────────────────────────────────────────────────────────────


def test_build_ws_url_http_to_ws():
    assert comfy_ws._build_ws_url(
        "http://comfy.test:8188", "abc123",
    ) == "ws://comfy.test:8188/ws?clientId=abc123"


def test_build_ws_url_https_to_wss():
    assert comfy_ws._build_ws_url(
        "https://secure.test:443", "xyz",
    ) == "wss://secure.test:443/ws?clientId=xyz"


def test_build_ws_url_strips_trailing_slash():
    assert comfy_ws._build_ws_url(
        "http://comfy.test:8188/", "id1",
    ) == "ws://comfy.test:8188/ws?clientId=id1"


def test_build_ws_url_no_scheme_defaults_to_ws():
    assert comfy_ws._build_ws_url(
        "comfy.test:8188", "id2",
    ) == "ws://comfy.test:8188/ws?clientId=id2"


def test_decode_binary_frame_png():
    image = b"\x89PNG\r\n\x1a\n" + b"fake-png-rest"
    blob = _bin_frame(image)
    frame = comfy_ws._decode_binary_frame(blob, received_at=1.0)
    assert frame is not None
    assert frame.event == comfy_ws.WS_EVENT_PREVIEW_IMAGE
    assert frame.format == comfy_ws.WS_FORMAT_PNG
    assert frame.image_bytes == image
    assert frame.format_name == "png"


def test_decode_binary_frame_jpg():
    image = b"\xff\xd8\xff\xe0fakejpeg"
    blob = _bin_frame(image, fmt=comfy_ws.WS_FORMAT_JPG)
    frame = comfy_ws._decode_binary_frame(blob, received_at=1.0)
    assert frame.format == comfy_ws.WS_FORMAT_JPG
    assert frame.format_name == "jpg"
    assert frame.image_bytes == image


def test_decode_binary_frame_too_short():
    # < 8 bytes -- not a valid frame
    assert comfy_ws._decode_binary_frame(b"\x00\x00", received_at=1.0) is None


def test_decode_binary_frame_unknown_event_returns_none():
    # event != WS_EVENT_PREVIEW_IMAGE -- skip silently
    blob = struct.pack(comfy_ws._WS_HEADER_FMT, 99, 2) + b"payload"
    assert comfy_ws._decode_binary_frame(blob, received_at=1.0) is None


def test_collect_outputs_images_and_gifs():
    msg_data = {
        "node": "9",
        "output": {
            "images": [
                {"filename": "a.png", "subfolder": "sub", "type": "output"},
                {"filename": "b.png", "subfolder": "", "type": "temp"},
            ],
            "gifs": [
                {"filename": "v.mp4", "subfolder": "vid", "type": "output"},
            ],
        },
        "prompt_id": "p1",
    }
    out = comfy_ws._collect_outputs_from_executed(msg_data)
    assert len(out) == 3
    assert out[0] == ("a.png", "sub", "output")
    assert out[2] == ("v.mp4", "vid", "output")


def test_collect_outputs_empty():
    assert comfy_ws._collect_outputs_from_executed({"output": {}}) == []
    assert comfy_ws._collect_outputs_from_executed({}) == []


# ────────────────────────────────────────────────────────────────────
# submit_and_listen happy + edge cases
# ────────────────────────────────────────────────────────────────────


def test_submit_and_listen_happy_path():
    image = b"\x89PNG\r\nfake-image-bytes"
    pid = "happy-pid"
    fake_ws = _FakeWS([
        # Initial status (no prompt_id)
        json.dumps({"type": "status",
                    "data": {"status": {"exec_info": {"queue_remaining": 0}}}}),
        # Execution start
        json.dumps({"type": "execution_start",
                    "data": {"prompt_id": pid}}),
        # Some node executing
        json.dumps({"type": "executing",
                    "data": {"node": "5", "prompt_id": pid}}),
        # Binary frame from SaveImageWebsocket
        _bin_frame(image),
        # Executed message with file output
        json.dumps({"type": "executed",
                    "data": {"node": "9", "prompt_id": pid,
                             "output": {"images": [
                                 {"filename": "x.png", "subfolder": "",
                                  "type": "output"}]}}}),
        # Done signal
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": pid}}),
    ])

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        result = comfy_ws.submit_and_listen(
            "http://comfy.test:8188",
            workflow={"5": {"class_type": "Mock", "inputs": {}}},
            client_id="cid-1",
            timeout=5.0,
        )
    finally:
        _stop_all(stops)

    assert result.prompt_id == pid
    assert result.file_outputs == [("x.png", "", "output")]
    assert len(result.binary_frames) == 1
    assert result.binary_frames[0].image_bytes == image
    assert result.binary_frames[0].format == comfy_ws.WS_FORMAT_PNG
    assert result.error_detail is None
    assert not result.interrupted
    assert fake_ws.closed


def test_submit_and_listen_passes_client_id_in_post():
    pid = "ci-test-pid"
    fake_ws = _FakeWS([
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": pid}}),
    ])

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = req.data
        captured["url"] = req.full_url
        return _make_post_response(pid)

    stops: List = []
    fake_connect = mock.MagicMock(return_value=fake_ws)
    p1 = mock.patch.object(comfy_ws, "_ws_connect", fake_connect)
    p1.start(); stops.append(p1.stop)
    p2 = mock.patch.object(comfy_ws.urlrequest, "urlopen",
                            side_effect=fake_urlopen)
    p2.start(); stops.append(p2.stop)

    try:
        comfy_ws.submit_and_listen(
            "http://comfy.test:8188",
            workflow={"1": {"class_type": "X", "inputs": {}}},
            client_id="my-client-id",
            timeout=5.0,
        )
    finally:
        _stop_all(stops)

    body = json.loads(captured["body"])
    assert body["client_id"] == "my-client-id"
    assert body["prompt"] == {"1": {"class_type": "X", "inputs": {}}}
    # And the ws URL contains the same client_id
    fake_connect.assert_called_once()
    ws_url = fake_connect.call_args[0][0]
    assert "clientId=my-client-id" in ws_url


def test_submit_and_listen_filters_other_prompts():
    """Messages with a different prompt_id should be ignored, even if
    they're 'executing node==None' (which would otherwise look like a
    done signal)."""
    pid = "ours"
    other = "someone-else"
    fake_ws = _FakeWS([
        # Other client's done -- ignore
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": other}}),
        # Other client's executed output -- ignore
        json.dumps({"type": "executed",
                    "data": {"node": "9", "prompt_id": other,
                             "output": {"images": [
                                 {"filename": "wrong.png",
                                  "subfolder": "", "type": "output"}]}}}),
        # Our done signal
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": pid}}),
    ])

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        result = comfy_ws.submit_and_listen(
            "http://comfy.test:8188",
            workflow={"1": {"class_type": "X", "inputs": {}}},
            timeout=5.0,
        )
    finally:
        _stop_all(stops)

    assert result.prompt_id == pid
    # Should NOT have collected the other client's wrong.png
    assert result.file_outputs == []


def test_submit_and_listen_execution_error():
    pid = "error-pid"
    fake_ws = _FakeWS([
        json.dumps({"type": "execution_error",
                    "data": {"prompt_id": pid,
                             "exception_type": "RuntimeError",
                             "exception_message": "OOM in KSampler",
                             "node_id": "5", "node_type": "KSampler"}}),
    ])

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        result = comfy_ws.submit_and_listen(
            "http://comfy.test:8188", workflow={}, timeout=5.0,
        )
    finally:
        _stop_all(stops)

    assert result.error_detail is not None
    assert "OOM in KSampler" in result.error_detail
    assert "KSampler" in result.error_detail


def test_submit_and_listen_interrupted():
    pid = "int-pid"
    fake_ws = _FakeWS([
        json.dumps({"type": "execution_interrupted",
                    "data": {"prompt_id": pid}}),
    ])

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        result = comfy_ws.submit_and_listen(
            "http://comfy.test:8188", workflow={}, timeout=5.0,
        )
    finally:
        _stop_all(stops)

    assert result.interrupted is True


def test_submit_and_listen_post_unreachable():
    pid = "n/a"
    fake_ws = _FakeWS([])  # Won't be used
    stops: List = []
    try:
        _patch_ws_and_post(
            stops, fake_ws,
            urllib.error.URLError("connection refused"))
        try:
            comfy_ws.submit_and_listen(
                "http://comfy.test:8188", workflow={}, timeout=2.0,
            )
        except comfy_ws.WSUnreachable as exc:
            assert "comfy.test:8188" in str(exc)
            return
        assert False, "expected WSUnreachable"
    finally:
        _stop_all(stops)


def test_submit_and_listen_post_http_error():
    fake_ws = _FakeWS([])
    err = urllib.error.HTTPError(
        "http://x", 400, "Bad Request", {},
        io.BytesIO(b'{"node_errors": {"5": {"errors": [{"message": "nope"}]}}}'),
    )

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, err)
        try:
            comfy_ws.submit_and_listen(
                "http://comfy.test:8188", workflow={}, timeout=2.0,
            )
        except comfy_ws.WSError as exc:
            assert "rejected workflow" in str(exc)
            return
        assert False, "expected WSError on HTTP 400"
    finally:
        _stop_all(stops)


def test_submit_and_listen_progress_callback_fires():
    pid = "prog-pid"
    fake_ws = _FakeWS([
        json.dumps({"type": "execution_start",
                    "data": {"prompt_id": pid}}),
        json.dumps({"type": "progress",
                    "data": {"value": 5, "max": 20, "prompt_id": pid}}),
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": pid}}),
    ])

    progress_calls = []
    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        comfy_ws.submit_and_listen(
            "http://comfy.test:8188", workflow={}, timeout=5.0,
            on_progress=lambda s, d: progress_calls.append((s, d)),
        )
    finally:
        _stop_all(stops)

    stages = [s for s, _ in progress_calls]
    # We saw at least the connect, submit, listen, exec_start, progress
    for expected in ("ws.connect", "ws.submit", "ws.listen",
                       "ws.exec_start", "ws.progress"):
        assert expected in stages, f"missing {expected}: got {stages}"


# ────────────────────────────────────────────────────────────────────
# dispatch_workflow with use_websocket=True
# ────────────────────────────────────────────────────────────────────


def test_dispatch_workflow_ws_happy():
    pid = "disp-ws-pid"
    image = b"\x89PNG\r\nws-image"
    fake_ws = _FakeWS([
        json.dumps({"type": "execution_start",
                    "data": {"prompt_id": pid}}),
        _bin_frame(image),
        json.dumps({"type": "executed",
                    "data": {"node": "9", "prompt_id": pid,
                             "output": {"images": [
                                 {"filename": "out.png", "subfolder": "",
                                  "type": "output"}]}}}),
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": pid}}),
    ])

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        result = dispatch.dispatch_workflow(
            "http://comfy.test:8188",
            workflow={"1": {"class_type": "X", "inputs": {}}},
            timeout=5.0, trusted=True, free_vram=False,
            privacy=False, use_websocket=True,
        )
    finally:
        _stop_all(stops)

    assert result.transport == "websocket"
    assert result.prompt_id == pid
    assert result.outputs == [("out.png", "", "output")]
    assert len(result.binary_outputs) == 1
    assert result.binary_outputs[0][0] == "png"
    assert result.binary_outputs[0][1] == image


def test_dispatch_workflow_ws_fallback_to_poll():
    """When use_websocket=True but ws connect fails, fall back to
    poll path."""
    pid = "poll-fallback"
    fake_ws = _FakeWS([])  # Won't be used; connect will fail

    # The ws path will fail at _ws_connect; the poll path then takes
    # over. Mock both:
    #   1. ws connect raises -> WSUnreachable
    #   2. poll path: POST /prompt then GET /history
    poll_post_resp = _make_post_response(pid)
    poll_history_resp = mock.MagicMock()
    poll_history_resp.read.return_value = json.dumps({
        pid: {
            "status": {"status_str": "completed"},
            "outputs": {"9": {"images": [
                {"filename": "fb.png", "subfolder": "",
                 "type": "output"}]}},
        },
    }).encode("utf-8")
    poll_history_cm = mock.MagicMock()
    poll_history_cm.__enter__.return_value = poll_history_resp
    poll_history_cm.__exit__.return_value = False

    def fake_urlopen(req, timeout=None):
        url = getattr(req, "full_url", str(req))
        if "/prompt" in url:
            return poll_post_resp
        if "/history/" in url:
            return poll_history_cm
        raise AssertionError(f"unexpected url: {url}")

    stops: List = []
    p1 = mock.patch.object(
        comfy_ws, "_ws_connect",
        side_effect=ConnectionRefusedError("nope"))
    p1.start(); stops.append(p1.stop)
    # Both modules' urlopen need patching: comfy_ws (for the ws-path
    # /prompt) and dispatch (for the poll-path /prompt + /history).
    p2 = mock.patch.object(comfy_ws.urlrequest, "urlopen",
                            side_effect=fake_urlopen)
    p2.start(); stops.append(p2.stop)
    p3 = mock.patch.object(dispatch.urllib.request, "urlopen",
                            side_effect=fake_urlopen)
    p3.start(); stops.append(p3.stop)

    try:
        result = dispatch.dispatch_workflow(
            "http://comfy.test:8188",
            workflow={"1": {"class_type": "X", "inputs": {}}},
            timeout=5.0, trusted=True, free_vram=False, privacy=False,
            use_websocket=True, ws_fallback_to_poll=True,
        )
    finally:
        _stop_all(stops)

    assert result.transport == "poll"
    assert result.outputs == [("fb.png", "", "output")]
    # Should have a warning explaining the fallback
    assert any("falling back to poll" in w.lower()
                for w in result.warnings), result.warnings


def test_dispatch_workflow_ws_strict_no_fallback():
    """ws_fallback_to_poll=False: ws failure must raise."""
    fake_ws = _FakeWS([])
    stops: List = []
    p1 = mock.patch.object(
        comfy_ws, "_ws_connect",
        side_effect=ConnectionRefusedError("nope"))
    p1.start(); stops.append(p1.stop)

    try:
        dispatch.dispatch_workflow(
            "http://comfy.test:8188",
            workflow={"1": {"class_type": "X", "inputs": {}}},
            timeout=5.0, trusted=True, free_vram=False, privacy=False,
            use_websocket=True, ws_fallback_to_poll=False,
        )
    except RuntimeError as exc:
        assert "ws dispatch failed" in str(exc)
        return
    finally:
        _stop_all(stops)
    assert False, "expected RuntimeError when ws_fallback_to_poll=False"


def test_dispatch_workflow_ws_execution_error_raises():
    """Execution error with NO outputs must raise RuntimeError."""
    pid = "err-pid"
    fake_ws = _FakeWS([
        json.dumps({"type": "execution_error",
                    "data": {"prompt_id": pid,
                             "exception_message": "ckpt missing"}}),
    ])

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        dispatch.dispatch_workflow(
            "http://comfy.test:8188", workflow={},
            timeout=5.0, trusted=True, free_vram=False, privacy=False,
            use_websocket=True, ws_fallback_to_poll=False,
        )
    except RuntimeError as exc:
        assert "execution failed" in str(exc) or "ckpt missing" in str(exc)
        return
    finally:
        _stop_all(stops)
    assert False, "expected RuntimeError on execution_error"


def test_dispatch_workflow_ws_execution_error_with_outputs_partial():
    """Execution error WITH outputs: don't raise; warn + return."""
    pid = "partial-pid"
    fake_ws = _FakeWS([
        json.dumps({"type": "executed",
                    "data": {"node": "9", "prompt_id": pid,
                             "output": {"images": [
                                 {"filename": "partial.png",
                                  "subfolder": "", "type": "output"}]}}}),
        json.dumps({"type": "execution_error",
                    "data": {"prompt_id": pid,
                             "exception_message": "side node failed"}}),
    ])

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        result = dispatch.dispatch_workflow(
            "http://comfy.test:8188", workflow={},
            timeout=5.0, trusted=True, free_vram=False, privacy=False,
            use_websocket=True, ws_fallback_to_poll=False,
        )
    finally:
        _stop_all(stops)

    assert result.transport == "websocket"
    assert result.outputs == [("partial.png", "", "output")]
    assert any("partial success" in w.lower() for w in result.warnings)


def test_dispatch_workflow_poll_path_unchanged():
    """Default use_websocket=False -- poll path should still work
    untouched. Shape of DispatchResult includes the new fields with
    defaults."""
    pid = "poll-pid"
    poll_post = _make_post_response(pid)
    history_resp = mock.MagicMock()
    history_resp.read.return_value = json.dumps({
        pid: {
            "status": {"status_str": "completed"},
            "outputs": {"9": {"images": [
                {"filename": "p.png", "subfolder": "",
                 "type": "output"}]}},
        },
    }).encode("utf-8")
    history_cm = mock.MagicMock()
    history_cm.__enter__.return_value = history_resp
    history_cm.__exit__.return_value = False

    def fake_urlopen(req, timeout=None):
        url = getattr(req, "full_url", str(req))
        if "/prompt" in url:
            return poll_post
        if "/history/" in url:
            return history_cm
        raise AssertionError(f"unexpected url: {url}")

    with mock.patch.object(dispatch.urllib.request, "urlopen",
                             side_effect=fake_urlopen):
        result = dispatch.dispatch_workflow(
            "http://comfy.test:8188", workflow={},
            timeout=5.0, trusted=True, free_vram=False, privacy=False,
        )

    assert result.transport == "poll"
    assert result.outputs == [("p.png", "", "output")]
    assert result.binary_outputs == []


# ────────────────────────────────────────────────────────────────────
# node_factory ETN helpers
# ────────────────────────────────────────────────────────────────────


def test_etn_load_image_base64_emits_correct_class():
    nf = node_factory.NodeFactory()
    nid = nf.etn_load_image_base64("base64-encoded-bytes")
    wf = nf.build()
    assert wf[nid]["class_type"] == "ETN_LoadImageBase64"
    assert wf[nid]["inputs"]["image"] == "base64-encoded-bytes"


def test_etn_send_image_websocket_emits_correct_class():
    nf = node_factory.NodeFactory()
    src = nf.etn_load_image_base64("aGk=")
    nid = nf.etn_send_image_websocket([src, 0], format="JPEG")
    wf = nf.build()
    assert wf[nid]["class_type"] == "ETN_SendImageWebSocket"
    assert wf[nid]["inputs"]["images"] == [src, 0]
    assert wf[nid]["inputs"]["format"] == "JPEG"


def test_save_image_websocket_emits_correct_class():
    nf = node_factory.NodeFactory()
    src = nf.etn_load_image_base64("aGk=")
    nid = nf.save_image_websocket([src, 0])
    wf = nf.build()
    assert wf[nid]["class_type"] == "SaveImageWebsocket"
    assert wf[nid]["inputs"]["images"] == [src, 0]
    # Core SaveImageWebsocket has no format arg (always PNG)
    assert "format" not in wf[nid]["inputs"]


def test_full_inline_workflow_shape():
    """Sanity: a full input-via-base64 / output-via-ws workflow
    builds with the expected class_types and node count."""
    nf = node_factory.NodeFactory()
    img_id = nf.etn_load_image_base64("aGVsbG8=")
    save_id = nf.save_image_websocket([img_id, 0], disk_backup=False)
    wf = nf.build()
    assert len(wf) == 2
    classes = sorted(node["class_type"] for node in wf.values())
    assert classes == ["ETN_LoadImageBase64", "SaveImageWebsocket"]


# ────────────────────────────────────────────────────────────────────
# Label discriminator (multi-output builders)
# ────────────────────────────────────────────────────────────────────


def test_save_image_websocket_label_attaches_meta():
    """``label=`` writes to the node's ``_meta`` dict."""
    nf = node_factory.NodeFactory()
    src = nf.etn_load_image_base64("aGk=")
    nid = nf.save_image_websocket([src, 0], label="sam3_mask")
    wf = nf.build()
    assert wf[nid]["_meta"] == {"label": "sam3_mask"}


def test_save_image_websocket_no_label_omits_meta():
    """No ``label=`` -> no ``_meta`` (preserve pre-OQ7 wire shape)."""
    nf = node_factory.NodeFactory()
    src = nf.etn_load_image_base64("aGk=")
    nid = nf.save_image_websocket([src, 0])
    wf = nf.build()
    assert "_meta" not in wf[nid]


def test_dispatch_workflow_ws_labels_multi_output():
    """Two SaveImageWebsocket nodes with different labels -> dispatcher
    threads each frame's producing node label through to
    binary_outputs[i][2]. Mirrors the build_sam3_segment shape."""
    pid = "label-pid"
    img_subject = b"\x89PNG\r\nsubject"
    img_mask = b"\x89PNG\r\nmask"
    fake_ws = _FakeWS([
        json.dumps({"type": "execution_start",
                    "data": {"prompt_id": pid}}),
        json.dumps({"type": "executing",
                    "data": {"node": "30", "prompt_id": pid}}),
        _bin_frame(img_subject),
        json.dumps({"type": "executing",
                    "data": {"node": "31", "prompt_id": pid}}),
        _bin_frame(img_mask),
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": pid}}),
    ])

    workflow = {
        "30": {"class_type": "SaveImageWebsocket",
               "inputs": {"images": ["1", 0]},
               "_meta": {"label": "sam3_subject"}},
        "31": {"class_type": "SaveImageWebsocket",
               "inputs": {"images": ["2", 0]},
               "_meta": {"label": "sam3_mask"}},
    }

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        result = dispatch.dispatch_workflow(
            "http://comfy.test:8188",
            workflow=workflow,
            timeout=5.0, trusted=True, free_vram=False,
            privacy=False, use_websocket=True,
        )
    finally:
        _stop_all(stops)

    assert result.transport == "websocket"
    assert len(result.binary_outputs) == 2
    # Order matches receipt order (subject first, mask second).
    assert result.binary_outputs[0] == ("png", img_subject, "sam3_subject")
    assert result.binary_outputs[1] == ("png", img_mask, "sam3_mask")


def test_dispatch_workflow_ws_label_none_when_unset():
    """Single ws save with no label -> third tuple element is None.
    Backward compat: the GIMP fold-in handles None as 'no label'."""
    pid = "nolabel-pid"
    img = b"\x89PNG\r\nplain"
    fake_ws = _FakeWS([
        json.dumps({"type": "executing",
                    "data": {"node": "7", "prompt_id": pid}}),
        _bin_frame(img),
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": pid}}),
    ])

    workflow = {
        "7": {"class_type": "SaveImageWebsocket",
              "inputs": {"images": ["1", 0]}},
    }

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        result = dispatch.dispatch_workflow(
            "http://comfy.test:8188",
            workflow=workflow,
            timeout=5.0, trusted=True, free_vram=False,
            privacy=False, use_websocket=True,
        )
    finally:
        _stop_all(stops)

    assert len(result.binary_outputs) == 1
    assert result.binary_outputs[0] == ("png", img, None)


def test_ws_image_frame_carries_node_id():
    """``submit_and_listen`` tags each binary frame with the most recent
    ``executing`` node's id, so the dispatcher can map frame->label."""
    pid = "frame-tag-pid"
    img_a = b"frame-a"
    img_b = b"frame-b"
    fake_ws = _FakeWS([
        json.dumps({"type": "executing",
                    "data": {"node": "alpha", "prompt_id": pid}}),
        _bin_frame(img_a),
        json.dumps({"type": "executing",
                    "data": {"node": "beta", "prompt_id": pid}}),
        _bin_frame(img_b),
        json.dumps({"type": "executing",
                    "data": {"node": None, "prompt_id": pid}}),
    ])

    stops: List = []
    try:
        _patch_ws_and_post(stops, fake_ws, _make_post_response(pid))
        ws_result = comfy_ws.submit_and_listen(
            "http://comfy.test:8188", workflow={}, timeout=5.0,
        )
    finally:
        _stop_all(stops)

    assert len(ws_result.binary_frames) == 2
    assert ws_result.binary_frames[0].node_id == "alpha"
    assert ws_result.binary_frames[0].image_bytes == img_a
    assert ws_result.binary_frames[1].node_id == "beta"
    assert ws_result.binary_frames[1].image_bytes == img_b


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────


def main() -> int:
    print("Phase 9 ws + ETN tests")
    print("=" * 60)
    tests = [
        ("build_ws_url http->ws", test_build_ws_url_http_to_ws),
        ("build_ws_url https->wss", test_build_ws_url_https_to_wss),
        ("build_ws_url strips slash",
            test_build_ws_url_strips_trailing_slash),
        ("build_ws_url no scheme",
            test_build_ws_url_no_scheme_defaults_to_ws),
        ("decode_binary_frame png", test_decode_binary_frame_png),
        ("decode_binary_frame jpg", test_decode_binary_frame_jpg),
        ("decode_binary_frame too short",
            test_decode_binary_frame_too_short),
        ("decode_binary_frame unknown event",
            test_decode_binary_frame_unknown_event_returns_none),
        ("collect_outputs images+gifs",
            test_collect_outputs_images_and_gifs),
        ("collect_outputs empty", test_collect_outputs_empty),
        ("submit_and_listen happy", test_submit_and_listen_happy_path),
        ("submit_and_listen passes client_id",
            test_submit_and_listen_passes_client_id_in_post),
        ("submit_and_listen filters other prompts",
            test_submit_and_listen_filters_other_prompts),
        ("submit_and_listen execution_error",
            test_submit_and_listen_execution_error),
        ("submit_and_listen interrupted",
            test_submit_and_listen_interrupted),
        ("submit_and_listen post unreachable",
            test_submit_and_listen_post_unreachable),
        ("submit_and_listen post http error",
            test_submit_and_listen_post_http_error),
        ("submit_and_listen progress callback",
            test_submit_and_listen_progress_callback_fires),
        ("dispatch_workflow ws happy", test_dispatch_workflow_ws_happy),
        ("dispatch_workflow ws fallback to poll",
            test_dispatch_workflow_ws_fallback_to_poll),
        ("dispatch_workflow ws strict no-fallback",
            test_dispatch_workflow_ws_strict_no_fallback),
        ("dispatch_workflow ws execution_error raises",
            test_dispatch_workflow_ws_execution_error_raises),
        ("dispatch_workflow ws partial success",
            test_dispatch_workflow_ws_execution_error_with_outputs_partial),
        ("dispatch_workflow poll path unchanged",
            test_dispatch_workflow_poll_path_unchanged),
        ("etn_load_image_base64 class_type",
            test_etn_load_image_base64_emits_correct_class),
        ("etn_send_image_websocket class_type",
            test_etn_send_image_websocket_emits_correct_class),
        ("save_image_websocket class_type",
            test_save_image_websocket_emits_correct_class),
        ("full inline workflow shape", test_full_inline_workflow_shape),
        ("save_image_websocket label attaches _meta",
            test_save_image_websocket_label_attaches_meta),
        ("save_image_websocket no-label omits _meta",
            test_save_image_websocket_no_label_omits_meta),
        ("dispatch ws labels multi-output",
            test_dispatch_workflow_ws_labels_multi_output),
        ("dispatch ws label None when unset",
            test_dispatch_workflow_ws_label_none_when_unset),
        ("WSImageFrame carries node_id",
            test_ws_image_frame_carries_node_id),
    ]

    for name, fn in tests:
        _run(name, fn)

    print("=" * 60)
    if _failures:
        print(f"FAILED ({len(_failures)} of {len(tests)}):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print(f"All {len(tests)} tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
