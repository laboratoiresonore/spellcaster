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
        "folder":   "controlnet",         # only "controlnet" allowed
        "filename": "SDXL/controlnet-union-sdxl-1.0.safetensors"
    }

For ``redownload``, the URL is looked up in ``CN_URL_MAP`` below —
Spellcaster curates the set, callers can't drive arbitrary downloads.

Safety
------

* folder is whitelisted to ``controlnet`` only.
* filename must pass path-traversal + drive-prefix checks.
* Resolved realpath must remain under the ``controlnet`` folder root
  (symlink / junction escape refused).
* Redownload streams to ``<dest>.download`` and atomically renames in
  — a failed download leaves the OLD file's deletion committed (the
  corrupt file is gone) but no garbage in place; the next repair
  run can retry cleanly.

Degrades gracefully: when ``folder_paths`` or ``PromptServer`` isn't
available (module loaded outside the ComfyUI runtime), registration
is a no-op.
"""

from __future__ import annotations

import os
import urllib.request


# Curated Hugging Face URLs for the CN files Spellcaster's 3D tools
# can fall back to. Each entry is a ~0.7-2.5 GB download so we keep
# the list tight (callers can't drive arbitrary URL fetches).
CN_URL_MAP: dict[str, str] = {
    # SDXL / Illustrious — Xinsir's Union Pro (supports normal map
    # + depth + canny + openpose via mode selector).
    "SDXL/controlnet-union-sdxl-1.0.safetensors": (
        "https://huggingface.co/xinsir/controlnet-union-sdxl-1.0/"
        "resolve/main/diffusion_pytorch_model_promax.safetensors"
    ),
    "SDXL\\controlnet-union-sdxl-1.0.safetensors": (
        "https://huggingface.co/xinsir/controlnet-union-sdxl-1.0/"
        "resolve/main/diffusion_pytorch_model_promax.safetensors"
    ),
    "controlnet-union-sdxl-1.0.safetensors": (
        "https://huggingface.co/xinsir/controlnet-union-sdxl-1.0/"
        "resolve/main/diffusion_pytorch_model_promax.safetensors"
    ),
    # SD 1.5 — the canonical lllyasviel v1.1 set.
    "control_v11p_sd15_normalbae.pth": (
        "https://huggingface.co/lllyasviel/ControlNet-v1-1/"
        "resolve/main/control_v11p_sd15_normalbae.pth"
    ),
    "control_v11f1p_sd15_depth_fp16.safetensors": (
        "https://huggingface.co/comfyanonymous/"
        "ControlNet-v1-1_fp16_safetensors/"
        "resolve/main/control_v11f1p_sd15_depth_fp16.safetensors"
    ),
    "control_v11p_sd15_lineart_fp16.safetensors": (
        "https://huggingface.co/comfyanonymous/"
        "ControlNet-v1-1_fp16_safetensors/"
        "resolve/main/control_v11p_sd15_lineart_fp16.safetensors"
    ),
    # Flux.1-dev — Shakker Labs Union Pro 2.0.
    "FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors": (
        "https://huggingface.co/Shakker-Labs/"
        "FLUX.1-dev-ControlNet-Union-Pro-2.0/"
        "resolve/main/diffusion_pytorch_model.safetensors"
    ),
}


def _is_safe_filename(name: str) -> bool:
    """Filename is usable iff it has no traversal / drive prefix /
    NUL / leading separator. Subdirectories (``SDXL/foo.safetensors``)
    are allowed — they're unavoidable for ComfyUI's nested layout."""
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
    the first configured path (the primary, canonical dir). None when
    ``folder_paths`` isn't available — caller aborts."""
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
        # Different drive letters — never legal here.
        return None, "path on different drive"
    return real, ""


def _delete_file(root: str, filename: str) -> tuple[bool, str]:
    real, reason = _safe_resolve(root, filename)
    if real is None:
        return False, reason
    if not os.path.isfile(real):
        # Treat "already gone" as success so retries are idempotent.
        return True, "not present"
    try:
        os.remove(real)
        return True, "deleted"
    except PermissionError as e:
        return False, f"permission: {e}"
    except OSError as e:
        return False, f"os error: {e}"


def _download_file(url: str, dest_real: str,
                    min_expected_bytes: int = 1 << 20) -> tuple[bool, str]:
    """Stream ``url`` to ``<dest_real>.download`` then atomically
    rename to ``dest_real``. Chunked so a 2.5 GB file doesn't OOM.
    Refuses to land a file that's smaller than ``min_expected_bytes``
    (partial downloads from the REPAIR path are exactly what we're
    trying to avoid re-introducing).
    """
    tmp = dest_real + ".download"
    try:
        # Clean up leftovers from a previous aborted run.
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        # Ensure the parent directory exists (for nested paths like
        # ``SDXL/controlnet-union-sdxl-1.0.safetensors``).
        os.makedirs(os.path.dirname(dest_real) or ".", exist_ok=True)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Spellcaster-ModelRepair/1.0"
        })
        with urllib.request.urlopen(req, timeout=900) as resp:
            # Stream 1 MB chunks so we don't OOM on a 2.5 GB download.
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
                           f"(< {min_expected_bytes} expected) — aborted")
        # Atomic rename into place.
        os.replace(tmp, dest_real)
        return True, f"downloaded {size} bytes"
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False, f"download failed: {e}"


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
        url = CN_URL_MAP.get(filename)
        if not url:
            bn = filename.replace("\\", "/").rsplit("/", 1)[-1]
            url = CN_URL_MAP.get(bn)
        if not url:
            return {"ok": False,
                    "error": f"no known HF URL for {filename!r}",
                    "known": sorted(CN_URL_MAP.keys())}
        # Delete the corrupt old file first so we don't ever have two
        # files competing on case-insensitive FS if the URL target
        # uses a slightly different path.
        del_ok, del_msg = _delete_file(cn_dir, filename)
        dest, reason = _safe_resolve(cn_dir, filename)
        if dest is None:
            return {"ok": False, "error": reason}
        dl_ok, dl_msg = _download_file(url, dest)
        return {
            "ok":           dl_ok,
            "action":       "redownload",
            "filename":     filename,
            "url":          url,
            "detail":       dl_msg,
            "deleted_old":  del_msg,
            "delete_ok":    del_ok,
        }

    return {"ok": False, "error": f"unknown action: {action!r}"}


def _register_routes() -> bool:
    """Wire the repair route onto ComfyUI's PromptServer. Returns
    True when the route is attached; False when we're not in a
    ComfyUI runtime (e.g. unit tests)."""
    try:
        from server import PromptServer
    except Exception:  # pragma: no cover — not in ComfyUI runtime
        return False
    try:
        from aiohttp import web
    except Exception:  # pragma: no cover
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
        return web.json_response({"cn_urls": CN_URL_MAP})

    return True


def is_available() -> bool:
    return _register_routes()


__all__ = [
    "CN_URL_MAP",
    "_handle", "_register_routes", "is_available",
]
