#!/usr/bin/env python3
"""Auto-generate ``spellcaster_core/builders_manifest.json``.

This script introspects ``spellcaster_core.workflows`` and emits a JSON
manifest that lists every public ``build_*`` function with:

  * ``id``           — stable string id (the bare builder name, no prefix)
  * ``builder``      — full ``build_*`` function name
  * ``label``        — human label derived from the docstring summary
  * ``kind``         — coarse bucket (image / video / 3d / detect / other)
  * ``model_family`` — best-guess model family this builder consumes
                       (sdxl / flux / klein / wan / ltx / cogvideo / hunyuan /
                       mochi / framepack / lumina2 / hunyuan_3d / illustrious /
                       generic). The C-side gate uses this to decide whether
                       the underlying nodes are present before exposing the
                       method.
  * ``params``       — list of parameter descriptors (name, required, default
                       when scalar-safe, kind hint when an input-slot
                       heuristic matches: image / mask / face / video).
  * ``input_slots``  — the subset of params that consume canvas-shaped data
                       (image / mask / face). Lets the host UI auto-fill
                       from the canvas without re-running the heuristic.
  * ``short_doc``    — first line of the docstring, trimmed to 160 chars.
  * ``target_class`` — the terminal ComfyUI ``class_type`` the builder
                       instantiates as its workhorse node (e.g. ``RMBG`` for
                       ``build_rembg_v3``). This field is the canonical
                       single-source-of-truth that replaces the formerly
                       hand-curated dispatcher tables on the Voodoomaster
                       Python loader AND the Voodoomancer C dispatcher. When
                       absent, the consumer falls back to its own static
                       table (graceful degrade for old manifests).

The intent: this manifest is the canonical "what generative methods exist"
contract that Voodoomaster advertises via ``/v1/capabilities.methods`` and
that the Voodoomancer C-side reads at startup to gate native AI handlers.
A new ``build_X`` in ``workflows.py`` regenerates the manifest, propagates
through the existing 6-surface mirror, and surfaces in the next caps
recompose — zero hand-coding required on the Python side.

The Voodoomancer C-side still needs a recompile to register a NEW
``handle_X`` for an unfamiliar action_id, but it can read the manifest to
gate which of its registered actions to advertise to GIMP at startup
(suppress actions whose ``id`` isn't in the manifest, or whose
``model_family`` is "unsupported" per the caps doc's ``archs``). A
SIGNATURE change to an existing builder does NOT require a recompile —
the C-side dispatches the kwargs verbatim through the helper subprocess.

Usage
-----

    python tools/build_builders_manifest.py            # writes manifest
    python tools/build_builders_manifest.py --check    # exit 1 on diff

CI hook: ``tests/builders_manifest_drift.py`` shells out to ``--check``.

The manifest lives at::

    comfyui-spellcaster/spellcaster_core/builders_manifest.json

…right next to ``workflows.py`` so the 6-surface mirror (already
enforced for the other ``spellcaster_core/`` files via
``tests/mirror_drift.py`` + ``tools/sync_surfaces.py``) carries the
manifest to every consumer surface for free.
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
CORE_DIR = REPO / "comfyui-spellcaster" / "spellcaster_core"
MANIFEST_PATH = CORE_DIR / "builders_manifest.json"

# Make the spellcaster_core package importable when running outside an
# installed environment. This mirrors the import path used by the Krita
# plugin's standalone-test invocation.
sys.path.insert(0, str(REPO / "comfyui-spellcaster"))


# ---------------------------------------------------------------------------
# Input-slot heuristics (mirrors plugins/krita/dynamic_dispatch.py)
# ---------------------------------------------------------------------------

_IMAGE_PARAM_NAMES = frozenset({
    "image", "image_bytes", "input_image", "source_image",
    "src_image", "canvas", "ref_image", "reference_image",
    "image_filename",
})
_MASK_PARAM_NAMES = frozenset({
    "mask", "mask_bytes", "selection_mask", "inpaint_mask",
    "mask_filename",
})
_FACE_PARAM_NAMES = frozenset({
    "source_face", "source_face_bytes", "face_image", "face_bytes",
    "face_filename", "face_ref_filename",
    "ref_filename", "reference_filename", "style_ref_filename",
    "source_filename", "target_filename",
    "end_image_filename",
    "clip_vision_image", "ip_adapter_image",
    "image2_filename", "image3_filename",
    "image_a_filename", "image_b_filename",
})
_VIDEO_PARAM_NAMES = frozenset({
    "video", "video_name", "video_filename", "video_bytes",
    "frame_filenames",
})


def _input_slot_kind(name: str) -> str | None:
    if name in _IMAGE_PARAM_NAMES:
        return "image"
    if name in _MASK_PARAM_NAMES:
        return "mask"
    if name in _FACE_PARAM_NAMES:
        return "face"
    if name in _VIDEO_PARAM_NAMES:
        return "video"
    return None


# ---------------------------------------------------------------------------
# Model-family inference
# ---------------------------------------------------------------------------

# Ordered: most-specific patterns first. The first match wins so e.g.
# ``build_wan22_t2v`` lands in "wan" not "generic".
#
# Patterns are matched against the bare builder name (no ``build_`` prefix).
# Examples:
#   build_klein_repose        → klein
#   build_pulid_flux          → flux
#   build_inpaint_fooocus     → sdxl  (Fooocus head is SDXL-only)
#   build_wan_video           → wan
#   build_seedvr2_video_upscale → video
_MODEL_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    # Klein family (Flux2-Klein architecture, Spellcaster-named)
    (r"^klein_", "klein"),
    # Explicit arch markers
    (r"^pulid_flux", "flux"),
    (r"^flux_", "flux"),
    (r"_flux$", "flux"),
    (r"_flux_", "flux"),
    (r"^qwen_edit", "flux"),  # qwen-image-edit shares the flux loader path
    # Video architectures (each one has dedicated loader nodes)
    (r"^wan22_t2v", "wan"),
    (r"^wan_animate", "wan"),
    (r"^wan_flf", "wan"),
    (r"^wan_video_blockswap", "wan"),
    (r"^wan_", "wan"),
    (r"^ltx_", "ltx"),
    (r"^cogvideo_", "cogvideo"),
    (r"^mochi_", "mochi"),
    (r"^framepack_", "framepack"),
    (r"^hunyuan_video", "hunyuan_video"),
    (r"^hunyuan_3d_", "hunyuan_3d"),
    (r"^lumina2_", "lumina2"),
    # SDXL-coupled methods (Fooocus head, SUPIR, IClight, etc are all
    # SDXL by construction).
    (r"^inpaint_fooocus", "sdxl"),
    (r"^supir", "sdxl"),
    (r"^iclight", "sdxl"),
    # SeedVR2 video upscale uses the wavespeed/seedvr pack; treat as video
    (r"^seedvr2_", "video"),
    (r"^seedv2r", "sdxl"),
    # Face / detect-style builders are arch-agnostic helpers
    (r"^sam3_", "detect"),
    (r"^magic_eraser$", "detect"),
    (r"^rembg", "detect"),
    (r"^depth_map", "detect"),
    (r"^normal_map", "detect"),
    (r"^ddcolor", "detect"),
    (r"^face_restore", "detect"),
    (r"^faceswap", "detect"),
    (r"^save_face_model", "detect"),
    (r"^lama_remove", "detect"),
    (r"^lut$", "detect"),
    (r"^color_match", "detect"),
    (r"^video_upscale", "video"),
    (r"^video_reactor", "video"),
    (r"^wavespeed_upscale", "detect"),
    (r"^upscale", "detect"),
    (r"^upscale_blend", "detect"),
    (r"^layer_blend", "detect"),
    (r"^frame_assembly", "video"),
    # FaceID is SDXL-coupled (IPAdapter-FaceID-Plus-v2 is SDXL)
    (r"^faceid_", "sdxl"),
    (r"^photobooth", "sdxl"),
    (r"^photo_restore", "sdxl"),
    (r"^detail_hallucinate", "sdxl"),
    (r"^controlnet_gen", "sdxl"),
    (r"^colorize", "sdxl"),
    (r"^style_transfer", "sdxl"),
)


def _model_family_for(builder_name: str) -> str:
    """Infer model family from the builder's name. Returns "generic" when
    no specific arch is implied."""
    bare = builder_name[len("build_"):] if builder_name.startswith(
        "build_") else builder_name
    for pat, fam in _MODEL_FAMILY_PATTERNS:
        if re.search(pat, bare):
            return fam
    return "generic"


# ---------------------------------------------------------------------------
# Kind bucket (mirrors dynamic_dispatch._bucket_for)
# ---------------------------------------------------------------------------

def _bucket_for(name: str) -> str:
    lname = name.lower()
    if any(t in lname for t in ("_video", "_wan", "_ltx", "_cogvideo",
                                "_mochi", "_framepack")):
        return "video"
    if "_3d" in lname or "hunyuan_3d" in lname:
        return "3d"
    if any(t in lname for t in ("_sam3", "sam2", "rembg", "detect")):
        return "detect"
    if any(t in lname for t in ("_face", "klein", "iclight", "supir",
                                "upscale", "colorize", "inpaint",
                                "outpaint", "img2img", "txt2img",
                                "magic_eraser", "detail_hallucinate",
                                "style_transfer", "normal_map")):
        return "image"
    return "other"


# ---------------------------------------------------------------------------
# target_class — terminal ComfyUI class_type the builder lands on
# ---------------------------------------------------------------------------
#
# The dispatcher (Voodoomancer C-side gimp-ai-manifest.c, Voodoomaster
# Python loader voodoomaster/capabilities/builders_manifest.py) gates
# methods on whether THIS ComfyUI install has the workhorse node class
# the builder needs. Pre-manifest, both surfaces kept hand-curated
# method_id -> class_type tables, which drifted independently — live
# witness 2026-05-14, all four entries on the C-side mirror were wrong
# (``RembgV3`` vs canonical ``RMBG``, ``DepthAnythingV2Preprocessor``
# vs ``DepthAnything_V3``, ``BAE-NormalMapPreprocessor`` vs
# ``NormalCrafterNode``). Producing this field from the same source
# of truth as ``workflows.py`` collapses the dual-SSoT.
#
# Resolution order:
#   1. Hand-curated _TARGET_CLASS_OVERRIDES below (highest authority;
#      hand-verified by reading the builder source).
#   2. _infer_target_class() heuristic: AST-walk the builder, return
#      the LAST direct ``_add("ClassName", ...)`` call. Sufficient for
#      simple 3-node builders (LoadImage -> Builder -> SaveImage).
#   3. NodeFactory helper inference: when the builder ends with a call
#      like ``nf.depth_anything_v3(...)`` and the helper itself ends in
#      a direct ``_add("ClassName", ...)``, surface that class.
#   4. None — manifest emits no field; consumer falls back to its
#      static table.
#
# Adding a new dispatcher-relevant method: prefer registering an
# override here AND verifying _infer_target_class() agrees (the
# generator's CI mode flags drift between the two).

_TARGET_CLASS_OVERRIDES: dict[str, str] = {
    # Dispatcher-relevant single-class detect/generic builders. These are
    # the methods Voodoomancer's manifest_node_map[] dispatches via the
    # generic LoadImage -> Builder -> SaveImage path (PoC scope).
    "color_match":      "ColorMatch",
    "depth_map_v3":     "DepthAnything_V3",
    "normal_map":       "NormalCrafterNode",
    "rembg":            "Image Rembg (Remove Background)",
    "rembg_birefnet":   "BiRefNetRMBG",
    "rembg_v3":         "RMBG",
    "ddcolor":          "DDColor_Colorize",
    "lut":              "ImageApplyLUT+",
}


def _infer_target_class(fn: Any) -> str | None:
    """Best-effort: AST-scan the builder body for the LAST direct
    ``_add("ClassName", ...)`` call (i.e. the call whose first arg is
    a string literal). Returns the literal, or None when the heuristic
    can't decide.

    This is intentionally narrow: detection-family / generic builders
    (the dispatcher-relevant slice) almost always end with a direct
    ``nf._add("X", {...})`` because they're 3-node graphs. Multi-stage
    builders (klein / sdxl / wan / ...) typically delegate to NodeFactory
    helper methods or do branching — they correctly fall through to the
    overrides table or to None.
    """
    import ast as _ast
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return None
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None
    last_class: str | None = None
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        # Match foo._add("ClassName", ...) and bare _add("ClassName", ...)
        is_add = False
        if isinstance(node.func, _ast.Attribute) and node.func.attr == "_add":
            is_add = True
        elif isinstance(node.func, _ast.Name) and node.func.id == "_add":
            is_add = True
        if not is_add or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, _ast.Constant) and isinstance(first.value, str):
            last_class = first.value
    return last_class


def _target_class_for(name: str, fn: Any) -> str | None:
    """Resolve the workhorse ComfyUI class_type for a builder.

    Returns None when neither the override table nor the AST heuristic
    can determine the class with confidence; the manifest then omits
    the ``target_class`` key and the consumer is expected to fall back
    to its own static table (PoC dispatcher safety net).
    """
    bare = name[len("build_"):] if name.startswith("build_") else name
    if bare in _TARGET_CLASS_OVERRIDES:
        return _TARGET_CLASS_OVERRIDES[bare]
    return _infer_target_class(fn)


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------

def _safe_default(v: Any) -> Any:
    """Coerce a parameter default to a JSON-safe value, or omit by
    returning a sentinel string for non-scalar / non-trivial defaults.

    Manifest defaults are advisory only — the host UI uses them to
    pre-fill form fields. The actual call still happens in-process in
    spellcaster_core, so the real Python default is honoured if the
    host passes nothing."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, (list, tuple)):
        try:
            return [_safe_default(x) for x in v]
        except Exception:  # noqa: BLE001
            return None
    if isinstance(v, dict):
        try:
            return {str(k): _safe_default(val) for k, val in v.items()}
        except Exception:  # noqa: BLE001
            return None
    # Callable / class / complex object — surface the type name so the
    # consumer can at least display it.
    try:
        return f"<{type(v).__name__}>"
    except Exception:  # noqa: BLE001
        return None


