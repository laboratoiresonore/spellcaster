"""Shared auto-updater primitives for Spellcaster.

Both the GIMP plugin ([_spellcaster_main.py]) and the Wizard Guild
([guild_launcher.py]) do the same thing on startup: hit GitHub's commits
API, compare SHAs, walk the tree, download files, and replace local copies.

Historically these were two ~260-line hand-rolled implementations with
subtle differences (staging semantics, protected-file sets, canonical-
source dedup). This module extracts the genuinely-shared primitives so
both callers become thin wrappers.

What's shared
-------------
- SHA compare (supports 7-char and 40-char)
- GitHub /commits fetch
- GitHub /git/trees/main?recursive=1 walk
- Single-file download with integrity check + null-byte scrub
- __pycache__ purge

What stays caller-specific
--------------------------
- Tree filter (which paths belong to this app)
- Staging policy (.update vs live replace)
- Protected file set
- Post-update work (GIMP pluginrc purge, theme reapply, Guild restart)

This split lets each caller keep its idiosyncratic behavior without
forcing a lowest-common-denominator design.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
import urllib.error
import urllib.request

# Text file extensions that get null-byte scrubbing (guards against
# Windows NTFS corruption where nulls can appear mid-file).
_TEXT_EXTS = (".py", ".js", ".jsx", ".css", ".json", ".md", ".txt", ".html")

# Hard upper bound on any single file pulled from the update source.
# 50 MB is far above any legitimate plugin file (largest shipped asset
# is ~300 KB) and well below what would cripple a system on download.
DEFAULT_MAX_BLOB_SIZE = 50 * 1024 * 1024


# Relative-path component characters that are always safe (portable,
# non-traversing, no drive markers). Everything else is rejected.
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._\- /]+$")


def safe_remainder(remainder: str) -> Optional[str]:
    """Normalize and validate a repo-relative path before using it on disk.

    Returns the normalized path (forward-slash, no leading slash) or None
    if the path would escape the target root, refer to a drive, contain
    control characters, or use NTFS-special names. Callers MUST skip
    anything that returns None — never coerce the original string.

    Defends against:
      - Directory traversal (`../` components, absolute paths).
      - Windows drive markers (`C:`, `\\\\server`).
      - Backslashes (git tree uses `/` — a backslash here is suspicious).
      - NUL bytes and other control chars.
      - Reserved Windows filenames (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
    """
    if not isinstance(remainder, str) or not remainder:
        return None
    # Reject NUL + other control chars outright.
    if any(ord(c) < 0x20 for c in remainder):
        return None
    # Reject backslashes — the GitHub Tree API uses forward slashes.
    if "\\" in remainder:
        return None
    # Reject drive markers like "C:", "c:foo", and UNC prefixes.
    if re.match(r"^[A-Za-z]:", remainder):
        return None
    if remainder.startswith("//") or remainder.startswith("/"):
        return None
    # Reject any `..` traversal component.
    parts = remainder.split("/")
    for p in parts:
        if p in ("", ".", ".."):
            return None
        # Windows-reserved basenames (case-insensitive, with or without ext).
        stem = p.split(".", 1)[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL"} or re.match(r"^(COM|LPT)[1-9]$", stem):
            return None
    # Final gate: charset allowlist after structural checks.
    if not _SAFE_PATH_RE.match(remainder):
        return None
    return "/".join(parts)


def git_blob_sha1(blob: bytes) -> str:
    """Compute git's blob SHA-1 for the given bytes.

    git stores each blob as ``sha1("blob <len>\\0<content>")`` — that SHA
    is what the Tree API returns as the per-entry ``sha`` field. Use this
    to verify a raw.githubusercontent download without a second API call.
    """
    h = hashlib.sha1()
    h.update(b"blob " + str(len(blob)).encode("ascii") + b"\x00")
    h.update(blob)
    return h.hexdigest()


def acquire_lock(path: Path, *, stale_after: float = 600.0) -> bool:
    """Atomic lock-file acquisition. Returns True if we hold the lock.

    - Uses O_CREAT|O_EXCL so exactly one caller wins.
    - Staleness guard: if the existing lock's mtime is older than
      ``stale_after`` seconds, overwrite (assumes the previous holder
      crashed).
    - Writes the current PID so post-mortem debugging knows who held it.
    """
    try:
        if path.exists():
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                age = 0
            if age < stale_after:
                return False
            # Stale — drop it and retry.
            try:
                path.unlink()
            except OSError:
                return False
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def release_lock(path: Path) -> None:
    """Best-effort lock release. Safe to call whether or not we hold it."""
    try:
        path.unlink()
    except OSError:
        pass


def shas_match(a: str, b: str) -> bool:
    """Compare commit SHAs. Accepts either 7-char truncated or 40-char full.
    Returns True if they point to the same commit.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    return a[:7] == b[:7]


def fetch_latest_sha(commits_url: str, headers: dict[str, str],
                     timeout: float = 15) -> str:
    """GET <commits_url> → latest commit's SHA. Raises on HTTP error."""
    req = urllib.request.Request(commits_url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data:
        raise ValueError("empty /commits response")
    return data[0]["sha"]


def fetch_tree(tree_url: str, headers: dict[str, str],
               timeout: float = 30) -> list[dict[str, Any]]:
    """GET <tree_url> (recursive) → list of tree items (blobs and trees).

    Each blob has keys: path, type, sha, size, url. Use type=="blob" to
    filter for files; trees (directories) are returned too.
    """
    req = urllib.request.Request(tree_url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("tree", [])


def download_blob(url: str, expected_size: int, headers: dict[str, str],
                  *, timeout: float = 60, scrub_nulls: bool = True,
                  filename_hint: str = "",
                  max_size: int = DEFAULT_MAX_BLOB_SIZE,
                  expected_sha: Optional[str] = None) -> bytes:
    """Download a single blob and return its bytes.

    - Verifies content length when expected_size > 0 (rejects truncated).
    - Caps at ``max_size`` bytes so a hostile server can't OOM the plugin.
      The read is bounded — we never accumulate more than max_size+1 bytes.
    - If ``expected_sha`` is given (git blob SHA-1 from the Tree API),
      the downloaded bytes are verified AFTER null-scrub is decided but
      BEFORE the scrub is applied. git computes the SHA on the raw bytes,
      so verification must happen on the untouched blob.
    - Scrubs null bytes from text files to guard against NTFS corruption.
      Pass scrub_nulls=False for strictly binary content. filename_hint
      is used to auto-detect text via extension.
    - Does NOT write to disk — caller controls placement (atomic rename,
      staging, etc.).

    Raises IOError on size mismatch, oversize, or SHA mismatch.
    """
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # Bounded read — read() without arg is unbounded; we want a
        # hard ceiling in case the server streams forever.
        blob = resp.read(max_size + 1)
    if len(blob) > max_size:
        raise IOError(f"blob exceeds max_size {max_size} bytes")
    if expected_size > 0 and len(blob) != expected_size:
        raise IOError(
            f"Incomplete download: got {len(blob)} bytes, "
            f"expected {expected_size}")
    # Integrity check BEFORE scrubbing — the Tree API's SHA is computed
    # on the raw blob bytes, nulls and all.
    if expected_sha:
        actual = git_blob_sha1(blob)
        # Accept either 7-char truncated or 40-char full SHA.
        if not shas_match(actual, expected_sha):
            raise IOError(
                f"SHA mismatch: got {actual[:12]}, expected {expected_sha[:12]}")
    if scrub_nulls and filename_hint.lower().endswith(_TEXT_EXTS):
        blob = blob.replace(b"\x00", b"")
    return blob


def atomic_write_or_stage(dest: Path, blob: bytes,
                          *, stage_suffix: str = ".update",
                          always_stage: bool = False) -> tuple[bool, bool]:
    """Write bytes to dest. Returns (replaced, staged).

    - Writes to a .tmp file first, then os.replace() to dest (atomic
      within the same filesystem).
    - If always_stage=True, writes to dest.update directly without
      attempting the live replace. Use for running .py modules where
      live replacement is unsafe (the process already imported it).
    - If live replace fails (Windows file-lock/PermissionError), falls
      back to staging with stage_suffix.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(blob)
    if always_stage:
        stage_path = dest.with_suffix(dest.suffix + stage_suffix)
        tmp.replace(stage_path)
        return (False, True)
    try:
        tmp.replace(dest)
        return (True, False)
    except PermissionError:
        stage_path = dest.with_suffix(dest.suffix + stage_suffix)
        tmp.replace(stage_path)
        return (False, True)


def purge_pycache(roots: Iterable[Path]) -> int:
    """Remove every __pycache__ dir under each root. Returns the count."""
    removed = 0
    for root in roots:
        if not root.is_dir():
            continue
        for pycache in root.rglob("__pycache__"):
            try:
                shutil.rmtree(pycache)
                removed += 1
            except Exception:
                pass
    return removed


def prune_stale_files(write_base: Path,
                      local_prefixes: Iterable[str],
                      remote_paths: set[str],
                      protected: set[str],
                      protected_suffixes: tuple[str, ...] = (".pyc", ".update",
                                                              ".tmp", ".onnx",
                                                              ".safetensors")) -> int:
    """Remove files under any local_prefix that aren't in remote_paths.

    - write_base: repo root on disk (e.g. spellcaster/ or PLUGIN_DIR)
    - local_prefixes: relative dirs to scan ("tavern", "scaffold", etc.)
    - remote_paths: set of file paths (relative to write_base) expected
      from the remote tree. Anything NOT in this set gets deleted.
    - protected: literal paths or filenames to preserve regardless
    - protected_suffixes: never delete files with these endings (bytecode,
      staged .update, temp, runtime model weights)
    Returns number of files removed.
    """
    removed = 0
    for prefix in local_prefixes:
        prefix_dir = write_base / prefix
        if not prefix_dir.is_dir():
            continue
        for local_file in prefix_dir.rglob("*"):
            if not local_file.is_file():
                continue
            rel = local_file.relative_to(write_base).as_posix()
            if rel in protected or local_file.name in protected:
                continue
            if local_file.suffix in protected_suffixes:
                continue
            if rel not in remote_paths:
                try:
                    local_file.unlink()
                    removed += 1
                except Exception:
                    pass
    return removed
