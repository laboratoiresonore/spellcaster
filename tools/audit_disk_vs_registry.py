#!/usr/bin/env python3
"""Audit on-disk model weights against the architecture registry.

Named in the 2026-09-22 + 2026-10-16 ecosystem digests' Tier-3 queues
as the mechanical answer to "if LTX-2.5 replaces LTXV-2.3 and Flux-3-Klein
replaces Flux-2-Klein, which weights on D:\\LLM are retirable?". The
10-16 digest filed it as a drafting candidate for a future Tier-1; this
is that draft.

What it does
------------
1. Imports ``spellcaster_core.architectures.ARCHITECTURES`` (via the
   same conftest-style sys.path shim used by the other tools in this
   folder — plugins/gimp/comfyui-connector/spellcaster_core is the
   authoritative mirror).
2. For every ``registered=True`` ArchConfig, pulls the referenced
   weight filenames from ``extra`` (``vae_name``, ``clip_name``,
   ``clip_name1``, ``clip_name2``, ``unet_name``, ``model_name``,
   ``audio_vae_name``, and the list ``clip_fallbacks``).
3. Walks the ComfyUI model root (``--models-dir``, default
   ``D:\\LLM\\ComfyUI\\models`` on Windows, ``~/.cache/comfyui/models``
   otherwise) and classifies every ``.safetensors`` / ``.gguf`` /
   ``.ckpt`` / ``.pt`` it finds under there.
4. Prints a three-section report:
     - ``[MISSING]`` — registered arch references a file we did not find.
     - ``[MATCHED]`` — a weight on disk is referenced by at least one
       registered arch. (Default: suppressed; pass ``--show-matched``.)
     - ``[ORPHAN]`` — a weight on disk is NOT referenced by any
       registered arch (candidate for retirement to cold storage, OR a
       dependency the registry does not yet declare).

Design notes
------------
- READ-ONLY. Never deletes, moves, or renames. Operator reads the
  ``[ORPHAN]`` section and decides.
- Fuzzy-match: ``extra`` filenames can be prefixed with a subfolder
  (``"MiniMax-H3/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"``).
  We match on the *basename* against the walked file's basename, so a
  weight at any depth under ``--models-dir`` counts as present.
- The tool runs on a fleet host (sandbox has no D:\\LLM access).
  ``--self-test`` runs the matching logic against a synthetic tempdir
  so it is still exercisable from the cloud.
- Weight extensions tracked: ``.safetensors`` ``.gguf`` ``.ckpt`` ``.pt``
  ``.bin``. Everything else under ``--models-dir`` is ignored. Config
  JSONs / tokenizer vocabs / etc. aren't "weights" to retire.

Exit codes
----------
    0 — audit complete, no MISSING entries
    1 — audit complete, at least one MISSING entry
    2 — tool error (models-dir not found, registry import failed)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable

_REPO = Path(__file__).resolve().parent.parent

# Match conftest.py: the authoritative spellcaster_core lives under
# plugins/gimp/comfyui-connector/. Keep this one path, not three.
_CORE_PARENT = _REPO / "plugins" / "gimp" / "comfyui-connector"
if _CORE_PARENT.is_dir() and str(_CORE_PARENT) not in sys.path:
    sys.path.insert(0, str(_CORE_PARENT))

_WEIGHT_EXTS = frozenset({".safetensors", ".gguf", ".ckpt", ".pt", ".bin"})

# Which keys inside ArchConfig.extra point at individual weight files.
_SINGLE_WEIGHT_KEYS = (
    "vae_name", "clip_name", "clip_name1", "clip_name2",
    "unet_name", "model_name", "audio_vae_name",
)
# Which keys inside ArchConfig.extra point at a LIST of alt weight files.
_LIST_WEIGHT_KEYS = ("clip_fallbacks",)


def _registry_expected_files() -> dict[str, list[str]]:
    """Return {arch_key: [basename, ...]} for every registered=True arch.

    Only ``registered=True`` entries count — stubs are detection-only
    placeholders with no declared weights.
    """
    from spellcaster_core.architectures import ARCHITECTURES  # noqa: E402
    out: dict[str, list[str]] = {}
    for key, cfg in ARCHITECTURES.items():
        if not getattr(cfg, "registered", True):
            continue
        files: list[str] = []
        extra = getattr(cfg, "extra", {}) or {}
        for k in _SINGLE_WEIGHT_KEYS:
            v = extra.get(k)
            if isinstance(v, str) and v.strip():
                files.append(os.path.basename(v.strip()))
        for k in _LIST_WEIGHT_KEYS:
            lst = extra.get(k)
            if isinstance(lst, (list, tuple)):
                for v in lst:
                    if isinstance(v, str) and v.strip():
                        files.append(os.path.basename(v.strip()))
        if files:
            out[key] = files
    return out


def _walk_weights(models_dir: Path) -> dict[str, list[Path]]:
    """Return {basename: [path, ...]} for every weight-ext file under models_dir.

    A single basename can map to several paths (same filename under
    different subfolders — e.g. ``ae.safetensors`` under both ``vae/``
    and ``flux1/``). Caller merges duplicates in the orphan report.
    """
    found: dict[str, list[Path]] = {}
    if not models_dir.is_dir():
        return found
    for root, _dirs, files in os.walk(models_dir):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in _WEIGHT_EXTS:
                found.setdefault(fn, []).append(Path(root) / fn)
    return found


def audit(models_dir: Path, expected: dict[str, list[str]] | None = None,
          found: dict[str, list[Path]] | None = None) -> dict:
    """Core auditing logic. Pure function so --self-test can inject
    synthetic ``expected`` / ``found`` without touching the real registry
    or filesystem.

    Returns a dict with three lists:
      - "missing": [(arch_key, basename), ...]
      - "matched": [(arch_key, basename, path), ...]
      - "orphan":  [path, ...]
    """
    if expected is None:
        expected = _registry_expected_files()
    if found is None:
        found = _walk_weights(models_dir)

    # Set of all basenames the registry declares interest in
    referenced_basenames: set[str] = set()
    for files in expected.values():
        referenced_basenames.update(files)

    missing: list[tuple[str, str]] = []
    matched: list[tuple[str, str, Path]] = []
    for arch_key, files in expected.items():
        for basename in files:
            paths = found.get(basename, [])
            if not paths:
                missing.append((arch_key, basename))
            else:
                # Report the first disk path we saw for the match.
                matched.append((arch_key, basename, paths[0]))

    orphan: list[Path] = []
    for basename, paths in found.items():
        if basename not in referenced_basenames:
            orphan.extend(paths)

    return {"missing": missing, "matched": matched, "orphan": orphan}


def _default_models_dir() -> Path:
    """Guess a sensible default for ``--models-dir``.

    Windows: ``D:\\LLM\\ComfyUI\\models`` matches the fleet convention
    the Tier-3 queue uses. Everywhere else (sandbox / Linux / mac):
    ``~/.cache/comfyui/models`` as a safe fallback that will not match
    anything on the cloud sandbox — audits of the real fleet pass
    ``--models-dir`` explicitly.
    """
    if sys.platform.startswith("win"):
        return Path(r"D:\LLM\ComfyUI\models")
    return Path.home() / ".cache" / "comfyui" / "models"


def _self_test() -> int:
    """Exercise the matching logic against a synthetic tempdir tree.

    Covers:
      - a MATCHED file (expected + on disk)
      - a MISSING file (expected but not on disk)
      - an ORPHAN file (on disk but no registry entry)
      - a subfolder-prefixed expected name (basename matching)
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "vae").mkdir()
        (root / "clip").mkdir()
        (root / "vae" / "ae.safetensors").write_text("stub")       # matched
        (root / "clip" / "qwen3vl_4b.safetensors").write_text("stub")  # matched (via subfolder-prefixed expected name)
        (root / "legacy_wan_1.0_vae.safetensors").write_text("stub")   # orphan
        # Note: "missing_from_disk.safetensors" is NOT created on disk.

        expected = {
            "fakearch": [
                "ae.safetensors",                 # matched: present at vae/
                "missing_from_disk.safetensors",  # missing
            ],
            "fakearch2": [
                # Simulates extra={"clip_name": "subdir/qwen3vl_4b.safetensors"}:
                # the registry helper already strips to basename before we see it.
                "qwen3vl_4b.safetensors",
            ],
        }
        found = _walk_weights(root)
        result = audit(root, expected=expected, found=found)

        failures = []
        if ("fakearch", "missing_from_disk.safetensors") not in result["missing"]:
            failures.append("missing path not surfaced")
        if len(result["matched"]) != 2:
            failures.append(f"expected 2 matched, got {len(result['matched'])}")
        matched_basenames = {m[1] for m in result["matched"]}
        if matched_basenames != {"ae.safetensors", "qwen3vl_4b.safetensors"}:
            failures.append(f"matched basenames wrong: {matched_basenames}")
        orphan_basenames = {p.name for p in result["orphan"]}
        if orphan_basenames != {"legacy_wan_1.0_vae.safetensors"}:
            failures.append(f"orphan basenames wrong: {orphan_basenames}")

        if failures:
            for f in failures:
                print(f"[FAIL] {f}", file=sys.stderr)
            return 1
        print("[OK] audit_disk_vs_registry --self-test: 4/4 cases passed")
        return 0


