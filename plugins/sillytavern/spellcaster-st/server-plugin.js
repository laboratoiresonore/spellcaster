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

// Max base64 body size (~20 MB decoded). 20 * 1024 * 1024 * 4/3 ≈ 27.97 MB chars.
const MAX_B64_CHARS = 28 * 1024 * 1024;
const MAX_FETCH_BYTES = 50 * 1024 * 1024;

// Reject a base64 body that would decode to more than MAX_B64_CHARS.
// Returns an error-dict on reject, null on pass. Caller: `if (err) return res.status(413).json(err);`
function _rejectOversizedB64(b64) {
    if (typeof b64 !== 'string') return { error: 'image_base64 must be a string' };
    if (b64.length > MAX_B64_CHARS) {
        return { error: `image_base64 too large (${b64.length} chars, max ${MAX_B64_CHARS})` };
    }
    return null;
}

// Only http/https; block loopback metadata endpoints and obvious internal
// footguns. Returns null on pass, error-dict on reject.
function _rejectUnsafeUrl(u) {
    if (typeof u !== 'string' || !u) return { error: 'url required' };
    let parsed;
    try { parsed = new URL(u); } catch { return { error: 'malformed url' }; }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return { error: `url scheme not allowed: ${parsed.protocol}` };
    }
    const host = parsed.hostname.toLowerCase();
    // Block AWS/GCP/Azure instance metadata service hostnames.
    if (host === '169.254.169.254' || host === 'metadata.google.internal'
        || host === 'metadata' || host.endsWith('.internal')) {
        return { error: 'url host blocked' };
    }
    return null;
}