def _params_for(sig: inspect.Signature) -> list[dict[str, Any]]:
    params: list[dict[str, Any]] = []
    for pname, p in sig.parameters.items():
        if pname in {"self", "cls"}:
            continue
        if p.kind in (inspect.Parameter.VAR_POSITIONAL,
                      inspect.Parameter.VAR_KEYWORD):
            continue
        entry: dict[str, Any] = {"name": pname}
        slot = _input_slot_kind(pname)
        if slot is not None:
            entry["slot"] = slot
        if p.annotation is not inspect.Parameter.empty:
            entry["annotation"] = (
                p.annotation.__name__ if isinstance(p.annotation, type)
                else str(p.annotation)
            )
        if p.default is inspect.Parameter.empty:
            entry["required"] = True
        else:
            entry["required"] = False
            entry["default"] = _safe_default(p.default)
        params.append(entry)
    return params


def _short_doc_for(fn: Any) -> str:
    doc = (inspect.getdoc(fn) or "").strip()
    first = doc.splitlines()[0] if doc else ""
    return first[:160]


def _label_for(builder_name: str, short_doc: str) -> str:
    """Human label for the method. Prefers the docstring summary; falls
    back to the bare builder name with underscores → spaces."""
    if short_doc:
        # Trim trailing period to match the menu style ("Inpaint" not "Inpaint.").
        return short_doc.rstrip(".")
    bare = builder_name[len("build_"):] if builder_name.startswith(
        "build_") else builder_name
    return bare.replace("_", " ").title()


