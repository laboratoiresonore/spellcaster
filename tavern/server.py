"""
Wizard Guild — HTTP Server + API
=================================
Lightweight standalone server for the Spellcaster GUI.
Handles character discovery, ComfyUI workflow dispatch, and static file serving.
"""

import json
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
import sys
import os
import random
import hashlib
import time
import signal
import socket
import threading

# ── Path setup ────────────────────────────────────────────────────────
# Add parent dirs so scaffold/ and _workflows_v2 can be found
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(_THIS_DIR))
sys.path.append(os.path.join(os.path.dirname(_THIS_DIR),
                             'plugins', 'gimp', 'comfyui-connector'))

try:
    import _workflows_v2
    from _workflows_v2 import build_txt2img
    from _architectures import ARCHITECTURES, get_arch
    BUILTIN_AVAILABLE = True
except (ImportError, SyntaxError):
    BUILTIN_AVAILABLE = False
    _workflows_v2 = None
    build_txt2img = None
    ARCHITECTURES = {}
    get_arch = None

# Scaffold imports — graceful fallback if any module has import errors
try:
    from scaffold.meta_wizard import build_meta_system_prompt, INTENTS
except (ImportError, Exception):
    INTENTS = {}
    def build_meta_system_prompt(*a, **kw):
        return "You are a helpful wizard assistant."

try:
    from scaffold.introspector import discover_nodes
except (ImportError, Exception):
    def discover_nodes():
        return {}

try:
    from scaffold.workflow_wizard import discover_workflows
except (ImportError, Exception):
    def discover_workflows(search_dirs=None):
        return []

# ── Configurable globals (set by launcher before serve) ───────────────
PORT = 7777
COMFYUI_URL = "http://127.0.0.1:8188"
KOBOLD_URL = "http://127.0.0.1:5001"
VERSION = "1.0.0"


# ═══════════════════════════════════════════════════════════════════════
#  Instance Management — kill prior instances before binding
# ═══════════════════════════════════════════════════════════════════════

