"""Spellcaster for Krita — AI image generation, upscaling, face swap, and more.

Install: copy this file + spellcaster_core/ to Krita's pykrita/ directory.
         Krita -> Settings -> Configure Krita -> Python Plugin Manager -> Enable Spellcaster

Requires: ComfyUI running (local or network).
"""

import os
import sys
from krita import *

# Add spellcaster_core to path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from spellcaster_core.plugin_base import SpellcasterPlugin
try:
    from spellcaster_core.plugin_presets import presets_for
except Exception:
    def presets_for(_origin):
        return []
try:
    from spellcaster_core.default_prompts import default_for
except Exception as _e:
    print(f"[spellcaster] default_prompts import failed: {_e!r}")
    def default_for(_op):
        return ""


class KritaSpellcaster(SpellcasterPlugin):
    """Krita-specific implementation of the Spellcaster plugin."""

    def __init__(self, server_url="http://192.168.86.28:8190",
                 guild_url=None, origin="krita"):
        # Read user's SAM3-skip preference from Krita settings BEFORE super()
        # so the base class's __init__ doesn't get to set the default.
        # Stored as the string "true" / "false" via Application.writeSetting.
        try:
            from krita import Application as _App
            _skip = (_App.readSetting(
                "spellcaster", "skip_sam3", "false") or "false").lower()
            self._initial_skip_sam3 = _skip in ("true", "1", "yes", "on")
        except Exception:
            self._initial_skip_sam3 = False
        # Passing guild_url + origin activates the cross-interface
        # heartbeat + AssetGallery stash in plugin_base.
        super().__init__(server_url, guild_url=guild_url, origin=origin)
        # Apply the persisted SAM3-skip preference.
        self.skip_sam3 = self._initial_skip_sam3
        self._app = Krita.instance()

    def _heartbeat_meta(self):
        # Report Krita's own version + the plugin host version so the
        # Guild's presence chip can show useful diagnostics. Krita's
        # Application.version() is "5.2.0"-style.
        try:
            krita_ver = str(self._app.version())
        except Exception:
            krita_ver = "unknown"
        return {
            "plugin": "krita",
            "krita_version": krita_ver,
            "transport": "plugin_base",
        }

    def get_canvas_png(self):
        """Export active document as PNG bytes."""
        doc = self._app.activeDocument()
        if not doc:
            raise RuntimeError("No active document")
        # Export to temp file
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        doc.exportImage(tmp.name, InfoObject())
        with open(tmp.name, "rb") as f:
            data = f.read()
        os.unlink(tmp.name)
        return data

    def get_mask_png(self):
        """Export the active selection as a grayscale mask PNG.

        Returns ``None`` when no selection is active, so the base
        class can show a clear "make a selection first" error. When
        a selection exists, the alpha channel is rendered into an
        8-bit grayscale canvas: white (selected) = regenerate here,
        black (unselected) = keep the original pixels. Matches the
        ``build_inpaint`` mask contract.
        """
        doc = self._app.activeDocument()
        if not doc:
            return None
        try:
            sel = doc.selection()
        except Exception:
            sel = None
        if sel is None:
            return None
        w, h = doc.width(), doc.height()
        try:
            # Krita.Selection.pixelData(x, y, w, h) returns a
            # grayscale byte array \u2014 one byte per pixel. Wrap
            # that in a minimal grayscale PNG so build_inpaint's
            # LoadImage node can decode it.
            raw = sel.pixelData(0, 0, w, h)
        except Exception:
            return None
        if not raw:
            return None
        # Minimal grayscale PNG writer (no PIL dependency, which is
        # a hit-or-miss dep in Krita's bundled Python).
        import struct as _struct
        import zlib as _zlib
        import binascii as _bin
        ihdr = _struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
        def _chunk(tag, data):
            crc = _bin.crc32(tag + data) & 0xFFFFFFFF
            return (_struct.pack(">I", len(data)) + tag + data
                    + _struct.pack(">I", crc))
        row_len = w
        scanlines = bytearray()
        for y in range(h):
            scanlines.append(0)
            start = y * row_len
            scanlines.extend(raw[start:start + row_len])
        idat = _zlib.compress(bytes(scanlines))
        png = (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", ihdr)
                + _chunk(b"IDAT", idat)
                + _chunk(b"IEND", b""))
        return png

    def get_normal_map_png(self):
        """Return the first layer whose name contains 'normal' as a
        PNG, so IC-Light relighting can pick it up for surface-aware
        output. Walks the active document's layers. Returns None
        when nothing matches \u2014 IC-Light then falls back to flat
        FC-mode relighting."""
        doc = self._app.activeDocument()
        if not doc:
            return None
        try:
            nodes = doc.rootNode().childNodes() or []
        except Exception:
            return None
        for node in nodes:
            try:
                name = (node.name() or "").lower()
            except Exception:
                continue
            if "normal" not in name:
                continue
            try:
                import tempfile as _tf
                tmp = _tf.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.close()
                node.save(tmp.name, 1.0, 1.0, InfoObject())
                with open(tmp.name, "rb") as f:
                    data = f.read()
                import os as _os
                _os.unlink(tmp.name)
                return data
            except Exception:
                return None
        return None

    def insert_layer(self, png_bytes, name="Spellcaster"):
        """Decode PNG bytes via QImage and insert as a new paint layer.

        Uses Acly AI-Diffusion's proven order:
          createNode → setPixelData (with QByteArray bytes) → addChildNode.
        Avoids Application.openDocument() which spawns a Krita import
        modal ("Exporting to canvas") and can hang the workflow.
        Handles QImage scanline padding (bytesPerLine ≠ width*4 on odd widths).
        """
        from PyQt5.QtGui import QImage
        from PyQt5.QtCore import QByteArray
        doc = self._app.activeDocument()
        if not doc:
            self.show_error("No active Krita document — open one first.")
            return
        img = QImage.fromData(png_bytes, "PNG")
        if img.isNull():
            self.show_error("Spellcaster: server returned a non-image "
                             "(check Voodoomaster console for errors).")
            return
        if img.format() != QImage.Format_ARGB32:
            img = img.convertToFormat(QImage.Format_ARGB32)
        w, h = img.width(), img.height()
        bpl = img.bytesPerLine()
        row_bytes = w * (img.depth() // 8)  # = w*4 for ARGB32
        if bpl != row_bytes:
            # Strip Qt's 32-bit scanline padding row-by-row.
            buf = QByteArray()
            for y in range(h):
                ptr = img.scanLine(y)
                buf.append(ptr.asstring(row_bytes))
            data = buf
        else:
            ptr = img.constBits()
            data = QByteArray(ptr.asstring(img.byteCount()))
        node = doc.createNode(name, "paintlayer")
        node.setPixelData(data, 0, 0, w, h)
        doc.rootNode().addChildNode(node, None)
        doc.refreshProjection()
        self.show_progress(f"Spellcaster: inserted {w}×{h} layer")

    def show_progress(self, message):
        """Show in Krita's status bar."""
        self._app.activeWindow().activeView().showFloatingMessage(
            message, QIcon(), 3000, 1)

    def show_error(self, message):
        """Show error dialog."""
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Spellcaster", message)

    # =====================================================================
    #  Klein / PuLID / SUPIR / SAM3 wrappers — wired to spellcaster_core
    #  workflows. Each does: upload canvas → build workflow → dispatch.
    # =====================================================================

    def _wf(self, builder_name):
        """Lazy import of workflows.py builders (it's a big module)."""
        from spellcaster_core import workflows
        return getattr(workflows, builder_name)

    def klein_img2img(self, prompt, klein_model_key="Klein 9B",
                      denoise=0.65, seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_klein_img2img")(
            img, klein_model_key, prompt, seed,
            denoise=denoise)
        return self._run_workflow(wf, "klein_img2img")

    def klein_refine(self, prompt, klein_model_key="Klein 9B",
                     denoise=0.35, seed=0):
        img = self.upload_canvas()
        # build_klein_refine doesn't accept denoise — the caller's denoise
        # arg is preserved on the method API for future use but isn't
        # forwarded to the builder yet.
        wf = self._wf("build_klein_refine")(
            img, klein_model_key, prompt, seed)
        return self._run_workflow(wf, "klein_refine")

    def klein_repose(self, prompt, klein_model_key="Klein 9B", seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_klein_repose")(
            img, klein_model_key, prompt, seed)
        return self._run_workflow(wf, "klein_repose")

    def klein_face_detail(self, prompt, seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_klein_face_detail")(img, prompt, seed)
        return self._run_workflow(wf, "klein_face_detail")

    def klein_batch_variations(self, prompt, klein_model_key="Klein 9B",
                                batch_count=4, seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_klein_batch_variations")(
            img, klein_model_key, prompt, seed, count=batch_count)
        return self._run_workflow(wf, "klein_batch_variations")

    def photobooth(self, prompt, klein_model_key="Klein 9B", seed=0):
        ref = self.upload_canvas()
        wf = self._wf("build_photobooth")(
            ref, prompt, seed, klein_model_key=klein_model_key)
        return self._run_workflow(wf, "photobooth")


    def klein_multi_angle(self, klein_model_key="Klein 4B", seed=0,
                          steps=4):
        """Klein multi-angle character sheet (7 views from one reference)."""
        img = self.upload_canvas()
        wf = self._wf("build_klein_multi_angle")(
            img, klein_model_key=klein_model_key,
            seed=seed, steps=steps)
        return self._run_workflow(wf, "klein_multi_angle")

    def pulid_flux(self, face_ref_bytes, prompt, seed=0):
        target = self.upload_canvas()
        face_ref = self._upload_bytes(face_ref_bytes,
                                       prefix="pulid_face")
        # Lock to Klein 4B + Klein PuLID v2 weights:
        # - The 8 GB GPU can't fit Flux 1 dev safetensors (only GGUF Q5).
        # - Klein 9B needs qwen_3_8b which isn't downloaded.
        # - Klein 4B has "4b" in the name so builder routes CLIPLoader to
        #   qwen_3_4b (which we have) and PuLID to the Flux2 node family
        #   from iFayens/ComfyUI-PuLID-Flux2.
        # denoise=0.25 (was 0.65): the previous default regenerated 65%% of
        # the canvas latent, blowing away background + clothes. PuLID's
        # identity-injection only needs ~0.20-0.35 denoise to imprint the
        # face on the existing image; lower preserves more of the original.
        # enhance=False skips the Klein enhancer chain which adds
        # ApplyTeaCachePatch (from lldacing/ComfyUI_Patches_ll). If you
        # install that pack you can flip enhance=True for ~1.5x speed.
        wf = self._wf("build_pulid_flux")(
            target, face_ref,
            prompt_text=prompt, negative_text="", seed=seed,
            flux_model="A-Flux\\flux-2-klein-4b-fp8.safetensors",
            pulid_model="pulid_flux2_klein_v2.safetensors",
            denoise=0.25,
            enhance=False,
        )
        return self._run_workflow(wf, "pulid_flux")

    def supir_upscale(self, prompt="", seed=0,
                      supir_model="SUPIR-v0Q_fp16.safetensors",
                      sdxl_model="SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors"):
        img = self.upload_canvas()
        wf = self._wf("build_supir")(img, supir_model, sdxl_model,
                                       prompt, seed)
        return self._run_workflow(wf, "supir")

    def klein_color_match(self, reference_bytes, strength=1.0):
        target = self.upload_canvas()
        ref = self._upload_bytes(reference_bytes,
                                  prefix="colormatch_ref")
        wf = self._wf("build_klein_color_match")(
            target, ref, strength=strength)
        return self._run_workflow(wf, "klein_color_match")

    def klein_headswap(self, source_face_bytes,
                        klein_model_key="Klein 4B", seed=0):
        target = self.upload_canvas()
        source = self._upload_bytes(source_face_bytes,
                                      prefix="headswap_source")
        # build_klein_headswap requires prompt as the 4th positional arg.
        # Pass "" since headswap doesn't use a prompt at the UI level.
        wf = self._wf("build_klein_headswap")(
            target, source, klein_model_key, "", seed)
        return self._run_workflow(wf, "klein_headswap")

    def klein_virtual_tryon(self, outfit_bytes, prompt="", seed=0):
        face = self.upload_canvas()
        outfit = self._upload_bytes(outfit_bytes, prefix="tryon_outfit")
        wf = self._wf("build_klein_virtual_tryon")(
            face, outfit, prompt, seed)
        return self._run_workflow(wf, "klein_virtual_tryon")

    def sam3_segment(self, prompt, confidence=0.6):
        img = self.upload_canvas()
        wf = self._wf("build_sam3_segment")(img, prompt,
                                              confidence=confidence)
        return self._run_workflow(wf, "sam3_segment")

    def sam3_extract(self, prompt="person", confidence=0.6):
        img = self.upload_canvas()
        wf = self._wf("build_sam3_extract")(img, prompt=prompt,
                                              confidence=confidence)
        return self._run_workflow(wf, "sam3_extract")

    def qwen_edit(self, prompt, seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_qwen_edit")(
            img,
            unet_name="qwen_image_edit_2509_fp8_e4m3fn.safetensors",
            clip_name="qwen_2.5_vl_7b_fp8_scaled.safetensors",
            vae_name="qwen_image_vae.safetensors",
            prompt_text=prompt, seed=seed)
        return self._run_workflow(wf, "qwen_edit")

    def _upload_bytes(self, png_bytes, prefix="aux"):
        """Upload a raw PNG buffer to ComfyUI and return its filename."""
        import time
        from spellcaster_core.comfy_ws import upload_image
        name = f"{prefix}_{int(time.time()*1000)}.png"
        # comfy_ws.upload_image uses the same server_url this plugin uses.
        upload_image(self.server, png_bytes, name)
        return name

    # =====================================================================
    #  Iteration 2 — inpaint / blend / scene family + alt face identity
    # =====================================================================

    def _upload_mask(self):
        """Upload the active selection as a PNG mask, return filename.
        Falls back to None if no selection (caller decides what to do)."""
        mask = self.get_mask_png()
        if mask is None:
            return None
        return self._upload_bytes(mask, prefix="mask")

    def klein_inpaint(self, prompt, klein_model_key="Klein 9B", seed=0,
                      denoise=1.0):
        img = self.upload_canvas()
        mask = self._upload_mask()
        wf = self._wf("build_klein_inpaint")(
            img, mask_filename=mask, prompt_text=prompt,
            seed=seed, denoise=denoise)
        return self._run_workflow(wf, "klein_inpaint")

    def klein_auto_inpaint(self, mask_prompt, inpaint_prompt, seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_klein_auto_inpaint")(
            img, mask_prompt, inpaint_prompt, seed)
        return self._run_workflow(wf, "klein_auto_inpaint")

    def klein_sam3_inpaint(self, segment_prompt, inpaint_prompt,
                            seed=0, confidence=0.6):
        img = self.upload_canvas()
        wf = self._wf("build_klein_sam3_inpaint")(
            img, segment_prompt, inpaint_prompt, seed,
            confidence=confidence)
        return self._run_workflow(wf, "klein_sam3_inpaint")

    def klein_blend(self, background_bytes, prompt, seed=0):
        fg = self.upload_canvas()
        bg = self._upload_bytes(background_bytes, prefix="blend_bg")
        wf = self._wf("build_klein_blend")(fg, bg, prompt, seed)
        return self._run_workflow(wf, "klein_blend")

    def klein_scene_img2img(self, prompt, seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_klein_scene_img2img")(img, prompt, seed)
        return self._run_workflow(wf, "klein_scene_img2img")

    def klein_generate_object(self, prompt, seed=0):
        scene = self.upload_canvas()
        wf = self._wf("build_klein_generate_object")(scene, prompt, seed)
        return self._run_workflow(wf, "klein_generate_object")

    def klein_detail(self, prompt, preset_key="default", seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_klein_detail")(img, preset_key, prompt, seed)
        return self._run_workflow(wf, "klein_detail")

    def klein_img2img_ref(self, ref_bytes, prompt,
                            klein_model_key="Klein 9B", seed=0):
        img = self.upload_canvas()
        ref = self._upload_bytes(ref_bytes, prefix="ref")
        wf = self._wf("build_klein_img2img_ref")(
            img, ref, klein_model_key, prompt, seed)
        return self._run_workflow(wf, "klein_img2img_ref")

    def faceid_img2img(self, face_ref_bytes, prompt, seed=0):
        target = self.upload_canvas()
        face = self._upload_bytes(face_ref_bytes, prefix="faceid")
        # build_faceid_img2img + load_model_stack expect "ckpt" (not
        # "checkpoint"), plus "steps"/"cfg" for the sampler.
        preset = {
            "ckpt": "SDXL\\Realistic\\RealVisXL_V5.0_fp16.safetensors",
            "arch": "sdxl",
            "steps": 28, "cfg": 6.0,
            "sampler": "dpmpp_2m", "scheduler": "karras",
            # denoise=0.35 (was 0.55): preserves more of the original
            # canvas. FaceID IPAdapter injects identity even at low
            # denoise; higher just regenerates background unnecessarily.
            "denoise": 0.35, "width": 1024, "height": 1024,
        }
        wf = self._wf("build_faceid_img2img")(
            target, face, preset, prompt_text=prompt,
            negative_text="", seed=seed)
        return self._run_workflow(wf, "faceid_img2img")

    def face_swap(self, source_image_bytes, swap_model="inswapper_128.onnx"):
        """Override base face_swap to disable CodeFormer post-restoration.
        CodeFormer at the default visibility=1.0 adds masculine features
        (moustache, stronger jaw, broader features) to female faces. We
        skip restoration entirely -- inswapper_128 alone preserves the
        source face's gender / age correctly.
        """
        if not source_image_bytes:
            self.show_error("Face Swap needs a source face image.")
            return None
        target = self.upload_canvas()
        src_name = self._upload_bytes(source_image_bytes, prefix="faceswap_src")
        # ReActorFaceSwapOpt requires face_restore_visibility >= 0.1 (min).
        # 0.1 is the lowest legal value and is barely-perceptible -- it does
        # NOT cause the moustache/jawline drift that visibility=1.0 produces.
        # codeformer_weight=0.0 further neutralizes the restoration pass.
        wf = self._wf("build_faceswap")(
            target, src_name,
            swap_model=swap_model,
            face_restore_vis=0.1,
            codeformer_weight=0.0,
        )
        return self._run_workflow(wf, "face_swap")

    def faceswap_mtb(self, source_face_bytes):
        target = self.upload_canvas()
        source = self._upload_bytes(source_face_bytes, prefix="mtb_face")
        wf = self._wf("build_faceswap_mtb")(target, source)
        return self._run_workflow(wf, "faceswap_mtb")

    def photo_restore(self, seed=0):
        """Old-photo restoration: upscale + face enhance + sharpen.
        No prompt -- pure quality pipeline. Wraps build_photo_restore."""
        img = self.upload_canvas()
        wf = self._wf("build_photo_restore")(
            img,
            upscale_model="4x-UltraSharp.pth",
            face_model="codeformer-v0.1.0.pth",
            facedetection="retinaface_resnet50",
            visibility=0.7,
            codeformer_weight=0.5,
            sharpen_radius=1.0,
            sigma=1.0,
            alpha=1.0,
        )
        return self._run_workflow(wf, "photo_restore")

    def inpaint_fooocus(self, prompt, seed=0):
        """Fooocus-style inpaint: LaMa pre-fill + Fooocus head LoRA on SDXL.
        Often higher quality than the default SDXL inpaint for clothing /
        object replacement. Requires a Krita selection (mask)."""
        img = self.upload_canvas()
        mask = self._upload_mask()
        if not mask:
            self.show_error("Fooocus inpaint needs a Krita selection.")
            return None
        preset = {
            "ckpt": "SDXL\\Realistic\\RealVisXL_V5.0_fp16.safetensors",
            "arch": "sdxl",
            "steps": 30, "cfg": 7.0,
            "sampler": "dpmpp_2m", "scheduler": "karras",
            "denoise": 0.85, "width": 1024, "height": 1024,
        }
        wf = self._wf("build_inpaint_fooocus")(
            img, mask, preset, prompt, "", seed)
        return self._run_workflow(wf, "inpaint_fooocus")

    def video_upscale(self, video_bytes, upscale_factor=2.0):
        """Upscale a video file. Uploads the video to ComfyUI's input dir
        then runs build_video_upscale."""
        if not video_bytes:
            self.show_error("Video upscale needs a video file.")
            return None
        import uuid as _u
        name = f"spellcaster_video_{_u.uuid4().hex[:8]}.mp4"
        # Use the raw-bytes upload helper inherited from the base class
        # (or fall back to our _upload_bytes which does the multipart POST).
        try:
            self._upload_raw(name, video_bytes)
        except AttributeError:
            self._upload_bytes(video_bytes, prefix="video")
            name = self._upload_bytes_last_name if hasattr(self, '_upload_bytes_last_name') else name
        wf = self._wf("build_video_upscale")(
            name, upscale_factor=upscale_factor)
        return self._run_workflow(wf, "video_upscale")

    # =====================================================================
    #  Iteration 3 — alt upscalers + utility ops
    # =====================================================================

    def wavespeed_upscale(self, target="2K", model="SeedVR2"):
        img = self.upload_canvas()
        wf = self._wf("build_wavespeed_upscale")(img, model=model,
                                                    target=target)
        return self._run_workflow(wf, "wavespeed_upscale")

    def seedv2r_upscale(self, prompt="", seed=0,
                          upscale_model="4x-UltraSharp.pth"):
        img = self.upload_canvas()
        # build_seedv2r requires: image, upscale_model, preset, prompt_text,
        # negative_text, seed, denoise, cfg, steps, scale_factor, orig_w, orig_h
        # Use a minimal SDXL preset and reasonable upscale defaults (2x).
        preset = {"arch": "sdxl", "steps": 20, "cfg": 6.5,
                  "sampler": "euler", "scheduler": "normal"}
        wf = self._wf("build_seedv2r")(
            img, upscale_model, preset,
            prompt, "", seed,
            0.35,        # denoise (low — preserve original after upscale)
            6.5,         # cfg
            20,          # steps
            2.0,         # scale_factor (2x)
            1024, 1024,  # orig_width, orig_height (canvas-typical)
        )
        return self._run_workflow(wf, "seedv2r")

    def depth_map(self, model="da3_large.safetensors"):
        img = self.upload_canvas()
        wf = self._wf("build_depth_map_v3")(img, model=model)
        return self._run_workflow(wf, "depth_map")

    def layer_blend(self, second_image_bytes, blend_factor=0.5):
        a = self.upload_canvas()
        b = self._upload_bytes(second_image_bytes, prefix="blend_b")
        wf = self._wf("build_layer_blend")(a, b, blend_factor=blend_factor)
        return self._run_workflow(wf, "layer_blend")

    def upscale_blend(self, model_a="4x-UltraSharp.pth",
                        model_b="4x_foolhardy_Remacri.pth"):
        img = self.upload_canvas()
        wf = self._wf("build_upscale_blend")(img, model_a, model_b)
        return self._run_workflow(wf, "upscale_blend")

    def lama_remove(self):
        """LaMa-based clean removal of selected region (no prompt)."""
        img = self.upload_canvas()
        mask = self._upload_mask()
        wf = self._wf("build_lama_remove")(img, mask_filename=mask)
        return self._run_workflow(wf, "lama_remove")

    def ddcolor(self, checkpoint="ddcolor_artistic.pth"):
        img = self.upload_canvas()
        wf = self._wf("build_ddcolor")(img, checkpoint=checkpoint)
        return self._run_workflow(wf, "ddcolor")

    def apply_lut(self, lut_name, strength=1.0):
        img = self.upload_canvas()
        wf = self._wf("build_lut")(img, lut_name, strength)
        return self._run_workflow(wf, "lut")

    def rembg_birefnet(self, model="BiRefNet-general"):
        img = self.upload_canvas()
        wf = self._wf("build_rembg_birefnet")(img, model=model)
        return self._run_workflow(wf, "rembg_birefnet")

    def rembg_v3(self, model="RMBG-2.0"):
        img = self.upload_canvas()
        wf = self._wf("build_rembg_v3")(img, model=model)
        return self._run_workflow(wf, "rembg_v3")

    def color_match_basic(self, reference_bytes, strength=1.0):
        """Non-Klein color match. Cheaper than klein_color_match."""
        source = self.upload_canvas()
        ref = self._upload_bytes(reference_bytes,
                                   prefix="colormatch_basic_ref")
        wf = self._wf("build_color_match")(source, ref, strength=strength)
        return self._run_workflow(wf, "color_match_basic")

    # =====================================================================
    #  Iteration 4 — video generation wrappers (results save server-side)
    #  Krita can't render video inline; these dispatch + toast.
    # =====================================================================

    def wan22_t2v(self, prompt, negative="", seed=0):
        wf = self._wf("build_wan22_t2v")(preset={}, prompt_text=prompt,
                                            negative_text=negative,
                                            seed=seed)
        return self._run_workflow(wf, "wan22_t2v")

    def wan_animate(self, prompt, negative="", seed=0):
        wf = self._wf("build_wan_animate_video")(
            prompt_text=prompt, negative_text=negative, seed=seed)
        return self._run_workflow(wf, "wan_animate")

    def framepack_video(self, prompt, negative="", seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_framepack_video")(
            img, prompt_text=prompt, negative_text=negative, seed=seed)
        return self._run_workflow(wf, "framepack_video")

    def hunyuan_video(self, prompt, seed=0):
        wf = self._wf("build_hunyuan_video")(prompt_text=prompt, seed=seed)
        return self._run_workflow(wf, "hunyuan_video")

    def mochi_video(self, prompt, negative="", seed=0):
        wf = self._wf("build_mochi_video")(
            prompt_text=prompt, negative_text=negative, seed=seed)
        return self._run_workflow(wf, "mochi_video")

    def cogvideo_video(self, prompt, negative="", seed=0):
        wf = self._wf("build_cogvideo_video")(
            prompt_text=prompt, negative_text=negative, seed=seed)
        return self._run_workflow(wf, "cogvideo_video")

    def wan_flf(self, end_frame_bytes, prompt, negative="", seed=0):
        """Wan first-last frame: canvas = start, picked file = end."""
        start = self.upload_canvas()
        end = self._upload_bytes(end_frame_bytes, prefix="wan_flf_end")
        wf = self._wf("build_wan_flf")(start, end, preset={},
                                          prompt_text=prompt,
                                          negative_text=negative, seed=seed)
        return self._run_workflow(wf, "wan_flf")

    def seedvr2_video_upscale(self, video_filename, seed=-1):
        """Upscale a video file already on the server."""
        wf = self._wf("build_seedvr2_video_upscale")(video_filename,
                                                       seed=seed)
        return self._run_workflow(wf, "seedvr2_video_upscale")

    # =====================================================================
    #  Iteration 5/6 — 3D + Lumina + ControlNet + frame assembly
    # =====================================================================

    def lumina2_txt2img(self, prompt, negative="", seed=0):
        wf = self._wf("build_lumina2_txt2img")(
            prompt_text=prompt, negative_text=negative, seed=seed)
        return self._run_workflow(wf, "lumina2_txt2img")

    def hunyuan_3d_mesh(self, seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_hunyuan_3d_mesh")(img, seed=seed)
        return self._run_workflow(wf, "hunyuan_3d_mesh")

    def hunyuan_3d_textured(self, seed=0):
        img = self.upload_canvas()
        wf = self._wf("build_hunyuan_3d_textured")(img, seed=seed)
        return self._run_workflow(wf, "hunyuan_3d_textured")

    def controlnet_gen(self, preprocessor, cn_model, prompt,
                         negative="", seed=0):
        img = self.upload_canvas()
        # build_controlnet_gen needs `preset` as a DICT (not a string) plus
        # explicit width/height/steps/cfg/sampler/scheduler. The builder
        # reads preset["arch"] and may read preset["steps"]/preset["cfg"]
        # via _apply_flux1_boosters etc. — give it the keys it needs.
        preset = {
            "arch": "sdxl",
            "checkpoint": "SDXL\\Realistic\\RealVisXL_V5.0_fp16.safetensors",
            "steps": 24,
            "cfg": 7.0,
            "sampler": "euler",
            "scheduler": "normal",
        }
        wf = self._wf("build_controlnet_gen")(
            img, preprocessor, cn_model,
            preset,
            prompt,
            negative,
            seed,
            1024, 1024,        # width, height
            24,                # steps
            7.0,               # cfg
            "euler",           # sampler
            "normal",          # scheduler
        )
        return self._run_workflow(wf, "controlnet_gen")

    def save_face_model(self, source_face_bytes, model_name,
                          overwrite=True):
        source = self._upload_bytes(source_face_bytes,
                                       prefix="save_face_src")
        wf = self._wf("build_save_face_model")(
            source, model_name, overwrite=overwrite)
        return self._run_workflow(wf, "save_face_model")

    def faceswap_from_model(self, face_model_name):
        target = self.upload_canvas()
        wf = self._wf("build_faceswap_model")(target, face_model_name)
        return self._run_workflow(wf, "faceswap_model")


class SpellcasterExtension(Extension):
    """Krita extension that adds Spellcaster menu items."""

    def __init__(self, parent):
        super().__init__(parent)
        self._plugin = None

    def setup(self):
        pass

    def _get_plugin(self):
        if not self._plugin:
            # Read server URL from config
            server = Application.readSetting("spellcaster", "server_url",
                                             "http://192.168.86.28:8190")
            # Optional Wizard Guild URL (blank = stand-alone mode).
            # Krita settings don't surface blank-by-default strings the
            # way Blender AddonPreferences do, so default to localhost
            # for discoverability; users can override via Settings
            # → Manage Resources → Python Plugins.
            guild = Application.readSetting("spellcaster", "guild_url",
                                            "http://127.0.0.1:7777")
            self._plugin = KritaSpellcaster(server, guild_url=guild,
                                             origin="krita")
        return self._plugin

    def createActions(self, window):
        # Main menu: Spellcaster
        menu = "tools/scripts/spellcaster"

        # txt2img
        a = window.createAction("spellcaster_txt2img", "Generate Image (txt2img)", menu)
        a.triggered.connect(self._on_txt2img)

        # Smart generate
        a2 = window.createAction("spellcaster_auto", "Smart Generate (auto)", menu)
        a2.triggered.connect(self._on_auto)

        # img2img
        a3 = window.createAction("spellcaster_img2img", "Transform (img2img)", menu)
        a3.triggered.connect(self._on_img2img)

        # Inpaint (needs an active selection)
        a_inp = window.createAction(
            "spellcaster_inpaint", "Inpaint Selection", menu)
        a_inp.triggered.connect(self._on_inpaint)

        # Outpaint (extends canvas by 256 px on the right)
        a_out = window.createAction(
            "spellcaster_outpaint", "Extend Canvas (Outpaint)", menu)
        a_out.triggered.connect(self._on_outpaint)

        # IC-Light relighting
        a_icl = window.createAction(
            "spellcaster_iclight", "Relight (IC-Light)", menu)
        a_icl.triggered.connect(self._on_iclight)

        # 3D normal-map generation
        a_nm = window.createAction(
            "spellcaster_normal_map", "Generate 3D Normal Map", menu)
        a_nm.triggered.connect(self._on_normal_map)

        # Upscale
        a4 = window.createAction("spellcaster_upscale", "AI Upscale (4x)", menu)
        a4.triggered.connect(self._on_upscale)

        # Remove background
        a5 = window.createAction("spellcaster_rembg", "Remove Background", menu)
        a5.triggered.connect(self._on_rembg)

        # Face restore
        a6 = window.createAction("spellcaster_face", "Restore Faces", menu)
        a6.triggered.connect(self._on_face_restore)

        # Detail hallucinate (upscale + detail diffusion)
        a_dh = window.createAction(
            "spellcaster_detail_hallucinate",
            "Detail Hallucinate (upscale + detail)", menu)
        a_dh.triggered.connect(self._on_detail_hallucinate)

        # Colorize B&W
        a_col = window.createAction(
            "spellcaster_colorize", "Colorize B&W", menu)
        a_col.triggered.connect(self._on_colorize)

        # Magic eraser (describe what to remove)
        a_me = window.createAction(
            "spellcaster_magic_eraser",
            "Magic Eraser (describe object)", menu)
        a_me.triggered.connect(self._on_magic_eraser)

        # Style transfer from file
        a_st = window.createAction(
            "spellcaster_style_transfer",
            "Style Transfer From File\u2026", menu)
        a_st.triggered.connect(self._on_style_transfer)

        # LTX text-to-video
        a_lt = window.createAction(
            "spellcaster_ltx_t2v", "Generate Video (LTX text-to-video)", menu)
        a_lt.triggered.connect(self._on_ltx_t2v)

        # LTX image-to-video (current canvas)
        a_li = window.createAction(
            "spellcaster_ltx_i2v", "Animate Canvas (LTX image-to-video)", menu)
        a_li.triggered.connect(self._on_ltx_i2v)

        # WAN image-to-video
        a_wi = window.createAction(
            "spellcaster_wan_i2v", "Animate Canvas (WAN image-to-video)", menu)
        a_wi.triggered.connect(self._on_wan_i2v)

        # Preset picker
        a_p = window.createAction(
            "spellcaster_presets", "Presets\u2026", menu)
        a_p.triggered.connect(self._on_presets)

        # Face swap (pick a source image)
        a_fs = window.createAction(
            "spellcaster_face_swap", "Swap Face From File\u2026", menu)
        a_fs.triggered.connect(self._on_face_swap)

        # \u2500\u2500 Klein 2 family \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        a_ki = window.createAction(
            "spellcaster_klein_img2img",
            "Klein img2img (high-fidelity transform)", menu)
        a_ki.triggered.connect(self._on_klein_img2img)

        a_kr = window.createAction(
            "spellcaster_klein_refine",
            "Klein refine (preserve identity, add detail)", menu)
        a_kr.triggered.connect(self._on_klein_refine)

        a_krp = window.createAction(
            "spellcaster_klein_repose",
            "Klein repose (change pose, keep identity)", menu)
        a_krp.triggered.connect(self._on_klein_repose)

        a_kfd = window.createAction(
            "spellcaster_klein_face_detail",
            "Klein face detail (sharpen faces only)", menu)
        a_kfd.triggered.connect(self._on_klein_face_detail)

        a_kbv = window.createAction(
            "spellcaster_klein_batch",
            "Klein batch variations (4x)", menu)
        a_kbv.triggered.connect(self._on_klein_batch)

        a_kma = window.createAction(
            "spellcaster_klein_multi_angle",
            "Klein multi-angle character sheet (7 views)…", menu)
        a_kma.triggered.connect(self._on_klein_multi_angle)

        a_pb = window.createAction(
            "spellcaster_photobooth",
            "Photobooth (passport-style headshot)", menu)
        a_pb.triggered.connect(self._on_photobooth)

        # \u2500\u2500 Identity / face swap (advanced) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        a_pulid = window.createAction(
            "spellcaster_pulid_flux",
            "PuLID face on Flux (best identity preservation)\u2026", menu)
        a_pulid.triggered.connect(self._on_pulid_flux)

        a_khs = window.createAction(
            "spellcaster_klein_headswap",
            "Klein head swap\u2026", menu)
        a_khs.triggered.connect(self._on_klein_headswap)

        a_kvt = window.createAction(
            "spellcaster_klein_tryon",
            "Klein virtual try-on (outfit swap)\u2026", menu)
        a_kvt.triggered.connect(self._on_klein_tryon)

        # \u2500\u2500 Upscale / color \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        a_sup = window.createAction(
            "spellcaster_supir",
            "SUPIR upscale (highest quality, slow)", menu)
        a_sup.triggered.connect(self._on_supir)

        a_kcm = window.createAction(
            "spellcaster_klein_color_match",
            "Klein color match (from reference image)\u2026", menu)
        a_kcm.triggered.connect(self._on_klein_color_match)

        # \u2500\u2500 Segmentation (SAM3) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        a_sam = window.createAction(
            "spellcaster_sam3_segment",
            "SAM3 segment by prompt", menu)
        a_sam.triggered.connect(self._on_sam3_segment)

        a_sex = window.createAction(
            "spellcaster_sam3_extract",
            "SAM3 extract subject (transparent cut-out)", menu)
        a_sex.triggered.connect(self._on_sam3_extract)

        # \u2500\u2500 Qwen edit \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        a_qe = window.createAction(
            "spellcaster_qwen_edit",
            "Qwen edit (semantic instruction edit)", menu)
        a_qe.triggered.connect(self._on_qwen_edit)

        # \u2500\u2500 Klein inpaint family (iteration 2) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        a_kin = window.createAction(
            "spellcaster_klein_inpaint",
            "Klein inpaint (selection-based)", menu)
        a_kin.triggered.connect(self._on_klein_inpaint)

        a_kai = window.createAction(
            "spellcaster_klein_auto_inpaint",
            "Klein auto-inpaint (detect + replace by prompt)", menu)
        a_kai.triggered.connect(self._on_klein_auto_inpaint)

        a_kss = window.createAction(
            "spellcaster_klein_sam3_inpaint",
            "Klein SAM3 inpaint (semantic select + rebuild)", menu)
        a_kss.triggered.connect(self._on_klein_sam3_inpaint)

        a_kbl = window.createAction(
            "spellcaster_klein_blend",
            "Klein blend (composite onto background)\u2026", menu)
        a_kbl.triggered.connect(self._on_klein_blend)

        a_ksc = window.createAction(
            "spellcaster_klein_scene_img2img",
            "Klein scene img2img (relight / re-scene)", menu)
        a_ksc.triggered.connect(self._on_klein_scene_img2img)

        a_kgo = window.createAction(
            "spellcaster_klein_generate_object",
            "Klein generate object into scene", menu)
        a_kgo.triggered.connect(self._on_klein_generate_object)

        a_kdt = window.createAction(
            "spellcaster_klein_detail",
            "Klein multi-pass detail enhance", menu)
        a_kdt.triggered.connect(self._on_klein_detail)

        a_kir = window.createAction(
            "spellcaster_klein_img2img_ref",
            "Klein img2img with reference image\u2026", menu)
        a_kir.triggered.connect(self._on_klein_img2img_ref)

        a_fid = window.createAction(
            "spellcaster_faceid_img2img",
            "FaceID img2img (IPAdapter identity)\u2026", menu)
        a_fid.triggered.connect(self._on_faceid_img2img)

        a_fmt = window.createAction(
            "spellcaster_faceswap_mtb",
            "Face swap (MTB \u2014 alt to ReActor)\u2026", menu)
        a_fmt.triggered.connect(self._on_faceswap_mtb)

        # \u2500\u2500 Iteration 3 \u2014 alt upscalers + utility ops \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        a_wsu = window.createAction(
            "spellcaster_wavespeed_upscale",
            "Wavespeed upscale (SeedVR2, fast 2K)", menu)
        a_wsu.triggered.connect(self._on_wavespeed_upscale)

        a_sv2 = window.createAction(
            "spellcaster_seedv2r",
            "SeedV2R upscale (controllable hallucination)", menu)
        a_sv2.triggered.connect(self._on_seedv2r)

        a_dm = window.createAction(
            "spellcaster_depth_map",
            "Depth map (DepthAnything v3)", menu)
        a_dm.triggered.connect(self._on_depth_map)

        a_lyb = window.createAction(
            "spellcaster_layer_blend",
            "Layer blend (mix with second image)\u2026", menu)
        a_lyb.triggered.connect(self._on_layer_blend)

        a_ub = window.createAction(
            "spellcaster_upscale_blend",
            "Upscale blend (compare 2 upscalers)", menu)
        a_ub.triggered.connect(self._on_upscale_blend)

        a_lama = window.createAction(
            "spellcaster_lama_remove",
            "LaMa remove (clean removal, no prompt)", menu)
        a_lama.triggered.connect(self._on_lama_remove)

        a_ddc = window.createAction(
            "spellcaster_ddcolor",
            "DDColor (alt B/W colorize)", menu)
        a_ddc.triggered.connect(self._on_ddcolor)

        a_lut = window.createAction(
            "spellcaster_lut",
            "Apply 3D LUT\u2026", menu)
        a_lut.triggered.connect(self._on_lut)

        a_rbn = window.createAction(
            "spellcaster_rembg_birefnet",
            "Remove background (BiRefNet, better)", menu)
        a_rbn.triggered.connect(self._on_rembg_birefnet)

        a_rv3 = window.createAction(
            "spellcaster_rembg_v3",
            "Remove background (RMBG-2.0, newest)", menu)
        a_rv3.triggered.connect(self._on_rembg_v3)

        a_cmb = window.createAction(
            "spellcaster_color_match_basic",
            "Basic color match (cheap, non-Klein)\u2026", menu)
        a_cmb.triggered.connect(self._on_color_match_basic)

        # \u2500\u2500 Iteration 4 \u2014 video gen (output to server, not canvas) \u2500
        a_w22 = window.createAction(
            "spellcaster_wan22_t2v",
            "Video: Wan 2.2 text-to-video", menu)
        a_w22.triggered.connect(self._on_wan22_t2v)

        a_wan = window.createAction(
            "spellcaster_wan_animate",
            "Video: Wan animate (text-driven)", menu)
        a_wan.triggered.connect(self._on_wan_animate)

        a_fpv = window.createAction(
            "spellcaster_framepack_video",
            "Video: Framepack (canvas as source)", menu)
        a_fpv.triggered.connect(self._on_framepack_video)

        a_hv = window.createAction(
            "spellcaster_hunyuan_video",
            "Video: Hunyuan (text-to-video)", menu)
        a_hv.triggered.connect(self._on_hunyuan_video)

        a_mv = window.createAction(
            "spellcaster_mochi_video",
            "Video: Mochi (text-to-video)", menu)
        a_mv.triggered.connect(self._on_mochi_video)

        a_cgv = window.createAction(
            "spellcaster_cogvideo_video",
            "Video: CogVideo (text-to-video)", menu)
        a_cgv.triggered.connect(self._on_cogvideo_video)

        a_wflf = window.createAction(
            "spellcaster_wan_flf",
            "Video: Wan first-last frame (canvas = start)\u2026", menu)
        a_wflf.triggered.connect(self._on_wan_flf)

        a_svr = window.createAction(
            "spellcaster_seedvr2_video_upscale",
            "Video: SeedVR2 upscale (server-side file)\u2026", menu)
        a_svr.triggered.connect(self._on_seedvr2_video_upscale)

        # \u2500\u2500 Iteration 5/6 \u2014 3D + Lumina + ControlNet + face model \u2500\u2500
        a_lum = window.createAction(
            "spellcaster_lumina2_txt2img",
            "Lumina 2 txt2img (alt to default)", menu)
        a_lum.triggered.connect(self._on_lumina2_txt2img)

        a_h3m = window.createAction(
            "spellcaster_hunyuan_3d_mesh",
            "3D: Hunyuan mesh from canvas", menu)
        a_h3m.triggered.connect(self._on_hunyuan_3d_mesh)

        a_h3t = window.createAction(
            "spellcaster_hunyuan_3d_textured",
            "3D: Hunyuan textured mesh from canvas", menu)
        a_h3t.triggered.connect(self._on_hunyuan_3d_textured)

        a_cn = window.createAction(
            "spellcaster_controlnet_gen",
            "ControlNet generation (structure-preserving)", menu)
        a_cn.triggered.connect(self._on_controlnet_gen)

        a_sfm = window.createAction(
            "spellcaster_save_face_model",
            "Save face model (for re-use)\u2026", menu)
        a_sfm.triggered.connect(self._on_save_face_model)

        a_fsm = window.createAction(
            "spellcaster_faceswap_from_model",
            "Face swap from saved model\u2026", menu)
        a_fsm.triggered.connect(self._on_faceswap_from_model)

        # Settings
        a7 = window.createAction("spellcaster_settings", "Settings...", menu)
        a7.triggered.connect(self._on_settings)

    def _on_txt2img(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "Describe what you want to generate:", op_key="txt2img")
        if ok and prompt:
            self._get_plugin().txt2img(prompt)

    def _on_auto(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "What do you want to create?", op_key="auto")
        if ok and prompt:
            self._get_plugin().auto(prompt)

    def _on_img2img(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "How should the image change?", op_key="img2img")
        if ok and prompt:
            self._get_plugin().img2img(prompt)

    def _on_inpaint(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "What should fill the selected region?", op_key="inpaint")
        if ok and prompt:
            self._get_plugin().inpaint(prompt)

    def _on_outpaint(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "Describe what should appear in the extended area:", op_key="outpaint")
        if ok and prompt:
            # Default: extend 256 px to the right. Users who want
            # other edges set them via a future settings dialog.
            self._get_plugin().outpaint(prompt, right=256)

    def _on_iclight(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "Describe the lighting (e.g. 'golden hour from left'):", op_key="iclight")
        if ok and prompt:
            self._get_plugin().iclight(prompt)

    def _on_normal_map(self):
        self._get_plugin().normal_map()

    def _on_face_swap(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Pick a source face image", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                source_bytes = f.read()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(
                None, "Spellcaster",
                f"Could not read {path}: {e}")
            return
        self._get_plugin().face_swap(source_bytes)

    def _on_upscale(self):
        self._get_plugin().upscale()

    def _on_rembg(self):
        self._get_plugin().rembg()

    def _on_face_restore(self):
        self._get_plugin().face_restore()

    def _on_detail_hallucinate(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "Detail hint (e.g. 'crisp pores, fine fabric'):", op_key="detail_hallucinate")
        if ok:
            self._get_plugin().detail_hallucinate(prompt or "detail, texture")

    def _on_colorize(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "Optional colour hint (e.g. 'warm sunset'):", op_key="colorize")
        if ok:
            self._get_plugin().colorize(prompt or "")

    def _on_magic_eraser(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "What should be removed? (e.g. 'power line', 'watermark'):", op_key="magic_eraser")
        if ok and prompt:
            self._get_plugin().magic_eraser(prompt)

    def _on_style_transfer(self):
        from PyQt5.QtWidgets import QFileDialog, QInputDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Pick a style reference", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                style_bytes = f.read()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(None, "Spellcaster",
                                 f"Could not read {path}: {e}")
            return
        prompt, ok = self._prompt("Spellcaster", "Optional guiding prompt:", op_key="style_transfer")
        if ok:
            self._get_plugin().style_transfer_from_bytes(
                style_bytes, prompt or "")

    def _on_ltx_t2v(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "Describe the video scene:", op_key="ltx_t2v")
        if ok and prompt:
            self._get_plugin().ltx_t2v(prompt, seconds=3.0)

    def _on_ltx_i2v(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "Describe how the canvas should move:", op_key="ltx_i2v")
        if ok and prompt:
            self._get_plugin().ltx_i2v(prompt, seconds=3.0)

    def _on_wan_i2v(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = self._prompt("Spellcaster", "Describe the motion for WAN I2V:", op_key="wan_i2v")
        if ok and prompt:
            self._get_plugin().wan_i2v(prompt, seconds=5.0)

    def _on_presets(self):
        from PyQt5.QtWidgets import QInputDialog
        presets = presets_for("krita")
        if not presets:
            return
        labels = [p["label"] for p in presets]
        label, ok = QInputDialog.getItem(
            None, "Spellcaster Presets",
            "Pick a preset:", labels, 0, False)
        if not ok or not label:
            return
        preset = next((p for p in presets if p["label"] == label), None)
        if not preset:
            return
        self._dispatch_preset(preset)

    def _dispatch_preset(self, preset):
        from PyQt5.QtWidgets import QInputDialog
        op = preset.get("op", "txt2img")
        prompt = preset.get("prompt", "")
        # Give the user a chance to tweak the prompt.
        if op not in ("upscale", "rembg", "normal_map") and not preset.get("placeholder"):
            prompt, ok = QInputDialog.getMultiLineText(
                None, preset["label"],
                "Prompt (edit if you want):", prompt)
            if not ok:
                return
        elif preset.get("placeholder"):
            prompt, ok = QInputDialog.getText(
                None, preset["label"],
                preset.get("placeholder") or "Describe:")
            if not ok or not prompt:
                return
        plug = self._get_plugin()
        kwargs = dict(preset.get("kwargs") or {})
        arch = preset.get("arch") or ""
        if arch and op in ("txt2img", "img2img", "colorize",
                            "detail_hallucinate", "style_transfer"):
            kwargs["arch"] = arch
        try:
            fn = getattr(plug, op, None)
            if not fn:
                plug.show_error(f"Preset op '{op}' not available.")
                return
            if op in ("upscale", "rembg", "normal_map"):
                fn()
            elif op == "magic_eraser":
                fn(prompt)
            else:
                fn(prompt, **kwargs)
        except Exception as e:
            plug.show_error(f"Preset failed: {e}")

    def _on_settings(self):
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox,
            QPushButton, QLabel,
        )
        dlg = QDialog()
        dlg.setWindowTitle("Spellcaster Settings")
        layout = QVBoxLayout(dlg)

        # Server URL
        layout.addWidget(QLabel("ComfyUI Server URL:"))
        url_in = QLineEdit(Application.readSetting(
            "spellcaster", "server_url", "http://192.168.86.28:8190"))
        layout.addWidget(url_in)

        # Skip SAM3 toggle
        skip_cur = (Application.readSetting(
            "spellcaster", "skip_sam3", "false") or "false").lower()
        skip_in = QCheckBox(
            "Skip SAM3 region-scoping  "
            "(workflows treat the whole canvas; install ComfyUI-Segment-"
            "Anything-2 to enable)")
        skip_in.setChecked(skip_cur in ("true", "1", "yes", "on"))
        layout.addWidget(skip_in)

        # Buttons
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        if dlg.exec_() == QDialog.Accepted:
            url = url_in.text().strip()
            if url:
                Application.writeSetting("spellcaster", "server_url", url)
            Application.writeSetting(
                "spellcaster", "skip_sam3",
                "true" if skip_in.isChecked() else "false")
            self._plugin = None  # Force reconnect with new settings

    # ─────────────────────────────────────────────────────────────
    #  Klein / PuLID / SUPIR / SAM3 / Qwen handlers
    # ─────────────────────────────────────────────────────────────
    def _prompt(self, title, label, default="", op_key=None):
        """Input dialog. If op_key is given, prefill with the ideal
        prompt template from spellcaster_core.default_prompts."""
        from PyQt5.QtWidgets import QInputDialog
        if op_key and not default:
            default = default_for(op_key)
        if default and len(default) > 80:
            return QInputDialog.getMultiLineText(
                None, title, label, default)
        return QInputDialog.getText(None, title, label, text=default)

    def _pick_image_bytes(self, title):
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            None, title, "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception as e:
            QMessageBox.critical(None, "Spellcaster",
                                  f"Could not read {path}: {e}")
            return None

    def _on_klein_img2img(self):
        prompt, ok = self._prompt("Klein img2img",
                                    "How should the image change?", op_key="klein_img2img")
        if ok and prompt:
            self._get_plugin().klein_img2img(prompt)

    def _on_klein_refine(self):
        prompt, ok = self._prompt("Klein refine",
                                    "Detail hint (e.g. 'sharper eyes, fabric texture'):", op_key="klein_refine")
        if ok:
            self._get_plugin().klein_refine(prompt or "detail, texture")

    def _on_klein_repose(self):
        prompt, ok = self._prompt("Klein repose",
                                    "New pose (e.g. 'sitting cross-legged, side view'):", op_key="klein_repose")
        if ok and prompt:
            self._get_plugin().klein_repose(prompt)

    def _on_klein_face_detail(self):
        prompt, ok = self._prompt("Klein face detail",
                                    "Optional guidance (or blank):", "", op_key="klein_face_detail")
        self._get_plugin().klein_face_detail(prompt or "natural skin, sharp eyes")

    def _on_klein_batch(self):
        prompt, ok = self._prompt("Klein batch variations",
                                    "Variation prompt:", op_key="klein_batch_variations")
        if ok and prompt:
            self._get_plugin().klein_batch_variations(prompt,
                                                       batch_count=4)

    def _on_klein_multi_angle(self):
        """Dispatch klein_multi_angle via Spellcaster (7-angle sheet)."""
        self._get_plugin().klein_multi_angle()
    def _on_photobooth(self):
        prompt, ok = self._prompt("Photobooth",
                                    "Style of portrait (or blank for default):", "", op_key="photobooth")
        self._get_plugin().photobooth(
            prompt or "professional passport portrait, neutral expression, "
                      "plain studio backdrop, soft natural light, photorealistic")

    def _on_pulid_flux(self):
        face_bytes = self._pick_image_bytes("Pick a face reference for PuLID")
        if not face_bytes:
            return
        prompt, ok = self._prompt("PuLID Flux",
                                    "What should the new image show?", op_key="pulid_flux")
        if ok and prompt:
            self._get_plugin().pulid_flux(face_bytes, prompt)

    def _on_klein_headswap(self):
        src = self._pick_image_bytes("Pick source face image")
        if not src:
            return
        self._get_plugin().klein_headswap(src)

    def _on_klein_tryon(self):
        outfit = self._pick_image_bytes("Pick outfit reference image")
        if not outfit:
            return
        prompt, ok = self._prompt("Klein virtual try-on",
                                    "Optional pose/scene guidance:", "", op_key="klein_virtual_tryon")
        self._get_plugin().klein_virtual_tryon(outfit, prompt or "")

    def _on_supir(self):
        prompt, ok = self._prompt("SUPIR upscale",
                                    "Optional positive prompt (blank = generic):", "", op_key="supir_upscale")
        self._get_plugin().supir_upscale(prompt or "")

    def _on_klein_color_match(self):
        ref = self._pick_image_bytes("Pick color-reference image")
        if not ref:
            return
        self._get_plugin().klein_color_match(ref, strength=1.0)

    def _on_sam3_segment(self):
        prompt, ok = self._prompt("SAM3 segment",
                                    "What to segment? (e.g. 'face', 'shirt'):", op_key="sam3_segment")
        if ok and prompt:
            self._get_plugin().sam3_segment(prompt)

    def _on_sam3_extract(self):
        prompt, ok = self._prompt("SAM3 extract",
                                    "Subject to extract:", "person", op_key="sam3_extract")
        if ok and prompt:
            self._get_plugin().sam3_extract(prompt)

    def _on_qwen_edit(self):
        prompt, ok = self._prompt(
            "Qwen edit",
            "Instruction (e.g. 'remove the cars', 'make it nighttime'):", op_key="qwen_edit")
        if ok and prompt:
            self._get_plugin().qwen_edit(prompt)

    # ── Iteration 2 handlers ────────────────────────────────────
    def _on_klein_inpaint(self):
        prompt, ok = self._prompt(
            "Klein inpaint",
            "What should fill the selected area? (make a selection first):", op_key="klein_inpaint")
        if ok and prompt:
            self._get_plugin().klein_inpaint(prompt)

    def _on_klein_auto_inpaint(self):
        mask_p, ok1 = self._prompt(
            "Klein auto-inpaint",
            "What to mask (e.g. 'background', 'shirt'):",
            op_key="klein_auto_inpaint.mask")
        if not ok1 or not mask_p: return
        inp_p, ok2 = self._prompt(
            "Klein auto-inpaint",
            "Replace with:",
            op_key="klein_auto_inpaint.fill")
        if ok2 and inp_p:
            self._get_plugin().klein_auto_inpaint(mask_p, inp_p)

    def _on_klein_sam3_inpaint(self):
        seg, ok1 = self._prompt(
            "Klein SAM3 inpaint",
            "Segment by prompt (e.g. 'watermark', 'power line'):",
            op_key="klein_sam3_inpaint.segment")
        if not ok1 or not seg: return
        inp, ok2 = self._prompt(
            "Klein SAM3 inpaint",
            "Rebuild as (e.g. 'sky', 'plain wall'):",
            op_key="klein_sam3_inpaint.fill")
        if ok2 and inp:
            self._get_plugin().klein_sam3_inpaint(seg, inp)

    def _on_klein_blend(self):
        bg = self._pick_image_bytes("Pick background image")
        if not bg: return
        prompt, ok = self._prompt(
            "Klein blend",
            "Composite guidance (optional):", "")
        self._get_plugin().klein_blend(bg, prompt or "")

    def _on_klein_scene_img2img(self):
        prompt, ok = self._prompt(
            "Klein scene img2img",
            "How should the scene change? (e.g. 'sunset', 'rainy'):")
        if ok and prompt:
            self._get_plugin().klein_scene_img2img(prompt)

    def _on_klein_generate_object(self):
        prompt, ok = self._prompt(
            "Klein generate object",
            "What to add (e.g. 'a wooden chair on the left'):")
        if ok and prompt:
            self._get_plugin().klein_generate_object(prompt)

    def _on_klein_detail(self):
        prompt, ok = self._prompt(
            "Klein detail",
            "Detail focus (e.g. 'skin pores, fabric weave'):")
        if ok:
            self._get_plugin().klein_detail(prompt or "detail")

    def _on_klein_img2img_ref(self):
        ref = self._pick_image_bytes("Pick reference image (style/structure)")
        if not ref: return
        prompt, ok = self._prompt(
            "Klein img2img with ref",
            "What should the result look like?")
        if ok and prompt:
            self._get_plugin().klein_img2img_ref(ref, prompt)

    def _on_faceid_img2img(self):
        face = self._pick_image_bytes("Pick face reference for FaceID")
        if not face: return
        prompt, ok = self._prompt(
            "FaceID img2img",
            "What should the scene be?")
        if ok and prompt:
            self._get_plugin().faceid_img2img(face, prompt)

    def _on_faceswap_mtb(self):
        src = self._pick_image_bytes("Pick source face image (MTB)")
        if not src: return
        self._get_plugin().faceswap_mtb(src)

    # ── Iteration 3 handlers ────────────────────────────────────
    def _on_wavespeed_upscale(self):
        from PyQt5.QtWidgets import QInputDialog
        target, ok = QInputDialog.getItem(
            None, "Wavespeed upscale", "Target size:",
            ["1K", "2K", "4K"], 1, False)
        if ok: self._get_plugin().wavespeed_upscale(target=target)

    def _on_seedv2r(self):
        prompt, ok = self._prompt(
            "SeedV2R upscale",
            "Optional positive prompt (blank = generic):", "")
        self._get_plugin().seedv2r_upscale(prompt or "")

    def _on_depth_map(self):
        self._get_plugin().depth_map()

    def _on_layer_blend(self):
        second = self._pick_image_bytes("Pick second image to blend with")
        if not second: return
        from PyQt5.QtWidgets import QInputDialog
        factor, ok = QInputDialog.getDouble(
            None, "Layer blend", "Blend factor (0=A, 1=B):",
            0.5, 0.0, 1.0, 2)
        if ok: self._get_plugin().layer_blend(second, blend_factor=factor)

    def _on_upscale_blend(self):
        self._get_plugin().upscale_blend()

    def _on_lama_remove(self):
        self._get_plugin().lama_remove()

    def _on_ddcolor(self):
        self._get_plugin().ddcolor()

    def _on_lut(self):
        name, ok = self._prompt(
            "Apply LUT",
            "LUT filename (e.g. 'kodak_2383.cube'):")
        if not ok or not name: return
        from PyQt5.QtWidgets import QInputDialog
        strength, ok2 = QInputDialog.getDouble(
            None, "Apply LUT", "Strength (0-1):", 1.0, 0.0, 1.0, 2)
        if ok2: self._get_plugin().apply_lut(name, strength=strength)

    def _on_rembg_birefnet(self):
        self._get_plugin().rembg_birefnet()

    def _on_rembg_v3(self):
        self._get_plugin().rembg_v3()

    def _on_color_match_basic(self):
        ref = self._pick_image_bytes("Pick color-reference image")
        if not ref: return
        self._get_plugin().color_match_basic(ref)

    # ── Iteration 4 video handlers ──────────────────────────────
    def _on_wan22_t2v(self):
        p, ok = self._prompt("Wan 2.2 text-to-video",
                                "Describe the video:")
        if ok and p: self._get_plugin().wan22_t2v(p)

    def _on_wan_animate(self):
        p, ok = self._prompt("Wan animate",
                                "Animation prompt:")
        if ok and p: self._get_plugin().wan_animate(p)

    def _on_framepack_video(self):
        p, ok = self._prompt("Framepack video",
                                "How should the canvas animate?")
        if ok and p: self._get_plugin().framepack_video(p)

    def _on_hunyuan_video(self):
        p, ok = self._prompt("Hunyuan text-to-video",
                                "Describe the video:")
        if ok and p: self._get_plugin().hunyuan_video(p)

    def _on_mochi_video(self):
        p, ok = self._prompt("Mochi text-to-video",
                                "Describe the video:")
        if ok and p: self._get_plugin().mochi_video(p)

    def _on_cogvideo_video(self):
        p, ok = self._prompt("CogVideo text-to-video",
                                "Describe the video:")
        if ok and p: self._get_plugin().cogvideo_video(p)

    def _on_wan_flf(self):
        end = self._pick_image_bytes("Pick END frame image (canvas = start)")
        if not end: return
        p, ok = self._prompt("Wan first-last frame",
                                "Motion between frames (optional):", "")
        self._get_plugin().wan_flf(end, p or "")

    def _on_seedvr2_video_upscale(self):
        name, ok = self._prompt(
            "SeedVR2 video upscale",
            "Server-side video filename to upscale:")
        if ok and name:
            self._get_plugin().seedvr2_video_upscale(name)

    # ── Iteration 5/6 handlers ──────────────────────────────────
    def _on_lumina2_txt2img(self):
        p, ok = self._prompt("Lumina 2 txt2img", "Describe the image:")
        if ok and p: self._get_plugin().lumina2_txt2img(p)

    def _on_hunyuan_3d_mesh(self):
        self._get_plugin().hunyuan_3d_mesh()

    def _on_hunyuan_3d_textured(self):
        self._get_plugin().hunyuan_3d_textured()

    def _on_controlnet_gen(self):
        from PyQt5.QtWidgets import QInputDialog
        pre, ok1 = QInputDialog.getItem(
            None, "ControlNet", "Preprocessor:",
            ["depth", "canny", "openpose", "lineart", "softedge",
             "scribble"], 0, False)
        if not ok1: return
        cn, ok2 = self._prompt(
            "ControlNet model",
            "ComfyUI model name (e.g. 'control_v11p_sd15_canny.pth'):")
        if not ok2 or not cn: return
        p, ok3 = self._prompt("ControlNet prompt", "Prompt:")
        if ok3 and p:
            self._get_plugin().controlnet_gen(pre, cn, p)

    def _on_save_face_model(self):
        src = self._pick_image_bytes("Pick source face to save as model")
        if not src: return
        name, ok = self._prompt(
            "Save face model", "Name for this face model:")
        if ok and name:
            self._get_plugin().save_face_model(src, name)

    def _on_faceswap_from_model(self):
        name, ok = self._prompt(
            "Face swap from saved model",
            "Saved face model name:")
        if ok and name:
            self._get_plugin().faceswap_from_model(name)





