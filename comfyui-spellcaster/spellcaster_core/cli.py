#!/usr/bin/env python3
"""Spellcaster CLI — generate images/videos from the command line.

No GIMP, no Wizard Guild, no browser needed. Just ComfyUI + this script.

Usage:
    # Generate an image
    python -m spellcaster_core.cli generate --prompt "a wizard in a forest" --server http://192.168.x.x:8188

    # Generate with specific model
    python -m spellcaster_core.cli generate --prompt "anime girl" --model "Illustrious\\ilustreal.safetensors" --arch illustrious

    # Upscale an image already on ComfyUI
    python -m spellcaster_core.cli upscale --image "myfile.png" --model "4x-UltraSharp.pth"

    # Check what nodes are available
    python -m spellcaster_core.cli doctor --server http://192.168.x.x:8188

    # Batch: generate variations
    python -m spellcaster_core.cli batch --prompt "a {color} dragon" --vary color=red,blue,green,gold

    # List available models on server
    python -m spellcaster_core.cli models --server http://192.168.x.x:8188
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import random

# Ensure spellcaster_core is importable
_here = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_here)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from spellcaster_core.workflows import build_txt2img, build_upscale, build_rembg
from spellcaster_core.architectures import get_arch, ARCHITECTURES
from spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model
from spellcaster_core.preflight import preflight_workflow, get_available_nodes


DEFAULT_SERVER = "http://127.0.0.1:8188"


# ═══════════════════════════════════════════════════════════════════════
#  ComfyUI communication
# ═══════════════════════════════════════════════════════════════════════

def submit(server, workflow):
    """Submit workflow to ComfyUI, return prompt_id."""
    ok, workflow, report = preflight_workflow(workflow, server)
    if not ok:
        print(f"  ERROR: Missing nodes: {', '.join(report['missing'])}")
        return None
    for orig, desc in report.get("substituted", []):
        print(f"  [fallback] {orig} -> {desc}")

    body = json.dumps({"prompt": workflow}).encode()
    req = urllib.request.Request(
        f"{server}/prompt", data=body,
        headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read()).get("prompt_id")
    except urllib.error.HTTPError as e:
        err = json.loads(e.read().decode())
        for nid, ne in err.get("node_errors", {}).items():
            for er in ne.get("errors", []):
                print(f"  REJECTED: {ne.get('class_type', '?')}: {er.get('details', '')[:120]}")
        return None


def wait_for(server, pid, timeout=300):
    """Poll until prompt completes. Returns output info or None."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = urllib.request.urlopen(f"{server}/history/{pid}", timeout=5)
            d = json.loads(r.read())
            if pid in d:
                st = d[pid].get("status", {})
                if st.get("completed"):
                    return d[pid].get("outputs", {})
                for msg in st.get("messages", []):
                    if msg[0] == "execution_error":
                        print(f"  ERROR: {msg[1].get('exception_message', '?')[:200]}")
                        return None
        except Exception:
            pass
        time.sleep(2)
    print(f"  TIMEOUT after {timeout}s")
    return None


def download_output(server, outputs, dest_dir="."):
    """Download output files from ComfyUI to local directory."""
    saved = []
    for nid, out in outputs.items():
        for key in ("images", "gifs", "videos"):
            for item in out.get(key, []):
                fn = item.get("filename", "")
                sf = item.get("subfolder", "")
                ft = item.get("type", "output")
                url = f"{server}/view?filename={fn}&subfolder={sf}&type={ft}"
                try:
                    data = urllib.request.urlopen(url, timeout=120).read()
                    dest = os.path.join(dest_dir, fn)
                    with open(dest, "wb") as f:
                        f.write(data)
                    saved.append(dest)
                    print(f"  Saved: {dest} ({len(data) / 1024:.0f} KB)")
                except Exception as e:
                    print(f"  Download failed: {fn} ({e})")
    return saved


# ═══════════════════════════════════════════════════════════════════════
#  Commands
# ═══════════════════════════════════════════════════════════════════════

