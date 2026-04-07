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
    # Process a user message through the unified meta wizard
    reply = sc.chat("user123", "I want to enhance a portrait")
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
from .meta_wizard import MetaWizard, MetaSession, build_meta_system_prompt

__all__ = [
    "SpellcasterScaffold",
    "discover_nodes",
    "NodeSpec",
    "ParamSpec",
    "SpellcasterWizard",
    "WizardSession",
    "MetaWizard",
    "MetaSession",
    "PRESETS",
    "preset_names",
    "apply_preset",
    "build_system_prompt",
    "build_meta_system_prompt",
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

    Provides three wizard modes:
      - self.meta:            Unified intent-driven router (recommended)
      - self.wizard:          Spellcaster-only (enhancement nodes with presets)
      - self.workflow_wizard:  Universal (ANY ComfyUI workflow on disk)

    Privacy:
      When cleanup_inputs/cleanup_outputs are True (the default), the
      ComfyUIRunner automatically deletes uploaded input files and
      generated output files from the ComfyUI server after they have
      been downloaded.  This is a core privacy feature for remote
      users (e.g. Signal Bridge) whose images must not persist on
      the server after delivery.
    """

    def __init__(self, comfyui_url: str = "http://localhost:8188",
                 cleanup_inputs: bool = True,
                 cleanup_outputs: bool = True):
        self.comfyui_url = comfyui_url
        self.nodes = discover_nodes()
        self.wizard = SpellcasterWizard(self.nodes)
        self.workflow_wizard = WorkflowWizard(comfyui_url=comfyui_url)
        self.meta = MetaWizard(
            spellcaster_wizard=self.wizard,
            workflow_wizard=self.workflow_wizard,
            nodes=self.nodes,
        )
        self.runner = ComfyUIRunner(
            comfyui_url,
            cleanup_inputs=cleanup_inputs,
            cleanup_outputs=cleanup_outputs,
        )

    def system_prompt(self) -> str:
        """Return the meta system prompt covering the full experience."""
        return build_meta_system_prompt(self.nodes)

    def system_prompt_spellcaster(self) -> str:
        """Return a system prompt for Spellcaster enhancement nodes only."""
        return build_system_prompt(self.nodes)

    def chat(self, user_id: str, text: str) -> str:
        """Process a user message through the unified meta wizard.

        This is the recommended entry point — it routes user intent
        to the correct sub-wizard automatically.
        """
        return self.meta.handle(user_id, text)

    def handle(self, user_id: str, text: str) -> str:
        """Process one user message through the Spellcaster wizard only."""
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
