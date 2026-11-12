#!/usr/bin/env python3
"""Audit on-disk ComfyUI weights against the architecture registry.

Named as a Tier-1 follow-up by the 2026-10-16 ecosystem digest:

    1. `tools/audit_disk_vs_registry.py` is still a Tier-3 TODO.
       … If the next wave of fleet downloads (Flux-3-Klein, LTX-2.5,
       Qwen-Image-2.1 either lane) lands, the retirable-weights
       question lives behind this tool. Writing it is a ~100-line
       Tier-1 candidate for a future digest: read `architectures.py`
       + walk `ComfyUI/models/*`, print paths matching `registered=True`
       arches that have more than one weights candidate on disk.

What it does
------------
Reads the architecture registry out of the in-tree
``spellcaster_core/architectures.py`` without executing arbitrary
Python from it (the file imports fleet-side wrappers that are not
available in the cloud sandbox), walks a user-supplied ComfyUI
``models/`` directory, and prints:

  * every ``registered=True`` architecture name alongside the weight
    paths that match a built-in substring heuristic for that arch;
  * stub arches (``registered=False``) with any matching weights,
    flagged as "known-but-not-wired" (operator attention needed
    before deletion);
  * any weight file in ``models/`` that did NOT match any registered
    or stub arch, flagged as "unclassified" (not necessarily junk —
    could be an unregistered community model).

Where an arch has **more than one** weights candidate on disk, each
file is marked ``[CANDIDATE n/N]`` so the operator can decide which
to keep. Deletion is never performed by this tool; it only reports.

Usage
-----

    python tools/audit_disk_vs_registry.py --models-root D:\\LLM\\ComfyUI\\models
    python tools/audit_disk_vs_registry.py --models-root /path/to/models --json
    python tools/audit_disk_vs_registry.py --self-check

``--self-check`` runs against a bundled fixture tree so the tool is
testable from the cloud sandbox where the fleet filesystem is not
reachable.

Exit codes
----------
    0  audit complete, no duplicate-weights findings
    1  audit complete, at least one arch has >1 candidate on disk
    2  input error (missing models root etc.)
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
import tempfile
from typing import Dict, Iterable, List, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY_PATH = (
    REPO_ROOT / "comfyui-spellcaster" / "spellcaster_core" / "architectures.py"
)

# Heuristic substring matchers per arch name. Case-insensitive, matched
# against the relative POSIX path of each weights file. Deliberately
# conservative — a false negative (unclassified file) is fine, a false
# positive (wrong arch claimed) is misleading, so the patterns here
# correspond to canonical distribution names that community repackages
# generally preserve.
#
# When an arch is added to the registry, add a substring here too — or
# it will show up as "unclassified" in the audit output.
ARCH_SUBSTRINGS: Dict[str, Tuple[str, ...]] = {
    "sd15":          ("sd15", "sd-1-5", "v1-5-pruned"),
    "sdxl":          ("sdxl", "sd-xl", "sd_xl_base"),
    "sdxl_turbo":    ("sdxl_turbo", "sdxl-turbo", "sd_xl_turbo"),
    "illustrious":   ("illustrious", "illustrious-xl"),
    "pony":          ("pony", "ponydiffusion"),
    "playground":    ("playground-v2", "playground_v2"),
    "zit":           ("z-image-turbo", "z_image_turbo", "zit"),
    "chroma":        ("chroma",),
    "flux1dev":      ("flux1-dev", "flux1dev", "flux.1-dev"),
    "flux2klein":    ("flux2-klein", "flux.2-klein", "flux-2-image-klein"),
    "flux2dev":      ("flux2-dev", "flux.2-dev", "flux-2-dev"),
    "flux3klein":    ("flux3-klein", "flux.3-klein", "flux-3-image-klein"),
    "krea2":         ("krea2", "krea-2"),
    "qwen_image":    ("qwen-image", "qwen_image"),
    "flux_kontext":  ("flux-kontext", "flux_kontext"),
    "wan":           ("wan2", "wan-2", "wan_2"),
    "ltx":           ("ltx-video", "ltxv", "ltx-2"),
    "seedvr":        ("seedvr",),
    "cogvideo":      ("cogvideo", "cogvideox"),
    "framepack":     ("framepack", "frame-pack"),
    "hunyuan_video": ("hunyuanvideo", "hunyuan-video", "hunyuan_video"),
    "mochi":         ("mochi-1", "mochi_1", "mochi1"),
    "minimax_h3":    ("minimax", "hailuo-3", "hailuo_3"),
    "skyreels":      ("skyreels",),
    "longcat":       ("longcat",),
    "lumina2":       ("lumina-2", "lumina2"),
    "hunyuan_3d":    ("hunyuan3d", "hunyuan-3d"),
    "supir":         ("supir",),
    "aurasr":        ("aurasr", "aura-sr"),
    # Stubs — included so weights tagged with them don't show as
    # "unclassified". The operator still has to wire the loader before
    # anything useful happens.
    "sd3":           ("sd3", "stable-diffusion-3"),
    "sd3_turbo":     ("sd3-turbo", "sd3_turbo"),
    "hunyuan_dit":   ("hunyuan-dit", "hunyuandit"),
    "pixart":        ("pixart",),
    "auraflow":      ("auraflow",),
    "kolors":        ("kolors",),
}

WEIGHTS_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".bin")


def parse_registry(path: pathlib.Path = REGISTRY_PATH) -> List[Tuple[str, bool]]:
    """Return ``[(arch_name, registered_bool), ...]`` from the AST.

    Does NOT ``exec`` the module — the registry file imports fleet-side
    wrappers that are unavailable in the sandbox.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: List[Tuple[str, bool]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_reg"
        ):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        name = node.args[0].value
        registered = True
        for kw in node.keywords:
            if kw.arg == "registered" and isinstance(kw.value, ast.Constant):
                registered = bool(kw.value.value)
        out.append((name, registered))
    return out