def _render(result: dict, models_dir: Path, show_matched: bool) -> list[str]:
    """Pretty-print the audit result for CLI consumption."""
    lines = [f"# audit_disk_vs_registry — {models_dir}", ""]
    lines.append(f"missing: {len(result['missing'])}  "
                 f"matched: {len(result['matched'])}  "
                 f"orphan: {len(result['orphan'])}")
    lines.append("")

    if result["missing"]:
        lines.append("[MISSING] — registered arch expects these files but they are not on disk:")
        for arch_key, basename in sorted(result["missing"]):
            lines.append(f"  - {arch_key}: {basename}")
        lines.append("")

    if show_matched and result["matched"]:
        lines.append("[MATCHED] — on-disk file is referenced by at least one registered arch:")
        for arch_key, basename, path in sorted(result["matched"]):
            lines.append(f"  - {arch_key}: {basename}   @ {path}")
        lines.append("")

    if result["orphan"]:
        lines.append("[ORPHAN] — on-disk weights with NO registry reference (candidates for retirement):")
        for path in sorted(result["orphan"]):
            lines.append(f"  - {path}")
        lines.append("")

    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models-dir", type=Path, default=_default_models_dir(),
                   help="ComfyUI models root to walk (default guesses from OS)")
    p.add_argument("--show-matched", action="store_true",
                   help="Also print the MATCHED section (long)")
    p.add_argument("--self-test", action="store_true",
                   help="Run the synthetic-tree test and exit (no filesystem walk)")
    args = p.parse_args(argv)

    if args.self_test:
        return _self_test()

    if not args.models_dir.is_dir():
        print(f"[ERROR] --models-dir does not exist: {args.models_dir}",
              file=sys.stderr)
        print("Pass --models-dir pointing at a ComfyUI models/ folder on this host,",
              file=sys.stderr)
        print("or run --self-test to exercise the audit logic without filesystem access.",
              file=sys.stderr)
        return 2

    try:
        expected = _registry_expected_files()
    except Exception as exc:  # noqa: BLE001 — bubble clean error, no stack
        print(f"[ERROR] could not import spellcaster_core.architectures: {exc}",
              file=sys.stderr)
        return 2

    found = _walk_weights(args.models_dir)
    result = audit(args.models_dir, expected=expected, found=found)
    for line in _render(result, args.models_dir, args.show_matched):
        print(line)

    return 1 if result["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
