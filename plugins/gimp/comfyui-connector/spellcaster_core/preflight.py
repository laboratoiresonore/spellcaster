"""Preflight — node availability check + automatic fallback system.

Before submitting a workflow to ComfyUI, preflight scans every node in the
workflow, checks if ComfyUI has that node type installed, and applies
automatic substitutions for known-broken or missing nodes.

Usage:
    from spellcaster_core.preflight import preflight_workflow

    workflow = build_txt2img(preset, prompt, negative, seed)
    ok, workflow, report = preflight_workflow(workflow, comfy_url)
    if not ok:
        print(f"Missing nodes: {report['missing']}")
    # workflow has fallbacks applied — safe to submit

The fallback registry maps broken/missing node types to alternatives:
    RTXVideoSuperResolution → UpscaleModelLoader + ImageUpscaleWithModel
    ReActorFaceSwapOpt → ReActorFaceSwap (older API)

Fallbacks preserve the same input/output wiring so downstream nodes
still work without changes.
"""

import json
import urllib.request
import urllib.error

# ═══════════════════════════════════════════════════════════════════════
#  Node availability cache (populated once per ComfyUI URL)
# ═══════════════════════════════════════════════════════════════════════

_available_nodes = {}   # {comfy_url: set(class_types)}
_node_info_cache = {}   # {comfy_url: {class_type: info_dict}}


def get_available_nodes(comfy_url, force_refresh=False):
    """Fetch all available node class_types from ComfyUI.

    Caches the result per URL. Returns a set of class_type strings.
    """
    if not force_refresh and comfy_url in _available_nodes:
        return _available_nodes[comfy_url]
    try:
        url = f"{comfy_url.rstrip('/')}/object_info"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        nodes = set(data.keys())
        _available_nodes[comfy_url] = nodes
        _node_info_cache[comfy_url] = data
        return nodes
    except Exception as e:
        print(f"[Preflight] WARNING: Could not fetch node list: {e}")
        return set()


def invalidate_cache(comfy_url=None):
    """Clear the node availability cache (call after installing new nodes)."""
    if comfy_url:
        _available_nodes.pop(comfy_url, None)
        _node_info_cache.pop(comfy_url, None)
    else:
        _available_nodes.clear()
        _node_info_cache.clear()


# ═══════════════════════════════════════════════════════════════════════
#  Fallback Registry
# ═══════════════════════════════════════════════════════════════════════
#
#  Maps a node class_type to a fallback function.
#  The function receives (node_id, node_dict, workflow) and returns
#  a dict of replacement nodes {nid: node_dict, ...} or None to skip.
#
#  IMPORTANT: Fallback functions must preserve the original node's output
#  slot wiring. If node "75" was RTXVideoSuperResolution with output [75, 0]
#  referenced by downstream nodes, the replacement must also produce
#  output at [some_id, 0] and all references to [75, 0] must be updated.

def _fallback_rtx_to_model_upscale(nid, node, workflow):
    """Replace RTXVideoSuperResolution with UpscaleModelLoader + ImageUpscaleWithModel.

    RTXVideoSuperResolution uses COMFY_DYNAMICCOMBO_V3 which is broken in
    ComfyUI's API prompt execution. This substitutes native nodes that always work.
    """
    inputs = node.get("inputs", {})
    images_ref = inputs.get("images")
    resize_type = inputs.get("resize_type", {})

    # Extract scale factor from V3 format or flat
    if isinstance(resize_type, dict):
        scale = resize_type.get("scale", 2.0)
    else:
        scale = inputs.get("scale", 2.0)

    # Build replacement nodes
    loader_nid = f"{nid}_ml"
    down_nid = f"{nid}_ds"

    replacements = {
        loader_nid: {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": "4x-UltraSharp.pth"},
        },
        nid: {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {
                "upscale_model": [loader_nid, 0],
                "image": images_ref,
            },
        },
    }

    # If scale < 4x, add a downscale node
    if scale < 3.5:
        ratio = scale / 4.0
        replacements[down_nid] = {
            "class_type": "ImageScaleBy",
            "inputs": {
                "image": [nid, 0],
                "upscale_method": "lanczos",
                "scale_by": ratio,
            },
        }
        # Rewire all downstream references from [nid, 0] to [down_nid, 0]
        _rewire_refs(workflow, nid, 0, down_nid, 0)

    return replacements


def _fallback_reactor_opt_to_basic(nid, node, workflow):
    """Replace ReActorFaceSwapOpt with ReActorFaceSwap (older, more compatible API)."""
    inputs = node.get("inputs", {})
    # ReActorFaceSwap has a simpler API — try direct substitution
    return {
        nid: {
            "class_type": "ReActorFaceSwap",
            "inputs": inputs,  # Same inputs, different class
        },
    }


def _fallback_skip(nid, node, workflow):
    """Remove this node entirely and rewire past it.

    Used for optional post-processing nodes (upscale, interpolation) that
    can be safely skipped without breaking the pipeline.
    """
    # Find what this node's input was and rewire outputs to bypass it
    inputs = node.get("inputs", {})
    # Find the primary image/video input
    for key in ("images", "image", "frames"):
        ref = inputs.get(key)
        if isinstance(ref, list) and len(ref) == 2:
            # Rewire all downstream [nid, 0] references to the input source
            _rewire_refs(workflow, nid, 0, ref[0], ref[1])
            return {}  # Empty dict = remove this node
    return None  # Can't skip safely


