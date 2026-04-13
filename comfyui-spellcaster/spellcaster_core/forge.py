"""The Forge — workflow architect, chimera builder, reverse-engineer.

The meta-wizard that creates other wizards. Capabilities:
  1. Reverse-engineer: extract workflow from a ComfyUI PNG's metadata
  2. Analyze: understand what a workflow does (models, LoRAs, pipeline type)
  3. Chimera: build multi-pass pipelines (generate -> refine -> post-process)
  4. Import: scan ComfyUI for unscaffolded workflows and wrap them
  5. Customize: clone a scaffold and modify its parameters

Usage:
    from spellcaster_core.forge import (
        reverse_engineer_image, analyze_workflow,
        build_chimera, discover_comfyui_workflows,
    )

    # Reverse-engineer a ComfyUI image
    wf = reverse_engineer_image("path/to/image.png")

    # Analyze what a workflow does
    info = analyze_workflow(wf)
    # {"type": "txt2img", "model": "juggernaut.safetensors", "arch": "sdxl",
    #  "loras": [...], "resolution": [1024, 1024], "steps": 20, ...}

    # Build a chimera pipeline
    chimera = build_chimera([
        {"action": "txt2img", "arch": "flux2klein", "prompt": "portrait"},
        {"action": "img2img", "arch": "sdxl", "denoise": 0.4, "prompt": "oil painting"},
        {"action": "upscale", "model": "4x-UltraSharp.pth"},
        {"action": "face_restore"},
    ])
"""

import json
import os
import struct
import zlib

try:
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .architectures import get_arch, ARCHITECTURES
except ImportError:
    from spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model
    from spellcaster_core.architectures import get_arch, ARCHITECTURES


# ═══════════════════════════════════════════════════════════════════════
#  Reverse-engineer: extract workflow from PNG metadata
# ═══════════════════════════════════════════════════════════════════════

def reverse_engineer_image(image_path):
    """Extract ComfyUI workflow from a PNG's embedded metadata.

    ComfyUI embeds workflow JSON in PNG tEXt chunks under keys
    'workflow' (UI format) and 'prompt' (API format).

    Returns dict: {"workflow": {...}, "prompt": {...}, "source": "png_metadata"}
    or None if no metadata found.
    """
    if not os.path.isfile(image_path):
        return None

    try:
        chunks = _read_png_text_chunks(image_path)
    except Exception:
        return None

    result = {"source": "png_metadata"}

    # ComfyUI stores workflow in tEXt chunk with key "workflow"
    if "workflow" in chunks:
        try:
            result["workflow"] = json.loads(chunks["workflow"])
        except Exception:
            pass

    # API-format prompt in tEXt chunk with key "prompt"
    if "prompt" in chunks:
        try:
            result["prompt"] = json.loads(chunks["prompt"])
        except Exception:
            pass

    if "workflow" not in result and "prompt" not in result:
        return None

    return result


def _read_png_text_chunks(filepath):
    """Read all tEXt/iTXt chunks from a PNG file."""
    chunks = {}
    with open(filepath, "rb") as f:
        # Verify PNG signature
        sig = f.read(8)
        if sig != b'\x89PNG\r\n\x1a\n':
            return chunks

        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            length = struct.unpack(">I", header[:4])[0]
            chunk_type = header[4:8]
            data = f.read(length)
            f.read(4)  # CRC

            if chunk_type == b'tEXt':
                # tEXt: key\0value
                null_idx = data.find(b'\x00')
                if null_idx >= 0:
                    key = data[:null_idx].decode('latin-1')
                    value = data[null_idx+1:].decode('utf-8', errors='replace')
                    chunks[key] = value

            elif chunk_type == b'iTXt':
                # iTXt: key\0compression\0\0\0value (simplified)
                null_idx = data.find(b'\x00')
                if null_idx >= 0:
                    key = data[:null_idx].decode('latin-1')
                    rest = data[null_idx+1:]
                    # Skip compression flag, method, language, translated keyword
                    # Find the actual text after the null separators
                    parts = rest.split(b'\x00', 3)
                    if len(parts) >= 4:
                        text_data = parts[3]
                        # Check if compressed
                        if parts[0] == b'\x01':
                            try:
                                text_data = zlib.decompress(text_data)
                            except Exception:
                                pass
                        chunks[key] = text_data.decode('utf-8', errors='replace')
                    elif len(parts) >= 1:
                        chunks[key] = rest.decode('utf-8', errors='replace')

            elif chunk_type == b'IEND':
                break

    return chunks


