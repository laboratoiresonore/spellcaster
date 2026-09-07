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
        build_outpaint, build_normal_map,
        build_detail_hallucinate, build_colorize, build_magic_eraser,
        build_ltx_video, build_wan_video,
    )
    from .architectures import get_arch
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .preflight import preflight_workflow
    from .optimizer import optimize_workflow
    from .recommend import recommend
    from .video_presets import (
        detect_ltx_preset, detect_wan_preset, ltx_mode_kwargs,
        wan_turbo_kwargs,
    )
except ImportError:
    from .workflows import (
        build_txt2img, build_img2img, build_upscale, build_rembg,
        build_faceswap, build_face_restore, build_style_transfer,
        build_iclight, build_lut, build_inpaint,
        build_outpaint, build_normal_map,
        build_detail_hallucinate, build_colorize, build_magic_eraser,
        build_ltx_video, build_wan_video,
    )
    from .architectures import get_arch
    from .model_detect import classify_unet_model, classify_ckpt_model
    from .preflight import preflight_workflow
    from .optimizer import optimize_workflow
    from .recommend import recommend
    from .video_presets import (
        detect_ltx_preset, detect_wan_preset, ltx_mode_kwargs,
        wan_turbo_kwargs,
    )


# Module-level single-start guards for the background loops.
# Blender's F8 script-reload + Krita's script_manager reload create
# fresh plugin INSTANCES from a fresh module import, so an
# instance-level guard (``self._heartbeat_started``) wouldn't survive
# across reloads and two loops would stack. Keying by ``origin``
# deduplicates across all reloads in the same process: the OLD
# thread stays alive (daemon, harmless), the new instance sees the
# guard is set and skips spawning a second pinger.
#
# Blender F8 reload DOES rebuild sys.modules so this set is wiped
# and a new thread starts; the OLD thread still ticks against the
# OLD server/guild URL. Users who hit F8 10× per day get 10
# accumulated daemon threads — acceptable (each ~5 KB stack, ticks
# every 20 s, swallowed exceptions) but worth knowing.
_HEARTBEAT_ORIGINS_STARTED = set()
_INBOX_ORIGINS_STARTED = set()


