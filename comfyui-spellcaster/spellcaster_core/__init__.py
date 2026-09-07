"""spellcaster_core — Canonical model architecture & workflow node registry.

This is the ONE SOURCE OF TRUTH for:
  1. Model architectures (ARCHITECTURES dict, ArchConfig class)
  2. Model name → architecture detection (classify_unet_model, classify_ckpt_model)
  3. ComfyUI node construction (NodeFactory class)
  4. Workflow composition patterns (load_model_stack, inject_lora_chain, etc)

All parts of Spellcaster (GIMP plugin, Wizard Guild, ComfyUI nodes) import from
this package. When you fix a bug or add a new architecture, fix it ONCE here
and all 39+ workflow builders are automatically updated.

USAGE:
    from . import (
        ARCHITECTURES, ArchConfig, get_arch,
        classify_unet_model, classify_ckpt_model,
        NodeFactory,
    )

    arch = get_arch("sdxl")
    model_loader = NodeFactory()
    ckpt_id = model_loader.checkpoint_loader("model.safetensors")
"""

from .architectures import ARCHITECTURES, ArchConfig, get_arch
from .model_detect import classify_unet_model, classify_ckpt_model
from .node_factory import NodeFactory

# Load custom architectures from archs/ directory at import time
try:
    from .arch_registry import load_custom_archs
    load_custom_archs()
except Exception:
    pass  # never block import over missing custom archs

__all__ = [
    "ARCHITECTURES",
    "ArchConfig",
    "get_arch",
    "classify_unet_model",
    "classify_ckpt_model",
    "NodeFactory",
]