# ═══════════════════════════════════════════════════════════════════════
#  Analyze: understand what a workflow does
# ═══════════════════════════════════════════════════════════════════════

def analyze_workflow(workflow):
    """Analyze a ComfyUI workflow and extract key information.

    Accepts either API format ({"1": {"class_type": ..., "inputs": ...}})
    or UI format ({"nodes": [...], "links": [...]}).

    Returns dict with:
      type: "txt2img", "img2img", "video", "upscale", etc.
      models: [{name, arch, loader_type}]
      loras: [{name, strength_model, strength_clip}]
      resolution: [width, height]
      steps: int
      cfg: float
      sampler: str
      scheduler: str
      node_types: [class_types used]
      pipeline_stages: ["generation", "upscale", "face_swap", ...]
    """
    # Detect format
    if "nodes" in workflow and "links" in workflow:
        return _analyze_ui_format(workflow)
    else:
        return _analyze_api_format(workflow)


def _analyze_api_format(workflow):
    """Analyze API-format workflow."""
    info = {
        "type": "unknown",
        "models": [],
        "loras": [],
        "resolution": [0, 0],
        "steps": 0,
        "cfg": 0,
        "sampler": "",
        "scheduler": "",
        "node_types": [],
        "pipeline_stages": [],
        "node_count": len(workflow),
    }

    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})
        info["node_types"].append(ct)

        # Models
        if ct == "CheckpointLoaderSimple":
            name = inputs.get("ckpt_name", "")
            info["models"].append({
                "name": name, "arch": classify_ckpt_model(name),
                "loader": "checkpoint"})
        elif ct in ("UNETLoader", "UnetLoaderGGUF"):
            name = inputs.get("unet_name", "")
            info["models"].append({
                "name": name, "arch": classify_unet_model(name),
                "loader": "unet_gguf" if "GGUF" in ct else "unet"})

        # LoRAs
        elif ct in ("LoraLoader", "LoraLoaderModelOnly"):
            info["loras"].append({
                "name": inputs.get("lora_name", ""),
                "strength_model": inputs.get("strength_model", 1.0),
                "strength_clip": inputs.get("strength_clip", 1.0),
            })

        # Resolution
        elif ct == "EmptyLatentImage":
            info["resolution"] = [inputs.get("width", 0), inputs.get("height", 0)]

        # Sampler
        elif ct == "KSampler":
            info["steps"] = inputs.get("steps", 0)
            info["cfg"] = inputs.get("cfg", 0)
            info["sampler"] = inputs.get("sampler_name", "")
            info["scheduler"] = inputs.get("scheduler", "")

        # Pipeline stages
        if ct in ("CheckpointLoaderSimple", "UNETLoader", "UnetLoaderGGUF"):
            if "generation" not in info["pipeline_stages"]:
                info["pipeline_stages"].append("generation")
        if ct in ("UpscaleModelLoader", "ImageUpscaleWithModel"):
            if "upscale" not in info["pipeline_stages"]:
                info["pipeline_stages"].append("upscale")
        if ct in ("ReActorFaceSwapOpt", "ReActorFaceSwap"):
            if "face_swap" not in info["pipeline_stages"]:
                info["pipeline_stages"].append("face_swap")
        if ct == "ReActorRestoreFace":
            if "face_restore" not in info["pipeline_stages"]:
                info["pipeline_stages"].append("face_restore")
        if ct in ("VHS_VideoCombine", "SaveVideo"):
            if "video" not in info["pipeline_stages"]:
                info["pipeline_stages"].append("video")
        if ct == "WanImageToVideo":
            info["type"] = "video_i2v"
        if ct == "ImageRembg":
            if "rembg" not in info["pipeline_stages"]:
                info["pipeline_stages"].append("rembg")

    # Infer workflow type
    if info["type"] == "unknown":
        stages = info["pipeline_stages"]
        if "video" in stages:
            info["type"] = "video"
        elif "generation" in stages and len(info["models"]) == 1:
            info["type"] = "txt2img"
        elif "generation" in stages and len(info["models"]) > 1:
            info["type"] = "chimera"
        elif "upscale" in stages and "generation" not in stages:
            info["type"] = "upscale"
        elif "face_swap" in stages:
            info["type"] = "face_swap"

    info["node_types"] = list(set(info["node_types"]))
    return info


