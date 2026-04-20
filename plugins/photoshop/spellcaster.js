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

    // Stash the bytes in the Guild's AssetGallery so cross-interface
    // subscribers (GIMP, Darktable, Resolve, SillyTavern, Signal) see
    // this generation via ``photoshop.asset.created``. Best-effort —
    // import continues even when the Guild is offline.
    try {
        await stashInGallery(buffer, layerName || "Photoshop result");
    } catch (e) {
        /* silent — gallery is additive, not blocking */
    }

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
//  Cross-interface backbone (§15)
// ═══════════════════════════════════════════════════════════════════

function _bytesToBase64(buffer) {
    // UXP's btoa() handles at most ~1 MB of binary-as-string; use a
    // chunked loop for larger PNGs (a 4k canvas can be 10+ MB).
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(
            null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
}

async function stashInGallery(buffer, title) {
    /** POST bytes to the Guild's AssetGallery. Fire-and-forget. */
    const body = {
        origin: "photoshop",
        kind: "generation",
        title: String(title || "Photoshop generation"),
        tags: ["photoshop_generation"],
        body_b64: _bytesToBase64(buffer),
    };
    const resp = await fetch(`${GUILD_URL}/api/assets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!resp.ok) return null;
    const json = await resp.json();
    return json && json.data && json.data.hash || null;
}

// Heartbeat loop — pings ``POST /api/interfaces/heartbeat`` every
// ~20 s so the Guild knows this Photoshop install is live and surfaces
// the chip in the sidebar. Silent on error (Guild offline); re-tries
// on every tick. Guarded by a module-level flag so repeated panel
// shows don't stack loops.
let _HEARTBEAT_STARTED = false;
function startHeartbeat(intervalS) {
    if (_HEARTBEAT_STARTED) return;
    _HEARTBEAT_STARTED = true;
    const payload = JSON.stringify({
        interface: "photoshop",
        meta: {
            plugin: "photoshop", plugin_version: "2.2.0",
            transport: "uxp_panel",
        },
        remote: false,
    });
    const tick = async () => {
        try {
            await fetch(`${GUILD_URL}/api/interfaces/heartbeat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: payload,
            });
        } catch (e) {
            /* silent — Guild offline; try again next tick */
        }
    };
    tick();  // fire immediately so the chip appears on panel show
    setInterval(tick, (intervalS || 20) * 1000);
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
            show() {
                setupPanel();
                // Fire the Guild heartbeat loop on every panel show —
                // the module-level flag keeps it single-instance.
                try { startHeartbeat(20); } catch (_) { /* silent */ }
            },
        },
    },
    commands: {
        "spellcasterGenerate": cmdSmartGenerate,
        "spellcasterUpscale": cmdUpscale,
        "spellcasterRembg": cmdRemoveBackground,
        "spellcasterGuild": cmdOpenGuild,
    },
});
