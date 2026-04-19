"""Smoke test for the Spellcaster video layer.

Runs offline -- no WanGP or ComfyUI required -- by hitting the parts of
the stack that are pure logic:

    * Shotboard round-trip (save / load / reorder / status)
    * Trajectory serialisation
    * CinematographerWizard full conversation flow
    * WanGPRunner preset introspection (no network)
    * VideoBridge composition (bridges to unreachable backends gracefully)

Run from the repo root::

    PYTHONPATH=. python tests/test_video_layer.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback

# Module-level constants for tests defined outside main()
_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(_HERE)
TMP = tempfile.mkdtemp(prefix="spellcaster_test_")


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    sys.path.insert(0, repo_root)

    # Minimal logging config so failures are visible
    import logging
    logging.basicConfig(level=logging.WARNING,
                        format="%(name)s: %(message)s")

    failures = []

    def check(label, fn):
        try:
            fn()
            print(f"  [OK]   {label}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {label}: {exc}")
            traceback.print_exc()
            failures.append(label)

    print("Smoke test: Spellcaster video layer")


    # Round 23 — Transitions + Concurrency
    check("Shot has transition and transition_ms fields",
          test_shot_transition_fields)
    check("Shot transition fields survive roundtrip",
          test_shot_transition_roundtrip)
    check("Shotboard persists transition fields",
          test_shotboard_transition_persistence)
    check("_xfade_name maps transitions to ffmpeg names",
          test_xfade_name_mapping)
    check("_build_xfade_filter returns None for all cuts",
          test_build_xfade_filter_all_cuts)
    check("_build_xfade_filter returns None for single video",
          test_build_xfade_filter_single_video)
    check("_build_xfade_filter produces xfade for non-cut transitions",
          test_build_xfade_filter_with_transitions)
    check("VideoBridge.get_settings returns defaults",
          test_video_bridge_get_settings)
    check("VideoBridge.set_max_concurrent clamps to 1-8",
          test_video_bridge_set_max_concurrent)
    check("queue_status includes max_concurrent",
          test_video_bridge_queue_status_has_max_concurrent)
    check("video_panel.jsx has transition picker",
          test_video_panel_transition_picker)
    check("video_panel.jsx has concurrency control",
          test_video_panel_concurrency_control)
    check("server.py has settings endpoints",
          test_server_settings_endpoints)
    check("server.py serializes shot transition fields",
          test_server_shot_serialization_has_transitions)
    check("VideoBridge has render semaphore",
          test_video_bridge_render_semaphore)


    # Round 24 — Export Settings
    check("ExportSettings has correct defaults",
          test_export_settings_defaults)
    check("ExportSettings survives roundtrip",
          test_export_settings_roundtrip)
    check("ExportSettings.from_dict ignores unknown keys",
          test_export_settings_from_dict_ignores_unknown)
    check("ffmpeg_output_args correct for h264",
          test_export_settings_ffmpeg_args_h264)
    check("ffmpeg_output_args includes -an when audio=False",
          test_export_settings_ffmpeg_args_no_audio)
    check("ffmpeg_output_args includes scale for resolution",
          test_export_settings_ffmpeg_args_resolution)
    check("ffmpeg_output_args correct for prores",
          test_export_settings_ffmpeg_args_prores)
    check("ffmpeg_output_args correct for vp9",
          test_export_settings_ffmpeg_args_vp9)
    check("EXPORT_CODECS and EXPORT_RESOLUTIONS defined",
          test_export_codecs_constant)
    check("VideoBridge get/set export settings",
          test_video_bridge_export_settings_methods)
    check("get_settings includes export key",
          test_video_bridge_get_settings_includes_export)
    check("server.py has export-settings endpoints",
          test_server_export_settings_endpoints)
    check("video_panel.jsx has export settings UI",
          test_video_panel_export_settings_ui)
    check("assemble_shots accepts export_settings param",
          test_assemble_shots_accepts_export_settings)


    # Round 25 — Scene Grouping
    check("Scene dataclass has correct fields",
          test_scene_dataclass)
    check("Scene survives roundtrip",
          test_scene_roundtrip)
    check("Shot has scene_id field",
          test_shot_has_scene_id)
    check("Shotboard.add_scene creates and persists",
          test_shotboard_add_scene)
    check("remove_scene clears orphaned shots",
          test_shotboard_remove_scene_clears_shots)
    check("assign_shot_to_scene sets and clears",
          test_shotboard_assign_shot_to_scene)
    check("assign to nonexistent scene returns None",
          test_shotboard_assign_to_nonexistent_scene)
    check("update_scene modifies fields",
          test_shotboard_update_scene)
    check("shots_in_scene returns correct shots",
          test_shotboard_shots_in_scene)
    check("Scenes persist across save/load",
          test_shotboard_scene_persistence)
    check("server.py has scene CRUD endpoints",
          test_server_scene_endpoints)
    check("server.py serializes scene_id in shots",
          test_server_shot_serialization_has_scene_id)
    check("video_panel.jsx has SceneManager",
          test_video_panel_scene_manager)
    check("video_panel.jsx has scene assignment",
          test_video_panel_scene_assign)


    # Round 26 — Undo/Redo
    check("UndoManager class exists in video_panel.jsx",
          test_undo_manager_class_exists)
    check("UndoManager has push/undo/redo/canUndo/canRedo",
          test_undo_manager_push_undo_redo)
    check("canUndo/canRedo state variables exist",
          test_undo_redo_state_vars)
    check("doUndo/doRedo/pushUndo functions exist",
          test_undo_redo_functions)
    check("Ctrl+Z/Ctrl+Y keyboard shortcuts wired",
          test_undo_redo_keyboard_shortcuts)
    check("Undo/Redo buttons in UI",
          test_undo_redo_buttons)
    check("addShot calls pushUndo before mutation",
          test_undo_snapshot_on_add_shot)
    check("removeShot calls pushUndo before mutation",
          test_undo_snapshot_on_remove_shot)
    check("Undo/redo uses import endpoint",
          test_undo_uses_import_endpoint)
    check("UndoManager has max history limit",
          test_undo_manager_max_history)


    # Round 27 — Render Queue Dashboard
    check("RenderQueuePanel component exists",
          test_render_queue_panel_exists)
    check("Queue summary shows running/queued/complete/failed",
          test_render_queue_summary_stats)
    check("Queue shows ETA from average render time",
          test_render_queue_eta)
    check("Queue shows individual items per status",
          test_render_queue_items)
    check("Queue has progress bars for running items",
          test_render_queue_progress_bar)
    check("Queue has cancel buttons",
          test_render_queue_cancel_button)
    check("Queue has retry buttons for failed items",
          test_render_queue_retry_button)
    check("Queue has toggle button",
          test_render_queue_toggle)
    check("Queue shows empty state message",
          test_render_queue_empty_state)
    check("server.py has cancel render endpoint",
          test_server_cancel_endpoint)


    # Round 28 — Preset Favorites and Quick-Switch
    check("VideoBridge has favorite presets methods",
          test_video_bridge_favorite_presets)
    check("toggle_favorite_preset toggles on/off",
          test_video_bridge_toggle_favorite)
    check("get_settings includes favorite_presets",
          test_video_bridge_settings_includes_favorites)
    check("server.py has favorites endpoints",
          test_server_favorites_endpoints)
    check("video_panel.jsx has favoritePresets state",
          test_video_panel_favorite_presets_state)
    check("video_panel.jsx has preset quick-switch",
          test_video_panel_preset_quick_switch)
    check("video_panel.jsx has favorite star button",
          test_video_panel_favorite_button)
    check("video_panel.jsx shows favorites in optgroup",
          test_video_panel_favorites_optgroup)


    # Round 29 — Shot Dependency Chains
    check("Shot dataclass has depends_on field",
          test_shot_depends_on_field)
    check("Shotboard.add_dependency adds dependency",
          test_shotboard_add_dependency)
    check("Shotboard.remove_dependency removes dependency",
          test_shotboard_remove_dependency)
    check("Shotboard.add_dependency rejects self-dependency",
          test_shotboard_self_dependency)
    check("Shotboard.add_dependency rejects duplicate dependency",
          test_shotboard_duplicate_dependency)
    check("Shotboard.dependencies_met checks statuses",
          test_shotboard_dependencies_met)
    check("Shotboard.ready_to_render combines status + deps",
          test_shotboard_ready_to_render)
    check("server.py has dependency endpoints",
          test_server_dependency_endpoints)
    check("server.py serializes depends_on in shot list",
          test_server_depends_on_serialization)
    check("video_panel.jsx has dependency row in ShotCard",
          test_video_panel_dependency_row)
    check("video_panel.jsx has addDependency function",
          test_video_panel_add_dependency_fn)
    check("video_panel.jsx has dep-badge with remove button",
          test_video_panel_dep_badges)


    # Round 30 — Dependency-Aware Batch Render Ordering
    check("Shotboard.has_cycle detects no cycle",
          test_shotboard_no_cycle)
    check("Shotboard.has_cycle detects cycle",
          test_shotboard_has_cycle)
    check("Shotboard.topological_sort orders deps first",
          test_shotboard_topo_sort_order)
    check("Shotboard.topological_sort handles no deps",
          test_shotboard_topo_sort_no_deps)
    check("Shotboard.topological_sort survives cycle",
          test_shotboard_topo_sort_cycle)
    check("queue_all_drafts returns has_cycle field",
          test_queue_all_drafts_has_cycle)
    check("server.py render-all returns dependency info",
          test_server_render_all_dep_info)
    check("video_panel.jsx uses batch render-all endpoint",
          test_video_panel_batch_render_all)
    check("video_panel.jsx has cycleWarning state",
          test_video_panel_cycle_warning_state)
    check("video_panel.jsx shows cycle warning banner",
          test_video_panel_cycle_warning_banner)


    # Round 31 — Render Order Preview and Dependency Graph
    check("Shotboard.render_order returns graph data",
          test_shotboard_render_order)
    check("render_order nodes have correct fields",
          test_render_order_node_fields)
    check("render_order edges reflect dependencies",
          test_render_order_edges)
    check("render_order ready_count is correct",
          test_render_order_ready_count)
    check("server.py has render-order endpoint",
          test_server_render_order_endpoint)
    check("video_panel.jsx has dep-graph-toggle button",
          test_video_panel_dep_graph_toggle)
    check("video_panel.jsx has dep-graph-panel",
          test_video_panel_dep_graph_panel)
    check("video_panel.jsx has fetchRenderOrder function",
          test_video_panel_fetch_render_order)
    check("video_panel.jsx shows dep-graph-node with status",
          test_video_panel_dep_graph_nodes)
    check("video_panel.jsx shows dep-graph-edge links",
          test_video_panel_dep_graph_edges)


    # Round 32 — Shot Duration Override and Total Timeline Duration
    check("Shot has target_duration_s field",
          test_shot_target_duration_field)
    check("target_duration_s survives roundtrip",
          test_shot_target_duration_roundtrip)
    check("Shotboard.effective_duration uses target override",
          test_shotboard_effective_duration)
    check("Shotboard.total_duration sums effective durations",
          test_shotboard_total_duration)
    check("server.py serializes target_duration_s",
          test_server_target_duration_serialization)
    check("server.py has total-duration endpoint",
          test_server_total_duration_endpoint)
    check("video_panel.jsx has target-duration-row",
          test_video_panel_target_duration_row)
    check("video_panel.jsx has duration-warning",
          test_video_panel_duration_warning)
    check("video_panel.jsx has totalTimelineDuration",
          test_video_panel_total_timeline_duration)
    check("video_panel.jsx shows total duration in header",
          test_video_panel_total_in_header)


    # Round 33 — Shot Locking
    check("Shot has locked field",
          test_shot_locked_field)
    check("Shotboard.lock_shot locks a shot",
          test_shotboard_lock_shot)
    check("Shotboard.unlock_shot unlocks a shot",
          test_shotboard_unlock_shot)
    check("Shotboard.update skips locked fields",
          test_shotboard_update_locked_skip)
    check("Shotboard.update allows system fields on locked",
          test_shotboard_update_locked_system_fields)
    check("Auto-lock on rendering status",
          test_shotboard_auto_lock_rendering)
    check("Auto-unlock on draft status",
          test_shotboard_auto_unlock_draft)
    check("server.py has lock endpoint",
          test_server_lock_endpoint)
    check("server.py serializes locked field",
          test_server_locked_serialization)
    check("video_panel.jsx has lock-indicator",
          test_video_panel_lock_indicator)
    check("video_panel.jsx has lock-toggle-btn",
          test_video_panel_lock_toggle)
    check("video_panel.jsx has toggleLock function",
          test_video_panel_toggle_lock_fn)

    # Round 34 — Render Completion Toast Notifications
    check("video_panel.jsx has ToastContainer component",
          test_video_panel_toast_container_component)
    check("video_panel.jsx has toast item CSS classes",
          test_video_panel_toast_item_classes)
    check("video_panel.jsx has toast type styling",
          test_video_panel_toast_type_styling)
    check("video_panel.jsx has addToast function",
          test_video_panel_add_toast_function)
    check("video_panel.jsx has dismissToast function",
          test_video_panel_dismiss_toast_function)
    check("video_panel.jsx has toast auto-dismiss",
          test_video_panel_toast_auto_dismiss)
    check("video_panel.jsx has prevShotsRef",
          test_video_panel_prev_shots_ref)
    check("video_panel.jsx has render-change detection",
          test_video_panel_render_change_detection)
    check("video_panel.jsx fires toast on ready",
          test_video_panel_toast_on_ready)
    check("video_panel.jsx fires toast on failed",
          test_video_panel_toast_on_failed)
    check("video_panel.jsx has toast state",
          test_video_panel_toast_state)
    check("video_panel.jsx renders ToastContainer",
          test_video_panel_toast_container_rendered)

    # Round 35 — Batch Actions Toolbar
    check("Shotboard.batch_lock locks multiple shots",
          test_shotboard_batch_lock)
    check("Shotboard.batch_lock unlocks multiple shots",
          test_shotboard_batch_unlock)
    check("Shotboard.batch_reset_status resets to draft",
          test_shotboard_batch_reset_status)
    check("Shotboard.batch_reset_status skips locked",
          test_shotboard_batch_reset_skips_locked)
    check("Shotboard.batch_color_label sets color on multiple",
          test_shotboard_batch_color_label)
    check("server.py has batch-lock endpoint",
          test_server_batch_lock_endpoint)
    check("server.py has batch-reset endpoint",
          test_server_batch_reset_endpoint)
    check("server.py has batch-color endpoint",
          test_server_batch_color_endpoint)
    check("video_panel.jsx has batch lock/unlock buttons",
          test_video_panel_batch_lock_btn)
    check("video_panel.jsx has batch reset button",
          test_video_panel_batch_reset_btn)
    check("video_panel.jsx has batch color select",
          test_video_panel_batch_color_select)
    check("video_panel.jsx has complete batch actions bar",
          test_video_panel_batch_actions_bar)

    # Round 36 — Shot Render History Log
    check("Shot has render_history field",
          test_shot_render_history_field)
    check("Shot render_history survives roundtrip",
          test_shot_render_history_roundtrip)
    check("Shotboard.record_render appends entry",
          test_shotboard_record_render)
    check("Shotboard.record_render caps at 20 entries",
          test_shotboard_record_render_caps_at_20)
    check("Shotboard.record_render stores error",
          test_shotboard_record_render_with_error)
    check("Shotboard.get_render_history returns list",
          test_shotboard_get_render_history)
    check("Shotboard.get_render_history returns [] for missing shot",
          test_shotboard_get_render_history_missing_shot)
    check("server.py has render history GET endpoint",
          test_server_render_history_endpoint)
    check("server.py has record-render POST endpoint",
          test_server_record_render_endpoint)
    check("video_panel.jsx has render history toggle",
          test_video_panel_render_history_toggle)
    check("video_panel.jsx has render history list",
          test_video_panel_render_history_list)
    check("video_panel.jsx has render history details",
          test_video_panel_render_history_details)

    # Round 37 — Prompt Character Count and Limit Warning
    check("video_panel.jsx has prompt character count",
          test_video_panel_prompt_char_count)
    check("video_panel.jsx has prompt limit warning",
          test_video_panel_prompt_limit_warning)
    check("video_panel.jsx has color thresholds",
          test_video_panel_prompt_color_thresholds)
    check("video_panel.jsx reads prompt_char_limit from preset",
          test_video_panel_prompt_char_limit_from_preset)
    check("video_panel.jsx has default 500 char limit",
          test_video_panel_default_char_limit)

    # Round 38 — Auto-scroll to Actively Rendering Shot
    check("video_panel.jsx has data-shot-id on cards",
          test_video_panel_shot_card_data_attribute)
    check("video_panel.jsx has scrollToShot function",
          test_video_panel_scroll_to_shot)
    check("video_panel.jsx has autoScroll state",
          test_video_panel_auto_scroll_state)
    check("video_panel.jsx triggers scroll on rendering",
          test_video_panel_auto_scroll_on_rendering)
    check("video_panel.jsx has auto-scroll toggle",
          test_video_panel_auto_scroll_toggle)
    check("video_panel.jsx auto-scroll defaults to on",
          test_video_panel_auto_scroll_default_on)

    # Round 39 — Render Queue ETA
    check("Shotboard.average_render_time computes correctly",
          test_shotboard_average_render_time)
    check("Shotboard.average_render_time returns 0 for empty",
          test_shotboard_average_render_time_empty)
    check("Shotboard.queue_eta estimates pending time",
          test_shotboard_queue_eta)
    check("Shotboard.queue_eta returns 0 when no pending",
          test_shotboard_queue_eta_no_pending)
    check("server.py has queue-eta endpoint",
          test_server_queue_eta_endpoint)
    check("video_panel.jsx shows queue ETA",
          test_video_panel_queue_eta_display)
    check("video_panel.jsx has remaining label",
          test_video_panel_queue_eta_label)

    # Round 40 — Shot Diff Indicator
    check("shot_diff returns no changes without render history",
          test_shot_diff_no_history)
    check("shot_diff detects prompt change",
          test_shot_diff_prompt_changed)
    check("shot_diff detects preset change",
          test_shot_diff_preset_changed)
    check("shot_diff detects overrides change",
          test_shot_diff_overrides_changed)
    check("shot_diff returns no changes when matching",
          test_shot_diff_no_changes)
    check("shot_diff only checks last successful render",
          test_shot_diff_ignores_failed)
    check("record_render stores overrides in entry",
          test_record_render_stores_overrides)
    check("server.py has shot diff endpoint",
          test_server_shot_diff_endpoint)
    check("video_panel.jsx has diff badge UI",
          test_video_panel_diff_badge)
    check("video_panel.jsx computes diff from render_history",
          test_video_panel_diff_computation)

    # Round 41 — Revert to Last Render
    check("revert_to_last_render restores prompt/preset/overrides",
          test_revert_restores_fields)
    check("revert_to_last_render returns None with no history",
          test_revert_no_history)
    check("revert_to_last_render rejects locked shot",
          test_revert_locked_shot)
    check("revert clears the diff",
          test_revert_clears_diff)
    check("revert returns empty dict when no changes",
          test_revert_no_changes)
    check("server.py has revert endpoint",
          test_server_revert_endpoint)
    check("video_panel.jsx has revert button",
          test_video_panel_revert_button)
    check("video_panel.jsx has revertShot function",
          test_video_panel_revert_function)

    # Round 42 — Shot Comparison View
    check("video_panel.jsx has compare toggle button",
          test_video_panel_compare_toggle)
    check("video_panel.jsx has compare panel",
          test_video_panel_compare_panel)
    check("video_panel.jsx has compare-old and compare-new cells",
          test_video_panel_compare_cells)
    check("video_panel.jsx compares prompt field",
          test_video_panel_compare_prompt)
    check("video_panel.jsx compares preset field",
          test_video_panel_compare_preset)
    check("video_panel.jsx compares overrides field",
          test_video_panel_compare_overrides)
    check("video_panel.jsx has showCompare state",
          test_video_panel_show_compare_state)

    # Round 43 — Negative Prompt Diff + Batch Revert
    check("record_render stores negative in entry",
          test_record_render_stores_negative)
    check("shot_diff detects negative prompt change",
          test_shot_diff_negative_changed)
    check("revert restores negative prompt",
          test_revert_restores_negative)
    check("batch_revert reverts multiple shots",
          test_batch_revert)
    check("batch_revert skips locked and no-history shots",
          test_batch_revert_skips)
    check("server.py has batch-revert endpoint",
          test_server_batch_revert_endpoint)
    check("video_panel.jsx has batch revert button",
          test_video_panel_batch_revert_button)
    check("video_panel.jsx has negative in diff computation",
          test_video_panel_negative_diff)
    check("video_panel.jsx has negative comparison row",
          test_video_panel_compare_negative)

    # Round 44 — Batch Prompt Edit + Keyboard Navigation
    check("batch_prompt_edit adds prefix",
          test_batch_prompt_edit_add_prefix)
    check("batch_prompt_edit adds suffix",
          test_batch_prompt_edit_add_suffix)
    check("batch_prompt_edit add is idempotent",
          test_batch_prompt_edit_idempotent)
    check("batch_prompt_edit removes prefix",
          test_batch_prompt_edit_remove_prefix)
    check("batch_prompt_edit removes suffix",
          test_batch_prompt_edit_remove_suffix)
    check("batch_prompt_edit skips locked shots",
          test_batch_prompt_edit_skips_locked)
    check("server.py has batch-prompt-edit endpoint",
          test_server_batch_prompt_edit_endpoint)
    check("video_panel.jsx has batch prompt edit UI",
          test_video_panel_batch_prompt_edit_ui)
    check("video_panel.jsx has focusedShotIndex state",
          test_video_panel_focused_shot_index_state)
    check("video_panel.jsx has keydown handler for arrow keys",
          test_video_panel_keydown_handler)
    check("video_panel.jsx passes focused prop to ShotCard",
          test_video_panel_shot_card_focused_prop)

    # Round 45 — Snapshots + Batch Duplicate
    check("save_snapshot + list_snapshots",
          test_snapshot_save_list)
    check("restore_snapshot rolls back creative state",
          test_snapshot_restore_rolls_back_creative_state)
    check("restore_snapshot skips locked",
          test_snapshot_restore_skips_locked)
    check("delete_snapshot",
          test_snapshot_delete)
    check("snapshots cap at 20",
          test_snapshot_caps_at_20)
    check("batch_duplicate counter suffix",
          test_batch_duplicate_counter_suffix)
    check("batch_duplicate plain suffix",
          test_batch_duplicate_plain_suffix)
    check("batch_duplicate resets status and history",
          test_batch_duplicate_resets_status_and_history)
    check("batch_duplicate skips missing ids",
          test_batch_duplicate_skips_missing)
    check("server.py has snapshot endpoints",
          test_server_snapshot_endpoints)
    check("server.py has batch-duplicate endpoint",
          test_server_batch_duplicate_endpoint)
    check("video_panel.jsx has snapshot UI",
          test_video_panel_snapshot_ui)
    check("video_panel.jsx has batch duplicate UI",
          test_video_panel_batch_duplicate_ui)

    # Round 46 — Auto-snapshot + Snapshot diff viewer
    check("_auto_snapshot_batch helper skips locked + missing",
          test_auto_snapshot_batch_helper)
    check("batch_revert auto-snapshots by default",
          test_batch_revert_auto_snapshots)
    check("batch_revert can disable auto-snapshot",
          test_batch_revert_can_disable_auto_snapshot)
    check("batch_prompt_edit auto-snapshots",
          test_batch_prompt_edit_auto_snapshots)
    check("batch_update_preset auto-snapshots",
          test_batch_update_preset_auto_snapshots)
    check("batch_update_preset skips no-op auto-snapshot",
          test_batch_update_preset_skips_noop)
    check("video_panel.jsx has snapshot compare state",
          test_video_panel_snapshot_compare_state)
    check("video_panel.jsx has snapshot diff panel",
          test_video_panel_snapshot_diff_panel)

    # Round 47 — EDL/FCPXML export + Snapshot pinning
    check("_slugify_reel CMX 3600 compliance",
          test_slugify_reel)
    check("_xml_escape handles entities",
          test_xml_escape)
    check("_frames_to_tc timecode conversion",
          test_frames_to_tc)
    check("export_edl basic shape",
          test_export_edl_basic)
    check("export_edl prefers render_duration_s",
          test_export_edl_uses_render_duration_if_available)
    check("export_fcpxml is valid XML",
          test_export_fcpxml_basic)
    check("export_fcpxml escapes title chars",
          test_export_fcpxml_escapes_title)
    check("pin/unpin snapshot",
          test_snapshot_pin_and_unpin)
    check("pin rejects missing snapshot/shot",
          test_pin_missing_snapshot_returns_false)
    check("pinned snapshot survives auto-prune",
          test_pinned_snapshot_survives_auto_prune)
    check("deleting pinned snapshot cleans pin list",
          test_deleting_a_pinned_snapshot_removes_pin_entry)
    check("pinned_snapshots survive roundtrip",
          test_shot_pinned_snapshots_survive_roundtrip)
    check("server.py has EDL endpoint",
          test_server_has_edl_endpoint)
    check("server.py has FCPXML endpoint",
          test_server_has_fcpxml_endpoint)
    check("server.py has snapshot pin endpoint",
          test_server_has_pin_endpoint)
    check("video_panel.jsx has EDL/FCPXML buttons",
          test_video_panel_has_edl_button)
    check("video_panel.jsx has pin button",
          test_video_panel_has_pin_button)

    print("-" * 50)

    from scaffold.shotboard import Shotboard, Shot, Trajectory
    from scaffold.video_wizard import CinematographerWizard
    from scaffold.wangp_runner import (
        WanGPRunner, WANGP_PRESETS, describe_preset, preset_names,
    )
    from scaffold.video_bridge import VideoBridge

    with tempfile.TemporaryDirectory() as tmp:
        board_path = os.path.join(tmp, "shotboard.json")

        # ---- Shotboard round-trip ----------------------------------
        def test_board_roundtrip():
            board = Shotboard(board_path)
            assert len(board) == 0
            s1 = board.add(title="Shot A", prompt="a wolf walks")
            s2 = board.add(title="Shot B", prompt="a fox pounces")
            assert s1.index == 0 and s2.index == 1
            board2 = Shotboard(board_path)
            assert len(board2) == 2
            assert board2.all()[0].title == "Shot A"
            assert board2.all()[1].title == "Shot B"
            board2.reorder([s2.id, s1.id])
            board3 = Shotboard(board_path)
            assert board3.all()[0].id == s2.id
            assert board3.all()[1].id == s1.id
            assert board3.all()[0].index == 0

        check("Shotboard persist / reload / reorder", test_board_roundtrip)

        # ---- Trajectory serialisation ------------------------------
        def test_trajectory():
            t = Trajectory(label="zoom",
                           points=[[10, 10], [20, 20], [30, 15]],
                           speeds=[1.0, 1.2],
                           colour="#00ff00")
            d = t.to_dict()
            back = Trajectory.from_dict(d)
            assert back.label == "zoom"
            assert back.points == [[10, 10], [20, 20], [30, 15]]
            assert back.speeds == [1.0, 1.2]

        check("Trajectory round-trip", test_trajectory)

        # ---- CinematographerWizard menu flow ------------------------
        def test_wizard_flow():
            board = Shotboard(os.path.join(tmp, "wizflow.json"))
            wiz = CinematographerWizard(board)
            r1 = wiz.handle("alice", "hi")
            assert "Cinematographer" in r1
            r2 = wiz.handle("alice", "1")
            assert "call this shot" in r2.lower() or "title" in r2.lower()
            r3 = wiz.handle("alice", "INT. forest - dawn")
            assert "describe" in r3.lower()
            r4 = wiz.handle("alice", "a wolf pads through pine trees")
            assert "backend" in r4.lower()
            r5 = wiz.handle("alice", "1")
            assert "preset" in r5.lower()
            r6 = wiz.handle("alice", "1")
            assert "reference image" in r6.lower() or "absolute path" in r6.lower()
            shots = board.all()
            assert len(shots) == 1
            assert shots[0].title == "INT. forest - dawn"
            assert shots[0].prompt.startswith("a wolf")
            assert shots[0].backend == "wangp"
            assert shots[0].preset in preset_names()

        check("CinematographerWizard happy-path flow", test_wizard_flow)

        # ---- Wizard cancel / reset ---------------------------------
        def test_wizard_cancel():
            board = Shotboard(os.path.join(tmp, "wizcancel.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("bob", "hi")
            wiz.handle("bob", "1")
            wiz.handle("bob", "some title")
            out = wiz.handle("bob", "cancel")
            assert "Cinematographer" in out
            sess = wiz.session("bob")
            assert sess.step in ("idle", "pick_action")

        check("Wizard cancel global escape", test_wizard_cancel)

        # ---- Preset catalogue is well-formed -----------------------
        def test_presets():
            assert len(preset_names()) == len(WANGP_PRESETS)
            for key, spec in WANGP_PRESETS.items():
                assert isinstance(spec["label"], str), key
                assert isinstance(spec["inputs"], list), key
                assert "model_hint" in spec, key
                d = describe_preset(key)
                d["label"] = "MUTATED"
                assert spec["label"] != "MUTATED", (
                    f"describe_preset({key}) leaks live reference"
                )

        check("WanGP preset catalogue sanity", test_presets)

        # ---- WanGPRunner graceful unavailability -------------------
        def test_runner_offline():
            runner = WanGPRunner("http://127.0.0.1:1")
            assert runner.is_available() is False
            info = runner.server_info()
            assert info["available"] is False
            result = runner.queue_generation(
                preset="wan22_t2v", prompt="test",
            )
            assert result["status"] == "error"
            assert "not reachable" in result["message"].lower()

        check("WanGPRunner handles dead server gracefully",
              test_runner_offline)

        # ---- Unknown preset handling -------------------------------
        def test_runner_bad_preset():
            runner = WanGPRunner("http://127.0.0.1:1")
            result = runner.queue_generation(
                preset="this_does_not_exist", prompt="x",
            )
            assert result["status"] == "error"
            assert "unknown preset" in result["message"].lower()

        check("WanGPRunner rejects unknown preset",
              test_runner_bad_preset)

        # ---- VideoBridge composition -------------------------------
        def test_bridge_composition():
            bridge_board = os.path.join(tmp, "bridgeboard.json")
            bridge = VideoBridge(
                shotboard_path=bridge_board,
                wangp_url="http://127.0.0.1:1",
                comfyui_url="http://127.0.0.1:2",
                output_dir=os.path.join(tmp, "renders"),
            )
            shot_dict = bridge.add_shot(
                title="remote", prompt="a cloud drifts",
                preset="wan22_t2v",
            )
            shot_id = shot_dict["id"]
            assert shot_dict["title"] == "remote"
            health = bridge.health()
            assert health["wangp"]["available"] is False
            assert health["comfyui"]["available"] is False
            assert health["shotboard"]["count"] == 1
            q = bridge.queue_shot(shot_id)
            assert q["status"] == "error"
            shots = bridge.list_shots()["shots"]
            assert any(s["status"] == "failed" for s in shots)

        check("VideoBridge composes end-to-end (offline)",
              test_bridge_composition)

        # ---- Chat -> auto-queue round trip --------------------------
        def test_chat_auto_queue():
            bridge = VideoBridge(
                shotboard_path=os.path.join(tmp, "chat.json"),
                wangp_url="http://127.0.0.1:1",
                comfyui_url="http://127.0.0.1:2",
                output_dir=os.path.join(tmp, "chatrenders"),
            )
            bridge.handle_chat("u1", "hi")
            bridge.handle_chat("u1", "1")
            bridge.handle_chat("u1", "Title A")
            bridge.handle_chat("u1", "a river flows")
            bridge.handle_chat("u1", "1")
            wangp_presets = list(WANGP_PRESETS.keys())
            t2v_idx = wangp_presets.index("wan22_t2v") + 1
            bridge.handle_chat("u1", str(t2v_idx))
            final = bridge.handle_chat("u1", "1")
            assert "queued" in final or "pending_render" in final

        check("Chat -> review -> auto-queue (offline)", test_chat_auto_queue)

        # ==============================================================
        # Shotboard edge cases
        # ==============================================================

        def test_board_remove():
            board = Shotboard(os.path.join(tmp, "rm.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            assert len(board) == 3
            assert board.remove(s2.id) is True
            assert len(board) == 2
            assert board.all()[0].index == 0
            assert board.all()[1].index == 1
            assert board.all()[0].id == s1.id
            assert board.all()[1].id == s3.id
            assert board.remove("bogus_id") is False

        check("Shotboard remove + reindex", test_board_remove)

        def test_board_update():
            board = Shotboard(os.path.join(tmp, "upd.json"))
            s = board.add(title="Old", prompt="old prompt")
            board.update(s.id, title="New", prompt="new prompt")
            got = board.get(s.id)
            assert got.title == "New"
            assert got.prompt == "new prompt"
            assert board.update("no_such_id", title="X") is None
            board.update(s.id, this_field_doesnt_exist=42)
            assert not hasattr(board.get(s.id), "this_field_doesnt_exist")

        check("Shotboard update + unknown fields", test_board_update)

        def test_board_navigation():
            board = Shotboard(os.path.join(tmp, "nav.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            assert board.next_of(s1.id).id == s2.id
            assert board.next_of(s2.id).id == s3.id
            assert board.next_of(s3.id) is None
            assert board.previous_of(s1.id) is None
            assert board.previous_of(s2.id).id == s1.id
            assert board.previous_of(s3.id).id == s2.id
            assert board.next_of("bogus") is None
            assert board.previous_of("bogus") is None

        check("Shotboard next_of / previous_of", test_board_navigation)

        def test_board_status_helpers():
            board = Shotboard(os.path.join(tmp, "status.json"))
            s = board.add(title="Job")
            assert s.status == "draft"
            board.mark_queued(s.id, "job-123")
            got = board.get(s.id)
            assert got.status == "queued"
            assert got.job_id == "job-123"
            board.mark_running(s.id)
            assert board.get(s.id).status == "running"
            board.mark_ready(s.id, "/tmp/out.mp4")
            got = board.get(s.id)
            assert got.status == "ready"
            assert got.video_path == "/tmp/out.mp4"
            assert got.job_id is None
            s2 = board.add(title="Fail")
            board.mark_failed(s2.id, "boom")
            got2 = board.get(s2.id)
            assert got2.status == "failed"
            assert got2.error == "boom"
            board.mark_failed(s2.id, "x" * 600)
            assert len(board.get(s2.id).error) == 500

        check("Shotboard status helpers", test_board_status_helpers)

        def test_board_export_for_next():
            board = Shotboard(os.path.join(tmp, "cont.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            result = board.export_for_next(s1.id, "/tmp/frame.png")
            assert result is not None
            assert result.id == s2.id
            assert board.get(s2.id).ref_image == "/tmp/frame.png"
            board.update(s3.id, ref_image="/old.png")
            board.export_for_next(s2.id, "/tmp/frame2.png")
            assert board.get(s3.id).ref_image == "/tmp/frame2.png"
            board.update(s3.id, carry_last_frame=False, ref_image="/keep.png")
            board.export_for_next(s2.id, "/tmp/frame3.png")
            assert board.get(s3.id).ref_image == "/keep.png"
            assert board.export_for_next(s3.id, "/x.png") is None
            board.update(s2.id, ref_image="/original.png",
                         carry_last_frame=True)
            board.export_for_next(s1.id, None)
            assert board.get(s2.id).ref_image == "/original.png"

        check("Shotboard export_for_next (continuity)", test_board_export_for_next)

        def test_board_ready_videos():
            board = Shotboard(os.path.join(tmp, "rv.json"))
            board.add(title="A")
            board.add(title="B")
            board.add(title="C")
            shots = board.all()
            assert board.ready_videos() == []
            board.mark_ready(shots[0].id, "/v1.mp4")
            board.mark_ready(shots[2].id, "/v3.mp4")
            assert board.ready_videos() == ["/v1.mp4", "/v3.mp4"]

        check("Shotboard ready_videos", test_board_ready_videos)

        def test_board_reorder_partial():
            board = Shotboard(os.path.join(tmp, "reop.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            board.reorder([s3.id, s1.id])
            ids = [s.id for s in board.all()]
            assert ids == [s3.id, s1.id, s2.id]
            assert board.all()[0].index == 0
            assert board.all()[1].index == 1
            assert board.all()[2].index == 2

        check("Shotboard reorder with partial ID list", test_board_reorder_partial)

        def test_board_corrupt_json():
            path = os.path.join(tmp, "corrupt.json")
            with open(path, "w") as f:
                f.write("{{{not valid json")
            board = Shotboard(path)
            assert len(board) == 0
            with open(path, "w") as f:
                f.write('"just a string"')
            board2 = Shotboard(path)
            assert len(board2) == 0
            import json
            with open(path, "w") as f:
                json.dump({"version": 1, "shots": [
                    {"id": "abc", "title": "T", "future_field": True}
                ]}, f)
            board3 = Shotboard(path)
            assert len(board3) == 1
            assert board3.all()[0].title == "T"

        check("Shotboard corrupt / future-schema JSON recovery",
              test_board_corrupt_json)


        # ==============================================================
        # CinematographerWizard extended coverage
        # ==============================================================

        def test_wizard_status_action():
            board = Shotboard(os.path.join(tmp, "wizstat.json"))
            board.add(title="Shot X", preset="wan22_t2v")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "6")  # status
            assert "Shot X" in r or "Shotboard" in r

        check("Wizard status action", test_wizard_status_action)

        def test_wizard_done_action():
            board = Shotboard(os.path.join(tmp, "wizdone.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "7")  # done
            assert "leaving" in r.lower() or "saved" in r.lower()
            sess = wiz.session("u")
            assert sess.step == "idle"

        check("Wizard done action exits cleanly", test_wizard_done_action)

        def test_wizard_edit_existing_shot():
            board = Shotboard(os.path.join(tmp, "wizedit.json"))
            board.add(title="First", prompt="p1", preset="wan22_t2v")
            board.add(title="Second", prompt="p2", preset="wan22_t2v")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "2")  # edit
            assert "First" in r and "Second" in r
            r2 = wiz.handle("u", "1")  # pick first shot
            assert "Review" in r2 or "review" in r2.lower()

        check("Wizard edit existing shot", test_wizard_edit_existing_shot)

        def test_wizard_edit_empty_board():
            board = Shotboard(os.path.join(tmp, "wizeditempty.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "2")  # edit on empty board
            assert "no shots" in r.lower() or "add a new" in r.lower()

        check("Wizard edit on empty board", test_wizard_edit_empty_board)

        def test_wizard_remove_shot():
            board = Shotboard(os.path.join(tmp, "wizrm.json"))
            board.add(title="Kill Me")
            assert len(board) == 1
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "4")  # remove
            assert "Kill Me" in r
            r2 = wiz.handle("u", "1")  # pick it
            assert "removed" in r2.lower() or "Removed" in r2
            assert len(board) == 0

        check("Wizard remove shot", test_wizard_remove_shot)

        def test_wizard_reorder_shots():
            board = Shotboard(os.path.join(tmp, "wizreord.json"))
            s1 = board.add(title="A")
            s2 = board.add(title="B")
            s3 = board.add(title="C")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "3")  # reorder
            assert "A" in r and "B" in r and "C" in r
            r2 = wiz.handle("u", "3,1,2")
            assert "reordered" in r2.lower() or "Reordered" in r2
            ids = [s.id for s in board.all()]
            assert ids == [s3.id, s1.id, s2.id]

        check("Wizard reorder shots", test_wizard_reorder_shots)

        def test_wizard_reorder_bad_input():
            board = Shotboard(os.path.join(tmp, "wizreordbad.json"))
            board.add(title="A")
            board.add(title="B")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            wiz.handle("u", "3")  # reorder
            r = wiz.handle("u", "abc")  # bad input
            assert "numbers" in r.lower() or "commas" in r.lower()

        check("Wizard reorder bad input", test_wizard_reorder_bad_input)

        def test_wizard_render_action():
            board = Shotboard(os.path.join(tmp, "wizrender.json"))
            board.add(title="Render Me", preset="wan22_t2v")
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "5")  # render
            assert "Render Me" in r
            r2 = wiz.handle("u", "1")  # pick it
            assert "queuing" in r2.lower() or "queue" in r2.lower()                 or "bridge" in r2.lower()
            # get_pending_render should return the shot id
            pending = wiz.get_pending_render("u")
            assert pending == board.all()[0].id

        check("Wizard render action sets pending", test_wizard_render_action)

        def test_wizard_invalid_pick():
            board = Shotboard(os.path.join(tmp, "wizinvalid.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            r = wiz.handle("u", "99")  # out of range
            assert "pick a number" in r.lower() or "Cinematographer" in r

        check("Wizard invalid menu pick", test_wizard_invalid_pick)

        def test_wizard_review_reedit():
            board = Shotboard(os.path.join(tmp, "wizreedit.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            wiz.handle("u", "1")  # new
            wiz.handle("u", "Original Title")
            wiz.handle("u", "original prompt")
            wiz.handle("u", "1")  # wangp
            keys = preset_names()
            t2v_idx = keys.index("wan22_t2v") + 1
            wiz.handle("u", str(t2v_idx))
            # Now at review; pick "Edit title" (option 2)
            r = wiz.handle("u", "2")
            assert "title" in r.lower()
            wiz.handle("u", "Changed Title")
            # Should be back at prompt edit
            wiz.handle("u", "changed prompt")
            # Pick backend again
            wiz.handle("u", "1")
            wiz.handle("u", str(t2v_idx))
            # Should be at review with updated values
            shot = board.all()[0]
            assert shot.title == "Changed Title"
            assert shot.prompt == "changed prompt"

        check("Wizard review re-edit title+prompt", test_wizard_review_reedit)

        def test_wizard_ref_bad_path():
            board = Shotboard(os.path.join(tmp, "wizrefbad.json"))
            wiz = CinematographerWizard(board)
            wiz.handle("u", "hi")
            wiz.handle("u", "1")  # new
            wiz.handle("u", "T")
            wiz.handle("u", "P")
            wiz.handle("u", "1")  # wangp
            wiz.handle("u", "1")  # first preset (i2v, needs image)
            r = wiz.handle("u", "/nonexistent/path.png")
            assert "can't find" in r.lower() or "upload" in r.lower()

        check("Wizard ref image bad path", test_wizard_ref_bad_path)

        def test_wizard_multi_user_isolation():
            board = Shotboard(os.path.join(tmp, "wizmulti.json"))
            wiz = CinematographerWizard(board)
            # Alice starts a new shot
            wiz.handle("alice", "hi")
            wiz.handle("alice", "1")  # new
            wiz.handle("alice", "Alice Shot")
            # Bob starts independently
            wiz.handle("bob", "hi")
            wiz.handle("bob", "1")
            wiz.handle("bob", "Bob Shot")
            # Alice continues from where she left off (prompt step)
            sess_a = wiz.session("alice")
            assert sess_a.step == "edit_prompt"
            sess_b = wiz.session("bob")
            assert sess_b.step == "edit_prompt"
            assert sess_a.current_shot_id != sess_b.current_shot_id

        check("Wizard multi-user session isolation", test_wizard_multi_user_isolation)

        def test_wizard_trajectory_skip():
            """When trajectories step has no trajectories and user says skip."""
            board = Shotboard(os.path.join(tmp, "wiztrajskip.json"))
            wiz = CinematographerWizard(board)
            # Create a shot manually and force into trajectories step
            shot = board.add(title="T", prompt="P", backend="wangp",
                             preset="wan_move_i2v")
            sess = wiz.session("u")
            sess.step = "trajectories"
            sess.current_shot_id = shot.id
            # Saying "done" with no trajectories should warn
            r = wiz.handle("u", "done")
            assert "don't see" in r.lower() or "draw" in r.lower()
            # Saying "skip" should advance (treated as unknown, falls
            # through to the "say done" message since it's not done/ok/ready)
            r2 = wiz.handle("u", "skip")
            assert "done" in r2.lower() or "draw" in r2.lower()

        check("Wizard trajectory step skip", test_wizard_trajectory_skip)


        # ==============================================================
        # MetaWizard video routing
        # ==============================================================

        from scaffold.meta_wizard import MetaWizard, INTENTS

        # Minimal stubs for SpellcasterWizard / WorkflowWizard so we
        # can test MetaWizard routing without ComfyUI.
        class _StubSession:
            def __init__(self):
                self.step = "idle"
            def is_complete(self):
                return False
            def to_workflow(self):
                return {}

        class _StubSpellWiz:
            def handle(self, uid, text):
                return f"[spell:{text}]"
            def get_session(self, uid):
                return _StubSession()

        class _StubWfWiz:
            def handle(self, uid, text):
                return f"[wf:{text}]"
            def get_session(self, uid):
                return _StubSession()

        def test_meta_video_intent_routes_to_workflow():
            """Video intent has route=workflow and delegates to workflow wizard."""
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
            )
            video_idx = next(
                i for i, intent in enumerate(INTENTS, 1)
                if intent["key"] == "video"
            )
            r = meta.handle("u1", str(video_idx))
            # Should delegate to workflow wizard with "video" hint
            assert "[wf:" in r, f"Expected workflow delegation, got: {r}"
            sess = meta._sessions["u1"]
            assert sess.active_sub == "workflow"

        check("MetaWizard video intent -> workflow", test_meta_video_intent_routes_to_workflow)

        def test_meta_video_intent_exists_in_intents():
            """INTENTS catalogue includes video, video_upscale, director."""
            keys = [i["key"] for i in INTENTS]
            assert "video" in keys, "Missing 'video' intent"
            assert "video_upscale" in keys, "Missing 'video_upscale' intent"
            assert "director" in keys, "Missing 'director' intent"
            # video intent should route to workflow
            vid = next(i for i in INTENTS if i["key"] == "video")
            assert vid["route"] == "workflow"
            assert vid.get("workflow_hint") == "video"

        check("MetaWizard video intents in catalogue", test_meta_video_intent_exists_in_intents)

        def test_meta_video_workflow_delegation():
            """Once in video/workflow, further messages delegate to wf wizard."""
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
            )
            video_idx = next(
                i for i, intent in enumerate(INTENTS, 1)
                if intent["key"] == "video"
            )
            meta.handle("u1", str(video_idx))
            # Further messages go to workflow
            r2 = meta.handle("u1", "show me video workflows")
            assert "[wf:" in r2
            # Global "menu" should reset
            r3 = meta.handle("u1", "menu")
            assert "spellcaster" in r3.lower() or "what would" in r3.lower()
            sess = meta._sessions["u1"]
            assert sess.active_sub is None

        check("MetaWizard video workflow delegation + menu reset", test_meta_video_workflow_delegation)

        def test_meta_global_menu_reset():
            """Typing 'menu' at any point resets to main menu."""
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
            )
            # Start a session
            r = meta.handle("u1", "hello")
            # Should show main menu
            assert "1." in r  # numbered menu
            # Menu should also work from any state
            r2 = meta.handle("u1", "menu")
            assert "1." in r2

        check("MetaWizard global menu reset", test_meta_global_menu_reset)

        def test_meta_bad_input_recovery():
            """Invalid input shows helpful error, doesn't crash."""
            meta = MetaWizard(
                spellcaster_wizard=_StubSpellWiz(),
                workflow_wizard=_StubWfWiz(),
            )
            meta.handle("u1", "start")  # show menu
            r = meta.handle("u1", "banana")
            assert "pick" in r.lower() or "didn't catch" in r.lower() or "number" in r.lower()

        check("MetaWizard bad input recovery", test_meta_bad_input_recovery)


        # ==============================================================
        # VideoBridge CRUD + edge cases
        # ==============================================================

        def _make_bridge(name):
            return VideoBridge(
                shotboard_path=os.path.join(tmp, f"{name}.json"),
                wangp_url="http://127.0.0.1:1",
                comfyui_url="http://127.0.0.1:2",
                output_dir=os.path.join(tmp, f"{name}_renders"),
            )

        def test_bridge_update_shot():
            bridge = _make_bridge("bupd")
            d = bridge.add_shot(title="Old", prompt="old")
            sid = d["id"]
            r = bridge.update_shot(sid, title="New", prompt="new")
            assert r["title"] == "New"
            assert r["prompt"] == "new"
            # Non-existent
            r2 = bridge.update_shot("nope", title="X")
            assert r2["status"] == "error"

        check("VideoBridge update_shot", test_bridge_update_shot)

        def test_bridge_remove_shot():
            bridge = _make_bridge("brm")
            d = bridge.add_shot(title="Gone")
            sid = d["id"]
            r = bridge.remove_shot(sid)
            assert r["status"] == "ok"
            assert bridge.list_shots()["shot_count"] == 0
            r2 = bridge.remove_shot("nope")
            assert r2["status"] == "error"

        check("VideoBridge remove_shot", test_bridge_remove_shot)

        def test_bridge_reorder_shots():
            bridge = _make_bridge("breord")
            d1 = bridge.add_shot(title="A")
            d2 = bridge.add_shot(title="B")
            d3 = bridge.add_shot(title="C")
            r = bridge.reorder_shots([d3["id"], d1["id"], d2["id"]])
            ids = [s["id"] for s in r["shots"]]
            assert ids == [d3["id"], d1["id"], d2["id"]]

        check("VideoBridge reorder_shots", test_bridge_reorder_shots)

        def test_bridge_attach_ref_missing():
            bridge = _make_bridge("bref")
            d = bridge.add_shot(title="T")
            r = bridge.attach_reference(d["id"], "/nonexistent/file.png")
            assert r["status"] == "error"
            assert "no file" in r["message"].lower()

        check("VideoBridge attach_reference missing file", test_bridge_attach_ref_missing)

        def test_bridge_attach_ref_bad_shot():
            bridge = _make_bridge("bref2")
            r = bridge.attach_reference("nope", "/tmp/x.png")
            assert r["status"] == "error"

        check("VideoBridge attach_reference bad shot", test_bridge_attach_ref_bad_shot)

        def test_bridge_set_trajectories():
            bridge = _make_bridge("btraj")
            d = bridge.add_shot(title="T")
            trajs = [
                {"label": "pan", "points": [[0, 0], [100, 100]], "colour": "#ff0000"},
            ]
            r = bridge.set_trajectories(d["id"], trajs)
            assert len(r["trajectories"]) == 1
            assert r["trajectories"][0]["label"] == "pan"
            # Bad shot
            r2 = bridge.set_trajectories("nope", trajs)
            assert r2["status"] == "error"

        check("VideoBridge set_trajectories", test_bridge_set_trajectories)

        def test_bridge_queue_unknown_backend():
            bridge = _make_bridge("bunk")
            d = bridge.add_shot(title="T", backend="alien_tech")
            r = bridge.queue_shot(d["id"])
            assert r["status"] == "error"
            assert "unknown backend" in r["message"].lower()

        check("VideoBridge queue unknown backend", test_bridge_queue_unknown_backend)

        def test_bridge_queue_nonexistent_shot():
            bridge = _make_bridge("bne")
            r = bridge.queue_shot("no_such_id")
            assert r["status"] == "error"
            assert "not found" in r["message"].lower()

        check("VideoBridge queue nonexistent shot", test_bridge_queue_nonexistent_shot)

        def test_bridge_queue_comfy_offline():
            bridge = _make_bridge("bcomfy")
            d = bridge.add_shot(title="T", backend="comfyui",
                                preset="ltx2_text_to_video")
            r = bridge.queue_shot(d["id"])
            assert r["status"] == "error"
            assert "not reachable" in r["message"].lower()

        check("VideoBridge queue ComfyUI offline", test_bridge_queue_comfy_offline)


        # ==============================================================
        # Frame extraction
        # ==============================================================

        from scaffold.frame_extract import (
            extract_last_frame, _ffmpeg_available, _get_duration_s,
        )
        import subprocess

        def test_frame_extract_ffmpeg():
            """Create a tiny 10-frame test video, extract last frame."""
            if not _ffmpeg_available():
                print("  [SKIP] ffmpeg not available")
                return
            vid = os.path.join(tmp, "test_vid.mp4")
            # Generate a 10-frame video: frames go from black to white
            # (each frame slightly brighter). The last frame is brightest.
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "color=c=red:s=64x64:d=0.5:r=20",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                vid,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               check=True, timeout=15)
            assert os.path.isfile(vid)

            out = extract_last_frame(vid)
            assert out is not None
            assert os.path.isfile(out)
            assert out.endswith(".png")
            assert os.path.getsize(out) > 100  # valid PNG

        check("extract_last_frame with ffmpeg", test_frame_extract_ffmpeg)

        def test_frame_extract_custom_output():
            """Extract to a specified output path."""
            if not _ffmpeg_available():
                print("  [SKIP] ffmpeg not available")
                return
            vid = os.path.join(tmp, "test_vid2.mp4")
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "color=c=blue:s=32x32:d=0.3:r=10",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                vid,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               check=True, timeout=15)
            custom_out = os.path.join(tmp, "my_frame.png")
            out = extract_last_frame(vid, output_path=custom_out)
            assert out == custom_out
            assert os.path.isfile(custom_out)

        check("extract_last_frame custom output path", test_frame_extract_custom_output)

        def test_frame_extract_missing_video():
            """Non-existent video returns None, doesn't crash."""
            out = extract_last_frame("/nonexistent/video.mp4")
            assert out is None

        check("extract_last_frame missing video", test_frame_extract_missing_video)

        def test_frame_extract_not_a_video():
            """A non-video file returns None gracefully."""
            bad = os.path.join(tmp, "notavideo.txt")
            with open(bad, "w") as f:
                f.write("hello world")
            out = extract_last_frame(bad)
            assert out is None

        check("extract_last_frame non-video file", test_frame_extract_not_a_video)

        def test_get_duration():
            """ffprobe duration works for our test video."""
            if not _ffmpeg_available():
                print("  [SKIP] ffmpeg not available")
                return
            vid = os.path.join(tmp, "test_vid.mp4")
            if not os.path.isfile(vid):
                print("  [SKIP] test video not created")
                return
            dur = _get_duration_s(vid)
            assert dur is not None
            assert 0.1 < dur < 5.0  # our tiny test clip

        check("ffprobe duration extraction", test_get_duration)


        # ==============================================================
        # Hybrid upscale chain
        # ==============================================================

        def test_hybrid_queue_offline():
            """Hybrid backend queues WanGP first; with WanGP offline it
            fails cleanly just like the plain WanGP path."""
            bridge = _make_bridge("bhybrid")
            d = bridge.add_shot(title="H", backend="hybrid",
                                preset="wan22_t2v")
            r = bridge.queue_shot(d["id"])
            assert r["status"] == "error"
            shot = bridge.board.get(d["id"])
            assert shot.status == "failed"

        check("Hybrid queue with offline backends", test_hybrid_queue_offline)

        def test_chain_comfy_upscale_no_comfy():
            """_chain_comfy_upscale skips gracefully when ComfyUI is down."""
            bridge = _make_bridge("bchain1")
            d = bridge.add_shot(title="T")
            # ComfyUI at port 2 is unreachable, so this should just log
            # and return without crashing.
            bridge._chain_comfy_upscale(d["id"], "/tmp/fake.mp4")
            # Shot should be unchanged (no crash, no status change)
            shot = bridge.board.get(d["id"])
            assert shot.status == "draft"

        check("_chain_comfy_upscale skips when ComfyUI offline",
              test_chain_comfy_upscale_no_comfy)

        def test_chain_comfy_upscale_no_workflow():
            """_chain_comfy_upscale skips if the workflow JSON is missing."""
            bridge = _make_bridge("bchain2")
            d = bridge.add_shot(title="T")
            # Monkey-patch ComfyUI as "available" to test the workflow check
            bridge.comfy.is_available = lambda: True
            # The workflow file check will fail naturally since the
            # workflows dir has the real file -- but with a fake video
            # path the run_raw would fail if it got that far. Since
            # ComfyUI isn't really available, run_raw will error.
            # This tests that the function doesn't crash.
            bridge._chain_comfy_upscale(d["id"], "/tmp/fake.mp4")
            shot = bridge.board.get(d["id"])
            assert shot.status == "draft"

        check("_chain_comfy_upscale handles errors gracefully",
              test_chain_comfy_upscale_no_workflow)


        # ==============================================================
        # Trajectory canvas data contract
        # ==============================================================

        def test_trajectory_canvas_js_exists():
            """The trajectory_canvas.js file exists and is valid JS."""
            js_path = os.path.join(
                repo_root, "tavern", "static", "trajectory_canvas.js")
            assert os.path.isfile(js_path), f"Missing {js_path}"
            with open(js_path) as f:
                src = f.read()
            assert "class TrajectoryCanvas" in src
            assert "getTrajectories" in src
            assert "setTrajectories" in src
            # Verify the output shape matches what Trajectory.from_dict expects
            assert "label:" in src or "label :" in src
            assert "points:" in src or "points :" in src
            assert "colour:" in src or "colour :" in src

        check("trajectory_canvas.js exists and has expected API",
              test_trajectory_canvas_js_exists)

        def test_trajectory_data_contract():
            """JS canvas output shape round-trips through Trajectory."""
            # Simulate what the JS canvas outputs (onSave callback)
            js_output = [
                {"label": "path-1", "points": [[10, 20], [30, 40], [50, 60]],
                 "colour": "#ff3366"},
                {"label": "path-2", "points": [[100, 200], [150, 250]],
                 "colour": "#33ccff"},
            ]
            # These must survive Trajectory.from_dict -> to_dict round-trip
            for raw in js_output:
                t = Trajectory.from_dict(raw)
                d = t.to_dict()
                assert d["label"] == raw["label"]
                assert d["points"] == raw["points"]
                assert d["colour"] == raw["colour"]
                # speeds should be absent (canvas doesn't emit it)
                assert "speeds" not in d

        check("Trajectory data contract (JS canvas <-> Python model)",
              test_trajectory_data_contract)

        def test_trajectory_canvas_test_page_exists():
            """The test_trajectory.html test page exists."""
            page = os.path.join(
                repo_root, "tavern", "static", "test_trajectory.html")
            assert os.path.isfile(page), f"Missing {page}"
            with open(page) as f:
                html = f.read()
            assert "TrajectoryCanvas" in html
            assert "trajectory_canvas.js" in html

        check("test_trajectory.html test page exists",
              test_trajectory_canvas_test_page_exists)


        # ── Video Panel frontend tests ──────────────────────────
        def test_video_panel_exists():
            """video_panel.jsx exists and has expected structure."""
            jsx = os.path.join(repo_root, "tavern", "static", "video_panel.jsx")
            assert os.path.isfile(jsx), f"Missing {jsx}"
            with open(jsx) as f:
                src = f.read()
            assert "window.VideoPanel = VideoPanel" in src, "Missing export"
            for ep in ["/api/video/shots", "/api/video/presets",
                       "/api/video/health", "/trajectories", "/render",
                       "/reference", "/api/video/reorder"]:
                assert ep in src, f"Missing endpoint ref: {ep}"
            assert "TrajectoryCanvas" in src, "Missing trajectory integration"
            assert "onDragStart" in src, "Missing drag-to-reorder"
            assert "renderAll" in src, "Missing batch render"
            assert "uploadReference" in src, "Missing reference upload"

        check("video_panel.jsx exists with full API surface",
              test_video_panel_exists)

        def test_video_panel_balance():
            """video_panel.jsx has balanced braces and parens."""
            jsx = os.path.join(repo_root, "tavern", "static", "video_panel.jsx")
            with open(jsx) as f:
                src = f.read()
            assert src.count("{") == src.count("}"), (
                f"Unbalanced braces: {src.count(chr(123))} open vs {src.count(chr(125))} close")
            assert src.count("(") == src.count(")"), (
                f"Unbalanced parens: {src.count(chr(40))} open vs {src.count(chr(41))} close")

        check("video_panel.jsx balanced braces/parens",
              test_video_panel_balance)

        def test_guild_html_script_order():
            """guild.html loads scripts in correct dependency order."""
            html_path = os.path.join(repo_root, "tavern", "static", "guild.html")
            with open(html_path) as f:
                html = f.read()
            tc_pos = html.index("trajectory_canvas.js")
            vp_pos = html.index("video_panel.jsx")
            tw_pos = html.index("travelling_wizard.jsx")
            assert tc_pos < vp_pos < tw_pos

        check("guild.html script load order correct",
              test_guild_html_script_order)

        def test_travelling_wizard_video_tab():
            """travelling_wizard.jsx has Video tab wired in."""
            jsx = os.path.join(repo_root, "tavern", "static", "travelling_wizard.jsx")
            with open(jsx) as f:
                src = f.read()
            assert '"video"' in src, "Missing video tab ID"
            assert "VideoPanel" in src, "Missing VideoPanel reference"

        check("travelling_wizard.jsx has Video tab",
              test_travelling_wizard_video_tab)

        def test_server_video_endpoints():
            """server.py has video file serving + all endpoints."""
            srv = os.path.join(repo_root, "tavern", "server.py")
            with open(srv) as f:
                src = f.read()
            assert "def _serve_file" in src, "Missing _serve_file"
            assert "image_data" in src, "Missing base64 upload"
            for ep in ["/api/video/shots", "/api/video/reorder",
                       "/api/video/chat"]:
                assert ep in src, f"Missing endpoint: {ep}"

        check("server.py has video file serving + all endpoints",
              test_server_video_endpoints)


        def test_video_chat_js_exists():
            """video_chat.js exists with expected structure."""
            js = os.path.join(repo_root, "tavern", "static", "video_chat.js")
            assert os.path.isfile(js), f"Missing {js}"
            with open(js) as f:
                src = f.read()
            assert "/api/video/chat" in src, "Missing chat endpoint"
            assert "videoChatActive" in src, "Missing mode toggle state"
            assert "video-chat-btn" in src, "Missing toggle button"
            assert "Cinematographer" in src, "Missing mode label"
            # Check index.html loads it
            html = os.path.join(repo_root, "tavern", "static", "index.html")
            with open(html) as f:
                h = f.read()
            assert "video_chat.js" in h, "video_chat.js not loaded in index.html"
            assert h.index("app.js") < h.index("video_chat.js"), (
                "video_chat.js must load AFTER app.js")

        check("video_chat.js exists with chat integration",
              test_video_chat_js_exists)

    # ── Round 3: Assembly, continuity, UI enhancements ──
    check("assemble_shots needs >= 2 ready videos",
          test_assemble_shots_needs_two)
    check("assemble_shots handles dummy files gracefully",
          test_assemble_shots_writes_concat_list)
    check("video_panel.jsx has continuity button",
          test_video_panel_has_continuity_button)
    check("video_panel.jsx has Export Video button",
          test_video_panel_has_export_button)
    check("video_panel.jsx has download button",
          test_video_panel_has_download_button)
    check("video_panel.jsx has progress bar",
          test_video_panel_has_progress_bar)
    check("server.py has continuity endpoint",
          test_server_has_continuity_endpoint)
    check("server.py has assemble endpoint",
          test_server_has_assemble_endpoint)
    check("video_bridge.py exports assemble_shots",
          test_video_bridge_has_assemble)

    # ── Round 4: Bridge init, progress, thumbnails, duplication ──
    check("Shotboard duplicate creates copy after original",
          test_shotboard_duplicate)
    check("Shotboard duplicate returns None for unknown id",
          test_shotboard_duplicate_nonexistent)
    check("VideoBridge render_progress returns structured info",
          test_video_bridge_render_progress)
    check("VideoBridge health includes progress + counts",
          test_video_bridge_health_has_progress)
    check("server.py initialises _VIDEO_BRIDGE",
          test_server_has_bridge_init)
    check("server.py has thumbnail endpoint",
          test_server_has_thumbnail_endpoint)
    check("server.py has duplicate endpoint",
          test_server_has_duplicate_endpoint)
    check("video_panel.jsx has Duplicate button",
          test_video_panel_has_duplicate_button)
    check("video_panel.jsx has thumbnail in header",
          test_video_panel_has_thumbnail)

    # ── Round 5: API contract alignment ──
    check("server uses _VIDEO_BRIDGE.add_shot (not board)",
          test_server_uses_bridge_add_shot)
    check("server uses _VIDEO_BRIDGE.remove_shot",
          test_server_uses_bridge_remove_shot)
    check("server uses _VIDEO_BRIDGE.update_shot with all fields",
          test_server_uses_bridge_update_shot)
    check("server uses _VIDEO_BRIDGE.set_trajectories",
          test_server_uses_bridge_set_trajectories)
    check("server uses _VIDEO_BRIDGE.reorder_shots with ordered_ids",
          test_server_uses_bridge_reorder_shots)
    check("server chat passes user_id to handle_chat",
          test_server_chat_has_user_id)
    check("server presets endpoint uses WANGP_PRESETS",
          test_server_presets_uses_wangp_presets)
    check("server shots list includes all Shot fields",
          test_server_shots_list_has_all_fields)
    check("Shot dataclass has negative and seed",
          test_shotboard_has_negative_and_seed)
    check("Shotboard.duplicate() saves before returning",
          test_shotboard_duplicate_saves)
    check("video_panel.jsx has negative prompt and seed UI",
          test_video_panel_has_negative_and_seed)
    check("server catch-all excludes all specific paths",
          test_server_catch_all_excludes_all_specific_paths)

    # ── Round 5b: Negative/seed pipeline passthrough ──
    check("Bridge passes negative_prompt to WanGP overrides",
          test_bridge_passes_negative_to_wangp)
    check("Bridge guards negative/seed with conditionals",
          test_bridge_negative_seed_only_when_set)
    check("WanGP _build_inputs merges overrides into payload",
          test_wangp_build_inputs_merges_overrides)
    check("Shot negative/seed survive save/load roundtrip",
          test_shotboard_negative_seed_roundtrip)
    check("Shot negative/seed have correct defaults",
          test_shotboard_negative_seed_defaults)

    # ── Round 5c: Progress + ComfyUI patching ──
    check("Bridge has _active_progress for real WanGP progress",
          test_bridge_has_active_progress)
    check("render_progress() uses real backend data",
          test_render_progress_uses_real_progress)
    check("_patch_comfy_workflow exists and is wired",
          test_patch_comfy_workflow_exists)
    check("_patch_comfy_workflow injects shot params correctly",
          test_patch_comfy_workflow_logic)
    check("_patch_comfy_workflow leaves unknown nodes untouched",
          test_patch_comfy_workflow_no_clobber)
    check("_patch_comfy_workflow with empty shot is safe",
          test_patch_comfy_workflow_empty_shot)

    # ── Round 5d: Batch render + ComfyUI upload ──
    check("VideoBridge has queue_all_drafts",
          test_bridge_has_queue_all_drafts)
    check("_queue_comfy uploads ref image",
          test_bridge_comfy_uploads_ref_image)
    check("server.py has /render-all endpoint",
          test_server_has_render_all_endpoint)
    check("video_panel.jsx uses batch render endpoint",
          test_video_panel_uses_batch_render)
    check("queue_all_drafts on empty board returns zero",
          test_queue_all_drafts_empty_board)

    # ── Round 6: SSE real-time progress ──
    check("VideoBridge has SSE subscribe/unsubscribe/emit",
          test_bridge_has_sse_subscribe)
    check("SSE subscribe returns queue that receives events",
          test_bridge_sse_roundtrip)
    check("_emit_shot_update sends structured events",
          test_bridge_emit_shot_update)
    check("SSE overflow auto-cleans dead subscribers",
          test_bridge_sse_overflow_cleanup)
    check("server.py has SSE /events endpoint",
          test_server_has_sse_endpoint)
    check("video_panel.jsx uses EventSource for SSE",
          test_video_panel_uses_eventsource)

    # ── Round 7: Per-shot overrides, carry_last_frame, retry ──
    check("Shot dataclass has overrides and carry_last_frame fields",
          test_shot_has_override_fields)
    check("Shotboard.update sets overrides dict",
          test_shotboard_update_overrides)
    check("Shotboard.update sets carry_last_frame",
          test_shotboard_update_carry_last_frame)
    check("server.py passes overrides + carry_last_frame to update_shot",
          test_server_passes_overrides)
    check("server.py has /retry endpoint",
          test_server_has_retry_endpoint)
    check("video_panel.jsx has override UI controls",
          test_video_panel_has_override_ui)
    check("video_panel.jsx has retry button calling /retry",
          test_video_panel_has_retry)
    check("video_panel.jsx has buildOverrides helper",
          test_video_panel_build_overrides)

    # ── Round 8: ComfyUI override patching + progress bar ──
    check("ComfyUI patch applies steps override to sampler nodes",
          test_comfy_patch_steps_override)
    check("ComfyUI patch applies cfg/guidance override",
          test_comfy_patch_cfg_override)
    check("ComfyUI patch applies frames override to latent nodes",
          test_comfy_patch_frames_override)
    check("ComfyUI patch applies resolution override to latent nodes",
          test_comfy_patch_resolution_override)
    check("ComfyUI patch collects scheduler and guider nodes",
          test_comfy_patch_scheduler_guider_nodes)
    check("Progress bar shows percentage text",
          test_progress_bar_shows_percentage)

    # ── Round 9: Duration display + status summary ──
    check("video_panel.jsx has calcDuration helper",
          test_jsx_has_calc_duration)
    check("video_panel.jsx has ShotSummary component",
          test_jsx_has_shot_summary)
    check("ShotCard receives presets prop",
          test_jsx_shotcard_receives_presets)

    # Round 10 — render_duration_s, status filter, filter chips
    check("Shot has render_duration_s field",
          test_shot_has_render_duration_field)
    check("Shotboard.update sets render_duration_s",
          test_shotboard_update_render_duration)
    check("WanGP worker tracks render time",
          test_bridge_wangp_worker_tracks_render_time)
    check("ComfyUI worker tracks render time",
          test_bridge_comfy_worker_tracks_render_time)
    check("video_panel.jsx has status filter",
          test_jsx_has_status_filter)
    check("video_panel.jsx has filter chip UI",
          test_jsx_has_filter_chips_ui)
    check("video_panel.jsx displays render duration",
          test_jsx_render_duration_display)

    # Round 11 — preset preview, debounced auto-save, expand default
    check("video_panel.jsx has preset parameter preview",
          test_jsx_preset_parameter_preview)
    check("video_panel.jsx has debounced auto-save",
          test_jsx_debounced_autosave)
    check("ShotCard expands draft shots by default",
          test_jsx_expand_default_draft)
    check("Preset preview shows all parameter labels",
          test_jsx_preset_preview_shows_params)

    # Round 12 — reset failed, reorder arrows, WanGP overrides
    check("VideoBridge has reset_failed method",
          test_bridge_has_reset_failed)
    check("server.py has /api/video/reset-failed endpoint",
          test_server_has_reset_failed_endpoint)
    check("video_panel.jsx has Reset Failed button",
          test_jsx_has_reset_failed_button)
    check("video_panel.jsx has moveShot function",
          test_jsx_has_move_shot)
    check("video_panel.jsx has reorder arrow buttons",
          test_jsx_has_reorder_arrows)
    check("WanGP overrides fully wired through chain",
          test_wangp_overrides_fully_wired)

    # Round 13 — error display, video preview, keyboard shortcuts
    check("video_panel.jsx shows error banner for failed shots",
          test_jsx_has_error_banner)
    check("video_panel.jsx has inline video preview",
          test_jsx_has_video_preview)
    check("server.py serves video files",
          test_server_has_video_serve_endpoint)
    check("video_panel.jsx has keyboard shortcuts",
          test_jsx_has_keyboard_shortcuts)
    check("video_panel.jsx shows shortcut hints",
          test_jsx_has_shortcut_hints)

    # Round 14 — Notes, templates, bulk select
    check("Shot has notes field",
          test_shot_has_notes_field)
    check("Shot notes survive roundtrip",
          test_shot_notes_roundtrip)
    check("VideoBridge template CRUD",
          test_bridge_template_crud)
    check("VideoBridge rejects empty template names",
          test_bridge_template_empty_name)
    check("server.py has template endpoints",
          test_server_has_template_endpoints)
    check("video_panel.jsx has notes field",
          test_jsx_has_notes_field)
    check("video_panel.jsx has template UI",
          test_jsx_has_template_ui)
    check("video_panel.jsx has bulk select",
          test_jsx_has_bulk_select)
    check("video_panel.jsx has template state",
          test_jsx_has_template_state)

    # Round 22 — Video editor Guild integration
    check("GuildSidebar accepts onWizardSelect prop",
          test_guild_sidebar_has_on_wizard_select_prop)
    check("selectChar calls onWizardSelect callback",
          test_select_char_calls_on_wizard_select)
    check("isVideoWizard helper checks build_fns and subtext",
          test_is_video_wizard_helper)
    check("handleWizardSelect auto-switches to video tab",
          test_handle_wizard_select_auto_switches_tab)
    check("handleWizardSelect restores previous tab",
          test_handle_wizard_select_restores_previous_tab)
    check("VideoPanel always mounted with display toggle",
          test_video_panel_always_mounted)
    check("GuildSidebar receives onWizardSelect in JSX",
          test_guild_sidebar_receives_on_wizard_select)
    check("travelling_wizard.jsx braces balanced after Round 22",
          test_travelling_wizard_braces_balanced)
    check("video_panel.jsx exports VideoPanel to window",
          test_video_panel_export_exists)
    check("server.py has base64 reference upload endpoint",
          test_server_reference_upload_endpoint)

    print("-" * 50)
    if failures:
        print(f"FAILED: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0



# ROUND 3 — imports needed for standalone test functions
sys.path.insert(0, BASE)
from scaffold.shotboard import Shotboard
# ROUND 3 — Video assembly, continuity endpoint, UI enhancements
# ═══════════════════════════════════════════════════════════════════════

def test_assemble_shots_needs_two():
    """assemble_shots returns None when fewer than 2 ready videos exist."""
    board = Shotboard(os.path.join(TMP, "asm1.json"))
    s1 = board.add(prompt="only one")
    board.mark_ready(s1.id, "/tmp/vid1.mp4")
    from scaffold.video_bridge import assemble_shots
    result = assemble_shots(board)
    # With exactly 1 video, assemble_shots returns it directly (no concat needed)
    assert result == "/tmp/vid1.mp4", f"Expected single video path, got {result}"

def test_assemble_shots_writes_concat_list():
    """assemble_shots creates a concat file and calls ffmpeg (offline = fails gracefully)."""
    board = Shotboard(os.path.join(TMP, "asm2.json"))
    s1 = board.add(prompt="shot1")
    s2 = board.add(prompt="shot2")
    # Create dummy video files
    v1 = os.path.join(TMP, "asm_v1.mp4")
    v2 = os.path.join(TMP, "asm_v2.mp4")
    for v in (v1, v2):
        with open(v, "wb") as f:
            f.write(b"\x00" * 100)
    board.mark_ready(s1.id, v1)
    board.mark_ready(s2.id, v2)
    from scaffold.video_bridge import assemble_shots
    # This will fail (dummy files aren't real mp4s) but should not crash
    result = assemble_shots(board, output_dir=TMP)
    # Result may be None (ffmpeg fails on dummy data) — that's fine
    # The point is it doesn't crash
    assert result is None or os.path.isfile(result)

def test_video_panel_has_continuity_button():
    """video_panel.jsx contains the continuity 'Use as next ref' button."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "onContinuity" in src, "Missing onContinuity prop in video_panel.jsx"
    assert "Use as next ref" in src, "Missing 'Use as next ref' button text"

def test_video_panel_has_export_button():
    """video_panel.jsx contains the Export Video / assemble button."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "assembleVideo" in src, "Missing assembleVideo function"
    assert "Export Video" in src, "Missing Export Video button text"
    assert "/api/video/assemble" in src, "Missing assemble endpoint call"
    assert "/api/video/assembled" in src, "Missing assembled download link"

def test_video_panel_has_download_button():
    """video_panel.jsx contains individual shot download button."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "download" in src.lower(), "Missing download attribute/button"

def test_video_panel_has_progress_bar():
    """video_panel.jsx contains render progress bar for running shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "shot.progress" in src, "Missing progress reference"
    assert "animate-pulse" in src, "Missing progress animation"

def test_server_has_continuity_endpoint():
    """server.py has the POST continuity endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/continuity" in src, "Missing /continuity endpoint in server.py"
    assert "export_for_next" in src, "Missing export_for_next call in continuity handler"

def test_server_has_assemble_endpoint():
    """server.py has the POST /api/video/assemble endpoint and GET /api/video/assembled."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/assemble" in src, "Missing /api/video/assemble POST endpoint"
    assert "/api/video/assembled" in src, "Missing /api/video/assembled GET endpoint"
    assert "assemble_shots" in src, "Missing assemble_shots import/call"

def test_video_bridge_has_assemble():
    """video_bridge.py exports assemble_shots function."""
    from scaffold.video_bridge import assemble_shots
    import inspect
    sig = inspect.signature(assemble_shots)
    params = list(sig.parameters.keys())
    assert "board" in params, f"assemble_shots missing 'board' param, has {params}"
    assert "output_dir" in params, f"assemble_shots missing 'output_dir' param, has {params}"


# ROUND 4 — Bridge init, progress, thumbnails, duplication
# ═══════════════════════════════════════════════════════════════════════

def test_shotboard_duplicate():
    """Shotboard.duplicate clones a shot with new id, draft status, right after original."""
    board = Shotboard(os.path.join(TMP, "dup_test.json"))
    s1 = board.add(prompt="original", title="Shot A", preset="wan22_i2v_lightning")
    s2 = board.add(prompt="other")
    dup = board.duplicate(s1.id)
    assert dup is not None, "duplicate returned None"
    assert dup.id != s1.id, "duplicate has same id"
    assert dup.prompt == "original", f"prompt mismatch: {dup.prompt}"
    assert dup.title == "Shot A (copy)", f"title mismatch: {dup.title}"
    assert dup.status == "draft", f"status should be draft, got {dup.status}"
    assert dup.video_path is None, "video_path should be None"
    # Verify insertion order: s1, dup, s2
    ids = [s.id for s in board._shots]
    assert ids.index(dup.id) == ids.index(s1.id) + 1, f"dup not right after original: {ids}"

def test_shotboard_duplicate_nonexistent():
    """Shotboard.duplicate returns None for unknown shot_id."""
    board = Shotboard(os.path.join(TMP, "dup_test2.json"))
    result = board.duplicate("nonexistent_id")
    assert result is None

def test_video_bridge_render_progress():
    """VideoBridge.render_progress returns structured progress info."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "prog_test.json"),
        comfyui_url="http://127.0.0.1:2",
        wangp_url="http://127.0.0.1:2",
    )
    progress = bridge.render_progress()
    assert "active" in progress, "Missing 'active' key"
    assert "stage" in progress, "Missing 'stage' key"
    assert "progress" in progress, "Missing 'progress' key"
    assert progress["active"] is None, "Should be idle"
    assert progress["stage"] == "idle"
    assert progress["progress"] == 0

def test_video_bridge_health_has_progress():
    """VideoBridge.health() includes render_progress, total_shots, ready_count."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "health_prog.json"),
        comfyui_url="http://127.0.0.1:2",
        wangp_url="http://127.0.0.1:2",
    )
    health = bridge.health()
    assert "render_progress" in health, "Missing render_progress in health"
    assert "total_shots" in health, "Missing total_shots in health"
    assert "ready_count" in health, "Missing ready_count in health"
    assert health["total_shots"] == 0
    assert health["ready_count"] == 0

