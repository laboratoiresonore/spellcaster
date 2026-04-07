#!/usr/bin/env python3
"""Golden tests: verify v2 workflow builders produce identical output to originals.

Run from the comfyui-connector directory:
    python test_golden.py

These tests import the new modular builders and compare their output against
hardcoded expected workflow dicts captured from the current production code.
This ensures zero regression during migration.
"""

import sys
import json

# Add current directory to path for imports
sys.path.insert(0, ".")

from _nodes import NodeFactory
from _architectures import ARCHITECTURES, get_arch
from _workflows_v2 import (
    build_rembg, build_upscale, build_lama_remove, build_lut,
    build_klein_img2img, build_txt2img,
    build_faceswap, build_faceswap_model, build_save_face_model,
    build_faceswap_mtb, build_face_restore, build_photo_restore,
    build_detail_hallucinate, build_colorize, build_controlnet_gen,
    build_iclight, build_supir, build_inpaint, build_outpaint,
    build_faceid_img2img, build_pulid_flux, build_img2img,
    build_klein_img2img_ref, build_klein_headswap,
    build_video_upscale, build_video_reactor,
    build_wan_video, build_wan_flf, build_seedvr2_video_upscale,
)


def dict_equal(a, b, path=""):
    """Deep compare two dicts, reporting first difference."""
    if type(a) != type(b):
        return False, f"{path}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            extra_a = set(a.keys()) - set(b.keys())
            extra_b = set(b.keys()) - set(a.keys())
            return False, f"{path}: keys differ. a_extra={extra_a}, b_extra={extra_b}"
        for k in a:
            ok, msg = dict_equal(a[k], b[k], f"{path}.{k}")
            if not ok:
                return False, msg
        return True, ""
    if isinstance(a, list):
        if len(a) != len(b):
            return False, f"{path}: list length {len(a)} != {len(b)}"
        for i, (ai, bi) in enumerate(zip(a, b)):
            ok, msg = dict_equal(ai, bi, f"{path}[{i}]")
            if not ok:
                return False, msg
        return True, ""
    if a != b:
        return False, f"{path}: {a!r} != {b!r}"
    return True, ""


def test_rembg():
    """Test build_rembg produces expected workflow."""
    wf = build_rembg("test_image.png")
    expected = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": "test_image.png"}},
        "2": {"class_type": "Image Rembg (Remove Background)",
              "inputs": {
                  "images": ["1", 0],
                  "transparency": True,
                  "model": "isnet-general-use",
                  "post_processing": False,
                  "only_mask": False,
                  "alpha_matting": False,
                  "alpha_matting_foreground_threshold": 240,
                  "alpha_matting_background_threshold": 10,
                  "alpha_matting_erode_size": 10,
                  "background_color": "none",
              }},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "spellcaster_rembg"}},
    }
    ok, msg = dict_equal(wf, expected)
    return ok, "rembg", msg


def test_upscale():
    """Test build_upscale produces expected workflow."""
    wf = build_upscale("test_image.png", "4x-UltraSharp.pth", 1.5)
    expected = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": "test_image.png"}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "3": {"class_type": "ImageUpscaleWithModelByFactor",
              "inputs": {"upscale_model": ["2", 0], "image": ["1", 0],
                         "scale_by": 1.5}},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "spellcaster_upscale"}},
    }
    ok, msg = dict_equal(wf, expected)
    return ok, "upscale", msg


def test_lama():
    """Test build_lama_remove produces expected workflow."""
    wf = build_lama_remove("test_image.png", "test_mask.png")
    expected = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": "test_image.png"}},
        "2": {"class_type": "LoadImage",
              "inputs": {"image": "test_mask.png"}},
        "5": {"class_type": "ImageToMask",
              "inputs": {"image": ["2", 0], "channel": "red"}},
        "3": {"class_type": "LamaRemover",
              "inputs": {"images": ["1", 0], "masks": ["5", 0],
                         "mask_threshold": 0.5, "gaussblur_radius": 8,
                         "invert_mask": False}},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": "spellcaster_lama"}},
    }
    ok, msg = dict_equal(wf, expected)
    return ok, "lama", msg


def test_lut():
    """Test build_lut produces expected workflow."""
    wf = build_lut("test_image.png", "Rec709_Kodak_2383_D65.cube", 0.8)
    expected = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": "test_image.png"}},
        "2": {"class_type": "ImageApplyLUT+",
              "inputs": {"image": ["1", 0],
                         "lut_file": "Rec709_Kodak_2383_D65.cube",
                         "strength": 0.8, "log": False,
                         "clip_values": True, "gamma_correction": False}},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "spellcaster_lut"}},
    }
    ok, msg = dict_equal(wf, expected)
    return ok, "lut", msg


