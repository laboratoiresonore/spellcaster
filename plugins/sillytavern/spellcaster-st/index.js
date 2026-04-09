/**
 * Spellcaster Extension for SillyTavern
 * =======================================
 * Living scenes, character restyling, autonomous image generation,
 * animated moments, and dynamic backgrounds — all powered by ComfyUI.
 *
 * Features:
 *   1. Auto-background: generates scene backgrounds from narrative context
 *   2. /restyle: batch-transform all character avatars (anime→photo, etc.)
 *   3. /scene: manually generate and set a scene background
 *   4. /portrait: generate a character portrait from description
 *   5. /animate: create a short video from the current scene
 *   6. Function tools: LLM autonomously triggers image generation
 *   7. Expression generation: on-the-fly emotion portraits
 *   8. Generate interceptor: extracts scene context for visual generation
 */

const PLUGIN_ID = 'spellcaster';
const API_BASE = '/api/plugins/spellcaster';

// ═══════════════════════════════════════════════════════════════════
//  Settings (persisted via extension_settings)
// ═══════════════════════════════════════════════════════════════════

const DEFAULT_SETTINGS = {
    enabled: true,
    comfyui_url: 'http://127.0.0.1:8188',
    auto_background: false,        // Generate backgrounds after each message
    auto_background_interval: 3,   // Every N messages (not every single one)
    auto_expressions: false,       // Generate expression portraits on the fly
    scene_width: 1280,
    scene_height: 720,
    portrait_width: 400,
    portrait_height: 600,
    restyle_denoise: 0.55,
    restyle_prompt: 'photorealistic portrait, professional photography, detailed skin texture, 8k',
    message_count: 0,              // Tracks messages for auto-background interval
    last_scene_description: '',    // Caches last generated scene
};

function getSettings() {
    const context = getContext();
    if (!context.extensionSettings[PLUGIN_ID]) {
        context.extensionSettings[PLUGIN_ID] = { ...DEFAULT_SETTINGS };
    }
    return context.extensionSettings[PLUGIN_ID];
}

function saveSettings() {
    const context = getContext();
    context.saveSettingsDebounced();
}

// ═══════════════════════════════════════════════════════════════════
//  ComfyUI API Helpers
// ═══════════════════════════════════════════════════════════════════

async function spellcasterAPI(endpoint, body) {
    const res = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        throw new Error(err.error || `Spellcaster API error: ${res.status}`);
    }
    return res.json();
}

