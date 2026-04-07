"""
Spellcaster Presets — curated parameter combinations for common use cases.

WHAT ARE PRESETS:
  Presets are pre-configured sets of parameters for enhancement nodes.
  Instead of asking users to manually set magnitude, contrast, normalize_strength
  each time, we offer presets like "Gentle", "Strong", "Maximum" that have been
  tested and balanced for real-world use.

HOW THEY'RE USED:
  1. When a user picks an enhancement node, the SpellcasterWizard checks for
     presets via preset_names_for_node()
  2. If presets exist, the wizard offers them as choices before manual config:
       "1. Gentle (subtle boost)
        2. Moderate (noticeable)
        3. Strong (punchy)
        ...
        N+1. Manual (step by step)
        N+2. All defaults"
  3. The LLM sees all presets in the system prompt and can recommend them
  4. Once a preset is chosen, all its parameters are applied at once

STRUCTURE:
  PRESETS: Dict[node_class_key, Dict[preset_name, Dict[param_name, value]]]

  Example:
    PRESETS["Flux2KleinEnhancer"]["Strong"] = {
        "magnitude": 1.35,
        "contrast": 0.30,
        "normalize_strength": 0.15,
        "edit_text_weight": 1.0,
    }

KEY FUNCTIONS:
  - apply_preset(node_key, preset_name) -> Dict: Apply a preset to a session
  - preset_names_for_node(node_key) -> List[str]: List available presets
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# -------------------------------------------------------------------
# Preset definitions
# -------------------------------------------------------------------

PRESETS: Dict[str, Dict[str, Dict[str, Any]]] = {

    # -- Flux2KleinEnhancer presets --
    "Flux2KleinEnhancer": {
        "Gentle (subtle boost)": {
            "magnitude": 1.15,
            "contrast": 0.10,
            "normalize_strength": 0.0,
            "edit_text_weight": 1.0,
        },
        "Moderate (noticeable)": {
            "magnitude": 1.25,
            "contrast": 0.20,
            "normalize_strength": 0.0,
            "edit_text_weight": 1.0,
        },
        "Strong (punchy)": {
            "magnitude": 1.35,
            "contrast": 0.30,
            "normalize_strength": 0.15,
            "edit_text_weight": 1.0,
        },
        "Aggressive": {
            "magnitude": 1.50,
            "contrast": 0.40,
            "normalize_strength": 0.25,
            "edit_text_weight": 1.0,
        },
        "Maximum": {
            "magnitude": 1.75,
            "contrast": 0.60,
            "normalize_strength": 0.35,
            "edit_text_weight": 1.0,
        },
        "Image Edit — Preserve": {
            "magnitude": 0.85,
            "contrast": 0.0,
            "normalize_strength": 0.0,
            "edit_text_weight": 0.70,
        },
        "Image Edit — Subtle": {
            "magnitude": 1.0,
            "contrast": 0.05,
            "normalize_strength": 0.0,
            "edit_text_weight": 0.85,
        },
        "Image Edit — Balanced": {
            "magnitude": 1.10,
            "contrast": 0.10,
            "normalize_strength": 0.10,
            "edit_text_weight": 1.0,
        },
        "Image Edit — Follow Prompt": {
            "magnitude": 1.20,
            "contrast": 0.15,
            "normalize_strength": 0.10,
            "edit_text_weight": 1.25,
        },
        "Image Edit — Force Change": {
            "magnitude": 1.35,
            "contrast": 0.25,
            "normalize_strength": 0.15,
            "edit_text_weight": 1.50,
        },
    },

    # -- Flux2KleinDetailController presets --
    "Flux2KleinDetailController": {
        "Boost front (subject)": {
            "front_mult": 1.5,
            "mid_mult": 1.0,
            "end_mult": 1.0,
        },
        "Boost mid (details)": {
            "front_mult": 1.0,
            "mid_mult": 1.5,
            "end_mult": 1.0,
        },
        "Boost end (style)": {
            "front_mult": 1.0,
            "mid_mult": 1.0,
            "end_mult": 1.5,
        },
        "Subject + style (skip detail)": {
            "front_mult": 1.3,
            "mid_mult": 0.8,
            "end_mult": 1.3,
        },
        "Even uplift": {
            "front_mult": 1.2,
            "mid_mult": 1.2,
            "end_mult": 1.2,
        },
    },

    # -- Flux2KleinRefLatentController presets (v2.0 — attention-patch based) --
    "Flux2KleinRefLatentController": {
        "Lock structure": {
            "strength": 3.0,
            "reference_index": 0,
            "spatial_fade": "none",
        },
        "Strong reference": {
            "strength": 2.0,
            "reference_index": 0,
            "spatial_fade": "none",
        },
        "Normal": {
            "strength": 1.0,
            "reference_index": 0,
            "spatial_fade": "none",
        },
        "Loose reference": {
            "strength": 0.5,
            "reference_index": 0,
            "spatial_fade": "none",
        },
        "Ignore reference": {
            "strength": 0.0,
            "reference_index": 0,
            "spatial_fade": "none",
        },
        "Center focus, edges free": {
            "strength": 1.5,
            "reference_index": 0,
            "spatial_fade": "center_out",
            "spatial_fade_strength": 0.7,
        },
        "Dual ref — slot 1": {
            "strength": 1.0,
            "reference_index": 1,
            "spatial_fade": "none",
        },
    },

    # -- Flux2KleinTextRefBalance presets --
    "Flux2KleinTextRefBalance": {
        "Reference only": {"balance": 0.0},
        "Mostly reference": {"balance": 0.25},
        "Balanced": {"balance": 0.5},
        "Mostly text": {"balance": 0.75},
        "Text only": {"balance": 1.0},
    },

    # -- Flux2KleinRefLatentWeight presets (new in v2.0) --
    "Flux2KleinRefLatentWeight": {
        "Full weight": {
            "reference_index": 0,
            "weight": 1.0,
        },
        "Half weight": {
            "reference_index": 0,
            "weight": 0.5,
        },
        "Double weight": {
            "reference_index": 0,
            "weight": 2.0,
        },
        "Suppress reference": {
            "reference_index": 0,
            "weight": 0.0,
        },
        "Boost ref slot 1": {
            "reference_index": 1,
            "weight": 1.5,
        },
    },

    # -- Flux2KleinMaskRefController presets --
    "Flux2KleinMaskRefController": {
        "Full mask, hard edges": {
            "strength": 1.0,
            "feather": 0,
            "channel_mode": "all",
            "invert_mask": False,
        },
        "Soft edges (feathered)": {
            "strength": 1.0,
            "feather": 8,
            "channel_mode": "all",
            "invert_mask": False,
        },
        "Structure only (low channels)": {
            "strength": 1.0,
            "feather": 0,
            "channel_mode": "low",
            "invert_mask": False,
        },
        "Texture only (high channels)": {
            "strength": 1.0,
            "feather": 0,
            "channel_mode": "high",
            "invert_mask": False,
        },
        "Half strength, soft": {
            "strength": 0.5,
            "feather": 4,
            "channel_mode": "all",
            "invert_mask": False,
        },
    },

    # -- Flux2KleinSectionedEncoder presets --
    "Flux2KleinSectionedEncoder": {
        "Auto-balanced": {
            "mode": "auto_balanced",
        },
        "Manual sections": {
            "mode": "manual",
        },
    },
}


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def preset_names() -> Dict[str, List[str]]:
    """Return {node_class_name: [preset_name, ...]} for all nodes with presets."""
    return {k: list(v.keys()) for k, v in PRESETS.items()}


def preset_names_for_node(node_key: str) -> List[str]:
    """Return preset names available for a given node, or empty list."""
    return list(PRESETS.get(node_key, {}).keys())


def apply_preset(node_key: str, preset_name: str) -> Dict[str, Any]:
    """Return a copy of the preset's param dict, or empty dict if not found."""
    node_presets = PRESETS.get(node_key, {})
    preset = node_presets.get(preset_name)
    if preset is None:
        return {}
    return dict(preset)  # shallow copy
