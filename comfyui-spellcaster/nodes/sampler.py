"""SpellcasterSampler — Architecture-aware sampler with auto-configuration.

Automatically selects KSampler vs SamplerCustomAdvanced+CFGGuider based on
architecture.  All parameters auto-populated from ArchConfig defaults.

Uses the exact same comfy.sample / comfy.samplers APIs as ComfyUI builtins.
"""

import os
import sys
import torch

import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview

# ── spellcaster_core import ────────────────────────────────────────────
_pack_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pack_dir not in sys.path:
    sys.path.insert(0, _pack_dir)

from spellcaster_core.architectures import get_arch


class SpellcasterSampler:
    """Architecture-aware sampler — one node for every model type."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "latent_image": ("LATENT",),
                "arch_key": ("STRING", {"default": "sdxl"}),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 0xffffffffffffffff,
                    "control_after_generate": True,
                }),
            },
            "optional": {
                "steps_override": ("INT", {
                    "default": 0, "min": 0, "max": 10000,
                    "tooltip": "0 = use architecture default",
                }),
                "cfg_override": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 100.0,
                    "step": 0.1, "round": 0.01,
                    "tooltip": "0 = use architecture default",
                }),
                "denoise": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                }),
                "sampler_override": (
                    ["auto"] + comfy.samplers.KSampler.SAMPLERS,
                    {"default": "auto"},
                ),
                "scheduler_override": (
                    ["auto"] + comfy.samplers.KSampler.SCHEDULERS,
                    {"default": "auto"},
                ),
            },
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("samples",)
    OUTPUT_TOOLTIPS = ("The denoised latent.",)
    FUNCTION = "sample"
    CATEGORY = "Spellcaster"
    DESCRIPTION = (
        "Architecture-aware sampler with auto-configured parameters. "
        "Standard KSampler for most models, SamplerCustomAdvanced for Klein."
    )
    SEARCH_ALIASES = ["spellcaster sampler", "auto sampler", "smart sampler"]

    def sample(self, model, positive, negative, latent_image, arch_key, seed,
               steps_override=0, cfg_override=0.0, denoise=1.0,
               sampler_override="auto", scheduler_override="auto"):

        arch = get_arch(arch_key)

        # Resolve final parameters
        steps     = steps_override     if steps_override > 0    else arch.default_steps
        cfg       = cfg_override       if cfg_override   > 0.0  else arch.default_cfg
        sampler   = sampler_override   if sampler_override   != "auto" else arch.default_sampler
        scheduler = scheduler_override if scheduler_override != "auto" else arch.default_scheduler

        print(f"\033[36m[Spellcaster]\033[0m Sampling {arch_key}: "
              f"steps={steps}, cfg={cfg}, sampler={sampler}, "
              f"scheduler={scheduler}, denoise={denoise}")

        if arch.sampler == "custom_advanced":
            return self._sample_custom_advanced(
                model, positive, negative, latent_image,
                seed, steps, cfg, sampler, denoise,
            )

        # Standard KSampler  (identical to ComfyUI's common_ksampler)
        return self._sample_ksampler(
            model, positive, negative, latent_image,
            seed, steps, cfg, sampler, scheduler, denoise,
        )

    # ── standard path (copy of common_ksampler) ───────────────────────
    @staticmethod
    def _sample_ksampler(model, positive, negative, latent,
                         seed, steps, cfg, sampler_name, scheduler, denoise):
        latent_image = latent["samples"]
        latent_image = comfy.sample.fix_empty_latent_channels(
            model, latent_image,
            latent.get("downscale_ratio_spacial", None),
        )

        batch_inds = latent.get("batch_index", None)
        noise = comfy.sample.prepare_noise(latent_image, seed, batch_inds)

        noise_mask = latent.get("noise_mask", None)
        callback   = latent_preview.prepare_callback(model, steps)
        disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED

        samples = comfy.sample.sample(
            model, noise, steps, cfg, sampler_name, scheduler,
            positive, negative, latent_image,
            denoise=denoise,
            noise_mask=noise_mask,
            callback=callback,
            disable_pbar=disable_pbar,
            seed=seed,
        )

        out = latent.copy()
        out.pop("downscale_ratio_spacial", None)
        out["samples"] = samples
        return (out,)

    # ── Klein path (CFGGuider + SamplerCustomAdvanced) ─────────────────
    @staticmethod
    def _sample_custom_advanced(model, positive, negative, latent,
                                seed, steps, cfg, sampler_name, denoise):
        """Flux 2 Klein pipeline: CFGGuider → SamplerCustomAdvanced."""

        # Build guider
        guider = comfy.samplers.CFGGuider(model)
        guider.set_conds(positive, negative)
        guider.set_cfg(cfg)

        # Build sampler object
        sampler_obj = comfy.samplers.sampler_object(sampler_name)

        # Build sigmas  ─  use the model's built-in sigma calculator
        sigmas = comfy.samplers.calculate_sigmas(
            model.get_model_object("model_sampling"),
            "simple", steps,
        ).cpu()

        # Truncate sigmas for denoise < 1.0
        if denoise < 1.0:
            total = len(sigmas) - 1
            start = max(0, total - int(total * denoise))
            sigmas = sigmas[start:]

        # Prepare latent
        latent_image = latent["samples"]
        latent_image = comfy.sample.fix_empty_latent_channels(
            guider.model_patcher, latent_image,
            latent.get("downscale_ratio_spacial", None),
        )
        latent_copy = latent.copy()
        latent_copy["samples"] = latent_image

        # Prepare noise
        from comfy_extras.nodes_custom_sampler import Noise_RandomNoise
        noise_gen = Noise_RandomNoise(seed)

        noise_mask = latent.get("noise_mask", None)
        callback   = latent_preview.prepare_callback(
            guider.model_patcher, sigmas.shape[-1] - 1,
        )
        disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED

        # Sample
        samples = guider.sample(
            noise_gen.generate_noise(latent_copy),
            latent_image,
            sampler_obj,
            sigmas,
            denoise_mask=noise_mask,
            callback=callback,
            disable_pbar=disable_pbar,
            seed=noise_gen.seed,
        )
        samples = samples.to(comfy.model_management.intermediate_device())

        out = latent.copy()
        out.pop("downscale_ratio_spacial", None)
        out["samples"] = samples
        return (out,)
