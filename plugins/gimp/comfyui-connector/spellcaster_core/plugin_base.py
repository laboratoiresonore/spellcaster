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

    def __init__(self, server_url="http://127.0.0.1:8188",
                 guild_url=None, origin=None):
        self.server = server_url
        self._last_upload = None  # filename on ComfyUI
        self._last_result = None  # (filename, subfolder, type)
        # Canonical URL for the most recent generation — set by
        # `_download_and_insert` after `_stash_in_gallery`. Callers
        # that need a shareable reference (chat embed, save-to-disk
        # link, downstream HTTP consumer) read this rather than
        # reconstructing the ComfyUI /view URL. Falls back to the raw
        # /view URL when no Guild is configured.
        self._last_gallery_url = None
        # Cross-interface backbone (§15). Optional — subclasses that
        # want to participate in AssetGallery / EventBus pass
        # ``guild_url``; leaving it None keeps the plugin purely
        # ComfyUI-direct for users without a Guild. ``origin`` MUST be
        # a KNOWN_INTERFACES key when set ("blender", "krita",
        # "photoshop", …) — the Guild's heartbeat endpoint rejects
        # anything else.
        self._guild_url = (guild_url or "").rstrip("/") or None
        self._origin = origin or ""
        self._heartbeat_started = False
        self._inbox_poll_started = False
        if self._guild_url and self._origin:
            self._start_heartbeat_loop()
            # Start inbox poll so the plugin can RECEIVE peer sends
            # (GIMP → Blender, Resolve → Krita, …). Without this the
            # interface is permanently "send-only" even though the
            # Guild already routes events to its mailbox.
            self._start_inbox_poll_loop()

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

    # ── Cross-interface backbone (optional — gated on guild_url) ──

    def _start_heartbeat_loop(self, interval_s=20):
        """Start a daemon thread that pings the Guild every ``interval_s``.

        Silent no-op when ``self._guild_url`` / ``self._origin`` aren't
        set. Only starts ONCE per plugin instance even if called
        repeatedly — the `_heartbeat_started` guard prevents stacking
        threads across editor reloads or hot-reloads.

        Every ping carries a ``meta`` dict with the plugin version
        (``bl_info`` for Blender, ``__version__`` for Krita) so the
        Guild's UI can surface plugin-version drift. ``remote=False``
        keeps the heartbeat on the LOCAL track (see interface_registry
        R58 — remote antennas use a separate track).
        """
        if self._heartbeat_started or not self._guild_url or not self._origin:
            return
        self._heartbeat_started = True
        import threading as _th
        t = _th.Thread(target=self._heartbeat_loop_body,
                       args=(float(interval_s),),
                       daemon=True,
                       name=f"spellcaster-{self._origin}-heartbeat")
        t.start()

    def _heartbeat_loop_body(self, interval_s):
        """Run loop for the heartbeat thread. NEVER raises — exceptions
        are swallowed so a temporary Guild outage doesn't kill the
        pinger for the rest of the editor session.
        """
        meta = self._heartbeat_meta()
        payload = json.dumps({
            "interface": self._origin, "meta": meta, "remote": False,
        }).encode()
        while True:
            try:
                req = urllib.request.Request(
                    f"{self._guild_url}/api/interfaces/heartbeat",
                    data=payload,
                    headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass  # Guild offline — try again next tick
            time.sleep(interval_s)

    def _heartbeat_meta(self):
        """Override to supply plugin metadata (version, editor name,
        capabilities). Default payload is minimal so the Guild still
        sees SOMETHING even from barebones plugins.
        """
        return {"plugin": self._origin, "transport": "plugin_base"}

    def _start_inbox_poll_loop(self, interval_s=20):
        """Start a daemon thread that drains this plugin's Guild
        inbox every ``interval_s`` and calls
        :meth:`_on_inbox_message` for each received event.

        Enables peer-send (GIMP → Blender, Resolve → Krita, …): when
        another plugin publishes ``<this_origin>.asset.send``, the
        mailbox fanout on the Guild side routes it to this interface's
        per-key queue, and this loop pops + dispatches it.

        Silent no-op when ``self._guild_url`` / ``self._origin``
        aren't set. Only starts ONCE per plugin instance — the
        ``_inbox_poll_started`` guard prevents stacking loops across
        editor reloads.

        Subclasses override ``_on_inbox_message(msg)`` to actually
        insert received bytes into their editor. Default
        implementation does nothing, so adding the poll loop to a
        new plugin is harmless even before it wires up the handler.
        """
        if (getattr(self, "_inbox_poll_started", False)
                or not self._guild_url or not self._origin):
            return
        self._inbox_poll_started = True
        import threading as _th
        t = _th.Thread(target=self._inbox_poll_loop_body,
                       args=(float(interval_s),),
                       daemon=True,
                       name=f"spellcaster-{self._origin}-inbox")
        t.start()

    def _inbox_poll_loop_body(self, interval_s):
        """Run loop for the inbox poller. NEVER raises — errors
        swallowed so a temporary Guild outage doesn't kill the poller.
        """
        while True:
            try:
                req = urllib.request.Request(
                    f"{self._guild_url}/api/{self._origin}/inbox?consume=1&max=20",
                    headers={"Accept": "application/json"})
                body = urllib.request.urlopen(req, timeout=5).read()
                msgs = (json.loads(body) or {}).get("messages") or []
                for m in msgs:
                    try:
                        self._on_inbox_message(m)
                    except Exception as _e:
                        self.show_error(
                            f"Inbox message dispatch failed: {_e}")
            except Exception:
                pass  # Guild offline — try again next tick
            time.sleep(interval_s)

    def _on_inbox_message(self, msg):
        """Override to handle a popped mailbox message.

        ``msg`` is the raw event dict (shape defined by
        ``spellcaster_core.events.AssetSend`` for ``*.asset.send``
        kinds). Subclasses typically pull ``msg['data']['image_url']``,
        resolve it against ``self._guild_url`` if relative, download,
        and call ``self.insert_layer(bytes, name)``.

        Default implementation: auto-handle ``*.asset.send`` by
        downloading the referenced asset and inserting as a layer.
        Subclasses with richer needs (Photoshop layer-group,
        Blender image-editor binding) override this.
        """
        kind = str(msg.get("kind") or "")
        data = msg.get("data") or {}
        if not kind.endswith(".asset.send"):
            return
        image_url = (data.get("image_url") or data.get("url") or "").strip()
        if not image_url:
            return
        if image_url.startswith("/"):
            image_url = self._guild_url.rstrip("/") + image_url
        # Scheme clamp — refuse file://, gopher://, etc.
        from urllib.parse import urlparse as _urlparse
        try:
            scheme = _urlparse(image_url).scheme.lower()
        except Exception:
            scheme = ""
        if scheme not in ("http", "https"):
            return
        try:
            # Cap at 100 MB — an adversarial peer could otherwise push
            # arbitrarily large bytes into the editor's memory.
            _MAX = 100 * 1024 * 1024
            resp_bytes = urllib.request.urlopen(image_url, timeout=30).read(_MAX + 1)
            if len(resp_bytes) > _MAX or len(resp_bytes) < 64:
                return
        except Exception:
            return
        label = data.get("title") or data.get("source") or "peer asset"
        try:
            self.insert_layer(resp_bytes, f"From {label}")
        except NotImplementedError:
            pass  # Subclass doesn't implement insert_layer — no-op.

    def _stash_in_gallery(self, png_bytes, *, kind="generation",
                           title=None, prompt=None, model=None, seed=None,
                           tags=None):
        """Push generated bytes into the Guild's AssetGallery.

        Fire-and-forget: any exception is swallowed. Returns the
        canonical ``/api/assets/<hash>`` URL on success, ``None``
        otherwise. Editors keep the bytes locally; the gallery stash
        is additive for cross-interface visibility (GIMP / Darktable /
        Resolve / SillyTavern / Signal subscribers see the generation
        land in real time).

        No-ops silently when ``self._guild_url`` / ``self._origin``
        aren't set (purely ComfyUI-direct mode).
        """
        if not png_bytes or not self._guild_url or not self._origin:
            return None
        try:
            import base64 as _b64
            body = json.dumps({
                "origin": self._origin,
                "kind": kind,
                "title": title or f"{self._origin} {kind}",
                "prompt": prompt,
                "model": model,
                "seed": seed,
                "tags": list(tags or []) + [f"{self._origin}_generation"],
                "body_b64": _b64.b64encode(png_bytes).decode("ascii"),
            }).encode()
            req = urllib.request.Request(
                f"{self._guild_url}/api/assets",
                data=body,
                headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=30).read()
            rec = json.loads(resp).get("data") or {}
            h = rec.get("hash")
            if h:
                return f"{self._guild_url}/api/assets/{h}"
        except Exception:
            pass
        return None

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
                            # Cross-interface stash (§15). No-ops when
                            # the plugin wasn't constructed with a
                            # guild_url; otherwise pushes the bytes
                            # into AssetGallery so every other plugin
                            # sees the generation via
                            # ``<origin>.asset.created``.
                            gallery_url = self._stash_in_gallery(
                                data, kind=label, title=fn)
                            # Record the canonical URL on the plugin
                            # so callers that want it can
                            # ``plugin._last_gallery_url`` without
                            # re-reading the bytes. Falls back to the
                            # raw ComfyUI /view URL only when the
                            # gallery stash didn't happen (no guild
                            # configured or upload failed).
                            self._last_gallery_url = gallery_url or url
                            self.show_progress(f"Done! ({len(data)//1024} KB)")
                            return data
                    except Exception as e:
                        self.show_error(f"Download failed: {e}")
        return None
