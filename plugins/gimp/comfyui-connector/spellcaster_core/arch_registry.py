"""Dynamic Architecture Registry — extend Spellcaster with custom model configs.

Drop a JSON file in spellcaster_core/archs/ and your custom model is supported
everywhere: GIMP, Wizard Guild, CLI, ComfyUI nodes.

Usage:
    # Register a custom architecture from JSON
    from spellcaster_core.arch_registry import load_custom_archs
    load_custom_archs()  # Scans archs/ directory

    # Or register programmatically
    from spellcaster_core.arch_registry import register_arch
    register_arch("my_model", {
        "loader": "checkpoint",
        "default_steps": 20,
        "default_cfg": 7.0,
        ...
    })

JSON format (archs/my_model.json):
    {
        "key": "my_model",
        "display_name": "My Custom Model",
        "loader": "checkpoint",
        "sampler_type": "ksampler",
        "clip_mode": "single",
        "supports_negative": true,
        "default_steps": 20,
        "default_cfg": 7.0,
        "default_sampler": "euler",
        "default_scheduler": "normal",
        "default_denoise": 0.65,
        "quality_positive": "masterpiece, best quality",
        "quality_negative": "worst quality, ugly, blurry",
        "lora_prefixes": ["MyModel\\\\"],
        "detect_unet_keywords": ["mymodel"],
        "detect_ckpt_keywords": ["mymodel"]
    }
"""

import json
import os

# Import the core architecture system
try:
    from .architectures import ARCHITECTURES, ArchConfig, _reg
    from .model_detect import UNET_ARCH_RULES, CKPT_ARCH_RULES, LORA_ARCH_PREFIXES
except ImportError:
    from _architectures import ARCHITECTURES, ArchConfig, _reg
    from spellcaster_core.model_detect import UNET_ARCH_RULES, CKPT_ARCH_RULES, LORA_ARCH_PREFIXES

# Directory for custom architecture JSON files
_HERE = os.path.dirname(os.path.abspath(__file__))
ARCHS_DIR = os.path.join(_HERE, "archs")


def register_arch(key, config):
    """Register a new architecture at runtime.

    Args:
        key: Architecture key string (e.g. "my_model")
        config: Dict with ArchConfig fields (see JSON format in module docstring)
    """
    # Build ArchConfig from dict (field names match ArchConfig.__init__ kwargs)
    arch = ArchConfig(
        key=key,
        loader=config.get("loader", "checkpoint"),
        sampler=config.get("sampler", config.get("sampler_type", "ksampler")),
        clip_mode=config.get("clip_mode", "bundled"),
        vae_mode=config.get("vae_mode", "bundled"),
        supports_negative=config.get("supports_negative", True),
        default_steps=config.get("default_steps", 20),
        default_cfg=config.get("default_cfg", 7.0),
        default_sampler=config.get("default_sampler", "euler"),
        default_scheduler=config.get("default_scheduler", "normal"),
        default_denoise=config.get("default_denoise", 0.65),
        turbo_config=config.get("turbo_config"),
        quality_positive=config.get("quality_positive", ""),
        quality_negative=config.get("quality_negative", ""),
        prompt_style=config.get("prompt_style", "tags"),
        prompt_guidance=config.get("prompt_guidance", ""),
        autoset_prompts=tuple(config.get("autoset_prompts", ("", ""))),
        autoset_denoise=config.get("autoset_denoise", {}),
        autoset_cn=config.get("autoset_cn", {}),
        autoset_loras=config.get("autoset_loras", {}),
        scene_group=config.get("scene_group", key),
        lora_prefixes=config.get("lora_prefixes", []),
        extra=config.get("extra", {}),
    )

    # Register in ARCHITECTURES
    ARCHITECTURES[key] = arch

    # Register detection keywords
    for kw in config.get("detect_unet_keywords", []):
        UNET_ARCH_RULES.insert(0, (kw.lower(), key))

    for kw in config.get("detect_ckpt_keywords", []):
        CKPT_ARCH_RULES.insert(0, (kw.lower(), key))

    # Register LoRA prefixes
    if config.get("lora_prefixes"):
        LORA_ARCH_PREFIXES[key] = config["lora_prefixes"]

    return arch


def load_custom_archs(directory=None):
    """Load all .json architecture configs from a directory.

    Scans spellcaster_core/archs/ by default. Each JSON file defines
    one architecture. Files are loaded in alphabetical order.

    Returns: list of (key, config) tuples that were registered.
    """
    search_dir = directory or ARCHS_DIR
    if not os.path.isdir(search_dir):
        return []

    registered = []
    for fname in sorted(os.listdir(search_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(search_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                config = json.load(f)
            key = config.get("key", fname.replace(".json", ""))
            if key in ARCHITECTURES:
                continue  # Don't override built-in architectures
            register_arch(key, config)
            registered.append((key, config))
        except Exception as e:
            print(f"[arch_registry] Failed to load {fname}: {e}")

    if registered:
        print(f"[arch_registry] Loaded {len(registered)} custom architecture(s): "
              f"{', '.join(k for k, _ in registered)}")

    return registered


def export_arch(key, filepath=None):
    """Export a built-in architecture as JSON (for users to use as a template).

    If no filepath given, returns the dict.
    """
    arch = ARCHITECTURES.get(key)
    if not arch:
        raise ValueError(f"Unknown architecture: {key}")

    config = {
        "key": key,
        "display_name": key.replace("_", " ").title(),
        "loader": arch.loader,
        "sampler": arch.sampler,
        "clip_mode": arch.clip_mode,
        "vae_mode": arch.vae_mode,
        "supports_negative": arch.supports_negative,
        "default_steps": arch.default_steps,
        "default_cfg": arch.default_cfg,
        "default_sampler": arch.default_sampler,
        "default_scheduler": arch.default_scheduler,
        "default_denoise": arch.default_denoise,
        "quality_positive": arch.quality_positive,
        "quality_negative": arch.quality_negative,
        "prompt_style": arch.prompt_style,
        "prompt_guidance": arch.prompt_guidance,
        "lora_prefixes": arch.lora_prefixes,
        "scene_group": arch.scene_group,
        "detect_unet_keywords": [],
        "detect_ckpt_keywords": [],
    }

    if filepath:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return filepath
    return config
