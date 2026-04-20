"""Diagnostic Wizard — test every capability, disable broken ones, optimize settings.

Runs a systematic probe of the connected ComfyUI server:
  1. Node inventory — what's installed, what's missing
  2. Model inventory — what architectures are available
  3. Functional tests — tiny generations to verify each pipeline works
  4. VRAM profiling — measure actual generation times and memory usage
  5. Generates a capability report + recommended configuration

Usage:
    from spellcaster_core.diagnostic import run_diagnostic

    report = run_diagnostic("http://192.168.x.x:8188", interactive=False)
    # report.working = ["txt2img_sd15", "txt2img_sdxl", "upscale", ...]
    # report.broken = ["iclight", "colorize", ...]
    # report.recommended_config = {...}

    # Interactive mode: asks user to rate results
    report = run_diagnostic(server, interactive=True, callback=print)
"""

import json
import os
import sys
import time
import random
import urllib.request
import urllib.error

try:
    from .preflight import get_available_nodes
    from .optimizer import get_server_vram, estimate_vram, get_max_resolution
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .architectures import get_arch, ARCHITECTURES
    from .workflows import (
        build_txt2img, build_upscale, build_rembg, build_faceswap,
        build_face_restore, build_faceswap_model, build_style_transfer,
        build_iclight, build_lut, build_wan_video, build_ltx_video,
    )
except ImportError:
    from spellcaster_core.preflight import get_available_nodes
    from spellcaster_core.optimizer import get_server_vram, estimate_vram, get_max_resolution
    from spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model
    from spellcaster_core.architectures import get_arch, ARCHITECTURES
    from spellcaster_core.workflows import (
        build_txt2img, build_upscale, build_rembg, build_faceswap,
        build_face_restore, build_faceswap_model, build_style_transfer,
        build_iclight, build_lut, build_wan_video, build_ltx_video,
    )


class DiagnosticReport:
    """Results of a diagnostic run."""
    def __init__(self):
        self.server_url = ""
        self.gpu_name = ""
        self.vram_total = 0.0
        self.vram_free = 0.0
        self.node_count = 0
        self.models = {}           # arch -> [model_names]
        self.working = []          # list of capability IDs that passed
        self.broken = []           # list of (capability_id, error_msg)
        self.timings = {}          # capability_id -> seconds
        self.missing_nodes = []    # critical nodes not installed
        self.warnings = []         # general warnings
        self.banish_wizards = []   # wizard IDs that should be hidden
        self.recommended_config = {}

    def summary(self):
        """Human-readable summary."""
        lines = [
            f"Spellcaster Diagnostic Report",
            f"  Server: {self.server_url}",
            f"  GPU: {self.gpu_name}",
            f"  VRAM: {self.vram_total:.1f} GB ({self.vram_free:.1f} GB free)",
            f"  Nodes: {self.node_count}",
            f"  Models: {sum(len(v) for v in self.models.values())} across {len(self.models)} architectures",
            "",
            f"  Working: {len(self.working)} capabilities",
        ]
        for cap in self.working:
            t = self.timings.get(cap, 0)
            lines.append(f"    + {cap} ({t:.0f}s)" if t else f"    + {cap}")

        if self.broken:
            lines.append(f"  Broken: {len(self.broken)} capabilities")
            for cap, err in self.broken:
                lines.append(f"    - {cap}: {err[:80]}")

        if self.missing_nodes:
            lines.append(f"  Missing nodes: {', '.join(self.missing_nodes)}")

        if self.banish_wizards:
            lines.append(f"  Recommend banishing: {', '.join(self.banish_wizards)}")

        if self.warnings:
            lines.append(f"  Warnings:")
            for w in self.warnings:
                lines.append(f"    ! {w}")

        return "\n".join(lines)

    def to_json(self):
        """Serializable dict for saving/transmitting."""
        return {
            "server_url": self.server_url,
            "gpu_name": self.gpu_name,
            "vram_total": self.vram_total,
            "vram_free": self.vram_free,
            "node_count": self.node_count,
            "models": self.models,
            "working": self.working,
            "broken": [(c, e) for c, e in self.broken],
            "timings": self.timings,
            "missing_nodes": self.missing_nodes,
            "banish_wizards": self.banish_wizards,
            "warnings": self.warnings,
            "recommended_config": self.recommended_config,
        }


