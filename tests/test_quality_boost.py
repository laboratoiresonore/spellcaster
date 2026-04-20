"""Smoke tests for the Tier A+B+C quality boosters.

Verifies the `_apply_quality_boost` and `_apply_flux1_boosters` helpers
wire the right nodes into img2img / txt2img / inpaint / outpaint:

  * PerturbedAttentionGuidance fires on SDXL/Illustrious/Flux1/Chroma
    /Kontext at quality>="balanced", skipped on SD1.5/ZIT/Klein.
  * RescaleCFG fires when cfg>=7.5 on SD1.5/SDXL/Illustrious.
  * FreeU_V2 fires only at quality="max" on SDXL (not Illustrious).
  * FluxGuidance + ModelSamplingFlux fire ALWAYS on flux1dev/flux_kontext
    (foundational — unrelated to quality profile).
  * DifferentialDiffusion fires on every non-Klein inpaint/outpaint path.
  * quality="fast" disables PAG/RescaleCFG/FreeU (Flux boosters still fire
    — they're not gated by profile, they're foundational for Flux quality).
  * Klein branch still behaves exactly as before — no PAG/RescaleCFG/FreeU,
    enhancer chain unchanged.

Run:
    PYTHONPATH=comfyui-spellcaster python tests/test_quality_boost.py
"""

from __future__ import annotations

import os
import sys
import traceback


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_CORE_ROOT = os.path.join(_REPO, "comfyui-spellcaster")
if _CORE_ROOT not in sys.path:
    sys.path.insert(0, _CORE_ROOT)


from spellcaster_core import workflows  # noqa: E402


# --- Fixtures -------------------------------------------------------------

SDXL_PRESET = {
    "arch": "sdxl",
    "ckpt": "sdxl_base.safetensors",
    "width": 1024, "height": 1024,
    "steps": 20, "cfg": 8.0, "denoise": 0.65,
}

SD15_PRESET = {
    "arch": "sd15",
    "ckpt": "v1-5-pruned.safetensors",
    "width": 512, "height": 512,
    "steps": 25, "cfg": 7.0, "denoise": 0.62,
}

SD15_HIGHCFG = {**SD15_PRESET, "cfg": 8.0}
SDXL_LOWCFG = {**SDXL_PRESET, "cfg": 6.5}

ILLUSTRIOUS_PRESET = {
    "arch": "illustrious",
    "ckpt": "illustrious.safetensors",
    "width": 1024, "height": 1024,
    "steps": 28, "cfg": 7.0, "denoise": 0.62,
}

ZIT_PRESET = {
    "arch": "zit",
    "ckpt": "z-image-turbo.safetensors",
    "width": 1024, "height": 1024,
    "steps": 4, "cfg": 1.5, "denoise": 0.6,
}

FLUX1_PRESET = {
    "arch": "flux1dev",
    "ckpt": "flux1-dev.safetensors",
    "width": 1024, "height": 1024,
    "steps": 20, "cfg": 1.0, "denoise": 0.65,
}

KLEIN_PRESET = {
    "arch": "flux2klein",
    "ckpt": "Klein-9B.safetensors",
    "width": 1024, "height": 1024,
    "steps": 6, "cfg": 1.0, "denoise": 0.65,
}

QUALITY_CLASS_TYPES = {
    "PerturbedAttentionGuidance",
    "RescaleCFG",
    "FreeU_V2",
    "FluxGuidance",
    "ModelSamplingFlux",
    "DifferentialDiffusion",
}


def class_types_present(graph, *names):
    """Return the subset of class_type names that appear in the graph."""
    present = {n["class_type"] for n in graph.values()}
    return {n for n in names if n in present}


def count(graph, class_type):
    return sum(1 for n in graph.values() if n.get("class_type") == class_type)


# --- img2img --------------------------------------------------------------

def case_img2img_sdxl_balanced():
    g = workflows.build_img2img("in.png", SDXL_PRESET, "cat", "", 1)
    # balanced -> PAG + RescaleCFG (cfg=8.0 >= 7.5), no FreeU
    assert count(g, "PerturbedAttentionGuidance") == 1
    assert count(g, "RescaleCFG") == 1
    assert count(g, "FreeU_V2") == 0


