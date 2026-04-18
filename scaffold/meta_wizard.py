"""
Meta Wizard — top-level router that translates user intent into the
correct wizard path through Spellcaster.

Sits above SpellcasterWizard (enhancement nodes) and WorkflowWizard
(arbitrary ComfyUI workflows) to provide a unified, intent-driven
experience.

A user says "I want to make this photo more cinematic" and the meta
wizard figures out they need Flux2KleinEnhancer with a Strong preset,
not a txt2img workflow.

State machine:
    idle -> intent -> [route to sub-wizard] -> sub_wizard_active -> done

Designed for 7B models — every decision is a numbered choice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .wizard import SpellcasterWizard, WizardSession
from .workflow_wizard import WorkflowWizard, WorkflowSession
from .introspector import NodeSpec
try:
    from .video_wizard import CinematographerWizard
except ImportError:
    CinematographerWizard = None


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
        "key": "generate",
        "label": "Generate a new image from text",
        "description": "txt2img — describe what you want, get an image",
        "route": "workflow",
        "workflow_hint": "txt2img",
    },
    {
        "key": "modify",
        "label": "Transform an existing image (img2img, style transfer, face swap)",
        "description": "img2img, face swap, repose, blend, style transfer",
        "route": "workflow",
        "workflow_hint": "img2img",
    },
    {
        "key": "video",
        "label": "Generate video (LTX2, WAN, animate from image)",
        "description": "Text-to-video, image-to-video, LTX 2.3, WAN 2.2, distilled fast mode",
        "route": "video",
        "workflow_hint": "video",
    },
    {
        "key": "video_upscale",
        "label": "Upscale or enhance video",
        "description": "SeedVR2 AI upscale, RTX super resolution, RIFE frame interpolation",
        "route": "pipeline",
        "pipeline_hint": ["seedvr2_upscale", "video_reactor"],
    },
    {
        "key": "director",
        "label": "Director's Chair (multi-step video sequences)",
        "description": "Chain WAN video steps with face re-injection, script presets, solo/duo/trio",
        "route": "pipeline",
        "pipeline_hint": ["director_solo"],
    },
    {
        "key": "studio",
        "label": "Magic Studios (full character pipeline)",
        "description": "Selfie to face model to body to wardrobe to set to video — guided 5-act pipeline",
        "route": "pipeline",
        "pipeline_hint": ["magic_studios"],
    },
    {
        "key": "workflow",
        "label": "Browse all ComfyUI workflows",
        "description": "Pick from any installed workflow and tune parameters",
        "route": "workflow",
    },
]


# ── Session tracking ──────────────────────────────────────────────────

@dataclass
class MetaSession:
    """Tracks one user's journey through the meta wizard."""
    user_id: str
    step: str = "idle"
    selected_intent: Optional[Dict[str, Any]] = None
    active_sub: Optional[str] = None   # "spellcaster" or "workflow"
    # Chain state — when user finishes one node, offer to chain another
    chain: List[Dict[str, Any]] = field(default_factory=list)

    def reset(self):
        self.step = "idle"
        self.selected_intent = None
        self.active_sub = None
        self.chain.clear()


# ── Meta Wizard ───────────────────────────────────────────────────────

