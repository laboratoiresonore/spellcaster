#!/usr/bin/env python3
"""Spellcaster Install Validator — re-runnable standalone probe.

Submits tiny test workflows to the configured ComfyUI server (txt2img per
architecture, upscale, rembg, faceswap, video) and reports which features
work end-to-end. Use this any time the install state changes:

  - After adding new models / LoRAs to ComfyUI manually
  - After installing a new custom-node pack
  - To re-confirm a previously-broken feature now works
  - In CI / monitoring against a remote ComfyUI

Usage:
    python validate_install.py                              # auto-detect server
    python validate_install.py --server-url http://x:8188
    python validate_install.py --server-url http://x:8188 --json
    python validate_install.py --save-report path/to/out.json

Exit code: 0 if ALL probed capabilities pass, 1 if anything failed,
           2 if the server was unreachable, 3 if the diagnostic module
           couldn't be located.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Reuse install.py's module loader + settings reader — single source of truth.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import install  # noqa: E402  (import after sys.path edit is intentional)


DEFAULT_SERVER_URL = "http://127.0.0.1:8188"


def _read_server_from_settings() -> str | None:
    """Pull server URL from the master spellcaster_settings.json if present."""
    candidates = [
        SCRIPT_DIR / "spellcaster_settings.json",
        SCRIPT_DIR.parent / "spellcaster_settings.json",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            url = data.get("comfyui_url")
            if url:
                return url
        except Exception:  # noqa: BLE001
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:", 1)[1] if "Usage:" in __doc__ else "",
    )
    parser.add_argument("--server-url", metavar="URL", default="",
                        help=f"ComfyUI server URL (default: read from "
                             f"spellcaster_settings.json, then "
                             f"{DEFAULT_SERVER_URL})")
    parser.add_argument("--save-report", metavar="PATH", default="",
                        help="Write the JSON report to this path (in addition "
                             "to the default location next to the installer).")
    parser.add_argument("--json", action="store_true",
                        help="Print only the JSON report on stdout (suppress "
                             "human-readable progress).")
    parser.add_argument("--no-save", action="store_true",
                        help="Do not persist the report to disk; stdout only.")
    args = parser.parse_args()

    server_url = (args.server_url
                  or _read_server_from_settings()
                  or DEFAULT_SERVER_URL).rstrip("/")

    if not args.json:
        print(f"Spellcaster Install Validator")
        print(f"  Server: {server_url}")
        print()

    # Quick reachability test — fail fast with exit code 2 if the server is
    # down, so monitoring scripts can distinguish "broken" from "unreachable".
    import urllib.request
    try:
        with urllib.request.urlopen(f"{server_url}/system_stats", timeout=5) as r:
            r.read()
    except Exception as exc:  # noqa: BLE001
        msg = f"Server unreachable at {server_url}: {exc}"
        if args.json:
            print(json.dumps({"reachable": False, "error": str(exc),
                              "server_url": server_url}))
        else:
            print(f"  ERROR: {msg}")
        return 2

    # Suppress progress when --json is set (machine-readable mode)
    callback = None
    if args.json:
        callback = lambda _msg: None

    report = install._run_validation(
        server_url, callback=callback,
        save_report=not args.no_save)

    if report is None:
        if args.json:
            print(json.dumps({"reachable": True, "error": "diagnostic_failed",
                              "server_url": server_url}))
        else:
            print("\n  ERROR: Diagnostic could not complete "
                  "(module load failure or runtime crash — see messages above).")
        return 3

    # Optional: write to user-specified path too
    if args.save_report:
        try:
            Path(args.save_report).write_text(
                json.dumps(report, indent=2), encoding="utf-8")
            if not args.json:
                print(f"\n  Report saved: {args.save_report}")
        except Exception as exc:  # noqa: BLE001
            if not args.json:
                print(f"\n  WARNING: Could not write to {args.save_report}: {exc}")

    if args.json:
        print(json.dumps(report))
    else:
        broken = report.get("broken", [])
        working = report.get("working", [])
        print(f"\n  Working: {len(working)}")
        for cap in working:
            t = report.get("timings", {}).get(cap, 0)
            print(f"    + {cap}{f' ({t:.0f}s)' if t else ''}")
        if broken:
            print(f"\n  Broken: {len(broken)}")
            for entry in broken:
                if isinstance(entry, (list, tuple)):
                    cap, err = entry[0], entry[1] if len(entry) > 1 else ""
                else:
                    cap, err = str(entry), ""
                print(f"    - {cap}: {str(err)[:100]}")

    # Exit non-zero if anything broke — useful for CI / monitoring.
    return 1 if report.get("broken") else 0


if __name__ == "__main__":
    sys.exit(main())