def case_img2img_sdxl_fast_disables_quality():
    g = workflows.build_img2img("in.png", SDXL_PRESET, "cat", "", 1,
                                 quality="fast")
    assert count(g, "PerturbedAttentionGuidance") == 0
    assert count(g, "RescaleCFG") == 0
    assert count(g, "FreeU_V2") == 0


def case_img2img_sdxl_max_adds_freeu():
    g = workflows.build_img2img("in.png", SDXL_PRESET, "cat", "", 1,
                                 quality="max")
    assert count(g, "PerturbedAttentionGuidance") == 1
    assert count(g, "RescaleCFG") == 1
    assert count(g, "FreeU_V2") == 1


def case_img2img_sdxl_lowcfg_skips_rescale():
    g = workflows.build_img2img("in.png", SDXL_LOWCFG, "cat", "", 1)
    assert count(g, "PerturbedAttentionGuidance") == 1
    assert count(g, "RescaleCFG") == 0  # cfg=6.5 < 7.5


def case_img2img_illustrious_no_freeu_at_max():
    g = workflows.build_img2img("in.png", ILLUSTRIOUS_PRESET, "anime", "", 1,
                                 quality="max")
    assert count(g, "PerturbedAttentionGuidance") == 1
    assert count(g, "FreeU_V2") == 0  # anime arches skip FreeU


def case_img2img_sd15_no_pag():
    g = workflows.build_img2img("in.png", SD15_PRESET, "portrait", "", 1)
    # SD1.5 doesn't get PAG (too destabilising), but gets RescaleCFG
    # if cfg is high enough. Default SD15 cfg=7.0 < 7.5 so neither fires.
    assert count(g, "PerturbedAttentionGuidance") == 0
    assert count(g, "RescaleCFG") == 0


def case_img2img_sd15_highcfg_gets_rescale():
    g = workflows.build_img2img("in.png", SD15_HIGHCFG, "portrait", "", 1)
    assert count(g, "PerturbedAttentionGuidance") == 0
    assert count(g, "RescaleCFG") == 1


def case_img2img_zit_skips_everything():
    """ZIT is a turbo distill — low CFG, low steps. Quality boost should
    not add anything (not in the PAG arch set, cfg=1.5 below rescale
    threshold)."""
    g = workflows.build_img2img("in.png", ZIT_PRESET, "photo", "", 1,
                                 quality="max")
    assert not class_types_present(g, "PerturbedAttentionGuidance",
                                     "RescaleCFG", "FreeU_V2")


def case_img2img_flux1_foundational_always_on():
    """Flux 1 Dev foundational boosters (FluxGuidance + ModelSamplingFlux)
    are NOT gated by quality — they're always on because Flux visibly
    underperforms without them."""
    for q in ("fast", "balanced", "max"):
        g = workflows.build_img2img("in.png", FLUX1_PRESET, "a dragon", "", 1,
                                     quality=q)
        assert count(g, "FluxGuidance") == 1, f"quality={q}"
        assert count(g, "ModelSamplingFlux") == 1, f"quality={q}"


def case_img2img_flux1_pag_respects_quality():
    g_fast = workflows.build_img2img("in.png", FLUX1_PRESET, "a dragon", "", 1,
                                      quality="fast")
    g_bal = workflows.build_img2img("in.png", FLUX1_PRESET, "a dragon", "", 1,
                                     quality="balanced")
    assert count(g_fast, "PerturbedAttentionGuidance") == 0
    assert count(g_bal, "PerturbedAttentionGuidance") == 1


def case_img2img_klein_untouched():
    """Klein is fully excluded — enhancer path stays exactly as before
    with no PAG/RescaleCFG/FreeU injections, and no Flux1 boosters
    (Klein uses its own ref-latent mechanism)."""
    g = workflows.build_img2img("in.png", KLEIN_PRESET, "cat", "", 1,
                                 quality="max")
    assert not class_types_present(g, "PerturbedAttentionGuidance",
                                     "RescaleCFG", "FreeU_V2",
                                     "FluxGuidance", "ModelSamplingFlux")


