"""Antenna startup splash.

Shown while the tray main() bootstraps the agent — config/token/cert
generation, _autopopulate_services probing the machine, HTTP server
binding. That sequence can take several seconds on first boot or when
the network detection probes time out; a silent EXE feels like it
crashed. The splash gives the user immediate visual feedback plus a
stepwise status line.

The module is import-safe on machines without Tkinter: if tkinter or
the logo asset can't be loaded, show_splash() returns a no-op handle
with the same API, so callers never need to isinstance-check.

Typical use:

    from . import splash
    s = splash.show_splash()
    s.status("Loading config…")
    ...
    s.status("Starting HTTP server…")
    ...
    s.close()
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Optional

# ── Theme (matches Wizard Guild / installer palette) ─────────────────
_BG = "#0B0715"
_ACCENT = "#D122E3"
_TEXT = "#E2DFEB"
_SUBTEXT = "#8B7CA8"
_FONT = ("Segoe UI", 10)
_TITLE_FONT = ("Segoe UI", 16, "bold")


def _asset_path() -> Optional[Path]:
    """Locate the splash logo across dev / PyInstaller / installed layouts.

    PyInstaller stashes bundled data under `sys._MEIPASS`; in dev we read
    from `antenna/assets/`; the tavern copy is a last-resort fallback.
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "antenna" / "assets" / "antenna_logo.png")
        candidates.append(Path(meipass) / "assets" / "antenna_logo.png")
    here = Path(__file__).resolve().parent
    candidates.append(here / "assets" / "antenna_logo.png")
    candidates.append(here.parent / "tavern" / "static" / "assets" / "30_antenna_logo.png")
    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


class _NullSplash:
    """No-op splash used when Tk / PIL unavailable."""

    def status(self, _text: str) -> None:
        pass

    def close(self) -> None:
        pass


class _TkSplash:
    """Tk-based splash window. Runs on the CALLING thread — the Tk mainloop
    is driven via `update_idletasks()` whenever `status()` or `close()` is
    called, so the window stays responsive without needing a separate
    thread to pump events. pystray requires the main thread, so doing
    the splash on the main thread is intentional.
    """

    def __init__(self, img_path: Optional[Path]):
        import tkinter as tk
        self._tk = tk
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg=_BG)

        # Centre on the primary screen
        w, h = 420, 520
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        container = tk.Frame(self._root, bg=_BG, bd=0)
        container.pack(fill="both", expand=True)

        # ── Logo ──
        self._img_ref = None  # hold ref so Tk doesn't GC
        if img_path and img_path.is_file():
            try:
                img = tk.PhotoImage(file=str(img_path))
                target = 360
                factor = max(1, max(img.width(), img.height()) // target)
                if factor > 1:
                    img = img.subsample(factor, factor)
                self._img_ref = img
                tk.Label(container, image=img, bd=0, bg=_BG).pack(pady=(24, 8))
            except Exception:  # noqa: BLE001
                self._img_ref = None

        tk.Label(
            container, text="Spellcaster Antenna",
            fg=_TEXT, bg=_BG, font=_TITLE_FONT,
        ).pack(pady=(6, 2))

        self._status_var = tk.StringVar(value="Starting…")
        tk.Label(
            container, textvariable=self._status_var,
            fg=_SUBTEXT, bg=_BG, font=_FONT, wraplength=380, justify="center",
        ).pack(pady=(0, 8))

        # Indeterminate progress bar — a single thin accent line that
        # pulses by sliding a coloured segment across. No ttk.Progressbar
        # because it ignores our theme colours on Windows.
        self._bar = tk.Canvas(
            container, width=320, height=4, bg=_BG,
            highlightthickness=0,
        )
        self._bar.pack(pady=(0, 20))
        self._pulse_x = -60
        self._pulse_segment_width = 60
        self._closed = False
        self._schedule_pulse()

        try:
            self._root.update_idletasks()
            self._root.update()
        except self._tk.TclError:
            pass

    def _schedule_pulse(self) -> None:
        if self._closed:
            return
        try:
            self._bar.delete("pulse")
            w = 320
            x1 = self._pulse_x
            x2 = x1 + self._pulse_segment_width
            self._bar.create_rectangle(
                x1, 0, x2, 4, fill=_ACCENT, outline="", tags="pulse",
            )
            self._pulse_x += 8
            if self._pulse_x > w:
                self._pulse_x = -60
            self._root.after(40, self._schedule_pulse)
        except self._tk.TclError:
            self._closed = True

    def status(self, text: str) -> None:
        if self._closed:
            return
        try:
            self._status_var.set(text)
            self._root.update_idletasks()
            self._root.update()
        except self._tk.TclError:
            self._closed = True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._root.destroy()
        except Exception:  # noqa: BLE001
            pass


def show_splash():
    """Return a splash handle with .status(text) and .close() methods.

    Silent fallback to a no-op object when Tk isn't available, so the
    antenna still boots on headless boxes or minimal Python installs.
    """
    if os.environ.get("ANTENNA_NO_SPLASH") == "1":
        return _NullSplash()
    # Respect non-interactive runs — no splash when stdout is redirected
    # to a pipe (services / Docker / scripted).
    if not sys.stdout.isatty() and os.name != "nt":
        return _NullSplash()
    try:
        import tkinter  # noqa: F401
    except Exception:  # noqa: BLE001
        return _NullSplash()
    try:
        return _TkSplash(_asset_path())
    except Exception as e:  # noqa: BLE001
        # Tk sometimes fails on headless Windows sessions (no display).
        # Never let a splash failure block the antenna from booting.
        print(f"[antenna.splash] skipped ({type(e).__name__}: {e})",
              file=sys.stderr)
        return _NullSplash()
