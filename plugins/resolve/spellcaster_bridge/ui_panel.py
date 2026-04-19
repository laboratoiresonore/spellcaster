"""Bridge status panel — built with Fusion UI Manager.

A small floating window that shows the Guild connection state, queue
status, and the last N events. Buttons for pause/resume, refresh,
and opening the Guild in a browser.

Fusion UI is XML-ish — declarative trees of Label/Button/HGroup/VGroup.
It's the only UI surface Resolve exposes to plugins.

The panel is opened via the Workspace → Workflow Integrations menu or
via a top-level script in Scripts → Utility → Spellcaster.
"""

from __future__ import annotations

import threading
import time
import webbrowser

from resolve_helpers import get_fusion  # type: ignore
from spellcaster_api import GuildClient  # type: ignore


class BridgePanel:
    """Fusion-UI panel. One per Resolve session; singleton-ish.

    Caller pattern:
        panel = BridgePanel(guild, sse, sync, config)
        panel.show()   # blocks the calling thread until user closes window
    """

    def __init__(self, guild: GuildClient, sse, sync, config):
        self.guild = guild
        self.sse = sse
        self.sync = sync
        self.config = config
        self._refresh_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._win = None
        self._disp = None

    # ── Entry ────────────────────────────────────────────────────────

    def show(self):
        fu = get_fusion()
        if not fu:
            print("[Spellcaster Bridge] Fusion UI not available — panel disabled.")
            return
        ui = fu.UIManager
        self._disp = fu.UIDispatcher(ui)

        layout = ui.VGroup({"Spacing": 6}, [
            # Header
            ui.HGroup({"Spacing": 8, "Weight": 0}, [
                ui.Label({"ID": "title", "Text": "Spellcaster Bridge",
                          "Font": ui.Font({"Family": "Helvetica", "PointSize": 15, "Bold": True})}),
                ui.HGap(0, 1.0),
                ui.Label({"ID": "status_dot", "Text": "●",
                          "Font": ui.Font({"PointSize": 14}),
                          "Alignment": {"AlignRight": True}}),
                ui.Label({"ID": "status_text", "Text": "connecting…"}),
            ]),
            ui.Label({"ID": "guild_url", "Text": self.guild.base_url,
                      "Font": ui.Font({"Family": "Courier", "PointSize": 10})}),

            # Queue counters
            ui.HGroup({"Spacing": 12, "Weight": 0}, [
                self._counter("running", "Running"),
                self._counter("draft", "Draft"),
                self._counter("ready", "Ready"),
                self._counter("failed", "Failed"),
            ]),

            # Controls
            ui.HGroup({"Spacing": 6, "Weight": 0}, [
                ui.Button({"ID": "btn_refresh", "Text": "↻ Refresh"}),
                ui.Button({"ID": "btn_render_all", "Text": "▶ Render all drafts"}),
                ui.Button({"ID": "btn_open_guild", "Text": "Open Guild ↗"}),
                ui.HGap(0, 1.0),
            ]),

            ui.Label({"Text": "Recent activity:",
                      "Font": ui.Font({"PointSize": 10, "Italic": True})}),
            ui.TextEdit({"ID": "log", "ReadOnly": True,
                         "Font": ui.Font({"Family": "Courier", "PointSize": 10}),
                         "Weight": 1}),

            # Footer: toggles
            ui.HGroup({"Spacing": 12, "Weight": 0}, [
                ui.CheckBox({"ID": "cb_auto_import", "Text": "Auto-import shots",
                             "Checked": bool(self.config.get("auto_import", True))}),
                ui.CheckBox({"ID": "cb_live_timeline", "Text": "Mirror to Live timeline",
                             "Checked": bool(self.config.get("live_timeline", False))}),
            ]),
        ])

        self._win = self._disp.AddWindow({
            "WindowTitle": "Spellcaster Bridge",
            "ID": "spellcaster_bridge_main",
            "Geometry": [400, 200, 460, 520],
        }, layout)

        # Event wiring
        w = self._win
        w.On.btn_refresh.Clicked = lambda ev: self._refresh_now()
        w.On.btn_render_all.Clicked = lambda ev: self._render_all()
        w.On.btn_open_guild.Clicked = lambda ev: webbrowser.open(self.guild.base_url)
        w.On.cb_auto_import.Clicked = lambda ev: self._toggle("auto_import", "cb_auto_import")
        w.On.cb_live_timeline.Clicked = lambda ev: self._toggle("live_timeline", "cb_live_timeline")
        w.On.spellcaster_bridge_main.Close = lambda ev: self._on_close()

        self._start_refresh_thread()
        self._win.Show()
        self._disp.RunLoop()
        self._win.Hide()

    # ── UI helpers ──────────────────────────────────────────────────

    def _counter(self, field_id: str, label: str):
        fu = get_fusion()
        ui = fu.UIManager
        return ui.VGroup({"Spacing": 1, "Weight": 0}, [
            ui.Label({"ID": f"count_{field_id}", "Text": "0",
                      "Font": ui.Font({"PointSize": 18, "Bold": True}),
                      "Alignment": {"AlignHCenter": True}}),
            ui.Label({"Text": label,
                      "Font": ui.Font({"PointSize": 9}),
                      "Alignment": {"AlignHCenter": True}}),
        ])

    def _toggle(self, key: str, checkbox_id: str):
        if self._win is None:
            return
        try:
            val = bool(self._win.Find(checkbox_id).Checked)
        except Exception:
            return
        self.config[key] = val
        self.config.save()

    def _refresh_now(self):
        """Called from the UI thread — schedule a one-shot refresh."""
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            shots = self.guild.list_shots()
        except Exception as e:
            shots = []
            self._append_log(f"refresh failed: {e}")
        self._apply_counters(shots)

    def _render_all(self):
        threading.Thread(target=self._do_render_all, daemon=True).start()

    def _do_render_all(self):
        try:
            r = self.guild.render_all_drafts()
            self._append_log(f"render-all queued: {r.get('queued', '?')}")
        except Exception as e:
            self._append_log(f"render-all failed: {e}")

    # ── Periodic refresh thread ──────────────────────────────────────

    def _start_refresh_thread(self):
        self._stop.clear()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop, daemon=True, name="bridge-panel-refresh")
        self._refresh_thread.start()

    def _refresh_loop(self):
        poll = float(self.config.get("poll_interval_s", 2.0))
        while not self._stop.is_set():
            try:
                shots = self.guild.list_shots()
                self._apply_counters(shots)
                self._apply_status()
            except Exception:
                pass
            # Also refresh the log tail from the sync module
            self._apply_log(self.sync.events_tail)
            if self._stop.wait(poll):
                return

    def _apply_counters(self, shots: list):
        if self._win is None:
            return
        counts = {"running": 0, "draft": 0, "ready": 0, "failed": 0}
        for s in shots:
            status = (s.get("status") or "").lower()
            if status in counts:
                counts[status] += 1
            elif status == "queued":
                counts["draft"] += 1
        try:
            for k, v in counts.items():
                self._win.Find(f"count_{k}").Text = str(v)
        except Exception:
            pass

    def _apply_status(self):
        if self._win is None:
            return
        mode = self.sse.mode
        dot_color = "green" if mode == "sse" else "yellow" if mode == "polling" else "red"
        # Fusion UI doesn't have easy color per-label; stick to emoji text
        dot_char = {"green": "●", "yellow": "◐", "red": "○"}[dot_color]
        label_text = {
            "sse": "live (SSE)",
            "polling": "polling fallback",
            "disconnected": "guild offline",
            "idle": "idle",
        }.get(mode, mode)
        try:
            self._win.Find("status_dot").Text = dot_char
            self._win.Find("status_text").Text = label_text
        except Exception:
            pass

    def _apply_log(self, lines: list[str]):
        if self._win is None:
            return
        try:
            self._win.Find("log").PlainText = "\n".join(lines[-100:])
        except Exception:
            pass

    def _append_log(self, msg: str):
        self.sync._log(msg)  # piggyback on the shared log tail

    # ── Close ───────────────────────────────────────────────────────

    def _on_close(self):
        self._stop.set()
        if self._disp:
            self._disp.ExitLoop()
