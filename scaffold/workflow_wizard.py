"""
Workflow Wizard — extends the Spellcaster wizard to support ANY ComfyUI
workflow, not just Spellcaster enhancement nodes.

State machine per user:
    idle -> browse -> workflow_pick -> param_select -> param_edit -> confirm -> done

Users can:
  1. Browse all workflows on their ComfyUI server (145+ user workflows)
  2. Pick one, see its tunable parameters
  3. Override specific values (prompt text, seed, model, dimensions, etc.)
  4. Submit to ComfyUI for execution

Works with or without a running ComfyUI server:
  - With server: /object_info provides perfect input name resolution
  - Without server: heuristic fallback with widget_{n} names

Designed so a 7B model can drive it — numbered menus, no ambiguity.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .workflow_parser import (
    ParsedWorkflow,
    ParsedInput,
    ParsedNode,
    WorkflowEntry,
    discover_workflows,
    parse_workflow,
    workflow_menu,
    tunable_params_menu,
)


# ── Smart parameter filtering ──────────────────────────────────────────

# Inputs a power user almost always wants to change
HIGH_PRIORITY_PATTERNS = {
    "text", "prompt", "positive", "negative",       # prompts
    "seed",                                          # randomness
    "ckpt_name", "unet_name", "model_name",          # models
    "lora_name",                                     # LoRAs
    "image", "video",                                # media inputs
}

# Inputs that are adjustable but usually fine at defaults
MEDIUM_PRIORITY_PATTERNS = {
    "width", "height", "batch_size",                 # dimensions
    "steps", "cfg", "denoise",                       # sampler
    "sampler_name", "scheduler",                     # sampler choice
    "strength", "weight", "scale",                   # intensities
}

# Inputs that are rarely changed (internal wiring, filenames, etc.)
LOW_PRIORITY_PATTERNS = {
    "filename_prefix", "save_",                      # output names
    "device", "dtype",                               # hardware
    "overwrite", "preview",                          # flags
}


def _input_priority(name: str, inp: ParsedInput) -> int:
    """Return priority 0 (highest) to 3 (lowest) for a tunable input."""
    low = name.lower()

    for pat in HIGH_PRIORITY_PATTERNS:
        if pat in low:
            return 0

    for pat in MEDIUM_PRIORITY_PATTERNS:
        if pat in low:
            return 1

    for pat in LOW_PRIORITY_PATTERNS:
        if pat in low:
            return 3

    # Model files are always interesting
    if isinstance(inp.value, str) and inp.value.endswith(
        (".safetensors", ".ckpt", ".gguf", ".pt", ".bin")
    ):
        return 0

    # Long strings are probably prompts
    if isinstance(inp.value, str) and len(inp.value) > 30:
        return 0

    return 2


def smart_tunable_params(wf: ParsedWorkflow,
                          max_params: int = 25) -> List[Tuple[str, str, ParsedInput]]:
    """Return the most important tunable parameters, capped at max_params.

    Returns list of (node_id, input_name, ParsedInput) sorted by priority.
    """
    all_tunable: List[Tuple[int, str, str, ParsedInput]] = []

    for nid, node in wf.active_nodes.items():
        for iname, inp in node.user_tunable_inputs.items():
            prio = _input_priority(iname, inp)
            all_tunable.append((prio, nid, iname, inp))

    all_tunable.sort(key=lambda t: t[0])

    result = [(nid, iname, inp) for _, nid, iname, inp in all_tunable[:max_params]]
    return result


# ── Workflow session ────────────────────────────────────────────────────

@dataclass
class WorkflowSession:
    """Tracks one user's progress through workflow selection and editing."""
    user_id: str
    step: str = "idle"
    # Browse state
    entries: List[WorkflowEntry] = field(default_factory=list)
    category_filter: Optional[str] = None
    # Selected workflow
    selected_entry: Optional[WorkflowEntry] = None
    parsed: Optional[ParsedWorkflow] = None
    # Parameter editing
    smart_params: List[Tuple[str, str, ParsedInput]] = field(default_factory=list)
    overrides: Dict[Tuple[str, str], Any] = field(default_factory=dict)
    editing_param_idx: Optional[int] = None

    def reset(self):
        self.step = "idle"
        self.selected_entry = None
        self.parsed = None
        self.smart_params.clear()
        self.overrides.clear()
        self.editing_param_idx = None
        self.category_filter = None


