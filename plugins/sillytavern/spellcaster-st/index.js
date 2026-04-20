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
    // Pre-cast every character + generate body doubles on extension
    // load. Off by default — this used to queue 15+ Klein jobs
    // silently on startup, blocking every user-initiated generation
    // for minutes. Opt-in via the settings toggle.
    auto_cast: false,
    scene_width: 1280,
    scene_height: 720,
    portrait_width: 400,
    portrait_height: 600,
    restyle_denoise: 0.55,
    restyle_prompt: 'photorealistic portrait, professional photography, detailed skin texture, 8k',
    last_scene_description: '',    // Dedup: skip if same scene detected again

    // Wizard-selected defaults. Empty strings mean "let the server auto-pick
    // based on what's installed" (backward compatible — pre-wizard users
    // continue to get automatic model selection by keyword priority).
    // Populated by the first-run wizard or by /spellcaster-wizard.
    image_model: '',               // Specific checkpoint filename, or '' for auto
    video_backend: 'auto',         // 'auto' | 'wan22' | 'none'
    quality_profile: 'balanced',   // 'fast' | 'balanced' | 'max'
    wizard_completed: false,       // First-run wizard flag; shown once on load

    // R120: auto-drain the cross-interface inbox so assets sent from
    // GIMP / Resolve / Darktable appear in chat without the user
    // having to type /sc-inbox. Off by default — an always-on poll
    // against the Guild is cheap but not zero-cost, and some users
    // don't use the cross-interface bridge at all.
    auto_inbox_poll: false,
    auto_inbox_interval_s: 30,     // Poll cadence when auto_inbox_poll is on
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

// Re-entrancy guard for the auto-background handler. WAN / Klein
// generations take 20-120 s; if two character messages render inside
// that window the naive handler fires two concurrent /studio/scene
// requests, ComfyUI queues them serially, and the user perceives the
// background "never updating" because each render is already stale
// by the time it lands. Keep one generation in flight at a time —
// the next message that arrives after completion gets its own pass.
let _autoBgInFlight = false;

