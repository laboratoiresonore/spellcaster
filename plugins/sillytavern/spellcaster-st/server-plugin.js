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
        const req = mod.request(url, { method: options.method || 'GET', ...options }, (res) => {
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
        if (req.body.backgrounds_dir) {
            BG_DIR = req.body.backgrounds_dir;
        }
        autoDetectBgDir();  // Auto-detect if not explicitly set
        res.json({ status: 'ok', comfyui_url: COMFYUI_URL, bg_dir: BG_DIR });
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
            if (!f