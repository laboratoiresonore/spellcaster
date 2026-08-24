#!/usr/bin/env python3
"""Ecosystem upgrade-research fact-collector.

Emits a structured snapshot of the Spellcaster stack that the
every-48h ecosystem-digest routine consumes to decide what to
research: which model families, architectures, node packs, and
build_ methods exist today, so the sweep can ask "is there anything
newer for X" and sort answers into Tier 1/2/3 findings.

The routine's own prompt names this tool by path and expects to
shell out to it. If we're missing it, we degrade to web-only
research and forget half of what the repo already ships — so this
file exists to be the canonical fact-collector.

Design goals
------------
- **No network calls.** The routine does its own WebSearch /
  WebFetch / HF hub queries. This tool only marshals what's already
  in the checkout.
- **No optional imports.** Reads JSON and greps text; does not
  import ``spellcaster_core`` (which would need ComfyUI on the
  path). Callable from any Python 3.10+ in the base venv.
- **Best-effort.** Any missing input degrades to a `null` field
  with a note, never aborts. The routine needs SOMETHING even if
  a source file has moved.

Output shape (JSON to stdout by default; ``--out FILE`` to write)::

    {
      "generated_at": "2026-08-24T00:00:00Z",  # UTC; --now overrides
      "repo": "spellcaster",
      "stack": {
        "method_count": 76,
        "methods": [ {"id": ..., "model_family": ..., ...}, ... ],
        "model_families": ["sdxl", "klein", "wan", ...],
        "custom_archs": ["my_custom_model"],
        "node_packs": {
          "required": [ {"name": ..., "repo": ..., "used_by": ...}, ... ],
          "optional": [...],
          "counts": {"required": 20, "optional": 5, "total": 25}
        }
      },
      "research_hints": [
        {"topic": "flux2klein", "reason": "current fastest quality engine",
         "watch": ["black-forest-labs", "capitan01R/ComfyUI-Flux2Klein-Enhancer"]},
        ...
      ],
      "notes": ["free-form observations for the digest header"]
    }

Usage
-----

    python tools/upgrade_research.py                   # JSON to stdout
    python tools/upgrade_research.py --out snap.json   # write to file
    python tools/upgrade_research.py --format yaml     # yaml (no deps: hand-rolled)
    python tools/upgrade_research.py --now 2026-08-24  # deterministic timestamp

Exit codes: 0 always; a section that couldn't be collected shows up
as ``null`` in the payload with a matching entry in ``notes``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "comfyui-spellcaster" / "spellcaster_core" / "builders_manifest.json"
ARCHS_DIR = REPO / "comfyui-spellcaster" / "spellcaster_core" / "archs"
DEPS_MD = REPO / "DEPENDENCIES.md"

# Topics the digest should always sweep for updates. Keep the list
# short and load-bearing: these are the model families whose
# upstream cadence is fast enough that a 48h sweep can plausibly
# find something. New family lands in workflows.py → add here so
# the next digest looks for it.
RESEARCH_HINTS = [
    {"topic": "flux2klein",
     "reason": "current fastest quality engine; Flux 2 line moves quickly",
     "watch": ["black-forest-labs", "capitan01R/ComfyUI-Flux2Klein-Enhancer"]},
    {"topic": "wan_video",
     "reason": "Wan 2.2 I2V + T2V; Alibaba iterates on the WAN line",
     "watch": ["Wan-AI", "Kijai/ComfyUI-WanVideoWrapper"]},
    {"topic": "ltx_video",
     "reason": "LTX-Video versions ship quickly (2.x line)",
     "watch": ["Lightricks/LTX-Video"]},
    {"topic": "supir",
     "reason": "restoration; SUPIR / SeedVR2 / photo_restore compete for the same slot",
     "watch": ["Fanghua-Yu/SUPIR", "ByteDance/SeedVR"]},
    {"topic": "sam3",
     "reason": "segmentation; SAM3 lineage is active",
     "watch": ["facebookresearch"]},
    {"topic": "birefnet",
     "reason": "background removal; BiRefNet variants land frequently",
     "watch": ["ZhengPeng7/BiRefNet"]},
    {"topic": "pulid",
     "reason": "identity-preserving portraits; PuLID-Flux iterations",
     "watch": ["ToTheBeginning/PuLID"]},
    {"topic": "reactor_faceswap",
     "reason": "faceswap engine; inswapper alternatives keep appearing",
     "watch": ["Gourieff/comfyui-reactor-node"]},
    {"topic": "depth_anything",
     "reason": "depth for 3D + SBS pipelines; Depth-Anything V2/V3 cadence",
     "watch": ["DepthAnything"]},
    {"topic": "controlnet_aux",
     "reason": "preprocessor pack; new preprocessors show up regularly",
     "watch": ["Fannovel16/comfyui_controlnet_aux"]},
]


def _load_manifest() -> tuple[dict | None, str | None]:
    if not MANIFEST.is_file():
        return None, f"missing: {MANIFEST.relative_to(REPO)}"
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover - guardrail only
        return None, f"unreadable manifest: {exc!r}"


def _custom_archs() -> list[str]:
    if not ARCHS_DIR.is_dir():
        return []
    out: list[str] = []
    for p in sorted(ARCHS_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            out.append(p.stem)
            continue
        out.append(str(data.get("key") or p.stem))
    return out


# The Required table has 4 columns (Pack | Repo | Used by | Notes);
# the Optional table has 3 (Pack | Repo | Notes). Handle both by
# capturing the tail as a variable-length list of cells.
_PACK_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*\[[^\]]+\]\(([^)]+)\)\s*\|(.*)$"
)


def _parse_dependencies_md() -> tuple[dict | None, str | None]:
    if not DEPS_MD.is_file():
        return None, f"missing: {DEPS_MD.name}"
    src = DEPS_MD.read_text(encoding="utf-8")
    sections: dict[str, list[dict]] = {"required": [], "optional": []}
    current: str | None = None
    for line in src.splitlines():
        low = line.lower()
        if low.startswith("## required"):
            current = "required"
            continue
        if low.startswith("## optional"):
            current = "optional"
            continue
        if line.startswith("## ") and current is not None:
            current = None
        if current is None:
            continue
        m = _PACK_ROW.match(line)
        if not m:
            continue
        name, repo, tail = m.groups()
        # Split remaining cells; a trailing `|` from the table
        # closer yields an empty final chunk that we drop.
        cells = [c.strip() for c in tail.split("|")]
        if cells and cells[-1] == "":
            cells.pop()
        entry: dict = {"name": name.strip(), "repo": repo.strip()}
        if current == "required":
            entry["used_by"] = cells[0] if len(cells) >= 1 else ""
            entry["notes"]   = (cells[1] if len(cells) >= 2 else "") or None
        else:
            entry["used_by"] = None  # optional table doesn't carry this column
            entry["notes"]   = (cells[0] if cells else "") or None
        sections[current].append(entry)
    counts = {
        "required": len(sections["required"]),
        "optional": len(sections["optional"]),
        "total":    len(sections["required"]) + len(sections["optional"]),
    }
    return {"required": sections["required"],
            "optional": sections["optional"],
            "counts":   counts}, None


def _collect_stack(notes: list[str]) -> dict:
    manifest, err = _load_manifest()
    if err:
        notes.append(err)
    methods = manifest.get("methods", []) if manifest else []
    method_count = manifest.get("method_count") if manifest else None
    families = sorted({m.get("model_family") for m in methods
                       if m.get("model_family")})
    packs, perr = _parse_dependencies_md()
    if perr:
        notes.append(perr)
    return {
        "method_count":   method_count,
        "methods":        [{
            "id":           m.get("id"),
            "kind":         m.get("kind"),
            "model_family": m.get("model_family"),
            "target_class": m.get("target_class"),
            "nsfw":         m.get("nsfw", False),
        } for m in methods],
        "model_families": families,
        "custom_archs":   _custom_archs(),
        "node_packs":     packs,
    }


def _yaml_dump(obj, indent: int = 0) -> str:
    """Tiny hand-rolled YAML emitter — no PyYAML dep. Handles the
    shapes this tool actually produces (str / int / bool / None /
    list / dict). Not general-purpose."""
    pad = "  " * indent
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return repr(obj)
    if isinstance(obj, str):
        if obj == "" or re.search(r"[:#\-\n\"'\[\]{}&*!|>%@`]", obj):
            return json.dumps(obj, ensure_ascii=False)
        return obj
    if isinstance(obj, list):
        if not obj:
            return "[]"
        out = []
        for item in obj:
            rendered = _yaml_dump(item, indent + 1)
            if isinstance(item, (dict, list)) and rendered not in ("{}", "[]"):
                out.append(f"{pad}-\n{rendered}")
            else:
                out.append(f"{pad}- {rendered}")
        return "\n".join(out)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        out = []
        for k, v in obj.items():
            rendered = _yaml_dump(v, indent + 1)
            if isinstance(v, (dict, list)) and rendered not in ("{}", "[]"):
                out.append(f"{pad}{k}:\n{rendered}")
            else:
                out.append(f"{pad}{k}: {rendered}")
        return "\n".join(out)
    return json.dumps(str(obj))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=None,
                    help="write payload to FILE (default: stdout)")
    ap.add_argument("--format", choices=["json", "yaml"], default="json",
                    help="output format (default: json)")
    ap.add_argument("--now", default=None,
                    help="ISO-8601 timestamp override (default: current UTC)")
    args = ap.parse_args()

    notes: list[str] = []
    stack = _collect_stack(notes)

    if args.now:
        generated_at = args.now
    else:
        # Deferred import: keeps `--now` runs deterministic in envs
        # where wall-clock is unavailable (some sandboxes / cron).
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "generated_at":    generated_at,
        "repo":            "spellcaster",
        "stack":           stack,
        "research_hints":  RESEARCH_HINTS,
        "notes":           notes,
    }

    if args.format == "yaml":
        rendered = _yaml_dump(payload) + "\n"
    else:
        rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        try:
            display = args.out.relative_to(REPO)
        except ValueError:
            display = args.out
        print(f"wrote {display} "
              f"({stack['method_count']} methods, "
              f"{len(stack['model_families'])} families).",
              file=sys.stderr)
    else:
        sys.stdout.write(rendered)

    return 0


if __name__ == "__main__":
    sys.exit(main())
