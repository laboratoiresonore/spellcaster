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

// Wizard-provisioned defaults. Mirror the three settings the ST-side
// wizard writes so downstream workflow builders can read them. Empty
// string on IMAGE_MODEL means "let getBestModel() auto-pick" (the
// pre-wizard behaviour, preserved when no wizard choice was made).
let SPELLCASTER_IMAGE_MODEL = '';
let SPELLCASTER_VIDEO_BACKEND = 'auto';   // 'auto' | 'wan22' | 'none'
let SPELLCASTER_QUALITY_PROFILE = 'balanced'; // 'fast' | 'balanced' | 'max'

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
 *
 * Bounded by default:
 *   - timeoutMs: 30 s on the whole request. A stalled ComfyUI or Guild
 *     used to hang this call forever; the poll loops in dispatchWorkflow
 *     and _animateViaGuild then accumulated one zombie socket per
 *     pending generation.
 *   - maxBytes: 50 MB hard ceiling. ComfyUI's /object_info can run 1–5 MB;
 *     a runaway or malicious server could otherwise stream unbounded data
 *     into the ST process.
 */
const FETCH_JSON_MAX_BYTES = 50 * 1024 * 1024;
const FETCH_JSON_TIMEOUT_MS = 30000;
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
        const maxBytes = options.maxBytes || FETCH_JSON_MAX_BYTES;
        const timeoutMs = options.timeoutMs || FETCH_JSON_TIMEOUT_MS;
        const req = mod.request(reqOpts, (res) => {
            const chunks = [];
            let total = 0;
            let aborted = false;
            res.on('data', chunk => {
                total += chunk.length;
                if (total > maxBytes) {
                    if (!aborted) {
                        aborted = true;
                        req.destroy(new Error(`response exceeded ${maxBytes} bytes`));
                    }
                    return;
                }
                chunks.push(chunk);
            });
            res.on('end', () => {
                if (aborted) return;
                const data = Buffer.concat(chunks).toString('utf8');
                try { resolve({ status: res.statusCode, data: JSON.parse(data) }); }
                catch { resolve({ status: res.statusCode, data: data }); }
            });
            res.on('error', reject);
        });
        req.on('error', reject);
        req.setTimeout(timeoutMs, () => req.destroy(new Error(`fetchJSON timeout after ${timeoutMs}ms`)));
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
 * Stash generated bytes in the Guild's AssetGallery and return a
 * canonical ``/api/assets/<hash>`` URL. Used in place of the raw
 * ComfyUI ``/view?filename=...`` URL so cross-interface subscribers
 * can see ST-originated generations and so the URL keeps working
 * after ComfyUI's privacy cleanup runs.
 *
 * Returns ``{ hash, url }`` on success or ``null`` on ANY failure —
 * the caller falls back to the raw ComfyUI URL in that case so
 * generations still reach the chat even when the Guild is offline.
 *
 * Do NOT throw from here; the dispatchWorkflow loop must keep
 * running regardless of backbone availability.
 */
async function guildStashGeneration(bytes, { kind, title, prompt, model, seed, tags, meta }) {
    if (!bytes || !bytes.length || !GUILD_URL) return null;
    try {
        const up = await fetchJSON(`${GUILD_URL}/api/assets`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                origin: 'sillytavern',
                kind: kind || 'generation',
                title: title || '',
                prompt: prompt || null,
                model: model || null,
                seed: (seed === undefined || seed === null) ? null : seed,
                tags: Array.isArray(tags) ? tags : [],
                meta: meta || {},
                body_b64: bytes.toString('base64'),
            }),
        });
        const rec = up && up.data;
        if (!rec || !rec.hash) return null;
        return {
            hash: rec.hash,
            url: `${GUILD_URL}/api/assets/${rec.hash}`,
        };
    } catch (e) {
        return null;
    }
}


/**
 * Submit a workflow to ComfyUI and poll for the result.
 * Returns { images: [base64...], videos: [base64...] } or throws.
 */