def iter_weights(models_root: pathlib.Path) -> Iterable[pathlib.Path]:
    for path in models_root.rglob("*"):
        if path.is_file() and path.suffix.lower() in WEIGHTS_SUFFIXES:
            yield path


def classify(
    weights: Iterable[pathlib.Path],
    models_root: pathlib.Path,
) -> Tuple[Dict[str, List[pathlib.Path]], List[pathlib.Path]]:
    by_arch: Dict[str, List[pathlib.Path]] = {name: [] for name in ARCH_SUBSTRINGS}
    unclassified: List[pathlib.Path] = []
    for wpath in weights:
        rel = wpath.relative_to(models_root).as_posix().lower()
        matched = False
        for arch, needles in ARCH_SUBSTRINGS.items():
            if any(re.search(re.escape(n), rel) for n in needles):
                by_arch[arch].append(wpath)
                matched = True
                break
        if not matched:
            unclassified.append(wpath)
    return by_arch, unclassified


def render_report(
    arches: List[Tuple[str, bool]],
    by_arch: Dict[str, List[pathlib.Path]],
    unclassified: List[pathlib.Path],
    models_root: pathlib.Path,
) -> Tuple[str, int]:
    lines: List[str] = []
    lines.append(f"# Disk-vs-registry audit — {models_root}")
    lines.append("")
    duplicates = 0
    lines.append("## Registered arches with on-disk weights")
    lines.append("")
    registered_names = {n for n, r in arches if r}
    stub_names = {n for n, r in arches if not r}
    for name in sorted(registered_names):
        candidates = sorted(by_arch.get(name, []))
        if not candidates:
            continue
        marker = "  [DUP]" if len(candidates) > 1 else ""
        lines.append(f"- `{name}`{marker}")
        for i, path in enumerate(candidates, 1):
            tag = f"[CANDIDATE {i}/{len(candidates)}] " if len(candidates) > 1 else ""
            lines.append(f"  - {tag}{path.relative_to(models_root).as_posix()}")
        if len(candidates) > 1:
            duplicates += 1
    missing = sorted(n for n in registered_names if not by_arch.get(n))
    if missing:
        lines.append("")
        lines.append("## Registered arches with NO on-disk weights")
        lines.append("")
        for name in missing:
            lines.append(f"- `{name}`")
    stub_hits = sorted(n for n in stub_names if by_arch.get(n))
    if stub_hits:
        lines.append("")
        lines.append("## Stub arches (registered=False) with weights on disk")
        lines.append("")
        lines.append(
            "These have weights but no workflow wiring yet. Do NOT delete"
            " without an operator call."
        )
        lines.append("")
        for name in stub_hits:
            lines.append(f"- `{name}`")
            for path in sorted(by_arch[name]):
                lines.append(f"  - {path.relative_to(models_root).as_posix()}")
    if unclassified:
        lines.append("")
        lines.append("## Unclassified weight files")
        lines.append("")
        lines.append(
            "These did not match any arch substring heuristic. They may be"
            " community models, loras, or files for arches not yet added"
            " to `ARCH_SUBSTRINGS` in this tool."
        )
        lines.append("")
        for path in sorted(unclassified):
            lines.append(f"- {path.relative_to(models_root).as_posix()}")
    lines.append("")
    lines.append(f"Summary: {duplicates} arch(es) with duplicate candidates.")
    return "\n".join(lines) + "\n", duplicates