def _analyze_ui_format(workflow):
    """Analyze UI-format workflow (litegraph nodes+links)."""
    # Convert UI nodes to pseudo-API format for reuse
    api_like = {}
    for node in workflow.get("nodes", []):
        nid = str(node.get("id", ""))
        ct = node.get("type", "")
        # Extract widget values as inputs
        inputs = {}
        for i, val in enumerate(node.get("widgets_values", [])):
            inputs[f"widget_{i}"] = val
        # Also check properties
        if "properties" in node:
            inputs.update(node["properties"])
        api_like[nid] = {"class_type": ct, "inputs": inputs}
    return _analyze_api_format(api_like)


# ═══════════════════════════════════════════════════════════════════════
#  Chimera: multi-pass pipeline builder
# ═══════════════════════════════════════════════════════════════════════

def build_chimera(steps, server=None):
    """Build a multi-pass chimera pipeline definition.

    Each step is a dict:
      {"action": "txt2img"|"img2img"|"upscale"|"face_swap"|"face_restore"|"rembg"|"wan_video",
       "arch": "sdxl",           # for generation steps
       "model": "model.safetensors",  # optional specific model
       "prompt": "...",          # for generation steps
       "negative": "...",        # optional
       "denoise": 0.5,           # for img2img
       "loras": [{name, strength_model, strength_clip}],
       ...other step-specific params}

    Returns a chimera definition dict that can be:
      1. Saved as a scaffold in the Travelling Wizard
      2. Executed via the Pipeline class
      3. Displayed in the Guild as a custom wizard
    """
    chimera = {
        "name": "Custom Chimera",
        "steps": steps,
        "step_count": len(steps),
        "models_used": [],
        "description": "",
    }

    # Build human-readable description
    desc_parts = []
    for i, step in enumerate(steps):
        action = step.get("action", "?")
        arch = step.get("arch", "")
        if action in ("txt2img", "img2img"):
            desc_parts.append(f"Pass {i+1}: {action} ({arch})")
        else:
            desc_parts.append(f"Pass {i+1}: {action}")
        if arch:
            chimera["models_used"].append(arch)

    chimera["description"] = " -> ".join(desc_parts)
    chimera["models_used"] = list(set(chimera["models_used"]))

    return chimera