async function dispatchWorkflow(workflow, timeoutMs = 180000, {
    stashMeta = null,
} = {}) {
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
                        const comfyUrl = `${COMFYUI_URL}/view?filename=${fn}&type=${imgType}${sub ? '&subfolder=' + sub : ''}`;
                        const bytes = await fetchBytes(comfyUrl);
                        // Canonical: stash in Guild AssetGallery so
                        // cross-interface subscribers see the gen and
                        // so the URL survives ComfyUI privacy cleanup.
                        // Fall back to the raw /view URL only when the
                        // Guild is unreachable — the chat still renders.
                        const stashed = await guildStashGeneration(bytes, {
                            kind: 'generation',
                            title: stashMeta?.title || fn,
                            prompt: stashMeta?.prompt,
                            model: stashMeta?.model,
                            seed: stashMeta?.seed,
                            tags: stashMeta?.tags || ['sillytavern_chat'],
                            meta: { source_node: nid, filename: fn, subfolder: sub },
                        });
                        result.images.push({
                            base64: bytes.toString('base64'),
                            filename: fn,
                            url: stashed ? stashed.url : comfyUrl,
                            hash: stashed ? stashed.hash : null,
                        });
                    }
                }
                if (nodeOut.gifs) {
                    for (const gif of nodeOut.gifs) {
                        const fn = gif.filename;
                        const sub = gif.subfolder || '';
                        const gifType = gif.type || 'output';
                        const comfyUrl = `${COMFYUI_URL}/view?filename=${fn}&type=${gifType}${sub ? '&subfolder=' + sub : ''}`;
                        const bytes = await fetchBytes(comfyUrl);
                        const stashed = await guildStashGeneration(bytes, {
                            kind: 'video',
                            title: stashMeta?.title || fn,
                            prompt: stashMeta?.prompt,
                            model: stashMeta?.model,
                            seed: stashMeta?.seed,
                            tags: stashMeta?.tags || ['sillytavern_chat'],
                            meta: { source_node: nid, filename: fn, subfolder: sub },
                        });
                        result.videos.push({
                            base64: bytes.toString('base64'),
                            filename: fn,
                            url: stashed ? stashed.url : comfyUrl,
                            hash: stashed ? stashed.hash : null,
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
        // Wizard-provisioned defaults. Whitelist enum fields; validate the
        // free-form checkpoint filename for shape only — we can't confirm
        // presence without a /object_info round-trip and won't block on
        // that here (the request may beat a ComfyUI cold-start).
        if (Object.prototype.hasOwnProperty.call(req.body, 'image_model')) {
            const raw = String(req.body.image_model || '').trim();
            // Empty string = auto-pick. A filename may legitimately carry
            // a subfolder prefix but must not traverse upward.
            if (raw && /\.\.[\\/]/.test(raw)) {
                return res.status(400).json({
                    error: 'image_model: path traversal not allowed',
                });
            }
            SPELLCASTER_IMAGE_MODEL = raw;
        }
        if (Object.prototype.hasOwnProperty.call(req.body, 'video_backend')) {
            const raw = String(req.body.video_backend || 'auto').trim();
            if (!['auto', 'wan22', 'none'].includes(raw)) {
                return res.status(400).json({
                    error: "video_backend must be 'auto', 'wan22', or 'none'",
                });
            }
            SPELLCASTER_VIDEO_BACKEND = raw;
        }
        if (Object.prototype.hasOwnProperty.call(req.body, 'quality_profile')) {
            const raw = String(req.body.quality_profile || 'balanced').trim();
            if (!['fast', 'balanced', 'max'].includes(raw)) {
                return res.status(400).json({
                    error: "quality_profile must be 'fast', 'balanced', or 'max'",
                });
            }
            SPELLCASTER_QUALITY_PROFILE = raw;
        }
        autoDetectBgDir();
        res.json({
            status: 'ok',
            comfyui_url:     COMFYUI_URL,
            guild_url:       GUILD_URL,
            bg_dir:          BG_DIR,
            image_model:     SPELLCASTER_IMAGE_MODEL,
            video_backend:   SPELLCASTER_VIDEO_BACKEND,
            quality_profile: SPELLCASTER_QUALITY_PROFILE,
        });
    });

    // GET /models — group /object_info's checkpoint + UNET lists by
    // architecture + report which video backends are installed. Used
    // by the first-run wizard's image-model + video-backend pickers.
    router.get('/models', async (req, res) => {
        let catalog;
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
            return res.status(502).json({ error: 'unexpected /object_info shape' });
        }
        const ckpts = catalog?.CheckpointLoaderSimple?.input?.required?.ckpt_name?.[0] || [];
        const unets = catalog?.UNETLoader?.input?.required?.unet_name?.[0] || [];
        // Filename-heuristic arch classification. Keys match the
        // comfyui-spellcaster arch registry so a wizard round-trip
        // survives unchanged through the workflow builders.
        const groups = {
            klein9b: [], klein4b: [], fluxkontext: [],
            flux1dev: [], sdxl: [], illustrious: [], sd15: [],
            zit: [], chroma: [],
        };
        const bucket = (name, isUnet) => {
            const n = String(name).toLowerCase();
            if (n.includes('klein')) {
                if (n.includes('9b')) return 'klein9b';
                if (n.includes('4b')) return 'klein4b';
                return 'klein9b';
            }
            if (n.includes('kontext')) return 'fluxkontext';
            if (isUnet && (n.includes('flux') || n.includes('flux1'))) return 'flux1dev';
            if (n.includes('chroma')) return 'chroma';
            if (n.includes('z-image') || n.includes('z_image') || n.includes('zimage')
                || n.includes('turbo-z') || n.includes('zit')) return 'zit';
            if (n.includes('illust') || n.includes('pony') || n.includes('noobai')) return 'illustrious';
            if (n.includes('sdxl') || n.includes('xl') || n.includes('jugger')
                || n.includes('realistic') || n.includes('zavy')) return 'sdxl';
            if (n.includes('sd15') || n.includes('sd-15') || n.includes('1.5')) return 'sd15';
            // Default: treat as SDXL checkpoint (most common untagged case).
            // UNETs without identifying markers go uncategorized rather than
            // dumped into sdxl — UNETs are arch-specific and misfiling is
            // louder there.
            return isUnet ? null : 'sdxl';
        };
        for (const c of ckpts) {
            const k = bucket(c, false);
            if (k) groups[k].push(c);
        }
        for (const u of unets) {
            const k = bucket(u, true);
            if (k) groups[k].push(u);
        }
        const image = {};
        for (const [k, v] of Object.entries(groups)) {
            if (v.length) image[k] = v.sort();
        }
        const nodes = new Set(Object.keys(catalog));
        const video = {
            wan: nodes.has('WanImageToVideo') || nodes.has('LoadWanVideoModel'),
            ltx: nodes.has('LTXVImgToVideo'),
        };
        res.json({ comfyui: COMFYUI_URL, image, video });
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
            // Scheme clamp: only accept `data:image/...` URLs. Without this
            // a caller could hand in `data:text/html;base64,...` which the
            // Guild would dutifully store + publish — a downstream plugin
            // that rendered the bytes without sniffing could then execute
            // HTML/JS. Also rejects `javascript:` pseudo-URLs.
            if (!/^data:image\/[a-zA-Z0-9.+-]+(;[a-zA-Z0-9=-]+)*,/i.test(dataUrl)) {
                return res.status(400).json({
                    error: 'image_data_url must be data:image/<type>[;...],<payload>',
                });
            }
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

    // GET /cross/events — server-sent-events proxy to the Guild's
    // /api/events/stream. The browser EventSource can't hit
    // 127.0.0.1:7777 directly on every ST deploy (mixed-content rules,
    // CSP, cross-origin quirks), so ST's server plugin proxies it here
    // on the same origin. Only sillytavern.asset.* kinds are forwarded
    // to keep the client-side filter cheap.
    //
    // Client usage:
    //   const es = new EventSource('/api/plugins/spellcaster/cross/events');
    //   es.addEventListener('sillytavern.asset.send', (ev) => {...});
    //
    // Falls back to a one-shot 503 if the Guild is unreachable — the
    // browser's `es.onerror` fires and the client can fall back to the
    // legacy /cross/inbox poll.
    router.get('/cross/events', (req, res) => {
        const mod = GUILD_URL.startsWith('https') ? https : http;
        let parsed;
        try { parsed = new URL(`${GUILD_URL}/api/events/stream?kinds=sillytavern.asset.`); }
        catch { return res.status(400).end(); }
        const upstream = mod.request({
            hostname: parsed.hostname,
            port: parsed.port,
            path: parsed.pathname + parsed.search,
            method: 'GET',
            headers: { 'Accept': 'text/event-stream' },
        }, (upRes) => {
            if (upRes.statusCode !== 200) {
                res.status(502).end();
                upRes.resume();
                return;
            }
            res.writeHead(200, {
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache, no-transform',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',   // defeat nginx buffering if ST is behind one
            });
            // Initial comment so the browser knows the connection is live.
            res.write(': spellcaster-sse-ready\n\n');
            upRes.on('data', chunk => {
                if (!res.writableEnded) res.write(chunk);
            });
            upRes.on('end', () => { if (!res.writableEnded) res.end(); });
            upRes.on('error', () => { if (!res.writableEnded) res.end(); });
        });
        upstream.on('error', () => {
            if (!res.headersSent) res.status(502).end();
            else if (!res.writableEnded) res.end();
        });
        // Client went away — tear down the upstream to avoid a zombie
        // long-poll against the Guild.
        req.on('close', () => {
            try { upstream.destroy(); } catch { /* already closed */ }
        });
        upstream.end();
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

            // Wizard gate — if the user explicitly disabled video, refuse
            // without burning ComfyUI queue time on a job they don't want.
            // Explicit body.engine overrides the gate (escape hatch for
            // power users).
            if (SPELLCASTER_VIDEO_BACKEND === 'none' && !engine) {
                return res.status(403).json({
                    error: 'Video backend disabled in Spellcaster wizard. Re-run /spellcaster-wizard or pass engine="legacy" to override.',
                });
            }

            const wantLegacy = engine === "legacy";
            const effectivePrompt = String(prompt || 'subtle breathing, gentle movement, living portrait').slice(0, 2000);

            // Try the canonical Guild path first.
            if (!wantLegacy) {
                try {
                    // Preset order of precedence:
                    //   1. Explicit body.engine ('ltx' | 'wan22' assumed via turbo)
                    //   2. Wizard-selected backend (video_backend === 'wan22')
                    //   3. Default: turbo ? lightning : hq
                    const forceWan = SPELLCASTER_VIDEO_BACKEND === 'wan22';
                    const preset = (engine === "ltx")
                        ? 'ltx_distilled'
                        : (forceWan || turbo ? 'wan22_i2v_lightning' : 'wan22_i2v_hq');
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

    // ── List currently-running /animate shots ──
    // Used by the `/animate-cancel` slash command so the client can
    // pick a shot to cancel without having to remember its id.
    router.get('/animate/active', (req, res) => {
        const active = [];
        for (const [id, info] of _activeAnimateShots.entries()) {
            active.push({
                shot_id: id,
                started_at: info.startedAt,
                cancelled: !!info.cancelled,
                age_seconds: Math.round((Date.now() - info.startedAt) / 1000),
            });
        }
        res.json({ active });
    });

    // ── Cancel an in-flight /animate shot ──
    // Flips the tracker's cancelled flag so the next poll tick of
    // _animateViaGuild breaks out, AND forwards a cancel to the Guild
    // so the backend stops rendering too. If shot_id is omitted, cancels
    // every in-flight animation — useful when the user doesn't know which
    // one they triggered.
    router.post('/animate/cancel', async (req, res) => {
        const ids = [];
        const want = req.body && req.body.shot_id;
        if (want) {
            if (_activeAnimateShots.has(want)) ids.push(want);
        } else {
            for (const k of _activeAnimateShots.keys()) ids.push(k);
        }
        if (!ids.length) return res.status(404).json({ error: 'no active animate shot' });
        const results = [];
        for (const id of ids) {
            // Local flag first — this bounds the worst-case wait to
            // one poll tick (~2 s).
            const tracked = _activeAnimateShots.get(id);
            if (tracked) tracked.cancelled = true;
            // Then forward to the Guild so the backend actually stops.
            let guildCode = 0;
            try {
                const r = await fetchJSON(
                    `${GUILD_URL}/api/video/shots/${id}/cancel`,
                    { method: 'POST', headers: { 'Content-Type': 'application/json' },
                      body: '{}', timeoutMs: 5000 });
                guildCode = r.status || 0;
            } catch { /* best-effort */ }
            results.push({ shot_id: id, local_flagged: !!tracked, guild_status: guildCode });
        }
        res.json({ cancelled: results });
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

    // ── Presence: list alive peers ──────────────────────────────────
    // Browser-side UI (e.g., cross-send slash commands) calls this on
    // menu render to decide which /sc-send-to-* chips to offer.
    router.get('/peers', async (req, res) => {
        try {
            const peers = await getPeerList();
            res.json({ peers });
        } catch (e) {
            res.status(500).json({ error: e.message });
        }
    });

    // ── Presence: register this ST instance with peers ──────────────
    // Both ComfyUI-Spellcaster's /spellcaster/presence/* routes AND
    // (if running) the Wizard Guild's /api/interfaces/heartbeat. Zero-
    // config cross-app discovery: when another plugin queries the
    // presence list, ST shows up without the user configuring
    // anything. See AUDIT_CROSS_APP_DISCOVERY.md §6.5.
    _startPresenceHeartbeat();

    console.log('[Spellcaster] Server plugin loaded. ComfyUI:', COMFYUI_URL);
}

// ═══════════════════════════════════════════════════════════════════
//  Cross-app presence (phase-9)
// ═══════════════════════════════════════════════════════════════════

// Short, LAN-safe hostname so the same plugin kind coexists on
// different machines. The broker derives instance_id from key@host when
// we don't supply one; we set both explicitly for clarity.
const _ST_HOST = (() => {
    try {
        const os = require('os');
        const raw = (os.hostname() || '').trim().split('.')[0].slice(0, 64);
        const cleaned = raw.replace(/[^a-zA-Z0-9_-]/g, '');
        return cleaned || 'st-host';
    } catch { return 'st-host'; }
})();

const _ST_PRESENCE = {
    key: 'sillytavern',
    label: 'SillyTavern',
    icon: '🎭',
    version: '2.0.0',
    capabilities: ['chat', 'send_image', 'receive_image', 'roleplay'],
    host: _ST_HOST,
    instance_id: `sillytavern@${_ST_HOST}`,
};

let _stPresenceTimer = null;

async function _presencePost(baseUrl, path, body, timeoutMs = 5000) {
    try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), timeoutMs);
        try {
            await fetch(`${baseUrl}${path}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: ctrl.signal,
            });
        } finally { clearTimeout(t); }
    } catch { /* best-effort, silent */ }
}

async function _heartbeatOnce() {
    const body = { ..._ST_PRESENCE };
    // Pack: ComfyUI-Spellcaster /spellcaster/presence/*. Primary path —
    // works even when the Guild is offline, which is the whole point.
    await _presencePost(COMFYUI_URL, '/spellcaster/presence/heartbeat', body);
    // Guild /api/interfaces/heartbeat — richer metadata; best-effort.
    // Shape is slightly different (interface= instead of key=) — the
    // Guild endpoint pre-dates the presence broker.
    await _presencePost(GUILD_URL, '/api/interfaces/heartbeat', {
        interface: _ST_PRESENCE.key,
        meta: {
            label: _ST_PRESENCE.label,
            capabilities: _ST_PRESENCE.capabilities,
            version: _ST_PRESENCE.version,
        },
    });
}

function _startPresenceHeartbeat() {
    // One-shot register first (presence broker auto-registers on
    // heartbeat too, but the explicit /register sets the label +
    // capabilities cleanly).
    _presencePost(COMFYUI_URL, '/spellcaster/presence/register', {
        ..._ST_PRESENCE,
    }).catch(() => {});
    // Immediate heartbeat so peers see us right away.
    _heartbeatOnce().catch(() => {});
    // Then every 20 s (under the 45 s default TTL so one miss is OK).
    if (_stPresenceTimer) clearInterval(_stPresenceTimer);
    _stPresenceTimer = setInterval(() => _heartbeatOnce().catch(() => {}), 20_000);
    // Don't pin Node's event loop open for the heartbeat timer alone.
    if (_stPresenceTimer.unref) _stPresenceTimer.unref();
}

// Query the union of both presence surfaces. Returns a deduped list;
// when the same key appears in both, prefer the Guild's richer record
// (has online_local / online_remote distinction via antennas).
async function getPeerList() {
    const seen = new Map();
    // 1) ComfyUI-Spellcaster — the baseline, always present when this
    //    plugin is installed (the pack is a hard dep for image gen).
    try {
        const r = await fetch(`${COMFYUI_URL}/spellcaster/presence/list`);
        if (r.ok) {
            const data = await r.json();
            for (const p of data.peers || []) {
                // Dedup by instance_id so multiple machines running the
                // same plugin kind all stay visible; only hide OUR own
                // instance_id.
                const inst = p.instance_id || p.key;
                if (inst && inst !== _ST_PRESENCE.instance_id) {
                    seen.set(inst, p);
                }
            }
        }
    } catch { /* pack too old or ComfyUI down */ }
    // 2) Guild — richer record when it's running; overwrites the
    //    pack's entry for the same key (Guild knows online_local etc.).
    try {
        const r = await fetch(`${GUILD_URL}/api/interfaces`);
        if (r.ok) {
            const data = await r.json();
            const ifaces = data.interfaces || {};
            for (const [key, info] of Object.entries(ifaces)) {
                if (key === _ST_PRESENCE.key) continue;
                if (!info || info.online === false) continue;
                seen.set(key, {
                    key,
                    label: info.ui_label || key,
                    icon: info.icon || '',
                    capabilities: info.capabilities || [],
                    age_s: Math.max(0, Math.round(Date.now()/1000 - (info.last_heartbeat || 0))),
                    source: 'guild',
                });
            }
        }
    } catch { /* Guild off, that's fine */ }
    return [...seen.values()];
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
        const pick = (m) => {
            _cachedModel = m;
            _cachedModelUrl = COMFYUI_URL;
            _cachedModelTs = Date.now();
            return m;
        };
        // Wizard override — if the user picked a specific checkpoint AND
        // ComfyUI still has it, honour the choice. Otherwise log and fall
        // through to the keyword-priority heuristic so we never break
        // generation because a user renamed a file.
        if (SPELLCASTER_IMAGE_MODEL && ckpts.includes(SPELLCASTER_IMAGE_MODEL)) {
            return pick(SPELLCASTER_IMAGE_MODEL);
        }
        if (SPELLCASTER_IMAGE_MODEL) {
            console.warn(`[Spellcaster] Wizard-selected image_model not present on ComfyUI: ${SPELLCASTER_IMAGE_MODEL} — auto-picking fallback.`);
        }
        // Prefer: flux > xl > juggernaut > anything
        const priorities = ['flux', 'xl', 'jugger', 'reborn', 'realistic'];
        for (const kw of priorities) {
            const match = ckpts.find(c => c.toLowerCase().includes(kw));
            if (match) return pick(match);
        }
        if (ckpts.length > 0) return pick(ckpts[0]);
    } catch { /* fallback */ }
    return null;
}

// Maps the wizard's quality_profile + architecture label onto a
// (steps, cfg) tuple. JS-side builders are much thinner than the
// Python workflow graph builders, so "quality" here is a coarse
// adjustment rather than a full PAG/RescaleCFG stack. Keep the
// arch-specific tuning in one place so the plain builders don't
// each need their own quality switch.
function qualityAdjust(baseSteps, baseCfg, arch = 'sdxl') {
    const profile = SPELLCASTER_QUALITY_PROFILE || 'balanced';
    if (profile === 'balanced') return { steps: baseSteps, cfg: baseCfg };

    // Klein is a distilled 4-step model — never change its step count
    // (raising wastes compute, lowering breaks output). Only CFG moves.
    if (arch === 'klein9b' || arch === 'klein4b') {
        if (profile === 'max')  return { steps: baseSteps, cfg: Math.min(baseCfg + 0.5, 3.5) };
        if (profile === 'fast') return { steps: baseSteps, cfg: baseCfg };
    }
    // Kontext edits — mild movement
    if (arch === 'kontext') {
        if (profile === 'max')  return { steps: Math.round(baseSteps * 1.2), cfg: baseCfg };
        if (profile === 'fast') return { steps: Math.max(4, Math.round(baseSteps * 0.7)), cfg: baseCfg };
    }
    // SDXL / SD 1.5 / everything else — generic percentage scaling
    if (profile === 'max')  return { steps: Math.round(baseSteps * 1.3), cfg: Math.min(baseCfg + 0.5, 9.0) };
    if (profile === 'fast') return { steps: Math.max(6, Math.round(baseSteps * 0.65)), cfg: Math.max(baseCfg - 0.5, 4.0) };
    return { steps: baseSteps, cfg: baseCfg };
}

// ═══════════════════════════════════════════════════════════════════
//  Workflow Builders (minimal self-contained — no Python dependency)
// ═══════════════════════════════════════════════════════════════════

function buildTxt2ImgWorkflow(prompt, negative, width, height, seed, modelName) {
    const q = qualityAdjust(25, 7.0, 'sdxl');
    return {
        "3": { "class_type": "KSampler", "inputs": {
            "seed": seed, "steps": q.steps, "cfg": q.cfg,
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
    const q = qualityAdjust(25, 7.0, 'sdxl');
    return {
        "1": { "class_type": "LoadImage", "inputs": { "image": imageName }},
        "3": { "class_type": "KSampler", "inputs": {
            "seed": Math.floor(Math.random() * 2147483647),
            "steps": q.steps, "cfg": q.cfg,
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
    const q = qualityAdjust(25, 7.0, 'sdxl');
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
            "seed": seed, "steps": q.steps, "cfg": q.cfg,
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

// In-flight animation shots (shot_id -> { startedAt, cancelled }).
// Populated by _animateViaGuild, drained by the cancel endpoint. Lets
// the /animate slash command surface a cancel action without the
// browser having to manage the shot id itself. Size-capped at 20
// entries so a broken caller can't leak.
const _activeAnimateShots = new Map();
function _trackAnimate(shotId) {
    _activeAnimateShots.set(shotId, { startedAt: Date.now(), cancelled: false });
    // Evict oldest if the map grows (shouldn't happen — each animate
    // cleans itself up in a finally — but defense in depth).
    if (_activeAnimateShots.size > 20) {
        const oldest = [..._activeAnimateShots.keys()][0];
        _activeAnimateShots.delete(oldest);
    }
}
function _untrackAnimate(shotId) {
    _activeAnimateShots.delete(shotId);
}

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
    _trackAnimate(shotId);

    try {
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
        // On each tick, check the cancel flag so POST /animate/cancel
        // can break us out without waiting for the next status poll.
        const deadline = Date.now() + 10 * 60 * 1000;
        let status = 'queued';
        while (Date.now() < deadline) {
            await new Promise(r => setTimeout(r, 2000));
            const tracked = _activeAnimateShots.get(shotId);
            if (tracked && tracked.cancelled) {
                throw new Error(`cancelled by user (shot ${shotId})`);
            }
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
    } finally {
        _untrackAnimate(shotId);
    }
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

// Named exports for the test suite. ST only destructures
// { info, init, exit } from this module, so the additional surface
// here is inert at runtime. Keep in lock-step with the helpers'
// definitions above; the tests in test/ pin their behaviour.
export {
    _rejectOversizedB64,
    _rejectUnsafeUrl,
    _safeNameOrNull,
    _roundMod,
    _capPrompt,
};