# ═══════════════════════════════════════════════════════════════════════
#  Capability test definitions
# ═══════════════════════════════════════════════════════════════════════

# Each test: (capability_id, display_name, build_fn, required_nodes, related_wizards)
# build_fn receives (models_dict, server_url, test_image) and returns a workflow

def _build_txt2img_test(arch_key, models, server, test_img):
    """Build a tiny txt2img test for a specific architecture."""
    if arch_key not in models or not models[arch_key]:
        return None
    model = models[arch_key][0]
    a = get_arch(arch_key)
    if not a:
        return None
    preset = {
        "ckpt": model, "arch": arch_key,
        "width": 256, "height": 256, "steps": 3,
        "cfg": a.default_cfg, "sampler": a.default_sampler,
        "scheduler": a.default_scheduler, "loader": a.loader,
        "clip_name1": "", "clip_name2": "", "vae_name": "",
    }
    return build_txt2img(preset, "test sphere on white", "ugly", random.randint(1, 2**31))


CAPABILITY_TESTS = [
    # Image generation per architecture
    ("txt2img_sd15", "SD 1.5 Generation",
     lambda m, s, i: _build_txt2img_test("sd15", m, s, i),
     ["CheckpointLoaderSimple", "KSampler"],
     ["studio_imaginus"]),

    ("txt2img_sdxl", "SDXL Generation",
     lambda m, s, i: _build_txt2img_test("sdxl", m, s, i),
     ["CheckpointLoaderSimple", "KSampler"],
     ["studio_imaginus"]),

    ("txt2img_illustrious", "Illustrious Generation",
     lambda m, s, i: _build_txt2img_test("illustrious", m, s, i),
     ["CheckpointLoaderSimple", "KSampler"],
     ["studio_imaginus"]),

    ("txt2img_flux", "Flux/Klein Generation",
     lambda m, s, i: _build_txt2img_test("flux2klein", m, s, i),
     ["UNETLoader", "CLIPLoader"],
     ["studio_imaginus"]),

    # Post-processing
    ("upscale", "AI Upscale (4x-UltraSharp)",
     lambda m, s, i: build_upscale(i, "4x-UltraSharp.pth") if i else None,
     ["UpscaleModelLoader", "ImageUpscaleWithModel"],
     ["studio_restorex"]),

    ("rembg", "Background Removal",
     lambda m, s, i: build_rembg(i) if i else None,
     ["ImageRembg"],
     ["studio_erasex"]),

    ("face_restore", "Face Restore (CodeFormer)",
     lambda m, s, i: build_face_restore(i, "codeformer-v0.1.0.pth", "retinaface_resnet50", 1.0, 0.7) if i else None,
     ["ReActorRestoreFace"],
     ["studio_masquerade"]),

    ("faceswap", "Face Swap (ReActor)",
     lambda m, s, i: build_faceswap(i, i) if i else None,
     ["ReActorFaceSwapOpt"],
     ["studio_masquerade"]),

    # Video
    ("wan_i2v", "WAN I2V Video",
     None,  # Built dynamically (needs WAN preset detection)
     ["WanImageToVideo", "UnetLoaderGGUF"],
     ["studio_videomancer", "studio_cinematic", "model_wan"]),

    ("ltx_t2v", "LTX T2V Video",
     None,  # Built dynamically
     ["LTXVLoader"],
     ["studio_videomancer", "model_ltx2"]),
]


# ═══════════════════════════════════════════════════════════════════════
#  Main diagnostic runner
# ═══════════════════════════════════════════════════════════════════════

