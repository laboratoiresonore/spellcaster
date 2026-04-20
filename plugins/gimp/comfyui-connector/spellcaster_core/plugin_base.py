"""Plugin Base — shared logic for all editor plugins (Krita, Blender, Photoshop, etc.)

Every editor plugin does the same 5 steps:
  1. Get pixels from the editor (editor-specific)
  2. Upload to ComfyUI
  3. Build + preflight + optimize + submit workflow
  4. Download result
  5. Insert back into editor (editor-specific)

This base class handles steps 2-4. Each editor plugin subclasses it
and implements get_pixels() and insert_result().

Usage (Krita example):
    class KritaSpellcaster(SpellcasterPlugin):
        def get_canvas_png(self):
            # Krita-specific: export active layer as PNG bytes
            ...
        def insert_layer(self, png_bytes, name):
            # Krita-specific: create new layer from PNG
            ...

    plugin = KritaSpellcaster("http://192.168.x.x:8188")
    plugin.txt2img("a magical forest", arch="sdxl")
    plugin.upscale()
    plugin.img2img("oil painting style", denoise=0.4)
"""

import json
import os
import tempfile
import time
import uuid
import urllib.request
import urllib.error

try:
    from .workflows import (
        build_txt2img, build_img2img, build_upscale, build_rembg,
        build_faceswap, build_face_restore, build_style_transfer,
        build_iclight, build_lut, build_inpaint,
    )
    from .architectures import get_arch
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .preflight import preflight_workflow
    from .optimizer import optimize_workflow
    from .recommend import recommend
except ImportError:
    from spellcaster_core.workflows import (
        build_txt2img, build_img2img, build_upscale, build_rembg,
        build_faceswap, build_face_restore, build_style_transfer,
        build_iclight, build_lut, build_inpaint,
    )
    from spellcaster_core.architectures import get_arch
    from spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model
    from spellcaster_core.preflight import preflight_workflow
    from spellcaster_core.optimizer import optimize_workflow
    from spellcaster_core.recommend import recommend


