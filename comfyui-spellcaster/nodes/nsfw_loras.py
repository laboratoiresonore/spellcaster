"""SpellcasterNSFWLoRA — NSFW LoRA preset loader with category management.

Provides curated NSFW LoRA presets organized by architecture and category.
Supports stacking multiple LoRAs with individual strength controls.

Uses the exact same comfy.sd.load_lora_for_models() API as ComfyUI's
built-in LoraLoader node.
"""

import os
import folder_paths
import comfy.sd
import comfy.utils

# ── NSFW LoRA registry ─────────────────────────────────────────────────
# Organized by architecture → category → list of LoRA filenames.
# The node auto-discovers which LoRAs are actually installed on disk.

NSFW_LORA_PRESETS = {
    "flux1dev": {
        "nsfw_unlock": [
            "aidmaNSFWunlock-FLUX-V0.2.safetensors",
        ],
        "body_type": [
            "NSFW_Flux_Petite-000002.safetensors",
        ],
        "anatomy_detail": [
            "FluxSideboob.safetensors",
            "flux-lora-foot.safetensors",
            "foot feet v1.safetensors",
            "sharp detailed image (foot focus) v1.1.safetensors",
            "CTAI- Hand and foot details v1.0.safetensors",
        ],
        "klein_nsfw": [
            "NSFW-klein.safetensors",
            "Flux Klein - NSFW v2.safetensors",
            "SEXGOD_FemaleNudity_Klein9b_v2.safetensors",
        ],
    },
    "flux2klein": {
        "acts": [
            "POV_blowjobV1_A.safetensors",
            "POV_blowjobV1_B.safetensors",
        ],
        "effects": [
            "PornMaster_cum_flux-2-klein-9b_V1.safetensors",
            "thick_cum_v1_f2k_9b_000002750.safetensors",
        ],
    },
    "sdxl": {
        "anatomy_detail": [
            "RealFeet_xl_v1.safetensors",
            "feet v2.safetensors",
        ],
    },
    "illustrious": {
        "anatomy_detail": [
            "detailed foot focus style illustriousXL v1.safetensors",
        ],
    },
    "wan_i2v": {
        "effects": [
            "Wan22_CumV2_High.safetensors",
            "Wan22_CumV2_Low.safetensors",
            "23High noise-Cumshot Aesthetics.safetensors",
            "56Low noise-Cumshot Aesthetics.safetensors",
        ],
        "acts": [
            "wan22_i2v_footjob_v2_ab_high.safetensors",
            "wan22_i2v_footjob_v2_ab_low.safetensors",
            "wan22_i2v_anal_v1_high_noise.safetensors",
            "wan22_i2v_anal_v1_low_noise.safetensors",
            "wan2.2-i2v-high-oral-insertion-v1.0.safetensors",
            "wan2.2-i2v-low-oral-insertion-v1.0.safetensors",
            "wan2.2_i2v_highnoise_footjob_v1.0.safetensors",
            "wan2.2_i2v_lownoise_footjob_v1.0.safetensors",
            "WAN-2.2-I2V-Double-Blowjob-HIGH-v1.safetensors",
            "WAN-2.2-I2V-Double-Blowjob-LOW-v1.safetensors",
        ],
        "anatomy_detail": [
            "wan2.2_i2v_highnoise_FOOT_WORSHIP_TOE_SUCKING_v1.0.safetensors",
            "wan2.2_i2v_lownoise_FOOT_WORSHIP_TOE_SUCKING_v1.0.safetensors",
            "wan22_i2v_feetup_V3_high_noise.safetensors",
            "wan22_i2v_feetup_V3_low_noise.safetensors",
        ],
        "general_nsfw": [
            "NSFW-22-H-e8.safetensors",
            "NSFW-22-L-e8.safetensors",
            "DR34ML4Y_I2V_14B_LOW_V2.safetensors",
        ],
        "motion": [
            "KISSHIGH.safetensors",
            "KISSLOW.safetensors",
            "wriggling_i2v_high_e010.safetensors",
            "wriggling_i2v_low_e020.safetensors",
        ],
    },
}


def _get_all_loras():
    """Return the full list of LoRA filenames ComfyUI knows about."""
    return folder_paths.get_filename_list("loras")


def _get_installed_nsfw_loras():
    """Return NSFW preset LoRAs that are actually installed on this system."""
    all_loras = _get_all_loras()
    # Build a set of basenames for fast lookup
    installed_basenames = {os.path.basename(l): l for l in all_loras}
    # Also check with full relative paths
    installed_set = set(all_loras)

    found = {}
    for arch, categories in NSFW_LORA_PRESETS.items():
        for cat, filenames in categories.items():
            for fname in filenames:
                # Try exact match first, then basename
                if fname in installed_set:
                    found[fname] = fname
                elif fname in installed_basenames:
                    found[fname] = installed_basenames[fname]
                else:
                    # Try partial match (basename in full path)
                    for lora_path in all_loras:
                        if lora_path.endswith(fname):
                            found[fname] = lora_path
                            break
    return found


