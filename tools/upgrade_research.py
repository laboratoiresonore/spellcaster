#!/usr/bin/env python3
"""Upgrade-research targets — feed for the every-48h ecosystem digest.

Every 48 hours the cloud-side Ecosystem Digest routine (see the
scheduled prompt in the operator's Claude Code account) sweeps the
upgrade-opportunity surface: which registered architectures have new
weights on Hugging Face, which sibling packs Kijai / Comfy-Org have
shipped, which video models have a new release-of-the-week. Prior
digest runs kept noting this script was missing and silently
degrading to open-ended web search; this file is the minimal contract
those runs asked for.

What it does
------------
Read the canonical architecture registry
(`comfyui-spellcaster/spellcaster_core/architectures.py`) and emit a
deterministic list of research targets — one per registered arch —
with:

  * arch key + `registered` flag + `scene_group`
  * Hugging Face repo hints (owner/name patterns the family typically
    ships under, based on what already runs in this stack)
  * candidate web-search queries an LLM agent can plug straight into
    WebSearch (versioned by the current month so year-old blog posts
    rank lower)

Nothing here talks to the network — that stays the caller's job — so
this script is fine to run in CI, on the dev host, and in the
Anthropic cloud sandbox alike. The point is to give the digest agent
a stable, checked-in seed of what to research instead of a fresh
brain-dump each time.

Usage
-----

    # Human-readable (default):
    python tools/upgrade_research.py

    # Machine-readable JSON, for the digest agent to consume:
    python tools/upgrade_research.py --json

    # Restrict to one scene group (image / video / sdxl / …):
    python tools/upgrade_research.py --group video

Contract for the digest agent
-----------------------------
The `targets` list in the JSON output IS the checklist. Each entry
has an `arch`, a `scene_group`, an `hf_hints` list (partial owner or
name patterns to search HF with) and a `web_queries` list (each an
already-versioned WebSearch string). The agent should run each
`web_queries[0]` first, cache the finding, and only dig deeper on
archs where the shallow query shows movement in the current or
previous month.

The script has no side effects and no external deps beyond the Python
stdlib and the repo's own `spellcaster_core.architectures` module.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Canonical registry lives under comfyui-spellcaster/. Prefer that over
# the plugins/gimp mirror so a stale mirror can't skew research targets.
CANON_CORE = REPO / "comfyui-spellcaster"
if str(CANON_CORE) not in sys.path:
    sys.path.insert(0, str(CANON_CORE))

try:
    from spellcaster_core.architectures import ARCHITECTURES, get_arch  # type: ignore
except Exception as exc:  # pragma: no cover — surfaces a clear error to the caller
    print(f"[upgrade_research] failed to import spellcaster_core.architectures: {exc}",
          file=sys.stderr)
    sys.exit(2)


# Per-arch upstream hints. Keys must match ARCHITECTURES keys. Missing
# keys degrade to a generic search string derived from the arch key —
# safe, just less precise. Add a new arch to this table whenever a new
# `_reg(...)` lands so digests get a targeted query for it.
#
# `hf_hints` are HF search fragments (owner or model prefix), not
# full URLs. The digest agent expands them via the Hugging-Face MCP.
# `web_queries` are already-versioned WebSearch inputs; put the most
# discriminating one first — the agent skims that before deciding to
# spend more of its ~25-call budget on the arch.
UPSTREAM_HINTS: dict[str, dict[str, list[str]]] = {
    # Image — SD ancestry
    "sd15":         {"hf_hints": ["runwayml/stable-diffusion-v1-5", "stable-diffusion-v1-5"]},
    "sdxl":         {"hf_hints": ["stabilityai/stable-diffusion-xl", "SG161222", "RunDiffusion"]},
    "sdxl_turbo":   {"hf_hints": ["stabilityai/sdxl-turbo", "ByteDance/SDXL-Lightning", "latent-consistency"]},
    "illustrious":  {"hf_hints": ["OnomaAIResearch/Illustrious-XL", "illustrious"]},
    "pony":         {"hf_hints": ["AstraliteHeart/pony-diffusion", "Pony"]},
    "playground":   {"hf_hints": ["playgroundai/playground-v2", "playgroundai/playground-v3"]},
    "zit":          {"hf_hints": ["Alpha-VLLM/Lumina-Image", "z_image_turbo", "zit"]},
    # DiT stubs
    "sd3":          {"hf_hints": ["stabilityai/stable-diffusion-3", "stabilityai/stable-diffusion-3.5"]},
    "sd3_turbo":    {"hf_hints": ["stabilityai/stable-diffusion-3.5-large-turbo"]},
    "hunyuan_dit":  {"hf_hints": ["Tencent-Hunyuan/HunyuanDiT"]},
    "pixart":       {"hf_hints": ["PixArt-alpha", "PixArt-Sigma"]},
    "auraflow":     {"hf_hints": ["fal/AuraFlow"]},
    "kolors":       {"hf_hints": ["Kwai-Kolors/Kolors"]},
    "lumina2":      {"hf_hints": ["Alpha-VLLM/Lumina-Image-2.0"]},
    # Flux / Chroma family
    "flux1dev":     {"hf_hints": ["black-forest-labs/FLUX.1-dev", "FLUX.1"]},
    "chroma":       {"hf_hints": ["lodestones/Chroma"]},
    "flux2klein":   {"hf_hints": ["black-forest-labs/FLUX.2-klein", "kaleidoscope"]},
    "flux_kontext": {"hf_hints": ["black-forest-labs/FLUX.1-Kontext", "kontext"]},
    # Video / motion
    "wan":          {"hf_hints": ["Wan-AI/Wan2.2", "Wan-AI/Wan2.1", "Kijai/WanVideo_comfy"]},
    "ltx":          {"hf_hints": ["Lightricks/LTX-Video"]},
    "seedvr":       {"hf_hints": ["ByteDance-Seed/SeedVR2", "SeedVR"]},
    "cogvideo":     {"hf_hints": ["THUDM/CogVideoX", "Kijai/CogVideoX_comfy"]},
    "framepack":    {"hf_hints": ["lllyasviel/FramePack", "Kijai/FramePackWrapper"]},
    "hunyuan_video":{"hf_hints": ["tencent/HunyuanVideo", "Kijai/HunyuanVideoWrapper"]},
    "mochi":        {"hf_hints": ["genmo/mochi-1-preview", "Kijai/MochiWrapper"]},
    # 3D
    "hunyuan_3d":   {"hf_hints": ["tencent/Hunyuan3D-2", "tencent/Hunyuan3D-2.1"]},
    # Restoration
    "supir":        {"hf_hints": ["camenduru/SUPIR", "Kijai/SUPIR_pruned"]},
}


def _current_month_tag(today: _dt.date | None = None) -> str:
    d = today or _dt.date.today()
    return d.strftime("%Y-%m")


def _default_web_queries(arch_key: str, month: str) -> list[str]:
    """Fallback query template for archs the hint table doesn't customise."""
    return [
        f"{arch_key} ComfyUI new release {month}",
        f"{arch_key} model update Hugging Face {month}",
    ]


