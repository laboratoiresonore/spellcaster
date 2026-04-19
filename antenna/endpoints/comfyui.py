"""ComfyUI service endpoints — antenna-driven node + model install.

Implements:

  POST /install-node   — git-clone a custom-node repo into the remote
                         ComfyUI's custom_nodes/ dir, install requirements.
  POST /install-model  — download a model file into the remote ComfyUI's
                         models/<kind>/ dir, with optional hf/civitai auth.

Both endpoints ENFORCE a manifest allowlist — a caller can only install
things that appear in the canonical `installer/manifest.json`. This
prevents a compromised client from tricking the agent into cloning a
malicious repo or saving an arbitrary URL's contents under models/.

The manifest is fetched live via `installer/remote_services.py`'s
cousin pattern: prefer GitHub-raw, fall back to the baked copy. The
agent re-reads on each request so pushed manifest changes reach remote
antennas without `/self-update`.

Design constraints
------------------
- **Reuse, don't duplicate**: `installer/install.py` already has robust
  `download_file` (civitai/hf token handling, size checks, atomic
  rename) and `git_clone` (ZIP fallback when git missing). The antenna
  imports those — no parallel implementation.
- **Bounded execution**: both endpoints block for the full install.
  That's fine for nodes (seconds) and small models (minutes). For
  multi-GB model downloads the client should expect a long-running
  HTTPS connection — document this.
- **Never execute user-supplied code outside the manifest allowlist**.
- **Audit every install** — the agent's audit log in `~/.spellcaster/`
  already records every authenticated request. Install success/failure
  is visible there.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import bus_client


# Lazy-import the installer's primitives; antenna/ and installer/ live in
# the same repo so this works as long as the agent was bootstrapped via
# the full `git clone` path (which is how every antenna is started).
def _import_installer():
    try:
        _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                   "..", ".."))
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        from installer import install as _install  # type: ignore
        return _install
    except ImportError as e:
        raise RuntimeError(
            f"antenna cannot reach installer module: {e}. "
            "Re-clone the spellcaster repo or run /self-update."
        )


# ─── Manifest fetch (with bake fallback) ──────────────────────────────────

_MANIFEST_URL = (
    "https://raw.githubusercontent.com/laboratoiresonore/"
    "spellcaster/main/installer/manifest.json"
)

# 60s cache — enough to coalesce a burst of requests, short enough that
# a pushed manifest change reaches every antenna within a minute.
_MANIFEST_CACHE: dict[str, Any] | None = None
_MANIFEST_CACHE_TS: float = 0.0
_MANIFEST_CACHE_TTL = 60.0


def _load_manifest() -> dict[str, Any]:
    """Return the current manifest. Fetches from GitHub, falls back to
    the baked installer/manifest.json on any network failure.
    """
    global _MANIFEST_CACHE, _MANIFEST_CACHE_TS
    now = time.time()
    if _MANIFEST_CACHE is not None and (now - _MANIFEST_CACHE_TS) < _MANIFEST_CACHE_TTL:
        return _MANIFEST_CACHE

    manifest: dict[str, Any] | None = None
    # Try remote first
    try:
        req = urllib.request.Request(_MANIFEST_URL, headers={
            "User-Agent": "spellcaster-antenna",
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            manifest = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            json.JSONDecodeError):
        manifest = None

    # Fall back to the baked copy shipped with the repo
    if manifest is None:
        baked = Path(__file__).resolve().parents[2] / "installer" / "manifest.json"
        if baked.is_file():
            try:
                manifest = json.loads(baked.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = None

    if manifest is None:
        raise RuntimeError("manifest unavailable — no network and no baked copy")

    _MANIFEST_CACHE = manifest
    _MANIFEST_CACHE_TS = now
    return manifest


# ─── ComfyUI root resolver ────────────────────────────────────────────────

def _comfyui_root(cfg: dict[str, Any]) -> Path | None:
    """Locate the ComfyUI install root on this machine.

    Priority: cfg['comfyui_root'] (explicit user config) > auto-detect via
    the installer's find_default_comfyui() helper. Returns None if neither
    finds anything installed — the endpoint will return 503 in that case.
    """
    explicit = (cfg.get("comfyui_root") or "").strip()
    if explicit and explicit != "auto":
        p = Path(os.path.expanduser(explicit))
        if p.is_dir():
            return p
    try:
        _install = _import_installer()
        found = _install.find_default_comfyui()
        if found:
            return Path(found)
    except Exception:
        pass
    return None


# ─── POST /install-node ───────────────────────────────────────────────────

def install_node(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /install-node

    Request body:
        {
          "node_key": "ComfyUI-Spellcaster",  // must match manifest.custom_nodes key
        }

    Response 200:
        {
          "node_key": "...",
          "installed_at": "<comfyui_root>/custom_nodes/<name>",
          "took_seconds": 4.7,
          "requirements_installed": true/false
        }

    Response 400: validation error (bad key, key not in manifest)
    Response 503: ComfyUI root not locatable on this machine
    Response 500: git/network/disk failure during install
    """
    body = ctx.get("body") or {}
    node_key = (body.get("node_key") or "").strip()
    if not node_key:
        return 400, {"error": "node_key required"}

    # Manifest validation — no arbitrary repos
    try:
        manifest = _load_manifest()
    except RuntimeError as e:
        return 500, {"error": str(e)}
    nodes = manifest.get("custom_nodes") or {}
    node_def = nodes.get(node_key)
    if not node_def:
        return 400, {
            "error": f"unknown node_key: {node_key!r}",
            "hint": "Must match a key under manifest.json's 'custom_nodes' dict",
            "available_keys": sorted(nodes.keys())[:20],
        }
    repo_url = (node_def.get("repo") or "").strip()
    if not repo_url or not repo_url.startswith(("https://github.com/",
                                                 "https://gitlab.com/",
                                                 "https://codeberg.org/")):
        return 500, {"error": f"manifest entry {node_key!r} lacks a trusted repo URL"}

    # Locate ComfyUI
    root = _comfyui_root(ctx["config"])
    if root is None:
        return 503, {"error": "ComfyUI not detected on this machine",
                     "hint": "Set comfyui_root in antenna_config.json or install ComfyUI"}

    custom_nodes_dir = root / "custom_nodes"
    custom_nodes_dir.mkdir(parents=True, exist_ok=True)
    dest = custom_nodes_dir / node_key

    # Clone (or pull if already present) — reuses installer's robust helper
    t_start = time.time()
    try:
        _install = _import_installer()
        ok = _install.git_clone(repo_url, dest, dry_run=False)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"clone failed: {type(e).__name__}: {e}"}

    if not ok:
        return 500, {"error": "git clone failed (see agent logs for details)"}

    # Requirements — best-effort (some node packs ship no requirements.txt)
    req_ok = False
    try:
        req_ok = bool(_install.install_node_requirements(dest, root, dry_run=False))
    except Exception:
        req_ok = False

    took = round(time.time() - t_start, 1)
    result = {
        "node_key": node_key,
        "installed_at": str(dest),
        "took_seconds": took,
        "requirements_installed": req_ok,
    }
    # Tell the hub so its UI can react (fire-and-forget, silent on failure)
    bus_client.emit(ctx, "antenna.node.installed", result)
    return 200, result