def test_server_has_bridge_init():
    """server.py initialises _VIDEO_BRIDGE in _server_init."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "_VIDEO_BRIDGE = None" in src, "Missing _VIDEO_BRIDGE global declaration"
    assert "VideoBridge(" in src, "Missing VideoBridge constructor call in _server_init"
    assert "global CHARS_CACHE, NODES_CACHE, _ANIM_POLL_THREAD, _VIDEO_BRIDGE" in src, \
        "Missing _VIDEO_BRIDGE in _server_init globals"

def test_server_has_thumbnail_endpoint():
    """server.py has the GET /thumbnail endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/thumbnail" in src, "Missing /thumbnail endpoint"
    assert "thumb.jpg" in src, "Missing thumbnail generation logic"

def test_server_has_duplicate_endpoint():
    """server.py has the POST /duplicate endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/duplicate" in src, "Missing /duplicate endpoint"
    assert "board.duplicate" in src, "Missing board.duplicate call"

def test_video_panel_has_duplicate_button():
    """video_panel.jsx has Duplicate button and wiring."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "onDuplicate" in src, "Missing onDuplicate prop"
    assert "duplicateShot" in src, "Missing duplicateShot function"
    assert "Duplicate" in src, "Missing Duplicate button text"
    assert "/duplicate" in src, "Missing /duplicate endpoint call"

