"""Preflight — node availability check + automatic fallback system.

Before submitting a workflow to ComfyUI, preflight scans every node in the
workflow, checks if ComfyUI has that node type installed, and applies
automatic substitutions for known-broken or missing nodes.

Usage:
    from .preflight import preflight_workflow

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
    inputs = node.get("inputs", {})
    for key in ("images", "image", "frames"):
        ref = inputs.get(key)
        if isinstance(ref, list) and len(ref) == 2:
            _rewire_refs(workflow, nid, 0, ref[0], ref[1])
            return {}
    return None


def _fallback_passthrough_model(nid, node, workflow):
    """Bypass an optional model-patching node (enhancer / TeaCache / PAG / etc.)
    when the custom node pack is not installed on the target ComfyUI server.
    Rewires downstream references from [nid, 0] to node['inputs']['model'].
    """
    inputs = node.get("inputs", {})
    ref = inputs.get("model")
    if isinstance(ref, list) and len(ref) == 2:
        _rewire_refs(workflow, nid, 0, ref[0], ref[1])
        return {}
    return None


def _fallback_passthrough_conditioning(nid, node, workflow):
    """Bypass an optional conditioning-patching node when not installed.
    Rewires downstream references from [nid, 0] to node['inputs']['conditioning'].
    """
    inputs = node.get("inputs", {})
    ref = inputs.get("conditioning")
    if isinstance(ref, list) and len(ref) == 2:
        _rewire_refs(workflow, nid, 0, ref[0], ref[1])
        return {}
    return None


# Optional pass-through nodes that wrap MODEL or CONDITIONING and can be
# safely bypassed when a server (such as Spark2) does not have the pack installed.
_OPTIONAL_MODEL_PASSTHROUGH_NODES = (
    "Flux2KleinRefLatentController",
    "Flux2KleinTextRefBalance",
    "Flux2KleinColorAnchor",
    "Flux2KleinRefLatentWeight",
    "IdentityGuidance",
    "IdentityFeatureTransfer",
    "IdentityFeatureTransferAdvanced",
    "ApplyTeaCachePatch",
    "ApplyFirstBlockCachePatch",
    "TeaCache",
    "PathchSageAttentionKJ",
    "TorchCompileModel",
    "CFGZeroStar",
    "PerturbedAttentionGuidance",
    "RescaleCFG",
    "FreeU_V2",
    "SkipLayerGuidanceDiT",
)

_OPTIONAL_COND_PASSTHROUGH_NODES = (
    "Flux2KleinEnhancer",
    "Flux2KleinTextEnhancer",
    "Flux2KleinMaskRefController",
)

# The registry: class_type → (fallback_fn, description, install_hint)
FALLBACK_REGISTRY = {
    "RIFE_VFI": (
        _fallback_skip,
        "RIFE frame interpolation -> skipped (output at base FPS)",
        "Install: ComfyUI-Frame-Interpolation for smooth video",
    ),
    "RIFE VFI": (
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
    "ReActorFaceSwapOpt": (
        _fallback_reactor_opt_to_basic,
        "ReActorFaceSwapOpt -> ReActorFaceSwap",
        "Install: comfyui-reactor-node",
    ),
}

for _opt_ct in _OPTIONAL_MODEL_PASSTHROUGH_NODES:
    FALLBACK_REGISTRY[_opt_ct] = (
        _fallback_passthrough_model,
        f"{_opt_ct} -> bypassed (optional model enhancer/booster not on server)",
        "Optional model enhancer node",
    )

for _opt_ct in _OPTIONAL_COND_PASSTHROUGH_NODES:
    FALLBACK_REGISTRY[_opt_ct] = (
        _fallback_passthrough_conditioning,
        f"{_opt_ct} -> bypassed (optional conditioning enhancer not on server)",
        "Optional conditioning enhancer node",
    )

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
#  Cross-machine / Spark2 Model Filename Healing
# ═══════════════════════════════════════════════════════════════════════

_MODEL_ALIAS_CANDIDATES = {
    "unet_name": [
        # (match_fn_on_lower_requested_name, ordered_candidate_substrings)
        (lambda s: "flux3" in s and "sd" in s, [
            "nvfp4/flux3_image_klein_sd_nvfp4.safetensors",
            "flux3_image_klein_sd_int8_convrot.safetensors",
            "flux3_image_klein_sd_bf16.safetensors",
        ]),
        (lambda s: ("flux3" in s or "flux-3" in s or "flux_3" in s) and ("sd" in s or "distill" in s), [
            "nvfp4/flux3_image_klein_sd_nvfp4.safetensors",
            "flux3-image-klein-int8-convrot.safetensors",
            "nvfp4/flux3_image_klein_base_nvfp4.safetensors",
        ]),
        (lambda s: "flux3" in s or "flux-3" in s or "flux_3" in s, [
            "nvfp4/flux3_image_klein_base_nvfp4.safetensors",
            "flux3-image-klein-int8-convrot.safetensors",
            "flux3_image_klein_base_bf16.safetensors",
            "nvfp4/flux3_image_klein_sd_nvfp4.safetensors",
        ]),
        (lambda s: "klein" in s and "9b" in s, [
            "nvfp4/flux-2-klein-9b-nvfp4.safetensors",
            "flux2-klein-9b-fp8/flux-2-klein-9b-fp8.safetensors",
            "flux-2-klein-9b.safetensors",
        ]),
        (lambda s: "klein" in s and "base" in s and "4b" in s, [
            "nvfp4/flux-2-klein-base-4b-nvfp4.safetensors",
            "nvfp4/flux-2-klein-4b-nvfp4.safetensors",
        ]),
        (lambda s: "klein" in s and "4b" in s, [
            "nvfp4/flux-2-klein-4b-nvfp4.safetensors",
            "nvfp4/flux-2-klein-base-4b-nvfp4.safetensors",
        ]),
        (lambda s: "flux2-dev" in s or "flux2_dev" in s or "flux-2-dev" in s, [
            "nvfp4/flux2-dev-nvfp4-mixed.safetensors",
            "flux2-dev-bf16/transformer/diffusion_pytorch_model_MERGED.safetensors",
        ]),
        (lambda s: "kontext" in s, [
            "nvfp4/flux1-kontext-dev-nvfp4.safetensors",
            "flux1-kontext-dev-bf16/flux1-kontext-dev.safetensors",
        ]),
        (lambda s: "krea2" in s or "krea-2" in s or "krea_2" in s, [
            "nvfp4/krea2_turbo_nvfp4.safetensors",
            "nvfp4/flux1-krea-dev-nvfp4.safetensors",
        ]),
        (lambda s: "kreaedit" in s or "krea-edit" in s, [
            "krea-edit/bigLove_kreaedit1.safetensors",
            "nvfp4/krea2_turbo_nvfp4.safetensors",
        ]),
        (lambda s: "qwen_image" in s or "qwen-image" in s, [
            "nvfp4/qwen_image_edit_2511_nvfp4.safetensors",
        ]),
        (lambda s: "z_image" in s or "z-image" in s or "zpop" in s or "zit" in s, [
            "nvfp4/z_image_turbo_nvfp4.safetensors",
            "ZIT/z_image_de_turbo_v1_bf16.safetensors",
        ]),
        (lambda s: "chroma" in s and "kaleidoscope" not in s, [
            "Chroma/Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors",
            "chroma-1-hd-bf16/chroma-unlocked-v50-flash-heun.safetensors",
        ]),
        (lambda s: "flux" in s and "schnell" in s, [
            "flux1-schnell.safetensors",
            "flux1-schnell-bf16/flux1-schnell.safetensors",
        ]),
        (lambda s: "flux" in s, [
            "nvfp4/flux1-dev-nvfp4.safetensors",
            "flux1-dev-fp8.safetensors",
            "flux1-dev.safetensors",
        ]),
    ],
    "clip_name": [
        (lambda s: "qwen_3_8b" in s or "qwen3_8b" in s, [
            "nvfp4/qwen_3_8b_fp4mixed.safetensors",
            "qwen_3_8b_fp8mixed.safetensors",
            "qwen_3_8b.safetensors",
        ]),
        (lambda s: "qwen_3_4b" in s and "flux2" in s, [
            "nvfp4/qwen_3_4b_fp4_flux2.safetensors",
            "nvfp4/qwen_3_4b_fp4_mixed.safetensors",
            "qwen_3_4b.safetensors",
        ]),
        (lambda s: "qwen_3_4b" in s or "qwen3_4b" in s, [
            "nvfp4/qwen_3_4b_fp4_flux2.safetensors",
            "nvfp4/qwen_3_4b_fp4_mixed.safetensors",
            "qwen_3_4b.safetensors",
        ]),
        (lambda s: "qwen3vl_4b" in s, [
            "qwen3vl_4b_int8_convrot.safetensors",
            "qwen3vl_4b_fp8_scaled.safetensors",
            "qwen3vl_4b_bf16.safetensors",
        ]),
        (lambda s: "qwen_2.5_vl" in s or "qwen2.5_vl" in s, [
            "nvfp4/qwen_2.5_vl_7b_nvfp4.safetensors",
            "qwen_2.5_vl_7b_fp8_scaled.safetensors",
        ]),
        (lambda s: "mistral_3_small" in s, [
            "nvfp4/mistral_3_small_flux2_fp4_mixed.safetensors",
            "flux2-dev-bf16/text_encoder/model_MERGED.safetensors",
        ]),
        (lambda s: "umt5" in s, [
            "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "umt5-xxl-enc-bf16.safetensors",
        ]),
        (lambda s: "t5xxl" in s, [
            "t5xxl_fp8_e4m3fn.safetensors",
            "t5xxl_fp8_e4m3fn_scaled.safetensors",
        ]),
        (lambda s: "gemma_3_12b" in s, [
            "nvfp4/gemma_3_12B_it_fp4_mixed.safetensors",
            "gemma_2_2b_fp16.safetensors",
        ]),
    ],
    "clip_name2": [
        (lambda s: "t5xxl" in s, [
            "t5xxl_fp8_e4m3fn.safetensors",
            "t5xxl_fp8_e4m3fn_scaled.safetensors",
        ]),
    ],
    "vae_name": [
        (lambda s: "flux2" in s, ["flux2-vae.safetensors"]),
        (lambda s: "qwen_image" in s, ["qwen_image_vae.safetensors"]),
        (lambda s: s == "ae.safetensors" or s.endswith("/ae.safetensors") or "flux1" in s, ["ae.safetensors"]),
    ],
}


def _resolve_picker_filename(requested, valid_list, input_name="unet_name", clip_type=None):
    """Resolve ``requested`` model filename against ``valid_list`` on the server."""
    if not requested or not valid_list:
        return requested
    try:
        from .model_detect import is_usable_model
    except ImportError:
        is_usable_model = lambda x, p="unet": True

    pool = ("vae" if "vae" in input_name
            else "clip" if "clip" in input_name
            else "ckpt" if "ckpt" in input_name
            else "unet")

    valid_set = set(valid_list)
    if requested in valid_set and is_usable_model(requested, pool):
        return requested

    req_norm = requested.replace("\\", "/").lower()
    req_base = req_norm.rsplit("/", 1)[-1]

    # 1. Normalized path or basename match
    for v in valid_list:
        if not is_usable_model(v, pool):
            continue
        vn = v.replace("\\", "/").lower()
        if vn == req_norm or vn.rsplit("/", 1)[-1] == req_base:
            return v

    # 2. Special case: qwen_3_4b with lumina2 vs flux2 clip_type
    if input_name == "clip_name" and "qwen_3_4b" in req_norm:
        if clip_type == "lumina2" and "nvfp4/qwen_3_4b_fp4_mixed.safetensors" in valid_set:
            return "nvfp4/qwen_3_4b_fp4_mixed.safetensors"
        if clip_type == "flux2" and "nvfp4/qwen_3_4b_fp4_flux2.safetensors" in valid_set:
            return "nvfp4/qwen_3_4b_fp4_flux2.safetensors"

    # 3. Alias table lookup
    for match_fn, candidates in _MODEL_ALIAS_CANDIDATES.get(input_name, []):
        if match_fn(req_norm):
            for cand in candidates:
                if cand in valid_set and is_usable_model(cand, pool):
                    return cand
                cand_low = cand.lower()
                for v in valid_list:
                    if v.replace("\\", "/").lower() == cand_low and is_usable_model(v, pool):
                        return v

    return requested


def heal_workflow_for_server(workflow, comfy_url):
    """Heal optional missing nodes and cross-machine model filenames in ``workflow``.

    Safe to call from both ``preflight_workflow`` and ``optimize_workflow``:
    uses the per-URL ``/object_info`` cache and fails open if ``comfy_url`` is
    unreachable.
    """
    if not workflow or not comfy_url:
        return workflow, []
    available = get_available_nodes(comfy_url)
    if not available:
        return workflow, []

    try:
        from .model_detect import classify_ckpt_model, is_usable_model
    except ImportError:
        classify_ckpt_model = lambda x: "sdxl"
        is_usable_model = lambda x, p="unet": True

    patched = {
        k: ({**v, "inputs": dict(v.get("inputs", {}))}
            if isinstance(v, dict) and "class_type" in v else v)
        for k, v in workflow.items()
    }
    notes = []

    # 1. Bypass missing optional model/conditioning pass-through nodes
    for nid, node in list(patched.items()):
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        if ct and ct not in available and ct in FALLBACK_REGISTRY:
            fb_fn, desc, _hint = FALLBACK_REGISTRY[ct]
            if fb_fn is not None:
                repl = fb_fn(nid, patched[nid], patched)
                if repl is not None:
                    if nid in patched and nid not in repl:
                        del patched[nid]
                    patched.update(repl)
                    notes.append(f"{ct} -> {desc}")

    # 2. Heal loader filenames & ZIT Checkpoint -> UNET+CLIP+VAE conversion
    unet_list = _get_picker_values(comfy_url, "UNETLoader", "unet_name")
    ckpt_list = _get_picker_values(comfy_url, "CheckpointLoaderSimple", "ckpt_name")
    lora_list = _get_picker_values(comfy_url, "LoraLoader", "lora_name")
    lora_set = set(lora_list)

    for nid, node in list(patched.items()):
        if not isinstance(node, dict) or nid not in patched:
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})

        # Convert desktop ZIT CheckpointLoaderSimple to Spark2 UNET+CLIP+VAE+AuraFlow
        if ct == "CheckpointLoaderSimple":
            ckpt_name = inputs.get("ckpt_name", "")
            if ckpt_name and ckpt_name not in ckpt_list:
                arch = classify_ckpt_model(ckpt_name)
                if arch == "zit":
                    zit_unet = _resolve_picker_filename(ckpt_name, unet_list, "unet_name")
                    if zit_unet in unet_list:
                        u_id = f"{nid}_unet"
                        c_id = f"{nid}_clip"
                        v_id = f"{nid}_vae"
                        clip_list = _get_picker_values(comfy_url, "CLIPLoader", "clip_name")
                        zit_clip = _resolve_picker_filename(
                            "nvfp4/qwen_3_4b_fp4_mixed.safetensors",
                            clip_list, "clip_name", clip_type="lumina2")
                        patched[u_id] = {
                            "class_type": "UNETLoader",
                            "inputs": {"unet_name": zit_unet, "weight_dtype": "default"},
                        }
                        patched[c_id] = {
                            "class_type": "CLIPLoader",
                            "inputs": {"clip_name": zit_clip, "type": "lumina2", "device": "default"},
                        }
                        patched[v_id] = {
                            "class_type": "VAELoader",
                            "inputs": {"vae_name": "ae.safetensors"},
                        }
                        patched[nid] = {
                            "class_type": "ModelSamplingAuraFlow",
                            "inputs": {"model": [u_id, 0], "shift": 3.0},
                        }
                        _rewire_refs(patched, nid, 1, c_id, 0)
                        _rewire_refs(patched, nid, 2, v_id, 0)
                        # Also upgrade EmptyLatentImage -> EmptySD3LatentImage for 16-ch ae.safetensors
                        for _lnid, lnode in patched.items():
                            if isinstance(lnode, dict) and lnode.get("class_type") == "EmptyLatentImage":
                                lnode["class_type"] = "EmptySD3LatentImage"
                        notes.append(f"ZIT CheckpointLoaderSimple({ckpt_name}) -> UNETLoader({zit_unet})")
                        continue
                # Same-arch checkpoint fallback if exact checkpoint is missing
                resolved_ckpt = _resolve_picker_filename(ckpt_name, ckpt_list, "ckpt_name")
                if resolved_ckpt not in ckpt_list:
                    for cand in ckpt_list:
                        if is_usable_model(cand, "ckpt") and classify_ckpt_model(cand) == arch:
                            resolved_ckpt = cand
                            break
                if resolved_ckpt in ckpt_list and resolved_ckpt != ckpt_name:
                    inputs["ckpt_name"] = resolved_ckpt
                    notes.append(f"Checkpoint {ckpt_name} -> {resolved_ckpt}")

        elif ct == "UNETLoader":
            u_name = inputs.get("unet_name", "")
            resolved = _resolve_picker_filename(u_name, unet_list, "unet_name")
            if resolved != u_name and resolved in unet_list:
                inputs["unet_name"] = resolved
                notes.append(f"UNET {u_name} -> {resolved}")
            elif u_name and unet_list and u_name not in unet_list and ckpt_list:
                resolved_ckpt = _resolve_picker_filename(u_name, ckpt_list, "ckpt_name")
                if resolved_ckpt in ckpt_list:
                    patched[nid] = {
                        "class_type": "CheckpointLoaderSimple",
                        "inputs": {"ckpt_name": resolved_ckpt},
                    }
                    notes.append(f"UNETLoader({u_name}) -> CheckpointLoaderSimple({resolved_ckpt})")

        elif ct == "CLIPLoader":
            c_name = inputs.get("clip_name", "")
            c_type = inputs.get("type", "")
            clip_list = _get_picker_values(comfy_url, "CLIPLoader", "clip_name")
            resolved = _resolve_picker_filename(c_name, clip_list, "clip_name", clip_type=c_type)
            if resolved != c_name:
                inputs["clip_name"] = resolved
                notes.append(f"CLIP {c_name} -> {resolved}")

        elif ct == "DualCLIPLoader":
            clip_list = _get_picker_values(comfy_url, "DualCLIPLoader", "clip_name1")
            for k in ("clip_name1", "clip_name2"):
                c_name = inputs.get(k, "")
                resolved = _resolve_picker_filename(c_name, clip_list, k)
                if resolved != c_name:
                    inputs[k] = resolved
                    notes.append(f"DualCLIP.{k} {c_name} -> {resolved}")

        elif ct == "VAELoader":
            v_name = inputs.get("vae_name", "")
            vae_list = _get_picker_values(comfy_url, "VAELoader", "vae_name")
            resolved = _resolve_picker_filename(v_name, vae_list, "vae_name")
            if resolved != v_name:
                inputs["vae_name"] = resolved
                notes.append(f"VAE {v_name} -> {resolved}")

        elif ct in ("LoraLoader", "LoraLoaderModelOnly") and lora_list:
            l_name = inputs.get("lora_name", "")
            if l_name and l_name not in lora_set:
                resolved = _resolve_picker_filename(l_name, lora_list, "lora_name")
                if resolved in lora_set:
                    inputs["lora_name"] = resolved
                    notes.append(f"LoRA {l_name} -> {resolved}")
                else:
                    # Missing desktop LoRA on remote server: bypass cleanly so generation succeeds
                    m_ref = inputs.get("model")
                    c_ref = inputs.get("clip")
                    if isinstance(m_ref, list) and len(m_ref) == 2:
                        _rewire_refs(patched, nid, 0, m_ref[0], m_ref[1])
                    if isinstance(c_ref, list) and len(c_ref) == 2:
                        _rewire_refs(patched, nid, 1, c_ref[0], c_ref[1])
                    del patched[nid]
                    notes.append(f"LoRA {l_name} not on server -> bypassed")

    return patched, notes


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
    patched = {
        k: ({**v, "inputs": dict(v.get("inputs", {}))}
            if isinstance(v, dict) and "class_type" in v else v)
        for k, v in workflow.items()
    }

    # Collect all class_types used in the workflow
    used_types = {}
    for nid, node in patched.items():
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

    # Phase 3: Heal cross-machine model filenames against server enums
    patched, heal_notes = heal_workflow_for_server(patched, comfy_url)
    for hn in heal_notes:
        report["substituted"].append(("model_heal", hn))

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


# ═══════════════════════════════════════════════════════════════════════
#  Model-file validation (ckpt / lora / cn / upscale / vae / clip)
# ═══════════════════════════════════════════════════════════════════════
#
#  preflight_workflow() above only validates that the NODE TYPES exist.
#  It doesn't check whether the MODEL FILES referenced by those nodes are
#  actually on the server. When a referenced file is missing, ComfyUI
#  submit fails with "Value not in list for <node>.<input>" — accurate
#  but not actionable because the user has no idea which file to
#  download.
#
#  `validate_workflow_files` extends preflight by cross-referencing
#  every picker-typed input (the ones ComfyUI shows as dropdowns) with
#  the list ComfyUI itself publishes in /object_info. When a value
#  isn't in the list, we record it as a "missing file" so the caller
#  can surface a useful message ("install <file> via ...").

#: Node-type + input-name pairs whose value should appear in that
#: input's declared picker. Expand this as new model-loader node types
#: are added to workflows. The canonical source of picker lists is
#: /object_info/<NodeType>.input.required[<input_name>][0] which is a
#: list of filenames — missing files get flagged.
_PICKER_INPUTS = {
    ("CheckpointLoaderSimple", "ckpt_name"),
    ("CheckpointLoader", "ckpt_name"),
    ("LoraLoader", "lora_name"),
    ("LoraLoaderModelOnly", "lora_name"),
    ("ControlNetLoader", "control_net_name"),
    ("UpscaleModelLoader", "model_name"),
    ("VAELoader", "vae_name"),
    ("CLIPLoader", "clip_name"),
    ("CLIPLoaderGGUF", "clip_name"),
    ("DualCLIPLoader", "clip_name1"),
    ("DualCLIPLoader", "clip_name2"),
    ("UNETLoader", "unet_name"),
    ("UnetLoaderGGUF", "unet_name"),
    ("DownloadAndLoadDepthAnythingV3Model", "model"),
    ("LoadAndApplyICLightUnet", "model_path"),
    # Add more as discovered. NB: some custom-node pickers use
    # different node names — this set is advisory, not exhaustive.
}


def _get_picker_values(comfy_url, class_type, input_name):
    """Return the list of valid values for a picker-typed input. Empty
    list when /object_info doesn't expose the node or the input shape
    isn't a list-of-strings."""
    try:
        if comfy_url not in _node_info_cache:
            get_available_nodes(comfy_url)
        info = _node_info_cache.get(comfy_url, {}).get(class_type)
        if not info:
            return []
        spec = (info.get("input", {}).get("required", {}).get(input_name)
                or info.get("input", {}).get("optional", {}).get(input_name))
        if not spec:
            return []
        # spec is [type_descriptor, ...]. Type descriptor is either a
        # primitive string ("STRING", "INT") or a LIST of values (the
        # picker).
        first = spec[0] if isinstance(spec, list) and spec else None
        if isinstance(first, list):
            return [str(v) for v in first]
        return []
    except Exception:
        return []


