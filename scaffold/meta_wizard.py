"""Intent catalogue and meta system-prompt builder.

Once upon a time this module hosted a `MetaWizard` router that delegated
chat to sub-wizards. That router and its sub-wizards were never wired
into the running Guild; the server calls `build_meta_system_prompt`
directly. This file is now just the two live pieces — `INTENTS` (used
by build_meta_system_prompt) and the prompt builder itself.

The per-wizard prompts with state-aware phase handling live in
`scaffold/spellcaster_wizard.py` (build_system_prompt). This generic
one is the fallback for workflow-catalogue characters that don't have
their own scaffold.
"""

from __future__ import annotations

from typing import Dict

from .introspector import NodeSpec


# ── Intent categories ─────────────────────────────────────────────────

INTENTS = [
    {
        "key": "enhance",
        "label": "Enhance an existing image",
        "description": "Boost detail, contrast, color grading, sharpening",
        "route": "spellcaster",
        "suggested_nodes": [
            "Flux2KleinEnhancer",
            "Flux2KleinDetailController",
        ],
    },
    {
        "key": "reference",
        "label": "Use a reference image to guide generation",
        "description": "Structure transfer, pose matching, style from reference",
        "route": "spellcaster",
        "suggested_nodes": [
            "Flux2KleinRefLatentController",
            "Flux2KleinTextRefBalance",
            "Flux2KleinRefLatentWeight",
        ],
    },
    {
        "key": "inpaint",
        "label": "Edit part of an image (inpaint / masked edit)",
        "description": "Change specific regions while keeping the rest",
        "route": "spellcaster",
        "suggested_nodes": [
            "Flux2KleinMaskRefController",
        ],
    },
    {
        "key": "txt2img",
        "label": "Generate a new image from text",
        "description": "Create an image from a prompt (no source image)",
        "route": "workflow",
        "workflow_hints": ["txt2img", "text to image", "flux"],
    },
    {
        "key": "img2img",
        "label": "Transform an image based on a prompt",
        "description": "Change style, subject, or mood of an existing image",
        "route": "workflow",
        "workflow_hints": ["img2img", "image to image"],
    },
    {
        "key": "video",
        "label": "Generate or edit video",
        "description": "Create videos from text or images, animate stills",
        "route": "workflow",
        "workflow_hints": ["video", "ltx", "wan", "ani"],
    },
    {
        "key": "browse",
        "label": "Browse all available workflows",
        "description": "See everything on your ComfyUI server",
        "route": "workflow",
        "workflow_hints": [],
    },
]


def build_meta_system_prompt(nodes: Dict[str, NodeSpec]) -> str:
    """Build a system prompt that covers the full meta wizard experience."""
    intent_block = "\n".join(
        f"  {i}. {intent['label']} — {intent['description']}"
        for i, intent in enumerate(INTENTS, 1)
    )

    node_block = ""
    if nodes:
        node_lines = []
        for key, node in nodes.items():
            params = node.all_user_params
            param_str = ", ".join(
                f"{p.name} ({p.type.lower()}, default={p.default})"
                for p in params[:5]
            )
            node_lines.append(f"  - {node.display_name} ({key}): {param_str}")
        node_block = "\n".join(node_lines)
    else:
        node_block = "  (Nodes discovered at runtime from ComfyUI)"

    return f"""You are Spellcaster, an AI assistant for FLUX.2 Klein image generation and enhancement via ComfyUI.

RULES:
- Always present numbered choices. Never ask open-ended questions.
- When the user picks a number, advance to the next step.
- For parameters with defaults, show the default and let the user type 'd' to accept.
- If the user types 'defaults', fill all remaining params with defaults and go to confirmation.
- Keep replies short. No essays. Just the next menu or confirmation.
- Never invent parameter values. Only use documented defaults or user choices.

MAIN MENU — what the user can do:
{intent_block}

When the user picks an intent:
- For enhancement (intents 1-3): show the relevant Spellcaster nodes
- For generation/modification (intents 4-6): route to the workflow library
- For browsing (intent 7): show the full workflow catalog

SPELLCASTER ENHANCEMENT NODES:
{node_block}

PRESETS:
Many nodes have presets — curated parameter combinations for common use cases.
When a user picks a node with presets, offer:
  1-N. [preset names]
  N+1. Manual (step by step)
  N+2. All defaults

PROTOCOL:
1. Show the main menu (intents)
2. User picks an intent by number or description
3. Show relevant nodes or workflow options
4. Guide through parameter configuration
5. Show confirmation with all settings
6. On confirm, output the final JSON
7. Offer to chain another node or finish

CHAINING:
After configuring one node, offer:
  1. Add another enhancement node
  2. Done — execute all
  3. Start over

OUTPUT FORMAT:
When confirmed, output JSON wrapped in code blocks:
```json
{{"node": "NodeClassName", "params": {{"key": value}}}}
```
(Skip conversation if a prompt was provided.)

GLOBAL COMMANDS:
  menu / home — Main menu
  cancel      — Cancel and reset
  help        — Show help
  defaults    — Accept remaining defaults
  workflows   — Browse ComfyUI workflow library"""
