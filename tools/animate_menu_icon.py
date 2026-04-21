#!/usr/bin/env python3
"""
Spellcaster — Animate a Menu Icon via LTX I2V
==============================================

Takes one of the generated menu icons (e.g. menu_summon.png) and
runs it through Spellcaster's CANONICAL LTX 2.3 I2V builder to
produce a short looping MP4 suitable for splash/header use in
dialogs like the Bridges Panel.

Distilled mode (8 steps) + pingpong=True keeps the clip small and
seamless. Uses the same detect_ltx_preset + build_ltx_video the
GIMP plugin uses.

Usage:
  python tools/animate_menu_icon.py --icon summon
  python tools/animate_menu_icon.py --icon summon --frames 33 --fps 16
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PACK = _ROOT / "comfyui-spellcaster"
if _PACK.exists():
    sys.path.insert(0, str(_PACK))

from spellcaster_core.workflows import build_ltx_video
from spellcaster_core.video_presets import (
    detect_ltx_preset, ltx_mode_kwargs)


_PROMPTS: dict[str, str] = {
    "summon": ("a massive explosion of magical conjuration energy "
                "pulsing and radiating outward, the neon sparks drifting "
                "and crackling, subtle rotation, looping mystical energy, "
                "cinematic volumetric light"),
    "klein":  ("the wooden voodoo doll idly breathing, the glowing cyan "
                "runes on its surface pulsing softly, the golden number "
                "2 above slowly rotating, mystical atmosphere"),
    "masks":  ("the tribal voodoo mask slowly tilting, the glowing "
                "magenta eyes pulsing and flickering, ambient mystical "
                "smoke drifting past, cinematic"),
    "sigils": ("the runic pentagram slowly rotating, the cyan runes "
                "flickering and pulsing with arcane energy, ethereal "
                "glow breathing in and out, mystical"),
    "alchemy": ("the purple potion bubbling and swirling inside the "
                 "flask, volumetric steam rising and drifting, the "
                 "glowing runes pulsing softly, mystical lighting"),
    "scrying": ("the purple and cyan nebula smoke swirling inside the "
                 "crystal ball, arcane runes around the base pulsing, "
                 "mystical ambient glow"),
    "bridges": ("the interlinked neon chains slowly rotating, the "
                 "magenta and cyan energy flowing along the links, "
                 "arcane runes pulsing, ethereal mystical glow"),
    "quick":  ("the plasma lightning bolt crackling and sparking, "
                "electric energy arcing outward, neon plasma tendrils "
                "pulsing, dynamic magical energy"),
    "crypt":  ("the skeleton key slowly rotating, the cyan runes on "
                "the shaft pulsing with arcane light, tarnished brass "
                "catching mystical rim light, mysterious"),
}


def _upload_image(server: str, path: Path) -> str:
    """Upload via /upload/image. Returns the filename on the server."""
    boundary = f"----sc{uuid.uuid4().hex[:12]}"
    data = path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; '
        f'filename="{path.name}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{server}/upload/image", data=body, method="POST",
        headers={"Content-Type":
                 f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode("utf-8", errors="replace"))
    return j.get("name", path.name)


def _queue(server: str, wf: dict) -> str:
    body = json.dumps({"prompt": wf,
                       "client_id": f"sc-animate-{uuid.uuid4().hex[:8]}"}
                      ).encode("utf-8")
    req = urllib.request.Request(f"{server}/prompt", data=body,
                                   method="POST",
                                   headers={"Content-Type":
                                            "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    pid = data.get("prompt_id")
    if not pid:
        raise RuntimeError(f"no prompt_id: {data}")
    return pid


def _wait(server: str, pid: str, timeout: float = 600.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=15) as r:
                hist = json.loads(r.read().decode("utf-8",
                                                   errors="replace"))
        except Exception:
            time.sleep(2); continue
        entry = hist.get(pid) if isinstance(hist, dict) else None
        if entry:
            outs = entry.get("outputs") or {}
            found = []
            for _, o in outs.items():
                for key in ("videos", "gifs", "images"):
                    for item in (o.get(key) or []):
                        found.append((
                            item.get("filename"),
                            item.get("subfolder", ""),
                            item.get("type", "output")))
            if found:
                return found
        time.sleep(2)
    raise TimeoutError(f"no output in {timeout:.0f}s")


def _download(server: str, fn: str, sf: str, ft: str) -> bytes:
    q = urllib.parse.urlencode({"filename": fn, "subfolder": sf,
                                  "type": ft})
    with urllib.request.urlopen(f"{server}/view?{q}", timeout=120) as r:
        return r.read()


def _server_from_config() -> str | None:
    for c in (_ROOT / "plugins" / "gimp" / "comfyui-connector" /
               "config.json",
               Path(os.environ.get("APPDATA", "")) / "GIMP" / "3.2" /
               "plug-ins" / "comfyui-connector" / "config.json"):
        try:
            if c.is_file():
                with c.open(encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("server_url"):
                    return cfg["server_url"]
        except Exception:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=None)
    ap.add_argument("--icon", default="summon",
                    help=f"choose from: {', '.join(_PROMPTS)}")
    ap.add_argument("--frames", type=int, default=25)
    ap.add_argument("--fps", type=int, default=16)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args()

    server = (args.server or _server_from_config() or "").rstrip("/")
    if not server:
        print("ERROR: no server; pass --server")
        return 1

    if args.icon not in _PROMPTS:
        print(f"ERROR: unknown icon {args.icon!r}; "
              f"pick from: {', '.join(_PROMPTS)}")
        return 1

    icons_dir = (_ROOT / "plugins" / "gimp" / "comfyui-connector" /
                  "assets" / "icons")
    src = icons_dir / f"menu_{args.icon}.png"
    if not src.is_file():
        print(f"ERROR: {src} missing; run tools/gen_menu_icons.py first")
        return 1

    print(f"Server: {server}")
    print(f"Source: {src.relative_to(_ROOT)}")
    print("Probing LTX preset...")
    try:
        preset = detect_ltx_preset(server)
    except Exception as e:
        print(f"ERROR: no LTX preset on {server}: {e}")
        return 1
    print(f"  preset: {preset.get('unet_name') or preset.get('ckpt')}")

    print("Uploading source frame...")
    up_name = _upload_image(server, src)
    print(f"  uploaded as: {up_name}")

    seed = args.seed if args.seed else (
        int.from_bytes(os.urandom(4), "big") & 0x7FFFFFFF)
    # Distilled 8-step I2V + pingpong for seamless loop.
    mode_kw = ltx_mode_kwargs("i2v")
    wf = build_ltx_video(
        preset,
        _PROMPTS[args.icon],
        seed,
        width=512, height=512,
        num_frames=args.frames,
        fps=args.fps,
        pingpong=True,
        image_filename=up_name,
        i2v_strength=0.75,
        **mode_kw,
    )
    print(f"Workflow: {len(wf)} nodes  seed={seed}  "
          f"frames={args.frames}  fps={args.fps}")
    print("Dispatching LTX I2V...")
    t0 = time.time()
    pid = _queue(server, wf)
    print(f"  prompt_id: {pid}")
    results = _wait(server, pid, timeout=args.timeout)
    if not results:
        print("ERROR: no output")
        return 1

    out_dir = icons_dir / "animated"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for fn, sf, ft in results:
        if not fn:
            continue
        blob = _download(server, fn, sf, ft)
        ext = Path(fn).suffix or ".mp4"
        dst = out_dir / f"menu_{args.icon}{ext}"
        dst.write_bytes(blob)
        saved.append(dst)
        print(f"  saved {len(blob):,} bytes -> "
              f"{dst.relative_to(_ROOT)}")

    print(f"Done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
