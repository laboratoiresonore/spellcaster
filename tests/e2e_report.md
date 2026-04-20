# Spellcaster E2E Audit

_Ran at_: 2026-04-19 22:10:57
_Totals_: **3** pass · **0** fail · **2** warn · **0** skip

## Video canon (spellcaster_core.video_presets)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | wan_turbo_kwargs | turbo={}  full={'steps': 30, 'cfg': 3.5, 'second_step': 15} | 0 |
| PASS | ltx_mode_kwargs | {'distilled': {'distilled': True, 'two_stage': False}, 'full': {'distilled': False, 'two_stage': False}, 'two_stage': {'distilled': False, 'two_stage': True}, 'i2v': {'distilled': True, 'two_stage': False}} | 0 |
| PASS | pick_wan_vae | 14B→wan_2.1_vae.safetensors  5B→wan2.2_vae.safetensors | 0 |
| WARN | detect_wan_preset (live) | no WAN models detected on server | 20012 |
| WARN | detect_ltx_preset (live) | no LTX models detected on server | 20022 |