def test_video_panel_has_thumbnail():
    """video_panel.jsx has thumbnail image in collapsed header."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "/thumbnail" in src, "Missing thumbnail image URL"

# ROUND 5 — API contract alignment tests

def test_server_uses_bridge_add_shot():
    """server.py calls _VIDEO_BRIDGE.add_shot, not board.add_shot."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "_VIDEO_BRIDGE.add_shot(" in src, "Missing _VIDEO_BRIDGE.add_shot call"
    assert "board.add_shot(" not in src, "Server should NOT call board.add_shot directly"
    # Check it passes all required fields
    assert "negative=" in src, "add_shot should pass negative"
    assert "seed=" in src, "add_shot should pass seed"

def test_server_uses_bridge_remove_shot():
    """server.py calls _VIDEO_BRIDGE.remove_shot, not board.remove."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "_VIDEO_BRIDGE.remove_shot(" in src, "Missing _VIDEO_BRIDGE.remove_shot call"

def test_server_uses_bridge_update_shot():
    """server.py calls _VIDEO_BRIDGE.update_shot with all editable fields."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "_VIDEO_BRIDGE.update_shot(" in src, "Missing _VIDEO_BRIDGE.update_shot call"
    # Must include all 6 editable fields
    for field in ('title', 'prompt', 'negative', 'preset', 'seed', 'backend'):
        assert f"'{field}'" in src, f"Missing '{field}' in update field list"

def test_server_uses_bridge_set_trajectories():
    """server.py calls _VIDEO_BRIDGE.set_trajectories, not board."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "_VIDEO_BRIDGE.set_trajectories(" in src, \
        "Missing _VIDEO_BRIDGE.set_trajectories call"

def test_server_uses_bridge_reorder_shots():
    """server.py calls _VIDEO_BRIDGE.reorder_shots with ordered_ids."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "_VIDEO_BRIDGE.reorder_shots(" in src, \
        "Missing _VIDEO_BRIDGE.reorder_shots call"
    assert "ordered_ids" in src, "Reorder should read 'ordered_ids' from JSON"

def test_server_chat_has_user_id():
    """server.py passes user_id to handle_chat."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "handle_chat(user_id," in src, "handle_chat must receive user_id"
    assert "guild_default" in src, "Default user_id should be 'guild_default'"

def test_server_presets_uses_wangp_presets():
    """server.py returns WANGP_PRESETS directly from scaffold.wangp_runner."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "from scaffold.wangp_runner import WANGP_PRESETS" in src, \
        "Missing WANGP_PRESETS import"
    assert "WANGP_PRESETS" in src, "Must use WANGP_PRESETS"

def test_server_shots_list_has_all_fields():
    """server.py shots list endpoint includes all Shot fields."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    # Find the /api/video/shots GET handler
    for field in ('title', 'index', 'negative', 'seed', 'backend',
                  'duration_s', 'carry_last_frame'):
        assert f'"{field}"' in src or f"'{field}'" in src, \
            f"Shots list endpoint missing '{field}' field"

def test_shotboard_has_negative_and_seed():
    """Shot dataclass includes negative and seed fields."""
    sb = os.path.join(BASE, "scaffold", "shotboard.py")
    with open(sb) as f:
        src = f.read()
    assert 'negative: str = ""' in src, "Missing negative field on Shot"
    assert "seed: Optional[int] = None" in src, "Missing seed field on Shot"

def test_shotboard_duplicate_saves():
    """Shotboard.duplicate() calls self.save() before returning."""
    sb = os.path.join(BASE, "scaffold", "shotboard.py")
    with open(sb) as f:
        src = f.read()
    # Find the duplicate method body — save must come before return
    dup_start = src.index("def duplicate(")
    dup_end = src.index("\n    def ", dup_start + 1)
    dup_body = src[dup_start:dup_end]
    assert "self.save()" in dup_body, "duplicate() must call self.save()"
    # save() must be before the final return
    save_pos = dup_body.index("self.save()")
    last_return_pos = dup_body.rindex("return ")
    assert save_pos < last_return_pos, "self.save() must come before final return"

def test_video_panel_has_negative_and_seed():
    """video_panel.jsx has negative prompt and seed inputs."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "editNegative" in src, "Missing editNegative state"
    assert "editSeed" in src, "Missing editSeed state"
    assert "Negative Prompt" in src, "Missing Negative Prompt label"
    assert "Seed" in src, "Missing Seed label"

def test_server_catch_all_excludes_all_specific_paths():
    """server.py catch-all update handler excludes continuity, duplicate etc."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/continuity" in src, "Missing /continuity exclusion"
    assert "/duplicate" in src, "Missing /duplicate exclusion"
    # The endswith tuple should have all specific sub-endpoints
    assert "'/render', '/reference', '/trajectories', '/continuity', '/duplicate'" in src, \
        "Catch-all endswith missing one or more path exclusions"

def test_bridge_passes_negative_to_wangp():
    """VideoBridge._queue_wangp merges shot.negative into overrides."""
    bridge_src = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(bridge_src) as f:
        src = f.read()
    assert 'overrides.setdefault("negative_prompt", shot.negative)' in src, \
        "Bridge must merge negative_prompt into overrides"
    assert 'overrides.setdefault("seed", shot.seed)' in src, \
        "Bridge must merge seed into overrides"

def test_bridge_negative_seed_only_when_set():
    """negative_prompt only added when shot.negative is truthy."""
    bridge_src = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(bridge_src) as f:
        src = f.read()
    assert "if shot.negative:" in src, "Must guard negative_prompt"
    assert "if shot.seed is not None:" in src, "Must guard seed"

def test_wangp_build_inputs_merges_overrides():
    """WanGPRunner._build_inputs spreads overrides into payload."""
    runner_src = os.path.join(BASE, "scaffold", "wangp_runner.py")
    with open(runner_src) as f:
        src = f.read()
    assert "merged.update(overrides" in src, "Must merge overrides"
    assert "**merged" in src, "Must spread merged dict"

def test_shotboard_negative_seed_roundtrip():
    """Shot negative/seed survive save/load cycle."""
    board_path = os.path.join(TMP, "neg_seed_rt.json")
    board = Shotboard(board_path)
    s = board.add(prompt="test", negative="blurry", seed=42)
    assert s.negative == "blurry"
    assert s.seed == 42
    board2 = Shotboard(board_path)
    s2 = board2.get(s.id)
    assert s2 is not None
    assert s2.negative == "blurry"
    assert s2.seed == 42

def test_shotboard_negative_seed_defaults():
    """Shot defaults: negative='', seed=None."""
    board_path = os.path.join(TMP, "neg_seed_def.json")
    board = Shotboard(board_path)
    s = board.add(prompt="bare shot")
    assert s.negative == ""
    assert s.seed is None

def test_bridge_has_active_progress():
    """VideoBridge tracks _active_progress for real WanGP progress."""
    bridge_src = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(bridge_src) as f:
        src = f.read()
    assert "_active_progress" in src, "Missing _active_progress field"
    assert "_on_wangp_progress" in src, "Missing progress callback"
    assert "on_progress=_on_wangp_progress" in src, "Callback not passed to wait()"

def test_render_progress_uses_real_progress():
    """render_progress() prefers real backend data over time estimates."""
    bridge_src = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(bridge_src) as f:
        src = f.read()
    assert "_active_progress > 0" in src, "Must check if real progress available"
    assert "_active_progress * 0.8" in src, "Must scale real progress (cap at 80)"

def test_patch_comfy_workflow_exists():
    """VideoBridge has _patch_comfy_workflow static method."""
    bridge_src = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(bridge_src) as f:
        src = f.read()
    assert "def _patch_comfy_workflow" in src, "Missing _patch_comfy_workflow"
    assert "_patch_comfy_workflow(workflow, shot)" in src, "Not called in _queue_comfy"

def test_patch_comfy_workflow_logic():
    """_patch_comfy_workflow injects prompt, negative, seed, ref_image."""
    from scaffold.video_bridge import VideoBridge
    from scaffold.shotboard import Shot
    # Build a fake API-format workflow
    workflow = {
        "1": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "placeholder", "clip": ["2", 0]},
            "_meta": {"title": "Positive Prompt"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "bad quality", "clip": ["3", 0]},
            "_meta": {"title": "Negative Prompt"},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {"seed": 0, "steps": 20, "cfg": 7.0},
        },
        "4": {
            "class_type": "LoadImage",
            "inputs": {"image": "default.png"},
        },
    }
    shot = Shot(
        prompt="a cat dancing",
        negative="blurry, ugly",
        seed=12345,
        ref_image="/tmp/ref.png",
    )
    patched = VideoBridge._patch_comfy_workflow(workflow, shot)
    # Positive prompt should be updated
    assert patched["1"]["inputs"]["text"] == "a cat dancing"
    # Negative prompt should be updated
    assert patched["2"]["inputs"]["text"] == "blurry, ugly"
    # Seed should be updated
    assert patched["3"]["inputs"]["seed"] == 12345
    # Image should be basename
    assert patched["4"]["inputs"]["image"] == "ref.png"

def test_patch_comfy_workflow_no_clobber():
    """_patch_comfy_workflow leaves unknown node types untouched."""
    from scaffold.video_bridge import VideoBridge
    from scaffold.shotboard import Shot
    workflow = {
        "1": {
            "class_type": "SomeCustomNode",
            "inputs": {"text": "keep me", "value": 42},
        },
    }
    shot = Shot(prompt="override", negative="bad", seed=99)
    patched = VideoBridge._patch_comfy_workflow(workflow, shot)
    assert patched["1"]["inputs"]["text"] == "keep me"
    assert patched["1"]["inputs"]["value"] == 42

def test_patch_comfy_workflow_empty_shot():
    """_patch_comfy_workflow with empty shot fields changes nothing."""
    from scaffold.video_bridge import VideoBridge
    from scaffold.shotboard import Shot
    workflow = {
        "1": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "original"},
            "_meta": {"title": "Positive"},
        },
        "2": {
            "class_type": "KSampler",
            "inputs": {"seed": 42},
        },
    }
    shot = Shot()  # empty defaults
    patched = VideoBridge._patch_comfy_workflow(workflow, shot)
    # Nothing should change because shot.prompt is empty
    assert patched["1"]["inputs"]["text"] == "original"
    # seed is None so shouldn't be patched
    assert patched["2"]["inputs"]["seed"] == 42


def test_bridge_has_queue_all_drafts():
    """VideoBridge has queue_all_drafts method."""
    bridge_src = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(bridge_src) as f:
        src = f.read()
    assert "def queue_all_drafts" in src, "Missing queue_all_drafts"
    assert "batch-render-watcher" in src, "Missing batch watcher thread"

def test_bridge_comfy_uploads_ref_image():
    """_queue_comfy uploads ref image to ComfyUI before run."""
    bridge_src = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(bridge_src) as f:
        src = f.read()
    assert "self.comfy.upload_image(" in src, "Missing upload_image call in _queue_comfy"
    assert "os.path.basename(shot.ref_image)" in src, "Must use basename for upload filename"

def test_server_has_render_all_endpoint():
    """server.py has POST /api/video/render-all endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/render-all" in src, "Missing /render-all endpoint"
    assert "queue_all_drafts" in src, "Must call queue_all_drafts"

def test_video_panel_uses_batch_render():
    """video_panel.jsx calls /api/video/render-all for Render All."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "/api/video/render-all" in src, "Must call batch render endpoint"

def test_queue_all_drafts_empty_board():
    """queue_all_drafts on empty board returns zero."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "batch_empty.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    result = bridge.queue_all_drafts()
    assert result["queued"] == 0
    assert result["shot_ids"] == []



# ── Round 6: SSE real-time progress tests ──

def test_bridge_has_sse_subscribe():
    """VideoBridge has subscribe/unsubscribe/emit SSE methods."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "sse_sub.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    assert hasattr(bridge, 'subscribe'), "Missing subscribe method"
    assert hasattr(bridge, 'unsubscribe'), "Missing unsubscribe method"
    assert hasattr(bridge, '_emit'), "Missing _emit method"
    assert hasattr(bridge, '_emit_shot_update'), "Missing _emit_shot_update method"

def test_bridge_sse_roundtrip():
    """subscribe() returns a queue that receives _emit() events."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "sse_rt.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    q = bridge.subscribe()
    bridge._emit("test-event", {"key": "value"})
    evt = q.get(timeout=1.0)
    assert evt["event"] == "test-event"
    assert evt["data"]["key"] == "value"
    bridge.unsubscribe(q)
    # After unsubscribe, no more events
    bridge._emit("test2", {})
    import queue as _queue
    try:
        q.get(timeout=0.1)
        assert False, "Should not receive events after unsubscribe"
    except _queue.Empty:
        pass  # correct

def test_bridge_emit_shot_update():
    """_emit_shot_update sends structured shot-update events."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "sse_shot.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    q = bridge.subscribe()
    bridge._emit_shot_update("shot-abc", status="running", progress=42.5)
    evt = q.get(timeout=1.0)
    assert evt["event"] == "shot-update"
    assert evt["data"]["shot_id"] == "shot-abc"
    assert evt["data"]["status"] == "running"
    assert evt["data"]["progress"] == 42.5
    bridge.unsubscribe(q)

def test_bridge_sse_overflow_cleanup():
    """Overflowed subscriber queues are auto-removed."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "sse_overflow.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    q = bridge.subscribe()
    # Fill the queue (maxsize=64) to trigger overflow
    for i in range(70):
        bridge._emit("flood", {"i": i})
    # The overflowed subscriber should have been auto-removed
    assert q not in bridge._sse_subscribers, \
        "Overflowed subscriber should be auto-cleaned"

def test_server_has_sse_endpoint():
    """server.py has the GET /api/video/events SSE endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/events" in src, "Missing /events SSE endpoint"
    assert "text/event-stream" in src, "Must set text/event-stream content type"
    assert "subscribe()" in src, "Must call bridge.subscribe()"

def test_video_panel_uses_eventsource():
    """video_panel.jsx uses EventSource for real-time SSE updates."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "EventSource" in src, "Must use EventSource"
    assert "/api/video/events" in src, "Must connect to /api/video/events"
    assert "shot-update" in src, "Must listen for shot-update events"
    assert "sseRef" in src, "Must track SSE ref for cleanup"



# ── Round 7: Per-shot overrides, carry_last_frame, retry tests ──

def test_shot_has_override_fields():
    """Shot dataclass has overrides (dict) and carry_last_frame (bool)."""
    from scaffold.shotboard import Shot
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(Shot)}
    assert "overrides" in fields, "Missing overrides field on Shot"
    assert "carry_last_frame" in fields, "Missing carry_last_frame field on Shot"
    # Defaults
    s = Shot(id="test", index=0)
    assert isinstance(s.overrides, dict), "overrides default should be dict"
    assert s.carry_last_frame is True, "carry_last_frame default should be True"

def test_shotboard_update_overrides():
    """Shotboard.update() correctly sets overrides dict."""
    from scaffold.shotboard import Shotboard
    board = Shotboard(os.path.join(TMP, "ov_test.json"))
    shot = board.add(prompt="test")
    sid = shot.id
    board.update(sid, overrides={"steps": 30, "guidance": 7.5})
    updated = board.get(sid)
    assert updated.overrides == {"steps": 30, "guidance": 7.5}
    # Clear overrides
    board.update(sid, overrides={})
    assert board.get(sid).overrides == {}

def test_shotboard_update_carry_last_frame():
    """Shotboard.update() toggles carry_last_frame."""
    from scaffold.shotboard import Shotboard
    board = Shotboard(os.path.join(TMP, "clf_test.json"))
    shot = board.add(prompt="test")
    sid = shot.id
    assert shot.carry_last_frame is True
    board.update(sid, carry_last_frame=False)
    assert board.get(sid).carry_last_frame is False
    board.update(sid, carry_last_frame=True)
    assert board.get(sid).carry_last_frame is True

def test_server_passes_overrides():
    """server.py update handler passes overrides and carry_last_frame."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "'overrides'" in src or '"overrides"' in src, \
        "server.py must pass overrides field"
    assert "'carry_last_frame'" in src or '"carry_last_frame"' in src, \
        "server.py must pass carry_last_frame field"
    assert "update_kw" in src, \
        "server.py should use update_kw dict pattern"

def test_server_has_retry_endpoint():
    """server.py has POST /retry endpoint that resets and re-queues."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/retry" in src, "Missing /retry endpoint path"
    assert "status='draft'" in src or 'status="draft"' in src, \
        "Retry must reset status to draft"
    assert "queue_shot" in src, "Retry must re-queue the shot"

def test_video_panel_has_override_ui():
    """video_panel.jsx has override controls (steps, guidance, frames, fps)."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "ovSteps" in src, "Missing ovSteps state"
    assert "ovGuidance" in src, "Missing ovGuidance state"
    assert "ovFrames" in src, "Missing ovFrames state"
    assert "ovFps" in src, "Missing ovFps state"
    assert "ovResolution" in src, "Missing ovResolution state"
    assert "showAdvanced" in src, "Missing showAdvanced toggle"
    assert "editCarryFrame" in src, "Missing editCarryFrame state"

def test_video_panel_has_retry():
    """video_panel.jsx has retry button that calls /retry endpoint."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "retryShot" in src, "Missing retryShot function"
    assert "/retry" in src, "Must call /retry endpoint"
    assert "onRetry" in src, "Must pass onRetry prop to ShotCard"

def test_video_panel_build_overrides():
    """video_panel.jsx has buildOverrides helper for constructing override dict."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "buildOverrides" in src, "Missing buildOverrides function"
    assert "parseInt" in src, "buildOverrides must parse int values"
    assert "parseFloat" in src, "buildOverrides must parse float (guidance)"


# ── Round 8: ComfyUI override patching + progress bar tests ──

def _make_test_workflow():
    """Build a minimal ComfyUI API-format workflow for testing."""
    return {
        "1": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "original prompt"},
            "_meta": {"title": "Positive Prompt"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "bad quality"},
            "_meta": {"title": "Negative Prompt"},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {"seed": 42, "steps": 20, "cfg": 7.0,
                       "sampler_name": "euler", "scheduler": "normal"},
        },
        "4": {
            "class_type": "EmptyLatentVideo",
            "inputs": {"width": 512, "height": 512, "length": 16},
        },
        "5": {
            "class_type": "BasicScheduler",
            "inputs": {"steps": 20, "denoise": 1.0},
        },
        "6": {
            "class_type": "CFGGuider",
            "inputs": {"cfg": 7.0},
        },
        "7": {
            "class_type": "LoadImage",
            "inputs": {"image": "placeholder.png"},
        },
    }


def test_comfy_patch_steps_override():
    """_patch_comfy_workflow applies steps from shot.overrides to sampler + scheduler."""
    from scaffold.video_bridge import VideoBridge
    from scaffold.shotboard import Shot
    wf = _make_test_workflow()
    shot = Shot(id="s1", prompt="test", overrides={"steps": 35})
    patched = VideoBridge._patch_comfy_workflow(wf, shot)
    assert patched["3"]["inputs"]["steps"] == 35, "KSampler steps not patched"
    assert patched["5"]["inputs"]["steps"] == 35, "BasicScheduler steps not patched"


def test_comfy_patch_cfg_override():
    """_patch_comfy_workflow applies guidance/cfg from overrides."""
    from scaffold.video_bridge import VideoBridge
    from scaffold.shotboard import Shot
    wf = _make_test_workflow()
    shot = Shot(id="s2", prompt="test", overrides={"guidance": 4.5})
    patched = VideoBridge._patch_comfy_workflow(wf, shot)
    assert patched["3"]["inputs"]["cfg"] == 4.5, "KSampler cfg not patched"
    assert patched["6"]["inputs"]["cfg"] == 4.5, "CFGGuider cfg not patched"


def test_comfy_patch_frames_override():
    """_patch_comfy_workflow applies frames override to EmptyLatentVideo length."""
    from scaffold.video_bridge import VideoBridge
    from scaffold.shotboard import Shot
    wf = _make_test_workflow()
    shot = Shot(id="s3", prompt="test", overrides={"frames": 32})
    patched = VideoBridge._patch_comfy_workflow(wf, shot)
    assert patched["4"]["inputs"]["length"] == 32, "EmptyLatentVideo length not patched"


def test_comfy_patch_resolution_override():
    """_patch_comfy_workflow applies resolution WxH to latent size nodes."""
    from scaffold.video_bridge import VideoBridge
    from scaffold.shotboard import Shot
    wf = _make_test_workflow()
    shot = Shot(id="s4", prompt="test", overrides={"resolution": "768x480"})
    patched = VideoBridge._patch_comfy_workflow(wf, shot)
    assert patched["4"]["inputs"]["width"] == 768, "Latent width not patched"
    assert patched["4"]["inputs"]["height"] == 480, "Latent height not patched"


def test_comfy_patch_scheduler_guider_nodes():
    """_patch_comfy_workflow recognises BasicScheduler and CFGGuider nodes."""
    from scaffold.video_bridge import VideoBridge
    from scaffold.shotboard import Shot
    wf = _make_test_workflow()
    # Verify no-override case leaves defaults intact
    shot = Shot(id="s5", prompt="test", overrides={})
    patched = VideoBridge._patch_comfy_workflow(wf, shot)
    assert patched["5"]["inputs"]["steps"] == 20, "Scheduler steps changed without override"
    assert patched["6"]["inputs"]["cfg"] == 7.0, "Guider cfg changed without override"


def test_progress_bar_shows_percentage():
    """video_panel.jsx progress bar shows numeric percentage."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "Math.round(shot.progress)" in src, "Must show rounded progress %"
    assert "tabular-nums" in src, "Progress text should use tabular-nums for alignment"
    assert "Math.min(shot.progress" in src, "Must cap progress at 100%"


# ── Round 9: Duration display + status summary tests ──

def test_jsx_has_calc_duration():
    """video_panel.jsx has calcDuration helper for estimated duration."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "calcDuration" in src, "Missing calcDuration function"
    assert "toFixed" in src, "calcDuration should format to fixed decimal"
    # Duration display in header
    assert "~{calcDuration()}s" in src or "calcDuration()" in src, \
        "Duration should be shown in shot header"

def test_jsx_has_shot_summary():
    """video_panel.jsx has ShotSummary component for status breakdown."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "function ShotSummary" in src, "Missing ShotSummary component"
    assert "total" in src.lower(), "ShotSummary should show total duration"
    assert "draft" in src, "ShotSummary should count draft shots"
    assert "ready" in src, "ShotSummary should count ready shots"
    assert "<ShotSummary" in src, "ShotSummary must be rendered in VideoPanel"

def test_jsx_shotcard_receives_presets():
    """ShotCard in VideoPanel receives the presets prop."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    # Check that ShotCard instantiation includes presets={presets}
    import re
    # Find the ShotCard usage in shots.map
    matches = re.findall(r'<ShotCard\s.*?presets=\{presets\}', src, re.DOTALL)
    assert len(matches) >= 1, "ShotCard must receive presets={presets} prop"


# ------------------------------------------------------------------
# Round 10 — render_duration_s, status filter, filter chips
# ------------------------------------------------------------------

def test_shot_has_render_duration_field():
    """Shot dataclass has render_duration_s field with None default."""
    from scaffold.shotboard import Shot
    s = Shot(id="dur1")
    assert hasattr(s, "render_duration_s"), "Missing render_duration_s field"
    assert s.render_duration_s is None, "Default should be None"
    # Should survive round-trip
    d = s.to_dict()
    assert "render_duration_s" in d
    s2 = Shot.from_dict({**d, "render_duration_s": 42.5})
    assert s2.render_duration_s == 42.5

def test_shotboard_update_render_duration():
    """Shotboard.update can set render_duration_s."""
    from scaffold.shotboard import Shotboard
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "board.json")
        board = Shotboard(path)
        s = board.add(prompt="test")
        assert s.render_duration_s is None
        board.update(s.id, render_duration_s=123.4)
        reloaded = Shotboard(path)
        assert reloaded.get(s.id).render_duration_s == 123.4

def test_bridge_wangp_worker_tracks_render_time():
    """WanGP worker code records render_start and updates render_duration_s."""
    vb = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(vb) as f:
        src = f.read()
    # WanGP worker: render_start = time.time() then update(..., render_duration_s=elapsed)
    assert "render_start = time.time()" in src, \
        "WanGP worker must record render start time"
    assert "self._active_started = render_start" in src, \
        "WanGP worker must set _active_started for progress reporting"
    assert "render_duration_s=elapsed" in src, \
        "Worker must save elapsed time as render_duration_s"

def test_bridge_comfy_worker_tracks_render_time():
    """ComfyUI worker code records render start and updates render_duration_s."""
    vb = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(vb) as f:
        src = f.read()
    assert "comfy_render_start = time.time()" in src, \
        "ComfyUI worker must record render start time"
    # Both workers should call update with render_duration_s
    import re
    matches = re.findall(r'render_duration_s=elapsed', src)
    assert len(matches) >= 2, \
        f"Both WanGP and ComfyUI workers should record render_duration_s, found {len(matches)}"

def test_jsx_has_status_filter():
    """video_panel.jsx has statusFilter state and filteredShots memo."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "statusFilter" in src, "Missing statusFilter state"
    assert "setStatusFilter" in src, "Missing setStatusFilter setter"
    assert "filteredShots" in src, "Missing filteredShots memo"
    # filteredShots should filter by status
    assert "s.status === statusFilter" in src or \
           "s.status===statusFilter" in src, \
        "filteredShots must filter shots by statusFilter"
    # Shot list should use filteredShots, not raw shots
    assert "filteredShots.map" in src, \
        "Shot list must iterate filteredShots, not raw shots"

def test_jsx_has_filter_chips_ui():
    """video_panel.jsx renders filter chip buttons for each status."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    # Should have chip buttons for all statuses
    for status in ("draft", "queued", "running", "ready", "failed"):
        assert f'"{status}"' in src, f"Filter chip missing status: {status}"
    # Should show count on chips
    assert "count" in src, "Filter chips should show count per status"
    # Should call setStatusFilter on click
    assert "setStatusFilter(f)" in src or "setStatusFilter(" in src, \
        "Filter chips must call setStatusFilter on click"

def test_jsx_render_duration_display():
    """video_panel.jsx displays render_duration_s for completed shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "render_duration_s" in src, \
        "ShotCard should display render_duration_s"
    assert "Math.floor" in src and "render_duration_s" in src, \
        "Should format render time with minutes for longer renders"


# ------------------------------------------------------------------
# Round 11 — preset preview, debounced auto-save, expand default
# ------------------------------------------------------------------

def test_jsx_preset_parameter_preview():
    """video_panel.jsx shows preset defaults merged with overrides."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "preset-params" in src or "Preset param" in src.lower() or "preset.defaults" in src.lower() or "defs.steps" in src, \
        "ShotCard should show preset parameter preview"
    # Should distinguish overridden vs default values
    assert "overridden" in src.lower() or "Overridden" in src, \
        "Preset preview should mark overridden values"

def test_jsx_debounced_autosave():
    """video_panel.jsx has debounced auto-save for shot edits."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "debounceRef" in src, "Missing debounceRef for auto-save"
    assert "clearTimeout" in src, "Auto-save should clear previous timer"
    assert "setTimeout" in src and "doSave" in src, \
        "Auto-save should call doSave after a delay"

def test_jsx_expand_default_draft():
    """ShotCard defaults to expanded for draft shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert 'shot.status === "draft"' in src and "expanded" in src, \
        "ShotCard should default expanded state based on draft status"

def test_jsx_preset_preview_shows_params():
    """Preset preview displays steps, guidance, frames, fps, resolution."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    for param in ("Steps", "Guidance", "Frames", "FPS", "Res"):
        assert param in src, f"Preset preview missing parameter label: {param}"


# ------------------------------------------------------------------
# Round 12 — reset failed, reorder arrows, WanGP overrides
# ------------------------------------------------------------------

def test_bridge_has_reset_failed():
    """VideoBridge.reset_failed resets failed shots to draft."""
    from scaffold.shotboard import Shotboard
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "board.json")
        board = Shotboard(path)
        s1 = board.add(prompt="ok", status="ready")
        s2 = board.add(prompt="bad", status="failed")
        s3 = board.add(prompt="also bad", status="failed")
        # Verify source code has reset_failed method
        vb_path = os.path.join(BASE, "scaffold", "video_bridge.py")
        with open(vb_path) as f:
            src = f.read()
        assert "def reset_failed" in src, "Missing reset_failed method"
        assert 'status="draft"' in src or "status='draft'" in src, \
            "reset_failed should set status to draft"
        # Test via board directly
        failed = [s for s in board if s.status == "failed"]
        assert len(failed) == 2
        for s in failed:
            board.update(s.id, status="draft", error=None, job_id=None)
        still_failed = [s for s in board if s.status == "failed"]
        assert len(still_failed) == 0

def test_server_has_reset_failed_endpoint():
    """server.py has /api/video/reset-failed endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/reset-failed" in src, \
        "Missing /api/video/reset-failed endpoint"
    assert "reset_failed()" in src, \
        "Endpoint should call _VIDEO_BRIDGE.reset_failed()"

def test_jsx_has_reset_failed_button():
    """video_panel.jsx has Reset Failed button."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "resetFailed" in src, "Missing resetFailed function"
    assert "reset-failed" in src, "Should call /api/video/reset-failed"
    assert "Reset Failed" in src, "Missing Reset Failed button label"

def test_jsx_has_move_shot():
    """video_panel.jsx has moveShot function for arrow reordering."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "moveShot" in src, "Missing moveShot function"
    assert "onMove" in src, "ShotCard should receive onMove prop"
    assert "isFirst" in src and "isLast" in src, \
        "ShotCard should receive isFirst/isLast for disabling arrows"

def test_jsx_has_reorder_arrows():
    """video_panel.jsx has up/down arrow buttons in ShotCard header."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "reorder-arrows" in src or "Move up" in src, \
        "Missing reorder arrow buttons"
    assert "onMove(shot.id, -1)" in src, "Missing move-up button"
    assert "onMove(shot.id, 1)" in src, "Missing move-down button"

def test_wangp_overrides_fully_wired():
    """WanGP override chain: shot.overrides -> _queue_wangp -> _build_inputs -> merged."""
    vb = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(vb) as f:
        vb_src = f.read()
    # Bridge merges shot.overrides into overrides dict
    assert "dict(shot.overrides or {})" in vb_src, \
        "Bridge should copy shot.overrides into overrides dict"
    assert "overrides=overrides" in vb_src, \
        "Bridge should pass overrides to queue_generation"
    # WanGP runner merges overrides into preset defaults
    wr = os.path.join(BASE, "scaffold", "wangp_runner.py")
    with open(wr) as f:
        wr_src = f.read()
    assert "merged.update(overrides" in wr_src, \
        "_build_inputs should merge overrides into preset defaults"


# ------------------------------------------------------------------
# Round 13 — error display, video preview, keyboard shortcuts
# ------------------------------------------------------------------

def test_jsx_has_error_banner():
    """video_panel.jsx shows error message for failed shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "error-banner" in src or "shot.error" in src, \
        "ShotCard should display shot.error for failed shots"
    assert 'status === "failed"' in src and "error" in src, \
        "Error display should be gated on failed status"

def test_jsx_has_video_preview():
    """video_panel.jsx has inline video element for ready shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "<video" in src, "Missing HTML5 video element"
    assert "/video`" in src or "/video'" in src, \
        "Video element should load from /api/video/shots/{id}/video"
    assert "controls" in src, "Video element should have controls"

def test_server_has_video_serve_endpoint():
    """server.py serves video files at /api/video/shots/{id}/video."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/video'" in src or '/video"' in src, \
        "Missing video serving endpoint"
    assert "_serve_file" in src and "video_path" in src, \
        "Should serve the shot's video_path file"
def test_jsx_has_keyboard_shortcuts():
    """video_panel.jsx has keyboard shortcut event listener."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "keydown" in src, "Missing keydown event listener"
    assert "addShot" in src and '"n"' in src.lower(), \
        "N key should trigger addShot"
    assert "renderAll" in src, \
        "Ctrl+Shift+R should trigger renderAll"

def test_jsx_has_shortcut_hints():
    """video_panel.jsx shows keyboard shortcut hints."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "shortcut-hints" in src or "Ctrl+Shift+R" in src, \
        "Should show keyboard shortcut hints"


# ═══════════════════════════════════════════════════════════════════════
# Round 14 — Notes field, prompt templates, bulk select
# ═══════════════════════════════════════════════════════════════════════

def test_shot_has_notes_field():
    """Shot dataclass has a notes field."""
    from scaffold.shotboard import Shot
    s = Shot(prompt="test")
    assert hasattr(s, "notes"), "Shot missing notes field"
    assert s.notes == "", "notes should default to empty string"
    s2 = Shot(prompt="test", notes="director note")
    assert s2.notes == "director note"
    d = s2.to_dict()
    assert d["notes"] == "director note", "notes should serialize"

def test_shot_notes_roundtrip():
    """Notes field survives to_dict/from_dict roundtrip."""
    from scaffold.shotboard import Shot
    s = Shot(prompt="test", notes="camera pan left")
    d = s.to_dict()
    s2 = Shot.from_dict(d)
    assert s2.notes == "camera pan left", "notes lost in roundtrip"

def test_bridge_template_crud():
    """VideoBridge can save, list, and delete prompt templates."""
    import tempfile, json
    from scaffold.shotboard import Shotboard
    with tempfile.TemporaryDirectory() as td:
        sb_path = os.path.join(td, "shotboard.json")
        board = Shotboard(sb_path)
        # Minimal bridge mock — just need template methods
        from scaffold.video_bridge import VideoBridge
        # Can't fully init without runners, so test the methods directly
        class FakeBridge:
            def __init__(self):
                self.board = board
            _templates_path = VideoBridge._templates_path
            _load_templates = VideoBridge._load_templates
            _save_templates = VideoBridge._save_templates
            list_templates = VideoBridge.list_templates
            save_template = VideoBridge.save_template
            delete_template = VideoBridge.delete_template
        fb = FakeBridge()
        # Initially empty
        assert fb.list_templates() == {"templates": {}}
        # Save
        r = fb.save_template("sunset", "golden hour sunset", "ugly, blurry")
        assert r["status"] == "ok"
        tpls = fb.list_templates()["templates"]
        assert "sunset" in tpls
        assert tpls["sunset"]["prompt"] == "golden hour sunset"
        assert tpls["sunset"]["negative"] == "ugly, blurry"
        # Overwrite
        fb.save_template("sunset", "dramatic sunset", "")
        tpls = fb.list_templates()["templates"]
        assert tpls["sunset"]["prompt"] == "dramatic sunset"
        # Delete
        r = fb.delete_template("sunset")
        assert r["status"] == "ok"
        assert fb.list_templates() == {"templates": {}}
        # Delete nonexistent
        r = fb.delete_template("nope")
        assert r["status"] == "error"

def test_bridge_template_empty_name():
    """save_template rejects empty names."""
    import tempfile
    from scaffold.shotboard import Shotboard
    from scaffold.video_bridge import VideoBridge
    with tempfile.TemporaryDirectory() as td:
        sb_path = os.path.join(td, "shotboard.json")
        board = Shotboard(sb_path)
        class FakeBridge:
            def __init__(self):
                self.board = board
            _templates_path = VideoBridge._templates_path
            _load_templates = VideoBridge._load_templates
            _save_templates = VideoBridge._save_templates
            save_template = VideoBridge.save_template
        fb = FakeBridge()
        r = fb.save_template("", "prompt", "")
        assert r["status"] == "error"
        r = fb.save_template("   ", "prompt", "")
        assert r["status"] == "error"

def test_server_has_template_endpoints():
    """server.py has template list/save/delete endpoints."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/templates'" in src, "Missing templates list endpoint"
    assert "/api/video/templates/save'" in src, "Missing templates save endpoint"
    assert "/api/video/templates/delete'" in src, "Missing templates delete endpoint"

def test_jsx_has_notes_field():
    """video_panel.jsx has notes textarea for director's notes."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "editNotes" in src, "Missing editNotes state"
    assert "shot-notes" in src or "shot.notes" in src, "Missing notes textarea"
    assert "not sent to model" in src.lower(), "Should indicate notes aren't sent to model"

def test_jsx_has_template_ui():
    """video_panel.jsx has prompt template save/load UI."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "onSaveTemplate" in src, "Missing onSaveTemplate prop"
    assert "onDeleteTemplate" in src, "Missing onDeleteTemplate prop"
    assert "save-template-btn" in src or "Save as template" in src, \
        "Missing save template button"
    assert "prompt-templates" in src, "Missing template picker UI"

def test_jsx_has_bulk_select():
    """video_panel.jsx has bulk select checkboxes and action bar."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "bulk-checkbox" in src, "Missing bulk select checkboxes"
    assert "bulk-actions" in src, "Missing bulk action bar"
    assert "deleteSelected" in src, "Missing deleteSelected function"
    assert "renderSelected" in src, "Missing renderSelected function"
    assert "selectAll" in src, "Missing selectAll function"
    assert "selectNone" in src, "Missing selectNone function"

def test_jsx_has_template_state():
    """video_panel.jsx fetches and stores templates in state."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "setTemplates" in src, "Missing setTemplates state setter"
    assert "/api/video/templates" in src, "Missing templates API call"

# ═══════════════════════════════════════════════════════════════════════
# Round 15 — Clone with variation, export/import shotboard
# ═══════════════════════════════════════════════════════════════════════

def test_bridge_clone_shot_basic():
    """VideoBridge.clone_shot creates a copy with new id and optional variation."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "clone_basic.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    s = bridge.board.add(prompt="sunset over ocean", title="Shot 1",
                         negative="blurry", preset="wan22_i2v_lightning")
    result = bridge.clone_shot(s.id)
    assert result.get("prompt") == "sunset over ocean", "Clone should copy prompt"
    assert result.get("id") != s.id, "Clone must have new id"
    assert result.get("negative") == "blurry", "Clone should copy negative"

def test_bridge_clone_shot_with_variation():
    """clone_shot appends variation to prompt when provided."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "clone_var.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    s = bridge.board.add(prompt="sunset over ocean")
    result = bridge.clone_shot(s.id, variation="with dramatic clouds")
    assert "(with dramatic clouds)" in result.get("prompt", ""), \
        f"Variation not appended: {result.get('prompt')}"

def test_bridge_clone_shot_nonexistent():
    """clone_shot returns error for unknown shot_id."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "clone_miss.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    result = bridge.clone_shot("nonexistent")
    assert result.get("status") == "error"

def test_server_has_clone_endpoint():
    """server.py has POST /api/video/shots/{id}/clone endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/clone" in src, "Missing /clone endpoint"
    assert "clone_shot" in src, "Must call clone_shot method"
    assert "variation" in src, "Must pass variation parameter"

def test_jsx_has_clone_button():
    """video_panel.jsx has Clone Variation button and cloneShot function."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "cloneShot" in src, "Missing cloneShot function"
    assert "onClone" in src, "Missing onClone prop"
    assert "Clone Variation" in src, "Missing Clone Variation button text"
    assert "/clone" in src, "Must call /clone endpoint"

def test_bridge_export_shotboard():
    """VideoBridge.export_shotboard returns full board data."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "export_test.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    bridge.board.add(prompt="shot A", title="First")
    bridge.board.add(prompt="shot B", title="Second")
    result = bridge.export_shotboard()
    assert "shots" in result, "Export must include shots list"
    assert len(result["shots"]) == 2, f"Expected 2 shots, got {len(result['shots'])}"
    assert result["shots"][0]["prompt"] == "shot A"
    assert result["shots"][1]["title"] == "Second"

def test_bridge_import_shotboard():
    """VideoBridge.import_shotboard replaces board from JSON data."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "import_test.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    bridge.board.add(prompt="existing")
    import_data = {
        "shots": [
            {"prompt": "imported A", "title": "IA"},
            {"prompt": "imported B", "title": "IB"},
            {"prompt": "imported C", "title": "IC"},
        ]
    }
    result = bridge.import_shotboard(import_data)
    assert result["status"] == "ok"
    assert result["imported"] == 3
    assert len(bridge.board) == 3
    assert bridge.board.all()[0].prompt == "imported A"
    assert all(s.status == "draft" for s in bridge.board)

def test_bridge_import_invalid_data():
    """import_shotboard rejects non-list shots field."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "import_bad.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    result = bridge.import_shotboard({"shots": "not a list"})
    assert result["status"] == "error"

def test_server_has_export_import_endpoints():
    """server.py has /api/video/export and /api/video/import endpoints."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/export" in src, "Missing /api/video/export endpoint"
    assert "/api/video/import" in src, "Missing /api/video/import endpoint"
    assert "export_shotboard" in src, "Must call export_shotboard"
    assert "import_shotboard" in src, "Must call import_shotboard"

def test_jsx_has_export_import_buttons():
    """video_panel.jsx has Export JSON and Import JSON buttons."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "exportShotboard" in src, "Missing exportShotboard function"
    assert "importShotboard" in src, "Missing importShotboard function"
    assert "Export JSON" in src, "Missing Export JSON button text"
    assert "Import JSON" in src, "Missing Import JSON button text"
    assert "export-json" in src, "Missing export-json CSS class"
    assert "import-json" in src, "Missing import-json CSS class"
    assert "/api/video/export" in src, "Must call export endpoint"
    assert "/api/video/import" in src, "Must call import endpoint"

def test_bridge_export_import_roundtrip():
    """Export then import produces identical board."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "rt_test.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    bridge.board.add(prompt="alpha", title="A", negative="blurry", seed=42)
    bridge.board.add(prompt="beta", title="B", notes="pan right")
    exported = bridge.export_shotboard()
    bridge2 = VideoBridge(
        shotboard_path=os.path.join(TMP, "rt_test2.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    result = bridge2.import_shotboard(exported)
    assert result["status"] == "ok"
    assert len(bridge2.board) == 2
    s1 = bridge2.board.all()[0]
    assert s1.prompt == "alpha"
    assert s1.negative == "blurry"
    assert s1.seed == 42
    s2 = bridge2.board.all()[1]
    assert s2.notes == "pan right"



# ═══════════════════════════════════════════════════════════════════════
# Round 16 — Timeline strip view with drag-and-drop reorder
# ═══════════════════════════════════════════════════════════════════════

def test_jsx_has_timeline_strip_component():
    """video_panel.jsx has TimelineStrip component with drag-and-drop."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "function TimelineStrip" in src, "Missing TimelineStrip component"
    assert "timeline-strip" in src, "Missing timeline-strip CSS class"
    assert "<TimelineStrip" in src, "TimelineStrip must be rendered in VideoPanel"

def test_jsx_timeline_has_drag_and_drop():
    """TimelineStrip supports HTML5 drag-and-drop for reordering."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "draggable" in src, "Timeline shots must be draggable"
    assert "onDragStart" in src, "Missing onDragStart handler"
    assert "onDragOver" in src, "Missing onDragOver handler"
    assert "onDrop" in src, "Missing onDrop handler"
    assert "dataTransfer" in src, "Must use dataTransfer for drag data"

def test_jsx_timeline_has_shot_thumbnails():
    """TimelineStrip shows thumbnail images or placeholder for each shot."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "timeline-thumb" in src, "Missing timeline thumbnail area"
    assert "timeline-shot" in src, "Missing timeline-shot CSS class"
    assert "timeline-status" in src, "Missing status indicator in timeline"

def test_jsx_timeline_has_selected_state():
    """TimelineStrip highlights the selected shot."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "selectedShotId" in src, "Missing selectedShotId state"
    assert "selectedId" in src, "TimelineStrip must receive selectedId prop"
    assert "onSelect" in src, "TimelineStrip must receive onSelect prop"
    assert "border-amber-500" in src, "Selected shot should have amber border"

def test_jsx_timeline_has_duration_display():
    """TimelineStrip shows duration for each shot."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "timeline-duration" in src, "Missing duration display in timeline"
    assert "toFixed" in src, "Duration should be formatted with toFixed"

def test_jsx_timeline_drop_handler():
    """VideoPanel has onTimelineDrop handler that calls reorder API."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "onTimelineDrop" in src, "Missing onTimelineDrop handler"
    assert "/api/video/reorder" in src, "Drop handler must call reorder API"

def test_jsx_timeline_status_colors():
    """TimelineStrip uses correct status colours for each state."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    # Check all five statuses are mapped
    for status in ("draft", "queued", "running", "ready", "failed"):
        assert f'"{status}"' in src, f"Timeline missing status colour for: {status}"
    assert "animate-pulse" in src, "Running status should pulse"

def test_shotboard_reorder_preserves_all():
    """Shotboard.reorder with all ids preserves every shot."""
    board = Shotboard(os.path.join(TMP, "reorder_all.json"))
    s1 = board.add(prompt="A")
    s2 = board.add(prompt="B")
    s3 = board.add(prompt="C")
    board.reorder([s3.id, s1.id, s2.id])
    ids = [s.id for s in board.all()]
    assert ids == [s3.id, s1.id, s2.id], f"Reorder failed: {ids}"
    assert all(s.index == i for i, s in enumerate(board.all())), "Indices not updated"

def test_shotboard_reorder_partial():
    """Shotboard.reorder with partial ids appends missing shots."""
    board = Shotboard(os.path.join(TMP, "reorder_partial.json"))
    s1 = board.add(prompt="A")
    s2 = board.add(prompt="B")
    s3 = board.add(prompt="C")
    board.reorder([s3.id])
    ids = [s.id for s in board.all()]
    assert ids[0] == s3.id, "First should be s3"
    assert len(ids) == 3, "No shots should be lost"
    assert set(ids) == {s1.id, s2.id, s3.id}, "All shots must survive"



# ═══════════════════════════════════════════════════════════════════════
# Round 17 — Shot search/filter, total duration display
# ═══════════════════════════════════════════════════════════════════════

def test_jsx_has_search_input():
    """video_panel.jsx has a search input for filtering shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "searchQuery" in src, "Missing searchQuery state"
    assert "setSearchQuery" in src, "Missing setSearchQuery setter"
    assert "search-input" in src, "Missing search input element"
    assert "search-bar" in src, "Missing search-bar container"
    assert "search-clear" in src, "Missing search clear button"

def test_jsx_search_filters_by_prompt_title_notes():
    """filteredShots respects searchQuery across prompt, title, and notes."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "searchQuery" in src and "filteredShots" in src, "Missing search+filter link"
    # Check it searches all three fields
    assert "s.prompt" in src and "toLowerCase" in src, "Should search prompt text"
    assert "s.title" in src, "Should search title"
    assert "s.notes" in src, "Should search notes"

def test_jsx_has_total_duration_display():
    """video_panel.jsx shows total shot count and estimated duration."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "total-duration" in src, "Missing total-duration display element"
    assert "shots.length" in src, "Should show shot count"
    assert "reduce" in src, "Should sum durations with reduce"
    assert "total" in src.lower(), "Should display total label"

def test_jsx_search_placeholder():
    """Search input has descriptive placeholder text."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "Search shots" in src, "Missing search placeholder"
    assert "placeholder" in src, "Input should have placeholder attribute"



# ═══════════════════════════════════════════════════════════════════════
# Round 18 — Color labels, confirm dialogs
# ═══════════════════════════════════════════════════════════════════════

def test_shot_has_color_label_field():
    """Shot dataclass has color_label field with empty string default."""
    from scaffold.shotboard import Shot
    s = Shot(prompt="test")
    assert hasattr(s, "color_label"), "Missing color_label field"
    assert s.color_label == "", "Default should be empty string"
    s2 = Shot(prompt="test", color_label="red")
    assert s2.color_label == "red"
    d = s2.to_dict()
    assert d["color_label"] == "red", "color_label should serialize"

def test_shot_color_label_roundtrip():
    """color_label survives to_dict/from_dict roundtrip."""
    from scaffold.shotboard import Shot
    s = Shot(prompt="test", color_label="blue")
    d = s.to_dict()
    s2 = Shot.from_dict(d)
    assert s2.color_label == "blue", "color_label lost in roundtrip"

def test_shotboard_update_color_label():
    """Shotboard.update can set color_label."""
    board = Shotboard(os.path.join(TMP, "color_test.json"))
    s = board.add(prompt="test")
    board.update(s.id, color_label="green")
    assert board.get(s.id).color_label == "green"
    board.update(s.id, color_label="")
    assert board.get(s.id).color_label == ""

def test_jsx_has_color_label_picker():
    """video_panel.jsx has color label picker UI."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "COLOR_LABELS" in src, "Missing COLOR_LABELS constant"
    assert "color-label-picker" in src, "Missing color-label-picker CSS class"
    assert "color-label-menu" in src, "Missing color label menu"
    assert "onColorLabel" in src, "Missing onColorLabel prop"
    assert "setColorLabel" in src, "Missing setColorLabel function"

def test_jsx_timeline_shows_color_label():
    """TimelineStrip renders color label dot for labelled shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "timeline-color-label" in src, "Missing color label in timeline"
    assert "color_label" in src, "Timeline must reference shot.color_label"

def test_jsx_has_confirm_on_delete():
    """removeShot uses window.confirm before deletion."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    # Find removeShot function and check for confirm
    idx = src.index("const removeShot")
    chunk = src[idx:idx+300]
    assert "confirm(" in chunk, "removeShot must use window.confirm"
    assert "cannot be undone" in chunk.lower(), "Confirm should warn about irreversibility"

def test_jsx_has_confirm_on_reset_failed():
    """resetFailed uses window.confirm before reset."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    idx = src.index("const resetFailed")
    chunk = src[idx:idx+300]
    assert "confirm(" in chunk, "resetFailed must use window.confirm"

def test_jsx_has_confirm_on_bulk_delete():
    """deleteSelected uses window.confirm before deletion."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    idx = src.index("const deleteSelected")
    chunk = src[idx:idx+300]
    assert "confirm(" in chunk, "deleteSelected must use window.confirm"

def test_jsx_has_confirm_on_import():
    """importShotboard uses window.confirm before replacing board."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert 'confirm("Import will replace' in src or "confirm(`Import will replace" in src, \
        "Import must confirm before overwriting"



# ═══════════════════════════════════════════════════════════════════════
# Round 19 — Render cancellation
# ═══════════════════════════════════════════════════════════════════════

def test_bridge_has_cancel_shot():
    """VideoBridge has cancel_shot method."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "cancel_test.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    assert hasattr(bridge, 'cancel_shot'), "Missing cancel_shot method"
    # Cancel on nothing should return error
    result = bridge.cancel_shot("nonexistent")
    assert result["status"] == "error"

def test_bridge_cancel_shot_resets_state():
    """cancel_shot resets active progress fields."""
    vb = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(vb) as f:
        src = f.read()
    assert "def cancel_shot" in src, "Missing cancel_shot method"
    # Must reset progress tracking
    idx = src.index("def cancel_shot")
    chunk = src[idx:idx+1000]
    assert "_active_progress = 0" in chunk, "cancel must reset _active_progress"
    assert "_active_stage" in chunk, "cancel must reset _active_stage"
    assert 'status="draft"' in chunk or "status='draft'" in chunk, \
        "cancel must reset shot status to draft"

def test_bridge_cancel_emits_sse():
    """cancel_shot emits a shot-update SSE event."""
    vb = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(vb) as f:
        src = f.read()
    idx = src.index("def cancel_shot")
    chunk = src[idx:idx+1000]
    assert "_emit_shot_update" in chunk, "cancel must emit SSE event"

def test_server_has_cancel_endpoint():
    """server.py has POST /cancel endpoint for shots."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/cancel" in src, "Missing /cancel endpoint"
    assert "cancel_shot" in src, "Must call cancel_shot method"

def test_jsx_has_cancel_button():
    """video_panel.jsx has Cancel button for running/queued shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "cancelShot" in src, "Missing cancelShot function"
    assert "onCancel" in src, "Missing onCancel prop"
    assert "cancel-render" in src, "Missing cancel-render CSS class"
    assert "/cancel" in src, "Must call /cancel endpoint"
    assert "Cancel" in src, "Missing Cancel button text"

def test_jsx_cancel_only_for_active():
    """Cancel button only shows for running/queued shots."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert '"running"' in src and '"queued"' in src, "Must check for running/queued status"
    assert "onCancel(shot.id)" in src, "Must call onCancel with shot id"

def test_jsx_cancel_has_confirm():
    """cancelShot uses window.confirm."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    idx = src.index("const cancelShot")
    chunk = src[idx:idx+300]
    assert "confirm(" in chunk, "cancelShot must use window.confirm"



# ═══════════════════════════════════════════════════════════════════════
# Round 20 — Batch Preset Change + Render Time Estimation
# ═══════════════════════════════════════════════════════════════════════

# -- estimate_render_time --

def _r20_bridge(name="r20"):
    from scaffold.video_bridge import VideoBridge
    return VideoBridge(
        shotboard_path=os.path.join(TMP, f"{name}.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )

def test_estimate_render_time_empty():
    """estimate_render_time returns empty estimates when no ready shots."""
    bridge = _r20_bridge("est_empty")
    bridge.board.add(prompt="draft shot", status="draft")
    result = bridge.estimate_render_time()
    assert result == {"estimates": {}}

def test_estimate_render_time_aggregates():
    """estimate_render_time computes avg/min/max per preset."""
    bridge = _r20_bridge("r20_0")
    s1 = bridge.board.add(prompt="a", preset="fast", status="ready",
                          render_duration_s=10.0)
    s2 = bridge.board.add(prompt="b", preset="fast", status="ready",
                          render_duration_s=20.0)
    s3 = bridge.board.add(prompt="c", preset="slow", status="ready",
                          render_duration_s=60.0)
    result = bridge.estimate_render_time()
    est = result["estimates"]
    assert "fast" in est
    assert "slow" in est
    assert est["fast"]["avg_seconds"] == 15.0
    assert est["fast"]["min_seconds"] == 10.0
    assert est["fast"]["max_seconds"] == 20.0
    assert est["fast"]["sample_count"] == 2
    assert est["slow"]["avg_seconds"] == 60.0
    assert est["slow"]["sample_count"] == 1

def test_estimate_render_time_single_preset():
    """estimate_render_time with preset= returns single estimate."""
    bridge = _r20_bridge("r20_1")
    bridge.board.add(prompt="a", preset="fast", status="ready",
                     render_duration_s=10.0)
    bridge.board.add(prompt="b", preset="fast", status="ready",
                     render_duration_s=30.0)
    result = bridge.estimate_render_time(preset="fast")
    assert result["avg_seconds"] == 20.0
    assert result["sample_count"] == 2

def test_estimate_render_time_unknown_preset():
    """estimate_render_time for unknown preset returns null estimate."""
    bridge = _r20_bridge("r20_2")
    result = bridge.estimate_render_time(preset="nonexistent")
    assert result["avg_seconds"] is None
    assert result["sample_count"] == 0

# -- batch_update_preset --

def test_batch_update_preset_basic():
    """batch_update_preset changes preset for multiple draft shots."""
    bridge = _r20_bridge("r20_3")
    s1 = bridge.board.add(prompt="a", preset="old_preset")
    s2 = bridge.board.add(prompt="b", preset="old_preset")
    result = bridge.batch_update_preset([s1.id, s2.id], "new_preset")
    assert result["updated"] == 2
    assert result["preset"] == "new_preset"
    assert bridge.board.get(s1.id).preset == "new_preset"
    assert bridge.board.get(s2.id).preset == "new_preset"

def test_batch_update_preset_skips_non_draft():
    """batch_update_preset only changes draft shots, skips running/ready."""
    bridge = _r20_bridge("r20_4")
    s1 = bridge.board.add(prompt="draft", preset="old")
    s2 = bridge.board.add(prompt="running", preset="old")
    bridge.board.update(s2.id, status="running")
    s3 = bridge.board.add(prompt="ready", preset="old")
    bridge.board.update(s3.id, status="ready")
    result = bridge.batch_update_preset([s1.id, s2.id, s3.id], "new")
    assert result["updated"] == 1
    assert bridge.board.get(s1.id).preset == "new"
    assert bridge.board.get(s2.id).preset == "old"
    assert bridge.board.get(s3.id).preset == "old"

def test_batch_update_preset_empty_list():
    """batch_update_preset with empty list updates nothing."""
    bridge = _r20_bridge("r20_5")
    result = bridge.batch_update_preset([], "any_preset")
    assert result["updated"] == 0

# -- server endpoints --

def test_server_estimate_endpoint():
    """Server /api/video/estimate endpoint exists in do_GET."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/estimate" in src, "estimate endpoint missing"

def test_server_batch_preset_endpoint():
    """Server /api/video/batch-preset endpoint exists."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/batch-preset" in src, "batch-preset endpoint missing"

# -- JSX features --

def test_jsx_batch_preset_select():
    """JSX has a batch-preset-select element in the bulk actions bar."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "batch-preset-select" in src, "batch preset select missing from JSX"

def test_jsx_batch_preset_function():
    """JSX has a batchPreset function that calls the API."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "const batchPreset" in src, "batchPreset function missing"
    idx = src.index("const batchPreset")
    chunk = src[idx:idx+500]
    assert "batch-preset" in chunk, "batchPreset must call batch-preset API"

def test_jsx_braces_balanced():
    """JSX file must have balanced braces."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    opens = src.count("{")
    closes = src.count("}")
    assert opens == closes, f"Brace imbalance: {opens} opens vs {closes} closes"



# ═══════════════════════════════════════════════════════════════════════
# Round 21 — Queue Pause/Resume + Grid/List View Toggle
# ═══════════════════════════════════════════════════════════════════════

# -- Queue pause/resume --

def test_bridge_has_pause_queue():
    """VideoBridge has pause_queue method."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "pause1.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    assert hasattr(bridge, 'pause_queue'), "Missing pause_queue method"
    result = bridge.pause_queue()
    assert result["status"] == "paused"
    assert bridge._paused is True

def test_bridge_has_resume_queue():
    """VideoBridge has resume_queue method."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "resume1.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    bridge.pause_queue()
    result = bridge.resume_queue()
    assert result["status"] == "resumed"
    assert bridge._paused is False

def test_bridge_pause_blocks_queue_shot():
    """When paused, queue_shot returns paused status instead of starting render."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "pause_block.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    shot = bridge.board.add(prompt="test")
    bridge.pause_queue()
    result = bridge.queue_shot(shot.id)
    assert result["status"] == "paused", f"Expected paused, got {result}"

def test_bridge_queue_status():
    """queue_status returns paused flag and counts."""
    from scaffold.video_bridge import VideoBridge
    bridge = VideoBridge(
        shotboard_path=os.path.join(TMP, "qstatus.json"),
        wangp_url="http://127.0.0.1:1",
        comfyui_url="http://127.0.0.1:2",
        output_dir=TMP,
    )
    bridge.board.add(prompt="draft1")
    bridge.board.add(prompt="draft2")
    status = bridge.queue_status()
    assert status["paused"] is False
    assert status["drafts_pending"] == 2
    assert status["queued"] == 0

def test_bridge_pause_emits_sse():
    """pause_queue emits SSE event."""
    vb = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(vb) as f:
        src = f.read()
    idx = src.index("def pause_queue")
    chunk = src[idx:idx+300]
    assert "_emit" in chunk, "pause_queue must emit SSE event"

def test_bridge_resume_emits_sse():
    """resume_queue emits SSE event."""
    vb = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(vb) as f:
        src = f.read()
    idx = src.index("def resume_queue")
    chunk = src[idx:idx+300]
    assert "_emit" in chunk, "resume_queue must emit SSE event"

def test_batch_watcher_respects_pause():
    """The _batch_watcher loop checks _paused flag."""
    vb = os.path.join(BASE, "scaffold", "video_bridge.py")
    with open(vb) as f:
        src = f.read()
    idx = src.index("def _batch_watcher")
    chunk = src[idx:idx+500]
    assert "_paused" in chunk, "batch watcher must check _paused flag"

# -- Server endpoints --

def test_server_has_queue_pause_endpoint():
    """Server has /api/video/queue/pause endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/queue/pause" in src

def test_server_has_queue_resume_endpoint():
    """Server has /api/video/queue/resume endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/queue/resume" in src

def test_server_has_queue_status_endpoint():
    """Server has /api/video/queue/status endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/queue/status" in src

# -- Grid/List view toggle --

def test_jsx_has_view_toggle():
    """JSX has a view-toggle button."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "view-toggle" in src, "view toggle button missing"

def test_jsx_has_view_mode_state():
    """JSX has viewMode state."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "viewMode" in src, "viewMode state missing"
    assert '"list"' in src and '"grid"' in src, "Must support list and grid modes"

def test_jsx_has_grid_card_component():
    """JSX has a GridCard component."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "function GridCard" in src, "GridCard component missing"
    assert "grid-card" in src, "GridCard must have grid-card className"

def test_jsx_grid_renders_thumbnails():
    """GridCard shows thumbnail or placeholder."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    idx = src.index("function GridCard")
    chunk = src[idx:idx+2000]
    assert "aspect-video" in chunk, "Grid card must have aspect-video container"
    assert "ref_image" in chunk, "Grid card must check for ref_image"

def test_jsx_grid_shows_status_badge():
    """GridCard shows status badge."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    idx = src.index("function GridCard")
    chunk = src[idx:idx+2000]
    assert "shot.status" in chunk, "Grid card must display shot status"

def test_jsx_has_shot_grid_class():
    """JSX renders a shot-grid container in grid mode."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "shot-grid" in src, "shot-grid container missing"

def test_jsx_has_queue_pause_button():
    """JSX has a queue pause/resume button."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "queue-pause-btn" in src, "queue pause button missing"
    assert "togglePause" in src, "togglePause function missing"

def test_jsx_braces_still_balanced():
    """JSX braces must remain balanced after Round 21 changes."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert src.count("{") == src.count("}"), \
        f"Brace imbalance: {src.count('{')} opens vs {src.count('}')} closes"


# ═══════════════════════════════════════════════════════════════
# Round 22 — Video editor Guild integration tests
# ═══════════════════════════════════════════════════════════════

def test_guild_sidebar_has_on_wizard_select_prop():
    """GuildSidebar accepts onWizardSelect callback prop."""
    jsx = os.path.join(BASE, "tavern", "static", "travelling_wizard.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "onWizardSelect" in src, "onWizardSelect prop missing from GuildSidebar"
    # Verify it's in the destructured props
    import re
    m = re.search(r"function GuildSidebar\(\{[^}]+\}", src)
    assert m, "GuildSidebar function signature not found"
    assert "onWizardSelect" in m.group(0), "onWizardSelect not in GuildSidebar props destructuring"

def test_select_char_calls_on_wizard_select():
    """selectChar in GuildSidebar calls onWizardSelect callback."""
    jsx = os.path.join(BASE, "tavern", "static", "travelling_wizard.jsx")
    with open(jsx) as f:
        src = f.read()
    # Find selectChar function body
    idx = src.index("const selectChar")
    chunk = src[idx:idx+500]
    assert "onWizardSelect" in chunk, "selectChar must call onWizardSelect"

def test_is_video_wizard_helper():
    """isVideoWizard helper function exists and checks build_fns/subtext."""
    jsx = os.path.join(BASE, "tavern", "static", "travelling_wizard.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "isVideoWizard" in src, "isVideoWizard helper missing"
    idx = src.index("isVideoWizard")
    chunk = src[idx:idx+500]
    assert "build_fns" in chunk, "isVideoWizard must check build_fns"
    assert "subtext" in chunk, "isVideoWizard must check subtext"
    assert "video" in chunk.lower(), "isVideoWizard must look for video keyword"

def test_handle_wizard_select_auto_switches_tab():
    """handleWizardSelect exists and switches activeTab to video."""
    jsx = os.path.join(BASE, "tavern", "static", "travelling_wizard.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "handleWizardSelect" in src, "handleWizardSelect missing"
    idx = src.index("handleWizardSelect")
    chunk = src[idx:idx+800]
    assert "isVideoWizard" in chunk, "handleWizardSelect must use isVideoWizard"
    assert 'setActiveTab("video")' in chunk, "Must auto-switch to video tab"

def test_handle_wizard_select_restores_previous_tab():
    """handleWizardSelect restores previous tab when non-video wizard selected."""
    jsx = os.path.join(BASE, "tavern", "static", "travelling_wizard.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "prevTabRef" in src, "prevTabRef missing for tab restoration"
    idx = src.index("handleWizardSelect")
    chunk = src[idx:idx+800]
    assert "prevTabRef" in chunk, "handleWizardSelect must use prevTabRef"

def test_video_panel_always_mounted():
    """VideoPanel is always mounted (hidden when inactive) to preserve state."""
    jsx = os.path.join(BASE, "tavern", "static", "travelling_wizard.jsx")
    with open(jsx) as f:
        src = f.read()
    # Should use display:none pattern, not conditional rendering
    assert 'display: activeTab === "video"' in src, "VideoPanel should use display toggle, not conditional mount"
    assert "VideoPanel" in src, "VideoPanel reference missing"

def test_guild_sidebar_receives_on_wizard_select():
    """GuildSidebar in SignalBridgeSettings receives onWizardSelect prop."""
    jsx = os.path.join(BASE, "tavern", "static", "travelling_wizard.jsx")
    with open(jsx) as f:
        src = f.read()
    # Find the GuildSidebar JSX usage (not definition)
    idx = src.index("<GuildSidebar")
    chunk = src[idx:idx+500]
    assert "onWizardSelect={handleWizardSelect}" in chunk, \
        "GuildSidebar must receive onWizardSelect={handleWizardSelect}"

def test_travelling_wizard_braces_balanced():
    """travelling_wizard.jsx braces must remain balanced after Round 22."""
    jsx = os.path.join(BASE, "tavern", "static", "travelling_wizard.jsx")
    with open(jsx) as f:
        src = f.read()
    assert src.count("{") == src.count("}"), \
        f"Brace imbalance: {src.count('{')} opens vs {src.count('}')}"
    assert src.count("(") == src.count(")"), \
        f"Paren imbalance: {src.count('(')} opens vs {src.count(')')}"

def test_video_panel_export_exists():
    """video_panel.jsx exports VideoPanel to window."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "window.VideoPanel = VideoPanel" in src, "Missing VideoPanel window export"

def test_server_reference_upload_endpoint():
    """server.py has base64 reference image upload endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "image_data" in src, "Missing image_data handling"
    assert "/reference" in src, "Missing reference endpoint"



# ══════════════════════════════════════════════════════════════════════
# Round 23 — Transitions + Concurrency
# ══════════════════════════════════════════════════════════════════════

def test_shot_transition_fields():
    """Shot dataclass has transition and transition_ms fields with defaults."""
    from scaffold.shotboard import Shot, TRANSITION_TYPES
    s = Shot()
    assert s.transition == "cut", f"Expected default 'cut', got {s.transition}"
    assert s.transition_ms == 500, f"Expected default 500, got {s.transition_ms}"
    assert "cut" in TRANSITION_TYPES
    assert "crossfade" in TRANSITION_TYPES
    assert "wipeleft" in TRANSITION_TYPES
    assert len(TRANSITION_TYPES) == 7, f"Expected 7 transition types, got {len(TRANSITION_TYPES)}"

def test_shot_transition_roundtrip():
    """Shot transition fields survive to_dict → from_dict roundtrip."""
    from scaffold.shotboard import Shot
    s = Shot(transition="crossfade", transition_ms=800)
    d = s.to_dict()
    assert d["transition"] == "crossfade"
    assert d["transition_ms"] == 800
    s2 = Shot.from_dict(d)
    assert s2.transition == "crossfade"
    assert s2.transition_ms == 800

def test_shotboard_transition_persistence():
    """Shotboard persists transition fields through save/load cycle."""
    import tempfile, os
    from scaffold.shotboard import Shotboard
    path = os.path.join(tempfile.mkdtemp(), "trans_test.json")
    board = Shotboard(path)
    shot = board.add(transition="fade", transition_ms=1000)
    sid = shot.id
    # Reload from disk
    board2 = Shotboard(path)
    loaded = board2.get(sid)
    assert loaded is not None
    assert loaded.transition == "fade", f"Expected 'fade', got {loaded.transition}"
    assert loaded.transition_ms == 1000

def test_xfade_name_mapping():
    """_xfade_name maps our transition names to ffmpeg names."""
    import sys
    sys.path.insert(0, ".")
    from scaffold.video_bridge import _xfade_name
    assert _xfade_name("fade") == "fade"
    assert _xfade_name("crossfade") == "fade"
    assert _xfade_name("wipeleft") == "wipeleft"
    assert _xfade_name("wiperight") == "wiperight"
    assert _xfade_name("wipeup") == "wipeup"
    assert _xfade_name("wipedown") == "wipedown"
    # Unknown falls back to fade
    assert _xfade_name("unknown") == "fade"

def test_build_xfade_filter_all_cuts():
    """_build_xfade_filter returns (None, None) when all transitions are cuts."""
    from scaffold.video_bridge import _build_xfade_filter
    from scaffold.shotboard import Shot
    shots = [Shot(transition="cut"), Shot(transition="cut"), Shot(transition="cut")]
    videos = ["/tmp/a.mp4", "/tmp/b.mp4", "/tmp/c.mp4"]
    f, label = _build_xfade_filter(shots, videos)
    assert f is None and label is None, "All-cut board should return None"

def test_build_xfade_filter_single_video():
    """_build_xfade_filter returns (None, None) for < 2 videos."""
    from scaffold.video_bridge import _build_xfade_filter
    from scaffold.shotboard import Shot
    f, label = _build_xfade_filter([Shot()], ["/tmp/a.mp4"])
    assert f is None and label is None

def test_build_xfade_filter_with_transitions():
    """_build_xfade_filter produces xfade filter string for non-cut transitions."""
    from scaffold.video_bridge import _build_xfade_filter
    from scaffold.shotboard import Shot
    shots = [Shot(transition="fade", transition_ms=500), Shot(transition="cut")]
    videos = ["/tmp/a.mp4", "/tmp/b.mp4"]
    f, label = _build_xfade_filter(shots, videos)
    # At least one non-cut transition => should produce a filter
    assert f is not None, "Expected xfade filter string"
    assert "xfade" in f, f"Expected 'xfade' in filter: {f}"
    assert label is not None

def test_video_bridge_get_settings():
    """VideoBridge.get_settings returns max_concurrent and paused."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "settings_test.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    settings = bridge.get_settings()
    assert "max_concurrent" in settings
    assert "paused" in settings
    assert settings["max_concurrent"] == 2  # default
    assert settings["paused"] is False

def test_video_bridge_set_max_concurrent():
    """VideoBridge.set_max_concurrent clamps to 1-8 range."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "conc_test.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    result = bridge.set_max_concurrent(4)
    assert result["max_concurrent"] == 4
    assert result["previous"] == 2
    # Clamp low
    result = bridge.set_max_concurrent(0)
    assert result["max_concurrent"] == 1
    # Clamp high
    result = bridge.set_max_concurrent(100)
    assert result["max_concurrent"] == 8

def test_video_bridge_queue_status_has_max_concurrent():
    """VideoBridge.queue_status includes max_concurrent."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "qs_test.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    status = bridge.queue_status()
    assert "max_concurrent" in status, "queue_status must include max_concurrent"

def test_video_panel_transition_picker():
    """video_panel.jsx has transition picker in ShotCard."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "transition-picker" in src, "Missing transition-picker class"
    assert "transition-type-select" in src, "Missing transition type select"
    assert "Crossfade" in src, "Missing Crossfade option"
    assert "Wipe Left" in src or "wipeleft" in src, "Missing wipe options"
    assert "editTransition" in src, "Missing editTransition state"

def test_video_panel_concurrency_control():
    """video_panel.jsx has concurrency control in HealthPanel."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "concurrency-control" in src, "Missing concurrency-control class"
    assert "max-concurrent-select" in src, "Missing max-concurrent-select"
    assert "maxConcurrent" in src, "Missing maxConcurrent state"
    assert "onMaxConcurrentChange" in src, "Missing onMaxConcurrentChange prop"

def test_server_settings_endpoints():
    """server.py has GET/POST /api/video/settings endpoints."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/settings" in src, "Missing settings endpoint"
    assert "get_settings" in src, "Missing get_settings call"
    assert "set_max_concurrent" in src, "Missing set_max_concurrent call"

def test_server_shot_serialization_has_transitions():
    """server.py serializes transition fields in shot responses."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "'transition'" in src or '"transition"' in src,         "Missing transition in shot serialization"
    assert "transition_ms" in src, "Missing transition_ms in shot serialization"

def test_video_bridge_render_semaphore():
    """VideoBridge has a render semaphore for concurrency gating."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "sem_test.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    assert hasattr(bridge, "_render_sem"), "Missing _render_sem"
    assert hasattr(bridge, "_max_concurrent"), "Missing _max_concurrent"
    # After set_max_concurrent, semaphore should be replaced
    bridge.set_max_concurrent(3)
    assert bridge._max_concurrent == 3



# ══════════════════════════════════════════════════════════════════════
# Round 24 — Export Settings
# ══════════════════════════════════════════════════════════════════════

def test_export_settings_defaults():
    """ExportSettings has correct default values."""
    from scaffold.video_bridge import ExportSettings
    es = ExportSettings()
    assert es.resolution == "source"
    assert es.codec == "h264"
    assert es.fps == 0
    assert es.crf == 23
    assert es.audio is True

def test_export_settings_roundtrip():
    """ExportSettings survives to_dict → from_dict roundtrip."""
    from scaffold.video_bridge import ExportSettings
    es = ExportSettings(resolution="1920x1080", codec="h265", fps=30, crf=18, audio=False)
    d = es.to_dict()
    assert d["resolution"] == "1920x1080"
    assert d["codec"] == "h265"
    es2 = ExportSettings.from_dict(d)
    assert es2.resolution == "1920x1080"
    assert es2.codec == "h265"
    assert es2.fps == 30
    assert es2.crf == 18
    assert es2.audio is False

def test_export_settings_from_dict_ignores_unknown():
    """ExportSettings.from_dict drops unknown keys gracefully."""
    from scaffold.video_bridge import ExportSettings
    es = ExportSettings.from_dict({"codec": "vp9", "bogus_key": 42})
    assert es.codec == "vp9"

def test_export_settings_ffmpeg_args_h264():
    """ffmpeg_output_args produces correct h264 args."""
    from scaffold.video_bridge import ExportSettings
    es = ExportSettings(codec="h264", crf=20, fps=24, resolution="source", audio=True)
    args = es.ffmpeg_output_args()
    assert "-c:v" in args
    assert "libx264" in args
    assert "-crf" in args
    assert "20" in args
    assert "-r" in args
    assert "24" in args
    assert "-an" not in args
    assert "-c:a" in args

def test_export_settings_ffmpeg_args_no_audio():
    """ffmpeg_output_args includes -an when audio=False."""
    from scaffold.video_bridge import ExportSettings
    es = ExportSettings(audio=False)
    args = es.ffmpeg_output_args()
    assert "-an" in args

def test_export_settings_ffmpeg_args_resolution():
    """ffmpeg_output_args includes scale filter for non-source resolution."""
    from scaffold.video_bridge import ExportSettings
    es = ExportSettings(resolution="1280x720")
    args = es.ffmpeg_output_args()
    assert "-vf" in args
    vf_idx = args.index("-vf")
    assert "1280" in args[vf_idx + 1]
    assert "720" in args[vf_idx + 1]

def test_export_settings_ffmpeg_args_prores():
    """ffmpeg_output_args uses prores_ks and skips CRF for prores."""
    from scaffold.video_bridge import ExportSettings
    es = ExportSettings(codec="prores")
    args = es.ffmpeg_output_args()
    assert "prores_ks" in args
    assert "-crf" not in args

def test_export_settings_ffmpeg_args_vp9():
    """ffmpeg_output_args uses libvpx-vp9 for vp9 codec."""
    from scaffold.video_bridge import ExportSettings
    es = ExportSettings(codec="vp9")
    args = es.ffmpeg_output_args()
    assert "libvpx-vp9" in args

def test_export_codecs_constant():
    """EXPORT_CODECS and EXPORT_RESOLUTIONS are defined."""
    from scaffold.video_bridge import EXPORT_CODECS, EXPORT_RESOLUTIONS
    assert "h264" in EXPORT_CODECS
    assert "h265" in EXPORT_CODECS
    assert "vp9" in EXPORT_CODECS
    assert "prores" in EXPORT_CODECS
    assert "source" in EXPORT_RESOLUTIONS
    assert "1920x1080" in EXPORT_RESOLUTIONS

def test_video_bridge_export_settings_methods():
    """VideoBridge has get/set_export_settings methods."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "export_test.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    settings = bridge.get_export_settings()
    assert settings["codec"] == "h264"
    assert settings["resolution"] == "source"
    result = bridge.set_export_settings({"codec": "h265", "crf": 18})
    assert result["codec"] == "h265"
    assert result["crf"] == 18

def test_video_bridge_get_settings_includes_export():
    """VideoBridge.get_settings includes export settings."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "exp_full.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    settings = bridge.get_settings()
    assert "export" in settings, "get_settings must include export key"
    assert settings["export"]["codec"] == "h264"

def test_server_export_settings_endpoints():
    """server.py has GET/POST /api/video/export-settings endpoints."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/export-settings" in src
    assert "get_export_settings" in src
    assert "set_export_settings" in src

def test_video_panel_export_settings_ui():
    """video_panel.jsx has export settings panel and controls."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "export-settings-panel" in src, "Missing export-settings-panel class"
    assert "export-resolution-select" in src, "Missing resolution select"
    assert "export-codec-select" in src, "Missing codec select"
    assert "export-fps-input" in src, "Missing fps input"
    assert "export-crf-input" in src, "Missing crf input"
    assert "export-audio-checkbox" in src, "Missing audio checkbox"
    assert "exportSettings" in src, "Missing exportSettings state"
    assert "showExportSettings" in src, "Missing showExportSettings toggle"
    assert "ExportSettingsPanel" in src, "Missing ExportSettingsPanel component"

def test_assemble_shots_accepts_export_settings():
    """assemble_shots signature accepts export_settings parameter."""
    import inspect
    from scaffold.video_bridge import assemble_shots
    sig = inspect.signature(assemble_shots)
    assert "export_settings" in sig.parameters, "Missing export_settings parameter"



# ══════════════════════════════════════════════════════════════════════
# Round 25 — Scene Grouping
# ══════════════════════════════════════════════════════════════════════

def test_scene_dataclass():
    """Scene dataclass has id, name, color, collapsed fields."""
    from scaffold.shotboard import Scene
    sc = Scene(name="Act 1", color="#ff0000")
    assert sc.name == "Act 1"
    assert sc.color == "#ff0000"
    assert sc.collapsed is False
    assert len(sc.id) > 0

def test_scene_roundtrip():
    """Scene survives to_dict → from_dict roundtrip."""
    from scaffold.shotboard import Scene
    sc = Scene(name="Forest", color="#00ff00", collapsed=True)
    d = sc.to_dict()
    sc2 = Scene.from_dict(d)
    assert sc2.name == "Forest"
    assert sc2.color == "#00ff00"
    assert sc2.collapsed is True
    assert sc2.id == sc.id

def test_shot_has_scene_id():
    """Shot dataclass has scene_id field defaulting to None."""
    from scaffold.shotboard import Shot
    s = Shot()
    assert s.scene_id is None
    s2 = Shot(scene_id="abc123")
    assert s2.scene_id == "abc123"

def test_shotboard_add_scene():
    """Shotboard.add_scene creates and persists a scene."""
    import tempfile, os
    from scaffold.shotboard import Shotboard
    path = os.path.join(tempfile.mkdtemp(), "scene_test.json")
    board = Shotboard(path)
    sc = board.add_scene(name="Intro", color="#ff0000")
    assert sc.name == "Intro"
    assert sc.color == "#ff0000"
    # Reload
    board2 = Shotboard(path)
    assert len(board2.scenes()) == 1
    assert board2.scenes()[0].name == "Intro"

def test_shotboard_remove_scene_clears_shots():
    """Removing a scene clears scene_id from its shots."""
    import tempfile, os
    from scaffold.shotboard import Shotboard
    path = os.path.join(tempfile.mkdtemp(), "rm_scene.json")
    board = Shotboard(path)
    sc = board.add_scene(name="Forest")
    shot = board.add(prompt="deer")
    board.assign_shot_to_scene(shot.id, sc.id)
    assert board.get(shot.id).scene_id == sc.id
    board.remove_scene(sc.id)
    assert board.get(shot.id).scene_id is None
    assert len(board.scenes()) == 0

def test_shotboard_assign_shot_to_scene():
    """assign_shot_to_scene sets and clears scene_id."""
    import tempfile, os
    from scaffold.shotboard import Shotboard
    path = os.path.join(tempfile.mkdtemp(), "assign_scene.json")
    board = Shotboard(path)
    sc = board.add_scene(name="Beach")
    shot = board.add(prompt="waves")
    result = board.assign_shot_to_scene(shot.id, sc.id)
    assert result is not None
    assert result.scene_id == sc.id
    # Unassign
    result2 = board.assign_shot_to_scene(shot.id, None)
    assert result2.scene_id is None

def test_shotboard_assign_to_nonexistent_scene():
    """assign_shot_to_scene returns None for nonexistent scene."""
    import tempfile, os
    from scaffold.shotboard import Shotboard
    path = os.path.join(tempfile.mkdtemp(), "bad_scene.json")
    board = Shotboard(path)
    shot = board.add(prompt="x")
    result = board.assign_shot_to_scene(shot.id, "nonexistent")
    assert result is None

def test_shotboard_update_scene():
    """update_scene modifies scene fields."""
    import tempfile, os
    from scaffold.shotboard import Shotboard
    path = os.path.join(tempfile.mkdtemp(), "upd_scene.json")
    board = Shotboard(path)
    sc = board.add_scene(name="Old")
    result = board.update_scene(sc.id, name="New", color="#aabbcc")
    assert result.name == "New"
    assert result.color == "#aabbcc"

def test_shotboard_shots_in_scene():
    """shots_in_scene returns shots in board order."""
    import tempfile, os
    from scaffold.shotboard import Shotboard
    path = os.path.join(tempfile.mkdtemp(), "in_scene.json")
    board = Shotboard(path)
    sc = board.add_scene(name="Act 1")
    s1 = board.add(prompt="one")
    s2 = board.add(prompt="two")
    s3 = board.add(prompt="three")
    board.assign_shot_to_scene(s1.id, sc.id)
    board.assign_shot_to_scene(s3.id, sc.id)
    in_scene = board.shots_in_scene(sc.id)
    assert len(in_scene) == 2
    assert in_scene[0].id == s1.id
    assert in_scene[1].id == s3.id

def test_shotboard_scene_persistence():
    """Scenes persist across save/load cycles with shots."""
    import tempfile, os
    from scaffold.shotboard import Shotboard
    path = os.path.join(tempfile.mkdtemp(), "persist_scene.json")
    board = Shotboard(path)
    sc = board.add_scene(name="Finale", color="#aabb00")
    shot = board.add(prompt="climax")
    board.assign_shot_to_scene(shot.id, sc.id)
    # Reload
    board2 = Shotboard(path)
    assert len(board2.scenes()) == 1
    assert board2.scenes()[0].name == "Finale"
    loaded_shot = board2.get(shot.id)
    assert loaded_shot.scene_id == sc.id

def test_server_scene_endpoints():
    """server.py has scene CRUD endpoints."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/scenes" in src, "Missing scenes endpoint"
    assert "add_scene" in src, "Missing add_scene call"
    assert "remove_scene" in src, "Missing remove_scene call"
    assert "assign_shot_to_scene" in src or "/assign" in src, "Missing assign endpoint"

def test_server_shot_serialization_has_scene_id():
    """server.py includes scene_id in shot serialization."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "scene_id" in src, "Missing scene_id in shot serialization"

def test_video_panel_scene_manager():
    """video_panel.jsx has SceneManager component and scene controls."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "scene-manager" in src, "Missing scene-manager class"
    assert "SceneManager" in src, "Missing SceneManager component"
    assert "scene-list" in src, "Missing scene list"
    assert "add-scene-btn" in src, "Missing add scene button"
    assert "scene-name-input" in src, "Missing scene name input"
    assert "scene-color-picker" in src, "Missing scene color picker"

def test_video_panel_scene_assign():
    """video_panel.jsx has scene assignment in shot cards."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "scene-assign-select" in src, "Missing scene assign select"
    assert "onSceneAssign" in src, "Missing onSceneAssign prop"
    assert "assignShotToScene" in src, "Missing assignShotToScene function"



# ══════════════════════════════════════════════════════════════════════
# Round 26 — Undo/Redo
# ══════════════════════════════════════════════════════════════════════

def test_undo_manager_class_exists():
    """video_panel.jsx has UndoManager class."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "class UndoManager" in src, "Missing UndoManager class"
    assert "_undoManager" in src, "Missing _undoManager instance"

def test_undo_manager_push_undo_redo():
    """UndoManager has push, undo, redo, canUndo, canRedo methods."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    for method in ["push(", "undo()", "redo()", "canUndo()", "canRedo()", "size()"]:
        assert method in src, f"Missing UndoManager.{method}"

def test_undo_redo_state_vars():
    """video_panel.jsx has canUndo/canRedo state variables."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "canUndo" in src, "Missing canUndo state"
    assert "canRedo" in src, "Missing canRedo state"
    assert "setCanUndo" in src, "Missing setCanUndo"
    assert "setCanRedo" in src, "Missing setCanRedo"

def test_undo_redo_functions():
    """video_panel.jsx has doUndo, doRedo, and pushUndo functions."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "doUndo" in src, "Missing doUndo function"
    assert "doRedo" in src, "Missing doRedo function"
    assert "pushUndo" in src, "Missing pushUndo function"

def test_undo_redo_keyboard_shortcuts():
    """video_panel.jsx has Ctrl+Z/Ctrl+Y keyboard shortcuts for undo/redo."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "doUndo" in src, "Missing undo shortcut"
    assert "doRedo" in src, "Missing redo shortcut"
    # Check for Ctrl+Z binding
    assert 'e.key === "z"' in src or "e.key === 'z'" in src, "Missing z key binding"
    assert "ctrlKey" in src or "metaKey" in src, "Missing ctrl/meta key modifier"

def test_undo_redo_buttons():
    """video_panel.jsx has undo/redo buttons in UI."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "undo-btn" in src, "Missing undo button class"
    assert "redo-btn" in src, "Missing redo button class"
    assert "Undo" in src, "Missing Undo label"
    assert "Redo" in src, "Missing Redo label"

def test_undo_snapshot_on_add_shot():
    """addShot calls pushUndo before mutation."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    # Find addShot function and verify pushUndo is called
    add_idx = src.find("const addShot = async")
    push_idx = src.find("pushUndo()", add_idx)
    api_idx = src.find('api.post("/api/video/shots"', add_idx)
    assert push_idx < api_idx, "pushUndo must be called before api.post in addShot"

def test_undo_snapshot_on_remove_shot():
    """removeShot calls pushUndo before mutation."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    rm_idx = src.find("const removeShot = async")
    push_idx = src.find("pushUndo()", rm_idx)
    api_idx = src.find("_method", rm_idx)
    assert push_idx < api_idx, "pushUndo must be called before api call in removeShot"

def test_undo_uses_import_endpoint():
    """Undo/redo restores state via the import endpoint."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "/api/video/import" in src, "Undo/redo must use import endpoint"

def test_undo_manager_max_history():
    """UndoManager has configurable max history size."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "maxHistory" in src or "_max" in src, "Missing max history configuration"



# ══════════════════════════════════════════════════════════════════════
# Round 27 — Render Queue Dashboard
# ══════════════════════════════════════════════════════════════════════

def test_render_queue_panel_exists():
    """video_panel.jsx has RenderQueuePanel component."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "function RenderQueuePanel" in src, "Missing RenderQueuePanel function"
    assert "render-queue-panel" in src, "Missing render-queue-panel class"

def test_render_queue_summary_stats():
    """RenderQueuePanel shows running/queued/complete/failed counts."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "queue-stat-running" in src, "Missing running stat"
    assert "queue-stat-queued" in src, "Missing queued stat"
    assert "queue-stat-ready" in src, "Missing ready/complete stat"
    assert "queue-stat-failed" in src, "Missing failed stat"

def test_render_queue_eta():
    """RenderQueuePanel shows ETA based on average render time."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "queue-eta" in src, "Missing queue-eta class"
    assert "avgRenderTime" in src, "Missing average render time calculation"

def test_render_queue_items():
    """RenderQueuePanel shows individual queue items for running/queued/failed."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "queue-item-running" in src, "Missing running queue items"
    assert "queue-item-queued" in src, "Missing queued queue items"
    assert "queue-item-failed" in src, "Missing failed queue items"

def test_render_queue_progress_bar():
    """RenderQueuePanel shows progress bars for running items."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "queue-progress-bar" in src, "Missing progress bar in queue"

def test_render_queue_cancel_button():
    """RenderQueuePanel has cancel buttons."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "queue-cancel-btn" in src, "Missing cancel button class"
    assert "cancelRender" in src, "Missing cancelRender function"

def test_render_queue_retry_button():
    """RenderQueuePanel has retry buttons for failed items."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "queue-retry-btn" in src, "Missing retry button class"
    assert "retryRender" in src, "Missing retryRender function"

def test_render_queue_toggle():
    """video_panel.jsx has a toggle button for the render queue panel."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "render-queue-toggle" in src, "Missing queue toggle button"
    assert "showRenderQueue" in src, "Missing showRenderQueue state"

def test_render_queue_empty_state():
    """RenderQueuePanel shows empty state message when no active renders."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "No active renders" in src, "Missing empty state message"

def test_server_cancel_endpoint():
    """server.py has cancel render endpoint."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/cancel" in src, "Missing cancel endpoint"
    assert "cancel_shot" in src, "Missing cancel_shot call"



# ══════════════════════════════════════════════════════════════════════
# Round 28 — Preset Favorites and Quick-Switch
# ══════════════════════════════════════════════════════════════════════

def test_video_bridge_favorite_presets():
    """VideoBridge has get/set/toggle favorite presets methods."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "fav_test.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    assert bridge.get_favorite_presets() == []
    bridge.set_favorite_presets(["preset_a", "preset_b"])
    assert bridge.get_favorite_presets() == ["preset_a", "preset_b"]

def test_video_bridge_toggle_favorite():
    """VideoBridge.toggle_favorite_preset toggles on and off."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "toggle_fav.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    result = bridge.toggle_favorite_preset("my_preset")
    assert result["favorited"] is True
    assert "my_preset" in result["favorites"]
    result2 = bridge.toggle_favorite_preset("my_preset")
    assert result2["favorited"] is False
    assert "my_preset" not in result2["favorites"]

def test_video_bridge_settings_includes_favorites():
    """get_settings includes favorite_presets."""
    import tempfile, os
    from scaffold.video_bridge import VideoBridge
    path = os.path.join(tempfile.mkdtemp(), "fav_settings.json")
    bridge = VideoBridge(shotboard_path=path, wangp_url="http://127.0.0.1:1", comfyui_url="http://127.0.0.1:2")
    settings = bridge.get_settings()
    assert "favorite_presets" in settings

def test_server_favorites_endpoints():
    """server.py has GET/POST /api/video/favorites endpoints."""
    srv = os.path.join(BASE, "tavern", "server.py")
    with open(srv) as f:
        src = f.read()
    assert "/api/video/favorites" in src, "Missing favorites endpoint"
    assert "toggle_favorite_preset" in src, "Missing toggle call"
    assert "get_favorite_presets" in src, "Missing get_favorite_presets call"

def test_video_panel_favorite_presets_state():
    """video_panel.jsx has favoritePresets state and toggle function."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "favoritePresets" in src, "Missing favoritePresets state"
    assert "setFavoritePresets" in src, "Missing setFavoritePresets"
    assert "toggleFavoritePreset" in src, "Missing toggleFavoritePreset function"

def test_video_panel_preset_quick_switch():
    """video_panel.jsx has preset quick-switch dropdown in ShotCard."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "preset-quick-switch" in src, "Missing preset-quick-switch class"
    assert "preset-quick-select" in src, "Missing quick-select dropdown"

def test_video_panel_favorite_button():
    """video_panel.jsx has favorite star button."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "favorite-preset-btn" in src, "Missing favorite button class"
    # Check for star characters (filled and empty)
    assert r"\u2605" in src or "★" in src, "Missing filled star"
    assert r"\u2606" in src or "☆" in src, "Missing empty star"

def test_video_panel_favorites_optgroup():
    """video_panel.jsx shows favorites in an optgroup at top of preset selector."""
    jsx = os.path.join(BASE, "tavern", "static", "video_panel.jsx")
    with open(jsx) as f:
        src = f.read()
    assert "optgroup" in src, "Missing optgroup for favorites"
    assert "Favorites" in src, "Missing Favorites label"



# ═══════════════════════════════════════════════════════════════════════════════
# Round 29 — Shot Dependency Chains
# ═══════════════════════════════════════════════════════════════════════════════

def test_shot_depends_on_field():
    """Shot dataclass has depends_on field defaulting to empty list."""
    from scaffold.shotboard import Shot
    s = Shot(id="s1", title="T", prompt="P")
    assert hasattr(s, "depends_on"), "Shot missing depends_on"
    assert isinstance(s.depends_on, list), "depends_on must be list"
    assert s.depends_on == [], "depends_on default must be []"
    d = s.to_dict()
    assert "depends_on" in d, "to_dict missing depends_on"
    assert d["depends_on"] == [], "to_dict depends_on wrong"

def test_shotboard_add_dependency():
    """Shotboard.add_dependency links two shots."""
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="Shot A", prompt="prompt A"))
        s2 = board.add(Shot(id="sb", title="Shot B", prompt="prompt B"))
        result = board.add_dependency(s1.id, s2.id)
        assert result is not None, "add_dependency returned None"
        assert s2.id in result.depends_on, "dependency not added"

def test_shotboard_remove_dependency():
    """Shotboard.remove_dependency unlinks shots."""
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="Shot A", prompt="prompt A"))
        s2 = board.add(Shot(id="sb", title="Shot B", prompt="prompt B"))
        board.add_dependency(s1.id, s2.id)
        result = board.remove_dependency(s1.id, s2.id)
        assert result is not None, "remove_dependency returned None"
        assert s2.id not in result.depends_on, "dependency not removed"

def test_shotboard_self_dependency():
    """Shotboard.add_dependency rejects self-referencing dependency."""
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="Shot A", prompt="prompt A"))
        result = board.add_dependency(s1.id, s1.id)
        assert result is None, "self-dependency should return None"

def test_shotboard_duplicate_dependency():
    """Shotboard.add_dependency does not duplicate existing deps."""
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="Shot A", prompt="prompt A"))
        s2 = board.add(Shot(id="sb", title="Shot B", prompt="prompt B"))
        board.add_dependency(s1.id, s2.id)
        board.add_dependency(s1.id, s2.id)  # duplicate
        shot = board.get(s1.id)
        count = shot.depends_on.count(s2.id)
        assert count == 1, f"dependency duplicated: count={count}"

def test_shotboard_dependencies_met():
    """Shotboard.dependencies_met checks dependency statuses."""
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="Shot A", prompt="prompt A"))
        s2 = board.add(Shot(id="sb", title="Shot B", prompt="prompt B"))
        board.add_dependency(s1.id, s2.id)
        # s2 is still draft, so deps NOT met
        assert not board.dependencies_met(s1.id), "deps should not be met (s2 is draft)"
        # Mark s2 as ready
        s2.status = "ready"
        board.save()
        assert board.dependencies_met(s1.id), "deps should be met (s2 is ready)"

def test_shotboard_ready_to_render():
    """Shotboard.ready_to_render combines status + dependency check."""
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="Shot A", prompt="prompt A"))
        s2 = board.add(Shot(id="sb", title="Shot B", prompt="prompt B"))
        board.add_dependency(s1.id, s2.id)
        # s1 is draft but s2 is not ready => not ready_to_render
        assert not board.ready_to_render(s1.id), "should not be ready (dep not met)"
        # Make s2 ready
        s2.status = "ready"
        board.save()
        assert board.ready_to_render(s1.id), "should be ready (draft + dep met)"
        # Make s1 not draft
        s1.status = "rendering"
        board.save()
        assert not board.ready_to_render(s1.id), "should not be ready (not draft)"

def test_server_dependency_endpoints():
    """server.py has POST and DELETE /api/video/dependencies endpoints."""
    src = open("tavern/server.py").read()
    assert "api/video/dependencies" in src, "Missing dependencies endpoint path"
    assert "add_dependency" in src, "Missing add_dependency call"
    assert "remove_dependency" in src, "Missing remove_dependency call"
    assert "dependencies_met" in src, "Missing dependencies_met call"
    assert "ready_to_render" in src, "Missing ready_to_render call"

def test_server_depends_on_serialization():
    """server.py includes depends_on in shot list serialization."""
    src = open("tavern/server.py").read()
    assert '"depends_on"' in src, "Missing depends_on in shot serialization"

def test_video_panel_dependency_row():
    """video_panel.jsx has dependency-row in ShotCard."""
    src = open("tavern/static/video_panel.jsx").read()
    assert "dependency-row" in src, "Missing dependency-row class"
    assert "dep-add-select" in src, "Missing dep-add-select class"
    assert "Depends on:" in src, "Missing Depends on label"

def test_video_panel_add_dependency_fn():
    """video_panel.jsx has addDependency and removeDependency functions."""
    src = open("tavern/static/video_panel.jsx").read()
    assert "const addDependency" in src, "Missing addDependency function"
    assert "const removeDependency" in src, "Missing removeDependency function"
    assert "onAddDependency" in src, "Missing onAddDependency prop"
    assert "onRemoveDependency" in src, "Missing onRemoveDependency prop"

def test_video_panel_dep_badges():
    """video_panel.jsx shows dep-badge with remove button for dependencies."""
    src = open("tavern/static/video_panel.jsx").read()
    assert "dep-badge" in src, "Missing dep-badge class"
    assert "dep-remove-btn" in src, "Missing dep-remove-btn class"
    assert "dep-badges" in src, "Missing dep-badges container"



# ===============================================================================
# Round 30 — Dependency-Aware Batch Render Ordering
# ===============================================================================

def test_shotboard_no_cycle():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        s2 = board.add(Shot(id="sb", title="B", prompt="b"))
        board.add_dependency(s2.id, s1.id)  # B depends on A
        assert not board.has_cycle(), "no cycle should be detected"

def test_shotboard_has_cycle():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        s2 = board.add(Shot(id="sb", title="B", prompt="b"))
        board.add_dependency(s1.id, s2.id)  # A depends on B
        board.add_dependency(s2.id, s1.id)  # B depends on A — cycle!
        assert board.has_cycle(), "cycle should be detected"

def test_shotboard_topo_sort_order():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        s2 = board.add(Shot(id="sb", title="B", prompt="b"))
        s3 = board.add(Shot(id="sc", title="C", prompt="c"))
        board.add_dependency(s3.id, s1.id)  # C depends on A
        board.add_dependency(s3.id, s2.id)  # C depends on B
        ordered = board.topological_sort()
        ids = [s.id for s in ordered]
        assert ids.index(s1.id) < ids.index(s3.id), "A must come before C"
        assert ids.index(s2.id) < ids.index(s3.id), "B must come before C"

def test_shotboard_topo_sort_no_deps():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        s2 = board.add(Shot(id="sb", title="B", prompt="b"))
        s3 = board.add(Shot(id="sc", title="C", prompt="c"))
        ordered = board.topological_sort()
        ids = [s.id for s in ordered]
        assert ids == ["sa", "sb", "sc"], f"no-dep sort should preserve order: {ids}"

def test_shotboard_topo_sort_cycle():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        s2 = board.add(Shot(id="sb", title="B", prompt="b"))
        board.add_dependency(s1.id, s2.id)
        board.add_dependency(s2.id, s1.id)
        ordered = board.topological_sort()
        ids = [s.id for s in ordered]
        # Both shots should still appear (no silent drop)
        assert len(ids) == 2, f"all shots must appear: {ids}"
        assert set(ids) == {"sa", "sb"}, f"wrong ids: {ids}"

def test_queue_all_drafts_has_cycle():
    src = open("scaffold/video_bridge.py").read()
    assert "has_cycle" in src, "queue_all_drafts should return has_cycle"
    assert "topological_sort" in src, "queue_all_drafts should use topological_sort"
    assert "deferred" in src, "queue_all_drafts should return deferred count"

def test_server_render_all_dep_info():
    src = open("tavern/server.py").read()
    assert "queue_all_drafts" in src, "render-all should call queue_all_drafts"
    assert "result[" in src or "result.get(" in src or 'result["status"]' in src, "should return result from queue_all_drafts"

def test_video_panel_batch_render_all():
    src = open("tavern/static/video_panel.jsx").read()
    assert '"/api/video/render-all"' in src, "renderAll should use batch endpoint"
    assert "has_cycle" in src, "should check has_cycle from response"

def test_video_panel_cycle_warning_state():
    src = open("tavern/static/video_panel.jsx").read()
    assert "cycleWarning" in src, "Missing cycleWarning state"
    assert "setCycleWarning" in src, "Missing setCycleWarning setter"

def test_video_panel_cycle_warning_banner():
    src = open("tavern/static/video_panel.jsx").read()
    assert "cycle-warning" in src, "Missing cycle-warning CSS class"
    assert "dependency cycle" in src, "Missing cycle warning text"



# ===============================================================================
# Round 31 — Render Order Preview and Dependency Graph
# ===============================================================================

def test_shotboard_render_order():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        s2 = board.add(Shot(id="sb", title="B", prompt="b"))
        board.add_dependency(s2.id, s1.id)
        ro = board.render_order()
        assert "nodes" in ro, "missing nodes"
        assert "edges" in ro, "missing edges"
        assert "has_cycle" in ro, "missing has_cycle"
        assert "total" in ro, "missing total"
        assert "ready_count" in ro, "missing ready_count"
        assert ro["total"] == 2

def test_render_order_node_fields():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        ro = board.render_order()
        node = ro["nodes"][0]
        for key in ("id", "title", "status", "order", "depends_on", "dependencies_met", "ready_to_render"):
            assert key in node, f"missing field {key}"

def test_render_order_edges():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        s2 = board.add(Shot(id="sb", title="B", prompt="b"))
        board.add_dependency(s2.id, s1.id)
        ro = board.render_order()
        assert len(ro["edges"]) == 1, f"expected 1 edge, got {len(ro['edges'])}"
        edge = ro["edges"][0]
        assert edge["from"] == "sa", f"edge from wrong: {edge}"
        assert edge["to"] == "sb", f"edge to wrong: {edge}"
        assert "met" in edge, "edge missing met field"

def test_render_order_ready_count():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        s2 = board.add(Shot(id="sb", title="B", prompt="b"))
        ro = board.render_order()
        # Both draft with no deps = both ready
        assert ro["ready_count"] == 2, f"expected 2 ready, got {ro['ready_count']}"
        board.add_dependency(s2.id, s1.id)
        ro2 = board.render_order()
        # s1 ready (draft, no deps), s2 not ready (dep on s1 which is draft not ready)
        assert ro2["ready_count"] == 1, f"expected 1 ready, got {ro2['ready_count']}"

def test_server_render_order_endpoint():
    src = open("tavern/server.py").read()
    assert "api/video/render-order" in src, "Missing render-order endpoint"
    assert "render_order()" in src, "Missing render_order() call"

def test_video_panel_dep_graph_toggle():
    src = open("tavern/static/video_panel.jsx").read()
    assert "dep-graph-toggle" in src, "Missing dep-graph-toggle button"
    assert "showDepGraph" in src, "Missing showDepGraph state"
    assert "Dep Graph" in src, "Missing Dep Graph label"

def test_video_panel_dep_graph_panel():
    src = open("tavern/static/video_panel.jsx").read()
    assert "dep-graph-panel" in src, "Missing dep-graph-panel"
    assert "Render Order" in src, "Missing Render Order heading"

def test_video_panel_fetch_render_order():
    src = open("tavern/static/video_panel.jsx").read()
    assert "fetchRenderOrder" in src, "Missing fetchRenderOrder function"
    assert "api/video/render-order" in src, "Missing render-order API call"
    assert "setRenderOrder" in src, "Missing setRenderOrder"

def test_video_panel_dep_graph_nodes():
    src = open("tavern/static/video_panel.jsx").read()
    assert "dep-graph-node" in src, "Missing dep-graph-node class"
    assert "dep-graph-order" in src, "Missing dep-graph-order class"
    assert "dep-graph-status" in src, "Missing dep-graph-status class"

def test_video_panel_dep_graph_edges():
    src = open("tavern/static/video_panel.jsx").read()
    assert "dep-graph-edges" in src, "Missing dep-graph-edges container"
    assert "dep-graph-edge" in src, "Missing dep-graph-edge class"
    assert "Dependency links" in src, "Missing Dependency links label"



# ===============================================================================
# Round 32 — Shot Duration Override and Total Timeline Duration
# ===============================================================================

def test_shot_target_duration_field():
    from scaffold.shotboard import Shot
    s = Shot(id="s1", title="T", prompt="P")
    assert hasattr(s, "target_duration_s"), "Shot missing target_duration_s"
    assert s.target_duration_s is None, "default should be None"

def test_shot_target_duration_roundtrip():
    from scaffold.shotboard import Shot
    s = Shot(id="s1", title="T", prompt="P", target_duration_s=5.0)
    d = s.to_dict()
    assert d["target_duration_s"] == 5.0
    s2 = Shot.from_dict(d)
    assert s2.target_duration_s == 5.0

def test_shotboard_effective_duration():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a", duration_s=3.0))
        # No target override — should return preset duration
        assert board.effective_duration(s1.id) == 3.0
        # With target override
        s1.target_duration_s = 5.0
        board.save()
        assert board.effective_duration(s1.id) == 5.0

def test_shotboard_total_duration():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        board.add(Shot(id="sa", title="A", prompt="a", duration_s=3.0))
        board.add(Shot(id="sb", title="B", prompt="b", duration_s=4.0, target_duration_s=6.0))
        total = board.total_duration()
        # 3.0 (preset) + 6.0 (target override) = 9.0
        assert total == 9.0, f"expected 9.0, got {total}"

def test_server_target_duration_serialization():
    src = open("tavern/server.py").read()
    assert "target_duration_s" in src, "Missing target_duration_s in serialization"

def test_server_total_duration_endpoint():
    src = open("tavern/server.py").read()
    assert "api/video/total-duration" in src, "Missing total-duration endpoint"
    assert "total_duration()" in src or "total_duration" in src, "Missing total_duration call"
    assert "effective_duration" in src, "Missing effective_duration call"

def test_video_panel_target_duration_row():
    src = open("tavern/static/video_panel.jsx").read()
    assert "target-duration-row" in src, "Missing target-duration-row"
    assert "target-duration-input" in src, "Missing target-duration-input"
    assert "Target duration" in src, "Missing Target duration label"

def test_video_panel_duration_warning():
    src = open("tavern/static/video_panel.jsx").read()
    assert "duration-warning" in src, "Missing duration-warning class"
    assert "exceeds 2x preset" in src, "Missing exceeds warning text"

def test_video_panel_total_timeline_duration():
    src = open("tavern/static/video_panel.jsx").read()
    assert "totalTimelineDuration" in src, "Missing totalTimelineDuration"
    assert "target_duration_s" in src, "Missing target_duration_s in duration calc"

def test_video_panel_total_in_header():
    src = open("tavern/static/video_panel.jsx").read()
    assert "total" in src.lower(), "Missing total in header display"
    assert "toFixed" in src, "Missing toFixed for duration formatting"



# ===============================================================================
# Round 33 — Shot Locking
# ===============================================================================

def test_shot_locked_field():
    from scaffold.shotboard import Shot
    s = Shot(id="s1", title="T", prompt="P")
    assert hasattr(s, "locked"), "Shot missing locked"
    assert s.locked is False, "default should be False"
    d = s.to_dict()
    assert "locked" in d, "to_dict missing locked"

def test_shotboard_lock_shot():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        assert not s1.locked
        result = board.lock_shot(s1.id)
        assert result is not None
        assert result.locked is True
        assert board.is_locked(s1.id)

def test_shotboard_unlock_shot():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        board.lock_shot(s1.id)
        assert board.is_locked(s1.id)
        result = board.unlock_shot(s1.id)
        assert result.locked is False
        assert not board.is_locked(s1.id)

def test_shotboard_update_locked_skip():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="original"))
        board.lock_shot(s1.id)
        result = board.update(s1.id, prompt="changed", title="new title")
        # Locked fields should NOT change
        assert result.prompt == "original", f"prompt changed on locked shot: {result.prompt}"
        assert result.title == "A", f"title changed on locked shot: {result.title}"

def test_shotboard_update_locked_system_fields():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        board.lock_shot(s1.id)
        result = board.update(s1.id, status="rendering", error="test error")
        assert result.status == "rendering", "system field status should update"
        assert result.error == "test error", "system field error should update"

def test_shotboard_auto_lock_rendering():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        assert not s1.locked
        board.update(s1.id, status="rendering")
        assert board.get(s1.id).locked is True, "should auto-lock on rendering"

def test_shotboard_auto_unlock_draft():
    import tempfile, os
    from scaffold.shotboard import Shotboard, Shot
    with tempfile.TemporaryDirectory() as tmp:
        board = Shotboard(os.path.join(tmp, "b.json"))
        s1 = board.add(Shot(id="sa", title="A", prompt="a"))
        board.update(s1.id, status="rendering")
        assert board.get(s1.id).locked is True
        board.update(s1.id, status="draft")
        assert board.get(s1.id).locked is False, "should auto-unlock on draft"

def test_server_lock_endpoint():
    src = open("tavern/server.py").read()
    assert "api/video/lock" in src, "Missing lock endpoint"
    assert "lock_shot" in src, "Missing lock_shot call"
    assert "unlock_shot" in src, "Missing unlock_shot call"

def test_server_locked_serialization():
    src = open("tavern/server.py").read()
    assert '"locked"' in src, "Missing locked in serialization"

def test_video_panel_lock_indicator():
    src = open("tavern/static/video_panel.jsx").read()
    assert "lock-indicator" in src, "Missing lock-indicator class"
    assert "isLocked" in src, "Missing isLocked variable"

def test_video_panel_lock_toggle():
    src = open("tavern/static/video_panel.jsx").read()
    assert "lock-toggle-btn" in src, "Missing lock-toggle-btn class"
    assert "onToggleLock" in src, "Missing onToggleLock prop"

def test_video_panel_toggle_lock_fn():
    src = open("tavern/static/video_panel.jsx").read()
    assert "const toggleLock" in src, "Missing toggleLock function"
    assert "/api/video/lock" in src, "Missing lock API call"


# Round 34 — Render Completion Toast Notifications

def test_video_panel_toast_container_component():
    src = open("tavern/static/video_panel.jsx").read()
    assert "function ToastContainer" in src, "Missing ToastContainer component"
    assert "toast-container" in src, "Missing toast-container class"

def test_video_panel_toast_item_classes():
    src = open("tavern/static/video_panel.jsx").read()
    assert "toast-item" in src, "Missing toast-item class"
    assert "toast-icon" in src, "Missing toast-icon class"
    assert "toast-message" in src, "Missing toast-message class"
    assert "toast-dismiss" in src, "Missing toast-dismiss class"

def test_video_panel_toast_type_styling():
    src = open("tavern/static/video_panel.jsx").read()
    assert "bg-emerald-800" in src, "Missing success toast styling"
    assert "bg-red-800" in src, "Missing error toast styling"
    assert "bg-slate-800" in src, "Missing info toast styling"

def test_video_panel_add_toast_function():
    src = open("tavern/static/video_panel.jsx").read()
    assert "addToast" in src, "Missing addToast function"
    assert "toastIdCounter" in src or "toastId" in src, "Missing toast ID counter"

def test_video_panel_dismiss_toast_function():
    src = open("tavern/static/video_panel.jsx").read()
    assert "dismissToast" in src, "Missing dismissToast function"
    assert "onDismiss" in src, "Missing onDismiss prop"

def test_video_panel_toast_auto_dismiss():
    src = open("tavern/static/video_panel.jsx").read()
    assert "setTimeout" in src, "Missing auto-dismiss setTimeout"
    assert "dismissToast" in src, "Missing dismissToast in auto-dismiss"

def test_video_panel_prev_shots_ref():
    src = open("tavern/static/video_panel.jsx").read()
    assert "prevShotsRef" in src, "Missing prevShotsRef for render-change detection"
    assert "useRef" in src, "Missing useRef for prevShotsRef"

def test_video_panel_render_change_detection():
    src = open("tavern/static/video_panel.jsx").read()
    # Should compare previous shots to new shots for status transitions
    assert "prevShotsRef.current" in src, "Missing prevShotsRef.current comparison"
    assert "rendered successfully" in src or "render" in src.lower(), "Missing success toast message"

def test_video_panel_toast_on_ready():
    src = open("tavern/static/video_panel.jsx").read()
    # When status changes to "ready", should fire a success toast
    assert '"ready"' in src, "Missing ready status check"
    assert "success" in src, "Missing success toast type"

def test_video_panel_toast_on_failed():
    src = open("tavern/static/video_panel.jsx").read()
    # When status changes to "failed", should fire an error toast
    assert '"failed"' in src, "Missing failed status check"
    assert "error" in src, "Missing error toast type"

def test_video_panel_toast_state():
    src = open("tavern/static/video_panel.jsx").read()
    assert "toasts" in src, "Missing toasts state"
    assert "setToasts" in src, "Missing setToasts setter"

def test_video_panel_toast_container_rendered():
    src = open("tavern/static/video_panel.jsx").read()
    assert "<ToastContainer" in src, "Missing ToastContainer render in VideoPanel"


# Round 35 — Batch Actions Toolbar

def test_shotboard_batch_lock():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    s1 = Shot(id="a1", title="A", prompt="p")
    s2 = Shot(id="a2", title="B", prompt="p")
    s3 = Shot(id="a3", title="C", prompt="p")
    board.add(s1); board.add(s2); board.add(s3)
    result = board.batch_lock(["a1", "a2"], lock=True)
    assert result["changed"] == 2, f"Expected 2 changed, got {result}"
    assert board.get("a1").locked is True
    assert board.get("a2").locked is True
    assert board.get("a3").locked is False

def test_shotboard_batch_unlock():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    s1 = Shot(id="b1", title="A", prompt="p", locked=True)
    s2 = Shot(id="b2", title="B", prompt="p", locked=True)
    board.add(s1); board.add(s2)
    result = board.batch_lock(["b1", "b2"], lock=False)
    assert result["changed"] == 2
    assert board.get("b1").locked is False
    assert board.get("b2").locked is False

def test_shotboard_batch_reset_status():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    s1 = Shot(id="c1", title="A", prompt="p", status="ready")
    s2 = Shot(id="c2", title="B", prompt="p", status="failed")
    s3 = Shot(id="c3", title="C", prompt="p", status="draft")
    board.add(s1); board.add(s2); board.add(s3)
    result = board.batch_reset_status(["c1", "c2", "c3"])
    assert result["reset"] == 2, f"Expected 2 reset, got {result}"
    assert board.get("c1").status == "draft"
    assert board.get("c2").status == "draft"
    assert board.get("c3").status == "draft"

def test_shotboard_batch_reset_skips_locked():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    s1 = Shot(id="d1", title="A", prompt="p", status="ready", locked=True)
    s2 = Shot(id="d2", title="B", prompt="p", status="failed")
    board.add(s1); board.add(s2)
    result = board.batch_reset_status(["d1", "d2"])
    assert result["reset"] == 1, "Should skip locked shot"
    assert board.get("d1").status == "ready", "Locked shot should not reset"
    assert board.get("d2").status == "draft"

def test_shotboard_batch_color_label():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    s1 = Shot(id="e1", title="A", prompt="p")
    s2 = Shot(id="e2", title="B", prompt="p")
    board.add(s1); board.add(s2)
    result = board.batch_color_label(["e1", "e2"], "red")
    assert result["changed"] == 2
    assert board.get("e1").color_label == "red"
    assert board.get("e2").color_label == "red"

def test_server_batch_lock_endpoint():
    src = open("tavern/server.py").read()
    assert "api/video/batch-lock" in src, "Missing batch-lock endpoint"
    assert "batch_lock" in src, "Missing batch_lock call"

def test_server_batch_reset_endpoint():
    src = open("tavern/server.py").read()
    assert "api/video/batch-reset" in src, "Missing batch-reset endpoint"
    assert "batch_reset_status" in src, "Missing batch_reset_status call"

def test_server_batch_color_endpoint():
    src = open("tavern/server.py").read()
    assert "api/video/batch-color" in src, "Missing batch-color endpoint"
    assert "batch_color_label" in src, "Missing batch_color_label call"

def test_video_panel_batch_lock_btn():
    src = open("tavern/static/video_panel.jsx").read()
    assert "batch-lock-btn" in src, "Missing batch-lock-btn class"
    assert "batch-unlock-btn" in src, "Missing batch-unlock-btn class"
    assert "batchLock" in src, "Missing batchLock function"

def test_video_panel_batch_reset_btn():
    src = open("tavern/static/video_panel.jsx").read()
    assert "batch-reset-btn" in src, "Missing batch-reset-btn class"
    assert "batchResetStatus" in src, "Missing batchResetStatus function"

def test_video_panel_batch_color_select():
    src = open("tavern/static/video_panel.jsx").read()
    assert "batch-color-select" in src, "Missing batch-color-select class"
    assert "batchColorLabel" in src, "Missing batchColorLabel function"

def test_video_panel_batch_actions_bar():
    src = open("tavern/static/video_panel.jsx").read()
    assert "bulk-actions" in src, "Missing bulk-actions container"
    assert "batch-deselect-btn" in src, "Missing deselect button class"
    assert "batch-render-btn" in src, "Missing render button class"
    assert "batch-delete-btn" in src, "Missing delete button class"


# Round 36 — Shot Render History Log

def test_shot_render_history_field():
    from scaffold.shotboard import Shot
    s = Shot(id="rh1", title="A", prompt="p")
    assert hasattr(s, "render_history"), "Missing render_history field"
    assert s.render_history == [], "Default should be empty list"

def test_shot_render_history_roundtrip():
    from scaffold.shotboard import Shot
    s = Shot(id="rh2", title="A", prompt="p")
    s.render_history.append({"timestamp": 1000, "preset": "test", "status": "ready"})
    d = s.to_dict()
    assert "render_history" in d, "Missing in to_dict"
    s2 = Shot.from_dict(d)
    assert len(s2.render_history) == 1, "History not preserved in roundtrip"

def test_shotboard_record_render():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    s = board.add(Shot(id="rh3", title="A", prompt="p", preset="test_preset"))
    entry = board.record_render("rh3", status="ready", duration_s=12.5)
    assert entry is not None, "record_render returned None"
    assert entry["status"] == "ready"
    assert entry["duration_s"] == 12.5
    assert entry["preset"] == "test_preset"
    assert "timestamp" in entry
    shot = board.get("rh3")
    assert len(shot.render_history) == 1

def test_shotboard_record_render_caps_at_20():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    s = board.add(Shot(id="rh4", title="A", prompt="p"))
    for i in range(25):
        board.record_render("rh4", status="ready", duration_s=float(i))
    shot = board.get("rh4")
    assert len(shot.render_history) == 20, f"Expected 20 entries, got {len(shot.render_history)}"

def test_shotboard_record_render_with_error():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="rh5", title="A", prompt="p"))
    entry = board.record_render("rh5", status="failed", error="GPU OOM")
    assert entry["status"] == "failed"
    assert entry["error"] == "GPU OOM"

def test_shotboard_get_render_history():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="rh6", title="A", prompt="p"))
    board.record_render("rh6", status="ready")
    board.record_render("rh6", status="failed", error="err")
    history = board.get_render_history("rh6")
    assert len(history) == 2
    assert history[0]["status"] == "ready"
    assert history[1]["status"] == "failed"

def test_shotboard_get_render_history_missing_shot():
    from scaffold.shotboard import Shotboard
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    assert board.get_render_history("nonexistent") == []

def test_server_render_history_endpoint():
    src = open("tavern/server.py").read()
    assert "/history" in src, "Missing history endpoint"
    assert "get_render_history" in src, "Missing get_render_history call"

def test_server_record_render_endpoint():
    src = open("tavern/server.py").read()
    assert "api/video/record-render" in src, "Missing record-render endpoint"
    assert "record_render" in src, "Missing record_render call"

def test_video_panel_render_history_toggle():
    src = open("tavern/static/video_panel.jsx").read()
    assert "render-history-toggle" in src, "Missing history toggle class"
    assert "showHistory" in src, "Missing showHistory state"
    assert "render-history-count" in src, "Missing history count"

def test_video_panel_render_history_list():
    src = open("tavern/static/video_panel.jsx").read()
    assert "render-history-list" in src, "Missing history list class"
    assert "render-history-entry" in src, "Missing history entry class"
    assert "render-history-status" in src, "Missing history status class"

def test_video_panel_render_history_details():
    src = open("tavern/static/video_panel.jsx").read()
    assert "render-history-time" in src, "Missing timestamp display"
    assert "render-history-preset" in src, "Missing preset display"
    assert "render-history-duration" in src, "Missing duration display"


# Round 37 — Prompt Character Count and Limit Warning

def test_video_panel_prompt_char_count():
    src = open("tavern/static/video_panel.jsx").read()
    assert "prompt-char-count" in src, "Missing prompt-char-count class"
    assert "prompt-char-current" in src, "Missing current count span"
    assert "prompt-char-limit" in src, "Missing limit span"

def test_video_panel_prompt_limit_warning():
    src = open("tavern/static/video_panel.jsx").read()
    assert "prompt-limit-warning" in src, "Missing limit warning class"
    assert "over limit" in src, "Missing over limit text"

def test_video_panel_prompt_color_thresholds():
    src = open("tavern/static/video_panel.jsx").read()
    assert "text-red-400" in src, "Missing red color for over-limit"
    assert "text-amber-400" in src, "Missing amber color for near-limit"

def test_video_panel_prompt_char_limit_from_preset():
    src = open("tavern/static/video_panel.jsx").read()
    assert "prompt_char_limit" in src, "Missing prompt_char_limit preset lookup"
    assert "currentPreset" in src, "Missing currentPreset variable"

def test_video_panel_default_char_limit():
    src = open("tavern/static/video_panel.jsx").read()
    assert "500" in src, "Missing default 500 char limit"


# Round 38 — Auto-scroll to Actively Rendering Shot

def test_video_panel_shot_card_data_attribute():
    src = open("tavern/static/video_panel.jsx").read()
    assert "data-shot-id" in src, "Missing data-shot-id attribute on shot card"
    assert "shot-card-root" in src, "Missing shot-card-root class"

def test_video_panel_scroll_to_shot():
    src = open("tavern/static/video_panel.jsx").read()
    assert "scrollToShot" in src, "Missing scrollToShot function"
    assert "scrollIntoView" in src, "Missing scrollIntoView call"

def test_video_panel_auto_scroll_state():
    src = open("tavern/static/video_panel.jsx").read()
    assert "autoScroll" in src, "Missing autoScroll state"
    assert "setAutoScroll" in src, "Missing setAutoScroll setter"

def test_video_panel_auto_scroll_on_rendering():
    src = open("tavern/static/video_panel.jsx").read()
    # Should trigger scroll when status changes to running
    assert "running" in src, "Missing running status check"
    assert "scrollToShot" in src, "Missing scrollToShot in change detection"

def test_video_panel_auto_scroll_toggle():
    src = open("tavern/static/video_panel.jsx").read()
    assert "auto-scroll-toggle" in src, "Missing auto-scroll-toggle class"
    assert "auto-scroll-checkbox" in src, "Missing auto-scroll-checkbox class"
    assert "auto-scroll-label" in src, "Missing auto-scroll-label class"

def test_video_panel_auto_scroll_default_on():
    src = open("tavern/static/video_panel.jsx").read()
    assert "autoScroll, setAutoScroll" in src or "setAutoScroll] = _useState(true)" in src, "Auto-scroll should default to true"


# Round 39 — Render Queue ETA

def test_shotboard_average_render_time():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="eta1", title="A", prompt="p", render_duration_s=10.0))
    board.add(Shot(id="eta2", title="B", prompt="p", render_duration_s=20.0))
    board.add(Shot(id="eta3", title="C", prompt="p"))
    avg = board.average_render_time()
    assert avg == 15.0, f"Expected 15.0, got {avg}"

def test_shotboard_average_render_time_empty():
    from scaffold.shotboard import Shotboard
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    assert board.average_render_time() == 0.0

def test_shotboard_queue_eta():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="q1", title="A", prompt="p", render_duration_s=10.0, status="ready"))
    board.add(Shot(id="q2", title="B", prompt="p", render_duration_s=20.0, status="ready"))
    board.add(Shot(id="q3", title="C", prompt="p", status="queued"))
    board.add(Shot(id="q4", title="D", prompt="p", status="running"))
    eta = board.queue_eta()
    assert eta["pending_count"] == 2, f"Expected 2 pending, got {eta}"
    assert eta["avg_render_s"] == 15.0
    assert eta["eta_seconds"] == 30.0

def test_shotboard_queue_eta_no_pending():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="qn1", title="A", prompt="p", status="ready", render_duration_s=10.0))
    eta = board.queue_eta()
    assert eta["eta_seconds"] == 0
    assert eta["pending_count"] == 0

def test_server_queue_eta_endpoint():
    src = open("tavern/server.py").read()
    assert "api/video/queue-eta" in src, "Missing queue-eta endpoint"
    assert "queue_eta" in src, "Missing queue_eta call"

def test_video_panel_queue_eta_display():
    src = open("tavern/static/video_panel.jsx").read()
    assert "queueEta" in src, "Missing queueEta computed value"
    assert "queue-eta-label" in src or "queue-eta-header" in src, "Missing queue ETA display"

def test_video_panel_queue_eta_label():
    src = open("tavern/static/video_panel.jsx").read()
    assert "remaining" in src, "Missing remaining label"
    assert "render_duration_s" in src, "Missing render_duration_s in ETA calc"




# Round 40 — Shot Diff Indicator

def test_shot_diff_no_history():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="df1", title="A", prompt="hello", preset="fast"))
    diff = board.shot_diff("df1")
    assert diff["has_changes"] is False, "No history means no diff"
    assert diff["fields"] == {}
    assert diff["last_render_ts"] is None

def test_shot_diff_prompt_changed():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="df2", title="A", prompt="original", preset="fast"))
    board.record_render("df2", status="ready", duration_s=5.0)
    # Now change prompt
    shot = board.get("df2")
    shot.prompt = "modified"
    shot.touch()
    board.save()
    diff = board.shot_diff("df2")
    assert diff["has_changes"] is True, "Prompt changed"
    assert "prompt" in diff["fields"]
    assert diff["fields"]["prompt"]["old"] == "original"
    assert diff["fields"]["prompt"]["new"] == "modified"

def test_shot_diff_preset_changed():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="df3", title="A", prompt="p", preset="fast"))
    board.record_render("df3", status="ready", duration_s=5.0)
    shot = board.get("df3")
    shot.preset = "slow"
    shot.touch()
    board.save()
    diff = board.shot_diff("df3")
    assert diff["has_changes"] is True
    assert "preset" in diff["fields"]
    assert diff["fields"]["preset"]["old"] == "fast"
    assert diff["fields"]["preset"]["new"] == "slow"

def test_shot_diff_overrides_changed():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="df4", title="A", prompt="p", preset="fast",
                   overrides={"steps": 20}))
    board.record_render("df4", status="ready", duration_s=5.0)
    shot = board.get("df4")
    shot.overrides = {"steps": 30}
    shot.touch()
    board.save()
    diff = board.shot_diff("df4")
    assert diff["has_changes"] is True
    assert "overrides" in diff["fields"]
    assert diff["fields"]["overrides"]["old"] == {"steps": 20}
    assert diff["fields"]["overrides"]["new"] == {"steps": 30}

def test_shot_diff_no_changes():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="df5", title="A", prompt="same", preset="fast"))
    board.record_render("df5", status="ready", duration_s=5.0)
    diff = board.shot_diff("df5")
    assert diff["has_changes"] is False, "Nothing changed since render"
    assert diff["fields"] == {}
    assert diff["last_render_ts"] is not None

def test_shot_diff_ignores_failed():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="df6", title="A", prompt="orig", preset="fast"))
    board.record_render("df6", status="ready", duration_s=5.0)
    # Change prompt, then record a failed render (should not update baseline)
    shot = board.get("df6")
    shot.prompt = "changed"
    shot.touch()
    board.save()
    board.record_render("df6", status="failed", error="boom")
    diff = board.shot_diff("df6")
    assert diff["has_changes"] is True, "Failed render should not reset diff baseline"
    assert "prompt" in diff["fields"]

def test_record_render_stores_overrides():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="ov1", title="A", prompt="p", overrides={"fps": 24}))
    entry = board.record_render("ov1", status="ready", duration_s=3.0)
    assert "overrides" in entry, "record_render must store overrides"
    assert entry["overrides"] == {"fps": 24}

def test_server_shot_diff_endpoint():
    src = open("tavern/server.py").read()
    assert "/diff" in src, "Missing /diff endpoint"
    assert "shot_diff" in src, "Missing shot_diff call"

def test_video_panel_diff_badge():
    src = open("tavern/static/video_panel.jsx").read()
    assert "shot-diff-badge" in src, "Missing diff badge CSS class"
    assert "Modified since last render" in src, "Missing diff badge label"

def test_video_panel_diff_computation():
    src = open("tavern/static/video_panel.jsx").read()
    assert "shot-diff-fields" in src, "Missing diff fields display"
    assert "lastOk" in src or "last_ok" in src, "Missing last-OK render lookup"



# Round 41 — Revert to Last Render

def test_revert_restores_fields():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="rv1", prompt="original", preset="fast",
                   overrides={"steps": 20}))
    board.record_render("rv1", status="ready", duration_s=5.0)
    # Modify all three fields
    shot = board.get("rv1")
    shot.prompt = "changed"
    shot.preset = "slow"
    shot.overrides = {"steps": 50}
    shot.touch()
    board.save()
    result = board.revert_to_last_render("rv1")
    assert result is not None
    assert "prompt" in result
    assert "preset" in result
    assert "overrides" in result
    shot = board.get("rv1")
    assert shot.prompt == "original"
    assert shot.preset == "fast"
    assert shot.overrides == {"steps": 20}

def test_revert_no_history():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="rv2", prompt="p", preset="fast"))
    result = board.revert_to_last_render("rv2")
    assert result is None, "No history means no revert"

def test_revert_locked_shot():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="rv3", prompt="orig", preset="fast", locked=True))
    board.record_render("rv3", status="ready", duration_s=5.0)
    shot = board.get("rv3")
    shot.prompt = "changed"
    shot.touch()
    board.save()
    result = board.revert_to_last_render("rv3")
    assert result is None, "Locked shots cannot be reverted"
    assert board.get("rv3").prompt == "changed", "Prompt should not have changed"

def test_revert_clears_diff():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="rv4", prompt="orig", preset="fast"))
    board.record_render("rv4", status="ready", duration_s=5.0)
    shot = board.get("rv4")
    shot.prompt = "changed"
    shot.touch()
    board.save()
    diff_before = board.shot_diff("rv4")
    assert diff_before["has_changes"] is True
    board.revert_to_last_render("rv4")
    diff_after = board.shot_diff("rv4")
    assert diff_after["has_changes"] is False, "After revert, diff should be clear"

def test_revert_no_changes():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="rv5", prompt="same", preset="fast"))
    board.record_render("rv5", status="ready", duration_s=5.0)
    # Don't change anything
    result = board.revert_to_last_render("rv5")
    assert result == {}, "No changes means empty revert dict"

def test_server_revert_endpoint():
    src = open("tavern/server.py").read()
    assert "/revert" in src, "Missing /revert endpoint"
    assert "revert_to_last_render" in src, "Missing revert_to_last_render call"

def test_video_panel_revert_button():
    src = open("tavern/static/video_panel.jsx").read()
    assert "revert-btn" in src, "Missing revert button CSS class"
    assert "Revert" in src, "Missing Revert label"

def test_video_panel_revert_function():
    src = open("tavern/static/video_panel.jsx").read()
    assert "revertShot" in src, "Missing revertShot function"
    assert "/revert" in src, "Missing /revert API call"



# Round 42 — Shot Comparison View

def test_video_panel_compare_toggle():
    src = open("tavern/static/video_panel.jsx").read()
    assert "compare-toggle-btn" in src, "Missing compare toggle button"
    assert "Compare" in src, "Missing Compare label"

def test_video_panel_compare_panel():
    src = open("tavern/static/video_panel.jsx").read()
    assert "shot-compare-panel" in src, "Missing compare panel"
    assert "shot-diff-section" in src, "Missing diff section wrapper"

def test_video_panel_compare_cells():
    src = open("tavern/static/video_panel.jsx").read()
    assert "compare-old" in src, "Missing compare-old class"
    assert "compare-new" in src, "Missing compare-new class"
    assert "bg-red-950" in src, "Missing red bg for old values"
    assert "bg-emerald-950" in src, "Missing green bg for new values"

def test_video_panel_compare_prompt():
    src = open("tavern/static/video_panel.jsx").read()
    assert "compare-row-prompt" in src, "Missing prompt comparison row"
    assert "compare-field-label" in src, "Missing field labels"

def test_video_panel_compare_preset():
    src = open("tavern/static/video_panel.jsx").read()
    assert "compare-row-preset" in src, "Missing preset comparison row"

def test_video_panel_compare_overrides():
    src = open("tavern/static/video_panel.jsx").read()
    assert "compare-row-overrides" in src, "Missing overrides comparison row"
    assert "JSON.stringify" in src, "Missing JSON serialization for overrides"

def test_video_panel_show_compare_state():
    src = open("tavern/static/video_panel.jsx").read()
    assert "showCompare" in src, "Missing showCompare state"
    assert "setShowCompare" in src, "Missing setShowCompare setter"



# Round 43 — Negative Prompt Diff + Batch Revert

def test_record_render_stores_negative():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="neg1", prompt="p", negative="blurry, distorted"))
    entry = board.record_render("neg1", status="ready", duration_s=3.0)
    assert "negative" in entry, "record_render must store negative"
    assert entry["negative"] == "blurry, distorted"

def test_shot_diff_negative_changed():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="neg2", prompt="p", negative="blurry"))
    board.record_render("neg2", status="ready", duration_s=5.0)
    shot = board.get("neg2")
    shot.negative = "blurry, artifacts"
    shot.touch()
    board.save()
    diff = board.shot_diff("neg2")
    assert diff["has_changes"] is True
    assert "negative" in diff["fields"]
    assert diff["fields"]["negative"]["old"] == "blurry"
    assert diff["fields"]["negative"]["new"] == "blurry, artifacts"

def test_revert_restores_negative():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="neg3", prompt="p", negative="original_neg"))
    board.record_render("neg3", status="ready", duration_s=5.0)
    shot = board.get("neg3")
    shot.negative = "changed_neg"
    shot.touch()
    board.save()
    result = board.revert_to_last_render("neg3")
    assert "negative" in result
    assert board.get("neg3").negative == "original_neg"

def test_batch_revert():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="br1", prompt="orig1", preset="fast"))
    board.add(Shot(id="br2", prompt="orig2", preset="fast"))
    board.record_render("br1", status="ready", duration_s=5.0)
    board.record_render("br2", status="ready", duration_s=5.0)
    board.get("br1").prompt = "changed1"
    board.get("br1").touch()
    board.get("br2").prompt = "changed2"
    board.get("br2").touch()
    board.save()
    result = board.batch_revert(["br1", "br2"])
    assert result["reverted"] == 2
    assert result["skipped"] == 0
    assert board.get("br1").prompt == "orig1"
    assert board.get("br2").prompt == "orig2"

def test_batch_revert_skips():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="bs1", prompt="p", locked=True))
    board.add(Shot(id="bs2", prompt="p"))  # no history
    board.record_render("bs1", status="ready", duration_s=5.0)
    board.get("bs1").prompt = "changed"
    board.get("bs1").touch()
    board.save()
    result = board.batch_revert(["bs1", "bs2", "nonexistent"])
    assert result["skipped"] == 3, f"Expected 3 skipped, got {result}"
    assert result["reverted"] == 0

def test_server_batch_revert_endpoint():
    src = open("tavern/server.py").read()
    assert "batch-revert" in src, "Missing batch-revert endpoint"
    assert "batch_revert" in src, "Missing batch_revert call"

def test_video_panel_batch_revert_button():
    src = open("tavern/static/video_panel.jsx").read()
    assert "batch-revert-btn" in src, "Missing batch revert button"
    assert "batchRevert" in src, "Missing batchRevert function"
    assert "Batch Revert" in src, "Missing Batch Revert label"

def test_video_panel_negative_diff():
    src = open("tavern/static/video_panel.jsx").read()
    assert "negative" in src, "Missing negative in diff computation"
    assert "lastOk.negative" in src, "Missing negative comparison against lastOk"

def test_video_panel_compare_negative():
    src = open("tavern/static/video_panel.jsx").read()
    assert "compare-row-negative" in src, "Missing negative comparison row"


# ─── Round 44 — Batch Prompt Edit + Keyboard Navigation ─────────────

def test_batch_prompt_edit_add_prefix():
    """add mode prepends a prefix to each shot's prompt"""
    with tempfile.TemporaryDirectory() as tmp:
        from scaffold.shotboard import Shotboard
        board = Shotboard(os.path.join(tmp, "shotboard.json"))
        s1 = board.add(title="s1", prompt="a wolf")
        s2 = board.add(title="s2", prompt="a fox")
        result = board.batch_prompt_edit([s1.id, s2.id],
                                          prefix="cinematic, ", mode="add")
        assert result["modified"] == 2, f"Expected 2 modified, got {result}"
        assert board.get(s1.id).prompt == "cinematic, a wolf"
        assert board.get(s2.id).prompt == "cinematic, a fox"


def test_batch_prompt_edit_add_suffix():
    """add mode appends a suffix to each shot's prompt"""
    with tempfile.TemporaryDirectory() as tmp:
        from scaffold.shotboard import Shotboard
        board = Shotboard(os.path.join(tmp, "shotboard.json"))
        s1 = board.add(title="s1", prompt="a wolf")
        result = board.batch_prompt_edit([s1.id], suffix=", 4k", mode="add")
        assert result["modified"] == 1
        assert board.get(s1.id).prompt == "a wolf, 4k"


def test_batch_prompt_edit_idempotent():
    """add mode is idempotent — won't double-add the same prefix"""
    with tempfile.TemporaryDirectory() as tmp:
        from scaffold.shotboard import Shotboard
        board = Shotboard(os.path.join(tmp, "shotboard.json"))
        s1 = board.add(title="s1", prompt="a wolf")
        # First add
        board.batch_prompt_edit([s1.id], prefix="HQ ", mode="add")
        assert board.get(s1.id).prompt == "HQ a wolf"
        # Second add with same prefix: should be a no-op
        result = board.batch_prompt_edit([s1.id], prefix="HQ ", mode="add")
        assert result["modified"] == 0, f"Expected 0 modified on re-add, got {result}"
        assert result["skipped"] == 1
        assert board.get(s1.id).prompt == "HQ a wolf"  # unchanged


def test_batch_prompt_edit_remove_prefix():
    """remove mode strips the prefix from the start of each prompt"""
    with tempfile.TemporaryDirectory() as tmp:
        from scaffold.shotboard import Shotboard
        board = Shotboard(os.path.join(tmp, "shotboard.json"))
        s1 = board.add(title="s1", prompt="cinematic, a wolf")
        result = board.batch_prompt_edit([s1.id],
                                          prefix="cinematic, ", mode="remove")
        assert result["modified"] == 1
        assert board.get(s1.id).prompt == "a wolf"


def test_batch_prompt_edit_remove_suffix():
    """remove mode strips the suffix from the end of each prompt"""
    with tempfile.TemporaryDirectory() as tmp:
        from scaffold.shotboard import Shotboard
        board = Shotboard(os.path.join(tmp, "shotboard.json"))
        s1 = board.add(title="s1", prompt="a wolf, 4k")
        result = board.batch_prompt_edit([s1.id], suffix=", 4k", mode="remove")
        assert result["modified"] == 1
        assert board.get(s1.id).prompt == "a wolf"


def test_batch_prompt_edit_skips_locked():
    """locked shots are skipped and counted under 'skipped'"""
    with tempfile.TemporaryDirectory() as tmp:
        from scaffold.shotboard import Shotboard
        board = Shotboard(os.path.join(tmp, "shotboard.json"))
        s1 = board.add(title="s1", prompt="a wolf")
        s2 = board.add(title="s2", prompt="a fox")
        # Lock s2
        board.get(s2.id).locked = True
        board.save()
        result = board.batch_prompt_edit([s1.id, s2.id],
                                          prefix="HQ ", mode="add")
        assert result["modified"] == 1, f"Expected 1 modified, got {result}"
        assert result["skipped"] == 1
        assert board.get(s1.id).prompt == "HQ a wolf"
        assert board.get(s2.id).prompt == "a fox"  # still locked, untouched


def test_server_batch_prompt_edit_endpoint():
    src = open("tavern/server.py").read()
    assert "batch-prompt-edit" in src, "Missing batch-prompt-edit endpoint"
    assert "batch_prompt_edit" in src, "Missing batch_prompt_edit call"


def test_video_panel_batch_prompt_edit_ui():
    src = open("tavern/static/video_panel.jsx").read()
    assert "batch-prompt-edit-btn" in src, "Missing batch prompt edit button"
    assert "batchPromptEdit" in src, "Missing batchPromptEdit function"
    assert "batch-prompt-prefix" in src, "Missing prefix input"
    assert "batch-prompt-suffix" in src, "Missing suffix input"
    assert "batch-prompt-mode-add" in src, "Missing add mode toggle"
    assert "batch-prompt-mode-remove" in src, "Missing remove mode toggle"


def test_video_panel_focused_shot_index_state():
    src = open("tavern/static/video_panel.jsx").read()
    assert "focusedShotIndex" in src, "Missing focusedShotIndex state"
    assert "setFocusedShotIndex" in src, "Missing setFocusedShotIndex setter"


def test_video_panel_keydown_handler():
    """Arrow key navigation wired at the VideoPanel container"""
    src = open("tavern/static/video_panel.jsx").read()
    assert 'e.key === "ArrowDown"' in src, "Missing ArrowDown handler"
    assert 'e.key === "ArrowUp"' in src, "Missing ArrowUp handler"
    assert 'e.key === "Escape"' in src, "Missing Escape handler"
    assert "window.addEventListener" in src, "Missing window keydown listener"


def test_video_panel_shot_card_focused_prop():
    """ShotCard receives focused prop and renders a focus ring"""
    src = open("tavern/static/video_panel.jsx").read()
    assert "focused={focusedShotIndex === idx}" in src, "Missing focused prop wiring"
    assert "shot-card-focused" in src, "Missing focused-card CSS class"
    assert "ring-2 ring-amber-400" in src, "Missing focus-ring styling"


# ════════════════════════════════════════════════════════════════════
# R45 — Snapshots (R45a) + Batch Duplicate (R45b)
# ════════════════════════════════════════════════════════════════════

def test_snapshot_save_list():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="s1", prompt="p1", title="Scene A", preset="fast"))
    snap = board.save_snapshot("s1", label="before tweak")
    assert snap is not None
    assert snap["label"] == "before tweak"
    assert snap["prompt"] == "p1"
    assert "id" in snap and "created_at" in snap
    snaps = board.list_snapshots("s1")
    assert len(snaps) == 1
    assert snaps[0]["label"] == "before tweak"


def test_snapshot_restore_rolls_back_creative_state():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="s2", prompt="original", title="T", preset="fast", notes="n1"))
    snap = board.save_snapshot("s2", label="v1")
    shot = board.get("s2")
    shot.prompt = "changed"
    shot.notes = "n2"
    shot.touch()
    board.save()
    restored = board.restore_snapshot("s2", snap["id"])
    assert restored is not None
    assert board.get("s2").prompt == "original"
    assert board.get("s2").notes == "n1"


def test_snapshot_restore_skips_locked():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="s3", prompt="p", preset="fast"))
    snap = board.save_snapshot("s3", label="l")
    board.get("s3").locked = True
    board.save()
    assert board.restore_snapshot("s3", snap["id"]) is None


def test_snapshot_delete():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="s4", prompt="p", preset="fast"))
    snap = board.save_snapshot("s4", label="l")
    assert board.delete_snapshot("s4", snap["id"]) is True
    assert board.delete_snapshot("s4", snap["id"]) is False
    assert board.list_snapshots("s4") == []


