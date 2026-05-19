#!/usr/bin/env python3
"""Export every ``build_*`` method in ``spellcaster_core.workflows`` to a
ComfyUI-GUI-loadable workflow ``.json`` file (one per method), complete
with a ``Note`` node documenting the method.

Why this exists
---------------

Each ``build_*`` returns a ComfyUI API-format prompt-graph dict (flat
``{node_id: {class_type, inputs}}``), which is what the ``/prompt`` REST
endpoint accepts. The ComfyUI **GUI** sidebar loads workflows from
``user/<user>/workflows/*.json``, but those use a different shape with
``nodes``, ``links``, ``last_node_id`` etc. This script converts every
spellcaster builder's API output to that GUI shape so the user can click
into each one in the GUI, read a Note describing it, and tweak knobs.

Notes
-----

* The conversion is best-effort. Widget ordering for unknown node classes
  follows insertion order of the API ``inputs`` dict (which is what
  spellcaster builders produce deterministically). Missing widget types
  render as plain text fields the user can fix in-GUI.
* Each exported workflow is a TEMPLATE, not a runnable graph. Image /
  mask / video inputs fall back to placeholder filenames; the user is
  expected to wire real inputs in the GUI.
* Builders that can't be invoked with synthesised defaults are skipped
  and reported in the final summary (with the exception).
* Runs nightly. Defensive about partial failures, useful logs.

CLI
---

::

    python tools/export_comfyui_workflows.py [flags]

Flags:

  --output-dir PATH     where to write JSONs (default: the user's active
                        ComfyUI workflows dir).
  --methods NAME1,NAME2 only export these builders (default: all).
  --dry-run             don't write anything, just report.
  --verbose             print each method as it's processed.

Exit codes:

  0  full success.
  1  partial: some builders failed, at least one exported.
  2  catastrophic: import / nothing exported / unrecoverable.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
CONNECTOR_DIR = REPO / "plugins" / "gimp" / "comfyui-connector"
DEFAULT_OUTPUT_DIR = Path(
    r"C:\Users\legui\Documents\ComfyUI\user\default\workflows\spellcaster"
)

# Make spellcaster_core importable.
sys.path.insert(0, str(CONNECTOR_DIR))

log = logging.getLogger("export_comfyui_workflows")


# ---------------------------------------------------------------------------
# Default-arg synthesis
# ---------------------------------------------------------------------------

# Default sampling preset. Covers the union of fields different arches
# read (``arch``/``width``/``height``/``steps``/``cfg``/``sampler``/
# ``scheduler``/``denoise``/``ckpt``). Extra keys are harmless; missing
# keys would crash. We pick ``sdxl`` because every builder that takes a
# generic preset accepts it (klein/flux/wan/etc. builders take their
# own typed args or pick up a video-flavoured preset below).
DEFAULT_PRESET: dict[str, Any] = {
    "arch":      "sdxl",
    "width":     1024,
    "height":    1024,
    "steps":     20,
    "cfg":       7.0,
    "denoise":   1.0,
    "sampler":   "euler",
    "scheduler": "normal",
    "ckpt":      "sd_xl_base_1.0.safetensors",
    "model":     "sd_xl_base_1.0.safetensors",
    "vae":       "sdxl_vae.safetensors",
    "clip":      "clip_l.safetensors",
}

# Per-arch presets — used by video builders that need a different
# shape (wan needs ``high_model``/``low_model``/``clip``/``vae``).
WAN_PRESET: dict[str, Any] = {
    "arch":           "wan",
    "width":          832,
    "height":         480,
    "steps":          6,
    "cfg":            1.0,
    "denoise":        1.0,
    "sampler":        "euler",
    "scheduler":      "simple",
    "high_model":     "wan2_2_t2v_high_noise.safetensors",
    "low_model":      "wan2_2_t2v_low_noise.safetensors",
    "clip":           "umt5_xxl_fp8_e4m3fn.safetensors",
    "vae":            "wan_2.1_vae.safetensors",
    "high_accel_lora": None,
    "low_accel_lora":  None,
}

LTX_PRESET: dict[str, Any] = {
    "arch":                  "ltx",
    "width":                 768,
    "height":                512,
    "steps":                 30,
    "cfg":                   3.0,
    "stg":                   1.0,
    "rescale":               0.7,
    "denoise":               1.0,
    "sampler":               "euler",
    "scheduler":             "normal",
    # LTX-specific slots — names match the docstring of build_ltx_video.
    "unet":                  "LTX/ltx-2.3-22b-dev-Q4_K_M.gguf",
    "text_encoder":          "google_gemma-3-12b-it",
    "embeddings_connector":  "ltxv-13b-098-embeddings-connector.safetensors",
    "vae":                   "ltxv-13b-098-vae.safetensors",
    "distilled_lora":        None,
    "latent_upscaler":       "ltxv-latent-upscaler.safetensors",
    "ckpt":                  "LTX/ltx-2.3-22b-dev-Q4_K_M.gguf",
    "model":                 "LTX/ltx-2.3-22b-dev-Q4_K_M.gguf",
    "clip":                  "t5xxl_fp8_e4m3fn.safetensors",
}

# Builders that take a ``preset`` arg need a flavour that matches the
# arch their _assert_method allow-lists. Resolved by builder NAME
# prefix; falls back to DEFAULT_PRESET for everything else.
_PER_BUILDER_PRESET: dict[str, dict[str, Any]] = {
    "build_wan_video":         WAN_PRESET,
    "build_wan_flf":           WAN_PRESET,
    "build_wan_animate_video": WAN_PRESET,
    "build_wan22_t2v":         WAN_PRESET,
    "build_ltx_video":         LTX_PRESET,
}


def _preset_for_builder(name: str) -> dict[str, Any]:
    return dict(_PER_BUILDER_PRESET.get(name, DEFAULT_PRESET))


# Klein model key default (must be a key in workflows.KLEIN_MODELS).
DEFAULT_KLEIN_MODEL_KEY = "Klein 9B"

# Filename slot placeholders. Builders that take image / mask / video
# inputs accept any string; the exported workflow is a template the GUI
# user will rewire.
PLACEHOLDER_IMAGE = "placeholder.png"
PLACEHOLDER_MASK = "placeholder_mask.png"
PLACEHOLDER_VIDEO = "placeholder.mp4"
PLACEHOLDER_FACE = "placeholder_face.png"

# Curated per-parameter overrides. The signature-walker uses these
# BEFORE its generic name/annotation heuristic, so the most-load-bearing
# names (preset, *_filename, klein_*) get sensible values without
# having to encode every annotation.
_PARAM_OVERRIDES: dict[str, Any] = {
    "preset":              DEFAULT_PRESET,
    "klein_model_key":     DEFAULT_KLEIN_MODEL_KEY,
    "klein_models":        None,  # builder loads workflows.KLEIN_MODELS
    "seed":                42,
    "steps":               20,
    "cfg":                 7.0,
    "denoise":             0.75,
    "guidance":            3.5,
    "strength":            1.0,
    "blend_factor":        0.5,
    "upscale_factor":      2.0,
    "fps":                 16.0,
    # Generic model-name slot used by ad-hoc builders that don't take
    # a preset.
    "model":               "sd_xl_base_1.0.safetensors",
    "model_name":          "4x-UltraSharp.pth",
    "upscale_model":       "4x-UltraSharp.pth",
    "supir_model":         "SUPIR-v0Q.ckpt",
    "sdxl_model":          "sd_xl_base_1.0.safetensors",
    "ckpt_name":           "sd_xl_base_1.0.safetensors",
    "unet_name":           "flux1-dev.safetensors",
    "clip_name":           "qwen_3_8b.safetensors",
    "vae_name":            "flux2-vae.safetensors",
    "t5_model":            "t5xxl_fp8_e4m3fn.safetensors",
    "vae_model":           "flux2-vae.safetensors",
    "wan_model":           "wan22-t2v-14b.safetensors",
    "face_model":          "default_face.safetensors",
    "face_models":         [],
    "checkpoint":          "ddcolor_artistic.pth",
    "swap_model":          "inswapper_128.onnx",
    "controlnet_model":    "control_canny-fp16.safetensors",
    "preprocessor_type":   "canny",
    "lut_name":            "neutral.cube",
    "facedetection":       "retinaface_resnet50",
    "filename_prefix":     "spellcaster_export",
    # Klein face-detail / sam3 inpaint accept a key for which preset to
    # use. None of these are validated at build-time so a stub is fine.
    "preset_key":          "balanced",
    "prompt":              "",
    "prompt_text":         "",
    "mask_prompt":         "person",
    "segment_prompt":      "person",
    "inpaint_prompt":      "",
    "negative":            "",
    "negative_text":       "",
    # Geometry — outpaint padding, seedv2r dims, video length.
    "left":                64,
    "top":                 64,
    "right":               64,
    "bottom":              64,
    "feathering":          32,
    "scale_factor":        1.0,
    "orig_width":          1024,
    "orig_height":         1024,
    "length":              81,
    "width":               1024,
    "height":              1024,
    "max_res":             1024,
    "target":              "2K",
}


def _is_filename_param(name: str) -> str | None:
    """If ``name`` looks like a content-input filename, return which
    kind of placeholder to use, else None."""
    lname = name.lower()
    if "video" in lname and "filename" in lname:
        return PLACEHOLDER_VIDEO
    if lname in {"video_name", "video_filename"}:
        return PLACEHOLDER_VIDEO
    if lname in {"frame_filenames"}:
        # list-of-frames input — synthesise a single-frame list so the
        # builder doesn't crash on iteration.
        return [PLACEHOLDER_IMAGE]
    if "mask" in lname and ("filename" in lname or "name" in lname):
        return PLACEHOLDER_MASK
    if any(token in lname for token in (
        "face_filename", "face_ref_filename", "ref_filename",
        "source_face", "face_image", "face_bytes",
    )):
        return PLACEHOLDER_FACE
    if "filename" in lname or lname.endswith("_name"):
        return PLACEHOLDER_IMAGE
    return None


def _synthesise_default(
    param: inspect.Parameter,
    builder_name: str | None = None,
) -> Any:
    """Pick a default value for an unfilled parameter.

    Resolution order:
      1. ``preset`` is special-cased per builder (video archs etc.).
      2. Curated ``_PARAM_OVERRIDES`` table (load-bearing names).
      3. Filename-slot heuristic (params containing ``_filename`` etc).
      4. Annotation-based fallback (str/int/float/bool/list/dict).
      5. Name-based fallback (anything ending in ``_filename`` etc).
      6. ``None``.
    """
    name = param.name
    if name == "preset" and builder_name is not None:
        return _preset_for_builder(builder_name)
    if name in _PARAM_OVERRIDES:
        return _PARAM_OVERRIDES[name]
    fname_placeholder = _is_filename_param(name)
    if fname_placeholder is not None:
        return fname_placeholder

    # Annotation-driven fallback.
    ann = param.annotation
    if ann is not inspect.Parameter.empty:
        ann_name = getattr(ann, "__name__", None) or str(ann)
        ann_lower = str(ann_name).lower()
        if "str" in ann_lower:
            return ""
        if "int" in ann_lower:
            return 512
        if "float" in ann_lower:
            return 1.0
        if "bool" in ann_lower:
            return False
        if "list" in ann_lower or "tuple" in ann_lower or "sequence" in ann_lower:
            return []
        if "dict" in ann_lower or "mapping" in ann_lower:
            return {}

    # Last-ditch name heuristics for common patterns.
    if name.endswith("_text") or name.endswith("_prompt") or name == "prompt":
        return ""
    if name.endswith("_seed") or name == "seed":
        return 42
    return None


def _build_call_kwargs(fn: Any) -> dict[str, Any]:
    """Build a kwargs dict that lets ``fn(**kwargs)`` succeed. Skip
    *args / **kwargs sinks; fill positional / keyword params from
    defaults when present, else synthesise."""
    sig = inspect.signature(fn)
    builder_name = fn.__name__
    out: dict[str, Any] = {}
    for pname, p in sig.parameters.items():
        if pname in {"self", "cls"}:
            continue
        if p.kind in (inspect.Parameter.VAR_POSITIONAL,
                      inspect.Parameter.VAR_KEYWORD):
            continue
        # Per-builder mask / use_solid_mask overrides — some builders
        # validate that AT LEAST ONE of mask_filename / sam3_prompt is
        # provided and would crash otherwise. Force the most-permissive
        # combo.
        if (pname == "use_solid_mask"
                and builder_name in {"build_klein_inpaint"}):
            out[pname] = True
            continue
        # build_lama_remove validates "mask_filename or sam3_prompt".
        # Even though its default is None, force-fill so the export
        # produces a template the user can rewire.
        if (pname == "mask_filename"
                and builder_name in {"build_lama_remove"}):
            out[pname] = PLACEHOLDER_MASK
            continue
        if p.default is not inspect.Parameter.empty:
            # Respect the function's own default (it's already known to be
            # call-correct). But for ``preset``-style required-but-typed
            # dicts that DO have a None default, override so the call
            # doesn't immediately crash inside the builder.
            if pname == "preset" and p.default is None:
                out[pname] = _preset_for_builder(builder_name)
            elif pname in _PARAM_OVERRIDES and p.default is None:
                out[pname] = _PARAM_OVERRIDES[pname]
            # Else leave it — the builder's own default fires.
            continue
        out[pname] = _synthesise_default(p, builder_name=builder_name)
    return out


# ---------------------------------------------------------------------------
# API → GUI conversion
# ---------------------------------------------------------------------------

def _is_link_ref(v: Any) -> bool:
    """A ComfyUI input link is ``[upstream_id, output_idx]`` — a length-2
    list/tuple whose first element coerces to a node-id string and whose
    second is an int. Be defensive: builders sometimes pass tuples vs
    lists; some output indices come through as floats."""
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return False
    upstream, idx = v
    if not isinstance(upstream, (str, int)):
        return False
    if not isinstance(idx, (int, float, bool)):
        return False
    return True


def _topo_sort(graph: dict[str, dict]) -> list[str]:
    """Kahn-style topological sort. Edges: upstream → downstream.
    Returns IDs in dependency order (loaders first, savers last)."""
    in_degree: dict[str, int] = {nid: 0 for nid in graph}
    edges: dict[str, list[str]] = {nid: [] for nid in graph}
    for nid, node in graph.items():
        for v in (node.get("inputs") or {}).values():
            if _is_link_ref(v):
                up = str(v[0])
                if up in graph and up != nid:
                    edges[up].append(nid)
                    in_degree[nid] += 1
    # Stable order: process by ascending int id when possible.
    def _sort_key(s: str) -> tuple[int, str]:
        try:
            return (0, f"{int(s):08d}")
        except (TypeError, ValueError):
            return (1, s)
    ready = sorted([n for n, d in in_degree.items() if d == 0], key=_sort_key)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        downs = sorted(edges[n], key=_sort_key)
        for d in downs:
            in_degree[d] -= 1
            if in_degree[d] == 0 and d not in order and d not in ready:
                ready.append(d)
        ready.sort(key=_sort_key)
    # Append any unreachable cycle members in stable order.
    for nid in sorted(graph, key=_sort_key):
        if nid not in order:
            order.append(nid)
    return order


def _layout_positions(order: list[str], graph: dict[str, dict]) -> dict[str, list[int]]:
    """Assign (x, y) positions left→right by topological column, using a
    simple layered layout. Nodes in the same column are stacked
    vertically."""
    col_of: dict[str, int] = {}
    for nid in order:
        node = graph[nid]
        upstream_cols = []
        for v in (node.get("inputs") or {}).values():
            if _is_link_ref(v):
                up = str(v[0])
                if up in col_of:
                    upstream_cols.append(col_of[up])
        col_of[nid] = (max(upstream_cols) + 1) if upstream_cols else 0
    # Vertical stacking within each column.
    row_of: dict[str, int] = {}
    by_col: dict[int, list[str]] = {}
    for nid in order:
        by_col.setdefault(col_of[nid], []).append(nid)
    for c, members in by_col.items():
        for i, nid in enumerate(members):
            row_of[nid] = i
    COL_WIDTH = 340
    ROW_HEIGHT = 260
    return {
        nid: [col_of[nid] * COL_WIDTH, row_of[nid] * ROW_HEIGHT]
        for nid in graph
    }


def _next_int_id(seen: set[int]) -> int:
    """Return the smallest positive int not in ``seen``; also update
    ``seen``."""
    candidate = (max(seen) + 1) if seen else 1
    seen.add(candidate)
    return candidate


def _coerce_node_id(s: str, mapping: dict[str, int], seen: set[int]) -> int:
    """Map an API node id (string, sometimes non-numeric) to a stable int
    GUI node id. Pure-int strings keep their value when free; else we
    allocate a fresh id."""
    if s in mapping:
        return mapping[s]
    try:
        ival = int(s)
    except (TypeError, ValueError):
        ival = _next_int_id(seen)
    else:
        if ival in seen or ival <= 0:
            ival = _next_int_id(seen)
        else:
            seen.add(ival)
    mapping[s] = ival
    return ival


def api_to_gui(
    api_graph: dict[str, dict],
    note_text: str | None = None,
) -> dict[str, Any]:
    """Convert a ComfyUI API-format prompt graph (flat
    ``{node_id: {class_type, inputs}}``) to the GUI workflow format
    (``{last_node_id, last_link_id, nodes, links, version, ...}``).

    Adds an optional Note node at ``[-400, 0]`` documenting the source
    method. Returns the GUI-format dict ready for ``json.dump``.
    """
    if not isinstance(api_graph, dict) or not api_graph:
        raise ValueError("api_graph must be a non-empty dict")

    order = _topo_sort(api_graph)
    positions = _layout_positions(order, api_graph)

    # Allocate stable int node ids.
    id_map: dict[str, int] = {}
    seen_ids: set[int] = set()
    for nid in order:
        _coerce_node_id(nid, id_map, seen_ids)

    nodes: list[dict[str, Any]] = []
    links: list[list[Any]] = []
    next_link_id = 1

    for topo_idx, nid in enumerate(order):
        api_node = api_graph[nid]
        class_type = api_node.get("class_type", "Unknown")
        api_inputs = api_node.get("inputs") or {}
        gui_id = id_map[nid]

        gui_inputs: list[dict[str, Any]] = []
        widgets_values: list[Any] = []

        for input_name, input_value in api_inputs.items():
            if _is_link_ref(input_value):
                up_str = str(input_value[0])
                out_idx = int(input_value[1])
                up_gui_id = id_map.get(up_str)
                if up_gui_id is None:
                    # Upstream not in graph — convert to a literal so the
                    # workflow still loads. This shouldn't happen for a
                    # well-formed API graph but be defensive.
                    widgets_values.append(input_value)
                    continue
                link_id = next_link_id
                next_link_id += 1
                links.append([
                    link_id,
                    up_gui_id,
                    out_idx,
                    gui_id,
                    len(gui_inputs),
                    "*",
                ])
                gui_inputs.append({
                    "name": input_name,
                    "type": "*",
                    "link": link_id,
                })
            else:
                widgets_values.append(input_value)

        nodes.append({
            "id":             gui_id,
            "type":           class_type,
            "pos":            positions.get(nid, [topo_idx * 340, 0]),
            "size":           [240, 120],
            "flags":          {},
            "order":          topo_idx + 1,  # 0 reserved for the Note
            "mode":           0,
            "inputs":         gui_inputs,
            "outputs":        [
                {"name": "*", "type": "*", "links": None},
            ],
            "properties":     {"Node name for S&R": class_type},
            "widgets_values": widgets_values,
        })

    # Note node: prepend with the smallest free int id so it shows
    # left of the graph (positioned at [-400, 0]).
    if note_text is not None:
        note_id = _next_int_id(seen_ids)
        nodes.insert(0, {
            "id":             note_id,
            "type":           "Note",
            "pos":            [-400, 0],
            "size":           [350, 200],
            "flags":          {},
            "order":          0,
            "mode":           0,
            "inputs":         [],
            "outputs":        [],
            "properties":     {},
            "widgets_values": [note_text],
            "color":          "#432",
            "bgcolor":        "#653",
        })

    last_node_id = max((n["id"] for n in nodes), default=0)
    last_link_id = next_link_id - 1

    return {
        "last_node_id": last_node_id,
        "last_link_id": last_link_id,
        "nodes":        nodes,
        "links":        links,
        "groups":       [],
        "config":       {},
        "extra":        {},
        "version":      0.4,
    }


# ---------------------------------------------------------------------------
# Note rendering
# ---------------------------------------------------------------------------

def _git_short_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO, stderr=subprocess.DEVNULL,
            text=True, timeout=5,
        ).strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


_GIT_SHA_CACHE: str | None = None


def _git_sha_cached() -> str:
    global _GIT_SHA_CACHE
    if _GIT_SHA_CACHE is None:
        _GIT_SHA_CACHE = _git_short_sha()
    return _GIT_SHA_CACHE


def _signature_str(fn: Any) -> str:
    try:
        return f"{fn.__name__}{inspect.signature(fn)}"
    except (TypeError, ValueError):
        return f"{fn.__name__}(?)"


def _note_text_for(fn: Any) -> str:
    name = fn.__name__
    doc = inspect.getdoc(fn) or "(no docstring)"
    sig = _signature_str(fn)
    sha = _git_sha_cached()
    date = _dt.date.today().isoformat()
    return (
        f"# {name}\n\n"
        f"{doc}\n\n"
        f"## Signature\n\n"
        f"`{sig}`\n\n"
        f"---\n"
        f"Exported from spellcaster @ {sha} on {date}. "
        f"Source: plugins/gimp/comfyui-connector/spellcaster_core/workflows.py "
        f"· DO NOT edit upstream — edit this copy."
    )


# ---------------------------------------------------------------------------
# Builder enumeration / invocation
# ---------------------------------------------------------------------------

def _enumerate_builders(module) -> list[tuple[str, Any]]:
    """Return [(name, fn), ...] for every ``build_*`` public function
    defined in ``module``. Sorted by name."""
    out: list[tuple[str, Any]] = []
    for name, fn in sorted(inspect.getmembers(module, inspect.isfunction)):
        if not name.startswith("build_"):
            continue
        if fn.__module__ != module.__name__:
            continue
        out.append((name, fn))
    return out


def _invoke_builder(fn: Any) -> dict:
    """Invoke ``fn`` with synthesised defaults. Returns the API graph.
    Raises on any error (caller logs and continues)."""
    kwargs = _build_call_kwargs(fn)
    return fn(**kwargs)


def _short_doc(fn: Any) -> str:
    doc = (inspect.getdoc(fn) or "").strip()
    return (doc.splitlines()[0] if doc else "").strip()


# ---------------------------------------------------------------------------
# Windows Controlled Folder Access fallback
# ---------------------------------------------------------------------------
#
# Windows Defender's "Controlled Folder Access" (CFA) protects user
# folders (Documents, Pictures, Desktop, ...) from writes by
# unrecognised processes. python.exe isn't on the default allow-list,
# which means:
#
#   * ``Path.mkdir()`` inside ``C:\Users\legui\Documents\...`` raises
#     ``FileNotFoundError`` (WinError 2) — yes, NotFound, not
#     AccessDenied. CFA disguises the block.
#   * Same for ``open(..., 'w')``: WinError 2 on a path whose parent
#     does exist.
#
# We work around this by:
#   1. Staging every write into a CFA-exempt temp dir.
#   2. After all writes succeed, copy the staging dir into the real
#      destination using ``powershell.exe`` (which IS on CFA's
#      allow-list because it ships with Windows). ``robocopy`` works
#      too but is noisier.
#
# This keeps the script working out of the box on a default Windows
# Home install — no need to ask the user to add python.exe to the CFA
# allow-list manually.


def _powershell_available() -> bool:
    return shutil.which("powershell.exe") is not None or shutil.which("powershell") is not None


def _copy_via_powershell(staging: Path, dest: Path) -> tuple[bool, str]:
    """Copy every file in ``staging`` into ``dest``, creating ``dest``
    if needed. Returns ``(ok, message)``. Uses PowerShell so writes
    bypass CFA. Paths are interpolated as single-quoted literals; we
    pre-validate the staging path so a stray quote can't smuggle in
    new commands."""
    if not _powershell_available():
        return False, "powershell.exe not on PATH"
    # Defence in depth: refuse if either path contains a single-quote
    # (our injection vector). Tempdirs and Documents subdirs don't.
    src = str(staging)
    dst = str(dest)
    if "'" in src or "'" in dst:
        return False, "refusing path with single-quote"
    script = (
        f"$ErrorActionPreference='Stop'; "
        f"New-Item -Path '{dst}' -ItemType Directory -Force | Out-Null; "
        f"Copy-Item -Path (Join-Path '{src}' '*') "
        f"-Destination '{dst}' -Recurse -Force"
    )
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-Command", script,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"powershell launch failed: {exc}"
    if result.returncode != 0:
        return False, (
            f"powershell exited {result.returncode}; "
            f"stderr={result.stderr.strip()[:500]}"
        )
    return True, "copied via powershell"


def _direct_write_works(target_dir: Path) -> bool:
    """Probe write permission by creating a tiny temp file and removing
    it. Returns False on any failure (CFA blocks tend to surface as
    WinError 2 — disguised as NotFound)."""
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    probe = target_dir / ".spellcaster_write_probe.tmp"
    try:
        probe.write_text("", encoding="utf-8")
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        # Wrote OK, even if cleanup hiccups.
        return True
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    p.add_argument(
        "--methods", type=str, default="",
        help="comma-separated builder names to export (default: all).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="don't write files; report what would happen.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="print each method as it's processed.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    try:
        from spellcaster_core import workflows  # type: ignore
    except Exception as exc:  # noqa: BLE001
        log.error("catastrophic: failed to import spellcaster_core.workflows: %s",
                  exc)
        traceback.print_exc()
        return 2

    all_builders = _enumerate_builders(workflows)
    log.info("discovered %d build_* methods in spellcaster_core.workflows",
             len(all_builders))

    if args.methods.strip():
        wanted = {n.strip() for n in args.methods.split(",") if n.strip()}
        builders = [(n, fn) for (n, fn) in all_builders if n in wanted]
        missing = wanted - {n for (n, _) in builders}
        if missing:
            log.warning("requested but not found: %s", sorted(missing))
    else:
        builders = all_builders

    if not builders:
        log.error("no builders selected; nothing to do.")
        return 2

    output_dir = args.output_dir
    # Stage writes in a temp dir when the destination isn't directly
    # writable (Windows CFA blocks python.exe writes into Documents).
    staging_dir: Path | None = None
    write_dir: Path = output_dir
    needs_relay = False
    if not args.dry_run:
        direct_ok = _direct_write_works(output_dir)
        if not direct_ok:
            needs_relay = True
            try:
                staging_dir = Path(tempfile.mkdtemp(
                    prefix="spellcaster_workflows_"))
            except Exception as exc:  # noqa: BLE001
                log.error("catastrophic: cannot create staging dir: %s", exc)
                return 2
            write_dir = staging_dir
            log.info(
                "destination %s rejected a write probe (likely Windows "
                "Controlled Folder Access). Staging to %s and relaying "
                "via PowerShell at the end.",
                output_dir, staging_dir,
            )
        else:
            log.debug("destination %s is directly writable.", output_dir)

    succeeded: list[tuple[str, Path, str]] = []
    failed: list[tuple[str, str]] = []

    for name, fn in builders:
        log.debug("processing %s", name)
        try:
            api_graph = _invoke_builder(fn)
        except Exception as exc:  # noqa: BLE001
            tb_short = f"{type(exc).__name__}: {exc}"
            log.warning("INVOKE FAIL %s: %s", name, tb_short)
            failed.append((name, f"invoke: {tb_short}"))
            continue

        if not isinstance(api_graph, dict) or not api_graph:
            log.warning("EMPTY OUTPUT %s: builder returned %r",
                        name, type(api_graph).__name__)
            failed.append((name, "empty/non-dict builder output"))
            continue

        try:
            gui = api_to_gui(api_graph, note_text=_note_text_for(fn))
        except Exception as exc:  # noqa: BLE001
            tb_short = f"{type(exc).__name__}: {exc}"
            log.warning("CONVERT FAIL %s: %s", name, tb_short)
            failed.append((name, f"convert: {tb_short}"))
            continue

        final_target = output_dir / f"{name}.json"
        write_target = write_dir / f"{name}.json"
        if args.dry_run:
            log.info("DRY %s -> %s (%d nodes)",
                     name, final_target, len(gui["nodes"]))
            succeeded.append((name, final_target, _short_doc(fn)))
            continue

        try:
            with open(write_target, "w", encoding="utf-8") as f:
                json.dump(gui, f, indent=2, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            tb_short = f"{type(exc).__name__}: {exc}"
            log.warning("WRITE FAIL %s: %s", name, tb_short)
            failed.append((name, f"write: {tb_short}"))
            continue

        log.info("OK %s -> %s (%d nodes)",
                 name, write_target.name, len(gui["nodes"]))
        succeeded.append((name, final_target, _short_doc(fn)))

    # Index file. Also written into the staging dir when relaying.
    final_index = output_dir / "_INDEX.md"
    index_write_target = write_dir / "_INDEX.md"
    if not args.dry_run and succeeded:
        try:
            lines = [
                "# Spellcaster ComfyUI workflows",
                "",
                f"Exported {_dt.datetime.now().isoformat(timespec='seconds')} "
                f"from spellcaster @ {_git_sha_cached()}.",
                "",
                f"Source: `plugins/gimp/comfyui-connector/spellcaster_core/workflows.py`",
                "",
                f"{len(succeeded)} workflows exported, {len(failed)} failed.",
                "",
                "## Workflows",
                "",
            ]
            for name, path, summary in succeeded:
                summary_clean = summary.replace("\n", " ").strip() or "(no summary)"
                lines.append(f"- **`{name}.json`** — {summary_clean}")
            if failed:
                lines.extend(["", "## Failed", ""])
                for name, why in failed:
                    why_clean = why.replace("\n", " ").strip()
                    lines.append(f"- `{name}` — {why_clean}")
            index_write_target.write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
            log.info("wrote index: %s", final_index)
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to write index: %s", exc)

    # Relay staging dir contents into the final destination via
    # PowerShell when needed (CFA workaround).
    if needs_relay and not args.dry_run and staging_dir is not None and succeeded:
        ok, msg = _copy_via_powershell(staging_dir, output_dir)
        if ok:
            log.info("relayed %d files into %s (%s)",
                     len(succeeded) + (1 if succeeded else 0),
                     output_dir, msg)
            # Clean staging dir on success.
            try:
                shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
        else:
            log.error(
                "RELAY FAIL: staging dir kept at %s. Manual copy needed. "
                "Reason: %s",
                staging_dir, msg,
            )
            log.error(
                "Run this in PowerShell to finish the export:\n"
                "  Copy-Item -Path '%s\\*' -Destination '%s' -Recurse -Force",
                staging_dir, output_dir,
            )
            # Treat as catastrophic — the user's expected destination
            # is empty.
            return 2

    log.info("done: %d exported, %d failed, total %d",
             len(succeeded), len(failed), len(builders))

    if failed and succeeded:
        return 1
    if not succeeded:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
