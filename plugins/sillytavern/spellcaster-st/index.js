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

import { getContext } from '../../../st-context.js';
import { SlashCommand } from '../../../slash-commands/SlashCommand.js';
import { ARGUMENT_TYPE, SlashCommandArgument } from '../../../slash-commands/SlashCommandArgument.js';
import { SlashCommandParser } from '../../../slash-commands/SlashCommandParser.js';

const PLUGIN_ID = 'spellcaster';
const API_BASE = '/api/plugins/spellcaster';

// Session-local counter for auto-background interval (not persisted)
let _autoBgCounter = 0;

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
    last_scene_description: '',    // Dedup: skip if same scene detected again
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
    const headers = getContext().getRequestHeaders();
    const res = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers,
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
        const res = await fetch(`${API_BASE}/health`, { headers: getContext().getRequestHeaders() });
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
        // Asterisk narration: *enters the tavern* or *They walked into the dark forest...*
        /\*([^*]{10,500})\*/g,
        // Parenthetical: (The scene shifts to a moonlit beach)
        /\(([^)]{10,500})\)/g,
        // Quote-free descriptions of settings
        /(?:scene|setting|background|location|environment|room|place)\s*(?:is|was|changed?\s+to|shifts?\s+to|:)\s*(.{10,300})/gi,
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
//  Story Scaffold — Detect narrative changes that need visual updates
// ═══════════════════════════════════════════════════════════════════

// Tracks the current visual state of the scene
const _sceneState = {
    location: '',           // Current scene location
    characters: [],         // Characters present in scene
    mood: 'neutral',        // Current atmosphere
    lastBodyPose: {},       // { charName: 'standing' | 'sitting' | 'running' | ... }
    lastAttire: {},         // { charName: 'last attire description' }
};

/**
 * Analyze a message and determine what visual changes are needed.
 * Returns an array of action objects: { type, reason, params }
 */
