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


# ────────────────────────────────────────────────────────────────────────
# Whimweaver replay-value bridge surface (proxy helpers)
# ────────────────────────────────────────────────────────────────────────
#
# These three helpers expose just enough of spellcaster's identity-
# preserving pipeline for whimweaver's "infinite memory + HIGH replay
# value" character system. Whimweaver owns the on-disk reservoir layout
# (one JSONL per character at `<reservoir_root>/<character_id>/
# portraits.jsonl`); these helpers only read/write that file.
#
# The functions are deliberately I/O-cheap and import-cheap — no ComfyUI
# submission happens here. They return a builder-name + builder-kwargs
# dict that whimweaver passes to its existing spellcaster_proxy +
# ComfyUI submitter.
#
# See `_dev_docs/WHIMWEAVER_REPLAY_BRIDGE_PROPOSAL.md` for full schema +
# integration notes.


_PORTRAITS_FILENAME = "portraits.jsonl"


# Builder routing order — best identity preservation first. We prefer
# PuLID-Flux for face-locked generation, then Klein img2img_ref with
# identity_lock=True, then Klein headswap, then plain Klein img2img,
# then SDXL img2img as a last resort.
_BUILDER_PREFERENCE: tuple[str, ...] = (
    "build_pulid_flux",
    "build_klein_img2img_ref",
    "build_klein_headswap",
    "build_klein_img2img",
    "build_sdxl_img2img",
)


def _portraits_path(reservoir_root, character_id: str) -> str:
    """Resolve the JSONL path for a character. `reservoir_root` may be a
    Path or a str — we accept either to keep the proxy boundary thin."""
    root = os.fspath(reservoir_root)
    return os.path.join(root, character_id, _PORTRAITS_FILENAME)


