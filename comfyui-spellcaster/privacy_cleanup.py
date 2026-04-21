"""Spellcaster privacy cleanup — HTTP delete route on ComfyUI's server.

Context: the GIMP plugin's existing "privacy cleanup" path used
``POST /upload/image`` with a 1x1 transparent PNG to "overwrite"
temp files. That worked for inputs (the endpoint writes to the
``input/`` folder where the file originally lived) but it
completely failed for outputs — ``/upload/image`` ALWAYS writes
to ``input/``, so a tiny PNG ended up in ``input/<output_name>``
while the actual output file in ``output/`` persisted untouched.

This module exposes a single HTTP route on ComfyUI's own
PromptServer that does a real file delete:

    POST /spellcaster/privacy/delete
    body: {
        "filenames":   ["gimp_abc.png", ...],
        "folder_type": "input" | "output" | "temp" | "all",
        "prefixes":    ["gimp_", "guild_", "spellcaster_", "sc_test_"]
    }

Returns ``{"deleted": [{"name": ..., "folder": ...}, ...],
            "failed":  [{"name": ..., "error": ...}, ...]}``.

Safety guarantees
-----------------

* Path traversal refused — filenames with ``..`` / absolute paths /
  drive prefixes are rejected before any unlink is attempted.
* Only files whose name starts with a caller-supplied
  ``prefixes`` entry (defaults to the Spellcaster-owned set
  ``gimp_``, ``guild_``, ``spellcaster_``, ``sc_test_``) are
  eligible — a malicious caller can't wipe ``comfyui_config.json``
  or ``extra_model_paths.yaml``.
* Resolved paths are re-validated to live UNDER the folder they
  were claimed to live in after ``realpath`` — symlink / junction
  tricks can't escape.
* Uses ``folder_paths`` from the ComfyUI runtime for the canonical
  input / output / temp directory resolution.

Degrades gracefully: when ``folder_paths`` or ``PromptServer`` is
unavailable (module loaded outside ComfyUI), registration is a
no-op and the blob-bus / presence / etc. endpoints stay unaffected.
"""

from __future__ import annotations

import os
from typing import Iterable


SAFE_DEFAULT_PREFIXES = (
    "gimp_", "guild_", "spellcaster_", "sc_test_", "sc_cache_",
    # sc_nmauto_ is the normal-map auto-gen upload prefix — same
    # owner, deliberately exempt from per-workflow wipe (see
    # privacy.CACHE_PREFIXES) but fair game for explicit delete.
    "sc_nmauto_",
)


def _resolve_folder_dirs(folder_type: str) -> list[tuple[str, str]]:
    """Return a list of ``(folder_name, abs_path)`` for the requested
    folder type. Safely handles ComfyUI's multi-dir folder layout
    (user vs shared input dirs etc.) by asking ``folder_paths``.

    Unknown folder_type returns an empty list.
    """
    try:
        import folder_paths  # provided by ComfyUI at runtime
    except Exception:
        return []

    wanted: list[tuple[str, str]] = []
    if folder_type == "all":
        targets = ("input", "output", "temp")
    else:
        targets = (folder_type,)
    for t in targets:
        try:
            if t == "input":
                p = folder_paths.get_input_directory()
            elif t == "output":
                p = folder_paths.get_output_directory()
            elif t == "temp":
                p = folder_paths.get_temp_directory()
            else:
                continue
        except Exception:
            continue
        if not p:
            continue
        try:
            wanted.append((t, os.path.realpath(p)))
        except Exception:
            wanted.append((t, p))
    return wanted


def _is_safe_filename(name: str) -> bool:
    """True when ``name`` looks like a plain filename (no path
    separators, no traversal, no drive prefix)."""
    if not isinstance(name, str) or not name:
        return False
    if name.startswith(("/", "\\")):
        return False
    if ":" in name:               # Windows drive prefix `C:\...`
        return False
    if "\x00" in name:
        return False
    # No directory separators anywhere — we only delete files at
    # the TOP of the input/output/temp folder. A caller that wants
    # to remove ``subfolder/foo.png`` must list the subfolder name
    # as part of the filename AND it still has to pass the
    # post-resolve "under folder root" guard below. Reject traversal.
    if ".." in name.replace("\\", "/").split("/"):
        return False
    return True