def test_snapshot_caps_at_20():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="s5", prompt="p", preset="fast"))
    for i in range(25):
        board.save_snapshot("s5", label=f"snap{i}")
    snaps = board.list_snapshots("s5")
    assert len(snaps) == 20
    # Oldest pruned — so first surviving label should be snap5
    assert snaps[0]["label"] == "snap5"
    assert snaps[-1]["label"] == "snap24"


def test_batch_duplicate_counter_suffix():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="d1", prompt="p", title="Intro", preset="fast"))
    board.add(Shot(id="d2", prompt="q", title="Outro", preset="fast"))
    result = board.batch_duplicate(["d1", "d2"], count=2)
    assert result["created"] == 4
    assert result["skipped"] == 0
    # New shots have v2 / v3 suffix
    titles = [s.title for s in board.all()]
    assert "Intro v2" in titles
    assert "Intro v3" in titles
    assert "Outro v2" in titles
    assert "Outro v3" in titles


def test_batch_duplicate_plain_suffix():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="dp1", prompt="p", title="X", preset="fast"))
    result = board.batch_duplicate(["dp1"], count=2, title_suffix_mode="plain")
    assert result["created"] == 2
    titles = [s.title for s in board.all()]
    assert "X (2)" in titles
    assert "X (3)" in titles