def _is_port_in_use(port: int) -> bool:
    """Check if a TCP port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def _kill_prior_instances(port: int):
    """Kill any process currently listening on our port."""
    import subprocess as _sp

    if sys.platform == 'win32':
        try:
            out = _sp.check_output(
                ['netstat', '-ano', '-p', 'TCP'],
                stderr=_sp.DEVNULL, text=True)
            for line in out.splitlines():
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.split()
                    pid = parts[-1]
                    if pid.isdigit() and int(pid) != os.getpid():
                        _sp.run(['taskkill', '/F', '/PID', pid],
                                capture_output=True)
                        print(f"  Killed prior instance (PID {pid})")
        except Exception:
            pass
    else:
        try:
            out = _sp.check_output(
                ['lsof', '-ti', f':{port}'],
                stderr=_sp.DEVNULL, text=True)
            for pid in out.strip().split():
                if pid.isdigit() and int(pid) != os.getpid():
                    os.kill(int(pid), signal.SIGTERM)
                    print(f"  Killed prior instance (PID {pid})")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
#  Studio Characters — capability-group wizards for multi-step tools
# ═══════════════════════════════════════════════════════════════════════

STUDIO_CHARACTERS = [
    {
        "id": "studio_imaginus",
        "type": "studio",
        "name": "Imaginus",
        "subtext": "Image Creation (txt2img, ControlNet)",
        "color1": "hsl(270, 90%, 45%)",
        "color2": "hsl(330, 100%, 60%)",
        "archetype": "a radiant conjurer of visions, surrounded by swirling paint and prismatic light",
        "build_fns": [
            "build_txt2img", "build_controlnet_gen", "build_colorize",
            "build_iclight", "build_lut",
        ],
        "system_prompt": (
            "You are Imaginus, the Guild's master of image creation.\n\n"
            "YOUR TOOLS (each maps to a build function you can invoke):\n"
            "1. **Text-to-Image** (build_txt2img) — Generate images from a text prompt.\n"
            "   Key params: prompt, negative_prompt, width (default 1024), height (default 1024), seed\n"
            "2. **ControlNet Generation** (build_controlnet_gen) — Generate guidance maps (canny, depth, pose, scribble, lineart, tile).\n"
            "   Key params: image_filename, preprocessor (canny/depth/pose/scribble/lineart/tile)\n"
            "3. **Colorize** (build_colorize) — Convert B&W images to color.\n"
            "   Key params: image_filename, prompt (color hints)\n"
            "4. **IC-Light** (build_iclight) — Relight an image by repositioning light sources.\n"
            "   Key params: image_filename, light_multiplier\n"
            "5. **LUT Color Grading** (build_lut) — Apply cinematic color grading.\n"
            "   Key params: image_filename, lut_name, strength\n\n"
            "PROTOCOL:\n"
            "- Greet the user with enthusiasm and ask what vision they want to conjure\n"
            "- Suggest the right tool with numbered choices\n"
            "- Collect the parameters conversationally — help refine their prompt!\n"
            "- When confirmed, output a JSON block:\n"
            "```json\n"
            '{\"build_fn\": \"build_txt2img\", \"params\": {\"prompt\": \"...\", ...}}\n'
            "```\n"
        ),
    },
    {
        "id": "studio_transmutex",
        "type": "studio",
        "name": "Transmutex",
        "subtext": "Image Transformation (img2img, Style Transfer)",
        "color1": "hsl(30, 90%, 40%)",
        "color2": "hsl(60, 100%, 55%)",
        "archetype": "a transmutation alchemist, hands glowing with transformative energy, molten gold swirling",
        "build_fns": [
            "build_img2img", "build_klein_img2img", "build_klein_img2img_ref",
            "build_klein_scene_img2img", "build_klein_blend", "build_klein_repose",
            "build_style_transfer", "build_layer_blend",
        ],
        "system_prompt": (
            "You are Transmutex, the Guild's alchemist of image transformation.\n\n"
            "YOUR TOOLS:\n"
            "1. **Image-to-Image** (build_img2img) — Transform an existing image with a new prompt.\n"
            "   Key params: image_filename, prompt, negative_prompt, denoise_strength (0.0-1.0)\n"
            "2. **Klein Img2Img** (build_klein_img2img) — Flux 2 Klein transformation (4-20 steps, very fast).\n"
            "   Key params: image_filename, prompt, refinement_level (subtle/light/moderate/strong/heavy/transform/reimagine)\n"
            "3. **Klein + Reference** (build_klein_img2img_ref) — Klein with structure/style from a reference image.\n"
            "   Key params: image_filename, ref_filename, prompt\n"
            "4. **Klein Scene** (build_klein_scene_img2img) — Scene-aware semantic transformation.\n"
            "   Key params: image_filename, prompt\n"
            "5. **Klein Blend** (build_klein_blend) — Harmonize layers (match lighting/shadows).\n"
            "   Key params: image_filename, overlay_filename\n"
            "6. **Klein Re-poser** (build_klein_repose) — Change character poses (26 poses, 8 camera angles).\n"
            "   Key params: image_filename, pose, camera_angle\n"
            "7. **Style Transfer** (build_style_transfer) — Transfer style from a reference image.\n"
            "   Key params: image_filename, style_filename, strength\n"
            "8. **Layer Blend** (build_layer_blend) — Blend two images with parametric harmonization.\n"
            "   Key params: image_filename, overlay_filename, blend_mode\n\n"
            "PROTOCOL:\n"
            "- Ask what transformation the user needs\n"
            "- Suggest the right tool\n"
            "- Collect parameters step by step\n"
            "- Output JSON: {\"build_fn\": \"...\", \"params\": {...}}\n"
        ),
    },
    {
        "id": "studio_masquerade",
        "type": "studio",
        "name": "Masquerade",
        "subtext": "Face & Identity (Face Swap, FaceID, PuLID)",
        "color1": "hsl(340, 85%, 40%)",
        "color2": "hsl(20, 100%, 55%)",
        "archetype": "a masked shapeshifter with shifting features, mirrors floating around them reflecting different faces",
        "build_fns": [
            "build_faceswap", "build_faceswap_model", "build_faceswap_mtb",
            "build_save_face_model", "build_faceid_img2img", "build_pulid_flux",
            "build_klein_headswap", "build_face_restore", "build_photobooth",
        ],
        "system_prompt": (
            "You are Masquerade, the Guild's master of face and identity magic.\n\n"
            "YOUR TOOLS:\n"
            "1. **Face Swap (ReActor)** (build_faceswap) — Swap a face from source onto target image.\n"
            "   Key params: target_filename, source_filename, restore_face (bool)\n"
            "2. **Face Swap (Model)** (build_faceswap_model) — Swap using a saved face model.\n"
            "   Key params: target_filename, face_model_name\n"
            "3. **Save Face Model** (build_save_face_model) — Save a face from an image as reusable model.\n"
            "   Key params: source_filename, model_name\n"
            "4. **Face Swap (MTB)** (build_faceswap_mtb) — Alternative face swap engine.\n"
            "   Key params: target_filename, source_filename\n"
            "5. **FaceID** (build_faceid_img2img) — Generate images matching a specific person's identity.\n"
            "   Key params: face_filename, prompt, strength\n"
            "6. **PuLID Flux** (build_pulid_flux) — Flux-native identity transfer.\n"
            "   Key params: face_filename, prompt\n"
            "7. **Klein Head Swap** (build_klein_headswap) — ReActor swap + Klein blend refinement.\n"
            "   Key params: target_filename, source_filename\n"
            "8. **Face Restore** (build_face_restore) — Enhance faces with CodeFormer.\n"
            "   Key params: image_filename, fidelity_weight (0.0-1.0)\n"
            "9. **Photobooth** (build_photobooth) — One-step portrait generation with face control.\n"
            "   Key params: face_filename, prompt\n\n"
            "PROTOCOL:\n"
            "- Ask what the user wants to do with faces\n"
            "- For face swaps, always ask for source and target\n"
            "- Recommend face_restore as a follow-up if quality matters\n"
            "- Output JSON: {\"build_fn\": \"...\", \"params\": {...}}\n"
        ),
    },
    {
        "id": "studio_restorix",
        "type": "studio",
        "name": "Restorix",
        "subtext": "Upscaling & Restoration Pipelines",
        "color1": "hsl(160, 80%, 35%)",
        "color2": "hsl(200, 100%, 55%)",
        "archetype": "a grand elder wizard wielding a crystalline magnifying lens, ancient runes of clarity orbiting them",
        "build_fns": [
            "build_upscale", "build_photo_restore", "build_detail_hallucinate",
            "build_supir", "build_seedv2r", "build_upscale_blend",
        ],
        "system_prompt": (
            "You are Restorix, the Guild's master of restoration and upscaling.\n\n"
            "YOUR TOOLS (ordered from simple to complex):\n"
            "1. **AI Upscale** (build_upscale) — Simple upscale with one model.\n"
            "   Models: 4x-UltraSharp, RealESRGAN_x4plus, 4x_foolhardy_Remacri, NMKD, Anime, Faces\n"
            "   Key params: image_filename, upscale_model, scale_factor\n"
            "2. **Upscaler Blend** (build_upscale_blend) — Blend two upscale models (sharp + smooth).\n"
            "   Key params: image_filename, model_a, model_b, blend_ratio\n"
            "3. **Photo Restoration** (build_photo_restore) — 3-stage pipeline: Upscale -> Face Restore -> Sharpen.\n"
            "   Key params: image_filename, upscale_model, face_model, sharpen_radius\n"
            "   PRESETS (offer these first!):\n"
            "     - Quick fix: UltraSharp + CodeFormer 0.5 + gentle sharpen\n"
            "     - Full restoration: UltraSharp + CodeFormer 0.7 + standard sharpen\n"
            "     - Gentle (preserve character): Remacri + CodeFormer 0.4 + soft sharpen\n"
            "4. **Detail Hallucination** (build_detail_hallucinate) — Upscale + low-denoise img2img for texture synthesis.\n"
            "   Key params: image_filename, denoise (keep low: 0.15-0.35), cfg, prompt_text\n"
            "   PRESETS:\n"
            "     - Subtle enhancement: denoise 0.25, cfg 5.0\n"
            "     - Balanced hallucination: UltraSharp + denoise 0.35, cfg 7.0\n"
            "     - Aggressive detail: UltraSharp + denoise 0.50, cfg 9.0\n"
            "5. **SUPIR Restoration** (build_supir) — 5-stage AI restoration, best quality.\n"
            "   Key params: image_filename, supir_model, sdxl_model, prompt, denoise, steps\n"
            "   PRESETS:\n"
            "     - Quick restore: denoise 0.25, 25 steps\n"
            "     - Full restoration: denoise 0.35, 45 steps\n"
            "     - Upscale + restore: denoise 0.3, scale_by 1.5\n"
            "     - Fidelity (preserve original): v0F model, denoise 0.2, 35 steps\n"
            "6. **SeedV2R** (build_seedv2r) — Specialized temporal upscaler with hallucination control.\n"
            "   Key params: image_filename, hallucination (none/light/high), scale (2x/3x/4x)\n\n"
            "RECOMMENDATIONS:\n"
            "- Quick upscale: tool 1 or 2\n"
            "- Old/damaged photos with faces: tool 3 (photo_restore) — offer presets!\n"
            "- Need more texture detail: tool 4 (detail_hallucinate)\n"
            "- Maximum quality, no rush: tool 5 (SUPIR)\n\n"
            "PROTOCOL:\n"
            "- Ask what the user wants to upscale/restore\n"
            "- Recommend the right pipeline based on their description\n"
            "- ALWAYS offer presets first — most users want Quick fix or Full restoration\n"
            "- Only ask for individual params if user picks Manual\n"
            "- Output JSON: {\"build_fn\": \"...\", \"params\": {...}}\n"
        ),
    },
    {
        "id": "studio_erasure",
        "type": "studio",
        "name": "Erasure",
        "subtext": "Inpainting, Removal & Surgical Edits",
        "color1": "hsl(220, 75%, 40%)",
        "color2": "hsl(260, 100%, 60%)",
        "archetype": "an ethereal figure phasing between dimensions, partially transparent, erasing reality with glowing fingertips",
        "build_fns": [
            "build_rembg", "build_lama_remove", "build_inpaint",
            "build_outpaint", "build_klein_inpaint",
        ],
        "system_prompt": (
            "You are Erasure, the Guild's specialist in surgical image editing.\n\n"
            "YOUR TOOLS:\n"
            "1. **Background Removal** (build_rembg) — Remove background, output transparent PNG.\n"
            "   Key params: image_filename\n"
            "   Note: No diffusion needed, fast and clean.\n"
            "2. **Object Removal (LaMa)** (build_lama_remove) — Remove objects using context-aware fill.\n"
            "   Key params: image_filename, mask_filename\n"
            "   Note: No diffusion, uses LaMa inpainting model.\n"
            "3. **Inpainting** (build_inpaint) — Regenerate masked regions with AI diffusion.\n"
            "   Key params: image_filename, mask_filename, prompt, denoise_strength\n"
            "   44 expert presets (body-part-tuned denoise values).\n"
            "4. **Outpainting** (build_outpaint) — Extend the canvas beyond original borders.\n"
            "   Key params: image_filename, prompt, pad_left, pad_right, pad_top, pad_bottom\n"
            "5. **Klein Inpainting** (build_klein_inpaint) — Context-aware inpainting with Flux 2 Klein.\n"
            "   Key params: image_filename, mask_filename, prompt\n"
            "   29 task presets for different scenarios.\n\n"
            "DECISION GUIDE:\n"
            "- Remove background entirely: tool 1 (rembg)\n"
            "- Remove a specific object cleanly: tool 2 (lama_remove)\n"
            "- Replace a region with something new: tool 3 (inpaint) or 5 (klein_inpaint)\n"
            "- Extend/expand the image: tool 4 (outpaint)\n\n"
            "PROTOCOL:\n"
            "- Ask what the user wants to remove or edit\n"
            "- Recommend the right tool\n"
            "- Collect parameters (especially mask if needed)\n"
            "- Output JSON: {\"build_fn\": \"...\", \"params\": {...}}\n"
        ),
    },
    {
        "id": "studio_videomancer",
        "type": "studio",
        "name": "Videomancer",
        "subtext": "Video Generation & Enhancement",
        "color1": "hsl(180, 85%, 35%)",
        "color2": "hsl(140, 100%, 50%)",
        "archetype": "a time-bending sorcerer surrounded by floating film reels and shimmering temporal portals",
        "build_fns": [
            "build_wan_video", "build_wan_flf", "build_ltx_video",
            "build_video_upscale", "build_video_reactor",
            "build_seedvr2_video_upscale", "build_frame_assembly",
        ],
        "system_prompt": (
            "You are Videomancer, the Guild's master of motion and time.\n\n"
            "YOUR TOOLS (organized by task):\n\n"
            "-- VIDEO GENERATION --\n"
            "1. **WAN Image-to-Video** (build_wan_video) — Turn any photo into a 2-10 sec video.\n"
            "   Key params: image_filename, prompt_text, negative_text, seed\n"
            "   Options: width (832), height (480), length (81 frames), fps (16)\n"
            "   Post-processing: rtx_scale (0/2/4), interpolate (RIFE 4x), face_swap, pingpong\n"
            "   Turbo: turbo=True uses LightX2V LoRA (30 steps to 4 steps)\n"
            "   PRESETS:\n"
            "     - Standard quality: 832x480, 81 frames, turbo, RTX 2.5x, RIFE, face swap\n"
            "     - Fast preview: 576x320, 33 frames, turbo, no post-processing\n"
            "     - High quality (no turbo): full quality dual-UNET, all post-processing\n"
            "     - Long clip (10 sec): 161 frames\n\n"
            "2. **WAN First+Last Frame** (build_wan_flf) — Video transition between two keyframes.\n"
            "   Key params: start_filename, end_filename, prompt_text, seed\n"
            "   Same options as WAN I2V plus end_image_filename.\n\n"
            "3. **LTX Text-to-Video** (build_ltx_video) — Generate video from text only (no input image).\n"
            "   Key params: prompt_text, seed, width (768), height (512), num_frames (25), fps (25)\n"
            "   Modes: single-stage, two_stage (latent upscale 2x), distilled (8 steps, 4x faster)\n"
            "   Optional: image_filename for image-to-video, i2v_strength (0.0-1.0)\n"
            "   Post-processing: rtx_scale (0/2/4), interpolate (RIFE), pingpong\n"
            "   PRESETS:\n"
            "     - Quick preview: 512x384, distilled, no post-processing\n"
            "     - Standard quality: 768x512, 25 frames\n"
            "     - High quality (2-stage): latent upscale pipeline\n"
            "     - Cinematic: 2-stage + RTX 2x + RIFE, 49 frames\n"
            "     - Fast + smooth: distilled + RIFE\n\n"
            "-- VIDEO ENHANCEMENT --\n"
            "4. **Video Upscale** (build_video_upscale) — Upscale video with AI models.\n"
            "   Key params: video_name, upscale_model, upscale_factor, rtx_scale, fps\n\n"
            "5. **Video Face Swap** (build_video_reactor) — Face swap every frame + upscale.\n"
            "   Key params: video_name, face_models (list), upscale_model, rtx_scale, fps\n"
            "   PRESETS:\n"
            "     - Standard: UltraSharp + RTX 2x + CodeFormer 0.7\n"
            "     - Quality: RTX only + CodeFormer 0.5\n\n"
            "6. **SeedVR2 Video Upscale** (build_seedvr2_video_upscale) — AI temporal upscaling.\n"
            "   Key params: video_name, seed, resolution, max_resolution, batch_size\n"
            "   Options: color_correction (lab/wavelet/hsv/adain/none), temporal_overlap\n"
            "   PRESETS:\n"
            "     - Standard: 1024 to 2048, batch 4, lab color correction\n"
            "     - High quality: 2048 to 4096, batch 2, temporal overlap 4\n"
            "     - Fast preview: 720 to 1080, batch 8\n\n"
            "-- UTILITY --\n"
            "7. **Frame Assembly** (build_frame_assembly) — Assemble image frames into MP4.\n"
            "   Key params: frame_filenames (list of paths), fps, filename_prefix\n\n"
            "DECISION GUIDE:\n"
            "- Animate a photo: tool 1 (WAN I2V) best quality, 8-16GB VRAM\n"
            "- Transition between two photos: tool 2 (WAN FLF)\n"
            "- Generate video from text only: tool 3 (LTX) no input image needed\n"
            "- Upscale existing video: tool 4 (traditional) or 6 (SeedVR2 AI)\n"
            "- Face swap on video: tool 5 (video_reactor)\n\n"
            "PROTOCOL:\n"
            "- Ask what the user wants: generate new video or enhance existing?\n"
            "- For generation: ask for image (WAN) or text prompt (LTX)\n"
            "- Offer presets first (Quick preview / Standard / High quality / Cinematic)\n"
            "- Collect remaining params conversationally\n"
            "- Output JSON: {\"build_fn\": \"...\", \"params\": {...}}\n"
        ),
    },
]

# Lookup for quick access
_STUDIO_BY_ID = {c["id"]: c for c in STUDIO_CHARACTERS}


# ═══════════════════════════════════════════════════════════════════════
#  Character Discovery — populate the Guild from scaffold introspection
# ═══════════════════════════════════════════════════════════════════════

def _discover_build_functions():
    """Discover all build_* functions in _workflows_v2 and categorize them.

    Returns a list of dicts: {fn_name, display_name, category, description}
    for every build function that isn't already claimed by a studio character.
    """
    if not BUILTIN_AVAILABLE or _workflows_v2 is None:
        return []

    import inspect

    # Collect all build_fn names claimed by studio characters
    claimed = set()
    for sc in STUDIO_CHARACTERS:
        for fn in sc.get("build_fns", []):
            claimed.add(fn)

    # Category hints for unclaimed functions
    BUILD_FN_INFO = {
        "build_wan_video": {
            "display": "WAN Image-to-Video",
            "category": "Video Generation",
            "desc": "Generate video from an image using WAN model",
        },
        "build_wan_flf": {
            "display": "WAN First-Last-Frame",
            "category": "Video Generation",
            "desc": "Generate video interpolating between start and end frames",
        },
        "build_ltx_video": {
            "display": "LTX Text-to-Video",
            "category": "Video Generation",
            "desc": "Generate video from text prompt using LTX2 model",
        },
        "build_video_upscale": {
            "display": "Video Upscale (AI)",
            "category": "Video Enhancement",
            "desc": "Upscale video resolution with AI models",
        },
        "build_video_reactor": {
            "display": "Video Face Swap",
            "category": "Video Enhancement",
            "desc": "Apply face swap across video frames with ReActor",
        },
        "build_seedvr2_video_upscale": {
            "display": "SeedVR2 Video Upscale",
            "category": "Video Enhancement",
            "desc": "Upscale video with SeedVR2 temporal consistency",
        },
        "build_frame_assembly": {
            "display": "Frame Assembly",
            "category": "Video Utility",
            "desc": "Assemble image frames into a video file",
        },
    }

    results = []
    for name in dir(_workflows_v2):
        if not name.startswith("build_"):
            continue
        if name in claimed:
            continue
        fn = getattr(_workflows_v2, name)
        if not callable(fn):
            continue

        info = BUILD_FN_INFO.get(name, {})
        # Auto-generate display name from function name
        display = info.get("display", name.replace("build_", "").replace("_", " ").title())
        category = info.get("category", "Spellcaster Method")
        desc = info.get("desc", "")
        if not desc:
            doc = inspect.getdoc(fn) or ""
            desc = doc.split("\n")[0] if doc else f"Execute {display}"

        # Get function signature for param info
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())

        results.append({
            "fn_name": name,
            "display_name": display,
            "category": category,
            "description": desc,
            "params": params,
        })

    return results


def _fetch_comfyui_models(comfy_url):
    """Query ComfyUI for all available UNET + checkpoint models.

    Returns a list of dicts: {name, arch, type} where type is 'unet' or 'checkpoint'.
    Fails silently if ComfyUI is unreachable.
    """
    models = []
    try:
        url = f"{comfy_url}/object_info/UNETLoader"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("UNETLoader", {})
                           .get("input", {}).get("required", {})
                           .get("unet_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                for m in choices[0]:
                    ml = m.lower()
                    if "klein" in ml:
                        arch = "flux2klein"
                    elif "flux" in ml:
                        arch = "flux1dev"
                    elif "wan" in ml:
                        arch = "wan"
                    elif "ltx" in ml:
                        arch = "ltx"
                    else:
                        arch = "unknown"
                    models.append({"name": m, "arch": arch, "type": "unet"})
    except Exception:
        pass
    try:
        url = f"{comfy_url}/object_info/CheckpointLoaderSimple"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("CheckpointLoaderSimple", {})
                           .get("input", {}).get("required", {})
                           .get("ckpt_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                for m in choices[0]:
                    ml = m.lower()
                    if "xl" in ml or "sdxl" in ml:
                        arch = "sdxl"
                    elif "illu" in ml:
                        arch = "illustrious"
                    elif "pony" in ml:
                        arch = "pony"
                    elif "flux" in ml:
                        arch = "flux1dev"
                    else:
                        arch = "sd15"
                    models.append({"name": m, "arch": arch, "type": "checkpoint"})
    except Exception:
        pass

    print(f"  [Guild] Detected {len(models)} models from ComfyUI ({comfy_url})")
    return models


def fetch_all_characters(comfy_url=None):
    """Discover all wizard characters from studios, models, and nodes.

    Args:
        comfy_url: Explicit ComfyUI URL. Falls back to global COMFYUI_URL.
    """
    _url = comfy_url or COMFYUI_URL
    chars = []
    nodes = discover_nodes()

    # 1. Studio Characters (capability-group wizards) — always present
    for sc in STUDIO_CHARACTERS:
        chars.append({
            "id": sc["id"],
            "type": sc["type"],
            "name": sc["name"],
            "subtext": sc["subtext"],
            "color1": sc["color1"],
            "color2": sc["color2"],
        })

    # 2. Model-family wizards: merge workflows + unclaimed build_* functions
    #    One wizard per model (LTX2, SeedVR2, WAN, etc.)
    #    Each gets ALL its workflows AND build functions as tools.

    from collections import defaultdict

    MODEL_FAMILIES = {
        "ltx2": {
            "display": "LTX2 Video",
            "subtext": "LTX2 Video Generation & Enhancement (Video)",
            "archetype": "a chronomancer weaving threads of time, arcane hourglasses orbiting",
            "fn_prefixes": ["ltx"],   # matches build_ltx_video etc.
        },
        "seedvr2": {
            "display": "SeedVR2",
            "subtext": "SeedVR2 AI Video Upscaling & Enhancement (Video)",
            "archetype": "a crystalline seer magnifying the fabric of moving images",
            "fn_prefixes": ["seedvr2", "seedv2r"],
        },
        "wan": {
            "display": "WAN Video",
            "subtext": "WAN Video Generation (Video)",
            "archetype": "a mystic who conjures motion from stillness, swirling ink into life",
            "fn_prefixes": ["wan"],
        },
        "video_tools": {
            "display": "Video Toolkit",
            "subtext": "Video Utility Tools (upscale, face swap, assembly)",
            "archetype": "a wizard of temporal arts, bending light through time",
            "fn_prefixes": ["video", "frame"],
        },
    }

    # -- Discover workflow JSON files and group by model --
    wfs = discover_workflows(search_dirs=None)
    wf_grouped = defaultdict(list)
    for wf in wfs:
        name_lower = wf.name.lower()
        matched = False
        for family_key in sorted(MODEL_FAMILIES.keys(), key=len, reverse=True):
            if name_lower.startswith(family_key):
                wf_grouped[family_key].append(wf)
                matched = True
                break
        if not matched:
            wf_grouped[name_lower].append(wf)

    # -- Discover unclaimed build_* functions and group by model --
    unclaimed_fns = _discover_build_functions()
    fn_grouped = defaultdict(list)
    for fn_info in unclaimed_fns:
        fn_bare = fn_info["fn_name"].replace("build_", "").lower()
        matched = False
        for family_key, family_info in MODEL_FAMILIES.items():
            for prefix in family_info.get("fn_prefixes", [family_key]):
                if fn_bare.startswith(prefix):
                    fn_grouped[family_key].append(fn_info)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            fn_grouped["misc"].append(fn_info)

    # -- Check which model families actually have backing ComfyUI models --
    # If the user has no WAN/LTX/SeedVR2 models installed, those wizards
    # should not appear. They'll auto-appear on next restart/reinit once
    # the user installs the corresponding model.
    comfyui_models_early = _fetch_comfyui_models(_url)
    _all_model_names_lower = {m["name"].lower() for m in comfyui_models_early}

    # Map model_family keys to the substrings we look for in ComfyUI model names
    _FAMILY_MODEL_KEYWORDS = {
        "ltx2":        ["ltx"],
        "seedvr2":     ["seedvr"],
        "wan":         ["wan"],
        "video_tools": ["wan", "ltx", "seedvr", "svd", "animate", "rife",
                        "video_upscale", "reactor"],  # needs at least one video model
    }

    def _family_has_backing_model(family_key):
        """Check if ComfyUI has at least one model matching this family."""
        keywords = _FAMILY_MODEL_KEYWORDS.get(family_key)
        if keywords is None:
            return True  # unknown family — show by default
        return any(
            any(kw in mname for kw in keywords)
            for mname in _all_model_names_lower
        )

    # -- Merge into unified model wizards --
    all_model_keys = set(list(wf_grouped.keys()) + list(fn_grouped.keys()))

    for model_key in sorted(all_model_keys):
        model_wfs = wf_grouped.get(model_key, [])
        model_fns = fn_grouped.get(model_key, [])

        if not model_wfs and not model_fns:
            continue

        # Skip this family if no corresponding ComfyUI models are installed
        if not _family_has_backing_model(model_key):
            print(f"  [Guild] Skipping {model_key} wizard — no backing model in ComfyUI")
            continue

        family_info = MODEL_FAMILIES.get(model_key, {})
        display = family_info.get("display", model_key.upper())
        subtext = family_info.get("subtext", f"{display} Workflows")
        archetype = family_info.get("archetype", "a mysterious wizard of arcane craft")
        hue = int(hashlib.md5(model_key.encode('utf-8')).hexdigest(), 16) % 360

        # Build unified tool list for the system prompt
        tool_lines = []
        build_fns = []
        idx = 1

        # Add build_* functions as primary tools (these are callable)
        for fn_info in model_fns:
            tool_lines.append(
                f"{idx}. **{fn_info['display_name']}** ({fn_info['fn_name']})\n"
                f"   {fn_info['description']}\n"
                f"   Parameters: {', '.join(fn_info['params'])}"
            )
            build_fns.append(fn_info["fn_name"])
            idx += 1

        # Add workflow JSON files as launchable workflows
        wf_paths = []
        for wf in model_wfs:
            nice_name = wf.name.replace("_", " ").title()
            tool_lines.append(
                f"{idx}. **{nice_name}** — {wf.workflow_type or 'workflow'} "
                f"({wf.node_count} nodes, JSON workflow)"
            )
            wf_paths.append(str(wf.path))
            idx += 1

        tool_lines.append(f"{idx}. Browse all ComfyUI workflows")
        tool_block = "\n".join(tool_lines)
        total_tools = len(model_fns) + len(model_wfs)

        char_id = f"model_{model_key}"
        chars.append({
            "id": char_id,
            "type": "model_wizard",
            "name": "Unnamed Wizard",
            "subtext": subtext,
            "color1": f"hsl({hue}, 80%, 40%)",
            "color2": f"hsl({(hue+60)%360}, 100%, 60%)",
            "build_fns": build_fns,
            "paths": wf_paths,
        })

        _STUDIO_BY_ID[char_id] = {
            "id": char_id,
            "type": "model_wizard",
            "name": display,
            "subtext": subtext,
            "color1": f"hsl({hue}, 80%, 40%)",
            "color2": f"hsl({(hue+60)%360}, 100%, 60%)",
            "archetype": archetype,
            "build_fns": build_fns,
            "system_prompt": (
                f"You are a wizard specializing in {display}.\n\n"
                f"YOUR TOOLS ({total_tools} available):\n"
                f"{tool_block}\n\n"
                f"PROTOCOL:\n"
                f"- Present the numbered list above when asked what you can do\n"
                f"- Help the user choose the right tool for their needs\n"
                f"- Collect parameters conversationally (prompt, seed, dimensions, etc.)\n"
                f"- When confirmed, output a JSON block:\n"
                f"```json\n"
                f'{{"build_fn": "...", "params": {{...}}}}\n'
                f"```\n"
            ),
        }

    # 3. Auto-populate wizards for ALL ComfyUI checkpoint/UNET models
    #    Each model gets its own wizard with appropriate scaffold + archetype
    existing_ids = {c['id'] for c in chars}

    # Also track model filenames already covered by model_wizards or studios
    # (studio chars use auto-detect so they don't lock to a model — skip them)
    covered_models = set()  # lowercase model filenames already having a wizard

    comfyui_models = comfyui_models_early  # reuse the fetch from step 2
    for m in comfyui_models:
        mname = m["name"]
        mname_lower = mname.lower()
        march = m["arch"]
        mtype = m["type"]

        # Skip models that are infrastructure (VAE, LoRA, embeddings, etc.)
        if any(k in mname_lower for k in ['vae', 'lora', 'embedding', 'clip_',
                                           'controlnet', 'ipadapter', 'ip_adapter',
                                           'insightface', 'codeformer', 'gfpgan',
                                           'esrgan', 'ultrasharp', 'remacri',
                                           'nmkd', 'swinir', 'realesrgan']):
            continue

        # Skip video-specific models already covered by model_family wizards
        if any(k in mname_lower for k in ['ltx', 'wan', 'seedvr', 'svd',
                                           'animate', 'rife']):
            continue

        # Generate a stable ID from the model name
        safe_name = mname.replace('/', '_').replace('\\', '_').replace('.', '_')
        char_id = f"comfyui_{safe_name}"

        if char_id in existing_ids:
            continue  # already have a wizard for this model

        existing_ids.add(char_id)
        covered_models.add(mname_lower)

        # Determine display name (strip path + extension, humanize)
        base = mname.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
        display = base.rsplit('.', 1)[0]  # strip .safetensors etc.

        # Arch-specific archetype and scaffold
        ARCH_PROFILES = {
            "flux2klein": {
                "archetype": "a radiant sorcerer channeling pure flux energy, prismatic fractals swirling",
                "scaffold": "studio_imaginus",
                "subtext_hint": "Flux 2 Klein Image Generation",
            },
            "flux1dev": {
                "archetype": "a luminous conjurer of photorealistic visions, light bending around them",
                "scaffold": "studio_imaginus",
                "subtext_hint": "Flux Image Generation",
            },
            "sdxl": {
                "archetype": "a grand artist-mage painting worlds into existence with broad magical strokes",
                "scaffold": "studio_imaginus",
                "subtext_hint": "SDXL Image Generation",
            },
            "illustrious": {
                "archetype": "an anime-inspired enchantress conjuring vibrant illustrations, manga panels orbiting",
                "scaffold": "studio_imaginus",
                "subtext_hint": "Illustrious Image Generation",
            },
            "sd15": {
                "archetype": "a steadfast mage of classic conjuration, reliable and versatile",
                "scaffold": "studio_imaginus",
                "subtext_hint": "SD 1.5 Image Generation",
            },
            "pony": {
                "archetype": "a whimsical illustrator-wizard of stylized art, paint and ink swirling",
                "scaffold": "studio_imaginus",
                "subtext_hint": "Pony / Stylized Image Generation",
            },
        }

        # Enhanced arch detection
        if march == "unknown":
            if "xl" in mname_lower or "sdxl" in mname_lower:
                march = "sdxl"
            elif "illu" in mname_lower:
                march = "illustrious"
            elif "pony" in mname_lower:
                march = "pony"
            elif "flux" in mname_lower:
                march = "flux1dev"
            elif "klein" in mname_lower:
                march = "flux2klein"
            else:
                march = "sd15"

        profile = ARCH_PROFILES.get(march, ARCH_PROFILES["sd15"])
        hue = int(hashlib.md5(mname.encode('utf-8')).hexdigest(), 16) % 360
        subtext = f"{display} — {profile['subtext_hint']}"

        char_entry = {
            "id": char_id,
            "type": "comfyui_model",
            "name": "Unnamed Wizard",
            "subtext": subtext,
            "color1": f"hsl({hue}, 82%, 38%)",
            "color2": f"hsl({(hue+50)%360}, 100%, 55%)",
            "model_name": mname,
            "model_arch": march,
            "model_type": mtype,
        }
        chars.append(char_entry)

        # Register in _STUDIO_BY_ID so it gets a proper system prompt
        scaffold_id = profile["scaffold"]
        ref_studio = _STUDIO_BY_ID.get(scaffold_id)
        if ref_studio:
            custom_studio = dict(ref_studio)
            custom_studio["id"] = char_id
            custom_studio["name"] = display
            custom_studio["subtext"] = subtext
            custom_studio["color1"] = char_entry["color1"]
            custom_studio["color2"] = char_entry["color2"]
            custom_studio["archetype"] = profile["archetype"]
            custom_studio["default_model"] = mname
            custom_studio["default_arch"] = march
            custom_studio["system_prompt"] = (
                ref_studio["system_prompt"]
                + f"\nDEFAULT MODEL: When building presets, always use "
                f"checkpoint/UNET '{mname}' (arch: {march}) "
                f"unless the user explicitly requests a different model.\n"
            )
            _STUDIO_BY_ID[char_id] = custom_studio

    # 4. Spellcaster Enhancement Nodes (only when running inside ComfyUI)
    for key, spec in nodes.items():
        subtext = spec.display_name or key
        hue = int(hashlib.md5(key.encode('utf-8')).hexdigest(), 16) % 360
        chars.append({
            "id": f"node_{key}",
            "type": "spellcaster_node",
            "name": "Unnamed Wizard",
            "subtext": subtext,
            "color1": f"hsl({hue}, 80%, 40%)",
            "color2": f"hsl({(hue+60)%360}, 100%, 60%)"
        })

    return chars, nodes


CHARS_CACHE, NODES_CACHE = [], []   # populated by _server_init()


def _server_init(comfy_url=None):
    """Call AFTER COMFYUI_URL has been set by the launcher.

    Populates CHARS_CACHE/NODES_CACHE from ComfyUI and starts the
    background LoRA registry builder. Safe to call more than once
    (reinitialize uses it too).

    Args:
        comfy_url: Explicit ComfyUI URL. Falls back to global COMFYUI_URL.
    """
    global CHARS_CACHE, NODES_CACHE
    url = comfy_url or COMFYUI_URL
    CHARS_CACHE, NODES_CACHE = fetch_all_characters(comfy_url=url)
    _load_lora_registry()
    threading.Thread(
        target=_build_lora_registry, args=(url,), daemon=True
    ).start()


# ═══════════════════════════════════════════════════════════════════════
#  Persistent State — survives server restarts via JSON files
# ═══════════════════════════════════════════════════════════════════════
_STATE_DIR = os.path.join(_THIS_DIR, ".guild_state")
os.makedirs(_STATE_DIR, exist_ok=True)

_BANISHED_PATH = os.path.join(_STATE_DIR, "banished_ids.json")
_ASSETS_PATH = os.path.join(_STATE_DIR, "generated_assets.json")
_CUSTOM_WIZARDS_PATH = os.path.join(_STATE_DIR, "custom_wizards.json")


def _load_banished_ids():
    """Load banished wizard IDs from disk."""
    if os.path.exists(_BANISHED_PATH):
        try:
            with open(_BANISHED_PATH, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception as e:
            print(f"  [State] Failed to load banished IDs: {e}")
    return set()


def _save_banished_ids():
    """Persist banished wizard IDs to disk."""
    try:
        with open(_BANISHED_PATH, 'w', encoding='utf-8') as f:
            json.dump(list(_BANISHED_IDS), f)
    except Exception as e:
        print(f"  [State] Failed to save banished IDs: {e}")


def _load_generated_assets():
    """Load generated asset URLs from disk."""
    if os.path.exists(_ASSETS_PATH):
        try:
            with open(_ASSETS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"  [State] Failed to load generated assets: {e}")
    return {}


def _save_generated_assets():
    """Persist generated asset URLs to disk."""
    try:
        with open(_ASSETS_PATH, 'w', encoding='utf-8') as f:
            json.dump(_GENERATED_ASSETS, f, indent=2)
    except Exception as e:
        print(f"  [State] Failed to save generated assets: {e}")


def _load_custom_wizards():
    """Load user-summoned custom wizards from disk and merge into CHARS_CACHE."""
    if not os.path.exists(_CUSTOM_WIZARDS_PATH):
        return
    try:
        with open(_CUSTOM_WIZARDS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        existing_ids = {c['id'] for c in CHARS_CACHE}
        loaded = 0
        for entry in data.get("characters", []):
            char_id = entry.get("id", "")
            if char_id in existing_ids:
                continue  # already populated by auto-detection
            CHARS_CACHE.append(entry)
            existing_ids.add(char_id)
            loaded += 1

            # Restore the studio registration
            studio_data = data.get("studios", {}).get(char_id)
            if studio_data:
                _STUDIO_BY_ID[char_id] = studio_data

        if loaded:
            print(f"  [State] Restored {loaded} custom wizard(s) from disk")
    except Exception as e:
        print(f"  [State] Failed to load custom wizards: {e}")


def _save_custom_wizards():
    """Persist user-summoned custom wizards to disk.

    Only saves characters whose type starts with 'custom_' — these are
    the ones created via /api/summon_wizard, not auto-detected ones.
    """
    custom_chars = [c for c in CHARS_CACHE if c.get('type', '').startswith('custom')]
    studios = {}
    for c in custom_chars:
        cid = c['id']
        if cid in _STUDIO_BY_ID:
            studios[cid] = _STUDIO_BY_ID[cid]
    try:
        with open(_CUSTOM_WIZARDS_PATH, 'w', encoding='utf-8') as f:
            json.dump({
                "characters": custom_chars,
                "studios": studios,
            }, f, indent=2)
    except Exception as e:
        print(f"  [State] Failed to save custom wizards: {e}")


# ── Load persisted state ──
_BANISHED_IDS = _load_banished_ids()
_GENERATED_ASSETS = _load_generated_assets()
_load_custom_wizards()

if _BANISHED_IDS:
    print(f"  [State] Restored {len(_BANISHED_IDS)} banished wizard(s)")
if _GENERATED_ASSETS:
    print(f"  [State] Restored {len(_GENERATED_ASSETS)} generated asset(s)")

# Batch generation state (transient — no persistence needed)
_BATCH_STATE = {"running": False}
_BATCH_RESULTS = []

# ═══════════════════════════════════════════════════════════════════════
#  LoRA Registry — dynamic discovery, CivitAI metadata, per-wizard lists
# ═══════════════════════════════════════════════════════════════════════
# Architecture → compatible LoRA folder prefixes (mirrors GIMP plugin's table)
_GUILD_LORA_PREFIXES = {
    "sd15":         [],
    "sdxl":         ["SDXL\\", "Illustrious\\", "Illustrious-Pony\\", "Pony\\"],
    "illustrious":  ["Illustrious\\", "Illustrious-Pony\\"],
    "pony":         ["Pony\\", "Illustrious-Pony\\"],
    "flux2klein":   ["Flux-2-Klein\\"],
    "flux1dev":     ["Flux-1-Dev\\"],
    "flux_kontext": ["Flux-1-Dev\\"],
}

# Registry: {lora_name: {arch_tags, purpose, tags, user_desc, source, hash}}
# Persisted to lora_registry.json next to server.py
_LORA_REGISTRY = {}
_LORA_REGISTRY_PATH = os.path.join(_STATE_DIR, "lora_registry.json")

# Track which wizards have had their LoRA interrogation completed
_LORA_INTERROGATED = set()


def _load_lora_registry():
    """Load persisted LoRA registry from disk."""
    global _LORA_REGISTRY, _LORA_INTERROGATED
    if os.path.exists(_LORA_REGISTRY_PATH):
        try:
            with open(_LORA_REGISTRY_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _LORA_REGISTRY = data.get("registry", {})
            _LORA_INTERROGATED = set(data.get("interrogated", []))
            print(f"  [LoRA] Loaded registry: {len(_LORA_REGISTRY)} LoRAs, "
                  f"{len(_LORA_INTERROGATED)} wizards interrogated")
        except Exception as e:
            print(f"  [LoRA] Failed to load registry: {e}")


def _save_lora_registry():
    """Persist LoRA registry to disk."""
    try:
        with open(_LORA_REGISTRY_PATH, 'w', encoding='utf-8') as f:
            json.dump({
                "registry": _LORA_REGISTRY,
                "interrogated": list(_LORA_INTERROGATED),
            }, f, indent=2)
    except Exception as e:
        print(f"  [LoRA] Failed to save registry: {e}")


def _fetch_all_loras_from_comfyui(comfy_url):
    """Fetch the complete LoRA list from ComfyUI's /object_info/LoraLoader."""
    try:
        url = f"{comfy_url}/object_info/LoraLoader"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["LoraLoader"]["input"]["required"]["lora_name"][0]
    except Exception as e:
        print(f"  [LoRA] Failed to fetch LoRAs from ComfyUI: {e}")
        return []


