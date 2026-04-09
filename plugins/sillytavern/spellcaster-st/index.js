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
            if (context.SlashCommandParser) {
                await context.SlashCommandParser.commands['bg']?.callback?.(null, result.bg_filename);
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

    // /restyle [style] — Restyle current character's avatar (persists to disk with backup)
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
    });

    // /restyle-undo — Restore the current character's original avatar from backup
    SCP.addCommandObject({
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
    });

    // /restyle-undo-all — Restore ALL character avatars from backups
    SCP.addCommandObject({
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
    });

    // /animate [prompt] — Animate the current character's avatar as a short GIF
    SCP.addCommandObject({
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

                if (result.videos?.