class SpellcasterPlugin:
    """Base class for all Spellcaster editor plugins.

    Subclass this and implement:
      - get_canvas_png() -> bytes: export current canvas/selection as PNG
      - insert_layer(png_bytes, name) -> None: import PNG as new layer
      - show_progress(message) -> None: update status (optional)
      - show_error(message) -> None: show error to user (optional)
    """

    def __init__(self, server_url="http://127.0.0.1:8188"):
        self.server = server_url
        self._last_upload = None  # filename on ComfyUI
        self._last_result = None  # (filename, subfolder, type)

    # ── Abstract methods (override in subclass) ──────────────────

    def get_canvas_png(self):
        """Export current canvas/selection as PNG bytes. Override this."""
        raise NotImplementedError

    def insert_layer(self, png_bytes, name="Spellcaster"):
        """Import PNG bytes as a new layer in the editor. Override this."""
        raise NotImplementedError

    def show_progress(self, message):
        """Update progress status. Override for editor-specific UI."""
        print(f"[Spellcaster] {message}")

    def show_error(self, message):
        """Show error to user. Override for editor-specific UI."""
        print(f"[Spellcaster ERROR] {message}")

    # ── Core operations (shared by all plugins) ──────────────────

    def upload_canvas(self):
        """Export canvas and upload to ComfyUI input folder."""
        self.show_progress("Exporting canvas...")
        png = self.get_canvas_png()
        name = f"spellcaster_{uuid.uuid4().hex[:8]}.png"
        self._upload_raw(name, png)
        self._last_upload = name
        return name

    def txt2img(self, prompt, negative="", arch="", model="",
                width=0, height=0, steps=0, cfg=None, seed=-1, loras=None,
                quality="balanced", fast_mode=False):
        """Generate an image from text and insert as layer.

        quality: "fast" | "balanced" (default) | "max". Controls the
            per-arch quality booster stack (PAG, RescaleCFG, FreeU_V2,
            SLG, AYS) wired by workflows.build_txt2img.
        fast_mode: opt-in TeaCache for Flux 1 Dev. Requires the
            ComfyUI-TeaCache custom pack on the server.
        """
        if not arch:
            rec = recommend(prompt, server=self.server)
            arch = rec["arch"]
            self.show_progress(f"Auto-selected: {arch}")

        preset = self._make_preset(arch, model, width, height, steps, cfg)
        if not preset:
            return

        import random
        if seed < 0:
            seed = random.randint(1, 2**32 - 1)

        a = get_arch(arch)
        if a and a.quality_positive and arch not in ("flux1dev", "flux2klein", "chroma"):
            prompt = f"{prompt}, {a.quality_positive}"
        if a and a.supports_negative and a.quality_negative:
            negative = f"{negative}, {a.quality_negative}" if negative else a.quality_negative

        wf = build_txt2img(preset, prompt, negative, seed, loras=loras,
                           quality=quality, fast_mode=fast_mode)
        return self._run_workflow(wf, "txt2img")

    def img2img(self, prompt, negative="", denoise=0.55, arch="sdxl", model="",
                 quality="balanced", fast_mode=False):
        """Transform the canvas with a prompt and insert result as layer.

        See :meth:`txt2img` for quality/fast_mode semantics.
        """
        name = self.upload_canvas()
        preset = self._make_preset(arch, model)
        if not preset:
            return
        import random
        wf = build_img2img(name, preset, prompt, negative,
                            random.randint(1, 2**32 - 1),
                            quality=quality, fast_mode=fast_mode)
        return self._run_workflow(wf, "img2img")

    def upscale(self, upscale_model="4x-UltraSharp.pth"):
        """Upscale the canvas and insert result as layer."""
        name = self._last_upload or self.upload_canvas()
        wf = build_upscale(name, upscale_model)
        return self._run_workflow(wf, "upscale")

    def rembg(self):
        """Remove background from canvas and insert result as layer."""
        name = self._last_upload or self.upload_canvas()
        wf = build_rembg(name)
        return self._run_workflow(wf, "rembg")

    def faceswap(self, source_png_bytes):
        """Swap face from source onto canvas."""
        target = self._last_upload or self.upload_canvas()
        source_name = f"spellcaster_src_{uuid.uuid4().hex[:8]}.png"
        self._upload_raw(source_name, source_png_bytes)
        wf = build_faceswap(target, source_name)
        return self._run_workflow(wf, "faceswap")

    def face_restore(self, model="codeformer-v0.1.0.pth", weight=0.7):
        """Restore/enhance faces in canvas."""
        name = self._last_upload or self.upload_canvas()
        wf = build_face_restore(name, model, "retinaface_resnet50", 1.0, weight)
        return self._run_workflow(wf, "face_restore")

    def style_transfer(self, style_png_bytes, prompt="apply style", arch="sdxl"):
        """Transfer style from reference image onto canvas."""
        content = self._last_upload or self.upload_canvas()
        style_name = f"spellcaster_style_{uuid.uuid4().hex[:8]}.png"
        self._upload_raw(style_name, style_png_bytes)
        preset = self._make_preset(arch)
        if not preset:
            return
        import random
        wf = build_style_transfer(content, style_name, preset, prompt, "", random.randint(1, 2**32 - 1))
        return self._run_workflow(wf, "style_transfer")

    def auto(self, prompt):
        """Smart generation — auto-pick model, arch, resolution from prompt."""
        rec = recommend(prompt, server=self.server)
        self.show_progress(f"Intent: {rec['intent']} -> {rec['arch']}")
        return self.txt2img(
            prompt, arch=rec["arch"],
            width=rec["settings"].get("width", 0),
            height=rec["settings"].get("height", 0),
            steps=rec["settings"].get("steps", 0),
            cfg=rec["settings"].get("cfg"),
        )

    # ── Internal helpers ─────────────────────────────────────────

    def _upload_raw(self, name, data):
        """Upload raw bytes to ComfyUI input folder."""
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self.server}/upload/image", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req, timeout=30)

    def _make_preset(self, arch, model="", width=0, height=0, steps=0, cfg=None):
        """Build a generation preset."""
        if not model:
            model = self._find_model(arch)
        if not model:
            self.show_error(f"No {arch} model found on server")
            return None
        a = get_arch(arch)
        _res = {"sd15": (512, 512), "sdxl": (1024, 1024), "illustrious": (1024, 1024),
                "flux1dev": (1024, 1024), "flux2klein": (1024, 1024), "chroma": (1024, 1024)}
        dw, dh = _res.get(arch, (512, 512))
        return {
            "ckpt": model, "arch": arch,
            "width": width or dw, "height": height or dh,
            "steps": steps or (a.default_steps if a else 20),
            "cfg": cfg if cfg is not None else (a.default_cfg if a else 7.0),
            "sampler": a.default_sampler if a else "euler",
            "scheduler": a.default_scheduler if a else "normal",
            "loader": a.loader if a else "checkpoint",
            "clip_name1": "", "clip_name2": "", "vae_name": "",
        }

    def _find_model(self, arch_key):
        """Find a model for an architecture on the server."""
        skip = ("vae", "embeddings", "audio", "clip_", "t5xxl", "umt5",
                "gemma", "qwen", "mistral", "llava", "connector")
        for node, field, cfn in [
            ("UnetLoaderGGUF", "unet_name", classify_unet_model),
            ("UNETLoader", "unet_name", classify_unet_model),
            ("CheckpointLoaderSimple", "ckpt_name", classify_ckpt_model),
        ]:
            try:
                r = urllib.request.urlopen(f"{self.server}/object_info/{node}", timeout=5)
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
        return None

    def _run_workflow(self, workflow, label="generation"):
        """Preflight + optimize + submit + download + insert."""
        # Preflight
        self.show_progress(f"Checking nodes...")
        try:
            ok, workflow, report = preflight_workflow(workflow, self.server)
            if report.get("substituted"):
                for orig, desc in report["substituted"]:
                    self.show_progress(f"Fallback: {desc}")
            if not ok:
                self.show_error(f"Missing nodes: {', '.join(report['missing'])}")
                return None
        except Exception:
            pass

        # Optimize
        try:
            workflow, warnings = optimize_workflow(workflow, comfy_url=self.server)
            for w in warnings:
                self.show_progress(f"Optimizer: {w}")
        except Exception:
            pass

        # Submit
        self.show_progress(f"Submitting {label}...")
        body = json.dumps({"prompt": workflow}).encode()
        req = urllib.request.Request(
            f"{self.server}/prompt", data=body,
            headers={"Content-Type": "application/json"})
        try:
            r = urllib.request.urlopen(req, timeout=10)
            pid = json.loads(r.read()).get("prompt_id")
        except urllib.error.HTTPError as e:
            err = json.loads(e.read().decode())
            self.show_error(f"Rejected: {json.dumps(err.get('node_errors', {}))[:200]}")
            return None

        if not pid:
            self.show_error("No prompt_id returned")
            return None

        # Poll
        self.show_progress(f"Generating ({label})...")
        t0 = time.time()
        while time.time() - t0 < 300:
            try:
                r = urllib.request.urlopen(f"{self.server}/history/{pid}", timeout=5)
                d = json.loads(r.read())
                if pid in d:
                    st = d[pid].get("status", {})
                    if st.get("completed"):
                        outputs = d[pid].get("outputs", {})
                        return self._download_and_insert(outputs, label)
                    for msg in st.get("messages", []):
                        if msg[0] == "execution_error":
                            self.show_error(msg[1].get("exception_message", "?")[:200])
                            return None
            except Exception:
                pass
            time.sleep(2)
            elapsed = int(time.time() - t0)
            self.show_progress(f"Generating ({label})... {elapsed}s")

        self.show_error("Timeout")
        return None

    def _download_and_insert(self, outputs, label):
        """Download output images and insert as layers."""
        for nid, out in outputs.items():
            for key in ("images", "gifs", "videos"):
                for item in out.get(key, []):
                    fn = item["filename"]
                    sf = item.get("subfolder", "")
                    ft = item.get("type", "output")
                    url = f"{self.server}/view?filename={fn}&subfolder={sf}&type={ft}"
                    try:
                        # 500 MB cap — same as cli.download_output. Beyond
                        # this the server is streaming garbage and we'd
                        # rather surface an error than hang the editor.
                        _MAX = 500 * 1024 * 1024
                        data = urllib.request.urlopen(url, timeout=120).read(_MAX + 1)
                        if len(data) > _MAX:
                            raise IOError(f"/view exceeded {_MAX} bytes")
                        if len(data) > 100:
                            self._last_upload = None
                            # Re-upload for chaining
                            chain_name = f"spellcaster_{uuid.uuid4().hex[:8]}.png"
                            if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                                self._upload_raw(chain_name, data)
                                self._last_upload = chain_name
                            self.insert_layer(data, f"{label}: {fn}")
                            self.show_progress(f"Done! ({len(data)//1024} KB)")
                            return data
                    except Exception as e:
                        self.show_error(f"Download failed: {e}")
        return None