class MetaWizard:
    """
    Top-level router that presents intent-based choices and delegates
    to SpellcasterWizard or WorkflowWizard.

    Call handle(user_id, text) for each message.
    Returns the next message to send back.
    """

    def __init__(
        self,
        spellcaster_wizard: SpellcasterWizard,
        workflow_wizard: WorkflowWizard,
        nodes: Optional[Dict[str, NodeSpec]] = None,
        video_wizard: Optional[Any] = None,
    ):
        self.spell = spellcaster_wizard
        self.wf = workflow_wizard
        self.video = video_wizard  # CinematographerWizard (optional)
        self.nodes = nodes or {}
        self._sessions: Dict[str, MetaSession] = {}

    def get_session(self, user_id: str) -> Optional[MetaSession]:
        return self._sessions.get(user_id)

    def handle(self, user_id: str, text: str) -> str:
        """Process one message, return reply."""
        text = text.strip()
        low = text.lower()

        s = self._sessions.get(user_id)

        # Global commands — always available
        if low in ("menu", "start", "home", "main"):
            if s:
                s.reset()
            return self._main_menu(user_id)

        if low in ("cancel", "quit", "exit", "stop"):
            if s:
                s.reset()
            return "Cancelled. Type 'menu' to start over."

        if low == "help":
            return self._help_text()

        # If sub-wizard is active, delegate to it
        if s and s.active_sub:
            return self._delegate_to_sub(s, text)

        # No session or idle — show main menu
        if s is None or s.step == "idle":
            s = MetaSession(user_id=user_id, step="intent")
            self._sessions[user_id] = s
            if low in ("", "hi", "hello", "hey"):
                return self._main_menu(user_id)
            # Try to interpret as intent pick
            return self._handle_intent(s, text)

        if s.step == "intent":
            return self._handle_intent(s, text)

        if s.step == "suggest_node":
            return self._handle_node_suggestion(s, text)

        if s.step == "chain_offer":
            return self._handle_chain(s, text)

        if s.step == "video_choice":
            return self._handle_video_choice(s, text)

        # Fallback
        s.reset()
        return self._main_menu(user_id)

    # ------------------------------------------------------------------
    # Main menu
    # ------------------------------------------------------------------

    def _main_menu(self, user_id: str) -> str:
        s = MetaSession(user_id=user_id, step="intent")
        self._sessions[user_id] = s

        lines = [
            "Spellcaster — FLUX.2 Klein Image Studio",
            "=" * 42,
            "",
            "What would you like to do?",
            "",
        ]

        for i, intent in enumerate(INTENTS, 1):
            lines.append(f"  {i}. {intent['label']}")
            lines.append(f"     {intent['description']}")

        lines.append("")
        lines.append("Pick a number, or describe what you want in your own words.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Intent handling
    # ------------------------------------------------------------------

    def _handle_intent(self, s: MetaSession, text: str) -> str:
        low = text.lower()

        # Try numeric pick
        try:
            idx = int(text) - 1
            if 0 <= idx < len(INTENTS):
                return self._select_intent(s, INTENTS[idx])
        except ValueError:
            pass

        # Try keyword matching against intent keys and labels
        best_match = None
        best_score = 0
        for intent in INTENTS:
            score = 0
            # Exact key match
            if low == intent["key"]:
                score = 100
            # Key in text
            elif intent["key"] in low:
                score = 50
            # Label words in text
            else:
                label_words = intent["label"].lower().split()
                desc_words = intent["description"].lower().split()
                all_words = set(label_words + desc_words)
                text_words = set(low.split())
                overlap = all_words & text_words
                score = len(overlap) * 10

            if score > best_score:
                best_score = score
                best_match = intent

        if best_match and best_score >= 10:
            return self._select_intent(s, best_match)

        return (
            f"I didn't catch that. Pick a number (1-{len(INTENTS)}) "
            f"from the menu, or describe what you want to do with your image."
        )

    def _select_intent(self, s: MetaSession, intent: dict) -> str:
        s.selected_intent = intent

        if intent["route"] == "spellcaster":
            # If there are suggested nodes, offer them
            suggested = intent.get("suggested_nodes", [])
            available = [n for n in suggested if n in self.nodes]

            if len(available) == 1:
                # Only one option — go straight to it
                s.active_sub = "spellcaster"
                s.step = "sub_active"
                # Feed the node pick to the spellcaster wizard
                # First trigger menu, then pick the node
                self.spell.handle(s.user_id, "menu")
                return self.spell.handle(s.user_id, available[0])
            elif available:
                s.step = "suggest_node"
                return self._suggest_nodes(s, available)
            else:
                # No specific nodes discovered — fall through to spellcaster menu
                s.active_sub = "spellcaster"
                s.step = "sub_active"
                return self.spell.handle(s.user_id, "menu")

        elif intent["route"] == "video":
            # Offer choice between single-render workflow and shotboard
            if self.video is not None:
                s.step = "video_choice"
                return (
                    "What kind of video session?\n\n"
                    "1. Quick render (single video via ComfyUI workflow)\n"
                    "2. Shotboard (multi-shot project via WanGP / LTX)\n"
                )
            # No video wizard available — fall through to workflow path
            s.active_sub = "workflow"
            s.step = "sub_active"
            hint = intent.get("workflow_hint")
            if hint:
                reply = self.wf.handle(s.user_id, "menu")
                search_reply = self.wf.handle(s.user_id, hint)
                if "No match" not in search_reply and "No workflows" not in search_reply:
                    return search_reply
                return reply
            return self.wf.handle(s.user_id, "menu")

        elif intent["route"] == "workflow":
            s.active_sub = "workflow"
            s.step = "sub_active"

            # If there's a workflow hint, search for it
            hint = intent.get("workflow_hint")
            if hint:
                reply = self.wf.handle(s.user_id, "menu")
                # Try searching with the hint
                search_reply = self.wf.handle(s.user_id, hint)
                # If it found something useful, return that
                if "No match" not in search_reply and "No workflows" not in search_reply:
                    return search_reply
                # Otherwise show the browse menu
                return reply
            else:
                return self.wf.handle(s.user_id, "menu")

        # Shouldn't get here
        return self._main_menu(s.user_id)

    # ------------------------------------------------------------------
    # Node suggestions (for spellcaster intents with multiple options)
    # ------------------------------------------------------------------

    def _suggest_nodes(self, s: MetaSession, available: List[str]) -> str:
        intent = s.selected_intent
        lines = [
            f"For '{intent['label'].lower()}':",
            "",
            "Which enhancement node would you like to configure?",
            "",
        ]

        s._suggested_nodes = available
        for i, key in enumerate(available, 1):
            node = self.nodes.get(key)
            name = node.display_name if node else key
            desc = node.description if node else ""
            lines.append(f"  {i}. {name}")
            if desc:
                lines.append(f"     {desc}")

        lines.append("")
        lines.append(f"  {len(available) + 1}. Show all enhancement nodes")
        lines.append("")
        lines.append("Pick a number.")
        return "\n".join(lines)

    def _handle_node_suggestion(self, s: MetaSession, text: str) -> str:
        available = getattr(s, "_suggested_nodes", [])

        try:
            idx = int(text) - 1
            if 0 <= idx < len(available):
                s.active_sub = "spellcaster"
                s.step = "sub_active"
                self.spell.handle(s.user_id, "menu")
                return self.spell.handle(s.user_id, available[idx])
            if idx == len(available):
                # Show all
                s.active_sub = "spellcaster"
                s.step = "sub_active"
                return self.spell.handle(s.user_id, "menu")
        except ValueError:
            pass

        return f"Pick a number (1-{len(available) + 1})."

    # ------------------------------------------------------------------
    # Sub-wizard delegation
    # ------------------------------------------------------------------

    def _delegate_to_sub(self, s: MetaSession, text: str) -> str:
        if s.active_sub == "spellcaster":
            reply = self.spell.handle(s.user_id, text)
            # Check if the sub-wizard completed
            session = self.spell.get_session(s.user_id)
            if session and session.is_complete():
                s.step = "chain_offer"
                s.chain.append(session.to_workflow())
                return reply + "\n\n" + self._chain_offer(s)
            return reply

        elif s.active_sub == "workflow":
            reply = self.wf.handle(s.user_id, text)
            # Check if workflow wizard completed
            wf_session = self.wf.get_session(s.user_id)
            if wf_session and wf_session.step == "done":
                s.step = "chain_offer"
                return reply + "\n\n" + self._chain_offer(s)
            return reply

        elif s.active_sub == "video":
            if self.video is None:
                s.reset()
                return self._main_menu(s.user_id)
            reply = self.video.handle(s.user_id, text)
            # Check if the video wizard flagged a render
            pending = self.video.get_pending_render(s.user_id)
            if pending:
                # The VideoBridge will pick this up via handle_chat;
                # here we just relay the wizard's reply.
                pass
            return reply

        return self._main_menu(s.user_id)

    # ------------------------------------------------------------------
    # Chaining — offer to add another node or finish
    # ------------------------------------------------------------------

    def _chain_offer(self, s: MetaSession) -> str:
        n = len(s.chain)
        lines = [
            f"Node {n} configured. What next?",
            "",
            "  1. Add another enhancement node (chain)",
            "  2. Done — execute all",
            "  3. Start over",
            "",
            "Reply with the number.",
        ]
        return "\n".join(lines)

    def _handle_chain(self, s: MetaSession, text: str) -> str:
        low = text.lower().strip()

        if low in ("1", "chain", "add", "another"):
            s.active_sub = "spellcaster"
            s.step = "sub_active"
            return self.spell.handle(s.user_id, "menu")

        if low in ("2", "done", "execute", "run", "go"):
            s.step = "done"
            n = len(s.chain)
            lines = [
                f"Pipeline complete — {n} node(s) configured.",
                "",
                "Final configuration:",
            ]
            for i, wf in enumerate(s.chain, 1):
                lines.append(f"  {i}. {wf['node']}: {wf['params']}")
            lines.append("")
            lines.append("Ready to execute via ComfyUI.")
            return "\n".join(lines)

        if low in ("3", "start over", "restart", "back"):
            s.reset()
            return self._main_menu(s.user_id)

        return "Reply 1 (add node), 2 (execute), or 3 (start over)."

    def _handle_video_choice(self, s: MetaSession, text: str) -> str:
        """Handle the video sub-menu: quick render vs shotboard."""
        low = text.lower().strip()

        if low in ("1", "quick", "single", "workflow"):
            # Fall through to the existing ComfyUI workflow path
            s.active_sub = "workflow"
            s.step = "sub_active"
            hint = (s.selected_intent or {}).get("workflow_hint", "video")
            reply = self.wf.handle(s.user_id, "menu")
            search_reply = self.wf.handle(s.user_id, hint)
            if "No match" not in search_reply and "No workflows" not in search_reply:
                return search_reply
            return reply

        if low in ("2", "shotboard", "multi", "project", "shots"):
            if self.video is None:
                s.reset()
                return ("Shotboard not available — video wizard module "
                        "not loaded.\n\n" + self._main_menu(s.user_id))
            s.active_sub = "video"
            s.step = "sub_active"
            return self.video.handle(s.user_id, "menu")

        return ("Pick a number:\n\n"
                "1. Quick render (single video via ComfyUI workflow)\n"
                "2. Shotboard (multi-shot project via WanGP / LTX)\n")

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _help_text(self) -> str:
        return (
            "Spellcaster — FLUX.2 Klein Image Studio\n"
            "========================================\n\n"
            "Commands you can use at any time:\n"
            "  menu / home  — Go back to the main menu\n"
            "  cancel       — Cancel current operation\n"
            "  help         — Show this message\n\n"
            "How it works:\n"
            "  1. Tell me what you want to do (or pick from the menu)\n"
            "  2. I'll guide you through configuring the right tools\n"
            "  3. You can chain multiple enhancements together\n"
            "  4. When ready, I'll send it to ComfyUI to execute\n\n"
            "You can also type 'workflows' to browse all ComfyUI workflows directly."
        )


# ── System prompt builder for meta wizard ─────────────────────────────

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

PRIVACY:
When privacy cleanup is enabled (the default), tell the user BEFORE execution:
  "For your privacy, your uploaded image(s) and the generated image(s)
   will be automatically deleted from the server after delivery to you."
After execution, relay the cleanup["privacy_message"] from the result to
confirm deletion. Example:
  "Privacy cleanup complete — 1 uploaded image(s) and 1 generated image(s)
   deleted from the server."
If cleanup fails or the extension is missing, warn the user honestly.

GLOBAL COMMANDS:
  menu / home — Main menu
  cancel      — Cancel and reset
  help        — Show help
  defaults    — Accept remaining defaults
  workflows   — Browse ComfyUI workflow library"""
