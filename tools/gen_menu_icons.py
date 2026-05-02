#!/usr/bin/env python3
"""
Spellcaster — Themed Menu Icons Generator
==========================================

Generates 9 category icons for the occult-themed top-level GIMP menus
via Spellcaster's OWN build_txt2img workflow (same canonical builder
the plugin uses at runtime — no hand-rolled JSON, no duplicated logic).

Each icon targets the menubar theme it represents:

  💥 Summon  — magical explosion conjuring energy
  🪆 Klein   — russian nesting matryoshka doll with floating "2"
  🎭 Masks   — ornate tribal ceremonial mask
  🕯 Sigils  — glowing runic pentagram
  ⚗ Alchemy  — bubbling alchemical flask with runes
  🔮 Scrying — crystal ball with swirling smoke
  🔗 Bridges — glowing magical chain links
  ⚡ Quick   — neon lightning bolt sigil
  🗝 Crypt   — antique skeleton key with runes

Output: plugins/gimp/comfyui-connector/assets/icons/menu_<name>.png
at 512x512 (downscaled to 64x64 at GIMP-icon-registration time).

Usage:
  python tools/gen_menu_icons.py                 # all 9, auto arch
  python tools/gen_menu_icons.py --only summon   # single icon
  python tools/gen_menu_icons.py --arch sdxl     # force arch
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

from spellcaster_core.workflows import build_txt2img
from spellcaster_core.architectures import get_arch


_NEG = (
    "text, letters, words, watermark, logo, signature, ui, interface, "
    "complex background, cluttered, multiple objects, photo border, "
    "frame, low quality, blurry, deformed"
)

# Each icon centers a distinctive magical emblem against a minimal dark
# vignette so GTK can render it cleanly at 48/64 px. Prompts lean on
# "centered icon" + "emblem" + "solid dark background" to keep output
# usable as a menu glyph without post-crop.
_ICONS: list[tuple[str, str]] = [
    ("summon",
     "a massive magical explosion of conjuration energy bursting "
     "outward, vibrant purple and cyan neon sparks radiating, "
     "centered emblem icon, solid black void background, symmetrical, "
     "volumetric light, glowing core, dynamic energy waves, "
     "cinematic, masterpiece"),
    ("klein",
     "an ornate russian matryoshka nesting doll, carved wood "
     "with glowing cyan runes, a luminous golden number 2 sigil "
     "floating above its head, centered emblem icon, solid black "
     "void background, symmetrical composition, mystical lighting"),
    ("masks",
     "an ornate tribal ceremonial mask with glowing magenta "
     "eyes and intricate carved patterns, bone and obsidian "
     "material, centered emblem icon, solid black void background, "
     "symmetrical, volumetric rim light, mystical"),
    ("sigils",
     "a glowing magical pentagram sigil etched in neon cyan on "
     "black stone, runic symbols at each point, centered emblem "
     "icon, solid black void background, symmetrical, ethereal glow, "
     "arcane geometry, masterpiece"),
    ("alchemy",
     "a round alchemical glass flask with bubbling iridescent "
     "purple potion inside, glowing runes etched on the glass, "
     "centered emblem icon, solid black void background, "
     "symmetrical, volumetric steam rising, mystical lighting"),
    ("scrying",
     "a polished obsidian crystal ball on an ornate stand, swirling "
     "purple and cyan nebula smoke visible inside, glowing runes "
     "around the base, centered emblem icon, solid black void "
     "background, symmetrical, ethereal"),
    ("bridges",
     "three interlinked chains of glowing neon magical energy "
     "forming a triangle, arcane runes etched on each link, "
     "centered emblem icon, solid black void background, "
     "symmetrical, ethereal cyan-magenta glow"),
    ("quick",
     "a single stylized neon lightning bolt sigil, electric purple "
     "core with cyan plasma edges, centered emblem icon, solid "
     "black void background, symmetrical, dynamic, arcane, "
     "masterpiece"),
    ("crypt",
     "an ornate antique skeleton key made of tarnished brass and "
     "black obsidian, glowing cyan runes carved along its shaft, "
     "centered emblem icon, solid black void background, "
     "symmetrical, mystical, masterpiece"),
]


_ARCH_PREFERENCE = ("flux2klein", "flux1dev", "sdxl", "illustrious", "sd15")


def _probe_arch(server: str) -> set[str]:
    try:
        with urllib.request.urlopen(
            f"{server.rstrip('/')}/object_info", timeout=6) as r:
            info = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return set()
    present: set[str] = set()
    for loader in ("CheckpointLoaderSimple", "UNETLoader",
                    "UnetLoaderGGUF"):
        meta = info.get(loader) or {}
        try:
            field = "ckpt_name" if "Check" in loader else "unet_name"
            ff = (meta.get("input", {}).get("required", {})
                      .get(field, [[]]))
            names = ff[0] if ff and isinstance(ff[0], list) else []
        except Exception:
            names = []
        for n in names:
            lo = str(n).lower()
            if "klein" in lo or "flux2" in lo or "flux-2" in lo:
                present.add("flux2klein")
            elif "flux1-dev" in lo or "flux-1-dev" in lo or "flux1dev" in lo:
                present.add("flux1dev")
            elif "xl" in lo or "sdxl" in lo:
                present.add("sdxl")
            elif "illustrious" in lo:
                present.add("illustrious")
            elif n.endswith((".safetensors", ".ckpt")):
                present.add("sd15")
    return present


def _pick_arch(server: str, requested: str | None) -> str:
    if requested:
        return requested
    present = _probe_arch(server)
    for c in _ARCH_PREFERENCE:
        if c in present:
            return c
    return "sdxl"


def _first_model(server: str, arch: str) -> str | None:
    try:
        with urllib.request.urlopen(
            f"{server.rstrip('/')}/object_info", timeout=6) as r:
            info = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    candidates: list[tuple[str, str]] = []
    for loader, field in (("CheckpointLoaderSimple", "ckpt_name"),
                           ("UNETLoader", "unet_name"),
                           ("UnetLoaderGGUF", "unet_name")):
        meta = info.get(loader) or {}
        try:
            ff = (meta.get("input", {}).get("required", {})
                      .get(field, [[]]))
            names = ff[0] if ff and isinstance(ff[0], list) else []
        except Exception:
            names = []
        for n in names:
            candidates.append((loader, str(n)))
    patterns = {"flux2klein": ("klein", "flux2", "flux-2"),
                "flux1dev": ("flux1-dev", "flux-1-dev", "flux1dev"),
                "sdxl": ("sdxl", "xl"),
                "illustrious": ("illustrious",),
                "sd15": (".safetensors",)}
    checks = patterns.get(arch, (arch,))
    for loader, n in candidates:
        if any(c in n.lower() for c in checks):
            return n
    for loader, n in candidates:
        if loader == "CheckpointLoaderSimple":
            return n
    return None


def _preset(arch_key: str, ckpt: str) -> dict:
    arch = get_arch(arch_key)
    if arch is None:
        raise RuntimeError(f"unknown arch {arch_key!r}")
    return {"arch": arch_key, "ckpt": ckpt,
            "width": 512, "height": 512,
            "steps": arch.default_steps, "cfg": arch.default_cfg,
            "denoise": 1.0, "sampler": arch.default_sampler,
            "scheduler": arch.default_scheduler,
            "loader": getattr(arch, "loader", "CheckpointLoaderSimple"),
            "clip_name1": "", "clip_name2": "", "vae_name": ""}


def _queue(server: str, wf: dict) -> str:
    body = json.dumps({"prompt": wf,
                       "client_id": f"sc-icons-{uuid.uuid4().hex[:8]}"}
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


def _wait(server: str, pid: str, timeout: float = 300.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=15) as r:
                hist = json.loads(r.read().decode("utf-8",
                                                   errors="replace"))
        except Exception:
            time.sleep(1.5); continue
        entry = hist.get(pid) if isinstance(hist, dict) else None
        if entry:
            outs = entry.get("outputs") or {}
            for _, o in outs.items():
                imgs = o.get("images") or []
                if imgs:
                    return [(i.get("filename"), i.get("subfolder", ""),
                             i.get("type", "output")) for i in imgs]
        time.sleep(1.5)
    raise TimeoutError(f"no output in {timeout:.0f}s")


def _download(server: str, fn: str, sf: str, ft: str) -> bytes:
    q = urllib.parse.urlencode({"filename": fn, "subfolder": sf,
                                  "type": ft})
    with urllib.request.urlopen(f"{server}/view?{q}", timeout=60) as r:
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
    ap.add_argument("--arch", default=None)
    ap.add_argument("--only", default=None,
                    help="single icon name (e.g. 'summon')")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args()

    server = (args.server or _server_from_config() or "").rstrip("/")
    if not server:
        print("ERROR: no server in config.json; pass --server")
        return 1
    arch = _pick_arch(server, args.arch)
    ckpt = _first_model(server, arch)
    if not ckpt:
        print(f"ERROR: no model found on {server} for arch {arch}")
        return 1
    preset = _preset(arch, ckpt)
    print(f"Server: {server}  Arch: {arch}  Model: {ckpt}")

    out_dir = (_ROOT / "plugins" / "gimp" / "comfyui-connector" /
               "assets" / "icons")
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = _ICONS
    if args.only:
        targets = [(n, p) for n, p in _ICONS if n == args.only]
        if not targets:
            print(f"ERROR: unknown --only {args.only!r}; "
                  f"choose from: {', '.join(n for n, _ in _ICONS)}")
            return 1

    t0_total = time.time()
    for i, (name, prompt) in enumerate(targets, 1):
        seed = args.seed if args.seed else (
            int.from_bytes(os.urandom(4), "big") & 0x7FFFFFFF)
        wf = build_txt2img(preset, prompt, _NEG, seed)
        print(f"[{i}/{len(targets)}] {name}  seed={seed}  "
              f"dispatching...")
        t0 = time.time()
        pid = _queue(server, wf)
        results = _wait(server, pid, timeout=args.timeout)
        if not results:
            print(f"  FAIL: no output for {name}")
            continue
        fn, sf, ft = results[0]
        blob = _download(server, fn, sf, ft)
        dst = out_dir / f"menu_{name}.png"
        dst.write_bytes(blob)
        print(f"  ok {len(blob):,} bytes -> {dst.relative_to(_ROOT)} "
              f"({time.time() - t0:.1f}s)")
    print(f"Done. Total: {time.time() - t0_total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
