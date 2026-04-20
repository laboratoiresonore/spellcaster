"""Detect models already installed on a remote ComfyUI server and
probe Civitai for newer versions of manifest entries.

The installer's local ``dest.exists()`` check only catches models on
the machine running the installer. When the user's ComfyUI sits on a
different box \u2014 the common Spellcaster setup \u2014 every manifest
entry looks missing, so the installer proposes to re-download
everything the user already has. This module fixes that.

Two surfaces:

  * ``enumerate_server_models(comfyui_url)`` \u2014 hits
    ``/object_info/<Loader>`` for every loader class that exposes a
    file list (CheckpointLoaderSimple, LoraLoader, ControlNetLoader,
    VAELoader, CLIPLoader, UNETLoader, UpscaleModelLoader). Returns
    ``{category: set(filenames)}``. Safe to call against an offline
    server \u2014 returns empty dict with a printed warning.
  * ``detect_available_updates(manifest, installed, civitai_key)``
    \u2014 for every manifest entry that points at a Civitai model page,
    resolves the latest version-id. Compares to the URL baked into
    the manifest; when they diverge, records an ``update_available``
    action with the new download URL.

The returned plan feeds into ``step_install_models`` so the user only
sees ``[INSTALL]`` for truly-missing files and ``[UPDATE]`` for
out-of-date ones. Already-present entries are silent (caller reports
them separately).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


# Loader classes whose ``input.required`` dict exposes the full list
# of installed files \u2014 the same surface the UI uses to populate
# LoRA / checkpoint dropdowns. Matching the input field to our manifest
# category tells us which ``models/<subdir>/`` the files live under.
_LOADER_CLASSES: dict[str, tuple[str, str]] = {
    "CheckpointLoaderSimple": ("checkpoints", "ckpt_name"),
    "LoraLoader":             ("loras",       "lora_name"),
    "ControlNetLoader":       ("controlnet",  "control_net_name"),
    "VAELoader":              ("vae",         "vae_name"),
    "CLIPLoader":             ("clip",        "clip_name"),
    "CLIPLoaderGGUF":         ("clip",        "clip_name"),
    "DualCLIPLoader":         ("clip",        "clip_name1"),
    "UNETLoader":             ("unet",        "unet_name"),
    "UnetLoaderGGUF":         ("unet",        "unet_name"),
    "UpscaleModelLoader":     ("upscale_models", "model_name"),
}


def enumerate_server_models(comfyui_url: str, *, timeout: float = 8.0
                              ) -> dict[str, set[str]]:
    """Return ``{category: set(filenames)}`` for every loader class.

    Filenames are returned as-given by ComfyUI \u2014 typically with
    Windows backslashes in nested folders. Callers that need to match
    against manifest paths should normalise both sides via
    :func:`normalise_model_path`.
    """
    out: dict[str, set[str]] = {}
    base = comfyui_url.rstrip("/")
    for cls, (category, field) in _LOADER_CLASSES.items():
        url = f"{base}/object_info/{urllib.parse.quote(cls)}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Spellcaster-Installer/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, json.JSONDecodeError, OSError):
            # Node pack not installed or server offline. Any missing
            # loader just means "we don't know about those" \u2014 don't
            # poison the detection with half-truths; leave the category
            # untouched so downstream treats manifest entries as
            # missing (safe default).
            continue
        inputs = (data.get(cls, {}).get("input", {}).get("required", {}) or {})
        values = inputs.get(field, [[]])
        if (isinstance(values, list) and values
                and isinstance(values[0], list)):
            out.setdefault(category, set()).update(values[0])
    return out


def normalise_model_path(s: str) -> str:
    """Collapse separators + lowercase for matching.

    ComfyUI returns ``SDXL\\Base\\foo.safetensors``; the manifest has
    ``checkpoints/SDXL/Base/foo.safetensors``. We split on both,
    lowercase, and rejoin with forward slash so the two align.
    """
    return s.replace("\\", "/").lower()


def _basename_of(path: str) -> str:
    """Last path segment, lowercased \u2014 our final-resort matcher."""
    return normalise_model_path(path).rsplit("/", 1)[-1]


def is_installed_on_server(manifest_rel_path: str, category: str,
                            server_models: dict[str, set[str]]) -> bool:
    """True when the manifest path's basename is present in the server
    index for the same category.

    We match on basename rather than full path because server folder
    structures often differ from the manifest's nominal layout (users
    reorganise, pack authors drop files in custom subdirs, etc.).
    """
    files = server_models.get(category) or set()
    if not files:
        return False
    target = _basename_of(manifest_rel_path)
    for f in files:
        if _basename_of(f) == target:
            return True
    return False


# ── Civitai latest-version probing ─────────────────────────────────────

_CIVITAI_MODEL_ID_RE = re.compile(r"civitai\.com/models/(\d+)", re.IGNORECASE)
_CIVITAI_VERSION_ID_RE = re.compile(
    r"civitai\.com/api/download/models/(\d+)", re.IGNORECASE)


def _civitai_model_id(page_url: str) -> Optional[int]:
    m = _CIVITAI_MODEL_ID_RE.search(page_url or "")
    return int(m.group(1)) if m else None


def _civitai_version_id(download_url: str) -> Optional[int]:
    m = _CIVITAI_VERSION_ID_RE.search(download_url or "")
    return int(m.group(1)) if m else None


def _civitai_latest_version(model_id: int, *, civitai_key: str = "",
                            timeout: float = 10.0) -> Optional[dict]:
    """Return the latest ``modelVersions`` entry for a Civitai model id.

    Civitai sorts versions newest-first. The zeroth entry is therefore
    the latest. Returns ``None`` on any failure so the caller skips
    the "update" path for that entry (safer than proposing a broken
    download).
    """
    url = f"https://civitai.com/api/v1/models/{model_id}"
    headers = {"User-Agent": "Spellcaster-Installer/1.0",
               "Accept": "application/json"}
    if civitai_key:
        headers["Authorization"] = f"Bearer {civitai_key}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, json.JSONDecodeError, OSError):
        return None
    versions = data.get("modelVersions") or []
    if not versions:
        return None
    return versions[0]


def _latest_download_url(latest_version: dict) -> Optional[str]:
    """Pick the primary file's download URL from a Civitai version."""
    files = latest_version.get("files") or []
    primary = next((f for f in files if f.get("primary")), None)
    if not primary and files:
        primary = files[0]
    if not primary:
        return None
    return primary.get("downloadUrl") or None


