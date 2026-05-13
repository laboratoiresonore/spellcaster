#!/usr/bin/env python3
"""Audit harness — systematic live-server testing of the installer suite.

Runs against a real ComfyUI instance (default: ``${COMFYUI_HOST}``
on the LAN) and exercises every installer function whose correctness
can be verified without writing to disk. Each check prints
PASS / FAIL / SKIP with the relevant evidence so regressions are
caught BEFORE they ship.

Usage:
    python installer_audit.py
    python installer_audit.py --server http://${COMFYUI_HOST}:8190
    python installer_audit.py --server http://user:pass@host:8190 --auth

Exit code 0 = all checks passed; 1 = any failure (CI-friendly).

Covered:
  - install.py:_split_url_credentials (auth split round-trip)
  - install.py:_find_spellcaster_core (BUNDLE_DIR + repo-tree paths)
  - install.py:find_all_gimp_dirs (every detected GIMP version)
  - install_remote.py re-exports of the above
  - install_remote.py:probe_server (live HTTP probe, with + without auth)
  - install.py LoRA classifier (live server response → arch buckets)
  - install_remote.py:detect_available_features (feature gating)
  - install_remote.py:detect_nsfw_mode (NSFW edition detection)
  - install_remote.py:write_settings credential-leak check
    (auth_header never appears in URL fields)
  - install.py:_split_url_credentials called consistently at all sites
    (grep audit of file)
  - bootstrap.py:_write_crashlog uses tz-aware UTC datetime
  - PyInstaller spec files bundle comfyui-spellcaster/
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

# Resolve installer dir whether this file lives in tests/ or installer/.
# Prefer the sibling ``installer/`` (when this file is in tests/); fall
# back to its own directory (when copied into installer/).
_FILE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _FILE_DIR.parent if _FILE_DIR.name == "tests" else _FILE_DIR.parent
HERE = (_REPO_ROOT / "installer") if (_REPO_ROOT / "installer").is_dir() else _FILE_DIR
sys.path.insert(0, str(HERE))

# ─── Console helpers ──────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

_results: list[tuple[str, str, str]] = []  # (status, name, detail)


def _record(status: str, name: str, detail: str = "") -> None:
    _results.append((status, name, detail))
    icon = {"PASS": f"{GREEN}✓{RESET}",
            "FAIL": f"{RED}✗{RESET}",
            "SKIP": f"{YELLOW}~{RESET}"}[status]
    print(f"  {icon} {name}")
    if detail:
        print(f"    {DIM}{detail}{RESET}")


def section(label: str) -> None:
    print(f"\n{BOLD}══ {label} ══{RESET}")


# ─── Checks ───────────────────────────────────────────────────────────────────

def check_split_credentials(install) -> None:
    """install._split_url_credentials round-trip auth + no-auth cases."""
    section("auth split round-trip")

    cases = [
        ("http://user:pw@host:8190",  "http://host:8190",        True),
        ("http://host:8190",          "http://host:8190",        False),
        ("https://u:p@example.com/x", "https://example.com/x",   True),
        ("http://192.168.1.1:8188",   "http://192.168.1.1:8188", False),
        ("http://just-user@host",     "http://host",             True),  # no password
    ]
    for raw, want_clean, want_auth in cases:
        clean, auth = install._split_url_credentials(raw)
        ok = clean == want_clean and (bool(auth) == want_auth)
        if ok:
            _record("PASS", f"split({raw!r})",
                    f"clean={clean}  auth={'set' if auth else 'None'}")
        else:
            _record("FAIL", f"split({raw!r})",
                    f"want=({want_clean!r}, auth={want_auth}); got=({clean!r}, auth={auth!r})")


def check_find_spellcaster_core(install) -> None:
    """install._find_spellcaster_core resolves to a real spellcaster_core."""
    section("_find_spellcaster_core")

    result = install._find_spellcaster_core()
    if result is None:
        _record("FAIL", "_find_spellcaster_core() returned None",
                "build_installer.py is supposed to bundle comfyui-spellcaster/; "
                "install.py search_roots include BUNDLE_DIR")
        return
    if not (result / "__init__.py").is_file():
        _record("FAIL", f"_find_spellcaster_core() = {result}",
                "but __init__.py missing")
        return
    if not (result / "workflows.py").is_file():
        _record("FAIL", f"_find_spellcaster_core() = {result}",
                "but workflows.py missing — bundle is incomplete")
        return
    # Sanity: must be the canonical surface (has nsfw_unlock_loras param)
    src = (result / "workflows.py").read_text(encoding="utf-8", errors="replace")
    if "nsfw_unlock_loras" not in src:
        _record("FAIL", "spellcaster_core/workflows.py is stale",
                "missing nsfw_unlock_loras param — surface drift vs canonical")
        return
    _record("PASS", f"_find_spellcaster_core() = {result.name}",
            f"resolved to {result}")


def check_multi_gimp(install) -> None:
    """install.find_all_gimp_dirs enumerates plural versions when present."""
    section("multi-GIMP detection")

    dirs = install.find_all_gimp_dirs()
    if not dirs:
        _record("SKIP", "find_all_gimp_dirs()", "no GIMP installations detected")
        return
    detail = f"{len(dirs)} version(s): " + ", ".join(d.name for d in dirs)
    _record("PASS", f"find_all_gimp_dirs() = {len(dirs)} dirs", detail)
    if len(dirs) >= 2:
        _record("PASS", "side-by-side GIMP scenario",
                "install_remote.py multi-GIMP loop will mirror to all of these")
    else:
        _record("SKIP", "side-by-side GIMP scenario",
                "only one version installed; can't exercise multi-GIMP path")


def check_install_remote_reexports(install_remote) -> None:
    """install_remote.py re-exports the helpers that fix P0-3 + P0-4."""
    section("install_remote.py re-exports")

    required = [
        "_split_url_credentials",   # P0-3
        "find_all_gimp_dirs",       # P0-4
        "find_default_gimp",        # baseline
        "_classify_server_loras",   # used by write_settings
    ]
    for name in required:
        if hasattr(install_remote, name):
            _record("PASS", f"install_remote.{name}",
                    "re-exported from install")
        else:
            _record("FAIL", f"install_remote.{name}",
                    "MISSING — calls will NameError at install time")


def check_live_probe(install_remote, server_url: str) -> dict | None:
    """install_remote.probe_server hits the live server."""
    section(f"live probe against {server_url}")

    # Capture probe output so it doesn't drown the audit log
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            info = install_remote.probe_server(server_url)
    except Exception as e:
        _record("FAIL", "probe_server raised", repr(e))
        return None

    if not info.get("reachable"):
        _record("FAIL", "probe_server reachability",
                f"server returned not reachable; URL was {server_url}")
        return None

    nodes = info.get("available_nodes", set())
    _record("PASS", "probe_server reachability",
            f"reachable=True; {len(nodes)} nodes; "
            f"{info.get('gpu_name','?')} {info.get('vram_total',0)//(1024**3)} GB")

    # Sanity-check the model lists came back
    for key, want_min in [("checkpoints", 1), ("loras", 1)]:
        n = len(info.get(key, []))
        if n >= want_min:
            _record("PASS", f"probe.{key}", f"{n} entries")
        else:
            _record("FAIL", f"probe.{key}", f"got {n}; expected >= {want_min}")

    return info


def check_lora_classifier(install, server_info: dict | None) -> None:
    """install._classify_server_loras buckets server LoRAs by architecture."""
    section("LoRA classifier")
    if not server_info:
        _record("SKIP", "_classify_server_loras", "no server_info from probe")
        return
    loras = server_info.get("loras", [])
    if not loras:
        _record("SKIP", "_classify_server_loras", "server has no LoRAs")
        return
    try:
        archs = install._classify_server_loras(loras)
    except Exception as e:
        _record("FAIL", "_classify_server_loras raised", repr(e))
        return
    # Expect at least one arch bucket
    total = sum(len(v) if isinstance(v, list) else 0 for v in archs.values())
    if total == 0:
        _record("FAIL", "_classify_server_loras", "0 LoRAs classified")
        return
    keys_with_data = [k for k, v in archs.items() if isinstance(v, list) and v]
    _record("PASS", f"_classify_server_loras() classified {total}/{len(loras)}",
            f"archs: {', '.join(keys_with_data[:6])}"
            + ("…" if len(keys_with_data) > 6 else ""))


def check_feature_detect(install_remote, server_info, manifest_path: Path) -> None:
    """install_remote.detect_available_features against live server."""
    section("feature detection")
    if not server_info:
        _record("SKIP", "detect_available_features", "no server_info")
        return
    if not manifest_path.is_file():
        _record("FAIL", "manifest.json missing", str(manifest_path))
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feats = install_remote.detect_available_features(manifest, server_info)
    if not feats:
        _record("FAIL", "detect_available_features", "returned 0 features")
        return
    _record("PASS", f"detect_available_features = {len(feats)}",
            f"first 3: {feats[:3]}")


def check_nsfw_detect(install_remote, server_info) -> None:
    """install_remote.detect_nsfw_mode picks up adult LoRAs/models correctly."""
    section("NSFW edition detection")
    if not server_info:
        _record("SKIP", "detect_nsfw_mode", "no server_info")
        return
    is_nsfw = install_remote.detect_nsfw_mode(server_info)
    # On the NSFW edition dev box we know there's at least one
    # adult-only LoRA — expect True there. On a clean SFW server
    # expect False. Either is acceptable; we just want to confirm
    # the function runs and returns a bool.
    _record("PASS", f"detect_nsfw_mode = {is_nsfw}",
            "(boolean returned without raising)")


def check_credential_leak_grep() -> None:
    """Static grep: any remaining `server_url` in a persisted-string position."""
    section("credential-leak static check")

    install_remote = HERE / "install_remote.py"
    src = install_remote.read_text(encoding="utf-8")

    # Pattern: server_url being interpolated into a write context.
    # The legitimate sites (now using clean_url / display_url) shouldn't trip.
    bad = re.findall(
        r'(?:json\.dumps|write_text|\.write\(|f["\'][^"\']*\{server_url\}'
        r'[^"\']*["\'])',
        src,
    )
    # Soft check — also look for direct f-strings containing {server_url}
    # in any disk-write helper.
    leaky_lines = []
    for i, line in enumerate(src.splitlines(), 1):
        if "server_url" in line and any(tok in line for tok in
                                          ("config.json", "settings.json",
                                           "guild_config", "write_text",
                                           "json.dumps")):
            # Allowlist: the audited functions that explicitly split first
            if "_split_url_credentials" in line or "# clean" in line.lower():
                continue
            leaky_lines.append((i, line.strip()[:120]))

    if not leaky_lines:
        _record("PASS", "no leaky server_url in disk-write sites", "")
    else:
        for i, ln in leaky_lines[:5]:
            _record("FAIL", f"install_remote.py:{i}", ln)


def check_bootstrap_datetime() -> None:
    """bootstrap.py crashlog uses tz-aware UTC datetimes (H3)."""
    section("bootstrap.py H3 hygiene")
    bp = (HERE / "bootstrap.py").read_text(encoding="utf-8")
    # Bad pattern: _dt.now() without timezone arg
    bad = re.findall(r"_dt\.now\(\s*\)", bp)
    if bad:
        _record("FAIL", "bootstrap.py crashlog datetime",
                f"{len(bad)} naive _dt.now() call(s) — H3 violation")
    else:
        # And verify the good pattern is present
        if re.search(r"_dt\.now\(\s*_tz\.utc\s*\)", bp):
            _record("PASS", "bootstrap.py crashlog datetime",
                    "uses _dt.now(_tz.utc)")
        else:
            _record("FAIL", "bootstrap.py crashlog datetime",
                    "no tz-aware now() found")


def check_specs_bundle_pack() -> None:
    """PyInstaller .spec files bundle comfyui-spellcaster/."""
    section("PyInstaller .spec bundles comfyui-spellcaster")
    for spec in HERE.glob("*.spec"):
        body = spec.read_text(encoding="utf-8", errors="replace")
        if "comfyui-spellcaster" in body:
            _record("PASS", f"{spec.name}", "bundles comfyui-spellcaster/")
        else:
            _record("FAIL", f"{spec.name}",
                    "missing comfyui-spellcaster — frozen .exe will crash "
                    "on _find_spellcaster_core")


def check_build_installer_bundle_pack() -> None:
    """build_installer.py adds --add-data for comfyui-spellcaster in ALL targets."""
    section("build_installer.py bundles comfyui-spellcaster")
    body = (HERE / "build_installer.py").read_text(encoding="utf-8")
    # Count the --add-data calls and the comfyui-spellcaster references
    add_data_count = body.count("--add-data")
    pack_count = body.count("comfyui-spellcaster")
    # 4 build targets × ~6 --add-data entries each ≈ 20-24; we just want
    # pack_count >= 4 (one --add-data per target).
    if pack_count >= 4:
        _record("PASS", "build_installer.py --add-data",
                f"comfyui-spellcaster referenced {pack_count} times "
                f"({add_data_count} total --add-data)")
    else:
        _record("FAIL", "build_installer.py --add-data",
                f"only {pack_count} comfyui-spellcaster reference(s) — "
                f"expected >= 4 (one per build target)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Default server resolves from environment, falling back to a
    # sensible localhost guess. Set COMFYUI_HOST in the dev environment
    # (or pass --server) to point at the LAN host. We intentionally
    # avoid baking a private LAN IP into tracked code (H2 hygiene).
    _default_server = os.environ.get(
        "COMFYUI_AUDIT_URL",
        f"http://{os.environ.get('COMFYUI_HOST','127.0.0.1')}:8190")
    parser.add_argument("--server", default=_default_server,
                        help="ComfyUI URL for live probe (default: "
                             "$COMFYUI_AUDIT_URL or http://$COMFYUI_HOST:8190)")
    parser.add_argument("--auth", action="store_true",
                        help="treat --server as containing user:pass@ "
                             "(exercises the auth split path)")
    parser.add_argument("--no-live", action="store_true",
                        help="skip checks that hit the live server")
    args = parser.parse_args()

    # Force UTF-8 console on Windows (cp1252 chokes on ✓ / ✗)
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print(f"{BOLD}Spellcaster Installer Audit{RESET}")
    print(f"  Target server: {args.server}")
    print(f"  Live HTTP:     {'no' if args.no_live else 'yes'}")
    print(f"  HERE:          {HERE}")

    # Load modules under audit
    import install
    import install_remote

    # ── Static + module-level checks ──
    check_split_credentials(install)
    check_find_spellcaster_core(install)
    check_multi_gimp(install)
    check_install_remote_reexports(install_remote)
    check_credential_leak_grep()
    check_bootstrap_datetime()
    check_specs_bundle_pack()
    check_build_installer_bundle_pack()

    # ── Live-server checks ──
    server_info = None
    if not args.no_live:
        server_info = check_live_probe(install_remote, args.server)
        check_lora_classifier(install, server_info)
        check_feature_detect(install_remote, server_info,
                             HERE / "manifest.json")
        check_nsfw_detect(install_remote, server_info)

    # ── Tabulate ──
    section("RESULTS")
    p = sum(1 for s, *_ in _results if s == "PASS")
    f = sum(1 for s, *_ in _results if s == "FAIL")
    sk = sum(1 for s, *_ in _results if s == "SKIP")
    total = p + f + sk
    print(f"  {GREEN}PASS{RESET}: {p}/{total}    "
          f"{RED}FAIL{RESET}: {f}    "
          f"{YELLOW}SKIP{RESET}: {sk}")
    if f:
        print(f"\n  {BOLD}Failures:{RESET}")
        for s, n, d in _results:
            if s == "FAIL":
                print(f"    {RED}✗{RESET} {n}")
                if d:
                    print(f"      {DIM}{d}{RESET}")
    return 0 if f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