def _delete_one(folder_root: str, filename: str,
                 prefixes: Iterable[str]) -> tuple[bool, str]:
    """Attempt to delete ``filename`` from ``folder_root``.

    Returns ``(ok, message)``. ``message`` is a short human-readable
    explanation on failure (or the word ``"deleted"`` on success).
    """
    if not _is_safe_filename(filename):
        return False, "unsafe filename"
    lname = filename.lower()
    if not any(lname.startswith(p) for p in prefixes):
        return False, "prefix not in allowed set"
    try:
        full = os.path.join(folder_root, filename)
        real = os.path.realpath(full)
        root_real = os.path.realpath(folder_root)
        # Harden against symlink escapes: the resolved file MUST sit
        # under the resolved folder root.
        if os.path.commonpath([real, root_real]) != root_real:
            return False, "path escapes folder root"
        if not os.path.isfile(real):
            # File already gone OR never existed — treat as "ok,
            # nothing to do" so repeated calls from the GIMP plug-in
            # stay idempotent.
            return True, "not present"
        os.remove(real)
        return True, "deleted"
    except FileNotFoundError:
        return True, "not present"
    except PermissionError as e:
        return False, f"permission: {e}"
    except OSError as e:
        return False, f"os error: {e}"


def _handle(body: dict) -> dict:
    """Core handler. Validates input, resolves folders, attempts
    deletes, returns a structured result."""
    names = body.get("filenames") if isinstance(body, dict) else None
    if not isinstance(names, list):
        return {"ok": False, "error": "filenames must be a list",
                "deleted": [], "failed": []}
    names = [n for n in names if isinstance(n, str)]

    folder_type = str(body.get("folder_type", "all") or "all").lower()
    if folder_type not in ("input", "output", "temp", "all"):
        return {"ok": False, "error": f"unknown folder_type: {folder_type!r}",
                "deleted": [], "failed": []}

    raw_prefixes = body.get("prefixes")
    if isinstance(raw_prefixes, list) and all(isinstance(p, str) for p in raw_prefixes):
        # Force prefixes to lowercase for stable matching + intersect
        # with the whitelisted safe set so a malicious caller can't
        # widen the scope to e.g. "" (match everything).
        caller_set = {p.lower() for p in raw_prefixes if p}
        prefixes = tuple(p for p in SAFE_DEFAULT_PREFIXES
                         if p in caller_set) or SAFE_DEFAULT_PREFIXES
    else:
        prefixes = SAFE_DEFAULT_PREFIXES

    folders = _resolve_folder_dirs(folder_type)
    if not folders:
        return {"ok": False, "error": f"no folders resolved for {folder_type!r}",
                "deleted": [], "failed": []}

    deleted: list[dict] = []
    failed: list[dict] = []
    for name in names:
        hit = False
        for folder_name, folder_root in folders:
            ok, msg = _delete_one(folder_root, name, prefixes)
            if ok and msg == "deleted":
                deleted.append({"name": name, "folder": folder_name})
                hit = True
                break
            elif ok and msg == "not present":
                # Keep scanning other folders — the same basename
                # can exist in input AND output.
                continue
            else:
                # Hard error on this folder — capture + keep trying
                # the next folder.
                failed.append({"name": name, "folder": folder_name,
                                "error": msg})
        if not hit and not any(f["name"] == name for f in failed):
            failed.append({"name": name, "error": "not found in any folder"})
    return {
        "ok": True,
        "deleted": deleted,
        "failed": failed,
        "folders_scanned": [f[0] for f in folders],
        "prefixes_matched": list(prefixes),
    }


def _register_routes() -> bool:
    """Wire the delete route onto ComfyUI's PromptServer. Returns True
    when the route is attached; False when we're not in a ComfyUI
    runtime (e.g. unit tests)."""
    try:
        from server import PromptServer        # ComfyUI's singleton
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

    @routes.post("/spellcaster/privacy/delete")
    async def _delete_route(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = _handle(body)
        status = 200 if result.get("ok") else 400
        return web.json_response(result, status=status)

    return True


def is_available() -> bool:
    """Mirrors presence / blob_bus API shape — returns True iff the
    route successfully registered against this ComfyUI process."""
    return _register_routes()


__all__ = [
    "SAFE_DEFAULT_PREFIXES",
    "_handle", "_register_routes", "is_available",
]
