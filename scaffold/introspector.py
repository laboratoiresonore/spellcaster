"""
Node introspector — auto-discovers Spellcaster node classes and extracts
every parameter, type, default, range, and tooltip into structured specs.

Works two ways:
  1. Live import (when running inside ComfyUI or with it importable)
  2. AST parse (standalone — reads .py files without importing)

This means the scaffold can generate menus even on a machine that
doesn't have ComfyUI installed.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ParamSpec:
    """One input parameter of a node."""
    name: str
    type: str                         # CONDITIONING, FLOAT, INT, BOOLEAN, STRING, MASK, CLIP, Choice
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[List[str]] = None  # for combo/choice params
    tooltip: Optional[str] = None
    required: bool = True
    multiline: bool = False

    def menu_line(self, index: int) -> str:
        """Format as a numbered menu line for a chatbot."""
        hint = ""
        if self.choices:
            hint = f" [{' / '.join(self.choices)}]"
        elif self.type == "FLOAT":
            rng = f" ({self.min}–{self.max})" if self.min is not None else ""
            hint = f" [default {self.default}]{rng}"
        elif self.type == "INT":
            rng = f" ({self.min}–{self.max})" if self.min is not None else ""
            hint = f" [default {self.default}]{rng}"
        elif self.type == "BOOLEAN":
            hint = f" [default {'yes' if self.default else 'no'}]"
        elif self.type == "STRING":
            hint = " [text]"

        tip = f"  — {self.tooltip}" if self.tooltip else ""
        req = "" if self.required else " (optional)"
        return f"{index}. {self.name}{hint}{req}{tip}"


@dataclass
class NodeSpec:
    """Full specification of one Spellcaster node."""
    class_name: str
    display_name: str
    category: str
    function: str
    description: str
    return_types: List[str] = field(default_factory=list)
    return_names: Optional[List[str]] = None
    required_params: List[ParamSpec] = field(default_factory=list)
    optional_params: List[ParamSpec] = field(default_factory=list)

    @property
    def all_user_params(self) -> List[ParamSpec]:
        """Params a user can set (excludes tensor/model inputs)."""
        skip = {"CONDITIONING", "CLIP", "MASK", "MODEL", "LATENT",
                "VAE", "IMAGE", "NOISE", "SIGMAS", "GUIDER", "SAMPLER"}
        return [
            p for p in self.required_params + self.optional_params
            if p.type not in skip
        ]

    def menu_block(self) -> str:
        """Full parameter menu for chatbot display."""
        lines = [f"--- {self.display_name} ---", ""]
        if self.description:
            lines.append(self.description)
            lines.append("")

        user_params = self.all_user_params
        if not user_params:
            lines.append("(No user-configurable parameters — uses defaults.)")
            return "\n".join(lines)

        lines.append("Parameters:")
        for i, p in enumerate(user_params, 1):
            lines.append(p.menu_line(i))
        lines.append("")
        lines.append(f"{len(user_params) + 1}. Use all defaults")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Live import discovery (inside ComfyUI environment)
# ---------------------------------------------------------------------------

def _discover_live() -> Dict[str, NodeSpec]:
    """Import the parent package and introspect classes directly."""
    # The parent package is one level up from scaffold/
    parent = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(parent.parent))
    try:
        pkg = importlib.import_module(parent.name)
    except ImportError:
        return {}

    mappings = getattr(pkg, "NODE_CLASS_MAPPINGS", {})
    display = getattr(pkg, "NODE_DISPLAY_NAME_MAPPINGS", {})

    specs: Dict[str, NodeSpec] = {}
    for cls_key, cls in mappings.items():
        spec = _class_to_spec(cls, cls_key, display.get(cls_key, cls_key))
        specs[cls_key] = spec
    return specs


def _class_to_spec(cls, cls_key: str, display_name: str) -> NodeSpec:
    """Convert a live ComfyUI node class to a NodeSpec."""
    input_types = cls.INPUT_TYPES() if callable(getattr(cls, "INPUT_TYPES", None)) else {}
    category = getattr(cls, "CATEGORY", "unknown")
    func = getattr(cls, "FUNCTION", "execute")
    rtypes = getattr(cls, "RETURN_TYPES", ())
    rnames = getattr(cls, "RETURN_NAMES", None)
    desc = (cls.__doc__ or "").strip().split("\n")[0]

    req_params = _parse_input_group(input_types.get("required", {}), required=True)
    opt_params = _parse_input_group(input_types.get("optional", {}), required=False)

    return NodeSpec(
        class_name=cls_key,
        display_name=display_name,
        category=category,
        function=func,
        description=desc,
        return_types=list(rtypes),
        return_names=list(rnames) if rnames else None,
        required_params=req_params,
        optional_params=opt_params,
    )


def _parse_input_group(group: dict, required: bool) -> List[ParamSpec]:
    params = []
    for name, spec in group.items():
        p = _parse_one_param(name, spec, required)
        if p:
            params.append(p)
    return params


def _parse_one_param(name: str, spec, required: bool) -> Optional[ParamSpec]:
    """Parse a single ComfyUI INPUT_TYPES entry into a ParamSpec."""
    if isinstance(spec, tuple) and len(spec) >= 1:
        type_or_list = spec[0]
        opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    elif isinstance(spec, list):
        # Choice list like ["linear", "dampen", ...]
        return ParamSpec(
            name=name, type="Choice", choices=spec, required=required,
            default=spec[0] if spec else None,
        )
    elif isinstance(spec, str):
        return ParamSpec(name=name, type=spec, required=required)
    else:
        return ParamSpec(name=name, type=str(spec), required=required)

    if isinstance(type_or_list, list):
        return ParamSpec(
            name=name, type="Choice", choices=type_or_list, required=required,
            default=opts.get("default", type_or_list[0] if type_or_list else None),
            tooltip=opts.get("tooltip"),
        )

    return ParamSpec(
        name=name,
        type=type_or_list,
        default=opts.get("default"),
        min=opts.get("min"),
        max=opts.get("max"),
        step=opts.get("step"),
        choices=None,
        tooltip=opts.get("tooltip"),
        required=required,
        multiline=opts.get("multiline", False),
    )


# ---------------------------------------------------------------------------
# AST-based discovery (standalone, no ComfyUI needed)
# ---------------------------------------------------------------------------

def _discover_ast() -> Dict[str, NodeSpec]:
    """Parse .py files with AST to extract node specs without importing."""
    parent = Path(__file__).resolve().parent.parent
    specs: Dict[str, NodeSpec] = {}

    # Read __init__.py for mappings
    init_path = parent / "__init__.py"
    if not init_path.exists():
        return specs

    init_src = init_path.read_text(encoding="utf-8", errors="replace")
    class_map = _extract_dict_from_source(init_src, "NODE_CLASS_MAPPINGS")
    display_map = _extract_dict_from_source(init_src, "NODE_DISPLAY_NAME_MAPPINGS")

    # Scan all .py files for classes
    for py_file in parent.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            cls_name = node.name
            if cls_name not in class_map and cls_name not in display_map:
                # Check if it looks like a ComfyUI node
                has_input_types = any(
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "INPUT_TYPES"
                    for item in node.body
                )
                if not has_input_types:
                    continue

            display = display_map.get(cls_name, cls_name)
            spec = _ast_class_to_spec(node, src, cls_name, display)
            specs[cls_name] = spec

    return specs


def _ast_class_to_spec(cls_node: ast.ClassDef, source: str,
                       cls_name: str, display_name: str) -> NodeSpec:
    """Extract a NodeSpec from an AST class definition."""
    category = "unknown"
    func = "execute"
    rtypes = []
    rnames = None
    desc = ast.get_docstring(cls_node) or ""
    desc = desc.strip().split("\n")[0] if desc else ""

    for item in cls_node.body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    if target.id == "CATEGORY" and isinstance(item.value, ast.Constant):
                        category = item.value.value
                    elif target.id == "FUNCTION" and isinstance(item.value, ast.Constant):
                        func = item.value.value
                    elif target.id == "RETURN_TYPES":
                        rtypes = _extract_tuple_strings(item.value)
                    elif target.id == "RETURN_NAMES":
                        rnames = _extract_tuple_strings(item.value)

    # Extract INPUT_TYPES by evaluating the dict portion from source
    req, opt = _extract_input_types_from_source(cls_node, source)

    return NodeSpec(
        class_name=cls_name,
        display_name=display_name,
        category=category,
        function=func,
        description=desc,
        return_types=rtypes,
        return_names=rnames,
        required_params=req,
        optional_params=opt,
    )


def _extract_tuple_strings(node) -> List[str]:
    """Extract string elements from a Tuple AST node."""
    if isinstance(node, ast.Tuple):
        return [
            elt.value for elt in node.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
    return []


def _extract_input_types_from_source(cls_node: ast.ClassDef,
                                     source: str) -> tuple:
    """Best-effort extraction of INPUT_TYPES return dict from source text."""
    # Find the INPUT_TYPES method and get its source range
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == "INPUT_TYPES":
                # Extract source lines
                start = item.lineno - 1
                end = item.end_lineno if hasattr(item, "end_lineno") else start + 50
                lines = source.split("\n")[start:end]
                method_src = "\n".join(lines)

                # Try to safely evaluate the return dict
                return _parse_input_types_text(method_src)
    return [], []


def _parse_input_types_text(method_src: str) -> tuple:
    """Parse INPUT_TYPES method source to extract required/optional params.

    Uses regex-based extraction since the dicts often contain
    non-literal expressions (function calls, etc.) that ast.literal_eval
    can't handle.
    """
    req_params = []
    opt_params = []

    # Find "required" and "optional" blocks
    for section, is_required in [("required", True), ("optional", False)]:
        # Look for "required": { ... } or "optional": { ... }
        pattern = rf'"{section}"\s*:\s*\{{'
        match = re.search(pattern, method_src)
        if not match:
            pattern = rf"'{section}'\s*:\s*\{{"
            match = re.search(pattern, method_src)
        if not match:
            continue

        # Extract parameter names and their basic info from the block
        # This is a simplified parser that gets name, type, and opts
        block_start = match.end()
        brace_depth = 1
        pos = block_start
        while pos < len(method_src) and brace_depth > 0:
            if method_src[pos] == "{":
                brace_depth += 1
            elif method_src[pos] == "}":
                brace_depth -= 1
            pos += 1
        block = method_src[block_start:pos - 1]

        # Extract individual params: "name": (TYPE, {opts})
        param_pattern = r'"(\w+)"\s*:\s*\(\s*"(\w+)"'
        for pm in re.finditer(param_pattern, block):
            pname, ptype = pm.group(1), pm.group(2)
            # Try to find default, min, max, step, tooltip in the opts dict
            opts = _extract_param_opts(block, pm.end())
            p = ParamSpec(
                name=pname, type=ptype, required=is_required,
                default=opts.get("default"),
                min=opts.get("min"),
                max=opts.get("max"),
                step=opts.get("step"),
                tooltip=opts.get("tooltip"),
                multiline=opts.get("multiline", False),
            )
            if is_required:
                req_params.append(p)
            else:
                opt_params.append(p)

        # Also look for choice lists: "name": (["opt1", "opt2"], {opts})
        choice_pattern = r'"(\w+)"\s*:\s*\(\s*\['
        for pm in re.finditer(choice_pattern, block):
            pname = pm.group(1)
            # Extract the list contents
            list_start = pm.end() - 1
            list_end = block.find("]", list_start)
            if list_end > 0:
                list_src = block[list_start:list_end + 1]
                choices = re.findall(r'"([^"]*)"', list_src)
                opts = _extract_param_opts(block, list_end)
                p = ParamSpec(
                    name=pname, type="Choice", required=is_required,
                    choices=choices,
                    default=opts.get("default", choices[0] if choices else None),
                    tooltip=opts.get("tooltip"),
                )
                if is_required:
                    req_params.append(p)
                else:
                    opt_params.append(p)

    return req_params, opt_params


def _extract_param_opts(block: str, start_pos: int) -> dict:
    """Extract {default: ..., min: ..., ...} from the text after a param type."""
    opts = {}
    # Look for the opts dict — but stop at the next param boundary to avoid
    # bleeding into the next parameter's defaults
    search_end = start_pos + 300
    # Find next param definition: "name": ("TYPE" or "name": ([
    # Must match the pattern of a ComfyUI param, not an opts key like "default"
    next_param = re.search(r'\n\s+"(\w+)"\s*:\s*\(\s*[\["]', block[start_pos + 1:start_pos + 300])
    if next_param:
        search_end = start_pos + 1 + next_param.start()
    search = block[start_pos:search_end]

    for key in ("default", "min", "max", "step"):
        # Match "key": number_or_bool or "key": "string_value"
        m = re.search(rf'"{key}"\s*:\s*([-\d.eE]+|True|False|"[^"]*")', search)
        if m:
            val = m.group(1)
            if val == "True":
                opts[key] = True
            elif val == "False":
                opts[key] = False
            elif val.startswith('"') and val.endswith('"'):
                opts[key] = val[1:-1]
            elif "." in val or "e" in val.lower():
                opts[key] = float(val)
            else:
                opts[key] = int(val)

    m = re.search(r'"tooltip"\s*:\s*"([^"]*)"', search)
    if m:
        opts["tooltip"] = m.group(1)

    m = re.search(r'"multiline"\s*:\s*(True|False)', search)
    if m:
        opts["multiline"] = m.group(1) == "True"

    return opts


def _extract_dict_from_source(source: str, var_name: str) -> dict:
    """Extract a simple {str: str/identifier} dict assignment from source."""
    result = {}
    pattern = rf'{var_name}\s*=\s*\{{'
    m = re.search(pattern, source)
    if not m:
        return result
    start = m.end()
    brace_depth = 1
    pos = start
    while pos < len(source) and brace_depth > 0:
        if source[pos] == "{":
            brace_depth += 1
        elif source[pos] == "}":
            brace_depth -= 1
        pos += 1
    block = source[start:pos - 1]
    # Extract "Key": Value pairs — Value might be a class ref or string
    for pm in re.finditer(r'"(\w+)"\s*:\s*(?:"([^"]*)"|(\w+))', block):
        key = pm.group(1)
        val = pm.group(2) if pm.group(2) is not None else pm.group(3)
        result[key] = val
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover_nodes() -> Dict[str, NodeSpec]:
    """Discover all Spellcaster nodes. Tries live import first, falls back to AST."""
    try:
        specs = _discover_live()
        if specs:
            return specs
    except Exception:
        pass
    return _discover_ast()


def dump_manifest(path: Optional[str] = None) -> str:
    """Dump all discovered nodes as JSON (for external tools to consume)."""
    specs = discover_nodes()
    data = {k: v.to_dict() for k, v in specs.items()}
    text = json.dumps(data, indent=2, default=str)
    if path:
        Path(path).write_text(text)
    return text