# =====================================================================
#  Spellcaster Docker — elegant panel like Acly's AI Image Diffusion
# =====================================================================
#  Single-panel UI exposing every wired workflow with category-prefixed
#  combo + prompt + optional reference picker + Generate. The same
#  KritaSpellcaster instance is reused (lazy-built via the extension's
#  _get_plugin()) so settings and the comfy_ws session are shared.
#
#  METHOD_SPECS is the spec table: each entry declares label, prompt
#  label, whether a reference image is needed (and what it's called),
#  and the call thunk that binds (plugin, prompt, ref_bytes) to the
#  underlying method's actual argument order.

from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase  # noqa: E402

# (category, method_name, label, needs_prompt, needs_ref, ref_label, call_fn)
# call_fn: f(plugin, prompt_text, ref_bytes) -> dispatch
METHOD_SPECS = [
    # ── Generate (no canvas needed; just prompt) ───────────────
    ('Generate', 'txt2img',         'Generate Image (txt2img)',         True,  False, '', lambda p, t, r: p.txt2img(t)),
    ('Generate', 'auto',            'Smart Generate (auto-pick)',       True,  False, '', lambda p, t, r: p.auto(t)),
    ('Generate', 'ltx_t2v',         'LTX text-to-video',                True,  False, '', lambda p, t, r: p.ltx_t2v(t)),
    ('Generate', 'wan22_t2v',       'Wan 2.2 text-to-video',            True,  False, '', lambda p, t, r: p.wan22_t2v(t)),
    ('Generate', 'wan_animate',     'Wan animate',                      True,  False, '', lambda p, t, r: p.wan_animate(t)),
    ('Generate', 'hunyuan_video',   'Hunyuan text-to-video',            True,  False, '', lambda p, t, r: p.hunyuan_video(t)),
    ('Generate', 'mochi_video',     'Mochi text-to-video',              True,  False, '', lambda p, t, r: p.mochi_video(t)),
    ('Generate', 'cogvideo_video',  'CogVideo text-to-video',           True,  False, '', lambda p, t, r: p.cogvideo_video(t)),

    # ── Transform (canvas + prompt) ────────────────────────────
    ('Transform', 'img2img',                'Transform (img2img)',          True,  False, '', lambda p, t, r: p.img2img(t)),
    ('Transform', 'klein_img2img',          'Klein img2img',                True,  False, '', lambda p, t, r: p.klein_img2img(t)),
    ('Transform', 'klein_refine',           'Klein refine (keep ID)',       True,  False, '', lambda p, t, r: p.klein_refine(t)),
    ('Transform', 'klein_repose',           'Klein repose',                 True,  False, '', lambda p, t, r: p.klein_repose(t)),
    ('Transform', 'klein_face_detail',      'Klein face detail',            True,  False, '', lambda p, t, r: p.klein_face_detail(t)),
    ('Transform', 'klein_detail',           'Klein multi-pass detail',      True,  False, '', lambda p, t, r: p.klein_detail(t)),
    ('Transform', 'klein_scene_img2img',    'Klein re-scene / relight',     True,  False, '', lambda p, t, r: p.klein_scene_img2img(t)),
    ('Transform', 'klein_generate_object',  'Klein add object to scene',    True,  False, '', lambda p, t, r: p.klein_generate_object(t)),
    ('Transform', 'klein_multi_angle',     'Klein multi-angle character sheet (7)',  False, False, '', lambda p, t, r: p.klein_multi_angle()),
    ('Transform', 'klein_batch_variations', 'Klein batch variations (4x)',  True,  False, '', lambda p, t, r: p.klein_batch_variations(t)),
    ('Transform', 'photobooth',             'Photobooth (passport portrait)', True, False, '', lambda p, t, r: p.photobooth(t)),
    ('Transform', 'qwen_edit',              'Qwen edit (semantic)',         True,  False, '', lambda p, t, r: p.qwen_edit(t)),
    ('Transform', 'iclight',                'IC-Light relight',             True,  False, '', lambda p, t, r: p.iclight(t)),
    ('Transform', 'detail_hallucinate',     'Detail Hallucinate',           True,  False, '', lambda p, t, r: p.detail_hallucinate(t)),
    ('Transform', 'colorize',               'Colorize B/W',                 True,  False, '', lambda p, t, r: p.colorize(t)),
    ('Transform', 'ddcolor',                'DDColor (alt B/W colorize)',   False, False, '', lambda p, t, r: p.ddcolor()),
    ('Transform', 'wan_i2v',                'Wan image-to-video',           True,  False, '', lambda p, t, r: p.wan_i2v(t)),
    ('Transform', 'ltx_i2v',                'LTX image-to-video',           True,  False, '', lambda p, t, r: p.ltx_i2v(t)),
    ('Transform', 'framepack_video',        'Framepack video (canvas src)', True,  False, '', lambda p, t, r: p.framepack_video(t)),

    # ── Inpaint / Erase (selection + prompt) ──────────────────
    ('Inpaint', 'inpaint',              'Inpaint selection (SDXL)',      True,  False, '', lambda p, t, r: p.inpaint(t)),
    ('Inpaint', 'klein_inpaint',        'Klein inpaint selection',       True,  False, '', lambda p, t, r: p.klein_inpaint(t)),
    ('Inpaint', 'magic_eraser',         'Magic Eraser (by prompt)',      True,  False, '', lambda p, t, r: p.magic_eraser(t)),
    ('Inpaint', 'lama_remove',          'LaMa clean removal (no prompt)',False, False, '', lambda p, t, r: p.lama_remove()),
    ('Inpaint', 'outpaint',             'Outpaint (extend canvas)',      True,  False, '', lambda p, t, r: p.outpaint(t)),

    # ── Face / Identity (canvas + ref face image) ─────────────
    ('Face', 'pulid_flux',         'PuLID face on Flux (best)',     True,  True,  'Face reference', lambda p, t, r: p.pulid_flux(r, t)),
    ('Face', 'faceid_img2img',     'FaceID img2img (IPAdapter)',    True,  True,  'Face reference', lambda p, t, r: p.faceid_img2img(r, t)),
    ('Face', 'face_swap',          'ReActor face swap',             False, True,  'Source face',    lambda p, t, r: p.face_swap(r)),
    ('Face', 'faceswap_mtb',       'MTB face swap',                 False, True,  'Source face',    lambda p, t, r: p.faceswap_mtb(r)),
    ('Face', 'klein_headswap',     'Klein head swap',               False, True,  'Source face',    lambda p, t, r: p.klein_headswap(r)),
    ('Face', 'klein_virtual_tryon','Klein virtual try-on (outfit)', True,  True,  'Outfit image',   lambda p, t, r: p.klein_virtual_tryon(r, t)),
    ('Face', 'face_restore',       'Restore Faces',                 False, False, '',               lambda p, t, r: p.face_restore()),

    ('Transform', 'photo_restore',         'Old photo restore (no prompt)',  False, False, '', lambda p, t, r: p.photo_restore()),
    ('Inpaint',   'inpaint_fooocus',       'Fooocus inpaint (LaMa+SDXL)',    True,  False, '', lambda p, t, r: p.inpaint_fooocus(t)),
    ('Upscale',   'video_upscale',         'Video upscale (pick file)',      False, True,  'Video file', lambda p, t, r: p.video_upscale(r) if r else None),

    # ── Style / Composite (canvas + ref image) ────────────────
    ('Style', 'style_transfer_from_bytes', 'Style Transfer',            True,  True,  'Style reference',  lambda p, t, r: p.style_transfer_from_bytes(r, t)),
    ('Style', 'klein_img2img_ref',         'Klein img2img w/ reference', True, True,  'Style/struct ref', lambda p, t, r: p.klein_img2img_ref(r, t)),
    ('Style', 'klein_color_match',         'Klein color match',         False, True,  'Color reference',  lambda p, t, r: p.klein_color_match(r)),
    ('Style', 'color_match_basic',         'Basic color match',         False, True,  'Color reference',  lambda p, t, r: p.color_match_basic(r)),
    ('Style', 'klein_blend',               'Klein blend onto background', True, True,  'Background image', lambda p, t, r: p.klein_blend(r, t)),
    ('Style', 'layer_blend',               'Layer blend (50/50)',       False, True,  'Second image',     lambda p, t, r: p.layer_blend(r, 0.5)),

    # ── Upscale ────────────────────────────────────────────────
    ('Upscale', 'upscale',           'AI Upscale (4x UltraSharp)',  False, False, '', lambda p, t, r: p.upscale()),
    ('Upscale', 'supir_upscale',     'SUPIR upscale (highest, slow)', True, False, '', lambda p, t, r: p.supir_upscale(t)),
    ('Upscale', 'seedv2r_upscale',   'SeedV2R upscale (controllable)', True, False, '', lambda p, t, r: p.seedv2r_upscale(t)),
    ('Upscale', 'wavespeed_upscale', 'Wavespeed 2K (fast SeedVR2)',  False, False, '', lambda p, t, r: p.wavespeed_upscale()),
    ('Upscale', 'upscale_blend',     'Upscale blend (2 upscalers)',  False, False, '', lambda p, t, r: p.upscale_blend()),

    # ── Cut-out / Maps ────────────────────────────────────────
    ('Maps', 'rembg',           'Remove background (basic)',     False, False, '', lambda p, t, r: p.rembg()),
    ('Maps', 'rembg_birefnet',  'Remove bg (BiRefNet)',          False, False, '', lambda p, t, r: p.rembg_birefnet()),
    ('Maps', 'rembg_v3',        'Remove bg (RMBG-2.0)',          False, False, '', lambda p, t, r: p.rembg_v3()),
    ('Maps', 'sam3_extract',    'SAM3 extract subject',          True,  False, '', lambda p, t, r: p.sam3_extract(t)),
    ('Maps', 'sam3_segment',    'SAM3 segment (mask)',           True,  False, '', lambda p, t, r: p.sam3_segment(t)),
    ('Maps', 'normal_map',      'Normal map',                    False, False, '', lambda p, t, r: p.normal_map()),
    ('Maps', 'depth_map',       'Depth map (DepthAnything v3)',  False, False, '', lambda p, t, r: p.depth_map()),

    # ── Iteration 5/6: extras ──────────────────────────────────
    ('Generate', 'lumina2_txt2img',     'Lumina 2 txt2img',           True,  False, '', lambda p, t, r: p.lumina2_txt2img(t)),
    ('Maps',     'hunyuan_3d_mesh',     '3D: Hunyuan mesh',           False, False, '', lambda p, t, r: p.hunyuan_3d_mesh()),
    ('Maps',     'hunyuan_3d_textured', '3D: Hunyuan textured mesh',  False, False, '', lambda p, t, r: p.hunyuan_3d_textured()),
    ('Face',     'faceswap_from_model', 'Face swap from saved model', True,  False, '', lambda p, t, r: p.faceswap_from_model(t)),
]

