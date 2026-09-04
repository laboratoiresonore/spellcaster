#!/usr/bin/env python3
"""Upgrade-research scaffold — enumerate installed archs + methods so the
every-48h cloud digest routine has a machine-readable snapshot to diff
against ecosystem releases.

The every-48h Ecosystem Research Digest routine references
``python tools/upgrade_research.py``. Prior runs degraded to web-only
research when this file was absent; this scaffold restores the
contract with a minimal, dependency-free surface:

    $ python tools/upgrade_research.py                 # human summary
    $ python tools/upgrade_research.py --json          # machine-readable
    $ python tools/upgrade_research.py --json --pretty
    $ python tools/upgrade_research.py --backends      # list backends
    $ python tools/upgrade_research.py --check         # exit 1 on drift

Backends implemented here (cloud-safe, no LAN reach):

* ``local_index`` — reads ``comfyui-spellcaster/spellcaster_core/
  lora_calibrations_sfw.json`` for the operator's known LoRA
  calibration table.
* ``arch_registry`` — enumerates every ``_reg("<key>", ...)`` in
  ``architectures.py`` so drift between the arch registry and the
  digest's claim of arch coverage is detectable.
* ``builders_manifest`` — reads
  ``comfyui-spellcaster/spellcaster_core/builders_manifest.json``
  when present. Reports total builder count and how many carry a
  resolved ``target_class`` (SSoT coverage metric).

Backends the routine's prompt mentions but that this scaffold does
NOT reach (they need LAN access the cloud sandbox lacks):

* ``comfy_manager`` — needs a local ComfyUI HTTP endpoint.
* ``local_llm`` — needs LM Studio / Ollama on the operator's fleet.
* ``civitai`` — deferred; may be implemented later once the routine
  has a public-cache-only path.

The routine's per-run digest is what actually publishes upgrade
candidates. This file only enumerates the baseline the digest
compares against.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE = REPO_ROOT / "comfyui-spellcaster" / "spellcaster_core"


# ── local_index ──────────────────────────────────────────────────────
def load_local_index():
    """Return the {arch: [lora, ...]} calibration table (may be empty)."""
    path = CORE / "lora_calibrations_sfw.json"
    if not path.is_file():
        return {"present": False, "loras": {}, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"present": True, "error": str(exc), "path": str(path)}
    return {
        "present": True,
        "schema_version": data.get("schema_version"),
        "loras": data.get("loras", {}),
        "lora_count": len(data.get("loras", {}) or {}),
        "path": str(path),
    }


# ── arch_registry ────────────────────────────────────────────────────
_REG_RE = re.compile(r'^_reg\(\s*"([^"]+)"', re.MULTILINE)


def load_arch_registry():
    """Return the list of arch keys currently registered."""
    path = CORE / "architectures.py"
    if not path.is_file():
        return {"present": False, "arches": [], "path": str(path)}
    text = path.read_text(encoding="utf-8")
    keys = _REG_RE.findall(text)
    return {
        "present": True,
        "arches": keys,
        "arch_count": len(keys),
        "path": str(path),
    }


# ── builders_manifest ────────────────────────────────────────────────
def load_builders_manifest():
    """Return builder count + target_class coverage."""
    path = CORE / "builders_manifest.json"
    if not path.is_file():
        return {"present": False, "builders": 0, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"present": True, "error": str(exc), "path": str(path)}
    if isinstance(data, list):
        builders = data
    else:
        # Canonical schema uses "methods"; older drafts used "builders".
        builders = data.get("methods") or data.get("builders") or []
    if isinstance(builders, dict):
        builders = list(builders.values())
    with_class = sum(
        1 for b in builders
        if isinstance(b, dict) and b.get("target_class")
    )
    return {
        "present": True,
        "builders": len(builders),
        "with_target_class": with_class,
        "coverage_pct": (
            round(100.0 * with_class / len(builders), 1)
            if builders else 0.0
        ),
        "path": str(path),
    }


# ── snapshot orchestration ───────────────────────────────────────────
BACKENDS = {
    "local_index": load_local_index,
    "arch_registry": load_arch_registry,
    "builders_manifest": load_builders_manifest,
}

DEFERRED_BACKENDS = ("comfy_manager", "local_llm", "civitai", "huggingface")


def snapshot():
    """Collect every reachable backend into one dict."""
    out = {"backends_reached": {}, "backends_deferred": list(DEFERRED_BACKENDS)}
    for name, fn in BACKENDS.items():
        try:
            out["backends_reached"][name] = fn()
        except Exception as exc:
            out["backends_reached"][name] = {"error": repr(exc)}
    return out


# ── CLI ──────────────────────────────────────────────────────────────
def _print_summary(snap):
    reached = snap.get("backends_reached", {})
    print("upgrade-research snapshot")
    print("=" * 48)

    ai = reached.get("arch_registry", {})
    if ai.get("present"):
        print(f"arch_registry: {ai.get('arch_count', 0)} architectures registered")
    else:
        print("arch_registry: NOT PRESENT")

    li = reached.get("local_index", {})
    if li.get("present"):
        print(
            f"local_index:   {li.get('lora_count', 0)} LoRA calibrations "
            f"(schema {li.get('schema_version', '?')})"
        )
    else:
        print("local_index:   NOT PRESENT")

    bm = reached.get("builders_manifest", {})
    if bm.get("present"):
        print(
            f"builders:      {bm.get('builders', 0)} total, "
            f"{bm.get('with_target_class', 0)} with target_class "
            f"({bm.get('coverage_pct', 0)}%)"
        )
    else:
        print("builders:      NOT PRESENT")

    print(f"deferred:      {', '.join(snap.get('backends_deferred', []))}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    ap.add_argument("--backends", action="store_true",
                    help="print reachable + deferred backend names, then exit")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any local backend is unreachable "
                         "(useful for CI to catch removed files)")
    args = ap.parse_args(argv)

    if args.backends:
        print("reachable: " + ", ".join(BACKENDS))
        print("deferred:  " + ", ".join(DEFERRED_BACKENDS))
        return 0

    snap = snapshot()

    if args.check:
        for name, result in snap["backends_reached"].items():
            if not result.get("present", True):
                print(f"FAIL: {name} not present ({result.get('path')})",
                      file=sys.stderr)
                return 1

    if args.json:
        indent = 2 if args.pretty else None
        json.dump(snap, sys.stdout, indent=indent, sort_keys=True)
        sys.stdout.write("\n")
    else:
        _print_summary(snap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
