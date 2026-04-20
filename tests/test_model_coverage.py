"""Tests for the expanded architecture registry + supported_methods
gating + size-aware checkpoint fallback.

Guards against the regressions called out in the flexibility audit:

  * 12 arch keys the detector could emit but that used to silently
    fall back to SDXL → now registered as first-class ArchConfigs
    (or explicit stubs where no builder exists yet).
  * UI advertising methods that crash at dispatch (video archs
    listing txt2img / img2img) → `supported_methods` gating.
  * Unknown checkpoint falling back to SD 1.5 regardless of file
    size → new `fallback_arch_for_size` heuristic.

Run:
    PYTHONPATH=comfyui-spellcaster python tests/test_model_coverage.py
"""
from __future__ import annotations

import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for p in (os.path.join(_REPO, "comfyui-spellcaster"), _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


from spellcaster_core.architectures import (  # noqa: E402
    ARCHITECTURES, get_arch, IMAGE_METHODS, VIDEO_METHODS, ALL_IMAGE_METHODS,
)
from spellcaster_core.model_detect import (  # noqa: E402
    classify_ckpt_model, classify_unet_model, fallback_arch_for_size,
    UNET_ARCH_RULES, CKPT_ARCH_RULES,
)


# Every arch key the detector can emit MUST appear in ARCHITECTURES
# so `get_arch(key)` returns a real config instead of silently falling
# back to sdxl. The fallback masks silent failures at dispatch time.
_DETECTOR_ARCHS = {arch for _kw, arch in UNET_ARCH_RULES}
_DETECTOR_ARCHS |= {arch for _kw, arch in CKPT_ARCH_RULES}


def case_every_detected_arch_is_registered():
    missing = sorted(a for a in _DETECTOR_ARCHS if a not in ARCHITECTURES)
    assert not missing, (
        f"Detector can emit these archs that aren't in ARCHITECTURES: "
        f"{missing}. Each arch needs at least a stub _reg() entry so "
        f"get_arch() returns a real config instead of silently falling "
        f"back to SDXL."
    )


def case_registered_archs_have_supported_methods():
    for key, arch in ARCHITECTURES.items():
        assert isinstance(arch.supported_methods, tuple), (
            f"{key}: supported_methods must be a tuple, got "
            f"{type(arch.supported_methods).__name__}"
        )


def case_video_archs_do_not_claim_txt2img():
    for key in ("wan", "ltx", "seedvr", "cogvideo"):
        arch = ARCHITECTURES[key]
        assert not arch.supports_method("txt2img"), (
            f"{key}: video arch advertised txt2img; UI would list a method "
            f"that crashes at dispatch"
        )
        assert not arch.supports_method("img2img"), f"{key}: img2img claimed"


def case_image_archs_advertise_core_methods():
    for key in ("sd15", "sdxl", "illustrious", "zit", "flux1dev",
                 "flux2klein", "flux_kontext", "chroma",
                 "sdxl_turbo", "pony", "playground"):
        arch = ARCHITECTURES[key]
        for m in ("txt2img", "img2img", "inpaint", "upscale"):
            assert arch.supports_method(m), f"{key}: missing core method {m!r}"


def case_klein_owns_klein_specific_methods():
    klein = ARCHITECTURES["flux2klein"]
    for m in ("klein_edit", "klein_headswap", "klein_repose", "klein_refine"):
        assert klein.supports_method(m), f"flux2klein missing {m!r}"
    # Other archs must NOT claim klein-specific methods
    sdxl = ARCHITECTURES["sdxl"]
    assert not sdxl.supports_method("klein_headswap")


def case_seedvr_is_upscale_only():
    seedvr = ARCHITECTURES["seedvr"]
    assert seedvr.supports_method("video_upscale")
    assert not seedvr.supports_method("video_gen")
    assert not seedvr.supports_method("txt2img")


def case_dit_stubs_register_false_with_no_methods():
    """DiT-based archs (sd3, hunyuan_dit, pixart, auraflow, kolors)
    have no builder coverage yet. They MUST be stubs — summoning a
    wizard for them must not list methods that would crash."""
    for key in ("sd3", "sd3_turbo", "hunyuan_dit", "pixart", "auraflow", "kolors"):
        arch = ARCHITECTURES[key]
        assert not arch.registered, f"{key}: expected stub (registered=False)"
        assert arch.supported_methods == (), (
            f"{key}: stub must advertise no methods; got {arch.supported_methods}"
        )


def case_sdxl_turbo_has_turbo_defaults():
    t = ARCHITECTURES["sdxl_turbo"]
    assert t.default_steps <= 8
    assert t.default_cfg <= 2.0
    assert t.supports_method("txt2img")


def case_pony_has_booru_score_cascade_guidance():
    p = ARCHITECTURES["pony"]
    assert p.prompt_style == "booru_tags"
    # Pony's score cascade is the defining feature of its prompt style
    assert "score_" in p.autoset_prompts[0].lower()
    # Negative should include low scores
    assert "score_4" in p.autoset_prompts[1].lower()


# ── Size-aware fallback ────────────────────────────────────────────────

def case_fallback_size_heuristic():
    assert fallback_arch_for_size(None) is None
    assert fallback_arch_for_size(0) is None
    assert fallback_arch_for_size(-5) is None
    # Classic SD 1.5 sizes
    assert fallback_arch_for_size(2 * 1024**3) == "sd15"   # 2 GB
    assert fallback_arch_for_size(4 * 1024**3) == "sd15"   # 4 GB (boundary)
    # SDXL territory
    assert fallback_arch_for_size(5 * 1024**3) == "sdxl"
    assert fallback_arch_for_size(int(6.5 * 1024**3)) == "sdxl"
    # Flux territory
    assert fallback_arch_for_size(12 * 1024**3) == "flux1dev"
    assert fallback_arch_for_size(23 * 1024**3) == "flux1dev"


def case_unknown_checkpoint_uses_size_hint():
    """The poster-child bug: a 6 GB SDXL merge with a truly generic
    name. Without size hint it falls back to SD 1.5 (wrong — 512×512
    defaults, wrong sampler). With size, it correctly routes to SDXL.
    The name picked here avoids ALL keyword rules in CKPT_ARCH_RULES
    (no turbo / no xl / no illu / no flux / etc.)."""
    name = "aardvark_v42_mix.safetensors"
    assert classify_ckpt_model(name) == "sd15"
    assert classify_ckpt_model(name, file_size=6 * 1024**3) == "sdxl"
    assert classify_ckpt_model(name, file_size=3 * 1024**3) == "sd15"
    assert classify_ckpt_model(name, file_size=15 * 1024**3) == "flux1dev"


def case_known_names_beat_size_hint():
    """Keyword rules take precedence over the size heuristic — a model
    whose name explicitly matches a CKPT_ARCH_RULES entry keeps its
    arch regardless of size."""
    # SDXL keyword wins even at 1 GB
    assert classify_ckpt_model("tiny_sdxl_mix.safetensors",
                                 file_size=1 * 1024**3) == "sdxl"
    # Illustrious keyword wins at any size
    assert classify_ckpt_model("illu_anime_v3.safetensors",
                                 file_size=20 * 1024**3) == "illustrious"
    # Flux keyword wins at any size
    assert classify_ckpt_model("flux_dev_q8.safetensors",
                                 file_size=1 * 1024**3) == "flux1dev"


# ── Arch config sanity (guard defaults for new archs) ─────────────────

def case_every_arch_has_sensible_defaults():
    for key, arch in ARCHITECTURES.items():
        assert arch.default_steps > 0, f"{key}: default_steps invalid"
        assert arch.default_cfg > 0, f"{key}: default_cfg invalid"
        w, h = arch.default_resolution
        assert w >= 256 and h >= 256, f"{key}: default_resolution too small"
        assert arch.default_sampler, f"{key}: default_sampler empty"
        assert arch.default_scheduler, f"{key}: default_scheduler empty"


CASES = [
    ("registry: every detected arch is registered",       case_every_detected_arch_is_registered),
    ("registry: every arch has supported_methods tuple",  case_registered_archs_have_supported_methods),
    ("gating: video archs hide txt2img/img2img",          case_video_archs_do_not_claim_txt2img),
    ("gating: image archs expose core methods",           case_image_archs_advertise_core_methods),
    ("gating: Klein owns klein_* methods",                case_klein_owns_klein_specific_methods),
    ("gating: SeedVR is upscale-only",                    case_seedvr_is_upscale_only),
    ("stubs: DiT archs are registered=False + no methods", case_dit_stubs_register_false_with_no_methods),
    ("turbo: sdxl_turbo defaults use fast sampler",       case_sdxl_turbo_has_turbo_defaults),
    ("pony: autoset has booru score cascade",             case_pony_has_booru_score_cascade_guidance),
    ("fallback: size heuristic picks right arch",         case_fallback_size_heuristic),
    ("fallback: unknown checkpoint uses size hint",       case_unknown_checkpoint_uses_size_hint),
    ("fallback: known-name keywords beat size hint",      case_known_names_beat_size_hint),
    ("sanity: every arch has sensible defaults",          case_every_arch_has_sensible_defaults),
]


def main():
    print("model coverage + arch registry tests")
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
