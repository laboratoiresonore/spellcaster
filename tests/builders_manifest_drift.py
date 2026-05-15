"""CI guard: ``builders_manifest.json`` must match what the generator
would produce against the current ``workflows.py``.

The manifest is the canonical surface that Voodoomaster advertises via
``/v1/capabilities.methods`` and the Voodoomancer C-side reads at
startup. If it falls out of sync with ``workflows.py`` (someone added
``build_X`` and forgot to regenerate, OR someone hand-edited the JSON),
the propagation chain silently breaks for the new method.

This test shells out to ``tools/build_builders_manifest.py --check``
and fails with a clear "regenerate via …" message on drift.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "tools/build_builders_manifest.py", "--check"],
        cwd=str(REPO), capture_output=True, text=True, timeout=60,
        check=False)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
