"""safe_fetch — allowlist + audit + size-cap wrapper for HTTP fetches.

Wraps ``urllib.request.urlopen`` so every outbound call in the
spellcaster ecosystem lands in a small choke point that:

  1. Rejects hosts not in the allowlist (Issue #14 defense).
  2. Refuses responses whose ``Content-Length`` header (or actual
     streamed body) exceeds a caller-supplied byte cap.
  3. Emits an append-only audit line at
     ``~/.voodoomaster/fetch_audit.jsonl`` so a maintainer can
     tell after the fact WHO fetched WHAT, WHEN, and HOW BIG the
     response was — even if the caller silently discarded it.

Public surface (all three take a ``timeout`` in seconds and a
``max_bytes`` ceiling):

    safe_get(url, timeout=30, max_bytes=MAX_BYTES,
             headers=None) -> bytes
    safe_post(url, data, timeout=30, max_bytes=MAX_BYTES,
              headers=None) -> bytes
    safe_urlopen(url_or_req, timeout=30,
                 max_bytes=MAX_BYTES) -> _AuditedResponse
        # Rare — only for streaming reads. Callers use it as a
        # context manager and read chunks with .read(n). The wrapper
        # tracks bytes + sha256 across reads and logs on close.

Refusals raise :class:`SafeFetchError`; HTTP / OS errors are
re-raised unchanged so existing ``except urllib.error.URLError``
branches keep working after migration.

The allowlist lives at module scope so an operator can extend it
without touching call sites::

    from spellcaster_core.safe_fetch import ALLOWED_HOSTS
    ALLOWED_HOSTS = frozenset(ALLOWED_HOSTS | {"my.host"})

The audit path can be overridden via the
``SPELLCASTER_FETCH_AUDIT_PATH`` env var — used by tests and by
sandboxed operator runs that want the log somewhere other than
``~/.voodoomaster/``. A log-write failure never blocks a fetch;
we ``print(..., file=sys.stderr)`` and carry on.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Union

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# Hostname allowlist. Membership is exact-match against the parsed
# ``.hostname`` component of the URL — a URL like
# ``https://evil.example.com/@raw.githubusercontent.com/…`` parses
# hostname="evil.example.com" and is refused. ``hf.co`` is the canonical
# short domain some Hugging Face flows redirect to; keep it or those
# redirects will break.
ALLOWED_HOSTS = frozenset({
    "raw.githubusercontent.com",
    "api.github.com",
    "huggingface.co",
    "hf.co",
    "civitai.com",
    "127.0.0.1",
    "localhost",
})

# Default byte cap. Sized to fit the largest legitimate blob we
# currently fetch (~50 MB plugin update blobs) with a safety margin.
# Callers that need less should pass their own ``max_bytes`` — going
# larger requires editing the module.
MAX_BYTES = 64 * 1024 * 1024

# Default audit path. Overridable via env var for tests / sandbox runs.
_DEFAULT_AUDIT_PATH = Path.home() / ".voodoomaster" / "fetch_audit.jsonl"

# Sentinel status strings for the audit log's ``status`` field.
_STATUS_REFUSED_ALLOWLIST = "REFUSED_ALLOWLIST"
_STATUS_REFUSED_SIZE_CAP = "REFUSED_SIZE_CAP"
_STATUS_ERROR = "ERROR"


class SafeFetchError(Exception):
    """Raised when the wrapper refuses a fetch (allowlist / size cap).

    Distinct from :class:`urllib.error.URLError` so callers can tell
    a policy refusal from a network failure. Subclasses of
    ``URLError`` (including ``HTTPError``) are re-raised unchanged.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _audit_path() -> Path:
    """Resolve the audit file path, honoring the env-var override."""
    override = os.environ.get("SPELLCASTER_FETCH_AUDIT_PATH")
    if override:
        return Path(override)
    return _DEFAULT_AUDIT_PATH


def _extract_host(url: str) -> Optional[str]:
    """Parse ``url`` and return its lowercased hostname, or None.

    Returns None when the URL is unparseable, has no host, uses an
    unexpected scheme, or embeds credentials via ``user@host`` (the
    latter is a common trick to smuggle a disallowed host past a
    naive substring check).
    """
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except (ValueError, TypeError):
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.hostname:
        return None
    netloc = parsed.netloc or ""
    # ``user@host`` embeds credentials — reject outright rather than
    # try to normalize; a real caller would not use this form.
    if "@" in netloc:
        return None
    return parsed.hostname.lower()


def _url_of(url_or_req: Union[str, urllib.request.Request]) -> str:
    """Return the URL string from a str or a Request object."""
    if isinstance(url_or_req, urllib.request.Request):
        return url_or_req.full_url
    return url_or_req