def _submit_and_wait(server, workflow, timeout=120):
    """Submit workflow, wait for result. Returns (ok, elapsed, error_msg)."""
    try:
        from .preflight import preflight_workflow
        ok, workflow, report = preflight_workflow(workflow, server)
        if not ok:
            return False, 0, f"Missing nodes: {report['missing']}"
    except ImportError:
        pass

    body = json.dumps({"prompt": workflow}).encode()
    req = urllib.request.Request(
        f"{server}/prompt", data=body,
        headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        pid = json.loads(r.read()).get("prompt_id")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            details = []
            for nid, ne in err.get("node_errors", {}).items():
                for er in ne.get("errors", []):
                    details.append(f"{ne.get('class_type', '?')}: {er.get('details', '')[:60]}")
            return False, 0, "; ".join(details) or str(e)
        except Exception:
            return False, 0, str(e)
    except Exception as e:
        return False, 0, str(e)

    if not pid:
        return False, 0, "No prompt_id returned"

    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = urllib.request.urlopen(f"{server}/history/{pid}", timeout=5)
            d = json.loads(r.read())
            if pid in d:
                st = d[pid].get("status", {})
                if st.get("completed"):
                    return True, time.time() - t0, ""
                for msg in st.get("messages", []):
                    if msg[0] == "execution_error":
                        return False, time.time() - t0, msg[1].get("exception_message", "?")[:150]
        except Exception:
            pass
        time.sleep(2)
    return False, timeout, "Timeout"


def _get_models(server):
    """Get all models grouped by architecture."""
    models = {}
    skip = ("vae", "embeddings", "audio", "clip_", "t5xxl", "umt5",
            "gemma", "qwen", "mistral", "llava", "connector")
    for node, field, cfn in [
        ("UnetLoaderGGUF", "unet_name", classify_unet_model),
        ("UNETLoader", "unet_name", classify_unet_model),
        ("CheckpointLoaderSimple", "ckpt_name", classify_ckpt_model),
    ]:
        try:
            r = urllib.request.urlopen(f"{server}/object_info/{node}", timeout=5)
            d = json.loads(r.read())
            spec = d[node]["input"]["required"][field]
            opts = spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])
            for m in opts:
                if any(s in m.lower() for s in skip):
                    continue
                arch = cfn(m)
                if arch != "unknown":
                    models.setdefault(arch, []).append(m)
        except Exception:
            pass
    return models


def _upload_test_image(server, image_data, name="diag_test.png"):
    """Upload a test image to ComfyUI input folder."""
    import uuid
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + image_data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{server}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req, timeout=10)
    return name


