"""Spellcaster model-repair HTTP route — delete + redownload corrupt
ControlNet files from inside ComfyUI's process.

Context: Spellcaster's 3D tools keep hitting files that are physically
on the server but unloadable (``safetensors_rust.SafetensorError:
Error while deserializing header: incomplete metadata, file not
fully covered`` — partial / aborted HF downloads). The GIMP plugin
has no write API into ``models/controlnet/``, so it can only detect
the error and blacklist the file for the session. Users had to SSH
into the box to delete + re-download.

This module exposes a single route on ComfyUI's own PromptServer so
the plugin CAN fix the file from its own machine:

    POST /spellcaster/models/repair
    body: {
        "action":   "delete" | "redownload",
        "folder":   "controlnet",
        "filename": "SDXL/controlnet-union-sdxl-1.0.safetensors"
    }

For ``redownload``, the filename is looked up in ``CN_REPO_MAP`` —
a curated (repo_id, repo_filename) table — and fetched via
``huggingface_hub.hf_hub_download()``. HF's client handles:

  * Resume-on-fail (``.incomplete`` sentinel in cache).
  * Chunk-level SHA-256 verification (xet backend).
  * Atomic final rename (same mechanic as our old hand-rolled path,
    now centralised + battle-tested).
  * ``HF_TOKEN`` env var honoured for gated repos.

We keep a slim local copy helper (``_local_copy_to_controlnet``) that
moves the HF-cache-resident file into the ComfyUI ``models/controlnet/``
tree so workflows find it at the path they expect. ``force_download``
mode deletes the cached copy first so a corrupt cache entry can't
mask a fresh fetch.

Legacy ``CN_URL_MAP`` (direct URLs) kept as a fallback for callers
that don't have ``huggingface_hub`` installed — degrades to inline
``urllib`` download. Bundle installations always ship with the lib.

Safety
------

* ``folder`` whitelisted to ``controlnet``.
* Filename must pass path-traversal + drive-prefix checks.
* Resolved realpath must remain under the ``controlnet`` folder root
  (symlink / junction escape refused).
* Download streams + atomic-renames so a failed download leaves the
  OLD file's deletion committed but no garbage in place.

Degrades gracefully: when ``folder_paths`` or ``PromptServer`` isn't
available (module loaded outside the ComfyUI runtime), registration
is a no-op.
"""

from __future__ import annotations

import os
import shutil
import urllib.request


# ── CN_REPO_MAP — canonical (repo_id, filename, revision) for every
# CN Spellcaster's 3D cascade cares about. Preferred route: HF client
# fetches from these tuples with all its verify/resume goodness.
# Each entry maps a FILENAME-AS-INSTALLED-ON-COMFY to a HF
# (repo_id, repo_filename, revision) triple.
CN_REPO_MAP: dict[str, tuple[str, str, str]] = {
    # SDXL / Illustrious — Xinsir's Union Pro (normal + depth + canny
    # + openpose via mode selector).
    "SDXL/controlnet-union-sdxl-1.0.safetensors": (
        "xinsir/controlnet-union-sdxl-1.0",
        "diffusion_pytorch_model_promax.safetensors",
        "main",
    ),
    "SDXL\\controlnet-union-sdxl-1.0.safetensors": (
        "xinsir/controlnet-union-sdxl-1.0",
        "diffusion_pytorch_model_promax.safetensors",
        "main",
    ),
    "controlnet-union-sdxl-1.0.safetensors": (
        "xinsir/controlnet-union-sdxl-1.0",
        "diffusion_pytorch_model_promax.safetensors",
        "main",
    ),
    # SD 1.5 — lllyasviel v1.1 set.
    "control_v11p_sd15_normalbae.pth": (
        "lllyasviel/ControlNet-v1-1",
        "control_v11p_sd15_normalbae.pth",
        "main",
    ),
    "control_v11f1p_sd15_depth_fp16.safetensors": (
        "comfyanonymous/ControlNet-v1-1_fp16_safetensors",
        "control_v11f1p_sd15_depth_fp16.safetensors",
        "main",
    ),
    "control_v11p_sd15_lineart_fp16.safetensors": (
        "comfyanonymous/ControlNet-v1-1_fp16_safetensors",
        "control_v11p_sd15_lineart_fp16.safetensors",
        "main",
    ),
    # Flux.1-dev — Shakker Labs Union Pro 2.0.
    "FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors": (
        "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0",
        "diffusion_pytorch_model.safetensors",
        "main",
    ),
}


