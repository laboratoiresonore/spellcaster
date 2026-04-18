"""Privacy cleanup — single source of truth for wiping temp files from ComfyUI.

Used by BOTH the GIMP plugin and the Wizard Guild server. Overwrites
uploaded inputs and generated outputs with a 1x1 transparent PNG to
reclaim space and prevent data persistence on the server.

USAGE:
    from spellcaster_core.privacy import cleanup_server_files

    # After downloading results locally:
    cleanup_server_files(comfy_url, workflow, results)
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


def cleanup_inputs(server, workflow=None):
    """Overwrite all Spellcaster temp input files on the server.

    Two strategies:
    1. If workflow is provided: scan LoadImage/VHS_LoadVideo nodes for
       filenames matching our prefixes, wipe those specifically.
    2. Always: scan the server's full input file list for our prefixes.
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
            fl = fname.lower()
            if any(fl.startswith(p) for p in OWNED_PREFIXES):
                _overwrite_with_tiny(server, fname)
    except Exception:
        pass


def cleanup_outputs(server, results):
    """Overwrite generated output files on the server with 1x1 pixels.

    Args:
        results: list of (filename, subfolder, folder_type) tuples
    """
    for fn, sf, ft in results:
        _overwrite_with_tiny(server, fn)


def cleanup_server_files(server, workflow=None, results=None):
    """Full privacy cleanup: wipe both inputs and outputs.

    This is the single function all consumers should call.
    """
    cleanup_inputs(server, workflow)
    if results:
        cleanup_outputs(server, results)