function detectStoryChanges(messageText) {
    const lower = messageText.toLowerCase();
    const changes = [];

    // ── LOCATION CHANGE ──
    // New scene / location transition
    const locationPatterns = [
        /(?:walk|step|enter|arrive|move|travel|head|go|run|flee|teleport|portal|transport)\w*\s+(?:into|to|toward|through|inside|outside|across|down|up)\s+(?:the\s+|a\s+)?([^.,!?*"]{8,80})/gi,
        /(?:scene\s+(?:shifts?|changes?|moves?|cuts?)\s+to|now\s+(?:in|at|inside|outside))\s+(?:the\s+|a\s+)?([^.,!?*"]{8,80})/gi,
        /(?:they\s+(?:are|were)\s+now\s+(?:in|at))\s+(?:the\s+|a\s+)?([^.,!?*"]{8,80})/gi,
    ];
    for (const p of locationPatterns) {
        const m = p.exec(messageText);
        if (m && m[1].trim().length > 5) {
            const newLoc = m[1].trim();
            if (newLoc !== _sceneState.location) {
                changes.push({ type: 'location_change', reason: `Moved to: ${newLoc}`, params: { location: newLoc } });
            }
        }
    }

    // ── CHARACTER ENTERS/EXITS ──
    const enterPatterns = [
        /(\w+)\s+(?:enters?|arrives?|appears?|joins?|walks?\s+in|steps?\s+(?:in|into|forward))/gi,
        /(?:a\s+(?:new\s+)?(?:figure|person|stranger|character|woman|man|elf|dwarf|knight|mage|warrior))\s+(?:enters?|appears?|arrives?|steps?\s+(?:in|forward|out))/gi,
    ];
    for (const p of enterPatterns) {
        const m = p.exec(messageText);
        if (m) {
            changes.push({ type: 'character_enter', reason: `Character entered: ${m[0].substring(0, 40)}`, params: {} });
        }
    }

    const exitPatterns = [
        /(\w+)\s+(?:leaves?|exits?|departs?|disappears?|walks?\s+(?:away|out|off)|storms?\s+(?:off|out)|runs?\s+(?:away|off))/gi,
        /(?:watch(?:es)?|see)\s+(?:\w+\s+)?(?:leave|depart|vanish|disappear|walk\s+away)/gi,
    ];
    for (const p of exitPatterns) {
        const m = p.exec(messageText);
        if (m) {
            changes.push({ type: 'character_exit', reason: `Character left: ${m[0].substring(0, 40)}`, params: {} });
        }
    }

    // ── POSE / POSITION CHANGE ──
    const poseKeywords = {
        'sitting': ['sits? down', 'takes? a seat', 'collapses? into', 'settles? into', 'slumps?', 'seated'],
        'standing': ['stands? up', 'rises?', 'gets? up', 'on (?:her|his|their) feet'],
        'running': ['runs?', 'sprints?', 'dashes?', 'bolts?', 'flees?', 'charges?'],
        'fighting': ['attacks?', 'swings?', 'strikes?', 'slashes?', 'parries?', 'blocks?', 'fights?', 'duels?', 'clashes?'],
        'kneeling': ['kneels?', 'drops? to .{0,10}knees?', 'genuflects?'],
        'lying': ['falls?', 'collapses?', 'lies? down', 'falls? (?:to|on) the (?:ground|floor)', 'knocked (?:down|out)'],
        'sneaking': ['sneaks?', 'creeps?', 'tiptoes?', 'crouches?', 'hides?', 'skulks?'],
        'dancing': ['dances?', 'twirls?', 'spins?', 'waltzes?'],
        'mounted': ['mounts?', 'climbs? (?:on|onto)', 'rides?', 'on (?:horse|dragon|mount)'],
    };
    for (const [pose, patterns] of Object.entries(poseKeywords)) {
        for (const pat of patterns) {
            if (new RegExp(pat, 'i').test(lower)) {
                changes.push({ type: 'pose_change', reason: `Pose: ${pose}`, params: { pose } });
                break;
            }
        }
    }

    // ── APPEARANCE / ATTIRE CHANGE ──
    const attirePatterns = [
        /(?:changes?\s+(?:into|to)|puts?\s+on|dons?|wears?|dressed\s+in|wearing)\s+([^.,!?*"]{8,60})/gi,
        /(?:removes?\s+(?:her|his|their)|takes?\s+off|strips?\s+off)\s+([^.,!?*"]{5,40})/gi,
        /(?:armor|cloak|robe|dress|gown|uniform|outfit|costume|disguise|mask)\s+(?:on|off)/gi,
    ];
    for (const p of attirePatterns) {
        const m = p.exec(messageText);
        if (m) {
            changes.push({ type: 'attire_change', reason: `Attire: ${m[0].substring(0, 50)}`, params: { attire: m[1]?.trim() || m[0].trim() } });
        }
    }

    // ── IMPORTANT OBJECT APPEARS ──
    const objectPatterns = [
        /(?:draws?|unsheathes?|pulls?\s+out|brandishes?|raises?)\s+(?:a\s+|the\s+)?([^.,!?*"]{4,40}(?:sword|blade|weapon|staff|wand|bow|dagger|axe|hammer|shield|gun|pistol|rifle))/gi,
        /(?:opens?\s+(?:a\s+|the\s+)?(?:chest|box|door|gate|portal|book|scroll|letter|map))/gi,
        /(?:a\s+(?:glowing|shining|ancient|magical|mysterious|golden|dark)\s+[^.,!?*"]{3,30})\s+(?:appears?|materializes?|emerges?|floats?)/gi,
        /(?:holds?\s+up|reveals?|presents?|shows?)\s+(?:a\s+|the\s+)?([^.,!?*"]{5,50})/gi,
    ];
    for (const p of objectPatterns) {
        const m = p.exec(messageText);
        if (m) {
            changes.push({ type: 'object_appear', reason: `Object: ${m[0].substring(0, 50)}`, params: {} });
        }
    }

    // ── WEATHER / TIME / ATMOSPHERE SHIFT ──
    const atmospherePatterns = [
        /(?:sun\s+(?:sets?|rises?)|dawn\s+breaks?|night\s+falls?|darkness\s+(?:falls?|descends?)|morning\s+(?:comes?|arrives?))/gi,
        /(?:rain\s+(?:begins?|starts?|pours?)|storm\s+(?:rolls?|breaks?|arrives?)|thunder|lightning|snow\s+(?:begins?|falls?))/gi,
        /(?:fog\s+(?:rolls?|creeps?|descends?)|mist\s+(?:rises?|thickens?)|smoke\s+(?:fills?|billows?))/gi,
        /(?:fire\s+(?:breaks?\s+out|erupts?|spreads?)|explosion|earthquake|ground\s+shakes?)/gi,
    ];
    for (const p of atmospherePatterns) {
        const m = p.exec(messageText);
        if (m) {
            changes.push({ type: 'atmosphere_change', reason: `Atmosphere: ${m[0].substring(0, 50)}`, params: {} });
        }
    }

    // ── INTERPERSONAL DYNAMICS ──
    const dynamicPatterns = [
        { type: 'interaction_intimate', patterns: [/(?:kiss(?:es)?|embraces?|holds?\s+(?:her|him|them)\s+close|pulls?\s+(?:her|him|them)\s+(?:close|into)|hugs?|caresses?)/gi] },
        { type: 'interaction_conflict', patterns: [/(?:argues?|shouts?\s+at|yells?\s+at|screams?\s+at|confronts?|accuses?|threatens?|pushes?\s+(?:away|back)|slaps?|punches?)/gi] },
        { type: 'interaction_dramatic', patterns: [/(?:betrays?|reveals?\s+(?:the\s+truth|a\s+secret)|confesses?|breaks?\s+down|cries?\s+out|falls?\s+to|dies?|killed|mortally\s+wound)/gi] },
    ];
    for (const { type, patterns } of dynamicPatterns) {
        for (const p of patterns) {
            const m = p.exec(messageText);
            if (m) {
                changes.push({ type, reason: m[0].substring(0, 50), params: {} });
                break;
            }
        }
    }

    return changes;
}

/**
 * Given detected changes, determine which visual regeneration actions to take.
 * Returns actions to execute: { action: 'scene'|'body'|'composite', ... }
 */
function planVisualUpdates(changes) {
    const actions = [];
    let needsNewScene = false;
    let needsNewBodies = false;
    let needsRecomposite = false;

    for (const change of changes) {
        switch (change.type) {
            case 'location_change':
                needsNewScene = true;
                needsNewBodies = true;  // New location likely means new attire
                break;
            case 'character_enter':
            case 'character_exit':
                needsRecomposite = true;  // Same scene, different characters
                break;
            case 'pose_change':
                needsNewBodies = true;  // Need new body in different pose
                break;
            case 'attire_change':
                needsNewBodies = true;
                break;
            case 'object_appear':
                needsRecomposite = true;  // Scene needs updating with new element
                break;
            case 'atmosphere_change':
                needsNewScene = true;  // Weather/time changed the scene look
                break;
            case 'interaction_intimate':
            case 'interaction_conflict':
            case 'interaction_dramatic':
                needsRecomposite = true;  // Character positioning changed
                needsNewBodies = true;   // Body poses need updating
                break;
        }
    }

    // Scene change is the most expensive — includes everything
    if (needsNewScene) {
        actions.push({ action: 'full_scene', changes });
    } else if (needsNewBodies) {
        actions.push({ action: 'regenerate_bodies', changes });
    } else if (needsRecomposite) {
        actions.push({ action: 'recomposite', changes });
    }

    return actions;
}

// ═══════════════════════════════════════════════════════════════════
//  Feature: Auto-Background Generation
// ═══════════════════════════════════════════════════════════════════

async function onCharacterMessageRendered(messageIndex) {
    const settings = getSettings();
    if (!settings.enabled || !settings.auto_background) return;

    const context = getContext();
    const message = context.chat[messageIndex];
    if (!message || message.is_user) return;

    // ── Scaffold: detect what changed in the story ──
    const storyChanges = detectStoryChanges(message.mes);
    const visualActions = planVisualUpdates(storyChanges);

    // Also check for scene description (original extraction for backward compat)
    const sceneDesc = extractSceneDescription(message.mes);

    // Decide whether to trigger visual update:
    // 1. Scaffold detected a change worth rendering
    // 2. OR we hit the message counter AND there's a new scene description
    const scaffoldTriggered = visualActions.length > 0;

    if (!scaffoldTriggered) {
        // Fall back to interval-based scene extraction
        _autoBgCounter = (_autoBgCounter || 0) + 1;
        if (_autoBgCounter < settings.auto_background_interval) return;
        _autoBgCounter = 0;

        if (!sceneDesc || sceneDesc === settings.last_scene_description) return;
    }

    // Build the scene description from scaffold context or extraction
    const effectiveScene = sceneDesc || settings.last_scene_description || 'the current scene';
    if (sceneDesc) {
        settings.last_scene_description = sceneDesc;
        saveSettings();
    }

    // Build attire hints from scaffold changes
    let attireHint = '';
    let poseHint = '';
    for (const change of storyChanges) {
        if (change.type === 'attire_change' && change.params.attire) attireHint = change.params.attire;
        if (change.type === 'pose_change' && change.params.pose) poseHint = change.params.pose;
        if (change.type === 'interaction_intimate') poseHint = 'embracing, close together';
        if (change.type === 'interaction_conflict') poseHint = 'confrontational stance, tense body language';
    }

    const changeReasons = storyChanges.map(c => c.reason).join(', ');
    console.log(`[Spellcaster] Scaffold: ${scaffoldTriggered ? changeReasons : 'interval'} → "${effectiveScene.substring(0, 50)}..."`);

    try {
        let result;
        const studioStatus = await fetch(`${API_BASE}/studio/assets`).then(r => r.json()).catch(() => null);
        const readyChars = studioStatus ? Object.entries(studioStatus.characters || {})
            .filter(([_, a]) => a.body)
            .map(([name]) => name) : [];

        if (readyChars.length > 0) {
            const characters = readyChars.map((name, i) => ({
                name,
                attire: attireHint
                    ? `${name}, ${attireHint}`
                    : `${name}, clothing appropriate for: ${effectiveScene}`,
                placement: {
                    x: readyChars.length === 1 ? 50 :
                       readyChars.length === 2 ? (i === 0 ? 35 : 65) :
                       (25 + i * 25),
                    y: 70,
                    scale: readyChars.length <= 2 ? 0.5 : 0.4,
                },
            }));

            result = await spellcasterAPI('/studio/scene', {
                description: effectiveScene,
                characters,
            });
        } else {
            // No studio characters — just generate the scene background
            result = await spellcasterAPI('/scene', {
                description: effectiveScene,
                width: settings.scene_width,
                height: settings.scene_height,
            });
        }

        if (result.bg_filename) {
            const context = getContext();
            if (SlashCommandParser) {
                await SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
            }
            const composited = result.characters_composited || 0;
            const label = composited > 0
                ? `Scene + ${composited} character(s): ${sceneDesc.substring(0, 40)}...`
                : `Scene: ${sceneDesc.substring(0, 50)}...`;
            toastr.info(label, 'Spellcaster');
        } else if (result.images?.[0]) {
            toastr.info('Background generated (save manually)', 'Spellcaster');
        }
    } catch (e) {
        console.error('[Spellcaster] Auto-background failed:', e);
        toastr.warning(`Background generation failed: ${e.message}`, 'Spellcaster');
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
            // Save as expression sprite so ST can use it for character expressions
            await spellcasterAPI('/save-expression', {
                character_name: characterName,
                emotion: emotion,
                image_base64: result.images[0].base64,
            });
            console.log(`[Spellcaster] Saved ${emotion} expression for ${characterName}`);
            toastr.info(`${characterName}: ${emotion} expression generated`, 'Spellcaster');
        }
    } catch (e) {
        console.error(`[Spellcaster] Expression generation failed for ${characterName}:`, e);
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Slash Commands
// ═══════════════════════════════════════════════════════════════════

function registerSlashCommands() {
    // Modern SillyTavern API: use ES module imports (top of file)
    // SlashCommandParser, SlashCommand, ARGUMENT_TYPE imported directly

    // /scene [description] — Generate and set a scene background
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
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
                    await SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
                    return `Scene generated: ${result.bg_filename}`;
                }
                return 'Scene generated (no background directory configured)';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Generate a scene background from a description and set it as the chat background.',
    }));

    // /portrait [description] — Generate a character portrait
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
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
    }));

    // /restyle [style] — Restyle current character's avatar (persists to disk with backup)
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
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
                    // Save restyled avatar to disk (backs up original as .bak.png)
                    await spellcasterAPI('/save-avatar', {
                        avatar_filename: char.avatar,
                        image_base64: result.images[0].base64,
                    });

                    const imgTag = `![restyled](data:image/png;base64,${result.images[0].base64})`;
                    toastr.success(`${char.name} restyled! (original backed up — use /restyle-undo to revert)`, 'Spellcaster');
                    return imgTag;
                }
                return 'Restyle failed';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Restyle the current character\'s avatar. Original is backed up automatically — use /restyle-undo to revert.',
    }));

    // /restyle-all [style] — Restyle ALL character avatars in current group/chat
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
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
                        // Save restyled avatar to disk (backs up original as .bak.png)
                        await spellcasterAPI('/save-avatar', {
                            avatar_filename: char.avatar,
                            image_base64: result.images[0].base64,
                        });
                        restyled++;
                        toastr.info(`Restyled ${char.name} (${restyled}/${chars.length})`, 'Spellcaster');
                    }
                } catch (e) {
                    console.error(`[Spellcaster] Restyle failed for ${char.name}:`, e);
                }
            }
            return `Restyled ${restyled}/${chars.length} characters (originals backed up — use /restyle-undo-all to revert)`;
        },
        helpString: 'Restyle ALL character avatars. Originals are backed up — use /restyle-undo-all to revert.',
    }));

    // /restyle-undo — Restore the current character's original avatar from backup
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'restyle-undo',
        callback: async (args, value) => {
            const context = getContext();
            const char = context.characters[context.characterId];
            if (!char?.avatar) return 'No character selected or no avatar';

            try {
                await spellcasterAPI('/restore-avatar', { avatar_filename: char.avatar });
                toastr.success(`${char.name}'s original avatar restored!`, 'Spellcaster');
                return `Restored ${char.name}'s original avatar`;
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Restore the current character\'s original avatar (before restyle).',
    }));

    // /restyle-undo-all — Restore ALL character avatars from backups
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'restyle-undo-all',
        callback: async (args, value) => {
            const context = getContext();
            const chars = context.characters.filter(c => c.avatar);
            let restored = 0;

            for (const char of chars) {
                try {
                    await spellcasterAPI('/restore-avatar', { avatar_filename: char.avatar });
                    restored++;
                } catch {
                    // No backup = was never restyled, skip silently
                }
            }
            if (restored > 0) {
                toastr.success(`Restored ${restored} avatar(s) to their originals!`, 'Spellcaster');
            } else {
                toastr.info('No backups found — no avatars were restyled.', 'Spellcaster');
            }
            return `Restored ${restored} avatar(s)`;
        },
        helpString: 'Restore ALL character avatars to their originals (before restyle).',
    }));

    // /animate [prompt] — Animate the current character's avatar as a short GIF
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'animate',
        callback: async (args, value) => {
            const context = getContext();
            const char = context.characters[context.characterId];
            if (!char?.avatar) return 'No character with avatar selected. Select a character first.';

            toastr.info(`Animating ${char.name}...`, 'Spellcaster');
            try {
                const avatarUrl = `/characters/${char.avatar}`;
                const avatarRes = await fetch(avatarUrl);
                if (!avatarRes.ok) return `Failed to fetch avatar: ${avatarRes.status}`;
                const avatarBlob = await avatarRes.blob();
                const base64 = await blobToBase64(avatarBlob);

                const result = await spellcasterAPI('/animate', {
                    image_base64: base64,
                    prompt: value || 'subtle breathing, gentle hair movement, living portrait',
                    length: 8,
                });

                if (result.videos?.[0]) {
                    const gifTag = `![animated](data:image/gif;base64,${result.videos[0].base64})`;
                    toastr.success(`${char.name} animated!`, 'Spellcaster');
                    return gifTag;
                }
                if (result.images?.[0]) {
                    const imgTag = `![animated](data:image/png;base64,${result.images[0].base64})`;
                    return imgTag;
                }
                return 'Animation generation completed but no output received';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Animate the current character\'s avatar as a short looping GIF.',
    }));

    // ═══════════════════════════════════════════════════════════════
    //  Magic Studios — Character Pipeline Commands
    // ═══════════════════════════════════════════════════════════════

    // /studio-cast — Generate face model from current character's avatar
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'studio-cast',
        callback: async (args, value) => {
            const context = getContext();
            const char = context.characters[context.characterId];
            if (!char?.avatar) return 'No character with avatar selected';

            toastr.info(`Casting ${char.name}... (generating face model)`, 'Magic Studios');
            try {
                const avatarRes = await fetch(`/characters/${char.avatar}`);
                if (!avatarRes.ok) return `Failed to fetch avatar: ${avatarRes.status}`;
                const base64 = await blobToBase64(await avatarRes.blob());

                const result = await spellcasterAPI('/studio/cast', {
                    avatar_base64: base64,
                    character_name: char.name,
                });

                if (result.images?.[0]) {
                    toastr.success(`${char.name} cast! Face model: ${result.face_model}`, 'Magic Studios');
                    return `![cast](data:image/png;base64,${result.images[0].base64})\n*${char.name} — face model saved as ${result.face_model}*`;
                }
                return `${char.name} cast successfully (face model: ${result.face_model})`;
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Generate a face model from the current character\'s avatar (Act 1: Casting Polaroids).',
    }));

    // /studio-cast-all — Cast all characters in the current chat
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'studio-cast-all',
        callback: async (args, value) => {
            const context = getContext();
            const chars = context.characters.filter(c => c.avatar);
            if (chars.length === 0) return 'No characters with avatars found';

            toastr.info(`Casting ${chars.length} characters...`, 'Magic Studios');
            let cast = 0;

            for (const char of chars) {
                try {
                    const avatarRes = await fetch(`/characters/${char.avatar}`);
                    if (!avatarRes.ok) continue;
                    const base64 = await blobToBase64(await avatarRes.blob());

                    await spellcasterAPI('/studio/cast', {
                        avatar_base64: base64,
                        character_name: char.name,
                    });
                    cast++;
                    toastr.info(`Cast ${char.name} (${cast}/${chars.length})`, 'Magic Studios');
                } catch (e) {
                    console.error(`[Studios] Cast failed for ${char.name}:`, e);
                }
            }
            toastr.success(`Cast ${cast}/${chars.length} characters!`, 'Magic Studios');
            return `Cast ${cast}/${chars.length} characters — face models ready`;
        },
        helpString: 'Generate face models for ALL characters in the chat (batch cast).',
    }));

    // /studio-body [description] — Generate full-body transparent PNG
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'studio-body',
        callback: async (args, value) => {
            const context = getContext();
            const char = context.characters[context.characterId];
            if (!char) return 'No character selected';

            const description = value || `${char.description || char.name}, casual clothing, neutral background`;
            toastr.info(`Generating body for ${char.name}...`, 'Magic Studios');
            try {
                const result = await spellcasterAPI('/studio/body', {
                    character_name: char.name,
                    description: description,
                });

                if (result.images?.[0]) {
                    toastr.success(`${char.name} body generated!`, 'Magic Studios');
                    return `![body](data:image/png;base64,${result.images[0].base64})\n*${char.name} — transparent body ready for scene compositing*`;
                }
                return 'Body generation completed but no output received';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Generate a full-body transparent PNG for the current character (Act 2: Body Double). Include attire in the description.',
    }));

    // /studio-body-all [attire] — Generate bodies for all cast characters
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'studio-body-all',
        callback: async (args, value) => {
            const context = getContext();
            const chars = context.characters.filter(c => c.avatar);

            toastr.info(`Generating bodies for all cast characters...`, 'Magic Studios');
            let done = 0;

            for (const char of chars) {
                try {
                    const desc = value
                        ? `${char.description || char.name}, ${value}`
                        : `${char.description || char.name}, casual clothing, natural pose`;
                    await spellcasterAPI('/studio/body', {
                        character_name: char.name,
                        description: desc,
                    });
                    done++;
                    toastr.info(`Body: ${char.name} (${done}/${chars.length})`, 'Magic Studios');
                } catch {
                    // Not cast yet — skip
                }
            }
            return `Generated ${done} body doubles — ready for scene compositing`;
        },
        helpString: 'Generate bodies for all cast characters. Optional: specify attire (e.g., /studio-body-all medieval fantasy clothing).',
    }));

    // /studio-scene [description] — Generate scene with characters composited in
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'studio-scene',
        callback: async (args, value) => {
            if (!value) return 'Usage: /studio-scene [scene description]. Characters with bodies will be composited in.';

            toastr.info(`Generating scene with characters...`, 'Magic Studios');
            try {
                // Get all characters in current group chat
                const context = getContext();
                const groupChars = context.groups?.[context.groupId]?.members || [];
                const charNames = groupChars
                    .map(id => context.characters.find(c => c.avatar === id || c.name === id))
                    .filter(Boolean)
                    .map(c => c.name);

                // Build character list with placement
                const characters = charNames.map((name, i) => ({
                    name,
                    attire: value.includes('tavern') ? `${name}, medieval fantasy tavern clothing` :
                            value.includes('forest') ? `${name}, adventurer outdoor clothing` :
                            value.includes('castle') || value.includes('throne') ? `${name}, royal court attire` :
                            value.includes('ship') ? `${name}, pirate seafaring clothing` :
                            value.includes('battle') ? `${name}, battle armor and weapons` :
                            undefined,  // Use existing body
                    placement: {
                        x: charNames.length === 1 ? 50 :
                           charNames.length === 2 ? (i === 0 ? 35 : 65) :
                           (25 + i * 25),
                        y: 70,
                        scale: charNames.length <= 2 ? 0.5 : 0.4,
                    },
                }));

                const result = await spellcasterAPI('/studio/scene', {
                    description: value,
                    characters: characters.length > 0 ? characters : undefined,
                });

                if (result.bg_filename) {
                    const ctx = getContext();
                    await SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
                }

                if (result.images?.[0]) {
                    const composited = result.characters_composited || 0;
                    const label = composited > 0
                        ? `*Scene with ${composited} character(s) composited and harmonized*`
                        : `*Scene generated (no characters had bodies ready)*`;
                    toastr.success(`Scene complete! ${composited} characters placed.`, 'Magic Studios');
                    return `![scene](data:image/png;base64,${result.images[0].base64})\n${label}`;
                }
                return 'Scene generated';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Generate a scene background with characters composited in. Characters are auto-dressed for the scene.',
    }));

    // /studio-status — Show which characters are ready
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'studio-status',
        callback: async (args, value) => {
            try {
                const result = await fetch(`${API_BASE}/studio/assets`).then(r => r.json());
                const chars = result.characters || {};
                const names = Object.keys(chars);
                if (names.length === 0) return 'No characters prepared. Use /studio-cast-all first.';

                const lines = names.map(n => {
                    const a = chars[n];
                    const castIcon = a.cast ? '✅' : '❌';
                    const bodyIcon = a.body ? '✅' : '❌';
                    return `${n}: Cast ${castIcon} | Body ${bodyIcon}`;
                });
                return `**Magic Studios Status:**\n${lines.join('\n')}`;
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Show which characters have been cast and have bodies ready.',
    }));

    // /spellcaster — Toggle extension on/off
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'spellcaster',
        callback: async (args, value) => {
            const settings = getSettings();
            const cmd = (value || '').trim().toLowerCase().replace(/\s+/g, ' ');
            if (cmd === 'on') {
                settings.enabled = true;
                saveSettings();
                return 'Spellcaster enabled';
            } else if (cmd === 'off') {
                settings.enabled = false;
                saveSettings();
                return 'Spellcaster disabled';
            } else if (cmd === 'auto-bg on' || cmd === 'auto bg on') {
                settings.auto_background = true;
                saveSettings();
                return 'Auto-background generation enabled';
            } else if (cmd === 'auto-bg off' || cmd === 'auto bg off') {
                settings.auto_background = false;
                saveSettings();
                return 'Auto-background generation disabled';
            } else if (cmd) {
                return `Unknown command: "${value}". Usage: /spellcaster [on|off|auto-bg on|auto-bg off]`;
            } else {
                return `Spellcaster: ${settings.enabled ? 'ON' : 'OFF'} | ` +
                       `Auto-BG: ${settings.auto_background ? 'ON' : 'OFF'} | ` +
                       `ComfyUI: ${settings.comfyui_url}`;
            }
        },
        helpString: 'Toggle Spellcaster features. Usage: /spellcaster [on|off|auto-bg on|auto-bg off]',
    }));

    // ══════════════════════════════════════════════════════════════════
    // R111: Cross-plugin commands. Slash commands send the current or
    // argument-supplied image to another Spellcaster surface
    // (💎 Resolve / GIMP / Darktable) via the Guild's asset gallery +
    // event bus. /sc-inbox pulls anything pending for this
    // SillyTavern instance.
    // ══════════════════════════════════════════════════════════════════

    // Find the most recent image URL in the chat — fallback when the
    // caller didn't pass one explicitly. Walks backward through
    // messages looking for an <img src=...> tag.
    function _findLastChatImage() {
        const ctx = getContext();
        const msgs = ctx.chat || [];
        for (let i = msgs.length - 1; i >= 0; i--) {
            const m = msgs[i];
            // SillyTavern stores images either as message.extra.image
            // (base64 or URL) or inline in mes HTML.
            const inl = m?.extra?.image;
            if (inl) return inl;
            const html = (m?.mes || '');
            const m1 = html.match(/!\[[^\]]*\]\(([^)]+)\)/);
            if (m1) return m1[1];
            const m2 = html.match(/<img[^>]+src=["']([^"']+)["']/);
            if (m2) return m2[1];
        }
        return null;
    }

    async function _sendToTarget(target, friendly, imgArg) {
        const img = (imgArg && imgArg.trim()) || _findLastChatImage();
        if (!img) {
            return `No image to send. Usage: /sc-send-to-${target} <url or data-url>, or post an image in chat first.`;
        }
        const body = img.startsWith('data:')
            ? { target, image_data_url: img, title: `From SillyTavern → ${friendly}` }
            : { target, image_url: img,      title: `From SillyTavern → ${friendly}` };
        toastr.info(`Sending to ${friendly}…`, 'Spellcaster');
        try {
            const result = await spellcasterAPI('/cross/send', body);
            if (result && result.ok) {
                const hint = ({
                    resolve:   "Bridge imports into Resolve's Media Pool automatically.",
                    gimp:      "In GIMP: Spellcaster > Cross-App > 💎 Check Inbox.",
                    darktable: "In Darktable: Check the Spellcaster lib for imported stills.",
                })[target] || '';
                return `💎 Sent to ${friendly} (hash ${String(result.hash).slice(0, 10)}…). ${hint}`;
            }
            return `Send to ${friendly} returned unexpected response: ${JSON.stringify(result).slice(0, 200)}`;
        } catch (e) {
            return `Send to ${friendly} failed: ${e.message}`;
        }
    }

    for (const [target, friendly] of [
        ['resolve',   'DaVinci Resolve'],
        ['gimp',      'GIMP'],
        ['darktable', 'Darktable'],
    ]) {
        SlashCommandParser.addCommandObject(SlashCommand.fromProps({
            name: `sc-send-to-${target}`,
            callback: async (args, value) => _sendToTarget(target, friendly, value),
            helpString: `Send an image to ${friendly}. Takes a URL or data-url; falls back to the most recent chat image.`,
        }));
    }

    // R119: /sc-capabilities — probe the configured ComfyUI's
    // /object_info and report which architectures are installed.
    // Mirrors the Darktable R118 check + the GIMP sentinel probe
    // so editors see a consistent "what's available" answer across
    // every Spellcaster surface.
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'sc-capabilities',
        callback: async () => {
            try {
                const res = await fetch(`${API_BASE}/capabilities`, {
                    headers: getContext().getRequestHeaders(),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    return `Capabilities probe failed: ${err.error || res.status}`;
                }
                const d = await res.json();
                const lines = [`💎 Spellcaster capabilities on ${d.comfyui}:`];
                lines.push(`(${d.node_count} total nodes in /object_info)`);
                lines.push('');
                if (d.available && d.available.length) {
                    lines.push('✓ **Installed:**');
                    for (const a of d.available) lines.push(`  • ${a}`);
                }
                if (d.missing && d.missing.length) {
                    lines.push('');
                    lines.push('✗ **Missing** (features using these will silently fail):');
                    for (const a of d.missing) lines.push(`  • ${a}`);
                }
                return lines.join('\n');
            } catch (e) {
                return `Capabilities error: ${e.message}`;
            }
        },
        helpString: 'Probe the configured ComfyUI and report which Spellcaster architectures are installed (Klein, Flux Kontext, Wan, LTX, SUPIR, etc.).',
    }));

    // /sc-inbox — pull + display pending inbox items for this SillyTavern
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'sc-inbox',
        callback: async () => {
            try {
                const res = await fetch(`${API_BASE}/cross/inbox`, {
                    headers: getContext().getRequestHeaders(),
                });
                if (!res.ok) return `Inbox fetch failed: HTTP ${res.status}`;
                const data = await res.json();
                const msgs = (data && data.messages) || [];
                if (!msgs.length) return '💎 Spellcaster inbox empty.';
                // Render each as markdown image + metadata
                const parts = msgs.map((m, i) => {
                    const d = m.data || {};
                    const src = d.source || '?';
                    const title = d.title || m.kind;
                    const url = d.image_url || '';
                    return `**${i + 1}. From ${src}:** ${title}\n\n` +
                           (url ? `![${title}](${url})` : '(no image url)');
                });
                return `💎 ${msgs.length} item(s) in Spellcaster inbox:\n\n` +
                       parts.join('\n\n---\n\n');
            } catch (e) {
                return `Inbox error: ${e.message}`;
            }
        },
        helpString: 'Pull pending cross-plugin assets sent to SillyTavern and render them in chat.',
    }));
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
                    await SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
                }
                if (result.images?.[0]) {
                    return `![scene](data:image/png;base64,${result.images[0].base64})\n*Scene: ${args.scene_description.substring(0, 80)}...*`;
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
                    return `![portrait](data:image/png;base64,${result.images[0].base64})\n*${args.character_description.substring(0, 60)}...*`;
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
                    await SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
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
            <div>/restyle [style] — transform current avatar (auto-backup)</div>
            <div>/restyle-all [style] — transform ALL avatars (auto-backup)</div>
            <div>/restyle-undo — restore current avatar to original</div>
            <div>/restyle-undo-all — restore ALL avatars to originals</div>
            <div>/animate [prompt] — animate current avatar as GIF</div>
            <div style="margin-top:6px"><strong>Magic Studios:</strong></div>
            <div>/studio-cast — create face model from avatar</div>
            <div>/studio-cast-all — cast all characters</div>
            <div>/studio-body [desc] — generate transparent body</div>
            <div>/studio-body-all [attire] — bodies for all</div>
            <div>/studio-scene [desc] — scene + characters composited</div>
            <div>/studio-status — check readiness</div>
            <div style="margin-top:6px"><strong>System:</strong></div>
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
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = () => reject(new Error('Failed to read image data'));
        reader.readAsDataURL(blob);
    });
}

