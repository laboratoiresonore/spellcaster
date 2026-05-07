#!/usr/bin/env python3
"""ecosystem_doctor — cross-repo drift detector & syncer.

The Spellcaster ecosystem has multiple repos that must keep certain
files byte-identical (e.g. ``_DEV_HYGIENE.md`` across spellcaster,
spellcaster_NSFW, Voodoomancer, Laborantin, whimweaver). The existing
docs (``MIRROR_TARGETS.md``, ``_DEV_HYGIENE.md``) declare these
relationships in prose; this script makes them executable.

Per CLAUDE.md §13 (UPGRADE_PLAN_2026-05-06.md §13 ecosystem-update
architecture): the ecosystem deliberately rejects collapsing mirrors
into a single source. The "awake-is-fine" mantra (MIRROR_TARGETS.md
§90) prefers documented complexity over silent drift. This tool
operationalises that — declared mirrors are an executable contract
that CI can verify and ``--apply`` can heal.

Per-repo config: ``ecosystem.config.json`` at the repo root.

Schema:
    {
      "canonical": [
        {
          "source": "_DEV_HYGIENE.md",
          "mirrors": [
            "../Voodoomancer/_DEV_HYGIENE.md",
            "../spellcaster_NSFW/_DEV_HYGIENE.md",
            ...
          ],
          "verifier": "byte-identical",
          "notes": "Cross-ecosystem hygiene rules H1-H7."
        }
      ]
    }

Mirror paths are resolved relative to the repo root.

Usage:
    python scripts/ecosystem_doctor.py verify
    python scripts/ecosystem_doctor.py verify --json
    python scripts/ecosystem_doctor.py sync _DEV_HYGIENE.md          # dry-run
    python scripts/ecosystem_doctor.py sync _DEV_HYGIENE.md --apply  # write

Exit codes:
    0  no drift
    1  drift detected (verify) or sync needs --apply
    2  config / IO error

Lives in spellcaster repo as the canonical implementation; vendored
into other repos via git subtree once the API stabilises (master plan
§F.2 voodoo-core distribution model).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "ecosystem.config.json"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_config(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(
            f"ecosystem config not found: {path}\n"
            "Create one at the repo root with the schema in this file's "
            "module docstring.")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve(repo_root: Path, p: str) -> Path:
    """Resolve a mirror path: absolute → as-is, relative → repo-relative."""
    pp = Path(p)
    return pp if pp.is_absolute() else (repo_root / pp).resolve()


def _entry_status(repo_root: Path, entry: dict) -> dict:
    """Compute drift status for one canonical → mirrors entry."""
    src = _resolve(repo_root, entry["source"])
    if not src.is_file():
        return {
            "source": str(src),
            "exists": False,
            "drift": True,
            "mirrors": [],
            "error": f"canonical source missing: {src}",
        }
    src_sha = _sha256(src)
    mirrors = []
    drift = False
    for m in entry.get("mirrors", []):
        mp = _resolve(repo_root, m)
        if not mp.is_file():
            mirrors.append({
                "path": str(mp),
                "exists": False,
                "drift": True,
                "sha": None,
                "note": "mirror missing",
            })
            drift = True
            continue
        msha = _sha256(mp)
        d = (msha != src_sha)
        mirrors.append({
            "path": str(mp),
            "exists": True,
            "drift": d,
            "sha": msha,
            "note": "" if not d else "byte-mismatch with canonical",
        })
        if d:
            drift = True
    return {
        "source": str(src),
        "exists": True,
        "src_sha": src_sha,
        "drift": drift,
        "mirrors": mirrors,
        "verifier": entry.get("verifier", "byte-identical"),
        "notes": entry.get("notes", ""),
    }


def cmd_verify(args) -> int:
    config = _load_config(CONFIG_PATH)
    results = [_entry_status(REPO_ROOT, e) for e in config.get("canonical", [])]
    if args.json:
        print(json.dumps({"results": results}, indent=2))
        return 1 if any(r["drift"] for r in results) else 0

    print("=" * 64)
    print("ecosystem_doctor — drift report")
    print(f"  repo:    {REPO_ROOT}")
    print(f"  config:  {CONFIG_PATH.name}")
    print("=" * 64)
    any_drift = False
    for r in results:
        src_short = Path(r["source"]).name
        if not r["exists"]:
            print(f"\n  [MISSING] {src_short}")
            print(f"    {r.get('error', '?')}")
            any_drift = True
            continue
        m_total = len(r["mirrors"])
        m_drift = sum(1 for m in r["mirrors"] if m["drift"])
        if r["drift"]:
            any_drift = True
            print(f"\n  [DRIFT]   {src_short}  ({m_drift}/{m_total} mirrors out of sync)")
        else:
            print(f"\n  [SYNC]    {src_short}  ({m_total}/{m_total} mirrors byte-identical)")
        for m in r["mirrors"]:
            mark = "✗" if m["drift"] else "✓"
            print(f"    {mark} {m['path']}")
            if m["drift"]:
                print(f"      → {m['note']}")
        if r.get("notes"):
            print(f"    notes: {r['notes']}")
    print()
    if any_drift:
        print("Drift detected. Use 'sync <source>' to inspect, 'sync <source> --apply' to heal.")
        return 1
    print("All declared mirrors byte-identical.")
    return 0


def cmd_sync(args) -> int:
    config = _load_config(CONFIG_PATH)
    target = args.source
    matches = [e for e in config.get("canonical", [])
               if Path(e["source"]).name == target or e["source"] == target]
    if not matches:
        print(f"FATAL: no canonical entry matching '{target}' in config", file=sys.stderr)
        return 2
    if len(matches) > 1:
        print(f"WARN: {len(matches)} entries match '{target}'; processing all.")
    rc = 0
    for entry in matches:
        status = _entry_status(REPO_ROOT, entry)
        if not status["exists"]:
            print(f"  [SKIP] canonical missing: {status['source']}")
            rc = 1
            continue
        src = Path(status["source"])
        for m in status["mirrors"]:
            mp = Path(m["path"])
            if not m["drift"]:
                print(f"  [OK]   {mp}")
                continue
            if args.apply:
                try:
                    mp.parent.mkdir(parents=True, exist_ok=True)
                    mp.write_bytes(src.read_bytes())
                    print(f"  [SYNC] {mp}")
                except Exception as exc:
                    print(f"  [FAIL] {mp}: {exc}")
                    rc = 1
            else:
                print(f"  [WOULD] {mp} ({m['note']})")
                rc = 1
    if not args.apply and rc == 1:
        print("\nDry-run; pass --apply to write.")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(prog="ecosystem_doctor",
                                  description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp_verify = sub.add_parser("verify", help="report drift across declared mirrors")
    sp_verify.add_argument("--json", action="store_true",
                            help="emit JSON instead of human report")
    sp_verify.set_defaults(func=cmd_verify)

    sp_sync = sub.add_parser("sync", help="sync a canonical source to its mirrors")
    sp_sync.add_argument("source", help="filename of the canonical source (e.g. _DEV_HYGIENE.md)")
    sp_sync.add_argument("--apply", action="store_true",
                          help="actually copy bytes (default is dry-run)")
    sp_sync.set_defaults(func=cmd_sync)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