# ─── POST /install-model ──────────────────────────────────────────────────

def _find_manifest_model(manifest: dict[str, Any], model_path: str) -> dict | None:
    """Walk manifest.features[*].models for an entry whose 'path' matches.

    Handles both schema shapes found in manifest.json:
      - Lists (e.g. `"checkpoints": [{path, url, size_mb}, ...]`)
      - Tier dicts (e.g. `"llm_tiers": {"low": {path, url, ...}, ...}`)
      - Plain dict values ({"note": "..."} is skipped)

    Returns the full model dict (with path, url, size_mb, sha256?) or None.
    """
    model_path_norm = model_path.replace("\\", "/").strip("/")

    def _check(candidate: dict) -> dict | None:
        if not isinstance(candidate, dict):
            return None
        p = (candidate.get("path") or "").replace("\\", "/").strip("/")
        if p == model_path_norm:
            return candidate
        return None

    for feat in (manifest.get("features") or {}).values():
        models_section = feat.get("models") or {}
        for group_key, group in models_section.items():
            if group_key == "note":
                continue
            if isinstance(group, list):
                for m in group:
                    hit = _check(m)
                    if hit:
                        return hit
            elif isinstance(group, dict):
                # Tier-map or single-model dict — check nested values too
                for v in group.values():
                    hit = _check(v)
                    if hit:
                        return hit
                # Also check if the group itself is the model entry
                hit = _check(group)
                if hit:
                    return hit
    return None


