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
     * Send a workflow build+dispatch request to the Guild.
     *
     * The Guild's ``/api/run_builder`` endpoint takes a builder name
     * (any ``build_*`` function in ``spellcaster_core.workflows``)
     * and a params dict. It runs the Python builder, submits to
     * ComfyUI, caches the result in the AssetGallery, and returns
     * ``/api/assets/<hash>`` URLs. Same surface Darktable uses —
     * CLAUDE.md §24 "The /api/run_builder Bridge" is the canon.
     *
     * Returns ``{ok: bool, urls: string[], error?: string}``.
     */
    const t0 = Date.now();
    let ok = false;
    let err = "";
    try {
        const resp = await fetch(`${GUILD_URL}/api/run_builder`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                builder: buildFn,
                params: params || {},
            }),
        });
        const data = await resp.json();
        if (!resp.ok || data.ok === false) {
            err = data.error || `HTTP ${resp.status}`;
            throw new Error(err);
        }
        ok = true;
        return { ok: true, urls: data.urls || [], ...data };
    } catch (e) {
        err = e.message || String(e);
        return { ok: false, urls: [], error: err };
    } finally {
        // Fire-and-forget dispatch telemetry so SpeedCoach sees
        // Photoshop renders alongside every other frontend.
        try {
            logDispatchTelemetry({
                handler: "photoshop_" + buildFn.replace(/^build_/, ""),
                buildFn: buildFn,
                elapsed: (Date.now() - t0) / 1000,
                failed: !ok,
                error: err,
            });
        } catch (_e) { /* silent */ }
    }
}

// ─── Canvas upload via AssetGallery ─────────────────────────────────

async function uploadCanvasToGuild(title) {
    /**
     * Export active document → POST bytes to the Guild's
     * AssetGallery → return ``/api/assets/<hash>`` URL. The Guild's
     * ``_translate_params`` resolves that URL to an uploaded ComfyUI
     * filename at dispatch time, so we don't have to touch ComfyUI
     * directly.
     */
    const doc = app.activeDocument;
    if (!doc) throw new Error("No active document");
    const tempFolder = await fs.getTemporaryFolder();
    const file = await tempFolder.createFile(
        "spellcaster_upload.png", { overwrite: true });
    await doc.saveAs.png(file, { compression: 6 });
    const buffer = await file.read({ format: require("uxp").storage.formats.binary });
    const hash = await stashInGallery(buffer, title || "Photoshop source");
    if (!hash) {
        throw new Error(
            "Guild AssetGallery rejected the upload. Is the Wizard "
            + "Guild running at " + GUILD_URL + " ?");
    }
    return `/api/assets/${hash}`;
}

// ─── Dispatch telemetry to the Guild ────────────────────────────────

async function logDispatchTelemetry({ handler, buildFn, arch, elapsed,
                                      failed, error }) {
    /**
     * Fire-and-forget POST to the Guild's ``/api/telemetry/dispatch_ok``
     * so every Photoshop render shows up in ``dispatch_log.jsonl``
     * alongside GIMP / Darktable / SillyTavern / Resolve / Guild-
     * internal ones. Never raises — telemetry failure must not break
     * the render.
     */
    try {
        await fetch(`${GUILD_URL}/api/telemetry/dispatch_ok`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                origin: "photoshop",
                handler: handler || "",
                build_fn: buildFn || "",
                arch: arch || "unknown",
                elapsed: Number(elapsed) || 0,
                failed: !!failed,
                error: error ? String(error).slice(0, 400) : "",
                ts: Date.now() / 1000,
            }),
        });
    } catch (_e) {
        /* Guild down — swallow */
    }
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
    /**
     * Generate a new image from a text prompt. Asks the Guild's
     * ``/api/recommend`` which architecture best fits the prompt
     * (keyword classifier over the user's installed models), then
     * dispatches the matching ``build_txt2img`` via
     * ``/api/run_builder``. Result imports as a new layer at the
     * top of the active document.
     */
    const prompt = await showPromptDialog("What do you want to create?");
    if (!prompt) return;
    showStatus("Classifying prompt…");
    try {
        let archHint = "sdxl";
        let modelHint = "";
        try {
            const rec = await guildAPI("/api/recommend", { prompt });
            if (rec && rec.arch) archHint = rec.arch;
            if (rec && rec.model) modelHint = rec.model;
        } catch (_e) {
            // Recommend is optional; fall back to sdxl.
        }
        showStatus(`Generating with ${archHint}\u2026`);
        const result = await executeWorkflow("build_txt2img", {
            prompt_text: prompt,
            negative: "",
            arch: archHint,
            model: modelHint || undefined,
            width: 1024,
            height: 1024,
            seed: Math.floor(Math.random() * 2 ** 31),
        });
        if (!result.ok) throw new Error(result.error || "generation failed");
        showStatus(`Importing ${result.urls.length} result(s)\u2026`);
        for (let i = 0; i < result.urls.length; i++) {
            const url = result.urls[i].startsWith("/")
                ? `${GUILD_URL}${result.urls[i]}`
                : result.urls[i];
            await importLayerFromURL(
                url, `Spellcaster: ${prompt.slice(0, 40)}`);
        }
        showStatus("Done.");
    } catch (e) {
        showError(e.message);
    }
}

async function cmdUpscale() {
    /**
     * 4\u00d7 upscale the active document via
     * ``build_upscale``. Uploads the canvas through the Guild's
     * AssetGallery (survives ComfyUI privacy cleanup, shared across
     * every Spellcaster surface). Result imports as a new layer.
     */
    showStatus("Uploading canvas to Guild\u2026");
    try {
        const srcRef = await uploadCanvasToGuild("Upscale source");
        showStatus("AI upscaling (4\u00d7)\u2026");
        const result = await executeWorkflow("build_upscale", {
            image_filename: srcRef,
            upscale_model: "4x-UltraSharp.pth",
        });
        if (!result.ok) throw new Error(result.error || "upscale failed");
        for (const u of result.urls) {
            const full = u.startsWith("/") ? `${GUILD_URL}${u}` : u;
            await importLayerFromURL(full, "Spellcaster Upscale 4x");
        }
        showStatus("Done.");
    } catch (e) {
        showError(e.message);
    }
}

async function cmdRemoveBackground() {
    /**
     * Remove the background of the active document via
     * ``build_rembg`` (isnet-general-use). Result is a transparent
     * PNG imported as a new layer; users can toggle the original
     * layer off to see the cutout.
     */
    showStatus("Uploading canvas to Guild\u2026");
    try {
        const srcRef = await uploadCanvasToGuild("Rembg source");
        showStatus("Removing background\u2026");
        const result = await executeWorkflow("build_rembg", {
            image_filename: srcRef,
            alpha_matting: false,
        });
        if (!result.ok) throw new Error(result.error || "rembg failed");
        for (const u of result.urls) {
            const full = u.startsWith("/") ? `${GUILD_URL}${u}` : u;
            await importLayerFromURL(full, "Spellcaster Background Removed");
        }
        showStatus("Done.");
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
