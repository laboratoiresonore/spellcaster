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

/**
 * Upload an image to ComfyUI's input folder.
 */
async function uploadToComfyUI(imageBuffer, filename) {
    const boundary = '----SpellcasterUpload' + Date.now();
    const body = Buffer.concat([
        Buffer.from(
            `--${boundary}\r\n` +
            `Content-Disposition: form-data; name="image"; filename="${filename}"\r\n` +
            `Content-Type: image/png\r\n\r\n`
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
            const model = await detectBestModel();
            if (!model) return res.status(500).json({ error: 'No checkpoint models found on ComfyUI' });
            const prompt = `${description}, cinematic scene, atmospheric, professional photography, 8k, detailed environment`;
            const negative = 'people, characters, faces, text, watermark, blurry, low quality';
            const workflow = buildTxt2ImgWorkflow(
                prompt, negative,
                width || 1280, height || 720,
                Math.floor(Math.random() * 2147483647),
                model
            );
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

            const model = await detectBestModel();
            if (!model) return res.status(500).json({ error: 'No checkpoint models found on ComfyUI' });

            // Upload to ComfyUI
            const imgBuf = Buffer.from(image_base64, 'base64');
            const uploadName = `spellcaster_restyle_${Date.now()}.png`;
            await uploadToComfyUI(imgBuf, uploadName);

            const workflow = buildImg2ImgWorkflow(
                uploadName,
                prompt || 'photorealistic portrait, professional photography, detailed',
                'cartoon, anime, drawing, sketch, blurry, low quality',
                denoise || 0.55,
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
    router.post('/animate', async (req, res) => {
        try {
            const { image_base64, prompt, length } = req.body;
            if (!image_base64) return res.status(400).json({ error: 'image_base64 required' });

            const imgBuf = Buffer.from(image_base64, 'base64');
            const uploadName = `spellcaster_anim_${Date.now()}.png`;
            await uploadToComfyUI(imgBuf, uploadName);

            // Build animation workflow (img2img batch with noise injection → GIF)
            const workflow = buildAnimationWorkflow(
                uploadName,
                prompt || 'subtle animation, gentle movement',
                length || 8
            );
            const result = await dispatchWorkflow(workflow, 300000);
            res.json({
                status: 'ok',
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
            const model = await detectBestModel();
            if (!model) return res.status(500).json({ error: 'No checkpoint models found on ComfyUI' });
            const prompt = `${description}, portrait photograph, 85mm lens, shallow depth of field, studio lighting, professional headshot, detailed face, 8k`;
            const negative = 'blurry, distorted, deformed, low quality, cartoon, watermark';
            const workflow = buildTxt2ImgWorkflow(
                prompt, negative,
                width || 400, height || 600,
                Math.floor(Math.random() * 2147483647),
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

/**
 * Build workflow: txt2img body → face swap (using avatar image) → remove background.
 * Result: transparent PNG of the character's full body.
 * Uses source_image (the avatar) directly for face swap — no saved face model needed.
 */
function buildBodyWorkflow(avatarImageName, bodyPrompt, modelName) {
    const seed = Math.floor(Math.random() * 2147483647);
    return {
        // Generate full body from text
        "4": { "class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": modelName,
        }},
        "5": { "class_type": "EmptyLatentImage", "inputs": {
            "width": 512, "height": 768, "batch_size": 1,
        }},
        "6": { "class_type": "CLIPTextEncode", "inputs": {
            "text": `${bodyPrompt}, full body, standing, looking at viewer, high quality, detailed, 8k`,
            "clip": ["4", 1],
        }},
        "7": { "class_type": "CLIPTextEncode", "inputs": {
            "text": "blurry, low quality, distorted, deformed, watermark, text, cropped, partial body",
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
        // Face swap using avatar image directly as source
        "10": { "class_type": "LoadImage", "inputs": {
            "image": avatarImageName,
        }},
        "20": { "class_type": "ReActorOptions", "inputs": {
            "input_faces_order": "left-right",
            "input_faces_index": "0",
            "detect_gender_input": "no",
            "source_faces_order": "left-right",
            "source_faces_index": "0",
            "detect_gender_source": "no",
            "console_log_level": 0,
            "restore_swapped_only": true,
        }},
        "21": { "class_type": "ReActorFaceBoost", "inputs": {
            "enabled": true,
            "boost_model": "GFPGANv1.4.pth",
            "interpolation": "Bicubic",
            "visibility": 1.0,
            "codeformer_weight": 0.7,
            "restore_with_main_after": false,
        }},
        "25": { "class_type": "ReActorFaceSwapOpt", "inputs": {
            "enabled": true,
            "input_image": ["8", 0],
            "source_image": ["10", 0],
            "swap_model": "reswapper_256.onnx",
            "facedetection": "retinaface_resnet50",
            "face_restore_model": "codeformer-v0.1.0.pth",
            "face_restore_visibility": 1.0,
            "codeformer_weight": 0.6,
            "options": ["20", 0],
            "face_boost": ["21", 0],
        }},
        // Remove background → transparent PNG
        "30": { "class_type": "Image Rembg (Remove Background)", "inputs": {
            "images": ["25", 0],
            "transparency": true,
            "model": "isnet-general-use",
            "post_processing": false,
            "only_mask": false,
            "alpha_matting": false,
            "alpha_matting_foreground_threshold": 240,
            "alpha_matting_background_threshold": 10,
            "alpha_matting_erode_size": 10,
            "background_color": "none",
        }},
        "9": { "class_type": "SaveImage", "inputs": {
            "filename_prefix": "Spellcaster_body",
            "images": ["30", 0],
        }},
    };
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
    let currentImageRef = ["8", 0];  // Start with the scene
    characters.forEach((char, i) => {
        const loadId = `${50 + i}`;
        const compId = `${60 + i}`;

        workflow[loadId] = { "class_type": "LoadImage", "inputs": {
            "image": char.bodyImageName,
        }};

        workflow[compId] = { "class_type": "AILab_ImageCombiner", "inputs": {
            "foreground": [loadId, 0],
            "background": currentImageRef,
            "mode": "normal",
            "foreground_opacity": 1.0,
            "foreground_scale": char.placement?.scale || 0.45,
            "position_x": char.placement?.x || (30 + i * 30),
            "position_y": char.placement?.y || 70,
        }};

        currentImageRef = [compId, 0];
    });

    // Harmonization pass — low-denoise img2img to blend characters into scene
    workflow["70"] = { "class_type": "VAEEncode", "inputs": {
        "pixels": currentImageRef, "vae": ["4", 2],
    }};
    workflow["71"] = { "class_type": "CLIPTextEncode", "inputs": {
        "text": `${scenePrompt}, people naturally in scene, matching lighting and shadows, cohesive composition, cinematic, 8k`,
        "clip": ["4", 1],
    }};
    workflow["72"] = { "class_type": "KSampler", "inputs": {
        "seed": seed + 1, "steps": 20, "cfg": 5.0,
        "sampler_name": "dpmpp_2m", "scheduler": "karras",
        "denoise": 0.25,   // Low denoise — preserve composition, blend lighting
        "model": ["4", 0],
        "positive": ["71", 0], "negative": ["7", 0],
        "latent_image": ["70", 0],
    }};
    workflow["73"] = { "class_type": "VAEDecode", "inputs": {
        "samples": ["72", 0], "vae": ["4", 2],
    }};
    workflow["9"] = { "class_type": "SaveImage", "inputs": {
        "filename_prefix": "Spellcaster_studio_scene",
        "images": ["73", 0],
    }};

    return workflow;
}

function buildAnimationWorkflow(imageName, prompt, numFrames) {
    // Img2img with low denoise on each frame variation — generates a short
    // animated GIF by creating subtle variations of the source image.
    // This is a lightweight animation approach that works with any SD/SDXL
    // checkpoint (no LTX/WAN models required).
    const seed = Math.floor(Math.random() * 2147483647);
    return {
        "1": { "class_type": "LoadImage", "inputs": { "image": imageName }},
        "4": { "class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": _cachedModel || "SDXL\\NoobAI-XL-v1.1.safetensors"
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
        "11": { "class_type": "InjectLatentNoise+", "inputs": {
            "latent": ["10", 0], "noise_seed": seed, "noise_strength": 0.12
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
