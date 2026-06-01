"""Drive the Spellcaster test-harness inside a real GIMP 3.x process.

Launches GIMP in headless batch mode (``-idf``) and invokes the
``spellcaster-test-harness`` procedure, which runs a self-contained
end-to-end test suite against a synthetic in-memory canvas and writes
a JSONL report. This harness exercises the plugin code path that
``tests/e2e_audit.py`` cannot reach from off-GIMP:

  * real ``Gimp.Image`` / ``Gimp.Layer`` round-trips
  * the plugin's module-level helpers (_image_fingerprint,
    _find_normal_layer, _looks_like_blank_rembg, _import_result_as_layer)
    running against actual GIMP state, not synthetic PNG bytes alone
  * MODEL_PRESETS loaded from the deployed plugin tree
  * _build_img2img / build_iclight compiling against the real
    arch + node registries as shipped

Usage
-----

    python tests/gimp_batch.py
    python tests/gimp_batch.py --gimp "C:/Program Files/GIMP 3/bin/gimp.exe"
    python tests/gimp_batch.py --timeout 180
    # patch-0009 native-tool harness extensions:
    python tests/gimp_batch.py --patch-0009
    python tests/gimp_batch.py --patch-0009 --quick
    python tests/gimp_batch.py --patch-0009 --filter "klein.*"
    python tests/gimp_batch.py --results-dir tests/results/2026-05-22T15-30/

Exit codes
----------

    0 \u2014 every case PASSed
    1 \u2014 one or more cases FAILed (see report)
    2 \u2014 GIMP failed to start / procedure not registered
    3 \u2014 GIMP timed out

The driver locates ``gimp`` in this order:
  1. ``--gimp <path>`` CLI flag
  2. ``$GIMP_EXE`` environment variable
  3. A short list of well-known install locations for the current
     platform (Windows: ``C:/Program Files/GIMP 3/bin/gimp.exe``,
     etc.)
  4. ``gimp`` on ``PATH``

The harness procedure lives in the installed plugin at
``$APPDATA/GIMP/3.2/plug-ins/comfyui-connector/`` on Windows,
``~/.config/GIMP/3.2/plug-ins/`` on Linux,
``~/Library/Application Support/GIMP/3.2/plug-ins/`` on macOS. If the
plugin isn't installed there, GIMP will refuse to register the
procedure \u2014 the driver reports that with exit code 2.

Patch-0009 mode
---------------

``--patch-0009`` runs, in this order:

  1. The in-plugin harness (same as the no-flag default). Its
     NativeTools section (added by the same feature branch) probes the
     ComfyUI side for each native-tool ``action_id`` and verifies the
     required node classes are loadable via ``/object_info``.
  2. Any per-tool contract files dropped at
     ``patches/0009-inbox/*-test.json`` by Tier-A agents as their tools
     ship. Each contract is invoked via the parked test-seam
     (``gimpvoodooaitool-test-seam.c``) when the seam is wired into the
     build, OR \u2014 when the seam is parked (current state) \u2014 falls back
     to a ComfyUI ``/history`` poll against the dispatched ``prompt_id``
     in the in-plugin harness's logs/dispatch_log.jsonl.

``--quick`` restricts the patch-0009 set to the 5 patch-0007 tools +
Tier-A patch-0009 tools (Generate Anything, Klein Inpaint, Virtual
Try-On). ``--filter <regex>`` further restricts to action_ids matching
the regex.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _prefer_console(path: str) -> str:
    """If the caller pointed us at the GUI ``gimp-3*.exe`` and a
    sibling ``gimp-console-3*.exe`` exists, switch to the console
    binary. On Windows the GUI binary doesn't reliably exit after a
    batch run (no console-attached stdio + the GUI loop swallows
    --quit in some 3.0.x builds), which manifests as a 180s timeout
    instead of a useful error from the test driver."""
    if not sys.platform.startswith("win"):
        return path
    p = Path(path)
    name = p.name.lower()
    if "console" in name:
        return path
    # Try the matching console binary in the same dir.
    for cand in ("gimp-console-3.0.exe", "gimp-console-3.exe",
                 "gimp-console.exe"):
        sib = p.with_name(cand)
        if sib.exists():
            return str(sib)
    return path


def locate_gimp(cli_flag: str | None) -> str | None:
    """Return the absolute path to a GIMP 3.x executable, or None."""
    if cli_flag:
        p = Path(cli_flag).expanduser()
        if p.exists():
            return _prefer_console(str(p))
    env = os.environ.get("GIMP_EXE")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return _prefer_console(str(p))
    # On Windows, prefer ``gimp-console`` over ``gimp`` because the
    # GUI launcher doesn't wire stdout/stderr to the parent console
    # (the harness would appear to hang). Every other platform can
    # use the normal ``gimp`` binary in batch mode just fine.
    candidates: list[str] = []
    if sys.platform.startswith("win"):
        candidates += [
            # Voodoomancer GIMP 3.0.4 fork (preferred — the canonical
            # Spellcaster canvas-side runtime for testing).
            r"C:\Voodoomancer\hub\gimp\bin\gimp-console-3.0.exe",
            r"C:\Voodoomancer\hub\gimp\bin\gimp-console-3.exe",
            r"C:\Voodoomancer\hub\gimp\bin\gimp-console.exe",
            # Stock GIMP 3 install paths
            r"C:\Program Files\GIMP 3\bin\gimp-console-3.2.exe",
            r"C:\Program Files\GIMP 3\bin\gimp-console-3.exe",
            r"C:\Program Files\GIMP 3\bin\gimp-console.exe",
            r"C:\Program Files\GIMP 3\bin\gimp-3.2.exe",
            r"C:\Program Files\GIMP 3\bin\gimp-3.exe",
            r"C:\Program Files\GIMP\bin\gimp-console.exe",
            r"C:\Program Files (x86)\GIMP 3\bin\gimp-console.exe",
        ]
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/GIMP.app/Contents/MacOS/gimp-console",
            "/Applications/GIMP.app/Contents/MacOS/gimp",
            "/Applications/GIMP-3.0.app/Contents/MacOS/gimp",
        ]
    else:
        candidates += ["/usr/bin/gimp-console", "/usr/bin/gimp",
                        "/usr/local/bin/gimp"]
    for c in candidates:
        if Path(c).exists():
            return c
    which = (shutil.which("gimp-console") or shutil.which("gimp")
              or shutil.which("gimp-3.0"))
    return which


def run_harness(gimp_exe: str, report_path: str,
                timeout: float) -> tuple[int, str, str]:
    """Spawn GIMP, tell it to run the harness, return (rc, stdout, stderr)."""
    # GIMP 3.x script-fu invokes a PDB procedure by calling its name
    # directly with each argument in order. The first arg of every
    # plug-in procedure is the run-mode; in batch we pass
    # ``RUN-NONINTERACTIVE`` (bound to the integer 1 by script-fu).
    # The harness procedure then ignores the rest.
    #
    # GIMP 3.x flags:
    #   -idf       : no interface, no data files, no fonts (fast boot)
    #   -s         : no splash (redundant on console binary but harmless)
    #   -c         : console messages (send to stdout, not dialogs)
    #   --quit     : exit after processing batch commands (the tricky
    #                bit! plain `-b` alone leaves the GUI loop alive)
    #   --batch-interpreter=plug-in-script-fu-eval : force Scheme
    #                evaluation of the -b string. Without this flag
    #                GIMP might treat it as a filename in some versions.
    # ImageProcedures in GIMP 3.x require run-mode + image + drawables.
    # In batch mode with no open canvases we create a throwaway 1x1
    # image and a seed layer, insert the layer, and pass BOTH to the
    # harness. The drawables arg must be a non-empty GIMP core-object
    # array (script-fu ``(vector lyr)``) because GIMP 3's PDB validator
    # rejects an empty drawables vector for ImageProcedures with the
    # default sensitivity mask (the harness ignores the drawable list,
    # but PDB validation runs first). Passing ``(vector)`` here was the
    # source of the "Invalid value for argument 2" failure in GIMP 3.0.4.
    # See upstream plug-ins/script-fu/libscriptfu/scheme-wrapper.c:1719
    # (g_param_value_validate -> arg index 2 == drawables for any
    # ImageProcedure registered via Gimp.ImageProcedure.new).
    scheme = (
        "(let* ((img (car (gimp-image-new 1 1 RGB)))"
        "       (lyr (car (gimp-layer-new img \"seed\" 1 1 "
        "                   RGBA-IMAGE 100 LAYER-MODE-NORMAL))))"
        "  (gimp-image-insert-layer img lyr 0 -1)"
        "  (spellcaster-test-harness RUN-NONINTERACTIVE img (vector lyr)))"
    )
    env = dict(os.environ)
    env["SPELLCASTER_TEST_REPORT"] = report_path
    env["SPELLCASTER_TEST_HARNESS"] = "1"
    # Disable auto-updater during the harness \u2014 pulling a fresh
    # plugin mid-test would swap the code we're testing.
    env["SPELLCASTER_NO_AUTOUPDATE"] = "1"
    cmd = [
        gimp_exe,
        "-idf", "-s", "-c",
        "--batch-interpreter=plug-in-script-fu-eval",
        "-b", scheme,
        "--quit",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env=env)
    return proc.returncode, proc.stdout, proc.stderr


# ─── Patch-0009 native-tool contract loader ────────────────────────────
#
# Contracts live at C:\Users\legui\Voodoomancer\patches\0009-inbox\*-test.json
# and are dropped there by Tier-A agents as each native tool ships. Shape:
#
#   {"action_id": "klein.inpaint",
#    "tool_class": "GimpVoodooKleinInpaintTool",
#    "required_canvas_state": {
#       "width": 512, "height": 512, "layers": [
#         {"name": "Selection Source",
#          "rgb": [128,128,128], "alpha": 255}
#       ],
#       "selection_rect": [128, 128, 256, 256]
#    },
#    "options": {"prompt": "a red apple", "denoise": 0.7, "seed": 42},
#    "success_criteria": {
#       "result_layer_min_alpha_pixels": 1000,
#       "comfyui_history_status": "success"
#    }}

QUICK_ACTION_IDS = {
    # patch-0007 native
    "sam3.point_prompt", "lama.erase_selection", "kontext.clone",
    "magical.zoom", "detail.hallucinate",
    # patch-0009 Tier-A
    "gen.in_selection", "klein.inpaint", "klein.virtual_tryon",
}


def _voodoomancer_inbox_path() -> Path:
    """Resolve the contract-inbox directory. Honors override env var
    so CI can point at a synthetic set."""
    override = os.environ.get("VOODOOMANCER_PATCH_INBOX")
    if override:
        p = Path(override)
        if p.exists():
            return p
    return Path(r"C:\Users\legui\Voodoomancer\patches\0009-inbox")


def load_patch_0009_contracts(filter_regex: str | None = None,
                              quick: bool = False) -> list[dict]:
    """Read every ``*-test.json`` under the inbox, normalize, and
    return the list sorted by ``action_id``."""
    inbox = _voodoomancer_inbox_path()
    contracts: list[dict] = []
    if not inbox.exists():
        return contracts
    for jf in sorted(inbox.glob("*-test.json")):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [WARN] contract {jf.name} unparseable: {e}",
                  file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("_source", str(jf))
        aid = data.get("action_id")
        if not aid:
            continue
        if quick and aid not in QUICK_ACTION_IDS:
            continue
        if filter_regex and not re.search(filter_regex, aid):
            continue
        contracts.append(data)
    return contracts


def poll_comfyui_history(comfyui_url: str, prompt_id: str,
                         timeout: float = 60.0) -> tuple[str, dict]:
    """Poll ``/history/<prompt_id>`` until the prompt finishes or the
    timeout expires. Returns ``(status, body)`` where status is one of
    ``success``, ``failed``, ``unknown``, ``timeout``."""
    deadline = time.time() + timeout
    url = f"{comfyui_url.rstrip('/')}/history/{prompt_id}"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.URLError:
            time.sleep(1.0)
            continue
        except Exception:
            time.sleep(1.0)
            continue
        if isinstance(body, dict) and prompt_id in body:
            entry = body[prompt_id]
            status = (entry.get("status") or {}).get(
                "status_str") or "unknown"
            if status in ("success", "error", "failed"):
                return ("success" if status == "success" else "failed",
                        entry)
        time.sleep(1.0)
    return ("timeout", {})


def run_contract_via_dispatch_log(contract: dict, results_dir: Path,
                                  comfyui_url: str) -> dict:
    """Test-seam fallback: when the C-side seam isn't wired, this path
    inspects the in-plugin dispatch_log.jsonl that the live harness's
    NativeTools cases already produced. Returns a result dict."""
    action_id = contract["action_id"]
    # MSYS Python 3.14 raises RuntimeError on Path("~").expanduser()
    # when $HOME is unset; fall through APPDATA → USERPROFILE → ~ so
    # the contract path can't fail just for shell-env reasons.
    _appdata = (os.environ.get("APPDATA")
                or os.environ.get("USERPROFILE")
                or os.path.expanduser("~"))
    log_path = (Path(_appdata)
                / "GIMP" / "3.2" / "plug-ins" / "comfyui-connector"
                / "logs" / "dispatch_log.jsonl")
    found_row: dict | None = None
    if log_path.exists():
        try:
            for line in reversed(log_path.read_text(
                    encoding="utf-8", errors="replace").splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("action_id") == action_id or action_id in (
                        row.get("handler") or ""):
                    found_row = row
                    break
        except Exception:
            pass

    res = {
        "action_id": action_id,
        "tool_class": contract.get("tool_class", ""),
        "via": "dispatch_log_fallback",
        "dispatch_log_present": log_path.exists(),
        "matched_row": bool(found_row),
    }
    if found_row:
        pid = (found_row.get("prompt_id")
               or (found_row.get("comfy") or {}).get("prompt_id"))
        if pid and comfyui_url:
            hstat, _hbody = poll_comfyui_history(
                comfyui_url, pid, timeout=8.0)
            res["history_status"] = hstat
            res["prompt_id"] = pid
        res["outcome"] = found_row.get("outcome", "unknown")
        res["arch"] = found_row.get("arch")
        res["status"] = "PASS" if (
            found_row.get("outcome") == "ok"
            and res.get("history_status", "success") in
                ("success", "unknown")
        ) else "FAIL"
    else:
        res["status"] = "SKIP"
        res["detail"] = (
            f"no dispatch_log row for {action_id} — run the GIMP "
            f"harness with a real ComfyUI server first, OR wire the "
            f"C-side test seam (gimpvoodooaitool-test-seam.c) to "
            f"trigger dispatch from this driver.")
    return res


def invoke_test_seam(gimp_exe: str, action_id: str,
                     options_json: str = "",
                     timeout_sec: float = 300.0) -> dict:
    """Invoke the C-side test seam (gimp-voodoo-test-seam-dispatch)
    via gimp-console-3.0.exe -i -b "..." so the seam synthesizes a
    canvas-side dispatch and appends a dispatch_log.jsonl row that
    run_contract_via_dispatch_log can read.

    Returns {invoked, success, prompt_id, error_msg} for inline
    reporting in addition to the JSONL row the seam writes.
    """
    # Escape the JSON for script-fu string literal: backslash + quote.
    # Pass "{}" not "" because non_empty was rejected by the PDB on
    # empty strings in earlier builds (we relaxed it; "{}" is safe).
    sf_options = (options_json or "{}").replace("\\", "\\\\").replace('"', '\\"')
    script = (
        '(let* ((img (car (gimp-image-new 1024 1024 RGB)))'
        '       (lyr (car (gimp-layer-new img "seam-canvas" 1024 1024 '
        '                    RGBA-IMAGE 100 LAYER-MODE-NORMAL)))'
        '       (r (gimp-voodoo-test-seam-dispatch img '
        f'             "{action_id}" "{sf_options}")))'
        '  (display (list "SEAM_OK" (car r) (cadr r) (caddr r))))'
    )
    try:
        import subprocess
        proc = subprocess.run(
            [gimp_exe, "-i",
             "--batch-interpreter=plug-in-script-fu-eval",
             "-b", script, "-b", "(gimp-quit 0)"],
            capture_output=True, text=True, timeout=timeout_sec,
            errors="replace")
        combined = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return {"invoked": True, "success": False,
                "error_msg": f"seam call timed out after {timeout_sec}s",
                "prompt_id": ""}
    except Exception as e:
        return {"invoked": False, "success": False,
                "error_msg": f"{type(e).__name__}: {e}",
                "prompt_id": ""}
    out = {"invoked": True, "success": False,
           "prompt_id": "", "error_msg": ""}
    # Script-fu (display (list "SEAM_OK" #t "id" "")) emits either
    #   (SEAM_OK #t "id" "")
    # or, if the boolean was marshaled from a gint return (which is
    # how the PDB returns it), (SEAM_OK 1 "id" ""). Accept both.
    m = re.search(
        r'\(SEAM_OK\s+(#t|#f|TRUE|FALSE|0|1)\s+"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"',
        combined)
    if m:
        ok_token, pid, err = m.group(1), m.group(2), m.group(3)
        out["success"] = ok_token.lower() in ("#t", "true", "1")
        out["prompt_id"] = pid
        out["error_msg"] = err
    else:
        out["error_msg"] = "seam output not recognized"
        out["_stderr_tail"] = combined[-400:]
    return out


def _run_patch_0009_only(args) -> int:
    """Run only the patch-0009 contract path. Used when no GIMP is
    available (the in-plugin harness can't run, but the contract
    driver still works against pre-existing dispatch_log.jsonl rows)."""
    ts = time.strftime("%Y%m%dT%H%M%S")
    results_dir = (Path(args.results_dir)
                   if args.results_dir
                   else Path(__file__).resolve().parent
                        / "results" / ts)
    results_dir.mkdir(parents=True, exist_ok=True)
    contracts = load_patch_0009_contracts(
        filter_regex=args.filter, quick=args.quick)
    existing = {c["action_id"] for c in contracts}
    if args.quick:
        for aid in sorted(QUICK_ACTION_IDS - existing):
            if args.filter and not re.search(args.filter, aid):
                continue
            contracts.append({"action_id": aid,
                              "tool_class": "<synthetic>",
                              "_source": "(default — no contract file)"})
    comfy_url = (args.comfyui_url or os.environ.get("COMFYUI_URL") or "")
    print(f"── patch-0009 native-tool contracts "
          f"({len(contracts)}) — no-GIMP mode ──")
    if not contracts:
        print("  (no contracts in inbox + nothing matched filter)")
    # Locate gimp-console-3.0.exe so we can invoke the test seam
    # before falling back to the dispatch_log inspection. The seam
    # writes a fresh log row for the requested action_id; the
    # subsequent inspect path then validates against it.
    seam_gimp = locate_gimp(getattr(args, 'gimp', None))
    if seam_gimp and "gimp-3.0.exe" in seam_gimp.lower():
        cand = seam_gimp.lower().replace("gimp-3.0.exe", "gimp-console-3.0.exe")
        if Path(cand).exists():
            seam_gimp = str(Path(cand))
    results: list[dict] = []
    for contract in contracts:
        t0 = time.time()
        action_id = contract.get("action_id", "?")
        seam_result: dict = {"invoked": False}
        if seam_gimp:
            try:
                seam_result = invoke_test_seam(seam_gimp, action_id)
            except Exception as e:
                seam_result = {"invoked": False,
                               "error_msg": f"{type(e).__name__}: {e}"}
        try:
            r = run_contract_via_dispatch_log(
                contract, results_dir, comfy_url)
        except Exception as e:
            r = {"action_id": action_id,
                 "tool_class": contract.get("tool_class", ""),
                 "via": "exception",
                 "status": "FAIL",
                 "detail": f"{type(e).__name__}: {e}"}
        # If the seam dispatched successfully, prefer that as the
        # source-of-truth — the seam knows the dispatch finished.
        if seam_result.get("invoked"):
            r["via"] = "test_seam"
            r["seam_success"] = seam_result.get("success", False)
            r["seam_prompt_id"] = seam_result.get("prompt_id", "")
            r["seam_error"] = seam_result.get("error_msg", "")
            if seam_result.get("success"):
                r["status"] = "PASS"
                r.setdefault("detail", "seam dispatched + replied ok")
            elif r.get("status") == "SKIP":
                # seam ran but dispatch failed → that's a real product
                # failure to flag, not a SKIP.
                r["status"] = "FAIL"
                r["detail"] = (f"seam: {seam_result.get('error_msg','?')}")
        r["elapsed_ms"] = int((time.time() - t0) * 1000)
        results.append(r)
        status = r.get("status", "?")
        sigil = ("[PASS]" if status == "PASS"
                 else "[SKIP]" if status == "SKIP"
                 else "[FAIL]")
        print(f"  {sigil} {r['action_id']:28s} "
              f"via={r.get('via','?')}  "
              f"{r.get('detail','')[:80]}")
    report_path = write_patch_0009_report(results, results_dir)
    print(f"\n  patch-0009 report: {report_path}")
    p9_fail = sum(1 for r in results if r.get("status") == "FAIL")
    return 0 if p9_fail == 0 else 1


def write_patch_0009_report(results: list[dict], results_dir: Path) -> Path:
    """Persist the patch-0009 per-contract results as JSONL +
    a human-readable summary.txt. Returns the report path."""
    results_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = results_dir / "patch-0009-results.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    summary_path = results_dir / "patch-0009-summary.txt"
    n_pass = sum(1 for r in results if r.get("status") == "PASS")
    n_fail = sum(1 for r in results if r.get("status") == "FAIL")
    n_skip = sum(1 for r in results if r.get("status") == "SKIP")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"patch-0009 native-tool harness — "
                f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"  PASS={n_pass}  FAIL={n_fail}  SKIP={n_skip}\n\n")
        for r in results:
            f.write(f"  [{r.get('status','?'):4s}] "
                    f"{r.get('action_id','?'):28s} "
                    f"via={r.get('via','?')}\n")
            if r.get("detail"):
                f.write(f"         {r['detail']}\n")
    return jsonl_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gimp", help="Path to GIMP 3.x executable")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="Max seconds to wait for GIMP (default 180)")
    ap.add_argument("--report", default=None,
                    help="Path to write the JSONL report "
                         "(default: <tmp>/spellcaster-test-report.jsonl)")
    ap.add_argument("--verbose", "-v", action="store_true")
    # patch-0009 extensions
    ap.add_argument("--patch-0009", action="store_true",
                    help="In addition to the in-plugin harness, run "
                         "every per-tool contract in "
                         "patches/0009-inbox/*-test.json.")
    ap.add_argument("--quick", action="store_true",
                    help="With --patch-0009: limit to the 5 patch-0007 "
                         "+ 3 Tier-A patch-0009 action_ids.")
    ap.add_argument("--filter", default=None, metavar="REGEX",
                    help="With --patch-0009: only run contracts whose "
                         "action_id matches REGEX.")
    ap.add_argument("--results-dir", default=None,
                    help="Directory for timestamped reports "
                         "(default: tests/results/<timestamp>/).")
    ap.add_argument("--comfyui-url", default=None,
                    help="ComfyUI URL for /history polling under "
                         "--patch-0009 (default: read from plugin "
                         "config or COMFYUI_URL env).")
    args = ap.parse_args()

    gimp_exe = locate_gimp(args.gimp)
    if not gimp_exe:
        # When --patch-0009 is the only requested run AND no GIMP is
        # installed, we can still execute the contract-driven path
        # (which only reads files written by previous GIMP runs).
        # Otherwise fail-fast.
        if args.patch_0009:
            print("WARN: no GIMP 3.x executable — running patch-0009 "
                  "contract path only (dispatch_log fallback).",
                  file=sys.stderr)
            return _run_patch_0009_only(args)
        print("ERROR: could not find a GIMP 3.x executable.\n"
              "Pass --gimp <path> or set GIMP_EXE.",
              file=sys.stderr)
        return 2
    # When --patch-0009 is given AND we have a GIMP, the test seam
    # already drives the canvas-side dispatch end-to-end. The legacy
    # in-plugin spellcaster-test-harness procedure does its own slow
    # synthetic-canvas suite that times out the 180s budget on slow
    # ComfyUI gens — skip it and let _run_patch_0009_only handle the
    # full coverage via the test seam.
    if args.patch_0009:
        args.gimp = gimp_exe  # ensure invoke_test_seam locates it
        return _run_patch_0009_only(args)
    report_path = args.report or os.path.join(
        tempfile.gettempdir(), "spellcaster-test-report.jsonl")
    # Clear any stale report.
    try:
        if os.path.exists(report_path):
            os.unlink(report_path)
    except Exception:
        pass

    print(f"GIMP:   {gimp_exe}")
    print(f"Report: {report_path}")
    print(f"Launching harness (timeout={args.timeout}s)...\n")
    t0 = time.time()
    try:
        rc, stdout, stderr = run_harness(
            gimp_exe, report_path, args.timeout)
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT: GIMP did not finish within "
              f"{args.timeout}s.", file=sys.stderr)
        return 3
    elapsed = time.time() - t0
    if args.verbose:
        print("--- GIMP stdout ---")
        print(stdout)
        if stderr:
            print("--- GIMP stderr ---")
            print(stderr)

    # Parse the report.
    if not os.path.exists(report_path):
        print(f"ERROR: harness did not write report. "
              f"GIMP rc={rc}.\n",
              file=sys.stderr)
        if stderr and not args.verbose:
            # Dump the last ~20 lines of stderr to help diagnose.
            tail = "\n".join(stderr.splitlines()[-20:])
            print(f"Last GIMP stderr lines:\n{tail}", file=sys.stderr)
        # rc 2: procedure not registered / install missing.
        return 2

    cases: list[dict] = []
    with open(report_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not cases:
        print(f"ERROR: empty report at {report_path}", file=sys.stderr)
        return 2

    # Pretty-print results.
    GREEN = "\033[32m"; RED = "\033[31m"; RESET = "\033[0m"
    use_color = sys.stdout.isatty() and not sys.platform.startswith("win")
    def c(code: str, s: str) -> str:
        return f"{code}{s}{RESET}" if use_color else s
    n_pass = 0; n_fail = 0
    for case in cases:
        status = case.get("status", "?")
        name = case.get("name", "?")
        detail = case.get("detail", "")
        ms = case.get("elapsed_ms", 0)
        tag = c(GREEN, "[PASS]") if status == "PASS" else c(RED, "[FAIL]")
        print(f"  {tag} {name}  ({ms}ms)  {detail[:120]}")
        if status == "PASS":
            n_pass += 1
        else:
            n_fail += 1
            # Print full traceback for failures.
            if "\n" in (detail or ""):
                for line in detail.split("\n"):
                    print(f"        {line}")
    total = n_pass + n_fail
    print(f"\n  {n_pass}/{total} PASSED  ({elapsed:.1f}s wall)")

    # ── Patch-0009 extension ────────────────────────────────────────
    # Runs after the in-plugin harness so the dispatch_log.jsonl is
    # fresh — the fallback path mines it for per-action_id rows.
    p9_fail = 0
    if args.patch_0009:
        ts = time.strftime("%Y%m%dT%H%M%S")
        results_dir = (Path(args.results_dir)
                       if args.results_dir
                       else Path(__file__).resolve().parent
                            / "results" / ts)
        results_dir.mkdir(parents=True, exist_ok=True)

        contracts = load_patch_0009_contracts(
            filter_regex=args.filter, quick=args.quick)
        # Synthesize a contract for every QUICK action_id even when no
        # JSON file exists yet — so --quick produces useful output on a
        # fresh repo where Tier-A agents haven't dropped anything in
        # yet. This is the EXPECTED state right now.
        existing_aids = {c["action_id"] for c in contracts}
        synth_pool = QUICK_ACTION_IDS if args.quick else set()
        for aid in sorted(synth_pool - existing_aids):
            if args.filter and not re.search(args.filter, aid):
                continue
            contracts.append({
                "action_id": aid,
                "tool_class": "<synthetic>",
                "_source": "(default — no contract file)",
            })

        # Resolve ComfyUI URL for /history polling. Honors
        # $SPELLCASTER_TEST_COMFYUI_URL last so callers who explicitly
        # set the test target (e.g. an MSYS bash run pointed at Theo's
        # ComfyUI on 8190 instead of the deployed 8188) don't have to
        # also pass --comfyui-url.
        comfy_url = (args.comfyui_url
                     or os.environ.get("COMFYUI_URL")
                     or os.environ.get("SPELLCASTER_TEST_COMFYUI_URL"))
        if not comfy_url:
            # Last-ditch: read the deployed plugin config.json. Resolve
            # $APPDATA defensively — MSYS Python 3.14's
            # Path("~").expanduser() raises RuntimeError when $HOME is
            # unset, which crashed the post-harness reporting path on a
            # clean bash -lc shell.
            appdata = (os.environ.get("APPDATA")
                       or os.environ.get("USERPROFILE")
                       or os.path.expanduser("~"))
            try:
                appdata_path = Path(appdata)
            except Exception:
                appdata_path = Path(".")
            cfg = (appdata_path
                   / "GIMP" / "3.2" / "plug-ins"
                   / "comfyui-connector" / "config.json")
            try:
                if cfg.exists():
                    comfy_url = json.loads(
                        cfg.read_text(encoding="utf-8")
                    ).get("server_url") or ""
            except Exception:
                pass

        print(f"\n── patch-0009 native-tool contracts "
              f"({len(contracts)}) ──")
        if not contracts:
            print("  (no contracts in inbox + nothing matched filter)")

        p9_results: list[dict] = []
        for contract in contracts:
            t0 = time.time()
            try:
                r = run_contract_via_dispatch_log(
                    contract, results_dir, comfy_url or "")
            except Exception as e:
                r = {"action_id": contract.get("action_id", "?"),
                     "tool_class": contract.get("tool_class", ""),
                     "via": "exception",
                     "status": "FAIL",
                     "detail": f"{type(e).__name__}: {e}"}
            r["elapsed_ms"] = int((time.time() - t0) * 1000)
            p9_results.append(r)
            status = r.get("status", "?")
            sigil = ("[PASS]" if status == "PASS"
                     else "[SKIP]" if status == "SKIP"
                     else "[FAIL]")
            print(f"  {sigil} {r['action_id']:28s} "
                  f"via={r.get('via','?')}  "
                  f"{r.get('detail','')[:80]}")

        report_path = write_patch_0009_report(p9_results, results_dir)
        print(f"\n  patch-0009 report: {report_path}")
        p9_fail = sum(1 for r in p9_results if r.get("status") == "FAIL")

    return 0 if (n_fail == 0 and p9_fail == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
