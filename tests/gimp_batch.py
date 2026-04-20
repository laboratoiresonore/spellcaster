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
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def locate_gimp(cli_flag: str | None) -> str | None:
    """Return the absolute path to a GIMP 3.x executable, or None."""
    if cli_flag:
        p = Path(cli_flag).expanduser()
        if p.exists():
            return str(p)
    env = os.environ.get("GIMP_EXE")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return str(p)
    # On Windows, prefer ``gimp-console`` over ``gimp`` because the
    # GUI launcher doesn't wire stdout/stderr to the parent console
    # (the harness would appear to hang). Every other platform can
    # use the normal ``gimp`` binary in batch mode just fine.
    candidates: list[str] = []
    if sys.platform.startswith("win"):
        candidates += [
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
    # ImageProcedures in GIMP 3.x require an image argument. In batch
    # mode with no open canvases, we create a throwaway 1\u00d71 image
    # first, pass it in, then let the harness build its own 256\u00d7256
    # canvas internally. Drawables is an empty vector \u2014 the
    # harness doesn't use it.
    scheme = (
        "(let* ((img (car (gimp-image-new 1 1 RGB)))"
        "       (lyr (car (gimp-layer-new img \"seed\" 1 1 "
        "                   RGBA-IMAGE 100 LAYER-MODE-NORMAL))))"
        "  (gimp-image-insert-layer img lyr 0 -1)"
        "  (spellcaster-test-harness RUN-NONINTERACTIVE img (vector)))"
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
    args = ap.parse_args()

    gimp_exe = locate_gimp(args.gimp)
    if not gimp_exe:
        print("ERROR: could not find a GIMP 3.x executable.\n"
              "Pass --gimp <path> or set GIMP_EXE.",
              file=sys.stderr)
        return 2
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
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
