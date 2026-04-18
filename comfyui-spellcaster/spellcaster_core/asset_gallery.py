"""Asset Gallery — hash-indexed, interface-aware shared asset store.

Every frontend can write generated/imported assets here, and every
frontend can list+fetch assets from every other. Assets are hashed by
content (SHA-256 of the raw bytes) so the same image generated twice
only stores once — deduplication for free.

Storage layout (under the Guild's existing _CREATIONS_DIR):

    creations/
      gallery/
        index.json          # one JSON blob with all metadata
        blobs/
          ab/abcd1234…5678.png
          cd/cd9876543…1234.mp4
          …

Index schema:

    {
      "version": 1,
      "assets": [
        {
          "hash": "abcd1234…5678",
          "ext": "png",
          "mime": "image/png",
          "size": 524288,
          "origin": "gimp",              # which interface wrote it
          "kind": "generation",          # generation | import | export | ref
          "title": "mountain landscape",
          "prompt": "alpine peaks at sunset",
          "model": "juggernautXL_v9",
          "seed": 42,
          "ts": 1713654321.12,
          "tags": ["landscape", "sunset"],
          "meta": { ... free-form ... }
        }
      ]
    }

The index is rewritten atomically on every mutation so crashes can
leave at most one partially-written temp file.

Interface-awareness: `list_assets(active_only=True)` filters results to
only show assets from interfaces that the InterfaceRegistry currently
reports as active. That way a user whose Resolve plugin is uninstalled
never sees "from Resolve" assets cluttering their gallery.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional


_GALLERY_VERSION = 1
_BLOB_DIR = "blobs"
_INDEX_FILENAME = "index.json"


# Known file extensions → MIME (we avoid relying on mimetypes.types_map
# which is platform-dependent)
_MIME_EXTS = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "json": "application/json",
}


@dataclass
class AssetRecord:
    hash: str
    ext: str
    mime: str
    size: int
    origin: str = "unknown"
    kind: str = "generation"
    title: str = ""
    prompt: str = ""
    model: str = ""
    seed: Optional[int] = None
    ts: float = 0.0
    tags: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AssetRecord":
        return cls(
            hash=d.get("hash", ""),
            ext=d.get("ext", "bin"),
            mime=d.get("mime", "application/octet-stream"),
            size=int(d.get("size", 0)),
            origin=d.get("origin", "unknown"),
            kind=d.get("kind", "generation"),
            title=d.get("title", ""),
            prompt=d.get("prompt", ""),
            model=d.get("model", ""),
            seed=d.get("seed"),
            ts=float(d.get("ts", 0.0)),
            tags=list(d.get("tags", [])),
            meta=dict(d.get("meta", {})),
        )


class AssetGallery:
    """Hash-indexed asset store with an on-disk JSON index."""

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.blob_dir = os.path.join(self.root, _BLOB_DIR)
        self.index_path = os.path.join(self.root, _INDEX_FILENAME)
        os.makedirs(self.blob_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._index: dict[str, AssetRecord] = {}
        self._load_index()

    # ── Index persistence ───────────────────────────────────────────

    def _load_index(self):
        if not os.path.isfile(self.index_path):
            return
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assets = data.get("assets", [])
            self._index = {
                a["hash"]: AssetRecord.from_dict(a)
                for a in assets if a.get("hash")
            }
        except Exception:
            # Corrupt index — start fresh. The blobs on disk will be
            # re-indexed by `scan_blobs()` if the caller triggers it.
            self._index = {}

    def _save_index_locked(self):
        """Atomic write of the index. Call with self._lock held."""
        data = {
            "version": _GALLERY_VERSION,
            "updated_at": time.time(),
            "assets": [r.to_dict() for r in self._index.values()],
        }
        tmp = self.index_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.index_path)
        except Exception:
            # Leave the old index in place on error
            try:
                os.unlink(tmp)
            except Exception:
                pass

    # ── Write ────────────────────────────────────────────────────────

    def put(self, data: bytes, *, origin: str = "unknown",
            kind: str = "generation", ext: Optional[str] = None,
            title: str = "", prompt: str = "", model: str = "",
            seed: Optional[int] = None,
            tags: Optional[list[str]] = None,
            meta: Optional[dict] = None) -> AssetRecord:
        """Write a blob + metadata. Returns the AssetRecord.

        Idempotent: if the same content is put again, we keep the first
        record's metadata (first write wins) but update the timestamp.
        """
        if not data:
            raise ValueError("empty asset body")
        h = hashlib.sha256(data).hexdigest()
        ext = (ext or _guess_ext(data, "bin")).lstrip(".")
        mime = _MIME_EXTS.get(ext, mimetypes.guess_type(f"x.{ext}")[0] or "application/octet-stream")

        # Blob path: gallery/blobs/ab/<hash>.ext
        shard = h[:2]
        shard_dir = os.path.join(self.blob_dir, shard)
        os.makedirs(shard_dir, exist_ok=True)
        dest = os.path.join(shard_dir, f"{h}.{ext}")

        with self._lock:
            existing = self._index.get(h)
            if not os.path.exists(dest):
                # Atomic write via tempfile + rename
                fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=shard_dir)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
                    os.replace(tmp, dest)
                except Exception:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
                    raise

            if existing is None:
                rec = AssetRecord(
                    hash=h, ext=ext, mime=mime, size=len(data),
                    origin=origin, kind=kind, title=title,
                    prompt=prompt, model=model, seed=seed,
                    ts=time.time(),
                    tags=list(tags or []),
                    meta=dict(meta or {}),
                )
                self._index[h] = rec
            else:
                # Touch the timestamp; preserve the original origin/kind
                existing.ts = time.time()
                # Merge any new meta fields in
                if meta:
                    existing.meta.update(meta)
                if tags:
                    existing.tags = sorted(set(existing.tags) | set(tags))
                rec = existing
            self._save_index_locked()
        return rec

    # ── Read ────────────────────────────────────────────────────────

    def get(self, h: str) -> Optional[AssetRecord]:
        with self._lock:
            return self._index.get(h)

    def path(self, h: str) -> Optional[str]:
        rec = self.get(h)
        if not rec:
            return None
        p = os.path.join(self.blob_dir, h[:2], f"{h}.{rec.ext}")
        return p if os.path.isfile(p) else None

    def bytes_of(self, h: str) -> Optional[bytes]:
        p = self.path(h)
        if not p:
            return None
        try:
            with open(p, "rb") as f:
                return f.read()
        except Exception:
            return None

    def list_assets(self, *, origins: Optional[Iterable[str]] = None,
                    kinds: Optional[Iterable[str]] = None,
                    since_ts: float = 0.0,
                    limit: int = 50,
                    active_only: bool = False,
                    registry=None) -> list[AssetRecord]:
        """List recent assets, most-recent first.

        Args:
            origins: Only include these origins. None = all origins.
            kinds: Only include these kinds.
            since_ts: Only include assets with ts > this.
            limit: Max results.
            active_only: If True, filter to origins the registry
                reports as active. Overrides `origins`.
            registry: InterfaceRegistry instance used for active_only.
        """
        if active_only and registry is not None:
            origins = set(registry.active_interfaces()) | {"guild"}
        origin_set = set(origins) if origins is not None else None
        kind_set = set(kinds) if kinds is not None else None
        with self._lock:
            records = list(self._index.values())
        records.sort(key=lambda r: r.ts, reverse=True)
        out = []
        for r in records:
            if since_ts and r.ts <= since_ts:
                continue
            if origin_set is not None and r.origin not in origin_set:
                continue
            if kind_set is not None and r.kind not in kind_set:
                continue
            out.append(r)
            if len(out) >= limit:
                break
        return out

    # ── Delete ───────────────────────────────────────────────────────

    def delete(self, h: str) -> bool:
        p = self.path(h)
        with self._lock:
            rec = self._index.pop(h, None)
            if rec is None:
                return False
            self._save_index_locked()
        if p and os.path.isfile(p):
            try:
                os.unlink(p)
            except Exception:
                pass
        return True

    def stats(self) -> dict:
        with self._lock:
            n = len(self._index)
            total = sum(r.size for r in self._index.values())
        return {"asset_count": n, "total_bytes": total, "root": self.root}


# ── Helpers ──────────────────────────────────────────────────────────


def _guess_ext(data: bytes, default: str = "bin") -> str:
    """Guess extension from the first few bytes (magic-number sniffing).

    Handles the common image/video formats the gallery stores. Falls
    back to `default`.
    """
    if len(data) < 12:
        return default
    head = data[:12]
    # PNG
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    # JPEG
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    # GIF
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    # WebP (RIFF....WEBP)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    # MP4 (... ftyp ...)
    if head[4:8] == b"ftyp":
        return "mp4"
    # WebM
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    # JSON
    stripped = data.lstrip()[:1]
    if stripped in (b"{", b"["):
        return "json"
    return default
