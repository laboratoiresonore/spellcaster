"""ComfyUI WebSocket client + ws-based dispatch -- Phase 9.

Replaces ``dispatch.py``'s ``/history/<prompt_id>`` poll loop with a
synchronous websocket subscription to ``/ws?clientId=<uuid>``. Listens
for the canonical completion signal (``type=executing`` with
``data.node==None`` and ``data.prompt_id==pid``) and consumes binary
image frames sent by ``ETN_SendImageWebSocket`` /
``SaveImageWebsocket`` (8-byte header + image bytes).

Why this exists
---------------

Two distinct wins (architecture study §sprint-1, EVAL_LANGGRAPH_COMFYSCRIPT.md):

  1. **Kill the /history poll race.** The poll loop fires GETs every
     500 ms; tight workflows (<2 s on warm caches) routinely complete
     between polls and the client either misses the result entirely
     or sees a stale empty entry. With ws, ComfyUI pushes an
     ``executing`` message with ``node==None`` the instant the prompt
     graph finishes -- no race.

  2. **Eliminate the filesystem round-trip on output.** Today, output
     images go ``SaveImage -> output/foo.png -> /view?filename=foo.png``.
     With ``SaveImageWebsocket`` (built into ComfyUI core) /
     ``ETN_SendImageWebSocket`` (Acly/comfyui-tooling-nodes), the image
     bytes arrive as a binary ws frame from the same socket as the
     status messages. No file ever lands in ``output/``. Privacy
     improvement and ~50-200 ms saved per image.

Pair with ``ETN_LoadImageBase64`` (Acly's pack) to embed input images
as base64 inside the prompt JSON itself, eliminating the input-side
``POST /upload/image`` + ``GET /view`` round-trip too. See
``node_factory.NodeFactory.etn_load_image_base64`` and
``node_factory.NodeFactory.etn_send_image_websocket``.

Wire format (binary frames)
---------------------------

Per ComfyUI's ``server.py``::

    header = struct.pack(">II", event_type, image_format)
    frame  = header + image_bytes

  ``event_type``:
      1 = preview/output image (the only one we care about)
  ``image_format``:
      1 = JPG, 2 = PNG, 3 = JPEG (older), 4 = WEBP (newer)

We expose the frames as ``WSImageFrame`` dataclasses with the raw
bytes; callers decode if they need PIL objects.

Dependency
----------

Uses ``websockets.sync.client`` (modern synchronous API in the
``websockets`` package). The Spellcaster bundle pre-installs
``websockets`` per the architecture study; falling back to
``websocket-client`` is documented but not implemented (both are
available in the dev tree, so the import path is straightforward to
swap if a future ComfyUI/protocol change requires it).
"""
from __future__ import annotations

import dataclasses
import json
import struct
import time
import uuid
from typing import Any, Callable, Iterator, List, Mapping, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

# ── Binary frame protocol ─────────────────────────────────────────

WS_EVENT_PREVIEW_IMAGE = 1
WS_FORMAT_JPG = 1
WS_FORMAT_PNG = 2
WS_FORMAT_JPEG_LEGACY = 3
WS_FORMAT_WEBP = 4
_WS_FORMAT_NAMES = {
    WS_FORMAT_JPG: "jpg",
    WS_FORMAT_PNG: "png",
    WS_FORMAT_JPEG_LEGACY: "jpeg",
    WS_FORMAT_WEBP: "webp",
}
_WS_HEADER_FMT = ">II"  # 2x uint32 big-endian -- per ComfyUI server.py
_WS_HEADER_LEN = 8


