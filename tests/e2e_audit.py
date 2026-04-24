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
    # Face-swap builders load inswapper_128.onnx via ONNX Runtime's TRT
    # provider. On boxes with a mismatched/missing
    # nvinfer_builder_resource_*.dll this crashes ComfyUI natively
    # (Windows access violation) — can't be caught from Python, and
    # /interrupt doesn't help because the crash happens inside the C
    # model-load before the interrupt is checked. Skip by default; opt
    # in with SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 once TRT is verified
    # healthy. Mirrors the §20.1 guard rationale.
    FACESWAP_BUILDERS = {
        "build_faceswap", "build_faceswap_model", "build_faceswap_mtb",
        "build_face_restore", "build_klein_headswap", "build_photobooth",
        "build_video_reactor", "build_photo_restore",
    }
    include_faceswap = os.environ.get(
        "SPELLCASTER_AUDIT_INCLUDE_FACESWAP", "").strip().lower() in (
            "1", "true", "yes", "on")
    tested = 0
    for name in build_fn_names:
        if tested >= max_tests:
            report.add(section, f"(cap reached at {max_tests})",
                       SKIP, f"{len(build_fn_names) - tested} untested")
            break
        if name in FACESWAP_BUILDERS and not include_faceswap:
            report.add(section, name, SKIP,
                       "faceswap family skipped (TRT crash risk); "
                       "set SPELLCASTER_AUDIT_INCLUDE_FACESWAP=1 to enable")
            tested += 1
            continue
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
    comfy_unsummoned = 0
    for ch in chars:
        cid = ch.get("id", "")
        name = ch.get("name", "")
        if ch.get("type") == "studio":
            studios_ok += 1
            continue
        if cid.startswith("comfyui_") or ch.get("type") == "comfyui_model":
            # Auto-detected ComfyUI models start with their bare filename
            # as the display name. Human-friendly naming happens inside
            # the Summon flow (LLM-assisted) once the user activates the
            # wizard. Un-summoned wizards legitimately have raw names —
            # don't flag them.
            if ch.get("needs_spellcaster") or not ch.get("activated", True):
                comfy_unsummoned += 1
                continue
            if looks_raw(name):
                comfy_raw.append((cid, name))
            else:
                comfy_named += 1

    report.add(section, "studio wizards", PASS,
               f"{studios_ok} core wizards present")
    total_model = comfy_named + len(comfy_raw)
    suffix = (f"  ({comfy_unsummoned} un-summoned skipped)"
              if comfy_unsummoned else "")
    if total_model == 0:
        report.add(section, "per-model wizards", SKIP,
                   f"no summoned per-model wizards{suffix}")
    elif not comfy_raw:
        report.add(section, "per-model wizards", PASS,
                   f"all {total_model} summoned wizards have human names"
                   f"{suffix}")
    else:
        snippet = ", ".join(f"{n!r}" for _, n in comfy_raw[:3])
        extra = f" +{len(comfy_raw)-3} more" if len(comfy_raw) > 3 else ""
        report.add(section, "per-model wizards", WARN,
                   f"{len(comfy_raw)}/{total_model} summoned but still raw: "
                   f"{snippet}{extra}{suffix}")


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
#  Post-audit sections — cover every function in every interface
#  (presence broker + blob bus + events schema + ST routes + GuildClient
#  + ControlNet model coverage + full coverage inventory). Added 2026-04-20.
# ═══════════════════════════════════════════════════════════════════════

def test_presence_broker(report: Report, verbose: bool = False) -> None:
    """ComfyUI-hosted presence broker — register / heartbeat / list /
    unregister round-trip. Also verifies multi-host coexistence (same
    `key` on two synthetic hosts = two `instance_id` entries)."""
    section = "Presence broker (ComfyUI)"
    comfy_url = get_comfyui_url()
    if not comfy_url:
        report.add(section, "broker.preflight", SKIP,
                   "comfyui_url not configured")
        return

    base = comfy_url.rstrip("/") + "/spellcaster/presence"

    def _post(path, body, timeout=3.0):
        try:
            req = urllib.request.Request(
                base + path,
                data=json.dumps(body).encode(),
                method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode())
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"error": str(e)}

    def _get(path, timeout=3.0):
        try:
            req = urllib.request.Request(base + path)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except Exception as e:
            return 0, {"error": str(e)}

    # Reachability
    t0 = time.time()
    sc, body = _get("/list")
    ms = int((time.time() - t0) * 1000)
    if sc != 200:
        report.add(section, "GET /list (baseline)", FAIL,
                   f"HTTP {sc}: {body}", ms)
        return
    peers_before = {p.get("instance_id") for p in body.get("peers", [])}
    report.add(section, "GET /list (baseline)", PASS,
               f"{len(peers_before)} peers", ms)

    # Reject bad key
    sc, body = _post("/register", {"key": "BAD-KEY-$"})
    report.add(section, "register rejects invalid key",
               PASS if sc == 400 else FAIL,
               f"HTTP {sc}")

    # Register two synthetic instances — same key, different host
    synth_key = "e2e_audit"
    sc1, r1 = _post("/register", {
        "key": synth_key, "host": "audit-hostA", "label": "Audit A"})
    sc2, r2 = _post("/register", {
        "key": synth_key, "host": "audit-hostB", "label": "Audit B"})
    if sc1 == 200 and sc2 == 200 and r1.get("instance_id") != r2.get("instance_id"):
        report.add(section, "multi-host coexistence", PASS,
                   f"{r1.get('instance_id')} + {r2.get('instance_id')}")
    else:
        report.add(section, "multi-host coexistence", FAIL,
                   f"sc1={sc1} sc2={sc2} r1={r1} r2={r2}")

    # Heartbeat refreshes
    sc, body = _post("/heartbeat", {
        "key": synth_key, "host": "audit-hostA"})
    report.add(section, "heartbeat refresh",
               PASS if sc == 200 and body.get("ok") else FAIL,
               f"age_s={body.get('age_s')}")

    # /list shows both
    sc, body = _get("/list")
    peers_after = {p.get("instance_id") for p in body.get("peers", [])}
    added = peers_after - peers_before
    if {r1.get("instance_id"), r2.get("instance_id")} <= added:
        report.add(section, "GET /list sees both synthetic peers", PASS,
                   f"+{len(added)} peers")
    else:
        report.add(section, "GET /list sees both synthetic peers", FAIL,
                   f"added={added}")

    # Unregister both — cleanup
    for host in ("audit-hostA", "audit-hostB"):
        sc, _ = _post("/unregister", {"key": synth_key, "host": host})
        report.add(section, f"unregister {host}",
                   PASS if sc == 200 else FAIL, f"HTTP {sc}")


