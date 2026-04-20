# Spellcaster E2E Audit

_Ran at_: 2026-04-20 10:37:37
_Totals_: **24** pass · **0** fail · **0** warn · **0** skip

## Event schema

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | import events.py | registry has 9 explicit kinds | 0 |
| PASS | _EventBase round-trip | kind= | 0 |
| PASS | AssetCreated round-trip | kind=*.asset.created | 0 |
| PASS | AssetUploaded round-trip | kind=*.asset.uploaded | 0 |
| PASS | GenerationFinished round-trip | kind=*.generation.finished | 0 |
| PASS | AssetSend round-trip | kind=*.asset.send | 0 |
| PASS | ClipImport round-trip | kind=resolve.clip.import | 0 |
| PASS | PresenceHeartbeat round-trip | kind=*.presence.heartbeat | 0 |
| PASS | GuildSelfUpdateResult round-trip | kind=guild.self_update.result | 0 |
| PASS | GuildSelfUpdateError round-trip | kind=guild.self_update.error | 0 |
| PASS | PlayheadGrab round-trip | kind=resolve.playhead.grab | 0 |
| PASS | PlayheadSendToPeer round-trip | kind=resolve.playhead.send_to_peer | 0 |
| PASS | TimelineImport round-trip | kind=resolve.timeline.import | 0 |
| PASS | PlayheadReady round-trip | kind=resolve.playhead.ready | 0 |
| PASS | TimelineImported round-trip | kind=resolve.timeline.imported | 0 |
| PASS | SendToPeerDone round-trip | kind=resolve.send_to_peer.done | 0 |
| PASS | publish_event() wildcard expansion | e2e_audit.asset.send | 0 |

## Coverage inventory

| Status | Test | Detail | Time (ms) |
|---|---|---|---|
| PASS | spellcaster_core | 39/451 referenced (9%) | 0 |
| PASS | comfyui_pack | 39/461 referenced (8%) | 0 |
| PASS | gimp_plugin | 39/528 referenced (7%) | 0 |
| PASS | resolve_shared | 1/42 referenced (2%) | 0 |
| PASS | resolve_bridge | 1/16 referenced (6%) | 0 |
| PASS | guild_tavern | 1/27 referenced (4%) | 0 |
| PASS | TOTAL across all surfaces | 120/1525 public fns referenced (8%) | 0 |
