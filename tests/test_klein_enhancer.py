"""Smoke tests for Flux2Klein-Enhancer wiring across generative builders.

Runs offline — NodeFactory emits plain dicts; no ComfyUI server needed.
Verifies:

    * enhance=True on a Klein preset inserts the full enhancer chain
      (RefLatentController -> TextRefBalance -> ColorAnchor) and routes
      the CFGGuider's model input to the last enhancer node.
    * enhance=False on a Klein preset emits zero enhancer nodes.
    * enhance=True on a non-Klein (SDXL) preset emits zero enhancer
      nodes (the flag is a no-op off Klein).
    * Every build() result has unique node IDs (no collisions between
      the enhancer IDs 870/880/890 and the builder's own IDs).
    * Already-enhanced builders (klein_img2img, outpaint Klein branch)
      still honor the enhance=False opt-out.

Run from the repo root::

    PYTHONPATH=comfyui-spellcaster python tests/test_klein_enhancer.py
"""

from __future__ import annotations

import os
import sys
import traceback


# The workflows live in comfyui-spellcaster/spellcaster_core/. Add that
# directory to sys.path so `from spellcaster_core import workflows` works.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_CORE_ROOT = os.path.join(_REPO, "comfyui-spellcaster")
if _CORE_ROOT not in sys.path:
    sys.path.insert(0, _CORE_ROOT)


from spellcaster_core import workflows  # noqa: E402


# --- Fixtures -------------------------------------------------------------

# Filename contains "9b" so the Klein CLIP selector picks qwen_3_8b
# (see load_model_stack); irrelevant for graph-shape assertions but
# avoids a noisy warning print.
KLEIN_PRESET = {
    "arch": "flux2klein",
    "ckpt": "Klein-9B.safetensors",
    "width": 1024,
    "height": 1024,
    "steps": 6,
    "cfg": 1.0,
    "denoise": 0.65,
}

SDXL_PRESET = {
    "arch": "sdxl",
    "ckpt": "sdxl_base.safetensors",
    "width": 1024,
    "height": 1024,
    "steps": 20,
    "cfg": 6.5,
    "denoise": 0.65,
}

ENHANCER_CLASS_TYPES = {
    "Flux2KleinRefLatentController",
    "Flux2KleinTextRefBalance",
    "Flux2KleinColorAnchor",
}


# --- Helpers --------------------------------------------------------------

def enhancer_node_ids(graph):
    """Return the set of node IDs whose class_type is one of the enhancer chain."""
    return {
        nid for nid, node in graph.items()
        if node.get("class_type") in ENHANCER_CLASS_TYPES
    }


def color_anchor_id(graph):
    """Return the node ID of the Flux2KleinColorAnchor node, or None."""
    for nid, node in graph.items():
        if node.get("class_type") == "Flux2KleinColorAnchor":
            return nid
    return None


def guider_model_ref(graph):
    """Return the `model` ref of the first CFGGuider in the graph, or None."""
    for node in graph.values():
        if node.get("class_type") == "CFGGuider":
            return node["inputs"].get("model")
    return None


def ksampler_model_ref(graph):
    """Return the `model` ref of the first KSampler in the graph, or None."""
    for node in graph.values():
        if node.get("class_type") == "KSampler":
            return node["inputs"].get("model")
    return None


def assert_unique_ids(graph, label):
    """build() returns dict so keys are unique by construction; this
    guards against anyone swapping in a list-based container later."""
    ids = list(graph.keys())
    if len(ids) != len(set(ids)):
        dups = [i for i in ids if ids.count(i) > 1]
        raise AssertionError(f"{label}: duplicate node IDs {sorted(set(dups))}")


# --- Per-builder cases ----------------------------------------------------

def case_img2img_klein_enhanced():
    g = workflows.build_img2img(
        "in.png", KLEIN_PRESET, "a cat", "", 12345, enhance=True)
    ids = enhancer_node_ids(g)
    assert ids == {"880", "881", "882"}, f"enhancer IDs wrong: {sorted(ids)}"
    anchor = color_anchor_id(g)
    assert guider_model_ref(g) == [anchor, 0], (
        "CFGGuider.model should target the ColorAnchor output; got "
        f"{guider_model_ref(g)!r}")
    assert_unique_ids(g, "img2img Klein enhance=True")


def case_img2img_klein_bypass():
    g = workflows.build_img2img(
        "in.png", KLEIN_PRESET, "a cat", "", 12345, enhance=False)
    assert not enhancer_node_ids(g), "enhance=False should emit no enhancer"
    # The guider model should point at the UNET loader (not an enhancer).
    gref = guider_model_ref(g)
    assert gref is not None, "Klein branch must create a CFGGuider"
    ref_node = g[gref[0]]
    assert ref_node["class_type"] not in ENHANCER_CLASS_TYPES, (
        f"guider should bypass enhancer; pointed at {ref_node['class_type']}")


