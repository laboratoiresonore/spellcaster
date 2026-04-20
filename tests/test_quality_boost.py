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