@dataclasses.dataclass(frozen=True)
class WSImageFrame:
    """One binary image frame from ComfyUI.

    ``event`` is the WS_EVENT_* code (currently always
    WS_EVENT_PREVIEW_IMAGE in ComfyUI; the field is preserved for
    forward compat). ``format`` is one of WS_FORMAT_*.

    ``image_bytes`` are the raw encoded bytes -- ready to write to a
    file or feed into PIL.Image.open(BytesIO(...)).
    """
    event: int
    format: int
    image_bytes: bytes
    received_at: float  # time.monotonic() at frame receipt; for diag

    @property
    def format_name(self) -> str:
        return _WS_FORMAT_NAMES.get(self.format, f"fmt{self.format}")

    def __repr__(self) -> str:  # pragma: no cover - just diag
        return (f"<WSImageFrame event={self.event} "
                f"format={self.format_name} bytes={len(self.image_bytes)}>")


@dataclasses.dataclass
class WSDispatchResult:
    """ws-side raw collection from a single prompt execution.

    The dispatch_workflow caller adapts this into a DispatchResult.
    """
    prompt_id: str
    file_outputs: List[Tuple[str, str, str]]  # (filename, subfolder, type)
    binary_frames: List[WSImageFrame]
    text_messages: List[Mapping[str, Any]]
    elapsed: float
    error_detail: Optional[str] = None  # set if execution_error fired
    interrupted: bool = False
    cached_nodes: List[str] = dataclasses.field(default_factory=list)


# ── Errors ────────────────────────────────────────────────────────


class WSError(RuntimeError):
    """Anything the ws path can fail on."""


class WSUnreachable(WSError):
    """Socket-level failure: connection refused, DNS, timeout."""


class WSTimeout(WSError):
    """Hit the per-call deadline before completion signal."""


class WSExecutionError(WSError):
    """ComfyUI sent ``execution_error`` for our prompt."""


class WSDependencyMissing(WSError):
    """The ``websockets`` package isn't importable.

    Raised lazily so importing this module doesn't fail when
    callers only want the constants / dataclasses.
    """


# ── Lazy import of ``websockets`` ─────────────────────────────────


def _ws_connect(url: str, *, timeout: float):
    """Open a synchronous websocket. Lazy import keeps the package
    optional at module load (some test paths don't need a real ws)."""
    try:
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover - dep is bundled
        raise WSDependencyMissing(
            "the 'websockets' package is required for ws dispatch; "
            "install via the bundle's python_embedded or "
            "`pip install websockets`") from exc
    return connect(url, open_timeout=timeout, close_timeout=timeout)


# ── Core client ───────────────────────────────────────────────────


def _build_ws_url(server: str, client_id: str) -> str:
    """``http://host:8188`` -> ``ws://host:8188/ws?clientId=<id>``."""
    base = server.rstrip("/")
    if base.startswith("https://"):
        scheme = "wss://"
        rest = base[len("https://"):]
    elif base.startswith("http://"):
        scheme = "ws://"
        rest = base[len("http://"):]
    else:
        scheme = "ws://"
        rest = base
    return f"{scheme}{rest}/ws?clientId={client_id}"


def _submit_prompt(server: str, workflow: Mapping[str, Any],
                    client_id: str, *,
                    timeout: float = 10.0,
                    extra_data: Optional[Mapping[str, Any]] = None,
                    ) -> str:
    """POST /prompt with ``client_id`` so SaveImageWebsocket frames
    route to our connection. Returns ``prompt_id``.

    The ``client_id`` field is REQUIRED for the binary-frame return
    path. Without it, ComfyUI emits the binary frame to whatever ws
    happens to be in its registry; with it, the frame goes only to
    the matching socket.
    """
    payload: dict[str, Any] = {
        "prompt": workflow,
        "client_id": client_id,
    }
    if extra_data:
        payload["extra_data"] = dict(extra_data)
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        f"{server.rstrip('/')}/prompt",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        # Surface ComfyUI's structured error so the caller can show
        # node_errors detail (matches the poll path's behavior in
        # dispatch.py:384-400).
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            err_body = str(exc)
        raise WSError(f"ComfyUI rejected workflow: {err_body[:500]}") from exc
    except urlerror.URLError as exc:
        raise WSUnreachable(f"ComfyUI is offline at {server}: {exc}") from exc

    pid = (data or {}).get("prompt_id")
    if not pid:
        raise WSError(f"ComfyUI did not return a prompt_id; got {data!r}")
    return str(pid)


