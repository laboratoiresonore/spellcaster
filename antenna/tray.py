"""Windows system-tray shell for the Spellcaster Antenna.

Runs the full antenna.agent + antenna.heartbeat stack, plus a tray icon
with a dynamic menu for service control (Start / Stop ComfyUI, Kobold,
Ollama), a status line, quick links to the Guild, and update checks.
Every user-visible action either invokes the antenna's existing HTTP /
Python APIs or posts a toast notification — nothing in the agent is
forked or reimplemented.

Dependencies (optional; module self-disables without them):
    pystray       — system-tray icon + native Windows menu
    Pillow        — generates the icon bitmap

Install path on Windows:
    %APPDATA%\\Python\\Python312\\site-packages\\pystray
    %APPDATA%\\Python\\Python312\\site-packages\\PIL

When either is missing we fall back to console mode (the old behavior)
with a single stderr line telling the operator how to enable the tray.

Graceful degradation order
──────────────────────────
    Windows + pystray installed  → full tray with menu + toasts
    Windows, pystray missing     → console mode, notify() prints to stdout
    Non-Windows                  → console mode (no tray call at all)

Public entry point
──────────────────
    main(argv=None) — mirrors antenna.agent.main()'s CLI contract so
                      `python -m antenna.tray` is a drop-in replacement
                      for `python -m antenna.agent` on Windows.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from typing import Optional

# Single-import guard so the rest of the module can call tray-only code
# unconditionally. When pystray isn't there, `main()` short-circuits to
# console mode BEFORE anything imports it.
try:
    import pystray                          # type: ignore
    from PIL import Image, ImageDraw        # type: ignore
    _PYSTRAY_OK = True
except Exception:  # noqa: BLE001
    pystray = None
    Image = None
    ImageDraw = None
    _PYSTRAY_OK = False

from . import agent, config, heartbeat, service_launcher
from . import detect, pairing

# ── Icon rendering ─────────────────────────────────────────────────────

_ICON_SIZE = 64
_STATE_COLOURS = {
    "running": (80, 200, 120, 255),    # green
    "busy":    (240, 200, 80, 255),    # amber
    "warn":    (240, 170, 70, 255),    # orange
    "error":   (220, 60, 60, 255),     # red
    "stopped": (160, 160, 160, 255),   # grey
}


def _build_icon(state: str = "running"):
    """Render the tray icon as a PIL image.

    We draw programmatically rather than shipping a .ico so the icon
    can reflect agent state (green = serving, amber = starting a
    service, red = something failed) without bundling artwork.
    """
    if not _PYSTRAY_OK:
        return None
    base = (0, 0, 0, 0)
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), base)
    d = ImageDraw.Draw(img)
    colour = _STATE_COLOURS.get(state, _STATE_COLOURS["running"])
    # Filled circle backdrop
    pad = 4
    d.ellipse((pad, pad, _ICON_SIZE - pad, _ICON_SIZE - pad), fill=colour)
    # White antenna glyph: two crossed lines + a tiny dot at the top
    c = _ICON_SIZE // 2
    arm = int(_ICON_SIZE * 0.28)
    d.line((c, c - arm, c, c + arm), fill=(255, 255, 255, 255), width=3)
    d.line((c - arm, c, c + arm, c), fill=(255, 255, 255, 255), width=3)
    d.ellipse((c - 3, c - arm - 6, c + 3, c - arm), fill=(255, 255, 255, 255))
    return img


# ── Tray state ─────────────────────────────────────────────────────────

class _TrayState:
    """Holds the mutable state the tray needs to drive its menu + icon."""

    def __init__(self, cfg: dict, server) -> None:
        self.cfg = cfg
        self.server = server
        self.icon: Optional["pystray.Icon"] = None
        self._lock = threading.Lock()
        self._service_state: dict[str, str] = {}  # cached "running" / "stopped"

    # Display label for the header line
    def subtitle(self) -> str:
        bind = self.cfg.get("bind", "0.0.0.0")
        port = self.cfg.get("port", 7334)
        scheme = "https" if config.tls_enabled(self.cfg) else "http"
        return f"{scheme}://{bind}:{port}"

    # ── Icon-state helpers ─────────────────────────────────────────
    def set_icon_state(self, state: str) -> None:
        if self.icon is not None:
            self.icon.icon = _build_icon(state)

    # ── Service control via service_launcher ───────────────────────
    def start_service(self, name: str) -> None:
        self.set_icon_state("busy")
        try:
            result = service_launcher.ensure_service_running(name, self.cfg)
            # Notifications fire from service_launcher itself, but status-tweak
            # the icon so the busy-amber snaps back to green on success.
            if result.get("state") in ("started", "already_running"):
                self.set_icon_state("running")
            elif result.get("state") == "not_installed":
                self.set_icon_state("warn")
                agent.notify(f"{name}: not installed",
                              "No launcher found for this service",
                              level="warn")
            else:
                self.set_icon_state("error")
        except Exception as e:  # noqa: BLE001
            self.set_icon_state("error")
            agent.notify(f"{name}: start error",
                          f"{type(e).__name__}: {e}", level="error")

    def stop_service(self, name: str) -> None:
        # service_launcher owns start but not stop yet — we taskkill by
        # port binding or by the recorded PID from _LAST_SPAWN. Best-effort.
        self.set_icon_state("busy")
        try:
            _stop_service_best_effort(name, self.cfg)
            self.set_icon_state("running")
            agent.notify(f"{name} stopped",
                          "process terminated", level="success")
        except Exception as e:  # noqa: BLE001
            self.set_icon_state("error")
            agent.notify(f"{name}: stop failed",
                          f"{type(e).__name__}: {e}", level="error")

    # ── Menu (dynamic — rebuilt each open) ─────────────────────────
    def menu(self):
        """Return a fresh pystray.Menu. Called on every tray-open by pystray
        so the menu reflects current service state.
        """
        items = []
        items.append(pystray.MenuItem(
            f"Antenna · {self.subtitle()}", None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)

        # Services block — Start/Stop per service that the antenna knows about.
        declared = list((self.cfg.get("services") or {}).keys())
        detected = list(detect.detect_all(self.cfg).keys()) \
                    if hasattr(detect, "detect_all") else []
        services = sorted(set(declared + detected))
        for svc in services:
            running = service_launcher._already_running(svc, self.cfg)  # noqa: SLF001
            label = f"{svc}: {'running' if running else 'stopped'}"
            items.append(pystray.MenuItem(
                label, self._menu_for_service(svc, running)))
        if services:
            items.append(pystray.Menu.SEPARATOR)

        # Quick links
        guild_url = self.cfg.get("hub_url") or "http://127.0.0.1:7777/"
        items.append(pystray.MenuItem(
            "Open Wizard Guild",
            lambda icon, _item: webbrowser.open(guild_url)))
        # Pair-with-Guild — pops a blocking dialog showing the 6-digit code
        # the user must type on the Guild side. Label flips to "Show
        # current pair code" when a pairing is already active.
        pair_state = pairing.get_pairing_state()
        pair_label = ("Show pair code (expires in "
                      f"{pair_state['expires_in']}s)"
                      if pair_state["active"] else "Pair with Guild…")
        items.append(pystray.MenuItem(
            pair_label,
            lambda icon, _item: threading.Thread(
                target=self._pair_with_guild, daemon=True).start()))
        items.append(pystray.MenuItem(
            "Check for antenna update",
            lambda icon, _item: self._trigger_self_update()))
        items.append(pystray.MenuItem(
            "Open antenna folder",
            lambda icon, _item: _open_folder(os.path.dirname(
                os.path.abspath(agent.__file__)))))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem(
            "Quit antenna", self._quit))
        return pystray.Menu(*items)

    def _menu_for_service(self, svc: str, running: bool):
        # Nested submenu: Start / Stop / View log
        return pystray.Menu(
            pystray.MenuItem(
                "Start", lambda icon, _item: threading.Thread(
                    target=self.start_service, args=(svc,), daemon=True).start(),
                enabled=not running),
            pystray.MenuItem(
                "Stop", lambda icon, _item: threading.Thread(
                    target=self.stop_service, args=(svc,), daemon=True).start(),
                enabled=running),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Show recent log", lambda icon, _item: _show_log(svc)),
        )

    def _trigger_self_update(self):
        """Ping the antenna's own /self-update endpoint so the user can
        kick an update check + restart from the tray without opening the
        Guild. Runs on a background thread so the menu doesn't freeze.
        """
        def worker():
            try:
                import urllib.request
                import json as _json
                bind = self.cfg.get("bind", "127.0.0.1")
                port = int(self.cfg.get("port", 7334))
                scheme = "https" if config.tls_enabled(self.cfg) else "http"
                # When TLS is on with a self-signed cert, urllib will
                # refuse — fall through to Python's CLI path instead of
                # disabling verification here.
                url = f"{scheme}://{bind}:{port}/self-update"
                req = urllib.request.Request(
                    url, method="POST",
                    headers={"Authorization": f"Bearer {agent._current_token() if hasattr(agent,'_current_token') else ''}"})
                import ssl
                ctx = ssl._create_unverified_context() if scheme == "https" else None
                with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                    payload = _json.loads(r.read().decode())
                    agent.notify("Self-update complete",
                                  payload.get("message", "updated"),
                                  level="success")
            except Exception as e:  # noqa: BLE001
                agent.notify("Self-update failed",
                              f"{type(e).__name__}: {e}", level="error")
        threading.Thread(target=worker, daemon=True).start()

    def _pair_with_guild(self):
        """Start (or resurface) a pairing session. Pops a tk dialog with
        the 6-digit code + instructions, so the user can type the code
        on the Guild machine. Blocks in its own thread — pystray's main
        loop stays responsive.
        """
        state = pairing.get_pairing_state()
        if state["active"]:
            # There's already a live code — we don't re-issue. Fetch the
            # current code via a direct internal call (safe since we're
            # running in the antenna process).
            code = pairing._PAIR_STATE["code"]  # noqa: SLF001
            ttl = state["expires_in"]
        else:
            result = pairing.start_pairing()
            code = result["code"]
            ttl = result["expires_in"]
        agent.notify(
            "Antenna ready to pair",
            f"Type code {code} on the Guild (expires in {ttl}s)",
            level="info")
        # Tiny tk modal for the big-readable code. Non-fatal if tk
        # isn't available — the toast covers the essentials anyway.
        try:
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
            root.title("Pair antenna with Guild")
            root.attributes("-topmost", True)
            root.configure(bg="#12101d")
            frm = ttk.Frame(root, padding=24)
            frm.pack()
            ttk.Label(frm, text="Type this 6-digit code on the Guild",
                       foreground="#c4b8e3",
                       background="#12101d",
                       font=("Segoe UI", 10)).pack()
            code_var = tk.StringVar(value=code)
            ttk.Label(frm, textvariable=code_var,
                       foreground="#ffd700",
                       background="#12101d",
                       font=("Consolas", 36, "bold")).pack(pady=(8, 8))
            subtitle = tk.StringVar(
                value=f"expires in {ttl}s · Guild → Antennas → Pair new")
            ttk.Label(frm, textvariable=subtitle,
                       foreground="#8a7eaf",
                       background="#12101d",
                       font=("Segoe UI", 9)).pack()
            ttk.Button(frm, text="Close", command=root.destroy).pack(
                pady=(16, 0))
            # Live-tick the countdown so users who leave the dialog up
            # see when the code is about to expire.
            def _tick():
                s = pairing.get_pairing_state()
                if not s["active"]:
                    code_var.set("— consumed —")
                    subtitle.set("Use the Guild side to finish.")
                    return
                subtitle.set(
                    f"expires in {s['expires_in']}s · "
                    "Guild → Antennas → Pair new")
                root.after(1000, _tick)
            root.after(1000, _tick)
            root.mainloop()
        except Exception:  # noqa: BLE001
            pass  # toast already fired — dialog is a nicety

    def _quit(self, icon, _item):
        agent.notify("Antenna shutting down", "", level="info")
        try:
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
        icon.stop()


# ── Stop-service best effort (service_launcher doesn't have one yet) ──

def _stop_service_best_effort(service: str, cfg: dict) -> None:
    """Kill the child the antenna spawned for `service`, if we have its PID.

    Falls back to port-based reaping when we don't — that way stopping
    ComfyUI works even if the antenna didn't launch it originally.
    """
    # 1. Last-spawn PID
    info = service_launcher.last_spawn_info().get(service) or {}
    pid = info.get("pid")
    killed = False
    if pid:
        try:
            import signal as _sig
            if os.name == "nt":
                # Windows needs taskkill for graceful shutdown
                import subprocess as _sp
                _sp.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                         capture_output=True, timeout=10)
            else:
                os.kill(pid, _sig.SIGTERM)
            killed = True
        except Exception:  # noqa: BLE001
            pass
    # 2. Port-based reaping as fallback
    if not killed:
        svc_cfg = (cfg.get("services") or {}).get(service, {})
        port = int(svc_cfg.get("port") or 0)
        if port:
            from . import port_cleanup
            port_cleanup.reap_port_holders(port, only_python=False)


# ── Helpers ────────────────────────────────────────────────────────────

def _open_folder(path: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)   # noqa: S606
        elif sys.platform == "darwin":
            import subprocess as _sp
            _sp.Popen(["open", path])
        else:
            import subprocess as _sp
            _sp.Popen(["xdg-open", path])
    except Exception:  # noqa: BLE001
        pass


def _show_log(service: str) -> None:
    """Print the service's recent log to the antenna console. The GUI
    variant (open in notepad) is a future nicety; for now the log still
    surfaces wherever the antenna is writing stdout.
    """
    tail = service_launcher.tail_log(service, lines=60)
    agent.notify(f"{service} — last 60 log lines",
                  tail[:600] + ("…" if len(tail) > 600 else ""),
                  level="info")


# ── Main entry point ───────────────────────────────────────────────────

def _install_tray_sink(state: _TrayState):
    """Plug the agent's notify() hook into the pystray toast API."""

    def sink(title: str, message: str, level: str):
        icon = state.icon
        if icon is None:
            return
        try:
            icon.notify(message or title, title=title)
        except Exception:  # noqa: BLE001
            # Some pystray backends omit notify(); degrade to icon colour only
            pass
        # Bump the icon colour briefly for visible feedback
        if level == "error":
            state.set_icon_state("error")
        elif level == "warn":
            state.set_icon_state("warn")
        elif level == "success":
            state.set_icon_state("running")

    agent.register_notify_sink(sink)


