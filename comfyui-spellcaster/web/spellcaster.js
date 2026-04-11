/**
 * ComfyUI-Spellcaster — Frontend extension
 *
 * Registers custom node colours, badges, and category defaults
 * so Spellcaster nodes are visually distinct in the workflow graph.
 *
 * Also shows a one-time install toast when the full Spellcaster suite
 * hasn't been set up yet.
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

// ── Install Toast ────────────────────────────────────────────────────
// Shows once per session if the full suite isn't installed.
// The backend writes web/spellcaster_status.json at startup.

const TOAST_DISMISSED_KEY = "spellcaster_install_toast_dismissed";

async function checkAndShowInstallToast() {
    // Don't show if user already dismissed it this browser session
    if (sessionStorage.getItem(TOAST_DISMISSED_KEY)) return;

    try {
        const resp = await fetch("extensions/ComfyUI-Spellcaster/spellcaster_status.json?" + Date.now());
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.suite_installed) return;
    } catch (_) {
        return; // file missing or parse error — don't bother
    }

    // Build the toast
    const toast = document.createElement("div");
    toast.id = "spellcaster-install-toast";
    toast.innerHTML = `
        <div style="
            position: fixed; bottom: 20px; right: 20px; z-index: 99999;
            max-width: 380px; padding: 16px 20px;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border: 1px solid #e94560; border-radius: 12px;
            box-shadow: 0 8px 32px rgba(233, 69, 96, 0.3);
            font-family: system-ui, -apple-system, sans-serif;
            color: #e0e0e0; font-size: 13px; line-height: 1.5;
            animation: spellcaster-slide-in 0.4s ease-out;
        ">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                <span style="font-size: 20px;">&#x2728;</span>
                <span style="font-weight: 700; font-size: 14px; color: #e94560;">
                    Spellcaster Nodes Installed!
                </span>
                <button id="spellcaster-toast-close" style="
                    margin-left: auto; background: none; border: none;
                    color: #888; font-size: 18px; cursor: pointer;
                    padding: 0 4px; line-height: 1;
                ">&times;</button>
            </div>
            <p style="margin: 0 0 10px 0; color: #b0b0b0;">
                Want the <strong style="color: #e0e0e0;">full suite</strong>?
                Wizard Guild, GIMP &amp; Darktable plugins, desktop shortcuts, and the model downloader.
            </p>
            <p style="margin: 0 0 6px 0; color: #b0b0b0; font-size: 12px;">
                Run <code style="
                    background: #0f3460; padding: 2px 6px; border-radius: 4px;
                    color: #4fc3f7; font-size: 12px;
                ">Install_Spellcaster_Suite.bat</code>
                in your <code style="
                    background: #0f3460; padding: 2px 6px; border-radius: 4px;
                    color: #4fc3f7; font-size: 12px;
                ">custom_nodes</code> folder.
            </p>
            <a href="https://github.com/laboratoiresonore/spellcaster" target="_blank" style="
                display: inline-block; margin-top: 4px;
                color: #e94560; font-size: 11px; text-decoration: none;
            ">Learn more &rarr;</a>
        </div>
        <style>
            @keyframes spellcaster-slide-in {
                from { opacity: 0; transform: translateY(20px); }
                to   { opacity: 1; transform: translateY(0); }
            }
        </style>
    `;
    document.body.appendChild(toast);

    // Close button
    document.getElementById("spellcaster-toast-close").addEventListener("click", () => {
        toast.remove();
        sessionStorage.setItem(TOAST_DISMISSED_KEY, "1");
    });

    // Auto-dismiss after 30 seconds
    setTimeout(() => {
        if (document.getElementById("spellcaster-install-toast")) {
            toast.style.transition = "opacity 0.5s ease";
            toast.style.opacity = "0";
            setTimeout(() => toast.remove(), 500);
        }
    }, 30000);
}


// ── Node Styling ─────────────────────────────────────────────────────

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

        // Show install toast after a short delay (let the UI settle)
        setTimeout(checkAndShowInstallToast, 3000);
    },
});