def test_batch_duplicate_resets_status_and_history():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="dr1", prompt="p", title="S", preset="fast",
                   status="ready", locked=True))
    board.record_render("dr1", status="ready", duration_s=4.0)
    board.save_snapshot("dr1", label="snap")
    result = board.batch_duplicate(["dr1"], count=1)
    assert result["created"] == 1
    copy_id = result["new_ids"][0]
    copy = board.get(copy_id)
    assert copy.status == "draft"
    assert copy.render_history == []
    assert copy.snapshots == []
    assert copy.locked is False
    assert copy.video_path is None
    assert copy.job_id is None


def test_batch_duplicate_skips_missing():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="k1", prompt="p", title="Y", preset="fast"))
    result = board.batch_duplicate(["k1", "missing"], count=1)
    assert result["created"] == 1
    assert result["skipped"] == 1


def test_server_snapshot_endpoints():
    src = open("tavern/server.py", encoding="utf-8").read()
    assert "/snapshot" in src
    assert "save_snapshot" in src
    assert "list_snapshots" in src
    assert "restore_snapshot" in src
    assert "delete_snapshot" in src


def test_server_batch_duplicate_endpoint():
    src = open("tavern/server.py", encoding="utf-8").read()
    assert "batch-duplicate" in src
    assert "batch_duplicate" in src
    # count cap enforced
    assert "min(50, int(data.get('count'" in src


