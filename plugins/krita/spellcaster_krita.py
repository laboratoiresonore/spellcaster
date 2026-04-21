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


class KritaSpellcaster(SpellcasterPlugin):
    """Krita-specific implementation of the Spellcaster plugin."""

    def __init__(self, server_url="http://127.0.0.1:8188",
                 guild_url=None, origin="krita"):
        # Passing guild_url + origin activates the cross-interface
        # heartbeat + AssetGallery stash in plugin_base.
        super().__init__(server_url, guild_url=guild_url, origin=origin)
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
        """Insert PNG bytes as a new paint layer in the active document."""
        doc = self._app.activeDocument()
        if not doc:
            return
        # Save to temp file for Krita to load
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(png_bytes)
        tmp.close()
        # Create new layer from file
        new_layer = doc.createNode(name, "paintlayer")
        # Load the image data
        temp_doc = self._app.openDocument(tmp.name)
        if temp_doc:
            pixel_data = temp_doc.pixelData(0, 0, temp_doc.width(), temp_doc.height())
            new_layer.setPixelData(pixel_data, 0, 0, temp_doc.width(), temp_doc.height())
            temp_doc.close()
        doc.rootNode().addChildNode(new_layer, None)
        doc.refreshProjection()
        os.unlink(tmp.name)

    def show_progress(self, message):
        """Show in Krita's status bar."""
        self._app.activeWindow().activeView().showFloatingMessage(
            message, QIcon(), 3000, 1)

    def show_error(self, message):
        """Show error dialog."""
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Spellcaster", message)


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
                                             "http://127.0.0.1:8188")
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
        menu = "spellcaster_menu"

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

        # Settings
        a7 = window.createAction("spellcaster_settings", "Settings...", menu)
        a7.triggered.connect(self._on_settings)

    def _on_txt2img(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(None, "Spellcaster", "Describe what you want to generate:")
        if ok and prompt:
            self._get_plugin().txt2img(prompt)

    def _on_auto(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(None, "Spellcaster", "What do you want to create?")
        if ok and prompt:
            self._get_plugin().auto(prompt)

    def _on_img2img(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(None, "Spellcaster", "How should the image change?")
        if ok and prompt:
            self._get_plugin().img2img(prompt)

    def _on_inpaint(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "What should fill the selected region?")
        if ok and prompt:
            self._get_plugin().inpaint(prompt)

    def _on_outpaint(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "Describe what should appear in the extended area:")
        if ok and prompt:
            # Default: extend 256 px to the right. Users who want
            # other edges set them via a future settings dialog.
            self._get_plugin().outpaint(prompt, right=256)

    def _on_iclight(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "Describe the lighting (e.g. 'golden hour from left'):")
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
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "Detail hint (e.g. 'crisp pores, fine fabric'):")
        if ok:
            self._get_plugin().detail_hallucinate(prompt or "detail, texture")

    def _on_colorize(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "Optional colour hint (e.g. 'warm sunset'):")
        if ok:
            self._get_plugin().colorize(prompt or "")

    def _on_magic_eraser(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "What should be removed? (e.g. 'power line', 'watermark'):")
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
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "Optional guiding prompt:")
        if ok:
            self._get_plugin().style_transfer_from_bytes(
                style_bytes, prompt or "")

    def _on_ltx_t2v(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster", "Describe the video scene:")
        if ok and prompt:
            self._get_plugin().ltx_t2v(prompt, seconds=3.0)

    def _on_ltx_i2v(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "Describe how the canvas should move:")
        if ok and prompt:
            self._get_plugin().ltx_i2v(prompt, seconds=3.0)

    def _on_wan_i2v(self):
        from PyQt5.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getText(
            None, "Spellcaster",
            "Describe the motion for WAN I2V:")
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
        from PyQt5.QtWidgets import QInputDialog
        current = Application.readSetting("spellcaster", "server_url",
                                          "http://127.0.0.1:8188")
        url, ok = QInputDialog.getText(None, "Spellcaster Settings",
                                       "ComfyUI Server URL:", text=current)
        if ok and url:
            Application.writeSetting("spellcaster", "server_url", url)
            self._plugin = None  # Force reconnect


Krita.instance().addExtension(SpellcasterExtension(Krita.instance()))
