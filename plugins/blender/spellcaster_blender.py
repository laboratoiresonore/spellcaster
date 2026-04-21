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
try:
    from spellcaster_core.plugin_presets import presets_for
except Exception:
    def presets_for(_origin):
        return []


class BlenderSpellcaster(SpellcasterPlugin):
    """Blender-specific Spellcaster implementation."""

    def _heartbeat_meta(self):
        # Populate ``meta`` on every /api/interfaces/heartbeat ping so
        # the Guild UI can show the live Blender version alongside the
        # chip. bl_info is mandatory for every Blender addon.
        v = bl_info.get("version", (0, 0, 0))
        return {
            "plugin": "blender",
            "plugin_version": ".".join(str(x) for x in v),
            "blender_min": ".".join(str(x) for x in bl_info.get("blender", (0, 0, 0))),
            "transport": "plugin_base",
        }

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
        guild = (prefs.preferences.guild_url
                 if prefs and hasattr(prefs.preferences, "guild_url")
                 else "http://127.0.0.1:7777")
        # Constructing with a guild_url + origin starts the heartbeat
        # loop AND enables per-generation AssetGallery stash (see
        # plugin_base.SpellcasterPlugin — cross-interface backbone
        # §15). Leaving guild blank falls back to pure ComfyUI-direct
        # mode for users who haven't set up the Guild.
        _plugin[0] = BlenderSpellcaster(url, guild_url=guild, origin="blender")
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


class SPELLCASTER_OT_outpaint(bpy.types.Operator):
    bl_idname = "spellcaster.outpaint"
    bl_label = "Extend Canvas (Outpaint)"
    bl_description = "Grow the active image by generating new pixels at its edges"

    prompt: bpy.props.StringProperty(
        name="What should appear in the extended area", default="")
    pixels: bpy.props.IntProperty(
        name="Pixels to extend", default=256, min=64, max=1024)
    direction: bpy.props.EnumProperty(
        name="Edge", default="right",
        items=[
            ("right",  "Right",  "Extend to the right"),
            ("left",   "Left",   "Extend to the left"),
            ("top",    "Top",    "Extend upward"),
            ("bottom", "Bottom", "Extend downward"),
        ])

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")
        self.layout.prop(self, "pixels")
        self.layout.prop(self, "direction")

    def execute(self, context):
        if not self.prompt:
            return {'CANCELLED'}
        kwargs = {"left": 0, "top": 0, "right": 0, "bottom": 0}
        kwargs[self.direction] = int(self.pixels)
        _get_plugin().outpaint(self.prompt, **kwargs)
        return {'FINISHED'}


class SPELLCASTER_OT_iclight(bpy.types.Operator):
    bl_idname = "spellcaster.iclight"
    bl_label = "Relight (IC-Light)"
    bl_description = "Re-light the current image with a text prompt (SD 1.5 IC-Light)"

    prompt: bpy.props.StringProperty(
        name="Lighting",
        default="golden hour from upper-left",
        description="Describe the desired light (direction + colour + intensity)")
    multiplier: bpy.props.FloatProperty(
        name="Strength", default=0.18, min=0.0, max=1.0,
        description="IC-Light strength — 0.18 subtle, 0.4 strong")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")
        self.layout.prop(self, "multiplier")

    def execute(self, context):
        if self.prompt:
            _get_plugin().iclight(self.prompt,
                                    multiplier=float(self.multiplier))
        return {'FINISHED'}


class SPELLCASTER_OT_normal_map(bpy.types.Operator):
    bl_idname = "spellcaster.normal_map"
    bl_label = "Generate 3D Normal Map"
    bl_description = "Run NormalCrafter on the active image; result imports as a new image named 'Normal Map (auto)'"

    def execute(self, context):
        _get_plugin().normal_map()
        return {'FINISHED'}


class SPELLCASTER_OT_detail_hallucinate(bpy.types.Operator):
    bl_idname = "spellcaster.detail_hallucinate"
    bl_label = "Detail Hallucinate"
    bl_description = "Upscale the active image and hallucinate fine detail"

    prompt: bpy.props.StringProperty(
        name="Detail hint", default="crisp detail, fine texture")
    factor: bpy.props.FloatProperty(
        name="Upscale factor", default=2.0, min=1.0, max=4.0)
    denoise: bpy.props.FloatProperty(
        name="Denoise", default=0.35, min=0.1, max=0.7)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")
        self.layout.prop(self, "factor")
        self.layout.prop(self, "denoise")

    def execute(self, context):
        _get_plugin().detail_hallucinate(
            self.prompt or "detail, texture",
            upscale_factor=float(self.factor),
            denoise=float(self.denoise))
        return {'FINISHED'}