def enumerate_manifest() -> list[dict[str, Any]]:
    """Return a list of manifest entries, sorted by builder name. Imports
    ``spellcaster_core.workflows`` and walks every public ``build_*``
    function defined in that module (re-exports skipped)."""
    mod = importlib.import_module("spellcaster_core.workflows")
    entries: list[dict[str, Any]] = []
    for name, fn in sorted(inspect.getmembers(mod, inspect.isfunction)):
        if not name.startswith("build_"):
            continue
        if fn.__module__ != mod.__name__:
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            params: list[dict[str, Any]] = []
        else:
            params = _params_for(sig)
        bare_id = name[len("build_"):]
        short_doc = _short_doc_for(fn)
        family = _model_family_for(name)
        kind = _bucket_for(name)
        input_slots = [p["name"] for p in params if "slot" in p]
        entry: dict[str, Any] = {
            "id":           bare_id,
            "builder":      name,
            "label":        _label_for(name, short_doc),
            "kind":         kind,
            "model_family": family,
            "input_slots":  input_slots,
            "params":       params,
            "short_doc":    short_doc,
        }
        target_class = _target_class_for(name, fn)
        if target_class:
            # Insert just after model_family so dispatcher-relevant
            # fields cluster together in the rendered JSON.
            entry = {
                "id":           entry["id"],
                "builder":      entry["builder"],
                "label":        entry["label"],
                "kind":         entry["kind"],
                "model_family": entry["model_family"],
                "target_class": target_class,
                "input_slots":  entry["input_slots"],
                "params":       entry["params"],
                "short_doc":    entry["short_doc"],
            }
        entries.append(entry)
    return entries


