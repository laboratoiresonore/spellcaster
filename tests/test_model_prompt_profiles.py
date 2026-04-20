"""Tests for the special per-model prompt profiles.

Covers the two durable model-specific handlers added when stock
SD 1.5 and GonzaloMo Zpop v3 AIO started producing bad output:

  * _is_stock_sd15 / _apply_stock_sd15 — base SD 1.5 checkpoints.
  * _is_zpop_aio  / _apply_zpop_aio   — GonzaloMo Zpop AIO merges.

Both detectors deliberately pick up renames + look-alikes so the
specialised handling survives when the user downloads a sibling
checkpoint under a different filename.

Run:
    PYTHONPATH=comfyui-spellcaster python tests/test_model_prompt_profiles.py
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


from spellcaster_core.model_prompt_profiles import (  # noqa: E402
    _is_stock_sd15,
    _is_zpop_aio,
    _apply_stock_sd15,
    _apply_zpop_aio,
    profile_for,
    apply_profile,
)


# ── Detectors ────────────────────────────────────────────────────────────

def case_stock_sd15_canonical():
    assert _is_stock_sd15("v1-5-pruned-emaonly.safetensors") is True
    assert _is_stock_sd15("v1-5-pruned.safetensors") is True
    assert _is_stock_sd15("v1-5-pruned-emaonly-fp16.safetensors") is True


def case_stock_sd15_rename_variants():
    # Subfolder prefixes get stripped before matching but the markers
    # still need to survive common renames.
    assert _is_stock_sd15("sd-v1-5.safetensors") is True
    assert _is_stock_sd15("stable-diffusion-v1-5.ckpt") is True
    assert _is_stock_sd15("sd15-base.safetensors") is True
    assert _is_stock_sd15("sd-1.5-base-fp16.safetensors") is True
    assert _is_stock_sd15("v1_5_pruned.safetensors") is True


def case_stock_sd15_excludes_finetunes():
    # Every community finetune has its own profile and must NOT be
    # swallowed by the base detector.
    assert _is_stock_sd15("juggernaut_reborn.safetensors") is False
    assert _is_stock_sd15("realisticVisionV51_v51VAE.safetensors") is False
    assert _is_stock_sd15("dreamshaper_v7.safetensors") is False
    assert _is_stock_sd15("absoluteReality_v181.safetensors") is False
    assert _is_stock_sd15("deliberate_v2.safetensors") is False


def case_stock_sd15_excludes_sdxl():
    # SDXL filenames sometimes carry "sd-1.5" strings in descriptive
    # text but should not match (SDXL profiles handle them).
    assert _is_stock_sd15("juggernautXL_v9.safetensors") is False
    assert _is_stock_sd15("sdxl_base_1.0.safetensors") is False


def case_zpop_aio_canonical():
    assert _is_zpop_aio("gonzalomozpop_v30aio.safetensors") is True
    assert _is_zpop_aio("gonzalomoZpop_v30AIO.safetensors") is True  # case-insens check upstream


def case_zpop_aio_variant_markers():
    assert _is_zpop_aio("gonzalomozpop_v3_0_aio.safetensors") is True
    assert _is_zpop_aio("zpop_aio_custom.safetensors") is True
    assert _is_zpop_aio("my_zpop_v3aio.safetensors") is True


def case_zpop_aio_excludes_pre_aio():
    # Pre-AIO Zpop is pure pop-art and should stay with the generic
    # "zpop" catch-all entry.
    assert _is_zpop_aio("gonzalomozpop_v2.safetensors") is False
    assert _is_zpop_aio("zpop_pop_art_v1.safetensors") is False


def case_zpop_aio_excludes_non_zpop():
    assert _is_zpop_aio("juggernautXL_v9.safetensors") is False
    assert _is_zpop_aio("some_aio_merge.safetensors") is False
    assert _is_zpop_aio("v1-5-pruned-emaonly.safetensors") is False


# ── Applicators — direct output contract ────────────────────────────────

def case_stock_sd15_applicator_adds_neutral_quality():
    p, n = _apply_stock_sd15("a dragon", "")
    # Style-neutral quality tags must be present.
    assert "masterpiece" in p
    assert "best quality" in p
    assert "highly detailed" in p
    # Crucially, NO camera / film-stock branding — those bias the base
    # model into a flat photoreal aesthetic.
    assert "DSLR" not in p
    assert "Fujifilm" not in p
    assert "RAW photo" not in p
    # Negative bans anatomy/artifacts but MUST NOT ban styles; the base
    # model needs to stay able to draw cartoons/paintings on request.
    assert "bad anatomy" in n
    assert "cartoon" not in n
    assert "drawing" not in n
    assert "painting" not in n


def case_stock_sd15_applicator_preserves_user_prompt():
    p, n = _apply_stock_sd15("anime girl in a garden", "")
    assert "anime girl in a garden" in p


def case_zpop_aio_applicator_injects_trigger_once():
    p, n = _apply_zpop_aio("a wizard casting a spell", "")
    # Model REQUIRES this trigger to activate its style head.
    assert p.lower().count("zpop style") == 1


def case_zpop_aio_applicator_preserves_existing_trigger():
    # User already typed the trigger — must not duplicate.
    p, n = _apply_zpop_aio("Zpop Style portrait of a knight", "")
    assert p.lower().count("zpop style") == 1


def case_zpop_aio_applicator_does_not_force_pop_art():
    p, n = _apply_zpop_aio("a photograph of a castle", "")
    # AIO can do photo/cinematic on request; pop-art forcing must stay off.
    assert "pop art" not in p.lower()
    assert "bold outlines" not in p.lower()
    assert "saturated colors" not in p.lower()


def case_zpop_aio_applicator_does_not_ban_photoreal():
    _, n = _apply_zpop_aio("a photograph of a castle", "")
    # AIO merges CAN render photorealistic output — that must not be
    # negatived away.
    assert "photorealistic" not in n.lower()


# ── End-to-end: profile_for + apply_profile resolution ─────────────────

def case_profile_for_picks_stock_sd15():
    p = profile_for("v1-5-pruned-emaonly.safetensors")
    assert p is not None
    assert p["arch_family"] == "sd15"
    assert callable(p.get("applicator"))


def case_profile_for_picks_zpop_aio():
    p = profile_for("gonzalomoZpop_v30AIO.safetensors")
    assert p is not None
    assert p["arch_family"] == "zit"
    assert callable(p.get("applicator"))


def case_profile_for_still_picks_sdxl_juggernaut():
    # Regression: the new callable matchers must not steal matches
    # from the existing substring-matched entries.
    p = profile_for("juggernautXL_v9Rundiffusionphoto2.safetensors")
    assert p is not None
    assert p["arch_family"] == "sdxl"


def case_profile_for_pure_zpop_still_hits_catchall():
    # Regression: non-AIO Zpop variants must still get the aggressive
    # pop-art injection from the generic `"zpop"` entry.
    p = profile_for("zpop_pop_art_v1.safetensors")
    assert p is not None
    assert p["arch_family"] == "zit"
    # The generic catch-all uses prefix/suffix, NOT an applicator.
    assert not callable(p.get("applicator"))
    assert "pop art" in (p.get("prompt_prefix", "") or "").lower() \
        or "zpop style" in (p.get("prompt_prefix", "") or "").lower()


def case_apply_profile_delegates_to_applicator_for_sd15():
    p = profile_for("v1-5-pruned-emaonly.safetensors")
    prompt, neg = apply_profile("an epic forest", "ugly", p)
    # Delegated to _apply_stock_sd15 — neutral quality tags present,
    # style bans absent from negative.
    assert "masterpiece" in prompt
    assert "DSLR" not in prompt
    assert "cartoon" not in neg


def case_apply_profile_delegates_to_applicator_for_zpop_aio():
    p = profile_for("gonzalomoZpop_v30AIO.safetensors")
    prompt, neg = apply_profile("a portrait of a wizard", "blurry", p)
    assert "zpop style" in prompt.lower()
    assert "pop art" not in prompt.lower()
    assert "photorealistic" not in neg.lower()


def case_apply_profile_none_passthrough():
    # Regression: apply_profile(..., None) returns inputs unchanged.
    p, n = apply_profile("hi", "no", None)
    assert p == "hi"
    assert n == "no"


def case_broken_detector_does_not_crash():
    # Regression: a callable that raises shouldn't break profile_for.
    # We simulate by temporarily monkey-patching PROFILES with a
    # broken matcher at the front.
    from spellcaster_core import model_prompt_profiles as m
    orig = m.PROFILES
    try:
        broken = {"match": lambda _name: (_ for _ in ()).throw(RuntimeError("boom"))}
        m.PROFILES = [broken] + orig
        # Should NOT raise — the try/except inside profile_for catches
        # the RuntimeError and falls through to the next candidate.
        result = m.profile_for("v1-5-pruned-emaonly.safetensors")
        assert result is not None
        assert result["arch_family"] == "sd15"
    finally:
        m.PROFILES = orig


# ── Runner ─────────────────────────────────────────────────────────────

CASES = [
    ("detect: stock SD1.5 canonical",              case_stock_sd15_canonical),
    ("detect: stock SD1.5 rename variants",        case_stock_sd15_rename_variants),
    ("detect: stock SD1.5 excludes finetunes",     case_stock_sd15_excludes_finetunes),
    ("detect: stock SD1.5 excludes SDXL",          case_stock_sd15_excludes_sdxl),
    ("detect: Zpop AIO canonical",                 case_zpop_aio_canonical),
    ("detect: Zpop AIO variant markers",           case_zpop_aio_variant_markers),
    ("detect: Zpop AIO excludes pre-AIO",          case_zpop_aio_excludes_pre_aio),
    ("detect: Zpop AIO excludes non-Zpop",         case_zpop_aio_excludes_non_zpop),

    ("apply: SD1.5 base neutral quality tags",     case_stock_sd15_applicator_adds_neutral_quality),
    ("apply: SD1.5 base preserves user prompt",    case_stock_sd15_applicator_preserves_user_prompt),
    ("apply: Zpop AIO injects trigger once",       case_zpop_aio_applicator_injects_trigger_once),
    ("apply: Zpop AIO preserves typed trigger",    case_zpop_aio_applicator_preserves_existing_trigger),
    ("apply: Zpop AIO does not force pop art",     case_zpop_aio_applicator_does_not_force_pop_art),
    ("apply: Zpop AIO does not ban photoreal",     case_zpop_aio_applicator_does_not_ban_photoreal),

    ("e2e: profile_for picks stock SD1.5",         case_profile_for_picks_stock_sd15),
    ("e2e: profile_for picks Zpop AIO",            case_profile_for_picks_zpop_aio),
    ("e2e: JuggernautXL unchanged",                case_profile_for_still_picks_sdxl_juggernaut),
    ("e2e: pure Zpop still hits catch-all",        case_profile_for_pure_zpop_still_hits_catchall),
    ("e2e: apply_profile delegates for SD1.5",     case_apply_profile_delegates_to_applicator_for_sd15),
    ("e2e: apply_profile delegates for Zpop AIO",  case_apply_profile_delegates_to_applicator_for_zpop_aio),
    ("e2e: apply_profile None -> passthrough",     case_apply_profile_none_passthrough),
    ("robustness: broken detector skipped",        case_broken_detector_does_not_crash),
]


def main():
    print("model_prompt_profiles specialised-handler tests")
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