def detect_available_updates(
        items: list[dict], *, civitai_key: str = "",
        progress_cb=None,
) -> list[dict]:
    """Given a flat list of manifest model entries, return an updates
    report.

    Each input item must carry ``path``, ``page_url``, and optionally
    ``url``. The report appends per-item status records:

      - ``"status": "update_available"`` with ``latest_url`` + ``latest_size_mb``
      - ``"status": "current"`` (manifest URL matches Civitai's latest)
      - ``"status": "not_civitai"`` (HuggingFace or null URL \u2014 skipped)
      - ``"status": "lookup_failed"`` (API error \u2014 fallback to
        the manifest URL as-is)

    ``progress_cb(i, total, item)`` is called before each probe so the
    caller can render a progress bar.
    """
    report: list[dict] = []
    total = len(items)
    for i, item in enumerate(items):
        if progress_cb:
            try:
                progress_cb(i, total, item)
            except Exception:
                pass
        rec = {"path": item.get("path"),
               "page_url": item.get("page_url"),
               "current_url": item.get("url"),
               "status": "not_civitai",
               "latest_url": None,
               "latest_size_mb": None,
               "latest_version_id": None,
               "note": ""}
        model_id = _civitai_model_id(item.get("page_url") or "")
        if model_id is None:
            report.append(rec)
            continue
        latest = _civitai_latest_version(model_id, civitai_key=civitai_key)
        if latest is None:
            rec["status"] = "lookup_failed"
            rec["note"] = "Civitai API unreachable; using manifest URL as-is."
            report.append(rec)
            continue
        latest_vid = latest.get("id")
        latest_url = _latest_download_url(latest)
        rec["latest_version_id"] = latest_vid
        rec["latest_url"] = latest_url
        files = latest.get("files") or []
        primary = next((f for f in files if f.get("primary")), None) or (files[0] if files else {})
        size_kb = primary.get("sizeKB") or 0
        rec["latest_size_mb"] = int(size_kb / 1024) if size_kb else None
        manifest_vid = _civitai_version_id(item.get("url") or "")
        if manifest_vid and latest_vid and manifest_vid == latest_vid:
            rec["status"] = "current"
            rec["note"] = f"manifest matches latest v{latest_vid}"
        elif manifest_vid and latest_vid and manifest_vid != latest_vid:
            rec["status"] = "update_available"
            rec["note"] = f"manifest v{manifest_vid} \u2192 latest v{latest_vid}"
        elif not manifest_vid and latest_vid:
            # Manifest had no direct URL (requires manual download).
            # Surfacing the Civitai-latest URL lets us propose an
            # auto-download in that slot.
            rec["status"] = "update_available"
            rec["note"] = f"no manifest URL; latest v{latest_vid} available"
        else:
            rec["status"] = "current"
        report.append(rec)
    return report


