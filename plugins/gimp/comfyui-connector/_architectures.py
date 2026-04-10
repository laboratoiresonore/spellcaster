"""Architecture Registry — centralised model-architecture configuration.

Every model architecture supported by Spellcaster has unique properties:
  - How to load the model (checkpoint vs separate unet/clip/vae)
  - What sampler pipeline to use (KSampler vs SamplerCustomAdvanced)
  - Whether negative prompts are supported
  - Default parameters (steps, CFG, denoise, sampler, scheduler)
  - LoRA path prefixes and strength
  - Quality boost prompts
  - Turbo mode configuration (if any)
  - Recommended ControlNet and LoRA combinations per use case

Before this registry, these properties were scattered across:
  _AUTOSET_PROMPTS, _AUTOSET_CFG, _AUTOSET_STEPS, _AUTOSET_DENOISE,
  QUALITY_BOOST_POSITIVE/NEGATIVE, ARCH_LORA_PREFIXES, TURBO_CONFIGS,
  and 50+ inline ``if arch == "sdxl"`` checks.

Now, each architecture is ONE ArchConfig entry that centralises all behaviour.
Adding a new model = adding one registration via _reg().

SUPPORTED ARCHITECTURES (as of April 2026):
  - sd15: Stable Diffusion 1.5 (512x512, checkpoint-based)
  - sdxl: Stable Diffusion XL (1024x1024, checkpoint-based)
  - illustrious: SDXL-based anime model (1024x1024, checkpoint-based)
  - zit: Z-Image-Turbo (fast SDXL distill, 4-6 steps, checkpoint-based)
  - flux1dev: Flux Development (1024x1024, separate loaders, dual CLIP)
  - flux2klein: Flux 2 Klein (distilled, 4 steps, separate loaders, custom sampler)
  - flux_kontext: Flux with edit instructions (experimental, separate loaders)

TYPICAL USAGE:
    from _architectures import ARCHITECTURES, get_arch

    arch = ARCHITECTURES["flux2klein"]
    print(arch.default_cfg)         # 1.0
    print(arch.supports_negative)   # False
    print(arch.loader)              # "unet_clip_vae"

    # Get recommended LoRA for img2img
    loras = arch.get_loras("img2img")

    # Get recommended ControlNet config
    cn_config = arch.get_cn("img2img")

    # Get denoise strength for a use case
    denoise = arch.get_denoise("inpaint", fallback=0.60)
"""


