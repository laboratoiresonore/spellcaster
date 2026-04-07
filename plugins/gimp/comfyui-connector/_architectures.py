"""Architecture Registry — centralised model-architecture configuration.

Every architecture-specific behaviour (loader pattern, sampler type, default
parameters, LoRA prefixes, turbo config, quality boost prompts) lives here
in ONE ArchConfig per architecture.

This replaces the scattered dicts: _AUTOSET_PROMPTS, _AUTOSET_CFG,
_AUTOSET_STEPS, _AUTOSET_DENOISE, QUALITY_BOOST_POSITIVE/NEGATIVE,
ARCH_LORA_PREFIXES, TURBO_CONFIGS, and the many inline ``if arch ==`` checks.

Adding a new architecture = adding one entry to ARCHITECTURES.

Usage:
    from _architectures import ARCHITECTURES
    arch = ARCHITECTURES["flux2klein"]
    arch.default_cfg           # 1.0
    arch.supports_negative     # False
    arch.loader                # "unet_clip_vae"
"""


class ArchConfig:
    """Configuration for a single model architecture."""

    __slots__ = (
        "key", "loader", "sampler", "clip_mode", "vae_mode",
        "supports_negative", "default_resolution",
        "default_cfg", "default_steps", "default_denoise",
        "default_sampler", "default_scheduler",
        "lora_prefixes", "turbo_config",
        "quality_positive", "quality_negative",
        "autoset_prompts", "autoset_denoise", "autoset_cn", "autoset_loras",
        "scene_group",
        "extra",
    )

    def __init__(self, key, **kw):
        self.key = key
        self.loader = kw.get("loader", "checkpoint")
        self.sampler = kw.get("sampler", "ksampler")
        self.clip_mode = kw.get("clip_mode", "bundled")
        self.vae_mode = kw.get("vae_mode", "bundled")
        self.supports_negative = kw.get("supports_negative", True)
        self.default_resolution = kw.get("default_resolution", (1024, 1024))
        self.default_cfg = kw.get("default_cfg", 7.0)
        self.default_steps = kw.get("default_steps", 25)
        self.default_denoise = kw.get("default_denoise", 0.60)
        self.default_sampler = kw.get("default_sampler", "euler")
        self.default_scheduler = kw.get("default_scheduler", "normal")
        self.lora_prefixes = kw.get("lora_prefixes", [])
        self.turbo_config = kw.get("turbo_config", None)
        self.quality_positive = kw.get("quality_positive", "")
        self.quality_negative = kw.get("quality_negative", "")
        self.autoset_prompts = kw.get("autoset_prompts", ("", ""))
        self.autoset_denoise = kw.get("autoset_denoise", {})
        self.autoset_cn = kw.get("autoset_cn", {})
        self.autoset_loras = kw.get("autoset_loras", {})
        self.scene_group = kw.get("scene_group", "sdxl")
        self.extra = kw.get("extra", {})

    def get_denoise(self, mode, fallback=0.60):
        """Get recommended denoise for a mode (img2img, inpaint, hallucinate...)."""
        return self.autoset_denoise.get(mode, fallback)

    def get_cn(self, mode):
        """Get recommended ControlNet config for a mode.
        Returns (cn1_key, cn1_strength, cn2_key, cn2_strength) or None.
        """
        return self.autoset_cn.get(mode)

    def get_loras(self, mode):
        """Get recommended LoRAs for a mode.
        Returns list of (lora_name, model_strength, clip_strength) or [].
        """
        return self.autoset_loras.get(mode, [])


# ═══════════════════════════════════════════════════════════════════════════
#  The Registry
# ═══════════════════════════════════════════════════════════════════════════

ARCHITECTURES = {}


def _reg(key, **kw):
    """Register an architecture."""
    ARCHITECTURES[key] = ArchConfig(key, **kw)


# ── SD 1.5 ────────────────────────────────────────────────────────────────

