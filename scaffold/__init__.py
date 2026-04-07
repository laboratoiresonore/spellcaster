"""
Spellcaster Scaffold — chatbot-driven interface for ComfyUI-Flux2Klein-Enhancer.

Auto-discovers all Spellcaster node classes, builds numbered menus and
step-by-step wizards so any tool-enabled LLM (7B+) can drive the full
enhancement pipeline from a chat interface.

Usage:
    from scaffold import SpellcasterScaffold
    sc = SpellcasterScaffold(comfyui_url="http://localhost:8188")
    # Get the system prompt to inject into your LLM
    print(sc.system_prompt())
    # Process a user message
    reply = sc.handle("1")  # picks first node from main menu
"""

from .introspector import discover_nodes, NodeSpec, ParamSpec
from .wizard import SpellcasterWizard, WizardSession
from .presets import PRESETS, preset_names, apply_preset
from .prompt_builder import build_system_prompt
from .comfyui_runner import ComfyUIRunner
from .bridge_launcher import BridgeLauncher, load_character_card
from .workflow_parser import (
    parse_workflow,
    discover_workflows,
    ParsedWorkflow,
    ParsedNode,
    ParsedInput,
    WorkflowEntry,
    fetch_object_info,
)
from .workflow_wizard import WorkflowWizard, WorkflowSession

__all__ = [
    "SpellcasterScaffold",
    "discover_nodes",
    "NodeSpec",
    "ParamSpec",
    "SpellcasterWizard",
    "WizardSession",
    "PRESETS",
    "preset_names",
    "apply_preset",
    "build_system_prompt",
    "ComfyUIRunner",
    "BridgeLauncher",
    "load_character_card",
    # Universal workflow parser
    "parse_workflow",
    "discover_workflows",
    "ParsedWorkflow",
    "ParsedNode",
    "ParsedInput",
    "WorkflowEntry",
    "fetch_object_info",
    "WorkflowWizard",
    "WorkflowSession",
]


class SpellcasterScaffold:
    """Top-level entry point that wires introspection + wizard + runner.

    Provides two wizard modes:
      - self.wizard: Spellcaster-only (8 enhancement nodes with presets)
      - self.workflow_wizard: Universal (ANY ComfyUI workflow on disk)
    """

    def __init__(self, comfyui_url: str = "http://localhost:8188"):
        self.comfyui_url = comfyui_url
        self.nodes = discover_nodes()
        self.wizard = SpellcasterWizard(self.nodes)
        self.workflow_wizard = WorkflowWizard(comfyui_url=comfyui_url)
        self.runner = ComfyUIRunner(comfyui_url)

    def system_prompt(self) -> str:
        """Return a full system prompt describing all available tools."""
        return build_system_prompt(self.nodes)

    def handle(self, user_id: str, text: str) -> str:
        """Process one user message through the Spellcaster wizard."""
        return self.wizard.handle(user_id, text)

    def handle_workflow(self, user_id: str, text: str) -> str:
        """Process one user message through the universal workflow wizard."""
        return self.workflow_wizard.handle(user_id, text)

    def execute(self, user_id: str) -> dict:
        """Execute the completed Spellcaster wizard session via ComfyUI API."""
        session = self.wizard.get_session(user_id)
        if not session or not session.is_complete():
            return {"error": "Wizard not complete"}
        return self.runner.run(session.to_workflow())

    def execute_workflow(self, user_id: str) -> dict:
        """Execute the completed workflow wizard session via ComfyUI API."""
        wf = self.workflow_wizard.get_final_workflow(user_id)
        if not wf:
            return {"error": "No workflow ready"}
        return self.runner.run_raw(wf)