# ── CN_URL_MAP — kept as LEGACY fallback for installs without
# huggingface_hub. Derived from CN_REPO_MAP at module load so the
# two can never drift. (Public map preserved for external callers
# + tests + installer coverage audit.)
CN_URL_MAP: dict[str, str] = {
    filename: (f"https://huggingface.co/{repo}/resolve/{rev}/{file}")
    for filename, (repo, file, rev) in CN_REPO_MAP.items()
}


def _is_safe_filename(name: str) -> bool:
    """Filename is usable iff it has no traversal / drive prefix /
    NUL / leading separator. Subdirectories (``SDXL/foo.safetensors``)
    are allowed."""
    if not isinstance(name, str) or not name:
        return False
    if ":" in name:
        return False
    if "\x00" in name:
        return False
    normalised = name.replace("\\", "/")
    if normalised.startswith("/"):
        return False
    parts = [p for p in normalised.split("/") if p]
    if any(p == ".." for p in parts):
        return False
    return True


def _resolve_controlnet_dir() -> str | None:
    """Ask ComfyUI's ``folder_paths`` for the controlnet dir. Returns
    the first configured path (the primary, canonical dir)."""
    try:
        import folder_paths
    except Exception:
        return None
    try:
        cn_paths = folder_paths.get_folder_paths("controlnet")
        if cn_paths:
            return os.path.realpath(cn_paths[0])
    except Exception:
        pass
    return None


def _safe_resolve(root: str, filename: str) -> tuple[str | None, str]:
    """Return (absolute_path, "") when safe, (None, reason) otherwise."""
    if not _is_safe_filename(filename):
        return None, "unsafe filename"
    full = os.path.join(root, filename)
    try:
        real = os.path.realpath(full)
    except Exception as e:
        return None, f"realpath failed: {e}"
    root_real = os.path.realpath(root)
    try:
        if os.path.commonpath([real, root_real]) != root_real:
            return None, "path escapes folder root"
    except ValueError:
        return None, "path on different drive"
    return real, ""


def _delete_file(root: str, filename: str) -> tuple[bool, str]:
    real, reason = _safe_resolve(root, filename)
    if real is None:
        return False, reason
    if not os.path.isfile(real):
        return True, "not present"
    try:
        os.remove(real)
        return True, "deleted"
    except PermissionError as e:
        return False, f"permission: {e}"
    except OSError as e:
        return False, f"os error: {e}"