_reg("sd15",
     loader="checkpoint",
     sampler="ksampler",
     clip_mode="bundled",
     vae_mode="bundled",
     supports_negative=True,
     default_resolution=(512, 512),
     default_cfg=7.0,
     default_steps=25,
     default_denoise=0.62,
     default_sampler="dpmpp_2m",
     default_scheduler="karras",
     lora_prefixes=[],
     turbo_config={
         "label": "Hyper-SD15 8-step",
         "lora": "Hyper-SD15-8steps-CFG-lora.safetensors",
         "strength_model": 1.0, "strength_clip": 1.0,
         "sampler": "ddim", "scheduler": "sgm_uniform",
         "steps": 8, "cfg": 5.0, "denoise": None,
     },
     quality_positive=(
         "masterpiece, best quality, highly detailed, photorealistic, sharp focus, "
         "professional photograph, DSLR, 8K UHD, soft natural lighting, film grain"
     ),
     quality_negative=(
         "(worst quality, low quality:1.4), bad anatomy, bad hands, text, error, "
         "missing fingers, extra digit, fewer digits, cropped, jpeg artifacts, "
         "signature, watermark, username, blurry, deformed, disfigured, mutated, "
         "extra limbs, duplicate, morbid, poorly drawn hands, poorly drawn face, "
         "mutation, ugly, disgusting, amateur"
     ),
     autoset_prompts=(
         "photorealistic, highly detailed, sharp focus, professional, 8k",
         "blurry, low quality, deformed, bad anatomy, watermark",
     ),
     autoset_denoise={
         "img2img": 0.60, "inpaint": 0.75, "hallucinate": 0.35,
         "seedv2r": 0.40, "colorize": 0.72, "style": 0.60,
     },
     autoset_cn={
         "img2img":     ("Off", 0.8, "Off", 0.5),
         "inpaint":     ("Off", 0.8, "Off", 0.5),
         "hallucinate": ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Off", 0.5),
         "seedv2r":     ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Off", 0.5),
         "colorize":    (None, None, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.5),
         "style":       ("Depth (spatial) — SD1.5/SDXL/ZIT", 0.6, "Off", 0.5),
     },
     autoset_loras={
         "img2img":     [("SD15\\add_detail.safetensors", 0.5, 0.5)],
         "txt2img":     [("SD15\\add_detail.safetensors", 0.5, 0.5)],
         "hallucinate": [("SD15\\add_detail.safetensors", 0.5, 0.5)],
     },
     scene_group="sd15",
     )


# ── SDXL ──────────────────────────────────────────────────────────────────

_reg("sdxl",
     loader="checkpoint",
     sampler="ksampler",
     clip_mode="bundled",
     vae_mode="bundled",
     supports_negative=True,
     default_resolution=(1024, 1024),
     default_cfg=6.5,
     default_steps=30,
     default_denoise=0.60,
     default_sampler="dpmpp_2m_sde",
     default_scheduler="karras",
     lora_prefixes=["SDXL\\", "Illustrious\\", "Illustrious-Pony\\", "Pony\\"],
     turbo_config={
         "label": "Hyper-SDXL 8-step",
         "lora": "Hyper-SDXL-8steps-CFG-lora.safetensors",
         "strength_model": 1.0, "strength_clip": 1.0,
         "sampler": "ddim", "scheduler": "sgm_uniform",
         "steps": 8, "cfg": 5.0, "denoise": None,
     },
     quality_positive=(
         "masterpiece, best quality, highly detailed, photorealistic, 8K UHD, "
         "DSLR, Fujifilm XT3, sharp focus, professional photograph, natural lighting, film grain"
     ),
     quality_negative=(
         "(worst quality, low quality:1.4), bad anatomy, bad hands, text, error, "
         "missing fingers, extra digit, fewer digits, cropped, jpeg artifacts, "
         "signature, watermark, blurry, deformed, disfigured, mutated, ugly, "
         "extra limbs, duplicate, poorly drawn face, amateur, 3d render, cartoon"
     ),
     autoset_prompts=(
         "photorealistic, ultra detailed, sharp focus, professional photograph, natural lighting, 8k resolution",
         "blurry, low quality, worst quality, deformed, bad anatomy, watermark, text, cartoon",
     ),
     autoset_denoise={
         "img2img": 0.60, "inpaint": 0.75, "hallucinate": 0.35,
         "seedv2r": 0.40, "colorize": 0.72, "style": 0.60, "supir": 0.30,
     },
     autoset_cn={
         "img2img":     ("Off", 0.8, "Off", 0.5),
         "inpaint":     ("Off", 0.8, "Off", 0.5),
         "hallucinate": ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.4),
         "seedv2r":     ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Off", 0.5),
         "colorize":    (None, None, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.5),
         "style":       ("Depth (spatial) — SD1.5/SDXL/ZIT", 0.6, "Off", 0.5),
         "supir":       ("Tile (detail) — SD1.5/SDXL/ZIT", 0.6, "Off", 0.4),
     },
     autoset_loras={
         "img2img":     [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.6, 0.6)],
         "txt2img":     [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.5, 0.5)],
         "inpaint":     [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.3, 0.3)],
         "hallucinate": [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.5, 0.5)],
         "seedv2r":     [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.5, 0.5)],
         "style": [],
         "supir": [],
     },
     scene_group="sdxl",
     )


# ── Illustrious (SDXL-based anime) ───────────────────────────────────────