def _run_self_check() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "checkpoints").mkdir()
        (root / "unet").mkdir()
        (root / "ltx").mkdir()
        # Two sdxl candidates → should flag a duplicate.
        (root / "checkpoints" / "sd_xl_base_1.0.safetensors").write_bytes(b"x")
        (root / "checkpoints" / "sdxl_base_fp8.safetensors").write_bytes(b"x")
        # One flux3klein → single.
        (root / "unet" / "flux-3-image-klein.safetensors").write_bytes(b"x")
        # One stub kolors → expect stub section.
        (root / "checkpoints" / "kolors-v1.safetensors").write_bytes(b"x")
        # Unknown.
        (root / "checkpoints" / "mystery-model-9000.safetensors").write_bytes(b"x")

        arches = parse_registry()
        by_arch, unclassified = classify(iter_weights(root), root)
        report, dups = render_report(arches, by_arch, unclassified, root)
        print(report)
        assert dups == 1, f"expected 1 duplicate (sdxl), got {dups}"
        assert any("kolors" in line for line in report.splitlines())
        assert any("mystery-model-9000" in line for line in report.splitlines())
        print("self-check OK")
    return 0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--models-root",
        help="Path to the ComfyUI models/ directory to audit.",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON summary instead of markdown.",
    )
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="Run against a bundled fixture tree (for CI / sandbox).",
    )
    args = ap.parse_args(argv)
    if args.self_check:
        return _run_self_check()
    if not args.models_root:
        print("error: --models-root is required (or pass --self-check)", file=sys.stderr)
        return 2
    root = pathlib.Path(args.models_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    arches = parse_registry()
    by_arch, unclassified = classify(iter_weights(root), root)
    if args.json:
        payload = {
            "models_root": str(root),
            "arches": [
                {"name": n, "registered": r, "weights": [
                    str(p.relative_to(root)) for p in sorted(by_arch.get(n, []))
                ]}
                for n, r in arches
            ],
            "unclassified": [str(p.relative_to(root)) for p in sorted(unclassified)],
        }
        print(json.dumps(payload, indent=2))
        return 1 if any(len(by_arch.get(n, [])) > 1 for n, r in arches if r) else 0
    report, dups = render_report(arches, by_arch, unclassified, root)
    print(report)
    return 1 if dups else 0


if __name__ == "__main__":
    sys.exit(main())
