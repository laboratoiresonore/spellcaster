"""Pipeline — chainable workflow composition.

Build multi-step AI pipelines with a fluent API. Each step's output
feeds the next. The pipeline handles file upload, workflow building,
preflight, optimization, submission, and result download automatically.

Usage:
    from spellcaster_core.pipeline import Pipeline

    # Simple generation + upscale
    Pipeline("http://192.168.x.x:8188") \\
        .txt2img("a wizard in a forest", arch="sdxl", width=512, height=512) \\
        .upscale("4x-UltraSharp.pth") \\
        .save("output/wizard.png") \\
        .run()

    # Image to video with face swap
    Pipeline("http://192.168.x.x:8188") \\
        .load("portrait.png") \\
        .wan_video("gentle breathing, soft sway", length=33) \\
        .save("output/") \\
        .run()

    # Batch variation
    Pipeline("http://192.168.x.x:8188") \\
        .txt2img("a {color} dragon", arch="sdxl") \\
        .upscale() \\
        .save("output/") \\
        .run_batch(color=["red", "blue", "green", "gold"])
"""

import json
import os
import random
import time
import urllib.request
import urllib.error
import tempfile

try:
    from .workflows import (
        build_txt2img, build_img2img, build_upscale, build_rembg,
        build_faceswap, build_face_restore, build_wan_video, build_ltx_video,
    )
    from .architectures import get_arch
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .preflight import preflight_workflow
    from .optimizer import optimize_workflow
except ImportError:
    from _workflows_v2 import (
        build_txt2img, build_img2img, build_upscale, build_rembg,
        build_faceswap, build_face_restore,
    )
    build_wan_video = build_ltx_video = None
    from _architectures import get_arch
    from spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model
    from spellcaster_core.preflight import preflight_workflow
    from spellcaster_core.optimizer import optimize_workflow