CATEGORY_ICONS = {
    'Generate': '📝', 'Transform': '🔄', 'Inpaint': '🩹',
    'Face': '👤', 'Style': '🎨', 'Upscale': '⬆️', 'Maps': '🎭',
}


class SpellcasterDocker(DockWidget):
    """Single-panel UI for every wired Spellcaster workflow."""

    def __init__(self):
        super().__init__()
        from PyQt5.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPlainTextEdit,
            QPushButton, QLabel, QFrame,
        )

        self.setWindowTitle("Spellcaster")
        self._plugin = None
        self._ref_bytes = None
        self._ref_path = ""

        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # Workflow combo
        v.addWidget(QLabel("<b>Workflow</b>"))
        self._combo = QComboBox()
        for cat, name, label, np_, nr, rl, _ in METHOD_SPECS:
            icon = CATEGORY_ICONS.get(cat, '')
            self._combo.addItem(f"{icon} {cat}: {label}",
                                (name, np_, nr, rl))
        self._combo.currentIndexChanged.connect(self._on_combo_change)
        v.addWidget(self._combo)

        # Prompt
        self._prompt_label = QLabel("<b>Prompt</b>")
        v.addWidget(self._prompt_label)
        self._prompt = QPlainTextEdit()
        self._prompt.setPlaceholderText("Describe the result…")
        self._prompt.setMaximumHeight(80)
        v.addWidget(self._prompt)

        # Reference picker row
        self._ref_label = QLabel("<b>Reference image</b>")
        v.addWidget(self._ref_label)
        ref_row = QHBoxLayout()
        self._ref_btn = QPushButton("Pick file…")
        self._ref_btn.clicked.connect(self._on_pick_ref)
        ref_row.addWidget(self._ref_btn)
        self._ref_clear = QPushButton("✕")
        self._ref_clear.setMaximumWidth(28)
        self._ref_clear.clicked.connect(self._on_clear_ref)
        ref_row.addWidget(self._ref_clear)
        v.addLayout(ref_row)
        self._ref_status = QLabel("(none)")
        v.addWidget(self._ref_status)

        # Separator
        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        v.addWidget(line)

        # Generate button
        self._go = QPushButton("Generate")
        self._go.setMinimumHeight(36)
        self._go.setStyleSheet(
            "QPushButton{font-weight:bold;background:#2a82da;color:white;"
            "border-radius:4px;}"
            "QPushButton:hover{background:#3a92ea;}")
        self._go.clicked.connect(self._on_go)
        v.addWidget(self._go)

        # Status
        self._status = QLabel("Ready.")
        self._status.setStyleSheet("color:#888;font-style:italic;")
        self._status.setWordWrap(True)
        v.addWidget(self._status)

        # Settings link
        s_row = QHBoxLayout()
        self._settings_btn = QPushButton("Settings…")
        self._settings_btn.clicked.connect(self._on_settings)
        s_row.addStretch(1)
        s_row.addWidget(self._settings_btn)
        v.addLayout(s_row)

        v.addStretch(1)
        self.setWidget(root)

        self._on_combo_change(0)

    def canvasChanged(self, canvas):
        pass  # required by DockWidget interface

    def _get_plugin(self):
        if not self._plugin:
            server = Application.readSetting("spellcaster", "server_url",
                                              "http://192.168.86.28:8190")
            guild = Application.readSetting("spellcaster", "guild_url",
                                             "http://127.0.0.1:7777")
            self._plugin = KritaSpellcaster(server, guild_url=guild,
                                             origin="krita")
        return self._plugin

    def _on_combo_change(self, idx):
        data = self._combo.itemData(idx)
        if not data: return
        name, needs_prompt, needs_ref, ref_label = data
        self._prompt_label.setVisible(needs_prompt)
        self._prompt.setVisible(needs_prompt)
        self._ref_label.setText(f"<b>{ref_label}</b>" if needs_ref
                                else "<b>Reference image</b>")
        self._ref_label.setVisible(needs_ref)
        self._ref_btn.setVisible(needs_ref)
        self._ref_clear.setVisible(needs_ref)
        self._ref_status.setVisible(needs_ref)
        # Auto-fill prompt with the ideal template for this op so the user
        # doesn't type boilerplate from scratch. Always reset first so a
        # previous workflow's prompt never lingers (especially when switching
        # to a no-prompt op like face_swap / faceswap_mtb / klein_headswap
        # where the prompt area is hidden but we don't want stale text).
        self._prompt.clear()
        if needs_prompt:
            template = default_for(name)
            if template:
                self._prompt.setPlainText(template)

    def _on_pick_ref(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Pick reference image", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if not path: return
        try:
            with open(path, "rb") as f: self._ref_bytes = f.read()
            self._ref_path = path
            import os
            self._ref_status.setText(os.path.basename(path))
        except Exception as e:
            self._ref_status.setText(f"Error: {e}")

    def _on_clear_ref(self):
        self._ref_bytes = None
        self._ref_path = ""
        self._ref_status.setText("(none)")

    def _on_go(self):
        idx = self._combo.currentIndex()
        spec_data = self._combo.itemData(idx)
        if not spec_data: return
        method_name = spec_data[0]
        needs_prompt = spec_data[1]
        needs_ref = spec_data[2]
        spec = next((s for s in METHOD_SPECS if s[1] == method_name), None)
        if not spec:
            self._status.setText(f"Unknown workflow: {method_name}")
            return
        prompt = self._prompt.toPlainText().strip() if needs_prompt else ""
        if needs_prompt and not prompt:
            self._status.setText("Prompt required.")
            return
        if needs_ref and not self._ref_bytes:
            self._status.setText("Reference image required.")
            return
        call_fn = spec[6]
        self._status.setText(f"Dispatching: {method_name}…")
        self._go.setEnabled(False)
        try:
            plug = self._get_plugin()
            call_fn(plug, prompt, self._ref_bytes)
            self._status.setText(f"Sent {method_name} to "
                                  f"{plug.server}")
        except Exception as e:
            self._status.setText(f"Error: {type(e).__name__}: {e}")
        finally:
            self._go.setEnabled(True)

    def _on_settings(self):
        from PyQt5.QtWidgets import QInputDialog
        current = Application.readSetting("spellcaster", "server_url",
                                           "http://192.168.86.28:8190")
        url, ok = QInputDialog.getText(None, "Spellcaster Settings",
                                        "ComfyUI / Voodoomaster URL:",
                                        text=current)
        if ok and url:
            Application.writeSetting("spellcaster", "server_url", url)
            self._plugin = None
            self._status.setText(f"Server: {url}")


Krita.instance().addExtension(SpellcasterExtension(Krita.instance()))
Krita.instance().addDockWidgetFactory(
    DockWidgetFactory("spellcasterDocker",
                       DockWidgetFactoryBase.DockRight,
                       SpellcasterDocker))
