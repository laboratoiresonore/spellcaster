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
                        const url = `${COMFYUI_URL}/view?filename=${fn}&type=output${sub ? '&subfolder=' + sub : ''}`;
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
                        const url = `${COMFYUI_URL}/view?filename=${fn}&type=output${sub ? '&subfolder=' + sub : ''}`;
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
            COMFYUI_URL = req.body.comfyui_url.replace(/\/+$/, '');
        }
        if (req.body.backgrounds_dir) {
            BG_DIR = req.body.backgrounds_dir;
        }
        res.json({ status: 'ok', comfyui_url: COMFYUI_URL });
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

    // ── Generate animated moment (video) ──
    router.post('/animate', async (req, res) => {
        try {
            const { image_base64, prompt, length } = req.body;
            if (!image_base64) return res.status(400).json({ error: 'image_base64 required' });

            const imgBuf = Buffer.from(image_base64, 'base64');
            const uploadName = `spellcaster_anim_${Date.now()}.png`;
            await uploadToComfyUI(imgBuf, uploadName);

            // Use LTX i2v for animation (simpler, wider compatibility)
            const workflow = buildLtxI2VWorkflow(
                uploadName,
                prompt || 'subtle animation, gentle movement',
                length || 25
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

function buildLtxI2VWorkflow(imageName, prompt, numFrames) {
    // Simplified LTX I2V — full version uses the Python builder
    return {
        "1": { "class_type": "LoadImage", "inputs": { "image": imageName }},
        "9": { "class_type": "SaveImage", "inputs": {
            "filename_prefix": "Spellcaster_ST_anim", "images": ["1", 0]
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