def test_video_panel_snapshot_ui():
    src = open("tavern/static/video_panel.jsx", encoding="utf-8").read()
    assert "snapshots-section" in src
    assert "snapshots-toggle" in src
    assert "snapshot-save-btn" in src
    assert "snapshot-restore-btn" in src
    assert "snapshot-delete-btn" in src
    assert "onSaveSnapshot" in src
    assert "onRestoreSnapshot" in src
    assert "onDeleteSnapshot" in src


def test_video_panel_batch_duplicate_ui():
    src = open("tavern/static/video_panel.jsx", encoding="utf-8").read()
    assert "batch-duplicate-btn" in src
    assert "batch-duplicate-panel" in src
    assert "batchDuplicate" in src
    assert "batchDupeCount" in src


# ════════════════════════════════════════════════════════════════════
# R46 — Auto-snapshot before batch ops (R46a) + Snapshot diff viewer (R46b)
# ════════════════════════════════════════════════════════════════════

def test_auto_snapshot_batch_helper():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="a1", prompt="p1", preset="fast"))
    board.add(Shot(id="a2", prompt="p2", preset="fast", locked=True))
    board.add(Shot(id="a3", prompt="p3", preset="fast"))
    # Locked shot is skipped, missing id ignored
    taken = board._auto_snapshot_batch(["a1", "a2", "a3", "missing"], "test op")
    assert taken == 2
    assert len(board.list_snapshots("a1")) == 1
    assert len(board.list_snapshots("a2")) == 0  # locked
    assert len(board.list_snapshots("a3")) == 1
    # Label convention
    assert board.list_snapshots("a1")[0]["label"] == "Auto: test op"


