# Spellcaster E2E Audit

_Ran at_: 2026-04-20 00:28:59
_Totals_: **5** pass · **0** fail · **0** warn · **0** skip

## Video canon (spellcaster_core.video_presets)

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | wan_turbo_kwargs | turbo={}  full={'steps': 30, 'cfg': 3.5, 'second_step': 15} | 0 |
| PASS | ltx_mode_kwargs | {'distilled': {'distilled': True, 'two_stage': False}, 'full': {'distilled': False, 'two_stage': False}, 'two_stage': {'distilled': False, 'two_stage': True}, 'i2v': {'distilled': True, 'two_stage': False}} | 0 |
| PASS | pick_wan_vae | 14B→wan_2.1_vae.safetensors  5B→wan2.2_vae.safetensors | 0 |
| PASS | detect_wan_preset (live) | high=Wan\2.2\Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_  vae=wan_2.1_vae.safetensors | 98 |
| PASS | detect_ltx_preset (live) | unet=LTX\ltx-2.3-22b-dev-Q4_K_M.gguf  te=gemma_3_12B_it_fp4_mixed.safet | 125 |
