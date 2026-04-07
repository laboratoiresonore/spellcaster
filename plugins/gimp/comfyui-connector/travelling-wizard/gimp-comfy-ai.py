#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GIMP Comfy AI - Main plugin class using mixin pattern
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
    """GIMP Comfy AI - Main plugin class using mixin pattern"""

    def __init__(self):
        super().__init__()
        self.config = self._load_config()  # from ConfigMixin
        self._ensure_config_defaults()     # from ConfigMixin
        self._cancel_requested = False

    def do_query_procedures(self):
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