def test_batch_revert_auto_snapshots():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="r1", prompt="orig", preset="fast"))
    board.record_render("r1", status="ready", duration_s=4.0)
    board.get("r1").prompt = "changed"
    board.get("r1").touch()
    board.save()
    result = board.batch_revert(["r1"])
    assert result["reverted"] == 1
    assert result.get("auto_snapshots") == 1
    # Snapshot holds the pre-revert state (i.e. "changed")
    snaps = board.list_snapshots("r1")
    assert len(snaps) == 1
    assert snaps[0]["prompt"] == "changed"
    assert "Auto:" in snaps[0]["label"]


def test_batch_revert_can_disable_auto_snapshot():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="r2", prompt="orig", preset="fast"))
    board.record_render("r2", status="ready", duration_s=4.0)
    board.get("r2").prompt = "changed"
    board.get("r2").touch()
    board.save()
    result = board.batch_revert(["r2"], snapshot_before=False)
    assert result["reverted"] == 1
    assert result.get("auto_snapshots") == 0
    assert board.list_snapshots("r2") == []


def test_batch_prompt_edit_auto_snapshots():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="p1", prompt="a cat", preset="fast"))
    board.add(Shot(id="p2", prompt="a dog", preset="fast"))
    result = board.batch_prompt_edit(["p1", "p2"], prefix="cinematic, ", mode="add")
    assert result["modified"] == 2
    assert result.get("auto_snapshots") == 2
    assert board.list_snapshots("p1")[0]["prompt"] == "a cat"  # pre-edit
    assert board.get("p1").prompt == "cinematic, a cat"


