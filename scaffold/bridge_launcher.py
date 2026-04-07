"""
Bridge Launcher — makes Signal Bridge accessible from Spellcaster tools.

This module provides a BridgeLauncher class that:
  - Reads and validates Signal Bridge config
  - Provides access to scaffold workflows via get_scaffold_for_workflow()
  - Lists available workflows with list_workflows()
  - Generates system prompts for specific scaffolds
  - Integrates with SpellcasterScaffold via register_with_spellcaster()
  - Launches the JSX settings GUI in the default browser

Also provides load_character_card(platform) to get character cards for
integration with various AI platforms (SillyTavern, OpenWebUI, etc).

Usage:
    from bridge_launcher import BridgeLauncher
    launcher = BridgeLauncher(config_path="signal_bridge_config.json")
    launcher.launch_settings_gui()
    prompt = launcher.get_system_prompt_for_workflow("txt2img")

CLI:
    python bridge_launcher.py --gui
    python bridge_launcher.py --card tavern
    python bridge_launcher.py --list
    python bridge_launcher.py --prompt txt2img
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# For CLI use, import at bottom after main module code
discover_nodes = None
NodeSpec = None
build_system_prompt = None


# Character card templates for various platforms
CHARACTER_CARDS = {
    "sillytavern": {
        "name": "Spellcaster FLUX.2 Klein Assistant",
        "description": "AI-powered interface for FLUX.2 Klein image enhancement and conditioning via Spellcaster scaffold.",
        "personality": "You are a helpful AI assistant that guides users through configuring and running FLUX.2 Klein image enhancement nodes. You present numbered choices, validate user inputs, and maintain deterministic state progression through the configuration workflow.",
        "scenario": "User wants to enhance images using FLUX.2 Klein conditioning nodes. Guide them through selecting nodes, configuring parameters, and confirming settings.",
        "first_mes": "Welcome to Spellcaster! I'm here to help you configure and run FLUX.2 Klein enhancement nodes. Type 'menu' to see available options or 'help' for commands.",
        "mes_example": "<USER>: I want to enhance an image\n<ASSISTANT>: I can help with that! Here are the available enhancement nodes:\n\n1. Flux2KleinEnhancer\n2. Flux2KleinDetailController\n3. Flux2KleinRefLatentController\n4. Flux2KleinTextRefBalance\n5. Flux2KleinRefLatentWeight\n\nWhich one would you like to use?",
        "world": "This is a specialized image generation enhancement tool built on ComfyUI and the FLUX.2 Klein model. Users interact with it through a numbered-menu text interface.",
    },
    "openwebui": {
        "name": "Spellcaster FLUX.2 Klein",
        "description": "Image enhancement tool for FLUX.2 Klein with numbered-menu interface",
        "role": "You help users configure and run FLUX.2 Klein image enhancement nodes through a numbered-choice interface. Always present options as numbered lists and accept user choices as numbers.",
        "instructions": [
            "Guide users through Spellcaster node selection and configuration",
            "Present all options as numbered choices (never open-ended)",
            "Accept user input as numbers or default values",
            "Maintain deterministic state progression",
            "Validate all parameter inputs before confirmation",
        ],
        "tools": ["spellcaster_enhance"],
    },
    "lmstudio": {
        "name": "Spellcaster FLUX.2 Enhancement",
        "description": "Deterministic image enhancement interface for FLUX.2 Klein",
        "behavior": "Numbered-menu driven configuration of image enhancement nodes",
    },
    "koboldcpp": {
        "name": "Spellcaster FLUX.2 Klein Assistant",
        "description": "Image enhancement tool - guides users through numbered menus to configure FLUX.2 Klein nodes",
        "system_prompt": "You are Spellcaster, an AI assistant for configuring FLUX.2 Klein image enhancement. Always use numbered menus. Never ask open-ended questions.",
    },
}


class BridgeLauncher:
    """
    Manages Signal Bridge integration with Spellcaster scaffold.

    Reads Signal Bridge config, provides workflow scaffolds, generates system
    prompts, and bridges between the legal-agent Signal infrastructure and
    the Spellcaster image enhancement tools.
    """

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        config_dict: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize BridgeLauncher.

        Args:
            config_path: Path to signal_bridge_config.json (or similar)
            config_dict: Pre-loaded config dict (takes precedence over config_path)

        Raises:
            FileNotFoundError: If config_path doesn't exist and config_dict not provided
            ValueError: If config is invalid or missing required fields
        """
        self.config: Dict[str, Any] = {}
        self._nodes: Dict[str, Any] = {}
        self._workflow_scaffolds: Dict[str, Dict[str, Any]] = {}

        # Load config
        if config_dict:
            self.config = config_dict
        elif config_path:
            config_path = Path(config_path)
            if not config_path.exists():
                raise FileNotFoundError(f"Config file not found: {config_path}")
            with open(config_path, "r") as f:
                self.config = json.load(f)
        else:
            # Try common locations
            for candidate in [
                Path("signal_bridge_config.json"),
                Path("../signal_bridge_config.json"),
                Path("signal_bridge_config.example.json"),
            ]:
                if candidate.exists():
                    with open(candidate, "r") as f:
                        self.config = json.load(f)
                    break

        # Validate config
        self._validate_config()

        # Discover nodes from Spellcaster (deferred import)
        global discover_nodes
        if discover_nodes is None:
            from .introspector import discover_nodes as _discover_nodes
            discover_nodes = _discover_nodes
        self._nodes = discover_nodes()

        # Build workflow scaffolds (these are predefined mappings)
        self._build_workflow_scaffolds()

    def _validate_config(self) -> None:
        """Validate that config has required fields."""
        required = ["phone_number", "signal_cli_path", "webui_url"]
        for field in required:
            if field not in self.config:
                raise ValueError(f"Config missing required field: {field}")

    def _build_workflow_scaffolds(self) -> None:
        """
        Build workflow scaffold definitions.

        These map workflow keys (like "txt2img", "inpaint") to their
        corresponding Spellcaster node configurations and system prompts.
        """
        self._workflow_scaffolds = {
            "txt2img": {
                "name": "Text to Image Enhancement",
                "description": "Enhance text-to-image generation using FLUX.2 Klein",
                "primary_nodes": ["Flux2KleinEnhancer"],
                "optional_nodes": ["Flux2KleinDetailController"],
            },
            "inpaint": {
                "name": "Inpainting with Reference",
                "description": "Inpaint regions while maintaining reference structure",
                "primary_nodes": ["Flux2KleinRefLatentController", "Flux2KleinMaskRefController"],
                "optional_nodes": ["Flux2KleinEnhancer"],
            },
            "detail": {
                "name": "Detail Control",
                "description": "Fine-tune detail distribution across image regions",
                "primary_nodes": ["Flux2KleinDetailController"],
                "optional_nodes": ["Flux2KleinEnhancer"],
            },
            "reference": {
                "name": "Reference Latent Control",
                "description": "Use reference images to guide generation structure",
                "primary_nodes": ["Flux2KleinRefLatentController"],
                "optional_nodes": ["Flux2KleinTextRefBalance"],
            },
            "masked": {
                "name": "Masked Reference Control",
                "description": "Apply reference control selectively via mask",
                "primary_nodes": ["Flux2KleinMaskRefController"],
                "optional_nodes": ["Flux2KleinRefLatentController"],
            },
            "sectioned": {
                "name": "Sectioned Encoding",
                "description": "Use sectioned encoding for advanced prompt control",
                "primary_nodes": ["Flux2KleinSectionedEncoder"],
                "optional_nodes": ["Flux2KleinEnhancer"],
            },
        }

    def list_workflows(self) -> List[str]:
        """Return list of available workflow keys."""
        return list(self._workflow_scaffolds.keys())

    def get_scaffold_for_workflow(self, workflow_key: str) -> Dict[str, Any]:
        """
        Get the scaffold JSON for a given workflow.

        Args:
            workflow_key: Key from list_workflows()

        Returns:
            Dict with workflow metadata, node list, and configuration

        Raises:
            KeyError: If workflow_key is invalid
        """
        if workflow_key not in self._workflow_scaffolds:
            raise KeyError(f"Unknown workflow: {workflow_key}")

        scaffold = dict(self._workflow_scaffolds[workflow_key])

        # Resolve node specs
        primary_nodes = []
        for node_key in scaffold.get("primary_nodes", []):
            if node_key in self._nodes:
                primary_nodes.append({
                    "class_name": node_key,
                    "display_name": self._nodes[node_key].display_name,
                    "description": self._nodes[node_key].description,
                })

        optional_nodes = []
        for node_key in scaffold.get("optional_nodes", []):
            if node_key in self._nodes:
                optional_nodes.append({
                    "class_name": node_key,
                    "display_name": self._nodes[node_key].display_name,
                    "description": self._nodes[node_key].description,
                })

        scaffold["primary_nodes"] = primary_nodes
        scaffold["optional_nodes"] = optional_nodes
        return scaffold

    def get_system_prompt_for_workflow(self, workflow_key: str) -> str:
        """
        Generate a system prompt tailored to a specific workflow.

        Args:
            workflow_key: Key from list_workflows()

        Returns:
            System prompt string for the LLM

        Raises:
            KeyError: If workflow_key is invalid
        """
        if workflow_key not in self._workflow_scaffolds:
            raise KeyError(f"Unknown workflow: {workflow_key}")

        # Get primary nodes for this workflow
        scaffold = self._workflow_scaffolds[workflow_key]
        primary_keys = scaffold.get("primary_nodes", [])

        # Filter nodes to just those in workflow
        filtered_nodes = {
            k: v for k, v in self._nodes.items()
            if k in primary_keys or k in scaffold.get("optional_nodes", [])
        }

        # Use existing prompt builder (deferred import)
        global build_system_prompt
        if build_system_prompt is None:
            from .prompt_builder import build_system_prompt as _build_system_prompt
            build_system_prompt = _build_system_prompt

        base_prompt = build_system_prompt(filtered_nodes)

        # Add workflow-specific context
        workflow_context = f"""
WORKFLOW: {scaffold['name']}
{scaffold.get('description', '')}

This workflow is optimized for the selected use case. Follow the node
configuration protocol, present numbered choices, and guide the user
through parameter collection."""

        return workflow_context + "\n\n" + base_prompt

    def get_system_prompt(self) -> str:
        """
        Get the full system prompt for all available nodes.

        Returns:
            Complete system prompt for Spellcaster
        """
        global build_system_prompt
        if build_system_prompt is None:
            from .prompt_builder import build_system_prompt as _build_system_prompt
            build_system_prompt = _build_system_prompt
        return build_system_prompt(self._nodes)

    def launch_settings_gui(self) -> None:
        """
        Open the Signal Bridge JSX settings GUI in the default browser.

        The GUI URL is determined from config["webui_url"]. This opens
        the web-based settings editor for configuring the bridge.
        """
        webui_url = self.config.get("webui_url", "http://localhost:8080")
        settings_url = f"{webui_url}/settings/signal-bridge"

        try:
            webbrowser.open(settings_url)
            print(f"Opened Signal Bridge settings at: {settings_url}")
        except Exception as e:
            print(
                f"Could not open browser. Visit manually: {settings_url}\n"
                f"Error: {e}"
            )

    def register_with_spellcaster(self, scaffold_instance: Any) -> None:
        """
        Register this launcher with a SpellcasterScaffold instance.

        This adds bridge methods to the scaffold so it can access Signal Bridge
        configs and workflows directly through the Spellcaster interface.

        Also applies privacy settings from the bridge config to the runner:
        if ``privacy.auto_delete_generated`` or ``privacy.clean_comfyui_input``
        are set, the runner's cleanup flags are updated accordingly.

        Args:
            scaffold_instance: A SpellcasterScaffold instance
        """
        # Add our methods to the scaffold instance
        scaffold_instance.bridge_launcher = self
        scaffold_instance.list_workflows = self.list_workflows
        scaffold_instance.get_scaffold = self.get_scaffold_for_workflow
        scaffold_instance.get_bridge_config = lambda: self.config

        # Apply privacy settings from bridge config to the runner.
        # The runner uses ComfyUI-api-tools DELETE endpoints for cleanup.
        privacy = self.config.get("privacy", {})
        if hasattr(scaffold_instance, "runner"):
            runner = scaffold_instance.runner
            runner.cleanup_inputs = privacy.get(
                "clean_comfyui_input", runner.cleanup_inputs)
            runner.cleanup_outputs = privacy.get(
                "auto_delete_generated", runner.cleanup_outputs)

        print("BridgeLauncher registered with SpellcasterScaffold")

    def get_config(self) -> Dict[str, Any]:
        """Return a copy of the current config."""
        return dict(self.config)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize launcher state to a dict.

        Returns:
            Dict with config, available workflows, and node list
        """
        return {
            "config": self.get_config(),
            "workflows": self.list_workflows(),
            "nodes": list(self._nodes.keys()),
            "scaffold_templates": self._workflow_scaffolds,
        }


def load_character_card(platform: str) -> Dict[str, Any]:
    """
    Load a character card for a given platform.

    Args:
        platform: One of "sillytavern", "openwebui", "lmstudio", "koboldcpp"

    Returns:
        Character card dict formatted for the platform

    Raises:
        ValueError: If platform is unknown
    """
    platform = platform.lower().strip()

    if platform not in CHARACTER_CARDS:
        available = ", ".join(CHARACTER_CARDS.keys())
        raise ValueError(f"Unknown platform '{platform}'. Available: {available}")

    return dict(CHARACTER_CARDS[platform])


# =====================================================================
# CLI Interface
# =====================================================================

def main():
    """Command-line interface for BridgeLauncher."""
    # Ensure imports are loaded for CLI use
    global discover_nodes, build_system_prompt
    if discover_nodes is None:
        from .introspector import discover_nodes as _discover_nodes
        discover_nodes = _discover_nodes
    if build_system_prompt is None:
        from .prompt_builder import build_system_prompt as _build_system_prompt
        build_system_prompt = _build_system_prompt

    parser = argparse.ArgumentParser(
        description="Signal Bridge launcher for Spellcaster scaffold",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bridge_launcher.py --gui
  python bridge_launcher.py --card tavern
  python bridge_launcher.py --card webui
  python bridge_launcher.py --list
  python bridge_launcher.py --prompt txt2img
  python bridge_launcher.py --scaffold txt2img
        """,
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to signal_bridge_config.json (auto-detects if not specified)",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--gui",
        action="store_true",
        help="Open Signal Bridge settings GUI in default browser",
    )
    group.add_argument(
        "--card",
        type=str,
        metavar="PLATFORM",
        help="Print character card for platform (sillytavern|openwebui|lmstudio|koboldcpp)",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List all available workflows",
    )
    group.add_argument(
        "--prompt",
        type=str,
        metavar="WORKFLOW",
        help="Print system prompt for workflow (use --list to see options)",
    )
    group.add_argument(
        "--scaffold",
        type=str,
        metavar="WORKFLOW",
        help="Print scaffold JSON for workflow",
    )
    group.add_argument(
        "--nodes",
        action="store_true",
        help="List all available Spellcaster nodes",
    )

    args = parser.parse_args()

    try:
        launcher = BridgeLauncher(config_path=args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.gui:
            launcher.launch_settings_gui()

        elif args.card:
            card = load_character_card(args.card)
            print(json.dumps(card, indent=2))

        elif args.list:
            workflows = launcher.list_workflows()
            print("Available Spellcaster workflows:")
            print()
            for workflow_key in workflows:
                scaffold = launcher.get_scaffold_for_workflow(workflow_key)
                print(f"  {workflow_key}: {scaffold['name']}")
                print(f"    {scaffold.get('description', 'No description')}")
                print()

        elif args.prompt:
            prompt = launcher.get_system_prompt_for_workflow(args.prompt)
            print(prompt)

        elif args.scaffold:
            scaffold = launcher.get_scaffold_for_workflow(args.scaffold)
            print(json.dumps(scaffold, indent=2))

        elif args.nodes:
            nodes = discover_nodes()
            print("Available Spellcaster nodes:")
            print()
            for key, node in nodes.items():
                print(f"  {key}: {node.display_name}")
                if node.description:
                    print(f"    {node.description}")
                print()

    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