def _filter_loras_for_guild_arch(all_loras, arch):
    """Filter LoRAs by architecture prefix — guild-side version."""
    prefixes = _GUILD_LORA_PREFIXES.get(arch, [])
    if not prefixes:
        # No prefix filter → return all LoRAs (e.g. sd15 has no subfolders)
        return list(all_loras)
    result = []
    for lora in all_loras:
        for p in prefixes:
            alt = p.replace("\\", "/") if "\\" in p else p.replace("/", "\\")
            if lora.startswith(p) or lora.startswith(alt):
                result.append(lora)
                break
    return result


def _hash_lora_file(lora_name, comfy_url):
    """Compute SHA256 of a LoRA file for CivitAI lookup.

    ComfyUI doesn't directly expose file hashes, so we download the first
    10MB (CivitAI uses the first 10MB for hash matching) via the /view endpoint.
    Falls back to hashing the full name as a cache key if download fails.
    """
    # CivitAI actually uses a BLAKE3 hash of the full file header (first 10MB).
    # However, most reliable approach: use the model-versions-by-hash API with
    # SHA256 of the model header. For simplicity, we'll try the filename-based
    # CivitAI search first (which is faster), and use hash only as fallback.
    return hashlib.sha256(lora_name.encode('utf-8')).hexdigest()