# schema_version bumped 1 -> 2 with the addition of the optional
# ``target_class`` field per method. Field is omitted when neither the
# override table nor the AST heuristic can resolve a class; consumers
# that parse this manifest are required to tolerate the field's
# absence (fall back to their own static table).
SCHEMA_VERSION = 2
GENERATOR_TAG = "spellcaster/tools/build_builders_manifest.py"


def build_manifest_document() -> dict[str, Any]:
    entries = enumerate_manifest()
    return {
        "schema_version": SCHEMA_VERSION,
        "generator":      GENERATOR_TAG,
        "source":         "comfyui-spellcaster/spellcaster_core/workflows.py",
        "method_count":   len(entries),
        "methods":        entries,
    }


def render_json(doc: dict[str, Any]) -> str:
    # Stable formatting so PR diffs are minimal: 2-space indent, sorted
    # top-level keys NOT used (we want the structural order above), but
    # within each method dict the keys ARE consistently ordered (insertion
    # order, deterministic per Python 3.7+).
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the manifest on disk doesn't match "
                         "the regenerated content (CI mode).")
    ap.add_argument("--stdout", action="store_true",
                    help="print the manifest to stdout instead of writing.")
    args = ap.parse_args()

    doc = build_manifest_document()
    rendered = render_json(doc)

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    if args.check:
        if not MANIFEST_PATH.is_file():
            print(f"check: manifest missing at {MANIFEST_PATH}",
                  file=sys.stderr)
            return 1
        on_disk = MANIFEST_PATH.read_text(encoding="utf-8")
        if on_disk != rendered:
            print(f"check: manifest at {MANIFEST_PATH} is stale.",
                  file=sys.stderr)
            print(f"       regenerate via: python "
                  f"tools/build_builders_manifest.py", file=sys.stderr)
            # Tiny diff hint — first divergence offset.
            for i, (a, b) in enumerate(zip(on_disk, rendered)):
                if a != b:
                    print(f"       first divergence at offset {i}",
                          file=sys.stderr)
                    break
            return 1
        print(f"check: manifest fresh ({doc['method_count']} methods).")
        return 0

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(REPO)} "
          f"({doc['method_count']} methods).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
