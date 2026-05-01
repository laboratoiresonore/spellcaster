"""SpellcasterLoader — Auto-detect architecture and load model stack.

Replaces the need for separate CheckpointLoaderSimple / UNETLoader +
CLIPLoader + VAELoader nodes.  Reads the model filename, detects the
architecture, and loads MODEL + CLIP + VAE in one step.

Uses the exact same comfy.sd APIs as ComfyUI's built-in loaders.
"""

import os
import sys
import torch
import folder_paths
import comfy.sd
import comfy.utils


from ..spellcaster_core.architectures import ARCHITECTURES, get_arch
from ..spellcaster_core.model_detect import classify_unet_model, classify_ckpt_model


class SpellcasterLoader:
    """Auto-detect architecture and load MODEL + CLIP + VAE in one node."""

    @classmethod
    def INPUT_TYPES(cls):
        checkpoints = folder_paths.get_filename_list("checkpoints")
        unet_models = folder_paths.get_filename_list("diffusion_models")
        all_models  = sorted(set(checkpoints + unet_models))
        arch_keys   = ["auto"] + sorted(ARCHITECTURES.keys())

        return {
            "required": {
                "model_name": (all_models, {
                    "tooltip": "Model file — architecture auto-detected from filename",
                }),
            },
            "optional": {
                "arch_override": (arch_keys, {
                    "default": "auto",
                    "tooltip": "Override auto-detection",
                }),
                "clip_override": (["auto"] + folder_paths.get_filename_list("text_encoders"), {
                    "default": "auto",
                    "tooltip": "Override CLIP file (auto = use architecture default)",
                }),
                "vae_override": (["auto"] + folder_paths.get_filename_list("vae"), {
                    "default": "auto",
                    "tooltip": "Override VAE file (auto = use architecture default)",
                }),
                "weight_dtype": (["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"], {
                    "default": "default",
                    "tooltip": "Weight data type for UNET models",
                }),
            },
        }

    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "STRING")
    RETURN_NAMES = ("model", "clip", "vae", "arch_key")
    OUTPUT_TOOLTIPS = (
        "Diffusion model (UNET) for denoising latents.",
        "CLIP text encoder for prompt encoding.",
        "VAE for encoding/decoding images ↔ latent space.",
        "Detected architecture key (pass to Sampler / Prompt Enhance).",
    )
    FUNCTION = "load"
    CATEGORY = "Spellcaster"
    DESCRIPTION = (
        "Auto-detect model architecture and load the full stack. "
        "Handles checkpoint (SD1.5/SDXL) and separate-loader (Flux/Klein/Chroma) "
        "models transparently."
    )
    SEARCH_ALIASES = ["spellcaster", "auto loader", "smart loader", "auto arch"]

    # ── main entry point ───────────────────────────────────────────────
    def load(self, model_name, arch_override="auto",
             clip_override="auto", vae_override="auto",
             weight_dtype="default"):

        # ── 1. Detect architecture ─────────────────────────────────────
        checkpoints = folder_paths.get_filename_list("checkpoints")
        unet_models = folder_paths.get_filename_list("diffusion_models")

        is_checkpoint = model_name in checkpoints
        is_unet       = model_name in unet_models

        if arch_override != "auto":
            arch_key = arch_override
        elif is_unet:
            arch_key = classify_unet_model(model_name)
        elif is_checkpoint:
            arch_key = classify_ckpt_model(model_name)
        else:
            arch_key = classify_ckpt_model(model_name)  # best-effort

        arch = get_arch(arch_key)
        print(f"\033[36m[Spellcaster]\033[0m {model_name} → arch={arch_key}, "
              f"loader={arch.loader}, clip_mode={arch.clip_mode}")

        # ── 2. Load based on architecture strategy ─────────────────────
        if arch.loader == "checkpoint" or (arch.loader == "unet_clip_vae" and is_checkpoint and not is_unet):
            # Checkpoint path  ─  single file → (MODEL, CLIP, VAE)
            ckpt_path = folder_paths.get_full_path_or_raise("checkpoints", model_name)
            out = comfy.sd.load_checkpoint_guess_config(
                ckpt_path,
                output_vae=True,
                output_clip=True,
                embedding_directory=folder_paths.get_folder_paths("embeddings"),
            )
            model, clip, vae = out[:3]

        else:
            # Separate loaders  ─  UNET + CLIP + VAE loaded independently
            model = self._load_unet(model_name, weight_dtype)
            clip  = self._load_clip(arch, model_name, clip_override)
            vae   = self._load_vae(arch, vae_override)

        return (model, clip, vae, arch_key)

    # ── UNET loader ────────────────────────────────────────────────────
    def _load_unet(self, unet_name, weight_dtype):
        model_options = {}
        if weight_dtype == "fp8_e4m3fn":
            model_options["dtype"] = torch.float8_e4m3fn
        elif weight_dtype == "fp8_e4m3fn_fast":
            model_options["dtype"] = torch.float8_e4m3fn
            model_options["fp8_optimizations"] = True
        elif weight_dtype == "fp8_e5m2":
            model_options["dtype"] = torch.float8_e5m2

        unet_path = folder_paths.get_full_path_or_raise("diffusion_models", unet_name)
        return comfy.sd.load_diffusion_model(unet_path, model_options=model_options)

    # ── CLIP loader ────────────────────────────────────────────────────
    def _load_clip(self, arch, model_name, clip_override):
        embeddings = folder_paths.get_folder_paths("embeddings")

        if clip_override != "auto":
            # Manual override — single CLIP, let ComfyUI figure out type
            clip_path = folder_paths.get_full_path_or_raise("text_encoders", clip_override)
            clip_type = self._resolve_clip_type(arch)
            return comfy.sd.load_clip(
                ckpt_paths=[clip_path],
                embedding_directory=embeddings,
                clip_type=clip_type,
            )

        # ── Auto CLIP selection per clip_mode ──────────────────────────
        if arch.clip_mode == "dual":
            # Flux Dev / Kontext  —  DualCLIPLoader (clip_l + t5xxl)
            c1 = arch.extra.get("clip_name1", "clip_l.safetensors")
            c2 = arch.extra.get("clip_name2", "t5xxl_fp8_e4m3fn.safetensors")
            clip_type_str = arch.extra.get("clip_type", "flux")
            clip_type = getattr(comfy.sd.CLIPType, clip_type_str.upper(),
                                comfy.sd.CLIPType.FLUX)

            p1 = folder_paths.get_full_path_or_raise("text_encoders", c1)
            p2 = folder_paths.get_full_path_or_raise("text_encoders", c2)
            print(f"\033[36m[Spellcaster]\033[0m Dual CLIP: {c1} + {c2} (type={clip_type_str})")
            return comfy.sd.load_clip(
                ckpt_paths=[p1, p2],
                embedding_directory=embeddings,
                clip_type=clip_type,
            )

        elif arch.clip_mode == "single_flux2":
            # Klein  —  auto-detect 9B vs 4B CLIP from model name
            ml = model_name.lower()
            is_4b = ("4b" in ml or "schnell" in ml
                     or "lite" in ml or "kaleidoscope" in ml)
            if is_4b:
                clip_name = arch.extra.get("clip_name_4b", "qwen_3_4b.safetensors")
            else:
                clip_name = arch.extra.get("clip_name_9b", "qwen_3_8b.safetensors")

            clip_type = getattr(comfy.sd.CLIPType, "FLUX2",
                                comfy.sd.CLIPType.STABLE_DIFFUSION)
            clip_path = folder_paths.get_full_path_or_raise("text_encoders", clip_name)
            print(f"\033[36m[Spellcaster]\033[0m Klein CLIP: {clip_name} "
                  f"(4b={is_4b})")
            return comfy.sd.load_clip(
                ckpt_paths=[clip_path],
                embedding_directory=embeddings,
                clip_type=clip_type,
            )

        elif arch.clip_mode == "single_chroma":
            # Chroma  —  T5-XXL with type="chroma"
            clip_name = arch.extra.get("clip_name", "t5xxl_fp8_e4m3fn.safetensors")
            clip_type = getattr(comfy.sd.CLIPType, "CHROMA",
                                comfy.sd.CLIPType.STABLE_DIFFUSION)
            clip_path = folder_paths.get_full_path_or_raise("text_encoders", clip_name)
            print(f"\033[36m[Spellcaster]\033[0m Chroma CLIP: {clip_name}")
            return comfy.sd.load_clip(
                ckpt_paths=[clip_path],
                embedding_directory=embeddings,
                clip_type=clip_type,
            )

        else:
            # Bundled or unknown — should have been caught by checkpoint path
            raise ValueError(f"Unexpected clip_mode '{arch.clip_mode}' "
                             f"for separate-loader architecture {arch.key}")

    # ── VAE loader ─────────────────────────────────────────────────────
    def _load_vae(self, arch, vae_override):
        if vae_override != "auto":
            vae_name = vae_override
        else:
            vae_name = arch.extra.get("vae_name", "ae.safetensors")

        vae_path = folder_paths.get_full_path_or_raise("vae", vae_name)
        sd, metadata = comfy.utils.load_torch_file(vae_path, return_metadata=True)
        vae = comfy.sd.VAE(sd=sd, metadata=metadata)
        vae.throw_exception_if_invalid()
        print(f"\033[36m[Spellcaster]\033[0m VAE: {vae_name}")
        return vae

    # ── helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _resolve_clip_type(arch):
        """Map arch clip_mode to comfy.sd.CLIPType enum."""
        mapping = {
            "dual":          "FLUX",
            "single_flux2":  "FLUX2",
            "single_chroma": "CHROMA",
        }
        name = mapping.get(arch.clip_mode, "STABLE_DIFFUSION")
        return getattr(comfy.sd.CLIPType, name, comfy.sd.CLIPType.STABLE_DIFFUSION)
