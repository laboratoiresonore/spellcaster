/**
 * Spellcaster for Adobe Photoshop — UXP Plugin
 *
 * Talks to the Wizard Guild HTTP API (not ComfyUI directly).
 * The Guild handles workflow building, preflight, optimization, and submission.
 *
 * Install: Photoshop -> Plugins -> Browse -> select this folder
 * Requires: Wizard Guild running (http://127.0.0.1:7777)
 */

const { app, core, action, imaging } = require("photoshop");
const { entrypoints } = require("uxp");
const fs = require("uxp").storage.localFileSystem;

const GUILD_URL = "http://127.0.0.1:7777";

// ═══════════════════════════════════════════════════════════════════
//  Guild API communication
// ═══════════════════════════════════════════════════════════════════

async function guildAPI(path, body = null) {
    const opts = {
        method: body ? "POST" : "GET",
        headers: { "Content-Type": "application/json" },
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(`${GUILD_URL}${path}`, opts);
    return resp.json();
}

async function executeWorkflow(buildFn, params) {
    /**
     * Send a workflow execution request to the Guild.
     * The Guild builds the workflow, runs preflight + optimizer,
     * submits to ComfyUI, and returns the result.
     */
    return guildAPI("/api/execute", {
        build_fn: buildFn,
        params: params,
    });
}

// ═══════════════════════════════════════════════════════════════════
//  Canvas export/import
// ═══════════════════════════════════════════════════════════════════

async function exportCanvasAsPNG() {
    /** Export current document as PNG to temp folder. */
    const doc = app.activeDocument;
    if (!doc) throw new Error("No active document");
    const tempFolder = await fs.getTemporaryFolder();
    const file = await tempFolder.createFile("spellcaster_export.png", { overwrite: true });
    await doc.saveAs.png(file, { compression: 6 });
    return file;
}

async function importLayerFromURL(url, layerName) {
    /** Download image from URL and add as new layer. */
    const resp = await fetch(url);
    const blob = await resp.blob();
    const tempFolder = await fs.getTemporaryFolder();
    const file = await tempFolder.createFile("spellcaster_result.png", { overwrite: true });
    const buffer = await blob.arrayBuffer();
    await file.write(buffer);

    // Place the file as a new layer
    await core.executeAsModal(async () => {
        const doc = app.activeDocument;
        await action.batchPlay([{
            _obj: "placeEvent",
            null: { _path: file.nativePath, _kind: "local" },
            linked: false,
        }], {});
        // Rename the placed layer
        const topLayer = doc.layers[0];
        if (topLayer) topLayer.name = layerName;
    }, { commandName: "Spellcaster Import" });
}

// ═══════════════════════════════════════════════════════════════════
//  Plugin commands
// ═══════════════════════════════════════════════════════════════════

async function cmdSmartGenerate() {
    const prompt = await showPromptDialog("What do you want to create?");
    if (!prompt) return;
    showStatus("Generating...");
    try {
        const rec = await guildAPI("/api/recommend", { prompt });
        showStatus(`Using ${rec.arch}...`);
        // TODO: wire to Guild execute endpoint
        showStatus("Done!");
    } catch (e) {
        showError(e.message);
    }
}

async function cmdUpscale() {
    showStatus("Exporting canvas...");
    try {
        // Export + upload + execute via Guild
        showStatus("Upscaling...");
        // TODO: implement upload to Guild
        showStatus("Done!");
    } catch (e) {
        showError(e.message);
    }
}

async function cmdRemoveBackground() {
    showStatus("Removing background...");
    try {
        // TODO: implement
        showStatus("Done!");
    } catch (e) {
        showError(e.message);
    }
}

async function cmdOpenGuild() {
    /** Open the Wizard Guild in the default browser. */
    require("uxp").shell.openExternal(GUILD_URL);
}

// ═══════════════════════════════════════════════════════════════════
//  UI helpers
// ═══════════════════════════════════════════════════════════════════

async function showPromptDialog(title) {
    return new Promise((resolve) => {
        const dlg = document.createElement("dialog");
        dlg.innerHTML = `
            <form method="dialog" style="padding:16px;min-width:300px;">
                <h2 style="margin:0 0 12px;font-size:16px;">${title}</h2>
                <input type="text" id="sp-prompt" style="width:100%;padding:8px;margin-bottom:12px;" />
                <div style="display:flex;gap:8px;justify-content:flex-end;">
                    <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
                    <button type="submit" uxp-variant="cta">Generate</button>
                </div>
            </form>
        `;
        dlg.addEventListener("close", () => {
            const input = dlg.querySelector("#sp-prompt");
            resolve(input ? input.value : null);
            dlg.remove();
        });
        document.body.appendChild(dlg);
        dlg.showModal();
    });
}

function showStatus(msg) {
    const el = document.getElementById("sp-status");
    if (el) el.textContent = msg;
    console.log(`[Spellcaster] ${msg}`);
}

function showError(msg) {
    const el = document.getElementById("sp-status");
    if (el) el.textContent = `Error: ${msg}`;
    console.error(`[Spellcaster] ${msg}`);
}

// ═══════════════════════════════════════════════════════════════════
//  Panel UI
// ═══════════════════════════════════════════════════════════════════

function setupPanel() {
    const panel = document.getElementById("spellcaster-panel");
    if (!panel) return;

    panel.innerHTML = `
        <div style="padding:12px;font-family:system-ui;">
            <h3 style="margin:0 0 12px;color:#B246F2;">Spellcaster</h3>
            <button id="sp-auto" style="width:100%;margin-bottom:6px;">Smart Generate</button>
            <button id="sp-upscale" style="width:100%;margin-bottom:6px;">AI Upscale (4x)</button>
            <button id="sp-rembg" style="width:100%;margin-bottom:6px;">Remove Background</button>
            <hr style="border-color:#333;margin:12px 0;" />
            <button id="sp-guild" style="width:100%;">Open Wizard Guild</button>
            <p id="sp-status" style="font-size:11px;color:#888;margin-top:8px;"></p>
        </div>
    `;

    document.getElementById("sp-auto")?.addEventListener("click", cmdSmartGenerate);
    document.getElementById("sp-upscale")?.addEventListener("click", cmdUpscale);
    document.getElementById("sp-rembg")?.addEventListener("click", cmdRemoveBackground);
    document.getElementById("sp-guild")?.addEventListener("click", cmdOpenGuild);
}

// ═══════════════════════════════════════════════════════════════════
//  Entry points
// ═══════════════════════════════════════════════════════════════════

entrypoints.setup({
    panels: {
        "spellcaster-panel": {
            show() { setupPanel(); },
        },
    },
    commands: {
        "spellcasterGenerate": cmdSmartGenerate,
        "spellcasterUpscale": cmdUpscale,
        "spellcasterRembg": cmdRemoveBackground,
        "spellcasterGuild": cmdOpenGuild,
    },
});
