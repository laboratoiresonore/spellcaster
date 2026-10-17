#!/usr/bin/env python
"""Lane6 leftover (P-031): real-run smoke for FramePack and Wan2.2 block-swap (T2V) on ComfyUI.

ONE COMMAND:
    python scripts/lane6_framepack_blockswap_smoke.py --which both --run
Offline-safe check first (no queueing, only builds the graphs and validates every class_type + loader value
against the live /object_info):
    python scripts/lane6_framepack_blockswap_smoke.py --which both
Base URL: --url, else $COMFY_URL, else http://127.0.0.1:8188.
Exit 0 = every requested workflow built+validated (and, with --run, produced an output file).
Exit 2 = built but a loader value is missing on the server (prints which). Exit 1 = run failed / timeout.
Tiny settings on purpose (proof of life, not quality): wan 480x272x17f 4 steps, framepack 1s @ 384.
"""
import argparse, io, json, os, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "comfyui-spellcaster"))
from spellcaster_core import workflows as W  # noqa: E402
from scaffold.comfyui_runner import ComfyUIRunner  # noqa: E402

WAN = dict(wan_model="wan22-t2v-a14b/wan2.2_t2v_low_noise_14B_fp8_e4m3fn.safetensors",
           t5_model="umt5-xxl-enc-bf16.safetensors",
           vae_model="Wan2_1_VAE_bf16.safetensors")
FP_MODEL = "FramePackI2V_HY_bf16.safetensors"


def oi(base, cls):
    with urllib.request.urlopen(f"{base}/object_info/{cls}", timeout=30) as r:
        return json.load(r).get(cls)


def validate(base, wf, skip=()):
    """Every class_type exists; every literal string input that is a combo on the server is a legal option."""
    missing = []
    cache = {}
    for nid, node in wf.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        ct = node["class_type"]
        if ct not in cache:
            cache[ct] = oi(base, ct)
        info = cache[ct]
        if not info:
            missing.append(f"node {nid}: class_type {ct} not installed")
            continue
        spec = {**info["input"].get("required", {}), **info["input"].get("optional", {})}
        for k, v in node.get("inputs", {}).items():
            if (ct, k) in skip:
                continue
            if isinstance(v, str) and k in spec and isinstance(spec[k][0], list) and v not in spec[k][0]:
                missing.append(f"node {nid} {ct}.{k}={v!r} not in server options")
    return missing


def png_bytes():
    from PIL import Image
    im = Image.new("RGB", (384, 384), (90, 120, 160))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"))
    ap.add_argument("--which", choices=["framepack", "wan_blockswap_t2v", "both"], default="both")
    ap.add_argument("--run", action="store_true", help="queue on the server")
    ap.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args()
    runner = ComfyUIRunner(a.url, timeout=a.timeout)
    if not runner.is_available():
        print(f"FAIL: {a.url} unreachable"); return 1
    jobs = {}
    if a.which in ("wan_blockswap_t2v", "both"):
        jobs["wan_blockswap_t2v"] = lambda: W.build_wan_video_blockswap_t2v(
            prompt_text="a paper boat on a calm pond, soft light", negative_text="blurry", seed=7,
            width=480, height=272, length=17, steps=4, blocks_to_swap=30, **WAN)
    if a.which in ("framepack", "both"):
        def fp():
            name = runner.upload_image(png_bytes(), "lane6_fp_in.png").get("name", "lane6_fp_in.png") if a.run else "lane6_fp_in.png"
            return W.build_framepack_video(name, "slow gentle motion", "", 7, model_name=FP_MODEL, llama_clip_name="llava_llama3_fp8_scaled.safetensors",
                                           clip_l_name="clip_l.safetensors", vae_name="hunyuan_video_vae_bf16.safetensors",
                                           clip_vision_name="sigclip_vision_patch14_384.safetensors",
                                           base_resolution=384, total_second_length=1.0, fps=24, steps=8)
        jobs["framepack"] = fp
    rc = 0
    for name, mk in jobs.items():
        wf = mk()
        bad = validate(a.url, wf, skip=() if a.run else (('LoadImage', 'image'),))
        print(f"[{name}] nodes={len(wf)} validate={'OK' if not bad else 'MISSING'}")
        for b in bad:
            print("   ", b)
        if bad:
            rc = max(rc, 2); continue
        if a.run:
            t = time.time()
            res = runner.run_raw(wf) if hasattr(runner, "run_raw") else runner.run(wf)
            ok = bool(res)
            print(f"[{name}] run {'OK' if ok else 'FAIL'} in {time.time()-t:.0f}s result={str(res)[:300]}")
            if not ok:
                rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