def install_model(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /install-model

    Request body:
        {
          "model_key": "checkpoints/SDXL/juggernaut_xl_v9.safetensors",
          "hf_token":     null,     // optional — gated HF repos
          "civitai_key":  null      // optional — private CivitAI models
        }

    The `model_key` must exactly match the `path` field on a model entry
    in manifest.features.<any>.models.<any>. This guarantees the URL, size,
    and optional sha256 come from the authoritative manifest, not the
    caller. A compromised client can't redirect the download.

    Response 200:
        {
          "model_key": "...",
          "saved_to": "<comfyui_root>/models/<kind>/<filename>",
          "bytes": 6843821568,
          "took_seconds": 127.3
        }

    Long-running: multi-GB models can take 10+ minutes. Clients should
    expect a long-lived HTTPS connection with no streaming progress
    (blocking response). A future /install-model/progress endpoint
    would address this; out of scope for Phase 2.
    """
    body = ctx.get("body") or {}
    model_key = (body.get("model_key") or "").strip()
    if not model_key:
        return 400, {"error": "model_key required"}

    try:
        manifest = _load_manifest()
    except RuntimeError as e:
        return 500, {"error": str(e)}

    entry = _find_manifest_model(manifest, model_key)
    if entry is None:
        return 400, {
            "error": f"unknown model_key: {model_key!r}",
            "hint": "Must match a 'path' under manifest.features.<any>.models.<any>",
        }

    url = (entry.get("url") or "").strip()
    if not url:
        return 500, {"error": f"manifest entry for {model_key!r} has no url"}

    root = _comfyui_root(ctx["config"])
    if root is None:
        return 503, {"error": "ComfyUI not detected on this machine"}

    # model_key is relative to the ComfyUI models/ dir ("checkpoints/X/Y.safetensors")
    dest = root / "models" / model_key
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Skip if already present and the size matches — operators may re-run
    # install-model for retry/idempotency. Don't redownload gigabytes.
    expected_bytes = int(entry.get("size_mb", 0)) * 1024 * 1024
    if dest.exists() and expected_bytes > 0:
        actual_bytes = dest.stat().st_size
        # Allow 1% tolerance — size_mb is approximate in the manifest
        tolerance = max(expected_bytes // 100, 1024 * 1024)
        if abs(actual_bytes - expected_bytes) <= tolerance:
            return 200, {
                "model_key": model_key,
                "saved_to": str(dest),
                "bytes": actual_bytes,
                "took_seconds": 0.0,
                "note": "already installed (size within tolerance)",
            }

    # Download — reuse installer's download_file (handles hf/civitai tokens,
    # progress to stderr, atomic .tmp + rename, size verification)
    hf_token = (body.get("hf_token") or "").strip()
    civitai_key = (body.get("civitai_key") or "").strip()
    t_start = time.time()
    try:
        _install = _import_installer()
        ok = _install.download_file(url, dest, dry_run=False,
                                     civitai_key=civitai_key, hf_token=hf_token)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": f"download failed: {type(e).__name__}: {e}"}

    if not ok or not dest.exists():
        return 500, {"error": "download failed (see agent logs)"}

    took = round(time.time() - t_start, 1)
    result = {
        "model_key": model_key,
        "saved_to": str(dest),
        "bytes": dest.stat().st_size,
        "took_seconds": took,
    }
    bus_client.emit(ctx, "antenna.model.installed", result)
    return 200, result