# --- txt2img --------------------------------------------------------------

def case_txt2img_sdxl_balanced_has_pag():
    g = workflows.build_txt2img(SDXL_PRESET, "cat", "", 1)
    assert count(g, "PerturbedAttentionGuidance") == 1


def case_txt2img_flux1_flux_guidance():
    g = workflows.build_txt2img(FLUX1_PRESET, "a dragon", "", 1)
    assert count(g, "FluxGuidance") == 1
    assert count(g, "ModelSamplingFlux") == 1


# --- inpaint --------------------------------------------------------------

def case_inpaint_sdxl_gets_differential():
    g = workflows.build_inpaint("in.png", "mask.png", SDXL_PRESET,
                                 "fix hands", "", 1)
    assert count(g, "DifferentialDiffusion") == 1, (
        "SDXL inpaint must wire DifferentialDiffusion for clean mask edges")


def case_inpaint_klein_no_differential():
    """Klein inpaint uses its own ref-latent flow; differential_diffusion
    should NOT be wired there (was never used, don't regress)."""
    g = workflows.build_inpaint("in.png", "mask.png", KLEIN_PRESET,
                                 "fix hands", "", 1)
    assert count(g, "DifferentialDiffusion") == 0


def case_inpaint_flux1_all_boosters():
    g = workflows.build_inpaint("in.png", "mask.png", FLUX1_PRESET,
                                 "retouch", "", 1)
    assert count(g, "DifferentialDiffusion") == 1
    assert count(g, "FluxGuidance") == 1
    assert count(g, "ModelSamplingFlux") == 1
    assert count(g, "PerturbedAttentionGuidance") == 1


# --- outpaint -------------------------------------------------------------

def case_outpaint_sdxl_differential_and_pag():
    g = workflows.build_outpaint("in.png", SDXL_PRESET, "", "", 1,
                                  left=32, top=0, right=32, bottom=0,
                                  feathering=10)
    assert count(g, "DifferentialDiffusion") == 1
    assert count(g, "PerturbedAttentionGuidance") == 1


def case_outpaint_klein_untouched():
    g = workflows.build_outpaint("in.png", KLEIN_PRESET, "", "", 1,
                                  left=32, top=0, right=32, bottom=0,
                                  feathering=10)
    assert count(g, "DifferentialDiffusion") == 0
    assert count(g, "PerturbedAttentionGuidance") == 0


# --- Secondary Klein-capable builders (non-Klein branches) ---------------
# The six builders below have a Klein dispatch we already cover, plus a
# non-Klein branch that runs plain KSampler. Those branches now pick up
# the quality + Flux1 boosters when called with a non-Klein preset.

def case_detail_hallucinate_sdxl_balanced():
    g = workflows.build_detail_hallucinate(
        "in.png", "4x-UltraSharp.pth", SDXL_PRESET,
        "sharper", "", 1, denoise=0.4, cfg=8.0, quality="balanced")
    assert count(g, "PerturbedAttentionGuidance") == 1
    assert count(g, "RescaleCFG") == 1


def case_detail_hallucinate_flux1_foundational():
    g = workflows.build_detail_hallucinate(
        "in.png", "4x-UltraSharp.pth", FLUX1_PRESET,
        "sharper", "", 1, denoise=0.4, cfg=3.5, quality="fast")
    # Foundational boosters on Flux1 fire regardless of quality=fast.
    assert count(g, "FluxGuidance") == 1
    assert count(g, "ModelSamplingFlux") == 1


def case_detail_hallucinate_klein_no_quality_boost():
    g = workflows.build_detail_hallucinate(
        "in.png", "4x-UltraSharp.pth", KLEIN_PRESET,
        "sharper", "", 1, denoise=0.4, cfg=1.0, quality="max")
    assert count(g, "PerturbedAttentionGuidance") == 0
    assert count(g, "FreeU_V2") == 0