def _web_queries_for(arch_key: str, month: str) -> list[str]:
    """Produce discriminating queries for an arch, versioned by month."""
    key_low = arch_key.lower()
    # Family-specific patterns land here. Keep them short — the LLM
    # agent will refine after seeing the first hit page.
    if key_low.startswith("wan"):
        return [
            f"Wan2.2 vs Wan2.5 release notes {month}",
            f"Kijai WanVideoWrapper changelog {month}",
        ]
    if key_low == "seedvr":
        return [
            f"SeedVR2 upscale ComfyUI release {month}",
            f"ByteDance SeedVR benchmark {month}",
        ]
    if key_low == "supir":
        return [
            f"SUPIR restoration ComfyUI update {month}",
            f"SUPIR vs SeedVR2 image restoration comparison {month}",
        ]
    if key_low.startswith("flux"):
        return [
            f"FLUX new release Black Forest Labs {month}",
            f"FLUX Kontext ComfyUI workflow update {month}",
        ]
    if key_low == "chroma":
        return [f"Chroma diffusion model release {month}"]
    if key_low == "hunyuan_video":
        return [f"HunyuanVideo weights update Tencent {month}"]
    if key_low == "hunyuan_3d":
        return [f"Hunyuan3D 2.1 vs 2.5 release {month}"]
    if key_low == "cogvideo":
        return [f"CogVideoX 1.5 release {month}"]
    if key_low == "mochi":
        return [f"Mochi-1 Genmo model update {month}"]
    if key_low == "framepack":
        return [f"FramePack low VRAM I2V release {month}"]
    if key_low == "ltx":
        return [f"LTX-Video Lightricks release notes {month}"]
    if key_low == "lumina2":
        return [f"Lumina-Image 2.0 release ComfyUI {month}"]
    if key_low.startswith("sd3"):
        return [f"Stable Diffusion 3.5 medium large release {month}"]
    if key_low == "sdxl":
        return [f"SDXL finetune notable release {month}"]
    if key_low == "sdxl_turbo":
        return [f"SDXL Turbo Lightning Hyper release {month}"]
    if key_low == "illustrious":
        return [f"Illustrious XL new version {month}"]
    if key_low == "pony":
        return [f"Pony Diffusion v7 release {month}"]
    if key_low == "playground":
        return [f"Playground v3 image model release {month}"]
    if key_low == "zit":
        return [f"Z-Image Turbo release ComfyUI {month}"]
    if key_low == "kolors":
        return [f"Kolors 2 release Kwai {month}"]
    if key_low == "pixart":
        return [f"PixArt-Sigma update {month}"]
    if key_low == "auraflow":
        return [f"AuraFlow v3 fal release {month}"]
    return _default_web_queries(arch_key, month)


