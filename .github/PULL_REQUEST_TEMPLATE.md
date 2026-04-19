<!-- Thanks for contributing. A few things to check before you open this. -->

## What does this change?

<!-- One or two sentences on the change and why. Link any related issue. -->

## Type of change

- [ ] Bug fix
- [ ] New tool / new preset
- [ ] New ComfyUI architecture support
- [ ] Refactor (no behavior change)
- [ ] Docs only
- [ ] Other

## Checklist

- [ ] **No personal data in the diff.** No real IPs, no `C:\Users\...` paths, no email addresses, no tokens.
- [ ] **No NSFW content in the public repo.** Nothing under `nsfw/` is staged (`nsfw/` is gitignored — never `git add -f`).
- [ ] **`spellcaster_core/` stays in sync.** If you edited a file under any `spellcaster_core/`, the three copies (`plugins/gimp/comfyui-connector/spellcaster_core/`, `comfyui-spellcaster/spellcaster_core/`, `../ComfyUI-Spellcaster/spellcaster_core/`) all match.
- [ ] **New ComfyUI custom nodes are declared.** If this uses a new custom-node pack, it's listed in `installer/manifest.json` under `custom_nodes` with `provides` + `required_by`, and `DEPENDENCIES.md` has been regenerated (`python scripts/generate_dependencies_md.py`).
- [ ] **New GIMP procedures are registered in all three dicts** (`_PROC_FEATURES`, `menu_map`, `_menu_paths`).
- [ ] **Tested locally** against a running ComfyUI server. Describe below.

## Test plan

<!-- What did you click, in what order, with what model? Screenshots of before/after welcome. -->

## Screenshots / clips (if UI)

<!-- Drag-drop. -->