async function onCharacterMessageRendered(messageIndex) {
    const settings = getSettings();
    if (!settings.enabled || !settings.auto_background) return;
    if (_autoBgInFlight) {
        console.log('[Spellcaster] Auto-bg already in flight — skipping message', messageIndex);
        return;
    }

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

    _autoBgInFlight = true;
    try {
        let result;
        const studioStatus = await fetch(`${API_BASE}/studio/assets`).then(r => r.json()).catch(() => null);
        const readyChars = studioStatus ? Object.entries(studioStatus.characters || {})
            .filter(([_, a]) => a.body)
            .map(([name]) => name) : [];

        if (readyChars.length > 0) {
            // AILab_ImageCombiner position_x/y are percentages [0..100].
            // Cap the composited crowd at 4 bodies to avoid a clown-car
            // horizontal line, then distribute evenly across 15..85.
            const toComp = readyChars.slice(0, 4);
            const denom = Math.max(1, toComp.length - 1);
            const characters = toComp.map((name, i) => ({
                name,
                attire: attireHint
                    ? `${name}, ${attireHint}`
                    : `${name}, clothing appropriate for: ${effectiveScene}`,
                placement: {
                    x: toComp.length === 1 ? 50
                        : toComp.length === 2 ? (i === 0 ? 35 : 65)
                        : Math.round(15 + (i * 70) / denom),
                    y: 70,
                    scale: toComp.length <= 2 ? 0.5 : 0.4,
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
            // sceneDesc can be null when the scaffold triggered via
            // a change type that doesn't carry a description
            // (character_enter / pose_change / etc). Fall back to
            // the effectiveScene text for the toast.
            const summary = (sceneDesc || effectiveScene || '').slice(0, 50);
            const label = composited > 0
                ? `Scene + ${composited} character(s): ${summary}…`
                : `Scene: ${summary}…`;
            toastr.info(label, 'Spellcaster');
        } else if (result.images?.[0]) {
            toastr.info('Background generated (save manually)', 'Spellcaster');
        }
    } catch (e) {
        console.error('[Spellcaster] Auto-background failed:', e);
        toastr.warning(`Background generation failed: ${e.message}`, 'Spellcaster');
    } finally {
        _autoBgInFlight = false;
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

    // /edit [instruction] — Edit-by-prompt on the current avatar.
    // Routes through the /edit endpoint's Klein → Kontext → SDXL
    // waterfall. Unlike /restyle (which expects a full style target),
    // /edit takes a natural-language instruction:
    //   /edit make her hair red
    //   /edit add a wizard hat
    //   /edit remove the glasses
    // Result is shown inline; unlike /restyle it does NOT persist to
    // disk — use /restyle when you want to replace the avatar.
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'edit',
        callback: async (args, value) => {
            if (!value) return 'Usage: /edit [instruction, e.g. "change the hair to red"]';
            const context = getContext();
            const char = context.characters[context.characterId];
            if (!char?.avatar) return 'No character with avatar selected.';

            toastr.info(`Editing ${char.name}...`, 'Spellcaster');
            try {
                const avatarRes = await fetch(`/characters/${char.avatar}`);
                if (!avatarRes.ok) return `Failed to fetch avatar: ${avatarRes.status}`;
                const base64 = await blobToBase64(await avatarRes.blob());

                const result = await spellcasterAPI('/edit', {
                    image_base64: base64,
                    instruction: value,
                });
                if (result.images?.[0]) {
                    const engine = result.engine || 'edit';
                    toastr.success(`${char.name} edited via ${engine.toUpperCase()}`, 'Spellcaster');
                    return `![edited](data:image/png;base64,${result.images[0].base64})\n*Edit: ${value} — engine: ${engine}*`;
                }
                return 'Edit completed but no output received';
            } catch (e) {
                return `Error: ${e.message}`;
            }
        },
        helpString: 'Edit the current avatar via natural-language instruction (Klein 2 / Flux Kontext / SDXL). Identity is preserved; the instruction drives the change.',
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

                // Build character list with placement (x,y are percentages 0..100)
                const toComp = charNames.slice(0, 4);
                const denom2 = Math.max(1, toComp.length - 1);
                const characters = toComp.map((name, i) => ({
                    name,
                    attire: value.includes('tavern') ? `${name}, medieval fantasy tavern clothing` :
                            value.includes('forest') ? `${name}, adventurer outdoor clothing` :
                            value.includes('castle') || value.includes('throne') ? `${name}, royal court attire` :
                            value.includes('ship') ? `${name}, pirate seafaring clothing` :
                            value.includes('battle') ? `${name}, battle armor and weapons` :
                            undefined,  // Use existing body
                    placement: {
                        x: toComp.length === 1 ? 50
                            : toComp.length === 2 ? (i === 0 ? 35 : 65)
                            : Math.round(15 + (i * 70) / denom2),
                        y: 70,
                        scale: toComp.length <= 2 ? 0.5 : 0.4,
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

    // /spellcaster-wizard — re-open the first-run configuration wizard
    // anytime. Same modal the user sees on a brand-new install.
    SlashCommandParser.addCommandObject(SlashCommand.fromProps({
        name: 'spellcaster-wizard',
        callback: async () => {
            openWizard();
            return 'Opening Spellcaster wizard…';
        },
        helpString: 'Run the Spellcaster configuration wizard (ComfyUI URL, image model, video backend, quality, automation).',
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
                // Sanitize before markdown interpolation — source, title
                // and url all originate from whatever interface published
                // the event. An attacker-controlled title containing
                // `](javascript:alert(1))` would otherwise inject into
                // both the link and the alt-text.
                const _stripMd = (s) => String(s == null ? '' : s)
                    .replace(/[\r\n]+/g, ' ')
                    .replace(/[\[\]()`*_~]/g, '')
                    .slice(0, 200);
                const _urlOk = (u) => {
                    if (typeof u !== 'string' || !u) return false;
                    // Allow only http(s), data:image/*, or a relative /api/ path.
                    if (u.startsWith('/api/')) return true;
                    try {
                        const p = new URL(u);
                        if (p.protocol === 'http:' || p.protocol === 'https:') return true;
                        if (p.protocol === 'data:' && /^data:image\//i.test(u)) return true;
                    } catch { return false; }
                    return false;
                };
                // Render each as markdown image + metadata
                const parts = msgs.map((m, i) => {
                    const d = m.data || {};
                    const src = _stripMd(d.source || '?');
                    const title = _stripMd(d.title || m.kind);
                    const rawUrl = d.image_url || '';
                    const url = _urlOk(rawUrl) ? rawUrl.replace(/[\s)]/g, encodeURIComponent) : '';
                    return `**${i + 1}. From ${src}:** ${title}\n\n` +
                           (url ? `![${title}](${url})` : '(no usable image url)');
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

// LLMs sometimes pass `null`, an empty string, or an object as a
// "string" argument; some models also produce multi-kilobyte
// hallucinated descriptions. Normalize here before the value lands in
// a network payload or a markdown message.
const _FN_MAX_ARG_CHARS = 2000;
function _ftString(v) {
    if (v == null) return '';
    return String(v).slice(0, _FN_MAX_ARG_CHARS);
}

// Markdown-safe truncation for labels that land inside `*italic*` /
// `![alt](...)` constructions. Strips characters that would break out
// of the markdown token, replaces newlines, caps length.
function _ftLabel(s, max = 80) {
    return String(s ?? '')
        .replace(/[\r\n]+/g, ' ')
        .replace(/[\[\]()*_`~]/g, '')
        .slice(0, max);
}

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
            const desc = _ftString(args && args.scene_description);
            if (!desc) return 'Scene generation skipped: missing description.';
            try {
                const settings = getSettings();
                const result = await spellcasterAPI('/scene', {
                    description: desc,
                    width: settings.scene_width,
                    height: settings.scene_height,
                });
                if (result.bg_filename && args.set_as_background !== false) {
                    await SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
                }
                if (result.images?.[0]) {
                    return `![scene](data:image/png;base64,${result.images[0].base64})\n*Scene: ${_ftLabel(desc)}*`;
                }
                return `Scene generated: ${_ftLabel(desc)}`;
            } catch (e) {
                return `Failed to generate scene: ${e && e.message ? e.message : e}`;
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
            const desc = _ftString(args && args.character_description);
            if (!desc) return 'Portrait generation skipped: missing description.';
            try {
                const result = await spellcasterAPI('/portrait', {
                    description: desc,
                });
                if (result.images?.[0]) {
                    return `![portrait](data:image/png;base64,${result.images[0].base64})\n*${_ftLabel(desc, 60)}*`;
                }
                return 'Portrait generation failed';
            } catch (e) {
                return `Failed: ${e && e.message ? e.message : e}`;
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
            const atmosphere = _ftString(args && args.atmosphere);
            const location = _ftString(args && args.location) || 'scene';
            if (!atmosphere) return 'Atmosphere change skipped: missing atmosphere.';
            try {
                const desc = `${location}, ${atmosphere}, cinematic atmosphere`;
                const settings = getSettings();
                const result = await spellcasterAPI('/scene', {
                    description: desc,
                    width: settings.scene_width,
                    height: settings.scene_height,
                });
                if (result.bg_filename) {
                    await SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
                }
                return `Atmosphere set: ${_ftLabel(atmosphere)}`;
            } catch (e) {
                return `Failed: ${e && e.message ? e.message : e}`;
            }
        },
        formatMessage: 'Shifting atmosphere...',
        shouldRegister: () => getSettings().enabled,
    });
}

// ═══════════════════════════════════════════════════════════════════
//  First-Run Wizard
// ═══════════════════════════════════════════════════════════════════
// Modal 7-step wizard that walks a user through the settings that
// matter: ComfyUI URL, image model, video backend, quality profile,
// and automation toggles. The existing settings panel is kept for
// incremental edits; the wizard is for first-run and "I want to
// reconfigure everything" moments. Launch paths:
//   * Automatic on first load when wizard_completed=false
//   * "Run wizard" button in the settings panel
//   * /spellcaster-wizard slash command

const WIZARD_STEPS = [
    { id: 'welcome',     title: 'Welcome' },
    { id: 'connection',  title: 'ComfyUI Server' },
    { id: 'image',       title: 'Image Model' },
    { id: 'video',       title: 'Video Backend' },
    { id: 'quality',     title: 'Quality Profile' },
    { id: 'automation',  title: 'Automation' },
    { id: 'review',      title: 'Review & Save' },
];

// Transient wizard state — NOT persisted until Save & Finish clicked.
// Aborting or closing without finishing discards changes.
let _wizardState = null;

function newWizardState() {
    const s = getSettings();
    return {
        step: 0,
        // Lazy-loaded on reaching the relevant step.
        capabilities: null, // { available:[arch,…], missing:[arch,…] }
        models: null,       // { image:{arch:[ckpt,…]}, video:{wan,ltx} }
        // Draft: edits pile up here until the user hits Save.
        draft: {
            comfyui_url:              s.comfyui_url,
            image_model:              s.image_model || '',
            video_backend:            s.video_backend || 'auto',
            quality_profile:          s.quality_profile || 'balanced',
            auto_background:          !!s.auto_background,
            auto_background_interval: s.auto_background_interval || 3,
            auto_expressions:         !!s.auto_expressions,
            auto_cast:                !!s.auto_cast,
        },
        // UI scratch: most recent connection probe result.
        connection: { tested: false, ok: false, message: '' },
    };
}

function openWizard() {
    _wizardState = newWizardState();
    renderWizard();
}

function closeWizard() {
    _wizardState = null;
    const host = document.getElementById('spellcaster-wizard-root');
    if (host && host.parentNode) host.parentNode.removeChild(host);
}

function wizardGo(delta) {
    if (!_wizardState) return;
    const next = Math.max(0, Math.min(WIZARD_STEPS.length - 1,
                                        _wizardState.step + delta));
    _wizardState.step = next;
    renderWizard();
}

function wizardFinish() {
    if (!_wizardState) return;
    const s = getSettings();
    Object.assign(s, _wizardState.draft);
    s.wizard_completed = true;
    saveSettings();
    // Push the new connection + per-workflow defaults to the server so
    // subsequent /scene, /portrait, /animate pick up the choices.
    spellcasterAPI('/settings', {
        comfyui_url:     _wizardState.draft.comfyui_url,
        image_model:     _wizardState.draft.image_model,
        video_backend:   _wizardState.draft.video_backend,
        quality_profile: _wizardState.draft.quality_profile,
    }).catch(() => { /* best-effort */ });
    closeWizard();
    // Re-render the flat settings panel so it reflects the new values
    // without forcing the user to reopen Extensions.
    try { renderSettingsPanel(); } catch { /* panel may not be mounted */ }
}

function renderWizard() {
    // Mount root once. We rebuild only the inner body on step change to
    // avoid re-initialising listeners we don't need to.
    let host = document.getElementById('spellcaster-wizard-root');
    if (!host) {
        host = document.createElement('div');
        host.id = 'spellcaster-wizard-root';
        document.body.appendChild(host);
    }
    const state = _wizardState;
    const step = WIZARD_STEPS[state.step];
    const progressDots = WIZARD_STEPS.map((s, i) => {
        const cls = i === state.step ? 'active'
                  : i <  state.step ? 'done' : 'upcoming';
        return `<span class="scw-dot scw-dot-${cls}" title="${s.title}"></span>`;
    }).join('');
    const bodyHtml = _renderWizardStep(step.id, state);
    const canBack = state.step > 0;
    const isLast  = state.step === WIZARD_STEPS.length - 1;
    host.innerHTML = `
    <div class="scw-backdrop" id="scw-backdrop"></div>
    <div class="scw-modal" role="dialog" aria-label="Spellcaster Wizard">
        <div class="scw-header">
            <div class="scw-title">
                <span class="scw-emoji">🧙‍♂️</span>
                Spellcaster Wizard
                <span class="scw-step-label">${step.title}</span>
            </div>
            <button class="scw-close" id="scw-close" aria-label="Close">×</button>
        </div>
        <div class="scw-progress">${progressDots}</div>
        <div class="scw-body">${bodyHtml}</div>
        <div class="scw-footer">
            <button class="scw-btn scw-secondary" id="scw-back"
                    ${canBack ? '' : 'disabled'}>Back</button>
            <button class="scw-btn scw-primary" id="scw-next">
                ${isLast ? 'Save & Apply' : 'Next'}
            </button>
        </div>
    </div>`;
    // Wire nav / close
    host.querySelector('#scw-close')?.addEventListener('click', closeWizard);
    host.querySelector('#scw-backdrop')?.addEventListener('click', closeWizard);
    host.querySelector('#scw-back')?.addEventListener('click', () => wizardGo(-1));
    host.querySelector('#scw-next')?.addEventListener('click', () => {
        if (isLast) wizardFinish();
        else wizardGo(+1);
    });
    // Per-step listeners (kept local to the step renderer via data-scw
    // attributes resolved below).
    _attachStepListeners(step.id, state, host);
}

// Step renderers — each takes state, returns an HTML string. Per-step
// DOM listeners are attached in _attachStepListeners so the wiring
// stays adjacent to the markup.

function _renderWizardStep(id, state) {
    const d = state.draft;
    switch (id) {
        case 'welcome':
            return `
                <p>This wizard sets Spellcaster's defaults in 6 quick steps.
                You can change any choice later via the Extensions panel
                or by re-running <code>/spellcaster-wizard</code>.</p>
                <p><strong>What you'll configure:</strong></p>
                <ul>
                    <li>ComfyUI server URL</li>
                    <li>Default image model (for /scene, /portrait)</li>
                    <li>Video backend (for /animate)</li>
                    <li>Quality profile (speed vs fidelity)</li>
                    <li>Automation toggles (auto-background, expressions)</li>
                </ul>
                <p class="scw-hint">Safe to skip: pressing Next keeps the
                current value at each step.</p>`;
        case 'connection':
            return `
                <label class="scw-field">
                    <span>ComfyUI URL</span>
                    <input type="text" id="scw-comfyui-url"
                           value="${_escape(d.comfyui_url)}" />
                </label>
                <div class="scw-row">
                    <button class="scw-btn scw-secondary" id="scw-test-conn">
                        Test connection
                    </button>
                    <span id="scw-conn-status" class="scw-status">
                        ${state.connection.tested
                            ? (state.connection.ok
                                ? '<span class="scw-ok">✓ '+_escape(state.connection.message)+'</span>'
                                : '<span class="scw-err">✗ '+_escape(state.connection.message)+'</span>')
                            : ''}
                    </span>
                </div>
                <p class="scw-hint">Default <code>http://127.0.0.1:8188</code>
                is correct for a ComfyUI running on this machine. For
                remote servers use the LAN IP, e.g.
                <code>http://192.168.1.50:8188</code>.</p>`;
        case 'image': {
            const loading = !state.models;
            if (loading) {
                _loadModelsAsync(state);
                return `<p class="scw-loading">Probing ComfyUI for installed models…</p>`;
            }
            const groups = state.models.image || {};
            const groupKeys = Object.keys(groups).filter(k => groups[k]?.length);
            if (groupKeys.length === 0) {
                return `<p class="scw-err">No image models detected on
                ${_escape(d.comfyui_url)}. Install at least one checkpoint
                in ComfyUI/models/checkpoints before using /scene or
                /portrait.</p>`;
            }
            // Radio card per arch, each with a nested select for the
            // specific checkpoint. "Let Spellcaster pick" radio at top
            // maps to draft.image_model = ''.
            const autoChecked = !d.image_model ? 'checked' : '';
            const cards = groupKeys.map((arch, i) => {
                const opts = groups[arch].map(m =>
                    `<option value="${_escape(m)}" ${m === d.image_model ? 'selected' : ''}>
                        ${_escape(_prettyModelName(m))}
                    </option>`).join('');
                const thisArchSelected = groups[arch].includes(d.image_model);
                return `
                <label class="scw-card ${thisArchSelected ? 'scw-selected' : ''}">
                    <input type="radio" name="scw-image-arch"
                           value="${_escape(arch)}"
                           ${thisArchSelected ? 'checked' : ''}
                           data-scw-arch="${_escape(arch)}" />
                    <strong>${_escape(_prettyArchLabel(arch))}</strong>
                    <select data-scw-arch-select="${_escape(arch)}">
                        ${opts}
                    </select>
                </label>`;
            }).join('');
            return `
                <p>Pick the default checkpoint for <code>/scene</code> and
                <code>/portrait</code>. You can always override per-command
                later.</p>
                <label class="scw-card ${!d.image_model ? 'scw-selected' : ''}">
                    <input type="radio" name="scw-image-arch" value="__auto__"
                           ${autoChecked} id="scw-image-auto" />
                    <strong>Let Spellcaster pick automatically</strong>
                    <span class="scw-hint">Recommended — Klein 9B &gt; SDXL
                    &gt; Juggernaut &gt; anything installed.</span>
                </label>
                <div class="scw-cards">${cards}</div>`;
        }
        case 'video': {
            const loading = !state.models;
            if (loading) {
                _loadModelsAsync(state);
                return `<p class="scw-loading">Checking video backends…</p>`;
            }
            const v = state.models.video || {};
            const wanOK = !!v.wan;
            const choice = d.video_backend || 'auto';
            return `
                <p>Pick which engine <code>/animate</code> should prefer.</p>
                <label class="scw-card ${choice === 'auto' ? 'scw-selected' : ''}">
                    <input type="radio" name="scw-video" value="auto"
                           ${choice === 'auto' ? 'checked' : ''} />
                    <strong>Auto (recommended)</strong>
                    <span class="scw-hint">Use whatever's installed; fall
                    back to legacy if none.</span>
                </label>
                <label class="scw-card ${choice === 'wan22' ? 'scw-selected' : ''}
                                     ${wanOK ? '' : 'scw-disabled'}">
                    <input type="radio" name="scw-video" value="wan22"
                           ${choice === 'wan22' ? 'checked' : ''}
                           ${wanOK ? '' : 'disabled'} />
                    <strong>Wan 2.2 I2V</strong>
                    <span class="scw-hint">
                        ${wanOK
                            ? 'Detected on this server. High quality, ~2–5 min per clip on a 16 GB GPU.'
                            : 'Not installed. Add WanImageToVideo + LoadWanVideoModel custom nodes.'}
                    </span>
                </label>
                <label class="scw-card ${choice === 'none' ? 'scw-selected' : ''}">
                    <input type="radio" name="scw-video" value="none"
                           ${choice === 'none' ? 'checked' : ''} />
                    <strong>Disable video</strong>
                    <span class="scw-hint"><code>/animate</code> will return an
                    error rather than run any workflow. Useful on
                    low-VRAM servers.</span>
                </label>`;
        }
        case 'quality': {
            const q = d.quality_profile;
            return `
                <p>Controls the quality-booster stack wired into every
                generation (PAG, RescaleCFG, FreeU_V2, SLG, AYS — picked
                per architecture).</p>
                <label class="scw-card ${q === 'fast' ? 'scw-selected' : ''}">
                    <input type="radio" name="scw-quality" value="fast"
                           ${q === 'fast' ? 'checked' : ''} />
                    <strong>Fast</strong>
                    <span class="scw-hint">No extra passes. Use when you
                    need throughput, not polish. Flux foundational
                    boosters still apply (they're correctness, not
                    optional).</span>
                </label>
                <label class="scw-card ${q === 'balanced' ? 'scw-selected' : ''}">
                    <input type="radio" name="scw-quality" value="balanced"
                           ${q === 'balanced' ? 'checked' : ''} />
                    <strong>Balanced (default)</strong>
                    <span class="scw-hint">PAG + RescaleCFG on SDXL/Flux1.
                    Strict improvement over plain KSampler at ~15% more
                    compute. The sensible default.</span>
                </label>
                <label class="scw-card ${q === 'max' ? 'scw-selected' : ''}">
                    <input type="radio" name="scw-quality" value="max"
                           ${q === 'max' ? 'checked' : ''} />
                    <strong>Max</strong>
                    <span class="scw-hint">Adds FreeU_V2 (SDXL), SLG
                    (Flux), AYS scheduler (SD1/SDXL). ~30% slower but
                    noticeably cleaner at low step counts.</span>
                </label>`;
        }
        case 'automation':
            return `
                <p>Passive features that trigger without an explicit
                command. All opt-in.</p>
                <label class="scw-field-inline">
                    <input type="checkbox" id="scw-auto-bg"
                           ${d.auto_background ? 'checked' : ''} />
                    <span>Auto-generate scene backgrounds from narrative</span>
                </label>
                <label class="scw-field">
                    <span>Background interval (every N messages)</span>
                    <input type="number" id="scw-bg-interval" min="1" max="20"
                           value="${d.auto_background_interval}" />
                </label>
                <label class="scw-field-inline">
                    <input type="checkbox" id="scw-auto-expr"
                           ${d.auto_expressions ? 'checked' : ''} />
                    <span>Auto-generate character expressions from mood</span>
                </label>
                <label class="scw-field-inline">
                    <input type="checkbox" id="scw-auto-cast"
                           ${d.auto_cast ? 'checked' : ''} />
                    <span>Auto-cast characters on startup
                        <em class="scw-hint">(queues Klein jobs at launch —
                         slow; expect multi-minute warm-up)</em></span>
                </label>`;
        case 'review':
            return `
                <p>Review and click <strong>Save & Apply</strong> to
                commit. Nothing is written until you click that button.</p>
                <dl class="scw-review">
                    <dt>ComfyUI</dt><dd><code>${_escape(d.comfyui_url)}</code></dd>
                    <dt>Image model</dt>
                    <dd>${d.image_model
                            ? '<code>'+_escape(d.image_model)+'</code>'
                            : '<em>auto-pick</em>'}</dd>
                    <dt>Video backend</dt>
                    <dd>${_escape(_prettyVideoLabel(d.video_backend))}</dd>
                    <dt>Quality profile</dt>
                    <dd>${_escape(d.quality_profile)}</dd>
                    <dt>Auto-backgrounds</dt>
                    <dd>${d.auto_background
                        ? 'every '+d.auto_background_interval+' messages'
                        : '<em>off</em>'}</dd>
                    <dt>Auto-expressions</dt>
                    <dd>${d.auto_expressions ? 'on' : '<em>off</em>'}</dd>
                    <dt>Auto-cast on startup</dt>
                    <dd>${d.auto_cast ? 'on' : '<em>off</em>'}</dd>
                </dl>`;
    }
    return `<p><em>Unknown step: ${id}</em></p>`;
}

function _attachStepListeners(id, state, host) {
    const d = state.draft;
    switch (id) {
        case 'connection': {
            const urlEl = host.querySelector('#scw-comfyui-url');
            urlEl?.addEventListener('input', (e) => {
                d.comfyui_url = e.target.value.trim().replace(/\/+$/, '');
                state.connection.tested = false;
                // Invalidate the models probe — we may be pointing at a
                // different server now.
                state.models = null;
            });
            host.querySelector('#scw-test-conn')?.addEventListener('click',
                async () => {
                    state.connection.tested = true;
                    state.connection.ok = false;
                    state.connection.message = 'Testing…';
                    renderWizard();
                    try {
                        const r = await fetch(`${API_BASE}/health`).then(x => x.json());
                        state.connection.ok = !!r.comfyui_ok;
                        state.connection.message = r.comfyui_ok
                            ? `Online. ${r.models ?? ''} checkpoints detected.`
                            : (r.error || 'ComfyUI unreachable');
                    } catch (e) {
                        state.connection.message = e?.message || 'Probe failed';
                    }
                    renderWizard();
                });
            return;
        }
        case 'image': {
            host.querySelector('#scw-image-auto')?.addEventListener('change', () => {
                d.image_model = '';
                renderWizard();
            });
            host.querySelectorAll('[data-scw-arch]').forEach(radio => {
                radio.addEventListener('change', (e) => {
                    const arch = e.target.getAttribute('data-scw-arch');
                    // Take the first model in the arch group; user can
                    // refine via the inner <select>.
                    const group = (state.models?.image || {})[arch] || [];
                    d.image_model = group[0] || '';
                    renderWizard();
                });
            });
            host.querySelectorAll('[data-scw-arch-select]').forEach(sel => {
                sel.addEventListener('change', (e) => {
                    d.image_model = e.target.value;
                    renderWizard();
                });
            });
            return;
        }
        case 'video': {
            host.querySelectorAll('input[name="scw-video"]').forEach(radio => {
                radio.addEventListener('change', (e) => {
                    d.video_backend = e.target.value;
                    renderWizard();
                });
            });
            return;
        }
        case 'quality': {
            host.querySelectorAll('input[name="scw-quality"]').forEach(radio => {
                radio.addEventListener('change', (e) => {
                    d.quality_profile = e.target.value;
                    renderWizard();
                });
            });
            return;
        }
        case 'automation': {
            host.querySelector('#scw-auto-bg')?.addEventListener('change',
                (e) => { d.auto_background = e.target.checked; });
            host.querySelector('#scw-bg-interval')?.addEventListener('change',
                (e) => { d.auto_background_interval = Math.max(1,
                    Math.min(20, parseInt(e.target.value, 10) || 3)); });
            host.querySelector('#scw-auto-expr')?.addEventListener('change',
                (e) => { d.auto_expressions = e.target.checked; });
            host.querySelector('#scw-auto-cast')?.addEventListener('change',
                (e) => { d.auto_cast = e.target.checked; });
            return;
        }
    }
}

async function _loadModelsAsync(state) {
    // Called from the image/video step renderers when models haven't been
    // probed yet. The renderer initially returns a "Loading…" view; we
    // re-render once the probe resolves.
    try {
        const r = await fetch(`${API_BASE}/models`).then(x => x.json());
        state.models = r && typeof r === 'object' ? r : { image: {}, video: {} };
    } catch (e) {
        state.models = { image: {}, video: {}, error: e?.message || 'probe failed' };
    }
    // Renderer keyed on _wizardState — only re-render if the user didn't
    // close the wizard in the meantime.
    if (_wizardState === state) renderWizard();
}

// Small display helpers. Keep pure (no DOM, no state) so they're easy to
// reason about / test / reuse.

function _prettyArchLabel(arch) {
    const labels = {
        klein9b:    'Flux 2 Klein 9B',
        klein4b:    'Flux 2 Klein 4B',
        fluxkontext:'Flux Kontext',
        flux1dev:   'Flux 1 Dev',
        sdxl:       'SDXL',
        illustrious:'Illustrious / Pony',
        sd15:       'SD 1.5',
        zit:        'Z-Image Turbo',
        chroma:     'Chroma',
    };
    return labels[arch] || arch;
}

function _prettyModelName(filename) {
    // Drop the subfolder prefix + .safetensors suffix for display.
    return String(filename)
        .replace(/^.*[\\/]/, '')
        .replace(/\.(safetensors|ckpt|gguf|pt)$/, '');
}

function _prettyVideoLabel(choice) {
    return {
        auto:  'Auto (pick best available)',
        wan22: 'Wan 2.2 I2V',
        none:  'Disabled',
    }[choice] || choice;
}

function _escape(s) {
    return String(s ?? '').replace(/[&<>"']/g,
        c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
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
            <button id="spellcaster-open-wizard" class="spellcaster-wizard-btn"
                    title="Step through Spellcaster's main settings one question at a time.">
                Run Wizard
            </button>
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
            <input type="number" id="spellcaster-bg-interval" value="${_escape(settings.auto_background_interval)}" min="1" max="20" style="width:60px">
        </div>

        <label class="spellcaster-toggle">
            <input type="checkbox" id="spellcaster-auto-expr" ${settings.auto_expressions ? 'checked' : ''}>
            <span>Auto-generate character expressions</span>
        </label>

        <label class="spellcaster-toggle" title="Pre-cast every character + generate a Klein body double on ST launch. Queues one job per character — expect several minutes of ComfyUI queue time after a fresh start. Off by default; /studio-cast-all runs the same pipeline on demand.">
            <input type="checkbox" id="spellcaster-auto-cast" ${settings.auto_cast ? 'checked' : ''}>
            <span>Auto-cast on startup (slow)</span>
        </label>

        <label class="spellcaster-toggle" title="Poll the Wizard Guild every ${_escape(settings.auto_inbox_interval_s || 30)}s for cross-plugin assets (images sent from GIMP / Resolve / Darktable). New items appear in chat automatically instead of only when you type /sc-inbox. Off by default.">
            <input type="checkbox" id="spellcaster-auto-inbox" ${settings.auto_inbox_poll ? 'checked' : ''}>
            <span>Auto-show assets from other apps</span>
        </label>

        <div class="spellcaster-row">
            <label>ComfyUI URL:</label>
            <input type="text" id="spellcaster-comfyui-url" value="${_escape(settings.comfyui_url)}" style="width:100%">
        </div>

        <div class="spellcaster-row">
            <label>Restyle prompt:</label>
            <textarea id="spellcaster-restyle-prompt" rows="2" style="width:100%">${_escape(settings.restyle_prompt)}</textarea>
        </div>

        <div class="spellcaster-row">
            <label>Restyle denoise (0.3=subtle, 0.7=heavy):</label>
            <input type="range" id="spellcaster-restyle-denoise" min="0.2" max="0.8" step="0.05" value="${_escape(settings.restyle_denoise)}">
            <span id="spellcaster-denoise-val">${_escape(settings.restyle_denoise)}</span>
        </div>

        <div class="spellcaster-commands">
            <strong>Generate:</strong>
            <div>/scene [description] — Klein txt2img → SDXL fallback</div>
            <div>/portrait [description] — Klein txt2img → SDXL fallback</div>
            <div>/animate [prompt] — WAN 2.2 I2V → LTX → legacy fallback</div>
            <div style="margin-top:6px"><strong>Edit the avatar:</strong></div>
            <div>/edit [instruction] — Klein img2img → Kontext → SDXL</div>
            <div>/restyle [style] — full restyle + persist (auto-backup)</div>
            <div>/restyle-all [style] — restyle every character</div>
            <div>/restyle-undo / /restyle-undo-all — revert to backup</div>
            <div style="margin-top:6px"><strong>Magic Studios:</strong></div>
            <div>/studio-cast / /studio-cast-all — create face models</div>
            <div>/studio-body [desc] / /studio-body-all [attire]</div>
            <div>/studio-scene [desc] — scene + characters composited</div>
            <div>/studio-status — check readiness</div>
            <div style="margin-top:6px"><strong>Cross-app + system:</strong></div>
            <div>/sc-capabilities — probe installed architectures</div>
            <div>/sc-send-to-resolve / -gimp / -darktable — ship an image</div>
            <div>/sc-inbox — pull assets sent to SillyTavern</div>
            <div>/spellcaster [on|off|auto-bg on|auto-bg off]</div>
        </div>
    </div>`;

    const container = document.getElementById('extensions_settings');
    if (container) {
        // Remove any previous Spellcaster panel + its listeners before
        // re-inserting. Avoids handler accumulation if renderSettingsPanel
        // is called more than once over the session.
        const prev = document.getElementById('spellcaster-settings');
        if (prev && prev.parentNode) {
            prev.parentNode.removeChild(prev);
        }
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
        document.getElementById('spellcaster-auto-inbox')?.addEventListener('change', (e) => {
            settings.auto_inbox_poll = e.target.checked;
            saveSettings();
            // If the user just turned it on, fire one poll right away
            // so they don't have to wait a full interval to see
            // anything that's been sitting in the queue.
            if (e.target.checked) pollInboxOnce().catch(() => {});
        });
        document.getElementById('spellcaster-auto-cast')?.addEventListener('change', (e) => {
            settings.auto_cast = e.target.checked;
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
        document.getElementById('spellcaster-open-wizard')?.addEventListener('click', () => {
            openWizard();
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

// Client-side 20 MB cap matches the server's 28 MB base64-chars cap
// (decoded ≈ 21 MB). Fail fast so the user gets a clear error instead
// of a generic HTTP 413 roundtrip.
const BLOB_TO_B64_MAX_BYTES = 20 * 1024 * 1024;
function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        if (!(blob instanceof Blob)) {
            reject(new Error('blobToBase64: expected Blob'));
            return;
        }
        if (blob.size > BLOB_TO_B64_MAX_BYTES) {
            reject(new Error(`blobToBase64: image is ${Math.round(blob.size / 1024 / 1024)} MB, max ${BLOB_TO_B64_MAX_BYTES / 1024 / 1024} MB`));
            return;
        }
        const reader = new FileReader();
        reader.onloadend = () => {
            try {
                const res = reader.result;
                if (typeof res !== 'string') {
                    reject(new Error('blobToBase64: FileReader produced non-string result'));
                    return;
                }
                const comma = res.indexOf(',');
                resolve(comma >= 0 ? res.slice(comma + 1) : res);
            } catch (e) {
                reject(e);
            }
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
// Auto-inbox poller — when `auto_inbox_poll` is enabled, fetch new
// cross-interface messages every `auto_inbox_interval_s` seconds and
// render them as chat messages. Mirrors the /sc-inbox slash-command's
// output format so the user experience is identical whether they type
// the command or just let assets appear. Guarded by several layers:
//   * Off by default — the user has to opt in.
//   * Skipped when the tab is hidden (document.hidden) — no point
//     pinging the Guild while the tab is backgrounded.
//   * Skipped when plugin is disabled.
//   * Single-flight: the next tick won't start while the previous is
//     still in flight.
//   * Clamped interval (10–300 s) so a bad setting can't hammer the
//     Guild or starve forever.
let _inboxInFlight = false;
async function pollInboxOnce() {
    if (_inboxInFlight) return 0;
    _inboxInFlight = true;
    try {
        const r = await fetch(`${API_BASE}/cross/inbox`, {
            headers: getContext().getRequestHeaders(),
        });
        if (!r.ok) return 0;
        const data = await r.json();
        const msgs = (data && data.messages) || [];
        if (!msgs.length) return 0;

        // Same renderer as /sc-inbox — kept in sync so both paths
        // produce identical output. Attacker-controlled `source`,
        // `title`, `image_url` (published by any interface with
        // Guild bus access) are scrubbed / allowlisted.
        const _stripMd = (s) => String(s == null ? '' : s)
            .replace(/[\r\n]+/g, ' ')
            .replace(/[\[\]()`*_~]/g, '')
            .slice(0, 200);
        const _urlOk = (u) => {
            if (typeof u !== 'string' || !u) return false;
            if (u.startsWith('/api/')) return true;
            try {
                const p = new URL(u);
                if (p.protocol === 'http:' || p.protocol === 'https:') return true;
                if (p.protocol === 'data:' && /^data:image\//i.test(u)) return true;
            } catch { return false; }
            return false;
        };
        const parts = msgs.map((m, i) => {
            const d = m.data || {};
            const src = _stripMd(d.source || '?');
            const title = _stripMd(d.title || m.kind);
            const rawUrl = d.image_url || '';
            const url = _urlOk(rawUrl) ? rawUrl.replace(/[\s)]/g, encodeURIComponent) : '';
            return `**${i + 1}. From ${src}:** ${title}\n\n` +
                   (url ? `![${title}](${url})` : '(no usable image url)');
        });
        const body = `💎 ${msgs.length} item(s) from cross-plugin:\n\n` +
                     parts.join('\n\n---\n\n');
        // Post as a system-ish message via ST's addOneMessage API if
        // available; fall back to toastr + console so the user still
        // sees something on older ST builds.
        try {
            const ctx = getContext();
            if (ctx && typeof ctx.addOneMessage === 'function') {
                const msg = {
                    name: 'Spellcaster',
                    is_user: false,
                    is_system: true,
                    send_date: Date.now(),
                    mes: body,
                    extra: { type: 'narrator' },
                };
                if (Array.isArray(ctx.chat)) ctx.chat.push(msg);
                ctx.addOneMessage(msg);
            } else if (typeof toastr !== 'undefined') {
                toastr.info(`Cross-plugin inbox: ${msgs.length} new item(s).`, 'Spellcaster');
            }
        } catch (e) {
            console.warn('[Spellcaster] inbox render failed:', e);
        }
        return msgs.length;
    } catch (e) {
        // Network hiccup — fine, try again next tick.
        return 0;
    } finally {
        _inboxInFlight = false;
    }
}

let _inboxTimer = null;
function startInboxAutoPoll() {
    if (_inboxTimer !== null) return;  // idempotent
    const tick = async () => {
        try {
            const settings = getSettings();
            if (!settings.enabled || !settings.auto_inbox_poll) return;
            if (typeof document !== 'undefined' && document.hidden) return;
            await pollInboxOnce();
        } catch (e) {
            console.warn('[Spellcaster] inbox poll tick failed:', e);
        }
    };
    // Clamp the interval to [10 s, 5 min] — a sane range prevents a
    // fat-fingered setting from hammering the Guild or waiting forever.
    const raw = Number(getSettings().auto_inbox_interval_s);
    const interval = Math.min(300, Math.max(10, Number.isFinite(raw) ? raw : 30)) * 1000;
    _inboxTimer = setInterval(tick, interval);
    // Also fire once right away so users don't wait a full cycle on
    // freshly-enabled auto-poll.
    setTimeout(tick, 500);
}

async function autoCastOnStartup() {
    const settings = getSettings();
    if (!settings.enabled || !settings.auto_cast) {
        // Default path. The previous behaviour queued a Klein body
        // job per character on every ST launch — 15+ jobs, ~10
        // minutes of blocked queue, no user consent. Gated behind
        // the "Auto-cast on startup" toggle now. /studio-cast-all
        // is still available for users who want it on demand.
        return;
    }

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

            // Auto-generate body if the card has a body_description.
            // Trim to a Klein-friendly length — character descriptions
            // are often multi-paragraph personas that dilute the body
            // prompt. ~400 chars captures the visual descriptors
            // without the backstory.
            const bodyDescRaw = char.data?.extensions?.spellcaster?.body_description
                             || char.description || '';
            const bodyDesc = bodyDescRaw.length > 400
                ? bodyDescRaw.slice(0, 400).replace(/\s+\S*$/, '') + '…'
                : bodyDescRaw;
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
    const eventTypes = context.eventTypes || context.event_types || {};
    const EV_CHAR_MSG = eventTypes.CHARACTER_MESSAGE_RENDERED || 'character_message_rendered';
    const EV_SETTINGS = eventTypes.SETTINGS_LOADED || 'settings_loaded';

    // Register event handlers
    if (eventSource) {
        // Auto-background on character message
        eventSource.on(EV_CHAR_MSG, (messageIndex) => {
            onCharacterMessageRendered(messageIndex);
        });

        // Expression generation on character message
        eventSource.on(EV_CHAR_MSG, (messageIndex) => {
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
        eventSource.on(EV_SETTINGS, () => {
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

    // Configure server plugin with whatever the wizard already saved
    // (or the defaults). Backwards-compatible: the server silently
    // ignores unknown keys, so older server-plugin.js won't break
    // until image_model / video_backend / quality_profile land there.
    const settings = getSettings();
    spellcasterAPI('/settings', {
        comfyui_url:     settings.comfyui_url,
        image_model:     settings.image_model || '',
        video_backend:   settings.video_backend || 'auto',
        quality_profile: settings.quality_profile || 'balanced',
    }).catch(() => {});

    // First-run wizard: open automatically if the user has never saved
    // a pass. Defer so ST's own UI has finished painting — otherwise
    // the modal can end up behind a late-opened drawer.
    if (!settings.wizard_completed) {
        setTimeout(() => {
            // Re-check: user may have dismissed the auto-open by
            // clicking Finish during the delay window.
            if (!getSettings().wizard_completed) openWizard();
        }, 2000);
    }

    // Auto-cast all characters in background (non-blocking, 5s delay).
    // Swallow any unhandled rejection — the function is best-effort;
    // per-character failures are already logged inside it.
    setTimeout(() => {
        autoCastOnStartup().catch(err =>
            console.warn('[Spellcaster] autoCastOnStartup failed:', err));
    }, 5000);

    // Start the cross-interface inbox auto-poller. No-ops if the
    // feature is disabled in settings; see startInboxAutoPoll() for
    // the gating. Lives independently of autoCastOnStartup.
    startInboxAutoPoll();

    console.log('[Spellcaster] Extension loaded. ComfyUI:', settings.comfyui_url);
})();