def validate_workflow_files(workflow, comfy_url):
    """Cross-check every model-file reference in a workflow against the
    files ComfyUI actually has on disk. Runs AFTER preflight_workflow
    (which may have substituted node types); operates on the patched
    workflow.

    Returns ``(ok, report)`` with ``report`` shape:
        {
          "missing_files": [(class_type, input_name, value)],
          "checked": N,                # count of picker inputs validated
        }

    Never raises — failures to reach the server return ok=True with an
    empty report (fail-open, matching the preflight_workflow contract).
    """
    report = {"missing_files": [], "checked": 0}
    if not workflow or not comfy_url:
        return True, report

    # Seed the info cache (also populates _available_nodes).
    get_available_nodes(comfy_url)
    info_cache = _node_info_cache.get(comfy_url, {})
    if not info_cache:
        return True, report   # couldn't reach server — fail open

    # Build picker-value sets for the node types actually used in THIS
    # workflow. Caches per-class so we don't refetch per node.
    picker_values_cache: dict[tuple[str, str], set[str]] = {}

    for _nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {}) or {}
        for inp_name, val in inputs.items():
            if (ct, inp_name) not in _PICKER_INPUTS:
                continue
            # val should be a string (filename). Upstream refs are
            # [node_id, slot] lists and can't be model-file references.
            if not isinstance(val, str) or not val:
                continue
            cache_key = (ct, inp_name)
            if cache_key not in picker_values_cache:
                picker_values_cache[cache_key] = set(
                    _get_picker_values(comfy_url, ct, inp_name))
            picker = picker_values_cache[cache_key]
            if not picker:
                continue   # unknown picker — can't verify, skip
            report["checked"] += 1
            if val not in picker:
                entry = (ct, inp_name, val)
                if entry not in report["missing_files"]:
                    report["missing_files"].append(entry)

    ok = len(report["missing_files"]) == 0
    return ok, report