def test_blob_bus(report: Report, verbose: bool = False) -> None:
    """ComfyUI-hosted blob bus — put / get / list / dedup / TTL ceiling.
    Exercises the multipart upload path used by every Send-to-X flow
    (GIMP / DT / Resolve blob-first transport)."""
    section = "Blob bus (ComfyUI)"
    comfy_url = get_comfyui_url()
    if not comfy_url:
        report.add(section, "blob.preflight", SKIP,
                   "comfyui_url not configured")
        return

    base = comfy_url.rstrip("/") + "/spellcaster/blob"
    payload = b"e2e_audit blob bus " + str(time.time()).encode()

    # Multipart upload
    import os as _os
    boundary = "----e2eAuditBlob" + _os.urandom(8).hex()
    parts = []
    def _f(name, value):
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    _f("origin", "e2e_audit")
    _f("kind", "test")
    _f("ttl_s", "120")  # short TTL so we don't pollute the store
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        b'Content-Disposition: form-data; name="file"; '
        b'filename="audit.bin"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n')
    parts.append(payload)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    t0 = time.time()
    try:
        req = urllib.request.Request(
            base + "/put", data=body, method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            })
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            put_rec = json.loads(resp.read().decode())
        ms = int((time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        report.add(section, "POST /blob/put", WARN,
                   f"HTTP {e.code} — blob bus may not be deployed yet")
        return
    except Exception as e:
        report.add(section, "POST /blob/put", FAIL, str(e))
        return

    h = put_rec.get("hash")
    if h and put_rec.get("url"):
        report.add(section, "POST /blob/put", PASS,
                   f"hash={h[:12]} size={put_rec.get('size')}", ms)
    else:
        report.add(section, "POST /blob/put", FAIL, str(put_rec))
        return

    # GET roundtrip
    try:
        with urllib.request.urlopen(put_rec["url"], timeout=5.0) as resp:
            got = resp.read()
        if got == payload:
            report.add(section, "GET /blob/<hash> roundtrip", PASS,
                       f"{len(got)}B exact match")
        else:
            report.add(section, "GET /blob/<hash> roundtrip", FAIL,
                       f"size mismatch got={len(got)} want={len(payload)}")
    except Exception as e:
        report.add(section, "GET /blob/<hash> roundtrip", FAIL, str(e))

    # Dedup — uploading the same bytes again should return the same hash
    try:
        req = urllib.request.Request(
            base + "/put", data=body, method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            })
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            put2 = json.loads(resp.read().decode())
        if put2.get("hash") == h:
            report.add(section, "dedup (same bytes → same hash)", PASS,
                       f"hash stable")
        else:
            report.add(section, "dedup (same bytes → same hash)", FAIL,
                       f"got {put2.get('hash')}")
    except Exception as e:
        report.add(section, "dedup (same bytes → same hash)", FAIL, str(e))

    # /list catalog
    try:
        with urllib.request.urlopen(base + "/list", timeout=3.0) as resp:
            lst = json.loads(resp.read().decode())
        blobs = lst.get("blobs") or []
        if any(b.get("hash") == h for b in blobs):
            report.add(section, "GET /blob/list", PASS,
                       f"{len(blobs)} live blobs incl. ours")
        else:
            report.add(section, "GET /blob/list", WARN,
                       f"ours missing ({len(blobs)} total)")
    except Exception as e:
        report.add(section, "GET /blob/list", FAIL, str(e))

    # 404 for unknown hash
    bogus = "0" * 64
    try:
        with urllib.request.urlopen(
                base + "/" + bogus, timeout=3.0) as resp:
            report.add(section, "GET /blob/<unknown>", FAIL,
                       f"expected 404, got {resp.status}")
    except urllib.error.HTTPError as e:
        report.add(section, "GET /blob/<unknown>", PASS if e.code == 404
                   else FAIL, f"HTTP {e.code}")
    except Exception as e:
        report.add(section, "GET /blob/<unknown>", FAIL, str(e))


def test_error_extraction(report: Report, verbose: bool = False) -> None:
    """spellcaster_core.dispatch.extract_execution_error +
    has_usable_outputs — canonical robust error extractor that every
    dispatch site delegates to. Covers the specific failure shapes we
    observed producing 'unknown error' in the Inpaint crash report:

      * status_str=error with message type == 'execution_error' but
        'exception_message' field present under 'message' instead
        (older ComfyUI builds / some custom nodes).
      * status_str=error with messages but NO execution_error type
        (interrupt-race, validation-after-submit).
      * status_str=error AND outputs emitted (partial success — the
        fix that lets ComfyUI-completed renders reach the plugin).
      * malformed status dicts (None, wrong shape).
    """
    section = "Error extraction"
    try:
        import importlib.util, os as _os
        here = _os.path.abspath(_os.path.dirname(__file__))
        mod_path = _os.path.abspath(_os.path.join(
            here, "..", "comfyui-spellcaster", "spellcaster_core",
            "dispatch.py"))
        spec = importlib.util.spec_from_file_location(
            "spellcaster_dispatch_audit", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        extract = mod.extract_execution_error
        has_outputs = mod.has_usable_outputs
    except Exception as e:
        report.add(section, "import dispatch.py", FAIL, str(e))
        return
    report.add(section, "import dispatch.py", PASS,
               f"module has {len([n for n in dir(mod) if not n.startswith('_')])} public names")

    cases = [
        # (name, status, expect_recognised, expect_substring)
        ("classic execution_error.exception_message",
         {"status_str": "error", "messages": [[
            "execution_error",
            {"exception_message": "Kernel size can't be greater",
             "exception_type": "RuntimeError", "node_type": "VAEEncode"}]]},
         True, "Kernel size"),
        ("execution_error with only 'message' field (non-canonical)",
         {"status_str": "error", "messages": [[
            "execution_error",
            {"message": "node failed", "node_id": "42"}]]},
         True, "node failed"),
        ("error type msg without exception_message",
         {"status_str": "error", "messages": [[
            "error",
            {"error": "preflight rejected", "details": "missing CN"}]]},
         True, "preflight rejected"),
        ("execution_interrupted (no exception)",
         {"status_str": "error", "messages": [[
            "execution_interrupted", {"prompt_id": "abc"}]]},
         False, "no recognised"),
        ("empty messages list",
         {"status_str": "error", "messages": []},
         False, "no recognised"),
        ("malformed status",
         None, False, "malformed"),
        ("status is a string",
         "broken", False, "malformed"),
        ("node_type prefix injection",
         {"status_str": "error", "messages": [[
            "execution_error",
            {"exception_message": "OOM",
             "node_type": "KSampler"}]]},
         True, "KSampler"),
    ]
    for name, status, expected_rec, substr in cases:
        try:
            detail, rec = extract(status)
            ok_rec = rec == expected_rec
            ok_sub = substr.lower() in detail.lower()
            if ok_rec and ok_sub:
                report.add(section, f"extract[{name}]", PASS,
                           f"detail={detail[:60]!r}")
            else:
                report.add(section, f"extract[{name}]", FAIL,
                           f"rec={rec} (want {expected_rec}); "
                           f"detail={detail[:120]!r} (want substr {substr!r})")
        except Exception as e:
            report.add(section, f"extract[{name}]", FAIL,
                       f"{type(e).__name__}: {e}")

    # has_usable_outputs truth table
    has_cases = [
        ("None entry", None, False),
        ("empty dict", {}, False),
        ("no outputs key", {"status": {}}, False),
        ("empty outputs", {"outputs": {}}, False),
        ("outputs with no filenames",
         {"outputs": {"10": {"images": [{"type": "output"}]}}}, False),
        ("outputs with images",
         {"outputs": {"10": {"images": [
            {"filename": "a.png", "subfolder": "", "type": "output"}]}}},
         True),
        ("outputs with gifs",
         {"outputs": {"10": {"gifs": [
            {"filename": "a.gif", "subfolder": "", "type": "output"}]}}},
         True),
        ("outputs with videos",
         {"outputs": {"12": {"videos": [
            {"filename": "a.mp4", "subfolder": "", "type": "output"}]}}},
         True),
        ("outputs malformed",
         {"outputs": "not a dict"}, False),
    ]
    for name, entry, expected in has_cases:
        try:
            got = has_outputs(entry)
            if got == expected:
                report.add(section, f"has_usable_outputs[{name}]",
                           PASS, f"{got}")
            else:
                report.add(section, f"has_usable_outputs[{name}]",
                           FAIL, f"got {got}, want {expected}")
        except Exception as e:
            report.add(section, f"has_usable_outputs[{name}]",
                       FAIL, f"{type(e).__name__}: {e}")


def test_events_schema(report: Report, verbose: bool = False) -> None:
    """spellcaster_core/events.py — every dataclass round-trips through
    to_payload() and parse_event(). Proves that publishers and
    subscribers share a single wire contract."""
    section = "Event schema"
    try:
        # Import from the canonical location. Tests run from repo root.
        # Prefer a clean sys.path import (mirrors how plugins load
        # spellcaster_core) over spec_from_file_location, because
        # dataclass()'s _is_type helper walks sys.modules to resolve
        # forward refs — spec-loaded modules that aren't registered
        # there crash with an opaque NoneType.__dict__ error.
        core_parent = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "comfyui-spellcaster"))
        if core_parent not in sys.path:
            sys.path.insert(0, core_parent)
        import importlib as _importlib
        # Drop a stale import (event_bus edited between runs) so we
        # always exercise the on-disk copy.
        sys.modules.pop("spellcaster_core.events", None)
        events_mod = _importlib.import_module("spellcaster_core.events")
    except Exception as e:
        report.add(section, "import events.py", FAIL, str(e))
        return
    report.add(section, "import events.py", PASS,
               f"registry has {len(events_mod.EVENT_SCHEMAS)} explicit kinds")

    # For every class in __all__, construct a default instance and
    # verify validate + to_payload + parse_event.
    all_names = getattr(events_mod, "__all__", [])
    dataclass_names = [n for n in all_names
                        if isinstance(getattr(events_mod, n, None), type)
                        and hasattr(getattr(events_mod, n), "KIND")]
    for name in dataclass_names:
        cls = getattr(events_mod, name)
        try:
            inst = cls()
            payload = inst.to_payload()
            assert isinstance(payload, dict)
            assert "KIND" not in payload
            assert cls.validate(payload) is True
            # Wildcard kinds require an origin to resolve; use a synthetic
            # origin for those and a direct kind lookup for the rest.
            kind = cls.KIND
            if kind.startswith("*."):
                kind = "e2e_audit" + kind[1:]
            parsed = events_mod.parse_event(kind, payload)
            if parsed is None and kind in events_mod.EVENT_SCHEMAS:
                raise AssertionError(f"parse_event returned None for {kind}")
            report.add(section, f"{name} round-trip", PASS,
                       f"kind={cls.KIND}")
        except Exception as e:
            report.add(section, f"{name} round-trip", FAIL, str(e))

    # publish_event helper + wildcard expansion
    try:
        captured = []

        class _Bus:
            def publish(self, kind, *, origin, data):
                captured.append((kind, origin, data))

        bus = _Bus()
        AssetSend = getattr(events_mod, "AssetSend")
        events_mod.publish_event(
            bus, AssetSend(image_url="/x", hash="h", source="audit"),
            origin="e2e_audit")
        if captured and captured[0][0] == "e2e_audit.asset.send":
            report.add(section, "publish_event() wildcard expansion", PASS,
                       captured[0][0])
        else:
            report.add(section, "publish_event() wildcard expansion", FAIL,
                       f"got {captured}")
    except Exception as e:
        report.add(section, "publish_event() wildcard expansion", FAIL,
                   str(e))