def run_diagnostic(server, callback=None, interactive=False):
    """Run full diagnostic suite.

    Args:
        server: ComfyUI server URL
        callback: Function to call with progress messages (default: print)
        interactive: If True, pause for user input on failures

    Returns: DiagnosticReport
    """
    log = callback or print
    report = DiagnosticReport()
    report.server_url = server

    # Phase 1: Server connectivity
    log("Phase 1: Server connectivity")
    try:
        r = urllib.request.urlopen(f"{server}/system_stats", timeout=5)
        stats = json.loads(r.read())
        dev = stats["devices"][0]
        report.gpu_name = dev["name"]
        report.vram_total = dev["vram_total"] / 1e9
        report.vram_free = dev["vram_free"] / 1e9
        log(f"  GPU: {report.gpu_name}")
        log(f"  VRAM: {report.vram_total:.1f} GB ({report.vram_free:.1f} GB free)")
    except Exception as e:
        log(f"  FAILED: Cannot reach {server} ({e})")
        report.warnings.append(f"Server unreachable: {e}")
        return report

    # Phase 2: Node inventory
    log("\nPhase 2: Node inventory")
    nodes = get_available_nodes(server, force_refresh=True)
    report.node_count = len(nodes)
    log(f"  {len(nodes)} nodes available")

    critical = {
        "CheckpointLoaderSimple": "Model loading",
        "KSampler": "Standard sampling",
        "SaveImage": "Image saving",
        "UpscaleModelLoader": "AI upscaling",
        "ImageUpscaleWithModel": "AI upscaling",
        "VHS_VideoCombine": "Video assembly",
        "ReActorFaceSwapOpt": "Face swap",
        "ImageRembg": "Background removal",
        "WanImageToVideo": "WAN I2V",
        "UnetLoaderGGUF": "GGUF model loading",
    }
    for ct, desc in critical.items():
        if ct not in nodes:
            report.missing_nodes.append(ct)
            log(f"  MISSING: {ct} ({desc})")

    # Phase 3: Model inventory
    log("\nPhase 3: Model inventory")
    models = _get_models(server)
    report.models = models
    for arch, mlist in sorted(models.items()):
        log(f"  {arch}: {len(mlist)} model(s)")

    if not models:
        log("  WARNING: No models found!")
        report.warnings.append("No generation models found on server")
        return report

    # Phase 4: Generate a test image for post-processing tests
    log("\nPhase 4: Generating test image")
    test_img = None
    # Pick the fastest available architecture
    for fast_arch in ["sd15", "sdxl", "illustrious", "flux2klein"]:
        if fast_arch in models:
            wf = _build_txt2img_test(fast_arch, models, server, None)
            if wf:
                ok, elapsed, err = _submit_and_wait(server, wf, timeout=60)
                if ok:
                    # Get the output filename
                    log(f"  Generated test image in {elapsed:.0f}s ({fast_arch})")
                    # Download and re-upload as input
                    try:
                        import urllib.request as _ur
                        # Find the prompt_id from the last submission
                        body = json.dumps({"prompt": wf}).encode()
                        req = _ur.Request(f"{server}/prompt", data=body,
                                          headers={"Content-Type": "application/json"})
                        r = _ur.urlopen(req, timeout=10)
                        pid = json.loads(r.read()).get("prompt_id")
                        time.sleep(3)
                        r2 = _ur.urlopen(f"{server}/history/{pid}", timeout=5)
                        hist = json.loads(r2.read()).get(pid, {})
                        for out in hist.get("outputs", {}).values():
                            if "images" in out:
                                fn = out["images"][0]["filename"]
                                ft = out["images"][0].get("type", "output")
                                img_data = _ur.urlopen(
                                    f"{server}/view?filename={fn}&type={ft}", timeout=30).read()
                                test_img = _upload_test_image(server, img_data)
                                log(f"  Test image uploaded: {test_img}")
                                break
                    except Exception:
                        pass
                    break
                else:
                    log(f"  {fast_arch} failed: {err[:60]}")

    if not test_img:
        log("  WARNING: Could not generate test image")
        report.warnings.append("Test image generation failed — post-processing tests skipped")

    # Phase 5: Capability tests
    log("\nPhase 5: Testing capabilities")
    for cap_id, cap_name, build_fn, required_nodes, related_wizards in CAPABILITY_TESTS:
        log(f"  {cap_name}...", end=" ")

        # Check required nodes
        missing = [n for n in required_nodes if n not in nodes]
        if missing:
            report.broken.append((cap_id, f"Missing nodes: {', '.join(missing)}"))
            report.banish_wizards.extend(related_wizards)
            log(f"SKIP (missing: {', '.join(missing)})")
            continue

        # Build workflow
        try:
            if build_fn:
                wf = build_fn(models, server, test_img)
            else:
                wf = None  # Dynamic tests handled below

            if cap_id == "wan_i2v" and test_img:
                wf = _build_wan_test(models, server, test_img)
            elif cap_id == "ltx_t2v":
                wf = _build_ltx_test(models, server)

            if wf is None:
                report.broken.append((cap_id, "No suitable model available"))
                report.banish_wizards.extend(related_wizards)
                log("SKIP (no model)")
                continue

        except Exception as e:
            report.broken.append((cap_id, f"Build error: {e}"))
            report.banish_wizards.extend(related_wizards)
            log(f"BUILD FAIL: {e}")
            continue

        # Submit and test
        ok, elapsed, err = _submit_and_wait(server, wf, timeout=180)
        if ok:
            report.working.append(cap_id)
            report.timings[cap_id] = elapsed
            log(f"OK ({elapsed:.0f}s)")
        else:
            report.broken.append((cap_id, err))
            report.banish_wizards.extend(related_wizards)
            log(f"FAIL: {err[:80]}")

    # Phase 6: Build recommended configuration
    log("\nPhase 6: Building recommendations")
    report.banish_wizards = list(set(report.banish_wizards))
    report.recommended_config = _build_config(report)

    log(f"\n{report.summary()}")
    return report


