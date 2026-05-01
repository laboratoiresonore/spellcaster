"""ComfyUI Manager-compatible installer for ComfyUI-Spellcaster.

Manager runs `python install.py` after cloning + on update. This
script is intentionally minimal: it installs requirements.txt and
exits 0. All heavy model / theme setup lives in the separate
Spellcaster suite installer (spellcaster/installer/install.py),
which this pack's __init__.py prompts the user to run on first
import when no suite is detected.

Idempotent: re-running `pip install -r requirements.txt` is a no-op
when deps are already satisfied. Falls back to exit 0 on any error
so a Manager update doesn't crash the whole update batch.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    pack_dir = Path(__file__).resolve().parent
    req = pack_dir / "requirements.txt"
    if not req.is_file():
        return 0
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            check=False,
            cwd=str(pack_dir),
        )
    except Exception as exc:
        # Never propagate — Manager treats non-zero as "pack broken"
        # and refuses to load the node, which is worse than a silent
        # dep miss (some features degrade gracefully).
        print(f"[ComfyUI-Spellcaster] install.py: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