def case_colorize_sdxl_balanced():
    g = workflows.build_colorize(
        "in.png", SDXL_PRESET, "colorful", "", 1,
        controlnet_strength=0.8, denoise=0.55, cfg=8.0, quality="balanced")
    assert count(g, "PerturbedAttentionGuidance") == 1
    assert count(g, "RescaleCFG") == 1


def case_colorize_flux1_wraps_cn_conditioning():
    """FluxGuidance on colorize wraps the CN-augmented positive, not the
    raw CLIP output — the graph should still have exactly ONE FluxGuidance
    fed from the ControlNetApplyAdvanced output."""
    g = workflows.build_colorize(
        "in.png", FLUX1_PRESET, "colorful", "", 1,
        controlnet_strength=0.8, denoise=0.55, cfg=3.5, quality="balanced")
    fg_nodes = [n for n in g.values() if n["class_type"] == "FluxGuidance"]
    assert len(fg_nodes) == 1
    model_in = fg_nodes[0]["inputs"]["conditioning"]
    # Input should be a ref pointing at a ControlNet apply node, not raw
    # CLIPTextEncode. Walk: model_in = [node_id, slot]. The node at
    # model_in[0] should be ControlNetApplyAdvanced.
    src_node = g[model_in[0]]
    assert src_node["class_type"] == "ControlNetApplyAdvanced", (
        f"FluxGuidance should consume CN-apply output; got {src_node['class_type']}")


def case_controlnet_gen_sdxl_balanced():
    g = workflows.build_controlnet_gen(
        "in.png", "CannyEdgePreprocessor",
        "SDXL\\controlnet-canny-sdxl-1.0.safetensors",
        SDXL_PRESET, "a castle", "", 1,
        width=1024, height=1024, steps=20, cfg=8.0,
        sampler="euler", scheduler="normal", quality="balanced")
    assert count(g, "PerturbedAttentionGuidance") == 1
    assert count(g, "RescaleCFG") == 1


def case_faceid_sdxl_chain_after_ipa():
    """Quality boost on faceid_img2img must chain AFTER the IPAdapter
    FaceID node so the sampler sees: loader -> FaceID -> PAG/... -> sampler.
    """
    g = workflows.build_faceid_img2img(
        "target.png", "face.png", SDXL_PRESET,
        "a portrait", "", 1, denoise=0.6, steps=20, cfg=8.0,
        quality="balanced")
    assert count(g, "PerturbedAttentionGuidance") == 1
    # The PAG node's model input should trace back to the IPAdapter node (4),
    # either directly or through a chain.
    pag_node = next(n for n in g.values()
                    if n["class_type"] == "PerturbedAttentionGuidance")
    model_in = pag_node["inputs"]["model"]
    # PAG input is always a single ref since it's the first in the quality
    # chain for faceid (no ModelSamplingFlux/etc on SDXL).
    assert model_in == ["4", 0], (
        f"PAG should consume the IPAdapter FaceID output (node 4); got {model_in}")


def case_style_transfer_flux1_pag_and_foundational():
    g = workflows.build_style_transfer(
        "target.png", "style.png", FLUX1_PRESET,
        "match style", "", 1, weight=0.8, denoise=0.6, quality="balanced")
    assert count(g, "FluxGuidance") == 1
    assert count(g, "ModelSamplingFlux") == 1
    assert count(g, "PerturbedAttentionGuidance") == 1


def case_seedv2r_sdxl_balanced():
    g = workflows.build_seedv2r(
        "in.png", "4x-UltraSharp.pth", SDXL_PRESET,
        "sharp", "", 1, denoise=0.5, cfg=8.0, steps=20,
        scale_factor=2.0, orig_width=512, orig_height=512,
        quality="balanced")
    assert count(g, "PerturbedAttentionGuidance") == 1
    assert count(g, "RescaleCFG") == 1


def case_seedv2r_zit_no_boosters():
    g = workflows.build_seedv2r(
        "in.png", "4x-UltraSharp.pth", ZIT_PRESET,
        "sharp", "", 1, denoise=0.5, cfg=1.5, steps=6,
        scale_factor=2.0, orig_width=512, orig_height=512,
        quality="max")
    assert count(g, "PerturbedAttentionGuidance") == 0
    assert count(g, "FreeU_V2") == 0


