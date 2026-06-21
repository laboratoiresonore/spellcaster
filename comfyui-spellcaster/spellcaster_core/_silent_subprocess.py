"""_silent_subprocess.py -- one-liner-installable silent-subprocess monkey-patch.

Mirrors the pattern proven in prometheus-client antenna's
prometheus_client/__init__.py: patches subprocess.Popen.__init__ once at
import time so every subprocess.{run,Popen,call,check_output,check_call}
call this process makes (or any module it imports makes transitively) is
automatically launched with CREATE_NO_WINDOW ORed into its creationflags.

Standalone -- no dependency on the antenna package -- so it doesn't
namespace-collide with the PyPI `prometheus-client` (metrics) library.

USAGE:
    # At the very top of any Python entry script that's been spamming
    # console windows on Windows (Laborantin canary_runner.py,
    # analyzer_stall_sentinel.py, etc.):
    import _silent_subprocess  # noqa -- side effect: patches Popen

CONTEXT (per FLEET-FUNCTION-ATLAS.md sec on silent-subprocess hot path,
2026-06-20): canary_runner + analyzer_stall_sentinel + Spellcaster ComfyUI
push + Voodoomancer cam push + Whimweaver nodes each implement subprocess
hardening on their own, with subtle bugs, triggering console flashes every
20-60s. This module consolidates the fix.
"""
from __future__ import annotations

import os
import subprocess

_PC_SILENT_PATCHED = "_pc_silent_patched"

if os.name == "nt" and not getattr(subprocess.Popen, _PC_SILENT_PATCHED, False):
    _CREATE_NO_WINDOW = 0x08000000
    _orig_init = subprocess.Popen.__init__

    def _silent_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        cf = kwargs.get("creationflags", 0) or 0
        kwargs["creationflags"] = cf | _CREATE_NO_WINDOW
        _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _silent_init  # type: ignore[method-assign]
    setattr(subprocess.Popen, _PC_SILENT_PATCHED, True)

    # Also suppress kernel-loader DLL dialogs that can interrupt headless
    # tray + scheduled-task runs ("foobar.dll: side-by-side configuration
    # is incorrect" etc.). Safe + idempotent.
    try:
        import ctypes
        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOOPENFILEERRORBOX = 0x8000
        ctypes.windll.kernel32.SetErrorMode(
            SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX
        )
    except Exception:
        pass
