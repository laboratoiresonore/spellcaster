#!/usr/bin/env python3
"""
Spellcaster — GIMP Splash Generator
====================================

Generates a new GIMP+Spellcaster splash screen by calling the SAME
canonical workflow builders the GIMP plugin uses internally. The
result is 1024x1024 (matches GIMP's native splash dimensions), saved
to BOTH plugin locations the force-repair flow reads from:

  * plugins/gimp/gimp_banner.png
  * plugins/gimp/comfyui-connector/gimp_banner.png

After it's written, the next `_reapply_appearance_assets()` call
(GIMP plugin boot, or Settings > Repair / Update Now, or the new
Restart button) will push the banner into GIMP's install dir so the
splash screen you see on next launch is the generated one.

USAGE
-----

    # Simplest — read server URL from the GIMP plugin's config.json
    python tools/gen_gimp_splash.py

    # Override server
    python tools/gen_gimp_splash.py --server http://192.168.x.x:8188

    # Pick a specific architecture (default auto-detects the fastest
    # SOTA photoreal arch the server has installed)
    python tools/gen_gimp_splash.py --arch flux2klein
    python tools/gen_gimp_splash.py --arch flux1dev
    python tools/gen_gimp_splash.py --arch sdxl

    # Custom prompt (overrides the built-in epic prompt)
    python tools/gen_gimp_splash.py --prompt "cyberpunk wizard with
    a holographic paintbrush, neon fractal cathedral, ..."

    # Seed control for iteration
    python tools/gen_gimp_splash.py --seed 42

    # Dry-run: print the workflow, don't dispatch
    python tools/gen_gimp_splash.py --dry-run

The script deliberately uses spellcaster_core.workflows.build_txt2img
(the SAME builder every in-plugin txt2img call goes through) — NOT a
hand-rolled workflow. That way we benefit from every quality boost
the plugin has acquired (PAG, SLG, CFG Zero Star, TeaCache, Sage
Attention, arch-specific samplers) without duplicating logic here.
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

# Resolve project root + make spellcaster_core importable.
_ROOT = Path(__file__).resolve().parent.parent
_PACK = _ROOT / "comfyui-spellcaster"
if _PACK.exists():
    sys.path.insert(0, str(_PACK))

try:
    from spellcaster_core.workflows import build_txt2img
    from spellcaster_core.architectures import get_arch
except Exception as e:
    print(f"ERROR: could not import spellcaster_core. Run from the "
          f"Spellcaster repo root.\n  {e}")
    sys.exit(2)


# ── Prompt ────────────────────────────────────────────────────────────

DEFAULT_PROMPT = (
    "epic cinematic portrait of an arcane wizard conjuring "
    "a glowing pixel-matrix spell, ornate brass steampunk paintbrush "
    "in one hand leaving trails of luminescent prismatic mana, "
    "intricately embroidered deep-purple robe with glowing rune-thread, "
    "sharp piercing eyes, stern determined expression, long silver beard "
    "catching rim light, GIMP wordmark subtly etched into the mana "
    "trails as floating golden runes reading SPELLCASTER, stage-lit by "
    "two warm rim lights and a cool cyan backlight, volumetric godrays "
    "through floating code particles, obsidian-and-gold baroque studio "
    "backdrop, 50mm portrait, shallow depth of field, sharp focus on "
    "face and hands, masterpiece, 8k detail, ultra-realistic skin "
    "texture, photographic composition"
)

DEFAULT_NEGATIVE = (
    "blurry, low quality, deformed, extra fingers, extra limbs, "
    "bad anatomy, watermark, text artefacts, signature, jpeg artefacts, "
    "tiling, low resolution, amateur, cartoon, anime, illustration, "
    "drawing"
)


# ── Architecture auto-detection ───────────────────────────────────────

#: Arch preference order. Flux 2 Klein is SOTA photoreal + 4-step fast;
#: Flux 1 Dev is the gold-standard fallback; SDXL the universal safety
#: net. Picked in order of (quality, availability).
_ARCH_PREFERENCE = ("flux2klein", "flux1dev", "chroma", "sdxl",
                    "illustrious", "sd15")


def _probe_arch_availability(server: str, timeout: float = 6.0) -> set[str]:
    """Hit /object_info and infer which archs are installed by checking
    for their loader classes + common model filenames."""
    try:
        with urllib.request.urlopen(
            f"{server.rstrip('/')}/object_info",
            timeout=timeout,
        ) as resp:
            info = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return set()
    loaders = {"CheckpointLoaderSimple", "UNETLoader", "UnetLoaderGGUF"}
    present: set[str] = set()
    for loader in loaders:
        meta = info.get(loader) or {}
        try:
            files_field = (meta.get("input", {})
                               .get("required", {})
                               .get(("ckpt_name" if "Checkpoint" in loader
                                     else "unet_name"), [[]]))
            names = files_field[0] if files_field and isinstance(
                files_field[0], list) else []
        except Exception:
            names = []
        for name in names:
            low = str(name).lower()
            if "klein" in low or "flux2" in low or "flux-2" in low:
                present.add("flux2klein")
            elif ("flux1-dev" in low or "flux-1-dev" in low
                  or "flux1dev" in low):
                present.add("flux1dev")
            elif "chroma" in low:
                present.add("chroma")
            elif "illustrious" in low:
                present.add("illustrious")
            elif "xl" in low or "sdxl" in low:
                present.add("sdxl")
            elif name.endswith((".safetensors", ".ckpt")):
                present.add("sd15")  # loose default for checkpoints
    return present


def _pick_arch(server: str, requested: str | None) -> str:
    if requested:
        return requested
    present = _probe_arch_availability(server)
    for cand in _ARCH_PREFERENCE:
        if cand in present:
            return cand
    return "sdxl"


# ── Server model/preset resolution ────────────────────────────────────

def _first_model_for_arch(server: str, arch: str,
                           timeout: float = 6.0) -> str | None:
    """Return the first server-side model filename matching ``arch``.

    We can't hardcode a specific ckpt because every install has
    different files. Instead we filter the server's model list by
    arch-identifying substrings and return the most promising match.
    """
    try:
        with urllib.request.urlopen(
            f"{server.rstrip('/')}/object_info",
            timeout=timeout,
        ) as resp:
            info = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None

    # Walk both checkpoint and UNET loaders.
    candidates: list[tuple[str, str]] = []
    for loader, field in (
        ("CheckpointLoaderSimple", "ckpt_name"),
        ("UNETLoader", "unet_name"),
        ("UnetLoaderGGUF", "unet_name"),
    ):
        meta = info.get(loader) or {}
        try:
            files_field = (meta.get("input", {})
                               .get("required", {})
                               .get(field, [[]]))
            names = files_field[0] if files_field and isinstance(
                files_field[0], list) else []
        except Exception:
            names = []
        for name in names:
            candidates.append((loader, str(name)))

    patterns = {
        "flux2klein": ("klein", "flux2", "flux-2", "flux_2"),
        "flux1dev":   ("flux1-dev", "flux-1-dev", "flux1dev", "flux.1"),
        "chroma":     ("chroma",),
        "sdxl":       ("sdxl", "xl"),
        "illustrious": ("illustrious",),
        "sd15":       (".safetensors", ".ckpt"),
        "zit":        ("z-image", "zit", "zimage"),
    }
    checks = patterns.get(arch, (arch,))
    for loader, name in candidates:
        low = name.lower()
        if any(c in low for c in checks):
            return name
    # No match — return whatever the first checkpoint is as a last resort.
    for loader, name in candidates:
        if loader == "CheckpointLoaderSimple":
            return name
    return None


def _build_preset(arch_key: str, ckpt: str) -> dict:
    """Minimal preset dict that build_txt2img will understand.

    The actual defaults (steps / cfg / sampler / scheduler / width /
    height) come from the ArchConfig — we just set what's needed."""
    arch = get_arch(arch_key)
    if arch is None:
        raise RuntimeError(f"unknown arch {arch_key!r}")
    w, h = 1024, 1024
    return {
        "arch":      arch_key,
        "ckpt":      ckpt,
        "width":     w,
        "height":    h,
        "steps":     arch.default_steps,
        "cfg":       arch.default_cfg,
        "denoise":   1.0,
        "sampler":   arch.default_sampler,
        "scheduler": arch.default_scheduler,
        "loader":    getattr(arch, "loader", "CheckpointLoaderSimple"),
        # Dual-CLIP archs like flux1dev auto-resolve — leaving blank
        # here is fine because the canonical builder handles defaults.
        "clip_name1": "", "clip_name2": "", "vae_name": "",
    }