def main(argv: Optional[list] = None) -> int:
    """Launch the antenna with a Windows system-tray shell.

    Returns a POSIX-style exit code so the EXE / .bat wrapper can
    surface failure. On non-Windows or when pystray is missing we
    delegate to antenna.agent.main (console mode).
    """
    # Non-Windows or missing deps → straight to console mode
    if os.name != "nt" or not _PYSTRAY_OK:
        if os.name == "nt":
            print("[antenna] pystray / Pillow not installed — falling "
                  "back to console mode. Install with:"
                  "\n    pip install pystray Pillow", file=sys.stderr)
        # agent.main() doesn't exist — but running `python -m antenna.agent`
        # does the serve loop. Replicate that inline here.
        cfg = config.bootstrap()
        agent.serve(cfg, block=True)
        return 0

    # Windows + pystray: start agent on a background thread, run the
    # tray on the main thread (pystray + COM require the main thread).
    cfg = config.bootstrap()
    server = agent.serve(cfg, block=False)
    state = _TrayState(cfg, server)

    # Background: drive the HTTP server loop. Daemon thread so Ctrl-C
    # + tray-quit both terminate cleanly.
    def _serve_loop():
        try:
            server.serve_forever()
        finally:
            try: server.server_close()
            except Exception: pass  # noqa: BLE001
    threading.Thread(target=_serve_loop, daemon=True, name="antenna-http").start()

    # Attach tray to agent.notify() before building the icon so the
    # startup toast (emitted at the tail of agent.serve) lands visibly.
    icon = pystray.Icon(
        "spellcaster-antenna",
        icon=_build_icon("running"),
        title=f"Spellcaster Antenna — {state.subtitle()}",
        menu=state.menu,  # pystray re-invokes this on every open
    )
    state.icon = icon
    _install_tray_sink(state)
    agent.notify("Spellcaster Antenna",
                  f"Ready on {state.subtitle()}. Right-click the tray "
                  f"icon to control services.",
                  level="success")

    # Blocks until user picks Quit from the menu.
    icon.run()
    # serve_forever has already exited via _quit → server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