_reg("illustrious",
     loader="checkpoint",
     sampler="ksampler",
     clip_mode="bundled",
     vae_mode="bundled",
     supports_negative=True,
     default_resolution=(1024, 1024),
     default_cfg=5.5,
     default_steps=28,
     default_denoise=0.58,
     default_sampler="euler_ancestral",
     default_scheduler="normal",
     lora_prefixes=["Illustrious\\", "Illustrious-Pony\\"],
     turbo_config={
         "label": "Hyper-SDXL 8-step",
         "lora": "Hyper-SDXL-8steps-CFG-lora.safetensors",
         "strength_model": 1.0, "strength_clip": 1.0,
         "sampler": "ddim", "scheduler": "sgm_uniform",
         "steps": 8, "cfg": 5.0, "denoise": None,
     },
     quality_positive=(
         "masterpiece, best quality, highly detailed, photorealistic, sharp focus, "
         "professional photograph, 8K UHD, natural lighting"
     ),
     quality_negative=(
         "(worst quality, low quality:1.4), bad anatomy, bad hands, text, "
         "watermark, blurry, deformed, ugly, extra limbs, amateur"
     ),
     autoset_prompts=(
         "masterpiece, best quality, very aesthetic, absurdres, highly detailed",
         "worst quality, low quality, lowres, bad anatomy",
     ),
     autoset_denoise={
         "img2img": 0.55, "inpaint": 0.70, "hallucinate": 0.35,
     },
     autoset_cn={
         "img2img":     ("Off", 0.8, "Off", 0.5),
         "inpaint":     ("Off", 0.8, "Off", 0.5),
         "hallucinate": ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.4),
         "seedv2r":     ("Tile (detail) — SD1.5/SDXL/ZIT", 0.7, "Off", 0.5),
         "colorize":    (None, None, "Depth (spatial) — SD1.5/SDXL/ZIT", 0.5),
         "style":       ("Depth (spatial) — SD1.5/SDXL/ZIT", 0.6, "Off", 0.5),
     },
     autoset_loras={
         "img2img": [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.4, 0.4)],
         "txt2img": [("SDXL\\Detail\\Wonderful_Details_XL_V1a.safetensors", 0.4, 0.4)],
     },
     scene_group="sdxl",
     )


# ── Z-Image-Turbo (fast SDXL distill) ────────────────────────────────────

_reg("zit",
     loader="checkpoint",
     sampler="ksampler",
     clip_mode="bundled",
     vae_mode="bundled",
     supports_negative=True,
     default_resolution=(1024, 1024),
     default_cfg=2.0,
     default_steps=6,
     default_denoise=0.55,
     default_sampler="euler",
     default_scheduler="sgm_uniform",
     lora_prefixes=["Z-Image-Turbo\\"],
     turbo_config=None,  # Already fast at 4-6 steps
     quality_positive=(
         "photorealistic, highly detailed, sharp focus, 8K UHD, professional, natural lighting"
     ),
     quality_negative=(
         "blurry, low quality, bad anatomy, deformed, ugly, watermark, text, amateur"
     ),
     autoset_prompts=(
         "photo, detailed, sharp",
         "blurry, bad",
     ),
     autoset_denoise={
         "img2img": 0.55, "inpaint": 0.70, "hallucinate": 0.30,
     },
     autoset_cn={
         "img2img":     ("ZIT Union (all modes) — ZIT only", 0.7, "Off", 0.5),
         "inpaint":     ("ZIT Union (all modes) — ZIT only", 0.7, "Off", 0.5),
         "hallucinate": ("ZIT Union (all modes) — ZIT only", 0.7, "Off", 0.5),
         "seedv2r":     ("ZIT Union (all modes) — ZIT only", 0.7, "Off", 0.5),
     },
     autoset_loras={
         "img2img": [],
         "txt2img": [],
     },
     scene_group="sdxl",
     )


# ── Flux 1 Dev ────────────────────────────────────────────────────────────