# --- AlignYourStepsScheduler (AYS) at quality="max" -----------------------
# AYS replaces the single-node KSampler with a 5-node custom-advanced
# pipeline. Only fires on sd15/sdxl/illustrious at max quality.

def _sampler_is_custom_advanced(graph):
    return count(graph, "SamplerCustomAdvanced") >= 1


def _sampler_is_plain_ksampler(graph):
    return count(graph, "KSampler") >= 1 and count(graph, "SamplerCustomAdvanced") == 0


def case_ays_fires_img2img_sdxl_max():
    g = workflows.build_img2img("in.png", SDXL_PRESET, "cat", "", 1,
                                 quality="max")
    assert count(g, "AlignYourStepsScheduler") == 1
    assert _sampler_is_custom_advanced(g)


def case_ays_fires_txt2img_sdxl_max():
    g = workflows.build_txt2img(SDXL_PRESET, "cat", "", 1, quality="max")
    assert count(g, "AlignYourStepsScheduler") == 1
    assert _sampler_is_custom_advanced(g)


def case_ays_fires_inpaint_sd15_max():
    g = workflows.build_inpaint("in.png", "mask.png", SD15_PRESET,
                                 "fix", "", 1, quality="max")
    ays_node = next(n for n in g.values()
                    if n["class_type"] == "AlignYourStepsScheduler")
    # SD1.5 gets model_type="SD1" (the node's only option besides SDXL).
    assert ays_node["inputs"]["model_type"] == "SD1"


def case_ays_fires_inpaint_sdxl_max():
    g = workflows.build_inpaint("in.png", "mask.png", SDXL_PRESET,
                                 "fix", "", 1, quality="max")
    ays_node = next(n for n in g.values()
                    if n["class_type"] == "AlignYourStepsScheduler")
    assert ays_node["inputs"]["model_type"] == "SDXL"


def case_ays_illustrious_uses_sdxl_type():
    g = workflows.build_txt2img(ILLUSTRIOUS_PRESET, "anime", "", 1,
                                 quality="max")
    ays_node = next(n for n in g.values()
                    if n["class_type"] == "AlignYourStepsScheduler")
    assert ays_node["inputs"]["model_type"] == "SDXL"


def case_ays_balanced_keeps_plain_ksampler():
    g = workflows.build_img2img("in.png", SDXL_PRESET, "cat", "", 1,
                                 quality="balanced")
    assert count(g, "AlignYourStepsScheduler") == 0
    assert _sampler_is_plain_ksampler(g)


def case_ays_skips_flux1_even_at_max():
    """Flux has no AYS sigma table. Quality=max on Flux1 should still
    use plain KSampler (with Flux boosters + PAG on the model side),
    not the AYS chain."""
    g = workflows.build_img2img("in.png", FLUX1_PRESET, "dragon", "", 1,
                                 quality="max")
    assert count(g, "AlignYourStepsScheduler") == 0
    assert _sampler_is_plain_ksampler(g)


def case_ays_skips_zit_even_at_max():
    g = workflows.build_txt2img(ZIT_PRESET, "photo", "", 1, quality="max")
    assert count(g, "AlignYourStepsScheduler") == 0
    assert _sampler_is_plain_ksampler(g)


def case_ays_skips_klein():
    """Klein has its own custom-advanced pipeline with enhancer +
    CFGGuider; the AYS path is gated off at source. The graph still
    contains a SamplerCustomAdvanced (from Klein's own builder) but NO
    AlignYourStepsScheduler — Klein uses BasicScheduler instead."""
    g = workflows.build_img2img("in.png", KLEIN_PRESET, "cat", "", 1,
                                 quality="max")
    assert count(g, "AlignYourStepsScheduler") == 0
    # Klein's own SamplerCustomAdvanced may be present — that's expected.


def case_ays_outpaint_sdxl_max():
    g = workflows.build_outpaint("in.png", SDXL_PRESET, "", "", 1,
                                  left=32, top=0, right=32, bottom=0,
                                  feathering=10, quality="max")
    assert count(g, "AlignYourStepsScheduler") == 1
    assert _sampler_is_custom_advanced(g)