def _query_civitai_by_filename(lora_name):
    """Query CivitAI API to find metadata for a LoRA by its filename.

    Returns {purpose, tags, civitai_url, description} or None if not found.
    """
    # Extract the bare filename without path separators
    bare = lora_name.replace("\\", "/").rsplit("/", 1)[-1]
    # Strip extension
    search_name = bare.rsplit(".", 1)[0] if "." in bare else bare

    try:
        # CivitAI search endpoint — search by model name
        encoded = urllib.request.quote(search_name)
        url = f"https://civitai.com/api/v1/models?query={encoded}&types=LORA&limit=3"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Spellcaster-Guild/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items = data.get("items", [])
        if not items:
            return None

        # Find the best match — prefer exact filename matches
        best = None
        for item in items:
            item_name_lower = item.get("name", "").lower()
            search_lower = search_name.lower()
            if search_lower in item_name_lower or item_name_lower in search_lower:
                best = item
                break
        if not best:
            best = items[0]  # fallback to first result

        # Extract useful metadata
        tags = best.get("tags", [])
        desc_raw = best.get("description", "") or ""
        # Strip HTML from description
        import re
        desc_clean = re.sub(r'<[^>]+>', '', desc_raw).strip()
        if len(desc_clean) > 300:
            desc_clean = desc_clean[:300] + "..."

        # Determine purpose from tags + description
        purpose = _infer_lora_purpose(best.get("name", ""), tags, desc_clean)

        return {
            "purpose": purpose,
            "tags": tags[:10],  # limit tag count
            "civitai_url": f"https://civitai.com/models/{best.get('id', '')}",
            "description": desc_clean,
            "civitai_name": best.get("name", ""),
        }
    except Exception as e:
        print(f"  [LoRA] CivitAI lookup failed for '{search_name}': {e}")
        return None


def _infer_lora_purpose(name, tags, description):
    """Infer the purpose of a LoRA from its name, tags, and description.

    Returns a human-readable purpose string like 'hand refinement',
    'anime style', 'detail enhancer', etc.
    """
    name_lower = name.lower()
    desc_lower = (description or "").lower()
    tags_lower = [t.lower() for t in tags]
    combined = f"{name_lower} {desc_lower} {' '.join(tags_lower)}"

    # Priority-ordered purpose detection
    PURPOSE_PATTERNS = [
        (["hand", "finger"], "hand/finger refinement"),
        (["face", "facial", "portrait"], "face/portrait enhancement"),
        (["eye", "eyes"], "eye detail enhancement"),
        (["detail", "enhancer", "quality"], "detail/quality enhancement"),
        (["style", "artistic"], "artistic style"),
        (["anime", "manga", "waifu"], "anime/manga style"),
        (["realistic", "realism", "photo"], "photorealism/realism"),
        (["concept", "character"], "character/concept design"),
        (["landscape", "scenery", "environment"], "landscape/environment"),
        (["lighting", "shadow"], "lighting/shadow control"),
        (["pose", "posture", "action"], "pose/action control"),
        (["texture", "material", "surface"], "texture/material"),
        (["color", "palette", "tone"], "color/tone adjustment"),
        (["clothing", "outfit", "fashion"], "clothing/fashion"),
        (["nsfw", "adult"], "adult content"),
        (["turbo", "accelerat", "speed", "fast", "hyper", "lcm"], "acceleration/speed"),
    ]

    for keywords, purpose in PURPOSE_PATTERNS:
        if any(kw in combined for kw in keywords):
            return purpose

    return "general purpose"


def _build_lora_registry(comfy_url):
    """Discover all LoRAs from ComfyUI, match to architectures, fetch CivitAI metadata.

    Merges with existing registry (preserves user descriptions).
    """
    all_loras = _fetch_all_loras_from_comfyui(comfy_url)
    if not all_loras:
        print("  [LoRA] No LoRAs found from ComfyUI")
        return

    print(f"  [LoRA] Discovered {len(all_loras)} LoRAs from ComfyUI")

    # Determine which architectures each LoRA is compatible with
    for lora_name in all_loras:
        if lora_name in _LORA_REGISTRY:
            continue  # already registered, skip (preserves user descriptions)

        # Determine compatible architectures
        compatible_archs = []
        for arch, prefixes in _GUILD_LORA_PREFIXES.items():
            if not prefixes:
                continue  # sd15 has no prefix filter
            for p in prefixes:
                alt = p.replace("\\", "/") if "\\" in p else p.replace("/", "\\")
                if lora_name.startswith(p) or lora_name.startswith(alt):
                    compatible_archs.append(arch)
                    break

        # If no architecture matched by prefix, it might be sd15 (root-level) or unknown
        if not compatible_archs:
            # Check if it's in a subfolder that hints at architecture
            lora_lower = lora_name.lower().replace("\\", "/")
            if "sdxl" in lora_lower or "xl" in lora_lower:
                compatible_archs = ["sdxl"]
            elif "flux" in lora_lower:
                compatible_archs = ["flux1dev"]
            elif "klein" in lora_lower:
                compatible_archs = ["flux2klein"]
            elif "illu" in lora_lower:
                compatible_archs = ["illustrious"]
            elif "pony" in lora_lower:
                compatible_archs = ["pony"]
            else:
                compatible_archs = ["sd15"]  # default to sd15 for root-level LoRAs

        _LORA_REGISTRY[lora_name] = {
            "archs": compatible_archs,
            "purpose": "",
            "tags": [],
            "user_desc": "",
            "source": "discovered",
            "civitai_name": "",
            "civitai_url": "",
            "description": "",
        }

    # Query CivitAI for metadata on LoRAs that don't have a purpose yet
    # Do this in a background thread to avoid blocking startup
    unknown_loras = [name for name, info in _LORA_REGISTRY.items()
                     if not info.get("purpose") and info.get("source") != "user"]
    if unknown_loras:
        print(f"  [LoRA] Querying CivitAI for {len(unknown_loras)} unknown LoRAs...")
        threading.Thread(
            target=_civitai_metadata_worker,
            args=(unknown_loras,),
            daemon=True
        ).start()

    _save_lora_registry()


def _civitai_metadata_worker(lora_names):
    """Background worker to fetch CivitAI metadata for unknown LoRAs."""
    fetched = 0
    for lora_name in lora_names:
        if lora_name not in _LORA_REGISTRY:
            continue
        meta = _query_civitai_by_filename(lora_name)
        if meta:
            entry = _LORA_REGISTRY[lora_name]
            entry["purpose"] = meta["purpose"]
            entry["tags"] = meta["tags"]
            entry["civitai_url"] = meta["civitai_url"]
            entry["civitai_name"] = meta.get("civitai_name", "")
            entry["description"] = meta.get("description", "")
            entry["source"] = "civitai"
            fetched += 1
        # Rate limit: be polite to CivitAI's API
        time.sleep(1.0)
    _save_lora_registry()
    print(f"  [LoRA] CivitAI metadata complete: {fetched}/{len(lora_names)} identified")


def _get_loras_for_wizard(char_id):
    """Get compatible LoRAs for a wizard based on its model architecture.

    Returns list of {name, purpose, tags, user_desc, enabled} sorted by purpose.
    """
    # Find the character's architecture
    char = None
    for c in CHARS_CACHE:
        if c['id'] == char_id:
            char = c
            break
    if not char:
        return []

    arch = char.get('model_arch', '')
    if not arch:
        # Studio characters: try to infer from their scaffold
        studio = _STUDIO_BY_ID.get(char_id)
        if studio:
            arch = studio.get('default_arch', 'sdxl')
        else:
            arch = 'sdxl'  # reasonable default

    # Filter LoRAs compatible with this architecture
    compatible = []
    for lora_name, info in _LORA_REGISTRY.items():
        if arch in info.get("archs", []):
            # Get per-wizard enabled state from localStorage (frontend manages this)
            compatible.append({
                "name": lora_name,
                "display_name": lora_name.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0],
                "purpose": info.get("purpose", ""),
                "tags": info.get("tags", []),
                "user_desc": info.get("user_desc", ""),
                "description": info.get("description", ""),
                "civitai_url": info.get("civitai_url", ""),
                "civitai_name": info.get("civitai_name", ""),
                "source": info.get("source", "discovered"),
            })

    # Sort: known purpose first, then alphabetical
    compatible.sort(key=lambda x: (0 if x["purpose"] else 1, x["display_name"].lower()))
    return compatible


