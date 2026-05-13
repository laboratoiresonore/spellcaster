#!/usr/bin/env python3
"""Night maintenance — composite verification across the ecosystem.

Designed to be invoked by a Theo nightly cron (or a Voodoomaster
dev-endpoint heartbeat) so the codebase + servers are continuously
verified without operator action. Writes a dated report file the
next morning's claude session reads to know what changed.

Checks (all non-destructive — no writes outside the report file):

1. tests/mirror_drift.py            — 6-surface byte-identical invariant
2. tests/installer_audit.py         — installer functions vs live server
3. live ComfyUI capability shape    — node count, feature flags, license
4. extra_model_paths.yaml integrity — D: primary still has the expected dirs
5. Voodoomaster caps server health  — backend.state=ready, license valid
6. Recent error scan                — comfyui.log / launcher.log / dev_audit.log

Usage:
    python tests/night_maintenance.py
    python tests/night_maintenance.py --server http://<HOST>:8190 \\
                                       --caps   http://<HOST>:8191
    python tests/night_maintenance.py --report ~/.voodoomaster/night_report.md

Output:
    - Console summary (CI-friendly exit code: 0 all green, 1 any red)
    - Markdown report at --report path (default:
      ~/.voodoomaster/night_report_YYYYMMDD.md)

Per Laborantin-aware practice (CLAUDE.md): the local LLM on Theo (LM
Studio on :1234) can run this on a cron and the next claude session
finds the night-report file ready to read instead of re-discovering
everything from scratch.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

DEFAULT_SERVER = "http://192.168.86.28:8190"
DEFAULT_CAPS   = "http://192.168.86.28:8191"


def _default_report_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", Path.home()))
    else:
        base = Path.home()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return base / ".voodoomaster" / f"night_report_{stamp}.md"


def _http_json(url: str, timeout: float = 10.0) -> dict | None:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "spellcaster-night-maintenance",
                          "Connection": "close"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


# ─── Individual checks ────────────────────────────────────────────────────────

def check_mirror_drift() -> tuple[bool, list[str]]:
    """Wrapper around tests/mirror_drift.py."""
    p = subprocess.run(
        [sys.executable, str(HERE / "mirror_drift.py"), "--quiet"],
        capture_output=True, text=True, timeout=60)
    lines = (p.stdout + p.stderr).splitlines()
    ok = (p.returncode == 0)
    summary = "byte-identical" if ok else "DRIFT DETECTED"
    if not ok:
        # Surface the first few useful lines
        for ln in lines:
            if "✗" in ln or "DRIFT" in ln:
                summary += f"  · {ln.strip()}"
                break
    return ok, [f"mirror_drift: {summary}"]


def check_installer_audit(server: str) -> tuple[bool, list[str]]:
    """Wrapper around tests/installer_audit.py."""
    p = subprocess.run(
        [sys.executable, str(HERE / "installer_audit.py"),
         "--server", server],
        capture_output=True, text=True, timeout=120)
    ok = (p.returncode == 0)
    # Extract the PASS/FAIL/SKIP summary line
    summary_line = next(
        (ln for ln in p.stdout.splitlines()
         if "PASS" in ln and "/" in ln),
        "no summary line found")
    return ok, [f"installer_audit: {summary_line.strip()}"]


def check_capabilities(caps_url: str) -> tuple[bool, list[str]]:
    """Probe Voodoomaster caps server for the expected shape."""
    healthz = _http_json(f"{caps_url}/healthz", timeout=5)
    if not healthz:
        return False, [f"caps server {caps_url}: no response"]
    if not healthz.get("comfy_reachable"):
        return False, [f"caps server: comfy_reachable=False"]

    caps = _http_json(f"{caps_url}/v1/capabilities", timeout=30)
    if not caps:
        return False, ["caps payload: empty / failed"]

    issues = []
    nodes = caps.get("node_count", 0)
    if nodes < 6000:
        issues.append(f"node_count={nodes} (expected >= 6000)")
    flags = caps.get("feature_flags", {})
    expected_true = ["sam3", "klein_enhancer", "klein_identity",
                     "ltx_video", "wan_video", "depth_anything_v3",
                     "face_swap_reactor", "stable_avatar"]
    missing_flags = [f for f in expected_true if not flags.get(f)]
    if missing_flags:
        issues.append(f"feature flags missing: {missing_flags}")
    backend = caps.get("backend", {})
    if backend.get("state") != "ready":
        issues.append(f"backend.state={backend.get('state')!r} "
                      f"(expected 'ready')")
    license_info = caps.get("license", {})
    if not license_info.get("activated"):
        issues.append("license not activated")

    if issues:
        return False, ["capabilities:"] + [f"  · {x}" for x in issues]
    return True, [f"capabilities: {nodes} nodes, "
                  f"{len(flags)} flags all green, "
                  f"backend ready, license active"]


def check_extra_model_paths() -> tuple[bool, list[str]]:
    """Verify D: primary still has the expected model categories."""
    # Theo-specific layout: D:/AI/ComfyUI-models/<cat>/
    primary = Path("D:/AI/ComfyUI-models")
    if not primary.is_dir():
        return False, [f"primary model root missing: {primary}"]
    required_subdirs = ["checkpoints", "loras", "vae", "unet", "clip",
                         "controlnet", "sam3", "depthanything3",
                         "StableAvatar", "hyperswap"]
    missing = [d for d in required_subdirs if not (primary / d).is_dir()]
    if missing:
        return False, [f"D: model root missing: {missing}"]
    return True, [f"D: model root: {len(required_subdirs)} expected "
                  f"dirs all present"]


def check_log_errors() -> tuple[bool, list[str]]:
    """Scan recent Voodoomaster + ComfyUI logs for UNRECOVERED errors.

    The watchdog soft-crash + auto-restart flow tags both the crash
    detection AND the successful recovery — we only want to alert when
    a crash was NOT followed by a ``restart-ok`` within the same log
    window. Otherwise every transient ComfyUI accept-loop death (a
    routine occurrence under heavy IO load) flags as a failure even
    though the system self-healed.
    """
    log_dir = Path.home() / ".voodoomaster"
    if not log_dir.is_dir():
        return True, [f"log dir absent ({log_dir}) — skip"]
    findings = []
    for name in ("launcher.log", "comfyui.log"):
        p = log_dir / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tail = text.splitlines()[-200:]  # last 200 lines
        # Find the index of the latest "restart-ok" — any error event
        # BEFORE that has been resolved (the system recovered). Only
        # error events AFTER are unresolved and worth surfacing.
        last_ok_idx = -1
        for i, ln in enumerate(tail):
            if "restart-ok" in ln or "boot start" in ln:
                last_ok_idx = i
        unresolved = tail[last_ok_idx + 1:] if last_ok_idx >= 0 else tail
        err_lines = [ln for ln in unresolved
                     if any(kw in ln for kw in ("ERROR ", "Traceback",
                                                   "watchdog-gave-up",
                                                   "crashed-detected"))]
        if err_lines:
            findings.append(f"{name}: {len(err_lines)} unrecovered "
                           f"error(s) in last 200 — latest: "
                           f"{err_lines[-1].strip()[:160]}")
    if findings:
        return False, ["log scan:"] + [f"  · {x}" for x in findings]
    return True, ["log scan: no fresh errors in launcher.log / comfyui.log"]


# ─── Report writer ────────────────────────────────────────────────────────────

def write_report(path: Path, sections: list[tuple[str, bool, list[str]]],
                 server: str, caps_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"# Night maintenance report — {now}",
        "",
        f"- Server probed: `{server}`",
        f"- Caps probed:   `{caps_url}`",
        "",
        "## Summary",
        "",
    ]
    for name, ok, _ in sections:
        icon = "OK" if ok else "FAIL"
        lines.append(f"- `{name}`: **{icon}**")
    lines += ["", "## Details", ""]
    for name, ok, detail in sections:
        lines.append(f"### {name} — {'OK' if ok else 'FAIL'}")
        for d in detail:
            lines.append(f"- {d}")
        lines.append("")
    lines.append("---")
    lines.append("_Generated by `tests/night_maintenance.py`._")
    path.write_text("\n".join(lines), encoding="utf-8")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", default=DEFAULT_SERVER,
                    help="ComfyUI URL (default: %(default)s)")
    ap.add_argument("--caps", default=DEFAULT_CAPS,
                    help="Voodoomaster caps URL (default: %(default)s)")
    ap.add_argument("--report", default=str(_default_report_path()),
                    help="Markdown report path (default: per-day under "
                         "~/.voodoomaster/)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.quiet:
        print(f"Night maintenance — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
        print(f"  Server: {args.server}")
        print(f"  Caps:   {args.caps}")
        print(f"  Report: {args.report}")
        print()

    sections: list[tuple[str, bool, list[str]]] = []
    checks = [
        ("mirror-drift",     check_mirror_drift,    ()),
        ("installer-audit",  check_installer_audit, (args.server,)),
        ("capabilities",     check_capabilities,    (args.caps,)),
        ("model-paths",      check_extra_model_paths, ()),
        ("log-scan",         check_log_errors,      ()),
    ]
    for name, fn, fnargs in checks:
        try:
            ok, detail = fn(*fnargs)
        except Exception as e:  # noqa: BLE001 — each check is best-effort
            ok = False
            detail = [f"{type(e).__name__}: {e}"]
        sections.append((name, ok, detail))
        if not args.quiet:
            icon = "\033[92mOK  \033[0m" if ok else "\033[91mFAIL\033[0m"
            print(f"  [{icon}] {name}")
            for d in detail:
                print(f"         {d}")

    write_report(Path(args.report), sections, args.server, args.caps)
    if not args.quiet:
        print(f"\nReport written → {args.report}")

    fail_count = sum(1 for _, ok, _ in sections if not ok)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