def _read_portrait_records(portraits_path: str) -> list[dict]:
    """Load every JSON line. Skips blank/corrupt lines silently — the
    whimweaver writer is append-only and a half-written tail line is
    expected on crash."""
    if not os.path.isfile(portraits_path):
        return []
    records: list[dict] = []
    try:
        with open(portraits_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    # Tolerate one bad tail line (crash mid-write).
                    continue
    except OSError:
        return []
    return records


def _write_portrait_records_atomic(portraits_path: str,
                                   records: list[dict]) -> bool:
    """Rewrite the JSONL atomically via tempfile + os.replace."""
    parent = os.path.dirname(portraits_path)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError:
        return False
    fd, tmp = tempfile.mkstemp(prefix=".tmp_portraits_", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, portraits_path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def get_character_portrait_history(
    character_id: str,
    *,
    reservoir_root,
    limit: int = 20,
) -> list[dict]:
    """Return portrait records for a character, newest first.

    Each record carries:
      - portrait_id          (str, unique within the character)
      - image_path           (str, abs path or gallery-hash:// URI)
      - builder              (str, one of the build_* names)
      - model_family         (str, e.g. "flux2_klein", "flux1_dev", "sdxl")
      - prompt_seed          (int)
      - parent_portrait_id   (str | None, points to the reference portrait
                              this one was conditioned on)
      - generated_at         (float, unix ts)
      - canonical            (bool, the seed portrait for the consistency
                              loop — there should be at most one True)

    Returns [] when the reservoir file is missing or empty.
    """
    if not character_id:
        return []
    portraits_path = _portraits_path(reservoir_root, character_id)
    records = _read_portrait_records(portraits_path)
    records.sort(key=lambda r: r.get("generated_at", 0.0), reverse=True)
    if limit > 0:
        records = records[:limit]
    return records


def _pick_reference_portrait(records: list[dict]) -> dict | None:
    """Return the portrait whimweaver should condition on:
      1. The first record marked canonical=True (newest if multiple).
      2. Otherwise the newest record overall.
      3. None if records is empty."""
    if not records:
        return None
    canonical = [r for r in records if r.get("canonical")]
    if canonical:
        canonical.sort(key=lambda r: r.get("generated_at", 0.0), reverse=True)
        return canonical[0]
    return records[0]  # newest by virtue of caller sorting


def _builder_supported(builder: str, feature_caps: dict | None) -> bool:
    """Cheap capability check. The /v1/capabilities payload exposes a
    `builders` map (builder_name → {available: bool, ...}) per the
    spellcaster manifest. We default to True when caps are absent so
    proxy callers without /v1/capabilities still get a usable result."""
    if not feature_caps:
        return True
    builders = feature_caps.get("builders") or {}
    if not isinstance(builders, dict):
        return True
    entry = builders.get(builder)
    if entry is None:
        # Not listed = assume unavailable (caps was provided, builder
        # missing means the host doesn't ship it).
        return False
    if isinstance(entry, dict):
        return bool(entry.get("available", True))
    return bool(entry)


def build_consistent_portrait_for_character(
    character_id: str,
    prompt: str,
    *,
    reservoir_root,
    builder_hint: str | None = None,
    feature_caps: dict | None = None,
) -> dict:
    """Pick the best identity-preserving builder for this character and
    return a submission packet for whimweaver to dispatch.

    Returns a dict shaped like:
        {
          "builder":              "build_pulid_flux" | "build_klein_*" | ...,
          "builder_args":         {kwargs ready to pass through proxy},
          "reference_portrait_id": str | None,
          "reference_image_path": str | None,
          "fallback_chain":       [str, ...],   # builders considered, in order
        }

    `builder_hint` (optional) lets the caller force-prefer a specific
    builder name — it is honored when feature_caps allow it, otherwise
    we fall through the default preference order.

    This function does NOT submit anything to ComfyUI. The caller is
    expected to import `spellcaster_proxy.<builder>` and submit the
    resulting workflow themselves.
    """
    if not character_id:
        raise ValueError("character_id is required")
    if not prompt:
        raise ValueError("prompt is required")

    history = get_character_portrait_history(
        character_id, reservoir_root=reservoir_root, limit=20
    )
    ref = _pick_reference_portrait(history)
    ref_id = ref.get("portrait_id") if ref else None
    ref_path = ref.get("image_path") if ref else None

    # Build the preference order. Honor builder_hint when supported.
    pref: list[str] = list(_BUILDER_PREFERENCE)
    if builder_hint and builder_hint in pref:
        pref.remove(builder_hint)
        pref.insert(0, builder_hint)

    # If no reference image is on file, the identity-preserving builders
    # have nothing to lock onto — fall back to plain image-to-image or
    # text-to-image. We expose this via the chain anyway so the caller
    # can decide.
    if ref_path is None:
        pref = [b for b in pref if b not in (
            "build_pulid_flux",
            "build_klein_img2img_ref",
            "build_klein_headswap",
        )]
        if not pref:
            pref = ["build_klein_img2img"]

    # Pick the first builder the caps allow.
    chosen: str | None = None
    for b in pref:
        if _builder_supported(b, feature_caps):
            chosen = b
            break
    if chosen is None:
        # Caps blocked everything in our preference order. Fall back to
        # the most permissive option so callers can at least try.
        chosen = pref[0]

    builder_args = _builder_args_for(
        chosen, prompt=prompt, ref_path=ref_path, ref=ref,
    )

    return {
        "builder": chosen,
        "builder_args": builder_args,
        "reference_portrait_id": ref_id,
        "reference_image_path": ref_path,
        "fallback_chain": pref,
    }


def _builder_args_for(builder: str, *, prompt: str,
                      ref_path: str | None, ref: dict | None) -> dict:
    """Translate the chosen builder into a kwargs dict whimweaver can
    splat onto the proxy call. We pass only minimal fields here — the
    caller layers their own seed, model, lora, and dimension policy on
    top. The seed (when ref exists) defaults to the reference portrait's
    seed so re-rolls tend to converge."""
    seed = (ref or {}).get("prompt_seed") if ref else None

    if builder == "build_pulid_flux":
        return {
            "face_ref_filename": ref_path,
            "prompt_text": prompt,
            "negative_text": "",
            "seed": seed,
        }
    if builder == "build_klein_img2img_ref":
        return {
            "ref_filename": ref_path,
            "image_filename": ref_path,  # caller may override with a base
            "prompt_text": prompt,
            "seed": seed,
            "identity_lock": True,
        }
    if builder == "build_klein_headswap":
        return {
            "target_filename": ref_path,  # caller usually overrides w/ new body
            "source_filename": ref_path,
            "prompt": prompt,
            "seed": seed,
            "use_identity_lock": True,
        }
    if builder == "build_klein_img2img":
        return {
            "image_filename": ref_path,
            "prompt_text": prompt,
            "seed": seed,
        }
    # SDXL fallback — caller wires the actual SDXL builder name in their
    # workflows module if they want it; we expose a generic shape.
    return {
        "image_filename": ref_path,
        "prompt_text": prompt,
        "seed": seed,
    }


def mark_canonical_portrait(
    character_id: str,
    portrait_id: str,
    *,
    reservoir_root,
) -> bool:
    """Set canonical=True on the named portrait and canonical=False on
    every other portrait for the same character.

    Returns True when the target portrait_id was found and the file was
    rewritten successfully; False otherwise (missing file, missing id,
    or write failure)."""
    if not character_id or not portrait_id:
        return False
    portraits_path = _portraits_path(reservoir_root, character_id)
    records = _read_portrait_records(portraits_path)
    if not records:
        return False
    found = False
    for r in records:
        if r.get("portrait_id") == portrait_id:
            r["canonical"] = True
            found = True
        else:
            if r.get("canonical"):
                r["canonical"] = False
    if not found:
        return False
    return _write_portrait_records_atomic(portraits_path, records)