def format_missing_files_hint(missing_files):
    """Human-readable explanation for a `missing_files` list.
    Groups by the kind of file (checkpoint / LoRA / ControlNet / …)
    and suggests where to find each one."""
    if not missing_files:
        return ""
    by_kind: dict[str, list[str]] = {}
    KIND_HINTS = {
        "ckpt_name": ("Checkpoint",
                       "ComfyUI/models/checkpoints/"),
        "lora_name": ("LoRA",
                       "ComfyUI/models/loras/"),
        "control_net_name": ("ControlNet",
                              "ComfyUI/models/controlnet/"),
        "model_name": ("Upscaler",
                        "ComfyUI/models/upscale_models/"),
        "vae_name": ("VAE",
                      "ComfyUI/models/vae/"),
        "clip_name": ("CLIP / text encoder",
                       "ComfyUI/models/clip/"),
        "clip_name1": ("CLIP / text encoder",
                        "ComfyUI/models/clip/"),
        "clip_name2": ("CLIP / text encoder",
                        "ComfyUI/models/clip/"),
        "unet_name": ("UNET / diffusion model",
                       "ComfyUI/models/unet/"),
        "model": ("Model",
                   "ComfyUI/models/"),
        "model_path": ("Model",
                        "ComfyUI/models/"),
    }
    for ct, inp_name, val in missing_files:
        label, _path = KIND_HINTS.get(inp_name, ("Model", "ComfyUI/models/"))
        by_kind.setdefault(label, []).append(val)
    lines = []
    for kind, files in by_kind.items():
        _label_path = next((v[1] for k, v in KIND_HINTS.items()
                             if v[0] == kind), "ComfyUI/models/")
        lines.append(f"Missing {kind} files (drop them into {_label_path}):")
        for f in files:
            lines.append(f"  • {f}")
    return "\n".join(lines)
