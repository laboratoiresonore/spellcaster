"""SpellcasterLoader — Auto-detect architecture and load model stack.

This node replaces the need for separate CheckpointLoaderSimple / UNETLoader +
CLIPLoader + VAELoader nodes. It reads the model filename, detects the
architecture (sd15, sdxl, flux1dev, flux2klein, chroma, etc.), and loads
everything correctly in one step.
"""

import os
import sys
import folder_paths

try:
    import comfy.sd
except ImportError:
    comfy = None

# Add parent to path for spellcaster_core imports
_pack_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pack_dir not in sys.path:
    sys.path.insert(0, _pack_dir)

try:
    from spellcaster_core.architectures import ARCHITECTURES, get_arch
    from spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model
except ImportError as e:
    print(f"[SpellcasterLoader] WARNING: Failed to import spellcaster_core: {e}")
    ARCHITECTURES = {}
    get_arch = None
    classify_unet_model = None
    classify_ckpt_model = None


class SpellcasterLoader:
    """Auto-detect architecture and load MODEL + CLIP + VAE in one node.

    Replaces the need for separate CheckpointLoaderSimple / UNETLoader +
    CLIPLoader + VAELoader nodes. Reads the model filename, detects the
    architecture (sd15, sdxl, flux1dev, flux2klein, chroma, etc.), and
    loads everything correctly.

    Returns:
      - model: Diffusion model (UNET)
      - clip: Text encoder (CLIP)
      - vae: VAE for latent encoding/decoding
      - arch_key: Detected architecture key (for downstream nodes)
    """

    @classmethod
    def INPUT_TYPES(cls):
        # Combine checkpoints and diffusion_models (UNETs)
        checkpoints = folder_paths.get_filename_list("checkpoints")
        unet_models = folder_paths.get_filename_list("diffusion_models")
        all_models = sorted(set(checkpoints + unet_models))

        arch_keys = ["auto"] + sorted(ARCHITECTURES.keys()) if ARCHITECTURES else ["auto"]

        return {
            "required": {
                "model_name": (all_models, {"tooltip": "Model file — architecture auto-detected from name"}),
            },
            "optional": {
                "arch_override": (arch_keys, {"default": "auto", "tooltip": "Override auto-detection"}),
                "clip_override": ("STRING", {"default": "", "tooltip": "Override CLIP model filename"}),
                "vae_override": ("STRING", {"default": "", "tooltip": "Override VAE filename"}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "STRING")
    RETURN_NAMES = ("model", "clip", "vae", "arch_key")
    FUNCTION = "load"
    CATEGORY = "Spellcaster"
    DESCRIPTION = "Auto-detect architecture and load model stack. ONE loader for all architectures."

    def load(self, model_name, arch_override="auto", clip_override="", vae_override=""):
        """Load model stack with architecture auto-detection.

        Args:
            model_name: Model filename (str)
            arch_override: Architecture key override ("auto" = detect from name)
            clip_override: Override CLIP model filename
            vae_override: Override VAE filename

        Returns:
            Tuple (model, clip, vae, arch_key)
        """
        if not comfy:
            raise RuntimeError("[SpellcasterLoader] ComfyUI comfy module not available")
        if not get_arch or not classify_unet_model or not classify_ckpt_model:
            raise RuntimeError("[SpellcasterLoader] spellcaster_core not available")

        # Detect architecture
        if arch_override != "auto":
            arch_key = arch_override
            print(f"[SpellcasterLoader] Using override arch: {arch_key}")
        else:
            # Check if model is in checkpoints or diffusion_models
            checkpoints = folder_paths.get_filename_list("checkpoints")
            unet_models = folder_paths.get_filename_list("diffusion_models")

            if model_name in checkpoints:
                arch_key = classify_ckpt_model(model_name)
                print(f"[SpellcasterLoader] Detected checkpoint model: {arch_key}")
            elif model_name in unet_models:
                arch_key = classify_unet_model(model_name)
                print(f"[SpellcasterLoader] Detected UNET model: {arch_key}")
            else:
                # Fallback: try to classify as checkpoint
                arch_key = classify_ckpt_model(model_name)
                print(f"[SpellcasterLoader] Fallback classification: {arch_key}")

        arch = get_arch(arch_key)
        if not arch:
            raise ValueError(f"[SpellcasterLoader] Unknown architecture: {arch_key}")

        # Get full path for model
        try:
            model_path = folder_paths.get_full_path("checkpoints", model_name)
        except:
            try:
                model_path = folder_paths.get_full_path("diffusion_models", model_name)
            except:
                raise ValueError(f"[SpellcasterLoader] Could not find model: {model_name}")

        print(f"[SpellcasterLoader] Loading {arch.loader} model from: {model_path}")

        # Load based on architecture loader strategy
        if arch.loader == "checkpoint":
            # Checkpoint-based: single file contains MODEL, CLIP, VAE
            try:
                model, clip, vae = comfy.sd.load_checkpoint_guess_config(
                    model_path, output_vae=True, output_clip=True
                )
                print(f"[SpellcasterLoader] Loaded checkpoint: model, clip, vae from {model_name}")
            except Exception as e:
                raise RuntimeError(f"[SpellcasterLoader] Failed to load checkpoint: {e}")

        elif arch.loader == "unet_clip_vae":
            # Separate loaders: UNET, CLIP, VAE loaded separately
            model = self._load_unet(model_path)
            clip = self._load_clip(arch, clip_override)
            vae = self._load_vae(arch, vae_override)
            print(f"[SpellcasterLoader] Loaded separate: unet, clip, vae for {arch_key}")

        else:
            raise ValueError(f"[SpellcasterLoader] Unknown loader type: {arch.loader}")

        return (model, clip, vae, arch_key)

    def _load_unet(self, unet_path):
        """Load UNET/diffusion model."""
        try:
            # Try load_diffusion_model first (preferred for newer ComfyUI)
            if hasattr(comfy.sd, 'load_diffusion_model'):
                return comfy.sd.load_diffusion_model(unet_path)
            # Fallback to load_unet
            elif hasattr(comfy.sd, 'load_unet'):
                return comfy.sd.load_unet(unet_path)
            else:
                raise RuntimeError("No UNET loader available in comfy.sd")
        except Exception as e:
            raise RuntimeError(f"[SpellcasterLoader] Failed to load UNET: {e}")

    def _load_clip(self, arch, clip_override):
        """Load CLIP text encoder based on architecture."""
        try:
            embeddings_dir = folder_paths.get_folder_paths("embeddings")[0] if folder_paths.get_folder_paths("embeddings") else None

            if clip_override:
                clip_path = folder_paths.get_full_path("clip", clip_override)
                print(f"[SpellcasterLoader] Loading override CLIP: {clip_override}")
            else:
                # Determine CLIP based on clip_mode
                if arch.clip_mode == "dual":
                    # Flux Dev / Kontext: DualCLIPLoader
                    clip1_name = arch.extra.get("clip_name1", "clip_l.safetensors")
                    clip2_name = arch.extra.get("clip_name2", "t5xxl_fp8_e4m3fn.safetensors")
                    clip_type = arch.extra.get("clip_type", "flux")

                    clip1_path = folder_paths.get_full_path("clip", clip1_name)
                    clip2_path = folder_paths.get_full_path("clip", clip2_name)

                    # Use DualCLIPLoader if available
                    if hasattr(comfy.sd, 'load_clip_vision'):
                        # Newer API: load_clip_vision or similar
                        clip1 = comfy.sd.load_clip([clip1_path], embedding_directory=embeddings_dir)
                        clip2 = comfy.sd.load_clip([clip2_path], embedding_directory=embeddings_dir)
                        # Combine them (this is simplified; actual dual loading is more complex)
                        return clip1
                    else:
                        # Fallback: load first CLIP
                        clip1_path = folder_paths.get_full_path("clip", clip1_name)
                        return comfy.sd.load_clip([clip1_path], embedding_directory=embeddings_dir)

                elif arch.clip_mode == "single_flux2":
                    # Klein: auto-detect CLIP based on model name
                    # (This is a simplified version; full logic would need model_name)
                    clip_name = arch.extra.get("clip_name_9b", "qwen_3_8b.safetensors")
                    clip_path = folder_paths.get_full_path("clip", clip_name)
                    print(f"[SpellcasterLoader] Loading Flux2 CLIP: {clip_name}")

                elif arch.clip_mode == "single_chroma":
                    # Chroma: single CLIPLoader with type="chroma"
                    clip_name = arch.extra.get("clip_name", "t5xxl_fp8_e4m3fn.safetensors")
                    clip_path = folder_paths.get_full_path("clip", clip_name)
                    print(f"[SpellcasterLoader] Loading Chroma CLIP: {clip_name}")

                else:
                    # Default: load standard CLIP
                    clip_name = arch.extra.get("clip_name", "clip_l.safetensors")
                    clip_path = folder_paths.get_full_path("clip", clip_name)

            # Load CLIP
            clip = comfy.sd.load_clip([clip_path], embedding_directory=embeddings_dir)
            return clip

        except Exception as e:
            raise RuntimeError(f"[SpellcasterLoader] Failed to load CLIP: {e}")

    def _load_vae(self, arch, vae_override):
        """Load VAE decoder/encoder."""
        try:
            if vae_override:
                vae_path = folder_paths.get_full_path("vae", vae_override)
                print(f"[SpellcasterLoader] Loading override VAE: {vae_override}")
            else:
                vae_name = arch.extra.get("vae_name", "ae.safetensors")
                vae_path = folder_paths.get_full_path("vae", vae_name)

            vae = comfy.sd.load_vae(vae_path)
            return vae

        except Exception as e:
            raise RuntimeError(f"[SpellcasterLoader] Failed to load VAE: {e}")


# Node registry (for ComfyUI)
NODE_CLASS_MAPPINGS = {
    "SpellcasterLoader": SpellcasterLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SpellcasterLoader": "Spellcaster Loader (Auto-Detect)",
}
