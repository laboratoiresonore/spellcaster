# Spellcaster Extension for SillyTavern

AI-powered living scenes, dynamic backgrounds, character restyling, autonomous image generation, cross-app asset transfer — all driven by ComfyUI (and optionally the Wizard Guild) through conversation.

## Features

### Living Scenes (Auto-Background)
The extension watches your roleplay narrative and automatically generates scene backgrounds when the setting changes. A forest scene generates a forest background; moving to a castle generates a castle. The tavern transforms with your story.

Narrative analysis runs a regex-based detector for location shifts, attire changes, weather/time, pose, and dramatic beats. False positives are trimmed by a post-filter that stops location captures at conjunctions ("walked into the bar **and** ordered drinks" → `bar`, not `bar and ordered drinks`).

### Character Restyling
Transform a single character's avatar with `/restyle`, or ALL avatars with `/restyle-all`. Backs up the original as `<name>.bak.png` so you can `/restyle-undo` / `/restyle-undo-all`. Uses Klein 2 img2img → Flux Kontext → SDXL img2img, whichever the server has.

### LLM Function Tools
Characters can autonomously decide when to generate visuals via three tools:

- `spellcaster_generate_scene(scene_description, set_as_background?)`
- `spellcaster_generate_portrait(character_description)`
- `spellcaster_set_atmosphere(atmosphere, location?)`

Argument handling is null-safe and length-capped (2 kB) so a hallucinating model can't crash the tool or break out of the rendered image token with `](javascript:...)`. Requires a model that supports function calling (Mistral, Llama 3.1+, GPT-4, Claude).

### Magic Studios (character-first compositing)

1. `/studio-cast` (or `-all`) — build a ReActor face model from a character's avatar.
2. `/studio-body [desc|attire]` (or `-all`) — generate a full-body transparent PNG with the face swapped in.
3. `/studio-scene [desc]` — generate a scene background and composite up to 4 character bodies into it.
4. `/studio-status` — check which characters are cast / have body images ready.

### Cross-app transfer (via Wizard Guild)

Ship the current chat image to another Spellcaster surface:

- `/sc-send-to-gimp [url]` — GIMP picks it up via **Spellcaster › Cross-App › 💎 Check Inbox**
- `/sc-send-to-darktable [url]` — Darktable's Spellcaster lib picks it up
- `/sc-send-to-resolve [url]` — Resolve's Media Pool bridge auto-imports it

And pull assets sent back to SillyTavern:

- `/sc-inbox` — pull pending items on demand
- **Auto-show assets from other apps** (new) — enable in settings to auto-poll the Guild every 30 s and render incoming assets as a system chat message. Off by default. See `auto_inbox_poll` / `auto_inbox_interval_s` below.

### Animated moments

`/animate [prompt]` routes through the Wizard Guild's `/api/video/shots` pipeline (WAN 2.2 I2V / LTX 2.3). Falls back to a local SDXL noise-injection "animation" if the Guild is unreachable. The canon (preset detection, VAE pairing, turbo formula, subtitle-burn-in negative) lives in `spellcaster_core.video_presets` + `spellcaster_core.workflows`; this plugin deliberately does NOT hand-roll WAN/LTX workflow JSON (CLAUDE.md §16.4).

### Slash Commands

| Command | What It Does |
|---|---|
| `/scene [description]` | Generate and set a scene background |
| `/portrait [description]` | Generate a character portrait inline |
| `/edit [instruction]` | Semantic edit of the current avatar (Klein → Kontext → SDXL) |
| `/restyle [style]` | Transform current character's avatar (persists with .bak backup) |
| `/restyle-all [style]` | Transform ALL character avatars at once |
| `/restyle-undo` / `/restyle-undo-all` | Revert from `.bak.png` |
| `/animate [prompt]` | Short video via Guild's WAN/LTX pipeline (SDXL fallback) |
| `/studio-cast` / `/studio-cast-all` | ReActor face model from avatar |
| `/studio-body [desc]` / `/studio-body-all [attire]` | Full-body transparent PNG with face swap |
| `/studio-scene [desc]` | Generate scene + composite cast characters |
| `/studio-status` | Readiness dashboard |
| `/sc-capabilities` | Probe ComfyUI `/object_info` and list installed architectures |
| `/sc-send-to-resolve` / `-gimp` / `-darktable` | Ship the current chat image across |
| `/sc-inbox` | Pull pending cross-plugin assets (also polled automatically when enabled) |
| `/spellcaster [on\|off\|auto-bg on\|auto-bg off]` | Toggle features |
| `/spellcaster-wizard` | (Re-)run the 7-step setup wizard |

### Expression Generation
Automatically generates emotion-appropriate portraits based on sentiment analysis of character messages. Happy scenes get smiling portraits; tense scenes get serious expressions.

## Requirements

- SillyTavern (latest release branch)
- ComfyUI running locally or on the network (with AI models installed)
- **Optional but recommended:** Wizard Guild (`http://127.0.0.1:7777`) — required for `/animate` real video and for cross-app `/sc-send-to-*` / `/sc-inbox`. Without it, `/animate` falls back to SDXL noise-injection jitter and cross-app commands no-op.
- Spellcaster models (use the Spellcaster installer)

## Installation

### From SillyTavern Extension Manager
1. Open SillyTavern → Extensions → Install Extension
2. Enter URL: `https://github.com/laboratoiresonore/spellcaster`
3. The extension auto-detects and configures itself

