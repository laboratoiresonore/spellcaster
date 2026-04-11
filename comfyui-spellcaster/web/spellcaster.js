/**
 * ComfyUI-Spellcaster-NSFW — Frontend extension
 *
 * Registers custom node colours, badges, and category defaults
 * so Spellcaster nodes are visually distinct in the workflow graph.
 * NSFW nodes get an additional colour accent.
 */
import { app } from "../../scripts/app.js";

const SPELLCASTER_COLOR = "#1a1a2e";     // Deep indigo background
const SPELLCASTER_BG    = "#16213e";     // Slightly lighter body
const SPELLCASTER_TITLE  = "#0f3460";    // Title bar dark blue
const SPELLCASTER_TEXT   = "#e94560";     // Accent red-pink for title text

const NSFW_COLOR = "#2e1a2e";            // Deep purple background
const NSFW_BG    = "#3e1640";            // Purple-tinted body
const NSFW_TEXT  = "#e945a0";            // Hot pink accent

const BASE_NODES = [
    "SpellcasterLoader",
    "SpellcasterPromptEnhance",
    "SpellcasterSampler",
    "SpellcasterOutput",
];

const NSFW_NODES = [
    "SpellcasterNSFWLoRA",
    "SpellcasterNSFWLoRAModelOnly",
];

app.registerExtension({
    name: "Spellcaster.NodeStyle",

    async beforeRegisterNodeDef(nodeType, nodeData, _app) {
        const isBase = BASE_NODES.includes(nodeData.name);
        const isNSFW = NSFW_NODES.includes(nodeData.name);
        if (!isBase && !isNSFW) return;

        const origOnCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnCreated?.apply(this, arguments);

            if (isNSFW) {
                this.color  = NSFW_COLOR;
                this.bgcolor = NSFW_BG;
            } else {
                this.color  = SPELLCASTER_COLOR;
                this.bgcolor = SPELLCASTER_BG;
            }

            // Add a small badge so the node is identifiable at a glance
            if (!this.badges) this.badges = [];
            this.badges.push({
                text: isNSFW ? "\uD83D\uDD25" : "\u2728",   // fire for NSFW, sparkles for base
                color: isNSFW ? NSFW_TEXT : SPELLCASTER_TEXT,
            });
        };
    },

    async setup() {
        if (app.ui?.settings) {
            try {
                app.ui.settings.addSetting({
                    id: "Spellcaster.CategoryColor",
                    name: "Spellcaster node colour",
                    type: "color",
                    defaultValue: SPELLCASTER_COLOR,
                });
            } catch (_) {
                // Older ComfyUI versions may not support addSetting
            }
        }
    },
});
