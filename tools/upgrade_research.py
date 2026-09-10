#!/usr/bin/env python3
"""Upgrade-research inventory dump.

Emits a machine-readable snapshot of the "upgrade surface" of the
Spellcaster repo so the periodic cloud-side ecosystem-research
routine (see ``.github/workflows`` + the cloud brief) has a single
authoritative starting point instead of re-deriving the model /
node / builder set by ad-hoc grep each run.

The routine (an Anthropic cloud sandbox with no LAN access) reads
this JSON, then queries the Hugging Face Hub + WebSearch for
newer or replacement models, and produces an ``_dev_docs/
ecosystem_digest_<date>.md`` PR against the repo. This script
itself does NOT hit the network. It is intentionally stdlib-only
so it can run inside the sandbox from a fresh clone without any
setup, and inside the dev host with the same behaviour.

Sources it reads (all in-repo):

  * ``comfyui-spellcaster/spellcaster_core/architectures.py`` —
    registered arch keys via ``_reg("key", ...)``.
  * ``installer/manifest.json`` — ComfyUI custom-node packs with
    ``repo`` + ``provides`` + ``required_by``.
  * ``comfyui-spellcaster/spellcaster_core/builders_manifest.json``
    — build_* workflows (id, model_family, target_class).

Outputs (pick one):

  * default / ``--json``      — one JSON blob to stdout.
  * ``--markdown``            — same content, rendered as a compact
                                Markdown report (nice for a PR
                                comment or for feeding an LLM).
  * ``--field <name>``        — print just one section: ``archs``,
                                ``nodes``, ``builders``.

The script exits 0 on a successful dump, 2 if a source file is
missing (a genuine repo problem the caller should surface).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent

ARCH_FILE = REPO / "comfyui-spellcaster" / "spellcaster_core" / "architectures.py"
MANIFEST_FILE = REPO / "installer" / "manifest.json"
BUILDERS_FILE = (
    REPO / "comfyui-spellcaster" / "spellcaster_core" / "builders_manifest.json"
)

# Restoration / upscale / face-restore / segmentation models are not in the
# arch registry (they are non-diffusion helpers), so keep a hand-maintained
# list here that the routine can compare against the Hub. Update this list
# when a new class of helper model lands.
HELPER_MODELS = {
    "restoration": ["SUPIR", "SeedVR2"],
    "upscale": ["UltraSharp", "RealESRGAN", "Remacri", "NMKD", "Anime"],
    "face_restore": [
        "GPEN-2048", "CodeFormer", "GFPGAN", "RestoreFormer++",
    ],
    "face_id": ["ReActor", "PuLID", "IPAdapter FaceID"],
    "segmentation": ["SAM3"],
    "background_removal": ["rembg", "BiRefNet", "BiRefNet Portrait", "RMBG-2.0"],
    "depth": ["DepthAnythingV3"],
    "normal": ["NormalCrafter"],
    "colorize": ["DDColor"],
}


def _parse_archs(path: Path) -> list[str]:
    """Return the list of arch keys registered via ``_reg("key", ...)``."""
    text = path.read_text(encoding="utf-8")
    # ``_reg("key", ...)`` at column 0 — this is the convention in the file.
    # Nested / commented forms are indented and won't match.
    return re.findall(r'^_reg\(\s*"([^"]+)"', text, flags=re.MULTILINE)


def _parse_nodes(path: Path) -> dict[str, dict[str, Any]]:
    """Return {node_pack_name: {repo, provides, required_by}} from installer manifest."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for name, meta in (data.get("custom_nodes") or {}).items():
        out[name] = {
            "repo": meta.get("repo"),
            "alt_repo": meta.get("alt_repo"),
            "provides": meta.get("provides") or [],
            "required_by": meta.get("required_by") or [],
            "optional": bool(meta.get("optional", False)),
        }
    return out


def _parse_builders(path: Path) -> list[dict[str, Any]]:
    """Return a compact list of build_* entries from builders_manifest.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = None
    if isinstance(data, dict):
        # The generated manifest uses ``methods`` at the top level; older
        # hand-written variants used ``builders``. Accept either.
        entries = data.get("methods") or data.get("builders")
    elif isinstance(data, list):
        entries = data
    if not isinstance(entries, list):
        return []
    keep = ("id", "builder", "kind", "model_family", "target_class", "short_doc")
    return [{k: e.get(k) for k in keep if k in e} for e in entries]


def _missing(files: list[Path]) -> list[Path]:
    return [p for p in files if not p.exists()]


def _snapshot() -> dict[str, Any]:
    return {
        "repo": "laboratoiresonore/spellcaster",
        "sources": {
            "archs": str(ARCH_FILE.relative_to(REPO)),
            "nodes": str(MANIFEST_FILE.relative_to(REPO)),
            "builders": str(BUILDERS_FILE.relative_to(REPO)),
        },
        "archs": _parse_archs(ARCH_FILE),
        "nodes": _parse_nodes(MANIFEST_FILE),
        "builders": _parse_builders(BUILDERS_FILE),
        "helper_models": HELPER_MODELS,
    }


def _render_markdown(snap: dict[str, Any]) -> str:
    out: list[str] = []
    out.append(f"# Spellcaster upgrade-research inventory\n")
    out.append(f"Repo: `{snap['repo']}`\n")

    out.append(f"\n## Registered architectures ({len(snap['archs'])})\n")
    out.append(", ".join(f"`{k}`" for k in snap["archs"]))

    nodes = snap["nodes"]
    out.append(f"\n\n## ComfyUI custom-node packs ({len(nodes)})\n")
    out.append("| Pack | Repo | Required by |")
    out.append("|---|---|---|")
    for name, meta in sorted(nodes.items()):
        req = ", ".join(meta["required_by"]) or "-"
        out.append(f"| `{name}` | {meta['repo']} | {req} |")

    builders = snap["builders"]
    out.append(f"\n## Workflow builders ({len(builders)})\n")
    fam_counts: dict[str, int] = {}
    for b in builders:
        fam = b.get("model_family") or "?"
        fam_counts[fam] = fam_counts.get(fam, 0) + 1
    for fam, n in sorted(fam_counts.items(), key=lambda kv: -kv[1]):
        out.append(f"- `{fam}`: {n}")

    helpers = snap["helper_models"]
    out.append(f"\n## Helper models (non-diffusion, hand-maintained)\n")
    for cat, items in helpers.items():
        out.append(f"- **{cat}**: {', '.join(items)}")

    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--markdown", action="store_true",
                   help="Render Markdown instead of JSON.")
    p.add_argument("--field", choices=("archs", "nodes", "builders", "helper_models"),
                   help="Emit just one section.")
    args = p.parse_args(argv)

    missing = _missing([ARCH_FILE, MANIFEST_FILE, BUILDERS_FILE])
    if missing:
        for m in missing:
            print(f"upgrade_research: missing source file: {m}", file=sys.stderr)
        return 2

    snap = _snapshot()

    if args.field:
        payload: Any = snap[args.field]
    else:
        payload = snap

    if args.markdown and not args.field:
        sys.stdout.write(_render_markdown(snap))
    else:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
