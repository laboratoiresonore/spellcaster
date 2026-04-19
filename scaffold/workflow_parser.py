"""
Universal ComfyUI Workflow Parser
=================================

Parses ANY ComfyUI workflow — whether saved from the web UI (litegraph
format) or exported as API JSON — into a structured, manipulable graph
that the scaffold system can use to:

  1. Present user-tunable parameters (prompts, seeds, model names, etc.)
  2. Let users choose which workflow to run via numbered menus
  3. Override specific inputs and submit to ComfyUI's /prompt API
  4. Generate LLM system prompts describing any workflow

Handles both formats transparently:
  - **Litegraph (UI)**: Has top-level "nodes" array + "links" array.
    Widget values are positional arrays matched against INPUT_TYPES.
  - **API format**: Has numbered node keys with "class_type" + "inputs".
    Values are either literals or [node_id, output_index] references.

The parser can work fully offline (static analysis) or enhanced via
ComfyUI's /object_info endpoint (which returns INPUT_TYPES for every
registered node, including custom nodes with UUID class types).

Zero external dependencies beyond stdlib + urllib.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# ── Node registry cache (populated from /object_info) ──────────────────

_object_info_cache: Optional[Dict[str, Any]] = None


def fetch_object_info(base_url: str = "http://localhost:8188",
                      timeout: int = 10) -> Dict[str, Any]:
    """Fetch the full node registry from a running ComfyUI server.

    Queries the /object_info endpoint to get complete metadata for all registered
    nodes including:
      - input_types: Required and optional input specifications
      - output_types: Output tensor types
      - display_name: Human-readable node name
      - category: Node category (e.g., "loaders", "sampling", "conditioning")
      - description: Optional node documentation

    This is cached globally to avoid repeated network requests.

    Args:
        base_url: ComfyUI server base URL (default: http://localhost:8188)
        timeout: Request timeout in seconds (default: 10)

    Returns:
        Dict keyed by class_type (e.g., "KSampler", "CheckpointLoader")
        with full node specifications. Returns empty dict on network error.
    """
    global _object_info_cache
    if _object_info_cache is not None:
        return _object_info_cache

    url = f"{base_url.rstrip('/')}/object_info"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _object_info_cache = json.loads(resp.read())
    except Exception:
        _object_info_cache = {}
    return _object_info_cache


def clear_object_info_cache():
    """Clear cached /object_info so the next call re-fetches."""
    global _object_info_cache
    _object_info_cache = None


# ── Data classes ────────────────────────────────────────────────────────

@dataclass
class ParsedInput:
    """A single input on a parsed node.

    Represents either:
      1. A literal value the user can change (e.g., text prompt, seed, strength)
      2. A connection to another node's output (is_connection=True)
      3. A tensor/model type that requires runtime wiring

    Used to present tunable parameters in wizard menus and identify which inputs
    should be shown to users (vs. which are internal/wired/tensor types).
    """
    name: str
    value: Any                          # literal value, or None if connected
    input_type: str = "UNKNOWN"         # FLOAT, INT, STRING, BOOLEAN, COMBO, MODEL, etc.
    is_connection: bool = False         # True if wired to another node's output
    source_node_id: Optional[str] = None  # If connected, which node produces this
    source_output_idx: Optional[int] = None  # Which output index from source
    # From object_info (when available):
    default: Any = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[List[str]] = None  # For COMBO types (model names, samplers, etc.)
    tooltip: Optional[str] = None       # Help text from node definition
    required: bool = True               # Whether this input must be provided
    multiline: bool = False             # For STRING inputs, allow newlines

    @property
    def is_user_tunable(self) -> bool:
        """True if this is a literal value a user could change.

        Returns False for:
          - Connections to other nodes (is_connection=True)
          - Tensor types (MODEL, CLIP, VAE, IMAGE, LATENT, etc.)

        These non-tunable inputs are hidden from the wizard menu because
        they require runtime wiring or are handled automatically.
        """
        if self.is_connection:
            return False
        # Tensor / model types are not user-tunable
        TENSOR_TYPES = {
            "MODEL", "CLIP", "VAE", "CONDITIONING", "LATENT", "IMAGE",
            "MASK", "NOISE", "SIGMAS", "GUIDER", "SAMPLER", "CONTROL_NET",
            "CLIP_VISION", "CLIP_VISION_OUTPUT", "STYLE_MODEL", "GLIGEN",
            "UPSCALE_MODEL", "TAESD", "PHOTOMAKER",
        }
        return self.input_type.upper() not in TENSOR_TYPES


@dataclass
class ParsedNode:
    """A single node in a parsed workflow.

    Represents a ComfyUI node instance with all its connections and inputs.
    Handles both active nodes and muted/bypassed nodes.

    Attributes:
        node_id: String identifier (node_index in API format, or UUID in litegraph)
        class_type: The node class (e.g., "KSampler", "CheckpointLoader")
        display_name: Human-readable name from object_info
        title: Optional user-set label in the ComfyUI UI
        category: Node category (e.g., "sampling", "loaders")
        inputs: Dict of input_name -> ParsedInput specs
        outputs: List of output type names
        mode: 0=active, 2=muted, 4=bypassed
        order: Execution order in the ComfyUI graph
    """
    node_id: str
    class_type: str
    display_name: str = ""
    title: str = ""                     # User-set title in the UI
    category: str = ""
    inputs: Dict[str, ParsedInput] = field(default_factory=dict)
    outputs: List[str] = field(default_factory=list)   # output type names
    mode: int = 0                       # 0=active, 2=muted, 4=bypassed
    order: int = 0                      # execution order

    @property
    def is_active(self) -> bool:
        """Whether this node will be executed (mode == 0)."""
        return self.mode == 0

    @property
    def is_output_node(self) -> bool:
        """Heuristic: does this node produce a final user-visible output?

        Returns True for nodes that save/preview images, videos, text, etc.
        Used to identify the 'destination' nodes in a workflow for UX purposes.
        """
        ct = self.class_type.lower()
        OUTPUT_PATTERNS = {
            "saveimage", "previewimage", "savevideo", "previewvideo",
            "vhs_videocombine", "createvideo", "image saver",
            "saveaudio", "showtextoutput", "showtext",
        }
        for pat in OUTPUT_PATTERNS:
            if pat in ct:
                return True
        return False

    @property
    def user_tunable_inputs(self) -> Dict[str, ParsedInput]:
        """Only the inputs a user would reasonably want to tweak."""
        return {k: v for k, v in self.inputs.items() if v.is_user_tunable}


@dataclass
class ParsedWorkflow:
    """A fully parsed ComfyUI workflow.

    This is the central data structure that represents a complete, validated
    ComfyUI workflow after parsing from either:
      1. Litegraph format (from ComfyUI web UI save, has nodes/links array)
      2. API format (from /prompt submission or export, has numbered node keys)

    The ParsedWorkflow provides:
      - Complete node graph with connections
      - User-tunable parameter identification
      - Output node detection
      - Workflow classification (txt2img, img2img, video, etc.)
      - Export back to API format for /prompt submission

    Used by WorkflowWizard to present choices and collect overrides, and by
    the parser to describe workflows to users in human-readable form.
    """
    source_path: Optional[str] = None  # File path if loaded from disk
    source_format: str = "unknown"      # "litegraph" or "api"
    nodes: Dict[str, ParsedNode] = field(default_factory=dict)  # node_id -> ParsedNode
    # Metadata from litegraph format
    groups: List[Dict[str, Any]] = field(default_factory=list)  # Node groups/frames
    extra: Dict[str, Any] = field(default_factory=dict)  # Other metadata

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def active_nodes(self) -> Dict[str, ParsedNode]:
        return {k: v for k, v in self.nodes.items() if v.is_active}

    @property
    def output_nodes(self) -> Dict[str, ParsedNode]:
        return {k: v for k, v in self.nodes.items() if v.is_output_node}

    @property
    def class_types_used(self) -> Set[str]:
        return {n.class_type for n in self.nodes.values()}

    def all_user_tunable(self) -> Dict[str, Dict[str, ParsedInput]]:
        """Returns {node_id: {input_name: ParsedInput}} for all tunable params."""
        result = {}
        for nid, node in self.active_nodes.items():
            tunable = node.user_tunable_inputs
            if tunable:
                result[nid] = tunable
        return result

    def summary(self) -> str:
        """Human-readable summary of the workflow."""
        active = self.active_nodes
        outputs = self.output_nodes
        tunable = self.all_user_tunable()
        total_params = sum(len(v) for v in tunable.values())

        lines = [
            f"Workflow: {self.source_path or '(unnamed)'}",
            f"Format: {self.source_format}",
            f"Nodes: {len(active)} active / {self.node_count} total",
            f"Output nodes: {len(outputs)}",
            f"Tunable parameters: {total_params} across {len(tunable)} nodes",
        ]

        if outputs:
            lines.append("")
            lines.append("Outputs:")
            for nid, node in outputs.items():
                lines.append(f"  [{nid}] {node.display_name or node.class_type}")

        # Classify workflow type
        ct_lower = {n.class_type.lower() for n in active.values()}
        wf_type = _classify_workflow(ct_lower)
        if wf_type:
            lines.insert(1, f"Type: {wf_type}")

        return "\n".join(lines)

    def to_api_workflow(self) -> Dict[str, Any]:
        """Export as ComfyUI API format (ready to POST to /prompt).

        Converts the parsed workflow back to the standard ComfyUI API format:
          - Keys are node IDs (strings)
          - Each value is {class_type: "...", inputs: {...}}
          - Node inputs contain literal values or [source_node_id, output_idx] references
          - Optional node titles are preserved in _meta

        Only active (non-muted, non-bypassed) nodes are included. Muted/bypassed
        nodes are skipped to respect the user's execution intent.

        Returns:
            Dict[str, Any]: Ready to submit to ComfyUI /prompt endpoint
        """
        wf = {}
        for nid, node in self.active_nodes.items():
            inputs = {}
            for iname, inp in node.inputs.items():
                if inp.is_connection:
                    inputs[iname] = [inp.source_node_id, inp.source_output_idx]
                else:
                    inputs[iname] = inp.value
            wf[nid] = {
                "class_type": node.class_type,
                "inputs": inputs,
            }
            if node.title:
                wf[nid]["_meta"] = {"title": node.title}
        return wf

    def to_parameterized(self, param_map: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
        """Export as API workflow with PARAM_ placeholders for tunable inputs.

        param_map: optional {(node_id, input_name): "PARAM_TYPE_NAME"} overrides.
        If not provided, auto-generates placeholder names.
        """
        wf = self.to_api_workflow()
        seen_names: Set[str] = set()

        for nid, node in self.active_nodes.items():
            for iname, inp in node.user_tunable_inputs.items():
                key = (nid, iname)
                if param_map and key in param_map:
                    placeholder = param_map[key]
                else:
                    placeholder = _auto_placeholder(inp, iname, seen_names)
                if nid in wf and iname in wf[nid]["inputs"]:
                    wf[nid]["inputs"][iname] = placeholder

        return wf


# ── Workflow classification ─────────────────────────────────────────────

_WORKFLOW_SIGNATURES = [
    # (label, required_any, required_all)
    # ── Video generation (order matters: most-specific first) ──
    ("LTX2 Image-to-Video", {"ltxvimgtovideo"}, set()),
    ("LTX2 Text-to-Video", {"ltxvbasesampler", "ltxvapplystg", "ltxvscheduler"}, set()),
    ("Text-to-Video", {"wan", "cogvideo", "animatediff", "txt2vid"}, set()),
    ("Image-to-Video", {"img2vid", "i2v", "clipvisionencode"}, {"video"}),
    ("Video-to-Video", {"vid2vid", "loadvideo", "getvideo"}, {"savevideo", "createvideo", "vhs_videocombine"}),
    # ── Video upscale ──
    ("Video Upscale (SeedVR2)", {"seedvr2videoupscaler"}, set()),
    ("Video Upscale (RTX)", {"rtxvideosuperresolution"}, {"vhs_videocombine"}),
    # ── Image tasks ──
    ("Face Swap", {"reactorfaceswap", "faceswap", "insightface"}, set()),
    ("Inpainting", {"inpaint", "setlatentnoisemask", "vaeencodeinpaint"}, set()),
    ("Upscale", {"imageupscalewithmodel", "upscale", "ultimatesdupscale"}, set()),
    ("ControlNet", {"controlnetapply", "controlnetloader", "controlnetapplyadvanced"}, set()),
    ("Image-to-Image", {"loadimage", "vaeencode"}, {"ksampler", "ksampleradvanced", "samplercustomadvanced"}),
    ("Text-to-Image", {"emptylatentimage", "emptysd3latentimage", "emptyflux2latentimage"}, set()),
    # ── Other ──
    ("Audio/Music", {"audio", "music", "song", "tts"}, set()),
    ("Captioning", {"joycaption", "wd14tagger", "florence2", "qwenvl"}, set()),
    ("Style Transfer", {"styletransfer", "ipadapter", "applystyle"}, set()),
    ("LoRA Training", {"loratrain", "trainlora"}, set()),
    ("3D Generation", {"3d", "mesh", "triposr"}, set()),
]


def _classify_workflow(ct_lower: Set[str]) -> str:
    """Classify a workflow by its node types."""
    ct_flat = " ".join(ct_lower)
    for label, any_of, all_of in _WORKFLOW_SIGNATURES:
        if any_of and any(kw in ct_flat for kw in any_of):
            if not all_of or all(kw in ct_flat for kw in all_of):
                return label
    return "General"


# ── Placeholder generation ──────────────────────────────────────────────

_TYPE_MAP = {
    "INT": "INT",
    "FLOAT": "FLOAT",
    "STRING": "STR",
    "BOOLEAN": "BOOL",
    "COMBO": "STR",
}


def _auto_placeholder(inp: ParsedInput, name: str,
                       seen: Set[str]) -> str:
    """Generate a PARAM_TYPE_NAME placeholder for an input."""
    type_prefix = _TYPE_MAP.get(inp.input_type.upper(), "STR")
    clean = re.sub(r"[^a-zA-Z0-9]", "_", name).upper().strip("_")
    base = f"PARAM_{type_prefix}_{clean}"

    if base not in seen:
        seen.add(base)
        return base

    i = 2
    while f"{base}_{i}" in seen:
        i += 1
    result = f"{base}_{i}"
    seen.add(result)
    return result


# ── Format detection and parsing ────────────────────────────────────────

def detect_format(data: dict) -> str:
    """Detect whether a workflow dict is litegraph (UI) or API format."""
    if "nodes" in data and isinstance(data.get("nodes"), list):
        return "litegraph"
    if "last_node_id" in data:
        return "litegraph"
    # API format: numbered string keys with class_type
    for k, v in data.items():
        if isinstance(v, dict) and "class_type" in v:
            return "api"
    return "unknown"


def parse_workflow(data: Union[dict, str, Path],
                   comfyui_url: Optional[str] = None,
                   ) -> ParsedWorkflow:
    """Parse any ComfyUI workflow into a ParsedWorkflow.

    Args:
        data: Workflow dict, JSON string, or path to .json file.
        comfyui_url: Optional ComfyUI server URL for /object_info enrichment.

    Returns:
        ParsedWorkflow with all nodes and inputs resolved.
    """
    source_path = None

    if isinstance(data, (str, Path)):
        path = Path(data)
        if path.exists():
            source_path = str(path)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        elif isinstance(data, str):
            data = json.loads(data)

    fmt = detect_format(data)

    # Optionally fetch object_info for type enrichment
    obj_info = {}
    if comfyui_url:
        obj_info = fetch_object_info(comfyui_url)

    if fmt == "litegraph":
        wf = _parse_litegraph(data, obj_info)
    elif fmt == "api":
        wf = _parse_api(data, obj_info)
    else:
        raise ValueError(f"Unrecognized workflow format (keys: {list(data.keys())[:5]})")

    wf.source_path = source_path
    return wf


# ── Litegraph parser ───────────────────────────────────────────────────

def _parse_litegraph(data: dict, obj_info: dict) -> ParsedWorkflow:
    """Parse a litegraph (UI-saved) workflow."""
    wf = ParsedWorkflow(source_format="litegraph")
    wf.groups = data.get("groups", [])
    wf.extra = data.get("extra", {})

    # Build link index: link_id -> (src_node_id, src_slot, dst_node_id, dst_slot, type_name)
    link_index: Dict[int, Tuple] = {}
    for link in data.get("links", []):
        # link = [link_id, src_node_id, src_slot, dst_node_id, dst_slot, type_name]
        if len(link) >= 6:
            link_index[link[0]] = (
                str(link[1]), link[2],
                str(link[3]), link[4],
                str(link[5]) if link[5] else "UNKNOWN",
            )

    for raw_node in data.get("nodes", []):
        nid = str(raw_node.get("id", ""))
        class_type = raw_node.get("type", "unknown")
        mode = raw_node.get("mode", 0)
        order = raw_node.get("order", 0)
        title = raw_node.get("title", "")

        # Resolve display name from object_info or properties
        display_name = title or ""
        props = raw_node.get("properties", {})
        s_and_r = props.get("Node name for S&R", "")
        if not display_name:
            if class_type in obj_info:
                display_name = obj_info[class_type].get("display_name", class_type)
            elif s_and_r:
                display_name = s_and_r
            else:
                display_name = class_type

        # Get output types
        outputs = []
        for out in raw_node.get("outputs", []):
            outputs.append(out.get("type", "UNKNOWN"))

        # Build inputs from object_info widget order + widgets_values
        inputs = _resolve_litegraph_inputs(
            raw_node, class_type, link_index, obj_info
        )

        category = ""
        if class_type in obj_info:
            category = obj_info[class_type].get("category", "")

        node = ParsedNode(
            node_id=nid,
            class_type=class_type,
            display_name=display_name,
            title=title,
            category=category,
            inputs=inputs,
            outputs=outputs,
            mode=mode,
            order=order,
        )
        wf.nodes[nid] = node

    return wf


def _resolve_litegraph_inputs(raw_node: dict, class_type: str,
                               link_index: Dict[int, Tuple],
                               obj_info: dict) -> Dict[str, ParsedInput]:
    """Resolve litegraph node inputs by combining connections and widget values.

    Litegraph stores:
      - Connections in node["inputs"][i]["link"] (link_id or None)
      - Widget values in node["widgets_values"] (positional array)

    The challenge: widgets_values is positional but we need to map positions
    to input names. We use /object_info to get the ordered INPUT_TYPES, then
    interleave connections and widgets to reconstruct the full input map.
    """
    nid = str(raw_node.get("id", ""))
    inputs: Dict[str, ParsedInput] = {}

    # Step 1: Process explicit connections from input slots
    raw_inputs = raw_node.get("inputs", [])
    connected_names: Set[str] = set()

    for slot in raw_inputs:
        name = slot.get("name", f"input_{slot.get('slot_index', 0)}")
        link_id = slot.get("link")
        input_type = slot.get("type", "UNKNOWN")

        if link_id is not None and link_id in link_index:
            src_nid, src_slot, _, _, link_type = link_index[link_id]
            inputs[name] = ParsedInput(
                name=name,
                value=None,
                input_type=link_type or input_type,
                is_connection=True,
                source_node_id=src_nid,
                source_output_idx=src_slot,
            )
            connected_names.add(name)
        elif link_id is None:
            # Slot exists but not connected — may have a widget fallback
            connected_names.add(name)  # Mark as "slot exists"

    # Step 2: Map widgets_values to input names via object_info
    widgets_values = raw_node.get("widgets_values")
    if widgets_values is None:
        widgets_values = []

    info = obj_info.get(class_type, {})
    if info:
        _map_widgets_with_object_info(
            inputs, widgets_values, info, connected_names, raw_inputs
        )
    else:
        # No object_info — do best-effort positional mapping
        _map_widgets_without_object_info(
            inputs, widgets_values, raw_node, connected_names
        )

    return inputs


def _map_widgets_with_object_info(inputs: Dict[str, ParsedInput],
                                    widgets_values: list,
                                    info: dict,
                                    connected_names: Set[str],
                                    raw_inputs: list) -> None:
    """Map widget values using object_info's INPUT_TYPES ordering.

    ComfyUI's litegraph serialization writes widget values in the order
    they appear in INPUT_TYPES (required first, then optional), skipping
    any input that has a connection slot.  We replicate that ordering to
    map positional values back to names.
    """
    input_info = info.get("input", {})
    required = input_info.get("required", {})
    optional = input_info.get("optional", {})

    # Build ordered list of (name, spec, is_required)
    ordered: List[Tuple[str, Any, bool]] = []
    for name, spec in required.items():
        ordered.append((name, spec, True))
    for name, spec in optional.items():
        ordered.append((name, spec, False))

    # Figure out which names are connection-only (not widgets)
    # Connection-only types don't consume a widgets_values slot
    CONNECTION_ONLY_TYPES = {
        "MODEL", "CLIP", "VAE", "CONDITIONING", "LATENT", "IMAGE",
        "MASK", "NOISE", "SIGMAS", "GUIDER", "SAMPLER", "CONTROL_NET",
        "CLIP_VISION", "CLIP_VISION_OUTPUT", "STYLE_MODEL", "GLIGEN",
        "UPSCALE_MODEL", "TAESD", "PHOTOMAKER",
    }

    widget_idx = 0
    for name, spec, is_required in ordered:
        # Determine the type
        if isinstance(spec, list):
            # Choice/combo
            input_type = "COMBO"
            choices = spec
            type_opts = {}
        elif isinstance(spec, tuple) and len(spec) >= 1:
            if isinstance(spec[0], list):
                input_type = "COMBO"
                choices = spec[0]
                type_opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            elif isinstance(spec[0], str):
                input_type = spec[0]
                choices = None
                type_opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            else:
                input_type = str(spec[0])
                choices = None
                type_opts = {}
        else:
            input_type = str(spec)
            choices = None
            type_opts = {}

        # If this input has a connection, skip it for widget mapping
        # but still record type info if we already parsed the connection
        is_connection_type = input_type.upper() in CONNECTION_ONLY_TYPES

        if name in inputs:
            # Already parsed as connection — enrich with type info
            existing = inputs[name]
            existing.input_type = input_type
            existing.required = is_required
            if choices:
                existing.choices = choices
            _apply_opts(existing, type_opts)
            # Connection types don't consume a widget slot
            if not is_connection_type:
                # Some widgets have a "converted to input" state — check
                # if there's a raw_input slot with this name and a link
                has_slot = any(
                    ri.get("name") == name and ri.get("link") is not None
                    for ri in ([] if not isinstance(inputs, dict) else [])
                )
                if not has_slot:
                    widget_idx += 1
            continue

        if is_connection_type:
            # This is a tensor input that should be connected
            # Don't consume a widget slot
            continue

        # This input maps to a widget — consume next widgets_values slot
        value = None
        if widget_idx < len(widgets_values):
            value = widgets_values[widget_idx]
            widget_idx += 1
        else:
            # Ran out of widget values — use default
            value = type_opts.get("default")
            widget_idx += 1  # Still advance conceptually

        inp = ParsedInput(
            name=name,
            value=value,
            input_type=input_type,
            is_connection=False,
            choices=choices if choices else None,
            required=is_required,
        )
        _apply_opts(inp, type_opts)
        inputs[name] = inp


def _map_widgets_without_object_info(inputs: Dict[str, ParsedInput],
                                       widgets_values: list,
                                       raw_node: dict,
                                       connected_names: Set[str]) -> None:
    """Best-effort widget mapping without object_info.

    Uses heuristics based on value types and common patterns.
    """
    widget_idx = 0
    for i, val in enumerate(widgets_values):
        name = f"widget_{i}"

        # Try to infer type
        if isinstance(val, bool):
            input_type = "BOOLEAN"
        elif isinstance(val, int):
            input_type = "INT"
        elif isinstance(val, float):
            input_type = "FLOAT"
        elif isinstance(val, str):
            input_type = "STRING"
            # Refine: model files
            if val.endswith((".safetensors", ".ckpt", ".gguf", ".pt", ".bin")):
                name = f"model_{i}" if "model" not in name else name
            elif len(val) > 50:
                name = f"text_{i}"
        elif val is None:
            input_type = "UNKNOWN"
        else:
            input_type = "UNKNOWN"

        inp = ParsedInput(
            name=name,
            value=val,
            input_type=input_type,
            is_connection=False,
        )
        inputs[name] = inp


def _apply_opts(inp: ParsedInput, opts: dict) -> None:
    """Apply object_info option dict to a ParsedInput."""
    if not opts or not isinstance(opts, dict):
        return
    if "default" in opts:
        inp.default = opts["default"]
    if "min" in opts:
        inp.min_val = opts["min"]
    if "max" in opts:
        inp.max_val = opts["max"]
    if "step" in opts:
        inp.step = opts["step"]
    if "tooltip" in opts:
        inp.tooltip = opts["tooltip"]
    if "multiline" in opts:
        inp.multiline = opts["multiline"]


# ── API format parser ──────────────────────────────────────────────────

def _parse_api(data: dict, obj_info: dict) -> ParsedWorkflow:
    """Parse an API-format workflow (numbered node keys with class_type)."""
    wf = ParsedWorkflow(source_format="api")

    for nid, node_data in data.items():
        if not isinstance(node_data, dict):
            continue
        class_type = node_data.get("class_type")
        if not class_type:
            continue

        display_name = class_type
        category = ""
        meta = node_data.get("_meta", {})
        title = meta.get("title", "")

        if class_type in obj_info:
            display_name = obj_info[class_type].get("display_name", class_type)
            category = obj_info[class_type].get("category", "")

        if title:
            display_name = title

        # Parse inputs
        raw_inputs = node_data.get("inputs", {})
        inputs = {}
        for iname, val in raw_inputs.items():
            if isinstance(val, list) and len(val) == 2:
                # Connection: [node_id, output_index]
                src_nid, src_idx = val
                inputs[iname] = ParsedInput(
                    name=iname,
                    value=None,
                    is_connection=True,
                    source_node_id=str(src_nid),
                    source_output_idx=int(src_idx),
                )
            else:
                inp = ParsedInput(
                    name=iname,
                    value=val,
                    input_type=_infer_type(val),
                    is_connection=False,
                )
                inputs[iname] = inp

        # Enrich from object_info
        if class_type in obj_info:
            _enrich_api_inputs(inputs, obj_info[class_type])

        # Determine outputs from object_info
        outputs = []
        if class_type in obj_info:
            outputs = list(obj_info[class_type].get("output", []))

        node = ParsedNode(
            node_id=str(nid),
            class_type=class_type,
            display_name=display_name,
            title=title,
            category=category,
            inputs=inputs,
            outputs=outputs,
        )
        wf.nodes[str(nid)] = node

    return wf


def _infer_type(val: Any) -> str:
    """Infer ComfyUI type from a Python value."""
    if isinstance(val, bool):
        return "BOOLEAN"
    if isinstance(val, int):
        return "INT"
    if isinstance(val, float):
        return "FLOAT"
    if isinstance(val, str):
        return "STRING"
    return "UNKNOWN"


def _enrich_api_inputs(inputs: Dict[str, ParsedInput],
                        info: dict) -> None:
    """Add type/range/choices from object_info to API-parsed inputs."""
    input_info = info.get("input", {})
    all_specs = {}
    all_specs.update(input_info.get("required", {}))
    all_specs.update(input_info.get("optional", {}))

    for name, inp in inputs.items():
        if name not in all_specs:
            continue
        spec = all_specs[name]

        if isinstance(spec, list):
            inp.input_type = "COMBO"
            inp.choices = spec
        elif isinstance(spec, tuple) and len(spec) >= 1:
            if isinstance(spec[0], list):
                inp.input_type = "COMBO"
                inp.choices = spec[0]
                if len(spec) > 1 and isinstance(spec[1], dict):
                    _apply_opts(inp, spec[1])
            elif isinstance(spec[0], str):
                inp.input_type = spec[0]
                if len(spec) > 1 and isinstance(spec[1], dict):
                    _apply_opts(inp, spec[1])

        inp.required = name in input_info.get("required", {})


# ── Workflow discovery ─────────────────────────────────────────────────

@dataclass
class WorkflowEntry:
    """A discovered workflow file."""
    path: Path
    name: str
    category: str               # subdirectory name, or "root"
    node_count: int = 0
    workflow_type: str = ""     # auto-classified type
    class_types: Set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.name,
            "category": self.category,
            "node_count": self.node_count,
            "workflow_type": self.workflow_type,
        }


def discover_workflows(search_dirs: Optional[List[Union[str, Path]]] = None,
                        ) -> List[WorkflowEntry]:
    """Scan directories for ComfyUI workflow JSON files.

    Default search paths include ComfyUI's user workflow directory.

    Returns:
        Sorted list of WorkflowEntry objects.
    """
    if search_dirs is None:
        search_dirs = _default_search_dirs()

    entries: List[WorkflowEntry] = []
    seen_paths: Set[str] = set()

    for search_dir in search_dirs:
        search_dir = Path(search_dir)
        if not search_dir.exists():
            continue

        for json_path in search_dir.rglob("*.json"):
            # Skip metadata sidecars
            if json_path.name.endswith(".meta.json"):
                continue

            resolved = str(json_path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            fmt = detect_format(data)
            if fmt == "unknown":
                continue

            # Quick parse for classification
            ct_set: Set[str] = set()
            node_count = 0

            if fmt == "litegraph":
                nodes = data.get("nodes", [])
                node_count = len(nodes)
                ct_set = {n.get("type", "") for n in nodes}
            elif fmt == "api":
                for k, v in data.items():
                    if isinstance(v, dict) and "class_type" in v:
                        node_count += 1
                        ct_set.add(v["class_type"])

            # Determine category from directory structure
            try:
                rel = json_path.relative_to(search_dir)
                parts = rel.parts
                category = parts[0] if len(parts) > 1 else "root"
            except ValueError:
                category = "root"

            ct_lower = {t.lower() for t in ct_set}
            wf_type = _classify_workflow(ct_lower)

            entry = WorkflowEntry(
                path=json_path,
                name=json_path.stem,
                category=category,
                node_count=node_count,
                workflow_type=wf_type,
                class_types=ct_set,
            )
            entries.append(entry)

    entries.sort(key=lambda e: (e.category, e.name.lower()))
    return entries


def classify_workflow_data(data: dict) -> tuple[int, str, Set[str]]:
    """Return (node_count, workflow_type, class_types) for a parsed
    workflow JSON dict.

    Public helper so callers outside workflow_parser.py (notably the
    Guild's remote-ComfyUI workflow proxy in tavern/server.py) get
    the same classification as discover_workflows() does for local
    files, without re-implementing the format-detection + type rules.
    Returns (0, "unknown", set()) when the format can't be detected.
    """
    if not isinstance(data, dict):
        return (0, "unknown", set())
    fmt = detect_format(data)
    ct_set: Set[str] = set()
    node_count = 0
    if fmt == "litegraph":
        nodes = data.get("nodes", []) or []
        node_count = len(nodes)
        ct_set = {n.get("type", "") for n in nodes if isinstance(n, dict)}
    elif fmt == "api":
        for v in data.values():
            if isinstance(v, dict) and "class_type" in v:
                node_count += 1
                ct_set.add(v["class_type"])
    else:
        return (0, "unknown", set())
    ct_lower = {t.lower() for t in ct_set if t}
    wf_type = _classify_workflow(ct_lower)
    return (node_count, wf_type, ct_set)


def _default_search_dirs() -> List[Path]:
    """Find ComfyUI's user workflow directories and bundled scaffold workflows."""
    candidates = [
        # Bundled workflow templates shipped with Spellcaster scaffold
        Path(__file__).resolve().parent / "workflows",
        # ComfyUI user workflow directories
        Path(__file__).resolve().parent.parent.parent / "ComfyUI" / "user" / "default" / "workflows",
        Path.home() / "ComfyUI" / "user" / "default" / "workflows",
    ]
    # Also check COMFYUI_PATH env var if set
    env_path = os.environ.get("COMFYUI_PATH")
    if env_path:
        candidates.append(Path(env_path) / "user" / "default" / "workflows")
    return [p for p in candidates if p.exists()]


# ── Menu generation for scaffold integration ───────────────────────────

def workflow_menu(entries: List[WorkflowEntry],
                   category_filter: Optional[str] = None) -> str:
    """Generate a numbered menu of available workflows.

    Returns text suitable for display in a chatbot or terminal.
    """
    if category_filter:
        filtered = [e for e in entries if e.category.lower() == category_filter.lower()]
    else:
        filtered = entries

    if not filtered:
        return "No workflows found."

    # Group by category
    cats: Dict[str, List[WorkflowEntry]] = OrderedDict()
    for e in filtered:
        cats.setdefault(e.category, []).append(e)

    lines = ["Available Workflows", "=" * 40, ""]
    idx = 1
    index_map: Dict[int, WorkflowEntry] = {}

    for cat, wfs in cats.items():
        lines.append(f"── {cat} ──")
        for wf in wfs:
            type_tag = f" [{wf.workflow_type}]" if wf.workflow_type else ""
            lines.append(f"  {idx}. {wf.name}{type_tag}  ({wf.node_count} nodes)")
            index_map[idx] = wf
            idx += 1
        lines.append("")

    lines.append(f"{idx}. Cancel")
    return "\n".join(lines)


def tunable_params_menu(wf: ParsedWorkflow) -> str:
    """Generate a numbered menu of all tunable parameters in a workflow.

    Groups params by node for clarity.
    """
    tunable = wf.all_user_tunable()
    if not tunable:
        return "This workflow has no user-tunable parameters."

    lines = ["Tunable Parameters", "=" * 40, ""]
    idx = 1

    for nid, params in tunable.items():
        node = wf.nodes[nid]
        lines.append(f"── {node.display_name or node.class_type} [{nid}] ──")

        for pname, inp in params.items():
            hint = ""
            if inp.choices:
                hint = f" [{' / '.join(str(c) for c in inp.choices[:5])}]"
                if len(inp.choices) > 5:
                    hint = hint[:-1] + f" +{len(inp.choices)-5} more]"
            elif inp.input_type in ("FLOAT", "INT"):
                parts = []
                if inp.value is not None:
                    parts.append(f"current={inp.value}")
                if inp.min_val is not None:
                    parts.append(f"min={inp.min_val}")
                if inp.max_val is not None:
                    parts.append(f"max={inp.max_val}")
                if parts:
                    hint = f" ({', '.join(parts)})"
            elif inp.input_type == "STRING" and inp.value:
                preview = str(inp.value)[:40]
                if len(str(inp.value)) > 40:
                    preview += "..."
                hint = f' = "{preview}"'
            elif inp.input_type == "BOOLEAN":
                hint = f" [{'yes' if inp.value else 'no'}]"

            tip = f"  — {inp.tooltip}" if inp.tooltip else ""
            req = "" if inp.required else " (optional)"
            lines.append(f"  {idx}. {pname}: {inp.input_type}{hint}{req}{tip}")
            idx += 1
        lines.append("")

    lines.append(f"{idx}. Keep all as-is (use current values)")
    return "\n".join(lines)


# ── Convenience: parse + summarize ─────────────────────────────────────

def quick_parse(path: Union[str, Path],
                comfyui_url: Optional[str] = None) -> str:
    """Parse a workflow and return a human-readable summary."""
    wf = parse_workflow(path, comfyui_url=comfyui_url)
    return wf.summary()