def case_img2img_sdxl_flag_ignored():
    # enhance=True on a non-Klein preset must NOT introduce enhancer
    # nodes — the flag is Klein-specific.
    g = workflows.build_img2img(
        "in.png", SDXL_PRESET, "a cat", "", 42, enhance=True)
    assert not enhancer_node_ids(g), "SDXL must not get Klein enhancer"
    # Sanity: SDXL path uses KSampler, not CFGGuider.
    assert ksampler_model_ref(g) is not None


def case_txt2img_klein_enhanced():
    g = workflows.build_txt2img(KLEIN_PRESET, "a dragon", "", 7, enhance=True)
    ids = enhancer_node_ids(g)
    assert ids == {"870", "871", "872"}, f"txt2img IDs wrong: {sorted(ids)}"
    anchor = color_anchor_id(g)
    assert guider_model_ref(g) == [anchor, 0]
    assert_unique_ids(g, "txt2img Klein enhance=True")


def case_txt2img_klein_bypass():
    g = workflows.build_txt2img(KLEIN_PRESET, "a dragon", "", 7, enhance=False)
    assert not enhancer_node_ids(g)


def case_txt2img_sdxl_flag_ignored():
    g = workflows.build_txt2img(SDXL_PRESET, "a dragon", "", 7, enhance=True)
    assert not enhancer_node_ids(g)


def case_inpaint_klein_enhanced():
    g = workflows.build_inpaint(
        "in.png", "mask.png", KLEIN_PRESET, "fix hands", "", 99, enhance=True)
    ids = enhancer_node_ids(g)
    assert ids == {"890", "891", "892"}, f"inpaint IDs wrong: {sorted(ids)}"
    anchor = color_anchor_id(g)
    assert guider_model_ref(g) == [anchor, 0]
    assert_unique_ids(g, "inpaint Klein enhance=True")


def case_inpaint_klein_bypass():
    g = workflows.build_inpaint(
        "in.png", "mask.png", KLEIN_PRESET, "fix hands", "", 99, enhance=False)
    assert not enhancer_node_ids(g)


def case_inpaint_sdxl_flag_ignored():
    g = workflows.build_inpaint(
        "in.png", "mask.png", SDXL_PRESET, "fix hands", "", 99, enhance=True)
    assert not enhancer_node_ids(g)


# --- Regression spot checks for already-enhanced Klein builders -----------

def case_klein_img2img_enhance_opt_out():
    """klein_img2img has always respected enhance=False; confirm."""
    g = workflows.build_klein_img2img(
        "in.png", "Klein 9B", "hello", 1, enhance=True,
        klein_models={"Klein 9B": {"unet": "Klein-9B.safetensors"}},
    )
    assert enhancer_node_ids(g), "klein_img2img enhance=True should wire chain"

    g2 = workflows.build_klein_img2img(
        "in.png", "Klein 9B", "hello", 1, enhance=False,
        klein_models={"Klein 9B": {"unet": "Klein-9B.safetensors"}},
    )
    assert not enhancer_node_ids(g2), "klein_img2img enhance=False must bypass"


def case_outpaint_klein_still_enhanced():
    """build_outpaint always wires the enhancer on the Klein branch; verify
    the contract still holds (no regression from our img2img/txt2img/inpaint
    edits)."""
    g = workflows.build_outpaint(
        "in.png", KLEIN_PRESET, "", "", 3,
        left=32, top=0, right=32, bottom=0, feathering=10,
    )
    assert enhancer_node_ids(g), "outpaint Klein branch must have enhancer"
    anchor = color_anchor_id(g)
    assert guider_model_ref(g) == [anchor, 0]


# --- Runner ---------------------------------------------------------------

CASES = [
    ("build_img2img  | klein + enhance",        case_img2img_klein_enhanced),
    ("build_img2img  | klein + no-enhance",     case_img2img_klein_bypass),
    ("build_img2img  | sdxl + enhance flag",    case_img2img_sdxl_flag_ignored),
    ("build_txt2img  | klein + enhance",        case_txt2img_klein_enhanced),
    ("build_txt2img  | klein + no-enhance",     case_txt2img_klein_bypass),
    ("build_txt2img  | sdxl + enhance flag",    case_txt2img_sdxl_flag_ignored),
    ("build_inpaint  | klein + enhance",        case_inpaint_klein_enhanced),
    ("build_inpaint  | klein + no-enhance",     case_inpaint_klein_bypass),
    ("build_inpaint  | sdxl + enhance flag",    case_inpaint_sdxl_flag_ignored),
    ("regression: klein_img2img opt-out",       case_klein_img2img_enhance_opt_out),
    ("regression: outpaint Klein stays wired",  case_outpaint_klein_still_enhanced),
]


def main():
    print("Flux2Klein-Enhancer wiring smoke tests")
    print("=" * 60)
    failures = []
    for label, fn in CASES:
        try:
            fn()
            print(f"  [OK]   {label}")
        except AssertionError as e:
            print(f"  [FAIL] {label}: {e}")
            failures.append(label)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR]  {label}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append(label)
    print("=" * 60)
    if failures:
        print(f"FAILED ({len(failures)}/{len(CASES)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASSED ({len(CASES)}/{len(CASES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
