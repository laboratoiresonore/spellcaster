/**
 * Spellcaster Server Plugin for SillyTavern
 * ==========================================
 * Express router that proxies requests to ComfyUI and handles
 * workflow dispatch, image retrieval, and background management.
 *
 * Mounted at: /api/plugins/spellcaster/*
 */

import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import https from 'node:https';

// Default ComfyUI URL — overridden by settings
let COMFYUI_URL = 'http://127.0.0.1:8188';

// R111: Wizard Guild URL — separate from ComfyUI. Used for
// cross-plugin asset publishing / inbox polling via the shared event
// bus and asset gallery. Defaults to the standard Guild port; can be
// overridden via the settings endpoint.
let GUILD_URL = 'http://127.0.0.1:7777';

// Backgrounds directory (SillyTavern stores them here)
let BG_DIR = '';

/**
 * Resolve ST's characters directory from the working directory.
 */
function resolveCharactersDir() {
    const dir = path.resolve('.');
    for (const c of [
        path.join(dir, 'data', 'default-user', 'characters'),
        path.join(dir, 'public', 'characters'),
    ]) {
        if (fs.existsSync(c)) return c;
    }
    return null;
}

/**
 * Auto-detect and set BG_DIR from ST's data layout (if not already set).
 */
function autoDetectBgDir() {
    if (BG_DIR) return;
    const dir = path.resolve('.');
    for (const c of [
        path.join(dir, 'data', 'default-user', 'backgrounds'),
        path.join(dir, 'public', 'backgrounds'),
    ]) {
        if (fs.existsSync(c)) { BG_DIR = c; return; }
    }
}

/**
 * Fetch JSON from a URL (Node.js native, no dependencies).
 */
function fetchJSON(url, options = {}) {
    return new Promise((resolve, reject) => {
        const mod = url.startsWith('https') ? https : http;
        const parsedUrl = new URL(url);
        const reqOpts = {
            hostname: parsedUrl.hostname,
            port: parsedUrl.port,
            path: parsedUrl.pathname + parsedUrl.search,
            method: options.method || 'GET',
            headers: options.headers || {},
        };
        const req = mod.request(reqOpts, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try { resolve({ status: res.statusCode, data: JSON.parse(data) }); }
                catch { resolve({ status: res.statusCode, data: data }); }
            });
        });
        req.on('error', reject);
        if (options.body) req.write(options.body);
        req.end();
    });
}

/**
 * Fetch raw bytes from a URL.
 */
function fetchBytes(url) {
    return new Promise((resolve, reject) => {
        const mod = url.startsWith('https') ? https : http;
        mod.get(url, (res) => {
            const chunks = [];
            res.on('data', chunk => chunks.push(chunk));
            res.on('end', () => resolve(Buffer.concat(chunks)));
            res.on('error', reject);
        }).on('error', reject);
    });
}

/**
 * Submit a workflow to ComfyUI and poll for the result.
 * Returns { images: [base64...], videos: [base64...] } or throws.
 */
