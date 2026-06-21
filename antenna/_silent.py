"""Subprocess helpers that never flash a console window on Windows pythonw.

The antenna runs as ``pythonw.exe`` (windowless Python). On Windows, every
``subprocess.run`` / ``subprocess.Popen`` call without ``creationflags`` set
spawns its child with a brief console attached -- a cmd-window flash on the
operator's desktop. The 5-second heartbeat shells out to ``tailscale ip -4``
and ``nvidia-smi`` every cycle, producing a constant popup fiesta.

Use ``_silent.run(...)`` / ``_silent.Popen(...)`` instead of the bare
``subprocess.run`` / ``subprocess.Popen``. They are drop-in replacements
that always OR in CREATE_NO_WINDOW on Windows; on POSIX they pass through.

The other ``subprocess`` symbols you might need -- ``PIPE``, ``DEVNULL``,
``CompletedProcess``, ``TimeoutExpired``, ``CalledProcessError``, etc. --
are intentionally NOT re-exported here. Continue to ``import subprocess``
for those.
"""
from __future__ import annotations

import os
import subprocess

# 0x08000000 == CREATE_NO_WINDOW. Defined at module level so callers
# can also reference it directly if they're building their own creationflags
# bitmask (see firewall.py for the existing exemplar).
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _apply(kwargs: dict) -> dict:
    if os.name == "nt":
        kwargs["creationflags"] = (kwargs.get("creationflags", 0)
                                   | CREATE_NO_WINDOW)
    return kwargs


def run(*args, **kwargs):
    """``subprocess.run`` that never shows a console on Windows."""
    return subprocess.run(*args, **_apply(kwargs))


def Popen(*args, **kwargs):
    """``subprocess.Popen`` that never shows a console on Windows."""
    return subprocess.Popen(*args, **_apply(kwargs))
