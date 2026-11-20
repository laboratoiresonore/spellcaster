#!/usr/bin/env python3
"""Compare the architecture registry against an on-disk weights manifest.

The 2026-10-16 ecosystem digest filed this tool as a Tier-1 candidate:
when the fleet starts rolling new generations onto `D:\\LLM` (Flux-3 Klein,
LTX-2.5, Qwen-Image-2.1, SAM 3.1, …), the question "what older weights can
I now retire?" and its mirror "which registered arches have NO on-disk
weights?" live behind one mechanical scan.

The tool is sandbox-friendly:

- No fleet access required. It reads
  ``comfyui-spellcaster/spellcaster_core/architectures.py`` (via import)
  for the registered-arch set, and a path listing provided on stdin or
  via ``--manifest``.
- A path listing is one absolute path per line, OR a JSON array of
  absolute paths, OR a ``.txt`` dump from
  ``powershell -c "Get-ChildItem D:\\LLM -Recurse | %{ $_.FullName }"`` /
  ``find D:/LLM -type f``.

Usage::

    # Pipe the manifest in:
    find D:/LLM/ComfyUI/models -type f | python tools/audit_disk_vs_registry.py

    # Or file path:
    python tools/audit_disk_vs_registry.py --manifest fleet-manifest.txt

    # Smoke-test with the tool's embedded empty manifest (CI):
    python tools/audit_disk_vs_registry.py --manifest /dev/null

Output sections:
    1. Arches with no on-disk weights match      (coverage gaps)
    2. Arches with >1 on-disk weights match      (retire candidates)
    3. On-disk files unmatched by any arch       (orphans)

Exit codes:
    0  no coverage gaps and no multi-match arches
    1  gaps or multi-matches found (informational — not a CI fail)
    2  bad input
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_CORE_PARENT = _REPO / "comfyui-spellcaster"
if _CORE_PARENT.is_dir() and str(_CORE_PARENT) not in sys.path:
    sys.path.insert(0, str(_CORE_PARENT))


# Per-arch filename patterns. These are regex fragments (case-insensitive)
# matched against the basename of each on-disk file. Each list is a
# disjunction — ANY match counts.
#
# Two guiding rules when extending this table:
#   1. Prefer tight patterns (e.g. "flux2-?dev" rather than "flux") so
#      flux1dev and flux2dev don't both claim the same checkpoint.
#   2. When one arch's weights legitimately live under another name (an
#      aurasr .safetensors stored alongside supir, say), add it to the
#      aurasr list rather than widening supir's.
_ARCH_PATTERNS: dict[str, list[str]] = {
    "sd15": [r"\bsd[-_]?1[._]?5\b", r"stable[-_]diffusion[-_]v1[-_.]?5"],
    "sdxl": [r"\bsdxl\b", r"stable[-_]diffusion[-_]xl"],
    "sdxl_turbo": [r"sdxl[-_]turbo", r"sd[-_]turbo"],
    "illustrious": [r"illustrious", r"noobai"],
    "pony": [r"pony[-_]?diffusion", r"\bponyxl\b"],
    "playground": [r"playground[-_]v?2[._]?5"],
    "zit": [r"z[-_]?image[-_]?turbo", r"\bzit\b"],
    "chroma": [r"\bchroma\b"],
    "flux1dev": [r"flux[-_.]?1[-_.]?dev"],
    "flux2klein": [r"flux[-_.]?2[-_.]?klein"],
    "flux2dev": [r"flux[-_.]?2[-_.]?dev"],
    "flux3klein": [r"flux[-_.]?3[-_.]?klein"],
    "krea2": [r"\bkrea[-_.]?2\b"],
    "qwen_image": [r"qwen[-_]?image"],
    "flux_kontext": [r"flux[-_.]?kontext", r"flux[-_.]?1[-_.]?kontext"],
    "wan": [r"\bwan[-_.]?2", r"\bwan[-_]?i2v"],
    "ltx": [r"\bltx(v|[-_.]?video|[-_.]?2)"],
    "seedvr": [r"seedvr", r"seed[-_]vr"],
    "cogvideo": [r"cogvideo(x)?"],
    "framepack": [r"frame[-_]?pack"],
    "hunyuan_video": [r"hunyuan[-_]?video"],
    "mochi": [r"\bmochi[-_.]?1?\b"],
    "minimax_h3": [r"minimax[-_]hailuo", r"hailuo[-_]3", r"minimax[-_]?h3"],
    "skyreels": [r"sky[-_]?reels"],
    "longcat": [r"longcat"],
    "lumina2": [r"lumina[-_.]?image[-_.]?2", r"\blumina[-_.]?2\b"],
    "hunyuan_3d": [r"hunyuan[-_]?3d"],
    "supir": [r"\bsupir\b"],
    "aurasr": [r"\baura[-_]?sr\b"],
}


def _load_registered_arches() -> set[str]:
    """Import the registry and return the fully-registered arch set."""
    from spellcaster_core.architectures import ARCHITECTURES  # noqa: E402
    return {k for k, v in ARCHITECTURES.items() if v.registered}


def _read_manifest(path: str | None) -> list[str]:
    raw = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        return [str(p) for p in json.loads(raw)]
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _compile_patterns() -> dict[str, re.Pattern[str]]:
    return {a: re.compile("|".join(pats), re.IGNORECASE)
            for a, pats in _ARCH_PATTERNS.items()}


def audit(paths: list[str],
          arches: set[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Return (per-arch matches, orphan paths)."""
    compiled = _compile_patterns()
    per_arch: dict[str, list[str]] = {a: [] for a in arches}
    orphans: list[str] = []
    for p in paths:
        base = Path(p).name
        matched = False
        for a in arches:
            pat = compiled.get(a)
            if pat and pat.search(base):
                per_arch[a].append(p)
                matched = True
        if not matched:
            orphans.append(p)
    return per_arch, orphans


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", help="path listing (one path/line or JSON)")
    ap.add_argument("--only", help="comma-separated arch allowlist")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-section headers; machine-readable JSON")
    args = ap.parse_args(argv)

    try:
        arches = _load_registered_arches()
    except Exception as exc:  # pragma: no cover
        print(f"error: could not load registry: {exc}", file=sys.stderr)
        return 2

    if args.only:
        allow = {a.strip() for a in args.only.split(",") if a.strip()}
        arches &= allow

    try:
        paths = _read_manifest(args.manifest)
    except Exception as exc:
        print(f"error: could not read manifest: {exc}", file=sys.stderr)
        return 2

    per_arch, orphans = audit(paths, arches)

    coverage_gaps = sorted(a for a, hits in per_arch.items() if not hits)
    multi_match = sorted(((a, hits) for a, hits in per_arch.items()
                          if len(hits) > 1), key=lambda t: -len(t[1]))

    if args.quiet:
        print(json.dumps({
            "coverage_gaps": coverage_gaps,
            "multi_match": {a: hits for a, hits in multi_match},
            "orphans": orphans,
            "scanned": len(paths),
            "registered_arches": sorted(arches),
        }, indent=2))
    else:
        print(f"Scanned {len(paths)} paths against {len(arches)} "
              f"registered arches.\n")
        print("# Coverage gaps (arch registered, NO weights on disk)")
        for a in coverage_gaps:
            print(f"  - {a}")
        if not coverage_gaps:
            print("  (none)")
        print("\n# Retire candidates (arch has >1 weights match on disk)")
        for a, hits in multi_match:
            print(f"  - {a} [{len(hits)} files]")
            for h in hits[:8]:
                print(f"      {h}")
            if len(hits) > 8:
                print(f"      … +{len(hits) - 8} more")
        if not multi_match:
            print("  (none)")
        print(f"\n# Orphans (on disk, unmatched by any registered arch): "
              f"{len(orphans)}")
        for o in orphans[:20]:
            print(f"  - {o}")
        if len(orphans) > 20:
            print(f"  … +{len(orphans) - 20} more")

    return 0 if not coverage_gaps and not multi_match else 1


if __name__ == "__main__":
    sys.exit(main())