def test_sillytavern_routes(report: Report, verbose: bool = False) -> None:
    """SillyTavern server-plugin routes. ST runs its own HTTP server
    on port 8000 by default; the server-plugin mounts routes under
    /api/plugins/spellcaster-st/. Tests probe each route with stub
    payloads. Gracefully skipped if ST isn't running."""
    section = "SillyTavern routes"
    sc, cfg = http_get("/api/config")
    st_url = (cfg.get("sillytavern_url") if isinstance(cfg, dict)
              else "") or "http://127.0.0.1:8000"
    base = st_url.rstrip("/") + "/api/plugins/spellcaster-st"

    def _probe(method, path, body=None, expected=(200, 204, 404)):
        url = base + path
        try:
            data = (json.dumps(body).encode("utf-8")
                    if method == "POST" and body is not None else None)
            req = urllib.request.Request(url, data=data, method=method,
                headers={"Content-Type": "application/json"} if data else {})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception as e:
            return None, str(e)
        return status, ""

    # Preflight — is ST up at all?
    sc, err = _probe("GET", "/peers")
    if sc is None:
        report.add(section, "ST preflight", SKIP,
                   f"ST not running ({err})")
        return
    report.add(section, "ST preflight", PASS,
               f"reachable at {st_url}")

    routes: list[tuple[str, str, Optional[dict]]] = [
        ("GET",  "/peers",        None),
        ("GET",  "/models",       None),
        ("GET",  "/capabilities", None),
        ("GET",  "/cross/inbox",  None),
        ("POST", "/settings",     {"comfyui_url": "http://127.0.0.1:8188"}),
    ]
    for method, path, body in routes:
        sc, err = _probe(method, path, body)
        if sc is None:
            report.add(section, f"{method} {path}", FAIL, err)
        elif sc in (200, 204):
            report.add(section, f"{method} {path}", PASS, f"HTTP {sc}")
        elif sc == 404:
            report.add(section, f"{method} {path}", WARN,
                       "route not registered (older ST plugin build?)")
        else:
            report.add(section, f"{method} {path}", WARN,
                       f"HTTP {sc}")