def _decode_binary_frame(blob: bytes, *,
                         received_at: float) -> Optional[WSImageFrame]:
    """Decode an 8-byte-header + payload binary frame. Returns None
    if the frame is too short to be a valid image frame.

    Defensive: ComfyUI occasionally emits non-image binary messages
    (e.g. progress with a different header shape in newer versions).
    Returning None here lets the listen loop ignore unknown shapes
    rather than aborting the whole dispatch."""
    if len(blob) < _WS_HEADER_LEN:
        return None
    event, fmt = struct.unpack(_WS_HEADER_FMT, blob[:_WS_HEADER_LEN])
    if event != WS_EVENT_PREVIEW_IMAGE:
        return None
    return WSImageFrame(
        event=event,
        format=fmt,
        image_bytes=blob[_WS_HEADER_LEN:],
        received_at=received_at,
    )


def _collect_outputs_from_executed(
        msg_data: Mapping[str, Any],
        ) -> List[Tuple[str, str, str]]:
    """Pull (filename, subfolder, type) tuples out of an ``executed``
    message's ``output`` dict. Handles both ``images`` and ``gifs``
    (VHS_VideoCombine) keys -- mirrors dispatch.py's poll path
    behavior."""
    out: List[Tuple[str, str, str]] = []
    output = msg_data.get("output") or {}
    for img in output.get("images", []) or []:
        out.append((
            img.get("filename", ""),
            img.get("subfolder", ""),
            img.get("type", "output"),
        ))
    for vid in output.get("gifs", []) or []:
        out.append((
            vid.get("filename", ""),
            vid.get("subfolder", ""),
            vid.get("type", "output"),
        ))
    return out