class Pipeline:
    """Chainable workflow composition for ComfyUI generation.

    Each method adds a step to the pipeline. .run() executes them
    sequentially, feeding each step's output as the next step's input.
    """

    def __init__(self, server_url="http://127.0.0.1:8188", verbose=True):
        self._server = server_url
        self._steps = []
        self._verbose = verbose
        self._save_dir = None
        self._results = []  # Accumulated (filename, subfolder, type) tuples

    # ── Step builders (fluent API) ──────────────────────────────────

    def load(self, image_path):
        """Load a local image and upload it to ComfyUI as the starting point."""
        self._steps.append(("load", {"path": image_path}))
        return self

    def auto(self, prompt, **kwargs):
        """Smart generation — auto-detect the best model and settings from prompt.

        Uses the recommender to analyze the prompt and pick architecture,
        resolution, steps, and model automatically.

            Pipeline(server).auto("anime girl in a garden").save("out/").run()
        """
        self._steps.append(("auto", {"prompt": prompt, **kwargs}))
        return self

    def txt2img(self, prompt, negative="", arch="sdxl", model="",
                width=0, height=0, steps=0, cfg=None, seed=-1, loras=None):
        """Generate an image from text."""
        self._steps.append(("txt2img", {
            "prompt": prompt, "negative": negative, "arch": arch,
            "model": model, "width": width, "height": height,
            "steps": steps, "cfg": cfg, "seed": seed, "loras": loras,
        }))
        return self

    def img2img(self, prompt, negative="", denoise=0.65, arch="sdxl", model=""):
        """Transform the previous output with a new prompt."""
        self._steps.append(("img2img", {
            "prompt": prompt, "negative": negative,
            "denoise": denoise, "arch": arch, "model": model,
        }))
        return self

    def upscale(self, model="4x-UltraSharp.pth"):
        """Upscale the previous output."""
        self._steps.append(("upscale", {"model": model}))
        return self

    def rembg(self):
        """Remove background from the previous output."""
        self._steps.append(("rembg", {}))
        return self

    def faceswap(self, source_image):
        """Swap a face onto the previous output."""
        self._steps.append(("faceswap", {"source": source_image}))
        return self

    def face_restore(self, model="codeformer-v0.1.0.pth", weight=0.7):
        """Restore/enhance faces in the previous output."""
        self._steps.append(("face_restore", {"model": model, "weight": weight}))
        return self

    def wan_video(self, prompt, negative="blurry static", length=33,
                  width=576, height=320, turbo=True, fps=16):
        """Animate the previous output into a video using WAN I2V."""
        self._steps.append(("wan_video", {
            "prompt": prompt, "negative": negative, "length": length,
            "width": width, "height": height, "turbo": turbo, "fps": fps,
        }))
        return self

    def ltx_video(self, prompt, width=384, height=256, num_frames=25, fps=25):
        """Generate or animate video with LTX."""
        self._steps.append(("ltx_video", {
            "prompt": prompt, "width": width, "height": height,
            "num_frames": num_frames, "fps": fps,
        }))
        return self

    def save(self, path="."):
        """Set where to save final outputs."""
        self._save_dir = path
        return self

    # ── Execution ───────────────────────────────────────────────────

    def run(self):
        """Execute the pipeline sequentially."""
        current_image = None  # filename on ComfyUI server

        for i, (step_type, params) in enumerate(self._steps):
            label = f"[{i+1}/{len(self._steps)}] {step_type}"
            if self._verbose:
                print(f"  {label}...", end=" ", flush=True)

            try:
                if step_type == "auto":
                    from .recommend import recommend
                    rec = recommend(params["prompt"], server=self._server)
                    if self._verbose:
                        print(f"[{rec['intent']}] {rec['arch']}", end=" ", flush=True)
                    auto_params = {
                        "prompt": params["prompt"],
                        "arch": rec["arch"],
                        "model": rec.get("model", ""),
                        "width": rec["settings"].get("width", 0),
                        "height": rec["settings"].get("height", 0),
                        "steps": rec["settings"].get("steps", 0),
                        "cfg": rec["settings"].get("cfg"),
                        "seed": params.get("seed", -1),
                        "negative": params.get("negative", ""),
                        "loras": params.get("loras"),
                    }
                    results = self._run_txt2img(auto_params)
                    current_image = self._first_image(results)
                    if self._verbose:
                        print(f"-> {current_image}")

                elif step_type == "load":
                    current_image = self._upload(params["path"])
                    if self._verbose:
                        print(f"uploaded as {current_image}")

                elif step_type == "txt2img":
                    results = self._run_txt2img(params)
                    current_image = self._first_image(results)
                    if self._verbose:
                        print(f"OK -> {current_image}")

                elif step_type == "img2img":
                    if not current_image:
                        raise RuntimeError("img2img needs a previous image")
                    results = self._run_img2img(current_image, params)
                    current_image = self._first_image(results)
                    if self._verbose:
                        print(f"OK -> {current_image}")

                elif step_type == "upscale":
                    if not current_image:
                        raise RuntimeError("upscale needs a previous image")
                    results = self._run_upscale(current_image, params)
                    current_image = self._first_image(results)
                    if self._verbose:
                        print(f"OK -> {current_image}")

                elif step_type == "rembg":
                    if not current_image:
                        raise RuntimeError("rembg needs a previous image")
                    results = self._run_simple(build_rembg(current_image))
                    current_image = self._first_image(results)
                    if self._verbose:
                        print(f"OK -> {current_image}")

                elif step_type == "faceswap":
                    if not current_image:
                        raise RuntimeError("faceswap needs a previous image")
                    source = self._upload(params["source"])
                    results = self._run_simple(build_faceswap(current_image, source))
                    current_image = self._first_image(results)
                    if self._verbose:
                        print(f"OK -> {current_image}")

                elif step_type == "face_restore":
                    if not current_image:
                        raise RuntimeError("face_restore needs a previous image")
                    results = self._run_simple(build_face_restore(
                        current_image, params["model"],
                        "retinaface_resnet50", 1.0, params["weight"]))
                    current_image = self._first_image(results)
                    if self._verbose:
                        print(f"OK -> {current_image}")

                elif step_type == "wan_video":
                    if not current_image:
                        raise RuntimeError("wan_video needs a previous image")
                    results = self._run_wan(current_image, params)
                    if self._verbose:
                        print(f"OK ({len(results)} outputs)")

                elif step_type == "ltx_video":
                    results = self._run_ltx(current_image, params)
                    if self._verbose:
                        print(f"OK ({len(results)} outputs)")

                else:
                    raise RuntimeError(f"Unknown step type: {step_type}")

            except Exception as e:
                if self._verbose:
                    print(f"FAIL: {e}")
                raise

        # Download final outputs
        if self._save_dir and self._results:
            return self._download_results()

        return self._results

    def run_batch(self, **variations):
        """Run the pipeline multiple times with template substitution.

        Usage: .run_batch(color=["red", "blue"], style=["anime", "photo"])
        Generates one run per combination.
        """
        import itertools
        keys = list(variations.keys())
        combos = list(itertools.product(*[variations[k] for k in keys]))

        all_results = []
        for combo in combos:
            subs = dict(zip(keys, combo))
            if self._verbose:
                print(f"\n--- Batch: {subs} ---")
            # Clone pipeline with substituted prompts
            patched = Pipeline(self._server, self._verbose)
            patched._save_dir = self._save_dir
            for step_type, params in self._steps:
                p = dict(params)
                for k, v in p.items():
                    if isinstance(v, str):
                        for var_name, var_val in subs.items():
                            p[k] = p[k].replace(f"{{{var_name}}}", str(var_val))
                patched._steps.append((step_type, p))
            results = patched.run()
            all_results.append((subs, results))

        return all_results

    # ── Internal ────────────────────────────────────────────────────

    def _upload(self, local_path):
        """Upload a local file to ComfyUI's input folder."""
        import uuid
        ext = os.path.splitext(local_path)[1] or ".png"
        remote_name = f"pipeline_{uuid.uuid4().hex[:8]}{ext}"
        data = open(local_path, "rb").read()

        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{remote_name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self._server}/upload/image", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req, timeout=30)
        return remote_name

    def _submit(self, workflow):
        """Preflight + optimize + submit to ComfyUI."""
        try:
            ok, workflow, report = preflight_workflow(workflow, self._server)
            if not ok:
                raise RuntimeError(f"Missing nodes: {report['missing']}")
            workflow, warnings = optimize_workflow(workflow, comfy_url=self._server)
            for w in warnings:
                if self._verbose:
                    print(f"    [opt] {w}")
        except ImportError:
            pass

        body = json.dumps({"prompt": workflow}).encode()
        req = urllib.request.Request(
            f"{self._server}/prompt", data=body,
            headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=10)
        pid = json.loads(r.read()).get("prompt_id")
        if not pid:
            raise RuntimeError("ComfyUI declined the workflow")
        return pid

    def _wait(self, pid, timeout=300):
        """Poll for completion, return outputs dict."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                r = urllib.request.urlopen(
                    f"{self._server}/history/{pid}", timeout=5)
                d = json.loads(r.read())
                if pid in d:
                    st = d[pid].get("status", {})
                    if st.get("completed"):
                        return d[pid].get("outputs", {})
                    for msg in st.get("messages", []):
                        if msg[0] == "execution_error":
                            raise RuntimeError(msg[1].get("exception_message", "?")[:200])
            except RuntimeError:
                raise
            except Exception:
                pass
            time.sleep(2)
        raise RuntimeError(f"Timeout after {timeout}s")

    def _extract_results(self, outputs):
        """Extract (filename, subfolder, type) tuples from ComfyUI outputs."""
        results = []
        for nid, out in outputs.items():
            for key in ("images", "gifs", "videos"):
                for item in out.get(key, []):
                    r = (item["filename"], item.get("subfolder", ""), item.get("type", "output"))
                    results.append(r)
                    self._results.append(r)
        return results

    def _first_image(self, results):
        """Get the first image filename from results (for chaining)."""
        for fn, sf, ft in results:
            if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                # Upload the output back to input folder for next step
                url = f"{self._server}/view?filename={fn}&subfolder={sf}&type={ft}"
                data = urllib.request.urlopen(url, timeout=60).read()
                import uuid
                new_name = f"pipeline_{uuid.uuid4().hex[:8]}.png"
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.write(data)
                tmp.close()
                self._upload_raw(new_name, data)
                os.unlink(tmp.name)
                return new_name
        return results[0][0] if results else None

    def _upload_raw(self, name, data):
        """Upload raw bytes to ComfyUI input folder."""
        import uuid
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self._server}/upload/image", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req, timeout=30)

    def _run_simple(self, workflow):
        """Submit workflow, wait, return results."""
        pid = self._submit(workflow)
        outputs = self._wait(pid)
        return self._extract_results(outputs)

    def _make_preset(self, arch_key, model=""):
        """Build a preset dict for txt2img/img2img."""
        if not model:
            model = self._find_model(arch_key)
        a = get_arch(arch_key)
        _res = {"sd15": (512, 512), "sdxl": (1024, 1024), "illustrious": (1024, 1024),
                "flux1dev": (1024, 1024), "flux2klein": (1024, 1024)}
        dw, dh = _res.get(arch_key, (512, 512))
        return {
            "ckpt": model, "arch": arch_key, "width": dw, "height": dh,
            "steps": a.default_steps, "cfg": a.default_cfg,
            "sampler": a.default_sampler, "scheduler": a.default_scheduler,
            "loader": a.loader, "clip_name1": "", "clip_name2": "", "vae_name": "",
        }

    def _find_model(self, arch_key):
        """Find the best model for an architecture on the server."""
        skip = ("vae", "embeddings", "audio", "clip_", "t5xxl", "umt5",
                "gemma", "qwen", "mistral", "llava")
        for node, field, cfn in [
            ("UnetLoaderGGUF", "unet_name", classify_unet_model),
            ("CheckpointLoaderSimple", "ckpt_name", classify_ckpt_model),
        ]:
            try:
                r = urllib.request.urlopen(f"{self._server}/object_info/{node}", timeout=5)
                d = json.loads(r.read())
                spec = d[node]["input"]["required"][field]
                opts = spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])
                for m in opts:
                    if any(s in m.lower() for s in skip):
                        continue
                    if cfn(m) == arch_key:
                        return m
            except Exception:
                pass
        raise RuntimeError(f"No {arch_key} model found on server")

    def _run_txt2img(self, params):
        arch = params.get("arch", "sdxl")
        preset = self._make_preset(arch, params.get("model", ""))
        if params.get("width"):
            preset["width"] = params["width"]
        if params.get("height"):
            preset["height"] = params["height"]
        if params.get("steps"):
            preset["steps"] = params["steps"]
        if params.get("cfg") is not None:
            preset["cfg"] = params["cfg"]
        seed = params.get("seed", -1)
        if seed < 0:
            seed = random.randint(1, 2**32 - 1)
        wf = build_txt2img(preset, params["prompt"],
                           params.get("negative", ""), seed,
                           loras=params.get("loras"))
        return self._run_simple(wf)

    def _run_img2img(self, image, params):
        arch = params.get("arch", "sdxl")
        preset = self._make_preset(arch, params.get("model", ""))
        seed = random.randint(1, 2**32 - 1)
        wf = build_img2img(image, preset, params["prompt"],
                           params.get("negative", ""), seed)
        return self._run_simple(wf)

    def _run_upscale(self, image, params):
        wf = build_upscale(image, params.get("model", "4x-UltraSharp.pth"))
        return self._run_simple(wf)

    def _run_wan(self, image, params):
        if not build_wan_video:
            raise RuntimeError("WAN video not available")
        # Build WAN preset from server detection
        from .preflight import get_available_nodes
        wan_preset = self._detect_wan_preset()
        seed = random.randint(1, 2**32 - 1)
        wf = build_wan_video(
            image, wan_preset, params["prompt"], params.get("negative", "blurry"), seed,
            width=params.get("width", 576), height=params.get("height", 320),
            length=params.get("length", 33), turbo=params.get("turbo", True),
            rtx_scale=0, interpolate=False, face_swap=False,
            fps=params.get("fps", 16))
        return self._run_simple(wf)

    def _run_ltx(self, image, params):
        if not build_ltx_video:
            raise RuntimeError("LTX video not available")
        ltx_preset = self._detect_ltx_preset()
        seed = random.randint(1, 2**32 - 1)
        kwargs = {
            "prompt_text": params["prompt"], "seed": seed,
            "width": params.get("width", 384), "height": params.get("height", 256),
            "num_frames": params.get("num_frames", 25), "fps": params.get("fps", 25),
        }
        if image:
            kwargs["image_filename"] = image
            kwargs["i2v_strength"] = 0.85
        wf = build_ltx_video(ltx_preset, **kwargs)
        return self._run_simple(wf)

    def _detect_wan_preset(self):
        """Build a WAN preset from server model inventory.

        Canonical detection via `video_presets.detect_wan_preset` — see
        CLAUDE.md §16 "Canonical Video Pipelines". This method is a thin
        per-instance wrapper; the heavy lifting (VAE pairing by UNET
        family, accel-LoRA matching, I2V-only filtering) lives in the
        core module so every consumer agrees.
        """
        from . import video_presets
        preset = video_presets.detect_wan_preset(self._server)
        if not preset:
            raise RuntimeError("No WAN I2V models found on server")
        # pipeline.py's legacy callers expect an "ip_adapter_model"
        # hint even when it's not used; keep it stable.
        preset.setdefault("ip_adapter_model", "ip-adapter-wan2.1-14b.bin")
        return preset

    def _detect_ltx_preset(self):
        """Build an LTX preset from server model inventory.

        Canonical detection via `video_presets.detect_ltx_preset` — see
        CLAUDE.md §16.3 for the recipe.
        """
        from . import video_presets
        preset = video_presets.detect_ltx_preset(self._server)
        if not preset:
            raise RuntimeError("No LTX models found on server")
        # Legacy callers read these extras; preserve for backwards compat.
        preset.setdefault("latent_upscaler", "")
        preset.setdefault("lora_prefix", "ltxv")
        # pipeline.py historically used steps=10 for LTX. detect_ltx_preset
        # returns the canonical 30 (full-step). Leave the canonical value —
        # pipeline's callers that want 10 can override via kwargs.
        return preset

    def _download_results(self):
        """Download all accumulated results to save_dir."""
        os.makedirs(self._save_dir, exist_ok=True)
        saved = []
        for fn, sf, ft in self._results:
            url = f"{self._server}/view?filename={fn}&subfolder={sf}&type={ft}"
            try:
                data = urllib.request.urlopen(url, timeout=120).read()
                dest = os.path.join(self._save_dir, fn)
                with open(dest, "wb") as f:
                    f.write(data)
                saved.append(dest)
                if self._verbose:
                    print(f"  Saved: {dest} ({len(data) / 1024:.0f} KB)")
            except Exception as e:
                if self._verbose:
                    print(f"  Download failed: {fn} ({e})")
        return saved
