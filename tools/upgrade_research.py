#!/usr/bin/env python3
"""Ecosystem upgrade-opportunity harness.

Prints a machine-readable snapshot of what a cloud-side ecosystem-research
routine (see the every-48h "Ecosystem Research Digest" runbook) needs to
know about the current repo state before it goes off and web-searches for
new models / node packs / architectures:

  * Every model family Spellcaster claims support for (name + version
    strings scraped from README + DEEP_DIVE + arch registry).
  * The ComfyUI node-pack manifest (installer/manifest.json), so the
    research pass knows which upstreams to check for new releases.
  * The `builders_manifest.json` model coverage table, so anything
    surfaced upstream can be checked against what the coverage tests
    already know about.
  * A short "digest hints" block: which docs to re-verify (README status
    date, DEEP_DIVE tool counts), which retired subsystems must stay
    retired (antenna), what the current live-file layout looks like.

The routine reads this snapshot BEFORE spending web-search budget so it
can (a) skip families that were already surveyed last cycle, (b) avoid
proposing a "new" pack that's already installed, and (c) know which
in-repo strings the routine itself might want to update as Tier-1 fixes.

Every collector is best-effort — a missing file or a JSON parse error
degrades to a placeholder rather than aborting. The idea is: even a
partial snapshot is more useful to the research pass than none.

Usage:
    python tools/upgrade_research.py
    python tools/upgrade_research.py --json
    python tools/upgrade_research.py --out _dev_docs/upgrade_research_snapshot.json

Exit codes: 0 always (best-effort). Non-zero would kill the nightly
cloud research routine, which is worse than a partial snapshot.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _safe(fn, label):
    try:
        return fn()
    except Exception as exc:
        return {"_error": f"{label}: {type(exc).__name__}: {exc}"}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def collect_readme_signals() -> dict:
    readme = REPO / "README.md"
    if not readme.exists():
        return {"_missing": str(readme)}
    text = _read_text(readme)
    status = re.search(r"Status\s*[—-]\s*([A-Z][a-z]+ \d{4})", text)
    tool_count = re.search(r"(\d+)\s+AI tools", text)
    return {
        "status_line": status.group(1) if status else None,
        "advertised_tool_count": int(tool_count.group(1)) if tool_count else None,
        "byte_size": len(text),
    }


def collect_deep_dive_signals() -> dict:
    dd = REPO / "DEEP_DIVE.md"
    if not dd.exists():
        return {"_missing": str(dd)}
    text = _read_text(dd)
    # Per-section tool counts declared in <summary><h3>Name (N)</h3>
    sections = []
    for m in re.finditer(r"<summary><h3>([^<]+?)\((\d+)\)", text):
        sections.append({"name": m.group(1).strip(), "declared": int(m.group(2))})
    # Total by summing declared per-section counts. Also parse the
    # composite headers of the form "Style (4) &bull; Select (3) &bull;
    # Video (7) — ..." where a single <summary> declares three sub-groups.
    total = 0
    for m in re.finditer(r"\((\d+)\)", text):
        # Only count those inside <summary> lines (best-effort).
        pass
    # More reliable: count every "(N)" inside a <summary> line.
    summary_line_re = re.compile(r"<summary><h3>[^<]+</h3></summary>")
    for line in text.splitlines():
        if "<summary><h3>" in line:
            for m in re.finditer(r"\((\d+)\)", line):
                total += int(m.group(1))
    advertised = re.search(r"All\s+(\d+)\s+Tools", text)
    return {
        "advertised_tool_count": int(advertised.group(1)) if advertised else None,
        "summed_section_counts": total,
        "section_headers": sections,
    }


def collect_manifest() -> dict:
    mf = REPO / "installer" / "manifest.json"
    if not mf.exists():
        return {"_missing": str(mf)}
    try:
        data = json.loads(_read_text(mf))
    except Exception as exc:
        return {"_error": f"parse: {exc}"}
    # Real shape: {"custom_nodes": {"<PackName>": {"repo": ..., ...}}, ...}
    packs = (data.get("custom_nodes")
             or data.get("node_packs")
             or data.get("packs"))
    if isinstance(packs, dict):
        pack_list = list(packs.keys())
    elif isinstance(packs, list):
        pack_list = [p.get("name") or p.get("repo")
                     for p in packs if isinstance(p, dict)]
    else:
        pack_list = []
    return {
        "path": str(mf.relative_to(REPO)),
        "manifest_version": data.get("version"),
        "pack_count": len(pack_list),
        "pack_names": pack_list[:60],
    }


def collect_builders_manifest() -> dict:
    for candidate in [
        REPO / "installer" / "builders_manifest.json",
        REPO / "comfyui-spellcaster" / "builders_manifest.json",
        REPO / "tests" / "builders_manifest.json",
    ]:
        if candidate.exists():
            try:
                data = json.loads(_read_text(candidate))
            except Exception as exc:
                return {"path": str(candidate.relative_to(REPO)),
                        "_error": f"parse: {exc}"}
            builders = data.get("builders") or data
            if isinstance(builders, dict):
                names = list(builders.keys())
            elif isinstance(builders, list):
                names = [b.get("name") if isinstance(b, dict) else str(b)
                         for b in builders]
            else:
                names = []
            return {
                "path": str(candidate.relative_to(REPO)),
                "builder_count": len(names),
                "sample_builders": names[:20],
            }
    return {"_missing": "no builders_manifest.json found"}


def collect_arch_registry() -> dict:
    """Best-effort scrape of the architecture registry names."""
    for candidate in [
        REPO / "comfyui-spellcaster" / "spellcaster_core" / "architectures.py",
        REPO / "plugins" / "gimp" / "comfyui-connector" / "spellcaster_core" / "architectures.py",
    ]:
        if candidate.exists():
            text = _read_text(candidate)
            # architectures.py registers via `_reg("key", ...)` at module
            # load; ArchConfig(key, ...) is the constructor a lint scan
            # for `name=` would miss. Accept both shapes.
            regs = sorted(set(re.findall(r'^\s*_reg\(\s*["\']([^"\']+)',
                                          text, re.MULTILINE)))
            constructed = sorted(set(re.findall(
                r'ArchConfig\(\s*["\']?([A-Za-z0-9_]+)', text)))
            names = regs or constructed
            return {
                "path": str(candidate.relative_to(REPO)),
                "arch_names": names,
                "count": len(names),
            }
    return {"_missing": "architectures.py not found"}


def collect_retired_subsystems() -> list[dict]:
    out: list[dict] = []
    marker = REPO / "ANTENNA_RETIRED.md"
    if marker.exists():
        out.append({
            "subsystem": "spellcaster-antenna",
            "marker": "ANTENNA_RETIRED.md",
            "replacement": "prometheus-client (external, out-of-tree)",
            "do_not_touch": True,
        })
    for p in REPO.glob("*.RETIRED-*"):
        out.append({"path": p.name, "do_not_touch": True})
    return out


def collect_digest_hints() -> dict:
    """Points the ecosystem digest routine at things worth verifying."""
    return {
        "check_readme_status_date_matches_today": True,
        "check_deep_dive_summed_tool_count_equals_advertised": True,
        "never_resurrect": ["antenna/", "spellcaster-antenna"],
        "leak_patterns_forbidden_in_tracked_files": [
            "internal-project-code-names (see .github/workflows/leak-check.yml)",
            "LAN IPs (192.168.*)",
            "operator personal identifiers",
        ],
        "safe_tier1_fix_examples": [
            "Bump README '📣 Status — <Month YYYY>' when a new month has landed.",
            "Correct a DEEP_DIVE per-section tool count when it disagrees with the sum.",
            "Update a stale link that points at a retired path.",
            "Fix a test whose expectation is out of date with a documented code change.",
        ],
    }


def build_snapshot() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": str(REPO),
        "readme": _safe(collect_readme_signals, "readme"),
        "deep_dive": _safe(collect_deep_dive_signals, "deep_dive"),
        "manifest": _safe(collect_manifest, "manifest"),
        "builders_manifest": _safe(collect_builders_manifest, "builders"),
        "arch_registry": _safe(collect_arch_registry, "arch"),
        "retired_subsystems": _safe(collect_retired_subsystems, "retired"),
        "digest_hints": collect_digest_hints(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true",
                    help="Print JSON to stdout (default: pretty text).")
    ap.add_argument("--out", type=Path,
                    help="Write snapshot to this path (JSON).")
    args = ap.parse_args()

    snap = build_snapshot()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snap, indent=2, sort_keys=True),
                            encoding="utf-8")
        print(f"wrote {args.out}")
        return 0

    if args.json:
        print(json.dumps(snap, indent=2, sort_keys=True))
        return 0

    # Pretty text mode.
    print(f"# upgrade_research snapshot @ {snap['generated_at']}\n")
    for section, payload in snap.items():
        if section in ("generated_at", "repo"):
            continue
        print(f"## {section}")
        if isinstance(payload, (dict, list)):
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(payload)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