def submit_and_listen(
        server: str,
        workflow: Mapping[str, Any],
        *,
        client_id: Optional[str] = None,
        timeout: float = 300.0,
        connect_timeout: float = 10.0,
        on_progress: Optional[Callable[[str, str], None]] = None,
        extra_data: Optional[Mapping[str, Any]] = None,
        ) -> WSDispatchResult:
    """Single entry point: open ws, submit prompt, listen until done.

    Returns a ``WSDispatchResult`` with all collected outputs +
    binary frames. Raises ``WSError`` (or a subclass) on failure.

    The order matters: connect ws BEFORE submitting the prompt. If
    you POST first and connect second, ComfyUI may have already
    finished and emitted the executing-done signal that you'll then
    miss. Race-free order: connect -> submit -> listen.
    """
    client_id = client_id or uuid.uuid4().hex
    ws_url = _build_ws_url(server, client_id)

    def _progress(stage: str, detail: str = "") -> None:
        if on_progress:
            try:
                on_progress(stage, detail)
            except Exception:  # noqa: BLE001 - never let progress crash dispatch
                pass

    _progress("ws.connect", ws_url)
    try:
        ws = _ws_connect(ws_url, timeout=connect_timeout)
    except WSDependencyMissing:
        raise
    except Exception as exc:  # noqa: BLE001
        # websockets surfaces a variety of exception types
        # (ConnectionRefusedError, OSError, InvalidStatus, …); fold
        # them all into WSUnreachable.
        raise WSUnreachable(f"could not connect to {ws_url}: {exc}") from exc

    text_messages: List[Mapping[str, Any]] = []
    binary_frames: List[WSImageFrame] = []
    file_outputs: List[Tuple[str, str, str]] = []
    cached_nodes: List[str] = []
    interrupted = False
    error_detail: Optional[str] = None
    t0 = time.monotonic()
    deadline = t0 + timeout

    try:
        # Submit AFTER opening the ws so we don't miss messages.
        _progress("ws.submit", "")
        prompt_id = _submit_prompt(
            server, workflow, client_id,
            timeout=connect_timeout, extra_data=extra_data,
        )
        _progress("ws.listen", prompt_id)

        # Listen loop
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WSTimeout(
                    f"timeout after {timeout}s waiting for prompt "
                    f"{prompt_id} (ws path)")
            try:
                msg = ws.recv(timeout=min(remaining, 10.0))
            except TimeoutError:
                # No message yet; loop and check the outer deadline.
                continue
            except Exception as exc:  # noqa: BLE001
                # Connection died mid-listen. Treat as ws failure so
                # the caller can fall back to polling.
                raise WSError(
                    f"ws connection died mid-listen: {exc}") from exc

            recv_time = time.monotonic()
            if isinstance(msg, (bytes, bytearray)):
                frame = _decode_binary_frame(bytes(msg), received_at=recv_time)
                if frame is not None:
                    binary_frames.append(frame)
                continue

            try:
                obj = json.loads(msg)
            except json.JSONDecodeError:
                # Unknown text shape -- log and skip
                continue

            mtype = obj.get("type")
            mdata = obj.get("data") or {}
            text_messages.append(obj)

            # Filter to OUR prompt only -- ComfyUI broadcasts every
            # message to every connected client_id. data.prompt_id
            # is set on the messages we care about.
            owner_pid = mdata.get("prompt_id")
            if owner_pid is not None and owner_pid != prompt_id:
                continue

            if mtype == "execution_start":
                _progress("ws.exec_start", prompt_id)
                continue

            if mtype == "execution_cached":
                cached_nodes = list(mdata.get("nodes") or [])
                continue

            if mtype == "executing":
                node_id = mdata.get("node")
                if node_id is None and owner_pid == prompt_id:
                    # Done signal: the prompt graph has fully executed.
                    break
                _progress("ws.executing", str(node_id) if node_id else "")
                continue

            if mtype == "executed":
                file_outputs.extend(_collect_outputs_from_executed(mdata))
                continue

            if mtype == "execution_error":
                error_detail = _format_execution_error(mdata)
                break

            if mtype == "execution_interrupted":
                interrupted = True
                break

            # progress / status messages: surface but don't act on them
            if mtype == "progress":
                value = mdata.get("value")
                maxv = mdata.get("max")
                if value is not None and maxv:
                    _progress("ws.progress", f"{value}/{maxv}")
                continue

    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass

    elapsed = time.monotonic() - t0
    return WSDispatchResult(
        prompt_id=prompt_id,
        file_outputs=file_outputs,
        binary_frames=binary_frames,
        text_messages=text_messages,
        elapsed=elapsed,
        error_detail=error_detail,
        interrupted=interrupted,
        cached_nodes=cached_nodes,
    )


def _format_execution_error(data: Mapping[str, Any]) -> str:
    """Best-effort error string from an execution_error message.
    Mirrors dispatch.extract_execution_error's spirit for the ws
    payload shape (which has slightly different keys: 'exception_message',
    'node_id', 'node_type', 'traceback')."""
    parts: list[str] = []
    et = data.get("exception_type")
    em = data.get("exception_message")
    if et and em:
        parts.append(f"{et}: {em}")
    elif em:
        parts.append(str(em))
    nid = data.get("node_id")
    nt = data.get("node_type")
    if nid or nt:
        parts.append(f"node={nt or '?'}({nid or '?'})")
    if not parts:
        # Fall through to the raw shape so the next debugger has
        # something to work with -- same spirit as the poll path.
        parts.append(json.dumps(dict(data))[:400])
    return " | ".join(parts)


__all__ = [
    "WS_EVENT_PREVIEW_IMAGE",
    "WS_FORMAT_JPG",
    "WS_FORMAT_PNG",
    "WS_FORMAT_JPEG_LEGACY",
    "WS_FORMAT_WEBP",
    "WSImageFrame",
    "WSDispatchResult",
    "WSError",
    "WSUnreachable",
    "WSTimeout",
    "WSExecutionError",
    "WSDependencyMissing",
    "submit_and_listen",
]
