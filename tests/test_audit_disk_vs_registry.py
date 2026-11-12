"""Smoke test for tools/audit_disk_vs_registry.py."""
from __future__ import annotations

import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "audit_disk_vs_registry.py"


def test_self_check_passes():
    result = subprocess.run(
        [sys.executable, str(TOOL), "--self-check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"self-check exited {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "self-check OK" in result.stdout


def test_missing_root_errors():
    result = subprocess.run(
        [sys.executable, str(TOOL), "--models-root", "/nonexistent/path/xyz-9999"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not a directory" in result.stderr


def test_parse_registry_includes_known_arches():
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    try:
        import audit_disk_vs_registry as m
    finally:
        sys.path.pop(0)
    arches = m.parse_registry()
    names = {n for n, _ in arches}
    for expected in ("sdxl", "flux3klein", "flux2dev", "krea2", "qwen_image"):
        assert expected in names, f"{expected} missing from registry parse"
    stubs = {n for n, r in arches if not r}
    assert "kolors" in stubs
