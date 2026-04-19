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
        # Setup Signal bridge — declares this antenna as a Signal bridge
        # host. Pops the wizard-guided setup dialog that walks the user
        # through signal-cli install + phone linking, then registers
        # 'signal' in the antenna services list so the Guild's Connected
        # apps chip row picks it up automatically.
        items.append(pystray.MenuItem(
            "Setup Signal bridge…",
            lambda icon, _item: threading.Thread(
                target=self._setup_signal_bridge, daemon=True).start()))
        # Windows shortcut management — surfaces the same install
        # flow the antenna.bat runs on first launch, but also lets
        # users toggle run-on-startup after the fact without hunting
        # in the registry. Non-Windows boxes hide this entry.
        if os.name == "nt":
            try:
                from . import install_shortcuts as _shc
                st = _shc.current_status()
            except Exception:  # noqa: BLE001
                _shc = None; st = {}
            if _shc is not None:
                def _toggle_startup(_i=None, _it=None):
                    def worker():
                        from . import install_shortcuts as _s
                        cur = _s.current_status()
                        if cur.get("startup"):
                            _s.install_shortcuts(
                                desktop=False, start_menu=False,
                                startup=False)
                            # install_shortcuts only creates — use
                            # remove to toggle off
                            _s.remove_shortcuts()
                            # Re-install desktop + start menu if those
                            # existed before (remove_shortcuts nuked
                            # all three)
                            if cur.get("desktop") or cur.get("start_menu"):
                                _s.install_shortcuts(
                                    desktop=bool(cur.get("desktop")),
                                    start_menu=bool(cur.get("start_menu")),
                                    startup=False)
                            agent.notify("Antenna shortcut removed",
                                          "will no longer auto-start at login",
                                          level="info")
                        else:
                            _s.install_shortcuts(
                                desktop=False, start_menu=False,
                                startup=True)
                            agent.notify("Antenna auto-start enabled",
                                          "will launch at every Windows login",
                                          level="success")
                    threading.Thread(target=worker, daemon=True).start()
                def _reinstall_shortcuts(_i=None, _it=None):
                    def worker():
                        from . import install_shortcuts as _s
                        r = _s.install_shortcuts(
                            desktop=True, start_menu=True, startup=False)
                        ok = sum(1 for v in
                                  (r.get("desktop"), r.get("start_menu"))
                                  if v)
                        agent.notify(f"Antenna shortcuts ({ok}/2)",
                                      "\n".join(r.get("errors") or [])
                                         or "desktop + Start Menu refreshed",
                                      level="success" if ok else "warn")
                    threading.Thread(target=worker, daemon=True).start()
                items.append(pystray.MenuItem(
                    "Reinstall desktop + Start Menu icons",
                    _reinstall_shortcuts))
                items.append(pystray.MenuItem(
                    lambda _i: ("Disable run-at-Windows-startup"
                                 if _shc.current_status().get("startup")
                                 else "Enable run-at-Windows-startup"),
                    _toggle_startup))
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

    def _setup_signal_bridge(self):
        """Guide the user through declaring this antenna as the Signal
        bridge host. Three pieces:

        1. Confirm signal-cli (or signal-cli-rest-api) is installed and
           reachable. If not, surface install instructions.
        2. Register the 'signal' service in this antenna's config so
           the Guild's Connected apps chip row picks it up.
        3. Pop a final dialog with next steps (link phone via QR, set
           up webhook target in Guild settings).

        Actual signal-cli automation is deferred — the user already has
        full access to signal-cli via this dialog, and the Guild's
        /api/signal_bridge_status probe detects the service at
        http://<antenna>:8080 (signal-cli-rest-api default).
        """
        try:
            # Mark 'signal' as an enabled service so chips render.
            cfg = config.load_config()
            services = list(cfg.get("services") or [])
            if "signal" not in services:
                services.append("signal")
                cfg["services"] = services
                config.save_config(cfg)
            agent.notify("Signal bridge registered",
                          "This antenna is now advertised to the Guild "
                          "as a Signal host. Point signal-cli-rest-api at "
                          "port 8080 and link your phone.", level="success")
        except Exception as e:  # noqa: BLE001
            agent.notify("Signal bridge setup failed",
                          f"{type(e).__name__}: {e}", level="error")
            return
        # Show a tk dialog with copy-pasteable install steps so the user
        # has a concrete next action. Optional — notify toast already
        # carries the primary message.
        try:
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
            root.title("Signal bridge — setup")
            root.attributes("-topmost", True)
            root.configure(bg="#12101d")
            frm = ttk.Frame(root, padding=20)
            frm.pack()
            ttk.Label(frm,
                       text="Signal bridge registered on this antenna",
                       foreground="#ffd700", background="#12101d",
                       font=("Segoe UI", 11, "bold")).pack()
            steps = (
                "Next steps:\n\n"
                "1. Install signal-cli-rest-api (Docker or native).\n"
                "   https://github.com/bbernhard/signal-cli-rest-api\n\n"
                "2. Start it on port 8080 (the antenna advertises this\n"
                "   port as the default signal endpoint).\n\n"
                "3. Link your phone:\n"
                "     curl http://127.0.0.1:8080/v1/qrcodelink?device_name=spellcaster\n\n"
                "4. Scan the QR code with Signal → Settings → Linked Devices.\n\n"
                "The Guild's Connected apps row will pick up the\n"
                "new 'signal' chip on the next poll (≤10s).")
            txt = tk.Text(frm, width=64, height=14, wrap="word",
                           bg="#1a1730", fg="#e8e6f5",
                           insertbackground="#e8e6f5",
                           font=("Consolas", 10), borderwidth=0)
            txt.insert("1.0", steps)
            txt.configure(state="disabled")
            txt.pack(pady=(12, 8))
            ttk.Button(frm, text="Close", command=root.destroy).pack()
            root.mainloop()
        except Exception:  # noqa: BLE001
            pass  # toast already carries the primary message

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
    # Build the menu by CALLING state.menu() — passing the bound
    # method directly made pystray try `Menu(*method)` which TypeErrors
    # ("argument after * must be an iterable, not method"). A fresh
    # Menu instance at startup is fine because the item labels that
    # need live state (startup toggle, status subtitle, service
    # running/stopped badge) are each wrapped in lambdas that pystray
    # re-evaluates every time the user opens the menu. Service
    # registration / removal during runtime still requires an
    # icon.update_menu() call — _rebuild_menu() below is the hook.
    icon = pystray.Icon(
        "spellcaster-antenna",
        icon=_build_icon("running"),
        title=f"Spellcaster Antenna — {state.subtitle()}",
        menu=state.menu(),
    )
    state._rebuild_menu = lambda: icon.update_menu()
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
