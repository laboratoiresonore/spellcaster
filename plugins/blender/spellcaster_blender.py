"""Spellcaster for Blender — AI texture generation, reference images, concept art.

Install: Edit -> Preferences -> Add-ons -> Install from File -> select this .py
         Enable "Spellcaster" in the add-on list.

Requires: ComfyUI running (local or network), spellcaster_core in Python path.
"""

bl_info = {
    "name": "Spellcaster",
    "author": "laboratoiresonore",
    "version": (2, 2, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Spellcaster",
    "description": "AI image generation via ComfyUI — textures, references, concept art",
    "category": "Paint",
}

import bpy
import os
import sys
import tempfile

# Add spellcaster_core to path
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in [_HERE, os.path.join(_HERE, "..", "..", "comfyui-spellcaster")]:
    if os.path.isdir(os.path.join(_candidate, "spellcaster_core")):
        if _candidate not in sys.path:
            sys.path.insert(0, _candidate)
        break

from spellcaster_core.plugin_base import SpellcasterPlugin


class BlenderSpellcaster(SpellcasterPlugin):
    """Blender-specific Spellcaster implementation."""

    def get_canvas_png(self):
        """Render current viewport or active image as PNG."""
        # Try active image editor first
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                img = area.spaces.active.image
                if img:
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.close()
                    img.save_render(tmp.name)
                    with open(tmp.name, "rb") as f:
                        data = f.read()
                    os.unlink(tmp.name)
                    return data

        # Fallback: render viewport
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        bpy.context.scene.render.filepath = tmp.name
        bpy.ops.render.opengl(write_still=True)
        with open(tmp.name, "rb") as f:
            data = f.read()
        os.unlink(tmp.name)
        return data

    def insert_layer(self, png_bytes, name="Spellcaster"):
        """Load PNG as a Blender image and optionally assign as texture."""
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(png_bytes)
        tmp.close()
        img = bpy.data.images.load(tmp.name)
        img.name = name
        os.unlink(tmp.name)
        # Open in image editor if available
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.spaces.active.image = img
                break
        return img

    def show_progress(self, message):
        """Show in Blender's status bar."""
        if hasattr(bpy.context, 'window_manager'):
            bpy.context.window_manager.progress_begin(0, 100)
        print(f"[Spellcaster] {message}")

    def show_error(self, message):
        """Show error popup."""
        def draw(self_op, context):
            self_op.layout.label(text=message[:80])
        bpy.context.window_manager.popup_menu(draw, title="Spellcaster Error", icon='ERROR')


# ═══════════════════════════════════════════════════════════════════════
#  Blender Operators
# ═══════════════════════════════════════════════════════════════════════

_plugin = [None]

def _get_plugin():
    if not _plugin[0]:
        prefs = bpy.context.preferences.addons.get(__name__)
        url = prefs.preferences.server_url if prefs else "http://127.0.0.1:8188"
        _plugin[0] = BlenderSpellcaster(url)
    return _plugin[0]


class SPELLCASTER_OT_txt2img(bpy.types.Operator):
    bl_idname = "spellcaster.txt2img"
    bl_label = "Generate Image"
    bl_description = "Generate an image from a text prompt via ComfyUI"

    prompt: bpy.props.StringProperty(name="Prompt", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")

    def execute(self, context):
        if self.prompt:
            _get_plugin().txt2img(self.prompt)
        return {'FINISHED'}


class SPELLCASTER_OT_auto(bpy.types.Operator):
    bl_idname = "spellcaster.auto"
    bl_label = "Smart Generate"
    bl_description = "Auto-detect best model from your prompt"

    prompt: bpy.props.StringProperty(name="What to create", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")

    def execute(self, context):
        if self.prompt:
            _get_plugin().auto(self.prompt)
        return {'FINISHED'}


class SPELLCASTER_OT_img2img(bpy.types.Operator):
    bl_idname = "spellcaster.img2img"
    bl_label = "Transform Image"
    bl_description = "Transform the current image with a prompt"

    prompt: bpy.props.StringProperty(name="Style/change", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")

    def execute(self, context):
        if self.prompt:
            _get_plugin().img2img(self.prompt)
        return {'FINISHED'}


class SPELLCASTER_OT_upscale(bpy.types.Operator):
    bl_idname = "spellcaster.upscale"
    bl_label = "AI Upscale (4x)"
    bl_description = "Upscale the current image with AI"

    def execute(self, context):
        _get_plugin().upscale()
        return {'FINISHED'}


class SPELLCASTER_OT_rembg(bpy.types.Operator):
    bl_idname = "spellcaster.rembg"
    bl_label = "Remove Background"
    bl_description = "Remove background from the current image"

    def execute(self, context):
        _get_plugin().rembg()
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════════
#  Panel (Sidebar)
# ═══════════════════════════════════════════════════════════════════════

class SPELLCASTER_PT_panel(bpy.types.Panel):
    bl_label = "Spellcaster"
    bl_idname = "SPELLCASTER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Spellcaster"

    def draw(self, context):
        layout = self.layout
        layout.operator("spellcaster.auto", icon='SHADERFX')
        layout.operator("spellcaster.txt2img", icon='IMAGE')
        layout.operator("spellcaster.img2img", icon='BRUSH_DATA')
        layout.separator()
        layout.operator("spellcaster.upscale", icon='FULLSCREEN_ENTER')
        layout.operator("spellcaster.rembg", icon='MATPLANE')


# ═══════════════════════════════════════════════════════════════════════
#  Preferences
# ═══════════════════════════════════════════════════════════════════════

class SpellcasterPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    server_url: bpy.props.StringProperty(
        name="ComfyUI Server URL",
        default="http://127.0.0.1:8188",
        description="URL of your ComfyUI server",
    )

    def draw(self, context):
        self.layout.prop(self, "server_url")


# ═══════════════════════════════════════════════════════════════════════
#  Registration
# ═══════════════════════════════════════════════════════════════════════

classes = [
    SpellcasterPreferences,
    SPELLCASTER_OT_txt2img,
    SPELLCASTER_OT_auto,
    SPELLCASTER_OT_img2img,
    SPELLCASTER_OT_upscale,
    SPELLCASTER_OT_rembg,
    SPELLCASTER_PT_panel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _plugin[0] = None

if __name__ == "__main__":
    register()
