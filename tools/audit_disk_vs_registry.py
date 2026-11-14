#!/usr/bin/env python3
"""Audit a ComfyUI models directory against spellcaster's architecture registry.

Named in the Tier-3 queues of the 2026-09-22 and 2026-10-16 ecosystem
digests as the missing tool behind the "which weights can we retire?"
question — written here as a Tier-1 drop by the 2026-11-14 digest.

What it does
------------

1. Loads ``spellcaster_core.architectures`` and extracts, per
   ``registered=True`` arch:
     * the ``key`` (e.g. ``flux2klein``)
     * ``lora_prefixes`` (where under ``loras/`` LoRAs for this arch live)
     * the explicit weight filenames declared in ``extra`` — ``clip_name``,
       ``clip_name1``, ``clip_name2``, ``vae_name``, ``unet_name``
2. Walks a ComfyUI models directory (``--models-dir`` or the
   ``SPELLCASTER_COMFYUI_MODELS`` env var, default ``D:/LLM/ComfyUI/models``).
3. Classifies every ``.safetensors`` / ``.gguf`` / ``.pt`` / ``.ckpt`` /
   ``.bin`` file against the registry:
     * "declared"      — file matches an explicit ``extra.*_name``
     * "lora-matched"  — under ``loras/`` and prefixed by a known arch's
       ``lora_prefixes``
     * "unknown"       — nothing claims it; candidate for retirement review
4. Prints a report with three sections, highest-signal first:
     * **UNKNOWN WEIGHTS** — paths with no claim; retirement candidates
     * **DUPLICATE SLOTS** — more than one file on disk claims the same
       declared slot (e.g. two different ``vae_name`` files for Klein)
     * **MISSING DECLARED** — an ``extra.*_name`` the registry asks for
       that isn't on disk at the expected path

The intent: give the operator a mechanical "what can I delete from
``D:\\LLM``?" answer without hand-grepping ``architectures.py``. Safe by
default — it ONLY reads. No file is ever moved, renamed, or removed.

Usage
-----

    # cloud/offline — show what the audit WOULD look for
    python tools/audit_disk_vs_registry.py --list-declared

    # on a fleet host with a real ComfyUI install
    python tools/audit_disk_vs_registry.py \\
        --models-dir D:/LLM/ComfyUI/models

    # JSON output (for a future Hermes consumer)
    python tools/audit_disk_vs_registry.py --models-dir ... --json

Exit codes: 0 always (this is an audit, not a gate).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make spellcaster_core importable from the ComfyUI side without a pip install.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "comfyui-spellcaster"))

from spellcaster_core.architectures import ARCHITECTURES  # noqa: E402

_WEIGHT_EXTS = {".safetensors", ".gguf", ".pt", ".ckpt", ".bin"}
_EXTRA_NAME_KEYS = ("clip_name", "clip_name1", "clip_name2", "vae_name", "unet_name")


def _collect_registry() -> dict[str, dict]:
    """Per registered arch: declared filenames + lora prefixes."""
    out: dict[str, dict] = {}
    for key, arch in ARCHITECTURES.items():
        if not arch.registered:
            continue
        declared: list[str] = []
        extra = getattr(arch, "extra", {}) or {}
        for k in _EXTRA_NAME_KEYS:
            v = extra.get(k)
            if isinstance(v, str) and v:
                # normalise Windows backslashes so path matching is portable
                declared.append(v.replace("\\", "/").lstrip("./"))
        lora_prefixes = [
            p.replace("\\", "/").rstrip("/") + "/"
            for p in (getattr(arch, "lora_prefixes", []) or [])
            if isinstance(p, str) and p
        ]
        out[key] = {"declared": declared, "lora_prefixes": lora_prefixes}
    return out


def _walk_weights(models_dir: Path) -> list[Path]:
    weights: list[Path] = []
    for root, _dirs, files in os.walk(models_dir):
        for name in files:
            if Path(name).suffix.lower() in _WEIGHT_EXTS:
                weights.append(Path(root) / name)
    return weights


def _classify(weights: list[Path], models_dir: Path, registry: dict[str, dict]):
    # Flatten every declared name across all arches, deduped — the same
    # name (e.g. "ae.safetensors", "flux2-vae.safetensors") is shared by
    # multiple arch registrations, so scanning per-arch would double-count.
    all_declared: set[str] = set()
    for info in registry.values():
        all_declared.update(info["declared"])
    by_declared: dict[str, list[Path]] = {}      # declared name -> [paths]
    lora_matched: dict[str, list[Path]] = {}     # arch_key -> [paths]
    unknown: list[Path] = []
    for w in weights:
        rel = w.relative_to(models_dir).as_posix()
        hit = False
        for dname in all_declared:
            # Path-component-boundary match: rel must equal dname, or end
            # with "/" + dname. Prevents "flux2-vae.safetensors" falsely
            # matching declared "ae.safetensors".
            if rel == dname or rel.endswith("/" + dname):
                by_declared.setdefault(dname, []).append(w)
                hit = True
                break
        if not hit and rel.startswith("loras/"):
            tail = rel[len("loras/"):]
            for arch_key, info in registry.items():
                for p in info["lora_prefixes"]:
                    if tail.startswith(p):
                        lora_matched.setdefault(arch_key, []).append(w)
                        hit = True
                        break
                if hit:
                    break
        if not hit:
            unknown.append(w)
    return by_declared, lora_matched, unknown


def _declared_expected_paths(registry: dict[str, dict]) -> set[str]:
    out: set[str] = set()
    for info in registry.values():
        for dname in info["declared"]:
            out.add(dname)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--models-dir",
        default=os.environ.get("SPELLCASTER_COMFYUI_MODELS", "D:/LLM/ComfyUI/models"),
        help="Path to a ComfyUI 'models' directory (default: env SPELLCASTER_COMFYUI_MODELS or D:/LLM/ComfyUI/models).",
    )
    ap.add_argument("--json", action="store_true", help="Emit structured JSON instead of a text report.")
    ap.add_argument(
        "--list-declared",
        action="store_true",
        help="Just print the declared-filename set the audit looks for; do not walk disk.",
    )
    args = ap.parse_args(argv)

    registry = _collect_registry()

    if args.list_declared:
        payload = {
            "registered_archs": sorted(registry),
            "declared_weight_filenames": sorted(_declared_expected_paths(registry)),
            "lora_prefixes": {k: v["lora_prefixes"] for k, v in registry.items() if v["lora_prefixes"]},
        }
        print(json.dumps(payload, indent=2))
        return 0

    models_dir = Path(args.models_dir)
    if not models_dir.is_dir():
        msg = f"models dir not found: {models_dir}"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            print(f"error: {msg}", file=sys.stderr)
            print("hint: pass --models-dir or set SPELLCASTER_COMFYUI_MODELS.", file=sys.stderr)
        return 0

    weights = _walk_weights(models_dir)
    by_declared, lora_matched, unknown = _classify(weights, models_dir, registry)

    missing_declared = [
        d for d in sorted(_declared_expected_paths(registry))
        if d not in by_declared
    ]
    duplicate_slots = {d: [str(p) for p in ps] for d, ps in by_declared.items() if len(ps) > 1}

    if args.json:
        print(json.dumps({
            "models_dir": str(models_dir),
            "weight_count": len(weights),
            "unknown": [str(p) for p in unknown],
            "duplicate_slots": duplicate_slots,
            "missing_declared": missing_declared,
            "lora_matched": {k: [str(p) for p in ps] for k, ps in lora_matched.items()},
        }, indent=2))
        return 0

    print(f"audit_disk_vs_registry: {len(weights)} weight files under {models_dir}")
    print(f"  registered archs: {len(registry)}")
    print()
    print(f"UNKNOWN WEIGHTS ({len(unknown)}) — nothing in the registry claims these:")
    for p in unknown:
        print(f"  {p.relative_to(models_dir).as_posix()}")
    print()
    print(f"DUPLICATE SLOTS ({len(duplicate_slots)}) — >1 file on disk for one declared name:")
    for dname, paths in sorted(duplicate_slots.items()):
        print(f"  {dname}:")
        for p in paths:
            print(f"    {p}")
    print()
    print(f"MISSING DECLARED ({len(missing_declared)}) — in registry, not on disk:")
    for d in missing_declared:
        print(f"  {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