def cmd_generate(args):
    """Generate an image from a text prompt."""
    server = args.server
    model = args.model
    arch_key = args.arch

    # Auto-detect architecture from model name
    if not arch_key and model:
        if model.endswith(".gguf"):
            arch_key = classify_unet_model(model)
        else:
            arch_key = classify_ckpt_model(model)
        print(f"  Auto-detected architecture: {arch_key}")

    if not arch_key:
        arch_key = "sd15"

    # Auto-detect model if not specified
    if not model:
        model = _find_best_model(server, arch_key)
        if not model:
            print("ERROR: No model specified and auto-detect failed.")
            return 1
        print(f"  Auto-selected model: {model}")

    a = get_arch(arch_key)
    is_gguf = model.endswith(".gguf")

    # Default resolution per architecture
    _default_res = {"sd15": (512, 512), "sdxl": (1024, 1024), "illustrious": (1024, 1024),
                    "flux1dev": (1024, 1024), "flux2klein": (1024, 1024), "chroma": (1024, 1024),
                    "zit": (1024, 1024), "pony": (1024, 1024)}
    dw, dh = _default_res.get(arch_key, (512, 512))

    preset = {
        "ckpt": model,
        "arch": arch_key,
        "width": args.width or dw,
        "height": args.height or dh,
        "steps": args.steps or a.default_steps,
        "cfg": args.cfg if args.cfg is not None else a.default_cfg,
        "sampler": a.default_sampler,
        "scheduler": a.default_scheduler,
        "loader": a.loader if not is_gguf or a.loader != "checkpoint" else "unet_clip_vae",
        "clip_name1": getattr(a, "clip_name1", ""),
        "clip_name2": getattr(a, "clip_name2", ""),
        "vae_name": getattr(a, "vae_name", ""),
    }

    negative = args.negative or ("blurry, ugly, deformed" if a.supports_negative else "")
    seed = args.seed if args.seed >= 0 else random.randint(1, 2**32 - 1)

    prompt_text = args.prompt
    # Auto-add quality tags
    if a.quality_positive and arch_key not in ("flux1dev", "flux2klein", "chroma"):
        prompt_text = f"{prompt_text}, {a.quality_positive}"

    print(f"  Generating: {args.width or a.default_width}x{args.height or a.default_height}, "
          f"{preset['steps']} steps, seed={seed}")

    workflow = build_txt2img(preset, prompt_text, negative, seed)
    pid = submit(server, workflow)
    if not pid:
        return 1

    print(f"  Queued: {pid[:12]}...")
    outputs = wait_for(server, pid, timeout=args.timeout)
    if outputs:
        download_output(server, outputs, args.output)
    return 0


def cmd_upscale(args):
    """Upscale an image on ComfyUI."""
    workflow = build_upscale(args.image, args.model or "4x-UltraSharp.pth")
    pid = submit(args.server, workflow)
    if not pid:
        return 1
    print(f"  Queued: {pid[:12]}...")
    outputs = wait_for(args.server, pid, timeout=args.timeout)
    if outputs:
        download_output(args.server, outputs, args.output)
    return 0


def cmd_rembg(args):
    """Remove background from an image on ComfyUI."""
    workflow = build_rembg(args.image)
    pid = submit(args.server, workflow)
    if not pid:
        return 1
    print(f"  Queued: {pid[:12]}...")
    outputs = wait_for(args.server, pid, timeout=args.timeout)
    if outputs:
        download_output(args.server, outputs, args.output)
    return 0


def cmd_batch(args):
    """Generate multiple variations from a template prompt."""
    if not args.vary:
        print("ERROR: --vary required (e.g. --vary color=red,blue,green)")
        return 1

    key, values_str = args.vary.split("=", 1)
    values = [v.strip() for v in values_str.split(",")]

    print(f"  Batch: {len(values)} variations of '{{{key}}}'")
    for i, val in enumerate(values):
        prompt = args.prompt.replace(f"{{{key}}}", val)
        print(f"\n  [{i+1}/{len(values)}] {prompt}")
        # Reuse generate logic
        args.prompt = prompt
        args.seed = random.randint(1, 2**32 - 1)
        cmd_generate(args)
    return 0