def test_txt2img_sdxl():
    """Test build_txt2img with SDXL preset."""
    preset = {
        "arch": "sdxl", "ckpt": "SDXL\\Base\\AlbedoBaseXL.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0, "denoise": 0.62,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    }
    wf = build_txt2img(preset, "a cat", "blurry", 42)

    # Verify structure
    assert "1" in wf, "Missing checkpoint loader"
    assert wf["1"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["1"]["inputs"]["ckpt_name"] == "SDXL\\Base\\AlbedoBaseXL.safetensors"
    assert "2" in wf and wf["2"]["class_type"] == "CLIPTextEncode"
    assert wf["2"]["inputs"]["text"] == "a cat"
    assert "3" in wf and wf["3"]["class_type"] == "CLIPTextEncode"
    assert wf["3"]["inputs"]["text"] == "blurry"
    assert "4" in wf and wf["4"]["class_type"] == "EmptyLatentImage"
    assert wf["4"]["inputs"]["width"] == 1024
    assert "5" in wf and wf["5"]["class_type"] == "KSampler"
    assert wf["5"]["inputs"]["seed"] == 42
    assert wf["5"]["inputs"]["denoise"] == 1.0  # Always 1.0 for txt2img
    assert wf["5"]["inputs"]["steps"] == 25
    assert "6" in wf and wf["6"]["class_type"] == "VAEDecode"
    assert "7" in wf and wf["7"]["class_type"] == "SaveImage"
    return True, "txt2img_sdxl", ""


def test_txt2img_flux():
    """Test build_txt2img with Flux preset (no negative prompt)."""
    preset = {
        "arch": "flux1dev", "ckpt": "flux1-dev-fp8.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 3.5, "denoise": 0.55,
        "sampler": "euler", "scheduler": "simple",
    }
    wf = build_txt2img(preset, "a dog", "", 99)

    # Flux uses UNETLoader + DualCLIPLoader + VAELoader
    assert wf["1"]["class_type"] == "UNETLoader"
    assert "1b" in wf and wf["1b"]["class_type"] == "DualCLIPLoader"
    assert "1c" in wf and wf["1c"]["class_type"] == "VAELoader"

    # Negative should be ConditioningZeroOut (no negative for Flux)
    assert wf["3"]["class_type"] == "ConditioningZeroOut"
    return True, "txt2img_flux", ""


def test_klein_img2img():
    """Test build_klein_img2img produces expected structure."""
    wf = build_klein_img2img(
        "test_image.png", "Klein 9B", "a portrait", 42,
        steps=4, guidance=1.0,
    )

    # Verify Klein architecture: UNETLoader + CLIPLoader(flux2) + VAELoader
    assert wf["1"]["class_type"] == "UNETLoader"
    assert "flux-2-klein-9b" in wf["1"]["inputs"]["unet_name"]
    assert wf["2"]["class_type"] == "CLIPLoader"
    assert wf["2"]["inputs"]["type"] == "flux2"
    assert "qwen_3_8b" in wf["2"]["inputs"]["clip_name"]  # 9B → qwen_3_8b
    assert wf["3"]["class_type"] == "VAELoader"
    assert wf["3"]["inputs"]["vae_name"] == "flux2-vae.safetensors"

    # Klein sampling: ReferenceLatent + CFGGuider + Flux2Scheduler + SamplerCustomAdvanced
    assert wf["20"]["class_type"] == "ReferenceLatent"
    assert wf["21"]["class_type"] == "ReferenceLatent"
    assert wf["30"]["class_type"] == "CFGGuider"
    assert wf["31"]["class_type"] == "KSamplerSelect"
    assert wf["32"]["class_type"] == "Flux2Scheduler"
    # Flux2Scheduler should NOT have model, denoise, max_shift, base_shift
    sched_inputs = wf["32"]["inputs"]
    assert "model" not in sched_inputs, "Flux2Scheduler should not have 'model' input"
    assert "denoise" not in sched_inputs, "Flux2Scheduler should not have 'denoise' input"
    assert "steps" in sched_inputs
    assert "width" in sched_inputs
    assert "height" in sched_inputs
    assert wf["33"]["class_type"] == "RandomNoise"
    assert wf["40"]["class_type"] == "SamplerCustomAdvanced"

    # Output
    assert wf["50"]["class_type"] == "VAEDecode"
    assert wf["51"]["class_type"] == "SaveImage"
    assert wf["51"]["inputs"]["filename_prefix"] == "gimp_klein"

    return True, "klein_img2img", ""


def test_node_factory_auto_id():
    """Test NodeFactory auto-ID assignment."""
    nf = NodeFactory()
    a = nf.load_image("a.png")
    b = nf.load_image("b.png")
    c = nf.save_image([b, 0], "test")
    assert a == "1", f"Expected '1', got '{a}'"
    assert b == "2", f"Expected '2', got '{b}'"
    assert c == "3", f"Expected '3', got '{c}'"
    return True, "auto_id", ""


def test_node_factory_explicit_id():
    """Test NodeFactory explicit ID assignment."""
    nf = NodeFactory()
    a = nf.load_image("a.png", node_id="10")
    b = nf.load_image("b.png")  # Should be 11 (after 10)
    c = nf.load_image("c.png", node_id="5")  # Explicit lower ID
    d = nf.load_image("d.png")  # Should be 12 (max was 11)
    assert a == "10", f"Expected '10', got '{a}'"
    assert b == "11", f"Expected '11', got '{b}'"
    assert c == "5", f"Expected '5', got '{c}'"
    # After explicit "5", next auto should still be 12 (not 6)
    assert d == "12", f"Expected '12', got '{d}'"
    wf = nf.build()
    assert set(wf.keys()) == {"10", "11", "5", "12"}
    return True, "explicit_id", ""


def test_architecture_registry():
    """Test architecture registry is complete and consistent."""
    expected_archs = ["sd15", "sdxl", "illustrious", "zit", "flux1dev", "flux2klein", "flux_kontext"]
    for key in expected_archs:
        assert key in ARCHITECTURES, f"Missing architecture: {key}"
        arch = ARCHITECTURES[key]
        assert arch.key == key
        assert arch.default_steps > 0
        assert arch.default_cfg > 0

    # Verify Flux architectures don't support negative
    assert not ARCHITECTURES["flux1dev"].supports_negative
    assert not ARCHITECTURES["flux2klein"].supports_negative
    assert not ARCHITECTURES["flux_kontext"].supports_negative

    # Verify SD/SDXL architectures DO support negative
    assert ARCHITECTURES["sd15"].supports_negative
    assert ARCHITECTURES["sdxl"].supports_negative
    assert ARCHITECTURES["illustrious"].supports_negative

    # Verify loader types
    assert ARCHITECTURES["sd15"].loader == "checkpoint"
    assert ARCHITECTURES["sdxl"].loader == "checkpoint"
    assert ARCHITECTURES["flux1dev"].loader == "unet_clip_vae"
    assert ARCHITECTURES["flux2klein"].loader == "unet_clip_vae"

    # Verify Klein has custom_advanced sampler
    assert ARCHITECTURES["flux2klein"].sampler == "custom_advanced"

    return True, "arch_registry", ""


def test_klein_4b_clip_selection():
    """Test that Klein 4B uses qwen_3_4b instead of qwen_3_8b."""
    wf = build_klein_img2img(
        "test.png", "Klein 4B", "test", 42,
    )
    assert "qwen_3_4b" in wf["2"]["inputs"]["clip_name"], \
        f"Klein 4B should use qwen_3_4b, got: {wf['2']['inputs']['clip_name']}"
    return True, "klein_4b_clip", ""


def test_faceswap():
    """Test build_faceswap produces expected structure."""
    wf = build_faceswap("target.png", "source.png")
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["2"]["class_type"] == "LoadImage"
    assert wf["3"]["class_type"] == "ReActorFaceSwapOpt"
    assert wf["3"]["inputs"]["source_image"] == ["2", 0]
    assert wf["3"]["inputs"]["swap_model"] == "inswapper_128.onnx"
    assert wf["4"]["class_type"] == "ReActorOptions"
    assert wf["5"]["class_type"] == "ReActorFaceBoost"
    assert wf["3"]["inputs"]["options"] == ["4", 0]
    assert wf["3"]["inputs"]["face_boost"] == ["5", 0]
    assert wf["10"]["class_type"] == "SaveImage"
    assert wf["10"]["inputs"]["images"] == ["3", 0]
    return True, "faceswap", ""


def test_faceswap_double_pass():
    """Test faceswap double-pass with quality preset."""
    presets = {
        "Ultra": {
            "pass1_model": "inswapper_128.onnx",
            "pass1_restore": "codeformer-v0.1.0.pth",
            "pass1_vis": 1.0, "pass1_cf": 0.7,
            "double_pass": True,
            "pass2_model": "inswapper_128_fp16.onnx",
            "pass2_restore": "GFPGANv1.4.pth",
            "pass2_vis": 1.0, "pass2_cf": 0.5,
        }
    }
    wf = build_faceswap("t.png", "s.png", quality_preset="Ultra", quality_presets=presets)
    assert "20" in wf and wf["20"]["class_type"] == "ReActorFaceSwapOpt"
    assert wf["20"]["inputs"]["input_image"] == ["3", 0]  # Chains from pass 1
    assert wf["20"]["inputs"]["swap_model"] == "inswapper_128_fp16.onnx"
    assert wf["10"]["inputs"]["images"] == ["20", 0]  # Output from pass 2
    return True, "faceswap_double", ""


def test_faceswap_model():
    """Test build_faceswap_model uses saved face model."""
    wf = build_faceswap_model("target.png", "my_face.safetensors")
    assert wf["2"]["class_type"] == "ReActorLoadFaceModel"
    assert wf["2"]["inputs"]["face_model"] == "my_face.safetensors"
    assert wf["3"]["class_type"] == "ReActorFaceSwapOpt"
    assert "face_model" in wf["3"]["inputs"]
    assert wf["3"]["inputs"]["face_model"] == ["2", 0]
    assert "source_image" not in wf["3"]["inputs"]
    return True, "faceswap_model", ""


def test_save_face_model():
    """Test build_save_face_model."""
    wf = build_save_face_model("face.png", "my_model")
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["2"]["class_type"] == "ReActorBuildFaceModel"
    assert wf["2"]["inputs"]["images"] == ["1", 0]
    assert wf["3"]["class_type"] == "ReActorSaveFaceModel"
    assert wf["3"]["inputs"]["face_model_name"] == "my_model"
    assert wf["3"]["inputs"]["save_mode"] == "overwrite"
    assert wf["4"]["class_type"] == "SaveImage"
    return True, "save_face_model", ""


def test_faceswap_mtb():
    """Test build_faceswap_mtb."""
    wf = build_faceswap_mtb("target.png", "source.png")
    assert wf["3"]["class_type"] == "Load Face Analysis Model (mtb)"
    assert wf["4"]["class_type"] == "Load Face Swap Model (mtb)"
    assert wf["5"]["class_type"] == "Face Swap (mtb)"
    assert wf["10"]["class_type"] == "SaveImage"
    return True, "faceswap_mtb", ""


def test_face_restore():
    """Test build_face_restore."""
    wf = build_face_restore("img.png", "codeformer-v0.1.0.pth", "retinaface_resnet50", 1.0, 0.7)
    expected = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "img.png"}},
        "2": {"class_type": "ReActorRestoreFace",
              "inputs": {"image": ["1", 0], "facedetection": "retinaface_resnet50",
                         "model": "codeformer-v0.1.0.pth", "visibility": 1.0,
                         "codeformer_weight": 0.7}},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "spellcaster_facerestore"}},
    }
    ok, msg = dict_equal(wf, expected)
    return ok, "face_restore", msg


