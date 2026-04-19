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
        # R85/R88: UIDispatcher can be None on the non-Fusion pages even
        # though ui.UIManager is present — skip gracefully instead of
        # crashing when the editor is e.g. on the Edit page.
        disp_factory = getattr(fu, "UIDispatcher", None)
        if ui is None or disp_factory is None:
            print("[Spellcaster Bridge] UIDispatcher unavailable "
                  "(open this panel from the Fusion page or use the "
                  "Guild web UI).")
            return
        self._disp = disp_factory(ui)

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

            # Controls — primary row
            ui.HGroup({"Spacing": 6, "Weight": 0}, [
                ui.Button({"ID": "btn_refresh", "Text": "↻ Refresh"}),
                ui.Button({"ID": "btn_render_all", "Text": "▶ Render all drafts"}),
                ui.Button({"ID": "btn_queue_toggle", "Text": "⏸ Pause queue"}),
                ui.Button({"ID": "btn_open_guild", "Text": "Open Guild ↗"}),
                ui.HGap(0, 1.0),
            ]),
            # R88: secondary controls — batch recovery + bulk actions
            ui.HGroup({"Spacing": 6, "Weight": 0}, [
                ui.Button({"ID": "btn_retry_failed", "Text": "⟳ Retry failed"}),
                ui.Button({"ID": "btn_cancel_all", "Text": "◼ Cancel all"}),
                ui.Button({"ID": "btn_refresh_timeline",
                            "Text": "↓ Refresh ready → timeline"}),
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
        w.On.btn_queue_toggle.Clicked = lambda ev: self._queue_toggle()
        w.On.btn_open_guild.Clicked = lambda ev: webbrowser.open(self.guild.base_url)
        w.On.btn_retry_failed.Clicked = lambda ev: self._retry_failed()
        w.On.btn_cancel_all.Clicked = lambda ev: self._cancel_all()
        w.On.btn_refresh_timeline.Clicked = lambda ev: self._refresh_to_timeline()
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

    # R88: queue toggle, retry-failed, cancel-all, refresh-to-timeline.
    # All run off-thread so the UI stays responsive. Log tail surfaces
    # outcomes. Errors are caught and logged — never raised to the
    # event callback (which would kill the dispatcher loop).

    def _queue_toggle(self):
        threading.Thread(target=self._do_queue_toggle, daemon=True).start()

    def _do_queue_toggle(self):
        try:
            status = self.guild.queue_status()
            paused = bool(status.get("paused", False))
            next_state = "resume" if paused else "pause"
            self.guild._post_json(f"/api/video/queue/{next_state}", {})
            self._append_log(f"queue {next_state}d")
            if self._win is not None:
                try:
                    btn = self._win.Find("btn_queue_toggle")
                    btn.Text = ("▶ Resume queue" if next_state == "pause"
                                 else "⏸ Pause queue")
                except Exception:
                    pass
        except Exception as e:
            self._append_log(f"queue toggle failed: {e}")

    def _retry_failed(self):
        threading.Thread(target=self._do_retry_failed, daemon=True).start()

    def _do_retry_failed(self):
        try:
            shots = self.guild.list_shots()
            failed = [s for s in shots
                       if (s.get("status") or "").lower() == "failed"]
            if not failed:
                self._append_log("no failed shots to retry")
                return
            self.guild._post_json("/api/video/reset-failed", {})
            self._append_log(f"re-queued {len(failed)} failed shot(s)")
        except Exception as e:
            self._append_log(f"retry-failed: {e}")

    def _cancel_all(self):
        threading.Thread(target=self._do_cancel_all, daemon=True).start()

    def _do_cancel_all(self):
        try:
            shots = self.guild.list_shots()
            live = [s for s in shots
                     if (s.get("status") or "").lower() in ("queued", "running")]
            if not live:
                self._append_log("no active renders to cancel")
                return
            cancelled = 0
            for shot in live:
                try:
                    self.guild.cancel_shot(shot.get("id") or "")
                    cancelled += 1
                except Exception:
                    continue
            # Pause the queue so nothing picks up mid-cancel
            try:
                self.guild._post_json("/api/video/queue/pause", {})
            except Exception:
                pass
            self._append_log(
                f"cancelled {cancelled}/{len(live)} active; queue paused")
        except Exception as e:
            self._append_log(f"cancel-all: {e}")

    def _refresh_to_timeline(self):
        """R88: append every ready Guild clip to the current Resolve
        timeline in shotboard order. Mirrors the standalone script
        refresh_ready_shots.py but runs inline inside the panel."""
        threading.Thread(target=self._do_refresh_to_timeline,
                          daemon=True).start()

    def _do_refresh_to_timeline(self):
        try:
            from resolve_helpers import (  # type: ignore
                get_media_pool, get_current_timeline,
                append_to_current_timeline,
            )
            import os as _os
            timeline = get_current_timeline()
            mp = get_media_pool()
            if not (timeline and mp):
                self._append_log("no active timeline — open one first")
                return
            shots = self.guild.list_shots()
            ready = [s for s in shots
                      if (s.get("status") or "").lower() == "ready"
                      and s.get("video_path")]
            ready.sort(key=lambda s: s.get("index", 0))
            if not ready:
                self._append_log("no ready shots to append")
                return

            clips_by_name: dict = {}

            def _walk(folder):
                try:
                    for c in folder.GetClipList() or []:
                        try:
                            props = c.GetClipProperty()
                            name = (props or {}).get("File Name") or c.GetName()
                        except Exception:
                            name = getattr(c, "GetName", lambda: "")()
                        if name:
                            clips_by_name.setdefault(_os.path.basename(name), c)
                    for sub in folder.GetSubFolderList() or []:
                        _walk(sub)
                except Exception:
                    pass

            try:
                _walk(mp.GetRootFolder())
            except Exception:
                pass

            appended = 0
            missing = 0
            for shot in ready:
                basename = _os.path.basename(shot.get("video_path") or "")
                item = clips_by_name.get(basename)
                if item is None:
                    missing += 1
                    continue
                try:
                    if append_to_current_timeline(item):
                        appended += 1
                except Exception:
                    missing += 1

            self._append_log(
                f"timeline: appended {appended}; {missing} not in pool yet")
        except Exception as e:
            self._append_log(f"refresh-to-timeline: {e}")

    # ── Periodic refresh thread ──────────────────────────────────────

    def _start_refresh_thread(self):
        self._stop.clear()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop, daemon=True, name="bridge-panel-refresh")
        self._refresh_thread.start()

    def _refresh_loop(self):
        poll = float(self.config.get("poll_interval_s", 2.0))
        # Throttle queue-status reads (every 4 polls — no need per tick)
        q_tick = 0
        while not self._stop.is_set():
            try:
                shots = self.guild.list_shots()
                self._apply_counters(shots)
                self._apply_status()
            except Exception:
                pass
            q_tick = (q_tick + 1) % 4
            if q_tick == 0:
                try:
                    qs = self.guild.queue_status()
                    self._apply_queue_button(bool(qs.get("paused", False)))
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

    def _apply_queue_button(self, paused: bool):
        """R88: keep the pause/resume button's label honest."""
        if self._win is None:
            return
        try:
            btn = self._win.Find("btn_queue_toggle")
            btn.Text = "▶ Resume queue" if paused else "⏸ Pause queue"
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