# ── Dispatch ──────────────────────────────────────────────────────────

def _queue_workflow(server: str, workflow: dict) -> str:
    """POST to /prompt, return the prompt_id."""
    body = json.dumps({
        "prompt": workflow,
        "client_id": f"spellcaster-gen-splash-{uuid.uuid4().hex[:8]}",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{server.rstrip('/')}/prompt",
        data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    pid = data.get("prompt_id")
    if not pid:
        raise RuntimeError(f"ComfyUI /prompt did not return prompt_id: {data}")
    return pid


def _wait_for_result(server: str, prompt_id: str,
                     timeout: float = 600.0) -> list[tuple[str, str, str]]:
    """Poll /history/<prompt_id> until outputs appear or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"{server.rstrip('/')}/history/{prompt_id}",
                timeout=15) as r:
                hist = json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception:
            time.sleep(1.5); continue
        entry = hist.get(prompt_id) if isinstance(hist, dict) else None
        if entry:
            outs = entry.get("outputs") or {}
            for _node_id, out in outs.items():
                images = out.get("images") or []
                if images:
                    return [(img.get("filename"),
                             img.get("subfolder", ""),
                             img.get("type", "output")) for img in images]
        time.sleep(1.5)
    raise TimeoutError(
        f"ComfyUI didn't return outputs within {timeout:.0f}s")


def _download(server: str, filename: str, subfolder: str,
              ftype: str) -> bytes:
    q = urllib.parse.urlencode(
        {"filename": filename, "subfolder": subfolder, "type": ftype})
    with urllib.request.urlopen(
        f"{server.rstrip('/')}/view?{q}", timeout=60) as r:
        return r.read()


# ── Main ─────────────────────────────────────────────────────────────

def _server_from_config() -> str | None:
    """Read the GIMP plugin's config.json to pull the user's server URL.
    Same file the plugin itself reads, so this tool uses whatever the
    user has pointed GIMP at."""
    for candidate in (
        _ROOT / "plugins" / "gimp" / "comfyui-connector" / "config.json",
        Path(os.environ.get("APPDATA", "")) /
            "GIMP" / "3.2" / "plug-ins" / "comfyui-connector" / "config.json",
    ):
        try:
            if candidate.is_file():
                with candidate.open(encoding="utf-8") as f:
                    cfg = json.load(f)
                url = cfg.get("server_url")
                if url:
                    return url
        except Exception:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate a GIMP+Spellcaster splash via ComfyUI.")
    ap.add_argument("--server", default=None,
        help="ComfyUI server URL (defaults to plugin config.json)")
    ap.add_argument("--arch", default=None,
        help="Architecture key (flux2klein / flux1dev / sdxl / ...). "
             "Auto-detected if omitted.")
    ap.add_argument("--ckpt", default=None,
        help="Explicit model filename (overrides arch auto-pick)")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT,
        help="Positive prompt (overrides the default epic prompt)")
    ap.add_argument("--negative", default=DEFAULT_NEGATIVE,
        help="Negative prompt")
    ap.add_argument("--seed", type=int, default=0,
        help="Seed (0 = random)")
    ap.add_argument("--timeout", type=float, default=600.0,
        help="Dispatch timeout in seconds (default 600s)")
    ap.add_argument("--dry-run", action="store_true",
        help="Build + print the workflow without dispatching.")
    args = ap.parse_args()

    server = args.server or _server_from_config()
    if not server:
        print("ERROR: no --server given and couldn't find a "
              "server_url in the GIMP plugin's config.json.")
        return 1
    server = server.rstrip("/")

    arch = _pick_arch(server, args.arch)
    ckpt = args.ckpt or _first_model_for_arch(server, arch)
    if not ckpt:
        print(f"ERROR: server {server} has no model matching arch={arch!r}.")
        return 1

    preset = _build_preset(arch, ckpt)
    seed = args.seed if args.seed else (int.from_bytes(os.urandom(4), "big")
                                         & 0x7FFFFFFF)
    wf = build_txt2img(preset, args.prompt, args.negative, seed)

    print(f"Server:   {server}")
    print(f"Arch:     {arch}")
    print(f"Model:    {ckpt}")
    print(f"Seed:     {seed}")
    print(f"Workflow: {len(wf)} nodes")

    if args.dry_run:
        print(json.dumps(wf, indent=2))
        return 0

    print("Dispatching...")
    pid = _queue_workflow(server, wf)
    print(f"  prompt_id: {pid}")

    print("Waiting for result...")
    t0 = time.time()
    results = _wait_for_result(server, pid, timeout=args.timeout)
    print(f"  done in {time.time() - t0:.1f}s — {len(results)} output(s)")

    if not results:
        print("ERROR: no outputs returned")
        return 1

    # First output → splash.
    fn, sf, ft = results[0]
    blob = _download(server, fn, sf, ft)
    print(f"  downloaded {len(blob):,} bytes ({fn})")

    # Write to both plugin-dir locations the repair-flow re-applies
    # from. The force-repair / auto-update / Restart cycle will then
    # copy it into <GIMP install>/share/gimp/3.0/images/gimp-splash.png.
    targets = [
        _ROOT / "plugins" / "gimp" / "gimp_banner.png",
        _ROOT / "plugins" / "gimp" / "comfyui-connector" / "gimp_banner.png",
    ]
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(blob)
        print(f"  wrote {t.relative_to(_ROOT)}")

    print()
    print("Done. Next steps:")
    print("  1. git add plugins/gimp/gimp_banner.png "
          "plugins/gimp/comfyui-connector/gimp_banner.png")
    print("  2. git commit + push")
    print("  3. Restart GIMP (Settings > Repair / Update Now > "
          "Restart GIMP) — the re-apply flow pushes the new banner "
          "into GIMP's install dir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
