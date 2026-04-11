"""SpellcasterSampler — Architecture-aware sampler with auto-configuration.

Automatically selects KSampler vs SamplerCustomAdvanced based on architecture.
All parameters are auto-populated from ArchConfig defaults, with optional overrides.
"""

import os
import sys

# Add parent to path for spellcaster_core imports
_pack_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pack_dir not in sys.path:
    sys.path.insert(0, _pack_dir)

try:
    import comfy.sample
    import comfy.samplers
except ImportError:
    comfy = None

try:
    from spellcaster_core.architectures import get_arch
except ImportError as e:
    print(f"[SpellcasterSampler] WARNING: Failed to import spellcaster_core: {e}")
    get_arch = None


class SpellcasterSampler:
    """Architecture-aware sampler — auto-selects KSampler vs SamplerCustomAdvanced.

    For most architectures (sd15, sdxl, flux1dev): uses standard KSampler.
    For flux2klein: uses SamplerCustomAdvanced + CFGGuider pipeline.
    All parameters auto-populated from ArchConfig defaults.

    Returns:
      - samples: Latent tensor ready for VAE decoding
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "latent_image": ("LATENT",),
                "arch_key": ("STRING", {"default": "sdxl"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            },
            "optional": {
                "steps_override": ("INT", {"default": 0, "min": 0, "max": 200,
                                          "tooltip": "0 = use arch default"}),
                "cfg_override": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100.0,
                                          "step": 0.1, "tooltip": "0 = use arch default"}),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "sampler_override": ("STRING", {"default": "", "tooltip": "Override sampler name"}),
                "scheduler_override": ("STRING", {"default": "", "tooltip": "Override scheduler"}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("samples",)
    FUNCTION = "sample"
    CATEGORY = "Spellcaster"
    DESCRIPTION = "Architecture-aware sampler with auto-configured parameters."

    def sample(self, model, positive, negative, latent_image, arch_key, seed,
               steps_override=0, cfg_override=0.0, denoise=1.0,
               sampler_override="", scheduler_override=""):
        """Sample with architecture-aware defaults.

        Args:
            model: Diffusion model (MODEL)
            positive: Positive conditioning (CONDITIONING)
            negative: Negative conditioning (CONDITIONING)
            latent_image: Starting latent (LATENT) - may be empty for txt2img
            arch_key: Architecture identifier (e.g., "sdxl", "flux2klein")
            seed: Random seed (int)
            steps_override: Override steps (0 = use arch default)
            cfg_override: Override CFG scale (0.0 = use arch default)
            denoise: Denoise strength (1.0 = full generation, 0.0 = preserve input)
            sampler_override: Override sampler algorithm
            scheduler_override: Override noise scheduler

        Returns:
            Tuple (sampled_latent,)
        """
        if not comfy:
            raise RuntimeError("[SpellcasterSampler] ComfyUI comfy module not available")
        if not get_arch:
            raise RuntimeError("[SpellcasterSampler] spellcaster_core not available")

        arch = get_arch(arch_key)
        if not arch:
            raise ValueError(f"[SpellcasterSampler] Unknown architecture: {arch_key}")

        # Get parameters from architecture defaults, with overrides
        steps = steps_override if steps_override > 0 else arch.default_steps
        cfg = cfg_override if cfg_override > 0.0 else arch.default_cfg
        sampler_name = sampler_override or arch.default_sampler
        scheduler = scheduler_override or arch.default_scheduler

        print(f"[SpellcasterSampler] {arch_key}: steps={steps}, cfg={cfg}, "
              f"sampler={sampler_name}, scheduler={scheduler}, denoise={denoise}")

        # Route to appropriate sampler based on architecture
        if arch.sampler == "custom_advanced":
            # Flux2 Klein: use SamplerCustomAdvanced + CFGGuider
            print(f"[SpellcasterSampler] Using custom_advanced pipeline for {arch_key}")
            samples = self._sample_custom_advanced(
                model, positive, negative, latent_image,
                seed, steps, cfg, sampler_name, scheduler, denoise
            )
        else:
            # Standard KSampler path (sd15, sdxl, flux1dev, etc)
            print(f"[SpellcasterSampler] Using KSampler for {arch_key}")
            samples = self._sample_standard(
                model, positive, negative, latent_image,
                seed, steps, cfg, sampler_name, scheduler, denoise
            )

        return (samples,)

    def _sample_standard(self, model, positive, negative, latent_image,
                         seed, steps, cfg, sampler_name, scheduler, denoise):
        """Standard KSampler path for most architectures."""
        try:
            # Use comfy.sample.sample() if available (preferred)
            if hasattr(comfy.sample, 'sample'):
                samples = comfy.sample.sample(
                    model,
                    seed,
                    steps,
                    cfg,
                    sampler_name,
                    scheduler,
                    positive,
                    negative,
                    latent_image,
                    denoise=denoise,
                )
                return samples
            else:
                # Fallback: use KSampler node logic directly
                raise RuntimeError("comfy.sample.sample not available")

        except Exception as e:
            print(f"[SpellcasterSampler] KSampler failed: {e}")
            raise RuntimeError(f"Sampling failed: {e}")

    def _sample_custom_advanced(self, model, positive, negative, latent_image,
                                seed, steps, cfg, sampler_name, scheduler, denoise):
        """Flux2 Klein sampling pipeline (SamplerCustomAdvanced + CFGGuider)."""
        try:
            # Klein pipeline requires special handling:
            # 1. CFGGuider wraps model + conditioning
            # 2. SamplerCustomAdvanced orchestrates the sampling

            # Create CFGGuider
            if not hasattr(comfy.samplers, 'CFGGuider'):
                raise RuntimeError("CFGGuider not available in comfy.samplers")

            guider = comfy.samplers.CFGGuider(model)
            guider.set_conds(positive, negative)
            guider.set_cfg(cfg)

            # Create sampler
            sampler_obj = comfy.samplers.sampler_object(sampler_name)

            # Get sigmas from scheduler
            if hasattr(comfy.samplers, 'Flux2Scheduler'):
                # Get latent dimensions for Flux2Scheduler
                batch_size = latent_image.get("samples", None).shape[0] if isinstance(latent_image, dict) else 1
                height = latent_image.get("samples", None).shape[2] * 8 if isinstance(latent_image, dict) else 1024
                width = latent_image.get("samples", None).shape[3] * 8 if isinstance(latent_image, dict) else 1024

                sigmas = comfy.samplers.Flux2Scheduler(steps, height, width)
            else:
                # Fallback: use standard scheduler
                sigmas = comfy.samplers.calculate_sigmas(sampler_obj, steps, scheduler)

            # Prepare noise
            noise = self._prepare_noise(seed, latent_image)

            # Sample using SamplerCustomAdvanced
            if hasattr(comfy.samplers, 'SamplerCustomAdvanced'):
                samples = comfy.samplers.SamplerCustomAdvanced().sample(
                    noise, guider, sampler_obj, sigmas, latent_image, steps
                )
                return samples
            else:
                # Fallback: use basic sampling flow
                samples = comfy.sample.sample(
                    model, seed, steps, cfg, sampler_name, scheduler,
                    positive, negative, latent_image, denoise=denoise
                )
                return samples

        except Exception as e:
            print(f"[SpellcasterSampler] custom_advanced failed: {e}")
            # Fallback to standard sampling
            print(f"[SpellcasterSampler] Falling back to standard KSampler")
            return self._sample_standard(
                model, positive, negative, latent_image,
                seed, steps, cfg, "euler", scheduler, denoise
            )

    def _prepare_noise(self, seed, latent_image):
        """Prepare noise for sampling."""
        try:
            if hasattr(comfy, 'utils') and hasattr(comfy.utils, 'RandomNoise'):
                return comfy.utils.RandomNoise(seed).sample()
            else:
                # Fallback: create noise directly
                import torch
                torch.manual_seed(seed)
                if isinstance(latent_image, dict) and "samples" in latent_image:
                    shape = latent_image["samples"].shape
                else:
                    shape = (1, 4, 128, 128)  # Default Flux2 shape
                return torch.randn(shape)
        except Exception as e:
            print(f"[SpellcasterSampler] Noise preparation failed: {e}")
            raise


# Node registry (for ComfyUI)
NODE_CLASS_MAPPINGS = {
    "SpellcasterSampler": SpellcasterSampler,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SpellcasterSampler": "Spellcaster Sampler (Auto-Config)",
}
