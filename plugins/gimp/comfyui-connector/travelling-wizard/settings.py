"""
Settings dialog mixin for GIMP AI Plugin - Workflow configuration and preferences.

Provides a tabbed settings dialog for configuring:

1. GENERAL SETTINGS:
   - ComfyUI server URL, input_dir, output_dir
   - Prompt history (view count, clear button)
   - Debug mode toggle (save intermediate images to temp)

2. WORKFLOW TABS (8 tabs for standard workflows):
   - Each tab: workflow path (JSON) + node override mappings
   - Override fields map plugin inputs to ComfyUI node IDs and field names
   - Pre-populated with default node IDs for common workflows
   - Supports: inpaint_focused, imageedit_1/2/3, generator, outpaint, upscaler_4x

3. CUSTOM WORKFLOWS TAB:
   - Displays workflows imported via Travelling Wizard
   - Shows metadata: type, node count, format, tunable parameters
   - Managed entirely by WizardMixin (this mixin is read-only for custom workflows)

The dialog persists all settings to the plugin config on Save.
"""

import tempfile
import gi
from gi.repository import Gimp, Gtk, GLib


class SettingsMixin:
    """Mixin class providing the tabbed settings dialog for workflow and server configuration.

    The dialog uses Gtk.Notebook for tabs. Each workflow tab lets users:
      - Specify the path to a ComfyUI workflow JSON
      - Override input parameter mappings (node_id → field name)

    Assumes parent class provides:
      - self.config: persistent config dict
      - self._save_config(): save config to disk
      - self._get_comfyui_config(): retrieve ComfyUI settings
      - self._get_prompt_history(): retrieve stored prompts
    """

    def _create_override_field(self, parent_box, label_text, node_id_value="", field_value=""):
        """Create a UI row with label and two text entry fields for node override mappings.

        Row layout: [Label (180px)] [Node ID Label] [Node ID Entry (100px)]
                    [Field Label] [Field Entry (120px)]

        These rows are packed into tabs to configure how plugin inputs map to
        specific ComfyUI node fields (e.g., "promptText" → node "75:6" field "text").

        Args:
            parent_box (Gtk.Box): Container to pack row into
            label_text (str): Display label (e.g., "Prompt Text")
            node_id_value (str): Initial node ID value (e.g., "75:6")
            field_value (str): Initial field name value (e.g., "text")

        Returns:
            tuple[Gtk.Entry, Gtk.Entry]: (node_id_entry, field_entry) for later retrieval
        """
        hbox = Gtk.HBox(spacing=8)
        hbox.set_margin_bottom(5)
        
        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.START)
        label.set_size_request(180, -1)
        hbox.pack_start(label, False, False, 0)
        
        node_id_label = Gtk.Label(label="Node ID:")
        node_id_label.set_halign(Gtk.Align.START)
        hbox.pack_start(node_id_label, False, False, 0)
        
        node_id_entry = Gtk.Entry()
        node_id_entry.set_text(str(node_id_value))
        node_id_entry.set_size_request(100, -1)
        hbox.pack_start(node_id_entry, False, False, 0)
        
        field_label = Gtk.Label(label="Field:")
        field_label.set_halign(Gtk.Align.START)
        hbox.pack_start(field_label, False, False, 0)
        
        field_entry = Gtk.Entry()
        field_entry.set_text(str(field_value))
        field_entry.set_size_request(120, -1)
        hbox.pack_start(field_entry, False, False, 0)
        
        parent_box.pack_start(hbox, False, False, 0)
        
        return node_id_entry, field_entry

    def _create_workflow_tab(self, notebook, action, display_name, override_keys):
        """Create a notebook tab for configuring a single workflow.

        Tab contains:
          - Workflow Path field (path to JSON file)
          - Separator line
          - Node Override section with fields for each override_key
          - Each override has two fields: node_id (where in ComfyUI) and field name

        Uses defaults dict to pre-populate common workflows' node IDs.

        Args:
            notebook (Gtk.Notebook): The notebook to append page to
            action (str): Action key (e.g., "inpaint_focused", "generator")
            display_name (str): Tab label (e.g., "Inpaint (Focused)")
            override_keys (list[str]): Parameter names to override (e.g.,
                                       ["promptText", "inputImageFilename"])

        Returns:
            tuple: (path_entry, override_entries_dict)
              - path_entry: Gtk.Entry for workflow JSON path
              - override_entries_dict: {key: (node_id_entry, field_entry), ...}
        """
        workflows = (self.config or {}).get("workflows", {})
        wf = (workflows.get(action, {}) or {}) if isinstance(workflows, dict) else {}
        wf_path = (wf.get("path") or "").strip() if isinstance(wf, dict) else ""
        overrides = (wf.get("overrides") or {}) if isinstance(wf, dict) else {}
        
        # Default values for each workflow/override key
        defaults = {
            "inpaint_focused": {
                "inputImageFilename": {"node_id": "225", "field": "image"},
                "saveFilenamePrefix": {"node_id": "163", "field": "filename_prefix"},
                "seed": {"node_id": "", "field": ""},  # Placeholder for user to configure
            },
            "imageedit_1": {
                "promptTextPositive": {"node_id": "111", "field": "prompt"},
                "promptTextNegative": {"node_id": "110", "field": "prompt"},
                "img1Filename": {"node_id": "78", "field": "image"},
                "seed": {"node_id": "3", "field": "seed"},
                "saveFilenamePrefix": {"node_id": "60", "field": "filename_prefix"},
            },
            "imageedit_2": {
                "promptTextPositive": {"node_id": "111", "field": "prompt"},
                "promptTextNegative": {"node_id": "110", "field": "prompt"},
                "img1Filename": {"node_id": "78", "field": "image"},
                "img2Filename": {"node_id": "106", "field": "image"},
                "seed": {"node_id": "3", "field": "seed"},
                "saveFilenamePrefix": {"node_id": "60", "field": "filename_prefix"},
            },
            "imageedit_3": {
                "promptTextPositive": {"node_id": "111", "field": "prompt"},
                "promptTextNegative": {"node_id": "110", "field": "prompt"},
                "img1Filename": {"node_id": "78", "field": "image"},
                "img2Filename": {"node_id": "106", "field": "image"},
                "img3Filename": {"node_id": "108", "field": "image"},
                "seed": {"node_id": "3", "field": "seed"},
                "saveFilenamePrefix": {"node_id": "60", "field": "filename_prefix"},
            },
            "generator": {
                "promptText": {"node_id": "75:6", "field": "text"},
                "saveFilenamePrefix": {"node_id": "60", "field": "filename_prefix"},
                "seed": {"node_id": "75:3", "field": "seed"},
                "width": {"node_id": "75:58", "field": "width"},
                "height": {"node_id": "75:58", "field": "height"},
            },
            "outpaint": {
                "promptText": {"node_id": "", "field": ""},
                "img1Filename": {"node_id": "193", "field": "image"},
                "padLeft": {"node_id": "202", "field": "left"},
                "padTop": {"node_id": "202", "field": "top"},
                "padRight": {"node_id": "202", "field": "right"},
                "padBottom": {"node_id": "202", "field": "bottom"},
                "seed": {"node_id": "190", "field": "seed"},
                "saveFilenamePrefix": {"node_id": "192", "field": "filename_prefix"},
            },
            "upscaler_4x": {
                "inputImageFilename": {"node_id": "32", "field": "image"},
                "saveFilenamePrefix": {"node_id": "9", "field": "filename_prefix"},
            },
        }
        
        # Create scrollable content area
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        content_box = Gtk.VBox(spacing=10)
        content_box.set_margin_start(15)
        content_box.set_margin_end(15)
        content_box.set_margin_top(15)
        content_box.set_margin_bottom(15)
        
        # Workflow path
        path_label = Gtk.Label(label="Workflow Path (JSON):")
        path_label.set_halign(Gtk.Align.START)
        content_box.pack_start(path_label, False, False, 0)
        
        path_entry = Gtk.Entry()
        path_entry.set_text(wf_path)
        content_box.pack_start(path_entry, False, False, 0)
        
        # Separator
        separator = Gtk.HSeparator()
        separator.set_margin_top(10)
        separator.set_margin_bottom(10)
        content_box.pack_start(separator, False, False, 0)
        
        # Override fields
        override_label = Gtk.Label()
        override_label.set_markup("<b>Node Overrides</b>")
        override_label.set_halign(Gtk.Align.START)
        content_box.pack_start(override_label, False, False, 0)
        
        override_info = Gtk.Label()
        override_info.set_text("Map plugin inputs to workflow node IDs and field names:")
        override_info.set_halign(Gtk.Align.START)
        override_info.get_style_context().add_class("dim-label")
        override_info.set_margin_bottom(5)
        content_box.pack_start(override_info, False, False, 0)
        
        # Store entries in a dict for later retrieval
        override_entries = {}
        
        for key in override_keys:
            node_id_val = ""
            field_val = ""
            
            # Check if override exists in config
            if isinstance(overrides, dict) and key in overrides:
                override_obj = overrides[key]
                if isinstance(override_obj, dict):
                    node_id_val = str(override_obj.get("node_id", ""))
                    field_val = str(override_obj.get("field", ""))
            
            # If no config value, use default if available
            if not node_id_val and not field_val:
                action_defaults = defaults.get(action, {})
                if key in action_defaults:
                    node_id_val = str(action_defaults[key].get("node_id", ""))
                    field_val = str(action_defaults[key].get("field", ""))
            
            # Create friendly label name
            label_map = {
                "promptText": "Prompt Text",
                "promptTextPositive": "Positive Prompt",
                "promptTextNegative": "Negative Prompt",
                "inputImageFilename": "Input Image",
                "inputMaskFilename": "Input Mask",
                "img1Filename": "Image 1",
                "img2Filename": "Image 2",
                "img3Filename": "Image 3",
                "saveFilenamePrefix": "Save Filename Prefix",
                "seed": "Seed",
                "width": "Width",
                "height": "Height",
                "padLeft": "Padding Left",
                "padTop": "Padding Top",
                "padRight": "Padding Right",
                "padBottom": "Padding Bottom",
            }
            label_text = label_map.get(key, key)
            
            node_entry, field_entry = self._create_override_field(
                content_box, label_text, node_id_val, field_val
            )
            override_entries[key] = (node_entry, field_entry)
        
        scroller.add(content_box)
        notebook.append_page(scroller, Gtk.Label(label=display_name))
        
        return path_entry, override_entries

    def _show_settings_dialog(self, parent_dialog):
        """Show the main tabbed settings dialog (650x500 modal).

        The dialog has 9 tabs:
          1. General: ComfyUI config + prompt history + debug mode
          2-8. Workflow tabs: inpaint_focused, imageedit_1/2/3, generator, outpaint, upscaler_4x
          9. Custom Workflows: read-only display of imported workflows

        On Save, all values are written to self.config and persisted to disk.

        Args:
            parent_dialog (Gtk.Dialog): Parent window for modality (may be None)
        """
        try:
            dialog = Gtk.Dialog(
                title="AI Plugin Settings",
                parent=parent_dialog,
                flags=Gtk.DialogFlags.MODAL,
            )

            # Set up dialog properties
            dialog.set_default_size(650, 500)
            dialog.set_resizable(True)

            # Add buttons
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            save_button = dialog.add_button("Save", Gtk.ResponseType.OK)
            save_button.set_can_default(True)
            save_button.grab_default()

            # Add content
            content_area = dialog.get_content_area()
            content_area.set_spacing(10)
            content_area.set_margin_start(10)
            content_area.set_margin_end(10)
            content_area.set_margin_top(10)
            content_area.set_margin_bottom(10)

            # Create notebook for tabs
            notebook = Gtk.Notebook()
            notebook.set_tab_pos(Gtk.PositionType.TOP)

            # Tab 1: General Settings
            # Use ScrolledWindow to allow overflow if content grows
            general_scroller = Gtk.ScrolledWindow()
            general_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            general_box = Gtk.VBox(spacing=15)
            general_box.set_margin_start(15)
            general_box.set_margin_end(15)
            general_box.set_margin_top(15)
            general_box.set_margin_bottom(15)

            # Load current ComfyUI config settings
            comfy_cfg = self._get_comfyui_config()

            # ── ComfyUI Server Configuration Frame ──
            # Contains: server URL, input_dir, output_dir text entries
            comfy_frame = Gtk.Frame(label="ComfyUI Configuration")
            comfy_box = Gtk.VBox(spacing=10)
            comfy_box.set_margin_start(10)
            comfy_box.set_margin_end(10)
            comfy_box.set_margin_top(10)
            comfy_box.set_margin_bottom(10)

            # Server URL field (e.g., "http://192.168.x.x:8188")
            comfy_url_label = Gtk.Label(label="Server URL (e.g. http://127.0.0.1:8188):")
            comfy_url_label.set_halign(Gtk.Align.START)
            comfy_box.pack_start(comfy_url_label, False, False, 0)
            comfy_url_entry = Gtk.Entry()
            comfy_url_entry.set_text((comfy_cfg.get("server_url") or "").strip())
            comfy_box.pack_start(comfy_url_entry, False, False, 0)

            # Input directory for loading source images
            comfy_input_label = Gtk.Label(label="ComfyUI input_dir (absolute path):")
            comfy_input_label.set_halign(Gtk.Align.START)
            comfy_box.pack_start(comfy_input_label, False, False, 0)
            comfy_input_entry = Gtk.Entry()
            comfy_input_entry.set_text((comfy_cfg.get("input_dir") or "").strip())
            comfy_box.pack_start(comfy_input_entry, False, False, 0)

            # Output directory where ComfyUI saves results
            comfy_output_label = Gtk.Label(label="ComfyUI output_dir (absolute path):")
            comfy_output_label.set_halign(Gtk.Align.START)
            comfy_box.pack_start(comfy_output_label, False, False, 0)
            comfy_output_entry = Gtk.Entry()
            comfy_output_entry.set_text((comfy_cfg.get("output_dir") or "").strip())
            comfy_box.pack_start(comfy_output_entry, False, False, 0)

            comfy_frame.add(comfy_box)
            general_box.pack_start(comfy_frame, False, False, 0)

            # Prompt History
            history_frame = Gtk.Frame(label="Prompt History")
            history_box = Gtk.VBox(spacing=10)
            history_box.set_margin_start(10)
            history_box.set_margin_end(10)
            history_box.set_margin_top(10)
            history_box.set_margin_bottom(10)

            history_count = len(self._get_prompt_history())
            count_label = Gtk.Label(label=f"Stored prompts: {history_count}")
            count_label.set_halign(Gtk.Align.START)
            history_box.pack_start(count_label, False, False, 0)

            clear_button = Gtk.Button(label="Clear Prompt History")
            clear_button.connect("clicked", self._on_clear_history_clicked)
            history_box.pack_start(clear_button, False, False, 0)

            history_frame.add(history_box)
            general_box.pack_start(history_frame, False, False, 0)

            # Debug Settings
            debug_frame = Gtk.Frame(label="Debug Settings")
            debug_box = Gtk.VBox(spacing=10)
            debug_box.set_margin_start(10)
            debug_box.set_margin_end(10)
            debug_box.set_margin_top(10)
            debug_box.set_margin_bottom(10)

            debug_checkbox = Gtk.CheckButton()
            debug_dir = tempfile.gettempdir()
            debug_checkbox.set_label(f"Save debug images to {debug_dir}")
            debug_checkbox.set_active(self.config.get("debug_mode", False))
            debug_box.pack_start(debug_checkbox, False, False, 0)

            debug_info = Gtk.Label()
            debug_info.set_text("Saves intermediate AI processing images for troubleshooting")
            debug_info.set_halign(Gtk.Align.START)
            debug_info.get_style_context().add_class("dim-label")
            debug_box.pack_start(debug_info, False, False, 0)

            debug_frame.add(debug_box)
            general_box.pack_start(debug_frame, False, False, 0)

            general_scroller.add(general_box)
            notebook.append_page(general_scroller, Gtk.Label(label="General"))

            # Store workflow tab data for saving
            workflow_tabs = {}

            # Tab 2: Inpaint Focused
            path_entry, override_entries = self._create_workflow_tab(
                notebook, "inpaint_focused", "Inpaint (Focused)",
                ["promptText", "inputImageFilename", "saveFilenamePrefix", "seed"]
            )
            workflow_tabs["inpaint_focused"] = (path_entry, override_entries)

            # Tab 3: ImageEdit 1-image
            path_entry, override_entries = self._create_workflow_tab(
                notebook, "imageedit_1", "ImageEdit (1-image)",
                ["promptTextPositive", "promptTextNegative", "img1Filename", "seed", "saveFilenamePrefix"]
            )
            workflow_tabs["imageedit_1"] = (path_entry, override_entries)

            # Tab 4: ImageEdit 2-image
            path_entry, override_entries = self._create_workflow_tab(
                notebook, "imageedit_2", "ImageEdit (2-image)",
                ["promptTextPositive", "promptTextNegative", "img1Filename", "img2Filename", "seed", "saveFilenamePrefix"]
            )
            workflow_tabs["imageedit_2"] = (path_entry, override_entries)

            # Tab 5: ImageEdit 3-image
            path_entry, override_entries = self._create_workflow_tab(
                notebook, "imageedit_3", "ImageEdit (3-image)",
                ["promptTextPositive", "promptTextNegative", "img1Filename", "img2Filename", "img3Filename", "seed", "saveFilenamePrefix"]
            )
            workflow_tabs["imageedit_3"] = (path_entry, override_entries)

            # Tab 6: Generator
            path_entry, override_entries = self._create_workflow_tab(
                notebook, "generator", "Generator",
                ["promptText", "saveFilenamePrefix", "seed", "width", "height"]
            )
            workflow_tabs["generator"] = (path_entry, override_entries)

            # Tab 7: Outpaint
            path_entry, override_entries = self._create_workflow_tab(
                notebook, "outpaint", "Outpaint",
                ["promptText", "img1Filename", "padLeft", "padTop", "padRight", "padBottom", "seed", "saveFilenamePrefix"]
            )
            workflow_tabs["outpaint"] = (path_entry, override_entries)

            # Tab 8: Upscaler (RealESRGAN 4x)
            path_entry, override_entries = self._create_workflow_tab(
                notebook, "upscaler_4x", "Upscaler (4x)",
                ["inputImageFilename", "saveFilenamePrefix"]
            )
            workflow_tabs["upscaler_4x"] = (path_entry, override_entries)

            # Tab 9: Custom Workflows (imported via Travelling Wizard)
            custom_scroller = Gtk.ScrolledWindow()
            custom_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            custom_box = Gtk.VBox(spacing=10)
            custom_box.set_margin_start(15)
            custom_box.set_margin_end(15)
            custom_box.set_margin_top(15)
            custom_box.set_margin_bottom(15)

            custom_info = Gtk.Label()
            custom_info.set_markup(
                "Workflows imported via <b>The Travelling Wizard</b> appear here.\n"
                "Use <b>Filters → AI → The Travelling Wizard</b> to browse and import workflows."
            )
            custom_info.set_halign(Gtk.Align.START)
            custom_info.set_line_wrap(True)
            custom_box.pack_start(custom_info, False, False, 0)

            sep = Gtk.HSeparator()
            custom_box.pack_start(sep, False, False, 4)

            custom_wfs = (self.config or {}).get("custom_workflows", {})
            if custom_wfs:
                for wf_name, wf_info in custom_wfs.items():
                    wf_frame = Gtk.Frame(label=wf_name)
                    wf_inner = Gtk.VBox(spacing=4)
                    wf_inner.set_margin_start(8)
                    wf_inner.set_margin_end(8)
                    wf_inner.set_margin_top(6)
                    wf_inner.set_margin_bottom(6)

                    wf_type = wf_info.get("workflow_type", "General")
                    wf_nodes = wf_info.get("node_count", "?")
                    wf_path = wf_info.get("path", "")
                    wf_fmt = wf_info.get("format", "?")

                    details = Gtk.Label()
                    details.set_markup(
                        f"Type: <b>{wf_type}</b>  |  Nodes: <b>{wf_nodes}</b>  |  Format: {wf_fmt}"
                    )
                    details.set_halign(Gtk.Align.START)
                    wf_inner.pack_start(details, False, False, 0)

                    if wf_path:
                        path_label = Gtk.Label()
                        path_label.set_markup(
                            f'<span size="small" foreground="#666">{wf_path}</span>'
                        )
                        path_label.set_halign(Gtk.Align.START)
                        path_label.set_selectable(True)
                        wf_inner.pack_start(path_label, False, False, 0)

                    tunables = wf_info.get("tunables", [])
                    if tunables:
                        params_label = Gtk.Label()
                        param_names = ", ".join(t.get("param", "") for t in tunables[:8])
                        if len(tunables) > 8:
                            param_names += f" (+{len(tunables) - 8} more)"
                        params_label.set_markup(
                            f'<span size="small">Tunable: {param_names}</span>'
                        )
                        params_label.set_halign(Gtk.Align.START)
                        wf_inner.pack_start(params_label, False, False, 0)

                    wf_frame.add(wf_inner)
                    custom_box.pack_start(wf_frame, False, False, 0)
            else:
                empty_label = Gtk.Label()
                empty_label.set_markup(
                    '<span foreground="#888">No custom workflows imported yet.\n\n'
                    'Use <b>Filters → AI → The Travelling Wizard</b> to:\n'
                    '  • Import workflow JSON files from your computer\n'
                    '  • Browse workflows from your ComfyUI server\n'
                    '  • Open the full Scaffold Editor in your browser</span>'
                )
                empty_label.set_halign(Gtk.Align.START)
                custom_box.pack_start(empty_label, False, False, 0)

            custom_scroller.add(custom_box)
            notebook.append_page(custom_scroller, Gtk.Label(label="Workflow Library"))

            content_area.pack_start(notebook, True, True, 0)

            # Show all widgets
            content_area.show_all()

            # Run dialog
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                # Save ComfyUI config
                if "comfyui" not in self.config or not isinstance(self.config["comfyui"], dict):
                    self.config["comfyui"] = {}
                self.config["comfyui"]["server_url"] = comfy_url_entry.get_text().strip()
                self.config["comfyui"]["input_dir"] = comfy_input_entry.get_text().strip()
                self.config["comfyui"]["output_dir"] = comfy_output_entry.get_text().strip()

                # Save workflow paths and overrides
                self.config.setdefault("workflows", {})
                for action, (path_entry, override_entries) in workflow_tabs.items():
                    self.config["workflows"].setdefault(action, {})
                    self.config["workflows"][action]["path"] = path_entry.get_text().strip()
                    self.config["workflows"][action]["overrides"] = {}
                    
                    for key, (node_entry, field_entry) in override_entries.items():
                        node_id = node_entry.get_text().strip()
                        field = field_entry.get_text().strip()
                        if node_id or field:  # Only save if at least one is set
                            self.config["workflows"][action]["overrides"][key] = {
                                "node_id": node_id,
                                "field": field
                            }

                # Save debug mode setting
                debug_mode = debug_checkbox.get_active()
                self.config["debug_mode"] = debug_mode
                self._save_config()
                print(f"DEBUG: Settings saved")

            dialog.destroy()

        except Exception as e:
            print(f"DEBUG: Settings dialog error: {e}")
            import traceback
            traceback.print_exc()

    def _on_clear_history_clicked(self, button):
        """Clear prompt history and save config.

        Args:
            button (Gtk.Button): The clicked button (unused, required by signal)
        """
        self.config["prompt_history"] = []
        self._save_config()
        print("DEBUG: Prompt history cleared")

    def run_settings(self, procedure, run_mode, image, drawables, config, run_data):
        """GIMP procedure entrypoint: open the Settings dialog from the menu.

        This is called when user selects Filters → AI → Settings.

        Args:
            procedure (Gimp.Procedure): The procedure being run
            run_mode (Gimp.RunMode): Execution mode (INTERACTIVE, etc.)
            image (Gimp.Image): The active image
            drawables (list): Selected drawables (not used for settings dialog)
            config: GIMP config object (not used)
            run_data: Additional run data (not used)

        Returns:
            Gimp.ProcedureResult: Status and error (if any)
        """
        try:
            print("DEBUG: Opening Settings dialog...")
            self._show_settings_dialog(None)
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as e:
            print(f"ERROR: Settings dialog failed: {e}")
            import traceback
            traceback.print_exc()
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

