"""Per-repo VIBECODER.md change-detector.

Run on a schedule (or via watcher). On invocation:
  1. Compute a hash of `git ls-files` content (pure-Python sha256 walk).
  2. Compare against prior state at `_vibecoder/state.json`.
  3. If anything changed (HEAD or content hash), regenerate the AUTO blocks of
     `VIBECODER.md` in place, preserving human-edited sections.
  4. Print a one-line summary.

Pure stdlib.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "_vibecoder" / "state.json"
VIBECODER = REPO / "VIBECODER.md"


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _ls_files() -> list[str]:
    raw = _git("ls-files")
    return [ln for ln in raw.splitlines() if ln.strip()]


def _content_hash(files: list[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        p = REPO / rel
        try:
            with open(p, "rb") as fh:
                while True:
                    chunk = fh.read(1 << 16)
                    if not chunk:
                        break
                    h.update(rel.encode("utf-8", "replace"))
                    h.update(b"\0")
                    h.update(chunk)
        except (OSError, FileNotFoundError):
            continue
    return h.hexdigest()


def _hot_files(files: list[str], days: int = 90, top_n: int = 12) -> list[str]:
    """Return up to top_n files most-frequently modified in the last `days`."""
    raw = _git("log", f"--since={days}.days.ago", "--name-only", "--pretty=format:")
    counts: dict[str, int] = {}
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # filter out tests / docs / configs / vibecoder itself
        low = ln.lower()
        if any(seg in low for seg in ("/tests/", "/test/", "tests/", "/__pycache__/", "/_vibecoder/")):
            continue
        if low.endswith((".md", ".txt", ".lock", ".cfg", ".ini", ".toml", ".yaml", ".yml", "vibecoder.md")):
            continue
        counts[ln] = counts.get(ln, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f for f, _ in ranked[:top_n]]


def _loc(files: list[str]) -> int:
    return len(files)


def _detect_test_cmd() -> str:
    if (REPO / "pytest.ini").exists() or (REPO / "pyproject.toml").exists() or (REPO / "tests").exists():
        return "pytest"
    if (REPO / "package.json").exists():
        return "npm test"
    if (REPO / "Cargo.toml").exists():
        return "cargo test"
    return "none-found"


def _commit_info() -> tuple[str, str]:
    sha = _git("rev-parse", "--short", "HEAD")
    subj = _git("log", "-1", "--pretty=%s")
    return sha, subj


def _replace_block(text: str, marker: str, new_inner: str) -> str:
    pat = re.compile(
        r"<!-- AUTO:" + re.escape(marker) + r" -->.*?<!-- /AUTO:" + re.escape(marker) + r" -->",
        re.DOTALL,
    )
    repl = f"<!-- AUTO:{marker} -->\n{new_inner}\n<!-- /AUTO:{marker} -->"
    if pat.search(text):
        return pat.sub(lambda m: repl, text)
    return text + "\n\n" + repl + "\n"


def main() -> int:
    if not VIBECODER.exists():
        print(f"[vibecoder] VIBECODER.md missing at {VIBECODER}; nothing to update.")
        return 1

    files = _ls_files()
    head = _git("rev-parse", "HEAD")
    chash = _content_hash(files)

    prior = {}
    if STATE.exists():
        try:
            prior = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            prior = {}

    if prior.get("head") == head and prior.get("content_hash") == chash:
        print(f"[vibecoder] no change (HEAD={head[:7]}).")
        return 0

    sha, subj = _commit_info()
    loc = _loc(files)
    test_cmd = _detect_test_cmd()
    hot = _hot_files(files)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Preserve human/scaffold-set language from existing glance block, if any.
    prior_text = VIBECODER.read_text(encoding="utf-8")
    lang_match = re.search(r"\*\*Primary language:\*\* `([^`]+)`", prior_text)
    lang = lang_match.group(1) if lang_match else "auto"

    glance = (
        f"- **Local path:** `{REPO}`\n"
        f"- **Primary language:** `{lang}`\n"
        f"- **Last analyzed:** `{ts}`\n"
        f"- **Last commit:** `{sha} - {subj}`\n"
        f"- **Lines of code (rough):** `{loc}`\n"
        f"- **Test command:** `{test_cmd}`"
    )
    if hot:
        modules = "\n".join(f"- `{f}`" for f in hot)
    else:
        modules = "_no recent activity in the last 90 days_"

    text = VIBECODER.read_text(encoding="utf-8")
    text = _replace_block(text, "glance", glance)
    text = _replace_block(text, "modules", modules)
    VIBECODER.write_text(text, encoding="utf-8")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(
            {"head": head, "content_hash": chash, "ts": ts}, indent=2, sort_keys=True
        ),
        encoding="utf-8",
    )

    print(f"[vibecoder] regenerated VIBECODER.md (HEAD={head[:7]}, files={loc}, hot={len(hot)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
