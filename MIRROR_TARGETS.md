# MIRROR_TARGETS.md — canonical file-path list for `spellcaster_core/` mirror sync

> **Canonical** location of the 6-surface mirror enumeration referenced
> by `spellcaster_NSFW/CLAUDE.md` §2 R1 ("Six-surface mirror sync") AND
> `Laborantin/CLAUDE.md` §2 R4 ("5-copy sync rule"). Resolves the
> contradiction between the two stale enumerations: there are SIX
> file-path-level surfaces, not five — Laborantin's R4 was counting at
> repo level rather than file-path level.
>
> Both documents now reference THIS file by path; their §2 entries
> only state the rule + invariant, not the enumeration. CI drift-checks
> read this file as the source of truth.

## The 6 surfaces

The canonical pack is at:

  **(C) `spellcaster/comfyui-spellcaster/spellcaster_core/<file>`**

…living in the SFW source repo (`laboratoiresonore/spellcaster`).
Every change starts here. After committing canonical, propagate to:

| # | Surface | Path |
|---|---------|------|
| 1 | GIMP-side dev copy | `spellcaster/plugins/gimp/comfyui-connector/spellcaster_core/<file>` |
| 2 | Public ComfyUI-Spellcaster pack (SFW) | `../ComfyUI-Spellcaster/spellcaster_core/<file>` |
| 3 | NSFW ComfyUI-Spellcaster pack | `../ComfyUI-Spellcaster-NSFW/spellcaster_core/<file>` |
| 4 | Installed user copy | `%APPDATA%/.../ComfyUI/custom_nodes/comfyui-spellcaster/spellcaster_core/<file>` |
| 5 | Voodoomancer-distro plug-in | `voodoomancer-distro/plugin/comfyui-connector/spellcaster_core/<file>` |
| 6 | Auto-updater seed (NSFW upstream) | `spellcaster_NSFW/comfyui-spellcaster/spellcaster_core/<file>` (synced from C via the auto-patch bot) |

Surface 6 is the one Voodoomancer end-users auto-pull from at runtime
(per `plugin/comfyui-connector/_spellcaster_main.py:_GITHUB_REPO`).
The auto-patch bot keeps it in sync with C; if an edit lands in any
other surface but not C, surface 6 will overwrite it on the next
auto-patch run — drift becomes silent + destructive.

## Files in scope

`spellcaster_core/` modules that must be byte-identical across all 6
surfaces (per `spellcaster_NSFW/CLAUDE.md` §2 R1):

```
workflows.py            node_factory.py         composites.py
architectures.py        prompt_enhance.py       video_presets.py
pipeline.py             diagnostic.py           preflight.py
model_detect.py         comfyui_llm.py          guild_llm.py
privacy.py              asset_gallery.py        event_bus.py
interface_registry.py   mailbox.py              cross_interface.py
lora_knowledge.py       lora_calibration_store.py    lora_scorer.py
faceswap_health.py      preflight_status.py     events.py
lora_calibrations_sfw.json
```

**Pack-root mirrors** (NOT inside `spellcaster_core/`, only mirror to
surfaces 1-3 — the three places a ComfyUI pack root lives):

```
presence.py             blob_bus.py
```

## Verification

`md5sum` (or `Get-FileHash`) compare across surfaces is the floor;
the `.claude/agents/sync-checker` agent in spellcaster_NSFW automates
the comparison. Run it before any commit touching shared files.

```bash
# Quick manual check (cd into the spellcaster repo first):
md5sum  comfyui-spellcaster/spellcaster_core/workflows.py \
        plugins/gimp/comfyui-connector/spellcaster_core/workflows.py \
        ../ComfyUI-Spellcaster/spellcaster_core/workflows.py \
        ../ComfyUI-Spellcaster-NSFW/spellcaster_core/workflows.py
```

All four hashes must match. Surface 4 (user-installed) is excluded
from compile-time checks because users move it; it's verified by the
client-side auto-updater on first launch.

## SFW vs NSFW exception

NSFW-only files (`workflows_nsfw.py`, `prompt_enhance_nsfw.py`,
`lora_calibrations_nsfw.json`, etc.) live ONLY at surfaces 3 and 6 —
never at surfaces 1, 2, 4, 5. The auto-patch bot enforces this: SFW
commits never carry NSFW additions forward; NSFW commits never push
back to SFW.

---

*Awkward is fine if it's awake — `awake` is the master plan §2.2
mantra for this rule. Document, CI-check, don't simplify away.*
