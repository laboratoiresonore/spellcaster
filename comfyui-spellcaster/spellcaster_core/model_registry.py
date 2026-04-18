"""Model Registry — unified model discovery cache.

Every frontend (GIMP, Darktable, Resolve, Guild) previously hit
ComfyUI's `/object_info` endpoint independently to find out what
checkpoints / LoRAs / VAEs / upscale models were available. That's
slow (~200ms per query per node), duplicated across interfaces, and
becomes a "discover new model = restart every frontend" chore.

The registry fetches `/object_info` once every 5 minutes (configurable)
and serves the cached results over a single Guild endpoint. Every
frontend asks the Guild; the Guild consults ComfyUI at most once per
refresh interval. Install a new model in ComfyUI → visible in every
interface within the refresh window.

Architecture-aware: results are classified via model_detect.py so each
checkpoint carries its `arch` key (sd15/sdxl/flux1dev/flux2klein/chroma/
illustrious/zit/kontext/unknown).

Usage (server-side):

    from spellcaster_core.model_registry import get_registry
    reg = get_registry(comfy_url="http://...:8188")
    models = reg.snapshot()
    # {"checkpoints": [{"name": "...", "arch": "sdxl"}, ...], "loras": [...], ...}

Usage (plugin-side):

    GET /api/models  →  returns the snapshot
    GET /api/models?kind=checkpoints  →  just checkpoints
    GET /api/models?arch=sdxl  →  filter by architecture
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


_DEFAULT_TTL_S = 300.0   # 5 minutes
_FETCH_TIMEOUT_S = 10.0


# Node.field pairs that enumerate a given category on ComfyUI's
# /object_info endpoint. Each value appears under input.required.<field>
# as a list (spec[0]).
_CATEGORIES = {
    "checkpoints": [
        ("CheckpointLoaderSimple", "ckpt_name"),
    ],
    "unets": [
        ("UNETLoader", "unet_name"),
        ("UnetLoaderGGUF", "unet_name"),
    ],
    "loras": [
        ("LoraLoader", "lora_name"),
    ],
    "vaes": [
        ("VAELoader", "vae_name"),
    ],
    "clips": [
        ("CLIPLoader", "clip_name"),
        ("DualCLIPLoader", "clip_name1"),
    ],
    "upscale_models": [
        ("UpscaleModelLoader", "model_name"),
    ],
    "control_nets": [
        ("ControlNetLoader", "control_net_name"),
    ],
    "embeddings": [
        ("CLIPTextEncode", "text"),  # placeholder — embeddings aren't a discrete list in standard ComfyUI
    ],
}


class ModelRegistry:
    """Thread-safe TTL cache of ComfyUI model discovery."""

    def __init__(self, comfy_url: str, ttl_s: float = _DEFAULT_TTL_S):
        self.comfy_url = comfy_url.rstrip("/")
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._cache: dict = {}
        self._last_refresh: float = 0.0
        self._last_error: str = ""

    # ── Public API ───────────────────────────────────────────────────

    def snapshot(self, force_refresh: bool = False) -> dict:
        """Return the current cached snapshot, refreshing if stale."""
        now = time.time()
        with self._lock:
            needs_refresh = (
                force_refresh
                or not self._cache
                or (now - self._last_refresh) > self.ttl_s
            )
        if needs_refresh:
            self._refresh()
        with self._lock:
            return dict(self._cache)

    def kind(self, category: str, arch: Optional[str] = None) -> list:
        """Return just one category, optionally filtered by architecture."""
        snap = self.snapshot()
        items = list(snap.get(category, []))
        if arch:
            items = [m for m in items if m.get("arch") == arch]
        return items

    @property
    def last_refresh_ts(self) -> float:
        return self._last_refresh

    @property
    def last_error(self) -> str:
        return self._last_error

    # ── Refresh ──────────────────────────────────────────────────────

    def _refresh(self):
        try:
            from .model_detect import classify_ckpt_model, classify_unet_model
        except ImportError:
            classify_ckpt_model = lambda n: "unknown"
            classify_unet_model = lambda n: "unknown"

        fresh = {
            "checkpoints": [],
            "unets": [],
            "loras": [],
            "vaes": [],
            "clips": [],
            "upscale_models": [],
            "control_nets": [],
        }

        # Pull /object_info once for the whole manifest — cheaper than
        # per-node when ComfyUI has many nodes
        try:
            info = self._fetch_object_info()
        except Exception as e:
            with self._lock:
                self._last_error = f"/object_info fetch: {e}"
            return

        # Each category may pull from multiple node types; deduplicate
        # within a category by name
        for cat, nodes in _CATEGORIES.items():
            if cat == "embeddings":
                continue
            seen = set()
            items = []
            for node_type, field_name in nodes:
                node = info.get(node_type)
                if not node:
                    continue
                names = self._extract_names(node, field_name)
                for n in names:
                    if n in seen:
                        continue
                    seen.add(n)
                    rec = {"name": n, "node": node_type}
                    # Classify checkpoints + UNETs by architecture
                    if cat == "checkpoints":
                        rec["arch"] = classify_ckpt_model(n)
                    elif cat == "unets":
                        rec["arch"] = classify_unet_model(n)
                    items.append(rec)
            fresh[cat] = items

        with self._lock:
            self._cache = fresh
            self._last_refresh = time.time()
            self._last_error = ""

    def _fetch_object_info(self) -> dict:
        url = f"{self.comfy_url}/object_info"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _extract_names(node: dict, field: str) -> list:
        """Navigate the /object_info shape for a node's choice list.

        Structure: node["input"]["required"][field] is either:
          - [list_of_choices]
          - [list_of_choices, {"default": ..., "tooltip": ...}]
          - ["STRING", {...}]  (not a list — skip)
        """
        try:
            spec = node["input"]["required"][field]
        except (KeyError, TypeError):
            try:
                spec = node["input"]["optional"][field]
            except (KeyError, TypeError):
                return []
        if not isinstance(spec, list) or not spec:
            return []
        first = spec[0]
        if isinstance(first, list):
            return [str(x) for x in first]
        return []


# Singleton (one per comfy_url)
_REGISTRIES: dict = {}
_REGISTRIES_LOCK = threading.Lock()


def get_registry(comfy_url: str, ttl_s: float = _DEFAULT_TTL_S) -> ModelRegistry:
    """Get-or-create the singleton registry for a given ComfyUI URL."""
    key = comfy_url.rstrip("/")
    with _REGISTRIES_LOCK:
        reg = _REGISTRIES.get(key)
        if reg is None:
            reg = ModelRegistry(key, ttl_s=ttl_s)
            _REGISTRIES[key] = reg
    return reg