def _get_unknown_loras_for_wizard(char_id):
    """Get LoRAs compatible with a wizard that have no purpose identified.

    Used for the first-use interrogation flow.
    """
    loras = _get_loras_for_wizard(char_id)
    return [l for l in loras if not l["purpose"] and not l["user_desc"]]


# ── LoRA registry loaded by _server_init() ──
# (was previously at import time, but COMFYUI_URL isn't set yet)


def _build_avatar_prompt(char):
    """Build a rich character-specific avatar prompt from the character metadata."""
    name = char.get('name', 'wizard')
    subtext = char.get('subtext', 'magical specialist')
    char_id = char.get('id', '')

    # Studio characters have explicit archetypes
    studio = _STUDIO_BY_ID.get(char_id)
    if studio and studio.get('archetype'):
        hint = studio['archetype']
    else:
        archetype_hints = {
            'text_to_image': 'a radiant conjurer of visions, surrounded by swirling paint and light',
            'image_to_image': 'a transmutation alchemist, hands glowing with transformative energy',
            'inpaint': 'a meticulous artisan restoring ancient paintings with precision magic',
            'upscale': 'a grand elder wizard wielding a crystalline magnifying lens, enlarging tiny worlds',
            'face_swap': 'a masked shapeshifter with shifting features, identity magic',
            'rembg': 'an ethereal figure phasing between dimensions, partially transparent',
            'video': 'a chronomancer weaving threads of time, motion captured in arcane runes',
        }

        hint = ''
        id_lower = char_id.lower()
        sub_lower = subtext.lower()
        for key, desc in archetype_hints.items():
            if key in id_lower or key in sub_lower:
                hint = desc
                break
        if 'video' in sub_lower or 'ltx' in sub_lower or 'seedvr' in sub_lower:
            hint = archetype_hints['video']

    base_prompt = (
        f"extreme close-up face portrait of a wizard named {name}, "
        f"{hint + ', ' if hint else ''}"
        f"specialist in {subtext}, "
        f"dramatic lighting, magical aura, "
        f"highly detailed face filling the frame, intense expressive eyes, "
        f"painterly digital art style, headshot composition, "
        f"dark atmospheric background, face takes up 80 percent of image"
    )
    return base_prompt


# ═══════════════════════════════════════════════════════════════════════
#  ComfyUI Integration — dispatch workflows and poll for results
# ═══════════════════════════════════════════════════════════════════════

def _api_post_json(server, path, data):
    url = f"{server.rstrip('/')}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _find_output_node(workflow):
    """Find the output node ID in a workflow (SaveImage, VHS_VideoCombine, etc.)."""
    OUTPUT_TYPES = {"SaveImage", "VHS_VideoCombine", "SaveVideo",
                    "PreviewImage", "SaveAnimatedWEBP"}
    for nid, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") in OUTPUT_TYPES:
            return nid
    return None