# The registry: class_type → (fallback_fn, description, install_hint)
FALLBACK_REGISTRY = {
    "RIFE_VFI": (
        _fallback_skip,
        "RIFE frame interpolation -> skipped (output at base FPS)",
        "Install: ComfyUI-Frame-Interpolation for smooth video",
    ),
    "ImageRembg": (
        None,  # No fallback — this is essential
        "Background removal node",
        "Install: ComfyUI-rembg (required for background removal)",
    ),
    "LaMaInpainting": (
        None,
        "LaMa object removal node",
        "Install: comfyui-lama (required for object removal)",
    ),
}

# Nodes that are ALWAYS substituted even if available on the server.
# These nodes pass ComfyUI validation but crash at execution time due to
# API changes (V3 dynamic combos, etc.). The fallback is more reliable.
ALWAYS_SUBSTITUTE = {
    "RTXVideoSuperResolution": (
        _fallback_rtx_to_model_upscale,
        "RTX Video Super Resolution -> AI model upscale (4x-UltraSharp)",
    ),
}


def _rewire_refs(workflow, old_nid, old_slot, new_nid, new_slot):
    """Rewire all references from [old_nid, old_slot] to [new_nid, new_slot]."""
    old_nid_str = str(old_nid)
    new_nid_str = str(new_nid)
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        for key, val in node.get("inputs", {}).items():
            if isinstance(val, list) and len(val) == 2:
                if str(val[0]) == old_nid_str and val[1] == old_slot:
                    node["inputs"][key] = [new_nid_str, new_slot]


# ═══════════════════════════════════════════════════════════════════════
#  Main Preflight Function
# ═══════════════════════════════════════════════════════════════════════

def preflight_workflow(workflow, comfy_url):
    """Check a workflow for missing nodes and apply automatic fallbacks.

    Args:
        workflow: ComfyUI workflow dict {node_id: {class_type, inputs}}
        comfy_url: ComfyUI server URL (for /object_info query)

    Returns:
        (ok, patched_workflow, report) where:
          ok: True if all nodes are available (or have fallbacks)
          patched_workflow: Workflow with fallbacks applied
          report: {
            "available": [class_types that exist],
            "missing": [class_types not found, no fallback],
            "substituted": [(original, replacement_desc)],
            "skipped": [(class_type, reason)],
          }
    """
    available = get_available_nodes(comfy_url)
    if not available:
        # Can't verify — pass through and hope for the best
        return True, workflow, {
            "available": [], "missing": [], "substituted": [], "skipped": [],
            "warning": "Could not reach ComfyUI to verify nodes",
        }

    report = {"available": [], "missing": [], "substituted": [], "skipped": []}
    patched = dict(workflow)  # Shallow copy — we'll replace individual nodes

    # Collect all class_types used in the workflow
    used_types = {}
    for nid, node in workflow.items():
        if isinstance(node, dict) and "class_type" in node:
            ct = node["class_type"]
            used_types.setdefault(ct, []).append(nid)

    # Phase 1: Always-substitute (known-broken nodes, even if available)
    for ct, nids in list(used_types.items()):
        if ct in ALWAYS_SUBSTITUTE:
            fallback_fn, desc = ALWAYS_SUBSTITUTE[ct]
            for nid in nids:
                if nid in patched:
                    replacements = fallback_fn(nid, patched[nid], patched)
                    if replacements is not None:
                        if nid in patched and nid not in replacements:
                            del patched[nid]
                        patched.update(replacements)
                        report["substituted"].append((ct, desc))
            print(f"[Preflight] {ct} -> {desc}")
            del used_types[ct]

    # Phase 2: Check remaining nodes against server availability
    for ct, nids in used_types.items():
        if ct in available:
            report["available"].append(ct)
            continue

        # Node missing — check fallback registry
        fallback_entry = FALLBACK_REGISTRY.get(ct)
        if fallback_entry:
            fallback_fn, desc, hint = fallback_entry
            if fallback_fn:
                for nid in nids:
                    if nid not in patched:
                        continue
                    replacements = fallback_fn(nid, patched[nid], patched)
                    if replacements is not None:
                        if nid in patched and nid not in replacements:
                            del patched[nid]
                        patched.update(replacements)
                        report["substituted"].append((ct, desc))
                    else:
                        report["missing"].append(ct)
                print(f"[Preflight] {ct} -> {desc}")
            else:
                report["missing"].append(ct)
                print(f"[Preflight] MISSING: {ct} -- {hint}")
        else:
            report["missing"].append(ct)
            print(f"[Preflight] MISSING: {ct} (no fallback available)")

    ok = len(report["missing"]) == 0
    return ok, patched, report


def check_workflow(workflow, comfy_url):
    """Quick check — returns list of missing node types (no fallback applied)."""
    available = get_available_nodes(comfy_url)
    if not available:
        return []
    missing = []
    for nid, node in workflow.items():
        if isinstance(node, dict):
            ct = node.get("class_type", "")
            if ct and ct not in available and ct not in missing:
                missing.append(ct)
    return missing