def execute_chimera(chimera, server, callback=None):
    """Execute a chimera pipeline on a ComfyUI server.

    Uses the Pipeline class to chain steps, feeding each output
    to the next step.

    Returns list of output (filename, subfolder, type) tuples.
    """
    try:
        from .pipeline import Pipeline
    except ImportError:
        from spellcaster_core.pipeline import Pipeline

    log = callback or print
    p = Pipeline(server, verbose=True)

    for i, step in enumerate(chimera.get("steps", [])):
        action = step.get("action", "")
        log(f"  Chimera step {i+1}/{chimera['step_count']}: {action}")

        if action == "txt2img":
            p.txt2img(
                step.get("prompt", ""),
                negative=step.get("negative", ""),
                arch=step.get("arch", "sdxl"),
                model=step.get("model", ""),
                width=step.get("width", 0),
                height=step.get("height", 0),
                steps=step.get("steps", 0),
                cfg=step.get("cfg"),
                loras=step.get("loras"),
            )
        elif action == "img2img":
            p.img2img(
                step.get("prompt", ""),
                negative=step.get("negative", ""),
                denoise=step.get("denoise", 0.5),
                arch=step.get("arch", "sdxl"),
            )
        elif action == "upscale":
            p.upscale(step.get("model", "4x-UltraSharp.pth"))
        elif action == "face_restore":
            p.face_restore(weight=step.get("weight", 0.7))
        elif action == "rembg":
            p.rembg()
        elif action == "faceswap":
            p.faceswap(step.get("source", ""))
        elif action == "wan_video":
            p.wan_video(
                step.get("prompt", "subtle motion"),
                length=step.get("length", 33),
                width=step.get("width", 576),
                height=step.get("height", 320),
            )
        elif action == "ltx_video":
            p.ltx_video(
                step.get("prompt", "animation"),
                width=step.get("width", 384),
                height=step.get("height", 256),
            )

    return p.run()


# ═══════════════════════════════════════════════════════════════════════
#  Discover: find unscaffolded workflows on ComfyUI
# ═══════════════════════════════════════════════════════════════════════

def discover_comfyui_workflows(comfy_dir=None):
    """Scan for .json workflow files in ComfyUI's user directory.

    Looks in ComfyUI/user/default/workflows/ and ComfyUI/output/*.json

    Returns list of dicts:
      [{"path": "/path/to/workflow.json", "name": "My Workflow",
        "analysis": {...analyze_workflow result...}}]
    """
    results = []

    search_dirs = []
    if comfy_dir:
        search_dirs.append(os.path.join(comfy_dir, "user", "default", "workflows"))
        search_dirs.append(os.path.join(comfy_dir, "output"))
        search_dirs.append(os.path.join(comfy_dir, "custom_workflows"))

    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for fname in os.listdir(search_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(search_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    wf = json.load(f)
                analysis = analyze_workflow(wf)
                results.append({
                    "path": fpath,
                    "name": fname.replace(".json", "").replace("_", " ").title(),
                    "analysis": analysis,
                })
            except Exception:
                pass

    return results


def workflow_to_scaffold(workflow, name="Imported Workflow"):
    """Convert a ComfyUI workflow into a Spellcaster scaffold definition.

    Extracts tunable parameters, sets sensible defaults, and creates
    a scaffold that can be loaded into the Travelling Wizard editor.
    """
    analysis = analyze_workflow(workflow)

    # Extract tunable parameters
    params = []
    if analysis.get("resolution", [0, 0]) != [0, 0]:
        w, h = analysis["resolution"]
        params.append({"name": "width", "type": "number", "label": "Width",
                       "default": str(w), "min": "256", "max": "2048"})
        params.append({"name": "height", "type": "number", "label": "Height",
                       "default": str(h), "min": "256", "max": "2048"})
    if analysis.get("steps"):
        params.append({"name": "steps", "type": "number", "label": "Steps",
                       "default": str(analysis["steps"]), "min": "1", "max": "100"})
    if analysis.get("cfg"):
        params.append({"name": "cfg", "type": "number", "label": "CFG Scale",
                       "default": str(analysis["cfg"]), "min": "1", "max": "20"})

    # Always add prompt
    params.insert(0, {"name": "prompt", "type": "text", "label": "Prompt",
                      "help": "Describe what you want to create"})

    scaffold = {
        "name": name,
        "description": f"{analysis['type']} workflow with {analysis['node_count']} nodes. "
                       f"Models: {', '.join(m['arch'] for m in analysis.get('models', []))}. "
                       f"Stages: {' -> '.join(analysis.get('pipeline_stages', []))}.",
        "workflow_key": name.lower().replace(" ", "_"),
        "workflow_type": analysis["type"],
        "params": params,
        "models": analysis.get("models", []),
        "loras": analysis.get("loras", []),
        "pipeline_stages": analysis.get("pipeline_stages", []),
        "original_workflow": workflow,
    }

    return scaffold
