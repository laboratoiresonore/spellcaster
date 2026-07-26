"""pytest bootstrap -- make `spellcaster_core` importable from the test suite.

WHY THIS EXISTS (2026-07-18)
The suite could not run AT ALL: `pytest tests/` reported 13 collection errors
and `ModuleNotFoundError: No module named 'spellcaster_core'`, and
`tests/test_model_coverage.py` died on `spellcaster_core.architectures`.

The package was never missing -- it was just never on `sys.path`. It lives at
`plugins/gimp/comfyui-connector/spellcaster_core/` (52 modules, the real one).
There is a SECOND, near-empty copy at `comfyui-spellcaster/spellcaster_core/`
containing only `cli.py`; importing that one is what makes the failure look
like "the package is broken" rather than "the path is wrong". The connector
copy is the authoritative one and is what this file selects.

Consequence of the outage: `.githooks/pre-push` enforces HERMES-EDITS-CODE
Stage 5 ("record at least one PASSED test"), so with no runnable test NOTHING
could be pushed to this repo through the sanctioned path.

If the two copies are ever reconciled (they should be -- see
`_audit/hermes-edits/`), update the path below rather than adding a third.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_CORE_PARENT = _ROOT / "plugins" / "gimp" / "comfyui-connector"

if _CORE_PARENT.is_dir() and str(_CORE_PARENT) not in sys.path:
    # Prepend: the near-empty comfyui-spellcaster copy must never win.
    sys.path.insert(0, str(_CORE_PARENT))
