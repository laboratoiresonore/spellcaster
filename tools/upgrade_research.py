#!/usr/bin/env python3
"""Snapshot the Spellcaster stack for the ecosystem-research routine.

The every-48h cloud digest names this tool in its prompt. It collects a
compact, offline snapshot of what the repo currently declares so the
research routine can diff against upstream (HF, GitHub) and decide what
to flag as Tier 1/2/3.

No network calls. No writes outside the file named by --out.
Reads only the repo checkout it's invoked in.

Usage:
    python tools/upgrade_research.py                       # print JSON to stdout
    python tools/upgrade_research.py --format yaml         # print YAML to stdout
    python tools/upgrade_research.py --out snap.json       # write JSON to file
    python tools/upgrade_research.py --out snap.yaml --format yaml
    python tools/upgrade_research.py --now 2026-08-26T00:00:00Z

Exit codes:
    0  snapshot written / printed
    1  a required source file was missing or malformed
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"missing required file: {path.relative_to(REPO_ROOT)}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"invalid JSON in {path.relative_to(REPO_ROOT)}: {e}")


def collect_methods() -> dict:
    manifest = _load_json(
        REPO_ROOT / "comfyui-spellcaster" / "spellcaster_core" / "builders_manifest.json"
    )
    methods = manifest.get("methods", [])
    families: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for m in methods:
        families[m.get("model_family", "unknown")] = (
            families.get(m.get("model_family", "unknown"), 0) + 1
        )
        kinds[m.get("kind", "unknown")] = kinds.get(m.get("kind", "unknown"), 0) + 1
    return {
        "count": len(methods),
        "schema_version": manifest.get("schema_version"),
        "by_family": dict(sorted(families.items(), key=lambda kv: -kv[1])),
        "by_kind": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "ids": sorted(m["id"] for m in methods if "id" in m),
    }


_ARCH_RE = re.compile(r'^_reg\("([a-z0-9_]+)"', re.MULTILINE)


def collect_archs() -> dict:
    archs_py = (
        REPO_ROOT / "comfyui-spellcaster" / "spellcaster_core" / "architectures.py"
    )
    if not archs_py.is_file():
        return {"count": 0, "ids": [], "source_missing": True}
    text = archs_py.read_text(encoding="utf-8", errors="replace")
    ids = sorted(set(_ARCH_RE.findall(text)))
    return {"count": len(ids), "ids": ids}


_DEPS_TOTAL_RE = re.compile(
    r"Total node packs:\s*\*\*(\d+)\*\*\s*\((\d+)\s+required,\s*(\d+)\s+optional\)",
    re.IGNORECASE,
)


def collect_node_packs() -> dict:
    manifest_path = REPO_ROOT / "installer" / "manifest.json"
    if not manifest_path.is_file():
        return {"total": 0, "packs": [], "source_missing": True}
    manifest = _load_json(manifest_path)
    packs = manifest.get("custom_nodes") or manifest.get("node_packs") or {}
    if isinstance(packs, dict):
        pack_list = [
            {"name": name, "repo": (meta or {}).get("repo")}
            for name, meta in sorted(packs.items(), key=lambda kv: kv[0].lower())
        ]
    else:
        pack_list = sorted(
            (
                {
                    "name": (p.get("name") or p.get("id")),
                    "repo": (p.get("repo") or p.get("url")),
                }
                for p in packs
            ),
            key=lambda e: (e["name"] or "").lower(),
        )

    # The required/optional split is documented in DEPENDENCIES.md, not in the JSON.
    required = optional = None
    deps_md = REPO_ROOT / "DEPENDENCIES.md"
    if deps_md.is_file():
        m = _DEPS_TOTAL_RE.search(deps_md.read_text(encoding="utf-8", errors="replace"))
        if m:
            _, required, optional = int(m.group(1)), int(m.group(2)), int(m.group(3))

    return {
        "total": len(pack_list),
        "required_count": required,
        "optional_count": optional,
        "packs": pack_list,
    }


def collect_readme_status() -> dict:
    readme = REPO_ROOT / "README.md"
    if not readme.is_file():
        return {"status_line": None}
    m = re.search(
        r"(?:\*\*|<strong>)\s*(?:📣\s*)?Status\s+[—-]\s+([^*<\n]+?)\s*(?:\*\*|</strong>)",
        readme.read_text(encoding="utf-8", errors="replace"),
    )
    return {"status_line": m.group(1).strip() if m else None}


def build_snapshot(now: str | None) -> dict:
    return {
        "generated_at": now or "unspecified",
        "repo": "laboratoiresonore/spellcaster",
        "tool": "tools/upgrade_research.py",
        "readme_status": collect_readme_status(),
        "methods": collect_methods(),
        "architectures": collect_archs(),
        "node_packs": collect_node_packs(),
    }


def _to_yaml(data, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(data, dict):
        if not data:
            return "{}"
        out = []
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out.append(_to_yaml(v, indent + 1))
            else:
                out.append(f"{pad}{k}: {_to_yaml_scalar(v)}")
        return "\n".join(out)
    if isinstance(data, list):
        if not data:
            return "[]"
        out = []
        for item in data:
            if isinstance(item, (dict, list)) and item:
                out.append(f"{pad}-")
                out.append(_to_yaml(item, indent + 1))
            else:
                out.append(f"{pad}- {_to_yaml_scalar(item)}")
        return "\n".join(out)
    return _to_yaml_scalar(data)


def _to_yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if any(c in s for c in ":#\n") or s in ("null", "true", "false", ""):
        return json.dumps(s)
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--now", help="ISO timestamp to stamp into the snapshot")
    ap.add_argument("--out", type=Path, help="write to this path instead of stdout")
    ap.add_argument("--format", choices=("json", "yaml"), default="json")
    args = ap.parse_args()

    snap = build_snapshot(args.now)

    if args.format == "yaml":
        payload = _to_yaml(snap) + "\n"
    else:
        payload = json.dumps(snap, indent=2, sort_keys=False) + "\n"

    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        np = snap["node_packs"]
        split = (
            f"{np['required_count']} required + {np['optional_count']} optional"
            if np.get("required_count") is not None
            else f"{np.get('total', 0)} packs"
        )
        print(
            f"wrote {args.out} "
            f"({snap['methods']['count']} methods, "
            f"{snap['architectures']['count']} archs, "
            f"{split})"
        )
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