// Accept most filenames ST users will produce (Unicode letters/digits,
// spaces, common punctuation) while blocking path separators, traversal
// tokens, and control chars. Callers should still pass the result
// through path.basename and/or a resolve-under-root check.
function _safeNameOrNull(name, { maxLen = 96 } = {}) {
    if (typeof name !== 'string') return null;
    const trimmed = name.trim();
    if (!trimmed || trimmed.length > maxLen) return null;
    if (trimmed === '.' || trimmed === '..') return null;
    // Reject control chars, path separators, drive markers, wildcards.
    if (/[\x00-\x1f\x7f/\\:*?"<>|]/.test(trimmed)) return null;
    if (trimmed.includes('..')) return null;
    return trimmed;
}

/**
 * Resolve ST's characters directory. Tries (in order):
 *   1. SPELLCASTER_ST_CHARACTERS_DIR env var (absolute path) — override
 *      for users running ST under Docker / custom data-user / non-
 *      default deploys. Without this, bespoke installs hit every
 *      /save-* endpoint's generic "Cannot find characters directory"
 *      error with nothing actionable.
 *   2. ST's canonical `data/default-user/characters/` (post-1.11 layout)
 *   3. ST's legacy `public/characters/` (pre-1.11 layout)
 */
function resolveCharactersDir() {
    const envOverride = process.env.SPELLCASTER_ST_CHARACTERS_DIR;
    if (envOverride && path.isAbsolute(envOverride) && fs.existsSync(envOverride)) {
        return envOverride;
    }
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
 * Also honours SPELLCASTER_ST_BACKGROUNDS_DIR as an override.
 */
function autoDetectBgDir() {
    if (BG_DIR) return;
    const envOverride = process.env.SPELLCASTER_ST_BACKGROUNDS_DIR;
    if (envOverride && path.isAbsolute(envOverride) && fs.existsSync(envOverride)) {
        BG_DIR = envOverride;
        return;
    }
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
function fetchBytes(url, { maxBytes = MAX_FETCH_BYTES, timeoutMs = 30000 } = {}) {
    return new Promise((resolve, reject) => {
        const mod = url.startsWith('https') ? https : http;
        const req = mod.get(url, (res) => {
            const chunks = [];
            let total = 0;
            res.on('data', chunk => {
                total += chunk.length;
                if (total > maxBytes) {
                    req.destroy(new Error(`response exceeded ${maxBytes} bytes`));
                    return;
                }
                chunks.push(chunk);
            });
            res.on('end', () => resolve(Buffer.concat(chunks)));
            res.on('error', reject);
        });
        req.on('error', reject);
        req.setTimeout(timeoutMs, () => req.destroy(new Error(`fetchBytes timeout after ${timeoutMs}ms`)));
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
            const raw = String(req.body.comfyui_url).replace(/\/+$/, '');
            const bad = _rejectUnsafeUrl(raw);
            if (bad) return res.status(400).json({ ...bad, field: 'comfyui_url' });
            if (raw !== COMFYUI_URL) {
                COMFYUI_URL = raw;
                _cachedModel = null;
                _cachedEditEngine = null;
            }
        }
        if (req.body.guild_url) {
            const raw = String(req.body.guild_url).replace(/\/+$/, '');
            const bad = _rejectUnsafeUrl(raw);
            if (bad) return res.status(400).json({ ...bad, field: 'guild_url' });
            GUILD_URL = raw;
        }
        if (req.body.backgrounds_dir) {
            const d = String(req.body.backgrounds_dir);
            if (!path.isAbsolute(d)) return res.status(400).json({ error: 'backgrounds_dir must be absolute' });
            BG_DIR = d;
        }
        autoDetectBgDir();
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
            const dataUrl = String(req.body.image_data_url);
            const comma = dataUrl.indexOf(',');
            body_b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
            const bad = _rejectOversizedB64(body_b64);
            if (bad) return res.status(413).json(bad);
        } else if (req.body.image_url) {
            const bad = _rejectUnsafeUrl(req.body.image_url);
            if (bad) return res.status(400).json({ ...bad, field: 'image_url' });
            try {
                const bin = await fetchBytes(req.body.image_url);
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
                _capPrompt(prompt) || 'a beautiful scene',
                _capPrompt(negative) || 'blurry, low quality',
                _roundMod(width || 1024, 8, 256),
                _roundMod(height || 768, 8, 256),
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
            const desc = _capPrompt(description);
            // Klein scene prompts are natural language; no quality-tag
            // boilerplate (Klein penalises it). SDXL keeps the tags so
            // ordinary checkpoints still produce cinematic output.
            const kleinPrompt = `${desc}, cinematic scene, atmospheric, detailed environment`;
            const sdxlPrompt  = `${desc}, cinematic scene, atmospheric, professional photography, 8k, detailed environment`;
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
                    _roundMod(width || 1280, 8, 256),
                    _roundMod(height || 720, 8, 256),
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
            const bad = _rejectOversizedB64(image_base64);
            if (bad) return res.status(413).json(bad);

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
            const effectivePrompt = _capPrompt(prompt) ||
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
            const bad = _rejectOversizedB64(image_base64);
            if (bad) return res.status(413).json(bad);
            const instr = _capPrompt(instruction);
            // Denoise in [0, 1] — ComfyUI rejects values outside this
            // but we catch early so the caller gets a clean 400.
            const denoiseNum = denoise == null ? undefined : Number(denoise);
            if (denoiseNum !== undefined && (!Number.isFinite(denoiseNum)
                || denoiseNum < 0 || denoiseNum > 1)) {
                return res.status(400).json({ error: 'denoise must be in [0, 1]' });
            }

            const imgBuf = Buffer.from(image_base64, 'base64');
            const uploadName = `spellcaster_edit_${Date.now()}.png`;
            await uploadToComfyUI(imgBuf, uploadName);

            const engine = (forceEngine && ["klein","kontext","sdxl"].includes(forceEngine))
                ? forceEngine : await detectEditEngine();
            let workflow = null;
            let usedEngine = engine;
            if (engine === "klein") {
                workflow = buildKleinEditWorkflow(uploadName, instr, {
                    denoise: denoiseNum || 0.55,
                });
            } else if (engine === "kontext") {
                workflow = buildKontextEditWorkflow(uploadName, instr, {
                    denoise: denoiseNum || 1.0,
                });
            } else {
                const model = await detectBestModel();
                if (!model) return res.status(500).json({
                    error: 'No edit engine available on ComfyUI',
                });
                usedEngine = "sdxl";
                workflow = buildImg2ImgWorkflow(
                    uploadName, instr,
                    'blurry, low quality, distorted',
                    denoiseNum || 0.55, model,
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
            const bad = _rejectOversizedB64(image_base64);
            if (bad) return res.status(413).json(bad);
            const safeName = _safeNameOrNull(path.basename(String(avatar_filename)));
            if (!safeName) {
                return res.status(400).json({ error: 'avatar_filename contains unsafe characters' });
            }

            const charDir = resolveCharactersDir();
            if (!charDir) {
                return res.status(500).json({ error: 'Cannot find SillyTavern characters directory' });
            }

            const avatarPath = path.join(charDir, safeName);
            if (!fs.existsSync(avatarPath)) {
                return res.status(404).json({ error: `Avatar not found: ${safeName}` });
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
            const safeName = _safeNameOrNull(path.basename(String(avatar_filename)));
            if (!safeName) {
                return res.status(400).json({ error: 'avatar_filename contains unsafe characters' });
            }

            const charDir = resolveCharactersDir();
            if (!charDir) {
                return res.status(500).json({ error: 'Cannot find SillyTavern characters directory' });
            }

            const avatarPath = path.join(charDir, safeName);
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
    // Per CLAUDE.md §16.4: the WAN + LTX canon lives ONLY in
    // spellcaster_core.video_presets + spellcaster_core.workflows (both
    // Python). SillyTavern is a JS plugin, so it CANNOT import them —
    // instead it POSTs to the Wizard Guild's /api/video/shots endpoints
    // which wrap the canon server-side. The Guild owns preset detection,
    // VAE pairing, turbo formula, subtitle-burn-in negative, and model
    // selection; ST just sends a prompt + reference image.
    //
    // Fallback: if the Guild is unreachable (or the caller passes
    // engine="legacy"), fall back to the local SDXL noise-injection
    // animation — NOT real video, just frame-variation jitter, but
    // useful as a last-resort preview.
    //
    // Client response shape is unchanged — { status, videos:[], images:[] }.
    router.post('/animate', async (req, res) => {
        try {
            const { image_base64, prompt, length, turbo, engine } = req.body || {};
            if (!image_base64) return res.status(400).json({ error: 'image_base64 required' });
            const b64Bad = _rejectOversizedB64(image_base64);
            if (b64Bad) return res.status(413).json(b64Bad);

            const wantLegacy = engine === "legacy";
            const effectivePrompt = String(prompt || 'subtle breathing, gentle movement, living portrait').slice(0, 2000);

            // Try the canonical Guild path first.
            if (!wantLegacy) {
                try {
                    const preset = (engine === "ltx")
                        ? 'ltx_distilled'
                        : (turbo ? 'wan22_i2v_lightning' : 'wan22_i2v_hq');
                    const guildResult = await _animateViaGuild({
                        image_base64,
                        prompt: effectivePrompt,
                        preset,
                    });
                    return res.json({
                        status: 'ok',
                        engine: guildResult.engine,
                        shot_id: guildResult.shot_id,
                        videos: guildResult.videos,
                        images: [],
                    });
                } catch (guildErr) {
                    // Guild offline or rejected — fall through to legacy.
                    console.warn('[Spellcaster] /animate Guild path failed, falling back to SDXL:', guildErr.message);
                }
            }

            // Legacy SDXL noise-injection fallback.
            const imgBuf = Buffer.from(image_base64, 'base64');
            const uploadName = `spellcaster_anim_${Date.now()}.png`;
            await uploadToComfyUI(imgBuf, uploadName);
            const fallbackModel = await detectBestModel();
            if (!fallbackModel) {
                return res.status(500).json({
                    error: 'Wizard Guild unreachable AND no SDXL fallback checkpoint found on ComfyUI. Start the Guild, or install at least one generative model.',
                });
            }
            const workflow = buildAnimationWorkflow(
                uploadName, effectivePrompt, length || 8, fallbackModel);
            const result = await dispatchWorkflow(workflow, 300000);
            res.json({
                status: 'ok',
                engine: 'legacy',
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
            const safeChar = _safeNameOrNull(character_name);
            const safeEmotion = _safeNameOrNull(emotion, { maxLen: 32 });
            if (!safeChar) return res.status(400).json({ error: 'character_name contains unsafe characters' });
            if (!safeEmotion) return res.status(400).json({ error: 'emotion contains unsafe characters' });
            const bad = _rejectOversizedB64(image_base64);
            if (bad) return res.status(413).json(bad);

            // ST stores expressions at: data/default-user/characters/<CharName>/
            const charDir = resolveCharactersDir();
            if (!charDir) {
                return res.status(500).json({ error: 'Cannot find SillyTavern characters directory' });
            }

            // Expression sprites go in a subfolder named after the character
            const exprDir = path.join(charDir, safeChar);
            // Defense-in-depth: ensure resolved path stays under charDir.
            const resolvedExprDir = path.resolve(exprDir);
            if (!resolvedExprDir.startsWith(path.resolve(charDir) + path.sep)
                && resolvedExprDir !== path.resolve(charDir)) {
                return res.status(400).json({ error: 'character_name escapes characters directory' });
            }
            if (!fs.existsSync(exprDir)) {
                fs.mkdirSync(exprDir, { recursive: true });
            }

            const exprPath = path.join(exprDir, `${safeEmotion}.png`);
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
            const desc = _capPrompt(description);
            // Klein portrait prompts are conversational; SDXL gets the
            // photographic-studio tag trailer it needs.
            const kleinPrompt = `${desc}, portrait photograph, 85mm lens, shallow depth of field, studio lighting, detailed face`;
            const sdxlPrompt  = `${desc}, portrait photograph, 85mm lens, shallow depth of field, studio lighting, professional headshot, detailed face, 8k`;
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
                    _roundMod(width || 400, 8, 256),
                    _roundMod(height || 600, 8, 256),
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
            const b64Bad = _rejectOversizedB64(avatar_base64);
            if (b64Bad) return res.status(413).json(b64Bad);

            // Sanitize name for filesystem
            const safeName = String(character_name).replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 30);
            if (!safeName) {
                return res.status(400).json({ error: 'character_name has no usable characters' });
            }
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

            const bodyPrompt = _capPrompt(description) || _capPrompt(attire) ||
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

            const sceneDesc = _capPrompt(description);
            if (charsToComposite.length > 0) {
                // Generate scene with characters
                const workflow = buildSceneCompositeWorkflow(sceneDesc, charsToComposite, model);
                result = await dispatchWorkflow(workflow, 300000);
            } else {
                // No characters — just generate the scene
                const promptText = `${sceneDesc}, cinematic scene, atmospheric, 8k`;
                const negative = 'people, characters, faces, text, watermark, blurry, low quality';
                const workflow = buildTxt2ImgWorkflow(
                    promptText, negative,
                    _roundMod(width || 1280, 8, 256),
                    _roundMod(height || 720, 8, 256),
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
    // Disabled by default — arbitrary workflow submission lets a caller
    // instruct ComfyUI to load/save any file the server can reach. Set
    // SPELLCASTER_ALLOW_DISPATCH=1 in the ST process env to re-enable.
    router.post('/dispatch', async (req, res) => {
        if (process.env.SPELLCASTER_ALLOW_DISPATCH !== '1') {
            return res.status(403).json({
                error: 'raw /dispatch is disabled. Set SPELLCASTER_ALLOW_DISPATCH=1 to enable.',
            });
        }
        try {
            const { workflow, timeout } = req.body;
            if (!workflow) return res.status(400).json({ error: 'workflow required' });
            if (typeof workflow !== 'object' || Array.isArray(workflow)) {
                return res.status(400).json({ error: 'workflow must be an object' });
            }
            const approxSize = JSON.stringify(workflow).length;
            if (approxSize > 2 * 1024 * 1024) {
                return res.status(413).json({ error: `workflow too large (${approxSize} chars)` });
            }
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
let _cachedModelUrl = null;
let _cachedModelTs = 0;
// Caches for ComfyUI introspection are invalidated on /settings URL
// change AND after MODEL_CACHE_TTL_MS so a ComfyUI model-swap without
// a /settings roundtrip still gets picked up within a few minutes.
const MODEL_CACHE_TTL_MS = 5 * 60 * 1000;

async function detectBestModel() {
    const fresh = _cachedModel
        && _cachedModelUrl === COMFYUI_URL
        && (Date.now() - _cachedModelTs) < MODEL_CACHE_TTL_MS;
    if (fresh) return _cachedModel;
    try {
        const res = await fetchJSON(`${COMFYUI_URL}/object_info/CheckpointLoaderSimple`);
        const ckpts = res.data?.CheckpointLoaderSimple?.input?.required?.ckpt_name?.[0] || [];
        // Prefer: flux > xl > juggernaut > anything
        const priorities = ['flux', 'xl', 'jugger', 'reborn', 'realistic'];
        const pick = (m) => {
            _cachedModel = m;
            _cachedModelUrl = COMFYUI_URL;
            _cachedModelTs = Date.now();
            return m;
        };
        for (const kw of priorities) {
            const match = ckpts.find(c => c.toLowerCase().includes(kw));
            if (match) return pick(match);
        }
        if (ckpts.length > 0) return pick(ckpts[0]);
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
// Clamps to [minV, maxV] so a caller-supplied 1e9 can't reach the
// allocator with a massive latent size.
function _roundMod(n, mod = 16, minV = 64, maxV = 2048) {
    const bounded = Math.min(maxV, Math.max(minV, Math.round(Number(n) / mod) * mod));
    return Number.isFinite(bounded) ? bounded : minV;
}

// Prompt-text clamp used on every endpoint that forwards a prompt
// string into a workflow. 4 kB is far past any model's effective
// context window, and this keeps a bad caller from posting megabytes
// of text to ComfyUI.
function _capPrompt(s, maxLen = 4000) {
    if (s == null) return '';
    const str = String(s);
    return str.length > maxLen ? str.slice(0, maxLen) : str;
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
let _cachedEditEngineTs = 0;

async function detectEditEngine() {
    const fresh = _cachedEditEngine
        && _cachedEditEngineUrl === COMFYUI_URL
        && (Date.now() - _cachedEditEngineTs) < MODEL_CACHE_TTL_MS;
    if (fresh) return _cachedEditEngine;
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
        _cachedEditEngineTs = Date.now();
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
//  WAN 2.2 I2V / LTX 2.3 — via Wizard Guild's /api/video/shots
// ═══════════════════════════════════════════════════════════════════
//
// Per CLAUDE.md §16.4: SillyTavern (JS, can't import spellcaster_core)
// does NOT hand-roll WAN/LTX workflow JSON. The canon — preset
// detection, VAE pairing, turbo vs HQ formula, subtitle burn-in
// negative, STG layers, mod-16 rounding — all lives in
// spellcaster_core.video_presets + spellcaster_core.workflows (Python).
// The Guild wraps that canon behind /api/video/shots endpoints.
//
// This JS path talks to the Guild only:
//   1. POST /api/video/shots                  → draft shot, returns id
//   2. POST /api/video/shots/<id>/reference   → attach the reference PNG
//   3. POST /api/video/shots/<id>/render      → start the render
//   4. GET  /api/video/shots                  → poll until status=ready
//   5. GET  /api/video/shots/<id>/video       → download the MP4/GIF
//
// If any step fails the caller (/animate) falls back to the local
// SDXL noise-injection path — still a last-resort preview for users
// without the Guild, but clearly labeled as "engine=legacy" in the
// response.

async function _animateViaGuild({ image_base64, prompt, preset }) {
    if (!GUILD_URL) throw new Error('GUILD_URL not configured');
    // Step 1: create a draft shot.
    const createResp = await fetchJSON(`${GUILD_URL}/api/video/shots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            title: `SillyTavern animate ${new Date().toISOString()}`,
            prompt,
            negative: '',
            preset,
        }),
    });
    if (createResp.status !== 200) {
        throw new Error(`Guild refused shot creation: HTTP ${createResp.status}`);
    }
    const shot = createResp.data || {};
    const shotId = shot.id || shot.shot_id;
    if (!shotId) throw new Error('Guild returned no shot id');

    // Step 2: attach the reference frame. The Guild expects either a
    // data URL or raw base64 in `image_data`; pass the plain b64 so
    // ST clients that forwarded a data-url already stripped work too.
    const refResp = await fetchJSON(
        `${GUILD_URL}/api/video/shots/${shotId}/reference`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_data: image_base64 }),
        });
    if (refResp.status !== 200) {
        throw new Error(`Guild refused reference upload: HTTP ${refResp.status}`);
    }

    // Step 3: render.
    const renderResp = await fetchJSON(
        `${GUILD_URL}/api/video/shots/${shotId}/render`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
        });
    if (renderResp.status !== 200) {
        throw new Error(`Guild refused render: HTTP ${renderResp.status}`);
    }

    // Step 4: poll until ready or failed. WAN 2.2 I2V on a single GPU
    // takes 30-180s; 10-minute ceiling covers slow servers + queue.
    const deadline = Date.now() + 10 * 60 * 1000;
    let status = 'queued';
    while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 2000));
        const listResp = await fetchJSON(`${GUILD_URL}/api/video/shots`);
        const shots = (listResp.data && listResp.data.shots) || [];
        const current = shots.find(s => s.id === shotId);
        status = current ? (current.status || 'unknown') : 'missing';
        if (status === 'ready') break;
        if (status === 'failed' || status === 'missing') {
            throw new Error(`Guild shot ${shotId} status=${status}`);
        }
    }
    if (status !== 'ready') {
        throw new Error(`Guild shot ${shotId} timed out in status=${status}`);
    }

    // Step 5: fetch the rendered video.
    const videoBuf = await fetchBytes(
        `${GUILD_URL}/api/video/shots/${shotId}/video`,
        { maxBytes: 200 * 1024 * 1024, timeoutMs: 60000 });
    return {
        engine: `guild:${preset}`,
        shot_id: shotId,
        videos: [{ base64: videoBuf.toString('base64'), filename: `${shotId}.mp4` }],
    };
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
