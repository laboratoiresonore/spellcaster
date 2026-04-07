#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GIMP Comfy AI Plugin - Main entry point and GIMP procedure registration.

This module serves as the plugin's entry point for GIMP 3.0+. It uses a mixin
pattern to compose multiple functionality modules:
  - ConfigMixin: Load/save persistent plugin settings
  - UtilsMixin: Helper functions for image processing
  - DialogsMixin: Error dialogs and notifications
  - ComfyUIMixin: Low-level HTTP communication with ComfyUI server
  - ImageProcessingMixin: PNG conversion, scaling, etc.
  - InpaintMixin: Inpainting workflow
  - CompositeMixin: Layer compositing
  - GeneratorMixin: Text-to-image generation
  - OutpaintMixin: Outpainting (extend canvas)
  - UpscalerMixin: 4x upscaling via RealESRGAN
  - SettingsMixin: Settings dialog (tabbed UI for workflow configuration)
  - WizardMixin: Travelling Wizard UI (browser-based scaffold editor)

The GimpComfyAIPlugin class registers the following GIMP procedures:
  - gimp-comfy-ai-wizard: "The Travelling Wizard" — open scaffold editor
  - gimp-comfy-ai-inpaint: "Inpainting" — selective image region generation
  - gimp-comfy-ai-layer-generator: "Image Generator" — text-to-image
  - gimp-comfy-ai-layer-composite: "Layer Composite" — blend layers
  - gimp-comfy-ai-outpaint: "Outpaint" — extend canvas boundaries
  - gimp-comfy-ai-upscaler-4x: "Upscaler (RealESRGAN 4x)" — enlarge image
  - gimp-comfy-ai-settings: "Settings" — open settings dialog

All procedures appear under Filters → AI in GIMP's menu.
"""

VERSION = "1.0.0"

import sys
import gi
gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
from gi.repository import Gimp, GLib

# Import all mixins
from config import ConfigMixin
from utils import UtilsMixin
from dialogs import DialogsMixin
from comfyui import ComfyUIMixin
from image_processing import ImageProcessingMixin
from inpaint import InpaintMixin
from composite import CompositeMixin
from generator import GeneratorMixin
from outpaint import OutpaintMixin
from upscaler import UpscalerMixin
from settings import SettingsMixin
from wizard import WizardMixin


class GimpComfyAIPlugin(
    Gimp.PlugIn,
    ConfigMixin,
    UtilsMixin,
    DialogsMixin,
    ComfyUIMixin,
    ImageProcessingMixin,
    InpaintMixin,
    CompositeMixin,
    GeneratorMixin,
    OutpaintMixin,
    UpscalerMixin,
    SettingsMixin,
    WizardMixin,
):
    """GIMP AI Plugin using mixin architecture for modular feature composition.

    This class inherits from multiple mixins, each providing a discrete set of
    functionality. The plugin loads configuration on startup and maintains it
    throughout the session. All GIMP procedure implementations delegate to their
    corresponding mixin methods.

    Attributes:
        config (dict): Persistent configuration loaded from disk (ComfyUI URLs,
                      workflow paths, node overrides, custom workflows, etc.)
        _cancel_requested (bool): Flag to signal cancellation of long operations
    """

    def __init__(self):
        """Initialize the plugin: load GIMP base, load config, set defaults."""
        super().__init__()
        # Load persisted config from ConfigMixin
        self.config = self._load_config()
        self._ensure_config_defaults()
        # Flag for user-initiated cancellation
        self._cancel_requested = False

    def do_query_procedures(self):
        """Return list of all GIMP procedures this plugin registers.

        Called by GIMP's plugin infrastructure during PDB initialization.
        Each returned procedure name will later have do_create_procedure called.

        Returns:
            list[str]: Procedure names (strings)
        """
        return [
            "gimp-comfy-ai-wizard",
            "gimp-comfy-ai-inpaint",
            "gimp-comfy-ai-layer-generator",
            "gimp-comfy-ai-layer-composite",
            "gimp-comfy-ai-outpaint",
            "gimp-comfy-ai-upscaler-4x",
            "gimp-comfy-ai-settings",
        ]

    def do_create_procedure(self, name):
        """Create and return a Gimp.ImageProcedure for the given name.

        Called by GIMP for each procedure name returned by do_query_procedures.
        Each procedure is registered as an ImageProcedure (requires an image as first arg),
        assigned a menu label, and given a menu path under Filters/AI/.

        Args:
            name (str): The procedure name to create

        Returns:
            Gimp.ImageProcedure: The configured procedure, or None if name not recognized
        """
        if name == "gimp-comfy-ai-wizard":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_wizard, None
            )
            procedure.set_menu_label("The Travelling Wizard")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        elif name == "gimp-comfy-ai-inpaint":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_inpaint, None
            )
            procedure.set_menu_label("Inpainting")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        elif name == "gimp-comfy-ai-layer-generator":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_layer_generator, None
            )
            procedure.set_menu_label("Image Generator")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        elif name == "gimp-comfy-ai-layer-composite":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_layer_composite, None
            )
            procedure.set_menu_label("Layer Composite")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        elif name == "gimp-comfy-ai-outpaint":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_outpaint, None
            )
            procedure.set_menu_label("Outpaint")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        elif name == "gimp-comfy-ai-upscaler-4x":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_upscaler_4x, None
            )
            procedure.set_menu_label("Upscaler (RealESRGAN 4x)")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        elif name == "gimp-comfy-ai-settings":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_settings, None
            )
            procedure.set_menu_label("Settings")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        return None


if __name__ == "__main__":
    # Required entrypoint for GIMP to complete the plug-in wire protocol handshake.
    # Without this, the plug-in process exits immediately and GIMP reports:
    #   gimp_wire_read(): unexpected EOF
    Gimp.main(GimpComfyAIPlugin.__gtype__, sys.argv)
