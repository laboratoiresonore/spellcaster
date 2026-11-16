#!/usr/bin/env python3
"""Audit ``ComfyUI/models/*`` on the fleet against the fully-registered
arches in ``architectures.py`` — find weights we still host for arches
that have been superseded (candidates for retirement) and flag arches
that are ``registered=True`` but have no matching weights on disk.

This exists because the 48h ecosystem digest's Tier-3 queue keeps
proposing fleet downloads of newer arches (Flux-3-Klein, LTX-2.5,
Qwen-Image-2.1, HyperFlow-H3-Flash, …) one wave at a time, but there
is no corresponding mechanical sweep to retire what those replace.
Over a few digest cycles that means ``D:\\LLM\\ComfyUI\\models`` grows
without bound while the operator has no at-a-glance view of what is
still earning its disk slot. The 2026-09-22 and 2026-10-16 digests
filed this tool as a Tier-1 drafting candidate for a future run. This
is that draft.

What it DOES not do
-------------------
This script does **not** delete or move anything. It is read-only and
emits a human-readable + a machine-readable report. The operator (or a
future Hermes/Prometheus local process) applies the retirement decisions.

Design
------
Read-only on both sides:

  * Registry side — parse ``comfyui-spellcaster/spellcaster_core/architectures.py``
    via AST (no runtime import; avoids pulling in ComfyUI-side deps) and
    build the set of ``registered=True`` arch ids. Fall back to
    ``registered=True`` implicitly when the kwarg is omitted, matching the
    ``ArchConfig.__init__`` default at ``architectures.py:186``.

  * Disk side — walk a configurable ``ComfyUI/models`` root (default
    ``D:\\LLM\\ComfyUI\\models`` to match the operator's Windows fleet
    layout; overridable via ``--models-dir``) and bucket every
    ``*.safetensors``, ``*.gguf``, ``*.ckpt``, ``*.pt``, ``*.pth`` file
    under its parent directory's name. The classifier is intentionally
    dumb — directory name match. Spellcaster operators keep a one-arch-
    per-subdirectory convention (``models/checkpoints/flux-2-klein/…``,
    ``models/unet/Qwen-Image-2.1/…``) so the heuristic works without
    reading weight headers.

Three output buckets
--------------------
  1. ``unmatched_on_disk``   — weights whose directory name has no
     obvious match in the registered arch id set. Could be: a retired
     arch, a weights folder named differently from its arch id, or a
     node pack's own weights (clip, vae, controlnet). Operator decides.
  2. ``missing_from_disk``   — arch ids registered as ``True`` with NO
     matching directory on disk. Could be: a newly-registered arch whose
     weights haven't landed yet (``flux3klein``, ``minimax_h3``,
     ``longcat``, ``qwen_image`` as of 2026-11-16), or a fleet host that
     lost its weights folder.
  3. ``duplicate_weights``   — the same arch id directory holding more
     than one distinct checkpoint-shaped file (e.g. ``flux-2-klein/``
     with both ``flux-2-klein-fp16.safetensors`` AND
     ``flux-2-klein-fp8.safetensors``). Not inherently bad — quant
     variants are legitimate — but worth flagging so the operator can
     confirm nothing is orphaned.

Usage
-----

    python tools/audit_disk_vs_registry.py \\
        --models-dir "D:\\LLM\\ComfyUI\\models"

    python tools/audit_disk_vs_registry.py --dry-run
        # No --models-dir needed; emits report shape against the
        # registry alone so CI can at least exercise the registry
        # parse. Every disk-side bucket is empty.

    python tools/audit_disk_vs_registry.py \\
        --models-dir "/mnt/spark1/ComfyUI/models" --json out.json

Exit codes
----------
  0  clean sweep — every registered arch has weights, no unmatched dirs
  1  at least one non-empty bucket (follow-up for the operator)
  2  registry parse failed (architectures.py not found or malformed)

Nothing is mutated; a retirement proposal is still a human call.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DEFAULT_ARCH_PATH = _REPO / "comfyui-spellcaster" / "spellcaster_core" / "architectures.py"
_DEFAULT_MODELS_DIR = Path(r"D:\LLM\ComfyUI\models")
_WEIGHT_SUFFIXES = {".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".sft"}


@dataclass
class ArchEntry:
    name: str
    registered: bool
    line: int


@dataclass
class DiskEntry:
    arch_dir: str
    files: list[str] = field(default_factory=list)
    total_bytes: int = 0


@dataclass
class AuditReport:
    models_dir: str
    arch_path: str
    registered_arches: list[str] = field(default_factory=list)
    stub_arches: list[str] = field(default_factory=list)
    unmatched_on_disk: list[DiskEntry] = field(default_factory=list)
    missing_from_disk: list[str] = field(default_factory=list)
    duplicate_weights: list[DiskEntry] = field(default_factory=list)
    matched: list[DiskEntry] = field(default_factory=list)


def parse_registry(arch_path: Path) -> list[ArchEntry]:
    """Pull every ``_reg("<name>", ..., registered=<bool>)`` from architectures.py.

    We walk the AST rather than regex-scraping so comments / strings
    containing the literal ``_reg(`` don't trip the counter. Each
    ``_reg`` call is a top-level ``Expr``/``Call`` whose first arg is
    the arch name string literal; the ``registered`` kwarg is explicit
    on every current entry but defaults to True per the ArchConfig
    constructor at ``architectures.py:186``, so a missing kwarg means
    fully-registered.
    """
    tree = ast.parse(arch_path.read_text(encoding="utf-8"))
    out: list[ArchEntry] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == "_reg"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        registered = True
        for kw in node.keywords:
            if kw.arg == "registered" and isinstance(kw.value, ast.Constant):
                registered = bool(kw.value.value)
        out.append(ArchEntry(name=first.value, registered=registered,
                              line=getattr(node, "lineno", 0)))
    return out


def _name_match(arch: str, dir_name: str) -> bool:
    """Loose string match between an arch id and a weights directory name.

    The operator's convention is informal — ``flux2klein`` can live
    under ``flux-2-klein``, ``flux2-klein``, ``FLUX.2-Klein``, or
    ``black-forest-labs/flux-2-klein``. We normalise both sides to
    lowercase with non-alnum stripped and require that the arch id be
    a substring of the directory name (one-directional). Going the
    other direction would mis-match a bare ``sdxl`` directory to the
    longer ``sdxl_turbo`` arch id. A directory named ``sdxl-turbo-v2``
    is still a substring hit for BOTH ``sdxl`` and ``sdxl_turbo``;
    the caller's longest-arch-first scan picks ``sdxl_turbo``, which
    is the right call.
    """
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    a = norm(arch)
    d = norm(dir_name)
    if not a or not d:
        return False
    return a in d


def scan_disk(models_dir: Path) -> list[DiskEntry]:
    """Bucket weight-shaped files under ``models_dir`` by their
    immediate parent directory. One DiskEntry per leaf directory that
    holds at least one weight file. Hidden dirs (`.git`, `__pycache__`)
    are skipped. Symlinks are followed once — cycles produce a warning
    on stderr and are then skipped."""
    seen: set[Path] = set()
    buckets: dict[str, DiskEntry] = {}
    if not models_dir.exists():
        return []

    for p in models_dir.rglob("*"):
        try:
            real = p.resolve(strict=False)
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        if not p.is_file():
            continue
        if p.suffix.lower() not in _WEIGHT_SUFFIXES:
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in p.parts):
            continue
        parent = p.parent.name
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        entry = buckets.setdefault(parent, DiskEntry(arch_dir=parent))
        entry.files.append(p.name)
        entry.total_bytes += size

    return sorted(buckets.values(), key=lambda e: e.arch_dir.lower())


def classify(entries: list[ArchEntry], disk: list[DiskEntry]) -> AuditReport:
    full = [e.name for e in entries if e.registered]
    stub = [e.name for e in entries if not e.registered]

    # Assign each disk bucket to the longest arch name that matches it;
    # short-name arches don't steal a directory that a more-specific
    # name claims (sdxl vs sdxl_turbo for a "sdxl-turbo-v2" folder).
    full_sorted = sorted(full, key=len, reverse=True)
    matched_arches: set[str] = set()
    matched_entries: list[DiskEntry] = []
    unmatched: list[DiskEntry] = []
    for d in disk:
        hit = None
        for a in full_sorted:
            if _name_match(a, d.arch_dir):
                hit = a
                break
        if hit is None:
            unmatched.append(d)
        else:
            matched_arches.add(hit)
            matched_entries.append(d)

    missing = [a for a in full if a not in matched_arches]

    # Duplicate flag: the same arch dir holds >1 weight-shaped file.
    # Quant variants are legitimate; this is a signal, not an alarm.
    dupes = [d for d in matched_entries if len(d.files) > 1]

    return AuditReport(
        models_dir="",  # filled by caller
        arch_path="",   # filled by caller
        registered_arches=sorted(full),
        stub_arches=sorted(stub),
        unmatched_on_disk=sorted(unmatched, key=lambda d: d.arch_dir.lower()),
        missing_from_disk=sorted(missing),
        duplicate_weights=sorted(dupes, key=lambda d: d.arch_dir.lower()),
        matched=sorted(matched_entries, key=lambda d: d.arch_dir.lower()),
    )


def render_md(r: AuditReport) -> str:
    lines = [
        "# Disk vs registry audit",
        "",
        f"- Models root: `{r.models_dir}`",
        f"- Registry:    `{r.arch_path}`",
        f"- Registered:  {len(r.registered_arches)}  "
        f"(stubs: {len(r.stub_arches)})",
        f"- On-disk dirs matched:   {len(r.matched)}",
        f"- Missing from disk:      {len(r.missing_from_disk)}",
        f"- Unmatched on disk:      {len(r.unmatched_on_disk)}",
        f"- Duplicate-weight dirs:  {len(r.duplicate_weights)}",
        "",
    ]
    if r.missing_from_disk:
        lines += ["## Registered but not on disk",
                  "",
                  "_Candidates for the operator's next download pass._",
                  ""]
        for name in r.missing_from_disk:
            lines.append(f"- `{name}`")
        lines.append("")
    if r.unmatched_on_disk:
        lines += ["## On disk but not matched to a registered arch",
                  "",
                  "_Candidates for retirement, OR a rename to match an "
                  "arch id, OR adapter / clip / vae weights that "
                  "legitimately live outside the arch set._",
                  ""]
        for d in r.unmatched_on_disk:
            gb = d.total_bytes / 1e9
            lines.append(f"- `{d.arch_dir}` — {len(d.files)} file(s), "
                         f"{gb:.2f} GB")
        lines.append("")
    if r.duplicate_weights:
        lines += ["## Dirs with more than one weight file",
                  "",
                  "_Expected for quant variants (fp16/fp8/gguf). Review "
                  "for orphaned pre-upgrade checkpoints._",
                  ""]
        for d in r.duplicate_weights:
            gb = d.total_bytes / 1e9
            lines.append(f"- `{d.arch_dir}` — {len(d.files)} files, "
                         f"{gb:.2f} GB")
            for f in d.files[:6]:
                lines.append(f"    - `{f}`")
            if len(d.files) > 6:
                lines.append(f"    - … and {len(d.files) - 6} more")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--models-dir", type=Path, default=_DEFAULT_MODELS_DIR,
                   help="ComfyUI/models root (default: %(default)s)")
    p.add_argument("--arch-path", type=Path, default=_DEFAULT_ARCH_PATH,
                   help="architectures.py path (default: %(default)s)")
    p.add_argument("--json", type=Path, default=None,
                   help="Write machine-readable report to this file")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip disk scan; emit registry-only report shape")
    args = p.parse_args(argv)

    if not args.arch_path.exists():
        print(f"error: {args.arch_path} not found", file=sys.stderr)
        return 2
    try:
        entries = parse_registry(args.arch_path)
    except SyntaxError as exc:
        print(f"error: registry parse failed: {exc}", file=sys.stderr)
        return 2

    disk: list[DiskEntry] = []
    if not args.dry_run:
        disk = scan_disk(args.models_dir)

    report = classify(entries, disk)
    report.models_dir = str(args.models_dir) + (" (dry-run)" if args.dry_run else "")
    report.arch_path = str(args.arch_path)

    print(render_md(report))
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(asdict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n(wrote JSON report to {args.json})", file=sys.stderr)

    if args.dry_run:
        # No real disk scan — every arch is trivially "missing". The
        # dry-run pass is a schema smoke test, not a sweep, so don't
        # claim a finding.
        return 0
    non_empty = (report.missing_from_disk or report.unmatched_on_disk
                 or report.duplicate_weights)
    return 1 if non_empty else 0


if __name__ == "__main__":
    sys.exit(main())
