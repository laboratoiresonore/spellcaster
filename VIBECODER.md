# Vibecoder scope - spellcaster

> **What this is:** the local vibe coder for `spellcaster` is a lightweight on-device LLM that handles routine code changes in this repo. It's NOT for architecture work, security review, or anything touching production data. The orchestrator (Claude Code) should defer to this scope when the user's request matches one of the bullets below.

## Repo at a glance
<!-- AUTO:glance -->
- **Local path:** `C:\Users\legui\spellcaster`
- **Primary language:** `Python`
- **Last analyzed:** `2026-05-07T09:42:28Z`
- **Last commit:** `79165a2 - chore(install): sync sanitized bootstrap shim from laboratoiresonore master`
- **Lines of code (rough):** `687`
- **Test command:** `pytest`
<!-- /AUTO:glance -->

## What the vibe coder owns (do delegate)
- Mechanical refactors confined to a single file
- Adding a CLI flag / config option that's already plumbed elsewhere in the repo
- Updating docstrings, type hints, comment formatting
- Fixing a single failing test where the fix is "make the test pass without changing semantics"
- Bumping a dependency version in the manifest (but not migrating call sites)
- Following an established pattern to add a new instance (e.g. another OWUI tool of the same shape, another route handler matching the existing list)
- Adding a new spell module in the existing spell-pack directory layout
- Mechanical refactor inside a single GUI panel file
- Adding an asset-loader entry that mirrors an existing one

## What the vibe coder must NOT touch (do not delegate)
- Schema changes (db migrations, breaking API changes)
- Anything in `_logs/`, `data/`, `cases/`, or other personal-data directories
- OAuth or credential handling
- Cross-repo refactors
- Anything that requires understanding the whole repo at once
- lab-installer bootstrap / self-update logic (sanitized shim is delicate)
- GitHub auto-fetch flow
- Anything that crosses spellcaster <-> spellcaster_NSFW boundaries (they share the bootstrap)

## Hand-off contract
The orchestrator should:
1. Make sure the change is local to one or two files.
2. Spell out the exact files + the desired behavior (the vibe coder is happier with concrete diffs than with goals).
3. Provide an obvious success signal (a test, a log line, a manual smoke check).

## Auto-detected modules (high signal for delegation)
<!-- AUTO:modules -->
- `plugins/gimp/comfyui-connector/comfyui-connector.py`
- `tavern/server.py`
- `plugins/gimp/comfyui-connector/_spellcaster_main.py`
- `tavern/static/app.js`
- `plugins/gimp/comfyui-connector/spellcaster_core/workflows.py`
- `comfyui-spellcaster/spellcaster_core/workflows.py`
- `tavern/static/index.html`
- `tavern/static/style.css`
- `.gitignore`
- `plugins/darktable/comfyui_connector.lua`
- `tavern/static/video_panel.jsx`
- `installer/install.py`
<!-- /AUTO:modules -->
