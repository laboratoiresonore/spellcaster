"""Privacy cleanup — single source of truth for wiping temp files from ComfyUI.

Used by BOTH the GIMP plugin and the Wizard Guild server. Overwrites
uploaded inputs and generated outputs with a 1x1 transparent PNG to
reclaim space and prevent data persistence on the server.

USAGE:
    from spellcaster_core.privacy import cleanup_server_files

    # After downloading results locally:
    cleanup_server_files(comfy_url, workflow, results)

Cache-protected files
---------------------

``CACHE_PREFIXES`` is a set of filename prefixes that the GIMP plugin
uses for its content-hash upload cache (see
``_export_and_upload_cached`` in ``_spellcaster_main.py``). A user who
sends the EXACT same image / selection to ComfyUI twice would have to
re-export + re-upload each time \u2014 500 ms to 30 s depending on
canvas size and fallback path. The cache sidesteps that by keeping
the uploaded file live on the server between workflows and reusing
the filename when the content hash matches.

Privacy-wise, cache files are opt-in (``image_upload_cache`` in
``config.json``) and survive only the per-session TTL. They ARE wiped
by explicit ``purge_cache(server)`` calls, and by the "Clear image
cache" menu entry in GIMP. They are NOT wiped by the after-every-
workflow ``cleanup_server_files`` path \u2014 that would defeat the
cache's purpose \u2014 but they ARE visible to ``/object_info`` so a
determined snooper can still see the files exist.
"""

import uuid
import urllib.request


# 1x1 transparent pixel PNG (89 bytes) — used to overwrite temp files
TINY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
    b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
    b'\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)

# File prefixes that Spellcaster owns (safe to wipe)
OWNED_PREFIXES = ("gimp_", "guild_", "spellcaster_", "sc_test_")

# File prefixes that belong to the GIMP upload-cache \u2014 EXEMPT from
# the after-every-workflow wipe so repeat submits of the same image /
# selection can reuse the uploaded bytes. Explicit ``purge_cache()``
# and "Clear image cache" still target these, so users who want strict
# privacy can blow them away on demand.
CACHE_PREFIXES = ("sc_cache_",)


def _overwrite_with_tiny(server, filename):
    """Overwrite a single file on ComfyUI's input folder with a 1x1 pixel."""
    try:
        url = f"{server.rstrip('/')}/upload/image"
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + TINY_PNG + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def _is_cache_protected(fname: str) -> bool:
    """Cache-protected files survive the after-every-workflow wipe.

    Used by both strategies in ``cleanup_inputs`` so the same exclusion
    logic applies everywhere.
    """
    if not fname:
        return False
    fl = fname.lower()
    return any(fl.startswith(p) for p in CACHE_PREFIXES)


def cleanup_inputs(server, workflow=None):
    """Overwrite all Spellcaster temp input files on the server.

    Two strategies:
    1. If workflow is provided: scan LoadImage/VHS_LoadVideo nodes for
       filenames matching our prefixes, wipe those specifically.
    2. Always: scan the server's full input file list for our prefixes.

    Files whose name starts with any ``CACHE_PREFIXES`` entry are NOT
    wiped \u2014 they belong to the GIMP upload-cache and must survive
    between workflows so repeat submits can reuse them. Use
    ``purge_cache(server)`` to blow those away on demand.
    """
    wiped = set()

    # Strategy 1: workflow-based (knows exactly which files were uploaded)
    if workflow:
        for nid, node in workflow.items():
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type", "")
            if ct not in ("LoadImage", "VHS_LoadVideo"):
                continue
            fname = (node.get("inputs", {}).get("image", "") or
                     node.get("inputs", {}).get("video", ""))
            if not fname or not isinstance(fname, str):
                continue
            if _is_cache_protected(fname):
                continue
            fl = fname.lower()
            # Check if it's ours (prefix match or cached asset hash)
            import re
            is_hash = bool(re.match(r'^[a-f0-9]{16}\.', fl))
            if is_hash or any(fl.startswith(p) for p in OWNED_PREFIXES):
                _overwrite_with_tiny(server, fname)
                wiped.add(fname)

    # Strategy 2: full server scan
    try:
        import json
        url = f"{server.rstrip('/')}/object_info/LoadImage"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read())
        input_files = info["LoadImage"]["input"]["required"]["image"][0]
        for fname in input_files:
            if fname in wiped:
                continue
            if _is_cache_protected(fname):
                continue
            fl = fname.lower()
            if any(fl.startswith(p) for p in OWNED_PREFIXES):
                _overwrite_with_tiny(server, fname)
    except Exception:
        pass


def purge_cache(server, *, prefixes=CACHE_PREFIXES, keep=None,
                 older_than_seconds=None):
    """Manually wipe every cache-protected file on the server.

    The after-every-workflow wipe deliberately SKIPS files matching
    ``CACHE_PREFIXES`` so the GIMP upload-cache can reuse uploaded
    bytes between submits. This function lets the user (or a TTL-
    driven housekeeper) burn that cache down when privacy posture
    matters more than reupload cost. Returns ``{"wiped": [...]}`` so
    callers can report what was removed.

    Args:
        server: ComfyUI URL.
        prefixes: iterable of filename prefixes to consider. Defaults
            to ``CACHE_PREFIXES`` so callers can't accidentally wipe
            OWNED_PREFIXES files through this function \u2014 use the
            standard ``cleanup_inputs`` for those.
        keep: optional iterable of filenames to preserve (e.g., a
            currently-in-flight submit). Matched case-insensitively.
        older_than_seconds: reserved for future mtime-based filtering
            once ComfyUI exposes file timestamps via an API. Today
            this argument is accepted for forward-compatibility but
            has no effect \u2014 the wipe still happens for every
            matching file.
    """
    keep_set = {str(k).lower() for k in (keep or ())}
    wiped: list[str] = []
    try:
        import json
        url = f"{server.rstrip('/')}/object_info/LoadImage"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read())
        input_files = info["LoadImage"]["input"]["required"]["image"][0]
    except Exception:
        return {"wiped": wiped, "error": "object_info fetch failed"}
    for fname in input_files:
        if not isinstance(fname, str):
            continue
        fl = fname.lower()
        if fl in keep_set:
            continue
        if not any(fl.startswith(p) for p in prefixes):
            continue
        _overwrite_with_tiny(server, fname)
        wiped.append(fname)
    return {"wiped": wiped}


def cleanup_outputs(server, results):
    """Overwrite generated output files on the server with 1x1 pixels.

    Args:
        results: list of (filename, subfolder, folder_type) tuples
    """
    for fn, sf, ft in results:
        _overwrite_with_tiny(server, fn)


def cleanup_server_files(server, workflow=None, results=None):
    """Full privacy cleanup: wipe both inputs and outputs.

    This is the single function all consumers should call. Cache-
    protected inputs (prefixes in ``CACHE_PREFIXES``) are SKIPPED so
    the GIMP upload-cache survives. To wipe those too, call
    ``purge_cache(server)`` explicitly.
    """
    cleanup_inputs(server, workflow)
    if results:
        cleanup_outputs(server, results)


__all__ = [
    "TINY_PNG", "OWNED_PREFIXES", "CACHE_PREFIXES",
    "cleanup_inputs", "cleanup_outputs", "cleanup_server_files",
    "purge_cache",
]
