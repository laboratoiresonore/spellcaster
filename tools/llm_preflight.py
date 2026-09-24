#!/usr/bin/env python3
"""LLM preflight — refuse an LLM job before it fires if the loaded
model's context window is too small for what the caller needs.

The 2026-09-24 monster incident (issue #181): qwen3-8b got loaded at
a 4,096-token context for a Hermes Agent job that needed at least
64,000. The LM Studio server was reporting the small 4K window as
authoritative and no layer in the stack had ground-truth data to
override it. This module is that ground-truth layer.

Public API
----------

    assert_context(model, required_ctx, host=None) -> None
        Refuse (raise :class:`InsufficientContextError`) if the loaded
        model's *effective* context window is below ``required_ctx``.

    get_declared_context(model, host=None) -> int
        Return the effective context — the LARGER of the value the
        server reports on ``GET /v1/models`` and the value in the
        ground-truth manifest ``installer/model_capabilities.json``.
        Never trusts the server alone: LM Studio has been observed to
        under-advertise (4K when the true window is 131K).

    load_manifest(path=None) -> dict
        Load ``installer/model_capabilities.json``. Raises
        :class:`FileNotFoundError` with a hint pointing at the fix if
        the file is missing.

CLI
---

    python tools/llm_preflight.py --model qwen3-8b --required-ctx 64000
    python tools/llm_preflight.py --model qwen3-8b --required-ctx 64000 \\
                                  --host http://127.0.0.1:1234

Exit 0 on success. Exit 1 with a formatted diagnostic naming the
declared and required contexts on failure. This is the tool the
operator can run to verify a monster-side fix.

Fallback behavior
-----------------

* Manifest missing: print a warning to stderr and trust the server
  alone (best we can do — we still get a preflight, just without a
  ground-truth override).
* Server unreachable: fall back to the manifest value if the model
  is known; otherwise raise with a clear "cannot determine context"
  message.
* Model absent from both: raise with a clear "unknown model" message.

Uses :func:`spellcaster_core.safe_fetch.safe_get` for the HTTP call
to ``/v1/models`` (allowlist + audit + size cap; issue #14 / PR #180).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path
from typing import Optional

# spellcaster_core lives under plugins/gimp/comfyui-connector/ — hook
# it onto sys.path so this tool (which sits in tools/, outside the
# package tree) can call the safe_fetch wrapper.
_REPO = Path(__file__).resolve().parent.parent
_CORE_PARENT = _REPO / "plugins" / "gimp" / "comfyui-connector"
if _CORE_PARENT.is_dir() and str(_CORE_PARENT) not in sys.path:
    sys.path.insert(0, str(_CORE_PARENT))
from spellcaster_core.safe_fetch import safe_get, SafeFetchError  # noqa: E402

# Force UTF-8 on Windows so the diagnostic message renders cleanly.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_MANIFEST = _REPO / "installer" / "model_capabilities.json"


class InsufficientContextError(RuntimeError):
    """Raised when the loaded model's context is below the caller's
    ``required_ctx``. The message names both values so a shell error
    is legible without opening a debugger."""


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest(path: Optional[Path] = None) -> dict:
    """Load ``installer/model_capabilities.json``.

    Returns the parsed dict. Raises :class:`FileNotFoundError` with a
    hint pointing at the source of truth if the file is missing —
    callers can catch this and fall back to server-reported values.
    """
    p = Path(path) if path is not None else DEFAULT_MANIFEST
    if not p.is_file():
        raise FileNotFoundError(
            f"model capabilities manifest not found at {p}. "
            f"Add an entry there for every local model — see the "
            f"file's _schema block for the format. This is the "
            f"ground-truth override for the server-reported context.")
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data


def _manifest_context_for(manifest: dict, model: str) -> Optional[int]:
    """Return the manifest-declared context_length for ``model``, or
    ``None`` if the model is not listed. Matches case-insensitively."""
    models = (manifest or {}).get("models") or {}
    if not isinstance(models, dict):
        return None
    key = model.lower()
    for name, entry in models.items():
        if not isinstance(entry, dict):
            continue
        if name.lower() == key:
            val = entry.get("context_length")
            if isinstance(val, int) and val > 0:
                return val
    return None


# ---------------------------------------------------------------------------
# Server-reported context via GET /v1/models
# ---------------------------------------------------------------------------

def _resolve_host(host: Optional[str]) -> str:
    """Resolve the OpenAI-compatible base URL for the LLM host.

    Precedence: explicit ``host`` arg → ``LM_STUDIO_HOST`` env →
    ``COMFYUI_HOST`` env (a bare hostname is upgraded to a full URL
    with the default LM Studio port :1234) → ``http://127.0.0.1:1234``.
    """
    if host:
        return host.rstrip("/")
    env = os.environ.get("LM_STUDIO_HOST")
    if env:
        return env.rstrip("/")
    comfy = os.environ.get("COMFYUI_HOST")
    if comfy:
        # COMFYUI_HOST is a bare hostname (matches how the other LLM
        # tools use it). Assume the LM Studio port :1234 unless the
        # caller already stitched a full URL together.
        if comfy.startswith(("http://", "https://")):
            return comfy.rstrip("/")
        return f"http://{comfy}:1234"
    return "http://127.0.0.1:1234"


def _fetch_server_context(host: str, model: str) -> Optional[int]:
    """Query ``GET <host>/v1/models`` and return the reported
    ``context_length`` for ``model``. Returns ``None`` when the server
    cannot be reached, is refused by the allowlist, does not list the
    model, or does not advertise a context length.
    """
    url = f"{host.rstrip('/')}/v1/models"
    try:
        raw = safe_get(
            url,
            timeout=10,
            headers={"Connection": "close",
                     "User-Agent": "spellcaster-llm-preflight"},
        )
    except (SafeFetchError, urllib.error.URLError, TimeoutError,
            OSError):
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    # OpenAI-compatible schema: {"data": [{"id": "...", ...}, ...]}
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return None
    key = model.lower()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id", "")).lower()
        if model_id != key:
            continue
        # LM Studio, Ollama, and llama.cpp each spell this differently.
        # Check all the common keys.
        for field in ("context_length", "max_context_length",
                      "n_ctx", "loaded_context_length",
                      "context_window"):
            val = entry.get(field)
            if isinstance(val, int) and val > 0:
                return val
        # Some servers nest it under a "metadata" or "config" block.
        for nest_key in ("metadata", "config"):
            nested = entry.get(nest_key)
            if isinstance(nested, dict):
                for field in ("context_length", "max_context_length",
                              "n_ctx"):
                    val = nested.get(field)
                    if isinstance(val, int) and val > 0:
                        return val
        return None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_declared_context(model: str,
                          host: Optional[str] = None,
                          manifest_path: Optional[Path] = None) -> int:
    """Return the effective context window for ``model``.

    Cross-references the server-reported value with the ground-truth
    manifest and returns the LARGER of the two. Server-under-reporting
    is the failure mode this whole module exists to defend against —
    trusting the server alone is what got us into issue #181.

    Raises :class:`InsufficientContextError` (used as a generic
    "cannot determine" signal) when neither source has a value for
    ``model``.
    """
    server_value: Optional[int] = None
    manifest_value: Optional[int] = None

    resolved_host = _resolve_host(host)
    server_value = _fetch_server_context(resolved_host, model)

    try:
        manifest = load_manifest(manifest_path)
    except FileNotFoundError as e:
        # No manifest — fall back to server value only, but shout
        # about it: the whole point of the fix is that the manifest
        # exists.
        print(f"[llm_preflight] WARNING: {e} Falling back to "
              f"server-reported value only.", file=sys.stderr)
        manifest = {}
    manifest_value = _manifest_context_for(manifest, model)

    if server_value is None and manifest_value is None:
        raise InsufficientContextError(
            f"unknown model {model!r}: not listed on "
            f"{resolved_host}/v1/models AND not in the manifest at "
            f"{manifest_path or DEFAULT_MANIFEST}. Either load the "
            f"model on the LM Studio host, or add it to "
            f"installer/model_capabilities.json (see the file's "
            f"_schema block).")
    return max(server_value or 0, manifest_value or 0)


def assert_context(model: str,
                    required_ctx: int,
                    host: Optional[str] = None,
                    manifest_path: Optional[Path] = None) -> None:
    """Refuse before firing a prompt if the loaded model's context is
    insufficient for the caller.

    Raises :class:`InsufficientContextError` with a message naming
    both ``required_ctx`` and the effective ``declared_ctx`` if the
    check fails. On success, returns ``None``.
    """
    declared = get_declared_context(model, host=host,
                                     manifest_path=manifest_path)
    if declared < required_ctx:
        resolved_host = _resolve_host(host)
        raise InsufficientContextError(
            f"model {model!r} on {resolved_host}: declared context "
            f"{declared} tokens is below required {required_ctx}. "
            f"Choose a model with at least {required_ctx} tokens, or "
            f"reload {model!r} at a larger --context-length (see "
            f"installer/model_capabilities.json for the true ceiling).")


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Preflight-check a local LLM's context window "
                    "against a job's requirement.")
    ap.add_argument("--model", required=True,
                    help="Model id as the server reports it (e.g. "
                         "qwen3-8b).")
    ap.add_argument("--required-ctx", type=int, required=True,
                    help="Minimum context length the caller needs "
                         "(tokens).")
    ap.add_argument("--host", default=None,
                    help="OpenAI-compatible base URL (e.g. "
                         "http://spark1:1234). Defaults to "
                         "$LM_STUDIO_HOST → $COMFYUI_HOST → "
                         "http://127.0.0.1:1234.")
    ap.add_argument("--manifest", default=None,
                    help="Override the manifest path "
                         "(default: installer/model_capabilities.json).")
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest) if args.manifest else None
    try:
        assert_context(args.model, args.required_ctx,
                        host=args.host, manifest_path=manifest_path)
    except InsufficientContextError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    declared = get_declared_context(args.model, host=args.host,
                                     manifest_path=manifest_path)
    print(f"OK: {args.model} declared_ctx={declared} tokens "
          f">= required {args.required_ctx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