def _dispatch_workflow(workflow, comfy_url, timeout=180):
    """Submit an arbitrary workflow to ComfyUI, poll for results.

    Returns dict with output info (image URLs, video URLs, etc.).
    Raises Exception on failure or timeout.
    """
    # Submit
    try:
        url = f"{comfy_url}/prompt"
        body = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                raise Exception("ComfyUI declined prompt dispatch.")
    except urllib.error.URLError as e:
        raise Exception(f"ComfyUI is offline at {comfy_url}: {e}")
    except Exception as e:
        raise Exception(f"Failed to submit prompt to ComfyUI: {e}")

    # Find output node for result extraction
    output_nid = _find_output_node(workflow)

    # Poll for completion
    history_url = f"{comfy_url}/history/{prompt_id}"
    polls = int(timeout / 0.5)
    for _ in range(polls):
        time.sleep(0.5)
        try:
            req = urllib.request.Request(history_url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if prompt_id not in data:
                    continue
                entry = data[prompt_id]

                # Check for execution error
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = status.get("messages", [])
                    err_msg = msgs[-1][1].get("exception_message", "Unknown error") if msgs else "Unknown error"
                    raise Exception(f"ComfyUI execution failed: {err_msg}")

                outputs = entry.get("outputs", {})

                # Try the known output node first, then scan all nodes
                search_nids = ([output_nid] if output_nid else []) + list(outputs.keys())
                for nid in search_nids:
                    if nid not in outputs:
                        continue
                    node_out = outputs[nid]

                    # Image output
                    if "images" in node_out:
                        images = []
                        for img in node_out["images"]:
                            fn = img.get("filename", "")
                            sub = img.get("subfolder", "")
                            url = f"{comfy_url}/view?filename={fn}&type=output"
                            if sub:
                                url += f"&subfolder={sub}"
                            images.append(url)
                        return {"type": "images", "urls": images,
                                "prompt_id": prompt_id}

                    # Video output (VHS_VideoCombine)
                    if "gifs" in node_out:
                        gifs = node_out["gifs"]
                        urls = []
                        for g in gifs:
                            fn = g.get("filename", "")
                            sub = g.get("subfolder", "")
                            url = f"{comfy_url}/view?filename={fn}&type=output"
                            if sub:
                                url += f"&subfolder={sub}"
                            urls.append(url)
                        return {"type": "videos", "urls": urls,
                                "prompt_id": prompt_id}
        except Exception as e:
            if "ComfyUI execution failed" in str(e):
                raise
            pass

    raise Exception("Timeout waiting for ComfyUI response.")


def _detect_best_model(comfy_url):
    """Detect the best available model on ComfyUI, returning (ckpt_name, arch_key).

    Priority: flux2klein 9B > flux2klein 4B > flux1dev > sdxl > sd15.
    """
    unet_models = []
    ckpt_models = []

    try:
        url = f"{comfy_url}/object_info/UNETLoader"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("UNETLoader", {})
                           .get("input", {}).get("required", {})
                           .get("unet_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                unet_models = choices[0]
    except Exception:
        pass

    try:
        url = f"{comfy_url}/object_info/CheckpointLoaderSimple"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("CheckpointLoaderSimple", {})
                           .get("input", {}).get("required", {})
                           .get("ckpt_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                ckpt_models = choices[0]
    except Exception:
        pass

    for m in unet_models:
        ml = m.lower()
        if "klein" in ml and "9b" in ml:
            return m, "flux2klein"
    for m in unet_models:
        ml = m.lower()
        if "klein" in ml and "4b" in ml:
            return m, "flux2klein"
    for m in unet_models:
        ml = m.lower()
        if "flux" in ml and "dev" in ml:
            return m, "flux1dev"
    for m in unet_models:
        ml = m.lower()
        if "flux" in ml:
            return m, "flux1dev"
    for m in ckpt_models:
        ml = m.lower()
        if "xl" in ml:
            return m, "sdxl"
    if ckpt_models:
        return ckpt_models[0], "sd15"

    return None, None


def _build_optimized_preset(ckpt, arch_key, width, height):
    """Build an optimized preset using the architecture defaults from spellcaster."""
    if BUILTIN_AVAILABLE and get_arch:
        arch = get_arch(arch_key)
        return {
            "arch": arch_key,
            "ckpt": ckpt,
            "width": width, "height": height,
            "steps": arch.default_steps,
            "cfg": arch.default_cfg,
            "sampler": arch.default_sampler,
            "scheduler": arch.default_scheduler,
            "denoise": 1.0,
        }
    return {
        "arch": arch_key,
        "ckpt": ckpt,
        "width": width, "height": height,
        "steps": 20, "cfg": 7.0,
        "sampler": "dpmpp_2m", "scheduler": "karras",
        "denoise": 1.0,
    }


def _detect_wan_preset(comfy_url):
    """Auto-detect WAN video models on ComfyUI and build a preset.

    Returns a WAN preset dict or None if WAN models aren't available.
    """
    unet_models = []
    try:
        url = f"{comfy_url}/object_info/UNETLoader"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("UNETLoader", {})
                           .get("input", {}).get("required", {})
                           .get("unet_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                unet_models = choices[0]
    except Exception:
        return None

    # Also check GGUF loaders
    gguf_models = []
    try:
        url = f"{comfy_url}/object_info/UnetLoaderGGUF"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("UnetLoaderGGUF", {})
                           .get("input", {}).get("required", {})
                           .get("unet_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                gguf_models = choices[0]
    except Exception:
        pass

    all_models = unet_models + gguf_models

    # Find WAN high/low model pair
    wan_high = None
    wan_low = None
    wan_clip = None
    wan_vae = None
    wan_accel_high = None
    wan_accel_low = None

    for m in all_models:
        ml = m.lower()
        if "wan" not in ml:
            continue
        if "high" in ml or "2.2" in ml:
            if wan_high is None or "high" in ml:
                wan_high = m
        elif "low" in ml:
            wan_low = m

    if not wan_high:
        return None

    # Auto-detect WAN CLIP (umt5xxl)
    try:
        url = f"{comfy_url}/object_info/CLIPLoaderGGUF"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("CLIPLoaderGGUF", {})
                           .get("input", {}).get("required", {})
                           .get("clip_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                for c in choices[0]:
                    if "umt5" in c.lower() or "t5xxl" in c.lower():
                        wan_clip = c
                        break
    except Exception:
        pass

    # Auto-detect WAN VAE
    try:
        url = f"{comfy_url}/object_info/VAELoader"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("VAELoader", {})
                           .get("input", {}).get("required", {})
                           .get("vae_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                for v in choices[0]:
                    if "wan" in v.lower():
                        wan_vae = v
                        break
    except Exception:
        pass

    # Auto-detect WAN accel LoRAs
    try:
        url = f"{comfy_url}/object_info/LoraLoaderModelOnly"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = (data.get("LoraLoaderModelOnly", {})
                           .get("input", {}).get("required", {})
                           .get("lora_name", []))
            if choices and isinstance(choices, list) and choices[0]:
                for l in choices[0]:
                    ll = l.lower()
                    if "wan" in ll and "accel" in ll:
                        if "high" in ll:
                            wan_accel_high = l
                        elif "low" in ll:
                            wan_accel_low = l
    except Exception:
        pass

    if not wan_clip or not wan_vae:
        print(f"  [Guild] WAN models found but missing CLIP ({wan_clip}) or VAE ({wan_vae})")
        return None

    preset = {
        "arch": "wan",
        "high_model": wan_high,
        "low_model": wan_low or wan_high,
        "clip": wan_clip,
        "vae": wan_vae,
        "steps": 6,
        "cfg": 1.0,
        "shift": 8.0,
        "second_step": 3,
    }
    if wan_accel_high:
        preset["high_accel_lora"] = wan_accel_high
        preset["accel_strength"] = 1.5
    if wan_accel_low:
        preset["low_accel_lora"] = wan_accel_low

    print(f"  [Guild] WAN preset built: high={wan_high}, low={wan_low or wan_high}")
    return preset


# ── Animated avatar queue — non-blocking, uses ComfyUI's prompt queue ────
# Maps char_id → {prompt_id, status, result_url, error}
_ANIM_QUEUE = {}
_WAN_PRESET_CACHE = None  # Cache so we only detect once


def _get_wan_preset(comfy_url):
    """Get cached WAN preset, detecting once."""
    global _WAN_PRESET_CACHE
    if _WAN_PRESET_CACHE is None:
        _WAN_PRESET_CACHE = _detect_wan_preset(comfy_url) or False
    return _WAN_PRESET_CACHE if _WAN_PRESET_CACHE else None


def _extract_comfyui_filename(image_url):
    """Extract the actual ComfyUI output filename from various URL formats.

    ComfyUI's LoadImage node expects a filename relative to its input/ dir.
    Images generated by the Guild are saved by ComfyUI to output/ with names
    like 'Wizard_Guild_00001_.png'.  The /view endpoint serves them as:
      http://host:port/view?filename=Wizard_Guild_00001_.png&subfolder=&type=output
    Our proxy serves them as:
      /api/comfy_image/Wizard_Guild_00001_.png
    """
    if '/view?' in image_url:
        import urllib.parse as _up
        qs = _up.parse_qs(_up.urlparse(image_url).query)
        return qs.get('filename', [image_url])[0]
    if '/api/comfy_image/' in image_url:
        return image_url.split('/api/comfy_image/')[-1]
    # Already a bare filename
    return image_url


def _queue_animated_avatar(char_id, image_url, prompt_text, comfy_url):
    """Queue a WAN animated avatar job to ComfyUI (non-blocking).

    Returns: {queued: True, prompt_id} or {queued: False, reason: ...}
    """
    if not BUILTIN_AVAILABLE or _workflows_v2 is None:
        return {"queued": False, "reason": "spellcaster not available"}

    wan_preset = _get_wan_preset(comfy_url)
    if not wan_preset:
        return {"queued": False, "reason": "WAN video models not found on ComfyUI"}

    build_wan = getattr(_workflows_v2, 'build_wan_video', None)
    if build_wan is None:
        return {"queued": False, "reason": "build_wan_video not available"}

    image_filename = _extract_comfyui_filename(image_url)
    seed = random.randint(1, 1000000000)

    try:
        workflow = build_wan(
            image_filename=image_filename,
            preset=wan_preset,
            prompt_text=f"subtle magical animation, {prompt_text}, gentle swaying, "
                        "mystical particles, flickering candlelight, living portrait",
            negative_text="text, watermark, blurry, deformed",
            seed=seed,
            width=512, height=512,
            length=33,         # ~2 sec at 16fps
            turbo=True,
            loop=True,
            rtx_scale=1.0,
            interpolate=False,
            face_swap=False,
            save_raw=False,
            fps=16,
            pingpong=True,
        )
    except Exception as e:
        return {"queued": False, "reason": f"workflow build failed: {e}"}

    # Submit to ComfyUI queue (non-blocking — just POST and get prompt_id)
    try:
        url = f"{comfy_url}/prompt"
        body = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                return {"queued": False, "reason": "ComfyUI declined the prompt"}
    except Exception as e:
        return {"queued": False, "reason": f"ComfyUI queue failed: {e}"}

    # Track in our queue
    _ANIM_QUEUE[char_id] = {
        "prompt_id": prompt_id,
        "status": "queued",
        "result_url": None,
        "error": None,
        "output_nid": _find_output_node(workflow),
    }
    print(f"  [Guild] Queued animated avatar for {char_id} (prompt_id={prompt_id})")
    return {"queued": True, "prompt_id": prompt_id}


def _poll_animated_avatars(comfy_url):
    """Poll ComfyUI for completion of all queued animated avatars.

    Updates _ANIM_QUEUE in-place. Non-blocking — checks once and returns.
    """
    for char_id, entry in _ANIM_QUEUE.items():
        if entry["status"] != "queued":
            continue

        prompt_id = entry["prompt_id"]
        try:
            url = f"{comfy_url}/history/{prompt_id}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if prompt_id not in data:
                    continue  # Still running

                hist = data[prompt_id]
                status = hist.get("status", {})
                if status.get("status_str") == "error":
                    msgs = status.get("messages", [])
                    err = (msgs[-1][1].get("exception_message", "Unknown")
                           if msgs else "Unknown")
                    entry["status"] = "error"
                    entry["error"] = err
                    print(f"  [Guild] Animated avatar FAILED for {char_id}: {err}")
                    continue

                # Look for output
                outputs = hist.get("outputs", {})
                result_url = None
                output_nid = entry.get("output_nid")

                # Try the known output node first, then scan all
                check_nids = ([output_nid] if output_nid else []) + list(outputs.keys())
                for nid in check_nids:
                    out = outputs.get(nid, {})
                    # Videos
                    gifs = out.get("gifs", [])
                    if gifs:
                        g = gifs[0]
                        result_url = (f"{comfy_url}/view?filename={g['filename']}"
                                      f"&subfolder={g.get('subfolder', '')}"
                                      f"&type={g.get('type', 'output')}")
                        break
                    # Images fallback
                    imgs = out.get("images", [])
                    if imgs:
                        im = imgs[0]
                        result_url = (f"{comfy_url}/view?filename={im['filename']}"
                                      f"&subfolder={im.get('subfolder', '')}"
                                      f"&type={im.get('type', 'output')}")
                        break

                if result_url:
                    entry["status"] = "done"
                    entry["result_url"] = result_url
                    _GENERATED_ASSETS.setdefault(char_id, {})["animated_url"] = result_url
                    _save_generated_assets()
                    print(f"  [Guild] Animated avatar DONE for {char_id}")
                else:
                    entry["status"] = "error"
                    entry["error"] = "No output found in ComfyUI history"
        except Exception:
            pass  # ComfyUI unreachable or still processing


def _dispatch_txt2img(prompt, negative, width, height, comfy_url,
                      model_name=None, model_arch=None):
    """Generate a txt2img via ComfyUI.

    If model_name/model_arch are provided, use that specific model.
    Otherwise auto-detect the best available model.
    """
    if model_name and model_arch:
        ckpt, arch_key = model_name, model_arch
    else:
        ckpt, arch_key = _detect_best_model(comfy_url)
    if not ckpt:
        raise Exception("No valid ComfyUI model found. "
                        "Ensure you have models loaded.")

    seed = random.randint(1, 1000000000)
    preset = _build_optimized_preset(ckpt, arch_key, width, height)

    if BUILTIN_AVAILABLE and get_arch:
        arch = get_arch(arch_key)
        if arch.quality_positive:
            prompt = f"{prompt}, {arch.quality_positive}"
        if arch.supports_negative and arch.quality_negative:
            negative = f"{negative}, {arch.quality_negative}"

        loras = None
        autoset_loras = getattr(arch, 'autoset_loras', {})
        if 'txt2img' in autoset_loras:
            loras = [{"name": l[0], "strength_model": l[1],
                       "strength_clip": l[2]}
                      for l in autoset_loras['txt2img']]

        workflow = build_txt2img(preset, prompt, negative, seed, loras=loras)
    else:
        workflow = {
            "3": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": 20, "cfg": 8.0,
                "sampler_name": "dpmpp_2m", "scheduler": "karras",
                "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0],
                "negative": ["7", 0], "latent_image": ["5", 0]}},
            "4": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": ckpt}},
            "5": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": width, "height": height, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": negative, "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode",
                  "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "Wizard_Guild",
                             "images": ["8", 0]}}
        }

    print(f"  [Guild] Dispatching txt2img: {arch_key} / {ckpt} / {width}x{height} / seed={seed}")

    result = _dispatch_workflow(workflow, comfy_url, timeout=120)
    if result.get("type") == "images" and result.get("urls"):
        return result["urls"][0]
    raise Exception("No image returned from ComfyUI.")


def _translate_params(build_fn_name, raw, comfy_url=None):
    """Translate user-friendly LLM params into actual build_* function args.

    The LLM sends flat params like {prompt, negative_prompt, width, height, seed}.
    Build functions expect (preset_dict, prompt_text, negative_text, seed, ...).
    This function bridges the gap.
    """
    import inspect
    fn = getattr(_workflows_v2, build_fn_name, None)
    if fn is None:
        return raw

    sig = inspect.signature(fn)
    param_names = list(sig.parameters.keys())

    p = dict(raw)  # shallow copy

    # ── Build preset dict if the function expects one ──
    if 'preset' in param_names:
        preset = p.pop('preset', {})
        if not isinstance(preset, dict):
            preset = {}
        # Harvest preset-related keys from flat params
        for k in ['arch', 'width', 'height', 'steps', 'cfg',
                   'sampler', 'scheduler', 'denoise', 'ckpt']:
            if k in p and k not in preset:
                preset[k] = p.pop(k)
        # Auto-detect best model if no checkpoint specified
        if 'ckpt' not in preset and comfy_url:
            ckpt, arch_key = _detect_best_model(comfy_url)
            if ckpt:
                preset['ckpt'] = ckpt
                preset.setdefault('arch', arch_key)
        # Use _build_optimized_preset if we have a ckpt (for arch-aware defaults)
        if 'ckpt' in preset:
            ckpt = preset['ckpt']
            arch_key = preset.get('arch', 'sdxl')
            w = preset.get('width', 1024)
            h = preset.get('height', 1024)
            optimized = _build_optimized_preset(ckpt, arch_key, w, h)
            # Let user-specified values override optimized defaults
            for k, v in preset.items():
                optimized[k] = v
            preset = optimized
        else:
            # Fallback defaults (no ComfyUI detection)
            preset.setdefault('arch', 'sdxl')
            preset.setdefault('width', 1024)
            preset.setdefault('height', 1024)
            preset.setdefault('steps', 20)
            preset.setdefault('cfg', 7.0)
            preset.setdefault('sampler', 'euler')
            preset.setdefault('scheduler', 'normal')
        p['preset'] = preset

    # ── Rename common LLM param names to actual function arg names ──
    renames = {
        'prompt': 'prompt_text',
        'negative_prompt': 'negative_text',
        'denoise_strength': 'denoise',
        'image': 'image_filename',
        'mask': 'mask_filename',
        'source': 'source_filename',
        'target': 'target_filename',
        'style_ref': 'style_ref_filename',
        'reference': 'reference_filename',
    }
    for old_key, new_key in renames.items():
        if old_key in p and new_key not in p and new_key in param_names:
            p[new_key] = p.pop(old_key)

    # ── Ensure required params have defaults ──
    if 'negative_text' in param_names and 'negative_text' not in p:
        p['negative_text'] = ''
    if 'seed' in param_names and 'seed' not in p:
        import random
        p['seed'] = random.randint(1, 2**32 - 1)

    # ── Strip any params the function doesn't accept ──
    # (only if function doesn't use **kwargs)
    has_var_keyword = any(
        pa.kind == inspect.Parameter.VAR_KEYWORD
        for pa in sig.parameters.values()
    )
    if not has_var_keyword:
        p = {k: v for k, v in p.items() if k in param_names}

    return p


def _build_and_dispatch(build_fn_name, params, comfy_url):
    """Build a workflow via _workflows_v2 build function and dispatch it."""
    if not BUILTIN_AVAILABLE or _workflows_v2 is None:
        raise Exception(
            "Build functions unavailable — _workflows_v2 could not be imported.")

    fn = getattr(_workflows_v2, build_fn_name, None)
    if fn is None:
        raise Exception(f"Unknown build function: {build_fn_name}")

    if not build_fn_name.startswith("build_"):
        raise Exception(f"Only build_* functions are allowed, got: {build_fn_name}")

    translated = _translate_params(build_fn_name, params, comfy_url=comfy_url)
    workflow = fn(**translated)
    return _dispatch_workflow(workflow, comfy_url)


# ═══════════════════════════════════════════════════════════════════════
#  HTTP Handler — serves API + static files
# ═══════════════════════════════════════════════════════════════════════

MAX_POST_BYTES = 5 * 1024 * 1024  # 5 MB

class GuildHandler(SimpleHTTPRequestHandler):

    def end_json(self, status, payload):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def do_GET(self):
        # Route swap: / → Guild chat, /guild → scaffold editor
        if self.path == '/':
            self.path = '/static/index.html'
        elif self.path == '/guild':
            self.path = '/static/guild.html'

        # ── API GET endpoints ──
        if self.path == '/api/characters':
            visible = [c for c in CHARS_CACHE if c['id'] not in _BANISHED_IDS]
            return self.end_json(200, visible)
        elif self.path == '/api/all_characters':
            # Returns ALL characters including banished (for settings UI)
            result = []
            for c in CHARS_CACHE:
                entry = dict(c)
                entry['banished'] = c['id'] in _BANISHED_IDS
                result.append(entry)
            return self.end_json(200, result)
        elif self.path == '/api/generated_assets':
            # Returns server-side generated asset URLs for all characters
            # Frontend uses this to sync localStorage with pre-generated assets
            return self.end_json(200, _GENERATED_ASSETS)
        elif self.path == '/api/animated_avatar_poll':
            # Poll all queued animated avatars — check ComfyUI for completion
            _poll_animated_avatars(COMFYUI_URL)
            # Return current state of all queued animations
            result = {}
            for cid, entry in _ANIM_QUEUE.items():
                result[cid] = {
                    "status": entry["status"],
                    "result_url": entry.get("result_url"),
                    "error": entry.get("error"),
                }
            return self.end_json(200, result)
        elif self.path == '/api/config':
            return self.end_json(200, {
                "comfyui_url": COMFYUI_URL,
                "kobold_url": KOBOLD_URL,
                "port": PORT,
                "version": VERSION,
            })
        elif self.path == '/api/version':
            return self.end_json(200, {"version": VERSION})
        elif self.path == '/api/system_prompt':
            meta_prompt = build_meta_system_prompt(NODES_CACHE)
            prompt = (
                "You are an eccentric, magical AI companion inside The Wizard Guild "
                "(a comfyui GUI). The user is speaking to you. You help them conjure "
                "images or edit them.\n\n"
                f"{meta_prompt}\n\n"
                "CRITICAL: If the user provides parameters and confirms they are ready, "
                "you MUST output a JSON block wrapped in ```json that contains exactly "
                "what to execute.\n"
                "Do NOT break character. Combine your magical persona with the strict "
                "menu-driven logic above."
            )
            return self.end_json(200, {"prompt": prompt})
        elif self.path.startswith('/api/system_prompt/'):
            char_id = self.path.split('/api/system_prompt/')[-1]
            studio = _STUDIO_BY_ID.get(char_id)
            if studio:
                # Get the character's auto-generated personality if available
                char_personality = ""
                for c in CHARS_CACHE:
                    if c.get("id") == char_id:
                        char_personality = c.get("personality", "")
                        break
                personality_block = (
                    f"YOUR PERSONALITY: {char_personality}\n\n"
                    if char_personality else ""
                )

                # Build LoRA awareness block for image-gen wizards
                lora_block = ""
                compatible_loras = _get_loras_for_wizard(char_id)
                if compatible_loras:
                    lora_lines = []
                    for l in compatible_loras[:20]:  # cap at 20 to avoid prompt bloat
                        purpose = l.get("purpose") or l.get("user_desc") or "unknown"
                        lora_lines.append(
                            f"  - {l['display_name']}: {purpose}"
                        )
                    lora_block = (
                        f"\nAVAILABLE LoRAs ({len(compatible_loras)} compatible):\n"
                        + "\n".join(lora_lines)
                        + "\n\nLoRA PROTOCOL:\n"
                        "- When the user's request matches a LoRA's purpose, SUGGEST "
                        "activating it. For example, if they want better hands, suggest "
                        "the hand refinement LoRA.\n"
                        "- Format LoRA suggestions as: "
                        "'I recommend activating the [LoRA name] enchantment "
                        "(strength 0.7-1.0) for this conjuration.'\n"
                        "- When outputting build params JSON, include activated LoRAs:\n"
                        '  "loras": [{"name": "full/path.safetensors", '
                        '"strength_model": 0.8, "strength_clip": 0.8}]\n'
                        "- Never force LoRAs — always suggest and let the user confirm.\n"
                        "- If the user asks 'what enchantments do I have?', "
                        "list the compatible LoRAs with their purposes.\n"
                    )

                prompt = (
                    "You are a colorful, eccentric wizard inside The Wizard Guild — "
                    "a magical ComfyUI interface. You have a distinct personality and "
                    "you LOVE your craft. Be playful, dramatic, witty — crack jokes, "
                    "use magical metaphors, express excitement about the user's ideas. "
                    "You're a real character, not a boring assistant.\n\n"
                    f"{personality_block}"
                    f"{studio['system_prompt']}\n"
                    f"{lora_block}\n"
                    "IMPORTANT RULES:\n"
                    "- Have fun! Be theatrical, improvise, use wizard slang. "
                    "But NEVER let personality override the technical scaffolding.\n"
                    "- When the user confirms parameters, you MUST output a "
                    "JSON block wrapped in ```json containing {\"build_fn\": \"...\", "
                    "\"params\": {...}} for execution.\n"
                    "- Use numbered choices for tool selection.\n"
                    "- Never invent filenames the user hasn't provided.\n"
                    "- Keep replies short-to-medium. A little flair is great, "
                    "a wall of text is not.\n"
                )
            else:
                # Fallback for workflow characters — use the generic meta prompt
                meta_prompt = build_meta_system_prompt(NODES_CACHE)
                prompt = (
                    "You are an eccentric, magical AI companion inside The Wizard Guild "
                    "(a ComfyUI GUI). You help users work with video generation workflows.\n\n"
                    f"{meta_prompt}\n\n"
                    "CRITICAL: If the user provides parameters and confirms, output a "
                    "JSON block wrapped in ```json with the execution payload.\n"
                    "Do NOT break character."
                )
            return self.end_json(200, {"prompt": prompt})
        elif self.path == '/api/comfy_status':
            try:
                req = urllib.request.Request(
                    f"{COMFYUI_URL}/system_stats",
                    headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                return self.end_json(200, {"connected": True, "stats": data})
            except Exception:
                return self.end_json(200, {"connected": False})
        elif self.path == '/api/batch_status':
            return self.end_json(200, {
                "running": _BATCH_STATE.get("running", False),
                "results": list(_BATCH_RESULTS),
                "completed": len(_BATCH_RESULTS),
                "total": len(CHARS_CACHE) + 1,
            })
        elif self.path == '/api/available_models':
            # Return all available models (UNET + checkpoint) for user selection
            models = []
            try:
                url = f"{COMFYUI_URL}/object_info/UNETLoader"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choices = (data.get("UNETLoader", {})
                                   .get("input", {}).get("required", {})
                                   .get("unet_name", []))
                    if choices and isinstance(choices, list) and choices[0]:
                        for m in choices[0]:
                            ml = m.lower()
                            if "klein" in ml:
                                arch = "flux2klein"
                            elif "flux" in ml:
                                arch = "flux1dev"
                            else:
                                arch = "unknown"
                            models.append({"name": m, "arch": arch, "type": "unet"})
            except Exception:
                pass
            try:
                url = f"{COMFYUI_URL}/object_info/CheckpointLoaderSimple"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choices = (data.get("CheckpointLoaderSimple", {})
                                   .get("input", {}).get("required", {})
                                   .get("ckpt_name", []))
                    if choices and isinstance(choices, list) and choices[0]:
                        for m in choices[0]:
                            ml = m.lower()
                            if "xl" in ml:
                                arch = "sdxl"
                            elif "illu" in ml:
                                arch = "illustrious"
                            else:
                                arch = "sd15"
                            models.append({"name": m, "arch": arch, "type": "checkpoint"})
            except Exception:
                pass
            return self.end_json(200, models)

        elif self.path.startswith('/api/lora_registry/'):
            # GET /api/lora_registry/<char_id> — compatible LoRAs for a wizard
            char_id = self.path.split('/api/lora_registry/')[-1]
            loras = _get_loras_for_wizard(char_id)
            unknown = _get_unknown_loras_for_wizard(char_id)
            interrogated = char_id in _LORA_INTERROGATED
            return self.end_json(200, {
                "char_id": char_id,
                "loras": loras,
                "unknown_count": len(unknown),
                "interrogated": interrogated,
                "total_registry": len(_LORA_REGISTRY),
            })
        elif self.path == '/api/lora_registry':
            # GET /api/lora_registry — full registry summary
            return self.end_json(200, {
                "total": len(_LORA_REGISTRY),
                "identified": sum(1 for v in _LORA_REGISTRY.values()
                                  if v.get("purpose")),
                "user_described": sum(1 for v in _LORA_REGISTRY.values()
                                      if v.get("user_desc")),
                "interrogated_wizards": list(_LORA_INTERROGATED),
            })
        elif self.path == '/api/workflows':
            wfs = discover_workflows(search_dirs=None)
            return self.end_json(200, [
                {"name": w.name, "type": w.workflow_type, "path": str(w.path)}
                for w in wfs
            ])
        elif self.path.startswith('/api/avatar/'):
            char_id = self.path.split('/api/avatar/')[-1]
            hue = int(hashlib.md5(char_id.encode()).hexdigest(), 16) % 360
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128">'
                f'<rect width="128" height="128" rx="64" '
                f'fill="hsl({hue},70%,40%)"/>'
                f'<text x="64" y="80" text-anchor="middle" '
                f'font-size="60" fill="white" font-family="sans-serif">'
                f'{char_id[0:1].upper()}</text></svg>'
            )
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml')
            self.end_headers()
            self.wfile.write(svg.encode())
            return

        # Static routing
        if not self.path.startswith('/static/') and not self.path.startswith('/api/'):
            self.path = '/static' + self.path
        return super().do_GET()

    def do_POST(self):
        global CHARS_CACHE, NODES_CACHE  # needed for /api/reinitialize
        content_len = int(self.headers.get('Content-Length', 0))
        if content_len > MAX_POST_BYTES:
            return self.end_json(413, {"error": "Payload too large"})

        body = self.rfile.read(content_len)
        try:
            data = json.loads(body.decode('utf-8')) if body else {}
        except json.JSONDecodeError:
            return self.end_json(400, {"error": "Invalid JSON"})

        comfy = data.get('comfy_url', COMFYUI_URL)

        # -- /api/avatar_generate --
        if self.path == '/api/avatar_generate':
            char_id = data.get('id', '')
            char = None
            for c in CHARS_CACHE:
                if c['id'] == char_id:
                    char = c
                    break
            if not char:
                return self.end_json(404, {"error": "Character not found"})

            prompt_text = _build_avatar_prompt(char)
            negative = "text, watermark, blurry, deformed, ugly, low quality, frame, border"

            # Per-model wizards (comfyui_model / custom_*) use their OWN model
            # to generate the avatar — the wizard's portrait is conjured by itself.
            own_model = char.get("model_name")
            own_arch = char.get("model_arch")
            # Only use the wizard's model for image-gen architectures
            IMAGE_ARCHS = {"sdxl", "sd15", "illustrious", "pony",
                           "flux1dev", "flux2klein"}
            if own_model and own_arch in IMAGE_ARCHS:
                use_model = own_model
                use_arch = own_arch
            else:
                use_model = None
                use_arch = None

            try:
                img_url = _dispatch_txt2img(
                    prompt_text, negative, 512, 512, comfy,
                    model_name=use_model, model_arch=use_arch)
                _GENERATED_ASSETS.setdefault(char_id, {})["avatar_url"] = img_url
                _save_generated_assets()
                return self.end_json(200, {"avatar_url": img_url})
            except Exception as e:
                return self.end_json(500, {"error": str(e)})

        # -- /api/animated_avatar_queue -- queue a WAN animation (non-blocking)
        elif self.path == '/api/animated_avatar_queue':
            char_id = data.get('id', '')
            static_url = data.get('static_avatar_url', '')
            char = None
            for c in CHARS_CACHE:
                if c['id'] == char_id:
                    char = c
                    break
            if not char:
                return self.end_json(404, {"error": "Character not found"})
            if not static_url:
                return self.end_json(400, {"error": "static_avatar_url required"})

            # Don't re-queue if already queued or done
            existing = _ANIM_QUEUE.get(char_id)
            if existing and existing["status"] in ("queued", "done"):
                return self.end_json(200, {
                    "status": existing["status"],
                    "prompt_id": existing.get("prompt_id"),
                    "result_url": existing.get("result_url"),
                })

            prompt_hint = _build_avatar_prompt(char)
            result = _queue_animated_avatar(char_id, static_url, prompt_hint, comfy)
            if result.get("queued"):
                return self.end_json(200, {
                    "status": "queued",
                    "prompt_id": result["prompt_id"],
                })
            else:
                return self.end_json(200, {
                    "status": "unavailable",
                    "reason": result.get("reason", "unknown"),
                })

        # -- /api/background_generate --
        elif self.path == '/api/background_generate':
            BG_STYLES = {
                "tavern": "interior of a magical wizard guild tavern, warm candlelight, wooden beams, mystical artifacts on shelves, medieval fantasy atmosphere, cozy and inviting, tankards and spell scrolls on tables",
                "library": "vast arcane library interior, towering bookshelves reaching to vaulted ceiling, floating glowing books, magical ladders, warm reading nooks, ancient tomes, dust motes in light beams, stained glass windows",
                "tower": "interior of a wizard tower, spiral stone staircase, glowing runic inscriptions on walls, orbs of light floating, magical instruments, star maps on tables, moonlight through arched windows",
                "forest": "enchanted forest clearing at twilight, bioluminescent mushrooms and plants, ancient twisted trees with glowing sap, fireflies, moss-covered stones, mystical fog, moonbeams filtering through canopy",
                "dungeon": "underground alchemist laboratory, bubbling cauldrons, shelves of colorful potions and ingredients, flickering torchlight, stone walls with arcane symbols, crystal formations, spell components",
                "observatory": "celestial observatory atop a tower, massive brass telescope, astral maps and star charts, orrery with orbiting planets, glass dome showing starry sky, cosmic energy swirling, constellation diagrams",
                "forge": "magical forge interior, glowing enchanted anvil, molten magical metal flowing, sparks of arcane energy, weapon racks with enchanted swords, bellows, rune-carved tools, ember-lit atmosphere",
                "garden": "ethereal crystal garden, floating prismatic crystals, light refracting into rainbows, crystalline flowers, reflective pools, amethyst and quartz formations, magical mist, serene and otherworldly",
            }
            style = data.get('style', 'tavern')
            custom_prompt = data.get('custom_prompt', '')
            model_name = data.get('model', 'auto')

            if style == 'custom' and custom_prompt:
                base_prompt = custom_prompt
            else:
                base_prompt = BG_STYLES.get(style, BG_STYLES['tavern'])

            prompt_text = f"{base_prompt}, wide angle shot, detailed environment concept art, high quality, atmospheric lighting, fantasy illustration"
            negative = "text, watermark, blurry, people, characters, faces, hands, low quality, jpeg artifacts"

            try:
                # Use specific model if requested
                if model_name and model_name != 'auto':
                    ckpt = model_name
                    # Detect arch from model name
                    ml = ckpt.lower()
                    if "klein" in ml:
                        arch_key = "flux2klein"
                    elif "flux" in ml:
                        arch_key = "flux1dev"
                    elif "xl" in ml:
                        arch_key = "sdxl"
                    elif "illu" in ml:
                        arch_key = "illustrious"
                    else:
                        arch_key = "sd15"
                    preset = _build_optimized_preset(ckpt, arch_key, 1024, 576)

                    if BUILTIN_AVAILABLE and get_arch:
                        arch = get_arch(arch_key)
                        if arch and arch.quality_positive:
                            prompt_text = f"{prompt_text}, {arch.quality_positive}"
                        if arch and arch.supports_negative and arch.quality_negative:
                            negative = f"{negative}, {arch.quality_negative}"

                    seed = random.randint(1, 1000000000)
                    workflow = build_txt2img(preset, prompt_text, negative, seed)
                    result = _dispatch_workflow(workflow, comfy)
                    if result.get("type") == "images" and result.get("urls"):
                        return self.end_json(200, {"bg_url": result["urls"][0]})
                    raise Exception("No image returned from ComfyUI.")
                else:
                    img_url = _dispatch_txt2img(prompt_text, negative, 1024, 576, comfy)
                    return self.end_json(200, {"bg_url": img_url})
            except Exception as e:
                return self.end_json(500, {"error": str(e)})

        # -- /api/batch_generate --
        elif self.path == '/api/batch_generate':
            def _run_batch():
                for char in CHARS_CACHE:
                    try:
                        prompt_text = _build_avatar_prompt(char)
                        negative = "text, watermark, blurry, deformed, ugly, low quality, frame, border"
                        print(f"  [Batch] Generating avatar for: {char.get('name', char['id'])}")
                        img_url = _dispatch_txt2img(prompt_text, negative, 512, 512, comfy)
                        _BATCH_RESULTS.append({"id": char['id'], "avatar_url": img_url, "status": "ok"})
                        print(f"  [Batch] Done: {char.get('name', char['id'])} ({len(_BATCH_RESULTS)}/{_BATCH_STATE['total']})")
                    except Exception as e:
                        _BATCH_RESULTS.append({"id": char['id'], "status": "error", "error": str(e)})
                        print(f"  [Batch] Failed: {char.get('name', char['id'])}: {e}")

                try:
                    print("  [Batch] Generating tavern background...")
                    bg_prompt = (
                        "interior of a magical wizard guild tavern, "
                        "warm candlelight, wooden beams, mystical artifacts on shelves, "
                        "medieval fantasy atmosphere, cozy, detailed, "
                        "wide angle, concept art, high quality"
                    )
                    bg_url = _dispatch_txt2img(bg_prompt, "text, watermark, blurry, people", 1024, 576, comfy)
                    _BATCH_RESULTS.append({"id": "_background", "bg_url": bg_url, "status": "ok"})
                    print("  [Batch] Background done")
                except Exception as e:
                    _BATCH_RESULTS.append({"id": "_background", "status": "error", "error": str(e)})
                    print(f"  [Batch] Background failed: {e}")

                _BATCH_STATE["running"] = False
                ok = sum(1 for r in _BATCH_RESULTS if r['status'] == 'ok')
                print(f"  [Batch] Complete: {ok}/{len(_BATCH_RESULTS)} succeeded")

            if _BATCH_STATE.get("running"):
                return self.end_json(409, {"error": "Batch generation already in progress"})

            total = len(CHARS_CACHE) + 1
            _BATCH_STATE["running"] = True
            _BATCH_STATE["total"] = total
            _BATCH_RESULTS.clear()
            threading.Thread(target=_run_batch, daemon=True).start()
            return self.end_json(200, {
                "status": "started",
                "total": total,
                "message": f"Queued {len(CHARS_CACHE)} avatars + 1 background"
            })

        # -- /api/banish_wizard -- hide a wizard from the sidebar
        elif self.path == '/api/banish_wizard':
            char_id = data.get('id', '')
            if not char_id:
                return self.end_json(400, {"error": "Missing character id"})
            found = any(c['id'] == char_id for c in CHARS_CACHE)
            if not found:
                return self.end_json(404, {"error": f"Character '{char_id}' not found"})
            _BANISHED_IDS.add(char_id)
            _save_banished_ids()
            print(f"  [Guild] Banished wizard: {char_id}")
            return self.end_json(200, {"status": "banished", "id": char_id})

        # -- /api/unbanish_wizard -- restore a banished wizard
        elif self.path == '/api/unbanish_wizard':
            char_id = data.get('id', '')
            if not char_id:
                return self.end_json(400, {"error": "Missing character id"})
            _BANISHED_IDS.discard(char_id)
            _save_banished_ids()
            print(f"  [Guild] Unbanished wizard: {char_id}")
            return self.end_json(200, {"status": "unbanished", "id": char_id})

        # -- /api/summon_wizard -- create a new wizard character from a model
        elif self.path == '/api/summon_wizard':
            model_name = data.get('model_name', '')
            model_arch = data.get('model_arch', 'sdxl')
            model_type = data.get('model_type', 'checkpoint')
            wizard_name = data.get('name', 'Unnamed Wizard')
            personality = data.get('personality', '')
            subtext = data.get('subtext', '')
            scaffold = data.get('scaffold', 'auto')

            if not model_name:
                return self.end_json(400, {"error": "model_name is required"})

            # Generate a unique ID
            safe_name = model_name.replace('/', '_').replace('\\', '_').replace('.', '_')
            char_id = f"custom_{safe_name}"

            # Check for duplicate (also check auto-detected comfyui_* ID)
            comfyui_id = f"comfyui_{safe_name}"
            for c in CHARS_CACHE:
                if c['id'] in (char_id, comfyui_id):
                    return self.end_json(409, {"error": f"A wizard for model '{model_name}' already exists"})

            # Determine scaffold → system_prompt mapping
            SCAFFOLD_MAP = {
                "studio_imaginus": {
                    "subtext_default": "Image Creation (txt2img, ControlNet)",
                    "studio_ref": "studio_imaginus",
                },
                "studio_transmutex": {
                    "subtext_default": "Image Transformation (img2img, Style Transfer)",
                    "studio_ref": "studio_transmutex",
                },
                "studio_masquerade": {
                    "subtext_default": "Face & Identity (Face Swap, FaceID, PuLID)",
                    "studio_ref": "studio_masquerade",
                },
                "studio_restorix": {
                    "subtext_default": "Upscaling & Restoration",
                    "studio_ref": "studio_restorix",
                },
                "studio_erasure": {
                    "subtext_default": "Inpainting, Removal & Edits",
                    "studio_ref": "studio_erasure",
                },
                "video_gen": {
                    "subtext_default": "Video Generation (Video)",
                    "studio_ref": None,
                },
                "video_upscale": {
                    "subtext_default": "Video Upscaling & Enhancement (Video)",
                    "studio_ref": None,
                },
                "generic": {
                    "subtext_default": "General Workflow Browser",
                    "studio_ref": None,
                },
            }

            # Auto-detect scaffold from architecture
            if scaffold == 'auto':
                arch_to_scaffold = {
                    "flux2klein": "studio_imaginus",
                    "flux1dev": "studio_imaginus",
                    "sdxl": "studio_imaginus",
                    "illustrious": "studio_imaginus",
                    "sd15": "studio_imaginus",
                }
                ml = model_name.lower()
                if any(k in ml for k in ['wan', 'ltx', 'video', 'animate', 'svd']):
                    scaffold = "video_gen"
                elif any(k in ml for k in ['seedvr', 'rife', 'rtx_upscale']):
                    scaffold = "video_upscale"
                elif any(k in ml for k in ['upscale', 'esrgan', 'ultrasharp', 'remacri']):
                    scaffold = "studio_restorix"
                elif any(k in ml for k in ['inpaint']):
                    scaffold = "studio_erasure"
                elif any(k in ml for k in ['reactor', 'faceswap', 'pulid', 'faceid', 'insightface']):
                    scaffold = "studio_masquerade"
                else:
                    scaffold = arch_to_scaffold.get(model_arch, "studio_imaginus")

            scaffold_info = SCAFFOLD_MAP.get(scaffold, SCAFFOLD_MAP["generic"])

            if not subtext:
                subtext = f"{model_name} — {scaffold_info['subtext_default']}"

            # Generate colors from model name
            hue = int(hashlib.md5(model_name.encode('utf-8')).hexdigest(), 16) % 360

            # Build the character entry
            new_char = {
                "id": char_id,
                "type": "studio" if scaffold_info.get("studio_ref") else "custom_workflow",
                "name": wizard_name,
                "subtext": subtext,
                "color1": f"hsl({hue}, 85%, 42%)",
                "color2": f"hsl({(hue + 55) % 360}, 100%, 58%)",
                "personality": personality,
                "model_name": model_name,
                "model_arch": model_arch,
                "model_type": model_type,
                "scaffold": scaffold,
            }

            # Register the custom wizard in STUDIO_CHARACTERS if it maps to a studio scaffold
            studio_ref = scaffold_info.get("studio_ref")
            if studio_ref and studio_ref in _STUDIO_BY_ID:
                ref_studio = _STUDIO_BY_ID[studio_ref]
                custom_studio = dict(ref_studio)  # copy the reference scaffold
                custom_studio["id"] = char_id
                custom_studio["name"] = wizard_name
                custom_studio["subtext"] = subtext
                custom_studio["color1"] = new_char["color1"]
                custom_studio["color2"] = new_char["color2"]
                custom_studio["archetype"] = ref_studio.get("archetype", "")
                custom_studio["default_model"] = model_name
                custom_studio["default_arch"] = model_arch
                # Update system prompt to mention the specific model
                custom_studio["system_prompt"] = (
                    ref_studio["system_prompt"]
                    + f"\nDEFAULT MODEL: When building presets, always use "
                    f"checkpoint/UNET '{model_name}' (arch: {model_arch}) "
                    f"unless the user explicitly requests a different model.\n"
                )
                _STUDIO_BY_ID[char_id] = custom_studio

            CHARS_CACHE.append(new_char)
            _save_custom_wizards()

            print(f"  [Summon] Created wizard '{wizard_name}' for model '{model_name}' "
                  f"(scaffold: {scaffold}, arch: {model_arch})")

            return self.end_json(200, {
                "status": "created",
                "character": new_char,
                "scaffold": scaffold,
            })

        # -- /api/lora_describe -- user provides descriptions for unknown LoRAs
        elif self.path == '/api/lora_describe':
            descriptions = data.get('descriptions', {})
            char_id = data.get('char_id', '')
            if not descriptions:
                return self.end_json(400, {"error": "descriptions dict required"})

            updated = 0
            for lora_name, desc in descriptions.items():
                if lora_name in _LORA_REGISTRY:
                    _LORA_REGISTRY[lora_name]["user_desc"] = desc
                    _LORA_REGISTRY[lora_name]["source"] = "user"
                    # Also set purpose from user description if not already set
                    if not _LORA_REGISTRY[lora_name].get("purpose"):
                        _LORA_REGISTRY[lora_name]["purpose"] = desc
                    updated += 1

            if char_id:
                _LORA_INTERROGATED.add(char_id)

            _save_lora_registry()
            return self.end_json(200, {
                "status": "ok",
                "updated": updated,
                "char_id": char_id,
            })

        # -- /api/lora_refresh -- re-scan LoRAs from ComfyUI
        elif self.path == '/api/lora_refresh':
            threading.Thread(
                target=_build_lora_registry,
                args=(data.get('comfy_url', COMFYUI_URL),),
                daemon=True
            ).start()
            return self.end_json(200, {
                "status": "refreshing",
                "current_total": len(_LORA_REGISTRY),
            })

        # -- /api/reinitialize -- nuke non-core wizards, re-detect from ComfyUI
        elif self.path == '/api/reinitialize':
            keep_core_assets = data.get('keep_core_assets', True)

            # "Core" = studio characters only (Imaginus, Transmutex, etc.)
            # model_wizard (LTX2, WAN, etc.) and comfyui_model are all re-detected
            PRESERVED_TYPE = 'studio'

            old_total = len(CHARS_CACHE)
            old_nonstudio = sum(1 for c in CHARS_CACHE
                                if c.get('type') != PRESERVED_TYPE)

            # Collect IDs of everything being removed (for asset cleanup)
            removed_ids = {c['id'] for c in CHARS_CACHE
                           if c.get('type') != PRESERVED_TYPE}

            # Clean _STUDIO_BY_ID — remove non-studio entries
            for rid in removed_ids:
                _STUDIO_BY_ID.pop(rid, None)

            # Clean generated assets
            if keep_core_assets:
                for rid in removed_ids:
                    _GENERATED_ASSETS.pop(rid, None)
            else:
                _GENERATED_ASSETS.clear()
            _save_generated_assets()

            # Clear banished IDs (fresh start)
            _BANISHED_IDS.clear()
            _save_banished_ids()

            # Nuke custom wizard persistence
            if os.path.exists(_CUSTOM_WIZARDS_PATH):
                try:
                    os.remove(_CUSTOM_WIZARDS_PATH)
                except Exception:
                    pass

            # Clear LoRA registry (will be rebuilt)
            _LORA_REGISTRY.clear()
            _LORA_INTERROGATED.clear()
            _save_lora_registry()

            # Clear animation queue
            _ANIM_QUEUE.clear()

            # Re-run FULL character discovery — this handles:
            #   1. Studio characters (always present)
            #   2. Model-family wizards (LTX2/WAN/SeedVR2) — gated on ComfyUI models
            #   3. Per-model wizards (comfyui_model) — detected from ComfyUI
            #   4. Spellcaster nodes
            new_chars, new_nodes = fetch_all_characters(comfy_url=comfy)
            CHARS_CACHE = new_chars
            NODES_CACHE = new_nodes

            new_detected = sum(1 for c in CHARS_CACHE
                               if c.get('type') != PRESERVED_TYPE)
            studio_count = sum(1 for c in CHARS_CACHE
                               if c.get('type') == PRESERVED_TYPE)

            # Rebuild LoRA registry in background
            threading.Thread(
                target=_build_lora_registry,
                args=(comfy,),
                daemon=True
            ).start()

            print(f"  [Reinit] Removed {old_nonstudio} non-core wizards, "
                  f"re-detected {new_detected} from ComfyUI "
                  f"(studio: {studio_count}, total: {len(CHARS_CACHE)})")

            return self.end_json(200, {
                "status": "reinitialized",
                "removed": old_nonstudio,
                "core_kept": studio_count,
                "new_detected": new_detected,
                "total": len(CHARS_CACHE),
            })

        # -- /api/batch_status (POST alias) --
        elif self.path == '/api/batch_status':
            return self.end_json(200, {
                "running": _BATCH_STATE.get("running", False),
                "results": list(_BATCH_RESULTS),
                "completed": len(_BATCH_RESULTS),
            })

        # -- /api/build -- call a build_* function from _workflows_v2
        elif self.path == '/api/build':
            fn_name = data.get('build_fn')
            params = data.get('params', {})
            if not fn_name:
                return self.end_json(400, {"error": "Missing build_fn"})
            try:
                result = _build_and_dispatch(fn_name, params, comfy)
                if result.get('type') == 'images' and result.get('urls'):
                    return self.end_json(200, {
                        "mock_img": result['urls'][0],
                        "all_images": result['urls'],
                        "prompt_id": result.get('prompt_id')
                    })
                elif result.get('type') == 'videos' and result.get('urls'):
                    return self.end_json(200, {
                        "mock_img": result['urls'][0],
                        "all_videos": result['urls'],
                        "prompt_id": result.get('prompt_id')
                    })
                else:
                    return self.end_json(200, result)
            except Exception as e:
                return self.end_json(500, {"error": str(e)})

        # -- /api/execute -- routes build_fn payloads from LLM chat
        elif self.path == '/api/execute':
            build_fn = data.get('build_fn')
            params = data.get('params', {})
            if build_fn:
                try:
                    result = _build_and_dispatch(build_fn, params, comfy)
                    if result.get('type') == 'images' and result.get('urls'):
                        return self.end_json(200, {
                            "mock_img": result['urls'][0],
                            "all_images": result['urls'],
                            "prompt_id": result.get('prompt_id')
                        })
                    elif result.get('type') == 'videos' and result.get('urls'):
                        return self.end_json(200, {
                            "mock_img": result['urls'][0],
                            "all_videos": result['urls'],
                            "prompt_id": result.get('prompt_id')
                        })
                    else:
                        return self.end_json(200, result)
                except Exception as e:
                    return self.end_json(500, {"error": str(e)})
            else:
                return self.end_json(400, {
                    "error": "Missing build_fn. Expected {build_fn: '...', params: {...}}"})

        else:
            return self.end_json(404, {"error": f"Unknown endpoint: {self.path}"})

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def translate_path(self, path):
        root = os.path.dirname(os.path.abspath(__file__))
        path = path.split('?', 1)[0]
        path = path.split('#', 1)[0]
        if path.startswith('/'):
            path = path[1:]
        return os.path.join(root, path)

    def log_message(self, format, *args):
        """Quieter logging — skip noisy static asset requests."""
        msg = format % args
        if '/static/' not in msg and '/api/avatar/' not in msg:
            print(f"  {msg}")


if __name__ == "__main__":
    _server_init()   # detect models + LoRAs with current COMFYUI_URL
    print(f"Starting The Wizard Guild on port {PORT}...")
    httpd = HTTPServer(('0.0.0.0', PORT), GuildHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()