def _build_wan_test(models, server, test_img):
    """Build a minimal WAN I2V test workflow.

    Uses the canonical detect_wan_preset + wan_turbo_kwargs helpers so the
    diagnostic probes the same code path the real app uses. Without this,
    a hand-rolled preset can pass diagnostic while real generation fails
    (different VAE pairing, different UNET family filter, different accel
    LoRA selection, etc.). See CLAUDE.md §16.4 rule #1 — no parallel
    detection.
    """
    if "wan" not in models:
        return None
    from . import video_presets as _vp
    preset = _vp.detect_wan_preset(server)
    if not preset:
        return None
    # Diagnostic is a turbo smoke test — shortest possible render that
    # exercises the full accel-LoRA path when available. Pair with
    # wan_turbo_kwargs per canon rule #2.
    _canon = _vp.wan_turbo_kwargs(True)
    return build_wan_video(
        test_img, preset, "test motion", "blurry", random.randint(1, 2**31),
        width=384, height=256, length=9, turbo=True,
        rtx_scale=0, interpolate=False, face_swap=False, fps=8,
        **_canon)


def _build_ltx_test(models, server):
    """Build a minimal LTX T2V test workflow."""
    if "ltx" not in models:
        return None

    def _opts(node, field):
        try:
            r = urllib.request.urlopen(f"{server}/object_info/{node}", timeout=5)
            d = json.loads(r.read())
            s = d[node]["input"]["required"][field]
            return s[0] if isinstance(s[0], list) else s[1].get("options", [])
        except:
            return []

    unets = _opts("UnetLoaderGGUF", "unet_name")
    clips = _opts("CLIPLoaderGGUF", "clip_name")
    vaes = _opts("VAELoader", "vae_name")

    ltx_unet = next((u for u in unets if "ltx" in u.lower()), "")
    ltx_te = next((c for c in clips if "gemma" in c.lower()), "")
    ltx_vae = next((v for v in vaes if "ltx" in v.lower() and "video" in v.lower()), "")
    ltx_conn = next((c for c in clips if "embeddings_connector" in c.lower()), "")

    if not ltx_unet or not ltx_te or not ltx_vae:
        return None

    preset = {
        "unet": ltx_unet, "text_encoder": ltx_te,
        "embeddings_connector": ltx_conn, "vae": ltx_vae,
        "steps": 5, "cfg": 4.0, "stg": 1.0, "rescale": 0.7,
        "distilled_lora": "", "latent_upscaler": "", "lora_prefix": "ltxv",
    }
    return build_ltx_video(
        preset, "test clouds moving", random.randint(1, 2**31),
        width=256, height=192, num_frames=5, fps=8)


def _build_config(report):
    """Build recommended configuration from diagnostic results."""
    config = {
        "vram_tier": "low" if report.vram_total < 8 else
                     "medium" if report.vram_total < 12 else
                     "high" if report.vram_total < 16 else "ultra",
        "working_capabilities": report.working,
        "banish_wizards": report.banish_wizards,
        "best_image_arch": None,
        "best_video_engine": None,
        "tiled_vae_recommended": report.vram_total < 16,
    }

    # Find best image architecture (fastest working one)
    for cap in ["txt2img_flux", "txt2img_sdxl", "txt2img_illustrious", "txt2img_sd15"]:
        if cap in report.working:
            config["best_image_arch"] = cap.replace("txt2img_", "")
            break

    # Find best video engine
    if "wan_i2v" in report.working:
        config["best_video_engine"] = "wan"
    elif "ltx_t2v" in report.working:
        config["best_video_engine"] = "ltx"

    return config
