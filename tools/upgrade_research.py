#!/usr/bin/env python3
"""Snapshot the model / arch / node-pack surface for the ecosystem digest.

The every-48h ecosystem-research routine (see _dev_docs/ecosystem_digest_*.md)
compares this snapshot against public model / node-pack registries to find
upgrade candidates. The routine expects this tool to exist; a missing tool
of its own name is a Tier-1 gap the routine is supposed to fix on itself,
which is why this minimal implementation exists.

The snapshot is deliberately narrow:

  * Every ``_reg()`` architecture in ``comfyui-spellcaster/spellcaster_core/architectures.py``
    with its ``registered`` flag and ``supported_methods`` (so the digest
    can spot arch stubs that never got promoted).
  * Every arch key the detector can emit (``model_detect.UNET_ARCH_RULES``
    and ``CKPT_ARCH_RULES``) so the digest can flag detector-keys with no
    matching ``_reg()`` block — the exact class of bug that let ``supir``
    silently fall back to SDXL for months.
  * Every ComfyUI node pack from ``installer/manifest.json`` with its
    upstream repo — the digest can then hit each repo's default branch
    and compare against the version the installer will pull.

Output is JSON on stdout by default. ``--yaml`` prints a bare YAML block
suitable for embedding in a digest. ``--diff <prior.json>`` prints only
what changed (arch keys added / removed, stubs still un-promoted, node
packs whose upstream URL moved).

The tool is intentionally offline-only. Enrichment (upstream tags, HF
model dates, security advisories) happens in the digest routine itself
using WebFetch / MCP; this tool just produces the ground-truth snapshot
of what the repo currently ships so the routine has a stable baseline to
compare against.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any


_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent


def _add_sys_path() -> None:
    for p in (_REPO / "comfyui-spellcaster", _REPO):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


@contextlib.contextmanager
def _quiet_imports():
    # spellcaster_core.arch_registry prints a "Loaded N custom architecture(s)"
    # banner to stdout at import time. That noise would break --out JSON /
    # YAML piping, so swallow stdout during the ARCHITECTURES import.
    real = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = real


def snapshot_archs() -> list[dict[str, Any]]:
    _add_sys_path()
    with _quiet_imports():
        from spellcaster_core.architectures import ARCHITECTURES  # type: ignore
    out: list[dict[str, Any]] = []
    for key in sorted(ARCHITECTURES):
        arch = ARCHITECTURES[key]
        out.append({
            "key": key,
            "registered": bool(getattr(arch, "registered", False)),
            "loader": getattr(arch, "loader", None),
            "sampler": getattr(arch, "sampler", None),
            "clip_mode": getattr(arch, "clip_mode", None),
            "supports_negative": bool(getattr(arch, "supports_negative", False)),
            "default_resolution": list(getattr(arch, "default_resolution", ()) or ()),
            "default_cfg": getattr(arch, "default_cfg", None),
            "default_steps": getattr(arch, "default_steps", None),
            "supported_methods": sorted(getattr(arch, "supported_methods", ()) or ()),
            "scene_group": getattr(arch, "scene_group", None),
        })
    return out


def snapshot_detector_keys() -> dict[str, Any]:
    _add_sys_path()
    with _quiet_imports():
        from spellcaster_core.model_detect import UNET_ARCH_RULES, CKPT_ARCH_RULES  # type: ignore
        from spellcaster_core.architectures import ARCHITECTURES  # type: ignore
    unet_keys = sorted({arch for _kw, arch in UNET_ARCH_RULES})
    ckpt_keys = sorted({arch for _kw, arch in CKPT_ARCH_RULES})
    all_keys = sorted(set(unet_keys) | set(ckpt_keys))
    missing = sorted(k for k in all_keys if k not in ARCHITECTURES)
    stubs = sorted(k for k in all_keys
                   if k in ARCHITECTURES
                   and not bool(getattr(ARCHITECTURES[k], "registered", False)))
    return {
        "unet_rule_keys": unet_keys,
        "ckpt_rule_keys": ckpt_keys,
        "all_detector_keys": all_keys,
        "detector_keys_missing_arch_config": missing,
        "detector_keys_unpromoted_stubs": stubs,
    }


def snapshot_node_packs() -> list[dict[str, Any]]:
    manifest_path = _REPO / "installer" / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [{"error": f"failed to parse manifest.json: {exc}"}]
    packs = data.get("custom_nodes") or data.get("node_packs") or []
    out: list[dict[str, Any]] = []
    if isinstance(packs, list):
        for entry in packs:
            if not isinstance(entry, dict):
                continue
            out.append({
                "name": entry.get("name") or entry.get("id"),
                "repo": entry.get("repo") or entry.get("url"),
                "required": bool(entry.get("required", True)),
                "used_by": entry.get("used_by") or entry.get("purpose"),
                "notes": entry.get("notes"),
            })
    elif isinstance(packs, dict):
        for name, entry in packs.items():
            if not isinstance(entry, dict):
                out.append({"name": name, "repo": entry})
                continue
            out.append({
                "name": name,
                "repo": entry.get("repo") or entry.get("url"),
                "required": bool(entry.get("required", True)),
                "used_by": entry.get("used_by") or entry.get("purpose"),
                "notes": entry.get("notes"),
            })
    return out


def build_snapshot() -> dict[str, Any]:
    return {
        "repo_root": str(_REPO),
        "archs": snapshot_archs(),
        "detector": snapshot_detector_keys(),
        "node_packs": snapshot_node_packs(),
    }


def diff_snapshots(prior: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    def _arch_keys(s: dict[str, Any]) -> set[str]:
        return {a["key"] for a in s.get("archs", [])}
    prior_keys = _arch_keys(prior)
    current_keys = _arch_keys(current)
    added = sorted(current_keys - prior_keys)
    removed = sorted(prior_keys - current_keys)
    prior_reg = {a["key"]: a.get("registered") for a in prior.get("archs", [])}
    promoted, demoted = [], []
    for a in current.get("archs", []):
        k = a["key"]
        if k in prior_reg and prior_reg[k] != a.get("registered"):
            (promoted if a.get("registered") else demoted).append(k)
    still_stubs = sorted(current.get("detector", {}).get("detector_keys_unpromoted_stubs", []))
    return {
        "arch_keys_added": added,
        "arch_keys_removed": removed,
        "arch_keys_promoted_to_registered": sorted(promoted),
        "arch_keys_demoted_from_registered": sorted(demoted),
        "detector_stubs_still_unpromoted": still_stubs,
    }


def _to_yaml_block(obj: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return pad + "{}\n"
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(_to_yaml_block(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {json.dumps(v)}")
        return "\n".join(lines) + "\n"
    if isinstance(obj, list):
        if not obj:
            return pad + "[]\n"
        lines = []
        for item in obj:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_to_yaml_block(item, indent + 1))
            else:
                lines.append(f"{pad}- {json.dumps(item)}")
        return "\n".join(lines) + "\n"
    return pad + json.dumps(obj) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yaml", action="store_true", help="emit YAML instead of JSON")
    ap.add_argument("--diff", metavar="PRIOR_JSON", help="diff against a prior snapshot JSON file")
    ap.add_argument("--out", metavar="PATH", help="write to file instead of stdout")
    args = ap.parse_args()

    current = build_snapshot()

    if args.diff:
        prior_path = Path(args.diff)
        if not prior_path.exists():
            print(f"prior snapshot not found: {prior_path}", file=sys.stderr)
            return 2
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        payload: dict[str, Any] = diff_snapshots(prior, current)
    else:
        payload = current

    text = _to_yaml_block(payload) if args.yaml else json.dumps(payload, indent=2, sort_keys=True) + "\n"

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
