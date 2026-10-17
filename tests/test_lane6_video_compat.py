"""Lane6 2026-10-05 regression tests: video workflows vs a spark2-style ComfyUI.

Offline (no network): urlopen is stubbed with a fake /object_info.
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scaffold import video_workflow_dispatch as D  # noqa: E402
from scaffold import comfyui_runner  # noqa: E402


def _fake_urlopen(table):
    def _open(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        for key, body in table.items():
            if url.endswith(key):
                return io.BytesIO(json.dumps(body).encode())
        raise OSError("not found: " + url)
    return _open


def test_ltx_resolver_ignores_lora_and_upscaler_and_uses_full_checkpoint():
    models = {
        "unet_gguf": [],
        "unet": ["ltx-2-3-22b/ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
                 "ltx-2-3-22b/ltx-2.3-22b-distilled.safetensors",
                 "ltx-2-3-22b/ltx-2.3-spatial-upscaler-x2-1.0.safetensors"],
        "clip": ["gemma-3-12b-it.safetensors"], "clip_gguf": [],
        "vae": ["LTX23_video_vae_bf16.safetensors"], "lora": [],
        "latent_upscaler": ["ltx-2.3-spatial-upscaler-x2-1.1.safetensors"],
    }
    p = D.resolve_ltx2_preset("ltx2_text_to_video", models)
    assert p["unet"] == "ltx-2-3-22b/ltx-2.3-22b-distilled.safetensors"
    assert p["embeddings_connector"] == p["unet"]
    assert p["distilled_baked"] is True and p["steps"] == 8
    assert p["latent_upscaler"] == "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"


def test_runner_strips_top_level_meta(monkeypatch):
    posted = {}

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _open(req, timeout=0):
        posted.update(json.loads(req.data))
        return _Resp(b'{"prompt_id": "x"}')
    monkeypatch.setattr(comfyui_runner.urllib.request, "urlopen", _open)
    r = comfyui_runner.ComfyUIRunner("http://x:1")
    assert r._queue_prompt({"_meta": {"title": "t"},
                            "1": {"class_type": "A", "inputs": {}}}) == "x"
    assert list(posted["prompt"]) == ["1"]


def test_adapt_missing_nodes_rife_to_gimm(monkeypatch):
    table = {
        "/object_info/RIFE%20VFI": {},
        "/object_info/DownloadAndLoadGIMMVFIModel": {"DownloadAndLoadGIMMVFIModel": {
            "input": {"required": {"model": [["gimmvfi_f_arb_lpips_fp32.safetensors",
                                              "gimmvfi_r_arb_lpips_fp32.safetensors"]]}}}},
        "/object_info/GIMMVFI_interpolate": {"GIMMVFI_interpolate": {"input": {}}},
    }
    monkeypatch.setattr(D.urllib.request, "urlopen", _fake_urlopen(table))
    wf = {"1": {"class_type": "RIFE VFI",
                "inputs": {"frames": ["0", 0], "multiplier": 2}}}
    notes = D.adapt_missing_nodes(wf, "http://x:1")
    assert notes and wf["1"]["class_type"] == "GIMMVFI_interpolate"
    assert wf["1"]["inputs"]["interpolation_factor"] == 2


def test_heal_swap_model_and_only_video(monkeypatch):
    table = {"/object_info/ReActorFaceSwapOpt": {"ReActorFaceSwapOpt": {"input": {
        "required": {"swap_model": [["inswapper_128.onnx"]]}}}}}
    monkeypatch.setattr(D.urllib.request, "urlopen", _fake_urlopen(table))
    wf = {"1": {"class_type": "ReActorFaceSwapOpt",
                "inputs": {"swap_model": "reswapper_256.onnx"}}}
    assert D.heal_video_workflow(wf, "http://x:1") == []  # no video node: untouched
    wf["2"] = {"class_type": "VHS_VideoCombine", "inputs": {}}
    D.heal_video_workflow(wf, "http://x:1")
    assert wf["1"]["inputs"]["swap_model"] == "inswapper_128.onnx"


def test_builders_emit_pingpong_and_framepack_scales_image():
    sys.path.insert(0, str(ROOT / "plugins" / "gimp" / "comfyui-connector"))
    from spellcaster_core import workflows as W
    wf = W.build_framepack_video("a.png", "p", "n", 1, model_name="m",
                                 llama_clip_name="l", clip_l_name="c",
                                 vae_name="v", clip_vision_name="cv")
    ref = wf["7"]["inputs"]["image"]
    assert wf[ref[0]]["class_type"] == "ImageScale"
    for n in wf.values():
        if n.get("class_type") == "VHS_VideoCombine":
            assert "pingpong" in n["inputs"]