async function dispatchWorkflow(workflow, timeoutMs = 180000) {
    // Submit
    const submitRes = await fetchJSON(`${COMFYUI_URL}/prompt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: workflow }),
    });

    if (submitRes.status !== 200 || !submitRes.data.prompt_id) {
        throw new Error(`ComfyUI rejected workflow: ${JSON.stringify(submitRes.data)}`);
    }

    const promptId = submitRes.data.prompt_id;
    const deadline = Date.now() + timeoutMs;

    // Poll for completion
    while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 500));
        try {
            const histRes = await fetchJSON(`${COMFYUI_URL}/history/${promptId}`);
            if (!histRes.data[promptId]) continue;

            const entry = histRes.data[promptId];
            const status = entry.status || {};
            if (status.status_str === 'error') {
                const msgs = status.messages || [];
                const err = msgs.length ? msgs[msgs.length - 1][1].exception_message : 'Unknown';
                throw new Error(`ComfyUI execution failed: ${err}`);
            }

            const outputs = entry.outputs || {};
            const result = { images: [], videos: [], prompt_id: promptId };

            for (const [nid, nodeOut] of Object.entries(outputs)) {
                if (nodeOut.images) {
                    for (const img of nodeOut.images) {
                        const fn = img.filename;
                        const sub = img.subfolder || '';
                        const imgType = img.type || 'output';  // Respect privacy mode redirects
                        const url = `${COMFYUI_URL}/view?filename=${fn}&type=${imgType}${sub ? '&subfolder=' + sub : ''}`;
                        const bytes = await fetchBytes(url);
                        result.images.push({
                            base64: bytes.toString('base64'),
                            filename: fn,
                            url: url,
                        });
                    }
                }
                if (nodeOut.gifs) {
                    for (const gif of nodeOut.gifs) {
                        const fn = gif.filename;
                        const sub = gif.subfolder || '';
                        const gifType = gif.type || 'output';
                        const url = `${COMFYUI_URL}/view?filename=${fn}&type=${gifType}${sub ? '&subfolder=' + sub : ''}`;
                        const bytes = await fetchBytes(url);
                        result.videos.push({
                            base64: bytes.toString('base64'),
                            filename: fn,
                            url: url,
                        });
                    }
                }
            }

            if (result.images.length > 0 || result.videos.length > 0) {
                return result;
            }
        } catch (e) {
            if (e.message.includes('execution failed')) throw e;
            // Network error — retry
        }
    }
    throw new Error('Timeout waiting for ComfyUI');
}

// Validate image bytes by magic-header sniffing. Node doesn't ship
// an image decoder, but every modern image format has a deterministic
// header — enough to catch the "SillyTavern sent us HTML or a
// truncated base64 string" case before it burns 40 s of WAN model
// load on an eventual LoadImage failure.
//
// Returns { ok, kind, mime, reason } — ok=false bubbles up to the
// caller as an HTTP 400. kind is 'png'|'jpeg'|'webp'|'gif'|'bmp'|'tiff'.
function _sniffImage(buf) {
    if (!buf || buf.length < 16) {
        return { ok: false, reason: `empty or truncated (${buf ? buf.length : 0} bytes)` };
    }
    const b = buf;
    // PNG: 89 50 4E 47 0D 0A 1A 0A
    if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4E && b[3] === 0x47) {
        return { ok: true, kind: 'png', mime: 'image/png' };
    }
    // JPEG: FF D8 FF
    if (b[0] === 0xFF && b[1] === 0xD8 && b[2] === 0xFF) {
        return { ok: true, kind: 'jpeg', mime: 'image/jpeg' };
    }
    // WebP: "RIFF....WEBP"
    if (b[0] === 0x52 && b[1] === 0x49 && b[2] === 0x46 && b[3] === 0x46
        && b[8] === 0x57 && b[9] === 0x45 && b[10] === 0x42 && b[11] === 0x50) {
        return { ok: true, kind: 'webp', mime: 'image/webp' };
    }
    // GIF: "GIF87a" / "GIF89a"
    if (b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46 && b[3] === 0x38) {
        return { ok: true, kind: 'gif', mime: 'image/gif' };
    }
    // BMP: "BM"
    if (b[0] === 0x42 && b[1] === 0x4D) {
        return { ok: true, kind: 'bmp', mime: 'image/bmp' };
    }
    // TIFF: "II*\0" (little-endian) or "MM\0*" (big-endian)
    if ((b[0] === 0x49 && b[1] === 0x49 && b[2] === 0x2A && b[3] === 0x00)
        || (b[0] === 0x4D && b[1] === 0x4D && b[2] === 0x00 && b[3] === 0x2A)) {
        return { ok: true, kind: 'tiff', mime: 'image/tiff' };
    }
    const head = Array.from(b.slice(0, 8))
        .map(n => n.toString(16).padStart(2, '0')).join(' ');
    return { ok: false, reason: `unrecognised magic bytes (${head})` };
}

/**
 * Upload an image to ComfyUI's input folder.
 *
 * Validates the buffer is an image before upload — WAN's LoadImage
 * would otherwise silently accept any bytes and crash mid-render
 * inside the 14B model load. TIFF/BMP/GIF/WebP/JPEG/PNG all pass
 * through with their proper mime type so ComfyUI's Pillow-based
 * LoadImage can decode them.
 *
 * Throws a specific Error on bad bytes so the caller can surface a
 * "not an image" message to the SillyTavern user.
 */
async function uploadToComfyUI(imageBuffer, filename) {
    const sniff = _sniffImage(imageBuffer);
    if (!sniff.ok) {
        throw new Error(`Upload rejected: ${filename} is not an image — ${sniff.reason}`);
    }
    const boundary = '----SpellcasterUpload' + Date.now();
    const body = Buffer.concat([
        Buffer.from(
            `--${boundary}\r\n` +
            `Content-Disposition: form-data; name="image"; filename="${filename}"\r\n` +
            `Content-Type: ${sniff.mime}\r\n\r\n`
        ),
        imageBuffer,
        Buffer.from(`\r\n--${boundary}--\r\n`),
    ]);

    return fetchJSON(`${COMFYUI_URL}/upload/image`, {
        method: 'POST',
        headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
        body: body,
    });
}

/**
 * Initialize the Express router.
 */
function init(router) {
    // ── Settings ──
    router.post('/settings', (req, res) => {
        if (req.body.comfyui_url) {
            const newUrl = req.body.comfyui_url.replace(/\/+$/, '');
            if (newUrl !== COMFYUI_URL) {
                COMFYUI_URL = newUrl;
                _cachedModel = null;  // Invalidate — new server may have different models
            }
        }
        if (req.body.guild_url) {
            GUILD_URL = String(req.body.guild_url).replace(/\/+$/, '');
        }
        if (req.body.backgrounds_dir) {
            BG_DIR = req.body.backgrounds_dir;
        }
        autoDetectBgDir();  // Auto-detect if not explicitly set
        res.json({
            status: 'ok',
            comfyui_url: COMFYUI_URL,
            guild_url: GUILD_URL,
            bg_dir: BG_DIR,
        });
    });

    // ══════════════════════════════════════════════════════════════════
    // R111: Cross-plugin transfer routes — server-plugin proxies to the
    // Wizard Guild's shared asset gallery + event bus so the browser
    // extension can send images to Resolve / GIMP / Darktable and pull
    // its own pending inbox. Server-side forwarding avoids CORS issues
    // on browsers that reject cross-origin fetches to 127.0.0.1:7777.
    // ══════════════════════════════════════════════════════════════════

    // POST /cross/send — publish the supplied image to <target>.
    // Body: { target: 'resolve'|'gimp'|'darktable',
    //         image_data_url: '<data:image/png;base64,...>',
    //         title?: string }
    // OR:   { target, image_url: '<absolute http url>' }
    // Returns: { ok, hash, asset_url }
    router.post('/cross/send', async (req, res) => {
        const target = String(req.body.target || '').trim().toLowerCase();
        if (!['resolve', 'gimp', 'darktable', 'sillytavern'].includes(target)) {
            return res.status(400).json({
                error: 'target must be one of: resolve, gimp, darktable, sillytavern',
            });
        }
        // Resolve body_b64 from whichever source the caller provided.
        let body_b64 = '';
        if (req.body.image_data_url) {
            const comma = req.body.image_data_url.indexOf(',');
            body_b64 = comma >= 0
                ? req.body.image_data_url.slice(comma + 1)
                : req.body.image_data_url;
        } else if (req.body.image_url) {
            // Server-side fetch the absolute URL then base64.
            try {
                const bin = await new Promise((resolve, reject) => {
                    const mod = req.body.image_url.startsWith('https')
                        ? https : http;
                    mod.get(req.body.image_url, (r) => {
                        const chunks = [];
                        r.on('data', (c) => chunks.push(c));
                        r.on('end', () => resolve(Buffer.concat(chunks)));
                        r.on('error', reject);
                    }).on('error', reject);
                });
                body_b64 = bin.toString('base64');
            } catch (e) {
                return res.status(502).json({
                    error: 'image_url fetch failed: ' + e.message,
                });
            }
        } else {
            return res.status(400).json({
                error: 'need image_data_url or image_url',
            });
        }
        if (!body_b64) {
            return res.status(400).json({ error: 'empty image data' });
        }
        // 1) upload to /api/assets
        let rec;
        try {
            const up = await fetchJSON(`${GUILD_URL}/api/assets`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    origin: 'sillytavern',
                    kind: 'asset',
                    title: req.body.title || `From SillyTavern → ${target}`,
                    tags: [`to_${target}`, 'sillytavern_export'],
                    body_b64,
                }),
            });
            rec = up.data;
        } catch (e) {
            return res.status(502).json({ error: 'guild upload failed: ' + e.message });
        }
        if (!rec || !rec.hash) {
            return res.status(502).json({
                error: 'guild upload returned no hash',
                detail: rec,
            });
        }
        const asset_url = `/api/assets/${rec.hash}`;
        // 2) publish <target>.asset.send event — mailbox fanout
        //    routes it to the target interface's inbox automatically.
        try {
            await fetchJSON(`${GUILD_URL}/api/events/emit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    kind: `${target}.asset.send`,
                    origin: 'sillytavern',
                    data: {
                        image_url: asset_url,
                        hash: rec.hash,
                        source: 'sillytavern',
                        title: req.body.title || '',
                    },
                }),
            });
        } catch (e) {
            // Upload succeeded, publish failed — still useful for manual
            // pickup via the asset URL. Report the mixed state.
            return res.json({
                ok: true,
                hash: rec.hash,
                asset_url: `${GUILD_URL}${asset_url}`,
                warning: 'event publish failed: ' + e.message,
            });
        }
        res.json({
            ok: true,
            hash: rec.hash,
            asset_url: `${GUILD_URL}${asset_url}`,
        });
    });

    // GET /capabilities — probe the configured ComfyUI's /object_info
    // and return { available: [arch,...], missing: [arch,...], nodes: N }.
    // Used by /sc-capabilities slash command + any future UI gating.
    // Mirrors the Darktable R118 / GIMP _FEATURE_SENTINELS approach.
    router.get('/capabilities', async (req, res) => {
        const sentinels = {
            'Flux 2 Klein':     ['Flux2KleinRefLatentController', 'Flux2KleinTextRefBalance'],
            'Flux Kontext':     ['FluxKontextImageScale', 'FluxKontextModelLoader'],
            'Flux 1 Dev':       ['FluxGuidance', 'DualCLIPLoader'],
            'SDXL':             ['KSamplerAdvanced'],
            'SD 1.5':           ['KSampler'],
            'Wan 2.2 Video':    ['WanImageToVideo', 'LoadWanVideoModel', 'WanVaceToVideo'],
            'LTX-2 Video':      ['LTXVImgToVideo', 'LTXVScheduler'],
            'SUPIR Upscale':    ['SUPIR_sample'],
            'SeedVR2 Video':    ['SeedVR2VideoUpscaler'],
            'IPAdapter':        ['IPAdapterAdvanced', 'IPAdapterUnifiedLoader'],
            'Face: ReActor':    ['ReActorFaceSwap'],
            'Face: PuLID Flux': ['PulidFluxModelLoader', 'ApplyPulidFlux'],
            'BG Remove':        ['BiRefNetRMBG', 'RMBG'],
            'Inpaint (LaMa)':   ['LaMaInpaint'],
            'Chroma':           ['ChromaSampler'],
        };
        let catalog = null;
        try {
            const r = await fetchJSON(`${COMFYUI_URL}/object_info`);
            catalog = r.data;
        } catch (e) {
            return res.status(502).json({
                error: 'ComfyUI unreachable: ' + e.message,
                comfyui: COMFYUI_URL,
            });
        }
        if (typeof catalog !== 'object' || catalog === null) {
            return res.status(502).json({
                error: 'ComfyUI returned unexpected /object_info shape',
            });
        }
        const nodes = new Set(Object.keys(catalog));
        const available = [];
        const missing = [];
        for (const [arch, list] of Object.entries(sentinels)) {
            let ok = false;
            for (const n of list) { if (nodes.has(n)) { ok = true; break; } }
            (ok ? available : missing).push(arch);
        }
        available.sort();
        missing.sort();
        res.json({
            comfyui: COMFYUI_URL,
            node_count: nodes.size,
            available,
            missing,
        });
    });

    // GET /cross/inbox — pull pending sillytavern.asset.* messages.
    // Returns: { messages: [{kind, data:{image_url,hash,source,...}}] }
    router.get('/cross/inbox', async (req, res) => {
        try {
            const consume = (req.query.consume || '1');
            const max = Math.min(100, parseInt(req.query.max || '20', 10));
            const r = await fetchJSON(
                `${GUILD_URL}/api/sillytavern/inbox?consume=${consume}&max=${max}`);
            const messages = ((r.data && r.data.messages) || [])
                .filter(m => (m.kind || '').startsWith('sillytavern.asset.'));
            // Resolve relative image_urls to absolute so the extension
            // can render them directly without knowing the Guild URL.
            for (const m of messages) {
                const d = m.data || {};
                if (d.image_url && d.image_url.startsWith('/')) {
                    d.image_url = `${GUILD_URL}${d.image_url}`;
                }
            }
            res.json({ messages });
        } catch (e) {
            res.status(502).json({ error: 'inbox fetch failed: ' + e.message });
        }
    });

    // ── Health check ──
    router.get('/health', async (req, res) => {
        try {
            const r = await fetchJSON(`${COMFYUI_URL}/system_stats`);
            res.json({ comfyui: 'connected', url: COMFYUI_URL });
        } catch {
            res.json({ comfyui: 'offline', url: COMFYUI_URL });
        }
    });

    // ── Generate image from text prompt ──
    router.post('/generate', async (req, res) => {
        try {
            const { prompt, negative, width, height, seed, style } = req.body;
            const model = await detectBestModel();
            if (!model) return res.status(500).json({ error: 'No checkpoint models found on ComfyUI' });
            const workflow = buildTxt2ImgWorkflow(
                prompt || 'a beautiful scene',
                negative || 'blurry, low quality',
                width || 1024, height || 768,
                seed || Math.floor(Math.random() * 2147483647),
                model
            );
            const result = await dispatchWorkflow(workflow);
            res.json({
                status: 'ok',
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Generate scene background ──
    router.post('/scene', async (req, res) => {
        try {
            const { description, width, height, style } = req.body;
            // Klein scene prompts are natural language; no quality-tag
            // boilerplate (Klein penalises it). SDXL keeps the tags so
            // ordinary checkpoints still produce cinematic output.
            const kleinPrompt = `${description}, cinematic scene, atmospheric, detailed environment`;
            const sdxlPrompt  = `${description}, cinematic scene, atmospheric, professional photography, 8k, detailed environment`;
            const negative = 'people, characters, faces, text, watermark, blurry, low quality';

            // Pick engine: Klein > Kontext > SDXL. Klein and Kontext
            // share the detector with /edit.
            const engine = await detectEditEngine();
            let workflow = null;
            let usedEngine = engine;
            if (engine === "klein") {
                workflow = buildKleinTxt2ImgWorkflow(kleinPrompt, {
                    width:  _roundMod(width  || 1280, 16, 256),
                    height: _roundMod(height || 720,  16, 256),
                });
            } else {
                const model = await detectBestModel();
                if (!model) return res.status(500).json({ error: 'No checkpoint models found on ComfyUI' });
                usedEngine = "sdxl";
                workflow = buildTxt2ImgWorkflow(
                    sdxlPrompt, negative,
                    width || 1280, height || 720,
                    Math.floor(Math.random() * 2147483647),
                    model,
                );
            }
            const result = await dispatchWorkflow(workflow);

            // Save as background file if BG_DIR is set
            let bgFilename = null;
            if (BG_DIR && result.images.length > 0) {
                bgFilename = `spellcaster_scene_${Date.now()}.png`;
                const bgPath = path.join(BG_DIR, bgFilename);
                fs.writeFileSync(bgPath, Buffer.from(result.images[0].base64, 'base64'));
            }

            res.json({
                status: 'ok',
                engine: usedEngine,
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
                bg_filename: bgFilename,
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Restyle an image (img2img / style transfer) ──
    router.post('/restyle', async (req, res) => {
        try {
            const { image_base64, prompt, style, denoise } = req.body;
            if (!image_base64) return res.status(400).json({ error: 'image_base64 required' });

            const imgBuf = Buffer.from(image_base64, 'base64');
            const uploadName = `spellcaster_restyle_${Date.now()}.png`;
            await uploadToComfyUI(imgBuf, uploadName);

            // Route through the best-available img2img engine:
            //   Klein 2 → Flux Kontext → SDXL img2img
            // All three accept the same denoise slider so the
            // existing client UX (slider 0.3..0.7) still maps cleanly.
            const engine = await detectEditEngine();
            let workflow = null;
            let usedEngine = engine;
            const effectivePrompt = prompt ||
                'photorealistic portrait, professional photography, detailed';
            if (engine === "klein") {
                workflow = buildKleinEditWorkflow(uploadName, effectivePrompt, {
                    denoise: denoise || 0.55,
                });
            } else if (engine === "kontext") {
                workflow = buildKontextEditWorkflow(uploadName, effectivePrompt, {
                    denoise: denoise || 0.55,
                });
            } else {
                const model = await detectBestModel();
                if (!model) return res.status(500).json({
                    error: 'No checkpoint models found on ComfyUI',
                });
                usedEngine = "sdxl";
                workflow = buildImg2ImgWorkflow(
                    uploadName, effectivePrompt,
                    'cartoon, anime, drawing, sketch, blurry, low quality',
                    denoise || 0.55, model,
                );
            }
            const result = await dispatchWorkflow(workflow);
            res.json({
                status: 'ok',
                engine: usedEngine,
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Semantic edit-by-prompt ────────────────────────────────────
    // Like /restyle but tuned for instructions rather than full
    // style transforms. Routed through the same engine waterfall:
    //   Klein 2 img2img  →  Flux Kontext  →  SDXL img2img
    // Default denoise is 0.55; callers can pass 0.3 for subtle
    // tweaks ("add glasses") or 0.75 for heavier redesigns.
    router.post('/edit', async (req, res) => {
        try {
            const { image_base64, instruction, denoise, engine: forceEngine } = req.body || {};
            if (!image_base64) return res.status(400).json({ error: 'image_base64 required' });
            if (!instruction) return res.status(400).json({ error: 'instruction required' });

            const imgBuf = Buffer.from(image_base64, 'base64');
            const uploadName = `spellcaster_edit_${Date.now()}.png`;
            await uploadToComfyUI(imgBuf, uploadName);

            const engine = (forceEngine && ["klein","kontext","sdxl"].includes(forceEngine))
                ? forceEngine : await detectEditEngine();
            let workflow = null;
            let usedEngine = engine;
            if (engine === "klein") {
                workflow = buildKleinEditWorkflow(uploadName, instruction, {
                    denoise: denoise || 0.55,
                });
            } else if (engine === "kontext") {
                workflow = buildKontextEditWorkflow(uploadName, instruction, {
                    denoise: denoise || 1.0,
                });
            } else {
                const model = await detectBestModel();
                if (!model) return res.status(500).json({
                    error: 'No edit engine available on ComfyUI',
                });
                usedEngine = "sdxl";
                workflow = buildImg2ImgWorkflow(
                    uploadName, instruction,
                    'blurry, low quality, distorted',
                    denoise || 0.55, model,
                );
            }
            const result = await dispatchWorkflow(workflow);
            res.json({
                status: 'ok',
                engine: usedEngine,
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Save restyled avatar (backup original as .bak.png, then replace) ──
    router.post('/save-avatar', (req, res) => {
        try {
            const { avatar_filename, image_base64 } = req.body;
            if (!avatar_filename || !image_base64) {
                return res.status(400).json({ error: 'avatar_filename and image_base64 required' });
            }

            const charDir = resolveCharactersDir();
            if (!charDir) {
                return res.status(500).json({ error: 'Cannot find SillyTavern characters directory' });
            }

            const avatarPath = path.join(charDir, path.basename(avatar_filename));
            if (!fs.existsSync(avatarPath)) {
                return res.status(404).json({ error: `Avatar not found: ${avatar_filename}` });
            }

            // Create backup (only if no backup exists yet — preserve the true original)
            const bakPath = avatarPath.replace(/\.png$/i, '.bak.png');
            if (!fs.existsSync(bakPath)) {
                fs.copyFileSync(avatarPath, bakPath);
            }

            // Write the restyled image
            const imgBuf = Buffer.from(image_base64, 'base64');
            fs.writeFileSync(avatarPath, imgBuf);

            res.json({ status: 'ok', backed_up: bakPath, avatar: avatarPath });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Restore original avatar from .bak.png ──
    router.post('/restore-avatar', (req, res) => {
        try {
            const { avatar_filename } = req.body;
            if (!avatar_filename) {
                return res.status(400).json({ error: 'avatar_filename required' });
            }

            const charDir = resolveCharactersDir();
            if (!charDir) {
                return res.status(500).json({ error: 'Cannot find SillyTavern characters directory' });
            }

            const avatarPath = path.join(charDir, path.basename(avatar_filename));
            const bakPath = avatarPath.replace(/\.png$/i, '.bak.png');

            if (!fs.existsSync(bakPath)) {
                return res.status(404).json({ error: 'No backup found — avatar was never restyled' });
            }

            // Restore original
            fs.copyFileSync(bakPath, avatarPath);
            fs.unlinkSync(bakPath);

            res.json({ status: 'ok', restored: avatarPath });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Generate animated moment (video) ──
    // Preference order:
    //   1. WAN 2.2 I2V via canonical two-pass pipeline (real motion)
    //   2. Fallback to the legacy noise-injection path (NOT real video,
    //      just frame-variation jitter). Only lands here when the Guild
    //      preset fetch returned null (no WAN install or Guild offline).
    //
    // Client response shape is unchanged — { status, videos:[], images:[] }.
    // WAN output is a GIF (see buildWanI2VWorkflow notes on format).
    router.post('/animate', async (req, res) => {
        try {
            const { image_base64, prompt, length, turbo, pingpong,
                    engine, end_image_base64, i2v_strength } = req.body || {};
            if (!image_base64) return res.status(400).json({ error: 'image_base64 required' });

            const imgBuf = Buffer.from(image_base64, 'base64');
            const uploadName = `spellcaster_anim_${Date.now()}.png`;
            await uploadToComfyUI(imgBuf, uploadName);

            // Optional first-last-frame end image — uploads alongside
            // the start frame. WAN supports this natively via
            // WanFirstLastFrameToVideo; LTX ignores it for now.
            let endUploadName = null;
            if (end_image_base64) {
                const endBuf = Buffer.from(end_image_base64, 'base64');
                endUploadName = `spellcaster_anim_end_${Date.now()}.png`;
                await uploadToComfyUI(endBuf, endUploadName);
            }

            // Engine selection:
            //   engine="wan"    → force WAN (default; auto-detects preset)
            //   engine="ltx"    → force LTX-2
            //   engine="legacy" → force the noise-injection fallback
            //   engine undefined → try WAN first, then LTX, then legacy
            const wantLtx    = engine === "ltx";
            const wantLegacy = engine === "legacy";
            const wantWan    = engine === "wan" || engine === undefined;

            let workflow = null;
            let usedEngine = "legacy";

            if (!wantLegacy && wantWan) {
                const wanPreset = await fetchVideoPreset("wan");
                if (wanPreset) {
                    usedEngine = "wan";
                    workflow = buildWanI2VWorkflow(
                        uploadName,
                        prompt || 'subtle breathing, gentle movement, living portrait',
                        wanPreset,
                        {
                            length: length || 33,
                            turbo:    turbo    !== undefined ? !!turbo    : true,
                            pingpong: pingpong !== undefined ? !!pingpong : true,
                            endImage: endUploadName,
                        },
                    );
                }
            }

            if (workflow === null && !wantLegacy && (wantLtx || engine === undefined)) {
                const ltxPreset = await fetchVideoPreset("ltx");
                if (ltxPreset) {
                    usedEngine = "ltx";
                    workflow = buildLtxI2VWorkflow(
                        uploadName,
                        prompt || 'subtle breathing, gentle movement, living portrait',
                        ltxPreset,
                        {
                            length: length || 25,
                            pingpong: pingpong !== undefined ? !!pingpong : true,
                            distilled: turbo !== undefined ? !!turbo : true,
                            i2v_strength: i2v_strength || 0.9,
                        },
                    );
                }
            }

            if (workflow === null) {
                // No preset available, or the caller forced legacy mode.
                workflow = buildAnimationWorkflow(
                    uploadName,
                    prompt || 'subtle animation, gentle movement',
                    length || 8,
                );
            }

            // WAN full-step can take 60-120s on the RTX 5060 Ti;
            // turbo ~20s. Keep 300s ceiling so slow servers don't
            // bail early on a valid job.
            const result = await dispatchWorkflow(workflow, 300000);
            res.json({
                status: 'ok',
                engine: usedEngine,
                videos: result.videos.map(v => ({ base64: v.base64, filename: v.filename })),
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Save expression sprite to ST's expressions folder ──
    router.post('/save-expression', (req, res) => {
        try {
            const { character_name, emotion, image_base64 } = req.body;
            if (!character_name || !emotion || !image_base64) {
                return res.status(400).json({ error: 'character_name, emotion, and image_base64 required' });
            }

            // ST stores expressions at: data/default-user/characters/<CharName>/
            const charDir = resolveCharactersDir();
            if (!charDir) {
                return res.status(500).json({ error: 'Cannot find SillyTavern characters directory' });
            }

            // Expression sprites go in a subfolder named after the character
            const exprDir = path.join(charDir, character_name);
            if (!fs.existsSync(exprDir)) {
                fs.mkdirSync(exprDir, { recursive: true });
            }

            const exprPath = path.join(exprDir, `${emotion}.png`);
            fs.writeFileSync(exprPath, Buffer.from(image_base64, 'base64'));

            res.json({ status: 'ok', path: exprPath });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Generate character portrait ──
    router.post('/portrait', async (req, res) => {
        try {
            const { description, width, height } = req.body;
            // Klein portrait prompts are conversational; SDXL gets the
            // photographic-studio tag trailer it needs.
            const kleinPrompt = `${description}, portrait photograph, 85mm lens, shallow depth of field, studio lighting, detailed face`;
            const sdxlPrompt  = `${description}, portrait photograph, 85mm lens, shallow depth of field, studio lighting, professional headshot, detailed face, 8k`;
            const negative = 'blurry, distorted, deformed, low quality, cartoon, watermark';

            // Default portrait size is 400×600 — tiny for Klein, which
            // wants ~1 MP. Upscale the request to 640×960 for Klein
            // (mod-16, ~0.6 MP, close to Klein's sweet spot) so output
            // is actually detailed.
            const engine = await detectEditEngine();
            let workflow = null;
            let usedEngine = engine;
            if (engine === "klein") {
                workflow = buildKleinTxt2ImgWorkflow(kleinPrompt, {
                    width:  _roundMod(width  || 640, 16, 256),
                    height: _roundMod(height || 960, 16, 256),
                });
            } else {
                const model = await detectBestModel();
                if (!model) return res.status(500).json({ error: 'No checkpoint models found on ComfyUI' });
                usedEngine = "sdxl";
                workflow = buildTxt2ImgWorkflow(
                    sdxlPrompt, negative,
                    width || 400, height || 600,
                    Math.floor(Math.random() * 2147483647),
                    model,
                );
            }
            const result = await dispatchWorkflow(workflow);
            res.json({
                status: 'ok',
                engine: usedEngine,
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ═══════════════════════════════════════════════════════════════
    //  Magic Studios Endpoints
    // ═══════════════════════════════════════════════════════════════

    // ── Cast: create face model from character avatar ──
    router.post('/studio/cast', async (req, res) => {
        try {
            const { avatar_base64, character_name } = req.body;
            if (!avatar_base64 || !character_name) {
                return res.status(400).json({ error: 'avatar_base64 and character_name required' });
            }

            // Sanitize name for filesystem
            const safeName = character_name.replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 30);
            const faceModelName = `spellcaster_${safeName}`;

            // Upload avatar to ComfyUI
            const imgBuf = Buffer.from(avatar_base64, 'base64');
            const uploadName = `spellcaster_avatar_${safeName}.png`;
            await uploadToComfyUI(imgBuf, uploadName);

            // Build and dispatch cast workflow
            const workflow = buildCastWorkflow(uploadName, faceModelName);
            const result = await dispatchWorkflow(workflow, 60000);

            // Track asset
            studioAssets[character_name] = studioAssets[character_name] || {};
            studioAssets[character_name].face_model = faceModelName;
            studioAssets[character_name].avatar_upload = uploadName;

            res.json({
                status: 'ok',
                face_model: faceModelName,
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Body: generate full-body transparent PNG with face swap ──
    router.post('/studio/body', async (req, res) => {
        try {
            const { character_name, description, attire } = req.body;
            if (!character_name) {
                return res.status(400).json({ error: 'character_name required' });
            }

            const assets = studioAssets[character_name];
            if (!assets?.avatar_upload) {
                return res.status(400).json({ error: `Character "${character_name}" has not been cast yet. Use /studio-cast first.` });
            }

            const model = await detectBestModel();
            if (!model) return res.status(500).json({ error: 'No checkpoint models found' });

            const bodyPrompt = description || attire ||
                `portrait of ${character_name}, neutral background, natural pose`;

            const workflow = buildBodyWorkflow(assets.avatar_upload, bodyPrompt, model);
            const result = await dispatchWorkflow(workflow, 180000);

            // Upload the transparent body back to ComfyUI input for later compositing
            if (result.images?.[0]) {
                const bodyBuf = Buffer.from(result.images[0].base64, 'base64');
                const bodyName = `spellcaster_body_${assets.face_model}.png`;
                await uploadToComfyUI(bodyBuf, bodyName);
                assets.body_image = bodyName;
                assets.body_prompt = bodyPrompt;
            }

            res.json({
                status: 'ok',
                body_image: assets.body_image,
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Studio scene: generate scene with characters composited in ──
    router.post('/studio/scene', async (req, res) => {
        try {
            const { description, characters, width, height } = req.body;
            // characters: [{ name, attire, placement: { x, y, scale } }]
            if (!description) {
                return res.status(400).json({ error: 'description required' });
            }

            const model = await detectBestModel();
            if (!model) return res.status(500).json({ error: 'No checkpoint models found' });

            // Resolve which characters have body images ready
            const charsToComposite = [];
            const castNeeded = [];
            const bodyNeeded = [];

            const charList = characters || Object.keys(studioAssets)
                .filter(n => studioAssets[n]?.body_image)
                .map(n => ({ name: n }));

            for (const charReq of charList) {
                const assets = studioAssets[charReq.name];
                if (!assets?.body_image) {
                    if (!assets?.face_model) {
                        castNeeded.push(charReq.name);
                    } else {
                        bodyNeeded.push(charReq.name);
                    }
                    continue;
                }

                // If attire specified and different from current, regenerate body
                if (charReq.attire && charReq.attire !== assets.body_prompt) {
                    const bodyPrompt = `${charReq.attire}, full body, standing, ${charReq.name}`;
                    const bodyWf = buildBodyWorkflow(assets.avatar_upload, bodyPrompt, model);
                    const bodyResult = await dispatchWorkflow(bodyWf, 180000);
                    if (bodyResult.images?.[0]) {
                        const bodyBuf = Buffer.from(bodyResult.images[0].base64, 'base64');
                        await uploadToComfyUI(bodyBuf, assets.body_image);
                        assets.body_prompt = charReq.attire;
                    }
                }

                charsToComposite.push({
                    bodyImageName: assets.body_image,
                    placement: charReq.placement || {},
                });
            }

            if (charsToComposite.length === 0 && charList.length > 0) {
                const missing = [...castNeeded.map(n => `${n} (needs /studio-cast)`),
                                 ...bodyNeeded.map(n => `${n} (needs /studio-body)`)];
                return res.status(400).json({
                    error: `No characters ready for compositing. Missing: ${missing.join(', ')}`,
                });
            }

            let result;
            let bgFilename = null;

            if (charsToComposite.length > 0) {
                // Generate scene with characters
                const workflow = buildSceneCompositeWorkflow(description, charsToComposite, model);
                result = await dispatchWorkflow(workflow, 300000);
            } else {
                // No characters — just generate the scene
                const prompt = `${description}, cinematic scene, atmospheric, 8k`;
                const negative = 'people, characters, faces, text, watermark, blurry, low quality';
                const workflow = buildTxt2ImgWorkflow(
                    prompt, negative, width || 1280, height || 720,
                    Math.floor(Math.random() * 2147483647), model
                );
                result = await dispatchWorkflow(workflow);
            }

            // Save as ST background
            if (BG_DIR && result.images?.length > 0) {
                bgFilename = `spellcaster_studio_${Date.now()}.png`;
                const bgPath = path.join(BG_DIR, bgFilename);
                fs.writeFileSync(bgPath, Buffer.from(result.images[0].base64, 'base64'));
            }

            res.json({
                status: 'ok',
                characters_composited: charsToComposite.length,
                bg_filename: bgFilename,
                images: result.images.map(i => ({ base64: i.base64, filename: i.filename })),
            });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── List studio assets ──
    router.get('/studio/assets', (req, res) => {
        const summary = {};
        for (const [name, assets] of Object.entries(studioAssets)) {
            summary[name] = {
                cast: !!assets.face_model,
                body: !!assets.body_image,
                face_model: assets.face_model || null,
            };
        }
        res.json({ status: 'ok', characters: summary });
    });

    // ── Raw workflow dispatch ──
    router.post('/dispatch', async (req, res) => {
        try {
            const { workflow, timeout } = req.body;
            if (!workflow) return res.status(400).json({ error: 'workflow required' });
            const result = await dispatchWorkflow(workflow, timeout || 180000);
            res.json({ status: 'ok', ...result });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    console.log('[Spellcaster] Server plugin loaded. ComfyUI:', COMFYUI_URL);
}

// ═══════════════════════════════════════════════════════════════════
//  Model Auto-Detection
// ═══════════════════════════════════════════════════════════════════

let _cachedModel = null;

async function detectBestModel() {
    if (_cachedModel) return _cachedModel;
    try {
        const res = await fetchJSON(`${COMFYUI_URL}/object_info/CheckpointLoaderSimple`);
        const ckpts = res.data?.CheckpointLoaderSimple?.input?.required?.ckpt_name?.[0] || [];
        // Prefer: flux > xl > juggernaut > anything
        const priorities = ['flux', 'xl', 'jugger', 'reborn', 'realistic'];
        for (const kw of priorities) {
            const match = ckpts.find(c => c.toLowerCase().includes(kw));
            if (match) { _cachedModel = match; return match; }
        }
        if (ckpts.length > 0) { _cachedModel = ckpts[0]; return ckpts[0]; }
    } catch { /* fallback */ }
    return null;
}

// ═══════════════════════════════════════════════════════════════════
//  Workflow Builders (minimal self-contained — no Python dependency)
// ═══════════════════════════════════════════════════════════════════

function buildTxt2ImgWorkflow(prompt, negative, width, height, seed, modelName) {
    return {
        "3": { "class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 25, "cfg": 7.0,
            "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "denoise": 1.0, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]
        }},
        "4": { "class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": modelName
        }},
        "5": { "class_type": "EmptyLatentImage", "inputs": {
            "width": width, "height": height, "batch_size": 1
        }},
        "6": { "class_type": "CLIPTextEncode", "inputs": {
            "text": prompt, "clip": ["4", 1]
        }},
        "7": { "class_type": "CLIPTextEncode", "inputs": {
            "text": negative, "clip": ["4", 1]
        }},
        "8": { "class_type": "VAEDecode", "inputs": {
            "samples": ["3", 0], "vae": ["4", 2]
        }},
        "9": { "class_type": "SaveImage", "inputs": {
            "filename_prefix": "Spellcaster_ST", "images": ["8", 0]
        }}
    };
}

function buildImg2ImgWorkflow(imageName, prompt, negative, denoise, modelName) {
    return {
        "1": { "class_type": "LoadImage", "inputs": { "image": imageName }},
        "3": { "class_type": "KSampler", "inputs": {
            "seed": Math.floor(Math.random() * 2147483647),
            "steps": 25, "cfg": 7.0,
            "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "denoise": denoise, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]
        }},
        "4": { "class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": modelName
        }},
        "5": { "class_type": "VAEEncode", "inputs": {
            "pixels": ["1", 0], "vae": ["4", 2]
        }},
        "6": { "class_type": "CLIPTextEncode", "inputs": {
            "text": prompt, "clip": ["4", 1]
        }},
        "7": { "class_type": "CLIPTextEncode", "inputs": {
            "text": negative, "clip": ["4", 1]
        }},
        "8": { "class_type": "VAEDecode", "inputs": {
            "samples": ["3", 0], "vae": ["4", 2]
        }},
        "9": { "class_type": "SaveImage", "inputs": {
            "filename_prefix": "Spellcaster_ST_restyle", "images": ["8", 0]
        }}
    };
}

// ═══════════════════════════════════════════════════════════════════
//  Magic Studios — Character Pipeline for SillyTavern
// ═══════════════════════════════════════════════════════════════════

// In-memory asset tracker: { charName: { face_model, body_image, avatar_upload } }
const studioAssets = {};

/**
 * Build workflow: avatar → clean face model saved to ComfyUI.
 * Pipeline: LoadImage → ReActorBuildFaceModel → ReActorSaveFaceModel
 */
function buildCastWorkflow(avatarUploadName, faceModelName) {
    return {
        "1": { "class_type": "LoadImage", "inputs": { "image": avatarUploadName }},
        "2": { "class_type": "ReActorBuildFaceModel", "inputs": {
            "images": ["1", 0],
            "face_index": 0,
            "compute_method": "Mean",
            "face_model_name": faceModelName,
            "save_mode": true,
            "send_only": false,
        }},
        "3": { "class_type": "ReActorSaveFaceModel", "inputs": {
            "face_model": ["2", 0],
            "save_mode": "overwrite",
            "face_model_name": faceModelName,
            "select_face_index": 0,
        }},
        // Need a SaveImage to produce visible output for dispatch polling
        "9": { "class_type": "SaveImage", "inputs": {
            "filename_prefix": `Spellcaster_cast_${faceModelName}`,
            "images": ["1", 0],
        }},
    };
}

// ═══════════════════════════════════════════════════════════════════
//  Klein 2 Config — canonical Spellcaster Klein models
//  Mirrors KLEIN_MODELS in spellcaster_core/workflows.py
// ═══════════════════════════════════════════════════════════════════
const KLEIN_UNET = "A-Flux\\Flux2\\flux-2-klein-9b.safetensors";
const KLEIN_CLIP = "qwen_3_8b.safetensors";
const FLUX2_VAE  = "flux2-vae.safetensors";

/**
 * Build workflow: Klein 2 advanced image-to-image from the avatar.
 * Result: transparent PNG of the character's full body.
 *
 * Klein's ReferenceLatent preserves face/identity from the avatar while
 * inventing the body from the prompt — no ReActor face-swap needed.
 * Follows the pattern of `build_klein_img2img` in spellcaster_core.
 */
function buildBodyWorkflow(avatarImageName, bodyPrompt, _unusedModelName) {
    const seed = Math.floor(Math.random() * 2147483647);
    return {
        // ── Klein 9B + matching CLIP + flux2 VAE ──
        "1":  { "class_type": "UNETLoader", "inputs": {
            "unet_name": KLEIN_UNET, "weight_dtype": "default",
        }},
        "2":  { "class_type": "CLIPLoader", "inputs": {
            "clip_name": KLEIN_CLIP, "type": "flux2", "device": "default",
        }},
        "3":  { "class_type": "VAELoader", "inputs": { "vae_name": FLUX2_VAE }},
        // ── Conditioning (Klein uses zero-out for negative) ──
        "4":  { "class_type": "CLIPTextEncode", "inputs": {
            "text": `${bodyPrompt}, full body portrait, standing, looking at viewer, neutral solid background, detailed, sharp focus`,
            "clip": ["2", 0],
        }},
        "5":  { "class_type": "ConditioningZeroOut", "inputs": {
            "conditioning": ["4", 0],
        }},
        // ── Avatar reference image → 1MP latent ──
        "10": { "class_type": "LoadImage", "inputs": { "image": avatarImageName }},
        "11": { "class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": ["10", 0], "upscale_method": "lanczos", "megapixels": 1.0,
            "resolution_steps": 1,
        }},
        "12": { "class_type": "VAEEncode", "inputs": {
            "pixels": ["11", 0], "vae": ["3", 0],
        }},
        // ── ReferenceLatent wrapping — ties conditioning to the avatar ──
        "20": { "class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["4", 0], "latent": ["12", 0],
        }},
        "21": { "class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["5", 0], "latent": ["12", 0],
        }},
        // ── Custom sampler: CFGGuider + BasicScheduler + SamplerCustomAdvanced ──
        "30": { "class_type": "CFGGuider", "inputs": {
            "model": ["1", 0], "positive": ["20", 0], "negative": ["21", 0],
            "cfg": 1.0,
        }},
        "31": { "class_type": "KSamplerSelect", "inputs": { "sampler_name": "euler" }},
        // High denoise (~0.88) so the body is reinvented; face stays via RefLatent.
        "32": { "class_type": "BasicScheduler", "inputs": {
            "model": ["1", 0], "scheduler": "simple", "steps": 6, "denoise": 0.88,
        }},
        "33": { "class_type": "RandomNoise", "inputs": { "noise_seed": seed }},
        "40": { "class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["33", 0], "guider": ["30", 0], "sampler": ["31", 0],
            "sigmas": ["32", 0], "latent_image": ["12", 0],
        }},
        "50": { "class_type": "VAEDecode", "inputs": {
            "samples": ["40", 0], "vae": ["3", 0],
        }},
        // ── Remove background → transparent PNG ──
        "60": { "class_type": "Image Rembg (Remove Background)", "inputs": {
            "images": ["50", 0],
            "transparency": true,
            "model": "isnet-general-use",
            "post_processing": true,
            "only_mask": false,
            "alpha_matting": true,
            "alpha_matting_foreground_threshold": 240,
            "alpha_matting_background_threshold": 10,
            "alpha_matting_erode_size": 10,
            "background_color": "none",
        }},
        "9":  { "class_type": "SaveImage", "inputs": {
            "filename_prefix": "Spellcaster_body_klein",
            "images": ["60", 0],
        }},
    };
}

/**
 * Klein 2 text-to-image — the canonical Spellcaster txt2img engine
 * when Klein 9B / 4B is installed. Pure EmptyLatent path (no input
 * image), same CFGGuider + BasicScheduler + SamplerCustomAdvanced
 * spine as build_klein_img2img. Steps default to 4 per
 * architectures.py's flux2klein registration — Klein is distilled
 * to 4 steps by design. CFG=1.0 always; Klein is CFG-free.
 *
 * Dimensions must be mod-16. Klein's native training resolution is
 * 1024×1024; callers should round to the nearest mod-16 variant.
 */
function buildKleinTxt2ImgWorkflow(prompt, opts = {}) {
    const {
        width = 1024, height = 1024, steps = 4, guidance = 1.0,
    } = opts;
    const seed = Math.floor(Math.random() * 2147483647);
    return {
        "1":  { "class_type": "UNETLoader", "inputs": {
            "unet_name": KLEIN_UNET, "weight_dtype": "default",
        }},
        "2":  { "class_type": "CLIPLoader", "inputs": {
            "clip_name": KLEIN_CLIP, "type": "flux2", "device": "default",
        }},
        "3":  { "class_type": "VAELoader", "inputs": { "vae_name": FLUX2_VAE }},
        "4":  { "class_type": "CLIPTextEncode", "inputs": {
            "text": prompt, "clip": ["2", 0],
        }},
        "5":  { "class_type": "ConditioningZeroOut", "inputs": {
            "conditioning": ["4", 0],
        }},
        "10": { "class_type": "EmptyLatentImage", "inputs": {
            "width": width, "height": height, "batch_size": 1,
        }},
        "30": { "class_type": "CFGGuider", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
            "cfg": guidance,
        }},
        "31": { "class_type": "KSamplerSelect", "inputs": { "sampler_name": "euler" }},
        "32": { "class_type": "BasicScheduler", "inputs": {
            "model": ["1", 0], "scheduler": "simple",
            "steps": steps, "denoise": 1.0,
        }},
        "33": { "class_type": "RandomNoise", "inputs": { "noise_seed": seed }},
        "40": { "class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["33", 0], "guider": ["30", 0], "sampler": ["31", 0],
            "sigmas": ["32", 0], "latent_image": ["10", 0],
        }},
        "50": { "class_type": "VAEDecode", "inputs": {
            "samples": ["40", 0], "vae": ["3", 0],
        }},
        "9":  { "class_type": "SaveImage", "inputs": {
            "filename_prefix": "Spellcaster_klein_t2i",
            "images": ["50", 0],
        }},
    };
}

// Round to nearest mod-N. Klein + Flux need mod-16 dims; SDXL
// tolerates mod-8. Used by the endpoint-level dim normalizers.
function _roundMod(n, mod = 16, minV = 64) {
    const r = Math.max(minV, Math.round(n / mod) * mod);
    return r;
}

// ═══════════════════════════════════════════════════════════════════
//  Edit-by-prompt pipeline  (Klein 2 preferred, Flux Kontext fallback)
// ═══════════════════════════════════════════════════════════════════
//
// Semantic edits ("change the outfit to armour", "remove the hat")
// need a ReferenceLatent-style workflow that holds identity while
// the diffusion re-paints the instructed region. The Spellcaster
// canon is: Klein 2 > Flux Kontext > SDXL img2img. Klein is preferred
// because it's the user-maintained spine of every Spellcaster edit
// path; Kontext is the proven external fallback.

// Flux Kontext model file names — fixed by architectures.py:
const KONTEXT_UNET  = "Flux\\flux1-dev-kontext_fp8_scaled.safetensors";
const KONTEXT_CLIP1 = "clip_l.safetensors";
const KONTEXT_CLIP2 = "t5xxl_fp8_e4m3fn.safetensors";
const KONTEXT_VAE   = "ae.safetensors";

/**
 * Klein 2 edit — same spine as buildBodyWorkflow but:
 *   - no Image Rembg at the end (the user wants a flat edited image,
 *     not a transparent cutout)
 *   - denoise controlled by caller (default 0.55 for moderate edits)
 *   - positive prompt used verbatim (no body-specific boilerplate)
 * Identity holds via ReferenceLatent on the source image; the
 * instruction lives in the positive text encoding.
 */
function buildKleinEditWorkflow(imageName, instruction, opts = {}) {
    const { denoise = 0.55, steps = 6, guidance = 1.0 } = opts;
    const seed = Math.floor(Math.random() * 2147483647);
    return {
        "1":  { "class_type": "UNETLoader", "inputs": {
            "unet_name": KLEIN_UNET, "weight_dtype": "default",
        }},
        "2":  { "class_type": "CLIPLoader", "inputs": {
            "clip_name": KLEIN_CLIP, "type": "flux2", "device": "default",
        }},
        "3":  { "class_type": "VAELoader", "inputs": { "vae_name": FLUX2_VAE }},
        "4":  { "class_type": "CLIPTextEncode", "inputs": {
            "text": instruction, "clip": ["2", 0],
        }},
        "5":  { "class_type": "ConditioningZeroOut", "inputs": {
            "conditioning": ["4", 0],
        }},
        "10": { "class_type": "LoadImage", "inputs": { "image": imageName }},
        "11": { "class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": ["10", 0], "upscale_method": "lanczos", "megapixels": 1.0,
            "resolution_steps": 1,
        }},
        "12": { "class_type": "VAEEncode", "inputs": {
            "pixels": ["11", 0], "vae": ["3", 0],
        }},
        "20": { "class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["4", 0], "latent": ["12", 0],
        }},
        "21": { "class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["5", 0], "latent": ["12", 0],
        }},
        "30": { "class_type": "CFGGuider", "inputs": {
            "model": ["1", 0], "positive": ["20", 0], "negative": ["21", 0],
            "cfg": guidance,
        }},
        "31": { "class_type": "KSamplerSelect", "inputs": { "sampler_name": "euler" }},
        "32": { "class_type": "BasicScheduler", "inputs": {
            "model": ["1", 0], "scheduler": "simple",
            "steps": steps, "denoise": denoise,
        }},
        "33": { "class_type": "RandomNoise", "inputs": { "noise_seed": seed }},
        "40": { "class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["33", 0], "guider": ["30", 0], "sampler": ["31", 0],
            "sigmas": ["32", 0], "latent_image": ["12", 0],
        }},
        "50": { "class_type": "VAEDecode", "inputs": {
            "samples": ["40", 0], "vae": ["3", 0],
        }},
        "9":  { "class_type": "SaveImage", "inputs": {
            "filename_prefix": "Spellcaster_edit_klein",
            "images": ["50", 0],
        }},
    };
}

/**
 * Flux Kontext edit — fallback path for servers without Klein. Uses
 * the dedicated Kontext UNET + DualCLIP + FluxKontextImageScale
 * (auto-resizes the reference to one of Kontext's supported buckets)
 * + FluxGuidance. Node structure mirrors Flux Kontext's published
 * reference workflow.
 *
 * ReferenceLatent on the encoded reference image anchors identity;
 * the text instruction drives the edit. Keep defaults close to
 * architectures.py's flux_kontext entry (cfg=3.5, steps=25).
 */
function buildKontextEditWorkflow(imageName, instruction, opts = {}) {
    const { denoise = 1.0, steps = 25, guidance = 3.5 } = opts;
    const seed = Math.floor(Math.random() * 2147483647);
    return {
        "1":  { "class_type": "UNETLoader", "inputs": {
            "unet_name": KONTEXT_UNET, "weight_dtype": "default",
        }},
        "2":  { "class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": KONTEXT_CLIP1, "clip_name2": KONTEXT_CLIP2,
            "type": "flux", "device": "default",
        }},
        "3":  { "class_type": "VAELoader", "inputs": { "vae_name": KONTEXT_VAE }},
        "4":  { "class_type": "CLIPTextEncode", "inputs": {
            "text": instruction, "clip": ["2", 0],
        }},
        "5":  { "class_type": "FluxGuidance", "inputs": {
            "conditioning": ["4", 0], "guidance": guidance,
        }},
        "6":  { "class_type": "ConditioningZeroOut", "inputs": {
            "conditioning": ["4", 0],
        }},
        "10": { "class_type": "LoadImage", "inputs": { "image": imageName }},
        "11": { "class_type": "FluxKontextImageScale", "inputs": {
            "image": ["10", 0],
        }},
        "12": { "class_type": "VAEEncode", "inputs": {
            "pixels": ["11", 0], "vae": ["3", 0],
        }},
        "20": { "class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["5", 0], "latent": ["12", 0],
        }},
        "3s": { "class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "denoise": denoise,
            "model": ["1", 0],
            "positive": ["20", 0], "negative": ["6", 0],
            "latent_image": ["12", 0],
        }},
        "50": { "class_type": "VAEDecode", "inputs": {
            "samples": ["3s", 0], "vae": ["3", 0],
        }},
        "9":  { "class_type": "SaveImage", "inputs": {
            "filename_prefix": "Spellcaster_edit_kontext",
            "images": ["50", 0],
        }},
    };
}

/**
 * Pick the best edit engine based on the server's /object_info/UNETLoader.
 * Cached per COMFYUI_URL — invalidate by flipping _cachedEditEngine to null.
 *
 * Priority: klein9b > klein4b > kontext > sdxl (falls through to
 * buildImg2ImgWorkflow in the /edit handler).
 */
let _cachedEditEngine = null;
let _cachedEditEngineUrl = null;

async function detectEditEngine() {
    if (_cachedEditEngine && _cachedEditEngineUrl === COMFYUI_URL) {
        return _cachedEditEngine;
    }
    try {
        const r = await fetchJSON(`${COMFYUI_URL}/object_info/UNETLoader`);
        const names = r.data?.UNETLoader?.input?.required?.unet_name?.[0] || [];
        const names2 = r.data?.UNETLoader?.input?.required?.unet_name?.[1]?.options || [];
        const all = [...names, ...names2];
        const haveKlein9 = all.some(n => n.toLowerCase().includes("flux-2-klein-9b"));
        const haveKlein4 = all.some(n => n.toLowerCase().includes("flux-2-klein-4b") || n.toLowerCase().includes("flux-2-klein-base-4b"));
        const haveKontext = all.some(n => n.toLowerCase().includes("kontext"));
        let engine = "sdxl";
        if (haveKlein9 || haveKlein4) engine = "klein";
        else if (haveKontext) engine = "kontext";
        _cachedEditEngine = engine;
        _cachedEditEngineUrl = COMFYUI_URL;
        return engine;
    } catch {
        return "sdxl";
    }
}

/**
 * Build workflow: generate scene → composite characters → harmonize.
 * Takes a scene description and 1-3 character body images to place.
 */
function buildSceneCompositeWorkflow(scenePrompt, characters, modelName) {
    // characters: [{ bodyImageName, placement: {x, y, scale} }]
    const seed = Math.floor(Math.random() * 2147483647);
    const workflow = {
        // Generate scene background
        "4": { "class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": modelName,
        }},
        "5": { "class_type": "EmptyLatentImage", "inputs": {
            "width": 1280, "height": 720, "batch_size": 1,
        }},
        "6": { "class_type": "CLIPTextEncode", "inputs": {
            "text": `${scenePrompt}, cinematic scene, atmospheric, detailed environment, 8k`,
            "clip": ["4", 1],
        }},
        "7": { "class_type": "CLIPTextEncode", "inputs": {
            "text": "people, characters, faces, text, watermark, blurry, low quality",
            "clip": ["4", 1],
        }},
        "3": { "class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 25, "cfg": 7.0,
            "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "denoise": 1.0, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0],
        }},
        "8": { "class_type": "VAEDecode", "inputs": {
            "samples": ["3", 0], "vae": ["4", 2],
        }},
    };

    // Composite each character onto the scene
    // AILab_ImageCombiner clamps position_x/position_y to [0..100].
    // Cap at 4 bodies to keep spacing readable and to stay within range.
    const toComp = characters.slice(0, 4);
    const denom = Math.max(1, toComp.length - 1);
    const clamp01 = (v, fb) => {
        const n = Number.isFinite(v) ? v : fb;
        return Math.max(0, Math.min(100, Math.round(n)));
    };
    let currentImageRef = ["8", 0];  // Start with the scene
    toComp.forEach((char, i) => {
        const loadId = `${50 + i}`;
        const compId = `${60 + i}`;

        workflow[loadId] = { "class_type": "LoadImage", "inputs": {
            "image": char.bodyImageName,
        }};

        const evenX = toComp.length === 1 ? 50
            : toComp.length === 2 ? (i === 0 ? 35 : 65)
            : Math.round(15 + (i * 70) / denom);

        workflow[compId] = { "class_type": "AILab_ImageCombiner", "inputs": {
            "foreground": [loadId, 0],
            "background": currentImageRef,
            "mode": "normal",
            "foreground_opacity": 1.0,
            "foreground_scale": char.placement?.scale || 0.45,
            "position_x": clamp01(char.placement?.x, evenX),
            "position_y": clamp01(char.placement?.y, 70),
        }};

        currentImageRef = [compId, 0];
    });

    // ── Harmonization pass: Klein 2 low-denoise blend ──
    // Mirrors `build_klein_blend` in spellcaster_core/workflows.py.
    // Keeps AILab composition (alpha-aware) then runs it through Klein at
    // denoise 0.25 with ReferenceLatent so the characters integrate into the
    // scene's lighting/palette without being repainted. This is the "top-notch
    // layer blender" from Spellcaster.
    workflow["90"] = { "class_type": "UNETLoader", "inputs": {
        "unet_name": KLEIN_UNET, "weight_dtype": "default",
    }};
    workflow["91"] = { "class_type": "CLIPLoader", "inputs": {
        "clip_name": KLEIN_CLIP, "type": "flux2", "device": "default",
    }};
    workflow["92"] = { "class_type": "VAELoader", "inputs": {
        "vae_name": FLUX2_VAE,
    }};
    workflow["70"] = { "class_type": "ImageScaleToTotalPixels", "inputs": {
        "image": currentImageRef, "upscale_method": "lanczos", "megapixels": 1.0,
        "resolution_steps": 1,
    }};
    workflow["71"] = { "class_type": "VAEEncode", "inputs": {
        "pixels": ["70", 0], "vae": ["92", 0],
    }};
    workflow["75"] = { "class_type": "CLIPTextEncode", "inputs": {
        "text": `${scenePrompt}, people naturally in scene, matching lighting and shadows, cohesive composition, cinematic`,
        "clip": ["91", 0],
    }};
    workflow["76"] = { "class_type": "ConditioningZeroOut", "inputs": {
        "conditioning": ["75", 0],
    }};
    workflow["77"] = { "class_type": "ReferenceLatent", "inputs": {
        "conditioning": ["75", 0], "latent": ["71", 0],
    }};
    workflow["78"] = { "class_type": "ReferenceLatent", "inputs": {
        "conditioning": ["76", 0], "latent": ["71", 0],
    }};
    workflow["80"] = { "class_type": "CFGGuider", "inputs": {
        "model": ["90", 0], "positive": ["77", 0], "negative": ["78", 0],
        "cfg": 1.0,
    }};
    workflow["81"] = { "class_type": "KSamplerSelect", "inputs": { "sampler_name": "euler" }};
    workflow["82"] = { "class_type": "BasicScheduler", "inputs": {
        "model": ["90", 0], "scheduler": "simple", "steps": 6, "denoise": 0.25,
    }};
    workflow["83"] = { "class_type": "RandomNoise", "inputs": { "noise_seed": seed + 1 }};
    workflow["84"] = { "class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["83", 0], "guider": ["80", 0], "sampler": ["81", 0],
        "sigmas": ["82", 0], "latent_image": ["71", 0],
    }};
    workflow["85"] = { "class_type": "VAEDecode", "inputs": {
        "samples": ["84", 0], "vae": ["92", 0],
    }};
    workflow["9"] = { "class_type": "SaveImage", "inputs": {
        "filename_prefix": "Spellcaster_studio_klein",
        "images": ["85", 0],
    }};

    return workflow;
}

// ═══════════════════════════════════════════════════════════════════
//  WAN 2.2 I2V — canonical Spellcaster animation pipeline
// ═══════════════════════════════════════════════════════════════════
//
// This is the REAL animation path. It mirrors `build_wan_video` in
// spellcaster_core/workflows.py. DO NOT diverge — every WAN workflow
// in the Spellcaster app flows through the same two-pass high/low
// KSamplerAdvanced pattern. See CLAUDE.md §16 for the canon.
//
// The ST plugin fetches the WAN preset from the Guild
// (`GET /api/video_preset?engine=wan`), which in turn calls
// `spellcaster_core.video_presets.detect_wan_preset`. If the Guild
// isn't reachable the endpoint we fall back to
// `buildAnimationWorkflow` below (legacy noise-injection) so nothing
// regresses on installs without a Guild running.

// Fetch the WAN/LTX preset from the local Wizard Guild. Returns null
// on any failure — callers must handle the null path.
//
// The Guild lives on the same machine as the SillyTavern server
// plugin in the supported install (both run on the user's
// workstation), so localhost:7777 is the usual target. GUILD_URL is
// configurable via the `/settings` endpoint.
async function fetchVideoPreset(engine = "wan") {
    try {
        const comfyParam = encodeURIComponent(COMFYUI_URL);
        const url = `${GUILD_URL}/api/video_preset?engine=${engine}&comfy_url=${comfyParam}`;
        const r = await fetchJSON(url);
        if (r.status !== 200) return null;
        const p = r.data && r.data.preset;
        return p || null;
    } catch {
        return null;
    }
}

// Build the canonical WAN 2.2 I2V workflow. `preset` is the dict
// returned by fetchVideoPreset — see video_presets.py for the schema.
// Parameters beyond `preset` are animation-shape only (dims, length,
// fps) plus `turbo` and `pingpong` which are common caller overrides.
//
// When `endImage` is supplied the workflow switches to first-last-
// frame mode via WanFirstLastFrameToVideo — the animation
// interpolates from start to end. The end image uses its own
// CLIPVisionEncode for matched semantic conditioning.
function buildWanI2VWorkflow(avatarImage, prompt, preset, opts = {}) {
    const {
        width = 512, height = 512,       // mod-16 square for ST avatars
        length = 33,                      // 33 frames ≈ 2s @ 16fps
        fps = 16,
        turbo = true,                     // preset defaults are already turbo
        pingpong = true,                  // looping avatar is the common case
        negative_prompt = null,
        endImage = null,                  // optional FLF target frame
    } = opts;
    const seed = Math.floor(Math.random() * 2147483647);

    // Full-step override: the preset is tuned for turbo (6 steps,
    // cfg=1.0, second_step=3). When turbo=false, apply the canonical
    // full-step kwargs from wan_turbo_kwargs(turbo=False).
    const steps       = turbo ? preset.steps       : 30;
    const cfg         = turbo ? preset.cfg         : 3.5;
    const second_step = turbo ? preset.second_step : 15;
    const shift       = preset.shift != null ? preset.shift : 8.0;

    const isGgufClip = !!preset.clip_is_gguf;
    const isGgufHigh = (preset.high_model || "").toLowerCase().endsWith(".gguf");
    const isGgufLow  = (preset.low_model  || "").toLowerCase().endsWith(".gguf");

    const neg = negative_prompt || "static, frozen, blurry, low quality, distorted";

    const wf = {};

    // ── Model loaders ──
    wf["1"] = isGgufClip
        ? { class_type: "CLIPLoaderGGUF", inputs: { clip_name: preset.clip, type: "wan" }}
        : { class_type: "CLIPLoader",     inputs: { clip_name: preset.clip, type: "wan", device: "default" }};

    wf["2"] = isGgufHigh
        ? { class_type: "UnetLoaderGGUF", inputs: { unet_name: preset.high_model }}
        : { class_type: "UNETLoader",     inputs: { unet_name: preset.high_model, weight_dtype: "default" }};

    wf["3"] = isGgufLow
        ? { class_type: "UnetLoaderGGUF", inputs: { unet_name: preset.low_model }}
        : { class_type: "UNETLoader",     inputs: { unet_name: preset.low_model, weight_dtype: "default" }};

    wf["4"] = { class_type: "VAELoader", inputs: { vae_name: preset.vae }};

    // ── Conditioning ──
    wf["5"] = { class_type: "CLIPTextEncode", inputs: { text: prompt, clip: ["1", 0] }};
    wf["6"] = { class_type: "CLIPTextEncode", inputs: { text: neg,    clip: ["1", 0] }};

    // ── Start image: load + exact-fit resize (lanczos, center crop) ──
    // The canonical builder pre-resizes so WanImageToVideo doesn't make
    // its own center-crop decision and clip the source unexpectedly.
    wf["7"]  = { class_type: "LoadImage", inputs: { image: avatarImage }};
    wf["7r"] = { class_type: "ImageScale", inputs: {
        image: ["7", 0], upscale_method: "lanczos",
        width, height, crop: "center",
    }};

    // ── CLIPVision: encode the ORIGINAL image (more detail for
    // semantic conditioning). Canonical pattern — don't shortcut to
    // the scaled version.
    wf["7cv"] = { class_type: "CLIPVisionLoader", inputs: {
        clip_name: "clip_vision_h.safetensors",
    }};
    wf["7ce"] = { class_type: "CLIPVisionEncode", inputs: {
        clip_vision: ["7cv", 0], image: ["7", 0],
        crop: "none",
    }};

    // ── End image (first-last-frame mode) ──
    // Mirror the start-image pipeline: LoadImage → ImageScale → own
    // CLIPVisionEncode. Reuses the same CLIPVisionLoader to keep the
    // workflow tight.
    const useFLF = !!endImage;
    if (useFLF) {
        wf["7b"]  = { class_type: "LoadImage", inputs: { image: endImage }};
        wf["7br"] = { class_type: "ImageScale", inputs: {
            image: ["7b", 0], upscale_method: "lanczos",
            width, height, crop: "center",
        }};
        wf["7be"] = { class_type: "CLIPVisionEncode", inputs: {
            clip_vision: ["7cv", 0], image: ["7b", 0],
            crop: "none",
        }};
    }

    // ── Acceleration LoRAs (turbo only) — LightX2V/Lightning I2V pair
    // stored on the preset. Strength 1.5 is the calibrated default.
    let highRef = ["2", 0];
    let lowRef  = ["3", 0];
    if (turbo) {
        const str = preset.accel_strength || 1.5;
        if (preset.high_accel_lora) {
            wf["100"] = { class_type: "LoraLoaderModelOnly", inputs: {
                model: highRef, lora_name: preset.high_accel_lora,
                strength_model: str,
            }};
            highRef = ["100", 0];
        }
        if (preset.low_accel_lora) {
            wf["120"] = { class_type: "LoraLoaderModelOnly", inputs: {
                model: lowRef, lora_name: preset.low_accel_lora,
                strength_model: str,
            }};
            lowRef = ["120", 0];
        }
    }

    // ── ModelSamplingSD3 shift on both branches ──
    if (shift && shift > 0) {
        wf["30"] = { class_type: "ModelSamplingSD3", inputs: { model: highRef, shift }};
        wf["31"] = { class_type: "ModelSamplingSD3", inputs: { model: lowRef,  shift }};
        highRef = ["30", 0];
        lowRef  = ["31", 0];
    }

    // ── Video conditioning: WanImageToVideo (I2V) or
    //    WanFirstLastFrameToVideo (FLF with end image). Both output
    //    [positive, negative, latent].
    if (useFLF) {
        wf["40"] = { class_type: "WanFirstLastFrameToVideo", inputs: {
            positive: ["5", 0],
            negative: ["6", 0],
            vae:      ["4", 0],
            width, height, length, batch_size: 1,
            clip_vision_start_image: ["7ce", 0],
            clip_vision_end_image:   ["7be", 0],
            start_image:             ["7r", 0],
            end_image:               ["7br", 0],
        }};
    } else {
        wf["40"] = { class_type: "WanImageToVideo", inputs: {
            positive:            ["5", 0],
            negative:            ["6", 0],
            vae:                 ["4", 0],
            width, height, length, batch_size: 1,
            clip_vision_output:  ["7ce", 0],
            start_image:         ["7r", 0],
        }};
    }

    // ── Two-pass KSamplerAdvanced (HIGH frames 0..second_step,
    //    LOW frames second_step..end). The LOW pass disables noise
    //    injection and forces cfg=1 — it's a refinement pass,
    //    matching the canonical pattern exactly.
    wf["50"] = { class_type: "KSamplerAdvanced", inputs: {
        model: highRef,
        positive: ["40", 0], negative: ["40", 1],
        latent_image: ["40", 2],
        add_noise: "enable", noise_seed: seed,
        steps, cfg, sampler_name: "euler", scheduler: "simple",
        start_at_step: 0, end_at_step: second_step,
        return_with_leftover_noise: "enable",
    }};
    wf["51"] = { class_type: "KSamplerAdvanced", inputs: {
        model: lowRef,
        positive: ["40", 0], negative: ["40", 1],
        latent_image: ["50", 0],
        add_noise: "disable", noise_seed: 0,
        steps, cfg: 1, sampler_name: "euler", scheduler: "simple",
        start_at_step: second_step, end_at_step: 10000,
        return_with_leftover_noise: "disable",
    }};

    // ── Decode + encode as GIF ──
    // GIF (not MP4) because the existing SillyTavern client renders
    // videos via the markdown image syntax `![animated](data:image/gif;...)`
    // — MP4 would need a <video> tag the client doesn't emit. Keep
    // MP4 as a future opt-in.
    wf["60"] = { class_type: "VAEDecode", inputs: {
        samples: ["51", 0], vae: ["4", 0],
    }};
    wf["70"] = { class_type: "VHS_VideoCombine", inputs: {
        images: ["60", 0], frame_rate: fps,
        loop_count: 0, filename_prefix: "Spellcaster_ST_wan_i2v",
        format: "image/gif", pingpong: !!pingpong,
        save_output: true,
    }};

    return wf;
}

// ═══════════════════════════════════════════════════════════════════
//  LTX-2.3 I2V — canonical Spellcaster alternative to WAN
// ═══════════════════════════════════════════════════════════════════
//
// LTX-2 is ~4× faster than WAN full-step and comparable quality for
// portrait animation. Mirrors build_ltx_video in spellcaster_core.
// Key canon points (CLAUDE.md §16.3):
//   • LTXVChunkFeedForward(chunks=4) wraps the UNET for VRAM
//   • LTXVApplySTG on layers "14, 19" before the sampler
//   • Default negative prompt blocks LTX's subtitle-burn-in artifact
//   • Distilled mode overrides steps/cfg/stg/rescale + injects the
//     distilled LoRA; full mode keeps preset defaults (30/4.0/1.0/0.7)

function buildLtxI2VWorkflow(avatarImage, prompt, preset, opts = {}) {
    const {
        width = 768, height = 512, length = 25, fps = 24,
        distilled = true,            // turbo-equivalent — 8 steps, cfg 1.0
        i2v_strength = 0.9,
        pingpong = true,
        negative_prompt = null,
    } = opts;
    const seed = Math.floor(Math.random() * 2147483647);

    // Distilled overrides — mirror build_ltx_video exactly
    const steps   = distilled ? 8   : (preset.steps   ?? 30);
    const cfg     = distilled ? 1.0 : (preset.cfg     ?? 4.0);
    const stg     = distilled ? 0.0 : (preset.stg     ?? 1.0);
    const rescale = distilled ? 0.0 : (preset.rescale ?? 0.7);

    // Subtitle-burn-in blocker — LTX training corpus includes
    // subtitled video; without this the model reproduces them.
    const neg = negative_prompt || (
        "text, subtitles, captions, watermark, logo, timestamp, UI, "
        + "interface, closed captions, overlay, written letters, typography"
    );

    const wf = {};
    const isGgufUnet = !!preset.unet_is_gguf ||
        (preset.unet || "").toLowerCase().endsWith(".gguf");

    wf["1"] = isGgufUnet
        ? { class_type: "UnetLoaderGGUF", inputs: { unet_name: preset.unet }}
        : { class_type: "UNETLoader",     inputs: { unet_name: preset.unet, weight_dtype: "default" }};

    let modelRef = ["1", 0];
    if (distilled && preset.distilled_lora) {
        wf["1b"] = { class_type: "LoraLoaderModelOnly", inputs: {
            model: modelRef, lora_name: preset.distilled_lora,
            strength_model: 1.0,
        }};
        modelRef = ["1b", 0];
    }

    // VRAM chunking + Spatial-Temporal Guidance. Defaults mirror the
    // node's declared schema — dim_threshold 4096 is the published
    // sweet spot that only triggers chunking on high-dim activations.
    wf["2"] = { class_type: "LTXVChunkFeedForward", inputs: {
        model: modelRef, chunks: 4, dim_threshold: 4096,
    }};
    wf["3"] = { class_type: "LTXVApplySTG", inputs: {
        model: ["2", 0], block_indices: "14, 19",
    }};

    // Text encoder (Gemma-3 via LTX's custom loader) + embeddings connector.
    // The node input names differ from the canonical preset keys:
    //   preset.text_encoder       → LTXAVTextEncoderLoader.text_encoder
    //   preset.embeddings_connector → LTXAVTextEncoderLoader.ckpt_name
    wf["4"] = { class_type: "LTXAVTextEncoderLoader", inputs: {
        text_encoder: preset.text_encoder,
        ckpt_name: preset.embeddings_connector,
        device: "default",
    }};

    wf["10"] = { class_type: "CLIPTextEncode", inputs: {
        text: prompt, clip: ["4", 0],
    }};
    wf["11"] = { class_type: "CLIPTextEncode", inputs: {
        text: neg, clip: ["4", 0],
    }};

    wf["5"] = { class_type: "VAELoader", inputs: { vae_name: preset.vae }};

    wf["12"] = { class_type: "LTXVConditioning", inputs: {
        positive: ["10", 0], negative: ["11", 0],
        frame_rate: fps,
    }};

    // LTXVScheduler wants the full shift/stretch/terminal set — use
    // the node's declared defaults so output quality matches ComfyUI's
    // reference LTX workflow.
    wf["15"] = { class_type: "LTXVScheduler", inputs: {
        steps, max_shift: 2.05, base_shift: 0.95,
        stretch: true, terminal: 0.1,
    }};
    wf["16"] = { class_type: "STGGuider", inputs: {
        model: ["3", 0],
        positive: ["12", 0], negative: ["12", 1],
        cfg, stg, rescale,
    }};
    wf["17"] = { class_type: "KSamplerSelect", inputs: { sampler_name: "euler" }};
    wf["18"] = { class_type: "RandomNoise", inputs: { noise_seed: seed }};

    // Start image — I2V conditioning
    wf["19"] = { class_type: "LoadImage", inputs: { image: avatarImage }};
    wf["20"] = { class_type: "LTXVBaseSampler", inputs: {
        model: ["3", 0], vae: ["5", 0], guider: ["16", 0],
        sampler: ["17", 0], sigmas: ["15", 0], noise: ["18", 0],
        width, height, num_frames: length,
        optional_cond_images: ["19", 0],
        optional_cond_indices: "0",
        strength: i2v_strength,
    }};

    // Spatio-temporal tiled VAE decode — LTX's memory-efficient path.
    // Input name is `latents` (not `samples`); tile params + overlap
    // + last_frame_fix all required after ComfyUI's recent LTX node
    // refactor. Defaults mirror the node's declared defaults.
    wf["40"] = { class_type: "LTXVSpatioTemporalTiledVAEDecode", inputs: {
        vae: ["5", 0], latents: ["20", 0],
        spatial_tiles: 4, spatial_overlap: 1,
        temporal_tile_length: 16, temporal_overlap: 1,
        last_frame_fix: false,
        working_device: "auto", working_dtype: "auto",
    }};

    // GIF output so the existing markdown client renders inline
    wf["50"] = { class_type: "VHS_VideoCombine", inputs: {
        images: ["40", 0], frame_rate: fps,
        loop_count: 0, filename_prefix: "Spellcaster_ST_ltx_i2v",
        format: "image/gif", pingpong: !!pingpong,
        save_output: true,
    }};

    return wf;
}

function buildAnimationWorkflow(imageName, prompt, numFrames, modelName) {
    // FALLBACK path — img2img with low-denoise noise injection on a
    // latent batch. This was the ST plugin's original animation
    // implementation; it's NOT real video, just 8 slightly-different
    // frames of the same image. Kept as a safety net for users whose
    // ComfyUI server lacks WAN / LTX / Kijai nodes (the animate
    // endpoint checks the WAN preset first and only lands here on
    // preset miss). Do not route new callers through this.
    //
    // `modelName` is the SDXL/SD-1.5 checkpoint chosen by
    // detectBestModel(). The previous build hardcoded a NoobAI
    // filename that didn't exist on most servers — fallback 500'd
    // before the first frame. Accept the caller's detected model.
    const seed = Math.floor(Math.random() * 2147483647);
    const ckpt = modelName || _cachedModel;
    if (!ckpt) {
        throw new Error('No checkpoint available for animation fallback — install WAN / LTX via the Spellcaster installer for real video.');
    }
    return {
        "1": { "class_type": "LoadImage", "inputs": { "image": imageName }},
        "4": { "class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": ckpt,
        }},
        "5": { "class_type": "VAEEncode", "inputs": {
            "pixels": ["1", 0], "vae": ["4", 2]
        }},
        "6": { "class_type": "CLIPTextEncode", "inputs": {
            "text": `${prompt}, subtle movement, cinematic, animated, high quality`,
            "clip": ["4", 1]
        }},
        "7": { "class_type": "CLIPTextEncode", "inputs": {
            "text": "static, frozen, still, blurry, low quality, deformed",
            "clip": ["4", 1]
        }},
        "10": { "class_type": "RepeatLatentBatch", "inputs": {
            "samples": ["5", 0], "amount": numFrames
        }},
        // `normalize` became required on a recent ComfyUI node refresh.
        // Default "false" matches the node's declared default and
        // preserves the original noise-injection behaviour.
        "11": { "class_type": "InjectLatentNoise+", "inputs": {
            "latent": ["10", 0], "noise_seed": seed, "noise_strength": 0.12,
            "normalize": "false",
        }},
        "3": { "class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 8, "cfg": 5.0,
            "sampler_name": "euler", "scheduler": "normal",
            "denoise": 0.15, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["11", 0]
        }},
        "8": { "class_type": "VAEDecode", "inputs": {
            "samples": ["3", 0], "vae": ["4", 2]
        }},
        "20": { "class_type": "VHS_VideoCombine", "inputs": {
            "images": ["8", 0], "frame_rate": 8.0,
            "loop_count": 0, "filename_prefix": "Spellcaster_ST_anim",
            "format": "image/gif", "pingpong": true,
            "save_output": true
        }}
    };
}

function exit() {
    console.log('[Spellcaster] Server plugin unloaded.');
}

const info = {
    id: 'spellcaster',
    name: 'Spellcaster',
    description: 'ComfyUI integration — living scenes, character restyling, autonomous image generation',
};

export { info, init, exit };