# --- Runner ---------------------------------------------------------------

CASES = [
    ("img2img  | sdxl balanced -> PAG + RescaleCFG",  case_img2img_sdxl_balanced),
    ("img2img  | sdxl fast disables everything",       case_img2img_sdxl_fast_disables_quality),
    ("img2img  | sdxl max adds FreeU",                 case_img2img_sdxl_max_adds_freeu),
    ("img2img  | sdxl cfg<7.5 skips RescaleCFG",       case_img2img_sdxl_lowcfg_skips_rescale),
    ("img2img  | illustrious max skips FreeU",         case_img2img_illustrious_no_freeu_at_max),
    ("img2img  | sd15 default no PAG/Rescale",         case_img2img_sd15_no_pag),
    ("img2img  | sd15 high-cfg gets RescaleCFG",       case_img2img_sd15_highcfg_gets_rescale),
    ("img2img  | zit skips every booster",             case_img2img_zit_skips_everything),
    ("img2img  | flux1 foundational always on",        case_img2img_flux1_foundational_always_on),
    ("img2img  | flux1 PAG respects quality",          case_img2img_flux1_pag_respects_quality),
    ("img2img  | klein untouched",                     case_img2img_klein_untouched),

    ("txt2img  | sdxl balanced PAG",                   case_txt2img_sdxl_balanced_has_pag),
    ("txt2img  | flux1 FluxGuidance + Sampling",       case_txt2img_flux1_flux_guidance),

    ("inpaint  | sdxl DifferentialDiffusion",          case_inpaint_sdxl_gets_differential),
    ("inpaint  | klein no DifferentialDiffusion",      case_inpaint_klein_no_differential),
    ("inpaint  | flux1 all boosters",                  case_inpaint_flux1_all_boosters),

    ("outpaint | sdxl DiffDiff + PAG",                 case_outpaint_sdxl_differential_and_pag),
    ("outpaint | klein untouched",                     case_outpaint_klein_untouched),

    ("detail_hallucinate | sdxl balanced",             case_detail_hallucinate_sdxl_balanced),
    ("detail_hallucinate | flux1 foundational",        case_detail_hallucinate_flux1_foundational),
    ("detail_hallucinate | klein no quality boost",    case_detail_hallucinate_klein_no_quality_boost),
    ("colorize           | sdxl balanced",             case_colorize_sdxl_balanced),
    ("colorize           | flux1 wraps CN cond",       case_colorize_flux1_wraps_cn_conditioning),
    ("controlnet_gen     | sdxl balanced",             case_controlnet_gen_sdxl_balanced),
    ("faceid_img2img     | sdxl PAG after IPA",        case_faceid_sdxl_chain_after_ipa),
    ("style_transfer     | flux1 foundational + PAG",  case_style_transfer_flux1_pag_and_foundational),
    ("seedv2r            | sdxl balanced",             case_seedv2r_sdxl_balanced),
    ("seedv2r            | zit max skips boosters",    case_seedv2r_zit_no_boosters),

    ("AYS | img2img sdxl max fires",                   case_ays_fires_img2img_sdxl_max),
    ("AYS | txt2img sdxl max fires",                   case_ays_fires_txt2img_sdxl_max),
    ("AYS | inpaint sd15 max uses SD1 type",           case_ays_fires_inpaint_sd15_max),
    ("AYS | inpaint sdxl max uses SDXL type",          case_ays_fires_inpaint_sdxl_max),
    ("AYS | illustrious uses SDXL type",               case_ays_illustrious_uses_sdxl_type),
    ("AYS | balanced keeps plain KSampler",            case_ays_balanced_keeps_plain_ksampler),
    ("AYS | skips flux1 at max",                       case_ays_skips_flux1_even_at_max),
    ("AYS | skips zit at max",                         case_ays_skips_zit_even_at_max),
    ("AYS | skips klein (own pipeline)",               case_ays_skips_klein),
    ("AYS | outpaint sdxl max fires",                  case_ays_outpaint_sdxl_max),
]


def main():
    print("Quality booster wiring tests")
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
