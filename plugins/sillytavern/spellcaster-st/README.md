# Spellcaster Extension for SillyTavern

AI-powered living scenes, dynamic backgrounds, character restyling, and autonomous image generation — all driven by ComfyUI through conversation.

## Features

### Living Scenes (Auto-Background)
The extension watches your roleplay narrative and automatically generates scene backgrounds when the setting changes. A forest scene generates a forest background; moving to a castle generates a castle. The tavern transforms with your story.

### Character Restyling
Transform ALL character avatars with a single command. Turn anime characters into photorealistic portraits, or vice versa. Uses AI style transfer through ComfyUI.

### LLM Function Tools
Characters can autonomously decide when to generate visuals. If the story reaches a dramatic moment, the AI calls `generate_scene` on its own. Requires a model that supports function calling (Mistral, Llama 3.1+, GPT-4).

### Slash Commands
| Command | What It Does |
|---|---|
| `/scene [description]` | Generate and set a scene background |
| `/portrait [description]` | Generate a character portrait inline |
| `/restyle [style]` | Transform current character's avatar |
| `/restyle-all [style]` | Transform ALL character avatars at once |
| `/animate [prompt]` | Generate a short animation |
| `/spellcaster [on\|off\|auto-bg on\|auto-bg off]` | Toggle features |

### Expression Generation
Automatically generates emotion-appropriate portraits based on sentiment analysis of character messages. Happy scenes get smiling portraits; tense scenes get serious expressions.

## Requirements

- SillyTavern (latest release branch)
- ComfyUI running locally or on network (with AI models installed)
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
3. Go to Extensions → Spellcaster → Set your ComfyUI URL

## Configuration

Open the Spellcaster panel in SillyTavern's extension settings:

| Setting | Default | Description |
|---|---|---|
| Enable Spellcaster | ON | Master toggle |
| Auto-generate backgrounds | OFF | Generate scene backgrounds from narrative |
| Background interval | 3 | Generate every N messages (not every message) |
| Auto-generate expressions | OFF | Generate emotion portraits on the fly |
| ComfyUI URL | http://127.0.0.1:8188 | Your ComfyUI server |
| Restyle prompt | photorealistic portrait... | Default style for /restyle |
| Restyle denoise | 0.55 | How much to change (0.3=subtle, 0.7=heavy) |
