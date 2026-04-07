"""
Travelling Wizard mixin for GIMP AI Plugin.

Provides:
- "Travelling Wizard" menu entry that opens the Signal Bridge settings UI
  in the user's default browser
- "Workflow Library" dialog for browsing and importing ComfyUI workflows
  directly inside GIMP
"""

import os
import json
import webbrowser
import gi
from gi.repository import Gimp, Gtk, GLib, Gio


class WizardMixin:
    """Mixin class providing Travelling Wizard and Workflow Library functionality"""

    # ── Travelling Wizard (browser launcher) ──────────────────────

    def run_wizard(self, procedure, run_mode, image, drawables, config, run_data):
        """Open the Travelling Wizard settings UI in the user's browser."""
        try:
            print("DEBUG: Launching Travelling Wizard...")
            self._show_wizard_dialog(None)
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            print(f"ERROR: Wizard dialog failed: {e}")
            import traceback
            traceback.print_exc()
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error()
            )

    def _show_wizard_dialog(self, parent_dialog):
        """Show the Travelling Wizard launcher dialog."""
        try:
            dialog = Gtk.Dialog(
                title="The Travelling Wizard",
                parent=parent_dialog,
                flags=Gtk.DialogFlags.MODAL,
            )
            dialog.set_default_size(520, 480)
            dialog.set_resizable(True)

            dialog.add_button("Close", Gtk.ResponseType.CLOSE)

            content = dialog.get_content_area()
            content.set_spacing(12)
            content.set_margin_start(16)
            content.set_margin_end(16)
            content.set_margin_top(16)
            content.set_margin_bottom(12)

            # ── Header ──
            header_label = Gtk.Label()
            header_label.set_markup(
                '<span size="x-large" weight="bold">The Travelling Wizard</span>\n'
                '<span size="small">Signal Bridge &amp; Spellcaster Scaffold</span>'
            )
            header_label.set_halign(Gtk.Align.START)
            content.pack_start(header_label, False, False, 0)

            sep = Gtk.HSeparator()
            content.pack_start(sep, False, False, 4)

            # ── Server status ──
            comfy_cfg = self._get_comfyui_config()
            server_url = (comfy_cfg.get("server_url") or "http://127.0.0.1:8188").rstrip("/")

            status_box = Gtk.HBox(spacing=8)
            status_icon = Gtk.Label()
            status_text = Gtk.Label()
            status_box.pack_start(status_icon, False, False, 0)
            status_box.pack_start(status_text, False, False, 0)
            content.pack_start(status_box, False, False, 0)

            # Check ComfyUI connectivity
            online = self._check_comfyui_online(server_url)
            if online:
                status_icon.set_markup('<span foreground="#4ade80">●</span>')
                status_text.set_markup(
                    f'<span foreground="#4ade80">ComfyUI Online</span>'
                    f'  <span size="small" foreground="#888">{server_url}</span>'
                )
            else:
                status_icon.set_markup('<span foreground="#f87171">●</span>')
                status_text.set_markup(
                    f'<span foreground="#f87171">ComfyUI Offline</span>'
                    f'  <span size="small" foreground="#888">{server_url}</span>'
                )

            # ── Action buttons frame ──
            actions_frame = Gtk.Frame(label="Actions")
            actions_box = Gtk.VBox(spacing=10)
            actions_box.set_margin_start(12)
            actions_box.set_margin_end(12)
            actions_box.set_margin_top(12)
            actions_box.set_margin_bottom(12)

            # Button 1: Open Settings UI in browser
            btn_settings = Gtk.Button()
            btn_settings_box = Gtk.VBox(spacing=2)
            btn_settings_title = Gtk.Label()
            btn_settings_title.set_markup("<b>Open Scaffold Editor</b>")
            btn_settings_title.set_halign(Gtk.Align.START)
            btn_settings_desc = Gtk.Label()
            btn_settings_desc.set_text(
                "Opens the full Travelling Wizard settings UI in your browser.\n"
                "Configure scaffolds, import workflows, manage integrations."
            )
            btn_settings_desc.set_halign(Gtk.Align.START)
            btn_settings_desc.set_line_wrap(True)
            btn_settings_desc.get_style_context().add_class("dim-label")
            btn_settings_box.pack_start(btn_settings_title, False, False, 0)
            btn_settings_box.pack_start(btn_settings_desc, False, False, 0)
            btn_settings.add(btn_settings_box)
            btn_settings.connect("clicked", self._on_open_scaffold_editor)
            actions_box.pack_start(btn_settings, False, False, 0)

            # Button 2: Workflow Library
            btn_workflows = Gtk.Button()
            btn_workflows_box = Gtk.VBox(spacing=2)
            btn_workflows_title = Gtk.Label()
            btn_workflows_title.set_markup("<b>Browse Workflow Library</b>")
            btn_workflows_title.set_halign(Gtk.Align.START)
            btn_workflows_desc = Gtk.Label()
            btn_workflows_desc.set_text(
                "Browse and import ComfyUI workflows from your server.\n"
                "Any workflow JSON can be parsed and turned into a GIMP action."
            )
            btn_workflows_desc.set_halign(Gtk.Align.START)
            btn_workflows_desc.set_line_wrap(True)
            btn_workflows_desc.get_style_context().add_class("dim-label")
            btn_workflows_box.pack_start(btn_workflows_title, False, False, 0)
            btn_workflows_box.pack_start(btn_workflows_desc, False, False, 0)
            btn_workflows.add(btn_workflows_box)
            btn_workflows.connect(
                "clicked", lambda w: self._show_workflow_library(dialog)
            )
            actions_box.pack_start(btn_workflows, False, False, 0)

            # Button 3: Import Workflow JSON
            btn_import = Gtk.Button()
            btn_import_box = Gtk.VBox(spacing=2)
            btn_import_title = Gtk.Label()
            btn_import_title.set_markup("<b>Import Workflow File</b>")
            btn_import_title.set_halign(Gtk.Align.START)
            btn_import_desc = Gtk.Label()
            btn_import_desc.set_text(
                "Import a ComfyUI workflow JSON from your computer.\n"
                "Supports litegraph (UI export) and API format."
            )
            btn_import_desc.set_halign(Gtk.Align.START)
            btn_import_desc.set_line_wrap(True)
            btn_import_desc.get_style_context().add_class("dim-label")
            btn_import_box.pack_start(btn_import_title, False, False, 0)
            btn_import_box.pack_start(btn_import_desc, False, False, 0)
            btn_import.add(btn_import_box)
            btn_import.connect(
                "clicked", lambda w: self._import_workflow_file(dialog)
            )
            actions_box.pack_start(btn_import, False, False, 0)

            actions_frame.add(actions_box)
            content.pack_start(actions_frame, False, False, 0)

            # ── Installed custom workflows ──
            custom_frame = Gtk.Frame(label="Installed Workflows")
            custom_box = Gtk.VBox(spacing=6)
            custom_box.set_margin_start(12)
            custom_box.set_margin_end(12)
            custom_box.set_margin_top(8)
            custom_box.set_margin_bottom(8)

            custom_wfs = self._get_custom_workflows()
            if custom_wfs:
                for wf_name, wf_info in custom_wfs.items():
                    row = Gtk.HBox(spacing=8)
                    name_label = Gtk.Label()
                    name_label.set_markup(f"<b>{wf_name}</b>")
                    name_label.set_halign(Gtk.Align.START)
                    row.pack_start(name_label, True, True, 0)

                    wf_type = wf_info.get("workflow_type", "General")
                    type_label = Gtk.Label()
                    type_label.set_markup(
                        f'<span size="small" foreground="#888">{wf_type}</span>'
                    )
                    row.pack_start(type_label, False, False, 0)

                    remove_btn = Gtk.Button(label="Remove")
                    remove_btn.set_size_request(70, -1)
                    remove_btn.connect(
                        "clicked",
                        lambda w, n=wf_name: self._remove_custom_workflow(n, dialog),
                    )
                    row.pack_start(remove_btn, False, False, 0)

                    custom_box.pack_start(row, False, False, 0)
            else:
                empty_label = Gtk.Label()
                empty_label.set_markup(
                    '<span foreground="#888">No custom workflows installed.\n'
                    "Use Import or Browse to add workflows.</span>"
                )
                empty_label.set_halign(Gtk.Align.CENTER)
                custom_box.pack_start(empty_label, False, False, 4)

            custom_frame.add(custom_box)
            content.pack_start(custom_frame, True, True, 0)

            content.show_all()
            dialog.run()
            dialog.destroy()

        except Exception as e:
            print(f"DEBUG: Wizard dialog error: {e}")
            import traceback
            traceback.print_exc()

    # ── Helpers ───────────────────────────────────────────────────

    def _check_comfyui_online(self, server_url):
        """Quick connectivity check against ComfyUI."""
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{server_url}/system_stats", method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=3)
            return resp.status == 200
        except Exception:
            return False

    def _on_open_scaffold_editor(self, button):
        """Open the Travelling Wizard settings JSX in the user's browser."""
        # Look for the settings HTML file in known locations
        candidates = [
            # Same directory as plugin
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "signal_bridge_settings.html",
            ),
            # Agent dir
            os.path.expanduser(
                "~/signal_bridge_settings.html"
            ),
        ]

        # Also check config for a custom path
        wizard_path = (self.config or {}).get("wizard_settings_path", "")
        if wizard_path:
            candidates.insert(0, wizard_path)

        opened = False
        for path in candidates:
            full = os.path.abspath(path)
            if os.path.isfile(full):
                webbrowser.open(f"file://{full}")
                opened = True
                break

        if not opened:
            # Fallback: try opening the ComfyUI server URL with scaffold endpoint
            comfy_cfg = self._get_comfyui_config()
            server_url = (
                comfy_cfg.get("server_url") or "http://127.0.0.1:8188"
            ).rstrip("/")
            webbrowser.open(f"{server_url}/spellcaster/settings")
            print(
                "DEBUG: Could not find local settings HTML, "
                "trying server endpoint"
            )

    def _get_custom_workflows(self):
        """Get user-imported custom workflows from config."""
        return (self.config or {}).get("custom_workflows", {})

    def _save_custom_workflow(self, name, wf_data):
        """Save a custom workflow to config."""
        if "custom_workflows" not in self.config:
            self.config["custom_workflows"] = {}
        self.config["custom_workflows"][name] = wf_data
        self._save_config()

    def _remove_custom_workflow(self, name, parent_dialog):
        """Remove a custom workflow from config and refresh."""
        custom = self.config.get("custom_workflows", {})
        if name in custom:
            del custom[name]
            self._save_config()
            # Refresh the wizard dialog
            parent_dialog.destroy()
            self._show_wizard_dialog(None)

    def _import_workflow_file(self, parent_dialog):
        """Open a file chooser to import a workflow JSON."""
        chooser = Gtk.FileChooserDialog(
            title="Import ComfyUI Workflow",
            parent=parent_dialog,
            action=Gtk.FileChooserAction.OPEN,
        )
        chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
        chooser.add_button("Import", Gtk.ResponseType.OK)
        chooser.set_select_multiple(True)

        # Filter for JSON files
        json_filter = Gtk.FileFilter()
        json_filter.set_name("ComfyUI Workflows (*.json)")
        json_filter.add_pattern("*.json")
        chooser.add_filter(json_filter)

        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        chooser.add_filter(all_filter)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            filenames = chooser.get_filenames()
            imported = 0
            for filepath in filenames:
                try:
                    result = self._parse_and_import_workflow(filepath)
                    if result:
                        imported += 1
                except Exception as e:
                    print(f"DEBUG: Failed to import {filepath}: {e}")

            if imported > 0:
                print(f"DEBUG: Imported {imported} workflow(s)")
                # Also register them in the Settings workflow tabs
                chooser.destroy()
                # Refresh wizard dialog
                parent_dialog.destroy()
                self._show_wizard_dialog(None)
                return

        chooser.destroy()

    def _parse_and_import_workflow(self, filepath):
        """Parse a workflow JSON and import it into config."""
        with open(filepath, "r") as f:
            data = json.load(f)

        filename = os.path.basename(filepath)
        name = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")

        # Detect format
        is_litegraph = isinstance(data, dict) and "nodes" in data and isinstance(
            data["nodes"], list
        )
        is_api = (
            isinstance(data, dict)
            and not is_litegraph
            and any(
                isinstance(v, dict) and "class_type" in v
                for v in data.values()
                if isinstance(v, dict)
            )
        )

        if not is_litegraph and not is_api:
            print(f"DEBUG: {filename} is not a recognized ComfyUI workflow format")
            return False

        # Count nodes
        if is_litegraph:
            node_count = len(data.get("nodes", []))
            node_types = [
                n.get("type", "") for n in data.get("nodes", [])
            ]
        else:
            entries = [
                (k, v)
                for k, v in data.items()
                if isinstance(v, dict) and "class_type" in v
            ]
            node_count = len(entries)
            node_types = [v.get("class_type", "") for _, v in entries]

        # Classify
        all_types = " ".join(node_types).lower()
        if "video" in all_types or "animate" in all_types:
            wf_type = "Image-to-Video" if "loadimage" in all_types else "Text-to-Video"
        elif "faceswap" in all_types or "reactor" in all_types:
            wf_type = "Face Swap"
        elif "inpaint" in all_types:
            wf_type = "Inpainting"
        elif "upscale" in all_types or "esrgan" in all_types:
            wf_type = "Upscale"
        elif "controlnet" in all_types:
            wf_type = "ControlNet"
        elif "loadimage" in all_types:
            wf_type = "Image-to-Image"
        elif "ksampler" in all_types:
            wf_type = "Text-to-Image"
        else:
            wf_type = "General"

        # Detect tunable parameters (for API format)
        tunables = []
        if is_api:
            for node_id, node in data.items():
                if not isinstance(node, dict) or "inputs" not in node:
                    continue
                ct = (node.get("class_type") or "").lower()
                for key, val in node.get("inputs", {}).items():
                    if isinstance(val, list):
                        continue  # connection, skip
                    lk = key.lower()
                    if any(
                        kw in lk
                        for kw in [
                            "prompt", "text", "positive", "negative",
                            "steps", "cfg", "denoise", "seed",
                            "ckpt", "model", "checkpoint",
                            "width", "height",
                        ]
                    ):
                        tunables.append(
                            {
                                "node_id": str(node_id),
                                "node_type": node.get("class_type", ""),
                                "param": key,
                                "default": val,
                            }
                        )

        wf_info = {
            "path": os.path.abspath(filepath),
            "format": "litegraph" if is_litegraph else "api",
            "workflow_type": wf_type,
            "node_count": node_count,
            "tunables": tunables,
        }

        self._save_custom_workflow(name, wf_info)
        print(
            f"DEBUG: Imported '{name}' — {wf_type}, "
            f"{node_count} nodes, {len(tunables)} tunable params"
        )
        return True

    # ── Workflow Library (server browse) ──────────────────────────

    def _show_workflow_library(self, parent_dialog):
        """Show a dialog listing workflows from the ComfyUI server."""
        comfy_cfg = self._get_comfyui_config()
        server_url = (
            comfy_cfg.get("server_url") or "http://127.0.0.1:8188"
        ).rstrip("/")

        dialog = Gtk.Dialog(
            title="ComfyUI Workflow Library",
            parent=parent_dialog,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.set_default_size(600, 500)
        dialog.set_resizable(True)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)

        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(8)

        # Try to fetch workflow list from server
        workflows = self._fetch_server_workflows(server_url)

        if workflows is None:
            # Server unavailable or endpoint not set up
            info_label = Gtk.Label()
            info_label.set_markup(
                "<b>Workflow Library</b>\n\n"
                "The workflow library endpoint is not available on your ComfyUI server.\n\n"
                "To browse server workflows, set up the Spellcaster scaffold API:\n\n"
                '<span font_family="monospace" size="small">'
                "from scaffold import discover_workflows\n"
                "entries = discover_workflows()\n"
                '</span>\n\n'
                'Or use <b>"Import Workflow File"</b> to load workflows from disk.'
            )
            info_label.set_halign(Gtk.Align.START)
            info_label.set_line_wrap(True)
            info_label.set_max_width_chars(60)
            content.pack_start(info_label, True, True, 0)

            # Still offer filesystem browse
            fs_btn = Gtk.Button(label="Browse Filesystem...")
            fs_btn.connect(
                "clicked",
                lambda w: self._browse_workflow_directory(dialog),
            )
            content.pack_start(fs_btn, False, False, 0)
        else:
            # Show workflow list
            search_entry = Gtk.Entry()
            search_entry.set_placeholder_text("Search workflows...")
            content.pack_start(search_entry, False, False, 0)

            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(
                Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
            )

            listbox = Gtk.ListBox()
            listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)

            for wf in workflows:
                row = Gtk.ListBoxRow()
                hbox = Gtk.HBox(spacing=8)
                hbox.set_margin_start(8)
                hbox.set_margin_end(8)
                hbox.set_margin_top(6)
                hbox.set_margin_bottom(6)

                name_label = Gtk.Label()
                name_label.set_markup(
                    f"<b>{wf.get('name', 'Untitled')}</b>"
                )
                name_label.set_halign(Gtk.Align.START)
                hbox.pack_start(name_label, True, True, 0)

                wtype = wf.get("workflow_type", "General")
                type_label = Gtk.Label()
                type_label.set_markup(
                    f'<span size="small" foreground="#888">'
                    f"{wtype} | {wf.get('node_count', '?')} nodes"
                    f"</span>"
                )
                hbox.pack_start(type_label, False, False, 0)

                import_btn = Gtk.Button(label="Import")
                import_btn.connect(
                    "clicked",
                    lambda w, wf_data=wf: self._import_server_workflow(
                        wf_data, dialog
                    ),
                )
                hbox.pack_start(import_btn, False, False, 0)

                row.add(hbox)
                listbox.add(row)

            # Filter function
            def on_search_changed(entry):
                text = entry.get_text().lower()
                for row in listbox.get_children():
                    child = row.get_child()
                    # Get first label text
                    labels = [
                        c
                        for c in child.get_children()
                        if isinstance(c, Gtk.Label)
                    ]
                    visible = not text or any(
                        text in (l.get_text() or "").lower() for l in labels
                    )
                    row.set_visible(visible)

            search_entry.connect("changed", on_search_changed)

            scroller.add(listbox)
            content.pack_start(scroller, True, True, 0)

            count_label = Gtk.Label()
            count_label.set_markup(
                f'<span size="small" foreground="#888">'
                f"{len(workflows)} workflows found</span>"
            )
            count_label.set_halign(Gtk.Align.START)
            content.pack_start(count_label, False, False, 0)

        content.show_all()
        dialog.run()
        dialog.destroy()

    def _fetch_server_workflows(self, server_url):
        """Try to fetch workflow catalog from ComfyUI server."""
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{server_url}/spellcaster/workflows", method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            pass
        return None

    def _import_server_workflow(self, wf_data, parent_dialog):
        """Import a workflow from the server catalog."""
        name = wf_data.get("name", "Untitled")
        self._save_custom_workflow(name, wf_data)
        print(f"DEBUG: Imported server workflow '{name}'")
        # Refresh
        parent_dialog.destroy()
        self._show_wizard_dialog(None)

    def _browse_workflow_directory(self, parent_dialog):
        """Let user pick a directory to scan for workflow JSONs."""
        chooser = Gtk.FileChooserDialog(
            title="Select Workflow Folder",
            parent=parent_dialog,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
        chooser.add_button("Scan Folder", Gtk.ResponseType.OK)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            folder = chooser.get_filename()
            chooser.destroy()
            imported = 0
            for root, dirs, files in os.walk(folder):
                for fname in files:
                    if fname.endswith(".json"):
                        filepath = os.path.join(root, fname)
                        try:
                            if self._parse_and_import_workflow(filepath):
                                imported += 1
                        except Exception as e:
                            print(f"DEBUG: Skip {fname}: {e}")
            if imported > 0:
                print(f"DEBUG: Imported {imported} workflows from {folder}")
                parent_dialog.destroy()
                self._show_wizard_dialog(None)
        else:
            chooser.destroy()
