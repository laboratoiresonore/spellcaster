/**
 * ComfyUI-Spellcaster — Frontend extension
 *
 * Registers custom node colours, badges, and category defaults
 * so Spellcaster nodes are visually distinct in the workflow graph.
 */
import { app } from "../../scripts/app.js";

const SPELLCASTER_COLOR = "#1a1a2e";     // Deep indigo background
const SPELLCASTER_BG    = "#16213e";     // Slightly lighter body
const SPELLCASTER_TITLE  = "#0f3460";    // Title bar dark blue
const SPELLCASTER_TEXT   = "#e94560";     // Accent red-pink for title text

const SPELLCASTER_NODES = [
    "SpellcasterLoader",
    "SpellcasterPromptEnhance",
    "SpellcasterSampler",
    "SpellcasterOutput",
];

app.registerExtension({
    name: "Spellcaster.NodeStyle",

    async beforeRegisterNodeDef(nodeType, nodeData, _app) {
        if (!SPELLCASTER_NODES.includes(nodeData.name)) return;

        const origOnCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnCreated?.apply(this, arguments);

            // Apply Spellcaster colour scheme
            this.color  = SPELLCASTER_COLOR;
            this.bgcolor = SPELLCASTER_BG;

            // Add a small badge so the node is identifiable at a glance
            if (!this.badges) this.badges = [];
            this.badges.push({
                text: "\u2728",   // sparkles emoji
                color: SPELLCASTER_TEXT,
            });
        };
    },

    async setup() {
        // Register the "Spellcaster" category colour in the node browser
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
