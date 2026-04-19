#!/usr/bin/env python3
"""Regenerate DEPENDENCIES.md from installer/manifest.json.

The manifest is the single source of truth for which ComfyUI custom node packs
Spellcaster depends on. This script turns its "custom_nodes" section into a
human-readable markdown document for the repo README to link to.

Run from repo root:

    python scripts/generate_dependencies_md.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "installer" / "manifest.json"
OUTPUT = REPO_ROOT / "DEPENDENCIES.md"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    nodes: dict[str, dict] = manifest.get("custom_nodes", {})
    features: dict[str, dict] = manifest.get("features", {})

    required = {n: info for n, info in nodes.items() if info.get("required_by")}
    optional = {n: info for n, info in nodes.items() if not info.get("required_by")}

    lines: list[str] = []
    lines.append("# Dependencies")
    lines.append("")
    lines.append(
        "Spellcaster itself is a GIMP plugin + Python server. The AI capabilities "
        "come from [ComfyUI](https://github.com/comfyanonymous/ComfyUI) and a "
        "set of ComfyUI custom node packs. GitHub's dependency graph only tracks "
        "PyPI packages, so this document exists to list the ComfyUI-side "
        "dependencies explicitly."
    )
    lines.append("")
    lines.append(
        "**This file is generated from [`installer/manifest.json`](installer/manifest.json)**. "
        "Do not edit by hand — run `python scripts/generate_dependencies_md.py` after "
        "editing the manifest."
    )
    lines.append("")
    lines.append("## How dependencies are installed")
    lines.append("")
    lines.append(
        "The Spellcaster installer (`spellcaster-installer.exe` or "
        "`python installer/install.py`) clones each required node pack into "
        "`ComfyUI/custom_nodes/` automatically. If you prefer to install "
        "manually, clone each repo from the **Repo** column below into your "
        "`custom_nodes` directory and restart ComfyUI."
    )
    lines.append("")
    lines.append(f"Total node packs: **{len(nodes)}** "
                 f"({len(required)} required, {len(optional)} optional).")
    lines.append("")

    lines.append("## Required ComfyUI node packs")
    lines.append("")
    lines.append("These packs must be present for the listed features to work. "
                 "Missing packs cause a clear error at workflow-build time, "
                 "not a silent fallback.")
    lines.append("")
    lines.append("| Pack | Repo | Used by | Notes |")
    lines.append("|------|------|---------|-------|")
    for name in sorted(required):
        info = required[name]
        repo = info.get("repo", "")
        used_by = info.get("required_by", [])
        used_labels = [features.get(f, {}).get("label", f) for f in used_by]
        note = (info.get("note") or "").replace("|", "\\|")
        repo_cell = f"[{name}]({repo})" if repo else name
        used_cell = ", ".join(used_labels) if used_labels else "—"
        lines.append(f"| `{name}` | {repo_cell} | {used_cell} | {note} |")
    lines.append("")

    lines.append("## Optional ComfyUI node packs")
    lines.append("")
    lines.append("These packs unlock higher-quality or alternative pipelines "
                 "when present. Spellcaster auto-detects them and substitutes "
                 "them into workflows via the preflight validator.")
    lines.append("")
    lines.append("| Pack | Repo | Notes |")
    lines.append("|------|------|-------|")
    for name in sorted(optional):
        info = optional[name]
        repo = info.get("repo", "")
        note = (info.get("note") or "").replace("|", "\\|")
        repo_cell = f"[{name}]({repo})" if repo else name
        lines.append(f"| `{name}` | {repo_cell} | {note} |")
    lines.append("")

    lines.append("## Python dependencies")
    lines.append("")
    lines.append(
        "The GIMP plugin runs inside GIMP's bundled Python 3.12 and uses only "
        "the Python standard library — there is no `requirements.txt` to "
        "install. The Wizard Guild server (`tavern/`) and the installer "
        "(`installer/`) likewise depend only on the standard library for "
        "their core paths. Any heavier Python packages (torch, transformers, "
        "accelerate, insightface, etc.) are pulled in by ComfyUI and its "
        "custom nodes, not by Spellcaster directly."
    )
    lines.append("")

    lines.append("## Related repositories")
    lines.append("")
    lines.append(
        "Spellcaster is split across four repos. Only two are public:"
    )
    lines.append("")
    lines.append(
        "- [`laboratoiresonore/spellcaster`](https://github.com/laboratoiresonore/spellcaster) — "
        "this repo (main app, installer, GIMP plugin, Guild server)"
    )
    lines.append(
        "- [`laboratoiresonore/ComfyUI-Spellcaster`](https://github.com/laboratoiresonore/ComfyUI-Spellcaster) — "
        "the 4 custom Spellcaster ComfyUI nodes (auto-arch loader, prompt enhancer, "
        "sampler, output)"
    )
    lines.append("")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
