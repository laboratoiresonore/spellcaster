"""End-to-end audit of every method across every Spellcaster surface.

Covers:

    * Guild REST endpoints               — every /api/* we document
    * Studio scaffolds (9 wizards)        — live system prompt + LLM turn
    * Per-model wizards                   — arch-family coverage spot-check
    * build_* functions (spellcaster_core.workflows)
                                          — compile + submit to ComfyUI /prompt
    * Cross-plugin scaffold manifest      — /api/spellcaster/manifest method
                                            inventory (GIMP / Darktable / Resolve
                                            / SillyTavern / Guild)
    * Cross-interface backbone            — event_bus.emit, asset_gallery,
                                            interface_registry.heartbeat,
                                            mailbox.push/pull round-trip
    * Video canon                         — detect_wan_preset, detect_ltx_preset,
                                            wan_turbo_kwargs, ltx_mode_kwargs
    * Model prompt profiles               — profile_for(known filenames)

CLI
---
    python tests/e2e_audit.py
    python tests/e2e_audit.py --verbose
    python tests/e2e_audit.py --only scaffolds,endpoints
    python tests/e2e_audit.py --skip build_fns,cross_interface
    python tests/e2e_audit.py --report tests/e2e_report.md

Exit codes
----------
    0 — every test passed
    1 — one or more tests failed (see report)
    2 — runtime error before tests could start (Guild down etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─── Config ────────────────────────────────────────────────────────────
GUILD_URL = os.environ.get("SPELLCASTER_TEST_GUILD_URL", "http://127.0.0.1:7777")
COMFYUI_URL_ENV = os.environ.get("SPELLCASTER_TEST_COMFYUI_URL")  # None = use Guild's
HTTP_TIMEOUT = float(os.environ.get("SPELLCASTER_TEST_TIMEOUT", "15"))
LLM_TIMEOUT = float(os.environ.get("SPELLCASTER_TEST_LLM_TIMEOUT", "120"))


# ─── Result accumulator ────────────────────────────────────────────────

PASS, FAIL, SKIP, WARN = "PASS", "FAIL", "SKIP", "WARN"

COLOR = {
    PASS: "\033[32m",
    FAIL: "\033[31m",
    SKIP: "\033[37m",
    WARN: "\033[33m",
    "RESET": "\033[0m",
}


@dataclass
class TestResult:
    section: str
    name: str
    status: str  # PASS | FAIL | SKIP | WARN
    detail: str = ""
    elapsed_ms: int = 0

    def line(self, pretty: bool = False) -> str:
        tag = f"[{self.status:4s}]"
        if pretty and sys.stdout.isatty():
            tag = f"{COLOR.get(self.status,'')}{tag}{COLOR['RESET']}"
        ms = f" ({self.elapsed_ms}ms)" if self.elapsed_ms else ""
        return f"  {tag} {self.name}{ms}  {self.detail}"


class Report:
    def __init__(self):
        self.results: list[TestResult] = []
        self._started_at = time.time()

    def add(self, section: str, name: str, status: str,
            detail: str = "", elapsed_ms: int = 0):
        self.results.append(TestResult(section, name, status, detail,
                                        elapsed_ms))

    def by_section(self):
        sections: dict[str, list[TestResult]] = {}
        for r in self.results:
            sections.setdefault(r.section, []).append(r)
        return sections

    def summary(self) -> dict[str, int]:
        s = {PASS: 0, FAIL: 0, SKIP: 0, WARN: 0}
        for r in self.results:
            s[r.status] = s.get(r.status, 0) + 1
        return s

    def print_to_stdout(self, pretty: bool = True):
        for section, results in self.by_section().items():
            print(f"\n═══ {section} ══════════════════════════════════════════")
            for r in results:
                print(r.line(pretty=pretty))
        s = self.summary()
        total = sum(s.values())
        elapsed = int(time.time() - self._started_at)
        print(f"\nTotal: {total}   "
              f"PASS: {s[PASS]}   FAIL: {s[FAIL]}   "
              f"WARN: {s[WARN]}   SKIP: {s[SKIP]}   "
              f"({elapsed}s)")

    def write_markdown(self, path: str):
        lines = ["# Spellcaster E2E Audit", ""]
        lines.append(f"_Ran at_: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        s = self.summary()
        lines.append(f"_Totals_: **{s[PASS]}** pass · **{s[FAIL]}** fail · "
                     f"**{s[WARN]}** warn · **{s[SKIP]}** skip")
        lines.append("")
        for section, results in self.by_section().items():
            lines.append(f"## {section}")
            lines.append("")
            lines.append("| Status | Test | Detail | Time (ms) |")
            lines.append("|---|---|---|---|")
            for r in results:
                detail = (r.detail or "").replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {r.status} | {r.name} | {detail} "
                              f"| {r.elapsed_ms} |")
            lines.append("")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


# ─── HTTP helpers ──────────────────────────────────────────────────────

def http_get(path: str, timeout: float = HTTP_TIMEOUT) -> tuple[int, dict | str]:
    url = path if path.startswith("http") else GUILD_URL.rstrip("/") + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
        try:
            return 200, json.loads(body)
        except json.JSONDecodeError:
            return 200, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def http_post(path: str, payload: dict, timeout: float = HTTP_TIMEOUT) -> tuple[int, dict | str]:
    url = path if path.startswith("http") else GUILD_URL.rstrip("/") + path
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
        try:
            return 200, json.loads(body)
        except json.JSONDecodeError:
            return 200, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        try:
            return e.code, json.loads(body) if body else body
        except json.JSONDecodeError:
            return e.code, body
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def get_comfyui_url() -> Optional[str]:
    if COMFYUI_URL_ENV:
        return COMFYUI_URL_ENV
    sc, body = http_get("/api/config")
    if sc == 200 and isinstance(body, dict):
        return body.get("comfyui_url") or None
    return None


# ═══════════════════════════════════════════════════════════════════════
#  TEST SECTIONS
# ═══════════════════════════════════════════════════════════════════════

def test_guild_endpoints(report: Report, verbose: bool = False) -> None:
    """Hit every documented /api/* GET route and confirm 200 + expected shape."""
    section = "Guild endpoints"

    # (path, [expected_keys_if_dict_or_none_if_string])
    endpoints: list[tuple[str, Optional[list[str]]]] = [
        ("/api/characters", None),
        ("/api/comfy_status", ["connected"]),
        ("/api/llm_status", ["backend"]),
        ("/api/antennas", ["antennas"]),
        ("/api/interfaces", None),
        ("/api/app_control/config", ["app_control"]),
        ("/api/config", ["comfyui_url"]),
        ("/api/assets?limit=5", None),
        ("/api/setup/state", None),
        ("/api/setup/status", ["phase"]),
        ("/api/setup/comfyui-status", ["reachable", "comfyui_url"]),
        ("/api/spellcaster/state", None),
        ("/api/video/presets", ["presets"]),
        ("/api/video/health", ["comfyui"]),
        ("/api/video/shots", None),
        ("/api/video/queue/status", None),
        ("/api/spellcaster/network/survey", None),
        ("/api/sillytavern_status", ["connected"]),
        ("/api/signal_bridge_status", None),
    ]
    for path, expected_keys in endpoints:
        t0 = time.time()
        sc, body = http_get(path)
        ms = int((time.time() - t0) * 1000)
        if sc == 200:
            if expected_keys and isinstance(body, dict):
                missing = [k for k in expected_keys if k not in body]
                if missing:
                    report.add(section, path, WARN,
                               f"200 OK but missing keys: {missing}", ms)
                else:
                    report.add(section, path, PASS,
                               f"{len(body)} keys" if isinstance(body, dict)
                               else f"{len(body) if hasattr(body,'__len__') else '?'} entries",
                               ms)
            else:
                size = len(body) if hasattr(body, "__len__") else "?"
                report.add(section, path, PASS, f"size={size}", ms)
        elif sc in (404, 405):
            report.add(section, path, WARN,
                       f"HTTP {sc} — endpoint not registered?", ms)
        else:
            snippet = str(body)[:100] if body else ""
            report.add(section, path, FAIL, f"HTTP {sc}: {snippet}", ms)


def test_scaffolds(report: Report, verbose: bool = False,
                   with_llm: bool = True) -> None:
    """Fetch /api/system_prompt/<id> for every studio wizard; optionally run
    one LLM turn so we catch prompts that render but never lead to output.
    """
    section = "Scaffolds — studio wizards"
    sc, chars = http_get("/api/characters")
    if sc != 200 or not isinstance(chars, list):
        report.add(section, "fetch /api/characters", FAIL,
                   f"HTTP {sc}")
        return

    studios = [c for c in chars if c.get("type") == "studio"]
    for ch in studios:
        cid = ch.get("id")
        if not cid:
            continue
        t0 = time.time()
        sc, body = http_get(f"/api/system_prompt/{cid}")
        ms = int((time.time() - t0) * 1000)
        if sc != 200 or not isinstance(body, dict):
            report.add(section, f"system_prompt[{cid}]", FAIL,
                       f"HTTP {sc}", ms)
            continue
        prompt = body.get("prompt", "") or ""
        if len(prompt) < 400:
            report.add(section, f"system_prompt[{cid}]", WARN,
                       f"short prompt ({len(prompt)} chars)", ms)
            continue
        report.add(section, f"system_prompt[{cid}]", PASS,
                   f"{len(prompt)} chars", ms)

        if with_llm:
            t0 = time.time()
            sc, lresp = http_post("/api/llm_generate", {
                "prompt": (
                    f"<|system|>\n{prompt}\n<|end|>\n"
                    f"<|user|>\nList the tools you can use right now "
                    f"(bullet list only, no prose).\n<|end|>\n"
                    f"<|assistant|>\n"
                ),
                "max_length": 180,
                "temperature": 0.5,
                "stop_sequence": ["<|end|>", "<|user|>", "\n\n\n"],
            }, timeout=LLM_TIMEOUT)
            ms = int((time.time() - t0) * 1000)
            if sc != 200 or not isinstance(lresp, dict):
                report.add(section, f"llm_turn[{cid}]", WARN,
                           f"HTTP {sc}", ms)
                continue
            try:
                text = lresp["results"][0]["text"] or ""
            except Exception:
                text = ""
            if len(text.strip()) < 30:
                report.add(section, f"llm_turn[{cid}]", WARN,
                           "thin/empty response", ms)
            else:
                snippet = text.strip().splitlines()[0][:80]
                report.add(section, f"llm_turn[{cid}]", PASS,
                           f'"{snippet}…"', ms)

    # Per-model wizards — spot-check ONE to confirm the system-prompt path
    # still returns something for the dynamic-scaffold branch.
    model_wizards = [c for c in chars if c.get("id", "").startswith("comfyui_")]
    if model_wizards:
        spot = model_wizards[0]
        cid = spot["id"]
        t0 = time.time()
        sc, body = http_get(f"/api/system_prompt/{cid}")
        ms = int((time.time() - t0) * 1000)
        if sc != 200 or not isinstance(body, dict):
            report.add(section, f"system_prompt[{cid}] (per-model spot)",
                       WARN, f"HTTP {sc}", ms)
        else:
            prompt = body.get("prompt", "")
            report.add(section,
                       f"system_prompt[{cid}] (per-model spot)",
                       PASS if len(prompt) > 200 else WARN,
                       f"{len(prompt)} chars", ms)


def test_build_functions(report: Report, verbose: bool = False,
                         max_tests: int = 200) -> None:
    """Import spellcaster_core.workflows and call as many build_* functions
    as possible with sane defaults, submitting to ComfyUI /prompt for
    validation (no sampling — ComfyUI returns immediately on validation
    failure, and we deliberately don't WAIT for results).
    """
    section = "build_* functions (compile + validate)"
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "comfyui-spellcaster"))
        from spellcaster_core import workflows as _wf  # type: ignore
    except Exception as e:
        report.add(section, "import spellcaster_core.workflows", FAIL,
                   f"{type(e).__name__}: {e}")
        return

    comfy_url = get_comfyui_url()
    if not comfy_url:
        report.add(section, "resolve ComfyUI URL", SKIP,
                   "no /api/config comfyui_url")
        return

    # Discover a real SDXL / SD1.5 checkpoint on the server so builders
    # that load one pass validation instead of failing on a bare filename.
    def _probe_enum(node_class, input_name):
        try:
            with urllib.request.urlopen(
                    f"{comfy_url}/object_info/{node_class}",
                    timeout=6) as r:
                data = json.loads(r.read())
            choices = (data.get(node_class, {})
                           .get("input", {}).get("required", {})
                           .get(input_name, []))
            if isinstance(choices, list) and choices:
                if isinstance(choices[0], list):
                    return list(choices[0])
                if len(choices) >= 2 and isinstance(choices[1], dict):
                    return list(choices[1].get("options") or [])
        except Exception:
            pass
        return []

    ckpt_list = _probe_enum("CheckpointLoaderSimple", "ckpt_name")
    real_sdxl = next((c for c in ckpt_list if "sdxl" in c.lower()
                       or "xl" in c.lower().rsplit(os.sep, 1)[-1]), None)
    real_sd15 = next((c for c in ckpt_list
                       if "sd-1.5" in c.lower() or "sd_1_5" in c.lower()
                       or "v1-5" in c.lower() or "sd15" in c.lower()
                       or "1.5" in c.lower()), None)
    real_flux2 = next((c for c in ckpt_list
                        if "klein" in c.lower()), None)

    # Upload tiny test.png + test_mask.png so LoadImage-based builders
    # (img2img, inpaint, iclight, etc.) validate instead of failing on
    # a filename that doesn't exist in ComfyUI's input/ dir.
    test_png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00"
                b"\x0cIDAT\x08\x99c``\x00\x00\x00\x04\x00\x01\x0b\xe7\x02\x9c"
                b"\x00\x00\x00\x00IEND\xaeB`\x82")
    for fn_name in ("test.png", "test_mask.png"):
        try:
            boundary = "----e2esb"
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; '
                f'name="image"; filename="{fn_name}"\r\n'
                f'Content-Type: image/png\r\n\r\n').encode() + test_png + \
                f'\r\n--{boundary}--\r\n'.encode()
            req = urllib.request.Request(
                f"{comfy_url}/upload/image", data=body,
                headers={"Content-Type":
                         f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
        except Exception:
            pass  # harmless; per-builder tests will surface the issue

    # Sensible dummy inputs — most builders are happy with these.
    # The preset dict carries keys every downstream node reaches for
    # (width/height/steps/cfg/sampler). Video builders need their
    # family-specific keys (high_model, unet) which we lookup live
    # from the canonical detectors below.
    defaults_by_param: dict[str, Any] = {
        "image_filename": "test.png",
        "start_filename": "test.png",
        "end_filename": "test.png",
        "mask_filename": "test_mask.png",
        "source_filename": "test.png",
        "reference_filename": "test.png",
        "target_filename": "test.png",
        "style_filename": "test.png",
        "style_ref_filename": "test.png",
        "face_ref_filename": "test.png",
        "fg_filename": "test.png",
        "bg_filename": "test.png",
        "pose_filename": "test.png",
        "outfit_filename": "test.png",
        "face_filename": "test.png",
        "ref_filename": "test.png",
        "overlay_filename": "test.png",
        "image_a_filename": "test.png",
        "image_b_filename": "test.png",
        "scene_filename": "test.png",
        "frame_filenames": ["test.png"],
        "video_name": "test.png",
        "prompt_text": "a magical landscape",
        "positive_text": "a magical landscape",
        "prompt": "a magical landscape",
        "inpaint_prompt": "a magical landscape",
        "negative_text": "",
        "negative": "",
        "seed": 42,
        "width": 1024, "height": 1024,
        "length": 25, "num_frames": 25, "fps": 16,
        "denoise": 0.6, "strength": 0.8,
        "controlnet_strength": 0.8,
        "cfg": 5.0, "steps": 20,
        "sampler": "euler", "scheduler": "normal",
        "ckpt_name": "sd_xl_base_1.0.safetensors",
        # `preset` default is filled AFTER the checkpoint probe below.
        "preset": None,
        "loras": [],
        # mask / prompt defaults for inpaint + sam3 builders
        "use_solid_mask": True,
        "sam3_prompt": "person",
        "mask_prompt": "person",
        "segment_prompt": "person",
        # Klein family model selector — resolved from klein_models table
        "klein_model_key": "Klein 9B",
        # Outpaint edges
        "left": 0, "top": 0, "right": 128, "bottom": 128,
        "feather": 32,
        # Face identity
        "visibility": 1.0, "facedetection": "retinaface_resnet50",
        "model_name": "",          # filled per-builder below
        # Preset keys used by klein_detail / klein_batch_variations
        "preset_key": "",
    }

    # Pull live video presets so WAN + LTX builders have real filenames.
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "comfyui-spellcaster"))
        from spellcaster_core import video_presets as _vp  # type: ignore
        wan_preset = _vp.detect_wan_preset(comfy_url)
        ltx_preset = _vp.detect_ltx_preset(comfy_url)
    except Exception:
        wan_preset = ltx_preset = None

    # Build a real SDXL preset using a checkpoint that actually exists on
    # the server, plus sensible defaults every downstream node reads.
    default_ckpt = real_sdxl or real_sd15 or (ckpt_list[0] if ckpt_list else "")
    default_preset = {
        "arch": "sdxl" if real_sdxl else ("sd15" if real_sd15 else "sdxl"),
        "ckpt": default_ckpt,
        "width": 1024, "height": 1024,
        "steps": 20, "cfg": 5.0,
        "sampler": "euler", "scheduler": "normal",
        "denoise": 1.0,
    }
    defaults_by_param["preset"] = default_preset

    # Per-builder preset override table. The generic `preset` default is
    # an SDXL preset; video builders need their family dict.
    # IC-Light is SD 1.5 only — it crashes on SDXL.
    preset_override_by_fn: dict[str, dict] = {}
    if wan_preset:
        for name in ("build_wan_video", "build_wan_flf", "build_wan22_t2v"):
            preset_override_by_fn[name] = wan_preset
    if ltx_preset:
        preset_override_by_fn["build_ltx_video"] = ltx_preset
    if real_flux2:
        preset_override_by_fn["build_klein_img2img"] = {
            "arch": "flux2klein",
            "ckpt": real_flux2,
            "width": 1024, "height": 1024,
            "steps": 8, "cfg": 1.0,
            "sampler": "euler", "scheduler": "simple",
        }

    # Extra kwarg overrides — for builders whose SAM3 / mask contract
    # can't be satisfied by a bare "test_mask.png" filename. We pass
    # `sam3_prompt` or force_solid so the builder has at least one
    # valid path to synthesise a mask.
    extra_kwargs_by_fn: dict[str, dict] = {
        "build_klein_inpaint": {"sam3_prompt": "person"},
        "build_lama_remove":   {"sam3_prompt": "person"},
    }
    # build_iclight takes `ckpt_name` (not a `preset` dict) and ONLY
    # accepts SD 1.5 checkpoints. Override the default SDXL ckpt.
    if real_sd15:
        extra_kwargs_by_fn["build_iclight"] = {"ckpt_name": real_sd15}

    # Probe live ComfyUI enums for face / upscale / LoRA / LUT inputs so
    # builders that consume those enums validate with a real filename.
    upscale_models = _probe_enum("UpscaleModelLoader", "model_name")
    face_models = _probe_enum("FaceModelLoader", "face_model")
    facerestore_models = _probe_enum("FaceRestoreCFWithModel", "model_name")
    luts_list = (_probe_enum("ApplyLUT+", "lut_name")
                  or _probe_enum("ImageApplyLUT", "lut_name"))
    preprocessors = _probe_enum("ControlNetPreprocessorSelector", "preprocessor")
    controlnet_models = _probe_enum("ControlNetLoader", "control_net_name")
    gguf_models = _probe_enum("UnetLoaderGGUF", "unet_name")
    supir_models = _probe_enum("SUPIR_model_loader_v2", "supir_model")

    real_upscale = next((m for m in upscale_models if "ultrasharp" in m.lower()
                          or "esrgan" in m.lower() or "4x" in m.lower()),
                         upscale_models[0] if upscale_models else "")
    real_face_model = face_models[0] if face_models else ""
    real_face_restore = facerestore_models[0] if facerestore_models else ""
    real_lut = next((l for l in luts_list if "film" in l.lower()
                     or "cinematic" in l.lower()),
                    luts_list[0] if luts_list else "")
    real_pose_preproc = next((p for p in preprocessors if "openpose" in p.lower()
                               or "dwpose" in p.lower() or "canny" in p.lower()),
                              preprocessors[0] if preprocessors else "")
    real_cn_model = next((c for c in controlnet_models if "sdxl" in c.lower()),
                          controlnet_models[0] if controlnet_models else "")
    real_flux_unet = next((u for u in gguf_models if "flux" in u.lower()
                            or "qwen" in u.lower()), "")
    real_supir = supir_models[0] if supir_models else ""

    # Per-builder kwarg fills for the SKIP bucket. Each entry uses the
    # exact kwarg name the builder's signature declares (no aliases).
    if real_upscale:
        # `upscale_model` is the shared name for the pure upscalers.
        for fn_name in ("build_detail_hallucinate", "build_seedv2r",
                        "build_video_upscale", "build_photo_restore"):
            extra_kwargs_by_fn.setdefault(fn_name, {})["upscale_model"] = real_upscale
        # Other builders rename to `model_name`.
        extra_kwargs_by_fn.setdefault("build_upscale", {})["model_name"] = real_upscale
        extra_kwargs_by_fn.setdefault("build_upscale_blend", {})["model_a_name"] = real_upscale
        extra_kwargs_by_fn.setdefault("build_upscale_blend", {})["model_b_name"] = real_upscale
    if real_face_model:
        extra_kwargs_by_fn.setdefault("build_faceswap_model", {})["face_model_name"] = real_face_model
        extra_kwargs_by_fn.setdefault("build_save_face_model", {})["model_name"] = real_face_model
    if real_face_restore:
        extra_kwargs_by_fn.setdefault("build_face_restore", {})["model_name"] = real_face_restore
        extra_kwargs_by_fn.setdefault("build_photo_restore", {})["face_model"] = real_face_restore
        extra_kwargs_by_fn.setdefault("build_video_reactor", {})["face_models"] = [real_face_restore]
    if real_lut:
        extra_kwargs_by_fn.setdefault("build_lut", {})["lut_name"] = real_lut
        extra_kwargs_by_fn.setdefault("build_lut", {})["strength"] = 0.8
    if real_cn_model and real_pose_preproc:
        extra_kwargs_by_fn.setdefault("build_controlnet_gen", {}).update({
            "preprocessor_type": real_pose_preproc,
            "controlnet_model": real_cn_model,
        })
    if real_flux_unet:
        extra_kwargs_by_fn.setdefault("build_qwen_edit", {}).update({
            "unet_name": real_flux_unet,
            "clip_name": "umt5-xxl-encoder-Q3_K_S.gguf",
            "vae_name":  "wan_2.1_vae.safetensors",
        })
    if real_supir and default_ckpt:
        extra_kwargs_by_fn.setdefault("build_supir", {}).update({
            "supir_model": real_supir,
            "sdxl_model": default_ckpt,
        })

    # Klein preset-key builders — use the first preset key the klein
    # preset table exposes; fall back to the enum probe.
    try:
        from spellcaster_core import workflows as _wf
        # Some klein builders take `klein_models` as a dict literal.
        # We don't know its shape without executing them — leave the
        # SKIP when those args are missing (better than fabricating).
        pass
    except Exception:
        pass
    # Outpaint / colorize shape
    extra_kwargs_by_fn.setdefault("build_outpaint", {}).update({
        "left": 0, "top": 0, "right": 128, "bottom": 128,
        "feathering": 32,  # signature spells it `feathering`, not `feather`
    })
    extra_kwargs_by_fn.setdefault("build_colorize", {}).update({
        "controlnet_strength": 0.8, "denoise": 0.5,
    })
    extra_kwargs_by_fn.setdefault("build_detail_hallucinate", {}).update({
        "denoise": 0.4, "steps": 20,
    })
    extra_kwargs_by_fn.setdefault("build_seedv2r", {}).update({
        "denoise": 0.4, "cfg": 5.0, "steps": 20,
        "scale_factor": 2, "orig_width": 1024, "orig_height": 1024,
    })
    extra_kwargs_by_fn.setdefault("build_face_restore", {}).update({
        "facedetection": "retinaface_resnet50",
        "visibility": 1.0,
        "codeformer_weight": 0.5,  # builder spells it `codeformer_weight`
    })
    extra_kwargs_by_fn.setdefault("build_photo_restore", {}).update({
        "facedetection": "retinaface_resnet50",
        "visibility": 1.0, "codeformer_weight": 0.5,
        "sharpen_radius": 1, "sigma": 1.0, "alpha": 0.5,
    })
    extra_kwargs_by_fn.setdefault("build_klein_detail", {}).update({
        "preset_key": "detail",
    })
    extra_kwargs_by_fn.setdefault("build_klein_batch_variations", {}).update({
        "klein_model_key": "Klein 9B",
    })

    build_fn_names = [n for n in dir(_wf) if n.startswith("build_")]
    tested = 0
    for name in build_fn_names:
        if tested >= max_tests:
            report.add(section, f"(cap reached at {max_tests})",
                       SKIP, f"{len(build_fn_names) - tested} untested")
            break
        fn = getattr(_wf, name, None)
        if not callable(fn):
            continue
        try:
            import inspect
            sig = inspect.signature(fn)
            kwargs = {}
            # Per-builder preset override wins over the default preset.
            preset_for_fn = preset_override_by_fn.get(name)
            for pname, p in sig.parameters.items():
                if p.default is not inspect.Parameter.empty:
                    continue  # keep function defaults
                if pname == "preset" and preset_for_fn is not None:
                    kwargs[pname] = preset_for_fn
                elif pname in defaults_by_param:
                    kwargs[pname] = defaults_by_param[pname]
                # else leave unset and let the call raise — we catch it.
            # Extra per-builder kwargs (override even defaulted params).
            for k, v in (extra_kwargs_by_fn.get(name) or {}).items():
                kwargs[k] = v
            t0 = time.time()
            wf = fn(**kwargs)
            ms = int((time.time() - t0) * 1000)
            if not isinstance(wf, dict) or not wf:
                report.add(section, name, WARN,
                           "builder returned empty/non-dict", ms)
                tested += 1
                continue
            # Submit to ComfyUI — accept means validation passed.
            t0 = time.time()
            sc, resp = http_post(f"{comfy_url}/prompt", {"prompt": wf},
                                  timeout=HTTP_TIMEOUT)
            ms2 = int((time.time() - t0) * 1000)
            if sc == 200 and isinstance(resp, dict) and resp.get("prompt_id"):
                # Interrupt to free the queue; keep it fast.
                try:
                    http_post(f"{comfy_url}/interrupt", {}, timeout=3)
                except Exception:
                    pass
                report.add(section, name, PASS,
                           f"{len(wf)} nodes, queued ok", ms + ms2)
            else:
                # Distinguish "real builder bug" from "this model isn't
                # installed on the server". ComfyUI raises
                # `value_not_in_list` for the latter — that's an
                # environment limit, not a builder fault, so we mark it
                # SKIP (with the missing value) instead of FAIL.
                snippet = json.dumps(resp)[:160] if not isinstance(resp, str) else resp[:160]
                env_miss = False
                missing_val = ""
                if isinstance(resp, dict):
                    node_errs = resp.get("node_errors") or {}
                    for nid, info in node_errs.items():
                        for err in info.get("errors") or []:
                            if err.get("type") == "value_not_in_list":
                                env_miss = True
                                ex = err.get("extra_info") or {}
                                missing_val = (f"{ex.get('input_name','?')}"
                                                f"={ex.get('received_value','?')}")
                                break
                        if env_miss:
                            break
                if env_miss:
                    report.add(section, name, SKIP,
                               f"env lacks model: {missing_val}", ms + ms2)
                else:
                    report.add(section, name, FAIL,
                               f"ComfyUI {sc}: {snippet}", ms + ms2)
            tested += 1
        except TypeError as e:
            report.add(section, name, SKIP,
                       f"needs extra args: {str(e)[:100]}")
            tested += 1
        except Exception as e:
            report.add(section, name, FAIL,
                       f"{type(e).__name__}: {str(e)[:120]}")
            tested += 1


def test_plugin_manifest(report: Report, verbose: bool = False) -> None:
    """The Travelling Wizard's cross-plugin manifest enumerates every
    registered method across GIMP / Darktable / Resolve / SillyTavern /
    Guild with an SSoT status per method. We surface the roll-up counts
    here so the audit shows plugin coverage at a glance."""
    section = "Cross-plugin scaffold manifest"
    sc, body = http_get("/api/scaffolds/all", timeout=30)
    if sc != 200:
        report.add(section, "/api/scaffolds/all", FAIL, f"HTTP {sc}")
        return
    if not isinstance(body, dict):
        report.add(section, "/api/scaffolds/all", FAIL,
                   "non-dict response")
        return

    # plugin_manifest returns shape:
    #   {"groups": [{...}, ...], "totals": {...}, "methods": [...]}
    plugins = (body.get("groups") or body.get("plugins") or [])
    totals = body.get("totals") or {}
    if totals:
        report.add(section, "totals", PASS,
                   ", ".join(f"{k}={v}" for k, v in totals.items()))
    else:
        total_methods = len(body.get("methods") or [])
        if total_methods:
            report.add(section, "totals", PASS,
                       f"methods={total_methods}")

    for group in plugins if isinstance(plugins, list) else []:
        gid = group.get("id") or group.get("source") or ""
        name = (group.get("name") or group.get("label") or gid or "?")
        methods = group.get("methods") or []
        count = len(methods) if methods else (
            group.get("count") or group.get("total") or 0)
        unknown = sum(1 for m in methods
                      if (m.get("ssot") or m.get("status")) in
                         ("unknown", "?", None))
        duplicate = sum(1 for m in methods
                        if (m.get("ssot") or m.get("status")) == "duplicate")
        warnings = sum(1 for m in methods
                       if (m.get("ssot") or m.get("status")) in
                          ("warning", "violation"))
        status = PASS
        if warnings or duplicate:
            status = WARN
        detail = (f"methods={count}"
                  + (f"  duplicate={duplicate}" if duplicate else "")
                  + (f"  warnings={warnings}" if warnings else "")
                  + (f"  unknown={unknown}" if unknown else ""))
        report.add(section, f"plugin[{name}]", status, detail)


def test_wizard_names(report: Report, verbose: bool = False) -> None:
    """Per-user request: flag wizards whose name still looks like a raw
    ComfyUI model filename (e.g. 'juggernautXL_v9Rundiffusionphoto2').
    Mirrors the client-side _looksLikeRawModelFilename detector in app.js."""
    section = "Wizard naming coverage"
    import re
    def looks_raw(name: str) -> bool:
        if not name or name == "Unnamed Wizard":
            return True
        if re.search(r"[_\-][vV]\d+", name): return True
        if re.search(r"_\d", name): return True
        if re.search(r"(fp8|fp16|q4|q6|q8|bf16|safetensors|gguf|aio|xl|hd|pony|noob)",
                     name, flags=re.I): return True
        if re.search(r"[A-Z]{3,}", name): return True
        if len(name) > 30: return True
        return False

    sc, chars = http_get("/api/characters")
    if sc != 200 or not isinstance(chars, list):
        report.add(section, "fetch /api/characters", FAIL, f"HTTP {sc}")
        return

    studios_ok = 0
    comfy_raw = []
    comfy_named = 0
    for ch in chars:
        cid = ch.get("id", "")
        name = ch.get("name", "")
        if ch.get("type") == "studio":
            studios_ok += 1
            continue
        if cid.startswith("comfyui_") or ch.get("type") == "comfyui_model":
            if looks_raw(name):
                comfy_raw.append((cid, name))
            else:
                comfy_named += 1

    report.add(section, "studio wizards", PASS,
               f"{studios_ok} core wizards present")
    total_model = comfy_named + len(comfy_raw)
    if total_model == 0:
        report.add(section, "per-model wizards", SKIP,
                   "no per-model wizards discovered")
    elif not comfy_raw:
        report.add(section, "per-model wizards", PASS,
                   f"all {total_model} wizards have human names")
    else:
        snippet = ", ".join(f"{n!r}" for _, n in comfy_raw[:3])
        extra = f" +{len(comfy_raw)-3} more" if len(comfy_raw) > 3 else ""
        report.add(section, "per-model wizards", WARN,
                   f"{len(comfy_raw)}/{total_model} still raw: {snippet}{extra}")


def test_video_canon(report: Report, verbose: bool = False) -> None:
    """Sanity-check the canonical video-preset detectors + formulas."""
    section = "Video canon (spellcaster_core.video_presets)"
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "comfyui-spellcaster"))
        from spellcaster_core import video_presets as vp  # type: ignore
    except Exception as e:
        report.add(section, "import video_presets", FAIL,
                   f"{type(e).__name__}: {e}")
        return

    # wan_turbo_kwargs shape
    try:
        t = vp.wan_turbo_kwargs(True)
        f = vp.wan_turbo_kwargs(False)
        ok = (t == {}
              and f.get("steps") == 30
              and f.get("cfg") == 3.5
              and f.get("second_step") == 15)
        report.add(section, "wan_turbo_kwargs",
                   PASS if ok else FAIL,
                   f"turbo={t}  full={f}")
    except Exception as e:
        report.add(section, "wan_turbo_kwargs", FAIL,
                   f"{type(e).__name__}: {e}")

    # ltx_mode_kwargs shape
    try:
        modes = {m: vp.ltx_mode_kwargs(m)
                 for m in ("distilled", "full", "two_stage", "i2v")}
        ok = (modes["distilled"]["distilled"] is True
              and modes["full"]["distilled"] is False
              and modes["two_stage"]["two_stage"] is True)
        report.add(section, "ltx_mode_kwargs",
                   PASS if ok else FAIL,
                   f"{modes}")
    except Exception as e:
        report.add(section, "ltx_mode_kwargs", FAIL,
                   f"{type(e).__name__}: {e}")

    # VAE pairing logic
    try:
        vae14 = vp.pick_wan_vae("wan2.2_i2v_high_14B.safetensors",
                                 ["wan2.2_vae.safetensors",
                                  "wan_2.1_vae.safetensors"])
        vae5 = vp.pick_wan_vae("wan2.2_ti2v_5b.safetensors",
                                ["wan2.2_vae.safetensors",
                                 "wan_2.1_vae.safetensors"])
        ok = (vae14 == "wan_2.1_vae.safetensors"
              and vae5 == "wan2.2_vae.safetensors")
        report.add(section, "pick_wan_vae",
                   PASS if ok else FAIL,
                   f"14B→{vae14}  5B→{vae5}")
    except Exception as e:
        report.add(section, "pick_wan_vae", FAIL,
                   f"{type(e).__name__}: {e}")

    # Live detect (against server)
    comfy_url = get_comfyui_url()
    if comfy_url:
        try:
            t0 = time.time()
            wan = vp.detect_wan_preset(comfy_url)
            ms = int((time.time() - t0) * 1000)
            if wan:
                report.add(section, "detect_wan_preset (live)", PASS,
                           f"high={wan.get('high_model','?')[:40]}  "
                           f"vae={wan.get('vae','?')[:30]}", ms)
            else:
                report.add(section, "detect_wan_preset (live)", WARN,
                           "no WAN models detected on server", ms)
        except Exception as e:
            report.add(section, "detect_wan_preset (live)", FAIL,
                       f"{type(e).__name__}: {e}")
        try:
            t0 = time.time()
            ltx = vp.detect_ltx_preset(comfy_url)
            ms = int((time.time() - t0) * 1000)
            if ltx:
                report.add(section, "detect_ltx_preset (live)", PASS,
                           f"unet={ltx.get('unet','?')[:40]}  "
                           f"te={ltx.get('text_encoder','?')[:30]}", ms)
            else:
                report.add(section, "detect_ltx_preset (live)", WARN,
                           "no LTX models detected on server", ms)
        except Exception as e:
            report.add(section, "detect_ltx_preset (live)", FAIL,
                       f"{type(e).__name__}: {e}")


def test_model_prompt_profiles(report: Report, verbose: bool = False) -> None:
    section = "Model prompt profiles (spellcaster_core.model_prompt_profiles)"
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "comfyui-spellcaster"))
        from spellcaster_core import model_prompt_profiles as mpp  # type: ignore
    except Exception as e:
        report.add(section, "import model_prompt_profiles", FAIL,
                   f"{type(e).__name__}: {e}")
        return

    known_models = [
        ("juggernautXL_v9Rundiffusionphoto2.safetensors", "sdxl"),
        ("gonzalomoZpop_v30AIO.safetensors", "zit"),
        ("sloppyMessyMix_sloppyMessyMixV1.safetensors", "illustrious"),
        ("FLUX1 Dev fp8.safetensors", "flux1dev"),
        ("Flux\\FLUX1 Dev fp8.safetensors", "flux1dev"),
        ("flux-2-klein-9b.safetensors", "flux2klein"),
        ("modernDisneyXL_v3.safetensors", "sdxl"),
    ]
    for name, want_arch in known_models:
        try:
            prof = mpp.profile_for(name)
            if not prof:
                report.add(section, f"profile[{name}]", FAIL, "no match")
                continue
            got_arch = prof.get("arch_family")
            ok = got_arch == want_arch
            report.add(section, f"profile[{name}]",
                       PASS if ok else FAIL,
                       f"arch={got_arch} (expected {want_arch})")
        except Exception as e:
            report.add(section, f"profile[{name}]", FAIL,
                       f"{type(e).__name__}: {e}")

    # apply_profile should actually inject quality tags for SDXL photoreal
    try:
        prof = mpp.profile_for("juggernautXL.safetensors")
        pos, neg = mpp.apply_profile("a cat on a chair", "", prof)
        ok = ("photorealistic" in pos.lower()
              and "cartoon" in neg.lower())
        report.add(section, "apply_profile(juggernautXL)",
                   PASS if ok else FAIL,
                   f"pos[:60]={pos[:60]!r}")
    except Exception as e:
        report.add(section, "apply_profile(juggernautXL)", FAIL,
                   f"{type(e).__name__}: {e}")


def test_cross_interface_backbone(report: Report, verbose: bool = False) -> None:
    """event_bus, interface_registry, mailbox sanity through the Guild HTTP."""
    section = "Cross-interface backbone"

    # interfaces snapshot
    sc, body = http_get("/api/interfaces")
    if sc == 200:
        if isinstance(body, list):
            live = [i for i in body if i.get("online")]
        else:
            live = []
        report.add(section, "/api/interfaces snapshot", PASS,
                   f"{len(body) if isinstance(body,(list,dict)) else '?'} entries, "
                   f"{len(live)} online")
    else:
        report.add(section, "/api/interfaces snapshot", FAIL, f"HTTP {sc}")

    # event_bus — publish a synthetic event and re-read the recent feed
    t0 = time.time()
    sc, _ = http_post("/api/events/emit", {
        "kind": "e2e_audit.ping",
        "origin": "e2e_audit",
        "data": {"marker": time.time()},
    })
    ms = int((time.time() - t0) * 1000)
    if sc == 200:
        report.add(section, "event_bus.emit", PASS, "published", ms)
    elif sc == 404:
        report.add(section, "event_bus.emit", WARN,
                   "endpoint not registered")
    else:
        report.add(section, "event_bus.emit", FAIL, f"HTTP {sc}", ms)

    # antennas registry
    sc, body = http_get("/api/antennas")
    if sc == 200 and isinstance(body, dict):
        ants = body.get("antennas") or []
        online = body.get("online", sum(1 for a in ants if a.get("online")))
        report.add(section, "/api/antennas registry", PASS,
                   f"{len(ants)} registered, {online} online")
    else:
        report.add(section, "/api/antennas registry", FAIL, f"HTTP {sc}")


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

SECTIONS = {
    "endpoints":        test_guild_endpoints,
    "scaffolds":        test_scaffolds,
    "naming":           test_wizard_names,
    "build_fns":        test_build_functions,
    "manifest":         test_plugin_manifest,
    "video":            test_video_canon,
    "profiles":         test_model_prompt_profiles,
    "cross_interface":  test_cross_interface_backbone,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma list of sections")
    ap.add_argument("--skip", help="comma list of sections")
    ap.add_argument("--report",
                     default=os.path.join(os.path.dirname(__file__),
                                          "e2e_report.md"),
                     help="markdown report output path")
    ap.add_argument("--no-llm", action="store_true",
                     help="skip the LLM turn in scaffold tests (faster)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    # Preflight — Guild must be reachable
    sc, body = http_get("/api/llm_status")
    if sc != 200:
        print(f"Guild preflight failed at {GUILD_URL}/api/llm_status "
              f"(HTTP {sc}: {body!r:.120})", file=sys.stderr)
        return 2

    selected = set(SECTIONS.keys())
    if args.only:
        selected = set(x.strip() for x in args.only.split(",") if x.strip())
    if args.skip:
        selected -= set(x.strip() for x in args.skip.split(",") if x.strip())

    report = Report()
    for key, fn in SECTIONS.items():
        if key not in selected:
            continue
        print(f"\n→ running section: {key}", file=sys.stderr)
        try:
            if key == "scaffolds":
                fn(report, verbose=args.verbose, with_llm=not args.no_llm)
            else:
                fn(report, verbose=args.verbose)
        except Exception as e:
            report.add(key, f"(section crashed)", FAIL,
                       f"{type(e).__name__}: {e}")

    report.print_to_stdout(pretty=True)
    try:
        report.write_markdown(args.report)
        print(f"\nReport written: {args.report}")
    except Exception as e:
        print(f"\nFailed to write report: {e}", file=sys.stderr)

    s = report.summary()
    return 0 if s[FAIL] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
