"""
Spellcaster Wizard — deterministic state machine that walks any user
through node parameter collection one step at a time.

Every decision is a numbered choice or a simple typed value.
Designed so a 7B model can drive it — no ambiguity, no open-ended parsing.

State machine per user:
    idle -> node_pick -> param_N -> ... -> confirm -> done
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .introspector import NodeSpec, ParamSpec, discover_nodes
from .presets import PRESETS, apply_preset, preset_names_for_node


@dataclass
class WizardSession:
    """Tracks one user's progress through a node configuration."""
    user_id: str
    step: str = "idle"                      # current state
    node_key: Optional[str] = None          # selected node class_name
    params: Dict[str, Any] = field(default_factory=dict)
    param_queue: List[ParamSpec] = field(default_factory=list)
    current_param_idx: int = 0
    skip_optional: bool = False

    def is_complete(self) -> bool:
        return self.step == "done"

    def reset(self):
        self.step = "idle"
        self.node_key = None
        self.params.clear()
        self.param_queue.clear()
        self.current_param_idx = 0
        self.skip_optional = False

    def to_workflow(self) -> dict:
        """Return the collected parameters as a workflow-ready dict."""
        return {
            "node": self.node_key,
            "params": dict(self.params),
        }


class SpellcasterWizard:
    """
    Manages wizard sessions for multiple users.

    Call handle(user_id, text) with each incoming message.
    Returns the next message to send back.
    """

    def __init__(self, nodes: Optional[Dict[str, NodeSpec]] = None):
        self.nodes: Dict[str, NodeSpec] = nodes or discover_nodes()
        self._sessions: Dict[str, WizardSession] = {}
        # Ordered list for menu indexing
        self._node_keys: List[str] = list(self.nodes.keys())

    def get_session(self, user_id: str) -> Optional[WizardSession]:
        return self._sessions.get(user_id)

    def handle(self, user_id: str, text: str) -> str:
        """Process one message, return reply."""
        text = text.strip()
        s = self._sessions.get(user_id)

        # Global commands
        low = text.lower()
        if low in ("cancel", "quit", "exit", "stop", "menu", "start"):
            if s:
                s.reset()
            return self._main_menu()

        if low == "help":
            return self._help_text()

        if s is None or s.step == "idle":
            s = WizardSession(user_id=user_id, step="node_pick")
            self._sessions[user_id] = s
            if low in ("", "hi", "hello", "hey"):
                return self._main_menu()
            # Try to interpret as a pick from the main menu
            return self._handle_node_pick(s, text)

        handler = getattr(self, f"_handle_{s.step}", None)
        if handler:
            return handler(s, text)

        s.reset()
        return self._main_menu()

    # ------------------------------------------------------------------
    # Main menu
    # ------------------------------------------------------------------

    def _main_menu(self) -> str:
        lines = [
            "Spellcaster Enhancement Nodes",
            "=" * 35,
            "",
            "Pick a node to configure:",
            "",
        ]
        for i, key in enumerate(self._node_keys, 1):
            node = self.nodes[key]
            lines.append(f"{i}. {node.display_name}")
            if node.description:
                lines.append(f"   {node.description}")
        lines.append("")
        lines.append("Reply with the number, or type 'help'.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Step: node_pick
    # ------------------------------------------------------------------

    def _handle_node_pick(self, s: WizardSession, text: str) -> str:
        # Try numeric pick
        try:
            idx = int(text) - 1
            if 0 <= idx < len(self._node_keys):
                return self._select_node(s, self._node_keys[idx])
        except ValueError:
            pass

        # Try name match
        low = text.lower()
        for key in self._node_keys:
            node = self.nodes[key]
            if low in node.display_name.lower() or low in key.lower():
                return self._select_node(s, key)

        return f"Didn't recognise '{text}'. Reply with a number (1-{len(self._node_keys)})."

    def _select_node(self, s: WizardSession, key: str) -> str:
        s.node_key = key
        node = self.nodes[key]
        user_params = node.all_user_params

        # Check for presets
        presets = preset_names_for_node(key)
        if presets:
            s.step = "preset_or_custom"
            lines = [
                f"Selected: {node.display_name}",
                "",
                "Use a preset or configure manually?",
                "",
            ]
            for i, name in enumerate(presets, 1):
                lines.append(f"{i}. {name}")
            lines.append(f"{len(presets) + 1}. Manual (step by step)")
            lines.append(f"{len(presets) + 2}. All defaults")
            lines.append("")
            lines.append("Reply with the number.")
            return "\n".join(lines)

        if not user_params:
            # No configurable params — go straight to confirm
            s.step = "confirm"
            return self._confirm_message(s)

        return self._start_param_walk(s, user_params)

    # ------------------------------------------------------------------
    # Step: preset_or_custom
    # ------------------------------------------------------------------

    def _handle_preset_or_custom(self, s: WizardSession, text: str) -> str:
        presets = preset_names_for_node(s.node_key)
        try:
            idx = int(text) - 1
        except ValueError:
            idx = -1

        if 0 <= idx < len(presets):
            # Apply preset
            preset_name = presets[idx]
            s.params = apply_preset(s.node_key, preset_name)
            s.step = "confirm"
            return self._confirm_message(s, f"Preset: {preset_name}")

        if idx == len(presets):
            # Manual
            node = self.nodes[s.node_key]
            return self._start_param_walk(s, node.all_user_params)

        if idx == len(presets) + 1:
            # All defaults
            node = self.nodes[s.node_key]
            for p in node.all_user_params:
                if p.default is not None:
                    s.params[p.name] = p.default
            s.step = "confirm"
            return self._confirm_message(s)

        return f"Reply with a number (1-{len(presets) + 2})."

    # ------------------------------------------------------------------
    # Step: param walk
    # ------------------------------------------------------------------

    def _start_param_walk(self, s: WizardSession, params: List[ParamSpec]) -> str:
        s.param_queue = list(params)
        s.current_param_idx = 0
        s.step = "param"
        return self._ask_current_param(s)

    def _handle_param(self, s: WizardSession, text: str) -> str:
        low = text.lower()

        # Skip remaining optional params
        if low in ("skip", "defaults", "done", "d"):
            return self._fill_remaining_defaults(s)

        param = s.param_queue[s.current_param_idx]
        value = self._parse_param_value(param, text)

        if value is None:
            return self._param_error(param)

        s.params[param.name] = value
        s.current_param_idx += 1

        # Are we done with all params?
        if s.current_param_idx >= len(s.param_queue):
            s.step = "confirm"
            return self._confirm_message(s)

        return self._ask_current_param(s)

    def _ask_current_param(self, s: WizardSession) -> str:
        param = s.param_queue[s.current_param_idx]
        idx = s.current_param_idx + 1
        total = len(s.param_queue)
        node = self.nodes[s.node_key]

        lines = [f"[{node.display_name}] Parameter {idx}/{total}: {param.name}"]

        if param.tooltip:
            lines.append(f"  {param.tooltip}")

        if param.choices:
            lines.append("")
            for i, c in enumerate(param.choices, 1):
                marker = " (default)" if c == param.default else ""
                lines.append(f"  {i}. {c}{marker}")
        elif param.type == "BOOLEAN":
            lines.append(f"  Reply yes/no (default: {'yes' if param.default else 'no'})")
        elif param.type == "STRING":
            lines.append(f"  Type your text (or 'skip' for empty)")
        else:
            rng = ""
            if param.min is not None and param.max is not None:
                rng = f" (range {param.min}–{param.max})"
            lines.append(f"  Enter a {param.type.lower()} value{rng}")
            if param.default is not None:
                lines.append(f"  Default: {param.default} — press Enter or type 'd' to use it")

        if not param.required:
            lines.append("  (optional — type 'skip' to use default)")
        if s.current_param_idx > 0:
            lines.append("")
            lines.append("  Type 'defaults' to accept defaults for all remaining params.")

        return "\n".join(lines)

    def _parse_param_value(self, param: ParamSpec, text: str) -> Any:
        """Parse user input into the correct type for this param."""
        low = text.lower().strip()

        # Use default
        if low in ("d", "default", "") and param.default is not None:
            return param.default

        # Choice
        if param.choices:
            try:
                idx = int(text) - 1
                if 0 <= idx < len(param.choices):
                    return param.choices[idx]
            except ValueError:
                pass
            # Try name match
            for c in param.choices:
                if low == c.lower():
                    return c
            return None

        # Boolean
        if param.type == "BOOLEAN":
            if low in ("yes", "y", "true", "1", "on"):
                return True
            if low in ("no", "n", "false", "0", "off"):
                return False
            if param.default is not None:
                return param.default
            return None

        # Float
        if param.type == "FLOAT":
            try:
                val = float(text)
                if param.min is not None and val < param.min:
                    val = param.min
                if param.max is not None and val > param.max:
                    val = param.max
                return val
            except ValueError:
                return None

        # Int
        if param.type == "INT":
            try:
                val = int(float(text))
                if param.min is not None and val < int(param.min):
                    val = int(param.min)
                if param.max is not None and val > int(param.max):
                    val = int(param.max)
                return val
            except ValueError:
                return None

        # String
        if param.type == "STRING":
            if low == "skip":
                return param.default or ""
            return text

        # Fallback — accept as string
        return text

    def _param_error(self, param: ParamSpec) -> str:
        if param.choices:
            opts = ", ".join(f"{i+1}={c}" for i, c in enumerate(param.choices))
            return f"Invalid choice. Pick a number: {opts}"
        if param.type == "FLOAT":
            return f"Enter a decimal number ({param.min}–{param.max})."
        if param.type == "INT":
            return f"Enter a whole number ({param.min}–{param.max})."
        if param.type == "BOOLEAN":
            return "Reply yes or no."
        return "Invalid input. Try again."

    def _fill_remaining_defaults(self, s: WizardSession) -> str:
        """Fill all remaining params with defaults and go to confirm."""
        while s.current_param_idx < len(s.param_queue):
            p = s.param_queue[s.current_param_idx]
            if p.default is not None:
                s.params[p.name] = p.default
            s.current_param_idx += 1
        s.step = "confirm"
        return self._confirm_message(s)

    # ------------------------------------------------------------------
    # Step: confirm
    # ------------------------------------------------------------------

    def _confirm_message(self, s: WizardSession, extra: str = "") -> str:
        node = self.nodes[s.node_key]
        lines = [
            f"Ready to apply: {node.display_name}",
        ]
        if extra:
            lines.append(extra)
        lines.append("")

        if s.params:
            lines.append("Settings:")
            for k, v in s.params.items():
                lines.append(f"  {k}: {v}")
        else:
            lines.append("(All defaults)")

        lines.append("")
        lines.append("1. Confirm and run")
        lines.append("2. Change a parameter")
        lines.append("3. Start over")
        lines.append("")
        lines.append("Reply with the number.")
        return "\n".join(lines)

    def _handle_confirm(self, s: WizardSession, text: str) -> str:
        low = text.lower().strip()
        if low in ("1", "confirm", "yes", "y", "run", "go"):
            s.step = "done"
            return (
                f"Executing {self.nodes[s.node_key].display_name} "
                f"with {len(s.params)} parameter(s)...\n\n"
                "Use the execute() method or connect to ComfyUI to run."
            )
        if low in ("2", "change", "edit"):
            node = self.nodes[s.node_key]
            return self._start_param_walk(s, node.all_user_params)
        if low in ("3", "start over", "restart", "back"):
            s.reset()
            return self._main_menu()
        return "Reply 1 (confirm), 2 (change), or 3 (start over)."

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _help_text(self) -> str:
        return (
            "Spellcaster Scaffold Help\n"
            "========================\n\n"
            "Commands you can use at any time:\n"
            "  menu / start — Go back to the main menu\n"
            "  cancel       — Cancel current operation\n"
            "  help         — Show this message\n"
            "  defaults / d — Accept all remaining defaults\n"
            "  skip         — Skip current optional parameter\n\n"
            "When asked for a parameter:\n"
            "  - Type a number to pick from a list\n"
            "  - Type 'd' or press Enter to use the default\n"
            "  - Type 'defaults' to accept defaults for everything remaining\n"
        )