class SPELLCASTER_OT_colorize(bpy.types.Operator):
    bl_idname = "spellcaster.colorize"
    bl_label = "Colorize B&W"
    bl_description = "Colorize a black-and-white image using ControlNet guidance"

    prompt: bpy.props.StringProperty(
        name="Colour hint",
        default="natural colors, warm midtones")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")

    def execute(self, context):
        _get_plugin().colorize(self.prompt or "")
        return {'FINISHED'}


class SPELLCASTER_OT_magic_eraser(bpy.types.Operator):
    bl_idname = "spellcaster.magic_eraser"
    bl_label = "Magic Eraser"
    bl_description = "Describe an object to remove; SAM3 + LaMa handle the rest"

    prompt: bpy.props.StringProperty(
        name="What to remove", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")

    def execute(self, context):
        if not self.prompt:
            return {'CANCELLED'}
        _get_plugin().magic_eraser(self.prompt)
        return {'FINISHED'}


class SPELLCASTER_OT_ltx_t2v(bpy.types.Operator):
    bl_idname = "spellcaster.ltx_t2v"
    bl_label = "LTX Text-to-Video"
    bl_description = "Generate a short video from a prompt via LTX 2.3"

    prompt: bpy.props.StringProperty(name="Scene", default="")
    seconds: bpy.props.FloatProperty(
        name="Seconds", default=3.0, min=0.5, max=6.0)
    width: bpy.props.IntProperty(name="Width", default=1280, min=256, max=1920)
    height: bpy.props.IntProperty(name="Height", default=720, min=256, max=1920)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")
        self.layout.prop(self, "seconds")
        self.layout.prop(self, "width")
        self.layout.prop(self, "height")

    def execute(self, context):
        if not self.prompt:
            return {'CANCELLED'}
        _get_plugin().ltx_t2v(
            self.prompt, seconds=float(self.seconds),
            width=int(self.width), height=int(self.height))
        return {'FINISHED'}


class SPELLCASTER_OT_ltx_i2v(bpy.types.Operator):
    bl_idname = "spellcaster.ltx_i2v"
    bl_label = "LTX Image-to-Video"
    bl_description = "Animate the active image via LTX 2.3 I2V"

    prompt: bpy.props.StringProperty(name="Motion", default="")
    seconds: bpy.props.FloatProperty(
        name="Seconds", default=3.0, min=0.5, max=6.0)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")
        self.layout.prop(self, "seconds")

    def execute(self, context):
        if not self.prompt:
            return {'CANCELLED'}
        _get_plugin().ltx_i2v(self.prompt, seconds=float(self.seconds))
        return {'FINISHED'}


class SPELLCASTER_OT_wan_i2v(bpy.types.Operator):
    bl_idname = "spellcaster.wan_i2v"
    bl_label = "WAN Image-to-Video"
    bl_description = "Animate the active image via WAN 2.2 I2V"

    prompt: bpy.props.StringProperty(name="Motion", default="")
    seconds: bpy.props.FloatProperty(
        name="Seconds", default=5.0, min=1.0, max=8.0)
    turbo: bpy.props.BoolProperty(
        name="Turbo (6 steps)", default=True,
        description="Lightning distilled; slower + more stable when off")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        self.layout.prop(self, "prompt")
        self.layout.prop(self, "seconds")
        self.layout.prop(self, "turbo")

    def execute(self, context):
        if not self.prompt:
            return {'CANCELLED'}
        _get_plugin().wan_i2v(
            self.prompt, seconds=float(self.seconds),
            turbo=bool(self.turbo))
        return {'FINISHED'}


def _preset_items_blender(self, context):
    presets = presets_for("blender")
    if not presets:
        return [("_none", "(no presets available)", "")]
    return [(str(i), p["label"], p.get("prompt") or "")
            for i, p in enumerate(presets)]


class SPELLCASTER_OT_preset(bpy.types.Operator):
    bl_idname = "spellcaster.preset"
    bl_label = "Run Preset"
    bl_description = "Pick one of the bundled Blender-oriented presets"

    preset_idx: bpy.props.EnumProperty(
        name="Preset", items=_preset_items_blender)
    prompt_override: bpy.props.StringProperty(
        name="Prompt (edit)", default="")

    def invoke(self, context, event):
        # Pre-fill prompt from the default preset.
        presets = presets_for("blender")
        try:
            idx = int(self.preset_idx)
        except Exception:
            idx = 0
        if 0 <= idx < len(presets):
            self.prompt_override = presets[idx].get("prompt") or ""
        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        self.layout.prop(self, "preset_idx")
        self.layout.prop(self, "prompt_override")

    def execute(self, context):
        presets = presets_for("blender")
        try:
            idx = int(self.preset_idx)
        except Exception:
            idx = 0
        if not (0 <= idx < len(presets)):
            return {'CANCELLED'}
        preset = presets[idx]
        plug = _get_plugin()
        op = preset.get("op", "txt2img")
        prompt = self.prompt_override or preset.get("prompt") or ""
        kwargs = dict(preset.get("kwargs") or {})
        if preset.get("arch") and op in (
                "txt2img", "img2img", "colorize",
                "detail_hallucinate", "style_transfer"):
            kwargs["arch"] = preset["arch"]
        fn = getattr(plug, op, None)
        if not fn:
            plug.show_error(f"Preset op '{op}' not available.")
            return {'CANCELLED'}
        try:
            if op in ("upscale", "rembg", "normal_map"):
                fn()
            elif op == "magic_eraser":
                fn(prompt)
            else:
                fn(prompt, **kwargs)
        except Exception as e:
            plug.show_error(f"Preset failed: {e}")
            return {'CANCELLED'}
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
        layout.operator("spellcaster.preset", icon='PRESET')
        layout.separator()
        layout.operator("spellcaster.auto", icon='SHADERFX')
        layout.operator("spellcaster.txt2img", icon='IMAGE')
        layout.operator("spellcaster.img2img", icon='BRUSH_DATA')
        layout.operator("spellcaster.outpaint", icon='ARROW_LEFTRIGHT')
        layout.operator("spellcaster.iclight", icon='LIGHT')
        layout.separator()
        layout.operator("spellcaster.detail_hallucinate", icon='MOD_SMOOTH')
        layout.operator("spellcaster.colorize", icon='COLOR')
        layout.operator("spellcaster.magic_eraser", icon='BRUSHES_ALL')
        layout.operator("spellcaster.upscale", icon='FULLSCREEN_ENTER')
        layout.operator("spellcaster.rembg", icon='MATPLANE')
        layout.operator("spellcaster.normal_map", icon='TEXTURE_DATA')
        layout.separator()
        layout.operator("spellcaster.ltx_t2v", icon='RENDER_ANIMATION')
        layout.operator("spellcaster.ltx_i2v", icon='PLAY')
        layout.operator("spellcaster.wan_i2v", icon='FILE_MOVIE')


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
    guild_url: bpy.props.StringProperty(
        name="Wizard Guild URL",
        default="http://127.0.0.1:7777",
        description=(
            "Optional: Wizard Guild for cross-app asset sharing with GIMP, "
            "Darktable, Resolve, SillyTavern. Leave blank to run stand-alone."),
    )

    def draw(self, context):
        self.layout.prop(self, "server_url")
        self.layout.prop(self, "guild_url")


# ═══════════════════════════════════════════════════════════════════════
#  Registration
# ═══════════════════════════════════════════════════════════════════════

classes = [
    SpellcasterPreferences,
    SPELLCASTER_OT_txt2img,
    SPELLCASTER_OT_auto,
    SPELLCASTER_OT_img2img,
    SPELLCASTER_OT_outpaint,
    SPELLCASTER_OT_iclight,
    SPELLCASTER_OT_upscale,
    SPELLCASTER_OT_rembg,
    SPELLCASTER_OT_normal_map,
    SPELLCASTER_OT_detail_hallucinate,
    SPELLCASTER_OT_colorize,
    SPELLCASTER_OT_magic_eraser,
    SPELLCASTER_OT_ltx_t2v,
    SPELLCASTER_OT_ltx_i2v,
    SPELLCASTER_OT_wan_i2v,
    SPELLCASTER_OT_preset,
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
