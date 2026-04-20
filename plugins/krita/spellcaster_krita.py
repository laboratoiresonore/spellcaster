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

        # Upscale
        a4 = window.createAction("spellcaster_upscale", "AI Upscale (4x)", menu)
        a4.triggered.connect(self._on_upscale)

        # Remove background
        a5 = window.createAction("spellcaster_rembg", "Remove Background", menu)
        a5.triggered.connect(self._on_rembg)

        # Face restore
        a6 = window.createAction("spellcaster_face", "Restore Faces", menu)
        a6.triggered.connect(self._on_face_restore)

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

    def _on_upscale(self):
        self._get_plugin().upscale()

    def _on_rembg(self):
        self._get_plugin().rembg()

    def _on_face_restore(self):
        self._get_plugin().face_restore()

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