// ═══════════════════════════════════════════════════════════════════
//  Auto-Cast — Pre-generate face models on startup
// ═══════════════════════════════════════════════════════════════════

/**
 * Auto-cast all characters with avatars in the background.
 * Runs after a short delay to not block UI initialization.
 * Skips characters already cast in this session.
 */
async function autoCastOnStartup() {
    const settings = getSettings();
    if (!settings.enabled) return;

    // Wait for ComfyUI to be reachable
    const connected = await checkHealth();
    if (!connected) {
        console.log('[Spellcaster] ComfyUI offline — skipping auto-cast');
        return;
    }

    const context = getContext();
    const chars = context.characters?.filter(c => c.avatar) || [];
    if (chars.length === 0) return;

    // Check which are already cast
    const status = await fetch(`${API_BASE}/studio/assets`).then(r => r.json()).catch(() => ({ characters: {} }));
    const alreadyCast = new Set(Object.keys(status.characters || {}));

    const toCast = chars.filter(c => !alreadyCast.has(c.name));
    if (toCast.length === 0) {
        console.log(`[Spellcaster] All ${chars.length} characters already cast`);
        return;
    }

    console.log(`[Spellcaster] Auto-casting ${toCast.length} characters in background...`);

    // Also include user persona avatar if available
    const userAvatar = context.user?.avatar;

    let cast = 0;
    let bodied = 0;
    for (const char of toCast) {
        try {
            const avatarUrl = `/characters/${char.avatar}`;
            const avatarRes = await fetch(avatarUrl);
            if (!avatarRes.ok) continue;
            const base64 = await blobToBase64(await avatarRes.blob());

            // Cast — save face model
            await spellcasterAPI('/studio/cast', {
                avatar_base64: base64,
                character_name: char.name,
            });
            cast++;

            // Auto-generate body if the card has a body_description
            const bodyDesc = char.data?.extensions?.spellcaster?.body_description
                          || char.description;
            if (bodyDesc) {
                try {
                    await spellcasterAPI('/studio/body', {
                        character_name: char.name,
                        description: bodyDesc,
                    });
                    bodied++;
                } catch (bodyErr) {
                    console.warn(`[Spellcaster] Auto-body failed for ${char.name}:`, bodyErr.message);
                }
            }
        } catch (e) {
            console.warn(`[Spellcaster] Auto-cast failed for ${char.name}:`, e.message);
        }
    }

    if (cast > 0) {
        console.log(`[Spellcaster] Auto-cast complete: ${cast} cast, ${bodied} bodies`);
        toastr.info(`${cast} cast, ${bodied} body doubles ready`, 'Spellcaster');
    }
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

    // Auto-cast all characters in background (non-blocking, 5s delay)
    setTimeout(() => autoCastOnStartup(), 5000);

    console.log('[Spellcaster] Extension loaded. ComfyUI:', settings.comfyui_url);
})();