def test_photo_restore():
    """Test build_photo_restore pipeline structure."""
    wf = build_photo_restore("img.png", "4x-UltraSharp.pth", "codeformer-v0.1.0.pth",
                              "retinaface_resnet50", 1.0, 0.7, 1, 1.0, 1.5)
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["2"]["class_type"] == "UpscaleModelLoader"
    assert wf["3"]["class_type"] == "ImageUpscaleWithModelByFactor"
    assert wf["3"]["inputs"]["scale_by"] == 1.0
    assert wf["4"]["class_type"] == "ReActorRestoreFace"
    assert wf["4"]["inputs"]["image"] == ["3", 0]  # Chains from upscale
    assert wf["5"]["class_type"] == "ImageSharpen"
    assert wf["5"]["inputs"]["image"] == ["4", 0]  # Chains from face restore
    assert wf["6"]["class_type"] == "SaveImage"
    return True, "photo_restore", ""


def test_detail_hallucinate():
    """Test build_detail_hallucinate structure."""
    preset = {
        "arch": "sdxl", "ckpt": "test.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    }
    wf = build_detail_hallucinate(
        "img.png", "4x-UltraSharp.pth", preset,
        "detailed photo", "blurry", 42, 0.35, 7.0,
        upscale_factor=1.5,
    )
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["2"]["class_type"] == "UpscaleModelLoader"
    assert wf["3"]["class_type"] == "ImageUpscaleWithModelByFactor"
    assert wf["4"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["8"]["class_type"] == "KSampler"
    assert wf["8"]["inputs"]["denoise"] == 0.35
    assert wf["10"]["class_type"] == "SaveImage"
    return True, "detail_hallucinate", ""


def test_detail_hallucinate_no_upscale():
    """Test detail_hallucinate without upscale model."""
    preset = {
        "arch": "sdxl", "ckpt": "test.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0,
        "sampler": "euler", "scheduler": "normal",
    }
    wf = build_detail_hallucinate(
        "img.png", None, preset, "prompt", "neg", 42, 0.3, 7.0,
    )
    # No upscale nodes
    assert "2" not in wf
    assert "3" not in wf
    # KSampler latent_image should trace back to VAEEncode of the raw image
    assert wf["7"]["class_type"] == "VAEEncode"
    assert wf["7"]["inputs"]["pixels"] == ["1", 0]
    return True, "detail_no_upscale", ""


def test_controlnet_gen():
    """Test build_controlnet_gen structure."""
    preset = {
        "arch": "sdxl", "ckpt": "test.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0,
        "sampler": "euler", "scheduler": "normal",
    }
    wf = build_controlnet_gen(
        "img.png", "ScribblePreprocessor", "cn_model.safetensors",
        preset, "a dog", "blurry", 42, 1024, 1024,
        25, 7.0, "euler", "normal",
    )
    assert wf["2"]["class_type"] == "ScribblePreprocessor"
    assert wf["4"]["class_type"] == "ControlNetLoader"
    assert wf["7"]["class_type"] == "ControlNetApplyAdvanced"
    assert wf["8"]["class_type"] == "EmptyLatentImage"
    assert wf["9"]["class_type"] == "KSampler"
    assert wf["9"]["inputs"]["denoise"] == 1.0
    return True, "controlnet_gen", ""


def test_iclight():
    """Test build_iclight structure."""
    wf = build_iclight("img.png", "sd15.safetensors", "soft light", "dark", 42)
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["2"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["10"]["class_type"] == "VAEEncode"
    assert wf["10"]["inputs"]["pixels"] == ["1", 0]  # Foreground to latent
    assert wf["3"]["class_type"] == "LoadAndApplyICLightUnet"
    assert wf["6"]["class_type"] == "ICLightConditioning"
    assert wf["6"]["inputs"]["foreground"] == ["10", 0]  # LATENT foreground
    assert wf["6"]["inputs"]["multiplier"] == 0.18
    assert wf["7"]["class_type"] == "KSampler"
    assert wf["7"]["inputs"]["model"] == ["3", 0]  # IC-Light model
    assert wf["7"]["inputs"]["positive"] == ["6", 0]  # ICLight cond outputs
    assert wf["7"]["inputs"]["negative"] == ["6", 1]
    assert wf["7"]["inputs"]["latent_image"] == ["6", 2]
    return True, "iclight", ""


def test_supir():
    """Test build_supir 5-stage pipeline structure."""
    wf = build_supir("img.png", "supir_model.safetensors", "sdxl.safetensors",
                      "sharp photo", 42)
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["10"]["class_type"] == "SUPIR_model_loader"
    assert wf["20"]["class_type"] == "SUPIR_first_stage"
    assert wf["30"]["class_type"] == "SUPIR_conditioner"
    assert wf["40"]["class_type"] == "SUPIR_sample"
    assert wf["50"]["class_type"] == "SUPIR_decode"
    assert wf["60"]["class_type"] == "SaveImage"
    # Verify chain connections
    assert wf["20"]["inputs"]["SUPIR_VAE"] == ["10", 1]
    assert wf["30"]["inputs"]["SUPIR_model"] == ["10", 0]
    assert wf["40"]["inputs"]["SUPIR_model"] == ["10", 0]
    assert wf["50"]["inputs"]["SUPIR_VAE"] == ["20", 0]
    return True, "supir", ""


def test_inpaint():
    """Test build_inpaint structure."""
    preset = {
        "arch": "sdxl", "ckpt": "test.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0, "denoise": 0.65,
        "sampler": "euler", "scheduler": "normal",
    }
    wf = build_inpaint("img.png", "mask.png", preset, "fill", "bad", 42)
    assert wf["4"]["class_type"] == "LoadImage"
    assert wf["5"]["class_type"] == "LoadImage"
    assert wf["51"]["class_type"] == "ImageToMask"
    assert wf["91"]["class_type"] == "ImageScale"
    assert wf["92"]["class_type"] == "ImageScale"
    assert wf["7"]["class_type"] == "SetLatentNoiseMask"
    assert wf["8"]["class_type"] == "KSampler"
    assert wf["95"]["class_type"] == "ImageScale"  # Restore to original size
    assert wf["10"]["class_type"] == "SaveImage"
    return True, "inpaint", ""


def test_outpaint():
    """Test build_outpaint structure."""
    preset = {
        "arch": "sdxl", "ckpt": "test.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0,
        "sampler": "euler", "scheduler": "normal",
    }
    wf = build_outpaint("img.png", preset, "extend", "bad", 42,
                          left=64, top=0, right=64, bottom=0, feathering=40)
    assert wf["5"]["class_type"] == "ImagePadForOutpaint"
    assert wf["5"]["inputs"]["left"] == 64
    assert wf["7"]["class_type"] == "SetLatentNoiseMask"
    assert wf["8"]["class_type"] == "KSampler"
    assert wf["8"]["inputs"]["denoise"] == 0.85
    assert wf["10"]["class_type"] == "SaveImage"
    return True, "outpaint", ""


def test_outpaint_klein():
    """Test outpaint with Klein falls back to KSampler (not SamplerCustomAdvanced)."""
    preset = {
        "arch": "flux2klein", "ckpt": "flux-2-klein-9b.safetensors",
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 3.5,
        "sampler": "euler", "scheduler": "simple",
    }
    wf = build_outpaint("img.png", preset, "extend", "bad", 42,
                          left=64, top=0, right=64, bottom=0, feathering=40)
    assert wf["8"]["class_type"] == "KSampler"  # NOT SamplerCustomAdvanced
    assert wf["8"]["inputs"]["denoise"] == 0.85
    return True, "outpaint_klein", ""


def test_faceid_img2img():
    """Test build_faceid_img2img structure."""
    preset = {
        "arch": "sdxl", "ckpt": "test.safetensors",
        "width": 1024, "height": 1024,
        "steps": 30, "cfg": 5.0, "denoise": 0.55,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    }
    wf = build_faceid_img2img("target.png", "face_ref.png", preset,
                               "portrait", "blurry", 42)
    assert wf["2"]["class_type"] == "IPAdapterUnifiedLoaderFaceID"
    assert wf["3"]["class_type"] == "LoadImage"  # face reference
    assert wf["4"]["class_type"] == "IPAdapterFaceID"
    assert wf["9"]["class_type"] == "KSampler"
    assert wf["9"]["inputs"]["model"] == ["4", 0]  # Model from FaceID
    return True, "faceid_img2img", ""


def test_pulid_flux1():
    """Test build_pulid_flux with Flux1-dev (PulidFlux* nodes)."""
    wf = build_pulid_flux("target.png", "face.png", "portrait", "", 42,
                            flux_model="Flux\\FLUX1 Dev fp8.safetensors")
    assert wf["1"]["class_type"] == "UNETLoader"
    assert wf["7"]["class_type"] == "DualCLIPLoader"  # Flux1 uses DualCLIP
    assert wf["2"]["class_type"] == "PulidFluxModelLoader"
    assert wf["3"]["class_type"] == "PulidFluxEvaClipLoader"
    assert wf["4"]["class_type"] == "PulidFluxInsightFaceLoader"
    assert wf["6"]["class_type"] == "ApplyPulidFlux"
    return True, "pulid_flux1", ""


def test_pulid_flux2():
    """Test build_pulid_flux with Flux2 Klein (PuLID* nodes)."""
    wf = build_pulid_flux("target.png", "face.png", "portrait", "", 42,
                            flux_model="A-Flux\\Flux2\\flux-2-klein-9b.safetensors")
    assert wf["1"]["class_type"] == "UNETLoader"
    assert wf["7"]["class_type"] == "CLIPLoader"  # Klein uses single CLIPLoader
    assert wf["7"]["inputs"]["type"] == "flux2"
    assert wf["2"]["class_type"] == "PuLIDModelLoader"
    assert wf["3"]["class_type"] == "PuLIDEVACLIPLoader"
    assert wf["4"]["class_type"] == "PuLIDInsightFaceLoader"
    assert wf["6"]["class_type"] == "ApplyPuLIDFlux2"
    return True, "pulid_flux2", ""


def test_colorize():
    """Test build_colorize structure."""
    preset = {
        "arch": "sdxl", "ckpt": "test.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0,
        "sampler": "euler", "scheduler": "normal",
    }
    wf = build_colorize("img.png", preset, "colorful photo", "bw", 42,
                          controlnet_strength=0.8, denoise=0.65,
                          lineart_models={"sdxl": "cn_lineart_xl.safetensors"})
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["2"]["class_type"] == "LineArtPreprocessor"
    assert wf["4"]["class_type"] == "ControlNetLoader"
    assert wf["7"]["class_type"] == "ControlNetApplyAdvanced"
    assert wf["9"]["class_type"] == "KSampler"
    assert wf["9"]["inputs"]["positive"] == ["7", 0]  # From ControlNet
    assert wf["11"]["class_type"] == "SaveImage"
    return True, "colorize", ""


def test_img2img_sdxl():
    """Test build_img2img with SDXL preset."""
    preset = {
        "arch": "sdxl", "ckpt": "test.safetensors",
        "width": 1024, "height": 1024,
        "steps": 25, "cfg": 7.0, "denoise": 0.65,
        "sampler": "dpmpp_2m_sde", "scheduler": "karras",
    }
    wf = build_img2img("img.png", preset, "a cat", "blurry", 42)
    assert wf["1"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["4"]["class_type"] == "LoadImage"
    assert wf["5"]["class_type"] == "VAEEncode"
    assert wf["6"]["class_type"] == "KSampler"
    assert wf["6"]["inputs"]["denoise"] == 0.65
    assert wf["7"]["class_type"] == "VAEDecode"
    assert wf["8"]["class_type"] == "SaveImage"
    return True, "img2img_sdxl", ""


# ═══════════════════════════════════════════════════════════════════════════
#  Klein Variant Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_klein_img2img_ref():
    """Test build_klein_img2img_ref with 9B model."""
    wf = build_klein_img2img_ref(
        "main.png", "ref.png", "Klein 9B",
        "a portrait", 42, steps=4, denoise=0.65, guidance=1.0,
    )
    # Model loaders
    assert wf["1"]["class_type"] == "UNETLoader"
    assert wf["2"]["class_type"] == "CLIPLoader"
    assert wf["2"]["inputs"]["type"] == "flux2"
    assert wf["3"]["class_type"] == "VAELoader"
    # Both images loaded
    assert wf["10"]["class_type"] == "LoadImage"
    assert wf["10"]["inputs"]["image"] == "main.png"
    assert wf["15"]["class_type"] == "LoadImage"
    assert wf["15"]["inputs"]["image"] == "ref.png"
    # ReferenceLatent for conditioning
    assert wf["20"]["class_type"] == "ReferenceLatent"
    assert wf["21"]["class_type"] == "ReferenceLatent"
    # SamplerCustomAdvanced path (Flux2Scheduler for non-denoise path)
    assert wf["30"]["class_type"] == "CFGGuider"
    assert wf["31"]["class_type"] == "KSamplerSelect"
    assert wf["32"]["class_type"] == "Flux2Scheduler"
    assert wf["40"]["class_type"] == "SamplerCustomAdvanced"
    assert wf["51"]["class_type"] == "SaveImage"
    return True, "klein_img2img_ref", ""


def test_klein_headswap():
    """Test build_klein_headswap structure — BasicScheduler for denoise."""
    wf = build_klein_headswap(
        "target.png", "source.png", "Klein 9B",
        "a portrait", 42, denoise=0.35, steps=20,
    )
    # Face swap stage
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["1"]["inputs"]["image"] == "target.png"
    assert wf["2"]["class_type"] == "LoadImage"
    assert wf["2"]["inputs"]["image"] == "source.png"
    assert wf["10"]["class_type"] == "ReActorFaceSwapOpt"
    assert wf["10o"]["class_type"] == "ReActorOptions"
    assert wf["10b"]["class_type"] == "ReActorFaceBoost"
    # Klein refinement stage
    assert wf["20"]["class_type"] == "UNETLoader"
    assert wf["21"]["class_type"] == "CLIPLoader"
    assert wf["21"]["inputs"]["type"] == "flux2"
    assert wf["22"]["class_type"] == "VAELoader"
    # Key: BasicScheduler (NOT Flux2Scheduler) for denoise support
    assert wf["42"]["class_type"] == "BasicScheduler"
    assert wf["42"]["inputs"]["denoise"] == 0.35
    assert wf["40"]["class_type"] == "CFGGuider"
    assert wf["50"]["class_type"] == "SamplerCustomAdvanced"
    assert wf["70"]["class_type"] == "SaveImage"
    return True, "klein_headswap", ""


def test_klein_headswap_face_model():
    """Test build_klein_headswap with saved face model instead of source image."""
    wf = build_klein_headswap(
        "target.png", "source.png", "Klein 4B",
        "a portrait", 42, face_model="my_face.safetensors",
    )
    # Should have face model loader
    assert wf["3"]["class_type"] == "ReActorLoadFaceModel"
    assert wf["3"]["inputs"]["face_model"] == "my_face.safetensors"
    # Source image should NOT be in swap node inputs (patched out)
    assert "source_image" not in wf["10"]["inputs"]
    # Klein 4B uses the smaller CLIP
    assert "qwen_3_4b" in wf["21"]["inputs"]["clip_name"]
    return True, "klein_headswap_face_model", ""


# ═══════════════════════════════════════════════════════════════════════════
#  Video Builder Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_video_upscale():
    """Test build_video_upscale structure."""
    wf = build_video_upscale("test.mp4", upscale_model="4x-UltraSharp.pth",
                              upscale_factor=2.0, rtx_scale=2.5, fps=24)
    assert wf["1"]["class_type"] == "VHS_LoadVideo"
    assert wf["1"]["inputs"]["video"] == "test.mp4"
    assert wf["10"]["class_type"] == "TS_Video_Upscale_With_Model"
    assert wf["10"]["inputs"]["factor"] == 2.0
    assert wf["20"]["class_type"] == "RTXVideoSuperResolution"
    assert wf["30"]["class_type"] == "CreateVideo"
    assert wf["30"]["inputs"]["fps"] == 24.0
    assert wf["31"]["class_type"] == "SaveVideo"
    assert wf["32"]["class_type"] == "SaveImage"
    return True, "video_upscale", ""


def test_video_upscale_no_upscale():
    """Test build_video_upscale with no model upscale (RTX only)."""
    wf = build_video_upscale("test.mp4", upscale_factor=1.0, rtx_scale=2.0)
    assert wf["1"]["class_type"] == "VHS_LoadVideo"
    assert "10" not in wf  # No TS upscale when factor <= 1.0
    assert wf["20"]["class_type"] == "RTXVideoSuperResolution"
    return True, "video_upscale_no_upscale", ""


def test_video_reactor():
    """Test build_video_reactor with face swap chain."""
    wf = build_video_reactor("test.mp4", ["face1.safetensors", "face2.safetensors"],
                              upscale_factor=1.5, rtx_scale=1.0, fps=16)
    assert wf["1"]["class_type"] == "VHS_LoadVideo"
    assert wf["10"]["class_type"] == "TS_Video_Upscale_With_Model"
    # Two face models = two swap chains
    assert wf["40"]["class_type"] == "ReActorLoadFaceModel"
    assert wf["40"]["inputs"]["face_model"] == "face1.safetensors"
    assert wf["41"]["class_type"] == "ReActorLoadFaceModel"
    assert wf["41"]["inputs"]["face_model"] == "face2.safetensors"
    assert wf["50"]["class_type"] == "ReActorFaceSwapOpt"
    assert wf["51"]["class_type"] == "ReActorFaceSwapOpt"
    # Second swap chains off first
    assert wf["51"]["inputs"]["input_image"] == ["50", 0]
    assert wf["70"]["class_type"] == "CreateVideo"
    assert wf["72"]["class_type"] == "SaveImage"
    return True, "video_reactor", ""


def test_wan_video():
    """Test build_wan_video basic structure (turbo mode)."""
    preset = {
        "arch": "wan",
        "high_model": "wan_high.gguf",
        "low_model": "wan_low.gguf",
        "clip": "umt5xxl_fp8.safetensors",
        "vae": "wan_vae.safetensors",
        "steps": 6, "cfg": 1.0, "shift": 8.0,
        "second_step": 3,
        "high_accel_lora": "wan_accel_high.safetensors",
        "low_accel_lora": "wan_accel_low.safetensors",
        "accel_strength": 1.5,
    }
    wf = build_wan_video("start.png", preset, "a cat walking", "", 42,
                          width=832, height=480, length=81,
                          turbo=True, interpolate=True, rtx_scale=2.5,
                          face_swap=True, save_raw=False)
    # Model loaders (GGUF)
    assert wf["1"]["class_type"] == "CLIPLoaderGGUF"
    assert wf["2"]["class_type"] == "UnetLoaderGGUF"
    assert wf["3"]["class_type"] == "UnetLoaderGGUF"
    assert wf["4"]["class_type"] == "VAELoader"
    # Prompts
    assert wf["5"]["class_type"] == "CLIPTextEncode"
    assert wf["6"]["class_type"] == "CLIPTextEncode"
    # Start image
    assert wf["7"]["class_type"] == "LoadImage"
    # Accel LoRAs in turbo mode
    assert wf["100"]["class_type"] == "LoraLoaderModelOnly"
    assert wf["120"]["class_type"] == "LoraLoaderModelOnly"
    # WanImageToVideo conditioning (not FLF)
    assert wf["40"]["class_type"] == "WanImageToVideo"
    # Two-pass KSamplerAdvanced
    assert wf["50"]["class_type"] == "KSamplerAdvanced"
    assert wf["50"]["inputs"]["end_at_step"] == 3  # second_step
    assert wf["51"]["class_type"] == "KSamplerAdvanced"
    assert wf["51"]["inputs"]["start_at_step"] == 3
    # VAE Decode
    assert wf["60"]["class_type"] == "VAEDecode"
    # Face swap
    assert wf["71"]["class_type"] == "ReActorFaceSwapOpt"
    # RIFE interpolation
    assert wf["70"]["class_type"] == "RIFE VFI"
    # RTX upscale
    assert wf["75"]["class_type"] == "RTXVideoSuperResolution"
    # Final video
    assert wf["83"]["class_type"] == "VHS_VideoCombine"
    assert wf["83"]["inputs"]["frame_rate"] == 64.0  # 16 * 4 (interpolated)
    # Last frame
    assert wf["86"]["class_type"] == "SaveImage"
    return True, "wan_video", ""


def test_wan_video_flf():
    """Test build_wan_flf wrapper (first-last-frame mode)."""
    preset = {
        "arch": "wan",
        "high_model": "wan_high.gguf",
        "low_model": "wan_low.gguf",
        "clip": "umt5xxl_fp8.safetensors",
        "vae": "wan_vae.safetensors",
        "steps": 6, "cfg": 1.0,
        "second_step": 3,
    }
    wf = build_wan_flf("start.png", "end.png", preset,
                        "a cat walking", "", 42,
                        turbo=False, interpolate=False, rtx_scale=1.0,
                        face_swap=False)
    # End image loaded
    assert wf["7b"]["class_type"] == "LoadImage"
    assert wf["7b"]["inputs"]["image"] == "end.png"
    # FLF conditioning (not WanImageToVideo)
    assert wf["40"]["class_type"] == "WanFirstLastFrameToVideo"
    return True, "wan_video_flf", ""


def test_wan_video_teacache():
    """Test build_wan_video with TeaCache enabled."""
    preset = {
        "arch": "wan",
        "high_model": "wan_high.safetensors",
        "low_model": "wan_low.safetensors",
        "clip": "umt5xxl_fp8.safetensors",
        "vae": "wan_vae.safetensors",
        "steps": 20, "cfg": 1.0,
        "second_step": 10,
    }
    wf = build_wan_video("start.png", preset, "prompt", "", 42,
                          turbo=False, teacache=True,
                          interpolate=False, rtx_scale=1.0, face_swap=False)
    assert wf["90"]["class_type"] == "ApplyTeaCachePatch"
    assert wf["91"]["class_type"] == "ApplyTeaCachePatch"
    return True, "wan_video_teacache", ""


def test_seedvr2_video_upscale():
    """Test build_seedvr2_video_upscale structure."""
    wf = build_seedvr2_video_upscale("test.mp4", seed=42, resolution=1024,
                                      batch_size=4, fps=24)
    assert wf["1"]["class_type"] == "VHS_LoadVideo"
    assert wf["1"]["inputs"]["video"] == "test.mp4"
    assert wf["2"]["class_type"] == "SeedVR2LoadVAEModel"
    assert wf["3"]["class_type"] == "SeedVR2VideoUpscaler"
    assert wf["3"]["inputs"]["seed"] == 42
    assert wf["3"]["inputs"]["resolution"] == 1024
    assert wf["3"]["inputs"]["batch_size"] == 4
    assert wf["10"]["class_type"] == "VHS_VideoCombine"
    assert wf["10"]["inputs"]["frame_rate"] == 24.0
    assert wf["11"]["class_type"] == "SaveImage"
    return True, "seedvr2_video_upscale", ""


# ═══════════════════════════════════════════════════════════════════════════
#  Runner
# ═══════════════════════════════════════════════════════════════════════════

def main():
    tests = [
        # Core infrastructure
        test_node_factory_auto_id,
        test_node_factory_explicit_id,
        test_architecture_registry,
        # Simple utility workflows
        test_rembg,
        test_upscale,
        test_lama,
        test_lut,
        # Generation workflows
        test_txt2img_sdxl,
        test_txt2img_flux,
        test_img2img_sdxl,
        test_klein_img2img,
        test_klein_4b_clip_selection,
        # Face swap workflows
        test_faceswap,
        test_faceswap_double_pass,
        test_faceswap_model,
        test_save_face_model,
        test_faceswap_mtb,
        # Enhancement workflows
        test_face_restore,
        test_photo_restore,
        test_detail_hallucinate,
        test_detail_hallucinate_no_upscale,
        # Creative workflows
        test_controlnet_gen,
        test_iclight,
        test_supir,
        test_colorize,
        # Inpaint/Outpaint
        test_inpaint,
        test_outpaint,
        test_outpaint_klein,
        # FaceID/PuLID
        test_faceid_img2img,
        test_pulid_flux1,
        test_pulid_flux2,
        # Klein variants
        test_klein_img2img_ref,
        test_klein_headswap,
        test_klein_headswap_face_model,
        # Video builders
        test_video_upscale,
        test_video_upscale_no_upscale,
        test_video_reactor,
        test_wan_video,
        test_wan_video_flf,
        test_wan_video_teacache,
        test_seedvr2_video_upscale,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            ok, name, msg = test()
            if ok:
                print(f"  PASS  {name}")
                passed += 1
            else:
                print(f"  FAIL  {name}: {msg}")
                failed += 1
        except Exception as e:
            print(f"  ERROR {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"  {passed} passed, {failed} failed, {passed + failed} total")
    if failed == 0:
        print("  All tests passed!")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