def test_guild_client(report: Report, verbose: bool = False) -> None:
    """Resolve plugin's GuildClient facade — every public method,
    called against the live Guild."""
    section = "GuildClient (Resolve shared/)"
    try:
        import importlib.util
        here = os.path.abspath(os.path.dirname(__file__))
        api_path = os.path.abspath(os.path.join(
            here, "..", "plugins", "resolve", "shared",
            "spellcaster_api.py"))
        spec = importlib.util.spec_from_file_location(
            "spellcaster_api", api_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        client = mod.GuildClient(GUILD_URL)
    except Exception as e:
        report.add(section, "import + construct", FAIL, str(e))
        return
    report.add(section, "import + construct", PASS,
               f"base_url={client.base_url}")

    # Introspect methods and call the ones that don't take required args
    # beyond the live endpoint.
    import inspect as _inspect
    methods = []
    for name, member in _inspect.getmembers(client, predicate=callable):
        if name.startswith("_"):
            continue
        try:
            sig = _inspect.signature(member)
            # Zero-required-arg methods we can call directly. Must
            # include KEYWORD_ONLY — methods like import_timeline(*,
            # timeline_name, fps, clips) are all keyword-only-required,
            # and calling them with no kwargs raises a TypeError that
            # previously reported as a spurious FAIL.
            required = [p for p in sig.parameters.values()
                        if p.default is _inspect.Parameter.empty
                        and p.kind in (_inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                       _inspect.Parameter.POSITIONAL_ONLY,
                                       _inspect.Parameter.KEYWORD_ONLY)]
            if not required:
                methods.append(name)
        except (TypeError, ValueError):
            continue
    for name in methods:
        t0 = time.time()
        try:
            getattr(client, name)()
            ms = int((time.time() - t0) * 1000)
            report.add(section, f"{name}()", PASS, "no exception", ms)
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            err = str(e)[:80]
            # Some endpoints may legitimately not exist in older Guilds
            if "404" in err or "not found" in err.lower():
                report.add(section, f"{name}()", WARN, err, ms)
            else:
                report.add(section, f"{name}()", FAIL, err, ms)


def test_cn_model_coverage(report: Report, verbose: bool = False) -> None:
    """For every ControlNet mode in the GIMP plugin's
    CONTROLNET_GUIDE_MODES, verify the referenced cn_model file is
    actually on the ComfyUI server. Catches mis-wired mappings like
    'Normal Map → control-lora-depth' (unrelated model)."""
    section = "ControlNet model coverage"
    comfy_url = get_comfyui_url()
    if not comfy_url:
        report.add(section, "preflight", SKIP,
                   "comfyui_url not configured")
        return

    # Fetch available CN models once
    try:
        url = comfy_url.rstrip("/") + "/object_info/ControlNetLoader"
        with urllib.request.urlopen(url, timeout=10.0) as resp:
            oi = json.loads(resp.read().decode())
    except Exception as e:
        report.add(section, "fetch /object_info/ControlNetLoader",
                   FAIL, str(e))
        return
    choices = (oi.get("ControlNetLoader", {}).get("input", {})
               .get("required", {}).get("control_net_name", [[]]))
    available = set(choices[0]) if choices and isinstance(choices[0], list) else set()
    report.add(section, "server CN inventory", PASS,
               f"{len(available)} CN files visible")

    # Parse CONTROLNET_GUIDE_MODES out of _spellcaster_main.py without
    # executing the GIMP plugin (imports GIMP libs).
    try:
        main_py = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "plugins", "gimp",
            "comfyui-connector", "_spellcaster_main.py"))
        import ast as _ast
        tree = _ast.parse(open(main_py, encoding="utf-8").read())
        modes_dict = None
        for node in tree.body:
            if (isinstance(node, _ast.Assign)
                    and any(isinstance(t, _ast.Name)
                             and t.id == "CONTROLNET_GUIDE_MODES"
                             for t in node.targets)):
                modes_dict = _ast.literal_eval(node.value)
                break
        if modes_dict is None:
            raise RuntimeError("CONTROLNET_GUIDE_MODES not found in main.py")
    except Exception as e:
        report.add(section, "parse CONTROLNET_GUIDE_MODES", FAIL, str(e))
        return
    report.add(section, "parse CONTROLNET_GUIDE_MODES", PASS,
               f"{len(modes_dict)} modes defined")

    # Exercise the SAME resolver logic §26 describes for the live
    # plugin: CONTROLNET_GUIDE_MODES mappings are authoritative at the
    # UI level, but
    # _resolve_cn_paths_in_workflow rewrites them to installed variants
    # at dispatch time (flat-form ↔ HF folder-form, fp16 stripping,
    # basename + stem matching). A mapping is "resolvable" when any of
    # those matches succeeds — only then is it really a missing file.
    GENERIC_HF = {"diffusion_pytorch_model.safetensors",
                   "pytorch_model.safetensors", "model.safetensors"}

    def _stem(path: str) -> str:
        norm = path.replace("\\", "/")
        bn = norm.rsplit("/", 1)[-1].lower()
        if bn in GENERIC_HF and "/" in norm:
            parent = norm.rsplit("/", 2)[-2].lower()
            return parent
        stem = bn.rsplit(".", 1)[0]
        if stem.endswith("_fp16"):
            stem = stem[:-len("_fp16")]
        return stem

    available_stems = {_stem(a) for a in available}
    available_basenames = {
        a.replace("\\", "/").rsplit("/", 1)[-1].lower()
        for a in available}

    def _resolvable(model_file: str) -> bool:
        if model_file in available:
            return True
        bn = model_file.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if bn not in GENERIC_HF and bn in available_basenames:
            return True
        s = _stem(model_file)
        if s and s in available_stems:
            return True
        return False

    missing = []
    for mode_name, spec in modes_dict.items():
        cn_models = spec.get("cn_models") or {}
        for arch, model_file in cn_models.items():
            if not model_file:
                continue
            if not _resolvable(model_file):
                missing.append(f"{mode_name!r}[{arch}] → {model_file}")
    if not missing:
        report.add(section, "every mode × arch resolves to an installed file",
                   PASS, f"{len(modes_dict)} modes verified via resolver")
    else:
        # Don't fail outright — genuinely missing files = install gap,
        # not a wiring bug. Warn with details.
        sample = "; ".join(missing[:5])
        more = f" (+{len(missing)-5} more)" if len(missing) > 5 else ""
        report.add(section, "every mode × arch resolves to an installed file",
                   WARN,
                   f"{len(missing)} mappings unresolvable: {sample}{more}")


def test_coverage_inventory(report: Report, verbose: bool = False) -> None:
    """Introspective sweep: for every importable module on every
    plugin surface, count public functions and flag what's not
    exercised elsewhere in this audit. The goal is a ceiling-count
    rather than per-function tests — live code is too plumbing-heavy
    for unit-style isolation. We report:

        total_public_fns / exercised_here

    where exercised_here is a coarse grep: if the function's name
    appears anywhere else in this file's source, it counts. This is
    intentionally over-generous; the report's real value is the
    INVENTORY (what exists) more than the percentage.
    """
    section = "Coverage inventory"
    import ast as _ast, inspect as _inspect

    repo_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), ".."))
    surfaces = [
        ("spellcaster_core",
         os.path.join(repo_root, "comfyui-spellcaster", "spellcaster_core")),
        ("comfyui_pack",
         os.path.join(repo_root, "comfyui-spellcaster")),
        ("gimp_plugin",
         os.path.join(repo_root, "plugins", "gimp", "comfyui-connector")),
        ("resolve_shared",
         os.path.join(repo_root, "plugins", "resolve", "shared")),
        ("resolve_bridge",
         os.path.join(repo_root, "plugins", "resolve",
                      "spellcaster_bridge")),
        ("guild_tavern",
         os.path.join(repo_root, "tavern")),
    ]

    # Load this audit's source once for "exercised" grep
    with open(__file__, encoding="utf-8") as f:
        audit_src = f.read()

    grand_total = 0
    grand_exercised = 0
    for surface_name, surface_dir in surfaces:
        if not os.path.isdir(surface_dir):
            report.add(section, f"{surface_name}", SKIP,
                       "dir missing")
            continue
        public_fns: list[str] = []
        for root, _dirs, files in os.walk(surface_dir):
            # Skip caches + vendored
            skip_parts = {"__pycache__", ".pytest_cache", "nsfw",
                          "staging", "node_modules"}
            if any(p in root.split(os.sep) for p in skip_parts):
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(root, fn)
                try:
                    tree = _ast.parse(open(path, encoding="utf-8").read())
                except Exception:
                    continue
                for node in _ast.walk(tree):
                    if isinstance(node, _ast.FunctionDef) and not node.name.startswith("_"):
                        public_fns.append(node.name)
        uniq = sorted(set(public_fns))
        exercised = [n for n in uniq
                     if (f" {n}(" in audit_src or f"\"{n}\"" in audit_src
                          or f"'{n}'" in audit_src)]
        grand_total += len(uniq)
        grand_exercised += len(exercised)
        pct = (100.0 * len(exercised) / max(1, len(uniq)))
        report.add(section, f"{surface_name}",
                   PASS if len(exercised) else WARN,
                   f"{len(exercised)}/{len(uniq)} referenced ({pct:.0f}%)")

    # Summary
    pct = 100.0 * grand_exercised / max(1, grand_total)
    report.add(section, "TOTAL across all surfaces",
               PASS,
               f"{grand_exercised}/{grand_total} public fns referenced "
               f"({pct:.0f}%)")


