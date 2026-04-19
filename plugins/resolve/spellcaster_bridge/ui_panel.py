"""Bridge Command Center — Fusion UI panel.

R124: upgraded from a pure status dashboard into an action surface.
The panel now exposes ~14 of the most-used Spellcaster ops as buttons
grouped by category (Capture / Generate / Selected clip / Send to),
alongside the original queue/status section. Buttons dispatch to the
existing Fusion Scripts in plugins/resolve/scripts/ via importlib —
no logic duplication.

Resolve's public scripting API has no hook for injecting items into
File/Edit/Timeline menus or clip right-click context menus, so this
dockable panel is the closest equivalent to a "toolbar" the platform
allows. The companion `keyboard_shortcuts_helper` script (R125)
surfaces a recommended hotkey map for the same ops.

Fusion UI is XML-ish — declarative trees of Label/Button/HGroup/VGroup.
No Tabs widget exists, so sections are modeled as VGroups with header
labels + horizontal separators.

Opened via Workspace > Workflow Integrations > Spellcaster, or via
Scripts > Utility > 💎 Spellcaster > open_bridge_panel.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
import traceback
import webbrowser

from resolve_helpers import get_fusion  # type: ignore
from spellcaster_api import GuildClient  # type: ignore


# ── Action catalog ──────────────────────────────────────────────────
# Each tuple: (button_id, label, script_basename)
# script_basename must match plugins/resolve/scripts/<name>.py and the
# script must expose a main() function.
_ACTIONS_CAPTURE = [
    ("act_playhead",   "📸 Playhead → Shot",    "generate_from_playhead"),
    ("act_timeline",   "📋 Timeline → Board",   "capture_timeline"),
    ("act_markers",    "🏷 Markers → Shots",    "markers_to_shots"),
]
_ACTIONS_GENERATE = [
    ("act_t2v",        "✨ From prompt",         "generate_from_prompt"),
    ("act_variations", "🎲 3 variations",        "generate_3_variations"),
    ("act_shootout",   "🎯 Preset shootout",     "preset_shootout"),
]
_ACTIONS_CLIP = [
    ("act_reprompt",   "♻ Reprompt",             "reprompt_selected_shot"),
    ("act_upscale",    "🔺 Upscale",             "upscale_selected_clip"),
    ("act_v2v",        "▶ V2V",                  "send_clip_to_v2v"),
    ("act_vace",       "🎭 VACE",                "send_clip_to_vace"),
]
_ACTIONS_SEND = [
    ("act_to_gimp",    "🎨 → GIMP",              "send_frame_to_gimp"),
    ("act_to_dt",      "🎞 → Darktable",         "send_frame_to_darktable"),
    ("act_to_st",      "💬 → SillyTavern",       "send_frame_to_sillytavern"),
]


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
        disp_factory = getattr(fu, "UIDispatcher", None)
        if ui is None or disp_factory is None:
            print("[Spellcaster Bridge] UIDispatcher unavailable "
                  "(open this panel from the Fusion page or use the "
                  "Guild web UI).")
            return
        self._disp = disp_factory(ui)

        layout = ui.VGroup({"Spacing": 6}, [
            # ── Header ───────────────────────────────────────────
            ui.HGroup({"Spacing": 8, "Weight": 0}, [
                ui.Label({"ID": "title", "Text": "💎 Spellcaster Command Center",
                          "Font": ui.Font({"Family": "Helvetica",
                                             "PointSize": 15, "Bold": True})}),
                ui.HGap(0, 1.0),
                ui.Label({"ID": "status_dot", "Text": "●",
                          "Font": ui.Font({"PointSize": 14}),
                          "Alignment": {"AlignRight": True}}),
                ui.Label({"ID": "status_text", "Text": "connecting…"}),
            ]),
            ui.Label({"ID": "guild_url", "Text": self.guild.base_url,
                      "Font": ui.Font({"Family": "Courier", "PointSize": 10})}),

            # ── Queue counters ───────────────────────────────────
            ui.HGroup({"Spacing": 12, "Weight": 0}, [
                self._counter("running", "Running"),
                self._counter("draft",   "Draft"),
                self._counter("ready",   "Ready"),
                self._counter("failed",  "Failed"),
            ]),

            # ── Actions: Capture ────────────────────────────────
            self._section_label("📸 Capture"),
            self._action_row(_ACTIONS_CAPTURE, ui),

            # ── Actions: Generate ───────────────────────────────
            self._section_label("✨ Generate"),
            self._action_row(_ACTIONS_GENERATE, ui),

            # ── Actions: Selected clip ──────────────────────────
            self._section_label("🎬 Selected clip"),
            self._action_row(_ACTIONS_CLIP, ui),

            # ── Actions: Send frame to ──────────────────────────
            self._section_label("📤 Send frame to"),
            self._action_row(_ACTIONS_SEND, ui),

            # ── Queue / timeline controls ───────────────────────
            self._section_label("⚙ Queue / timeline"),
            ui.HGroup({"Spacing": 6, "Weight": 0}, [
                ui.Button({"ID": "btn_refresh",        "Text": "↻ Refresh"}),
                ui.Button({"ID": "btn_render_all",     "Text": "▶ Render drafts"}),
                ui.Button({"ID": "btn_queue_toggle",   "Text": "⏸ Pause queue"}),
                ui.Button({"ID": "btn_open_guild",     "Text": "Open Guild ↗"}),
                ui.HGap(0, 1.0),
            ]),
            ui.HGroup({"Spacing": 6, "Weight": 0}, [
                ui.Button({"ID": "btn_retry_failed",   "Text": "⟳ Retry failed"}),
                ui.Button({"ID": "btn_cancel_all",     "Text": "◼ Cancel all"}),
                ui.Button({"ID": "btn_refresh_timeline",
                            "Text": "↓ Ready → timeline"}),
                ui.Button({"ID": "btn_shortcuts",
                            "Text": "🎹 Shortcuts…"}),
                ui.HGap(0, 1.0),
            ]),

            # ── Activity log ────────────────────────────────────
            ui.Label({"Text": "Recent activity:",
                      "Font": ui.Font({"PointSize": 10, "Italic": True})}),
            ui.TextEdit({"ID": "log", "ReadOnly": True,
                         "Font": ui.Font({"Family": "Courier", "PointSize": 10}),
                         "Weight": 1}),

            # ── Footer toggles ──────────────────────────────────
            ui.HGroup({"Spacing": 12, "Weight": 0}, [
                ui.CheckBox({"ID": "cb_auto_import",   "Text": "Auto-import shots",
                             "Checked": bool(self.config.get("auto_import", True))}),
                ui.CheckBox({"ID": "cb_live_timeline", "Text": "Mirror to Live timeline",
                             "Checked": bool(self.config.get("live_timeline", False))}),
            ]),
        ])

        self._win = self._disp.AddWindow({
            "WindowTitle": "Spellcaster Command Center",
            "ID": "spellcaster_bridge_main",
            "Geometry": [200, 120, 560, 800],
        }, layout)

        # Event wiring
        w = self._win
        w.On.btn_refresh.Clicked          = lambda ev: self._refresh_now()
        w.On.btn_render_all.Clicked       = lambda ev: self._render_all()
        w.On.btn_queue_toggle.Clicked     = lambda ev: self._queue_toggle()
        w.On.btn_open_guild.Clicked       = lambda ev: webbrowser.open(self.guild.base_url)
        w.On.btn_retry_failed.Clicked     = lambda ev: self._retry_failed()
        w.On.btn_cancel_all.Clicked       = lambda ev: self._cancel_all()
        w.On.btn_refresh_timeline.Clicked = lambda ev: self._refresh_to_timeline()
        w.On.btn_shortcuts.Clicked        = lambda ev: self._run_script("keyboard_shortcuts_helper")
        w.On.cb_auto_import.Clicked       = lambda ev: self._toggle("auto_import", "cb_auto_import")
        w.On.cb_live_timeline.Clicked     = lambda ev: self._toggle("live_timeline", "cb_live_timeline")
        w.On.spellcaster_bridge_main.Close = lambda ev: self._on_close()

        # Wire every action-catalog button to a dispatch thread that
        # loads and runs the named script.
        for group in (_ACTIONS_CAPTURE, _ACTIONS_GENERATE,
                      _ACTIONS_CLIP, _ACTIONS_SEND):
            for btn_id, label, script in group:
                self._wire_action(w, btn_id, script, label)

        self._start_refresh_thread()
        self._win.Show()
        self._disp.RunLoop()
        self._win.Hide()

    # ── UI helpers ──────────────────────────────────────────────────

    def _section_label(self, text: str):
        fu = get_fusion()
        ui = fu.UIManager
        return ui.Label({
            "Text": text,
            "Font": ui.Font({"PointSize": 11, "Bold": True}),
            "Weight": 0,
        })

    def _action_row(self, actions, ui):
        """Lay out an action group as an HGroup of buttons."""
        items = []
        for btn_id, label, _script in actions:
            items.append(ui.Button({"ID": btn_id, "Text": label,
                                      "MinimumSize": [120, 28]}))
        items.append(ui.HGap(0, 1.0))
        return ui.HGroup({"Spacing": 6, "Weight": 0}, items)

    def _wire_action(self, w, btn_id: str, script: str, label: str):
        def _on_click(_ev, s=script, l=label):
            self._append_log(f"▶ {l}")
            threading.Thread(
                target=self._run_script, args=(s, l),
                daemon=True, name=f"spellcaster-{s}",
            ).start()
        # Fusion UI exposes a dynamic On.<id>.<event> attribute chain;
        # retrieve the per-button slot with getattr so we can assign
        # .Clicked from data rather than hard-coded names.
        try:
            getattr(w.On, btn_id).Clicked = _on_click
        except Exception:
            # Fallback for older Fusion UI builds where On is a subscript
            try:
                w.On[btn_id].Clicked = _on_click
            except Exception as e:  # noqa: BLE001
                self._append_log(
                    f"✗ couldn't wire {btn_id}: {e}")

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

    # ── Script dispatch ─────────────────────────────────────────────

    def _run_script(self, script_basename: str, label: str = ""):
        """Locate `<script_basename>.py` in the user's Fusion/Scripts
        tree, import it, and call its `main()`. The panel itself
        lives in Workflow Integration Plugins, a different dir from
        the Fusion Scripts, so we resolve the path explicitly.
        """
        paths = self._find_script_tree()
        src = None
        for base in paths:
            cand = os.path.join(base, f"{script_basename}.py")
            if os.path.isfile(cand):
                src = cand
                break
        if src is None:
            self._append_log(
                f"✗ couldn't locate {script_basename}.py in Fusion Scripts")
            return
        try:
            mod_name = f"spellcaster_action_{script_basename}"
            spec = importlib.util.spec_from_file_location(mod_name, src)
            if spec is None or spec.loader is None:
                self._append_log(f"✗ import spec failed for {script_basename}")
                return
            mod = importlib.util.module_from_spec(spec)
            # Give the loaded module the shared/ path so its
            # _locate_shared() still works from the panel context.
            spec.loader.exec_module(mod)
            main = getattr(mod, "main", None)
            if main is None:
                self._append_log(f"✗ {script_basename}: no main()")
                return
            rc = main()
            self._append_log(f"✓ {label or script_basename} → rc={rc}")
        except Exception as e:  # noqa: BLE001
            self._append_log(f"✗ {label or script_basename}: {e}")
            traceback.print_exc()

    def _find_script_tree(self) -> list[str]:
        """Return the candidate installed script directories, one per
        Resolve page subfolder. The scripts are deployed identically
        to every page folder (R104 diamond-prefix convention); first
        hit wins."""
        cands: list[str] = []
        subs = ("Utility", "Edit", "Color", "Deliver", "Comp")
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                root = os.path.join(
                    appdata, "Blackmagic Design", "DaVinci Resolve",
                    "Support", "Fusion", "Scripts")
                for s in subs:
                    cands.append(os.path.join(root, s, "💎 Spellcaster"))
        elif sys.platform == "darwin":
            root = os.path.expanduser(
                "~/Library/Application Support/Blackmagic Design/"
                "DaVinci Resolve/Fusion/Scripts")
            for s in subs:
                cands.append(os.path.join(root, s, "💎 Spellcaster"))
        else:
            root = os.path.expanduser(
                "~/.local/share/DaVinciResolve/Fusion/Scripts")
            for s in subs:
                cands.append(os.path.join(root, s, "💎 Spellcaster"))
        return cands

    # ── Existing queue / status handlers ────────────────────────────

    def _refresh_now(self):
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
            try:
                self.guild._post_json("/api/video/queue/pause", {})
            except Exception:
                pass
            self._append_log(
                f"cancelled {cancelled}/{len(live)} active; queue paused")
        except Exception as e:
            self._append_log(f"cancel-all: {e}")

    def _refresh_to_timeline(self):
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
        self.sync._log(msg)

    # ── Close ───────────────────────────────────────────────────────

    def _on_close(self):
        self._stop.set()
        if self._disp:
            self._disp.ExitLoop()
