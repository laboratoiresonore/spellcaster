#!/usr/bin/env python3
"""Audit on-disk ComfyUI weights against the arch registry.

Filed as a Tier-1 follow-up by the 2026-10-16 ecosystem digest. Context:
when fleet downloads from the Tier-3 local-action-queue land
(Flux-3-Klein, LTX-2.5, Qwen-Image-2.1, Krea 2 …) the older superseded
weights on ``D:\\LLM\\ComfyUI\\models`` need to be flagged for
retirement. Rather than diff that by hand, this tool reads
``architectures.py`` + walks ``ComfyUI/models/*`` and prints three
sections:

    REDUNDANT   — a registered arch has more than one candidate weight
                  on disk. Human picks one and retires the rest.
    ORPHANED    — weights that match NO registered arch. Candidates for
                  moving to a quarantine directory before deletion.
    MISSING     — a registered arch declares a canonical ``clip_name`` /
                  ``vae_name`` in its ``extra`` dict but that exact path
                  is absent from disk. Coverage gap or stale extra dict.

Operation is read-only — the tool never deletes or moves anything. The
output is a report; retirement is a separate manual (or Hermes-driven)
step.

Cloud sandbox note
------------------
The spellcaster cloud sandbox has no access to the fleet's model drives,
so running this from the cloud without ``--dry-run`` will typically find
no root and exit cleanly with an explanatory message. Run with
``--dry-run`` to exercise the registry-load + report-shape paths.

Resolution of ``--models-root``:
  1. explicit ``--models-root`` argument
  2. ``COMFYUI_MODELS_DIR`` environment variable
  3. ``D:\\LLM\\ComfyUI\\models`` on Windows
  4. ``~/ComfyUI/models`` on Linux/macOS
  5. refuse to walk if none exist (exit 2, with a message)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Make `spellcaster_core` importable without a src-install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CORE_PARENT = _REPO_ROOT / "comfyui-spellcaster"
if str(_CORE_PARENT) not in sys.path:
    sys.path.insert(0, str(_CORE_PARENT))

from spellcaster_core.architectures import ARCHITECTURES  # noqa: E402

# File extensions this tool treats as "weights candidates" to classify.
# Everything else in the models tree (JSON configs, text, images) is
# ignored.
_WEIGHT_EXTS = frozenset({
    ".safetensors", ".sft", ".ckpt", ".pt", ".pth",
    ".bin", ".gguf", ".onnx",
})

# Arch-keyword table — the substrings we look for in a filename to
# attribute it to a registered arch. Lowercased, hyphen/underscore
# treated as equivalent. Keys MUST be arch ids present in
# ``ARCHITECTURES``; the audit skips keys that aren't.
#
# Keep this close to the ``_HF_ARCH_QUERIES`` map in
# ``tools/upgrade_research.py`` — they serve the same intent (map a
# string to an arch) but this one indexes filenames instead of HF repo
# ids, so the keywords are slightly different (e.g. "fp8", "nvfp4"
# suffixes don't belong here).
_ARCH_FILENAME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sd15": ("sd15", "sd_1_5", "stable-diffusion-v1-5", "stable_diffusion_1_5"),
    "sdxl": ("sdxl", "sd_xl", "stable-diffusion-xl"),
    "sdxl_turbo": ("sdxl-turbo", "sd-turbo", "sdxl_turbo"),
    "illustrious": ("illustrious", "noobai", "wai-illustrious"),
    "pony": ("pony", "ponydiffusion"),
    "playground": ("playground-v2", "playgroundv2", "playground_v2"),
    "zit": ("z-image", "z_image", "zimage"),
    "chroma": ("chroma",),
    "flux1dev": ("flux.1-dev", "flux-1-dev", "flux1-dev", "flux1dev"),
    "flux_kontext": ("flux-kontext", "flux_kontext", "flux.1-kontext"),
    "flux2klein": ("flux.2-klein", "flux2-klein", "flux_2_klein"),
    "flux2dev": ("flux.2-dev", "flux2-dev", "flux_2_dev"),
    "flux3klein": ("flux.3-klein", "flux-3-klein", "flux3-klein", "flux-3-image-klein"),
    "krea2": ("krea-2", "krea2", "krea-edit"),
    "qwen_image": ("qwen-image", "qwen_image", "qwen-image-edit"),
    "wan": ("wan-2", "wan2", "wan_2"),
    "ltx": ("ltx-video", "ltxv", "ltx-2", "ltx2"),
    "seedvr": ("seedvr", "seed-vr"),
    "cogvideo": ("cogvideo", "cogvideox"),
    "framepack": ("framepack", "frame-pack"),
    "hunyuan_video": ("hunyuanvideo", "hunyuan-video", "hunyuan_video"),
    "hunyuan_3d": ("hunyuan3d", "hunyuan-3d", "hunyuan_3d"),
    "mochi": ("mochi",),
    "minimax_h3": ("minimax-h3", "minimax_h3", "minimax"),
    "skyreels": ("skyreels", "sky-reels"),
    "longcat": ("longcat", "long-cat"),
    "lumina2": ("lumina-image-2", "lumina2", "lumina-2"),
    "supir": ("supir", "sup-ir"),
    "aurasr": ("aurasr", "aura-sr"),
    "sd3": ("stable-diffusion-3", "sd3"),
    "sd3_turbo": ("sd3-turbo", "sd3_turbo"),
    "hunyuan_dit": ("hunyuan-dit", "hunyuandit"),
    "pixart": ("pixart-sigma", "pixart-alpha", "pixart"),
    "auraflow": ("auraflow",),
    "kolors": ("kolors",),
}


def _norm(s: str) -> str:
    """Lowercase + collapse `-`/`_` to a single `_` for keyword probing."""
    return re.sub(r"[-_]+", "_", s.lower())


def _attribute_file(path: Path) -> str | None:
    """Return the arch id a filename most likely belongs to, or None.

    Precedence:
      1. an exact match on a registered arch's declared ``clip_name`` /
         ``vae_name`` from ``extra`` (strongest signal — the registry is
         the ground truth)
      2. a keyword match against ``_ARCH_FILENAME_KEYWORDS``
      3. None (treated as orphaned)
    """
    name = path.name
    name_norm = _norm(name)
    # Pass 1 — registry's own canonical filenames.
    for arch_id, arch in ARCHITECTURES.items():
        extra = getattr(arch, "extra", None) or {}
        for key in ("clip_name", "clip_name1", "clip_name2",
                    "vae_name", "audio_vae_name"):
            canonical = extra.get(key)
            if isinstance(canonical, str) and canonical:
                # strip any subfolder prefix in the extra dict —
                # ComfyUI reads "foo/bar.safetensors" relative to a
                # category root, so basename comparison is correct.
                if Path(canonical).name.lower() == name.lower():
                    return arch_id
        for alt in extra.get("clip_fallbacks", ()) or ():
            if isinstance(alt, str) and Path(alt).name.lower() == name.lower():
                return arch_id
    # Pass 2 — keyword probe. In addition to the explicit keyword list
    # we also probe the arch_id itself (normalized) so filenames like
    # ``flux3klein-fp8.safetensors`` — bare arch id, no separator — are
    # attributed instead of orphaned.
    for arch_id, keywords in _ARCH_FILENAME_KEYWORDS.items():
        if arch_id not in ARCHITECTURES:
            continue  # registry drift — skip gracefully
        probes = (arch_id,) + tuple(keywords)
        for kw in probes:
            if _norm(kw) in name_norm:
                return arch_id
    return None


def _default_root() -> Path | None:
    env = os.environ.get("COMFYUI_MODELS_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        p = Path(r"D:\LLM\ComfyUI\models")
        return p if p.exists() else None
    p = Path.home() / "ComfyUI" / "models"
    return p if p.exists() else None


def audit(models_root: Path) -> dict:
    """Walk ``models_root`` and classify each weights file.

    Returns a dict with three lists:
      - ``redundant``: {"arch": "...", "files": [paths]}  (>1 candidate)
      - ``orphaned``:  [paths with no arch attribution]
      - ``missing``:   [{"arch": "...", "want": "..."}]  (registry
                        declares a canonical path that isn't on disk)
    """
    by_arch: dict[str, list[str]] = {}
    orphaned: list[str] = []
    declared: dict[str, set[str]] = {}  # arch -> set of expected basenames

    for arch_id, arch in ARCHITECTURES.items():
        extra = getattr(arch, "extra", None) or {}
        for key in ("clip_name", "clip_name1", "clip_name2",
                    "vae_name", "audio_vae_name"):
            canonical = extra.get(key)
            if isinstance(canonical, str) and canonical:
                declared.setdefault(arch_id, set()).add(
                    Path(canonical).name.lower())

    for root, _dirs, files in os.walk(models_root):
        for f in files:
            path = Path(root) / f
            if path.suffix.lower() not in _WEIGHT_EXTS:
                continue
            arch_id = _attribute_file(path)
            if arch_id is None:
                orphaned.append(str(path))
            else:
                by_arch.setdefault(arch_id, []).append(str(path))

    redundant = [
        {"arch": a, "files": sorted(fs)}
        for a, fs in sorted(by_arch.items())
        if len(fs) > 1
    ]
    on_disk_basenames = {
        Path(p).name.lower()
        for files in by_arch.values()
        for p in files
    } | {Path(p).name.lower() for p in orphaned}
    missing = []
    for arch_id, wants in sorted(declared.items()):
        for want in sorted(wants):
            if want not in on_disk_basenames:
                missing.append({"arch": arch_id, "want": want})
    return {
        "models_root": str(models_root),
        "redundant": redundant,
        "orphaned": sorted(orphaned),
        "missing": missing,
    }


def _format_report(result: dict) -> str:
    out: list[str] = []
    out.append(f"audit_disk_vs_registry: root={result['models_root']}")
    out.append("")
    out.append(f"REDUNDANT  (>1 weights candidate per arch): {len(result['redundant'])}")
    for row in result["redundant"]:
        out.append(f"  [{row['arch']}]")
        for f in row["files"]:
            out.append(f"    - {f}")
    out.append("")
    out.append(f"ORPHANED  (no arch attribution): {len(result['orphaned'])}")
    for f in result["orphaned"]:
        out.append(f"  - {f}")
    out.append("")
    out.append(f"MISSING  (registry declares, disk lacks): {len(result['missing'])}")
    for row in result["missing"]:
        out.append(f"  - [{row['arch']}] {row['want']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models-root", type=Path, default=None,
                    help="ComfyUI models dir (default: $COMFYUI_MODELS_DIR, "
                         "else D:\\LLM\\ComfyUI\\models on Windows, else "
                         "~/ComfyUI/models)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what WOULD be scanned (registry size + "
                         "resolved root), do no filesystem walk. Used for "
                         "cloud-sandbox smoke tests.")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON instead of a text "
                         "report (for Hermes consumption).")
    args = ap.parse_args(argv)

    root = args.models_root or _default_root()
    arch_count = len(ARCHITECTURES)
    registered = sum(1 for a in ARCHITECTURES.values() if a.registered)
    stubs = arch_count - registered

    if args.dry_run:
        if args.json:
            print(json.dumps({
                "dry_run": True,
                "arch_total": arch_count,
                "arch_registered": registered,
                "arch_stubs": stubs,
                "resolved_root": str(root) if root else None,
            }, indent=2))
        else:
            print("audit_disk_vs_registry (DRY-RUN)")
            print(f"  registry: {registered} fully-registered + "
                  f"{stubs} stubs = {arch_count} total")
            root_label = str(root) if root else (
                "(none — pass --models-root or set COMFYUI_MODELS_DIR)")
            print(f"  resolved_root: {root_label}")
        return 0

    if root is None or not root.exists():
        print(
            "audit_disk_vs_registry: no models root resolved — "
            "pass --models-root or set COMFYUI_MODELS_DIR, or run "
            "with --dry-run from the cloud sandbox.",
            file=sys.stderr,
        )
        return 2

    result = audit(root)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(_format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