# ═══════════════════════════════════════════════════════════════════════
#  REGRESSION GUARDS — pin the bug classes we've chased this cycle
# ═══════════════════════════════════════════════════════════════════════
#
# These sections don't require a live Guild or ComfyUI. They pin the
# bug classes we've been hunting over the recent sessions:
#
#   upload_cache    — privacy.CACHE_PREFIXES exempts sc_cache_ from the
#                     per-workflow wipe; purge_cache targets only those.
#   guards          — blank-PNG / uniform-mask detectors classify the
#                     synthetic edge cases correctly (the classifiers
#                     that drive SAM3 / BiRefNet "nothing matched"
#                     warnings and the IC-Light fallback).
#   iclight_cn      — build_iclight routes the normal map through a
#                     proper ControlNet (not the FBC opt_background
#                     colour-compositing slot).
#   plugin_surface  — AST sweep of _spellcaster_main.py:
#                       - registration integrity (§7 of CLAUDE.md):
#                         every _PROC_FEATURES key has a menu_map entry
#                         and a _menu_paths entry.
#                       - _apply_mask_mode calls pass 5 or 6 positional
#                         args (not the silently-swallowed 6-arg regression
#                         from 2026-04-20).
#                       - every _run_* handler's outer `except Exception`
#                         prints a traceback before the Gimp.message.
#                       - _download_image() assignments use bytes-typed
#                         variable names (no "mask_path = bytes" footgun).


def test_upload_cache(report: Report, verbose: bool = False) -> None:
    """Pure-Python test of the GIMP upload-cache privacy exemption.

    Monkey-patches ``_overwrite_with_tiny`` so no network calls fire
    and confirms:
      * ``sc_cache_*`` filenames are skipped by ``cleanup_inputs``
        when passed via the workflow dict AND the full-server-scan
        path (via a stub /object_info response).
      * ``cleanup_outputs`` still wipes result PNGs.
      * ``purge_cache`` does the OPPOSITE: targets ONLY the cache
        prefixes, leaves ``gimp_*`` / ``spellcaster_*`` alone.
      * ``CACHE_PREFIXES`` and ``OWNED_PREFIXES`` don't overlap.
    """
    section = "Upload cache & privacy"
    t0 = time.time()

    try:
        from spellcaster_core import privacy as _priv
    except Exception as e:
        report.add(section, "import privacy", FAIL,
                   f"{type(e).__name__}: {e}")
        return

    # Sanity: prefixes don't overlap (a sc_cache_* file would otherwise
    # also match the OWNED_PREFIXES wipe path).
    overlap = set(_priv.CACHE_PREFIXES) & set(_priv.OWNED_PREFIXES)
    report.add(section,
               "CACHE_PREFIXES \u2229 OWNED_PREFIXES is empty",
               PASS if not overlap else FAIL,
               f"overlap={overlap}" if overlap else "")

    # Spy on the HTTP wipe helper so we can assert WHICH files got touched
    # without hitting any server.
    wiped: list[str] = []

    def _spy_overwrite(server: str, fname: str) -> None:
        wiped.append(fname)

    orig_over = _priv._overwrite_with_tiny
    _priv._overwrite_with_tiny = _spy_overwrite

    # Stub urlopen for the Strategy-2 /object_info scan.
    import urllib.request as _u
    orig_urlopen = _u.urlopen
    SERVER_INPUTS = ["gimp_123.png", "sc_cache_abc.png",
                     "spellcaster_xyz.png", "unrelated_user_file.png"]

    class _FakeResp:
        status = 200
        def __init__(self, body: bytes): self._body = body
        def __enter__(self): return self
        def __exit__(self, *_a): pass
        def read(self): return self._body

    def _fake_urlopen(req, *a, **kw):
        url = getattr(req, "full_url", str(req))
        if "/object_info/LoadImage" in url:
            body = json.dumps({
                "LoadImage": {"input": {"required": {
                    "image": [SERVER_INPUTS]}}}}).encode()
            return _FakeResp(body)
        if "/spellcaster/privacy/delete" in url:
            # Simulate "pack not installed" so the privacy code falls
            # back to the legacy `_overwrite_with_tiny` path that the
            # spy above watches. Without this, `_delete_via_route`
            # would see a 200+empty-body from the default stub and
            # short-circuit the fallback — the spy would never fire.
            import urllib.error as _ue
            raise _ue.HTTPError(url, 404, "not found",
                                 hdrs={}, fp=None)
        # Anything else: empty body, caller will choke — desired.
        return _FakeResp(b"{}")

    _u.urlopen = _fake_urlopen
    try:
        # Case 1 — cleanup_inputs with a workflow that REFERENCES a
        # cache-protected file in a LoadImage node. It must not wipe.
        wf = {
            "1": {"class_type": "LoadImage",
                   "inputs": {"image": "sc_cache_deadbeef.png"}},
            "2": {"class_type": "LoadImage",
                   "inputs": {"image": "gimp_abc.png"}},
        }
        wiped.clear()
        _priv.cleanup_inputs("http://test:1", workflow=wf)
        cache_wiped = [f for f in wiped if f.startswith("sc_cache_")]
        gimp_wiped = [f for f in wiped if f.startswith("gimp_")]
        report.add(section,
                   "cleanup_inputs SKIPS sc_cache_* from workflow",
                   PASS if not cache_wiped else FAIL,
                   f"wiped={cache_wiped}")
        report.add(section,
                   "cleanup_inputs WIPES gimp_* from workflow",
                   PASS if gimp_wiped else FAIL,
                   f"wiped={gimp_wiped}")

        # Case 2 — Strategy-2 server scan. sc_cache_* stays, gimp_*
        # and spellcaster_* go, user files ignored.
        wiped.clear()
        _priv.cleanup_inputs("http://test:1", workflow=None)
        want_wiped = {"gimp_123.png", "spellcaster_xyz.png"}
        want_alive = {"sc_cache_abc.png", "unrelated_user_file.png"}
        got_wiped = set(wiped)
        missing = want_wiped - got_wiped
        extra = got_wiped & want_alive
        ok = not missing and not extra
        report.add(section,
                   "cleanup_inputs server-scan exempts sc_cache_*",
                   PASS if ok else FAIL,
                   f"missing={missing}, extra={extra}")

        # Case 3 — purge_cache does the INVERSE: only sc_cache_*.
        wiped.clear()
        res = _priv.purge_cache("http://test:1")
        pc_wiped = set(res.get("wiped") or [])
        only_cache = all(f.startswith("sc_cache_") for f in pc_wiped)
        has_the_cache_one = "sc_cache_abc.png" in pc_wiped
        report.add(section,
                   "purge_cache targets ONLY CACHE_PREFIXES",
                   PASS if only_cache and has_the_cache_one else FAIL,
                   f"wiped={sorted(pc_wiped)}")

        # Case 4 — cleanup_outputs wipes its arg unconditionally.
        wiped.clear()
        _priv.cleanup_outputs("http://test:1", [
            ("result_1.png", "", "output"),
            ("sc_cache_should_still_go_if_passed_here.png", "", "output"),
        ])
        report.add(section,
                   "cleanup_outputs wipes all result files",
                   PASS if len(wiped) == 2 else FAIL,
                   f"wiped={wiped}")
    finally:
        _priv._overwrite_with_tiny = orig_over
        _u.urlopen = orig_urlopen

    report.add(section, "section complete", PASS,
               elapsed_ms=int((time.time() - t0) * 1000))