_reg("flux1dev",
     loader="unet_clip_vae",
     sampler="ksampler",
     clip_mode="dual",          # DualCLIPLoader (clip_l + t5xxl)
     vae_mode="separate",       # VAELoader
     supports_negative=False,
     default_resolution=(1024, 1024),
     default_cfg=3.5,
     default_steps=25,
     default_denoise=0.55,
     default_sampler="euler",
     default_scheduler="simple",
     lora_prefixes=["Flux-1-Dev\\"],
     turbo_config={
         "label": "Hyper-FLUX 8-step",
         "lora": "Hyper-FLUX.1-dev-8steps-lora.safetensors",
         "strength_model": 0.125, "strength_clip": 0.125,
         "sampler": "euler", "scheduler": "simple",
         "steps": 8, "cfg": 3.5, "denoise": None,
     },
     quality_positive=(
         "photorealistic, highly detailed, sharp focus, professional photograph, "
         "8K UHD, natural lighting, Fujifilm XT3, film grain, depth of field"
     ),
     quality_negative=(
         "blurry, low quality, bad anatomy, deformed, disfigured, ugly, "
         "watermark, text, signature, extra limbs, missing fingers, amateur, "
         "3d render, cartoon, illustration, painting"
     ),
     autoset_prompts=(
         "A highly detailed professional photograph with natural lighting and sharp focus throughout",
         "",
     ),
     autoset_denoise={
         "img2img": 0.55, "inpaint": 0.70, "hallucinate": 0.35, "style": 0.55,
     },
     autoset_cn={
         "img2img":     ("Flux Union Pro (all-in-one) — Flux only", 0.7, "Off", 0.5),
         "inpaint":     ("Flux Union Pro (all-in-one) — Flux only", 0.6, "Off", 0.5),
         "hallucinate": ("Flux Union Pro (all-in-one) — Flux only", 0.7, "Off", 0.5),
         "seedv2r":     ("Flux Union Pro (all-in-one) — Flux only", 0.7, "Off", 0.5),
         "style":       ("Flux Union Pro (all-in-one) — Flux only", 0.6, "Off", 0.5),
     },
     autoset_loras={
         "img2img": [("Flux\\xlabs_flux_realism_lora_comfyui.safetensors", 0.5, 0.5)],
         "txt2img": [("Flux\\xlabs_flux_realism_lora_comfyui.safetensors", 0.5, 0.5)],
         "inpaint": [],
     },
     scene_group="flux",
     extra={
         "clip_name1": "clip_l.safetensors",
         "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
         "clip_type": "flux",
         "vae_name": "ae.safetensors",
     },
     )


# ── Flux 2 Klein (distilled) ─────────────────────────────────────────────

_reg("flux2klein",
     loader="unet_clip_vae",
     sampler="custom_advanced",  # SamplerCustomAdvanced + CFGGuider
     clip_mode="single_flux2",   # CLIPLoader with type="flux2"
     vae_mode="separate",
     supports_negative=False,
     default_resolution=(1024, 1024),
     default_cfg=1.0,
     default_steps=4,
     default_denoise=0.65,
     default_sampler="euler",
     default_scheduler="simple",
     lora_prefixes=["Flux-2-Klein\\"],
     turbo_config=None,  # Already 4 steps
     quality_positive=(
         "photorealistic, highly detailed, sharp focus, professional photograph, "
         "8K UHD, natural lighting, depth of field"
     ),
     quality_negative=(
         "blurry, low quality, bad anatomy, deformed, disfigured, ugly, "
         "watermark, text, extra limbs, amateur, cartoon"
     ),
     autoset_prompts=(
         "Detailed professional photograph, natural light, sharp, realistic",
         "",
     ),
     autoset_denoise={
         "img2img": 0.55,
     },
     autoset_cn={
         "img2img": ("Flux Union Pro (all-in-one) — Flux only", 0.7, "Off", 0.5),
     },
     autoset_loras={
         "img2img": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
         "txt2img": [("Flux-2-Klein\\K9bSh4rpD3tails.safetensors", 0.5, 0.5)],
     },
     scene_group="flux",
     extra={
         "vae_name": "flux2-vae.safetensors",
         "clip_type": "flux2",
         # CLIP selection is model-dependent: 9B→qwen_3_8b, 4B→qwen_3_4b
         # Handled by load_model_stack() using the preset's "ckpt" field.
     },
     )


# ── Flux Kontext (edit instructions) ─────────────────────────────────────

_reg("flux_kontext",
     loader="unet_clip_vae",
     sampler="ksampler",
     clip_mode="dual",
     vae_mode="separate",
     supports_negative=False,
     default_resolution=(1024, 1024),
     default_cfg=3.5,
     default_steps=25,
     default_denoise=0.55,
     default_sampler="euler",
     default_scheduler="simple",
     lora_prefixes=["Flux-1-Dev\\"],  # Compatible with Dev LoRAs
     turbo_config={
         "label": "Hyper-FLUX 8-step",
         "lora": "Hyper-FLUX.1-dev-8steps-lora.safetensors",
         "strength_model": 0.125, "strength_clip": 0.125,
         "sampler": "euler", "scheduler": "simple",
         "steps": 8, "cfg": 3.5, "denoise": None,
     },
     quality_positive="",
     quality_negative="",
     autoset_prompts=(
         "A highly detailed professional photograph with natural lighting",
         "",
     ),
     autoset_denoise={},
     autoset_cn={},
     autoset_loras={},
     scene_group="flux_kontext",
     extra={
         "clip_name1": "clip_l.safetensors",
         "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
         "clip_type": "flux",
         "vae_name": "ae.safetensors",
     },
     )


# ═══════════════════════════════════════════════════════════════════════════
#  Helper: look up architecture (with fallback)
# ═══════════════════════════════════════════════════════════════════════════

def get_arch(key, fallback="sdxl"):
    """Get an ArchConfig by key, falling back to sdxl if unknown."""
    return ARCHITECTURES.get(key, ARCHITECTURES.get(fallback))
