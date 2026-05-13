#!/usr/bin/env python3
"""Local-LLM delegation gateway.

Per Laborantin-aware practice: tasks that don't require Claude-level
reasoning should be delegated to Theo's local LLMs (LM Studio on
:1234). Frees Claude's context for the work only Claude can do.

What counts as "safe to delegate":

  - Docstring + comment polish on functions whose code is unchanged
  - Test-fixture generation (parametrize inputs, no logic decisions)
  - Boilerplate refactor *proposals* (caller reviews the diff)
  - Log/report summarization
  - Code-style cleanup (formatting, naming consistency)
  - README / changelog drafts

What MUST NOT be delegated:

  - Architecture changes (interface choices, dependency direction)
  - 6-surface mirror sync (must be byte-identical — human-verified)
  - Security-sensitive code (auth, credential handling, crypto)
  - ComfyUI workflow logic (one wrong node name = silent failure
    per _DEV_HYGIENE.md H4)
  - Anything that modifies a client (.claude/, VSCode settings,
    Antigravity — per user policy)

Default endpoint: ``http://192.168.86.28:1234/v1/chat/completions``
(LM Studio on Theo). Override with --endpoint.

Usage:
    # Polish docstrings on a single file
    python tools/llm_delegate.py polish-docs --file path/to/x.py

    # Summarize a log file
    python tools/llm_delegate.py summarize-log --file launcher.log

    # Free-form prompt (echo to stdout, no file writes)
    python tools/llm_delegate.py ask "<prompt>"

Every mode writes the LLM response to stdout. File-mutation modes
(``polish-docs``) emit a UNIFIED DIFF — apply with ``patch -p0``
after human review. Never auto-apply.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_ENDPOINT = "http://192.168.86.28:1234/v1/chat/completions"
DEFAULT_MODEL = "qwen2.5-coder-7b-instruct"   # fast + code-aware
LARGE_MODEL   = "qwen3-30b-a3b"                # use for nuanced summarization

# Maximum file size we'll send to the LLM (bytes). Larger files get
# refused with a helpful message — chunk them or use Claude.
MAX_FILE_BYTES = 200_000


def _post_chat(endpoint: str, model: str,
               system: str, user: str,
               max_tokens: int = 4096,
               temperature: float = 0.2) -> str:
    """POST to /v1/chat/completions and return the assistant text."""
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "spellcaster-llm-delegate",
                 "Connection": "close"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        payload = json.loads(r.read().decode("utf-8"))
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM returned no choices: {payload}")
    return choices[0]["message"]["content"]


# ─── Modes ────────────────────────────────────────────────────────────────────

def mode_polish_docs(args) -> int:
    p = Path(args.file)
    if not p.is_file():
        print(f"file not found: {p}", file=sys.stderr)
        return 1
    if p.stat().st_size > MAX_FILE_BYTES:
        print(f"file too large ({p.stat().st_size} > {MAX_FILE_BYTES} bytes); "
              f"split before delegating", file=sys.stderr)
        return 1
    src = p.read_text(encoding="utf-8")

    system = (
        "You are a careful Python documentation editor. Improve docstrings "
        "and comments WITHOUT changing any code. Preserve all imports, "
        "function signatures, and logic. Output a unified diff (diff -u "
        "style) that a human will review before applying. If no edits are "
        "warranted, output exactly: NO CHANGES NEEDED."
    )
    user = (
        f"File: {p.name}\n\n```python\n{src}\n```\n\n"
        "Constraints:\n"
        "- Don't expand short, clear identifiers into long phrases.\n"
        "- Don't add module-level docstrings to files that don't have one.\n"
        "- Don't rewrite working comments just to change wording.\n"
        "- Add docstrings only where they explain WHY (intent), not WHAT.\n"
    )
    out = _post_chat(args.endpoint, args.model, system, user,
                     max_tokens=8192)
    print(out)
    return 0


def mode_summarize_log(args) -> int:
    p = Path(args.file)
    if not p.is_file():
        print(f"file not found: {p}", file=sys.stderr)
        return 1
    text = p.read_text(encoding="utf-8", errors="replace")
    # Send the last 4k lines so we summarize recent state, not the
    # full history.
    tail = "\n".join(text.splitlines()[-4000:])
    if len(tail) > MAX_FILE_BYTES:
        tail = tail[-MAX_FILE_BYTES:]
    system = (
        "You are a log triage assistant. Given the tail of a server log, "
        "produce a short structured summary: (1) what's healthy, (2) "
        "what's broken, (3) what's worth investigating. Prefer specific "
        "timestamps and error counts over prose."
    )
    user = f"File: {p.name}\n\n```\n{tail}\n```"
    out = _post_chat(args.endpoint, args.model, system, user,
                     max_tokens=2048)
    print(out)
    return 0


def mode_ask(args) -> int:
    if not args.prompt:
        print("ask: empty prompt", file=sys.stderr)
        return 1
    system = (
        "You are a careful coding assistant. Answer concisely. If the "
        "request would require modifying source code, output the diff "
        "(diff -u format) for the caller to review — DO NOT pretend to "
        "have applied changes."
    )
    out = _post_chat(args.endpoint, args.model, system, args.prompt,
                     max_tokens=args.max_tokens or 2048,
                     temperature=args.temperature or 0.3)
    print(out)
    return 0


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                    help="OpenAI-style /v1/chat/completions URL "
                         "(default: LM Studio on Theo)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Model id (default: {DEFAULT_MODEL})")
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--temperature", type=float, default=None)

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("polish-docs",
                       help="Suggest docstring/comment edits for a file")
    p.add_argument("--file", required=True)
    p.set_defaults(func=mode_polish_docs)

    p = sub.add_parser("summarize-log",
                       help="Triage-summarize a server log tail")
    p.add_argument("--file", required=True)
    p.set_defaults(func=mode_summarize_log)

    p = sub.add_parser("ask",
                       help="Free-form prompt → stdout")
    p.add_argument("prompt", nargs="?", default="")
    p.set_defaults(func=mode_ask)

    args = ap.parse_args()
    try:
        return args.func(args)
    except urllib.error.URLError as e:
        print(f"LLM endpoint unreachable: {args.endpoint} — {e}",
              file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — bubble up cleanly for shell use
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