# ── Workflow Wizard ─────────────────────────────────────────────────────

class WorkflowWizard:
    """
    Interactive wizard for browsing and running arbitrary ComfyUI workflows.

    Call handle(user_id, text) with each incoming message.
    Returns the next message to send back.
    """

    def __init__(self,
                 search_dirs: Optional[List[Union[str, Path]]] = None,
                 comfyui_url: Optional[str] = None):
        self.search_dirs = search_dirs
        self.comfyui_url = comfyui_url
        self._sessions: Dict[str, WorkflowSession] = {}
        self._entries: Optional[List[WorkflowEntry]] = None

    @property
    def entries(self) -> List[WorkflowEntry]:
        if self._entries is None:
            self._entries = discover_workflows(self.search_dirs)
        return self._entries

    def refresh(self):
        """Re-scan workflow directories."""
        self._entries = None

    def get_session(self, user_id: str) -> Optional[WorkflowSession]:
        return self._sessions.get(user_id)

    def handle(self, user_id: str, text: str) -> str:
        """Process one message, return reply."""
        text = text.strip()
        s = self._sessions.get(user_id)
        low = text.lower()

        # Global commands
        if low in ("cancel", "quit", "exit", "stop"):
            if s:
                s.reset()
            return "Cancelled. Type 'workflows' to browse again."

        if low in ("menu", "workflows", "browse", "start", "wf"):
            if s:
                s.reset()
            else:
                s = WorkflowSession(user_id=user_id)
                self._sessions[user_id] = s
            s.step = "browse"
            s.entries = self.entries
            return self._browse_menu(s)

        if low == "help":
            return self._help_text()

        if low == "refresh":
            self.refresh()
            return f"Rescanned. Found {len(self.entries)} workflows. Type 'workflows' to browse."

        # If no session, show browse
        if s is None or s.step == "idle":
            s = WorkflowSession(user_id=user_id)
            self._sessions[user_id] = s
            if low in ("", "hi", "hello", "hey"):
                s.step = "browse"
                s.entries = self.entries
                return self._browse_menu(s)
            # Maybe they typed a number right away
            s.step = "browse"
            s.entries = self.entries
            return self._handle_browse(s, text)

        handler = getattr(self, f"_handle_{s.step}", None)
        if handler:
            return handler(s, text)

        s.reset()
        return self._browse_menu(s)

    # ------------------------------------------------------------------
    # Browse: category selection and workflow listing
    # ------------------------------------------------------------------

    def _browse_menu(self, s: WorkflowSession) -> str:
        """Show workflow categories for browsing."""
        entries = s.entries or self.entries

        # Group by category
        cats: Dict[str, List[WorkflowEntry]] = OrderedDict()
        for e in entries:
            cats.setdefault(e.category, []).append(e)

        lines = [
            "ComfyUI Workflow Library",
            "=" * 35,
            f"({len(entries)} workflows found)",
            "",
            "Browse by category:",
            "",
        ]

        cat_list = list(cats.keys())
        for i, cat in enumerate(cat_list, 1):
            wfs = cats[cat]
            types = set(w.workflow_type for w in wfs)
            type_str = ", ".join(sorted(types)[:3])
            lines.append(f"  {i}. {cat} ({len(wfs)} workflows — {type_str})")

        lines.append("")
        lines.append(f"  {len(cat_list) + 1}. Show ALL workflows")
        lines.append(f"  {len(cat_list) + 2}. Search by name")
        lines.append("")
        lines.append("Reply with a number or type a workflow name to search.")
        return "\n".join(lines)

    def _handle_browse(self, s: WorkflowSession, text: str) -> str:
        low = text.lower()
        entries = s.entries or self.entries

        # Build category list
        cats = OrderedDict()
        for e in entries:
            cats.setdefault(e.category, []).append(e)
        cat_list = list(cats.keys())

        try:
            idx = int(text)
            if 1 <= idx <= len(cat_list):
                # Show workflows in this category
                s.category_filter = cat_list[idx - 1]
                s.step = "workflow_pick"
                return self._workflow_list(s)
            elif idx == len(cat_list) + 1:
                # Show all
                s.category_filter = None
                s.step = "workflow_pick"
                return self._workflow_list(s)
            elif idx == len(cat_list) + 2:
                s.step = "search"
                return "Type a search term (part of the workflow name):"
        except ValueError:
            pass

        # Text search
        matches = [e for e in entries if low in e.name.lower()]
        if len(matches) == 1:
            return self._select_workflow(s, matches[0])
        elif matches:
            s.entries = matches
            s.step = "workflow_pick"
            s.category_filter = None
            return self._workflow_list(s, title=f"Search results for '{text}'")

        return f"No match for '{text}'. Type a number (1-{len(cat_list) + 2}) or a workflow name."

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _handle_search(self, s: WorkflowSession, text: str) -> str:
        low = text.lower()
        entries = self.entries
        matches = [e for e in entries if low in e.name.lower()]

        if not matches:
            return f"No workflows matching '{text}'. Try another search, or type 'menu' to browse."
        if len(matches) == 1:
            return self._select_workflow(s, matches[0])

        s.entries = matches
        s.step = "workflow_pick"
        s.category_filter = None
        return self._workflow_list(s, title=f"Search results for '{text}' ({len(matches)} found)")

    # ------------------------------------------------------------------
    # Workflow pick: numbered list within a category
    # ------------------------------------------------------------------

    def _workflow_list(self, s: WorkflowSession,
                       title: Optional[str] = None) -> str:
        entries = s.entries or self.entries
        if s.category_filter:
            filtered = [e for e in entries if e.category == s.category_filter]
            title = title or f"── {s.category_filter} ──"
        else:
            filtered = entries
            title = title or "All Workflows"

        s._filtered = filtered  # stash for index lookup

        lines = [title, "=" * 35, ""]
        for i, e in enumerate(filtered, 1):
            tag = f" [{e.workflow_type}]" if e.workflow_type else ""
            lines.append(f"  {i}. {e.name}{tag}  ({e.node_count} nodes)")
        lines.append("")
        lines.append(f"  {len(filtered) + 1}. Back to categories")
        lines.append("")
        lines.append("Reply with a number.")
        return "\n".join(lines)

    def _handle_workflow_pick(self, s: WorkflowSession, text: str) -> str:
        filtered = getattr(s, "_filtered", s.entries or self.entries)

        try:
            idx = int(text)
            if idx == len(filtered) + 1:
                s.step = "browse"
                s.category_filter = None
                s.entries = self.entries
                return self._browse_menu(s)
            if 1 <= idx <= len(filtered):
                return self._select_workflow(s, filtered[idx - 1])
        except ValueError:
            # Try name match
            low = text.lower()
            for e in filtered:
                if low in e.name.lower():
                    return self._select_workflow(s, e)

        return f"Reply with a number (1-{len(filtered) + 1})."

    # ------------------------------------------------------------------
    # Workflow selected — parse and show parameters
    # ------------------------------------------------------------------

    def _select_workflow(self, s: WorkflowSession,
                         entry: WorkflowEntry) -> str:
        s.selected_entry = entry
        s.parsed = parse_workflow(entry.path, comfyui_url=self.comfyui_url)
        s.smart_params = smart_tunable_params(s.parsed, max_params=30)
        s.overrides.clear()
        s.step = "param_select"

        return self._param_overview(s)

    def _param_overview(self, s: WorkflowSession) -> str:
        wf = s.parsed
        entry = s.selected_entry

        lines = [
            f"Workflow: {entry.name}",
            f"Type: {wf.summary().split(chr(10))[1].replace('Type: ', '')}",
            f"Nodes: {len(wf.active_nodes)} active",
            "",
            "Key tunable parameters:",
            "",
        ]

        for i, (nid, iname, inp) in enumerate(s.smart_params, 1):
            node = wf.nodes[nid]
            node_label = node.title or node.display_name or node.class_type
            val_preview = _format_value(inp.value)
            override = s.overrides.get((nid, iname))
            if override is not None:
                val_preview = f"{_format_value(override)} (changed)"

            lines.append(f"  {i}. [{node_label}] {iname} = {val_preview}")

        lines.append("")
        lines.append(f"  {len(s.smart_params) + 1}. Run as-is (current values)")
        lines.append(f"  {len(s.smart_params) + 2}. Show ALL parameters")
        lines.append(f"  {len(s.smart_params) + 3}. Back to workflow list")
        lines.append("")
        lines.append("Pick a parameter number to change, or choose an action.")
        return "\n".join(lines)

    def _handle_param_select(self, s: WorkflowSession, text: str) -> str:
        n_params = len(s.smart_params)

        try:
            idx = int(text)
        except ValueError:
            low = text.lower()
            if low in ("run", "go", "execute", "ok"):
                return self._go_to_confirm(s)
            if low in ("all", "show all"):
                return self._show_all_params(s)
            if low in ("back",):
                s.step = "browse"
                return self._browse_menu(s)
            return f"Reply with a number (1-{n_params + 3})."

        if idx == n_params + 1:
            return self._go_to_confirm(s)
        if idx == n_params + 2:
            return self._show_all_params(s)
        if idx == n_params + 3:
            s.step = "browse"
            s.entries = self.entries
            s.category_filter = None
            return self._browse_menu(s)
        if 1 <= idx <= n_params:
            s.editing_param_idx = idx - 1
            s.step = "param_edit"
            return self._ask_param_value(s)

        return f"Reply with a number (1-{n_params + 3})."

    # ------------------------------------------------------------------
    # Parameter editing
    # ------------------------------------------------------------------

    def _ask_param_value(self, s: WorkflowSession) -> str:
        nid, iname, inp = s.smart_params[s.editing_param_idx]
        node = s.parsed.nodes[nid]
        node_label = node.title or node.display_name or node.class_type

        lines = [f"Editing: [{node_label}] {iname}"]

        if inp.tooltip:
            lines.append(f"  {inp.tooltip}")

        current = s.overrides.get((nid, iname), inp.value)
        lines.append(f"  Current value: {_format_value(current)}")

        if inp.choices:
            lines.append("")
            for i, c in enumerate(inp.choices[:15], 1):
                marker = " ←" if c == current else ""
                lines.append(f"  {i}. {c}{marker}")
            if len(inp.choices) > 15:
                lines.append(f"  ... and {len(inp.choices) - 15} more")
        elif inp.input_type.upper() == "BOOLEAN":
            lines.append("  Reply: yes / no")
        elif inp.input_type.upper() == "INT":
            rng = ""
            if inp.min_val is not None:
                rng += f" min={inp.min_val}"
            if inp.max_val is not None:
                rng += f" max={inp.max_val}"
            lines.append(f"  Enter a whole number{rng}")
        elif inp.input_type.upper() == "FLOAT":
            rng = ""
            if inp.min_val is not None:
                rng += f" min={inp.min_val}"
            if inp.max_val is not None:
                rng += f" max={inp.max_val}"
            lines.append(f"  Enter a decimal number{rng}")
        elif inp.input_type.upper() == "STRING":
            if inp.multiline:
                lines.append("  Enter your text (can be multiple sentences)")
            else:
                lines.append("  Enter new value")
        else:
            lines.append(f"  Enter new value (type: {inp.input_type})")

        lines.append("")
        lines.append("  Type 'keep' to keep current value, 'back' to go back.")
        return "\n".join(lines)

    def _handle_param_edit(self, s: WorkflowSession, text: str) -> str:
        low = text.lower().strip()

        if low in ("keep", "cancel", "back"):
            s.step = "param_select"
            return self._param_overview(s)

        nid, iname, inp = s.smart_params[s.editing_param_idx]
        value = _parse_input_value(inp, text)

        if value is None:
            return f"Invalid input. Try again, or type 'keep' to keep current value."

        s.overrides[(nid, iname)] = value
        s.step = "param_select"
        return self._param_overview(s)

    # ------------------------------------------------------------------
    # Show all params
    # ------------------------------------------------------------------

    def _show_all_params(self, s: WorkflowSession) -> str:
        lines = [tunable_params_menu(s.parsed)]
        lines.append("")
        lines.append("Type 'back' to return to the key parameters view.")
        s.step = "all_params_view"
        return "\n".join(lines)

    def _handle_all_params_view(self, s: WorkflowSession, text: str) -> str:
        s.step = "param_select"
        return self._param_overview(s)

    # ------------------------------------------------------------------
    # Confirm and produce output
    # ------------------------------------------------------------------

    def _go_to_confirm(self, s: WorkflowSession) -> str:
        s.step = "confirm"

        lines = [
            f"Ready to run: {s.selected_entry.name}",
            "",
        ]

        if s.overrides:
            lines.append("Changes from defaults:")
            for (nid, iname), val in s.overrides.items():
                node = s.parsed.nodes[nid]
                label = node.title or node.display_name or node.class_type
                lines.append(f"  [{label}] {iname} = {_format_value(val)}")
        else:
            lines.append("(No changes — running with original values)")

        lines.append("")
        lines.append("1. Confirm and run")
        lines.append("2. Change more parameters")
        lines.append("3. Pick a different workflow")
        lines.append("")
        lines.append("Reply with the number.")
        return "\n".join(lines)

    def _handle_confirm(self, s: WorkflowSession, text: str) -> str:
        low = text.lower().strip()

        if low in ("1", "confirm", "yes", "y", "run", "go"):
            s.step = "done"
            return self._execute(s)
        if low in ("2", "change", "edit"):
            s.step = "param_select"
            return self._param_overview(s)
        if low in ("3", "back", "different"):
            s.step = "browse"
            s.entries = self.entries
            return self._browse_menu(s)

        return "Reply 1 (run), 2 (edit params), or 3 (different workflow)."

    def _execute(self, s: WorkflowSession) -> str:
        """Build the final API workflow with overrides applied."""
        wf = s.parsed
        api = wf.to_api_workflow()

        # Apply overrides
        for (nid, iname), val in s.overrides.items():
            if nid in api and iname in api[nid].get("inputs", {}):
                api[nid]["inputs"][iname] = val

        # Store for external retrieval
        s._final_workflow = api

        n_overrides = len(s.overrides)
        return (
            f"Workflow '{s.selected_entry.name}' ready "
            f"({len(api)} nodes, {n_overrides} override(s)).\n\n"
            f"Call get_final_workflow(user_id) to get the API JSON, "
            f"or connect to ComfyUI to execute."
        )

    def get_final_workflow(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the completed workflow API JSON for a user."""
        s = self._sessions.get(user_id)
        if s and hasattr(s, "_final_workflow"):
            return s._final_workflow
        return None

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _help_text(self) -> str:
        return (
            "Workflow Wizard Help\n"
            "====================\n\n"
            "Commands:\n"
            "  workflows / menu — Browse all workflows\n"
            "  refresh          — Re-scan workflow directories\n"
            "  cancel           — Cancel current operation\n"
            "  help             — Show this message\n\n"
            "Navigation:\n"
            "  - Type a number to pick from any menu\n"
            "  - Type a workflow name to search\n"
            "  - Type 'back' to go up one level\n"
            "  - Type 'run' to execute with current settings\n"
        )


# ── Helpers ─────────────────────────────────────────────────────────────

def _format_value(val: Any, max_len: int = 50) -> str:
    """Format a value for display in menus."""
    if val is None:
        return "(empty)"
    if isinstance(val, bool):
        return "yes" if val else "no"
    if isinstance(val, str):
        if len(val) > max_len:
            return f'"{val[:max_len]}..."'
        return f'"{val}"'
    return str(val)


def _parse_input_value(inp: ParsedInput, text: str) -> Any:
    """Parse user input for a specific ParsedInput."""
    low = text.lower().strip()
    itype = inp.input_type.upper()

    # Choices
    if inp.choices:
        try:
            idx = int(text) - 1
            if 0 <= idx < len(inp.choices):
                return inp.choices[idx]
        except ValueError:
            pass
        for c in inp.choices:
            if low == str(c).lower():
                return c
        return None

    # Boolean
    if itype == "BOOLEAN":
        if low in ("yes", "y", "true", "1", "on"):
            return True
        if low in ("no", "n", "false", "0", "off"):
            return False
        return None

    # Int
    if itype == "INT":
        try:
            val = int(float(text))
            if inp.min_val is not None and val < inp.min_val:
                val = int(inp.min_val)
            if inp.max_val is not None and val > inp.max_val:
                val = int(inp.max_val)
            return val
        except ValueError:
            return None

    # Float
    if itype == "FLOAT":
        try:
            val = float(text)
            if inp.min_val is not None and val < inp.min_val:
                val = inp.min_val
            if inp.max_val is not None and val > inp.max_val:
                val = inp.max_val
            return val
        except ValueError:
            return None

    # String (anything goes)
    return text
