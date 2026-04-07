"""
Prompt Builder — generates an LLM system prompt from introspected nodes.

The output is a complete system prompt that any 7B+ tool-enabled model
can use to drive the Spellcaster scaffold. It describes every node,
every parameter, every preset, and the exact numbered-menu protocol
the model should follow.

The prompt is deterministic and regenerated fresh each time, so it
always reflects the current state of the Spellcaster node pack.
"""

from __future__ import annotations

from typing import Dict, List

from .introspector import NodeSpec
from .presets import PRESETS, preset_names_for_node


def build_system_prompt(nodes: Dict[str, NodeSpec]) -> str:
    """Build a complete system prompt for driving Spellcaster via chat."""
    sections = [
        _header(),
        _protocol_section(),
        _nodes_section(nodes),
        _presets_section(nodes),
        _commands_section(),
    ]
    return "\n\n".join(sections)


def build_tool_description(nodes: Dict[str, NodeSpec]) -> str:
    """Build a shorter tool description for Open WebUI / Kobold tool registration."""
    node_list = ", ".join(n.display_name for n in nodes.values())
    return (
        f"Spellcaster conditioning enhancement for FLUX.2 Klein. "
        f"Available nodes: {node_list}. "
        f"Send numbered choices to configure and run enhancement nodes. "
        f"Type 'menu' to see options."
    )


# -------------------------------------------------------------------
# Section builders
# -------------------------------------------------------------------

def _header() -> str:
    return (
        "You are a Spellcaster assistant — you help users configure and run "
        "FLUX.2 Klein conditioning enhancement nodes via a simple numbered-menu "
        "interface.\n\n"
        "RULES:\n"
        "- Always present numbered choices. Never ask open-ended questions.\n"
        "- When the user picks a number, advance to the next step.\n"
        "- For parameters with defaults, always show the default and let "
        "the user press 'd' or Enter to accept it.\n"
        "- If the user types 'defaults' at any param step, fill all remaining "
        "params with defaults and go to confirmation.\n"
        "- Never invent parameter values. Only use values the user explicitly chose "
        "or the documented defaults.\n"
        "- Keep replies short. No essays. Just the next menu or confirmation."
    )


def _protocol_section() -> str:
    return (
        "PROTOCOL\n"
        "========\n\n"
        "1. Show the main menu (list of available nodes).\n"
        "2. User picks a node by number.\n"
        "3. If presets exist, offer: preset list + 'Manual' + 'All defaults'.\n"
        "4. If manual: walk through each user-configurable parameter one at a time.\n"
        "   - Show the parameter name, type, range, default, and tooltip.\n"
        "   - For choice params, show numbered options.\n"
        "   - Accept 'd' or empty input as 'use default'.\n"
        "5. After all params collected (or preset chosen), show confirmation:\n"
        "   - List all settings.\n"
        "   - Offer: 1=Confirm, 2=Change a parameter, 3=Start over.\n"
        "6. On confirm, output the final parameter JSON and signal ready to execute.\n\n"
        "GLOBAL COMMANDS (user can type these at any time):\n"
        "  menu / start  — Return to main menu\n"
        "  cancel         — Cancel and reset\n"
        "  help           — Show help\n"
        "  defaults / d   — Accept remaining defaults\n"
        "  skip           — Skip optional parameter"
    )


def _nodes_section(nodes: Dict[str, NodeSpec]) -> str:
    lines = ["AVAILABLE NODES", "=" * 40, ""]

    for i, (key, node) in enumerate(nodes.items(), 1):
        lines.append(f"NODE {i}: {node.display_name} ({key})")
        if node.description:
            lines.append(f"  {node.description}")
        lines.append("")

        user_params = node.all_user_params
        if not user_params:
            lines.append("  No user-configurable parameters.")
            lines.append("")
            continue

        lines.append("  Parameters:")
        for p in user_params:
            req = "required" if p.required else "optional"
            if p.choices:
                choices_str = ", ".join(p.choices)
                lines.append(
                    f"    - {p.name} ({req}): choose from [{choices_str}], "
                    f"default={p.default}"
                )
            elif p.type == "BOOLEAN":
                lines.append(
                    f"    - {p.name} ({req}): yes/no, default={'yes' if p.default else 'no'}"
                )
            elif p.type == "STRING":
                lines.append(f"    - {p.name} ({req}): text input")
            else:
                rng = ""
                if p.min is not None:
                    rng = f" range {p.min}–{p.max}"
                    if p.step:
                        rng += f" step {p.step}"
                lines.append(
                    f"    - {p.name} ({req}): {p.type.lower()}, "
                    f"default={p.default}{rng}"
                )
            if p.tooltip:
                lines.append(f"      {p.tooltip}")
        lines.append("")

    return "\n".join(lines)


def _presets_section(nodes: Dict[str, NodeSpec]) -> str:
    lines = ["PRESETS", "=" * 40, ""]

    for key in nodes:
        presets = preset_names_for_node(key)
        if not presets:
            continue
        node_presets = PRESETS.get(key, {})
        lines.append(f"{nodes[key].display_name}:")
        for name in presets:
            vals = node_presets[name]
            summary = ", ".join(f"{k}={v}" for k, v in vals.items())
            lines.append(f"  - {name}: {summary}")
        lines.append("")

    if len(lines) == 3:
        return ""  # no presets at all

    return "\n".join(lines)


def _commands_section() -> str:
    return (
        "OUTPUT FORMAT\n"
        "=============\n\n"
        "When the user confirms, output the settings as a JSON block:\n\n"
        "```json\n"
        "{\n"
        '  "node": "Flux2KleinEnhancer",\n'
        '  "params": {\n'
        '    "magnitude": 1.25,\n'
        '    "contrast": 0.20\n'
        "  }\n"
        "}\n"
        "```\n\n"
        "The scaffold runtime will pick this up and execute it against ComfyUI."
    )
