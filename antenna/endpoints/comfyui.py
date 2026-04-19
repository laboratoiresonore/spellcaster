"""ComfyUI service endpoints for the antenna — STUBS (Phase 2).

This module exists so `antenna/agent.py` can import it unconditionally
on startup (was silently swallowing the ImportError and leaving users
with a confusing `comfyui service declared but endpoints not yet built`
warning on every launch).

The real implementations come in antenna roadmap items 7-8:

- `install_node`  — git-clone a manifest-listed custom-node repo into
                    the remote ComfyUI's custom_nodes/ dir; allowlist
                    against installer/manifest.json; audit-log.
- `install_model` — download a manifest-listed model file (with
                    civitai/hf-token support) into the remote
                    ComfyUI's models/<kind>/ dir.

Until those ship, both endpoints return 501 with a clear machine-
readable error so clients can display "not yet available, use the
installer for now" instead of erroring.

The contract matches the rest of antenna/endpoints/: each handler
accepts a `request_ctx` dict and returns `(status_code, response_body)`.
"""
from __future__ import annotations

from typing import Any


_NOT_YET_BODY = {
    "error": "not_yet_implemented",
    "phase": 2,
    "hint": "Use the Spellcaster installer (installer/install.py or "
            "spellcaster-installer.exe) to add nodes/models to the remote "
            "ComfyUI for now. Antenna-driven install lands in a later phase.",
}


def install_node(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /install-node — STUB. Accepts the shape it WILL accept later
    so client code written against this endpoint can pin the body schema
    now without waiting for the real implementation.

    Future request body:
      {
        "node_key": "ComfyUI-Spellcaster",   // manifest key
        "ref": "main"                          // optional branch/tag
      }

    Future success response:
      {
        "node_key": "...",
        "installed_at": "<path>",
        "sha": "<commit>",
        "took_seconds": 4.7
      }
    """
    return 501, dict(_NOT_YET_BODY, endpoint="install-node")


def install_model(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /install-model — STUB. See install_node.

    Future request body:
      {
        "model_key": "SDXL/juggernaut_xl_v9.safetensors",  // manifest path
        "url_override": null,          // optional — manifest is authoritative
        "hf_token": null,              // optional — gated HF repos
        "civitai_key": null            // optional — private CivitAI models
      }

    Future success response:
      {
        "model_key": "...",
        "saved_to": "<path>",
        "bytes": 6843821568,
        "sha256": "<hex>",
        "took_seconds": 127.3
      }
    """
    return 501, dict(_NOT_YET_BODY, endpoint="install-model")