def _get_categories_for_arch(arch_key):
    """Get available NSFW categories for an architecture."""
    # Map arch_keys to NSFW_LORA_PRESETS keys
    arch_map = {
        "flux1dev": "flux1dev",
        "flux_dev": "flux1dev",
        "flux2klein": "flux2klein",
        "flux_2_klein": "flux2klein",
        "sdxl": "sdxl",
        "illustrious": "illustrious",
        "wan_i2v": "wan_i2v",
        "wan": "wan_i2v",
    }
    preset_key = arch_map.get(arch_key, arch_key)
    return NSFW_LORA_PRESETS.get(preset_key, {})


class SpellcasterNSFWLoRA:
    """Load one or more NSFW LoRAs onto MODEL + CLIP by preset category.

    Supports three modes:
    - "preset": Pick from curated NSFW categories for the detected architecture
    - "manual": Pick any LoRA from the full loras/ folder
    - "stack": Apply a preset category (all LoRAs in that category at once)
    """

    @classmethod
    def INPUT_TYPES(cls):
        all_loras = ["none"] + folder_paths.get_filename_list("loras")
        all_categories = set()
        for arch_cats in NSFW_LORA_PRESETS.values():
            all_categories.update(arch_cats.keys())
        categories = ["none"] + sorted(all_categories)

        return {
            "required": {
                "model": ("MODEL", {"tooltip": "MODEL from SpellcasterLoader or another loader"}),
                "clip": ("CLIP", {"tooltip": "CLIP from SpellcasterLoader or another loader"}),
                "mode": (["preset", "manual", "stack"], {
                    "default": "preset",
                    "tooltip": "preset: single LoRA from NSFW category. manual: any LoRA. stack: all LoRAs in a category.",
                }),
                "strength_model": ("FLOAT", {
                    "default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01,
                    "tooltip": "LoRA strength applied to MODEL weights",
                }),
                "strength_clip": ("FLOAT", {
                    "default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01,
                    "tooltip": "LoRA strength applied to CLIP weights",
                }),
            },
            "optional": {
                "arch_key": ("STRING", {
                    "default": "",
                    "tooltip": "Architecture key from SpellcasterLoader (auto-selects NSFW presets). Leave empty for manual mode.",
                }),
                "category": (categories, {
                    "default": "none",
                    "tooltip": "NSFW LoRA category (for preset/stack modes)",
                }),
                "lora_name": (all_loras, {
                    "default": "none",
                    "tooltip": "Manual LoRA selection (for manual mode)",
                }),
                "preset_index": ("INT", {
                    "default": 0, "min": 0, "max": 50,
                    "tooltip": "Which LoRA within the category to use (preset mode only, 0 = first)",
                }),
            },
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING")
    RETURN_NAMES = ("model", "clip", "applied_loras")
    OUTPUT_TOOLTIPS = (
        "MODEL with NSFW LoRA(s) applied",
        "CLIP with NSFW LoRA(s) applied",
        "Comma-separated list of applied LoRA filenames",
    )
    FUNCTION = "load_nsfw_lora"
    CATEGORY = "Spellcaster/NSFW"
    DESCRIPTION = "Load NSFW LoRAs by architecture-aware presets or manual selection. Chain multiple for stacking."

    def load_nsfw_lora(self, model, clip, mode, strength_model, strength_clip,
                       arch_key="", category="none", lora_name="none", preset_index=0):
        applied = []

        if mode == "manual":
            # Manual: load a single user-selected LoRA
            if lora_name == "none":
                return (model, clip, "")
            model, clip = self._apply_lora(model, clip, lora_name, strength_model, strength_clip)
            applied.append(os.path.basename(lora_name))

        elif mode == "preset":
            # Preset: load one LoRA from an NSFW category for the given arch
            if category == "none" or not arch_key:
                return (model, clip, "")
            categories = _get_categories_for_arch(arch_key)
            lora_list = categories.get(category, [])
            installed = _get_installed_nsfw_loras()

            # Filter to installed only
            available = [(f, installed[f]) for f in lora_list if f in installed]
            if not available:
                print(f"\033[33m[Spellcaster NSFW]\033[0m No installed LoRAs for {arch_key}/{category}")
                return (model, clip, "")

            idx = min(preset_index, len(available) - 1)
            fname, full_path = available[idx]
            model, clip = self._apply_lora(model, clip, full_path, strength_model, strength_clip)
            applied.append(os.path.basename(fname))

        elif mode == "stack":
            # Stack: load ALL LoRAs in a category
            if category == "none" or not arch_key:
                return (model, clip, "")
            categories = _get_categories_for_arch(arch_key)
            lora_list = categories.get(category, [])
            installed = _get_installed_nsfw_loras()

            available = [(f, installed[f]) for f in lora_list if f in installed]
            if not available:
                print(f"\033[33m[Spellcaster NSFW]\033[0m No installed LoRAs for {arch_key}/{category}")
                return (model, clip, "")

            for fname, full_path in available:
                model, clip = self._apply_lora(model, clip, full_path, strength_model, strength_clip)
                applied.append(os.path.basename(fname))
                print(f"\033[35m[Spellcaster NSFW]\033[0m Stacked: {fname} (str={strength_model:.2f})")

        return (model, clip, ", ".join(applied))

    @staticmethod
    def _apply_lora(model, clip, lora_name, strength_model, strength_clip):
        """Load and apply a single LoRA — mirrors ComfyUI's built-in LoraLoader."""
        lora_path = folder_paths.get_full_path_or_raise("loras", lora_name)
        lora = comfy.utils.load_torch_file(lora_path, safe_load=True)
        model_lora, clip_lora = comfy.sd.load_lora_for_models(
            model, clip, lora, strength_model, strength_clip,
        )
        return model_lora, clip_lora


class SpellcasterNSFWLoRAModelOnly:
    """Load NSFW LoRA onto MODEL only (no CLIP). For video pipelines like WAN I2V."""

    @classmethod
    def INPUT_TYPES(cls):
        all_loras = ["none"] + folder_paths.get_filename_list("loras")
        all_categories = set()
        for arch_cats in NSFW_LORA_PRESETS.values():
            all_categories.update(arch_cats.keys())
        categories = ["none"] + sorted(all_categories)

        return {
            "required": {
                "model": ("MODEL", {"tooltip": "MODEL from loader"}),
                "mode": (["preset", "manual", "stack"], {"default": "preset"}),
                "strength_model": ("FLOAT", {
                    "default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01,
                }),
            },
            "optional": {
                "arch_key": ("STRING", {"default": ""}),
                "category": (categories, {"default": "none"}),
                "lora_name": (all_loras, {"default": "none"}),
                "preset_index": ("INT", {"default": 0, "min": 0, "max": 50}),
            },
        }

    RETURN_TYPES = ("MODEL", "STRING")
    RETURN_NAMES = ("model", "applied_loras")
    OUTPUT_TOOLTIPS = ("MODEL with NSFW LoRA(s) applied", "Applied LoRA names")
    FUNCTION = "load_nsfw_lora_model_only"
    CATEGORY = "Spellcaster/NSFW"
    DESCRIPTION = "Load NSFW LoRAs onto MODEL only (for video/WAN pipelines where CLIP is separate)."

    def load_nsfw_lora_model_only(self, model, mode, strength_model,
                                   arch_key="", category="none", lora_name="none", preset_index=0):
        applied = []

        if mode == "manual":
            if lora_name == "none":
                return (model, "")
            model = self._apply_lora(model, lora_name, strength_model)
            applied.append(os.path.basename(lora_name))

        elif mode == "preset":
            if category == "none" or not arch_key:
                return (model, "")
            categories = _get_categories_for_arch(arch_key)
            lora_list = categories.get(category, [])
            installed = _get_installed_nsfw_loras()
            available = [(f, installed[f]) for f in lora_list if f in installed]
            if not available:
                return (model, "")
            idx = min(preset_index, len(available) - 1)
            fname, full_path = available[idx]
            model = self._apply_lora(model, full_path, strength_model)
            applied.append(os.path.basename(fname))

        elif mode == "stack":
            if category == "none" or not arch_key:
                return (model, "")
            categories = _get_categories_for_arch(arch_key)
            lora_list = categories.get(category, [])
            installed = _get_installed_nsfw_loras()
            available = [(f, installed[f]) for f in lora_list if f in installed]
            for fname, full_path in available:
                model = self._apply_lora(model, full_path, strength_model)
                applied.append(os.path.basename(fname))

        return (model, ", ".join(applied))

    @staticmethod
    def _apply_lora(model, lora_name, strength_model):
        """Load and apply LoRA to model only — mirrors LoraLoaderModelOnly."""
        lora_path = folder_paths.get_full_path_or_raise("loras", lora_name)
        lora = comfy.utils.load_torch_file(lora_path, safe_load=True)
        model_lora, _ = comfy.sd.load_lora_for_models(
            model, None, lora, strength_model, 0,
        )
        return model_lora