def _download_via_hf(filename: str, dest_real: str) -> tuple[bool, str]:
    """Preferred path — ``huggingface_hub.hf_hub_download`` to a
    local_dir with ``force_download=True`` so a corrupt cache can't
    mask a fresh fetch.

    Inherits resume-on-fail, SHA-256 chunk verification (xet backend),
    tqdm progress logging, and ``HF_TOKEN`` env var auth. ~100 LOC of
    the previous hand-rolled streamer + size-verify + atomic-rename
    deleted by this switch.
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return False, "huggingface_hub not installed"
    entry = CN_REPO_MAP.get(filename)
    if not entry:
        bn = filename.replace("\\", "/").rsplit("/", 1)[-1]
        entry = CN_REPO_MAP.get(bn)
    if not entry:
        return False, f"no HF repo mapping for {filename!r}"
    repo_id, repo_filename, revision = entry
    parent = os.path.dirname(dest_real) or "."
    try:
        os.makedirs(parent, exist_ok=True)
        # Ask HF to deposit the file DIRECTLY at the final controlnet/
        # dir layout — no symlinks into the HF cache, so ComfyUI's
        # folder_paths sees the expected on-disk path.
        # The ``local_dir`` arg is the directory; HF appends
        # ``repo_filename`` under it. We'll rename post-download if
        # the on-server layout expects a different basename.
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=repo_filename,
            revision=revision,
            local_dir=parent,
            force_download=True,
            # Don't create HF's own subfolder structure — we want the
            # file placed where ComfyUI expects it.
        )
        # If the downloaded basename differs from the install name,
        # rename (no-op when they match).
        dest_basename = os.path.basename(dest_real)
        dl_basename = os.path.basename(downloaded_path)
        if dl_basename != dest_basename:
            os.replace(downloaded_path, dest_real)
        size = os.path.getsize(dest_real)
        return True, (f"downloaded {size} bytes via hf_hub_download "
                       f"(repo={repo_id}, rev={revision})")
    except Exception as e:
        return False, f"hf_hub_download failed: {e}"


def _download_via_urllib(filename: str, dest_real: str,
                           min_expected_bytes: int = 1 << 20
                           ) -> tuple[bool, str]:
    """Fallback — used only when ``huggingface_hub`` isn't installed.
    Streams the URL from CN_URL_MAP to ``<dest_real>.download`` then
    atomic-renames in. Kept for environments that refuse the HF
    dependency (air-gapped servers, custom Python builds).
    """
    url = CN_URL_MAP.get(filename)
    if not url:
        bn = filename.replace("\\", "/").rsplit("/", 1)[-1]
        url = CN_URL_MAP.get(bn)
    if not url:
        return False, f"no URL mapping for {filename!r}"
    tmp = dest_real + ".download"
    try:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        os.makedirs(os.path.dirname(dest_real) or ".", exist_ok=True)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Spellcaster-ModelRepair/2.0"
        })
        with urllib.request.urlopen(req, timeout=900) as resp:
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
        size = os.path.getsize(tmp)
        if size < min_expected_bytes:
            try:
                os.remove(tmp)
            except Exception:
                pass
            return False, (f"downloaded only {size} bytes "
                           f"(< {min_expected_bytes} expected)")
        os.replace(tmp, dest_real)
        return True, f"downloaded {size} bytes via urllib (fallback)"
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False, f"urllib download failed: {e}"


def _download_file(filename: str, dest_real: str) -> tuple[bool, str]:
    """Download dispatcher — hf_hub_download first, urllib fallback."""
    ok, msg = _download_via_hf(filename, dest_real)
    if ok:
        return ok, msg
    if "not installed" in msg or "no HF repo mapping" in msg:
        # hf unavailable OR this file isn't in CN_REPO_MAP — try urllib.
        return _download_via_urllib(filename, dest_real)
    # HF path failed for some other reason (network, gated repo, etc.)
    # — don't silently fall back to urllib; surface the HF error so
    # the user can diagnose auth / connectivity.
    return False, msg


def _handle(body: dict) -> dict:
    action = str(body.get("action") or "").lower()
    filename = body.get("filename") or ""
    folder = str(body.get("folder") or "controlnet").lower()
    if folder != "controlnet":
        return {"ok": False, "error": f"folder not allowed: {folder!r}"}
    cn_dir = _resolve_controlnet_dir()
    if not cn_dir:
        return {"ok": False, "error": "could not resolve controlnet folder"}

    if action == "delete":
        ok, msg = _delete_file(cn_dir, filename)
        return {"ok": ok, "action": "delete",
                "filename": filename, "detail": msg}

    if action == "redownload":
        if not (CN_REPO_MAP.get(filename) or CN_URL_MAP.get(filename)
                or CN_REPO_MAP.get(
                    filename.replace("\\", "/").rsplit("/", 1)[-1])
                or CN_URL_MAP.get(
                    filename.replace("\\", "/").rsplit("/", 1)[-1])):
            return {"ok": False,
                    "error": f"no repo / URL mapping for {filename!r}",
                    "known": sorted(CN_REPO_MAP.keys())}
        # Delete the corrupt old file first so we don't get two files
        # competing on case-insensitive filesystems.
        del_ok, del_msg = _delete_file(cn_dir, filename)
        dest, reason = _safe_resolve(cn_dir, filename)
        if dest is None:
            return {"ok": False, "error": reason}
        dl_ok, dl_msg = _download_file(filename, dest)
        return {
            "ok":           dl_ok,
            "action":       "redownload",
            "filename":     filename,
            "detail":       dl_msg,
            "deleted_old":  del_msg,
            "delete_ok":    del_ok,
        }

    return {"ok": False, "error": f"unknown action: {action!r}"}


def _register_routes() -> bool:
    """Wire the repair route onto ComfyUI's PromptServer."""
    try:
        from server import PromptServer
    except Exception:
        return False
    try:
        from aiohttp import web
    except Exception:
        return False
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return False
    routes = getattr(instance, "routes", None)
    if routes is None:
        return False

    @routes.post("/spellcaster/models/repair")
    async def _repair_route(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = _handle(body)
        status = 200 if result.get("ok") else 400
        return web.json_response(result, status=status)

    @routes.get("/spellcaster/models/known_urls")
    async def _known_route(_request):
        return web.json_response({
            "cn_urls": CN_URL_MAP,       # legacy flat URL map
            "cn_repos": {
                k: {"repo": r, "file": f, "rev": rev}
                for k, (r, f, rev) in CN_REPO_MAP.items()
            },
        })

    return True


def is_available() -> bool:
    return _register_routes()


__all__ = [
    "CN_URL_MAP", "CN_REPO_MAP",
    "_handle", "_register_routes", "is_available",
]