def build_install_plan(
        manifest: dict, *,
        comfyui_url: Optional[str] = None,
        local_models_dir: Optional[str] = None,
        civitai_key: str = "",
        selected_features: Optional[set[str]] = None,
        probe_civitai: bool = False,
        progress_cb=None,
) -> dict:
    """One-shot planner: for every manifest model entry, decide
    INSTALL / UPDATE / SKIP.

    Precedence for "already installed":
      1. ``comfyui_url`` set and file is in its loader enumeration \u2014 SKIP.
      2. ``local_models_dir`` set and the destination path exists on
         disk \u2014 SKIP.

    When ``probe_civitai=True`` AND the entry has a Civitai page URL,
    the planner will also hit the API to check whether a newer version
    is available; if so, the plan records ``status="update"`` with the
    fresh ``url``. When ``probe_civitai=False`` (default), the existing
    manifest URL is used as-is.

    Returns a dict ``{install: [...], update: [...], skip: [...], errors: [...]}``.
    Each item is a copy of the manifest entry plus ``feature_key`` +
    ``status_reason``.
    """
    server_models: dict[str, set[str]] = {}
    if comfyui_url:
        try:
            server_models = enumerate_server_models(comfyui_url)
        except Exception as e:
            server_models = {}
            print(f"  [installer] server probe failed: {e}")

    plan: dict[str, list[dict]] = {
        "install": [], "update": [], "skip": [], "errors": []}

    # Flat list of (feature_key, category, item) triples to iterate.
    flat: list[tuple[str, str, dict]] = []
    for feat_key, feat in manifest.get("features", {}).items():
        if selected_features is not None and feat_key not in selected_features:
            continue
        models_section = feat.get("models") or {}
        for category, items in models_section.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    flat.append((feat_key, category, dict(item)))

    # Optional Civitai probe \u2014 done BEFORE the install/skip
    # decision so the "update available" state can flow into the plan.
    civitai_updates: dict[str, dict] = {}
    if probe_civitai and flat:
        update_probes = [item for _, _, item in flat
                          if item.get("page_url") and "civitai.com" in (item.get("page_url") or "")]
        if update_probes:
            rows = detect_available_updates(
                update_probes, civitai_key=civitai_key,
                progress_cb=progress_cb)
            for r in rows:
                p = r.get("path")
                if p:
                    civitai_updates[p] = r

    for feat_key, category, item in flat:
        path = item.get("path", "")
        item["feature_key"] = feat_key
        item["category"] = category

        # Step 1 \u2014 already on the user's ComfyUI server?
        if server_models and is_installed_on_server(
                path, category, server_models):
            item["status_reason"] = "already present on ComfyUI server"
            plan["skip"].append(item)
            continue

        # Step 2 \u2014 already in the local models dir?
        if local_models_dir:
            try:
                from pathlib import Path
                dest = Path(local_models_dir) / path
                if dest.exists():
                    item["status_reason"] = "already present on local disk"
                    plan["skip"].append(item)
                    continue
            except Exception:
                pass

        # Step 3 \u2014 Civitai update available?
        upd = civitai_updates.get(path) if probe_civitai else None
        if upd and upd.get("status") == "update_available" and upd.get("latest_url"):
            item["url"] = upd["latest_url"]
            if upd.get("latest_size_mb"):
                item["size_mb"] = upd["latest_size_mb"]
            item["status_reason"] = upd.get("note") or "Civitai update available"
            plan["update"].append(item)
            continue

        # Step 4 \u2014 default: install as-is from manifest.
        if not item.get("url"):
            # No download URL and not installed anywhere \u2014 user
            # must download manually via page_url.
            item["status_reason"] = "no direct URL; manual download required"
            plan["errors"].append(item)
            continue
        item["status_reason"] = "not installed; fetch from manifest URL"
        plan["install"].append(item)

    return plan


def summarise_plan(plan: dict) -> str:
    """Render a human-readable summary of a plan dict."""
    lines = []
    lines.append(f"  INSTALL:   {len(plan['install'])} file(s)")
    lines.append(f"  UPDATE:    {len(plan['update'])} file(s)")
    lines.append(f"  SKIP:      {len(plan['skip'])} file(s) already present")
    if plan["errors"]:
        lines.append(f"  MANUAL:    {len(plan['errors'])} require manual download")
    return "\n".join(lines)


__all__ = [
    "enumerate_server_models",
    "is_installed_on_server",
    "normalise_model_path",
    "detect_available_updates",
    "build_install_plan",
    "summarise_plan",
]
