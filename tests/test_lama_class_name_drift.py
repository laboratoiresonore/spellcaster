"""Regression guard for the PATCH_0009 LaMa phantom-class-name cleanup.

`LaMaInpaint`, `LaMaInpainting`, and `LaMaInpaintingModelLoader` are
*phantom* ComfyUI class names — no custom-node pack has ever registered
any of them. They appeared in the spellcaster repo via copy-paste drift
from an early planning doc; every feature gate / inventory entry /
preflight check that referenced them was silently fail-open at runtime
and provided no value.

The real class emitted by ``build_lama_remove()`` is **``LamaRemover``**
(from `gokayfem/comfyui-lama-remover`), with ``LamaRemoverIMG`` as the
secondary node. See:

    * comfyui-spellcaster/spellcaster_core/node_factory.py
        -> ``return self._add("LamaRemover", {...})``
    * comfyui-spellcaster/spellcaster_core/workflows.py
        -> docstring "20: LamaRemover ..."
    * tests/e2e_audit.py _NATIVE_ACTION_NODES["lama.erase_selection"]
        -> ["LamaRemover"]
    * Voodoomancer/patches/PATCH_0009_LAMA_REGRESSION.md

This test asserts:

    1. ZERO quoted (i.e. code-active) occurrences of any phantom name
       anywhere in the spellcaster repo.
    2. At least one real ``LamaRemover`` reference exists in the
       canonical source files (positive control — guards against an
       over-eager future scrub deleting the correct class too).

The phantom names DO appear in repo source files as inline commentary
(PATCH_0009 cleanup notes, darktable's stale-note explanation). The
test ignores those by only matching the names when they appear inside
single or double quotes — i.e. as a class identifier string literal,
which is the only way ComfyUI would ever look them up.

Run from the repo root::

    python tests/test_lama_class_name_drift.py
"""

from __future__ import annotations

import os
import re
import sys
import traceback


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)


# --- Config ---------------------------------------------------------------

PHANTOM_NAMES = (
    "LaMaInpaint",
    "LaMaInpainting",
    "LaMaInpaintingModelLoader",
)

# A phantom hit only matters if the name appears inside a string literal
# (single or double quote). Comments / docstrings mentioning the name in
# backticks or prose don't drive runtime behavior. ``LaMaInpaintingModelLoader``
# is a strict superstring of ``LaMaInpainting`` so we search for the longest
# match first and exclude already-matched spans from the shorter search.
_QUOTED_PATTERNS = {
    name: re.compile(r"""['"]""" + re.escape(name) + r"""['"]""")
    for name in PHANTOM_NAMES
}

# File extensions we scan. Anything binary or non-source is skipped.
SOURCE_SUFFIXES = (
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".json", ".lua", ".rb", ".sh", ".ps1", ".html", ".vue", ".svelte",
    ".cfg", ".ini", ".toml", ".yaml", ".yml",
)

# Directories we never walk into (build artefacts, vendored deps,
# git internals).
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "build", "dist", ".pytest_cache", ".mypy_cache", "site-packages",
}

# This test file itself contains the phantom strings (as quoted entries
# in PHANTOM_NAMES) for legitimate reasons — the regex search shouldn't
# flag itself.
SELF_PATH = os.path.abspath(__file__)


# --- Helpers --------------------------------------------------------------

def iter_source_files(root):
    """Walk ``root`` yielding absolute paths to source files we should scan."""
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip-dirs in-place so os.walk doesn't descend into them.
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(SOURCE_SUFFIXES):
                continue
            full = os.path.join(dirpath, fn)
            if os.path.abspath(full) == SELF_PATH:
                continue
            yield full