### Manual Installation
1. Copy the `spellcaster-st` folder to:
   - `SillyTavern/data/default-user/extensions/spellcaster-st/` (UI extension)
   - `SillyTavern/plugins/spellcaster-st/` (server plugin)
2. Restart SillyTavern
3. Go to Extensions → Spellcaster → Set your ComfyUI URL (or run the first-run wizard)

### Bespoke / Docker deploys

The server plugin auto-detects SillyTavern's characters + backgrounds
directories relative to the ST process CWD (`data/default-user/characters/`
or `public/characters/`). For Docker volumes or custom data-user
layouts, set absolute-path overrides on the ST process environment:

```
SPELLCASTER_ST_CHARACTERS_DIR=/st/data/users/alice/characters
SPELLCASTER_ST_BACKGROUNDS_DIR=/st/data/users/alice/backgrounds
```

Without these, `/save-avatar`, `/save-expression`, and the scene
background save path will 500 with "Cannot find SillyTavern
characters directory".

## Configuration

Open the Spellcaster panel in SillyTavern's extension settings:

| Setting | Default | Description |
|---|---|---|
| Enable Spellcaster | ON | Master toggle |
| Auto-generate backgrounds | OFF | Generate scene backgrounds from narrative |
| Background interval | 3 | Generate every N messages (not every message) |
| Auto-generate expressions | OFF | Generate emotion portraits on the fly |
| Auto-cast on startup (slow) | OFF | Pre-cast every character + body on ST launch; queues 1 Klein job per character |
| **Auto-show assets from other apps** | **OFF** | Poll the Guild's inbox every `auto_inbox_interval_s` and render pending cross-plugin assets as a system message — no more manual `/sc-inbox` |
| ComfyUI URL | `http://127.0.0.1:8188` | Your ComfyUI server |
| Restyle prompt | photorealistic portrait... | Default style for /restyle |
| Restyle denoise | 0.55 | How much to change (0.3=subtle, 0.7=heavy) |
| Image model | _auto_ | Picked by wizard; empty = auto-select best installed |
| Video backend | auto | `auto`, `wan22`, or `none` (for /animate) |
| Quality profile | balanced | `fast`, `balanced`, or `max` (PAG/RescaleCFG/FreeU/SLG/AYS stack) |
| `auto_inbox_interval_s` | 30 | Inbox poll cadence (clamped to [10 s, 5 min]) |

### First-Run Wizard

On first load the extension opens a 7-step wizard:

1. Welcome
2. ComfyUI server URL + connection test
3. Default image model (populated from `/object_info`, grouped by arch — `klein9b`, `klein4b`, `fluxkontext`, `flux1dev`, `sdxl`, `illustrious`, `sd15`, `zit`, `chroma`)
4. Video backend (auto-detects Wan 2.2 / LTX; shows disabled if not installed)
5. Quality profile (Fast / Balanced / Max — controls the server-side quality-booster stack wired by `workflows.build_txt2img` / `build_img2img` / `build_inpaint`)
6. Automation toggles (auto-background interval, auto-expressions, auto-cast on startup, **auto-show from other apps**)
7. Review & Save

The wizard writes the same settings keys the flat panel does — nothing
hidden. Re-run any time with `/spellcaster-wizard` or the **Run Wizard**
button in the Extensions settings panel.

## Endpoints (server-plugin.js)

Mounted at `/api/plugins/spellcaster/*`. Notable:

- `POST /settings` — update ComfyUI / Guild URL, `backgrounds_dir` (absolute), image_model, video_backend, quality_profile. URLs clamped to `http(s):`.
- `GET /models` — classify ComfyUI's `/object_info` into arch buckets (bounded: 30 s timeout, 50 MB cap).
- `GET /capabilities` — architecture feature gate based on installed nodes.
- `GET /health` — ComfyUI reachability probe.
- `POST /generate` `/scene` `/portrait` `/restyle` `/edit` `/animate` `/studio/*` — the generation surface.
- `POST /save-avatar` `/save-expression` `/restore-avatar` — persistence. Filenames + character names path-sanitized; 28 MB base64 cap; resolve-under-root check.
- `POST /cross/send` `/cross/inbox` — cross-plugin transfer via the Wizard Guild. `image_url` scheme-clamped to `http(s)` (no `file://` smuggling); `image_data_url` required to match `data:image/<type>`.
- `POST /dispatch` — raw ComfyUI workflow submission. **Disabled by default** — opt in via `SPELLCASTER_ALLOW_DISPATCH=1` on the ST process environment.

## Security notes

- Every base64 image endpoint enforces a 28 MB cap (`_rejectOversizedB64`) — a malicious client can't OOM the ST process.
- `/cross/send`'s `image_url` path fetches server-side via `fetchBytes` which has a 50 MB + 30 s hard ceiling.
- `fetchJSON` has a 30 s timeout and 50 MB cap — a stalled or rogue ComfyUI/Guild can't hang the plugin forever.
- Every filename landing in a filesystem path goes through `_safeNameOrNull` (rejects path separators, drive markers, NTFS-reserved names, `..`, control chars) + a `path.basename` + a resolve-under-root check.
- The `/sc-inbox` renderer escapes markdown delimiters from attacker-reachable `source` / `title` fields and allowlists `image_url` to `http(s):` / `data:image/` / relative `/api/`.
- Function-tool outputs are length-capped (2 kB) and markdown-safe-truncated so a hallucinated `](javascript:...)` can't break out of the `![alt](url)` wrapping.
- Settings-panel template literals escape `& < > " '` on every interpolation as defense-in-depth against a future "import settings from JSON" regression.
