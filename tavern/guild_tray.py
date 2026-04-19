"""Windows system-tray shell for the Wizard Guild.

Counterpart to antenna/tray.py. The Guild is a headless HTTP server +
browser UI, so the tray's job is:

  - Keep the Guild process alive without stealing the foreground console
  - Offer a one-click "Open Wizard Guild" menu item (relaunches the
    browser at the Guild URL)
  - Offer Quit that cleanly shuts down the HTTPServer + child processes
  - Surface status transitions (boot / exit) as native toast balloons

It does NOT fork or reimplement any of guild_launcher.main(); the
launcher still runs the full boot flow in a daemon thread and posts
notifications here via the notify() hook.

Dependencies — all optional, module self-disables when missing:
    pystray   — tray icon + native menu
    Pillow    — programmatic icon bitmap

Public entry points
───────────────────
    run_tray(guild_url, shutdown_cb) — blocks the caller thread; used
        by guild_launcher.main() to supersede its Ctrl-C wait loop.
    notify(title, body)              — surface a toast; no-op when the
        tray isn't running (launcher still prints the event to stdout).
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from typing import Callable, Optional

try:
    import pystray                          # type: ignore
    from PIL import Image, ImageDraw        # type: ignore
    _PYSTRAY_OK = True
except Exception:  # noqa: BLE001
    pystray = None
    Image = None
    ImageDraw = None
    _PYSTRAY_OK = False


# ── Icon rendering ────────────────────────────────────────────────────
#
# Draws a 64×64 gold-on-purple "WG" glyph so the tray entry reads as
# the Wizard Guild without shipping a separate .ico. Matches the
# Guild's splash gradient (purple → gold).

_ICON_SIZE = 64
_PURPLE = (106, 27, 154, 255)
_GOLD   = (255, 215, 0, 255)
_GREY   = (160, 160, 160, 255)
_RED    = (220, 60, 60, 255)


def _build_icon(state: str = "running"):
    if not _PYSTRAY_OK:
        return None
    # Background circle uses purple for running/paired, grey while
    # booting, red if the server died. The glyph colour stays gold
    # across states so users can spot the tray entry at a glance.
    bg = {"running": _PURPLE, "booting": _GREY,
           "error":   _RED,    "stopped": _GREY}.get(state, _PURPLE)
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, _ICON_SIZE - 2, _ICON_SIZE - 2), fill=bg)
    # WG glyph — chunky so it reads at 16px system-tray size.
    try:
        from PIL import ImageFont  # type: ignore
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None
    text = "WG"
    try:
        if font is not None:
            bbox = d.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
        else:
            tw, th = 24, 14
    except Exception:  # noqa: BLE001
        tw, th = 24, 14
    d.text(((_ICON_SIZE - tw) / 2 - 2, (_ICON_SIZE - th) / 2 - 4),
            text, fill=_GOLD, font=font)
    return img


# ── Notification hook ─────────────────────────────────────────────────
#
# Mirrors antenna.agent.notify() — the launcher can call this at any
# lifecycle moment and the tray will surface it as a balloon toast.
# Before the tray starts, events print to stdout so we never lose
# telemetry in console-only environments.

_ICON_REF: Optional["pystray.Icon"] = None
_STATE = "booting"


def notify(title: str, body: str = "", level: str = "info") -> None:
    msg = f"[guild][{level}] {title}"
    if body:
        msg += f" — {body}"
    print(msg, flush=True)
    if _ICON_REF is None:
        return
    try:
        _ICON_REF.notify(body or title, title=title)
    except Exception:  # noqa: BLE001
        pass


def set_state(state: str) -> None:
    """Flip the tray icon colour so users see boot → running → stopped
    transitions without opening the menu."""
    global _STATE
    _STATE = state
    if _ICON_REF is None or not _PYSTRAY_OK:
        return
    try:
        _ICON_REF.icon = _build_icon(state)
    except Exception:  # noqa: BLE001
        pass


# ── Tray controller ───────────────────────────────────────────────────

class _TrayController:
    def __init__(self, guild_url: str, shutdown_cb: Callable[[], None]):
        self.guild_url = guild_url
        self.shutdown_cb = shutdown_cb
        self.icon: Optional["pystray.Icon"] = None

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                lambda _i: "Wizard Guild: running" if _STATE == "running"
                           else f"Wizard Guild: {_STATE}",
                None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Wizard Guild…",
                              lambda _i, _it: self._open_browser(),
                              default=True),
            pystray.MenuItem("Connect an app…",
                              lambda _i, _it: self._open_connect_app()),
            pystray.MenuItem("Copy Guild URL",
                              lambda _i, _it: self._copy_url()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda _i, _it: self._quit()),
        )

    def _open_connect_app(self):
        # Open the Guild UI with the ?connect_app=1 query flag so the
        # front-end auto-pops the local Connect-an-app picker. Same
        # popover used by right-click on antenna chips, but pre-targeted
        # at 'local'. Keeps tray and chip UX unified.
        try:
            sep = '&' if '?' in self.guild_url else '?'
            webbrowser.open(f"{self.guild_url}{sep}connect_app=1")
        except Exception as e:  # noqa: BLE001
            notify("Could not open Connect dialog",
                    str(e)[:200], level="error")

    def _open_browser(self):
        try:
            webbrowser.open(self.guild_url)
        except Exception as e:  # noqa: BLE001
            notify("Could not open browser", str(e)[:200], level="error")

    def _copy_url(self):
        # Best-effort clipboard copy. Falls back to a toast showing
        # the URL if no clipboard binding is available.
        try:
            if sys.platform == "win32":
                import subprocess
                subprocess.run(["clip"], input=self.guild_url.encode("utf-16le"),
                                check=False)
                notify("Guild URL copied", self.guild_url)
                return
        except Exception:  # noqa: BLE001
            pass
        notify("Guild URL", self.guild_url)

    def _quit(self):
        notify("Wizard Guild shutting down", "",  level="info")
        try:
            # Shutdown runs on a thread so pystray's main loop can tear
            # down cleanly while the HTTPServer stops accepting.
            threading.Thread(target=self.shutdown_cb, daemon=True).start()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
        if self.icon is not None:
            self.icon.stop()


def run_tray(guild_url: str, shutdown_cb: Callable[[], None]) -> bool:
    """Block the caller thread while the Guild tray is alive.

    Returns True if the tray started, False when pystray is missing
    (the caller then falls back to the usual Ctrl-C sleep loop).
    """
    if not _PYSTRAY_OK:
        print("  [tray] pystray/Pillow unavailable — install them to "
              "get a system-tray icon. Falling back to console mode.")
        return False
    global _ICON_REF
    ctrl = _TrayController(guild_url, shutdown_cb)
    image = _build_icon("running")
    ctrl.icon = pystray.Icon(
        "wizard_guild",
        icon=image,
        title="Wizard Guild",
        menu=ctrl._menu(),
    )
    _ICON_REF = ctrl.icon
    set_state("running")
    notify("Wizard Guild online", guild_url)
    try:
        ctrl.icon.run()   # blocks until _quit() calls icon.stop()
    finally:
        _ICON_REF = None
        set_state("stopped")
    return True