# ─── Synthetic PNG helper used by multiple regression sections ─────────

def _synth_png(w: int, h: int, color_type: int, *,
                fill_val: int = 255,
                alpha: "int | None" = None,
                mixed: bool = False) -> bytes:
    """Minimal valid PNG builder for test fixtures.

    color_type: 0=L, 2=RGB, 3=palette (unused), 4=LA, 6=RGBA.
    fill_val   : grayscale/R channel byte.
    alpha      : override the alpha channel byte (RGBA/LA only).
    mixed      : generate a 50/50 black-white pattern (structure).
    """
    import struct
    import zlib
    import binascii
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    ihdr = struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    if mixed and color_type == 0:
        rows = []
        for _y in range(h):
            pix = b"\xff" * (w // 2) + b"\x00" * (w - w // 2)
            rows.append(b"\x00" + pix)
        raw = b"".join(rows)
    else:
        if color_type == 6:
            a = alpha if alpha is not None else 255
            pixel = bytes([fill_val, 0, 0, a])
        elif color_type == 4:
            a = alpha if alpha is not None else 255
            pixel = bytes([fill_val, a])
        elif color_type == 2:
            pixel = bytes([fill_val, 0, 0])
        else:
            pixel = bytes([fill_val])
        row = b"\x00" + pixel * w
        raw = row * h
    idat = zlib.compress(raw)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", idat)
            + _chunk(b"IEND", b""))