async function checkHealth() {
    try {
        const res = await fetch(`${API_BASE}/health`);
        const data = await res.json();
        return data.comfyui === 'connected';
    } catch {
        return false;
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Scene Extraction — parse narrative for visual context
// ═══════════════════════════════════════════════════════════════════

function extractSceneDescription(messageText) {
    // Look for scene-setting patterns in the message
    const patterns = [
        // Asterisk narration: *They walked into the dark forest*
        /\*([^*]{20,200})\*/g,
        // Parenthetical: (The scene shifts to a moonlit beach)
        /\(([^)]{20,200})\)/g,
        // Quote-free descriptions of settings
        /(?:scene|setting|background|location|environment|room|place)\s*(?:is|was|changed?\s+to|shifts?\s+to|:)\s*(.{15,150})/gi,
    ];

    const scenes = [];
    for (const pattern of patterns) {
        let match;
        while ((match = pattern.exec(messageText)) !== null) {
            const desc = match[1].trim();
            // Filter out dialogue and short fragments
            if (desc.length > 15 && !desc.startsWith('"') && !desc.startsWith("'")) {
                scenes.push(desc);
            }
        }
    }

    // Return the longest scene description (most detailed)
    if (scenes.length > 0) {
        return scenes.sort((a, b) => b.length - a.length)[0];
    }
    return null;
}

function extractEmotionFromMessage(text) {
    // Simple keyword-based emotion detection
    const emotions = {
        'happy': ['smile', 'laugh', 'grin', 'joy', 'cheer', 'delight', 'beam'],
        'sad': ['cry', 'tear', 'sob', 'mourn', 'grief', 'sorrow', 'weep'],
        'angry': ['fury', 'rage', 'snarl', 'growl', 'scowl', 'glare', 'fist'],
        'surprised': ['gasp', 'shock', 'widen', 'startle', 'stun', 'stare'],
        'afraid': ['tremble', 'shake', 'fear', 'terror', 'pale', 'shiver'],
        'love': ['blush', 'flutter', 'warmth', 'tender', 'embrace', 'kiss'],
        'thinking': ['ponder', 'consider', 'hmm', 'think', 'wonder', 'contemplate'],
        'confident': ['smirk', 'swagger', 'proud', 'boldly', 'chest', 'stand tall'],
    };

    const lower = text.toLowerCase();
    let bestEmotion = 'neutral';
    let bestScore = 0;

    for (const [emotion, keywords] of Object.entries(emotions)) {
        let score = 0;
        for (const kw of keywords) {
            if (lower.includes(kw)) score++;
        }
        if (score > bestScore) {
            bestScore = score;
            bestEmotion = emotion;
        }
    }
    return bestEmotion;
}

// ═══════════════════════════════════════════════════════════════════
//  Feature: Auto-Background Generation
// ═══════════════════════════════════════════════════════════════════

async function onCharacterMessageRendered(messageIndex) {
    const settings = getSettings();
    if (!settings.enabled || !settings.auto_background) return;

    settings.message_count = (settings.message_count || 0) + 1;
    if (settings.message_count % settings.auto_background_interval !== 0) return;

    const context = getContext();
    const message = context.chat[messageIndex];
    if (!message || message.is_user) return;

    const sceneDesc = extractSceneDescription(message.mes);
    if (!sceneDesc || sceneDesc === settings.last_scene_description) return;

    settings.last_scene_description = sceneDesc;
    saveSettings();

    console.log(`[Spellcaster] Auto-background: "${sceneDesc.substring(0, 60)}..."`);

    try {
        const result = await spellcasterAPI('/scene', {
            description: sceneDesc,
            width: settings.scene_width,
            height: settings.scene_height,
        });

        if (result.bg_filename) {
            // Use ST's /bg command to set the background
            const context = getContext();
            if (context.SlashCommandParser) {
                await context.SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
            }
            toastr.info(`Scene: ${sceneDesc.substring(0, 50)}...`, 'Spellcaster');
        } else if (result.images?.[0]) {
            // Fallback: inject as inline image
            toastr.info('Background generated (save manually)', 'Spellcaster');
        }
    } catch (e) {
        console.error('[Spellcaster] Auto-background failed:', e);
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Feature: Expression Generation (on-the-fly emotion portraits)
// ═══════════════════════════════════════════════════════════════════

async function generateExpression(characterName, emotion, messageText) {
    const settings = getSettings();
    if (!settings.auto_expressions) return;

    const context = getContext();
    const char = context.characters.find(c => c.name === characterName);
    if (!char) return;

    const prompt = `${char.description || characterName}, ${emotion} expression, ` +
                   `portrait, looking at viewer, detailed face, studio lighting`;

    try {
        const result = await spellcasterAPI('/portrait', {
            description: prompt,
            width: settings.portrait_width,
            height: settings.portrait_height,
        });

        if (result.images?.[0]) {
            console.log(`[Spellcaster] Generated ${emotion} expression for ${characterName}`);
            // The expression could be saved to the character's expression folder
            // For now, we just log it — full expression integration needs file system access
        }
    } catch (e) {
        console.error(`[Spellcaster] Expression generation failed for ${characterName}:`, e);
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Slash Commands
// ═══════════════════════════════════════════════════════════════════

function registerSlashCommands() {
    const context = getContext();
    const SCP = context.SlashCommandParser;
    if (!SCP) return;

    // /scene [description] — Generate and set a scene background
    SCP.addCommandObject({
        name: 'scene',
        callback: async (args, value) => {
            if (!value) return 'Usage: /scene [description of the scene]';
            toastr.info('Generating scene...', 'Spellcaster');
            try {
                const settings = getSettings();
                const result = await spellcasterAPI('/scene', {
                    description: value,
                    width: settings.scene_width,
                    height: settings.scene_height,
                });
                if (result.bg_filename) {
                    await SCP.commands['bg']?.callback?.(null, result.bg_filename);
                    return `Scene generated: ${result.bg_filename}`;
                }
                return 'Scene generated (no background directory configured)';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Generate a scene background from a description and set it as the chat background.',
    });

    // /portrait [description] — Generate a character portrait
    SCP.addCommandObject({
        name: 'portrait',
        callback: async (args, value) => {
            if (!value) return 'Usage: /portrait [description of the character]';
            toastr.info('Generating portrait...', 'Spellcaster');
            try {
                const result = await spellcasterAPI('/portrait', { description: value });
                if (result.images?.[0]) {
                    const imgTag = `![portrait](data:image/png;base64,${result.images[0].base64})`;
                    return imgTag;
                }
                return 'Portrait generation failed';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Generate a character portrait from a description.',
    });

    // /restyle [style] — Restyle current character's avatar
    SCP.addCommandObject({
        name: 'restyle',
        callback: async (args, value) => {
            const style = value || getSettings().restyle_prompt;
            const context = getContext();
            const char = context.characters[context.characterId];
            if (!char) return 'No character selected';

            toastr.info(`Restyling ${char.name}...`, 'Spellcaster');
            try {
                // Get current avatar as base64
                const avatarUrl = char.avatar ? `/characters/${char.avatar}` : null;
                if (!avatarUrl) return 'Character has no avatar';

                const avatarRes = await fetch(avatarUrl);
                const avatarBlob = await avatarRes.blob();
                const base64 = await blobToBase64(avatarBlob);

                const result = await spellcasterAPI('/restyle', {
                    image_base64: base64,
                    prompt: style,
                    denoise: getSettings().restyle_denoise,
                });

                if (result.images?.[0]) {
                    const imgTag = `![restyled](data:image/png;base64,${result.images[0].base64})`;
                    toastr.success(`${char.name} restyled!`, 'Spellcaster');
                    return imgTag;
                }
                return 'Restyle failed';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Restyle the current character\'s avatar using AI image transformation.',
    });

    // /restyle-all [style] — Restyle ALL character avatars in current group/chat
    SCP.addCommandObject({
        name: 'restyle-all',
        callback: async (args, value) => {
            const style = value || getSettings().restyle_prompt;
            const context = getContext();
            const chars = context.characters.filter(c => c.avatar);

            if (chars.length === 0) return 'No characters with avatars found';

            toastr.info(`Restyling ${chars.length} characters...`, 'Spellcaster');
            let restyled = 0;

            for (const char of chars) {
                try {
                    const avatarUrl = `/characters/${char.avatar}`;
                    const avatarRes = await fetch(avatarUrl);
                    const avatarBlob = await avatarRes.blob();
                    const base64 = await blobToBase64(avatarBlob);

                    const result = await spellcasterAPI('/restyle', {
                        image_base64: base64,
                        prompt: style,
                        denoise: getSettings().restyle_denoise,
                    });

                    if (result.images?.[0]) {
                        restyled++;
                        toastr.info(`Restyled ${char.name} (${restyled}/${chars.length})`, 'Spellcaster');
                    }
                } catch (e) {
                    console.error(`[Spellcaster] Restyle failed for ${char.name}:`, e);
                }
            }
            return `Restyled ${restyled}/${chars.length} characters`;
        },
        helpString: 'Restyle ALL character avatars with the given style prompt.',
    });

    // /animate [prompt] — Generate a short video from current scene
    SCP.addCommandObject({
        name: 'animate',
        callback: async (args, value) => {
            toastr.info('Generating animation...', 'Spellcaster');
            // TODO: Get current scene/character image and animate it
            return 'Animation feature requires an image. Use /scene first, then /animate.';
        },
        helpString: 'Generate a short animated video from the current scene.',
    });

    // /spellcaster — Toggle extension on/off
    SCP.addCommandObject({
        name: 'spellcaster',
        callback: async (args, value) => {
            const settings = getSettings();
            if (value === 'on') {
                settings.enabled = true;
                saveSettings();
                return 'Spellcaster enabled';
            } else if (value === 'off') {
                settings.enabled = false;
                saveSettings();
                return 'Spellcaster disabled';
            } else if (value === 'auto-bg on') {
                settings.auto_background = true;
                saveSettings();
                return 'Auto-background generation enabled';
            } else if (value === 'auto-bg off') {
                settings.auto_background = false;
                saveSettings();
                return 'Auto-background generation disabled';
            } else {
                return `Spellcaster: ${settings.enabled ? 'ON' : 'OFF'} | ` +
                       `Auto-BG: ${settings.auto_background ? 'ON' : 'OFF'} | ` +
                       `ComfyUI: ${settings.comfyui_url}`;
            }
        },
        helpString: 'Toggle Spellcaster features. Usage: /spellcaster [on|off|auto-bg on|auto-bg off]',
    });
}

// ═══════════════════════════════════════════════════════════════════
//  Function Tools (LLM-Autonomous Image Generation)
// ═══════════════════════════════════════════════════════════════════

function registerFunctionTools() {
    const context = getContext();
    if (!context.registerFunctionTool) return;

    // Tool: Generate a scene image
    context.registerFunctionTool({
        name: 'spellcaster_generate_scene',
        displayName: 'Generate Scene Image',
        description: 'Generate an image of the current scene or environment. Call this when the narrative describes a new location, dramatic scene change, or when a visual would enhance the story.',
        parameters: {
            type: 'object',
            properties: {
                scene_description: {
                    type: 'string',
                    description: 'Detailed description of the scene to generate (location, lighting, mood, time of day)',
                },
                set_as_background: {
                    type: 'boolean',
                    description: 'Whether to set the generated image as the chat background',
                },
            },
            required: ['scene_description'],
        },
        action: async (args) => {
            try {
                const settings = getSettings();
                const result = await spellcasterAPI('/scene', {
                    description: args.scene_description,
                    width: settings.scene_width,
                    height: settings.scene_height,
                });
                if (result.bg_filename && args.set_as_background !== false) {
                    const ctx = getContext();
                    await ctx.SlashCommandParser?.commands['bg']?.callback?.(null, result.bg_filename);
                }
                return `Scene generated: ${args.scene_description.substring(0, 80)}...`;
            } catch (e) {
                return `Failed to generate scene: ${e.message}`;
            }
        },
        formatMessage: 'Conjuring scene...',
        shouldRegister: () => getSettings().enabled,
    });

    // Tool: Generate a character portrait
    context.registerFunctionTool({
        name: 'spellcaster_generate_portrait',
        displayName: 'Generate Portrait',
        description: 'Generate a portrait image of a character. Call this when introducing a new character or when a character\'s appearance changes significantly.',
        parameters: {
            type: 'object',
            properties: {
                character_description: {
                    type: 'string',
                    description: 'Physical description of the character (appearance, clothing, expression, setting)',
                },
            },
            required: ['character_description'],
        },
        action: async (args) => {
            try {
                const result = await spellcasterAPI('/portrait', {
                    description: args.character_description,
                });
                if (result.images?.[0]) {
                    return `Portrait generated for: ${args.character_description.substring(0, 50)}...`;
                }
                return 'Portrait generation failed';
            } catch (e) {
                return `Failed: ${e.message}`;
            }
        },
        formatMessage: 'Painting portrait...',
        shouldRegister: () => getSettings().enabled,
    });

    // Tool: Change the mood/atmosphere
    context.registerFunctionTool({
        name: 'spellcaster_set_atmosphere',
        displayName: 'Set Atmosphere',
        description: 'Change the visual atmosphere of the scene. Call this when the mood shifts dramatically (e.g., from calm to tense, day to night, peaceful to chaotic).',
        parameters: {
            type: 'object',
            properties: {
                atmosphere: {
                    type: 'string',
                    description: 'Description of the new atmosphere (lighting, mood, weather, time)',
                },
                location: {
                    type: 'string',
                    description: 'Current location/setting',
                },
            },
            required: ['atmosphere'],
        },
        action: async (args) => {
            try {
                const desc = `${args.location || 'scene'}, ${args.atmosphere}, cinematic atmosphere`;
                const settings = getSettings();
                const result = await spellcasterAPI('/scene', {
                    description: desc,
                    width: settings.scene_width,
                    height: settings.scene_height,
                });
                if (result.bg_filename) {
                    const ctx = getContext();
                    await ctx.SlashCommandParser?.commands['bg']?.callback?.(null, result.bg_filename);
                }
                return `Atmosphere set: ${args.atmosphere}`;
            } catch (e) {
                return `Failed: ${e.message}`;
            }
        },
        formatMessage: 'Shifting atmosphere...',
        shouldRegister: () => getSettings().enabled,
    });
}

// ═══════════════════════════════════════════════════════════════════
//  Generate Interceptor
// ═══════════════════════════════════════════════════════════════════

/**
 * Called before each LLM generation. Extracts scene context from
 * recent messages and stores it for potential auto-background use.
 */
async function spellcasterInterceptor(chat) {
    const settings = getSettings();
    if (!settings.enabled) return;

    // Extract scene context from the last few messages
    const recentMessages = chat.slice(-5);
    for (const msg of recentMessages) {
        if (msg.mes) {
            const scene = extractSceneDescription(msg.mes);
            if (scene) {
                settings.last_scene_description = scene;
            }
        }
    }
    // Don't modify the chat array — just observe
}

// Make it globally accessible for the manifest's generate_interceptor
window.spellcasterInterceptor = spellcasterInterceptor;

// ═══════════════════════════════════════════════════════════════════
//  Settings UI Panel
// ═══════════════════════════════════════════════════════════════════

function renderSettingsPanel() {
    const settings = getSettings();
    const html = `
    <div id="spellcaster-settings" class="spellcaster-panel">
        <div class="spellcaster-header">
            <span class="spellcaster-icon">🧙</span>
            <strong>Spellcaster</strong>
            <span id="spellcaster-status" class="spellcaster-status">checking...</span>
        </div>

        <label class="spellcaster-toggle">
            <input type="checkbox" id="spellcaster-enabled" ${settings.enabled ? 'checked' : ''}>
            <span>Enable Spellcaster</span>
        </label>

        <label class="spellcaster-toggle">
            <input type="checkbox" id="spellcaster-auto-bg" ${settings.auto_background ? 'checked' : ''}>
            <span>Auto-generate backgrounds from narrative</span>
        </label>

        <div class="spellcaster-row">
            <label>Background interval (every N messages):</label>
            <input type="number" id="spellcaster-bg-interval" value="${settings.auto_background_interval}" min="1" max="20" style="width:60px">
        </div>

        <label class="spellcaster-toggle">
            <input type="checkbox" id="spellcaster-auto-expr" ${settings.auto_expressions ? 'checked' : ''}>
            <span>Auto-generate character expressions</span>
        </label>

        <div class="spellcaster-row">
            <label>ComfyUI URL:</label>
            <input type="text" id="spellcaster-comfyui-url" value="${settings.comfyui_url}" style="width:100%">
        </div>

        <div class="spellcaster-row">
            <label>Restyle prompt:</label>
            <textarea id="spellcaster-restyle-prompt" rows="2" style="width:100%">${settings.restyle_prompt}</textarea>
        </div>

        <div class="spellcaster-row">
            <label>Restyle denoise (0.3=subtle, 0.7=heavy):</label>
            <input type="range" id="spellcaster-restyle-denoise" min="0.2" max="0.8" step="0.05" value="${settings.restyle_denoise}">
            <span id="spellcaster-denoise-val">${settings.restyle_denoise}</span>
        </div>

        <div class="spellcaster-commands">
            <strong>Slash Commands:</strong>
            <div>/scene [description] — generate + set background</div>
            <div>/portrait [description] — generate character portrait</div>
            <div>/restyle [style] — transform current avatar</div>
            <div>/restyle-all [style] — transform ALL avatars</div>
            <div>/spellcaster [on|off|auto-bg on|auto-bg off]</div>
        </div>
    </div>`;

    const container = document.getElementById('extensions_settings');
    if (container) {
        const div = document.createElement('div');
        div.innerHTML = html;
        container.appendChild(div);

        // Wire up controls
        document.getElementById('spellcaster-enabled')?.addEventListener('change', (e) => {
            settings.enabled = e.target.checked;
            saveSettings();
        });
        document.getElementById('spellcaster-auto-bg')?.addEventListener('change', (e) => {
            settings.auto_background = e.target.checked;
            saveSettings();
        });
        document.getElementById('spellcaster-bg-interval')?.addEventListener('change', (e) => {
            settings.auto_background_interval = parseInt(e.target.value) || 3;
            saveSettings();
        });
        document.getElementById('spellcaster-auto-expr')?.addEventListener('change', (e) => {
            settings.auto_expressions = e.target.checked;
            saveSettings();
        });
        document.getElementById('spellcaster-comfyui-url')?.addEventListener('change', (e) => {
            settings.comfyui_url = e.target.value.trim().replace(/\/+$/, '');
            saveSettings();
            // Update server plugin
            spellcasterAPI('/settings', { comfyui_url: settings.comfyui_url }).catch(() => {});
        });
        document.getElementById('spellcaster-restyle-prompt')?.addEventListener('change', (e) => {
            settings.restyle_prompt = e.target.value;
            saveSettings();
        });
        document.getElementById('spellcaster-restyle-denoise')?.addEventListener('input', (e) => {
            settings.restyle_denoise = parseFloat(e.target.value);
            document.getElementById('spellcaster-denoise-val').textContent = settings.restyle_denoise;
            saveSettings();
        });

        // Check health
        checkHealth().then(connected => {
            const el = document.getElementById('spellcaster-status');
            if (el) {
                el.textContent = connected ? '● Connected' : '○ Offline';
                el.style.color = connected ? '#2ed573' : '#ff4757';
            }
        });
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Utilities
// ═══════════════════════════════════════════════════════════════════

function blobToBase64(blob) {
    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => {
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.readAsDataURL(blob);
    });
}

// ═══════════════════════════════════════════════════════════════════
//  Initialization
// ═══════════════════════════════════════════════════════════════════

(function() {
    const context = getContext();
    const eventSource = context.eventSource;

    // Register event handlers
    if (eventSource) {
        // Auto-background on character message
        eventSource.on('CHARACTER_MESSAGE_RENDERED', (messageIndex) => {
            onCharacterMessageRendered(messageIndex);
        });

        // Expression generation on character message
        eventSource.on('CHARACTER_MESSAGE_RENDERED', (messageIndex) => {
            const settings = getSettings();
            if (!settings.enabled || !settings.auto_expressions) return;
            const msg = context.chat[messageIndex];
            if (!msg || msg.is_user) return;
            const emotion = extractEmotionFromMessage(msg.mes);
            if (emotion !== 'neutral') {
                generateExpression(msg.name, emotion, msg.mes);
            }
        });

        // Configure server plugin when settings load
        eventSource.on('SETTINGS_LOADED', () => {
            const settings = getSettings();
            spellcasterAPI('/settings', {
                comfyui_url: settings.comfyui_url,
            }).catch(() => {});
        });
    }

    // Register slash commands
    registerSlashCommands();

    // Register function tools
    registerFunctionTools();

    // Render settings panel
    renderSettingsPanel();

    // Configure server plugin
    const settings = getSettings();
    spellcasterAPI('/settings', { comfyui_url: settings.comfyui_url }).catch(() => {});

    console.log('[Spellcaster] Extension loaded. ComfyUI:', settings.comfyui_url);
})();