def quoted_phantom_hits(path):
    """Return list of (lineno, name, line_text) for quoted phantom occurrences.

    Reads the file as UTF-8 (errors='replace' so a stray byte doesn't
    crash the whole walk).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    hits = []
    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        for name, pat in _QUOTED_PATTERNS.items():
            if pat.search(line):
                hits.append((lineno, name, line.rstrip()))
    return hits


# --- Cases ----------------------------------------------------------------

def case_no_quoted_phantoms_in_repo():
    """No source file in the spellcaster repo may contain a quoted phantom."""
    offenders = []
    for path in iter_source_files(_REPO):
        for lineno, name, line in quoted_phantom_hits(path):
            rel = os.path.relpath(path, _REPO)
            offenders.append(f"  {rel}:{lineno}  ({name})  {line.strip()}")
    if offenders:
        raise AssertionError(
            "Phantom LaMa class name(s) found as quoted literals:\n"
            + "\n".join(offenders)
            + "\n\nReplace with `LamaRemover` (and optionally `LamaRemoverIMG`)."
            + " See Voodoomancer/patches/PATCH_0009_LAMA_REGRESSION.md."
        )


def case_lama_remover_is_referenced_positive_control():
    """At least one of the canonical source files must reference
    ``LamaRemover``. If this fails, an over-eager refactor has likely
    wiped the correct class along with the phantom — investigate.
    """
    canonical_files = [
        os.path.join(_REPO, "comfyui-spellcaster", "spellcaster_core",
                     "node_factory.py"),
        os.path.join(_REPO, "comfyui-spellcaster", "spellcaster_core",
                     "workflows.py"),
        os.path.join(_REPO, "tests", "e2e_audit.py"),
    ]
    found_in = []
    missing = []
    for f in canonical_files:
        if not os.path.exists(f):
            missing.append(f)
            continue
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            if "LamaRemover" in fh.read():
                found_in.append(f)
    if missing:
        raise AssertionError(
            "Positive-control files missing from repo: "
            + ", ".join(os.path.relpath(m, _REPO) for m in missing)
        )
    if not found_in:
        raise AssertionError(
            "Positive control failed: none of "
            + ", ".join(os.path.relpath(f, _REPO) for f in canonical_files)
            + " mentions `LamaRemover`. Did a refactor wipe the real class too?"
        )


def case_canonical_node_factory_emits_lama_remover():
    """The build_lama_remove path in node_factory.py must explicitly add
    a node of class_type ``LamaRemover``. This is a tighter positive
    control than just-mentions-the-string — it confirms the call site
    that drives runtime is still correct.
    """
    nf = os.path.join(_REPO, "comfyui-spellcaster", "spellcaster_core",
                      "node_factory.py")
    if not os.path.exists(nf):
        raise AssertionError(f"missing canonical file: {nf}")
    with open(nf, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    # Match either single or double quoted "LamaRemover" passed as a
    # positional arg to ._add(...). Stay conservative — the patch doc
    # quotes the exact call at line 2017.
    if not re.search(r"""_add\(\s*['"]LamaRemover['"]""", text):
        raise AssertionError(
            "node_factory.py no longer calls self._add('LamaRemover', ...). "
            "build_lama_remove() may have been refactored to emit a different "
            "class — verify against the live ComfyUI /object_info catalogue."
        )


# --- Runner ---------------------------------------------------------------

CASES = [
    ("no quoted phantom LaMa names in repo",
        case_no_quoted_phantoms_in_repo),
    ("positive control: LamaRemover referenced in canonical files",
        case_lama_remover_is_referenced_positive_control),
    ("positive control: node_factory._add('LamaRemover', ...) intact",
        case_canonical_node_factory_emits_lama_remover),
]


def main():
    print("LaMa class-name drift regression guard")
    print("=" * 60)
    failures = []
    for label, fn in CASES:
        try:
            fn()
            print(f"  [OK]   {label}")
        except AssertionError as e:
            print(f"  [FAIL] {label}: {e}")
            failures.append(label)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR]  {label}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append(label)
    print("=" * 60)
    if failures:
        print(f"FAILED ({len(failures)}/{len(CASES)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASSED ({len(CASES)}/{len(CASES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