def _extract_plugin_functions(*names: str) -> dict:
    """Lift standalone helper functions out of the GIMP plugin source
    without importing the whole module (``_spellcaster_main.py``
    does ``import gi`` at top-level, which fails off-GIMP).

    Returns ``{name: callable}`` for each requested function. A miss
    leaves the key absent; callers should treat that as SKIP.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(repo_root, "plugins", "gimp", "comfyui-connector",
                        "_spellcaster_main.py")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        src = f.read()
    import ast as _ast
    try:
        tree = _ast.parse(src)
    except Exception:
        return {}
    out: dict = {}
    requested = set(names)
    for node in tree.body:  # module-level only \u2014 no method defs
        if isinstance(node, _ast.FunctionDef) and node.name in requested:
            src_slice = _ast.get_source_segment(src, node)
            if not src_slice:
                continue
            ns: dict = {}
            try:
                exec(src_slice, ns)
            except Exception:
                continue
            if node.name in ns:
                out[node.name] = ns[node.name]
    return out


def test_guards(report: Report, verbose: bool = False) -> None:
    """Pin the blank/uniform classifiers that drive SAM3 / BiRefNet
    "nothing matched" warnings and the IC-Light rembg fallback.

    Each classifier gets a canned suite of synthetic PNGs with known
    answers. A regression that makes either function always-True or
    always-False would show up here immediately.
    """
    section = "Blank/uniform classifiers"
    t0 = time.time()

    fns = _extract_plugin_functions(
        "_looks_like_blank_rembg", "_looks_like_uniform_mask")
    blank = fns.get("_looks_like_blank_rembg")
    uni = fns.get("_looks_like_uniform_mask")

    if not blank or not uni:
        report.add(section, "extract helpers from _spellcaster_main.py",
                   SKIP, "helper not found (refactored?)")
        return

    blank_cases = [
        # (label, png_bytes, expect_blank)
        ("empty bytes",            b"",                                   True),
        ("garbage bytes",          b"not a PNG",                          True),
        ("RGBA alpha=0 (blank)",    _synth_png(16, 16, 6, alpha=0),        True),
        ("RGBA alpha=255 (opaque)", _synth_png(16, 16, 6, alpha=255),      False),
        ("RGB (no alpha channel)",  _synth_png(16, 16, 2),                 True),
        ("LA alpha=0",              _synth_png(16, 16, 4, alpha=0),        True),
        ("LA alpha=255",            _synth_png(16, 16, 4, alpha=255),      False),
    ]
    for label, buf, want in blank_cases:
        try:
            got = bool(blank(buf))
        except Exception as e:
            report.add(section, f"blank: {label}", FAIL,
                       f"{type(e).__name__}: {e}")
            continue
        report.add(section, f"blank: {label}",
                   PASS if got == want else FAIL,
                   "" if got == want else f"got={got} want={want}")

    uni_cases = [
        ("all-black L",   _synth_png(16, 16, 0, fill_val=0),   True),
        ("all-white L",   _synth_png(16, 16, 0, fill_val=255), True),
        ("mixed L",       _synth_png(32, 32, 0, mixed=True),   False),
        ("empty",         b"",                                  True),
    ]
    for label, buf, want in uni_cases:
        try:
            got = bool(uni(buf))
        except Exception as e:
            report.add(section, f"uniform: {label}", FAIL,
                       f"{type(e).__name__}: {e}")
            continue
        report.add(section, f"uniform: {label}",
                   PASS if got == want else FAIL,
                   "" if got == want else f"got={got} want={want}")

    report.add(section, "section complete", PASS,
               elapsed_ms=int((time.time() - t0) * 1000))


def test_iclight_cn(report: Report, verbose: bool = False) -> None:
    """Pin the IC-Light normal-map routing fix: normal maps go through
    a real ``control_v11p_sd15_normalbae`` ControlNet, NOT through
    ``iclight_sd15_fbc``'s ``opt_background`` colour-compositing slot.

    Builds the workflow in two configurations and inspects the graph
    node types + filenames. Doesn't hit ComfyUI \u2014 pure builder
    compile.
    """
    section = "IC-Light normal-map routing"
    t0 = time.time()

    try:
        from spellcaster_core.workflows import build_iclight
    except Exception as e:
        report.add(section, "import build_iclight", FAIL,
                   f"{type(e).__name__}: {e}")
        return

    # Path A: normal map provided. Expect FC UNET + normalbae CN chain.
    try:
        wf_a = build_iclight(
            image_filename="test_input.png",
            ckpt_name="SD-1.5\\v1-5-pruned-emaonly.safetensors",
            prompt="studio light from top-left",
            negative="",
            seed=42,
            normal_map_filename="test_normal.png",
        )
    except Exception as e:
        report.add(section, "build_iclight(normal=X) compiles", FAIL,
                   f"{type(e).__name__}: {e}")
        return
    classes_a = {n.get("class_type", "") for n in wf_a.values()
                 if isinstance(n, dict)}

    # FBC model is the bug class B regression \u2014 must not be loaded.
    has_fbc = any(
        "iclight_sd15_fbc" in (n.get("inputs", {}) or {}).get("model_path", "")
        or "iclight_sd15_fbc" in json.dumps(n.get("inputs") or {})
        for n in wf_a.values() if isinstance(n, dict))
    report.add(section,
               "normal-map path does NOT load iclight_sd15_fbc",
               PASS if not has_fbc else FAIL,
               "FBC would re-introduce the pastel-colour bug"
               if has_fbc else "")

    # ControlNet chain MUST be present with the normalbae model.
    has_cn_loader = "ControlNetLoader" in classes_a
    has_cn_apply = "ControlNetApplyAdvanced" in classes_a
    cn_names = [
        (n.get("inputs", {}) or {}).get("control_net_name", "")
        for n in wf_a.values()
        if isinstance(n, dict)
        and n.get("class_type") == "ControlNetLoader"
    ]
    has_normalbae = any("normalbae" in (n or "").lower() for n in cn_names)
    report.add(section,
               "normal-map path loads ControlNetLoader",
               PASS if has_cn_loader else FAIL,
               f"classes={sorted(classes_a)}")
    report.add(section,
               "normal-map path applies ControlNetApplyAdvanced",
               PASS if has_cn_apply else FAIL)
    report.add(section,
               "CN model is normalbae (surface-aware)",
               PASS if has_normalbae else FAIL,
               f"cn_names={cn_names}")

    # Confirm the normal map is loaded as an IMAGE (LoadImage) \u2014
    # NOT VAE-encoded to a latent (the old FBC path).
    nm_load = any(
        (n.get("inputs") or {}).get("image", "") == "test_normal.png"
        and n.get("class_type") == "LoadImage"
        for n in wf_a.values() if isinstance(n, dict))
    report.add(section,
               "normal map loaded as image (not latent)",
               PASS if nm_load else FAIL)

    # Path B: NO normal map. Expect FC UNET + NO CN.
    try:
        wf_b = build_iclight(
            image_filename="test_input.png",
            ckpt_name="SD-1.5\\v1-5-pruned-emaonly.safetensors",
            prompt="studio light",
            negative="",
            seed=42,
            normal_map_filename=None,
        )
    except Exception as e:
        report.add(section, "build_iclight(normal=None) compiles", FAIL,
                   f"{type(e).__name__}: {e}")
        return
    classes_b = {n.get("class_type", "") for n in wf_b.values()
                 if isinstance(n, dict)}
    report.add(section,
               "no-normal path does NOT include ControlNet",
               PASS if "ControlNetLoader" not in classes_b
               and "ControlNetApplyAdvanced" not in classes_b
               else FAIL,
               f"classes={sorted(classes_b)}")

    report.add(section, "section complete", PASS,
               elapsed_ms=int((time.time() - t0) * 1000))


def test_plugin_surface(report: Report, verbose: bool = False) -> None:
    """AST sweep of the GIMP plugin. Catches four regression classes:

      1. Registration integrity (CLAUDE.md §7): the three dicts
         ``_PROC_FEATURES`` / ``menu_map`` / ``_menu_paths`` must have
         identical keys. A procedure missing from any one of them
         silently fails to appear in the GIMP menu.
      2. ``_apply_mask_mode`` arg count. The signature is
         ``(server, image, img_data, layer_name, mask_enabled,
         keep_size=False)`` \u2014 5 required + 1 kwarg-style
         positional. 4 args = missing flag; 7+ = off-by-one
         regression.
      3. Traceback discipline: every ``_run_*`` handler whose outer
         ``except Exception`` shows a ``Gimp.message`` must first
         print the traceback. Silent tracebacks are how we hunted
         ghosts for three sessions.
      4. ``_download_image`` bytes-typed variables. The helper
         returns PNG bytes, NOT a path \u2014 assigning into a
         variable named ``*_path`` is the footgun that caused
         "Anything But" to die with "embedded null byte".
      5. Upload-cache migration coverage: count remaining
         ``_export_image_to_tmp(image)`` \u2192 ``_upload_image(srv,
         tmp, ...)`` idioms and report. Regression-checked against
         a baseline.
    """
    section = "Plugin surface (AST)"
    t0 = time.time()

    repo_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), ".."))
    path = os.path.join(repo_root, "plugins", "gimp", "comfyui-connector",
                        "_spellcaster_main.py")
    if not os.path.exists(path):
        report.add(section, "_spellcaster_main.py present", SKIP,
                   "file missing")
        return
    with open(path, encoding="utf-8") as f:
        src = f.read()

    import ast as _ast
    try:
        tree = _ast.parse(src)
    except SyntaxError as e:
        report.add(section, "plugin parses", FAIL,
                   f"line {e.lineno}: {e.msg}")
        return
    report.add(section, "plugin parses", PASS)

    # ── 1. Registration-integrity ─────────────────────────────
    def _dict_keys_at_name(var_name: str) -> "set[str] | None":
        """Return the set of string keys for the FIRST assignment of
        ``var_name = {...}`` or ``... = {var_name: ...}`` at any
        depth that has literal string keys. Walk the whole tree
        because these dicts live inside ``do_query_procedures``."""
        for node in _ast.walk(tree):
            # Direct module-level assign: `var_name = {...}`
            if isinstance(node, _ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, _ast.Name) and tgt.id == var_name
                            and isinstance(node.value, _ast.Dict)):
                        return {k.value for k in node.value.keys
                                if isinstance(k, _ast.Constant)
                                and isinstance(k.value, str)}
            # Inside do_query_procedures: `self.<var_name> = {...}` or
            # `<var_name> = {...}` local.
            if isinstance(node, _ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, _ast.Attribute)
                            and tgt.attr == var_name
                            and isinstance(node.value, _ast.Dict)):
                        return {k.value for k in node.value.keys
                                if isinstance(k, _ast.Constant)
                                and isinstance(k.value, str)}
        return None

    proc_keys = _dict_keys_at_name("_PROC_FEATURES")
    menu_keys = _dict_keys_at_name("menu_map")
    path_keys = _dict_keys_at_name("_menu_paths")
    if proc_keys is None or menu_keys is None or path_keys is None:
        report.add(section, "locate registration dicts", SKIP,
                   f"PROC={proc_keys is not None}, "
                   f"menu={menu_keys is not None}, "
                   f"paths={path_keys is not None}")
    else:
        missing_in_menu = proc_keys - menu_keys
        missing_in_paths = proc_keys - path_keys
        orphan_menu = menu_keys - proc_keys
        orphan_paths = path_keys - proc_keys
        report.add(section,
                   f"every _PROC_FEATURES key has menu_map entry "
                   f"({len(proc_keys)} procs)",
                   PASS if not missing_in_menu else FAIL,
                   f"missing={sorted(missing_in_menu)[:8]}"
                   if missing_in_menu else "")
        report.add(section,
                   "every _PROC_FEATURES key has _menu_paths entry",
                   PASS if not missing_in_paths else FAIL,
                   f"missing={sorted(missing_in_paths)[:8]}"
                   if missing_in_paths else "")
        report.add(section,
                   "no orphan menu_map keys (every menu has a feature)",
                   PASS if not orphan_menu else WARN,
                   f"orphan={sorted(orphan_menu)[:8]}"
                   if orphan_menu else "")
        report.add(section,
                   "no orphan _menu_paths keys",
                   PASS if not orphan_paths else WARN,
                   f"orphan={sorted(orphan_paths)[:8]}"
                   if orphan_paths else "")

    # ── 2. _apply_mask_mode arg count ─────────────────────────
    amm_calls = []  # list of (lineno, positional_count)
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Call)
                and isinstance(node.func, _ast.Name)
                and node.func.id == "_apply_mask_mode"):
            amm_calls.append((node.lineno, len(node.args)))
    bad = [(ln, n) for (ln, n) in amm_calls if n not in (5, 6)]
    report.add(section,
               f"_apply_mask_mode arity (5 or 6) across "
               f"{len(amm_calls)} call sites",
               PASS if not bad else FAIL,
               f"bad={bad[:5]}" if bad else "")

    # ── 3. Traceback discipline in _run_* handlers ────────────
    # We only care about the OUTER try/except of each handler \u2014
    # the catch-all at the tail of the method that surfaces an
    # unexpected failure back to the user. Nested try/except blocks
    # (Gtk callbacks, optional post-success degradation like
    # "MP4 export failed but GIF succeeded") are not the silent-
    # swallow regression class the plugin's outer handlers embody.
    missing_tb: list[str] = []
    for node in _ast.walk(tree):
        if not (isinstance(node, _ast.FunctionDef)
                and node.name.startswith("_run_")):
            continue
        # Find the outermost Try node whose body is the handler's
        # top-level work block. Traverse direct children only.
        outer_try = None
        for stmt in node.body:
            if isinstance(stmt, _ast.Try):
                outer_try = stmt
                # Don't break \u2014 some handlers wrap the whole
                # body in a single Try, but others have preflight
                # `try: import ...` blocks first. Pick the LAST
                # top-level Try \u2014 that's the work-wrapping one.
        if outer_try is None:
            continue
        for inner in outer_try.handlers:
            handler_src = _ast.get_source_segment(src, inner) or ""
            if "Gimp.message" not in handler_src:
                continue
            if "{e}" not in handler_src:
                continue
            if ("traceback.print_exc" in handler_src
                    or "traceback.format_exc" in handler_src):
                continue
            missing_tb.append(f"{node.name}:{inner.lineno}")
    report.add(section,
               "every _run_* Gimp.message-ing except prints traceback",
               PASS if not missing_tb else WARN,
               f"missing={missing_tb[:8]}" if missing_tb else "")

    # ── 4. _download_image assigned to path-typed variable ────
    # The helper returns bytes. A variable name like `*_path`,
    # `*_file`, or `path` implies a filesystem path and is the
    # footgun that crashed "Anything But".
    SUSPECT_NAMES = {"path", "mask_path", "img_path", "file_path",
                     "image_path", "ref_path", "output_path"}
    bad_assigns: list[str] = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Assign):
            continue
        # Accept single-target assigns only
        if len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not (isinstance(tgt, _ast.Name) and tgt.id in SUSPECT_NAMES):
            continue
        if not (isinstance(node.value, _ast.Call)
                and isinstance(node.value.func, _ast.Name)
                and node.value.func.id == "_download_image"):
            continue
        bad_assigns.append(f"{tgt.id} at line {node.lineno}")
    report.add(section,
               "_download_image results aren't stored as '*_path'",
               PASS if not bad_assigns else FAIL,
               f"bad={bad_assigns[:5]}" if bad_assigns else "")

    # ── 5. Upload-cache migration coverage ────────────────────
    # Count pre-cache idiom hits vs post-cache idiom hits. Baseline
    # is "most things migrated" \u2014 lots of pre-cache hits would
    # mean a new handler slipped in without using the cached helper.
    pre_cache_hits = src.count("_export_image_to_tmp(image)")
    cached_helper_hits = src.count("_export_and_upload_cached(")
    # The 8 intentional leaves (helper internals, manual send, etc.)
    # are documented; flag when it climbs sharply.
    LEAVE_BUDGET = 12  # fail-fast ceiling, not a strict count
    report.add(section,
               f"upload-cache migration "
               f"(cached={cached_helper_hits}, "
               f"legacy={pre_cache_hits})",
               PASS if pre_cache_hits <= LEAVE_BUDGET else WARN,
               f"{pre_cache_hits} legacy idioms remain "
               f"(budget {LEAVE_BUDGET}; helper leaves are expected)")

    # ── 6. Prefix discipline ──────────────────────────────────
    # Ensure sc_cache_ is used for cached uploads and gimp_ or
    # sc_nmauto_ are used for privacy-wipeable / auto-gen uploads.
    # A literal `sc_cache_` not followed by formatted hash would be
    # suspicious.
    bad_prefix: list[str] = []
    import re as _re
    for m in _re.finditer(r'"sc_cache_([^"]*)"', src):
        rest = m.group(1)
        # Normal case: "sc_cache_{fp}.png" or "sc_cache_{fingerprint}.png"
        if "{" in rest or rest.startswith("cache"):
            continue
        line = src[:m.start()].count("\n") + 1
        bad_prefix.append(f"line {line}: sc_cache_{rest!r}")
    report.add(section,
               "sc_cache_* literals use content-hash suffix",
               PASS if not bad_prefix else WARN,
               f"non-hash={bad_prefix[:5]}" if bad_prefix else "")

    report.add(section, "section complete", PASS,
               elapsed_ms=int((time.time() - t0) * 1000))


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

SECTIONS = {
    "endpoints":         test_guild_endpoints,
    "scaffolds":         test_scaffolds,
    "naming":            test_wizard_names,
    "build_fns":         test_build_functions,
    "manifest":          test_plugin_manifest,
    "video":             test_video_canon,
    "profiles":          test_model_prompt_profiles,
    "cross_interface":   test_cross_interface_backbone,
    # Post-audit (2026-04-20) — cover every surface shipped this week
    "presence_broker":   test_presence_broker,
    "blob_bus":          test_blob_bus,
    "error_extraction":  test_error_extraction,
    "events_schema":     test_events_schema,
    "st_routes":         test_sillytavern_routes,
    "guild_client":      test_guild_client,
    "cn_model_coverage": test_cn_model_coverage,
    "coverage_inventory": test_coverage_inventory,
    # Regression-guard layer (all offline) — pin the bug classes
    # chased over the recent sessions.
    "upload_cache":      test_upload_cache,
    "guards":            test_guards,
    "iclight_cn":        test_iclight_cn,
    "plugin_surface":    test_plugin_surface,
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
    ap.add_argument("--offline", action="store_true",
                     help="Run only sections that don't need a live Guild "
                          "(events_schema, coverage_inventory)")
    args = ap.parse_args()

    # Sections that don't contact the Guild — safe to run standalone.
    OFFLINE_SECTIONS = {"events_schema", "coverage_inventory",
                         "upload_cache", "guards", "iclight_cn",
                         "plugin_surface", "error_extraction"}

    selected = set(SECTIONS.keys())
    if args.only:
        selected = set(x.strip() for x in args.only.split(",") if x.strip())
    if args.skip:
        selected -= set(x.strip() for x in args.skip.split(",") if x.strip())
    if args.offline:
        selected &= OFFLINE_SECTIONS

    # Preflight — Guild must be reachable, unless every selected section
    # is offline. Coverage inventory + events schema don't need it.
    needs_guild = bool(selected - OFFLINE_SECTIONS)
    if needs_guild:
        sc, body = http_get("/api/llm_status")
        if sc != 200:
            print(f"Guild preflight failed at {GUILD_URL}/api/llm_status "
                  f"(HTTP {sc}: {body!r:.120})", file=sys.stderr)
            print("Hint: pass --offline to run just the sections that "
                  "don't need the Guild.", file=sys.stderr)
            return 2

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