def cmd_doctor(args):
    """Check ComfyUI server health and node availability."""
    server = args.server
    print(f"Spellcaster Doctor")
    print(f"  Server: {server}")
    print()

    # Check connectivity
    try:
        r = urllib.request.urlopen(f"{server}/system_stats", timeout=5)
        stats = json.loads(r.read())
        dev = stats["devices"][0]
        print(f"  GPU: {dev['name']}")
        print(f"  VRAM: {dev['vram_total'] / 1e9:.1f} GB total, "
              f"{dev['vram_free'] / 1e9:.1f} GB free")
    except Exception as e:
        print(f"  ERROR: Cannot reach server ({e})")
        return 1

    # Node count
    nodes = get_available_nodes(server, force_refresh=True)
    print(f"  Nodes: {len(nodes)} available")
    print()

    # Check critical nodes
    critical = {
        "CheckpointLoaderSimple": "Model loading (checkpoint)",
        "UNETLoader": "Model loading (UNET)",
        "UnetLoaderGGUF": "Model loading (GGUF)",
        "CLIPLoader": "Text encoder loading",
        "CLIPLoaderGGUF": "Text encoder loading (GGUF)",
        "VAELoader": "VAE loading",
        "KSampler": "Standard sampling",
        "SaveImage": "Image saving",
        "VHS_VideoCombine": "Video assembly (VideoHelperSuite)",
        "ReActorFaceSwapOpt": "Face swap (ReActor)",
        "ImageRembg": "Background removal",
        "LaMaInpainting": "Object removal (LaMa)",
        "RIFE_VFI": "Frame interpolation (RIFE)",
        "RTXVideoSuperResolution": "RTX upscale (known broken - auto-fallback)",
        "WanImageToVideo": "WAN I2V conditioning",
        "IPAdapterWANLoader": "WAN IP-Adapter",
        "LTXVLoader": "LTX video loading",
        "UpscaleModelLoader": "AI upscale model loading",
        "ImageUpscaleWithModel": "AI upscale execution",
    }

    print("  Critical Nodes:")
    for ct, desc in critical.items():
        status = "OK" if ct in nodes else "MISSING"
        icon = "+" if status == "OK" else "-"
        print(f"    [{icon}] {ct}: {desc}")

    # Model inventory
    print()
    _print_models(server)
    return 0


def cmd_models(args):
    """List all available models on ComfyUI."""
    _print_models(args.server)
    return 0


def _print_models(server):
    """Print available models grouped by type."""
    def _get_opts(node, field):
        try:
            r = urllib.request.urlopen(f"{server}/object_info/{node}", timeout=5)
            d = json.loads(r.read())
            spec = d[node]["input"]["required"][field]
            if isinstance(spec[0], list):
                return spec[0]
            elif isinstance(spec[1], dict) and "options" in spec[1]:
                return spec[1]["options"]
            return spec[0] if isinstance(spec[0], str) else []
        except Exception:
            return []

    ckpts = _get_opts("CheckpointLoaderSimple", "ckpt_name")
    unets = _get_opts("UnetLoaderGGUF", "unet_name")

    if ckpts:
        print(f"  Checkpoints ({len(ckpts)}):")
        for c in ckpts:
            arch = classify_ckpt_model(c)
            print(f"    [{arch:12s}] {c}")
    if unets:
        print(f"  UNET/GGUF ({len(unets)}):")
        for u in unets:
            arch = classify_unet_model(u)
            print(f"    [{arch:12s}] {u}")


def cmd_vram(args):
    """Estimate VRAM usage for a generation configuration."""
    from spellcaster_core.optimizer import estimate_vram, get_max_resolution, get_server_vram, ARCH_BASE_VRAM

    server_vram = get_server_vram(args.server) if args.server != DEFAULT_SERVER else None

    if args.all:
        print(f"VRAM Estimates ({args.width}x{args.height}, {args.frames} frames)")
        if server_vram:
            print(f"Server VRAM: {server_vram:.1f} GB")
        print()
        for arch in sorted(ARCH_BASE_VRAM.keys()):
            est, breakdown = estimate_vram(arch, args.width, args.height, args.frames)
            safe = ""
            if server_vram:
                safe = " OK" if est < server_vram * 0.9 else " OOM RISK"
                max_w, max_h = get_max_resolution(server_vram, arch)
                safe += f" (max safe: {max_w}x{max_h})"
            print(f"  {arch:14s} {est:5.1f} GB  {breakdown}{safe}")
    else:
        est, breakdown = estimate_vram(args.arch, args.width, args.height, args.frames)
        print(f"VRAM estimate for {args.arch}: {est:.1f} GB")
        print(f"  {breakdown}")
        if server_vram:
            pct = est / server_vram * 100
            status = "OK" if pct < 90 else "OOM RISK"
            print(f"  Server: {server_vram:.1f} GB ({pct:.0f}% usage) [{status}]")
            max_w, max_h = get_max_resolution(server_vram, args.arch)
            print(f"  Max safe resolution: {max_w}x{max_h}")
    return 0