class SpellcasterPlugin:
    """Base class for all Spellcaster editor plugins.

    Subclass this and implement:
      - get_canvas_png() -> bytes: export current canvas/selection as PNG
      - insert_layer(png_bytes, name) -> None: import PNG as new layer
      - show_progress(message) -> None: update status (optional)
      - show_error(message) -> None: show error to user (optional)
    """

    def __init__(self, server_url: str = "http://127.0.0.1:8188",
                 guild_url: str | None = None,
                 origin: str | None = None) -> None:
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

    def get_canvas_png(self) -> bytes:
        """Export current canvas/selection as PNG bytes. Override this."""
        raise NotImplementedError

    def insert_layer(self, png_bytes: bytes,
                      name: str = "Spellcaster") -> None:
        """Import PNG bytes as a new layer in the editor. Override this."""
        raise NotImplementedError

    def show_progress(self, message: str) -> None:
        """Update progress status. Override for editor-specific UI."""
        print(f"[Spellcaster] {message}")

    def show_error(self, message: str) -> None:
        """Show error to user. Override for editor-specific UI."""
        print(f"[Spellcaster ERROR] {message}")

    # ── Core operations (shared by all plugins) ──────────────────

    def upload_canvas(self) -> str:
        """Export canvas and upload to ComfyUI input folder."""
        self.show_progress("Exporting canvas...")
        png = self.get_canvas_png()
        name = f"spellcaster_{uuid.uuid4().hex[:8]}.png"
        self._upload_raw(name, png)
        self._last_upload = name
        return name

    def txt2img(self, prompt: str, negative: str = "",
                arch: str = "", model: str = "",
                width: int = 0, height: int = 0, steps: int = 0,
                cfg: float | None = None, seed: int = -1,
                loras: list | None = None,
                quality: str = "balanced",
                fast_mode: bool = False) -> bytes | None:
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

    def img2img(self, prompt: str, negative: str = "",
                 denoise: float = 0.55, arch: str = "sdxl",
                 model: str = "",
                 quality: str = "balanced",
                 fast_mode: bool = False) -> bytes | None:
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

    def upscale(self, upscale_model: str = "4x-UltraSharp.pth") -> bytes | None:
        """Upscale the canvas and insert result as layer."""
        name = self._last_upload or self.upload_canvas()
        wf = build_upscale(name, upscale_model)
        return self._run_workflow(wf, "upscale")

    def rembg(self) -> bytes | None:
        """Remove background from canvas and insert result as layer."""
        name = self._last_upload or self.upload_canvas()
        wf = build_rembg(name)
        return self._run_workflow(wf, "rembg")

    def faceswap(self, source_png_bytes: bytes) -> bytes | None:
        """Swap face from source onto canvas."""
        target = self._last_upload or self.upload_canvas()
        source_name = f"spellcaster_src_{uuid.uuid4().hex[:8]}.png"
        self._upload_raw(source_name, source_png_bytes)
        wf = build_faceswap(target, source_name)
        return self._run_workflow(wf, "faceswap")

    def face_restore(self, model: str = "codeformer-v0.1.0.pth",
                      weight: float = 0.7) -> bytes | None:
        """Restore/enhance faces in canvas."""
        name = self._last_upload or self.upload_canvas()
        wf = build_face_restore(name, model, "retinaface_resnet50", 1.0, weight)
        return self._run_workflow(wf, "face_restore")

    def style_transfer(self, style_png_bytes: bytes,
                        prompt: str = "apply style",
                        arch: str = "sdxl") -> bytes | None:
        """Transfer style from reference image onto canvas."""
        content = self._last_upload or self.upload_canvas()
        style_name = f"spellcaster_style_{uuid.uuid4().hex[:8]}.png"
        self._upload_raw(style_name, style_png_bytes)
        preset = self._make_preset(arch)
        if not preset:
            return None
        import random
        wf = build_style_transfer(content, style_name, preset, prompt, "", random.randint(1, 2**32 - 1))
        return self._run_workflow(wf, "style_transfer")

    def auto(self, prompt: str) -> bytes | None:
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

    # ── Extended operations (2026-04-20) ─────────────────────────
    # Each method supplies an abstract hook the subclass can
    # override. Default implementations raise `NotImplementedError`
    # with a message pointing at the hook so editor plugins don't
    # fail silently when they haven't wired the capability yet.

    def get_mask_png(self):
        """Export the active SELECTION / alpha-mask as a grayscale
        PNG (white = inpaint here, black = keep). Override in the
        subclass when the editor exposes a selection (Krita selection,
        Photoshop quick-mask, GIMP selection channel).

        Returns ``None`` when no selection is active; raises only if
        the editor CAN'T produce a mask despite one existing.
        """
        return None

    def get_normal_map_png(self):
        """Export an existing 3D normal-map layer if the user has one.
        Optional hook used by :meth:`iclight` for surface-aware
        relighting. Default: no normal map \u2014 IC-Light falls back
        to flat FC-mode relighting."""
        return None

    def inpaint(self, prompt, negative="", denoise=0.65, arch="sdxl",
                 model="", quality="balanced", fast_mode=False):
        """Regenerate a selected region while preserving the rest.

        Requires the subclass to implement :meth:`get_mask_png` \u2014
        a grayscale PNG where white marks the region to regenerate.
        When the editor has no selection, raises a clear error so
        users know to make one first.
        """
        mask_bytes = None
        try:
            mask_bytes = self.get_mask_png()
        except Exception as e:
            self.show_error(f"Mask export failed: {e}")
            return None
        if not mask_bytes:
            self.show_error(
                "Inpaint requires a selection. Make one first (the "
                "selected region is what will be regenerated) and "
                "run inpaint again.")
            return None
        # Upload image + mask to ComfyUI. We intentionally use
        # ``_upload_raw`` not ``upload_canvas`` so the two uploads
        # share a single UUID root (easier to grep in privacy logs).
        import uuid as _u
        stem = _u.uuid4().hex[:8]
        image_name = f"spellcaster_inp_{stem}.png"
        mask_name = f"spellcaster_mask_{stem}.png"
        self.show_progress("Uploading canvas + mask...")
        self._upload_raw(image_name, self.get_canvas_png())
        self._upload_raw(mask_name, mask_bytes)
        self._last_upload = image_name
        preset = self._make_preset(arch, model)
        if not preset:
            return None
        preset["denoise"] = float(denoise)
        import random
        wf = build_inpaint(
            image_name, mask_name, preset, prompt, negative,
            random.randint(1, 2 ** 32 - 1),
            quality=quality, fast_mode=fast_mode)
        return self._run_workflow(wf, "inpaint")

    def outpaint(self, prompt, negative="",
                  left=0, top=0, right=256, bottom=0, feathering=40,
                  arch="sdxl", model="",
                  quality="balanced", fast_mode=False):
        """Extend the canvas on any combination of edges.

        ``left / top / right / bottom`` are pixel amounts to grow on
        each edge. Default extends 256 px to the right; pass the edge
        set that matches the user's intent. ``feathering`` smooths
        the seam between original + generated pixels.
        """
        name = self.upload_canvas()
        preset = self._make_preset(arch, model)
        if not preset:
            return None
        import random
        wf = build_outpaint(
            name, preset, prompt, negative,
            random.randint(1, 2 ** 32 - 1),
            int(left), int(top), int(right), int(bottom),
            int(feathering),
            quality=quality, fast_mode=fast_mode)
        return self._run_workflow(wf, "outpaint")

    def iclight(self, prompt, negative="", multiplier=0.18,
                 steps=20, cfg=2.0, arch="sd15", model=""):
        """IC-Light relighting \u2014 change lighting direction + colour.

        Uses SD 1.5's IC-Light FC model by default. When the subclass
        provides a normal map via :meth:`get_normal_map_png`, the
        workflow routes it through a proper normal-map ControlNet for
        surface-aware relighting (Bug B fix from 2026-04-20). Without
        a normal map, relight is flat but still useful.
        """
        name = self.upload_canvas()
        # Pick an SD-1.5 checkpoint: caller's ``model`` wins if given,
        # else the first SD-1.5 preset on the server.
        preset = self._make_preset(arch, model)
        if not preset:
            return None
        ckpt_name = preset.get("ckpt") or model or ""
        if not ckpt_name:
            self.show_error(
                "IC-Light needs an SD-1.5 checkpoint. Set one in your "
                "Spellcaster settings or install a SD-1.5 model.")
            return None
        # Optional normal map: upload if the subclass exposes one.
        normal_name = None
        try:
            nm_bytes = self.get_normal_map_png()
        except Exception:
            nm_bytes = None
        if nm_bytes:
            import uuid as _u
            normal_name = f"spellcaster_iclight_nm_{_u.uuid4().hex[:8]}.png"
            self._upload_raw(normal_name, nm_bytes)
        import random
        wf = build_iclight(
            name, ckpt_name, prompt, negative,
            random.randint(1, 2 ** 32 - 1),
            multiplier=float(multiplier),
            steps=int(steps), cfg=float(cfg),
            normal_map_filename=normal_name)
        return self._run_workflow(wf, "iclight")

    def face_swap(self, source_image_bytes,
                    swap_model="inswapper_128.onnx"):
        """Swap the face on the canvas for the one in
        ``source_image_bytes`` (PNG / JPEG). ReActor-based; requires
        the ComfyUI-ReActor node pack on the server."""
        if not source_image_bytes:
            self.show_error(
                "Face Swap needs a source face image. Pass "
                "``source_image_bytes`` from a file picker / "
                "clipboard / layer selection.")
            return None
        target_name = self.upload_canvas()
        import uuid as _u
        src_name = f"spellcaster_face_src_{_u.uuid4().hex[:8]}.png"
        self._upload_raw(src_name, source_image_bytes)
        wf = build_faceswap(target_name, src_name,
                             swap_model=swap_model)
        return self._run_workflow(wf, "face_swap")

    def normal_map(self, max_res=1024):
        """Generate a 3D surface-normal map of the active canvas.

        Runs NormalCrafter on the server and inserts the resulting
        RGB normal-map as a new layer. The layer is named
        ``"Normal Map (auto)"`` so subsequent IC-Light / inpaint /
        img2img calls can pick it up via
        :meth:`get_normal_map_png`-aware downstream logic.
        """
        name = self.upload_canvas()
        import random
        wf = build_normal_map(name,
                                seed=random.randint(1, 2 ** 31),
                                max_res=int(max_res))
        return self._run_workflow(wf, "normal_map")

    # ── Extended operations (2026-04-20 capability parity) ────────
    # These match the GIMP plugin's capability set within reason: any
    # op needing a canvas is gated on the subclass implementing
    # ``get_canvas_png``. Video / text-only ops work on any plugin.

    def detail_hallucinate(self, prompt: str, negative: str = "",
                            upscale_model: str = "4x-UltraSharp.pth",
                            upscale_factor: float = 1.0,
                            denoise: float = 0.35,
                            cfg: float | None = None,
                            steps: int | None = None,
                            arch: str = "sdxl", model: str = "",
                            quality: str = "balanced") -> bytes | None:
        """Super-resolve + add photographic detail via img2img diffusion.

        GIMP's most-used upscale path. Runs an ESRGAN pass then a low-
        denoise diffusion pass so the upscaler can hallucinate pores,
        fabric weave, stone texture. ``denoise`` 0.25-0.45 is the
        sweet spot — higher drifts from the source, lower barely adds
        detail.
        """
        name = self._last_upload or self.upload_canvas()
        preset = self._make_preset(arch, model, steps=steps or 0,
                                    cfg=cfg)
        if not preset:
            return None
        import random
        wf = build_detail_hallucinate(
            name, upscale_model, preset, prompt, negative,
            random.randint(1, 2 ** 32 - 1),
            denoise=float(denoise),
            cfg=float(preset["cfg"]),
            steps=int(preset["steps"]),
            upscale_factor=float(upscale_factor),
            quality=quality)
        return self._run_workflow(wf, "detail_hallucinate")

    def colorize(self, prompt: str = "", negative: str = "",
                  controlnet_strength: float = 0.7,
                  denoise: float = 0.85, arch: str = "sdxl",
                  model: str = "",
                  quality: str = "balanced") -> bytes | None:
        """Colorize a B&W image. Uses lineart ControlNet + low-denoise
        diffusion, so the line structure stays locked while the diffuser
        fills in hues. ``prompt`` is optional — hints help
        ("warm sunset", "1970s kodachrome") but the default colour
        preset works for most photos.
        """
        name = self._last_upload or self.upload_canvas()
        preset = self._make_preset(arch, model)
        if not preset:
            return None
        import random
        wf = build_colorize(
            name, preset, prompt, negative,
            random.randint(1, 2 ** 32 - 1),
            controlnet_strength=float(controlnet_strength),
            denoise=float(denoise),
            quality=quality)
        return self._run_workflow(wf, "colorize")

    def magic_eraser(self, prompt: str, confidence: float = 0.6,
                      mask_expand: int = 8,
                      mask_blur: int = 4) -> bytes | None:
        """Remove an unwanted object by describing it.

        SAM3 segments the described object, LaMa inpaints over the
        mask. No selection needed — just a prompt ("power line",
        "watermark", "tourist in background").
        """
        name = self._last_upload or self.upload_canvas()
        wf = build_magic_eraser(
            name, prompt,
            confidence=float(confidence),
            mask_expand=int(mask_expand),
            mask_blur=int(mask_blur))
        return self._run_workflow(wf, "magic_eraser")

    def style_transfer_from_bytes(self, style_bytes: bytes,
                                    prompt: str = "",
                                    negative: str = "",
                                    weight: float = 0.8,
                                    denoise: float = 0.55,
                                    arch: str = "sdxl",
                                    model: str = "",
                                    quality: str = "balanced"
                                    ) -> bytes | None:
        """IPAdapter-based style transfer from a reference image.

        ``style_bytes`` is the style reference PNG (from file picker,
        clipboard, or a second layer). The canvas is the target.
        Alias distinct from :meth:`style_transfer` so UIs can offer
        both an IPAdapter path and a dispatch-style path.
        """
        if not style_bytes:
            self.show_error("Style transfer needs a reference image.")
            return None
        target = self._last_upload or self.upload_canvas()
        style_name = f"spellcaster_style_{uuid.uuid4().hex[:8]}.png"
        self._upload_raw(style_name, style_bytes)
        preset = self._make_preset(arch, model)
        if not preset:
            return None
        import random
        wf = build_style_transfer(
            target, style_name, preset, prompt, negative,
            random.randint(1, 2 ** 32 - 1),
            weight=float(weight),
            denoise=float(denoise),
            quality=quality)
        return self._run_workflow(wf, "style_transfer")

    def ltx_t2v(self, prompt: str, negative: str | None = None,
                 seconds: float = 3.0, fps: int = 25,
                 width: int = 1280, height: int = 720,
                 mode: str = "distilled") -> bytes | None:
        """Text-to-video via LTX 2.3. No canvas needed.

        ``mode`` is ``"distilled"`` (8-step fast, default),
        ``"full"`` (30-step quality), or ``"two_stage"`` (half-res
        + latent upscale — slowest, best detail).

        Resolution is clamped to mod-32; frame count derives from
        ``seconds * fps`` clamped to [17, 161] (LTX's safe range).
        """
        preset = detect_ltx_preset(self.server)
        if not preset:
            self.show_error(
                "No LTX 2.3 models found on the server. Install the "
                "LTX model family to use text-to-video.")
            return None
        # Snap WxH to mod-32 (LTX hard requirement).
        def _snap32(v):
            v = int(v) // 32 * 32
            return max(256, v)
        w, h = _snap32(width), _snap32(height)
        # LTX is safest between 17 and 161 frames.
        nframes = max(17, min(161, int(float(seconds) * float(fps))))
        import random
        kwargs = ltx_mode_kwargs(mode)
        wf = build_ltx_video(
            preset, prompt,
            random.randint(1, 2 ** 32 - 1),
            width=w, height=h, num_frames=nframes, fps=int(fps),
            negative_text=negative,
            **kwargs)
        return self._run_workflow(wf, "ltx_t2v")

    def ltx_i2v(self, prompt: str, negative: str | None = None,
                 seconds: float = 3.0, fps: int = 25,
                 width: int = 1280, height: int = 720,
                 i2v_strength: float = 0.9) -> bytes | None:
        """Image-to-video via LTX 2.3 distilled I2V. Uses the current
        canvas as the seed frame.
        """
        preset = detect_ltx_preset(self.server)
        if not preset:
            self.show_error("No LTX 2.3 models found on the server.")
            return None
        name = self._last_upload or self.upload_canvas()
        def _snap32(v):
            v = int(v) // 32 * 32
            return max(256, v)
        w, h = _snap32(width), _snap32(height)
        nframes = max(17, min(161, int(float(seconds) * float(fps))))
        import random
        kwargs = ltx_mode_kwargs("i2v")
        wf = build_ltx_video(
            preset, prompt,
            random.randint(1, 2 ** 32 - 1),
            width=w, height=h, num_frames=nframes, fps=int(fps),
            image_filename=name, i2v_strength=float(i2v_strength),
            negative_text=negative,
            **kwargs)
        return self._run_workflow(wf, "ltx_i2v")

    def wan_i2v(self, prompt: str, negative: str = "",
                 seconds: float = 5.0, fps: int = 16,
                 width: int = 832, height: int = 480,
                 turbo: bool = True) -> bytes | None:
        """Image-to-video via WAN 2.2. Uses the current canvas as the
        seed frame. Auto-detects an I2V-safe preset on the server
        (14B I2V or 5B TI2V); raises if neither is present.
        """
        preset = detect_wan_preset(self.server)
        if not preset:
            self.show_error(
                "No WAN 2.2 I2V models found on the server. Install "
                "the WAN 2.2 14B I2V model to use image-to-video.")
            return None
        name = self._last_upload or self.upload_canvas()
        def _snap16(v):
            v = int(v) // 16 * 16
            return max(256, v)
        w, h = _snap16(width), _snap16(height)
        # WAN's safe length window.
        length = max(33, min(121, int(float(seconds) * float(fps)) + 1))
        # Mod-4 enforcement for length (WAN quirk).
        length = ((length - 1) // 4) * 4 + 1
        import random
        kwargs = wan_turbo_kwargs(bool(turbo))
        wf = build_wan_video(
            name, preset, prompt, negative,
            random.randint(1, 2 ** 32 - 1),
            width=w, height=h, length=length, fps=int(fps),
            turbo=bool(turbo),
            **kwargs)
        return self._run_workflow(wf, "wan_i2v")

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
        # Module-level dedup — survives editor script_manager reloads
        # that re-instantiate the plugin but keep the Python process
        # alive. Blender F8 / Krita reload tears down sys.modules and
        # a fresh thread starts (the old one stays daemon-alive), so
        # this guard only helps within a single module lifetime.
        key = (self._origin, self._guild_url)
        if key in _HEARTBEAT_ORIGINS_STARTED:
            self._heartbeat_started = True
            return
        _HEARTBEAT_ORIGINS_STARTED.add(key)
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
        # Module-level dedup — same rationale as _start_heartbeat_loop
        # above. Prevents multiple polls against the same mailbox
        # across script_manager reloads that recreate the plugin
        # instance without re-importing the module.
        key = (self._origin, self._guild_url)
        if key in _INBOX_ORIGINS_STARTED:
            self._inbox_poll_started = True
            return
        _INBOX_ORIGINS_STARTED.add(key)
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
        """Preflight + optimize + submit + download + insert.

        Fires dispatch telemetry on every exit path so SpeedCoach
        sees Krita / Blender / (and any future plugin-base consumer)
        renders alongside GIMP / Darktable / SillyTavern / Guild-
        internal ones. Emission routes through ``_post_dispatch_
        telemetry`` \u2014 a fire-and-forget POST to the Guild's
        ``/api/telemetry/dispatch_ok`` endpoint.
        """
        t0 = time.time()
        outcome = "error"
        err_str = ""
        arch = self._guess_workflow_arch(workflow)
        try:
            # Preflight
            self.show_progress(f"Checking nodes...")
            try:
                ok, workflow, report = preflight_workflow(
                    workflow, self.server)
                if report.get("substituted"):
                    for orig, desc in report["substituted"]:
                        self.show_progress(f"Fallback: {desc}")
                if not ok:
                    err_str = (
                        f"Missing nodes: {', '.join(report['missing'])}")
                    self.show_error(err_str)
                    return None
            except Exception:
                pass

            # Optimize
            try:
                workflow, warnings = optimize_workflow(
                    workflow, comfy_url=self.server)
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
                err = {}
                try:
                    err = json.loads(e.read().decode())
                except Exception:
                    pass
                err_str = (
                    f"Rejected: {json.dumps(err.get('node_errors', {}))[:200]}")
                self.show_error(err_str)
                return None

            if not pid:
                err_str = "No prompt_id returned"
                self.show_error(err_str)
                return None

            # Poll
            self.show_progress(f"Generating ({label})...")
            tpoll = time.time()
            while time.time() - tpoll < 300:
                try:
                    r = urllib.request.urlopen(
                        f"{self.server}/history/{pid}", timeout=5)
                    d = json.loads(r.read())
                    if pid in d:
                        st = d[pid].get("status", {})
                        if st.get("completed"):
                            outputs = d[pid].get("outputs", {})
                            outcome = "ok"
                            return self._download_and_insert(outputs, label)
                        if st.get("status_str") == "error":
                            try:
                                from .dispatch import (
                                    extract_execution_error,
                                    has_usable_outputs,
                                )
                                err_str, _ = extract_execution_error(st)
                                if has_usable_outputs(d[pid]):
                                    # Partial success — surface output.
                                    outcome = "ok"
                                    return self._download_and_insert(
                                        d[pid].get("outputs", {}), label)
                            except ImportError:
                                msgs = st.get("messages") or []
                                err_str = "?"
                                for msg in msgs:
                                    if (isinstance(msg, (list, tuple))
                                            and len(msg) >= 2
                                            and msg[0] == "execution_error"):
                                        err_str = (msg[1]
                                                   .get("exception_message",
                                                         "?"))[:200]
                                        break
                            self.show_error(err_str)
                            return None
                except Exception:
                    pass
                time.sleep(2)
                elapsed = int(time.time() - tpoll)
                self.show_progress(f"Generating ({label})... {elapsed}s")

            err_str = "Timeout"
            self.show_error(err_str)
            return None
        except Exception as _exc:
            err_str = f"{type(_exc).__name__}: {_exc}"
            raise
        finally:
            try:
                self._post_dispatch_telemetry(
                    handler=f"{self._origin or 'plugin'}_{label}",
                    build_fn="",
                    arch=arch,
                    elapsed=time.time() - t0,
                    failed=(outcome != "ok"),
                    error=err_str,
                )
            except Exception:
                pass

    def _guess_workflow_arch(self, workflow) -> str:
        """Best-effort arch classification from loader nodes.

        Matches the Guild + GIMP helpers so telemetry rows share the
        same ``arch`` key regardless of origin.
        """
        if not isinstance(workflow, dict):
            return ""
        saw_klein = False
        loaders = {
            "CheckpointLoaderSimple", "CheckpointLoader",
            "CheckpointLoaderGGUF", "UNETLoader", "UnetLoaderGGUF",
            "UNetLoader",
        }
        try:
            from .model_detect import classify_ckpt_model
        except Exception:
            classify_ckpt_model = None
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type", "")
            if ct.startswith("Flux2Klein"):
                saw_klein = True
            if ct in loaders and classify_ckpt_model is not None:
                inputs = node.get("inputs", {}) or {}
                name = (inputs.get("ckpt_name") or inputs.get("unet_name")
                        or inputs.get("model_name") or "")
                if name:
                    try:
                        arch = classify_ckpt_model(name)
                        if arch:
                            return arch
                    except Exception:
                        pass
        return "flux2klein" if saw_klein else "unknown"

    def _post_dispatch_telemetry(self, *, handler, build_fn, arch,
                                   elapsed, failed, error):
        """Fire-and-forget POST to the Guild's dispatch_ok endpoint.

        Only runs when ``guild_url`` was supplied at construction. A
        Guild-less plugin (stand-alone ComfyUI-direct mode) produces
        no telemetry \u2014 same trade-off as Darktable's helper.
        Never raises.
        """
        if not self._guild_url:
            return
        try:
            body = json.dumps({
                "origin": self._origin or "plugin",
                "handler": handler or "",
                "build_fn": build_fn or "",
                "arch": arch or "unknown",
                "elapsed": float(elapsed or 0.0),
                "failed": bool(failed),
                "error": str(error or "")[:400],
                "ts": time.time(),
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self._guild_url}/api/telemetry/dispatch_ok",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST")
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            # Guild offline \u2014 swallow.
            pass

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
