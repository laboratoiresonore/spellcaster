"""Installer bootstrap splash.

Shown while bootstrap.py fetches the latest installer from GitHub (5-15
seconds on a cold cache). Under `--windowed` the .exe has no console,
so a silent fetch looked like a crash — that's the literal "exe does
nothing" in issue #7.

API mirrors ``antenna.splash``:

    from installer import splash
    sp = splash.show_splash()
    sp.status("Fetching latest installer…")
    ...
    sp.close()

Graceful degradation — returns a no-op handle if Tk is missing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

try:
    from . import theme  # type: ignore
except Exception:  # noqa: BLE001
    try:
        import theme  # type: ignore
    except Exception:  # noqa: BLE001
        theme = None  # pragma: no cover — splash degrades gracefully


# Inlined fallbacks if theme module fails to import (bundle corrupt).
_BG      = getattr(theme, "BG",      "#0B0715")
_BG_CARD = getattr(theme, "BG_CARD", "#110A1F")
_ACCENT  = getattr(theme, "ACCENT",  "#D122E3")
_TEXT    = getattr(theme, "TEXT",    "#FFFFFF")
_MUTED   = getattr(theme, "TEXT_MUTED", "#8E889D")
_FONT    = (getattr(theme, "FONT_FAMILY", "Segoe UI"), 10)
_TITLE   = (getattr(theme, "FONT_FAMILY", "Segoe UI"), 18, "bold")


def _asset_path() -> Optional[Path]:
    """Find the installer hero image across dev / PyInstaller layouts."""
    if theme is not None:
        for key in ("hero", "banner", "antenna"):
            p = theme.asset(key)
            if p:
                return p
    # Static fallbacks when theme module isn't available
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.extend([
            Path(meipass) / "assets" / "spellcaster_hero.png",
            Path(meipass) / "spellcaster_hero.png",
            Path(meipass) / "assets" / "readme_banner.png",
        ])
    here = Path(__file__).resolve().parent
    candidates.extend([
        here.parent / "assets" / "spellcaster_hero.png",
        here.parent / "assets" / "readme_banner.png",
    ])
    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


class _NullSplash:
    def status(self, _text: str) -> None: pass
    def close(self) -> None: pass


class _TkSplash:
    """Tk-based splash — runs on the calling thread, pumps events
    synchronously on every status() call. Simpler than a thread-based
    splash and plays well with PyInstaller's single-threaded startup.
    """

    def __init__(self, img_path: Optional[Path]):
        import tkinter as tk
        self._tk = tk
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg=_BG)

        w, h = 520, 420
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - w) // 2
        y = max(40, (sh - h) // 3)
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        if theme is not None:
            theme.try_set_window_icon(self._root)

        # Magenta accent strip across the top so the splash reads as
        # "Spellcaster" even at a glance.
        accent = tk.Frame(self._root, bg=_ACCENT, height=3)
        accent.pack(fill="x")

        container = tk.Frame(self._root, bg=_BG, bd=0)
        container.pack(fill="both", expand=True)

        # Logo
        self._img_ref = None
        if img_path and img_path.is_file():
            try:
                img = tk.PhotoImage(file=str(img_path))
                target = 260
                factor = max(1, max(img.width(), img.height()) // target)
                if factor > 1:
                    img = img.subsample(factor, factor)
                self._img_ref = img
                tk.Label(container, image=img, bd=0, bg=_BG).pack(pady=(28, 8))
            except Exception:  # noqa: BLE001
                self._img_ref = None

        tk.Label(
            container, text="Spellcaster",
            fg=_TEXT, bg=_BG, font=_TITLE,
        ).pack(pady=(4, 0))
        tk.Label(
            container, text="Premium Installer",
            fg=_ACCENT, bg=_BG, font=(_FONT[0], 11, "bold"),
        ).pack()

        self._status_var = tk.StringVar(value="Starting…")
        tk.Label(
            container, textvariable=self._status_var,
            fg=_MUTED, bg=_BG, font=_FONT,
            wraplength=460, justify="center",
        ).pack(pady=(12, 8))

        # Pulsing accent bar
        self._bar = tk.Canvas(
            container, width=360, height=4, bg=_BG, highlightthickness=0,
        )
        self._bar.pack(pady=(0, 24))
        self._pulse_x = -80
        self._closed = False
        self._pulse()

        try:
            self._root.update_idletasks()
            self._root.update()
        except self._tk.TclError:
            self._closed = True

    def _pulse(self) -> None:
        if self._closed:
            return
        try:
            self._bar.delete("pulse")
            self._bar.create_rectangle(
                self._pulse_x, 0, self._pulse_x + 80, 4,
                fill=_ACCENT, outline="", tags="pulse",
            )
            self._pulse_x += 10
            if self._pulse_x > 360:
                self._pulse_x = -80
            self._pulse_after = self._root.after(45, self._pulse)
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
        # Cancel the pending pulse `after` callback before destroying —
        # otherwise Tk logs "invalid command name ..._pulse" to stderr.
        pulse_after = getattr(self, "_pulse_after", None)
        if pulse_after is not None:
            try: self._root.after_cancel(pulse_after)
            except Exception: pass  # noqa: BLE001
        try:
            self._root.destroy()
        except Exception:  # noqa: BLE001
            pass


def show_splash():
    """Return a splash handle (.status(text) / .close()).

    Falls back to a silent no-op when Tk is missing or the display is
    unavailable. Respect ANTENNA_NO_SPLASH and SPELLCASTER_NO_SPLASH
    environment overrides so headless CI runs stay clean.
    """
    if os.environ.get("SPELLCASTER_NO_SPLASH") == "1":
        return _NullSplash()
    if os.environ.get("ANTENNA_NO_SPLASH") == "1":
        return _NullSplash()
    try:
        import tkinter  # noqa: F401
    except Exception:  # noqa: BLE001
        return _NullSplash()
    try:
        return _TkSplash(_asset_path())
    except Exception as e:  # noqa: BLE001
        print(f"[installer.splash] skipped ({type(e).__name__}: {e})",
              file=sys.stderr)
        return _NullSplash()