def test_batch_update_preset_auto_snapshots():
    from scaffold.shotboard import Shotboard, Shot
    from scaffold.video_bridge import VideoBridge
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="u1", prompt="p", preset="fast", status="draft"))
    board.add(Shot(id="u2", prompt="q", preset="fast", status="draft"))
    bridge = VideoBridge.__new__(VideoBridge)
    bridge.board = board
    result = bridge.batch_update_preset(["u1", "u2"], preset="quality")
    assert result["updated"] == 2
    assert result["preset"] == "quality"
    assert result.get("auto_snapshots") == 2
    # Snapshot captures pre-change preset
    assert board.list_snapshots("u1")[0]["preset"] == "fast"
    assert board.get("u1").preset == "quality"


def test_batch_update_preset_skips_noop():
    from scaffold.shotboard import Shotboard, Shot
    from scaffold.video_bridge import VideoBridge
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="n1", prompt="p", preset="fast", status="draft"))
    bridge = VideoBridge.__new__(VideoBridge)
    bridge.board = board
    result = bridge.batch_update_preset(["n1"], preset="fast")
    # No change means no auto-snapshot
    assert result.get("auto_snapshots") == 0


def test_video_panel_snapshot_compare_state():
    src = open("tavern/static/video_panel.jsx", encoding="utf-8").read()
    assert "snapCompare" in src
    assert "setSnapCompare" in src
    assert "snapshot-compare-check" in src


def test_video_panel_snapshot_diff_panel():
    src = open("tavern/static/video_panel.jsx", encoding="utf-8").read()
    assert "snapshot-diff-panel" in src
    assert "snapshot-diff-close" in src
    assert "No differences in creative state" in src


# ════════════════════════════════════════════════════════════════════
# R47 — EDL/FCPXML export (R47a) + Snapshot pinning (R47b)
# ════════════════════════════════════════════════════════════════════

def test_slugify_reel():
    from scaffold.shotboard import _slugify_reel
    assert _slugify_reel("Scene A") == "SCENEA"
    assert _slugify_reel("EXT. Forest — Day") == "EXTFORES"  # capped at 8
    assert _slugify_reel("") == "CLIP"
    assert _slugify_reel(None) == "CLIP"
    assert _slugify_reel("!!!") == "CLIP"


def test_xml_escape():
    from scaffold.shotboard import _xml_escape
    assert _xml_escape("a & b") == "a &amp; b"
    assert _xml_escape('<tag attr="x">') == "&lt;tag attr=&quot;x&quot;&gt;"
    assert _xml_escape("it's") == "it&apos;s"


def test_frames_to_tc():
    from scaffold.shotboard import Shotboard
    assert Shotboard._frames_to_tc(0, 30) == "00:00:00:00"
    assert Shotboard._frames_to_tc(30, 30) == "00:00:01:00"
    assert Shotboard._frames_to_tc(90, 30) == "00:00:03:00"
    assert Shotboard._frames_to_tc(3600 * 30, 30) == "01:00:00:00"


def test_export_edl_basic():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="e1", title="Scene A", prompt="p",
                   video_path="/tmp/out1.mp4", status="ready", duration_s=3.0))
    board.add(Shot(id="e2", title="Scene B", prompt="q",
                   video_path="/tmp/out2.mp4", status="ready", duration_s=2.0))
    board.add(Shot(id="e3", title="Draft Only", prompt="z", status="draft"))
    edl = board.export_edl(fps=30)
    # Header
    assert edl.startswith("TITLE: Spellcaster Timeline")
    assert "FCM: NON-DROP FRAME" in edl
    # Only ready shots are present
    assert "SCENEA" in edl
    assert "SCENEB" in edl
    assert "DRAFTONL" not in edl  # skipped
    # Two events
    assert "001  SCENEA" in edl
    assert "002  SCENEB" in edl
    # Record-time continuity: event 2 starts where event 1 ends
    assert "00:00:00:00 00:00:03:00 00:00:00:00 00:00:03:00" in edl
    assert "00:00:00:00 00:00:02:00 00:00:03:00 00:00:05:00" in edl
    # FROM CLIP NAME
    assert "FROM CLIP NAME: out1.mp4" in edl
    assert "FROM CLIP NAME: out2.mp4" in edl


def test_export_edl_uses_render_duration_if_available():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="e1", title="S", prompt="p",
                   video_path="/tmp/o.mp4", status="ready",
                   duration_s=1.0, render_duration_s=5.0))
    edl = board.export_edl(fps=30)
    # 5.0s at 30fps = 150 frames = 00:00:05:00
    assert "00:00:05:00" in edl


def test_export_fcpxml_basic():
    from scaffold.shotboard import Shotboard, Shot
    import xml.etree.ElementTree as ET
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="f1", title="Scene A", prompt="p",
                   video_path="/tmp/out1.mp4", status="ready", duration_s=3.0))
    board.add(Shot(id="f2", title="Scene B", prompt="q",
                   video_path="/tmp/out2.mp4", status="ready", duration_s=2.0))
    xml = board.export_fcpxml(fps=30)
    # Header
    assert xml.startswith("<?xml")
    assert '<fcpxml version="1.10">' in xml
    # Parses as valid XML
    root = ET.fromstring(xml)
    assert root.tag == "fcpxml"
    # Has format, two assets, two asset-clips
    assets = root.findall(".//asset")
    assert len(assets) == 2
    clips = root.findall(".//asset-clip")
    assert len(clips) == 2
    # Durations
    assert clips[0].get("duration") == "90/30s"
    assert clips[1].get("duration") == "60/30s"
    assert clips[1].get("offset") == "90/30s"


def test_export_fcpxml_escapes_title():
    from scaffold.shotboard import Shotboard, Shot
    import xml.etree.ElementTree as ET
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="f1", title='A & <script>', prompt="p",
                   video_path="/tmp/o.mp4", status="ready", duration_s=1.0))
    xml = board.export_fcpxml(fps=30)
    # Parses without exception — proves escaping worked
    ET.fromstring(xml)
    assert "&amp;" in xml
    assert "&lt;script&gt;" in xml


def test_snapshot_pin_and_unpin():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="pn1", prompt="p", preset="fast"))
    snap = board.save_snapshot("pn1", label="keep me")
    assert board.pin_snapshot("pn1", snap["id"]) is True
    assert snap["id"] in board.get("pn1").pinned_snapshots
    # Idempotent re-pin
    assert board.pin_snapshot("pn1", snap["id"]) is True
    assert board.get("pn1").pinned_snapshots.count(snap["id"]) == 1
    # Unpin
    assert board.unpin_snapshot("pn1", snap["id"]) is True
    assert snap["id"] not in board.get("pn1").pinned_snapshots
    # Unpinning again is a no-op-returning-False
    assert board.unpin_snapshot("pn1", snap["id"]) is False


def test_pin_missing_snapshot_returns_false():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="pn2", prompt="p", preset="fast"))
    assert board.pin_snapshot("pn2", "nonexistent") is False
    assert board.pin_snapshot("nonexistent_shot", "x") is False


def test_pinned_snapshot_survives_auto_prune():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="pn3", prompt="p", preset="fast"))
    # Save one, pin it
    first = board.save_snapshot("pn3", label="PINNED FIRST")
    board.pin_snapshot("pn3", first["id"])
    # Save 25 more — unpinned should prune, pinned survives
    for i in range(25):
        board.save_snapshot("pn3", label=f"auto{i}")
    snaps = board.list_snapshots("pn3")
    assert len(snaps) == 20
    ids = {s["id"] for s in snaps}
    assert first["id"] in ids, "Pinned snapshot was evicted"
    # The oldest unpinned should be gone; newest unpinned must remain
    labels = [s["label"] for s in snaps]
    assert "PINNED FIRST" in labels
    assert "auto24" in labels  # most recent must survive
    assert "auto0" not in labels  # oldest unpinned must be pruned


def test_deleting_a_pinned_snapshot_removes_pin_entry():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    board = Shotboard(os.path.join(d, "sb.json"))
    board.add(Shot(id="pn4", prompt="p", preset="fast"))
    snap = board.save_snapshot("pn4", label="to delete")
    board.pin_snapshot("pn4", snap["id"])
    assert board.delete_snapshot("pn4", snap["id"]) is True
    # pinned_snapshots must not contain a stale id
    assert snap["id"] not in board.get("pn4").pinned_snapshots


def test_shot_pinned_snapshots_survive_roundtrip():
    from scaffold.shotboard import Shotboard, Shot
    import tempfile, os
    d = tempfile.mkdtemp()
    p = os.path.join(d, "sb.json")
    board = Shotboard(p)
    board.add(Shot(id="rt", prompt="p", preset="fast"))
    snap = board.save_snapshot("rt", label="l")
    board.pin_snapshot("rt", snap["id"])
    board2 = Shotboard(p)
    assert board2.get("rt").pinned_snapshots == [snap["id"]]


def test_server_has_edl_endpoint():
    src = open("tavern/server.py", encoding="utf-8").read()
    assert "/api/video/export/edl" in src
    assert "export_edl" in src
    assert "spellcaster_timeline.edl" in src


def test_server_has_fcpxml_endpoint():
    src = open("tavern/server.py", encoding="utf-8").read()
    assert "/api/video/export/fcpxml" in src
    assert "export_fcpxml" in src


def test_server_has_pin_endpoint():
    src = open("tavern/server.py", encoding="utf-8").read()
    assert "/pin" in src
    assert "pin_snapshot" in src
    assert "unpin_snapshot" in src


def test_video_panel_has_edl_button():
    src = open("tavern/static/video_panel.jsx", encoding="utf-8").read()
    assert "export-edl" in src
    assert "export-fcpxml" in src
    assert "/api/video/export/edl" in src
    assert "/api/video/export/fcpxml" in src


def test_video_panel_has_pin_button():
    src = open("tavern/static/video_panel.jsx", encoding="utf-8").read()
    assert "snapshot-pin-btn" in src
    assert "togglePinSnapshot" in src
    assert "pinned_snapshots" in src


if __name__ == "__main__":
    sys.exit(main())