def _find_best_model(server, arch_key):
    """Find the best available model for an architecture on ComfyUI."""
    def _get_opts(node, field):
        try:
            r = urllib.request.urlopen(f"{server}/object_info/{node}", timeout=5)
            d = json.loads(r.read())
            spec = d[node]["input"]["required"][field]
            if isinstance(spec[0], list):
                return spec[0]
            elif isinstance(spec[1], dict) and "options" in spec[1]:
                return spec[1]["options"]
            return []
        except Exception:
            return []

    # Skip known non-model files (VAEs, text encoders, embeddings connectors)
    skip_patterns = ("vae", "embeddings_connector", "audio_vae", "text_encoder",
                     "clip_", "t5xxl", "umt5", "gemma", "qwen", "mistral", "llava")

    # Try GGUF first, then checkpoints
    for loader, field, classify_fn in [
        ("UnetLoaderGGUF", "unet_name", classify_unet_model),
        ("CheckpointLoaderSimple", "ckpt_name", classify_ckpt_model),
    ]:
        for m in _get_opts(loader, field):
            ml = m.lower()
            if any(s in ml for s in skip_patterns):
                continue
            if classify_fn(m) == arch_key:
                return m
    return None


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        prog="spellcaster",
        description="Spellcaster CLI -- generate images/videos via ComfyUI")
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER,
                        help=f"ComfyUI server URL (default: {DEFAULT_SERVER})")
    parser.add_argument("--output", "-o", default=".",
                        help="Output directory (default: current dir)")
    parser.add_argument("--timeout", "-t", type=int, default=300,
                        help="Timeout in seconds (default: 300)")

    sub = parser.add_subparsers(dest="command", help="Command to run")

    # generate
    p_gen = sub.add_parser("generate", aliases=["gen", "g"],
                           help="Generate image from text prompt")
    p_gen.add_argument("--prompt", "-p", required=True, help="Text prompt")
    p_gen.add_argument("--negative", "-n", default="", help="Negative prompt")
    p_gen.add_argument("--model", "-m", default="", help="Model filename")
    p_gen.add_argument("--arch", "-a", default="", help="Architecture key (sd15, sdxl, flux2klein, ...)")
    p_gen.add_argument("--width", "-W", type=int, default=0)
    p_gen.add_argument("--height", "-H", type=int, default=0)
    p_gen.add_argument("--steps", type=int, default=0)
    p_gen.add_argument("--cfg", type=float, default=None)
    p_gen.add_argument("--seed", type=int, default=-1)

    # upscale
    p_up = sub.add_parser("upscale", aliases=["up"],
                          help="Upscale an image")
    p_up.add_argument("--image", "-i", required=True, help="Image filename on ComfyUI")
    p_up.add_argument("--model", "-m", default="4x-UltraSharp.pth")

    # rembg
    p_rm = sub.add_parser("rembg", aliases=["bg"],
                          help="Remove background")
    p_rm.add_argument("--image", "-i", required=True, help="Image filename on ComfyUI")

    # batch
    p_batch = sub.add_parser("batch", aliases=["b"],
                             help="Batch generate variations")
    p_batch.add_argument("--prompt", "-p", required=True, help="Template prompt with {variable}")
    p_batch.add_argument("--vary", "-v", required=True, help="variable=val1,val2,val3")
    p_batch.add_argument("--model", "-m", default="")
    p_batch.add_argument("--arch", "-a", default="")
    p_batch.add_argument("--width", "-W", type=int, default=0)
    p_batch.add_argument("--height", "-H", type=int, default=0)
    p_batch.add_argument("--steps", type=int, default=0)
    p_batch.add_argument("--cfg", type=float, default=None)
    p_batch.add_argument("--seed", type=int, default=-1)
    p_batch.add_argument("--negative", "-n", default="")

    # doctor
    sub.add_parser("doctor", aliases=["doc", "check"],
                   help="Check server health and node availability")

    # models
    sub.add_parser("models", aliases=["ls"],
                   help="List available models")

    # vram estimate
    p_vram = sub.add_parser("vram", help="Estimate VRAM usage for a generation")
    p_vram.add_argument("--arch", "-a", default="sdxl", help="Architecture")
    p_vram.add_argument("--width", "-W", type=int, default=1024)
    p_vram.add_argument("--height", "-H", type=int, default=1024)
    p_vram.add_argument("--frames", "-f", type=int, default=1, help="Frame count (video)")
    p_vram.add_argument("--all", action="store_true", help="Show all architectures")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    cmd = args.command
    if cmd in ("generate", "gen", "g"):
        return cmd_generate(args)
    elif cmd in ("upscale", "up"):
        return cmd_upscale(args)
    elif cmd in ("rembg", "bg"):
        return cmd_rembg(args)
    elif cmd in ("batch", "b"):
        return cmd_batch(args)
    elif cmd in ("doctor", "doc", "check"):
        return cmd_doctor(args)
    elif cmd in ("models", "ls"):
        return cmd_models(args)
    elif cmd == "vram":
        return cmd_vram(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