class ArchConfig:
    """Configuration for a single model architecture.

    Each architecture (e.g. "sdxl", "flux2klein") has unique properties that
    affect how workflows are constructed. ArchConfig captures all of them:

    LOADING STRATEGY:
      - loader: How models are loaded (checkpoint vs separate)
      - clip_mode: Text encoder strategy (bundled, single, dual)
      - vae_mode: VAE loading strategy (bundled, separate)

    SAMPLING PARAMETERS:
      - sampler: Scheduler type (ksampler, custom_advanced)
      - default_sampler: Recommended sampler algorithm (euler, dpmpp_2m, etc)
      - default_scheduler: Noise schedule (normal, karras, exponential)
      - default_cfg: Classifier-free guidance scale
      - default_steps: Recommended number of steps
      - default_denoise: Default denoise strength (1.0 = full generation)
      - default_resolution: Recommended output size (width, height)

    ARCHITECTURE SPECIFICS:
      - supports_negative: Whether negative prompts work (False for Flux)
      - lora_prefixes: Expected LoRA folder names for this architecture

    QUALITY & OPTIMIZATION:
      - quality_positive/negative: Boost prompts for enhanced quality
      - turbo_config: Fast mode via Hyper-LoRA (if None, no turbo mode)

    PROMPT STYLE (for LLM scaffolding):
      - prompt_style: How this arch prefers prompts ("booru_tags", "natural",
                      "minimal"). Guides the LLM in how to write/rewrite prompts.
      - prompt_guidance: Expert rules the LLM should follow when crafting prompts
                         for this architecture (multiline string).

    CONTEXT-AWARE CONFIGURATION:
      - autoset_prompts: Default prompts when user hasn't provided text
      - autoset_denoise: Recommended denoise per use case (img2img, inpaint, etc)
      - autoset_cn: Recommended ControlNet per use case (mode → (cn1, str1, cn2, str2))
      - autoset_loras: Recommended LoRA chain per use case
      - scene_group: Scene preset category for UI organization

    EXTENSION POINT:
      - extra: Dict for architecture-specific data (CLIP names, VAE paths, etc)
    """

    __slots__ = (
        "key", "loader", "sampler", "clip_mode", "vae_mode",
        "supports_negative", "default_resolution",
        "default_cfg", "default_steps", "default_denoise",
        "default_sampler", "default_scheduler",
        "lora_prefixes", "turbo_config",
        "quality_positive", "quality_negative",
        "prompt_style", "prompt_guidance",
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
        self.prompt_style = kw.get("prompt_style", "booru_tags")
        self.prompt_guidance = kw.get("prompt_guidance", "")
        self.autoset_prompts = kw.get("autoset_prompts", ("", ""))
        self.autoset_denoise = kw.get("autoset_denoise", {})
        self.autoset_cn = kw.get("autoset_cn", {})
        self.autoset_loras = kw.get("autoset_loras", {})
        self.scene_group = kw.get("scene_group", "sdxl")
        self.extra = kw.get("extra", {})

    def get_denoise(self, mode, fallback=0.60):
        """Get recommended denoise strength for a specific use case.

        Denoise strength controls how much the model relies on the input image
        vs generating from scratch. Values are specific to the architecture and
        use case (img2img, inpaint, etc).

        Args:
            mode: Use case ("img2img", "inpaint", "hallucinate", "colorize", etc)
            fallback: Default if mode not found (default 0.60)

        Returns:
            Float between 0.0 (preserve input) and 1.0 (full generation)
        """
        return self.autoset_denoise.get(mode, fallback)

    def get_cn(self, mode):
        """Get recommended ControlNet configuration for a use case.

        Returns a tuple describing up to two chained ControlNets:
          (cn1_key, cn1_strength, cn2_key, cn2_strength)

        Where each cn_key is either:
          - A ControlNet name string (e.g. "Canny Edge Detection — SDXL")
          - "Off" to disable that slot
          - None to skip initialization

        Args:
            mode: Use case ("img2img", "inpaint", "hallucinate", etc)

        Returns:
            Tuple (cn1, cn1_str, cn2, cn2_str) or None if not configured
        """
        return self.autoset_cn.get(mode)

    def get_loras(self, mode):
        """Get recommended LoRA chain for a use case.

        Returns a list of LoRA configurations to apply in sequence. Each
        element is a dict with: {name, strength_model, strength_clip}.

        Args:
            mode: Use case ("img2img", "txt2img", "inpaint", etc)

        Returns:
            List of dicts [{"name": "...", "strength_model": 0.5, ...}, ...]
            Empty list if no LoRAs recommended.
        """
        return self.autoset_loras.get(mode, [])


# ═══════════════════════════════════════════════════════════════════════════
#  The Registry
# ═══════════════════════════════════════════════════════════════════════════
# This section holds all registered architectures. Each registration via _reg()
# adds one ArchConfig to the ARCHITECTURES dict. Workflow builders query this
# dict to determine how to construct workflows for a specific model.

ARCHITECTURES = {}


def _reg(key, **kw):
    """Register a new architecture in the global ARCHITECTURES registry.

    Called during module load to populate ARCHITECTURES with all supported
    model architectures. Each _reg() call creates one ArchConfig.

    Args:
        key: Architecture identifier string (e.g. "sdxl", "flux2klein")
        **kw: ArchConfig parameters (loader, sampler, quality_positive, etc)
    """
    ARCHITECTURES[key] = ArchConfig(key, **kw)


# ───────────────────────────────────────────────────────────────────────────
#  ARCHITECTURE REGISTRATIONS
# ───────────────────────────────────────────────────────────────────────────
#
# Each _reg() call below defines one model architecture. The key parameter
# (e.g. "sdxl", "flux2klein") is the identifier used throughout Spellcaster
# to look up configuration. All parameters have sensible defaults; override
# only what's different from the defaults.
#
# KEY CONFIGURATIONS BY CATEGORY:
#
#   Checkpoint-based models (single file):
#     - sd15, sdxl, illustrious, zit
#     Loader: "checkpoint" (CheckpointLoaderSimple)
#     Outputs: [0]=MODEL, [1]=CLIP, [2]=VAE from single file
#
#   Separate-loader models (UNET + CLIP + VAE separate):
#     - flux1dev, flux2klein, flux_kontext
#     Loader: "unet_clip_vae"
#     CLIP modes: "dual" (two CLIPs for Flux) or "single_flux2" (one for Klein)
#     Each loaded separately, composed into workflow
#
#   Sampler patterns:
#     - "ksampler": Standard KSampler (most architectures)
#     - "custom_advanced": SamplerCustomAdvanced + CFGGuider (Klein)
#
# ───────────────────────────────────────────────────────────────────────────

# ── SD 1.5 ────────────────────────────────────────────────────────────────
# Stable Diffusion 1.5 — classic 512x512 architecture
# Good for: general purpose, retro/pixel art, fine control with lower VRAM

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
     prompt_style="booru_tags",
     prompt_guidance=(
         "PROMPT FORMAT: Comma-separated tags, most important first.\n"
         "Use weighted emphasis: (important concept:1.3), subtle detail.\n"
         "Quality tags go first: masterpiece, best quality, highly detailed.\n"
         "Subject tags next: 1girl, long hair, blue eyes, standing.\n"
         "Scene/style tags last: outdoors, sunset, cinematic lighting.\n"
         "NEGATIVE prompt is CRITICAL: always include bad anatomy, bad hands, etc.\n"
         "Typical structure: [quality], [subject], [scene], [style], [camera]\n"
         "Keep prompts under 75 tokens (CLIP limit). 40-60 tags is ideal.\n"
         "Parentheses boost weight: (tag:1.0-1.5). Brackets reduce: [tag]."
     ),
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
# Stable Diffusion XL — modern 1024x1024 architecture (2023)
# Good for: photorealism, high detail, Illustrious anime models, best balance

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
     prompt_style="booru_tags",
     prompt_guidance=(
         "PROMPT FORMAT: Comma-separated tags, like SD1.5 but more expressive.\n"
         "Weighted emphasis works: (concept:1.2). SDXL handles longer prompts.\n"
         "Camera metadata helps greatly: shot on Fujifilm XT3, 35mm, f/2.8.\n"
         "Lighting descriptors matter: golden hour, studio lighting, rim light.\n"
         "NEGATIVE prompt is important but less critical than SD1.5.\n"
         "Mix tags with short phrases: cinematic composition, dramatic shadows.\n"
         "Resolution tags: 8K UHD, high resolution, detailed. These help.\n"
         "SDXL handles 150+ tokens well (dual CLIP). Be descriptive."
     ),
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
# Illustrious Anime — SDXL-derived anime/illustration specialisation (2024)
# Good for: anime, manga, illustration, stylised art (better than generic SDXL)

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
     prompt_style="booru_tags",
     prompt_guidance=(
         "PROMPT FORMAT: Booru/Danbooru tag style, comma-separated.\n"
         "Start with character tags: 1girl, solo, long hair, blue eyes.\n"
         "Quality: masterpiece, best quality, highly detailed, absurdres.\n"
         "Style tags: anime coloring, cel shading, illustration, digital art.\n"
         "Emphasize aesthetics: aesthetic, beautiful, vibrant colors.\n"
         "Negative must include: bad anatomy, bad hands, worst quality.\n"
         "Works best with Danbooru-style tags, NOT natural language.\n"
         "Weighted emphasis: (tag:1.2) works. Keep within 0.8-1.5 range."
     ),
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
# Z-Image-Turbo — ultra-fast SDXL distillation (4-6 steps, 2024)
# Good for: speed-critical, real-time generation, RTX 5060 Ti sweet spot

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
     prompt_style="booru_tags",
     prompt_guidance=(
         "PROMPT FORMAT: Same as SDXL (tag-based) but keep it shorter.\n"
         "Turbo model distilled to 4-6 steps; overly complex prompts hurt.\n"
         "Focus on the essential subject + one style descriptor.\n"
         "Low CFG (~2.0): the model is already biased toward quality.\n"
         "Skip camera metadata. Skip quality tags. Just describe the scene.\n"
         "Negative prompt still works but keep it minimal."
     ),
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
# Flux Development — next-gen diffusion by Black Forest Labs (2024)
# Architecture: separate UNET + dual CLIP (clip_l + t5xxl)
# Good for: cutting-edge quality, no negative prompts, 25-30 steps (slower)

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
     prompt_style="natural",
     prompt_guidance=(
         "PROMPT FORMAT: Natural language sentences, NOT comma-separated tags.\n"
         "Write like a description: A photograph of a woman with auburn hair\n"
         "standing in a sunlit meadow, wearing a white dress, wind in her hair.\n"
         "Do NOT use weighted emphasis syntax like (tag:1.2). Flux ignores it.\n"
         "Do NOT use booru tags. Flux was NOT trained on them.\n"
         "NO negative prompt. Flux does not support negative conditioning.\n"
         "Be verbose and descriptive. Longer prompts give better results.\n"
         "Specify camera, lens, film: shot on 35mm film, shallow depth of field.\n"
         "Describe mood and atmosphere: warm golden light, melancholic mood.\n"
         "T5-XXL encoder understands full sentences. Use them."
     ),
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


# ── Chroma (v1/v2) — single CLIPLoader with type="chroma" ───────────────
# Chroma — flow-matching model using T5-XXL with chroma-specific CLIP loading
# Architecture: separate UNET + single CLIP (chroma type) + standard KSampler
# Good for: high quality photorealistic images, CFG-guided generation

_reg("chroma",
     loader="unet_clip_vae",
     sampler="ksampler",
     clip_mode="single_chroma",  # CLIPLoader with type="chroma"
     vae_mode="separate",
     supports_negative=False,
     default_resolution=(1024, 1024),
     default_cfg=3.0,
     default_steps=25,
     default_denoise=0.65,
     default_sampler="euler",
     default_scheduler="simple",
     lora_prefixes=[],
     turbo_config=None,
     prompt_style="natural",
     prompt_guidance=(
         "PROMPT FORMAT: Natural language, like Flux. No tags, no weights.\n"
         "Descriptive sentences work best. No negative prompts supported.\n"
         "Keep it concise. Chroma is a lighter flow-matching model."
     ),
     quality_positive=(
         "photorealistic, highly detailed, sharp focus, professional photograph, "
         "natural lighting, depth of field"
     ),
     quality_negative="",
     autoset_prompts=(
         "Detailed professional photograph, natural light, sharp, realistic",
         "",
     ),
     autoset_denoise={
         "img2img": 0.55,
     },
     autoset_cn={},
     autoset_loras={},
     scene_group="flux",
     extra={
         "vae_name": "ae.safetensors",
         "clip_type": "chroma",
         "clip_name": "t5xxl_fp8_e4m3fn.safetensors",
     },
     )


# ── Flux 2 Klein (distilled) ─────────────────────────────────────────────
# Flux 2 Klein — Flux distilled to 4 steps, custom sampler (2025)
# Architecture: separate UNET + single CLIP (flux2 type) + custom sampler
# Good for: speed (4 steps), quality comparable to Flux1, no negative prompts
# Note: Requires SamplerCustomAdvanced + CFGGuider (not standard KSampler)

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
     prompt_style="natural",
     prompt_guidance=(
         "PROMPT FORMAT: Natural language, like Flux but even simpler.\n"
         "Klein is distilled to 4 steps. Keep prompts clear and direct.\n"
         "No weighted emphasis, no tags, no negative prompt.\n"
         "Good: A photorealistic portrait of an elderly man with kind eyes.\n"
         "Bad: masterpiece, best quality, highly detailed (tag spam hurts).\n"
         "CFG is 1.0. The model already knows what quality means.\n"
         "Focus on WHAT you want, not quality modifiers."
     ),
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
# Flux Kontext — Flux variant with edit instruction support (experimental, 2025)
# Similar to Flux1Dev but with additional guidance mechanism for edits

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
     prompt_style="natural",
     prompt_guidance=(
         "PROMPT FORMAT: Edit instructions in natural language.\n"
         "Describe the edit: Change the hair color to red.\n"
         "Or describe the target: The same scene but during sunset.\n"
         "No quality tags, no weights, no negative prompts."
     ),
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
    """Get an ArchConfig by key, with fallback for unknown architectures.

    This is the standard lookup function used throughout the codebase. If the
    requested key doesn't exist, falls back to a known architecture (default
    "sdxl") to avoid crashes when an unknown architecture is referenced.

    Args:
        key: Architecture identifier (e.g. "sdxl", "flux2klein")
        fallback: Fallback architecture if key not found (default "sdxl")

    Returns:
        ArchConfig instance (guaranteed non-None unless both key and fallback
        don't exist, which would indicate a misconfiguration)

    Example:
        arch = get_arch("flux2klein")  # Returns ARCHITECTURES["flux2klein"]
        if arch.supports_negative:     # Check if arch accepts negative prompts
            # ...
    """
    return ARCHITECTURES.get(key, ARCHITECTURES.get(fallback))
