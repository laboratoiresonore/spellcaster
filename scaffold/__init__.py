"""Spellcaster scaffold package — LLM + Guild server helpers.

This package is imported piecemeal from `tavern/server.py` (not as a whole).
Each module is independent and carries its own public surface. Nothing
here is auto-re-exported; callers import the exact submodule they need.

Live submodules (as of 2026-04):
    introspector, workflow_parser, workflow_wizard (discover_workflows),
    meta_wizard (build_meta_system_prompt, INTENTS),
    spellcaster_wizard (FEATURE_METHODS, calc_install_quote, build_system_prompt),
    model_activation, lora_calibration, lora_grouping, scaffold_calibration,
    issue_cue, cue_seeder, network_survey, install_plan,
    video_bridge, video_wizard, shotboard, wangp_runner, video_assembler,
    comfyui_runner, frame_extract.
"""