def build_targets(scene_group: str | None = None,
                  today: _dt.date | None = None) -> list[dict]:
    """Return the sorted list of research targets."""
    month = _current_month_tag(today)
    out: list[dict] = []
    for key in sorted(ARCHITECTURES.keys()):
        arch = ARCHITECTURES[key]
        if scene_group and getattr(arch, "scene_group", None) != scene_group:
            continue
        hints = UPSTREAM_HINTS.get(key, {}).get("hf_hints", [])
        out.append({
            "arch": key,
            "scene_group": getattr(arch, "scene_group", None),
            "registered": bool(getattr(arch, "registered", True)),
            "supported_methods": list(getattr(arch, "supported_methods", ()) or ()),
            "default_steps": getattr(arch, "default_steps", None),
            "default_cfg": getattr(arch, "default_cfg", None),
            "hf_hints": hints,
            "web_queries": _web_queries_for(key, month),
        })
    return out


def _print_markdown(targets: list[dict], month: str) -> None:
    print(f"# Upgrade-research targets — {month}\n")
    print(f"Total archs: **{len(targets)}**  ·  ",
          f"registered: **{sum(1 for t in targets if t['registered'])}**  ·  ",
          f"stubs: **{sum(1 for t in targets if not t['registered'])}**\n")
    by_group: dict[str, list[dict]] = {}
    for t in targets:
        by_group.setdefault(t["scene_group"] or "unknown", []).append(t)
    for group in sorted(by_group.keys()):
        print(f"## scene_group: `{group}`\n")
        for t in by_group[group]:
            flag = "" if t["registered"] else " _(stub)_"
            print(f"### `{t['arch']}`{flag}")
            if t["hf_hints"]:
                print("- **HF hints:** " + ", ".join(f"`{h}`" for h in t["hf_hints"]))
            print("- **Web queries:**")
            for q in t["web_queries"]:
                print(f"  - `{q}`")
            print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit upgrade-research targets for the ecosystem digest routine.")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of markdown.")
    ap.add_argument("--group", default=None, help="Restrict to one scene_group (image / video / sdxl / …).")
    args = ap.parse_args()

    targets = build_targets(scene_group=args.group)
    if args.json:
        json.dump({
            "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "month_tag": _current_month_tag(),
            "arch_count": len(targets),
            "targets": targets,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_markdown(targets, _current_month_tag())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