def _caller_frame_info(skip: int) -> str:
    """Best-effort ``filename:function`` string for the caller.

    Walks ``sys._getframe`` ``skip`` frames up from _this_ function.
    Falls back to ``"<unknown>"`` on any error so audit logging is
    never the cause of a failure.
    """
    try:
        frame = sys._getframe(skip)  # noqa: SLF001 — audit call chain
    except ValueError:
        return "<unknown>"
    try:
        fn = Path(frame.f_code.co_filename).name
        name = frame.f_code.co_name
        return f"{fn}:{name}"
    except Exception:  # noqa: BLE001 — never let audit block
        return "<unknown>"


def _write_audit(caller: str, url: str, host: Optional[str],
                 status: Any, nbytes: int, sha256_hex: str) -> None:
    """Append one JSONL line to the audit log.

    Log-write failures are printed to stderr and swallowed — the fetch
    result MUST NOT depend on the audit file being writable (else a
    read-only home dir would break the whole app).
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "caller": caller,
        "url": url,
        "host": host or "",
        "status": status,
        "bytes": int(nbytes),
        "sha256": sha256_hex,
    }
    path = _audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        # Best-effort — a broken audit log must not break the fetch.
        print(f"[safe_fetch] audit-log write failed: {exc}", file=sys.stderr)


def _check_allowlist(url: str, caller: str) -> str:
    """Validate ``url`` against ALLOWED_HOSTS. Return the host on success.

    Writes a REFUSED_ALLOWLIST audit line and raises SafeFetchError on
    failure.
    """
    host = _extract_host(url)
    if host is None or host not in ALLOWED_HOSTS:
        _write_audit(caller, url, host, _STATUS_REFUSED_ALLOWLIST, 0, "")
        raise SafeFetchError(
            f"safe_fetch: host not in allowlist: {url!r} "
            f"(parsed host={host!r}); extend "
            f"spellcaster_core.safe_fetch.ALLOWED_HOSTS to permit."
        )
    return host


def _check_content_length(resp: Any, max_bytes: int, caller: str,
                          url: str, host: str) -> None:
    """If the response advertises ``Content-Length > max_bytes``, refuse."""
    try:
        cl_raw = resp.headers.get("Content-Length")
    except AttributeError:
        cl_raw = None
    if cl_raw is None:
        return
    try:
        cl = int(cl_raw)
    except (TypeError, ValueError):
        return
    if cl > max_bytes:
        try:
            resp.close()
        except Exception:  # noqa: BLE001 — closing best-effort
            pass
        _write_audit(caller, url, host, _STATUS_REFUSED_SIZE_CAP, 0, "")
        raise SafeFetchError(
            f"safe_fetch: Content-Length {cl} exceeds max_bytes "
            f"{max_bytes} for {url!r}"
        )


def _resp_status(resp: Any) -> int:
    """Extract the HTTP status code from a urllib response."""
    for attr in ("status", "code"):
        val = getattr(resp, attr, None)
        if isinstance(val, int):
            return val
    return 0


# ---------------------------------------------------------------------------
# Streaming wrapper (used by safe_urlopen and internally by safe_get)
# ---------------------------------------------------------------------------

class _AuditedResponse:
    """Wraps a ``urlopen`` response so ``.read()`` counts bytes and
    updates a running SHA-256; logs one audit line on close.

    Enforces ``max_bytes`` on every ``.read()`` call — cumulative
    bytes past the cap raise SafeFetchError and log a REFUSED_SIZE_CAP.
    """

    __slots__ = ("_resp", "_caller", "_url", "_host", "_max_bytes",
                 "_hasher", "_bytes", "_logged", "_error_status")

    def __init__(self, resp: Any, caller: str, url: str, host: str,
                 max_bytes: int) -> None:
        self._resp = resp
        self._caller = caller
        self._url = url
        self._host = host
        self._max_bytes = max_bytes
        self._hasher = hashlib.sha256()
        self._bytes = 0
        self._logged = False
        self._error_status: Optional[str] = None

    def read(self, amt: Optional[int] = None) -> bytes:
        # Cap the individual read so a huge ``amt`` can't blow past
        # ``max_bytes`` in one shot even if the caller asked for it.
        remaining = self._max_bytes + 1 - self._bytes
        if remaining <= 0:
            data = b""
        else:
            if amt is None or amt < 0:
                effective = remaining
            else:
                effective = min(amt, remaining)
            data = self._resp.read(effective)
        self._bytes += len(data)
        self._hasher.update(data)
        if self._bytes > self._max_bytes:
            self._error_status = _STATUS_REFUSED_SIZE_CAP
            try:
                self._resp.close()
            except Exception:  # noqa: BLE001
                pass
            self._log_once(force_status=_STATUS_REFUSED_SIZE_CAP,
                            nbytes=0, sha_hex="")
            raise SafeFetchError(
                f"safe_fetch: streamed body exceeded max_bytes "
                f"{self._max_bytes} for {self._url!r}"
            )
        return data

    def __getattr__(self, name: str) -> Any:
        # Delegate everything else (headers, status, geturl, etc.) to
        # the underlying response object.
        return getattr(self._resp, name)

    def __enter__(self) -> "_AuditedResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        try:
            self._resp.close()
        finally:
            self._log_once()

    def _log_once(self, *, force_status: Optional[Any] = None,
                   nbytes: Optional[int] = None,
                   sha_hex: Optional[str] = None) -> None:
        if self._logged:
            return
        self._logged = True
        status = force_status if force_status is not None else _resp_status(self._resp)
        n = self._bytes if nbytes is None else nbytes
        sha = (self._hasher.hexdigest() if n and sha_hex is None
                else (sha_hex or ""))
        _write_audit(self._caller, self._url, self._host, status, n, sha)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def safe_urlopen(url_or_req: Union[str, urllib.request.Request],
                 timeout: float = 30,
                 max_bytes: int = MAX_BYTES) -> _AuditedResponse:
    """Open a URL through the allowlist + audit gate; return a stream.

    Prefer :func:`safe_get` / :func:`safe_post` — this variant exists
    for callers (auto_updater's ``download_blob`` in particular) that
    need to do bounded streaming ``.read(n)`` themselves.
    """
    caller = _caller_frame_info(2)
    url = _url_of(url_or_req)
    host = _check_allowlist(url, caller)
    try:
        resp = urllib.request.urlopen(url_or_req, timeout=timeout)
    except urllib.error.HTTPError:
        _write_audit(caller, url, host, _STATUS_ERROR, 0, "")
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        _write_audit(caller, url, host, _STATUS_ERROR, 0, "")
        raise
    try:
        _check_content_length(resp, max_bytes, caller, url, host)
    except SafeFetchError:
        raise
    return _AuditedResponse(resp, caller, url, host, max_bytes)


def safe_get(url: str, timeout: float = 30,
             max_bytes: int = MAX_BYTES,
             headers: Optional[Mapping[str, str]] = None) -> bytes:
    """GET ``url`` through the allowlist + audit gate. Returns the body.

    On failure: raises :class:`SafeFetchError` for a policy refusal,
    or the underlying ``urllib.error.URLError`` / ``OSError`` /
    ``TimeoutError`` for a network failure. The audit log always
    records the attempt.
    """
    caller = _caller_frame_info(2)
    _check_allowlist(url, caller)  # raises SafeFetchError on refusal
    req = urllib.request.Request(url, headers=dict(headers or {}))
    # Delegate the actual open (and the streaming size cap) to
    # safe_urlopen; we just consume the body eagerly.
    # ``_caller_frame_info`` inside safe_urlopen would point at THIS
    # function, so re-do the frame walk here and pass audit fields
    # through _AuditedResponse's regular ``.read()`` / ``.close()``.
    host = _extract_host(url) or ""
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        _write_audit(caller, url, host, _STATUS_ERROR, 0, "")
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        _write_audit(caller, url, host, _STATUS_ERROR, 0, "")
        raise
    try:
        _check_content_length(resp, max_bytes, caller, url, host)
    except SafeFetchError:
        raise
    audited = _AuditedResponse(resp, caller, url, host, max_bytes)
    try:
        body = audited.read()  # single big read, capped at max_bytes+1
    finally:
        audited.close()
    return body


def safe_post(url: str,
              data: Union[bytes, str, Mapping[str, Any], None],
              timeout: float = 30,
              max_bytes: int = MAX_BYTES,
              headers: Optional[Mapping[str, str]] = None) -> bytes:
    """POST ``data`` to ``url`` through the allowlist + audit gate.

    ``data`` may be raw bytes, a str (UTF-8 encoded), or a mapping
    (JSON-encoded with a ``Content-Type: application/json`` header
    added when not already present).
    """
    caller = _caller_frame_info(2)
    host = _check_allowlist(url, caller)
    req_headers = dict(headers or {})
    payload: Optional[bytes]
    if data is None:
        payload = None
    elif isinstance(data, bytes):
        payload = data
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    elif isinstance(data, Mapping):
        payload = json.dumps(dict(data)).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    else:
        raise TypeError(
            f"safe_post: unsupported data type {type(data).__name__}"
        )
    req = urllib.request.Request(url, data=payload,
                                  headers=req_headers,
                                  method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        _write_audit(caller, url, host, _STATUS_ERROR, 0, "")
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        _write_audit(caller, url, host, _STATUS_ERROR, 0, "")
        raise
    try:
        _check_content_length(resp, max_bytes, caller, url, host)
    except SafeFetchError:
        raise
    audited = _AuditedResponse(resp, caller, url, host, max_bytes)
    try:
        body = audited.read()
    finally:
        audited.close()
    return body


__all__ = [
    "ALLOWED_HOSTS",
    "MAX_BYTES",
    "SafeFetchError",
    "safe_get",
    "safe_post",
    "safe_urlopen",
]
